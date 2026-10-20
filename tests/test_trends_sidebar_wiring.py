"""Trends sidebar: section cards, section ticks and tooltips (Landing 45, Oct 16).

Glenn asked for tooltips explaining each sidebar item, then rewrote the text
as one tip per section (separate tips for the three Confluence chips and the
two limit dropdowns), and asked for each section to be its own card with a
checkbox to include it in the filter or not. Rulings (15:45): a section
filters only while ticked; unticking keeps its settings; changing a setting
in a section ticks it; each setup has its own tick; the Near flip, Hide
choppy and setup chips became the tick; Timeframe and Refresh have none;
everything starts unticked. static/trends.js keeps the text in TRENDS_TIPS
and shows it with TrendsTip (hover after a pause, keyboard focus, tap;
mouse-out, blur or Escape close it; aria-describedby links it). Browser
checks (1920, 1250 and 390px) are in the landing record; these pin the wiring.
Landing 50c (Oct 18): the Respected trend tab's DIRECTION, TIMEFRAMES and
RETESTING NOW sections live in the same sidebar (shown only on that tab).
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["assetClass", "onTxflow", "setup1", "setup1Recency", "compression", "respDirection", "respTimeframes", "respRetest", "trend", "confAll3", "conf4H", "confDW", "alignment",
        "timeSinceFlipped", "nearFlip", "nearFlipThreshold", "hideChoppy", "hideChoppyThreshold",
        "timeframe", "topVolume", "refresh"]
TICKS = ["trendOn", "confluenceOn", "alignmentOn", "timeSinceOn", "topVolumeOn"]


def _js():
    with open(os.path.join(ROOT, "static", "trends.js"), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def _sidebar(js):
    return _between(js, "function TrendsSidebar(", "/* ── main screen ── */")


def test_every_tip_has_text_and_is_used():
    js = _js()
    tips = _between(js, "const TRENDS_TIPS = {", "/* ── pure helpers ── */")
    for key in KEYS:
        assert "  " + key + ": {" in tips, key
        assert "TRENDS_TIPS." + key in _sidebar(js), key
    assert tips.count("title: ") == len(KEYS)
    assert tips.count("body: ") == len(KEYS)
    assert "TRENDS_TF_TIP_NOTES" not in js


def test_tip_text_matches_the_code_it_describes():
    tips = _between(_js(), "const TRENDS_TIPS = {", "/* ── pure helpers ── */")
    # Trend is flip-based (hysteretic), not where the last close sits
    assert "the last flip on that TF was a candle closing above the upper band" in tips
    assert "Closes back inside the band don't change either." in tips
    assert "H1 and H4 keep 60 days of candles, H12 150 days, D about 300 days, W about 41 weeks." in tips
    assert "Keeps only the top 20, 50 or 100 coins by 24-hour volume among those passing the other filters" in tips
    assert "All 3 agree, and the H4 trend agrees too." in tips
    assert "Neutral means the EMAs are tangled." in tips
    assert "or below it by ' + TRENDS_SETUP1_MAX_GAP_PCT + '% or less" in tips
    assert "A coin that is bearish now is measured to the upper edge" in tips
    assert "a coin that is bullish now is measured to the lower edge" in tips
    assert "more than 6 hours old" in tips


def test_sections_tick_and_filter():
    js = _js()
    defaults = _between(js, "const TRENDS_FILTER_DEFAULTS = {", "};")
    for tick in TICKS:
        assert "  " + tick + ": false," in defaults, tick
    assert "setup1: false," in defaults and "nearFlip: false," in defaults and "hideChoppy: false," in defaults
    passes = _between(js, "function _trendsPassesSearchAndSidebar(", "function _trendsSortValue(")
    assert "if (filters.trendOn && !_trendsPassesMultiFilter(filters.trend," in passes
    assert "if (filters.alignmentOn && !_trendsPassesMultiFilter(filters.alignment," in passes
    assert "if (filters.confluenceOn && (filters.confluenceAll3 || filters.confluenceDW || filters.confluence4H)) {" in passes
    assert "if (filters.timeSinceOn && !_trendsPassesTimeSinceFlipped(" in passes
    assert "if (!filters.topVolumeOn || filters.topVolume === 'all') return searchAndSidebarFiltered;" in js


def test_sidebar_layout_ticks_and_auto_tick():
    js = _js()
    side = _sidebar(js)
    assert side.count("React.createElement(TrendsSidebarSection, {") == 14   # ASSET CLASS (L46); 3 Respected tab sections (L50c); ON TXFLOW (L53)
    assert side.count("onCheck: (v) =>") == 13          # 8 sections with a tick + the two setup rows + DIRECTION and RETESTING NOW (L50c) + ON TXFLOW (L53)
    assert "React.createElement(TrendsSidebarSection, { title: 'TIMEFRAME', tip: TRENDS_TIPS.timeframe }," in side
    assert "React.createElement(TrendsSidebarSection, { title: 'TREND CONFLUENCE'," in side   # Glenn 16:05
    for flag in ("'trendOn'", "'alignmentOn'"):
        assert side.count(flag) == 3, flag                 # every chip of the section ticks it
    assert side.count("confluenceOn: true") == 3
    assert "set({ timeSinceFlipped: e.target.value, timeSinceOn: true })" in side
    assert "set({ nearFlipThreshold: Number(e.target.value), nearFlip: true })" in side
    assert "set({ hideChoppyThreshold: Number(e.target.value), hideChoppy: true })" in side
    assert "set({ setup1Recency: e.target.value, setup1: true })" in side
    assert "set({ topVolume: e.target.value, topVolumeOn: true })" in side
    assert "label: 'Near flip'" not in side and "label: 'Hide choppy'" not in side
    card = _between(js, "function TrendsSidebarSection(", "function TrendsSetupRow(")
    assert "type: 'checkbox', checked: on, onChange: (e) => onCheck(e.target.checked)," in card
    assert "border: '1px solid ' + (on ? TRENDS_ACCENT : TRENDS_BORDER)," in card
    assert "background: TRENDS_HEADER_BG" in card
    assert "React.createElement(TrendsTip, { tip }, React.createElement(TrendsInfoButton, { label: tip.title }))" in card


def test_tip_component_behaviour_is_wired():
    js = _js()
    comp = _between(js, "function TrendsTip({ tip, block, children }) {", "function TrendsChipToggle(")
    assert "const TRENDS_TIP_DELAY_MS = 350;" in js
    assert "const id = React.useId();" in comp
    assert "timerRef.current = setTimeout(show, TRENDS_TIP_DELAY_MS);" in comp
    assert "if (t && t.matches && t.matches(':focus-visible')) show();" in comp
    assert "onMouseEnter, onMouseLeave: hide, onFocus, onBlur: hide, onTouchStart," in comp
    assert "if (e.key === 'Escape') hide();" in comp
    assert "React.cloneElement(children, { 'aria-describedby': id })" in comp
    assert "id, role: 'tooltip', className: 'trends-tip'," in comp
    # Landing 52: drawn on document.body with position:fixed from the control's on-screen
    # box, lined up with the sidebar's inner edges, flipped above when there is no room below
    assert "ReactDOM.createPortal(" in comp and "      document.body" in comp
    assert "display: anchor ? 'block' : 'none', position: 'fixed', zIndex: 1000," in comp
    assert "const sidebar = el.closest('.trends-sidebar');" in comp
    assert "left: sr ? sr.left + sidebar.clientLeft + pad : r.left," in comp
    assert "width: Math.max(200, sidebar ? sidebar.clientWidth - 2 * pad : 268)," in comp
    assert "let top = anchor.bottom + 4;" in comp
    assert "if (top + h > vh - 8 && anchor.top - 4 - h >= 8) top = anchor.top - 4 - h;" in comp
    assert "const left = Math.min(Math.max(8, anchor.left), vw - width - 8);" in comp
    assert "visibility: pos ? 'visible' : 'hidden'," in comp
    assert "whiteSpace: 'normal', pointerEvents: 'none'," in comp
    assert "function onTouchStart() {" + chr(10) + "    clearTimeout(timerRef.current);" + chr(10) + "    show();" in comp
    assert "window.addEventListener('scroll', onScroll, true);" in comp
    assert "window.addEventListener('resize', hide);" in comp
    assert "if (Date.now() - openedAtRef.current < TRENDS_COL_TIP_SETTLE_MS) measure(); else hide();" in comp
    assert "function TrendsChipToggle({ active, label, onClick, color, 'aria-describedby': describedBy }) {" in js
    info = _between(js, "function TrendsInfoButton(", "const TRENDS_SECTION_TITLE_STYLE")
    assert "type: 'button', 'aria-label': 'About ' + label, 'aria-describedby': describedBy," in info
