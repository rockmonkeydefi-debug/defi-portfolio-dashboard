"""Landing 62 (Oct 23, Glenn "A, A" after the prototype): a price bar on each
Open positions row of the Perps page, in place of the Entry, Mark, Stop and
Target columns (static/perps.js PerpsPriceBar).

The stop sits on the left and the take-profits on the right for longs and
shorts alike; the bar runs from the stop to the furthest take-profit
(prpBarModel). The dot is the current price (the venue's mark), with an arrow
when it is past either end. Every level shows its number under the bar (the
nearest and the furthest take-profit when there are more than two), the
current price and its R above it, and the hover lists every level with its R
(prpBarText). Without a stop the left end reaches the current price; without
a take-profit the right end is 2R or the current price. Manual trades have no
price feed, so no dot. The old Target cell (PerpsTargetCell) is gone.

Browser checks (1920, 1250 and 390px, against main) are in the landing
record; these read the source files and run the bar's model in node.
"""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_NODE = shutil.which("node") is not None
NL = chr(10)
MD = chr(0xB7)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    assert start in text, start
    rest = text.split(start, 1)[1]
    assert end in rest, end
    return rest.split(end, 1)[0]


def _fn(js, name):
    """The source of one top-level function (it ends at the first line that is a lone closing brace)."""
    start = js.index("function " + name + "(")
    return js[start:js.index(NL + "}" + NL, start) + 2]


def _run(body, data):
    js = _read("static/perps.js")
    script = NL.join(["function fmtPrice(n) { return '$' + n.toPrecision(3); }"]
                     + [_fn(js, n) for n in ("prpNum", "prpPx", "prpR", "prpBarModel", "prpBarTpName", "prpBarText")]
                     + ["const data = JSON.parse(process.argv[1]);", body])
    res = subprocess.run(["node", "-e", script, json.dumps(data)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def _models(cases):
    return _run("console.log(JSON.stringify(data.map(c => prpBarModel(c[0], c[1], c[2], c[3], c[4]))));", cases)


def _close(a, b):
    return abs(a - b) < 1e-6


def test_one_price_column_where_four_were():
    js = _read("static/perps.js")
    grid = _between(js, "const PRP_OPEN_GRID = ", ";")
    assert "'minmax(80px,0.9fr) minmax(360px,3.9fr) minmax(90px,1fr) minmax(76px,0.8fr) minmax(100px,1fr)'" in grid
    assert "repeat(4," not in grid                                   # Size, Entry, Mark, Stop are gone as columns
    tab = _between(js, "function PerpsOpenTab(", "function PerpsHistoryRow(")
    head = _between(tab, 'className="spot-grid-row spot-grid-head"', "</div>")
    assert "<span style={{ paddingLeft: 16 }}>Price levels</span>" in head
    for gone in (">Entry<", ">Mark<", ">Stop<", ">Target<"):
        assert gone not in head
    assert "the stop on the left, take-profits on the right (long or short)" in tab


def test_the_open_row_and_an_untracked_position_draw_the_bar():
    js = _read("static/perps.js")
    row = _between(js, "function PerpsOpenRow(", "if (!open) return row;")
    assert '<div className="spot-cell prp-bar-cell" data-label="Price levels">' in row
    assert ("<PerpsPriceBar direction={t.direction} entry={t.avg_entry} stop={t.stop ? t.stop.px : null} tps={tps}" in row)
    assert "mark={!isManual && live ? live.mark_px : null} noMark={isManual ? 'Manual: no price feed' : 'No live data yet'}" in row
    assert "PRP_STOP_SOURCE[t.stop.source]" in _between(row, "stopNote={", "/>")
    untracked = _between(js, "function PerpsUntrackedRow(", "function PerpsOpenTab(")
    assert "<PerpsPriceBar direction={u.direction} entry={live.entry_px} stop={live.stop_px} tps={live.take_profits}" in untracked
    assert "mark={live.mark_px}" in untracked
    for body in (row, untracked):
        for gone in ("num('Entry'", "num('Mark'", "num('Stop'", 'data-label="Target"', "PerpsTargetCell"):
            assert gone not in body
    assert "function PerpsTargetCell(" not in js and "<PerpsTargetCell" not in js
    assert "gridTemplateColumns: PRP_OPEN_GRID" in untracked


def test_the_bar_labels_every_level_and_spreads_the_labels():
    js = _read("static/perps.js")
    bar = _between(js, "function PerpsPriceBar(", "/* ")
    assert "const PRP_BAR_TP_LABELS = 2;" in js
    assert "n <= PRP_BAR_TP_LABELS ? model.tps.map((t, i) => i) : [0, n - 1]" in bar
    assert 'name="Stop" value={prpPx(model.stop.px)}' in bar and 'name="Entry" value={prpPx(model.entry.px)}' in bar
    assert 'name="No stop"' in bar and 'name="No take-profit"' in bar
    assert 'role="img" aria-label={text} title={text}' in bar
    assert "prpBarPlaceLabels(box)" in bar and "new ResizeObserver(place)" in bar and "ro.disconnect()" in bar
    place = _fn(js, "prpBarPlaceLabels")
    assert "prev + PRP_BAR_GAP" in place and "width - items[i].w" in place and "next - PRP_BAR_GAP - items[i].w" in place


def test_the_bar_cell_css():
    css = _read("static/style.css")
    assert ".prp-bar-cell { padding: 0 16px; }" in css
    narrow = _between(css, ".prp-bar-cell { padding: 0 16px; }", "}" + NL + "}")
    assert "@media (max-width: 1249px)" in narrow and ".prp-bar-cell { grid-column: 1 / -1; padding: 0;" in narrow


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_long_and_short_read_the_same_way():
    long_, short = _models([["long", "100", "95", ["110", "120"], "105"], ["short", "100", "105", ["90", "80"], "95"]])
    for m in (long_, short):
        assert _close(m["stop"]["pos"], 0) and _close(m["entry"]["pos"], 20)
        assert [round(t["pos"], 6) for t in m["tps"]] == [60, 100]
        assert _close(m["mark"]["pos"], 40) and m["mark"]["side"] == "profit" and m["mark"]["out"] is None
        assert _close(m["stop"]["r"], -1) and _close(m["mark"]["r"], 1) and [round(t["r"], 6) for t in m["tps"]] == [2, 4]


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_a_price_past_either_end_sits_at_the_edge():
    past_tp, past_stop = _models([["long", "100", "95", ["110"], "130"], ["short", "100", "105", ["90"], "107"]])
    assert past_tp["mark"]["pos"] == 100 and past_tp["mark"]["out"] == "right"
    assert past_stop["mark"]["pos"] == 0 and past_stop["mark"]["out"] == "left" and past_stop["mark"]["side"] == "loss"


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_missing_levels():
    no_stop, no_tp, bare, no_entry, manual = _models([
        ["long", "100", None, ["110"], "97"],          # no stop: the left end reaches the current price
        ["long", "100", "95", [], "103"],              # no take-profit: the right end is 2R (or the price)
        ["long", "100", None, None, None],             # nothing but the entry
        ["long", "", "95", ["110"], "105"],
        ["long", "38.4", "36.9", ["42"], None],        # manual: no price feed
    ])
    assert no_stop["stop"] is None and no_stop["mark"]["pos"] == 0 and no_stop["mark"]["r"] is None
    assert _close(no_stop["entry"]["pos"], 3 / 13 * 100) and no_stop["tps"][0]["pos"] == 100
    assert no_tp["tps"] == [] and _close(no_tp["entry"]["pos"], 5 / 15 * 100) and _close(no_tp["mark"]["pos"], 8 / 15 * 100)
    assert bare["entry"]["pos"] == 50 and bare["stop"] is None and bare["mark"] is None
    assert no_entry is None
    assert manual["mark"] is None and _close(manual["tps"][0]["r"], 3.6 / 1.5)


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_a_stop_past_entry_and_a_take_profit_on_the_losing_side_stay_on_the_bar():
    trailed, odd = _models([["long", "100", "102", ["110"], "105"], ["long", "100", "95", ["93"], "99"]])
    assert trailed["stop"]["r"] is None and trailed["entry"]["pos"] == 0 and _close(trailed["stop"]["pos"], 20)
    assert all(0 <= p <= 100 for p in (odd["stop"]["pos"], odd["entry"]["pos"], odd["tps"][0]["pos"], odd["mark"]["pos"]))


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_the_hover_text_lists_every_level_with_its_r():
    out = _run("console.log(JSON.stringify(data.map(c => prpBarText(prpBarModel(c[0], c[1], c[2], c[3], c[4]), c[0], c[5]))));",
               [["long", "100", "95", ["110", "120"], "105", "entered here"], ["short", "3.80", None, [], "3.62", None],
                ["long", "100", "95", ["110"], None, None]])
    sep = " " + MD + " "
    assert out[0] == sep.join(["Long: Stop $95.00 (-1.00R), entered here", "Entry $100.00", "Current $105.00 (+1.00R)",
                               "TP1 $110.00 (2.0R)", "TP2 $120.00 (4.0R). 1R = entry to stop."])
    assert out[1] == sep.join(["Short: No stop", "Entry $3.80", "Current $3.62", "No take-profit. 1R = entry to stop."])
    assert out[2] == sep.join(["Long: Stop $95.00 (-1.00R)", "Entry $100.00", "TP $110.00 (2.0R). 1R = entry to stop."])
