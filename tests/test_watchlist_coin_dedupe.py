"""Prevent duplicate tickers — the same HL coin under different symbol spellings
(e.g. a -USDC spot vs a -USDT perp, or ETH-USDT vs ETHUSDT) — from entering the
watchlist via Import HL or manual Add.

Identity is resolution to the canonical HL coin (_scanner_symbol_to_coin ->
_hl_resolve_coin), NOT a string heuristic. _hl_resolve_coin is stubbed per test so
the suite is hermetic: the quote-suffix strip in _scanner_symbol_to_coin does the
real collapsing work and the stub just echoes the stripped base — no network.
"""
import sqlite3
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as _pdb


def _schema(c):
    c.executescript("""
        CREATE TABLE scanner_watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT UNIQUE,
            exchange TEXT, asset_type TEXT, htf_timeframe TEXT, ltf_timeframe TEXT,
            notes TEXT, contract_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE scanner_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, status TEXT,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    """)


def _open(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Temp-file DB with get_connection patched to hand out fresh conns."""
    path = str(tmp_path / 'dedupe.db')
    c = _open(path)
    _schema(c)
    c.commit()
    c.close()
    monkeypatch.setattr(_pdb, 'get_connection', lambda: _open(path))
    return path


def _seed(path, symbols):
    c = _open(path)
    for s in symbols:
        c.execute("INSERT INTO scanner_watchlist (symbol) VALUES (?)", (s,))
    c.commit()
    c.close()


def _stub_resolve(monkeypatch):
    # Offline resolver: _scanner_symbol_to_coin strips the quote suffix, this just
    # returns the stripped base verbatim (canonicalization is exercised elsewhere).
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda t: t)


def _unpack(resp):
    return (resp[0], resp[1]) if isinstance(resp, tuple) else (resp, 200)


# ── helper: _watchlist_coin_exists ────────────────────────────────────────────

def test_watchlist_coin_exists_matches_by_resolved_coin(db, monkeypatch):
    _stub_resolve(monkeypatch)
    _seed(db, ['WOWUSDT'])
    c = _open(db)
    assert wp._watchlist_coin_exists(c, 'WOW') is True      # WOWUSDT resolves to WOW
    assert wp._watchlist_coin_exists(c, 'BTC') is False
    assert wp._watchlist_coin_exists(c, None) is False      # falsy coin → fail-open
    c.close()


def test_watchlist_coin_exists_fail_open_on_resolution_error(db, monkeypatch):
    def _boom(_t):
        raise RuntimeError('HL universe unavailable')
    monkeypatch.setattr(wp, '_hl_resolve_coin', _boom)
    _seed(db, ['WOWUSDT'])
    c = _open(db)
    # No existing row resolves → nothing matches → False (fail-open: add proceeds).
    assert wp._watchlist_coin_exists(c, 'WOW') is False
    c.close()


# ── manual Add: reject same-coin dupe in BOTH directions ──────────────────────

def test_manual_add_rejects_when_usdc_form_exists(db, monkeypatch):
    _stub_resolve(monkeypatch)
    _seed(db, ['WOWUSDC'])                      # spot form already listed
    with wp.app.test_request_context(
            '/api/trading/scanner/watchlist', method='POST', json={'symbol': 'WOW'}):
        body, status = _unpack(wp.api_trading_scanner_watchlist_add())
    assert status == 409
    assert body.get_json()['error'] == 'Already on watchlist as WOWUSDC'
    c = _open(db)
    assert c.execute("SELECT COUNT(*) FROM scanner_watchlist").fetchone()[0] == 1
    c.close()


def test_manual_add_rejects_when_usdt_form_exists(db, monkeypatch):
    _stub_resolve(monkeypatch)
    _seed(db, ['WOWUSDT'])
    with wp.app.test_request_context(
            '/api/trading/scanner/watchlist', method='POST', json={'symbol': 'WOWUSDC'}):
        body, status = _unpack(wp.api_trading_scanner_watchlist_add())
    assert status == 409
    assert body.get_json()['error'] == 'Already on watchlist as WOWUSDT'
    c = _open(db)
    assert c.execute("SELECT COUNT(*) FROM scanner_watchlist").fetchone()[0] == 1
    c.close()


def test_manual_add_fail_open_when_resolution_unavailable(db, monkeypatch):
    def _boom(_t):
        raise RuntimeError('HL universe unavailable')
    monkeypatch.setattr(wp, '_hl_resolve_coin', _boom)
    _seed(db, ['WOWUSDT'])
    with wp.app.test_request_context(
            '/api/trading/scanner/watchlist', method='POST', json={'symbol': 'WOWUSDC'}):
        body, status = _unpack(wp.api_trading_scanner_watchlist_add())
    assert status == 200                       # coin check no-ops → add proceeds
    assert body.get_json()['success'] is True
    c = _open(db)
    assert c.execute("SELECT COUNT(*) FROM scanner_watchlist").fetchone()[0] == 2
    c.close()


# ── Import HL: skip same-coin dupes ───────────────────────────────────────────

def _stub_import_assets(monkeypatch, assets):
    monkeypatch.setattr(wp, '_hl_fetch_top_volume', lambda *a, **k: list(assets))


def test_import_skips_dashed_twin_of_existing(db, monkeypatch):
    _stub_resolve(monkeypatch)
    _seed(db, ['ETHUSDT'])
    _stub_import_assets(monkeypatch,
                        [{'symbol': 'ETH-USDT', 'asset_type': 'crypto', 'volume_24h': 100.0}])
    with wp.app.test_request_context(
            '/api/trading/scanner/hl-import', method='POST', json={'n': 20}):
        payload = wp.api_trading_scanner_hl_import().get_json()
    assert payload['added'] == 0
    assert payload['skipped'] == 1
    c = _open(db)
    assert c.execute("SELECT COUNT(*) FROM scanner_watchlist").fetchone()[0] == 1
    c.close()


def test_import_skips_same_coin_quote_mismatch(db, monkeypatch):
    # Only the resolved-coin identity catches this — normalization keeps the
    # differing quotes (WOWUSDC vs WOWUSDT) as distinct strings.
    _stub_resolve(monkeypatch)
    _seed(db, ['WOWUSDT'])
    _stub_import_assets(monkeypatch,
                        [{'symbol': 'WOWUSDC', 'asset_type': 'crypto', 'volume_24h': 100.0}])
    with wp.app.test_request_context(
            '/api/trading/scanner/hl-import', method='POST', json={'n': 20}):
        payload = wp.api_trading_scanner_hl_import().get_json()
    assert payload['added'] == 0
    assert payload['skipped'] == 1
    c = _open(db)
    assert c.execute("SELECT COUNT(*) FROM scanner_watchlist").fetchone()[0] == 1
    c.close()


def test_import_adds_genuinely_new_coin(db, monkeypatch):
    _stub_resolve(monkeypatch)
    _seed(db, ['WOWUSDT'])
    _stub_import_assets(monkeypatch,
                        [{'symbol': 'ARBUSDT', 'asset_type': 'crypto', 'volume_24h': 100.0}])
    with wp.app.test_request_context(
            '/api/trading/scanner/hl-import', method='POST', json={'n': 20}):
        payload = wp.api_trading_scanner_hl_import().get_json()
    assert payload['added'] == 1
    assert payload['skipped'] == 0
    c = _open(db)
    assert {r['symbol'] for r in c.execute("SELECT symbol FROM scanner_watchlist")} == {'WOWUSDT', 'ARBUSDT'}
    c.close()
