"""Tests for LP range-block data: tick math, tier derivation, and Uniswap V4 reads.

Covers: the shared ticks_to_prices() helper matches the original inline V3/Aerodrome
math exactly (proves the extract-method refactor didn't change behavior); in_range
derivation is null-safe and orientation-correct in both decimal directions; Uniswap
V4 PositionInfo bit-decoding and poolId hashing; check_uniswap_v4_lp_position's
success path (known ticks -> expected bounds) and failure path (any exception ->
None, never a guess); and Zerion's tier-2 payload mapping vs tier-3 null default.

web_portfolio spawns a background scheduler on non-__main__ import; we neutralize
threading.Thread.start during import (established pattern) so no thread starts.
"""
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

from src.connectors.uniswap_v4 import decode_position_info, compute_pool_id
from src.connectors.zerion import map_zerion_lp_to_app


# ─── ticks_to_prices: matches the original inline formula exactly ─────────────

def _old_inline_formula(tick_lower, tick_upper, sqrt_price_x96, token0_decimals, token1_decimals):
    """Reproduces the pre-refactor inline math verbatim (both check_lp_position and
    check_aerodrome_slipstream_lp_position used this before it was extracted)."""
    sqrt_price = sqrt_price_x96 / (2 ** 96)
    current_price_raw = sqrt_price ** 2
    decimal_adjustment = 10 ** (token0_decimals - token1_decimals)
    current_price_adjusted = current_price_raw * decimal_adjustment
    price_lower = (1.0001 ** tick_lower) * decimal_adjustment
    price_upper = (1.0001 ** tick_upper) * decimal_adjustment
    return price_lower, price_upper, current_price_adjusted


def test_ticks_to_prices_matches_old_inline_formula_eth_usdc_orientation():
    # token0 has fewer decimals than token1 (e.g. token0=WBTC 8dp, token1=USDC 6dp
    # inverted for variety) — decimal_adjustment < 1 direction.
    tick_lower, tick_upper, current_tick = 190000, 210000, 200000
    sqrt_price_x96 = int((1.0001 ** current_tick) ** 0.5 * (2 ** 96))
    expected = _old_inline_formula(tick_lower, tick_upper, sqrt_price_x96, 18, 6)
    got = wp.ticks_to_prices(tick_lower, tick_upper, current_tick, sqrt_price_x96, 18, 6)
    assert got == expected


def test_ticks_to_prices_matches_old_inline_formula_opposite_decimal_direction():
    # token0_decimals > token1_decimals — decimal_adjustment > 1 direction (the
    # "other orientation" the task asks to check).
    tick_lower, tick_upper, current_tick = -50000, -30000, -40000
    sqrt_price_x96 = int((1.0001 ** current_tick) ** 0.5 * (2 ** 96))
    expected = _old_inline_formula(tick_lower, tick_upper, sqrt_price_x96, 8, 18)
    got = wp.ticks_to_prices(tick_lower, tick_upper, current_tick, sqrt_price_x96, 8, 18)
    assert got == expected


# ─── in_range derivation: null-safe, orientation-correct both directions ──────

def test_derive_in_range_true_when_current_between_bounds():
    assert wp._derive_in_range(1000.0, 1500.0, 2000.0) is True


def test_derive_in_range_false_when_current_outside_bounds():
    assert wp._derive_in_range(1000.0, 2500.0, 2000.0) is False
    assert wp._derive_in_range(1000.0, 500.0, 2000.0) is False


def test_derive_in_range_null_when_any_value_missing():
    assert wp._derive_in_range(None, 1500.0, 2000.0) is None
    assert wp._derive_in_range(1000.0, None, 2000.0) is None
    assert wp._derive_in_range(1000.0, 1500.0, None) is None
    assert wp._derive_in_range(None, None, None) is None


def test_build_range_block_never_defaults_in_range():
    block = wp.build_range_block(None, None, None, None)
    assert block == {
        "min_price": None, "max_price": None, "current_price": None,
        "source": None, "in_range": None,
    }


def test_ticks_to_prices_in_range_correct_for_both_decimal_directions():
    # decimal_adjustment > 1 (token0_decimals > token1_decimals)
    lo, hi, cur = wp.ticks_to_prices(-1000, 1000, 0, int(2 ** 96), 18, 6)
    assert wp._derive_in_range(lo, cur, hi) is True
    lo, hi, cur = wp.ticks_to_prices(-1000, -500, 0, int(2 ** 96), 18, 6)
    assert wp._derive_in_range(lo, cur, hi) is False

    # decimal_adjustment < 1 (token0_decimals < token1_decimals)
    lo, hi, cur = wp.ticks_to_prices(-1000, 1000, 0, int(2 ** 96), 6, 18)
    assert wp._derive_in_range(lo, cur, hi) is True
    lo, hi, cur = wp.ticks_to_prices(500, 1000, 0, int(2 ** 96), 6, 18)
    assert wp._derive_in_range(lo, cur, hi) is False


# ─── Uniswap V4: PositionInfo bit-decoding ─────────────────────────────────────

def _pack_position_info(tick_lower, tick_upper, pool_id_upper=0, has_subscriber=0):
    """Build a packed PositionInfo uint256 the same way PositionInfoLibrary does,
    for round-tripping through decode_position_info()."""
    tl = tick_lower & 0xFFFFFF
    tu = tick_upper & 0xFFFFFF
    return (pool_id_upper << 56) | (tu << 32) | (tl << 8) | (has_subscriber & 0xFF)


def test_decode_position_info_positive_ticks():
    info = _pack_position_info(1000, 5000)
    assert decode_position_info(info) == (1000, 5000)


def test_decode_position_info_negative_ticks():
    info = _pack_position_info(-887200, -1000)
    assert decode_position_info(info) == (-887200, -1000)


def test_decode_position_info_mixed_sign():
    info = _pack_position_info(-60000, 60000)
    assert decode_position_info(info) == (-60000, 60000)


# ─── Uniswap V4: poolId derivation ─────────────────────────────────────────────

def test_compute_pool_id_deterministic_and_32_bytes():
    c0 = "0x0000000000000000000000000000000000000001"
    c1 = "0x0000000000000000000000000000000000000002"
    hooks = "0x0000000000000000000000000000000000000000"
    pid1 = compute_pool_id(c0, c1, 3000, 60, hooks)
    pid2 = compute_pool_id(c0, c1, 3000, 60, hooks)
    assert pid1 == pid2
    assert isinstance(pid1, (bytes, bytearray))
    assert len(pid1) == 32


def test_compute_pool_id_changes_with_fee():
    c0 = "0x0000000000000000000000000000000000000001"
    c1 = "0x0000000000000000000000000000000000000002"
    hooks = "0x0000000000000000000000000000000000000000"
    pid_a = compute_pool_id(c0, c1, 3000, 60, hooks)
    pid_b = compute_pool_id(c0, c1, 500, 10, hooks)
    assert pid_a != pid_b


# ─── check_uniswap_v4_lp_position: fake connector ──────────────────────────────

class _FakeCall:
    def __init__(self, value):
        self._value = value

    def call(self):
        return self._value


class _FakeFunctions:
    def __init__(self, **kwargs):
        self._kwargs = kwargs

    def __getattr__(self, name):
        if name not in self._kwargs:
            raise AttributeError(name)
        spec = self._kwargs[name]

        def _fn(*args, **kw):
            value = spec(*args, **kw) if callable(spec) else spec
            return _FakeCall(value)
        return _fn


class _FakeContract:
    def __init__(self, **kwargs):
        self.functions = _FakeFunctions(**kwargs)


class _FakeEth:
    def __init__(self, contracts_by_address):
        self._contracts = contracts_by_address

    def contract(self, address=None, abi=None):
        return self._contracts[address]


class _FakeW3:
    def __init__(self, contracts_by_address):
        self.eth = _FakeEth(contracts_by_address)


TOKEN0 = "0x0000000000000000000000000000000000000001"
TOKEN1 = "0x0000000000000000000000000000000000000002"
HOOKS = "0x0000000000000000000000000000000000000000"


def _make_v4_connector(tick_lower=-1000, tick_upper=1000, current_tick=0, liquidity=10 ** 18,
                        token0_decimals=18, token1_decimals=6, fee=3000, tick_spacing=60,
                        raise_on="none"):
    from web3 import Web3
    sqrt_price_x96 = int((1.0001 ** current_tick) ** 0.5 * (2 ** 96))
    info = _pack_position_info(tick_lower, tick_upper)
    pool_key = (TOKEN0, TOKEN1, fee, tick_spacing, HOOKS)

    def _get_pool_and_position_info(token_id):
        if raise_on == "position_manager":
            raise RuntimeError("RPC unavailable")
        return (pool_key, info)

    def _get_slot0(pool_id):
        if raise_on == "state_view":
            raise RuntimeError("RPC unavailable")
        return (sqrt_price_x96, current_tick, 0, 0)

    position_manager = _FakeContract(
        getPoolAndPositionInfo=_get_pool_and_position_info,
        getPositionLiquidity=lambda token_id: liquidity,
    )
    state_view = _FakeContract(getSlot0=_get_slot0)
    token0_contract = _FakeContract(symbol=lambda: "WETH", decimals=lambda: token0_decimals)
    token1_contract = _FakeContract(symbol=lambda: "USDC", decimals=lambda: token1_decimals)

    w3 = _FakeW3({
        Web3.to_checksum_address(TOKEN0): token0_contract,
        Web3.to_checksum_address(TOKEN1): token1_contract,
    })

    class _Connector:
        pass

    c = _Connector()
    c.position_manager = position_manager
    c.state_view = state_view
    c.w3 = w3
    return c


def test_check_uniswap_v4_lp_position_known_ticks_yields_expected_bounds(monkeypatch):
    monkeypatch.setattr(wp, "get_token_price_usd", lambda symbol, address, chain: 1.0)
    connector = _make_v4_connector(tick_lower=-1000, tick_upper=1000, current_tick=0,
                                    token0_decimals=18, token1_decimals=6)
    result = wp.check_uniswap_v4_lp_position(connector, 42, wp.Chain.ETHEREUM)

    assert result is not None
    expected_lo, expected_hi, expected_cur = wp.ticks_to_prices(-1000, 1000, 0, int(2 ** 96), 18, 6)
    assert result["price_lower"] == expected_lo
    assert result["price_upper"] == expected_hi
    assert result["current_price"] == expected_cur
    assert result["in_range"] is True
    assert result["range"] == {
        "min_price": expected_lo, "max_price": expected_hi, "current_price": expected_cur,
        "source": "onchain", "in_range": True,
    }
    assert result["token0_symbol"] == "WETH"
    assert result["token1_symbol"] == "USDC"
    assert result["total_value_usd"] > 0  # amounts derived from liquidity, not fabricated


def test_check_uniswap_v4_lp_position_out_of_range():
    connector = _make_v4_connector(tick_lower=1000, tick_upper=2000, current_tick=0)
    result = wp.check_uniswap_v4_lp_position(connector, 42, wp.Chain.ETHEREUM)
    assert result is not None
    assert result["in_range"] is False
    assert result["range"]["source"] == "onchain"


def test_check_uniswap_v4_lp_position_returns_none_on_position_manager_failure():
    connector = _make_v4_connector(raise_on="position_manager")
    result = wp.check_uniswap_v4_lp_position(connector, 42, wp.Chain.ETHEREUM)
    assert result is None


def test_check_uniswap_v4_lp_position_returns_none_on_state_view_failure():
    connector = _make_v4_connector(raise_on="state_view")
    result = wp.check_uniswap_v4_lp_position(connector, 42, wp.Chain.ETHEREUM)
    assert result is None


# ─── Zerion fallback: tier 2 (payload) vs tier 3 (nulls) ───────────────────────

def _group(chain_id="base", protocol_name="uniswap v4", extra_attrs=None):
    base_attrs = {
        "application_metadata": {"name": protocol_name},
        "protocol_module": "liquidity_pool",
        "group_id": "g1",
        "fungible_info": {"symbol": "USDC"},
        "quantity": {"float": 1000.0},
        "value": 1000.0,
        "price": 1.0,
        "position_type": "deposit",
    }
    if extra_attrs:
        base_attrs.update(extra_attrs)
    return [{
        "attributes": base_attrs,
        "relationships": {"chain": {"data": {"id": chain_id}}},
    }]


def test_map_zerion_lp_to_app_tier3_all_null_range_when_nothing_available():
    result = map_zerion_lp_to_app(_group(), "0xwallet", "Test Wallet")
    assert result["range"] == {
        "min_price": None, "max_price": None, "current_price": None,
        "source": None, "in_range": None,
    }
    assert result["in_range"] is None
    # legacy flat fields stay at the pre-existing "no range" sentinel (0)
    assert result["price_lower"] == 0
    assert result["price_upper"] == 0


def test_map_zerion_lp_to_app_tier2_payload_range_populates_when_present():
    group = _group(extra_attrs={"min_price": 1800.0, "max_price": 2600.0, "current_price": 2200.0})
    result = map_zerion_lp_to_app(group, "0xwallet", "Test Wallet")
    assert result["range"] == {
        "min_price": 1800.0, "max_price": 2600.0, "current_price": 2200.0,
        "source": "payload", "in_range": True,
    }
    assert result["in_range"] is True


def test_map_zerion_lp_to_app_tier2_payload_range_out_of_range():
    group = _group(extra_attrs={"min_price": 1800.0, "max_price": 2600.0, "current_price": 3000.0})
    result = map_zerion_lp_to_app(group, "0xwallet", "Test Wallet")
    assert result["range"]["source"] == "payload"
    assert result["range"]["in_range"] is False
    assert result["in_range"] is False


def test_map_zerion_lp_to_app_never_defaults_in_range_true():
    # Regression guard for the PR #85 bug this whole block builds on top of:
    # an unenriched position must never read in_range=True.
    result = map_zerion_lp_to_app(_group(protocol_name="uniswap v4"), "0xwallet", "Test Wallet")
    assert result["in_range"] is not True
