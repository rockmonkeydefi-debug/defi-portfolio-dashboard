"""Commit 3b.3a - cbBTC as a second hop anchor (HANDOFF_maxfi_ledger.md
"Commit 3b.3a"). No network: maxfi_ledger_ingest.eth_call /
eth_get_logs are monkeypatched at the same seam
tests/test_maxfi_ledger_pricing.py uses. Swap logs come from the four
SYNTHETIC fixtures under tests/fixtures/maxfi_ledger/synthetic_*.json
(Etherscan-page shape of base_swap_page.json; each carries a
"_synthetic" header with the hand-derived sqrtPriceX96 -> price
arithmetic the assertions below pin).

The WETH byte-identity gate is NOT a test here: it is the existing 3b.2
pricing tests passing unmodified (tests/test_maxfi_ledger_pricing.py).
"""
import json
import os

import pytest

import maxfi_ledger_ingest as mli
import maxfi_ledger_pricing as mlp

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "maxfi_ledger")


def load_fixture(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)["result"]


@pytest.fixture(autouse=True)
def _clear_caches():
    for cache in (mlp._DECIMALS_CACHE, mlp._POOL_RESOLUTION_CACHE, mlp._HOP_POOL_CACHE, mlp._POOL_TOKENS_CACHE):
        cache.clear()
    yield
    for cache in (mlp._DECIMALS_CACHE, mlp._POOL_RESOLUTION_CACHE, mlp._HOP_POOL_CACHE, mlp._POOL_TOKENS_CACHE):
        cache.clear()


NPM = "0x" + "77" * 20
CBADA = "0xcbada732173e39521cdbe8bf59a6dc85a9fc7b8c"  # Base, 6 dec (step-1 finding)
MSTR = "0xec262a75e413fafd0df80480274532c79d42da09"  # RH, 18 dec
BASE_POS_POOL = "0x86c33d51671b0a336e4eda898d1a0dbc2064f058"  # real Base cbADA/cbBTC pool
RH_POS_POOL = "0x6f8dc7122b56017c46892f91d38d871acf787f9b"  # real RH cbBTC/MSTR pool (id 112)
TARGET_BLOCK = 5000  # every fixture Swap sits at 0x1388 = 5000

BASE_HOP_LOGS = load_fixture("synthetic_base_cbbtc_usdc_hop_swap.json")
BASE_POS_LOGS = load_fixture("synthetic_base_cbada_cbbtc_position_swap.json")
RH_HOP_LOGS = load_fixture("synthetic_rh_cbbtc_usdg_hop_swap.json")
RH_POS_LOGS = load_fixture("synthetic_rh_cbbtc_mstr_position_swap.json")

BASE_CBADA_CBBTC_POOL = {
    "pool_address": BASE_POS_POOL, "token0": CBADA, "token1": mlp.ADDR_BASE_CBBTC,
    "fee": 3000, "decimals0": 6, "decimals1": 8,
}
RH_CBBTC_MSTR_POOL = {
    "pool_address": RH_POS_POOL, "token0": mlp.ADDR_RH_CBBTC, "token1": MSTR,
    "fee": 3000, "decimals0": 8, "decimals1": 18,
}


def _addr_word(address):
    return address[2:].lower().zfill(64)


def _uint_word(value):
    return format(value, "064x")


DECIMALS = {
    mlp.ADDR_BASE_USDC: 6, mlp.ADDR_BASE_CBBTC: 8, CBADA: 6, mlp.ADDR_BASE_WETH: 18,
    mlp.ADDR_RH_USDG: 6, mlp.ADDR_RH_CBBTC: 8, MSTR: 18, mlp.ADDR_RH_WETH: 18,
}
# What the ruled hop pools' own token0()/token1() return (V3 address order:
# the stable's address is lower than cbBTC's on both chains).
HOP_POOL_TOKENS = {
    mlp.BASE_CBBTC_HOP_POOL: (mlp.ADDR_BASE_USDC, mlp.ADDR_BASE_CBBTC),
    mlp.RH_CBBTC_HOP_POOL: (mlp.ADDR_RH_USDG, mlp.ADDR_RH_CBBTC),
}


def _fake_eth_call(hop_pool_tokens=HOP_POOL_TOKENS):
    """decimals() for every known token; token0()/token1() for the ruled
    cbBTC hop pools. Anything else (npm.positions, factory, getPool...) is
    a test bug - the position pool is always passed pre-resolved."""
    def fake(chain, to, data, timeout=30):
        to = to.lower()
        if data.startswith(mlp.SEL_ERC20_DECIMALS) and to in DECIMALS:
            return "0x" + _uint_word(DECIMALS[to])
        if to in hop_pool_tokens:
            if data.startswith(mlp.SEL_POOL_TOKEN0):
                return "0x" + _addr_word(hop_pool_tokens[to][0])
            if data.startswith(mlp.SEL_POOL_TOKEN1):
                return "0x" + _addr_word(hop_pool_tokens[to][1])
        raise AssertionError(f"unexpected eth_call: to={to} data={data[:10]}")
    return fake


def _fake_eth_get_logs(logs_by_pool, queried=None):
    def fake(chain, address, topics, from_block, to_block, timeout=30):
        if queried is not None:
            queried.append((address.lower(), to_block - from_block + 1))
        return logs_by_pool.get(address.lower(), [])
    return fake


# ── b) Base cbADA/cbBTC via the cbBTC/USDC hop ────────────────────────────

def test_base_cbada_cbbtc_prices_via_cbbtc_usdc_hop(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call())
    monkeypatch.setattr(mli, "eth_get_logs", _fake_eth_get_logs({
        mlp.BASE_CBBTC_HOP_POOL: BASE_HOP_LOGS, BASE_POS_POOL: BASE_POS_LOGS,
    }))

    token0_usd, token1_usd, pool, stats = mlp.token0_token1_usd_at_block(
        "base", NPM, 100, target_block=TARGET_BLOCK, pool=BASE_CBADA_CBBTC_POOL
    )

    assert stats["reason"] is None
    assert stats["hop_anchor"] == "cbBTC"
    assert token1_usd == pytest.approx(100_000.0, rel=1e-9)  # cbBTC, from the hop fixture
    assert token0_usd == pytest.approx(0.50, rel=1e-9)  # cbADA, off the position pool's ratio
    # 6/8/6-decimal orientation honored - the deliberately-wrong values:
    assert token1_usd != pytest.approx(1e-5, rel=1e-3)  # hop pool read as cbBTC-per-USDC inverted
    assert token0_usd != pytest.approx(2e10, rel=1e-3)  # position pool anchor side inverted
    # token0()/token1() + 2 hop decimals, then the two walks
    assert stats["rpc_calls"] == 4 + stats["swap_walk_calls"]
    assert stats["swap_walk_calls"] == 2


# ── c) Robinhood cbBTC/MSTR via the cbBTC/USDG hop ─────────────────────────

def test_rh_cbbtc_mstr_prices_via_cbbtc_usdg_hop(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call())
    monkeypatch.setattr(mli, "eth_get_logs", _fake_eth_get_logs({
        mlp.RH_CBBTC_HOP_POOL: RH_HOP_LOGS, RH_POS_POOL: RH_POS_LOGS,
    }))

    token0_usd, token1_usd, pool, stats = mlp.token0_token1_usd_at_block(
        "robinhood", NPM, 1063377, target_block=TARGET_BLOCK, pool=RH_CBBTC_MSTR_POOL
    )

    assert stats["reason"] is None
    assert stats["hop_anchor"] == "cbBTC"
    assert token0_usd == pytest.approx(100_000.0, rel=1e-9)  # cbBTC (USDG pinned $1.00)
    assert token1_usd == pytest.approx(400.0, rel=1e-9)  # MSTR, 18 dec
    assert token1_usd != pytest.approx(2.5e7, rel=1e-3)  # wrong orientation on the position pool


# ── d) window selection per (chain, anchor) ───────────────────────────────

def _record_windows(monkeypatch):
    seen = {}

    def fake_walk(chain, pool_address, target_block, window=None, max_windows=mlp.DEFAULT_SWAP_WALK_MAX_WINDOWS):
        seen[pool_address.lower()] = window
        return [], {"windows_checked": 1, "calls": 1, "found_at_block": None}

    monkeypatch.setattr(mlp, "swap_logs_backward", fake_walk)
    return seen


def test_cbbtc_hop_walk_uses_10x_window_weth_unchanged(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call())
    seen = _record_windows(monkeypatch)

    mlp.token0_token1_usd_at_block("base", NPM, 1, target_block=TARGET_BLOCK, pool=BASE_CBADA_CBBTC_POOL)
    mlp.token0_token1_usd_at_block("robinhood", NPM, 2, target_block=TARGET_BLOCK, pool=RH_CBBTC_MSTR_POOL)
    assert seen[mlp.BASE_CBBTC_HOP_POOL] == mlp.HOP_ANCHOR_WALK_WINDOW_BLOCKS[("base", "cbBTC")] == 20_000
    assert seen[mlp.RH_CBBTC_HOP_POOL] == mlp.HOP_ANCHOR_WALK_WINDOW_BLOCKS[("robinhood", "cbBTC")] == 200_000

    # WETH still gets 3b.2.5's values - the registry references the old constant.
    rh_weth_hop = "0x" + "ab" * 20
    monkeypatch.setitem(mlp._HOP_POOL_CACHE, "robinhood", rh_weth_hop)
    alt = "0x" + "dd" * 20
    mlp.token0_token1_usd_at_block("base", NPM, 3, target_block=TARGET_BLOCK, pool={
        "pool_address": "0x" + "e1" * 20, "token0": alt, "token1": mlp.ADDR_BASE_WETH,
        "fee": 3000, "decimals0": 18, "decimals1": 18,
    })
    mlp.token0_token1_usd_at_block("robinhood", NPM, 4, target_block=TARGET_BLOCK, pool={
        "pool_address": "0x" + "e2" * 20, "token0": alt, "token1": mlp.ADDR_RH_WETH,
        "fee": 3000, "decimals0": 18, "decimals1": 18,
    })
    assert seen[mlp.BASE_HOP_POOL] == mlp.HOP_POOL_WALK_WINDOW_BLOCKS["base"] == 2_000
    assert seen[rh_weth_hop] == mlp.HOP_POOL_WALK_WINDOW_BLOCKS["robinhood"] == 20_000


# ── e) precedence: WETH before cbBTC when both sides are anchors ──────────

def test_weth_takes_precedence_over_cbbtc(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call())
    seen = _record_windows(monkeypatch)
    weth_cbbtc_pool = {  # WETH 0x4200... < cbBTC 0xcbb7... -> WETH is token0
        "pool_address": "0x" + "e3" * 20, "token0": mlp.ADDR_BASE_WETH, "token1": mlp.ADDR_BASE_CBBTC,
        "fee": 500, "decimals0": 18, "decimals1": 8,
    }

    _, _, _, stats = mlp.token0_token1_usd_at_block("base", NPM, 5, target_block=TARGET_BLOCK, pool=weth_cbbtc_pool)

    assert stats["hop_anchor"] == "WETH"
    assert mlp.BASE_HOP_POOL in seen
    assert mlp.BASE_CBBTC_HOP_POOL not in seen
    assert mlp.HOP_ANCHORS["base"][0]["symbol"] == "WETH"  # registry order IS the precedence


# ── f) unpriceable_pair tightened + hop_anchor on failures ────────────────

def test_unpriceable_pair_only_when_neither_stable_nor_any_anchor(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("no RPC should be made for an unpriceable pair")

    monkeypatch.setattr(mli, "eth_call", _boom)
    monkeypatch.setattr(mli, "eth_get_logs", _boom)

    token0_usd, token1_usd, _, stats = mlp.token0_token1_usd_at_block("base", NPM, 6, target_block=TARGET_BLOCK, pool={
        "pool_address": "0x" + "e4" * 20, "token0": "0x" + "ee" * 20, "token1": "0x" + "ff" * 20,
        "fee": 500, "decimals0": 18, "decimals1": 18,
    })

    assert (token0_usd, token1_usd) == (None, None)
    assert stats["reason"] == "unpriceable_pair"
    assert stats["hop_anchor"] is None


def test_cbbtc_side_failure_carries_hop_anchor(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call())
    monkeypatch.setattr(mli, "eth_get_logs", _fake_eth_get_logs({}))  # no Swap anywhere

    _, _, _, stats = mlp.token0_token1_usd_at_block("base", NPM, 7, target_block=TARGET_BLOCK, pool=BASE_CBADA_CBBTC_POOL)

    assert stats["reason"] == "hop_price_unavailable"
    assert stats["hop_anchor"] == "cbBTC"


# ── g) hop_price_unavailable on the cbBTC hop pool, no wider fallback ─────

def test_rh_cbbtc_hop_no_swap_in_window_fails_without_widening(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call())
    queried = []
    monkeypatch.setattr(mli, "eth_get_logs", _fake_eth_get_logs({}, queried))

    token0_usd, token1_usd, _, stats = mlp.token0_token1_usd_at_block(
        "robinhood", NPM, 1063377, target_block=10_000_000, pool=RH_CBBTC_MSTR_POOL
    )

    assert (token0_usd, token1_usd) == (None, None)
    assert stats["reason"] == "hop_price_unavailable"
    assert {a for a, _ in queried} == {mlp.RH_CBBTC_HOP_POOL}  # position pool never walked
    assert max(w for _, w in queried) <= 200_000  # never widened past the cbBTC window
    assert stats["windows_checked"] <= mlp.DEFAULT_SWAP_WALK_MAX_WINDOWS  # max_windows unchanged


# ── h) a mis-ruled hop pool is caught, never mis-priced ───────────────────

def test_ruled_hop_pool_with_wrong_tokens_is_hop_pool_mismatch(monkeypatch):
    wrong = dict(HOP_POOL_TOKENS)
    wrong[mlp.BASE_CBBTC_HOP_POOL] = (mlp.ADDR_BASE_USDC, "0x" + "ee" * 20)  # not cbBTC
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call(wrong))
    queried = []
    monkeypatch.setattr(mli, "eth_get_logs", _fake_eth_get_logs({}, queried))

    token0_usd, token1_usd, _, stats = mlp.token0_token1_usd_at_block("base", NPM, 8, target_block=TARGET_BLOCK, pool=BASE_CBADA_CBBTC_POOL)

    assert (token0_usd, token1_usd) == (None, None)
    assert stats["reason"] == "hop_pool_mismatch"
    assert stats["hop_anchor"] == "cbBTC"
    assert queried == []  # no walk on a pool that failed verification


# ── registry integrity ────────────────────────────────────────────────────

def test_registry_references_existing_constants_lowercase_weth_first():
    for chain, entries in mlp.HOP_ANCHORS.items():
        assert [e["symbol"] for e in entries] == ["WETH", "cbBTC"]
        for e in entries:
            for key in ("token", "stable", "hop_pool"):
                if e[key] is not None:
                    assert e[key] == e[key].lower()
    assert mlp.HOP_ANCHORS["base"][0]["hop_pool"] is mlp.BASE_HOP_POOL
    assert mlp.HOP_ANCHORS["base"][0]["token"] is mlp.ADDR_BASE_WETH
    assert mlp.HOP_ANCHORS["robinhood"][0]["hop_pool"] is None  # resolved at runtime, as before
    assert mlp.HOP_ANCHORS["base"][1]["hop_pool"] is mlp.BASE_CBBTC_HOP_POOL
    assert mlp.HOP_ANCHORS["robinhood"][1]["hop_pool"] is mlp.RH_CBBTC_HOP_POOL
