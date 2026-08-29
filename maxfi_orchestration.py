"""MaxFi Phase C — scan-and-persist orchestration.

Combines a live wallet snapshot (maxfi_client.get_wallet_position_snapshot)
with the pure matching heuristic (maxfi_matching.classify_positions) and
writes the result into maxfi_positions (maxfi_schema.py). This is the
first state-writing MaxFi code in this build.

Not wired into any scheduled/automatic path — invoked ONLY via the manual
POST /api/maxfi/scan/<chain>/<wallet> route in web_portfolio.py.
"""

from datetime import datetime, timezone

from maxfi_client import (
    get_wallet_position_snapshot,
    get_vault_deposit_info,
    eth_block_number,
    MaxFiRpcError,
    MaxFiDecodeError,
)
from maxfi_matching import classify_positions
from maxfi_math import split_basis_proportional


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _load_previous_open_positions(db_connection, chain, wallet):
    """Returns (previous, row_id_by_array_index).

    `previous` is shaped exactly as classify_positions() expects.
    `row_id_by_array_index` maps each previous entry's array_index (as it
    stood at the START of this scan, before any reclassification) back to
    its maxfi_positions.id, so writes can target the right row regardless
    of how classify_positions() re-buckets it (e.g. a rebalanced or
    index-drifted entry is still looked up via its OLD array_index).

    Reads rows by column position, not sqlite3.Row/dict access — this
    must work whether the caller's connection has row_factory set or not
    (the orchestration tests use a bare sqlite3.connect(':memory:')).
    """
    rows = db_connection.execute(
        """
        SELECT id, array_index, token_id, pool_address, token0_address,
               token1_address, fee_tier
        FROM maxfi_positions
        WHERE chain = ? AND wallet = ? AND status = 'open'
        """,
        (chain, wallet),
    ).fetchall()

    previous = []
    row_id_by_array_index = {}
    for row_id, array_index, token_id, pool_address, token0_address, token1_address, fee_tier in rows:
        row_id_by_array_index[array_index] = row_id
        previous.append({
            "array_index": array_index,
            "token_id": token_id,
            "pool_address": pool_address,
            "token0_address": token0_address,
            "token1_address": token1_address,
            "fee_tier": fee_tier,
        })
    return previous, row_id_by_array_index


def run_scan_and_persist(db_connection, chain, wallet):
    """Scan `wallet` on `chain`, diff against the last-known open positions
    in maxfi_positions, and persist the result. See maxfi_schema.py for
    table shapes and the Phase C spec for the full write contract.

    Step 1 (fetch the live snapshot) is the ONLY thing that can fail the
    whole scan: any MaxFiRpcError/MaxFiDecodeError there propagates
    unmodified (the caller/route turns it into a 502) and nothing is
    written. A per-position enrichment failure during the OPENED branch
    is handled locally and never aborts the rest of the scan.
    """
    current = get_wallet_position_snapshot(chain, wallet)
    main_block_number = eth_block_number(chain)
    captured_at_utc = _utc_now_iso()

    previous, row_id_by_array_index = _load_previous_open_positions(db_connection, chain, wallet)
    classification = classify_positions(previous, current)

    written = {"matched": 0, "rebalanced": 0, "opened": 0, "closed": 0}
    now = captured_at_utc

    # MATCHED — token_id, array_index (in case compaction drift shifted it
    # even though token_id proved this is still the same position),
    # last_scan_at. array_index is a denormalized, current-value field per
    # the schema design - it must be kept current here exactly as the
    # REBALANCED branch below already does, or it silently goes stale after
    # any compaction event. first_seen_at/_source/_block are the identity
    # anchor and are NEVER touched here, same as REBALANCED.
    for entry in classification["matched"]:
        row_id = row_id_by_array_index[entry["previous"]["array_index"]]
        cur = entry["current"]
        db_connection.execute(
            "UPDATE maxfi_positions SET token_id = ?, array_index = ?, last_scan_at = ? WHERE id = ?",
            (cur["token_id"], cur["array_index"], now, row_id),
        )
        written["matched"] += 1

    # REBALANCED — token_id, array_index (in case it also drifted),
    # last_scan_at. first_seen_at/_source/_block are the identity anchor
    # and are NEVER touched here — they must survive a rebalance exactly
    # as live data already proved they do on-chain.
    for entry in classification["rebalanced"]:
        row_id = row_id_by_array_index[entry["previous"]["array_index"]]
        cur = entry["current"]
        db_connection.execute(
            "UPDATE maxfi_positions SET token_id = ?, array_index = ?, last_scan_at = ? WHERE id = ?",
            (cur["token_id"], cur["array_index"], now, row_id),
        )
        written["rebalanced"] += 1

    # OPENED — insert. Enrichment failure is caught narrowly and falls
    # back rather than aborting the scan (constraint 8): the row is still
    # written, just with an honestly-labeled first_seen_at_source.
    for entry in classification["opened"]:
        cur = entry["current"]
        try:
            info = get_vault_deposit_info(chain, wallet, int(cur["token_id"]))
            first_seen_at = datetime.fromtimestamp(
                info["deposit_timestamp"], tz=timezone.utc
            ).isoformat()
            first_seen_at_source = "chain"
            first_seen_block = info["block_number"]
        except (MaxFiRpcError, MaxFiDecodeError) as e:
            print(
                f"[maxfi] deposit-time enrichment failed for {chain}/{wallet} "
                f"token_id={cur['token_id']}: {e}"
            )
            first_seen_at = now
            first_seen_at_source = "fallback_now"
            first_seen_block = str(main_block_number)

        db_connection.execute(
            """
            INSERT INTO maxfi_positions (
                chain, wallet, token_id, array_index, pool_address,
                token0_address, token1_address, fee_tier, status,
                first_seen_at, first_seen_at_source, first_seen_block,
                last_scan_at, closed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, NULL)
            """,
            (
                chain, wallet, cur["token_id"], cur["array_index"], cur["pool_address"],
                cur["token0_address"], cur["token1_address"], cur["fee_tier"],
                first_seen_at, first_seen_at_source, first_seen_block, now,
            ),
        )
        written["opened"] += 1

    # CLOSED — status + closed_at only. Row is never deleted; historical
    # record stays.
    for entry in classification["closed"]:
        row_id = row_id_by_array_index[entry["previous"]["array_index"]]
        db_connection.execute(
            "UPDATE maxfi_positions SET status = 'closed', closed_at = ? WHERE id = ?",
            (now, row_id),
        )
        written["closed"] += 1

    # AMBIGUOUS — no database write (constraint 9); returned only.

    db_connection.commit()

    return {
        "chain": chain,
        "wallet": wallet,
        "captured_at_utc": captured_at_utc,
        "block_number": str(main_block_number),
        "written": written,
        "ambiguous_flagged": classification["ambiguous"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Phase D.3.2a — ambiguity auto-resolution DECISION layer only. No database
# access, no network calls, no writes anywhere below this line. This module's
# write path above (run_scan_and_persist) is completely untouched by this
# addition - it still never resolves an ambiguous entry, and D.3.1's detection
# logic (maxfi_matching.py) is not modified by this phase at all.
#
# The eventual write path (D.3.2b, NOT built here) will call
# decide_ambiguity_resolution() with real current-value/departing-info
# mappings (sourced from the same pipeline GET /api/maxfi/valuation/<chain>/
# <wallet> already uses - see web_portfolio.py's new /ambiguity-preview route,
# which exercises this same function read-only) and act on an 'auto_split' or
# 'auto_split_no_basis' outcome by opening two new maxfi_positions rows.
# Nothing in this phase inserts, updates, or deletes anything.
# ─────────────────────────────────────────────────────────────────────────────

AMBIGUITY_AUTO_SPLIT_SOURCE = "ambiguity_auto_split"


def decide_ambiguity_resolution(group, current_values_by_token_id, departing_info_by_token_id):
    """Decide what SHOULD happen for one ambiguous group from
    maxfi_matching.group_ambiguous_entries() - reports a decision, writes
    nothing. Pure function: no DB access, no network, no clock read: every
    input it needs is a plain argument.

    group: one structured group dict from group_ambiguous_entries() -
    {"chain", "pool_address", "pool_key", "departing": [{"token_id",
    "array_index"}, ...], "arriving": [...], ...}.

    current_values_by_token_id: {arriving token_id: float|None} - the
    current computed USD value for each arriving position (see
    maxfi_pricing.value_position()'s current_value_usd), or None if a
    price could not be resolved for that position. A token_id absent from
    this mapping is treated identically to an explicit None - pricing
    was not (or could not be) obtained for it either way.

    departing_info_by_token_id: {departing token_id: {"initial_value_usd":
    float|None, "first_seen_at": datetime|None}} - the recorded basis and
    open-date for each departing position, read from maxfi_positions /
    maxfi_initial_value. A token_id absent from this mapping is treated
    identically to {"initial_value_usd": None, "first_seen_at": None}.

    Outcomes, evaluated in this exact order (each is final - only one is
    ever returned):
      'manual_group_shape'  - departing count != 2 or arriving count != 2.
                               Auto-resolution is defined only for a clean
                               2-vs-2 collision; any other shape needs a
                               human, exactly as an AMBIGUOUS entry does
                               today with no auto-resolution layer at all.
      'defer_pricing'        - a current USD value is unavailable (None,
                               including an absent mapping key) for either
                               arriving position, or both available values
                               sum to zero (no valid split ratio). The
                               group stays exactly as ambiguous as it was -
                               a pricing outage is temporary and must never
                               cost a position its basis.
      'auto_split_no_basis'  - either departing position's initial_value_usd
                               `is None` (0.0 is a real, present value and
                               does NOT trigger this branch - see
                               test_maxfi_orchestration.py's dedicated
                               regression test for this exact distinction).
                               Both arriving positions get a null proposed
                               initial value; whichever departing value
                               WAS present (if either) is surfaced via
                               discarded_basis_usd/discarded_basis_token_id
                               so it is reported, never silently dropped.
      'auto_split'           - both departing initial_value_usd values
                               `is not None`. The pooled total is split
                               across the arriving positions in proportion
                               to their current values via
                               maxfi_math.split_basis_proportional() - see
                               that function's docstring for why the split
                               is POOL-then-split rather than a 1:1 pairing.

    For both 'auto_split' outcomes (with or without basis), the result also
    reports inherit_first_seen_at: the earlier of the two departing
    positions' first_seen_at (maxfi_positions.first_seen_at is NOT NULL for
    any row actually read from the table, so both should be present in
    practice; if a caller's mapping is missing one anyway, whichever is
    present is used rather than raising).

    Returns a dict - see the four outcome branches below for the exact
    per-outcome shape. Every outcome includes: outcome, chain,
    pool_address, pool_key, departing (list of {token_id,
    initial_value_usd, first_seen_at}), arriving (list of {token_id,
    current_value_usd, proposed_initial_value_usd}), departing_count,
    arriving_count.
    """
    departing = group.get("departing") or []
    arriving = group.get("arriving") or []
    departing_count = len(departing)
    arriving_count = len(arriving)

    departing_view = [
        {
            "token_id": d["token_id"],
            "initial_value_usd": departing_info_by_token_id.get(
                d["token_id"], {}
            ).get("initial_value_usd"),
            "first_seen_at": departing_info_by_token_id.get(
                d["token_id"], {}
            ).get("first_seen_at"),
        }
        for d in departing
    ]
    arriving_current_values = [
        current_values_by_token_id.get(a["token_id"]) for a in arriving
    ]

    base = {
        "chain": group.get("chain"),
        "pool_address": group.get("pool_address"),
        "pool_key": group.get("pool_key"),
        "departing": departing_view,
        "departing_count": departing_count,
        "arriving_count": arriving_count,
    }

    if departing_count != 2 or arriving_count != 2:
        return {
            **base,
            "outcome": "manual_group_shape",
            "arriving": [
                {
                    "token_id": a["token_id"],
                    "current_value_usd": current_values_by_token_id.get(a["token_id"]),
                    "proposed_initial_value_usd": None,
                }
                for a in arriving
            ],
        }

    missing_current_value_token_ids = [
        arriving[i]["token_id"]
        for i, value in enumerate(arriving_current_values)
        if value is None
    ]
    if missing_current_value_token_ids or sum(v for v in arriving_current_values if v is not None) == 0:
        return {
            **base,
            "outcome": "defer_pricing",
            "missing_current_value_token_ids": missing_current_value_token_ids,
            "arriving": [
                {
                    "token_id": arriving[i]["token_id"],
                    "current_value_usd": arriving_current_values[i],
                    "proposed_initial_value_usd": None,
                }
                for i in range(arriving_count)
            ],
        }

    departing_initial_values = [d["initial_value_usd"] for d in departing_view]
    departing_first_seen_ats = [d["first_seen_at"] for d in departing_view]
    present_first_seen_ats = [t for t in departing_first_seen_ats if t is not None]
    inherit_first_seen_at = min(present_first_seen_ats) if present_first_seen_ats else None

    if any(v is None for v in departing_initial_values):
        present = [
            (departing_view[i]["initial_value_usd"], departing_view[i]["token_id"])
            for i in range(2)
            if departing_view[i]["initial_value_usd"] is not None
        ]
        discarded_basis_usd, discarded_basis_token_id = present[0] if present else (None, None)
        return {
            **base,
            "outcome": "auto_split_no_basis",
            "discarded_basis_usd": discarded_basis_usd,
            "discarded_basis_token_id": discarded_basis_token_id,
            "inherit_first_seen_at": inherit_first_seen_at,
            "source": AMBIGUITY_AUTO_SPLIT_SOURCE,
            "arriving": [
                {
                    "token_id": arriving[i]["token_id"],
                    "current_value_usd": arriving_current_values[i],
                    "proposed_initial_value_usd": None,
                }
                for i in range(2)
            ],
        }

    total_basis = departing_initial_values[0] + departing_initial_values[1]
    split = split_basis_proportional(total_basis, arriving_current_values)
    return {
        **base,
        "outcome": "auto_split",
        "inherit_first_seen_at": inherit_first_seen_at,
        "source": AMBIGUITY_AUTO_SPLIT_SOURCE,
        "arriving": [
            {
                "token_id": arriving[i]["token_id"],
                "current_value_usd": arriving_current_values[i],
                "proposed_initial_value_usd": split[i],
            }
            for i in range(2)
        ],
    }
