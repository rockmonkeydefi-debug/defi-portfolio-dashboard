"""Landing 66 (Oct 24, Glenn "A, A" after the prototype): the Dashboard's
Open Perps card draws the Perps page's price bar (static/dashboard.js
DashOpenPerpsCard, static/perps.js PerpsPriceBar).

One PRICE LEVELS column where ENTRY, MARK, STOP and TP were: the stop on the
left, every live take-profit on the right (the route's "take_profits",
nearest first; "tp_px" when the list is missing), the dot at the mark. No
stop shows the bar's "No stop" in the warning colour; a partial stop gets a
line under the bar; when the open orders could not be read the cell says so
in text (no bar, so no false "No stop"). The stop's distance from the mark
moves into the hover text. Liquidation keeps its own column. The table's
minimum width fits the card at 1250px. On a phone the table still scrolls
sideways (Glenn's "A").

perps.js loads after dashboard.js, so the bar is read from window at render
time. Browser checks against main are in the landing record; these read the
source files only.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    assert start in text, start
    rest = text.split(start, 1)[1]
    assert end in rest, end
    return rest.split(end, 1)[0]


def _card():
    js = _read("static/dashboard.js")
    return _between(js, "function DashOpenPerpsCard(", NL + "}" + NL)


def test_one_price_column_where_four_were():
    js = _read("static/dashboard.js")
    grid = _between(js, "const DASH_PERPS_GRID = ", ";")
    assert grid == "'minmax(130px,1fr) minmax(130px,1fr) 104px minmax(352px,3fr) 112px 96px 88px 88px'"
    mins = [int(x) for x in re.findall("([0-9]+)px", grid)]
    width = int(_between(js, "const DASH_PERPS_MIN_WIDTH = ", ";"))
    assert width == sum(mins) + 10 * (len(mins) - 1) + 40 == 1210      # columns, 10px gaps, 20px padding each side
    assert width <= 1216                                               # the card's inner width at 1250px
    card = _card()
    assert "<div style={{ paddingLeft: 8 }}>PRICE LEVELS</div>" in card
    for gone in ("headCell('ENTRY')", "headCell('MARK')", "headCell('STOP'", "headCell('TP')", "stopCell", "r.tp_px)"):
        assert gone not in card, gone
    assert "headCell('VENUE " + chr(0xB7) + " WALLET', undefined, true)" in card
    heads = re.findall("headCell[(]'([A-Z. ]+)'", card)                  # the other headings, in order
    assert heads == ["POSITION", "SIZE", "UNREALIZED", "IF STOPPED", "LIQ.", "FUNDING"]


def test_the_bar_is_wired_with_every_level():
    card = _card()
    assert "const Bar = window.PerpsPriceBar;" in card
    assert ("<Bar direction={r.direction} entry={r.entry_px} stop={r.flags.includes('no_stop') ? null : r.stop_px} tps={tps}"
            in card)
    assert 'mark={r.mark_px} noMark="No mark price" stopNote={note || undefined} />' in card
    assert "const tps = Array.isArray(r.take_profits) ? r.take_profits : (r.tp_px ? [r.tp_px] : []);" in card
    assert "_dashSignedPct(r.stopDist, 2) + ' from mark'" in card                     # the old second line, now in the hover
    assert "partial ? 'covers only part of the position' : null" in card
    assert "The stop covers only part of the position</div>" in card
    assert "{levels}" in card and card.index("{levels}") < card.index("{two(num(unreal.text, unreal.color),")
    assert "{two(num(liq," in card                                                   # liquidation keeps its column


def test_unreadable_orders_say_so_instead_of_a_bar():
    card = _card()
    branch = _between(card, "if (r.flags.includes('open_orders_unavailable')) {", "} else if (!Bar) {")
    assert "Stop and take-profits unknown: open orders could not be read" in branch
    assert "<Bar" not in branch
    assert "'Open orders could not be read' + (r.open_orders_error ? ': ' + r.open_orders_error : '')" in branch


def test_perps_js_shares_the_bar_and_loads_before_the_app():
    perps = _read("static/perps.js")
    assert NL + "window.PerpsPriceBar = PerpsPriceBar;" + NL in perps
    html = _read("templates/index.html")
    d, p, a = (html.index("/static/" + f + "?v=") for f in ("dashboard.js", "perps.js", "app.js"))
    assert d < p < a                                                     # read at render time, after every file has run
