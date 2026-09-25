"""Ledger-as-source commit 1 - per-position ledger claims, exposed as the
additive comparison key "ledger_shadow" on GET /api/maxfi/positions/<chain>/
<wallet> and GET /api/maxfi/advisor. No displayed value changes: claimed_usd,
the advisor's verdict/run rates and every existing key stay manual-claims
based; ledger_shadow only sits beside them for a production comparison.

Rulings under test:
- row -> lineage mapping is the existing _maxfi_ledger_lineage_assignment
  (the reconciliation route's mapping), unchanged;
- a row is "covered" iff its current (chain, token_id) has a
  maxfi_ledger_positions row;
- a CLOSED row's final withdraw-tx fee claim is excluded from Claimed and
  reported separately (final_claim_usd) - manual closing values include it;
- verified / verified_aggregate AERO rewards count, never as a final claim;
- the ledger verdict's accrual anchor uses the latest FEE claim only.

Seeding helpers and the client/db fixtures are IMPORTED from
tests/test_maxfi_ledger_reconciliation.py (precedent:
tests/test_maxfi_ledger_lineage_rollup.py) - underscore helpers and fixtures
only, never a test_* function. The advisor seeders come from
tests/test_maxfi_advisor.py under aliases (both modules define
_seed_position); that module's own client/advisor_db fixtures are NOT
imported. Every expected value is hand-computed from the seeded rows.

The advisor-route tests stub wp._maybe_kick_metrics_auto_refresh to return
[] (its real return type): with no fresh maxfi_pool_metrics row it would
otherwise spawn a background DexScreener refresh thread - a network call
this read-only comparison must never trigger (T15)."""
from datetime import datetime, timedelta, timezone

import pytest

import web_portfolio as wp

from test_maxfi_ledger_reconciliation import (  # noqa: F401  (client/db are fixtures)
    RECON_URL,
    _forbid_rpc,
    _get_position,
    _seed_claim,
    _seed_closing_value,
    _seed_ledger_claim,
    _seed_ledger_event,
    _seed_ledger_position,
    _seed_position,
    client,
    db,
)
from test_maxfi_advisor import (
    WALLET as ADV_WALLET,
    _seed_catalogue_pool as _adv_seed_catalogue_pool,
    _seed_claim as _adv_seed_claim,
    _seed_metrics as _adv_seed_metrics,
    _seed_position as _adv_seed_position,
    _seed_token_daily as _adv_seed_token_daily,
)

WALLET = "0x" + "a" * 40          # test_maxfi_ledger_reconciliation._seed_position's default
POSITIONS_URL = f"/api/maxfi/positions/base/{WALLET}"
ADVISOR_URL = "/api/maxfi/advisor"
AERO = "0x940181a94a35a4569e4529a3cdfb74e38fd98631"

SHADOW_KEYS = {
    "covered", "lineage_token_count", "fee_claimed_usd", "reward_claimed_usd", "claimed_usd",
    "final_claim_usd", "final_claim_unpriced", "claim_count", "unpriced_claims",
    "last_fee_claim_at", "ledger_head_closed",
}
ADVISOR_SHADOW_KEYS = {
    "covered", "claimed_usd", "claim_count", "unpriced_claims", "ledger_head_closed",
    "uncollected_accrual_days", "verdict", "run_rate_7d_pct_day", "run_rate_lifetime_pct_day",
    "window_earned_usd", "lifetime_earned_usd", "threshold_pct_day", "margin_pct_day", "flags",
}


# ── local seed helpers ─────────────────────────────────────────────────────

def _seed_reward(db, token_id, tx_hash, status, block_timestamp, net_usd, chain="base", reward_token=AERO):
    """One maxfi_ledger_reward_claims row - modelled on
    tests/test_maxfi_ledger_emissions_c5.py::_seed_reward_claim, with the
    block_timestamp and tx_hash under the caller's control."""
    db.execute(
        """
        INSERT INTO maxfi_ledger_reward_claims
        (chain, tx_hash, token_id, reward_token, log_index, block_number, block_timestamp,
         gross_wei, fee_wei, treasury_wei, referral_wei, net_wei, verification_status, net_usd, computed_at)
        VALUES (?, ?, ?, ?, 1, 100, ?, '10', '0', '0', '0', '10', ?, ?, '2026-09-24T00:00:00+00:00')
        """,
        (chain, tx_hash, token_id, reward_token, block_timestamp, status, net_usd),
    )
    db.commit()


def _link(db, tokens, chain="base", closed=None, exit_price_usd=None):
    """A linear ledger lineage tokens[0] -> ... -> tokens[-1]. `closed` names
    tokens whose ledger row carries closed_at (a withdrawn token)."""
    closed = closed or {}
    for i, t in enumerate(tokens):
        _seed_ledger_position(
            db, chain=chain, token_id=t,
            rebalanced_from_token_id=tokens[i - 1] if i > 0 else None,
            rebalanced_to_token_id=tokens[i + 1] if i + 1 < len(tokens) else None,
            closed_at=closed.get(t),
            exit_price_usd=exit_price_usd if t in closed else None,
        )


def _fee(db, token_id, tx_hash, ts, usd, fh_event=False, chain="base"):
    """A maxfi_ledger_claims row, optionally with its FeesHarvested event in
    the same tx (the reconciliation route pairs claims through events)."""
    _seed_ledger_claim(db, chain, token_id, tx_hash, ts, usd)
    if fh_event:
        _seed_ledger_event(db, chain, token_id, "FeesHarvested", ts, {"token_id": int(token_id)}, tx_hash=tx_hash)


def _withdraw(db, token_id, tx_hash, ts, block_number=1, chain="base"):
    # log_index 5: the same tx may also carry a FeesHarvested event (log_index
    # 0), and maxfi_ledger_events is unique on (chain, tx_hash, log_index).
    _seed_ledger_event(db, chain, token_id, "PositionWithdrawn", ts, {"token_id": int(token_id)},
                       tx_hash=tx_hash, block_number=block_number, log_index=5)


def _shadows(client):
    r = client.get(POSITIONS_URL)
    assert r.status_code == 200
    return {row["id"]: row for row in r.get_json()}


def _ts(day, month=3):
    return f"2026-{month:02d}-{day:02d}T00:00:00+00:00"


def _pure(app_rows, ledger_rows=(), claim_rows=(), reward_rows=(), withdraw_events=()):
    return wp._maxfi_ledger_position_claims(list(app_rows), list(ledger_rows), list(claim_rows),
                                            list(reward_rows), list(withdraw_events))


def _ledger_row(token_id, frm=None, to=None, closed_at=None, chain="base"):
    return {"chain": chain, "token_id": token_id, "rebalanced_from_token_id": frm,
            "rebalanced_to_token_id": to, "closed_at": closed_at,
            "exit_amount0_wei": None, "exit_price_usd": None}


# ── T1-T4: lineage mapping and coverage ────────────────────────────────────

def test_t1_linear_lineage_head_row_counts_every_token(client, db):
    _seed_position(db, 1, token_id="300")
    _link(db, ["100", "200", "300"])
    _fee(db, "100", "0xa1", _ts(1), 10.0)
    _fee(db, "200", "0xa2", _ts(2), 20.0)
    _fee(db, "300", "0xa3", _ts(3), 30.0)
    s = _shadows(client)[1]["ledger_shadow"]
    assert s["covered"] is True
    assert s["lineage_token_count"] == 3
    assert s["claim_count"] == 3
    assert s["fee_claimed_usd"] == 60.0 and s["claimed_usd"] == 60.0
    assert s["unpriced_claims"] == 0


def test_t2_rebalance_gap_row_absent_from_ledger_is_uncovered(client, db):
    _seed_position(db, 1, token_id="500")
    _link(db, ["100", "200"])                  # an earlier lineage that reaches no app row
    _fee(db, "100", "0xb1", _ts(1), 11.0)
    _fee(db, "200", "0xb2", _ts(2), 22.0)
    s = _shadows(client)[1]["ledger_shadow"]
    assert s["covered"] is False
    assert s["claim_count"] == 0
    assert s["claimed_usd"] == 0.0
    assert s["lineage_token_count"] == 1


def test_t3_two_rows_on_one_lineage_split_at_the_later_rows_token(client, db):
    _seed_position(db, 1, token_id="100")
    _seed_position(db, 2, token_id="300")
    _link(db, ["100", "200", "300", "400"])
    _fee(db, "100", "0xc1", _ts(1), 1.0)
    _fee(db, "200", "0xc2", _ts(2), 2.0)
    _fee(db, "300", "0xc3", _ts(3), 4.0)
    _fee(db, "400", "0xc4", _ts(4), 8.0)
    rows = _shadows(client)
    s1, s2 = rows[1]["ledger_shadow"], rows[2]["ledger_shadow"]
    assert (s1["claimed_usd"], s1["claim_count"]) == (3.0, 2)
    assert (s2["claimed_usd"], s2["claim_count"]) == (12.0, 2)
    assert s1["claimed_usd"] + s2["claimed_usd"] == 15.0      # the lineage total, nothing twice
    assert s1["lineage_token_count"] == s2["lineage_token_count"] == 4


def test_t4_duplicate_rows_on_one_token_lowest_id_owns(client, db):
    # maxfi_positions is unique on (chain, wallet, token_id) among OPEN rows,
    # so the higher-id duplicate is a closed row on the same token.
    _seed_position(db, 1, token_id="100")
    _seed_position(db, 2, token_id="100", status="closed", closed_at=_ts(9))
    _link(db, ["100"])
    _fee(db, "100", "0xd1", _ts(1), 5.0)
    rows = _shadows(client)
    assert (rows[1]["ledger_shadow"]["claim_count"], rows[1]["ledger_shadow"]["claimed_usd"]) == (1, 5.0)
    assert (rows[2]["ledger_shadow"]["claim_count"], rows[2]["ledger_shadow"]["claimed_usd"]) == (0, 0.0)


# ── T5-T7: the final withdraw-tx claim ─────────────────────────────────────

def _closed_scene(db, final_usd, pid=1):
    _seed_position(db, pid, token_id="200", status="closed", closed_at=_ts(20))
    _link(db, ["100", "200"], closed={"200": _ts(20)}, exit_price_usd=90.0)
    _fee(db, "100", "0xe1", _ts(1), 10.0)
    _fee(db, "200", "0xe2", _ts(2), 3.0)
    _fee(db, "200", "0xWD", _ts(20), final_usd)       # the withdraw tx's own fee claim
    _withdraw(db, "200", "0xwd", _ts(20))              # lowercase hash on the event


def test_t5_closed_row_excludes_its_withdraw_tx_claim(client, db):
    _closed_scene(db, 7.0)
    s = _shadows(client)[1]["ledger_shadow"]
    assert s["fee_claimed_usd"] == 13.0 and s["claimed_usd"] == 13.0
    assert s["final_claim_usd"] == 7.0 and s["final_claim_unpriced"] is False
    assert s["claim_count"] == 2
    assert s["last_fee_claim_at"] == _ts(2)
    assert s["ledger_head_closed"] is False
    assert "claims" not in s                            # the list is advisor-internal


def test_t5_pure_claims_list_excludes_the_final_claim():
    out = _pure(
        [(1, "base", "200", "closed")],
        [_ledger_row("100", to="200"), _ledger_row("200", frm="100", closed_at=_ts(20))],
        [("base", "100", "0xe1", _ts(1), 10.0), ("base", "200", "0xe2", _ts(2), 3.0),
         ("base", "200", "0xWD", _ts(20), 7.0)],
        [],
        [("base", "200", "0xwd", 50)],
    )[1]
    assert out["claims"] == [(_ts(1), 10.0), (_ts(2), 3.0)]
    assert out["final_claim_usd"] == 7.0 and out["fee_claimed_usd"] == 13.0


def test_t5_pure_highest_block_withdraw_is_the_final_tx():
    out = _pure(
        [(1, "base", "200", "closed")],
        [_ledger_row("200", closed_at=_ts(20))],
        [("base", "200", "0xold", _ts(10), 4.0), ("base", "200", "0xnew", _ts(20), 6.0)],
        [],
        [("base", "200", "0xnew", 9), ("base", "200", "0xold", 5)],
    )[1]
    assert out["final_claim_usd"] == 6.0
    assert out["fee_claimed_usd"] == 4.0 and out["claim_count"] == 1


def test_t6_unpriced_withdraw_claim_is_final_unpriced_not_counted_unpriced(client, db):
    _closed_scene(db, None)
    s = _shadows(client)[1]["ledger_shadow"]
    assert s["final_claim_usd"] is None
    assert s["final_claim_unpriced"] is True
    assert s["unpriced_claims"] == 0
    assert s["fee_claimed_usd"] == 13.0 and s["claim_count"] == 2


def test_t7_open_row_with_closed_ledger_head_keeps_every_claim(client, db):
    _seed_position(db, 1, token_id="100")
    _link(db, ["100", "200"], closed={"200": _ts(20)}, exit_price_usd=90.0)
    _fee(db, "100", "0xf1", _ts(1), 10.0)
    _fee(db, "200", "0xwd", _ts(20), 7.0)
    _withdraw(db, "200", "0xwd", _ts(20))
    s = _shadows(client)[1]["ledger_shadow"]
    assert s["ledger_head_closed"] is True
    assert s["fee_claimed_usd"] == 17.0 and s["claim_count"] == 2
    assert s["final_claim_usd"] is None and s["final_claim_unpriced"] is False


# ── T8-T10: unpriced claims, rewards, the fee-only accrual anchor ──────────

def test_t8_unpriced_fee_claim_is_excluded_from_sums_and_listed(client, db):
    _seed_position(db, 1, token_id="100")
    _link(db, ["100"])
    _fee(db, "100", "0xg1", _ts(1), 5.0)
    _fee(db, "100", "0xg2", _ts(2), None)
    s = _shadows(client)[1]["ledger_shadow"]
    assert s["fee_claimed_usd"] == 5.0 and s["claimed_usd"] == 5.0
    assert s["unpriced_claims"] == 1 and s["claim_count"] == 2
    out = _pure([(1, "base", "100", "open")], [_ledger_row("100")],
                [("base", "100", "0xg1", _ts(1), 5.0), ("base", "100", "0xg2", _ts(2), None)])[1]
    assert out["claims"] == [(_ts(1), 5.0), (_ts(2), None)]


def test_t9_only_counted_reward_statuses_count(client, db):
    _seed_position(db, 1, token_id="100")
    _link(db, ["100"])
    _fee(db, "100", "0xh0", _ts(1), 1.0)
    _seed_reward(db, "100", "0xh1", "verified", _ts(2), 2.0)
    _seed_reward(db, "100", "0xh2", "verified_aggregate", _ts(3), 3.0)
    _seed_reward(db, "100", "0xh3", "verified", _ts(4), None)
    for i, status in enumerate(["fee_without_claim", "window_unknown", "out_of_window", "gross_disagreement",
                                "mismatch", "no_payout", "ambiguous"]):
        _seed_reward(db, "100", f"0xhx{i}", status, _ts(5), 100.0)
    s = _shadows(client)[1]["ledger_shadow"]
    assert s["reward_claimed_usd"] == 5.0
    assert s["fee_claimed_usd"] == 1.0
    assert s["claimed_usd"] == 6.0
    assert s["claim_count"] == 4 and s["unpriced_claims"] == 1
    out = _pure([(1, "base", "100", "open")], [_ledger_row("100")],
                [("base", "100", "0xh0", _ts(1), 1.0)],
                [("base", "100", "0xh1", AERO, "verified", _ts(2), 2.0),
                 ("base", "100", "0xh2", AERO, "verified_aggregate", _ts(3), 3.0),
                 ("base", "100", "0xh3", AERO, "verified", _ts(4), None),
                 ("base", "100", "0xhx", AERO, "mismatch", _ts(5), 100.0)])[1]
    assert out["claims"] == [(_ts(1), 1.0), (_ts(2), 2.0), (_ts(3), 3.0), (_ts(4), None)]


def test_t9_reward_on_a_closed_rows_withdraw_tx_is_never_the_final_claim(client, db):
    _closed_scene(db, 7.0)
    _seed_reward(db, "200", "0xwd", "verified", _ts(20), 2.5)
    s = _shadows(client)[1]["ledger_shadow"]
    assert s["reward_claimed_usd"] == 2.5 and s["final_claim_usd"] == 7.0
    assert s["claimed_usd"] == 15.5 and s["claim_count"] == 3


def test_t10_newer_reward_does_not_move_last_fee_claim_at(client, db):
    _seed_position(db, 1, token_id="100")
    _link(db, ["100"])
    _fee(db, "100", "0xi1", _ts(1), 1.0)
    _seed_reward(db, "100", "0xi2", "verified", _ts(5), 2.0)
    assert _shadows(client)[1]["ledger_shadow"]["last_fee_claim_at"] == _ts(1)


# ── T11: parity with the reconciliation route ──────────────────────────────

def test_t11_parity_with_reconciliation_claims(client, db):
    # row 1: open, multi-token lineage 10 -> 11 -> 12, app row on the head
    _seed_position(db, 1, token_id="12")
    _link(db, ["10", "11", "12"])
    _fee(db, "10", "0xp10", _ts(1), 1.5, fh_event=True)
    _fee(db, "11", "0xp11", _ts(2), 2.5, fh_event=True)
    _fee(db, "12", "0xp12", _ts(3), None, fh_event=True)     # unpriced on both sides
    _fee(db, "12", "0xp12b", _ts(4), 4.0, fh_event=True)
    _seed_claim(db, 1, _ts(4), 4.0)                          # pairs with 0xp12b in the recon
    # row 2: closed, lineage 20 -> 21, withdraw claim on 21
    _seed_position(db, 2, token_id="21", status="closed", closed_at=_ts(25))
    _link(db, ["20", "21"], closed={"21": _ts(25)}, exit_price_usd=50.0)
    _fee(db, "20", "0xp20", _ts(5), 1.0, fh_event=True)
    _fee(db, "21", "0xp21", _ts(6), 2.0, fh_event=True)
    _fee(db, "21", "0xpwd", _ts(25), 4.0, fh_event=True)
    _withdraw(db, "21", "0xpwd", _ts(25))
    _seed_closing_value(db, 2, 54.0)
    # rows 3 and 4: two app rows on one lineage 30 -> 31 -> 32
    _seed_position(db, 3, token_id="30")
    _seed_position(db, 4, token_id="32")
    _link(db, ["30", "31", "32"])
    _fee(db, "30", "0xp30", _ts(7), 0.25, fh_event=True)
    _fee(db, "31", "0xp31", _ts(8), 0.5, fh_event=True)
    _fee(db, "32", "0xp32", _ts(9), 0.75, fh_event=True)
    _seed_reward(db, "32", "0xp32r", "verified", _ts(9), 9.0)   # rewards are outside the recon's claims

    shadows = _shadows(client)
    r = client.get(RECON_URL)
    assert r.status_code == 200
    recon = r.get_json()
    expected = {1: 8.0, 2: 7.0, 3: 0.75, 4: 0.75}               # hand-computed fee totals incl. final
    for pid, total in expected.items():
        s = shadows[pid]["ledger_shadow"]
        claims = _get_position(recon, pid)["claims"]
        recon_total = (sum(c["ledger_usd"] for c in claims["claims"] if c["ledger_usd"] is not None)
                       + sum(e["ledger_usd"] for e in claims["unpaired_ledger_events"] if e["ledger_usd"] is not None))
        assert s["fee_claimed_usd"] + (s["final_claim_usd"] or 0) == pytest.approx(recon_total), pid
        assert recon_total == pytest.approx(total), pid
    assert shadows[2]["ledger_shadow"]["final_claim_usd"] == 4.0


# ── T12: the positions route ───────────────────────────────────────────────

def test_t12_positions_route_adds_ledger_shadow_and_keeps_manual_claimed(client, db):
    _seed_position(db, 1, token_id="200")
    _link(db, ["100", "200"])
    _fee(db, "100", "0xj1", _ts(1), 10.0)
    _fee(db, "200", "0xj2", _ts(2), 15.0)
    _fee(db, "200", "0xj3", _ts(3), None)
    _seed_reward(db, "200", "0xj4", "verified", _ts(4), 2.0)
    _seed_claim(db, 1, _ts(2), 99.0)                   # manual total differs on purpose
    row = _shadows(client)[1]
    assert row["claimed_usd"] == 99.0
    assert row["claims_unavailable"] is False
    assert row["ledger_shadow"] == {
        "covered": True, "lineage_token_count": 2,
        "fee_claimed_usd": 25.0, "reward_claimed_usd": 2.0, "claimed_usd": 27.0,
        "final_claim_usd": None, "final_claim_unpriced": False,
        "claim_count": 4, "unpriced_claims": 1,
        "last_fee_claim_at": _ts(3), "ledger_head_closed": False,
    }
    assert set(row["ledger_shadow"]) == SHADOW_KEYS


# ── T13-T15: the advisor route, fail-soft, no RPC ──────────────────────────

def _advisor_scene(db, now):
    """Manual claims say CLOSE, ledger claims say HOLD. Decay: the volatile
    token fell 1.2 -> 1.0 over the 7-day base, pct_7d = -16.667%, so
    decay = 16.667 / 7 = 2.381 %/day and the HOLD threshold is 2 x 2.381 =
    4.762 %/day. Manual: $20 in the window -> 20 / 10000 / 7 x 100 =
    0.0286 %/day -> CLOSE. Ledger: $5000 fee + $1 reward in the window ->
    5001 / 10000 / 7 x 100 = 7.1443 %/day -> HOLD."""
    today = now.date()
    _adv_seed_position(db, 1, first_seen_at=(now - timedelta(days=40)).isoformat())
    _adv_seed_claim(db, 1, (now - timedelta(days=5)).isoformat(), 20.0)
    _adv_seed_catalogue_pool(db)
    _adv_seed_metrics(db)
    _adv_seed_token_daily(db, date=(today - timedelta(days=8)).isoformat(), close_usd=1.2)
    _adv_seed_token_daily(db, date=(today - timedelta(days=1)).isoformat(), close_usd=1.0)
    _seed_ledger_position(db, chain="base", token_id="1")
    _seed_ledger_claim(db, "base", "1", "0xk1", (now - timedelta(days=2)).isoformat(), 5000.0)
    _seed_reward(db, "1", "0xk2", "verified", (now - timedelta(days=1)).isoformat(), 1.0)


def _adv_pos(body, position_id):
    return next(p for p in body["positions"] if p["id"] == position_id)


def _no_kick(monkeypatch):
    monkeypatch.setattr(wp, "_maybe_kick_metrics_auto_refresh", lambda: [])


def test_t13_advisor_route_ledger_verdict_beside_the_unchanged_manual_one(client, db, monkeypatch):
    _no_kick(monkeypatch)
    _advisor_scene(db, datetime.now(timezone.utc))
    r = client.get(ADVISOR_URL)
    assert r.status_code == 200
    body = r.get_json()
    assert body["ledger_shadow_unavailable"] is False
    pos = _adv_pos(body, 1)
    assert pos["verdict"] == "CLOSE"
    assert pos["run_rate_7d_pct_day"] == pytest.approx(20.0 / 10000.0 / 7.0 * 100.0)
    s = pos["ledger_shadow"]
    assert set(s) == ADVISOR_SHADOW_KEYS
    assert s["verdict"] == "HOLD"
    assert s["run_rate_7d_pct_day"] == pytest.approx(5001.0 / 10000.0 / 7.0 * 100.0)
    assert s["window_earned_usd"] == pytest.approx(5001.0)
    assert s["lifetime_earned_usd"] == pytest.approx(5001.0)
    assert s["threshold_pct_day"] == pytest.approx(2.0 * (1.0 - 1.0 / 1.2) * 100.0 / 7.0)
    assert s["uncollected_accrual_days"] == pytest.approx(2.0, abs=0.01)   # the fee claim, not the reward
    assert (s["covered"], s["claimed_usd"], s["claim_count"], s["unpriced_claims"], s["ledger_head_closed"]) == (
        True, 5001.0, 2, 0, False)


def test_t14_fail_soft_when_the_loader_raises(client, db, monkeypatch):
    _no_kick(monkeypatch)
    _advisor_scene(db, datetime.now(timezone.utc))
    _seed_position(db, 2, token_id="200")                  # a positions-route row (wallet 0xaa..)
    _seed_claim(db, 2, _ts(2), 12.0)
    before_positions = _shadows(client)
    before_verdict = _adv_pos(client.get(ADVISOR_URL).get_json(), 1)["verdict"]

    def _boom(*a, **k):
        raise RuntimeError("ledger load failed")

    monkeypatch.setattr(wp, "_maxfi_ledger_load_position_claims", _boom)
    rows = _shadows(client)
    assert rows and all(row["ledger_shadow"] == {"unavailable": True} for row in rows.values())
    assert rows[2]["claimed_usd"] == before_positions[2]["claimed_usd"] == 12.0
    r = client.get(ADVISOR_URL)
    assert r.status_code == 200
    body = r.get_json()
    assert body["ledger_shadow_unavailable"] is True
    assert body["positions"] and all(p["ledger_shadow"] == {"unavailable": True} for p in body["positions"])
    assert _adv_pos(body, 1)["verdict"] == before_verdict == "CLOSE"


def test_t15_both_routes_run_without_pricing_or_rpc(client, db, monkeypatch):
    _no_kick(monkeypatch)
    _forbid_rpc(monkeypatch)
    _advisor_scene(db, datetime.now(timezone.utc))
    _closed_scene(db, 7.0, pid=2)                          # id 1 is the advisor scene's row
    rows = _shadows(client)
    assert rows[2]["ledger_shadow"]["final_claim_usd"] == 7.0
    r = client.get(ADVISOR_URL)
    assert r.status_code == 200
    assert _adv_pos(r.get_json(), 1)["ledger_shadow"]["verdict"] == "HOLD"
