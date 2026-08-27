"""Pure tick/price math for MaxFi LP diagnostics — no network, no imports
from web_portfolio.py. Kept side-effect-free so it's testable in a sandbox
with no RPC egress (see tests/test_maxfi_math.py).
"""

from decimal import Decimal

Q96 = Decimal(2) ** 96


def to_signed(word_int, bits):
    """Two's-complement sign extension of the low `bits` bits of word_int.

    word_int may be the raw sub-word value or a full 256-bit word already
    sign-extended by the EVM — masking to the low `bits` bits first makes
    both representations decode identically.
    """
    mask = (1 << bits) - 1
    value = word_int & mask
    sign_bit = 1 << (bits - 1)
    if value & sign_bit:
        value -= (1 << bits)
    return value


def to_int24(word_int):
    return to_signed(word_int, 24)


def to_int128(word_int):
    return to_signed(word_int, 128)


def to_int56(word_int):
    return to_signed(word_int, 56)


def tick_to_price(tick, decimals0, decimals1):
    """token1-per-token0 price at `tick`, adjusted for token decimals."""
    return (1.0001 ** tick) * (10 ** (decimals0 - decimals1))


def sqrt_price_x96_to_price(sqrt_price_x96, decimals0, decimals1):
    """token1-per-token0 price from a slot0 sqrtPriceX96 fixed-point value.

    Uses Decimal throughout so squaring happens before any float cast —
    casting sqrt_price_x96 to float first loses precision for realistic
    on-chain magnitudes (~2^96..2^160).
    """
    ratio = Decimal(sqrt_price_x96) / Q96
    price = (ratio * ratio) * (Decimal(10) ** (decimals0 - decimals1))
    return float(price)


def range_percent(tick_lower, tick_upper, decimals0, decimals1):
    """Percent width of a [tick_lower, tick_upper] range, tick-derived."""
    price_lower = tick_to_price(tick_lower, decimals0, decimals1)
    price_upper = tick_to_price(tick_upper, decimals0, decimals1)
    return (price_upper / price_lower - 1) * 100


def invert_price(price):
    """1 / price, guarded against division by zero."""
    if price == 0:
        raise ValueError("cannot invert a zero price")
    return 1.0 / price
