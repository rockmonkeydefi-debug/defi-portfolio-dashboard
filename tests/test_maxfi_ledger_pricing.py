"""Tests for maxfi_ledger_pricing.py (HANDOFF_maxfi_ledger.md Commit
3b.2) - the RPC layer for Swap-log USD pricing. No network: every test
monkeypatches maxfi_ledger_ingest.eth_call/scan_logs_chunked directly,
same boundary tests/test_maxfi_ledger_ingest.py uses against
maxfi_ledger_ingest's own transport functions.
"""

from decimal import Decimal

import pytest

import maxfi_ledger as ml
import maxfi_ledger_ingest as mli
import maxfi_ledger_pricing as mlp


@pytest.fixture(autouse=True)
def _clear_caches():
    mlp._DECIMALS_CACHE.clear()
    mlp._POOL_RESOLUTION_CACHE.clear()
    mlp._HOP_POOL_CACHE.clear()
    mlp._POOL_TOKENS_CACHE.clear()  # Commit 3b.2.1
    yield
    mlp._DECIMALS_CACHE.clear()
    mlp._POOL_RESOLUTION_CACHE.clear()
    mlp._HOP_POOL_CACHE.clear()
    mlp._POOL_TOKENS_CACHE.clear()


def _addr_word(address):
    h = address[2:] if address.startswith("0x") else address
    return h.lower().zfill(64)


def _uint_word(value):
    return format(value, "064x")


def _npm_positions_result(token0, token1, fee):
    """12-word npm.positions(tokenId) result - only words 2/3/4
    (token0/token1/fee) are meaningful to this module; the rest are
    dummy zero words, matching decode_npm_position's real 12-word
    layout (maxfi_client.py)."""
    words = [_uint_word(0)] * 12
    words[2] = _addr_word(token0)
    words[3] = _addr_word(token1)
    words[4] = _uint_word(fee)
    return "0x" + "".join(words)


BASE = "base"
NPM = "0x" + "77" * 20
FACTORY = "0x" + "88" * 20
POOL = "0x" + "99" * 20
TOKEN_A = "0x" + "aa" * 20
TOKEN_B = "0x" + "bb" * 20


# ── get_decimals ──────────────────────────────────────────────────────────

def test_get_decimals_returns_value_and_caches(monkeypatch):
    calls = {"n": 0}

    def fake_eth_call(chain, to, data, timeout=30):
        calls["n"] += 1
        return "0x" + _uint_word(18)

    monkeypatch.setattr(mli, "eth_call", fake_eth_call)

    d1 = mlp.get_decimals(BASE, TOKEN_A)
    d2 = mlp.get_decimals(BASE, TOKEN_A)

    assert d1 == d2 == 18
    assert calls["n"] == 1  # second call served from cache


def test_get_decimals_returns_none_on_rpc_error(monkeypatch):
    def fake_eth_call_fail(chain, to, data, timeout=30):
        raise mli.MaxFiRpcError("boom")

    monkeypatch.setattr(mli, "eth_call", fake_eth_call_fail)

    assert mlp.get_decimals(BASE, TOKEN_A) is None
    assert (BASE, TOKEN_A.lower()) not in mlp._DECIMALS_CACHE


# ── get_npm_position_tokens ───────────────────────────────────────────────

def test_get_npm_position_tokens_decodes_token0_token1_fee(monkeypatch):
    monkeypatch.setattr(
        mli, "eth_call",
        lambda chain, to, data, timeout=30: _npm_positions_result(TOKEN_A, TOKEN_B, 500),
    )

    result = mlp.get_npm_position_tokens(BASE, NPM, 100)

    assert result == {"token0": TOKEN_A.lower(), "token1": TOKEN_B.lower(), "fee": 500}


def test_get_npm_position_tokens_none_on_rpc_error(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", lambda *a, **k: (_ for _ in ()).throw(mli.MaxFiRpcError("boom")))
    assert mlp.get_npm_position_tokens(BASE, NPM, 100) is None


def test_get_npm_position_tokens_none_on_short_result(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", lambda *a, **k: "0x" + _uint_word(0))
    assert mlp.get_npm_position_tokens(BASE, NPM, 100) is None


# ── get_factory / get_pool ─────────────────────────────────────────────────

def test_get_factory_decodes_address(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", lambda chain, to, data, timeout=30: "0x" + _addr_word(FACTORY))
    assert mlp.get_factory(BASE, NPM) == FACTORY.lower()


def test_get_factory_none_on_rpc_error(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", lambda *a, **k: (_ for _ in ()).throw(mli.MaxFiRpcError("boom")))
    assert mlp.get_factory(BASE, NPM) is None


def test_get_pool_decodes_nonzero_address(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", lambda chain, to, data, timeout=30: "0x" + _addr_word(POOL))
    assert mlp.get_pool(BASE, FACTORY, TOKEN_A, TOKEN_B, 500) == POOL.lower()


def test_get_pool_returns_zero_address_as_is_not_none(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", lambda chain, to, data, timeout=30: "0x" + _uint_word(0))
    assert mlp.get_pool(BASE, FACTORY, TOKEN_A, TOKEN_B, 500) == mlp._ZERO_ADDRESS


def test_get_pool_none_on_rpc_error(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", lambda *a, **k: (_ for _ in ()).throw(mli.MaxFiRpcError("boom")))
    assert mlp.get_pool(BASE, FACTORY, TOKEN_A, TOKEN_B, 500) is None


# ── resolve_position_pool ───────────────────────────────────────────────

def test_resolve_position_pool_full_success_and_caches(monkeypatch):
    calls = {"n": 0}

    def fake_eth_call(chain, to, data, timeout=30):
        calls["n"] += 1
        if data.startswith(mlp.SEL_NPM_POSITIONS):
            return _npm_positions_result(TOKEN_A, TOKEN_B, 500)
        if data.startswith(mlp.SEL_NPM_FACTORY):
            return "0x" + _addr_word(FACTORY)
        if data.startswith(mlp.SEL_FACTORY_GET_POOL):
            return "0x" + _addr_word(POOL)
        if data.startswith(mlp.SEL_ERC20_DECIMALS):
            return "0x" + _uint_word(18 if to == TOKEN_A.lower() else 6)
        raise AssertionError(f"unexpected call: {data}")

    monkeypatch.setattr(mli, "eth_call", fake_eth_call)

    # Commit 3b.2.1: resolve_position_pool() now returns (pool, reason).
    result1, reason1 = mlp.resolve_position_pool(BASE, NPM, 100)
    result2, reason2 = mlp.resolve_position_pool(BASE, NPM, 100)

    assert result1 == result2 == {
        "pool_address": POOL.lower(), "token0": TOKEN_A.lower(), "token1": TOKEN_B.lower(),
        "fee": 500, "decimals0": 18, "decimals1": 6, "pool_source": "npm_positions",
    }
    assert reason1 is None and reason2 is None
    calls_after_first = calls["n"]
    mlp.resolve_position_pool(BASE, NPM, 100)
    assert calls["n"] == calls_after_first  # second resolve served entirely from cache


def test_resolve_position_pool_none_when_pool_is_zero_address(monkeypatch):
    def fake_eth_call(chain, to, data, timeout=30):
        if data.startswith(mlp.SEL_NPM_POSITIONS):
            return _npm_positions_result(TOKEN_A, TOKEN_B, 500)
        if data.startswith(mlp.SEL_NPM_FACTORY):
            return "0x" + _addr_word(FACTORY)
        if data.startswith(mlp.SEL_FACTORY_GET_POOL):
            return "0x" + _uint_word(0)
        raise AssertionError("decimals must never be looked up when the pool is unresolved")

    monkeypatch.setattr(mli, "eth_call", fake_eth_call)
    # Commit 3b.2.1: (None, "pool_unresolved") in place of a bare None.
    result, reason = mlp.resolve_position_pool(BASE, NPM, 100)
    assert result is None
    assert reason == "pool_unresolved"
    assert (BASE, "100") not in mlp._POOL_RESOLUTION_CACHE


def test_resolve_position_pool_none_on_positions_failure(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", lambda *a, **k: (_ for _ in ()).throw(mli.MaxFiRpcError("boom")))
    # Commit 3b.2.1: (None, "pool_tokens_unresolved") in place of a bare None.
    result, reason = mlp.resolve_position_pool(BASE, NPM, 100)
    assert result is None
    assert reason == "pool_tokens_unresolved"


# ── Commit 3b.2.1: pool_address given -> mint_receipt path, no NPM calls ──

def test_resolve_position_pool_with_pool_address_skips_npm_calls_entirely(monkeypatch):
    """The whole point of spec error #25's fix: when pool_address is
    given (from the mint receipt), resolve_position_pool() must make NO
    npm.positions()/factory()/getPool() call at all - those revert for a
    burned NFT. Only token0()/token1()/decimals() on the pool/token
    contracts, which never burn."""
    calls = []

    def fake_eth_call(chain, to, data, timeout=30):
        calls.append(data[:10])
        if data.startswith(mlp.SEL_POOL_TOKEN0):
            return "0x" + _addr_word(TOKEN_A)
        if data.startswith(mlp.SEL_POOL_TOKEN1):
            return "0x" + _addr_word(TOKEN_B)
        if data.startswith(mlp.SEL_ERC20_DECIMALS):
            return "0x" + _uint_word(18 if to == TOKEN_A.lower() else 6)
        raise AssertionError(f"unexpected call (should never happen on the mint_receipt path): {data}")

    monkeypatch.setattr(mli, "eth_call", fake_eth_call)

    result, reason = mlp.resolve_position_pool(BASE, NPM, 100, pool_address=POOL)

    assert reason is None
    assert result == {
        "pool_address": POOL.lower(), "token0": TOKEN_A.lower(), "token1": TOKEN_B.lower(),
        "fee": None, "decimals0": 18, "decimals1": 6, "pool_source": "mint_receipt",
    }
    assert not any(c.startswith(mlp.SEL_NPM_POSITIONS) for c in calls)
    assert not any(c.startswith(mlp.SEL_NPM_FACTORY) for c in calls)
    assert not any(c.startswith(mlp.SEL_FACTORY_GET_POOL) for c in calls)


def test_resolve_position_pool_without_pool_address_uses_npm_positions_path(monkeypatch):
    """Without pool_address, falls back to the original npm.positions()
    -> factory() -> getPool() path - still valid for a live NFT."""
    def fake_eth_call(chain, to, data, timeout=30):
        if data.startswith(mlp.SEL_NPM_POSITIONS):
            return _npm_positions_result(TOKEN_A, TOKEN_B, 500)
        if data.startswith(mlp.SEL_NPM_FACTORY):
            return "0x" + _addr_word(FACTORY)
        if data.startswith(mlp.SEL_FACTORY_GET_POOL):
            return "0x" + _addr_word(POOL)
        if data.startswith(mlp.SEL_ERC20_DECIMALS):
            return "0x" + _uint_word(18 if to == TOKEN_A.lower() else 6)
        raise AssertionError(f"unexpected call: {data}")

    monkeypatch.setattr(mli, "eth_call", fake_eth_call)

    result, reason = mlp.resolve_position_pool(BASE, NPM, 100)

    assert reason is None
    assert result["pool_source"] == "npm_positions"
    assert result["fee"] == 500


def test_resolve_position_pool_with_pool_address_none_tokens_reason(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", lambda *a, **k: (_ for _ in ()).throw(mli.MaxFiRpcError("boom")))
    result, reason = mlp.resolve_position_pool(BASE, NPM, 100, pool_address=POOL)
    assert result is None
    assert reason == "pool_tokens_unresolved"


def test_resolve_position_pool_with_pool_address_decimals_unresolved_reason(monkeypatch):
    def fake_eth_call(chain, to, data, timeout=30):
        if data.startswith(mlp.SEL_POOL_TOKEN0):
            return "0x" + _addr_word(TOKEN_A)
        if data.startswith(mlp.SEL_POOL_TOKEN1):
            return "0x" + _addr_word(TOKEN_B)
        raise mli.MaxFiRpcError("boom")  # decimals() fails

    monkeypatch.setattr(mli, "eth_call", fake_eth_call)
    result, reason = mlp.resolve_position_pool(BASE, NPM, 100, pool_address=POOL)
    assert result is None
    assert reason == "decimals_unresolved"


# ── resolve_rh_hop_pool ───────────────────────────────────────────────────

def test_resolve_rh_hop_pool_probes_fee_tiers_first_nonzero_wins(monkeypatch):
    probed_fees = []

    def fake_eth_call(chain, to, data, timeout=30):
        if data.startswith(mlp.SEL_NPM_FACTORY):
            return "0x" + _addr_word(FACTORY)
        if data.startswith(mlp.SEL_FACTORY_GET_POOL):
            fee = int(data[-64:], 16)
            probed_fees.append(fee)
            if fee == 3000:
                return "0x" + _addr_word(POOL)
            return "0x" + _uint_word(0)
        raise AssertionError(f"unexpected call: {data}")

    monkeypatch.setattr(mli, "eth_call", fake_eth_call)

    result = mlp.resolve_rh_hop_pool("robinhood", NPM)

    assert result == POOL.lower()
    assert probed_fees == [100, 500, 3000]  # stops at the first non-zero


def test_resolve_rh_hop_pool_all_four_zero_returns_none(monkeypatch):
    def fake_eth_call(chain, to, data, timeout=30):
        if data.startswith(mlp.SEL_NPM_FACTORY):
            return "0x" + _addr_word(FACTORY)
        if data.startswith(mlp.SEL_FACTORY_GET_POOL):
            return "0x" + _uint_word(0)
        raise AssertionError(f"unexpected call: {data}")

    monkeypatch.setattr(mli, "eth_call", fake_eth_call)

    assert mlp.resolve_rh_hop_pool("robinhood", NPM) is None
    assert "robinhood" not in mlp._HOP_POOL_CACHE


def test_resolve_rh_hop_pool_caches_across_calls(monkeypatch):
    calls = {"n": 0}

    def fake_eth_call(chain, to, data, timeout=30):
        calls["n"] += 1
        if data.startswith(mlp.SEL_NPM_FACTORY):
            return "0x" + _addr_word(FACTORY)
        return "0x" + _addr_word(POOL)

    monkeypatch.setattr(mli, "eth_call", fake_eth_call)

    r1 = mlp.resolve_rh_hop_pool("robinhood", NPM)
    calls_after_first = calls["n"]
    r2 = mlp.resolve_rh_hop_pool("robinhood", NPM)

    assert r1 == r2
    assert calls["n"] == calls_after_first  # second call fully cached


# ── swap_logs_backward ────────────────────────────────────────────────────

def _swap_log(block_number):
    return {
        "address": POOL,
        "topics": [ml.TOPIC_SWAP, "0x" + "11" * 32, "0x" + "22" * 32],
        "data": "0x" + "00" * 160,
        "blockNumber": hex(block_number),
        "timeStamp": hex(1700000000 + block_number),
        "transactionHash": "0x" + format(block_number, "x").rjust(64, "0"),
        "logIndex": "0x0",
    }


def test_swap_logs_backward_finds_in_first_window(monkeypatch):
    def fake_eth_get_logs(chain, address, topics, from_block, to_block, timeout=30):
        return [_swap_log(to_block)]

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)

    logs, stats = mlp.swap_logs_backward(BASE, POOL, target_block=100_000, window=1000)

    assert len(logs) == 1
    assert stats["windows_checked"] == 1
    # Commit 3b.2.1 fix: found_at_block is the SELECTED Swap's own block
    # (the fake returns a log at to_block=100_000, the window's END, not
    # its start 99_001 - the old, cosmetically-wrong value this test used
    # to pin).
    assert stats["found_at_block"] == 100_000


def test_swap_logs_backward_adapts_raw_rpc_shape_logs(monkeypatch):
    """Regression pin (hotfix 3b.1.2's own finding): a REAL eth_getLogs
    record has no "timeStamp" field - only Alchemy's non-standard
    "blockTimestamp", or neither. Handed to maxfi_ledger.decode_log()
    unadapted, it KeyErrors (proved directly below) - swap_logs_backward's
    own docstring promises its returned logs are already decode_log()-
    ready, so its OWN output, built from this exact raw shape, must
    decode cleanly, unlike every other test here's already-Etherscan-
    shape test doubles (convenient, but never exercises this adaptation
    step)."""
    raw_log = {
        "address": POOL,
        "topics": [ml.TOPIC_SWAP, "0x" + "11" * 32, "0x" + "22" * 32],
        "data": "0x" + "00" * 160,
        "blockNumber": hex(99_500),
        "blockTimestamp": hex(1700000000),  # Alchemy shape, not "timeStamp"
        "transactionHash": "0x" + format(99_500, "x").rjust(64, "0"),
        "logIndex": "0x0",
    }
    with pytest.raises(KeyError):
        ml.decode_log(raw_log)  # proves the raw shape really would KeyError unadapted

    monkeypatch.setattr(mli, "eth_get_logs", lambda chain, address, topics, from_block, to_block, timeout=30: [raw_log])

    logs, stats = mlp.swap_logs_backward(BASE, POOL, target_block=100_000, window=1000)

    assert len(logs) == 1
    record = ml.decode_log(logs[0])  # must NOT raise now that it's adapted
    assert record is not None
    assert record["event_type"] == "Swap"


def test_swap_logs_backward_steps_back_multiple_windows(monkeypatch):
    def fake_eth_get_logs(chain, address, topics, from_block, to_block, timeout=30):
        if to_block < 97_000:
            return [_swap_log(to_block)]
        return []

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)

    logs, stats = mlp.swap_logs_backward(BASE, POOL, target_block=100_000, window=1000, max_windows=10)

    assert len(logs) == 1
    assert stats["windows_checked"] > 1


def test_swap_logs_backward_exhausts_cap_returns_empty(monkeypatch):
    monkeypatch.setattr(mli, "eth_get_logs", lambda *a, **k: [])

    logs, stats = mlp.swap_logs_backward(BASE, POOL, target_block=100_000, window=1000, max_windows=5)

    assert logs == []
    assert stats["windows_checked"] == 5
    assert stats["found_at_block"] is None


# ── swap_logs_backward per-chain default window (Commit 3b.2.3) ──────────

def test_swap_logs_backward_default_window_is_per_chain(monkeypatch):
    """No explicit window= - Base defaults to 10_000, Robinhood to
    2_000_000 (SWAP_WALK_WINDOW_BLOCKS; Commit 3b.2.4 raised it from
    200_000 - ~19 RPC calls/lookup measured on Sep 20 - to match
    DEFAULT_CHUNK_SIZE, so one window is one call)."""
    seen = {}

    def fake_eth_get_logs(chain, address, topics, from_block, to_block, timeout=30):
        seen[chain] = to_block - from_block + 1
        return []

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)

    mlp.swap_logs_backward(BASE, POOL, target_block=1_000_000, max_windows=1)
    # target_block must exceed the 2M window, or the walk clips at block 0
    # and the measured span would be target_block + 1, not the window.
    mlp.swap_logs_backward("robinhood", POOL, target_block=10_000_000, max_windows=1)

    assert seen[BASE] == 10_000
    assert seen["robinhood"] == 2_000_000


def test_swap_logs_backward_explicit_window_overrides_chain_default(monkeypatch):
    seen = {}

    def fake_eth_get_logs(chain, address, topics, from_block, to_block, timeout=30):
        seen[chain] = to_block - from_block + 1
        return []

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)

    mlp.swap_logs_backward("robinhood", POOL, target_block=1_000_000, window=777, max_windows=1)

    assert seen["robinhood"] == 777


# ── token0_token1_usd_at_block ────────────────────────────────────────────

def _sqrt_price_x96_for(price_t1_per_t0, decimals0, decimals1):
    Q96 = 2 ** 96
    ratio_squared = Decimal(price_t1_per_t0) / (Decimal(10) ** (decimals0 - decimals1))
    return int(ratio_squared.sqrt() * Q96)


def _synthetic_swap_log(sqrt_price_x96, pool_address, block_number):
    words = [format(0, "064x"), format(0, "064x"), format(sqrt_price_x96, "064x"), format(0, "064x"), format(0, "064x")]
    return {
        "address": pool_address,
        "topics": [ml.TOPIC_SWAP, "0x" + "11" * 32, "0x" + "22" * 32],
        "data": "0x" + "".join(words),
        "blockNumber": hex(block_number),
        "timeStamp": hex(1700000000 + block_number),
        "transactionHash": "0x" + format(block_number, "x").rjust(64, "0"),
        "logIndex": "0x0",
    }


def test_token0_token1_usd_direct_stable(monkeypatch):
    """Position pool = ALT(token0, dec18)/USDC(token1, dec6, the Base
    stable), rate fixed at $3/ALT."""
    alt = "0x" + "cc" * 20
    pool_resolution = {
        "pool_address": POOL, "token0": alt, "token1": mlp.ADDR_BASE_USDC,
        "fee": 500, "decimals0": 18, "decimals1": 6,
    }
    sqrt_price_x96 = _sqrt_price_x96_for(3.0, decimals0=18, decimals1=6)

    def fake_eth_get_logs(chain, address, topics, from_block, to_block, timeout=30):
        return [_synthetic_swap_log(sqrt_price_x96, POOL, to_block)]

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)

    token0_usd, token1_usd, pool, stats = mlp.token0_token1_usd_at_block(
        BASE, NPM, 100, target_block=5000, pool=pool_resolution
    )

    assert token1_usd == 1.0  # USDC
    assert abs(token0_usd - 3.0) / 3.0 < 1e-9  # ALT
    assert pool == pool_resolution
    assert stats["swap_walk_calls"] >= 1


def test_token0_token1_usd_hop_via_weth(monkeypatch, ):
    """Position pool = ALT(token0, dec18)/WETH(token1, dec18, Base's
    WETH), no direct stable side - must hop through BASE_HOP_POOL."""
    alt = "0x" + "dd" * 20
    pool_resolution = {
        "pool_address": POOL, "token0": alt, "token1": mlp.ADDR_BASE_WETH,
        "fee": 3000, "decimals0": 18, "decimals1": 18,
    }
    # Hop pool: WETH(token0, dec18)/USDC(token1, dec6) at $2000/WETH.
    hop_sqrt_price_x96 = _sqrt_price_x96_for(2000.0, decimals0=18, decimals1=6)
    # Position pool: 0.0005 WETH per 1 ALT (= $1/ALT at $2000/WETH).
    position_sqrt_price_x96 = _sqrt_price_x96_for(0.0005, decimals0=18, decimals1=18)

    def fake_eth_call(chain, to, data, timeout=30):
        assert data.startswith(mlp.SEL_ERC20_DECIMALS)
        if to == mlp.ADDR_BASE_WETH:
            return "0x" + _uint_word(18)
        if to == mlp.ADDR_BASE_USDC:
            return "0x" + _uint_word(6)
        raise AssertionError(f"unexpected decimals() call: {to}")

    def fake_eth_get_logs(chain, address, topics, from_block, to_block, timeout=30):
        if address == mlp.BASE_HOP_POOL:
            return [_synthetic_swap_log(hop_sqrt_price_x96, mlp.BASE_HOP_POOL, to_block)]
        if address == POOL:
            return [_synthetic_swap_log(position_sqrt_price_x96, POOL, to_block)]
        raise AssertionError(f"unexpected pool address: {address}")

    monkeypatch.setattr(mli, "eth_call", fake_eth_call)
    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)

    token0_usd, token1_usd, pool, stats = mlp.token0_token1_usd_at_block(
        BASE, NPM, 100, target_block=5000, pool=pool_resolution
    )

    assert abs(token1_usd - 2000.0) / 2000.0 < 1e-9  # WETH
    assert abs(token0_usd - 1.0) / 1.0 < 1e-9  # ALT
    assert stats["swap_walk_calls"] >= 2  # one hop-pool walk + one position-pool walk


def test_token0_token1_usd_no_priced_path_returns_none(monkeypatch):
    """Neither side is a known stable or WETH-like anchor - no hop path
    exists, must return (None, None, pool, stats), never guess."""
    pool_resolution = {
        "pool_address": POOL, "token0": "0x" + "ee" * 20, "token1": "0x" + "ff" * 20,
        "fee": 500, "decimals0": 18, "decimals1": 18,
    }

    def _boom(*a, **k):
        raise AssertionError("no RPC call should be made when neither side has a priced path")

    monkeypatch.setattr(mli, "eth_get_logs", _boom)

    token0_usd, token1_usd, pool, stats = mlp.token0_token1_usd_at_block(
        BASE, NPM, 100, target_block=5000, pool=pool_resolution
    )

    assert token0_usd is None
    assert token1_usd is None
    assert pool == pool_resolution
    assert stats["reason"] == "unpriceable_pair"  # Commit 3b.2.1


def test_token0_token1_usd_pool_resolution_failure_returns_none_pool(monkeypatch):
    monkeypatch.setattr(mli, "eth_call", lambda *a, **k: (_ for _ in ()).throw(mli.MaxFiRpcError("boom")))

    token0_usd, token1_usd, pool, stats = mlp.token0_token1_usd_at_block(BASE, NPM, 100, target_block=5000)

    assert token0_usd is None
    assert token1_usd is None
    assert pool is None
    assert stats["reason"] == "pool_tokens_unresolved"  # Commit 3b.2.1


def test_token0_token1_usd_no_swap_in_reach_reason(monkeypatch):
    pool_resolution = {
        "pool_address": POOL, "token0": "0x" + "cc" * 20, "token1": mlp.ADDR_BASE_USDC,
        "fee": 500, "decimals0": 18, "decimals1": 6,
    }
    monkeypatch.setattr(mli, "eth_get_logs", lambda *a, **k: [])  # no Swap ever found

    token0_usd, token1_usd, pool, stats = mlp.token0_token1_usd_at_block(
        BASE, NPM, 100, target_block=5000, pool=pool_resolution
    )

    assert token0_usd is None and token1_usd is None
    assert stats["reason"] == "no_swap_in_reach"


def test_token0_token1_usd_hop_pool_unresolved_reason(monkeypatch):
    """Robinhood, hop path, all four RH hop-pool fee-tier probes come back
    zero - hop_pool_unresolved, not a guess."""
    alt = "0x" + "cc" * 20
    pool_resolution = {
        "pool_address": POOL, "token0": alt, "token1": mlp.ADDR_RH_WETH,
        "fee": 500, "decimals0": 18, "decimals1": 18,
    }

    def fake_eth_call(chain, to, data, timeout=30):
        if data.startswith(mlp.SEL_NPM_FACTORY):
            return "0x" + _addr_word(FACTORY)
        if data.startswith(mlp.SEL_FACTORY_GET_POOL):
            return "0x" + _uint_word(0)  # every fee tier: zero address
        raise AssertionError(f"unexpected call: {data}")

    monkeypatch.setattr(mli, "eth_call", fake_eth_call)

    token0_usd, token1_usd, pool, stats = mlp.token0_token1_usd_at_block(
        "robinhood", NPM, 100, target_block=5000, pool=pool_resolution
    )

    assert token0_usd is None and token1_usd is None
    assert stats["reason"] == "hop_pool_unresolved"


# ── token0_token1_usd_at_block rpc_calls accounting (Commit 3b.2.3) ──────

def test_token0_token1_usd_rpc_calls_counts_resolution_plus_walk(monkeypatch):
    """rpc_calls = every eth_call/eth_get_logs this invocation actually
    caused - pool resolution (npm.positions + factory + getPool +
    2x decimals = 5 calls, fresh/uncached) PLUS the swap walk's own
    call(s)."""
    alt = "0x" + "cc" * 20

    def fake_eth_call(chain, to, data, timeout=30):
        if data.startswith(mlp.SEL_NPM_POSITIONS):
            return _npm_positions_result(alt, mlp.ADDR_BASE_USDC, 500)
        if data.startswith(mlp.SEL_NPM_FACTORY):
            return "0x" + _addr_word(FACTORY)
        if data.startswith(mlp.SEL_FACTORY_GET_POOL):
            return "0x" + _addr_word(POOL)
        if data.startswith(mlp.SEL_ERC20_DECIMALS):
            return "0x" + _uint_word(18 if to == alt else 6)
        raise AssertionError(f"unexpected eth_call: {data}")

    sqrt_price_x96 = _sqrt_price_x96_for(3.0, decimals0=18, decimals1=6)
    monkeypatch.setattr(mli, "eth_call", fake_eth_call)
    monkeypatch.setattr(
        mli, "eth_get_logs",
        lambda chain, address, topics, from_block, to_block, timeout=30: [
            _synthetic_swap_log(sqrt_price_x96, POOL, to_block)
        ],
    )

    token0_usd, token1_usd, pool, stats = mlp.token0_token1_usd_at_block(BASE, NPM, 100, target_block=5000)

    assert token0_usd is not None
    assert stats["rpc_calls"] == 5 + stats["swap_walk_calls"]
    assert stats["swap_walk_calls"] >= 1


def test_token0_token1_usd_rpc_calls_zero_when_pool_pre_resolved(monkeypatch):
    """Caller-supplied `pool` (already resolved) skips resolve_position_
    pool() entirely - rpc_calls must equal exactly the swap walk's own
    calls, zero resolution calls attributed."""
    pool_resolution = {
        "pool_address": POOL, "token0": "0x" + "cc" * 20, "token1": mlp.ADDR_BASE_USDC,
        "fee": 500, "decimals0": 18, "decimals1": 6,
    }
    sqrt_price_x96 = _sqrt_price_x96_for(3.0, decimals0=18, decimals1=6)

    def _boom(*a, **k):
        raise AssertionError("no eth_call expected - pool was pre-resolved")

    monkeypatch.setattr(mli, "eth_call", _boom)
    monkeypatch.setattr(
        mli, "eth_get_logs",
        lambda chain, address, topics, from_block, to_block, timeout=30: [
            _synthetic_swap_log(sqrt_price_x96, POOL, to_block)
        ],
    )

    token0_usd, token1_usd, pool, stats = mlp.token0_token1_usd_at_block(
        BASE, NPM, 100, target_block=5000, pool=pool_resolution
    )

    assert token0_usd is not None
    assert stats["rpc_calls"] == stats["swap_walk_calls"]
    assert stats["swap_walk_calls"] >= 1


def test_token0_token1_usd_rpc_calls_zero_resolution_on_cache_hit(monkeypatch):
    """Two lookups for the SAME token_id (e.g. basis then exit) - the
    second hits resolve_position_pool()'s own cache, so its rpc_calls
    must count only that second call's own swap walk, zero resolution
    calls - even though the FIRST call did pay for resolution."""
    alt = "0x" + "cc" * 20

    def fake_eth_call(chain, to, data, timeout=30):
        if data.startswith(mlp.SEL_NPM_POSITIONS):
            return _npm_positions_result(alt, mlp.ADDR_BASE_USDC, 500)
        if data.startswith(mlp.SEL_NPM_FACTORY):
            return "0x" + _addr_word(FACTORY)
        if data.startswith(mlp.SEL_FACTORY_GET_POOL):
            return "0x" + _addr_word(POOL)
        if data.startswith(mlp.SEL_ERC20_DECIMALS):
            return "0x" + _uint_word(18 if to == alt else 6)
        raise AssertionError(f"unexpected eth_call: {data}")

    sqrt_price_x96 = _sqrt_price_x96_for(3.0, decimals0=18, decimals1=6)
    monkeypatch.setattr(mli, "eth_call", fake_eth_call)
    monkeypatch.setattr(
        mli, "eth_get_logs",
        lambda chain, address, topics, from_block, to_block, timeout=30: [
            _synthetic_swap_log(sqrt_price_x96, POOL, to_block)
        ],
    )

    _, _, _, stats1 = mlp.token0_token1_usd_at_block(BASE, NPM, 100, target_block=5000)
    _, _, _, stats2 = mlp.token0_token1_usd_at_block(BASE, NPM, 100, target_block=6000)

    assert stats1["rpc_calls"] == 5 + stats1["swap_walk_calls"]
    assert stats2["rpc_calls"] == stats2["swap_walk_calls"]  # cache hit: zero resolution calls


# ── hop-pool walk window + hop_price_unavailable (Commit 3b.2.5) ─────────

def test_hop_walk_uses_hop_window_and_position_walk_keeps_chain_window(monkeypatch):
    """Robinhood hop path: the HOP pool walk must pass
    HOP_POOL_WALK_WINDOW_BLOCKS["robinhood"] (20_000) while the POSITION
    pool walk still gets SWAP_WALK_WINDOW_BLOCKS["robinhood"] (2_000_000)
    - asserted on each swap_logs_backward call's own window kwarg. The
    hop walk returns a priced Swap so the position walk is reached."""
    alt = "0x" + "cc" * 20
    hop_pool = "0x" + "ee" * 20
    pool_resolution = {
        "pool_address": POOL, "token0": alt, "token1": mlp.ADDR_RH_WETH,
        "fee": 500, "decimals0": 18, "decimals1": 18,
    }
    monkeypatch.setitem(mlp._HOP_POOL_CACHE, "robinhood", hop_pool)
    monkeypatch.setitem(mlp._DECIMALS_CACHE, ("robinhood", mlp.ADDR_RH_WETH), 18)
    monkeypatch.setitem(mlp._DECIMALS_CACHE, ("robinhood", mlp.ADDR_RH_USDG), 6)
    # Hop pool sorts to WETH(token0, dec18)/USDG(token1, dec6): $2000/WETH.
    hop_sqrt_price_x96 = _sqrt_price_x96_for(2000.0, decimals0=18, decimals1=6)
    seen = {}

    def fake_walk(chain, pool_address, target_block, window=None, max_windows=mlp.DEFAULT_SWAP_WALK_MAX_WINDOWS):
        seen[pool_address] = window
        if pool_address == hop_pool:
            return [_synthetic_swap_log(hop_sqrt_price_x96, hop_pool, target_block)], \
                   {"windows_checked": 1, "calls": 1, "found_at_block": target_block}
        return [], {"windows_checked": 1, "calls": 1, "found_at_block": None}

    monkeypatch.setattr(mlp, "swap_logs_backward", fake_walk)

    mlp.token0_token1_usd_at_block("robinhood", NPM, 100, target_block=5000, pool=pool_resolution)

    assert seen[hop_pool] == mlp.HOP_POOL_WALK_WINDOW_BLOCKS["robinhood"] == 20_000
    # The position walk passes NO window (None) - swap_logs_backward resolves
    # that to the chain default itself (pinned by
    # test_swap_logs_backward_default_window_is_per_chain); mirror that
    # resolution here to assert the effective window is still 2M.
    assert seen[POOL] is None
    effective = seen[POOL] if seen[POOL] is not None else mlp.SWAP_WALK_WINDOW_BLOCKS["robinhood"]
    assert effective == 2_000_000


def test_hop_walk_empty_reports_hop_price_unavailable(monkeypatch):
    """Base hop path, no Swap anywhere in the hop pool's own short walk -
    reason is hop_price_unavailable (not no_swap_in_reach, which is the
    POSITION pool's), no price, and no retry with a wider window."""
    alt = "0x" + "dd" * 20
    pool_resolution = {
        "pool_address": POOL, "token0": alt, "token1": mlp.ADDR_BASE_WETH,
        "fee": 3000, "decimals0": 18, "decimals1": 18,
    }
    monkeypatch.setitem(mlp._DECIMALS_CACHE, (BASE, mlp.ADDR_BASE_WETH), 18)
    monkeypatch.setitem(mlp._DECIMALS_CACHE, (BASE, mlp.ADDR_BASE_USDC), 6)
    queried = []

    def fake_eth_get_logs(chain, address, topics, from_block, to_block, timeout=30):
        queried.append((address, to_block - from_block + 1))
        return []

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)

    token0_usd, token1_usd, pool, stats = mlp.token0_token1_usd_at_block(
        BASE, NPM, 100, target_block=5000, pool=pool_resolution
    )

    assert token0_usd is None and token1_usd is None
    assert stats["reason"] == "hop_price_unavailable"
    assert {a for a, _ in queried} == {mlp.BASE_HOP_POOL}  # position pool never walked
    assert max(w for _, w in queried) <= mlp.HOP_POOL_WALK_WINDOW_BLOCKS["base"]  # never widened
