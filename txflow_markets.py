"""TxFlow market helpers for the Trends scanner (Landing 53) - pure: no
network, no DB, no web_portfolio import.

TxFlow's info API (POST https://api.txflow.com/info, no signing) answers
`spotMeta` (every token TxFlow lists, perps included) and `candleSnapshot`
(under the bare name, e.g. "BTC", not "BTC-USDC"); most other read types are
refused (SPEC_txflow_trends.md, recons of Oct 19). So the scan builds its own
market list: this module holds the parts that need no I/O.

- Which TxFlow tokens are the SAME asset as a Hyperliquid market the scan
  already covers (name or confirmed alias, and a last price within 5% of
  Hyperliquid's) - those Hyperliquid rows get a TxFlow link / "On TxFlow" tag.
  A same-name token with a different price (TxFlow QNT 198 vs xyz QNT 38.2)
  is a mismatch: TxFlow's own market, shown as TxFlow-only. A price missing on
  either side is "unknown": no tag and no TxFlow-only row, so a failed call
  cannot create a duplicate row for an asset Hyperliquid already covers.
- The rows TxFlow alone lists are stored under "txflow:<NAME>" so they never
  collide with a bare Hyperliquid name in noodle_state.
- 24h volume from closed hourly bars (the $50k floor), the candle request
  body and the answer parsers.

[Unverified] The request body below is Hyperliquid's candleSnapshot shape;
the spec records TxFlow's depths and bar fields, not the body.
"""
import math
import re

STORED_PREFIX = "txflow:"
PRICE_TOLERANCE = 0.05          # same asset when the last prices are within 5%
HOUR_SECONDS = 3600
MATCH_PRICE_MAX_AGE_SECONDS = 2 * HOUR_SECONDS   # a match-table price older than this is "unknown"

# TxFlow token name -> the Hyperliquid name it is the same asset as (all
# price-confirmed in the Oct 19 recon: ratios within ~0.5%).
TXFLOW_ALIASES = {
    "XAU": "GOLD", "XAG": "SILVER", "XPT": "PLATINUM", "XPD": "PALLADIUM",
    "BZ": "BRENTOIL", "SAMSUNG": "SMSN", "USDJPY": "JPY", "EURUSD": "EUR",
    "QNTX": "QNT",
}
STABLECOINS = frozenset({"USDC", "USDT", "USDE", "DAI", "FDUSD", "USDH", "USDS", "PYUSD", "USDD", "USD1"})
# Skipped outright: stablecoins, and XAUT (the same gold as XAU, less volume).
IGNORED = STABLECOINS | frozenset({"XAUT"})

_INTERVAL_MS = {
    "1h": 3600 * 1000, "4h": 4 * 3600 * 1000, "12h": 12 * 3600 * 1000,
    "1d": 24 * 3600 * 1000,
}


class MatchAborted(Exception):
    """Raised by a price function to stop build_match (the API looks locked);
    build_match lets it through, every other error is just 'price unknown'."""


# ── names ──────────────────────────────────────────────────────────────

def hl_name_for(txflow_name):
    """The UPPER Hyperliquid-side name a TxFlow token would carry: the confirmed
    alias when there is one, "1000X" -> "KX" (TxFlow 1000BONK is Hyperliquid's
    kBONK; the scan's name lists are UPPER-keyed), else the name upper-cased."""
    up = str(txflow_name or "").strip().upper()
    if up in TXFLOW_ALIASES:
        return TXFLOW_ALIASES[up]
    m = re.fullmatch(r"1000([A-Z][A-Z0-9]*)", up)       # 1000 + a ticker, not 1000000MOG
    if m:
        return "K" + m.group(1)
    return up


def is_ignored(txflow_name):
    return str(txflow_name or "").strip().upper() in IGNORED


def stored_symbol(txflow_name):
    """The noodle_state symbol of a TxFlow-only market."""
    return STORED_PREFIX + str(txflow_name)


def is_stored_symbol(symbol):
    return str(symbol or "").startswith(STORED_PREFIX)


def bare_name(symbol):
    """The TxFlow name inside a stored symbol; any other symbol unchanged."""
    s = str(symbol or "")
    return s[len(STORED_PREFIX):] if s.startswith(STORED_PREFIX) else s


# ── answers and requests ──────────────────────────────────────────────

def parse_spot_meta(answer):
    """The token names of a TxFlow spotMeta answer ({"tokens": [{"name": ...}]}),
    first occurrence of each (RAY is listed twice), in the answer's order.
    Anything else -> []."""
    if not isinstance(answer, dict) or not isinstance(answer.get("tokens"), list):
        return []
    seen, out = set(), []
    for tok in answer["tokens"]:
        name = tok.get("name") if isinstance(tok, dict) else None
        if not isinstance(name, str):
            continue
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def parse_candles(raw):
    """TxFlow candle answer -> the scan's candle dicts {open, high, low,
    close, volume, time} (time in epoch SECONDS; the answer's t is
    milliseconds [Inference: same as Hyperliquid's]), oldest first, one per
    open time. Malformed bars (and bars with a non-finite number) are
    skipped. A non-list answer, or a non-empty answer with no usable bar
    (the bar fields are not the ones expected), raises ValueError: both are
    an error, never a quiet empty series. An empty list is a market with no
    bars and returns []."""
    if not isinstance(raw, list):
        raise ValueError("candleSnapshot answer is not a list")
    by_time = {}
    for c in raw:
        try:
            t = int(c["t"]) // 1000
            bar = {"open": float(c["o"]), "high": float(c["h"]), "low": float(c["l"]),
                   "close": float(c["c"]), "volume": float(c["v"]), "time": t}
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not all(math.isfinite(bar[k]) for k in ("open", "high", "low", "close", "volume")):
            continue
        by_time[t] = bar
    if raw and not by_time:
        raise ValueError("candleSnapshot answer has no usable bars")
    return [by_time[k] for k in sorted(by_time)]


def candle_request(name, interval, limit, now_ms):
    """The candleSnapshot body for `limit` bars of `interval` ending at
    now_ms, under the bare TxFlow name."""
    ms = _INTERVAL_MS[interval]
    return {"type": "candleSnapshot", "req": {
        "coin": str(name), "interval": interval,
        "startTime": int(now_ms) - ms * int(limit), "endTime": int(now_ms)}}


def volume_24h(candles_1h, now_ts):
    """~24h notional volume: sum of volume x close over the 24 CLOSED hourly
    bars before the hour now_ts is in (by open time, not 'the last 24 bars':
    a thin market can have missing hours, which count as no volume). 0.0 when
    none qualify."""
    total = 0.0
    end = (int(now_ts) // HOUR_SECONDS) * HOUR_SECONDS      # open of the still-forming bar
    lo = end - 24 * HOUR_SECONDS
    for c in candles_1h or []:
        t = c.get("time")
        if t is None or t < lo or t >= end:
            continue
        total += float(c.get("volume") or 0.0) * float(c.get("close") or 0.0)
    return total


def last_close(candles, now_ts, max_age=MATCH_PRICE_MAX_AGE_SECONDS):
    """The newest bar's close, or None when there is no bar or the newest one
    opened more than max_age seconds before now_ts (a market that has not
    traded lately has no current price to compare)."""
    if not candles:
        return None
    last = candles[-1]
    t = last.get("time")
    if t is None or now_ts - t > max_age:
        return None
    return last.get("close")


# ── matching ────────────────────────────────────────────────────────────

def classify(txflow_name, hl_prices, txflow_price, tol=PRICE_TOLERANCE):
    """('ignored'|'only'|'unknown'|'tagged'|'mismatch', UPPER Hyperliquid name
    or None) for one TxFlow token.

    hl_prices: {UPPER Hyperliquid name: [last price, ...]} for every perp the
    scan's list holds (the scan's list keeps one entry per name today, but a
    name on both the main and the xyz exchange may carry several prices).
    'only': the name (or alias) is on neither exchange.
    'tagged': a price within tol of TxFlow's. 'mismatch': both prices known
    and none close. 'unknown': a usable price is missing on either side."""
    if is_ignored(txflow_name):
        return "ignored", None
    key = hl_name_for(txflow_name)
    if key not in hl_prices:
        return "only", None
    prices = [q for q in (_usable_price(p) for p in hl_prices[key]) if q is not None]
    txflow_price = _usable_price(txflow_price)
    if txflow_price is None or not prices:
        return "unknown", key
    if any(abs(txflow_price - p) <= tol * p for p in prices):
        return "tagged", key
    return "mismatch", key


def build_match(tokens, hl_prices, price_fn, previous=None, tol=PRICE_TOLERANCE, heartbeat=None):
    """The match table for a token list.

    price_fn(name) -> TxFlow's last price (may raise: that token is then
    'unknown'; MatchAborted stops the build and propagates). Names TxFlow
    shares with no Hyperliquid market need no price call. `previous` (an
    earlier table) supplies the answer for 'unknown' tokens: a tag or a
    TxFlow-only entry it held is kept, otherwise the token is left out.
    heartbeat(done, total) is called after each token.

    Returns {"tags": {UPPER Hyperliquid name: TxFlow name}, "only": [TxFlow
    names], "unknown": [...], "mismatch": [...], "retry": [...]}; tags and only
    are what the scan and the route use. "retry" is the part of "unknown"
    that is TxFlow's price missing while Hyperliquid's is usable: worth asking
    again soon (a Hyperliquid price missing stays missing until Hyperliquid
    lists one)."""
    prev = clean_match(previous) or {"tags": {}, "only": []}
    tags, only, unknown, mismatch, retry = {}, [], [], [], []
    names = list(tokens or [])
    for i, name in enumerate(names):
        if is_ignored(name):
            pass
        elif hl_name_for(name) not in hl_prices:
            only.append(name)
        else:
            try:
                px = price_fn(name)
            except MatchAborted:
                raise
            except Exception:
                px = None
            kind, key = classify(name, hl_prices, px, tol)
            if kind == "tagged":
                tags.setdefault(key, name)
            elif kind == "mismatch":
                only.append(name)
                mismatch.append(name)
            else:  # unknown
                unknown.append(name)
                if any(_usable_price(p) is not None for p in hl_prices[key]):
                    retry.append(name)     # Hyperliquid's price is usable, so TxFlow's is what is missing
                if prev["tags"].get(key) == name:
                    tags.setdefault(key, name)
                elif name in prev["only"]:
                    only.append(name)
        if heartbeat is not None:
            heartbeat(i + 1, len(names))
    return {"tags": tags, "only": only, "unknown": unknown, "mismatch": mismatch, "retry": retry}


def _usable_price(p):
    """p as a positive float, else None."""
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or p <= 0:
        return None
    return float(p)


def clean_match(obj):
    """A stored/cached match table checked and trimmed to {"tags": {str: str},
    "only": [str], "built_at": float|None}, or None when it is not one."""
    if not isinstance(obj, dict):
        return None
    tags, only = obj.get("tags"), obj.get("only")
    if not isinstance(tags, dict) or not isinstance(only, list):
        return None
    clean_tags = {str(k).upper(): str(v) for k, v in tags.items()
                  if isinstance(k, str) and isinstance(v, str) and k and v}
    clean_only = []
    for n in only:
        if isinstance(n, str) and n and n not in clean_only:
            clean_only.append(n)
    built = obj.get("built_at")
    built = float(built) if isinstance(built, (int, float)) and not isinstance(built, bool) else None
    return {"tags": clean_tags, "only": clean_only, "built_at": built}


def candidates(tokens, match):
    """The TxFlow-only names to scan: match['only'] that TxFlow still lists,
    in the token list's order, each once."""
    m = clean_match(match)
    if not m:
        return []
    listed = set(tokens or [])
    return [n for n in dict.fromkeys(m["only"]) if n in listed]


def txflow_name_for(symbol, tags):
    """The TxFlow market name for one noodle_state symbol, or None: a stored
    TxFlow-only symbol carries it; a Hyperliquid symbol looks it up in tags
    (UPPER-keyed)."""
    s = str(symbol or "")
    if is_stored_symbol(s):
        return bare_name(s) or None
    return (tags or {}).get(s.strip().upper())
