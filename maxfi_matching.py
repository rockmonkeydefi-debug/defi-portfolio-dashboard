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
"""


def _same_pool(a, b):
    return (
        a["token0_address"].lower() == b["token0_address"].lower()
        and a["token1_address"].lower() == b["token1_address"].lower()
        and a["fee_tier"] == b["fee_tier"]
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
