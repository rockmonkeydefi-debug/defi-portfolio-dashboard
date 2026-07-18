"""DR anomaly exclusion-list suite (synthetic replays + a frozen BTC fixture).

The exclusion is an INPUT filter, not a rule change: an excluded bar contributes
body-only extremes to running-extreme tracking (its wick can never become a
boundary) and its pivots are ineligible as DR origins/seeds, while its CLOSE
stays real so breaks still fire. These tests lock that behavior against the
SHIPPED _ict_dealing_range; no network.
"""
import calendar
import json
import os
import threading
import time

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

DAY = 86400
_FIX = os.path.join(os.path.dirname(__file__), 'fixtures')


def _mk(o, h, l, c, i):
    return {'open': o, 'high': h, 'low': l, 'close': c,
            'time': 1_700_000_000 + i * DAY, 'volume': 1.0}


def _series(rows):
    return [_mk(o, h, l, c, i) for i, (o, h, l, c) in enumerate(rows)]


def _dr(rows, excl_idx=(), prom=0.0, trace=False):
    candles = _series(rows)
    sh, sl = wp._ict_swing_points(candles, lookback=400, left_bars=2, right_bars=2)
    excl = {candles[i]['time'] for i in excl_idx}
    tr = [] if trace else None
    d = wp._ict_dealing_range(sh, sl, candles[-1]['close'], candles=candles,
                              pivot_min_prominence_atr=prom, excluded_bar_times=excl,
                              trace_events=tr)
    if trace:
        return d, [e for e in tr if e.get('type') == 'break'], tr
    return d


# Base: pivot low @2 = 100 (seed low), pivot high @5 = 200 (seed high) + padding.
_BASE = [(150, 155, 148, 150), (150, 152, 140, 145), (145, 146, 100, 102),
         (102, 120, 101, 118), (118, 160, 117, 158), (158, 200, 157, 199),
         (199, 190, 150, 155), (155, 158, 145, 150), (150, 156, 146, 151),
         (151, 157, 147, 152)]


def test_excluded_wick_never_boundary():
    # A down-break bar with a deep wick (50) but a shallow body low (88). Without
    # exclusion the boundary jumps to the wick; with the bar excluded it jumps to
    # the body low — the anomalous wick can never become a boundary.
    rows = _BASE + [(151, 158, 95, 150), (150, 151, 50, 88), (88, 95, 86, 92)]
    assert _dr(rows)['low'] == 50                    # wick becomes the boundary
    assert _dr(rows, excl_idx=[11])['low'] == 88     # body-only after exclusion


def test_excluded_pivot_not_origin():
    # Down-break where the most-recent HIGH pivot sits on the excluded bar (@12);
    # origin selection must skip it and fall back to the older prominent high.
    rows = _BASE + [(151, 131, 120, 129), (129, 131, 121, 127), (127, 132, 124, 130),
                    (130, 128, 120, 124), (124, 126, 119, 122), (122, 90, 88, 92),
                    (92, 95, 88, 90)]
    assert _dr(rows)['high'] == 132                  # recent pivot is the origin
    assert _dr(rows, excl_idx=[12])['high'] == 200   # excluded pivot skipped


def test_anomaly_close_still_breaks():
    # The excluded bar's own CLOSE crosses the low → the break still fires; the
    # new low is the bar's body low (90), never its wick (85).
    rows = _BASE + [(150, 151, 85, 90), (90, 95, 88, 92)]
    d, breaks, _ = _dr(rows, excl_idx=[10], trace=True)
    assert len(breaks) >= 1                           # break fired on the anomaly close
    assert d['low'] == 90                             # body low, not the 85 wick


def test_unfreeze_sequence():
    # Frozen-range analog: a deep excluded flash wick (30) that no later close
    # ever breaks fossilizes the low and freezes the high. With the bar excluded
    # the decline's closes fire a sequence of down-breaks and the high re-derives
    # below its frozen value.
    rows = [(250, 255, 248, 250), (250, 252, 242, 245), (245, 246, 200, 202),
            (202, 260, 201, 258), (258, 300, 257, 299), (299, 292, 255, 260),
            (260, 266, 254, 258), (258, 264, 252, 256), (256, 262, 250, 254),
            (254, 262, 30, 252),                        # 9: FLASH (excluded) wick 30
            (252, 258, 248, 250), (250, 256, 246, 248), (248, 254, 244, 246),
            (246, 250, 192, 195),                       # 13: break #1
            (195, 205, 188, 192), (192, 200, 185, 188),
            (188, 230, 184, 225),                       # 16: lower-high pivot (230)
            (225, 220, 180, 182), (182, 215, 178, 184),
            (184, 190, 150, 152),                       # 19: break → origin 230
            (152, 158, 140, 142)]
    off = _dr(rows)
    on = _dr(rows, excl_idx=[9], trace=True)
    d_on, breaks_on, _ = on
    _, breaks_off, _ = _dr(rows, trace=True)
    assert off['low'] == 30                            # frozen on the deep wick
    assert d_on['low'] != 30                           # wick gone
    assert len(breaks_on) > len(breaks_off)            # sequence of down-breaks fires
    assert d_on['high'] < off['high']                  # high re-derives below frozen


def test_empty_exclusion_list_noop():
    # No exclusions (None, empty set, or the kwarg omitted) → byte-identical DR.
    rows = _BASE + [(151, 158, 95, 150), (150, 152, 80, 88), (88, 95, 86, 92)]
    candles = _series(rows)
    sh, sl = wp._ict_swing_points(candles, lookback=400, left_bars=2, right_bars=2)
    base = wp._ict_dealing_range(sh, sl, candles[-1]['close'], candles=candles)
    none_ = wp._ict_dealing_range(sh, sl, candles[-1]['close'], candles=candles,
                                  excluded_bar_times=None)
    empty = wp._ict_dealing_range(sh, sl, candles[-1]['close'], candles=candles,
                                  excluded_bar_times=set())
    assert base == none_ == empty


def test_dr_excluded_bar_times_matches_tf_and_date():
    def _t(s):
        return calendar.timegm(time.strptime(s, '%Y-%m-%d'))
    candles = [{'time': _t('2025-10-06')}, {'time': _t('2025-10-13')}]
    settings = {'dr_anomaly_exclusions': [{'tf': '1W', 'date': '2025-10-06'}]}
    # case-insensitive TF match ('1W' entry vs '1w' interval)
    assert wp._dr_excluded_bar_times('1w', candles, settings) == {_t('2025-10-06')}
    # non-matching TF → empty (the weekly entry does not touch the daily walk)
    assert wp._dr_excluded_bar_times('1d', candles, settings) == set()
    # empty/missing list → empty
    assert wp._dr_excluded_bar_times('1w', candles, {}) == set()


def test_btc_1w_regression_unchanged_with_exclusion():
    # HARD GATE: BTC 1W must stay EXACTLY 82799 / 58062 (eq 70430.5) with the
    # default 2025-10-06 exclusion active — its verified anchors are 2026
    # structures and must be unperturbed. Replay of a frozen weekly fixture.
    with open(os.path.join(_FIX, 'btc_1w_weekly.json')) as f:
        bars = json.load(f)
    sh, sl = wp._ict_swing_points(bars, lookback=100, left_bars=2, right_bars=2)
    excl = {c['time'] for c in bars
            if time.strftime('%Y-%m-%d', time.gmtime(c['time'])) == '2025-10-06'}
    assert len(excl) == 1                              # the fixture contains the Oct bar
    d = wp._ict_dealing_range(sh, sl, bars[-1]['close'], candles=bars,
                              pivot_min_prominence_atr=1.49, excluded_bar_times=excl)
    assert d['high'] == 82799.0
    assert d['low'] == 58062.0
    assert d['eq'] == 70430.5
