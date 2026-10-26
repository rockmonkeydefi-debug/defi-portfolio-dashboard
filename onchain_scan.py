"""Landing 70: ad hoc on-chain token check - the data side.

Given a chain (one of Spot's seven) and a token contract address, find the
token's most liquid pool on GeckoTerminal, pull its candles for the five
noodle timeframes and hand back clean candle lists the existing noodle /
respected-trend / point-of-interest code can read. Nothing here is stored
and nothing here imports web_portfolio (the compute and the route live
there, so they can reuse the scan's helpers).

Network: every call goes through maxfi_history's pacing and keyed-API
switch (COINGECKO_API_KEY), so a check is polite to the shared quota:
/networks (cached), one token-pools call (or one pool call when a pool
address is pasted), then four candle calls (1h, 4h, 12h, 1d). The weekly
series is built from the dailies by the caller. About 7 calls at 3 s.

UNVERIFIED from the build sandbox (it cannot reach GeckoTerminal): the
/networks id for Robinhood Chain, the token-pools / pool response shape,
and the CoinGecko-keyed endpoint's parity with the public one. Every
parse here is tolerant and fails with a plain message instead of
guessing; the first real check is the verification.
"""
import math
import os
import time

import requests

import maxfi_history

# Which GeckoTerminal network ids to accept for each Spot chain, in order of
# preference. A candidate only counts when /networks lists it; if none is
# listed a name match is tried; otherwise the chain is "not supported".
NETWORK_CANDIDATES = {
    'ethereum': ['eth'],
    'base': ['base'],
    'arbitrum': ['arbitrum'],
    'bsc': ['bsc'],
    'robinhood': ['robinhood', 'robinhood-chain', 'robinhood_chain'],
    'sonic': ['sonic'],
    'solana': ['solana'],
}
# Name fragments for the fallback match against /networks "name".
NETWORK_NAME_HINTS = {
    'ethereum': ['ethereum'],
    'base': ['base'],
    'arbitrum': ['arbitrum'],
    'bsc': ['bnb', 'bsc'],
    'robinhood': ['robinhood'],
    'sonic': ['sonic'],
    'solana': ['solana'],
}

NETWORKS_CACHE_SECONDS = 6 * 3600
NETWORKS_MAX_PAGES = 6
POOLS_ALTERNATIVES = 4

# (timeframe key, GT timeframe, GT aggregate, bar seconds, bars to ask for)
CANDLE_PLAN = (
    ('1h', 'hour', 1, 3600, 1000),
    ('4h', 'hour', 4, 14400, 1000),
    ('12h', 'hour', 12, 43200, 1000),
    ('1d', 'day', 1, 86400, 1000),
)

_networks_cache = {'at': 0.0, 'ids': None}


class OnchainError(Exception):
    """A plain-words failure for the caller to show. `status` is the HTTP
    status the route should answer with."""

    def __init__(self, message, status=502):
        super().__init__(message)
        self.message = message
        self.status = status


def _base_url_and_headers():
    headers = {"Accept": "application/json;version=20230302"}
    api_key = os.environ.get("COINGECKO_API_KEY")
    if api_key:
        headers["x-cg-demo-api-key"] = api_key
        return maxfi_history.CG_ONCHAIN_BASE_URL, headers
    return maxfi_history.GT_PUBLIC_BASE_URL, headers


def _get_json(path, params=None, timeout=10):
    """One paced GET under the GeckoTerminal / CoinGecko onchain base.
    Raises OnchainError with a plain message on any failure."""
    base, headers = _base_url_and_headers()
    time.sleep(maxfi_history.GT_CALL_SPACING_SECONDS)
    try:
        resp = requests.get(base + path, params=params or {}, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        raise OnchainError(f"GeckoTerminal request failed: {type(e).__name__}", 502)
    if resp.status_code == 429:
        raise OnchainError("GeckoTerminal is rate-limiting (HTTP 429). Wait a minute and try again.", 429)
    if resp.status_code == 404:
        raise OnchainError("GeckoTerminal has no record of that (HTTP 404).", 404)
    if not resp.ok:
        raise OnchainError(f"GeckoTerminal answered HTTP {resp.status_code}.", 502)
    try:
        return resp.json()
    except ValueError:
        raise OnchainError("GeckoTerminal returned something that is not JSON.", 502)


def _list_network_ids():
    """{id: lowercased name} for every network GeckoTerminal lists. Cached
    for a few hours; a failure raises (nothing is cached)."""
    now = time.time()
    if _networks_cache['ids'] is not None and now - _networks_cache['at'] < NETWORKS_CACHE_SECONDS:
        return _networks_cache['ids']
    ids = {}
    for page in range(1, NETWORKS_MAX_PAGES + 1):
        payload = _get_json('/networks', {'page': page})
        try:
            data = payload['data']
        except (KeyError, TypeError):
            raise OnchainError("GeckoTerminal's network list had an unexpected shape.", 502)
        if not isinstance(data, list) or not data:
            break
        for n in data:
            try:
                nid = str(n['id'])
            except (KeyError, TypeError):
                continue
            name = ''
            try:
                name = str(n['attributes']['name']).lower()
            except (KeyError, TypeError):
                pass
            ids[nid] = name
        nxt = None
        if isinstance(payload, dict):
            nxt = (payload.get('links') or {}).get('next') if isinstance(payload.get('links'), dict) else None
        if not nxt:
            break
    if not ids:
        raise OnchainError("GeckoTerminal's network list was empty.", 502)
    _networks_cache['at'] = now
    _networks_cache['ids'] = ids
    return ids


def resolve_network(chain, chain_label=None):
    """The GeckoTerminal network id for a Spot chain key, or raises
    OnchainError(400) saying the chain is not supported by GeckoTerminal."""
    ids = _list_network_ids()
    for cand in NETWORK_CANDIDATES.get(chain, [chain]):
        if cand in ids:
            return cand
    hints = NETWORK_NAME_HINTS.get(chain, [chain])
    for nid, name in ids.items():
        if any(h in name or h == nid for h in hints):
            return nid
    label = chain_label or chain
    raise OnchainError(f"{label} is not supported by GeckoTerminal, so it cannot be checked here.", 400)


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _token_part(rel, key):
    """Lowercased-for-compare token address out of a relationship id such as
    'eth_0xabc...'; None when the shape is not as expected."""
    try:
        tid = str(rel[key]['data']['id'])
    except (KeyError, TypeError):
        return None
    return tid.rsplit('_', 1)[-1] if '_' in tid else tid


def _parse_pool(item):
    """One pool object -> a flat dict, or None when it is unusable."""
    try:
        a = item['attributes']
        rel = item['relationships']
        address = str(a['address'])
    except (KeyError, TypeError):
        return None
    vol = a.get('volume_usd')
    return {
        'address': address,
        'name': str(a.get('name') or ''),
        'dex': (((rel.get('dex') or {}).get('data') or {}).get('id')),
        'liquidity_usd': _num(a.get('reserve_in_usd')),
        'volume_24h_usd': _num(vol.get('h24')) if isinstance(vol, dict) else None,
        'created_at': a.get('pool_created_at'),
        'base': _token_part(rel, 'base_token'),
        'quote': _token_part(rel, 'quote_token'),
    }


def side_of(token, pool):
    """'base' / 'quote' / None for a token address against a parsed pool.
    EVM compares case-insensitively; base58 (Solana) keeps case."""
    if not token:
        return None
    for side in ('base', 'quote'):
        other = pool.get(side)
        if other is None:
            continue
        if other == token or other.lower() == token.lower() and token.startswith('0x'):
            return side
    return None


def find_pool(network, token, pool_address=None):
    """-> (pool dict, side, alternatives list, auto bool).

    With `pool_address` the pool is looked up directly (token optional:
    without one the base token is charted). Otherwise the token's pools are
    listed and the one with the most liquidity is picked; the next few are
    returned as `alternatives` so a different one can be pasted."""
    if pool_address:
        payload = _get_json(f'/networks/{network}/pools/{pool_address}')
        try:
            pool = _parse_pool(payload['data'])
        except (KeyError, TypeError):
            pool = None
        if pool is None:
            raise OnchainError("GeckoTerminal's pool answer had an unexpected shape.", 502)
        if token:
            side = side_of(token, pool)
            if side is None:
                raise OnchainError("That token is not one of the two tokens in the pool you pasted.", 400)
        else:
            side = 'base'
        return pool, side, [], False

    payload = _get_json(f'/networks/{network}/tokens/{token}/pools', {'page': 1})
    try:
        data = payload['data']
    except (KeyError, TypeError):
        raise OnchainError("GeckoTerminal's token-pools answer had an unexpected shape.", 502)
    pools = []
    for item in data if isinstance(data, list) else []:
        p = _parse_pool(item)
        if p is None:
            continue
        s = side_of(token, p)
        if s is None:
            continue
        p['_side'] = s
        pools.append(p)
    if not pools:
        raise OnchainError("GeckoTerminal lists no pools for that token on this chain. "
                           "It may be too new, mistyped, or on another chain.", 404)
    pools.sort(key=lambda p: (p['liquidity_usd'] if p['liquidity_usd'] is not None else -1.0,
                              p['volume_24h_usd'] if p['volume_24h_usd'] is not None else -1.0),
               reverse=True)
    best = pools[0]
    alts = [{k: p[k] for k in ('address', 'name', 'dex', 'liquidity_usd', 'volume_24h_usd')}
            for p in pools[1:1 + POOLS_ALTERNATIVES]]
    return best, best['_side'], alts, True


def normalize_candles(raw, step, now_ts):
    """GeckoTerminal [[ts, o, h, l, c, v], ...] (any order, gaps where nothing
    traded) -> ascending candle dicts with every empty bar filled by carrying
    the last close forward (volume 0), running up to and including the bar
    that holds `now_ts`, so the last candle is always the still-forming one
    the scan code drops. Malformed rows and non-positive prices are skipped.
    Raises OnchainError when nothing usable is left."""
    by_ts = {}
    for row in raw or []:
        try:
            ts = int(row[0])
            o, h, l, c, v = (_num(row[1]), _num(row[2]), _num(row[3]), _num(row[4]), _num(row[5]))
        except (TypeError, ValueError, IndexError):
            continue
        if None in (o, h, l, c) or min(o, h, l, c) <= 0:
            continue
        by_ts[ts] = {'time': ts, 'open': o, 'high': h, 'low': l, 'close': c,
                     'volume': v if v is not None else 0.0}
    if not by_ts:
        raise OnchainError("GeckoTerminal returned no usable candles for that pool.", 404)
    ordered = [by_ts[t] for t in sorted(by_ts)]
    out = [ordered[0]]
    for c in ordered[1:]:
        t = out[-1]['time'] + step
        while t < c['time']:
            prev = out[-1]['close']
            out.append({'time': t, 'open': prev, 'high': prev, 'low': prev, 'close': prev, 'volume': 0.0})
            t += step
        out.append(c)
    # carry through to the bar holding "now" (same phase as the series)
    last = out[-1]['time']
    current = last + ((now_ts - last) // step) * step if now_ts > last else last
    t = last + step
    while t <= current:
        prev = out[-1]['close']
        out.append({'time': t, 'open': prev, 'high': prev, 'low': prev, 'close': prev, 'volume': 0.0})
        t += step
    return out


def fetch_series(network, pool, side, now_ts=None):
    """-> {'1h': [...], '4h': [...], '12h': [...], '1d': [...]} candle lists
    (forming bar last). `pool` is a parsed pool dict; `side` says which of
    its two tokens is being charted (the quote side asks GeckoTerminal to
    invert the chart). Raises OnchainError."""
    now_ts = int(now_ts if now_ts is not None else time.time())
    series = {}
    for key, gt_tf, aggregate, step, limit in CANDLE_PLAN:
        try:
            res = maxfi_history.fetch_pool_ohlcv(
                network, pool['address'], gt_tf, aggregate=aggregate, limit=limit,
                token=('quote' if side == 'quote' else None))
        except maxfi_history.GTRateLimitError:
            raise OnchainError("GeckoTerminal is rate-limiting (HTTP 429). Wait a minute and try again.", 429)
        except maxfi_history.GTError as e:
            raise OnchainError(f"GeckoTerminal candle call failed for {key}: {e}", 502)
        series[key] = normalize_candles(res.get('candles'), step, now_ts)
    return series
