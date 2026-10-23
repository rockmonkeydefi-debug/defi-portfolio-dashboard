"""Respected trend tab: points of interest (Landing 58, Oct 20).

Glenn asked for the old ICT order block and fair value gap detectors on the
Respected trend tab. Rulings ("your recs"): the scan finds them and stores one
per respected timeframe (tests/test_trend_poi.py covers the search and the
columns); each cell shows its type and range, with "POI at band" when it sits
on the noodle band; a POI AT THE BAND sidebar section keeps coins with one on
the band on a passing timeframe, ticked like Testing now and combining with
it. Browser checks (1920, 1250 and 390px) are in the landing record; these pin
the wiring and run the real helpers in node.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(ROOT, "static", "trends.js"), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def test_default_tip_and_sidebar_section():
    js = _js()
    assert "  respPoi: false,             // Landing 58: POI at the band (ticks like Testing now)" in js
    tips = _between(js, "const TRENDS_TIPS = {", "/* -- pure helpers -- */".replace("--", chr(0x2500) * 2))
    tip = _between(tips, "  respPoi: {", "  },")
    assert "title: 'POI at the band'," in tip
    assert "by default a body of at least 0.7 ATR" in tip and "at least a tenth of the ATR" in tip
    assert "an order block once a candle closes through it, a gap once price fills it" in tip
    assert "A watch list, not an entry signal." in tip
    side = _between(js, "function TrendsSidebar(", "/* -- main screen -- */".replace("--", chr(0x2500) * 2))
    sec = _between(side, "    resp && React.createElement(TrendsSidebarSection, { title: 'POI AT THE BAND', tip: TRENDS_TIPS.respPoi,", "    ),")
    assert "checked: filters.respPoi, onCheck: (v) => set({ respPoi: v }) }," in sec
    assert "'An order block or fair value gap on the band on a respected timeframe.'" in sec
    assert "fontSize: 11, color: TRENDS_TEXT_SECONDARY" in sec
    # the next section after TESTING NOW
    gap = _between(side, "title: 'TESTING NOW'", "title: 'POI AT THE BAND'")
    assert gap.count("TrendsSidebarSection") == 1


def test_cell_row_and_render_wiring():
    js = _js()
    poi = _between(js, "function _trendsPoi(r) {", '// "Respected for" text')
    assert "(r.poi_type !== 'OB' && r.poi_type !== 'FVG') || typeof r.poi_top !== 'number' || typeof r.poi_bottom !== 'number') return null;" in poi
    cell = _between(js, "function _trendsRespectCell(r, tfKey, nowMs) {", "function _trendsPoi(")
    assert "poi: _trendsPoi(r), poiAtBand: r.poi_at_band === true," in cell
    row = _between(js, "function _trendsRespectRow(row, filters, nowMs) {", "function _trendsIsTxflowOnly(")
    assert row.index("if (!cell || cell.status !== 'pass') continue;") < row.index("if (filters.respPoi && !cell.poiAtBand) continue;")
    assert row.index("if (filters.respRetest && !cell.retesting) continue;") < row.index("if (filters.respPoi && !cell.poiAtBand) continue;")
    render = _between(js, "function TrendsRespectCell({ cell, tfKey }) {", "function TrendsRespectedTable(")
    assert "!stale && cell.poi ? React.createElement('div', { 'data-poi': cell.poi.type, style: small }," in render
    # two unbreakable halves, so a tight column wraps before the top instead of widening the table
    assert "React.createElement('span', { style: { whiteSpace: 'nowrap' } }, cell.poi.type + ' ' + window.fmtTokenPrice(cell.poi.bottom) + ' -'), ' '," in render
    assert "React.createElement('span', { style: { whiteSpace: 'nowrap' } }, window.fmtTokenPrice(cell.poi.top))) : null," in render
    assert "!stale && cell.poiAtBand ? React.createElement('div', {" in render and "}, 'POI at band') : null," in render
    assert render.index("}, 'testing') : null,") < render.index("'data-poi'") < render.index("}, 'POI at band')") < render.index("'history limited'")


def _run(cases):
    """Run the real respected-tab helpers from static/trends.js in node."""
    js = _js()
    nl = chr(10)
    consts = nl.join(re.findall(r"^const TRENDS_(?:RESPECT_[A-Za-z_0-9]+|ALL_ASSET_CLASSES) = .*;$", js, re.M))
    multi = "function _trendsPassesMultiFilter(" + _between(js, "function _trendsPassesMultiFilter(", "function _trendsPassesTimeSinceFlipped(")
    helpers = "function _trendsRespectCell(" + _between(js, "function _trendsRespectCell(", "function _trendsIsTxflowOnly(")
    script = nl.join([
        consts, multi,
        "function _trendsAgeFromTs(nowMs, t) { return typeof t !== 'number' ? null : Math.max(0, Math.floor(nowMs / 1000) - t); }",
        helpers,
        "const cases = JSON.parse(process.argv[1]);",
        "const out = cases.map((c) => {",
        "  if (c.kind === 'cell') { const x = _trendsRespectCell(c.r, c.tf, c.now); return x ? { status: x.status, poi: x.poi, poiAtBand: x.poiAtBand } : null; }",
        "  const f = Object.assign({}, c.filters, { respDir: new Set(c.filters.respDir), respTfs: new Set(c.filters.respTfs) });",
        "  return _trendsRespectRow(c.row, f, c.now).counted;",
        "});",
        "console.log(JSON.stringify(out));",
    ])
    res = subprocess.run(["node", "-e", script, json.dumps(cases)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


COMPUTED = "2026-10-18T12:30:00+00:00"
BASE = 1792324200                             # 2026-10-18T12:30:00Z
DAY = BASE - BASE % 86400
NOW_MS = BASE * 1000
TF_SEC = {"1h": 3600, "4h": 14400, "12h": 43200, "1d": 86400}
LAST_OPEN = {"1h": 11 * 3600, "4h": 8 * 3600, "12h": 0, "1d": -86400}


def _r(tf="4h", ago=2, price=100.0, poi_type="OB", top=101.0, bottom=99.0, at_band=True, count=2):
    last_open = DAY + LAST_OPEN[tf]
    return {"respect_dir": "BULLISH", "respect_tags": 3, "respect_losses": 0,
            "respect_last_ts": last_open - ago * TF_SEC[tf], "respect_since": last_open - 40 * TF_SEC[tf],
            "respect_ranging_since": None, "respect_unbounded": False, "computed_at": COMPUTED,
            "price": price, "lower_band": 95.0, "upper_band": 105.0,
            "poi_type": poi_type, "poi_top": top, "poi_bottom": bottom, "poi_ts": last_open - 10 * TF_SEC[tf],
            "poi_at_band": at_band, "poi_count": count}


def _filters(**kw):
    f = {"respDirOn": False, "respDir": ["BULLISH", "BEARISH"], "respRetest": False, "respPoi": False,
         "respTfs": ["1d", "12h", "4h", "1h"]}
    f.update(kw)
    return f


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_behaviour_cells():
    cases = [
        {"kind": "cell", "r": _r(), "tf": "4h", "now": NOW_MS},
        {"kind": "cell", "r": _r(poi_type="FVG", at_band=False, count=1), "tf": "4h", "now": NOW_MS},
        {"kind": "cell", "r": _r(poi_type="BOS"), "tf": "4h", "now": NOW_MS},              # unknown type: no POI
        {"kind": "cell", "r": _r(top=None), "tf": "4h", "now": NOW_MS},                    # missing level: no POI
        {"kind": "cell", "r": _r(poi_type=None, top=None, bottom=None, at_band=None, count=None), "tf": "4h", "now": NOW_MS},
        {"kind": "cell", "r": _r(at_band=1), "tf": "4h", "now": NOW_MS},                   # only a real true counts
        {"kind": "cell", "r": _r(ago=40), "tf": "4h", "now": NOW_MS},                      # stale cell keeps its POI
    ]
    got = _run(cases)
    assert got[0] == {"status": "pass", "poiAtBand": True,
                      "poi": {"type": "OB", "top": 101.0, "bottom": 99.0, "atBand": True, "count": 2}}
    assert got[1]["poi"] == {"type": "FVG", "top": 101.0, "bottom": 99.0, "atBand": False, "count": 1}
    assert got[1]["poiAtBand"] is False
    assert got[2]["poi"] is None and got[3]["poi"] is None and got[4]["poi"] is None
    assert got[4]["poiAtBand"] is False
    assert got[5]["poiAtBand"] is False and got[5]["poi"]["atBand"] is False
    assert got[6]["status"] == "stale" and got[6]["poiAtBand"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_behaviour_filter_and_testing_now():
    row = {"symbol": "AAA", "timeframes": {
        "1d": _r("1d", at_band=True, price=110.0),           # POI at band, price outside the band
        "12h": _r("12h", at_band=False, price=100.0),        # testing, POI not at band
        "4h": _r("4h", at_band=True, price=100.0),           # testing and POI at band
        "1h": _r("1h", ago=40, at_band=True, price=100.0),   # stale: never counted
    }}
    cases = [
        {"kind": "row", "row": row, "filters": _filters(), "now": NOW_MS},
        {"kind": "row", "row": row, "filters": _filters(respPoi=True), "now": NOW_MS},
        {"kind": "row", "row": row, "filters": _filters(respRetest=True), "now": NOW_MS},
        {"kind": "row", "row": row, "filters": _filters(respPoi=True, respRetest=True), "now": NOW_MS},
        {"kind": "row", "row": row, "filters": _filters(respPoi=True, respTfs=["12h", "1h"]), "now": NOW_MS},
    ]
    got = _run(cases)
    assert got[0] == ["1d", "12h", "4h"]
    assert got[1] == ["1d", "4h"]
    assert got[2] == ["12h", "4h"]
    assert got[3] == ["4h"]
    assert got[4] == []
