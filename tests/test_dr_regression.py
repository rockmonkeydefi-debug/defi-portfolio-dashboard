"""DR regression suite (reconstructed from hand-verified ground truth).

These encode the D2.5 BREAK-ONLY movement rules and the D2.6 origin significance
filter as SYNTHETIC replay fixtures — no network. Every assertion was confirmed
against the SHIPPED _ict_dealing_range / _ict_swing_points unmodified; a failure
here means either the reconstruction mis-encodes ground truth or a regression was
introduced, NOT a signal to edit the detector.

Ground-truth behaviors covered:
  break-only movement
    - sweep_no_move:  a wick through a boundary that CLOSES back inside never
      moves the boundary (the BTC June-weekly 59100-analog sweep).
    - break_jumps_to_wick: a CLOSE beyond a boundary jumps it to the
      running-extreme wick reached so far (inclusive of the break bar).
    - no_rebreak_inside: once broken, price trading back inside does not move it.
    - pivot-confirmation alone never moves a boundary.
  origin rule 1-A + significance filter (D2.6)
    - a sub-threshold (noise) opposite pivot is skipped and the next prominent
      pivot is picked (the H12 60935-analog filtered, 65587-analog picked).
    - empty-origin (all opposite pivots filtered) HOLDS the existing anchor.
    - the filter also gates the SEED: if nothing is eligible, no range forms.
"""
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

DAY = 86400


def _mk(o, h, l, c, i):
    return {'open': o, 'high': h, 'low': l, 'close': c,
            'time': 1_700_000_000 + i * DAY, 'volume': 1.0}


def _series(rows):
    return [_mk(o, h, l, c, i) for i, (o, h, l, c) in enumerate(rows)]


def _dr(rows, prom=0.0):
    candles = _series(rows)
    sh, sl = wp._ict_swing_points(candles, lookback=400, left_bars=2, right_bars=2)
    d = wp._ict_dealing_range(sh, sl, candles[-1]['close'], candles=candles,
                              pivot_min_prominence_atr=prom)
    return d


# A clean base: pivot low @2 = 100 (seed low), pivot high @5 = 200 (seed high),
# padding so the high confirms within the walk (final bar is the forming candle).
_BASE = [
    (150, 155, 148, 150), (150, 152, 140, 145), (145, 146, 100, 102),
    (102, 120, 101, 118), (118, 160, 117, 158), (158, 200, 157, 199),
    (199, 190, 150, 155), (155, 158, 145, 150), (150, 156, 146, 151),
    (151, 157, 147, 152),
]


def test_seed_forms_from_first_pivot_pair():
    d = _dr(_BASE)
    assert d is not None
    assert d['high'] == 200 and d['low'] == 100


def test_sweep_close_inside_does_not_move_boundary():
    # Wick to 90 (below the 100 low) but CLOSE 140 back inside → no move.
    rows = _BASE + [(151, 158, 90, 140), (140, 150, 138, 145)]
    d = _dr(rows)
    assert d['low'] == 100          # boundary held — sweep, not break


def test_pivot_confirmation_alone_never_moves_boundary():
    # _BASE already forms a SECOND confirmed pivot low (@7 ~145) inside the
    # range; a confirmed pivot with no close-break must not move the low.
    d = _dr(_BASE)
    assert d['low'] == 100


def test_close_break_jumps_low_to_running_extreme_wick():
    # First a 95-wick bar that closes back (no break), then a bar CLOSING at 88
    # (< 100) with low 80 → low jumps to the running-min wick (80). A trailing
    # bar makes the break bar a CLOSED bar the walk processes.
    rows = _BASE + [(151, 158, 95, 150), (150, 152, 80, 88), (88, 95, 86, 92)]
    d = _dr(rows)
    assert d['low'] == 80
    assert d['high'] == 200         # opposite boundary re-derives to the origin


def test_no_rebreak_when_price_returns_inside():
    rows = _BASE + [(151, 158, 95, 150), (150, 152, 80, 88),
                    (88, 150, 86, 140)]   # back inside; low 86 > 80
    d = _dr(rows)
    assert d['low'] == 80           # unchanged — no re-break


# ── Origin significance filter (D2.6). One fixture, three thresholds. ──
# ATR warmup (16 bars) so ATR14 is defined at the noise pivot. Prominent high
# @18 = 205 (65587-analog); noise high @23 = 131 (60935-analog) sits just above
# the lows so its min-leg/ATR is sub-threshold. A down-break at the end forces
# the high boundary to re-derive to the leg origin.
_WARM = [((150, 156, 144, 150) if i % 2 == 0 else (150, 155, 145, 150))
         for i in range(16)]
_FILTER_ROWS = _WARM + [
    (150, 152, 100, 105), (105, 120, 104, 118), (118, 205, 117, 200),
    (200, 190, 150, 160), (160, 150, 118, 120), (120, 125, 117, 123),
    (123, 129, 121, 127), (127, 131, 124, 129), (129, 128, 120, 124),
    (124, 126, 119, 122), (122, 127, 120, 125), (125, 126, 121, 124),
    (124, 123, 90, 95), (95, 120, 92, 110),
]


def test_no_filter_picks_most_recent_noise_pivot():
    # prom=0 (filter off): origin = most-recent usable high pivot = noise 131.
    d = _dr(_FILTER_ROWS, prom=0.0)
    assert d['high'] == 131
    assert d['low'] == 90           # broken side → running-min wick


def test_significance_filter_skips_noise_picks_prominent():
    # prom=1.49 (live): noise 131 is filtered → next prominent pivot 205 picked.
    d = _dr(_FILTER_ROWS, prom=1.49)
    assert d['high'] == 205
    assert d['low'] == 90


def test_empty_origin_holds_anchor():
    # prom=5.0: every opposite pivot filtered at the break → origin HELD → the
    # high anchor stays at the seed high (205); the broken low still moves.
    d = _dr(_FILTER_ROWS, prom=5.0)
    assert d['high'] == 205
    assert d['low'] == 90


def test_seed_filter_blocks_range_when_nothing_eligible():
    # prom=10.0: no pivot clears the threshold → no seed ever forms → no range.
    d = _dr(_FILTER_ROWS, prom=10.0)
    assert d is None
