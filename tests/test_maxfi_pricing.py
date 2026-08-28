"""Tests for maxfi_pricing.py (pure valuation math) and
maxfi_anchor_prices.py (anchor USD resolver). Offline, no network, no
database — maxfi_pricing.py takes everything as arguments, and the
anchor resolver tests inject a stub fetcher.
"""

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

import maxfi_anchor_prices as ap
import maxfi_math as mm
import maxfi_pricing as mp

@pytest.fixture(autouse=True)
def _clear_anchor_price_cache():
    """maxfi_anchor_prices keeps a module-level in-memory cache by design
    (mirrors the real resolver's own persistence across requests) - clear
    it before each test so tests are independent of execution order and
    don't rely on well-separated `now` values to avoid collisions."""
    ap._price_cache.clear()
    yield
    ap._price_cache.clear()


Q96 = 2 ** 96


def tick_to_sqrt_price_x96(tick):
    return int((1.0001 ** (tick / 2)) * Q96)


def price_to_tick(price_decimal_adjusted, decimals0, decimals1):
    raw_price = price_decimal_adjusted / (10 ** (decimals0 - decimals1))
    return math.log(raw_price) / math.log(1.0001)


# ── Frozen #757217 fixture ────────────────────────────────────────────────
#
# There is no raw sqrtPriceX96/decoded state actually captured and stored
# in this repo for Robinhood position #757217 (WETH/STONKBROKER) — Phase A's
# own test suite (tests/test_maxfi_math.py) only recorded the DERIVED price
# range the live maxfi.tech card displayed for it: 120501 to 170655, with a
# reported 41.6% range width. There are no raw_words to "locate" for this
# position; none were ever captured. This fixture is RECONSTRUCTED from
# those two known reference numbers, the same way Phase A's own
# sqrt_price_x96_to_price round-trip test built a synthetic sqrtPriceX96
# from a chosen tick rather than pretending to have genuine on-chain hex.
# decimals0=decimals1=18 is an assumption (STONKBROKER's real decimals were
# never independently confirmed anywhere in this repo) — flagged here and
# in the Phase D summary, not silently assumed.
_POS_757217_PRICE_LOWER = 120501.0
_POS_757217_PRICE_UPPER = 170655.0
_POS_757217_DECIMALS0 = 18
_POS_757217_DECIMALS1 = 18


def test_pool_price_token1_per_token0_against_757217_fixture():
    # Pick a current price inside the known range and build a
    # self-consistent sqrtPriceX96 for it (same construction method as
    # Phase A's own round-trip test), then confirm the function recovers it.
    current_price = (_POS_757217_PRICE_LOWER * _POS_757217_PRICE_UPPER) ** 0.5  # geometric mean
    tick = round(price_to_tick(current_price, _POS_757217_DECIMALS0, _POS_757217_DECIMALS1))
    sqrt_price_x96 = tick_to_sqrt_price_x96(tick)

    recovered = mp.pool_price_token1_per_token0(sqrt_price_x96, _POS_757217_DECIMALS0, _POS_757217_DECIMALS1)

    # tick rounding introduces a tiny, expected discrepancy from the exact
    # geometric-mean price - within 0.1% is the same tolerance Phase A's
    # own round-trip test used for the equivalent construction.
    assert recovered == pytest.approx(current_price, rel=0.001)
    assert _POS_757217_PRICE_LOWER < recovered < _POS_757217_PRICE_UPPER


def test_pool_price_token1_per_token0_range_matches_reported_bounds():
    # The range bounds themselves should also round-trip through the same
    # tick construction, confirming the fixture's internal consistency.
    tick_lower = round(price_to_tick(_POS_757217_PRICE_LOWER, _POS_757217_DECIMALS0, _POS_757217_DECIMALS1))
    tick_upper = round(price_to_tick(_POS_757217_PRICE_UPPER, _POS_757217_DECIMALS0, _POS_757217_DECIMALS1))
    price_lower = mp.pool_price_token1_per_token0(
        tick_to_sqrt_price_x96(tick_lower), _POS_757217_DECIMALS0, _POS_757217_DECIMALS1
    )
    price_upper = mp.pool_price_token1_per_token0(
        tick_to_sqrt_price_x96(tick_upper), _POS_757217_DECIMALS0, _POS_757217_DECIMALS1
    )
    assert price_lower == pytest.approx(_POS_757217_PRICE_LOWER, rel=0.001)
    assert price_upper == pytest.approx(_POS_757217_PRICE_UPPER, rel=0.001)


# ── derive_usd_prices: both directions (the highest-value test here) ────

def test_derive_usd_prices_anchor_is_token0():
    # WETH(18)/USDC(6), token0=WETH is the anchor at $2500.
    price_t1_per_t0 = 2500.0  # USDC per WETH
    sqrt_price_x96 = int(Q96 * Decimal(price_t1_per_t0 * 10 ** (6 - 18)).sqrt())
    result = mp.derive_usd_prices("WETH", "USDC", "token0", 2500.0, sqrt_price_x96, 18, 6)
    assert result["token0_usd"] == 2500.0
    assert result["token1_usd"] == pytest.approx(1.0, rel=0.01)
    assert result["derived_side"] == "token1"


def test_derive_usd_prices_anchor_is_token1():
    # USDC(6)/WETH(18) — token0/token1 order flipped (address-sorted, not
    # semantic) — anchor is now token1 (WETH) at $2500.
    price_t1_per_t0 = 1 / 2500.0  # WETH per USDC
    sqrt_price_x96 = int(Q96 * Decimal(price_t1_per_t0 * 10 ** (18 - 6)).sqrt())
    result = mp.derive_usd_prices("USDC", "WETH", "token1", 2500.0, sqrt_price_x96, 6, 18)
    assert result["token1_usd"] == 2500.0
    assert result["token0_usd"] == pytest.approx(1.0, rel=0.01)
    assert result["derived_side"] == "token0"


def test_derive_usd_prices_directions_are_not_accidentally_symmetric():
    # A regression guard against the exact failure mode the spec warns
    # about: an inversion bug produces a PLAUSIBLE-LOOKING wrong number
    # (e.g. multiplying instead of dividing) rather than crashing. Assert
    # the token0-anchor and token1-anchor results for the SAME pool rate
    # are reciprocal-shaped, not identical.
    sqrt_price_x96 = tick_to_sqrt_price_x96(round(price_to_tick(2500.0, 18, 6)))
    as_token0 = mp.derive_usd_prices("A", "B", "token0", 2500.0, sqrt_price_x96, 18, 6)
    as_token1 = mp.derive_usd_prices("A", "B", "token1", 2500.0, sqrt_price_x96, 18, 6)
    # If anchor is token0 ($2500), the derived token1 price is small (~1).
    # If the SAME $2500 anchor is instead attached to token1, the derived
    # token0 price is huge (~2500 * 2500) - these must differ enormously;
    # an inversion bug would make them coincidentally close.
    assert as_token0["token1_usd"] < 10
    assert as_token1["token0_usd"] > 1_000_000


def test_derive_usd_prices_invalid_anchor_side_raises():
    with pytest.raises(ValueError):
        mp.derive_usd_prices("A", "B", "sideways", 2500.0, tick_to_sqrt_price_x96(0), 18, 6)


def test_derive_usd_prices_anchor_price_none_propagates_none():
    result = mp.derive_usd_prices("A", "B", "token0", None, tick_to_sqrt_price_x96(0), 18, 6)
    assert result["token0_usd"] is None
    assert result["token1_usd"] is None


# ── Decimals asymmetry ────────────────────────────────────────────────────

def test_decimals_asymmetry_18_6_vs_6_18():
    tick = round(price_to_tick(2500.0, 18, 6))
    sqrt_price_x96 = tick_to_sqrt_price_x96(tick)
    price_18_6 = mp.pool_price_token1_per_token0(sqrt_price_x96, 18, 6)
    assert price_18_6 == pytest.approx(2500.0, rel=0.001)

    # Same raw tick, decimals REVERSED (6, 18): the 10**(d0-d1) adjustment
    # must apply in the opposite direction, producing a wildly different
    # (not just sign-flipped) number - 10**12 apart, not 1/2500.
    price_6_18 = mp.pool_price_token1_per_token0(sqrt_price_x96, 6, 18)
    assert price_6_18 == pytest.approx(2500.0 * 10 ** (6 - 18) / 10 ** (18 - 6), rel=0.001)
    assert price_6_18 != pytest.approx(price_18_6, rel=0.5)


# ── Division-by-zero guards: assert None specifically, not falsiness ────

def test_days_held_zero_gives_none_usd_per_day():
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    result = mp.compute_performance(
        current_value_usd=1000.0, initial_value_usd=900.0,
        uncollected_usd=10.0, collected_usd=5.0,
        first_seen_at_utc=now, now_utc=now,  # zero elapsed time
    )
    assert result["days_held"] == 0
    assert result["usd_per_day"] is None
    assert result["usd_per_day"] is not 0.0  # noqa: F632 - explicit identity, not truthiness


def test_days_held_negative_gives_none_usd_per_day():
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    later_first_seen = now + timedelta(days=1)  # first_seen AFTER now - malformed input
    result = mp.compute_performance(
        current_value_usd=1000.0, initial_value_usd=900.0,
        uncollected_usd=10.0, collected_usd=5.0,
        first_seen_at_utc=later_first_seen, now_utc=now,
    )
    assert result["days_held"] < 0
    assert result["usd_per_day"] is None


def test_current_value_zero_gives_none_apr():
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    first_seen = now - timedelta(days=30)
    result = mp.compute_performance(
        current_value_usd=0.0, initial_value_usd=900.0,
        uncollected_usd=10.0, collected_usd=5.0,
        first_seen_at_utc=first_seen, now_utc=now,
    )
    assert result["apr_percent"] is None


def test_current_value_none_gives_none_apr():
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    first_seen = now - timedelta(days=30)
    result = mp.compute_performance(
        current_value_usd=None, initial_value_usd=900.0,
        uncollected_usd=10.0, collected_usd=5.0,
        first_seen_at_utc=first_seen, now_utc=now,
    )
    assert result["apr_percent"] is None
    assert result["pnl_usd"] is None  # current_value_usd unavailable


def test_initial_value_none_gives_none_pnl():
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    first_seen = now - timedelta(days=30)
    result = mp.compute_performance(
        current_value_usd=1000.0, initial_value_usd=None,
        uncollected_usd=10.0, collected_usd=5.0,
        first_seen_at_utc=first_seen, now_utc=now,
    )
    assert result["pnl_usd"] is None
    assert any("initial_value_usd is null" in n for n in result["notes"])


def test_first_seen_at_none_gives_none_days_held():
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    result = mp.compute_performance(
        current_value_usd=1000.0, initial_value_usd=900.0,
        uncollected_usd=10.0, collected_usd=5.0,
        first_seen_at_utc=None, now_utc=now,
    )
    assert result["days_held"] is None
    assert result["usd_per_day"] is None
    assert result["apr_percent"] is None
    # pnl_usd is still computable - it doesn't depend on days_held at all.
    assert result["pnl_usd"] == pytest.approx(1000.0 + 10.0 - 900.0)


# ── P/L excludes collected fees ───────────────────────────────────────────

def test_pnl_excludes_collected_fees():
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    first_seen = now - timedelta(days=10)
    current_value_usd = 5000.0
    initial_value_usd = 4000.0
    uncollected_usd = 50.0
    collected_usd = 300.0  # large, non-zero - must NOT leak into pnl_usd

    result = mp.compute_performance(
        current_value_usd, initial_value_usd, uncollected_usd, collected_usd,
        first_seen, now,
    )
    expected_pnl = current_value_usd + uncollected_usd - initial_value_usd
    assert result["pnl_usd"] == pytest.approx(expected_pnl)
    assert result["pnl_usd"] != pytest.approx(expected_pnl + collected_usd)
    # total_earned_usd is a separate figure that DOES include collected.
    assert result["total_earned_usd"] == pytest.approx(collected_usd + uncollected_usd)


# ── Uncollected fee math, including uint256 wraparound ──────────────────

def test_fee_growth_inside_in_range():
    inside = mm.fee_growth_inside(
        current_tick=0, tick_lower=-10, tick_upper=10,
        fee_growth_global=1000, fee_growth_outside_lower=100, fee_growth_outside_upper=50,
    )
    assert inside == 850


def test_fee_growth_inside_wraparound_underflow():
    # fee_growth_outside_lower > fee_growth_global: the "feeGrowthGlobal -
    # feeGrowthOutside" subtraction underflows uint256 - this is EXPECTED
    # (per the Uniswap V3 accumulator design), masked rather than guarded.
    result = mm.fee_growth_inside(
        current_tick=-20, tick_lower=-10, tick_upper=10,
        fee_growth_global=5, fee_growth_outside_lower=100, fee_growth_outside_upper=2,
    )
    below_expected = (5 - 100) & mm.MASK_256
    expected = (5 - below_expected - 2) & mm.MASK_256
    assert result == expected
    assert 0 <= result <= mm.MASK_256  # stayed a valid uint256, never negative


def test_uncollected_fees_against_757217_style_fixture():
    # liquidity chosen so the fee-growth delta divides evenly, isolating
    # the formula's correctness from float/rounding concerns.
    liquidity = 2 ** 64
    fee_growth_inside_last = 500
    fee_growth_inside_current = fee_growth_inside_last + 2 ** 128  # delta = exactly 2**128
    tokens_owed = 42
    result = mm.uncollected_fees(liquidity, fee_growth_inside_current, fee_growth_inside_last, tokens_owed)
    assert result == liquidity + tokens_owed


def test_uncollected_fees_wraparound_delta():
    # fee_growth_inside_last > fee_growth_inside_current: the accumulator
    # itself wrapped between reads. Masked, not guarded - must not raise
    # and must not go negative.
    liquidity = 10
    result = mm.uncollected_fees(
        liquidity, fee_growth_inside_current=5, fee_growth_inside_last=10, tokens_owed=0
    )
    delta_expected = (5 - 10) & mm.MASK_256
    assert result == (liquidity * delta_expected) >> 128
    assert result >= 0


def test_value_position_wires_uncollected_and_collected_correctly():
    tick_lower, tick_upper, current_tick = -100, 100, 0
    sqrt_price_x96 = tick_to_sqrt_price_x96(current_tick)
    result = mp.value_position(
        liquidity=10 ** 18, tick_lower=tick_lower, tick_upper=tick_upper,
        current_tick=current_tick, sqrt_price_x96=sqrt_price_x96,
        decimals0=18, decimals1=18, token0_usd=2.0, token1_usd=3.0,
        uncollected0=1.5, uncollected1=2.5, collected0=0.5, collected1=0.25,
    )
    assert result["uncollected0"] == 1.5
    assert result["uncollected1"] == 2.5
    assert result["uncollected_usd"] == pytest.approx(1.5 * 2.0 + 2.5 * 3.0)
    assert result["collected_usd"] == pytest.approx(0.5 * 2.0 + 0.25 * 3.0)
    assert result["total_earned_usd"] == pytest.approx(result["collected_usd"] + result["uncollected_usd"])
    assert result["current_value_usd"] == pytest.approx(result["amount0_usd"] + result["amount1_usd"])


def test_value_position_none_prices_propagate_none_not_zero():
    result = mp.value_position(
        liquidity=10 ** 18, tick_lower=-100, tick_upper=100, current_tick=0,
        sqrt_price_x96=tick_to_sqrt_price_x96(0), decimals0=18, decimals1=18,
        token0_usd=None, token1_usd=None,
        uncollected0=1.0, uncollected1=1.0, collected0=1.0, collected1=1.0,
    )
    assert result["amount0_usd"] is None
    assert result["amount1_usd"] is None
    assert result["current_value_usd"] is None
    assert result["uncollected_usd"] is None
    assert result["collected_usd"] is None
    assert result["total_earned_usd"] is None
    # Token amounts themselves are still computed - a missing price doesn't
    # block the on-chain-math side of the valuation.
    assert result["amount0"] is not None
    assert result["amount1"] is not None


def test_sanity_check_price_within_tolerance():
    result = mp.sanity_check_price(100.0, 101.0, tolerance_frac=0.05)
    assert result["diverged"] is False
    assert result["ratio"] == pytest.approx(100.0 / 101.0)


def test_sanity_check_price_beyond_tolerance():
    result = mp.sanity_check_price(100.0, 50.0, tolerance_frac=0.05)
    assert result["diverged"] is True


def test_sanity_check_price_missing_input_is_none_not_false():
    result = mp.sanity_check_price(None, 100.0, tolerance_frac=0.05)
    assert result["diverged"] is None
    assert result["ratio"] is None


# ── Anchor resolver ────────────────────────────────────────────────────────

def test_anchor_resolver_miss_is_not_cached():
    calls = []

    def failing_then_succeeding(asset):
        calls.append(asset)
        return None if len(calls) == 1 else 2500.0

    r1 = ap.resolve_anchor_price("ETH", now=1000.0, fetcher=failing_then_succeeding)
    assert r1 == {"usd": None, "price_source": "unavailable", "age_seconds": None}

    # The miss must NOT have been cached - the very next call (still no TTL
    # elapsed) must attempt a fresh fetch, not reuse a cached miss.
    r2 = ap.resolve_anchor_price("ETH", now=1000.1, fetcher=failing_then_succeeding)
    assert r2["price_source"] == "live"
    assert r2["usd"] == 2500.0
    assert len(calls) == 2


def test_anchor_resolver_serves_stale_on_failure():
    def succeed(asset):
        return 2500.0

    r1 = ap.resolve_anchor_price("WETH", now=2000.0, fetcher=succeed)
    assert r1["price_source"] == "live"

    def fail(asset):
        return None

    r2 = ap.resolve_anchor_price("WETH", now=2000.0 + 61, fetcher=fail)  # past default 60s TTL
    assert r2["price_source"] == "stale"
    assert r2["usd"] == 2500.0
    assert r2["age_seconds"] == 61


def test_anchor_resolver_usdg_pins_to_one_when_no_external_price():
    def always_fail(asset):
        return None

    result = ap.resolve_anchor_price("USDG", now=3000.0, fetcher=always_fail)
    assert result == {"usd": 1.00, "price_source": "pinned", "age_seconds": None}


def test_anchor_resolver_usdg_uses_live_price_if_available():
    def succeed(asset):
        return 1.0005

    result = ap.resolve_anchor_price("USDG", now=4000.0, fetcher=succeed)
    assert result["price_source"] == "live"
    assert result["usd"] == 1.0005


def test_anchor_resolver_weth_and_eth_share_the_same_cache_entry():
    calls = []

    def succeed(asset):
        calls.append(asset)
        return 2500.0

    ap.resolve_anchor_price("WETH", now=5000.0, fetcher=succeed)
    r2 = ap.resolve_anchor_price("ETH", now=5000.1, fetcher=succeed)
    assert r2["price_source"] == "live"
    assert len(calls) == 1  # second call served from the shared ETH cache entry


def test_anchor_resolver_unknown_symbol_is_unavailable():
    result = ap.resolve_anchor_price("DOGE", now=6000.0, fetcher=lambda a: 1.0)
    assert result == {"usd": None, "price_source": "unavailable", "age_seconds": None}
