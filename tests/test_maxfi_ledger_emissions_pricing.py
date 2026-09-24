"""Emissions C3 - reward-token pricing (maxfi_ledger_pricing.
reward_token_usd_at_block + the additive price-block stats keys). No
network: eth_call / eth_get_logs are monkeypatched, the same boundary
tests/test_maxfi_ledger_pricing.py uses."""
from decimal import Decimal

import pytest

import maxfi_ledger as ml
import maxfi_ledger_ingest as mli
import maxfi_ledger_pricing as mlp


@pytest.fixture(autouse=True)
def _clear_caches():
    for cache in (mlp._DECIMALS_CACHE, mlp._POOL_RESOLUTION_CACHE, mlp._HOP_POOL_CACHE, mlp._POOL_TOKENS_CACHE):
        cache.clear()
    yield
    for cache in (mlp._DECIMALS_CACHE, mlp._POOL_RESOLUTION_CACHE, mlp._HOP_POOL_CACHE, mlp._POOL_TOKENS_CACHE):
        cache.clear()


AERO = mlp.ADDR_BASE_AERO
AERO_POOL = mlp.BASE_AERO_WETH_POOL
TARGET = 45_037_465


def _word(v):
    return format(v, "064x")


def _addr(a):
    return "0x" + a[2:].lower().zfill(64)


def _sqrt_price_x96_for(price_t1_per_t0, decimals0, decimals1):
    ratio_squared = Decimal(price_t1_per_t0) / (Decimal(10) ** (decimals0 - decimals1))
    return int(ratio_squared.sqrt() * 2 ** 96)


def _swap_log(sqrt_price_x96, pool, block):
    words = [_word(0), _word(0), _word(sqrt_price_x96), _word(0), _word(0)]
    return {"address": pool, "topics": [ml.TOPIC_SWAP, "0x" + "11" * 32, "0x" + "22" * 32],
            "data": "0x" + "".join(words), "blockNumber": hex(block),
            "timeStamp": hex(1_700_000_000 + block), "transactionHash": "0x" + format(block, "x").rjust(64, "0"),
            "logIndex": "0x0"}


DECIMALS = {mlp.ADDR_BASE_WETH: 18, AERO: 18, mlp.ADDR_BASE_USDC: 6}


def _fake_eth_call(pool_tokens):
    def fake(chain, to, data, timeout=30):
        to = to.lower()
        if data.startswith(mlp.SEL_ERC20_DECIMALS):
            return "0x" + _word(DECIMALS[to])
        if to in pool_tokens and data.startswith(mlp.SEL_POOL_TOKEN0):
            return "0x" + _addr(pool_tokens[to][0])[2:]
        if to in pool_tokens and data.startswith(mlp.SEL_POOL_TOKEN1):
            return "0x" + _addr(pool_tokens[to][1])[2:]
        raise AssertionError(f"unexpected eth_call {to} {data}")
    return fake


def _fake_get_logs(weth_usd=2000.0, aero_per_weth=4000.0, hop_offset=100, pool_offset=50):
    def fake(chain, address, topics, from_block, to_block, timeout=30):
        if address == mlp.BASE_HOP_POOL:  # WETH(token0, 18) / USDC(token1, 6)
            return [_swap_log(_sqrt_price_x96_for(weth_usd, 18, 6), address, to_block - hop_offset)]
        if address == AERO_POOL:  # WETH(token0) / AERO(token1): AERO per WETH
            return [_swap_log(_sqrt_price_x96_for(aero_per_weth, 18, 18), address, to_block - pool_offset)]
        raise AssertionError(f"unexpected getLogs {address}")
    return fake


def test_registry_pins_aero_to_the_ruled_pool():
    assert AERO == "0x940181a94a35a4569e4529a3cdfb74e38fd98631"
    assert mlp.REWARD_TOKEN_POOLS[("base", AERO)] == {
        "pool": "0x3d5d143381916280ff91407febeb52f2b60f33cf", "quote": mlp.ADDR_BASE_WETH,
    }


def test_aero_priced_via_weth_hop_with_price_blocks(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call({AERO_POOL: (mlp.ADDR_BASE_WETH, AERO)}))
    monkeypatch.setattr(mli, "eth_get_logs", _fake_get_logs())
    out = mlp.reward_token_usd_at_block("base", AERO, TARGET)
    assert out["reason"] is None and out["price_source"] == "swap_log"
    assert abs(out["usd"] - 0.5) / 0.5 < 1e-9  # $2000/WETH / 4000 AERO per WETH
    assert out["decimals"] == 18 and out["hop_anchor"] == "WETH" and out["pool_address"] == AERO_POOL
    assert out["price_block"] == TARGET - 50 and out["hop_price_block"] == TARGET - 100
    assert out["price_block_timestamp"].startswith("20") and out["hop_price_block_timestamp"].startswith("20")
    # 2 pool-token calls + 2 decimals (WETH, AERO) + USDC decimals + 2 swap walks
    assert out["rpc_calls"] == 7


def test_pool_pair_mismatch_is_a_reason_and_never_prices(monkeypatch):
    wrong = "0x" + "cd" * 20
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call({AERO_POOL: (mlp.ADDR_BASE_WETH, wrong)}))
    monkeypatch.setattr(mli, "eth_get_logs", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no walk")))
    out = mlp.reward_token_usd_at_block("base", AERO, TARGET)
    assert out["usd"] is None and out["reason"] == "reward_pool_mismatch" and out["rpc_calls"] == 2


def test_pool_tokens_unresolved_is_a_reason(monkeypatch):
    def boom(chain, to, data, timeout=30):
        raise mli.MaxFiRpcError("revert")
    monkeypatch.setattr(mli, "eth_call", boom)
    out = mlp.reward_token_usd_at_block("base", AERO, TARGET)
    assert out["usd"] is None and out["reason"] == "reward_pool_tokens_unresolved"


def test_unregistered_reward_token_is_a_reason_with_zero_rpc(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no rpc")))
    out = mlp.reward_token_usd_at_block("base", "0x3055913c90fcc1a6ce9a358911721eeb942013a1", TARGET)
    assert out["usd"] is None and out["reason"] == "reward_token_unregistered" and out["rpc_calls"] == 0
    out = mlp.reward_token_usd_at_block("robinhood", AERO, TARGET)
    assert out["reason"] == "reward_token_unregistered"


def test_chain_stable_is_one_dollar_without_a_swap(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call({}))
    monkeypatch.setattr(mli, "eth_get_logs", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no walk")))
    out = mlp.reward_token_usd_at_block("base", mlp.ADDR_BASE_USDC, TARGET)
    assert (out["usd"], out["decimals"], out["price_source"], out["reason"]) == (1.0, 6, "stable", None)
    assert out["price_block"] is None


def test_runtime_resolved_anchor_hop_pool_is_a_reason():
    out = mlp.reward_token_usd_at_block("robinhood", mlp.ADDR_RH_WETH, TARGET)
    assert out["usd"] is None and out["reason"] == "reward_anchor_hop_pool_not_fixed" and out["rpc_calls"] == 0


def test_fixed_hop_anchor_is_priced_off_its_hop_pool(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call({mlp.BASE_HOP_POOL: (mlp.ADDR_BASE_WETH, mlp.ADDR_BASE_USDC)}))
    monkeypatch.setattr(mli, "eth_get_logs", _fake_get_logs(weth_usd=2500.0))
    out = mlp.reward_token_usd_at_block("base", mlp.ADDR_BASE_WETH, TARGET)
    assert out["reason"] is None and abs(out["usd"] - 2500.0) / 2500.0 < 1e-9
    assert out["pool_address"] == mlp.BASE_HOP_POOL and out["hop_anchor"] is None


def test_existing_pricing_path_gains_only_additive_stats_keys(monkeypatch):
    alt = "0x" + "cc" * 20
    pool = {"pool_address": AERO_POOL, "token0": alt, "token1": mlp.ADDR_BASE_USDC,
            "fee": 500, "decimals0": 18, "decimals1": 6}
    monkeypatch.setattr(mli, "eth_get_logs", lambda c, a, t, f, to, timeout=30: [
        _swap_log(_sqrt_price_x96_for(3.0, 18, 6), AERO_POOL, to - 7)])
    token0_usd, token1_usd, _pool, stats = mlp.token0_token1_usd_at_block("base", None, 1, 5000, pool=pool)
    assert abs(token0_usd - 3.0) < 1e-9 and token1_usd == 1.0
    assert {"swap_walk_calls", "windows_checked", "reason", "hop_anchor", "rpc_calls"} <= set(stats)
    assert stats["price_block"] == 4993 and stats["hop_price_block"] is None
