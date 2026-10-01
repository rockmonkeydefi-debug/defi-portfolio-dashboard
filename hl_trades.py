"""Hyperliquid perp trades (cycles) from stored fills, funding and order
history - HANDOFF_trading_performance.md rulings 6, 7 and 8, Commit 3.

PURE: stdlib only (decimal), no Flask, no DB, no network. web_portfolio.py
loads the stored raw rows and calls build_cycles; money math is Decimal from
the raw strings, never float.

Rules (the R1-R9 contract of the trade-engine fixtures, with the additions
noted):
- Ordering: chain_order orders each coin's fills by time and, within one
  timestamp, follows the startPosition chain (the next fill starts where the
  running position stands). Input order and tid are never relied on; when the
  chain cannot be followed the fills fall back to tid order and the cycle is
  flagged 'chain_gap'.
- Opening vs closing comes from position math, not the dir string: a fill
  from 0, or growing |position| on the same sign, opens; shrinking |position|
  closes; a sign change is a FLIP, split into a closing part (size
  |startPosition|, carrying all of closedPnl) and an opening part (the rest),
  the fee split pro rata by size, both cycles flagged 'flip_split'. A cycle
  opens when the position leaves 0 and closes when it returns to 0.
- A fill with a truthy 'liquidation' key, or 'Liquidat' in dir, flags its
  cycle 'liquidated'.
- Fills seen while no cycle is open and startPosition != 0 (a position opened
  before the window) are skipped until the position next returns to 0 (or
  flips, whose opening part starts a cycle); they are counted in
  skipped_partial_fills.
- direction = the sign of the opening position; peak_size = max |position|;
  avg_entry / avg_exit = size-weighted px of the opening / closing parts;
  gross = sum(closedPnl); fees = sum(fee + builderFee) (closedPnl excludes
  fees); net = gross - fees + funding.
- Funding: hourly rows (nSamples null) belong to the cycle of that coin with
  open < time <= close; daily totals (nSamples set, [time, time + DAY_MS))
  are split across overlapping cycles of that coin pro rata by overlap
  duration; anything else is unattributed.
- Initial stop: standalone order records only (children ignored) with
  isTrigger, reduceOnly, 'Stop' in orderType, triggerPx > 0, the same coin
  and the side opposing the position (A for long, B for short). An order ends
  at the latest statusTimestamp of any non-'open' record of its oid. Pick the
  latest-placed candidate with open - STOP_LOOKBACK_MS <= placed <= open and
  end > open (or no end); else the earliest-placed with open < placed <=
  close. None -> flag 'stop_missing'.
- R = net / (|avg_entry - stop| x peak_size); None while open or without a
  stop.
"""
from decimal import Decimal

DAY_MS = 86400000
STOP_LOOKBACK_MS = 3 * DAY_MS
_INF = 10 ** 16
_Q = Decimal("0.000001")
_ZERO = Decimal(0)


def _d(v):
    """Decimal from a raw API value (string or number); None / '' -> 0."""
    if v is None or v == "":
        return _ZERO
    return Decimal(str(v))


def _q(x):
    return None if x is None else str(x.quantize(_Q))


def _end(f):
    """The position after a fill: startPosition + sz for side B, - sz for A."""
    sz = _d(f.get("sz"))
    return _d(f.get("startPosition")) + (sz if f.get("side") == "B" else -sz)


def _sign(x):
    return (x > 0) - (x < 0)


def chain_order(fills):
    """Order fills per coin: by time, and within one timestamp by the
    startPosition chain. Returns (ordered fills, set of tids picked out of
    chain). The first fill of a timestamp is the one starting at the running
    position, else the group's unique chain head (a fill whose startPosition
    is no other fill's end); after it, each next fill must start where the
    previous one ended. Where neither holds, the lowest tid is taken and its
    tid is reported as a gap."""
    by_coin = {}
    for f in fills or []:
        by_coin.setdefault(f.get("coin"), []).append(f)
    first_time = {c: min(int(f["time"]) for f in fs) for c, fs in by_coin.items()}
    ordered, gaps = [], set()
    for coin in sorted(by_coin, key=lambda c: (first_time[c], str(c))):
        fs = sorted(by_coin[coin], key=lambda f: (int(f["time"]), int(f["tid"])))
        pos = None
        i = 0
        while i < len(fs):
            j = i
            while j < len(fs) and int(fs[j]["time"]) == int(fs[i]["time"]):
                j += 1
            remaining = fs[i:j]
            first = True
            while remaining:
                pick = None
                if pos is not None:
                    pick = next((f for f in remaining if _d(f.get("startPosition")) == pos), None)
                if pick is None:
                    if first:
                        ends = [(_end(g), g) for g in remaining]
                        heads = [f for f in remaining
                                 if not any(e == _d(f.get("startPosition")) for e, g in ends if g is not f)]
                        pick = heads[0] if heads else remaining[0]
                        if len(heads) != 1 and len(remaining) > 1:
                            gaps.add(int(pick["tid"]))
                    else:
                        pick = remaining[0]
                        gaps.add(int(pick["tid"]))
                remaining.remove(pick)
                ordered.append(pick)
                pos = _end(pick)
                first = False
            i = j
    return ordered, gaps


def _new_cycle(wallet, f, direction):
    return {"wallet": wallet, "coin": f.get("coin"), "direction": direction,
            "open_time": int(f["time"]), "close_time": None, "first_tid": int(f["tid"]), "fill_count": 0,
            "peak": _ZERO, "en": _ZERO, "es": _ZERO, "xn": _ZERO, "xs": _ZERO,
            "gross": _ZERO, "fees": _ZERO, "funding": _ZERO, "flags": []}


def _flag(cy, name):
    if cy is not None and name not in cy["flags"]:
        cy["flags"].append(name)


def _build_raw_cycles(wallet, fills):
    ordered, gaps = chain_order(fills)
    cycles, cur, running = [], {}, {}
    skipped = 0
    for f in ordered:
        coin = f.get("coin")
        s = _d(f.get("startPosition"))
        sz = _d(f.get("sz"))
        e = _end(f)
        px = _d(f.get("px"))
        fee = _d(f.get("fee")) + _d(f.get("builderFee"))
        pnl = _d(f.get("closedPnl"))
        liq = bool(f.get("liquidation")) or "Liquidat" in str(f.get("dir") or "")
        gap = int(f["tid"]) in gaps
        cy = cur.get(coin)
        if cy is not None and coin in running and running[coin] != s:
            _flag(cy, "chain_gap")
        running[coin] = e

        if s != 0 and e != 0 and _sign(s) != _sign(e):
            kind = "flip"
        elif s == 0 or (_sign(s) == _sign(e) and abs(e) > abs(s)):
            kind = "open"
        else:
            kind = "close"

        if kind == "open":
            if s == 0:
                if cy is not None:          # the previous cycle never returned to 0
                    _flag(cy, "chain_gap")
                if e == 0:                  # zero-size fill from 0: nothing to open
                    continue
                cy = cur[coin] = _new_cycle(wallet, f, "long" if e > 0 else "short")
                cycles.append(cy)
            elif cy is None:
                skipped += 1
                continue
            cy["fill_count"] += 1
            cy["en"] += px * sz
            cy["es"] += sz
            cy["gross"] += pnl
            cy["fees"] += fee
            cy["peak"] = max(cy["peak"], abs(e))
            if liq:
                _flag(cy, "liquidated")
            if gap:
                _flag(cy, "chain_gap")
        elif kind == "close":
            if cy is None:
                skipped += 1
                continue
            cy["fill_count"] += 1
            cy["xn"] += px * sz
            cy["xs"] += sz
            cy["gross"] += pnl
            cy["fees"] += fee
            cy["peak"] = max(cy["peak"], abs(e))
            if liq:
                _flag(cy, "liquidated")
            if gap:
                _flag(cy, "chain_gap")
            if e == 0:
                cy["close_time"] = int(f["time"])
                del cur[coin]
        else:                               # flip: close |s|, open the rest
            close_sz = abs(s)
            open_sz = sz - close_sz
            fee_close = fee * close_sz / sz if sz else _ZERO
            fee_open = fee - fee_close
            if cy is None:
                skipped += 1
            else:
                cy["fill_count"] += 1
                cy["xn"] += px * close_sz
                cy["xs"] += close_sz
                cy["gross"] += pnl
                cy["fees"] += fee_close
                cy["peak"] = max(cy["peak"], abs(s))
                cy["close_time"] = int(f["time"])
                _flag(cy, "flip_split")
                if liq:
                    _flag(cy, "liquidated")
                if gap:
                    _flag(cy, "chain_gap")
            ny = cur[coin] = _new_cycle(wallet, f, "long" if e > 0 else "short")
            cycles.append(ny)
            ny["fill_count"] += 1
            ny["en"] += px * open_sz
            ny["es"] += open_sz
            ny["fees"] += fee_open
            ny["peak"] = abs(e)
            _flag(ny, "flip_split")
            if gap:
                _flag(ny, "chain_gap")
    return cycles, skipped


def _attribute_funding(cycles, funding):
    unattributed = _ZERO
    rows = sorted(funding or [], key=lambda r: int(r.get("time") or 0))
    for row in rows:
        d = row.get("delta") or {}
        t = int(row.get("time") or 0)
        amt = _d(d.get("usdc"))
        mine = [cy for cy in cycles if cy["coin"] == d.get("coin")]
        if d.get("nSamples") is None:
            hit = [cy for cy in mine if cy["open_time"] < t <= (cy["close_time"] or _INF)]
            if hit:
                hit[0]["funding"] += amt
            else:
                unattributed += amt
        else:
            ov = []
            for cy in mine:
                a, b = max(cy["open_time"], t), min(cy["close_time"] or _INF, t + DAY_MS)
                if b > a:
                    ov.append((cy, b - a))
            tot = sum(x[1] for x in ov)
            if not ov:
                unattributed += amt
            for cy, dur in ov:
                cy["funding"] += amt * Decimal(dur) / Decimal(tot)
    return unattributed


def _pick_stops(cycles, orders):
    ends, cands = {}, {}
    for h in orders or []:
        o = h.get("order") or {}
        oid = o.get("oid")
        if h.get("status") != "open":
            ends[oid] = max(ends.get(oid, 0), int(h.get("statusTimestamp") or 0))
        if (o.get("isTrigger") and o.get("reduceOnly") and "Stop" in str(o.get("orderType") or "")
                and _d(o.get("triggerPx")) > 0):
            cands[(oid, o.get("timestamp"))] = {"coin": o.get("coin"), "side": o.get("side"),
                                                "px": _d(o.get("triggerPx")), "placed": int(o.get("timestamp")),
                                                "oid": oid}
    for cy in cycles:
        side = "A" if cy["direction"] == "long" else "B"
        mine = [s for s in cands.values() if s["coin"] == cy["coin"] and s["side"] == side]
        op = cy["open_time"]
        cl = cy["close_time"] or _INF
        alive = [s for s in mine if op - STOP_LOOKBACK_MS <= s["placed"] <= op and ends.get(s["oid"], _INF) > op]
        after = [s for s in mine if op < s["placed"] <= cl]
        pick = (max(alive, key=lambda s: s["placed"]) if alive
                else (min(after, key=lambda s: s["placed"]) if after else None))
        cy["stop"] = pick["px"] if pick else None
        cy["stop_placed"] = pick["placed"] if pick else None
        if pick is None:
            _flag(cy, "stop_missing")


def _summarize(cy):
    avg_in = cy["en"] / cy["es"] if cy["es"] else None
    avg_out = cy["xn"] / cy["xs"] if cy["xs"] else None
    net = cy["gross"] - cy["fees"] + cy["funding"]
    r = None
    if cy["stop"] is not None and cy["close_time"] is not None and avg_in is not None:
        risk = abs(avg_in - cy["stop"]) * cy["peak"]
        if risk:
            r = net / risk
    return {"wallet": cy["wallet"], "coin": cy["coin"], "direction": cy["direction"],
            "status": "closed" if cy["close_time"] else "open",
            "open_time": cy["open_time"], "close_time": cy["close_time"], "first_tid": cy["first_tid"],
            "fill_count": cy["fill_count"], "peak_size": _q(cy["peak"]), "avg_entry": _q(avg_in),
            "avg_exit": _q(avg_out), "gross_closed_pnl": _q(cy["gross"]), "fees": _q(cy["fees"]),
            "funding": _q(cy["funding"]), "net_pnl": _q(net), "initial_stop": _q(cy["stop"]),
            "stop_placed": cy["stop_placed"], "r_multiple": _q(r),
            "flags": list(cy["flags"]), "stop_source": "hl_order" if cy["stop"] is not None else None,
            "trade_key": f"{cy['wallet']}|{cy['coin']}|{cy['first_tid']}"}


def build_cycles(wallet, fills, funding, orders):
    """Perp cycles for one wallet from its raw userFillsByTime rows, userFunding
    rows and historicalOrders records. Returns {"cycles": [...] (oldest
    open_time first), "unattributed_funding": 6-decimal str,
    "skipped_partial_fills": int}. Spot ('@N') fills are ignored."""
    perp_fills = [f for f in fills or [] if not str(f.get("coin") or "").startswith("@")]
    cycles, skipped = _build_raw_cycles(wallet, perp_fills)
    unattributed = _attribute_funding(cycles, funding)
    _pick_stops(cycles, orders)
    out = [_summarize(cy) for cy in sorted(cycles, key=lambda c: (c["open_time"], c["first_tid"]))]
    return {"cycles": out, "unattributed_funding": _q(unattributed), "skipped_partial_fills": skipped}


def _dn(v):
    """Decimal from a raw API value, or None when missing or not a number."""
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v))
    except Exception:
        return None
    return d if d.is_finite() else None


def open_position_rows(positions, open_orders):
    """The open-perps view for one wallet (the Dashboard OPEN PERPS card):
    one row per position from the accounts cache's per-position fields
    (web_portfolio._hl_positions_from_state) plus its live stop / take-profit
    from frontendOpenOrders. Pure; Decimal from the raw strings.

    Rules:
    - Positions with szi 0 or missing are skipped. direction = long when szi
      > 0, else short; size = |szi|; value = |position_value|; mark = value /
      size (None when either is missing or size is 0).
    - unrealized_pct = (mark - entry) / entry x 100, negated for shorts (None
      without mark or entry).
    - Candidate orders: same coin, isTrigger, reduceOnly or isPositionTpsl,
      the closing side (A for a long, B for a short), triggerPx > 0. Stops
      have 'Stop' in orderType, take-profits 'Take Profit'. The stop is the
      tightest one (long: highest triggerPx; short: lowest); the take-profit
      the nearest (long: lowest; short: highest).
    - covered = size when the chosen stop's sz is 0 (a position TP/SL covers
      the whole position) or >= size, else its sz; flag 'stop_partial' when
      covered < size. if_stopped_pnl = (stop - entry) x covered, negated for
      shorts. stop_distance_pct = (stop - mark) / mark x 100.
    - Flags: 'no_stop' when open_orders is a list with no stop candidate;
      'open_orders_unavailable' when open_orders is None (the read failed) -
      then stop, take-profit, if_stopped_pnl and stop_distance_pct are None.

    Each row: {coin, direction, size, entry_px, mark_px, position_value,
    unrealized_pnl, unrealized_pct, stop_px, stop_distance_pct,
    if_stopped_pnl, tp_px, liquidation_px, leverage, leverage_type,
    margin_used, funding_since_open (raw, unchanged), flags}; numbers are
    6-decimal strings or None, leverage / leverage_type pass through."""
    orders = [o for o in open_orders if isinstance(o, dict)] if isinstance(open_orders, list) else None
    out = []
    for p in positions or []:
        if not isinstance(p, dict):
            continue
        szi = _dn(p.get("szi"))
        if szi is None or szi == 0:
            continue
        long_ = szi > 0
        size = abs(szi)
        entry = _dn(p.get("entry_px"))
        pv = _dn(p.get("position_value"))
        value = abs(pv) if pv is not None else None
        mark = value / size if value is not None and size else None
        unrealized_pct = None
        if mark is not None and entry:
            unrealized_pct = (mark - entry) / entry * 100 * (1 if long_ else -1)

        flags = []
        stop = tp = if_stopped = distance = None
        if orders is None:
            flags.append("open_orders_unavailable")
        else:
            close_side = "A" if long_ else "B"
            cands = [o for o in orders
                     if o.get("coin") == p.get("coin") and o.get("isTrigger")
                     and (o.get("reduceOnly") or o.get("isPositionTpsl"))
                     and o.get("side") == close_side and (_dn(o.get("triggerPx")) or 0) > 0]
            stops = [o for o in cands if "Stop" in str(o.get("orderType") or "")]
            tps = [o for o in cands if "Take Profit" in str(o.get("orderType") or "")]
            px = lambda o: _dn(o.get("triggerPx"))
            if stops:
                chosen = (max if long_ else min)(stops, key=px)
                stop = px(chosen)
                stop_sz = _dn(chosen.get("sz")) or _ZERO
                covered = size if stop_sz == 0 or stop_sz >= size else stop_sz
                if covered < size:
                    flags.append("stop_partial")
                if entry is not None:
                    if_stopped = (stop - entry) * covered * (1 if long_ else -1)
                if mark:
                    distance = (stop - mark) / mark * 100
            else:
                flags.append("no_stop")
            if tps:
                tp = px((min if long_ else max)(tps, key=px))

        out.append({"coin": p.get("coin"), "direction": "long" if long_ else "short", "size": _q(size),
                    "entry_px": _q(entry), "mark_px": _q(mark), "position_value": _q(value),
                    "unrealized_pnl": _q(_dn(p.get("unrealized_pnl"))), "unrealized_pct": _q(unrealized_pct),
                    "stop_px": _q(stop), "stop_distance_pct": _q(distance), "if_stopped_pnl": _q(if_stopped),
                    "tp_px": _q(tp), "liquidation_px": _q(_dn(p.get("liquidation_px"))),
                    "leverage": p.get("leverage"), "leverage_type": p.get("leverage_type"),
                    "margin_used": _q(_dn(p.get("margin_used"))),
                    "funding_since_open": p.get("cum_funding_since_open"), "flags": flags})
    return out
