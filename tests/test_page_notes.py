"""Landing 19: page notes - the append-only page_notes table and
GET / PUT /api/page-notes/<page> (the Spot page's formatted notes box,
tables included). Landing 20: alignment and table styling (cell colours,
column widths, the table's border). Landing 21: lines and bullets inside a
table cell are plain text (a line break inside a cell is saved as U+2028,
LINE SEPARATOR; a bullet line starts with a bullet and a space), so the
server keeps them like any other text.

The note is a Quill Delta document checked by _page_note_check: text inserts
only, an allowlist of formats with checked values, size limits. Saves carry
the id of the version the edit started from; a different latest version
answers 409. An unchanged document writes nothing.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). No network.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import json
import sqlite3
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db

URL = "/api/page-notes/spot"

# Every allowed format once.
FULL = {"ops": [
    {"insert": "Plan", "attributes": {"bold": True}},
    {"insert": "\n", "attributes": {"header": 1}},
    {"insert": "Watch "},
    {"insert": "BTC", "attributes": {"color": "#ff8a8a", "background": "#5c1f1f", "italic": True}},
    {"insert": " and "},
    {"insert": "ETH", "attributes": {"underline": True, "strike": True}},
    {"insert": "\n"},
    {"insert": "Weekly flip", "attributes": {"link": "https://example.com/chart"}},
    {"insert": "\n", "attributes": {"list": "bullet"}},
    {"insert": "Second"},
    {"insert": "\n", "attributes": {"list": "ordered", "indent": 1}},
    {"insert": "Done"},
    {"insert": "\n", "attributes": {"list": "checked"}},
    {"insert": "To do"},
    {"insert": "\n", "attributes": {"list": "unchecked"}},
    {"insert": "Quote"},
    {"insert": "\n", "attributes": {"blockquote": True}},
    {"insert": "mail", "attributes": {"link": "mailto:me@example.com"}},
    {"insert": "\n", "attributes": {"header": 3}},
]}


# A 2 x 3 table between two lines: each cell's text ends with a line break
# carrying its row's id; an empty cell is just the line break.
TABLE = {"ops": [
    {"insert": "Watchlist\n"},
    {"insert": "Token"}, {"insert": "\n", "attributes": {"table": "row-1"}},
    {"insert": "Entry", "attributes": {"bold": True}}, {"insert": "\n", "attributes": {"table": "row-1"}},
    {"insert": "Stop"}, {"insert": "\n", "attributes": {"table": "row-1"}},
    {"insert": "BTC", "attributes": {"color": "#4fdd8e"}}, {"insert": "\n", "attributes": {"table": "row-2"}},
    {"insert": "82,000"}, {"insert": "\n\n", "attributes": {"table": "row-2"}},
    {"insert": "after the table\n"},
]}


# Landing 20: a styled 2 x 2 table (column widths, a cell colour, a thick
# amber border, a centred and a right-aligned cell) and aligned lines.
_B = {"cell-bw": "3px", "cell-bc": "#ffb52e"}
STYLED = {"ops": [
    {"insert": "Centred title"}, {"insert": "\n", "attributes": {"align": "center", "header": 2}},
    {"insert": "Pair"}, {"insert": "\n", "attributes": {"table": "row-1", "cell-w": "30%", "cell-bg": "#1b5435", **_B}},
    {"insert": "Size"}, {"insert": "\n", "attributes": {"table": "row-1", "cell-w": "70%", "align": "right", **_B}},
    {"insert": "SOL"}, {"insert": "\n", "attributes": {"table": "row-2", "cell-w": "30%", "align": "center", **_B}},
    {"insert": "12"}, {"insert": "\n", "attributes": {"table": "row-2", "cell-w": "70%", "align": "right", **_B}},
    {"insert": "right line"}, {"insert": "\n", "attributes": {"align": "right"}},
    {"insert": "centred item"}, {"insert": "\n", "attributes": {"align": "center", "list": "bullet"}},
]}


def doc(*texts):
    return {"ops": [{"insert": "".join(texts) + "\n"}]}


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    conn = portfolio_db.get_connection()
    yield conn
    conn.close()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(wp.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP")))
    monkeypatch.setattr(wp.requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP")))
    monkeypatch.setattr(threading.Thread, "start", lambda self, *a, **k: (_ for _ in ()).throw(AssertionError("thread")))
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def rows(db, page="spot"):
    return [dict(r) for r in db.execute("SELECT * FROM page_notes WHERE page = ? ORDER BY id", (page,))]


def put(client, delta, base_id):
    return client.put(URL, json={"delta": delta, "base_id": base_id})


# ── Table ────────────────────────────────────────────────────────────────────

def test_table_and_index_exist_and_init_db_runs_twice(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info(page_notes)")]
    assert cols == ["id", "page", "body_json", "body_text", "created_at"]
    idx = {r[1] for r in db.execute("PRAGMA index_list(page_notes)")}
    assert "idx_page_notes_page" in idx
    portfolio_db.init_db()
    assert [r[1] for r in db.execute("PRAGMA table_info(page_notes)")] == cols


def test_page_must_not_be_blank(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO page_notes (page, body_json, body_text, created_at) VALUES ('', '{}', '', 'x')")


# ── GET ──────────────────────────────────────────────────────────────────────

def test_get_before_any_save(client):
    r = client.get(URL)
    assert r.status_code == 200
    assert r.get_json() == {"page": "spot", "id": None, "delta": None, "text": "", "saved_at": None, "empty": True}


def test_unknown_page_is_404(client):
    assert client.get("/api/page-notes/perps").status_code == 404
    assert client.put("/api/page-notes/perps", json={"delta": doc("x"), "base_id": None}).status_code == 404


def test_login_gate(db, monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    c = wp.app.test_client()
    assert c.get(URL).status_code == 401
    assert c.put(URL, json={"delta": doc("x"), "base_id": None}).status_code == 401
    assert rows(db) == []


# ── PUT: saving ──────────────────────────────────────────────────────────────

def test_save_every_format_and_read_it_back(client, db):
    r = put(client, FULL, None)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["changed"] is True and body["page"] == "spot" and body["empty"] is False
    assert body["delta"] == FULL
    assert body["text"] == "Plan\nWatch BTC and ETH\nWeekly flip\nSecond\nDone\nTo do\nQuote\nmail"
    assert body["saved_at"].endswith("+00:00")
    stored = rows(db)
    assert len(stored) == 1 and stored[0]["id"] == body["id"]
    assert json.loads(stored[0]["body_json"]) == FULL
    g = client.get(URL).get_json()
    assert g == {k: v for k, v in body.items() if k != "changed"}


def test_save_a_table(client, db):
    r = put(client, TABLE, None)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["delta"] == TABLE
    assert body["text"] == "Watchlist\nToken\nEntry\nStop\nBTC\n82,000\n\nafter the table"


def test_save_a_styled_table_and_aligned_lines(client, db):
    r = put(client, STYLED, None)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["delta"] == STYLED
    assert body["text"] == "Centred title\nPair\nSize\nSOL\n12\nright line\ncentred item"
    assert json.loads(rows(db)[0]["body_json"]) == STYLED


def test_notes_saved_before_table_styling_still_save():
    # Landing 19 documents have no cell formats; they pass unchanged.
    for d in (FULL, TABLE):
        body_json, _, err = wp._page_note_check(d)
        assert err is None and json.loads(body_json) == d


def test_stored_json_is_compact_with_sorted_keys(client, db):
    put(client, {"ops": [{"attributes": {"italic": True, "bold": True}, "insert": "é ✓"}, {"insert": "\n"}]}, None)
    assert rows(db)[0]["body_json"] == '{"ops":[{"attributes":{"bold":true,"italic":true},"insert":"é ✓"},{"insert":"\\n"}]}'


def test_an_empty_attributes_object_is_dropped(client):
    r = put(client, {"ops": [{"insert": "a", "attributes": {}}, {"insert": "\n"}]}, None)
    assert r.get_json()["delta"] == {"ops": [{"insert": "a"}, {"insert": "\n"}]}


def test_unchanged_document_writes_nothing(client, db):
    first = put(client, FULL, None).get_json()
    again = put(client, FULL, first["id"])
    assert again.status_code == 200
    assert again.get_json()["changed"] is False and again.get_json()["id"] == first["id"]
    assert len(rows(db)) == 1


def test_every_save_is_kept_and_the_latest_wins(client, db):
    a = put(client, doc("first"), None).get_json()
    b = put(client, doc("second"), a["id"]).get_json()
    c = put(client, doc("third"), b["id"]).get_json()
    stored = rows(db)
    assert [r["body_text"] for r in stored] == ["first", "second", "third"]
    assert client.get(URL).get_json()["id"] == c["id"] and client.get(URL).get_json()["text"] == "third"


def test_an_empty_note_saves_and_reads_as_empty(client):
    a = put(client, doc("something"), None).get_json()
    r = put(client, {"ops": [{"insert": "\n"}]}, a["id"]).get_json()
    assert r["changed"] is True and r["empty"] is True and r["text"] == ""
    assert client.get(URL).get_json()["empty"] is True


def test_markup_is_kept_as_plain_text(client):
    r = put(client, doc("<script>alert(1)</script> <b>x</b>"), None).get_json()
    assert r["text"] == "<script>alert(1)</script> <b>x</b>"
    assert r["delta"]["ops"][0]["insert"].startswith("<script>")


# ── PUT: versions ────────────────────────────────────────────────────────────

def test_a_stale_base_answers_409_with_the_current_version(client, db):
    a = put(client, doc("mine"), None).get_json()
    put(client, doc("other tab"), a["id"])
    r = put(client, doc("my late edit"), a["id"])
    assert r.status_code == 409
    body = r.get_json()
    assert "another tab" in body["error"]
    assert body["current"]["text"] == "other tab"
    assert [x["body_text"] for x in rows(db)] == ["mine", "other tab"]


def test_a_null_base_when_a_note_exists_is_409(client, db):
    put(client, doc("existing"), None)
    r = put(client, doc("new"), None)
    assert r.status_code == 409 and r.get_json()["current"]["text"] == "existing"
    assert len(rows(db)) == 1


def test_a_base_when_no_note_exists_is_409(client, db):
    r = put(client, doc("x"), 7)
    assert r.status_code == 409 and r.get_json()["current"]["id"] is None
    assert rows(db) == []


# ── PUT: checks ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body", [
    None, [], "text", {"delta": doc("x")}, {"base_id": None},
    {"delta": doc("x"), "base_id": "1"}, {"delta": doc("x"), "base_id": True},
    {"delta": doc("x"), "base_id": 0}, {"delta": doc("x"), "base_id": 1.5},
])
def test_bad_bodies_are_400(client, db, body):
    r = client.put(URL, data=json.dumps(body), content_type="application/json")
    assert r.status_code == 400
    assert rows(db) == []


def T(attrs, insert="x"):
    return {"ops": [{"insert": insert, "attributes": attrs}, {"insert": "\n"}]}


def L(attrs, text="line"):
    return {"ops": [{"insert": text}, {"insert": "\n", "attributes": attrs}]}


@pytest.mark.parametrize("delta", [
    None, [], "x", {}, {"ops": []}, {"ops": "x"}, {"ops": [{"insert": "x\n"}], "extra": 1},
    {"ops": [{"retain": 3}]}, {"ops": [{"delete": 1}]},
    {"ops": [{"insert": "x", "retain": 1}]},
    {"ops": [{"insert": {"image": "https://example.com/a.png"}}, {"insert": "\n"}]},
    {"ops": [{"insert": {"video": "x"}}, {"insert": "\n"}]},
    {"ops": [{"insert": ""}, {"insert": "\n"}]},
    {"ops": [{"insert": 5}]},
    {"ops": ["x"]},
    {"ops": [{"insert": "x", "attributes": "bold"}, {"insert": "\n"}]},
    # unknown formats
    T({"font": "serif"}), T({"size": "large"}), T({"script": "sub"}), T({"code": True}),
    L({"code-block": True}), T({"image": "x"}), L({"direction": "rtl"}), L({"cell": "x"}),
    # bad values
    T({"bold": "true"}), T({"bold": 1}), T({"italic": False}),
    T({"color": "red"}), T({"color": "#fff"}), T({"color": "#ff0000; display:none"}), T({"color": "rgb(1,2,3)"}),
    T({"background": "#12345g"}), T({"background": None}),
    T({"link": "javascript:alert(1)"}), T({"link": "about:blank"}), T({"link": "example.com"}),
    T({"link": "https://a b"}), T({"link": "https://" + "a" * 2000}), T({"link": "tel:123"}), T({"link": 5}),
    L({"header": 4}), L({"header": "1"}), L({"header": True}), L({"header": 0}),
    L({"list": "check"}), L({"list": "dots"}), L({"list": True}),
    L({"indent": 0}), L({"indent": 9}), L({"indent": True}), L({"indent": "1"}),
    L({"blockquote": "yes"}),
    # line formats on text
    T({"header": 1}), T({"list": "bullet"}), T({"indent": 1}), T({"blockquote": True}),
    T({"header": 2}, insert="x\n"), T({"table": "row-1"}),
    # table cells
    L({"table": "1"}), L({"table": 1}), L({"table": "row-ABC"}), L({"table": "row-"}), L({"table": "row-" + "a" * 17}),
    L({"table": "row-1 x"}), L({"table": True}), L({"table": None}),
    L({"table": "row-1", "header": 1}), L({"table": "row-1", "list": "bullet"}),
    L({"table": "row-1", "indent": 1}), L({"table": "row-1", "blockquote": True}),
    # alignment (Landing 20): centre and right only, on lines only
    L({"align": "left"}), L({"align": "justify"}), L({"align": True}), L({"align": "Center"}), L({"align": ""}),
    T({"align": "center"}),
    # cell styles (Landing 20): table cells only, checked values
    L({"cell-bg": "#1b5435"}), L({"cell-w": "30%"}), L({"cell-bw": "2px"}), L({"cell-bc": "#ffb52e"}),
    L({"header": 1, "cell-bg": "#1b5435"}), T({"table": "row-1", "cell-bg": "#1b5435"}),
    L({"table": "row-1", "cell-bg": "green"}), L({"table": "row-1", "cell-bg": "#fff"}),
    L({"table": "row-1", "cell-bg": "#1b5435;x"}), L({"table": "row-1", "cell-bg": None}),
    L({"table": "row-1", "cell-bc": "rgb(1,2,3)"}), L({"table": "row-1", "cell-bc": 0}),
    L({"table": "row-1", "cell-w": "4%"}), L({"table": "row-1", "cell-w": "96%"}), L({"table": "row-1", "cell-w": "100%"}),
    L({"table": "row-1", "cell-w": "30"}), L({"table": "row-1", "cell-w": 30}), L({"table": "row-1", "cell-w": "30.5%"}),
    L({"table": "row-1", "cell-w": "05%"}), L({"table": "row-1", "cell-w": "30px"}), L({"table": "row-1", "cell-w": " 30%"}),
    L({"table": "row-1", "cell-bw": "4px"}), L({"table": "row-1", "cell-bw": "0px"}), L({"table": "row-1", "cell-bw": 2}),
    L({"table": "row-1", "cell-bw": "2px solid"}),
])
def test_documents_that_fail_the_check_are_400(client, db, delta):
    r = put(client, delta, None)
    assert r.status_code == 400, r.get_json()
    assert r.get_json()["error"]
    assert rows(db) == []


def test_text_limit_counts_characters_without_trailing_line_breaks(client, db):
    ok = put(client, {"ops": [{"insert": "é" * wp.PAGE_NOTE_TEXT_MAX + "\n\n\n"}]}, None)
    assert ok.status_code == 200
    over = put(client, {"ops": [{"insert": "a" * (wp.PAGE_NOTE_TEXT_MAX + 1) + "\n"}]}, ok.get_json()["id"])
    assert over.status_code == 400 and "10,000" in over.get_json()["error"]
    assert len(rows(db)) == 1


def test_json_size_limit(client, db):
    link = "https://example.com/" + "p" * 60
    ops = []
    for i in range(1500):
        ops.append({"insert": "ab", "attributes": {"link": link, "color": "#ff8a8a", "background": "#1d4d33"}})
        ops.append({"insert": "c"})
    ops.append({"insert": "\n"})
    r = put(client, {"ops": ops}, None)
    assert r.status_code == 400 and "too much formatting" in r.get_json()["error"]
    assert rows(db) == []


def test_ops_limit(client, db):
    ops = [{"insert": "a", "attributes": {"bold": True}} if i % 2 else {"insert": "b"}
           for i in range(wp.PAGE_NOTE_OPS_MAX + 1)]
    r = put(client, {"ops": ops}, None)
    assert r.status_code == 400 and rows(db) == []


def test_check_function_directly():
    body_json, text, err = wp._page_note_check(FULL)
    assert err is None and json.loads(body_json) == FULL and text.startswith("Plan\n")
    assert wp._page_note_check({"ops": [{"insert": "x"}]})[1] == "x"   # no trailing line break needed
    assert wp._page_note_check(L({"list": "bullet"}, text="a"))[2] is None
    # A line format on several line breaks at once (two empty list items) is fine.
    assert wp._page_note_check({"ops": [{"insert": "\n\n", "attributes": {"list": "bullet"}}]})[2] is None
    # Inline formats inside a table cell are fine; so is a row of empty cells.
    assert wp._page_note_check(TABLE)[2] is None
    assert wp._page_note_check({"ops": [{"insert": "\n\n\n", "attributes": {"table": "row-z9"}}]})[2] is None


def test_cell_styles_and_alignment_limits():
    cell = lambda **a: wp._page_note_check(L({"table": "row-1", **a}))[2]
    for w in (wp.PAGE_NOTE_WIDTH_MIN, 50, wp.PAGE_NOTE_WIDTH_MAX):
        assert cell(**{"cell-w": f"{w}%"}) is None
    for bw in wp.PAGE_NOTE_BORDERS:
        assert cell(**{"cell-bw": bw}) is None
    assert cell(**{"cell-bg": "#ABCDEF", "cell-bc": "#abcdef"}) is None   # either case, as color / background
    for a in wp.PAGE_NOTE_ALIGNS:
        assert cell(align=a) is None
        assert wp._page_note_check(L({"align": a}))[2] is None
        assert wp._page_note_check(L({"align": a, "header": 1}))[2] is None
        assert wp._page_note_check(L({"align": a, "list": "ordered", "indent": 2}))[2] is None
    # Every cell format at once, on several empty cells of one row.
    every = {"table": "row-a", "cell-bg": "#0f5555", "cell-w": "25%", "cell-bw": "2px", "cell-bc": "#8cc8ff", "align": "center"}
    assert wp._page_note_check({"ops": [{"insert": "\n\n\n\n", "attributes": every}]})[2] is None
    # The messages say what went wrong.
    assert "table cell" in wp._page_note_check(L({"cell-bg": "#0f5555"}))[2]
    assert "cell-w" in cell(**{"cell-w": "3%"})
    assert "align" in wp._page_note_check(L({"align": "justify"}))[2]


# ── Landing 21: lines and bullets inside a table cell ────────────────────────
# The editor saves a line break inside a cell as U+2028 (LINE SEPARATOR) in
# the cell's text and a bullet line as one that starts with a bullet and a
# space. To the server they are ordinary text: these tests pin that it keeps
# them unchanged and counts each break as one character.

LS = chr(0x2028)
BULLET = chr(0x2022) + " "
CELL_LINES = {"ops": [
    {"insert": "Thesis"}, {"insert": "\n", "attributes": {"table": "row-1", "cell-w": "30%"}},
    {"insert": BULLET + "Weekly noodle up" + LS + BULLET},
    {"insert": "Volume", "attributes": {"bold": True}},
    {"insert": " rising" + LS + "plain line" + LS},
    {"insert": "\n", "attributes": {"table": "row-1", "cell-w": "70%"}},
    {"insert": "after" + LS + "the table\n"},
]}


def test_lines_and_bullets_inside_a_cell_are_kept_as_text(client, db):
    r = put(client, CELL_LINES, None)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["delta"] == CELL_LINES and body["empty"] is False
    assert body["text"] == ("Thesis\n" + BULLET + "Weekly noodle up" + LS + BULLET + "Volume rising" + LS
                            + "plain line" + LS + "\nafter" + LS + "the table")
    assert json.loads(rows(db)[0]["body_json"]) == CELL_LINES
    assert client.get(URL).get_json()["delta"] == CELL_LINES
    # Saved again unchanged, it writes nothing.
    again = put(client, CELL_LINES, body["id"]).get_json()
    assert again["changed"] is False and len(rows(db)) == 1


def test_a_line_break_inside_a_cell_counts_as_one_character(client, db):
    cell = lambda text: {"ops": [{"insert": text}, {"insert": "\n", "attributes": {"table": "row-1"}}]}
    full = "a" * (wp.PAGE_NOTE_TEXT_MAX - 1) + LS
    ok = put(client, cell(full), None)
    assert ok.status_code == 200, ok.get_json()
    over = put(client, cell(full + LS), ok.get_json()["id"])
    assert over.status_code == 400 and "10,000" in over.get_json()["error"]
    assert len(rows(db)) == 1


# ── Landing 24: the Notes page's two tabs ────────────────────────────────────
# The Notes page (Trading menu) has two tabs, Watchlist and Nuggets. Each is
# its own page in page_notes, with its own versions and its own conflict
# check; the Spot note is unaffected.

NOTES_TABS = ("notes-watchlist", "notes-nuggets")


def put_page(client, page, delta, base_id):
    return client.put("/api/page-notes/" + page, json={"delta": delta, "base_id": base_id})


def test_the_notes_tabs_are_known_pages(client):
    assert wp.PAGE_NOTE_PAGES == ("spot",) + NOTES_TABS
    for page in NOTES_TABS:
        r = client.get("/api/page-notes/" + page)
        assert r.status_code == 200
        assert r.get_json() == {"page": page, "id": None, "delta": None, "text": "", "saved_at": None, "empty": True}


def test_each_notes_tab_saves_on_its_own(client, db):
    w = put_page(client, "notes-watchlist", TABLE, None)
    assert w.status_code == 200, w.get_json()
    assert w.get_json()["page"] == "notes-watchlist" and w.get_json()["delta"] == TABLE
    # The other tab and the Spot note are still empty; a first save there starts from null.
    assert client.get("/api/page-notes/notes-nuggets").get_json()["empty"] is True
    assert client.get(URL).get_json()["id"] is None
    n = put_page(client, "notes-nuggets", doc("Cut losers fast"), None)
    assert n.status_code == 200, n.get_json()
    s = put(client, doc("spot note"), None)
    assert s.status_code == 200, s.get_json()
    assert [r["body_text"] for r in rows(db, "notes-watchlist")] == ["Watchlist\nToken\nEntry\nStop\nBTC\n82,000\n\nafter the table"]
    assert [r["body_text"] for r in rows(db, "notes-nuggets")] == ["Cut losers fast"]
    assert [r["body_text"] for r in rows(db, "spot")] == ["spot note"]
    # Each tab keeps its own versions.
    w2 = put_page(client, "notes-watchlist", doc("second"), w.get_json()["id"])
    assert w2.status_code == 200 and w2.get_json()["changed"] is True
    assert len(rows(db, "notes-watchlist")) == 2 and len(rows(db, "notes-nuggets")) == 1
    assert client.get("/api/page-notes/notes-nuggets").get_json()["text"] == "Cut losers fast"


def test_a_conflict_on_one_notes_tab_leaves_the_others_alone(client, db):
    first = put_page(client, "notes-watchlist", doc("a"), None).get_json()
    put_page(client, "notes-watchlist", doc("b"), first["id"])
    stale = put_page(client, "notes-watchlist", doc("c"), first["id"])
    assert stale.status_code == 409
    assert stale.get_json()["current"]["page"] == "notes-watchlist"
    assert stale.get_json()["current"]["text"] == "b"
    # The other tab's first save is not affected by the watchlist's versions.
    ok = put_page(client, "notes-nuggets", doc("tip"), None)
    assert ok.status_code == 200, ok.get_json()
    # A base id from another tab is a conflict, not a save.
    cross = put_page(client, "notes-nuggets", doc("tip 2"), first["id"])
    assert cross.status_code == 409
    assert [r["body_text"] for r in rows(db, "notes-nuggets")] == ["tip"]


def test_other_page_names_stay_unknown(client, db):
    for page in ("notes", "notes-other", "Notes-Watchlist", "watchlist", "nuggets", "notes-watchlist-2"):
        assert client.get("/api/page-notes/" + page).status_code == 404, page
        assert put_page(client, page, doc("x"), None).status_code == 404, page
    assert db.execute("SELECT COUNT(*) FROM page_notes").fetchone()[0] == 0
