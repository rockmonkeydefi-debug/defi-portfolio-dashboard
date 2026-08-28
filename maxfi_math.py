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


# ── Phase D additions: uncollected-fee math + liquidity->amounts ────────
# Absent before this phase (see Phase D STEP 1 report). Both are raw
# on-chain math — same category as everything above — so they live here,
# not in maxfi_pricing.py. Neither does any decimals adjustment or USD
# conversion; both return raw base-unit quantities. maxfi_pricing.py's
# value_position() is responsible for the decimals division (the "final
# division producing a display value") and the USD multiplication.

MASK_256 = (1 << 256) - 1


def fee_growth_inside(current_tick, tick_lower, tick_upper, fee_growth_global,
                       fee_growth_outside_lower, fee_growth_outside_upper):
    """Standard Uniswap V3 feeGrowthInside formula, for ONE token (call
    once per token with that token's own feeGrowthGlobal/Outside values).

    feeGrowthInside = feeGrowthGlobal - feeGrowthBelow - feeGrowthAbove,
    with feeGrowthBelow/Above selected by where current_tick sits relative
    to [tick_lower, tick_upper) (exactly mirroring Uniswap V3 core's own
    Tick.getFeeGrowthInside branch selection):
      feeGrowthBelow = feeGrowthOutside_lower           if current_tick >= tick_lower
                      = feeGrowthGlobal - feeGrowthOutside_lower   otherwise
      feeGrowthAbove = feeGrowthOutside_upper           if current_tick <  tick_upper
                      = feeGrowthGlobal - feeGrowthOutside_upper   otherwise

    All values are raw X128 fixed-point uint256 accumulators. Underflow in
    these subtractions is EXPECTED and correct (the accumulator wraps
    around uint256 by design) — masked to 2**256-1, never guarded against.
    """
    if current_tick >= tick_lower:
        below = fee_growth_outside_lower & MASK_256
    else:
        below = (fee_growth_global - fee_growth_outside_lower) & MASK_256
    if current_tick < tick_upper:
        above = fee_growth_outside_upper & MASK_256
    else:
        above = (fee_growth_global - fee_growth_outside_upper) & MASK_256
    return (fee_growth_global - below - above) & MASK_256


def uncollected_fees(liquidity, fee_growth_inside_current, fee_growth_inside_last, tokens_owed):
    """uncollected = liquidity * (feeGrowthInside - feeGrowthInsideLast) / 2**128,
    plus the position's already-accrued tokensOwed. Returns a raw base-unit
    integer (not decimals-adjusted) for ONE token — call once per token.

    The (feeGrowthInside - feeGrowthInsideLast) subtraction wraps the same
    way as fee_growth_inside()'s internal subtractions — masked, not guarded.
    """
    delta = (fee_growth_inside_current - fee_growth_inside_last) & MASK_256
    return ((liquidity * delta) >> 128) + tokens_owed


def liquidity_to_amounts(liquidity, tick_lower, tick_upper, current_tick, sqrt_price_x96):
    """Standard Uniswap V3 liquidity->amounts formula. Returns
    (amount0_raw, amount1_raw) in RAW base units (not decimals-adjusted).

    sqrt_price_x96 is the pool's actual current sqrtPriceX96 (exact,
    on-chain integer). The tick-boundary sqrt prices for tick_lower/
    tick_upper have no equivalent on-chain integer available to us, so
    they're derived via 1.0001**(tick/2) in float space — the same
    convention tick_to_price() already uses elsewhere in this module.
    This is not bit-exact with Uniswap's own TickMath library (a
    log-based bit-shift algorithm), but it agrees far beyond what USD
    valuation needs.

    Branch selection mirrors fee_growth_inside()'s tick boundaries exactly
    (current_tick < tick_lower / >= tick_upper / in between), so a
    position priced "at the edge" of its range is treated consistently by
    both functions.
    """
    sqrt_lower = 1.0001 ** (tick_lower / 2)
    sqrt_upper = 1.0001 ** (tick_upper / 2)
    sqrt_current = float(Decimal(sqrt_price_x96) / Q96)

    if current_tick < tick_lower:
        amount0_raw = liquidity * (1 / sqrt_lower - 1 / sqrt_upper)
        amount1_raw = 0.0
    elif current_tick >= tick_upper:
        amount0_raw = 0.0
        amount1_raw = liquidity * (sqrt_upper - sqrt_lower)
    else:
        amount0_raw = liquidity * (1 / sqrt_current - 1 / sqrt_upper)
        amount1_raw = liquidity * (sqrt_current - sqrt_lower)

    return amount0_raw, amount1_raw
