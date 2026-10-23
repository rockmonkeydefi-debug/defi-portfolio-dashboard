"""Doc's Daily and Weekly Trend EMAs (Paragon / RM Trends v4.11) - pure engine.

Glenn's rulings (Oct 16, SPEC_doc_system.md Part F): Doc's Daily Trend is
EMA 100 (fast) and EMA 200 (slow) of 4H closes, and his Weekly Trend is
EMA 100 and EMA 200 of daily closes. Setup 1's "Daily cross" is the Daily
Trend's fast EMA crossing its slow EMA. compute_ema_cross gives one
series' two EMAs, which side of the slow EMA the fast one is on, and when
it got there.

Pure, like noodle_bands.py: plain candle dicts in (time = unix seconds,
closed bars only - the caller drops the still-forming bar), a plain dict
out. Reuses noodle_bands.ema (SMA-seeded), so the slow EMA says nothing
until `slow` bars exist, and its seed fades by (slow - 1) / (slow + 1) per
bar after that: the scan fetches about 700 bars per series
(DOC_TREND_CANDLE_LIMITS in web_portfolio.py), which leaves under 1% of
the seed in EMA 200.
"""
from src.engines.noodle_bands import ema, BULLISH, BEARISH

DOC_TREND_FAST = 100
DOC_TREND_SLOW = 200


def compute_ema_cross(candles, fast=DOC_TREND_FAST, slow=DOC_TREND_SLOW):
    """EMA `fast` and EMA `slow` of the closes, and the latest cross.

    Returns a dict:
      ema_fast, ema_slow  the last bar's two EMAs; None when there are
                          fewer than `slow` bars
      cross_state         BULLISH when the fast EMA is above the slow one,
                          BEARISH when below; a bar where they are exactly
                          equal keeps the side before it (a strict cross,
                          like the noodle's flips). None when there are
                          fewer than `slow` bars or they were never apart
      cross_ts            open time of the first bar on the current side
                          (the bar whose close made the cross), or None
      cross_unbounded     True when the fast EMA has been on this side
                          since the first bar both EMAs exist, so the
                          cross is older than the data (age unknown);
                          False when cross_ts is set; None with no state
    """
    out = {'ema_fast': None, 'ema_slow': None, 'cross_state': None,
           'cross_ts': None, 'cross_unbounded': None}
    closes = [c['close'] for c in candles]
    n = len(closes)
    if fast < 1 or fast >= slow or n < slow:
        return out
    ef = ema(closes, fast)
    es = ema(closes, slow)
    out['ema_fast'], out['ema_slow'] = ef[-1], es[-1]
    side = None       # BULLISH | BEARISH once the EMAs have been apart
    since = None      # index of the first bar on the current side
    crossed = False   # True once the side has changed at least once
    for i in range(slow - 1, n):
        diff = ef[i] - es[i]
        if diff > 0:
            s = BULLISH
        elif diff < 0:
            s = BEARISH
        else:
            continue
        if side is None:
            side, since = s, i
        elif s != side:
            side, since, crossed = s, i, True
    if side is None:
        return out
    out['cross_state'] = side
    out['cross_ts'] = candles[since]['time'] if crossed else None
    out['cross_unbounded'] = not crossed
    return out


DOC_BAND_CLOSES = 2   # Doc band states: two consecutive closes beyond the far edge (Oct 17 / Oct 20 rulings)


def compute_band_state(candles, fast=DOC_TREND_FAST, slow=DOC_TREND_SLOW, closes=DOC_BAND_CLOSES):
    """Doc's band state with the two-close rule (Landing 59; Glenn's Oct 16
    ruling 3 and the Oct 17 / Oct 20 two-close rule).

    The band is the zone between EMA `fast` and EMA `slow` of the closes. It
    is held (BULLISH) after `closes` consecutive closes above its upper edge
    (the higher of the two EMAs) and lost (BEARISH) after `closes`
    consecutive closes below its lower edge; a close inside the zone, or
    fewer consecutive closes beyond an edge, changes nothing. Each bar is
    judged against that bar's own EMAs. Closed bars only (the caller drops
    the still-forming bar).

    Returns a dict:
      state            BULLISH | BEARISH, None until the first run of
                       `closes` closes beyond an edge (or with fewer than
                       `slow` bars)
      state_ts         open time of the bar whose close confirmed the state
                       (the last of the run), or None
      position         where the last close sits: above | inside | below
                       (None with fewer than `slow` bars)
      upper, lower     the last bar's edges (None with fewer than `slow` bars)
      ema_fast, ema_slow, cross_state, cross_ts, cross_unbounded
                       as compute_ema_cross
      bars             how many bars were read
    """
    out = dict(compute_ema_cross(candles, fast=fast, slow=slow))
    out.update(state=None, state_ts=None, position=None, upper=None, lower=None, bars=len(candles))
    closes_list = [c['close'] for c in candles]
    n = len(closes_list)
    if fast < 1 or fast >= slow or n < slow or closes < 1:
        return out
    ef = ema(closes_list, fast)
    es = ema(closes_list, slow)
    state = None
    state_i = None
    run_side, run_len = None, 0
    for i in range(slow - 1, n):
        hi, lo = max(ef[i], es[i]), min(ef[i], es[i])
        c = closes_list[i]
        side = BULLISH if c > hi else BEARISH if c < lo else None
        if side is None:
            run_side, run_len = None, 0
            continue
        run_len = run_len + 1 if side == run_side else 1
        run_side = side
        if run_len >= closes and side != state:
            state, state_i = side, i
    last_hi, last_lo = max(ef[-1], es[-1]), min(ef[-1], es[-1])
    last = closes_list[-1]
    out['upper'], out['lower'] = last_hi, last_lo
    out['position'] = 'above' if last > last_hi else 'below' if last < last_lo else 'inside'
    out['state'] = state
    out['state_ts'] = candles[state_i]['time'] if state_i is not None else None
    return out
