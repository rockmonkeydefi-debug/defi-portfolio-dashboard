"""Advisor v1, Landing 8c-3: the Perps page's Rules tab (static/perpsrules.js,
PerpsRulesTab) mirrors server limits and calls the 8b-2 routes. These tests
read the page source: the mirrored constants must equal the server's, the tab
must be wired into the Perps page, and every route the tab calls must exist.

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


def js_int(src, name):
    m = re.search(r"^const " + name + r" = (\d+);", src, re.M)
    assert m, name
    return int(m.group(1))


def test_mirrored_limits_match_the_server():
    src = read("perpsrules.js")
    assert js_int(src, "PRP_RULE_REASON_MAX") == wp.PERP_RULE_REASON_MAX
    assert js_int(src, "PRP_CAPITAL_MAX_USD") == wp.PERP_CAPITAL_MAX_USD
    assert js_int(src, "PRP_CAPITAL_MAX_AHEAD_DAYS") == wp.PERP_CAPITAL_MAX_AHEAD_DAYS
    assert js_int(src, "PRP_RISK_PER_TRADE_PCT") == pr.RISK_PER_TRADE_PCT
    assert js_int(src, "PRP_RISK_TOTAL_PCT") == pr.RISK_TOTAL_PCT


def test_the_tab_is_wired_into_the_perps_page():
    page = read("perps.js")
    tabs = re.search(r"const PRP_TABS = \[(.*?)\];", page, re.S)
    assert tabs and re.findall(r"id: '([a-z]+)'", tabs.group(1)) == ["open", "history", "transactions", "rules"]
    assert "<PerpsRulesTab advisor={advisor} hide={hideValues} onChanged={loadRules} gate={data.summary.gate || null} />" in page   # gate: Landing 16
    assert "function PerpsRulesTab(" in read("perpsrules.js")


def test_every_route_the_tab_calls_exists():
    src = read("perpsrules.js")
    rules = {r.rule for r in wp.app.url_map.iter_rules()}
    calls = {
        "/api/trading/advisor/perps/settings": "'/api/trading/advisor/perps/settings'",
        "/api/trading/advisor/perps/rules/<rule_id>/status": "'/api/trading/advisor/perps/rules/' + encodeURIComponent(rule.id) + '/status'",
        "/api/trading/advisor/perps/capital": "'/api/trading/advisor/perps/capital'",
    }
    for route, call in calls.items():
        assert route in rules, route
        assert call in src, call


def test_tally_lists_every_rule_with_fails():
    src = read("perpsrules.js")
    body = src[src.index("function prpRulesTally("):src.index("function prpExitReasonLabel(")]
    assert "const ids = ((advisor && advisor.rules) || []).map(r => r.id);" in body
    assert "r.status === 'enforced'" not in body
