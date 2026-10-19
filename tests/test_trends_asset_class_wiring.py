"""Trends ASSET CLASS filter and the trend-confluence tile (Landing 46, Oct 16).

Glenn asked for a filter to show only crypto, only TradFi, or both (ruling
2-A: the route tags each symbol, see tests/test_noodle_asset_class.py), and
for the "Full confluence" tile to read "Full trend confluence" (it counts
trend-state agreement only). static/trends.js adds an ASSET CLASS card at the
top of the sidebar that works like the Landing 45 sections: it filters only
while ticked, a chip click ticks it, and a coin with no class shows only with
all chips on. Landing 53 (Oct 19) added a third chip, TxFlow, for the markets
only TxFlow lists (tests/test_trends_txflow_wiring.py). Browser checks (1920,
1250 and 390px) are in the landing record; these pin the wiring.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(ROOT, "static", "trends.js"), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def test_defaults_and_filter():
    js = _js()
    assert "const TRENDS_ALL_ASSET_CLASSES = ['crypto', 'tradfi', 'txflow'];" in js
    defaults = _between(js, "const TRENDS_FILTER_DEFAULTS = {", "};")
    assert "assetClassOn: false," in defaults
    assert "assetClasses: new Set(TRENDS_ALL_ASSET_CLASSES)," in defaults
    passes = _between(js, "function _trendsPassesSearchAndSidebar(", "function _trendsSortValue(")
    assert ("if (filters.assetClassOn && !_trendsPassesMultiFilter(filters.assetClasses, "
            "TRENDS_ALL_ASSET_CLASSES, row.asset_class)) return false;") in passes
    assert "assetClasses: new Set(TRENDS_ALL_ASSET_CLASSES) }));" in js     # fresh Set per screen


def test_card_is_first_and_ticks_on_change():
    side = _between(_js(), "function TrendsSidebar(", "/* ── main screen ── */")
    first = side.index("React.createElement(TrendsSidebarSection, {")
    assert side[first:].startswith("React.createElement(TrendsSidebarSection, { title: 'ASSET CLASS', tip: TRENDS_TIPS.assetClass,")
    assert "checked: filters.assetClassOn, onCheck: (v) => set({ assetClassOn: v }) }," in side
    assert "toggleSetMember('assetClasses', 'crypto', 'assetClassOn')" in side
    assert "toggleSetMember('assetClasses', 'tradfi', 'assetClassOn')" in side
    assert "toggleSetMember('assetClasses', 'txflow', 'assetClassOn')" in side
    assert "label: 'Crypto'" in side and "label: 'TradFi'" in side and "label: 'TxFlow'" in side


def test_tooltip_and_tile():
    js = _js()
    tip = _between(js, "  assetClass: {", "  onTxflow: {")
    assert "TradFi: perps on its xyz exchange" in tip
    assert "a name listed on both counts as crypto" in tip
    assert "TxFlow: markets that only TxFlow lists" in tip
    assert "shows only with all three chips on" in tip
    assert "tile('Full trend confluence', stats.confluence + ' (all 3 TFs agree)', TRENDS_ACCENT)" in js
    assert "tile('Full confluence'" not in js
