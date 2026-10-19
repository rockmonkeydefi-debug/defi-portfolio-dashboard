"""Trends table column tooltips (Landing 54, Oct 19).

Glenn asked for header tooltips on five Trends table columns (the first
buildable item after Landing 53), ruled "A" (hover on the header label plus a
small "i" button for touch and keyboard), on the main table and on the
expanded row's sub-table, and wrote the five texts himself. static/trends.js
keeps them in TRENDS_COLUMN_TIPS and shows them with TrendsHeaderTip, a
separate component from the sidebar's TrendsTip (that one is anchored to the
sidebar). Browser checks (1920, 1250 and 390px) are in the landing record;
these pin the text and the wiring.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)

# key -> (title, body): Glenn's Oct 19 texts, character for character.
TIPS = {
    "pct": ("Δ since flip",
            "Price change from the flip price to the current price."),
    "toFlip": ("To flip",
               "Distance from the last closed candle to the band edge that will trigger a trend flip, "
               "as a % of the closing price. Positive when bearish (price must rise to the upper edge), "
               "negative when bullish (price must fall to the lower edge)."),
    "flip": ("Time since flip",
             "Time since the trend last flipped on the selected timeframe. “> Nd” means the flip is "
             "older than the scan window, so the age is unknown."),
    "flips": ("Flips",
              "Number of trend flips inside the scan window for the selected timeframe "
              "(60 days on 1H/4H, 150 on 12H, about 300 on Daily, 41 weeks on Weekly)."),
    "rsVsBtc": ("RS vs BTC",
                "Token price change since flip minus BTC’s change over the same stretch as a %. "
                "Positive means it beat BTC. Blank for flips older than the scan window or when "
                "BTC’s history doesn’t reach back to the flip."),
}
LABELS = {"pct": "Δ SINCE FLIP", "toFlip": "TO FLIP", "flip": "TIME SINCE FLIP",
          "flips": "FLIPS", "rsVsBtc": "RS VS BTC"}


def _js():
    with open(os.path.join(ROOT, "static", "trends.js"), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def _tips_block(js):
    return _between(js, "const TRENDS_COLUMN_TIPS = {", "const TRENDS_COL_TIP_WIDTH")


def _component(js):
    return _between(js, "function TrendsHeaderTip(", "/* ── sub-table (A2: expandable row accordion) ── */")


def _main_table(js):
    return _between(js, "function TrendsTable(", "/* ── respected trend tab (Landing 50c) ── */")


def _sub_table(js):
    return _between(js, "function TrendsSubTable(", "/* ── stats strip ── */")


def test_five_texts_are_exact():
    block = _tips_block(_js())
    for key, (title, body) in TIPS.items():
        want = NL.join(["  %s: {" % key, "    title: '%s'," % title, "    body: '%s'," % body, "  },"])
        assert want in block, key
    assert block.count("title:") == 5 and block.count("body:") == 5


def test_main_table_header_wiring():
    table = _main_table(_js())
    for key, label in LABELS.items():
        # the sort key and the tip key are the same word for all five columns
        assert "sortableTh('%s', '%s', TRENDS_COLUMN_TIPS.%s)," % (label, key, key) in table, key
    # the other columns keep their plain headers
    for plain in ["sortableTh('#', 'rank'),", "sortableTh('TOKEN', 'symbol'),", "sortableTh('TREND', 'trend'),",
                  "sortableTh('ALIGNMENT (EMA)', 'alignment'),", "sortableTh('PRIOR ALIGNMENT', 'priorAlignment'),",
                  "sortableTh('PRICE', 'price'),", "sortableTh('VOLUME 24H', 'volume'),"]:
        assert plain in table, plain
    assert "const sortableTh = (txt, key, tip) => {" in table
    assert "const props = { onClick: () => cycleSort(key), style: thStyle(key) };" in table
    assert "? React.createElement('th', props, React.createElement(TrendsHeaderTip, { tip, text: txt, arrow }))" in table
    assert ": React.createElement('th', props, txt, arrow);" in table
    assert "const arrow = sort.key === key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : '';" in table


def test_sub_table_header_wiring():
    sub = _sub_table(_js())
    for key, label in LABELS.items():
        assert ("React.createElement(TrendsHeaderTip, { tip: TRENDS_COLUMN_TIPS.%s, text: '%s', arrow: '' })"
                % (key, label)) in sub, key
    assert sub.count("React.createElement(TrendsHeaderTip,") == 5


def test_sidebar_tip_component_is_left_alone():
    js = _js()
    side = _between(js, "function TrendsTip({ tip, block, children }) {", "function TrendsChipToggle(")
    assert "TrendsHeaderTip" not in side and "createPortal" not in side
    assert "TRENDS_COLUMN_TIPS" not in _between(js, "const TRENDS_TIPS = {", "const TRENDS_COLUMN_TIPS")


def test_header_tip_behaviour_is_wired():
    js = _js()
    comp = _component(js)
    # opens: mouse hover after the same pause the sidebar uses, never on touch
    assert "timerRef.current = setTimeout(show, TRENDS_TIP_DELAY_MS);" in comp
    assert "function onPointerEnter(e) {" + NL + "    if (e.pointerType === 'touch') return;" in comp
    assert "function onPointerLeave(e) {" + NL + "    if (e.pointerType === 'touch') return;" + NL + "    hide();" in comp
    assert "React.createElement('span', { ref: wrapRef, onPointerEnter, onPointerLeave }," in comp
    # the "i": a click or tap toggles it and never reaches the <th> (no sort)
    assert "function onInfoClick(e) {" + NL + "    e.stopPropagation();" in comp
    assert "if (anchor) hide(); else show();" in comp
    assert "onClick: onInfoClick, onFocus: onInfoFocus, onBlur: hide," in comp
    assert "if (t && t.matches && t.matches(':focus-visible')) show();" in comp
    assert "'aria-label': 'About ' + tip.title, 'aria-describedby': open ? id : undefined," in comp
    # closes: Escape, press elsewhere, resize, later scroll
    assert "if (e.key === 'Escape') hide();" in comp
    assert "document.addEventListener('pointerdown', onDown, true);" in comp
    assert "window.addEventListener('resize', hide);" in comp
    assert "window.addEventListener('scroll', onScroll, true);" in comp
    assert "if (Date.now() - openedAtRef.current < TRENDS_COL_TIP_SETTLE_MS) measure(); else hide();" in comp
    assert "const TRENDS_COL_TIP_SETTLE_MS = 250;" in js
    assert "const TRENDS_COL_TIP_WIDTH = 280;" in js
    # drawn on document.body, fixed, kept inside the viewport
    assert "ReactDOM.createPortal(" in comp and "      document.body" + NL in comp
    assert "position: 'fixed', zIndex: 1000," in comp
    assert "id, role: 'tooltip', className: 'trends-col-tip'," in comp
    assert "const left = Math.min(Math.max(8, anchor.left), vw - width - 8);" in comp
    assert "if (top + h > vh - 8 && anchor.top - 6 - h >= 8) top = anchor.top - 6 - h;" in comp
    assert "const width = Math.min(TRENDS_COL_TIP_WIDTH, vw - 16);" in comp
    # the "i" stays with the last word of the label
    assert "const cut = text.lastIndexOf(' ') + 1;" in comp
    # text size follows the visibility standard (13px body)
    assert "fontSize: 13, lineHeight: 1.45," in comp
    assert "pointerEvents: 'none'," in comp
