"""Respected trend (Doc's "tag") per timeframe - pure engine.

Landing 51 (Oct 18) rework, Glenn's rulings (SPEC_respected_trend_test.md and
its addendum):

  * The band must be TRENDING for a history to begin. Direction comes from the
    slope of the slow EMA (the band basis): slope = (EMA now - EMA `slope_bars`
    bars ago) / ATR. A history opens when |slope| reaches `slope_enter` and
    closes when it falls to `slope_exit` or below (hysteresis, so a slope that
    wobbles between the two does not flicker). A slope that crosses straight
    to the opposite `slope_enter` starts a new history the other way. While
    the band is flat there is no history and no respected trend.
  * The history is back-dated to where the slope first exceeded `slope_exit`
    in the stretch leading into the entry, and everything (tags, losses, the
    clock) is counted from there. A flat band resets all of it.
  * A TAG is a wick into the band that holds, followed by a new run extreme.
    Bullish: a bar with low <= upper band and close >= lower band (it does
    not have to close inside the band), then a bar whose high beats the
    history's high so far. Bearish is the mirror. After a tag the next one
    needs price to get clear of the band again. Tags are never reset by a
    loss.
  * A LOSS is `confirm` (2) consecutive closes beyond the far edge: one rogue
    close is not acceptance beyond the band. A longer streak counts once.
    Two or more losses in one history mean "not respected" (the frontend
    applies that; one loss is tolerated).

The columns are informational (a watch list), not entry triggers. This is NOT
the noodle's `state`: that flips on a single strict close and is left alone.

Ranging: when the band is flat NOW and the history that just ended was
respected at its end (RESPECT_MIN_TAGS tags, at most RESPECT_MAX_LOSSES
losses, latest tag within RESPECT_WINDOW_BARS bars at its last bar), the open
time of the first flat bar is returned as `ranging_since`, so the Trends
screen can show "Ranging" on that timeframe for a while. Those three
RESPECT_* constants repeat the frontend's pass rule in static/trends.js;
tests/test_trends_respected_wiring.py asserts the two copies agree.

Pure, like noodle_bands.py: plain candle dicts in (time = unix seconds,
closed bars only - the caller drops the still-forming bar), a plain dict
out. Reuses noodle_bands.ema / atr / _compute_bands, so the bands are the
noodle's own.
"""
from src.engines.noodle_bands import ema, atr, _compute_bands, BULLISH, BEARISH

RESPECT_CONFIRM_CLOSES = 2      # consecutive closes beyond the far edge = one loss
RESPECT_SLOPE_BARS = 10         # N: bars the slow EMA change is measured over
RESPECT_SLOPE_ENTER = 0.6       # |slope| (ATR units) that opens a history
RESPECT_SLOPE_EXIT = 0.3        # |slope| at or below which the history ends
RESPECT_MIN_TAGS = 2            # the pass rule, for the Ranging badge only
RESPECT_MAX_LOSSES = 1
RESPECT_WINDOW_BARS = 30


class _History:
    """One sloping stretch of the band: direction, tags, losses, tag phase."""
    __slots__ = ('direction', 'start', 'phase', 'ext', 'tags', 'last_tag', 'streak', 'losses')

    def __init__(self, direction, start):
        self.direction = direction     # 1 bullish, -1 bearish
        self.start = start             # index of the history's first bar
        self.phase = None              # None (no bar yet), 'clear', 'pulled', 'seek'
        self.ext = None                # high (bullish) / low (bearish) so far
        self.tags = 0
        self.last_tag = None           # index of the bar that made the latest tag
        self.streak = 0                # consecutive closes beyond the far edge
        self.losses = 0

    def passes(self, idx):
        """The tab's pass rule as of bar `idx` (bars ago < the window)."""
        return (self.tags >= RESPECT_MIN_TAGS and self.losses <= RESPECT_MAX_LOSSES
                and self.last_tag is not None and idx - self.last_tag < RESPECT_WINDOW_BARS)


def _slope_series(basis, atr_series, bars):
    out = [None] * len(basis)
    for i in range(bars, len(basis)):
        a = atr_series[i]
        if basis[i] is None or basis[i - bars] is None or a is None or not a:
            continue
        out[i] = (basis[i] - basis[i - bars]) / a
    return out


def _feed(h, candles, upper, lower, m, confirm):
    """Take bar `m` into history `h`: loss streak, then the tag phase machine."""
    c = candles[m]
    close, hi, lo = c['close'], c['high'], c['low']
    up, lw = upper[m], lower[m]
    bull = h.direction == 1
    beyond = (close < lw) if bull else (close > up)
    h.streak = h.streak + 1 if beyond else 0
    if h.streak == confirm:                     # counted once per streak
        h.losses += 1
    if h.phase is None:                         # the history's first bar
        h.ext = hi if bull else lo
        h.phase = 'clear' if ((close > up) if bull else (close < lw)) else 'seek'
        return
    # The tag is checked before this bar's own pullback is noted, so the bar
    # that makes the new extreme is never also the pullback bar (a spike that
    # closes back inside the band is a rejection).
    if bull:
        if h.phase == 'pulled' and hi > h.ext:
            h.tags += 1
            h.last_tag = m
            h.phase = 'seek'
        if h.phase == 'clear' and lo <= up and close >= lw:
            h.phase = 'pulled'
        if h.phase == 'seek' and close > up:
            h.phase = 'clear'
        h.ext = max(h.ext, hi)
    else:
        if h.phase == 'pulled' and lo < h.ext:
            h.tags += 1
            h.last_tag = m
            h.phase = 'seek'
        if h.phase == 'clear' and hi >= lw and close <= up:
            h.phase = 'pulled'
        if h.phase == 'seek' and close < lw:
            h.phase = 'clear'
        h.ext = min(h.ext, lo)


def compute_respected_trend(candles, slow=28, atr_length=14, band_multiplier=0.011875,
                            use_atr=True, confirm=RESPECT_CONFIRM_CLOSES,
                            slope_bars=RESPECT_SLOPE_BARS, slope_enter=RESPECT_SLOPE_ENTER,
                            slope_exit=RESPECT_SLOPE_EXIT):
    """The current sloping history's direction, tags, losses and start.

    Returns a dict:
      dir           BULLISH | BEARISH: the side of the band's slope while a
                    history is open at the last bar, else None (the band is
                    flat, or there are too few bars for the slope)
      tags          respected tags in the history, or None when dir is None
      last_ts       open time of the bar that made the latest tag, or None
      unbounded     True when the history reaches the first bar the slope can
                    be measured on (it may have started earlier, so tags and
                    the clock are lower bounds); False otherwise; None when
                    dir is None
      since         open time of the history's first bar (back-dated to where
                    the slope first exceeded slope_exit), or None
      losses        episodes of `confirm` consecutive closes beyond the far
                    edge in the history, or None when dir is None
      ranging_since open time of the first flat bar, only when the band is
                    flat at the last bar and the history that just ended was
                    respected at its end; else None
    """
    out = {'dir': None, 'tags': None, 'last_ts': None, 'unbounded': None,
           'since': None, 'losses': None, 'ranging_since': None}
    n = len(candles or [])
    if n == 0 or confirm < 1 or slope_bars < 1:
        return out
    closes = [c['close'] for c in candles]
    slow_ema = ema(closes, slow)
    atr_series = atr(candles, atr_length)
    upper, lower = _compute_bands(slow_ema, atr_series if use_atr else None, band_multiplier, use_atr)
    slope = _slope_series(slow_ema, atr_series, slope_bars)
    first = next((i for i in range(n) if slope[i] is not None and upper[i] is not None), None)
    if first is None:
        return out

    def back(i, d):
        j = i
        while j - 1 >= first and slope[j - 1] is not None and d * slope[j - 1] > slope_exit:
            j -= 1
        return j

    def open_history(i, d):
        st = back(i, d)
        h = _History(d, st)
        for m in range(st, i + 1):
            _feed(h, candles, upper, lower, m, confirm)
        return h

    d, hist = 0, None
    ended_ok = False          # did the history that last ended (flat) pass at its end?
    flat_i = None             # index of the first flat bar after it
    for i in range(first, n):
        s = slope[i]
        if s is None or upper[i] is None:        # slope cannot be measured here: no history
            d, hist, ended_ok, flat_i = 0, None, False, None
            continue
        if d == 0:
            if s >= slope_enter:
                d = 1
            elif s <= -slope_enter:
                d = -1
            if d:
                hist = open_history(i, d)
                ended_ok, flat_i = False, None
        elif d == 1:
            if s <= -slope_enter:                # straight to a bearish slope
                d = -1
                hist = open_history(i, d)
            elif s <= slope_exit:                # the band went flat
                ended_ok, flat_i = hist.passes(i - 1), i
                d, hist = 0, None
            else:
                _feed(hist, candles, upper, lower, i, confirm)
        else:
            if s >= slope_enter:
                d = 1
                hist = open_history(i, d)
            elif s >= -slope_exit:
                ended_ok, flat_i = hist.passes(i - 1), i
                d, hist = 0, None
            else:
                _feed(hist, candles, upper, lower, i, confirm)

    if d == 0:
        if ended_ok and flat_i is not None:
            out['ranging_since'] = candles[flat_i]['time']
        return out
    out['dir'] = BULLISH if d == 1 else BEARISH
    out['tags'] = hist.tags
    out['last_ts'] = candles[hist.last_tag]['time'] if hist.last_tag is not None else None
    out['unbounded'] = hist.start == first
    out['since'] = candles[hist.start]['time']
    out['losses'] = hist.losses
    return out
