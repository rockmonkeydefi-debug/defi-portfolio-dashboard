"""OB D1 qualification suite (reconstructed from hand-verified ground truth).

Synthetic replay against the SHIPPED _ob_qualification — the three-part
immediate-displacement test (leg-direction e+1, dims, e/e+1/e+2 displacement
FVG, e+2 closed). No network. A failure here means the reconstruction or a
regression — never a reason to edit the detector.

Fixtures use a 14-bar flat warmup (true range ≈ 2 → ATR14 ≈ 2) so thresholds are
controllable, then the cluster-end candle e (idx 14), the displacement e+1
(idx 15), e+2 (idx 16), and a trailing closed bar unless testing 'pending'.
Live settings: ob_body_atr_min=0.7, ob_body_range_ratio_min=0.35,
fvg_min_atr_frac=0.1.
"""
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

DAY = 86400
SETTINGS = {'ob_body_atr_min': 0.7, 'ob_body_range_ratio_min': 0.35,
            'fvg_min_atr_frac': 0.1}
E_IDX = 14   # cluster-end index in every fixture


def _mk(o, h, l, c, i):
    return {'open': o, 'high': h, 'low': l, 'close': c,
            'time': 1_700_000_000 + i * DAY, 'volume': 1.0}


def _build(e_row, e1_row, e2_row, trailing=True):
    rows = [(100, 101, 99, 100)] * 14      # ATR warmup, TR ≈ 2
    rows = list(rows) + [e_row, e1_row, e2_row]
    if trailing:
        rows.append((92, 93, 90, 91))      # makes e+2 a CLOSED bar
    return [_mk(o, h, l, c, i) for i, (o, h, l, c) in enumerate(rows)]


def _qual(candles):
    return wp._ob_qualification(candles, E_IDX, 'bearish', SETTINGS)


def test_qualified_cluster():
    # e up-candle; e+1 strong DOWN body (dims pass); e+2 gaps below e.low (FVG).
    c = _build((100, 102, 99, 101), (101, 101.5, 93.5, 94), (94, 98, 90, 92))
    q = _qual(c)
    assert q['status'] == 'qualified'
    assert q['reason'] is None
    assert q['measured']['fvg_ok'] is True


def test_wrong_direction_e1_is_not_leg_direction():
    # e+1 is an UP candle in a bearish leg → rejected at part (1).
    c = _build((100, 102, 99, 101), (101, 108, 100, 107), (107, 109, 104, 106))
    q = _qual(c)
    assert q['status'] == 'rejected'
    assert q['reason'] == 'not_leg_direction'


def test_weak_e1_body_is_dims_fail():
    # e+1 is a down candle but a tiny body → fails the dims thresholds.
    c = _build((100, 102, 99, 101), (101, 101.2, 100.7, 100.9), (100.9, 101, 96, 97))
    q = _qual(c)
    assert q['status'] == 'rejected'
    assert q['reason'] == 'dims_fail'


def test_no_gap_is_no_displacement_fvg():
    # Strong e+1 down body, but e+2 high (100) >= e.low (99) → no FVG gap.
    c = _build((100, 102, 99, 101), (101, 101.5, 93.5, 94), (94, 100, 92, 95))
    q = _qual(c)
    assert q['status'] == 'rejected'
    assert q['reason'] == 'no_displacement_fvg'


def test_unclosed_e2_is_pending():
    # No trailing bar → e+2 is the still-forming final candle → pending.
    c = _build((100, 102, 99, 101), (101, 101.5, 93.5, 94), (94, 98, 90, 92),
               trailing=False)
    q = _qual(c)
    assert q['status'] == 'pending'
    assert q['reason'] == 'pending_bars'
    assert q['measured']['e2_closed'] is False


def test_qualified_cluster_surfaces_via_order_block():
    # Integration: the detector attaches the same qualification to the cluster.
    c = _build((100, 102, 99, 101), (101, 101.5, 93.5, 94), (94, 98, 90, 92))
    dr = {'high': 105.0, 'low': 90.0,
          'anchor_high_time': c[E_IDX]['time'],      # down leg: high before low
          'anchor_low_time': c[E_IDX + 2]['time']}
    clusters = wp._ict_order_block(c, 'bearish', dr, settings=SETTINGS)
    matched = [o for o in clusters if o.get('cluster_end_idx') == E_IDX]
    assert matched, "expected a cluster ending at e"
    assert matched[0]['qualification']['status'] == 'qualified'
