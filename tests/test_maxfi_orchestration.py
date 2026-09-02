"""Tests for maxfi_orchestration.py (Phase C scan-and-persist).

In-memory SQLite + monkeypatched get_wallet_position_snapshot() /
get_vault_deposit_info() / eth_block_number() - no real network calls.
"""

import sqlite3

import pytest

import maxfi_client as mc
import maxfi_matching as mm
import maxfi_orchestration as orch
import maxfi_schema


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
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


# ── wallet-casing fix: LOWER() on both sides of every wallet comparison ──
#
# Neither the wallets store nor maxfi_positions.wallet is normalized on
# write - each keeps whatever casing appeared at write time, and existing
# rows are never rewritten (rewriting would break the live checksummed
# 0xaB7A515c... wallet). So a scan invoked with a DIFFERENT casing of an
# already-known wallet must still recognize its existing open rows as
# already-known. Before the fix (bare `wallet = ?`), this would have missed
# every existing row in _load_previous_open_positions and re-inserted every
# one of them as a brand-new 'opened' position with no basis - this is the
# test that matters most, run against run_scan_and_persist directly rather
# than through the route.

def test_scan_with_different_wallet_casing_matches_open_rows_not_a_duplicate(monkeypatch):
    conn = make_db()
    current = [pos(0, "100"), pos(1, "101")]
    _seed(monkeypatch, conn, current, wallet="0xWALLET")

    count_after_first = conn.execute("SELECT COUNT(*) FROM maxfi_positions").fetchone()[0]
    assert count_after_first == 2

    # Same on-chain snapshot, but the scan is now invoked with a DIFFERENT
    # casing of the same wallet (e.g. a second wallet-store entry for the
    # identical address, typed with different casing).
    _patch_snapshot(monkeypatch, current)
    result2 = orch.run_scan_and_persist(conn, "base", "0xwallet")

    assert result2["written"] == {"matched": 2, "rebalanced": 0, "opened": 0, "closed": 0}
    count_after_second = conn.execute("SELECT COUNT(*) FROM maxfi_positions").fetchone()[0]
    assert count_after_second == 2  # no duplicate rows inserted


# THE CRASH TEST — no existing test reproduced this before this block. If the
# write path (the scan route, fixed separately in web_portfolio.py) ever lets
# two casings of the same wallet each accumulate an open row at the same
# array_index, _load_previous_open_positions's own LOWER()-wrapped read
# returns BOTH rows in one "previous" snapshot, and classify_positions (via
# maxfi_matching._index_previous — NOT maxfi_orchestration, an earlier
# discovery pass had that wrong) raises ValueError rather than silently
# misclassifying anything. This documents the exact failure the route-level
# wallet-casing resolution exists to prevent from ever occurring.

def test_two_casings_of_same_wallet_sharing_array_index_raises_on_load():
    conn = make_db()
    for wallet_casing in ("0xWALLET", "0xwallet"):
        conn.execute(
            """
            INSERT INTO maxfi_positions (
                chain, wallet, token_id, array_index, pool_address,
                token0_address, token1_address, fee_tier, status,
                first_seen_at, first_seen_at_source, first_seen_block,
                last_scan_at, closed_at
            ) VALUES ('base', ?, ?, 0, '0xPOOL', '0xT0', '0xT1', 3000,
                      'open', '2026-01-01T00:00:00+00:00', 'chain', '1',
                      '2026-01-01T00:00:00+00:00', NULL)
            """,
            (wallet_casing, wallet_casing),
        )
    conn.commit()

    previous, _ = orch._load_previous_open_positions(conn, "base", "0xWALLET")
    assert len(previous) == 2  # LOWER() correctly matches both differently-cased rows

    with pytest.raises(ValueError, match="duplicate array_index"):
        mm.classify_positions(previous, [])


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


# ── Full-close guard: a live snapshot that decodes to zero positions ────
#
# get_wallet_position_snapshot returns [] on a Lens call that SUCCEEDS but
# decodes to zero token ids - no exception, no warning. Unguarded, that []
# flows into classify_positions and every previously-open row lands in
# "closed" (current_token_ids is an empty set, so every previous token_id
# is trivially "not in" it), which run_scan_and_persist then commits
# atomically as an ordinary, successful scan. allow_full_close=False (the
# default) must refuse that instead; allow_full_close=True is the explicit
# override for a genuine full exit.

def test_full_close_refused_when_snapshot_empty_and_rows_open(monkeypatch):
    conn = make_db()
    current1 = [pos(0, "100"), pos(1, "101")]
    _seed(monkeypatch, conn, current1)

    # Second scan: Lens decodes to zero positions while 2 rows are open.
    _patch_snapshot(monkeypatch, [])

    with pytest.raises(orch.MaxFiFullCloseRefused) as exc_info:
        orch.run_scan_and_persist(conn, "base", "0xWALLET")

    assert exc_info.value.open_count == 2
    rows = conn.execute("SELECT status, closed_at FROM maxfi_positions").fetchall()
    assert len(rows) == 2
    assert all(status == "open" and closed_at is None for status, closed_at in rows)


def test_full_close_allowed_with_override(monkeypatch):
    conn = make_db()
    current1 = [pos(0, "100"), pos(1, "101")]
    _seed(monkeypatch, conn, current1)

    _patch_snapshot(monkeypatch, [])

    result = orch.run_scan_and_persist(conn, "base", "0xWALLET", allow_full_close=True)

    assert result["written"] == {"matched": 0, "rebalanced": 0, "opened": 0, "closed": 2}
    rows = conn.execute("SELECT status FROM maxfi_positions").fetchall()
    assert all(status == "closed" for (status,) in rows)


def test_empty_snapshot_with_zero_open_rows_does_not_raise(monkeypatch):
    conn = make_db()
    _patch_snapshot(monkeypatch, [])
    _patch_block_number(monkeypatch, 1000)

    result = orch.run_scan_and_persist(conn, "base", "0xWALLET")

    assert result["written"] == {"matched": 0, "rebalanced": 0, "opened": 0, "closed": 0}


def test_partial_close_with_nonempty_snapshot_is_unaffected_by_guard(monkeypatch):
    """Regression: the guard only fires on a fully empty snapshot. An
    ordinary partial close (a non-empty snapshot missing some previously-
    open positions) must still close exactly the missing ones and leave the
    rest open, exactly as before this change."""
    conn = make_db()
    current1 = [pos(0, "100"), pos(1, "101"), pos(2, "102")]
    _seed(monkeypatch, conn, current1)

    # Position at index 1 closes; 0 and 2 remain live.
    current2 = [pos(0, "100"), pos(2, "102")]
    _patch_snapshot(monkeypatch, current2)

    result = orch.run_scan_and_persist(conn, "base", "0xWALLET")

    assert result["written"] == {"matched": 2, "rebalanced": 0, "opened": 0, "closed": 1}
    row = conn.execute(
        "SELECT status FROM maxfi_positions WHERE token_id = '101'"
    ).fetchone()
    assert row[0] == "closed"
    still_open = conn.execute(
        "SELECT COUNT(*) FROM maxfi_positions WHERE status='open'"
    ).fetchone()[0]
    assert still_open == 2


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


# ── Schema-only tests for maxfi_claims / maxfi_position_lineage ─────────────
# These two tables have no reader and no writer yet - nothing here exercises
# a route or any allocation arithmetic. Just: the tables exist, their columns
# are exactly what was declared, ensure_maxfi_tables stays idempotent, and
# the rows the later write path will need (a swept-but-unsold claim, two
# identical claims, a two-arriving lineage group) can actually be stored.

def test_claims_and_lineage_tables_exist(monkeypatch):
    conn = make_db()
    names = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert "maxfi_claims" in names
    assert "maxfi_position_lineage" in names


def test_claims_table_columns_exact(monkeypatch):
    conn = make_db()
    cols = [row[1] for row in conn.execute("PRAGMA table_info(maxfi_claims)").fetchall()]
    assert cols == [
        "id", "position_id", "claimed_at", "token0_symbol", "token0_amount",
        "token1_symbol", "token1_amount", "sold_at", "proceeds_usd", "note",
        "set_at", "set_by",
    ]


def test_lineage_table_columns_exact(monkeypatch):
    conn = make_db()
    cols = [row[1] for row in conn.execute("PRAGMA table_info(maxfi_position_lineage)").fetchall()]
    assert cols == [
        "id", "departing_position_id", "arriving_position_id",
        "split_group_id", "arriving_current_value_usd", "created_at",
    ]


def test_ensure_maxfi_tables_twice_is_a_noop(monkeypatch):
    conn = make_db()
    # No exception on a second call is the assertion - the whole file's
    # idempotency guarantee, exercised against the two new tables too.
    status = maxfi_schema.ensure_maxfi_tables(conn)
    assert status == {"unique_index_ready": True, "notes_column_ready": True}


def test_claims_accepts_unsold_and_zero_proceeds(monkeypatch):
    conn = make_db()
    conn.execute(
        """
        INSERT INTO maxfi_claims (position_id, claimed_at, sold_at, proceeds_usd, set_at, set_by)
        VALUES (1, '2026-01-01T00:00:00+00:00', NULL, NULL, '2026-01-01T00:00:00+00:00', 'glenn')
        """
    )
    conn.execute(
        """
        INSERT INTO maxfi_claims (position_id, claimed_at, sold_at, proceeds_usd, set_at, set_by)
        VALUES (1, '2026-01-02T00:00:00+00:00', '2026-01-03T00:00:00+00:00', 0, '2026-01-03T00:00:00+00:00', 'glenn')
        """
    )
    conn.commit()
    rows = conn.execute(
        "SELECT sold_at, proceeds_usd FROM maxfi_claims ORDER BY id"
    ).fetchall()
    assert rows[0] == (None, None)
    assert rows[1] == ("2026-01-03T00:00:00+00:00", 0)


def test_claims_allows_duplicate_rows(monkeypatch):
    conn = make_db()
    for _ in range(2):
        conn.execute(
            """
            INSERT INTO maxfi_claims (position_id, claimed_at, proceeds_usd, set_at, set_by)
            VALUES (1, '2026-01-01T00:00:00+00:00', 50.0, '2026-01-01T00:00:00+00:00', 'glenn')
            """
        )
    conn.commit()
    rows = conn.execute(
        "SELECT id FROM maxfi_claims WHERE position_id = 1 AND claimed_at = '2026-01-01T00:00:00+00:00' "
        "AND proceeds_usd = 50.0 ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] != rows[1][0]


def test_lineage_accepts_two_arriving_rows_for_one_split_group(monkeypatch):
    conn = make_db()
    conn.execute(
        """
        INSERT INTO maxfi_position_lineage
            (departing_position_id, arriving_position_id, split_group_id,
             arriving_current_value_usd, created_at)
        VALUES (10, 20, 'split-1', 100.0, '2026-01-01T00:00:00+00:00')
        """
    )
    conn.execute(
        """
        INSERT INTO maxfi_position_lineage
            (departing_position_id, arriving_position_id, split_group_id,
             arriving_current_value_usd, created_at)
        VALUES (11, 21, 'split-1', 200.0, '2026-01-01T00:00:00+00:00')
        """
    )
    conn.commit()
    rows = conn.execute(
        "SELECT arriving_position_id FROM maxfi_position_lineage WHERE split_group_id = 'split-1' ORDER BY arriving_position_id"
    ).fetchall()
    assert [r[0] for r in rows] == [20, 21]
