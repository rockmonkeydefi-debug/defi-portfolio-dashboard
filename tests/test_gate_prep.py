"""Landing 22 (HANDOFF_advisor_v1.md section 42): perp_rules.gate_prep, the
parts an open perp trade still needs before its close to count toward the
1% -> 2% risk gate (setup and POI tags, a take-profit).

Glenn, Oct 9 ("your recs"): flag an open trade that can still count while
it lacks something the gate will ask for at the close and that can still be
added while it is open. Each part is asked for only while its rule was
enforced when the trade opened, as gate_check judges it.

Pure: plain dicts, no database, no network. Made-up prices.
"""
import copy
import itertools

from src.engines import perp_rules as pr

OPEN = "2026-10-08T10:00:00+00:00"
NOW = pr._ms("2026-10-09T12:00:00+00:00")
RETEST = {"setup": "retest", "setup_tagged_at": "2026-10-08T10:05:00+00:00", "break_what": None,
          "poi": {"type": "order_block", "timeframe": "4h", "tagged_at": "2026-10-08T10:05:00+00:00"}}


def trade(planned=None, live="none", opened_at=OPEN):
    """An open ETH long. planned: planned take-profit prices (None = no plan
    recorded). live: "none" = no live read, else the live take-profit list
    (None = the venue's take-profit read failed)."""
    t = {"trade_id": "t1", "market": "perp", "source": "hyperliquid", "status": "open", "direction": "long",
         "opened_at": opened_at, "avg_entry": "100", "stop": {"px": "95"}, "size_peak": "2",
         "planned_target": ({"prices": planned, "source": "orders"} if planned is not None else None),
         "live": None if live == "none" else {"take_profits": live}}
    return t


def status_rows(*rows):
    """settings with status changes: (rule, status, from)."""
    return {"status": [{"rule": r, "status": s, "from": f, "reason": "test", "set_at": f} for r, s, f in rows]}


# ── the parts ────────────────────────────────────────────────────────────

def test_parts_constant():
    assert pr.GATE_PREP_PARTS == ("setup", "poi", "take_profit")


def test_untagged_without_a_take_profit_needs_everything():
    assert pr.gate_prep(trade(live=[]), None, None, NOW) == ["setup", "poi", "take_profit"]


def test_tagged_with_a_planned_take_profit_needs_nothing():
    assert pr.gate_prep(trade(planned=["110"], live=[]), RETEST, None, NOW) == []


def test_setup_only_and_poi_only():
    no_poi = dict(RETEST, poi=None)
    assert pr.gate_prep(trade(planned=["110"]), no_poi, None, NOW) == ["poi"]
    no_setup = dict(RETEST, setup=None, setup_tagged_at=None)
    assert pr.gate_prep(trade(planned=["110"]), no_setup, None, NOW) == ["setup"]


def test_breakout_needs_what_broke():
    bo = dict(RETEST, setup="breakout", break_what=None)
    assert pr.gate_prep(trade(planned=["110"]), bo, None, NOW) == ["setup"]
    bo_ok = dict(bo, break_what={"kind": "trendline", "timeframe": "4h"})
    assert pr.gate_prep(trade(planned=["110"]), bo_ok, None, NOW) == []
    other = dict(RETEST, setup="other")
    assert pr.gate_prep(trade(planned=["110"]), other, None, NOW) == []
    unknown = dict(RETEST, setup="scalp")
    assert pr.gate_prep(trade(planned=["110"]), unknown, None, NOW) == ["setup"]


# ── the take-profit: missing only when known ─────────────────────────────

def test_take_profit_unknown_is_not_missing():
    assert pr.gate_prep(trade(live="none"), RETEST, None, NOW) == []          # no live read
    assert pr.gate_prep(trade(live=None), RETEST, None, NOW) == []            # the venue's read failed
    t = trade()
    t["live"] = {"take_profits": "x"}
    assert pr.gate_prep(t, RETEST, None, NOW) == []
    t["live"] = "x"
    assert pr.gate_prep(t, RETEST, None, NOW) == []
    t["live"] = {"take_profits": [], "stale": True}                          # the last venue read failed
    assert pr.gate_prep(t, RETEST, None, NOW) == []
    t["live"] = {"take_profits": [], "stale": False}
    assert pr.gate_prep(t, RETEST, None, NOW) == ["take_profit"]


def test_take_profit_present_live_or_planned():
    assert pr.gate_prep(trade(live=["110"]), RETEST, None, NOW) == []
    assert pr.gate_prep(trade(planned=["110"], live=[]), RETEST, None, NOW) == []
    assert pr.gate_prep(trade(planned=["110"], live="none"), RETEST, None, NOW) == []


def test_take_profit_unreadable_prices_do_not_count():
    assert pr.gate_prep(trade(planned=["", None, "abc"], live=[]), RETEST, None, NOW) == ["take_profit"]
    assert pr.gate_prep(trade(planned=[], live=["", "nan"]), RETEST, None, NOW) == ["take_profit"]
    assert pr.gate_prep(trade(live=[]), RETEST, None, NOW) == ["take_profit"]


# ── statuses when the trade opened (forward only) ────────────────────────

def test_a_rule_tracking_before_the_open_drops_its_part():
    before = "2026-10-07T00:00:00+00:00"
    s = status_rows(("E2", "tracking", before))
    assert pr.gate_prep(trade(live=[]), None, s, NOW) == ["poi", "take_profit"]
    s = status_rows(("E3", "tracking", before))
    assert pr.gate_prep(trade(live=[]), None, s, NOW) == ["setup", "take_profit"]


def test_a_change_after_the_open_does_not_apply():
    after = "2026-10-08T12:00:00+00:00"
    s = status_rows(("E2", "tracking", after), ("E3", "tracking", after), ("R3", "tracking", after),
                    ("M1", "tracking", after))
    assert pr.gate_prep(trade(live=[]), None, s, NOW) == ["setup", "poi", "take_profit"]


def test_take_profit_needs_r3_or_m1_enforced():
    before = "2026-10-07T00:00:00+00:00"
    only_r3 = status_rows(("R3", "tracking", before))
    assert pr.gate_prep(trade(live=[]), RETEST, only_r3, NOW) == ["take_profit"]      # M1 still enforced
    only_m1 = status_rows(("M1", "tracking", before))
    assert pr.gate_prep(trade(live=[]), RETEST, only_m1, NOW) == ["take_profit"]      # R3 still enforced
    both = status_rows(("R3", "tracking", before), ("M1", "tracking", before))
    assert pr.gate_prep(trade(live=[]), RETEST, both, NOW) == []


def test_unreadable_open_time_uses_the_statuses_now():
    s = status_rows(("E2", "tracking", "2026-10-09T00:00:00+00:00"))
    assert pr.gate_prep(trade(live=[], opened_at="not a date"), None, s, NOW) == ["poi", "take_profit"]
    assert pr.gate_prep(trade(live=[], opened_at=None), None, s, NOW) == ["poi", "take_profit"]


def test_pure_inputs_unchanged():
    t, tags = trade(planned=["110"], live=[]), copy.deepcopy(RETEST)
    s = status_rows(("E2", "tracking", "2026-10-07T00:00:00+00:00"))
    before = (copy.deepcopy(t), copy.deepcopy(tags), copy.deepcopy(s))
    pr.gate_prep(t, tags, s, NOW)
    assert (t, tags, s) == before


# ── agreement with the gate (gate_check at the close) ────────────────────

def test_tag_parts_agree_with_gate_check():
    """For every tag state and E2 / E3 status at the open, the tag parts
    gate_prep asks for are exactly the parts gate_check would find missing
    if the trade closed with those tags."""
    before = "2026-10-07T00:00:00+00:00"
    tag_states = [None, RETEST, dict(RETEST, poi=None), dict(RETEST, setup=None, setup_tagged_at=None),
                  dict(RETEST, setup="breakout", break_what=None)]
    part_rule = {"setup": "E2", "poi": "E3"}
    for tags, e2, e3 in itertools.product(tag_states, ("enforced", "tracking"), ("enforced", "tracking")):
        s = status_rows(("E2", e2, before), ("E3", e3, before))
        t = trade(planned=["110"], live=["110"])
        parts = [p for p in pr.gate_prep(t, tags, s, NOW) if p in part_rule]
        closed = dict(t, status="closed", closed_at="2026-10-08T15:00:00+00:00")
        ev = pr.evaluate_trade(closed, None, [closed], tags, NOW, s)
        reason, rules, _ = pr.gate_check(ev, tags, tags)
        missing = rules if reason in ("not_tagged", "tagged_after_close") else []
        assert [part_rule[p] for p in parts] == missing, (tags, e2, e3)


def test_no_take_profit_part_when_r3_reads_a_plan():
    """A planned take-profit (what R3 reads at the close) never leaves the part."""
    t = trade(planned=["110"], live=[])
    closed = dict(t, status="closed", closed_at="2026-10-08T15:00:00+00:00")
    assert pr.rule_r3(closed)["verdict"] != "no_plan"
    assert "take_profit" not in pr.gate_prep(t, RETEST, None, NOW)
