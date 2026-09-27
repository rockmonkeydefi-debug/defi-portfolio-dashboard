"""Chart series for the Dashboard's equity chart over portfolio_total_snapshots
(GET /api/history/portfolio-total-chart; HANDOFF_total_history.md, "Chart
route (Dashboard redesign)").

PURE: no Flask, no DB, no network and no clock reads. The route reads the rows
and passes them in.

Rulings (Glenn, Sep 27):
1. The chart reads portfolio_total_snapshots: the definition_version 0
   backfill, then the live rows.
2. The seam between definitions is marked, never hidden. Every point carries
   its definition version and its old-basis value (basis0 = snapshot total +
   Hyperliquid, stored on every row), so a change across the seam can be
   computed on the old basis at both ends.
3. Runs where any wallet failed (wallets_completed < wallets_total) are left
   out. Nothing else is filtered.

Each total row goes to the FIRST matching reason, or becomes a point:
- not_usable: status != 'completed', hl_counted != 1, or total_usd is None.
- incomplete: wallets_total or wallets_completed is None, wallets_total < 1,
  or wallets_completed != wallets_total.
- unparseable: the timestamp does not parse.
- point: {id, t (UTC ISO, milliseconds, "Z"), v, total, basis0}.
seams: {t, from_v, to_v} wherever v changes between consecutive points (t is
the later point's). benchmarks: {t, btc, eth} for market rows with a parseable
timestamp and at least one of the two prices.
"""
from datetime import timezone

from maxfi_advisor import parse_utc


def _iso_ms(dt):
    """An aware datetime -> UTC ISO with milliseconds and a "Z" suffix."""
    return dt.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def build_chart(total_rows, market_rows):
    """(portfolio_total_snapshots rows, market_snapshots price rows), both
    oldest first -> {"points", "seams", "excluded", "benchmarks"}."""
    points = []
    excluded = {"not_usable": 0, "incomplete": 0, "unparseable": 0}
    for row in total_rows or []:
        if row.get("status") != "completed" or row.get("hl_counted") != 1 or row.get("total_usd") is None:
            excluded["not_usable"] += 1
            continue
        wt, wc = row.get("wallets_total"), row.get("wallets_completed")
        if wt is None or wc is None or wt < 1 or wc != wt:
            excluded["incomplete"] += 1
            continue
        dt = parse_utc(row.get("timestamp"))
        if dt is None:
            excluded["unparseable"] += 1
            continue
        snap, hl = row.get("snapshot_total_usd"), row.get("hyperliquid_usd")
        points.append({
            "id": row.get("id"),
            "t": _iso_ms(dt),
            "v": row.get("definition_version"),
            "total": float(row["total_usd"]),
            "basis0": float(snap) + float(hl) if snap is not None and hl is not None else None,
        })

    seams = [{"t": b["t"], "from_v": a["v"], "to_v": b["v"]}
             for a, b in zip(points, points[1:]) if a["v"] != b["v"]]

    benchmarks = []
    for row in market_rows or []:
        btc, eth = row.get("btc_price"), row.get("eth_price")
        if btc is None and eth is None:
            continue
        dt = parse_utc(row.get("timestamp"))
        if dt is None:
            continue
        benchmarks.append({"t": _iso_ms(dt), "btc": btc, "eth": eth})

    return {"points": points, "seams": seams, "excluded": excluded, "benchmarks": benchmarks}
