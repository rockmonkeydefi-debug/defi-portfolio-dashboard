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

import requests

logger = logging.getLogger(__name__)

GT_API_BASE = "https://api.geckoterminal.com/api/v2"

# ASSUMED, not verified against GeckoTerminal's own network registry - see
# module docstring.
GT_NETWORK_BY_CHAIN = {"robinhood": "robinhood", "base": "base"}

# Per-invocation call budget and inter-call spacing. GT's public API rate
# limit is 30 calls/min; GT_CALL_SPACING_SECONDS (2.1s -> ~28.6 calls/min)
# stays under that with headroom, while GT_CALL_BUDGET_PER_RUN bounds how
# long a single backfill request runs (a resumable route calls back
# repeatedly rather than trying to drain an unbounded worklist in one HTTP
# request/gunicorn-worker timeout).
GT_CALL_BUDGET_PER_RUN = 25
GT_CALL_SPACING_SECONDS = 2.1


class GTError(Exception):
    """Raised by fetch_pool_ohlcv on any GeckoTerminal HTTP/parse failure.
    This is the ONLY function in this module that talks to the network,
    and the only one tests monkeypatch - every other function here is pure.
    Callers (the backfill route) catch this per-unit - one pool's GT error
    must never abort the whole backfill run - and turn it into a
    {status: 'error', reason: str(e)} entry, never letting it propagate."""


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
    """
    params = {"aggregate": aggregate, "limit": limit, "currency": "usd"}
    if before_timestamp is not None:
        params["before_timestamp"] = before_timestamp
    if token is not None:
        params["token"] = token
    url = f"{GT_API_BASE}/networks/{network}/pools/{pool_address}/ohlcv/{timeframe}"
    try:
        resp = requests.get(
            url, params=params, timeout=timeout,
            headers={"Accept": "application/json;version=20230302"},
        )
    except requests.RequestException as e:
        raise GTError(f"GeckoTerminal request failed for {network}/{pool_address}: {e}")
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
