import sqlite3

import maxfi_schema


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    maxfi_schema.ensure_maxfi_tables(conn)
    return conn


def table_columns(conn, table):
    return {row[1]: row for row in conn.execute(f"PRAGMA table_info({table})")}


def test_maxfi_token_price_stats_created_with_expected_columns_and_pk():
    conn = make_db()
    columns = table_columns(conn, "maxfi_token_price_stats")

    expected = {
        "chain",
        "address",
        "symbol",
        "last_price_usd",
        "last_price_at",
        "ath_price_usd",
        "ath_at",
        "first_recorded_at",
    }
    assert set(columns.keys()) == expected

    pk_columns = {name for name, row in columns.items() if row[5] > 0}
    assert pk_columns == {"chain", "address"}


def test_ensure_maxfi_tables_idempotent_for_token_price_stats():
    conn = make_db()
    # Second call must not raise, and the table/columns must remain intact.
    maxfi_schema.ensure_maxfi_tables(conn)

    columns = table_columns(conn, "maxfi_token_price_stats")
    expected = {
        "chain",
        "address",
        "symbol",
        "last_price_usd",
        "last_price_at",
        "ath_price_usd",
        "ath_at",
        "first_recorded_at",
    }
    assert set(columns.keys()) == expected


def test_maxfi_positions_gains_open_token_price_columns_null_by_default():
    conn = make_db()
    columns = table_columns(conn, "maxfi_positions")
    assert "open_token_price_usd" in columns
    assert "open_token_price_source" in columns

    conn.execute(
        """
        INSERT INTO maxfi_positions (
          chain, wallet, token_id, array_index, pool_address,
          token0_address, token1_address, fee_tier, status,
          first_seen_at, first_seen_at_source, last_scan_at
        ) VALUES (
          'base', '0xwallet', '1', 0, '0xpool',
          '0xtoken0', '0xtoken1', 500, 'open',
          '2026-09-06T00:00:00Z', 'scan', '2026-09-06T00:00:00Z'
        )
        """
    )
    conn.commit()

    row = conn.execute(
        "SELECT open_token_price_usd, open_token_price_source FROM maxfi_positions"
    ).fetchone()
    assert row == (None, None)


def test_ensure_maxfi_tables_return_dict_unchanged():
    conn = make_db()
    result = maxfi_schema.ensure_maxfi_tables(conn)
    assert set(result.keys()) == {"unique_index_ready", "notes_column_ready"}


def test_maxfi_token_price_stats_composite_pk_enforced():
    conn = make_db()
    conn.execute(
        """
        INSERT INTO maxfi_token_price_stats (
          chain, address, symbol, last_price_usd, last_price_at,
          ath_price_usd, ath_at, first_recorded_at
        ) VALUES (
          'base', '0xabc', 'FOO', 1.0, '2026-09-06T00:00:00Z',
          1.0, '2026-09-06T00:00:00Z', '2026-09-06T00:00:00Z'
        )
        """
    )
    conn.commit()

    try:
        conn.execute(
            """
            INSERT INTO maxfi_token_price_stats (
              chain, address, symbol, last_price_usd, last_price_at,
              ath_price_usd, ath_at, first_recorded_at
            ) VALUES (
              'base', '0xabc', 'FOO', 2.0, '2026-09-06T01:00:00Z',
              2.0, '2026-09-06T01:00:00Z', '2026-09-06T01:00:00Z'
            )
            """
        )
        conn.commit()
        assert False, "expected IntegrityError on duplicate (chain, address)"
    except sqlite3.IntegrityError:
        pass

    # Same address on a different chain must succeed.
    conn.execute(
        """
        INSERT INTO maxfi_token_price_stats (
          chain, address, symbol, last_price_usd, last_price_at,
          ath_price_usd, ath_at, first_recorded_at
        ) VALUES (
          'robinhood', '0xabc', 'FOO', 1.0, '2026-09-06T00:00:00Z',
          1.0, '2026-09-06T00:00:00Z', '2026-09-06T00:00:00Z'
        )
        """
    )
    conn.commit()

    rows = conn.execute(
        "SELECT chain, address FROM maxfi_token_price_stats ORDER BY chain"
    ).fetchall()
    assert rows == [("base", "0xabc"), ("robinhood", "0xabc")]
