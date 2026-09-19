"""Pure decode/derive module for the MaxFi vault-event ledger
(HANDOFF_maxfi_ledger.md, Commit 1). No network, no RPC, no sqlite - only
maxfi_math and stdlib, plus web3.Web3.keccak for topic0 constants at
module load (a local hash function, not a network call - same use
web_portfolio.py already makes at ~857/1029).

Event dispatch is by topic0 HASH CONSTANT only, never by event name or a
Blockscout `decoded.method_call` string - two different events can share a
name (see base_harvest_6039568.json: a pool-level `Collect` and an NPM
`Collect` have different topic0s; neither is in this module's tracked
vocabulary and both must decode to None, same as `Burn` and ERC20
`Transfer` in that same fixture).

Tracked vocabulary this commit (8 of the 9 named in the handoff doc):
PositionCreated, PositionWithdrawn, FeesHarvested, SnuggleRebalanced
(vault); ProtocolFeesDistributed, FeesCompounded, FeesHarvestedDirect
(StakingManager); Swap (pool, pricing only).

PoolAdded is explicitly DEFERRED, not decoded this commit: the handoff
doc's own event contract ends `PoolAdded(poolId, pool, token0, token1,
fee, ...)` - the trailing ellipsis means the full field list was not
captured live, so no topic0 can be computed without guessing at a
signature that has no fixture to check it against. decode_log() has no
dispatch entry for it, which is safe (falls through to the same None
every other unrecognized topic0 gets) but is a real gap: nothing in this
commit builds the poolId -> pool/token0/token1 map. Flagged in the
Commit-1 report, not silently worked around.

FeesCompounded and FeesHarvestedDirect (StakingManager) are also decoded
from an INFERRED signature - HANDOFF_maxfi_ledger.md gives their field
NAMES (`tokenId, owner, amount0, amount1`) but never their Solidity TYPES
or which are indexed. The types used below (uint256 tokenId indexed;
address owner, uint256 amount0, uint256 amount1 in data) mirror the same
field names' types everywhere else in this event family (FeesHarvested's
fees0/fees1, PositionWithdrawn's amount0/amount1, ProtocolFeesDistributed's
tokenId-only-indexed shape) and are marked [Inference] at their topic0
constants below. Neither fixture set contains a FeesCompounded or
FeesHarvestedDirect log, so this inference is untested against a real
event - only against the synthetic scenarios in
tests/test_maxfi_ledger_derive.py.
"""

import json

from web3 import Web3

import maxfi_math

EVENT_TYPES = (
    "PositionCreated",
    "PositionWithdrawn",
    "FeesHarvested",
    "SnuggleRebalanced",
    "ProtocolFeesDistributed",
    "FeesCompounded",
    "FeesHarvestedDirect",
    "Swap",
)


def _topic0(signature):
    h = Web3.keccak(text=signature).hex()
    if not h.startswith("0x"):
        h = "0x" + h
    return h.lower()


TOPIC_POSITION_CREATED = _topic0("PositionCreated(uint256,address,bytes32,int24,int24,uint128,bool)")
TOPIC_POSITION_WITHDRAWN = _topic0("PositionWithdrawn(uint256,address,uint256,uint256)")
TOPIC_FEES_HARVESTED = _topic0("FeesHarvested(uint256,address,uint256,uint256)")
TOPIC_SNUGGLE_REBALANCED = _topic0(
    "SnuggleRebalanced(uint256,uint256,address,int24,int24,uint256,uint256,bool,uint32)"
)
TOPIC_PROTOCOL_FEES_DISTRIBUTED = _topic0("ProtocolFeesDistributed(uint256,uint256,uint256,uint256,uint256)")
TOPIC_FEES_COMPOUNDED = _topic0("FeesCompounded(uint256,address,uint256,uint256)")  # [Inference]
TOPIC_FEES_HARVESTED_DIRECT = _topic0("FeesHarvestedDirect(uint256,address,uint256,uint256)")  # [Inference]
TOPIC_SWAP = _topic0("Swap(address,address,int256,int256,uint160,uint128,int24)")


# ── raw-log normalization: both fixture shapes -------------------------
# Etherscan-shape (base_position_created.json, base_swap_page.json): flat
# dict, hex-string blockNumber/logIndex/timeStamp, "address"/"transactionHash".
# Blockscout-shape (base_harvest_*.json, rh_*.json): "block_number" (int),
# "block_timestamp" (ISO string), "index" (int), "transaction_hash",
# "address" is a dict with "hash". The "decoded" key Blockscout attaches is
# NEVER used for dispatch (constraint 4) - only topics[0] is.

def _normalize_log(log):
    if "blockNumber" in log:
        address = log["address"]
        block_number = int(log["blockNumber"], 16)
        block_timestamp = _unix_hex_to_iso(log["timeStamp"])
        tx_hash = log["transactionHash"]
        log_index = int(log["logIndex"], 16)
    else:
        address = log["address"]["hash"]
        block_number = int(log["block_number"])
        block_timestamp = log["block_timestamp"]
        tx_hash = log["transaction_hash"]
        log_index = int(log["index"])

    return {
        "contract_address": address.lower(),
        "block_number": block_number,
        "block_timestamp": block_timestamp,
        "tx_hash": tx_hash.lower(),
        "log_index": log_index,
        "topics": log["topics"],
        "data": log["data"],
    }


def _unix_hex_to_iso(hex_str):
    import datetime

    ts = int(hex_str, 16)
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _topic_to_int(topic_hex):
    return int(topic_hex, 16)


def _topic_to_address(topic_hex):
    return "0x" + topic_hex[-40:].lower()


def _word_to_address(word_int):
    return "0x" + format(word_int & ((1 << 160) - 1), "040x")


def _data_words(data_hex):
    body = data_hex[2:] if data_hex.startswith("0x") else data_hex
    return [int(body[i:i + 64], 16) for i in range(0, len(body), 64)]


# ── per-event-type decoders ---------------------------------------------
# Each returns (event_type, ledger_fields, decoded_payload).
# ledger_fields carries the columns decode_log() needs beyond the generic
# ones: vault, npm (always None - see module docstring / HANDOFF ruling 9),
# token_id, pool_address.

def _decode_position_created(topics, data, contract_address):
    words = _data_words(data)
    token_id = _topic_to_int(topics[1])
    owner = _topic_to_address(topics[2])
    pool_id = topics[3].lower()
    tick_lower = maxfi_math.to_int24(words[0])
    tick_upper = maxfi_math.to_int24(words[1])
    liquidity = words[2]
    auto_snuggle_enabled = bool(words[3])
    ledger_fields = {
        "vault": contract_address,
        "npm": None,
        "token_id": str(token_id),
        "pool_address": None,
    }
    decoded = {
        "token_id": token_id,
        "owner": owner,
        "pool_id": pool_id,
        "tick_lower": tick_lower,
        "tick_upper": tick_upper,
        "liquidity": liquidity,
        "auto_snuggle_enabled": auto_snuggle_enabled,
    }
    return "PositionCreated", ledger_fields, decoded


def _decode_position_withdrawn(topics, data, contract_address):
    words = _data_words(data)
    token_id = _topic_to_int(topics[1])
    owner = _topic_to_address(topics[2])
    ledger_fields = {
        "vault": contract_address,
        "npm": None,
        "token_id": str(token_id),
        "pool_address": None,
    }
    decoded = {
        "token_id": token_id,
        "owner": owner,
        "amount0": words[0],
        "amount1": words[1],
    }
    return "PositionWithdrawn", ledger_fields, decoded


def _decode_fees_harvested(topics, data, contract_address):
    words = _data_words(data)
    token_id = _topic_to_int(topics[1])
    owner = _topic_to_address(topics[2])
    ledger_fields = {
        "vault": contract_address,
        "npm": None,
        "token_id": str(token_id),
        "pool_address": None,
    }
    decoded = {
        "token_id": token_id,
        "owner": owner,
        "fees0": words[0],
        "fees1": words[1],
    }
    return "FeesHarvested", ledger_fields, decoded


def _decode_snuggle_rebalanced(topics, data, contract_address):
    words = _data_words(data)
    old_token_id = _topic_to_int(topics[1])
    new_token_id = _topic_to_int(topics[2])
    owner = _topic_to_address(topics[3])
    new_tick_lower = maxfi_math.to_int24(words[0])
    new_tick_upper = maxfi_math.to_int24(words[1])
    protocol_fee0 = words[2]
    protocol_fee1 = words[3]
    was_manual = bool(words[4])
    total_rebalances = words[5]
    # ledger key's token_id points at the row this event is filed under by
    # decode_log() when called standalone; derive_all() re-files this same
    # decoded record under BOTH the old and new token_id groups (see its
    # own docstring) since a rebalance event is meaningful to both sides.
    ledger_fields = {
        "vault": contract_address,
        "npm": None,
        "token_id": str(new_token_id),
        "pool_address": None,
    }
    decoded = {
        "old_token_id": old_token_id,
        "new_token_id": new_token_id,
        "owner": owner,
        "new_tick_lower": new_tick_lower,
        "new_tick_upper": new_tick_upper,
        "protocol_fee0": protocol_fee0,
        "protocol_fee1": protocol_fee1,
        "was_manual": was_manual,
        "total_rebalances": total_rebalances,
    }
    return "SnuggleRebalanced", ledger_fields, decoded


def _decode_protocol_fees_distributed(topics, data, contract_address):
    words = _data_words(data)
    token_id = _topic_to_int(topics[1])
    ledger_fields = {
        # vault is None: StakingManager emits this, not the vault. Which
        # vault owns this token_id is a same-tx correlation problem,
        # solved (when possible) in derive_all(), not here.
        "vault": None,
        "npm": None,
        "token_id": str(token_id),
        "pool_address": None,
    }
    decoded = {
        "token_id": token_id,
        "treasury0": words[0],
        "treasury1": words[1],
        "referral0": words[2],
        "referral1": words[3],
    }
    return "ProtocolFeesDistributed", ledger_fields, decoded


def _decode_fees_compounded(topics, data, contract_address):
    words = _data_words(data)
    token_id = _topic_to_int(topics[1])
    owner = _word_to_address(words[0])
    ledger_fields = {
        "vault": None,
        "npm": None,
        "token_id": str(token_id),
        "pool_address": None,
    }
    decoded = {
        "token_id": token_id,
        "owner": owner,
        "amount0": words[1],
        "amount1": words[2],
    }
    return "FeesCompounded", ledger_fields, decoded


def _decode_fees_harvested_direct(topics, data, contract_address):
    words = _data_words(data)
    token_id = _topic_to_int(topics[1])
    owner = _word_to_address(words[0])
    ledger_fields = {
        "vault": None,
        "npm": None,
        "token_id": str(token_id),
        "pool_address": None,
    }
    decoded = {
        "token_id": token_id,
        "owner": owner,
        "amount0": words[1],
        "amount1": words[2],
    }
    return "FeesHarvestedDirect", ledger_fields, decoded


def _decode_swap(topics, data, contract_address):
    words = _data_words(data)
    sender = _topic_to_address(topics[1])
    recipient = _topic_to_address(topics[2])
    amount0 = maxfi_math.to_signed(words[0], 256)
    amount1 = maxfi_math.to_signed(words[1], 256)
    sqrt_price_x96 = words[2]
    liquidity = words[3]
    tick = maxfi_math.to_int24(words[4])
    ledger_fields = {
        "vault": None,
        "npm": None,
        "token_id": None,
        "pool_address": contract_address,
    }
    decoded = {
        "sender": sender,
        "recipient": recipient,
        "amount0": amount0,
        "amount1": amount1,
        "sqrt_price_x96": sqrt_price_x96,
        "liquidity": liquidity,
        "tick": tick,
    }
    return "Swap", ledger_fields, decoded


_DECODERS = {
    TOPIC_POSITION_CREATED: _decode_position_created,
    TOPIC_POSITION_WITHDRAWN: _decode_position_withdrawn,
    TOPIC_FEES_HARVESTED: _decode_fees_harvested,
    TOPIC_SNUGGLE_REBALANCED: _decode_snuggle_rebalanced,
    TOPIC_PROTOCOL_FEES_DISTRIBUTED: _decode_protocol_fees_distributed,
    TOPIC_FEES_COMPOUNDED: _decode_fees_compounded,
    TOPIC_FEES_HARVESTED_DIRECT: _decode_fees_harvested_direct,
    TOPIC_SWAP: _decode_swap,
}


def decode_log(log):
    """Decode one raw log (either fixture shape) into a dict matching the
    maxfi_ledger_events row shape (minus `id`, `chain`, `created_at` - the
    caller's concern, not this pure module's). Returns None for any topic0
    not in this module's tracked vocabulary (constraint: dispatch by
    topic0 HASH ONLY, never by event name).
    """
    normalized = _normalize_log(log)
    topics = normalized["topics"]
    if not topics or not topics[0]:
        return None
    topic0 = topics[0].lower()
    decoder = _DECODERS.get(topic0)
    if decoder is None:
        return None

    event_type, ledger_fields, decoded_payload = decoder(topics, normalized["data"], normalized["contract_address"])

    return {
        "contract_address": normalized["contract_address"],
        "vault": ledger_fields["vault"],
        "npm": ledger_fields["npm"],
        "token_id": ledger_fields["token_id"],
        "pool_address": ledger_fields["pool_address"],
        "event_type": event_type,
        "block_number": normalized["block_number"],
        "block_timestamp": normalized["block_timestamp"],
        "tx_hash": normalized["tx_hash"],
        "log_index": normalized["log_index"],
        "topic0": topic0,
        "topics_json": json.dumps([t.lower() if isinstance(t, str) else t for t in topics]),
        "data_hex": normalized["data"].lower(),
        "decoded_json": json.dumps(decoded_payload),
    }


def decode_swap(log, decimals0, decimals1):
    """Decode a Swap log and additionally compute its pool price via the
    ALREADY-EXISTING maxfi_math.sqrt_price_x96_to_price (HANDOFF ruling 3 -
    reused, not reimplemented). Raises ValueError if `log` does not decode
    to a Swap event.

    Returns token1-per-token0 price only. Resolving that to USD for a
    non-stable pair (e.g. WETH/ChumpCoin, RH tokenId 908769) requires a
    second hop through the chain's WETH/USDC pool at the same block -
    NOT implemented this commit (HANDOFF ruling 10). For a pool where
    token1 IS a USD stablecoin (e.g. Base ETH/USDC), the caller may treat
    this price as USD-per-token0 directly.
    """
    record = decode_log(log)
    if record is None or record["event_type"] != "Swap":
        raise ValueError("decode_swap: log does not decode to a Swap event")
    decoded = json.loads(record["decoded_json"])
    price = maxfi_math.sqrt_price_x96_to_price(decoded["sqrt_price_x96"], decimals0, decimals1)
    return {**record, "price_token1_per_token0": price}


def price_at_or_before(swap_logs, target_block):
    """Pure selection over a list of raw Swap logs (any shape decode_log
    accepts) for ONE pool: the decoded Swap record with the greatest
    block_number <= target_block, ties broken by the greatest log_index
    (HANDOFF ruling 10 - a V3 pool's price only moves on Swap, so the most
    recent Swap at-or-before a block IS the price at that block, however
    far back it is). Returns None if no such log exists in the list (every
    log is after target_block, or the list is empty).

    [Unverified] the correct fallback for a pool with ZERO swaps ever (a
    just-`Initialize`d pool) is that Initialize event's own starting
    sqrtPriceX96 - not implemented here. A caller getting None back for a
    real pool needs that fallback, which this commit does not provide.
    """
    candidates = []
    for log in swap_logs:
        record = decode_log(log)
        if record is None or record["event_type"] != "Swap":
            continue
        if record["block_number"] <= target_block:
            candidates.append(record)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["block_number"], r["log_index"]))
    return candidates[-1]


# ── derive: raw decoded events -> per-position ledger rows ---------------

def _tx_net_claim(events, tx_hash, token_id):
    """Net wallet-side fee claim contributed by ONE tx, for ONE token_id.

    Ordinary harvest (no FeesHarvestedDirect in this tx): net = FeesHarvested
    gross minus this tx's ProtocolFeesDistributed treasury+referral - the
    branch fixture-verified against both harvest fixtures (Base tokenId
    6039568, RH tokenId 908769).

    Rebalance-tx branch [Inference, no rebalance-tx fixture exists to
    verify this branch]: when a FeesHarvestedDirect event for this token_id
    is ALSO present in this tx (alongside FeesHarvested + ProtocolFeesDistributed),
    FeesHarvestedDirect's amount is treated as the authoritative net claim
    for this tx instead - the ProtocolFeesDistributed-derived net for the
    same FeesHarvested event is NOT additionally added, to avoid double-
    counting the same underlying fee event once via the harvest+split pair
    and again via the direct-to-wallet event.
    """
    direct = [
        json.loads(e["decoded_json"])
        for e in events
        if e["event_type"] == "FeesHarvestedDirect"
        and e["tx_hash"] == tx_hash
        and json.loads(e["decoded_json"])["token_id"] == token_id
    ]
    if direct:
        amount0 = sum(d["amount0"] for d in direct)
        amount1 = sum(d["amount1"] for d in direct)
        return amount0, amount1

    harvested = [
        json.loads(e["decoded_json"])
        for e in events
        if e["event_type"] == "FeesHarvested"
        and e["tx_hash"] == tx_hash
        and json.loads(e["decoded_json"])["token_id"] == token_id
    ]
    distributed = [
        json.loads(e["decoded_json"])
        for e in events
        if e["event_type"] == "ProtocolFeesDistributed"
        and e["tx_hash"] == tx_hash
        and json.loads(e["decoded_json"])["token_id"] == token_id
    ]
    gross0 = sum(h["fees0"] for h in harvested)
    gross1 = sum(h["fees1"] for h in harvested)
    taken0 = sum(d["treasury0"] + d["referral0"] for d in distributed)
    taken1 = sum(d["treasury1"] + d["referral1"] for d in distributed)
    return gross0 - taken0, gross1 - taken1


def derive_position_ledger(events, ledger_key):
    """Derive one maxfi_ledger_positions row from every decoded event
    belonging to a SINGLE (vault, npm, token_id) lifecycle - the caller
    (derive_all, or a test) has already grouped `events` to just that key
    and supplies it as `ledger_key = (vault, npm, token_id)`.

    `ledger_key` is taken as given rather than re-inferred from `events`:
    a SnuggleRebalanced event's own decoded token_id is always its
    new_token_id (see _decode_snuggle_rebalanced), so a group consisting
    only of that event on its OLD-token_id side has no event whose own
    token_id field matches the group's actual key - inferring the key from
    event contents is order-dependent and wrong for that case. The caller
    already knows the key from grouping, so it is passed in instead of
    guessed.

    computed_at is deliberately NOT produced here (this module does no
    clock access, staying pure/deterministic) - it is None in the return
    value, left for the future write path to fill in immediately before
    INSERT, matching maxfi_ledger_positions.computed_at's NOT NULL
    constraint only at that later write time.

    basis_* columns are always None/left unpopulated this commit (see
    maxfi_schema.py's maxfi_ledger_positions comments and HANDOFF
    constraint 8) - no IncreaseLiquidity decoder or fixture exists yet.
    """
    vault, npm, token_id = ledger_key
    pool_id = None
    owner = None
    opened_at = None
    opened_block = None
    rebalanced_from_token_id = None
    rebalanced_to_token_id = None
    rebalanced_at = None
    rebalanced_block = None
    closed_at = None
    closed_block = None
    exit_amount0_wei = None
    exit_amount1_wei = None
    exit_net_fee0_wei = None
    exit_net_fee1_wei = None
    claimed_gross0 = 0
    claimed_gross1 = 0
    claimed_net0 = 0
    claimed_net1 = 0
    compounded0 = 0
    compounded1 = 0
    seen_gross_tx_token = set()

    for event in events:
        decoded = json.loads(event["decoded_json"])
        if event["event_type"] == "PositionCreated":
            opened_at = event["block_timestamp"]
            opened_block = event["block_number"]
            owner = decoded["owner"]
            pool_id = decoded["pool_id"]
        elif event["event_type"] == "SnuggleRebalanced":
            if str(decoded["old_token_id"]) == token_id:
                rebalanced_to_token_id = str(decoded["new_token_id"])
                rebalanced_at = event["block_timestamp"]
                rebalanced_block = event["block_number"]
            if str(decoded["new_token_id"]) == token_id:
                rebalanced_from_token_id = str(decoded["old_token_id"])
                if opened_at is None:
                    opened_at = event["block_timestamp"]
                    opened_block = event["block_number"]
        elif event["event_type"] == "PositionWithdrawn":
            closed_at = event["block_timestamp"]
            closed_block = event["block_number"]
            exit_amount0_wei = str(decoded["amount0"])
            exit_amount1_wei = str(decoded["amount1"])
            net0, net1 = _tx_net_claim(events, event["tx_hash"], decoded["token_id"])
            exit_net_fee0_wei = str(net0)
            exit_net_fee1_wei = str(net1)
        elif event["event_type"] == "FeesHarvested":
            claimed_gross0 += decoded["fees0"]
            claimed_gross1 += decoded["fees1"]
            key = (event["tx_hash"], decoded["token_id"])
            if key not in seen_gross_tx_token:
                seen_gross_tx_token.add(key)
                net0, net1 = _tx_net_claim(events, event["tx_hash"], decoded["token_id"])
                claimed_net0 += net0
                claimed_net1 += net1
        elif event["event_type"] == "FeesCompounded":
            # Always principal, never fees - HANDOFF's rebalance rule,
            # now event-backed (ruling in the Sep 18 ground-truth section).
            compounded0 += decoded["amount0"]
            compounded1 += decoded["amount1"]

    return {
        "vault": vault,
        "npm": npm,
        "token_id": token_id,
        "pool_id": pool_id,
        "pool_address": None,
        "owner": owner,
        "opened_at": opened_at,
        "opened_block": opened_block,
        "rebalanced_from_token_id": rebalanced_from_token_id,
        "rebalanced_to_token_id": rebalanced_to_token_id,
        "rebalanced_at": rebalanced_at,
        "rebalanced_block": rebalanced_block,
        "closed_at": closed_at,
        "closed_block": closed_block,
        "exit_amount0_wei": exit_amount0_wei,
        "exit_amount1_wei": exit_amount1_wei,
        "exit_net_fee0_wei": exit_net_fee0_wei,
        "exit_net_fee1_wei": exit_net_fee1_wei,
        "exit_price_usd": None,
        "exit_price_source": None,
        "claimed_gross0_wei": str(claimed_gross0),
        "claimed_gross1_wei": str(claimed_gross1),
        "claimed_net0_wei": str(claimed_net0),
        "claimed_net1_wei": str(claimed_net1),
        "compounded0_wei": str(compounded0),
        "compounded1_wei": str(compounded1),
        # basis_* left unpopulated this commit - see docstring.
        "basis_liquidity_wei": None,
        "basis_amount0_wei": None,
        "basis_amount1_wei": None,
        "basis_block": None,
        "basis_at": None,
        "basis_price_usd": None,
        "basis_price_source": None,
        # No maxfi_ledger_events.id exists yet on these pre-insert decode
        # records - populated by the future ingest commit that inserts
        # events first and re-runs derive against the stored rows.
        "source_event_ids": None,
        # Left None by this pure function - see docstring.
        "computed_at": None,
    }


def _ledger_keys_for_event(event):
    """Every (vault, npm, token_id) group this event belongs to. Almost
    always exactly one; a SnuggleRebalanced event belongs to TWO groups
    (the token_id it rebalanced FROM and the one it rebalanced TO), since
    it is meaningful to both the closing old row and the opening new one.
    A StakingManager event (vault=None) with no vault-carrying sibling in
    the same tx anywhere in the input cannot be resolved to a vault at all
    and is dropped - see derive_all()'s docstring.
    """
    decoded = json.loads(event["decoded_json"])
    npm = event.get("npm")
    if event["event_type"] == "SnuggleRebalanced":
        vault = event["vault"]
        return [
            (vault, npm, str(decoded["old_token_id"])),
            (vault, npm, str(decoded["new_token_id"])),
        ]
    if event.get("vault") is not None:
        return [(event["vault"], npm, event["token_id"])]
    return []


def derive_all(events):
    """Group decoded events (each carrying a caller-added "chain" key - see
    module docstring; decode_log() itself never sets "chain") by ledger key
    and call derive_position_ledger() once per group. Returns one dict per
    group found, each with a "chain" key added back in.

    A StakingManager event (ProtocolFeesDistributed / FeesCompounded /
    FeesHarvestedDirect) carries no vault of its own (module docstring).
    This resolves it by SAME-TX, SAME-token_id correlation against any
    vault-carrying event elsewhere in the full input (typically the
    accompanying FeesHarvested) - not just within its own group, since at
    grouping time its vault is exactly the unknown being resolved. An
    event with no such sibling anywhere in the input is dropped (not
    raised, not guessed) - this is a real coverage gap for a StakingManager
    event with no matching vault event in the SAME batch, flagged in the
    Commit-1 report, not fixed here.
    """
    vault_by_tx_token = {}
    for event in events:
        if event.get("vault") is None:
            continue
        decoded = json.loads(event["decoded_json"])
        token_id = decoded.get("token_id", event.get("token_id"))
        if token_id is None:
            continue
        vault_by_tx_token[(event["tx_hash"], str(token_id))] = event["vault"]

    resolved_events = []
    for event in events:
        if event["event_type"] == "Swap":
            continue
        if event.get("vault") is None:
            decoded = json.loads(event["decoded_json"])
            vault = vault_by_tx_token.get((event["tx_hash"], str(decoded["token_id"])))
            if vault is None:
                continue
            event = {**event, "vault": vault}
        resolved_events.append(event)

    groups = {}
    for event in resolved_events:
        chain = event.get("chain")
        for vault, npm, token_id in _ledger_keys_for_event(event):
            key = (chain, vault, npm, token_id)
            groups.setdefault(key, []).append(event)

    results = []
    for (chain, vault, npm, token_id), group_events in groups.items():
        row = derive_position_ledger(group_events, (vault, npm, token_id))
        row["chain"] = chain
        results.append(row)
    return results
