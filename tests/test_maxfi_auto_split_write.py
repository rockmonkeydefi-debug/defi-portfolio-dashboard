"""Tests for maxfi_orchestration.resolve_ambiguous_auto_splits (Phase D.3.2b) -
the auto-split WRITE path. This is the first MaxFi code that writes money
values unattended, the first code that writes a status='closed' row, and the
first code that touches the new `notes` column - so these tests exercise the
actual database writes (and non-writes) directly, in-memory, with no network
and no Flask test client.

Group/decision shapes are built directly (matching group_ambiguous_entries()'s
documented output shape exactly, same technique as
test_maxfi_ambiguity_resolution.py's synthetic-group tests) rather than routed
through classify_positions(), for full control over departing/arriving order -
resolve_ambiguous_auto_splits() iterates decision["arriving"] in the same
order group["arriving"] is given, which several tests below rely on to
predict exact autoincrement ids.
"""

import json
import sqlite3
from datetime import datetime, timezone

import pytest

import maxfi_orchestration as orch
import maxfi_schema
from maxfi_orchestration import (
    resolve_ambiguous_auto_splits,
    AMBIGUITY_AUTO_SPLIT_SOURCE,
    AMBIGUITY_AUTO_SPLIT_FIRST_SEEN_SOURCE,
)


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    maxfi_schema.ensure_maxfi_tables(conn)
    return conn


CHAIN = "robinhood"
WALLET = "0xWALLET"
POOL = "0x70504a6fafdbfb75fe971faa4dd716e79ac5624c"
SCHEMA_STATUS_READY = {"unique_index_ready": True, "notes_column_ready": True}
CAPTURED_AT = "2026-08-01T00:00:00+00:00"


def _seed_open_position(conn, token_id, array_index, first_seen_at="2026-01-01T00:00:00+00:00",
                         pool=POOL, token0="0xWETH", token1="0xMSTR", fee=3000):
    conn.execute(
        """
        INSERT INTO maxfi_positions (
            chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, first_seen_block,
            last_scan_at, closed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, 'chain', '1', ?, NULL)
        """,
        (CHAIN, WALLET, token_id, array_index, pool, token0, token1, fee,
         first_seen_at, first_seen_at),
    )
    conn.commit()


def _arriving_pos(array_index, pool=POOL, token0="0xWETH", token1="0xMSTR", fee=3000):
    return {"array_index": array_index, "pool_address": pool,
            "token0_address": token0, "token1_address": token1, "fee_tier": fee}


def _mstr_group():
    return {
        "chain": CHAIN,
        "pool_key": ("0xweth", "0xmstr", 3000),
        "pool_address": POOL,
        "departing": [{"token_id": "799578", "array_index": 0}, {"token_id": "770744", "array_index": 1}],
        "arriving": [{"token_id": "834942", "array_index": 0}, {"token_id": "842318", "array_index": 1}],
        "array_indices": [0, 1],
        "reasons": ["multiple concurrent positions in same pool - array_index pairing not verifiable"] * 2,
    }


def _mstr_current_values():
    return {"834942": 257.53454955124613, "842318": 278.5612680400029}


def _mstr_departing_info(basis_799578=334.00, basis_770744=259.00,
                          first_seen_799578=None, first_seen_770744=None):
    return {
        "799578": {"initial_value_usd": basis_799578,
                   "first_seen_at": first_seen_799578 or datetime(2026, 6, 1, tzinfo=timezone.utc)},
        "770744": {"initial_value_usd": basis_770744,
                   "first_seen_at": first_seen_770744 or datetime(2026, 5, 15, tzinfo=timezone.utc)},
    }


def _mstr_current_positions():
    return {"834942": _arriving_pos(0), "842318": _arriving_pos(1)}


# ── 1. Happy path: 'auto_split' closes departing, opens arriving, splits basis ──

def test_happy_path_auto_split_closes_departing_opens_arriving_with_split_basis():
    conn = make_db()
    _seed_open_position(conn, "799578", 0)
    _seed_open_position(conn, "770744", 1)

    summary = resolve_ambiguous_auto_splits(
        conn, CHAIN, WALLET, [_mstr_group()],
        _mstr_current_values(), _mstr_departing_info(), _mstr_current_positions(),
        SCHEMA_STATUS_READY, CAPTURED_AT,
    )

    assert summary["resolved"] == 1
    assert summary["skipped"] == []
    assert summary["deferred"] == 0
    assert summary["manual"] == 0
    assert summary["refused"] is False
    # Two departing rows closed, two arriving rows opened - the exact same
    # counts this fixture's own assertions below verify by reading the rows
    # back, now also reported directly in the summary rather than being
    # invisible to a caller that only reads written (which this function
    # runs strictly after and never touches).
    assert summary["closed_by_auto_split"] == 2
    assert summary["opened_by_auto_split"] == 2

    departing_rows = conn.execute(
        "SELECT status, closed_at FROM maxfi_positions WHERE token_id IN ('799578', '770744')"
    ).fetchall()
    assert len(departing_rows) == 2
    for status, closed_at in departing_rows:
        assert status == "closed"
        assert closed_at == CAPTURED_AT

    arriving_rows = conn.execute(
        "SELECT token_id, status, first_seen_at_source, closed_at FROM maxfi_positions "
        "WHERE token_id IN ('834942', '842318') ORDER BY token_id"
    ).fetchall()
    assert len(arriving_rows) == 2
    for token_id, status, first_seen_at_source, closed_at in arriving_rows:
        assert status == "open"
        assert first_seen_at_source == AMBIGUITY_AUTO_SPLIT_FIRST_SEEN_SOURCE
        assert closed_at is None

    initial_values = conn.execute(
        """
        SELECT p.token_id, iv.source, iv.initial_value_usd
        FROM maxfi_initial_value iv JOIN maxfi_positions p ON p.id = iv.position_id
        WHERE p.token_id IN ('834942', '842318')
        """
    ).fetchall()
    assert len(initial_values) == 2
    total = 0.0
    for token_id, source, initial_value_usd in initial_values:
        assert source == AMBIGUITY_AUTO_SPLIT_SOURCE
        total += initial_value_usd
    assert total == pytest.approx(593.00, abs=1e-9)


# ── 2. Transaction rollback: a mid-write failure leaves nothing partial ─────

class _FlakyConnection(sqlite3.Connection):
    """A Connection subclass that raises on the Nth call to execute().

    A real sqlite3.Connection rejects arbitrary instance attribute
    assignment (`conn.execute = wrapper` raises "attribute 'execute' is
    read-only"), so a monkeypatched wrapper isn't possible on the base
    type. Subclassing instead gives a normal instance __dict__, so plain
    attributes like _fail_after/_call_count work exactly like on any other
    Python object, and overriding execute() at the class level intercepts
    every call resolve_ambiguous_auto_splits makes through db_connection.
    """
    def execute(self, *args, **kwargs):
        if getattr(self, "_fail_after", None) is not None:
            self._call_count = getattr(self, "_call_count", 0) + 1
            if self._call_count == self._fail_after:
                raise sqlite3.OperationalError("simulated failure")
        return super().execute(*args, **kwargs)


def test_transaction_rollback_leaves_nothing_partial():
    conn = sqlite3.connect(":memory:", factory=_FlakyConnection)
    conn.execute("PRAGMA foreign_keys=ON")
    maxfi_schema.ensure_maxfi_tables(conn)
    _seed_open_position(conn, "799578", 0)
    _seed_open_position(conn, "770744", 1)

    # Guard calls run first (untouched by _fail_after, set below only after
    # seeding): 2 SELECTs for the arriving already-tracked guard + 2 SELECTs
    # for the departing lookup guard = calls 1-4, then BEGIN IMMEDIATE = 5,
    # then the two departing CLOSE updates = 6, 7, then the first arriving
    # INSERT = 8 - failing exactly there is "after the closes, during the
    # inserts," as required.
    conn._call_count = 0
    conn._fail_after = 8

    summary = resolve_ambiguous_auto_splits(
        conn, CHAIN, WALLET, [_mstr_group()],
        _mstr_current_values(), _mstr_departing_info(), _mstr_current_positions(),
        SCHEMA_STATUS_READY, CAPTURED_AT,
    )

    assert summary["resolved"] == 0
    assert len(summary["skipped"]) == 1
    assert "write_failed" in summary["skipped"][0]["reason"]

    departing_rows = conn.execute(
        "SELECT status FROM maxfi_positions WHERE token_id IN ('799578', '770744')"
    ).fetchall()
    assert [r[0] for r in departing_rows] == ["open", "open"]

    assert conn.execute(
        "SELECT COUNT(*) FROM maxfi_positions WHERE token_id IN ('834942', '842318')"
    ).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM maxfi_initial_value").fetchone()[0] == 0


# ── 3. Both-untracked guard: a repeat run is a silent no-op ─────────────────

def test_repeat_run_after_success_is_a_no_op_via_already_tracked_guard():
    conn = make_db()
    _seed_open_position(conn, "799578", 0)
    _seed_open_position(conn, "770744", 1)

    args = (CHAIN, WALLET, [_mstr_group()], _mstr_current_values(),
            _mstr_departing_info(), _mstr_current_positions(),
            SCHEMA_STATUS_READY, CAPTURED_AT)

    first = resolve_ambiguous_auto_splits(conn, *args)
    assert first["resolved"] == 1

    positions_count_after_first = conn.execute("SELECT COUNT(*) FROM maxfi_positions").fetchone()[0]
    initial_value_count_after_first = conn.execute("SELECT COUNT(*) FROM maxfi_initial_value").fetchone()[0]

    second = resolve_ambiguous_auto_splits(conn, *args)

    assert second["resolved"] == 0
    assert len(second["skipped"]) == 1
    assert second["skipped"][0]["reason"] == "arriving_already_tracked"
    assert not second["deferred"] and not second["manual"] and not second["refused"]

    assert conn.execute("SELECT COUNT(*) FROM maxfi_positions").fetchone()[0] == positions_count_after_first
    assert conn.execute("SELECT COUNT(*) FROM maxfi_initial_value").fetchone()[0] == initial_value_count_after_first


# ── 4. Never overwrite an existing maxfi_initial_value row ──────────────────

def test_no_overwrite_of_existing_manual_override_initial_value():
    conn = make_db()
    _seed_open_position(conn, "799578", 0)   # id 1
    _seed_open_position(conn, "770744", 1)   # id 2

    # Pre-seed a manual override at position_id=3 - the id the auto-split
    # write path will assign to the first arriving token ("834942", i.e.
    # decision["arriving"][0] given _mstr_group()'s literal ordering).
    # AUTOINCREMENT hands out strictly increasing ids and none have been
    # deleted, so id 3 is deterministic in this fresh, fully-controlled
    # database. foreign_keys is briefly OFF only for this one insert, since
    # the referenced position row does not exist yet at this point in the
    # test's constructed timeline (this simulates "a human set this before
    # the auto-split ever ran" for a position_id that both sides of this
    # test agree on ahead of time).
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "INSERT INTO maxfi_initial_value (position_id, source, initial_value_usd, set_at, set_by) "
        "VALUES (3, 'manual_override', 999.0, ?, 'human')",
        (CAPTURED_AT,),
    )
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()

    summary = resolve_ambiguous_auto_splits(
        conn, CHAIN, WALLET, [_mstr_group()],
        _mstr_current_values(), _mstr_departing_info(), _mstr_current_positions(),
        SCHEMA_STATUS_READY, CAPTURED_AT,
    )

    assert summary["resolved"] == 1

    row_834942_id = conn.execute(
        "SELECT id FROM maxfi_positions WHERE token_id = '834942'"
    ).fetchone()[0]
    assert row_834942_id == 3  # confirms the predicted id actually landed

    preserved = conn.execute(
        "SELECT source, initial_value_usd FROM maxfi_initial_value WHERE position_id = 3"
    ).fetchone()
    assert preserved == ("manual_override", 999.0)  # untouched

    other_row = conn.execute(
        "SELECT iv.source FROM maxfi_initial_value iv JOIN maxfi_positions p ON p.id = iv.position_id "
        "WHERE p.token_id = '842318'"
    ).fetchone()
    assert other_row is not None
    assert other_row[0] == AMBIGUITY_AUTO_SPLIT_SOURCE  # the other arriving position still got its row


# ── 5. first_seen_at inheritance; get_vault_deposit_info is never called ────

def test_first_seen_at_inheritance_and_vault_deposit_info_never_called(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("get_vault_deposit_info must never be called by the auto-split write path")
    monkeypatch.setattr(orch, "get_vault_deposit_info", _boom)

    conn = make_db()
    earlier = "2026-05-15T00:00:00+00:00"
    later = "2026-06-01T00:00:00+00:00"
    _seed_open_position(conn, "799578", 0, first_seen_at=later)
    _seed_open_position(conn, "770744", 1, first_seen_at=earlier)

    departing_info = _mstr_departing_info(
        first_seen_799578=datetime(2026, 6, 1, tzinfo=timezone.utc),
        first_seen_770744=datetime(2026, 5, 15, tzinfo=timezone.utc),
    )

    summary = resolve_ambiguous_auto_splits(
        conn, CHAIN, WALLET, [_mstr_group()],
        _mstr_current_values(), departing_info, _mstr_current_positions(),
        SCHEMA_STATUS_READY, CAPTURED_AT,
    )

    assert summary["resolved"] == 1

    first_seen_ats = conn.execute(
        "SELECT DISTINCT first_seen_at FROM maxfi_positions WHERE token_id IN ('834942', '842318')"
    ).fetchall()
    assert len(first_seen_ats) == 1
    assert first_seen_ats[0][0] == earlier  # both arriving rows inherit the EARLIER date


# ── 6. 'defer_pricing' writes absolutely nothing ────────────────────────────

def test_defer_pricing_writes_nothing():
    conn = make_db()
    _seed_open_position(conn, "799578", 0)
    _seed_open_position(conn, "770744", 1)

    current_values = {"834942": 257.53, "842318": None}  # one missing -> defer_pricing

    summary = resolve_ambiguous_auto_splits(
        conn, CHAIN, WALLET, [_mstr_group()],
        current_values, _mstr_departing_info(), _mstr_current_positions(),
        SCHEMA_STATUS_READY, CAPTURED_AT,
    )

    assert summary["deferred"] == 1
    assert summary["resolved"] == 0
    assert summary["skipped"] == []

    assert conn.execute(
        "SELECT status FROM maxfi_positions WHERE token_id = '799578'"
    ).fetchone()[0] == "open"
    assert conn.execute(
        "SELECT status FROM maxfi_positions WHERE token_id = '770744'"
    ).fetchone()[0] == "open"
    assert conn.execute("SELECT COUNT(*) FROM maxfi_positions").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM maxfi_initial_value").fetchone()[0] == 0


# ── 7. 'auto_split_no_basis': positions open with no basis; notes records it ─

def test_auto_split_no_basis_writes_positions_but_no_initial_value_and_records_notes():
    conn = make_db()
    _seed_open_position(conn, "799578", 0)
    _seed_open_position(conn, "770744", 1)

    departing_info = _mstr_departing_info(basis_799578=None)  # one missing basis

    summary = resolve_ambiguous_auto_splits(
        conn, CHAIN, WALLET, [_mstr_group()],
        _mstr_current_values(), departing_info, _mstr_current_positions(),
        SCHEMA_STATUS_READY, CAPTURED_AT,
    )

    assert summary["resolved"] == 1

    arriving_rows = conn.execute(
        "SELECT token_id, status, notes FROM maxfi_positions WHERE token_id IN ('834942', '842318')"
    ).fetchall()
    assert len(arriving_rows) == 2
    for token_id, status, notes in arriving_rows:
        assert status == "open"
        payload = json.loads(notes)
        assert payload["outcome"] == "auto_split_no_basis"
        assert payload["discarded_basis"]["initial_value_usd"] == pytest.approx(259.00, abs=1e-9)
        assert payload["discarded_basis"]["token_id"] == "770744"

    assert conn.execute("SELECT COUNT(*) FROM maxfi_initial_value").fetchone()[0] == 0


# ── 8. Refuses to run at all when the unique index isn't confirmed present ──

def test_refuses_when_unique_index_not_ready():
    conn = make_db()
    _seed_open_position(conn, "799578", 0)
    _seed_open_position(conn, "770744", 1)

    summary = resolve_ambiguous_auto_splits(
        conn, CHAIN, WALLET, [_mstr_group()],
        _mstr_current_values(), _mstr_departing_info(), _mstr_current_positions(),
        {"unique_index_ready": False, "notes_column_ready": True}, CAPTURED_AT,
    )

    assert summary == {"resolved": 0, "skipped": [], "deferred": 0, "manual": 0,
                        "refused": True, "reason": "unique_index_not_ready",
                        "closed_by_auto_split": 0, "opened_by_auto_split": 0}

    assert conn.execute("SELECT COUNT(*) FROM maxfi_positions").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM maxfi_initial_value").fetchone()[0] == 0
