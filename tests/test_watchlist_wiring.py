"""Landing 78: how static/watchlist.js is wired - the menu item, the app
route, the script order, the shared globals it reads, the endpoints it calls,
and the rules a script in this app has to keep (names, ASCII). Source-level
checks in the style of the other wiring tests; behaviour is checked in a
headless browser, not here.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _between(text, start, end):
    assert start in text, start
    rest = text.split(start, 1)[1]
    assert end in rest, end
    return rest.split(end, 1)[0]


JS = _read("static/watchlist.js")


def test_the_menu_lists_the_page_in_the_trading_group_with_an_icon():
    nav = _read("static/nav.js")
    assert "{ id: 'watchlist',          label: 'Watch List' }," in nav
    assert "ids: ['spot', 'perps', 'trends', 'watchlist', 'notes', 'tt'] }," in nav
    assert re.search(r"^  'watchlist': 'M[^']+',$", nav, re.M)
    assert "'tt-watchlist'" in nav            # the old hidden Trading Tools page keeps its own id


def test_the_app_shows_the_screen_with_an_error_boundary_and_the_wide_layout():
    app = _read("static/app.js")
    assert "  watchlist:   'Watch List'," in app
    branch = _between(app, "activeTab === 'watchlist')", "// Landing 24")
    assert "React.createElement(window.ErrorBoundary || React.Fragment, null," in branch
    assert "React.createElement(window.WatchListScreen, { hideValues, refreshTrigger })" in branch
    assert "+ (activeTab === 'watchlist' ? ' tv-content--notes' : '')" in app
    assert "+ (activeTab === 'notes' ? ' tv-content--notes' : '')" in app          # the Notes page's own line is untouched


def test_the_script_loads_after_everything_it_reads_and_before_the_app():
    html = _read("templates/index.html")
    order = [m.group(1) for m in re.finditer(r'/static/([a-z0-9]+)\.js\?v=', html)]
    at = order.index("watchlist")
    for earlier in ("utils", "pagenotes", "spotpnl", "trends", "dashboard"):
        assert order.index(earlier) < at, earlier
    assert at < order.index("app")


def test_every_global_it_reads_is_defined_where_it_expects():
    where = {
        "static/spotpnl.js": ["const SPOT_TREND_TFS =", "const SPOT_TREND_WORD =", "function SpotTrendDot("],
        "static/trends.js": ["function _trendsRespectCell(", "function _trendsFmtRespectedFor("],
        "static/pagenotes.js": ["function pnSavedLabel(", "window.PageNotesPanel = PageNotesPanel;",
                                "window.PageNotesHasDraft = pnHasDraft;", "window.PageNotesShowPages = pnShowPages;",
                                "return typeof page === 'string' && page.startsWith('notes-');"],
        "static/utils.js": ["window.fmtTokenPrice = fmtTokenPrice;"],
        "static/dashboard.js": ["window.ImageStorageMeter = ImageStorageMeter;"],
    }
    for rel, needles in where.items():
        text = _read(rel)
        for n in needles:
            assert n in text, (rel, n)


def test_the_note_key_is_the_one_the_server_uses_and_keeps_the_notes_prefix():
    py = _read("web_portfolio.py")
    assert 'return isinstance(page, str) and page.startswith("notes-")' in py      # images in the item's notes
    assert '_WATCH_KEY_RE = re.compile(r"notes-w([1-9][0-9]{0,5})")' in py
    assert "const WL_KEY_RE = /^notes-w[1-9][0-9]{0,5}$/;" in JS
    assert "page={item.key}" in JS


def test_the_page_calls_only_routes_that_exist():
    py = _read("web_portfolio.py")
    calls = set(re.findall(r"'(/api/watchlist[^']*)'", JS))
    assert calls == {"/api/watchlist", "/api/watchlist/prices", "/api/watchlist/", "/api/watchlist/"}, calls
    for route in ("@app.route('/api/watchlist', methods=['GET'])", "@app.route('/api/watchlist/prices', methods=['GET'])",
                  "@app.route('/api/watchlist', methods=['POST'])", "@app.route('/api/watchlist/<key>', methods=['PUT'])",
                  "@app.route('/api/watchlist/<key>/check', methods=['POST'])",
                  "@app.route('/api/watchlist/<key>/delete-preview', methods=['GET'])",
                  "@app.route('/api/watchlist/<key>', methods=['DELETE'])"):
        assert route in py, route
    assert "'/api/watchlist/' + key + '/check'" in JS and "'PUT', '/api/watchlist/' + key" in JS
    assert "wlRequest('POST', '/api/watchlist', body)" in JS


def test_polling_timeouts_and_the_old_check_age():
    assert "const WL_PRICE_POLL_MS = 120000;" in JS
    assert "const WL_CHECK_TIMEOUT_MS = 90000;" in JS
    assert "const WL_CHECK_OLD_MS = 24 * 3600 * 1000;" in JS
    assert "document.visibilityState === 'visible'" in JS          # no polling from a background tab


def test_a_kilo_market_never_supplies_a_price():
    body = _between(JS, "function wlPriceView(", NL + "}" + NL)
    assert "const kilo = " in body and "&& !kilo" in body
    assert "String(sc.scanner_symbol).toUpperCase() !== String(item.name).trim().toUpperCase()" in body


def test_the_screen_guards_every_items_notes_and_an_unsaved_summary():
    assert "window.PageNotesShowPages(allKeys.split(','))" in JS
    assert "window.addEventListener('beforeunload', warn);" in JS and "window.removeEventListener('beforeunload', warn);" in JS
    assert "window.PageNotesHasDraft(item.key)" in JS


def test_hide_values_hides_the_summary_and_the_notes():
    assert "hideValues ? <span className=\"wl-muted\">{WL_MASK}</span>" in JS
    assert "hideValues={hideValues} label={item.name + ' notes'} variant=\"page\"" in JS


def test_delete_is_one_request_to_one_route_after_a_confirmation_with_real_counts():
    assert JS.count("'DELETE'") == 1 and "wlRequest('DELETE', '/api/watchlist/' + key," in JS
    assert "keepIds && keepIds.length ? { keep_image_ids: keepIds } : undefined" in JS
    sec = _between(JS, "function WlTokenSection(", NL + "}" + NL)
    assert "const previewPath = '/api/watchlist/' + item.key + '/delete-preview';" in sec
    assert "wlRequest('GET', previewPath)" in sec                    # the usage line
    assert "wlRequest('GET', previewPath + (keepIds.length ? '?keep=' + keepIds.join(',') : ''))" in sec   # a fresh read for the question
    assert "Delete {item.name} permanently?" in sec and "This can't be undone." in sec
    assert 'role="alertdialog"' in sec and ">Keep</button>" in sec and "Delete permanently" in sec
    assert "if (confirm.step === 'ready' && keepRef.current) keepRef.current.focus();" in sec      # opens on the safe button
    assert "e.key === 'Escape' && (confirm.step === 'ready' || confirm.step === 'error')" in sec
    assert "delBtnRef.current && !delBtnRef.current.disabled ? delBtnRef.current" in sec      # focus back to Delete token, else the row
    assert "if (confirm.step === 'error' && retryRef.current) retryRef.current.focus();" in sec
    assert "const blocked = checking || busy;" in sec and "disabled={confirm.step === 'deleting' || blocked}" in sec   # not while a check runs
    assert "if (confirm.step !== 'ready') return;" in sec                                       # no double submit
    assert "Export DB" in sec
    assert "{draft ? ' Your unsaved note edits will be lost too.' : ''}" in sec


def test_a_failed_preview_never_leaves_a_way_to_delete():
    sec = _between(JS, "function WlTokenSection(", NL + "}" + NL)
    err = _between(sec, "confirm.step === 'error' &&", "</div>}")
    assert "Delete permanently" not in err and "Try again" in err and "Keep" in err


def test_after_a_delete_the_page_drops_every_trace_and_refreshes_the_meter():
    fn = _between(JS, "async function deleteItem(key, keepIds) {", NL + "  }" + NL)
    assert "res.status === 404" in fn and "load();" in fn and "prev.data.items.filter(i => i.key !== key)" in fn
    assert "The server didn't confirm the delete. Reload the page to see whether it went through." in fn
    for needle in ("setExpandedFor(key, false);", "setDraftFor(key, undefined);", "setMeterKey(k => k + 1);",
                   "' was deleted. '", "Freed ", "No images were freed."):
        assert needle in fn, needle
    assert "button.primary" in fn


def test_the_script_is_ascii_and_every_top_level_name_has_the_prefix():
    assert JS.isascii()
    names = re.findall(r"^(?:function|const|let|var|async function)\s+([A-Za-z_$][\w$]*)", JS, re.M)
    assert names, "no top-level names found"
    bad = [n for n in names if not re.match(r"^(wl|WL_|Wl|WatchListScreen$)", n)]
    assert bad == [], bad


def test_no_other_script_defines_a_name_this_one_does():
    mine = set(re.findall(r"^(?:function|const|let|var|async function)\s+([A-Za-z_$][\w$]*)", JS, re.M))
    mine.discard("useWLState")
    for fn in sorted(os.listdir(os.path.join(ROOT, "static"))):
        if not fn.endswith(".js") or fn == "watchlist.js":
            continue
        other = _read("static/" + fn)
        for n in sorted(mine):
            assert not re.search(r"^(?:function|const|let|var|async function)\s+" + re.escape(n) + r"\b", other, re.M), (fn, n)


def test_the_stylesheet_has_the_rules_the_page_relies_on():
    css = _read("static/style.css")
    for sel in (".wl-page {", ".wl-head {", ".wl-body[hidden] {", ".wl-list[hidden] {", ".wl-c-active input {"):
        assert sel in css, sel
    assert ".wl-body .pn-panel--page .pn-head--sticky { position:static; }" in css
    assert ".wl-row .tv-chip { font-size:12px; }" in css
    assert ".wl-trend-table thead th { font-size:12px;" in css
    # a border or separator is never fainter than the app's own line colour
    for m in re.finditer(r"\.wl-[a-z-]+[^{]*\{[^}]*border[^}]*\}", css):
        assert "rgba(255,255,255,0.1" not in m.group(0), m.group(0)


def test_summary_drafts_live_in_the_screen_and_a_save_only_clears_what_it_sent():
    assert "const [drafts, setDrafts] = useWLState({});" in JS
    assert "draftRaw={drafts[item.key]} onDraft={(v, same) => setDraftFor(item.key, v, same)}" in JS
    save = _between(JS, "async function saveSummary() {", NL + "  }" + NL)
    assert "const sent = draftRaw;" in save and "onDraft(sent, true)" in save
    fn = _between(JS, "function setDraftFor(key, value, clearIfSame) {", NL + "  }" + NL)
    assert "d[key] === value ? drop() : d" in fn
    assert "useWLState(item.summary)" not in JS            # no row-local copy that a remount would lose


def test_the_trend_source_is_the_fresher_of_the_scanner_and_the_saved_check():
    body = _between(JS, "function wlTrendSource(", NL + "}" + NL)
    assert "return isFinite(c) && (!isFinite(s) || c > s) ? ck : sc;" in body
    assert "hasRows(item.scanner.timeframes)" in body        # a scanner match without rows doesn't hide a saved check


def test_an_older_list_read_never_overwrites_a_newer_reply():
    assert "const seen = mutationsRef.current;" in JS
    assert "mutationsRef.current !== seen" in JS
    assert JS.count("mutationsRef.current += 1;") == 3        # a list reply, a saved check, a delete that found it gone


def test_toggling_active_announces_and_keeps_the_keyboard_place():
    body = _between(JS, "async function patchItem(", NL + "  }" + NL + NL)
    assert "' is active again.' : ' moved to Inactive.'" in body
    assert "'button.wl-sec-toggle'" in body and ".wl-c-active input" in body
    assert 'className="wl-flash" role="status"' in JS


def test_the_toggle_points_at_a_body_only_once_it_exists():
    assert "aria-controls={opened ? body : undefined}" in JS


def test_the_page_gives_up_after_the_prices_route_does():
    assert "const WL_REQUEST_TIMEOUT_MS = 20000;" in JS
    assert "const WL_CHECK_TIMEOUT_MS = 90000;" in JS


def test_images_in_unsaved_drafts_elsewhere_are_kept():
    fn = _between(JS, "function wlDraftImageIds(exceptKey) {", NL + "}" + NL)
    assert "typeof pnDrafts === 'undefined'" in fn and "page === exceptKey" in fn
    assert "/\\/api\\/note-images\\/([1-9][0-9]{0,9})/g" in fn and ".slice(0, 2000)" in fn
    assert "const pnDrafts = {};" in _read("static/pagenotes.js")
    sec = _between(JS, "function WlTokenSection(", NL + "}" + NL)
    assert "const keepIds = wlDraftImageIds(item.key);" in sec and "await onDelete(confirm.keep)" in sec
    assert "will stay because an unsaved note elsewhere in this browser uses" in sec


def test_the_question_only_names_what_the_token_has():
    sec = _between(JS, "function WlTokenSection(", NL + "}" + NL)
    assert "item.summary ? 'its plan summary' : null, item.check ? 'its saved trend' : null" in sec
    assert "', counting every saved version ('" in sec


def test_priority_list_in_each_row_and_in_add():
    import web_portfolio as wpm
    assert "const WL_PRIORITIES = [['high', 'High'], ['medium', 'Medium'], ['low', 'Low']];" in JS
    assert [p for p, _ in re.findall(r"\['(\w+)', '(\w+)'\]", _between(JS, "const WL_PRIORITIES = ", ";"))] == list(wpm.WATCH_PRIORITIES)
    row = _between(JS, "function WlItemRow(", NL + "}" + NL)
    assert "aria-label={'Priority of ' + item.name}" in row and "onPatch({ priority: v })" in row
    assert row.index('className="wl-c-name"') < row.index('className="wl-c-prio"') < row.index('className="wl-c-price')
    form = _between(JS, "function WlAddForm(", NL + "}" + NL)
    assert "useWLState('medium')" in form and "contract: contract.trim(), priority })" in form
    assert 'id="wl-add-priority"' in form


def test_a_priority_change_that_moves_the_row_says_where_it_went_and_keeps_focus():
    fn = _between(JS, "async function patchItem(key, body) {", NL + "  }" + NL)
    assert "if (it && at !== before) showFlash(" in fn and "' in Watching.'" in fn
    assert "'[data-key=\"' + key + '\"] .wl-prio'" in fn


def test_the_priority_chip_styles():
    css = _read("static/style.css")
    # Landing 82a: High is light green, the chip is about 20% smaller (12px text, the grid-text floor)
    assert ".wl-prio--high { background:#a7f0c4; color:var(--bg); border:1px solid #a7f0c4; }" in css
    assert ".wl-prio { font:inherit; font-size:12px; font-weight:600; min-height:26px; padding:2px 5px;" in css
    assert ".wl-prio--medium { background:transparent; color:var(--text); border:1px solid var(--accent-line); }" in css
    assert ".wl-prio--low { background:transparent; color:var(--text3); border:1px solid rgba(255,255,255,0.3);" in css
    assert "grid-template-areas:\"name prio active\"" in css and ".wl-c-prio { grid-area:prio; }" in css


def test_the_chip_sits_between_the_name_and_the_price_and_the_intro_text_is_gone():
    css = _read("static/style.css")
    # Landing 82a: the name column gives up width to a flexible priority column, so the chip
    # (left in its column) lands midway between a typical name and the price at 1920px
    assert ".wl-head { display:grid; grid-template-columns:minmax(150px,0.9fr) minmax(100px,0.7fr) 104px 170px minmax(150px,1fr) minmax(200px,2fr) 96px;" in css
    assert "wl-sub" not in JS and ".wl-sub" not in css
    assert "Tokens you are watching but don't hold" not in JS
    top = _between(JS, '<div className="wl-top">', '<div className="wl-meter">')
    assert '<div className="tv-page-title">Watch List</div>' in top
