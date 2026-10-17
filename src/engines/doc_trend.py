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
