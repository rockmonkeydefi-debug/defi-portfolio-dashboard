"""Landing 57 (Oct 20): on the Notes page the note's header row (tab name,
saved time, Edit) stays in view while a long note scrolls, and Edit from
further down opens the editor at the saved line at the top of the screen.

Glenn asked for the Edit button to "float" down as he scrolls a long note;
he ruled (17:10, "your recs"): a sticky header row (A), the editor opening at
the line being read (A), both in one landing (A). The header sticks just under
the 48px top bar (TOPBAR_HEIGHT_PX in static/app.js), at the top once the menu
docks (NAV_DOCK_QUERY in static/nav.js, 1880px). Each read-view line and table
cell carries data-pn-line, its line number, which is also its place in the
editor's lines (both count one line per saved line break). Browser checks
(1920, 1250 and 390px) are in the landing record; these pin the wiring.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


def test_the_header_sticks_under_the_top_bar_on_the_notes_page_only():
    css = _read("static/style.css")
    rule = ".pn-panel--page .pn-head--sticky { position: sticky; top: 48px; z-index: 3; background: var(--panel);"
    assert rule in css
    assert "margin: -10px -14px 6px; padding: 10px 14px 6px; border-radius: 11px 11px 0 0;" in css
    assert "border-bottom: 1px solid rgba(255,255,255,0.25); }" in css
    docked = css.index("@media (min-width: 1880px) {", css.index(rule))
    assert css.index(".pn-panel--page .pn-head--sticky { top: 0; }", docked) - docked < 80
    # The offsets follow the top bar's height and the menu's docking width.
    assert "const TOPBAR_HEIGHT_PX = 48;" in _read("static/app.js")
    assert "const NAV_DOCK_QUERY = '(min-width: 1880px)';" in _read("static/nav.js")
    # The panel itself must not clip it (a sticky child needs no overflow on its box).
    at = css.index(chr(10) + ".pn-panel {")
    panel = css[at:css.index("}", at)]
    assert "overflow" not in panel
    js = _read("static/pagenotes.js")
    assert "const head = <div ref={headRef} className={'pn-head' + (full && mode === 'read' ? ' pn-head--sticky' : '')}>" in js


def test_read_view_lines_and_cells_carry_their_line_number():
    js = _read("static/pagenotes.js")
    read = _between(js, "function PageNotesRead({ delta }) {", "// True when the range (or the cursor) touches a table cell.")
    assert "out.push(<div key={i} data-pn-line={i} className={cls}" in read
    assert "return <td key={ci} data-pn-line={c ? c.n : undefined} style=" in read
    assert "last.cells.push({ segs: ln.segs, a, n: i });" in read
    assert "table.rows.push({ id: cell, cells: [{ segs: ln.segs, a, n: i }] });" in read
    # The numbers are the line indexes of pnLines, the same lines the editor holds.
    assert "const lines = pnLines(delta);" in read and "lines.forEach((ln, i) => {" in read


def test_edit_takes_the_line_at_the_top_of_the_screen():
    js = _read("static/pagenotes.js")
    anchor = _between(js, "function pnReadAnchor(readEl, headEl) {", "function pnKeepAnchor(")
    assert "const below = headEl.getBoundingClientRect().bottom;" in anchor
    assert "for (const el of readEl.querySelectorAll('[data-pn-line]')) {" in anchor
    assert "if (el.getBoundingClientRect().bottom > below + 1) return Number(el.getAttribute('data-pn-line')) || 0;" in anchor
    start = _between(js, "  function startEdit() {", "  function closeEditor(")
    take = "openAtRef.current = full ? pnReadAnchor(readRef.current, headRef.current) : 0;     // Landing 57"
    assert take in start and start.index(take) < start.index("setMode('edit');")


def test_the_editor_opens_at_that_line_and_keeps_it_while_images_load():
    js = _read("static/pagenotes.js")
    setup = _between(js, "    quillRef.current = quill;", "    setInTable(pnRangeInTable(quill, lastRangeRef.current));")
    assert "const openAt = openAtRef.current;" in setup and "openAtRef.current = 0;" in setup
    assert "const anchor = lines.length ? lines[Math.min(openAt, lines.length - 1)] : null;" in setup
    assert "quill.setSelection(at, 0, 'silent');" in setup and "lastRangeRef.current = { index: at, length: 0 };" in setup
    assert "stopAnchor = pnKeepAnchor(quill, anchor);" in setup
    # Without an anchor (Edit from the top) it opens as before.
    assert "quill.setSelection(quill.getLength(), 0, 'silent');" in setup
    assert setup.index("quill.focus();") < setup.index("const openAt = openAtRef.current;")
    cleanup = _between(js, "    return () => {" + chr(10) + "      stopAnchor();", "  }, [editorOpen]);")
    assert "quillRef.current = null;" in cleanup
    keep = _between(js, "function pnKeepAnchor(quill, blot) {", "function PageNotesPanel(")
    assert "root.scrollTop += blot.domNode.getBoundingClientRect().top - root.getBoundingClientRect().top;" in keep
    assert "root.addEventListener('load', place, true);" in keep and "root.removeEventListener('load', place, true);" in keep
    assert "const events = ['wheel', 'touchstart', 'keydown', 'mousedown'];" in keep
    # The user's own scroll, typing or click stops it (and closing the editor does too).
    assert "events.forEach(t => root.addEventListener(t, stop, true));" in keep
    assert "events.forEach(t => root.removeEventListener(t, stop, true));" in keep
    assert "timer = setTimeout(stop, PN_ANCHOR_HOLD_MS);" in keep
    assert "const PN_ANCHOR_HOLD_MS = 2000;" in js and "PN_ANCHOR_GAP_PX" not in js
