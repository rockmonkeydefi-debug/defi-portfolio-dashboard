"""Tests for maxfi_repair.merge_split_predecessors (Phase D.3.1 fallout
repair). Offline, in-memory SQLite only - same fixture pattern as
tests/test_maxfi_auto_split_write.py (make_db() with PRAGMA foreign_keys=ON,
schema via maxfi_schema.ensure_maxfi_tables), reused rather than reinvented.
Does NOT touch that file's _FlakyConnection or _fail_after.
"""

import json
import sqlite3

import pytest

import maxfi_schema
from maxfi_repair import merge_split_predecessors, MERGE_RESOLUTION, SPLIT_MERGE_CHAIN, SPLIT_MERGE_WALLET

CHAIN = SPLIT_MERGE_CHAIN
WALLET = SPLIT_MERGE_WALLET
POOL = "0xc4a21f9d6485fc5893dd4a491b320a83daf4da1d"
TOKEN0 = "0xWETH"
TOKEN1 = "0xAI"
FEE = 3000

PRED1_DATE = "2026-01-01T00:00:00+00:00"
PRED2_DATE = "2026-02-01T00:00:00+00:00"
SCAN_AT = "2026-03-01T00:00:00+00:00"
CLOSED_AT = "2026-03-01T00:00:00+00:00"
MERGED_AT = "2026-03-02T00:00:00+00:00"


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    maxfi_schema.ensure_maxfi_tables(conn)
    return conn


def _seed_closed_predecessor(conn, token_id, array_index, first_seen_at, first_seen_block,
                              pool=POOL, token0=TOKEN0, token1=TOKEN1, fee=FEE, status="closed"):
    cursor = conn.execute(
        """
        INSERT INTO maxfi_positions (
            chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, first_seen_block,
            last_scan_at, closed_at, closed_by, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'chain', ?, ?, ?, NULL, NULL)
        """,
        (CHAIN, WALLET, token_id, array_index, pool, token0, token1, fee, status,
         first_seen_at, first_seen_block, SCAN_AT, CLOSED_AT if status == "closed" else None),
    )
    conn.commit()
    return cursor.lastrowid


def _seed_open_successor(conn, token_id, array_index, first_seen_at, notes,
                          pool=POOL, token0=TOKEN0, token1=TOKEN1, fee=FEE):
    cursor = conn.execute(
        """
        INSERT INTO maxfi_positions (
            chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, first_seen_block,
            last_scan_at, closed_at, closed_by, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, 'ambiguity_auto_split_inherited', NULL, ?, NULL, NULL, ?)
        """,
        (CHAIN, WALLET, token_id, array_index, pool, token0, token1, fee,
         first_seen_at, SCAN_AT, notes),
    )
    conn.commit()
    return cursor.lastrowid


def _insert_initial_value(conn, position_id, source, value, set_by="system"):
    conn.execute(
        """
        INSERT INTO maxfi_initial_value (position_id, source, initial_value_usd, set_at, set_by)
        VALUES (?, ?, ?, ?, ?)
        """,
        (position_id, source, value, SCAN_AT, set_by),
    )
    conn.commit()


def _insert_lineage(conn, departing_id, arriving_id, current_value_usd, split_group_id=SCAN_AT + "|" + POOL):
    conn.execute(
        """
        INSERT INTO maxfi_position_lineage
            (departing_position_id, arriving_position_id, split_group_id, arriving_current_value_usd, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (departing_id, arriving_id, split_group_id, current_value_usd, SCAN_AT),
    )
    conn.commit()


def _auto_split_notes(departing_token_ids):
    return json.dumps({
        "resolution": "ambiguity_auto_split",
        "resolved_at": SCAN_AT,
        "pool_address": POOL,
        "departing": [{"token_id": tid, "initial_value_usd": None} for tid in departing_token_ids],
        "arriving": [
            {"token_id": "NEW_1", "current_value_usd": 200.0, "proposed_initial_value_usd": 100.0},
            {"token_id": "NEW_2", "current_value_usd": 220.0, "proposed_initial_value_usd": 110.0},
        ],
        "outcome": "auto_split",
    })


def _seed_default_group(conn, succ1_basis=("ambiguity_auto_split", 100.0), succ2_basis=None):
    """One post-split group, the shape the CONTEXT block specifies: two
    closed predecessors (manual_override bases 105.0/123.0), two open
    successors at the same array_indices naming both predecessor token_ids
    in their notes' "departing" list, plus the four lineage rows."""
    pred1_id = _seed_closed_predecessor(conn, "OLD_1", 0, PRED1_DATE, "100")
    pred2_id = _seed_closed_predecessor(conn, "OLD_2", 1, PRED2_DATE, "101")
    _insert_initial_value(conn, pred1_id, "manual_override", 105.0, set_by="human")
    _insert_initial_value(conn, pred2_id, "manual_override", 123.0, set_by="human")

    notes = _auto_split_notes(["OLD_1", "OLD_2"])
    succ1_id = _seed_open_successor(conn, "NEW_1", 0, PRED1_DATE, notes)
    succ2_id = _seed_open_successor(conn, "NEW_2", 1, PRED1_DATE, notes)

    if succ1_basis is not None:
        _insert_initial_value(conn, succ1_id, succ1_basis[0], succ1_basis[1])
    if succ2_basis is not None:
        _insert_initial_value(conn, succ2_id, succ2_basis[0], succ2_basis[1])

    _insert_lineage(conn, pred1_id, succ1_id, 200.0)
    _insert_lineage(conn, pred1_id, succ2_id, 220.0)
    _insert_lineage(conn, pred2_id, succ1_id, 200.0)
    _insert_lineage(conn, pred2_id, succ2_id, 220.0)

    pairs = [
        {"predecessor_id": pred1_id, "successor_id": succ1_id, "predecessor_token_id": "OLD_1"},
        {"predecessor_id": pred2_id, "successor_id": succ2_id, "predecessor_token_id": "OLD_2"},
    ]
    ids = {"pred1": pred1_id, "pred2": pred2_id, "succ1": succ1_id, "succ2": succ2_id}
    return pairs, ids


def _table_counts(conn):
    tables = ("maxfi_positions", "maxfi_initial_value", "maxfi_position_lineage",
              "maxfi_claims", "maxfi_strategy_labels", "maxfi_position_user_data")
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


# ── dry run ──────────────────────────────────────────────────────────────

def test_dry_run_writes_nothing_and_returns_full_plan():
    conn = make_db()
    pairs, ids = _seed_default_group(conn)
    before = _table_counts(conn)

    result = merge_split_predecessors(conn, CHAIN, WALLET, pairs, MERGED_AT, execute=False)

    after = _table_counts(conn)
    assert after == before

    assert result["mode"] == "dry_run"
    assert result["ok"] is True
    assert result["refusals"] == []
    assert len(result["pairs"]) == 2
    basis_actions = [p["basis_action"] for p in result["pairs"]]
    assert basis_actions == ["replace_auto_split", "insert_from_predecessor"]
    assert result["totals"]["maxfi_position_lineage_deletes"] == 4


# ── execute ──────────────────────────────────────────────────────────────

def test_execute_merges_predecessors_into_successors():
    conn = make_db()
    pairs, ids = _seed_default_group(conn)

    result = merge_split_predecessors(conn, CHAIN, WALLET, pairs, MERGED_AT, execute=True)

    assert result["mode"] == "executed"
    assert result["ok"] is True

    # Predecessors gone.
    assert conn.execute(
        "SELECT COUNT(*) FROM maxfi_positions WHERE id IN (?, ?)", (ids["pred1"], ids["pred2"])
    ).fetchone()[0] == 0

    # Successors carry the predecessor's date/source/block; array_index,
    # token_id and last_scan_at are untouched.
    succ1 = conn.execute(
        "SELECT token_id, array_index, first_seen_at, first_seen_at_source, first_seen_block, last_scan_at, notes "
        "FROM maxfi_positions WHERE id = ?", (ids["succ1"],)
    ).fetchone()
    assert succ1[0] == "NEW_1"
    assert succ1[1] == 0
    assert succ1[2] == PRED1_DATE
    assert succ1[3] == "chain"
    assert succ1[4] == "100"
    assert succ1[5] == SCAN_AT

    succ2 = conn.execute(
        "SELECT token_id, array_index, first_seen_at, first_seen_at_source, first_seen_block, last_scan_at, notes "
        "FROM maxfi_positions WHERE id = ?", (ids["succ2"],)
    ).fetchone()
    assert succ2[0] == "NEW_2"
    assert succ2[1] == 1
    assert succ2[2] == PRED2_DATE
    assert succ2[3] == "chain"
    assert succ2[4] == "101"
    assert succ2[5] == SCAN_AT

    # Successor notes: merge record nesting the original auto-split payload.
    succ1_notes = json.loads(succ1[6])
    assert succ1_notes["resolution"] == MERGE_RESOLUTION
    assert succ1_notes["original_auto_split"]["outcome"] == "auto_split"
    succ2_notes = json.loads(succ2[6])
    assert succ2_notes["resolution"] == MERGE_RESOLUTION
    assert succ2_notes["original_auto_split"]["outcome"] == "auto_split"

    # Bases: successor 1 (was 'ambiguity_auto_split') replaced by pred1's
    # 105.0/manual_override; successor 2 (had none) gets pred2's 123.0.
    bases = {
        token_id: (source, value)
        for token_id, source, value in conn.execute(
            "SELECT p.token_id, iv.source, iv.initial_value_usd FROM maxfi_initial_value iv "
            "JOIN maxfi_positions p ON p.id = iv.position_id"
        ).fetchall()
    }
    assert bases == {"NEW_1": ("manual_override", 105.0), "NEW_2": ("manual_override", 123.0)}
    assert conn.execute("SELECT COUNT(*) FROM maxfi_initial_value").fetchone()[0] == 2

    assert conn.execute("SELECT COUNT(*) FROM maxfi_position_lineage").fetchone()[0] == 0


# ── kept_existing ────────────────────────────────────────────────────────

def test_manual_override_on_successor_is_kept_not_overwritten():
    conn = make_db()
    pairs, ids = _seed_default_group(conn, succ1_basis=("manual_override", 580.0))

    result = merge_split_predecessors(conn, CHAIN, WALLET, pairs, MERGED_AT, execute=True)

    assert result["ok"] is True
    row = conn.execute(
        "SELECT source, initial_value_usd FROM maxfi_initial_value WHERE position_id = ?",
        (ids["succ1"],),
    ).fetchone()
    assert row == ("manual_override", 580.0)


# ── refusals ─────────────────────────────────────────────────────────────

def test_refused_on_array_index_mismatch():
    conn = make_db()
    pairs, ids = _seed_default_group(conn)
    conn.execute("UPDATE maxfi_positions SET array_index = 99 WHERE id = ?", (ids["succ2"],))
    conn.commit()
    before = _table_counts(conn)

    result = merge_split_predecessors(conn, CHAIN, WALLET, pairs, MERGED_AT, execute=True)

    assert result["mode"] == "refused"
    assert result["ok"] is False
    assert any(r["reason"] == "array_index_mismatch" for r in result["refusals"])
    assert _table_counts(conn) == before


def test_refused_when_predecessor_has_claims_row():
    conn = make_db()
    pairs, ids = _seed_default_group(conn)
    conn.execute(
        "INSERT INTO maxfi_claims (position_id, claimed_at, set_at, set_by) VALUES (?, ?, ?, ?)",
        (ids["pred1"], SCAN_AT, SCAN_AT, "human"),
    )
    conn.commit()
    before = _table_counts(conn)

    result = merge_split_predecessors(conn, CHAIN, WALLET, pairs, MERGED_AT, execute=True)

    assert result["mode"] == "refused"
    reasons = [r["reason"] for r in result["refusals"]]
    assert any("maxfi_claims" in r for r in reasons)
    assert _table_counts(conn) == before


def test_refused_when_predecessor_status_is_open():
    conn = make_db()
    pairs, ids = _seed_default_group(conn)
    conn.execute("UPDATE maxfi_positions SET status = 'open' WHERE id = ?", (ids["pred1"],))
    conn.commit()
    before = _table_counts(conn)

    result = merge_split_predecessors(conn, CHAIN, WALLET, pairs, MERGED_AT, execute=True)

    assert result["mode"] == "refused"
    assert any(r["reason"] == "predecessor_not_closed" for r in result["refusals"])
    assert _table_counts(conn) == before


def test_refused_on_wrong_wallet():
    conn = make_db()
    pairs, ids = _seed_default_group(conn)
    before = _table_counts(conn)

    result = merge_split_predecessors(
        conn, CHAIN, "0x000000000000000000000000000000000000ff", pairs, MERGED_AT, execute=True,
    )

    assert result["mode"] == "refused"
    assert result["refusals"][0]["reason"] == "wrong_chain_or_wallet"
    assert _table_counts(conn) == before


def test_all_or_nothing_second_pair_failure_blocks_the_first():
    conn = make_db()
    pairs, ids = _seed_default_group(conn)
    # Corrupt only the second pair's array_index alignment - the first pair
    # remains fully valid on its own.
    conn.execute("UPDATE maxfi_positions SET array_index = 99 WHERE id = ?", (ids["succ2"],))
    conn.commit()
    before = _table_counts(conn)

    result = merge_split_predecessors(conn, CHAIN, WALLET, pairs, MERGED_AT, execute=True)

    assert result["mode"] == "refused"
    assert _table_counts(conn) == before
    # The first pair's predecessor is still there, still closed, untouched.
    pred1_row = conn.execute(
        "SELECT status, first_seen_at_source FROM maxfi_positions WHERE id = ?", (ids["pred1"],)
    ).fetchone()
    assert pred1_row == ("closed", "chain")
    succ1_row = conn.execute(
        "SELECT first_seen_at_source FROM maxfi_positions WHERE id = ?", (ids["succ1"],)
    ).fetchone()
    assert succ1_row == ("ambiguity_auto_split_inherited",)
