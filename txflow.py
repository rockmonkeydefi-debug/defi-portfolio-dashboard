"""TxFlow view helpers - pure: no network, no DB, no web_portfolio import.

web_portfolio.py reads TxFlow's info API (POST https://api.txflow.com/info,
{"type": "clearinghouseState", "user": ...}) in a background cache and calls
open_position_rows on each stored answer. The verified TxFlow facts (coin
names with the quote, stops on the position's tpsl list, capitalised
leverage type, ...) are in tests/fixtures/txflow/README.md.

TxFlow trades (HANDOFF_trading_performance.md Commit 4c) reuse the
Hyperliquid cycle engine (hl_trades.build_cycles) on the stored userFills and
historicalOrders, after two conversions to Hyperliquid's conventions:
- to_hl_fills: a closing fill's closedPnl is NET of its fee on TxFlow;
  Hyperliquid's excludes it, so the fee is added back (exact Decimal).
- to_hl_orders: a position stop (isTrigger, isPositionTpsl or reduceOnly,
  orderType "Market", triggerCondition "Price below" on a sell / "Price
  above" on a buy) becomes a "Stop Market" reduce-only order, which the
  engine's initial-stop rule picks. Take-profits stay as they are.
TxFlow has no funding history (userFunding is refused), so funding comes
from readings of each open position's cumFunding.sinceOpen (same sign as
Hyperliquid's userFunding usdc: negative when paid): funding_rows uses the
latest reading inside each cycle as that cycle's funding, flagged
"funding_approx"; a cycle without a reading is flagged "funding_missing".
"""
from decimal import Context, localcontext

import hl_trades
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


def take_profits(state):
    """Every live take-profit per open position in one clearinghouseState
    answer (the Perps page's Target column), with open_position_rows' rules:
    take-profits are the position's "tpsl" entries with tpTriggerPrice > 0.
    Pure.

    Returns {coin_name(position.coin): [trigger prices, nearest first (long:
    lowest first; short: highest first), plain decimal strings at full
    precision (_qp), equal prices listed once]} for every open position (szi
    not 0) whose tpsl is a list - an empty list when it has none. A position
    whose tpsl is not a list is absent (unknown, not "none"); an odd state
    gives {}."""
    out = {}
    if not isinstance(state, dict) or not isinstance(state.get("assetPositions"), list):
        return out
    for ap in state["assetPositions"]:
        if not isinstance(ap, dict) or not isinstance(ap.get("position"), dict) or not isinstance(ap.get("tpsl"), list):
            continue
        p = ap["position"]
        szi = _dn(p.get("szi"))
        if szi is None or szi == 0:
            continue
        prices = {_dn(t.get("tpTriggerPrice")) for t in ap["tpsl"] if isinstance(t, dict)}
        prices = {x for x in prices if x is not None and x > 0}
        out[coin_name(p.get("coin"))] = [_qp(x) for x in sorted(prices, reverse=szi < 0)]
    return out


def to_hl_fills(fills):
    """Copies of TxFlow userFills rows in Hyperliquid's convention. A fill
    that REDUCES the position (end = startPosition + sz for side "B", - sz
    for "A", and |end| < |startPosition|) gets closedPnl = closedPnl + fee,
    as an exact Decimal string: TxFlow's closedPnl is net of the fee,
    Hyperliquid's is not. Every other fill is copied unchanged."""
    out = []
    for f in fills or []:
        g = dict(f)
        start, sz = _dn(f.get("startPosition")), _dn(f.get("sz"))
        if start is not None and sz is not None:
            end = start + sz if f.get("side") == "B" else start - sz
            if abs(end) < abs(start):
                with localcontext(Context(prec=100)):
                    g["closedPnl"] = str((_dn(f.get("closedPnl")) or 0) + (_dn(f.get("fee")) or 0))
        out.append(g)
    return out


def to_hl_orders(records):
    """Copies of TxFlow historicalOrders records in Hyperliquid's
    convention. An order with isTrigger true and (isPositionTpsl or
    reduceOnly) that is a STOP for the position it closes - side "A" with
    triggerCondition starting "Price below" (a long's stop), or side "B" with
    "Price above" (a short's stop) - gets orderType "Stop Market" and
    reduceOnly true. Take-profits and every other record are unchanged."""
    out = []
    for rec in records or []:
        r = dict(rec)
        o = rec.get("order") if isinstance(rec, dict) else None
        if isinstance(o, dict):
            o2 = dict(o)
            cond = str(o.get("triggerCondition") or "")
            is_stop = ((o.get("side") == "A" and cond.startswith("Price below"))
                       or (o.get("side") == "B" and cond.startswith("Price above")))
            if o.get("isTrigger") and (o.get("isPositionTpsl") or o.get("reduceOnly")) and is_stop:
                o2["orderType"] = "Stop Market"
                o2["reduceOnly"] = True
            r["order"] = o2
        out.append(r)
    return out


def to_hl_take_profits(records):
    """Copies of TxFlow historicalOrders records in which a position
    TAKE-PROFIT (isTrigger true, isPositionTpsl or reduceOnly, and side "A"
    with triggerCondition starting "Price above" - a long's take-profit - or
    side "B" with "Price below" - a short's) gets orderType "Take Profit
    Market" and reduceOnly true, so hl_trades.planned_targets picks it.
    Every other record is unchanged; the input is never modified. Separate
    from to_hl_orders, whose output (stops only) the cycle engine uses."""
    out = []
    for rec in records or []:
        r = dict(rec) if isinstance(rec, dict) else rec
        o = rec.get("order") if isinstance(rec, dict) else None
        if isinstance(o, dict):
            cond = str(o.get("triggerCondition") or "")
            is_tp = ((o.get("side") == "A" and cond.startswith("Price above"))
                     or (o.get("side") == "B" and cond.startswith("Price below")))
            if o.get("isTrigger") and (o.get("isPositionTpsl") or o.get("reduceOnly")) and is_tp:
                o2 = dict(o)
                o2["orderType"] = "Take Profit Market"
                o2["reduceOnly"] = True
                r["order"] = o2
        out.append(r)
    return out


def funding_rows(cycles, obs):
    """Hyperliquid-style funding rows from sinceOpen readings. cycles are
    hl_trades cycle dicts; obs are {"coin", "observed_ms", "since_open"}.
    Per cycle: the readings of the same coin (coin_name on both sides) with
    open_time < observed_ms <= (close_time, or no limit while open); the
    latest one becomes {"time": observed_ms, "delta": {"coin": the cycle's
    coin, "usdc": since_open, "szi": None, "nSamples": None}} (an hourly-style
    row, so the engine books it to that cycle). Returns (rows, {trade_key:
    True when a reading was found, else False})."""
    rows, found = [], {}
    for cy in cycles:
        coin = coin_name(cy.get("coin"))
        close = cy.get("close_time")
        hit = [o for o in obs or []
               if coin_name(o.get("coin")) == coin
               and cy["open_time"] < int(o["observed_ms"]) and (close is None or int(o["observed_ms"]) <= close)]
        if hit:
            last = max(hit, key=lambda o: int(o["observed_ms"]))
            rows.append({"time": int(last["observed_ms"]),
                         "delta": {"coin": cy.get("coin"), "usdc": last["since_open"], "szi": None,
                                   "nSamples": None}})
        found[cy["trade_key"]] = bool(hit)
    return rows, found


def build_cycles(wallet, fills, records, obs):
    """TxFlow trades for one wallet through the Hyperliquid engine. Pass 1:
    hl_trades.build_cycles("txflow|" + wallet, to_hl_fills(fills), [],
    to_hl_orders(records)); funding_rows on its cycles; pass 2: the same call
    with those rows as funding. Returns pass 2 with every cycle flagged
    "funding_approx" (a reading was found) or "funding_missing" (none). The
    "txflow|" prefix keeps trade_keys distinct from Hyperliquid's for the
    same address."""
    key = "txflow|" + wallet
    hl_fills, hl_orders = to_hl_fills(fills), to_hl_orders(records)
    first = hl_trades.build_cycles(key, hl_fills, [], hl_orders)
    rows, found = funding_rows(first["cycles"], obs)
    second = hl_trades.build_cycles(key, hl_fills, rows, hl_orders)
    for cy in second["cycles"]:
        cy["flags"].append("funding_approx" if found.get(cy["trade_key"]) else "funding_missing")
    return second


def live_stops(state):
    """The live position stops in one clearinghouseState answer:
    {coin_name(position.coin): {"px": the tightest stop (long: highest
    slTriggerPrice; short: lowest) at full precision, "set_at_ms": that tpsl
    entry's createTime}}. Positions without a stop (or with szi 0) are
    absent; an odd shape gives {}."""
    out = {}
    if not isinstance(state, dict) or not isinstance(state.get("assetPositions"), list):
        return out
    for ap in state["assetPositions"]:
        if not isinstance(ap, dict) or not isinstance(ap.get("position"), dict) or not isinstance(ap.get("tpsl"), list):
            continue
        p = ap["position"]
        szi = _dn(p.get("szi"))
        if not szi:
            continue
        sl = lambda t: _dn(t.get("slTriggerPrice"))
        stops = [t for t in ap["tpsl"] if isinstance(t, dict) and (sl(t) or 0) > 0]
        if not stops:
            continue
        chosen = (max if szi > 0 else min)(stops, key=sl)
        out[coin_name(p.get("coin"))] = {"px": _qp(sl(chosen)), "set_at_ms": chosen.get("createTime")}
    return out
