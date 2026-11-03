"""Landing 88: the wiring of the Spot Summary in the Notes page editor (source-text checks; the behaviour is
covered by tests/test_spot_summary_rich.py and the headless-browser runs).

- static/pagenotes.js: PageNotesPanel takes an io prop (load / save adapter) and emptyText; with no io the
  two page-notes requests are the ones the older wiring tests pin; an io note may hold images; the read view is
  exported for the History tab.
- static/spotjournal.js: SJSummary mounts the panel with the Summary routes behind it (the page key for drafts,
  the version token as base_id, the legacy text converted by sjToDelta); SpotJournal no longer has its own
  textarea Summary (Landing 89 then moved the dated updates into the same editor: see
  tests/test_spot_updates_rich_wiring.py).
- static/spothistory.js: the collapsed Summary reads the document when there is one and the plain text when not.
- static/style.css: the panel's header stays put inside the Notes card.
"""
import re
import threading
from pathlib import Path

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

ROOT = Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _body(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]


# -- pagenotes.js -----------------------------------------------------------------------------------------------


def test_the_panel_takes_an_io_and_keeps_the_page_notes_requests_for_no_io():
    src = _read("static/pagenotes.js")
    assert "function PageNotesPanel({ page, hideValues, label, variant, io, emptyText, startInEdit, onClosed }) {" in src
    assert src.count("'/api/page-notes/' + page") == 2                    # also pinned by test_page_notes_wiring
    assert "(io ? io.get() : pnRequest('GET', '/api/page-notes/' + page)).then(res => {" in src
    assert ("const res = io ? await io.put(delta, baseId) : await pnRequest('PUT', '/api/page-notes/' + page, "
            "{ delta, base_id: baseId });") in src


def test_an_io_note_may_hold_images_and_the_empty_text_can_be_replaced():
    src = _read("static/pagenotes.js")
    assert "const imagesOk = pnImagesAllowed(page) || !!io;" in src
    assert "function pnImagesAllowed(page) {\n  return typeof page === 'string' && page.startsWith('notes-');\n}" in src   # unchanged
    assert "{emptyText || 'No notes yet.'}" in src


def test_the_read_view_is_exported_and_the_old_exports_stay():
    src = _read("static/pagenotes.js")
    for line in ("window.PageNotesPanel = PageNotesPanel;", "window.PageNotesRead = PageNotesRead;",
                 "window.PageNotesHasDraft = pnHasDraft;", "window.PageNotesShowPages = pnShowPages;"):
        assert line in src


def test_drafts_are_kept_in_pnDrafts_where_a_delete_looks_for_their_images():
    # A Spot draft's pictures are protected from a Watch List / Notes tab delete because the panel keeps every
    # draft in pnDrafts and wlDraftImageIds reads every entry of it (Landing 79 / 83 / 87).
    pn = _read("static/pagenotes.js")
    assert "pnDrafts[page] = { delta: start, baseId:" in pn
    wl = _read("static/watchlist.js")
    assert "Object.keys(pnDrafts).forEach(page => {" in wl and "JSON.stringify(pnDrafts[page].delta)" in wl
    nb = _read("static/notebook.js")
    for src, name, arg in ((wl, "wlDraftImageIds", "exceptKey"), (nb, "nbDraftImageIds", "exceptPage")):
        fn = _body(src, "function " + name + "(", "\n}\n")
        # every draft but the one being deleted counts, whatever its key (a Spot Summary's is 'spot-summary:...'):
        # the only skip is the excepted page, an empty draft or one with no document
        assert "Object.keys(pnDrafts).forEach(page => {" in fn
        assert "if (page === %s || !pnDrafts[page] || !pnDrafts[page].delta) return;" % arg in fn
        assert "JSON.stringify(pnDrafts[page].delta)" in fn
        for filtering in ("startsWith", "indexOf", "includes(", ".match(", "test(page", "slice("):
            assert filtering not in fn.replace("slice(0, ", "")


def test_two_panels_of_one_position_get_their_own_drafts():
    # History shows a position's Summary under every closed trade; a draft (and its uploads) is per panel.
    hist = _read("static/spothistory.js")
    assert "scope={'t' + id}" in hist
    jr = _read("static/spotjournal.js")
    assert jr.count("(scope || 'open')") == 1
    pn = _read("static/pagenotes.js")
    assert "pnDrafts[page] = { delta: start, baseId:" in pn          # one draft per page key, so the key must differ


# -- spotjournal.js ---------------------------------------------------------------------------------------------


def test_the_summary_panel_is_mounted_with_the_summary_routes():
    src = _read("static/spotjournal.js")
    body = _body(src, "function SJSummary(", "// -- A dated update in the Notes page editor (Landing 89)")
    assert "const Panel = window.PageNotesPanel;" in body
    assert "'/api/spot/position-notes/view' + query" in body
    assert "pnRequest('PUT', '/api/spot/position-notes', { chain, contract_address, delta, base_id: baseId })" in body
    assert "page={'spot-summary:' + (scope || 'open') + ':' + chain + ' ' + contract_address}" in body
    assert "function SJSummary({ chain, contract_address, symbol, scope, onSaved }) {" in body
    assert 'variant="page" io={io}' in body and "emptyText={SJ_SUMMARY_EMPTY}" in body
    assert "label={'Summary for ' + symbol}" in body
    assert "encodeURIComponent(chain)" in body and "encodeURIComponent(contract_address)" in body
    # the plain text of an older Summary is converted for the editor, on a read and on a 409's current version
    assert "res.data = sjSummaryView(res.data);" in body
    assert "current: sjSummaryView(res.data.current)" in body
    assert "onSaved(res.data.text, res.data.delta)" in body


def test_the_old_summary_text_is_converted_by_the_marker_parser():
    src = _read("static/spotjournal.js")
    body = _body(src, "function sjToDelta(text) {", "// The server's Summary view")
    assert "sjParseNote(text)" in body
    assert ("ops.push(sg.b ? { insert: sg.t, attributes: { bold: true } }\n"
            "        : sg.i ? { insert: sg.t, attributes: { italic: true } } : { insert: sg.t });") in body
    assert "attributes: { list: 'bullet' }" in body
    assert "[{ insert: '\\n' }]" in body                                    # an empty Summary is one empty line
    assert "window.sjToDelta = sjToDelta;" in src


def test_the_journal_has_no_textarea_summary_any_more():
    src = _read("static/spotjournal.js")
    journal = src[src.index("function SpotJournal("):]
    for gone in ("saveSummary", "sumEditing", "sumDraft", "sumBusy", "sumError", "'/api/spot/position-notes', { method: 'PUT'"):
        assert gone not in journal
    assert "<SJSummary key={key} chain={chain} contract_address={contract_address} symbol={symbol}" in journal
    assert "onSaved={(text, delta) => onSummarySaved(key, text, delta)}" in journal
    assert "symbol={symbol} scope={scope}" in journal
    assert "editing, setEditing, scope }) {" in src


def test_every_top_level_name_added_to_the_file_keeps_the_prefix():
    src = _read("static/spotjournal.js")
    names = re.findall(r"^(?:async )?function (\w+)|^const (\w+)", src, re.M)
    flat = [a or b for a, b in names]
    assert flat and all(n.startswith(("sj", "SJ", "SpotJournal")) for n in flat if n != "")


def test_the_file_adds_nothing_outside_ascii():
    # The source stays ASCII where this landing wrote it: the new block builds nothing from raw symbols.
    block = _read("static/spotjournal.js")
    block = block[block.index("const SJ_SUMMARY_EMPTY"):block.index("// -- A dated update in the Notes page editor (Landing 89)")]
    block = block.replace("\u2500", "")          # the file's own section rule below the block is not part of it
    assert all(ord(c) < 128 for c in block)


# -- spothistory.js ---------------------------------------------------------------------------------------------


def test_history_reads_the_document_when_there_is_one():
    src = _read("static/spothistory.js")
    assert "const [summaryDocs, setSummaryDocs] = useSHXState({});" in src
    assert "if (n.delta) docs[n.chain + ' ' + n.contract_address] = n.delta;" in src
    assert "function onSummarySaved(key, note, delta) {" in src
    assert "setSummaryDocs(prev => ({ ...prev, [key]: delta || undefined }));" in src
    assert "summaryDocs[key] && window.PageNotesRead" in src
    assert "<window.PageNotesRead delta={summaryDocs[key]} />" in src
    assert ": <SJNoteText text={summary} />)" in src                          # a plain Summary reads as before


def test_open_positions_still_takes_the_plain_text_back_for_the_tooltip():
    src = _read("static/spotpnl.js")
    assert "function onNoteSaved(key, note) {" in src
    assert "onSummarySaved={onNoteSaved}" in src


# -- style.css and the routes -----------------------------------------------------------------------------------


def test_the_panel_header_is_not_sticky_inside_the_notes_card():
    css = _read("static/style.css")
    assert ".sj-summary .pn-panel--page .pn-head--sticky { position: static; }" in css
    assert ".pn-read-sj { overflow: visible; }" in css
    assert ".pn-panel--page .pn-head--sticky { position: sticky;" in css       # the Notes page keeps its own


def test_the_routes_the_summary_calls_exist():
    rules = {(r.rule, m) for r in wp.app.url_map.iter_rules() for m in r.methods}
    for rule, method in (("/api/spot/position-notes", "GET"), ("/api/spot/position-notes", "PUT"),
                         ("/api/spot/position-notes/view", "GET")):
        assert (rule, method) in rules
