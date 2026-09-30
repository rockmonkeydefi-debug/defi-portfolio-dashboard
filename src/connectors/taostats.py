"""Taostats account reader for Bittensor (TAO) wallets.

Verified against live responses (Sep 29-30, 2026):
- GET https://api.taostats.io/api/account/latest/v1?address=<ss58>, with the
  headers "authorization: <raw API key>" (no "Bearer") and
  "accept: application/json". The key comes only from the caller
  (os.getenv("TAOSTATS_API_KEY") in web_portfolio.py, read at call time).
- No rate-limit headers are returned. The free plan allows 5 credits/min and
  10,000 credits/month; the caller's refresh timer (15 min, one call per
  wallet) holds the budget.
- The response is {"pagination": {...}, "data": [ONE account object]}.
  Amounts are strings in rao (1 TAO = 10^9 rao); they are parsed as int,
  never float, until the final TAO/USD step in the caller.
- data[0].timestamp is Taostats' index time (observed ~14 min behind the
  request); it is the "as of" for every amount.
- Identities on the real sample:
    balance_total = balance_free + balance_staked + balance_reserved
                    + balance_liquidity
    balance_staked = balance_staked_alpha_as_tao + balance_staked_root
    sum(alpha_balances[].balance_as_tao) = balance_staked_alpha_as_tao
- Each alpha_balances[] entry: {"balance" (alpha, rao), "balance_as_tao"
  (rao), "hotkey", "coldkey", "netuid"}. balance_liquidity may be "0" or
  null.

fetch_account is the only function with I/O; parse_account is pure.
"""

TAOSTATS_BASE_URL = "https://api.taostats.io"
ACCOUNT_PATH = "/api/account/latest/v1"
RAO_PER_TAO = 10 ** 9
REQUEST_TIMEOUT_SECONDS = 10


class TaostatsError(Exception):
    """A Taostats read failed. Messages never contain the API key, the
    request headers or the URL - only status codes, exception type names or
    fixed texts."""


def fetch_account(address, api_key, get=None):
    """GET the latest account object for one SS58 address. Returns the parsed
    JSON. Raises TaostatsError on a non-200 status ("rate limited (HTTP 429)"
    or "HTTP <status>") or on any exception from the request or the JSON
    decode (message = the exception's type name only)."""
    if get is None:
        import requests
        get = requests.get
    try:
        resp = get(TAOSTATS_BASE_URL + ACCOUNT_PATH, params={"address": address},
                   headers={"accept": "application/json", "authorization": api_key},
                   timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception as e:
        raise TaostatsError(type(e).__name__) from None
    status = getattr(resp, "status_code", None)
    if status == 429:
        raise TaostatsError("rate limited (HTTP 429)")
    if status != 200:
        raise TaostatsError(f"HTTP {status}")
    try:
        return resp.json()
    except Exception as e:
        raise TaostatsError(type(e).__name__) from None


def _rao(v):
    """A rao amount (string or int) as int; None -> 0."""
    if v is None:
        return 0
    try:
        return int(str(v))
    except ValueError:
        raise TaostatsError("bad amount") from None


def parse_account(payload, address):
    """Parse one account/latest/v1 response for `address` into JSON-safe ints.

    Returns {"address", "as_of" (the Taostats timestamp string as given),
    "block" (int or None), "free_rao", "reserved_rao", "root_rao",
    "liquidity_rao", "alpha": [{"netuid", "alpha_rao", "as_tao_rao",
    "hotkeys"}] (summed per subnet, sorted by netuid, all-zero subnets
    dropped), "alpha_as_tao_field_rao", "total_rao", "parts_rao", "diff_rao"}.
    parts_rao = free + reserved + root + liquidity + the alpha as-TAO sum;
    diff_rao = total - parts_rao. Raises TaostatsError on an unexpected
    shape."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if (not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict)
            or (data[0].get("address") or {}).get("ss58") != address or not data[0].get("timestamp")):
        raise TaostatsError("unexpected account response")
    acct = data[0]

    free = _rao(acct.get("balance_free"))
    reserved = _rao(acct.get("balance_reserved"))
    root = _rao(acct.get("balance_staked_root"))
    liquidity = _rao(acct.get("balance_liquidity"))
    alpha_field = _rao(acct.get("balance_staked_alpha_as_tao"))
    total = _rao(acct.get("balance_total"))

    per_netuid = {}
    for entry in acct.get("alpha_balances") or []:
        if not isinstance(entry, dict):
            continue
        coldkey = entry.get("coldkey")
        if coldkey and coldkey != address:
            continue
        try:
            netuid = int(entry.get("netuid"))
        except (TypeError, ValueError):
            raise TaostatsError("bad amount") from None
        agg = per_netuid.setdefault(netuid, {"alpha_rao": 0, "as_tao_rao": 0, "hotkeys": set()})
        agg["alpha_rao"] += _rao(entry.get("balance"))
        agg["as_tao_rao"] += _rao(entry.get("balance_as_tao"))
        if entry.get("hotkey"):
            agg["hotkeys"].add(entry["hotkey"])
    alpha = [{"netuid": n, "alpha_rao": a["alpha_rao"], "as_tao_rao": a["as_tao_rao"], "hotkeys": len(a["hotkeys"])}
             for n, a in sorted(per_netuid.items()) if a["alpha_rao"] or a["as_tao_rao"]]

    parts = free + reserved + root + liquidity + sum(a["as_tao_rao"] for a in alpha)
    block = acct.get("block_number")
    try:
        block = int(block) if block is not None else None
    except (TypeError, ValueError):
        block = None
    return {"address": address, "as_of": acct["timestamp"], "block": block,
            "free_rao": free, "reserved_rao": reserved, "root_rao": root, "liquidity_rao": liquidity,
            "alpha": alpha, "alpha_as_tao_field_rao": alpha_field, "total_rao": total,
            "parts_rao": parts, "diff_rao": total - parts}
