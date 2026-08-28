"""Route-level regression tests for MaxFi Phase D.1.

Covers: the anchor registry code-side defaults + settings-override merge
(STEP 4), the dual-anchor valuation path where Phase D's one real defect
was found (STEP 5), the mirrored anchor-as-token1 case (also STEP 5 - the
census confirms this inversion direction is live in three real positions,
not hypothetical), and the collected_valuation_basis field (STEP 3c).

No network, no database writes - the client/anchor-resolver seams are
monkeypatched. web_portfolio spawns a background scheduler on non-__main__
import; we neutralize threading.Thread.start during import (established
pattern) so no thread starts.
"""
import math
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import pytest

WALLET = "0x" + "b" * 40
WETH_BASE = "0x4200000000000000000000000000000000000006"
USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
WETH_ROBINHOOD = "0x0bd7d308f8e1639fab988df18a8011f41eacad73"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def price_to_tick(price_decimal_adjusted, decimals0, decimals1):
    raw_price = price_decimal_adjusted / (10 ** (decimals0 - decimals1))
    return math.log(raw_price) / math.log(1.0001)


def tick_to_sqrt_price_x96(tick):
    return int((1.0001 ** (tick / 2)) * (2 ** 96))


def make_diag(token0_addr, token1_addr, dec0, dec1, price_lower, price_upper, price_current, liquidity):
    """Synthetic position_diagnostic()-shaped payload with a
    self-consistent, correctly-derived sqrtPriceX96/ticks for the given
    (decimals-adjusted) price range and current price."""
    tick_lower = round(price_to_tick(price_lower, dec0, dec1))
    tick_upper = round(price_to_tick(price_upper, dec0, dec1))
    current_tick = round(price_to_tick(price_current, dec0, dec1))
    sqrt_price_x96 = tick_to_sqrt_price_x96(current_tick)
    return {
        "token0": {"address": token0_addr, "symbol": "T0", "decimals": dec0},
        "token1": {"address": token1_addr, "symbol": "T1", "decimals": dec1},
        "vault_position": {"decoded": {
            "currentTickLower": str(tick_lower), "currentTickUpper": str(tick_upper),
            "cumulativeFees0": "0", "cumulativeFees1": "0",
        }},
        "npm_position": {"decoded": {
            "liquidity": str(liquidity),
            "feeGrowthInside0LastX128": "0", "feeGrowthInside1LastX128": "0",
            "tokensOwed0": "0", "tokensOwed1": "0",
        }},
        "slot0": {"decoded": {"sqrtPriceX96": str(sqrt_price_x96), "tick": str(current_tick)}},
        "fee_growth_global_0_x128": "0", "fee_growth_global_1_x128": "0",
        "ticks_lower": {"decoded": {"feeGrowthOutside0X128": "0", "feeGrowthOutside1X128": "0"}},
        "ticks_upper": {"decoded": {"feeGrowthOutside0X128": "0", "feeGrowthOutside1X128": "0"}},
    }


# ── STEP 4: anchor registry defaults + settings override merge ──────────

def test_anchor_registry_defaults_resolve_all_four_seeded_addresses(monkeypatch):
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {})
    registry = wp._maxfi_effective_anchor_registry()
    assert registry["robinhood:0x0bd7d308f8e1639fab988df18a8011f41eacad73"] == "ETH"
    assert registry["robinhood:0x5fc5360d0400a0fd4f2af552add042d716f1d168"] == "USDG"
    assert registry["base:0x4200000000000000000000000000000000000006"] == "ETH"
    assert registry["base:0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"] == "USDC"


def test_anchor_registry_absent_settings_key_falls_back_to_defaults_only(monkeypatch):
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {"some_unrelated_key": 1})
    registry = wp._maxfi_effective_anchor_registry()
    assert registry == dict(wp.MAXFI_ANCHOR_REGISTRY_DEFAULTS)


def test_anchor_registry_settings_override_merges_on_top_not_replaces(monkeypatch):
    new_token = "base:0x9999999999999999999999999999999999999999"
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {
        "maxfi_anchor_registry": {new_token: "USDC"}
    })
    registry = wp._maxfi_effective_anchor_registry()
    assert registry[new_token] == "USDC"
    # All four code-side defaults survive - override merges on top, doesn't replace.
    assert registry["robinhood:0x0bd7d308f8e1639fab988df18a8011f41eacad73"] == "ETH"
    assert registry["robinhood:0x5fc5360d0400a0fd4f2af552add042d716f1d168"] == "USDG"
    assert registry["base:0x4200000000000000000000000000000000000006"] == "ETH"
    assert registry["base:0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"] == "USDC"
    assert len(registry) == 5


def test_anchor_registry_lookup_is_case_insensitive_on_address(monkeypatch):
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {
        "maxfi_anchor_registry": {"base:0xAAAABBBBCCCCDDDDEEEEFFFF0000111122223333": "USDC"}
    })
    registry = wp._maxfi_effective_anchor_registry()
    assert registry["base:0xaaaabbbbccccddddeeeeffff0000111122223333"] == "USDC"


# ── STEP 5: dual-anchor route-level regression ───────────────────────────
# The one real defect found in Phase D was here: a hand-rolled
# multiplication in this exact branch produced ~6.25M instead of ~1.0. See
# the Phase D.1 summary for confirmation that swapping the fix back to a
# multiplication makes this test fail.

def test_dual_anchor_route_path_sanity_check_and_value(monkeypatch, client):
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {})  # code-side defaults only
    monkeypatch.setattr(wp, "maxfi_eth_block_number", lambda chain: 1000)

    snapshot = [{"array_index": 0, "token_id": "1", "pool_address": "0xPOOL",
                 "token0_address": WETH_BASE, "token1_address": USDC_BASE, "fee_tier": 500}]
    monkeypatch.setattr(wp, "maxfi_get_wallet_position_snapshot", lambda chain, wallet: snapshot)

    diag = make_diag(WETH_BASE, USDC_BASE, 18, 6, 2300.0, 2700.0, 2500.0, 5 * 10 ** 17)
    monkeypatch.setattr(wp, "maxfi_position_diagnostic", lambda chain, wallet, token_id: diag)

    def fake_resolve(symbol, now=None, fetcher=None):
        return {"ETH": {"usd": 2500.0, "price_source": "live", "age_seconds": 0},
                "USDC": {"usd": 1.0, "price_source": "live", "age_seconds": 0}}[symbol]
    monkeypatch.setattr(wp.maxfi_anchor_prices, "resolve_anchor_price", fake_resolve)

    r = client.get(f"/api/maxfi/valuation/base/{WALLET}")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]

    assert "sanity_check" in pos
    assert pos["sanity_check"]["diverged"] is False
    assert pos["sanity_check"]["ratio"] == pytest.approx(1.0, rel=0.01)

    # Both anchors resolved INDEPENDENTLY (not derived from each other):
    # amount*_usd must equal amount * that side's own known price exactly.
    assert pos["amount0_usd"] == pytest.approx(pos["amount0"] * 2500.0, rel=1e-6)
    assert pos["amount1_usd"] == pytest.approx(pos["amount1"] * 1.0, rel=1e-6)
    expected_value = pos["amount0"] * 2500.0 + pos["amount1"] * 1.0
    assert pos["current_value_usd"] == pytest.approx(expected_value, rel=1e-6)


def test_single_anchor_route_path_anchor_as_token1(monkeypatch, client):
    """Address sorting can put the anchor on EITHER side. The token census
    confirms WETH sits as token1 in the CASHCAT pool and USDG as token1
    against DJT on Robinhood Chain - this inversion direction is live in
    three real positions, not a hypothetical edge case."""
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {})
    monkeypatch.setattr(wp, "maxfi_eth_block_number", lambda chain: 2000)

    memecoin_addr = "0x" + "c" * 40  # synthetic - exact address not needed for this test

    snapshot = [{"array_index": 0, "token_id": "2", "pool_address": "0xPOOL2",
                 "token0_address": memecoin_addr, "token1_address": WETH_ROBINHOOD, "fee_tier": 3000}]
    monkeypatch.setattr(wp, "maxfi_get_wallet_position_snapshot", lambda chain, wallet: snapshot)

    # 1 WETH = 2500 memecoin -> 1 memecoin = 1/2500 WETH.
    diag = make_diag(memecoin_addr, WETH_ROBINHOOD, 18, 18, 1 / 2600, 1 / 2400, 1 / 2500, 5 * 10 ** 17)
    monkeypatch.setattr(wp, "maxfi_position_diagnostic", lambda chain, wallet, token_id: diag)

    monkeypatch.setattr(
        wp.maxfi_anchor_prices, "resolve_anchor_price",
        lambda symbol, now=None, fetcher=None: {"usd": 2500.0, "price_source": "live", "age_seconds": 0},
    )

    r = client.get(f"/api/maxfi/valuation/robinhood/{WALLET}")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]

    assert pos["status"] in ("priced", "partial")
    assert pos["reason"] in (None, "no_matching_db_row")
    # token1 (WETH) is the anchor - its USD value is amount1 * $2500 exactly.
    assert pos["amount1_usd"] == pytest.approx(pos["amount1"] * 2500.0, rel=1e-6)
    # token0 (memecoin) is DERIVED: 1 memecoin ~= 1/2500 WETH ~= $1.
    assert pos["amount0_usd"] == pytest.approx(pos["amount0"] * 1.0, rel=0.01)


# ── STEP 3c: collected_valuation_basis field ─────────────────────────────

def test_valuation_response_includes_collected_valuation_basis(monkeypatch, client):
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {})
    monkeypatch.setattr(wp, "maxfi_eth_block_number", lambda chain: 3000)

    snapshot = [{"array_index": 0, "token_id": "3", "pool_address": "0xPOOL3",
                 "token0_address": WETH_BASE, "token1_address": USDC_BASE, "fee_tier": 500}]
    monkeypatch.setattr(wp, "maxfi_get_wallet_position_snapshot", lambda chain, wallet: snapshot)

    diag = make_diag(WETH_BASE, USDC_BASE, 18, 6, 2300.0, 2700.0, 2500.0, 5 * 10 ** 17)
    monkeypatch.setattr(wp, "maxfi_position_diagnostic", lambda chain, wallet, token_id: diag)

    def fake_resolve(symbol, now=None, fetcher=None):
        return {"ETH": {"usd": 2500.0, "price_source": "live", "age_seconds": 0},
                "USDC": {"usd": 1.0, "price_source": "live", "age_seconds": 0}}[symbol]
    monkeypatch.setattr(wp.maxfi_anchor_prices, "resolve_anchor_price", fake_resolve)

    r = client.get(f"/api/maxfi/valuation/base/{WALLET}")
    pos = r.get_json()["positions"][0]
    assert pos["collected_valuation_basis"] == "current_price"


def test_unpriced_position_has_null_collected_valuation_basis(monkeypatch, client):
    # No anchor in this pair at all -> unpriced, and collected fees were
    # never valued, so the basis field must be null, not a misleading
    # "current_price" label on a figure that doesn't exist.
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {})
    monkeypatch.setattr(wp, "maxfi_eth_block_number", lambda chain: 4000)

    non_anchor_a = "0x" + "d" * 40
    non_anchor_b = "0x" + "e" * 40
    snapshot = [{"array_index": 0, "token_id": "4", "pool_address": "0xPOOL4",
                 "token0_address": non_anchor_a, "token1_address": non_anchor_b, "fee_tier": 3000}]
    monkeypatch.setattr(wp, "maxfi_get_wallet_position_snapshot", lambda chain, wallet: snapshot)

    diag = make_diag(non_anchor_a, non_anchor_b, 18, 18, 0.9, 1.1, 1.0, 5 * 10 ** 17)
    monkeypatch.setattr(wp, "maxfi_position_diagnostic", lambda chain, wallet, token_id: diag)

    r = client.get(f"/api/maxfi/valuation/base/{WALLET}")
    pos = r.get_json()["positions"][0]
    assert pos["status"] == "unpriced"
    assert pos["reason"] == "no_anchor_in_pair"
    assert pos["collected_valuation_basis"] is None
