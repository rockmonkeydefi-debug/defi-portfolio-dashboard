"""Noodle bands unit tests (Commit 1, engine half) — pure logic, no network,
no DB. No TradingView numbers appear anywhere in this file: the parity
harness against real TradingView captures is explicitly deferred until
those captures are supplied (see HANDOFF_ma_band_scanner.md) and is NOT
implemented here.

Every "expected" value below is computed by an independent reference
calculation written directly in this file (by hand, in the test itself) —
never by calling src.engines.noodle_bands's own ema()/rma()/atr()/
compute_noodle_state to verify themselves.
"""
import pytest

from src.engines.noodle_bands import ema, atr, compute_noodle_state

HOUR = 3600
T0 = 1_700_000_000


def _c(i, o, h, l, c, v=1.0):
    return {'open': o, 'high': h, 'low': l, 'close': c, 'volume': v,
            'time': T0 + i * HOUR}


def _flat(closes):
    """Candles with open=high=low=close. Fine for any test that never
    touches ATR (use_atr=False)."""
    return [_c(i, p, p, p, p) for i, p in enumerate(closes)]


# ── ema() / atr() numeric correctness ───────────────────────────────────
def test_ema_matches_hand_computed_sma_seeded_recurrence():
    # period=3, alpha=2/(3+1)=0.5 exactly -> clean fractions, no rounding.
    closes = [1, 2, 3, 4, 5]
    result = ema(closes, 3)
    # index2 seed = mean(1,2,3) = 2.0
    # index3 = 4*0.5 + 2.0*0.5 = 3.0
    # index4 = 5*0.5 + 3.0*0.5 = 4.0
    assert result == [None, None, 2.0, 3.0, 4.0]


def test_ema_returns_all_none_when_shorter_than_period():
    assert ema([1, 2], 3) == [None, None]


def test_atr_matches_hand_computed_wilder_rma_of_true_range():
    candles = [
        _c(0, 10, 11, 9, 10),
        _c(1, 10, 12, 10, 11),   # TR = max(2, |12-10|=2, |10-10|=0) = 2
        _c(2, 11, 14, 12, 13),   # TR = max(2, |14-11|=3, |12-11|=1) = 3
        _c(3, 13, 15, 13, 14),   # TR = max(2, |15-13|=2, |13-13|=0) = 2
        _c(4, 14, 17, 14, 16),   # TR = max(3, |17-14|=3, |14-14|=0) = 3
    ]
    result = atr(candles, 3)
    # TR series (index 0 undefined): [None, 2, 3, 2, 3]
    # seed (index 3) = mean(2,3,2) = 7/3
    # index4 = (7/3 * 2 + 3) / 3 = 23/9
    assert result[0] is None
    assert result[1] is None
    assert result[2] is None
    assert result[3] == pytest.approx(7 / 3)
    assert result[4] == pytest.approx(23 / 9)


# ── signal flips ─────────────────────────────────────────────────────────
# All of these use small overridden periods and use_atr=False (offset =
# slow_ema * band_multiplier) so the fixtures stay short and hand-checkable;
# compute_noodle_state's own defaults are exercised for real once real HL
# candles flow through it in Commit 2 — this file only proves the mechanics.

def test_bullish_flip_on_strict_cross_above_upper_band():
    closes = [100, 100, 100, 100, 130]
    candles = _flat(closes)
    result = compute_noodle_state(candles, fast=2, medium=3, slow=3,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['state'] == 'BULLISH'
    assert result['flip_ts'] == candles[4]['time']
    assert result['flip_price'] == 130
    assert result['flip_age_unbounded'] is False


def test_bearish_flip_on_strict_cross_below_lower_band():
    closes = [100, 100, 100, 100, 70]
    candles = _flat(closes)
    result = compute_noodle_state(candles, fast=2, medium=3, slow=3,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['state'] == 'BEARISH'
    assert result['flip_ts'] == candles[4]['time']
    assert result['flip_price'] == 70
    assert result['flip_age_unbounded'] is False


def test_hysteresis_state_persists_after_return_inside_band():
    # Same bullish flip as above, plus one more bar (close=105) back inside
    # the band. No new cross -> state must still read the bar-4 flip, with
    # the SAME flip_ts/flip_price (not the last bar's).
    closes = [100, 100, 100, 100, 130, 105]
    candles = _flat(closes)
    result = compute_noodle_state(candles, fast=2, medium=3, slow=3,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['state'] == 'BULLISH'
    assert result['flip_ts'] == candles[4]['time']
    assert result['flip_price'] == 130
    assert result['flip_age_unbounded'] is False


def test_warmup_when_history_shorter_than_slow_ema_needs():
    candles = _flat([100, 101])   # only 2 bars; slow=3 needs 3 to seed
    result = compute_noodle_state(candles, fast=2, medium=3, slow=3,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    # Per-key checks (not a whole-dict == literal) so this test doesn't
    # have to be touched every time an additive key is appended to the
    # return dict elsewhere in Commit-1-of-the-Trends-restyle work - it
    # still pins every one of these 9 original values exactly as before.
    assert result['state'] == 'WARMUP'
    assert result['flip_ts'] is None
    assert result['flip_price'] is None
    assert result['flip_age_unbounded'] is None
    assert result['alignment_bull'] is None
    assert result['alignment_bear'] is None
    assert result['basis_ema'] is None
    assert result['upper_band'] is None
    assert result['lower_band'] is None
    # Additive alignment keys (Trends-restyle Commit 1): undefined right
    # alongside everything else when there isn't enough history to say
    # anything at all.
    assert result['alignment_state'] is None
    assert result['alignment_prev_state'] is None
    assert result['alignment_changed_ts'] is None
    assert result['alignment_changed_unbounded'] is None


def test_compute_noodle_state_does_not_raise_on_empty_candles():
    result = compute_noodle_state([], fast=2, medium=3, slow=3,
                                   atr_length=3, use_atr=False)
    assert result['state'] == 'WARMUP'
    assert result['basis_ema'] is None


def test_warmup_when_inside_band_with_no_locatable_flip():
    # Flat series: enough history to compute the band, but price never
    # leaves it and never crosses it.
    closes = [100, 100, 100, 100, 100]
    candles = _flat(closes)
    result = compute_noodle_state(candles, fast=2, medium=3, slow=3,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['state'] == 'WARMUP'
    assert result['flip_ts'] is None
    assert result['flip_price'] is None
    assert result['flip_age_unbounded'] is False
    # Unlike the too-short-history case above, real snapshot values exist.
    assert result['basis_ema'] == 100.0
    assert result['upper_band'] == pytest.approx(110.0)
    assert result['lower_band'] == pytest.approx(90.0)


def test_flip_age_unbounded_when_outside_band_with_no_cross_in_window():
    # Price jumps far above the band on bar 1 and stays there for the rest
    # of the (short) window - by the time the band is even defined (index
    # 2), price is already outside it, so no crossover event exists to
    # find, yet the final bar is still outside the band.
    closes = [100, 300, 300, 300]
    candles = _flat(closes)
    result = compute_noodle_state(candles, fast=2, medium=3, slow=3,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['state'] == 'BULLISH'
    assert result['flip_ts'] is None
    assert result['flip_price'] is None
    assert result['flip_age_unbounded'] is True


# ── alignment score ──────────────────────────────────────────────────────
def test_alignment_score_full_bullish_stack():
    # Hand-checked: ema_f(2)=75, ema_m(3)=70, ema_s(4)=65 at the final bar
    # -> ema_f>ema_m>ema_s on every pairing.
    closes = [10, 20, 30, 40, 50, 60, 70, 80]
    candles = _flat(closes)
    result = compute_noodle_state(candles, fast=2, medium=3, slow=4,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['alignment_bull'] == 3
    assert result['alignment_bear'] == 0


def test_alignment_score_full_bearish_stack():
    # Mirror image of the bullish-stack fixture: ema_f(2)=15, ema_m(3)=20,
    # ema_s(4)=25 at the final bar -> ema_f<ema_m<ema_s on every pairing.
    closes = [80, 70, 60, 50, 40, 30, 20, 10]
    candles = _flat(closes)
    result = compute_noodle_state(candles, fast=2, medium=3, slow=4,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['alignment_bull'] == 0
    assert result['alignment_bear'] == 3


# ── alignment_state 3-state mapping + walk-back (Trends-restyle Commit 1) ─
# Full-stack-only mapping (ruling 4): BULLISH iff alignment_bull==3,
# BEARISH iff alignment_bear==3, NEUTRAL otherwise (2-1/1-2/ties).

def test_alignment_state_bullish_on_full_bullish_stack():
    # Same fixture/hand-check as test_alignment_score_full_bullish_stack:
    # ema_f(2)=75, ema_m(3)=70, ema_s(4)=65 at the final bar -> 3-0.
    closes = [10, 20, 30, 40, 50, 60, 70, 80]
    candles = _flat(closes)
    result = compute_noodle_state(candles, fast=2, medium=3, slow=4,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['alignment_state'] == 'BULLISH'


def test_alignment_state_bearish_on_full_bearish_stack():
    # Same fixture/hand-check as test_alignment_score_full_bearish_stack:
    # ema_f(2)=15, ema_m(3)=20, ema_s(4)=25 at the final bar -> 0-3.
    closes = [80, 70, 60, 50, 40, 30, 20, 10]
    candles = _flat(closes)
    result = compute_noodle_state(candles, fast=2, medium=3, slow=4,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['alignment_state'] == 'BEARISH'


def test_alignment_state_neutral_on_2_1_split():
    # Hand-checked (fast=2/medium=3/slow=4) at the final bar (index 4):
    # ema_f=23.074, ema_m=22.333, ema_s=22.6 -> ema_f > ema_s > ema_m.
    # bull = (ef>em)+(ef>es)+(em>es) = 1+1+0 = 2; bear = 0+0+1 = 1.
    # Neither is 3 -> NEUTRAL (a 2-1 split, EMAs not cleanly stacked).
    closes = [10, 20, 40, 22, 22]
    candles = _flat(closes)
    result = compute_noodle_state(candles, fast=2, medium=3, slow=4,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['alignment_bull'] == 2
    assert result['alignment_bear'] == 1
    assert result['alignment_state'] == 'NEUTRAL'


def test_alignment_state_neutral_on_1_2_split():
    # Hand-checked (fast=2/medium=3/slow=4) at the final bar (index 4):
    # ema_f=21.296, ema_m=20.833, ema_s=21.5 -> ema_s > ema_f > ema_m.
    # bull = (ef>em)+(ef>es)+(em>es) = 1+0+0 = 1; bear = 0+1+1 = 2.
    # Neither is 3 -> NEUTRAL (a 1-2 split).
    closes = [10, 20, 40, 20, 20]
    candles = _flat(closes)
    result = compute_noodle_state(candles, fast=2, medium=3, slow=4,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['alignment_bull'] == 1
    assert result['alignment_bear'] == 2
    assert result['alignment_state'] == 'NEUTRAL'


def test_alignment_walk_back_locates_the_prior_differing_state():
    # Hand-checked (fast=2/medium=3/slow=4), per-bar alignment across the
    # evaluable window (first_idx=3 .. last=8):
    #   idx3: ef=25,     em=30, es=35    -> es>em>ef   -> BEARISH (3-0)
    #   idx4: ef=15,     em=20, es=25    -> es>em>ef   -> BEARISH
    #   idx5: ef=18.333, em=20, es=23    -> es>em>ef   -> BEARISH
    #   idx6: ef=32.778, em=30, es=29.8  -> ef>em>es   -> BULLISH  <- flips here
    #   idx7: ef=57.593, em=50, es=45.88 -> ef>em>es   -> BULLISH
    #   idx8: ef=85.864, em=75, es=67.528-> ef>em>es   -> BULLISH  (final bar)
    # Walking back from idx7: idx7/idx6 match the final BULLISH state;
    # idx5 is the first differing (BEARISH) bar -> the current run's first
    # bar is idx6, one after it.
    closes = [50, 40, 30, 20, 10, 20, 40, 70, 100]
    candles = _flat(closes)
    result = compute_noodle_state(candles, fast=2, medium=3, slow=4,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['alignment_state'] == 'BULLISH'
    assert result['alignment_prev_state'] == 'BEARISH'
    assert result['alignment_changed_ts'] == candles[6]['time']
    assert result['alignment_changed_unbounded'] is False


def test_alignment_changed_unbounded_when_state_constant_across_window():
    # Same fixture as test_alignment_state_bullish_on_full_bullish_stack:
    # this series is fully bullish-stacked (3-0) from first_idx=3 all the
    # way to the final bar - no differing bar exists anywhere in the
    # evaluable window, so the change predates the window (unbounded).
    closes = [10, 20, 30, 40, 50, 60, 70, 80]
    candles = _flat(closes)
    result = compute_noodle_state(candles, fast=2, medium=3, slow=4,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['alignment_state'] == 'BULLISH'
    assert result['alignment_prev_state'] is None
    assert result['alignment_changed_unbounded'] is True


def test_alignment_single_bar_window_is_the_unbounded_boundary_case():
    # Exactly 4 candles with slow=4 -> first_idx == last == 3: the
    # evaluable window is exactly ONE bar, so the walk-back loop has
    # nothing to iterate over. Documented assumption (not explicitly
    # named in HANDOFF_trends_restyle.md): this degenerates cleanly into
    # the unbounded case, the same as a window with no differing bar.
    closes = [10, 20, 30, 40]
    candles = _flat(closes)
    result = compute_noodle_state(candles, fast=2, medium=3, slow=4,
                                   atr_length=3, band_multiplier=0.1,
                                   use_atr=False)
    assert result['alignment_state'] == 'BULLISH'
    assert result['alignment_prev_state'] is None
    assert result['alignment_changed_ts'] == candles[3]['time']
    assert result['alignment_changed_unbounded'] is True
