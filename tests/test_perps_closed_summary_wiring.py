"""Landing 76: the summary above the Perps Closed table, pinned as source text.
The new source stays ASCII: the middle dot and the dash come from
PRP_SUM_DOT and PRP_SUM_DASH (String.fromCharCode).

Glenn (Oct 30): the old block of tally lines was confusing. Now: three tiles
(clean, with a rule fail, checked), a rule table in registry order with each
rule's name, its enforced fails and a bar (tracking rules greyed, a dash unless
they had fails while enforced; E2 and E3 carry a sub-line), a "Hide details"
toggle remembered in the browser (open by default), a tags and revised-exits
card, and the after-exit ("had you held the plan") card drawn from counts.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _between(src, a, b):
    i = src.index(a)
    return src[i:src.index(b, i + len(a))]


def test_the_tally_counts_every_rules_verdicts():
    src = _read("static/perpsrules.js")
    body = _between(src, "function prpRulesTally(", "function prpExitReasonLabel(")
    assert "(ev.enforced_fails || []).forEach(id => { failBy[id] = (failBy[id] || 0) + 1; fails += 1; });" in body
    assert "v[x.verdict] = (v[x.verdict] || 0) + 1;" in body
    assert "const e2 = verdicts.E2 || {};" in body
    assert "failCount: failBy, fails, verdicts," in body


def test_the_rule_table_follows_the_registry_and_greys_tracking_rules():
    src = _read("static/perpsrules.js")
    table = _between(src, "function PerpsSumRules(", "function PerpsSumTags(")
    assert "(data.rules || []).forEach(reg => {" in table
    assert "rows.push(<PerpsSumRuleRow key={reg.id} reg={reg} t={t} />);" in table
    assert "'Rule check' + PRP_SUM_DOT + 'rules v' + data.definition_version" in table
    row = _between(src, "function PerpsSumRuleRow(", "function PerpsSumRules(")
    assert "const n = t.failCount[id] || 0;" in row
    assert "const tracking = reg.status === 'tracking';" in row
    assert "{tracking && !n ? PRP_SUM_DASH : n}" in row
    assert "{n ? 'tracking now' : 'tracking, not counted'}" in row
    assert "const pct = t.evaluated ? Math.min(100, n / t.evaluated * 100) : 0;" in row
    assert "sub = 'Also: ' + parts.join(PRP_SUM_DOT);" in row
    assert "sub = 'Not tagged ' + v.not_tagged + ' (not a fail)';" in row


def test_the_toggle_is_open_by_default_and_remembered():
    src = _read("static/perpsrules.js")
    assert "const PRP_SUM_RULES_KEY = 'perpsSummaryRules';" in src
    assert "const PRP_SUM_DOT = ' ' + String.fromCharCode(183) + ' ';" in src
    assert "const PRP_SUM_DASH = String.fromCharCode(8212);" in src
    table = _between(src, "function PerpsSumRules(", "function PerpsSumTags(")
    assert "usePRPState(() => prpReadLocal(PRP_SUM_RULES_KEY, 'open') !== 'hidden');" in table
    assert "prpWriteLocal(PRP_SUM_RULES_KEY, v ? 'open' : 'hidden');" in table
    assert "{open ? 'Hide details' : 'Show details'}" in table
    assert "{open && <table" in table


def test_the_tiles_and_the_fail_note():
    src = _read("static/perpsrules.js")
    top = _between(src, "function PerpsRulesTally(", "function prpTagDraft(")
    assert 'n={t.clean} label="clean" sub="no enforced rule fail"' in top
    assert 'n={t.evaluated - t.clean} label="with a rule fail" sub="at least one enforced fail"' in top
    assert "(t.total - t.evaluated) + ' not read yet' : 'of ' + t.total + ' closed in view'" in top
    assert "'Rules tally unavailable: ' + advisor.error + ' '" in top and "onClick={advisor.reload}>Retry</button>" in top
    table = _between(src, "function PerpsSumRules(", "function PerpsSumTags(")
    assert "+ (t.fails > withFail ? ': one trade can fail more than one rule.' : '.')" in table


def test_the_after_exit_card_reads_counts_from_perps_js():
    rules = _read("static/perpsrules.js")
    assert ("const PRP_SUM_HELD = [['target', 'Target first', 'var(--ok)'], ['stop', 'Stop first', 'var(--fail)'],"
            in rules)
    held = _between(rules, "function PerpsSumHeld(", "function PerpsRulesTally(")
    assert "PRP_SUM_HELD.filter(h => held[h[0]] || h[0] === 'target' || h[0] === 'stop')" in held
    assert "title={'Counts the closed trades in this view. ' + PRP_HELD_TIP}" in held
    perps = _read("static/perps.js")
    tally = _between(perps, "function prpHeldTally(rows) {", "/* ")
    assert "return c;" in tally and "Had you held the plan: " not in perps
    assert "<PerpsRulesTally rows={rows} advisor={advisor} tags={tags} held={held} />" in perps
    assert "const held = prpHeldTally(rows);" in perps


def test_the_old_lines_are_gone():
    src = _read("static/perpsrules.js")
    for old in ("'Enforced fails by rule: '", "'E2 setup check: '", "closed trades have no enforced fail"):
        assert old not in src, old


def test_the_layout_stacks_on_narrow_screens():
    css = _read("static/style.css")
    block = css[css.index("/* Landing 76:"):]
    assert ".prp-sum-grid { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(0, 1fr);" in block
    assert "@media (max-width: 1000px) { .prp-sum-grid { grid-template-columns: minmax(0, 1fr); } }" in block
    assert ".prp-sum-tile-sub, .prp-sum-bar { display: none; }" in block
