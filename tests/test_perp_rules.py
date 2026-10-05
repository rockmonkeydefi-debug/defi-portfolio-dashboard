"""Advisor v1, Landing 8a (HANDOFF_spot_perps_rebuild.md 16-20): the pure perp
rule evaluator (src/engines/perp_rules.py) and the read-only route
GET /api/trading/advisor/perps.

Rule tests use hand-built trade dicts in the trades route's shape and
Hyperliquid-shaped order records; the recorded, sanitized exports in
tests/fixtures/hl_trading back the closing-order and widened-stop checks.
Route tests use a real init_db() on a tmp_path SQLite file
(portfolio_db.get_db_path monkeypatched). No network. Fake wallet addresses
only, built in code; made-up prices and sizes.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import json
import os
import re
import threading
from datetime import datetime, timezone
from decimal import Decimal

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import hl_trades
import txflow
import src.storage.portfolio_db as portfolio_db
from src.engines import perp_rules as pr

HL_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "hl_trading")
TXF_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "txflow")
W = "0x" + "e" * 40
MIN = 60000
HOUR = 3600000
DAY = 86400000
T0 = int(datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def trend(reason=None, direction_ok=True, **pos):
    """An open_snapshot with a trend part; pos maps timeframe -> position."""
    tfs = {tf: {"position": p, "state": "IGNORED"} for tf, p in pos.items()}
    return {"trend": {"v": 1, "reason": reason, "timeframes": {} if reason else tfs}, "leverage": None}


ALL_ABOVE = dict(m15="above", m30="above", h1="above", h4="above", h12="above", d1="above", w1="above")


def snap(reason=None, **pos):
    names = {"m15": "15m", "m30": "30m", "h1": "1h", "h4": "4h", "h12": "12h", "d1": "1d", "w1": "1w"}
    return trend(reason, **{names[k]: v for k, v in pos.items()})


def trade(**kw):
    t = {"trade_id": "t1", "market": "perp", "source": "hyperliquid", "status": "closed", "direction": "long",
         "symbol": "ETH", "opened_at": _iso(T0), "closed_at": _iso(T0 + DAY), "avg_entry": "100",
         "size_peak": "10", "stop": {"px": "95", "source": "hl_order", "set_at": _iso(T0 + 2 * MIN)},
         "planned_target": None, "leverage": None, "net_pnl": "10",
         "annotation": {"followed_rules": None, "notes": None, "deviation_note": None},
         "open_snapshot": snap(**ALL_ABOVE)}
    t.update(kw)
    return t


def rec(oid, px, placed, side="A", coin="ETH", status="open", status_ts=None, kind="Stop Market", reduce_only=True,
        trigger=True):
    return {"status": status, "statusTimestamp": status_ts if status_ts is not None else placed,
            "order": {"coin": coin, "side": side, "oid": oid, "timestamp": placed, "triggerPx": str(px),
                      "isTrigger": trigger, "reduceOnly": reduce_only, "isPositionTpsl": False,
                      "orderType": kind, "children": []}}


def ended(oid, px, placed, at, status="canceled", **kw):
    return [rec(oid, px, placed, **kw), rec(oid, px, placed, status=status, status_ts=at, **kw)]


def tp(oid, px, placed, **kw):
    return rec(oid, px, placed, kind="Take Profit Market", **kw)


def tp_ended(oid, px, placed, at, status="canceled", **kw):
    return ended(oid, px, placed, at, status=status, kind="Take Profit Market", **kw)


def orders(records, fills=(), direction="long", open_ms=T0, close_ms=T0 + DAY, coin="ETH"):
    return pr.trade_orders(records, records, list(fills), coin, direction, open_ms, close_ms)


def by_rule(result):
    return {r["rule"]: r for r in result["rules"]}


def has_number(text):
    return re.search(r"\d", text) is not None


# ── the registry ─────────────────────────────────────────────────────────

def test_registry_definitions_statuses_and_constants():
    ids = [r["id"] for r in pr.RULES]
    assert ids == ["E1", "E2", "E3", "R1", "R2", "R3", "R4", "M1", "M2", "M3", "X1", "X2"]
    for r in pr.RULES:
        assert r["definition"].strip() and r["title"].strip() and r["group"] in ("entry", "risk", "management", "exit")
        assert r["status"] in ("enforced", "tracking")
    assert {r["id"] for r in pr.RULES if r["status"] == "tracking"} == {"R4", "M3"}
    assert pr.SETTLE_MIN * 60000 == hl_trades.SETTLE_MS
    assert (pr.CAPITAL_USD, pr.CAPITAL_FROM, pr.RISK_PER_TRADE_PCT, pr.RISK_TOTAL_PCT) == (50000, "2026-09-13", 1, 5)
    assert (pr.MIN_PLAN_R, pr.NEGLIGIBLE_1R_USD, pr.DEFINITION_VERSION) == (Decimal("2.0"), 5, 2)


def test_tracking_rules_never_count_as_enforced_fails():
    # R4 reads "fail" in its text (stop far beyond half the liquidation distance) and M3 reports a move.
    t = trade(leverage="50", stop={"px": "80", "source": "hl_order", "set_at": _iso(T0 + 30 * MIN)})
    o = orders([rec(1, 80, T0 + 30 * MIN), rec(2, 101, T0 + 3 * HOUR)])
    res = pr.evaluate_trade(t, o, [t], now_ms=T0 + 2 * DAY)
    rules = by_rule(res)
    assert rules["R4"]["verdict"] == "tracking" and rules["R4"]["evidence"].endswith(": fail")
    assert rules["M3"]["verdict"] == "tracking" and "R at the move not measured" in rules["M3"]["evidence"]
    assert "R4" not in res["enforced_fails"] and "M3" not in res["enforced_fails"]
    assert {x["rule"] for x in res["tracking"]} == {"R4", "M3"}
    for r in res["rules"]:
        assert r["status"] == pr._STATUS[r["rule"]] and r["verdict"] in pr.VERDICTS
        assert (r["reason"] is not None) == (r["verdict"] == "not_measurable")


# ── direction mirror and E1 ──────────────────────────────────────────────

def test_side_mirror():
    assert pr.side("above", "long") == "with" and pr.side("below", "long") == "against"
    assert pr.side("below", "short") == "with" and pr.side("above", "short") == "against"
    assert pr.side("touch", "short") == "touch" and pr.side(None, "long") is None


def test_e1_long_pass_fail_neutral():
    assert pr.rule_e1(trade())["verdict"] == "pass"
    r = pr.rule_e1(trade(open_snapshot=snap(h12="above", d1="below", w1="above")))
    assert r["verdict"] == "fail" and "1d" in r["evidence"]
    assert pr.rule_e1(trade(open_snapshot=snap(h12="touch", d1="above", w1="above")))["verdict"] == "neutral"


def test_e1_short_mirror():
    short = dict(direction="short")
    assert pr.rule_e1(trade(open_snapshot=snap(h12="below", d1="below", w1="below"), **short))["verdict"] == "pass"
    r = pr.rule_e1(trade(open_snapshot=snap(h12="below", d1="below", w1="above"), **short))
    assert r["verdict"] == "fail" and "1w" in r["evidence"]
    assert pr.rule_e1(trade(open_snapshot=snap(h12="touch", d1="below", w1="below"), **short))["verdict"] == "neutral"


def test_e1_missing_snapshot_reasons():
    r = pr.rule_e1(trade(open_snapshot=None))
    assert r["verdict"] == "not_measurable" and r["reason"] == "not_captured"
    r = pr.rule_e1(trade(open_snapshot={"trend": None, "leverage": None}))
    assert r["reason"] == "not_captured"
    r = pr.rule_e1(trade(open_snapshot=snap(reason="price_mismatch")))
    assert r["verdict"] == "not_measurable" and r["reason"] == "price_mismatch"
    r = pr.rule_e1(trade(open_snapshot=snap(h12="above", d1="above", w1=None)))
    assert r["reason"] == "incomplete_timeframes"


# ── E2 ───────────────────────────────────────────────────────────────────

LOWER_TOUCH = dict(m15="touch", m30="above", h1="above", h4="above")
LOWER_CLEAN = dict(m15="above", m30="above", h1="above", h4="above")


def test_e2_retest_pass_and_fail():
    t = trade(open_snapshot=snap(**LOWER_TOUCH))
    r = pr.rule_e2(t, {"setup": "retest"})
    assert r["verdict"] == "pass" and "15m" in r["evidence"]
    r = pr.rule_e2(trade(open_snapshot=snap(**LOWER_CLEAN)), {"setup": "retest"})
    assert r["verdict"] == "fail" and "no timeframe touching the noodle" in r["evidence"]


def test_e2_breakout_other_self_reported_untagged_not_tagged():
    t = trade(open_snapshot=snap(**LOWER_TOUCH))
    assert pr.rule_e2(t, {"setup": "breakout", "break_what": {"kind": "range", "timeframe": "4h"}})["verdict"] == \
        "self_reported"
    assert pr.rule_e2(t, {"setup": "other"})["verdict"] == "self_reported"
    r = pr.rule_e2(t, None)
    assert r["verdict"] == "not_tagged" and "touching: 15m" in r["evidence"]


def test_e2_breakout_without_break_what_is_untagged():
    t = trade(open_snapshot=snap(**LOWER_TOUCH))
    assert pr.rule_e2(t, {"setup": "breakout", "break_what": None})["verdict"] == "not_tagged"
    assert pr._effective_setup({"setup": "breakout"}) is None
    assert pr._effective_setup({"setup": "breakout", "break_what": {"kind": "high", "timeframe": "1d"}}) == "breakout"
    assert pr._effective_setup({"setup": "nonsense"}) is None


def test_e2_against_fails_whatever_the_tag():
    t = trade(open_snapshot=snap(m15="touch", m30="above", h1="below", h4="above"))
    for tags in ({"setup": "breakout", "break_what": {"kind": "range", "timeframe": "1h"}}, {"setup": "retest"}, None):
        r = pr.rule_e2(t, tags)
        assert r["verdict"] == "fail" and "1h (below)" in r["evidence"]


def test_e2_short_mirror_and_missing_snapshot():
    t = trade(direction="short", open_snapshot=snap(m15="below", m30="touch", h1="below", h4="below"))
    assert pr.rule_e2(t, {"setup": "retest"})["verdict"] == "pass"
    t = trade(direction="short", open_snapshot=snap(m15="below", m30="touch", h1="above", h4="below"))
    assert pr.rule_e2(t, {"setup": "retest"})["verdict"] == "fail"
    r = pr.rule_e2(trade(open_snapshot=None), {"setup": "retest"})
    assert r["verdict"] == "not_measurable" and r["reason"] == "not_captured"


# ── E3 ───────────────────────────────────────────────────────────────────

def test_e3_tags():
    assert pr.rule_e3(trade(), None)["verdict"] == "not_tagged"
    r = pr.rule_e3(trade(), {"poi": {"type": "order block", "timeframe": "4h", "tagged_at": _iso(T0 + 5 * MIN)}})
    assert r["verdict"] == "pass" and "tagged live" in r["evidence"] and "4h" in r["evidence"]
    r = pr.rule_e3(trade(), {"poi": {"type": "range low", "timeframe": "1d", "tagged_at": _iso(T0 + 2 * DAY)}})
    assert r["verdict"] == "pass" and "tagged after close" in r["evidence"]
    r = pr.rule_e3(trade(status="open", closed_at=None),
                   {"poi": {"type": "fvg", "timeframe": "1h", "tagged_at": _iso(T0 + 2 * DAY)}})
    assert "tagged live" in r["evidence"]


# ── R1 ───────────────────────────────────────────────────────────────────

def test_r1_pass_late_boundary_and_sources():
    r = pr.rule_r1(trade())
    assert r["verdict"] == "pass" and "hl_order" in r["evidence"] and "2.0 min" in r["evidence"]
    r = pr.rule_r1(trade(stop={"px": "95", "source": "txflow_order", "set_at": _iso(T0 + 15 * MIN)}))
    assert r["verdict"] == "fail" and "txflow_order" in r["evidence"] and "15.0 min" in r["evidence"]
    assert pr.rule_r1(trade(stop={"px": "95", "source": "hl_order", "set_at": _iso(T0 + 630000)}))["verdict"] == "pass"
    assert pr.rule_r1(trade(stop={"px": "95", "source": "hl_order", "set_at": _iso(T0 + 631000)}))["verdict"] == "fail"
    r = pr.rule_r1(trade(stop={"px": "95", "source": "manual", "set_at": _iso(T0 + 3 * HOUR)}))
    assert r["verdict"] == "fail" and "manual" in r["evidence"]
    r = pr.rule_r1(trade(stop={"px": "95", "source": "manual_log", "set_at": _iso(T0)}))
    assert r["verdict"] == "pass" and "manual_log" in r["evidence"]
    r = pr.rule_r1(trade(stop={"px": "95", "source": "hl_order", "set_at": _iso(T0 - 3 * MIN)}))
    assert r["verdict"] == "pass" and "3.0 min before entry" in r["evidence"]


def test_r1_no_stop_and_unknown_time():
    assert pr.rule_r1(trade(stop=None))["verdict"] == "fail"
    r = pr.rule_r1(trade(stop={"px": "95", "source": "txflow_tpsl", "set_at": None}))
    assert r["verdict"] == "not_measurable" and r["reason"] == "stop_time_unknown" and "txflow_tpsl" in r["evidence"]


# ── R2 ───────────────────────────────────────────────────────────────────

def test_r2_pass_and_per_trade_breach():
    t = trade()                                                            # 1R = 5 x 10 = $50 = 0.10%
    r = pr.rule_r2(t, [t])
    assert r["verdict"] == "pass" and "$50.00" in r["evidence"] and "0.10%" in r["evidence"]
    big = trade(size_peak="120")                                           # 1R = $600 = 1.20%
    r = pr.rule_r2(big, [big])
    assert r["verdict"] == "fail" and "1.20%" in r["evidence"] and "per trade" in r["evidence"]


def test_r2_concurrency_breach():
    # Each 1R $450 (0.90%); six open at this trade's open = $2,700 (5.4%) > 5%.
    others = [trade(trade_id=f"o{i}", size_peak="90", opened_at=_iso(T0 - (i + 1) * HOUR), closed_at=None,
                    status="open") for i in range(5)]
    closed_before = trade(trade_id="gone", size_peak="90", opened_at=_iso(T0 - 2 * DAY), closed_at=_iso(T0 - DAY))
    spot = trade(trade_id="sp", market="spot", size_peak="900", opened_at=_iso(T0 - HOUR), closed_at=None)
    later = trade(trade_id="later", size_peak="90", opened_at=_iso(T0 + HOUR))
    me = trade(size_peak="90")
    r = pr.rule_r2(me, others + [closed_before, spot, later, me])
    assert r["verdict"] == "fail" and "$2,700.00" in r["evidence"] and "6 trades" in r["evidence"]
    r = pr.rule_r2(me, others[:3] + [me])
    assert r["verdict"] == "pass" and "$1,800.00" in r["evidence"]


def test_r2_before_capital_date_negligible_and_no_stop():
    early = trade(opened_at="2026-09-01T10:00:00+00:00")
    r = pr.rule_r2(early, [early])
    assert r["verdict"] == "not_measurable" and r["reason"] == "before_capital_date"
    # A tiny trade (an Oct 1 BTC-style 0.0005 position, 1R about $1.20) lands on negligible_size.
    tiny = trade(symbol="BTC", opened_at="2026-10-01T09:00:00+00:00", avg_entry="61500", size_peak="0.0005",
                 stop={"px": "59100", "source": "hl_order", "set_at": "2026-10-01T09:01:00+00:00"})
    r = pr.rule_r2(tiny, [tiny])
    assert r["verdict"] == "not_measurable" and r["reason"] == "negligible_size" and "$1.20" in r["evidence"]
    past = trade(stop={"px": "101", "source": "hl_order", "set_at": _iso(T0)})        # stop past entry: 1R zero
    assert pr.rule_r2(past, [past])["reason"] == "negligible_size"
    assert pr.rule_r2(trade(stop=None), [])["reason"] == "no_stop"


# ── R3 ───────────────────────────────────────────────────────────────────

def plan(*prices, moved_to=None):
    return {"prices": list(prices), "source": "hl_order", "set_at": _iso(T0), "moved_to": moved_to, "moved_at": None}


def test_r3_no_plan_wrong_side_and_boundaries():
    assert pr.rule_r3(trade())["verdict"] == "no_plan"
    r = pr.rule_r3(trade(planned_target=plan("90")))
    assert r["verdict"] == "fail" and "wrong side" in r["evidence"]
    r = pr.rule_r3(trade(planned_target=plan("110")))                     # 10 / 5 = 2.00R exactly
    assert r["verdict"] == "pass" and "2.00R" in r["evidence"]
    r = pr.rule_r3(trade(planned_target=plan("109.85")))                  # 9.85 / 5 = 1.97R
    assert r["verdict"] == "fail" and "1.97R" in r["evidence"]
    r = pr.rule_r3(trade(planned_target=plan("90", "112", "120")))        # the nearest profit-side one
    assert r["verdict"] == "pass" and "take-profit 112" in r["evidence"]


def test_r3_short_and_no_stop_distance():
    t = trade(direction="short", stop={"px": "105", "source": "hl_order", "set_at": _iso(T0)},
              planned_target=plan("85", "92"))
    r = pr.rule_r3(t)
    assert r["verdict"] == "fail" and "1.60R" in r["evidence"]           # nearest is 92: 8 / 5
    r = pr.rule_r3(trade(stop=None, planned_target=plan("120")))
    assert r["verdict"] == "not_measurable" and r["reason"] == "no_stop_distance"


# ── R4 ───────────────────────────────────────────────────────────────────

def test_r4_tracking():
    r = pr.rule_r4(trade())
    assert r["verdict"] == "not_measurable" and r["reason"] == "leverage_not_recorded"
    r = pr.rule_r4(trade(leverage="5"))                                    # 5% <= (100 / 5) / 2 = 10%
    assert r["verdict"] == "tracking" and "5.00%" in r["evidence"] and r["evidence"].endswith(": pass")
    r = pr.rule_r4(trade(leverage="20"))                                   # 5% > 2.5%
    assert r["verdict"] == "tracking" and "2.50%" in r["evidence"] and r["evidence"].endswith(": fail")


# ── M1 ───────────────────────────────────────────────────────────────────

def test_m1_pass_and_moved():
    o = orders([tp(1, 110, T0 + MIN), tp(2, 120, T0 + MIN + 20000)])
    t = trade(planned_target=plan("110", "120"))
    r = pr.rule_m1(t, o)
    assert r["verdict"] == "pass" and "110" in r["evidence"]
    r = pr.rule_m1(trade(planned_target=plan("110", moved_to="125")), o)
    assert r["verdict"] == "fail" and "125" in r["evidence"]


def test_m1_cancelled_while_open_vs_close_time_cleanup():
    t = trade(planned_target=plan("110"))
    o = orders(tp_ended(1, 110, T0 + MIN, T0 + 3 * HOUR))
    r = pr.rule_m1(t, o)
    assert r["verdict"] == "fail" and "canceled" in r["evidence"] and "180 min" in r["evidence"]
    o = orders(tp_ended(1, 110, T0 + MIN, T0 + DAY - 3000, status="reduceOnlyCanceled"))      # 3 s before the close
    assert pr.rule_m1(t, o)["verdict"] == "pass"
    o = orders(tp_ended(1, 110, T0 + MIN, T0 + DAY, status="filled"))                          # the target hit
    assert pr.rule_m1(t, o)["verdict"] == "pass"


def test_m1_edited_open_trade_and_missing_history():
    t = trade(planned_target=plan("110"))
    o = orders([tp(1, 110, T0 + MIN), tp(1, 115, T0 + MIN)])                                    # same oid, new price
    assert pr.rule_m1(t, o)["verdict"] == "fail"
    open_t = trade(status="open", closed_at=None, planned_target=plan("110"))
    o = orders(tp_ended(1, 110, T0 + MIN, T0 + 2 * HOUR), close_ms=None)
    r = pr.rule_m1(open_t, o, now_ms=T0 + DAY)
    assert r["verdict"] == "fail" and "(so far)" in r["evidence"]
    assert pr.rule_m1(trade(), orders([]))["verdict"] == "no_plan"
    seen = trade(planned_target={"prices": ["110"], "source": "seen_live", "set_at": None, "moved_to": None,
                                 "moved_at": None})
    r = pr.rule_m1(seen, orders([]))
    assert r["verdict"] == "not_measurable" and r["reason"] == "no_order_history"
    r = pr.rule_m1(trade(source="manual"), None)
    assert r["verdict"] == "not_measurable" and r["reason"] == "manual"


# ── M2 ───────────────────────────────────────────────────────────────────

def test_m2_widening_after_settle_window_fails():
    o = orders(ended(1, 95, T0, T0 + 61 * MIN) + [rec(2, 93, T0 + 61 * MIN)])
    r = pr.rule_m2(trade(), o)
    assert r["verdict"] == "fail" and "95 -> 93" in r["evidence"] and "61 min" in r["evidence"]


def test_m2_correction_inside_window_and_tightening_pass():
    o = orders(ended(1, 97, T0, T0 + 3 * MIN) + ended(2, 93, T0 + 3 * MIN, T0 + 2 * HOUR) + [rec(3, 96, T0 + 2 * HOUR)])
    r = pr.rule_m2(trade(), o)
    assert r["verdict"] == "pass" and "10 min" in r["evidence"]


def test_m2_short_widening_cancel_then_replace_and_no_history():
    o = orders(ended(1, 105, T0, T0 + HOUR, side="B") + [rec(2, 108, T0 + HOUR, side="B")], direction="short")
    assert pr.rule_m2(trade(direction="short"), o)["verdict"] == "fail"
    # The old stop cancelled, a wider one placed 20 minutes later: still the stop it replaced.
    o = orders(ended(1, 95, T0, T0 + HOUR) + [rec(2, 90, T0 + HOUR + 20 * MIN)])
    assert pr.rule_m2(trade(), o)["verdict"] == "fail"
    r = pr.rule_m2(trade(), orders([tp(1, 110, T0)]))
    assert r["verdict"] == "not_measurable" and r["reason"] == "no_stop_history"
    assert pr.rule_m2(trade(source="manual"), None)["reason"] == "manual"


def test_m2_recorded_btc_stop_widened_61_minutes_in():
    fills, recs = _hl("rm.fills.json"), _hl("rm.hist_orders.json")
    cycles = hl_trades.build_cycles("w", fills, _hl("rm.funding.json"), recs)["cycles"]
    fails = []
    for c in cycles:
        o = pr.trade_orders(recs, recs, fills, c["coin"], c["direction"], c["open_time"], c["close_time"])
        r = pr.rule_m2({"direction": c["direction"], "source": "hyperliquid"}, o)
        if r["verdict"] == "fail":
            fails.append((c["coin"], r["evidence"]))
    assert len(fails) == 1 and fails[0][0] == "BTC" and "61 min after entry" in fails[0][1]


def test_m2_loss_side_widening_fails_without_notes():
    # BTC-style: entry 100, stop 95 loosened to 93 an hour in - still below entry.
    o = orders(ended(1, 95, T0, T0 + 61 * MIN) + [rec(2, 93, T0 + 61 * MIN)])
    r = pr.rule_m2(trade(), o)
    assert r["verdict"] == "fail" and "95 -> 93" in r["evidence"] and "notes" not in r


def test_m2_in_profit_loosening_is_a_note():
    t = trade(avg_entry="104.13")
    o = orders(ended(1, "105.684", T0 + 5 * HOUR, T0 + 6 * HOUR) + [rec(2, "105.670", T0 + 6 * HOUR)])
    r = pr.rule_m2(t, o)
    assert r["verdict"] == "pass" and len(r["notes"]) == 1
    assert "stop loosened while already past breakeven" in r["notes"][0]
    assert "105.684 -> 105.67" in r["notes"][0] and "360 min" in r["notes"][0]
    assert "M2" not in pr.evaluate_trade(t, o, [t])["enforced_fails"]


def test_m2_short_mirror():
    short = trade(direction="short", avg_entry="100", stop={"px": "105", "source": "hl_order", "set_at": _iso(T0)})
    o = orders(ended(1, 105, T0, T0 + HOUR, side="B") + [rec(2, 107, T0 + HOUR, side="B")], direction="short")
    r = pr.rule_m2(short, o)
    assert r["verdict"] == "fail" and "notes" not in r
    o = orders(ended(1, 97, T0 + HOUR, T0 + 2 * HOUR, side="B") + [rec(2, 98, T0 + 2 * HOUR, side="B")],
               direction="short")
    r = pr.rule_m2(short, o)
    assert r["verdict"] == "pass" and "past breakeven" in r["notes"][0]


def test_m2_stop_exactly_at_entry_is_not_the_loss_side():
    o = orders(ended(1, 102, T0 + HOUR, T0 + 2 * HOUR) + [rec(2, 100, T0 + 2 * HOUR)])
    r = pr.rule_m2(trade(), o)
    assert r["verdict"] == "pass" and "102 -> 100" in r["notes"][0]
    o = orders(ended(1, 98, T0 + HOUR, T0 + 2 * HOUR, side="B") + [rec(2, 100, T0 + 2 * HOUR, side="B")],
               direction="short")
    assert pr.rule_m2(trade(direction="short"), o)["verdict"] == "pass"


def test_m2_profit_side_to_loss_side_fails():
    o = orders(ended(1, 102, T0 + HOUR, T0 + 2 * HOUR) + [rec(2, 99, T0 + 2 * HOUR)])
    r = pr.rule_m2(trade(), o)
    assert r["verdict"] == "fail" and "102 -> 99" in r["evidence"] and "notes" not in r


def test_m2_a_note_and_a_fail_give_fail():
    o = orders(ended(1, 95, T0, T0 + HOUR) + ended(2, 93, T0 + HOUR, T0 + 3 * HOUR)        # loss-side widening
               + ended(3, 104, T0 + 3 * HOUR, T0 + 4 * HOUR) + [rec(4, 102, T0 + 4 * HOUR)])  # in-profit loosening
    r = pr.rule_m2(trade(), o)
    assert r["verdict"] == "fail" and "95 -> 93" in r["evidence"]
    assert len(r["notes"]) == 1 and "104 -> 102" in r["notes"][0]


def test_m2_no_loosening_has_no_notes():
    o = orders(ended(1, 95, T0, T0 + HOUR) + [rec(2, 97, T0 + HOUR)])
    r = pr.rule_m2(trade(), o)
    assert r["verdict"] == "pass" and "notes" not in r
    assert set(r) == {"rule", "status", "verdict", "evidence", "reason"}


# ── M3 ───────────────────────────────────────────────────────────────────

def test_m3_breakeven_move_and_none():
    o = orders(ended(1, 95, T0, T0 + 3 * HOUR) + [rec(2, 100, T0 + 3 * HOUR)])
    r = pr.rule_m3(trade(), o)
    assert r["verdict"] == "tracking" and "180 min" in r["evidence"] and "R at the move not measured" in r["evidence"]
    r = pr.rule_m3(trade(), orders([rec(1, 95, T0)]))
    assert r["verdict"] == "tracking" and r["evidence"] == "no breakeven move"
    assert pr.rule_m3(trade(source="manual"), None)["reason"] == "manual"


# ── X1 ───────────────────────────────────────────────────────────────────

def fill(coin, tid, t, side, sz, px, start, oid, pnl="0", **kw):
    f = {"coin": coin, "tid": tid, "time": t, "side": side, "sz": sz, "px": px, "startPosition": start,
         "closedPnl": pnl, "fee": "0", "builderFee": "0", "dir": "x", "oid": oid, "hash": "0x0"}
    f.update(kw)
    return f


def test_x1_revised_exit_needs_an_exit_reason_not_notes():
    # Rules v2 (Landing 8c-2): a revised exit passes on an exit reason; notes no longer count.
    close = T0 + DAY
    recs = [rec(50, 0, close, kind="Market", trigger=False, reduce_only=False, status="filled")]
    fills = [fill("ETH", 1, T0, "B", "10", "100", "0", 40), fill("ETH", 2, close, "A", "10", "101", "10", 50)]
    o = orders(recs, fills)
    assert o["closing"] == {"kind": "hand", "order_type": "Market"}
    r = pr.rule_x1(trade(), o)
    assert r["verdict"] == "fail" and r["evidence"] == "revised exit (Market) without an exit reason"
    r = pr.rule_x1(trade(annotation={"followed_rules": None, "notes": "momentum died", "deviation_note": None}), o)
    assert r["verdict"] == "fail"
    ann = {"followed_rules": None, "notes": None, "deviation_note": None, "exit_reason": "emotional",
           "exit_reason_note": "private text"}
    r = pr.rule_x1(trade(annotation=ann), o)
    assert r["verdict"] == "pass" and r["evidence"] == "revised exit (Market); reason: Emotional"
    assert "private text" not in r["evidence"]
    r = pr.rule_x1(trade(annotation=dict(ann, exit_reason="reversal_pattern")), o)
    assert r["evidence"].endswith("reason: Topping pattern")
    r = pr.rule_x1(trade(direction="short", annotation=dict(ann, exit_reason="reversal_pattern")), o)
    assert r["evidence"].endswith("reason: Bottoming pattern")
    r = pr.rule_x1(trade(annotation=dict(ann, exit_reason="not_a_reason")), o)
    assert r["verdict"] == "fail"


def test_exit_reason_list():
    assert pr.EXIT_REASON_KEYS == ("fundamental_thesis_changed", "sd_level_broke", "reversal_pattern",
                                   "took_profit_early", "time_stop", "cut_risk", "emotional", "other")
    assert pr.EXIT_REASON_NOTE_REQUIRED == ("other",)
    assert pr.exit_reason_label("sd_level_broke") == "S/D level broke" and pr.exit_reason_label("x") is None


def test_x1_trigger_unknown_open_liquidation():
    close = T0 + DAY
    recs = ended(60, 95, T0, close, status="triggered")
    fills = [fill("ETH", 2, close, "A", "10", "95", "10", 60)]
    assert pr.rule_x1(trade(), orders(recs, fills))["verdict"] == "neutral"
    r = pr.rule_x1(trade(), orders([], fills))
    assert r["verdict"] == "not_measurable" and r["reason"] == "closing_order_unknown"
    assert pr.rule_x1(trade(), orders(recs, []))["reason"] == "closing_order_unknown"
    r = pr.rule_x1(trade(status="open", closed_at=None), orders(recs, fills, close_ms=None))
    assert r["verdict"] == "not_measurable" and r["reason"] == "open"
    liq = [fill("ETH", 2, close, "A", "10", "80", "10", 61, liquidation={"method": "market"})]
    r = pr.rule_x1(trade(), orders([], liq))
    assert r["verdict"] == "neutral" and "liquidation" in r["evidence"]
    assert pr.rule_x1(trade(source="manual"), None)["reason"] == "manual"


def test_x1_recorded_closes_and_txflow_trigger():
    fills, recs = _hl("rm.fills.json"), _hl("rm.hist_orders.json")
    cycles = hl_trades.build_cycles("w", fills, _hl("rm.funding.json"), recs)["cycles"]
    kinds = [pr.trade_orders(recs, recs, fills, c["coin"], c["direction"], c["open_time"], c["close_time"])["closing"]
             ["kind"] for c in cycles if c["status"] == "closed"]
    assert kinds.count("hand") == 3 and kinds.count("trigger") == 6
    t_fills = json.load(open(os.path.join(TXF_FIX, "userFills.json")))
    t_recs = json.load(open(os.path.join(TXF_FIX, "historicalOrders.json")))
    pengu_close = next(f["time"] for f in t_fills if f["coin"] == "PENGU" and f["side"] == "A")
    o = pr.trade_orders(txflow.to_hl_orders(t_recs), txflow.to_hl_take_profits(t_recs), t_fills, "PENGU", "long",
                        pengu_close - DAY, pengu_close)
    assert o["closing"]["kind"] == "trigger"


def _hl(name):
    with open(os.path.join(HL_FIX, name)) as f:
        return json.load(f)


# ── X2 and the per-trade summary ─────────────────────────────────────────

def test_x2_review_and_enforced_fail_count():
    t = trade(annotation={"followed_rules": True, "notes": None, "deviation_note": None})
    r = pr.rule_x2(t, 0)
    assert r["verdict"] == "pass" and "Your review: Followed" in r["evidence"] and "0 enforced fails" in r["evidence"]
    r = pr.rule_x2(trade(annotation={"followed_rules": False, "notes": None, "deviation_note": None}), 1)
    assert r["verdict"] == "pass" and "Deviated" in r["evidence"] and "1 enforced fail" in r["evidence"]
    r = pr.rule_x2(trade(), 3)
    assert r["verdict"] == "fail" and "needs review" in r["evidence"] and "3 enforced fails" in r["evidence"]
    assert pr.rule_x2(trade(status="open", closed_at=None), 0)["reason"] == "open"


def test_evaluate_trade_summary_and_x2_counts_the_others():
    t = trade(stop=None)                                                  # R1 fails; R2 / R3 not measurable
    res = pr.evaluate_trade(t, orders([]), [t])
    rules = by_rule(res)
    assert [r["rule"] for r in res["rules"]] == [r["id"] for r in pr.RULES]
    assert res["enforced_fails"] == ["R1", "X2"] and "1 enforced fail" in rules["X2"]["evidence"]
    assert rules["E2"]["verdict"] == "not_tagged" and rules["E3"]["verdict"] == "not_tagged"
    assert res["measured"] == sum(1 for r in res["rules"] if r["verdict"] not in ("not_measurable", "not_tagged"))
    for r in res["rules"]:
        if r["verdict"] in ("pass", "fail"):
            assert r["evidence"]


def test_evidence_carries_numbers():
    t = trade(planned_target=plan("112"), leverage="5")
    o = orders(ended(1, 95, T0, T0 + 61 * MIN) + [rec(2, 93, T0 + 61 * MIN), tp(3, 112, T0 + MIN)])
    res = by_rule(pr.evaluate_trade(t, o, [t]))
    for rid in ("E1", "R1", "R2", "R3", "R4", "M1", "M2"):
        assert has_number(res[rid]["evidence"]), rid


def test_evaluate_all_and_tally():
    a = trade(trade_id="a", annotation={"followed_rules": True, "notes": None, "deviation_note": None})
    b = trade(trade_id="b", stop=None)
    c = trade(trade_id="c", status="open", closed_at=None)
    s = trade(trade_id="s", market="spot")
    out = pr.evaluate_all([a, b, c, s], {}, now_ms=T0 + 2 * DAY)
    assert set(out["trades"]) == {"a", "b", "c"}
    assert out["capital"] == {"usd": 50000, "from": "2026-09-13"} and out["note"] == pr.TALLY_NOTE
    tally = out["tally"]
    assert tally["closed_without_enforced_fails"] == 1 and tally["closed_with_enforced_fails"] == 1
    assert tally["failing_by_rule"]["R1"] == 1 and tally["by_rule"]["R1"] == {"pass": 2, "fail": 1}
    assert sum(tally["by_rule"]["X2"].values()) == 3
    assert "avg" not in json.dumps(tally)


# ── the route ────────────────────────────────────────────────────────────

BTC_OPEN, BTC_CLOSE = T0, T0 + 20 * HOUR
ETH_OPEN, ETH_CLOSE = T0 + 2 * DAY, T0 + 2 * DAY + 5 * HOUR
SOL_OPEN = T0 + 3 * DAY


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {W: {"label": "HL main"}})
    monkeypatch.setattr(wp, "_hl_post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HL call")))
    monkeypatch.setattr(wp, "_txflow_post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no TxFlow call")))
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": None, "wallets": {}})
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    conn = portfolio_db.get_connection()
    conn.execute("INSERT INTO hl_sync_state (wallet, first_seen_at, last_sync_at, last_ok_at) VALUES (?, ?, ?, ?)",
                 (W, "2026-09-01T00:00:00+00:00", "2026-09-26T00:00:00+00:00", "2026-09-26T00:00:00+00:00"))
    # BTC: long 0.01 from 100,000, stop 99,000 hit at the close (a trigger exit).
    # ETH: long 1 from 4,000, closed by a market order (a revised exit, no notes).
    # SOL: long 10 from 150, still open.
    for f in (fill("BTC", 1, BTC_OPEN, "B", "0.01", "100000", "0", 101),
              fill("BTC", 2, BTC_CLOSE, "A", "0.01", "99000", "0.01", 11, pnl="-10"),
              fill("ETH", 3, ETH_OPEN, "B", "1", "4000", "0", 103),
              fill("ETH", 4, ETH_CLOSE, "A", "1", "4100", "1", 104, pnl="100"),
              fill("SOL", 5, SOL_OPEN, "B", "10", "150", "0", 105)):
        conn.execute("INSERT INTO hl_fills (wallet, tid, coin, time_ms, raw_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (W, f["tid"], f["coin"], f["time"], json.dumps(f), "2026-09-26T00:00:00+00:00"))
    records = (ended(11, 99000, BTC_OPEN + MIN, BTC_CLOSE, coin="BTC", status="triggered")
               + tp_ended(12, 103000, BTC_OPEN + MIN, BTC_CLOSE, coin="BTC", status="reduceOnlyCanceled")
               + ended(13, 3950, ETH_OPEN, ETH_CLOSE, coin="ETH", status="reduceOnlyCanceled")
               + [rec(104, 0, ETH_CLOSE, coin="ETH", kind="Market", trigger=False, reduce_only=False, status="filled")]
               + [rec(15, 145, SOL_OPEN + MIN, coin="SOL")])
    for i, r in enumerate(records):
        conn.execute("INSERT INTO hl_orders (wallet, oid, coin, status, status_ts, order_ts, raw_json, fetched_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (W, r["order"]["oid"], r["order"]["coin"], r["status"], r["statusTimestamp"] + i,
                      r["order"]["timestamp"], json.dumps(r), "2026-09-26T00:00:00+00:00"))
    conn.execute("INSERT INTO spot_trade_log (ticker, direction, source, venue, entry_price, stop_price, qty, "
                 "target_price, exit_price, entered_at, exited_at, followed_rules, market, created_at, updated_at) "
                 "VALUES ('DOGE', 'long', 'MHC', 'Manual', 0.2, 0.19, 1000, 0.23, 0.22, ?, ?, 1, 'perp', 'x', 'x')",
                 (_iso(T0 + HOUR), _iso(T0 + 5 * HOUR)))
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def client(db, monkeypatch):
    calls = []
    for name in ("_maybe_kick_hl_trades_refresh", "_maybe_kick_txflow_trades_refresh",
                 "_maybe_kick_hl_accounts_refresh", "_maybe_kick_txflow_refresh", "_trade_snapshot_pass",
                 "_trade_exit_pass_safe", "_trade_snapshot_worker", "_hl_candles_range", "_hl_candles_before"):
        monkeypatch.setattr(wp, name, lambda *a, _n=name, **k: calls.append(_n) or
                            (_ for _ in ()).throw(AssertionError(f"{_n} called")))
    monkeypatch.setattr(wp.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP")))
    monkeypatch.setattr(wp.requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP")))
    monkeypatch.setattr(threading.Thread, "start", lambda self, *a, **k: calls.append("thread"))
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    c.calls = calls
    return c


def advisor(client):
    r = client.get('/api/trading/advisor/perps')
    assert r.status_code == 200, r.get_data(as_text=True)
    return r


def ids_by_symbol(db):
    trades, _ = wp._trades_build(db)
    return {t["symbol"]: t["trade_id"] for t in trades}


def test_route_shape_and_verdicts(db, client):
    ids = ids_by_symbol(db)
    # A stored open snapshot for BTC (all with the long): E2 then reads not_tagged (no setup tags in 8a).
    tfs = {tf: {"position": "above"} for tf in ("15m", "30m", "1h", "4h", "12h", "1d", "1w")}
    db.execute("INSERT INTO trade_annotations (trade_id, market, scanner_snapshot_json, created_at, updated_at) "
               "VALUES (?, 'perp', ?, 'x', 'x')", (ids["BTC"], json.dumps({"trend": {"v": 1, "reason": None,
                                                                                    "timeframes": tfs}})))
    db.commit()
    body = advisor(client).get_json()
    assert set(body) == {"definition_version", "capital", "rules", "trades", "tally", "note"}
    assert body["definition_version"] == 2 and body["capital"] == {"usd": 50000, "from": "2026-09-13"}
    assert [r["id"] for r in body["rules"]] == [r["id"] for r in pr.RULES]
    assert set(body["trades"]) == {ids["BTC"], ids["ETH"], ids["SOL"], ids["DOGE"]}
    btc = by_rule(body["trades"][ids["BTC"]])
    assert btc["X1"]["verdict"] == "neutral" and btc["M1"]["verdict"] == "pass" and btc["R1"]["verdict"] == "pass"
    assert btc["E1"]["verdict"] == "pass"
    assert btc["E2"]["verdict"] == "not_tagged" and btc["E3"]["verdict"] == "not_tagged"
    assert by_rule(body["trades"][ids["ETH"]])["E2"]["reason"] == "not_captured"     # no snapshot stored
    eth = by_rule(body["trades"][ids["ETH"]])
    assert eth["X1"]["verdict"] == "fail" and eth["X2"]["verdict"] == "fail"
    sol = by_rule(body["trades"][ids["SOL"]])                                  # open: handled
    assert sol["X1"]["reason"] == "open" and sol["X2"]["reason"] == "open" and sol["M2"]["verdict"] == "pass"
    doge = by_rule(body["trades"][ids["DOGE"]])                                # manual perp: no order history
    for rid in ("M1", "M2", "M3", "X1"):
        assert doge[rid]["verdict"] == "not_measurable" and doge[rid]["reason"] == "manual"
    assert doge["X2"]["verdict"] == "pass" and doge["R1"]["verdict"] == "pass"
    assert body["tally"]["closed_with_enforced_fails"] + body["tally"]["closed_without_enforced_fails"] == 3
    assert body["note"] == "lead only: small sample, one market period"


def test_route_is_read_only_with_one_build_and_no_calls(db, client, monkeypatch):
    before = "\n".join(db.iterdump())
    builds = []
    real = wp._trades_build
    monkeypatch.setattr(wp, "_trades_build", lambda conn, extras=None: builds.append(1) or real(conn, extras))
    advisor(client)
    assert builds == [1]
    assert client.calls == []
    db2 = portfolio_db.get_connection()
    try:
        assert "\n".join(db2.iterdump()) == before
    finally:
        db2.close()


def test_route_leaks_no_wallet(db, client):
    text = advisor(client).get_data(as_text=True)
    assert W not in text and W[2:] not in text and "HL main" not in text
    assert re.search(r"0x[0-9a-fA-F]{40}", text) is None
    assert "_order_ref" not in text and "wallet" not in text


def test_trades_route_still_hides_the_order_ref(db, client, monkeypatch):
    monkeypatch.setattr(wp, "_maybe_kick_hl_trades_refresh", lambda now, force=False: False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_trades_refresh", lambda now, force=False: False)
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", lambda now: False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", lambda now: False)
    text = client.get('/api/trading/trades').get_data(as_text=True)
    assert "_order_ref" not in text and W not in text
