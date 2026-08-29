"""MaxFi position identity matching heuristic — pure, network-free.

Background: live verification proved token_id is NOT durable on Robinhood
Chain (auto-rebalance burns the old Uniswap NFT and mints a new one; 4 of 20
positions re-minted within an 8-hour window). array_index (a position's slot
in lens.getUserPositions()'s returned array) has held stable through every
observed rebalance, but its behavior under a position-COUNT change (a close
or a new open) is untested — no such event has occurred in the observation
window yet.

This module combines array_index, token_id, and pool identity
(token0_address + token1_address + fee_tier) to classify each position
across two scans (a "previous" snapshot and a "current" one), with an
explicit "ambiguous" fallback whenever the signals disagree rather than a
silent guess. It takes two plain lists of dicts and returns a classification
dict — no network calls, no imports of maxfi_client or web_portfolio, so
it's fully testable with zero network egress.

Position dict shape (both snapshots): {"array_index": int, "token_id": str,
"pool_address": str, "token0_address": str, "token1_address": str,
"fee_tier": int}.

Classification rules, in priority order per current-scan entry:
  a) MATCHED: same array_index AND same token_id present in previous.
  b) REBALANCED: same array_index present in previous, token_id differs,
     AND (token0_address, token1_address, fee_tier) identical.
  c) AMBIGUOUS (index reused, pool changed): same array_index present in
     previous, token_id differs, AND the pool differs.
  d) OPENED: current array_index has no corresponding entry in previous.

CLOSED is determined separately: any previous position whose token_id does
not appear anywhere in current AND whose old array_index in current now
holds a different pool (i.e. wasn't claimed by rule b).

Array-index drift under a position-count change (rule (c)'s untested case)
is handled by one deliberate addition beyond the four rules above: before
treating a same-index token_id change as a fresh rebalance/ambiguous slot,
we check whether that exact token_id was ALREADY a known position elsewhere
in `previous` (i.e. it didn't rebalance at all — it's the same NFT, just
sitting at a different array_index because something else in the array
changed count). Token_id equality is the strongest identity signal we have
(a rebalance always mints a genuinely new token_id), so this is treated as
MATCHED with an explicit `array_index_changed: True` flag rather than left
to fall through to ambiguous/rebalanced against an unrelated slot, or worse,
left unaccounted for and tripping the internal consistency check on every
real close. See the Phase C-prep summary for why this was added — it isn't
one of the four bullet rules verbatim, but is required to satisfy them
faithfully once the array can change length.

Same-pool ambiguity detection (Phase D.3.1): rule (b) validates an
array_index pairing using pool identity alone, which is sound when at most
one previous and one current position share that pool — there's only one
possible pairing, so array_index continuity is trustworthy by elimination.
It is NOT sound when two or more positions in the same pool rebalance
within the same scan window: each pairing is still made independently, one
array_index slot at a time, and pool identity can't tell a correct pairing
from a swapped one between candidates it never compares against each
other. classify_positions() runs a second pass after the main loop that
detects exactly this condition (see the comment above that pass) and
reclassifies the affected entries from REBALANCED to AMBIGUOUS rather than
let a coin-flip array_index pairing decide silently.
"""


def _same_pool(a, b):
    return (
        a["token0_address"].lower() == b["token0_address"].lower()
        and a["token1_address"].lower() == b["token1_address"].lower()
        and a["fee_tier"] == b["fee_tier"]
    )


def _pool_key(position):
    """Same fields _same_pool compares, as a hashable tuple - used to COUNT
    how many rebalance candidates share a pool (see the same-pool ambiguity
    pass in classify_positions), not just pairwise-compare two of them."""
    return (
        position["token0_address"].lower(),
        position["token1_address"].lower(),
        position["fee_tier"],
    )


def _entry(previous_pos, current_pos, reason=None, array_index_changed=False):
    e = {
        "array_index": (current_pos or previous_pos)["array_index"],
        "previous": previous_pos,
        "current": current_pos,
    }
    if array_index_changed:
        e["array_index_changed"] = True
    if reason:
        e["reason"] = reason
    return e


def _index_previous(previous):
    by_index = {}
    for p in previous:
        idx = p["array_index"]
        if idx in by_index:
            raise ValueError(
                f"malformed previous snapshot: duplicate array_index {idx}"
            )
        by_index[idx] = p
    return by_index


def _index_current(current):
    by_index = {}
    for c in current:
        idx = c["array_index"]
        if idx in by_index:
            raise ValueError(
                f"malformed current snapshot: duplicate array_index {idx}"
            )
        by_index[idx] = c
    return by_index


def _assert_all_previous_accounted_for(previous, accounted_indices):
    """Every previous entry must land in exactly one output bucket. Raises
    ValueError naming the unaccounted array_index(es) rather than letting a
    rule-set bug silently drop a position from the classification."""
    missing = [p["array_index"] for p in previous if p["array_index"] not in accounted_indices]
    if missing:
        raise ValueError(
            f"internal consistency check failed: {len(missing)} previous "
            f"position(s) not accounted for in any output bucket: {sorted(missing)}"
        )


def classify_positions(previous, current):
    """Classify `current` positions against a `previous` snapshot.

    previous, current: list of position dicts (see module docstring for
    shape). Either may be None or empty — None is treated as "no previous
    state available" (every current entry becomes "opened").

    Returns:
      {
        "matched": [...],
        "rebalanced": [...],
        "closed": [...],
        "opened": [...],
        "ambiguous": [...],
      }
    Every entry carries {"array_index", "previous", "current", ...} — the
    full position dict on both sides (None on whichever side doesn't
    apply), plus a "reason" string for every ambiguous entry and an
    "array_index_changed" flag when a matched position's slot moved.
    """
    previous = list(previous) if previous else []
    current = list(current) if current else []

    previous_by_index = _index_previous(previous)
    current_by_index = _index_current(current)
    previous_by_token = {p["token_id"]: p for p in previous}
    current_token_ids = {c["token_id"] for c in current}

    matched, rebalanced, ambiguous, opened = [], [], [], []
    accounted_previous_indices = set()

    for idx in sorted(current_by_index):
        cur = current_by_index[idx]
        prev_at_idx = previous_by_index.get(idx)

        # Rule (a): same array_index, same token_id.
        if prev_at_idx is not None and prev_at_idx["token_id"] == cur["token_id"]:
            matched.append(_entry(prev_at_idx, cur))
            accounted_previous_indices.add(idx)
            continue

        # Array-index drift check (see module docstring): this exact
        # token_id already existed in `previous`, just at a different
        # index — not a rebalance (token_id is unchanged), not a fresh
        # index-reuse ambiguity (the token_id isn't new).
        prev_elsewhere = previous_by_token.get(cur["token_id"])
        if prev_elsewhere is not None and prev_elsewhere["array_index"] != idx:
            matched.append(_entry(prev_elsewhere, cur, array_index_changed=True))
            accounted_previous_indices.add(prev_elsewhere["array_index"])
            continue

        # Rule (d): no previous entry at this index at all.
        if prev_at_idx is None:
            opened.append(_entry(None, cur))
            continue

        # Rules (b)/(c): same index, genuinely different (non-drifted) token_id.
        accounted_previous_indices.add(idx)
        if _same_pool(prev_at_idx, cur):
            rebalanced.append(_entry(prev_at_idx, cur))
        else:
            ambiguous.append(_entry(
                prev_at_idx, cur,
                reason="array_index reused with different pool - possible close+open, not a rebalance",
            ))

    # ── Same-pool ambiguity detection (Phase D.3.1) ──────────────────────
    #
    # The loop above validates each array_index pairing using pool identity
    # alone (_same_pool: token0/token1/fee_tier). That's sufficient when at
    # most one previous position and one current position share a given
    # pool — there is only one possible pairing, so array_index continuity
    # is trustworthy by elimination. It breaks down the moment TWO OR MORE
    # positions in the SAME pool rebalance within the same scan window:
    # each was paired above independently, one array_index slot at a time,
    # and _same_pool never compares one candidate pairing against another
    # — it has no way to know a second, equally plausible pairing exists.
    # The result is a CONFIDENT "rebalanced" classification for every one
    # of them that may silently have the wrong old position linked to the
    # wrong new one. No signal available anywhere in this codebase — on
    # chain or otherwise — distinguishes which specific old position
    # became which specific new one when several share a pool concurrently
    # (see the Phase D.3 matching diagnostic), so the honest answer is to
    # surface this as ambiguous rather than let array_index alone decide
    # silently.
    #
    # Deliberately narrow: this counts candidates only among entries
    # already provisionally rebalanced above (not the raw previous/current
    # snapshots), which is exactly the "previous entries not matched via
    # rule (a)/(b) [drift]" and "current entries classified rebalanced"
    # populations this pass needs — a previous entry that matched exactly
    # or drifted is already unambiguous and correctly excluded, and a
    # previous entry that closed (no surviving current counterpart at all)
    # is not a candidate for having become a current pool occupant, so it
    # correctly doesn't inflate the count either. Because each rebalanced
    # entry pairs exactly one previous position with one current position
    # of that same pool, the previous-side and current-side candidate
    # counts for a given pool are identical by construction here, so one
    # count per pool suffices for both halves of the check. Only pools
    # where that count is > 1 (i.e. more than one rebalance candidate on
    # BOTH sides) are reclassified — a pool with multiple previous
    # candidates but only one surviving current one (the rest closed) has
    # just one possible pairing left by elimination and stays rebalanced;
    # widening this to "any pool that ever had multiple positions" is out
    # of scope for this pass.
    rebalanced_pool_counts = {}
    for entry in rebalanced:
        pool_key = _pool_key(entry["previous"])
        rebalanced_pool_counts[pool_key] = rebalanced_pool_counts.get(pool_key, 0) + 1

    still_rebalanced = []
    for entry in rebalanced:
        pool_key = _pool_key(entry["previous"])
        if rebalanced_pool_counts[pool_key] > 1:
            ambiguous.append(_entry(
                entry["previous"], entry["current"],
                reason=(
                    "multiple concurrent positions in same pool - "
                    "array_index pairing not verifiable"
                ),
            ))
        else:
            still_rebalanced.append(entry)
    rebalanced = still_rebalanced

    closed = []
    for prev in previous:
        idx = prev["array_index"]
        if idx in accounted_previous_indices:
            continue
        if prev["token_id"] not in current_token_ids:
            closed.append(_entry(prev, None))
            accounted_previous_indices.add(idx)
        else:
            # Defensive fallback: token_id survives in current but wasn't
            # resolved by the drift check above. Shouldn't happen (every
            # current entry is visited in the loop above and the drift
            # check covers exactly this case), but never silently drop a
            # previous entry - flag it rather than let the consistency
            # check below fail with no explanation.
            new_idx = next(
                c["array_index"] for c in current if c["token_id"] == prev["token_id"]
            )
            ambiguous.append(_entry(
                prev, current_by_index[new_idx],
                reason=(
                    f"token_id persisted in current at array_index {new_idx} "
                    f"(was {idx} in previous) but was not resolved as a match "
                    f"by the array-index drift check - investigate"
                ),
            ))
            accounted_previous_indices.add(idx)

    _assert_all_previous_accounted_for(previous, accounted_previous_indices)

    return {
        "matched": matched,
        "rebalanced": rebalanced,
        "closed": closed,
        "opened": opened,
        "ambiguous": ambiguous,
    }


def summarize(classification):
    """Counts only, e.g. {"matched": 16, "rebalanced": 3, "closed": 0,
    "opened": 0, "ambiguous": 1} - for a quick-glance response field."""
    return {key: len(entries) for key, entries in classification.items()}


def group_ambiguous_entries(ambiguous_entries, chain=None):
    """Group classify_positions()'s flat "ambiguous" list into per-pool
    collision groups (Phase D.3.2a).

    classify_positions() itself is UNCHANGED by this — this is a separate,
    read-only transformation applied to its output afterward, so a
    decision layer (see maxfi_orchestration.py) can reason about "how many
    departing and arriving positions collided in this pool" instead of one
    flat, seemingly-unrelated entry per array_index. The flat list this
    reads is untouched; nothing here mutates classify_positions()'s return
    value or changes which entries end up ambiguous.

    Grouping key is (chain, pool identity), where pool identity is the
    same (token0_address, token1_address, fee_tier) tuple _pool_key()
    already uses elsewhere in this file — not the raw pool_address string.
    The two are equivalent for any real collision (a Uniswap V3 pool
    address is deterministically derived from that exact tuple via the
    factory contract, which is exactly why _same_pool()/_pool_key() key on
    it instead of the address), but token0/token1/fee_tier is this file's
    own established pool-identity convention (Phase D.3.1), so grouping
    is kept consistent with it rather than introducing a second, parallel
    notion of "same pool" based on the address string.

    chain: optional chain identifier attached to every group. Position
    dicts carry no chain field (classify_positions() is chain-agnostic —
    see module docstring), so this is a plain pass-through argument, never
    computed, fetched, or defaulted from anything else here.

    Every ambiguous entry lands in exactly one group — an entry that is
    the only one sharing its pool becomes its own single-entry group (the
    "array_index reused with different pool" rule (c) always produces
    exactly one departing + one arriving position and is never merged
    with anything else), so nothing is ever silently dropped. An entry
    whose "previous" or "current" is None (not producible by
    classify_positions() today, but never assumed impossible) simply
    contributes nothing to that side of its group rather than raising.

    Returns a list of dicts, in first-seen order:
      {
        "chain": chain,
        "pool_key": (token0_address_lower, token1_address_lower, fee_tier),
        "pool_address": str | None,      # from whichever side had one
        "departing": [{"token_id": str, "array_index": int}, ...],
        "arriving": [{"token_id": str, "array_index": int}, ...],
        "array_indices": [int, ...],     # one per constituent entry
        "reasons": [str | None, ...],    # original reason strings, verbatim,
                                          # one per constituent entry, in order
      }
    """
    groups_by_key = {}
    order = []

    for entry in ambiguous_entries:
        previous_pos = entry.get("previous")
        current_pos = entry.get("current")
        pool_source = previous_pos if previous_pos is not None else current_pos

        if pool_source is None:
            # Defensive only — classify_positions() never produces an
            # ambiguous entry with both sides None today. Group it alone
            # under a key that can't collide with any real pool rather
            # than raising or silently dropping it.
            pool_key = ("__no_pool_data__", entry.get("array_index"))
            pool_address = None
        else:
            pool_key = _pool_key(pool_source)
            pool_address = pool_source.get("pool_address")

        group_key = (chain, pool_key)
        if group_key not in groups_by_key:
            groups_by_key[group_key] = {
                "chain": chain,
                "pool_key": pool_key,
                "pool_address": pool_address,
                "departing": [],
                "arriving": [],
                "array_indices": [],
                "reasons": [],
            }
            order.append(group_key)

        group = groups_by_key[group_key]
        if previous_pos is not None:
            group["departing"].append({
                "token_id": previous_pos["token_id"],
                "array_index": previous_pos["array_index"],
            })
        if current_pos is not None:
            group["arriving"].append({
                "token_id": current_pos["token_id"],
                "array_index": current_pos["array_index"],
            })
        group["array_indices"].append(entry.get("array_index"))
        group["reasons"].append(entry.get("reason"))

    return [groups_by_key[key] for key in order]
