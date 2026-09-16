"""Noodle bands (MA-band trend indicator) — pure signal engine.

Ports the TradingView "RM Money Noodle v3" indicator (a Wilder-ATR band
around a slow EMA, with hysteretic trend state) for the Hyperliquid perp
universe. See HANDOFF_ma_band_scanner.md for the full design/spec this
module implements — the Indicator spec and Locked-architecture point 1
sections in particular. This docstring covers only the mechanics.

Pure module, same precedent as cascade_composer.py: no Flask, no SQLite, no
network, no import from web_portfolio.py. Every function takes plain candle
dicts (the exact shape web_portfolio.py's _hl_fetch_candles returns —
open/high/low/close/volume/time, time = unix seconds) or plain numeric
lists, and returns plain dicts/lists — unit-testable in isolation.

Deliberately NOT reusing web_portfolio.py's _ict_atr (a plain mean-of-
true-range, i.e. an SMA — it will not match TradingView's ta.atr) or
_ict_ema20 (hardcoded to a 20-period seed). ema()/rma()/atr() below are
fresh, generic implementations built to match Pine's ta.ema/ta.rma/ta.atr
methods.

Known, accepted drift source (documented in the handoff doc — not a bug to
"fix" here): Pine's ta.ema/ta.atr are computed from a symbol's entire
on-chart history. This module only ever sees the fetched candle window, so
its SMA-seeded EMA/RMA converges toward TradingView's own value as the
window grows, but will not reproduce it exactly on a short window. The
parity harness (deferred until real TradingView captures are supplied) is
what actually measures this drift — nothing here should be tuned to
"fix" it by guessing at TradingView's numbers.
"""

BULLISH = 'BULLISH'
BEARISH = 'BEARISH'
WARMUP = 'WARMUP'


def ema(values, period):
    """Standard EMA over a plain list of numbers (e.g. closes).

    Returns a list the same length as `values`: the first `period - 1`
    entries are None (not enough bars yet), the entry at index `period - 1`
    seeds as the SMA of `values[:period]`, and every entry after that
    recurses with alpha = 2 / (period + 1).

    This is an SMA-seeded EMA, not a from-inception EMA — see the module
    docstring's note on TradingView convergence drift.
    """
    n = len(values)
    out = [None] * n
    if period < 1 or n < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    alpha = 2.0 / (period + 1)
    prev = seed
    for i in range(period, n):
        prev = values[i] * alpha + prev * (1.0 - alpha)
        out[i] = prev
    return out


def rma(values, period):
    """Wilder/RMA smoothing over a plain list of numbers.

    `values` may begin with a leading run of None (e.g. a true-range series
    has no defined value at index 0 — there is no previous close to diff
    against there); everything from the first non-None entry onward must be
    a real number. Returns a list the same length as `values`: None until
    `period` values have been collected to seed from (seeded as their SMA),
    then rma[i] = (rma[i-1] * (period - 1) + values[i]) / period.

    This is Wilder's smoothing exactly as Pine's ta.rma/ta.atr perform it —
    NOT the plain simple-moving-average that web_portfolio.py's _ict_atr
    computes over true range. Do not substitute one for the other.
    """
    n = len(values)
    out = [None] * n
    start = 0
    while start < n and values[start] is None:
        start += 1
    seed_end = start + period
    if period < 1 or seed_end > n:
        return out
    seed = sum(values[start:seed_end]) / period
    out[seed_end - 1] = seed
    prev = seed
    for i in range(seed_end, n):
        prev = (prev * (period - 1) + values[i]) / period
        out[i] = prev
    return out


def _true_range(candles):
    """True range per bar, aligned to `candles`. Index 0 is always None (no
    previous close to compare against) — same convention as
    web_portfolio.py's _ict_atr, which likewise starts its walk at index 1.
    """
    n = len(candles)
    out = [None] * n
    for i in range(1, n):
        h = candles[i]['high']
        l = candles[i]['low']
        pc = candles[i - 1]['close']
        out[i] = max(h - l, abs(h - pc), abs(l - pc))
    return out


def atr(candles, period):
    """Wilder ATR: RMA of the true-range series, aligned to `candles`."""
    return rma(_true_range(candles), period)


def _compute_bands(ema_s, atr_series, band_multiplier, use_atr):
    """Upper/lower band per bar, aligned to `ema_s`. None until both the
    slow EMA and (when use_atr) the ATR are defined at that index.

    offset = atr * band_multiplier * 40          (use_atr)
           = slow_ema * band_multiplier           (otherwise)
    The *40 constant is a documented quirk of the source Pine script —
    replicated literally, not a tunable.
    """
    n = len(ema_s)
    upper = [None] * n
    lower = [None] * n
    for i in range(n):
        s = ema_s[i]
        if s is None:
            continue
        if use_atr:
            a = atr_series[i] if atr_series is not None else None
            if a is None:
                continue
            offset = a * band_multiplier * 40
        else:
            offset = s * band_multiplier
        upper[i] = s + offset
        lower[i] = s - offset
    return upper, lower


def compute_noodle_state(candles, fast=12, medium=21, slow=25, atr_length=20,
                          band_multiplier=0.01, use_atr=True):
    """Compute the noodle trend state for ONE (symbol, timeframe) candle
    series. Pure function of `candles`; no mutation, no I/O.

    Canonical parameters (Glenn's live TradingView settings, not script
    defaults) are the function's own defaults; every one is overridable by
    the caller, never hardcoded elsewhere in this module.

    State is HYSTERETIC across the whole window: a strict cross of close
    over the upper band (crossover) or under the lower band (crossunder)
    flips the state, and that state persists — including through a return
    to inside the band — until the next real cross. "Strict" means the
    prior bar must have been on the other side: crossover requires
    prev_close <= prev_upper AND cur_close > cur_upper (crossunder mirrors
    this against the lower band); merely touching a band without having
    been on the other side first is not a flip.

    Returns a dict:
      state              BULLISH | BEARISH | WARMUP
      flip_ts            epoch seconds of the most recent flip's bar, or
                          None
      flip_price         that bar's close, or None
      flip_age_unbounded True iff no cross exists anywhere in the fetched
                          window but the last close sits outside the band
                          (so a real flip almost certainly happened before
                          the window started — age is unknown, not zero).
                          None when there isn't enough history to say
                          anything at all (see below).
      alignment_bull     0-3: count of (ema_f>ema_m), (ema_f>ema_s),
                          (ema_m>ema_s) true, at the final bar
      alignment_bear     0-3: the same three comparisons, each mirrored
      basis_ema          final-bar slow EMA
      upper_band         final-bar upper band
      lower_band         final-bar lower band

    Three outcomes for `state`:
      - Fewer bars than needed for ema_f/ema_m/the band (ema_s + ATR when
        use_atr) to be defined at all: WARMUP, and every other field is
        None. Never raises on a short (or empty) candle list.
      - Enough history exists, and either a cross was found in-window (state
        = direction of the MOST RECENT one) or the last close sits outside
        the band with no in-window cross (state = that side,
        flip_age_unbounded=True, flip_ts/flip_price=None) — basis_ema/
        upper_band/lower_band/alignment_* are always real numbers here.
      - Enough history exists, no cross was found, and the last close sits
        inside the band: WARMUP, but (unlike the too-short case above)
        basis_ema/upper_band/lower_band/alignment_* are real numbers and
        flip_age_unbounded is False — this is "nothing to report", not
        "can't compute".
    """
    candles = candles or []
    n = len(candles)
    closes = [c['close'] for c in candles]

    ema_f = ema(closes, fast)
    ema_m = ema(closes, medium)
    ema_s = ema(closes, slow)
    atr_series = atr(candles, atr_length) if use_atr else None
    upper, lower = _compute_bands(ema_s, atr_series, band_multiplier, use_atr)

    first_idx = None
    for i in range(n):
        if ema_f[i] is not None and ema_m[i] is not None and upper[i] is not None:
            first_idx = i
            break

    if first_idx is None:
        return {
            'state': WARMUP, 'flip_ts': None, 'flip_price': None,
            'flip_age_unbounded': None,
            'alignment_bull': None, 'alignment_bear': None,
            'basis_ema': None, 'upper_band': None, 'lower_band': None,
        }

    # Strict-cross walk, oldest to newest bar — the LAST flip found wins,
    # which is what makes this hysteretic rather than a per-bar state.
    flip_state = None
    flip_ts = None
    flip_price = None
    for i in range(first_idx + 1, n):
        prev_close, cur_close = closes[i - 1], closes[i]
        prev_upper, cur_upper = upper[i - 1], upper[i]
        prev_lower, cur_lower = lower[i - 1], lower[i]
        if prev_close <= prev_upper and cur_close > cur_upper:
            flip_state, flip_ts, flip_price = BULLISH, candles[i]['time'], cur_close
        elif prev_close >= prev_lower and cur_close < cur_lower:
            flip_state, flip_ts, flip_price = BEARISH, candles[i]['time'], cur_close

    last = n - 1
    if flip_state is not None:
        state = flip_state
        flip_age_unbounded = False
    else:
        if closes[last] > upper[last]:
            state, flip_age_unbounded = BULLISH, True
        elif closes[last] < lower[last]:
            state, flip_age_unbounded = BEARISH, True
        else:
            state, flip_age_unbounded = WARMUP, False
        flip_ts, flip_price = None, None

    ef, em_, es = ema_f[last], ema_m[last], ema_s[last]
    alignment_bull = int(ef > em_) + int(ef > es) + int(em_ > es)
    alignment_bear = int(ef < em_) + int(ef < es) + int(em_ < es)

    return {
        'state': state, 'flip_ts': flip_ts, 'flip_price': flip_price,
        'flip_age_unbounded': flip_age_unbounded,
        'alignment_bull': alignment_bull, 'alignment_bear': alignment_bear,
        'basis_ema': es, 'upper_band': upper[last], 'lower_band': lower[last],
    }
