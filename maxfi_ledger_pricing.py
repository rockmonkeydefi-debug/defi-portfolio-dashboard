"""RPC layer for MaxFi Swap-log USD pricing (HANDOFF_maxfi_ledger.md
Commit 3b.2): per-tokenId pool resolution (NPM positions() -> factory()
-> getPool()), the Robinhood WETH/USDG hop-pool fee-tier probe, ERC20
decimals() lookup, and the backward-chunked Swap-log walk this needs to
price basis/exit/claim USD without ever range-scanning a pool (HANDOFF
ruling 10).

Kept separate from maxfi_ledger_ingest.py on purpose: that module's own
docstring scopes pricing OUT of its job (RPC ingest infrastructure +
receipt-based NPM resolution for the EVENT scan, ruling 9 as amended by
3b.1.6). This module instead REUSES maxfi_ledger_ingest.py's transport
primitives (eth_call, scan_logs_chunked, MaxFiRpcError and friends) by
IMPORTING that module, rather than duplicating the HTTP plumbing a third
time - eth_call is already documented there as a kept general transport
primitive.

maxfi_client.py is NOT imported here, by explicit instruction (Commit
3b.2 hard constraint): it hardcodes ONE NPM per chain
(CHAINS[chain]["position_manager"]), which doesn't fit this workstream's
per-tokenId NPM resolution - Base has TWO NPMs (3b.1.6's finding), and
3b.1.6's receipt walk already resolves which one owns a given tokenId.
The handful of selectors/ABI-encoding helpers needed are hand-rolled
here instead, in maxfi_ledger_ingest.py's own established style
(encode_topic_address/encode_topic_uint256's pattern, just for calldata
instead of topic filters) - the selector hex constants below were
copied from maxfi_client.py's own SEL_POSITIONS/SEL_NPM_FACTORY/
SEL_FACTORY_GET_POOL/SEL_ERC20_DECIMALS by reading that file first, not
retyped from memory.

maxfi_pricing.py (a different, pre-existing module - Phase D, CURRENT-
price live valuation of open positions) is also not imported: its
value_position()/derive_usd_prices() solve a related but distinct
problem (today's price from a pool's CURRENT slot0, batched via
Multicall3) with that module's own current-price assumptions baked in.
This module's job is strictly historical - the Swap-log price AT a
specific past block, via maxfi_ledger.usd_price_at_or_before() over a
backward-walked log window - different enough in shape (a full Swap-log
walk vs. one slot0 read) that sharing an implementation would be a false
economy. maxfi_ledger.py's own pricing math (usd_price_at_or_before,
position_usd_value) is reused here, not reimplemented.
"""

import maxfi_ledger
import maxfi_ledger_ingest as mli


# ── Address / selector registry ──────────────────────────────────────────
# Copied verbatim, never re-derived at runtime - matches the CHAINS
# registry convention in maxfi_ledger_ingest.py. Values from
# HANDOFF_maxfi_ledger.md Commit 3b.2's own CONTEXT/ruling 10.

ADDR_BASE_WETH = "0x4200000000000000000000000000000000000006"
ADDR_BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
BASE_HOP_POOL = "0xd0b53d9277642d899df5c87a3966a349a798f224"

ADDR_RH_WETH = "0x0bd7d308f8e1639fab988df18a8011f41eacad73"  # aeWETH
ADDR_RH_USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"

# Commit 3b.3a - cbBTC as a SECOND hop anchor (Glenn's ruling A/A/A, Sep
# 21: narrow router, not any-token). Every currently-unpriceable lookup
# on both chains (Base 18 = cbADA/cbBTC, RH 1 = cbBTC/MSTR) has cbBTC on
# one side. Hop pools ruled by normalized liquidity from the 3b.3 step-1b
# probe: Base cbBTC/USDC 0.05%, RH cbBTC/USDG 0.05%. Orientation is NOT
# assumed from these lines - the hop step reads token0()/token1() off the
# pool (see HOP_ANCHORS' hop_pool_tokens_via_rpc).
ADDR_BASE_CBBTC = "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf"  # 8 dec
BASE_CBBTC_HOP_POOL = "0xfbb6eed8e7aa03b138556eedaf5d271a5e1e43ef"  # cbBTC/USDC 500
ADDR_RH_CBBTC = "0xcec185eb182c47d1ba1efc84e6959e18cd620be4"  # 8 dec
RH_CBBTC_HOP_POOL = "0x9664d869540e9d0a76f12c6623946c6d5d201e09"  # cbBTC/USDG 500

# Ruling B: RH's hop pool is resolved programmatically, never hardcoded -
# probe these fee tiers in order, first non-zero getPool() result wins.
RH_HOP_POOL_FEE_TIERS = (100, 500, 3000, 10000)

# Selectors confirmed against maxfi_client.py's own SEL_POSITIONS/
# SEL_NPM_FACTORY/SEL_FACTORY_GET_POOL/SEL_ERC20_DECIMALS before copying.
SEL_NPM_POSITIONS = "0x99fbab88"
SEL_NPM_FACTORY = "0xc45a0155"
SEL_FACTORY_GET_POOL = "0x1698ee82"
SEL_ERC20_DECIMALS = "0x313ce567"

# Commit 3b.2.1 - token0()/token1() on the pool contract itself (standard,
# immutable Uniswap V3 pool interface). Computed via
# Web3.keccak(text="token0()")/"token1()", never guessed - the pool
# contract never burns, unlike an NFT position, which is why this path
# exists at all (see maxfi_ledger_ingest.TOPIC_POOL_MINT's own comment).
SEL_POOL_TOKEN0 = "0x0dfe1681"
SEL_POOL_TOKEN1 = "0xd21220a7"

_ZERO_ADDRESS = "0x" + "0" * 40


def _encode_address(address):
    h = address[2:] if address.startswith(("0x", "0X")) else address
    return h.lower().zfill(64)


def _encode_uint256(value):
    return format(int(value), "x").zfill(64)


def _calldata(selector, *encoded_words):
    sel = selector[2:] if selector.startswith(("0x", "0X")) else selector
    return "0x" + sel + "".join(encoded_words)


def _decode_address_word(raw_hex):
    body = raw_hex[2:] if raw_hex.startswith("0x") else raw_hex
    if len(body) < 64:
        return None
    return "0x" + body[:64][-40:].lower()


def _decode_uint_word(raw_hex):
    body = raw_hex[2:] if raw_hex.startswith("0x") else raw_hex
    if len(body) < 64:
        return None
    return int(body[:64], 16)


def _sort_pair(addr_a, addr_b):
    """(token0, token1) by address value - the Uniswap V3 ordering
    invariant (lower address is always token0). Used for the two KNOWN
    hop-pool pairs (Base WETH/USDC, RH aeWETH/USDG), where both
    constituent addresses are already known from the fixed registry
    above, so no token0()/token1() RPC call is needed to get this right.
    """
    a, b = addr_a.lower(), addr_b.lower()
    return (a, b) if int(a, 16) < int(b, 16) else (b, a)


# ── Per-process caches ────────────────────────────────────────────────────
# Same write-only-on-success contract as maxfi_client._VAULT_CACHE and
# (before its 3b.1.6 removal) maxfi_ledger_ingest._NPM_RESOLUTION_CACHE:
# cleared on process restart, per-worker under gunicorn, never written on
# a failed lookup so the next call retries.

_DECIMALS_CACHE = {}
_POOL_RESOLUTION_CACHE = {}
_HOP_POOL_CACHE = {}
_POOL_TOKENS_CACHE = {}


def _bump(_counter):
    """Commit 3b.2.3 - increments the caller's call-count accumulator (a
    one-element list, so it's mutated in place across every helper a
    single token0_token1_usd_at_block() invocation touches) once per
    eth_call/eth_get_logs actually issued - never on a cache hit, and
    regardless of whether the call itself then succeeds or raises (an
    attempted RPC call still counts against the budget). A no-op when
    `_counter` is None - every caller below defaults it to None, so
    direct test calls (none of which pass a counter) are unaffected."""
    if _counter is not None:
        _counter[0] += 1


def get_decimals(chain, token_address, _counter=None):
    """ERC20 decimals() - cached per (chain, token_address), an immutable
    on-chain value. Returns None (never raises) on any RPC failure or a
    malformed result - soft-isolated, the 3b.1.3 precedent this whole
    pricing path follows."""
    token_address = token_address.lower()
    key = (chain, token_address)
    if key in _DECIMALS_CACHE:
        return _DECIMALS_CACHE[key]
    _bump(_counter)
    try:
        raw = mli.eth_call(chain, token_address, _calldata(SEL_ERC20_DECIMALS))
    except mli.MaxFiRpcError:
        return None
    decimals = _decode_uint_word(raw)
    if decimals is None:
        return None
    _DECIMALS_CACHE[key] = decimals
    return decimals


def get_npm_position_tokens(chain, npm_address, token_id, _counter=None):
    """npm.positions(tokenId) -> {token0, token1, fee} only - the other 9
    words of the real 12-word NPM positions() struct (nonce/operator/
    ticks/liquidity/feeGrowth/tokensOwed - see maxfi_client.
    decode_npm_position for the full layout this mirrors) are irrelevant
    to pool resolution and not decoded here. Returns None (never raises)
    on any RPC failure or a short/malformed result."""
    _bump(_counter)
    try:
        raw = mli.eth_call(chain, npm_address, _calldata(SEL_NPM_POSITIONS, _encode_uint256(token_id)))
    except mli.MaxFiRpcError:
        return None
    body = raw[2:] if raw.startswith("0x") else raw
    if len(body) < 64 * 5:
        return None
    words = [body[i:i + 64] for i in range(0, 64 * 5, 64)]
    token0 = _decode_address_word(words[2])
    token1 = _decode_address_word(words[3])
    fee = _decode_uint_word(words[4])
    if token0 is None or token1 is None or fee is None:
        return None
    return {"token0": token0, "token1": token1, "fee": fee}


def get_factory(chain, npm_address, _counter=None):
    """npm.factory() - the Uniswap V3 factory address for whichever NPM
    `npm_address` is. Returns None (never raises) on any RPC failure."""
    _bump(_counter)
    try:
        raw = mli.eth_call(chain, npm_address, _calldata(SEL_NPM_FACTORY))
    except mli.MaxFiRpcError:
        return None
    return _decode_address_word(raw)


def get_pool(chain, factory_address, token0, token1, fee, _counter=None):
    """factory.getPool(token0, token1, fee) - returns the pool address,
    or the zero address if that (token0, token1, fee) combination has no
    pool (a real, non-error result - a fee-tier probe needs to tell this
    apart from an RPC failure). Returns None only on an actual RPC
    failure, never on a clean zero-address result."""
    _bump(_counter)
    try:
        raw = mli.eth_call(
            chain, factory_address,
            _calldata(SEL_FACTORY_GET_POOL, _encode_address(token0), _encode_address(token1), _encode_uint256(fee)),
        )
    except mli.MaxFiRpcError:
        return None
    return _decode_address_word(raw)


def get_pool_tokens(chain, pool_address, _counter=None):
    """pool.token0()/pool.token1() - cached per (chain, pool_address), an
    immutable on-chain value once a pool exists. Returns None (never
    raises) on any RPC failure. Commit 3b.2.1: the pool-address-known
    path (a mint receipt's own Mint log gives the pool directly) uses
    this instead of npm.positions() at "latest", which reverts for a
    burned NFT - a pool contract itself never burns."""
    pool_address = pool_address.lower()
    key = (chain, pool_address)
    if key in _POOL_TOKENS_CACHE:
        return _POOL_TOKENS_CACHE[key]
    _bump(_counter)
    _bump(_counter)
    try:
        token0_raw = mli.eth_call(chain, pool_address, _calldata(SEL_POOL_TOKEN0))
        token1_raw = mli.eth_call(chain, pool_address, _calldata(SEL_POOL_TOKEN1))
    except mli.MaxFiRpcError:
        return None
    token0 = _decode_address_word(token0_raw)
    token1 = _decode_address_word(token1_raw)
    if token0 is None or token1 is None:
        return None
    result = {"token0": token0, "token1": token1}
    _POOL_TOKENS_CACHE[key] = result
    return result


def resolve_position_pool(chain, npm_address, token_id, pool_address=None, _counter=None):
    """Per-tokenId pool resolution (HANDOFF_maxfi_ledger.md Commit 3b.2,
    amended 3b.2.1). Two paths:

    - `pool_address` GIVEN (Commit 3b.2.1 - resolved from the mint/
      rebalance receipt's own pool Mint log by maxfi_ledger_ingest.
      scan_chain(), TOPIC_POOL_MINT's own comment): resolves token0/
      token1 via get_pool_tokens() directly on the pool contract - NO
      npm.positions()/factory()/getPool() call at all. This is the
      preferred path: npm.positions() reads a POSITION at "latest",
      which REVERTS once that NFT is burned (rebalanced away or
      withdrawn) - spec error #25, the root cause of 49 of 50 Base
      positions pricing as unpriced-with-no-reason in the first post-
      3b.2 dry_run. A pool contract itself never burns.
    - `pool_address` NOT given: falls back to the original npm.
      positions() -> factory() -> getPool() pattern (maxfi_client.
      position_diagnostic()'s proven shape, generalized to a per-tokenId
      NPM instead of one hardcoded NPM per chain - Base has TWO NPMs,
      3b.1.6's finding). Still valid for a LIVE NFT; kept, not deleted.

    Cached per (chain, token_id) regardless of which path resolved it -
    a minted position's token0/token1/pool/decimals never change once
    resolved. Returns (pool_dict_or_None, reason_or_None) - reason is
    always None on a cache hit or full success; on failure, one of
    "pool_tokens_unresolved" (token0/token1 lookup failed - either
    get_pool_tokens() on the mint-receipt path, or get_npm_position_
    tokens() on the npm_positions path), "pool_unresolved" (tokens/fee
    known but factory()/getPool() failed or returned the zero address -
    only possible on the npm_positions path, since the mint-receipt path
    is handed the pool address directly), "decimals_unresolved". Never
    raises - soft-isolated, the 3b.1.3 precedent: one position's pricing
    failure must never abort a batch.

    Returns {"pool_address", "token0", "token1", "fee", "decimals0",
    "decimals1", "pool_source": "mint_receipt" | "npm_positions"} on
    success ("fee" is None on the mint_receipt path - a pool's Mint log
    carries no fee tier, only npm.positions() does, and nothing in this
    module's pricing math needs it).
    """
    key = (chain, str(token_id))
    if key in _POOL_RESOLUTION_CACHE:
        return _POOL_RESOLUTION_CACHE[key], None

    if pool_address is not None:
        tokens = get_pool_tokens(chain, pool_address, _counter=_counter)
        if tokens is None:
            return None, "pool_tokens_unresolved"
        decimals0 = get_decimals(chain, tokens["token0"], _counter=_counter)
        decimals1 = get_decimals(chain, tokens["token1"], _counter=_counter)
        if decimals0 is None or decimals1 is None:
            return None, "decimals_unresolved"
        result = {
            "pool_address": pool_address.lower(),
            "token0": tokens["token0"],
            "token1": tokens["token1"],
            "fee": None,
            "decimals0": decimals0,
            "decimals1": decimals1,
            "pool_source": "mint_receipt",
        }
        _POOL_RESOLUTION_CACHE[key] = result
        return result, None

    tokens = get_npm_position_tokens(chain, npm_address, token_id, _counter=_counter)
    if tokens is None:
        return None, "pool_tokens_unresolved"
    factory_address = get_factory(chain, npm_address, _counter=_counter)
    if factory_address is None or factory_address == _ZERO_ADDRESS:
        return None, "pool_unresolved"
    resolved_pool_address = get_pool(
        chain, factory_address, tokens["token0"], tokens["token1"], tokens["fee"], _counter=_counter
    )
    if resolved_pool_address is None or resolved_pool_address == _ZERO_ADDRESS:
        return None, "pool_unresolved"
    decimals0 = get_decimals(chain, tokens["token0"], _counter=_counter)
    decimals1 = get_decimals(chain, tokens["token1"], _counter=_counter)
    if decimals0 is None or decimals1 is None:
        return None, "decimals_unresolved"

    result = {
        "pool_address": resolved_pool_address,
        "token0": tokens["token0"],
        "token1": tokens["token1"],
        "fee": tokens["fee"],
        "decimals0": decimals0,
        "decimals1": decimals1,
        "pool_source": "npm_positions",
    }
    _POOL_RESOLUTION_CACHE[key] = result
    return result, None


def resolve_rh_hop_pool(chain, npm_address, _counter=None):
    """Robinhood WETH/USDG hop pool, resolved programmatically (ruling
    B): probes factory.getPool(aeWETH, USDG, fee) for fee in
    RH_HOP_POOL_FEE_TIERS, first non-zero address wins. Cached - the
    whole chain shares one hop pool. Returns None if the factory lookup
    itself fails, or if ALL FOUR fee tiers come back the zero address -
    per ruling B, that exact case is the one condition this function's
    caller must STOP and report on rather than guessing a fifth fee tier
    or falling back to a guessed address.
    """
    if chain in _HOP_POOL_CACHE:
        return _HOP_POOL_CACHE[chain]

    factory_address = get_factory(chain, npm_address, _counter=_counter)
    if factory_address is None or factory_address == _ZERO_ADDRESS:
        return None

    for fee in RH_HOP_POOL_FEE_TIERS:
        pool_address = get_pool(chain, factory_address, ADDR_RH_WETH, ADDR_RH_USDG, fee, _counter=_counter)
        if pool_address is not None and pool_address != _ZERO_ADDRESS:
            _HOP_POOL_CACHE[chain] = pool_address
            return pool_address
    return None


# ── Backward-chunked Swap-log walk (never a full range-scan - ruling 10) ──

# 10,000-block windows, capped at 30 - a bit under 300,000 blocks (~a week
# of Base's ~2s blocks) of total backward reach per price lookup, so one
# unpriceable/inactive pool can never silently consume unbounded RPC
# calls. Both are caller-overridable, not load-bearing constants elsewhere.
DEFAULT_SWAP_WALK_WINDOW = 10_000
DEFAULT_SWAP_WALK_MAX_WINDOWS = 30

# Commit 3b.2.3 - Robinhood's own per-block reach needs a much wider
# window than Base's to cover the same ~week of history within
# max_windows=30 (ruling B's own evidence, HANDOFF). Keyed by chain;
# DEFAULT_SWAP_WALK_WINDOW is the fallback for any chain not listed
# here. An explicit `window=` argument always wins over this lookup -
# swap_logs_backward only consults it when the caller passes none.
#
# Commit 3b.2.4 - Robinhood 200k -> 2M: ~19 RPC calls per lookup at 200k
# (Sep 20 evidence - quiet pools step through many ~5.5h windows before
# the first Swap); 2M matches maxfi_ledger_ingest.DEFAULT_CHUNK_SIZE so
# one window = one call, and oversize ranges self-halve inside
# scan_logs_chunked. max_windows stays 30 (~60M blocks, ~70 days of
# reach on RH). Base is unchanged.
SWAP_WALK_WINDOW_BLOCKS = {"base": 10_000, "robinhood": 2_000_000}

# Commit 3b.2.5 - the WETH/stable HOP pool gets its own, much smaller
# window: the hop pool is the most active pool on the chain; a
# chain-sized window returns tens of thousands of logs per lookup (Sep
# 20 stall - a 1-lookup dry_run ran 30+ min after 3b.2.4 widened RH to
# 2M). ~1h on Base, ~33 min on RH per window; with max_windows=30 the
# reach is ~30h / ~16h. A hop pool with no Swap in that span is not a
# usable price anchor and fails as "hop_price_unavailable" - never
# widened, never retried with the position-pool window.
HOP_POOL_WALK_WINDOW_BLOCKS = {"base": 2_000, "robinhood": 20_000}

# Commit 3b.3a - per-(chain, anchor symbol) hop-walk window. Kept as a
# SIBLING of HOP_POOL_WALK_WINDOW_BLOCKS rather than nesting it: that
# constant is indexed by chain by existing tests and stays the single
# source of the WETH values (referenced here, not re-typed). cbBTC/stable
# pools are far quieter than WETH/stable, so cbBTC gets 10x [Inference -
# sized from the step-1b probe's liquidity, not from measured swap
# density; revisit if hop_price_unavailable shows up on a cbBTC hop].
# max_windows is unchanged; no wider-window fallback (3b.2.5 precedent).
HOP_ANCHOR_WALK_WINDOW_BLOCKS = {
    ("base", "WETH"): HOP_POOL_WALK_WINDOW_BLOCKS["base"],
    ("robinhood", "WETH"): HOP_POOL_WALK_WINDOW_BLOCKS["robinhood"],
    ("base", "cbBTC"): 10 * HOP_POOL_WALK_WINDOW_BLOCKS["base"],
    ("robinhood", "cbBTC"): 10 * HOP_POOL_WALK_WINDOW_BLOCKS["robinhood"],
}

# Commit 3b.3a - hop-anchor registry. ONE hop implementation, driven by
# this table: a position pool with a stable side prices directly; else
# the FIRST entry here whose token is on either side is the hop anchor
# (order = precedence, WETH first); else unpriceable_pair. Addresses
# reference the constants above - never re-typed. hop_pool None means
# "resolve at runtime via resolve_rh_hop_pool()", exactly as RH WETH
# works today. hop_pool_tokens_via_rpc: the WETH entries keep today's
# RPC-free _sort_pair orientation (the V3 address-order invariant) so WETH
# pricing stays byte-identical; the cbBTC entries read token0()/token1()
# off the ruled pool via get_pool_tokens() - which also VERIFIES the pool
# really holds {cbBTC, stable} (a mis-ruled address fails as
# hop_pool_mismatch instead of silently mis-pricing a money path).
HOP_ANCHORS = {
    "base": [
        {"symbol": "WETH", "token": ADDR_BASE_WETH, "hop_pool": BASE_HOP_POOL,
         "stable": ADDR_BASE_USDC, "hop_pool_tokens_via_rpc": False},
        {"symbol": "cbBTC", "token": ADDR_BASE_CBBTC, "hop_pool": BASE_CBBTC_HOP_POOL,
         "stable": ADDR_BASE_USDC, "hop_pool_tokens_via_rpc": True},
    ],
    "robinhood": [
        {"symbol": "WETH", "token": ADDR_RH_WETH, "hop_pool": None,
         "stable": ADDR_RH_USDG, "hop_pool_tokens_via_rpc": False},
        {"symbol": "cbBTC", "token": ADDR_RH_CBBTC, "hop_pool": RH_CBBTC_HOP_POOL,
         "stable": ADDR_RH_USDG, "hop_pool_tokens_via_rpc": True},
    ],
}


def swap_logs_backward(chain, pool_address, target_block, window=None,
                        max_windows=DEFAULT_SWAP_WALK_MAX_WINDOWS):
    """Backward-chunked walk for Swap logs at-or-before target_block,
    stopping at the first window with ANY Swap log - never a full
    range-scan of the pool's history (HANDOFF ruling 10, explicit).
    Reuses maxfi_ledger_ingest.scan_logs_chunked() for each window's own
    fetch, so a window that's itself oversized (a very dense pool) or hit
    with a 429 gets the SAME halving/retry backoff eth_get_logs's other
    callers already get - not reimplemented here.

    `window` (Commit 3b.2.3): None (the default) resolves to `chain`'s
    own SWAP_WALK_WINDOW_BLOCKS entry (falling back to
    DEFAULT_SWAP_WALK_WINDOW for an unlisted chain) - an explicit value
    always overrides that lookup, unchanged from before this commit.

    Capped at `max_windows` windows - once exhausted with no Swap found,
    returns ([], stats) with stats["found_at_block"] None, the same "no
    price available" shape as maxfi_ledger.price_at_or_before() returning
    None, never an exception (an actual MaxFiRpcError from a window's own
    fetch DOES propagate, uncaught - this function does no soft
    isolation of its own; the caller's per-position try/except is where
    that happens, the 3b.1.3 precedent).

    Returns (swap_logs, stats) - swap_logs is the one window's raw Swap
    logs, ALREADY adapted via maxfi_ledger_ingest.rpc_log_to_etherscan_
    shape() (through that module's own _adapt_rpc_logs, its own per-call
    {block_number: timestamp_hex} cache) into decode_log()-ready shape -
    a raw eth_getLogs record handed to decode_log() unadapted KeyErrors
    on "timeStamp" (hotfix 3b.1.2's own finding, the exact failure mode
    this adaptation step exists to prevent) - or [] if no Swap was found,
    anywhere within the cap. stats is {"windows_checked", "calls",
    "found_at_block"} - found_at_block (Commit 3b.2.1 fix: was the
    window's own START block, a cosmetic bug - now the ACTUAL block of
    the most-recent Swap this window returned, i.e. the one
    price_at_or_before() will go on to select) is None until a Swap is
    found.
    """
    if window is None:
        window = SWAP_WALK_WINDOW_BLOCKS.get(chain, DEFAULT_SWAP_WALK_WINDOW)
    stats = {"windows_checked": 0, "calls": 0, "found_at_block": None}
    timestamp_cache = {}
    window_to = target_block
    for _ in range(max_windows):
        if window_to < 0:
            break
        window_from = max(window_to - window + 1, 0)
        logs, chunk_stats = mli.scan_logs_chunked(
            chain, pool_address, [[maxfi_ledger.TOPIC_SWAP]], window_from, window_to
        )
        stats["windows_checked"] += 1
        stats["calls"] += chunk_stats["calls"]
        if logs:
            logs = mli._adapt_rpc_logs(chain, logs, timestamp_cache)
            stats["found_at_block"] = max(int(log["blockNumber"], 16) for log in logs)
            return logs, stats
        if window_from == 0:
            break
        window_to = window_from - 1
    return [], stats


# ── Orchestration: one position's token0_usd/token1_usd at a block ───────

_STABLE_BY_CHAIN = {"base": ADDR_BASE_USDC, "robinhood": ADDR_RH_USDG}


def _hop_anchor_for(chain, token0, token1):
    """The first HOP_ANCHORS entry for `chain` whose token is on either
    side of the position pool (registry order = precedence), or None."""
    for anchor in HOP_ANCHORS.get(chain, ()):
        if anchor["token"] in (token0, token1):
            return anchor
    return None


def _hop_pool_and_pair(chain, npm_address, anchor, _counter=None):
    """(hop_pool_address, anchor_token, stable_address) for one registry
    `anchor`, or None if unavailable. A fixed hop_pool is returned as-is;
    hop_pool None (RH WETH) resolves via resolve_rh_hop_pool() exactly as
    before Commit 3b.3a."""
    if anchor["hop_pool"] is not None:
        return anchor["hop_pool"], anchor["token"], anchor["stable"]
    hop_pool = resolve_rh_hop_pool(chain, npm_address, _counter=_counter)
    if hop_pool is None:
        return None
    return hop_pool, anchor["token"], anchor["stable"]


def _hop_walk_window(chain, anchor_symbol):
    return HOP_ANCHOR_WALK_WINDOW_BLOCKS.get(
        (chain, anchor_symbol), HOP_POOL_WALK_WINDOW_BLOCKS.get(chain, DEFAULT_SWAP_WALK_WINDOW)
    )


def token0_token1_usd_at_block(chain, npm_address, token_id, target_block, pool=None, pool_address=None):
    """Resolve token0_usd/token1_usd for ONE position's own pool at
    target_block - direct-stable (the position's pool has USDC/USDG on
    one side) or one hop via WETH/aeWETH (neither side is a direct
    stable, but one side is WETH-like) - per this module's own docstring.
    A pool with NEITHER a direct stable NOR a WETH-like side has no
    priced path here (a second hop is out of scope) and returns
    (None, None, pool, stats) like any other pricing failure.

    `pool` lets a caller pass in an ALREADY-resolved
    resolve_position_pool() result (e.g. basis and exit for the SAME
    position, priced at two different blocks, need only resolve the pool
    once) - resolved fresh via resolve_position_pool() if omitted.
    `pool_address` (Commit 3b.2.1, ignored when `pool` is given) is
    forwarded to resolve_position_pool() - the mint-receipt path, never
    npm.positions() at "latest" (see that function's own docstring for
    why that matters).

    Returns (token0_usd, token1_usd, pool_resolution, stats) -
    pool_resolution is resolve_position_pool()'s own dict (the caller
    needs pool_address/decimals for its own DB write) or None if pool
    resolution itself failed; stats is {"swap_walk_calls",
    "windows_checked", "reason", "hop_anchor", "rpc_calls"}, accumulated
    across every Swap-log walk this call made (one for a direct price,
    two for a hop), for the route's own RPC/failure accounting. "reason"
    (Commit 3b.2.1) is None on success, else one of
    resolve_position_pool()'s own reasons ("pool_tokens_unresolved"/
    "pool_unresolved"/"decimals_unresolved"), "hop_pool_unresolved" (the
    RH hop-pool probe failed), "hop_pool_tokens_unresolved" /
    "hop_pool_mismatch" (Commit 3b.3a, cbBTC entries only: the ruled hop
    pool's token0()/token1() could not be read, or don't match
    {anchor, stable}), "no_swap_in_reach" (the POSITION pool's backward
    walk found nothing within its cap), "hop_price_unavailable" (Commit
    3b.2.5: the HOP pool's own short walk found no Swap; never retried
    with a wider window), or "unpriceable_pair" (Commit 3b.3a: neither
    side is a stable NOR any HOP_ANCHORS entry - WETH or cbBTC).
    "hop_anchor" (Commit 3b.3a) is the registry symbol the hop step used
    ("WETH"/"cbBTC"), None on a direct price, a resolution failure, or
    unpriceable_pair. "rpc_calls" (Commit 3b.2.3) is EVERY eth_call/
    eth_get_logs this invocation actually caused - swap_walk_calls PLUS
    every pool-token/decimals/hop-pool resolution call, counting only
    calls actually made (a cache hit anywhere along the way costs 0).
    Never raises: any failure anywhere returns (None, None,
    pool_resolution_or_None, stats).
    """
    _counter = [0]
    token0_usd, token1_usd, pool_result, stats = _token0_token1_usd_at_block_impl(
        chain, npm_address, token_id, target_block, pool, pool_address, _counter
    )
    stats["rpc_calls"] = _counter[0] + stats["swap_walk_calls"]
    return token0_usd, token1_usd, pool_result, stats


def _token0_token1_usd_at_block_impl(chain, npm_address, token_id, target_block, pool, pool_address, _counter):
    """token0_token1_usd_at_block()'s own body, factored out so the
    public function's single exit point (above) can add up "rpc_calls"
    once, after every early-return path below has already run - see that
    function's own docstring for the full contract."""
    stats = {"swap_walk_calls": 0, "windows_checked": 0, "reason": None, "hop_anchor": None}
    if pool is None:
        pool, reason = resolve_position_pool(
            chain, npm_address, token_id, pool_address=pool_address, _counter=_counter
        )
        if pool is None:
            stats["reason"] = reason
            return None, None, None, stats

    token0, token1 = pool["token0"].lower(), pool["token1"].lower()
    stable = _STABLE_BY_CHAIN.get(chain)

    if stable is not None and (token0 == stable or token1 == stable):
        anchor_is_token1 = (token1 == stable)
        logs, walk_stats = swap_logs_backward(chain, pool["pool_address"], target_block)
        stats["swap_walk_calls"] += walk_stats["calls"]
        stats["windows_checked"] += walk_stats["windows_checked"]
        other_usd = maxfi_ledger.usd_price_at_or_before(
            logs, target_block, pool["decimals0"], pool["decimals1"], anchor_is_token1, 1.0
        )
        if other_usd is None:
            stats["reason"] = "no_swap_in_reach"
            return None, None, pool, stats
        token0_usd = 1.0 if token0 == stable else other_usd
        token1_usd = 1.0 if token1 == stable else other_usd
        return token0_usd, token1_usd, pool, stats

    # Commit 3b.3a: ONE registry-driven hop step (HOP_ANCHORS) - WETH and
    # cbBTC share it; the WETH entries reproduce the pre-3b.3a path
    # byte-for-byte (same pool source, same _sort_pair orientation, same
    # window, same reasons, same RPC count).
    anchor = _hop_anchor_for(chain, token0, token1)
    if anchor is not None:
        stats["hop_anchor"] = anchor["symbol"]
        hop = _hop_pool_and_pair(chain, npm_address, anchor, _counter=_counter)
        if hop is None:
            stats["reason"] = "hop_pool_unresolved"
            return None, None, pool, stats
        hop_pool_address, anchor_addr, stable_addr = hop
        if anchor["hop_pool_tokens_via_rpc"]:
            hop_tokens = get_pool_tokens(chain, hop_pool_address, _counter=_counter)
            if hop_tokens is None:
                stats["reason"] = "hop_pool_tokens_unresolved"
                return None, None, pool, stats
            hop_token0, hop_token1 = hop_tokens["token0"].lower(), hop_tokens["token1"].lower()
            if {hop_token0, hop_token1} != {anchor_addr, stable_addr}:
                stats["reason"] = "hop_pool_mismatch"
                return None, None, pool, stats
        else:
            hop_token0, hop_token1 = _sort_pair(anchor_addr, stable_addr)
        hop_decimals0 = get_decimals(chain, hop_token0, _counter=_counter)
        hop_decimals1 = get_decimals(chain, hop_token1, _counter=_counter)
        if hop_decimals0 is None or hop_decimals1 is None:
            stats["reason"] = "decimals_unresolved"
            return None, None, pool, stats

        # Commit 3b.2.5: the hop pool walks with its own small window, NOT
        # the chain's position-pool window (2M blocks on RH's busiest pool
        # = tens of thousands of Swap logs per lookup, the Sep 20 stall);
        # Commit 3b.3a: per-anchor, see HOP_ANCHOR_WALK_WINDOW_BLOCKS.
        hop_logs, hop_walk_stats = swap_logs_backward(
            chain, hop_pool_address, target_block,
            window=_hop_walk_window(chain, anchor["symbol"]),
        )
        stats["swap_walk_calls"] += hop_walk_stats["calls"]
        stats["windows_checked"] += hop_walk_stats["windows_checked"]
        hop_stable_is_token1 = (hop_token1 == stable_addr)
        anchor_usd = maxfi_ledger.usd_price_at_or_before(
            hop_logs, target_block, hop_decimals0, hop_decimals1, hop_stable_is_token1, 1.0
        )
        if anchor_usd is None:
            stats["reason"] = "hop_price_unavailable"
            return None, None, pool, stats

        position_anchor_is_token1 = (token1 == anchor_addr)
        logs, walk_stats = swap_logs_backward(chain, pool["pool_address"], target_block)
        stats["swap_walk_calls"] += walk_stats["calls"]
        stats["windows_checked"] += walk_stats["windows_checked"]
        other_usd = maxfi_ledger.usd_price_at_or_before(
            logs, target_block, pool["decimals0"], pool["decimals1"], position_anchor_is_token1, anchor_usd
        )
        if other_usd is None:
            stats["reason"] = "no_swap_in_reach"
            return None, None, pool, stats
        token0_usd = anchor_usd if token0 == anchor_addr else other_usd
        token1_usd = anchor_usd if token1 == anchor_addr else other_usd
        return token0_usd, token1_usd, pool, stats

    stats["reason"] = "unpriceable_pair"
    return None, None, pool, stats
