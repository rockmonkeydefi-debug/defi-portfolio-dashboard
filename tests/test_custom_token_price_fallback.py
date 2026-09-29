"""Custom-token last-good-price fallback (level-shift PR 3).

Covers the custom_token_price_snapshot table (success-only writes of the last
live DexScreener price per custom token) and build_custom_token_rows' 24 h
fallback to it when a live price fails.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). No network."""
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

PLAZM = "0xA1FBB38bF486b97108aA87E92008187CA06998f6"
PLAZM_L = PLAZM.lower()
WALLET = "0x1111111111111111111111111111111111111111"


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


# ── the fallback in build_custom_token_rows ────────────────────────────────

@pytest.fixture
def env(dbpath, monkeypatch):
    """One custom token (PLAZM on base), one EVM wallet, caches cleared.
    Tests set the price / balance behaviour through the returned dict."""
    conn = sqlite3.connect(dbpath)
    conn.execute("INSERT INTO custom_tokens (chain, contract, symbol, decimals, added_at) "
                 "VALUES ('base', ?, 'PLAZM', 18, '2026-01-01T00:00:00')", (PLAZM,))
    conn.commit()
    conn.close()
    wp._dexscreener_price_cache.clear()
    wp._custom_balance_cache.clear()
    state = {"price": 2.0, "balance": 100000.0}

    def price(contract, chain=None, _now=None):
        return state["price"]

    def balance(chain, contract, wallet, decimals, _now=None):
        if state["balance"] is None:
            raise RuntimeError("rpc down")
        return state["balance"]
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [WALLET])
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {WALLET: {"label": "Main"}})
    monkeypatch.setattr(wp, "custom_token_chain_supported", lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_dexscreener_price", price)
    monkeypatch.setattr(wp, "fetch_erc20_balance_cached", balance)
    yield state
    wp._dexscreener_price_cache.clear()
    wp._custom_balance_cache.clear()


def _snapshot_rows(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT contract, chain, price_usd, fetched_at FROM custom_token_price_snapshot").fetchall()
    finally:
        conn.close()


def _seed_snapshot(path, price, fetched_at):
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO custom_token_price_snapshot (contract, chain, price_usd, fetched_at) VALUES (?, 'base', ?, ?)",
                 (PLAZM_L, price, fetched_at))
    conn.commit()
    conn.close()


def _hours_ago(h):
    return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()


def test_live_price_is_saved_and_row_not_stale(dbpath, env):
    rows = wp.build_custom_token_rows()
    assert len(rows) == 1
    row = rows[0]
    assert (row["price_usd"], row["value_usd"], row["price_stale"], row["price_as_of"]) == (2.0, 200000.0, False, None)
    [(contract, chain, price, fetched_at)] = _snapshot_rows(dbpath)
    assert (contract, chain, price) == (PLAZM_L, "base", 2.0)
    at = datetime.fromisoformat(fetched_at)
    assert at.tzinfo is not None and abs((datetime.now(timezone.utc) - at).total_seconds()) < 60


def test_saved_fetch_time_is_the_cached_fetch_time(dbpath, env):
    t0 = time.time() - 120
    wp._dexscreener_price_cache[PLAZM_L] = (2.0, t0)
    wp.build_custom_token_rows()
    [(_c, _ch, _p, fetched_at)] = _snapshot_rows(dbpath)
    assert fetched_at == datetime.fromtimestamp(t0, timezone.utc).isoformat()


def test_failed_price_carries_a_fresh_stored_price(dbpath, env):
    seeded = _hours_ago(3)
    _seed_snapshot(dbpath, 0.05, seeded)
    env["price"] = None
    [row] = wp.build_custom_token_rows()
    assert row["price_usd"] == 0.05
    assert row["value_usd"] == pytest.approx(5000.0)
    assert row["price_stale"] is True and row["price_as_of"] == seeded
    assert row["balance_failed"] is False
    assert _snapshot_rows(dbpath) == [(PLAZM_L, "base", 0.05, seeded)]


def test_stored_price_older_than_24h_is_not_carried(dbpath, env):
    seeded = _hours_ago(25)
    _seed_snapshot(dbpath, 0.05, seeded)
    env["price"] = None
    [row] = wp.build_custom_token_rows()
    assert (row["price_usd"], row["value_usd"], row["price_stale"], row["price_as_of"]) == (None, 0.0, False, None)
    assert _snapshot_rows(dbpath) == [(PLAZM_L, "base", 0.05, seeded)]


def test_zero_price_is_a_failed_price(dbpath, env):
    env["price"] = 0.0
    wp.build_custom_token_rows()
    assert _snapshot_rows(dbpath) == []                     # 0 is never written
    seeded = _hours_ago(1)
    _seed_snapshot(dbpath, 0.05, seeded)
    [row] = wp.build_custom_token_rows()
    assert row["price_usd"] == 0.05 and row["price_stale"] is True and row["price_as_of"] == seeded
    assert _snapshot_rows(dbpath) == [(PLAZM_L, "base", 0.05, seeded)]


def test_failed_balance_is_never_carried(dbpath, env):
    _seed_snapshot(dbpath, 0.05, _hours_ago(1))
    env["price"] = None
    env["balance"] = None
    [row] = wp.build_custom_token_rows()
    assert row["balance"] is None and row["value_usd"] == 0.0 and row["balance_failed"] is True


def test_snapshot_read_error_degrades_to_todays_rows(dbpath, env, monkeypatch):
    def boom(contracts):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(wp, "_custom_price_snapshot_read", boom)
    _seed_snapshot(dbpath, 0.05, _hours_ago(1))
    env["price"] = None
    [row] = wp.build_custom_token_rows()
    assert (row["price_usd"], row["value_usd"], row["price_stale"], row["price_as_of"]) == (None, 0.0, False, None)
    assert row["balance"] == 100000.0


def test_snapshot_write_error_leaves_live_rows_unchanged(dbpath, env, monkeypatch):
    def boom(entries):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(wp, "_custom_price_snapshot_upsert", boom)
    [row] = wp.build_custom_token_rows()
    assert (row["price_usd"], row["value_usd"], row["price_stale"], row["price_as_of"]) == (2.0, 200000.0, False, None)
    assert _snapshot_rows(dbpath) == []
