"""Hyperliquid history backfill for past snapshot runs (HANDOFF_total_history.md,
"Hyperliquid backfill (definition_version 0)").

PURE: stdlib only (json, math, datetime) - no Flask, no DB, no network. The
route (web_portfolio._run_hl_history_backfill) fetches and captures the raw
Hyperliquid responses, reads the snapshot runs and the first measured row,
and hands them in here.

For every chart-visible snapshot run (at least one completed
portfolio_snapshots row) before the first portfolio_total_snapshots row with
definition_version >= 1, one definition_version 0 row:
    total_usd = the run's old snapshot total + Hyperliquid
(no MaxFi fees; old GMX and lending rules). Only wallets with a
portfolio_snapshots row in that run count toward its Hyperliquid value.

A wallet's Hyperliquid value at a run's time t:
- Sources: `portfolio` (account value history; windows day, week, month,
  allTime - finest first; perp windows ignored) and
  `userNonFundingLedgerUpdates` (deposits, withdrawals, sends, transfers).
- Leading $0 points are dropped: Hyperliquid's history starts with a $0
  point even when the account already holds money.
- The finest window with a point at or before t is used. With p1 = the last
  point <= t and p2 = the next point:
      value = v1 + transfers in (p1, t] + share of the remaining change,
      remaining change = (v2 - v1) - transfers in (p1, p2]   (trading P/L),
      share = (t - p1) / (p2 - p1)   (straight line).
  Without a next point: v1 + transfers in (p1, t].
- Before a wallet's first remaining point: its cumulative ledger transfers.
- A transfer that cannot be valued in USD, inside an interval a run depends
  on, raises UnvaluedTransfer (the run then counts that wallet as 0 and the
  report's checks block a real write).
"""
import json
import math
import re
from datetime import datetime, timezone

DEFINITION_VERSION = 0
DEFINITION_TEXT = "old snapshot total + Hyperliquid; no MaxFi fees; old GMX and lending rules"
METHOD_TEXT = ("window point + ledger transfers since it + straight-line share of the remaining change to the next "
               "point; before a wallet's first history point, cumulative ledger transfers")
WINDOWS = ("day", "week", "month", "allTime")   # finest first; perp windows ignored
LEDGER_PAGE_LIMIT = 500
NEGATIVE_TOLERANCE_USD = 0.005

_EVM_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
_REPORT_LIST_CAP = 20


class UnvaluedTransfer(Exception):
    """A ledger transfer with no USD value inside an interval a run depends on."""

    def __init__(self, time_ms, type_):
        super().__init__(f"unvalued {type_} at {iso_ms(time_ms)}")
        self.time_ms = time_ms
        self.type = type_


def short(addr):
    """0x1234...abcd (unchanged when 14 characters or fewer)."""
    addr = str(addr)
    return addr if len(addr) <= 14 else addr[:6] + "..." + addr[-4:]


def iso_ms(ms):
    """Epoch milliseconds -> 'YYYY-MM-DDTHH:MM:SSZ' (UTC)."""
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_run_ts(ts):
    """A portfolio_snapshots timestamp string -> epoch ms. Naive = UTC.
    None when unparseable."""
    try:
        dt = datetime.fromisoformat(str(ts).strip().replace(' ', 'T'))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(round(dt.timestamp() * 1000))


def _finite(value):
    """float(value) when finite, else None."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def parse_portfolio(response):
    """The `portfolio` response -> {window: [(ms, value), ...]} for WINDOWS
    only (every key present, [] when absent). Unparseable or non-finite
    points are skipped; points are sorted by time; LEADING points with value
    <= 0 are dropped (interior zeros stay). A non-list response raises
    ValueError."""
    if not isinstance(response, list):
        raise ValueError(f"portfolio response is {type(response).__name__}, not a list")
    out = {w: [] for w in WINDOWS}
    for entry in response:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2 or entry[0] not in out:
            continue
        body = entry[1] if isinstance(entry[1], dict) else {}
        points = []
        for p in body.get("accountValueHistory") or []:
            try:
                ms = int(p[0])
            except (TypeError, ValueError, IndexError):
                continue
            v = _finite(p[1]) if isinstance(p, (list, tuple)) and len(p) > 1 else None
            if v is None:
                continue
            points.append((ms, v))
        points.sort(key=lambda x: x[0])
        while points and points[0][1] <= 0:
            points.pop(0)
        out[entry[0]] = points
    return out


def event_key(event):
    """Dedup key of one userNonFundingLedgerUpdates event: (time, hash, delta.type)."""
    delta = event.get("delta") if isinstance(event.get("delta"), dict) else {}
    return (event.get("time"), event.get("hash"), delta.get("type"))


def _transfer_usd(delta, wallet_l):
    """USD effect of a send / spotTransfer on the wallet (None when unvalued)."""
    user = str(delta.get("user") or "").lower()
    dest = str(delta.get("destination") or "").lower()
    if user == wallet_l and dest == wallet_l:
        return 0.0
    amount = _finite(delta.get("usdcValue"))
    if amount is None and delta.get("token") == "USDC":
        amount = _finite(delta.get("amount"))
    if amount is None:
        return None
    if dest == wallet_l:
        return amount
    if user == wallet_l:
        return -amount
    return None


def classify_ledger(events, wallet):
    """userNonFundingLedgerUpdates events -> [{"time_ms", "usd", "type"}],
    sorted by time, deduplicated by (time, hash, delta.type). usd is None when
    the event cannot be valued. Addresses compare lowercase.
    - deposit +usdc, withdraw -usdc, accountClassTransfer 0
    - send / spotTransfer: usdcValue (or amount for token USDC), + when the
      wallet is the destination, - when it is the sender, 0 to itself
    - any other type, or an unparseable number: None
    Events without a parseable time are skipped (they cannot be placed)."""
    wallet_l = str(wallet).lower()
    seen = set()
    flows = []
    for e in events or []:
        if not isinstance(e, dict):
            continue
        key = event_key(e)
        if key in seen:
            continue
        seen.add(key)
        try:
            time_ms = int(e.get("time"))
        except (TypeError, ValueError):
            continue
        delta = e.get("delta") if isinstance(e.get("delta"), dict) else {}
        kind = delta.get("type")
        if kind == "deposit":
            v = _finite(delta.get("usdc"))
            usd = v
        elif kind == "withdraw":
            v = _finite(delta.get("usdc"))
            usd = -v if v is not None else None
        elif kind == "accountClassTransfer":
            usd = 0.0
        elif kind in ("send", "spotTransfer"):
            usd = _transfer_usd(delta, wallet_l)
        else:
            usd = None
        flows.append({"time_ms": time_ms, "usd": usd, "type": kind})
    flows.sort(key=lambda f: f["time_ms"])
    return flows


def _flow_sum(flows, lo, hi):
    """Sum of usd over flows with lo < time_ms <= hi (lo None = no lower
    bound). Raises UnvaluedTransfer on the first unvalued flow."""
    total = 0.0
    for f in flows:
        t = f["time_ms"]
        if (lo is None or t > lo) and t <= hi:
            if f["usd"] is None:
                raise UnvaluedTransfer(t, f["type"])
            total += f["usd"]
    return total


def value_at(windows, flows, t_ms):
    """A wallet's Hyperliquid value at t_ms (see the module docstring).
    Raises UnvaluedTransfer."""
    for w in WINDOWS:
        pts = windows.get(w) or []
        if pts and pts[0][0] <= t_ms:
            break
    else:
        cum = _flow_sum(flows, None, t_ms)
        return {"value_usd": cum, "basis": "ledger_only", "window": None, "p1": None, "p2": None,
                "transfers_since_p1_usd": cum, "transfers_p1_to_p2_usd": None, "pnl_share_usd": 0.0}
    p1 = None
    p2 = None
    for p in pts:
        if p[0] <= t_ms:
            p1 = p
        else:
            p2 = p
            break
    t1, v1 = p1
    if p2 is not None:
        t2, v2 = p2
        f12 = _flow_sum(flows, t1, t2)
        f1t = _flow_sum(flows, t1, t_ms)
        resid = (v2 - v1) - f12
        share = resid * (t_ms - t1) / (t2 - t1)
        value = v1 + f1t + share
        p2_out = [iso_ms(t2), v2]
    else:
        f12 = None
        f1t = _flow_sum(flows, t1, t_ms)
        share = 0.0
        value = v1 + f1t
        p2_out = None
    return {"value_usd": value, "basis": "points", "window": w, "p1": [iso_ms(t1), v1], "p2": p2_out,
            "transfers_since_p1_usd": f1t, "transfers_p1_to_p2_usd": f12, "pnl_share_usd": share}


def wallet_data_from_capture(capture_rows):
    """hl_history_captures rows (dicts with wallet, request_type,
    response_json) -> {wallet: {"windows", "flows", "ledger_events",
    "ledger_types", "funded"}}. Exactly one 'portfolio' row per wallet;
    'ledger' pages are concatenated in row order (non-list pages skipped)."""
    grouped = {}
    for row in capture_rows:
        g = grouped.setdefault(row["wallet"], {"portfolio": [], "ledger": []})
        g.setdefault(row["request_type"], []).append(json.loads(row["response_json"]))
    out = {}
    for wallet, g in grouped.items():
        if len(g["portfolio"]) != 1:
            raise ValueError(f"{short(wallet)}: {len(g['portfolio'])} portfolio responses in the capture, expected 1")
        windows = parse_portfolio(g["portfolio"][0])
        events = []
        for page in g["ledger"]:
            if isinstance(page, list):
                events.extend(page)
        flows = classify_ledger(events, wallet)
        types = {}
        for f in flows:
            types[f["type"]] = types.get(f["type"], 0) + 1
        out[wallet] = {"windows": windows, "flows": flows, "ledger_events": len(flows), "ledger_types": types,
                       "funded": any(windows[w] for w in WINDOWS) or bool(flows)}
    return out


def _seam_entry(row):
    if not row:
        return None
    return {k: row.get(k) for k in ("timestamp", "snapshot_total_usd", "hyperliquid_usd", "total_usd")}


def build_backfill(runs, wallet_data, first_measured, capture_id=None, labels=None):
    """(rows, report) for the definition_version 0 backfill.

    runs: get_snapshot_runs_before(...) output - [{"timestamp", "rows":
        [{"wallet", "status", "total_value_usd"}]}], oldest first.
    wallet_data: wallet_data_from_capture(...) output.
    first_measured: the first definition_version >= 1 row (dict).
    Each row carries only timestamp, status, definition_version, total_usd,
    snapshot_total_usd, hyperliquid_usd, hl_counted, wallets_total,
    wallets_completed and detail_json - every other column stays NULL."""
    labels = labels or {}
    funded = {w: d for w, d in wallet_data.items() if d["funded"]}
    queried_l = {w.lower() for w in wallet_data}
    stats = {w: {"basis_counts": {"points": 0, "ledger_only": 0}, "window_counts": {x: 0 for x in WINDOWS},
                 "runs_counted": 0} for w in funded}
    unvalued, negative = [], []
    not_queried = {}
    minute_buckets = {}
    unparseable = 0
    rows, run_reports = [], []
    selected = 0

    for run in runs:
        run_rows = run.get("rows") or []
        completed = [r for r in run_rows if r.get("status") == "completed"]
        if not completed:
            continue
        ts = run["timestamp"]
        t_ms = parse_run_ts(ts)
        if t_ms is None:
            unparseable += 1
            continue
        selected += 1
        bucket = str(ts)[:16]
        minute_buckets[bucket] = minute_buckets.get(bucket, 0) + 1
        present = {str(r.get("wallet") or "").lower() for r in run_rows}
        for r in run_rows:
            w = str(r.get("wallet") or "")
            if _EVM_RE.match(w) and w.lower() not in queried_l:
                not_queried[w.lower()] = not_queried.get(w.lower(), 0) + 1
        snapshot_total = sum((r.get("total_value_usd") or 0) for r in completed)

        hl = 0.0
        detail_wallets, by_wallet = {}, {}
        for wallet, d in funded.items():
            if wallet.lower() not in present:
                continue
            try:
                v = value_at(d["windows"], d["flows"], t_ms)
            except UnvaluedTransfer as e:
                unvalued.append({"wallet": short(wallet), "run": ts, "event": iso_ms(e.time_ms), "type": e.type})
                detail_wallets[wallet.lower()] = {"value_usd": 0.0, "unvalued_transfer": {"event": iso_ms(e.time_ms),
                                                                                          "type": e.type}}
                by_wallet[short(wallet)] = 0.0
                continue
            if v["value_usd"] < -NEGATIVE_TOLERANCE_USD:
                negative.append({"wallet": short(wallet), "run": ts, "value_usd": v["value_usd"]})
            hl += v["value_usd"]
            detail_wallets[wallet.lower()] = v
            by_wallet[short(wallet)] = v["value_usd"]
            s = stats[wallet]
            s["basis_counts"][v["basis"]] += 1
            if v["window"]:
                s["window_counts"][v["window"]] += 1
            s["runs_counted"] += 1

        detail = {"source": "hyperliquid_backfill", "definition_version": DEFINITION_VERSION,
                  "definition": DEFINITION_TEXT, "method": METHOD_TEXT, "capture_id": capture_id,
                  "run_rows": {"total": len(run_rows), "completed": len(completed)}, "wallets": detail_wallets}
        row = {"timestamp": ts, "status": "completed", "definition_version": DEFINITION_VERSION,
               "total_usd": snapshot_total + hl, "snapshot_total_usd": snapshot_total, "hyperliquid_usd": hl,
               "hl_counted": 1, "wallets_total": len(run_rows), "wallets_completed": len(completed),
               "detail_json": json.dumps(detail, sort_keys=True)}
        rows.append(row)
        run_reports.append({"timestamp": ts, "snapshot_total_usd": snapshot_total, "hyperliquid_usd": hl,
                            "total_usd": row["total_usd"], "wallets_total": len(run_rows),
                            "wallets_completed": len(completed), "hl_by_wallet": by_wallet})

    funded_report = []
    for wallet, d in funded.items():
        firsts = [d["windows"][w][0] for w in WINDOWS if d["windows"][w]]
        first_pt = min(firsts, key=lambda p: p[0]) if firsts else None
        funded_report.append(dict({
            "wallet": short(wallet), "label": labels.get(wallet),
            "first_history_point": [iso_ms(first_pt[0]), first_pt[1]] if first_pt else None,
            "points": {w: len(d["windows"][w]) for w in WINDOWS},
            "ledger_events": d["ledger_events"], "ledger_types": d["ledger_types"],
            "first_ledger_event": iso_ms(d["flows"][0]["time_ms"]) if d["flows"] else None}, **stats[wallet]))

    report = {
        "cutoff": first_measured["timestamp"], "runs_before_cutoff": len(runs), "runs_selected": selected,
        "rows": len(rows), "wallets_queried": len(wallet_data), "funded_wallets": funded_report,
        "checks": {
            "unvalued_used": unvalued[:_REPORT_LIST_CAP], "unvalued_used_count": len(unvalued),
            "negative_values": negative[:_REPORT_LIST_CAP], "negative_values_count": len(negative),
            "not_queried_evm_in_runs": [{"wallet": short(w), "runs": n} for w, n in sorted(not_queried.items())],
            "minute_collisions": sum(1 for n in minute_buckets.values() if n > 1),
            "unparseable_timestamps": unparseable,
        },
        "blocking": bool(unvalued) or bool(negative),
        "seam": {"last_backfill": _seam_entry(rows[-1]) if rows else None,
                 "first_measured": _seam_entry(first_measured)},
        "runs": run_reports,
    }
    return rows, report
