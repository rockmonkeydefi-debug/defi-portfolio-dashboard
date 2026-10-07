"""Landing 15: every reason _trades_gate_reason can return has a short and a
long label on the Perps page (static/perps.js PRP_GATE_SHORT / PRP_GATE_LONG),
and the Perps page and the Dashboard read summary.gate.count_from.

Reads the source files only; no app or database.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import inspect
import os
import re
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _js_keys(src, name):
    m = re.search(r"const " + name + r" = \{(.*?)\n\};", src, re.S)
    assert m, name + " not found"
    return set(re.findall(r"(?:^|[\s,{])(\w+):", m.group(1)))


def test_every_gate_reason_has_both_labels():
    reasons = set(re.findall(r'return "(\w+)"', inspect.getsource(wp._trades_gate_reason)))
    assert "before_gate_count" in reasons and "before_rule" in reasons
    src = _read("static/perps.js")
    assert reasons <= _js_keys(src, "PRP_GATE_SHORT")
    assert reasons <= _js_keys(src, "PRP_GATE_LONG")


def test_pages_read_count_from():
    perps = _read("static/perps.js")
    assert "data.summary.gate.count_from" in perps                    # PerpsScreen
    assert "gate.count_from ? prpDate(gate.count_from)" in perps       # the Risk gate card
    assert perps.count("gateCountFrom={gateCountFrom}") == 2          # into History, then each row
    assert "prpGateLong(g.reason, gateCountFrom)" in perps
    assert "gate.count_from" in _read("static/dashboard.js")           # the PERP RISK tile's hover text
