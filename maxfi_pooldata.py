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
