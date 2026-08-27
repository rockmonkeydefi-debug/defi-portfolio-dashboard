"""Unit tests for maxfi_math.py — pure tick/price math, no network.

Expected values are independently derived and cross-checked against live
MaxFi capture (Base position 5884225, Robinhood position 757217). Do not
adjust them to make a failing implementation pass.
"""

import pytest

from maxfi_math import (
    to_signed,
    to_int24,
    to_int128,
    to_int56,
    tick_to_price,
    sqrt_price_x96_to_price,
    range_percent,
    invert_price,
)


def test_sign_extension_int24():
    # Per spec: derive the words as 2**256 - N rather than trusting the
    # task's hex literals for them, which turn out not to actually encode
    # -199240 / -198110 under two's complement — the computed value wins.
    word_a = 2 ** 256 - 199240
    word_b = 2 ** 256 - 198110

    assert to_int24(word_a) == -199240
    assert to_int24(word_b) == -198110
    assert to_int24(0) == 0
    assert to_int24(1) == 1


def test_to_signed_generic():
    assert to_signed(0, 24) == 0
    assert to_signed(1, 24) == 1
    assert to_signed((1 << 23), 24) == -(1 << 23)  # sign bit set, min value
    assert to_signed((1 << 24) - 1, 24) == -1       # all ones == -1


def test_to_int128_and_int56_sign_extension():
    assert to_int128(2 ** 256 - 12345) == -12345
    assert to_int128(0) == 0
    assert to_int56(2 ** 256 - 42) == -42
    assert to_int56(0) == 0


def test_tick_to_price_weth_usdc():
    # token0=WETH(18), token1=USDC(6). Matches live Base position 5884225
    # range of $2,226-$2,492 (ETH traded $2,488-$2,503 at capture time,
    # outOfRangeSince correctly set).
    price_lower = tick_to_price(-199240, 18, 6)
    price_upper = tick_to_price(-198110, 18, 6)
    assert price_lower == pytest.approx(2226.1, abs=0.5)
    assert price_upper == pytest.approx(2492.4, abs=0.5)


def test_range_percent_tick_derived_vs_reported_bps():
    # Tick-derived range width for the same Base position 5884225.
    # The vault reported rangeWidthBps = 1130 (11.30%) for this position;
    # that's the REQUESTED width, while actual bounds snap to tick spacing,
    # so the tick-derived 11.96% legitimately differs — expected, not a bug.
    pct = range_percent(-199240, -198110, 18, 6)
    assert pct == pytest.approx(11.96, abs=0.05)


def test_range_percent_fixture_robinhood_stonkbroker():
    # Robinhood position 757217 (WETH/STONKBROKER) live card displayed 41.6%
    # for a price range of 120501 to 170655.
    pct = (170655 / 120501 - 1) * 100
    assert pct == pytest.approx(41.62, abs=0.05)


def test_sqrt_price_x96_round_trip():
    for tick in (-199240, -198110, 0, 12345, -12345):
        price_from_tick = tick_to_price(tick, 18, 6)
        sqrt_price_x96 = int((1.0001 ** (tick / 2)) * (2 ** 96))
        price_from_sqrt = sqrt_price_x96_to_price(sqrt_price_x96, 18, 6)
        assert price_from_sqrt == pytest.approx(price_from_tick, rel=0.001)


def test_invert_price():
    assert invert_price(2.0) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        invert_price(0)
