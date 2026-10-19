"""Trends: TxFlow markets (Landing 53, Oct 19).

Glenn asked for TxFlow in the Trends scanner (spec: claude/SPEC_txflow_trends.md).
The scan stores the markets only TxFlow lists as "txflow:<NAME>" (asset class
'txflow') and the route adds txflow_name to every coin TxFlow lists
(tests/test_noodle_txflow_scan.py). static/trends.js shows them:
- a third ASSET CLASS chip, TxFlow (on by default with the others);
- an ON TXFLOW section, a plain tick: only coins TxFlow lists;
- a TX link on the Respected trend tab only (ruling 5-A), under TxFlow's own
  name (Hyperliquid's kBONK is TxFlow's 1000BONK);
- a "TxFlow" marker beside a TxFlow-only market, the bare name in search and
  the name sort, and no rank for it (ruling 6-A: "#" shows a dash and Top by
  volume drops it).
Browser checks (1920, 1250 and 390px) are in the landing record; these pin the
wiring and run the real helpers from static/trends.js in node.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

import txflow_markets
import web_portfolio as wp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(ROOT, "static", "trends.js"), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def test_constants_and_defaults():
    js = _js()
    assert "const TRENDS_TX_TRADE_URL = 'https://app.txflow.com/trade/';" in js
    assert "const TRENDS_TXFLOW_PREFIX = '" + txflow_markets.STORED_PREFIX + "';" in js      # the scan's stored prefix
    assert "const TRENDS_ALL_ASSET_CLASSES = ['crypto', 'tradfi', 'txflow'];" in js
    defaults = _between(js, "const TRENDS_FILTER_DEFAULTS = {", "};")
    assert "  onTxflow: false," in defaults                   # starts unticked like every section
    assert "assetClasses: new Set(TRENDS_ALL_ASSET_CLASSES)," in defaults


def test_tips_match_the_backend_they_describe():
    tips = _between(_js(), "const TRENDS_TIPS = {", "/* ── pure helpers ── */")
    on = _between(tips, "  onTxflow: {", "  setup1: {")
    assert "within " + str(int(round(txflow_markets.PRICE_TOLERANCE * 100))) + "% of Hyperliquid's" in on
    assert txflow_markets.TXFLOW_ALIASES["XAU"] == "GOLD" and "such as XAU for GOLD" in on
    assert wp.TXFLOW_MATCH_TTL_SECONDS == 86400 and "after it is a day old" in on
    assert "carry a TX link" in on
    refresh = _between(tips, "  refresh: {", "};")
    assert "at least $" + str(int(wp.TXFLOW_SCAN_MIN_VOLUME // 1000)) + "k of 24-hour volume" in refresh
    top = _between(tips, "  topVolume: {", "  refresh: {")
    assert "Markets only TxFlow lists are not ranked" in top and "any choice but All hides them" in top


def test_sidebar_section_sits_under_asset_class_on_both_tabs():
    side = _between(_js(), "function TrendsSidebar(", "/* ── main screen ── */")
    start = side.index("React.createElement(TrendsSidebarSection, { title: 'ON TXFLOW', tip: TRENDS_TIPS.onTxflow,")
    assert side.index("title: 'ASSET CLASS'") < start < side.index("title: 'DIRECTION'")
    assert "checked: filters.onTxflow, onCheck: (v) => set({ onTxflow: v }) }," in side
    assert "resp && React.createElement(TrendsSidebarSection, { title: 'ON TXFLOW'" not in side   # shown on both tabs


def test_filter_and_rank_wiring():
    js = _js()
    passes = _between(js, "function _trendsPassesSearchAndSidebar(", "const TRENDS_TOP_VOLUME_N")
    assert "if (filters.onTxflow && !_trendsOnTxflow(row)) return false;" in passes
    assert "_trendsDisplayName(row).toUpperCase().indexOf(q)" in passes
    listing = _between(js, "function _trendsRespectedList(", "function _trendsRespectVolume(")
    assert "if (filters.onTxflow && !_trendsOnTxflow(row)) continue;" in listing
    assert "_trendsDisplayName(row).toUpperCase().indexOf(q)" in listing
    screen = _between(js, "function TrendsScreen() {", "window.TrendsScreen")
    assert ".filter((r) => !_trendsIsTxflowOnly(r))" in _between(screen, "const rankMap = ", "const filtered = ")
    assert "respList.filter((it) => !_trendsIsTxflowOnly(it.row))" in _between(screen, "const respRankMap = ", "const respSorted = ")


def test_links_marker_and_names_in_the_tables():
    js = _js()
    main = _between(js, "function TrendsTable(", "/* ── respected trend tab (Landing 50c) ── */")
    assert "_trendsDisplayName(row)," in main
    assert "_trendsIsTxflowOnly(row) ? React.createElement(TrendsTxflowTag) : null," in main
    assert "_trendsTxUrl" not in main and "TX ↗" not in main          # ruling 5-A: links on the Respected tab only
    resp = _between(js, "function TrendsRespectedTable(", "/* ── sidebar ── */")
    assert "tx = _trendsTxUrl(row)" in resp
    assert "_trendsDisplayName(row)," in resp
    assert "_trendsIsTxflowOnly(row) ? React.createElement(TrendsTxflowTag) : null," in resp
    assert "(tv || hl || tx) ?" in resp
    assert ("tx ? React.createElement('a', { href: tx, target: '_blank', rel: 'noopener noreferrer', style: linkStyle," + chr(10)
            + "                  title: 'Open the market on TxFlow' }, 'TX ↗') : null)") in resp
    # a coin with no rank prints a dash on the Respected tab
    assert "rankMap.has(row.symbol) ? String(rankMap.get(row.symbol)) : '—'" in resp
    tag = _between(js, "function TrendsTxflowTag() {", "// Alignment chip")
    assert "}, 'TxFlow');" in tag and "fontSize: 11" in tag           # visible-size marker (11px minimum)
    assert "key: row.symbol" in main and "key: row.symbol" in resp    # rows stay keyed by the stored symbol


def _run(cases):
    """Run the real TxFlow helpers from static/trends.js in node."""
    js = _js()
    nl = chr(10)
    consts = nl.join(re.findall(
        r"^const TRENDS_(?:RESPECT_[A-Za-z_0-9]+|TV_CHART_URL|HL_TRADE_URL|TX_TRADE_URL|TXFLOW_PREFIX|ALL_ASSET_CLASSES) = .*;$", js, re.M))
    multi = "function _trendsPassesMultiFilter(" + _between(js, "function _trendsPassesMultiFilter(", "function _trendsPassesTimeSinceFlipped(")
    region = "function _trendsRespectCell(" + _between(js, "function _trendsRespectCell(", "// Every sidebar filter")
    passes = "function _trendsPassesSearchAndSidebar(" + _between(js, "function _trendsPassesSearchAndSidebar(", "const TRENDS_TOP_VOLUME_N")
    sortval = "function _trendsSortValue(" + _between(js, "function _trendsSortValue(", "/* ── small presentational pieces ── */")
    script = nl.join([
        consts, multi,
        "function _trendsAgeFromTs(nowMs, t) { return typeof t !== 'number' ? null : Math.max(0, Math.floor(nowMs / 1000) - t); }",
        "function _trendsPassesNearFlip() { return true; }",
        "function _trendsPassesHideChoppy() { return true; }",
        region, passes, sortval,
        "const cases = JSON.parse(process.argv[1]);",
        "const fix = (f) => Object.assign({}, f, { respDir: new Set(f.respDir), respTfs: new Set(f.respTfs), assetClasses: new Set(f.assetClasses),",
        "  trend: new Set(), alignment: new Set() });",
        "const out = cases.map((c) => {",
        "  if (c.kind === 'names') return c.rows.map((r) => [_trendsDisplayName(r), _trendsIsTxflowOnly(r), _trendsOnTxflow(r)]);",
        "  if (c.kind === 'links') return [_trendsTvUrl(c.row), _trendsHlUrl(c.row), _trendsTxUrl(c.row)];",
        "  if (c.kind === 'passes') return c.rows.filter((r) => _trendsPassesSearchAndSidebar(r, fix(c.filters), '1d', c.now)).map((r) => r.symbol);",
        "  if (c.kind === 'list') return _trendsRespectedList(c.rows, fix(c.filters), c.now).map((it) => it.row.symbol);",
        "  if (c.kind === 'sort') return [_trendsSortValue(c.row, c.key, '1d', new Map(c.rank)),",
        "    _trendsRespectSortValue({ row: c.row, info: { cells: {} } }, c.key, new Map(c.rank))];",
        "});",
        "console.log(JSON.stringify(out));",
    ])
    res = subprocess.run(["node", "-e", script, json.dumps(cases)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


BASE = 1792324200                             # 2026-10-18T12:30:00Z
DAY = BASE - BASE % 86400
NOW_MS = BASE * 1000
COMPUTED = "2026-10-18T12:30:00+00:00"


def _r4h(ago=1):
    """A 4h timeframe row the Respected tab lists: respected, latest tag `ago` bars before the last closed bar."""
    last_open = DAY + 8 * 3600
    return {"respect_dir": "BULLISH", "respect_tags": 2, "respect_losses": 0,
            "respect_last_ts": last_open - ago * 14400, "respect_since": last_open - 40 * 14400,
            "respect_ranging_since": None, "respect_breaks": None, "respect_unbounded": False,
            "computed_at": COMPUTED, "price": 100.0, "lower_band": 95.0, "upper_band": 105.0}


def _row(symbol, asset_class, txflow_name=None):
    return {"symbol": symbol, "asset_class": asset_class, "txflow_name": txflow_name, "timeframes": {"4h": _r4h()}}


def _filters(**kw):
    f = {"respDirOn": False, "respDir": ["BULLISH", "BEARISH"], "respRetest": False, "respTfs": ["4h"],
         "assetClassOn": False, "assetClasses": ["crypto", "tradfi", "txflow"], "onTxflow": False, "search": "",
         "setup1": False, "compression": False, "confluenceOn": False, "trendOn": False, "alignmentOn": False,
         "timeSinceOn": False, "nearFlip": False, "hideChoppy": False}
    f.update(kw)
    return f


pytestmark_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

ROWS = [
    _row("BTC", "crypto", "BTC"),                 # on both venues, same name
    _row("kBONK", "crypto", "1000BONK"),          # TxFlow's name differs from Hyperliquid's
    _row("GOLD", "crypto", "XAU"),                # alias
    _row("NVDA", "tradfi"),                       # Hyperliquid only
    _row("QNT", "tradfi"),                        # xyz QNT: not TxFlow's QNT
    _row("txflow:QNT", "txflow", "QNT"),          # TxFlow's own QNT (different price)
    _row("txflow:COTI", "txflow", "COTI"),
    _row("DELISTED", None),
]


@pytestmark_node
def test_behaviour_names_links_and_filters():
    cases = [
        {"kind": "names", "rows": [{"symbol": "txflow:QNT", "txflow_name": "QNT"},{"symbol": "QNT", "txflow_name": ""}, {"symbol": "kBONK", "txflow_name": "1000BONK"}]},
        {"kind": "links", "row": ROWS[1]},                                           # 1
        {"kind": "links", "row": ROWS[5]},                                           # 2
        {"kind": "links", "row": ROWS[3]},                                           # 3
        {"kind": "links", "row": {"symbol": "txflow:A&B", "asset_class": "txflow", "txflow_name": "A&B"}},
        {"kind": "links", "row": {"symbol": "X", "asset_class": "crypto", "txflow_name": ""}},
        {"kind": "passes", "rows": ROWS, "now": NOW_MS, "filters": _filters()},     # 6: nothing filtered
        {"kind": "passes", "rows": ROWS, "now": NOW_MS, "filters": _filters(onTxflow=True)},
        {"kind": "passes", "rows": ROWS, "now": NOW_MS, "filters": _filters(assetClassOn=True, assetClasses=["txflow"])},
        {"kind": "passes", "rows": ROWS, "now": NOW_MS, "filters": _filters(assetClassOn=True, assetClasses=["crypto", "tradfi"])},
        {"kind": "passes", "rows": ROWS, "now": NOW_MS, "filters": _filters(assetClassOn=True, assetClasses=["crypto", "txflow"])},
        {"kind": "passes", "rows": ROWS, "now": NOW_MS, "filters": _filters(onTxflow=True, assetClassOn=True, assetClasses=["crypto"])},
        {"kind": "passes", "rows": ROWS, "now": NOW_MS, "filters": _filters(search="qnt")},
        {"kind": "passes", "rows": ROWS, "now": NOW_MS, "filters": _filters(search="txflow")},
        {"kind": "passes", "rows": ROWS, "now": NOW_MS, "filters": _filters(search="coti")},
    ]
    got = _run(cases)
    assert got[0] == [["QNT", True, True], ["QNT", False, False], ["kBONK", False, True]]
    assert got[1] == ["https://www.tradingview.com/chart/?symbol=HYPERLIQUID%3AKBONKUSDC.P",
                      "https://app.hyperliquid.xyz/trade/kBONK",
                      "https://app.txflow.com/trade/1000BONK-USDC"]
    assert got[2] == [None, None, "https://app.txflow.com/trade/QNT-USDC"]          # TxFlow-only: its own link only
    assert got[3] == [None, "https://app.hyperliquid.xyz/trade/xyz:NVDA", None]     # not on TxFlow: no TX link
    assert got[4] == [None, None, "https://app.txflow.com/trade/A%26B-USDC"]
    assert got[5][2] is None                                                        # an empty name is not a market
    everything = [r["symbol"] for r in ROWS]
    assert got[6] == everything
    assert got[7] == ["BTC", "kBONK", "GOLD", "txflow:QNT", "txflow:COTI"]          # tagged and TxFlow-only, not xyz QNT
    assert got[8] == ["txflow:QNT", "txflow:COTI"]
    assert got[9] == ["BTC", "kBONK", "GOLD", "NVDA", "QNT"]                        # TxFlow chip off hides them and the unclassed coin
    assert got[10] == ["BTC", "kBONK", "GOLD", "txflow:QNT", "txflow:COTI"]         # TradFi off: tradfi and unclassed coins go
    assert got[11] == ["BTC", "kBONK", "GOLD"]                                      # both filters apply together
    assert got[12] == ["QNT", "txflow:QNT"]                                         # search sees the bare name
    assert got[13] == []                                                            # the stored prefix is not searchable
    assert got[14] == ["txflow:COTI"]


@pytestmark_node
def test_behaviour_respected_list_and_sorting():
    cases = [
        {"kind": "list", "rows": ROWS, "now": NOW_MS, "filters": _filters()},
        {"kind": "list", "rows": ROWS, "now": NOW_MS, "filters": _filters(onTxflow=True)},
        {"kind": "list", "rows": ROWS, "now": NOW_MS, "filters": _filters(assetClassOn=True, assetClasses=["txflow"])},
        {"kind": "list", "rows": ROWS, "now": NOW_MS, "filters": _filters(assetClassOn=True, assetClasses=["crypto", "tradfi"])},
        {"kind": "list", "rows": ROWS, "now": NOW_MS, "filters": _filters(search="qnt")},
        {"kind": "list", "rows": ROWS, "now": NOW_MS, "filters": _filters(search="txflow")},
        {"kind": "sort", "row": ROWS[5], "key": "symbol", "rank": [["BTC", 1]]},
        {"kind": "sort", "row": ROWS[5], "key": "rank", "rank": [["BTC", 1]]},
        {"kind": "sort", "row": ROWS[0], "key": "rank", "rank": [["BTC", 1]]},
    ]
    got = _run(cases)
    assert got[0] == [r["symbol"] for r in ROWS]            # no section ticked: every listed coin shows
    assert got[1] == ["BTC", "kBONK", "GOLD", "txflow:QNT", "txflow:COTI"]
    assert got[2] == ["txflow:QNT", "txflow:COTI"]
    assert got[3] == ["BTC", "kBONK", "GOLD", "NVDA", "QNT"]
    assert got[4] == ["QNT", "txflow:QNT"]
    assert got[5] == []
    assert got[6] == ["QNT", "QNT"]                       # the name sort uses the bare name on both tabs
    assert got[7] == [None, None]                          # no rank: sorts to the bottom
    assert got[8] == [1, 1]


# ── the stats strip and the manual perp form's ticker list ────────────────

def _node(script):
    res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def _strip_tiles(rows, tf="1d"):
    """Run the real TrendsStatsStrip from static/trends.js against a stub React; return {tile label: value}."""
    js = _js()
    nl = chr(10)
    script = nl.join([
        "const TRENDS_PANEL_BG = 'x', TRENDS_BORDER = 'x', TRENDS_TEXT_SECONDARY = 'x', TRENDS_TEXT_PRIMARY = 'x';",
        "const TRENDS_BULL = 'x', TRENDS_BEAR = 'x', TRENDS_NEUTRAL = 'x', TRENDS_ACCENT = 'x';",
        "const TRENDS_TXFLOW_PREFIX = '" + txflow_markets.STORED_PREFIX + "';",
        "const React = { useMemo: (f) => f(), createElement: (type, props, ...kids) => ({ type, props, kids }) };",
        "function _trendsConfluence(rowTimeframes) {" + _between(js, "function _trendsConfluence(rowTimeframes) {", nl + "}" + nl) + nl + "}",
        "function _trendsIsTxflowOnly(row) {" + _between(js, "function _trendsIsTxflowOnly(row) {", nl + "}") + nl + "}",
        "function TrendsStatsStrip(" + _between(js, "function TrendsStatsStrip(", nl + "}" + nl + nl + "/* ── table ── */") + nl + "}",
        "const rows = JSON.parse(process.argv[1]);",
        "const tree = TrendsStatsStrip({ rows, selectedTf: '" + tf + "' });",
        "console.log(JSON.stringify(tree.kids.map((t) => [t.kids[0].kids[0], t.kids[1].kids[0]])));",
    ])
    res = subprocess.run(["node", "-e", script, json.dumps(rows)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return {label: value for label, value in json.loads(res.stdout)}


def _tf_row(symbol, state):
    return {"symbol": symbol, "timeframes": {"1d": {"state": state}, "12h": {"state": state}, "1w": {"state": state}}}


def test_stats_strip_source_skips_txflow_only_rows():
    strip = _between(_js(), "function TrendsStatsStrip(", "/* ── table ── */")
    assert "if (_trendsIsTxflowOnly(r)) return;" in strip
    assert strip.index("_trendsIsTxflowOnly(r)") < strip.index("total++")


@pytestmark_node
def test_stats_strip_counts_hyperliquid_scan_rows_only():
    rows = [_tf_row("BTC", "BULLISH"), _tf_row("ETH", "BEARISH"), _tf_row("GOLD", "WARMUP"),
            _tf_row("txflow:COTI", "BULLISH"), _tf_row("txflow:QNT", "BULLISH")]
    tiles = _strip_tiles(rows)
    assert tiles["Total tokens"] == 3                                  # the two TxFlow-only rows are not counted
    assert tiles["Bullish"] == "1 (33%)" and tiles["Bearish"] == "1 (33%)" and tiles["Neutral"] == "1 (33%)"
    assert tiles["Full trend confluence"] == "2 (all 3 TFs agree)"       # BTC and ETH; GOLD is warming up


@pytestmark_node
def test_stats_strip_with_only_txflow_rows_shows_zero_not_a_division_error():
    tiles = _strip_tiles([_tf_row("txflow:COTI", "BULLISH")])
    assert tiles["Total tokens"] == 0 and tiles["Bullish"] == "0 (0%)"


def _perps_js():
    with open(os.path.join(ROOT, "static", "perps.js"), encoding="utf-8") as fh:
        return fh.read()


@pytestmark_node
def test_manual_form_ticker_list_uses_bare_names_once_each():
    fn = "function prpTickerOptions(" + _between(_perps_js(), "function prpTickerOptions(", chr(10) + "}" + chr(10)) + chr(10) + "}"
    script = fn + chr(10) + "const cases = JSON.parse(process.argv[1]); console.log(JSON.stringify(cases.map(prpTickerOptions)));"
    cases = [
        [{"symbol": "BTC"}, {"symbol": "txflow:COTI"}, {"symbol": "QNT"}, {"symbol": "txflow:QNT"}, {"symbol": "kBONK"}],
        [], None, "no", [{"symbol": ""}, {}, None, {"symbol": "txflow:"}],
    ]
    res = subprocess.run(["node", "-e", script, json.dumps(cases)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    got = json.loads(res.stdout)
    assert got[0] == ["BTC", "COTI", "QNT", "kBONK"]               # the prefix is gone; QNT (xyz) and TxFlow's QNT are one ticker
    assert got[1] == [] and got[2] == [] and got[3] == []
    assert got[4] == []                                            # junk entries and a bare prefix are dropped


def test_manual_form_uses_the_helper():
    src = _perps_js()
    assert "setTickers(prpTickerOptions(d && d.symbols));" in src
    assert src.count("function prpTickerOptions(") == 1
