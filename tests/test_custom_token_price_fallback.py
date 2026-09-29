"""Custom-token last-good-price fallback (level-shift PR 3).

Covers the custom_token_price_snapshot table (success-only writes of the last
live DexScreener price per custom token).

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). No network."""
import sqlite3

import pytest

import src.storage.portfolio_db as portfolio_db


@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    return path


def _columns(path):
    conn = sqlite3.connect(path)
    try:
        return [(r[1], r[2], r[3], r[5]) for r in conn.execute("PRAGMA table_info(custom_token_price_snapshot)")]
    finally:
        conn.close()


# ── schema ─────────────────────────────────────────────────────────────────

def test_init_db_creates_the_table_with_exact_columns(dbpath):
    # (name, type, notnull, pk)
    assert _columns(dbpath) == [
        ("id", "INTEGER", 0, 1),
        ("contract", "TEXT", 1, 0),
        ("chain", "TEXT", 1, 0),
        ("price_usd", "REAL", 1, 0),
        ("fetched_at", "TEXT", 1, 0),
    ]
    conn = sqlite3.connect(dbpath)
    try:
        conn.execute("INSERT INTO custom_token_price_snapshot (contract, chain, price_usd, fetched_at) "
                     "VALUES ('0xabc', 'base', 1.0, '2026-09-29T00:00:00+00:00')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO custom_token_price_snapshot (contract, chain, price_usd, fetched_at) "
                         "VALUES ('0xabc', 'base', 2.0, '2026-09-29T01:00:00+00:00')")
    finally:
        conn.close()


def test_init_db_twice_is_harmless(dbpath):
    conn = sqlite3.connect(dbpath)
    conn.execute("INSERT INTO custom_token_price_snapshot (contract, chain, price_usd, fetched_at) "
                 "VALUES ('0xabc', 'base', 1.0, '2026-09-29T00:00:00+00:00')")
    conn.commit()
    conn.close()
    before = _columns(dbpath)
    portfolio_db.init_db()
    assert _columns(dbpath) == before
    conn = sqlite3.connect(dbpath)
    try:
        assert conn.execute("SELECT contract, price_usd FROM custom_token_price_snapshot").fetchall() == [("0xabc", 1.0)]
    finally:
        conn.close()
