"""Landing 47 (Oct 16): Doc's Daily and Weekly Trend EMAs on noodle_state.

Glenn's rulings (SPEC_doc_system.md Part F): Doc's Daily Trend is EMA 100
and EMA 200 of 4H closes, his Weekly Trend EMA 100 and EMA 200 of daily
closes, and setup 1's "Daily cross" is the Daily Trend fast EMA crossing
the slow one. src/engines/doc_trend.compute_ema_cross gives the two EMAs
and the latest cross; the scan fetches 2800 1h bars and 700 dailies so EMA
200's seed fades (DOC_TREND_CANDLE_LIMITS) while the noodle keeps exactly
its old inputs; the 4h and 1d rows store the result in five doc_* columns;
the noodle-state route returns them. Fixture conventions copy
test_noodle_band_proximity.py (no cross-file fixture imports): real
init_db on a temp file for the migration, a shared-cache in-memory SQLite
with a hand-rolled schema for the scan and the route.
"""
import sqlite3
import threading
import uuid

import src.engines.doc_trend as doc_trend
import src.storage.portfolio_db as portfolio_db
from src.engines.doc_trend import compute_ema_cross

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import pytest

DOC_COLUMNS = ('doc_ema_fast', 'doc_ema_slow', 'doc_cross_state', 'doc_cross_ts',
               'doc_cross_unbounded')
T0 = 1_699_999_200          # a whole hour (and a whole 4h bucket) in unix seconds


def _bars(closes, step, t0=T0):
    return [{'open': c, 'high': c + 1.0, 'low': c - 1.0, 'close': c, 'volume': 10.0,
             'time': t0 + i * step} for i, c in enumerate(closes)]


def _reference_ema(values, period):
    """EMA at the last bar written out as weights, not as a running loop:
    the SMA of the first `period` values, then every later value weighted
    alpha * (1 - alpha) ** age."""
    alpha = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    later = values[period:]
    m = len(later)
    total = seed * (1.0 - alpha) ** m
    for j, v in enumerate(later):
        total += alpha * v * (1.0 - alpha) ** (m - 1 - j)
    return total


def _down_then_up(n_down, n_up, start=100.0, step=0.1):
    down = [start - step * i for i in range(n_down)]
    low = down[-1]
    return down + [low + step * (i + 1) for i in range(n_up)]


# ── the engine ────────────────────────────────────────────────────────────

def test_fewer_bars_than_the_slow_ema_says_nothing():
    out = compute_ema_cross(_bars([100.0 + i for i in range(199)], 3600))
    assert out == {'ema_fast': None, 'ema_slow': None, 'cross_state': None,
                   'cross_ts': None, 'cross_unbounded': None}
    assert compute_ema_cross([])['ema_slow'] is None


def test_fast_must_be_shorter_than_slow():
    bars = _bars([100.0 + i for i in range(50)], 3600)
    assert compute_ema_cross(bars, fast=20, slow=20)['ema_fast'] is None
    assert compute_ema_cross(bars, fast=30, slow=20)['cross_state'] is None


def test_emas_match_the_written_out_formula():
    closes = [100.0 + 7.0 * ((i * 37) % 11) - 0.05 * i for i in range(700)]
    out = compute_ema_cross(_bars(closes, 14400))
    assert out['ema_fast'] == pytest.approx(_reference_ema(closes, 100), rel=1e-9)
    assert out['ema_slow'] == pytest.approx(_reference_ema(closes, 200), rel=1e-9)
    assert doc_trend.DOC_TREND_FAST == 100 and doc_trend.DOC_TREND_SLOW == 200


def test_a_rise_after_a_fall_is_a_bullish_cross_dated_by_its_first_bar():
    bars = _bars(_down_then_up(400, 300), 14400)
    out = compute_ema_cross(bars)
    assert out['cross_state'] == 'BULLISH'
    assert out['cross_unbounded'] is False
    ef = doc_trend.ema([b['close'] for b in bars], 100)
    es = doc_trend.ema([b['close'] for b in bars], 200)
    first_above = next(i for i in range(len(bars) - 1, 198, -1)
                       if not ef[i - 1] > es[i - 1])
    assert ef[first_above] > es[first_above]
    assert out['cross_ts'] == bars[first_above]['time']
    assert all(ef[i] > es[i] for i in range(first_above, len(bars)))


def test_a_fall_after_a_rise_is_bearish():
    closes = [50.0 + 0.1 * i for i in range(400)] + [90.0 - 0.1 * i for i in range(300)]
    out = compute_ema_cross(_bars(closes, 86400))
    assert out['cross_state'] == 'BEARISH'
    assert out['cross_unbounded'] is False
    assert isinstance(out['cross_ts'], int)


def test_one_side_since_the_first_bar_is_unbounded():
    out = compute_ema_cross(_bars([100.0 + 0.1 * i for i in range(400)], 14400))
    assert out['cross_state'] == 'BULLISH'
    assert out['cross_ts'] is None
    assert out['cross_unbounded'] is True


def test_a_flat_series_has_emas_but_no_side():
    out = compute_ema_cross(_bars([5.0] * 300, 14400))
    assert out['ema_fast'] == pytest.approx(5.0)
    assert out['ema_slow'] == pytest.approx(5.0)
    assert out['cross_state'] is None
    assert out['cross_ts'] is None and out['cross_unbounded'] is None


def test_an_exactly_equal_bar_keeps_the_side_before_it(monkeypatch):
    # Hand-set EMAs (fast 2, slow 3): apart from bar 2, equal at bars 4 and
    # 6, a real cross only at bar 7.
    fast = [None, 1.0, 9.0, 9.0, 5.0, 9.0, 5.0, 1.0]
    slow = [None, None, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0]
    monkeypatch.setattr(doc_trend, 'ema', lambda values, period: {2: fast, 3: slow}[period])
    bars = _bars([1.0] * 8, 3600)
    out = compute_ema_cross(bars, fast=2, slow=3)
    assert out['cross_state'] == 'BEARISH'
    assert out['cross_ts'] == bars[7]['time']
    fast[7] = 5.0                       # equal on the last bar: still bullish, never crossed
    out = compute_ema_cross(bars, fast=2, slow=3)
    assert out['cross_state'] == 'BULLISH'
    assert out['cross_unbounded'] is True


# ── the migration ─────────────────────────────────────────────────────────

def _cols(path):
    conn = sqlite3.connect(path)
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(noodle_state)")}
    finally:
        conn.close()


def test_init_db_adds_the_five_columns_and_twice_is_a_noop(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(portfolio_db, 'get_db_path', lambda: path)
    portfolio_db.init_db()
    portfolio_db.init_db()
    assert set(DOC_COLUMNS) <= _cols(path)


def test_upgrade_keeps_existing_rows_and_leaves_the_new_columns_null(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(portfolio_db, 'get_db_path', lambda: path)
    portfolio_db.init_db()
    conn = sqlite3.connect(path)
    for col in DOC_COLUMNS:                      # back to the pre-Landing 47 table
        conn.execute(f"ALTER TABLE noodle_state DROP COLUMN {col}")
    conn.execute("INSERT INTO noodle_state (symbol, timeframe, state, upper_band, computed_at) "
                 "VALUES ('ETH', '4h', 'BULLISH', 110.0, '2026-10-16T00:00:00+00:00')")
    conn.commit()
    conn.close()
    assert not set(DOC_COLUMNS) & _cols(path)

    portfolio_db.init_db()

    assert set(DOC_COLUMNS) <= _cols(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM noodle_state WHERE symbol='ETH'").fetchone()
    conn.close()
    assert row['state'] == 'BULLISH' and row['upper_band'] == 110.0
    assert all(row[c] is None for c in DOC_COLUMNS)


# ── the scan and the route ───────────────────────────────────────────────

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
        respect_dir TEXT,
        respect_tags INTEGER,
        respect_last_ts REAL,
        respect_unbounded INTEGER,
        respect_breaks INTEGER,
        respect_since REAL,
        respect_losses INTEGER,
        respect_ranging_since REAL,
        poi_type TEXT,
        poi_top REAL,
        poi_bottom REAL,
        poi_ts REAL,
        poi_at_band INTEGER,
        poi_count INTEGER,
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
    uri = f"file:doc_trend_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    keepalive.row_factory = sqlite3.Row
    keepalive.executescript(NOODLE_STATE_SCHEMA)
    keepalive.executescript(NOODLE_SCAN_RUNS_SCHEMA)
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


def test_depths():
    assert wp.DOC_TREND_CANDLE_LIMITS == {'1h': 2800, '1d': 700}
    assert wp.NOODLE_CANDLE_LIMITS == {'1d': 300, '12h': 300, '1w': 200, '1h': 1440}


def test_scan_fetches_deeper_keeps_the_noodle_inputs_and_stores_doc_trends(
        noodle_db, tmp_path, monkeypatch):
    monkeypatch.setattr(wp, "_SCANNER_SETTINGS_PATH", str(tmp_path / "scanner_settings.json"))
    monkeypatch.setattr(wp, '_hl_fetch_top_volume', lambda n=None, limit=None: [
        {'name': 'ETH', 'symbol': 'ETH-USDT', 'volume_24h': 1000.0, 'price': 100.0,
         'asset_type': 'crypto'}])
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)

    dailies_deep = _bars(_down_then_up(450, 251), 86400)          # 701 bars, as HL returns
    h1_deep = _bars(_down_then_up(1700, 1101, step=0.01), 3600)   # 2801 bars
    h12 = _bars([100.0 + 0.01 * i for i in range(301)], 43200)
    asked = []

    def fake_fetch_candles(coin, interval, limit=200):
        asked.append((coin, interval, limit))
        return {'1d': dailies_deep, '12h': h12, '1h': h1_deep}[interval]

    monkeypatch.setattr(wp, '_hl_fetch_candles', fake_fetch_candles)
    seen = {}
    real_noodle = wp.compute_noodle_state

    def spy(candles, **kw):
        seen.setdefault(len(seen), candles)
        return real_noodle(candles, **kw)

    monkeypatch.setattr(wp, 'compute_noodle_state', spy)

    payload, status = wp._run_noodle_scan_body()
    assert status == 200 and payload['scanned'] == 1 and payload['errors'] == 0

    eth = sorted((i, lim) for c, i, lim in asked if c == 'ETH')
    assert eth == [('12h', 300), ('1d', 700), ('1h', 2800)]

    # The noodle saw exactly what the old 300-day / 1440-hour requests gave it,
    # except the weekly, which reads every daily since Landing 65.
    old_dailies = dailies_deep[-301:]
    old_h1 = h1_deep[-1440:]
    order = ['1w', '1d', '12h', '4h', '1h']
    expected_inputs = {
        '1w': wp._weekly_from_dailies(dailies_deep, limit=200)[:-1],
        '1d': old_dailies[:-1],
        '12h': h12[:-1],
        '4h': wp._h4_from_h1(old_h1, limit=360)[:-1],
        '1h': old_h1[:-1],
    }
    calls = [seen[k] for k in sorted(seen)]
    assert len(calls) == 5
    for tf, got in zip(order, calls):
        assert got == expected_inputs[tf], tf

    rows = {r['timeframe']: dict(r) for r in noodle_db.execute(
        "SELECT * FROM noodle_state WHERE symbol='ETH'").fetchall()}
    daily_trend = compute_ema_cross(wp._h4_from_h1(h1_deep, limit=700)[:-1])
    weekly_trend = compute_ema_cross(dailies_deep[:-1])
    for tf, exp in (('4h', daily_trend), ('1d', weekly_trend)):
        r = rows[tf]
        assert exp['ema_slow'] is not None and exp['cross_state'] == 'BULLISH'
        assert r['doc_ema_fast'] == pytest.approx(exp['ema_fast'])
        assert r['doc_ema_slow'] == pytest.approx(exp['ema_slow'])
        assert r['doc_cross_state'] == exp['cross_state']
        assert r['doc_cross_ts'] == exp['cross_ts']
        assert r['doc_cross_unbounded'] == 0
    for tf in ('1w', '12h', '1h'):
        assert all(rows[tf][c] is None for c in DOC_COLUMNS), tf


def test_young_coin_too_short_for_ema_200_stores_nulls(noodle_db, tmp_path, monkeypatch):
    monkeypatch.setattr(wp, "_SCANNER_SETTINGS_PATH", str(tmp_path / "scanner_settings.json"))
    monkeypatch.setattr(wp, '_hl_fetch_top_volume', lambda n=None, limit=None: [
        {'name': 'NEWC', 'symbol': 'NEWC-USDT', 'volume_24h': 1.0, 'price': 1.0,
         'asset_type': 'crypto'}])
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    short = {'1d': _bars([1.0 + 0.01 * i for i in range(150)], 86400),
             '12h': _bars([1.0 + 0.01 * i for i in range(300)], 43200),
             '1h': _bars([1.0 + 0.001 * i for i in range(700)], 3600)}
    monkeypatch.setattr(wp, '_hl_fetch_candles', lambda coin, interval, limit=200: short[interval])
    payload, status = wp._run_noodle_scan_body()
    assert status == 200 and payload['scanned'] == 1 and payload['errors'] == 0
    rows = noodle_db.execute("SELECT * FROM noodle_state WHERE symbol='NEWC'").fetchall()
    assert len(rows) == 5
    assert all(r[c] is None for r in rows for c in DOC_COLUMNS)


def test_route_returns_the_doc_columns(client, noodle_db, monkeypatch):
    monkeypatch.setattr(wp, '_maybe_kick_noodle_auto_refresh', lambda: False)
    monkeypatch.setattr(wp, '_hl_refresh_universes', lambda force=False: None)
    noodle_db.execute(
        "INSERT INTO noodle_state (symbol, timeframe, state, computed_at, doc_ema_fast, doc_ema_slow, "
        "doc_cross_state, doc_cross_ts, doc_cross_unbounded) VALUES "
        "('ETH', '4h', 'BULLISH', '2026-10-16T00:00:00+00:00', 101.5, 99.25, 'BULLISH', 1760000000.0, 0)")
    noodle_db.execute(
        "INSERT INTO noodle_state (symbol, timeframe, state, computed_at, doc_ema_fast, doc_ema_slow, "
        "doc_cross_state, doc_cross_ts, doc_cross_unbounded) VALUES "
        "('ETH', '1d', 'BULLISH', '2026-10-16T00:00:00+00:00', 120.0, 125.0, 'BEARISH', NULL, 1)")
    noodle_db.execute(
        "INSERT INTO noodle_state (symbol, timeframe, state, computed_at) VALUES "
        "('ETH', '1h', 'BULLISH', '2026-10-16T00:00:00+00:00')")
    noodle_db.commit()
    resp = client.get('/api/trading/scanner/noodle-state')
    assert resp.status_code == 200
    tfs = resp.get_json()['symbols'][0]['timeframes']
    assert tfs['4h']['doc_ema_fast'] == 101.5 and tfs['4h']['doc_ema_slow'] == 99.25
    assert tfs['4h']['doc_cross_state'] == 'BULLISH' and tfs['4h']['doc_cross_ts'] == 1760000000.0
    assert tfs['4h']['doc_cross_unbounded'] is False
    assert tfs['1d']['doc_cross_state'] == 'BEARISH' and tfs['1d']['doc_cross_ts'] is None
    assert tfs['1d']['doc_cross_unbounded'] is True
    assert all(tfs['1h'][c] is None for c in DOC_COLUMNS)
