"""Tests for MaxFi Phase D.3.2a — ambiguity auto-resolution decision layer.

Pure functions only: maxfi_math.split_basis_proportional (rounding),
maxfi_matching.group_ambiguous_entries (grouping), and
maxfi_orchestration.decide_ambiguity_resolution (the decision). No network,
no database, no Flask test client - decide_ambiguity_resolution() takes
every input as a plain argument, so it's exercised directly rather than
through the /ambiguity-preview route.

Fixture shapes match production literally - an empty dict is not the same
as null, and mismatches of this kind have caused two prior escapes in this
repo (see the D.3.2a task spec). Departing/arriving mappings below always
use real dicts with real keys, never bare truthiness stand-ins.
"""

from datetime import datetime, timezone

import pytest

from maxfi_math import split_basis_proportional
from maxfi_matching import group_ambiguous_entries
from maxfi_orchestration import decide_ambiguity_resolution, AMBIGUITY_AUTO_SPLIT_SOURCE


def pos(idx, token_id, pool="0xPOOL_MSTR", token0="0xWETH", token1="0xMSTR", fee=3000):
    return {
        "array_index": idx,
        "token_id": token_id,
        "pool_address": pool,
        "token0_address": token0,
        "token1_address": token1,
        "fee_tier": fee,
    }


def ambiguous_entry(previous_pos, current_pos, reason):
    return {
        "array_index": (current_pos or previous_pos)["array_index"],
        "previous": previous_pos,
        "current": current_pos,
        "reason": reason,
    }


# ── The real WETH/MSTR case, used across several tests below ────────────────
MSTR_POOL = "0x70504a6fafdbfb75fe971faa4dd716e79ac5624c"
ROBINHOOD_CHAIN = "robinhood"  # chain id 4663


def _mstr_group():
    departing_entries = [
        ambiguous_entry(
            pos(0, "799578", pool=MSTR_POOL), pos(0, "834942", pool=MSTR_POOL),
            reason="multiple concurrent positions in same pool - array_index pairing not verifiable",
        ),
        ambiguous_entry(
            pos(1, "770744", pool=MSTR_POOL), pos(1, "842318", pool=MSTR_POOL),
            reason="multiple concurrent positions in same pool - array_index pairing not verifiable",
        ),
    ]
    groups = group_ambiguous_entries(departing_entries, chain=ROBINHOOD_CHAIN)
    assert len(groups) == 1
    return groups[0]


# ── 1. Real case, 2-vs-2, both bases present -> auto_split ──────────────────

def test_real_mstr_case_both_bases_present_auto_split():
    group = _mstr_group()
    current_values_by_token_id = {"834942": 257.53454955124613, "842318": 278.5612680400029}
    departing_info_by_token_id = {
        "799578": {"initial_value_usd": 334.00, "first_seen_at": datetime(2026, 6, 1, tzinfo=timezone.utc)},
        "770744": {"initial_value_usd": 259.00, "first_seen_at": datetime(2026, 5, 15, tzinfo=timezone.utc)},
    }

    decision = decide_ambiguity_resolution(group, current_values_by_token_id, departing_info_by_token_id)

    assert decision["outcome"] == "auto_split"
    assert decision["source"] == AMBIGUITY_AUTO_SPLIT_SOURCE
    proposed = {a["token_id"]: a["proposed_initial_value_usd"] for a in decision["arriving"]}
    total = proposed["834942"] + proposed["842318"]
    assert total == pytest.approx(593.00, abs=1e-9)
    # Larger current value (842318) must get the larger share.
    assert proposed["842318"] > proposed["834942"]
    # Allocation ratio matches the supplied current values, not a 50/50 guess.
    assert proposed["834942"] / total == pytest.approx(
        current_values_by_token_id["834942"] / sum(current_values_by_token_id.values()), abs=0.001
    )


# ── 2. Same case, one departing initial_value_usd is None -> auto_split_no_basis ──

def test_real_mstr_case_one_missing_basis_auto_split_no_basis():
    group = _mstr_group()
    current_values_by_token_id = {"834942": 257.53, "842318": 278.56}
    departing_info_by_token_id = {
        "799578": {"initial_value_usd": None, "first_seen_at": datetime(2026, 6, 1, tzinfo=timezone.utc)},
        "770744": {"initial_value_usd": 259.00, "first_seen_at": datetime(2026, 5, 15, tzinfo=timezone.utc)},
    }

    decision = decide_ambiguity_resolution(group, current_values_by_token_id, departing_info_by_token_id)

    assert decision["outcome"] == "auto_split_no_basis"
    for a in decision["arriving"]:
        assert a["proposed_initial_value_usd"] is None
    assert decision["discarded_basis_usd"] == 259.00
    assert decision["discarded_basis_token_id"] == "770744"


# ── 3. A departing initial_value_usd of 0.0 -> auto_split, NOT auto_split_no_basis ──
# This is the truthiness-vs-`is not None` regression test named explicitly.

def test_zero_initial_value_usd_is_present_not_treated_as_missing():
    group = _mstr_group()
    current_values_by_token_id = {"834942": 100.0, "842318": 100.0}
    departing_info_by_token_id = {
        "799578": {"initial_value_usd": 0.0, "first_seen_at": datetime(2026, 6, 1, tzinfo=timezone.utc)},
        "770744": {"initial_value_usd": 50.0, "first_seen_at": datetime(2026, 5, 15, tzinfo=timezone.utc)},
    }

    decision = decide_ambiguity_resolution(group, current_values_by_token_id, departing_info_by_token_id)

    assert decision["outcome"] == "auto_split"
    assert "discarded_basis_usd" not in decision
    proposed_total = sum(a["proposed_initial_value_usd"] for a in decision["arriving"])
    assert proposed_total == pytest.approx(50.0, abs=1e-9)  # 0.0 + 50.0, not discarded


# ── 4. One arriving position has no available current value -> defer_pricing ──

def test_one_arriving_current_value_missing_defers_pricing():
    group = _mstr_group()
    current_values_by_token_id = {"834942": 257.53, "842318": None}
    departing_info_by_token_id = {
        "799578": {"initial_value_usd": 334.00, "first_seen_at": datetime(2026, 6, 1, tzinfo=timezone.utc)},
        "770744": {"initial_value_usd": 259.00, "first_seen_at": datetime(2026, 5, 15, tzinfo=timezone.utc)},
    }

    decision = decide_ambiguity_resolution(group, current_values_by_token_id, departing_info_by_token_id)

    assert decision["outcome"] == "defer_pricing"
    assert decision["missing_current_value_token_ids"] == ["842318"]


def test_arriving_current_value_absent_from_mapping_also_defers_pricing():
    # An absent KEY must be treated identically to an explicit None.
    group = _mstr_group()
    current_values_by_token_id = {"834942": 257.53}  # 842318 key entirely absent
    departing_info_by_token_id = {
        "799578": {"initial_value_usd": 334.00, "first_seen_at": datetime(2026, 6, 1, tzinfo=timezone.utc)},
        "770744": {"initial_value_usd": 259.00, "first_seen_at": datetime(2026, 5, 15, tzinfo=timezone.utc)},
    }
    decision = decide_ambiguity_resolution(group, current_values_by_token_id, departing_info_by_token_id)
    assert decision["outcome"] == "defer_pricing"
    assert decision["missing_current_value_token_ids"] == ["842318"]


# ── 5. Both arriving current values are 0.0 -> defer_pricing, no ZeroDivisionError ──

def test_both_arriving_current_values_zero_defers_pricing_without_crash():
    group = _mstr_group()
    current_values_by_token_id = {"834942": 0.0, "842318": 0.0}
    departing_info_by_token_id = {
        "799578": {"initial_value_usd": 334.00, "first_seen_at": datetime(2026, 6, 1, tzinfo=timezone.utc)},
        "770744": {"initial_value_usd": 259.00, "first_seen_at": datetime(2026, 5, 15, tzinfo=timezone.utc)},
    }

    decision = decide_ambiguity_resolution(group, current_values_by_token_id, departing_info_by_token_id)

    assert decision["outcome"] == "defer_pricing"
    # Both values were technically "available" (0.0, not None) - the sum-to-
    # zero branch is what catches this, not the missing-value branch.
    assert decision["missing_current_value_token_ids"] == []


# ── 6. 3-vs-3 group -> manual_group_shape ────────────────────────────────────

def test_three_vs_three_group_is_manual_group_shape():
    entries = [
        ambiguous_entry(pos(i, f"OLD_{i}", pool=MSTR_POOL), pos(i, f"NEW_{i}", pool=MSTR_POOL), "reason")
        for i in range(3)
    ]
    groups = group_ambiguous_entries(entries, chain=ROBINHOOD_CHAIN)
    assert len(groups) == 1
    group = groups[0]

    decision = decide_ambiguity_resolution(group, {}, {})

    assert decision["outcome"] == "manual_group_shape"
    assert decision["departing_count"] == 3
    assert decision["arriving_count"] == 3


# ── 7. 2-vs-3 and 1-vs-2 -> manual_group_shape (synthetic, defense-in-depth) ──
# NOTE: today's matching (D.3.1's same-pool pass) cannot actually emit an
# asymmetric group - it counts candidates only within the provisional
# "rebalanced" bucket, where every entry pairs exactly one previous with one
# current position of the same pool, so the previous-side and current-side
# counts for any given pool are always equal by construction (see the D.3.1
# summary). These groups are constructed directly (bypassing
# group_ambiguous_entries' own grouping, which could never produce this
# shape from real classify_positions() output) purely to prove the
# defense-in-depth branch in decide_ambiguity_resolution behaves correctly
# if it is ever handed a shape group_ambiguous_entries did not itself build -
# not a scenario the live pipeline can produce today.

def test_two_vs_three_synthetic_group_is_manual_group_shape():
    group = {
        "chain": ROBINHOOD_CHAIN,
        "pool_address": MSTR_POOL,
        "pool_key": ("0xweth", "0xmstr", 3000),
        "departing": [{"token_id": "A", "array_index": 0}, {"token_id": "B", "array_index": 1}],
        "arriving": [
            {"token_id": "X", "array_index": 0},
            {"token_id": "Y", "array_index": 1},
            {"token_id": "Z", "array_index": 2},
        ],
        "array_indices": [0, 1, 2],
        "reasons": ["synthetic"],
    }
    decision = decide_ambiguity_resolution(group, {}, {})
    assert decision["outcome"] == "manual_group_shape"
    assert decision["departing_count"] == 2
    assert decision["arriving_count"] == 3


def test_one_vs_two_synthetic_group_is_manual_group_shape():
    group = {
        "chain": ROBINHOOD_CHAIN,
        "pool_address": MSTR_POOL,
        "pool_key": ("0xweth", "0xmstr", 3000),
        "departing": [{"token_id": "A", "array_index": 0}],
        "arriving": [{"token_id": "X", "array_index": 0}, {"token_id": "Y", "array_index": 1}],
        "array_indices": [0, 1],
        "reasons": ["synthetic"],
    }
    decision = decide_ambiguity_resolution(group, {}, {})
    assert decision["outcome"] == "manual_group_shape"
    assert decision["departing_count"] == 1
    assert decision["arriving_count"] == 2


# ── 8. split_basis_proportional rounding: naive independent rounding misses ──

def test_split_basis_proportional_rounding_lands_on_larger_side():
    # total_basis=130.05 (13005 cents); current_values 178.44/892.20 make
    # each side's raw cents share land exactly on a half-cent (2167.5 and
    # 10837.5). Rounding each side INDEPENDENTLY (round(2167.5)=2168,
    # round(10837.5)=10838, both banker's-rounding to the nearest even) sums
    # to 13006 cents ($130.06) - one cent OVER total_basis. The function must
    # never do that: the smaller side (178.44) is rounded directly, and the
    # larger side (892.20) absorbs whatever's left, so the sum is exact.
    result = split_basis_proportional(130.05, [178.44, 892.20])
    assert sum(result) == pytest.approx(130.05, abs=1e-9)
    assert result[0] == pytest.approx(21.68, abs=1e-9)   # smaller value, directly rounded
    assert result[1] == pytest.approx(108.37, abs=1e-9)  # larger value, absorbs the residual
    assert result[1] > result[0]


def test_split_basis_proportional_order_preserved_regardless_of_magnitude():
    # Output order must match input order even when index 0 holds the
    # LARGER value (the "smaller gets rounded directly" rule is about
    # magnitude, not position).
    result = split_basis_proportional(130.05, [892.20, 178.44])
    assert sum(result) == pytest.approx(130.05, abs=1e-9)
    assert result[0] == pytest.approx(108.37, abs=1e-9)  # now at index 0 (larger)
    assert result[1] == pytest.approx(21.68, abs=1e-9)   # now at index 1 (smaller)


def test_split_basis_proportional_real_mstr_values_sum_exactly():
    result = split_basis_proportional(593.00, [257.53454955124613, 278.5612680400029])
    assert sum(result) == pytest.approx(593.00, abs=1e-9)
    assert result[0] < result[1]  # 834942's slot got the smaller current value


def test_split_basis_proportional_raises_on_none_total_basis():
    with pytest.raises(ValueError):
        split_basis_proportional(None, [10.0, 20.0])


def test_split_basis_proportional_raises_on_wrong_length():
    with pytest.raises(ValueError):
        split_basis_proportional(100.0, [10.0, 20.0, 30.0])
    with pytest.raises(ValueError):
        split_basis_proportional(100.0, [10.0])


def test_split_basis_proportional_raises_on_none_current_value():
    with pytest.raises(ValueError):
        split_basis_proportional(100.0, [10.0, None])


def test_split_basis_proportional_raises_on_negative_current_value():
    with pytest.raises(ValueError):
        split_basis_proportional(100.0, [-5.0, 20.0])


def test_split_basis_proportional_raises_on_zero_sum():
    with pytest.raises(ValueError):
        split_basis_proportional(100.0, [0.0, 0.0])


# ── 9. inherit_first_seen_at returns the EARLIER of the two departing dates ──

def test_inherit_first_seen_at_is_earlier_of_the_two_departing_dates():
    group = _mstr_group()
    current_values_by_token_id = {"834942": 257.53, "842318": 278.56}
    earlier = datetime(2026, 5, 15, tzinfo=timezone.utc)
    later = datetime(2026, 6, 1, tzinfo=timezone.utc)
    departing_info_by_token_id = {
        "799578": {"initial_value_usd": 334.00, "first_seen_at": later},
        "770744": {"initial_value_usd": 259.00, "first_seen_at": earlier},
    }

    decision = decide_ambiguity_resolution(group, current_values_by_token_id, departing_info_by_token_id)

    assert decision["outcome"] == "auto_split"
    assert decision["inherit_first_seen_at"] == earlier


def test_inherit_first_seen_at_also_reported_for_auto_split_no_basis():
    group = _mstr_group()
    current_values_by_token_id = {"834942": 257.53, "842318": 278.56}
    earlier = datetime(2026, 5, 15, tzinfo=timezone.utc)
    later = datetime(2026, 6, 1, tzinfo=timezone.utc)
    departing_info_by_token_id = {
        "799578": {"initial_value_usd": None, "first_seen_at": later},
        "770744": {"initial_value_usd": 259.00, "first_seen_at": earlier},
    }

    decision = decide_ambiguity_resolution(group, current_values_by_token_id, departing_info_by_token_id)

    assert decision["outcome"] == "auto_split_no_basis"
    assert decision["inherit_first_seen_at"] == earlier


# ── 10. Grouping: two same-pool entries collapse into one 2-vs-2 group ──────

def test_grouping_collapses_two_same_pool_entries_into_one_group_with_reasons_preserved():
    reason_a = "multiple concurrent positions in same pool - array_index pairing not verifiable"
    reason_b = "multiple concurrent positions in same pool - array_index pairing not verifiable"
    entries = [
        ambiguous_entry(pos(0, "799578", pool=MSTR_POOL), pos(0, "834942", pool=MSTR_POOL), reason_a),
        ambiguous_entry(pos(1, "770744", pool=MSTR_POOL), pos(1, "842318", pool=MSTR_POOL), reason_b),
    ]

    groups = group_ambiguous_entries(entries, chain=ROBINHOOD_CHAIN)

    assert len(groups) == 1
    group = groups[0]
    assert group["chain"] == ROBINHOOD_CHAIN
    assert group["pool_address"] == MSTR_POOL
    assert {d["token_id"] for d in group["departing"]} == {"799578", "770744"}
    assert {a["token_id"] for a in group["arriving"]} == {"834942", "842318"}
    assert group["reasons"] == [reason_a, reason_b]


# ── 11. A lone (non-collision) ambiguous entry becomes its own group ────────

def test_grouping_lone_index_reused_entry_becomes_its_own_single_entry_group():
    lone_reason = "array_index reused with different pool - possible close+open, not a rebalance"
    entries = [
        ambiguous_entry(
            pos(5, "OLD_TOKEN", pool="0xPOOL_A", token0="0xA0", token1="0xA1"),
            pos(5, "NEW_TOKEN_NEVER_SEEN", pool="0xPOOL_DIFFERENT", token0="0xB0", token1="0xB1"),
            lone_reason,
        ),
    ]

    groups = group_ambiguous_entries(entries, chain=ROBINHOOD_CHAIN)

    assert len(groups) == 1
    group = groups[0]
    assert group["reasons"] == [lone_reason]
    assert len(group["departing"]) == 1
    assert len(group["arriving"]) == 1
    assert group["departing"][0]["token_id"] == "OLD_TOKEN"
    assert group["arriving"][0]["token_id"] == "NEW_TOKEN_NEVER_SEEN"


def test_grouping_does_not_merge_unrelated_pools():
    entries = [
        ambiguous_entry(
            pos(0, "OLD_A", pool="0xPOOL_A", token0="0xA0", token1="0xA1"),
            pos(0, "NEW_A", pool="0xPOOL_DIFF_A", token0="0xA0", token1="0xA2"),
            "array_index reused with different pool - possible close+open, not a rebalance",
        ),
        ambiguous_entry(
            pos(1, "OLD_B", pool="0xPOOL_B", token0="0xB0", token1="0xB1"),
            pos(1, "NEW_B", pool="0xPOOL_DIFF_B", token0="0xB0", token1="0xB2"),
            "array_index reused with different pool - possible close+open, not a rebalance",
        ),
    ]
    groups = group_ambiguous_entries(entries, chain=ROBINHOOD_CHAIN)
    assert len(groups) == 2


# ── 12. Grouping: an entry with previous=None or current=None is handled ────

def test_grouping_handles_none_previous_without_raising():
    entries = [ambiguous_entry(None, pos(2, "NEW_ONLY"), "synthetic: no departing side")]
    groups = group_ambiguous_entries(entries, chain=ROBINHOOD_CHAIN)
    assert len(groups) == 1
    assert groups[0]["departing"] == []
    assert len(groups[0]["arriving"]) == 1
    assert groups[0]["arriving"][0]["token_id"] == "NEW_ONLY"


def test_grouping_handles_none_current_without_raising():
    entries = [ambiguous_entry(pos(3, "OLD_ONLY"), None, "synthetic: no arriving side")]
    groups = group_ambiguous_entries(entries, chain=ROBINHOOD_CHAIN)
    assert len(groups) == 1
    assert groups[0]["arriving"] == []
    assert len(groups[0]["departing"]) == 1
    assert groups[0]["departing"][0]["token_id"] == "OLD_ONLY"


def test_grouping_handles_both_sides_none_without_raising():
    # Built directly (not via ambiguous_entry(), which mirrors
    # maxfi_matching._entry()'s own array_index derivation and would itself
    # raise on both-None input) - classify_positions() never produces this
    # shape either, but group_ambiguous_entries() must not assume it can't
    # receive it.
    entries = [{"array_index": 9, "previous": None, "current": None,
                "reason": "synthetic: neither side present"}]
    groups = group_ambiguous_entries(entries, chain=ROBINHOOD_CHAIN)
    assert len(groups) == 1
    assert groups[0]["departing"] == []
    assert groups[0]["arriving"] == []
    assert groups[0]["pool_address"] is None


def test_grouping_no_pool_data_fallback_keys_uniquely_per_entry():
    # Two separate none/none entries must NOT merge into one group - the
    # "__no_pool_data__" fallback key still includes array_index, exactly
    # as before this fix (this branch is untouched by it).
    entries = [
        {"array_index": 9, "previous": None, "current": None,
         "reason": "synthetic: neither side present"},
        {"array_index": 10, "previous": None, "current": None,
         "reason": "synthetic: neither side present"},
    ]
    groups = group_ambiguous_entries(entries, chain=ROBINHOOD_CHAIN)
    assert len(groups) == 2
    for group in groups:
        assert group["pool_address"] is None
        assert group["departing"] == []
        assert group["arriving"] == []


# ── 13. Grouping fix: BOTH sides must match a group, not the departing ──────
# ── pool alone (the confirmed production incident) ──────────────────────────
#
# Pre-fix, group_ambiguous_entries() keyed a group on whichever side was
# present, always preferring the departing side when both existed. Two
# INDEPENDENT rule-(c) "array_index reused with different pool" entries that
# happened to depart the SAME pool therefore merged into one false 2-vs-2
# group even though their arriving positions were in two entirely unrelated
# pools - decide_ambiguity_resolution then correctly passed a 2-vs-2 shape
# check on a group that should never have existed, and
# resolve_ambiguous_auto_splits pooled both departing cost bases and split
# the total across two positions that had never collided at all. Confirmed
# in production 2026-08-29 on robinhood: array_index 11 and 12 both departed
# 0x70504a6fafdbfb75fe971faa4dd716e79ac5624c but arrived in
# 0xec6a2662de42da97b338430a0c51dd8774bd8969 and
# 0xe3b608eec422701e07c5c16995fe9e30fff93fd0 respectively - two different,
# unrelated pools, 593.00 of cost basis fabricated across rows 31 and 32.

def test_grouping_two_independent_close_opens_from_same_pool_stay_separate():
    """The exact production incident, reconstructed: two positions depart
    the SAME pool (MSTR_POOL, standing in for the real departing pool
    0x70504a6fafdbfb75fe971faa4dd716e79ac5624c) but arrive in two DIFFERENT,
    unrelated pools (the real arriving pool addresses from the incident).
    Must produce TWO separate 1-vs-1 groups, never one false 2-vs-2."""
    entries = [
        ambiguous_entry(
            pos(11, "OLD_11", pool=MSTR_POOL, token0="0xWETH", token1="0xMSTR"),
            pos(11, "863267", pool="0xec6a2662de42da97b338430a0c51dd8774bd8969",
                token0="0xWETH", token1="0xTOKENA"),
            "array_index reused with different pool - possible close+open, not a rebalance",
        ),
        ambiguous_entry(
            pos(12, "OLD_12", pool=MSTR_POOL, token0="0xWETH", token1="0xMSTR"),
            pos(12, "863197", pool="0xe3b608eec422701e07c5c16995fe9e30fff93fd0",
                token0="0xWETH", token1="0xTOKENB"),
            "array_index reused with different pool - possible close+open, not a rebalance",
        ),
    ]

    groups = group_ambiguous_entries(entries, chain=ROBINHOOD_CHAIN)

    assert len(groups) == 2
    for group in groups:
        assert len(group["departing"]) == 1
        assert len(group["arriving"]) == 1
    arriving_token_ids = {g["arriving"][0]["token_id"] for g in groups}
    assert arriving_token_ids == {"863267", "863197"}
    departing_token_ids = {g["departing"][0]["token_id"] for g in groups}
    assert departing_token_ids == {"OLD_11", "OLD_12"}
    # pool_address on each group must still be the DEPARTING pool - the
    # notes-JSON provenance meaning is unchanged by this fix.
    for group in groups:
        assert group["pool_address"] == MSTR_POOL


def test_grouping_genuine_same_pool_collision_still_merges_into_one_2v2_group():
    """Both departing AND both arriving in the same pool - the real
    rebalance-collision case (rows 27/28 in production) - must remain
    exactly as before: one group, 2-vs-2."""
    entries = [
        ambiguous_entry(
            pos(0, "OLD_1", pool=MSTR_POOL, token0="0xWETH", token1="0xMSTR"),
            pos(0, "NEW_1", pool=MSTR_POOL, token0="0xWETH", token1="0xMSTR"),
            "multiple concurrent positions in same pool - array_index pairing not verifiable",
        ),
        ambiguous_entry(
            pos(1, "OLD_2", pool=MSTR_POOL, token0="0xWETH", token1="0xMSTR"),
            pos(1, "NEW_2", pool=MSTR_POOL, token0="0xWETH", token1="0xMSTR"),
            "multiple concurrent positions in same pool - array_index pairing not verifiable",
        ),
    ]

    groups = group_ambiguous_entries(entries, chain=ROBINHOOD_CHAIN)

    assert len(groups) == 1
    group = groups[0]
    assert len(group["departing"]) == 2
    assert len(group["arriving"]) == 2


def test_grouping_pool_identity_is_case_insensitive():
    """The same pool identity in differing checksum casing must still
    merge into one group - _pool_key() already lowercases token0/token1,
    and both the departing-side and arriving-side keys this fix introduces
    reuse that same primitive."""
    entries = [
        ambiguous_entry(
            pos(0, "OLD_1", pool=MSTR_POOL, token0="0xWETH", token1="0xMSTR"),
            pos(0, "NEW_1", pool=MSTR_POOL, token0="0xWETH", token1="0xMSTR"),
            "multiple concurrent positions in same pool - array_index pairing not verifiable",
        ),
        ambiguous_entry(
            pos(1, "OLD_2", pool=MSTR_POOL, token0="0xweth", token1="0xmstr"),
            pos(1, "NEW_2", pool=MSTR_POOL, token0="0xWETH", token1="0xMSTR"),
            "multiple concurrent positions in same pool - array_index pairing not verifiable",
        ),
    ]

    groups = group_ambiguous_entries(entries, chain=ROBINHOOD_CHAIN)

    assert len(groups) == 1
    assert len(groups[0]["departing"]) == 2
    assert len(groups[0]["arriving"]) == 2


def test_grouping_pure_departure_and_pure_arrival_in_same_pool_do_not_merge():
    """A pure departure (no arriving side) and a pure arrival (no departing
    side) in the SAME pool must never merge into one group - an absent
    side keys as an explicit absence, never a wildcard."""
    entries = [
        ambiguous_entry(
            pos(0, "OLD_ONLY", pool=MSTR_POOL, token0="0xWETH", token1="0xMSTR"), None,
            "synthetic: no arriving side",
        ),
        ambiguous_entry(
            None, pos(1, "NEW_ONLY", pool=MSTR_POOL, token0="0xWETH", token1="0xMSTR"),
            "synthetic: no departing side",
        ),
    ]

    groups = group_ambiguous_entries(entries, chain=ROBINHOOD_CHAIN)

    assert len(groups) == 2
    for group in groups:
        assert len(group["departing"]) + len(group["arriving"]) == 1


def test_cross_pool_close_opens_resolve_to_manual_group_shape_not_auto_split():
    """Downstream verification: the two separate groups produced by the
    production-incident regression above must each resolve to
    manual_group_shape (writes nothing) when passed through
    decide_ambiguity_resolution, never auto_split."""
    entries = [
        ambiguous_entry(
            pos(11, "OLD_11", pool=MSTR_POOL, token0="0xWETH", token1="0xMSTR"),
            pos(11, "863267", pool="0xec6a2662de42da97b338430a0c51dd8774bd8969",
                token0="0xWETH", token1="0xTOKENA"),
            "array_index reused with different pool - possible close+open, not a rebalance",
        ),
        ambiguous_entry(
            pos(12, "OLD_12", pool=MSTR_POOL, token0="0xWETH", token1="0xMSTR"),
            pos(12, "863197", pool="0xe3b608eec422701e07c5c16995fe9e30fff93fd0",
                token0="0xWETH", token1="0xTOKENB"),
            "array_index reused with different pool - possible close+open, not a rebalance",
        ),
    ]

    groups = group_ambiguous_entries(entries, chain=ROBINHOOD_CHAIN)
    assert len(groups) == 2

    for group in groups:
        decision = decide_ambiguity_resolution(group, {}, {})
        assert decision["outcome"] == "manual_group_shape"
        assert decision["departing_count"] == 1
        assert decision["arriving_count"] == 1
