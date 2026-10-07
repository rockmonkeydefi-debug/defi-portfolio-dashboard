"""Advisor v1, Landing 16: the Rules tab's risk-limits editor
(static/perpsrules.js, PerpsRiskLimitsEditor). These tests read the page
source: the editor is wired into the tab with the page's risk gate, calls a
route that exists, takes its bounds from the settings (not copies of the
server's numbers), and the capital line and history use the stored limits.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import os
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


def editor_src():
    src = read("perpsrules.js")
    return src[src.index("function PerpsRiskLimitsEditor("):src.index("function PerpsSettingsHistory(")]


def test_the_editor_is_wired_with_the_gate():
    assert "gate={data.summary.gate || null} />" in read("perps.js")
    src = read("perpsrules.js")
    assert "function PerpsRulesTab({ advisor, hide, onChanged, gate })" in src
    assert "<PerpsRiskLimitsEditor view={view} gate={gate} hide={hide} onSaved={onSaved} />" in src


def test_the_route_the_editor_calls_exists():
    rules = {r.rule for r in wp.app.url_map.iter_rules()}
    assert "/api/trading/advisor/perps/risk-limits" in rules
    assert "api('/api/trading/advisor/perps/risk-limits', { method: 'PUT'," in editor_src()
    assert "per_trade_pct: per.bps / 100, total_pct: tot.bps / 100" in editor_src()


def test_bounds_come_from_the_settings():
    body = editor_src()
    assert "view.risk_bounds ||" in body and "bounds.per_trade_max_bps" in body and "bounds.locked_max_bps" in body
    # the fallback bounds match the server's, for a settings response without them
    fallback = "{ min_bps: %d, per_trade_max_bps: %d, total_max_bps: %d, locked_max_bps: %d }" % (
        pr.RISK_MIN_BPS, pr.RISK_PER_TRADE_MAX_BPS, pr.RISK_TOTAL_MAX_BPS, pr.RISK_DEFAULT["per_trade_bps"])
    assert fallback in body


def test_saves_are_guarded_and_the_gate_is_checked_before_sending():
    body = editor_src()
    assert "if (!resp) return null;" in body                         # 401: api() returns undefined
    assert "per.bps > gateFree && !unlocked" in body
    assert "raising && !reason.trim()" in body


def test_capital_line_and_history_use_the_stored_limits():
    src = read("perpsrules.js")
    capital = src[src.index("function PerpsCapitalEditor("):src.index("function PerpsRiskLimitsEditor(")]
    assert "const lim = prpRiskNow(view);" in capital and "PRP_RISK_PER_TRADE_PCT" not in capital
    history = src[src.index("function PerpsSettingsHistory("):src.index("function PerpsRulesTab(")]
    assert "view.risk_changes" in history
