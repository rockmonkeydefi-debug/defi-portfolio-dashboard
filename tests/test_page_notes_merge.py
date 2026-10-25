"""Landing 67: merged cells in the Notes tables.

The page (static/pagenotes.js) repairs any document's merges before it saves
or shows them, with the same rules the server gate applies
(web_portfolio._page_note_check_merges). These tests run the page's real
repair functions in node and feed what they return to the server's check, so
anything the page saves the server accepts. The gate's own cases are in
test_page_notes.py; the wiring is read from the source, as in
test_page_notes_wiring.py.
"""
import json
import os
import random
import shutil
import subprocess
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_NODE = shutil.which("node") is not None
NL = chr(10)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def _repair(docs):
    js = _read("static/pagenotes.js")
    helpers = NL.join([
        "const PN_SPAN_MAX" + _between(js, "const PN_SPAN_MAX", NL),
        "function pnSameAttrs" + _between(js, "function pnSameAttrs", NL + "}" + NL) + NL + "}",
        "function pnSpanValue" + _between(js, "function pnSpanValue", "// Even column widths"),
    ])
    script = NL.join([
        helpers,
        "const docs = JSON.parse(require('fs').readFileSync(0, 'utf8'));",
        "console.log(JSON.stringify(docs.map(d => { const a = pnRepairDeltaMerges(d.ops); const b = pnRepairDeltaMerges(a);"
        " return [a, JSON.stringify(a) === JSON.stringify(b)]; })));",
    ])
    res = subprocess.run(["node", "-e", script], input=json.dumps(docs), capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def _span_values(values):
    js = _read("static/pagenotes.js")
    script = NL.join([
        "const PN_SPAN_MAX" + _between(js, "const PN_SPAN_MAX", NL),
        "function pnSpanValue" + _between(js, "function pnSpanValue", "// The merges of one row"),
        "console.log(JSON.stringify(JSON.parse(require('fs').readFileSync(0, 'utf8')).map(pnSpanValue)));",
    ])
    res = subprocess.run(["node", "-e", script], input=json.dumps(values), capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def _flat(ops):
    """The ops with every line break on its own (the page joins equal neighbours)."""
    out = []
    for op in ops:
        ins = op["insert"]
        if isinstance(ins, str) and len(ins) > 1 and ins.replace(NL, "") == "":
            out += [{"insert": NL, "attributes": dict(op["attributes"])} for _ in ins]
        else:
            out.append(op)
    return out


def _cell(row, text="", **attrs):
    ops = [{"insert": text}] if text else []
    ops.append({"insert": NL, "attributes": dict({"table": row}, **attrs)})
    return ops


def _doc(*cells):
    ops = []
    for c in cells:
        ops += c
    return {"ops": ops + [{"insert": "end" + NL}]}


def _gen(rng):
    ops = []
    for ri in range(rng.randint(1, 3)):
        for _ in range(rng.randint(1, 6)):
            if rng.random() < .45:
                ops.append({"insert": rng.choice(["x", "ab", "c d"])})
            a = {"table": "row-%d" % (ri + 1)}
            r = rng.random()
            if r < .3:
                a["cell-span"] = str(rng.choice([2, 2, 3, 4, 7, 25, 1]))
            elif r < .6:
                a["cell-covered"] = True
            if rng.random() < .2:
                a["cell-span"] = str(rng.choice([2, 3]))
                a["cell-covered"] = True
            if rng.random() < .5:
                a["cell-w"] = "%d%%" % rng.choice([20, 30, 50])
            ops.append({"insert": NL, "attributes": a})
        if rng.random() < .3:
            ops.append({"insert": "plain" + NL})
    ops.append({"insert": "end" + NL})
    return {"ops": ops}


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_what_the_page_repairs_the_server_accepts():
    rng = random.Random(67)
    docs = [_gen(rng) for _ in range(300)]
    out = _repair(docs)
    kept = 0
    for d, (fixed, stable) in zip(docs, out):
        assert stable, d
        err = wp._page_note_check({"ops": fixed}, images_ok=True)[2]
        assert err is None, (err, d)
        kept += any("cell-span" in (op.get("attributes") or {}) for op in fixed)
    assert kept > 30                       # the fuzz does produce merges that survive


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_a_valid_merge_is_left_as_it_is():
    d = _doc(_cell("row-1", "a", **{"cell-span": "3"}), _cell("row-1", **{"cell-covered": True}),
             _cell("row-1", **{"cell-covered": True}), _cell("row-1", "z"))
    (fixed, _), = _repair([d])
    assert _flat(fixed) == d["ops"]


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_a_document_without_merges_is_returned_untouched():
    d = {"ops": [{"insert": "a"}, {"insert": NL * 3, "attributes": {"table": "row-1", "cell-w": "30%"}}, {"insert": "end" + NL}]}
    (fixed, _), = _repair([d])
    assert fixed == d["ops"]               # not even re-split into single breaks


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_broken_merges_are_repaired_the_same_way_the_server_judges_them():
    wide = _doc(_cell("row-1", **{"cell-span": "4"}), _cell("row-1", **{"cell-covered": True}), _cell("row-1"))
    lone = _doc(_cell("row-1", **{"cell-covered": True}), _cell("row-1"))
    full = _doc(_cell("row-1", **{"cell-span": "2"}), _cell("row-1", "text", **{"cell-covered": True}))
    one = _doc(_cell("row-1", **{"cell-span": "1"}), _cell("row-1"))
    out = _repair([wide, lone, full, one])
    attrs = lambda f: [(op.get("attributes") or {}).get("cell-span") or ((op.get("attributes") or {}).get("cell-covered")) for op in _flat(f) if op["insert"] == NL]
    assert attrs(out[0][0]) == ["2", True, None]          # narrowed to what the row holds
    assert attrs(out[1][0]) == [None, None]               # a covered cell nothing covers is plain again
    assert attrs(out[2][0]) == [None, None]               # a covered cell holding text breaks the merge
    assert attrs(out[3][0]) == [None, None]               # a span of one is no merge
    for d in out:
        assert wp._page_note_check({"ops": d[0]})[2] is None


def test_the_page_and_the_server_share_the_limits():
    js = _read("static/pagenotes.js")
    assert "const PN_SPAN_MAX = %d;" % wp.PAGE_NOTE_SPAN_MAX in js
    assert "const PN_MERGE_KEYS = [" + ", ".join("'%s'" % k for k in wp._PAGE_NOTE_MERGE) + "];" in js


def test_merge_buttons_and_width_guard_are_wired():
    js = _read("static/pagenotes.js")
    assert "Merge cells" in js and "Split cell" in js
    assert "pnLayoutMerged" in js and "pnCellTab" in js and "pnCoveredFix" in js
    css = _read("static/style.css")
    assert "table.pn-merged" in css and "td[data-pn-covered]" in css
    assert "grid-column: span var(--pn-span, 1)" in css


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_span_values_read_the_same_as_the_server():
    values = ["0", "1", "2", "9", "10", "20", "21", "30", "99", "100", "-2", "2.5", "x", "", " 2", "02", 2, True, None]
    got = _span_values(values)
    for v, g in zip(values, got):
        assert (g is not None) == (isinstance(v, str) and wp._PAGE_NOTE_SPAN_RE.fullmatch(v) is not None), (v, g)
        assert g is None or g == int(v)
    assert got[values.index("20")] == 20 and got[values.index("21")] is None and got[values.index("1")] is None


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_a_plain_line_ends_a_row_for_the_page_too():
    d = {"ops": _cell("row-1", **{"cell-span": "2"}) + [{"insert": "break" + NL}] + _cell("row-1", **{"cell-covered": True}) + [{"insert": "end" + NL}]}
    (fixed, _), = _repair([d])
    assert all("cell-span" not in (op.get("attributes") or {}) and "cell-covered" not in (op.get("attributes") or {}) for op in fixed)
    assert wp._page_note_check({"ops": fixed})[2] is None
