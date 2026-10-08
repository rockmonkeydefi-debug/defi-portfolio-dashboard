"""Landing 17 (HANDOFF_advisor_v1.md section 37): perp_rules.gate_check, the
pure part of the 1% -> 2% risk gate's rule check.

Glenn, Oct 7 (A; Q1-Q3 A): a closed perp trade counts only when the setup
and the POI were tagged before it closed, the rule check has no enforced
fail, it had a take-profit, and every enforced rule could be checked. A
rule's status is its status when the trade opened; tracking rules never
block.

Hand-built trade dicts in the trades route's shape and Hyperliquid-shaped
order records. No database, no network, no app import. Made-up prices and
sizes; no wallet addresses.
"""
import copy
from datetime import datetime, timezone

from src.engines import perp_rules as pr

MIN = 60000
DAY = 86400000
T0 = int(datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)
CLOSE = T0 + DAY


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


TFS = {"15m": "touch", "30m": "above", "1h": "above", "4h": "above", "12h": "above", "1d": "above", "1w": "above"}


def snap(reason=None, **override):
    tfs = dict(TFS, **override)
    return {"trend": {"v": 1, "reason": reason,
                      "timeframes": {} if reason else {tf: {"position": p} for tf, p in tfs.items()}},
            "leverage": None}


def trade(**kw):
    """A long that passes every enforced rule: stop 2 min after entry, 1R $50, take-profit at 2R left alone
    and filled, reviewed Followed."""
    t = {"trade_id": "t1", "market": "perp", "source": "hyperliquid", "status": "closed", "direction": "long",
         "symbol": "ETH", "opened_at": _iso(T0), "closed_at": _iso(CLOSE), "avg_entry": "100", "size_peak": "10",
         "stop": {"px": "95", "source": "hl_order", "set_at": _iso(T0 + 2 * MIN)},
         "planned_target": {"prices": ["110"], "source": "hl_order", "set_at": _iso(T0 + 2 * MIN),
                            "moved_to": None, "moved_at": None},
         "leverage": None, "net_pnl": "100",
         "annotation": {"followed_rules": True, "notes": None, "deviation_note": None, "exit_reason": None,
                        "exit_reason_note": None},
         "open_snapshot": snap()}
    t.update(kw)
    return t


def rec(oid, px, placed, kind, status="open", status_ts=None):
    return {"status": status, "statusTimestamp": status_ts if status_ts is not None else placed,
            "order": {"coin": "ETH", "side": "A", "oid": oid, "timestamp": placed, "triggerPx": str(px),
                      "isTrigger": True, "reduceOnly": True, "isPositionTpsl": False, "orderType": kind,
                      "children": []}}


RECORDS = [rec(1, 95, T0 + 2 * MIN, "Stop Market"),
           rec(1, 95, T0 + 2 * MIN, "Stop Market", status="canceled", status_ts=CLOSE),
           rec(2, 110, T0 + 2 * MIN, "Take Profit Market"),
           rec(2, 110, T0 + 2 * MIN, "Take Profit Market", status="filled", status_ts=CLOSE)]
FILLS = [{"coin": "ETH", "tid": 9, "time": CLOSE, "side": "A", "sz": "10", "px": "110", "startPosition": "10",
          "closedPnl": "100", "fee": "0", "builderFee": "0", "dir": "Close Long", "oid": 2, "hash": "0x0"}]


def orders(records=RECORDS, fills=FILLS):
    return pr.trade_orders(records, records, fills, "ETH", "long", T0, CLOSE)


TAGS = {"setup": "retest", "setup_tagged_at": _iso(T0 + 5 * MIN), "break_what": None,
        "poi": {"type": "order_block", "timeframe": "1h", "tagged_at": _iso(T0 + 5 * MIN)}}


def evaluate(t=None, o="default", tags=TAGS, settings=None):
    t = t or trade()
    return pr.evaluate_trade(t, orders() if o == "default" else o, [t], tags, now_ms=CLOSE + DAY, settings=settings)


def check(t=None, o="default", tags=TAGS, tags_now=None, settings=None):
    return pr.gate_check(evaluate(t, o, tags, settings), tags, tags_now)


def flip(rule, status, at_ms):
    return {"rule": rule, "status": status, "from": _iso(at_ms), "reason": "test", "set_at": _iso(at_ms)}


# ── the clean trade ──────────────────────────────────────────────────────

def test_reasons_constant():
    assert pr.GATE_REASONS == ("not_tagged", "tagged_after_close", "rule_fail", "no_plan", "unchecked")
    assert pr.GATE_TAG_RULES == ("E2", "E3")


def test_a_clean_trade_counts():
    ev = evaluate()
    verdicts = {r["rule"]: r["verdict"] for r in ev["rules"] if r["status"] == "enforced"}
    assert verdicts == {"E1": "pass", "E2": "pass", "E3": "pass", "R1": "pass", "R2": "pass", "R3": "pass",
                        "M1": "pass", "M2": "pass", "X1": "neutral", "X2": "pass"}
    assert pr.gate_check(ev, TAGS) == (None, [], {})
    assert pr.gate_check(ev, TAGS, TAGS) == (None, [], {})


def test_gate_check_is_pure():
    ev = evaluate()
    ev_copy, tags_copy = copy.deepcopy(ev), copy.deepcopy(TAGS)
    pr.gate_check(ev, TAGS, TAGS)
    assert ev == ev_copy and TAGS == tags_copy


# ── tags saved before the close ──────────────────────────────────────────

def test_no_tags_is_not_tagged_with_both_parts():
    assert check(tags=None) == ("not_tagged", ["E2", "E3"], {})
    assert check(tags={}) == ("not_tagged", ["E2", "E3"], {})


def test_one_part_missing():
    assert check(tags=dict(TAGS, poi=None)) == ("not_tagged", ["E3"], {})
    assert check(tags=dict(TAGS, setup=None)) == ("not_tagged", ["E2"], {})


def test_a_breakout_without_what_broke_is_not_tagged():
    assert check(tags=dict(TAGS, setup="breakout", break_what=None)) == ("not_tagged", ["E2"], {})
    brk = dict(TAGS, setup="breakout", break_what={"kind": "trendline", "timeframe": "4h"})
    assert check(tags=brk) == (None, [], {})          # E2 self_reported counts (working assumption)
    assert {r["rule"]: r["verdict"] for r in evaluate(tags=brk)["rules"]}["E2"] == "self_reported"


def test_tagged_after_close_when_the_current_tags_have_the_parts():
    assert check(tags=None, tags_now=TAGS) == ("tagged_after_close", ["E2", "E3"], {})
    assert check(tags=dict(TAGS, poi=None), tags_now=TAGS) == ("tagged_after_close", ["E3"], {})
    # the current tags still miss a part: not tagged
    assert check(tags=None, tags_now=dict(TAGS, poi=None)) == ("not_tagged", ["E2", "E3"], {})
    assert check(tags=None, tags_now=None) == ("not_tagged", ["E2", "E3"], {})


def test_tags_come_before_a_rule_fail():
    t = trade(open_snapshot=snap(**{"1d": "below"}))
    assert check(t, tags=None) == ("not_tagged", ["E2", "E3"], {})
    assert check(t)[0] == "rule_fail"


def test_a_tag_is_required_only_while_its_rule_was_enforced_at_the_open():
    s = {"status": [flip("E3", "tracking", T0 - DAY)]}
    assert check(tags=dict(TAGS, poi=None), settings=s) == (None, [], {})
    # flipped after the trade opened: still enforced for this trade
    s_late = {"status": [flip("E3", "tracking", T0 + MIN)]}
    assert check(tags=dict(TAGS, poi=None), settings=s_late) == ("not_tagged", ["E3"], {})


def test_a_retag_after_close_cannot_rescue_a_failed_retest():
    # Retest saved before the close, nothing touching: E2 fails. A Breakout saved later is ignored.
    t = trade(open_snapshot=snap(**{"15m": "above"}))
    brk = dict(TAGS, setup="breakout", break_what={"kind": "trendline", "timeframe": "4h"})
    assert check(t, tags=TAGS, tags_now=brk) == ("rule_fail", ["E2"], {})


# ── rule fails ───────────────────────────────────────────────────────────

def test_enforced_fails_block_in_registry_order():
    t = trade(open_snapshot=snap(**{"1d": "below"}),
              stop={"px": "95", "source": "hl_order", "set_at": _iso(T0 + 30 * MIN)})
    assert check(t) == ("rule_fail", ["E1", "R1"], {})


def test_a_fail_on_a_rule_tracking_at_the_open_does_not_block():
    t = trade(open_snapshot=snap(**{"1d": "below"}))
    assert check(t, settings={"status": [flip("E1", "tracking", T0 - DAY)]}) == (None, [], {})
    assert check(t, settings={"status": [flip("E1", "tracking", T0 + MIN)]}) == ("rule_fail", ["E1"], {})


def test_r2_over_the_limit_fails():
    t = trade(size_peak="200")                         # 1R $1,000 = 2% of $50k
    assert check(t) == ("rule_fail", ["R2"], {})


def test_a_revised_exit_without_a_reason_fails_until_one_is_picked():
    recs = RECORDS[:2] + [rec(2, 110, T0 + 2 * MIN, "Take Profit Market"),
                          rec(2, 110, T0 + 2 * MIN, "Take Profit Market", status="canceled", status_ts=CLOSE - 1000)]
    hand = [dict(FILLS[0], oid=7)]
    recs = recs + [{"status": "filled", "statusTimestamp": CLOSE,
                    "order": {"coin": "ETH", "side": "A", "oid": 7, "timestamp": CLOSE, "triggerPx": "0",
                              "isTrigger": False, "reduceOnly": True, "isPositionTpsl": False,
                              "orderType": "Market", "children": []}}]
    o = orders(recs, hand)
    assert check(o=o) == ("rule_fail", ["X1"], {})
    picked = trade(annotation=dict(trade()["annotation"], exit_reason="time_stop"))
    assert check(picked, o=o) == (None, [], {})


# ── no take-profit ───────────────────────────────────────────────────────

def test_no_take_profit_is_no_plan():
    t = trade(planned_target=None)
    o = orders(RECORDS[:2], [dict(FILLS[0], oid=1)])   # closed by the stop, no take-profit order
    assert check(t, o=o) == ("no_plan", ["R3", "M1"], {})


def test_no_plan_blocks_only_while_r3_or_m1_was_enforced_at_the_open():
    t = trade(planned_target=None)
    o = orders(RECORDS[:2], [dict(FILLS[0], oid=1)])
    s = {"status": [flip("R3", "tracking", T0 - DAY)]}
    assert check(t, o=o, settings=s) == ("no_plan", ["M1"], {})
    s2 = {"status": [flip("R3", "tracking", T0 - DAY), flip("M1", "tracking", T0 - DAY)]}
    assert check(t, o=o, settings=s2) == (None, [], {})


def test_a_rule_fail_comes_before_no_plan():
    t = trade(planned_target=None, open_snapshot=snap(**{"1w": "below"}))
    o = orders(RECORDS[:2], [dict(FILLS[0], oid=1)])
    assert check(t, o=o) == ("rule_fail", ["E1"], {})


# ── not checkable ────────────────────────────────────────────────────────

def test_a_missing_trend_snapshot_is_unchecked_with_its_reason():
    t = trade(open_snapshot=None)
    assert check(t) == ("unchecked", ["E1", "E2"], {"E1": "not_captured", "E2": "not_captured"})
    t2 = trade(open_snapshot=snap(reason="not_on_hyperliquid"))
    assert check(t2) == ("unchecked", ["E1", "E2"], {"E1": "not_on_hyperliquid", "E2": "not_on_hyperliquid"})


def test_negligible_size_is_unchecked():
    t = trade(size_peak="0.5")                         # 1R $2.50
    assert check(t) == ("unchecked", ["R2"], {"R2": "negligible_size"})


def test_a_closing_order_not_in_the_history_is_unchecked():
    assert check(o=orders(RECORDS, [])) == ("unchecked", ["X1"], {"X1": "closing_order_unknown"})


def test_a_manual_trade_is_unchecked():
    t = trade(source="manual", planned_target={"prices": ["110"], "source": "manual_log", "set_at": None,
                                               "moved_to": None, "moved_at": None})
    assert check(t, o=None) == ("unchecked", ["M1", "M2", "X1"],
                                {"M1": "manual", "M2": "manual", "X1": "manual"})


def test_no_plan_comes_before_unchecked():
    t = trade(planned_target=None, open_snapshot=None)
    o = orders(RECORDS[:2], [dict(FILLS[0], oid=1)])
    assert check(t, o=o) == ("no_plan", ["R3", "M1"], {})


def test_a_tracking_rule_that_cannot_be_measured_never_blocks():
    # R4 is tracking by default; leverage is null on a closed trade, so it is not measurable
    ev = evaluate()
    r4 = next(r for r in ev["rules"] if r["rule"] == "R4")
    assert r4["status"] == "tracking" and r4["verdict"] == "not_measurable"
    assert pr.gate_check(ev, TAGS) == (None, [], {})


def test_every_reason_returned_is_listed():
    seen = {check(tags=None)[0], check(tags=None, tags_now=TAGS)[0],
            check(trade(open_snapshot=snap(**{"1d": "below"})))[0],
            check(trade(planned_target=None), o=orders(RECORDS[:2], [dict(FILLS[0], oid=1)]))[0],
            check(trade(open_snapshot=None))[0]}
    assert seen == set(pr.GATE_REASONS)
