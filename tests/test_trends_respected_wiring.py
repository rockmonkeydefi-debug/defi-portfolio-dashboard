"""Trends "Respected trend" tab (Landings 50 and 50c, Oct 17-18).

Glenn asked for the timeframes a coin is respecting, as watch-list
information (not entry triggers), then (Oct 18) for every timeframe shown at
once on its own tab: only coins with at least one respected timeframe, a
timeframe with two or more closes beyond the band never listed, one whose
latest tag is older than 30 bars shown dimmed as stale (a trend can be
intact without a new run high), columns high to low, TradingView and
Hyperliquid links per row, and the default order most respected timeframes
first. static/trends.js reads the five respect_* columns the scan stores on
the 1h / 4h / 12h / 1d rows (src/engines/respected_trend.py). Browser checks
(1920, 1250 and 390px) are in the landing record; these pin the wiring.
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


def test_constants_and_defaults():
    js = _js()
    assert "const TRENDS_RESPECT_MIN_TAGS = 2;" in js
    assert "const TRENDS_RESPECT_WINDOW_BARS = 30;" in js
    assert "const TRENDS_RESPECT_MAX_BREAKS = 1;" in js
    assert "const TRENDS_RESPECT_TFS = ['1d', '12h', '4h', '1h'];" in js          # high to low (Glenn)
    assert "const TRENDS_RESPECT_DIRS = ['BULLISH', 'BEARISH'];" in js
    assert "const TRENDS_TAB_STORAGE_KEY = 'trends.tab';" in js
    assert "const TRENDS_TV_CHART_URL = 'https://www.tradingview.com/chart/?symbol=';" in js
    assert "const TRENDS_HL_TRADE_URL = 'https://app.hyperliquid.xyz/trade/';" in js
    defaults = _between(js, "const TRENDS_FILTER_DEFAULTS = {", "};")
    assert "  respDirOn: false," in defaults and "  respRetest: false," in defaults
    assert "  respDir: new Set(TRENDS_RESPECT_DIRS)," in defaults
    assert "  respTfs: new Set(TRENDS_RESPECT_TFS)," in defaults
    assert "respected: false" not in defaults and "respectedRetest" not in defaults


def test_the_trends_tab_no_longer_carries_the_respected_filter():
    js = _js()
    passes = _between(js, "function _trendsPassesSearchAndSidebar(", "function _trendsSortValue(")
    assert "respect" not in passes.lower()
    table = _between(js, "function TrendsTable(", "/* ── respected trend tab (Landing 50c) ── */")
    assert "respectedOn" not in table and "_trendsRespect" not in table
    setups = _between(js, "!resp && React.createElement(TrendsSidebarSection, { title: 'SETUPS' },",
                      "!resp && React.createElement(TrendsSidebarSection, { title: 'TREND',")
    assert "Respected trend" not in setups and "Retesting now" not in setups
    assert "_trendsRespectedLabel" not in js and "TRENDS_TIPS.respected" not in js


def test_cell_rules_fail_closed():
    body = _between(_js(), "function _trendsRespectCell(r, tfKey, nowMs) {", "function _trendsRespectRow(")
    assert "if (!r || TRENDS_RESPECT_DIRS.indexOf(r.respect_dir) === -1) return null;" in body
    assert "if (typeof r.respect_tags !== 'number' || r.respect_tags < TRENDS_RESPECT_MIN_TAGS) return null;" in body
    assert "if (typeof r.respect_breaks !== 'number' || r.respect_breaks > TRENDS_RESPECT_MAX_BREAKS) return null;" in body
    assert "const lastClosedOpen = Math.floor(computedSec / tfSec) * tfSec - tfSec;" in body
    assert "status: barsAgo < TRENDS_RESPECT_WINDOW_BARS ? 'pass' : 'stale'," in body
    assert "r.price >= r.lower_band && r.price <= r.upper_band" in body


def test_tab_sidebar_table_and_links_are_wired():
    js = _js()
    screen = _between(js, "function TrendsScreen() {", "window.TrendsScreen = TrendsScreen;")
    assert "try { return localStorage.getItem(TRENDS_TAB_STORAGE_KEY) === 'respected' ? 'respected' : 'trends'; }" in screen
    assert "try { localStorage.setItem(TRENDS_TAB_STORAGE_KEY, t); } catch (e) {}" in screen
    assert "React.createElement(TrendsTabs, { tab, setTab })," in screen
    assert "mode: tab, filters, setFilters, selectedTf, setSelectedTf," in screen
    assert "return out.sort((a, b) => (b.info.counted.length - a.info.counted.length)" in screen
    assert "A watch list, not an entry signal." not in screen                       # Glenn: line removed
    tabs = _between(js, "function TrendsTabs({ tab, setTab }) {", "function TrendsRespectCell(")
    assert "btn('trends', 'Trends'), btn('respected', 'Respected trend')" in tabs
    side = _between(js, "function TrendsSidebar(", "/* ── main screen ── */")
    assert "const resp = mode === 'respected';" in side
    assert side.count("!resp && React.createElement(TrendsSidebarSection, {") == 8
    assert side.count("resp && React.createElement(TrendsSidebarSection, {") == 11         # 8 hidden + 3 shown
    for title in ("'DIRECTION'", "'TIMEFRAMES'", "'RETESTING NOW'"):
        assert "    resp && React.createElement(TrendsSidebarSection, { title: " + title in side, title
    assert "if (next.has(tfKey)) { if (next.size > 1) next.delete(tfKey); } else next.add(tfKey);" in side
    cell = _between(js, "function TrendsRespectCell({ cell, tfKey }) {", "function TrendsRespectedTable(")
    assert "stale ? 'stale · last tag ' + cell.barsAgo + ' bars ago'" in cell
    assert "cell.breaks === 1 ? React.createElement('div', { style: small }, '1 close beyond') : null," in cell
    links = _between(js, "function _trendsTvUrl(row) {", "/* ── small presentational pieces ── */")
    assert "'HYPERLIQUID:' + row.symbol.toUpperCase() + 'USDC.P'" in links
    assert "return TRENDS_HL_TRADE_URL + 'xyz:' + row.symbol;" in links


def _run(cases):
    """Run the real respected-tab helpers from static/trends.js in node."""
    js = _js()
    nl = chr(10)
    consts = nl.join(re.findall(r"^const TRENDS_(?:RESPECT_[A-Za-z_0-9]+|TV_CHART_URL|HL_TRADE_URL|ALL_ASSET_CLASSES) = .*;$", js, re.M))
    multi = "function _trendsPassesMultiFilter(" + _between(js, "function _trendsPassesMultiFilter(", "function _trendsPassesTimeSinceFlipped(")
    helpers = "function _trendsRespectCell(" + _between(js, "function _trendsRespectCell(", "// Every sidebar filter")
    script = nl.join([
        consts, multi,
        "function _trendsAgeFromTs(nowMs, t) { return typeof t !== 'number' ? null : Math.max(0, Math.floor(nowMs / 1000) - t); }",
        helpers,
        "const cases = JSON.parse(process.argv[1]);",
        "const out = cases.map((c) => {",
        "  if (c.kind === 'cell') return _trendsRespectCell(c.r, c.tf, c.now);",
        "  if (c.kind === 'links') return [_trendsTvUrl(c.row), _trendsHlUrl(c.row)];",
        "  const f = Object.assign({}, c.filters, { respDir: new Set(c.filters.respDir), respTfs: new Set(c.filters.respTfs),",
        "    assetClasses: new Set(c.filters.assetClasses) });",
        "  if (c.kind === 'row') { const x = _trendsRespectRow(c.row, f, c.now); return { counted: x.counted, cells: Object.keys(x.cells) }; }",
        "  if (c.kind === 'list') return _trendsRespectedList(c.rows, f, c.now).map((it) => it.row.symbol);",
        "});",
        "console.log(JSON.stringify(out));",
    ])
    res = subprocess.run(["node", "-e", script, json.dumps(cases)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


COMPUTED = "2026-10-18T12:30:00+00:00"       # last closed bars: 1h 11:00, 4h 08:00, 12h 00:00, 1d the day before
BASE = 1792324200                             # 2026-10-18T12:30:00Z
DAY = BASE - BASE % 86400
NOW_MS = BASE * 1000


def _r(ago, tags=2, breaks=0, direction="BULLISH", price=100.0, tf="4h"):
    tf_sec = {"1h": 3600, "4h": 14400, "12h": 43200, "1d": 86400}[tf]
    last_open = {"1h": 11 * 3600, "4h": 8 * 3600, "12h": 0, "1d": -86400}[tf]
    return {"respect_dir": direction, "respect_tags": tags, "respect_breaks": breaks,
            "respect_last_ts": DAY + last_open - ago * tf_sec, "respect_unbounded": False,
            "computed_at": COMPUTED, "price": price, "lower_band": 95.0, "upper_band": 105.0}


def _filters(**kw):
    f = {"respDirOn": False, "respDir": ["BULLISH", "BEARISH"], "respRetest": False,
         "respTfs": ["1d", "12h", "4h", "1h"], "assetClassOn": False, "assetClasses": ["crypto", "tradfi"], "search": ""}
    f.update(kw)
    return f


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_behaviour_cells():
    cases = [
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _r(0)},                      # newest closed bar
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _r(29)},                     # 30th bar still passes
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _r(30)},                     # 31st: stale
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _r(0, tags=1)},              # one tag: nothing
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _r(0, breaks=1)},            # one close beyond: passes
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _r(0, breaks=2)},            # two: never listed
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _r(0, breaks=None)},         # not rescanned: fails closed
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": dict(_r(0), respect_dir=None)},
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": dict(_r(0), computed_at=None)},
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _r(0, price=95.0)},          # on the lower edge: retesting
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _r(0, price=120.0)},         # outside the band
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": None},
    ]
    got = _run(cases)
    assert got[0]["status"] == "pass" and got[0]["barsAgo"] == 0
    assert got[1]["status"] == "pass" and got[1]["barsAgo"] == 29
    assert got[2]["status"] == "stale" and got[2]["barsAgo"] == 30
    assert got[3] is None
    assert got[4]["status"] == "pass" and got[4]["breaks"] == 1
    assert got[5] is None and got[6] is None and got[7] is None and got[8] is None
    assert got[9]["retesting"] is True and got[10]["retesting"] is False
    assert got[11] is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_behaviour_rows_list_and_links():
    row = {"symbol": "ALFA", "asset_class": "crypto", "timeframes": {
        "1d": _r(3, tf="1d"), "12h": _r(62, tags=3, tf="12h"), "4h": _r(2, price=120.0),
        "1h": _r(5, direction="BEARISH", tf="1h")}}
    stale_only = {"symbol": "BRAVO", "asset_class": "crypto", "timeframes": {"12h": _r(62, tf="12h")}}
    tradfi = {"symbol": "NVDA", "asset_class": "tradfi", "timeframes": {"4h": _r(1)}}
    cases = [
        {"kind": "row", "now": NOW_MS, "row": row, "filters": _filters()},
        {"kind": "row", "now": NOW_MS, "row": row, "filters": _filters(respDirOn=True, respDir=["BEARISH"])},
        {"kind": "row", "now": NOW_MS, "row": row, "filters": _filters(respRetest=True)},
        {"kind": "row", "now": NOW_MS, "row": row, "filters": _filters(respTfs=["12h", "4h"])},
        {"kind": "list", "now": NOW_MS, "rows": [row, stale_only, tradfi], "filters": _filters()},
        {"kind": "list", "now": NOW_MS, "rows": [row, stale_only, tradfi], "filters": _filters(assetClassOn=True, assetClasses=["tradfi"])},
        {"kind": "list", "now": NOW_MS, "rows": [row, stale_only, tradfi], "filters": _filters(search="alf")},
        {"kind": "links", "row": {"symbol": "kBONK", "asset_class": "crypto"}},
        {"kind": "links", "row": {"symbol": "NVDA", "asset_class": "tradfi"}},
        {"kind": "links", "row": {"symbol": "ODD", "asset_class": None}},
    ]
    got = _run(cases)
    assert got[0] == {"counted": ["1d", "4h", "1h"], "cells": ["1d", "12h", "4h", "1h"]}   # 12h is stale
    assert got[1]["counted"] == ["1h"]
    assert got[2]["counted"] == ["1d", "1h"]                                                # 4h price is outside
    assert got[3] == {"counted": ["4h"], "cells": ["12h", "4h"]}
    assert got[4] == ["ALFA", "NVDA"]                                                        # stale only: not listed
    assert got[5] == ["NVDA"] and got[6] == ["ALFA"]
    assert got[7] == ["https://www.tradingview.com/chart/?symbol=HYPERLIQUID%3AKBONKUSDC.P",
                      "https://app.hyperliquid.xyz/trade/kBONK"]
    assert got[8] == [None, "https://app.hyperliquid.xyz/trade/xyz:NVDA"]
    assert got[9] == [None, None]
