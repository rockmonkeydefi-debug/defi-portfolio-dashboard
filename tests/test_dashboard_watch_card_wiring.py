"""Landing 92: the Watch List card on the Dashboard (source-text checks; the behaviour is checked by the
headless-browser runs).

- static/dashboard.js: DashWatchCard in row 4's third slot, fed by GET /api/watchlist and /api/watchlist/prices
  (added to the Dashboard's load and Refresh). The first 6 active tokens in the server's order, "+N more", each row
  read with the Watch List page's own helpers; the plan summary is the hover text and is hidden with Hide values;
  a token opens the Watch List with its row open (watchListExpanded) and a one-time window.__watchListJump.
- static/watchlist.js: WatchListScreen reads the jump once, opens that row, scrolls it into view and focuses it.
- static/style.css: row 4 is three columns from 1280px; between 768 and 1279px two, the card spanning both.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LENDING_HEAD = "/* " + chr(0x2500) * 2 + " ROW 1 Right: Lending card"


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _body(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]


def test_the_card_is_in_row_four_with_its_loads():
    js = _read("static/dashboard.js")
    row4 = js[js.index('<div className="dash-row4">'):]
    row4 = row4[:row4.index("</div>")]
    order = [row4.index(x) for x in ("<DashBtcCard ", "<DashLendingCard ", "<DashWatchCard ")]
    assert order == sorted(order)
    assert ("<DashWatchCard model={watchModel} prices={watchPrices} hideValues={hideValues} onOpen={onOpenWatch} "
            "onOpenToken={onOpenWatchToken} />") in row4
    fetch_all = _body(js, "const fetchAll = useDashCallback(", "useDashEffect(() => { fetchAll(); }, []);")
    assert "load('/api/watchlist', d => setWatch(prev =>" in fetch_all
    assert "load('/api/watchlist/prices', d => setWatchPrices(prev =>" in fetch_all
    assert "prev.status === 'ok' ? prev : { status: 'error', data: null }" in fetch_all     # a failed refresh keeps the card


def test_the_card_shows_six_active_tokens_in_the_server_order():
    js = _read("static/dashboard.js")
    assert "const DASH_WATCH_MAX = 6;" in js
    model = _body(js, "function _dashWatchModel(watch, nowMs) {", "function DashWatchCard(")
    assert "const active = (watch.data.items || []).filter(i => i && i.active);" in model
    assert "more: Math.max(0, active.length - DASH_WATCH_MAX)" in model
    assert "rows: active.slice(0, DASH_WATCH_MAX)" in model
    assert "sort(" not in model                                         # the server's order (priority, then added)
    # the Watch List page's own helpers, so both read the same
    for h in ("wlTrendSource(item)", "wlRespected(source.tfs, nowMs)"):
        assert h in model
    card = _body(js, "function DashWatchCard(", LENDING_HEAD)
    for h in ("wlPriceView(item, live[item.key])", "<WlTrendDots tfs={source.tfs} source={source} name={item.name} />",
              "WL_TF_LABEL[best.tf]", "wlCleanSummary(item.summary)"):
        assert h in card
    assert "{'+' + model.more + ' more'}" in card
    assert "'No active tokens on the Watch List yet.'" in card and "'Watch List unavailable'" in card


def test_hide_values_hides_the_plan_and_keeps_prices():
    js = _read("static/dashboard.js")
    card = _body(js, "function DashWatchCard(", LENDING_HEAD)
    assert "const plan = !hideValues && item.summary ? wlCleanSummary(item.summary) : '';" in card
    assert "title={plan ? 'Plan: ' + plan : undefined}" in card
    assert card.count("hideValues") == 2                                # the prop and the plan line only


def test_a_token_opens_its_row_on_the_watch_list():
    js = _read("static/dashboard.js")
    go = _body(js, "  const onOpenWatchToken = (key) => {", "  const watchModel = ")
    assert "if (open.indexOf(key) === -1) wlWriteExpanded(open.concat([key]));" in go
    assert "window.__watchListJump = key;" in go and "onOpenWatch();" in go
    assert "const onOpenWatch = () => { setActiveTab && setActiveTab('watchlist'); };" in js
    wl = _read("static/watchlist.js")
    assert "const k = window.__watchListJump;" in wl and "window.__watchListJump = undefined;" in wl
    assert "return typeof k === 'string' && WL_KEY_RE.test(k) ? k : null;" in wl
    jump = _body(wl, "  useWLEffect(() => {\n    if (!jumpKey || state.status !== 'ok') return;", "}, [jumpKey, state.status]);")
    assert "setJumpKey(null);" in jump                                  # once
    assert "row.scrollIntoView({ block: 'start', behavior: 'auto' });" in jump
    assert "if (t) t.focus({ preventScroll: true });" in jump
    # the row is held in place while the open rows above it load, unless you scroll or press a key
    assert "const WL_JUMP_HOLD_MS = 2500;" in wl
    assert "['wheel', 'touchstart', 'keydown', 'mousedown'].forEach(ev => window.addEventListener(ev, stop, true));" in jump
    assert "if (Math.abs(row.getBoundingClientRect().top - at) > 4) row.scrollIntoView({ block: 'start', behavior: 'auto' });" in jump
    # the helpers the Dashboard reaches into stay where it expects them
    for name in ("function wlReadExpanded()", "function wlWriteExpanded(keys)", "function wlTrendSource(item)",
                 "function wlRespected(tfs, nowMs)", "function wlPriceView(item, live)", "function WlTrendDots(",
                 "function wlCleanSummary(s)", "const WL_TF_LABEL = ", "const WL_DIR_LABEL = "):
        assert name in wl, name


def test_row_four_layout():
    css = re.sub(r"/[*].*?[*]/", "", _read("static/style.css"), flags=re.S)
    assert ".dash-row4 { display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:16px; align-items:stretch; }" in css
    mid = css[css.index("@media (max-width:1279px) and (min-width:768px) {"):]
    mid = mid[:mid.index("}\n}") + 1] if "}\n}" in mid else mid
    assert ".dash-row4 { grid-template-columns:repeat(2, minmax(0,1fr)); }" in mid
    assert ".dash-row4 > .dash-watch { grid-column:1 / -1; }" in mid
    assert ".wl-row { scroll-margin-top:12px; }" in css
    assert ".dash-watch-row:focus-visible { outline:2px solid var(--dash-accent); outline-offset:2px; }" in css
