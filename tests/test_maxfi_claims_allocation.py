"""Unit tests for maxfi_math.allocate_proportional and allocate_claims
(Phase D.3.3) — pure functions, no DB, no network.

allocate_proportional generalizes split_basis_proportional (money-path,
2-value-only) to any list length >= 1. The equivalence tests below are
the ones that stop the two functions drifting apart at n=2.
"""

import pytest

from maxfi_math import (
    split_basis_proportional,
    allocate_proportional,
    allocate_claims,
)


# ── allocate_proportional: equivalence with split_basis_proportional at n=2 ──
#
# Every pair here has a positive sum (v0 + v1 != 0), because
# split_basis_proportional RAISES ValueError on a zero sum — there is no
# "same list" to compare against for that input. allocate_proportional's
# zero-sum behavior (distribute evenly, never raise) is a DELIBERATE,
# spec-required widening for the claims path, not a bug in the existing
# function, and is covered separately below rather than folded into this
# equivalence loop.
EQUIVALENCE_CASES = [
    (100.0, [40.0, 60.0]),
    (100.0, [60.0, 40.0]),
    (100.0, [50.0, 50.0]),          # exact tie
    (0.01, [1.0, 1.0]),             # smallest possible cent, exact tie
    (33.33, [10.0, 20.0]),          # awkward cents
    (100.005, [1.0, 2.0]),          # sub-cent total, float-rounding-prone
    (593.0, [0.0, 100.0]),          # one side zero, sum still positive
    (593.0, [100.0, 0.0]),          # zero on the other side
    (7.0, [1.0, 1000.0]),           # lopsided ratio
    (250.0, [123.45, 126.55]),      # near-tie, non-round values
]


@pytest.mark.parametrize("total,values", EQUIVALENCE_CASES)
def test_allocate_proportional_matches_split_basis_proportional_at_n2(total, values):
    assert allocate_proportional(total, values) == split_basis_proportional(total, values)


# ── allocate_proportional: n=1, n=3, n=4 sum exactly ────────────────────────

def test_n1_returns_rounded_total():
    assert allocate_proportional(123.456, [999.0]) == [123.46]
    assert allocate_proportional(0.0, [0.0]) == [0.0]
    assert allocate_proportional(50.0, [0.0]) == [50.0]


@pytest.mark.parametrize("total,values", [
    (100.0, [10.0, 20.0, 30.0]),
    (0.01, [1.0, 1.0, 1.0]),
    (999.99, [1.0, 2.0, 3.0]),
    (37.0, [5.0, 5.0, 5.0]),         # 3-way exact tie
])
def test_n3_sums_exactly(total, values):
    shares = allocate_proportional(total, values)
    assert len(shares) == 3
    assert round(sum(shares), 2) == round(total, 2)


@pytest.mark.parametrize("total,values", [
    (100.0, [10.0, 20.0, 30.0, 40.0]),
    (0.03, [1.0, 1.0, 1.0, 1.0]),
    (1234.56, [1.0, 1.0, 1.0, 1.0]),
])
def test_n4_sums_exactly(total, values):
    shares = allocate_proportional(total, values)
    assert len(shares) == 4
    assert round(sum(shares), 2) == round(total, 2)


# ── allocate_proportional: zero-sum values distributes, never zeroes ───────

def test_zero_sum_values_distributes_evenly_remainder_to_index_0():
    # split_basis_proportional would raise ValueError here (v0 + v1 == 0).
    with pytest.raises(ValueError):
        split_basis_proportional(100.0, [0.0, 0.0])

    shares = allocate_proportional(100.0, [0.0, 0.0])
    assert shares == [50.0, 50.0]
    assert sum(shares) == 100.0

    shares3 = allocate_proportional(100.0, [0.0, 0.0, 0.0])
    assert round(sum(shares3), 2) == 100.0
    # 10000 cents / 3 = 3333 base, remainder 1 -> index 0 gets it.
    assert shares3 == [33.34, 33.33, 33.33]


def test_zero_sum_values_zero_total_is_all_zeros():
    assert allocate_proportional(0.0, [0.0, 0.0]) == [0.0, 0.0]


# ── allocate_proportional: total == 0 with a nonzero-sum values list ───────

def test_total_zero_returns_all_zeros():
    assert allocate_proportional(0.0, [10.0, 20.0, 30.0]) == [0.0, 0.0, 0.0]


# ── allocate_proportional: ValueError cases ────────────────────────────────

def test_none_total_raises():
    with pytest.raises(ValueError):
        allocate_proportional(None, [1.0, 2.0])


def test_negative_total_raises():
    with pytest.raises(ValueError):
        allocate_proportional(-1.0, [1.0, 2.0])


def test_empty_values_raises():
    with pytest.raises(ValueError):
        allocate_proportional(100.0, [])


def test_none_value_raises():
    with pytest.raises(ValueError):
        allocate_proportional(100.0, [1.0, None])


def test_negative_value_raises():
    with pytest.raises(ValueError):
        allocate_proportional(100.0, [1.0, -2.0])


# ── allocate_proportional: float-drift case, integer-cents proof ──────────
#
# NOTE (deviation from the block spec's literal wording - see final
# summary): the spec describes this case as summing to "exactly 0.30".
# A bare Python float sum of the returned shares (0.1 + 0.2) can never
# bit-for-bit equal the literal 0.30 - that is the well-known IEEE-754
# binary float representation gap, present for ANY implementation that
# returns per-share floats of 0.1 and 0.2, not a flaw in this function.
# What integer-cents arithmetic actually guarantees, and what this test
# proves directly, is that the underlying CENT INTEGERS sum exactly to
# round(total * 100) - the two-decimal-rounded float sum matches too.

def test_float_drift_case_sums_to_exactly_030():
    shares = allocate_proportional(0.30, [0.1, 0.2])
    assert round(sum(shares), 2) == 0.30
    cents = [round(s * 100) for s in shares]
    assert sum(cents) == round(0.30 * 100)


# ── allocate_claims ─────────────────────────────────────────────────────────

def _lineage_row(id_, departing, arriving, split_group_id, arriving_value):
    return {
        "id": id_,
        "departing_position_id": departing,
        "arriving_position_id": arriving,
        "split_group_id": split_group_id,
        "arriving_current_value_usd": arriving_value,
    }


def test_empty_lineage_returns_claims_unchanged():
    claims = {1: 50.0, 2: 0.0}
    result = allocate_claims(claims, [])
    assert result == claims
    assert result is not claims  # not the same object - documented as not mutated


def test_2x2_cross_product_no_double_allocation():
    # One split group: departing D=10 (holding $100 of claims), arriving
    # A=11 (value 300) and A=12 (value 700). The cross product means D
    # pairs with BOTH arriving rows, and (per the schema/spec) BOTH
    # departing rows in a real 2x2 group pair with both arriving rows -
    # here there is only one departing row with claims, so we model the
    # full 2x2 shape (two departing ids sharing the group) but give only
    # one of them claims, to isolate the double-allocation risk on A11/A12.
    lineage = [
        _lineage_row(1, 10, 11, "g1", 300.0),
        _lineage_row(2, 10, 12, "g1", 700.0),
        _lineage_row(3, 20, 11, "g1", 300.0),
        _lineage_row(4, 20, 12, "g1", 700.0),
    ]
    claims = {10: 100.0}
    result = allocate_claims(claims, lineage)

    assert result[11] == 30.0
    assert result[12] == 70.0
    assert result[11] + result[12] == 100.0
    # Departing id 20 had no own claims and is not an arriving id anywhere.
    assert 20 not in result


def test_two_departing_rows_each_with_claims_in_one_group():
    lineage = [
        _lineage_row(1, 10, 12, "g1", 300.0),
        _lineage_row(2, 10, 13, "g1", 700.0),
        _lineage_row(3, 11, 12, "g1", 300.0),
        _lineage_row(4, 11, 13, "g1", 700.0),
    ]
    claims = {10: 100.0, 11: 50.0}
    result = allocate_claims(claims, lineage)

    # 10 -> [30, 70], 11 -> [15, 35]
    assert result[12] == pytest.approx(45.0)
    assert result[13] == pytest.approx(105.0)
    assert result[12] + result[13] == pytest.approx(150.0)


def test_multi_hop_a_to_b_to_c_forward_order():
    # A(1) -splits into-> B(2) [group g1]; B(2) -splits into-> C(3) [group g2].
    lineage = [
        _lineage_row(1, 1, 2, "g1", 500.0),
        _lineage_row(2, 2, 3, "g2", 500.0),
    ]
    claims = {1: 40.0}
    result = allocate_claims(claims, lineage)
    assert result[2] == 40.0
    assert result[3] == 40.0


def test_multi_hop_is_order_independent_when_reversed():
    lineage_forward = [
        _lineage_row(1, 1, 2, "g1", 500.0),
        _lineage_row(2, 2, 3, "g2", 500.0),
    ]
    lineage_reversed = list(reversed(lineage_forward))
    claims = {1: 40.0}
    assert allocate_claims(claims, lineage_forward) == allocate_claims(claims, lineage_reversed)


def test_arriving_row_with_own_claims_plus_inherited_share():
    lineage = [
        _lineage_row(1, 10, 11, "g1", 300.0),
        _lineage_row(2, 10, 12, "g1", 700.0),
    ]
    claims = {10: 100.0, 11: 5.0}
    result = allocate_claims(claims, lineage)
    # 11's own $5 plus its 30% share of D10's $100 = $35 total.
    assert result[11] == pytest.approx(35.0)
    assert result[12] == pytest.approx(70.0)


def test_group_with_three_arriving_rows_does_not_raise():
    lineage = [
        _lineage_row(1, 10, 11, "g1", 100.0),
        _lineage_row(2, 10, 12, "g1", 200.0),
        _lineage_row(3, 10, 13, "g1", 300.0),
    ]
    claims = {10: 60.0}
    result = allocate_claims(claims, lineage)
    assert round(result[11] + result[12] + result[13], 2) == 60.0
    assert result[11] < result[12] < result[13]


def test_row_violating_id_ordering_is_skipped_not_raised(caplog):
    # arriving(5) < departing(10) - violates the AUTOINCREMENT ordering
    # guarantee. Must be skipped, not raised, and must not contaminate the
    # rest of its group.
    lineage = [
        _lineage_row(1, 10, 5, "g1", 999.0),
        _lineage_row(2, 10, 11, "g1", 300.0),
        _lineage_row(3, 10, 12, "g1", 700.0),
    ]
    claims = {10: 100.0}
    result = allocate_claims(claims, lineage)
    assert 5 not in result
    assert result[11] == 30.0
    assert result[12] == 70.0


def test_determinism_under_shuffled_input():
    import random

    lineage = [
        _lineage_row(1, 1, 2, "g1", 300.0),
        _lineage_row(2, 1, 3, "g1", 700.0),
        _lineage_row(3, 4, 2, "g1", 300.0),
        _lineage_row(4, 4, 3, "g1", 700.0),
        _lineage_row(5, 2, 5, "g2", 1000.0),
    ]
    claims = {1: 100.0, 4: 50.0}

    baseline = allocate_claims(claims, lineage)
    for seed in range(10):
        shuffled = list(lineage)
        random.Random(seed).shuffle(shuffled)
        assert allocate_claims(claims, shuffled) == baseline
