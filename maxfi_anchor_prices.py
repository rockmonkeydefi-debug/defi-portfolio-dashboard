"""MaxFi anchor USD price resolver — Phase D, hardened in Phase D.2b.

Deliberately independent of the existing spot-price path
(fetch_dexscreener_price / _get_dexscreener_price in web_portfolio.py): on
the spot page a transient price miss costs one row, but WETH sits on one
side of most live LP positions, so the same miss there would unprice the
whole LP portfolio. The existing path also caches failures for a full TTL,
which would make that outage persist rather than self-correct. This
resolver instead:
  - never caches a miss — only successful, plausibility-checked lookups
    are stored
  - serves stale data on a fresh-fetch failure ONLY if that stale value
    still passes the current plausibility band — otherwise it's treated
    as a miss, never served just because it's cached
  - logs every failure explicitly (asset + reason) — no bare except
  - pins USDC and USDG to their expected values, visibly, rather than
    trusting a live lookup for either

Resolves exactly three canonical assets: WETH/ETH, USDC, USDG. Bridged
WETH on Robinhood Chain has no feed of its own and is priced as ETH —
'WETH' and 'ETH' both resolve to the same canonical cache entry.

Phase D.2a/D.2b root cause: the original single-reference DexScreener
lookup matched a returned pair on baseToken.address alone, with no
chainId filter and no liquidity tiebreak, and had no plausibility check
at all before caching whatever price came back. DexScreener's
tokens/{address} endpoint returns matches across every chain, so a
same-address token on an unrelated chain (a common occurrence, not a
coincidence) could be accepted ahead of the real pair — this is what
produced ETH priced near $0.00001277 and USDC near $0.001047 in
production. The fix below: (1) an ordered list of (chain, address)
references per asset, each request filtered to matching chainId AND
address and reduced by highest liquidity rather than array order, and
(2) a plausibility band checked BEFORE a price is ever cached or
returned as live/stale, falling through to the next reference (or to
"unavailable") on a band failure. USDC no longer resolves via live
lookup at all — it round-trips too much fee/LP noise around $1 for a
band alone to safely gate, so it is pinned like USDG, with an
independent advisory depeg check that can only log, never alter the
pinned price.
"""

import json
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

_SETTINGS_PATH = os.path.join("data", "scanner_settings.json")
_DEFAULT_TTL_SECONDS = 60

# Ordered (chain_id, address) references per canonical asset, used ONLY to
# ask DexScreener for a global USD price of the canonical asset. This is
# NOT the per-chain "which address on THIS position's chain is this token"
# mapping — that's maxfi_anchor_registry in scanner_settings.json, populated
# separately from the token-census endpoint. These are well-known,
# officially-documented addresses that never change, so they're a fixed
# lookup table here rather than a settings tunable. References are tried in
# order; a later reference is only tried if the earlier one fails to fetch
# or fails the plausibility band (see _fetch_dexscreener_usd).
#
# USDC has no entry here (Phase D.2b) — see module docstring; it resolves
# via the pinned path in _resolve_usdc, not this table.
#
# USDG intentionally has no entry: no canonical mainnet address for it is
# confidently known to this codebase, and the same "never invent or guess a
# contract address" rule that applies to maxfi_anchor_registry applies here.
# USDG therefore always falls through to the pinned-1.00 path below — that
# IS the expected primary path for USDG, not a rare edge case.
_CANONICAL_LOOKUP_REFERENCES = {
    "ETH": [
        ("base", "0x4200000000000000000000000000000000000006"),
        ("ethereum", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"),
    ],
}

# Advisory-only reference(s) for USDC's depeg check (see _resolve_usdc) — a
# separate table from _CANONICAL_LOOKUP_REFERENCES because USDC's pinned
# price can never be overridden by what these return.
_DEPEG_CHECK_REFERENCES = {
    "USDC": [("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913")],
}

# Code-side plausibility band defaults: (min_usd, max_usd). Overridable per
# asset via FLAT scanner_settings.json keys (the runtime settings UI cannot
# edit nested objects) — see _effective_price_band(). Same
# code-default-plus-optional-flat-override pattern as maxfi_anchor_registry
# in web_portfolio.py.
_PRICE_BAND_DEFAULTS = {
    "ETH": (500.0, 20000.0),
    "USDC": (0.85, 1.15),  # advisory depeg band only — see _resolve_usdc
}

_CANONICAL_ALIASES = {"WETH": "ETH", "ETH": "ETH", "USDC": "USDC", "USDG": "USDG"}

# In-memory cache: canonical asset -> (usd_price, fetched_at_epoch_seconds).
# Populated ONLY by a successful, band-passing fetch — see module docstring.
_price_cache = {}


def _setting(key, default):
    try:
        with open(_SETTINGS_PATH, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and key in data:
            return data[key]
    except Exception:
        pass
    return default


def _ttl_seconds():
    return float(_setting("maxfi_anchor_price_ttl_seconds", _DEFAULT_TTL_SECONDS))


def _effective_price_band(canonical_asset):
    """Code-side _PRICE_BAND_DEFAULTS[canonical_asset] merged with optional
    FLAT scanner_settings.json overrides
    'maxfi_price_band_<asset>_min'/'..._max'. Either key absent -> that
    side keeps its code-side default; both absent -> the default band
    unchanged. Mirrors _maxfi_effective_anchor_registry()'s
    defaults-plus-optional-override shape in web_portfolio.py, adapted to
    flat keys since this settings file's UI can't edit a nested object."""
    default_lo, default_hi = _PRICE_BAND_DEFAULTS[canonical_asset]
    lo_key = f"maxfi_price_band_{canonical_asset.lower()}_min"
    hi_key = f"maxfi_price_band_{canonical_asset.lower()}_max"
    lo = _setting(lo_key, default_lo)
    hi = _setting(hi_key, default_hi)
    return (lo, hi)


def _select_best_pair(pairs, ref_chain_id, ref_address):
    """Reduce a DexScreener 'pairs' array to a single USD price for one
    (chain, address) reference. Filters to entries matching BOTH chainId
    AND baseToken.address (a bare address match alone lets a same-address
    token on an unrelated chain through — see module docstring), then
    takes the highest-liquidity match among what's left rather than the
    first array element. Returns float or None."""
    best_pair = None
    best_liquidity = -1.0
    for pair in pairs:
        if pair.get("chainId") != ref_chain_id:
            continue
        base = pair.get("baseToken") or {}
        if str(base.get("address", "")).lower() != ref_address.lower():
            continue
        try:
            liquidity = float((pair.get("liquidity") or {}).get("usd") or 0)
        except (TypeError, ValueError):
            liquidity = 0.0
        if liquidity > best_liquidity:
            best_liquidity = liquidity
            best_pair = pair
    if best_pair is None:
        return None
    price_usd = best_pair.get("priceUsd")
    if price_usd is None:
        return None
    try:
        return float(price_usd)
    except (TypeError, ValueError):
        return None


def _fetch_reference_price(ref_chain_id, ref_address, timeout=10):
    """One DexScreener tokens/{address} call for a single (chain, address)
    reference, reduced via _select_best_pair. Returns float or None. Never
    raises — every failure path is logged here, no bare except."""
    try:
        resp = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{ref_address}", timeout=timeout
        )
    except requests.RequestException as e:
        logger.warning(f"[maxfi anchor] DexScreener request failed for {ref_chain_id}:{ref_address}: {e}")
        return None
    if not resp.ok:
        logger.warning(f"[maxfi anchor] DexScreener HTTP {resp.status_code} for {ref_chain_id}:{ref_address}")
        return None
    try:
        payload = resp.json()
    except ValueError as e:
        logger.warning(f"[maxfi anchor] DexScreener returned non-JSON for {ref_chain_id}:{ref_address}: {e}")
        return None
    pairs = payload.get("pairs") or []
    return _select_best_pair(pairs, ref_chain_id, ref_address)


def _fetch_dexscreener_usd(canonical_asset, fetcher=None, timeout=10):
    """Try each ordered reference in _CANONICAL_LOOKUP_REFERENCES for
    canonical_asset, in order, until one produces a price inside the
    current plausibility band (_effective_price_band). A reference that
    fails to fetch, or whose price fails the band, is logged and skipped
    in favor of the next one — a bad primary-reference price is never
    cached or returned.

    fetcher: replaces the real per-reference DexScreener call for tests —
    a callable (ref_chain_id: str, ref_address: str, timeout=...) ->
    float|None. Defaults to _fetch_reference_price.

    Returns (price, ref_chain_id, ref_address) on success, or None if
    every configured reference failed to fetch or failed the band (this
    includes an asset with no configured references at all, e.g. USDC or
    USDG — callers decide the pinned/unavailable fallback for those)."""
    fetch_ref = fetcher if fetcher is not None else _fetch_reference_price
    references = _CANONICAL_LOOKUP_REFERENCES.get(canonical_asset, [])
    lo, hi = _effective_price_band(canonical_asset)
    for ref_chain_id, ref_address in references:
        price = fetch_ref(ref_chain_id, ref_address, timeout=timeout)
        if price is None:
            continue
        if lo <= price <= hi:
            return (price, ref_chain_id, ref_address)
        logger.warning(
            f"[maxfi anchor] {canonical_asset} price {price} from {ref_chain_id}:{ref_address} "
            f"failed plausibility band [{lo}, {hi}] - trying next reference"
        )
    return None


def _resolve_eth(now, fetcher):
    """ETH/WETH resolution: TTL-fresh cache hit (re-validated against the
    current band — a cached value that no longer passes a since-tightened
    band is not served just because the TTL hasn't expired), else a fresh
    multi-reference fetch, else a stale cache serve gated by the same band
    check, else unavailable. The cache is written to only after a price
    has already passed the band (see _fetch_dexscreener_usd) — never
    before validation."""
    canonical = "ETH"
    lo, hi = _effective_price_band(canonical)
    cached = _price_cache.get(canonical)

    if cached is not None:
        cached_price, cached_at = cached
        if (now - cached_at) < _ttl_seconds() and lo <= cached_price <= hi:
            return {"usd": cached_price, "price_source": "live", "age_seconds": int(now - cached_at)}

    result = _fetch_dexscreener_usd(canonical, fetcher=fetcher)
    if result is not None:
        price, ref_chain_id, ref_address = result
        _price_cache[canonical] = (price, now)
        return {"usd": price, "price_source": "live", "age_seconds": 0}

    # Fresh fetch failed (every reference either didn't fetch or failed the
    # band) — serve stale ONLY if the cached value still independently
    # passes the current band; otherwise it's exactly as unavailable as no
    # cache at all.
    if cached is not None:
        cached_price, cached_at = cached
        if lo <= cached_price <= hi:
            age = int(now - cached_at)
            logger.warning(f"[maxfi anchor] fresh fetch failed for {canonical}, serving stale (age {age}s)")
            return {"usd": cached_price, "price_source": "stale", "age_seconds": age}
        logger.warning(
            f"[maxfi anchor] cached {canonical} price {cached_price} fails current "
            f"band [{lo}, {hi}] - not serving as stale"
        )

    logger.warning(f"[maxfi anchor] no price available for {canonical} (no cache, fetch failed)")
    return {"usd": None, "price_source": "unavailable", "age_seconds": None}


def _resolve_usdc(now, fetcher):
    """USDC no longer resolves via live lookup as its primary path (Phase
    D.2b) — it is pinned to 1.00 unconditionally, exactly like USDG. A
    best-effort advisory depeg check runs afterward, wrapped so nothing it
    does — including a raised exception from the fetcher — can ever alter
    the pinned result already computed above."""
    result = {"usd": 1.0, "price_source": "pinned", "age_seconds": 0}
    try:
        fetch_ref = fetcher if fetcher is not None else _fetch_reference_price
        lo, hi = _effective_price_band("USDC")
        for ref_chain_id, ref_address in _DEPEG_CHECK_REFERENCES.get("USDC", []):
            price = fetch_ref(ref_chain_id, ref_address, timeout=10)
            if price is None:
                continue
            if not (lo <= price <= hi):
                logger.warning(
                    f"[maxfi anchor] USDC depeg check: observed {price} from "
                    f"{ref_chain_id}:{ref_address} outside advisory band [{lo}, {hi}]"
                )
            break  # one best-effort observation is enough for an advisory check
    except Exception as e:
        logger.warning(f"[maxfi anchor] USDC depeg check failed (advisory only, pin unaffected): {e}")
    return result


def resolve_anchor_price(asset_symbol, now=None, fetcher=None):
    """Resolve the USD price of a canonical anchor asset.

    asset_symbol: 'WETH', 'ETH', 'USDC', or 'USDG'.
    now: epoch seconds — injected for testability, defaults to time.time().
    fetcher: replaces the real per-reference DexScreener call for tests.
    For ETH/USDC (which go through the reference-table path) this is a
    callable (ref_chain_id: str, ref_address: str, timeout=...) ->
    float|None, defaulting to _fetch_reference_price. For USDG (unchanged
    from Phase D) this is a callable (canonical_asset: str) -> float|None,
    defaulting to _fetch_dexscreener_usd — USDG has no configured
    references, so this always returns None regardless of the fetcher
    used, and USDG falls through to its pinned path exactly as before.

    Returns {"usd": float|None, "price_source": str, "age_seconds": int|None}
    with price_source in {'live', 'stale', 'pinned', 'unavailable'}.
    """
    now = now if now is not None else time.time()

    canonical = _CANONICAL_ALIASES.get(asset_symbol)
    if canonical is None:
        logger.warning(f"[maxfi anchor] unknown anchor asset symbol: {asset_symbol!r}")
        return {"usd": None, "price_source": "unavailable", "age_seconds": None}

    if canonical == "USDC":
        return _resolve_usdc(now, fetcher)

    if canonical == "ETH":
        return _resolve_eth(now, fetcher)

    # canonical == "USDG" — unchanged from Phase D: no configured
    # references, so a live lookup always misses and this pins to 1.00.
    fetch = fetcher if fetcher is not None else _fetch_dexscreener_usd
    cached = _price_cache.get(canonical)
    if cached is not None:
        cached_price, cached_at = cached
        if (now - cached_at) < _ttl_seconds():
            return {"usd": cached_price, "price_source": "live", "age_seconds": int(now - cached_at)}
    price = fetch(canonical)
    if price is not None:
        _price_cache[canonical] = (price, now)
        return {"usd": price, "price_source": "live", "age_seconds": 0}
    logger.warning("[maxfi anchor] USDG has no external price available — pinning to 1.00")
    return {"usd": 1.00, "price_source": "pinned", "age_seconds": None}
