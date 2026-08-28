"""MaxFi anchor USD price resolver — Phase D.

Deliberately independent of the existing spot-price path
(fetch_dexscreener_price / _get_dexscreener_price in web_portfolio.py): on
the spot page a transient price miss costs one row, but WETH sits on one
side of 16 of the 21 live LP positions, so the same miss there would
unprice the whole LP portfolio. The existing path also caches failures for
a full TTL, which would make that outage persist rather than self-correct.
This resolver instead:
  - never caches a miss — only successful lookups are stored
  - serves stale data on a fresh-fetch failure, with the age surfaced
  - logs every failure explicitly (asset + reason) — no bare except
  - pins USDG to 1.00, visibly, when no external price resolves

Resolves exactly three canonical assets: WETH/ETH, USDC, USDG. Bridged
WETH on Robinhood Chain has no feed of its own and is priced as ETH —
'WETH' and 'ETH' both resolve to the same canonical cache entry.
"""

import json
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

_SETTINGS_PATH = os.path.join("data", "scanner_settings.json")
_DEFAULT_TTL_SECONDS = 60

# Canonical Ethereum-mainnet contract addresses used ONLY to ask DexScreener
# for a global USD price of the canonical asset. This is NOT the per-chain
# "which address on THIS position's chain is this token" mapping — that's
# maxfi_anchor_registry in scanner_settings.json, populated separately from
# the token-census endpoint. These two are well-known, officially-documented
# addresses that never change, so they're a fixed lookup table here rather
# than a settings tunable.
#
# USDG intentionally has no entry: no canonical mainnet address for it is
# confidently known to this codebase, and the same "never invent or guess a
# contract address" rule that applies to maxfi_anchor_registry applies here.
# USDG therefore always falls through to the pinned-1.00 path below — that
# IS the expected primary path for USDG, not a rare edge case.
_CANONICAL_LOOKUP_ADDRESS = {
    "ETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",   # WETH, Ethereum mainnet
    "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC, Ethereum mainnet
}

_CANONICAL_ALIASES = {"WETH": "ETH", "ETH": "ETH", "USDC": "USDC", "USDG": "USDG"}

# In-memory cache: canonical asset -> (usd_price, fetched_at_epoch_seconds).
# Populated ONLY by a successful fetch — see module docstring.
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


def _fetch_dexscreener_usd(canonical_asset, timeout=10):
    """One independent DexScreener lookup for a canonical asset's USD
    price. Returns float or None. Never raises — every failure path is
    logged here, no bare except."""
    address = _CANONICAL_LOOKUP_ADDRESS.get(canonical_asset)
    if address is None:
        logger.warning(f"[maxfi anchor] no canonical lookup address configured for {canonical_asset}")
        return None
    try:
        resp = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{address}", timeout=timeout
        )
    except requests.RequestException as e:
        logger.warning(f"[maxfi anchor] DexScreener request failed for {canonical_asset} ({address}): {e}")
        return None
    if not resp.ok:
        logger.warning(f"[maxfi anchor] DexScreener HTTP {resp.status_code} for {canonical_asset} ({address})")
        return None
    try:
        payload = resp.json()
    except ValueError as e:
        logger.warning(f"[maxfi anchor] DexScreener returned non-JSON for {canonical_asset}: {e}")
        return None
    pairs = payload.get("pairs") or []
    for pair in pairs:
        base = pair.get("baseToken") or {}
        if str(base.get("address", "")).lower() == address.lower():
            price_usd = pair.get("priceUsd")
            if price_usd is not None:
                try:
                    return float(price_usd)
                except (TypeError, ValueError):
                    continue
    logger.warning(f"[maxfi anchor] no usable pair found for {canonical_asset} ({address})")
    return None


def resolve_anchor_price(asset_symbol, now=None, fetcher=None):
    """Resolve the USD price of a canonical anchor asset.

    asset_symbol: 'WETH', 'ETH', 'USDC', or 'USDG'.
    now: epoch seconds — injected for testability, defaults to time.time().
    fetcher: replaces the real DexScreener call for tests — a callable
    (canonical_asset: str) -> float|None. Defaults to _fetch_dexscreener_usd.

    Returns {"usd": float|None, "price_source": str, "age_seconds": int|None}
    with price_source in {'live', 'stale', 'pinned', 'unavailable'}.
    """
    now = now if now is not None else time.time()
    fetch = fetcher if fetcher is not None else _fetch_dexscreener_usd

    canonical = _CANONICAL_ALIASES.get(asset_symbol)
    if canonical is None:
        logger.warning(f"[maxfi anchor] unknown anchor asset symbol: {asset_symbol!r}")
        return {"usd": None, "price_source": "unavailable", "age_seconds": None}

    cached = _price_cache.get(canonical)
    if cached is not None:
        cached_price, cached_at = cached
        if (now - cached_at) < _ttl_seconds():
            return {"usd": cached_price, "price_source": "live", "age_seconds": int(now - cached_at)}

    if canonical == "USDG":
        price = fetch(canonical)
        if price is not None:
            _price_cache[canonical] = (price, now)
            return {"usd": price, "price_source": "live", "age_seconds": 0}
        logger.warning("[maxfi anchor] USDG has no external price available — pinning to 1.00")
        return {"usd": 1.00, "price_source": "pinned", "age_seconds": None}

    price = fetch(canonical)
    if price is not None:
        _price_cache[canonical] = (price, now)
        return {"usd": price, "price_source": "live", "age_seconds": 0}

    # Fresh fetch failed — serve stale if we have anything, however old.
    if cached is not None:
        cached_price, cached_at = cached
        age = int(now - cached_at)
        logger.warning(f"[maxfi anchor] fresh fetch failed for {canonical}, serving stale (age {age}s)")
        return {"usd": cached_price, "price_source": "stale", "age_seconds": age}

    logger.warning(f"[maxfi anchor] no price available for {canonical} (no cache, fetch failed)")
    return {"usd": None, "price_source": "unavailable", "age_seconds": None}
