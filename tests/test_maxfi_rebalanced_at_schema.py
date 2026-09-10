"""Schema tests for LP Advisor C1.2 (commit 1 of 2: schema only):
maxfi_positions.last_rebalanced_at, added via the same guarded-ALTER
pattern already used for notes/closed_by/open_token_price_usd/
open_token_price_source/ath_source/last_value_usd/last_value_at/
last_uncollected_usd.

In-memory SQLite, same arrange style as
tests/test_maxfi_closing_value_schema.py.
"""

import sqlite3

import maxfi_schema


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    maxfi_schema.ensure_maxfi_tables(conn)
    return conn


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_new_column_exists_after_ensure():
    conn = make_db()

    positions_cols = _columns(conn, "maxfi_positions")
    assert "last_rebalanced_at" in positions_cols


def test_ensure_twice_is_a_noop_for_new_column():
    conn = make_db()
    # make_db() already ran ensure_maxfi_tables once - run it again and
    # confirm no exception, with the column present exactly once (PRAGMA
    # table_info can only ever report a column once per table regardless,
    # so the real assertion here is simply that the second call succeeds).
    maxfi_schema.ensure_maxfi_tables(conn)

    positions_rows = list(conn.execute("PRAGMA table_info(maxfi_positions)"))
    positions_names = [row[1] for row in positions_rows]
    assert positions_names.count("last_rebalanced_at") == 1


def test_migration_adds_column_to_preexisting_table():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")

    # Pre-migration shape - copied from maxfi_schema.py's own CREATE TABLE
    # statement, WITHOUT last_rebalanced_at and WITHOUT any of the other
    # ALTER-added columns (notes, closed_by, open_token_price_usd,
    # open_token_price_source, last_value_usd, last_value_at,
    # last_uncollected_usd).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS maxfi_positions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          chain TEXT NOT NULL,
          wallet TEXT NOT NULL,
          token_id TEXT NOT NULL,
          array_index INTEGER NOT NULL,
          pool_address TEXT NOT NULL,
          token0_address TEXT NOT NULL,
          token1_address TEXT NOT NULL,
          fee_tier INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'open',
          first_seen_at TEXT NOT NULL,
          first_seen_at_source TEXT NOT NULL,
          first_seen_block TEXT,
          last_scan_at TEXT NOT NULL,
          closed_at TEXT
        )
    """)
    conn.commit()

    positions_cols_before = _columns(conn, "maxfi_positions")
    assert "last_rebalanced_at" not in positions_cols_before

    maxfi_schema.ensure_maxfi_tables(conn)

    positions_cols_after = _columns(conn, "maxfi_positions")
    assert "last_rebalanced_at" in positions_cols_after


def test_last_rebalanced_at_defaults_null_on_existing_rows():
    conn = make_db()

    conn.execute(
        """
        INSERT INTO maxfi_positions (
            chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, last_scan_at
        ) VALUES ('base', '0xWALLET', '1', 0, '0xPOOL', '0xTOKEN0', '0xTOKEN1',
                  3000, 'open', '2026-01-01T00:00:00+00:00', 'chain',
                  '2026-01-01T00:00:00+00:00')
        """
    )
    conn.commit()

    row = conn.execute(
        "SELECT last_rebalanced_at FROM maxfi_positions WHERE token_id = '1'"
    ).fetchone()
    assert row[0] is None


def test_return_dict_keys_unchanged():
    conn = make_db()
    status = maxfi_schema.ensure_maxfi_tables(conn)
    assert set(status.keys()) == {"unique_index_ready", "notes_column_ready"}
