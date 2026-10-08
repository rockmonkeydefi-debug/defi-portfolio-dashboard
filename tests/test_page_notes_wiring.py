"""Landing 19: the page notes panel's frontend wiring (static/pagenotes.js,
static/spotpnl.js, templates/index.html, static/style.css).

- the page loads pagenotes.js before spotpnl.js, and Quill only on demand,
  pinned to one version;
- the limits and format lists mirrored in pagenotes.js equal the server's;
- the two colour palettes stay readable on the dark theme;
- the saved note is never put into the page as HTML;
- the Spot page shows the panel for a page the server accepts.

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
    server = set(wp._PAGE_NOTE_FLAGS) | set(wp._PAGE_NOTE_COLOURS) | set(wp._PAGE_NOTE_BLOCK) | {"link"}
    assert formats == server


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
