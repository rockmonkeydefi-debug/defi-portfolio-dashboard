"""Trends "Respected trend" tab (Landings 50, 50c and 51, Oct 17-18).

Glenn asked for the timeframes a coin is respecting, as watch-list
information (not entry triggers), then (Oct 18) for every timeframe shown at
once on its own tab: only coins with at least one respected timeframe, one
whose latest tag is older than 30 bars shown dimmed as stale (a trend can be
intact without a new run high), columns high to low, TradingView and
Hyperliquid links per row, and the default order most respected timeframes
first. Landing 51 reworked the rule around the band's slope: a timeframe with
two or more losses (two closes in a row beyond the far edge) is never listed,
a flat band means no trend, the cell shows how long the trend has been
respected ("respected 3W 2D") instead of a tag count, "Retesting now" became
"Testing now", and a flat band right after a respected history shows
"Ranging". static/trends.js reads the respect_* columns the scan stores on the
1h / 4h / 12h / 1d rows (src/engines/respected_trend.py). Browser checks
(1920, 1250 and 390px) are in the landing record; these pin the wiring.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

import src.engines.respected_trend as rt

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
    assert "const TRENDS_RESPECT_MAX_LOSSES = 1;" in js
    assert "TRENDS_RESPECT_MAX_BREAKS" not in js
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


def test_the_engine_and_the_tab_share_one_pass_rule():
    """The engine repeats the tab's pass rule for the Ranging marker; the copies must not drift."""
    js = _js()
    for js_name, value in (("MIN_TAGS", rt.RESPECT_MIN_TAGS), ("MAX_LOSSES", rt.RESPECT_MAX_LOSSES),
                           ("WINDOW_BARS", rt.RESPECT_WINDOW_BARS)):
        m = re.search(r"^const TRENDS_RESPECT_" + js_name + r" = ([0-9]+);$", js, re.M)
        assert m and int(m.group(1)) == value, js_name


def test_the_trends_tab_no_longer_carries_the_respected_filter():
    js = _js()
    passes = _between(js, "function _trendsPassesSearchAndSidebar(", "function _trendsSortValue(")
    assert "respect" not in passes.lower()
    table = _between(js, "function TrendsTable(", "/* ── respected trend tab (Landing 50c) ── */")
    assert "respectedOn" not in table and "_trendsRespect" not in table
    setups = _between(js, "!resp && React.createElement(TrendsSidebarSection, { title: 'SETUPS' },",
                      "!resp && React.createElement(TrendsSidebarSection, { title: 'TREND',")
    assert "Respected trend" not in setups and "Retesting now" not in setups and "Testing now" not in setups
    assert "_trendsRespectedLabel" not in js and "TRENDS_TIPS.respected" not in js


def test_cell_rules_fail_closed():
    body = _between(_js(), "function _trendsRespectCell(r, tfKey, nowMs) {", "function _trendsRespectRow(")
    assert "if (!r || typeof r.computed_at !== 'string') return null;" in body
    assert "if (r.respect_dir === null || r.respect_dir === undefined) {" in body
    assert "if (TRENDS_RESPECT_DIRS.indexOf(r.respect_dir) === -1) return null;" in body
    assert "if (typeof r.respect_ranging_since !== 'number') return null;" in body
    assert "if (flatBars >= TRENDS_RESPECT_WINDOW_BARS) return null;" in body
    assert "if (typeof r.respect_since !== 'number') return null;" in body                       # not rescanned
    assert "if (typeof r.respect_tags !== 'number' || r.respect_tags < TRENDS_RESPECT_MIN_TAGS) return null;" in body
    assert "if (typeof r.respect_losses !== 'number' || r.respect_losses > TRENDS_RESPECT_MAX_LOSSES) return null;" in body
    assert "respect_breaks" not in body
    assert "const lastClosedOpen = Math.floor(computedSec / tfSec) * tfSec - tfSec;" in body
    assert "status: barsAgo < TRENDS_RESPECT_WINDOW_BARS ? 'pass' : 'stale'," in body
    assert "forSeconds: Math.max(0, lastClosedOpen + tfSec - r.respect_since)," in body
    assert "r.price >= r.lower_band && r.price <= r.upper_band" in body


def test_testing_now_wording_and_cell_text():
    js = _js()
    assert "Retesting" not in js and "RETESTING" not in js and "retesting'" not in js     # identifiers stay, text goes
    assert "title: 'Testing now'," in js
    cell = _between(js, "function TrendsRespectCell({ cell, tfKey }) {", "function TrendsRespectedTable(")
    assert "}, 'testing') : null," in cell
    assert "}, TRENDS_STATE_LABELS[cell.dir])," in cell                                    # first line: just Bullish / Bearish
    assert "' tags'" not in cell and "1 close beyond" not in cell and "cell.breaks" not in cell
    assert "'respected ' + forText" in cell
    assert "}, 'Ranging')," in cell and "'went flat ' + flatAge + ' ago'" in cell


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
    for title in ("'DIRECTION'", "'TIMEFRAMES'", "'TESTING NOW'"):
        assert "    resp && React.createElement(TrendsSidebarSection, { title: " + title in side, title
    assert "if (next.has(tfKey)) { if (next.size > 1) next.delete(tfKey); } else next.add(tfKey);" in side
    cell = _between(js, "function TrendsRespectCell({ cell, tfKey }) {", "function TrendsRespectedTable(")
    assert "stale ? 'stale · last tag ' + cell.barsAgo + ' bars ago'" in cell
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
        "const f0 = (c) => Object.assign({}, c.filters, { respDir: new Set(c.filters.respDir), respTfs: new Set(c.filters.respTfs), assetClasses: new Set(c.filters.assetClasses) });",
        "const out = cases.map((c) => {",
        "  if (c.kind === 'cell') return _trendsRespectCell(c.r, c.tf, c.now);",
        "  if (c.kind === 'fmt') return _trendsFmtRespectedFor(c.s, c.u);",
        "  if (c.kind === 'status') { const x = _trendsRespectRow(c.row, f0(c), c.now); const o = {}; for (const k of Object.keys(x.cells)) o[k] = x.cells[k] ? x.cells[k].status : null; return o; }",
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


TF_SEC = {"1h": 3600, "4h": 14400, "12h": 43200, "1d": 86400}
LAST_OPEN = {"1h": 11 * 3600, "4h": 8 * 3600, "12h": 0, "1d": -86400}      # offset of the last closed bar from DAY


def _r(ago, tags=2, losses=0, direction="BULLISH", price=100.0, tf="4h", since_bars=40):
    """A timeframe row with a sloping history: latest tag `ago` bars before the last closed bar, history
    started `since_bars` bars before it (so it has been respected for since_bars + 1 bars)."""
    last_open = DAY + LAST_OPEN[tf]
    return {"respect_dir": direction, "respect_tags": tags, "respect_losses": losses,
            "respect_last_ts": last_open - ago * TF_SEC[tf], "respect_since": last_open - since_bars * TF_SEC[tf],
            "respect_ranging_since": None, "respect_breaks": None, "respect_unbounded": False,
            "computed_at": COMPUTED, "price": price, "lower_band": 95.0, "upper_band": 105.0}


def _flat(bars_ago, tf="4h"):
    """A timeframe row whose band went flat `bars_ago` bars before the last closed bar, after a respected history."""
    last_open = DAY + LAST_OPEN[tf]
    return {"respect_dir": None, "respect_tags": None, "respect_losses": None, "respect_last_ts": None,
            "respect_since": None, "respect_ranging_since": last_open - bars_ago * TF_SEC[tf],
            "respect_breaks": None, "respect_unbounded": None, "computed_at": COMPUTED,
            "price": 100.0, "lower_band": 95.0, "upper_band": 105.0}


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
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _r(0, losses=1)},            # one loss: passes
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _r(0, losses=2)},            # two: never listed
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _r(0, losses=None)},         # no loss count: fails closed
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": dict(_r(0), respect_dir=None)},
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": dict(_r(0), computed_at=None)},
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _r(0, price=95.0)},          # on the lower edge: retesting
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _r(0, price=120.0)},         # outside the band
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": None},
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": dict(_r(0), respect_since=None)},          # row from before Landing 51
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": dict(_r(0), respect_since=None, respect_breaks=0)},
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _r(0, since_bars=0)},        # history began on the last closed bar
        {"kind": "cell", "tf": "1d", "now": NOW_MS, "r": _r(0, tf="1d", since_bars=20)},
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": dict(_r(0), respect_unbounded=True)},
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _flat(0)},                   # the band just went flat
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _flat(29)},
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": _flat(30)},                  # 30 bars on: gone
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": dict(_flat(0), respect_ranging_since=None)},
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": dict(_flat(0), computed_at=None)},
        {"kind": "cell", "tf": "4h", "now": NOW_MS, "r": dict(_flat(0), respect_dir="SIDEWAYS")},    # unknown dir is not a history
    ]
    got = _run(cases)
    assert got[0]["status"] == "pass" and got[0]["barsAgo"] == 0
    assert got[1]["status"] == "pass" and got[1]["barsAgo"] == 29
    assert got[2]["status"] == "stale" and got[2]["barsAgo"] == 30
    assert got[3] is None
    assert got[4]["status"] == "pass" and got[4]["losses"] == 1
    assert got[5] is None and got[6] is None and got[7] is None and got[8] is None
    assert got[9]["retesting"] is True and got[10]["retesting"] is False
    assert got[11] is None
    assert got[12] is None and got[13] is None                                    # old-format rows fail closed
    assert got[14]["forSeconds"] == 14400                                         # through the end of the last closed bar
    assert got[15]["forSeconds"] == 21 * 86400
    assert got[0]["forSeconds"] == 41 * 14400 and got[0]["unbounded"] is False and got[16]["unbounded"] is True
    assert got[17] == {"status": "ranging", "flatBars": 0, "ageSeconds": got[17]["ageSeconds"]}
    assert got[17]["ageSeconds"] == NOW_MS // 1000 - (DAY + 8 * 3600)
    assert got[18]["status"] == "ranging" and got[18]["flatBars"] == 29
    assert got[19] is None and got[20] is None and got[21] is None and got[22] is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_behaviour_respected_for_text():
    d, h = 86400, 3600
    cases = [{"kind": "fmt", "s": s, "u": u} for s, u in (
        (23 * d, False), (7 * d, False), (6 * d + 23 * h, False), (5 * d + 6 * h, False), (5 * d, False),
        (18 * h, False), (59 * 60, False), (0, False), (23 * d + 2 * h, True), (30 * d, True), (None, False))]
    assert _run(cases) == ["3W 2D", "1W", "6D 23H", "5D 6H", "5D", "18H", "< 1H", "< 1H", "≥3W 2D", "≥4W 2D", None]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_behaviour_rows_list_and_links():
    row = {"symbol": "ALFA", "asset_class": "crypto", "timeframes": {
        "1d": _r(3, tf="1d"), "12h": _r(62, tags=3, tf="12h"), "4h": _r(2, price=120.0),
        "1h": _r(5, direction="BEARISH", tf="1h")}}
    stale_only = {"symbol": "BRAVO", "asset_class": "crypto", "timeframes": {"12h": _r(62, tf="12h")}}
    tradfi = {"symbol": "NVDA", "asset_class": "tradfi", "timeframes": {"4h": _r(1)}}
    ranging_only = {"symbol": "CHARLIE", "asset_class": "crypto", "timeframes": {"12h": _flat(2, tf="12h"), "4h": _flat(5)}}
    mixed = {"symbol": "DELTA", "asset_class": "crypto", "timeframes": {
        "1d": _r(3, tf="1d"), "12h": _flat(2, tf="12h"), "4h": _r(40), "1h": _flat(60, tf="1h")}}
    cases = [
        {"kind": "row", "now": NOW_MS, "row": row, "filters": _filters()},
        {"kind": "row", "now": NOW_MS, "row": row, "filters": _filters(respDirOn=True, respDir=["BEARISH"])},
        {"kind": "row", "now": NOW_MS, "row": row, "filters": _filters(respRetest=True)},
        {"kind": "row", "now": NOW_MS, "row": row, "filters": _filters(respTfs=["12h", "4h"])},
        {"kind": "list", "now": NOW_MS, "rows": [row, stale_only, tradfi], "filters": _filters()},
        {"kind": "list", "now": NOW_MS, "rows": [row, stale_only, tradfi], "filters": _filters(assetClassOn=True, assetClasses=["tradfi"])},
        {"kind": "list", "now": NOW_MS, "rows": [row, stale_only, tradfi], "filters": _filters(search="alf")},
        {"kind": "list", "now": NOW_MS, "rows": [row, ranging_only], "filters": _filters()},
        {"kind": "status", "now": NOW_MS, "row": mixed, "filters": _filters()},
        {"kind": "row", "now": NOW_MS, "row": mixed, "filters": _filters()},
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
    assert got[7] == ["ALFA"]                                                                # a ranging-only coin is not listed
    assert got[8] == {"1d": "pass", "12h": "ranging", "4h": "stale", "1h": None}            # 1h flat is 60 bars old: no cell
    assert got[9] == {"counted": ["1d"], "cells": ["1d", "12h", "4h", "1h"]}                # ranging and stale do not count
    assert got[10] == ["https://www.tradingview.com/chart/?symbol=HYPERLIQUID%3AKBONKUSDC.P",
                       "https://app.hyperliquid.xyz/trade/kBONK"]
    assert got[11] == [None, "https://app.hyperliquid.xyz/trade/xyz:NVDA"]
    assert got[12] == [None, None]
