"""Landing 24: the page side of the Notes page. static/notebook.js shows
two tabs, Watchlist and Nuggets, each a PageNotesPanel (static/pagenotes.js)
in its full-page mode, saved under its own page name; static/nav.js lists
Notes in the Trading section right after Trends; static/app.js renders it;
templates/index.html loads notebook.js after pagenotes.js. The shared editor
also makes the browser ask before leaving with unsaved edits on notes that are
on screen, and a save that returns after its tab was left closes only the
draft it carried. No browser here: these read the source files (the headless
checks for the landing exercise the behaviour).
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


def _tab_pages(src):
    return re.findall(r"\{ id: '(\w+)', page: '([\w-]+)', label: '([^']+)' \}", src)


def test_the_tabs_are_watchlist_and_nuggets_and_the_server_knows_their_pages():
    tabs = _tab_pages(_read("static/notebook.js"))
    assert tabs == [("watchlist", "notes-watchlist", "Watchlist"), ("nuggets", "notes-nuggets", "Nuggets")]
    pages = [p for _, p, _ in tabs]
    assert all(p in wp.PAGE_NOTE_PAGES for p in pages)
    # Every Notes page the server accepts has a tab.
    assert [p for p in wp.PAGE_NOTE_PAGES if p.startswith("notes-")] == pages


def test_each_tab_gets_its_own_full_page_panel():
    src = _read("static/notebook.js")
    # Keyed by page: switching tabs mounts a fresh editor instead of carrying
    # one tab's editor state into the other.
    assert ('<Panel key={current.page} page={current.page} hideValues={hideValues} '
            'label={current.label} variant="page" />') in src
    assert "const Panel = window.PageNotesPanel;" in src
    assert "window.NotesScreen = NotesScreen;" in src
    assert "localStorage.getItem(NB_TAB_KEY)" in src and "const NB_TAB_KEY = 'notesTab';" in src
    assert "window.PageNotesHasDraft" in src


def test_top_level_names_are_prefixed():
    src = _read("static/notebook.js")
    names = re.findall(r"^(?:function|const|let|var) (\w+)", src, re.M)
    assert names, "no top-level names found"
    assert all(n.startswith(("nb", "NB", "Notes")) for n in names), names


def test_the_menu_lists_notes_after_trends_in_trading():
    src = _read("static/nav.js")
    assert "  { id: 'notes',              label: 'Notes' },\n" in src
    assert src.index("{ id: 'trends',") < src.index("{ id: 'notes',") < src.index("{ id: 'portfolio-tokens',")
    assert "{ key: 'trading',  heading: 'Trading',  ids: ['spot', 'perps', 'trends', 'notes', 'tt'] }," in src
    assert re.search(r"^  'notes': 'M[^']+',$", src, re.M)


def test_the_app_renders_the_notes_page():
    src = _read("static/app.js")
    assert "  notes:       'Notes',\n" in src
    assert "if (typeof window.NotesScreen !== 'undefined' && activeTab === 'notes')" in src
    assert "React.createElement(window.NotesScreen, { hideValues })" in src


def test_index_loads_notebook_after_pagenotes_and_before_app():
    html = _read("templates/index.html")
    tag = '<script type="text/babel" src="/static/notebook.js?v={{ static_version }}"></script>'
    assert html.count(tag) == 1
    assert html.index("/static/pagenotes.js?v=") < html.index(tag) < html.index("/static/app.js?v=")


def test_the_editor_asks_before_leaving_with_unsaved_edits_on_screen():
    src = _read("static/pagenotes.js")
    assert "window.addEventListener('beforeunload', e => {" in src
    assert "if (!pnUnsavedOnScreen()) return;" in src and "e.preventDefault();" in src and "e.returnValue = '';" in src
    assert "return !!(pnDrafts[page] && pnDrafts[page].dirty);" in src
    assert "return Object.keys(pnOnScreen).some(p => pnOnScreen[p] > 0 && pnHasDraft(p));" in src
    # Each panel counts its own page while mounted; the Notes page counts both tabs.
    assert "usePNEffect(() => pnShowPages([page]), [page]);" in src
    assert "window.PageNotesHasDraft = pnHasDraft;" in src and "window.PageNotesShowPages = pnShowPages;" in src
    nb = _read("static/notebook.js")
    assert "window.PageNotesShowPages(NB_TABS.map(t => t.page))" in nb
    # Exactly one listener: the guard is module-level, not per panel.
    assert src.count("addEventListener('beforeunload'") == 1
    # Settings' exports navigate to a download; they must not meet the guard,
    # which only counts notes on screen (no notes panel on Settings).
    settings = _read("static/settings.js")
    assert "window.location = '/api/backup/db'" in settings and "PageNotesPanel" not in settings


def test_a_save_closes_only_the_draft_it_carried():
    src = _read("static/pagenotes.js")
    assert "const sent = pnDrafts[page];" in src
    assert "if (now && now !== sent) {" in src and "pnDrafts[page] = { ...now, baseId: res.data.id };" in src
    assert "if (!mountedRef.current) {" in src
    assert "if (now) pnDrafts[page] = { delta: now.delta, baseId: res.data.id, dirty: false };" in src


def test_full_page_mode_only_changes_the_notes_page():
    src = _read("static/pagenotes.js")
    assert "function PageNotesPanel({ page, hideValues, label, variant }) {" in src
    assert "const full = variant === 'page';" in src
    assert "const clamp = !full && !expanded && tall;" in src
    assert "{!full && (tall || expanded) && <button" in src
    assert "(full ? ' pn-panel--page' : '')" in src
    # The Spot panel passes no variant, so it keeps the 5-line read view.
    spot = _read("static/spotpnl.js")
    assert '<NotesPanel page="spot" hideValues={hideValues} label="Spot notes" />' in spot
    assert "variant=" not in spot


def test_the_styles_exist():
    css = _read("static/style.css")
    for rule in (".nb-page {", ".nb-head {", ".nb-tabs {", ".nb-unsaved {", ".pn-panel--page .ql-editor {"):
        assert rule in css, rule
    assert "max-height: max(320px, calc(100vh - 380px));" in css and "max-height: max(320px, calc(100dvh - 380px));" in css
    # The full-page editor's height rule comes after the panel's default one, so it wins.
    assert css.index(".pn-panel .ql-editor { min-height: 180px;") < css.index(".pn-panel--page .ql-editor {")
