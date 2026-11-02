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


def test_the_notes_page_is_as_wide_as_spot_without_the_maxfi_rules():
    """Landing 36: the Notes page gets its own 1700px container class, not
    tv-content--wide (whose MaxFi focus rule would turn its focus rings teal)."""
    app = _read("static/app.js")
    css = _read("static/style.css")
    assert "+ (activeTab === 'notes' ? ' tv-content--notes' : '')" in app
    assert "activeTab === 'maxfi' || activeTab === 'spot' || activeTab === 'perps' ? ' tv-content--wide'" in app
    assert ".tv-content.tv-content--notes { max-width: 1700px; }" in css
    assert ".tv-content.tv-content--wide { max-width: 1700px; }" in css


def test_copy_tab_is_in_tab_options_and_calls_its_route():
    src = _read("static/notebook.js")
    assert ("/api/note-tabs/<key>/copy", "POST") in _routes()
    assert "const NB_TAB_MODES = ['options', 'rename', 'archive', 'copy', 'delete'];" in src   # delete: Landing 83
    options = src.split("if (box.mode === 'options') {", 1)[1].split("if (box.mode === 'archive') {", 1)[0]
    assert "onClick={() => copyTab(false)}" in options and ">Copy tab</button>" in options
    assert "disabled={full || busy}" in options
    assert options.index("Move right") < options.index("Copy tab") < options.index("Archive")
    fn = src.split("async function copyTab(confirmed) {", 1)[1].split("\n  }\n", 1)[0]
    assert "if (!confirmed && hasDraft(current.page)) { switchBox('copy'); return; }" in fn
    assert "write('POST', '/api/note-tabs/' + encodeURIComponent(current.page) + '/copy')" in fn
    assert "show(data.key);" in fn and "setFocusReq({ tab: data.key });" in fn


def test_copy_with_unsaved_edits_asks_first():
    src = _read("static/notebook.js")
    q = src.split("if (box.mode === 'copy') {", 1)[1].split("if (box.mode === 'archived') {", 1)[0]
    assert "The copy takes the last saved version of its notes, not your unsaved edits." in q
    assert "onClick={() => copyTab(true)}>Copy saved version</button>" in q and 'data-nb-first=""' in q


def test_the_copy_word_and_limits_match_the_name_rules():
    assert wp.NOTE_TAB_COPY_WORD == "copy"
    assert wp._note_tab_copy_label("Setups", []) == "Setups (copy)"
    assert len(wp._note_tab_copy_label("y" * 40, [])) == wp.NOTE_TAB_LABEL_MAX


# -- Delete a tab (Landing 83) ------------------------------------------------------------

def _fn(src, head):
    return src.split(head, 1)[1].split("\n  }\n", 1)[0]


def test_delete_routes_exist_and_the_keep_limit_matches():
    src = _read("static/notebook.js")
    assert ("/api/note-tabs/<key>", "DELETE") in _routes() and ("/api/note-tabs/<key>/delete-preview", "GET") in _routes()
    assert "const NB_KEEP_IDS_MAX = %d;" % wp.WATCH_KEEP_IDS_MAX in src
    assert "const NB_DELETE_ARCHIVED = 'delete-archived';" in src


def test_delete_is_in_tab_options_after_archive():
    src = _read("static/notebook.js")
    options = src.split("if (box.mode === 'options') {", 1)[1].split("if (box.mode === 'archive') {", 1)[0]
    assert "onClick={() => startDelete(current, 'delete')}>{'Delete\\u2026'}</button>" in options
    assert options.index("Archive") < options.index("startDelete(current, 'delete')") < options.index(">Close</button>")


def test_each_archived_tab_has_delete_next_to_restore():
    src = _read("static/notebook.js")
    arch = src.split("if (box.mode === 'archived') {", 1)[1].split("return null;", 1)[0]
    assert "aria-label={'Delete the ' + t.label + ' tab'}" in arch
    assert "onClick={() => startDelete(t, NB_DELETE_ARCHIVED)}>{'Delete\\u2026'}</button>" in arch
    assert arch.index("restoreTab(t)") < arch.index("startDelete(t, NB_DELETE_ARCHIVED)")
    assert "{box.info && <div role=\"status\" className=\"nb-box-text\">{box.info}</div>}" in arch
    assert "aria-expanded={boxFor(['archived', NB_DELETE_ARCHIVED])}" in src


def test_the_question_reads_exact_counts_and_keeps_draft_images():
    src = _read("static/notebook.js")
    assert "function startDelete(t, mode) {\n    if (busy) return;\n    loadDelete(t, mode, '');\n  }" in src
    fn = _fn(src, "async function loadDelete(t, mode, note) {")
    assert "const keep = nbDraftImageIds(t.page);" in fn
    assert "'/api/note-tabs/' + encodeURIComponent(t.page) + '/delete-preview'" in fn and "'?keep=' + keep.join(',')" in fn
    assert "step: 'error', gone: res.status === 404" in fn and "if (res.status === 404) load();" in fn
    ids = src.split("function nbDraftImageIds(exceptPage) {", 1)[1].split("\n}\n", 1)[0]
    assert "if (page === exceptPage" in ids and "/\\/api\\/note-images\\/([1-9][0-9]{0,9})/g" in ids
    assert wp._PAGE_NOTE_IMAGE_SRC_RE.pattern == r"/api/note-images/([1-9][0-9]{0,9})"
    assert ".slice(0, NB_KEEP_IDS_MAX)" in ids
    up = src.split("function nbUploadsBusy() {", 1)[1].split("\n}\n", 1)[0]
    assert "Object.keys(pnUploads).some(p => pnUploadCount(p) > 0)" in up


def test_delete_sends_the_keep_list_and_stamp_and_handles_every_reply():
    src = _read("static/notebook.js")
    fn = _fn(src, "async function deleteTab() {")
    assert "if (busy || del.step !== 'ready' || !del.data || del.data.last_open) return;" in fn
    assert "if (nbUploadsBusy()) {" in fn and "An image is still uploading into a note." in fn
    assert "const keep = nbDraftImageIds(key);" in fn                                 # read again at the click
    assert "nbRequest('DELETE', '/api/note-tabs/' + encodeURIComponent(key), { keep_image_ids: keep, stamp: del.data.stamp })" in fn
    assert "if (res.status === 409 && res.data && res.data.changed) {" in fn and "loadDelete(t, live.box.mode, 'Not deleted: the tab changed" in fn
    assert "if (!ok && res.status !== 404) {" in fn                                    # 404: deleted elsewhere = gone
    assert "\"The server didn't confirm the delete. Reload the page to see whether it went through.\"" in fn
    assert "delete pnDrafts[key];" in fn
    assert "'Freed ' + nbPlural(f.count, 'image') + ' (' + nbMb(f.bytes) + ').'" in fn and "'No images were freed.'" in fn
    # Clicks made while the delete ran win: the page moves on only from what it shows now.
    assert "const live = liveRef.current;" in fn
    assert "live.box.target === key" in fn and "if (live.page === key && next) show(next.page);" in fn
    assert "if (asking && fromArchived && left > 0) { setBox({ mode: 'archived', text: '', page: null, info: msg }); return; }" in fn
    assert "if (!asking) return;" in fn
    assert "liveRef.current = { page: current ? current.page : null, box };" in src


def test_another_windows_delete_refreshes_the_list_on_any_change():
    src = _read("static/notebook.js")
    fn = _fn(src, "async function write(method, path, body) {")
    assert "if (res.status === 404) load();" in fn


def test_the_question_says_what_goes_and_keep_comes_first():
    src = _read("static/notebook.js")
    body = src.split("function deleteBody() {", 1)[1].split("\n  }\n", 1)[0]
    assert '<div role="alertdialog" aria-labelledby={titleId}' in body
    assert "'Delete the \\u201c' + t.label + '\\u201d tab permanently?'" in body
    assert "\" This can't be undone. For a copy first, use Settings, Export DB.\"" in body
    assert "' Your unsaved edits on this tab will be lost too.'" in body
    assert '<div role="alert" className="pn-alert">This is the only open tab. Add another tab before deleting it.</div>' in body
    assert '<div aria-live="polite">' in body and 'id={descId}>{text}</p>' in body
    assert "{del.gone\n          ? <button type=\"button\" className=\"tv-btn pn-btn\" data-nb-first=\"\" onClick={keepTab}>Close</button>" in body
    assert "labelsRef.current[del.key]" in body
    assert "disabled={!d || working || d.last_open || busy}" in body
    assert "data-nb-first={del.step === 'error' ? undefined : ''}" in body and "onClick={keepTab}>Keep</button>" in body
    assert "if (box.mode === 'delete' || box.mode === NB_DELETE_ARCHIVED) { if (del.step !== 'deleting') keepTab(); }" in src
    assert "if (box.mode === 'delete' || box.mode === NB_DELETE_ARCHIVED) return deleteBody();" in src


def test_a_tab_deleted_in_another_window_is_named_when_its_panel_closes():
    src = _read("static/notebook.js")
    assert "tabs.forEach(t => { labelsRef.current[t.page] = t.label; });" in src
    assert ": !gone && name ? '\\u201c' + name + '\\u201d was deleted, maybe in another window.' : ''" in src
