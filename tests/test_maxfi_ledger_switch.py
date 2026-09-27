"""Ledger-as-source commit 4 - the switch. The on-chain ledger is the only
source of Claimed, P/L, the run rates and the verdict on GET
/api/maxfi/positions/<chain>/<wallet>, GET /api/maxfi/valuation/<chain>/
<wallet> and GET /api/maxfi/advisor; ledger_shadow is retired.

Rulings under test (Glenn, Sep 27):
- R1 manual maxfi_claims rows count nowhere in these three routes;
- R2 a CLOSED row's final withdraw-tx fee claim is excluded only when its
  closing value is manual (closing_value_usd set and closing_value_source
  not 'auto_last_observed'; a NULL source is manual-equivalent) - an
  auto-copied or missing closing value leaves the final claim COUNTED;
- R3 verified AERO rewards count; R4 the accrual anchor is the latest FEE
  claim;
- R5/R6 an uncovered row is "catching_up" (open, a backfill can run, and
  either no successful run yet or observed after it - the auto-backfill's
  own coverage predicate) or "not_in_ledger"; either way its Claimed / P/L
  / run rate / verdict are withheld, never shown as a false zero;
- R7 an open covered row whose ledger head is closed keeps its claims but
  its verdict is withheld;
- R8 unattributed ledger lineages are totalled on the advisor's "ledger"
  block; R9 "claims_provenance" replaces "ledger_shadow"; R10 a ledger load
  failure keeps the claims_unavailable contract.

Every new helper is referenced as wp.<name> inside the test bodies, so the
red run fails per test. Seeders and fixtures come from
tests/test_maxfi_ledger_reconciliation.py, tests/test_maxfi_ledger_as_source.py
and tests/test_maxfi_advisor.py (underscore helpers and fixtures only, never
a test_* function). The last-run files and the advisor settings file are
pinned to tmp_path by an autouse fixture; conftest already turns the
backfill spawners into no-ops, and the advisor tests stub the metrics kick.
Every expected number is hand-computed in a comment."""
import json
import math
from datetime import datetime, timedelta, timezone

import pytest

import web_portfolio as wp

from test_maxfi_ledger_reconciliation import (  # noqa: F401  (client/db are fixtures)
    _forbid_rpc,
    _seed_claim,
    _seed_initial_value,
    _seed_ledger_claim,
    _seed_ledger_position,
    _seed_position,
    client,
    db,
)
from test_maxfi_ledger_as_source import (
    _advisor_scene,
    _fee,
    _ledger_row,
    _link,
    _seed_reward,
    _ts,
    _withdraw,
)
from test_maxfi_advisor import (
    _seed_claim as _adv_seed_claim,
    _seed_position as _adv_seed_position,
)

WALLET = "0x" + "a" * 40          # test_maxfi_ledger_reconciliation._seed_position's default
POSITIONS_URL = f"/api/maxfi/positions/base/{WALLET}"
VALUATION_URL = f"/api/maxfi/valuation/base/{WALLET}"
ADVISOR_URL = "/api/maxfi/advisor"
AERO = "0x940181a94a35a4569e4529a3cdfb74e38fd98631"
WETH_BASE = "0x4200000000000000000000000000000000000006"
USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
T = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)

PROVENANCE_KEYS = {
    "source", "ledger_state", "ledger_as_of", "covered", "lineage_token_count", "fee_claimed_usd",
    "reward_claimed_usd", "claimed_usd", "final_claim_usd", "final_claim_unpriced", "final_claim_included",
    "claim_count", "unpriced_claims", "last_fee_claim_at", "ledger_head_closed",
}
ADVISOR_PROVENANCE_KEYS = {
    "source", "ledger_state", "covered", "claimed_usd", "claim_count", "unpriced_claims",
    "ledger_head_closed", "uncollected_accrual_days",
}
R6_FIGURES = ("run_rate_7d_pct_day", "run_rate_lifetime_pct_day", "window_earned_usd", "lifetime_earned_usd")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    """tmp_path last-run files and advisor settings; a missing file is "no
    successful run" / the defaults (ledger_auto_backfill_enabled True)."""
    monkeypatch.setattr(wp, "LEDGER_BACKFILL_LAST_RUN_PATH", str(tmp_path / "ledger_backfill_last_run_{chain}.json"))
    monkeypatch.setattr(wp, "ADVISOR_SETTINGS_PATH", str(tmp_path / "advisor_settings.json"))
    spawned = []
    monkeypatch.setattr(wp, "_spawn_ledger_backfill_thread", lambda chains: spawned.append(list(chains)))

    class Env:
        calls = spawned

        @staticmethod
        def last_run(chain, run_at, dry_run=False, **extra):
            body = dict({"chain": chain, "dry_run": dry_run, "run_at": run_at}, **extra)
            (tmp_path / f"ledger_backfill_last_run_{chain}.json").write_text(json.dumps(body))

        @staticmethod
        def settings(**values):
            (tmp_path / "advisor_settings.json").write_text(json.dumps(values))

    return Env


def _no_kick(monkeypatch):
    monkeypatch.setattr(wp, "_maybe_kick_metrics_auto_refresh", lambda: [])


def _boom(*a, **k):
    raise RuntimeError("ledger load failed")


def _rows(client, url=POSITIONS_URL):
    r = client.get(url)
    assert r.status_code == 200
    return {row["id"]: row for row in r.get_json()}


def _advisor(client):
    r = client.get(ADVISOR_URL)
    assert r.status_code == 200
    return r.get_json()


def _adv_pos(body, position_id):
    return next(p for p in body["positions"] if p["id"] == position_id)


def _set_rebalanced(db, pid, iso):
    db.execute("UPDATE maxfi_positions SET last_rebalanced_at = ? WHERE id = ?", (iso, pid))
    db.commit()


def _closing(db, pid, usd, source):
    db.execute(
        "INSERT INTO maxfi_position_user_data (position_id, closing_value_usd, closing_value_source, set_at, set_by) "
        "VALUES (?, ?, ?, '2026-01-01T00:00:00+00:00', 'glenn')",
        (pid, usd, source),
    )
    db.commit()


# ── S1: the R2 matrix on the pure helper ───────────────────────────────────

# Closed row 1 on lineage 100 -> 200 (200 withdrawn): fees 10 (ts 1) + 3 (ts 2)
# + the withdraw-tx claim 7 (ts 20, tx 0xWD; the event carries 0xwd).
# Included: fee = claimed = 10 + 3 + 7 = 20, 3 claims, last fee ts 20.
# Excluded: fee = claimed = 13, 2 claims, last fee ts 2.
def _r2_pure(closing_values, final_usd=7.0, **kw):
    return wp._maxfi_ledger_position_claims(
        [(1, "base", "200", "closed")],
        [_ledger_row("100", to="200"), _ledger_row("200", frm="100", closed_at=_ts(20))],
        [("base", "100", "0xe1", _ts(1), 10.0), ("base", "200", "0xe2", _ts(2), 3.0),
         ("base", "200", "0xWD", _ts(20), final_usd)],
        [],
        [("base", "200", "0xwd", 50)],
        closing_values=closing_values, **kw,
    )[1]


@pytest.mark.parametrize("closing_values, included", [
    ({1: (100.0, "manual")}, False),
    ({1: (100.0, None)}, False),                       # legacy NULL source = manual-equivalent
    ({1: (100.0, "auto_last_observed")}, True),
    ({}, True),                                        # no closing-value row at all
    ({1: (None, "manual")}, True),                     # no closing value
], ids=["manual", "null_source", "auto_last_observed", "no_entry", "value_none"])
def test_s1_r2_matrix(closing_values, included):
    out = _r2_pure(closing_values)
    assert out["final_claim_usd"] == 7.0                 # reported either way
    assert out["final_claim_unpriced"] is False
    assert out["final_claim_included"] is included
    if included:
        assert out["fee_claimed_usd"] == 20.0 and out["claimed_usd"] == 20.0
        assert out["claim_count"] == 3
        assert out["claims"] == [(_ts(1), 10.0), (_ts(2), 3.0), (_ts(20), 7.0)]
        assert out["last_fee_claim_at"] == _ts(20)
    else:
        assert out["fee_claimed_usd"] == 13.0 and out["claimed_usd"] == 13.0
        assert out["claim_count"] == 2
        assert out["claims"] == [(_ts(1), 10.0), (_ts(2), 3.0)]
        assert out["last_fee_claim_at"] == _ts(2)


def test_s1_closing_values_none_means_include():
    out = wp._maxfi_ledger_position_claims(
        [(1, "base", "200", "closed")],
        [_ledger_row("200", closed_at=_ts(20))],
        [("base", "200", "0xe2", _ts(2), 3.0), ("base", "200", "0xwd", _ts(20), 7.0)],
        [],
        [("base", "200", "0xwd", 50)],
    )[1]
    # 3 + 7 = 10: no closing values at all -> the final claim counts
    assert (out["fee_claimed_usd"], out["claim_count"], out["final_claim_included"]) == (10.0, 2, True)


def test_s1_unpriced_final_on_an_included_row_counts_as_unpriced():
    out = _r2_pure({1: (100.0, "auto_last_observed")}, final_usd=None)
    assert out["final_claim_usd"] is None and out["final_claim_unpriced"] is True
    assert out["final_claim_included"] is True
    assert out["unpriced_claims"] == 1                   # counted, never summed
    assert out["fee_claimed_usd"] == 13.0 and out["claim_count"] == 3
    assert out["claims"][-1] == (_ts(20), None)


def test_s1_open_row_has_no_final_claim():
    out = wp._maxfi_ledger_position_claims(
        [(1, "base", "100", "open")], [_ledger_row("100")], [("base", "100", "0xa", _ts(1), 4.0)], [], [],
        closing_values={},
    )[1]
    assert (out["final_claim_usd"], out["final_claim_included"], out["claimed_usd"]) == (None, False, 4.0)


# ── S2: ledger_state (pure) and parity with the auto-backfill trigger ──────

@pytest.mark.parametrize("covered, status, observed, last_success, possible, expected", [
    (True, "open", "2026-01-01T00:00:00+00:00", T, False, "covered"),
    (True, "closed", None, None, True, "covered"),
    (False, "closed", (T + timedelta(hours=1)).isoformat(), None, True, "not_in_ledger"),
    (False, "open", "2026-01-01T00:00:00+00:00", None, True, "catching_up"),       # no successful run yet
    (False, "open", (T + timedelta(minutes=1)).isoformat(), T, True, "catching_up"),
    (False, "open", "2026-09-25T12:01:00", T, True, "catching_up"),                 # naive = UTC
    (False, "open", T.isoformat(), T, True, "not_in_ledger"),                        # equal is not after
    (False, "open", (T - timedelta(minutes=1)).isoformat(), T, True, "not_in_ledger"),
    (False, "open", "not-a-time", T, True, "not_in_ledger"),
    (False, "open", None, T, True, "not_in_ledger"),
    (False, "open", "not-a-time", None, True, "catching_up"),
    (False, "open", (T + timedelta(minutes=1)).isoformat(), T, False, "not_in_ledger"),  # backfill impossible
    (False, "open", "2026-01-01T00:00:00+00:00", None, False, "not_in_ledger"),
], ids=["covered", "covered_closed", "closed_uncovered", "no_success", "observed_after", "naive_after",
        "observed_equal", "observed_before", "unparseable_with_success", "none_with_success",
        "unparseable_no_success", "impossible_after", "impossible_no_success"])
def test_s2_ledger_state_matrix(covered, status, observed, last_success, possible, expected):
    assert wp._maxfi_ledger_state(covered, status, observed, last_success, possible) == expected


def test_s2_state_context_reads_last_run_files_and_settings(env):
    env.last_run("base", T.isoformat())
    env.last_run("robinhood", T.isoformat(), dry_run=True)
    ctx = wp._maxfi_ledger_state_context()
    assert set(ctx) == {"last_success", "as_of", "backfill_possible"}
    assert set(ctx["last_success"]) == set(ctx["as_of"]) == set(wp.MAXFI_CHAINS)
    assert ctx["last_success"]["base"] == T
    assert ctx["as_of"]["base"] == T.isoformat()
    assert ctx["last_success"]["robinhood"] is None and ctx["as_of"]["robinhood"] is None
    assert ctx["backfill_possible"] is True


def test_s2_state_context_disabled_lock_and_settings_failure(env, monkeypatch):
    env.settings(ledger_auto_backfill_enabled=False)
    assert wp._maxfi_ledger_state_context()["backfill_possible"] is False
    assert wp._LEDGER_BACKFILL_LOCK.acquire(blocking=False)
    try:
        assert wp._maxfi_ledger_state_context()["backfill_possible"] is True     # a run in flight
        monkeypatch.setattr(wp, "_advisor_settings", _boom)
        assert wp._maxfi_ledger_state_context()["backfill_possible"] is True     # lock still checked
    finally:
        wp._LEDGER_BACKFILL_LOCK.release()
    assert wp._maxfi_ledger_state_context()["backfill_possible"] is False        # failure = disabled


@pytest.mark.parametrize("first_seen, rebalanced, enabled", [
    (T - timedelta(minutes=30), None, True),       # after the T-1h run -> coverage kick
    (T - timedelta(hours=2), None, True),          # before it -> nothing
    (T - timedelta(hours=1), None, True),          # equal -> nothing
    (T - timedelta(days=30), T - timedelta(minutes=5), True),   # last_rebalanced_at wins
    ("not-a-time", None, True),                    # unparseable -> nothing
    (T - timedelta(minutes=30), None, False),      # auto-backfill disabled -> nothing
], ids=["after", "before", "equal", "rebalanced_after", "unparseable", "disabled"])
def test_s2_parity_with_the_coverage_trigger(db, env, first_seen, rebalanced, enabled):
    for chain in wp.MAXFI_CHAINS:                   # every chain ran at T-1h: the TIME rule is not due
        env.last_run(chain, (T - timedelta(hours=1)).isoformat())
    if not enabled:
        env.settings(ledger_auto_backfill_enabled=False)
    first_seen_raw = first_seen if isinstance(first_seen, str) else first_seen.isoformat()
    _seed_position(db, 1, token_id="500", first_seen_at=first_seen_raw)
    observed_raw = first_seen_raw
    if rebalanced is not None:
        _set_rebalanced(db, 1, rebalanced.isoformat())
        observed_raw = rebalanced.isoformat()
    kicked, reasons = wp._maybe_kick_ledger_auto_backfill(now_utc=T)
    ctx = wp._maxfi_ledger_state_context()
    state = wp._maxfi_ledger_state(False, "open", observed_raw, ctx["last_success"]["base"], ctx["backfill_possible"])
    assert state in ("catching_up", "not_in_ledger")
    assert ((kicked, reasons) == (["base"], {"base": "coverage"})) is (state == "catching_up")
    assert ((kicked, reasons) == ([], {})) is (state == "not_in_ledger")


# ── S3: unattributed lineages (pure) ───────────────────────────────────────

def test_s3_unattributed_lineages_and_totals():
    owner = "0xAbCdEf" + "0" * 34
    app_rows = [(1, "base", "10", "open")]
    ledger_rows = [
        dict(_ledger_row("10"), owner="0x" + "1" * 40),                  # attributed (row 1)
        dict(_ledger_row("20", to="21"), owner=None),
        dict(_ledger_row("21", frm="20"), owner=owner),                  # head of lineage A
        dict(_ledger_row("30"), owner=None),                             # lineage B, no owner
    ]
    claim_rows = [
        ("base", "10", "0xa", _ts(1), 5.0),
        ("base", "20", "0xb", _ts(2), 1.5),
        ("base", "21", "0xc", _ts(3), 2.5),
        ("base", "21", "0xd", _ts(4), None),                             # unpriced: counted, not summed
        ("base", "30", "0xe", _ts(5), 0.25),
    ]
    reward_rows = [
        ("base", "10", "0xr0", AERO, "verified", _ts(1), 50.0),          # attributed - not here
        ("base", "21", "0xr1", AERO, "verified", _ts(3), 4.0),
        ("base", "20", "0xr2", AERO, "mismatch", _ts(2), 100.0),         # not a counted status
    ]
    out = wp._maxfi_ledger_unattributed_claims(app_rows, ledger_rows, claim_rows, reward_rows)
    # A: fees 1.5 + 2.5 = 4.0 (+1 unpriced), reward 4.0, claimed 8.0, 3 fee claims + 1 reward = 4
    # B: fee 0.25, claimed 0.25, 1 claim
    assert out["lineages"] == [
        {"chain": "base", "owner": owner.lower(), "root_token_id": "20", "head_token_id": "21",
         "token_count": 2, "fee_claimed_usd": 4.0, "reward_claimed_usd": 4.0, "claimed_usd": 8.0,
         "claim_count": 4, "unpriced_claims": 1},
        {"chain": "base", "owner": None, "root_token_id": "30", "head_token_id": "30",
         "token_count": 1, "fee_claimed_usd": 0.25, "reward_claimed_usd": 0.0, "claimed_usd": 0.25,
         "claim_count": 1, "unpriced_claims": 0},
    ]
    # totals: 2 lineages, fee 4.25, reward 4.0, claimed 8.25, 5 claims, 1 unpriced
    assert out["totals"] == {"base": {"lineage_count": 2, "fee_claimed_usd": 4.25, "reward_claimed_usd": 4.0,
                                      "claimed_usd": 8.25, "claim_count": 5, "unpriced_claims": 1}}


def test_s3_nothing_unattributed():
    out = wp._maxfi_ledger_unattributed_claims(
        [(1, "base", "10", "open")], [dict(_ledger_row("10"), owner=None)], [], [])
    assert out == {"lineages": [], "totals": {}}


def test_s3_load_inputs_carries_owner_and_closing_values(db):
    _seed_position(db, 1, token_id="10", status="closed", closed_at=_ts(9))
    _seed_ledger_position(db, token_id="10", owner="0xOwNeR")
    _closing(db, 1, 55.0, "auto_last_observed")
    from src.storage.portfolio_db import get_connection     # the db fixture's patched getter
    conn = get_connection()
    try:
        inputs = wp._maxfi_ledger_load_inputs(conn)
    finally:
        conn.close()
    assert set(inputs) == {"app_rows", "ledger_rows", "claim_rows", "reward_rows", "withdraw_events",
                           "closing_values"}
    assert inputs["app_rows"] == [(1, "base", "10", "closed")]
    assert inputs["ledger_rows"][0]["owner"] == "0xOwNeR"
    assert inputs["closing_values"] == {1: (55.0, "auto_last_observed")}


# ── S4: the positions route, covered rows ──────────────────────────────────

def _covered_scene(db):
    # lineage 100 -> 200, row 1 on 200: fees 10 + 15 (+1 unpriced), reward 2
    # -> fee 25, reward 2, claimed 27, 4 claims, 1 unpriced
    _seed_position(db, 1, token_id="200")
    _link(db, ["100", "200"])
    _fee(db, "100", "0xj1", _ts(1), 10.0)
    _fee(db, "200", "0xj2", _ts(2), 15.0)
    _fee(db, "200", "0xj3", _ts(3), None)
    _seed_reward(db, "200", "0xj4", "verified", _ts(4), 2.0)
    _seed_claim(db, 1, _ts(2), 999.0)                 # manual - ignored (R1)


def test_s4_positions_route_reads_the_ledger(client, db, env):
    env.last_run("base", T.isoformat())
    _covered_scene(db)
    row = _rows(client)[1]
    assert row["claimed_usd"] == 27.0
    assert row["claims_unavailable"] is False
    assert "ledger_shadow" not in row
    assert set(row["claims_provenance"]) == PROVENANCE_KEYS
    assert row["claims_provenance"] == {
        "source": "ledger", "ledger_state": "covered", "ledger_as_of": T.isoformat(),
        "covered": True, "lineage_token_count": 2,
        "fee_claimed_usd": 25.0, "reward_claimed_usd": 2.0, "claimed_usd": 27.0,
        "final_claim_usd": None, "final_claim_unpriced": False, "final_claim_included": False,
        "claim_count": 4, "unpriced_claims": 1, "last_fee_claim_at": _ts(3), "ledger_head_closed": False,
    }


@pytest.mark.parametrize("last_run", [None, {"dry_run": True}, {"error": "boom"}],
                         ids=["absent", "dry_run", "error"])
def test_s4_ledger_as_of_none_without_a_successful_run(client, db, env, last_run):
    if last_run is not None:
        env.last_run("base", T.isoformat(), **last_run)
    _covered_scene(db)
    row = _rows(client)[1]
    assert row["claims_provenance"]["ledger_as_of"] is None
    assert row["claimed_usd"] == 27.0                 # a covered row never waits on the run file


# ── S5: the positions route, uncovered rows ────────────────────────────────

def test_s5_uncovered_rows_withhold_claimed(client, db, env):
    env.last_run("base", T.isoformat())
    _seed_position(db, 1, token_id="501", first_seen_at=(T + timedelta(hours=1)).isoformat())   # after
    _seed_position(db, 2, token_id="502", first_seen_at=(T - timedelta(hours=1)).isoformat())   # before
    _seed_position(db, 3, token_id="503", first_seen_at=(T - timedelta(days=9)).isoformat())
    _set_rebalanced(db, 3, (T + timedelta(minutes=5)).isoformat())                               # rebalanced after
    _seed_position(db, 4, token_id="504", status="closed", closed_at=_ts(9),
                   first_seen_at=(T + timedelta(hours=1)).isoformat())
    for pid in (1, 2, 3, 4):
        _seed_claim(db, pid, _ts(2), 50.0)            # manual - ignored
    rows = _rows(client)
    states = {pid: rows[pid]["claims_provenance"]["ledger_state"] for pid in rows}
    assert states == {1: "catching_up", 2: "not_in_ledger", 3: "catching_up", 4: "not_in_ledger"}
    for pid, row in rows.items():
        assert row["claimed_usd"] is None, pid
        assert row["claims_unavailable"] is False
        assert row["claims_provenance"]["covered"] is False
        assert row["claims_provenance"]["claimed_usd"] == 0.0     # the raw ledger sum
        assert "last_rebalanced_at" in row
    assert rows[3]["last_rebalanced_at"] == (T + timedelta(minutes=5)).isoformat()


def test_s5_no_success_yet_is_catching_up(client, db):
    _seed_position(db, 1, token_id="501")
    row = _rows(client)[1]
    assert row["claims_provenance"]["ledger_state"] == "catching_up"
    assert row["claims_provenance"]["ledger_as_of"] is None
    assert row["claimed_usd"] is None


def test_s5_backfill_impossible_is_not_in_ledger(client, db, env):
    env.settings(ledger_auto_backfill_enabled=False)
    _seed_position(db, 1, token_id="501")
    assert not wp._LEDGER_BACKFILL_LOCK.locked()
    row = _rows(client)[1]
    assert row["claims_provenance"]["ledger_state"] == "not_in_ledger"
    assert row["claimed_usd"] is None


# ── S6: the positions route, R2 end to end ─────────────────────────────────

def _closed_row(db, closing):
    # lineage 100 -> 200 (withdrawn), fees 10 + 3, withdraw-tx claim 7
    _seed_position(db, 1, token_id="200", status="closed", closed_at=_ts(20))
    _link(db, ["100", "200"], closed={"200": _ts(20)}, exit_price_usd=90.0)
    _fee(db, "100", "0xe1", _ts(1), 10.0)
    _fee(db, "200", "0xe2", _ts(2), 3.0)
    _fee(db, "200", "0xWD", _ts(20), 7.0)
    _withdraw(db, "200", "0xwd", _ts(20))
    if closing is not None:
        _closing(db, 1, *closing)


@pytest.mark.parametrize("closing, claimed, included", [
    ((100.0, "auto_last_observed"), 20.0, True),       # 10 + 3 + 7
    ((100.0, "manual"), 13.0, False),                  # 10 + 3
    ((100.0, None), 13.0, False),
    (None, 20.0, True),
], ids=["auto_last_observed", "manual", "null_source", "no_closing_value"])
def test_s6_positions_route_final_harvest(client, db, closing, claimed, included):
    _closed_row(db, closing)
    row = _rows(client)[1]
    assert row["claimed_usd"] == claimed
    p = row["claims_provenance"]
    assert p["ledger_state"] == "covered"
    assert p["final_claim_usd"] == 7.0
    assert p["final_claim_included"] is included
    assert p["claim_count"] == (3 if included else 2)


# ── S7: the positions route, ledger load failure ───────────────────────────

def test_s7_positions_route_load_failure(client, db, monkeypatch):
    _covered_scene(db)
    _seed_position(db, 2, token_id="777")
    monkeypatch.setattr(wp, "_maxfi_ledger_load_inputs", _boom)
    rows = _rows(client)
    assert set(rows) == {1, 2}
    for row in rows.values():
        assert row["claims_unavailable"] is True
        assert row["claimed_usd"] == 0.0
        assert row["claims_provenance"] == {"source": "ledger", "unavailable": True}
        assert "ledger_shadow" not in row


# ── S8: the valuation route ────────────────────────────────────────────────

def _tick(price, dec0, dec1):
    return math.log(price / (10 ** (dec0 - dec1))) / math.log(1.0001)


def _diag(price_lower=2300.0, price_upper=2700.0, price_current=2500.0, liquidity=5 * 10 ** 17):
    """A position_diagnostic()-shaped WETH/USDC payload with no fees -
    modelled on tests/test_maxfi_valuation_route.py::make_diag."""
    tl, tu, tc = (round(_tick(p, 18, 6)) for p in (price_lower, price_upper, price_current))
    return {
        "token0": {"address": WETH_BASE, "symbol": "T0", "decimals": 18},
        "token1": {"address": USDC_BASE, "symbol": "T1", "decimals": 6},
        "vault_position": {"decoded": {"currentTickLower": str(tl), "currentTickUpper": str(tu),
                                       "cumulativeFees0": "0", "cumulativeFees1": "0"}},
        "npm_position": {"decoded": {"liquidity": str(liquidity), "feeGrowthInside0LastX128": "0",
                                     "feeGrowthInside1LastX128": "0", "tokensOwed0": "0", "tokensOwed1": "0"}},
        "slot0": {"decoded": {"sqrtPriceX96": str(int((1.0001 ** (tc / 2)) * (2 ** 96))), "tick": str(tc)}},
        "fee_growth_global_0_x128": "0", "fee_growth_global_1_x128": "0",
        "ticks_lower": {"decoded": {"feeGrowthOutside0X128": "0", "feeGrowthOutside1X128": "0"}},
        "ticks_upper": {"decoded": {"feeGrowthOutside0X128": "0", "feeGrowthOutside1X128": "0"}},
    }


def _valuation_seams(monkeypatch, token_ids=("1",)):
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {})
    monkeypatch.setattr(wp, "maxfi_eth_block_number", lambda chain: 1000)
    snapshot = [{"array_index": i, "token_id": t, "pool_address": "0xpool", "token0_address": WETH_BASE,
                 "token1_address": USDC_BASE, "fee_tier": 500} for i, t in enumerate(token_ids)]
    monkeypatch.setattr(wp, "maxfi_get_wallet_position_snapshot", lambda chain, wallet: snapshot)
    diag = _diag()
    monkeypatch.setattr(wp, "maxfi_position_diagnostic", lambda chain, wallet, token_id: diag)
    monkeypatch.setattr(wp.maxfi_anchor_prices, "resolve_anchor_price", lambda symbol, now=None, fetcher=None: {
        "ETH": {"usd": 2500.0, "price_source": "live", "age_seconds": 0},
        "USDC": {"usd": 1.0, "price_source": "live", "age_seconds": 0}}[symbol])


def _valuation(client):
    r = client.get(VALUATION_URL)
    assert r.status_code == 200
    body = r.get_json()
    return body, {p["token_id"]: p for p in body["positions"]}


def _open_row_with_basis(db):
    _seed_position(db, 1, token_id="1")               # open, first seen 2026-01-01
    _seed_initial_value(db, 1, 1000.0)
    _seed_claim(db, 1, _ts(2), 999.0)                 # manual - ignored (R1)


def test_s8_valuation_covered_uses_ledger_claimed(client, db, monkeypatch):
    _valuation_seams(monkeypatch, token_ids=("1", "2"))
    _open_row_with_basis(db)
    _seed_ledger_position(db, token_id="1")
    _seed_ledger_claim(db, "base", "1", "0xv1", _ts(3), 20.0)
    _seed_reward(db, "1", "0xv2", "verified", _ts(4), 5.0)
    body, pos = _valuation(client)
    assert body["claims_unavailable"] is False
    p = pos["1"]
    assert p["claims_ledger_state"] == "covered"
    # pnl = value + uncollected + ledger claimed (20 + 5) - basis 1000
    assert p["performance"]["pnl_usd"] == pytest.approx(p["current_value_usd"] + p["uncollected_usd"] + 25.0 - 1000.0)
    assert pos["2"]["claims_ledger_state"] is None     # no open DB row for token 2


@pytest.mark.parametrize("last_run_at, state", [
    (None, "catching_up"),                             # no successful run yet
    (T.isoformat(), "not_in_ledger"),                  # the run came after 2026-01-01 and missed it
], ids=["catching_up", "not_in_ledger"])
def test_s8_valuation_uncovered_suppresses_pnl(client, db, env, monkeypatch, last_run_at, state):
    if last_run_at is not None:
        env.last_run("base", last_run_at)
    _valuation_seams(monkeypatch)
    _open_row_with_basis(db)
    body, pos = _valuation(client)
    p = pos["1"]
    assert body["claims_unavailable"] is False
    assert p["claims_ledger_state"] == state
    assert p["current_value_usd"] is not None
    assert p["performance"]["pnl_usd"] is None
    assert f"pnl_usd suppressed: claims not in ledger ({state})" in p["performance"]["notes"]


def test_s8_valuation_loader_failure(client, db, monkeypatch):
    _valuation_seams(monkeypatch)
    _open_row_with_basis(db)
    _seed_ledger_position(db, token_id="1")
    _seed_ledger_claim(db, "base", "1", "0xv1", _ts(3), 20.0)
    monkeypatch.setattr(wp, "_maxfi_ledger_load_position_claims", _boom)
    body, pos = _valuation(client)
    p = pos["1"]
    assert body["claims_unavailable"] is True
    assert p["claims_ledger_state"] is None
    # claimed falls back to 0.0: pnl = value + uncollected + 0 - 1000
    assert p["performance"]["pnl_usd"] == pytest.approx(p["current_value_usd"] + p["uncollected_usd"] - 1000.0)


# ── S9: the advisor route reads the ledger ─────────────────────────────────

def test_s9_advisor_verdict_run_rate_and_anchor_from_the_ledger(client, db, monkeypatch):
    _no_kick(monkeypatch)
    _advisor_scene(db, datetime.now(timezone.utc))    # manual $20 says CLOSE; ledger $5000 + $1 says HOLD
    body = _advisor(client)
    assert body["claims_unavailable"] is False
    assert "ledger_shadow_unavailable" not in body
    pos = _adv_pos(body, 1)
    assert "ledger_shadow" not in pos
    assert pos["verdict"] == "HOLD"
    # 5001 / 10000 / 7 x 100 = 7.1443 %/day
    assert pos["run_rate_7d_pct_day"] == pytest.approx(5001.0 / 10000.0 / 7.0 * 100.0)
    assert pos["window_earned_usd"] == pytest.approx(5001.0)
    assert pos["lifetime_earned_usd"] == pytest.approx(5001.0)
    prov = pos["claims_provenance"]
    assert set(prov) == ADVISOR_PROVENANCE_KEYS
    # the fee claim 2 days ago anchors accrual, not the reward 1 day ago
    assert prov["uncollected_accrual_days"] == pytest.approx(2.0, abs=0.01)
    assert (prov["source"], prov["ledger_state"], prov["covered"], prov["claimed_usd"], prov["claim_count"],
            prov["unpriced_claims"], prov["ledger_head_closed"]) == (
        "ledger", "covered", True, 5001.0, 2, 0, False)


# ── S10: the advisor's holds ───────────────────────────────────────────────

def _assert_held(pos, flag):
    assert pos["verdict"] == "insufficient_data"
    assert pos["flags"][-1] == flag
    assert pos["threshold_pct_day"] is None and pos["margin_pct_day"] is None and pos["decay_floored"] is None


def test_s10_catching_up_row_is_held_with_figures_withheld(client, db, monkeypatch):
    _no_kick(monkeypatch)
    now = datetime.now(timezone.utc)
    _advisor_scene(db, now)
    _adv_seed_position(db, 2, first_seen_at=(now - timedelta(days=40)).isoformat(), ledger_covered=False)
    _adv_seed_claim(db, 2, (now - timedelta(days=3)).isoformat(), 400.0)     # manual - ignored
    pos = _adv_pos(_advisor(client), 2)                # no successful run yet -> catching_up
    _assert_held(pos, "ledger_catching_up")
    for k in R6_FIGURES:
        assert pos[k] is None, k
    # price and decay still reported: 1.2 -> 1.0 = -16.667%, decay 16.667 / 7
    assert pos["pct_7d"] == pytest.approx((1.0 - 1.2) / 1.2 * 100.0)
    assert pos["decay_pct_day"] == pytest.approx((1.0 - 1.0 / 1.2) * 100.0 / 7.0)
    assert pos["claims_provenance"]["ledger_state"] == "catching_up"
    assert pos["claims_provenance"]["covered"] is False


def test_s10_not_in_ledger_row_is_held(client, db, env, monkeypatch):
    _no_kick(monkeypatch)
    now = datetime.now(timezone.utc)
    _advisor_scene(db, now)
    _adv_seed_position(db, 2, first_seen_at=(now - timedelta(days=40)).isoformat(), ledger_covered=False)
    env.last_run("base", (now - timedelta(hours=1)).isoformat())     # ran after row 2 was seen, missed it
    body = _advisor(client)
    pos = _adv_pos(body, 2)
    _assert_held(pos, "not_in_ledger")
    for k in R6_FIGURES:
        assert pos[k] is None, k
    assert pos["pct_7d"] is not None
    assert _adv_pos(body, 1)["verdict"] == "HOLD"       # the covered row is unaffected


def test_s10_ledger_head_closed_holds_verdict_keeps_run_rate(client, db, monkeypatch):
    _no_kick(monkeypatch)
    now = datetime.now(timezone.utc)
    _advisor_scene(db, now)
    _adv_seed_position(db, 3, first_seen_at=(now - timedelta(days=40)).isoformat(), ledger_covered=False)
    _seed_ledger_position(db, token_id="3", rebalanced_to_token_id="99")
    _seed_ledger_position(db, token_id="99", rebalanced_from_token_id="3", closed_at=(now - timedelta(days=1)).isoformat())
    _seed_ledger_claim(db, "base", "3", "0xh3", (now - timedelta(days=2)).isoformat(), 5000.0)
    pos = _adv_pos(_advisor(client), 3)
    _assert_held(pos, "ledger_head_closed")
    # the claims still count: 5000 / 10000 / 7 x 100
    assert pos["run_rate_7d_pct_day"] == pytest.approx(5000.0 / 10000.0 / 7.0 * 100.0)
    assert pos["window_earned_usd"] == pytest.approx(5000.0)
    assert pos["claims_provenance"]["ledger_head_closed"] is True
    assert pos["claims_provenance"]["ledger_state"] == "covered"


# ── S11: the advisor's "ledger" block and load failure ─────────────────────

def test_s11_ledger_block_as_of_and_unattributed(client, db, env, monkeypatch):
    _no_kick(monkeypatch)
    _advisor_scene(db, datetime.now(timezone.utc))
    env.last_run("base", T.isoformat())
    env.last_run("robinhood", T.isoformat(), dry_run=True)
    owner = "0x" + "D" * 40
    _seed_ledger_position(db, token_id="700", owner=owner)          # a lineage no app row reaches
    _seed_ledger_claim(db, "base", "700", "0xu1", _ts(1), 3.0)
    _seed_reward(db, "700", "0xu2", "verified", _ts(2), 1.0)
    _seed_reward(db, "700", "0xu3", "mismatch", _ts(3), 50.0)      # not counted
    body = _advisor(client)
    ledger = body["ledger"]
    expected_as_of = {chain: None for chain in wp.MAXFI_CHAINS}
    expected_as_of["base"] = T.isoformat()
    assert ledger["as_of"] == expected_as_of
    assert ledger["unavailable"] is False
    # fee 3.0 + counted reward 1.0 = 4.0, 2 claims
    assert ledger["unattributed"] == [
        {"chain": "base", "owner": owner.lower(), "root_token_id": "700", "head_token_id": "700",
         "token_count": 1, "fee_claimed_usd": 3.0, "reward_claimed_usd": 1.0, "claimed_usd": 4.0,
         "claim_count": 2, "unpriced_claims": 0},
    ]
    assert ledger["unattributed_totals"] == {"base": {
        "lineage_count": 1, "fee_claimed_usd": 3.0, "reward_claimed_usd": 1.0, "claimed_usd": 4.0,
        "claim_count": 2, "unpriced_claims": 0}}


def test_s11_advisor_load_failure(client, db, monkeypatch):
    _no_kick(monkeypatch)
    now = datetime.now(timezone.utc)
    _advisor_scene(db, now)
    _adv_seed_position(db, 2, first_seen_at=(now - timedelta(days=40)).isoformat(), ledger_covered=False)
    monkeypatch.setattr(wp, "_maxfi_ledger_load_inputs", _boom)
    body = _advisor(client)
    assert body["claims_unavailable"] is True
    assert body["ledger"]["unavailable"] is True
    assert body["positions"]
    for pos in body["positions"]:
        _assert_held(pos, "claims_unavailable")
        for k in R6_FIGURES:
            assert pos[k] is None, k
        assert pos["pct_7d"] is not None
        assert pos["claims_provenance"] == {"source": "ledger", "unavailable": True}


def test_s11_routes_make_no_rpc(client, db, monkeypatch):
    _no_kick(monkeypatch)
    _forbid_rpc(monkeypatch)
    _advisor_scene(db, datetime.now(timezone.utc))
    _seed_position(db, 2, token_id="200", status="closed", closed_at=_ts(20))
    _link(db, ["200"], closed={"200": _ts(20)}, exit_price_usd=90.0)
    _fee(db, "200", "0xwd", _ts(20), 7.0)
    _withdraw(db, "200", "0xwd", _ts(20))
    assert _rows(client)[2]["claims_provenance"]["final_claim_included"] is True    # no closing value
    assert _adv_pos(_advisor(client), 1)["verdict"] == "HOLD"
