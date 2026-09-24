"""MaxFi ledger emissions (staking-reward) compute - C3, PURE: no network,
no sqlite (the maxfi_ledger.py discipline). Design of record:
HANDOFF_maxfi_ledger.md "Emissions design - rulings Q1-Q5 (Sep 24)" plus
the "Emissions step 1 - close-out" findings above it.

Pipeline (driven by web_portfolio._run_ledger_backfill, which owns every
RPC call via maxfi_ledger_ingest.scan_reward_events and every price via
maxfi_ledger_pricing.reward_token_usd_at_block):

  decode_reward_logs()  raw vault / StakingManager logs -> flat events,
                        branching on EMITTER (one StakingRewardsClaimed
                        topic0, two emitters - Q1). A foreign emitter or a
                        topic0 not allowed for that emitter is rejected and
                        counted, never decoded.
  build_claim_keys()    events -> one key per (tx_hash, token_id,
                        reward_token): gross (StakingManager amount if
                        present, else the vault's), fee/treasury/referral
                        sums, net = gross - fee, claim_path, gross_source.
  classify_keys()       lifecycle guard + Transfer check + the ruled status
                        precedence (STATUS_PRECEDENCE below).

Nothing here writes anything. C3 reports; C4 writes.
"""

import datetime

import maxfi_ledger


# ── Event identities (Q1) ────────────────────────────────────────────────
# Same canonical signatures as web_portfolio's _REWARDS_* constants (the
# rewards diagnostic route) - a test pins equality; those constants stay
# where they are until 3b.3b-4.
TOPIC_STAKING_REWARDS_CLAIMED = maxfi_ledger._topic0("StakingRewardsClaimed(uint256,address,address,uint256)")
TOPIC_PERFORMANCE_FEE_COLLECTED = maxfi_ledger._topic0(
    "PerformanceFeeCollected(uint256,address,uint256,uint256,uint256)"
)
TOPIC_POSITION_STAKED = maxfi_ledger._topic0("PositionStaked(uint256,address)")
TOPIC_POSITION_UNSTAKED = maxfi_ledger._topic0("PositionUnstaked(uint256,address)")
# ERC-20 Transfer(address indexed from, address indexed to, uint256 value).
# ERC-721 Transfer shares this topic0 but indexes tokenId too (4 topics) -
# the Transfer check keeps exactly-3-topic logs only.
TOPIC_ERC20_TRANSFER = maxfi_ledger._topic0("Transfer(address,address,uint256)")

VAULT_TOPICS = (TOPIC_STAKING_REWARDS_CLAIMED, TOPIC_PERFORMANCE_FEE_COLLECTED)
STAKING_MANAGER_TOPICS = (TOPIC_STAKING_REWARDS_CLAIMED, TOPIC_POSITION_STAKED, TOPIC_POSITION_UNSTAKED)


# ── Status vocabulary (Q1 + pre-ruling 1, Sep 24) ────────────────────────
STATUS_FEE_WITHOUT_CLAIM = "fee_without_claim"
STATUS_WINDOW_UNKNOWN = "window_unknown"
STATUS_OUT_OF_WINDOW = "out_of_window"
STATUS_GROSS_DISAGREEMENT = "gross_disagreement"
STATUS_VERIFIED = "verified"
STATUS_VERIFIED_AGGREGATE = "verified_aggregate"
STATUS_MISMATCH = "mismatch"
STATUS_NO_PAYOUT = "no_payout"
# Reserved by the design, never assigned by C3 (no real case found).
STATUS_AMBIGUOUS = "ambiguous"

# First match wins, per key.
STATUS_PRECEDENCE = (
    STATUS_FEE_WITHOUT_CLAIM,
    STATUS_WINDOW_UNKNOWN,
    STATUS_OUT_OF_WINDOW,
    STATUS_GROSS_DISAGREEMENT,
    STATUS_VERIFIED,
    STATUS_VERIFIED_AGGREGATE,
    STATUS_MISMATCH,
    STATUS_NO_PAYOUT,
)
ALL_STATUSES = STATUS_PRECEDENCE + (STATUS_AMBIGUOUS,)
# Totals count these only (Q2).
COUNTED_STATUSES = (STATUS_VERIFIED, STATUS_VERIFIED_AGGREGATE)

CLAIM_PATH_MANUAL = "manual"          # vault claim only
CLAIM_PATH_REBALANCE = "rebalance"    # StakingManager claim only (keeper)
CLAIM_PATH_WITHDRAWAL = "withdrawal"  # both emitters


# ── helpers ───────────────────────────────────────────────────────────────

def _addr_from_topic(topic_hex):
    return "0x" + topic_hex[-40:].lower()


def _hex_or_int(value):
    if isinstance(value, int):
        return value
    return int(value, 16)


def iso_to_unix(iso):
    """maxfi_ledger._unix_hex_to_iso()'s own "...Z" format (or any ISO
    string with an explicit offset) -> unix seconds. None passes through."""
    if iso is None:
        return None
    s = iso[:-1] + "+00:00" if iso.endswith("Z") else iso
    return int(datetime.datetime.fromisoformat(s).timestamp())


# ── decode (branch on emitter) ────────────────────────────────────────────

def decode_reward_logs(raw_logs, vault, staking_manager, sample_limit=10):
    """Raw getLogs records (Etherscan shape, i.e. already adapted by
    maxfi_ledger_ingest) -> (events, rejected, decode_failures).

    events: flat dicts, one per accepted log, "kind" one of vault_claim /
    sm_claim / fee / staked / unstaked. A vault StakingRewardsClaimed carries
    owner = topics[2]; a StakingManager StakingRewardsClaimed's owner slot
    is the vault (close-out Q1) and is ignored. PerformanceFeeCollected is
    vault-only. rejected: {"count", "sample"} for a foreign emitter or a
    topic0 not allowed for its emitter. decode_failures: {"count",
    "sample"} for an allowed log whose shape does not decode.
    """
    vault = vault.lower()
    staking_manager = staking_manager.lower()
    events = []
    rejected = {"count": 0, "sample": []}
    failures = {"count": 0, "sample": []}
    for log in raw_logs:
        try:
            norm = maxfi_ledger._normalize_log(log)
        except Exception as e:  # malformed envelope - never aborts the batch
            failures["count"] += 1
            if len(failures["sample"]) < sample_limit:
                failures["sample"].append({"error": f"{type(e).__name__}: {e}"})
            continue
        emitter = norm["contract_address"]
        topics = [t.lower() for t in (norm["topics"] or []) if isinstance(t, str)]
        topic0 = topics[0] if topics else None
        allowed = VAULT_TOPICS if emitter == vault else STAKING_MANAGER_TOPICS if emitter == staking_manager else ()
        if topic0 not in allowed:
            rejected["count"] += 1
            if len(rejected["sample"]) < sample_limit:
                rejected["sample"].append({
                    "tx_hash": norm["tx_hash"], "log_index": norm["log_index"],
                    "emitter": emitter, "topic0": topic0,
                })
            continue
        base = {
            "tx_hash": norm["tx_hash"],
            "block_number": norm["block_number"],
            "block_timestamp": norm["block_timestamp"],
            "log_index": norm["log_index"],
            "emitter": emitter,
        }
        try:
            base["token_id"] = str(int(topics[1], 16))
            words = maxfi_ledger._data_words(norm["data"] or "0x")
            if topic0 == TOPIC_STAKING_REWARDS_CLAIMED:
                base["reward_token"] = _addr_from_topic(topics[3])
                base["amount"] = words[0]
                if emitter == vault:
                    base["kind"] = "vault_claim"
                    base["owner"] = _addr_from_topic(topics[2])
                else:
                    base["kind"] = "sm_claim"
            elif topic0 == TOPIC_PERFORMANCE_FEE_COLLECTED:
                base["kind"] = "fee"
                base["reward_token"] = _addr_from_topic(topics[2])
                base["fee"], base["treasury"], base["referral"] = words[0], words[1], words[2]
            else:
                base["kind"] = "staked" if topic0 == TOPIC_POSITION_STAKED else "unstaked"
                base["staking_contract"] = _addr_from_topic(topics[2])
        except (IndexError, ValueError, TypeError) as e:
            failures["count"] += 1
            if len(failures["sample"]) < sample_limit:
                failures["sample"].append({
                    "tx_hash": norm["tx_hash"], "log_index": norm["log_index"],
                    "emitter": emitter, "topic0": topic0, "error": f"{type(e).__name__}: {e}",
                })
            continue
        events.append(base)
    return events, rejected, failures


def event_counts(events, rejected, decode_failures):
    counts = {"vault_claims": 0, "sm_claims": 0, "fees": 0, "staked": 0, "unstaked": 0}
    field = {"vault_claim": "vault_claims", "sm_claim": "sm_claims", "fee": "fees",
             "staked": "staked", "unstaked": "unstaked"}
    for e in events:
        counts[field[e["kind"]]] += 1
    counts["rejected"] = rejected["count"]
    counts["decode_failed"] = decode_failures["count"]
    return counts


# ── dedup / net (Q1) ──────────────────────────────────────────────────────

def build_claim_keys(events):
    """One dict per (tx_hash, token_id, reward_token) that has a claim or a
    fee. gross = StakingManager amount if present, else the vault amount;
    net = gross - sum(feeAmount). Wei values are ints here (the caller
    stringifies at the report boundary). A fee key with no claim keeps
    gross/net/claim_path/gross_source None (-> fee_without_claim)."""
    grouped = {}
    for e in events:
        if e["kind"] not in ("vault_claim", "sm_claim", "fee"):
            continue
        key = (e["tx_hash"], e["token_id"], e["reward_token"])
        grouped.setdefault(key, []).append(e)

    keys = []
    for (tx_hash, token_id, reward_token), evs in grouped.items():
        vault_claims = [e for e in evs if e["kind"] == "vault_claim"]
        sm_claims = [e for e in evs if e["kind"] == "sm_claim"]
        fees = [e for e in evs if e["kind"] == "fee"]
        gross_vault = sum(e["amount"] for e in vault_claims) if vault_claims else None
        gross_sm = sum(e["amount"] for e in sm_claims) if sm_claims else None
        fee = sum(e["fee"] for e in fees)
        treasury = sum(e["treasury"] for e in fees)
        referral = sum(e["referral"] for e in fees)
        if gross_sm is not None and gross_vault is not None:
            gross, gross_source, claim_path = gross_sm, "both", CLAIM_PATH_WITHDRAWAL
        elif gross_sm is not None:
            gross, gross_source, claim_path = gross_sm, "sm", CLAIM_PATH_REBALANCE
        elif gross_vault is not None:
            gross, gross_source, claim_path = gross_vault, "vault", CLAIM_PATH_MANUAL
        else:
            gross = gross_source = claim_path = None
        anchor_logs = vault_claims + sm_claims or fees
        first = min(anchor_logs, key=lambda e: e["log_index"])
        keys.append({
            "tx_hash": tx_hash,
            "token_id": token_id,
            "reward_token": reward_token,
            "log_index": first["log_index"],
            "block_number": first["block_number"],
            "block_timestamp": first["block_timestamp"],
            "gross": gross,
            "gross_sm": gross_sm,
            "gross_vault": gross_vault,
            "gross_source": gross_source,
            "claim_path": claim_path,
            "fee": fee,
            "treasury": treasury,
            "referral": referral,
            "fee_logs": len(fees),
            "net": gross - fee if gross is not None else None,
            "vault_owner": vault_claims[0]["owner"] if vault_claims else None,
            "gross_disagreement": gross_sm is not None and gross_vault is not None and gross_sm != gross_vault,
        })
    keys.sort(key=lambda k: (k["block_number"], k["log_index"], k["token_id"], k["reward_token"]))
    return keys


# ── lifecycle guard (Q1) ──────────────────────────────────────────────────

def in_lifecycle_window(claim_block, opened_block, rebalanced_block, closed_block):
    """True / False, or None when the window is unknown (no opened_block).
    Inclusive on both ends: opened_block <= claim_block <= end, end =
    rebalanced_block or closed_block or +inf."""
    if opened_block is None:
        return None
    end = rebalanced_block if rebalanced_block is not None else closed_block
    if claim_block < opened_block:
        return False
    return end is None or claim_block <= end


# ── Transfer check (Q1) ───────────────────────────────────────────────────

def _receipt_transfers(receipt_logs, reward_token, vault):
    """Every ERC-20 (exactly 3 topics) Transfer of `reward_token` whose
    sender is `vault`, in log_index order: [{log_index, to, value}]."""
    out = []
    for log in receipt_logs or []:
        topics = [t.lower() for t in (log.get("topics") or []) if isinstance(t, str)]
        if len(topics) != 3 or topics[0] != TOPIC_ERC20_TRANSFER:
            continue
        if (log.get("address") or "").lower() != reward_token:
            continue
        if _addr_from_topic(topics[1]) != vault:
            continue
        words = maxfi_ledger._data_words(log.get("data") or "0x")
        if not words:
            continue
        out.append({
            "log_index": _hex_or_int(log["logIndex"]),
            "to": _addr_from_topic(topics[2]),
            "value": words[0],
        })
    out.sort(key=lambda t: t["log_index"])
    return out


def match_transfers(keys, receipts_by_tx, vault):
    """Per (tx_hash, owner, reward_token) group over keys that carry a
    claim: pass 1 - each key (log_index order) takes the first unused
    candidate whose value == net exactly -> verified; pass 2 - the group's
    remaining keys: no unused candidates -> no_payout; sum(remaining net)
    == sum(unused values) -> verified_aggregate; else mismatch. Candidates
    = vault_transfers filtered to `to == owner`.

    Mutates each key in place: transfer_check (the pre-precedence
    outcome), transfer_log_index/transfer_to/transfer_wei, vault_transfers
    (report-only: every reward-token Transfer out of the vault in the
    receipt), receipt_available."""
    vault = vault.lower()
    groups = {}
    for k in keys:
        receipt_logs = receipts_by_tx.get(k["tx_hash"])
        k["receipt_available"] = receipt_logs is not None
        k["vault_transfers"] = _receipt_transfers(receipt_logs, k["reward_token"], vault)
        k.setdefault("transfer_check", None)
        k.setdefault("transfer_log_index", None)
        k.setdefault("transfer_to", None)
        k.setdefault("transfer_wei", None)
        if k["net"] is None:
            continue
        groups.setdefault((k["tx_hash"], k.get("owner"), k["reward_token"]), []).append(k)

    for (tx_hash, owner, reward_token), group in groups.items():
        group.sort(key=lambda k: k["log_index"])
        candidates = [t for t in group[0]["vault_transfers"] if owner is not None and t["to"] == owner]
        used = set()
        remaining = []
        for k in group:
            hit = next((t for t in candidates if t["log_index"] not in used and t["value"] == k["net"]), None)
            if hit is None:
                remaining.append(k)
                continue
            used.add(hit["log_index"])
            k["transfer_check"] = STATUS_VERIFIED
            k["transfer_log_index"] = hit["log_index"]
            k["transfer_to"] = hit["to"]
            k["transfer_wei"] = hit["value"]
        if not remaining:
            continue
        unused = [t for t in candidates if t["log_index"] not in used]
        if not unused:
            outcome = STATUS_NO_PAYOUT
        elif sum(k["net"] for k in remaining) == sum(t["value"] for t in unused):
            outcome = STATUS_VERIFIED_AGGREGATE
        else:
            outcome = STATUS_MISMATCH
        for k in remaining:
            k["transfer_check"] = outcome
            k["transfer_candidates_unused"] = [dict(t) for t in unused]


# ── status (pre-ruling 1: first match wins) ───────────────────────────────

def final_status(key):
    if key["gross"] is None:
        return STATUS_FEE_WITHOUT_CLAIM
    if key.get("in_window") is None:
        return STATUS_WINDOW_UNKNOWN
    if key["in_window"] is False:
        return STATUS_OUT_OF_WINDOW
    if key["gross_disagreement"]:
        return STATUS_GROSS_DISAGREEMENT
    return key["transfer_check"]


def classify_keys(keys, ledger_by_token, receipts_by_tx, vault, tracked_wallets):
    """Lifecycle guard + owner + Transfer check + final status, in place.
    ledger_by_token: {token_id: {"owner", "opened_block",
    "rebalanced_block", "closed_block"}} from THIS run's derived rows.
    Owner = the vault claim's own owner slot when a vault claim exists,
    else the ledger row's owner (a keeper claim's owner slot is the vault).
    """
    tracked = {w.lower() for w in tracked_wallets}
    for k in keys:
        row = ledger_by_token.get(k["token_id"])
        ledger_owner = (row or {}).get("owner")
        k["ledger_owner"] = ledger_owner
        k["owner"] = k["vault_owner"] or ledger_owner
        k["owner_source"] = "vault_claim" if k["vault_owner"] else ("ledger" if ledger_owner else None)
        k["owner_is_tracked"] = k["owner"] in tracked if k["owner"] else False
        k["opened_block"] = (row or {}).get("opened_block")
        end = None
        if row is not None:
            end = row.get("rebalanced_block") if row.get("rebalanced_block") is not None else row.get("closed_block")
        k["window_end_block"] = end
        k["in_window"] = (
            in_lifecycle_window(k["block_number"], row.get("opened_block"), row.get("rebalanced_block"),
                                row.get("closed_block"))
            if row is not None else None
        )
    match_transfers(keys, receipts_by_tx, vault)
    for k in keys:
        k["verification_status"] = final_status(k)
    return keys


def status_counts(keys):
    counts = {s: 0 for s in ALL_STATUSES}
    for k in keys:
        counts[k["verification_status"]] = counts.get(k["verification_status"], 0) + 1
    return counts
