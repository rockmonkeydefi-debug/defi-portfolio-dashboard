"""Spot trades (HANDOFF_trading_performance.md rulings 4, 7 and 11) - pure: no
DB, no network, no web_portfolio import.

A spot trade is a position cycle: it opens when a position's units go from
zero to positive and closes when its remaining units fall to DUST_FRACTION
(1%) or less of the cycle's peak. Adds and partial sells stay inside the
trade. Dollar P/L is FIFO's realized P/L, split per trade: build() keeps FIFO
lots IDENTICAL to web_portfolio._calculate_spot_fifo (same order, same
matching loop, same 1e-9 tolerances, price = total / units), so per position
the trades' realized P/L plus the orphan sells' realized P/L equals FIFO's
realized_pnl (parity() checks it). Floats throughout, matching FIFO's
arithmetic.

Known effect of the dust rule: dust left by a closed trade stays in FIFO's
lots, and its (tiny) cost lands in whichever later sell consumes it - an
after-close sell of the dust, or the first sell of the next trade.
"""
from collections import deque
from decimal import Decimal

# A trade closes when its remaining units fall to <= this fraction of its peak (HANDOFF ruling 4; tunable).
DUST_FRACTION = 0.01
# The absolute floor for that close test (= FIFO's open-position threshold).
MIN_OPEN_UNITS = 1e-6


def _new_trade(key, row):
    return {"trade_key": key + "|" + str(row["id"]), "key": key, "symbol": str(row["symbol"]).upper(),
            "status": "open", "open_date": row["trade_date"], "close_date": None, "close_id": None,
            "first_buy_id": row["id"], "buy_ids": [], "sell_ids": [],
            "units_bought": 0.0, "units_sold": 0.0, "peak_units": 0.0,
            "cost_in": 0.0, "proceeds": 0.0, "realized_pnl": 0.0, "after_close_realized": 0.0,
            "last_sell_date": None, "flags": []}


def _flag(trade, flag):
    if flag not in trade["flags"]:
        trade["flags"].append(flag)


def build(rows):
    """Spot trades and orphan sells from spot_transactions rows.

    rows: ALREADY in FIFO order (_calculate_spot_fifo's ORDER BY id, then
    sorted by (parsed trade_date or 0, id)). Each row is a dict with id, key
    (the stringified position key), symbol, side, units (float), total (float:
    price_usd, the TOTAL incl. fees) and trade_date (the stored string).

    One pass. Per key: FIFO lots exactly as _calculate_spot_fifo keeps them,
    the open trade (None when none) and the last trade.
    - side (lower-cased) not 'buy' / 'sell': ignored, as FIFO does.
    - buy: the lot is appended exactly as FIFO does (price = total / units if
      units > 1e-12 else 0.0). units <= 1e-12: the row joins the open trade's
      buy_ids if one is open (nothing else changes), else it is ignored (no
      trade opens). Otherwise, with no trade open, a new trade opens:
      trade_key = key + "|" + row id, first_buy_id = row id, open_date =
      trade_date, status "open", flags [], counters 0. Then on the open trade:
      units_bought += units; cost_in += total; buy_ids gets the id;
      peak_units = max(peak_units, units_bought - units_sold).
    - sell: FIFO's matching loop gives the matched cost basis C and the
      unmatched units U. orphan_part = U x price when U > 1e-9, else 0.0;
      trade_part = total - C - orphan_part (so orphan_part + trade_part ==
      total - C, FIFO's realized for this sell); matched_units = units - U
      when U > 1e-9, else units. The target is the open trade; with none, the
      key's last trade, flagged "after_close_sell" (once), whose
      after_close_realized also gains trade_part; with none either, no
      target. With a target: units_sold += matched_units; proceeds +=
      total - orphan_part; realized_pnl += trade_part; sell_ids gets the id;
      last_sell_date = trade_date. On an open target, remaining =
      units_bought - units_sold; remaining <= max(DUST_FRACTION x peak_units,
      MIN_OPEN_UNITS) closes it (status "closed", close_date = trade_date,
      close_id = row id, no longer open), else status "partly_closed". A
      closed target stays "closed".
      When orphan_part > 0, or there is no target, an orphan record is
      appended: {sell_id, key, symbol, trade_date, units_sold (= units),
      units_unmatched (U when U > 1e-9, else units), realized_pnl
      (orphan_part, plus trade_part when there is no target), status ("full"
      when U >= units - 1e-9 or there is no target, else "partial")}. With a
      target and orphan_part > 0 the trade is also flagged "orphan_sell"
      (once).

    Each trade: trade_key, key, symbol (upper-cased, from its first buy),
    status, open_date, close_date, close_id, first_buy_id, buy_ids, sell_ids,
    units_bought, units_sold, open_units (max(units_bought - units_sold, 0.0);
    0.0 when closed), peak_units, cost_in, proceeds, realized_pnl,
    after_close_realized (the part of realized_pnl booked by after-close
    sells; 0.0 at creation), avg_entry
    (cost_in / units_bought, None when 0), avg_exit (proceeds / units_sold,
    None when 0), last_sell_date, flags.

    Returns {"trades": in the order they opened, "orphans": in row order}.
    Dust left by a closed trade stays in the lots; its cost lands in whichever
    later sell consumes it."""
    lots = {}          # key -> deque of {"units", "price"}, as FIFO keeps them
    open_trade = {}    # key -> trade or None
    last_trade = {}    # key -> trade
    trades, orphans = [], []

    for row in rows:
        key = row["key"]
        side = str(row["side"]).lower()
        units = float(row["units"])
        total = float(row["total"])
        price = total / units if units > 1e-12 else 0.0
        queue = lots.setdefault(key, deque())
        cur = open_trade.get(key)

        if side == "buy":
            queue.append({"units": units, "price": price})
            if units <= 1e-12:
                if cur is not None:
                    cur["buy_ids"].append(row["id"])
                continue
            if cur is None:
                cur = _new_trade(key, row)
                open_trade[key] = cur
                last_trade[key] = cur
                trades.append(cur)
            cur["units_bought"] += units
            cur["cost_in"] += total
            cur["buy_ids"].append(row["id"])
            cur["peak_units"] = max(cur["peak_units"], cur["units_bought"] - cur["units_sold"])

        elif side == "sell":
            remaining = units
            cost_basis = 0.0
            while remaining > 1e-9 and queue:
                lot = queue[0]
                if lot["units"] <= remaining + 1e-9:
                    cost_basis += lot["units"] * lot["price"]
                    remaining -= lot["units"]
                    queue.popleft()
                else:
                    cost_basis += remaining * lot["price"]
                    lot["units"] -= remaining
                    remaining = 0.0
            unmatched = remaining
            orphan_part = unmatched * price if unmatched > 1e-9 else 0.0
            trade_part = total - cost_basis - orphan_part
            matched_units = units - unmatched if unmatched > 1e-9 else units

            target = cur
            if target is None and key in last_trade:
                target = last_trade[key]
                _flag(target, "after_close_sell")
                target["after_close_realized"] += trade_part
            if target is not None:
                target["units_sold"] += matched_units
                target["proceeds"] += total - orphan_part
                target["realized_pnl"] += trade_part
                target["sell_ids"].append(row["id"])
                target["last_sell_date"] = row["trade_date"]
                if target is cur:
                    left = cur["units_bought"] - cur["units_sold"]
                    if left <= max(DUST_FRACTION * cur["peak_units"], MIN_OPEN_UNITS):
                        cur["status"] = "closed"
                        cur["close_date"] = row["trade_date"]
                        cur["close_id"] = row["id"]
                        open_trade[key] = None
                    else:
                        cur["status"] = "partly_closed"
            if orphan_part > 0 or target is None:
                orphans.append({"sell_id": row["id"], "key": key, "symbol": row["symbol"],
                                "trade_date": row["trade_date"], "units_sold": units,
                                "units_unmatched": unmatched if unmatched > 1e-9 else units,
                                "realized_pnl": orphan_part + (trade_part if target is None else 0.0),
                                "status": "full" if unmatched >= units - 1e-9 or target is None else "partial"})
                if target is not None:
                    _flag(target, "orphan_sell")

    for t in trades:
        t["open_units"] = 0.0 if t["status"] == "closed" else max(t["units_bought"] - t["units_sold"], 0.0)
        t["avg_entry"] = t["cost_in"] / t["units_bought"] if t["units_bought"] else None
        t["avg_exit"] = t["proceeds"] / t["units_sold"] if t["units_sold"] else None
    return {"trades": trades, "orphans": orphans}


def parity(trades, orphans, fifo_realized):
    """Per position key, the summed realized_pnl of its trades plus its
    orphan records must equal fifo_realized[key] ({key: realized_pnl} from
    _calculate_spot_fifo) within 1e-6. A key present on only one side counts
    0.0 on the other. Returns {"ok", "positions" (keys compared),
    "mismatches": [{"key", "fifo_realized", "trades_realized", "diff"}]}."""
    derived = {}
    for rec in list(trades) + list(orphans):
        derived[rec["key"]] = derived.get(rec["key"], 0.0) + rec["realized_pnl"]
    keys = sorted(set(derived) | set(fifo_realized))
    mismatches = []
    for k in keys:
        f = fifo_realized.get(k, 0.0)
        d = derived.get(k, 0.0)
        if abs(d - f) > 1e-6:
            mismatches.append({"key": k, "fifo_realized": f, "trades_realized": d, "diff": d - f})
    return {"ok": not mismatches, "positions": len(keys), "mismatches": mismatches}


def fmt_usd(x):
    """None -> None; else a 6-decimal string."""
    return None if x is None else f"{x:.6f}"


def fmt_num(x):
    """None -> None; else a plain decimal string at 10 significant digits,
    never exponent notation, trailing zeros stripped, "-0" -> "0"
    (0.00000364 -> "0.00000364", 83805.0 -> "83805", 1e15 ->
    "1000000000000000")."""
    if x is None:
        return None
    s = format(Decimal(f"{x:.10g}"), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s == "-0" else s
