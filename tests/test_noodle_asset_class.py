"""Landing 46 (Oct 16): the Trends route tags each symbol crypto or TradFi.

Glenn asked for a Crypto / TradFi filter on Trends (ruling 2-A: tag on read,
no schema change). The scan strips HIP-3's 'xyz:' prefix and keeps no asset
type, so GET /api/trading/scanner/noodle-state tags each symbol from the two
cached Hyperliquid market lists (_HL_UNIVERSE_CACHE 'crypto' and 'xyz') with
_noodle_asset_class: crypto first (the order _hl_resolve_coin fetches
candles in), then TradFi, else None. Fixture convention: the shared-cache
in-memory SQLite + hand-rolled schema + client of
test_noodle_band_proximity.py, copied (no cross-file fixture imports).
"""
import sqlite3
import threading
import uuid

import src.storage.portfolio_db as portfolio_db

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import pytest

CRYPTO = {'BTC': 'BTC', 'KBONK': 'kBONK', 'HYPER': 'HYPER', 'GOLD': 'GOLD'}
XYZ = {'NVDA': 'xyz:NVDA', 'GOLD': 'xyz:GOLD', 'XYZ100': 'xyz:XYZ100'}


def test_crypto_name_is_crypto():
    assert wp._noodle_asset_class('BTC', CRYPTO, XYZ) == 'crypto'
    assert wp._noodle_asset_class('HYPER', CRYPTO, XYZ) == 'crypto'


def test_lookup_ignores_case_and_spaces():
    assert wp._noodle_asset_class('kBONK', CRYPTO, XYZ) == 'crypto'
    assert wp._noodle_asset_class(' nvda ', CRYPTO, XYZ) == 'tradfi'


def test_tradfi_name_is_tradfi():
    assert wp._noodle_asset_class('NVDA', CRYPTO, XYZ) == 'tradfi'
    assert wp._noodle_asset_class('XYZ100', CRYPTO, XYZ) == 'tradfi'


def test_name_on_both_lists_is_crypto_like_the_candle_lookup():
    assert wp._noodle_asset_class('GOLD', CRYPTO, XYZ) == 'crypto'


def test_unknown_or_missing_is_none():
    assert wp._noodle_asset_class('DELISTED', CRYPTO, XYZ) is None
    assert wp._noodle_asset_class('', CRYPTO, XYZ) is None
    assert wp._noodle_asset_class(None, CRYPTO, XYZ) is None
    assert wp._noodle_asset_class('BTC', {}, {}) is None
    assert wp._noodle_asset_class('NVDA', None, None) is None


NOODLE_STATE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS noodle_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        state TEXT,
        flip_ts REAL,
        flip_price REAL,
        flip_age_unbounded INTEGER,
        flip_count_window INTEGER,
        alignment_bull INTEGER,
        alignment_bear INTEGER,
        basis_ema REAL,
        upper_band REAL,
        lower_band REAL,
        last_close REAL,
        price REAL,
        computed_at TEXT,
        volume_24h REAL,
        alignment_state TEXT,
        alignment_prev_state TEXT,
        alignment_changed_ts REAL,
        alignment_changed_unbounded INTEGER,
        rs_vs_btc_pct REAL,
        doc_ema_fast REAL,
        doc_ema_slow REAL,
        doc_cross_state TEXT,
        doc_cross_ts REAL,
        doc_cross_unbounded INTEGER,
        UNIQUE(symbol, timeframe)
    )
"""


@pytest.fixture
def noodle_db(monkeypatch):
    uri = f"file:noodle_asset_class_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    keepalive.row_factory = sqlite3.Row
    keepalive.executescript(NOODLE_STATE_SCHEMA)
    keepalive.commit()

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    yield keepalive
    keepalive.close()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _seed(db, *symbols):
    for s in symbols:
        db.execute(
            "INSERT INTO noodle_state (symbol, timeframe, state, upper_band, lower_band, last_close, price, computed_at) "
            "VALUES (?, '1d', 'BULLISH', 110.0, 90.0, 100.0, 105.0, '2026-01-01T00:00:00+00:00')", (s,))
    db.commit()


def test_route_tags_each_symbol(client, noodle_db, monkeypatch):
    monkeypatch.setattr(wp, '_maybe_kick_noodle_auto_refresh', lambda: False)
    calls = []
    monkeypatch.setattr(wp, '_hl_refresh_universes', lambda force=False: calls.append(force))
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, 'crypto', CRYPTO)
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, 'xyz', XYZ)
    _seed(noodle_db, 'BTC', 'kBONK', 'NVDA', 'GOLD', 'DELISTED')
    resp = client.get('/api/trading/scanner/noodle-state')
    assert resp.status_code == 200
    got = {s['symbol']: s['asset_class'] for s in resp.get_json()['symbols']}
    assert got == {'BTC': 'crypto', 'kBONK': 'crypto', 'NVDA': 'tradfi', 'GOLD': 'crypto', 'DELISTED': None}
    assert calls == [False]                    # one best-effort refresh per read, never forced


def test_route_still_answers_when_the_refresh_fails_and_no_list_is_loaded(client, noodle_db, monkeypatch):
    monkeypatch.setattr(wp, '_maybe_kick_noodle_auto_refresh', lambda: False)

    def boom(force=False):
        raise RuntimeError('no network')
    monkeypatch.setattr(wp, '_hl_refresh_universes', boom)
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, 'crypto', None)
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, 'xyz', None)
    _seed(noodle_db, 'BTC', 'NVDA')
    resp = client.get('/api/trading/scanner/noodle-state')
    assert resp.status_code == 200
    got = {s['symbol']: s['asset_class'] for s in resp.get_json()['symbols']}
    assert got == {'BTC': None, 'NVDA': None}
