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

# ── Function selectors (verified from live traffic) ─────────────────────

SEL_LENS_VAULT = "0xfbfa77cf"
SEL_LENS_GET_USER_POSITIONS = "0x2a6bc2dd"
SEL_LENS_IS_POSITION_OUT_OF_RANGE = "0x41051ef8"
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

def get_vault(chain):
    cfg = _chain_cfg(chain)
    raw = rpc_call(chain, cfg["lens"], calldata(SEL_LENS_VAULT))
    words = split_words(raw)
    if len(words) != 1:
        raise MaxFiDecodeError(f"[{chain}] lens.vault() returned {len(words)} words, expected 1")
    return decode_address(words[0])


def get_factory(chain):
    cfg = _chain_cfg(chain)
    raw = rpc_call(chain, cfg["position_manager"], calldata(SEL_NPM_FACTORY))
    words = split_words(raw)
    if len(words) != 1:
        raise MaxFiDecodeError(f"[{chain}] npm.factory() returned {len(words)} words, expected 1")
    return decode_address(words[0])


def get_user_positions(chain, wallet):
    cfg = _chain_cfg(chain)
    cd = calldata(SEL_LENS_GET_USER_POSITIONS, encode_address(wallet))
    raw = rpc_call(chain, cfg["lens"], cd)
    return decode_dynamic_uint256_array(raw)


def is_position_out_of_range(chain, token_id):
    cfg = _chain_cfg(chain)
    cd = calldata(SEL_LENS_IS_POSITION_OUT_OF_RANGE, encode_uint256(token_id))
    raw = rpc_call(chain, cfg["lens"], cd)
    words = split_words(raw)
    if len(words) != 1:
        raise MaxFiDecodeError(
            f"[{chain}] lens.isPositionOutOfRange() returned {len(words)} words, expected 1"
        )
    return decode_bool(words[0])


def get_pool(chain, factory_address, token0, token1, fee):
    cd = calldata(SEL_FACTORY_GET_POOL, encode_address(token0), encode_address(token1), encode_uint256(fee))
    raw = rpc_call(chain, factory_address, cd)
    words = split_words(raw)
    if len(words) != 1:
        raise MaxFiDecodeError(f"[{chain}] factory.getPool() returned {len(words)} words, expected 1")
    return decode_address(words[0])


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
    words = split_words(raw_hex)
    if len(words) != 16:
        raise MaxFiDecodeError(
            f"vault positions() returned {len(words)} words, expected 16 "
            f"(vault implementation layout may have changed)"
        )
    decoded = {
        "tokenId": word_to_int(words[0]),
        "poolId": "0x" + words[1],
        "owner": decode_address(words[2]),
        "rangeWidthBps": word_to_int(words[3]),
        "currentTickLower": to_int24(word_to_int(words[4])),
        "currentTickUpper": to_int24(word_to_int(words[5])),
        "autoSnuggleEnabled": decode_bool(words[6]),
        "autoCompoundEnabled": decode_bool(words[7]),
        "rebalanceDelay": word_to_int(words[8]),
        "outOfRangeSince": word_to_int(words[9]),
        "totalRebalances": word_to_int(words[10]),
        "lastRebalanceTime": word_to_int(words[11]),
        "depositTimestamp": word_to_int(words[12]),
        "cumulativeFees0": word_to_int(words[13]),
        "cumulativeFees1": word_to_int(words[14]),
        "cumulativeRewards": word_to_int(words[15]),
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
    return decoded, words


def decode_npm_position(raw_hex):
    """Decode Uniswap V3 NonfungiblePositionManager.positions(tokenId) —
    12 static words, standard layout."""
    words = split_words(raw_hex)
    if len(words) != 12:
        raise MaxFiDecodeError(f"NPM positions() returned {len(words)} words, expected 12")
    decoded = {
        "nonce": word_to_int(words[0]),
        "operator": decode_address(words[1]),
        "token0": decode_address(words[2]),
        "token1": decode_address(words[3]),
        "fee": word_to_int(words[4]),
        "tickLower": to_int24(word_to_int(words[5])),
        "tickUpper": to_int24(word_to_int(words[6])),
        "liquidity": word_to_int(words[7]),
        "feeGrowthInside0LastX128": word_to_int(words[8]),
        "feeGrowthInside1LastX128": word_to_int(words[9]),
        "tokensOwed0": word_to_int(words[10]),
        "tokensOwed1": word_to_int(words[11]),
    }
    if not decoded["tickLower"] < decoded["tickUpper"]:
        raise MaxFiDecodeError(
            f"NPM positions() tickLower {decoded['tickLower']} is not < tickUpper {decoded['tickUpper']}"
        )
    return decoded, words


def decode_slot0(raw_hex):
    words = split_words(raw_hex)
    if len(words) != 7:
        raise MaxFiDecodeError(f"pool slot0() returned {len(words)} words, expected 7")
    decoded = {
        "sqrtPriceX96": word_to_int(words[0]),
        "tick": to_int24(word_to_int(words[1])),
        "observationIndex": word_to_int(words[2]),
        "observationCardinality": word_to_int(words[3]),
        "observationCardinalityNext": word_to_int(words[4]),
        "feeProtocol": word_to_int(words[5]),
        "unlocked": decode_bool(words[6]),
    }
    return decoded, words


def decode_tick(raw_hex):
    words = split_words(raw_hex)
    if len(words) != 8:
        raise MaxFiDecodeError(f"pool ticks() returned {len(words)} words, expected 8")
    decoded = {
        "liquidityGross": word_to_int(words[0]),
        "liquidityNet": to_int128(word_to_int(words[1])),
        "feeGrowthOutside0X128": word_to_int(words[2]),
        "feeGrowthOutside1X128": word_to_int(words[3]),
        "tickCumulativeOutside": to_int56(word_to_int(words[4])),
        "secondsPerLiquidityOutsideX128": word_to_int(words[5]),
        "secondsOutside": word_to_int(words[6]),
        "initialized": decode_bool(words[7]),
    }
    return decoded, words


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
    decimals_words = split_words(decimals_raw)
    if len(decimals_words) != 1:
        raise MaxFiDecodeError(
            f"ERC20 decimals() returned {len(decimals_words)} words, expected 1"
        )
    decimals = word_to_int(decimals_words[0])
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

    vault = _run_stage("lens_vault", get_vault, chain)
    factory = _run_stage("npm_factory", get_factory, chain)
    ids = _run_stage("lens_get_user_positions", get_user_positions, chain, wallet)

    return {
        "chain": chain,
        "chain_id": cfg["chain_id"],
        "wallet": wallet,
        "multicall3_probe": probe_result,
        "lens": cfg["lens"],
        "vault": vault,
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

    is_out_of_range = _run_stage(
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
    vault_decoded, vault_words = _run_stage(
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
        "is_out_of_range": is_out_of_range,
        "vault_position": {
            "decoded": stringify_ints(vault_decoded),
            "raw_words": raw_words_hex(vault_words),
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
