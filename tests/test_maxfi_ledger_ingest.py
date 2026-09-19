"""Tests for maxfi_ledger_ingest.py (HANDOFF_maxfi_ledger.md Commit 3b.1) -
the RPC/network layer for the MaxFi vault-event ledger backfill. No
network calls: every test monkeypatches this module's own eth_get_logs/
eth_call/eth_block_number functions directly, never `requests` (same
boundary tests/test_maxfi_client.py uses against maxfi_client.rpc_call).
"""

import json
import os

import pytest

import maxfi_ledger as ml
import maxfi_ledger_ingest as mli

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "maxfi_ledger")


def load_fixture(name):
    with open(os.path.join(FIXTURES, name)) as fh:
        return json.load(fh)


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


# ── Hotfix 3b.1.1: eth_get_logs() classifies by BODY, not HTTP status ────
# alone - first production Base dry_run failed because Alchemy delivers
# an oversize-range rejection as HTTP 400 WITH a JSON-RPC error body, not
# a 200. These stub `requests.post` directly (the file's other tests stub
# eth_get_logs itself) since they exercise eth_get_logs()'s own body-
# classification logic, not its callers - same convention as
# tests/test_maxfi_history.py / tests/test_maxfi_pooldata.py
# (`monkeypatch.setattr(<module>.requests, "post"/"get", ...)`).

class _FakeResponse:
    def __init__(self, status_code, json_data=None, json_raises=False):
        self.status_code = status_code
        self._json_data = json_data
        self._json_raises = json_raises

    def json(self):
        if self._json_raises:
            raise ValueError("not JSON")
        return self._json_data


_ALCHEMY_OVERSIZE_BODY = {
    "error": {
        "code": -32602,
        "message": (
            "Log response size exceeded. You can make eth_getLogs requests "
            "with up to a 2K block range ..."
        ),
    }
}


def test_eth_get_logs_classifies_alchemy_http_400_oversize_range_body(monkeypatch):
    monkeypatch.setenv("BASE_RPC_URL", "http://fake-rpc.test")
    monkeypatch.setattr(
        mli.requests, "post",
        lambda url, json=None, timeout=None: _FakeResponse(400, _ALCHEMY_OVERSIZE_BODY),
    )

    with pytest.raises(mli.MaxFiRpcOversizeRange):
        mli.eth_get_logs("base", "0xvault", [], 0, 100000)


def test_eth_get_logs_http_400_non_oversize_body_raises_with_status_and_message(monkeypatch):
    monkeypatch.setenv("BASE_RPC_URL", "http://fake-rpc.test")
    body = {"error": {"message": "invalid params"}}
    monkeypatch.setattr(mli.requests, "post", lambda url, json=None, timeout=None: _FakeResponse(400, body))

    with pytest.raises(mli.MaxFiRpcError) as exc_info:
        mli.eth_get_logs("base", "0xvault", [], 0, 100)

    msg = str(exc_info.value)
    assert "HTTP 400" in msg
    assert "invalid params" in msg


def test_eth_get_logs_http_400_non_json_body_falls_through_to_generic_error(monkeypatch):
    monkeypatch.setenv("BASE_RPC_URL", "http://fake-rpc.test")
    monkeypatch.setattr(
        mli.requests, "post",
        lambda url, json=None, timeout=None: _FakeResponse(400, json_raises=True),
    )

    with pytest.raises(mli.MaxFiRpcError) as exc_info:
        mli.eth_get_logs("base", "0xvault", [], 0, 100)

    assert "HTTP 400" in str(exc_info.value)


def test_eth_get_logs_429_still_raises_too_many_requests(monkeypatch):
    # Regression pin: 429 handling must be unaffected by the body-parsing
    # change above - still classified by HTTP status alone, before any
    # body is parsed.
    monkeypatch.setenv("BASE_RPC_URL", "http://fake-rpc.test")
    monkeypatch.setattr(mli.requests, "post", lambda url, json=None, timeout=None: _FakeResponse(429))

    with pytest.raises(mli.MaxFiRpcTooManyRequests):
        mli.eth_get_logs("base", "0xvault", [], 0, 100)


def test_scan_logs_chunked_halves_on_real_alchemy_http_400_oversize_body(monkeypatch):
    """End-to-end through the REAL eth_get_logs (not stubbed) - proves
    scan_logs_chunked()'s halving actually fires against the exact
    HTTP-400-with-JSON-RPC-error-body shape that broke the first
    production Base dry_run."""
    monkeypatch.setenv("BASE_RPC_URL", "http://fake-rpc.test")

    def fake_post(url, json=None, timeout=None):
        params = json["params"][0]
        from_block = int(params["fromBlock"], 16)
        to_block = int(params["toBlock"], 16)
        if to_block - from_block + 1 > 2000:
            return _FakeResponse(400, _ALCHEMY_OVERSIZE_BODY)
        return _FakeResponse(200, {"jsonrpc": "2.0", "id": 1, "result": []})

    monkeypatch.setattr(mli.requests, "post", fake_post)

    logs, stats = mli.scan_logs_chunked("base", "0xvault", [], 0, 9999, chunk_size=10000)

    assert logs == []
    assert stats["chunk_halvings"] > 0
    assert stats["final_chunk_size"] <= 2000


# ── Hotfix 3b.1.2: raw-RPC-log shape adaptation ──────────────────────────
# A raw eth_getLogs record is a THIRD log shape maxfi_ledger._normalize_log
# was never meant to handle (it has blockNumber hex, so the Etherscan
# branch is taken, then KeyErrors on log["timeStamp"] - a field standard
# RPC output doesn't carry). Alchemy adds a non-standard blockTimestamp
# field instead; a plain node has neither. The first real, post-hotfix-
# 3b.1.1 production Base dry_run completed every RPC pass cleanly and
# then 500'd with {"error": "'timeStamp'"} once decode_log() actually ran
# against real RPC output for the first time - every 3b.1 ingest test
# used fixture-shaped fakes that were already Etherscan-shape, so this
# gap was never exercised.
#
# base_rpc_getlogs_page.json is real Alchemy eth_getLogs output for the
# Base vault, captured live in chat Sep 19, blocks 0x2a8ae01-0x2a8b1e8.
# The page was truncated mid-way through a seventh entry in that capture;
# only the six complete entries here are real - this is NOT a full page,
# and asserting len() == 7 or more would misrepresent it as one.
#
# NOTE: the task text describing this fixture stated log[5] (the
# FeesHarvested entry) decodes to token_id 66312213. Independently
# recomputed against this fixture's own topics[1]
# ("0x...03f1d815") before writing this test: int("3f1d815", 16) is
# 66181141, not 66312213 (which is hex 0x3f3d815 - a one-digit
# transposition, 1<->3, from the real value). The fixture is used
# byte-for-byte as given; only the STATED expectation was wrong, and is
# corrected here rather than encoded as a bug.

def test_base_rpc_getlogs_page_is_six_complete_entries():
    fixture = load_fixture("base_rpc_getlogs_page.json")
    assert len(fixture) == 6


def test_rpc_fixture_position_created_decodes_via_adapter():
    fixture = load_fixture("base_rpc_getlogs_page.json")
    adapted = mli.rpc_log_to_etherscan_shape(fixture[0])
    record = ml.decode_log(adapted)
    assert record is not None
    assert record["event_type"] == "PositionCreated"
    assert record["block_number"] == 44609025
    assert record["block_timestamp"] == ml._unix_hex_to_iso("0x69dbb8e5")
    decoded = json.loads(record["decoded_json"])
    assert decoded["token_id"] == 4954839
    assert decoded["owner"] == "0xab7a515c6e2eea5140ed8a5b09a7d782f3b26743"


def test_rpc_fixture_fees_harvested_decodes_via_adapter():
    fixture = load_fixture("base_rpc_getlogs_page.json")
    adapted = mli.rpc_log_to_etherscan_shape(fixture[5])
    record = ml.decode_log(adapted)
    assert record is not None
    assert record["event_type"] == "FeesHarvested"
    decoded = json.loads(record["decoded_json"])
    # 66181141 (0x3f1d815), independently recomputed - see this section's
    # own banner comment on the task text's stated (wrong) 66312213.
    assert decoded["token_id"] == 66181141


def test_rpc_fixture_unknown_vault_events_decode_to_none():
    """logs[1..4] share topic0 0x8952a490... - not in this module's
    tracked vocabulary. Pins that an unrecognized vault event is skipped
    (decode_log returns None), not raised - the adapter must not treat
    "unrecognized event" as a decode failure."""
    fixture = load_fixture("base_rpc_getlogs_page.json")
    for raw_log in fixture[1:5]:
        adapted = mli.rpc_log_to_etherscan_shape(raw_log)
        assert ml.decode_log(adapted) is None


def test_rpc_log_to_etherscan_shape_uses_block_timestamp_hex_fallback_when_absent():
    raw_log = dict(load_fixture("base_rpc_getlogs_page.json")[0])
    del raw_log["blockTimestamp"]
    adapted = mli.rpc_log_to_etherscan_shape(raw_log, block_timestamp_hex="0xdeadbeef")
    assert adapted["timeStamp"] == "0xdeadbeef"
    # Everything else copied verbatim, hex strings untouched (never
    # converted to int in the adapter itself).
    assert adapted["blockNumber"] == raw_log["blockNumber"]
    assert adapted["address"] == raw_log["address"]
    assert adapted["topics"] == raw_log["topics"]
    assert adapted["data"] == raw_log["data"]
    assert adapted["transactionHash"] == raw_log["transactionHash"]
    assert adapted["logIndex"] == raw_log["logIndex"]


def test_rpc_log_to_etherscan_shape_raises_without_any_timestamp_source():
    raw_log = dict(load_fixture("base_rpc_getlogs_page.json")[0])
    del raw_log["blockTimestamp"]
    with pytest.raises(ValueError, match=r"blockTimestamp"):
        mli.rpc_log_to_etherscan_shape(raw_log)


def test_unadapted_raw_rpc_log_raises_keyerror_on_decode_log():
    """Regression pin documenting WHY the adapter must live in the
    ingest layer: an unadapted raw RPC log handed straight to
    maxfi_ledger.decode_log() KeyErrors on 'timeStamp' - exactly the
    production 500 this hotfix exists to prevent. maxfi_ledger.py itself
    is untouched; this only proves the failure mode the adapter now
    intercepts before decode_log() is ever called on a raw RPC log."""
    fixture = load_fixture("base_rpc_getlogs_page.json")
    with pytest.raises(KeyError):
        ml.decode_log(fixture[0])


def test_scan_chain_falls_back_to_eth_get_block_timestamp_once_per_shared_block(monkeypatch):
    """Two logs sharing one block, neither carrying blockTimestamp (a
    plain-node shape) - the fallback must be called exactly once for
    that block, not once per log, via scan_chain()'s own per-invocation
    cache."""
    chain = "base"
    vault = mli.CHAINS[chain]["vault"]
    wallet = "0xaB7A515c6e2Eea5140eD8A5b09A7D782F3B26743"
    pool_id = "0x" + "11" * 32

    def _raw_position_created_log(token_id, block_number, log_index):
        topics = [
            ml.TOPIC_POSITION_CREATED,
            mli.encode_topic_uint256(token_id),
            mli.encode_topic_address(wallet),
            pool_id,
        ]
        return {
            "address": vault,
            "blockNumber": hex(block_number),
            "transactionHash": "0x" + format(block_number * 100 + log_index, "x").rjust(64, "0"),
            "logIndex": hex(log_index),
            "topics": topics,
            "data": "0x" + "".join(format(w, "064x") for w in (100, 200, 5000, 0)),
            # No blockTimestamp - a plain-node shape.
        }

    log_a = _raw_position_created_log(100, 44609100, 0)
    log_b = _raw_position_created_log(101, 44609100, 1)  # same block as log_a

    def fake_eth_get_logs(c, address, topics, from_block, to_block, timeout=30):
        group = set(topics[0])
        if group == {ml.TOPIC_POSITION_CREATED, ml.TOPIC_POSITION_WITHDRAWN, ml.TOPIC_FEES_HARVESTED}:
            return [log_a, log_b]
        return []

    lookups = []

    def fake_eth_get_block_timestamp(c, block_number, timeout=30):
        lookups.append(block_number)
        return "0x69dbb8e5"

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)
    monkeypatch.setattr(mli, "eth_get_block_timestamp", fake_eth_get_block_timestamp)
    monkeypatch.setattr(mli, "eth_block_number", lambda chain, timeout=30: 44_609_200)

    result = mli.scan_chain(chain, [wallet])

    assert lookups == [44609100]  # exactly one call, for the one shared block
    assert result["block_timestamp_lookups"] == 1
    assert sorted(result["token_ids"]) == ["100", "101"]
    # Both raw_logs entries must be decode_log()-ready (adapted) - the
    # caller (_run_ledger_backfill) will decode them again itself.
    for adapted_log in result["raw_logs"]:
        assert ml.decode_log(adapted_log) is not None


# ── Hotfix 3b.1.3: per-log decode isolation ──────────────────────────────
# The first real Base dry_run after 3b.1.2 completed every RPC pass and
# then 500'd with a bare IndexError during decode - one undecodable log
# aborted the whole backfill. Precedent: B1.1's own
# decode_positions_and_pools_soft (web_portfolio.py). maxfi_ledger.py's
# decoders are untouched by this hotfix - a failing log is recorded and
# skipped, never patched around.

def test_safe_decode_log_returns_none_and_records_diagnostic_on_index_error():
    vault = mli.CHAINS["base"]["vault"]
    wallet = "0xaB7A515c6e2Eea5140eD8A5b09A7D782F3B26743"
    # Real PositionCreated topic0 but only 3 topics (missing pool_id at
    # topics[3]) - _decode_position_created reads topics[3], IndexError.
    bad_log = _make_log(
        vault,
        [ml.TOPIC_POSITION_CREATED, mli.encode_topic_uint256(100), mli.encode_topic_address(wallet)],
        [100, 200, 5000, 0],
        block_number=44609100,
        log_index=7,
    )
    failures = []

    record = mli.safe_decode_log(bad_log, failures)

    assert record is None
    assert len(failures) == 1
    f = failures[0]
    assert f["error"].startswith("IndexError")
    assert f["topic_count"] == 3
    assert f["tx_hash"] == bad_log["transactionHash"]
    assert f["log_index"] == bad_log["logIndex"]
    assert f["block_number"] == bad_log["blockNumber"]
    assert f["contract_address"] == vault
    assert f["topic0"] == ml.TOPIC_POSITION_CREATED


def test_safe_decode_log_valid_log_returns_record_and_leaves_failures_untouched():
    vault = mli.CHAINS["base"]["vault"]
    wallet = "0xaB7A515c6e2Eea5140eD8A5b09A7D782F3B26743"
    pool_id = "0x" + "11" * 32
    good_log = _make_log(
        vault,
        [ml.TOPIC_POSITION_CREATED, mli.encode_topic_uint256(100), mli.encode_topic_address(wallet), pool_id],
        [100, 200, 5000, 0],
    )
    failures = []

    record = mli.safe_decode_log(good_log, failures)

    assert record is not None
    assert record["event_type"] == "PositionCreated"
    assert failures == []


def test_safe_decode_log_respects_sample_limit():
    vault = mli.CHAINS["base"]["vault"]
    wallet = "0xaB7A515c6e2Eea5140eD8A5b09A7D782F3B26743"

    def bad_log(log_index):
        return _make_log(
            vault,
            [ml.TOPIC_POSITION_CREATED, mli.encode_topic_uint256(100), mli.encode_topic_address(wallet)],
            [100, 200, 5000, 0],
            log_index=log_index,
        )

    failures = []
    for i in range(3):
        result = mli.safe_decode_log(bad_log(i), failures, sample_limit=2)
        assert result is None  # every call still fails, regardless of sample_limit

    # Count is the caller's job (constraint 2's own wording) - this only
    # pins the helper's own append/truncation behavior.
    assert len(failures) == 2


def test_safe_decode_log_malformed_log_missing_topics_never_raises():
    failures = []

    record = mli.safe_decode_log({"address": "0xdead"}, failures)

    assert record is None
    assert len(failures) == 1
    f = failures[0]
    assert f["topic_count"] == 0
    assert f["topic0"] is None
    assert f["data_word_count"] == 0


def test_dedupe_failures_keeps_first_occurrence_per_tx_hash_log_index():
    a1 = {"tx_hash": "0xaaa", "log_index": 1, "error": "first"}
    a2 = {"tx_hash": "0xaaa", "log_index": 1, "error": "second (dup)"}
    b1 = {"tx_hash": "0xbbb", "log_index": 2, "error": "third"}

    deduped = mli._dedupe_failures([a1, a2, b1])

    assert deduped == [a1, b1]


def test_scan_chain_isolates_one_bad_log_and_still_discovers_the_good_token_id(monkeypatch):
    chain = "base"
    vault = mli.CHAINS[chain]["vault"]
    wallet = "0xaB7A515c6e2Eea5140eD8A5b09A7D782F3B26743"
    pool_id = "0x" + "11" * 32

    good_log = _position_created_log(100, wallet, pool_id, vault, block_number=44609100, log_index=0)
    bad_log = _make_log(
        vault,
        [ml.TOPIC_POSITION_CREATED, mli.encode_topic_uint256(101), mli.encode_topic_address(wallet)],
        [100, 200, 5000, 0],
        block_number=44609100,
        log_index=1,
    )

    def fake_eth_get_logs(c, address, topics, from_block, to_block, timeout=30):
        group = set(topics[0])
        if group == {ml.TOPIC_POSITION_CREATED, ml.TOPIC_POSITION_WITHDRAWN, ml.TOPIC_FEES_HARVESTED}:
            return [good_log, bad_log]
        return []

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)
    monkeypatch.setattr(mli, "eth_block_number", lambda chain, timeout=30: 44_700_000)

    result = mli.scan_chain(chain, [wallet])  # must not raise

    assert "100" in result["token_ids"]
    assert result["decode_failed"] == 1
    assert len(result["decode_failures"]) == 1
    assert result["decode_failures"][0]["error"].startswith("IndexError")


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
        "block_timestamp_lookups": 0,
        "decode_failed": 0, "decode_failures": [],
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
