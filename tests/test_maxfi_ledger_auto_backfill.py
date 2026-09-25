"""Ledger-as-source commit 2 - the on-view automatic ledger backfill, the
twin of the metrics auto-refresh (_maybe_kick_metrics_auto_refresh +
_spawn_metrics_refresh_thread) on GET /api/maxfi/advisor.

Rulings under test (Glenn, Sep 25), per chain in MAXFI_CHAINS:
- COVERAGE: an open maxfi_positions row's (chain, token_id) has no
  maxfi_ledger_positions row AND the scanner observed it
  (COALESCE(last_rebalanced_at, first_seen_at)) after the chain's last
  successful real run;
- TIME: no successful real run within ledger_backfill_staleness_hours;
- "last successful real run" = the last-run file with dry_run false, no
  "error" key and a parseable run_at - anything else is stale;
- at most one start per chain per 15 minutes; one daemon thread runs the
  kicked chains sequentially, real runs only, and a failure in one chain
  never stops the next.

No network and no real threads: tests/conftest.py's autouse fixture turns
_spawn_ledger_backfill_thread into a no-op and gives every test a fresh
last-kick map; the trigger tests here swap in a recorder. The last-run
files and the advisor settings file live in tmp_path. The sqlite db/client
fixtures come from tests/test_maxfi_ledger_reconciliation.py (precedent:
tests/test_maxfi_ledger_as_source.py) - underscore helpers and fixtures
only, never a test_* function.

The advisor-route tests also stub _maybe_kick_metrics_auto_refresh: with no
maxfi_pool_metrics row it would start a real DexScreener refresh thread."""
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

import web_portfolio as wp

from test_maxfi_ledger_reconciliation import (  # noqa: F401  (client/db are fixtures)
    _seed_ledger_position,
    _seed_position,
    client,
    db,
)

# The real spawner, captured before conftest's autouse no-op can replace it
# (getattr, so a missing function is a test failure, not a collection error).
_REAL_SPAWN = getattr(wp, "_spawn_ledger_backfill_thread", None)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
ADVISOR_URL = "/api/maxfi/advisor"
SETTINGS_URL = "/api/settings/advisor"


def _iso(dt):
    return dt.isoformat()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """tmp_path settings + last-run files, and a spawn recorder."""
    monkeypatch.setattr(wp, "ADVISOR_SETTINGS_PATH", str(tmp_path / "advisor_settings.json"))
    monkeypatch.setattr(wp, "LEDGER_BACKFILL_LAST_RUN_PATH", str(tmp_path / "ledger_backfill_last_run_{chain}.json"))
    spawned = []
    monkeypatch.setattr(wp, "_spawn_ledger_backfill_thread", lambda chains: spawned.append(list(chains)))

    class Env:
        calls = spawned

        @staticmethod
        def last_run(chain, run_at, dry_run=False, **extra):
            body = dict({"chain": chain, "dry_run": dry_run, "run_at": run_at}, **extra)
            (tmp_path / f"ledger_backfill_last_run_{chain}.json").write_text(json.dumps(body))

        @staticmethod
        def raw_last_run(chain, text):
            (tmp_path / f"ledger_backfill_last_run_{chain}.json").write_text(text)

        @staticmethod
        def settings(**values):
            (tmp_path / "advisor_settings.json").write_text(json.dumps(values))

        @staticmethod
        def fresh_all(hours_ago=1):
            for chain in wp.MAXFI_CHAINS:
                Env.last_run(chain, _iso(NOW - timedelta(hours=hours_ago)))

    return Env


def _open(db, pid, token_id, observed, chain="base", rebalanced=None):
    _seed_position(db, pid, chain=chain, token_id=token_id, first_seen_at=_iso(observed))
    if rebalanced is not None:
        db.execute("UPDATE maxfi_positions SET last_rebalanced_at = ? WHERE id = ?", (_iso(rebalanced), pid))
        db.commit()


def _kick(now=NOW):
    return wp._maybe_kick_ledger_auto_backfill(now_utc=now)


# ── K1-K2: the coverage trigger ────────────────────────────────────────────

def test_k1_missing_token_observed_after_a_fresh_run_starts_its_chain(db, env):
    env.fresh_all()                                         # runs at NOW-1h
    _open(db, 1, "500", NOW - timedelta(minutes=30))        # not in the ledger
    assert _kick() == (["base"], {"base": "coverage"})
    assert env.calls == [["base"]]


def test_k1_last_rebalanced_at_wins_over_first_seen_at(db, env):
    env.fresh_all()
    _open(db, 1, "500", NOW - timedelta(days=30), rebalanced=NOW - timedelta(minutes=5))
    assert _kick() == (["base"], {"base": "coverage"})


def test_k2_missing_token_observed_before_the_fresh_run_starts_nothing(db, env):
    env.fresh_all()
    _open(db, 1, "500", NOW - timedelta(hours=2))           # seen before the NOW-1h run
    assert _kick() == ([], {})
    assert env.calls == []


# ── K3-K7: the time trigger and what counts as a successful run ────────────

def test_k3_covered_tokens_and_a_7h_old_run_start_on_time(db, env):
    env.fresh_all()
    env.last_run("base", _iso(NOW - timedelta(hours=7)))
    _open(db, 1, "100", NOW - timedelta(days=3))
    _seed_ledger_position(db, chain="base", token_id="100")
    assert _kick() == (["base"], {"base": "time"})
    assert env.calls == [["base"]]


def test_k4_fresh_and_fully_covered_starts_nothing(db, env):
    env.fresh_all()
    _open(db, 1, "100", NOW - timedelta(minutes=10))
    _seed_ledger_position(db, chain="base", token_id="100")
    assert _kick() == ([], {})
    assert env.calls == []


def test_k5_no_last_run_file_starts_on_time_and_coverage(db, env):
    env.last_run("robinhood", _iso(NOW - timedelta(hours=1)))
    _open(db, 1, "500", NOW - timedelta(days=3))            # missing, no successful run ever
    assert _kick() == (["base"], {"base": "coverage+time"})


def test_k5_no_last_run_file_with_everything_covered_is_time_only(db, env):
    env.last_run("robinhood", _iso(NOW - timedelta(hours=1)))
    _open(db, 1, "100", NOW - timedelta(days=3))
    _seed_ledger_position(db, chain="base", token_id="100")
    assert _kick() == (["base"], {"base": "time"})


def test_k6_a_fresh_dry_run_counts_as_stale(db, env):
    env.fresh_all()
    env.last_run("base", _iso(NOW - timedelta(minutes=5)), dry_run=True)
    assert _kick() == (["base"], {"base": "time"})


@pytest.mark.parametrize("variant", ["error_key", "bad_run_at", "invalid_json", "missing_run_at"])
def test_k7_unusable_last_run_files_count_as_stale(db, env, variant):
    env.fresh_all()
    if variant == "error_key":
        env.last_run("base", _iso(NOW - timedelta(minutes=5)), error="MaxFiLedgerIngestError")
    elif variant == "bad_run_at":
        env.last_run("base", "not-a-timestamp")
    elif variant == "missing_run_at":
        env.raw_last_run("base", json.dumps({"dry_run": False}))
    else:
        env.raw_last_run("base", "{not json")
    assert _kick() == (["base"], {"base": "time"})


def test_k7_last_successful_run_helper_reads_a_naive_run_at_as_utc(env):
    env.last_run("base", "2026-09-25T10:00:00")
    assert wp._ledger_last_successful_run_at("base") == datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    env.last_run("base", _iso(NOW), dry_run=True)
    assert wp._ledger_last_successful_run_at("base") is None
    assert wp._ledger_last_successful_run_at("robinhood") is None       # no file


# ── K8-K11: cooldown, kill switch, staleness setting, one spawn ────────────

def test_k8_cooldown_blocks_a_second_start_within_15_minutes(db, env):
    env.fresh_all()
    env.last_run("base", _iso(NOW - timedelta(hours=7)))
    assert wp.MAXFI_LEDGER_AUTO_BACKFILL_COOLDOWN_MINUTES == 15
    assert _kick()[0] == ["base"]
    assert _kick(NOW + timedelta(minutes=14)) == ([], {})
    assert _kick(NOW + timedelta(minutes=16)) == (["base"], {"base": "time"})
    assert env.calls == [["base"], ["base"]]


def test_k9_kill_switch_starts_nothing(db, env):
    env.settings(ledger_auto_backfill_enabled=False)
    _open(db, 1, "500", NOW - timedelta(minutes=5))         # both triggers would fire
    assert _kick() == ([], {})
    assert env.calls == []


def test_k10_staleness_hours_setting_is_honoured(db, env):
    env.fresh_all()
    env.last_run("base", _iso(NOW - timedelta(hours=2)))
    env.settings(ledger_backfill_staleness_hours=6.0)
    assert _kick() == ([], {})
    env.settings(ledger_backfill_staleness_hours=1.0)
    assert _kick() == (["base"], {"base": "time"})


def test_k11_both_chains_due_is_one_spawn_in_maxfi_chains_order(db, env):
    _open(db, 1, "500", NOW - timedelta(minutes=5), chain="robinhood")
    kicked, reasons = _kick()
    assert kicked == list(wp.MAXFI_CHAINS)
    assert reasons == {"base": "time", "robinhood": "coverage+time"}
    assert env.calls == [list(wp.MAXFI_CHAINS)]


# ── K12: the worker ────────────────────────────────────────────────────────

class _InlineThread:
    made = []

    def __init__(self, target=None, name=None, daemon=None, **kwargs):
        self.target, self.name, self.daemon = target, name, daemon
        _InlineThread.made.append(self)

    def start(self):
        self.target()


def _run_worker(monkeypatch, behaviours):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        outcome = behaviours[args[0]]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    _InlineThread.made = []
    monkeypatch.setattr(threading, "Thread", _InlineThread)
    monkeypatch.setattr(wp, "_run_ledger_backfill", fake_run)
    assert _REAL_SPAWN is not None, "_spawn_ledger_backfill_thread missing"
    _REAL_SPAWN(list(wp.MAXFI_CHAINS))
    return calls


def test_k12_worker_logs_a_409_and_still_runs_the_next_chain(monkeypatch, capsys):
    calls = _run_worker(monkeypatch, {
        "base": ({"error": "RefreshBusy", "detail": "a ledger backfill is already running"}, 409),
        "robinhood": ({"positions_upserted": 3, "claims_upserted": 5, "pricing_deferred": {}}, 200),
    })
    assert calls == [(("base",), {}), (("robinhood",), {})]    # one real run each, no dry_run
    out = capsys.readouterr().out
    assert "RefreshBusy" in out and "positions_upserted=3" in out and "claims_upserted=5" in out
    assert len(_InlineThread.made) == 1
    assert _InlineThread.made[0].name == "ledger-auto-backfill" and _InlineThread.made[0].daemon is True


def test_k12_worker_logs_an_exception_and_still_runs_the_next_chain(monkeypatch, capsys):
    calls = _run_worker(monkeypatch, {
        "base": RuntimeError("rpc exploded"),
        "robinhood": ({"positions_upserted": 1, "claims_upserted": 0, "pricing_deferred": {}}, 200),
    })
    assert calls == [(("base",), {}), (("robinhood",), {})]
    assert "rpc exploded" in capsys.readouterr().out


# ── K13: settings ──────────────────────────────────────────────────────────

def test_k13_settings_defaults_and_validation(client, env):
    body = client.get(SETTINGS_URL).get_json()
    assert body["ledger_auto_backfill_enabled"] is True
    assert body["ledger_backfill_staleness_hours"] == 6.0
    r = client.post(SETTINGS_URL, json={"ledger_auto_backfill_enabled": False, "ledger_backfill_staleness_hours": 3})
    assert r.status_code == 200
    saved = r.get_json()
    assert saved["ledger_auto_backfill_enabled"] is False and saved["ledger_backfill_staleness_hours"] == 3.0
    for payload, key in [({"ledger_auto_backfill_enabled": "true"}, "ledger_auto_backfill_enabled"),
                         ({"ledger_auto_backfill_enabled": 1}, "ledger_auto_backfill_enabled"),
                         ({"ledger_backfill_staleness_hours": "abc"}, "ledger_backfill_staleness_hours"),
                         ({"ledger_backfill_staleness_hours": 0}, "ledger_backfill_staleness_hours"),
                         ({"ledger_backfill_staleness_hours": -2}, "ledger_backfill_staleness_hours")]:
        r = client.post(SETTINGS_URL, json=payload)
        assert r.status_code == 400, payload
        assert key in r.get_json()["error"], payload


# ── K14-K15: the advisor route ─────────────────────────────────────────────

def _route_scene(db, monkeypatch):
    monkeypatch.setattr(wp, "_maybe_kick_metrics_auto_refresh", lambda: ["base"])   # sentinel, no thread
    _seed_position(db, 1, chain="base", token_id="1")        # open, not in the ledger, no last-run file


def test_k14_advisor_route_reports_the_kick_beside_the_unchanged_keys(client, db, env, monkeypatch):
    _route_scene(db, monkeypatch)
    body = client.get(ADVISOR_URL).get_json()
    assert body["metrics_refresh_kicked"] == ["base"]
    assert body["ledger_backfill_kicked"] == ["base", "robinhood"]
    assert body["ledger_backfill_kick_reasons"] == {"base": "coverage+time", "robinhood": "time"}
    assert body["ledger_backfill_in_flight"] is True
    assert env.calls == [["base", "robinhood"]]

    def _boom(now_utc=None):
        raise RuntimeError("trigger broke")

    monkeypatch.setattr(wp, "_maybe_kick_ledger_auto_backfill", _boom)
    r = client.get(ADVISOR_URL)
    assert r.status_code == 200
    failed = r.get_json()
    assert failed["ledger_backfill_kicked"] == [] and failed["ledger_backfill_kick_reasons"] == {}
    assert failed["ledger_backfill_in_flight"] is False
    assert failed["metrics_refresh_kicked"] == ["base"]
    # the positions payload does not depend on the kick
    assert [p["id"] for p in failed["positions"]] == [p["id"] for p in body["positions"]] == [1]
    assert [sorted(p) for p in failed["positions"]] == [sorted(p) for p in body["positions"]]
    assert [p["verdict"] for p in failed["positions"]] == [p["verdict"] for p in body["positions"]]


def test_k14_in_flight_reflects_a_held_backfill_lock(client, db, env, monkeypatch):
    _route_scene(db, monkeypatch)
    env.settings(ledger_auto_backfill_enabled=False)
    assert client.get(ADVISOR_URL).get_json()["ledger_backfill_in_flight"] is False
    assert wp._LEDGER_BACKFILL_LOCK.acquire(blocking=False)
    try:
        assert client.get(ADVISOR_URL).get_json()["ledger_backfill_in_flight"] is True
    finally:
        wp._LEDGER_BACKFILL_LOCK.release()


def test_k15_conftest_guard_means_no_real_thread_ever_starts(client, db, tmp_path, monkeypatch):
    # No recorder here: conftest's autouse no-op is the spawner in force.
    monkeypatch.setattr(wp, "ADVISOR_SETTINGS_PATH", str(tmp_path / "advisor_settings.json"))
    monkeypatch.setattr(wp, "LEDGER_BACKFILL_LAST_RUN_PATH", str(tmp_path / "ledger_backfill_last_run_{chain}.json"))
    _route_scene(db, monkeypatch)

    def _no_threads(self, *a, **k):
        raise AssertionError("a real thread was started")

    monkeypatch.setattr(threading.Thread, "start", _no_threads)
    r = client.get(ADVISOR_URL)
    assert r.status_code == 200
    # a non-empty kick proves the spawn call itself succeeded - i.e. the
    # no-op ran, since a real spawn would have raised and fallen back to []
    assert r.get_json()["ledger_backfill_kicked"] == ["base", "robinhood"]
