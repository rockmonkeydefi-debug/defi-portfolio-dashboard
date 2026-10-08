"""Landing 17 (HANDOFF_advisor_v1.md section 37): the Perps page labels every
reason perp_rules.gate_check can return (static/perps.js PRP_GATE_SHORT /
PRP_GATE_LONG), adds the rule ids to the long label (prpGateRules), re-reads
the trades after a tag save and a Rules-tab save, and the Risk gate card and
the Dashboard tile describe the rule check.

Reads the source files only; no app or database.
"""
import os
import re

from src.engines import perp_rules as pr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _js_keys(src, name):
    m = re.search(r"const " + name + r" = \{(.*?)\n\};", src, re.S)
    assert m, name + " not found"
    return set(re.findall(r"(?:^|[\s,{])(\w+):", m.group(1)))


def _js_object_keys(src, name):
    m = re.search(r"const " + name + r" = \{(.*?)\};", src, re.S)
    assert m, name + " not found"
    return set(re.findall(r"(?:^|[\s,{])(\w+):", m.group(1)))


def _function(src, name):
    start = src.index("function " + name + "(")
    end = src.index("\n  }\n", start)
    return src[start:end]


def test_every_rule_check_reason_has_both_labels():
    src = _read("static/perps.js")
    assert set(pr.GATE_REASONS) <= _js_keys(src, "PRP_GATE_SHORT")
    assert set(pr.GATE_REASONS) <= _js_keys(src, "PRP_GATE_LONG")


def test_the_rule_ids_follow_the_long_label():
    src = _read("static/perps.js")
    assert src.count("prpGateLong(g.reason, gateCountFrom) + prpGateRules(g)") == 2   # the Gate cell and the Gate fact
    assert "function prpGateRules(g)" in src
    assert _js_object_keys(src, "PRP_GATE_TAG_PART") == set(pr.GATE_TAG_RULES)
    for reason in pr.GATE_REASONS:
        assert "'" + reason + "'" in src[src.index("function prpGateRules(g)"):]


def test_tag_and_rules_tab_saves_reread_the_trades():
    src = _read("static/perps.js")
    body = _function(src, "onTagSaved")
    assert "load();" in body and "loadRules();" in body
    assert "onChanged={onSavedAll}" in src
    assert re.search(r"function onSavedAll\(\) \{ load\(\); loadRules\(\); \}", src)


def test_the_card_and_the_tile_describe_the_rule_check():
    assert "pass the rule check" in _read("static/perps.js")
    assert "passing the rule check" in _read("static/dashboard.js")
