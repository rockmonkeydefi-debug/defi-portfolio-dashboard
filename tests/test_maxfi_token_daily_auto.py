"""Ledger-as-source commit 3 - the token-daily refresh as a callable
(_run_token_daily_refresh) with a busy lock, plus the on-view DAILY
auto-refresh on GET /api/maxfi/advisor (default OFF until a post-deploy
dry run is eyeball-checked - the route's own DEPLOY PROTOCOL).

Rulings under test (Glenn, Sep 25), per chain in MAXFI_CHAINS, today =
now_utc's UTC date:
- "daily": the chain has no maxfi_token_daily row dated today;
- "held": an open position's non-anchor token has no row dated today;
- at most one start per chain per 60 minutes; one daemon thread drains
  each kicked chain with up to 10 real runs (70s between runs, 120s after
  a rate-limit abort, stop on a non-200 or an empty deferral).

Fixtures and seeders are IMPORTED from tests/test_maxfi_token_daily_refresh.py
(underscore helpers and fixtures only, never a test_* function);
maxfi_history.fetch_pool_ohlcv is monkeypatched exactly as that file does -
no network. tests/conftest.py's autouse fixture makes the new spawner a
no-op and gives every test a fresh last-kick map; the trigger tests here
install a recorder. The advisor-route tests also stub the metrics and
ledger kicks (the metrics kick would otherwise start a real refresh thread)."""
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

import maxfi_history
import web_portfolio as wp

from test_maxfi_token_daily_refresh import (  # noqa: F401  (client/daily_db are fixtures)
    POOL_A,
    QUOTE,
    TOKEN_A,
    TOKEN_B,
    _daily_rows,
    _page,
    _seed_catalogue_pool,
    _seed_metrics,
    _seed_position,
    _seed_token_daily,
    client,
    daily_db,
)

# The real spawner, captured before conftest's autouse no-op replaces it
# (getattr, so a missing function is a test failure, not a collection error).
_REAL_SPAWN = getattr(wp, "_spawn_token_daily_refresh_thread", None)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
TODAY = "2026-09-25"
YESTERDAY = "2026-09-24"
BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"       # a base anchor
RH_TOKEN = "0x" + "7" * 40
ADVISOR_URL = "/api/maxfi/advisor"
SETTINGS_URL = "/api/settings/advisor"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(wp, "ADVISOR_SETTINGS_PATH", str(tmp_path / "advisor_settings.json"))
    spawned = []
    monkeypatch.setattr(wp, "_spawn_token_daily_refresh_thread", lambda chains: spawned.append(list(chains)))

    class Env:
        calls = spawned

        @staticmethod
        def enable(value=True):
            (tmp_path / "advisor_settings.json").write_text(json.dumps({"token_daily_auto_refresh_enabled": value}))

    return Env


def _current(db, chain, address=None):
    """A row dated today for `chain`, so the chain is not "daily" due."""
    _seed_token_daily(db, chain, (address or ("0x" + "9" * 40)).lower(), TODAY)


def _kick(now=NOW):
    return wp._maybe_kick_token_daily_auto_refresh(now_utc=now)


# ── P1-P2: the callable and its lock ───────────────────────────────────────

def _parity_scene(db, monkeypatch):
    _seed_catalogue_pool(db, "base", POOL_A, TOKEN_A, QUOTE)
    _seed_metrics(db, "base", POOL_A, liquidity_usd=50000.0)
    _seed_position(db, 1, "base", POOL_A, TOKEN_A, QUOTE)
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv",
                        lambda network, pool, tf, **kw: _page(TOKEN_A, QUOTE, [("2026-09-01", 1.5)]))


def _without_run_at(payload):
    return {k: v for k, v in payload.items() if k != "run_at"}


def test_p1_callable_matches_the_route_dry_real_floor_and_invalid_chain(client, daily_db, monkeypatch):
    _parity_scene(daily_db, monkeypatch)
    r = client.post("/api/maxfi/token-daily-refresh/base?dry_run=true")
    payload, status = wp._run_token_daily_refresh("base", dry_run=True)
    assert (status, _without_run_at(payload)) == (r.status_code, _without_run_at(r.get_json()))
    assert payload["dry_run"] is True and payload["results"][0]["status"] == "would_write"

    r = client.post("/api/maxfi/token-daily-refresh/base?liquidity_floor=0")
    route_real = r.get_json()
    daily_db.execute("DELETE FROM maxfi_token_daily")
    daily_db.commit()
    payload, status = wp._run_token_daily_refresh("base", liquidity_floor=0.0)
    assert (status, _without_run_at(payload)) == (r.status_code, _without_run_at(route_real))
    assert payload["liquidity_floor_usd"] == 0.0 and payload["results"][0]["status"] == "written"
    assert len(_daily_rows(daily_db, "base", TOKEN_A)) == 1

    payload, status = wp._run_token_daily_refresh("base")
    assert payload["liquidity_floor_usd"] == wp.MAXFI_TOKEN_DAILY_LIQUIDITY_FLOOR_USD

    r = client.post("/api/maxfi/token-daily-refresh/nope")
    assert wp._run_token_daily_refresh("nope") == (r.get_json(), 400)
    # the route still checks the chain before the floor, as before
    r = client.post("/api/maxfi/token-daily-refresh/nope?liquidity_floor=abc")
    assert r.status_code == 400 and r.get_json()["error"] == "InvalidChain"
    r = client.post("/api/maxfi/token-daily-refresh/base?liquidity_floor=-1")
    assert r.status_code == 400 and r.get_json()["error"] == "InvalidLiquidityFloor"


def test_p2_busy_lock_409_and_released_after_normal_and_failed_runs(client, daily_db, monkeypatch):
    _parity_scene(daily_db, monkeypatch)
    assert wp._TOKEN_DAILY_REFRESH_LOCK.acquire(blocking=False)
    try:
        r = client.post("/api/maxfi/token-daily-refresh/base")
        assert r.status_code == 409
        assert r.get_json() == {"error": "RefreshBusy", "detail": "a token-daily refresh is already running"}
        assert wp._run_token_daily_refresh("base")[1] == 409
    finally:
        wp._TOKEN_DAILY_REFRESH_LOCK.release()

    assert wp._run_token_daily_refresh("base", dry_run=True)[1] == 200
    assert not wp._TOKEN_DAILY_REFRESH_LOCK.locked()

    def _boom(*a, **k):
        raise RuntimeError("unexpected failure inside the body")

    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", _boom)
    with pytest.raises(RuntimeError):
        wp._run_token_daily_refresh("base", dry_run=True)
    assert not wp._TOKEN_DAILY_REFRESH_LOCK.locked()


# ── P3-P9: the trigger ─────────────────────────────────────────────────────

def test_p3_default_setting_is_off(daily_db, env):
    assert wp.ADVISOR_SETTINGS_DEFAULTS["token_daily_auto_refresh_enabled"] is False
    assert _kick() == ([], {})                                 # empty db: both chains would be due
    assert env.calls == []


def test_p4_no_row_dated_today_is_daily(daily_db, env):
    env.enable()
    _seed_token_daily(daily_db, "base", TOKEN_B, YESTERDAY)
    _current(daily_db, "robinhood")
    assert _kick() == (["base"], {"base": "daily"})
    assert env.calls == [["base"]]


def test_p5_held_non_anchor_token_missing_today_is_held(daily_db, env):
    env.enable()
    _current(daily_db, "base", TOKEN_B)
    _seed_position(daily_db, 1, "base", POOL_A, TOKEN_A, QUOTE)      # TOKEN_A has no row today
    _current(daily_db, "robinhood")
    assert _kick() == (["base"], {"base": "held"})


def test_p5_both_rules_give_daily_plus_held(daily_db, env):
    env.enable()
    _seed_position(daily_db, 1, "base", POOL_A, TOKEN_A, QUOTE)
    _current(daily_db, "robinhood")
    assert _kick() == (["base"], {"base": "daily+held"})


def test_p6_everything_current_starts_nothing(daily_db, env):
    env.enable()
    _seed_position(daily_db, 1, "base", POOL_A, TOKEN_A.upper(), QUOTE)   # held address is lowercased
    _current(daily_db, "base", TOKEN_A)
    _current(daily_db, "robinhood")
    assert _kick() == ([], {})
    assert env.calls == []


def test_p7_held_anchor_tokens_never_trigger_held(daily_db, env):
    env.enable()
    _current(daily_db, "base", TOKEN_B)
    _seed_position(daily_db, 1, "base", POOL_A, BASE_USDC, QUOTE)     # both sides are base anchors
    _current(daily_db, "robinhood")
    assert _kick() == ([], {})


def test_p8_cooldown_is_60_minutes(daily_db, env):
    env.enable()
    _current(daily_db, "robinhood")
    assert wp.MAXFI_TOKEN_DAILY_AUTO_COOLDOWN_MINUTES == 60
    assert _kick()[0] == ["base"]
    assert _kick(NOW + timedelta(minutes=59)) == ([], {})
    assert _kick(NOW + timedelta(minutes=61)) == (["base"], {"base": "daily"})
    assert env.calls == [["base"], ["base"]]


def test_p9_both_chains_due_is_one_spawn_in_maxfi_chains_order(daily_db, env):
    env.enable()
    _seed_position(daily_db, 2, "robinhood", "0xrhpool", RH_TOKEN, "0x0bd7d308f8e1639fab988df18a8011f41eacad73")
    kicked, reasons = _kick()
    assert kicked == list(wp.MAXFI_CHAINS)
    assert reasons == {"base": "daily", "robinhood": "daily+held"}
    assert env.calls == [list(wp.MAXFI_CHAINS)]


def test_p9_today_follows_the_injected_utc_date(daily_db, env):
    env.enable()
    _current(daily_db, "base")
    _current(daily_db, "robinhood")
    assert _kick() == ([], {})
    # one minute past midnight UTC on the next day: yesterday's rows no longer count
    assert _kick(datetime(2026, 9, 26, 0, 1, tzinfo=timezone.utc))[0] == list(wp.MAXFI_CHAINS)


# ── P10: the worker ────────────────────────────────────────────────────────

class _InlineThread:
    made = []

    def __init__(self, target=None, name=None, daemon=None, **kwargs):
        self.target, self.name, self.daemon = target, name, daemon
        _InlineThread.made.append(self)

    def start(self):
        self.target()


def _ok(deferred, rate_limited=False):
    return ({"deferred_budget": deferred, "aborted_rate_limited": rate_limited, "attempted": 1}, 200)


def _run_worker(monkeypatch, script, chains=None):
    """script: {chain: [outcome, ...]}, outcome a (payload, status) or an Exception."""
    calls, sleeps = [], []
    queues = {chain: list(outcomes) for chain, outcomes in script.items()}

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        outcome = queues[args[0]].pop(0) if len(queues[args[0]]) > 1 else queues[args[0]][0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    _InlineThread.made = []
    monkeypatch.setattr(threading, "Thread", _InlineThread)
    monkeypatch.setattr(wp, "_run_token_daily_refresh", fake_run)
    monkeypatch.setattr(wp.time, "sleep", lambda s: sleeps.append(s))
    assert _REAL_SPAWN is not None, "_spawn_token_daily_refresh_thread missing"
    _REAL_SPAWN(chains or list(wp.MAXFI_CHAINS))
    return calls, sleeps


def test_p10_drains_until_nothing_is_deferred(monkeypatch):
    calls, sleeps = _run_worker(monkeypatch, {"base": [_ok(10), _ok(0)], "robinhood": [_ok(0)]})
    assert calls == [(("base",), {}), (("base",), {}), (("robinhood",), {})]    # real runs only, no dry_run
    assert sleeps == [70]
    assert len(_InlineThread.made) == 1
    assert _InlineThread.made[0].name == "token-daily-auto-refresh" and _InlineThread.made[0].daemon is True


def test_p10_rate_limit_abort_waits_120_then_continues(monkeypatch):
    calls, sleeps = _run_worker(monkeypatch, {"base": [_ok(4, rate_limited=True), _ok(0)], "robinhood": [_ok(0)]},
                                chains=["base"])
    assert calls == [(("base",), {}), (("base",), {})]
    assert sleeps == [120]


def test_p10_run_cap_is_honoured(monkeypatch):
    assert wp.MAXFI_TOKEN_DAILY_AUTO_MAX_RUNS == 10
    calls, sleeps = _run_worker(monkeypatch, {"base": [_ok(5)]}, chains=["base"])
    assert len(calls) == 10
    assert sleeps == [70] * 9                                   # no wait after the last allowed run


def test_p10_a_409_stops_that_chain_and_the_next_still_runs(monkeypatch, capsys):
    busy = ({"error": "RefreshBusy", "detail": "a token-daily refresh is already running"}, 409)
    calls, sleeps = _run_worker(monkeypatch, {"base": [busy], "robinhood": [_ok(0)]})
    assert calls == [(("base",), {}), (("robinhood",), {})]
    assert sleeps == []
    assert "RefreshBusy" in capsys.readouterr().out


def test_p10_an_exception_stops_that_chain_and_the_next_still_runs(monkeypatch, capsys):
    calls, _ = _run_worker(monkeypatch, {"base": [RuntimeError("gt exploded")], "robinhood": [_ok(0)]})
    assert calls == [(("base",), {}), (("robinhood",), {})]
    assert all(not kw.get("dry_run") for _, kw in calls)
    assert "gt exploded" in capsys.readouterr().out


# ── P11: settings ──────────────────────────────────────────────────────────

def test_p11_settings_default_false_and_validation(client, env):
    assert client.get(SETTINGS_URL).get_json()["token_daily_auto_refresh_enabled"] is False
    for value in (True, False):
        r = client.post(SETTINGS_URL, json={"token_daily_auto_refresh_enabled": value})
        assert r.status_code == 200 and r.get_json()["token_daily_auto_refresh_enabled"] is value
    for bad in ("true", 1, None):
        r = client.post(SETTINGS_URL, json={"token_daily_auto_refresh_enabled": bad})
        assert r.status_code == 400, bad
        assert "token_daily_auto_refresh_enabled" in r.get_json()["error"], bad


# ── P12-P13: the advisor route ─────────────────────────────────────────────

EXISTING_ADVISOR_KEYS = {
    "as_of", "positions", "entry_candidates", "constants", "metrics_refresh_kicked",
    "ledger_shadow_unavailable", "ledger_backfill_kicked", "ledger_backfill_kick_reasons",
    "ledger_backfill_in_flight",
}
NEW_KEYS = {"token_daily_kicked", "token_daily_kick_reasons", "token_daily_in_flight"}


def _stub_other_kicks(monkeypatch):
    monkeypatch.setattr(wp, "_maybe_kick_metrics_auto_refresh", lambda: ["base"])
    monkeypatch.setattr(wp, "_maybe_kick_ledger_auto_backfill", lambda now_utc=None: (["robinhood"], {"robinhood": "time"}))


def test_p12_advisor_route_reports_the_kick_beside_the_unchanged_keys(client, daily_db, env, monkeypatch):
    _stub_other_kicks(monkeypatch)
    env.enable()
    body = client.get(ADVISOR_URL).get_json()
    assert set(body) == EXISTING_ADVISOR_KEYS | NEW_KEYS
    assert body["metrics_refresh_kicked"] == ["base"]
    assert body["ledger_backfill_kicked"] == ["robinhood"]
    assert body["ledger_backfill_kick_reasons"] == {"robinhood": "time"}
    assert body["token_daily_kicked"] == list(wp.MAXFI_CHAINS)
    assert body["token_daily_kick_reasons"] == {c: "daily" for c in wp.MAXFI_CHAINS}
    assert body["token_daily_in_flight"] is True
    assert env.calls == [list(wp.MAXFI_CHAINS)]

    def _boom(now_utc=None):
        raise RuntimeError("trigger broke")

    monkeypatch.setattr(wp, "_maybe_kick_token_daily_auto_refresh", _boom)
    r = client.get(ADVISOR_URL)
    assert r.status_code == 200
    failed = r.get_json()
    assert failed["token_daily_kicked"] == [] and failed["token_daily_kick_reasons"] == {}
    assert failed["token_daily_in_flight"] is False
    assert failed["ledger_backfill_kicked"] == ["robinhood"] and failed["metrics_refresh_kicked"] == ["base"]


def test_p12_in_flight_reflects_a_held_refresh_lock(client, daily_db, env, monkeypatch):
    _stub_other_kicks(monkeypatch)
    assert client.get(ADVISOR_URL).get_json()["token_daily_in_flight"] is False      # setting off
    assert wp._TOKEN_DAILY_REFRESH_LOCK.acquire(blocking=False)
    try:
        assert client.get(ADVISOR_URL).get_json()["token_daily_in_flight"] is True
    finally:
        wp._TOKEN_DAILY_REFRESH_LOCK.release()


def test_p13_conftest_guard_means_no_real_thread_ever_starts(client, daily_db, tmp_path, monkeypatch):
    # No recorder here: conftest's autouse no-op is the spawner in force.
    monkeypatch.setattr(wp, "ADVISOR_SETTINGS_PATH", str(tmp_path / "advisor_settings.json"))
    (tmp_path / "advisor_settings.json").write_text(json.dumps({"token_daily_auto_refresh_enabled": True}))
    _stub_other_kicks(monkeypatch)

    def _no_threads(self, *a, **k):
        raise AssertionError("a real thread was started")

    monkeypatch.setattr(threading.Thread, "start", _no_threads)
    r = client.get(ADVISOR_URL)
    assert r.status_code == 200
    # a non-empty kick proves the spawn call itself succeeded - i.e. the
    # no-op ran, since a real spawn would have raised and fallen back to []
    assert r.get_json()["token_daily_kicked"] == list(wp.MAXFI_CHAINS)
