"""One-shot data repair (Phase D.3.1 fallout) — DELETE THIS MODULE, its route
in web_portfolio.py, and the one import line pulling it in, once the repair
below has actually been executed against production.

Background: the retired same-pool ambiguity rule in maxfi_matching.py (see
commit "MaxFi matching: stop reclassifying same-pool concurrent rebalances as
ambiguous") used to reclassify a same-pool concurrent rebalance as ambiguous.
That fed maxfi_orchestration.resolve_ambiguous_auto_splits, which CLOSED the
two departing rows and INSERTED two replacement rows carrying an inherited
(min-of-pair) first_seen_at and either a pooled/redistributed basis or no
basis at all. Ground truth (owner-confirmed, chain 'robinhood', wallet
0x8fc433ca5117529f199e2ba07cf7edfefb5331ee): every one of the twelve closed
rows below is still an open position — the replacement row IS that position,
just under a re-minted NFT id. The closed rows and their auto-split
replacements are bookkeeping artefacts, not real close/open events.

Repair = MERGE each predecessor (the closed, pre-split row) into its
successor (the open, post-split row) that sits at the predecessor's own
array_index:
  - the successor's basis is replaced by the predecessor's ONLY when the
    successor's own basis is absent or is the auto-split value itself — a
    manual override on the successor is never touched.
  - the successor inherits the predecessor's first_seen_at,
    first_seen_at_source and first_seen_block.
  - the successor's notes column is rewritten to a merge record that nests
    the original auto-split notes payload verbatim, so that payload is never
    lost even though it's no longer the live notes value.
  - the predecessor's maxfi_initial_value row, every maxfi_position_lineage
    row naming it as the departing side, and the predecessor row itself are
    deleted.

The twelve pairs (predecessor_id -> successor_id, predecessor_token_id):
    39 -> 99   927040      WETH/AI          pool 0xc4a21f9d6485fc5893dd4a491b320a83daf4da1d
    40 -> 100  927072      WETH/AI
    45 -> 101  927232      WETH/JUGGERNAUT  pool 0x588b0785f50063260003b7790c42f1ef74902746
    49 -> 102  937985      WETH/JUGGERNAUT
    51 -> 105  938223      WETH/NASDANQ     pool 0xdb1b57704d5122058ff925c1e765c17b21d065ec
    52 -> 106  1026103     WETH/NASDANQ
    42 -> 103  927113      WETH/CLIPPY      pool 0xec6a2662de42da97b338430a0c51dd8774bd8969
    66 -> 104  1007980     WETH/CLIPPY
    83 -> 107  972589      WETH/STONKBROKER pool 0xa9d49caa5e906558dacdc66d563ac78f0c26d4ef
    84 -> 108  1023825     WETH/STONKBROKER
    86 -> 109  972690      WETH/TENDIES     pool 0x237609918f330add285b8bc5f8f2922283d1c4c5
    87 -> 110  1021977     WETH/TENDIES

merge_split_predecessors() is pure over a connection: it never writes unless
execute=True, and never writes at all if ANY pair fails verification — the
whole batch is one all-or-nothing transaction, not resolved pair by pair.
"""

import json


SPLIT_MERGE_CHAIN = "robinhood"
SPLIT_MERGE_WALLET = "0x8fc433ca5117529f199e2ba07cf7edfefb5331ee"

SPLIT_MERGE_PAIRS = (
    {"predecessor_id": 39, "successor_id": 99, "predecessor_token_id": "927040"},
    {"predecessor_id": 40, "successor_id": 100, "predecessor_token_id": "927072"},
    {"predecessor_id": 45, "successor_id": 101, "predecessor_token_id": "927232"},
    {"predecessor_id": 49, "successor_id": 102, "predecessor_token_id": "937985"},
    {"predecessor_id": 51, "successor_id": 105, "predecessor_token_id": "938223"},
    {"predecessor_id": 52, "successor_id": 106, "predecessor_token_id": "1026103"},
    {"predecessor_id": 42, "successor_id": 103, "predecessor_token_id": "927113"},
    {"predecessor_id": 66, "successor_id": 104, "predecessor_token_id": "1007980"},
    {"predecessor_id": 83, "successor_id": 107, "predecessor_token_id": "972589"},
    {"predecessor_id": 84, "successor_id": 108, "predecessor_token_id": "1023825"},
    {"predecessor_id": 86, "successor_id": 109, "predecessor_token_id": "972690"},
    {"predecessor_id": 87, "successor_id": 110, "predecessor_token_id": "1021977"},
)

MERGE_RESOLUTION = "split_merged_into_predecessor_identity"

_POSITION_COLUMNS = (
    "id", "chain", "wallet", "token_id", "array_index", "pool_address",
    "token0_address", "token1_address", "fee_tier", "status",
    "first_seen_at", "first_seen_at_source", "first_seen_block",
    "last_scan_at", "closed_at", "closed_by", "notes",
)


def _fetch_position(conn, position_id):
    row = conn.execute(
        "SELECT " + ", ".join(_POSITION_COLUMNS) + " FROM maxfi_positions WHERE id = ?",
        (position_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(zip(_POSITION_COLUMNS, row))


def _fetch_initial_value(conn, position_id):
    row = conn.execute(
        "SELECT source, initial_value_usd, set_at, set_by FROM maxfi_initial_value "
        "WHERE position_id = ?",
        (position_id,),
    ).fetchone()
    if row is None:
        return None
    source, initial_value_usd, set_at, set_by = row
    return {"source": source, "initial_value_usd": initial_value_usd, "set_at": set_at, "set_by": set_by}


def _count_dependent_rows(conn, table, position_id):
    return conn.execute(
        "SELECT COUNT(*) FROM " + table + " WHERE position_id = ?", (position_id,)
    ).fetchone()[0]


def _lineage_departing_ids_for_arriving(conn, arriving_position_id):
    return [
        r[0] for r in conn.execute(
            "SELECT departing_position_id FROM maxfi_position_lineage WHERE arriving_position_id = ?",
            (arriving_position_id,),
        ).fetchall()
    ]


def _lineage_delete_count(conn, predecessor_id):
    return conn.execute(
        "SELECT COUNT(*) FROM maxfi_position_lineage WHERE departing_position_id = ?",
        (predecessor_id,),
    ).fetchone()[0]


def _basis_action(predecessor_basis, successor_basis):
    """The precedence exactly matches the four documented outcomes: an
    absent successor basis with a predecessor basis present always wins
    first; an existing auto-split successor basis is replaced only when a
    predecessor basis exists to replace it with; any other existing
    successor basis (a manual override, or anything not
    'ambiguity_auto_split') is always kept; everything else — no
    predecessor basis to draw from — is a no-op."""
    if successor_basis is None and predecessor_basis is not None:
        return "insert_from_predecessor"
    if (successor_basis is not None and successor_basis["source"] == "ambiguity_auto_split"
            and predecessor_basis is not None):
        return "replace_auto_split"
    if successor_basis is not None and successor_basis["source"] != "ambiguity_auto_split":
        return "kept_existing"
    return "none"


def merge_split_predecessors(conn, chain, wallet, pairs, merged_at_utc, execute):
    """Verify, plan, and (only if execute=True and verification is clean)
    execute the predecessor-into-successor merge described in the module
    docstring, for exactly the (predecessor_id, successor_id,
    predecessor_token_id) triples in `pairs`.

    Never writes unless execute is True. Never writes at all — not even for
    the pairs that passed — if any pair fails verification: refusals are
    collected across the WHOLE batch before any write is attempted, and a
    single write transaction covers every pair together.

    Returns {"chain", "wallet", "mode": "dry_run"|"executed"|"refused",
    "ok": bool, "refusals": [...], "pairs": [...plan...], "totals": {...},
    "merged_at_utc"}.
    """
    refusals = []
    totals = {
        "pairs": len(pairs),
        "basis_insert_from_predecessor": 0,
        "basis_replace_auto_split": 0,
        "basis_kept_existing": 0,
        "basis_none": 0,
        "maxfi_initial_value_deletes": 0,
        "maxfi_position_lineage_deletes": 0,
        "maxfi_positions_deletes": 0,
    }

    def _refused_result():
        return {
            "chain": chain, "wallet": wallet, "mode": "refused", "ok": False,
            "refusals": refusals, "pairs": [], "totals": totals,
            "merged_at_utc": merged_at_utc,
        }

    # A wrong chain/wallet invalidates every other check below (they all
    # assume the rows they SELECT actually belong to this chain/wallet), so
    # this is one refusal for the whole call, not one per pair, and nothing
    # else is checked.
    if chain != SPLIT_MERGE_CHAIN or wallet.lower() != SPLIT_MERGE_WALLET:
        refusals.append({
            "pair": None,
            "reason": "wrong_chain_or_wallet",
            "detail": (
                f"expected chain={SPLIT_MERGE_CHAIN!r} wallet={SPLIT_MERGE_WALLET!r}, "
                f"got chain={chain!r} wallet={wallet!r}"
            ),
        })
        return _refused_result()

    all_ids = []
    for pair in pairs:
        all_ids.append(pair["predecessor_id"])
        all_ids.append(pair["successor_id"])
    seen_ids = set()
    duplicate_ids = set()
    for one_id in all_ids:
        if one_id in seen_ids:
            duplicate_ids.add(one_id)
        seen_ids.add(one_id)
    if duplicate_ids:
        refusals.append({
            "pair": None,
            "reason": "duplicate_id_across_pairs",
            "detail": f"id(s) used more than once across pairs: {sorted(duplicate_ids)}",
        })

    all_predecessor_ids = {pair["predecessor_id"] for pair in pairs}

    pairs_public = []
    pairs_internal = []

    for pair in pairs:
        predecessor_id = pair["predecessor_id"]
        successor_id = pair["successor_id"]
        predecessor_token_id = pair["predecessor_token_id"]

        predecessor = _fetch_position(conn, predecessor_id)
        successor = _fetch_position(conn, successor_id)

        if predecessor is None:
            refusals.append({
                "pair": pair, "reason": "predecessor_not_found",
                "detail": f"no maxfi_positions row with id {predecessor_id}",
            })
        else:
            if predecessor["status"] != "closed":
                refusals.append({
                    "pair": pair, "reason": "predecessor_not_closed",
                    "detail": (
                        f"predecessor {predecessor_id} status={predecessor['status']!r}, "
                        f"expected 'closed'"
                    ),
                })
            if predecessor["closed_by"] is not None:
                refusals.append({
                    "pair": pair, "reason": "predecessor_closed_by_not_null",
                    "detail": (
                        f"predecessor {predecessor_id} closed_by={predecessor['closed_by']!r}, "
                        f"expected NULL"
                    ),
                })
            if predecessor["chain"] != chain:
                refusals.append({
                    "pair": pair, "reason": "predecessor_chain_mismatch",
                    "detail": f"predecessor {predecessor_id} chain={predecessor['chain']!r}, expected {chain!r}",
                })
            if predecessor["wallet"].lower() != wallet.lower():
                refusals.append({
                    "pair": pair, "reason": "predecessor_wallet_mismatch",
                    "detail": f"predecessor {predecessor_id} wallet={predecessor['wallet']!r}, expected {wallet!r}",
                })
            if predecessor["token_id"] != predecessor_token_id:
                refusals.append({
                    "pair": pair, "reason": "predecessor_token_id_mismatch",
                    "detail": (
                        f"predecessor {predecessor_id} token_id={predecessor['token_id']!r}, "
                        f"expected {predecessor_token_id!r}"
                    ),
                })

        if successor is None:
            refusals.append({
                "pair": pair, "reason": "successor_not_found",
                "detail": f"no maxfi_positions row with id {successor_id}",
            })
        else:
            if successor["status"] != "open":
                refusals.append({
                    "pair": pair, "reason": "successor_not_open",
                    "detail": f"successor {successor_id} status={successor['status']!r}, expected 'open'",
                })
            if successor["chain"] != chain:
                refusals.append({
                    "pair": pair, "reason": "successor_chain_mismatch",
                    "detail": f"successor {successor_id} chain={successor['chain']!r}, expected {chain!r}",
                })
            if successor["wallet"].lower() != wallet.lower():
                refusals.append({
                    "pair": pair, "reason": "successor_wallet_mismatch",
                    "detail": f"successor {successor_id} wallet={successor['wallet']!r}, expected {wallet!r}",
                })

        if predecessor is not None and successor is not None:
            if (predecessor["pool_address"].lower() != successor["pool_address"].lower()
                    or predecessor["token0_address"].lower() != successor["token0_address"].lower()
                    or predecessor["token1_address"].lower() != successor["token1_address"].lower()
                    or predecessor["fee_tier"] != successor["fee_tier"]):
                refusals.append({
                    "pair": pair, "reason": "pool_identity_mismatch",
                    "detail": (
                        f"predecessor {predecessor_id} pool identity does not match "
                        f"successor {successor_id}"
                    ),
                })
            if predecessor["array_index"] != successor["array_index"]:
                refusals.append({
                    "pair": pair, "reason": "array_index_mismatch",
                    "detail": (
                        f"predecessor {predecessor_id} array_index={predecessor['array_index']}, "
                        f"successor {successor_id} array_index={successor['array_index']}"
                    ),
                })

        successor_notes = None
        if successor is not None:
            parsed_notes = None
            try:
                parsed_notes = json.loads(successor["notes"]) if successor["notes"] else None
            except (TypeError, ValueError):
                parsed_notes = None
            if not isinstance(parsed_notes, dict):
                refusals.append({
                    "pair": pair, "reason": "successor_notes_unparseable",
                    "detail": f"successor {successor_id} notes is not valid JSON: {successor['notes']!r}",
                })
            else:
                successor_notes = parsed_notes
                if successor_notes.get("resolution") != "ambiguity_auto_split":
                    refusals.append({
                        "pair": pair, "reason": "successor_notes_wrong_resolution",
                        "detail": (
                            f"successor {successor_id} notes resolution="
                            f"{successor_notes.get('resolution')!r}, expected 'ambiguity_auto_split'"
                        ),
                    })
                departing_token_ids = [
                    d.get("token_id") for d in successor_notes.get("departing", [])
                    if isinstance(d, dict)
                ]
                if predecessor_token_id not in departing_token_ids:
                    refusals.append({
                        "pair": pair, "reason": "predecessor_token_id_not_in_successor_departing",
                        "detail": (
                            f"predecessor token_id {predecessor_token_id!r} not found in successor "
                            f"{successor_id} notes departing list {departing_token_ids!r}"
                        ),
                    })

        if predecessor is not None:
            claims_count = _count_dependent_rows(conn, "maxfi_claims", predecessor_id)
            if claims_count:
                refusals.append({
                    "pair": pair, "reason": "predecessor_has_maxfi_claims_rows",
                    "detail": f"{claims_count} row(s) in maxfi_claims for predecessor {predecessor_id}",
                })
            labels_count = _count_dependent_rows(conn, "maxfi_strategy_labels", predecessor_id)
            if labels_count:
                refusals.append({
                    "pair": pair, "reason": "predecessor_has_maxfi_strategy_labels_rows",
                    "detail": (
                        f"{labels_count} row(s) in maxfi_strategy_labels for predecessor {predecessor_id}"
                    ),
                })
            user_data_count = _count_dependent_rows(conn, "maxfi_position_user_data", predecessor_id)
            if user_data_count:
                refusals.append({
                    "pair": pair, "reason": "predecessor_has_maxfi_position_user_data_rows",
                    "detail": (
                        f"{user_data_count} row(s) in maxfi_position_user_data for "
                        f"predecessor {predecessor_id}"
                    ),
                })

        if successor is not None:
            departing_ids = _lineage_departing_ids_for_arriving(conn, successor_id)
            unknown = sorted({d for d in departing_ids if d not in all_predecessor_ids})
            if unknown:
                refusals.append({
                    "pair": pair, "reason": "lineage_references_unknown_predecessor",
                    "detail": (
                        f"successor {successor_id} has lineage row(s) departing from unknown "
                        f"predecessor id(s) {unknown}"
                    ),
                })

        predecessor_basis = _fetch_initial_value(conn, predecessor_id) if predecessor is not None else None
        successor_basis = _fetch_initial_value(conn, successor_id) if successor is not None else None
        basis_action = _basis_action(predecessor_basis, successor_basis)
        totals["basis_" + basis_action] += 1

        if basis_action in ("insert_from_predecessor", "replace_auto_split"):
            basis_after = dict(predecessor_basis)
        elif basis_action == "kept_existing":
            basis_after = dict(successor_basis)
        else:
            basis_after = dict(successor_basis) if successor_basis is not None else None

        date_after = {
            "first_seen_at": predecessor["first_seen_at"] if predecessor is not None else None,
            "first_seen_at_source": predecessor["first_seen_at_source"] if predecessor is not None else None,
            "first_seen_block": predecessor["first_seen_block"] if predecessor is not None else None,
        }
        date_before = {
            "first_seen_at": successor["first_seen_at"] if successor is not None else None,
            "first_seen_at_source": successor["first_seen_at_source"] if successor is not None else None,
            "first_seen_block": successor["first_seen_block"] if successor is not None else None,
        }

        lineage_delete_count = _lineage_delete_count(conn, predecessor_id) if predecessor is not None else 0
        deletes = {
            "maxfi_initial_value": 1 if predecessor_basis is not None else 0,
            "maxfi_position_lineage": lineage_delete_count,
            "maxfi_positions": 1 if predecessor is not None else 0,
        }
        totals["maxfi_initial_value_deletes"] += deletes["maxfi_initial_value"]
        totals["maxfi_position_lineage_deletes"] += deletes["maxfi_position_lineage"]
        totals["maxfi_positions_deletes"] += deletes["maxfi_positions"]

        pairs_public.append({
            "predecessor_id": predecessor_id,
            "successor_id": successor_id,
            "predecessor_token_id": predecessor_token_id,
            "basis_action": basis_action,
            "basis_before": successor_basis,
            "basis_after": basis_after,
            "date_action": {"before": date_before, "after": date_after},
            "notes_action": "rewrite_to_merge_record",
            "deletes": deletes,
        })
        pairs_internal.append({
            "pair": pair,
            "predecessor": predecessor,
            "successor": successor,
            "predecessor_basis": predecessor_basis,
            "basis_action": basis_action,
            "original_notes": successor_notes,
            "deletes": deletes,
        })

    ok = not refusals
    result = {
        "chain": chain,
        "wallet": wallet,
        "mode": "refused" if not ok else ("executed" if execute else "dry_run"),
        "ok": ok,
        "refusals": refusals,
        "pairs": pairs_public,
        "totals": totals,
        "merged_at_utc": merged_at_utc,
    }

    if not execute or not ok:
        return result

    conn.execute("BEGIN IMMEDIATE")
    try:
        for internal in pairs_internal:
            predecessor = internal["predecessor"]
            successor = internal["successor"]
            predecessor_id = predecessor["id"]
            successor_id = successor["id"]
            basis_action = internal["basis_action"]
            predecessor_basis = internal["predecessor_basis"]
            deletes = internal["deletes"]

            if basis_action == "insert_from_predecessor":
                conn.execute(
                    """
                    INSERT INTO maxfi_initial_value (position_id, source, initial_value_usd, set_at, set_by)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (successor_id, predecessor_basis["source"], predecessor_basis["initial_value_usd"],
                     predecessor_basis["set_at"], predecessor_basis["set_by"]),
                )
            elif basis_action == "replace_auto_split":
                conn.execute(
                    """
                    UPDATE maxfi_initial_value
                    SET source = ?, initial_value_usd = ?, set_at = ?, set_by = ?
                    WHERE position_id = ?
                    """,
                    (predecessor_basis["source"], predecessor_basis["initial_value_usd"],
                     predecessor_basis["set_at"], predecessor_basis["set_by"], successor_id),
                )
            # "kept_existing" / "none": no maxfi_initial_value write for this pair.

            new_notes = json.dumps({
                "resolution": MERGE_RESOLUTION,
                "merged_at": merged_at_utc,
                "predecessor_id": predecessor_id,
                "predecessor_token_id": internal["pair"]["predecessor_token_id"],
                "basis_action": basis_action,
                "original_auto_split": internal["original_notes"],
            })
            conn.execute(
                """
                UPDATE maxfi_positions
                SET first_seen_at = ?, first_seen_at_source = ?, first_seen_block = ?, notes = ?
                WHERE id = ?
                """,
                (predecessor["first_seen_at"], predecessor["first_seen_at_source"],
                 predecessor["first_seen_block"], new_notes, successor_id),
            )

            cursor = conn.execute(
                "DELETE FROM maxfi_initial_value WHERE position_id = ?", (predecessor_id,)
            )
            if cursor.rowcount != deletes["maxfi_initial_value"]:
                raise AssertionError(
                    f"maxfi_initial_value delete rowcount {cursor.rowcount} != planned "
                    f"{deletes['maxfi_initial_value']} for predecessor {predecessor_id}"
                )

            cursor = conn.execute(
                "DELETE FROM maxfi_position_lineage WHERE departing_position_id = ?", (predecessor_id,)
            )
            if cursor.rowcount != deletes["maxfi_position_lineage"]:
                raise AssertionError(
                    f"maxfi_position_lineage delete rowcount {cursor.rowcount} != planned "
                    f"{deletes['maxfi_position_lineage']} for predecessor {predecessor_id}"
                )

            cursor = conn.execute(
                "DELETE FROM maxfi_positions WHERE id = ?", (predecessor_id,)
            )
            if cursor.rowcount != deletes["maxfi_positions"]:
                raise AssertionError(
                    f"maxfi_positions delete rowcount {cursor.rowcount} != planned "
                    f"{deletes['maxfi_positions']} for predecessor {predecessor_id}"
                )

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return result
