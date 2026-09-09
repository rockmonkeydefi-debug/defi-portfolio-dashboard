"""Regression tests for maxfi_client.py's tiered word-count validation
(Phase A.1). Offline, synthetic fixtures only — no network calls.

Bug: lens.isPositionOutOfRange(uint256) on Robinhood Chain returns 2 words,
not the 1 originally captured (truncated ABI capture in the source findings
doc). Exact word-count enforcement on MaxFi's own contracts (lens, vault)
was too strict; Uniswap's standardized contracts keep exact enforcement.
"""

import pytest

import maxfi_client as mc


# ── _split_words: the two-tier helper itself ────────────────────────────

def test_split_words_at_least_with_extra_word():
    # Mirrors the real Robinhood Chain isPositionOutOfRange() behavior:
    # 1 word expected, 2 actually returned.
    raw = "0x" + mc.encode_uint256(1) + mc.encode_uint256(999)
    known, extra = mc._split_words(raw, 1, "at_least", "test")
    assert known == [mc.encode_uint256(1)]
    assert extra == [mc.encode_uint256(999)]


def test_split_words_at_least_floor_still_enforced():
    with pytest.raises(mc.MaxFiDecodeError):
        mc._split_words("0x", 1, "at_least", "test")


def test_split_words_exact_rejects_extra_words():
    # 8-word payload where exactly 7 (slot0-shaped) is required.
    raw = "0x" + "".join(mc.encode_uint256(i) for i in range(8))
    with pytest.raises(mc.MaxFiDecodeError):
        mc._split_words(raw, 7, "exact", "pool slot0()")


def test_split_words_exact_match_has_no_extra():
    raw = "0x" + "".join(mc.encode_uint256(i) for i in range(7))
    known, extra = mc._split_words(raw, 7, "exact", "pool slot0()")
    assert len(known) == 7
    assert extra == []


# ── isPositionOutOfRange: end-to-end through the real call site ─────────

def test_is_position_out_of_range_decodes_two_word_payload(monkeypatch):
    # word0 = bool (true), word1 = the mystery second word Robinhood Chain
    # actually returns. Its meaning is unconfirmed — this test only checks
    # it survives the round trip as an extra word, not what it means.
    mystery_word = mc.encode_uint256(0xDEADBEEF)
    raw = "0x" + mc.encode_uint256(1) + mystery_word
    monkeypatch.setattr(mc, "rpc_call", lambda chain, to, cd, timeout=None: raw)

    decoded, extra = mc.is_position_out_of_range("robinhood", 757217)

    assert decoded is True
    assert extra == [mystery_word]


def test_is_position_out_of_range_rejects_empty_result(monkeypatch):
    # Floor (at least 1 word) must still raise — this isn't a removed check.
    monkeypatch.setattr(
        mc, "rpc_call",
        lambda chain, to, cd, timeout=None: (_ for _ in ()).throw(
            mc.MaxFiRpcError("empty result")
        ),
    )
    with pytest.raises(mc.MaxFiRpcError):
        mc.is_position_out_of_range("robinhood", 757217)


# ── vault.positions(): "at_least" tier, sanity assertions untouched ─────

_OWNER = "0x1234567890123456789012345678901234567890"


def _vault_position_words():
    return [
        mc.encode_uint256(5884225),           # tokenId
        "ab" * 32,                            # poolId
        mc.encode_address(_OWNER),            # owner
        mc.encode_uint256(1130),              # rangeWidthBps
        mc.encode_int24(-199240),             # currentTickLower
        mc.encode_int24(-198110),             # currentTickUpper
        mc.encode_uint256(1),                 # autoSnuggleEnabled
        mc.encode_uint256(0),                 # autoCompoundEnabled
        mc.encode_uint256(3600),              # rebalanceDelay
        mc.encode_uint256(0),                 # outOfRangeSince
        mc.encode_uint256(4),                 # totalRebalances
        mc.encode_uint256(1700000000),        # lastRebalanceTime
        mc.encode_uint256(1690000000),        # depositTimestamp
        mc.encode_uint256(123456),            # cumulativeFees0
        mc.encode_uint256(654321),            # cumulativeFees1
        mc.encode_uint256(999),               # cumulativeRewards
    ]


def test_decode_vault_position_extra_words_surfaced_not_dropped():
    words = _vault_position_words() + [mc.encode_uint256(777)]
    raw = "0x" + "".join(words)
    decoded, known, extra = mc.decode_vault_position(raw, expected_owner=_OWNER, now_ts=1700000000)
    assert len(known) == 16
    assert extra == [mc.encode_uint256(777)]
    assert decoded["currentTickLower"] == -199240


def test_decode_vault_position_no_extra_words_is_empty_list():
    raw = "0x" + "".join(_vault_position_words())
    decoded, known, extra = mc.decode_vault_position(raw, expected_owner=_OWNER, now_ts=1700000000)
    assert extra == []


def test_decode_vault_position_still_rejects_too_few_words():
    raw = "0x" + "".join(_vault_position_words()[:15])
    with pytest.raises(mc.MaxFiDecodeError):
        mc.decode_vault_position(raw, expected_owner=_OWNER, now_ts=1700000000)


def test_decode_vault_position_sanity_assertions_untouched():
    # Owner mismatch must still raise, unaffected by the tiering change.
    raw = "0x" + "".join(_vault_position_words())
    with pytest.raises(mc.MaxFiDecodeError):
        mc.decode_vault_position(
            raw, expected_owner="0x0000000000000000000000000000000000000001", now_ts=1700000000
        )


# ── Uniswap decoders: exact tier is unaffected by this patch ────────────

def test_decode_slot0_still_exact():
    words = [
        mc.encode_uint256(123456789),
        mc.encode_int24(-199240),
        mc.encode_uint256(5),
        mc.encode_uint256(100),
        mc.encode_uint256(100),
        mc.encode_uint256(0),
        mc.encode_uint256(1),
    ]
    raw = "0x" + "".join(words)
    decoded, known = mc.decode_slot0(raw)
    assert decoded["tick"] == -199240

    # One extra word should still raise for a Uniswap (exact-tier) decoder.
    raw_extra = raw + mc.encode_uint256(1)
    with pytest.raises(mc.MaxFiDecodeError):
        mc.decode_slot0(raw_extra)


# ── get_vault: per-chain module-level cache ──────────────────────────────

_VAULT_ADDR_A = "0x1111111111111111111111111111111111111111"
_VAULT_ADDR_B = "0x2222222222222222222222222222222222222222"


@pytest.fixture(autouse=True)
def _clear_vault_cache():
    mc._VAULT_CACHE.clear()
    yield
    mc._VAULT_CACHE.clear()


def test_get_vault_miss_then_hit(monkeypatch):
    calls = []

    def _fake_rpc_call(chain, to, cd, timeout=None):
        calls.append(chain)
        return "0x" + mc.encode_address(_VAULT_ADDR_A)

    monkeypatch.setattr(mc, "rpc_call", _fake_rpc_call)

    first = mc.get_vault("base")
    second = mc.get_vault("base")

    assert len(calls) == 1
    assert first == second


def test_get_vault_per_chain_isolation(monkeypatch):
    calls = []
    addr_by_chain = {"base": _VAULT_ADDR_A, "robinhood": _VAULT_ADDR_B}

    def _fake_rpc_call(chain, to, cd, timeout=None):
        calls.append(chain)
        return "0x" + mc.encode_address(addr_by_chain[chain])

    monkeypatch.setattr(mc, "rpc_call", _fake_rpc_call)

    base_addr, _ = mc.get_vault("base")
    robinhood_addr, _ = mc.get_vault("robinhood")

    assert len(calls) == 2
    assert base_addr != robinhood_addr
    assert base_addr == _VAULT_ADDR_A
    assert robinhood_addr == _VAULT_ADDR_B

    mc.get_vault("base")
    mc.get_vault("robinhood")
    assert len(calls) == 2


def test_get_vault_failure_is_not_memoised(monkeypatch):
    calls = []

    def _fake_rpc_call(chain, to, cd, timeout=None):
        calls.append(chain)
        if len(calls) == 1:
            raise mc.MaxFiRpcError("simulated RPC failure")
        return "0x" + mc.encode_address(_VAULT_ADDR_A)

    monkeypatch.setattr(mc, "rpc_call", _fake_rpc_call)

    with pytest.raises(mc.MaxFiRpcError):
        mc.get_vault("base")
    assert "base" not in mc._VAULT_CACHE

    address, _extra = mc.get_vault("base")
    assert len(calls) == 2
    assert address == _VAULT_ADDR_A


def test_get_vault_use_cache_false_bypasses_read(monkeypatch):
    calls = []

    def _fake_rpc_call(chain, to, cd, timeout=None):
        calls.append(chain)
        return "0x" + mc.encode_address(_VAULT_ADDR_A)

    monkeypatch.setattr(mc, "rpc_call", _fake_rpc_call)

    mc.get_vault("base")
    mc.get_vault("base", use_cache=False)

    assert len(calls) == 2


# ── LP Advisor Phase A1.6: get_npm_balance_of / enumerate_owner_token_ids ──

_OWNER_A1_6 = "0x1234567890123456789012345678901234567890"


def test_get_npm_balance_of_decodes_and_sends_selector_and_address(monkeypatch):
    sent = {}

    def _fake_rpc_call(chain, to, cd, timeout=None):
        sent["chain"] = chain
        sent["to"] = to
        sent["cd"] = cd
        return "0x" + mc.encode_uint256(7)

    monkeypatch.setattr(mc, "rpc_call", _fake_rpc_call)

    result = mc.get_npm_balance_of("base", _OWNER_A1_6)

    assert result == 7
    assert sent["chain"] == "base"
    assert sent["to"] == mc.CHAINS["base"]["position_manager"]
    assert sent["cd"] == mc.calldata(mc.SEL_ERC721_BALANCE_OF, mc.encode_address(_OWNER_A1_6))


def test_enumerate_owner_token_ids_returns_ids_in_slot_order(monkeypatch):
    ids = [111, 222, 333]

    def _fake_multicall3_soft(chain, calls, chunk_size=None):
        assert len(calls) == 3
        return [(True, "0x" + mc.encode_uint256(tid)) for tid in ids]

    monkeypatch.setattr(mc, "multicall3_soft", _fake_multicall3_soft)

    token_ids, failed = mc.enumerate_owner_token_ids("base", _OWNER_A1_6, 3)

    assert token_ids == ids
    assert failed == 0


def test_enumerate_owner_token_ids_counts_failed_slot_without_raising(monkeypatch):
    def _fake_multicall3_soft(chain, calls, chunk_size=None):
        return [
            (True, "0x" + mc.encode_uint256(111)),
            (False, None),
            (True, "0x" + mc.encode_uint256(333)),
        ]

    monkeypatch.setattr(mc, "multicall3_soft", _fake_multicall3_soft)

    token_ids, failed = mc.enumerate_owner_token_ids("base", _OWNER_A1_6, 3)

    assert token_ids == [111, 333]
    assert failed == 1


def test_enumerate_owner_token_ids_zero_count_returns_empty_no_rpc_call(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must not call multicall3_soft for count=0")

    monkeypatch.setattr(mc, "multicall3_soft", _boom)

    token_ids, failed = mc.enumerate_owner_token_ids("base", _OWNER_A1_6, 0)

    assert token_ids == []
    assert failed == 0


# ── LP Advisor B1.1: decode_positions_and_pools_soft ────────────────────
#
# Fail-soft sibling of decode_positions_and_pools (still strict, still the
# catalogue probe's precedent - untouched here). Stubs multicall3_soft for
# both the positions() and getPool() batches; decode_npm_position and
# _split_words run for real against synthetic-but-valid raw payloads.

_FACTORY = "0xfabfabfabfabfabfabfabfabfabfabfabfabfab0"


def _npm_position_raw(token0, token1, fee=3000, tick_lower=-100, tick_upper=100):
    words = [
        mc.encode_uint256(0),                     # nonce
        mc.encode_address("0x" + "0" * 40),       # operator
        mc.encode_address(token0),
        mc.encode_address(token1),
        mc.encode_uint256(fee),
        mc.encode_int24(tick_lower),
        mc.encode_int24(tick_upper),
        mc.encode_uint256(0),                     # liquidity
        mc.encode_uint256(0),                     # feeGrowthInside0LastX128
        mc.encode_uint256(0),                     # feeGrowthInside1LastX128
        mc.encode_uint256(0),                     # tokensOwed0
        mc.encode_uint256(0),                     # tokensOwed1
    ]
    return "0x" + "".join(words)


def _pool_raw(pool_address):
    return "0x" + mc.encode_address(pool_address)


def test_decode_soft_all_succeed_matches_strict_shape(monkeypatch):
    monkeypatch.setattr(mc, "get_factory", lambda chain: _FACTORY)

    tok0a, tok1a = "0x" + "a" * 40, "0x" + "b" * 40
    tok0b, tok1b = "0x" + "c" * 40, "0x" + "d" * 40
    pool_a, pool_b = "0x" + "1" * 40, "0x" + "2" * 40

    def _fake_multicall3_soft(chain, calls, chunk_size=None):
        if len(calls) == 2 and calls[0][0] == mc.CHAINS["base"]["position_manager"]:
            return [
                (True, _npm_position_raw(tok0a, tok1a)),
                (True, _npm_position_raw(tok0b, tok1b, fee=500)),
            ]
        return [(True, _pool_raw(pool_a)), (True, _pool_raw(pool_b))]

    monkeypatch.setattr(mc, "multicall3_soft", _fake_multicall3_soft)

    decoded, failed = mc.decode_positions_and_pools_soft("base", [1, 2])

    assert failed == 0
    assert decoded == [
        {"token_id": "1", "pool_address": pool_a, "token0_address": tok0a,
         "token1_address": tok1a, "fee_tier": 3000},
        {"token_id": "2", "pool_address": pool_b, "token0_address": tok0b,
         "token1_address": tok1b, "fee_tier": 500},
    ]


def test_decode_soft_mid_batch_failure_preserves_alignment(monkeypatch):
    monkeypatch.setattr(mc, "get_factory", lambda chain: _FACTORY)

    tok0a, tok1a = "0x" + "a" * 40, "0x" + "b" * 40
    tok0c, tok1c = "0x" + "e" * 40, "0x" + "f" * 40
    pool_a, pool_c = "0x" + "1" * 40, "0x" + "3" * 40

    def _fake_multicall3_soft(chain, calls, chunk_size=None):
        if len(calls) == 3:
            # token_id 2's positions() sub-call reverted mid-batch.
            return [
                (True, _npm_position_raw(tok0a, tok1a)),
                (False, None),
                (True, _npm_position_raw(tok0c, tok1c)),
            ]
        # Only 2 survivors reach the pool batch - re-associated positionally,
        # never zipped against the original 3-element token_ids list.
        assert len(calls) == 2
        return [(True, _pool_raw(pool_a)), (True, _pool_raw(pool_c))]

    monkeypatch.setattr(mc, "multicall3_soft", _fake_multicall3_soft)

    decoded, failed = mc.decode_positions_and_pools_soft("base", [1, 2, 3])

    assert failed == 1
    assert decoded == [
        {"token_id": "1", "pool_address": pool_a, "token0_address": tok0a,
         "token1_address": tok1a, "fee_tier": 3000},
        {"token_id": "3", "pool_address": pool_c, "token0_address": tok0c,
         "token1_address": tok1c, "fee_tier": 3000},
    ]


def test_decode_soft_npm_decode_failure_dropped_run_continues(monkeypatch):
    monkeypatch.setattr(mc, "get_factory", lambda chain: _FACTORY)

    tok0b, tok1b = "0x" + "c" * 40, "0x" + "d" * 40
    pool_b = "0x" + "2" * 40

    def _fake_multicall3_soft(chain, calls, chunk_size=None):
        if len(calls) == 2:
            return [
                # tickLower (100) not < tickUpper (-100) - decode_npm_position
                # raises MaxFiDecodeError on this payload.
                (True, _npm_position_raw(tok0b, tok1b, tick_lower=100, tick_upper=-100)),
                (True, _npm_position_raw(tok0b, tok1b)),
            ]
        assert len(calls) == 1
        return [(True, _pool_raw(pool_b))]

    monkeypatch.setattr(mc, "multicall3_soft", _fake_multicall3_soft)

    decoded, failed = mc.decode_positions_and_pools_soft("base", [1, 2])

    assert failed == 1
    assert decoded == [
        {"token_id": "2", "pool_address": pool_b, "token0_address": tok0b,
         "token1_address": tok1b, "fee_tier": 3000},
    ]


def test_decode_soft_get_pool_failure_dropped_at_pool_stage(monkeypatch):
    monkeypatch.setattr(mc, "get_factory", lambda chain: _FACTORY)

    tok0a, tok1a = "0x" + "a" * 40, "0x" + "b" * 40
    tok0b, tok1b = "0x" + "c" * 40, "0x" + "d" * 40
    pool_b = "0x" + "2" * 40

    def _fake_multicall3_soft(chain, calls, chunk_size=None):
        if len(calls) == 2 and calls[0][0] == mc.CHAINS["base"]["position_manager"]:
            return [
                (True, _npm_position_raw(tok0a, tok1a)),
                (True, _npm_position_raw(tok0b, tok1b)),
            ]
        # Both positions() calls survived, so both reach the pool batch;
        # token_id 1's getPool() sub-call reverts here.
        assert len(calls) == 2
        return [(False, None), (True, _pool_raw(pool_b))]

    monkeypatch.setattr(mc, "multicall3_soft", _fake_multicall3_soft)

    decoded, failed = mc.decode_positions_and_pools_soft("base", [1, 2])

    assert failed == 1
    assert decoded == [
        {"token_id": "2", "pool_address": pool_b, "token0_address": tok0b,
         "token1_address": tok1b, "fee_tier": 3000},
    ]


def test_decode_soft_empty_token_ids_returns_empty_no_rpc_call(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must not call multicall3_soft for empty token_ids")

    monkeypatch.setattr(mc, "multicall3_soft", _boom)
    monkeypatch.setattr(mc, "get_factory", _boom)

    decoded, failed = mc.decode_positions_and_pools_soft("base", [])

    assert decoded == []
    assert failed == 0
