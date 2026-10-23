"""Trends sidebar: scrolling section list and pinned Refresh (Landing 52, Oct 19).

On the Trends tab the sidebar is 1,388px tall (11 sections), so at a 950px
window the sticky box hid NEAR FLIP, HIDE CHOPPY, TIMEFRAME, TOP BY VOLUME and
Refresh until the page was scrolled to its end. Glenn ruled option A (the
sections scroll inside the box, Refresh and the scan progress stay pinned at
its bottom) and, on "your recs", also: the sidebar tips are drawn on screen
(position:fixed in a portal) so the scrolling list cannot clip them, and the
cap applies only while the sidebar is beside the table (under the table, at
390px, it keeps its full height and the page scrolls). static/trends.js
decides "beside" from the row's width: the row wraps below the table's flex
basis + gap + sidebar width. Browser checks (1920, 1250 and 390px, a width
sweep, a short window, tips, keyboard, a running scan) are in the landing
record; these pin the wiring.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(ROOT, "static", "trends.js"), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def _sidebar(js):
    return _between(js, "function TrendsSidebar(", "/* ── main screen ── */")


def _screen(js):
    return js.split("function TrendsScreen() {", 1)[1]


def test_row_constants_add_up_and_replace_the_literals():
    js = _js()
    assert "const TRENDS_PANEL_BASIS = 500;" in js
    assert "const TRENDS_SIDEBAR_WIDTH = 300;" in js
    assert "const TRENDS_ROW_GAP = 16;" in js
    assert "const TRENDS_SIDE_BY_SIDE_MIN = TRENDS_PANEL_BASIS + TRENDS_ROW_GAP + TRENDS_SIDEBAR_WIDTH;" in js
    assert 500 + 16 + 300 == 816
    screen = _screen(js)
    assert "gap: TRENDS_ROW_GAP, alignItems: 'flex-start', flexWrap: 'wrap'" in screen
    assert "flex: '1 1 ' + TRENDS_PANEL_BASIS + 'px', minWidth: 0," in screen
    assert "width: TRENDS_SIDEBAR_WIDTH, flexShrink: 0," in _sidebar(js)
    # no second copy of the numbers is left in the layout styles
    assert "'1 1 500px'" not in js and "gap: 16, alignItems" not in js and "width: 300, flexShrink" not in js


def test_screen_knows_when_the_sidebar_is_beside_the_table():
    screen = _screen(_js())
    assert "const [rowEl, setRowEl] = React.useState(null);" in screen
    assert "const [sideBySide, setSideBySide] = React.useState(true);" in screen
    assert "const check = () => setSideBySide(rowEl.clientWidth >= TRENDS_SIDE_BY_SIDE_MIN);" in screen
    assert "const ro = new ResizeObserver(check);" in screen and "ro.observe(rowEl);" in screen
    assert "return () => ro.disconnect();" in screen
    # no ResizeObserver: fall back to the window's resize event
    assert "window.addEventListener('resize', check);" in screen
    assert "return () => window.removeEventListener('resize', check);" in screen
    assert "React.createElement('div', { ref: setRowEl, style: { display: 'flex'," in screen
    assert "onRefresh: handleRefresh, pinned: sideBySide," in screen
    # the hooks sit before the loading early return
    assert screen.index("setSideBySide] = React.useState") < screen.index("if (loading) {")


def test_pinned_sidebar_caps_height_and_scrolls_the_list_only():
    js = _js()
    side = _sidebar(js)
    assert "onRefresh, pinned }) {" in side
    assert "borderRadius: 8, padding: 16, alignSelf: 'flex-start', position: 'sticky', top: 12," in side
    assert "const listStyle = {};" in side
    assert "const footStyle = { borderTop: '1px solid ' + TRENDS_BORDER, paddingTop: 16 };" in side
    gate = _between(side, "  if (pinned) {", "  // The sections are the children")
    assert "Object.assign(boxStyle, { display: 'flex', flexDirection: 'column', maxHeight: 'calc(100vh - 24px)' });" in gate
    assert "flex: '0 1 auto', minHeight: 0, overflowY: 'auto', overflowX: 'hidden', margin: '-16px -16px 0', padding: '16px 16px 0'," in gate
    assert "scrollbarWidth: 'thin', scrollbarColor: 'rgba(255,255,255,0.45) transparent'," in gate
    assert "footStyle.flex = '0 0 auto';" in gate
    # nothing but the pinned branch touches the caps
    assert side.count("maxHeight") == 1 and side.count("overflowY") == 1


def test_sections_scroll_and_the_refresh_block_is_the_pinned_footer():
    side = _sidebar(_js())
    assert "return React.createElement('div', { className: 'trends-sidebar', style: boxStyle }," in side
    list_at = side.index("className: 'trends-sidebar-list', style: listStyle")
    foot_at = side.index("className: 'trends-sidebar-foot', style: footStyle")
    assert list_at < foot_at
    inside_list = side[list_at:foot_at]
    assert inside_list.count("React.createElement(TrendsSidebarSection, {") == 15   # every section scrolls (POI AT THE BAND since L58)
    assert "'Refresh'" not in inside_list and "TrendsScanProgress" not in inside_list
    footer = side[foot_at:]
    assert "TrendsTip, { tip: TRENDS_TIPS.refresh, block: true }" in footer
    assert "refreshBusy ? 'Scanning…' : 'Refresh'" in footer
    assert "React.createElement(TrendsScanProgress, { run: scanRun, nowMs })," in footer
    assert "scanDoneMsg && React.createElement(" in footer
    assert footer.count("TrendsSidebarSection") == 0
