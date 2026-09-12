"""DeFiLlama-backed pool catalogue probe (LP Advisor workstream, Phase A1
of the data layer). Purpose: verify what DeFiLlama's live yields catalogue
actually contains for MaxFi/Robinhood Chain pools before any schema is
designed - Phase A2 designs the real PoolDataProvider schema from the raw
shapes this probe reports back, not from guesswork.

Same one-seam convention as maxfi_history.py: fetch_llama_pools is the ONLY
function in this module that talks to the network, and the only one tests
monkeypatch - every other function here is pure. The route
(api_maxfi_pooldata_probe in web_portfolio.py) looks up every function used
here as a module attribute at call time (maxfi_pooldata.fetch_llama_pools,
etc.), so route-level tests can monkeypatch them.

The DeFiLlama project slug and chain name for MaxFi and Robinhood Chain are
UNVERIFIED - discovering them live is the entire point of this probe. All
matching below (discover_projects, discover_chains, filter_pools) is
case-insensitive substring or case-insensitive-exact matching against
whatever raw strings DeFiLlama actually returns, never a hardcoded slug.
"""

import math
from datetime import date, timedelta

import requests

LLAMA_YIELDS_POOLS_URL = "https://yields.llama.fi/pools"

# The exact raw-pool fields Phase A2's schema will need to evaluate for
# coverage before committing to columns - see summarize_field_availability.
_PROBE_FIELDS = [
    "pool", "project", "chain", "symbol", "tvlUsd", "apy", "apyBase",
    "apyReward", "volumeUsd1d", "volumeUsd7d", "poolMeta",
    "underlyingTokens", "url",
]


class LlamaError(Exception):
    """Raised only by fetch_llama_pools on any DeFiLlama HTTP/parse
    failure. Callers (the probe route) catch this and report it as an
    error response - it must never propagate into a 500."""


def fetch_llama_pools(timeout=30):
    """One GET https://yields.llama.fi/pools call. The ONLY network-
    touching function in this module. Raises LlamaError on a request
    failure, a non-2xx status, a non-JSON body, or a JSON payload whose
    top-level "data" key is missing or not a list - every other failure
    mode is reported per-probe by the caller, never a hard crash out of
    the route. Returns the list under payload["data"] unchanged."""
    try:
        r = requests.get(
            LLAMA_YIELDS_POOLS_URL,
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise LlamaError(f"request to {LLAMA_YIELDS_POOLS_URL} failed: {e}")

    if not (200 <= r.status_code < 300):
        raise LlamaError(
            f"{LLAMA_YIELDS_POOLS_URL} returned HTTP {r.status_code}"
        )

    try:
        payload = r.json()
    except ValueError as e:
        raise LlamaError(f"{LLAMA_YIELDS_POOLS_URL} returned non-JSON body: {e}")

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise LlamaError(
            "DeFiLlama payload has no list under 'data' - "
            f"got {type(data).__name__ if payload is not None else 'no payload'}"
        )
    return data


def discover_projects(pools, keyword="maxfi"):
    """Pure. Case-insensitive substring match of `keyword` against each
    dict row's str(pool.get("project", "")). Non-dict rows are skipped.
    Returns a sorted list of the distinct matching project values (the
    raw values, not the keyword)."""
    keyword_lower = keyword.lower()
    matched = set()
    for pool in pools:
        if not isinstance(pool, dict):
            continue
        project = str(pool.get("project", ""))
        if keyword_lower in project.lower():
            matched.add(project)
    return sorted(matched)


def discover_chains(pools, keyword="robinhood"):
    """Pure. Same pattern as discover_projects, against str(pool.get("chain",
    "")). Returns a sorted list of the distinct matching chain values."""
    keyword_lower = keyword.lower()
    matched = set()
    for pool in pools:
        if not isinstance(pool, dict):
            continue
        chain = str(pool.get("chain", ""))
        if keyword_lower in chain.lower():
            matched.add(chain)
    return sorted(matched)


def filter_pools(pools, projects=None, chains=None):
    """Pure. Keeps dict rows where (projects is falsy OR the row's project
    case-insensitively exact-matches one of `projects`) AND (chains is
    falsy OR the row's chain case-insensitively exact-matches one of
    `chains`). Non-dict rows never match (filtered out) unless both
    `projects` and `chains` are falsy, in which case everything - dict or
    not - passes through untouched."""
    if not projects and not chains:
        return list(pools)

    projects_lower = {p.lower() for p in projects} if projects else None
    chains_lower = {c.lower() for c in chains} if chains else None

    out = []
    for pool in pools:
        if not isinstance(pool, dict):
            continue
        if projects_lower is not None and str(pool.get("project", "")).lower() not in projects_lower:
            continue
        if chains_lower is not None and str(pool.get("chain", "")).lower() not in chains_lower:
            continue
        out.append(pool)
    return out


def match_pools_by_underlying(pools, held_tokens):
    """Pure. Phase A1.5 - identifies which DeFiLlama project actually
    covers the app's held volatile tokens (anchor/stable noise is excluded
    upstream: held_tokens is expected to come from
    maxfi_token_price_stats, which by construction holds volatile tokens
    only) by joining each pool's underlyingTokens against the held-token
    address set.

    held_tokens: list of dicts {"chain": str, "address": str, "symbol":
    str-or-None} - addresses are assumed already lowercased by the caller
    but are lowercased again here defensively.

    Returns {"matched_pools": [...], "projects": {...},
    "unmatched_held_tokens": [...]} - see the module's own callers
    (api_maxfi_pooldata_probe) for how each piece is surfaced."""
    held_by_address = {}
    for token in held_tokens:
        addr = str(token.get("address", "")).lower()
        held_by_address[addr] = token

    matched_pools = []
    matched_addresses_overall = set()
    projects = {}

    for pool in pools:
        if not isinstance(pool, dict):
            continue
        underlying = pool.get("underlyingTokens") or []
        hit_addresses = sorted({
            addr.lower() for addr in underlying
            if isinstance(addr, str) and addr.lower() in held_by_address
        })
        if not hit_addresses:
            continue

        matched_tokens = [
            {
                "address": addr,
                "symbol": held_by_address[addr].get("symbol"),
                "chain": held_by_address[addr].get("chain"),
            }
            for addr in hit_addresses
        ]
        matched_addresses_overall.update(hit_addresses)

        project = str(pool.get("project", ""))
        matched_pools.append({
            "project": project,
            "llama_chain": str(pool.get("chain", "")),
            "symbol": pool.get("symbol"),
            "pool_meta": pool.get("poolMeta"),
            "llama_pool_id": pool.get("pool"),
            "tvl_usd": pool.get("tvlUsd"),
            "matched_tokens": matched_tokens,
        })

        project_entry = projects.setdefault(project, {
            "pool_count": 0, "matched_token_addresses": set(), "matched_token_symbols": set(),
        })
        project_entry["pool_count"] += 1
        project_entry["matched_token_addresses"].update(hit_addresses)
        project_entry["matched_token_symbols"].update(
            t["symbol"] for t in matched_tokens if t["symbol"] is not None
        )

    projects_out = {
        project: {
            "pool_count": entry["pool_count"],
            "matched_token_addresses": sorted(entry["matched_token_addresses"]),
            "matched_token_symbols": sorted(entry["matched_token_symbols"]),
        }
        for project, entry in projects.items()
    }

    unmatched_held_tokens = sorted(
        (token for addr, token in held_by_address.items() if addr not in matched_addresses_overall),
        key=lambda t: str(t.get("address", "")),
    )

    return {
        "matched_pools": matched_pools,
        "projects": projects_out,
        "unmatched_held_tokens": unmatched_held_tokens,
    }


def summarize_field_availability(pools):
    """Pure. For each field in _PROBE_FIELDS, reports how many rows carry
    the key at all ("present") versus how many carry it with a non-None
    value ("non_null") - present-but-null (a key DeFiLlama always sends,
    sometimes as null) reads differently from the key being entirely
    absent, and Phase A2's schema needs to tell those apart. Non-dict rows
    are skipped for every per-field count but still counted in the
    top-level "row_count", which is len(pools) unconditionally."""
    summary = {"row_count": len(pools)}
    for field in _PROBE_FIELDS:
        present = 0
        non_null = 0
        for pool in pools:
            if not isinstance(pool, dict):
                continue
            if field in pool:
                present += 1
                if pool[field] is not None:
                    non_null += 1
        summary[field] = {"present": present, "non_null": non_null}
    return summary


# ── LP Advisor Phase A2 (commit 2 of 2): DexScreener pair provider + trend
# math. fetch_dexscreener_pairs is the ONLY new network-touching function -
# everything else below is pure. No sqlite, no Flask, no DB access anywhere
# in this module; routes and persistence are Phase B.

DEXSCREENER_PAIRS_URL_TEMPLATE = "https://api.dexscreener.com/latest/dex/pairs/{chain_slug}/{addresses}"
# 30 = DexScreener's documented per-call address cap for the pairs endpoint.
DEXSCREENER_PAIRS_BATCH_MAX = 30


class DexScreenerError(Exception):
    """Raised only by fetch_dexscreener_pairs on any DexScreener HTTP/parse
    failure. Callers report this per-batch and never let it propagate."""


def fetch_dexscreener_pairs(chain_slug, pool_addresses, timeout=15):
    """One GET .../latest/dex/pairs/{chain_slug}/{addresses} call. The ONLY
    new network-touching function in this module. chain_slug comes from the
    app's existing chain registry, passed in by the caller - this module
    holds no chain table of its own.

    Raises DexScreenerError on an empty `pool_addresses` or one exceeding
    DEXSCREENER_PAIRS_BATCH_MAX (a caller batching bug, not a network
    failure - still the same error type so route handling stays uniform,
    and raised BEFORE any network call), a request failure, a non-2xx
    status, a non-JSON body, a non-object JSON payload, or a payload whose
    "pairs" key is neither a list nor None.

    Returns payload.get("pairs") or [] - DexScreener returns a null
    "pairs" for no matches, normalized to [] here rather than surfaced as
    None."""
    if not pool_addresses:
        raise DexScreenerError("pool_addresses must be non-empty")
    if len(pool_addresses) > DEXSCREENER_PAIRS_BATCH_MAX:
        raise DexScreenerError(
            f"batch of {len(pool_addresses)} exceeds DEXSCREENER_PAIRS_BATCH_MAX "
            f"({DEXSCREENER_PAIRS_BATCH_MAX})"
        )

    url = DEXSCREENER_PAIRS_URL_TEMPLATE.format(
        chain_slug=chain_slug, addresses=",".join(pool_addresses),
    )
    try:
        r = requests.get(url, headers={"Accept": "application/json"}, timeout=timeout)
    except requests.RequestException as e:
        raise DexScreenerError(f"request to {url} failed: {e}")

    if not (200 <= r.status_code < 300):
        raise DexScreenerError(f"{url} returned HTTP {r.status_code}")

    try:
        payload = r.json()
    except ValueError as e:
        raise DexScreenerError(f"{url} returned non-JSON body: {e}")

    if not isinstance(payload, dict):
        raise DexScreenerError(
            f"DexScreener payload is not a JSON object - got {type(payload).__name__}"
        )
    pairs = payload.get("pairs")
    if pairs is not None and not isinstance(pairs, list):
        raise DexScreenerError(
            f"DexScreener payload has a non-list, non-null 'pairs' - got {type(pairs).__name__}"
        )
    return pairs or []


def summarize_pair_batches(pool_addresses, batch_max=DEXSCREENER_PAIRS_BATCH_MAX):
    """Pure. Splits pool_addresses into batches of at most batch_max,
    preserving input order - pulled out as its own function so the
    batching fetch_dexscreener_pairs callers will use is testable without
    network. Empty input returns []."""
    return [pool_addresses[i:i + batch_max] for i in range(0, len(pool_addresses), batch_max)]


def _finite_or_none(value):
    """Coerce to float, returning None on a missing/non-numeric/NaN/
    infinite value rather than raising - the shared rule every
    parse_pair_metrics field follows."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def parse_pair_metrics(pair):
    """Pure. Parses one raw DexScreener pair dict into
    {"pool_address", "price_usd", "liquidity_usd", "volume_h24",
    "volume_h6", "volume_h1", "price_change_h24"}.

    pool_address is str(pair["pairAddress"]).lower() - if pairAddress is
    missing or non-str, the pair is unkeyable and the whole call returns
    None. price_usd comes from pair["priceUsd"] via float() (DexScreener
    sends it as a STRING); liquidity_usd from pair["liquidity"]["usd"];
    volumes from pair["volume"]["h24"/"h6"/"h1"]; price_change_h24 from
    pair["priceChange"]["h24"] (verified live: priceChange can omit keys
    entirely on thin pairs). Every field independently degrades to None on
    a missing key, None, non-numeric, NaN, or infinite value - this
    function never raises."""
    if not isinstance(pair, dict):
        return None
    pool_address = pair.get("pairAddress")
    if not isinstance(pool_address, str):
        return None

    liquidity = pair.get("liquidity")
    if not isinstance(liquidity, dict):
        liquidity = {}
    volume = pair.get("volume")
    if not isinstance(volume, dict):
        volume = {}
    price_change = pair.get("priceChange")
    if not isinstance(price_change, dict):
        price_change = {}

    return {
        "pool_address": pool_address.lower(),
        "price_usd": _finite_or_none(pair.get("priceUsd")),
        "liquidity_usd": _finite_or_none(liquidity.get("usd")),
        "volume_h24": _finite_or_none(volume.get("h24")),
        "volume_h6": _finite_or_none(volume.get("h6")),
        "volume_h1": _finite_or_none(volume.get("h1")),
        "price_change_h24": _finite_or_none(price_change.get("h24")),
    }


def _parse_daily_rows(daily_rows):
    """Parse (date_str, close_usd) tuples into (date, close) pairs,
    silently dropping any row whose date string doesn't parse - a
    malformed row must degrade this row, never abort the whole trend
    calculation."""
    parsed = []
    for entry in daily_rows:
        try:
            d, close = entry
            parsed.append((date.fromisoformat(d), close))
        except (TypeError, ValueError):
            continue
    return parsed


def price_change_pct(daily_rows, as_of_date, window_days):
    """Pure. `daily_rows` is a list of (date_str "YYYY-MM-DD", close_usd
    float) tuples, any order, possibly gappy. `as_of_date` is a
    "YYYY-MM-DD" string.

    latest = the row with the max date <= as_of_date. base = the row
    nearest to (as_of_date - window_days) within a +/- 2-day tolerance.
    Returns None (never fabricates) when either row is missing, or when
    base close <= 0. Otherwise ((latest - base) / base) * 100."""
    try:
        as_of = date.fromisoformat(as_of_date)
    except (TypeError, ValueError):
        return None

    parsed = _parse_daily_rows(daily_rows)
    if not parsed:
        return None

    on_or_before = [row for row in parsed if row[0] <= as_of]
    if not on_or_before:
        return None
    _latest_date, latest_close = max(on_or_before, key=lambda row: row[0])
    latest_close = _finite_or_none(latest_close)
    if latest_close is None:
        return None

    target_base_date = as_of - timedelta(days=window_days)
    within_tolerance = [row for row in parsed if abs((row[0] - target_base_date).days) <= 2]
    if not within_tolerance:
        return None
    _base_date, base_close = min(
        within_tolerance, key=lambda row: abs((row[0] - target_base_date).days)
    )
    base_close = _finite_or_none(base_close)
    if base_close is None or base_close <= 0:
        return None

    return (latest_close - base_close) / base_close * 100


def volume_trend_ratio(recent_avg, trailing_avg):
    """Pure scalar helper: recent_avg / trailing_avg. Returns None if
    either is None, non-finite, or trailing_avg <= 0. Volume windows
    themselves come from maxfi_pool_metrics snapshots in Phase B/C - this
    commit only ships the ratio math so the advisor's multiplier has one
    tested home."""
    recent = _finite_or_none(recent_avg)
    trailing = _finite_or_none(trailing_avg)
    if recent is None or trailing is None or trailing <= 0:
        return None
    return recent / trailing


# Phase E v1.3 - sharp-dump clause, judgment-set (NOT derived) same
# treatment as maxfi_advisor's tunable constants. Motivation: the plain
# both-windows-negative gate passes a pumped-then-dumping token whenever
# its 30d window is still positive - live observation: "AI" passed entry
# at -21.7% 7d on +2245% 30d, a token in the middle of a sharp weekly dump
# that a healthy month completely masked. A token down more than 15% on
# the week is a live dump regardless of what its month looks like. Tuned
# later against the pool scout's observed distribution, not derived up
# front.
POOLDATA_SHARP_DUMP_PCT_7D = -15.0


def downtrend_gate(daily_rows, as_of_date):
    """Pure. The entry gate per Glenn's discipline list: 7d AND 30d
    negative blocks entry - PLUS (Phase E v1.3) a sharp-dump override: a 7d
    decline worse than POOLDATA_SHARP_DUMP_PCT_7D (-15.0, strict < - exactly
    -15.0 is NOT sharp) blocks entry REGARDLESS of pct_30d, including when
    pct_30d is None/unknown. This is a deliberate, one-directional extension
    of the "unknown surfaces as unknown" contract: a KNOWN sharp weekly dump
    is disqualifying on its own, so an unknown 30d can no longer rescue it
    into a None (unresolved) reading the way it used to - it is blocked
    outright. An unknown 7d still can't tell you anything, so pct_7d=None
    still leaves sharp_dump=None and falls through to the ordinary
    either-is-None -> None handling below.

    Returns {"pct_7d", "pct_30d", "blocked", "sharp_dump"}. sharp_dump is
    True/False when pct_7d is a number, None when pct_7d is None. blocked:
    True whenever sharp_dump is True (regardless of pct_30d); otherwise
    None when either percentage is None; otherwise True only when both are
    negative, False when at least one is >= 0 - byte-identical to the
    pre-v1.3 rule outside the sharp-dump case. Unknown is surfaced as
    unknown, never coerced to passing."""
    pct_7d = price_change_pct(daily_rows, as_of_date, 7)
    pct_30d = price_change_pct(daily_rows, as_of_date, 30)

    sharp_dump = None if pct_7d is None else pct_7d < POOLDATA_SHARP_DUMP_PCT_7D

    if sharp_dump:
        blocked = True
    elif pct_7d is None or pct_30d is None:
        blocked = None
    else:
        blocked = pct_7d < 0 and pct_30d < 0

    return {"pct_7d": pct_7d, "pct_30d": pct_30d, "blocked": blocked, "sharp_dump": sharp_dump}
