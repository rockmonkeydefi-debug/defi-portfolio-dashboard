"""Landing 31: the page side of tabs on the Notes page (static/notebook.js).
The tab bar comes from GET /api/note-tabs; "+ New tab", "Tab options"
(rename, move left / right, archive) and "Archived (N)" (restore) call the
tab routes, and every reply carries the whole tab list. No browser here:
these read the source files (the headless checks for the landing exercise
the behaviour).
"""
import os
import re

import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _routes():
    return {(r.rule, m) for r in wp.app.url_map.iter_rules() for m in r.methods}


def test_the_default_tabs_equal_the_servers():
    src = _read("static/notebook.js")
    tabs = re.findall(r"\{ id: '(\w+)', page: '([\w-]+)', label: '([^']+)' \}", src)
    assert [(p, label) for _, p, label in tabs] == list(wp.NOTE_TAB_DEFAULTS)
    # The ids are what browsers remembered before Landing 31.
    assert [i for i, _, _ in tabs] == ["watchlist", "nuggets"]


def test_the_limits_equal_the_servers():
    src = _read("static/notebook.js")
    assert f"const NB_LABEL_MAX = {wp.NOTE_TAB_LABEL_MAX};" in src
    assert f"const NB_ACTIVE_MAX = {wp.NOTE_TABS_ACTIVE_MAX};" in src
    # The server's reply carries its own limits, which win when present.
    assert "(list.limits && list.limits.label_max) || NB_LABEL_MAX" in src
    assert "(list.limits && list.limits.active_max) || NB_ACTIVE_MAX" in src


def test_every_route_the_page_calls_exists():
    src = _read("static/notebook.js")
    routes = _routes()
    assert "nbRequest('GET', '/api/note-tabs', undefined, NB_LIST_TIMEOUT_MS)" in src and ("/api/note-tabs", "GET") in routes
    assert "write('POST', '/api/note-tabs', { label })" in src and ("/api/note-tabs", "POST") in routes
    assert "write('PUT', '/api/note-tabs/order', { keys })" in src and ("/api/note-tabs/order", "PUT") in routes
    assert src.count("write('PUT', '/api/note-tabs/' + encodeURIComponent(") == 3
    assert ("/api/note-tabs/<key>", "PUT") in routes
    assert "{ archived: true }" in src and "{ archived: false }" in src


def test_a_tab_is_remembered_by_its_key_and_old_ids_still_work():
    src = _read("static/notebook.js")
    assert "const NB_TAB_KEY = 'notesTab';" in src
    assert "const legacy = NB_DEFAULT_TABS.find(t => t.id === v);" in src
    assert "return legacy ? legacy.page : v;" in src
    assert "localStorage.setItem(NB_TAB_KEY, page)" in src
    # A remembered tab that is gone (archived) falls back to the first open tab.
    assert "const current = active.find(t => t.page === want) || active[0] || null;" in src


def test_every_reply_replaces_the_tab_list():
    src = _read("static/notebook.js")
    assert "if (res.data && Array.isArray(res.data.tabs)) setList({ status: 'ok', ...nbFromReply(res.data) });" in src


def test_a_tab_with_unsaved_edits_cant_be_archived():
    src = _read("static/notebook.js")
    # Shown when the question opens; checked at the click (saving below the
    # question doesn't redraw it, so the button isn't disabled for it).
    assert "const dirty = hasDraft(current.page);" in src
    assert "disabled={last} onClick={archiveTab}>Archive tab</button>" in src
    assert "if (hasDraft(current.page)) {" in src
    # Archive's question opens with the focus on Cancel, not on Archive: the
    # marked element first, whatever comes before it in the panel.
    assert 'data-nb-first="" onClick={closeBox}>Cancel</button>' in src
    assert "boxRef.current.querySelector('[data-nb-first]') || boxRef.current.querySelector(" in src


def test_the_leave_warning_covers_every_tab_archived_ones_too():
    src = _read("static/notebook.js")
    # Another window may archive a tab with unsaved edits here.
    assert "const pagesKey = tabs.map(t => t.page).join('|');" in src
    assert "[pagesKey]);" in src
    assert "hasDraft(t.page) && <span className=\"nb-unsaved\">unsaved edits: restore it to save them</span>" in src
    assert "const archivedDraft = archived.some(t => hasDraft(t.page));" in src


def test_the_tab_list_read_times_out_into_the_default_tabs():
    src = _read("static/notebook.js")
    assert "const NB_LIST_TIMEOUT_MS = 10000;" in src
    assert "nbRequest('GET', '/api/note-tabs', undefined, NB_LIST_TIMEOUT_MS)" in src
    assert "signal: ctrl ? ctrl.signal : undefined" in src and "setTimeout(() => ctrl.abort(), timeoutMs)" in src


def test_try_again_keeps_the_shown_tab():
    src = _read("static/notebook.js")
    assert "if (current) setWant(current.page);" in src
    assert "onClick={retry}>" in src
    # The list is not blanked while asking, so an open editor stays mounted.
    assert "setList({ status: 'loading'" not in src


def test_the_open_tabs_panel_closes_when_its_tab_leaves_the_bar():
    src = _read("static/notebook.js")
    assert "&& (!box.page || box.page === current.page);" in src
    assert "page: NB_TAB_MODES.includes(mode) && current ? current.page : null" in src
    # It closes with a note saying why, unless this window archived the tab itself.
    assert "if (box && box.page && shownPage && box.page !== shownPage) {" in src
    assert "was archived in another window. Restore it from Archived." in src
    assert "setBox(prev => (prev ? { ...prev, page: null } : prev));" in src
    # aria-controls only names the panel while it is shown; aria-expanded is always true or false.
    assert src.count("aria-controls={boxFor(") == 3 and 'aria-controls="nb-box"' not in src
    assert "const boxFor = m => !!(showBox &&" in src


def test_a_failed_tab_read_shows_the_default_tabs_without_tools():
    src = _read("static/notebook.js")
    assert "const fallback = list.status === 'error';" in src
    assert "fallback ? NB_DEFAULT_TABS.map(" in src
    assert "{!fallback && <button" in src and "{!fallback && <div className=\"nb-tools\">" in src


def test_the_styles_exist():
    css = _read("static/style.css")
    for rule in (".nb-bar {", ".nb-tab {", ".nb-tab-label {", ".nb-tools {", ".nb-box {", ".nb-field input {",
                 ".nb-count {", ".nb-archived li {"):
        assert rule in css, rule
    # A long name is cut on one line; the full name is the hover.
    assert ".nb-tab-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" in css


def test_the_tabs_are_a_left_column_on_wide_screens():
    """Landing 35: from NB_SIDE_QUERY the tabs and their tools (nb-side) sit
    left of the note (nb-main); the JS query and the CSS media query are the
    same width, and the column's sticky offset follows the menu's dock width."""
    src = _read("static/notebook.js")
    css = _read("static/style.css")
    nav = _read("static/nav.js")
    assert "const NB_SIDE_QUERY = '(min-width: 900px)';" in src
    assert "@media (min-width: 900px) {\n  .nb-layout { display: grid; grid-template-columns: 220px minmax(0, 1fr);" in css
    # The tabs come first (keyboard order: tabs, tools, then the panel and the note).
    assert src.index('className="nb-side"') < src.index('className="nb-main"') < src.index('id="nb-box"')
    # Moving a tab reads up / down in the column, left / right in the row.
    assert "{side ? 'Move up' : 'Move left'}" in src and "{side ? 'Move down' : 'Move right'}" in src
    # A long name wraps in the column (the row still cuts it, test_the_styles_exist).
    assert ".nb-side .nb-tab-label { white-space: normal; overflow-wrap: anywhere; }" in css
    # Below the 48px top bar until the menu docks, then near the top.
    assert ".nb-side { position: sticky; top: 64px;" in css
    assert "const NAV_DOCK_QUERY = '(min-width: 1880px)';" in nav
    assert "@media (min-width: 1880px) {\n  .nb-side { top: 16px;" in css
