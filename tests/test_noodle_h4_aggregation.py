"""Intraday-timeframes Commit 1 (HANDOFF_intraday_timeframes.md) - unit
tests for _h4_from_h1 (web_portfolio.py) plus the ruling-2 parity GATE:
aggregating real HL 1h candles through _h4_from_h1 must match HL's own
native 4h candles bar-for-bar, for at least two symbols. If that parity
test fails on any bar, the aggregator is wrong (or a real UTC-alignment
assumption is wrong) and 4h must not ship until that's understood - see
ruling 2, this is not a test to loosen to force green.

The parity fixtures (tests/fixtures/noodle_h1_{btc,eth}.json and
tests/fixtures/noodle_h4_native_{btc,eth}.json) were captured live through
the real _hl_fetch_candles -> _hl_post -> _hl_rate_acquire path (same rate
limiter the scan body uses), then trimmed to drop each series' own
still-forming last bar - the same candles[:-1] treatment the scan body
applies uniformly to every timeframe - so the fixtures already represent
closed bars only. Deliberately separate from tests/fixtures/btc_h1_mar2026
.json / btc_h4_feb2026.json / btc_h4_may2026.json, which belong to
test_dr_anomaly_exclusion.py / test_mss_detector.py (ICT/cascade, out of
scope here) and whose date ranges don't both usefully overlap anyway.
"""
import json
import os

import pytest

import web_portfolio as wp

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def _load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return json.load(f)


def _synthetic_h1(start_ts, n, step=3600, base_price=100.0):
    """n synthetic 1h candles, one per hour starting at start_ts (should
    already be a 4h-boundary-aligned epoch second for tests that care
    about bucket edges). Distinct open/high/low/close/volume per bar so
    aggregation (open-of-first, close-of-last, extremes, summed volume)
    is actually exercised rather than accidentally trivial."""
    out = []
    for i in range(n):
        out.append({
            'time': start_ts + i * step,
            'open': base_price + i,
            'high': base_price + i + 0.5,
            'low': base_price + i - 0.5,
            'close': base_price + i + 0.25,
            'volume': 10.0 + i,
        })
    return out


# ── aggregator unit tests ──────────────────────────────────────────────

def test_h4_from_h1_empty_input_returns_empty_list():
    assert wp._h4_from_h1([], limit=100) == []


def test_h4_from_h1_aligns_to_utc_4h_boundaries():
    # 1970-01-01 08:00:00 UTC - a real 4h boundary (28800 = 8*3600, and
    # 28800 % 14400 == 0) - offset by 1h so the bucket must be computed,
    # not accidentally equal to the input's own first timestamp.
    start = 28800 - 3600   # 07:00 UTC - belongs to the 04:00-08:00 bucket
    candles = _synthetic_h1(start, n=8)   # spans 07:00 -> 14:00
    out = wp._h4_from_h1(candles, limit=100)
    for bucket in out:
        assert bucket['time'] % 14400 == 0, f"bucket time {bucket['time']} not 4h-aligned"


def test_h4_from_h1_open_close_high_low_volume_aggregation():
    # Exactly one full 4-bar bucket, 00:00-04:00 UTC.
    candles = _synthetic_h1(0, n=4)
    out = wp._h4_from_h1(candles, limit=100)
    assert len(out) == 1
    bucket = out[0]
    assert bucket['time'] == 0
    assert bucket['open'] == candles[0]['open']      # open of FIRST bar
    assert bucket['close'] == candles[-1]['close']    # close of LAST bar
    assert bucket['high'] == max(c['high'] for c in candles)
    assert bucket['low'] == min(c['low'] for c in candles)
    assert bucket['volume'] == pytest.approx(sum(c['volume'] for c in candles))


def test_h4_from_h1_retains_partial_trailing_bucket():
    """A forming/partial bucket (here: 2 of 4 hours present) is NOT dropped
    by the aggregator itself - ruling 1's contract mirrors
    _weekly_from_dailies exactly: the shared candles[:-1] in the scan-body
    loop is what drops the forming bar, uniformly for every timeframe."""
    candles = _synthetic_h1(0, n=6)   # one full bucket (0-4) + a 2-bar partial (4-8)
    out = wp._h4_from_h1(candles, limit=100)
    assert len(out) == 2
    partial = out[1]
    assert partial['time'] == 14400
    assert partial['open'] == candles[4]['open']
    assert partial['close'] == candles[5]['close']
    assert partial['volume'] == pytest.approx(candles[4]['volume'] + candles[5]['volume'])


def test_h4_from_h1_respects_limit():
    candles = _synthetic_h1(0, n=40)   # 10 full 4h buckets
    out = wp._h4_from_h1(candles, limit=3)
    assert len(out) == 3
    # the LAST 3 buckets, not the first 3.
    all_buckets = wp._h4_from_h1(candles, limit=100)
    assert out == all_buckets[-3:]


def test_h4_from_h1_handles_the_off_by_one_1441_bar_depth_probe_result():
    """The live 1h depth probe (Step 1/2) returned 1441 bars for a
    1440-bar request - an off-by-one, not a truncation. The scan body
    slices defensively before calling this helper, but the helper itself
    must not choke on an input length that isn't a clean multiple of 4
    either."""
    candles = _synthetic_h1(0, n=1441)
    out = wp._h4_from_h1(candles, limit=360)
    assert len(out) == 360
    for bucket in out:
        assert bucket['time'] % 14400 == 0


# ── ruling 2 GATE: real-data parity against HL's own native 4h ─────────

@pytest.mark.parametrize('symbol', ['btc', 'eth'])
def test_h4_from_h1_matches_native_4h_bar_for_bar(symbol):
    h1 = _load_fixture(f'noodle_h1_{symbol}.json')
    native_h4 = _load_fixture(f'noodle_h4_native_{symbol}.json')

    aggregated = wp._h4_from_h1(h1, limit=len(h1))
    aggregated_by_time = {c['time']: c for c in aggregated}
    native_by_time = {c['time']: c for c in native_h4}

    # Only buckets built from a FULL 4 contributing 1h bars are a fair
    # native comparison. The h1 fixture's fetch window doesn't start (or,
    # post-trim, end) on a 4h boundary, so its leading and trailing 4h
    # buckets are legitimately partial (1-3 hours of source data) - _h4_
    # from_h1 aggregates them anyway (mirroring _weekly_from_dailies's own
    # "don't drop partial buckets" contract), so they exist in
    # `aggregated` with the SAME time key as their native counterpart but
    # necessarily DIFFERENT values (fewer source hours). That's a fixture-
    # window edge effect, not an aggregation bug - confirmed by counting
    # contributing bars per bucket directly from the fixture. Real scans
    # hit the same edge only once, on the single oldest bucket of a
    # ~360-bucket series, which is warm-up truncation any indicator series
    # already has - not something this parity gate needs to cover.
    from collections import Counter
    bucket_bar_counts = Counter((c['time'] // 14400) * 14400 for c in h1)
    full_buckets = {t for t, n in bucket_bar_counts.items() if n == 4}

    shared_times = sorted(full_buckets & set(aggregated_by_time) & set(native_by_time))
    assert len(shared_times) >= 30, (
        f"only {len(shared_times)} fully-covered overlapping 4h buckets "
        f"between the {symbol} 1h and native-4h fixtures - not enough "
        f"overlap to be a meaningful parity check; fixtures may need "
        f"recapturing with a wider window")

    for t in shared_times:
        agg = aggregated_by_time[t]
        nat = native_by_time[t]
        assert agg['open'] == pytest.approx(nat['open']), f"{symbol} @ {t}: open"
        assert agg['close'] == pytest.approx(nat['close']), f"{symbol} @ {t}: close"
        assert agg['high'] == pytest.approx(nat['high']), f"{symbol} @ {t}: high"
        assert agg['low'] == pytest.approx(nat['low']), f"{symbol} @ {t}: low"
        assert agg['volume'] == pytest.approx(nat['volume'], rel=1e-6), f"{symbol} @ {t}: volume"
