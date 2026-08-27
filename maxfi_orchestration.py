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
