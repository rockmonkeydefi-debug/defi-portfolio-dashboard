"""Adjudication 2 (3b.3b-adj-2) - exit and basis comparison basis in
GET /api/maxfi/ledger-reconciliation (HANDOFF_maxfi_ledger.md).

EXIT: compared figure = wallet-received = the exit token's principal-only
exit_price_usd + the NET claim of that token's withdraw tx
(maxfi_ledger_claims joined on (chain, token_id, tx_hash)). The exit token
is the head-most withdrawn token among the row's adj-1 assigned tokens.
BASIS: compared figure = the lineage ROOT token's basis_price_usd; the
own-token and segment-start bases are informational context only.
Tolerance for both: max($1.00 floor, 1% of the manual figure).

Every expected value below is hand-computed from the seeded data, never
derived from the code under test. Helpers/fixtures are imported (underscore
names and fixtures only, never a test_* function).
"""
import web_portfolio as wp

from test_maxfi_ledger_reconciliation import (  # noqa: F401  (client/db are fixtures)
    RECON_URL,
    _forbid_rpc,
    _get_position,
    _seed_closing_value,
    _seed_initial_value,
    _seed_ledger_claim,
    _seed_ledger_event,
    _seed_ledger_position,
    _seed_position,
    client,
    db,
)
from test_maxfi_ledger_lineage_rollup import _link

TX_W = "0x" + "e1" * 32
TX_H = "0x" + "e2" * 32


def _withdraw(db, chain, token_id, ts, tx, claim_usd="absent"):
    """PositionWithdrawn event on (chain, token_id) in tx; optionally the
    same-tx NET claim row ("absent" = no claim row; None = unpriced)."""
    _seed_ledger_event(db, chain, token_id, "PositionWithdrawn", ts,
                       {"token_id": int(token_id), "amount0": 1, "amount1": 1}, tx_hash=tx)
    if claim_usd != "absent":
        _seed_ledger_claim(db, chain, token_id, tx.lower(), ts, claim_usd)


# ── tolerance helper ─────────────────────────────────────────────────────

def test_basis_exit_tolerance_helper_floor_and_one_percent():
    t = wp._maxfi_ledger_basis_exit_tolerance
    assert t(None) == 1.0
    assert t(0.0) == 1.0
    assert t(50.0) == 1.0
    assert t(100.0) == 1.0
    assert t(250.0) == 2.5
    assert t(1000.0) == 10.0


# ── exit ─────────────────────────────────────────────────────────────────

def test_exit_wallet_received_adds_withdraw_tx_claim_matched(client, db):
    _seed_position(db, 1, token_id="1", status="closed", closed_at="2026-02-01T00:00:00+00:00")
    _seed_closing_value(db, 1, 110.0)
    _seed_ledger_position(db, token_id="1", closed_at="2026-02-01T00:00:00Z", exit_price_usd=100.0)
    _withdraw(db, "base", "1", "2026-02-01T00:00:00Z", TX_W, 10.0)

    pos = _get_position(client.get(RECON_URL).get_json(), 1)
    assert pos["exit"]["status"] == "matched"
    ctx = pos["exit"]["ledger_context"]
    assert ctx["exit_price_usd"] == 100.0
    assert ctx["final_claim_usd"] == 10.0
    assert ctx["wallet_received_usd"] == 110.0
    assert ctx["exit_token_id"] == "1"
    assert ctx["withdrawn_token_count"] == 1


def test_exit_principal_only_manual_entry_is_now_a_mismatch(client, db):
    _seed_position(db, 1, token_id="1", status="closed", closed_at="2026-02-01T00:00:00+00:00")
    _seed_closing_value(db, 1, 100.0)  # |100 - 110| = 10 > max(1, 1.00)
    _seed_ledger_position(db, token_id="1", closed_at="2026-02-01T00:00:00Z", exit_price_usd=100.0)
    _withdraw(db, "base", "1", "2026-02-01T00:00:00Z", TX_W, 10.0)

    pos = _get_position(client.get(RECON_URL).get_json(), 1)
    assert pos["exit"]["status"] == "mismatch"


def test_exit_other_tx_claim_is_not_added_no_withdraw_claim_adds_zero(client, db):
    _seed_position(db, 1, token_id="1", status="closed", closed_at="2026-02-01T00:00:00+00:00")
    _seed_closing_value(db, 1, 200.0)
    _seed_ledger_position(db, token_id="1", closed_at="2026-02-01T00:00:00Z", exit_price_usd=200.0)
    _withdraw(db, "base", "1", "2026-02-01T00:00:00Z", TX_W)  # no claim row in the withdraw tx
    _seed_ledger_claim(db, "base", "1", TX_H, "2026-01-20T00:00:00Z", 5.0)  # earlier harvest

    pos = _get_position(client.get(RECON_URL).get_json(), 1)
    assert pos["exit"]["status"] == "matched"
    assert pos["exit"]["ledger_context"]["final_claim_usd"] == 0.0
    assert pos["exit"]["ledger_context"]["wallet_received_usd"] == 200.0


def test_exit_unpriced_withdraw_claim_is_ledger_unpriced(client, db):
    _seed_position(db, 1, token_id="1", status="closed", closed_at="2026-02-01T00:00:00+00:00")
    _seed_closing_value(db, 1, 110.0)
    _seed_ledger_position(db, token_id="1", closed_at="2026-02-01T00:00:00Z", exit_price_usd=100.0)
    _withdraw(db, "base", "1", "2026-02-01T00:00:00Z", TX_W, None)

    pos = _get_position(client.get(RECON_URL).get_json(), 1)
    assert pos["exit"]["status"] == "ledger_unpriced"
    assert pos["exit"]["ledger_context"]["final_claim_usd"] is None
    assert pos["exit"]["ledger_context"]["wallet_received_usd"] is None


def test_exit_withdraw_tx_join_is_case_insensitive(client, db):
    _seed_position(db, 1, token_id="1", status="closed", closed_at="2026-02-01T00:00:00+00:00")
    _seed_closing_value(db, 1, 110.0)
    _seed_ledger_position(db, token_id="1", closed_at="2026-02-01T00:00:00Z", exit_price_usd=100.0)
    _seed_ledger_event(db, "base", "1", "PositionWithdrawn", "2026-02-01T00:00:00Z",
                       {"token_id": 1, "amount0": 1, "amount1": 1}, tx_hash="0x" + "AB" * 32)
    _seed_ledger_claim(db, "base", "1", "0x" + "ab" * 32, "2026-02-01T00:00:00Z", 10.0)

    pos = _get_position(client.get(RECON_URL).get_json(), 1)
    assert pos["exit"]["ledger_context"]["final_claim_usd"] == 10.0
    assert pos["exit"]["status"] == "matched"


def test_exit_row_on_rebalanced_token_reads_withdrawn_successor(client, db):
    """The pos 113/114 shape: the app row holds 100, the chain moved on to
    200, which was withdrawn. Before adj-2 this row read manual_only."""
    _seed_position(db, 1, token_id="100", status="closed", closed_at="2026-03-01T00:00:00+00:00")
    _seed_closing_value(db, 1, 305.0)
    _link(db, "base", ["100", "200"], **{
        "200": {"closed_at": "2026-03-01T00:00:00Z", "exit_price_usd": 300.0},
    })
    _withdraw(db, "base", "200", "2026-03-01T00:00:00Z", TX_W, 5.0)

    pos = _get_position(client.get(RECON_URL).get_json(), 1)
    assert pos["exit"]["status"] == "matched"
    assert pos["exit"]["ledger_context"]["exit_token_id"] == "200"
    assert pos["exit"]["ledger_context"]["wallet_received_usd"] == 305.0


def test_exit_two_app_rows_on_one_lineage_exit_goes_to_later_row(client, db):
    """The pos 5/34 shape: chain 1->2->3->4, app rows on 1 and 3; the head
    (4) is withdrawn and belongs to the later row only - never counted twice."""
    _seed_position(db, 5, token_id="1", status="closed", closed_at="2026-03-01T00:00:00+00:00")
    _seed_position(db, 34, token_id="3", status="closed", closed_at="2026-03-04T00:00:00+00:00")
    _seed_closing_value(db, 34, 400.0)
    _link(db, "base", ["1", "2", "3", "4"], **{
        "4": {"closed_at": "2026-03-04T00:00:00Z", "exit_price_usd": 400.0},
    })

    body = client.get(RECON_URL).get_json()
    p5, p34 = _get_position(body, 5), _get_position(body, 34)
    assert p34["exit"]["status"] == "matched"
    assert p34["exit"]["ledger_context"]["exit_token_id"] == "4"
    assert p5["exit"]["status"] == "no_data"
    assert p5["exit"]["ledger_context"]["exit_token_id"] is None
    assert p5["exit"]["ledger_context"]["withdrawn_token_count"] == 0
    assert body["summary"]["exit"]["matched"] == 1
    assert body["summary"]["exit"]["no_data"] == 1


def test_exit_one_percent_boundary(client, db):
    for pid, exit_usd in ((1, 1010.0), (2, 1011.0)):
        _seed_position(db, pid, token_id=str(pid), status="closed", closed_at="2026-02-01T00:00:00+00:00")
        _seed_closing_value(db, pid, 1000.0)  # tolerance max(1, 10.0) = 10.0
        _seed_ledger_position(db, token_id=str(pid), closed_at="2026-02-01T00:00:00Z", exit_price_usd=exit_usd)

    body = client.get(RECON_URL).get_json()
    assert _get_position(body, 1)["exit"]["status"] == "matched"
    assert _get_position(body, 2)["exit"]["status"] == "mismatch"


# ── basis ────────────────────────────────────────────────────────────────

def test_basis_reads_lineage_root_deposit_for_row_on_rebalanced_child(client, db):
    _seed_position(db, 1, token_id="300")
    _seed_initial_value(db, 1, 200.0)  # tolerance max(1, 2.0) = 2.0
    _link(db, "base", ["100", "200", "300"], **{
        "100": {"opened_at": "2026-01-01T00:00:00Z", "basis_price_usd": 201.0},
        "200": {"opened_at": "2026-01-05T00:00:00Z", "basis_price_usd": 260.0},
        "300": {"opened_at": "2026-01-09T00:00:00Z", "basis_price_usd": 310.0},
    })

    pos = _get_position(client.get(RECON_URL).get_json(), 1)
    assert pos["basis"]["status"] == "matched"
    ctx = pos["basis"]["ledger_context"]
    assert ctx["basis_token_id"] == "100"
    assert ctx["basis_price_usd"] == 201.0
    assert ctx["own_token_basis_usd"] == 310.0
    assert ctx["segment_token_id"] == "100"
    assert ctx["segment_basis_usd"] == 201.0


def test_basis_later_app_row_compares_root_and_reports_its_segment(client, db):
    _seed_position(db, 5, token_id="1")
    _seed_position(db, 34, token_id="3")
    _seed_initial_value(db, 5, 200.0)
    _seed_initial_value(db, 34, 200.0, source="ambiguity_auto_split")
    _link(db, "base", ["1", "2", "3", "4"], **{
        "1": {"opened_at": "2026-01-01T00:00:00Z", "basis_price_usd": 200.0},
        "3": {"opened_at": "2026-01-05T00:00:00Z", "basis_price_usd": 260.0},
    })

    body = client.get(RECON_URL).get_json()
    p5, p34 = _get_position(body, 5), _get_position(body, 34)
    assert p5["basis"]["status"] == "matched"
    assert p34["basis"]["status"] == "matched"
    assert p34["basis"]["ledger_context"]["basis_token_id"] == "1"
    assert p34["basis"]["ledger_context"]["segment_token_id"] == "3"
    assert p34["basis"]["ledger_context"]["segment_basis_usd"] == 260.0


def test_basis_root_present_but_unpriced_is_ledger_unpriced(client, db):
    _seed_position(db, 1, token_id="200")
    _seed_initial_value(db, 1, 284.0)
    _link(db, "base", ["100", "200"], **{
        "100": {"opened_at": "2026-01-01T00:00:00Z", "basis_price_usd": None},
        "200": {"opened_at": "2026-01-05T00:00:00Z", "basis_price_usd": 250.0},
    })

    pos = _get_position(client.get(RECON_URL).get_json(), 1)
    assert pos["basis"]["status"] == "ledger_unpriced"
    assert pos["basis"]["ledger_context"]["own_token_basis_usd"] == 250.0


def test_basis_one_percent_boundary(client, db):
    for pid, basis_usd in ((1, 505.0), (2, 506.0)):
        _seed_position(db, pid, token_id=str(pid))
        _seed_initial_value(db, pid, 500.0)  # tolerance max(1, 5.0) = 5.0
        _seed_ledger_position(db, token_id=str(pid), opened_at="2026-01-01T00:00:00Z", basis_price_usd=basis_usd)

    body = client.get(RECON_URL).get_json()
    assert _get_position(body, 1)["basis"]["status"] == "matched"
    assert _get_position(body, 2)["basis"]["status"] == "mismatch"


# ── unchanged paths / read-only ──────────────────────────────────────────

def test_app_token_without_ledger_row_is_unchanged(client, db):
    _seed_position(db, 1, token_id="9", status="closed", closed_at="2026-02-01T00:00:00+00:00")
    _seed_initial_value(db, 1, 100.0)
    _seed_closing_value(db, 1, 50.0)

    pos = _get_position(client.get(RECON_URL).get_json(), 1)
    assert pos["basis"]["status"] == "manual_only"
    assert pos["basis"]["ledger_context"]["basis_token_id"] == "9"
    assert pos["exit"]["status"] == "manual_only"
    assert pos["exit"]["ledger_context"]["exit_token_id"] is None


def test_adj2_route_makes_no_rpc(client, db, monkeypatch):
    _forbid_rpc(monkeypatch)
    _seed_position(db, 1, token_id="100", status="closed", closed_at="2026-03-01T00:00:00+00:00")
    _seed_initial_value(db, 1, 200.0)
    _seed_closing_value(db, 1, 305.0)
    _link(db, "base", ["100", "200"], **{
        "100": {"opened_at": "2026-01-01T00:00:00Z", "basis_price_usd": 200.0},
        "200": {"closed_at": "2026-03-01T00:00:00Z", "exit_price_usd": 300.0},
    })
    _withdraw(db, "base", "200", "2026-03-01T00:00:00Z", TX_W, 5.0)

    resp = client.get(RECON_URL)
    assert resp.status_code == 200
    pos = _get_position(resp.get_json(), 1)
    assert pos["basis"]["status"] == "matched"
    assert pos["exit"]["status"] == "matched"
