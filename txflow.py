"""TxFlow view helpers - pure: no network, no DB, no web_portfolio import.

web_portfolio.py reads TxFlow's info API (POST https://api.txflow.com/info,
{"type": "clearinghouseState", "user": ...}) in a background cache and calls
open_position_rows on each stored answer. The verified TxFlow facts (coin
names with the quote, stops on the position's tpsl list, capitalised
leverage type, ...) are in tests/fixtures/txflow/README.md.
"""
# Shared Decimal / formatting helpers so TxFlow rows match Hyperliquid rows exactly.
from hl_trades import _dn, _q, _qp

# Multiplier that turns TxFlow's cumFunding.sinceOpen into Hyperliquid's convention (positive = PAID), the convention /api/trading/perps/open emits. -1 assumes TxFlow reports funding paid as a negative number, like its cumFee. UNCONFIRMED - checked before merge; set to 1 if the check disagrees.
FUNDING_TO_PAID_POSITIVE = -1
QUOTE_SUFFIX = "-USDC"


def coin_name(raw):
    """The bare coin: a trailing "-USDC" (any case) is stripped
    ("HYPE-USDC" -> "HYPE", "eth-usdc" -> "eth"); anything else is returned
    unchanged."""
    s = str(raw or "")
    if s.upper().endswith(QUOTE_SUFFIX):
        return s[:-len(QUOTE_SUFFIX)]
    return s


def open_position_rows(state):
    """The open-perps rows for one TxFlow clearinghouseState answer, with
    exactly the keys and string formats of hl_trades.open_position_rows.

    Rules:
    - state not a dict, or assetPositions not a list -> []. Entries that are
      not dicts, or whose "position" is not a dict, are skipped; so are
      positions whose szi is 0 or missing. direction = long when szi > 0,
      else short; size = |szi|; coin = coin_name(position.coin).
    - value = |positionValue|; mark = markPx when > 0 (passed through), else
      value / size (10 significant digits), else None.
    - unrealized_pct = (mark - entry) / entry x 100, negated for shorts (None
      without mark or entry, or when entry is 0).
    - Stops and take-profits come from the entry's "tpsl" list (TxFlow keeps
      them on the position, not in the open orders): stops are entries with
      slTriggerPrice > 0, take-profits those with tpTriggerPrice > 0. The stop
      is the tightest (long: highest trigger; short: lowest), the take-profit
      the nearest (long: lowest; short: highest). covered = size when the
      stop's quantity is missing, <= 0 or >= size, else that quantity; flag
      'stop_partial' when covered < size. if_stopped_pnl = (stop - entry) x
      covered, negated for shorts; stop_distance_pct = (stop - mark) / mark x
      100. No stop -> flag 'no_stop'. tpsl not a list -> flag
      'open_orders_unavailable' and stop / take-profit / if_stopped_pnl /
      stop_distance_pct None.
    - liquidation_px = liquidationPx when > 0, else None. leverage =
      leverage.value; leverage_type = leverage.type lower-cased ("Cross" ->
      "cross"). margin_used = marginUsed.
    - funding_since_open = cumFunding.sinceOpen x FUNDING_TO_PAID_POSITIVE
      (Hyperliquid's convention: positive = paid), None when missing.
    - Formats as hl_trades: entry / stop / tp / liquidation prices full
      precision (_qp), mark as above, every other number a 6-decimal string
      (_q), None when missing."""
    if not isinstance(state, dict) or not isinstance(state.get("assetPositions"), list):
        return []
    out = []
    for ap in state["assetPositions"]:
        if not isinstance(ap, dict) or not isinstance(ap.get("position"), dict):
            continue
        p = ap["position"]
        szi = _dn(p.get("szi"))
        if szi is None or szi == 0:
            continue
        long_ = szi > 0
        size = abs(szi)
        entry = _dn(p.get("entryPx"))
        pv = _dn(p.get("positionValue"))
        value = abs(pv) if pv is not None else None
        mark_px = _dn(p.get("markPx"))
        if mark_px is not None and mark_px > 0:
            mark, mark_text = mark_px, _qp(mark_px)
        elif value is not None and size:
            mark = value / size
            mark_text = _qp(mark, 10)
        else:
            mark, mark_text = None, None
        unrealized_pct = None
        if mark is not None and entry:
            unrealized_pct = (mark - entry) / entry * 100 * (1 if long_ else -1)

        flags = []
        stop = tp = if_stopped = distance = None
        tpsl = ap.get("tpsl")
        if not isinstance(tpsl, list):
            flags.append("open_orders_unavailable")
        else:
            entries = [t for t in tpsl if isinstance(t, dict)]
            stops = [t for t in entries if (_dn(t.get("slTriggerPrice")) or 0) > 0]
            tps = [t for t in entries if (_dn(t.get("tpTriggerPrice")) or 0) > 0]
            if stops:
                sl = lambda t: _dn(t.get("slTriggerPrice"))
                chosen = (max if long_ else min)(stops, key=sl)
                stop = sl(chosen)
                qty = _dn(chosen.get("quantity"))
                covered = size if qty is None or qty <= 0 or qty >= size else qty
                if covered < size:
                    flags.append("stop_partial")
                if entry is not None:
                    if_stopped = (stop - entry) * covered * (1 if long_ else -1)
                if mark:
                    distance = (stop - mark) / mark * 100
            else:
                flags.append("no_stop")
            if tps:
                tp_of = lambda t: _dn(t.get("tpTriggerPrice"))
                tp = tp_of((min if long_ else max)(tps, key=tp_of))

        liq = _dn(p.get("liquidationPx"))
        lev = p.get("leverage") if isinstance(p.get("leverage"), dict) else None
        lev_type = lev.get("type") if lev else None
        cum = p.get("cumFunding") if isinstance(p.get("cumFunding"), dict) else None
        since_open = _dn(cum.get("sinceOpen")) if cum else None
        out.append({"coin": coin_name(p.get("coin")), "direction": "long" if long_ else "short", "size": _q(size),
                    "entry_px": _qp(entry), "mark_px": mark_text, "position_value": _q(value),
                    "unrealized_pnl": _q(_dn(p.get("unrealizedPnl"))), "unrealized_pct": _q(unrealized_pct),
                    "stop_px": _qp(stop), "stop_distance_pct": _q(distance), "if_stopped_pnl": _q(if_stopped),
                    "tp_px": _qp(tp), "liquidation_px": _qp(liq if liq is not None and liq > 0 else None),
                    "leverage": lev.get("value") if lev else None,
                    "leverage_type": str(lev_type).lower() if lev_type is not None else None,
                    "margin_used": _q(_dn(p.get("marginUsed"))),
                    "funding_since_open": _q(since_open * FUNDING_TO_PAID_POSITIVE) if since_open is not None else None,
                    "flags": flags})
    return out
