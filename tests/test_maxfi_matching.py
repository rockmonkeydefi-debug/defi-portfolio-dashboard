"""Tests for maxfi_matching.py's position identity matching heuristic.

Offline, synthetic fixtures only - no network calls, no imports of
maxfi_client or web_portfolio (matching the module's own purity contract).
"""

import pytest

from maxfi_matching import (
    classify_positions,
    summarize,
    _assert_all_previous_accounted_for,
)


def pos(idx, token_id, pool="0xPOOL_A", token0="0xTOKEN_A", token1="0xTOKEN_B", fee=3000):
    return {
        "array_index": idx,
        "token_id": token_id,
        "pool_address": pool,
        "token0_address": token0,
        "token1_address": token1,
        "fee_tier": fee,
    }


# ── (a) all matched ──────────────────────────────────────────────────────

def test_all_matched():
    previous = [pos(0, "T0", "0xPOOL_A"), pos(1, "T1", "0xPOOL_B"), pos(2, "T2", "0xPOOL_C")]
    current = [pos(0, "T0", "0xPOOL_A"), pos(1, "T1", "0xPOOL_B"), pos(2, "T2", "0xPOOL_C")]

    result = classify_positions(previous, current)

    assert len(result["matched"]) == 3
    assert result["rebalanced"] == []
    assert result["closed"] == []
    assert result["opened"] == []
    assert result["ambiguous"] == []


# ── (b) single rebalance ─────────────────────────────────────────────────

def test_single_rebalance():
    previous = [pos(0, "T0", "0xPOOL_A"), pos(1, "T1", "0xPOOL_B"), pos(2, "T2", "0xPOOL_C")]
    # index 1 re-minted a new token_id; pool (token0/token1/fee) unchanged.
    current = [pos(0, "T0", "0xPOOL_A"), pos(1, "T1_NEW", "0xPOOL_B"), pos(2, "T2", "0xPOOL_C")]

    result = classify_positions(previous, current)

    assert len(result["matched"]) == 2
    assert len(result["rebalanced"]) == 1
    assert result["rebalanced"][0]["array_index"] == 1
    assert result["rebalanced"][0]["previous"]["token_id"] == "T1"
    assert result["rebalanced"][0]["current"]["token_id"] == "T1_NEW"
    assert result["closed"] == []
    assert result["opened"] == []
    assert result["ambiguous"] == []


# ── (c) multiple simultaneous rebalances — the real observed case ───────

def test_multiple_simultaneous_rebalances():
    # 20 positions, distinct pools so a coincidental pool match can't hide
    # a bug. Indices 3, 7, 12, 18 re-mint a new token_id with the same pool.
    rebalanced_indices = {3, 7, 12, 18}
    previous = [pos(i, f"T{i}", f"0xPOOL_{i}") for i in range(20)]
    current = [
        pos(i, f"T{i}_NEW" if i in rebalanced_indices else f"T{i}", f"0xPOOL_{i}")
        for i in range(20)
    ]

    result = classify_positions(previous, current)

    assert len(result["rebalanced"]) == 4
    assert {e["array_index"] for e in result["rebalanced"]} == rebalanced_indices
    assert len(result["matched"]) == 16
    assert result["closed"] == []
    assert result["opened"] == []
    assert result["ambiguous"] == []


# ── (d) close detected, with full re-indexing of trailing slots ─────────

def test_close_detected():
    # 5 positions, each with its own distinct pool. Index 2 closes. This
    # models the untested real-world case: the array compacts, so every
    # slot after the closed one shifts down by one (index 3 -> 2, 4 -> 3).
    # array_index alone would misread the shifted survivors as "index
    # reused" (rule c); token_id continuity is what correctly recognizes
    # them as still-matched, just relocated.
    previous = [pos(i, f"T{i}", f"0xPOOL_{i}") for i in range(5)]
    current = [
        pos(0, "T0", "0xPOOL_0"),
        pos(1, "T1", "0xPOOL_1"),
        pos(2, "T3", "0xPOOL_3"),  # was at index 3
        pos(3, "T4", "0xPOOL_4"),  # was at index 4
    ]

    result = classify_positions(previous, current)

    assert len(result["closed"]) == 1
    assert result["closed"][0]["previous"]["token_id"] == "T2"
    assert result["closed"][0]["current"] is None

    # T0 and T1 are untouched by the shrink - plain matches, no drift flag.
    untouched = {e["current"]["token_id"]: e for e in result["matched"] if not e.get("array_index_changed")}
    assert set(untouched) == {"T0", "T1"}

    # T3 and T4 shifted down by one slot but are still positively identified
    # (via token_id) as matched, not silently dropped or misclassified as
    # rebalanced/ambiguous.
    drifted = {e["current"]["token_id"]: e for e in result["matched"] if e.get("array_index_changed")}
    assert set(drifted) == {"T3", "T4"}
    assert drifted["T3"]["previous"]["array_index"] == 3
    assert drifted["T3"]["current"]["array_index"] == 2
    assert drifted["T4"]["previous"]["array_index"] == 4
    assert drifted["T4"]["current"]["array_index"] == 3

    assert len(result["matched"]) == 4
    assert result["rebalanced"] == []
    assert result["opened"] == []
    assert result["ambiguous"] == []


# ── (e) open detected ─────────────────────────────────────────────────────

def test_open_detected():
    previous = [pos(0, "T0", "0xPOOL_A"), pos(1, "T1", "0xPOOL_B"), pos(2, "T2", "0xPOOL_C")]
    current = [
        pos(0, "T0", "0xPOOL_A"),
        pos(1, "T1", "0xPOOL_B"),
        pos(2, "T2", "0xPOOL_C"),
        pos(3, "T3_NEW", "0xPOOL_NEW"),  # never seen before
    ]

    result = classify_positions(previous, current)

    assert len(result["opened"]) == 1
    assert result["opened"][0]["array_index"] == 3
    assert result["opened"][0]["current"]["token_id"] == "T3_NEW"
    assert result["opened"][0]["previous"] is None
    assert len(result["matched"]) == 3
    assert result["rebalanced"] == []
    assert result["closed"] == []
    assert result["ambiguous"] == []


# ── (f) ambiguous: index reused, pool differs, token_id genuinely new ───

def test_ambiguous_index_reuse():
    previous = [pos(0, "T0", "0xPOOL_A", token1="0xTOKEN_B", fee=3000), pos(1, "T1", "0xPOOL_B")]
    current = [
        # index 0: brand-new token_id (not seen anywhere in previous) AND a
        # different pool - could be close+open landing in the freed slot.
        pos(0, "T0_NEVER_SEEN", "0xPOOL_DIFFERENT", token1="0xTOKEN_C", fee=500),
        pos(1, "T1", "0xPOOL_B"),
    ]

    result = classify_positions(previous, current)

    assert len(result["ambiguous"]) == 1
    entry = result["ambiguous"][0]
    assert entry["array_index"] == 0
    assert "reason" in entry
    assert entry["reason"]  # non-empty
    assert "different pool" in entry["reason"]
    assert len(result["matched"]) == 1
    assert result["rebalanced"] == []
    assert result["closed"] == []
    assert result["opened"] == []


# ── (g) no previous state ────────────────────────────────────────────────

@pytest.mark.parametrize("previous", [None, []])
def test_no_previous_state(previous):
    current = [pos(0, "T0", "0xPOOL_A"), pos(1, "T1", "0xPOOL_B"), pos(2, "T2", "0xPOOL_C")]

    result = classify_positions(previous, current)

    assert len(result["opened"]) == 3
    assert result["matched"] == []
    assert result["rebalanced"] == []
    assert result["closed"] == []
    assert result["ambiguous"] == []


# ── (h) internal consistency check actually fires ────────────────────────

def test_internal_consistency_check_raises_on_unaccounted_entry():
    previous = [pos(0, "T0"), pos(1, "T1")]
    # Deliberately "forget" index 1 - simulates a rule-set bug that failed
    # to account for a previous entry.
    incomplete_accounted = {0}

    with pytest.raises(ValueError, match=r"1 previous position\(s\) not accounted for"):
        _assert_all_previous_accounted_for(previous, incomplete_accounted)


def test_internal_consistency_check_passes_when_complete():
    previous = [pos(0, "T0"), pos(1, "T1")]
    # Should not raise.
    _assert_all_previous_accounted_for(previous, {0, 1})


def test_classify_positions_never_raises_on_the_provided_fixtures():
    # classify_positions() itself should never trip its own consistency
    # check on any of the well-formed fixtures above - it's a defense
    # against a rule-set bug, not something a normal scan should hit.
    previous = [pos(i, f"T{i}", f"0xPOOL_{i}") for i in range(5)]
    current = [pos(0, "T0", "0xPOOL_0"), pos(1, "T1", "0xPOOL_1"),
               pos(2, "T3", "0xPOOL_3"), pos(3, "T4", "0xPOOL_4")]
    classify_positions(previous, current)  # should not raise


# ── (i) summarize ─────────────────────────────────────────────────────────

def test_summarize_matches_all_matched_fixture():
    previous = [pos(0, "T0", "0xPOOL_A"), pos(1, "T1", "0xPOOL_B"), pos(2, "T2", "0xPOOL_C")]
    result = classify_positions(previous, previous)
    assert summarize(result) == {"matched": 3, "rebalanced": 0, "closed": 0, "opened": 0, "ambiguous": 0}


def test_summarize_matches_multiple_rebalances_fixture():
    rebalanced_indices = {3, 7, 12, 18}
    previous = [pos(i, f"T{i}", f"0xPOOL_{i}") for i in range(20)]
    current = [
        pos(i, f"T{i}_NEW" if i in rebalanced_indices else f"T{i}", f"0xPOOL_{i}")
        for i in range(20)
    ]
    result = classify_positions(previous, current)
    summary = summarize(result)
    assert summary == {"matched": 16, "rebalanced": 4, "closed": 0, "opened": 0, "ambiguous": 0}
    for key, entries in result.items():
        assert summary[key] == len(entries)


def test_summarize_matches_close_detected_fixture():
    previous = [pos(i, f"T{i}", f"0xPOOL_{i}") for i in range(5)]
    current = [pos(0, "T0", "0xPOOL_0"), pos(1, "T1", "0xPOOL_1"),
               pos(2, "T3", "0xPOOL_3"), pos(3, "T4", "0xPOOL_4")]
    result = classify_positions(previous, current)
    summary = summarize(result)
    assert summary == {"matched": 4, "rebalanced": 0, "closed": 1, "opened": 0, "ambiguous": 0}
    for key, entries in result.items():
        assert summary[key] == len(entries)
