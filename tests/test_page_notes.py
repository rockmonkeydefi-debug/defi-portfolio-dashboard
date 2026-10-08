"""Landing 19: page notes - the append-only page_notes table and
GET / PUT /api/page-notes/<page> (the Spot page's formatted notes box).

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
    L({"align": "center"}), L({"code-block": True}), T({"image": "x"}),
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
    T({"header": 2}, insert="x\n"),
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
