"""Schema-only tests for the LP Advisor Phase A2 tables: maxfi_catalogue_pools
(on-chain-enumerated MaxFi pool catalogue), maxfi_pool_metrics (DexScreener
overwrite-always snapshot), and maxfi_token_daily (bounded 35-row rolling
daily-close window). Follows tests/test_maxfi_token_price_stats.py's
conventions: in-memory sqlite, direct ensure_maxfi_tables() call, no
network, no Flask.
"""
import sqlite3

import maxfi_schema


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    maxfi_schema.ensure_maxfi_tables(conn)
    return conn


def table_columns(conn, table):
    return {row[1]: row for row in conn.execute(f"PRAGMA table_info({table})")}


# ── maxfi_catalogue_pools ────────────────────────────────────────────────

def test_maxfi_catalogue_pools_created_with_expected_columns_and_pk():
    conn = make_db()
    columns = table_columns(conn, "maxfi_catalogue_pools")

    expected = {
        "chain", "pool_address", "token0_address", "token1_address",
        "token0_symbol", "token1_symbol", "fee_tier", "position_count",
        "first_seen_at", "last_seen_at", "last_enumerated_at",
    }
    assert set(columns.keys()) == expected

    pk_columns = {name for name, row in columns.items() if row[5] > 0}
    assert pk_columns == {"chain", "pool_address"}


def _insert_catalogue_pool(conn, chain="base", pool_address="0xpool", ts="2026-09-06T00:00:00Z"):
    conn.execute(
        """
        INSERT INTO maxfi_catalogue_pools (
          chain, pool_address, token0_address, token1_address,
          token0_symbol, token1_symbol, fee_tier, position_count,
          first_seen_at, last_seen_at, last_enumerated_at
        ) VALUES (?, ?, '0xtoken0', '0xtoken1', 'FOO', 'USDC', 3000, 1, ?, ?, ?)
        """,
        (chain, pool_address, ts, ts, ts),
    )
    conn.commit()


def test_maxfi_catalogue_pools_composite_pk_enforced():
    conn = make_db()
    _insert_catalogue_pool(conn)

    try:
        _insert_catalogue_pool(conn)
        assert False, "expected IntegrityError on duplicate (chain, pool_address)"
    except sqlite3.IntegrityError:
        pass

    # Same pool_address on a different chain must succeed.
    _insert_catalogue_pool(conn, chain="robinhood")
    rows = conn.execute(
        "SELECT chain, pool_address FROM maxfi_catalogue_pools ORDER BY chain"
    ).fetchall()
    assert rows == [("base", "0xpool"), ("robinhood", "0xpool")]


# ── maxfi_pool_metrics ───────────────────────────────────────────────────

def test_maxfi_pool_metrics_created_with_expected_columns_and_pk():
    conn = make_db()
    columns = table_columns(conn, "maxfi_pool_metrics")

    expected = {
        "chain", "pool_address", "price_usd", "liquidity_usd",
        "volume_h24", "volume_h6", "volume_h1", "price_change_h24", "fetched_at",
    }
    assert set(columns.keys()) == expected

    pk_columns = {name for name, row in columns.items() if row[5] > 0}
    assert pk_columns == {"chain", "pool_address"}


def _insert_pool_metrics(conn, chain="base", pool_address="0xpool", ts="2026-09-06T00:00:00Z"):
    conn.execute(
        """
        INSERT INTO maxfi_pool_metrics (
          chain, pool_address, price_usd, liquidity_usd,
          volume_h24, volume_h6, volume_h1, price_change_h24, fetched_at
        ) VALUES (?, ?, 1.0, 1000.0, 100.0, 10.0, 1.0, 0.5, ?)
        """,
        (chain, pool_address, ts),
    )
    conn.commit()


def test_maxfi_pool_metrics_composite_pk_enforced():
    conn = make_db()
    _insert_pool_metrics(conn)

    try:
        _insert_pool_metrics(conn)
        assert False, "expected IntegrityError on duplicate (chain, pool_address)"
    except sqlite3.IntegrityError:
        pass

    _insert_pool_metrics(conn, chain="robinhood")
    rows = conn.execute(
        "SELECT chain, pool_address FROM maxfi_pool_metrics ORDER BY chain"
    ).fetchall()
    assert rows == [("base", "0xpool"), ("robinhood", "0xpool")]


def test_maxfi_pool_metrics_metric_columns_are_nullable():
    conn = make_db()
    conn.execute(
        """
        INSERT INTO maxfi_pool_metrics (chain, pool_address, fetched_at)
        VALUES ('base', '0xpool', '2026-09-06T00:00:00Z')
        """
    )
    conn.commit()
    row = conn.execute(
        "SELECT price_usd, liquidity_usd, volume_h24, volume_h6, volume_h1, price_change_h24 "
        "FROM maxfi_pool_metrics WHERE chain='base' AND pool_address='0xpool'"
    ).fetchone()
    assert row == (None, None, None, None, None, None)


# ── maxfi_token_daily ────────────────────────────────────────────────────

def test_maxfi_token_daily_created_with_expected_columns_and_pk():
    conn = make_db()
    columns = table_columns(conn, "maxfi_token_daily")

    expected = {
        "chain", "address", "date", "close_usd",
        "source_pool_address", "fetched_at",
    }
    assert set(columns.keys()) == expected

    pk_columns = {name for name, row in columns.items() if row[5] > 0}
    assert pk_columns == {"chain", "address", "date"}


def _insert_token_daily(conn, chain="base", address="0xabc", date="2026-09-06", ts="2026-09-06T00:00:00Z"):
    conn.execute(
        """
        INSERT INTO maxfi_token_daily (
          chain, address, date, close_usd, source_pool_address, fetched_at
        ) VALUES (?, ?, ?, 1.0, '0xpool', ?)
        """,
        (chain, address, date, ts),
    )
    conn.commit()


def test_maxfi_token_daily_composite_pk_enforced():
    conn = make_db()
    _insert_token_daily(conn)

    try:
        _insert_token_daily(conn)
        assert False, "expected IntegrityError on duplicate (chain, address, date)"
    except sqlite3.IntegrityError:
        pass

    # Same (chain, address) on a different date must succeed.
    _insert_token_daily(conn, date="2026-09-07")
    rows = conn.execute(
        "SELECT date FROM maxfi_token_daily WHERE chain='base' AND address='0xabc' ORDER BY date"
    ).fetchall()
    assert rows == [("2026-09-06",), ("2026-09-07",)]


# ── MAXFI_TOKEN_DAILY_MAX_ROWS ───────────────────────────────────────────

def test_maxfi_token_daily_max_rows_is_35():
    assert maxfi_schema.MAXFI_TOKEN_DAILY_MAX_ROWS == 35


# ── idempotency ──────────────────────────────────────────────────────────

def test_ensure_maxfi_tables_idempotent_for_phase_a2_tables():
    conn = make_db()
    # Second call must not raise, and all three new tables must remain intact.
    maxfi_schema.ensure_maxfi_tables(conn)

    assert set(table_columns(conn, "maxfi_catalogue_pools").keys()) == {
        "chain", "pool_address", "token0_address", "token1_address",
        "token0_symbol", "token1_symbol", "fee_tier", "position_count",
        "first_seen_at", "last_seen_at", "last_enumerated_at",
    }
    assert set(table_columns(conn, "maxfi_pool_metrics").keys()) == {
        "chain", "pool_address", "price_usd", "liquidity_usd",
        "volume_h24", "volume_h6", "volume_h1", "price_change_h24", "fetched_at",
    }
    assert set(table_columns(conn, "maxfi_token_daily").keys()) == {
        "chain", "address", "date", "close_usd",
        "source_pool_address", "fetched_at",
    }


# ── return-dict contract ─────────────────────────────────────────────────

def test_ensure_maxfi_tables_return_dict_unchanged_by_phase_a2():
    conn = make_db()
    result = maxfi_schema.ensure_maxfi_tables(conn)
    # Exact key set as read from the file before this commit's edits -
    # any future key addition must fail this test loudly.
    assert set(result.keys()) == {"unique_index_ready", "notes_column_ready"}
