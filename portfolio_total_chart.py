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
   out. Nothing else is filtered except ruling 4.
4. (Glenn, Sep 28; level-shift investigation) The one-run glitch runs listed
   in GLITCH_RUNS are left out of the chart. The stored rows are never
   changed; removing an entry restores the run.

Each total row goes to the FIRST matching reason, or becomes a point:
- not_usable: status != 'completed', hl_counted != 1, or total_usd is None.
- incomplete: wallets_total or wallets_completed is None, wallets_total < 1,
  or wallets_completed != wallets_total.
- unparseable: the timestamp does not parse.
- glitch: the timestamp is one of GLITCH_RUNS (ruling 4).
- point: {id, t (UTC ISO, milliseconds, "Z"), v, total, basis0}.
left_out (Landing 42): one entry per run left out as not_usable, incomplete or
glitch whose timestamp parses, {id, t, kind, glitch}, oldest first; the route
adds "reasons" (describe_left_out) for the chart's hollow dots and tooltips.
seams: {t, from_v, to_v} wherever v changes between consecutive points (t is
the later point's). benchmarks: {t, btc, eth} for market rows with a parseable
timestamp and at least one of the two prices.
"""
from datetime import timezone

from maxfi_advisor import parse_utc

# Ruling 4: one-run glitch runs left out of the chart, as (stored timestamp -
# naive UTC - , reason). The stored rows are untouched; delete an entry to
# restore its run.
GLITCH_RUNS = (
    ("2026-08-24T15:30:21.767709", "ESHARE priced $0 (custom token, one run)"),
    ("2026-08-24T17:46:19.912052", "CVX priced $0 (custom token)"),
    ("2026-08-24T19:46:49.022730", "CVX priced $0 (custom token)"),
    ("2026-08-24T21:47:19.140615", "CVX and ESHARE priced $0 (custom tokens)"),
    ("2026-08-30T02:22:25.849751", "PLAZM and ESHARE priced $0 (custom tokens, one run)"),
    ("2026-09-26T22:04:51.026351", "MaxFi LP rebalance: old and new position both reported (Desktop Hot WETH)"),
    ("2026-09-27T20:53:08.421440", "MaxFi LP row reported twice (Desktop Hot WETH)"),
    ("2026-09-27T21:12:02.721903", "MaxFi LP row reported twice (Desktop Hot WETH)"),
)
_GLITCH_INSTANTS = frozenset(parse_utc(ts) for ts, _reason in GLITCH_RUNS)
_GLITCH_REASONS = {parse_utc(ts): reason for ts, reason in GLITCH_RUNS}


def _iso_ms(dt):
    """An aware datetime -> UTC ISO with milliseconds and a "Z" suffix."""
    return dt.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def build_chart(total_rows, market_rows):
    """(portfolio_total_snapshots rows, market_snapshots price rows), both
    oldest first -> {"points", "seams", "excluded", "benchmarks"}."""
    points = []
    excluded = {"not_usable": 0, "incomplete": 0, "unparseable": 0, "glitch": 0}
    left_out = []

    def _leave_out(row, kind, dt):
        if dt is not None:
            left_out.append({"id": row.get("id"), "t": _iso_ms(dt), "kind": kind,
                             "glitch": _GLITCH_REASONS.get(dt)})

    for row in total_rows or []:
        if row.get("status") != "completed" or row.get("hl_counted") != 1 or row.get("total_usd") is None:
            excluded["not_usable"] += 1
            _leave_out(row, "not_usable", parse_utc(row.get("timestamp")))
            continue
        wt, wc = row.get("wallets_total"), row.get("wallets_completed")
        if wt is None or wc is None or wt < 1 or wc != wt:
            excluded["incomplete"] += 1
            _leave_out(row, "incomplete", parse_utc(row.get("timestamp")))
            continue
        dt = parse_utc(row.get("timestamp"))
        if dt is None:
            excluded["unparseable"] += 1
            continue
        if dt in _GLITCH_INSTANTS:
            excluded["glitch"] += 1
            _leave_out(row, "glitch", dt)
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

    left_out.sort(key=lambda e: e["t"])
    return {"points": points, "seams": seams, "excluded": excluded, "benchmarks": benchmarks,
            "left_out": left_out}


def describe_left_out(run, failed_wallet_labels=(), glitch=None):
    """Plain sentences saying why one run is left out of the chart (Landing 42).

    run: the run's portfolio_total_snapshots fields {status, hl_counted,
    total_usd, error, wallets_total, wallets_completed, detail} (detail =
    parsed detail_json or None). failed_wallet_labels: Settings labels of the
    run's wallet rows with status 'failed'. glitch: the GLITCH_RUNS reason.

    Runs recorded from Landing 42 on carry detail["run_notes"], written when
    the run was saved; they are used as they are. Older runs are described
    from what was stored: failed wallet rows, the composer's error, TxFlow
    wallets not read and Hyperliquid's warning. Never empty."""
    run = run or {}
    detail = run.get("detail") if isinstance(run.get("detail"), dict) else {}
    notes = detail.get("run_notes")
    reasons = [str(n) for n in notes if n] if isinstance(notes, list) else []
    recorded = bool(reasons)
    if not recorded:
        for name in failed_wallet_labels or ():
            reasons.append(f"{name}: wallet didn't save (the cause wasn't recorded before Oct 15)")
        wt, wc = run.get("wallets_total"), run.get("wallets_completed")
        if not failed_wallet_labels and isinstance(wt, int) and isinstance(wc, int) and wc < wt:
            n = wt - wc
            reasons.append(f"{n} wallet{'' if n == 1 else 's'} didn't save")
    status = run.get("status")
    if status == "failed":
        reasons.append(_composer_error_text(run.get("error")))
    elif not recorded:
        comps = {c.get("key"): c for c in _list(detail.get("components")) if isinstance(c, dict)}
        if run.get("hl_counted") is not None and run.get("hl_counted") != 1:
            hl = comps.get("hyperliquid") or {}
            failed = [str(w).split(": ", 1)[1] for w in _list(hl.get("warnings"))
                      if str(w).startswith("last Hyperliquid refresh failed: ")]
            reasons.append("Hyperliquid not counted: no Hyperliquid reading yet"
                           + (f" (last refresh failed: {failed[0]})" if failed else ""))
        if status == "partial":
            tx = comps.get("txflow")
            tx_detail = (tx or {}).get("detail")
            unread = [str(r.get("label") or "TxFlow")
                      for r in _list(tx_detail.get("wallets") if isinstance(tx_detail, dict) else None)
                      if isinstance(r, dict) and not r.get("counted")]
            if tx is not None and not tx.get("counted"):
                reasons.append("TxFlow not counted: no TxFlow reading yet")
            elif unread:
                reasons.append("TxFlow not read for " + ", ".join(unread))
            else:
                reasons.append("Some data didn't load (which source wasn't recorded before Oct 15)")
        if status == "completed" and run.get("total_usd") is None:
            reasons.append("No total was saved for this run")
    if glitch:
        reasons.append(f"Left out by hand as a known glitch: {glitch}")
    out = []
    for r in reasons:
        if r not in out:
            out.append(r)
    return out or ["Left out of the chart (no cause recorded)"]


def _list(value):
    return value if isinstance(value, list) else []


def _composer_error_text(error):
    """The composer's stored error (already masked) in plain words."""
    text = str(error or "").strip()
    if "cache_cold" in text:
        return "The total wasn't worked out: the portfolio data hadn't loaded yet"
    return "The total wasn't worked out: an error stopped it" + (f" ({text})" if text else "")
