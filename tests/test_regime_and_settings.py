"""Phase 4c backend — weekly regime + editable anomaly exclusions.

Regime units exercise the pure _weekly_regime (close-based, prominence-passing,
exclusion-honoring swing monotonicity). Settings tests round-trip the
dr_anomaly_exclusions PUT acceptance (valid persists / malformed rejected) against
a temp settings file. No network.
"""
import os
import tempfile
import threading
import time

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

_WEEK = 7 * 24 * 3600
# Low prominence threshold so the synthetic monotonicity — not ATR calibration — is
# what these units assert; the real 1.40 default is exercised live (see summary).
_ST = dict(wp._SCANNER_SETTINGS_DEFAULTS)
_ST['dr_pivot_min_prominence_atr'] = 0.1


def _series(closes, t0=1_700_000_000):
    return [{'open': c, 'high': c + 1, 'low': c - 1, 'close': c,
             'time': t0 + i * _WEEK, 'volume': 1.0} for i, c in enumerate(closes)]


# Pivots spaced ~4 bars apart so each peak/trough is a genuine 2-bar local extreme.
_BULL = [20, 25, 30, 22, 12, 20, 40, 30, 18, 28, 50, 40, 22, 30, 35]   # HH 30/40/50, HL 12/18/22
_BEAR = [40, 45, 50, 40, 22, 35, 40, 30, 18, 25, 30, 20, 12, 18, 22]   # LH 50/40/30, LL 22/18/12


def test_regime_bullish_when_both_ascending():
    r = wp._weekly_regime(_series(_BULL), _ST)
    assert r['regime'] == 'bullish'
    assert [h['price'] for h in r['highs']] == [30, 40, 50]
    assert [lo['price'] for lo in r['lows']] == [12, 18, 22]
    # dates carried for display
    assert all(h['date'] for h in r['highs'])


def test_regime_bearish_when_both_descending():
    r = wp._weekly_regime(_series(_BEAR), _ST)
    assert r['regime'] == 'bearish'
    assert [h['price'] for h in r['highs']] == [50, 40, 30]
    assert [lo['price'] for lo in r['lows']] == [22, 18, 12]


def test_regime_neutral_hh_but_ll():
    # ascending highs, DESCENDING lows → neutral (not both same direction).
    mix = [20, 25, 30, 22, 12, 20, 40, 30, 8, 28, 50, 40, 4, 30, 35]
    r = wp._weekly_regime(_series(mix), _ST)
    assert r['regime'] == 'neutral'
    assert [h['price'] for h in r['highs']] == [30, 40, 50]
    assert [lo['price'] for lo in r['lows']] == [12, 8, 4]


def test_regime_neutral_lh_but_hl():
    # descending highs, ASCENDING lows → neutral.
    mix = [40, 45, 50, 40, 12, 35, 40, 30, 18, 25, 30, 20, 22, 28, 33]
    r = wp._weekly_regime(_series(mix), _ST)
    assert r['regime'] == 'neutral'
    assert [h['price'] for h in r['highs']] == [50, 40, 30]
    assert [lo['price'] for lo in r['lows']] == [12, 18, 20]


def test_regime_neutral_fewer_than_three_highs():
    # Only two qualifying highs → neutral regardless of lows.
    short = [20, 25, 30, 22, 12, 20, 40, 30, 18, 25, 28]
    r = wp._weekly_regime(_series(short), _ST)
    assert r['regime'] == 'neutral'
    assert len(r['highs']) < 3


def test_regime_neutral_equal_values_not_strictly_monotonic():
    # Highs 30, 40, 40 → not STRICTLY ascending → neutral.
    eq = [20, 25, 30, 22, 12, 20, 40, 30, 18, 28, 40, 30, 22, 30, 35]
    r = wp._weekly_regime(_series(eq), _ST)
    assert r['regime'] == 'neutral'
    assert [h['price'] for h in r['highs']] == [30, 40, 40]


def test_regime_excluded_bar_pivot_skipped():
    # Excluding the middle high (40 @ idx6) drops the qualifying highs to two →
    # the pivot is ineligible (as in the DR walk) and the regime falls to neutral.
    cs = _series(_BULL)
    date = time.strftime('%Y-%m-%d', time.gmtime(cs[6]['time']))
    st = dict(_ST)
    st['dr_anomaly_exclusions'] = [{'tf': '1W', 'date': date}]
    r = wp._weekly_regime(cs, st)
    assert 40 not in [h['price'] for h in r['highs']]     # excluded pivot gone
    assert r['regime'] == 'neutral'
    # baseline (no exclusion) is bullish → the exclusion is what changed it
    assert wp._weekly_regime(cs, _ST)['regime'] == 'bullish'


def test_regime_neutral_on_empty_or_short():
    assert wp._weekly_regime([], _ST)['regime'] == 'neutral'
    assert wp._weekly_regime(_series([10, 20, 30]), _ST)['regime'] == 'neutral'


# ── per-TF regime thresholds (4c follow-up) ───────────────────────────────────

# A close series whose recent structure is 3 descending highs + 3 descending lows,
# but the H3 / L2 pivots score in [1.0, 1.49): at threshold 1.49 they are filtered
# (only 2 qualifying highs/lows → neutral); at 1.0 they pass → bearish. ATR is
# defined here (pivots at index >= 16) so the threshold genuinely matters.
_FLIP = [88.0, 88.5, 89.0, 89.5, 90.0, 90.5, 91.0, 91.5, 92.0, 92.5, 93.0, 93.5,
         94.0, 94.5, 95.0, 95.5, 96.0, 93.75, 91.5, 89.25, 87, 88.25, 89.5, 90.75,
         92, 90.125, 88.25, 86.375, 84.5, 85.375, 86.25, 87.125, 88, 85.0, 82.0,
         79.0, 76, 78.0, 80.0, 82.0, 84.0]


def test_regime_threshold_flip_neutral_at_149_bearish_at_10():
    cs = _series(_FLIP)
    st = dict(wp._SCANNER_SETTINGS_DEFAULTS)
    assert wp._regime(cs, '1w', 1.49, st)['regime'] == 'neutral'
    assert wp._regime(cs, '1w', 1.0, st)['regime'] == 'bearish'


def test_weekly_regime_reads_1w_threshold_key():
    cs = _series(_FLIP)
    strict = dict(wp._SCANNER_SETTINGS_DEFAULTS); strict['regime_min_prominence_atr_1w'] = 1.49
    loose = dict(wp._SCANNER_SETTINGS_DEFAULTS); loose['regime_min_prominence_atr_1w'] = 1.0
    assert wp._weekly_regime(cs, strict)['regime'] == 'neutral'
    assert wp._weekly_regime(cs, loose)['regime'] == 'bearish'


def test_daily_regime_reads_1d_threshold_key_and_rule():
    # Daily regime runs the same last-3 rule; at the default 1.0 the bullish
    # construction (ATR-undefined on the short synthetic → prominence passes) reads
    # bullish, and the 1d key is what it consults.
    cs = _series(_BULL)
    st = dict(wp._SCANNER_SETTINGS_DEFAULTS); st['regime_min_prominence_atr_1d'] = 1.0
    assert wp._daily_regime(cs, st)['regime'] == 'bullish'


def test_daily_regime_honors_1d_anomaly_exclusion():
    # A '1D' exclusion drops the excluded pivot from the daily regime (same as the
    # DR walk), flipping the bullish construction to neutral.
    cs = _series(_BULL)
    date = time.strftime('%Y-%m-%d', time.gmtime(cs[6]['time']))   # middle high bar
    st = dict(wp._SCANNER_SETTINGS_DEFAULTS)
    st['dr_anomaly_exclusions'] = [{'tf': '1D', 'date': date}]
    assert 40 not in [h['price'] for h in wp._daily_regime(cs, st)['highs']]
    assert wp._daily_regime(cs, st)['regime'] == 'neutral'
    # baseline (no exclusion) is bullish
    assert wp._daily_regime(cs, dict(wp._SCANNER_SETTINGS_DEFAULTS))['regime'] == 'bullish'


# ── dr_anomaly_exclusions PUT round-trip ──────────────────────────────────────

def _put(json_body, tmp_path):
    """Invoke the (undecorated) settings PUT view against a temp settings file.
    Returns (status_code, payload_dict)."""
    wp._SCANNER_SETTINGS_PATH = tmp_path
    with wp.app.test_request_context(
            '/api/trading/scanner/settings', method='PUT', json=json_body):
        resp = wp.api_scanner_settings_put.__wrapped__()
    if isinstance(resp, tuple):
        body, status = resp[0], resp[1]
    else:
        body, status = resp, 200
    return status, body.get_json()


def test_exclusions_put_valid_list_persists(tmp_path):
    p = str(tmp_path / 'scanner_settings.json')
    status, saved = _put(
        {'dr_anomaly_exclusions': [{'tf': '1W', 'date': '2025-10-06'},
                                   {'tf': '4h', 'date': '2026-01-02'}]}, p)
    assert status == 200
    assert saved['dr_anomaly_exclusions'] == [
        {'tf': '1W', 'date': '2025-10-06'}, {'tf': '4h', 'date': '2026-01-02'}]
    # persisted and read back through the normal loader
    wp._SCANNER_SETTINGS_PATH = p
    assert wp._scanner_settings()['dr_anomaly_exclusions'][0]['date'] == '2025-10-06'


def test_exclusions_put_rejects_non_list(tmp_path):
    status, body = _put({'dr_anomaly_exclusions': 'nope'}, str(tmp_path / 's.json'))
    assert status == 400


def test_exclusions_put_rejects_unknown_tf(tmp_path):
    status, body = _put(
        {'dr_anomaly_exclusions': [{'tf': '3d', 'date': '2025-10-06'}]},
        str(tmp_path / 's.json'))
    assert status == 400
    assert 'tf' in body['error']


def test_exclusions_put_rejects_bad_date(tmp_path):
    status, body = _put(
        {'dr_anomaly_exclusions': [{'tf': '1w', 'date': '2025-13-99'}]},
        str(tmp_path / 's.json'))
    assert status == 400
    assert 'date' in body['error']


def test_exclusions_put_rejects_non_object_entry(tmp_path):
    status, body = _put(
        {'dr_anomaly_exclusions': ['2025-10-06']}, str(tmp_path / 's.json'))
    assert status == 400


# ── regime threshold PUT round-trip (both new keys) ───────────────────────────

def test_regime_thresholds_put_persist(tmp_path):
    p = str(tmp_path / 'scanner_settings.json')
    status, saved = _put(
        {'regime_min_prominence_atr_1w': 0.8, 'regime_min_prominence_atr_1d': 1.2}, p)
    assert status == 200
    assert saved['regime_min_prominence_atr_1w'] == 0.8
    assert saved['regime_min_prominence_atr_1d'] == 1.2
    wp._SCANNER_SETTINGS_PATH = p
    assert wp._scanner_settings()['regime_min_prominence_atr_1d'] == 1.2


def test_regime_thresholds_put_reject_out_of_bounds(tmp_path):
    s1, _ = _put({'regime_min_prominence_atr_1w': 99}, str(tmp_path / 'a.json'))
    s2, _ = _put({'regime_min_prominence_atr_1d': 0.0}, str(tmp_path / 'b.json'))
    s3, _ = _put({'regime_min_prominence_atr_1w': 'abc'}, str(tmp_path / 'c.json'))
    assert s1 == 400 and s2 == 400 and s3 == 400


def test_regime_thresholds_default_to_one():
    d = wp._SCANNER_SETTINGS_DEFAULTS
    assert d['regime_min_prominence_atr_1w'] == 1.0
    assert d['regime_min_prominence_atr_1d'] == 1.0


# ── detection tunables newly PUT-wired for the settings regroup ───────────────

def test_detection_tunables_put_persist(tmp_path):
    p = str(tmp_path / 'scanner_settings.json')
    status, saved = _put({'fvg_min_atr_frac': 0.2, 'mss_sfp_lookback_bars': 40,
                          'mss_origin_window_bars': 12}, p)
    assert status == 200
    assert saved['fvg_min_atr_frac'] == 0.2
    assert saved['mss_sfp_lookback_bars'] == 40
    assert saved['mss_origin_window_bars'] == 12


def test_detection_tunables_put_reject_bad(tmp_path):
    s1, _ = _put({'mss_sfp_lookback_bars': 0}, str(tmp_path / 'a.json'))
    s2, _ = _put({'fvg_min_atr_frac': 99}, str(tmp_path / 'b.json'))
    s3, _ = _put({'mss_origin_window_bars': 'x'}, str(tmp_path / 'c.json'))
    assert s1 == 400 and s2 == 400 and s3 == 400


# ── exclusions optional-time PUT round-trip (Phase 5) ─────────────────────────

def test_exclusions_put_timed_entry_persists(tmp_path):
    p = str(tmp_path / 's.json')
    status, saved = _put({'dr_anomaly_exclusions': [
        {'tf': '4H', 'date': '2025-10-10', 'time': '20:00'},   # timed
        {'tf': '1D', 'date': '2025-10-10'}]}, p)               # date-only stays date-only
    assert status == 200
    assert saved['dr_anomaly_exclusions'][0] == {'tf': '4H', 'date': '2025-10-10', 'time': '20:00'}
    assert saved['dr_anomaly_exclusions'][1] == {'tf': '1D', 'date': '2025-10-10'}   # no time key


def test_exclusions_put_normalizes_and_rejects_bad_time(tmp_path):
    # zero-pads the hour of a valid time (1-digit hour, 2-digit minute)
    _, saved = _put({'dr_anomaly_exclusions': [
        {'tf': '12h', 'date': '2025-10-10', 'time': '9:05'}]}, str(tmp_path / 'a.json'))
    assert saved['dr_anomaly_exclusions'][0]['time'] == '09:05'
    # rejects an unparseable time
    s2, _ = _put({'dr_anomaly_exclusions': [
        {'tf': '4H', 'date': '2025-10-10', 'time': '25:99'}]}, str(tmp_path / 'b.json'))
    assert s2 == 400
    # blank time → treated as date-only (no time key persisted)
    _, saved3 = _put({'dr_anomaly_exclusions': [
        {'tf': '4H', 'date': '2025-10-10', 'time': ''}]}, str(tmp_path / 'c.json'))
    assert 'time' not in saved3['dr_anomaly_exclusions'][0]
