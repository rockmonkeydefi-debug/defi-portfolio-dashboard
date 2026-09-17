"""Band-proximity Commit 1 (HANDOFF_band_proximity.md) - _noodle_dist_to_
flip_pct's sign convention and None cases (pure function, no DB), the
last_close migration's idempotence, the scan body persisting last_close
for all five timeframes, and the noodle-state route emitting
dist_to_flip_pct per timeframe.

Fixture conventions, picked per sub-test to match the existing file each
mirrors (this suite has no cross-file fixture imports - every noodle_*
test file is self-contained, see test_noodle_auto_refresh.py /
test_noodle_scan_runs.py precedent):
  - (a)/(b) call the pure helper directly, no fixture at all.
  - (c) reuses the init_db()-on-a-temp-file convention from
    test_noodle_scan_runs.py / test_noodle_state_schema.py (real init_db,
    monkeypatched get_db_path - proves the migration itself, not the scan
    body).
  - (d)/(e) reuse test_noodle_auto_refresh.py's shared-cache in-memory
    SQLite + hand-rolled schema + monkeypatched get_connection + client
    fixture convention verbatim (the scan body opens/closes its own
    connection internally; a bare ':memory:' would lose state), since
    nothing here imports fixtures from that file.
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


# ── (a)/(b): _noodle_dist_to_flip_pct - pure function, no DB ─────────────

def test_dist_to_flip_pct_bearish_below_upper_is_positive():
    # BEARISH, last_close (100) below the upper edge (110) that would
    # flip it bullish - positive, per ruling 2.
    assert wp._noodle_dist_to_flip_pct('BEARISH', 110.0, 90.0, 100.0) == pytest.approx(10.0)


def test_dist_to_flip_pct_bullish_above_lower_is_negative():
    # BULLISH, last_close (100) above the lower edge (90) that would
    # flip it bearish - negative, per ruling 2.
    assert wp._noodle_dist_to_flip_pct('BULLISH', 110.0, 90.0, 100.0) == pytest.approx(-10.0)


def test_dist_to_flip_pct_bearish_through_band_keeps_negative_sign():
    # BEARISH but last_close (120) already ABOVE the upper edge (110) -
    # price is already through the band; the flip is pending the engine's
    # confirmation. Sign is NOT clamped to positive - stays negative.
    assert wp._noodle_dist_to_flip_pct('BEARISH', 110.0, 90.0, 120.0) == pytest.approx(
        (110.0 - 120.0) / 120.0 * 100.0)
    assert wp._noodle_dist_to_flip_pct('BEARISH', 110.0, 90.0, 120.0) < 0


def test_dist_to_flip_pct_bullish_through_band_keeps_positive_sign():
    # BULLISH but last_close (80) already BELOW the lower edge (90) -
    # through-band on the other side; stays positive, not clamped.
    assert wp._noodle_dist_to_flip_pct('BULLISH', 110.0, 90.0, 80.0) == pytest.approx(
        (90.0 - 80.0) / 80.0 * 100.0)
    assert wp._noodle_dist_to_flip_pct('BULLISH', 110.0, 90.0, 80.0) > 0


def test_dist_to_flip_pct_none_on_warmup_state():
    assert wp._noodle_dist_to_flip_pct('WARMUP', 110.0, 90.0, 100.0) is None


def test_dist_to_flip_pct_none_on_state_none():
    assert wp._noodle_dist_to_flip_pct(None, 110.0, 90.0, 100.0) is None


def test_dist_to_flip_pct_none_on_missing_edge():
    # BEARISH needs upper_band; BULLISH needs lower_band.
    assert wp._noodle_dist_to_flip_pct('BEARISH', None, 90.0, 100.0) is None
    assert wp._noodle_dist_to_flip_pct('BULLISH', 110.0, None, 100.0) is None


def test_dist_to_flip_pct_none_on_last_close_none():
    assert wp._noodle_dist_to_flip_pct('BEARISH', 110.0, 90.0, None) is None


def test_dist_to_flip_pct_none_on_last_close_zero():
    assert wp._noodle_dist_to_flip_pct('BEARISH', 110.0, 90.0, 0.0) is None


# ── (c): migration idempotence, reusing test_noodle_scan_runs.py's ───────
# ── init_db()-on-a-temp-file convention ───────────────────────────────────

def test_last_close_column_exists_after_init_db(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(portfolio_db, 'get_db_path', lambda: path)

    portfolio_db.init_db()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cols = [row['name'] for row in conn.execute("PRAGMA table_info(noodle_state)")]
    assert cols.count('last_close') == 1
    conn.close()


def test_init_db_twice_is_a_noop_for_last_close(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(portfolio_db, 'get_db_path', lambda: path)

    portfolio_db.init_db()
    portfolio_db.init_db()  # must not raise (ADD COLUMN on an already-migrated table)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cols = [row['name'] for row in conn.execute("PRAGMA table_info(noodle_state)")]
    assert cols.count('last_close') == 1
    conn.close()


# ── (d)/(e): scan body + route, reusing test_noodle_auto_refresh.py's ────
# ── shared-cache/hand-rolled-schema/client fixture convention ────────────

NOODLE_STATE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS noodle_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        state TEXT,
        flip_ts REAL,
        flip_price REAL,
        flip_age_unbounded INTEGER,
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
    uri = f"file:noodle_band_proximity_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
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


def _varying_candles(n, base, step):
    """n candles with a distinct, index-varying close - unlike
    test_noodle_auto_refresh.py's _tiny_candles (constant close=100.0 for
    every bar), this makes last_close == candles[-2]['close'] a
    meaningful assertion rather than a coincidental match."""
    return [
        {'open': base + i, 'high': base + i + 1.0, 'low': base + i - 1.0,
         'close': base + i, 'volume': 10.0 + i, 'time': 1_700_000_000 + i * step}
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


def test_run_noodle_scan_body_persists_last_close_for_all_five_timeframes(
        noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('BTC'))
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)

    dailies = _varying_candles(n=10, base=1000.0, step=86400)
    h12 = _varying_candles(n=10, base=2000.0, step=43200)
    h1 = _varying_candles(n=10, base=3000.0, step=3600)

    def fake_fetch_candles(coin, interval, limit=200):
        return {'1d': dailies, '12h': h12, '1h': h1}[interval]

    monkeypatch.setattr(wp, '_hl_fetch_candles', fake_fetch_candles)
    # compute_noodle_state runs for REAL here (not mocked) - it's a pure,
    # cheap function and this test needs last_close to reflect each
    # series' own real closed[-1], which a fixed FAKE_RESULT can't prove.

    # Expected last_close per timeframe: derive the SAME series the scan
    # body itself derives (weekly/h4 are aggregated, not fetched), then
    # take the same closed[-1]['close'] the scan body computes.
    weekly = wp._weekly_from_dailies(dailies, limit=wp.NOODLE_CANDLE_LIMITS['1w'])
    h4 = wp._h4_from_h1(h1, limit=wp.NOODLE_CANDLE_LIMITS['1h'] // 4)
    expected = {
        '1w': weekly[:-1][-1]['close'],
        '1d': dailies[:-1][-1]['close'],
        '12h': h12[:-1][-1]['close'],
        '4h': h4[:-1][-1]['close'],
        '1h': h1[:-1][-1]['close'],
    }

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['scanned'] == 1

    rows = {r['timeframe']: r['last_close'] for r in
            noodle_db.execute("SELECT timeframe, last_close FROM noodle_state WHERE symbol='BTC'").fetchall()}
    assert set(rows.keys()) == {'1w', '1d', '12h', '4h', '1h'}
    for tf, exp in expected.items():
        assert rows[tf] == pytest.approx(exp), f"{tf}: last_close mismatch"


def test_noodle_state_route_emits_dist_to_flip_pct_per_timeframe(client, noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_maybe_kick_noodle_auto_refresh', lambda: False)

    noodle_db.execute(
        """INSERT INTO noodle_state
             (symbol, timeframe, state, upper_band, lower_band, last_close,
              price, computed_at, flip_ts, flip_price, flip_age_unbounded,
              alignment_bull, alignment_bear, basis_ema, volume_24h,
              alignment_state, alignment_prev_state, alignment_changed_ts,
              alignment_changed_unbounded)
           VALUES ('BEARC', '1d', 'BEARISH', 110.0, 90.0, 100.0,
                   105.0, '2026-01-01T00:00:00+00:00', 1700000000.0, 108.0, 0,
                   0, 3, 100.0, 5000.0,
                   'BEARISH', 'NEUTRAL', 1695000000.0, 0)""")
    noodle_db.execute(
        """INSERT INTO noodle_state
             (symbol, timeframe, state, upper_band, lower_band, last_close,
              price, computed_at)
           VALUES ('BULLC', '1d', 'BULLISH', 110.0, 90.0, 100.0,
                   105.0, '2026-01-01T00:00:00+00:00')""")
    noodle_db.execute(
        """INSERT INTO noodle_state
             (symbol, timeframe, state, upper_band, lower_band, last_close,
              price, computed_at)
           VALUES ('WARMC', '1d', 'WARMUP', 110.0, 90.0, 100.0,
                   105.0, '2026-01-01T00:00:00+00:00')""")
    noodle_db.commit()

    resp = client.get('/api/trading/scanner/noodle-state')
    assert resp.status_code == 200
    payload = resp.get_json()
    entries = {s['symbol']: s['timeframes']['1d'] for s in payload['symbols']
               if s['symbol'] in ('BEARC', 'BULLC', 'WARMC')}

    bear_tf = entries['BEARC']
    assert bear_tf['dist_to_flip_pct'] == pytest.approx((110.0 - 100.0) / 100.0 * 100.0)
    assert bear_tf['dist_to_flip_pct'] > 0
    # Every pre-existing key is still present alongside the new ones.
    for key in ('state', 'flip_ts', 'flip_price', 'flip_age_unbounded',
                'alignment_bull', 'alignment_bear', 'basis_ema', 'upper_band',
                'lower_band', 'price', 'computed_at', 'volume_24h',
                'alignment_state', 'alignment_prev_state',
                'alignment_changed_ts', 'alignment_changed_unbounded',
                'last_close', 'dist_to_flip_pct'):
        assert key in bear_tf, f"missing pre-existing or new key: {key}"

    bull_tf = entries['BULLC']
    assert bull_tf['dist_to_flip_pct'] == pytest.approx((90.0 - 100.0) / 100.0 * 100.0)
    assert bull_tf['dist_to_flip_pct'] < 0

    warm_tf = entries['WARMC']
    assert warm_tf['dist_to_flip_pct'] is None
