"""GeckoTerminal historical backfill (GT backfill workstream, commit 2 of 3).

Pure fetch/compute helpers with no database or Flask dependency - the
resumable backfill route lives in web_portfolio.py and imports this module.
Kept separate so every network-touching function has exactly one seam
(fetch_pool_ohlcv) that tests monkeypatch, with no real HTTP call reachable
from a test run.

Network slugs (GT_NETWORK_BY_CHAIN) are ASSUMED to be 'robinhood' and
'base' - unverified against GeckoTerminal's actual registry. A wrong slug
surfaces as a GTError (HTTP 404, most likely) on every unit for that chain,
never a raise out of the route - see fetch_pool_ohlcv's docstring.
"""

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

GT_PUBLIC_BASE_URL = "https://api.geckoterminal.com/api/v2"

# Keyed-API upgrade: CoinGecko's onchain API serves the same GeckoTerminal
# data under a per-key quota instead of GT's public per-IP one - see
# fetch_pool_ohlcv's docstring for when this is used.
CG_ONCHAIN_BASE_URL = "https://api.coingecko.com/api/v3/onchain"

# ASSUMED, not verified against GeckoTerminal's own network registry - see
# module docstring.
GT_NETWORK_BY_CHAIN = {"robinhood": "robinhood", "base": "base"}

# Per-invocation call budget and inter-call spacing. GT's public API rate
# limit is 30 calls/min; GT_CALL_SPACING_SECONDS (3.0s -> 20 calls/min)
# stays under that with headroom, while GT_CALL_BUDGET_PER_RUN bounds how
# long a single backfill request runs (a resumable route calls back
# repeatedly rather than trying to drain an unbounded worklist in one HTTP
# request/gunicorn-worker timeout).
#
# 429 fix 1/2: this used to be 2.1s and the spacing lived only in the
# route, between UNITS - fetch_full_day_history's own pages fired
# back-to-back with no spacing at all, so a single multi-page ATH unit
# could burst well past the limit on its own. The sleep now lives inside
# fetch_pool_ohlcv itself (see its docstring), so every GT call in the
# process self-paces regardless of which function issues it. 3.0s gives
# more headroom than the old 2.1s did, since Railway's egress IPs are
# shared across tenants - this process is never the limit's only consumer.
GT_CALL_BUDGET_PER_RUN = 25
GT_CALL_SPACING_SECONDS = 3.0


class GTError(Exception):
    """Raised by fetch_pool_ohlcv on any GeckoTerminal HTTP/parse failure.
    This is the ONLY function in this module that talks to the network,
    and the only one tests monkeypatch - every other function here is pure.
    Callers (the backfill route) catch this per-unit - one pool's GT error
    must never abort the whole backfill run - and turn it into a
    {status: 'error', reason: str(e)} entry, never letting it propagate."""


class GTRateLimitError(GTError):
    """Raised by fetch_pool_ohlcv specifically for an HTTP 429 (rate
    limited) response - a distinct type from the base GTError so the
    backfill route can tell "this one pool/unit failed" (recoverable, keep
    going - see GTError's own docstring) from "we just got throttled"
    (every remaining call this run would fail the same way, so the route
    aborts the whole run rather than burning the rest of its budget on
    calls guaranteed to 429 too - see api_maxfi_backfill_history)."""


def fetch_pool_ohlcv(network, pool_address, timeframe, *, aggregate=1,
                      before_timestamp=None, limit=1000, token=None, timeout=10):
    """One GET .../networks/{network}/pools/{pool_address}/ohlcv/{timeframe}
    call. Same requests conventions as maxfi_anchor_prices.py's
    _fetch_reference_price - a bare timeout, no retry loop - except this
    function RAISES (GTError) on failure instead of returning None: a
    missed anchor price there is a normal degraded case with its own
    fallback chain, but every GT failure here is always reported per-unit
    by the caller, so raising keeps that reporting in one place (the
    caller) rather than two.

    Returns {"candles": [[ts, o, h, l, c, v], ...], "base_address": lower,
    "quote_address": lower}. GT does not guarantee candle order - callers
    must never assume ascending/descending ts.

    Keyed-API upgrade: even at 3.0s pacing after a long cooldown, runs were
    still dying to HTTP 429 after only ~6 calls - GeckoTerminal's free
    tier limits per IP, and Railway's egress IP is shared across tenants,
    so other tenants' traffic exhausts the same quota this process draws
    from. When COINGECKO_API_KEY is set in the environment, this targets
    CoinGecko's onchain API instead - documented as the same
    GeckoTerminal data, but billed against this key's own quota rather
    than the shared IP's. The key is read here, per call (os.environ.get,
    not module-level state), so a Railway variable change takes effect on
    the very next call with no restart and no code change, and tests can
    monkeypatch the environment directly. Response-shape parity between
    the two endpoints is UNVERIFIED until a real key is live - parsing
    below stays exactly as tolerant as it already was for the public
    endpoint (skip/raise GTError on a shape surprise, never a hard
    assumption), so any drift is caught the same way an ordinary GT
    hiccup already is: per-unit, not a hard crash.
    """
    params = {"aggregate": aggregate, "limit": limit, "currency": "usd"}
    if before_timestamp is not None:
        params["before_timestamp"] = before_timestamp
    if token is not None:
        params["token"] = token

    headers = {"Accept": "application/json;version=20230302"}
    api_key = os.environ.get("COINGECKO_API_KEY")
    if api_key:
        base_url = CG_ONCHAIN_BASE_URL
        headers["x-cg-demo-api-key"] = api_key
    else:
        base_url = GT_PUBLIC_BASE_URL
    url = f"{base_url}/networks/{network}/pools/{pool_address}/ohlcv/{timeframe}"

    # 429 fix 1/2: every GT call in the process self-paces here,
    # unconditionally, before it fires - not just between units in the
    # route - so a multi-page fetch_full_day_history call can no longer
    # burst several requests back-to-back with no spacing between them.
    time.sleep(GT_CALL_SPACING_SECONDS)
    try:
        resp = requests.get(url, params=params, timeout=timeout, headers=headers)
    except requests.RequestException as e:
        raise GTError(f"GeckoTerminal request failed for {network}/{pool_address}: {e}")
    if resp.status_code == 429:
        raise GTRateLimitError(f"GeckoTerminal HTTP {resp.status_code} for {network}/{pool_address}")
    if not resp.ok:
        raise GTError(f"GeckoTerminal HTTP {resp.status_code} for {network}/{pool_address}")
    try:
        payload = resp.json()
    except ValueError as e:
        raise GTError(f"GeckoTerminal returned non-JSON for {network}/{pool_address}: {e}")
    try:
        candles = payload["data"]["attributes"]["ohlcv_list"]
        meta = payload["meta"]
        base_address = str(meta["base"]["address"]).lower()
        quote_address = str(meta["quote"]["address"]).lower()
    except (KeyError, TypeError) as e:
        raise GTError(f"GeckoTerminal response shape unexpected for {network}/{pool_address}: {e}")
    return {"candles": candles, "base_address": base_address, "quote_address": quote_address}


def resolve_token_side(volatile_address, base_address, quote_address):
    """Lowercased comparison only - callers pass raw-cased addresses from
    anywhere (maxfi_positions.token0/1_address are unnormalized on write).
    Returns 'base', 'quote', or None if volatile_address matches neither."""
    if not volatile_address:
        return None
    v = str(volatile_address).lower()
    if base_address and v == str(base_address).lower():
        return "base"
    if quote_address and v == str(quote_address).lower():
        return "quote"
    return None


def compute_ath(candles):
    """Max over the high column (index 2 of [ts, o, h, l, c, v]),
    order-agnostic (GT does not guarantee candle order) and skipping any
    row that fails to parse as (int, float) or is NaN/infinite, rather than
    raising on one bad row. Returns (ath_price, ath_epoch), or None if no
    row survives parsing."""
    best = None
    for row in candles or []:
        try:
            ts = int(row[0])
            high = float(row[2])
        except (TypeError, ValueError, IndexError):
            continue
        if high != high or high in (float("inf"), float("-inf")):  # NaN/inf guard
            continue
        if best is None or high > best[0]:
            best = (high, ts)
    return best


def candle_open_at(candles, target_epoch, candle_seconds):
    """The candle whose [ts, ts + candle_seconds) window brackets
    target_epoch, if any; else the nearest candle within
    2 * candle_seconds of target_epoch, if any; else None. Returns
    (open_price, candle_epoch). Malformed rows are skipped like
    compute_ath, never raised on."""
    parsed = []
    for row in candles or []:
        try:
            ts = int(row[0])
            open_price = float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        parsed.append((ts, open_price))
    if not parsed:
        return None

    for ts, open_price in parsed:
        if ts <= target_epoch < ts + candle_seconds:
            return (open_price, ts)

    tolerance = 2 * candle_seconds
    best = None
    best_dist = None
    for ts, open_price in parsed:
        dist = abs(ts - target_epoch)
        if dist <= tolerance and (best_dist is None or dist < best_dist):
            best = (open_price, ts)
            best_dist = dist
    return best


def fetch_full_day_history(network, pool_address, token, fetch=fetch_pool_ohlcv,
                            max_pages=4, counter=None):
    """Pages GT's day-timeframe OHLCV for one pool, oldest-first via
    before_timestamp = the oldest ts seen in the previous page, until an
    empty page or max_pages is reached.

    `fetch` is swappable (same seam as fetch_pool_ohlcv itself - a test
    passes its own fake directly; the real caller in web_portfolio.py
    always passes maxfi_history.fetch_pool_ohlcv explicitly, a fresh
    module-attribute lookup made at call time, rather than relying on this
    function's own default - so a route-level test that monkeypatches
    maxfi_history.fetch_pool_ohlcv is honored here too, not just for a
    caller that skips this function).

    `counter`, a one-element list (e.g. [0]), is bumped once per attempted
    page - including a page whose fetch raises - so a caller can track a
    shared GT call budget across many pools/units; a fresh throwaway
    counter is used when none is given. Raises GTError exactly as
    fetch_pool_ohlcv does on a page failure - the caller handles per-unit
    isolation, not this function.
    """
    if counter is None:
        counter = [0]
    candles = []
    before_ts = None
    for _ in range(max_pages):
        counter[0] += 1
        page = fetch(network, pool_address, "day", aggregate=1,
                      before_timestamp=before_ts, limit=1000, token=token)
        page_candles = page.get("candles") or []
        if not page_candles:
            break
        candles.extend(page_candles)
        try:
            oldest_ts = min(int(row[0]) for row in page_candles)
        except (TypeError, ValueError, IndexError):
            break  # malformed page - stop paging rather than loop forever
        if before_ts is not None and oldest_ts >= before_ts:
            break  # no progress - guards against an infinite loop
        before_ts = oldest_ts
    return candles
