"""Schema-only tests for spot_price_snapshot (Spot stale-serve 1/3).

Runs the real init_db() against a temp-file SQLite (via a monkeypatched
get_db_path()) rather than a hand-rolled schema mirror, same pattern as
test_spot_transactions_schema.py - this also proves init_db() itself is
idempotent for this table.
"""
import sqlite3

import src.storage.portfolio_db as _pdb


def _open(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_spot_price_snapshot_has_exactly_the_expected_columns(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(_pdb, 'get_db_path', lambda: path)

    _pdb.init_db()

    conn = _open(path)
    cols = {row['name'] for row in conn.execute("PRAGMA table_info(spot_price_snapshot)")}
    assert cols == {'id', 'position_key', 'price_usd', 'fetched_at'}
    conn.close()


def test_spot_price_snapshot_enforces_unique_position_key(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(_pdb, 'get_db_path', lambda: path)

    _pdb.init_db()

    conn = _open(path)
    conn.execute(
        "INSERT INTO spot_price_snapshot (position_key, price_usd, fetched_at) "
        "VALUES ('base 0xABC', 1.5, '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    try:
        conn.execute(
            "INSERT INTO spot_price_snapshot (position_key, price_usd, fetched_at) "
            "VALUES ('base 0xABC', 2.0, '2026-01-02T00:00:00+00:00')"
        )
        conn.commit()
        assert False, "expected sqlite3.IntegrityError on duplicate position_key"
    except sqlite3.IntegrityError:
        pass
    conn.close()


def test_spot_price_snapshot_upsert_leaves_one_row_with_new_values(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(_pdb, 'get_db_path', lambda: path)

    _pdb.init_db()

    conn = _open(path)
    upsert_sql = (
        "INSERT INTO spot_price_snapshot (position_key, price_usd, fetched_at) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(position_key) DO UPDATE SET "
        "price_usd=excluded.price_usd, fetched_at=excluded.fetched_at"
    )
    conn.execute(upsert_sql, ('BTC', 50000.0, '2026-01-01T00:00:00+00:00'))
    conn.commit()
    conn.execute(upsert_sql, ('BTC', 51000.0, '2026-01-02T00:00:00+00:00'))
    conn.commit()

    rows = conn.execute(
        "SELECT price_usd, fetched_at FROM spot_price_snapshot WHERE position_key='BTC'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]['price_usd'] == 51000.0
    assert rows[0]['fetched_at'] == '2026-01-02T00:00:00+00:00'
    conn.close()


def test_init_db_twice_is_a_noop_for_spot_price_snapshot(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(_pdb, 'get_db_path', lambda: path)

    _pdb.init_db()

    conn = _open(path)
    conn.execute(
        "INSERT INTO spot_price_snapshot (position_key, price_usd, fetched_at) "
        "VALUES ('robinhood 0xDEF', 3.25, '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    _pdb.init_db()  # must not raise, and must not touch existing rows

    conn = _open(path)
    cols = {row['name'] for row in conn.execute("PRAGMA table_info(spot_price_snapshot)")}
    assert cols == {'id', 'position_key', 'price_usd', 'fetched_at'}
    row = conn.execute(
        "SELECT price_usd, fetched_at FROM spot_price_snapshot WHERE position_key='robinhood 0xDEF'"
    ).fetchone()
    assert row['price_usd'] == 3.25
    assert row['fetched_at'] == '2026-01-01T00:00:00+00:00'
    conn.close()
