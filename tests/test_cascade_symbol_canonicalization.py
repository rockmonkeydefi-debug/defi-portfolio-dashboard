"""cascade_state symbols are canonicalized by resolved HL coin, so a dashed
manual-scan symbol ('ZEC-USDT') and an undashed scheduled-scan symbol ('ZECUSDT')
for one coin share a single row (no board twins, no double compute).

_hl_resolve_coin is stubbed per test so the suite is hermetic: the quote-suffix
strip in _scanner_symbol_to_coin plus _normalize_symbol do the collapsing, and the
stub just echoes the stripped base — no network.
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

_ST = dict(wp._SCANNER_SETTINGS_DEFAULTS)


def _stub_resolve(monkeypatch):
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda t: t)


def _conn():
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE cascade_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, pair TEXT,
            stage INTEGER DEFAULT 0, root_poi_id TEXT, root_zone_top REAL,
            root_zone_bottom REAL, root_poi_type TEXT, nested_poi_id TEXT,
            nested_zone_top REAL, nested_zone_bottom REAL, nested_poi_type TEXT,
            first_tap_at TEXT, last_tap_at TEXT, root_bias TEXT, mss_detail TEXT,
            updated_at TEXT, UNIQUE(symbol, pair));
        CREATE TABLE cascade_transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, pair TEXT,
            from_stage INTEGER, to_stage INTEGER, reason TEXT, root_poi_id TEXT,
            nested_poi_id TEXT, detail TEXT, created_at TEXT);
    """)
    return c


def _ns0(bias='bullish'):
    """Minimal Stage-0 namespace state — reaches the persist upsert with no MSS /
    candle machinery (no network)."""
    return {'stage': 0, 'root_bias': bias, 'root_poi': None, 'nested_poi': None,
            'first_tap_at': None, 'last_tap_at': None,
            'root_candidates': [], 'nested_candidates': [], 'overlaps': [],
            'root_dr': {}, 'nested_dr': {}}


def _row(c, updated_at, symbol, pair='W_D', stage=1):
    c.execute("INSERT INTO cascade_state (symbol, pair, stage, updated_at) VALUES (?,?,?,?)",
              (symbol, pair, stage, updated_at))


# ── _canonical_scanner_symbol ─────────────────────────────────────────────────

def test_canonical_collapses_dashed_and_case(monkeypatch):
    _stub_resolve(monkeypatch)
    assert wp._canonical_scanner_symbol('ZEC-USDT') == 'ZECUSDT'
    assert wp._canonical_scanner_symbol('ZECUSDT') == 'ZECUSDT'
    assert wp._canonical_scanner_symbol('zecusdt') == 'ZECUSDT'
    assert wp._canonical_scanner_symbol('ZEC') == 'ZECUSDT'
    # idempotent
    assert wp._canonical_scanner_symbol(wp._canonical_scanner_symbol('ZEC-USDT')) == 'ZECUSDT'


def test_canonical_fail_open_on_resolution_error(monkeypatch):
    def _boom(_t):
        raise RuntimeError('HL universe unavailable')
    monkeypatch.setattr(wp, '_hl_resolve_coin', _boom)
    # Any error → input returned unchanged (never raises).
    assert wp._canonical_scanner_symbol('ZEC-USDT') == 'ZEC-USDT'
    assert wp._canonical_scanner_symbol('') == ''


# ── persist boundary lands on the canonical row ───────────────────────────────

def test_persist_dashed_lands_on_canonical_row(monkeypatch):
    _stub_resolve(monkeypatch)
    c = _conn()
    wp._persist_cascade_pair(c, 'ZEC-USDT', 'W_D', _ns0(), 't1', {}, _ST)
    rows = c.execute("SELECT symbol FROM cascade_state").fetchall()
    assert [r['symbol'] for r in rows] == ['ZECUSDT']       # canonical, not 'ZEC-USDT'

    # An undashed persist for the same coin+pair upserts the SAME row (no twin).
    wp._persist_cascade_pair(c, 'ZECUSDT', 'W_D', _ns0(), 't2', {}, _ST)
    rows = c.execute("SELECT symbol, updated_at FROM cascade_state").fetchall()
    assert len(rows) == 1 and rows[0]['symbol'] == 'ZECUSDT'
    c.close()


# ── boot merge of existing twins ──────────────────────────────────────────────

def test_boot_merge_keeps_freshest_and_renames_to_canonical(monkeypatch):
    _stub_resolve(monkeypatch)
    c = _conn()
    _row(c, '2026-07-01T00:00:00Z', 'ZEC-USDT', 'W_D', stage=1)   # older twin
    _row(c, '2026-07-10T00:00:00Z', 'ZECUSDT', 'W_D', stage=2)    # fresher twin
    c.execute("INSERT INTO cascade_transitions (symbol, pair, from_stage, to_stage, reason) "
              "VALUES ('ZEC-USDT','W_D',0,1,'rooted')")
    c.commit()

    n = wp._merge_cascade_symbol_twins(c)
    c.commit()
    assert n == 1
    rows = c.execute("SELECT symbol, stage FROM cascade_state").fetchall()
    assert len(rows) == 1
    assert rows[0]['symbol'] == 'ZECUSDT' and rows[0]['stage'] == 2   # freshest kept
    # transitions untouched (history stays under its original symbol)
    assert c.execute("SELECT COUNT(*) FROM cascade_transitions WHERE symbol='ZEC-USDT'").fetchone()[0] == 1
    c.close()


def test_boot_merge_renames_lone_dashed_row(monkeypatch):
    _stub_resolve(monkeypatch)
    c = _conn()
    _row(c, '2026-07-01T00:00:00Z', 'ZEC-USDT', 'W_D', stage=1)
    c.commit()
    assert wp._merge_cascade_symbol_twins(c) == 0                  # nothing deleted
    assert c.execute("SELECT symbol FROM cascade_state").fetchone()['symbol'] == 'ZECUSDT'  # renamed
    c.close()


def test_boot_merge_noop_when_clean(monkeypatch):
    _stub_resolve(monkeypatch)
    c = _conn()
    _row(c, '2026-07-01T00:00:00Z', 'ZECUSDT', 'W_D', stage=2)
    _row(c, '2026-07-01T00:00:00Z', 'BTCUSDT', 'W_H4', stage=1)
    c.commit()
    assert wp._merge_cascade_symbol_twins(c) == 0
    assert {r['symbol'] for r in c.execute("SELECT symbol FROM cascade_state")} == {'ZECUSDT', 'BTCUSDT'}
    c.close()


def test_boot_merge_across_pairs_independent(monkeypatch):
    # Twins are grouped by (coin, pair): same coin on two pairs are NOT merged.
    _stub_resolve(monkeypatch)
    c = _conn()
    _row(c, '2026-07-01T00:00:00Z', 'ZEC-USDT', 'W_D', stage=1)
    _row(c, '2026-07-02T00:00:00Z', 'ZECUSDT', 'W_D', stage=2)   # twin of the above
    _row(c, '2026-07-03T00:00:00Z', 'ZEC-USDT', 'W_H4', stage=1)  # different pair — kept
    c.commit()
    assert wp._merge_cascade_symbol_twins(c) == 1
    got = {(r['symbol'], r['pair']) for r in c.execute("SELECT symbol, pair FROM cascade_state")}
    assert got == {('ZECUSDT', 'W_D'), ('ZECUSDT', 'W_H4')}
    c.close()


# ── drill read canonicalizes the query symbol ─────────────────────────────────

def test_diagnose_drill_with_dashed_finds_canonical_row(tmp_path, monkeypatch):
    _stub_resolve(monkeypatch)
    # No network: stub the snapshot fetch so compose yields plain Stage-0 states.
    monkeypatch.setattr(wp, '_cascade_snaps_for_coin', lambda coin, *a, **k: ({}, {}))

    path = str(tmp_path / 'drill.db')
    seed = sqlite3.connect(path)
    seed.row_factory = sqlite3.Row
    seed.executescript(_conn_ddl())
    seed.execute("INSERT INTO cascade_state (symbol, pair, stage, updated_at) "
                 "VALUES ('ZECUSDT','W_D',2,'2026-07-10T00:00:00Z')")
    seed.commit()
    seed.close()

    def _open():
        cc = sqlite3.connect(path)
        cc.row_factory = sqlite3.Row
        return cc
    monkeypatch.setattr(_pdb, 'get_connection', _open)

    with wp.app.test_request_context('/api/trading/scanner/cascade-diagnose?symbol=ZEC-USDT'):
        resp = wp.api_trading_scanner_cascade_diagnose.__wrapped__()
    payload = resp.get_json()
    # Drilling the dashed form resolved to the canonical row's stored state.
    assert payload['pairs']['W_D']['storedState'] is not None
    assert payload['pairs']['W_D']['storedState']['stage'] == 2


def _conn_ddl():
    return """
        CREATE TABLE cascade_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, pair TEXT,
            stage INTEGER DEFAULT 0, root_poi_id TEXT, root_zone_top REAL,
            root_zone_bottom REAL, root_poi_type TEXT, nested_poi_id TEXT,
            nested_zone_top REAL, nested_zone_bottom REAL, nested_poi_type TEXT,
            first_tap_at TEXT, last_tap_at TEXT, root_bias TEXT, mss_detail TEXT,
            updated_at TEXT, UNIQUE(symbol, pair));
        CREATE TABLE cascade_transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, pair TEXT,
            from_stage INTEGER, to_stage INTEGER, reason TEXT, root_poi_id TEXT,
            nested_poi_id TEXT, detail TEXT, created_at TEXT);
    """
