"""Landing 32: the page side of images in notes (static/pagenotes.js). The
editor takes images only in the Notes page tabs, shrinks each in the browser
and uploads it with the editor's header, keeps only images this app stored,
never puts one in a table, and saves only once uploads are done. The read
view links each image to its full size. No browser here: these read the
source files (the headless checks for the landing exercise the behaviour).
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


def _const(src, name):
    m = re.search(r"^const " + re.escape(name) + r" = (.+?);", src, re.M)
    assert m, name
    return m.group(1)


def _routes():
    return {(r.rule, m) for r in wp.app.url_map.iter_rules() for m in r.methods}


def test_the_limits_equal_the_servers():
    src = _read("static/pagenotes.js")
    assert _const(src, "PN_IMAGE_MAX_BYTES") == "2 * 1024 * 1024" and wp.NOTE_IMAGE_MAX_BYTES == 2 * 1024 * 1024
    assert int(_const(src, "PN_IMAGES_PER_NOTE")) == wp.PAGE_NOTE_IMAGES_MAX
    assert _const(src, "PN_UPLOAD_HEADER") == "'" + wp.NOTE_IMAGE_UPLOAD_HEADER + "'"
    assert int(_const(src, "PN_IMAGE_SHRINK_SIDE")) <= wp.NOTE_IMAGE_MAX_SIDE


def test_the_image_address_pattern_equals_the_servers():
    js = _const(src := _read("static/pagenotes.js"), "PN_IMAGE_SRC_RE")
    assert js == r"/^\/api\/note-images\/[1-9][0-9]{0,9}$/"
    pattern = re.compile(js[2:-2].replace("\\/", "/"))
    for s in ("/api/note-images/1", "/api/note-images/1234567890", "/api/note-images/0", "/api/note-images/01",
              "/api/note-images/12345678901", "/api/note-images/1?x", "https://x/api/note-images/1", "/api/note-images/"):
        assert bool(pattern.fullmatch(s)) == bool(wp._PAGE_NOTE_IMAGE_SRC_RE.fullmatch(s)), s


def test_only_the_notes_tabs_take_images():
    src = _read("static/pagenotes.js")
    assert "return typeof page === 'string' && page.startsWith('notes-');" in src
    assert all(wp._page_note_images_ok(p) for p in ("notes-watchlist", "notes-t3")) and not wp._page_note_images_ok("spot")
    # The image format and the Image button exist only there.
    assert "formats: PN_FORMATS.concat([PN_BREAK_FORMAT]).concat(imagesOk ? ['image'] : [])," in src
    assert "container: imagesOk ? PN_TOOLBAR.map(g => (g.includes('table') ? g.concat(['image']) : g)) : PN_TOOLBAR," in src
    assert "if (!imagesOk) { setHint('Images can go in the Notes page tabs, not in this panel.'); return; }" in src
    # Paste and drop hand over a wider list, so an image type that can't be used gets a message.
    assert "uploader: { mimetypes: PN_IMAGE_DROP_TYPES, handler: (range, files) => addImages(range, files) }," in src
    assert "f.type.startsWith('image/') && f.type !== 'image/svg+xml'" in src
    spot = _read("static/spotpnl.js")
    assert '<NotesPanel page="spot"' in spot


def test_every_route_the_editor_calls_exists():
    src = _read("static/pagenotes.js")
    routes = _routes()
    assert "fetch('/api/note-images', { method: 'POST', body: blob," in src and ("/api/note-images", "POST") in routes
    assert "[PN_UPLOAD_HEADER]: '1'" in src
    assert "pnRequest('GET', '/api/note-images/usage')" in src and ("/api/note-images/usage", "GET") in routes
    assert ("/api/note-images/<int(max=9999999999):image_id>", "GET") in routes


def test_images_are_shrunk_and_saved_again_before_upload():
    src = _read("static/pagenotes.js")
    assert "src = await createImageBitmap(file);" in src
    assert "Math.min(1, PN_IMAGE_SHRINK_SIDE / Math.max(src.width, src.height))" in src
    assert "[['image/webp', 0.9], ['image/png', undefined], ['image/jpeg', 0.85], ['image/jpeg', 0.7]]" in src
    assert "const from = type === 'image/jpeg' ? onWhite : canvas;" in src
    assert "blob.type === type && blob.size <= PN_IMAGE_MAX_BYTES" in src
    assert "await pnUploadImage(await pnPrepareImage(file))" in src


def test_only_this_apps_images_are_kept():
    src = _read("static/pagenotes.js")
    # Pasted <img>: kept only when it is a stored image; dropped with a hint otherwise.
    assert "quill.clipboard.addMatcher('IMG', node => {" in src
    assert "const src = imagesOk ? pnImageSrc(node.getAttribute('src')) : null;" in src
    # Saving keeps an image's address only, and drops one that isn't this app's.
    assert "const src = pnImageSrc(raw.insert.image);\n      if (src) ops.push({ insert: { image: src } });" in src
    assert "u.origin === window.location.origin && !u.search && !u.hash && PN_IMAGE_SRC_RE.test(u.pathname)" in src
    # An image copied from a read view (its <img> plus a file) keeps the stored image.
    assert "quill.root.addEventListener('paste', onPasteStored, true);" in src
    assert "if (!only || only.tagName !== 'IMG' || !pnImageSrc(only.getAttribute('src'))) return;" in src


def test_no_image_inside_a_table_and_at_most_50():
    src = _read("static/pagenotes.js")
    assert "while (at < quill.getLength() - 1 && pnRangeInTable(quill, { index: at, length: 0 })) at += 1;" in src
    assert "if (pnImageInTable(delta)) {" in src
    assert "the pasted image was left out" in src
    assert "if (pnRangeInTable(q, range)) { refuse('Images'); return; }" in src
    assert "if (pnRangeInTable(quill, r)) { setHint(\"Images can't go inside a table." in src
    assert "+ waiting + list.length > PN_IMAGES_PER_NOTE" in src
    assert "if (pnImageCount(delta) > PN_IMAGES_PER_NOTE) {" in src


def test_uploads_are_kept_per_note_and_save_waits_for_them():
    src = _read("static/pagenotes.js")
    # Kept per note (they outlive an editor), one at a time in order.
    assert "const pnUploads = {};" in src and "ups.chain = ups.chain.then(async () => {" in src
    assert "ups.slots.forEach(slot => { slot.index = delta.transformPosition(slot.index); })" in src
    assert "quill.on('text-change', followEdits);" in src and "quill.off('text-change', followEdits);" in src
    assert "ups.editor = quill;" in src and "if (ups.editor === quill) ups.editor = null;" in src
    # Finished after its editor closed: into the note's draft, at its place.
    assert "if (st.editor) { slot.index = pnPlaceInEditor(st.editor, slot.index, url) + 1; return true; }" in src
    assert "pnDrafts[page] = { ...draft, delta: { ops: doc.compose(ins).ops }, dirty: true };" in src
    # Save waits; Cancel asks while images are on their way.
    assert "if (uploading > 0) {" in src and "wait for the images to finish uploading" in src
    assert "if (dirty || uploading > 0) { setConfirmDiscard(true); return; }" in src
    # The panel follows its note's uploads after a remount.
    assert "pnUploadListeners.add(onUploads);" in src and "setUploading(pnUploadCount(page));" in src
    # A failure while the panel was off screen is shown when it comes back.
    assert "if (info.hint && !shown) pnUploadState(page).missed = info.hint;" in src
    assert "if (st.missed) { setError(st.missed); st.missed = null; }" in src
    # With the editor closed (Hide values), on the error line too.
    assert "if (extra.hint) { if (quillRef.current) setHint(extra.hint); else setError(extra.hint); }" in src


def test_discarding_the_edit_drops_its_uploads():
    src = _read("static/pagenotes.js")
    # Cancel / Discard changes / Discard mine all close the editor through closeEditor.
    assert "    delete pnDrafts[page];\n    pnDropUploads(page);" in src
    assert "st.slots.forEach(slot => { slot.dropped = true; });\n  st.slots = [];" in src
    assert "if (slot.dropped) return;" in src and "if (slot.dropped) return false;" in src
    # A dropped slot has left the list: it is never spliced by a stale index.
    assert "if (!slot.left && at >= 0) ups.slots.splice(at, 1);" in src
    assert "ups.slots.splice(ups.slots.indexOf(slot), 1)" not in src
    # A new edit starts without an old message.
    i = src.index("  function startEdit() {")
    assert "setHint('');" in src[i:src.index("setMode('edit');", i)]


def test_an_upload_gives_up_and_no_image_is_added_during_a_save():
    src = _read("static/pagenotes.js")
    assert int(_const(src, "PN_UPLOAD_TIMEOUT_MS")) == 90000
    assert "setTimeout(() => ctrl.abort(), PN_UPLOAD_TIMEOUT_MS)" in src and "signal: ctrl ? ctrl.signal : undefined" in src
    assert "if (savingRef.current) { setHint('Wait for the save to finish, then add the image.'); return; }" in src
    assert src.count("savingRef.current = ") == 2


def test_a_reload_asks_while_an_image_is_on_its_way():
    src = _read("static/pagenotes.js")
    assert "pnOnScreen[p] > 0 && (pnHasDraft(p) || pnUploadCount(p) > 0)" in src


def test_a_note_of_only_images_is_saved():
    src = _read("static/pagenotes.js")
    assert "if (len === 0 && pnImageCount(delta) === 0 && baseId == null && (!note || note.id == null)) {" in src


def test_clear_formatting_keeps_images():
    src = _read("static/pagenotes.js")
    assert ".ops.some(op => pnIsBreak(op) || pnIsImage(op))) {" in src


def test_the_read_view_links_each_image_to_its_full_size():
    src = _read("static/pagenotes.js")
    assert ('<a key={key} className="pn-img-link" href={seg.img} target="_blank" rel="noopener" title="Open full size">'
            in src)
    assert '<img className="pn-img" src={seg.img} alt="Image in note (opens full size)" loading="lazy" />' in src
    assert "if (src) segs.push({ img: src, a: {} });" in src
    # Still no HTML strings: the read view builds elements.
    assert src.count("innerHTML") == 1


def test_no_raw_invisible_characters():
    src = _read("static/pagenotes.js")
    for ch in ("\u00a0", "\u200b", "\u200e", "\u200f", "\u2028", "\u2066"):
        assert ch not in src


def test_the_styles_exist():
    css = _read("static/style.css")
    for rule in (".pn-img-link {", ".pn-img {", ".pn-panel .ql-editor img {", ".pn-uploading {", ".pn-counts {"):
        assert rule in css, rule
    assert ".pn-img { display: block; max-width: 100%; height: auto;" in css


def test_the_storage_line_is_not_read_out_on_every_keystroke():
    src = _read("static/pagenotes.js")
    # Only the character count is a live region; the storage is a separate span.
    assert '{imagesOk && usage && <span className="pn-count pn-usage">' in src
    i = src.index('aria-live="polite">{count.toLocaleString')
    assert src.index("</span>", i) < src.index("pn-usage", i)
