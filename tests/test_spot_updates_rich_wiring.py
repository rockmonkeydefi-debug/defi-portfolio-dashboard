"""Landing 89: the wiring of the dated updates in the Notes page editor (source-text checks; the behaviour is
covered by tests/test_spot_updates_rich.py and the headless-browser runs).

- static/pagenotes.js: PageNotesPanel takes two more optional props, startInEdit (mount in edit mode) and onClosed
  (called whenever the editor closes), and nothing else changed.
- static/spotjournal.js: each update is a panel of its own (SJUpdateDoc, key 'spot-update:<scope>:<id>') through the
  update routes with the version token as base_id; a new one is composed in a panel (SJNewUpdate, key
  'spot-update-new:<scope>:<position>'); the textarea editor is gone; an update written before still reads as before.
- static/spotpnl.js, static/spothistory.js: the page-level journal state is the map of open editors (no draft or
  composer state of its own); the Closed tab's collapsed updates read the document.
- static/style.css: a read update has no card and no header of its own.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _body(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]


# -- pagenotes.js -----------------------------------------------------------------------------------------------


def test_the_panel_opens_in_edit_mode_when_asked_and_says_when_the_editor_closes():
    src = _read("static/pagenotes.js")
    assert "function PageNotesPanel({ page, hideValues, label, variant, io, emptyText, startInEdit, onClosed }) {" in src
    assert "usePNState(() => (pnDrafts[page] || startInEdit ? 'edit' : 'read'));" in src
    close = _body(src, "  function closeEditor(newNote) {", "  async function save(")
    assert "if (onClosed) onClosed(newNote || null);" in close
    assert close.count("onClosed") == 2                                     # the guard and the call
    assert src.count("onClosed(newNote") == 1                                # closeEditor is the only place it is called
    # every way the editor closes goes through closeEditor: Save, Use theirs, Cancel, Discard, nothing to keep
    assert src.count("closeEditor(") == 6                                    # the definition and five calls
    assert "closeEditor(res.data);" in src and "closeEditor(theirs);" in src and "closeEditor(null);      // nothing to keep" in src


def test_the_new_props_are_documented_in_the_header_comment():
    src = _read("static/pagenotes.js")
    head = src[:src.index("const { useState: usePNState")]
    assert "Landing 89" in head and "startInEdit" in head and "onClosed(note)" in head


# -- spotjournal.js ---------------------------------------------------------------------------------------------


def test_an_update_as_the_editor_reads_it():
    src = _read("static/spotjournal.js")
    body = _body(src, "function sjUpdateView(u) {", "// One dated update as a Notes page panel.")
    assert "id: u.version" in body                                          # the version token is the editor's note id
    assert "delta: u.delta || sjToDelta(u.body)" in body                    # an older update opens converted
    assert "text: u.body" in body and "saved_at: u.edited_at || u.created_at" in body
    assert "empty: !String(u.body || '').trim()" in body and "legacy: !!u.legacy" in body
    assert "row: u" in body                                                 # so the page can replace its copy


def test_an_update_panel_saves_through_the_put_route_with_the_version_token():
    src = _read("static/spotjournal.js")
    body = _body(src, "function SJUpdateDoc(", "// The composer of a new update")
    assert "const Panel = window.PageNotesPanel;" in body and "The notes editor didn't load." in body
    assert "async get() { return { status: 200, data: sjUpdateView(u) }; }" in body      # from the list: no request per panel
    assert "pnRequest('PUT', '/api/spot/note-updates/' + u.id, { delta, base_id: baseId })" in body
    assert "if (res && res.status === 200 && res.data) { onSaved(res.data); res.data = sjUpdateView(res.data); }" in body
    assert ("else if (res && res.status === 409 && res.data && res.data.current) "
            "res.data = { ...res.data, current: sjUpdateView(res.data.current) };") in body
    assert "<Panel page={pageKey} label={'Update from ' + stamp} variant=\"page\" io={io} startInEdit={editing} onClosed={onClosed} />" in body
    assert 'className="sj-update"' in body


def test_a_new_update_is_composed_in_a_panel_and_created_by_the_post_route():
    src = _read("static/spotjournal.js")
    body = _body(src, "function SJNewUpdate(", "// After an editor closes")
    assert "async get() { return { status: 200, data: { id: null, delta: null, text: '', saved_at: null, empty: true, legacy: false } }; }" in body
    assert "pnRequest('POST', '/api/spot/note-updates', { chain, contract_address, delta })" in body
    assert "if (res && res.status === 201 && res.data) {" in body and "return { status: 200, data: sjUpdateView(res.data) };" in body
    assert "label={'New update for ' + symbol} variant=\"page\" io={io} startInEdit={true} onClosed={() => onClosed()}" in body
    assert "It is stamped with the date and time when you save it." in body
    # a stored update clears its own draft: the panel may be gone by the time the reply arrives (a tab switch), and
    # then nothing else would close the composer or drop the draft, and a second Save would add the update twice
    stored = _body(body, "if (res && res.status === 201 && res.data) {", "return res;")
    assert stored.index("onAdded(res.data);") < stored.index("delete pnDrafts[pageKey];") < stored.index("return { status: 200")


def test_each_panel_has_its_own_draft_key_per_scope():
    src = _read("static/spotjournal.js")
    journal = src[src.index("function SpotJournal("):]
    assert "function SpotJournal({ row, updates, notesError, onSummarySaved, onUpdatesChanged, editing, setEditing, scope }) {" in journal
    assert "const where = scope || 'open';" in journal
    assert "const composeKey = 'spot-update-new:' + where + ':' + key;" in journal
    assert "const pageKey = 'spot-update:' + where + ':' + u.id;" in journal
    # a trade's journal and the Open row's are different panels, even for one update
    assert "scope={scope}" in journal                                        # the Summary's key is scoped the same way
    hist = _read("static/spothistory.js")
    assert "scope={'t' + id}" in hist


def test_the_journal_remounts_a_panel_between_reading_and_editing_and_keeps_an_older_update_as_it_was():
    src = _read("static/spotjournal.js")
    journal = src[src.index("function SpotJournal("):]
    assert "{isEditing || u.delta" in journal
    # a read panel is remounted when the update's version changes (it reads its note once, when it mounts): another
    # view of the update saved, or the page refreshed
    assert "<SJUpdateDoc key={pageKey + (isEditing ? ':edit' : ':read:' + u.version)}" in journal
    assert ": <SJNoteText text={u.body} />}" in journal                      # an update with no document reads as before
    assert "onClick={() => { setConfirmId(null); setEditing(pageKey, true); }}>Edit</button>" in journal
    assert "{!isEditing && !confirming && <span" in journal                  # Edit and Delete hide while editing
    assert "onSaved={replaceUpdate}" in journal
    assert "if (view && view.row) replaceUpdate(view.row); setEditing(pageKey, false);" in journal
    assert "onAdded={added => { onUpdatesChanged(key, list => [added].concat(list)); setEditing(composeKey, false); }}" in journal
    assert "setEditing(composeKey, false);" in journal and "{composing && <SJNewUpdate " in journal
    assert "{!composing && <button" in journal and "onClick={() => setEditing(composeKey, true)}>+ Add update</button>" in journal


def test_an_update_with_unsaved_changes_in_another_view_is_not_deleted():
    src = _read("static/spotjournal.js")
    body = _body(src, "  async function deleteUpdate(u) {", "  const errLine")
    check = body[:body.index("setDeleteBusy(true);")]
    assert "Object.keys(pnDrafts).filter(k => k.indexOf('spot-update:') === 0" in check
    assert "k.slice(k.lastIndexOf(':') + 1) === String(u.id)" in check and "pnDrafts[k].dirty" in check
    assert "if (unsaved.length) { setDeleteError('This update has unsaved changes open in another view." in check
    assert "return; }" in check                                              # nothing is sent
    assert "api('/api/spot/note-updates/' + u.id, { method: 'DELETE' })" in body.split("setDeleteBusy(true);")[1]


def test_focus_goes_back_to_the_journals_own_button_after_an_editor_closes():
    src = _read("static/spotjournal.js")
    assert "function sjFocusLater(attr, value) {" in src
    journal = src[src.index("function SpotJournal("):]
    assert "data-sj-edit={pageKey}" in journal and "data-sj-add={composeKey}" in journal
    assert "sjFocusLater('data-sj-edit', pageKey)" in journal and "sjFocusLater('data-sj-add', composeKey)" in journal


def test_delete_is_as_before_and_the_textarea_editor_is_gone():
    src = _read("static/spotjournal.js")
    journal = src[src.index("function SpotJournal("):]
    assert "'/api/spot/note-updates/' + u.id, { method: 'DELETE' }" in journal
    for gone in ("SJEditor", "sjTrimEnd", "sjLineRange", "SJ_MAX", "SJ_EDITOR_ROWS", "<textarea", "maxLength", "execCommand",
                 "addUpdate", "saveEdit", "editDraft", "editBusy", "addBusy", "onDraftChange", "setComposing", "'/api/spot/note-updates', { method: 'POST'",
                 "{ method: 'PUT', body: JSON.stringify({ body })"):
        assert gone not in src, gone
    assert "useRef" not in src and "useEffect" not in src                    # the hooks only the textarea used
    assert "const { useState: useSJState } = React;" in src


def test_the_older_text_helpers_and_exports_stay():
    src = _read("static/spotjournal.js")
    for line in ("window.SpotJournal = SpotJournal;", "window.SJNoteText = SJNoteText;", "window.sjParseNote = sjParseNote;",
                 "window.sjToDelta = sjToDelta;", "window.sjInline = sjInline;", "window.sjPlain = sjPlain;",
                 "window.sjParseTime = sjParseTime;", "window.sjStamp = sjStamp;", "window.sjAgo = sjAgo;",
                 "window.sjShortAge = sjShortAge;"):
        assert line in src
    names = re.findall(r"^(?:async )?function (\w+)|^const (\w+)", src, re.M)
    flat = [a or b for a, b in names]
    assert flat and all(n.startswith(("sj", "SJ", "SpotJournal")) for n in flat)


def test_the_new_block_is_plain_ascii():
    src = _read("static/spotjournal.js")
    block = _body(src, "// -- A dated update in the Notes page editor (Landing 89)", "// " + chr(0x2500) * 2 + " The journal")
    assert all(ord(c) < 128 for c in block)


# -- spotpnl.js and spothistory.js -----------------------------------------------------------------------------


def test_the_page_keeps_the_map_of_open_editors_and_no_drafts_of_its_own():
    pnl = _read("static/spotpnl.js")
    assert "const [editing, setEditing] = useState({});" in pnl
    assert "const journal = { openRows, setOpenRows, editing, setEditing };" in pnl
    for gone in ("setDrafts", "setComposing", "journal.drafts", "journal.composing", "onDraftChange"):
        assert gone not in pnl, gone
    assert "editing={journal.editing} setEditing={(panelKey, open) => journal.setEditing(prev => ({ ...prev, [panelKey]: open }))} />" in pnl
    hist = _read("static/spothistory.js")
    for gone in ("setDrafts", "setComposing", "journal.drafts", "journal.composing", "onDraftChange"):
        assert gone not in hist, gone
    assert "editing={journal.editing} setEditing={(panelKey, open) => journal.setEditing(prev => ({ ...prev, [panelKey]: open }))} />" in hist


def test_the_closed_tab_reads_an_updates_document_and_an_older_update_as_text():
    hist = _read("static/spothistory.js")
    assert "{u.delta && window.PageNotesRead" in hist
    assert '? <div className="pn-read pn-read-sj"><window.PageNotesRead delta={u.delta} /></div>' in hist
    assert ": <SJNoteText text={u.body} />}" in hist


def test_the_row_tooltip_still_reads_the_plain_text_mirror():
    pnl = _read("static/spotpnl.js")
    assert "sjPlain(ups[0].body)" in pnl                                     # body stays the plain-text mirror of every save


# -- style.css --------------------------------------------------------------------------------------------------


def test_a_read_update_has_no_card_or_header_and_an_edited_one_has_the_panel():
    css = re.sub(r"/[*].*?[*]/", "", _read("static/style.css"), flags=re.S)
    assert ".sj-update .pn-panel--page { background: none; border: 0; padding: 0; }" in css
    assert ".sj-update .pn-panel--page:not(.pn-editing) .pn-head { display: none; }" in css
    assert (".sj-update .pn-panel--page.pn-editing { background: var(--panel); border: 1px solid var(--line); "
            "padding: 10px 14px 12px; }") in css
    assert ".sj-update .pn-panel--page .pn-head--sticky { position: static; }" in css
