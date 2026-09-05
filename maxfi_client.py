"""MaxFi LP diagnostic network layer: per-chain contract registry, minimal
hand-rolled ABI encode/decode, and Multicall3 aggregate3 batching with
strict per-call failure checking.

Deliberately independent of web_portfolio.py and of the existing
custom-token RPC helper there (CUSTOM_TOKEN_CHAINS / _balance_of_raw etc.):
that helper is shaped for single balanceOf-style web3.py contract calls,
not aggregate3 batching with per-call failure inspection. This module talks
JSON-RPC directly via `requests` (already a project dependency) instead of
adding web3/eth-abi, since hand-rolled 32-byte-word ABI encode/decode is
all two static-struct diagnostic endpoints need.
"""

import os
import json
import time
import requests
from datetime import datetime, timezone

from maxfi_math import (
    to_int24,
    to_int128,
    to_int56,
    tick_to_price,
    sqrt_price_x96_to_price,
    range_percent,
)


# ── Errors ───────────────────────────────────────────────────────────────

class MaxFiError(Exception):
    """Base class for all MaxFi diagnostic errors."""


class MaxFiRpcError(MaxFiError):
    """A JSON-RPC call failed outright: HTTP error, JSON-RPC error object,
    or an empty "0x" result (almost always a revert)."""


class MaxFiCallError(MaxFiError):
    """A Multicall3 sub-call reported failure, or Multicall3 itself isn't
    reachable/deployed at the expected address on this chain."""


class MaxFiDecodeError(MaxFiError):
    """Decoded contract return data had the wrong word count or failed a
    plausibility check. The MaxFi vault is an upgradeable proxy whose
    field layout can change silently, so these checks exist to catch that
    rather than let a shifted layout produce quietly-wrong numbers."""


# ── Tunables (scanner_settings.json — never hardcoded; missing key/file
# falls back to the default below rather than raising) ─────────────────

_SETTINGS_PATH = os.path.join("data", "scanner_settings.json")
_DEFAULT_MULTICALL_CHUNK_SIZE = 50
_DEFAULT_RPC_TIMEOUT_SECONDS = 10


def _setting(key, default):
    try:
        with open(_SETTINGS_PATH, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and key in data:
            return data[key]
    except Exception:
        pass
    return default


def multicall_chunk_size():
    return int(_setting("maxfi_multicall_chunk_size", _DEFAULT_MULTICALL_CHUNK_SIZE))


def rpc_timeout():
    return float(_setting("maxfi_rpc_timeout_seconds", _DEFAULT_RPC_TIMEOUT_SECONDS))


# ── Chain / contract registry ───────────────────────────────────────────
# Lens addresses differ per chain — never assume a shared deployment
# address for anything except Multicall3, which is address-deterministic
# (CREATE2, same address on every chain that has it deployed).

MULTICALL3_ADDRESS = "0xcA11bde05977b3631167028862bE2a173976CA11"

CHAINS = {
    "base": {
        "chain_id": 8453,
        "lens": "0x286490622bcc7261c0Ce794b7166dc67d3cE18Bd",
        "position_manager": "0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1",
        # Reuses the same BASE_RPC_URL env var web_portfolio.py's
        # CUSTOM_TOKEN_CHAINS registry resolves for Base (Alchemy) — see
        # PR summary for exact line references. No new URL/key introduced.
        "rpc_url": os.getenv("BASE_RPC_URL", ""),
    },
    "robinhood": {
        "chain_id": 4663,
        "lens": "0x71b55e366a0f43260b1138a32c312ba7bb7f30f7",
        "position_manager": "0x73991a25c818bf1f1128deaab1492d45638de0d3",
        "rpc_url": "https://rpc.mainnet.chain.robinhood.com/",
    },
}

# Vault addresses are immutable per chain absent a protocol migration, so the
# lens.vault() lookup is resolved once per chain per process and reused. Keyed on
# chain slug so a Base resolution can never be served for a Robinhood lookup.
# Written only on a fully successful, non-zero resolution: a failed or zero-address
# lookup leaves the key absent so the next call retries. Cleared on process restart,
# so a Railway redeploy re-resolves. Per-worker under gunicorn, not shared.
_VAULT_CACHE = {}

# ── Function selectors (verified from live traffic) ─────────────────────

SEL_LENS_VAULT = "0xfbfa77cf"
SEL_LENS_GET_USER_POSITIONS = "0x2a6bc2dd"
SEL_LENS_IS_POSITION_OUT_OF_RANGE = "0x41051ef8"
# NOTE (Phase A.1): returns 2 words in practice on Robinhood Chain, not 1 as
# originally captured — the source findings doc's ABI capture was truncated
# (evidenced by "+N more" notation elsewhere in the same doc on other lens
# functions). The second word's meaning is unconfirmed as of this patch; see
# is_position_out_of_range()'s "at_least" tier and its extra_words output.
# NOTE selector collision: this exact selector is used by BOTH the MaxFi
# vault's positions(uint256) and the Uniswap V3 NPM's positions(uint256),
# returning completely different structs. decode_vault_position() and
# decode_npm_position() are separate functions for exactly this reason —
# never share a decoder between the two call sites.
SEL_POSITIONS = "0x99fbab88"
SEL_NPM_FACTORY = "0xc45a0155"
SEL_FACTORY_GET_POOL = "0x1698ee82"
SEL_POOL_SLOT0 = "0x3850c7bd"
SEL_POOL_FEE_GROWTH_GLOBAL_0 = "0xf3058399"
SEL_POOL_FEE_GROWTH_GLOBAL_1 = "0x46141319"
SEL_POOL_TICKS = "0xf30dba93"
SEL_ERC20_DECIMALS = "0x313ce567"
SEL_ERC20_SYMBOL = "0x95d89b41"

AGGREGATE3_SELECTOR = "0x82ad56cb"


def _chain_cfg(chain):
    cfg = CHAINS.get(chain)
    if cfg is None:
        raise MaxFiRpcError(f"unknown chain: {chain!r} (expected one of {sorted(CHAINS)})")
    return cfg


# ── Minimal ABI encoding (hand-rolled — no web3/eth-abi dependency) ─────

def _strip0x(h):
    return h[2:] if h.startswith(("0x", "0X")) else h


def encode_address(address):
    h = _strip0x(address).lower()
    if len(h) != 40:
        raise ValueError(f"invalid address for ABI encoding: {address!r}")
    return h.rjust(64, "0")


def encode_uint256(value):
    if value < 0:
        raise ValueError(f"encode_uint256 requires a non-negative value, got {value}")
    return format(value, "x").rjust(64, "0")


def encode_int24(value):
    """Two's-complement encode a signed value into a full 32-byte word —
    the EVM always sign-extends signed call arguments to a full word."""
    return format(value & ((1 << 256) - 1), "x").rjust(64, "0")


def calldata(selector, *encoded_words):
    """Prefix an ABI selector onto already-encoded 32-byte-word arguments."""
    return "0x" + _strip0x(selector) + "".join(encoded_words)


# ── Minimal ABI decoding ─────────────────────────────────────────────────

def split_words(raw_hex):
    """Split 0x-prefixed return data into a list of 32-byte hex words
    (each 64 hex chars, no 0x prefix)."""
    h = _strip0x(raw_hex)
    if len(h) % 64 != 0:
        raise MaxFiDecodeError(
            f"return data length {len(h) // 2} bytes is not a multiple of 32"
        )
    return [h[i:i + 64] for i in range(0, len(h), 64)]


def _split_words(data_hex, expected_count, mode, label):
    """Two-tier word-count validation on top of split_words().

    mode="exact": standardized, immutable contracts (Uniswap NPM/pool,
    ERC20, Multicall3-adjacent calls) where any word-count mismatch is a
    genuine anomaly and must raise.

    mode="at_least": MaxFi's own contracts (lens, vault), where our
    captured ABI is demonstrably incomplete (isPositionOutOfRange was
    captured as 1 word but actually returns 2 on Robinhood Chain).
    expected_count is a floor, not a ceiling: fewer words still raises,
    but extra words are returned rather than rejected or dropped, so the
    caller can decode the known fields and surface the rest.

    Returns (known_words, extra_words) — extra_words is always [] in
    "exact" mode.
    """
    words = split_words(data_hex)
    if mode == "exact" and len(words) != expected_count:
        raise MaxFiDecodeError(
            f"{label} returned {len(words)} words, expected exactly {expected_count}"
        )
    if mode == "at_least" and len(words) < expected_count:
        raise MaxFiDecodeError(
            f"{label} returned {len(words)} words, expected at least {expected_count}"
        )
    return words[:expected_count], words[expected_count:]


def word_to_int(word_hex):
    return int(word_hex, 16)


decode_uint = word_to_int


def decode_address(word_hex):
    return "0x" + word_hex[-40:]


def decode_bool(word_hex):
    return word_to_int(word_hex) != 0


def decode_dynamic_uint256_array(raw_hex):
    """Decode a single dynamic `uint256[]` return value: offset word,
    length word (at that offset), then `length` element words."""
    words = split_words(raw_hex)
    if not words:
        raise MaxFiDecodeError("empty return data for dynamic uint256[]")
    offset = word_to_int(words[0])
    if offset % 32 != 0:
        raise MaxFiDecodeError(f"unexpected dynamic array offset: {offset}")
    idx = offset // 32
    if idx >= len(words):
        raise MaxFiDecodeError("dynamic array offset points past return data")
    length = word_to_int(words[idx])
    start, end = idx + 1, idx + 1 + length
    if end > len(words):
        raise MaxFiDecodeError(
            f"dynamic array length {length} exceeds available return data"
        )
    return [word_to_int(w) for w in words[start:end]]


def decode_string_or_bytes32(raw_hex):
    """Decode an ERC20-style string return that may be ABI-dynamic
    (modern tokens) or a right-padded bytes32 (old-style, e.g. MKR).
    Tries dynamic first, falls back to bytes32, strips nulls."""
    words = split_words(raw_hex)
    if not words:
        return ""
    try:
        offset = word_to_int(words[0])
        if offset % 32 == 0:
            idx = offset // 32
            if 0 < idx < len(words):
                length = word_to_int(words[idx])
                start = idx + 1
                n_words = (length + 31) // 32
                if length <= 1024 and start + n_words <= len(words):
                    raw = "".join(words[start:start + n_words])
                    text = bytes.fromhex(raw)[:length].decode("utf-8", "strict")
                    if text:
                        return text
    except Exception:
        pass
    raw = bytes.fromhex(words[0])
    return raw.rstrip(b"\x00").decode("utf-8", "ignore")


# ── JSON-RPC transport ───────────────────────────────────────────────────

def rpc_call(chain, to_address, data_hex, timeout=None):
    """One eth_call at "latest". Raises MaxFiRpcError naming the chain,
    target, and selector on any HTTP error, JSON-RPC error object, or
    empty "0x" result (a revert masquerading as data)."""
    cfg = _chain_cfg(chain)
    url = cfg["rpc_url"]
    selector = data_hex[:10]
    if not url:
        raise MaxFiRpcError(f"[{chain}] no RPC URL configured for target {to_address} ({selector})")
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": to_address, "data": data_hex}, "latest"],
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout or rpc_timeout())
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
        raise MaxFiRpcError(
            f"[{chain}] empty result calling {to_address} ({selector}) — likely a revert"
        )
    return result


def eth_block_number(chain):
    cfg = _chain_cfg(chain)
    url = cfg["rpc_url"]
    if not url:
        raise MaxFiRpcError(f"[{chain}] no RPC URL configured for eth_blockNumber")
    payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}
    try:
        resp = requests.post(url, json=payload, timeout=rpc_timeout())
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


# ── Multicall3 aggregate3 ────────────────────────────────────────────────

def _pad32(data_bytes):
    n = len(data_bytes)
    padded = ((n + 31) // 32) * 32
    return data_bytes + b"\x00" * (padded - n)


def encode_aggregate3(calls):
    """Encode aggregate3((address,bool,bytes)[]) calldata.

    calls: list of (target_address, allow_failure, calldata_hex).
    """
    n = len(calls)
    tuple_encodings = []
    for target, allow_failure, cd_hex in calls:
        cd_bytes = bytes.fromhex(_strip0x(cd_hex))
        tuple_hex = (
            encode_address(target)
            + encode_uint256(1 if allow_failure else 0)
            + encode_uint256(0x60)  # offset to `bytes callData` within this tuple
            + encode_uint256(len(cd_bytes))
            + _pad32(cd_bytes).hex()
        )
        tuple_encodings.append(tuple_hex)

    offsets = []
    running = n * 32  # bytes occupied by the n offset words themselves
    for t in tuple_encodings:
        offsets.append(running)
        running += len(t) // 2

    array_body = "".join(encode_uint256(o) for o in offsets) + "".join(tuple_encodings)
    body = encode_uint256(0x20) + encode_uint256(n) + array_body
    return calldata(AGGREGATE3_SELECTOR, body)


def decode_aggregate3_result(raw_hex):
    """Decode aggregate3's `Result[] returns (bool success, bytes returnData)`.

    Returns a list of (success, return_data_hex) in call order.
    """
    words = split_words(raw_hex)
    if len(words) < 2:
        raise MaxFiDecodeError("aggregate3 return data too short")
    top_offset = word_to_int(words[0])
    if top_offset != 32:
        raise MaxFiDecodeError(f"unexpected aggregate3 top-level offset: {top_offset}")
    length = word_to_int(words[1])
    elements_start = 2  # index of the word right after the length word
    offset_words = words[elements_start:elements_start + length]
    if len(offset_words) != length:
        raise MaxFiDecodeError("aggregate3 result array shorter than its declared length")

    results = []
    for off_word in offset_words:
        rel_offset = word_to_int(off_word)
        if rel_offset % 32 != 0:
            raise MaxFiDecodeError(f"unexpected aggregate3 element offset: {rel_offset}")
        idx = elements_start + rel_offset // 32
        success = word_to_int(words[idx]) != 0
        bytes_offset = word_to_int(words[idx + 1])
        if bytes_offset % 32 != 0:
            raise MaxFiDecodeError(f"unexpected aggregate3 returnData offset: {bytes_offset}")
        length_idx = idx + bytes_offset // 32
        data_len = word_to_int(words[length_idx])
        n_words = (data_len + 31) // 32
        data_words = words[length_idx + 1:length_idx + 1 + n_words]
        raw = "".join(data_words)
        results.append((success, "0x" + raw[:data_len * 2]))
    return results


def multicall3(chain, calls, chunk_size=None):
    """Batch `calls` (list of (target_address, calldata_hex)) through
    Multicall3.aggregate3, chunked at `chunk_size` (default from
    scanner_settings.json). Returns decoded returnData in the same order
    as `calls`.

    allowFailure is always set true per Call3 entry, but every result's
    success flag is checked explicitly and any false raises MaxFiCallError
    naming the index and target — a reverted sub-call with allowFailure
    true decodes to all-zero bytes, which must never pass silently as data.
    """
    if chunk_size is None:
        chunk_size = multicall_chunk_size()
    results = []
    for start in range(0, len(calls), chunk_size):
        chunk = calls[start:start + chunk_size]
        agg_calls = [(target, True, cd) for target, cd in chunk]
        cd_hex = encode_aggregate3(agg_calls)
        raw = rpc_call(chain, MULTICALL3_ADDRESS, cd_hex)
        decoded = decode_aggregate3_result(raw)
        if len(decoded) != len(chunk):
            raise MaxFiCallError(
                f"[{chain}] multicall3 returned {len(decoded)} results for {len(chunk)} calls"
            )
        for i, (success, ret_data) in enumerate(decoded):
            if not success:
                target = chunk[i][0]
                raise MaxFiCallError(
                    f"[{chain}] multicall3 sub-call {start + i} to {target} failed "
                    f"(reverted or otherwise unsuccessful)"
                )
            results.append(ret_data)
    return results


def multicall3_soft(chain, calls, chunk_size=None):
    """Fail-soft sibling of multicall3(): same chunking/encode/decode path,
    but never raises on a sub-call failure. Exists for callers (like the
    range-status endpoint) where one bad position must not take down every
    other position's result on the same poll — multicall3()'s own
    all-or-nothing behavior (one reverted/failed sub-call raises
    MaxFiCallError for the whole batch) is exactly wrong for that shape.

    Returns a list of (success_bool, return_data_hex_or_None) tuples in the
    same order as `calls` — one per input call, always, even on failure.
    success=False means either the sub-call itself reverted (return_data
    still present, per Multicall3's allowFailure=true semantics) or the
    surrounding chunk's rpc_call/decode failed entirely (network error,
    timeout, or a malformed aggregate3 response) — in that second case every
    call in the affected chunk gets (False, None), since the failure isn't
    attributable to any one sub-call.
    """
    if chunk_size is None:
        chunk_size = multicall_chunk_size()
    results = []
    for start in range(0, len(calls), chunk_size):
        chunk = calls[start:start + chunk_size]
        try:
            agg_calls = [(target, True, cd) for target, cd in chunk]
            cd_hex = encode_aggregate3(agg_calls)
            raw = rpc_call(chain, MULTICALL3_ADDRESS, cd_hex)
            decoded = decode_aggregate3_result(raw)
            if len(decoded) != len(chunk):
                raise MaxFiCallError(
                    f"[{chain}] multicall3_soft returned {len(decoded)} results "
                    f"for {len(chunk)} calls"
                )
        except Exception:
            results.extend([(False, None)] * len(chunk))
            continue
        for success, ret_data in decoded:
            results.append((success, ret_data))
    return results


def probe_multicall3(chain):
    """Confirm Multicall3 is actually deployed at the canonical address on
    this chain by routing a single trivial call (lens.vault()) through it.
    Raises MaxFiCallError/MaxFiRpcError on failure — Robinhood Chain's
    Multicall3 presence is inferred from observed traffic, not confirmed,
    so this must fail clearly rather than producing a confusing downstream
    error later."""
    cfg = _chain_cfg(chain)
    cd = calldata(SEL_LENS_VAULT)
    results = multicall3(chain, [(cfg["lens"], cd)], chunk_size=1)
    if len(results) != 1:
        raise MaxFiCallError(f"[{chain}] multicall3 probe returned unexpected result count")


# ── High-level contract wrappers ─────────────────────────────────────────

def get_vault(chain, use_cache=True):
    """Returns (vault_address, extra_words) — lens is a MaxFi contract, so
    this is "at_least" tier: extra words are surfaced, not rejected.

    Resolved once per chain per process and reused via _VAULT_CACHE, since the
    vault address is immutable per chain absent a protocol migration. A cache
    hit returns a NEW list copy of extra_words so a caller can never alias and
    mutate the cached value. use_cache=False skips the cache READ only — a
    successful resolution is still written to the cache regardless, since a
    fresh value is valid and refreshing a stale entry is desirable. A failed
    or zero-address resolution is never written, so the next call retries.
    """
    if use_cache and chain in _VAULT_CACHE:
        address, extra = _VAULT_CACHE[chain]
        return address, list(extra)
    print(f"[{chain}] lens.vault() resolving vault address (cache miss)")
    cfg = _chain_cfg(chain)
    raw = rpc_call(chain, cfg["lens"], calldata(SEL_LENS_VAULT))
    known, extra = _split_words(raw, 1, "at_least", f"[{chain}] lens.vault()")
    address = decode_address(known[0])
    if address != "0x0000000000000000000000000000000000000000":
        _VAULT_CACHE[chain] = (address, extra)
    return address, extra


def get_factory(chain):
    """Uniswap NPM — standardized/immutable, "exact" tier."""
    cfg = _chain_cfg(chain)
    raw = rpc_call(chain, cfg["position_manager"], calldata(SEL_NPM_FACTORY))
    known, _extra = _split_words(raw, 1, "exact", f"[{chain}] npm.factory()")
    return decode_address(known[0])


def get_user_positions(chain, wallet):
    cfg = _chain_cfg(chain)
    cd = calldata(SEL_LENS_GET_USER_POSITIONS, encode_address(wallet))
    raw = rpc_call(chain, cfg["lens"], cd)
    return decode_dynamic_uint256_array(raw)


def is_position_out_of_range(chain, token_id):
    """Returns (decoded_bool, extra_words). lens is a MaxFi contract and
    this call is confirmed (live, on Robinhood Chain) to return 2 words,
    not the 1 originally captured — "at_least" tier, extra words carried
    forward rather than dropped or rejected."""
    cfg = _chain_cfg(chain)
    cd = calldata(SEL_LENS_IS_POSITION_OUT_OF_RANGE, encode_uint256(token_id))
    raw = rpc_call(chain, cfg["lens"], cd)
    known, extra = _split_words(raw, 1, "at_least", f"[{chain}] lens.isPositionOutOfRange()")
    return decode_bool(known[0]), extra


def get_pool(chain, factory_address, token0, token1, fee):
    """Uniswap V3 factory — standardized/immutable, "exact" tier."""
    cd = calldata(SEL_FACTORY_GET_POOL, encode_address(token0), encode_address(token1), encode_uint256(fee))
    raw = rpc_call(chain, factory_address, cd)
    known, _extra = _split_words(raw, 1, "exact", f"[{chain}] factory.getPool()")
    return decode_address(known[0])


# ── Struct decoders — kept strictly separate: SEL_POSITIONS collides ────
# between the MaxFi vault and the Uniswap NPM, and the two structs are
# completely different. Sharing a decoder here would silently produce
# garbage (constraint from the task spec).

def decode_vault_position(raw_hex, expected_owner, now_ts=None):
    """Decode MaxFi vault.positions(tokenId) — 16 static words, no ABI
    offset word. Layout is HIGH CONFIDENCE BUT NOT PROVEN (unverified
    upgradeable-proxy implementation), which is why raw_words is always
    returned alongside this decode. Raises MaxFiDecodeError on wrong word
    count or an implausible decode (proxy layout may have shifted)."""
    if now_ts is None:
        now_ts = time.time()
    # vault is a MaxFi contract — "at_least" tier: our captured ABI is
    # demonstrably incomplete (see isPositionOutOfRange), so this call path
    # (never yet exercised live) is treated with the same caution. Fewer
    # than 16 words is still always an error; more are carried forward as
    # extra_words rather than rejected or silently dropped.
    known, extra = _split_words(
        raw_hex, 16, "at_least",
        "vault positions() (MaxFi's own contract — captured ABI may be incomplete)"
    )
    decoded = {
        "tokenId": word_to_int(known[0]),
        "poolId": "0x" + known[1],
        "owner": decode_address(known[2]),
        "rangeWidthBps": word_to_int(known[3]),
        "currentTickLower": to_int24(word_to_int(known[4])),
        "currentTickUpper": to_int24(word_to_int(known[5])),
        "autoSnuggleEnabled": decode_bool(known[6]),
        "autoCompoundEnabled": decode_bool(known[7]),
        "rebalanceDelay": word_to_int(known[8]),
        "outOfRangeSince": word_to_int(known[9]),
        "totalRebalances": word_to_int(known[10]),
        "lastRebalanceTime": word_to_int(known[11]),
        "depositTimestamp": word_to_int(known[12]),
        "cumulativeFees0": word_to_int(known[13]),
        "cumulativeFees1": word_to_int(known[14]),
        "cumulativeRewards": word_to_int(known[15]),
    }
    if decoded["owner"].lower() != expected_owner.lower():
        raise MaxFiDecodeError(
            f"vault positions() owner {decoded['owner']} != queried wallet {expected_owner} "
            f"(vault implementation layout may have changed)"
        )
    if not decoded["currentTickLower"] < decoded["currentTickUpper"]:
        raise MaxFiDecodeError(
            f"vault positions() currentTickLower {decoded['currentTickLower']} is not < "
            f"currentTickUpper {decoded['currentTickUpper']} "
            f"(vault implementation layout may have changed)"
        )
    if not (1600000000 <= decoded["depositTimestamp"] <= now_ts + 86400):
        raise MaxFiDecodeError(
            f"vault positions() depositTimestamp {decoded['depositTimestamp']} is implausible "
            f"(vault implementation layout may have changed)"
        )
    return decoded, known, extra


def decode_npm_position(raw_hex):
    """Decode Uniswap V3 NonfungiblePositionManager.positions(tokenId) —
    12 static words, standard layout. Standardized/immutable contract,
    "exact" tier."""
    known, _extra = _split_words(raw_hex, 12, "exact", "NPM positions()")
    decoded = {
        "nonce": word_to_int(known[0]),
        "operator": decode_address(known[1]),
        "token0": decode_address(known[2]),
        "token1": decode_address(known[3]),
        "fee": word_to_int(known[4]),
        "tickLower": to_int24(word_to_int(known[5])),
        "tickUpper": to_int24(word_to_int(known[6])),
        "liquidity": word_to_int(known[7]),
        "feeGrowthInside0LastX128": word_to_int(known[8]),
        "feeGrowthInside1LastX128": word_to_int(known[9]),
        "tokensOwed0": word_to_int(known[10]),
        "tokensOwed1": word_to_int(known[11]),
    }
    if not decoded["tickLower"] < decoded["tickUpper"]:
        raise MaxFiDecodeError(
            f"NPM positions() tickLower {decoded['tickLower']} is not < tickUpper {decoded['tickUpper']}"
        )
    return decoded, known


def decode_slot0(raw_hex):
    """Uniswap V3 pool — standardized/immutable, "exact" tier."""
    known, _extra = _split_words(raw_hex, 7, "exact", "pool slot0()")
    decoded = {
        "sqrtPriceX96": word_to_int(known[0]),
        "tick": to_int24(word_to_int(known[1])),
        "observationIndex": word_to_int(known[2]),
        "observationCardinality": word_to_int(known[3]),
        "observationCardinalityNext": word_to_int(known[4]),
        "feeProtocol": word_to_int(known[5]),
        "unlocked": decode_bool(known[6]),
    }
    return decoded, known


def decode_tick(raw_hex):
    """Uniswap V3 pool — standardized/immutable, "exact" tier."""
    known, _extra = _split_words(raw_hex, 8, "exact", "pool ticks()")
    decoded = {
        "liquidityGross": word_to_int(known[0]),
        "liquidityNet": to_int128(word_to_int(known[1])),
        "feeGrowthOutside0X128": word_to_int(known[2]),
        "feeGrowthOutside1X128": word_to_int(known[3]),
        "tickCumulativeOutside": to_int56(word_to_int(known[4])),
        "secondsPerLiquidityOutsideX128": word_to_int(known[5]),
        "secondsOutside": word_to_int(known[6]),
        "initialized": decode_bool(known[7]),
    }
    return decoded, known


def raw_words_hex(words):
    return ["0x" + w for w in words]


def stringify_ints(decoded):
    """JSON-safety pass for a decoded struct dict: every plain int becomes
    a string (uint256/uint160/uint128 all exceed 2**53 and would lose
    precision as JSON numbers — constraint applies uniformly here so a
    layout change never silently reintroduces a numeric field). Bools and
    strings (addresses, poolId) pass through unchanged."""
    out = {}
    for k, v in decoded.items():
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, int):
            out[k] = str(v)
        else:
            out[k] = v
    return out


def get_erc20_metadata_calls(token_address):
    """Calldata pair for (decimals(), symbol()) on an ERC20 — for batching
    through multicall3 alongside other calls."""
    return [
        (token_address, calldata(SEL_ERC20_DECIMALS)),
        (token_address, calldata(SEL_ERC20_SYMBOL)),
    ]


def decode_erc20_metadata(decimals_raw, symbol_raw):
    """Standard ERC20 — not a MaxFi contract, "exact" tier (not one of the
    call sites named in the Phase A.1 spec, but classified the same way
    for consistency: it's a standardized/immutable interface, same as the
    Uniswap decoders above)."""
    decimals_known, _extra = _split_words(decimals_raw, 1, "exact", "ERC20 decimals()")
    decimals = word_to_int(decimals_known[0])
    symbol = decode_string_or_bytes32(symbol_raw)
    return symbol, decimals


# ── Orchestration for the two diagnostic endpoints ──────────────────────
# Route bodies in web_portfolio.py stay thin (parse args, call in, jsonify,
# catch errors); all the actual sequencing lives here so it's covered by
# the same module the network/decode logic lives in.

def _run_stage(stage, fn, *args, **kwargs):
    """Call fn(*args, **kwargs); on a MaxFiError, tag it with which stage
    failed (if not already tagged) before re-raising, so the route handler
    can report {"stage": ...} without threading stage names through every
    call site by hand."""
    try:
        return fn(*args, **kwargs)
    except MaxFiError as e:
        if not hasattr(e, "stage"):
            e.stage = stage
        raise


def wallet_diagnostic(chain, wallet):
    """GET /api/maxfi/debug/<chain>/<wallet> payload.

    The Multicall3 probe is informational, not fatal: vault()/factory()/
    getUserPositions() below are plain single eth_calls that don't depend
    on Multicall3, so a probe failure is reported inline rather than
    aborting the whole response.
    """
    cfg = _chain_cfg(chain)

    try:
        probe_multicall3(chain)
        probe_result = "ok"
    except MaxFiError as e:
        probe_result = f"{type(e).__name__}: {e}"

    vault, vault_extra_words = _run_stage("lens_vault", get_vault, chain, use_cache=False)
    factory = _run_stage("npm_factory", get_factory, chain)
    ids = _run_stage("lens_get_user_positions", get_user_positions, chain, wallet)

    return {
        "chain": chain,
        "chain_id": cfg["chain_id"],
        "wallet": wallet,
        "multicall3_probe": probe_result,
        "lens": cfg["lens"],
        "vault": vault,
        # lens is a MaxFi contract ("at_least" tier) — surfaced per the
        # never-silently-drop-extra-words rule, empty unless vault()
        # is ever observed returning more than 1 word.
        "vault_extra_words": raw_words_hex(vault_extra_words),
        "position_manager": cfg["position_manager"],
        "factory": factory,
        "position_count": len(ids),
        "position_ids": [str(i) for i in ids],
    }


def position_diagnostic(chain, wallet, token_id):
    """GET /api/maxfi/debug/<chain>/<wallet>/<token_id> payload.

    Resolves the pool via npm.positions(tokenId) -> token0/token1/fee ->
    factory.getPool(...) — never via the vault's opaque poolId bytes32,
    whose derivation to an address is unknown (per task spec). Batches the
    pool/token state reads through multicall3 since they're independent
    once the pool address and token addresses are known.
    """
    base = wallet_diagnostic(chain, wallet)
    cfg = _chain_cfg(chain)
    vault_address = base["vault"]
    factory_address = base["factory"]

    is_out_of_range, is_out_of_range_extra = _run_stage(
        "lens_is_position_out_of_range", is_position_out_of_range, chain, token_id
    )

    npm_raw = _run_stage(
        "npm_positions",
        rpc_call,
        chain,
        cfg["position_manager"],
        calldata(SEL_POSITIONS, encode_uint256(token_id)),
    )
    npm_decoded, npm_words = _run_stage("npm_positions_decode", decode_npm_position, npm_raw)

    vault_raw = _run_stage(
        "vault_positions",
        rpc_call,
        chain,
        vault_address,
        calldata(SEL_POSITIONS, encode_uint256(token_id)),
    )
    vault_decoded, vault_words, vault_position_extra_words = _run_stage(
        "vault_positions_decode", decode_vault_position, vault_raw, wallet
    )

    pool = _run_stage(
        "pool_resolve",
        get_pool,
        chain,
        factory_address,
        npm_decoded["token0"],
        npm_decoded["token1"],
        npm_decoded["fee"],
    )

    tick_lower = vault_decoded["currentTickLower"]
    tick_upper = vault_decoded["currentTickUpper"]
    batch_calls = [
        (pool, calldata(SEL_POOL_SLOT0)),
        (pool, calldata(SEL_POOL_FEE_GROWTH_GLOBAL_0)),
        (pool, calldata(SEL_POOL_FEE_GROWTH_GLOBAL_1)),
        (pool, calldata(SEL_POOL_TICKS, encode_int24(tick_lower))),
        (pool, calldata(SEL_POOL_TICKS, encode_int24(tick_upper))),
    ] + get_erc20_metadata_calls(npm_decoded["token0"]) + get_erc20_metadata_calls(npm_decoded["token1"])

    (
        slot0_raw, feeg0_raw, feeg1_raw, ticks_lower_raw, ticks_upper_raw,
        t0_decimals_raw, t0_symbol_raw, t1_decimals_raw, t1_symbol_raw,
    ) = _run_stage("pool_state_batch", multicall3, chain, batch_calls)

    slot0_decoded, slot0_words = _run_stage("slot0_decode", decode_slot0, slot0_raw)
    ticks_lower_decoded, ticks_lower_words = _run_stage("ticks_lower_decode", decode_tick, ticks_lower_raw)
    ticks_upper_decoded, ticks_upper_words = _run_stage("ticks_upper_decode", decode_tick, ticks_upper_raw)

    fee_growth_global_0 = word_to_int(split_words(feeg0_raw)[0])
    fee_growth_global_1 = word_to_int(split_words(feeg1_raw)[0])

    token0_symbol, token0_decimals = _run_stage(
        "token0_metadata_decode", decode_erc20_metadata, t0_decimals_raw, t0_symbol_raw
    )
    token1_symbol, token1_decimals = _run_stage(
        "token1_metadata_decode", decode_erc20_metadata, t1_decimals_raw, t1_symbol_raw
    )

    price_lower = tick_to_price(tick_lower, token0_decimals, token1_decimals)
    price_upper = tick_to_price(tick_upper, token0_decimals, token1_decimals)
    price_current_from_slot0 = sqrt_price_x96_to_price(
        slot0_decoded["sqrtPriceX96"], token0_decimals, token1_decimals
    )
    pct = range_percent(tick_lower, tick_upper, token0_decimals, token1_decimals)

    block_number = _run_stage("eth_block_number", eth_block_number, chain)

    result = dict(base)
    result.update({
        "token_id": str(token_id),
        "pool": pool,
        # Shape change (Phase A.1): was a bare bool, now {decoded, extra_words}
        # — lens is a MaxFi contract ("at_least" tier) and this call is
        # confirmed live to return 2 words, not the 1 originally captured.
        "is_out_of_range": {
            "decoded": is_out_of_range,
            "extra_words": raw_words_hex(is_out_of_range_extra),
        },
        "vault_position": {
            "decoded": stringify_ints(vault_decoded),
            "raw_words": raw_words_hex(vault_words),
            "extra_words": raw_words_hex(vault_position_extra_words),
        },
        "npm_position": {
            "decoded": stringify_ints(npm_decoded),
            "raw_words": raw_words_hex(npm_words),
        },
        "slot0": {
            "decoded": stringify_ints(slot0_decoded),
            "raw_words": raw_words_hex(slot0_words),
        },
        "fee_growth_global_0_x128": str(fee_growth_global_0),
        "fee_growth_global_1_x128": str(fee_growth_global_1),
        "ticks_lower": {
            "decoded": stringify_ints(ticks_lower_decoded),
            "raw_words": raw_words_hex(ticks_lower_words),
        },
        "ticks_upper": {
            "decoded": stringify_ints(ticks_upper_decoded),
            "raw_words": raw_words_hex(ticks_upper_words),
        },
        "token0": {"address": npm_decoded["token0"], "symbol": token0_symbol, "decimals": token0_decimals},
        "token1": {"address": npm_decoded["token1"], "symbol": token1_symbol, "decimals": token1_decimals},
        "derived": {
            "price_lower": price_lower,
            "price_upper": price_upper,
            "price_current_from_slot0": price_current_from_slot0,
            "range_percent": pct,
            "range_width_bps_reported": str(vault_decoded["rangeWidthBps"]),
            "note": (
                "range_percent is tick-derived; rangeWidthBps is the requested "
                "width and will differ - this is expected"
            ),
        },
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "block_number": str(block_number),
    })
    return result


# ── Wallet position snapshot — for the position-identity matching        ──
# ── heuristic in maxfi_matching.py (Phase C prep). New helper only; no    ──
# ── existing function above this point is modified.                      ──

def get_wallet_position_snapshot(chain, wallet, chunk_size=None):
    """For every token_id in lens.getUserPositions(wallet), resolve
    array_index, token_id, and pool identity (token0_address,
    token1_address, fee_tier, pool_address via factory.getPool()).

    Returns a list of dicts matching the shape maxfi_matching.
    classify_positions() expects:
      {"array_index": int, "token_id": str, "pool_address": str,
       "token0_address": str, "token1_address": str, "fee_tier": int}

    array_index is the position's 0-based index in the order
    get_user_positions() returned it — the same array lens.
    getUserPositions() enumerates.

    Reuses decode_npm_position() unmodified for the NPM struct (no
    duplication there). The pool-address resolution reuses the exact same
    primitives get_pool() uses internally (calldata()/_split_words()/
    decode_address(), all "exact" tier) rather than calling get_pool()
    itself — get_pool() performs one un-batched rpc_call per invocation,
    which would defeat batching this needs across every position in the
    wallet. This is a deliberate, narrow exception to "reuse the existing
    helper," not a re-implementation of any decode logic.

    Fails loudly per the same constraints as the rest of this module: any
    decode failure for a single position raises immediately (via
    decode_npm_position()'s own checks, or the inline pool-address check
    below) rather than omitting that position from the snapshot — a
    missing position in a snapshot used for matching is exactly the kind
    of silent gap this feature exists to avoid.

    More RPC-heavy than the single-position debug endpoint: roughly 2
    additional eth_calls per position (npm.positions() + factory.getPool())
    on top of the fixed wallet-level cost (getUserPositions + factory()).
    Batched through multicall3, chunked at `chunk_size` (default from
    scanner_settings.json, same tunable the rest of this module uses).
    Manually-invoked diagnostic only — not wired into any scheduled scan.
    """
    cfg = _chain_cfg(chain)
    token_ids = get_user_positions(chain, wallet)
    if not token_ids:
        return []

    factory = get_factory(chain)

    positions_calls = [
        (cfg["position_manager"], calldata(SEL_POSITIONS, encode_uint256(tid)))
        for tid in token_ids
    ]
    positions_raw = multicall3(chain, positions_calls, chunk_size=chunk_size)

    npm_decoded_list = [decode_npm_position(raw)[0] for raw in positions_raw]

    pool_calls = [
        (factory, calldata(
            SEL_FACTORY_GET_POOL,
            encode_address(d["token0"]),
            encode_address(d["token1"]),
            encode_uint256(d["fee"]),
        ))
        for d in npm_decoded_list
    ]
    pool_raw = multicall3(chain, pool_calls, chunk_size=chunk_size)

    snapshot = []
    for array_index, (tid, npm_decoded, praw) in enumerate(zip(token_ids, npm_decoded_list, pool_raw)):
        # Same "exact" tier + decode_address() factory.getPool() uses
        # internally — see docstring for why get_pool() itself isn't
        # called here.
        pool_known, _extra = _split_words(
            praw, 1, "exact", f"[{chain}] factory.getPool() (token_id {tid})"
        )
        pool_address = decode_address(pool_known[0])
        snapshot.append({
            "array_index": array_index,
            "token_id": str(tid),
            "pool_address": pool_address,
            "token0_address": npm_decoded["token0"],
            "token1_address": npm_decoded["token1"],
            "fee_tier": npm_decoded["fee"],
        })
    return snapshot


# ── Narrow vault enrichment — for Phase C's newly-opened-position          ──
# ── deposit-time backfill. New function only; no existing function above  ──
# ── this point is modified.                                               ──

def get_vault_deposit_info(chain, wallet, token_id):
    """Fetch vault.positions(token_id) only and decode it with the existing
    decode_vault_position() (Phase A/A.1) — no decode logic duplicated.

    Returns {"deposit_timestamp": int, "total_rebalances": int,
    "block_number": str}.

    Deliberately narrower than position_diagnostic(): does not call the
    NPM, pool, slot0, ticks, or factory. Resolving the vault's own address
    still costs one prerequisite call (lens.vault() — the vault has no
    fixed address, per-chain or otherwise), so this is 3 sequential plain
    eth_calls total (lens.vault, vault.positions, eth_blockNumber), not
    strictly "1 RPC round trip" — but a small, fixed cost independent of
    position count, and far cheaper than the full ~14-call position
    diagnostic. See the Phase C summary for why a true single-call version
    isn't possible without threading the vault address through the caller.

    Raises MaxFiRpcError/MaxFiDecodeError on any failure — the caller
    (maxfi_orchestration.run_scan_and_persist) decides whether that's
    fatal, not this function.
    """
    vault_address, _vault_extra = get_vault(chain)
    raw = rpc_call(chain, vault_address, calldata(SEL_POSITIONS, encode_uint256(token_id)))
    decoded, _known, _extra = decode_vault_position(raw, expected_owner=wallet)
    block_number = eth_block_number(chain)
    return {
        "deposit_timestamp": decoded["depositTimestamp"],
        "total_rebalances": decoded["totalRebalances"],
        "block_number": str(block_number),
    }


# ── Range status — fast, valuation-free tick/bounds check for a ~60s poll ──
# ── New function only; no existing function above this point is modified.  ──

def fetch_range_status(chain, wallet, positions):
    """Fast, valuation-free range status for every position in `positions`.

    `positions` is a list of dicts each carrying at least `token_id` and
    `pool_address` — the caller (the /api/maxfi/range route) supplies them
    from the DB; this function does no database access of its own.

    Costs, per chain: one un-batched lens.vault() call to resolve the vault
    address (get_vault() — the vault has no fixed/configured address, same
    reason get_vault_deposit_info() above pays this), then exactly two
    batched multicall3_soft() calls — one vault.positions() per position,
    one slot0() per DISTINCT pool_address. No USD pricing, no
    factory.getPool() (pool_address is already resolved and stored by the
    scan path), no lens.isPositionOutOfRange() (in/out is derived from the
    tick data these two batches already carry).

    Uses multicall3_soft(), not multicall3(): one bad/reverting position
    must not blank every other position's range status on the same poll.

    Returns a list of dicts, one per input position, in input order:
      {"token_id", "pool_address", "tick_lower", "tick_upper",
       "current_tick", "width_pct", "in_range", "rebalance_delay",
       "out_of_range_since", "status", "reason", "range_width_bps"}
    status is "ok" when both that position's vault call and its pool's
    slot0 call succeeded AND decoded cleanly; "unavailable" otherwise, with
    every numeric/boolean field None — never a partial or guessed value.
    """
    if not positions:
        return []

    vault_address, _vault_extra = get_vault(chain)

    vault_calls = [
        (vault_address, calldata(SEL_POSITIONS, encode_uint256(int(p["token_id"]))))
        for p in positions
    ]
    vault_results = multicall3_soft(chain, vault_calls)

    vault_decoded_by_index = {}
    vault_fail_reason_by_index = {}
    for i, (success, raw) in enumerate(vault_results):
        if not success or raw is None:
            vault_fail_reason_by_index[i] = "vault_call_failed"
            continue
        try:
            decoded, _known, _extra = decode_vault_position(raw, expected_owner=wallet)
        except Exception:
            # Decode-level failure (owner mismatch, implausible timestamp,
            # short word count) — same "unavailable, not fatal" treatment
            # as an RPC-level failure. One bad position must not affect
            # any other position's result.
            vault_fail_reason_by_index[i] = "vault_decode_failed"
            continue
        vault_decoded_by_index[i] = decoded

    distinct_pools = []
    seen_pools = set()
    for p in positions:
        addr = p["pool_address"]
        if addr not in seen_pools:
            seen_pools.add(addr)
            distinct_pools.append(addr)

    slot0_calls = [(addr, calldata(SEL_POOL_SLOT0)) for addr in distinct_pools]
    slot0_results = multicall3_soft(chain, slot0_calls)

    slot0_decoded_by_pool = {}
    slot0_fail_reason_by_pool = {}
    for addr, (success, raw) in zip(distinct_pools, slot0_results):
        if not success or raw is None:
            slot0_fail_reason_by_pool[addr] = "pool_call_failed"
            continue
        try:
            decoded, _known = decode_slot0(raw)
        except Exception:
            slot0_fail_reason_by_pool[addr] = "pool_decode_failed"
            continue
        slot0_decoded_by_pool[addr] = decoded

    out = []
    for i, p in enumerate(positions):
        token_id = str(p["token_id"])
        pool_address = p["pool_address"]
        vault_decoded = vault_decoded_by_index.get(i)
        slot0_decoded = slot0_decoded_by_pool.get(pool_address)

        if vault_decoded is None or slot0_decoded is None:
            # The vault call is the per-position signal (one call per
            # token_id); the pool call is shared across every position on
            # that pool. When both sides failed, report the vault reason —
            # it points at this specific position rather than the pool it
            # happens to share with others.
            reason = vault_fail_reason_by_index.get(i)
            if reason is None:
                reason = slot0_fail_reason_by_pool.get(pool_address)
            if reason is None:
                reason = "unknown"
            out.append({
                "token_id": token_id,
                "pool_address": pool_address,
                "tick_lower": None,
                "tick_upper": None,
                "current_tick": None,
                "width_pct": None,
                "in_range": None,
                "rebalance_delay": None,
                "out_of_range_since": None,
                "status": "unavailable",
                "reason": reason,
                "range_width_bps": None,
            })
            continue

        tick_lower = vault_decoded["currentTickLower"]
        tick_upper = vault_decoded["currentTickUpper"]
        current_tick = slot0_decoded["tick"]

        # decimals0/decimals1 cancel in range_percent's ratio
        # (price_upper/price_lower) — any equal pair produces the same
        # result, so passing 18/18 here avoids a real ERC20 decimals()
        # fetch entirely. See maxfi_math.range_percent's own math: both
        # tick_to_price calls are scaled by the identical
        # 10**(decimals0-decimals1) factor, which divides out.
        width_pct = range_percent(tick_lower, tick_upper, 18, 18)

        # Uniswap V3 convention: a position's range is the half-open
        # interval [tickLower, tickUpper) — current_tick == tick_upper is
        # OUT of range, current_tick == tick_lower is IN.
        in_range = tick_lower <= current_tick < tick_upper

        out.append({
            "token_id": token_id,
            "pool_address": pool_address,
            "tick_lower": tick_lower,
            "tick_upper": tick_upper,
            "current_tick": current_tick,
            "width_pct": width_pct,
            "in_range": in_range,
            "rebalance_delay": str(vault_decoded["rebalanceDelay"]),
            "out_of_range_since": str(vault_decoded["outOfRangeSince"]),
            "status": "ok",
            "reason": None,
            # Diagnostic only — the vault's own stored width, to compare
            # against the tick-derived width_pct above. width_pct remains
            # the value to display (confirmed against MaxFi's own UI);
            # nothing should switch to range_width_bps without a human
            # decision.
            "range_width_bps": str(vault_decoded["rangeWidthBps"]),
        })
    return out
