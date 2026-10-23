"""Landing 58 (Oct 20): a point of interest (POI) per respected timeframe.

Glenn ruled ("your recs", 19:10 PDT): order blocks and FVGs are computed in
the Trends scan and stored per respected timeframe (A); found by the old ICT
detectors' own rules, searched within the current respected history and in
its direction instead of a dealing range's leg (A); a POI that overlaps the
noodle band is flagged "at the band", to combine with Testing now (A).
web_portfolio._trend_pois reuses _ict_order_block (with its D1 displacement
qualification) and _ict_fvg_in_zone (size and fill rules) with no zone
restriction; an OB stays valid until a closed candle closes through its far
side, an FVG until it is fully filled. Real init_db() on a tmp_path SQLite
file for the scan and the route. No network.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db

T0 = 1759000000
STEP = 14400
POI_COLUMNS = ('poi_type', 'poi_top', 'poi_bottom', 'poi_ts', 'poi_at_band', 'poi_count')
SETTINGS = dict(wp._SCANNER_SETTINGS_DEFAULTS)


def _bar(i, o, c, h, low):
    return {'time': T0 + i * STEP, 'open': o, 'high': h, 'low': low, 'close': c, 'volume': 1.0}


def _bullish_series(after=None, forming=None):
    """40 small up candles drifting up from 100 (range 0.6), then the setup:
    bar 40 a down candle (the order block: 101.9 to 102.4), bar 41 a strong up
    candle from it, bar 42 leaving a gap over bar 40 (the FVG: 102.4 to
    103.5), then small up candles to bar 59 that never come back down, then
    the still-forming bar. `after` replaces bars from 43 on; `forming` the
    forming bar."""
    bars = []
    for i in range(40):
        p = 100 + 0.05 * i
        bars.append(_bar(i, p - 0.1, p + 0.1, p + 0.3, p - 0.3))
    bars.append(_bar(40, 102.3, 102.0, 102.4, 101.9))
    bars.append(_bar(41, 102.0, 104.0, 104.1, 101.95))
    bars.append(_bar(42, 104.0, 104.6, 104.8, 103.5))
    if after is None:
        bars.append(_bar(43, 104.6, 104.7, 104.9, 104.0))
        p = 104.7
        for i in range(44, 60):
            bars.append(_bar(i, p, p + 0.1, p + 0.3, p - 0.2))
            p += 0.1
    else:
        bars.extend(after)
    n = len(bars)
    bars.append(forming or _bar(n, bars[-1]['close'], bars[-1]['close'], bars[-1]['close'] + 0.1, bars[-1]['close'] - 0.1))
    return bars


def _mirror(bars, axis=300.0):
    return [{'time': b['time'], 'open': axis - b['open'], 'close': axis - b['close'],
             'high': axis - b['low'], 'low': axis - b['high'], 'volume': b['volume']} for b in bars]


SINCE = T0 + 30 * STEP
OB = {'type': 'OB', 'top': 102.4, 'bottom': 101.9, 'ts': T0 + 40 * STEP}
FVG = {'type': 'FVG', 'top': 103.5, 'bottom': 102.4, 'ts': T0 + 40 * STEP}


def _picked(out):
    return {k: out[k] for k in ('type', 'top', 'bottom', 'ts')}


# -- the detector rules, inside the history --------------------------------

def test_finds_the_order_block_and_the_fvg_and_prefers_one_at_the_band():
    bars = _bullish_series()
    out = wp._trend_pois(bars, 'BULLISH', SINCE, 102.2, 101.5, settings=SETTINGS)
    assert out['count'] == 2 and out['at_band'] is True
    assert _picked(out) == OB                       # only the OB overlaps the band 101.5-102.2
    both = wp._trend_pois(bars, 'BULLISH', SINCE, 103.0, 102.0, settings=SETTINGS)
    assert both['at_band'] is True and _picked(both) == FVG        # both overlap: the nearest to price


def test_with_none_at_the_band_the_nearest_to_price_is_kept():
    out = wp._trend_pois(_bullish_series(), 'BULLISH', SINCE, 106.0, 105.0, settings=SETTINGS)
    assert out['count'] == 2 and out['at_band'] is False and _picked(out) == FVG
    nob = wp._trend_pois(_bullish_series(), 'BULLISH', SINCE, None, None, settings=SETTINGS)
    assert nob['at_band'] is False and _picked(nob) == FVG          # no band: nothing is at it


def test_a_close_through_the_order_block_and_a_filled_gap_are_spent():
    after = [_bar(43, 104.6, 104.7, 104.9, 104.0), _bar(44, 104.7, 101.5, 104.8, 101.0)]
    after += [_bar(45 + k, 101.5, 101.6, 101.8, 101.3) for k in range(10)]
    out = wp._trend_pois(_bullish_series(after=after), 'BULLISH', SINCE, 102.2, 101.5, settings=SETTINGS)
    assert out == {'type': None, 'top': None, 'bottom': None, 'ts': None, 'at_band': False, 'count': 0}


def test_a_spent_poi_stays_spent_when_price_comes_back():
    # bar 44 closes under the OB (and its low fills the gap); price then climbs back above both
    after = [_bar(43, 104.6, 104.7, 104.9, 104.0), _bar(44, 104.7, 101.5, 104.8, 101.0)]
    after += [_bar(45 + k, 101.5 + 0.2 * k, 101.7 + 0.2 * k, 101.9 + 0.2 * k, 101.3 + 0.2 * k) for k in range(10)]
    bars = _bullish_series(after=after)
    assert bars[-2]['close'] > OB['top']
    out = wp._trend_pois(bars, 'BULLISH', SINCE, 102.2, 101.5, settings=SETTINGS)
    assert out == {'type': None, 'top': None, 'bottom': None, 'ts': None, 'at_band': False, 'count': 0}


def test_a_wick_through_the_order_block_does_not_spend_it():
    # bar 44 wicks to 101.7 (under the OB's 101.9) but closes at 102.6; the wick fills the gap
    after = [_bar(43, 104.6, 104.7, 104.9, 104.0), _bar(44, 104.7, 102.6, 104.8, 101.7)]
    after += [_bar(45 + k, 102.6 + 0.1 * k, 102.7 + 0.1 * k, 102.9 + 0.1 * k, 102.4 + 0.1 * k) for k in range(10)]
    out = wp._trend_pois(_bullish_series(after=after), 'BULLISH', SINCE, 102.2, 101.5, settings=SETTINGS)
    assert out['count'] == 1 and out['at_band'] is True and _picked(out) == OB


def test_the_forming_bar_never_spends_a_poi():
    forming = _bar(60, 106.3, 101.0, 106.4, 100.5)                  # still open: ignored
    out = wp._trend_pois(_bullish_series(forming=forming), 'BULLISH', SINCE, 102.2, 101.5, settings=SETTINGS)
    assert out['count'] == 2 and _picked(out) == OB


def test_only_the_respected_history_is_searched():
    late = T0 + 45 * STEP                                           # the history began after the setup
    out = wp._trend_pois(_bullish_series(), 'BULLISH', late, 102.2, 101.5, settings=SETTINGS)
    assert out['count'] == 0 and out['type'] is None and out['at_band'] is False
    # A bearish history over the same bars finds no bullish setup.
    bear = wp._trend_pois(_bullish_series(), 'BEARISH', SINCE, 102.2, 101.5, settings=SETTINGS)
    assert bear['type'] is None


def test_no_history_means_nothing_to_search():
    none = {'type': None, 'top': None, 'bottom': None, 'ts': None, 'at_band': None, 'count': None}
    bars = _bullish_series()
    assert wp._trend_pois(bars, None, SINCE, 102.2, 101.5, settings=SETTINGS) == none
    assert wp._trend_pois(bars, 'BULLISH', None, 102.2, 101.5, settings=SETTINGS) == none
    assert wp._trend_pois(bars, 'BULLISH', SINCE + 1, 102.2, 101.5, settings=SETTINGS) == none   # not a bar
    assert wp._trend_pois(bars, 'BULLISH', bars[-2]['time'], 102.2, 101.5, settings=SETTINGS) == none
    assert wp._trend_pois([], 'BULLISH', SINCE, 102.2, 101.5, settings=SETTINGS) == none


def test_the_old_detectors_thresholds_apply():
    strict_ob = dict(SETTINGS, ob_body_atr_min=99)                  # no displacement is strong enough
    out = wp._trend_pois(_bullish_series(), 'BULLISH', SINCE, 102.2, 101.5, settings=strict_ob)
    assert out['count'] == 1 and _picked(out) == FVG and out['at_band'] is False
    strict_gap = dict(SETTINGS, fvg_min_atr_frac=99)                # no gap is big enough: no FVG, and the
    out = wp._trend_pois(_bullish_series(), 'BULLISH', SINCE, 102.2, 101.5, settings=strict_gap)
    assert out['count'] == 0                                        # OB's displacement gap fails too


def test_bearish_is_the_mirror():
    bars = _mirror(_bullish_series())
    out = wp._trend_pois(bars, 'BEARISH', SINCE, 300 - 101.5, 300 - 102.2, settings=SETTINGS)
    assert out['count'] == 2 and out['at_band'] is True
    assert out['type'] == 'OB' and out['top'] == pytest.approx(198.1) and out['bottom'] == pytest.approx(197.6)
    far = wp._trend_pois(bars, 'BEARISH', SINCE, 195.0, 194.0, settings=SETTINGS)
    assert far['at_band'] is False and far['type'] == 'FVG'
    assert far['bottom'] == pytest.approx(196.5) and far['top'] == pytest.approx(197.6)


def test_a_poi_price_sits_in_is_on_the_trends_side():
    # The last close drops into the gap: the FVG (102.4-103.5) contains it and counts, the OB is below it.
    # (A POI wholly on the other side of the last close is always spent or filled already, so the
    # side rule only decides POIs price sits in.)
    after = [_bar(43, 104.6, 104.7, 104.9, 104.0), _bar(44, 104.7, 103.0, 104.8, 102.9)]
    out = wp._trend_pois(_bullish_series(after=after), 'BULLISH', SINCE, 106.0, 105.0, settings=SETTINGS)
    assert out['count'] == 2 and _picked(out) == FVG
    # The bearish mirror: the last close sits inside the bearish gap.
    bear = wp._trend_pois(_mirror(_bullish_series(after=after)), 'BEARISH', SINCE, 1.0, 0.5, settings=SETTINGS)
    assert bear['count'] == 2 and bear['type'] == 'FVG' and bear['bottom'] == pytest.approx(196.5)


# -- the scan and the route ------------------------------------------------

@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    monkeypatch.setattr(wp, "_SCANNER_SETTINGS_PATH", str(tmp_path / "scanner_settings.json"))
    portfolio_db.init_db()
    conn = portfolio_db.get_connection()
    yield conn
    conn.close()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _lines(n, start, step):
    return [{'open': start + step * i, 'high': start + step * i + 1.0, 'low': start + step * i - 1.0,
             'close': start + step * i, 'volume': 10.0, 'time': T0 + i * 3600} for i in range(n)]


def _scan_inputs(monkeypatch):
    monkeypatch.setattr(wp, '_hl_fetch_top_volume', lambda n=None, limit=None: [
        {'name': 'ETH', 'symbol': 'ETH-USDT', 'volume_24h': 1000.0, 'price': 100.0, 'asset_type': 'crypto'}])
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    # Steep enough (0.5 a bar against an ATR of about 2) that the slow EMA's slope opens histories.
    series = {'1d': _lines(700, 100.0, 0.5), '12h': _lines(301, 100.0, 0.5), '1h': _lines(2800, 100.0, 0.5)}
    monkeypatch.setattr(wp, '_hl_fetch_candles', lambda coin, interval, limit=200: series[interval])


def test_init_db_adds_the_poi_columns(db):
    cols = {r[1]: r[2] for r in db.execute("PRAGMA table_info(noodle_state)")}
    assert [cols.get(c) for c in POI_COLUMNS] == ['TEXT', 'REAL', 'REAL', 'REAL', 'INTEGER', 'INTEGER']


def test_scan_stores_each_poi_field_in_its_own_column(db, monkeypatch):
    _scan_inputs(monkeypatch)
    histories = {}

    def fake_respect(closed, **kwargs):
        k = len(histories) + 1
        histories[len(closed)] = k
        return {'dir': 'BULLISH', 'tags': 3, 'last_ts': closed[-1]['time'], 'unbounded': False,
                'since': closed[-20]['time'], 'losses': 0, 'ranging_since': None}

    calls = []

    def fake_poi(candles, direction, since_ts, upper_band, lower_band, settings=None):
        calls.append({'n': len(candles), 'dir': direction, 'since': since_ts, 'up': upper_band, 'lo': lower_band,
                      'settings': settings})
        k = len(calls)
        if k % 2:
            return {'type': 'OB', 'top': 10.5 + k, 'bottom': 9.5 + k, 'ts': 5000.5 + k, 'at_band': True, 'count': k}
        return {'type': None, 'top': None, 'bottom': None, 'ts': None, 'at_band': False, 'count': 0}

    monkeypatch.setattr(wp, 'compute_respected_trend', fake_respect)
    monkeypatch.setattr(wp, '_trend_pois', fake_poi)
    payload, status = wp._run_noodle_scan_body()
    assert status == 200 and payload['errors'] == 0
    assert len(calls) == 4                                           # 1d, 12h, 4h, 1h; never 1w
    rows = {r['timeframe']: dict(r) for r in db.execute("SELECT * FROM noodle_state WHERE symbol='ETH'").fetchall()}
    for c in calls:
        assert c['n'] - 1 in histories                               # the full list: closed bars + the forming bar
        assert c['dir'] == 'BULLISH' and c['settings']['ob_body_atr_min'] == SETTINGS['ob_body_atr_min']
    seen = 0
    for tf in ('1d', '12h', '4h', '1h'):
        r = rows[tf]
        call = next(c for c in calls if c['up'] == r['upper_band'] and c['lo'] == r['lower_band'] and c['since'] == r['respect_since'])
        assert call is not None
        if r['poi_type'] == 'OB':
            k = r['poi_count']
            assert (r['poi_top'], r['poi_bottom'], r['poi_ts'], r['poi_at_band']) == (10.5 + k, 9.5 + k, 5000.5 + k, 1)
            seen += 1
        else:
            got = (r['poi_type'], r['poi_top'], r['poi_bottom'], r['poi_ts'], r['poi_at_band'], r['poi_count'])
            assert got == (None, None, None, None, 0, 0)
    assert seen == 2
    assert all(rows['1w'][c] is None for c in POI_COLUMNS)


def test_a_rescan_replaces_the_stored_poi(db, monkeypatch):
    _scan_inputs(monkeypatch)
    open_history = {'dir': 'BULLISH', 'tags': 3, 'unbounded': False, 'losses': 0, 'ranging_since': None}
    state = {'respect': open_history, 'poi': {'type': 'FVG', 'top': 7.5, 'bottom': 6.5, 'ts': 4000.0, 'at_band': True, 'count': 2}}

    def fake_respect(closed, **kw):
        r = dict(state['respect'])
        if r.get('dir'):
            r.update(last_ts=closed[-1]['time'], since=closed[-20]['time'])
        else:
            r.update(last_ts=None, since=None)
        return r

    monkeypatch.setattr(wp, 'compute_respected_trend', fake_respect)
    monkeypatch.setattr(wp, '_trend_pois', lambda *a, **k: dict(state['poi']))

    def stored():
        return [tuple(r[c] for c in POI_COLUMNS) for r in db.execute(
            "SELECT * FROM noodle_state WHERE timeframe != '1w' ORDER BY timeframe").fetchall()]

    assert wp._run_noodle_scan_body()[1] == 200
    assert stored() == [('FVG', 7.5, 6.5, 4000.0, 1, 2)] * 4
    state['poi'] = {'type': None, 'top': None, 'bottom': None, 'ts': None, 'at_band': False, 'count': 0}
    assert wp._run_noodle_scan_body()[1] == 200
    assert stored() == [(None, None, None, None, 0, 0)] * 4                       # none found now
    state['poi'] = {'type': 'OB', 'top': 9.0, 'bottom': 8.0, 'ts': 4100.0, 'at_band': False, 'count': 1}
    assert wp._run_noodle_scan_body()[1] == 200
    state['respect'] = {'dir': None, 'tags': None, 'unbounded': None, 'losses': None, 'ranging_since': None}
    assert wp._run_noodle_scan_body()[1] == 200
    assert stored() == [(None,) * 6] * 4                                           # the history ended


def test_no_history_means_no_search_and_null_columns(db, monkeypatch):
    _scan_inputs(monkeypatch)
    monkeypatch.setattr(wp, 'compute_respected_trend', lambda closed, **kw: {
        'dir': None, 'tags': None, 'last_ts': None, 'unbounded': None, 'since': None, 'losses': None,
        'ranging_since': None})
    monkeypatch.setattr(wp, '_trend_pois', lambda *a, **k: pytest.fail('searched without a history'))
    payload, status = wp._run_noodle_scan_body()
    assert status == 200 and payload['errors'] == 0
    for r in db.execute("SELECT * FROM noodle_state").fetchall():
        assert all(r[c] is None for c in POI_COLUMNS)


def test_a_failing_search_leaves_the_row_and_its_poi_columns_empty(db, monkeypatch, capsys):
    _scan_inputs(monkeypatch)
    monkeypatch.setattr(wp, 'compute_respected_trend', lambda closed, **kw: {
        'dir': 'BEARISH', 'tags': 2, 'last_ts': closed[-1]['time'], 'unbounded': False,
        'since': closed[-10]['time'], 'losses': 0, 'ranging_since': None})

    def boom(*a, **k):
        raise ValueError('bad candles')

    monkeypatch.setattr(wp, '_trend_pois', boom)
    payload, status = wp._run_noodle_scan_body()
    assert status == 200 and payload['errors'] == 0
    rows = db.execute("SELECT * FROM noodle_state WHERE timeframe != '1w'").fetchall()
    assert len(rows) == 4 and all(r['respect_dir'] == 'BEARISH' for r in rows)
    assert all(r[c] is None for r in rows for c in POI_COLUMNS)
    assert 'points of interest failed - ValueError: bad candles' in capsys.readouterr().out


def test_a_real_scan_matches_the_search_on_the_same_bars(db, monkeypatch):
    """The scan hands _trend_pois each timeframe's full candle list (forming bar last),
    the history's side and start, and the band it stored."""
    _scan_inputs(monkeypatch)
    seen = []
    real = wp._trend_pois

    def spy(candles, direction, since_ts, upper_band, lower_band, settings=None):
        out = real(candles, direction, since_ts, upper_band, lower_band, settings=settings)
        seen.append((candles, direction, since_ts, upper_band, lower_band, out))
        return out

    monkeypatch.setattr(wp, '_trend_pois', spy)
    payload, status = wp._run_noodle_scan_body()
    assert status == 200 and payload['errors'] == 0
    assert seen                                                      # the steady climb opens histories
    rows = {(r['upper_band'], r['lower_band']): dict(r) for r in db.execute(
        "SELECT * FROM noodle_state WHERE timeframe != '1w'").fetchall()}
    for candles, direction, since_ts, up, lo, out in seen:
        r = rows[(up, lo)]
        assert r['respect_dir'] == direction and r['respect_since'] == since_ts
        assert candles[-2]['close'] == r['last_close']               # the forming bar is last, not dropped
        got = (r['poi_type'], r['poi_top'], r['poi_bottom'], r['poi_ts'], r['poi_count'])
        assert got == (out['type'], out['top'], out['bottom'], out['ts'], out['count'])
        assert r['poi_at_band'] == (int(out['at_band']) if out['at_band'] is not None else None)


def test_route_returns_the_poi_columns(client, db, monkeypatch):
    monkeypatch.setattr(wp, '_maybe_kick_noodle_auto_refresh', lambda: False)
    monkeypatch.setattr(wp, '_hl_refresh_universes', lambda force=False: None)
    db.execute(
        "INSERT INTO noodle_state (symbol, timeframe, state, computed_at, respect_dir, respect_since, "
        "poi_type, poi_top, poi_bottom, poi_ts, poi_at_band, poi_count) VALUES "
        "('ETH', '4h', 'BULLISH', '2026-10-20T00:00:00+00:00', 'BULLISH', 1759000000.0, "
        "'FVG', 103.5, 102.4, 1760000000.0, 1, 3)")
    db.execute(
        "INSERT INTO noodle_state (symbol, timeframe, state, computed_at, respect_dir, respect_since, "
        "poi_type, poi_top, poi_bottom, poi_ts, poi_at_band, poi_count) VALUES "
        "('ETH', '1d', 'BEARISH', '2026-10-20T00:00:00+00:00', 'BEARISH', 1758000000.0, "
        "NULL, NULL, NULL, NULL, 0, 0)")
    db.execute(
        "INSERT INTO noodle_state (symbol, timeframe, state, computed_at) VALUES "
        "('ETH', '1w', 'BULLISH', '2026-10-20T00:00:00+00:00')")
    db.commit()
    resp = client.get('/api/trading/scanner/noodle-state')
    assert resp.status_code == 200
    tfs = resp.get_json()['symbols'][0]['timeframes']
    assert (tfs['4h']['poi_type'], tfs['4h']['poi_top'], tfs['4h']['poi_bottom'], tfs['4h']['poi_ts'],
            tfs['4h']['poi_at_band'], tfs['4h']['poi_count']) == ('FVG', 103.5, 102.4, 1760000000.0, True, 3)
    assert tfs['1d']['poi_type'] is None and tfs['1d']['poi_at_band'] is False and tfs['1d']['poi_count'] == 0
    assert all(tfs['1w'][c] is None for c in POI_COLUMNS)
