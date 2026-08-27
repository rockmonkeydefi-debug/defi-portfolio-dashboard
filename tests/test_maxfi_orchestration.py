"""Tests for maxfi_orchestration.py (Phase C scan-and-persist).

In-memory SQLite + monkeypatched get_wallet_position_snapshot() /
get_vault_deposit_info() / eth_block_number() - no real network calls.
"""

import sqlite3

import maxfi_client as mc
import maxfi_orchestration as orch
import maxfi_schema


def make_db():
    conn = sqlite3.connect(":memory:")
    maxfi_schema.ensure_maxfi_tables(conn)
    return conn


def pos(idx, token_id, pool="0xPOOL_0", token0="0xTOKEN_A", token1="0xTOKEN_B", fee=3000):
    # token_id is a numeric string throughout - real on-chain token_ids are
    # uint256s stringified, and the OPENED enrichment path does int(token_id).
    return {
        "array_index": idx,
        "token_id": token_id,
        "pool_address": pool,
        "token0_address": token0,
        "token1_address": token1,
        "fee_tier": fee,
    }


def _patch_snapshot(monkeypatch, snapshot):
    monkeypatch.setattr(orch, "get_wallet_position_snapshot", lambda chain, wallet: snapshot)


def _patch_block_number(monkeypatch, n=1000):
    monkeypatch.setattr(orch, "eth_block_number", lambda chain: n)


def _patch_enrichment_success(monkeypatch, deposit_timestamp=1700000000, block_number="999"):
    monkeypatch.setattr(
        orch, "get_vault_deposit_info",
        lambda chain, wallet, token_id: {
            "deposit_timestamp": deposit_timestamp,
            "total_rebalances": 0,
            "block_number": block_number,
        },
    )


def _seed(monkeypatch, conn, snapshot, chain="base", wallet="0xWALLET"):
    """Run an initial scan (all positions land as 'opened') with enrichment
    succeeding for everything, to set up a baseline for a second scan."""
    _patch_snapshot(monkeypatch, snapshot)
    _patch_block_number(monkeypatch, 1000)
    _patch_enrichment_success(monkeypatch)
    return orch.run_scan_and_persist(conn, chain, wallet)


# ── (a) first-ever scan: everything opened, mixed enrichment outcome ────

def test_first_scan_all_opened_mixed_enrichment(monkeypatch):
    conn = make_db()
    current = [pos(0, "100"), pos(1, "101"), pos(2, "102")]
    _patch_snapshot(monkeypatch, current)
    _patch_block_number(monkeypatch, 1000)

    def fake_enrich(chain, wallet, token_id):
        if token_id == 101:  # simulate enrichment failure for this one
            raise mc.MaxFiRpcError("simulated failure")
        return {"deposit_timestamp": 1700000000, "total_rebalances": 0, "block_number": "999"}

    monkeypatch.setattr(orch, "get_vault_deposit_info", fake_enrich)

    result = orch.run_scan_and_persist(conn, "base", "0xWALLET")

    assert result["written"] == {"matched": 0, "rebalanced": 0, "opened": 3, "closed": 0}
    assert result["ambiguous_flagged"] == []
    assert result["chain"] == "base"
    assert result["wallet"] == "0xWALLET"
    assert result["block_number"] == "1000"

    rows = conn.execute(
        "SELECT token_id, first_seen_at_source, first_seen_block FROM maxfi_positions ORDER BY array_index"
    ).fetchall()
    assert len(rows) == 3
    assert rows[0] == ("100", "chain", "999")
    assert rows[1][1] == "fallback_now"
    assert rows[1][2] == "1000"  # falls back to the main snapshot's block number
    assert rows[2] == ("102", "chain", "999")


# ── (b) second scan, no changes: idempotency ─────────────────────────────

def test_second_scan_no_changes_is_idempotent(monkeypatch):
    conn = make_db()
    current = [pos(0, "100"), pos(1, "101"), pos(2, "102")]
    _seed(monkeypatch, conn, current)

    count_after_first = conn.execute("SELECT COUNT(*) FROM maxfi_positions").fetchone()[0]
    first_seen_before = [
        r[0] for r in conn.execute("SELECT first_seen_at FROM maxfi_positions ORDER BY array_index").fetchall()
    ]
    assert count_after_first == 3

    # Re-run with the identical snapshot - nothing changed on chain.
    _patch_snapshot(monkeypatch, current)
    result2 = orch.run_scan_and_persist(conn, "base", "0xWALLET")

    count_after_second = conn.execute("SELECT COUNT(*) FROM maxfi_positions").fetchone()[0]
    assert count_after_second == count_after_first  # zero new rows
    assert result2["written"] == {"matched": 3, "rebalanced": 0, "opened": 0, "closed": 0}

    first_seen_after = [
        r[0] for r in conn.execute("SELECT first_seen_at FROM maxfi_positions ORDER BY array_index").fetchall()
    ]
    assert first_seen_after == first_seen_before  # untouched by a matched-only scan


# ── (c) rebalance between scans ──────────────────────────────────────────

def test_rebalance_updates_token_id_keeps_first_seen_at(monkeypatch):
    conn = make_db()
    current1 = [pos(0, "100"), pos(1, "101")]
    _seed(monkeypatch, conn, current1)

    original = dict(conn.execute("SELECT token_id, first_seen_at FROM maxfi_positions").fetchall())

    # Index 1 re-mints: new token_id, same pool.
    current2 = [pos(0, "100"), pos(1, "901")]
    _patch_snapshot(monkeypatch, current2)

    result2 = orch.run_scan_and_persist(conn, "base", "0xWALLET")
    assert result2["written"] == {"matched": 1, "rebalanced": 1, "opened": 0, "closed": 0}

    row = conn.execute(
        "SELECT token_id, first_seen_at, status FROM maxfi_positions WHERE array_index = 1"
    ).fetchone()
    assert row[0] == "901"
    assert row[1] == original["101"]  # identity anchor untouched
    assert row[2] == "open"
    assert conn.execute("SELECT COUNT(*) FROM maxfi_positions").fetchone()[0] == 2  # no new row


# ── (d) close between scans ──────────────────────────────────────────────

def test_close_marks_status_closed_row_not_deleted(monkeypatch):
    conn = make_db()
    current1 = [pos(0, "100"), pos(1, "101")]
    _seed(monkeypatch, conn, current1)

    # Position at index 1 closes (removed from the end of the array).
    current2 = [pos(0, "100")]
    _patch_snapshot(monkeypatch, current2)

    result2 = orch.run_scan_and_persist(conn, "base", "0xWALLET")
    assert result2["written"] == {"matched": 1, "rebalanced": 0, "opened": 0, "closed": 1}

    assert conn.execute("SELECT COUNT(*) FROM maxfi_positions").fetchone()[0] == 2  # row not deleted
    row = conn.execute(
        "SELECT status, closed_at FROM maxfi_positions WHERE token_id = '101'"
    ).fetchone()
    assert row[0] == "closed"
    assert row[1] is not None


# ── Regression: MATCHED must persist array_index (compaction drift) ─────

def test_matched_position_array_index_updates_on_compaction_drift(monkeypatch):
    """A close can compact a LATER, unrelated position down one slot. That
    position's token_id is unchanged, so classify_positions() correctly
    calls it 'matched' (not rebalanced/ambiguous) via its drift-handling.
    The DB row's array_index must still track the new value - it's a
    denormalized, current-value field per the schema design, kept current
    by the REBALANCED branch already; MATCHED must do the same or it goes
    silently stale after any compaction event."""
    conn = make_db()
    seed_snapshot = [
        pos(0, "100", pool="0xPOOL_0"),
        pos(1, "101", pool="0xPOOL_1"),
        pos(2, "102", pool="0xPOOL_2"),
    ]
    _seed(monkeypatch, conn, seed_snapshot)

    original = conn.execute(
        "SELECT first_seen_at, first_seen_at_source, first_seen_block "
        "FROM maxfi_positions WHERE token_id = '102'"
    ).fetchone()

    # token_id 101 (array_index 1) closes. token_id 102 (array_index 2,
    # same pool, unchanged otherwise) now shows up at array_index 1 due to
    # compaction.
    compacted_snapshot = [pos(0, "100", pool="0xPOOL_0"), pos(1, "102", pool="0xPOOL_2")]
    _patch_snapshot(monkeypatch, compacted_snapshot)

    result = orch.run_scan_and_persist(conn, "base", "0xWALLET")

    # (a) Sanity check: classify_positions' drift handling still recognizes
    # this as matched, not rebalanced/ambiguous.
    assert result["written"] == {"matched": 2, "rebalanced": 0, "opened": 0, "closed": 1}

    # (b) The actual regression check: array_index in the DB is now 1 (the
    # NEW/current value), not 2 (the stale pre-compaction value).
    row = conn.execute(
        "SELECT array_index, status FROM maxfi_positions WHERE token_id = '102'"
    ).fetchone()
    assert row[0] == 1
    assert row[1] == "open"

    # (c) Identity anchor is byte-identical to before this scan - a match
    # (even one with a shifted array_index) must never touch it.
    updated = conn.execute(
        "SELECT first_seen_at, first_seen_at_source, first_seen_block "
        "FROM maxfi_positions WHERE token_id = '102'"
    ).fetchone()
    assert updated == original

    # (d) The position that actually closed (token_id 101) is marked
    # closed, not deleted.
    closed_row = conn.execute(
        "SELECT status, closed_at FROM maxfi_positions WHERE token_id = '101'"
    ).fetchone()
    assert closed_row[0] == "closed"
    assert closed_row[1] is not None


# ── (e) enrichment failure path doesn't abort the scan ──────────────────

def test_enrichment_failure_does_not_abort_scan(monkeypatch):
    conn = make_db()
    current = [pos(0, "100"), pos(1, "101")]
    _patch_snapshot(monkeypatch, current)
    _patch_block_number(monkeypatch, 555)

    def always_fail(chain, wallet, token_id):
        raise mc.MaxFiRpcError("rpc down")

    monkeypatch.setattr(orch, "get_vault_deposit_info", always_fail)

    result = orch.run_scan_and_persist(conn, "base", "0xWALLET")

    # Both positions still get written despite every enrichment call failing.
    assert result["written"] == {"matched": 0, "rebalanced": 0, "opened": 2, "closed": 0}
    rows = conn.execute(
        "SELECT first_seen_at_source, first_seen_block FROM maxfi_positions"
    ).fetchall()
    assert len(rows) == 2
    for source, block in rows:
        assert source == "fallback_now"
        assert block == "555"


def test_enrichment_decode_error_also_falls_back(monkeypatch):
    """MaxFiDecodeError must be caught the same way as MaxFiRpcError -
    both are named explicitly in the spec, not a broad except."""
    conn = make_db()
    current = [pos(0, "100")]
    _patch_snapshot(monkeypatch, current)
    _patch_block_number(monkeypatch, 777)
    monkeypatch.setattr(
        orch, "get_vault_deposit_info",
        lambda chain, wallet, token_id: (_ for _ in ()).throw(mc.MaxFiDecodeError("bad decode")),
    )

    result = orch.run_scan_and_persist(conn, "base", "0xWALLET")

    assert result["written"]["opened"] == 1
    row = conn.execute("SELECT first_seen_at_source, first_seen_block FROM maxfi_positions").fetchone()
    assert row == ("fallback_now", "777")


# ── (f) ambiguous case: no write, but flagged in the response ───────────

def test_ambiguous_not_written_but_flagged(monkeypatch):
    conn = make_db()
    current1 = [pos(0, "100", pool="0xPOOL_0")]
    _seed(monkeypatch, conn, current1)

    # Index 0 reused with a brand-new token_id AND a different pool.
    current2 = [pos(0, "999", pool="0xPOOL_DIFFERENT", token1="0xTOKEN_C", fee=500)]
    _patch_snapshot(monkeypatch, current2)

    result2 = orch.run_scan_and_persist(conn, "base", "0xWALLET")

    assert result2["written"] == {"matched": 0, "rebalanced": 0, "opened": 0, "closed": 0}
    assert len(result2["ambiguous_flagged"]) == 1
    assert result2["ambiguous_flagged"][0]["reason"]  # non-empty

    # Nothing written for the ambiguous case: the original row is untouched.
    rows = conn.execute("SELECT token_id, status FROM maxfi_positions").fetchall()
    assert rows == [("100", "open")]


# ── Fatal main-snapshot failure: nothing written at all ──────────────────

def test_main_snapshot_failure_writes_nothing(monkeypatch):
    conn = make_db()

    def fail_snapshot(chain, wallet):
        raise mc.MaxFiRpcError("node unreachable")

    monkeypatch.setattr(orch, "get_wallet_position_snapshot", fail_snapshot)

    try:
        orch.run_scan_and_persist(conn, "base", "0xWALLET")
        assert False, "should have raised"
    except mc.MaxFiRpcError:
        pass

    assert conn.execute("SELECT COUNT(*) FROM maxfi_positions").fetchone()[0] == 0
