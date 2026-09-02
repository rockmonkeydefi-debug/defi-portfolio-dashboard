"""Pure tick/price math for MaxFi LP diagnostics — no network, no imports
from web_portfolio.py. Kept side-effect-free so it's testable in a sandbox
with no RPC egress (see tests/test_maxfi_math.py).
"""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

Q96 = Decimal(2) ** 96


def to_signed(word_int, bits):
    """Two's-complement sign extension of the low `bits` bits of word_int.

    word_int may be the raw sub-word value or a full 256-bit word already
    sign-extended by the EVM — masking to the low `bits` bits first makes
    both representations decode identically.
    """
    mask = (1 << bits) - 1
    value = word_int & mask
    sign_bit = 1 << (bits - 1)
    if value & sign_bit:
        value -= (1 << bits)
    return value


def to_int24(word_int):
    return to_signed(word_int, 24)


def to_int128(word_int):
    return to_signed(word_int, 128)


def to_int56(word_int):
    return to_signed(word_int, 56)


def tick_to_price(tick, decimals0, decimals1):
    """token1-per-token0 price at `tick`, adjusted for token decimals."""
    return (1.0001 ** tick) * (10 ** (decimals0 - decimals1))


def sqrt_price_x96_to_price(sqrt_price_x96, decimals0, decimals1):
    """token1-per-token0 price from a slot0 sqrtPriceX96 fixed-point value.

    Uses Decimal throughout so squaring happens before any float cast —
    casting sqrt_price_x96 to float first loses precision for realistic
    on-chain magnitudes (~2^96..2^160).
    """
    ratio = Decimal(sqrt_price_x96) / Q96
    price = (ratio * ratio) * (Decimal(10) ** (decimals0 - decimals1))
    return float(price)


def range_percent(tick_lower, tick_upper, decimals0, decimals1):
    """Percent width of a [tick_lower, tick_upper] range, tick-derived."""
    price_lower = tick_to_price(tick_lower, decimals0, decimals1)
    price_upper = tick_to_price(tick_upper, decimals0, decimals1)
    return (price_upper / price_lower - 1) * 100


def invert_price(price):
    """1 / price, guarded against division by zero."""
    if price == 0:
        raise ValueError("cannot invert a zero price")
    return 1.0 / price


# ── Phase D additions: uncollected-fee math + liquidity->amounts ────────
# Absent before this phase (see Phase D STEP 1 report). Both are raw
# on-chain math — same category as everything above — so they live here,
# not in maxfi_pricing.py. Neither does any decimals adjustment or USD
# conversion; both return raw base-unit quantities. maxfi_pricing.py's
# value_position() is responsible for the decimals division (the "final
# division producing a display value") and the USD multiplication.

MASK_256 = (1 << 256) - 1


def fee_growth_inside(current_tick, tick_lower, tick_upper, fee_growth_global,
                       fee_growth_outside_lower, fee_growth_outside_upper):
    """Standard Uniswap V3 feeGrowthInside formula, for ONE token (call
    once per token with that token's own feeGrowthGlobal/Outside values).

    feeGrowthInside = feeGrowthGlobal - feeGrowthBelow - feeGrowthAbove,
    with feeGrowthBelow/Above selected by where current_tick sits relative
    to [tick_lower, tick_upper) (exactly mirroring Uniswap V3 core's own
    Tick.getFeeGrowthInside branch selection):
      feeGrowthBelow = feeGrowthOutside_lower           if current_tick >= tick_lower
                      = feeGrowthGlobal - feeGrowthOutside_lower   otherwise
      feeGrowthAbove = feeGrowthOutside_upper           if current_tick <  tick_upper
                      = feeGrowthGlobal - feeGrowthOutside_upper   otherwise

    All values are raw X128 fixed-point uint256 accumulators. Underflow in
    these subtractions is EXPECTED and correct (the accumulator wraps
    around uint256 by design) — masked to 2**256-1, never guarded against.
    """
    if current_tick >= tick_lower:
        below = fee_growth_outside_lower & MASK_256
    else:
        below = (fee_growth_global - fee_growth_outside_lower) & MASK_256
    if current_tick < tick_upper:
        above = fee_growth_outside_upper & MASK_256
    else:
        above = (fee_growth_global - fee_growth_outside_upper) & MASK_256
    return (fee_growth_global - below - above) & MASK_256


def uncollected_fees(liquidity, fee_growth_inside_current, fee_growth_inside_last, tokens_owed):
    """uncollected = liquidity * (feeGrowthInside - feeGrowthInsideLast) / 2**128,
    plus the position's already-accrued tokensOwed. Returns a raw base-unit
    integer (not decimals-adjusted) for ONE token — call once per token.

    The (feeGrowthInside - feeGrowthInsideLast) subtraction wraps the same
    way as fee_growth_inside()'s internal subtractions — masked, not guarded.
    """
    delta = (fee_growth_inside_current - fee_growth_inside_last) & MASK_256
    return ((liquidity * delta) >> 128) + tokens_owed


def liquidity_to_amounts(liquidity, tick_lower, tick_upper, current_tick, sqrt_price_x96):
    """Standard Uniswap V3 liquidity->amounts formula. Returns
    (amount0_raw, amount1_raw) in RAW base units (not decimals-adjusted).

    sqrt_price_x96 is the pool's actual current sqrtPriceX96 (exact,
    on-chain integer). The tick-boundary sqrt prices for tick_lower/
    tick_upper have no equivalent on-chain integer available to us, so
    they're derived via 1.0001**(tick/2) in float space — the same
    convention tick_to_price() already uses elsewhere in this module.
    This is not bit-exact with Uniswap's own TickMath library (a
    log-based bit-shift algorithm), but it agrees far beyond what USD
    valuation needs.

    Branch selection mirrors fee_growth_inside()'s tick boundaries exactly
    (current_tick < tick_lower / >= tick_upper / in between), so a
    position priced "at the edge" of its range is treated consistently by
    both functions.
    """
    sqrt_lower = 1.0001 ** (tick_lower / 2)
    sqrt_upper = 1.0001 ** (tick_upper / 2)
    sqrt_current = float(Decimal(sqrt_price_x96) / Q96)

    if current_tick < tick_lower:
        amount0_raw = liquidity * (1 / sqrt_lower - 1 / sqrt_upper)
        amount1_raw = 0.0
    elif current_tick >= tick_upper:
        amount0_raw = 0.0
        amount1_raw = liquidity * (sqrt_upper - sqrt_lower)
    else:
        amount0_raw = liquidity * (1 / sqrt_current - 1 / sqrt_upper)
        amount1_raw = liquidity * (sqrt_current - sqrt_lower)

    return amount0_raw, amount1_raw


def split_basis_proportional(total_basis, current_values):
    """Pool-then-split allocation for a same-pool rebalance ambiguity
    (Phase D.3.2a): the combined initial_value_usd of the two departing
    positions is split across the two arriving positions in proportion to
    each arriving position's CURRENT computed USD value — never one
    departing position's basis paired to one specific arriving position.

    This is deliberate: array_index pairing for a same-pool collision is
    NOT verifiable (see maxfi_matching.py's same-pool ambiguity pass) — no
    signal distinguishes which departing position became which arriving
    one. Pairing basis 1:1 would silently encode a guess about that
    pairing. Splitting the pooled total by current value instead makes no
    claim about which departing position became which arriving one, and
    preserves the group's AGGREGATE unrealized P/L exactly (sum of
    arriving current values minus the pooled departing basis), even
    though the resulting PER-POSITION P/L split is itself an
    approximation.

    total_basis: pooled initial_value_usd of the two departing positions.
    current_values: exactly 2 floats, each arriving position's current
    computed USD value, in a fixed order — the two returned allocations
    are in that same order.

    Returns a list of 2 floats, each rounded to 2 decimal places, summing
    EXACTLY to round(total_basis, 2). Computed in integer cents
    internally (never via independent per-side rounding) specifically so
    the sum can't drift from the total by a floating-point or rounding
    residual — see tests/test_maxfi_math.py for a case where independently
    rounding each side's share would miss the total by a cent.

    The one arrangement decision this makes: the position with the
    SMALLER current value gets its cents share computed directly (rounded
    to the nearest cent); the position with the LARGER current value gets
    whatever's left after that (total_cents - smaller_cents). Any single
    cent of rounding adjustment is therefore always absorbed by the
    larger-value position, never split independently between the two.

    Raises ValueError (never guesses) if: total_basis is None;
    current_values does not have exactly 2 entries; either current value
    is None or negative; or the two current values sum to zero (no valid
    ratio to split by).
    """
    if total_basis is None:
        raise ValueError("split_basis_proportional: total_basis must not be None")
    if len(current_values) != 2:
        raise ValueError(
            f"split_basis_proportional: current_values must have exactly 2 "
            f"entries, got {len(current_values)}"
        )
    v0, v1 = current_values
    if v0 is None or v1 is None:
        raise ValueError("split_basis_proportional: current_values must not contain None")
    if v0 < 0 or v1 < 0:
        raise ValueError("split_basis_proportional: current_values must not be negative")
    if v0 + v1 == 0:
        raise ValueError(
            "split_basis_proportional: current_values sum to zero - no valid ratio to split by"
        )

    total_cents = round(total_basis * 100)
    if v0 <= v1:
        smaller_idx, larger_idx, smaller_v = 0, 1, v0
    else:
        smaller_idx, larger_idx, smaller_v = 1, 0, v1

    smaller_cents = round(total_cents * (smaller_v / (v0 + v1)))
    larger_cents = total_cents - smaller_cents

    result = [None, None]
    result[smaller_idx] = smaller_cents / 100
    result[larger_idx] = larger_cents / 100
    return result


def allocate_proportional(total, values):
    """N-way cents-exact proportional allocator (Phase D.3.3) — a
    generalization of split_basis_proportional (above) to any list length
    >= 1, for allocating a claimed-fees ancestor's total down across
    however many arriving positions its lineage group actually has (a
    split group is not always 2-arriving; see maxfi_position_lineage).

    Does NOT replace or call split_basis_proportional — that function
    stays exactly as-is (money-path code, separately tested). This
    mirrors its algorithm instead: work in integer cents, give every
    value its proportional share rounded to the nearest cent, and let
    the LARGEST value absorb whatever cent(s) are left over so the sum
    can never drift from round(total, 2) by a rounding residual. At
    length 2, this must produce IDENTICAL output to
    split_basis_proportional for every non-raising input — see the
    equivalence test in tests/test_maxfi_claims_allocation.py.

    total: the pooled amount to allocate. Must be >= 0.
    values: a list of length >= 1, each a non-negative float — the same
    ordering signal split_basis_proportional's current_values uses (e.g.
    each arriving position's current USD value). Not mutated.

    Returns a list of floats, same length and order as `values`, each
    rounded to 2 decimal places, summing EXACTLY to round(total, 2).

    Special cases:
    - len(values) == 1: returns [round(total, 2)] — nothing to allocate
      a ratio against.
    - total == 0: every share is 0.0.
    - sum(values) == 0 (only reachable when every value is 0, since
      negative values are rejected below): there is no ratio to split
      by, so — UNLIKE split_basis_proportional, which raises ValueError
      on exactly this condition — this function spreads `total` as
      evenly as possible in integer cents, with any leftover cent(s)
      going to index 0. This is a deliberate widening for the claims
      path, not a bug fix: a claimed-fees allocation must never lose
      money to an exception just because every arriving position in a
      group happened to be priced at zero when the split occurred.

    Tie-break for "the largest value": scanned left to right, ties keep
    the HIGHEST index (a later equal value replaces the current pick).
    This is deterministic, not symmetric, and is chosen specifically so
    that n=2 matches split_basis_proportional's own tie rule exactly —
    that function's `v0 <= v1` test means an exact tie always sends the
    remainder to index 1, i.e. always prefers the higher index as
    "larger". Generalizing "last index seen with the running-maximum
    value" to n values reduces to that same rule at n=2. When every
    value is 0 (the zero-sum branch above), there is no largest value to
    apply this rule to, so that branch uses index 0 for the leftover
    remainder instead — a different, explicitly separate tie-break for a
    condition split_basis_proportional never reaches at all.

    Raises ValueError (never guesses) if: total is None; total is
    negative; values is empty; any value is None; any value is negative.
    """
    if total is None:
        raise ValueError("allocate_proportional: total must not be None")
    if total < 0:
        raise ValueError("allocate_proportional: total must not be negative")
    if not values:
        raise ValueError("allocate_proportional: values must not be empty")
    if any(v is None for v in values):
        raise ValueError("allocate_proportional: values must not contain None")
    if any(v < 0 for v in values):
        raise ValueError("allocate_proportional: values must not be negative")

    total_cents = round(total * 100)
    n = len(values)

    if n == 1:
        return [total_cents / 100]

    values_sum = sum(values)
    if values_sum == 0:
        base_cents = total_cents // n
        remainder = total_cents - base_cents * n
        cents = [base_cents] * n
        cents[0] += remainder
        return [c / 100 for c in cents]

    largest_idx = 0
    for i in range(1, n):
        if values[i] >= values[largest_idx]:
            largest_idx = i

    cents = [0] * n
    allocated = 0
    for i in range(n):
        if i == largest_idx:
            continue
        share = round(total_cents * (values[i] / values_sum))
        cents[i] = share
        allocated += share
    cents[largest_idx] = total_cents - allocated

    return [c / 100 for c in cents]


def allocate_claims(claims_by_position, lineage_rows):
    """Push each position's own claimed-fee total down through
    maxfi_position_lineage so a descendant of a claimed position inherits
    its share of that ancestor's claims (Phase D.3.3). Pure function — no
    DB, no I/O; the caller loads both arguments with its own bulk queries.

    claims_by_position: {position_id: float} — each position's OWN
    claimed total (already summed across its maxfi_claims rows by the
    caller). Not mutated; returned by value (copied), not by reference.

    lineage_rows: an iterable of row-like objects, each supporting
    row["field_name"] indexing — a plain dict, or a sqlite3.Row from a
    connection opened the way this codebase's get_connection() does
    (row_factory = sqlite3.Row) — carrying at least: id,
    departing_position_id, arriving_position_id, split_group_id,
    arriving_current_value_usd.

    Returns {position_id: float} — each position's EFFECTIVE claimed
    total: its own claims (if any) plus everything allocated down to it
    from every ancestor, at every hop. A position with no lineage stake
    (never an arriving id in any row) and no own claims is ABSENT from
    the result, not mapped to 0.0; any position that IS an arriving id
    somewhere, or has an own-claims entry, always appears as a float
    (0.0 is a legitimate allocated-or-claimed amount, not a placeholder
    for "missing").

    CROSS-PRODUCT DE-DUPLICATION is the whole game here:
    resolve_ambiguous_auto_splits writes one lineage row per (departing,
    arriving) PAIR — the full cross product of a split group's departing
    rows against its arriving rows (four rows for an ordinary
    2-departing/2-arriving split). Naively iterating rows would allocate
    from one departing id to the same arriving id once per duplicate row
    it appears in. This function instead reduces each split_group_id to
    its DISTINCT departing-id set and DISTINCT arriving-id list FIRST,
    and calls allocate_proportional exactly once per (departing id,
    group's arriving list) pair — never once per lineage row. Each
    arriving id's list position is ordered by the lowest lineage `id` at
    which it is seen (computed as a running minimum over all of that
    arriving id's duplicate rows, so the result does not depend on the
    order `lineage_rows` is supplied in), and its
    arriving_current_value_usd is taken from that same lowest-id row.

    ORDERING GUARANTEE THIS RELIES ON: a lineage row's
    arriving_position_id is greater than its departing_position_id
    GLOBALLY — maxfi_positions.id is a true SQLite AUTOINCREMENT column,
    and resolve_ambiguous_auto_splits always UPDATEs the departing rows
    (which already exist) before INSERTing the arriving ones inside the
    same transaction — so the (departing -> arriving) edges form an
    acyclic graph. Split groups are processed in ascending order of
    min(arriving_position_id) within the group, which is a topological
    order for that graph: every group that could feed a share INTO this
    group's departing ids has a lower min(arriving_position_id) and was
    therefore already processed, so a departing id's effective total is
    already final by the time this function reads it to allocate it
    onward. No recursion, no visited set, no depth limit.

    A lineage row whose arriving_position_id is NOT strictly greater than
    its departing_position_id violates that guarantee. It is skipped and
    logged as a warning — never raised, never looped on — and the rest of
    its split group is processed normally.
    """
    if not lineage_rows:
        return dict(claims_by_position)

    groups = {}
    for row in lineage_rows:
        departing_id = row["departing_position_id"]
        arriving_id = row["arriving_position_id"]
        lineage_row_id = row["id"]
        if not (arriving_id > departing_id):
            logger.warning(
                "[maxfi claims] lineage row id=%s violates "
                "arriving_position_id > departing_position_id "
                "(departing=%s, arriving=%s) - skipping",
                lineage_row_id, departing_id, arriving_id,
            )
            continue

        split_group_id = row["split_group_id"]
        group = groups.setdefault(split_group_id, {
            "departing_ids": set(),
            "arriving_first_seen": {},
            "arriving_value": {},
        })
        group["departing_ids"].add(departing_id)

        first_seen = group["arriving_first_seen"].get(arriving_id)
        if first_seen is None or lineage_row_id < first_seen:
            group["arriving_first_seen"][arriving_id] = lineage_row_id
            group["arriving_value"][arriving_id] = row["arriving_current_value_usd"]

    ordered_group_ids = sorted(groups, key=lambda gid: min(groups[gid]["arriving_value"]))

    effective = dict(claims_by_position)

    for split_group_id in ordered_group_ids:
        group = groups[split_group_id]
        arriving_ids = sorted(
            group["arriving_first_seen"], key=lambda aid: group["arriving_first_seen"][aid]
        )
        arriving_values = [group["arriving_value"][aid] for aid in arriving_ids]
        for departing_id in sorted(group["departing_ids"]):
            current_total = effective.get(departing_id, 0.0)
            shares = allocate_proportional(current_total, arriving_values)
            for arriving_id, share in zip(arriving_ids, shares):
                effective[arriving_id] = effective.get(arriving_id, 0.0) + share

    return effective
