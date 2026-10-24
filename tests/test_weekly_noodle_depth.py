"""Landing 65 (Oct 24, Glenn "your recs": A, A, A): the weekly noodle reads
about 99 weeks of history instead of about 41.

Since Landing 47 the scan fetches 700 dailies per symbol for Doc's Weekly
Trend; the weekly noodle used only the newest 301 of them, so its EMA 28 and
ATR 14 had ~15 weeks past their warm-up. Now:
- the Hyperliquid and TxFlow loops build the 1w series from every daily
  fetched (_weekly_from_dailies(dailies_deep, ...)); the 1d row still reads
  the newest 301;
- the BTC pre-fetch for RS vs BTC fetches as deep, so a weekly flip up to
  ~99 weeks back still finds BTC's close at that week;
- NOODLE_WINDOW_DAYS['1w'] (the page's "> Nd" label) is 693;
- a trade snapshot's 1w reading is built from as many dailies, while its 1d
  reading keeps the newest TRADE_SNAPSHOT_DEPTH['1d'].

Real init_db() on a tmp_path SQLite file; candles are made up in code; no
network. web_portfolio spawns a background scheduler on import, neutralized
the usual way.
"""
import inspect
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db
from src.engines.noodle_bands import compute_noodle_state

DAY = 86400
WEEK = 7 * DAY
T0 = 1_640_995_200 + 4 * DAY    # Wed 2022-01-05 00:00 UTC (day 0 of the made-up series)
N = 701                          # what Hyperliquid returns for a 700-daily request (the bar the start falls in)


def _bars(closes, step, t0=T0):
    return [{'open': c, 'high': c + 1.0, 'low': c - 1.0, 'close': c, 'volume': 10.0,
             'time': t0 + i * step} for i, c in enumerate(closes)]


def _eth_dailies():
    """250 days down, then 451 days up: the weekly noodle turns bullish about
    60 weeks before the end, so the newest ~43 weeks are all one uptrend."""
    down = [100.0 - 0.1 * i for i in range(250)]
    return _bars(down + [down[-1] + 0.1 * (i + 1) for i in range(N - 250)], DAY)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.setattr(wp, "_SCANNER_SETTINGS_PATH", str(tmp_path / "scanner_settings.json"))
    return path


def _scan(monkeypatch, eth_dailies, btc_dailies):
    monkeypatch.setattr(wp, '_hl_fetch_top_volume', lambda n=None, limit=None: [
        {'name': 'ETH', 'symbol': 'ETH-USDT', 'volume_24h': 1000.0, 'price': eth_dailies[-1]['close'],
         'asset_type': 'crypto'}])
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    monkeypatch.setattr(wp, '_noodle_txflow_phase', lambda *a, **k: {'written': 0, 'failed': 0})
    end = eth_dailies[-1]['time'] + DAY
    h12 = _bars([100.0 + 0.01 * i for i in range(301)], DAY // 2, t0=end - 301 * DAY // 2)
    h1 = _bars([100.0 + 0.001 * i for i in range(2801)], 3600, t0=end - 2801 * 3600)
    series = {'ETH': {'1d': eth_dailies, '12h': h12, '1h': h1},
              'BTC': {'1d': btc_dailies, '12h': h12, '1h': h1}}
    asked = []

    def fake_fetch_candles(coin, interval, limit=200):
        asked.append((coin, interval, limit))
        return series[coin][interval]

    monkeypatch.setattr(wp, '_hl_fetch_candles', fake_fetch_candles)
    payload, status = wp._run_noodle_scan_body()
    assert status == 200 and payload['scanned'] == 1 and payload['errors'] == 0, payload
    conn = portfolio_db.get_connection()
    rows = {r['timeframe']: dict(r) for r in conn.execute(
        "SELECT * FROM noodle_state WHERE symbol='ETH'").fetchall()}
    conn.close()
    return asked, rows


def test_the_weekly_reads_every_daily_and_rs_vs_btc_reaches_its_flip(db, monkeypatch):
    eth = _eth_dailies()
    btc = _bars([50000.0 + 10.0 * i for i in range(N)], DAY)
    asked, rows = _scan(monkeypatch, eth, btc)
    assert ('ETH', '1d', 700) in asked and ('BTC', '1d', 700) in asked   # one request each, as before

    weekly = wp._weekly_from_dailies(eth, limit=wp.NOODLE_CANDLE_LIMITS['1w'])[:-1]
    assert len(weekly) >= 99
    exp = compute_noodle_state(weekly)
    w = rows['1w']
    assert w['state'] == exp['state'] == 'BULLISH'
    assert w['upper_band'] == pytest.approx(exp['upper_band']) and w['lower_band'] == pytest.approx(exp['lower_band'])
    assert w['flip_count_window'] == exp['flip_count_window']
    assert not w['flip_age_unbounded'] and w['flip_ts'] == exp['flip_ts']
    assert w['flip_ts'] < eth[-1]['time'] - 43 * WEEK                     # older than the old window reached

    # The old 301 dailies saw only the uptrend: a bullish state of unknown age.
    old = compute_noodle_state(wp._weekly_from_dailies(eth[-301:], limit=200)[:-1])
    assert old['flip_age_unbounded'] is True

    # RS vs BTC on that flip: BTC's weekly is as deep, so the flip week is covered.
    btc_weekly = wp._weekly_from_dailies(btc, limit=wp.NOODLE_CANDLE_LIMITS['1w'])[:-1]
    want = wp._rs_vs_btc_pct(exp['flip_ts'], exp['flip_price'], False, weekly[-1]['close'], btc_weekly)
    assert want is not None and w['rs_vs_btc_pct'] == pytest.approx(want)

    # The daily row still reads the newest 301 dailies, as before Landing 65.
    d_exp = compute_noodle_state(eth[-301:][:-1])
    d = rows['1d']
    assert d['upper_band'] == pytest.approx(d_exp['upper_band']) and d['flip_count_window'] == d_exp['flip_count_window']
    assert d['flip_ts'] == d_exp['flip_ts']


def test_txflow_markets_build_the_weekly_the_same_way():
    src = inspect.getsource(wp._noodle_txflow_phase)
    assert "dailies = dailies_deep[-(NOODLE_CANDLE_LIMITS['1d'] + 1):]" in src
    assert "weekly = _weekly_from_dailies(dailies_deep, limit=NOODLE_CANDLE_LIMITS['1w'])" in src
    assert "_weekly_from_dailies(dailies," not in src
    assert wp.TXFLOW_SCAN_CANDLE_LIMITS['1d'] == wp.DOC_TREND_CANDLE_LIMITS['1d']


def test_the_window_label_matches_the_daily_depth():
    # 700 dailies make 100 calendar weeks; the newest is still forming: 99 closed weeks.
    assert wp.NOODLE_WINDOW_DAYS['1w'] == (wp.DOC_TREND_CANDLE_LIMITS['1d'] // 7 - 1) * 7 == 693
    assert wp.NOODLE_CANDLE_LIMITS['1w'] * 7 >= wp.DOC_TREND_CANDLE_LIMITS['1d']   # the cap never trims


def _snapshot(monkeypatch, timeframes):
    asked = []
    as_of_ms = (T0 + 900 * DAY + 13 * 3600) * 1000      # mid-day, mid-week

    def fake_before(coin, interval, end_ms, limit):
        asked.append((interval, limit))
        step = {'1d': DAY, '1h': 3600}.get(interval) or wp.TRADE_SNAPSHOT_TF_MS[interval] // 1000
        last_open = end_ms // 1000 // step * step - step                  # the newest bar that has closed
        return [{'open': 100.0 + 0.05 * k, 'high': 101.0 + 0.05 * k, 'low': 99.0 + 0.05 * k,
                 'close': 100.0 + 0.05 * k, 'volume': 1.0, 'time': last_open - (limit - 1 - k) * step}
                for k in range(limit)]

    monkeypatch.setattr(wp, '_hl_candles_before', fake_before)
    settings = {'fast': 12, 'medium': 21, 'slow': 28, 'atr_length': 14, 'band_multiplier': 0.011875, 'use_atr': True}
    view = wp._trade_open_trend("ETH", as_of_ms, None, 1, timeframes, settings)
    return asked, view, settings, as_of_ms


def test_a_trade_snapshot_reads_the_weekly_as_deep_as_the_scan(monkeypatch):
    asked, view, settings, as_of_ms = _snapshot(monkeypatch, ('1d', '1w'))
    assert asked == [('1d', wp.DOC_TREND_CANDLE_LIMITS['1d'])]           # one daily request serves both
    assert int(view['1d']['bars']) == wp.TRADE_SNAPSHOT_DEPTH['1d'] == 300
    assert int(view['1w']['bars']) >= 99
    dailies = wp._hl_candles_before("ETH", "1d", as_of_ms, wp.DOC_TREND_CANDLE_LIMITS['1d'])
    d_exp = compute_noodle_state(dailies[-300:], **settings)
    assert float(view['1d']['upper_band']) == pytest.approx(d_exp['upper_band'], rel=1e-9)
    weeks = [w for w in wp._weekly_from_dailies(dailies, limit=10 ** 6) if w['time'] + WEEK <= as_of_ms // 1000]
    w_exp = compute_noodle_state(weeks, **settings)
    assert int(view['1w']['bars']) == len(weeks)
    assert float(view['1w']['upper_band']) == pytest.approx(w_exp['upper_band'], rel=1e-9)


def test_a_snapshot_without_the_weekly_keeps_its_daily_request(monkeypatch):
    asked, view, _, _ = _snapshot(monkeypatch, ('1d',))
    assert asked == [('1d', wp.TRADE_SNAPSHOT_DEPTH['1d'])]
    assert int(view['1d']['bars']) == 300
