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
        "ath_source",
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
        "ath_source",
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


# ── GeckoTerminal backfill workstream (commit 1 of 3): ath_source ───────────

def _insert_stats_row(conn, chain="base", address="0xabc", price=1.0, ts="2026-09-06T00:00:00Z", **extra):
    columns = ["chain", "address", "symbol", "last_price_usd", "last_price_at",
               "ath_price_usd", "ath_at", "first_recorded_at"]
    values = [chain, address, "FOO", price, ts, price, ts, ts]
    for k, v in extra.items():
        columns.append(k)
        values.append(v)
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO maxfi_token_price_stats ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    conn.commit()


def test_ath_source_exists_and_defaults_to_observed_on_fresh_insert():
    conn = make_db()
    columns = table_columns(conn, "maxfi_token_price_stats")
    assert "ath_source" in columns

    # Insert WITHOUT naming ath_source - must read back the column default.
    _insert_stats_row(conn)
    row = conn.execute(
        "SELECT ath_source FROM maxfi_token_price_stats WHERE chain='base' AND address='0xabc'"
    ).fetchone()
    assert row[0] == "observed"


def test_ath_source_default_applies_to_rows_that_predate_the_column():
    """Simulates the real migration order: a row is written by the CREATE
    TABLE shape BEFORE this commit (no ath_source column at all), then
    ensure_maxfi_tables runs the ALTER on top of it. SQLite's documented
    behaviour for `ADD COLUMN ... DEFAULT` is to report that default for
    every pre-existing row, not NULL - this test pins that behaviour rather
    than assuming it."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    # The exact pre-ath_source maxfi_token_price_stats shape (copied, not
    # imported - ensure_maxfi_tables's CREATE TABLE IF NOT EXISTS below must
    # not recreate or alter the columns of a table that already exists).
    conn.execute("""
        CREATE TABLE maxfi_token_price_stats (
          chain             TEXT NOT NULL,
          address           TEXT NOT NULL,
          symbol            TEXT,
          last_price_usd    REAL NOT NULL,
          last_price_at     TEXT NOT NULL,
          ath_price_usd     REAL NOT NULL,
          ath_at            TEXT NOT NULL,
          first_recorded_at TEXT NOT NULL,
          PRIMARY KEY (chain, address)
        )
    """)
    _insert_stats_row(conn, chain="base", address="0xpre")
    conn.commit()

    maxfi_schema.ensure_maxfi_tables(conn)

    row = conn.execute(
        "SELECT ath_source FROM maxfi_token_price_stats WHERE chain='base' AND address='0xpre'"
    ).fetchone()
    assert row[0] == "observed"


def test_live_upsert_shape_never_clobbers_a_manually_set_ath_source():
    """Guards the live valuation upsert's can't-clobber property
    structurally: the exact ON CONFLICT(chain, address) DO UPDATE statement
    web_portfolio.py's _maxfi_persist_token_price_stats runs (copied here,
    not imported, per this commit's schema-only scope) never names
    ath_source in its SET clause, so a manually-set 'backfilled' value must
    survive a fresh price observation untouched."""
    conn = make_db()
    _insert_stats_row(conn)
    conn.execute(
        "UPDATE maxfi_token_price_stats SET ath_source = 'backfilled' "
        "WHERE chain='base' AND address='0xabc'"
    )
    conn.commit()

    conn.execute(
        """
        INSERT INTO maxfi_token_price_stats
          (chain, address, symbol, last_price_usd, last_price_at,
           ath_price_usd, ath_at, first_recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chain, address) DO UPDATE SET
          last_price_usd = excluded.last_price_usd,
          last_price_at  = excluded.last_price_at,
          symbol         = COALESCE(excluded.symbol, symbol),
          ath_at         = CASE WHEN excluded.last_price_usd > ath_price_usd
                                THEN excluded.last_price_at ELSE ath_at END,
          ath_price_usd  = CASE WHEN excluded.last_price_usd > ath_price_usd
                                THEN excluded.last_price_usd ELSE ath_price_usd END
        """,
        ("base", "0xabc", "FOO", 2.0, "2026-09-06T01:00:00Z",
         2.0, "2026-09-06T01:00:00Z", "2026-09-06T01:00:00Z"),
    )
    conn.commit()

    row = conn.execute(
        "SELECT last_price_usd, ath_price_usd, ath_source FROM maxfi_token_price_stats "
        "WHERE chain='base' AND address='0xabc'"
    ).fetchone()
    assert row[0] == 2.0          # the upsert itself still works
    assert row[1] == 2.0
    assert row[2] == "backfilled"  # untouched by the SET clause


def test_ensure_maxfi_tables_return_dict_unchanged_with_ath_source():
    conn = make_db()
    result = maxfi_schema.ensure_maxfi_tables(conn)
    assert set(result.keys()) == {"unique_index_ready", "notes_column_ready"}


def test_ensure_maxfi_tables_idempotent_for_ath_source():
    conn = make_db()
    # Second call must not raise, and the column must remain intact.
    maxfi_schema.ensure_maxfi_tables(conn)

    columns = table_columns(conn, "maxfi_token_price_stats")
    assert "ath_source" in columns
