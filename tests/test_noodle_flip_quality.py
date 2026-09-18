"""Flip quality Path A (HANDOFF_flip_quality.md) - compute_noodle_state's
flip_count_window (every strict crossover/crossunder found across the
full bar-walk, not just the most recent one), the flip_count_window
migration's idempotence, the scan body persisting it for all five
timeframes, and the noodle-state route emitting it per timeframe.

Fixture conventions (this suite has no cross-file fixture imports - every
noodle_* test file is self-contained, see test_noodle_band_proximity.py /
test_noodle_auto_refresh.py precedent):
  - Pure-function tests call compute_noodle_state directly, hand-verified
    against an independent reference walk written in this file's own
    comments (same discipline as test_noodle_bands.py) - never asserted
    by calling compute_noodle_state a second time to check itself.
  - Migration idempotence reuses the init_db()-on-a-temp-file convention
    from test_noodle_band_proximity.py / test_noodle_scan_runs.py.
  - Scan-body/route tests reuse test_noodle_auto_refresh.py's shared-cache
    in-memory SQLite + hand-rolled schema + monkeypatched get_connection +
    client fixture convention verbatim.
"""
import sqlite3
import threading
import uuid

import src.storage.portfolio_db as portfolio_db
from src.engines.noodle_bands import compute_noodle_state

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import pytest

HOUR = 3600
T0 = 1_700_000_000


def _c(i, p):
    """Flat candle (open=high=low=close=p) - fine for any test that never
    touches ATR (use_atr=False), same helper shape as test_noodle_bands.py."""
    return {'open': p, 'high': p, 'low': p, 'close': p, 'volume': 1.0,
            'time': T0 + i * HOUR}


# ── pure-function: flip_count_window, hand-verified walk ─────────────────
# fast=2, medium=3, slow=3, band_multiplier=0.1, use_atr=False - same small
# params as test_noodle_bands.py's flip tests, so offset = ema_s * 0.1 and
# ema_s (period 3, alpha=0.5) is hand-computable bar by bar.

def test_flip_count_window_counts_every_cross_not_just_the_last():
    # closes: three flat seed bars, then bull/bear/bull spikes each
    # separated by one flat recovery bar. Independent hand walk (alpha=0.5,
    # offset=ema_s*0.1):
    #   i2 seed ema_s=100 (mean of 100,100,100)
    #   i3 close=100 -> ema_s=100                          no cross (both 100)
    #   i4 close=130 -> ema_s=115, upper=126.5              100<=110 & 130>126.5 -> BULL #1
    #   i5 close=100 -> ema_s=107.5                         130<=upper[4]=126.5? no -> no cross either side
    #   i6 close=100 -> ema_s=103.75                        100 inside band -> no cross
    #   i7 close=70  -> ema_s=86.875, lower=78.1875          100>=lower[6]=93.375 & 70<78.1875 -> BEAR #2
    #   i8 close=100 -> ema_s=93.4375                       70<=upper[7]? 70<=95.5625 yes, but cur=100 not > upper[8]=102.78 -> no cross
    #   i9 close=100 -> ema_s=96.71875                      no cross (inside band)
    #   i10 close=130 -> ema_s=113.359375, upper=124.695...  100<=upper[9]=106.39 & 130>124.70 -> BULL #3
    closes = [100, 100, 100, 100, 130, 100, 100, 70, 100, 100, 130]
    candles = [_c(i, p) for i, p in enumerate(closes)]
    result = compute_noodle_state(candles, fast=2, medium=3, slow=3,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['flip_count_window'] == 3
    # The LAST flip (bar 10, bullish) still wins for state/flip_ts/flip_price
    # - flip_count_window is additive, it doesn't change hysteresis semantics.
    assert result['state'] == 'BULLISH'
    assert result['flip_ts'] == candles[10]['time']
    assert result['flip_price'] == 130


def test_flip_count_window_zero_when_no_cross_found():
    # Never leaves the band: ema_s tracks toward ~102-103, offset ~10%,
    # closes of 105/102 stay inside [lower, upper] at every bar - hand
    # walk confirms zero crosses (see inline HANDOFF derivation above for
    # the same offset formula).
    closes = [100, 100, 100, 105, 102]
    candles = [_c(i, p) for i, p in enumerate(closes)]
    result = compute_noodle_state(candles, fast=2, medium=3, slow=3,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['flip_count_window'] == 0
    assert result['state'] == 'WARMUP'


def test_flip_count_window_none_when_history_too_short():
    candles = [_c(0, 100), _c(1, 101)]   # only 2 bars; slow=3 needs 3
    result = compute_noodle_state(candles, fast=2, medium=3, slow=3,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['state'] == 'WARMUP'
    assert result['flip_count_window'] is None


# ── migration idempotence, reusing the init_db()-on-a-temp-file ──────────
# ── convention from test_noodle_band_proximity.py ────────────────────────

def test_flip_count_window_column_exists_after_init_db(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(portfolio_db, 'get_db_path', lambda: path)

    portfolio_db.init_db()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cols = [row['name'] for row in conn.execute("PRAGMA table_info(noodle_state)")]
    assert cols.count('flip_count_window') == 1
    conn.close()


def test_init_db_twice_is_a_noop_for_flip_count_window(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(portfolio_db, 'get_db_path', lambda: path)

    portfolio_db.init_db()
    portfolio_db.init_db()  # must not raise (ADD COLUMN on an already-migrated table)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cols = [row['name'] for row in conn.execute("PRAGMA table_info(noodle_state)")]
    assert cols.count('flip_count_window') == 1
    conn.close()


# ── scan body + route, reusing test_noodle_auto_refresh.py's shared-cache/ ─
# ── hand-rolled-schema/client fixture convention ──────────────────────────

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
    uri = f"file:noodle_flip_quality_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
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
    """n candles with a distinct, index-varying close - same helper shape
    as test_noodle_band_proximity.py's _varying_candles, so each timeframe
    series produces its own real (not coincidentally matching) flip count."""
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


def test_run_noodle_scan_body_persists_flip_count_window_for_all_five_timeframes(
        noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('BTC'))
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)

    dailies = _varying_candles(n=30, base=1000.0, step=86400)
    h12 = _varying_candles(n=30, base=2000.0, step=43200)
    h1 = _varying_candles(n=30, base=3000.0, step=3600)

    def fake_fetch_candles(coin, interval, limit=200):
        return {'1d': dailies, '12h': h12, '1h': h1}[interval]

    monkeypatch.setattr(wp, '_hl_fetch_candles', fake_fetch_candles)
    # compute_noodle_state runs for REAL here (not mocked) - this test only
    # needs to prove the scan body threads its real flip_count_window
    # through the INSERT for every timeframe; the counting logic itself is
    # proven separately by the hand-verified pure-function tests above.

    weekly = wp._weekly_from_dailies(dailies, limit=wp.NOODLE_CANDLE_LIMITS['1w'])
    h4 = wp._h4_from_h1(h1, limit=wp.NOODLE_CANDLE_LIMITS['1h'] // 4)
    series_by_tf = {'1w': weekly, '1d': dailies, '12h': h12, '4h': h4, '1h': h1}
    expected = {
        tf: compute_noodle_state(candles[:-1])['flip_count_window']
        for tf, candles in series_by_tf.items()
    }

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['scanned'] == 1

    rows = {r['timeframe']: r['flip_count_window'] for r in
            noodle_db.execute(
                "SELECT timeframe, flip_count_window FROM noodle_state WHERE symbol='BTC'").fetchall()}
    assert set(rows.keys()) == {'1w', '1d', '12h', '4h', '1h'}
    for tf, exp in expected.items():
        assert rows[tf] == exp, f"{tf}: flip_count_window mismatch"


def test_noodle_state_route_emits_flip_count_window_per_timeframe(client, noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_maybe_kick_noodle_auto_refresh', lambda: False)

    noodle_db.execute(
        """INSERT INTO noodle_state
             (symbol, timeframe, state, upper_band, lower_band, last_close,
              flip_count_window, price, computed_at)
           VALUES ('CHOP', '1d', 'BULLISH', 110.0, 90.0, 100.0,
                   7, 105.0, '2026-01-01T00:00:00+00:00')""")
    noodle_db.execute(
        """INSERT INTO noodle_state
             (symbol, timeframe, state, upper_band, lower_band, last_close,
              flip_count_window, price, computed_at)
           VALUES ('CLEAN', '1d', 'BULLISH', 110.0, 90.0, 100.0,
                   0, 105.0, '2026-01-01T00:00:00+00:00')""")
    # flip_count_window left NULL (column omitted) - undefined/too-short
    # history case, must survive as None through the route, same as every
    # other nullable field.
    noodle_db.execute(
        """INSERT INTO noodle_state
             (symbol, timeframe, state, upper_band, lower_band, last_close,
              price, computed_at)
           VALUES ('WARM', '1d', 'WARMUP', 110.0, 90.0, 100.0,
                   105.0, '2026-01-01T00:00:00+00:00')""")
    noodle_db.commit()

    resp = client.get('/api/trading/scanner/noodle-state')
    assert resp.status_code == 200
    payload = resp.get_json()
    entries = {s['symbol']: s['timeframes']['1d'] for s in payload['symbols']
               if s['symbol'] in ('CHOP', 'CLEAN', 'WARM')}

    assert entries['CHOP']['flip_count_window'] == 7
    assert entries['CLEAN']['flip_count_window'] == 0
    assert entries['WARM']['flip_count_window'] is None
    # Every pre-existing key (including the band-proximity addition) is
    # still present alongside the new one.
    for key in ('state', 'flip_ts', 'flip_price', 'flip_age_unbounded',
                'alignment_bull', 'alignment_bear', 'basis_ema', 'upper_band',
                'lower_band', 'last_close', 'dist_to_flip_pct', 'price',
                'computed_at', 'flip_count_window'):
        assert key in entries['CHOP'], f"missing pre-existing or new key: {key}"
