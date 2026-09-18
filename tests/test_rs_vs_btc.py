"""RS vs BTC (HANDOFF_rs_vs_btc.md) - _rs_vs_btc_pct's math and None cases
(pure function, no DB), the rs_vs_btc_pct migration's idempotence, the
scan body's BTC pre-fetch + per-symbol wiring (including BTC's own rows
always getting None - ruling 4), and the noodle-state route emitting
rs_vs_btc_pct per timeframe.

Fixture conventions, mirroring tests/test_noodle_band_proximity.py (the
doc's own cited closest precedent) - this suite has no cross-file fixture
imports, every noodle_* test file is self-contained:
  - Pure-function tests call the helper directly, no fixture at all.
  - Migration idempotence reuses the init_db()-on-a-temp-file convention.
  - Scan-body/route tests reuse the shared-cache in-memory SQLite + hand-
    rolled schema + monkeypatched get_connection + client fixture
    convention verbatim.
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


# ── pure function: _rs_vs_btc_pct ─────────────────────────────────────────

def _btc_candles(pairs):
    """[(time, close), ...] -> the candle-dict shape _rs_vs_btc_pct reads
    (only 'time'/'close' matter to it)."""
    return [{'time': t, 'close': c} for t, c in pairs]


def test_rs_vs_btc_pct_basic_spread():
    # Token: flip_price=42.0, last_close=48.0 -> +14.285714...%
    # BTC: price at flip_ts=300 is 50300 (exact match), last close=50800
    #      -> +0.994046...%
    # rs = token_pct - btc_pct
    btc = _btc_candles([(0, 50000.0), (100, 50100.0), (200, 50200.0),
                        (300, 50300.0), (400, 50400.0)])
    result = wp._rs_vs_btc_pct(flip_ts=300, flip_price=42.0,
                                flip_age_unbounded=False, last_close=48.0,
                                btc_closed_candles=btc)
    token_pct = (48.0 - 42.0) / 42.0 * 100.0
    btc_pct = (50400.0 - 50300.0) / 50300.0 * 100.0
    assert result == pytest.approx(token_pct - btc_pct)


def test_rs_vs_btc_pct_uses_first_btc_candle_at_or_after_flip_ts():
    # flip_ts=250 falls BETWEEN two BTC candles (200 and 300) - the first
    # one at-or-after (300, price 50300) is used, not 200's.
    btc = _btc_candles([(0, 50000.0), (200, 50200.0), (300, 50300.0), (400, 50400.0)])
    result = wp._rs_vs_btc_pct(flip_ts=250, flip_price=10.0,
                                flip_age_unbounded=False, last_close=11.0,
                                btc_closed_candles=btc)
    token_pct = (11.0 - 10.0) / 10.0 * 100.0
    btc_pct = (50400.0 - 50300.0) / 50300.0 * 100.0
    assert result == pytest.approx(token_pct - btc_pct)


def test_rs_vs_btc_pct_none_when_flip_age_unbounded():
    btc = _btc_candles([(0, 50000.0), (100, 50100.0)])
    assert wp._rs_vs_btc_pct(100, 10.0, True, 11.0, btc) is None


def test_rs_vs_btc_pct_none_when_flip_ts_predates_btc_window():
    # Earliest BTC candle is at t=200; flip_ts=100 predates it - refused,
    # not approximated against the earliest available bar (ruling 4).
    btc = _btc_candles([(200, 50200.0), (300, 50300.0)])
    assert wp._rs_vs_btc_pct(100, 10.0, False, 11.0, btc) is None


def test_rs_vs_btc_pct_none_when_no_btc_candle_at_or_after_flip_ts():
    # flip_ts=500 is later than every BTC candle in this series - no
    # candle satisfies "first one at-or-after", so no reference point.
    btc = _btc_candles([(0, 50000.0), (100, 50100.0)])
    assert wp._rs_vs_btc_pct(500, 10.0, False, 11.0, btc) is None


def test_rs_vs_btc_pct_none_when_btc_candles_empty():
    assert wp._rs_vs_btc_pct(100, 10.0, False, 11.0, []) is None
    assert wp._rs_vs_btc_pct(100, 10.0, False, 11.0, None) is None


def test_rs_vs_btc_pct_none_on_missing_token_inputs():
    btc = _btc_candles([(0, 50000.0), (100, 50100.0)])
    assert wp._rs_vs_btc_pct(None, 10.0, False, 11.0, btc) is None
    assert wp._rs_vs_btc_pct(100, None, False, 11.0, btc) is None
    assert wp._rs_vs_btc_pct(100, 0.0, False, 11.0, btc) is None
    assert wp._rs_vs_btc_pct(100, 10.0, False, None, btc) is None


# ── migration idempotence, reusing the init_db()-on-a-temp-file ──────────
# ── convention ─────────────────────────────────────────────────────────

def test_rs_vs_btc_pct_column_exists_after_init_db(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(portfolio_db, 'get_db_path', lambda: path)

    portfolio_db.init_db()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cols = [row['name'] for row in conn.execute("PRAGMA table_info(noodle_state)")]
    assert cols.count('rs_vs_btc_pct') == 1
    conn.close()


def test_init_db_twice_is_a_noop_for_rs_vs_btc_pct(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(portfolio_db, 'get_db_path', lambda: path)

    portfolio_db.init_db()
    portfolio_db.init_db()  # must not raise (ADD COLUMN on an already-migrated table)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cols = [row['name'] for row in conn.execute("PRAGMA table_info(noodle_state)")]
    assert cols.count('rs_vs_btc_pct') == 1
    conn.close()


# ── scan body + route, reusing the shared-cache/hand-rolled-schema/ ──────
# ── client fixture convention ─────────────────────────────────────────────

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
        UNIQUE(symbol, timeframe)
    )
"""

NOODLE_SCAN_RUNS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS noodle_scan_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trigger TEXT NOT NULL,
        status TEXT NOT NULL,
        started_ts REAL NOT NULL,
        updated_ts REAL NOT NULL,
        finished_ts REAL,
        total INTEGER,
        done INTEGER NOT NULL DEFAULT 0,
        errors INTEGER NOT NULL DEFAULT 0,
        retired INTEGER,
        error_msg TEXT
    )
"""


@pytest.fixture
def noodle_db(monkeypatch):
    uri = f"file:rs_vs_btc_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    keepalive.row_factory = sqlite3.Row
    keepalive.executescript(NOODLE_STATE_SCHEMA)
    keepalive.executescript(NOODLE_SCAN_RUNS_SCHEMA)
    keepalive.commit()

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    yield keepalive
    keepalive.close()


def _default_scanner_settings_path(monkeypatch, tmp_path):
    monkeypatch.setattr(wp, "_SCANNER_SETTINGS_PATH", str(tmp_path / "scanner_settings.json"))


def _fake_universe(*symbols, asset_type='crypto'):
    return [
        {'name': s, 'symbol': f'{s}-USDT', 'volume_24h': 1000.0 - i,
         'price': 100.0 + i, 'asset_type': asset_type}
        for i, s in enumerate(symbols)
    ]


def _varying_candles(n, base, step, t0=1_700_000_000):
    return [
        {'open': base + i, 'high': base + i + 1.0, 'low': base + i - 1.0,
         'close': base + i, 'volume': 10.0 + i, 'time': t0 + i * step}
        for i in range(n)
    ]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


FAKE_RESULT = {
    'state': 'BULLISH', 'flip_ts': 1_700_000_000 + 1800, 'flip_price': 42.0,
    'flip_age_unbounded': False, 'flip_count_window': 1,
    'alignment_bull': 3, 'alignment_bear': 0,
    'basis_ema': 45.0, 'upper_band': 50.0, 'lower_band': 40.0,
    'alignment_state': 'BULLISH', 'alignment_prev_state': None,
    'alignment_changed_ts': 1_700_000_000, 'alignment_changed_unbounded': True,
}


def test_run_noodle_scan_body_computes_and_persists_rs_vs_btc_pct(
        noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('BTC', 'ETH'))
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    monkeypatch.setattr(wp, 'compute_noodle_state', lambda candles, **kw: dict(FAKE_RESULT))

    eth_dailies = _varying_candles(n=10, base=40.0, step=86400)
    eth_h12 = _varying_candles(n=10, base=140.0, step=43200)
    eth_h1 = _varying_candles(n=10, base=340.0, step=3600)
    btc_dailies = _varying_candles(n=10, base=50000.0, step=86400)
    btc_h12 = _varying_candles(n=10, base=51000.0, step=43200)
    btc_h1 = _varying_candles(n=10, base=52000.0, step=3600)

    def fake_fetch_candles(coin, interval, limit=200):
        series = {'BTC': {'1d': btc_dailies, '12h': btc_h12, '1h': btc_h1},
                  'ETH': {'1d': eth_dailies, '12h': eth_h12, '1h': eth_h1}}[coin]
        return series[interval]

    monkeypatch.setattr(wp, '_hl_fetch_candles', fake_fetch_candles)

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['scanned'] == 2

    # ETH's 1d row: last_close = eth_dailies[:-1][-1]['close'] = 40+8 = 48.0
    # (real, derived from candles - compute_noodle_state is mocked but
    # last_close never depends on it). flip_ts/flip_price come from
    # FAKE_RESULT (42.0). BTC's 1d closed series (btc_dailies[:-1]) has its
    # first candle at-or-after flip_ts=1_700_000_000+1800 at index 1
    # (time = t0+86400 >= t0+1800), close = 50000+1=50001.0; last closed
    # candle is index 8, close = 50000+8=50008.0.
    eth_row = noodle_db.execute(
        "SELECT rs_vs_btc_pct FROM noodle_state WHERE symbol='ETH' AND timeframe='1d'").fetchone()
    token_pct = (48.0 - 42.0) / 42.0 * 100.0
    btc_pct = (50008.0 - 50001.0) / 50001.0 * 100.0
    assert eth_row['rs_vs_btc_pct'] == pytest.approx(token_pct - btc_pct)

    # BTC's own rows never get a self-comparison (ruling 4) - None on
    # every timeframe, not just 1d.
    btc_rows = noodle_db.execute(
        "SELECT timeframe, rs_vs_btc_pct FROM noodle_state WHERE symbol='BTC'").fetchall()
    assert set(r['timeframe'] for r in btc_rows) == {'1w', '1d', '12h', '4h', '1h'}
    for r in btc_rows:
        assert r['rs_vs_btc_pct'] is None, f"BTC's own {r['timeframe']} row must be None"


def test_run_noodle_scan_body_rs_vs_btc_pct_null_when_flip_age_unbounded(
        noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('ETH'))
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    unbounded_result = dict(FAKE_RESULT)
    unbounded_result['flip_age_unbounded'] = True
    monkeypatch.setattr(wp, 'compute_noodle_state', lambda candles, **kw: dict(unbounded_result))

    eth_dailies = _varying_candles(n=10, base=40.0, step=86400)

    def fake_fetch_candles(coin, interval, limit=200):
        return eth_dailies

    monkeypatch.setattr(wp, '_hl_fetch_candles', fake_fetch_candles)

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['scanned'] == 1

    row = noodle_db.execute(
        "SELECT rs_vs_btc_pct FROM noodle_state WHERE symbol='ETH' AND timeframe='1d'").fetchone()
    assert row['rs_vs_btc_pct'] is None


def test_run_noodle_scan_body_degrades_gracefully_when_btc_prefetch_fails(
        noodle_db, tmp_path, monkeypatch):
    # BTC absent from perp_universe entirely (ruling 5: the pre-fetch does
    # not depend on BTC's presence in the loop) and its resolve raises -
    # the scan must still complete for every other symbol, with
    # rs_vs_btc_pct simply None rather than the pass erroring out.
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('ETH'))

    def fake_resolve_coin(symbol):
        if symbol == 'BTC':
            raise RuntimeError("HL lookup failed")
        return symbol

    monkeypatch.setattr(wp, '_hl_resolve_coin', fake_resolve_coin)
    monkeypatch.setattr(wp, 'compute_noodle_state', lambda candles, **kw: dict(FAKE_RESULT))

    eth_dailies = _varying_candles(n=10, base=40.0, step=86400)
    monkeypatch.setattr(wp, '_hl_fetch_candles', lambda coin, interval, limit=200: eth_dailies)

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['scanned'] == 1
    assert payload['errors'] == 0

    row = noodle_db.execute(
        "SELECT rs_vs_btc_pct FROM noodle_state WHERE symbol='ETH' AND timeframe='1d'").fetchone()
    assert row['rs_vs_btc_pct'] is None


def test_noodle_state_route_emits_rs_vs_btc_pct_per_timeframe(client, noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_maybe_kick_noodle_auto_refresh', lambda: False)

    noodle_db.execute(
        """INSERT INTO noodle_state
             (symbol, timeframe, state, last_close, price, computed_at, rs_vs_btc_pct)
           VALUES ('ETH', '1d', 'BULLISH', 48.0, 45.0, '2026-01-01T00:00:00+00:00', 13.29)""")
    noodle_db.execute(
        """INSERT INTO noodle_state
             (symbol, timeframe, state, last_close, price, computed_at)
           VALUES ('BTC', '1d', 'BULLISH', 50008.0, 50000.0, '2026-01-01T00:00:00+00:00')""")
    noodle_db.commit()

    resp = client.get('/api/trading/scanner/noodle-state')
    assert resp.status_code == 200
    payload = resp.get_json()
    entries = {s['symbol']: s['timeframes']['1d'] for s in payload['symbols']
               if s['symbol'] in ('ETH', 'BTC')}

    assert entries['ETH']['rs_vs_btc_pct'] == pytest.approx(13.29)
    assert entries['BTC']['rs_vs_btc_pct'] is None
    # Every pre-existing key is still present alongside the new one.
    for key in ('state', 'flip_ts', 'flip_price', 'flip_age_unbounded',
                'flip_count_window', 'last_close', 'dist_to_flip_pct',
                'price', 'computed_at', 'rs_vs_btc_pct'):
        assert key in entries['ETH'], f"missing pre-existing or new key: {key}"
