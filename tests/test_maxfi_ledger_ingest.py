"""Tests for maxfi_ledger_ingest.py (HANDOFF_maxfi_ledger.md Commit 3b.1) -
the RPC/network layer for the MaxFi vault-event ledger backfill. No
network calls: every test monkeypatches this module's own eth_get_logs/
eth_call/eth_block_number functions directly, never `requests` (same
boundary tests/test_maxfi_client.py uses against maxfi_client.rpc_call).
"""

import pytest

import maxfi_ledger as ml
import maxfi_ledger_ingest as mli


@pytest.fixture(autouse=True)
def _clear_npm_cache():
    mli._NPM_RESOLUTION_CACHE.clear()
    yield
    mli._NPM_RESOLUTION_CACHE.clear()


# ── raw log builders (Etherscan shape - matches maxfi_ledger._normalize_log's
# "blockNumber" branch) - not fixtures, constructed inline per this file's
# own need, same convention as tests/test_maxfi_ledger_derive.py's mk_event ──

def _word(value):
    return format(value, "064x")


def _make_log(address, topics, data_words, block_number=100, tx_hash=None, log_index=0):
    if tx_hash is None:
        tx_hash = "0x" + format(block_number, "x").rjust(64, "0")
    return {
        "address": address,
        "blockNumber": hex(block_number),
        "timeStamp": hex(1700000000 + block_number),
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
        "topics": topics,
        "data": "0x" + "".join(_word(w) for w in data_words),
    }


def _position_created_log(token_id, owner, pool_id, address, block_number=100, log_index=0):
    topics = [
        ml.TOPIC_POSITION_CREATED,
        mli.encode_topic_uint256(token_id),
        mli.encode_topic_address(owner),
        pool_id,
    ]
    # tick_lower, tick_upper, liquidity, auto_snuggle_enabled - dummy
    # non-negative values, decode correctness is covered exhaustively
    # elsewhere (tests/test_maxfi_ledger_decode.py); this file only needs
    # a log that decodes successfully to PositionCreated.
    return _make_log(address, topics, [100, 200, 5000, 0], block_number, log_index=log_index)


def _pool_added_log(pool_id, pool, token0, token1, fee, position_adapter, reward_adapter,
                     address, block_number=90, log_index=0):
    topics = [ml.TOPIC_POOL_ADDED, pool_id]
    words = [
        int(pool[2:], 16), int(token0[2:], 16), int(token1[2:], 16),
        fee, int(position_adapter[2:], 16), int(reward_adapter[2:], 16),
    ]
    return _make_log(address, topics, words, block_number, log_index=log_index)


def _increase_liquidity_log(token_id, address, block_number=110, log_index=0):
    topics = [ml.TOPIC_INCREASE_LIQUIDITY, mli.encode_topic_uint256(token_id), None, None]
    return _make_log(address, topics, [3000, 4000, 5000], block_number, log_index=log_index)


def _fees_compounded_log(token_id, owner, address, block_number=120, log_index=0):
    topics = [ml.TOPIC_FEES_COMPOUNDED, mli.encode_topic_uint256(token_id)]
    owner_word = int(owner[2:], 16)
    return _make_log(address, topics, [owner_word, 100, 200], block_number, log_index=log_index)


def _fees_harvested_direct_log(token_id, owner, address, block_number=121, log_index=0):
    topics = [ml.TOPIC_FEES_HARVESTED_DIRECT, mli.encode_topic_uint256(token_id)]
    owner_word = int(owner[2:], 16)
    return _make_log(address, topics, [owner_word, 300, 400], block_number, log_index=log_index)


# ── owner/token_id topic encoding ────────────────────────────────────────

def test_encode_topic_address_is_32_byte_left_padded():
    topic = mli.encode_topic_address("0xaB7A515c6e2Eea5140eD8A5b09A7D782F3B26743")
    assert topic == "0x000000000000000000000000ab7a515c6e2eea5140ed8a5b09a7d782f3b26743"
    assert len(topic) == 66


def test_encode_topic_uint256_is_32_byte_left_padded():
    # Matches the real value that appears verbatim in
    # tests/fixtures/maxfi_ledger/base_mint_6039568.json's own topics[1]
    # for tokenId 6039568 (Commit 3a) - an independent cross-check.
    topic = mli.encode_topic_uint256(6039568)
    assert topic == "0x00000000000000000000000000000000000000000000000000000000005c2810"
    assert len(topic) == 66


# ── scan_logs_chunked: adaptive backoff ──────────────────────────────────

def test_scan_logs_chunked_halves_on_oversize_range_and_covers_full_span(monkeypatch):
    # Threshold (600) sits ABOVE mli.MIN_CHUNK_SIZE (500) so halving can
    # actually reach a range small enough to succeed, rather than hitting
    # the floor and giving up - see the dedicated "gives up" test below
    # for that other case.
    def fake_eth_get_logs(chain, address, topics, from_block, to_block, timeout=30):
        if to_block - from_block + 1 > 600:
            raise mli.MaxFiRpcOversizeRange("range too large")
        return [{"blockNumber": hex(b)} for b in range(from_block, to_block + 1)]

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)

    logs, stats = mli.scan_logs_chunked("base", "0xvault", [], 0, 1999, chunk_size=2000)

    assert len(logs) == 2000  # every block in [0, 1999] covered, nothing silently dropped
    assert stats["chunk_halvings"] >= 1
    assert stats["final_chunk_size"] <= 600
    assert stats["final_chunk_size"] >= mli.MIN_CHUNK_SIZE


def test_scan_logs_chunked_429_retries_same_range_without_shrinking(monkeypatch):
    attempts = {"n": 0}
    seen_ranges = []

    def fake_eth_get_logs(chain, address, topics, from_block, to_block, timeout=30):
        seen_ranges.append((from_block, to_block))
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise mli.MaxFiRpcTooManyRequests("HTTP 429")
        return [{"blockNumber": hex(from_block)}]

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)
    monkeypatch.setattr(mli.time, "sleep", lambda s: None)

    logs, stats = mli.scan_logs_chunked("base", "0xvault", [], 0, 99, chunk_size=100)

    assert stats["retries_429"] == 2
    assert stats["chunk_halvings"] == 0
    # Every retry (including the eventual success) hit the exact same
    # range - a 429 must never shrink the chunk.
    assert seen_ranges == [(0, 99), (0, 99), (0, 99)]
    assert len(logs) == 1


def test_scan_logs_chunked_gives_up_rather_than_silently_dropping_a_range(monkeypatch):
    """Unlike the uniswap_v4._discover_via_rpc pattern this is adapted
    from (which logs a warning and moves on once chunk_size bottoms out),
    an oversize-range error at the floor chunk size must raise - never
    silently drop a block range in a financial ledger backfill."""
    def fake_eth_get_logs(chain, address, topics, from_block, to_block, timeout=30):
        raise mli.MaxFiRpcOversizeRange("still too large")

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)

    with pytest.raises(mli.MaxFiRpcOversizeRange):
        mli.scan_logs_chunked("base", "0xvault", [], 0, 999, chunk_size=mli.MIN_CHUNK_SIZE)


def test_scan_logs_chunked_non_recoverable_error_propagates_immediately(monkeypatch):
    def fake_eth_get_logs(chain, address, topics, from_block, to_block, timeout=30):
        raise mli.MaxFiRpcError("some other RPC failure")

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)

    with pytest.raises(mli.MaxFiRpcError):
        mli.scan_logs_chunked("base", "0xvault", [], 0, 999, chunk_size=1000)


# ── NPM resolution + caching ──────────────────────────────────────────────

def test_resolve_npm_address_caches_after_success(monkeypatch):
    npm = "0x" + "77" * 20
    calls = {"n": 0}

    def fake_eth_call(chain, to, data, timeout=30):
        calls["n"] += 1
        return "0x" + _word(int(npm[2:], 16))

    monkeypatch.setattr(mli, "eth_call", fake_eth_call)

    addr1 = mli.resolve_npm_address("base", "0xpool1", "0xadapter1")
    addr2 = mli.resolve_npm_address("base", "0xpool1", "0xadapter1")

    assert addr1 == addr2 == npm.lower()
    assert calls["n"] == 1  # second call served entirely from cache
    assert mli._NPM_RESOLUTION_CACHE[("base", "0xpool1")] == npm.lower()


def test_resolve_npm_address_failure_is_not_cached(monkeypatch):
    def fake_eth_call_fail(chain, to, data, timeout=30):
        raise mli.MaxFiRpcError("boom")

    monkeypatch.setattr(mli, "eth_call", fake_eth_call_fail)

    result = mli.resolve_npm_address("base", "0xpool2", "0xadapter2")

    assert result is None
    assert ("base", "0xpool2") not in mli._NPM_RESOLUTION_CACHE


def test_resolve_npm_address_zero_address_is_not_cached(monkeypatch):
    def fake_eth_call_zero(chain, to, data, timeout=30):
        return "0x" + _word(0)

    monkeypatch.setattr(mli, "eth_call", fake_eth_call_zero)

    result = mli.resolve_npm_address("base", "0xpool3", "0xadapter3")

    assert result is None
    assert ("base", "0xpool3") not in mli._NPM_RESOLUTION_CACHE


# ── scan_chain: two-pass token_id handoff + NPM resolution + pass 3 ─────

def test_scan_chain_two_pass_token_id_handoff_and_npm_resolution(monkeypatch):
    chain = "base"
    vault = mli.CHAINS[chain]["vault"]
    staking_manager = mli.CHAINS[chain]["staking_manager"]
    wallet = "0xaB7A515c6e2Eea5140eD8A5b09A7D782F3B26743"
    pool_id = "0x" + "11" * 32
    position_adapter = "0x" + "22" * 20
    npm_address = "0x" + "33" * 20
    token0 = "0x" + "44" * 20
    token1 = "0x" + "55" * 20

    pc_log = _position_created_log(6039568, wallet, pool_id, vault)
    pool_added_log = _pool_added_log(
        pool_id, "0x" + "66" * 20, token0, token1, 500, position_adapter, "0x" + "00" * 20, vault
    )
    il_log = _increase_liquidity_log(6039568, npm_address)

    def fake_eth_get_logs(c, address, topics, from_block, to_block, timeout=30):
        group = set(topics[0])
        if group == {ml.TOPIC_POSITION_CREATED, ml.TOPIC_POSITION_WITHDRAWN, ml.TOPIC_FEES_HARVESTED}:
            assert address == vault
            assert mli.encode_topic_address(wallet) in topics[2]
            return [pc_log]
        if group == {ml.TOPIC_SNUGGLE_REBALANCED}:
            assert address == vault
            assert mli.encode_topic_address(wallet) in topics[3]
            return []
        if group == {ml.TOPIC_POOL_ADDED}:
            assert address == vault
            return [pool_added_log]
        if group == {ml.TOPIC_PROTOCOL_FEES_DISTRIBUTED, ml.TOPIC_FEES_COMPOUNDED, ml.TOPIC_FEES_HARVESTED_DIRECT}:
            assert address == staking_manager
            # Pass 2 must be filtered on the token_id pass 1 discovered.
            assert mli.encode_topic_uint256(6039568) in topics[1]
            return []
        if group == {ml.TOPIC_INCREASE_LIQUIDITY}:
            # Pass 3's TARGET must be the resolved NPM address, and its
            # filter must carry the same token_id pass 1 discovered.
            assert address == npm_address.lower()
            assert mli.encode_topic_uint256(6039568) in topics[1]
            return [il_log]
        raise AssertionError(f"unexpected eth_get_logs call: {address} {topics}")

    def fake_eth_call(chain, to, data, timeout=30):
        assert to == position_adapter
        assert data == mli.SEL_POSITION_MANAGER
        return "0x" + _word(int(npm_address[2:], 16))

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)
    monkeypatch.setattr(mli, "eth_call", fake_eth_call)
    monkeypatch.setattr(mli, "eth_block_number", lambda chain, timeout=30: mli.CHAINS["base"]["start_block"] + 100)

    result = mli.scan_chain(chain, [wallet])

    assert result["token_ids"] == ["6039568"]
    assert result["npm_resolutions"] == [{"pool_id": pool_id, "npm_address": npm_address.lower()}]
    assert result["wallets_scanned"] == [wallet]
    assert il_log in result["raw_logs"]
    assert pc_log in result["raw_logs"]


def test_scan_chain_no_pool_added_event_skips_pass3_and_leaves_npm_unresolved(monkeypatch):
    """Accepted scope limit: a pool whose PoolAdded event isn't in this
    batch never resolves an NPM address, and pass 3 (which needs that
    address as its query target) is skipped entirely - not an error."""
    chain = "base"
    vault = mli.CHAINS[chain]["vault"]
    wallet = "0xaB7A515c6e2Eea5140eD8A5b09A7D782F3B26743"
    pool_id = "0x" + "11" * 32
    pc_log = _position_created_log(100, wallet, pool_id, vault)

    calls = []

    def fake_eth_get_logs(c, address, topics, from_block, to_block, timeout=30):
        calls.append((address, tuple(topics[0])))
        group = set(topics[0])
        if group == {ml.TOPIC_POSITION_CREATED, ml.TOPIC_POSITION_WITHDRAWN, ml.TOPIC_FEES_HARVESTED}:
            return [pc_log]
        if group == {ml.TOPIC_SNUGGLE_REBALANCED}:
            return []
        if group == {ml.TOPIC_POOL_ADDED}:
            return []  # no PoolAdded event in this batch
        if group == {ml.TOPIC_PROTOCOL_FEES_DISTRIBUTED, ml.TOPIC_FEES_COMPOUNDED, ml.TOPIC_FEES_HARVESTED_DIRECT}:
            return []
        raise AssertionError(f"pass 3 (NPM) must never be called when NPM resolution found nothing: {address} {topics}")

    def _boom_eth_call(*a, **k):
        raise AssertionError("NPM resolution must never be attempted with no PoolAdded match")

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)
    monkeypatch.setattr(mli, "eth_call", _boom_eth_call)
    monkeypatch.setattr(mli, "eth_block_number", lambda chain, timeout=30: mli.CHAINS["base"]["start_block"] + 100)

    result = mli.scan_chain(chain, [wallet])

    assert result["token_ids"] == ["100"]
    assert result["npm_resolutions"] == []


def test_scan_chain_no_wallets_returns_empty_without_any_rpc_call(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must not make any RPC call with an empty wallet set")

    monkeypatch.setattr(mli, "eth_get_logs", _boom)
    monkeypatch.setattr(mli, "eth_call", _boom)
    monkeypatch.setattr(mli, "eth_block_number", _boom)

    result = mli.scan_chain("base", [])

    assert result == {
        "raw_logs": [], "wallets_scanned": [], "token_ids": [],
        "npm_resolutions": [], "event_type_counts": {},
        "chunk_stats": {
            "pass1_vault": {"calls": 0, "chunk_halvings": 0, "retries_429": 0, "final_chunk_size": None},
            "pass1_snuggle_rebalanced": {"calls": 0, "chunk_halvings": 0, "retries_429": 0, "final_chunk_size": None},
            "pool_added": {"calls": 0, "chunk_halvings": 0, "retries_429": 0, "final_chunk_size": None},
            "pass2_staking_manager": {"calls": 0, "chunk_halvings": 0, "retries_429": 0, "final_chunk_size": None},
            "pass3_npm": {},
        },
    }


# ── unverified_event_types counting (event_type_counts is what the      ──
# ── backfill route derives its unverified_event_types report from)      ──

def test_scan_chain_counts_fees_compounded_and_fees_harvested_direct(monkeypatch):
    chain = "base"
    vault = mli.CHAINS[chain]["vault"]
    staking_manager = mli.CHAINS[chain]["staking_manager"]
    wallet = "0xaB7A515c6e2Eea5140eD8A5b09A7D782F3B26743"
    pool_id = "0x" + "11" * 32

    pc_log = _position_created_log(100, wallet, pool_id, vault)
    fc_log = _fees_compounded_log(100, wallet, staking_manager)
    fhd_log = _fees_harvested_direct_log(100, wallet, staking_manager)

    def fake_eth_get_logs(c, address, topics, from_block, to_block, timeout=30):
        group = set(topics[0])
        if group == {ml.TOPIC_POSITION_CREATED, ml.TOPIC_POSITION_WITHDRAWN, ml.TOPIC_FEES_HARVESTED}:
            return [pc_log]
        if group == {ml.TOPIC_SNUGGLE_REBALANCED}:
            return []
        if group == {ml.TOPIC_POOL_ADDED}:
            return []
        if group == {ml.TOPIC_PROTOCOL_FEES_DISTRIBUTED, ml.TOPIC_FEES_COMPOUNDED, ml.TOPIC_FEES_HARVESTED_DIRECT}:
            return [fc_log, fhd_log]
        raise AssertionError(f"unexpected call: {address} {topics}")

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)
    monkeypatch.setattr(mli, "eth_block_number", lambda chain, timeout=30: mli.CHAINS["base"]["start_block"] + 100)

    result = mli.scan_chain(chain, [wallet])

    assert result["event_type_counts"].get("FeesCompounded") == 1
    assert result["event_type_counts"].get("FeesHarvestedDirect") == 1
    assert result["event_type_counts"].get("PositionCreated") == 1


# ── RPC URL / unknown chain errors ───────────────────────────────────────

def test_missing_rpc_url_raises_same_shape_as_maxfi_client(monkeypatch):
    monkeypatch.delenv("RH_RPC_URL", raising=False)
    with pytest.raises(mli.MaxFiRpcError, match=r"no RPC URL configured"):
        mli.eth_block_number("robinhood")


def test_unknown_chain_raises():
    with pytest.raises(mli.MaxFiRpcError, match="unknown chain"):
        mli.scan_logs_chunked("not-a-real-chain", "0xaddr", [], 0, 1)
