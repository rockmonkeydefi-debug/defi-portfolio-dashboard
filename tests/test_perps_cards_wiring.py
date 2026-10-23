"""Landing 61 (Oct 23, Glenn "A, A" twice): the expanded Perps rows as cards.

An expanded row on the Perps page shows its sections as cards, the Spot
page's look (window.SpotCard from static/spotplan.js, wrapped by PerpsCard in
static/perps.js):
- Open: Position, Plan, Notes, then the Rule check as a full-width card;
- Closed: Result, Plan, Review, Notes, then the Rule check.
From 1400px the cards sit in two columns (static/style.css .prp-detail-grid:
Open has Position and Notes on the left, Plan on the right; Closed has
Result and Notes on the left, Plan then Review on the right); below that they
stack in reading order. The Plan card reads Trends at Open (the noodle at the
open), Stop, Take-profit, then Setup and entry zone. Each card that saves has
its own saver, so its Saving / Saved / error line shows in that card. A
manual trade's stop shows in its Plan card; a synced closed trade no longer
repeats the stop's source above the Stop editor (the editor's line has it).

Browser checks (1920, 1250 and 390px, against main) are in the landing
record; these read the source files only.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL_BRACE = chr(10) + "}" + chr(10)     # the end of a CSS block


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    assert start in text, start
    rest = text.split(start, 1)[1]
    assert end in rest, end
    return rest.split(end, 1)[0]


def _cards(detail):
    """[(part, title, body)] for each PerpsCard in a row's detail, in order."""
    out = []
    for chunk in detail.split('<PerpsCard part="')[1:]:
        part = chunk.split('"', 1)[0]
        title = chunk.split('title="', 1)[1].split('"', 1)[0]
        out.append((part, title, chunk.split("</PerpsCard>", 1)[0].split('">', 1)[1]))
    return out


def _detail(js, fn, next_fn):
    body = _between(js, "function " + fn + "(", "function " + next_fn + "(")
    return body, _between(body, '<div className="spot-detail"', "</React.Fragment>;")


def _ordered(text, needles):
    pos = [text.find(n) for n in needles]
    assert all(p >= 0 for p in pos), [n for n, p in zip(needles, pos) if p < 0]
    return pos == sorted(pos)


def _token(css, name):
    m = re.search("--" + name + ":[ ]*(#[0-9a-fA-F]{6});", css)
    assert m, name
    return m.group(1)


def _lum(hex_color):
    h = hex_color.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def test_spotplan_loads_before_the_perps_files():
    html = _read("templates/index.html")
    assert _ordered(html, ["/static/spotplan.js", "/static/perps.js", "/static/perpsrules.js"])


def test_the_card_wrapper_uses_the_spot_card():
    js = _read("static/perps.js")
    card = _between(js, "function PerpsCard(", "function PerpsPlanPart(")
    assert "const Card = window.SpotCard;" in card
    assert "accent={PRP_CARD_EDGE[part]}" in card and "data-prp-card={part}" in card
    edges = _between(js, "const PRP_CARD_EDGE = {", "};")
    got = dict(re.findall("([a-z]+): '(var[(]--[a-z0-9]+[)])'", edges))
    assert got == {"position": "var(--text4)", "result": "var(--text4)", "plan": "var(--accent)", "review": "var(--ok)",
                   "notes": "var(--adapt)", "rules": "var(--text3)"}


def test_card_edges_are_visible_and_neighbours_differ():
    js = _read("static/perps.js")
    css = _read("static/style.css")
    edges = _between(js, "const PRP_CARD_EDGE = {", "};")
    tok = dict((k, v) for k, v in re.findall("([a-z]+): 'var[(]--([a-z0-9]+)[)]'", edges))
    bg = _token(css, "bg")
    for part, name in tok.items():
        assert _contrast(_token(css, name), bg) >= 3, part          # the 4px edge reads at a glance
    for a, b in (("position", "plan"), ("position", "notes"), ("notes", "plan"),
                 ("result", "plan"), ("result", "notes"), ("notes", "review"), ("plan", "review")):
        assert tok[a] != tok[b], (a, b)                              # cards side by side or stacked differ


def test_open_row_cards_in_order_with_their_contents():
    js = _read("static/perps.js")
    body, detail = _detail(js, "PerpsOpenRow", "PerpsUntrackedRow")
    assert '<div className="prp-detail-grid open">' in detail
    assert "flexWrap: 'wrap', gap: 28" not in detail
    cards = _cards(detail)
    assert [(p, t) for p, t, _ in cards] == [("position", "Position"), ("plan", "Plan"), ("notes", "Notes"),
                                             ("rules", "Rule check")]
    pos, plan, notes, rules = (c[2] for c in cards)
    assert _ordered(pos, ['label="Venue"', 'label="Opened"', 'label="Leverage"', 'label="Peak size"',
                          'label="Fees so far"', 'label="Funding so far"', 'label="1R at the stop"',
                          'label="Liquidation"', 'label="Live data"', "<PerpsManualClose trade={t} saver={saver} />",
                          "<PerpsManualDelete trade={t} saver={saver} />",
                          "<PerpsStatus saving={saver.saving} status={saver.status} />"])
    assert _ordered(plan, ["<PerpsTrendsAtOpen trade={t} />", '<PerpsPlanPart title="Stop">',
                           "<PerpsStopEditor trade={t} saver={planSaver} closed={false} />",
                           "<PerpsCorrectionFact trade={t} />", '<PerpsPlanPart title="Take-profit">',
                           "<PerpsPlanFact trade={t} model={plan} />", "<PerpsTagEditor trade={t} tag={tag} onSaved={onTagSaved} />",
                           "<PerpsStatus saving={planSaver.saving} status={planSaver.status} />"])
    assert _ordered(notes, ["<PerpsNotesEditor trade={t} saver={notesSaver} withDeviation={false} />",
                            "Followed or deviated is set once the trade closes",
                            "<PerpsStatus saving={notesSaver.saving} status={notesSaver.status} />"])
    assert rules.strip() == "<PerpsRuleCheck trade={t} advisor={advisor} hide={hide} inCard />"
    assert 'label="At open"' not in detail and "<PerpsAtOpen" not in detail   # the noodle moved into Trends at Open
    assert len(re.findall("prpUseSaver[(]t, onSaved[)]", body)) == 3


def test_closed_row_cards_in_order_with_their_contents():
    js = _read("static/perps.js")
    body, detail = _detail(js, "PerpsHistoryRow", "PerpsUnattached")
    assert '<div className="prp-detail-grid closed">' in detail
    cards = _cards(detail)
    assert [(p, t) for p, t, _ in cards] == [("result", "Result"), ("plan", "Plan"), ("review", "Review"),
                                             ("notes", "Notes"), ("rules", "Rule check")]
    res, plan, review, notes, rules = (c[2] for c in cards)
    assert _ordered(res, ['label="Venue"', 'label="Opened"', 'label="Closed"', "<PerpsAtExit trade={t} />",
                          'label="Peak size"', 'label="Fees"', 'label="Funding"', 'label="1R (peak size to stop)"',
                          "<PerpsExcursionFacts trade={t} />", "<PerpsHeldFact trade={t} />", "PRP_FLAGS[f]",
                          "<PerpsManualDelete trade={t} saver={saver} />",
                          "<PerpsStatus saving={saver.saving} status={saver.status} />"])
    assert _ordered(plan, ["<PerpsTrendsAtOpen trade={t} />", '<PerpsPlanPart title="Stop">',
                           "<PerpsStopEditor trade={t} saver={planSaver} closed={true} />",
                           "<PerpsCorrectionFact trade={t} />", '<PerpsPlanPart title="Take-profit">',
                           "<PerpsPlanFact trade={t} model={plan} emptyText=",
                           "<PerpsTagEditor trade={t} tag={tag} onSaved={onTagSaved} />",
                           "<PerpsStatus saving={planSaver.saving} status={planSaver.status} />"])
    assert _ordered(review, ["<PerpsReviewButtons trade={t} saver={reviewSaver} />",
                             "<PerpsExitReason trade={t} advisor={advisor} saver={reviewSaver} />",
                             'label="Gate"', "t.before_rule",
                             "<PerpsStatus saving={reviewSaver.saving} status={reviewSaver.status} />"])
    assert _ordered(notes, ["<PerpsNotesEditor trade={t} saver={notesSaver} withDeviation={true} />",
                            "<PerpsStatus saving={notesSaver.saving} status={notesSaver.status} />"])
    assert rules.strip() == "<PerpsRuleCheck trade={t} advisor={advisor} hide={hide} inCard />"
    assert 'label="Stop source"' not in detail                      # the Stop editor's line carries the source
    assert len(re.findall("prpUseSaver[(]t, onSaved[)]", body)) == 4


def test_a_manual_trades_stop_shows_in_the_plan_card():
    js = _read("static/perps.js")
    for fn, nxt in (("PerpsOpenRow", "PerpsUntrackedRow"), ("PerpsHistoryRow", "PerpsUnattached")):
        _, detail = _detail(js, fn, nxt)
        plan = [c for c in _cards(detail) if c[0] == "plan"][0][2]
        manual = _between(plan, "{isManual", ": <PerpsStopEditor")
        assert '<PerpsPlanPart title="Stop">' in manual and '<PerpsFact label="Stop">' in manual
        assert "prpPx(t.stop.px)" in manual and "PRP_STOP_SOURCE[t.stop.source]" in manual
        assert "'No stop recorded'" in manual


def test_trends_at_open_and_the_noodle_label():
    js = _read("static/perps.js")
    trends = _between(js, "function PerpsTrendsAtOpen(", "/* ")
    assert "if (!t.open_snapshot) return null;" in trends
    assert '<PerpsPlanPart title="Trends at Open">' in trends and '<PerpsAtOpen trade={t} label="Noodle" />' in trends
    at_open = _between(js, "function PerpsAtOpen(", "/* ")
    assert "const lab = label || 'At open';" in at_open
    assert 'label="At open"' not in at_open and at_open.count("label={lab}") == 3
    part = _between(js, "function PerpsPlanPart(", "function PerpsTrendsAtOpen(")
    assert "<span style={PRP_SECTION}>{title}</span>" in part


def test_the_rule_check_drops_its_title_inside_a_card():
    rules = _read("static/perpsrules.js")
    head = _between(rules, "function PerpsRuleCheck(", "const regById")
    assert head.startswith("{ trade, advisor, hide, inCard })")
    assert "const title = inCard ? null : <span style={PRP_SECTION}>Rule check</span>;" in head


def test_two_columns_from_1400px_by_grid_areas():
    css = _read("static/style.css")
    block = _between(css, "/* Landing 61:", "@media (min-width: 1400px) {")
    assert ".prp-detail-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; align-items: start; }" in block
    media = _between(css, block + "@media (min-width: 1400px) {", NL_BRACE)
    assert 'grid-template-areas: "position plan" "notes plan";' in media
    assert 'grid-template-areas: "result plan" "notes plan" "notes review";' in media
    assert media.count("grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);") == 2
    open_rule = _between(media, ".prp-detail-grid.open {", "}")
    closed_rule = _between(media, ".prp-detail-grid.closed {", "}")
    assert "grid-template-rows: auto 1fr;" in open_rule            # the last row takes the slack: no gap under Position
    assert "grid-template-rows: auto auto 1fr;" in closed_rule     # nor under Result
    for part in ("position", "result", "plan", "review", "notes"):
        assert '.prp-detail-grid > [data-prp-card="' + part + '"] { grid-area: ' + part + '; }' in media
    outside = css.replace(media, "")
    assert '[data-prp-card=' not in outside                         # the areas exist only from 1400px
    spot = _between(css, ".spot-detail-grid {", ".spot-card .spot-j75")
    assert "@media (min-width: 1400px)" in spot                      # the same breakpoint as the Spot cards
