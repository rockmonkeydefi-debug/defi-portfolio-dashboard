"""Respected trend (Doc's "tag") per timeframe - pure engine.

Glenn's rulings (Oct 17, SPEC_respected_trend_test.md): a trend stays intact
until TWO CONSECUTIVE candles close beyond its far edge (a single close
beyond, or a wick through that closes back, is still intact). A respected
TAG, inside the current run: price has been clear of the band, pulls back so
a bar closes inside the band (or beyond it, for one bar), and then makes a
new run high (bullish run) or a new run low (bearish run). The run starts at
the second of the two closes beyond the opposite band. The columns are
informational (watch-list), not entry triggers.

Landing 50b (Oct 18): the run also counts its closes beyond the far edge
(below the lower band in a bullish run, above the upper band in a bearish
one). Under the two-close rule they can never be consecutive, but Glenn does
not want a timeframe listed as respected once its run has two or more of
them; the count is stored so the Trends screen can apply that.

This is NOT the noodle's `state`: that flips on a single strict close and is
left alone. The run here may therefore disagree with `state` for a bar or
two, which is why the direction is stored beside the tag count.

Pure, like noodle_bands.py: plain candle dicts in (time = unix seconds,
closed bars only - the caller drops the still-forming bar), a plain dict
out. Reuses noodle_bands.ema / atr / _compute_bands, so the bands are the
noodle's own.
"""
from src.engines.noodle_bands import ema, atr, _compute_bands, BULLISH, BEARISH

RESPECT_CONFIRM_CLOSES = 2


def compute_respected_trend(candles, slow=28, atr_length=14, band_multiplier=0.011875,
                            use_atr=True, confirm=RESPECT_CONFIRM_CLOSES):
    """The current run's direction and its respected tags.

    Returns a dict:
      dir        BULLISH | BEARISH: the side of the current run, or None
                 when no run has been confirmed (too few bars, or price has
                 never closed beyond a band twice in a row)
      tags       number of respected tags in the current run (0 or more),
                 or None when dir is None
      last_ts    open time of the bar that made the latest tag, or None
      unbounded  True when the current run is the first one the data shows
                 (no earlier flip was seen, so it may have started before
                 the fetched bars and its tag count is a lower bound);
                 False when a flip was seen; None when dir is None
      breaks     number of closes beyond the far edge since the run started
                 (strict: a close on the edge is not beyond it; a wick
                 through that closes back is not counted), or None when dir
                 is None
    """
    out = {'dir': None, 'tags': None, 'last_ts': None, 'unbounded': None, 'breaks': None}
    n = len(candles or [])
    if n == 0 or confirm < 1:
        return out
    closes = [c['close'] for c in candles]
    slow_ema = ema(closes, slow)
    atr_series = atr(candles, atr_length) if use_atr else None
    upper, lower = _compute_bands(slow_ema, atr_series, band_multiplier, use_atr)
    first = next((i for i in range(n) if upper[i] is not None), None)
    if first is None:
        return out
    state = 0                 # 0 none yet, 1 bullish run, -1 bearish run
    above = below = 0         # consecutive closes beyond the upper / lower band
    flips = 0
    # 'clear' -> 'pulled' -> (tag) 'seek' -> 'clear'. A pullback stays noted
    # until a new extreme tags it; after a tag, the next one needs price to
    # get clear of the band again.
    phase = None
    run_hi = run_lo = None
    tags = 0
    last_i = None
    breaks = 0
    for i in range(first, n):
        c = candles[i]
        close = c['close']
        above = above + 1 if close > upper[i] else 0
        below = below + 1 if close < lower[i] else 0
        flip = 0
        if above >= confirm and state != 1:
            flip = 1
        elif below >= confirm and state != -1:
            flip = -1
        if flip:
            state = flip
            flips += 1
            tags, last_i, phase, breaks = 0, None, 'clear', 0
            seg = candles[max(0, i - confirm + 1):i + 1]
            run_hi = max(x['high'] for x in seg)
            run_lo = min(x['low'] for x in seg)
            continue
        if state == 0:
            continue
        # The tag is checked before this bar's own pullback is noted, so the
        # bar that makes the new extreme is never also the pullback bar (a
        # wick that spikes and closes inside the band is a rejection).
        if state == 1:
            if phase == 'pulled' and c['high'] > run_hi:
                tags, last_i, phase = tags + 1, i, 'seek'
            if phase == 'clear' and close <= upper[i]:
                phase = 'pulled'
            if phase == 'seek' and close > upper[i]:
                phase = 'clear'
            run_hi = max(run_hi, c['high'])
            if close < lower[i]:
                breaks += 1
        else:
            if phase == 'pulled' and c['low'] < run_lo:
                tags, last_i, phase = tags + 1, i, 'seek'
            if phase == 'clear' and close >= lower[i]:
                phase = 'pulled'
            if phase == 'seek' and close < lower[i]:
                phase = 'clear'
            run_lo = min(run_lo, c['low'])
            if close > upper[i]:
                breaks += 1
    if state == 0:
        return out
    out['dir'] = BULLISH if state == 1 else BEARISH
    out['tags'] = tags
    out['last_ts'] = candles[last_i]['time'] if last_i is not None else None
    out['unbounded'] = flips == 1
    out['breaks'] = breaks
    return out
