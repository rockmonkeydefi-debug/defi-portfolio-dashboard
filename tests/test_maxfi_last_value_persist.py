"""Tests for _maxfi_persist_last_values (MaxFi closing-value capture,
commit 2 of 4): rolling last_value_usd/last_value_at persistence for
priced open positions, run once per valuation cycle.

Same shared-cache-sqlite-URI + monkeypatched portfolio_db.get_connection
convention as tests/test_maxfi_valuation_route.py's iv_db fixture - the
helper opens and closes its OWN connection per call, so a fresh anonymous
':memory:' db would lose all state the instant that connection closed.
web_portfolio spawns a background scheduler on non-__main__ import;
neutralized during import exactly like that file does.
"""
import sqlite3
import threading
import uuid

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import pytest

import maxfi_schema
import src.storage.portfolio_db as portfolio_db

CHAIN = "base"
WALLET = "0xWALLET"


@pytest.fixture
def lv_db(monkeypatch):
    uri = f"file:maxfi_lv_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    keepalive.row_factory = sqlite3.Row
    maxfi_schema.ensure_maxfi_tables(keepalive)

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    yield keepalive
    keepalive.close()


def _seed_position(db, position_id, token_id, status="open",
                    last_value_usd=None, last_value_at=None,
                    chain=CHAIN, wallet=WALLET):
    db.execute(
        """
        INSERT INTO maxfi_positions (
            id, chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, first_seen_block,
            last_scan_at, closed_at, last_value_usd, last_value_at
        ) VALUES (?, ?, ?, ?, 0, '0xPOOL', '0xT0', '0xT1', 3000, ?,
                  '2026-01-01T00:00:00+00:00', 'chain', '1',
                  '2026-01-01T00:00:00+00:00', NULL, ?, ?)
        """,
        (position_id, chain, wallet, str(token_id), status, last_value_usd, last_value_at),
    )
    db.commit()


def _last_value(db, position_id):
    row = db.execute(
        "SELECT last_value_usd, last_value_at FROM maxfi_positions WHERE id = ?", (position_id,)
    ).fetchone()
    return (row["last_value_usd"], row["last_value_at"])


def _last_uncollected(db, position_id):
    row = db.execute(
        "SELECT last_uncollected_usd FROM maxfi_positions WHERE id = ?", (position_id,)
    ).fetchone()
    return row["last_uncollected_usd"]


def _entry(token_id, status, current_value_usd, uncollected_usd=None):
    entry = {"token_id": token_id, "status": status, "current_value_usd": current_value_usd}
    if uncollected_usd is not None:
        entry["uncollected_usd"] = uncollected_usd
    return entry


# ── (a) priced entry gets written ────────────────────────────────────────

def test_priced_open_position_gets_last_value_written(lv_db):
    _seed_position(lv_db, 1, "100")

    ts = "2026-06-01T00:00:00+00:00"
    wp._maxfi_persist_last_values(CHAIN, WALLET, [_entry("100", "priced", 123.45)], ts)

    assert _last_value(lv_db, 1) == (123.45, ts)


# ── (b) overwrite-always ─────────────────────────────────────────────────

def test_second_cycle_overwrites_prior_value(lv_db):
    _seed_position(lv_db, 2, "200")

    ts1 = "2026-06-01T00:00:00+00:00"
    wp._maxfi_persist_last_values(CHAIN, WALLET, [_entry("200", "priced", 100.0)], ts1)
    assert _last_value(lv_db, 2) == (100.0, ts1)

    ts2 = "2026-06-02T00:00:00+00:00"
    wp._maxfi_persist_last_values(CHAIN, WALLET, [_entry("200", "priced", 250.0)], ts2)
    assert _last_value(lv_db, 2) == (250.0, ts2)


# ── (c) unpriced / partial entries skipped ───────────────────────────────

def test_unpriced_and_partial_entries_are_skipped(lv_db):
    _seed_position(lv_db, 3, "300", last_value_usd=50.0, last_value_at="2026-01-01T00:00:00+00:00")

    wp._maxfi_persist_last_values(CHAIN, WALLET, [_entry("300", "unpriced", None)], "2026-06-01T00:00:00+00:00")
    assert _last_value(lv_db, 3) == (50.0, "2026-01-01T00:00:00+00:00")

    wp._maxfi_persist_last_values(CHAIN, WALLET, [_entry("300", "partial", 999.0)], "2026-06-02T00:00:00+00:00")
    assert _last_value(lv_db, 3) == (50.0, "2026-01-01T00:00:00+00:00")


# ── (d) non-finite value skipped ─────────────────────────────────────────

def test_non_finite_value_is_skipped(lv_db):
    _seed_position(lv_db, 4, "400", last_value_usd=75.0, last_value_at="2026-01-01T00:00:00+00:00")

    wp._maxfi_persist_last_values(CHAIN, WALLET, [_entry("400", "priced", float("nan"))], "2026-06-01T00:00:00+00:00")
    assert _last_value(lv_db, 4) == (75.0, "2026-01-01T00:00:00+00:00")

    wp._maxfi_persist_last_values(CHAIN, WALLET, [_entry("400", "priced", float("inf"))], "2026-06-02T00:00:00+00:00")
    assert _last_value(lv_db, 4) == (75.0, "2026-01-01T00:00:00+00:00")


# ── (e) closed rows never touched ────────────────────────────────────────

def test_closed_rows_never_touched(lv_db):
    _seed_position(lv_db, 5, "500", status="closed")

    wp._maxfi_persist_last_values(CHAIN, WALLET, [_entry("500", "priced", 42.0)], "2026-06-01T00:00:00+00:00")

    assert _last_value(lv_db, 5) == (None, None)


# ── (h) C1.1: last_uncollected_usd persisted alongside last_value_usd ──────

def test_priced_entry_with_uncollected_writes_both_columns(lv_db):
    _seed_position(lv_db, 6, "600")

    ts = "2026-06-01T00:00:00+00:00"
    wp._maxfi_persist_last_values(
        CHAIN, WALLET, [_entry("600", "priced", 123.45, uncollected_usd=9.87)], ts
    )

    assert _last_value(lv_db, 6) == (123.45, ts)
    assert _last_uncollected(lv_db, 6) == pytest.approx(9.87)


def test_second_cycle_overwrites_prior_uncollected_value(lv_db):
    _seed_position(lv_db, 7, "700")

    ts1 = "2026-06-01T00:00:00+00:00"
    wp._maxfi_persist_last_values(
        CHAIN, WALLET, [_entry("700", "priced", 100.0, uncollected_usd=5.0)], ts1
    )
    assert _last_uncollected(lv_db, 7) == pytest.approx(5.0)

    ts2 = "2026-06-02T00:00:00+00:00"
    wp._maxfi_persist_last_values(
        CHAIN, WALLET, [_entry("700", "priced", 250.0, uncollected_usd=12.5)], ts2
    )
    assert _last_uncollected(lv_db, 7) == pytest.approx(12.5)


def test_uncollected_of_exactly_zero_is_written_not_null(lv_db):
    _seed_position(lv_db, 8, "800")

    wp._maxfi_persist_last_values(
        CHAIN, WALLET, [_entry("800", "priced", 50.0, uncollected_usd=0.0)],
        "2026-06-01T00:00:00+00:00",
    )

    assert _last_uncollected(lv_db, 8) == 0.0


def test_missing_or_bad_uncollected_writes_null_but_value_still_written(lv_db):
    _seed_position(lv_db, 9, "900")
    _seed_position(lv_db, 10, "901")
    _seed_position(lv_db, 11, "902")
    ts = "2026-06-01T00:00:00+00:00"

    # Missing key entirely (no uncollected_usd= passed) - .get() returns None.
    wp._maxfi_persist_last_values(CHAIN, WALLET, [_entry("900", "priced", 10.0)], ts)
    assert _last_value(lv_db, 9) == (10.0, ts)
    assert _last_uncollected(lv_db, 9) is None

    # Non-finite.
    wp._maxfi_persist_last_values(
        CHAIN, WALLET, [_entry("901", "priced", 20.0, uncollected_usd=float("nan"))], ts
    )
    assert _last_value(lv_db, 10) == (20.0, ts)
    assert _last_uncollected(lv_db, 10) is None

    wp._maxfi_persist_last_values(
        CHAIN, WALLET, [_entry("902", "priced", 30.0, uncollected_usd=float("inf"))], ts
    )
    assert _last_value(lv_db, 11) == (30.0, ts)
    assert _last_uncollected(lv_db, 11) is None


# ── (f) failure isolation ────────────────────────────────────────────────

def test_helper_failure_is_swallowed(monkeypatch):
    def _boom():
        raise RuntimeError("connection pool exhausted")
    monkeypatch.setattr(portfolio_db, "get_connection", _boom)

    # Must not raise - the failure is logged and swallowed.
    wp._maxfi_persist_last_values(CHAIN, WALLET, [_entry("1", "priced", 1.0)], "2026-06-01T00:00:00+00:00")


# ── (g) zero eligible entries opens no connection ────────────────────────

def test_zero_eligible_entries_opens_no_connection(monkeypatch):
    def _fail_if_called():
        pytest.fail("get_connection was called with zero eligible entries")
    monkeypatch.setattr(portfolio_db, "get_connection", _fail_if_called)

    wp._maxfi_persist_last_values(
        CHAIN, WALLET,
        [_entry("1", "unpriced", None), _entry("2", "partial", 10.0)],
        "2026-06-01T00:00:00+00:00",
    )
