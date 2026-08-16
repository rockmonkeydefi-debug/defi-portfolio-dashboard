"""Tests for LP on-chain/Zerion coverage reconciliation (the WETH/USDC vs USDC/WETH defect).

The defect these guard against: two Uniswap V3 positions on the same Base pool in
one wallet rendered as "WETH/USDC — IN RANGE" and "USDC/WETH — UNKNOWN". They are
not two positions where one failed; they are one on-chain enriched row (named in
canonical pool order, token0 < token1 by address, so WETH/USDC on Base) plus one
tier-3 Zerion fallback row (named in Zerion's own deposit-leg order). The old
reconciliation counted Zerion groups against on-chain positions for the whole
(wallet, chain) without ever matching them by identity, so which row lost its
range data was decided by dict iteration order, and positions on unrelated pools
could consume each other's coverage slots.

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


# ─── lp_pair_key: order-independent pair identity ─────────────────────────────

def test_pair_key_is_order_independent():
    """The core of the reported defect: these are the same pool."""
    assert wp.lp_pair_key("WETH", "USDC") == wp.lp_pair_key("USDC", "WETH")


def test_pair_key_distinguishes_different_pairs():
    assert wp.lp_pair_key("WETH", "USDC") != wp.lp_pair_key("WETH", "DAI")


def test_pair_key_normalizes_case_and_whitespace():
    assert wp.lp_pair_key(" weth ", "usdc") == wp.lp_pair_key("WETH", "USDC")


def test_pair_key_treats_wrapped_and_native_as_equal():
    # An on-chain V3 pool leg is always WETH; Zerion may label it ETH.
    assert wp.lp_pair_key("WETH", "USDC") == wp.lp_pair_key("ETH", "USDC")
    assert wp.lp_pair_key("WBTC", "USDC") == wp.lp_pair_key("BTC", "USDC")


def test_pair_key_handles_missing_symbols():
    assert wp.lp_pair_key(None, None) == ("?", "?")
    assert wp.lp_pair_key("USDC", None) == wp.lp_pair_key(None, "USDC")


# ─── zerion_group_pair_key: derives the key from a Zerion group ────────────────

def _leg(symbol, position_type="deposit"):
    return {"attributes": {"fungible_info": {"symbol": symbol}, "position_type": position_type}}


def test_zerion_group_pair_key_matches_onchain_regardless_of_leg_order():
    """A Zerion group listing USDC first must match an on-chain WETH/USDC row."""
    group = [_leg("USDC"), _leg("WETH")]
    assert wp.zerion_group_pair_key(group) == wp.lp_pair_key("WETH", "USDC")


def test_zerion_group_pair_key_ignores_reward_legs():
    # Reward legs are uncollected fees, not principal — they must not be
    # mistaken for a pair token (map_zerion_lp_to_app excludes them too).
    group = [_leg("WETH"), _leg("USDC"), _leg("AERO", position_type="reward")]
    assert wp.zerion_group_pair_key(group) == wp.lp_pair_key("WETH", "USDC")


def test_zerion_group_pair_key_dedupes_repeated_symbols():
    group = [_leg("WETH"), _leg("WETH"), _leg("USDC")]
    assert wp.zerion_group_pair_key(group) == wp.lp_pair_key("WETH", "USDC")


def test_zerion_group_pair_key_handles_empty_group():
    assert wp.zerion_group_pair_key([]) == ("?", "?")


# ─── claim_onchain_coverage: which groups get a tier-3 fallback ────────────────

def test_both_orientations_of_same_pool_are_covered_by_two_enriched_rows():
    """THE REGRESSION TEST for the reported defect.

    Wallet holds two positions on the same Base pool; both enrich on-chain (so
    both are named WETH/USDC in canonical order). Zerion reports the same two
    positions, one group ordered WETH/USDC and the other USDC/WETH. Neither
    Zerion group may produce a tier-3 fallback row — both are already covered.
    """
    pk = wp.lp_pair_key("WETH", "USDC")
    remaining = {pk: 2}

    group_a = wp.zerion_group_pair_key([_leg("WETH"), _leg("USDC")])
    group_b = wp.zerion_group_pair_key([_leg("USDC"), _leg("WETH")])  # inverted

    assert wp.claim_onchain_coverage(group_a, remaining, groups_seen=1, total_enriched=2) is True
    assert wp.claim_onchain_coverage(group_b, remaining, groups_seen=2, total_enriched=2) is True
    assert remaining[pk] == 0  # both slots consumed


def test_uncovered_group_on_same_pool_falls_back_to_zerion():
    """Only one of two same-pool positions is enumerable on-chain: the first
    Zerion group is covered, the second correctly gets a tier-3 fallback."""
    pk = wp.lp_pair_key("WETH", "USDC")
    remaining = {pk: 1}

    assert wp.claim_onchain_coverage(pk, remaining, groups_seen=1, total_enriched=1) is True
    assert wp.claim_onchain_coverage(pk, remaining, groups_seen=2, total_enriched=1) is False


def test_positions_on_different_pools_do_not_consume_each_others_coverage():
    """Old count-based behaviour let one enriched WETH/USDC row suppress the
    fallback for an unrelated DAI/USDC group. Coverage is per-pair now."""
    weth_usdc = wp.lp_pair_key("WETH", "USDC")
    dai_usdc = wp.lp_pair_key("DAI", "USDC")
    remaining = {weth_usdc: 1}

    assert wp.claim_onchain_coverage(weth_usdc, remaining, groups_seen=1, total_enriched=1) is True
    # DAI/USDC has no enriched row; groups_seen(2) > total_enriched(1) -> fallback.
    assert wp.claim_onchain_coverage(dai_usdc, remaining, groups_seen=2, total_enriched=1) is False


def test_no_onchain_rows_means_every_group_falls_back():
    """No RPC configured: nothing enriched, so every Zerion group must appear."""
    remaining = {}
    assert wp.claim_onchain_coverage(wp.lp_pair_key("WETH", "USDC"), remaining, 1, 0) is False
    assert wp.claim_onchain_coverage(wp.lp_pair_key("DAI", "USDC"), remaining, 2, 0) is False


def test_unmatched_pair_key_does_not_duplicate_when_counts_already_balance():
    """Safety net: if a group's symbols don't match any enriched row but the
    on-chain rows already account for every group, emitting a fallback would
    duplicate a position. Degrade to the old count-based invariant instead."""
    remaining = {wp.lp_pair_key("WETH", "USDC"): 0}
    unmatched = wp.lp_pair_key("SOMETHING", "ODD")
    assert wp.claim_onchain_coverage(unmatched, remaining, groups_seen=1, total_enriched=1) is True


def test_failed_enrichment_frees_its_group_to_fall_back():
    """One of two enumerated NFTs fails to enrich. total_enriched counts only
    successes, so the uncovered group still surfaces via Zerion rather than
    being suppressed by a count that included the failure."""
    pk = wp.lp_pair_key("WETH", "USDC")
    remaining = {pk: 1}  # 2 NFTs enumerated, only 1 enriched

    assert wp.claim_onchain_coverage(pk, remaining, groups_seen=1, total_enriched=1) is True
    assert wp.claim_onchain_coverage(pk, remaining, groups_seen=2, total_enriched=1) is False


# ─── V4 discovery chain gating (step 3: Base via Etherscan V2 only) ───────────

def test_base_is_reachable_via_etherscan_v2_but_not_rpc_log_scan():
    from src.connectors.uniswap_v4 import ETHERSCAN_V2_CHAIN_IDS, RPC_LOG_SCAN_CHAIN_IDS
    assert 8453 in ETHERSCAN_V2_CHAIN_IDS   # unified API covers Base with one key
    assert 8453 not in RPC_LOG_SCAN_CHAIN_IDS  # bounded scan is not viable there


def test_rpc_log_scan_chains_are_a_subset_of_etherscan_chains():
    from src.connectors.uniswap_v4 import ETHERSCAN_V2_CHAIN_IDS, RPC_LOG_SCAN_CHAIN_IDS
    assert RPC_LOG_SCAN_CHAIN_IDS <= ETHERSCAN_V2_CHAIN_IDS


def test_v4_discovery_returns_empty_without_etherscan_key_on_base(monkeypatch):
    """No key on Base: report nothing found rather than scanning a window too
    short to be meaningful."""
    from src.connectors import uniswap_v4 as v4

    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)

    class _FakeEth:
        chain_id = 8453

    class _Conn:
        pass

    c = _Conn()
    c.w3 = type("W3", (), {"eth": _FakeEth()})()
    c._discover_via_rpc = lambda w: (_ for _ in ()).throw(
        AssertionError("RPC log scan must not run on Base")
    )

    ids = v4.UniswapV4Connector._discover_candidate_token_ids(c, "0x" + "1" * 40)
    assert ids == []


def test_v4_discovery_uses_etherscan_on_base_when_key_present(monkeypatch):
    from src.connectors import uniswap_v4 as v4

    monkeypatch.setenv("ETHERSCAN_API_KEY", "testkey")
    called = {}

    class _FakeEth:
        chain_id = 8453

    class _Conn:
        pass

    c = _Conn()
    c.w3 = type("W3", (), {"eth": _FakeEth()})()

    def _fake_etherscan(chain_id, api_key, wallet):
        called["chain_id"] = chain_id
        return [111, 222]

    c._discover_via_etherscan = _fake_etherscan
    c._discover_via_rpc = lambda w: (_ for _ in ()).throw(
        AssertionError("RPC log scan must not run on Base")
    )

    ids = v4.UniswapV4Connector._discover_candidate_token_ids(c, "0x" + "1" * 40)
    assert ids == [111, 222]
    assert called["chain_id"] == 8453
