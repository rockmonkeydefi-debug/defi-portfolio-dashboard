"""Reference perp-cycle derivation used to produce expected_cycles.json for the
sanitized Hyperliquid fixtures (HANDOFF_trading_performance.md, Commit 3).
Rules (also written into tests/fixtures/hl_trading/README.md):
 R1 fills per (wallet, coin) in file order (API order: time ascending; same-time
    fills already chained by startPosition). A cycle opens on a fill whose
    startPosition == 0 and closes on the fill whose end position
    (startPosition + sz for side B, - sz for side A) == 0. Flip fills
    ('Long > Short' / 'Short > Long') would be split; none occur here.
 R2 direction = long if the opening fill is side B, else short.
 R3 peak_size = max |end position| over the cycle's fills.
 R4 avg_entry = sum(px*sz)/sum(sz) over fills whose dir starts 'Open';
    avg_exit likewise over 'Close' fills (None while open).
 R5 gross = sum(closedPnl); fees = sum(fee + builderFee) (closedPnl excludes fees).
 R6 funding: entries with nSamples null are hourly and belong to the cycle of
    that coin with open < time <= close (close = +inf while open). Entries with
    nSamples set are daily totals for [time, time + 86400000); they are split
    across overlapping cycles of that coin pro rata by overlap duration.
    Anything matching no cycle is 'unattributed'.
 R7 net = gross - fees + funding.
 R8 initial stop: candidates are standalone order records (children ignored)
    with isTrigger true, reduceOnly true, orderType containing 'Stop',
    triggerPx > 0, same coin, side opposite to the position (A for long,
    B for short). An order's end time is the statusTimestamp of any record of
    the same oid whose status is not 'open'. Pick the latest-placed candidate
    with placed <= open < end (or no end) and placed >= open - 3 days; if none,
    the earliest-placed candidate with open < placed <= close.
 R9 R = net / (|avg_entry - stop| * peak_size); None while open or without stop.
"""
import json, sys
from decimal import Decimal as D

INF = 10 ** 16


def cycles_for(fills, funding, hist, wallet):
    cycles, cur = [], {}
    for f in fills:
        c = f["coin"]; sp = D(f["startPosition"]); sz = D(f["sz"])
        if "Long >" in f["dir"] or "Short >" in f["dir"]:
            raise SystemExit("flip fill present - reference script does not split flips")
        end = sp + (sz if f["side"] == "B" else -sz)
        if sp == 0:
            cur[c] = {"wallet": wallet, "coin": c, "direction": "long" if f["side"] == "B" else "short",
                      "open_time": f["time"], "close_time": None, "first_tid": f["tid"], "fill_count": 0,
                      "peak": D(0), "en": D(0), "es": D(0), "xn": D(0), "xs": D(0),
                      "gross": D(0), "fees": D(0), "funding": D(0)}
        cy = cur[c]
        cy["fill_count"] += 1
        cy["gross"] += D(f["closedPnl"]); cy["fees"] += D(f["fee"]) + D(f.get("builderFee") or 0)
        if f["dir"].startswith("Open"):
            cy["en"] += D(f["px"]) * sz; cy["es"] += sz
        else:
            cy["xn"] += D(f["px"]) * sz; cy["xs"] += sz
        cy["peak"] = max(cy["peak"], abs(end))
        if end == 0:
            cy["close_time"] = f["time"]; cycles.append(cy); del cur[c]
    cycles.extend(cur.values())

    unattributed = D(0)
    for e in funding:
        d = e["delta"]; t = e["time"]; amt = D(d["usdc"])
        mine = [cy for cy in cycles if cy["coin"] == d["coin"]]
        if d.get("nSamples") is None:
            hit = [cy for cy in mine if cy["open_time"] < t <= (cy["close_time"] or INF)]
            if hit:
                hit[0]["funding"] += amt
            else:
                unattributed += amt
        else:
            ov = []
            for cy in mine:
                a, b = max(cy["open_time"], t), min(cy["close_time"] or INF, t + 86400000)
                if b > a:
                    ov.append((cy, b - a))
            tot = sum(x[1] for x in ov)
            if not ov:
                unattributed += amt
            for cy, dur in ov:
                cy["funding"] += amt * D(dur) / D(tot)

    ends, cands = {}, {}
    for h in hist:
        o = h["order"]
        if h["status"] != "open":
            ends[o["oid"]] = max(ends.get(o["oid"], 0), h["statusTimestamp"])
        if o.get("isTrigger") and o.get("reduceOnly") and "Stop" in o["orderType"] and D(o["triggerPx"]) > 0:
            cands[(o["oid"], o["timestamp"])] = {"coin": o["coin"], "side": o["side"], "px": D(o["triggerPx"]),
                                                 "placed": o["timestamp"], "oid": o["oid"]}
    for cy in cycles:
        side = "A" if cy["direction"] == "long" else "B"
        mine = [s for s in cands.values() if s["coin"] == cy["coin"] and s["side"] == side]
        op = cy["open_time"]; cl = cy["close_time"] or INF
        alive = [s for s in mine if op - 3 * 86400000 <= s["placed"] <= op and ends.get(s["oid"], INF) > op]
        after = [s for s in mine if op < s["placed"] <= cl]
        pick = max(alive, key=lambda s: s["placed"]) if alive else (min(after, key=lambda s: s["placed"]) if after else None)
        cy["stop"] = pick["px"] if pick else None
        cy["stop_placed"] = pick["placed"] if pick else None
    return cycles, unattributed


def summarize(cy):
    avg_in = cy["en"] / cy["es"]
    avg_out = cy["xn"] / cy["xs"] if cy["xs"] else None
    net = cy["gross"] - cy["fees"] + cy["funding"]
    r = None
    if cy["stop"] is not None and cy["close_time"] is not None:
        r = net / (abs(avg_in - cy["stop"]) * cy["peak"])
    q = lambda x: None if x is None else str(x.quantize(D("0.000001")))
    return {"wallet": cy["wallet"], "coin": cy["coin"], "direction": cy["direction"], "status": "closed" if cy["close_time"] else "open",
            "open_time": cy["open_time"], "close_time": cy["close_time"], "first_tid": cy["first_tid"], "fill_count": cy["fill_count"],
            "peak_size": q(cy["peak"]), "avg_entry": q(avg_in), "avg_exit": q(avg_out), "gross_closed_pnl": q(cy["gross"]),
            "fees": q(cy["fees"]), "funding": q(cy["funding"]), "net_pnl": q(net), "initial_stop": q(cy["stop"]),
            "stop_placed": cy["stop_placed"], "r_multiple": q(r)}


if __name__ == "__main__":
    base = sys.argv[1]
    result = {"wallets": {}, "cycles": []}
    for w in sys.argv[2:]:
        ld = lambda k: json.load(open(f"{base}/{w}.{k}.json"))
        fills = sorted(ld("fills"), key=lambda f: f["time"])
        cycles, un = cycles_for(fills, ld("funding"), ld("hist_orders"), w)
        result["wallets"][w] = {"unattributed_funding": str(un.quantize(D("0.000001"))), "cycles": len(cycles)}
        result["cycles"].extend(summarize(cy) for cy in sorted(cycles, key=lambda c: c["open_time"]))
    print(json.dumps(result, indent=1))
