"""Landing 32: the page side of images in notes (static/pagenotes.js). The
editor takes images only in the Notes page tabs, shrinks each in the browser
and uploads it with the editor's header, keeps only images this app stored,
and saves only once uploads are done. The read view links each image to its
full size. Landing 56 (Oct 20): images may go inside table cells too. No browser here: these read the
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
    assert "const src = pnImageSrc(raw.insert.image);" in src
    assert "if (src) ops.push(width ? { insert: { image: src }, attributes: { width } } : { insert: { image: src } });" in src
    assert "u.origin === window.location.origin && !u.search && !u.hash && PN_IMAGE_SRC_RE.test(u.pathname)" in src
    # An image copied from a read view (its <img> plus a file) keeps the stored image.
    assert "quill.root.addEventListener('paste', onPasteStored, true);" in src
    assert "if (!only || only.tagName !== 'IMG' || !pnImageSrc(only.getAttribute('src'))) return;" in src


def test_images_go_inside_table_cells_and_at_most_50():
    src = _read("static/pagenotes.js")
    # Landing 56: every refusal of an image in a table is gone (the Image button,
    # a pick, paste or drop, an upload landing late, a paste inside one cell, Save).
    for gone in ("pnRangeInTable(quill, { index: at, length: 0 })", "pnImageInTable", "refuse('Images')",
                 "Images can't go inside a table", "the pasted image was left out", "an image ended up inside a table"):
        assert gone not in src, gone
    assert "const at = Math.min(index, Math.max(quill.getLength() - 1, 0));   // a table cell too (Landing 56)" in src
    # No table test is left on the paths an image takes, whatever a refusal would say.
    regions = {
        "pnPlaceInEditor": ("function pnPlaceInEditor(", "function pnPlaceImage("),
        "the Image button": ("      image() {", "    pnRegisterCellFormats(Quill);"),
        "addImages": ("    function addImages(range, files) {", "    // An image copied from a note's read view"),
        "a paste in one cell": ("      if (c && range.index + range.length <= c.end) {", "      } else if (range && [data.text, data.html]"),
        "Save": ("  async function save(overrideBase) {", "    const len = pnTextLength(delta);"),
    }
    for name, (a, b) in regions.items():
        part = src[src.index(a):src.index(b, src.index(a))]
        code = chr(10).join(line.split("//")[0] for line in part.split(chr(10)))      # comments aside
        assert "pnRangeInTable" not in code and "table" not in code.lower(), name
    # A paste inside one cell keeps a stored image and its width.
    paste = src[src.index("function pnCellPaste(pasted) {"):src.index("// An editor table's cells")]
    assert "if (pnIsImage(op)) {" in paste and "const src = pnImageSrc(op.insert.image);" in paste
    assert "if (src) cur.push({ img: src, w: pnImageWidth(op.attributes && op.attributes.width) });" in paste
    assert "out = sg.img ? out.insert({ image: sg.img }, sg.w ? { width: sg.w } : undefined) : out.insert(sg.t, sg.a);" in paste
    assert "add = pnCellPaste(quill.clipboard.convert({ text: data.text, html: data.html }, {}));" in src
    # The 50-image cap still counts every image, cells included.
    assert "+ waiting + list.length > PN_IMAGES_PER_NOTE" in src
    assert "if (pnImageCount(delta) > PN_IMAGES_PER_NOTE) {" in src


def test_an_image_takes_one_place_in_a_cell_line():
    src = _read("static/pagenotes.js")
    assert "const PN_EMBED_CHAR = String.fromCharCode(0xfffc);" in src
    lines = src[src.index("function pnCellLines(quill, c) {"):src.index("function pnLineAt(")]
    assert "text += PN_EMBED_CHAR;   // an image (Landing 56) takes one place, in the text too" in lines
    # The read view's bullet test counts an image the same way.
    assert "return segs.map(sg => (sg.img ? PN_EMBED_CHAR : sg.t)).join('').startsWith(PN_CELL_BULLET);" in src


def test_the_image_size_bar_in_a_table():
    src = _read("static/pagenotes.js")
    assert "showImage(imagesOk ? pnSelectedImage(quill, r) : null);     // in a table cell too (Landing 56)" in src
    assert "!inside ? pnSelectedImage" not in src
    # The bar comes before the table bars, and says an image there stays within its column.
    assert src.index('aria-label="Image size" onKeyDown={back}>') < src.index('role="toolbar" aria-label="Table">')
    assert '''{inTable ? 'In a table an image is never wider than its column' : "Every size stays within the note's width"}''' in src
    # Both views draw tables at fixed column widths and cap an image at its box.
    css = _read("static/style.css")
    assert ".pn-table { width: 100%; table-layout: fixed;" in css
    assert ".pn-img { display: block; max-width: 100%;" in css
    assert ".pn-panel .ql-editor img { max-width: 100%;" in css


def test_uploads_are_kept_per_note_and_save_waits_for_them():
    src = _read("static/pagenotes.js")
    # Kept per note (they outlive an editor), one at a time in order.
    assert "const pnUploads = {};" in src and "ups.chain = ups.chain.then(async () => {" in src
    assert "ups.slots.forEach(slot => { slot.index = delta.transformPosition(slot.index); })" in src
    assert "quill.on('text-change', followEdits);" in src and "quill.off('text-change', followEdits);" in src
    assert "ups.editor = quill;" in src and "if (ups.editor === quill) ups.editor = null;" in src
    # Finished after its editor closed: into the note's draft, at its place.
    assert "if (st.editor) { slot.index = pnPlaceInEditor(st.editor, slot.index, url, width) + 1; return true; }" in src
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
    assert ('<img className="pn-img" src={seg.img} width={seg.w || undefined} alt="Image in note (opens full size)" '
            'loading="lazy" />' in src)
    assert "if (src) segs.push({ img: src, w: pnImageWidth(op.attributes && op.attributes.width), a: {} });" in src
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


# ── Landing 33: an image's display width ────────────────────────────────────

def test_the_display_width_rules_equal_the_servers():
    src = _read("static/pagenotes.js")
    assert int(_const(src, "PN_IMAGE_WIDTH_MIN")) == wp.PAGE_NOTE_IMAGE_WIDTH_MIN
    assert int(_const(src, "PN_IMAGE_WIDTH_MAX")) == wp.PAGE_NOTE_IMAGE_WIDTH_MAX
    js = _const(src, "PN_IMAGE_WIDTH_RE")
    assert js == r"/^[1-9][0-9]{1,3}$/" and wp._PAGE_NOTE_IMAGE_WIDTH_RE.pattern == js[2:-2]
    # Small / Medium / Large and the size a new wide image comes in at (Glenn, Oct 12: 320 / 560 / 800, Large).
    assert _const(src, "PN_IMAGE_SIZES") == "[['Small', 320], ['Medium', 560], ['Large', 800]]"
    assert int(_const(src, "PN_IMAGE_NEW_MAX")) == 800
    for px in (320, 560, 800):
        assert wp.PAGE_NOTE_IMAGE_WIDTH_MIN <= px <= wp.PAGE_NOTE_IMAGE_WIDTH_MAX


def test_the_width_is_kept_everywhere_an_image_goes():
    src = _read("static/pagenotes.js")
    # Saved and shown; copied images keep it; a new wide image comes in at Large.
    assert "const width = pnImageWidth(raw.attributes && raw.attributes.width);" in src
    assert "const width = pnImageWidth(node.getAttribute('width'));" in src
    assert "return new DeltaClass().insert({ image: src }, width ? { width } : undefined);" in src
    assert "pnPlaceImage(page, slot, data.url, pnNewImageWidth(data.width))" in src
    assert "return Number.isInteger(width) && width > PN_IMAGE_NEW_MAX ? String(PN_IMAGE_NEW_MAX) : null;" in src
    assert src.count("insert({ image: url }, width ? { width } : undefined)") == 2
    # Clear formatting clears text formats only: the width is not one of them.
    m = __import__("re").search(r"^const PN_INLINE = (.+?);", src, __import__("re").M)
    assert m and "width" not in m.group(1)


def test_the_image_size_bar():
    src = _read("static/pagenotes.js")
    assert 'className="pn-tablebar pn-imgsize" role="toolbar" aria-label="Image size"' in src
    assert "window.Quill.find(imageNodeRef.current).format('width', width || false);\n    quill.update('user');" in src
    # Sizes wider than the image are greyed out (unless that size is the one set).
    assert "const tooWide = own > 0 && px >= own;" in src and "disabled={tooWide && !on}" in src
    assert "aria-pressed={!imgSel.width}" in src
    # A click puts the cursor just after the image (never a selection Enter or typing would
    # replace); the bar acts on that image. Escape there moves to the bar, and Escape comes back.
    assert "quill.setSelection(quill.getIndex(blot) + 1, 0, 'user');" in src
    assert "const index = range.length === 1 ? range.index : range.index - 1;" in src
    # The bar acts on its image's node, wherever uploads have moved it.
    assert "const at = pnImageRange(quill, imageNodeRef.current);" in src and src.count("pnImageRange(quill, imageNodeRef.current)") == 2
    # An upload landing while the focus is in the bar (or elsewhere) leaves it there.
    assert "if (away && away.isConnected && document.activeElement !== away) away.focus({ preventScroll: true });" in src
    assert "quill.setSelection(away ? at : at + 1, 0, away ? 'api' : 'silent');" in src
    # A cursor move clears a hint, except while an upload is placed.
    assert "if (eventName === 'selection-change' && !pnPlacing.has(quill)) setHint('');" in src
    assert "pnPlacing.add(quill);\n  try {" in src and "} finally {\n    pnPlacing.delete(quill);\n  }" in src
    # A broken image's load is awaited once.
    assert "if (img && img.node && !img.natural && !waitingLoad.has(img.node)) {" in src
    assert "quill.root.addEventListener('click', onImageClick);" in src and "quill.root.removeEventListener('click', onImageClick);" in src
    assert "pnImageBar: { key: 'Escape', handler: function (range) {" in src
    assert src.index("pnImageBar: { key: 'Escape'") < src.index("pnTableBar: { key: 'Escape'")
    # The outline is set only when missing (a class change the editor sees, not an edit).
    assert "if (img && img.node && !img.node.classList.contains('pn-img-selected')) img.node.classList.add('pn-img-selected');" in src
    css = _read("static/style.css")
    assert ".pn-panel .ql-editor img.pn-img-selected { outline: 2px solid var(--accent);" in css

