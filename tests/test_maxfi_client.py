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
