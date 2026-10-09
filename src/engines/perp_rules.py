"""Advisor v1, Landing 8a: the perp-trade rule evaluator
(HANDOFF_spot_perps_rebuild sections 16-20).

PURE: stdlib (datetime, decimal) and hl_trades' constants only - no Flask,
no DB, no network, no import from web_portfolio.py. The route
(GET /api/trading/advisor/perps) builds the trades once (_trades_build), reads
the stored order history and fills, turns each synced trade's history into
the small structure trade_orders() returns, and calls evaluate_all().

Rules (RULES; status "enforced" or "tracking": the registry's default, or the
stored change in force when the trade opened, Landing 8b-2):
  E1 higher timeframes (12h, 1d, 1w) not against the trade at the open
  E2 lower timeframes (15m, 30m, 1h, 4h) by setup: retest touches, none against
  E3 a point of interest tagged
  R1 a stop in force within SETTLE_MIN of the open
  R2 1R within the per-trade limit (1% of capital by default); all open 1R within
     the total limit (5% by default); the limits are dated settings (Landing 16)
  R3 the planned take-profit at least MIN_PLAN_R by price
  R4 (tracking by default) the stop inside half the liquidation distance at the
     leverage; pass / fail verdicts only while enforced
  M1 the first planned take-profit set left alone while the trade is open
  M2 no stop widened on the loss side of entry after the settle window (at or past
     entry a loosening is a note)
  M3 (tracking, fixed: no pass / fail test) when the stop first moved to breakeven
  X1 a revised exit has an exit reason picked (Landing 8c-2; notes no longer count)
  X2 the trade reviewed (Followed / Deviated)

Every result is {"rule", "status", "verdict", "evidence", "reason"}; reason is
set only for not_measurable. Tracking rules never count as a deviation and
never appear in enforced_fails. Setup and POI tags are optional inputs; from
Landing 8b-1 the route passes the stored ones (trade_tags), and a trade
without a stored tag reads not_tagged on E2 and E3.

Settings (Landing 8b-2) are an optional input too: {"status": [{"rule",
"status", "from", "reason", "set_at"}], "capital": [{"from", "usd",
"set_at"}]}, each in the order the changes were made (the route reads
perp_rule_status and perp_capital). A status change applies to trades opened
at or after its "from" time; earlier trades keep the status they were judged
under (forward only), and a result whose status at the open differs from the
rule's status now carries a note. Capital is dated: R2 measures against the
period in force when the trade opened. Without settings the code defaults
apply (the registry's statuses, CAPITAL_USD from CAPITAL_FROM). Nothing here
keeps state between calls.

Landing 16 adds "risk": [{"per_trade_bps", "total_bps", "from", "reason",
"set_at"}] (the route reads perp_risk_limits): R2's limits in whole basis
points (100 = 1%), forward only like a status change. R2 judges each trade
by the limits in force when it opened, with a note when the limits now
differ; without rows the defaults apply (RISK_PER_TRADE_PCT, RISK_TOTAL_PCT).

Landing 17: gate_check() says why the rule check keeps a closed perp trade
out of the 1% -> 2% risk gate (web_portfolio counts a trade only when its own
gate checks pass and gate_check finds nothing).

Landing 22: gate_prep() lists what an open perp trade still needs before its
close to count (setup and POI tags, a take-profit), so the Perps page and the
menu can flag it while it can still be fixed.

Landing 23: a per-trade limit above the default (RISK_DEFAULT, 1%) applies
only to a trade opened while the risk gate was unlocked. R2 reads the trade's
"gate_at_open" ({"unlocked", "seen_at", ...}: the gate as web_portfolio's
background pass recorded it the first time it saw the trade; never
recomputed). Locked: the per-trade limit is the default, with a note. No
record: not measurable ("gate_not_recorded"). With limits at or below the
default the record is never read, so R2 is unchanged."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import hl_trades

CAPITAL_USD = 50000
CAPITAL_FROM = "2026-09-13"            # UTC
RISK_PER_TRADE_PCT = 1                 # R2's default limits (Landing 16: dated settings override them)
RISK_TOTAL_PCT = 5
# Landing 16: R2's limits as stored settings, in whole basis points (100 = 1%).
# Per trade from RISK_MIN_BPS up to RISK_PER_TRADE_MAX_BPS (2%, the risk gate's
# step; the save route allows more than the default 1% only while the gate is
# unlocked); total from the per-trade limit up to RISK_TOTAL_MAX_BPS (5%, the
# Sep 13 ceiling). A stored row outside these bounds is ignored. A higher
# ceiling is a code change.
RISK_MIN_BPS = 10
RISK_PER_TRADE_MAX_BPS = 200
RISK_TOTAL_MAX_BPS = 500
RISK_DEFAULT = {"per_trade_bps": RISK_PER_TRADE_PCT * 100, "total_bps": RISK_TOTAL_PCT * 100}
SETTLE_MIN = 10                        # mirrors hl_trades.SETTLE_MS (a test checks they agree)
MIN_PLAN_R = Decimal("2.0")
NEGLIGIBLE_1R_USD = 5
DEFINITION_VERSION = 2                 # 2 (Landing 8c-2): X1 reads the exit reason, not the notes

R1_LIMIT_MIN = Decimal("10.5")         # R1: the stop counts as in force at entry if set within this
TP_CLOSE_GRACE_MS = 5000               # M1: a take-profit cancelled this close to the close is close-time cleanup
SETTLE_MS = SETTLE_MIN * 60000
LOWER_TFS = ("15m", "30m", "1h", "4h")
HIGHER_TFS = ("12h", "1d", "1w")
TALLY_NOTE = "lead only: small sample, one market period"

VERDICTS = ("pass", "fail", "neutral", "not_measurable", "tracking", "self_reported", "no_plan", "not_tagged")
SETUPS = ("retest", "breakout", "other")

# Why a revised exit happened (Landing 8c-2). The keys are what
# trade_annotations.exit_reason stores; the save route checks against them
# (the table has no CHECK, so a new reason is a one-line change here).
# "reversal_pattern" reads "Topping pattern" on a long and "Bottoming
# pattern" on a short. static/perpsrules.js keeps the same keys and labels
# (a test pins them).
EXIT_REASONS = (
    ("fundamental_thesis_changed", "Fundamental thesis changed"),
    ("sd_level_broke", "S/D level broke"),
    ("reversal_pattern", "Topping pattern"),
    ("took_profit_early", "Took profit early (no signal)"),
    ("time_stop", "Time stop (not moving)"),
    ("cut_risk", "Cut risk (news or event)"),
    ("resized", "Resized (size or leverage too high)"),
    ("emotional", "Emotional"),
    ("other", "Other"),
)
EXIT_REASON_KEYS = tuple(k for k, _ in EXIT_REASONS)
EXIT_REASON_NOTE_REQUIRED = ("other",)


def exit_reason_label(key, direction=None):
    """The label for a stored exit reason; None for an unknown key."""
    if key == "reversal_pattern" and direction == "short":
        return "Bottoming pattern"
    return dict(EXIT_REASONS).get(key)

RULES = [
    {"id": "E1", "group": "entry", "title": "Higher timeframes not against the trade", "status": "enforced",
     "definition": "At the open, the noodle on 12h, 1d and 1w: any timeframe against the trade fails; all with it "
                   "passes; touching (none against) is neutral."},
    {"id": "E2", "group": "entry", "title": "Lower timeframes fit the setup", "status": "enforced",
     "definition": "At the open, the noodle on 15m, 30m, 1h and 4h: any timeframe against the trade fails. A retest "
                   "passes when at least one timeframe touches the noodle; a breakout or other setup is self-reported; "
                   "an untagged trade is not tagged."},
    {"id": "E3", "group": "entry", "title": "A point of interest tagged", "status": "enforced",
     "definition": "The trade has a point-of-interest tag (type and timeframe); untagged trades are not tagged."},
    {"id": "R1", "group": "risk", "title": "Stop in force at entry", "status": "enforced",
     "definition": "A stop set within 10 minutes of the open (10.5 allowed); no stop or a later stop fails."},
    {"id": "R2", "group": "risk", "title": "Risk within capital limits", "status": "enforced",
     "definition": "1R (entry to stop x peak size) at most the per-trade limit in force when the trade opened (1% "
                   "of capital by default), and the 1R of every perp trade open when this one opened, this one "
                   "included, at most the total limit (5% by default). A per-trade limit above 1% applies only "
                   "if the risk gate was unlocked when the trade opened, as recorded when the trade was first "
                   "seen; otherwise 1%."},
    {"id": "R3", "group": "risk", "title": "Planned target at least 2R", "status": "enforced",
     "definition": "The nearest planned take-profit on the profit side of entry is at least 2R away by price."},
    {"id": "R4", "group": "risk", "title": "Stop inside half the liquidation distance", "status": "tracking",
     "definition": "The stop's distance from entry, as % of entry, at most half of 100 / leverage."},
    {"id": "M1", "group": "management", "title": "Planned take-profit left alone", "status": "enforced",
     "definition": "The first planned take-profit set is not edited, moved or cancelled while the trade is open "
                   "(cancels in the last 5 seconds before the close are close-time cleanup)."},
    {"id": "M2", "group": "management", "title": "Stop never widened", "status": "enforced",
     "definition": "After the first 10 minutes, no new stop further from entry than the stop it replaced while it "
                   "is still on the loss side of entry. Loosening a stop already at or past entry is a note, not a "
                   "fail."},
    {"id": "M3", "group": "management", "title": "Breakeven move", "status": "tracking",
     "definition": "When the stop first moved to entry or past it; R at that moment is not measured in v1."},
    {"id": "X1", "group": "exit", "title": "Revised exit has a reason", "status": "enforced",
     "definition": "A trade closed by a revised exit (a market or limit order instead of a stop or take-profit) has an "
                   "exit reason picked; trade notes do not count. A trade closed by a stop, a take-profit or "
                   "liquidation is neutral."},
    {"id": "X2", "group": "exit", "title": "Trade reviewed", "status": "enforced",
     "definition": "A closed trade has your review (Followed or Deviated)."},
]
_STATUS = {r["id"]: r["status"] for r in RULES}      # the registry defaults
RULE_IDS = tuple(r["id"] for r in RULES)
RULE_STATUSES = ("enforced", "tracking")
# Rules whose status can be changed (Landing 8b-2). M3 has no pass / fail test,
# so enforcing it would mean nothing: its status stays tracking.
FLIPPABLE = tuple(i for i in RULE_IDS if i != "M3")
_INF = 10 ** 16


# ── small helpers ────────────────────────────────────────────────────────

def _d(v):
    """A Decimal from a string / number, None when missing or not finite."""
    if v is None or isinstance(v, bool):
        return None
    try:
        x = Decimal(str(v).strip())
    except (InvalidOperation, ValueError):
        return None
    return x if x.is_finite() else None


def _ms(value):
    """An ISO time / "YYYY-MM-DD" string (naive reads as UTC) -> epoch ms, or None."""
    if not value:
        return None
    s = str(value).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _num(x):
    """A Decimal as a plain string without exponent or trailing zeros."""
    s = format(x.normalize(), "f")
    return s if s not in ("-0",) else "0"


def _usd(x):
    return f"${x:,.2f}"


def _minutes(a_ms, b_ms):
    return Decimal(b_ms - a_ms) / Decimal(60000)


def side(position, direction):
    """The noodle position read for a trade: "touch" stays "touch"; a long is
    "with" above and "against" below; a short the mirror. None when unknown."""
    if position == "touch":
        return "touch"
    if position not in ("above", "below"):
        return None
    if str(direction).lower() == "short":
        return "with" if position == "below" else "against"
    return "with" if position == "above" else "against"


def _result(rule, verdict, evidence, reason=None):
    return {"rule": rule, "status": _STATUS[rule], "verdict": verdict, "evidence": evidence,
            "reason": reason if verdict == "not_measurable" else None}


def _nm(rule, reason, evidence=None):
    return _result(rule, "not_measurable", evidence or reason.replace("_", " "), reason)


def _no_history_reason(trade):
    return "manual" if trade.get("source") == "manual" else "no_order_history"


def one_r_usd(trade):
    """1R in dollars: |entry - stop| x peak size, zero when the stop is at or
    past entry. None without an entry, a stop or a size."""
    entry = _d(trade.get("avg_entry"))
    stop = _d((trade.get("stop") or {}).get("px"))
    size = _d(trade.get("size_peak"))
    if entry is None or stop is None or size is None:
        return None
    dist = entry - stop if str(trade.get("direction")).lower() != "short" else stop - entry
    return max(dist, Decimal(0)) * abs(size)


def _stop_distance(trade):
    """(entry, stop, distance) with distance = entry - stop for a long (stop - entry
    for a short); distance <= 0 or None means no usable stop distance."""
    entry = _d(trade.get("avg_entry"))
    stop = _d((trade.get("stop") or {}).get("px"))
    if entry is None or stop is None:
        return entry, stop, None
    dist = entry - stop if str(trade.get("direction")).lower() != "short" else stop - entry
    return entry, stop, dist


def _effective_setup(tags):
    """The setup tag in force: "breakout" without break_what counts as not tagged."""
    tags = tags or {}
    setup = tags.get("setup")
    if setup not in SETUPS:
        return None
    if setup == "breakout" and not tags.get("break_what"):
        return None
    return setup


# ── settings: status changes and dated capital (Landing 8b-2) ────────────

def _now_ms():
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _date_ms(value):
    """A strict "YYYY-MM-DD" string -> epoch ms at 00:00 UTC, or None."""
    if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
        return None
    try:
        d = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return int(d.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _status_changes(settings):
    """{rule: [(from_ms, status, row)]} from settings["status"], sorted by time
    (rows at the same time keep their stored order, so the later one wins).
    Rows for a rule outside FLIPPABLE, with a status other than enforced /
    tracking, or with an unreadable "from" are ignored."""
    out = {}
    for row in (settings or {}).get("status") or []:
        if not isinstance(row, dict):
            continue
        rule, status, at = row.get("rule"), row.get("status"), _ms(row.get("from"))
        if rule not in FLIPPABLE or status not in RULE_STATUSES or at is None:
            continue
        out.setdefault(rule, []).append((at, status, row))
    for changes in out.values():
        changes.sort(key=lambda c: c[0])
    return out


def _status_change_at(rule, at_ms, changes):
    """The latest change of `rule` at or before at_ms, or None."""
    hit = None
    for c in changes.get(rule, ()):
        if c[0] <= at_ms:
            hit = c
    return hit


def status_at(rule, at_ms=None, settings=None, now_ms=None):
    """The rule's status for a trade opened at at_ms (epoch ms): the latest
    stored change at or before that time, else the registry default. at_ms
    None (open time unknown) gives the status now."""
    at = at_ms if at_ms is not None else (now_ms if now_ms is not None else _now_ms())
    hit = _status_change_at(rule, at, _status_changes(settings))
    return hit[1] if hit else _STATUS[rule]


def rules_view(settings=None, now_ms=None):
    """The registry with each rule's status now: every RULES field (status =
    the status now) plus "default_status", "status_since" (the "from" time of
    the change in force, None while on the default) and "flippable"."""
    now = now_ms if now_ms is not None else _now_ms()
    changes = _status_changes(settings)
    out = []
    for r in RULES:
        hit = _status_change_at(r["id"], now, changes)
        out.append(dict(r, status=hit[1] if hit else r["status"], default_status=r["status"],
                        status_since=hit[2].get("from") if hit else None, flippable=r["id"] in FLIPPABLE))
    return out


def capital_periods(settings=None):
    """The capital periods in date order: [{"from", "usd", "set_at"}]. The code
    default (CAPITAL_USD from CAPITAL_FROM, set_at None) stands unless a stored
    row for that date replaces it. For each date the latest stored row wins; a
    row with usd None removes that date's stored value (on CAPITAL_FROM the
    default comes back). Rows dated before CAPITAL_FROM, with an unreadable
    date, or with usd other than a positive whole number or None are ignored."""
    start = _date_ms(CAPITAL_FROM)
    by_date = {}
    for row in (settings or {}).get("capital") or []:
        if not isinstance(row, dict):
            continue
        frm, usd = row.get("from"), row.get("usd")
        at = _date_ms(frm)
        if at is None or at < start:
            continue
        if usd is None:
            by_date.pop(frm, None)
        elif isinstance(usd, int) and not isinstance(usd, bool) and usd > 0:
            by_date[frm] = {"from": frm, "usd": usd, "set_at": row.get("set_at")}
    if CAPITAL_FROM not in by_date:
        by_date[CAPITAL_FROM] = {"from": CAPITAL_FROM, "usd": CAPITAL_USD, "set_at": None}
    return [by_date[k] for k in sorted(by_date)]


def capital_at(at_ms, settings=None):
    """The capital period in force at at_ms: the one with the latest "from"
    date at or before it; None before CAPITAL_FROM."""
    hit = None
    for p in capital_periods(settings):
        if _date_ms(p["from"]) <= at_ms:
            hit = p
    return hit


def settings_changed_at(settings=None):
    """The "set_at" time of the latest stored change (status, capital or risk limits), or None."""
    times = [r.get("set_at") for key in ("status", "capital", "risk") for r in (settings or {}).get(key) or []
             if isinstance(r, dict) and _ms(r.get("set_at")) is not None]
    return max(times, key=_ms) if times else None


def _bps_pct(bps):
    """Basis points -> a percentage without trailing zeros: 100 -> "1", 150 -> "1.5"."""
    return _num(Decimal(bps) / 100)


def _is_bps(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _risk_changes(settings):
    """[(from_ms, row)] from settings["risk"], sorted by time (rows at the same
    time keep their stored order, so the later one wins). Rows with an
    unreadable "from", a value that isn't a whole number of basis points, or
    limits outside the bounds (RISK_MIN_BPS <= per trade <= RISK_PER_TRADE_MAX_BPS,
    per trade <= total <= RISK_TOTAL_MAX_BPS) are ignored."""
    out = []
    for row in (settings or {}).get("risk") or []:
        if not isinstance(row, dict):
            continue
        per_trade, total, at = row.get("per_trade_bps"), row.get("total_bps"), _ms(row.get("from"))
        if at is None or not _is_bps(per_trade) or not _is_bps(total):
            continue
        if not (RISK_MIN_BPS <= per_trade <= RISK_PER_TRADE_MAX_BPS and per_trade <= total <= RISK_TOTAL_MAX_BPS):
            continue
        out.append((at, row))
    out.sort(key=lambda c: c[0])
    return out


def risk_at(at_ms, settings=None):
    """R2's limits for a trade opened at at_ms (epoch ms): {"per_trade_bps",
    "total_bps", "since", "reason"} from the latest stored change at or before
    at_ms, else the defaults (since and reason None)."""
    hit = None
    for at, row in _risk_changes(settings):
        if at <= at_ms:
            hit = row
    if hit is None:
        return dict(RISK_DEFAULT, since=None, reason=None)
    return {"per_trade_bps": hit["per_trade_bps"], "total_bps": hit["total_bps"], "since": hit.get("from"),
            "reason": hit.get("reason")}


# ── order history (pure; the route passes stored records) ─────────────────

def _closing_kind(records, fills, coin, close_ms):
    """How the closing fill was made: {"kind": "trigger" | "hand" | "liquidation",
    "order_type"}, or None when the closing order cannot be found."""
    if close_ms is None:
        return None
    at = [f for f in fills or [] if isinstance(f, dict) and f.get("coin") == coin and f.get("time") == close_ms]
    if not at:
        return None

    def ends_flat(f):
        start, sz = _d(f.get("startPosition")), _d(f.get("sz"))
        if start is None or sz is None:
            return False
        end = start + sz if f.get("side") == "B" else start - sz
        return end == 0

    fill = next((f for f in at if ends_flat(f)), at[-1])
    if fill.get("liquidation") or "Liquidat" in str(fill.get("dir") or ""):
        return {"kind": "liquidation", "order_type": None}
    oid = fill.get("oid")
    recs = [r for r in records or [] if isinstance(r, dict) and isinstance(r.get("order"), dict)
            and r["order"].get("oid") == oid]
    if oid is None or not recs:
        return None
    types = [str(r["order"].get("orderType") or "") for r in recs]
    trigger = any(r["order"].get("isTrigger") or r.get("status") == "triggered" for r in recs) or any(
        "Stop" in t or "Take Profit" in t for t in types)
    return {"kind": "trigger" if trigger else "hand", "order_type": next((t for t in types if t), None)}


def trade_orders(stop_records, tp_records, fills, coin, direction, open_ms, close_ms):
    """One synced trade's order history in the shape the M and X rules read.
    stop_records / tp_records: Hyperliquid-shaped historicalOrders records (for
    TxFlow: txflow.to_hl_orders / txflow.to_hl_take_profits of the stored
    records); fills: the wallet's raw fills (carrying "oid"). Candidates follow
    hl_trades: the same coin, the closing side (A for a long, B for a short),
    isTrigger with a trigger price above 0, placed no earlier than
    STOP_LOOKBACK_MS before the open; stops need reduceOnly and 'Stop' in
    orderType, take-profits reduceOnly or isPositionTpsl and 'Take Profit'.

    Returns {"stops": [{"oid", "px", "placed"}], "tps": [...same...],
    "ends": {oid: latest non-'open' statusTimestamp}, "end_status": {oid: its
    status}, "tp_prices": {oid: set of trigger prices seen}, "open_ms",
    "close_ms", "closing": _closing_kind}."""
    closing_side = "A" if str(direction).lower() != "short" else "B"
    lo = open_ms - hl_trades.STOP_LOOKBACK_MS
    ends, end_status = {}, {}

    def scan(records, want):
        out, prices = {}, {}
        for h in records or []:
            if not isinstance(h, dict) or not isinstance(h.get("order"), dict):
                continue
            o = h["order"]
            oid = o.get("oid")
            if h.get("status") != "open":
                ts = int(h.get("statusTimestamp") or 0)
                if ts >= ends.get(oid, -1):
                    ends[oid], end_status[oid] = ts, h.get("status")
            px = _d(o.get("triggerPx"))
            if (o.get("isTrigger") and want(o) and px is not None and px > 0 and o.get("timestamp") is not None
                    and o.get("coin") == coin and o.get("side") == closing_side
                    and int(o["timestamp"]) >= lo):
                out[(oid, int(o["timestamp"]), px)] = {"oid": oid, "px": px, "placed": int(o["timestamp"])}
                prices.setdefault(oid, set()).add(px)
        return sorted(out.values(), key=lambda c: (c["placed"], str(c["oid"]))), prices

    stops, _ = scan(stop_records, lambda o: o.get("reduceOnly") and "Stop" in str(o.get("orderType") or ""))
    tps, tp_prices = scan(tp_records, lambda o: (o.get("reduceOnly") or o.get("isPositionTpsl"))
                          and "Take Profit" in str(o.get("orderType") or ""))
    return {"stops": stops, "tps": tps, "ends": ends, "end_status": end_status, "tp_prices": tp_prices,
            "open_ms": open_ms, "close_ms": close_ms,
            "closing": _closing_kind(stop_records, fills, coin, close_ms)}


def _in_force(cands, ends, t, exclude=None):
    alive = [c for c in cands if c["placed"] <= t and ends.get(c["oid"], _INF) > t and c is not exclude]
    return max(alive, key=lambda c: (c["placed"], str(c["oid"]))) if alive else None


# ── the rules ────────────────────────────────────────────────────────────

def _trend(trade):
    """(timeframes, None) for a usable open-snapshot trend, else (None, reason)."""
    tr = ((trade.get("open_snapshot") or {}).get("trend"))
    if not isinstance(tr, dict):
        return None, "not_captured"
    if tr.get("reason"):
        return None, str(tr["reason"])
    tfs = tr.get("timeframes")
    return (tfs, None) if isinstance(tfs, dict) else (None, "not_captured")


def _reading(tfs, wanted, direction):
    """{tf: (position, side)} for the wanted timeframes; None when one is missing."""
    out = {}
    for tf in wanted:
        pos = (tfs.get(tf) or {}).get("position") if isinstance(tfs.get(tf), dict) else None
        s = side(pos, direction)
        if s is None:
            return None
        out[tf] = (pos, s)
    return out


def rule_e1(trade):
    tfs, reason = _trend(trade)
    if tfs is None:
        return _nm("E1", reason, f"no usable snapshot at the open ({reason})")
    read = _reading(tfs, HIGHER_TFS, trade.get("direction"))
    if read is None:
        return _nm("E1", "incomplete_timeframes", "12h, 1d or 1w missing from the snapshot")
    text = ", ".join(f"{tf} {s} ({p})" if s != "touch" else f"{tf} touch" for tf, (p, s) in read.items())
    against = [tf for tf, (_, s) in read.items() if s == "against"]
    if against:
        return _result("E1", "fail", f"against on {', '.join(against)}: {text}")
    if all(s == "with" for _, s in read.values()):
        return _result("E1", "pass", text)
    return _result("E1", "neutral", text)


def rule_e2(trade, tags=None):
    tfs, reason = _trend(trade)
    if tfs is None:
        return _nm("E2", reason, f"no usable snapshot at the open ({reason})")
    read = _reading(tfs, LOWER_TFS, trade.get("direction"))
    if read is None:
        return _nm("E2", "incomplete_timeframes", "15m, 30m, 1h or 4h missing from the snapshot")
    touching = [tf for tf, (_, s) in read.items() if s == "touch"]
    against = [tf for tf, (_, s) in read.items() if s == "against"]
    text = f"touching: {', '.join(touching) or 'none'}; against: {', '.join(against) or 'none'}"
    setup = _effective_setup(tags)
    if against:
        return _result("E2", "fail", f"against on {', '.join(f'{tf} ({read[tf][0]})' for tf in against)}; {text}")
    if setup == "retest":
        if touching:
            return _result("E2", "pass", f"retest; {text}")
        return _result("E2", "fail", f"retest: no timeframe touching the noodle; {text}")
    if setup in ("breakout", "other"):
        return _result("E2", "self_reported", f"{setup}; {text}")
    return _result("E2", "not_tagged", f"setup not tagged; {text}")


def rule_e3(trade, tags=None):
    poi = (tags or {}).get("poi")
    if not poi:
        return _result("E3", "not_tagged", "no point of interest tagged")
    opened, closed, at = _ms(trade.get("opened_at")), _ms(trade.get("closed_at")), _ms(poi.get("tagged_at"))
    live = (at is not None and opened is not None and at <= opened + SETTLE_MS) or (
        at is not None and (closed is None or at < closed))
    what = " ".join(str(x) for x in (poi.get("type"), poi.get("timeframe")) if x)
    return _result("E3", "pass", f"{what or 'point of interest'}; {'tagged live' if live else 'tagged after close'}")


def rule_r1(trade):
    stop = trade.get("stop") or {}
    if stop.get("px") is None:
        return _result("R1", "fail", "no stop")
    set_ms, open_ms = _ms(stop.get("set_at")), _ms(trade.get("opened_at"))
    src = stop.get("source") or "unknown"
    if set_ms is None or open_ms is None:
        return _nm("R1", "stop_time_unknown", f"{src} stop at {stop['px']}, time set unknown")
    m = _minutes(open_ms, set_ms)
    when = (f"{m:.1f} min after entry" if m >= 0 else f"{-m:.1f} min before entry")
    verdict = "pass" if m <= R1_LIMIT_MIN else "fail"
    return _result("R1", verdict, f"{src} stop at {stop['px']}, set {when}")


def rule_r2(trade, all_trades, settings=None, now_ms=None):
    one_r = one_r_usd(trade)
    if (trade.get("stop") or {}).get("px") is None:
        return _nm("R2", "no_stop", "no stop: 1R unknown")
    if one_r is None:
        return _nm("R2", "no_entry", "entry or size unknown: 1R unknown")
    if one_r < NEGLIGIBLE_1R_USD:
        return _nm("R2", "negligible_size", f"1R {_usd(one_r)} is under {_usd(Decimal(NEGLIGIBLE_1R_USD))}")
    opened = _ms(trade.get("opened_at"))
    if opened is None or opened < _ms(CAPITAL_FROM):
        return _nm("R2", "before_capital_date", f"opened before the capital date {CAPITAL_FROM}")
    period = capital_at(opened, settings)      # never None from CAPITAL_FROM on (the default stands there)
    capital = Decimal(period["usd"])
    total, n = Decimal(0), 0
    for u in all_trades or []:
        if u.get("market") != "perp":
            continue
        u_open, u_close = _ms(u.get("opened_at")), _ms(u.get("closed_at"))
        if u is trade or (u.get("trade_id") is not None and u.get("trade_id") == trade.get("trade_id")):
            total += one_r
            n += 1
            continue
        if u_open is None or u_open > opened or (u_close is not None and opened >= u_close):
            continue
        total += one_r_usd(u) or Decimal(0)
        n += 1
    pct = one_r / capital * 100
    total_pct = total / capital * 100
    text = (f"1R {_usd(one_r)} ({pct:.2f}% of capital); open at entry {_usd(total)} ({total_pct:.2f}%) "
            f"across {n} trade{'s' if n != 1 else ''}")
    # Landing 16: the limits in force when the trade opened (the defaults without stored rows).
    limits = risk_at(opened, settings)
    # Landing 23: a per-trade limit above the default needs the risk gate unlocked at the open.
    per_trade_bps, gate_note = _r2_gate_limit(trade, limits["per_trade_bps"])
    if per_trade_bps is None:
        return _nm("R2", "gate_not_recorded",
                   f"risk gate at the open not recorded yet: the stored {_bps_pct(limits['per_trade_bps'])}% per "
                   f"trade applies only if it was unlocked")
    if pct > Decimal(per_trade_bps) / 100:
        res = _result("R2", "fail", f"over {_bps_pct(per_trade_bps)}% per trade: {text}")
    elif total_pct > Decimal(limits["total_bps"]) / 100:
        res = _result("R2", "fail", f"over {_bps_pct(limits['total_bps'])}% open in total: {text}")
    else:
        res = _result("R2", "pass", text)
    notes = []
    # Landing 8b-2: a note when the capital entry used was made after the trade
    # opened (dates only: notes are shown as sent under Hide values).
    set_ms = _ms(period.get("set_at"))
    if set_ms is not None and set_ms > opened:
        notes.append(f"capital entry for {period['from']} made {_iso(set_ms)}, after the trade opened")
    # Landing 16: a note when the limits now differ from those the trade was judged by.
    later = risk_at(now_ms if now_ms is not None else _now_ms(), settings)
    if (later["per_trade_bps"], later["total_bps"]) != (limits["per_trade_bps"], limits["total_bps"]):
        when = f"since {_iso(_ms(later['since']))}" if later["since"] else "now"
        notes.append(f"limits {_bps_pct(limits['per_trade_bps'])}% / {_bps_pct(limits['total_bps'])}% when this "
                     f"trade opened; {_bps_pct(later['per_trade_bps'])}% / {_bps_pct(later['total_bps'])}% {when}")
    if gate_note:
        notes.append(gate_note)
    if notes:
        res["notes"] = notes
    return res


def _r2_gate_limit(trade, stored_bps):
    """Landing 23: (the per-trade limit R2 applies, a note or None). At or below
    the default the stored limit applies and the gate record is not read. Above
    it, the trade's gate_at_open decides: unlocked -> the stored limit; locked ->
    the default; no usable record -> (None, None), R2 not measurable."""
    if stored_bps <= RISK_DEFAULT["per_trade_bps"]:
        return stored_bps, None
    g = trade.get("gate_at_open")
    if not isinstance(g, dict) or not isinstance(g.get("unlocked"), bool):
        return None, None
    seen = _ms(g.get("seen_at"))
    when = f" (recorded {_iso(seen)})" if seen is not None else ""
    if g["unlocked"]:
        return stored_bps, (f"risk gate unlocked when this trade opened{when}: the stored "
                            f"{_bps_pct(stored_bps)}% per trade applied")
    default = RISK_DEFAULT["per_trade_bps"]
    return default, (f"risk gate locked when this trade opened{when}: {_bps_pct(default)}% per trade applied "
                     f"instead of the stored {_bps_pct(stored_bps)}%")


def rule_r3(trade):
    prices = [p for p in ((trade.get("planned_target") or {}).get("prices") or []) if _d(p) is not None]
    if not prices:
        return _result("R3", "no_plan", "no planned take-profit")
    entry, stop, dist = _stop_distance(trade)
    if entry is None or dist is None or dist <= 0:
        return _nm("R3", "no_stop_distance", "no usable stop distance")
    short = str(trade.get("direction")).lower() == "short"
    good = [_d(p) for p in prices if (_d(p) < entry if short else _d(p) > entry)]
    if not good:
        return _result("R3", "fail", f"take-profit on the wrong side of entry {_num(entry)}")
    tp = max(good) if short else min(good)
    plan_r = abs(tp - entry) / dist
    text = f"plan {plan_r:.2f}R (take-profit {_num(tp)}, entry {_num(entry)}, stop {_num(stop)})"
    return _result("R3", "pass" if plan_r >= MIN_PLAN_R else "fail", text)


def rule_r4(trade, enforced=False):
    """Tracking (the default): verdict "tracking", the outcome at the end of the
    evidence. Enforced when the trade opened (Landing 8b-2): verdict pass / fail."""
    lev = _d(trade.get("leverage"))
    if lev is None or lev <= 0:
        return _nm("R4", "leverage_not_recorded", "leverage not recorded")
    entry, stop, _ = _stop_distance(trade)
    if entry is None or stop is None or entry == 0:
        return _nm("R4", "no_stop", "no stop")
    dist_pct = abs(entry - stop) / entry * 100
    limit = Decimal(100) / lev / 2
    ok = "pass" if dist_pct <= limit else "fail"
    text = f"stop {dist_pct:.2f}% from entry, limit {limit:.2f}% at {_num(lev)}x"
    if enforced:
        return _result("R4", ok, text)
    return _result("R4", "tracking", f"{text}: {ok}")


def rule_m1(trade, orders, now_ms=None):
    if orders is None:
        return _nm("M1", _no_history_reason(trade))
    open_ms, close_ms = orders["open_ms"], orders["close_ms"]
    end_cap = close_ms if close_ms is not None else _INF
    ends = orders["ends"]
    during = [c for c in orders["tps"]
              if (open_ms - hl_trades.STOP_LOOKBACK_MS <= c["placed"] <= open_ms and ends.get(c["oid"], _INF) > open_ms)
              or open_ms < c["placed"] <= end_cap]
    if not during:
        if (trade.get("planned_target") or {}).get("prices"):
            return _nm("M1", "no_order_history", "take-profit not in the order history")
        return _result("M1", "no_plan", "no planned take-profit")
    so_far = " (so far)" if close_ms is None else ""
    t0 = min(c["placed"] for c in during)
    first = [c for c in during if c["placed"] - t0 <= hl_trades.PLAN_GRACE_MS]
    limit = close_ms - TP_CLOSE_GRACE_MS if close_ms is not None else (now_ms if now_ms is not None else _INF)
    for c in first:
        if len(orders["tp_prices"].get(c["oid"], ())) > 1:
            return _result("M1", "fail", f"take-profit {_num(c['px'])} edited while the trade was open{so_far}")
        end, status = ends.get(c["oid"]), orders["end_status"].get(c["oid"])
        if end is not None and status not in ("filled", "triggered") and end < limit:
            m = _minutes(open_ms, end)
            return _result("M1", "fail", f"take-profit {_num(c['px'])} {status} at {_iso(end)}, "
                                         f"{m:.0f} min after entry{so_far}")
    moved = (trade.get("planned_target") or {}).get("moved_to")
    if moved:
        return _result("M1", "fail", f"planned target moved to {moved}{so_far}")
    return _result("M1", "pass", f"take-profit {', '.join(_num(c['px']) for c in first)} left in place{so_far}")


def rule_m2(trade, orders, now_ms=None):
    if orders is None:
        return _nm("M2", _no_history_reason(trade))
    stops = orders["stops"]
    if not stops:
        return _nm("M2", "no_stop_history", "no stop in the order history")
    open_ms, close_ms, ends = orders["open_ms"], orders["close_ms"], orders["ends"]
    start = open_ms + SETTLE_MS
    end = close_ms if close_ms is not None else (now_ms if now_ms is not None else _INF)
    short = str(trade.get("direction")).lower() == "short"
    entry = _d(trade.get("avg_entry"))
    first_fail, notes = None, []
    for c in stops:
        if not (start < c["placed"] <= end):
            continue
        prev = _in_force(stops, ends, c["placed"] - 1, exclude=c)
        if prev is None:
            gone = [s for s in stops if s is not c and s["placed"] < c["placed"] and ends.get(s["oid"], _INF) <= c["placed"]]
            prev = max(gone, key=lambda s: (ends.get(s["oid"], 0), s["placed"])) if gone else None
        if prev is None:
            continue
        looser = c["px"] > prev["px"] if short else c["px"] < prev["px"]
        if not looser:
            continue
        m = _minutes(open_ms, c["placed"])
        # Ruling C (Oct 5): only a loosening that leaves the stop on the loss side of entry is a widening.
        # At or past entry it is a tracking note. Without an entry every loosening counts as a widening.
        loss_side = entry is None or (c["px"] > entry if short else c["px"] < entry)
        if loss_side:
            if first_fail is None:
                first_fail = (f"stop widened {_num(prev['px'])} -> {_num(c['px'])} at {_iso(c['placed'])}, "
                              f"{m:.0f} min after entry")
        else:
            notes.append(f"stop loosened while already past breakeven: {_num(prev['px'])} -> {_num(c['px'])} at "
                         f"{_iso(c['placed'])}, {m:.0f} min after entry")
    so_far = " (so far)" if close_ms is None else ""
    if first_fail is not None:
        res = _result("M2", "fail", first_fail)
    else:
        res = _result("M2", "pass", f"no stop moved further from entry on the loss side after the first "
                                    f"{SETTLE_MIN} min{so_far}")
    if notes:
        res["notes"] = notes
    return res


def rule_m3(trade, orders):
    if orders is None:
        return _nm("M3", _no_history_reason(trade))
    entry = _d(trade.get("avg_entry"))
    if entry is None:
        return _nm("M3", "no_entry", "entry unknown")
    open_ms, close_ms = orders["open_ms"], orders["close_ms"]
    end = close_ms if close_ms is not None else _INF
    short = str(trade.get("direction")).lower() == "short"
    for c in orders["stops"]:
        if open_ms < c["placed"] <= end and (c["px"] <= entry if short else c["px"] >= entry):
            m = _minutes(open_ms, c["placed"])
            return _result("M3", "tracking", f"stop moved to {_num(c['px'])} (entry {_num(entry)}) at "
                                             f"{_iso(c['placed'])}, {m:.0f} min after entry; R at the move not measured")
    return _result("M3", "tracking", "no breakeven move")


def rule_x1(trade, orders):
    if trade.get("status") != "closed":
        return _nm("X1", "open", "trade still open")
    if orders is None:
        return _nm("X1", _no_history_reason(trade))
    closing = orders.get("closing")
    if not closing or closing.get("kind") is None:
        return _nm("X1", "closing_order_unknown", "the order that closed the trade is not in the history")
    if closing["kind"] == "trigger":
        return _result("X1", "neutral", "closed by a stop/take-profit")
    if closing["kind"] == "liquidation":
        return _result("X1", "neutral", "closed by liquidation")
    how = f"revised exit ({closing.get('order_type') or 'order'})"
    label = exit_reason_label((trade.get("annotation") or {}).get("exit_reason"), trade.get("direction"))
    if label:
        return _result("X1", "pass", f"{how}; reason: {label}")
    return _result("X1", "fail", f"{how} without an exit reason")


def rule_x2(trade, enforced_fails):
    if trade.get("status") != "closed":
        return _nm("X2", "open", "trade still open")
    followed = (trade.get("annotation") or {}).get("followed_rules")
    tail = f"Rules v{DEFINITION_VERSION}: {enforced_fails} enforced fail{'s' if enforced_fails != 1 else ''}"
    if followed is None:
        return _result("X2", "fail", f"needs review; {tail}")
    return _result("X2", "pass", f"Your review: {'Followed' if followed else 'Deviated'}; {tail}")


# ── per trade and per route ──────────────────────────────────────────────

def evaluate_trade(trade, orders, all_trades, tags=None, now_ms=None, settings=None):
    """Every rule for one perp trade. orders: trade_orders(...) for a synced
    trade, None when there is no order history (manual trades: reason
    "manual"). all_trades: every trade (R2 sums the perps open at this
    trade's open). tags: optional {"setup", "setup_tagged_at", "break_what",
    "poi"}. now_ms: "now" for open trades (M1 / M2 so far). settings: optional
    stored status changes and capital (Landing 8b-2, see the module docstring).

    Each result's status is the rule's status when the trade opened (the
    registry default without settings); a result whose status then differs
    from the status now carries a note.

    Returns {"rules": [results in registry order], "enforced_fails": [rule ids],
    "tracking": [{"rule", "verdict", "evidence"}], "measured": results whose
    verdict is not not_measurable / not_tagged}."""
    opened = _ms(trade.get("opened_at"))
    now = now_ms if now_ms is not None else _now_ms()
    changes = _status_changes(settings)

    def status(rule, at):
        hit = _status_change_at(rule, at, changes)
        return (hit[1], hit[2].get("from")) if hit else (_STATUS[rule], None)

    at_open = {rid: status(rid, opened if opened is not None else now)[0] for rid in RULE_IDS}

    def stamp(res):
        rid = res["rule"]
        res["status"] = at_open[rid]
        now_status, since = status(rid, now)
        if now_status != at_open[rid]:
            when = f"since {_iso(_ms(since))}" if since is not None else "now"
            res.setdefault("notes", []).append(f"{at_open[rid]} when this trade opened; {now_status} {when}")
        return res

    results = [rule_e1(trade), rule_e2(trade, tags), rule_e3(trade, tags),
               rule_r1(trade), rule_r2(trade, all_trades, settings, now), rule_r3(trade),
               rule_r4(trade, enforced=at_open["R4"] == "enforced"),
               rule_m1(trade, orders, now_ms), rule_m2(trade, orders, now_ms), rule_m3(trade, orders),
               rule_x1(trade, orders)]
    results = [stamp(r) for r in results]
    fails = sum(1 for r in results if r["status"] == "enforced" and r["verdict"] == "fail")
    results.append(stamp(rule_x2(trade, fails)))
    return {"rules": results,
            "enforced_fails": [r["rule"] for r in results if r["status"] == "enforced" and r["verdict"] == "fail"],
            "tracking": [{"rule": r["rule"], "verdict": r["verdict"], "evidence": r["evidence"]}
                         for r in results if r["status"] == "tracking"],
            "measured": sum(1 for r in results if r["verdict"] not in ("not_measurable", "not_tagged"))}


def tally(evaluated, trades_by_id):
    """Route-level counts: per rule {verdict: n}; closed perps with zero / at
    least one enforced fail; per rule the number of trades failing. No average
    R by group (a console lead only)."""
    by_rule = {r["id"]: {} for r in RULES}
    failing = {r["id"]: 0 for r in RULES}
    clean = flagged = 0
    for tid, ev in evaluated.items():
        for res in ev["rules"]:
            counts = by_rule[res["rule"]]
            counts[res["verdict"]] = counts.get(res["verdict"], 0) + 1
            if res["verdict"] == "fail":
                failing[res["rule"]] += 1
        if (trades_by_id.get(tid) or {}).get("status") == "closed":
            if ev["enforced_fails"]:
                flagged += 1
            else:
                clean += 1
    return {"by_rule": by_rule, "closed_without_enforced_fails": clean, "closed_with_enforced_fails": flagged,
            "failing_by_rule": failing}


def _capital_now(settings, now):
    """{"usd", "from"} of the capital period in force at `now` (the first period
    before CAPITAL_FROM)."""
    p = capital_at(now, settings) or capital_periods(settings)[0]
    return {"usd": p["usd"], "from": p["from"]}


def evaluate_all(trades, orders_by_trade, tags_by_trade=None, now_ms=None, settings=None):
    """The route's response for every perp trade (market == perp, open and
    closed) in `trades`: {"definition_version", "capital" (the period in force
    now: {"usd", "from"}), "rules" (the registry, each rule's status = its
    status now), "trades": {trade_id: {"rules", "enforced_fails", "tracking",
    "measured"}}, "tally", "note"}. settings: optional stored status changes
    and capital (Landing 8b-2); without them the response is the same as
    before 8b-2. The settings themselves (history, periods, defaults) are
    settings_view's job."""
    perps = [t for t in trades or [] if t.get("market") == "perp"]
    tags_by_trade = tags_by_trade or {}
    now = now_ms if now_ms is not None else _now_ms()
    out = {}
    for t in perps:
        out[t["trade_id"]] = evaluate_trade(t, (orders_by_trade or {}).get(t["trade_id"]), trades,
                                            tags_by_trade.get(t["trade_id"]), now_ms, settings)
    status_now = {r["id"]: r["status"] for r in rules_view(settings, now)}
    return {"definition_version": DEFINITION_VERSION,
            "capital": _capital_now(settings, now),
            "rules": [dict(r, status=status_now[r["id"]]) for r in RULES],
            "trades": out,
            "tally": tally(out, {t["trade_id"]: t for t in perps}),
            "note": TALLY_NOTE}


def settings_view(settings=None, now_ms=None):
    """The rule settings as the settings route returns them (Landing 8b-2):
    {"rules": rules_view (with "status_reason", the reason stored with the
    change in force), "capital": the period in force now, "capital_periods",
    "capital_start": CAPITAL_FROM, "status_changes": [{"rule", "status",
    "from", "reason"}] and "capital_changes": [{"from", "usd", "set_at"}]
    as stored (oldest first), "settings_changed_at"}. Landing 16 adds
    "risk_limits" (R2's limits now: {"per_trade_bps", "total_bps", "since",
    "reason"}), "risk_default", "risk_bounds" ({"min_bps",
    "per_trade_max_bps", "total_max_bps", "locked_max_bps": the most per
    trade while the risk gate is locked}) and "risk_changes" ([{"per_trade_bps",
    "total_bps", "from", "reason"}] as stored, oldest first)."""
    now = now_ms if now_ms is not None else _now_ms()
    changes = _status_changes(settings)
    rules = rules_view(settings, now)
    for r in rules:
        hit = _status_change_at(r["id"], now, changes)
        r["status_reason"] = hit[2].get("reason") if hit else None
    stored = settings or {}
    return {"rules": rules,
            "capital": _capital_now(settings, now),
            "capital_periods": [dict(p) for p in capital_periods(settings)],
            "capital_start": CAPITAL_FROM,
            "status_changes": [{"rule": r.get("rule"), "status": r.get("status"), "from": r.get("from"),
                                "reason": r.get("reason")}
                               for r in stored.get("status") or [] if isinstance(r, dict)],
            "capital_changes": [{"from": r.get("from"), "usd": r.get("usd"), "set_at": r.get("set_at")}
                                for r in stored.get("capital") or [] if isinstance(r, dict)],
            "settings_changed_at": settings_changed_at(settings),
            "risk_limits": risk_at(now, settings),
            "risk_default": dict(RISK_DEFAULT),
            "risk_bounds": {"min_bps": RISK_MIN_BPS, "per_trade_max_bps": RISK_PER_TRADE_MAX_BPS,
                            "total_max_bps": RISK_TOTAL_MAX_BPS, "locked_max_bps": RISK_DEFAULT["per_trade_bps"]},
            "risk_changes": [{"per_trade_bps": r.get("per_trade_bps"), "total_bps": r.get("total_bps"),
                              "from": r.get("from"), "reason": r.get("reason")}
                             for r in stored.get("risk") or [] if isinstance(r, dict)]}


# ── the 1% -> 2% risk gate (Landing 17) ──────────────────────────────────
# Glenn, Oct 7 (A; Q1-Q3 A): a closed perp trade counts toward the risk gate
# only when, beyond the gate's own checks (web_portfolio._trades_gate_reason),
# the setup and the POI were tagged before it closed, the rule check has no
# enforced fail, it had a take-profit, and every enforced rule could be
# checked. A rule's status is its status when the trade opened; tracking
# rules never block. static/perps.js labels every reason (a test pins them).
GATE_REASONS = ("not_tagged", "tagged_after_close", "rule_fail", "no_plan", "unchecked")
GATE_TAG_RULES = ("E2", "E3")          # E2 reads the setup tag, E3 the POI tag


def _tag_missing(rule, tags):
    if rule == "E2":
        return _effective_setup(tags) is None
    return not (tags or {}).get("poi")


def gate_check(evaluation, tags, tags_now=None):
    """Why the rule check keeps a closed perp trade out of the risk gate, as
    (reason, rule ids, why); (None, [], {}) when it does not.

    evaluation: evaluate_trade's result for the trade, computed with `tags`,
    the tags saved before the trade closed (None when there were none).
    tags_now: its current tags, used only to tell "tagged_after_close" from
    "not_tagged". The first that applies:
      not_tagged / tagged_after_close - E2 (the setup) or E3 (the POI) is
        enforced and its tag was not saved before the close; rule ids = the
        parts missing; tagged_after_close when the current tags have them;
      rule_fail - evaluation["enforced_fails"] (each rule's status when the
        trade opened);
      no_plan - an enforced rule reads "no_plan" (R3 or M1: no take-profit);
      unchecked - an enforced rule is not_measurable; why = {rule id: its
        reason} (e.g. "not_captured", "negligible_size", "manual").
    Pure: reads its arguments only."""
    results = [r for r in (evaluation or {}).get("rules") or [] if isinstance(r, dict)]
    enforced = [r for r in results if r.get("status") == "enforced"]
    tag_rules = [r["rule"] for r in enforced if r.get("rule") in GATE_TAG_RULES]
    missing = [rid for rid in GATE_TAG_RULES if rid in tag_rules and _tag_missing(rid, tags)]
    if missing:
        later = tags_now is not None and not any(_tag_missing(rid, tags_now) for rid in missing)
        return ("tagged_after_close" if later else "not_tagged"), missing, {}
    fails = [rid for rid in (evaluation or {}).get("enforced_fails") or []]
    if fails:
        return "rule_fail", fails, {}
    plan = [r["rule"] for r in enforced if r.get("verdict") == "no_plan"]
    if plan:
        return "no_plan", plan, {}
    unmeasured = [r for r in enforced if r.get("verdict") == "not_measurable"]
    if unmeasured:
        return ("unchecked", [r["rule"] for r in unmeasured],
                {r["rule"]: r.get("reason") or "unknown" for r in unmeasured})
    return None, [], {}


# ── before the close: what an open trade still needs to count (Landing 22) ──
# Glenn, Oct 9: an open perp trade is flagged while it lacks something the
# risk gate will ask for at the close that can still be added while it is
# open: the setup tag (E2), the POI tag (E3) and a take-profit (R3 / M1:
# gate_check's no_plan). Each part is asked for only while its rule was
# enforced when the trade opened, as gate_check judges it. Which trades are
# flagged at all (open, synced, trading book, opened since the gate's count
# date) is web_portfolio's call (_trades_gate_prep). static/perps.js and
# static/utils.js use the same part names (a test pins them).
GATE_PREP_PARTS = ("setup", "poi", "take_profit")


def _take_profit_missing(trade):
    """True only when the trade is known to have no take-profit: no planned
    take-profit recorded (planned_target: the stored orders, or the prices
    the snapshot pass saw live) and the venue's live read lists none. False
    when either has a price, and when the live read is missing, stale (the
    last read failed, so these are older figures) or could not read the
    take-profits (take_profits not a list): unknown is not missing."""
    planned = (trade.get("planned_target") or {}).get("prices") or []
    if any(_d(p) is not None for p in planned):
        return False
    live = trade.get("live")
    if not isinstance(live, dict) or live.get("stale"):
        return False
    tps = live.get("take_profits")
    if not isinstance(tps, list):
        return False
    return not any(_d(p) is not None for p in tps)


def gate_prep(trade, tags=None, settings=None, now_ms=None):
    """The parts an open perp trade still needs before its close to count
    toward the risk gate, in GATE_PREP_PARTS order; [] when none.
      setup       - E2 enforced when the trade opened and no setup tag in
                    force (a breakout without "what broke" counts as none);
      poi         - E3 enforced when the trade opened and no POI tag;
      take_profit - R3 or M1 enforced when the trade opened and the trade is
                    known to have no take-profit (_take_profit_missing).
    tags: the trade's current tags in evaluate_trade's shape (None when
    untagged). settings: as evaluate_trade's. A trade whose open time cannot
    be read is judged by the statuses now. Pure: reads its arguments only."""
    opened = _ms(trade.get("opened_at"))
    status = lambda rule: status_at(rule, opened, settings, now_ms)
    missing = []
    if status("E2") == "enforced" and _tag_missing("E2", tags):
        missing.append("setup")
    if status("E3") == "enforced" and _tag_missing("E3", tags):
        missing.append("poi")
    if (status("R3") == "enforced" or status("M1") == "enforced") and _take_profit_missing(trade):
        missing.append("take_profit")
    return missing
