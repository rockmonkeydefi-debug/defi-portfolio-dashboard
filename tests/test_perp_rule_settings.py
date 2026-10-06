"""Advisor v1, Landing 8b-2: rule status changes and dated capital in the pure
evaluator (src/engines/perp_rules.py) - forward-only status (a change applies
to trades opened at or after it), R4 pass / fail only while enforced, M3
fixed, dated capital periods for R2, the notes, settings_view, and no state
kept between calls.

Hand-built trade dicts in the trades route's shape; made-up prices and sizes.
No DB, no network, no web_portfolio import."""
import copy
import re
from datetime import datetime, timezone

from src.engines import perp_rules as pr

MIN = 60000
HOUR = 3600000
DAY = 86400000
MONEY = re.compile(r"\$|of capital", re.I)


def ms(y, mo, d, h=0, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


def iso(t):
    return datetime.fromtimestamp(t / 1000, timezone.utc).isoformat()


T0 = ms(2026, 9, 20, 10)
NOW = ms(2026, 10, 6, 12)
ABOVE = {"trend": {"v": 1, "reason": None,
                   "timeframes": {tf: {"position": "above"} for tf in ("15m", "30m", "1h", "4h", "12h", "1d", "1w")}}}


def trade(tid="t1", opened=T0, closed=None, **kw):
    """A closed long by default: entry 100, stop 95 set 2 min in, size 10 (1R 50)."""
    closed = opened + DAY if closed is None else closed
    t = {"trade_id": tid, "market": "perp", "source": "hyperliquid", "status": "closed" if closed else "open",
         "direction": "long", "symbol": "ETH", "opened_at": iso(opened) if opened is not None else None,
         "closed_at": iso(closed) if closed else None, "avg_entry": "100", "size_peak": "10",
         "stop": {"px": "95", "source": "hl_order", "set_at": iso((opened or T0) + 2 * MIN)},
         "planned_target": None, "leverage": None, "net_pnl": "10",
         "annotation": {"followed_rules": True, "notes": None, "deviation_note": None},
         "open_snapshot": copy.deepcopy(ABOVE)}
    t.update(kw)
    return t


NO_STOP = {}


def status_row(rule, status, at, reason=None):
    return {"rule": rule, "status": status, "from": iso(at), "reason": reason, "set_at": iso(at)}


def cap_row(frm, usd, set_at):
    return {"from": frm, "usd": usd, "set_at": iso(set_at)}


def by_rule(res):
    return {r["rule"]: r for r in res["rules"]}


def one(t, settings=None, now=NOW, all_trades=None):
    return pr.evaluate_trade(t, None, all_trades or [t], now_ms=now, settings=settings)


# ── constants and the default path ───────────────────────────────────────

def test_flippable_and_status_constants():
    assert pr.RULE_IDS == ("E1", "E2", "E3", "R1", "R2", "R3", "R4", "M1", "M2", "M3", "X1", "X2")
    assert pr.FLIPPABLE == tuple(i for i in pr.RULE_IDS if i != "M3")
    assert pr.RULE_STATUSES == ("enforced", "tracking")


def test_no_settings_is_the_default():
    t = trade(stop=NO_STOP)
    runs = [one(t, s) for s in (None, {}, {"status": [], "capital": []})]
    assert runs[0] == runs[1] == runs[2]
    for r in runs[0]["rules"]:
        assert r["status"] == pr._STATUS[r["rule"]] and "notes" not in r
    out = pr.evaluate_all([t], {}, now_ms=NOW)
    assert out["capital"] == {"usd": 50000, "from": "2026-09-13"}
    assert out["rules"] == [dict(r) for r in pr.RULES]
    assert set(out) == {"definition_version", "capital", "rules", "trades", "tally", "note"}
    view = pr.settings_view(None, NOW)
    assert [(r["id"], r["status"], r["default_status"], r["status_since"], r["status_reason"], r["flippable"])
            for r in view["rules"]] == [(r["id"], r["status"], r["status"], None, None, r["id"] != "M3")
                                        for r in pr.RULES]
    assert view["capital"] == {"usd": 50000, "from": "2026-09-13"}
    assert view["capital_periods"] == [{"from": "2026-09-13", "usd": 50000, "set_at": None}]
    assert view["capital_start"] == "2026-09-13"
    assert view["status_changes"] == [] and view["capital_changes"] == [] and view["settings_changed_at"] is None


# ── status changes: forward only ─────────────────────────────────────────

def test_status_change_is_forward_only():
    s = {"status": [status_row("R1", "tracking", T0 + DAY, "testing the flip")]}
    a = trade("a", T0, stop=NO_STOP)                    # opened before the change
    b = trade("b", T0 + 2 * DAY, stop=NO_STOP)          # opened after it
    out = pr.evaluate_all([a, b], {}, now_ms=NOW, settings=s)
    ra, rb = by_rule(out["trades"]["a"]), by_rule(out["trades"]["b"])
    assert ra["R1"]["status"] == "enforced" and ra["R1"]["verdict"] == "fail"
    assert out["trades"]["a"]["enforced_fails"] == ["R1"]
    assert ra["R1"]["notes"] == ["enforced when this trade opened; tracking since 2026-09-21 10:00 UTC"]
    assert ra["X2"]["evidence"].endswith("Rules v2: 1 enforced fail")
    assert rb["R1"]["status"] == "tracking" and rb["R1"]["verdict"] == "fail" and "notes" not in rb["R1"]
    assert out["trades"]["b"]["enforced_fails"] == []
    assert "R1" in {x["rule"] for x in out["trades"]["b"]["tracking"]}
    assert rb["X2"]["evidence"].endswith("Rules v2: 0 enforced fails")
    reg = {r["id"]: r for r in out["rules"]}
    assert reg["R1"]["status"] == "tracking" and reg["E1"]["status"] == "enforced"
    assert set(reg["R1"]) == set(pr.RULES[0])          # the registry keeps its shape
    assert out["tally"]["closed_with_enforced_fails"] == 1 and out["tally"]["closed_without_enforced_fails"] == 1


def test_change_at_the_open_time_applies():
    s = {"status": [status_row("R1", "tracking", T0)]}
    assert by_rule(one(trade(opened=T0, stop=NO_STOP), s))["R1"]["status"] == "tracking"
    assert by_rule(one(trade(opened=T0 - 1, stop=NO_STOP), s))["R1"]["status"] == "enforced"


def test_back_and_forth():
    s = {"status": [status_row("R1", "tracking", T0 + DAY, "trial"), status_row("R1", "enforced", T0 + 3 * DAY)]}
    d0, d2, d4 = (trade(f"d{i}", T0 + i * DAY, stop=NO_STOP) for i in (0, 2, 4))
    out = pr.evaluate_all([d0, d2, d4], {}, now_ms=NOW, settings=s)
    r0, r2, r4 = (by_rule(out["trades"][k]) for k in ("d0", "d2", "d4"))
    assert r0["R1"]["status"] == "enforced" and "notes" not in r0["R1"]
    assert r2["R1"]["status"] == "tracking"
    assert r2["R1"]["notes"] == ["tracking when this trade opened; enforced since 2026-09-23 10:00 UTC"]
    assert r4["R1"]["status"] == "enforced" and "notes" not in r4["R1"]
    view = {r["id"]: r for r in pr.settings_view(s, NOW)["rules"]}
    assert view["R1"]["status"] == "enforced" and view["R1"]["status_since"] == iso(T0 + 3 * DAY)
    assert view["R1"]["status_reason"] is None


def test_x2_and_the_tally_follow_the_status_at_the_open():
    s = {"status": [status_row("X2", "tracking", T0 - DAY)]}
    t = trade(annotation={"followed_rules": None, "notes": None, "deviation_note": None})
    res = one(t, s)
    x2 = by_rule(res)["X2"]
    assert x2["status"] == "tracking" and x2["verdict"] == "fail" and res["enforced_fails"] == []
    out = pr.evaluate_all([t], {}, now_ms=NOW, settings=s)
    assert out["tally"]["closed_without_enforced_fails"] == 1


def test_open_time_unknown_uses_the_status_now():
    s = {"status": [status_row("R1", "tracking", T0)]}
    r = by_rule(one(trade(opened=None, closed=T0 + DAY, stop=NO_STOP), s))
    assert r["R1"]["status"] == "tracking" and "notes" not in r["R1"]
    assert r["R2"]["reason"] == "no_stop"


def test_a_change_after_now_is_not_in_force_yet():
    s = {"status": [status_row("R1", "tracking", NOW + DAY)]}
    t = trade("late", NOW + 2 * DAY, closed=0, stop=NO_STOP)          # opened after both (a test-only clock)
    r = by_rule(one(t, s))
    assert r["R1"]["status"] == "tracking" and r["R1"]["notes"] == ["tracking when this trade opened; enforced now"]
    assert {x["id"]: x["status"] for x in pr.settings_view(s, NOW)["rules"]}["R1"] == "enforced"


# ── R4 and M3 ────────────────────────────────────────────────────────────

def test_r4_gives_pass_or_fail_only_while_enforced():
    far = trade(leverage="50", stop={"px": "80", "source": "hl_order", "set_at": iso(T0 + 2 * MIN)})
    near = trade(leverage="50", stop={"px": "99.5", "source": "hl_order", "set_at": iso(T0 + 2 * MIN)})
    plain = by_rule(one(far))["R4"]                                     # default: tracking, outcome in the text
    assert plain["verdict"] == "tracking" and plain["evidence"].endswith(": fail")
    s = {"status": [status_row("R4", "enforced", T0 - DAY)]}
    res = one(far, s)
    r4 = by_rule(res)["R4"]
    assert r4["status"] == "enforced" and r4["verdict"] == "fail" and "R4" in res["enforced_fails"]
    assert r4["evidence"] == "stop 20.00% from entry, limit 1.00% at 50x"
    assert by_rule(one(near, s))["R4"]["verdict"] == "pass"
    assert by_rule(one(trade(), s))["R4"]["verdict"] == "not_measurable"      # no leverage on a closed trade


def test_m3_unknown_and_bad_rows_are_ignored():
    t = trade(stop=NO_STOP)
    bad = {"status": [status_row("M3", "enforced", T0 - DAY), status_row("Z9", "tracking", T0 - DAY),
                      status_row("E1", "off", T0 - DAY), dict(status_row("E1", "tracking", T0), **{"from": "yesterday"}),
                      dict(status_row("R1", "tracking", T0), **{"from": None}), "R1 tracking", None]}
    assert one(t, bad) == one(t)
    assert pr.settings_view(bad, NOW)["rules"] == pr.settings_view(None, NOW)["rules"]
    assert pr.status_at("M3", T0, bad) == "tracking" and pr.status_at("E1", T0, bad) == "enforced"


# ── dated capital ────────────────────────────────────────────────────────

def test_capital_periods_latest_row_per_date_and_removal():
    s1, s2, s3, s4 = (NOW + i * MIN for i in range(4))
    rows = [cap_row("2026-10-01", 60000, s1), cap_row("2026-10-01", 70000, s2),
            cap_row("2026-10-05", 80000, s3), cap_row("2026-10-05", None, s4),
            cap_row("2026-09-01", 90000, s1),                                    # before the rule start
            cap_row("2026-10-09", None, s1),                                     # removes nothing
            cap_row("2026-10-02", 0, s1), cap_row("2026-10-02", -5, s1), cap_row("2026-10-02", True, s1),
            cap_row("2026-10-02", "60000", s1), cap_row("2026-10-02", 1.5, s1),
            cap_row("2026-9-1", 60000, s1), cap_row("2026-10-1x", 60000, s1), cap_row(None, 60000, s1)]
    assert pr.capital_periods({"capital": rows}) == [
        {"from": "2026-09-13", "usd": 50000, "set_at": None},
        {"from": "2026-10-01", "usd": 70000, "set_at": iso(s2)}]
    rows += [cap_row("2026-09-13", 55000, s3)]
    assert pr.capital_periods({"capital": rows})[0] == {"from": "2026-09-13", "usd": 55000, "set_at": iso(s3)}
    rows += [cap_row("2026-09-13", None, s4)]
    assert pr.capital_periods({"capital": rows})[0] == {"from": "2026-09-13", "usd": 50000, "set_at": None}


def test_capital_at():
    s = {"capital": [cap_row("2026-10-01", 70000, NOW)]}
    assert pr.capital_at(ms(2026, 9, 12, 23, 59), s) is None
    assert pr.capital_at(ms(2026, 9, 13), s)["usd"] == 50000
    assert pr.capital_at(ms(2026, 10, 1) - 1, s)["usd"] == 50000
    assert pr.capital_at(ms(2026, 10, 1), s)["usd"] == 70000


def test_r2_measures_against_the_capital_at_the_open():
    big = dict(size_peak="120")                                          # 1R = 600
    default = by_rule(one(trade(**big)))["R2"]
    assert default["verdict"] == "fail" and "(1.20% of capital)" in default["evidence"]
    s = {"capital": [cap_row("2026-09-13", 100000, T0 - DAY), cap_row("2026-10-01", 40000, T0 - DAY)]}
    sept = by_rule(one(trade(**big), s))["R2"]
    assert sept["verdict"] == "pass" and "(0.60% of capital)" in sept["evidence"] and "notes" not in sept
    octo = by_rule(one(trade("oct", ms(2026, 10, 2, 9), **big), s))["R2"]
    assert octo["verdict"] == "fail" and "(1.50% of capital)" in octo["evidence"]


def test_r2_total_limit_uses_the_same_capital():
    s = {"capital": [cap_row("2026-09-13", 60000, T0 - DAY)]}
    trades = [trade(f"o{i}", T0 + i * HOUR, closed=0, size_peak="120") for i in range(6)]   # six open, 1R 600 each
    out = pr.evaluate_all(trades, {}, now_ms=NOW, settings=s)
    fifth, sixth = by_rule(out["trades"]["o4"])["R2"], by_rule(out["trades"]["o5"])["R2"]
    assert fifth["verdict"] == "pass" and "(5.00%)" in fifth["evidence"]
    assert sixth["verdict"] == "fail" and sixth["evidence"].startswith("over 5% open in total")


def test_r2_note_when_the_capital_entry_was_made_after_the_open():
    s = {"capital": [cap_row("2026-09-13", 100000, ms(2026, 10, 6, 9, 30))]}
    before = by_rule(one(trade(), s))["R2"]
    assert before["notes"] == ["capital entry for 2026-09-13 made 2026-10-06 09:30 UTC, after the trade opened"]
    after = by_rule(one(trade("new", ms(2026, 10, 6, 10)), s))["R2"]
    assert "notes" not in after


def test_capital_now_and_settings_changed_at():
    s = {"capital": [cap_row("2026-10-10", 75000, NOW)],
         "status": [status_row("E3", "tracking", NOW - HOUR, "tagging habit not formed")]}
    assert pr.evaluate_all([], {}, now_ms=NOW, settings=s)["capital"] == {"usd": 50000, "from": "2026-09-13"}
    later = ms(2026, 10, 11)
    assert pr.evaluate_all([], {}, now_ms=later, settings=s)["capital"] == {"usd": 75000, "from": "2026-10-10"}
    view = pr.settings_view(s, NOW)
    assert [p["from"] for p in view["capital_periods"]] == ["2026-09-13", "2026-10-10"]
    assert view["settings_changed_at"] == iso(NOW)
    assert view["status_changes"] == [{"rule": "E3", "status": "tracking", "from": iso(NOW - HOUR),
                                       "reason": "tagging habit not formed"}]
    assert view["capital_changes"] == [{"from": "2026-10-10", "usd": 75000, "set_at": iso(NOW)}]
    assert {r["id"]: r["status_reason"] for r in view["rules"]}["E3"] == "tagging habit not formed"


# ── what reaches the page, and no state between calls ────────────────────

def test_notes_and_reasons_carry_no_dollar_amounts():
    s = {"status": [status_row(rid, "tracking", T0 + HOUR, "why") for rid in pr.FLIPPABLE],
         "capital": [cap_row("2026-09-13", 100000, NOW)]}
    out = pr.evaluate_all([trade(size_peak="120"), trade("x", T0 + DAY, stop=NO_STOP)], {}, now_ms=NOW, settings=s)
    seen = 0
    for ev in out["trades"].values():
        for r in ev["rules"]:
            for note in r.get("notes") or []:
                seen += 1
                assert not MONEY.search(note), (r["rule"], note)
            assert not MONEY.search(str(r["reason"] or ""))
            if r["rule"] != "R2":
                assert not MONEY.search(r["evidence"]), (r["rule"], r["evidence"])
    assert seen == 11            # ten status notes on the first trade (R4 was tracking already) + its R2 capital note
    for r in out["rules"]:
        assert "$" not in r["definition"] and "$" not in r["title"]


def test_nothing_is_kept_between_calls():
    rules_before, status_before = copy.deepcopy(pr.RULES), dict(pr._STATUS)
    t = trade(stop=NO_STOP)
    plain = one(t)
    s = {"status": [status_row(rid, "tracking" if pr._STATUS[rid] == "enforced" else "enforced", T0 - DAY, "x")
                    for rid in pr.FLIPPABLE],
         "capital": [cap_row("2026-09-13", 1000, T0 - DAY)]}
    flipped = one(t, s)
    assert flipped != plain and by_rule(flipped)["R1"]["status"] == "tracking"
    assert one(t) == plain
    assert pr.evaluate_all([t], {}, now_ms=NOW)["capital"] == {"usd": 50000, "from": "2026-09-13"}
    assert pr.RULES == rules_before and pr._STATUS == status_before
