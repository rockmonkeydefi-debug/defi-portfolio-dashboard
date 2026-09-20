"""Network/RPC layer for the MaxFi vault-event ledger backfill
(HANDOFF_maxfi_ledger.md, Commit 3b.1). maxfi_ledger.py stays pure (its own
docstring: "No network, no RPC, no sqlite") - every eth_getLogs/eth_call
this workstream needs lives here instead, mirroring maxfi_client.py's
hand-rolled `requests`-based JSON-RPC conventions (MaxFiRpcError, and
rpc_call's "[{chain}] ... calling {target} ({selector})" message shape)
rather than introducing web3.py's HTTPProvider. maxfi_client.py itself is
not reused here: it is a separate, already-scoped module for the
diagnostic/valuation call sites (eth_call + Multicall3 only), and this
module's job - eth_getLogs with chunking/backoff, plus one eth_call for
NPM resolution - is different enough to warrant its own small transport
functions rather than threading a new capability through that module.

Scope: RPC ingest infrastructure + NPM resolution (ruling 9) + returning
raw logs for the caller (web_portfolio._run_ledger_backfill) to decode and
write. Swap-log USD pricing (Commit 3b.2) and the new per-claim USD
storage (3b.3) are explicitly OUT of scope here - nothing in this module
prices anything.

This module DOES import and call maxfi_ledger.decode_log() (to discover
the token_id/pool_id set pass 1 yields, and to count fetched events by
type) - that is not a purity violation of maxfi_ledger.py itself (which
remains untouched, still pure); it is this module reusing that pure
decode logic rather than reimplementing it, the same way
web_portfolio.py's own ledger routes already do.
"""

import json
import os
import time

import requests
from web3 import Web3

import maxfi_ledger


# ── Errors ────────────────────────────────────────────────────────────────

class MaxFiIngestError(Exception):
    """Base class for every error this module raises."""


class MaxFiRpcError(MaxFiIngestError):
    """A JSON-RPC call failed outright: HTTP error, JSON-RPC error object,
    or an unexpected/empty result - mirrors maxfi_client.MaxFiRpcError's
    message shape exactly, for consistency across both MaxFi network
    modules."""


class MaxFiRpcOversizeRange(MaxFiRpcError):
    """The provider rejected an eth_getLogs call because the requested
    block range (or its result count) was too large. Recoverable by
    scan_logs_chunked(): halve the chunk size and retry the SAME range."""


class MaxFiRpcTooManyRequests(MaxFiRpcError):
    """HTTP 429 from the RPC provider. Recoverable by scan_logs_chunked():
    sleep and retry the SAME range at the SAME chunk size - a rate limit
    says nothing about whether the range itself was too large, so
    shrinking it in response would be the wrong reaction and would only
    prolong the scan."""


# ── Chain / contract registry ───────────────────────────────────────────
# Addresses copied verbatim from HANDOFF_maxfi_ledger.md (lines 67/81/99/
# 100 as of the Commit 3b.1 task) - never re-derived. Lowercased here at
# registry-definition time, matching every other address column's
# lowercase-at-storage/comparison convention in this codebase.

CHAINS = {
    "base": {
        "rpc_url_env": "BASE_RPC_URL",
        "vault": "0x7D27CDfBFcC878F7E7349e216d44204BFd2AFd55".lower(),
        "staking_manager": "0x4994743d7183d2ea5c651292A9Dab2C781020638".lower(),
        # Earliest known PositionCreated (HANDOFF_maxfi_ledger.md line 106)
        # - evidence-based, NOT a confirmed deploy block. The no-cursor
        # full-rescan model (see scan_chain()) re-fetches from here on
        # every invocation.
        "start_block": 44_609_025,
    },
    "robinhood": {
        "rpc_url_env": "RH_RPC_URL",
        "vault": "0x1195C074F898b7644bA732407619c9804dFE6DCE".lower(),
        "staking_manager": "0xBfD8cf8094feee44C314B3d5ec49ccDfd80caBAe".lower(),
        # Owner-topic filtering (see scan_chain()) keeps the scan cheap
        # regardless of range, so genesis is used rather than guessing a
        # start block with no supporting evidence, unlike Base above.
        "start_block": 1,
    },
}


def _chain_cfg(chain):
    cfg = CHAINS.get(chain)
    if cfg is None:
        raise MaxFiRpcError(f"unknown chain: {chain!r} (expected one of {sorted(CHAINS)})")
    return cfg


def _rpc_url(chain):
    cfg = _chain_cfg(chain)
    url = os.getenv(cfg["rpc_url_env"], "")
    if not url:
        raise MaxFiRpcError(
            f"[{chain}] no RPC URL configured (env var {cfg['rpc_url_env']} unset)"
        )
    return url


# ── JSON-RPC transport ───────────────────────────────────────────────────

def eth_block_number(chain, timeout=30):
    url = _rpc_url(chain)
    payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise MaxFiRpcError(f"[{chain}] HTTP error calling eth_blockNumber: {e}")
    if resp.status_code != 200:
        raise MaxFiRpcError(f"[{chain}] HTTP {resp.status_code} calling eth_blockNumber")
    body = resp.json()
    if isinstance(body, dict) and body.get("error"):
        raise MaxFiRpcError(f"[{chain}] JSON-RPC error calling eth_blockNumber: {body['error']}")
    result = body.get("result") if isinstance(body, dict) else None
    if not result:
        raise MaxFiRpcError(f"[{chain}] empty result calling eth_blockNumber")
    return int(result, 16)


def _looks_like_oversize_range_error(message):
    """Heuristic match over a JSON-RPC error message for the family of
    "this eth_getLogs call covers too much ground" responses different
    providers word differently (Alchemy, Infura, generic geth/erigon
    nodes).

    Hotfix 3b.1.1: this does NOT reliably arrive as a 200 HTTP response,
    contrary to what this docstring originally (wrongly) claimed - the
    first production Base dry_run failed because Alchemy delivers this
    exact rejection as HTTP 400 WITH a JSON-RPC error body, not a 200.
    eth_get_logs() therefore classifies by BODY CONTENT for any HTTP
    status, never trusting the status code alone to rule this out. A 429
    (rate limit) remains the one failure classified by HTTP status alone,
    since a 429 response carries no comparable JSON-RPC error body to
    inspect."""
    m = message.lower()
    return any(s in m for s in (
        "block range", "query returned more than", "exceeds the range",
        "range is too large", "limit exceeded", "too many results",
        "more than 10000 results", "response size exceeded",
        "up to a", "block range should work", "log response size exceeded",
        "query exceeds",
    ))


def eth_get_logs(chain, address, topics, from_block, to_block, timeout=30):
    """One eth_getLogs call, block range inclusive. Raises
    MaxFiRpcOversizeRange or MaxFiRpcTooManyRequests for the two
    specifically-recoverable failure shapes scan_logs_chunked() knows how
    to handle; any other failure raises the plain MaxFiRpcError base
    class. Callers doing a real scan use scan_logs_chunked() below, not
    this directly - this function makes exactly one RPC call, however
    large `[from_block, to_block]` is."""
    url = _rpc_url(chain)
    params = [{
        "address": address,
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block),
        "topics": topics,
    }]
    payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": params}
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise MaxFiRpcError(
            f"[{chain}] HTTP error calling eth_getLogs ({address}, blocks {from_block}-{to_block}): {e}"
        )
    if resp.status_code == 429:
        raise MaxFiRpcTooManyRequests(
            f"[{chain}] HTTP 429 calling eth_getLogs ({address}, blocks {from_block}-{to_block})"
        )

    # Body is parsed for ANY status, not only 200 (hotfix 3b.1.1): Alchemy
    # delivers an oversize-range rejection as HTTP 400 WITH a JSON-RPC
    # error body, not as a 200 - see _looks_like_oversize_range_error's
    # own docstring. A non-200 whose body is non-JSON or carries no
    # "error" key falls through unclassified to the generic
    # "HTTP {status} calling eth_getLogs" error below, same as before
    # this hotfix.
    try:
        body = resp.json()
    except ValueError:
        body = None

    if isinstance(body, dict) and body.get("error"):
        err = body["error"]
        message = str(err.get("message", err)) if isinstance(err, dict) else str(err)
        if _looks_like_oversize_range_error(message):
            raise MaxFiRpcOversizeRange(
                f"[{chain}] oversize-range error calling eth_getLogs "
                f"({address}, blocks {from_block}-{to_block}): {message}"
            )
        raise MaxFiRpcError(
            f"[{chain}] HTTP {resp.status_code} JSON-RPC error calling eth_getLogs "
            f"({address}, blocks {from_block}-{to_block}): {message}"
        )

    if resp.status_code != 200:
        raise MaxFiRpcError(
            f"[{chain}] HTTP {resp.status_code} calling eth_getLogs ({address}, blocks {from_block}-{to_block})"
        )
    if body is None:
        raise MaxFiRpcError(
            f"[{chain}] non-JSON RPC response calling eth_getLogs ({address}, blocks {from_block}-{to_block})"
        )
    result = body.get("result") if isinstance(body, dict) else None
    if result is None:
        raise MaxFiRpcError(
            f"[{chain}] empty result calling eth_getLogs ({address}, blocks {from_block}-{to_block})"
        )
    return result


def eth_call(chain, to_address, data_hex, timeout=30):
    """One eth_call at "latest" - same contract as maxfi_client.rpc_call
    (same error-message shape), kept as its own small function here
    rather than imported from maxfi_client (see module docstring)."""
    url = _rpc_url(chain)
    selector = data_hex[:10]
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "eth_call",
        "params": [{"to": to_address, "data": data_hex}, "latest"],
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise MaxFiRpcError(f"[{chain}] HTTP error calling {to_address} ({selector}): {e}")
    if resp.status_code != 200:
        raise MaxFiRpcError(f"[{chain}] HTTP {resp.status_code} calling {to_address} ({selector})")
    try:
        body = resp.json()
    except ValueError:
        raise MaxFiRpcError(f"[{chain}] non-JSON RPC response calling {to_address} ({selector})")
    if isinstance(body, dict) and body.get("error"):
        raise MaxFiRpcError(f"[{chain}] JSON-RPC error calling {to_address} ({selector}): {body['error']}")
    result = body.get("result") if isinstance(body, dict) else None
    if not result or result == "0x":
        raise MaxFiRpcError(f"[{chain}] empty result calling {to_address} ({selector}) — likely a revert")
    return result


def eth_get_block_timestamp(chain, block_number, timeout=30):
    """eth_getBlockByNumber(block_number, full_transactions=false) ->
    result["timestamp"] (hex unix seconds) - hotfix 3b.1.2's fallback for
    an RPC node whose eth_getLogs response carries no per-log timestamp
    at all (a plain node, unlike Alchemy's non-standard blockTimestamp
    field - see rpc_log_to_etherscan_shape()). Same requests/MaxFiRpcError
    conventions as eth_call/eth_get_logs above.

    Callers doing a real scan should go through scan_chain()'s own
    per-invocation (chain, block_number) cache rather than calling this
    directly for every log - see that cache's own comment for why (many
    logs routinely share one block)."""
    url = _rpc_url(chain)
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "eth_getBlockByNumber",
        "params": [hex(block_number), False],
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise MaxFiRpcError(f"[{chain}] HTTP error calling eth_getBlockByNumber({block_number}): {e}")
    if resp.status_code != 200:
        raise MaxFiRpcError(f"[{chain}] HTTP {resp.status_code} calling eth_getBlockByNumber({block_number})")
    try:
        body = resp.json()
    except ValueError:
        raise MaxFiRpcError(f"[{chain}] non-JSON RPC response calling eth_getBlockByNumber({block_number})")
    if isinstance(body, dict) and body.get("error"):
        raise MaxFiRpcError(
            f"[{chain}] JSON-RPC error calling eth_getBlockByNumber({block_number}): {body['error']}"
        )
    result = body.get("result") if isinstance(body, dict) else None
    if not result or "timestamp" not in result:
        raise MaxFiRpcError(
            f"[{chain}] empty/missing timestamp calling eth_getBlockByNumber({block_number})"
        )
    return result["timestamp"]


# ── Chunked eth_getLogs with adaptive backoff ────────────────────────────

# Hotfix 3b.1.4: raised from 50_000 now that Alchemy PAYG (confirmed live
# by the first successful Base dry_run - 139 calls/pass, 0 halvings, 0
# 429s) imposes NO eth_getLogs block-range cap, only a 150 MB response-
# size cap. That 150 MB cap - not a range limit - is what
# scan_logs_chunked()'s adaptive halving now guards against; halving
# itself stays exactly as it is, unchanged by this constant. The
# Free-tier 10-block limit hotfix 3b.1.1 found is the reason the halving
# path must be kept at all, even though PAYG itself needs it far less
# often - a future run on a Free-tier key (or any provider with a real
# range cap) still needs it to work correctly.
DEFAULT_CHUNK_SIZE = 2_000_000
MIN_CHUNK_SIZE = 500
RETRY_429_SLEEP_SECONDS = 2
MAX_429_RETRIES = 5

# Hotfix 3b.1.4: PoolAdded fires once, at admin-approval time, BEFORE any
# user ever opens a position in that pool - so it can be, and normally
# is, far earlier than this wallet set's own earliest tracked event
# (cfg["start_block"], which is evidence-based from the earliest known
# PositionCreated for THIS wallet, not the chain). The first successful
# Base dry_run used cfg["start_block"] for the PoolAdded scan too and
# found zero PoolAdded events as a direct result - no NPM resolution,
# so pass 3 (IncreaseLiquidity) never ran, so none of the 50 derived
# positions got a basis. PoolAdded MUST scan from genesis, independently
# of every wallet-scoped pass below - never share start_block with them.
POOL_ADDED_START_BLOCK = 0


def scan_logs_chunked(chain, address, topics, from_block, to_block, chunk_size=None):
    """eth_getLogs over [from_block, to_block] inclusive, chunked with
    adaptive backoff - adapted from
    src.connectors.uniswap_v4._discover_via_rpc's pattern, but generalized
    to distinguish a 429 from an oversize-range error. That original
    pattern treated every exception identically (halve until a floor,
    then silently drop the failed range and move on); this instead:

    - MaxFiRpcOversizeRange: halve chunk_size and retry the SAME
      from_block at the smaller size - never advances past a range that
      was too large to fetch.
    - MaxFiRpcTooManyRequests: sleep RETRY_429_SLEEP_SECONDS and retry the
      exact same range at the SAME chunk_size, up to MAX_429_RETRIES
      total across the whole scan - a rate limit says nothing about
      whether the range itself was too large, so shrinking it would be
      the wrong response.
    - Any other MaxFiRpcError propagates immediately, unretried.
    - Once chunk_size cannot be halved any further (already at
      MIN_CHUNK_SIZE) and an oversize-range error still occurs, or
      MAX_429_RETRIES is exhausted, the exception propagates rather than
      silently dropping the range - a silently-dropped block range in a
      financial ledger backfill is exactly the kind of gap this
      workstream exists to avoid, so this never degrades to "best
      effort" the way the connector pattern it's adapted from does.

    Returns (logs, stats) - logs is the full flat list of raw logs across
    every chunk; stats is {"calls", "chunk_halvings", "retries_429",
    "final_chunk_size"}, useful for the backfill response to flag when a
    scan needed an unexpectedly large number of chunked calls (the signal
    that a resumable cursor becomes worth building later - HANDOFF
    Commit 3b.1, constraint 4).
    """
    if chunk_size is None:
        chunk_size = DEFAULT_CHUNK_SIZE
    logs = []
    cursor = from_block
    stats = {"calls": 0, "chunk_halvings": 0, "retries_429": 0, "final_chunk_size": chunk_size}

    while cursor <= to_block:
        chunk_end = min(cursor + chunk_size - 1, to_block)
        try:
            chunk_logs = eth_get_logs(chain, address, topics, cursor, chunk_end)
            stats["calls"] += 1
        except MaxFiRpcOversizeRange:
            if chunk_size <= MIN_CHUNK_SIZE:
                raise
            chunk_size = max(MIN_CHUNK_SIZE, chunk_size // 2)
            stats["chunk_halvings"] += 1
            continue
        except MaxFiRpcTooManyRequests:
            stats["retries_429"] += 1
            if stats["retries_429"] > MAX_429_RETRIES:
                raise
            time.sleep(RETRY_429_SLEEP_SECONDS)
            continue
        logs.extend(chunk_logs)
        cursor = chunk_end + 1

    stats["final_chunk_size"] = chunk_size
    return logs, stats


# ── Topic filter encoding ─────────────────────────────────────────────────

def encode_topic_address(address):
    """32-byte left-padded topic filter value for an indexed `address`
    param (an owner topic) - same shape as
    src.connectors.uniswap_v4._discover_via_rpc's wallet_topic."""
    h = address[2:] if address.startswith(("0x", "0X")) else address
    return "0x" + h.lower().zfill(64)


def encode_topic_uint256(value):
    """32-byte left-padded topic filter value for an indexed `uint256`
    param (a token_id topic)."""
    return "0x" + format(int(value), "x").zfill(64)


# ── NPM resolution (ruling 9) ─────────────────────────────────────────────
# [Inference]: positionManager() is NOT ABI-verified the way PoolAdded's
# signature is (maxfi_ledger.py's own module docstring) - its selector is
# computed via the same local keccak() technique as maxfi_ledger.py's
# topic0 constants, but unlike PoolAdded there is no sourcify-verified ABI
# confirming this signature is actually what positionAdapter implements.
# scan_chain()'s npm_resolutions output exists specifically so Glenn can
# eyeball a resolved (pool_id, npm_address) pair against the known Base
# NPM (0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1) on his first live
# dry-run before this is trusted.

def _selector(signature):
    h = Web3.keccak(text=signature).hex()
    if not h.startswith("0x"):
        h = "0x" + h
    return h[:10]  # "0x" + 8 hex chars = 4-byte selector


SEL_POSITION_MANAGER = _selector("positionManager()")  # [Inference]

# Cache for resolved (chain, pool_id) -> npm_address, mirroring
# maxfi_client._VAULT_CACHE's shape exactly: per-process, written ONLY on
# a successful non-zero resolution, so a failed/zero-address lookup
# leaves the key absent and the next call retries. Cleared on process
# restart; per-worker under gunicorn, not shared.
_NPM_RESOLUTION_CACHE = {}


def _decode_eth_call_address(raw_hex):
    body = raw_hex[2:] if raw_hex.startswith("0x") else raw_hex
    if len(body) < 64:
        return None
    return "0x" + body[:64][-40:].lower()


def resolve_npm_address(chain, pool_id, position_adapter_address, use_cache=True):
    """positionAdapter.positionManager() via one eth_call - resolves the
    real NPM address for `pool_id` (ruling 9). Never raises: an RPC
    failure, an empty/short result, or a zero address all return None,
    matching the accepted scope limit already established for
    maxfi_ledger.build_pool_map() (a pool with no resolvable NPM simply
    keeps its positions' npm at None downstream - not treated as an
    error to route around here).

    Cached per (chain, pool_id) - see _NPM_RESOLUTION_CACHE's own comment
    for the exact caching contract.
    """
    key = (chain, pool_id)
    if use_cache and key in _NPM_RESOLUTION_CACHE:
        return _NPM_RESOLUTION_CACHE[key]
    try:
        raw = eth_call(chain, position_adapter_address, SEL_POSITION_MANAGER)
    except MaxFiRpcError:
        return None
    address = _decode_eth_call_address(raw)
    if address is None or address == "0x" + "0" * 40:
        return None
    _NPM_RESOLUTION_CACHE[key] = address
    return address


# ── Per-log decode isolation (hotfix 3b.1.3) ─────────────────────────────
# The first real Base dry_run after 3b.1.2 completed every RPC pass and
# then 500'd with a bare IndexError during decode - one undecodable log
# aborted the entire backfill. Precedent: B1.1's
# decode_positions_and_pools_soft (web_portfolio.py, LP Advisor Phase B)
# established that one bad unit must never abort a whole production run.
# maxfi_ledger.py's decoders are UNTOUCHED here - a log that fails is
# recorded and skipped, never patched around, because the right decoder
# change (if any) needs the real failing log's shape in hand first; this
# hotfix's job is only to make sure that log gets captured for diagnosis
# instead of crashing the run.

# Effectively-unbounded internal collection cap: safe_decode_log's own
# sample_limit parameter defaults to 10 (the response-facing sample
# size), but every internal call site below passes this much larger
# constant instead, so NOTHING is lost to premature truncation before
# the final ≤10 slice happens at the response boundary
# (_run_ledger_backfill, web_portfolio.py) - "keep a separate integer
# count of ALL failures" is satisfied by simply never dropping any
# failure until that final boundary, rather than trying to track a count
# separately from the list itself.
_UNBOUNDED_FAILURE_LIMIT = 1_000_000


def safe_decode_log(raw_log, failures, sample_limit=10):
    """Calls maxfi_ledger.decode_log(raw_log) inside try/except Exception.
    On success, returns the decoded record (or None, exactly as
    decode_log() itself returns None for a topic0 outside this module's
    tracked vocabulary - NOT a failure, nothing appended). On an actual
    exception, appends a diagnostic dict to `failures` (a caller-owned
    list) - but only while len(failures) < sample_limit, so a caller
    controls how much detail it keeps - and returns None either way.

    The diagnostic is read entirely defensively from the RAW log (never
    the exception, never anything decode_log() may have partially
    computed) so building it can never itself raise:
      {tx_hash, log_index, block_number, contract_address, topic0,
       topic_count, data_word_count, error}
    topic_count = len(topics) (0 if topics is missing/not a list).
    data_word_count = (len(data) - 2) // 64 for a "0x..." data string,
    else 0. Every other field is read via .get() with no fallback that
    could itself raise; a malformed log (missing keys entirely) yields
    None values in the diagnostic rather than an exception.
    """
    try:
        return maxfi_ledger.decode_log(raw_log)
    except Exception as e:
        if len(failures) < sample_limit:
            log = raw_log if isinstance(raw_log, dict) else {}

            topics = log.get("topics")
            if not isinstance(topics, list):
                topics = []

            data = log.get("data")
            if isinstance(data, str) and data.startswith("0x"):
                data_word_count = (len(data) - 2) // 64
            else:
                data_word_count = 0

            address = log.get("address")
            if isinstance(address, dict):
                address = address.get("hash")

            tx_hash = log.get("transactionHash", log.get("transaction_hash"))
            log_index = log.get("logIndex", log.get("index"))
            block_number = log.get("blockNumber", log.get("block_number"))

            failures.append({
                "tx_hash": tx_hash,
                "log_index": log_index,
                "block_number": block_number,
                "contract_address": address,
                "topic0": topics[0] if topics else None,
                "topic_count": len(topics),
                "data_word_count": data_word_count,
                "error": f"{type(e).__name__}: {e}",
            })
        return None


def _dedupe_failures(failures):
    """Collapses `failures` to one entry per distinct (tx_hash,
    log_index), keeping the first occurrence - the same physical log can
    legitimately fail decode more than once across this module's own
    internal loops (e.g. scan_chain()'s token_id-discovery pass and its
    event_type_counts pass both touch the same raw log), and again in
    the route's own separate re-decode of the same raw_logs list. Pure,
    no mutation of the input list."""
    seen = set()
    deduped = []
    for f in failures:
        key = (f.get("tx_hash"), f.get("log_index"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    return deduped


# ── Two-pass, wallet-scoped chain scan ────────────────────────────────────

def _owner_topics(wallets):
    return [encode_topic_address(w) for w in wallets]


def _token_id_topics(token_ids):
    return [encode_topic_uint256(tid) for tid in token_ids]


# ── Raw-RPC-log adaptation (hotfix 3b.1.2) ───────────────────────────────
# A raw eth_getLogs record is a THIRD log shape - distinct from both
# shapes maxfi_ledger._normalize_log documents and handles (Etherscan:
# blockNumber hex + timeStamp hex; Blockscout: block_number int +
# block_timestamp ISO string). It has blockNumber (hex), so
# _normalize_log takes the Etherscan branch - and then KeyErrors on
# log["timeStamp"], a field standard eth_getLogs output does not carry.
# Alchemy adds a NON-STANDARD blockTimestamp field (hex unix seconds);
# a plain node returns no per-log timestamp at all. maxfi_ledger.py
# stays PURE and UNTOUCHED (its own docstring: no network) - this
# adaptation happens entirely in the network/ingest layer, before
# decode_log() ever sees a log, exactly as this file's original module
# docstring always intended ("returns raw logs in the same shape
# decode_log already accepts") but which 3b.1 never verified against a
# real RPC response - only fixture-shaped test doubles, which are
# already Etherscan-shape and never exposed this gap.

def rpc_log_to_etherscan_shape(log, block_timestamp_hex=None):
    """Adapts one raw eth_getLogs log record into the Etherscan shape
    maxfi_ledger.decode_log() already accepts. Copies address/topics/
    data/blockNumber/transactionHash/logIndex VERBATIM from the raw RPC
    log (hex strings as-is - never converted to int here; _normalize_log
    does that conversion itself). timeStamp is set, in priority order:
      (a) the raw log's own "blockTimestamp" field, if present;
      (b) `block_timestamp_hex`, if the caller supplies one (the
          eth_getBlockByNumber fallback path);
      (c) otherwise raises ValueError naming the block - never guesses a
          timestamp.

    Pure: no network call of its own; always returns a NEW dict, never
    mutates `log`.
    """
    block_number = log["blockNumber"]
    if "blockTimestamp" in log:
        timestamp_hex = log["blockTimestamp"]
    elif block_timestamp_hex is not None:
        timestamp_hex = block_timestamp_hex
    else:
        raise ValueError(
            f"no blockTimestamp on RPC log and no block_timestamp_hex fallback given (block {block_number})"
        )
    return {
        "address": log["address"],
        "topics": log["topics"],
        "data": log["data"],
        "blockNumber": block_number,
        "transactionHash": log["transactionHash"],
        "logIndex": log["logIndex"],
        "timeStamp": timestamp_hex,
    }


def _adapt_rpc_logs(chain, raw_logs, timestamp_cache):
    """Adapts a batch of raw eth_getLogs records for one scan_chain()
    pass, via rpc_log_to_etherscan_shape(). `timestamp_cache` is
    scan_chain()'s own per-invocation {block_number: timestamp_hex} dict,
    shared across every pass in that one call - many logs routinely
    share a block (see the real six-log Alchemy fixture, where 5 of 6
    entries are block 0x2a8ae26), so this ensures at most one
    eth_getBlockByNumber fallback call per distinct block per scan, not
    one per log.

    A log that already carries "timeStamp" is passed through unchanged
    (not re-wrapped) - this is the case for every existing fixture/test
    double in this codebase, which are already Etherscan-shape and need
    no adaptation; a genuine raw RPC log never has this key, only
    "blockTimestamp" (Alchemy) or neither, so this never fires in
    production and exists purely so this hotfix doesn't touch the
    behavior of any log that was already decode_log()-ready.
    """
    adapted = []
    for raw_log in raw_logs:
        if "timeStamp" in raw_log:
            adapted.append(raw_log)
            continue
        if "blockTimestamp" in raw_log:
            adapted.append(rpc_log_to_etherscan_shape(raw_log))
            continue
        block_number = int(raw_log["blockNumber"], 16)
        if block_number not in timestamp_cache:
            timestamp_cache[block_number] = eth_get_block_timestamp(chain, block_number)
        adapted.append(rpc_log_to_etherscan_shape(raw_log, block_timestamp_hex=timestamp_cache[block_number]))
    return adapted


def scan_chain(chain, wallets):
    """Owner/token_id-filtered scan of `chain` for every wallet in
    `wallets` (HANDOFF_maxfi_ledger.md Commit 3b.1). Returns raw logs
    only - the caller (web_portfolio._run_ledger_backfill) decodes them
    via maxfi_ledger.decode_log() before writing, since that decode/
    insert/derive logic belongs with the DB write path, not this network
    module. (This function DOES call decode_log() internally, but only
    to discover the token_id/pool_id set pass 1 yields and to count
    fetched events by type for the caller's unverified_event_types
    reporting - each raw log therefore gets decoded twice across the
    full pipeline, once here and once again by the caller. Cheap,
    pure-CPU work relative to the RPC calls themselves; not worth a
    cross-module decode cache for a batch job that runs rarely.)

    Real dependency order (NOT the literal order named in this commit's
    own task text, which listed "pass 3 -> PoolAdded unfiltered -> NPM
    resolution" - impossible as written, since pass 3's query TARGET is
    the address NPM resolution produces; NPM resolution must complete
    before pass 3 can run. Flagged in this commit's own report, resolved
    here by the actual data dependency, not by the literal step order):

      1. Pass 1 (vault, owner-filtered): PositionCreated/
         PositionWithdrawn/FeesHarvested in ONE eth_getLogs call (owner
         at topics[2]) plus SnuggleRebalanced in a second call (owner at
         topics[3] - a different position) -> yields this wallet set's
         full token_id set (including SnuggleRebalanced's new_token_id -
         rebalance-minted children, HANDOFF's "also visible in the dump"
         note) and every PositionCreated event's pool_id.
      2. PoolAdded (vault, unfiltered) - independent of wallets/
         token_ids, so this could run anytime; placed here because NPM
         resolution (next) needs its output.
      3. NPM resolution (ruling 9): for each pool_id actually seen in
         step 1 (never every PoolAdded event on the chain), find its
         PoolAdded record from step 2 and resolve
         positionAdapter.positionManager().
      4. Pass 2 (StakingManager, token_id-filtered): ProtocolFeesDistributed/
         FeesCompounded/FeesHarvestedDirect - no owner topic exists on
         any of these three, only step 1's token_id set is needed.
      5. Pass 3 (NPM, token_id-filtered): IncreaseLiquidity - needs BOTH
         step 1's token_id set AND step 3's resolved NPM address(es) as
         its query target(s); one call per distinct resolved NPM address
         (a wallet's positions can span more than one pool/NPM).

    Returns {"raw_logs": [...], "wallets_scanned": [...], "token_ids":
    [...], "npm_resolutions": [{"pool_id", "npm_address"}, ...],
    "event_type_counts": {event_type: count, ...},
    "chunk_stats": {"pass1_vault", "pass1_snuggle_rebalanced",
    "pool_added", "pass2_staking_manager", "pass3_npm" (dict keyed by
    resolved npm_address)}}.
    """
    cfg = _chain_cfg(chain)
    vault = cfg["vault"]
    staking_manager = cfg["staking_manager"]
    start_block = cfg["start_block"]

    empty_stats = {"calls": 0, "chunk_halvings": 0, "retries_429": 0, "final_chunk_size": None}

    if not wallets:
        return {
            "raw_logs": [], "wallets_scanned": [], "token_ids": [],
            "npm_resolutions": [], "event_type_counts": {},
            "block_timestamp_lookups": 0,
            "decode_failed": 0, "decode_failures": [],
            "chunk_stats": {
                "pass1_vault": dict(empty_stats),
                "pass1_snuggle_rebalanced": dict(empty_stats),
                "pool_added": {**empty_stats, "from_block": POOL_ADDED_START_BLOCK},
                "pass2_staking_manager": dict(empty_stats),
                "pass3_npm": {},
            },
        }

    end_block = eth_block_number(chain)
    owner_topics = _owner_topics(wallets)

    # Per-invocation {block_number: timestamp_hex} cache (hotfix 3b.1.2) -
    # shared across every pass below so a block with several logs (the
    # routine case - see rpc_log_to_etherscan_shape's own comment)
    # triggers at most one eth_getBlockByNumber fallback call, not one
    # per log. On Alchemy this cache never gets a single entry (every
    # log already carries blockTimestamp) - block_timestamp_lookups in
    # the return value below reports len(this cache) so that's visible,
    # not assumed.
    timestamp_cache = {}

    # Per-invocation decode-failure collection (hotfix 3b.1.3), shared
    # across every decode_log() call site in this function (token_id/
    # pool_id discovery, the PoolAdded lookup, and event_type_counts) -
    # see _dedupe_failures()'s own comment for why the SAME physical log
    # can legitimately end up appended more than once here before the
    # dedup pass right before this function returns.
    decode_failures = []

    # Pass 1a: PositionCreated / PositionWithdrawn / FeesHarvested - owner
    # at topics[2], one call covers every wallet via an OR-list there.
    pass1_vault_topics = [
        [
            maxfi_ledger.TOPIC_POSITION_CREATED,
            maxfi_ledger.TOPIC_POSITION_WITHDRAWN,
            maxfi_ledger.TOPIC_FEES_HARVESTED,
        ],
        None,
        owner_topics,
    ]
    pass1_vault_logs, pass1_vault_stats = scan_logs_chunked(
        chain, vault, pass1_vault_topics, start_block, end_block
    )
    pass1_vault_logs = _adapt_rpc_logs(chain, pass1_vault_logs, timestamp_cache)

    # Pass 1b: SnuggleRebalanced - owner at topics[3], its own call.
    pass1_snuggle_topics = [
        [maxfi_ledger.TOPIC_SNUGGLE_REBALANCED],
        None, None,
        owner_topics,
    ]
    pass1_snuggle_logs, pass1_snuggle_stats = scan_logs_chunked(
        chain, vault, pass1_snuggle_topics, start_block, end_block
    )
    pass1_snuggle_logs = _adapt_rpc_logs(chain, pass1_snuggle_logs, timestamp_cache)

    pass1_logs = pass1_vault_logs + pass1_snuggle_logs

    token_ids = set()
    pool_ids_seen = set()
    for raw_log in pass1_logs:
        record = safe_decode_log(raw_log, decode_failures, sample_limit=_UNBOUNDED_FAILURE_LIMIT)
        if record is None:
            continue
        decoded = json.loads(record["decoded_json"])
        if record["event_type"] == "SnuggleRebalanced":
            token_ids.add(decoded["old_token_id"])
            token_ids.add(decoded["new_token_id"])
        else:
            token_ids.add(decoded["token_id"])
        if record["event_type"] == "PositionCreated":
            pool_ids_seen.add(decoded["pool_id"])

    # Step 2: PoolAdded, unfiltered against the vault - scans from
    # genesis (POOL_ADDED_START_BLOCK), NEVER cfg["start_block"]. See
    # POOL_ADDED_START_BLOCK's own comment for why sharing it with the
    # wallet-scoped passes below silently zeroes out NPM resolution.
    pool_added_topics = [[maxfi_ledger.TOPIC_POOL_ADDED]]
    pool_added_logs, pool_added_stats = scan_logs_chunked(
        chain, vault, pool_added_topics, POOL_ADDED_START_BLOCK, end_block
    )
    pool_added_stats["from_block"] = POOL_ADDED_START_BLOCK
    pool_added_logs = _adapt_rpc_logs(chain, pool_added_logs, timestamp_cache)
    pool_added_by_pool_id = {}
    for raw_log in pool_added_logs:
        record = safe_decode_log(raw_log, decode_failures, sample_limit=_UNBOUNDED_FAILURE_LIMIT)
        if record is None or record["event_type"] != "PoolAdded":
            continue
        decoded = json.loads(record["decoded_json"])
        pool_added_by_pool_id[decoded["pool_id"]] = decoded

    # Step 3: NPM resolution - only for pool_ids this wallet set actually
    # touches, never every PoolAdded event on the chain.
    npm_resolutions = []
    npm_addresses_by_pool_id = {}
    for pool_id in sorted(pool_ids_seen):
        pool_added = pool_added_by_pool_id.get(pool_id)
        if pool_added is None:
            # Accepted scope limit (same precedent as
            # maxfi_ledger.build_pool_map): a pool whose PoolAdded event
            # isn't in this batch stays unresolved, not an error.
            continue
        npm_address = resolve_npm_address(chain, pool_id, pool_added["position_adapter"])
        if npm_address is not None:
            npm_addresses_by_pool_id[pool_id] = npm_address
            npm_resolutions.append({"pool_id": pool_id, "npm_address": npm_address})

    npm_addresses = sorted(set(npm_addresses_by_pool_id.values()))

    # Pass 2: StakingManager, token_id-filtered - no owner topic exists
    # on any of these three event types.
    pass2_logs = []
    pass2_stats = dict(empty_stats)
    if token_ids:
        pass2_topics = [
            [
                maxfi_ledger.TOPIC_PROTOCOL_FEES_DISTRIBUTED,
                maxfi_ledger.TOPIC_FEES_COMPOUNDED,
                maxfi_ledger.TOPIC_FEES_HARVESTED_DIRECT,
            ],
            _token_id_topics(sorted(token_ids)),
        ]
        pass2_logs, pass2_stats = scan_logs_chunked(
            chain, staking_manager, pass2_topics, start_block, end_block
        )
        pass2_logs = _adapt_rpc_logs(chain, pass2_logs, timestamp_cache)

    # Pass 3: NPM, token_id-filtered - one call per distinct resolved NPM
    # address (a wallet's positions can span more than one pool/NPM).
    pass3_logs = []
    pass3_stats_by_npm = {}
    if token_ids and npm_addresses:
        pass3_topics = [[maxfi_ledger.TOPIC_INCREASE_LIQUIDITY], _token_id_topics(sorted(token_ids))]
        for npm_address in npm_addresses:
            logs, stats = scan_logs_chunked(chain, npm_address, pass3_topics, start_block, end_block)
            logs = _adapt_rpc_logs(chain, logs, timestamp_cache)
            pass3_logs.extend(logs)
            pass3_stats_by_npm[npm_address] = stats

    raw_logs = pass1_logs + pool_added_logs + pass2_logs + pass3_logs

    event_type_counts = {}
    for raw_log in raw_logs:
        record = safe_decode_log(raw_log, decode_failures, sample_limit=_UNBOUNDED_FAILURE_LIMIT)
        if record is None:
            continue
        et = record["event_type"]
        event_type_counts[et] = event_type_counts.get(et, 0) + 1

    # Dedupe now, not per-loop above: the SAME physical log is touched by
    # more than one loop in this function (e.g. every pass1_logs entry is
    # also part of raw_logs above), so an undecodable log can legitimately
    # generate more than one raw diagnostic before this point - collapse
    # to one entry per (tx_hash, log_index) so decode_failed reflects
    # distinct BAD LOGS, not distinct decode ATTEMPTS.
    decode_failures = _dedupe_failures(decode_failures)

    return {
        "raw_logs": raw_logs,
        "wallets_scanned": list(wallets),
        "token_ids": sorted(str(t) for t in token_ids),
        "npm_resolutions": npm_resolutions,
        "event_type_counts": event_type_counts,
        # Hotfix 3b.1.2 - count of DISTINCT blocks that needed the
        # eth_getBlockByNumber fallback (len(timestamp_cache), not a
        # per-log count). On Alchemy today this is always 0: every log
        # already carries blockTimestamp, so the fallback is never
        # invoked - expected, not a bug.
        "block_timestamp_lookups": len(timestamp_cache),
        # Hotfix 3b.1.3 - logs that raised during decode_log(), recorded
        # and skipped rather than aborting the scan. Not yet deduped
        # against the route's OWN separate re-decode of raw_logs
        # (_run_ledger_backfill does that final merge+dedupe) - this is
        # scan_chain()'s own complete, internally-deduped count/sample.
        "decode_failed": len(decode_failures),
        "decode_failures": decode_failures,
        "chunk_stats": {
            "pass1_vault": pass1_vault_stats,
            "pass1_snuggle_rebalanced": pass1_snuggle_stats,
            "pool_added": pool_added_stats,
            "pass2_staking_manager": pass2_stats,
            "pass3_npm": pass3_stats_by_npm,
        },
    }
