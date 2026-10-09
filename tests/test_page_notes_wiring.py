"""Landing 19: the page notes panel's frontend wiring (static/pagenotes.js,
static/spotpnl.js, templates/index.html, static/style.css). Landing 20:
alignment and table styling. Landing 21: lines and bullets inside a cell.

- the page loads pagenotes.js before spotpnl.js, and Quill only on demand,
  pinned to one version;
- the limits, format lists and table row ids mirrored in pagenotes.js
  equal the server's (alignment, cell styles and their values included);
- the colour palettes stay readable on the dark theme;
- every cell style the editor sets is drawn by style.css;
- the saved note is never put into the page as HTML;
- the Spot page shows the panel for a page the server accepts;
- Landing 21: a line break and a bullet inside a table cell are saved as
  the characters the server tests pin, the editor's own break element never
  reaches the server, and Quill's table Enter / Up / Down / Delete are
  replaced in cells.

Reads the source files only; no app or database.
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
    m = re.search(r"^const " + name + r" = (.*?);\s*(?://.*)?$", src, re.M)
    assert m, name + " not found"
    return m.group(1)


def _lum(h):
    h = h.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _palette(src, name):
    m = re.search(r"const " + name + r" = \[(.*?)\];", src, re.S)
    assert m, name + " not found"
    return re.findall(r"\['(#[0-9a-f]{6})', '([^']+)'\]", m.group(1))


def test_scripts_load_in_order_and_quill_only_on_demand():
    html = _read("templates/index.html")
    journal = html.index('src="/static/spotjournal.js')
    notes = html.index('src="/static/pagenotes.js')
    spot = html.index('src="/static/spotpnl.js')
    assert journal < notes < spot
    assert "quill" not in html.lower()
    src = _read("static/pagenotes.js")
    assert _const(src, "PN_QUILL_JS") == "'https://unpkg.com/quill@2.0.3/dist/quill.js'"
    assert _const(src, "PN_QUILL_CSS") == "'https://unpkg.com/quill@2.0.3/dist/quill.snow.css'"


def test_limits_and_formats_match_the_server():
    src = _read("static/pagenotes.js")
    assert int(_const(src, "PN_TEXT_MAX")) == wp.PAGE_NOTE_TEXT_MAX
    assert int(_const(src, "PN_INDENT_MAX")) == wp.PAGE_NOTE_INDENT_MAX
    assert _const(src, "PN_HEADERS") == "[" + ", ".join(str(h) for h in wp.PAGE_NOTE_HEADERS) + "]"
    assert re.findall(r"'(\w+)'", _const(src, "PN_LISTS")) == list(wp.PAGE_NOTE_LISTS)
    m = re.search(r"const PN_FORMATS = \[(.*?)\];", src, re.S)
    formats = set(re.findall(r"'([\w-]+)'", m.group(1)))
    server = (set(wp._PAGE_NOTE_FLAGS) | set(wp._PAGE_NOTE_COLOURS) | set(wp._PAGE_NOTE_BLOCK)
              | set(wp._PAGE_NOTE_CELL) | {"link", "align"})
    assert formats == server
    assert set(wp._PAGE_NOTE_LINE_ONLY) == set(wp._PAGE_NOTE_BLOCK) | set(wp._PAGE_NOTE_CELL) | {"align"}


def test_tables_match_the_server():
    src = _read("static/pagenotes.js")
    m = re.search(r"const PN_ROW_RE = /\^(.*?)\$/;", src)
    assert m and m.group(1) == wp._PAGE_NOTE_ROW_RE.pattern
    assert "['blockquote', 'link', 'table']," in src
    assert "table: true," in src
    # The renumbered ids the page saves pass the server's check.
    assert "clean.table = 'row-' + rows.toString(36);" in src
    for n in (1, 35, 36, 10 ** 9):
        assert wp._PAGE_NOTE_ROW_RE.fullmatch("row-" + _base36(n))
    css = _read("static/style.css")
    assert ".pn-table td" in css and ".pn-panel .ql-editor td" in css


def test_alignment_and_cell_styles_match_the_server():
    src = _read("static/pagenotes.js")
    assert re.findall(r"'(\w+)'", _const(src, "PN_ALIGNS")) == list(wp.PAGE_NOTE_ALIGNS)
    assert "[{ align: [false, ...PN_ALIGNS] }]," in src
    assert int(_const(src, "PN_WIDTH_MIN")) == wp.PAGE_NOTE_WIDTH_MIN
    assert int(_const(src, "PN_WIDTH_MAX")) == wp.PAGE_NOTE_WIDTH_MAX
    assert re.findall(r"'(\w+)'", _const(src, "PN_BORDER_VALUES")) == list(wp.PAGE_NOTE_BORDERS)
    borders = re.findall(r"\[(false|'\w+'), '\w+'\]", _const(src, "PN_BORDERS"))
    assert borders[0] == "false" and all(b.strip("'") in wp.PAGE_NOTE_BORDERS for b in borders[1:])
    m = re.search(r"const PN_WIDTH_RE = /\^(.*?)\$/;", src)
    assert m and m.group(1) == wp._PAGE_NOTE_WIDTH_RE.pattern
    # The width rules: at most PN_WIDTH_COLS_MAX columns can each have the minimum.
    assert int(_const(src, "PN_WIDTH_COLS_MAX")) * wp.PAGE_NOTE_WIDTH_MIN <= 100
    assert 100 - wp.PAGE_NOTE_WIDTH_MIN == wp.PAGE_NOTE_WIDTH_MAX   # two columns: 5 + 95


def test_every_cell_style_is_drawn_by_the_stylesheet():
    src = _read("static/pagenotes.js")
    props = dict(re.findall(r"'(cell-\w+)': '(--pn-cell-\w+)'", _const(src, "PN_CELL_PROPS")))
    assert set(props) == set(wp._PAGE_NOTE_CELL)
    css = _read("static/style.css")
    rule = re.search(r"\.pn-panel \.ql-editor td \{(.*?)\}", css, re.S).group(1)
    for prop in props.values():
        assert "var(" + prop + "," in rule, prop


def test_table_palettes_are_readable_on_the_dark_theme():
    src = _read("static/pagenotes.js")
    css = _read("static/style.css")
    panel = re.search(r"--panel:\s*(#[0-9a-fA-F]{6})", css).group(1)
    cells = _palette(src, "PN_CELL_COLOURS")
    borders = _palette(src, "PN_BORDER_COLOURS")
    assert len(cells) >= 6 and len(borders) >= 6
    assert re.search(r"const PN_CELL_COLOURS = \[\[false, 'None'\],", src)
    assert re.search(r"const PN_BORDER_COLOURS = \[\[false, 'Default'\],", src)
    link = re.search(r"\.pn-link \{ color: (#[0-9a-f]{6});", css).group(1)
    for hex_, name in cells:
        assert _contrast("#ffffff", hex_) >= 9, (name, hex_)
        assert _contrast("#c9d1d9", hex_) >= 6, (name, hex_)
        assert _contrast(link, hex_) >= 4.5, (name, hex_)
    for hex_, name in borders:
        assert _contrast(hex_, panel) >= 4.8, (name, hex_)
    for hex_, _ in cells + borders:
        assert wp._PAGE_NOTE_HEX_RE.fullmatch(hex_)


def _base36(n):
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out or "0"


def test_palettes_are_readable_on_the_dark_theme():
    src = _read("static/pagenotes.js")
    css = _read("static/style.css")
    panel = re.search(r"--panel:\s*(#[0-9a-fA-F]{6})", css).group(1)
    colours = _palette(src, "PN_TEXT_COLOURS")
    highlights = _palette(src, "PN_HIGHLIGHTS")
    assert len(colours) >= 8 and len(highlights) >= 5
    for hex_, name in colours:
        assert _contrast(hex_, panel) >= 4.5, (name, hex_)
    for hex_, name in highlights:
        assert _contrast("#ffffff", hex_) >= 4.5, (name, hex_)
    # Every value the pickers offer passes the server's colour check.
    for hex_, _ in colours + highlights:
        assert wp._PAGE_NOTE_HEX_RE.fullmatch(hex_)


def test_the_note_is_never_put_into_the_page_as_html():
    src = _read("static/pagenotes.js")
    assert "dangerouslySetInnerHTML" not in src
    assert re.findall(r"innerHTML[^;]*;", src) == ["innerHTML = '';"]
    assert "function PageNotesRead(" in src and "pnSegment(" in src


def test_spot_page_shows_the_panel_for_a_known_page():
    src = _read("static/spotpnl.js")
    m = re.search(r'<NotesPanel page="(\w+)" hideValues=\{hideValues\}', src)
    assert m and m.group(1) in wp.PAGE_NOTE_PAGES
    assert "const NotesPanel = window.PageNotesPanel;" in src
    assert "window.PageNotesPanel = PageNotesPanel;" in _read("static/pagenotes.js")
    css = _read("static/style.css")
    for cls in (".spot-head", ".spot-head-title", ".spot-head-notes", ".spot-head-tabs", ".spot-head-contracts", ".pn-panel"):
        assert cls + " " in css or cls + "{" in css


def test_the_routes_the_panel_calls_exist():
    src = _read("static/pagenotes.js")
    assert src.count("'/api/page-notes/' + page") == 2
    rules = {(r.rule, m) for r in wp.app.url_map.iter_rules() for m in r.methods}
    assert ("/api/page-notes/<page>", "GET") in rules
    assert ("/api/page-notes/<page>", "PUT") in rules


def test_lines_and_bullets_inside_a_cell_are_saved_as_text():
    src = _read("static/pagenotes.js")
    # The saved characters (pinned on the server by test_page_notes.py): U+2028
    # for a line break inside a cell, a bullet and a space for a bullet line.
    assert _const(src, "PN_CELL_BREAK") == "String.fromCharCode(0x2028)"
    assert _const(src, "PN_CELL_BULLET") == "String.fromCharCode(0x2022) + ' '"
    assert chr(0x2028) not in src and chr(0x2022) not in src   # written as codes, never raw
    # The break element is the editor's own: not a format the server knows,
    # added to the editor's formats only, saved as the character and turned
    # back into the element when the editor opens.
    brk = _const(src, "PN_BREAK_FORMAT").strip("'")
    server = set(wp._PAGE_NOTE_FLAGS) | set(wp._PAGE_NOTE_COLOURS) | set(wp._PAGE_NOTE_LINE_ONLY) | {"link"}
    assert brk and brk not in server
    assert "formats: PN_FORMATS.concat([PN_BREAK_FORMAT])," in src
    assert "const op = pnIsBreak(raw) ? { insert: PN_CELL_BREAK, attributes: raw.attributes } : raw;" in src
    assert "quill.setContents(pnToEditor(start), 'silent');" in src
    # The read view starts a new line at the same character.
    assert "sg.t.split(PN_CELL_BREAK)" in src


def test_quills_table_keys_are_replaced_in_cells():
    src = _read("static/pagenotes.js")
    for name in ("table enter", "table up", "table down", "table delete"):
        assert "'" + name + "': null," in src, name
    for name in ("table enter", "table up", "table down"):
        assert "quillKeys['" + name + "'].handler" in src, name
    for name, key in (("pnCellEnter", "Enter"), ("pnCellShiftEnter", "Enter"),
                      ("pnCellUp", "ArrowUp"), ("pnCellDown", "ArrowDown"), ("pnCellDelete", "Delete")):
        assert re.search(name + r": \{ key: '" + key + r"',[^}]*format: \['table'\]", src), name
    assert "if (value === 'bullet') { setHint(''); pnToggleCellBullets(q, range); return; }" in src
    assert "quill.clipboard.onPaste = " in src and "quill.clipboard.onCopy = " in src
    css = _read("static/style.css")
    for cls in (".pn-cline", ".pn-cbullet", ".pn-cmarker"):
        assert cls + " {" in css, cls
