"""Phase 4a — MSS (market-structure-shift) detector suite.

Locks _detect_mss against three hand-charted BTC ground-truth cases (frozen HL
fixtures) plus tap-gate, no-lookahead, and per-evidence synthetic units. The
detector is additive and independent — the shipped _detect_choch is never
touched or called. No network: the ground-truth cases replay frozen candle
fixtures under tests/fixtures/.

MSS fires on the trigger TF for `bias` when, at/after the Stage-2 POI tap, a
CLOSED candle closes THROUGH the most-recent confirmed opposite swing (bearish →
swing low; bullish → swing high) AND the reversal carries >=1 named evidence
element (SFP / OB / FVG). Evidence is recorded by name; composition is
informational (the user adjudicates it against his charts).
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

_FIX = os.path.join(os.path.dirname(__file__), 'fixtures')
_ST = dict(wp._SCANNER_SETTINGS_DEFAULTS)


def _load(name):
    with open(os.path.join(_FIX, name)) as f:
        return json.load(f)


def _ts(s):
    """UTC date/datetime string → epoch seconds (bar OPEN basis)."""
    fmt = '%Y-%m-%d %H:%M' if ' ' in s else '%Y-%m-%d'
    return calendar.timegm(time.strptime(s, fmt))


def _date(ts):
    return time.strftime('%Y-%m-%d', time.gmtime(ts))


# ══════════════════════════════════════════════════════════════════════════════
# GROUND-TRUTH CASES (frozen fixtures) — the detector MUST reproduce these.
# ══════════════════════════════════════════════════════════════════════════════

def test_case_A_btc_h4_may2026_short():
    # BTC H4, early May 2026, SHORT. Weekly FVG POI ~80,000–84,500. Price rallies
    # INTO the zone ~May 5–6 (the tap); a confirmed H4 swing low ~80,900 forms, and
    # a strong down candle closes through it ~May 7 → MUST fire short there.
    candles = _load('btc_h4_may2026.json')
    r = wp._detect_mss(candles, 'bearish', settings=_ST, tap_time=_ts('2026-05-05'))
    assert r['fired'] is True
    assert r['direction'] == 'bearish'
    assert _date(r['break_bar_ts']) == '2026-05-07'          # the May-7 down-break
    assert r['break_close'] == 79868.0                       # the strong down close
    assert r['broken_swing']['side'] == 'low'
    assert 80000.0 < r['broken_swing']['price'] < 81500.0    # ~80,900 (actual 80,711)
    assert r['evidence']                                     # non-empty
    assert set(r['evidence']) <= {'SFP', 'OB', 'FVG'}


def test_case_A_negative_tap_gate_defers_fire():
    # NEGATIVE half: an H4 structure break ~a week earlier (Apr 27, close 77,100)
    # sits OUTSIDE any POI. With the tap gate at the May 5–6 zone entry, that
    # earlier break must NOT fire — the fire is deferred to May 7. Demonstrated by
    # contrast: an early (pre-POI) tap fires at the Apr-27 break; the proper POI
    # tap fires strictly later, at May 7.
    candles = _load('btc_h4_may2026.json')
    early = wp._detect_mss(candles, 'bearish', settings=_ST, tap_bar_index=5)
    proper = wp._detect_mss(candles, 'bearish', settings=_ST, tap_time=_ts('2026-05-05'))
    assert early['fired'] and proper['fired']
    assert _date(early['break_bar_ts']) == '2026-04-27'      # out-of-POI early break
    assert _date(proper['break_bar_ts']) == '2026-05-07'     # deferred to the POI break
    assert proper['break_bar_index'] > early['break_bar_index']
    # the break candle closes at/after the tap (never before it)
    assert proper['break_bar_ts'] >= _ts('2026-05-05')


def test_case_B_btc_h4_feb2026_long_most_recent_not_deeper():
    # BTC H4, late Feb 2026, LONG. Weekly OB POI ~63,000–65,000. Decline into the
    # zone prints lower highs (~68,600 then ~66,300); low ~62,800 around Feb 24. The
    # Feb 25 rally closes through the ~66,300 MOST-RECENT lower high → MUST fire
    # long there, NOT waiting for the deeper ~68,600 high.
    candles = _load('btc_h4_feb2026.json')
    r = wp._detect_mss(candles, 'bullish', settings=_ST, tap_time=_ts('2026-02-23'))
    assert r['fired'] is True
    assert r['direction'] == 'bullish'
    assert _date(r['break_bar_ts']) == '2026-02-25'
    assert r['break_close'] == 67368.0
    assert r['broken_swing']['side'] == 'high'
    # broke the most-recent ~66,300 high (actual 66,326) — NOT the deeper ~68,600.
    assert 66000.0 < r['broken_swing']['price'] < 66700.0
    assert r['broken_swing']['price'] < 68000.0
    # the fire close (67,368) is BELOW the deeper ~68,600 high → it did not wait for it.
    assert r['break_close'] < 68000.0
    assert r['evidence']


def test_case_C_btc_h1_mar2026_long():
    # BTC H1, Mar 1–2 2026, LONG. Daily OB POI ~64,700–68,200. H1 decline into the
    # zone; the large ~Mar 2 candle closes through the most-recent confirmed lower
    # high → MUST fire long on that candle.
    #
    # NOTE for chart adjudication: the user eyeballed the broken lower high at
    # ~67,000 (the Mar-01 ~18:00-PT pivot). The MOST-RECENT confirmed H1 pivot high
    # at the break is 66,692 (Mar-02 09:00 UTC), i.e. one pivot nearer than the
    # 67,000 the eye picks — exactly the locked "most recent, not second-pivot-back"
    # rule. The break candle, timing (~Mar 2 AM PT) and direction all match.
    candles = _load('btc_h1_mar2026.json')
    r = wp._detect_mss(candles, 'bullish', settings=_ST, tap_time=_ts('2026-03-01'))
    assert r['fired'] is True
    assert r['direction'] == 'bullish'
    assert _date(r['break_bar_ts']) == '2026-03-02'
    assert r['break_close'] == 67142.0                       # the large Mar-2 up close
    assert r['broken_swing']['side'] == 'high'
    assert 66000.0 < r['broken_swing']['price'] < 67200.0    # most-recent 66,692
    assert r['evidence']


def test_all_cases_evidence_non_empty_and_named():
    # Every ground-truth fire carries >=1 named evidence element from the fixed set.
    for name, bias, tap in [('btc_h4_may2026.json', 'bearish', '2026-05-05'),
                            ('btc_h4_feb2026.json', 'bullish', '2026-02-23'),
                            ('btc_h1_mar2026.json', 'bullish', '2026-03-01')]:
        r = wp._detect_mss(_load(name), bias, settings=_ST, tap_time=_ts(tap))
        assert r['fired']
        assert len(r['evidence']) >= 1
        assert set(r['evidence']) <= {'SFP', 'OB', 'FVG'}
        # every element present is described in evidence_detail
        for el in r['evidence']:
            assert el in r['evidence_detail']


def test_no_lookahead_broken_swing_confirmed_before_break_on_cases():
    # No-lookahead invariant on the real fires: the broken swing's pivot must be
    # CONFIRMED (pivot_index + right_bars) strictly before the break bar — a pivot
    # confirming AT the break bar is not usable.
    for name, bias, tap in [('btc_h4_may2026.json', 'bearish', '2026-05-05'),
                            ('btc_h4_feb2026.json', 'bullish', '2026-02-23'),
                            ('btc_h1_mar2026.json', 'bullish', '2026-03-01')]:
        r = wp._detect_mss(_load(name), bias, settings=_ST, tap_time=_ts(tap))
        assert r['fired']
        assert r['broken_swing']['pivot_index'] + 2 < r['break_bar_index']


def test_h1_opportunistic_confirm_annotation():
    # W-rooted pairs: after an H4 fire, the SAME detector runs on the H1 series and
    # attaches h1_confirm/h1_evidence as a pure annotation (never gating). Compose
    # the Feb H4 long with the Mar H1 long to exercise the second-call path.
    h4 = _load('btc_h4_feb2026.json')
    h1 = _load('btc_h1_mar2026.json')
    r = wp._detect_mss(h4, 'bullish', settings=_ST, tap_time=_ts('2026-02-23'),
                       h1_confirm_candles=h1, h1_tap_time=_ts('2026-03-01'))
    assert r['fired'] is True
    assert r['h1_confirm'] is True
    assert isinstance(r['h1_evidence'], list) and r['h1_evidence']
    # annotation only — the primary fire is unchanged by the H1 pass
    assert r['break_close'] == 67368.0


def test_h1_confirm_absent_when_h1_series_not_supplied():
    # Without an H1 series the annotation keys are simply absent (never gating).
    r = wp._detect_mss(_load('btc_h4_feb2026.json'), 'bullish', settings=_ST,
                       tap_time=_ts('2026-02-23'))
    assert r['fired'] is True
    assert 'h1_confirm' not in r


# ══════════════════════════════════════════════════════════════════════════════
# SYNTHETIC UNITS — tap gate, no-lookahead, and per-evidence isolation.
#
# A parametric builder (closes + explicit pivot-extreme overrides + asymmetric
# wicks) yields series where only the intended turning points are pivots and no
# stray FVGs form, so each evidence element can be isolated. Bullish scaffold:
# pivot HIGH @101 (idx16), decline to pivot LOW @88 (idx20), reversal breaks 101.
# ══════════════════════════════════════════════════════════════════════════════

_H = 3600 * 4
_WARM = [97.0] * 14
_APP = [98, 99, 100, 98, 96, 93, 90]   # idx14..20 (pivot-high @16, pivot-low @20 via overrides)


def _build(closes, hi=None, lo=None, uw=0.2, lw=1.2, body=None):
    hi = hi or {}; lo = lo or {}; body = body or {}
    out = []
    prev = closes[0]
    for i, cl in enumerate(closes):
        o = prev
        u, d = body[i] if i in body else (uw, lw)
        h = max(o, cl) + u
        l = min(o, cl) - d
        if i in hi:
            h = hi[i]
        if i in lo:
            l = lo[i]
        out.append({'open': o, 'high': round(h, 4), 'low': round(l, 4), 'close': cl,
                    'time': 1_700_000_000 + i * _H, 'volume': 1.0})
        prev = cl
    return out


def _scaf(mid, lo_extra=None, body=None):
    lo = {20: 88}
    if lo_extra:
        lo.update(lo_extra)
    return _build(_WARM + _APP + mid, {16: 101}, lo, body=body)


# reversal closes (idx21..): +1 gentle to break 101, then two margin bars.
_GENTLE = [91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 101, 101]


def test_no_tap_never_fires():
    # Tap gate: with no tap supplied the detector cannot fire (reason no_tap).
    r = wp._detect_mss(_scaf(_GENTLE), 'bullish', settings=_ST)
    assert r['fired'] is False
    assert r['reason'] == 'no_tap'


def test_break_without_evidence_does_not_fire():
    # A clean close-through with NO SFP/OB/FVG present → not fired, reason
    # no_evidence, and the break is reported as the nearest candidate.
    r = wp._detect_mss(_scaf(_GENTLE), 'bullish', settings=_ST, tap_bar_index=17)
    assert r['fired'] is False
    assert r['reason'] == 'no_evidence'
    assert r['nearest_candidate']['broken_swing']['price'] == 101


def test_sfp_only_fire():
    # One candle sweeps the confirmed swing low (wick below 88) and closes back
    # above → SFP is the sole evidence.
    r = wp._detect_mss(_scaf(_GENTLE, lo_extra={25: 86}), 'bullish',
                       settings=_ST, tap_bar_index=17)
    assert r['fired'] is True
    assert r['evidence'] == ['SFP']
    assert r['evidence_detail']['SFP']['swept_swing']['price'] == 88


def test_ob_only_fire():
    # A counter-bias (down) candle followed by a dims-passing up displacement at the
    # reversal origin → OB is the sole evidence (no sweep, no gap).
    ob = [91, 92, 93, 94, 95, 96, 97, 98, 99, 98, 100, 99, 101, 101, 101]
    r = wp._detect_mss(_scaf(ob), 'bullish', settings=_ST, tap_bar_index=17)
    assert r['fired'] is True
    assert r['evidence'] == ['OB']
    assert r['evidence_detail']['OB']['disp_body_atr'] >= _ST['ob_body_atr_min']
    assert r['evidence_detail']['OB']['disp_body_range'] >= _ST['ob_body_range_ratio_min']


def test_fvg_only_fire():
    # A single reversal-direction 3-candle gap from the breaking leg → FVG is the
    # sole evidence (no sweep, no dims-passing OB).
    fvg = [91, 92, 93, 94, 95, 98, 99, 100, 101, 101, 101]
    r = wp._detect_mss(_scaf(fvg, body={27: (0.2, 0.2)}), 'bullish',
                       settings=_ST, tap_bar_index=17)
    assert r['fired'] is True
    assert r['evidence'] == ['FVG']
    frac = r['evidence_detail']['FVG']['size_atr_frac']
    assert frac is None or frac >= _ST['fvg_min_atr_frac']


def test_no_lookahead_later_higher_pivot_ignored():
    # A higher swing high forms LATER in the series (after the break). The detector
    # must break the earlier confirmed pivot (@101, idx16) at the reversal — never
    # reaching forward to the later 110 pivot. Verifies swings are selected as of
    # the break bar (pivot confirmed strictly before it), not from the whole series.
    nl = [91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 101, 101,
          100, 103, 106, 110, 106, 103, 100, 100, 100]     # later higher pivot ~110
    r = wp._detect_mss(_scaf(nl, lo_extra={25: 86}), 'bullish',
                       settings=_ST, tap_bar_index=17)
    assert r['fired'] is True
    assert r['broken_swing']['pivot_index'] == 16
    assert r['broken_swing']['price'] == 101
    assert r['broken_swing']['pivot_index'] + 2 < r['break_bar_index']


def test_evidence_list_contents_are_named_and_deduped():
    # The evidence list is a list of distinct element NAMES drawn from the fixed set,
    # each backed by an entry in evidence_detail (composition is informational).
    r = wp._detect_mss(_load('btc_h4_feb2026.json'), 'bullish', settings=_ST,
                       tap_time=_ts('2026-02-23'))
    assert r['fired']
    assert r['evidence'] == list(dict.fromkeys(r['evidence']))   # no duplicates
    assert all(e in ('SFP', 'OB', 'FVG') for e in r['evidence'])
    assert set(r['evidence']) == set(r['evidence_detail'].keys())


def test_tunables_read_from_settings_not_hardcoded():
    # The two MSS tunables are present in the scanner-settings defaults and honored
    # from the passed settings dict (never hardcoded). Shrinking the SFP lookback so
    # the swept swing sits out of range drops SFP from the evidence.
    base = _scaf(_GENTLE, lo_extra={25: 86})
    assert 'mss_sfp_lookback_bars' in wp._SCANNER_SETTINGS_DEFAULTS
    assert 'mss_origin_window_bars' in wp._SCANNER_SETTINGS_DEFAULTS
    tight = dict(_ST)
    tight['mss_sfp_lookback_bars'] = 3     # swing low @idx20 now outside lookback
    r = wp._detect_mss(base, 'bullish', settings=tight, tap_bar_index=17)
    # with SFP gone and no other evidence, the gentle break no longer qualifies
    assert 'SFP' not in (r.get('evidence') or [])
