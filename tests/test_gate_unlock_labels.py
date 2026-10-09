"""Landing 23 (HANDOFF_advisor_v1.md section 43): the pages show the risk
gate's three checks from the server (summary.gate "checks", "min_avg_r",
"recent_n", "recent_expectancy_r") instead of working them out, the Rules tab
says which check keeps the gate locked and what R2 does with a stored raise
meanwhile, and the Gate hover names R2's new not-measurable reason. These
tests read the page source.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import os
import re
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

from src.engines import perp_rules as pr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(ROOT, "static", name), encoding="utf-8") as f:
        return f.read()


def section(src, start, end):
    return src[src.index(start):src.index(end, src.index(start))]


def test_the_fields_the_pages_read_are_in_the_summary():
    view = wp._trades_gate_view([])
    for key in ("checks", "min_avg_r", "recent_n", "recent_expectancy_r", "expectancy_r", "eligible_count", "target",
                "unlocked"):
        assert key in view
    assert set(view["checks"]) == {"count", "average", "recent"}
    for name in ("perps.js", "dashboard.js", "perpsrules.js"):
        src = read(name)
        for key in ("checks", "min_avg_r", "recent_n", "recent_expectancy_r"):
            assert "gate." + key in src, (name, key)


def test_the_perps_card_uses_the_servers_checks():
    card = section(read("perps.js"), "<PerpsKpi label=\"Risk gate", "</PerpsKpi>")
    for c in ("count", "average", "recent"):
        assert "check(!!checks." + c + "," in card
    assert "exp > 0" not in card and "count >= target" not in card
    assert "'Last ' + recentN + ' average R '" in card
    assert "goes back to 1% as soon as either average fails" in card
    assert "R2 holds trades opened then to 1% per trade" in card


def test_the_dashboard_tile_uses_the_servers_checks():
    src = read("dashboard.js")
    tile = section(src, "tile('PERP RISK'", "</div>")
    for c in ("count", "average", "recent"):
        assert "check(!!checks." + c + "," in tile
    assert "exp > 0" not in tile and "count >= target" not in tile
    assert "goes back to 1% as soon as either average fails" in tile


def test_the_rules_tab_names_the_failing_check_and_a_stored_raise():
    src = read("perpsrules.js")
    why = section(src, "function prpGateLockedWhy(gate)", "\n}\n")
    assert "if (!c.count)" in why and "if (!c.average)" in why and "above 0R needed" in why
    editor = section(src, "function PerpsRiskLimitsEditor(", "function PerpsSettingsHistory(")
    assert "const raised = cur.per_trade_bps > bounds.locked_max_bps;" in editor
    assert "'R2 holds trades opened while it is locked to '" in editor
    assert "'% applies again once it unlocks.'" in editor
    # one definition across the plain scripts (they share the global scope)
    defs = sum(len(re.findall(r"function prpGateLockedWhy\(", read(n)))
               for n in os.listdir(os.path.join(ROOT, "static")) if n.endswith(".js"))
    assert defs == 1


def test_the_gate_hover_names_r2s_new_reason():
    src = read("perps.js")
    table = section(src, "const PRP_GATE_WHY = {", "};")
    assert "gate_not_recorded: 'risk gate at the open not recorded'" in table
    t = {"trade_id": "x", "market": "perp", "source": "hyperliquid", "status": "closed", "direction": "long",
         "opened_at": "2026-10-12T10:00:00+00:00", "closed_at": "2026-10-13T10:00:00+00:00", "avg_entry": "100",
         "size_peak": "150", "stop": {"px": "95", "set_at": "2026-10-12T10:02:00+00:00"}, "gate_at_open": None}
    s = {"risk": [{"per_trade_bps": 200, "total_bps": 500, "from": "2026-10-11T00:00:00+00:00", "reason": "x",
                   "set_at": "2026-10-11T00:00:00+00:00"}]}
    assert pr.rule_r2(t, [t], s)["reason"] == "gate_not_recorded"
