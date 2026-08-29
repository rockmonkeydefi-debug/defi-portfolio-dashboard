"""MaxFi Phase C — scan-and-persist orchestration.

Combines a live wallet snapshot (maxfi_client.get_wallet_position_snapshot)
with the pure matching heuristic (maxfi_matching.classify_positions) and
writes the result into maxfi_positions (maxfi_schema.py). This is the
first state-writing MaxFi code in this build.

Not wired into any scheduled/automatic path — invoked ONLY via the manual
POST /api/maxfi/scan/<chain>/<wallet> route in web_portfolio.py.
"""

import json
import logging
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

# Phase D.3.2b: first logging usage in this module (previously a single bare
# print() in the OPENED branch below, left untouched - unrelated to this
# phase). This module now contains the only unattended money-writing path
# in MaxFi and has a prior history of silent failure paths, so its new code
# follows web_portfolio.py's existing logging.getLogger(__name__) convention
# rather than extending the bare-print idiom further.
logger = logging.getLogger(__name__)


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
        # Phase D.3.2b: the raw live snapshot this scan already fetched, so
        # a caller resolving ambiguous groups afterward (see
        # resolve_ambiguous_auto_splits below) can look up an arriving
        # position's pool_address/token0_address/token1_address/fee_tier
        # (group_ambiguous_entries()'s "arriving" entries carry only
        # token_id and array_index) WITHOUT a second on-chain fetch.
        # Additive - every existing caller that only reads the keys above
        # is unaffected.
        "snapshot": current,
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


# ─────────────────────────────────────────────────────────────────────────────
# Phase D.3.2b — the auto-split WRITE path. Everything above this line
# (decide_ambiguity_resolution and run_scan_and_persist) is unchanged in
# behavior except run_scan_and_persist's return dict gaining the additive
# "snapshot" key above. D.3.1 detection (maxfi_matching.py) is not modified
# by this phase at all.
#
# This is a SEPARATE post-scan function, not inline in run_scan_and_persist,
# per the approved design: it needs current USD values from
# web_portfolio._maxfi_resolve_current_value_usd, and this module importing
# web_portfolio would be circular; and run_scan_and_persist buffers all four
# of its loops into one implicit transaction committed once at the end, so a
# commit() placed inside it would flush unrelated scan writes early instead
# of isolating the split. The route (web_portfolio.api_maxfi_scan) calls
# this AFTER run_scan_and_persist has returned and its own transaction has
# committed. This function opens and owns an entirely separate transaction.
# A crash between the two transactions is harmless: the group is simply
# still ambiguous and is retried on the next scan.
# ─────────────────────────────────────────────────────────────────────────────

# first_seen_at_source for an arriving row opened by the auto-split path -
# distinct from the OPENED branch's 'chain'/'fallback_now' above, since this
# timestamp was never read from chain for THIS row at all; it's inherited
# from whichever departing position opened earlier (see inherit_first_seen_at).
AMBIGUITY_AUTO_SPLIT_FIRST_SEEN_SOURCE = "ambiguity_auto_split_inherited"


def _normalize_first_seen_at(value):
    """maxfi_positions.first_seen_at is TEXT holding ISO 8601.
    decide_ambiguity_resolution()'s inherit_first_seen_at is a datetime in
    practice (built from real first_seen_at values a caller has already
    parsed via datetime.fromisoformat before passing them in - see that
    function's docstring), but this accepts an already-str value unchanged
    too, rather than assuming one exact caller-supplied type forever."""
    if isinstance(value, str):
        return value
    return value.isoformat()


def resolve_ambiguous_auto_splits(
    db_connection, chain, wallet,
    groups,
    current_values_by_token_id,
    departing_info_by_token_id,
    current_positions_by_token_id,
    schema_status,
    captured_at_utc,
):
    """Act on group_ambiguous_entries() output: for each group, call
    decide_ambiguity_resolution() and, for exactly the 'auto_split' and
    'auto_split_no_basis' outcomes, close the two departing rows and open
    the two arriving rows in one transaction PER GROUP. Writes nothing for
    'manual_group_shape' or 'defer_pricing' - see LOCKED POLICY.

    db_connection: a connection with NO transaction already open (see the
    entry guard below) - this function issues its own BEGIN IMMEDIATE /
    COMMIT / ROLLBACK per group, entirely separate from any transaction
    the caller may have already committed on a DIFFERENT connection.

    chain, wallet: identify the scan this is resolving groups for.

    groups: maxfi_matching.group_ambiguous_entries() output.

    current_values_by_token_id: {arriving token_id: float|None} - see
    decide_ambiguity_resolution()'s own parameter of the same name.

    departing_info_by_token_id: {departing token_id: {"initial_value_usd":
    float|None, "first_seen_at": datetime|None}} - see
    decide_ambiguity_resolution()'s own parameter of the same name.

    current_positions_by_token_id: {token_id: position dict} built from the
    SAME live snapshot run_scan_and_persist already fetched (its return
    dict's "snapshot" key) - REQUIRED because group_ambiguous_entries()'s
    "arriving" entries carry only token_id and array_index, never
    pool_address/token0_address/token1_address/fee_tier, which the new
    maxfi_positions rows need. Never re-fetched from chain here.

    schema_status: the dict ensure_maxfi_tables() returned for this
    request's connection setup. auto-split refuses to run at all unless
    schema_status["unique_index_ready"] is True - see the first guard.

    captured_at_utc: ISO string - the SAME timestamp value the scan itself
    used for last_scan_at, reused here for closed_at/last_scan_at/set_at so
    every row this request touches (scan writes and auto-split writes
    alike) agrees on "when this happened," even though they're two
    separate transactions.

    Returns a summary dict: {"resolved": int, "skipped": [...],
    "deferred": int, "manual": int, "refused": bool, "reason": str|None} -
    "skipped" is a list of {"pool_address", "reason", ...} dicts, one per
    group that reached a guard and stopped short of writing.
    """
    if schema_status.get("unique_index_ready") is not True:
        logger.error(
            "[maxfi auto-split] refusing to run for %s/%s: unique_index_ready "
            "is not True (schema_status=%r) - the open-identity uniqueness "
            "guarantee is not confirmed present, so auto-resolution cannot "
            "safely run",
            chain, wallet, schema_status,
        )
        return {"resolved": 0, "skipped": [], "deferred": 0, "manual": 0,
                "refused": True, "reason": "unique_index_not_ready"}

    if db_connection.in_transaction:
        raise ValueError(
            "resolve_ambiguous_auto_splits: db_connection.in_transaction is "
            "True on entry - caller contract requires a clean connection "
            "(the scan's own transaction, on its own connection, must "
            "already have committed and closed before this is called)"
        )

    summary = {"resolved": 0, "skipped": [], "deferred": 0, "manual": 0,
               "refused": False, "reason": None}

    for group in groups:
        decision = decide_ambiguity_resolution(
            group, current_values_by_token_id, departing_info_by_token_id
        )
        outcome = decision["outcome"]
        pool_address = decision.get("pool_address")

        if outcome == "manual_group_shape":
            summary["manual"] += 1
            continue

        if outcome == "defer_pricing":
            # Expected during a pricing outage (e.g. DexScreener rate
            # limiting under load) - INFO, not a fault. The group stays
            # exactly as ambiguous as it was; nothing is written.
            logger.info(
                "[maxfi auto-split] deferring pool=%s for %s/%s (pricing "
                "unavailable - expected under load): missing=%s",
                pool_address, chain, wallet,
                decision.get("missing_current_value_token_ids"),
            )
            summary["deferred"] += 1
            continue

        # outcome is 'auto_split' or 'auto_split_no_basis' from here on.
        departing_token_ids = [d["token_id"] for d in decision["departing"]]
        arriving_token_ids = [a["token_id"] for a in decision["arriving"]]

        # SECOND GUARD: both arriving token_ids must be currently untracked
        # (no open row already claims them) - makes a repeat run a no-op.
        already_tracked = []
        for tid in arriving_token_ids:
            row = db_connection.execute(
                "SELECT id FROM maxfi_positions WHERE chain = ? AND wallet = ? "
                "AND token_id = ? AND status = 'open'",
                (chain, wallet, str(tid)),
            ).fetchone()
            if row is not None:
                already_tracked.append(tid)
        if already_tracked:
            logger.warning(
                "[maxfi auto-split] skipping pool=%s for %s/%s: arriving "
                "token_id(s) %s already tracked as open",
                pool_address, chain, wallet, already_tracked,
            )
            summary["skipped"].append({
                "pool_address": pool_address,
                "reason": "arriving_already_tracked",
                "token_ids": already_tracked,
            })
            continue

        # THIRD GUARD: both departing token_ids must resolve to exactly one
        # open row each.
        departing_row_ids = {}
        lookup_failed = False
        for tid in departing_token_ids:
            rows = db_connection.execute(
                "SELECT id FROM maxfi_positions WHERE chain = ? AND wallet = ? "
                "AND token_id = ? AND status = 'open'",
                (chain, wallet, str(tid)),
            ).fetchall()
            if len(rows) != 1:
                logger.warning(
                    "[maxfi auto-split] skipping pool=%s for %s/%s: departing "
                    "token_id %s resolved to %d open row(s), expected exactly 1",
                    pool_address, chain, wallet, tid, len(rows),
                )
                lookup_failed = True
                break
            departing_row_ids[tid] = rows[0][0]
        if lookup_failed:
            summary["skipped"].append({
                "pool_address": pool_address,
                "reason": "departing_lookup_failed",
            })
            continue

        # All guards passed - one transaction for this group only, so one
        # group's failure can never abort or partially affect another.
        db_connection.execute("BEGIN IMMEDIATE")
        try:
            for tid in departing_token_ids:
                db_connection.execute(
                    "UPDATE maxfi_positions SET status = 'closed', closed_at = ? WHERE id = ?",
                    (captured_at_utc, departing_row_ids[tid]),
                )

            inherit_first_seen_at = _normalize_first_seen_at(decision["inherit_first_seen_at"])

            notes_payload = {
                "resolution": "ambiguity_auto_split",
                "resolved_at": captured_at_utc,
                "pool_address": pool_address,
                "departing": [
                    {"token_id": d["token_id"], "initial_value_usd": d["initial_value_usd"]}
                    for d in decision["departing"]
                ],
                "arriving": [
                    {
                        "token_id": a["token_id"],
                        "current_value_usd": a["current_value_usd"],
                        "proposed_initial_value_usd": a["proposed_initial_value_usd"],
                    }
                    for a in decision["arriving"]
                ],
                "outcome": outcome,
            }
            if outcome == "auto_split_no_basis":
                # The whole reason this column exists - never omitted when
                # a value is actually being discarded.
                notes_payload["discarded_basis"] = {
                    "initial_value_usd": decision.get("discarded_basis_usd"),
                    "token_id": decision.get("discarded_basis_token_id"),
                }
            notes_json = json.dumps(notes_payload)

            new_position_ids = {}
            for a in decision["arriving"]:
                tid = a["token_id"]
                cur_pos = current_positions_by_token_id[tid]
                cursor = db_connection.execute(
                    """
                    INSERT INTO maxfi_positions (
                        chain, wallet, token_id, array_index, pool_address,
                        token0_address, token1_address, fee_tier, status,
                        first_seen_at, first_seen_at_source, first_seen_block,
                        last_scan_at, closed_at, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, NULL, ?, NULL, ?)
                    """,
                    (
                        chain, wallet, tid, cur_pos["array_index"], cur_pos["pool_address"],
                        cur_pos["token0_address"], cur_pos["token1_address"], cur_pos["fee_tier"],
                        inherit_first_seen_at, AMBIGUITY_AUTO_SPLIT_FIRST_SEEN_SOURCE,
                        captured_at_utc, notes_json,
                    ),
                )
                new_position_ids[tid] = cursor.lastrowid

            # maxfi_positions rows are inserted before maxfi_initial_value
            # rows unconditionally (above) because PRAGMA foreign_keys=ON
            # is live in production - the FK would reject the reverse order.
            if outcome == "auto_split":
                for a in decision["arriving"]:
                    tid = a["token_id"]
                    position_id = new_position_ids[tid]
                    existing = db_connection.execute(
                        "SELECT source FROM maxfi_initial_value WHERE position_id = ?",
                        (position_id,),
                    ).fetchone()
                    if existing is not None:
                        # Never overwrite - the split value wins ONLY when
                        # nothing else has already claimed this position_id.
                        logger.warning(
                            "[maxfi auto-split] position_id %s (token_id %s) "
                            "already has a maxfi_initial_value row (source=%s) "
                            "- skipping, never overwriting",
                            position_id, tid, existing[0],
                        )
                        continue
                    db_connection.execute(
                        """
                        INSERT INTO maxfi_initial_value
                            (position_id, source, initial_value_usd, set_at, set_by)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (position_id, AMBIGUITY_AUTO_SPLIT_SOURCE,
                         a["proposed_initial_value_usd"], captured_at_utc, "system"),
                    )
            # outcome == 'auto_split_no_basis': no maxfi_initial_value rows
            # at all - both arriving positions start with an unknown basis,
            # same as any other freshly-opened position with no recorded
            # cost, per LOCKED POLICY.

            db_connection.commit()
            summary["resolved"] += 1

            logger.info(
                "[maxfi auto-split] resolved pool=%s for %s/%s: departing=%s "
                "arriving=%s splits=%s outcome=%s",
                pool_address, chain, wallet,
                [(d["token_id"], d["initial_value_usd"]) for d in decision["departing"]],
                [(a["token_id"], a["current_value_usd"]) for a in decision["arriving"]],
                [(a["token_id"], a["proposed_initial_value_usd"]) for a in decision["arriving"]],
                outcome,
            )
        except Exception as e:
            db_connection.rollback()
            logger.error(
                "[maxfi auto-split] FAILED pool=%s for %s/%s departing_token_ids=%s "
                "arriving_token_ids=%s: %s",
                pool_address, chain, wallet, departing_token_ids, arriving_token_ids, e,
            )
            summary["skipped"].append({
                "pool_address": pool_address,
                "reason": f"write_failed: {type(e).__name__}: {e}",
            })
            continue

    return summary
