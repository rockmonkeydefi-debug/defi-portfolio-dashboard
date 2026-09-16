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
    assert result == {
        'state': 'WARMUP', 'flip_ts': None, 'flip_price': None,
        'flip_age_unbounded': None,
        'alignment_bull': None, 'alignment_bear': None,
        'basis_ema': None, 'upper_band': None, 'lower_band': None,
    }


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
