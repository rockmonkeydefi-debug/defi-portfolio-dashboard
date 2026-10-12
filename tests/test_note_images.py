"""Landing 32: images in notes - the note_images table, POST /api/note-images
(upload), GET /api/note-images/<id> (serve), GET /api/note-images/usage, and
the note checker accepting stored images in the Notes page tabs only.

An image is stored once per distinct content (sha256), never deleted, PNG /
JPEG / WebP only recognised from its own bytes, whole files only, at most
NOTE_IMAGE_MAX_BYTES each and NOTE_IMAGES_TOTAL_MAX_BYTES together; the
upload needs the editor's header. A note refers to one as
{"insert": {"image": "/api/note-images/<id>"}}: no formatting, never on a
table cell's line, at most PAGE_NOTE_IMAGES_MAX per note, and every id must be
stored. The Spot panel keeps text only.

The image files below are tiny real files made once with Pillow (embedded, so
the tests don't need it). Real init_db() on a tmp_path SQLite file
(portfolio_db.get_db_path monkeypatched). No network.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import base64
import hashlib
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

PNG_3x2 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAMAAAACCAIAAAASFvFNAAAAGElEQVR4nGM8oaHBwMDAwMDAKFdxAsICAB7IAnkM9soFAAAAAElFTkSuQmCC")
JPEG_4x3 = base64.b64decode("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCAADAAQDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDzX7LD/wA8Y/8AvkUUUV/Qv1HCf8+o/wDgK/yPwr+18x/6CZ/+By/zP//Z")
JPEG_PROG_5x4 = base64.b64decode("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wgARCAAEAAUDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAb/xAAVAQEBAAAAAAAAAAAAAAAAAAAGB//aAAwDAQACEAMQAAABmhQgn//EABYQAAMAAAAAAAAAAAAAAAAAAAABEv/aAAgBAQABBQKUf//EABkRAAEFAAAAAAAAAAAAAAAAAAEABBRTkf/aAAgBAwEBPwGW4sOlf//EABkRAAEFAAAAAAAAAAAAAAAAAAABAxNSkf/aAAgBAgEBPwGBqqYf/8QAFhAAAwAAAAAAAAAAAAAAAAAAAAEx/9oACAEBAAY/Aoj/xAAVEAEBAAAAAAAAAAAAAAAAAAAA8f/aAAgBAQABPyGc/9oADAMBAAIAAwAAABAP/8QAFhEAAwAAAAAAAAAAAAAAAAAAAMHw/9oACAEDAQE/EL5n/8QAFhEAAwAAAAAAAAAAAAAAAAAAANHx/9oACAECAQE/EIxH/8QAFRABAQAAAAAAAAAAAAAAAAAAAPH/2gAIAQEAAT8QgH//2Q==")
WEBP_LOSSY_6x5 = base64.b64decode("UklGRlgAAABXRUJQVlA4IEwAAADQAgCdASoGAAUAAUAmJagCdLoB+AEsAwQD9APf/BTwAP7t2IgbQhLJmbGhpDK2Z/8432YIEfhH/kGfqpf/IV2rSqhAkHRFR7l8sYAA")
WEBP_LOSSLESS_7x3 = base64.b64decode("UklGRiIAAABXRUJQVlA4TBYAAAAvBoAAAA9wFKhbIR8FdP5DC/MX0f8w")
WEBP_ALPHA_8x2 = base64.b64decode("UklGRmIAAABXRUJQVlA4WAoAAAAQAAAABwAAAQAAQUxQSA0AAAABD/DA/4iIMP8R/Q8BAFZQOCAuAAAAMAEAnQEqCAACAAFAJiWgAANwAP7t2IgbQhLJmbGhpDK2R//+N4/uU/xT46AAAA==")
GIF_2x2 = base64.b64decode("R0lGODdhAgACAIEAAMgoKB54yAAAAAAAACwAAAAAAgACAAAIBwABAAgQICAAOw==")
BMP_2x2 = base64.b64decode("Qk1GAAAAAAAAADYAAAAoAAAAAgAAAAIAAAABABgAAAAAABAAAADEDgAAxA4AAAAAAAAAAAAAyHgeyHgeAAAoKMgoKMgAAA==")
PNG_4097x1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAEAEAAAABCAIAAAA+gZcVAAAAKElEQVR4nO3BMQEAAAgDIG2z/ikWyxoewDYZAAAAAAAAAAAAAADgvQPl5AEa3GHgAAAAAABJRU5ErkJggg==")

UPLOAD = "/api/note-images"
HEADER = {"X-Playbook-Upload": "1"}


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


def upload(client, data, headers=HEADER, content_type="image/png"):
    return client.post(UPLOAD, data=data, headers=headers, content_type=content_type)


def rows(db):
    return [dict(r) for r in db.execute("SELECT id, sha256, mime, width, height, bytes, created_at FROM note_images ORDER BY id")]


def img(url):
    return {"insert": {"image": url}}


def note(*ops):
    return {"ops": list(ops) + [{"insert": "\n"}]}


def put_note(client, page, delta, base_id=None):
    return client.put(f"/api/page-notes/{page}", json={"delta": delta, "base_id": base_id})


# ── Table ────────────────────────────────────────────────────────────────────

def test_table_exists_and_init_db_runs_twice(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info(note_images)")]
    assert cols == ["id", "sha256", "mime", "width", "height", "bytes", "data", "created_at"]
    portfolio_db.init_db()
    assert [r[1] for r in db.execute("PRAGMA table_info(note_images)")] == cols


GOOD = ("a" * 64, "image/png", 3, 2, 4, b"\x89PNG", "x")


@pytest.mark.parametrize("i,bad", [
    (0, "A" * 64), (0, "a" * 63), (0, "g" * 64),                 # sha256: lower-case hex, 64 characters
    (1, "image/gif"), (1, "image/svg+xml"), (1, "text/html"),   # only the three types
    (2, 0), (2, 4097), (2, "three"), (3, 0), (3, 4097),              # sides 1..4096, whole numbers
    (4, 0), (4, 2097153), (4, 5),                                # bytes: 1..2 MB and the data's length
    (5, "\\x89PNG"),                                             # data stored as text, not bytes
])
def test_the_table_refuses_bad_rows(db, i, bad):
    vals = list(GOOD)
    vals[i] = bad
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO note_images (sha256, mime, width, height, bytes, data, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)", vals)


def test_the_same_image_is_stored_once_by_the_table_too(db):
    db.execute("INSERT INTO note_images (sha256, mime, width, height, bytes, data, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", GOOD)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO note_images (sha256, mime, width, height, bytes, data, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", GOOD)


# ── Recognising an image from its bytes ──────────────────────────────────────

@pytest.mark.parametrize("data,want", [
    (PNG_3x2, ("image/png", 3, 2)),
    (JPEG_4x3, ("image/jpeg", 4, 3)),
    (JPEG_PROG_5x4, ("image/jpeg", 5, 4)),
    (WEBP_LOSSY_6x5, ("image/webp", 6, 5)),
    (WEBP_LOSSLESS_7x3, ("image/webp", 7, 3)),
    (WEBP_ALPHA_8x2, ("image/webp", 8, 2)),
    (PNG_4097x1, ("image/png", 4097, 1)),
])
def test_real_files_are_recognised(data, want):
    assert wp._note_image_sniff(data) == want


@pytest.mark.parametrize("data", [
    GIF_2x2, BMP_2x2,
    b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    b"<!doctype html><script>alert(1)</script>",
    PNG_3x2 + b"<html><script>alert(1)</script>",     # anything after the image
    PNG_3x2[:-12],                                       # cut short
    JPEG_4x3 + b"junk", JPEG_4x3[:-2],
    WEBP_LOSSY_6x5 + b"\x00", WEBP_LOSSY_6x5[:-1],
    b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"RIFF\x00\x00\x00\x00WEBP", b"", b"\x00" * 64,
])
def test_anything_else_is_not(data):
    assert wp._note_image_sniff(data) is None


# ── Upload ───────────────────────────────────────────────────────────────────

def test_upload_stores_the_image_and_returns_its_url(client, db):
    r = upload(client, WEBP_LOSSY_6x5, content_type="image/webp")
    assert r.status_code == 201
    body = r.get_json()
    assert body["url"] == f"/api/note-images/{body['id']}" and body["existing"] is False
    assert (body["mime"], body["width"], body["height"], body["bytes"]) == ("image/webp", 6, 5, len(WEBP_LOSSY_6x5))
    assert body["usage"] == {"count": 1, "bytes": len(WEBP_LOSSY_6x5), "max_bytes": 100 * 1024 * 1024,
                             "image_max_bytes": 2 * 1024 * 1024, "per_note_max": 50}
    got = rows(db)
    assert len(got) == 1 and got[0]["sha256"] == hashlib.sha256(WEBP_LOSSY_6x5).hexdigest()
    assert db.execute("SELECT data FROM note_images").fetchone()[0] == WEBP_LOSSY_6x5


def test_the_type_comes_from_the_bytes_not_the_request(client, db):
    r = upload(client, JPEG_4x3, content_type="image/png")
    assert r.status_code == 201 and r.get_json()["mime"] == "image/jpeg"


def test_the_same_image_twice_is_stored_once(client, db):
    first = upload(client, PNG_3x2).get_json()
    again = upload(client, PNG_3x2)
    assert again.status_code == 200
    assert again.get_json()["id"] == first["id"] and again.get_json()["existing"] is True
    assert len(rows(db)) == 1


def test_the_editor_header_is_required(client, db):
    for headers in ({}, {"X-Playbook-Upload": "0"}, {"X-Playbook-Upload": "yes"}):
        r = upload(client, PNG_3x2, headers=headers)
        assert r.status_code == 400 and "notes editor" in r.get_json()["error"]
    # A form post from another site can't add the header.
    r = client.post(UPLOAD, data={"file": (__import__("io").BytesIO(PNG_3x2), "x.png")}, content_type="multipart/form-data")
    assert r.status_code == 400
    assert rows(db) == []


@pytest.mark.parametrize("data", [
    b"", GIF_2x2, BMP_2x2, PNG_3x2 + b"<script>", b"<svg xmlns='http://www.w3.org/2000/svg'/>",
    b"<html></html>", JPEG_4x3[:-2],
])
def test_anything_but_a_whole_png_jpeg_or_webp_is_refused(client, db, data):
    r = upload(client, data)
    assert r.status_code == 400
    assert rows(db) == []


def test_more_than_4096_pixels_a_side_is_refused(client, db):
    r = upload(client, PNG_4097x1)
    assert r.status_code == 400 and "4096 pixels" in r.get_json()["error"]
    assert rows(db) == []


def test_more_than_2_mb_is_refused(client, db):
    big = PNG_3x2[:-12] + b"\x00" * (2 * 1024 * 1024) + PNG_3x2[-12:]
    r = upload(client, big)
    assert r.status_code == 413 and "2 MB" in r.get_json()["error"]
    assert rows(db) == []


def test_storage_full_is_refused_but_a_stored_image_still_answers(client, db, monkeypatch):
    first = upload(client, PNG_3x2).get_json()
    monkeypatch.setattr(wp, "NOTE_IMAGES_TOTAL_MAX_BYTES", len(PNG_3x2) + 10)
    r = upload(client, JPEG_4x3)
    assert r.status_code == 409 and "full" in r.get_json()["error"]
    assert r.get_json()["usage"]["count"] == 1
    assert len(rows(db)) == 1
    again = upload(client, PNG_3x2)
    assert again.status_code == 200 and again.get_json()["id"] == first["id"]


def test_login_gate(db, monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    c = wp.app.test_client()
    assert c.post(UPLOAD, data=PNG_3x2, headers=HEADER, content_type="image/png").status_code == 401
    assert c.get("/api/note-images/usage").status_code == 401
    db.execute("INSERT INTO note_images (sha256, mime, width, height, bytes, data, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (hashlib.sha256(PNG_3x2).hexdigest(), "image/png", 3, 2, len(PNG_3x2), PNG_3x2, "x"))
    db.commit()
    assert c.get("/api/note-images/1").status_code == 401
    assert len(rows(db)) == 1


# ── Serve and usage ──────────────────────────────────────────────────────────

def test_serve_returns_the_bytes_with_safe_headers(client, db):
    up = upload(client, JPEG_4x3).get_json()
    r = client.get(up["url"])
    assert r.status_code == 200 and r.data == JPEG_4x3 and r.mimetype == "image/jpeg"
    h = r.headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in h["Content-Security-Policy"] and "default-src 'none'" in h["Content-Security-Policy"]
    # Checked on every view (a restore can hand an id out again), cheaply by its ETag.
    assert h["Cache-Control"] == "private, no-cache"
    assert h["Cross-Origin-Resource-Policy"] == "same-origin"
    assert h["Content-Disposition"] == f'inline; filename="note-image-{up["id"]}.jpg"'
    assert h["ETag"] == '"' + hashlib.sha256(JPEG_4x3).hexdigest() + '"'
    again = client.get(up["url"], headers={"If-None-Match": h["ETag"]})
    assert again.status_code == 304 and again.data == b""


def test_a_304_does_not_read_the_image(client, db, monkeypatch):
    up = upload(client, JPEG_4x3).get_json()
    etag = client.get(up["url"]).headers["ETag"]
    seen = []
    real = portfolio_db.get_connection

    def traced():
        conn = real()
        conn.set_trace_callback(seen.append)
        return conn

    monkeypatch.setattr(portfolio_db, "get_connection", traced)
    again = client.get(up["url"], headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.data == b""
    assert again.headers["ETag"] == etag and again.headers["Cache-Control"] == "private, no-cache"
    reads = [s for s in seen if "FROM note_images" in s]
    assert reads and not any("data" in s.split("FROM")[0] for s in reads)
    # Another picture under that id (or none cached): the bytes are read and sent.
    seen.clear()
    full = client.get(up["url"], headers={"If-None-Match": '"' + "0" * 64 + '"'})
    assert full.status_code == 200 and full.data == JPEG_4x3
    assert any("SELECT data" in s for s in seen)


def test_unknown_images_are_404(client, db):
    upload(client, PNG_3x2)
    for path in ("/api/note-images/2", "/api/note-images/0", "/api/note-images/abc", "/api/note-images/-1",
                 "/api/note-images/99999999999", "/api/note-images/99999999999999999999999"):
        assert client.get(path).status_code == 404, path


def test_usage_and_reads_write_nothing(client, db):
    up = upload(client, PNG_3x2).get_json()
    before = rows(db)
    u = client.get("/api/note-images/usage")
    assert u.status_code == 200 and u.get_json()["count"] == 1 and u.get_json()["bytes"] == len(PNG_3x2)
    client.get(up["url"])
    assert rows(db) == before


# ── The note checker ─────────────────────────────────────────────────────────

def test_the_spot_note_keeps_text_only():
    body, text, err = wp._page_note_check(note(img("/api/note-images/1")))
    assert body is None and err == "only text can be saved (no images or other embeds)"
    assert wp._page_note_images_ok("spot") is False
    assert all(wp._page_note_images_ok(p) for p in ("notes-watchlist", "notes-nuggets", "notes-t1"))


def test_an_image_is_kept_as_its_url_and_shows_as_image_in_the_text():
    body, text, err = wp._page_note_check(note({"insert": "Setup "}, img("/api/note-images/7"), {"insert": " here"}),
                                          images_ok=True)
    assert err is None
    assert '{"insert":{"image":"/api/note-images/7"}}' in body
    assert text == "Setup [image] here"
    assert wp._page_note_image_ids(body) == [7]


def test_an_image_alone_is_not_an_empty_note():
    body, text, err = wp._page_note_check(note(img("/api/note-images/1")), images_ok=True)
    assert err is None and text == "[image]"


def test_text_only_notes_are_unchanged_with_images_allowed():
    delta = note({"insert": "Plain", "attributes": {"bold": True}})
    assert wp._page_note_check(delta, images_ok=True) == wp._page_note_check(delta)


@pytest.mark.parametrize("ins", [
    {"image": "https://example.com/x.png"}, {"image": "data:image/png;base64,iVBORw0KGgo="},
    {"image": "/api/note-images/0"}, {"image": "/api/note-images/01"}, {"image": "/api/note-images/1x"},
    {"image": "/api/note-images/1?x=1"}, {"image": "//evil.example/api/note-images/1"},
    {"image": "/static/x.png"}, {"image": 5}, {"image": "/api/note-images/1", "alt": "x"},
    {"video": "/api/note-images/1"}, {},
])
def test_only_images_from_this_app_are_accepted(ins):
    body, _, err = wp._page_note_check(note({"insert": ins}), images_ok=True)
    assert body is None and "added in the notes editor" in err


def test_an_image_carries_no_formatting():
    # Landing 33: a display width is its only attribute.
    for attrs in ({"bold": True}, {"link": "https://example.com"}, {"height": "200"}, {"alt": "x"},
                  {"width": "200", "bold": True}, {"width": "200", "height": "100"}):
        body, _, err = wp._page_note_check(note({"insert": {"image": "/api/note-images/1"}, "attributes": attrs}),
                                           images_ok=True)
        assert body is None and "formatting" in err, attrs
    # An empty attributes object is fine (dropped).
    body, _, err = wp._page_note_check(note({"insert": {"image": "/api/note-images/1"}, "attributes": {}}), images_ok=True)
    assert err is None and body == '{"ops":[{"insert":{"image":"/api/note-images/1"}},{"insert":"\\n"}]}'
    body, _, err = wp._page_note_check(note({"insert": {"image": "/api/note-images/1"}, "attributes": "wide"}),
                                       images_ok=True)
    assert body is None and err == "the note's formatting is not readable"


# ── Landing 33: an image's display width ─────────────────────────────────────

@pytest.mark.parametrize("width", ["50", "320", "560", "800", "1999", "4096"])
def test_an_image_keeps_its_display_width(width):
    body, text, err = wp._page_note_check(
        note({"insert": "Chart "}, {"insert": {"image": "/api/note-images/3"}, "attributes": {"width": width}}),
        images_ok=True)
    assert err is None and text == "Chart [image]"
    assert '{"attributes":{"width":"%s"},"insert":{"image":"/api/note-images/3"}}' % width in body
    assert wp._page_note_image_ids(body) == [3]


@pytest.mark.parametrize("width", ["49", "4097", "0", "050", "560px", "56.5", " 560", "560 ", "", "10000",
                                   "-560", 560, 560.0, None, True, ["560"]])
def test_a_display_width_out_of_range_or_not_digits_is_refused(width):
    body, _, err = wp._page_note_check(
        note({"insert": {"image": "/api/note-images/3"}, "attributes": {"width": width}}), images_ok=True)
    assert body is None and err == "an image's display width must be a whole number of pixels from 50 to 4096"


def test_a_sized_image_is_still_an_image_everywhere():
    sized = {"insert": {"image": "/api/note-images/1"}, "attributes": {"width": "320"}}
    # Never inside a table, at most 50, and only in the Notes tabs.
    cell = {"insert": "\n", "attributes": {"table": "row-1"}}
    assert wp._page_note_check({"ops": [sized, cell, {"insert": "\n"}]}, images_ok=True)[2] == "images can't go inside a table"
    many = [dict(sized) for _ in range(51)]
    assert "at most 50 images" in wp._page_note_check(note(*many), images_ok=True)[2]
    assert wp._page_note_check(note(sized))[2] == "only text can be saved (no images or other embeds)"
    # A width is not text: a cell's text limit and the plain text ignore it.
    assert wp._page_note_check(note(sized), images_ok=True)[1] == "[image]"


def test_a_notes_tab_saves_and_returns_a_sized_image(client, db):
    up = upload(client, PNG_3x2).get_json()
    sized = {"insert": {"image": up["url"]}, "attributes": {"width": "560"}}
    r = put_note(client, "notes-watchlist", note({"insert": "Chart "}, sized, img(up["url"])))
    assert r.status_code == 200
    got = client.get("/api/page-notes/notes-watchlist").get_json()
    assert got["delta"]["ops"][1] == sized and got["delta"]["ops"][2] == {"insert": {"image": up["url"]}}
    assert got["text"] == "Chart [image][image]"
    # Changing only the width is a change; the same width again is not.
    resized = {"insert": {"image": up["url"]}, "attributes": {"width": "320"}}
    r2 = put_note(client, "notes-watchlist", note({"insert": "Chart "}, resized, img(up["url"])), base_id=got["id"])
    assert r2.status_code == 200 and r2.get_json()["changed"] is True
    r3 = put_note(client, "notes-watchlist", note({"insert": "Chart "}, resized, img(up["url"])), base_id=r2.get_json()["id"])
    assert r3.status_code == 200 and r3.get_json()["changed"] is False
    # The stored image itself is untouched.
    assert client.get(up["url"]).data == PNG_3x2


def test_images_never_go_inside_a_table():
    cell = {"insert": "\n", "attributes": {"table": "row-1"}}
    for line in ([img("/api/note-images/1"), cell],
                 [img("/api/note-images/1"), {"insert": "after"}, cell],
                 [{"insert": "before"}, img("/api/note-images/1"), cell]):
        body, _, err = wp._page_note_check({"ops": line + [{"insert": "\n"}]}, images_ok=True)
        assert body is None and err == "images can't go inside a table"
    # An image on its own line next to a table is fine.
    ok = {"ops": [img("/api/note-images/1"), {"insert": "\n"}, {"insert": "A"}, cell, {"insert": "\n"}]}
    assert wp._page_note_check(ok, images_ok=True)[2] is None
    ok2 = {"ops": [{"insert": "A"}, cell, img("/api/note-images/1"), {"insert": "\n"}]}
    assert wp._page_note_check(ok2, images_ok=True)[2] is None


def test_images_on_headings_lists_and_quotes_are_fine():
    for attrs in ({"header": 2}, {"list": "bullet"}, {"blockquote": True}, {"align": "center"}):
        body, _, err = wp._page_note_check({"ops": [img("/api/note-images/1"), {"insert": "\n", "attributes": attrs}]},
                                           images_ok=True)
        assert err is None, attrs


def test_an_upload_without_a_length_is_still_capped(client, db):
    # As gunicorn hands over a chunked upload: the decoded body, no length,
    # the stream marked as ending where the body ends.
    def post(body):
        return client.post(UPLOAD, input_stream=__import__("io").BytesIO(body), headers=HEADER, content_type="image/png",
                           environ_overrides={"wsgi.input_terminated": True})
    big = PNG_3x2[:-12] + b"\x00" * (2 * 1024 * 1024) + PNG_3x2[-12:]
    assert post(big).status_code == 413
    assert rows(db) == []
    assert post(PNG_3x2).status_code == 201
    assert len(rows(db)) == 1


def test_at_most_50_images_in_a_note_and_they_dont_count_as_text():
    fifty = [img(f"/api/note-images/{i}") for i in range(1, 51)]
    body, text, err = wp._page_note_check(note({"insert": "x" * wp.PAGE_NOTE_TEXT_MAX}, *fifty), images_ok=True)
    assert err is None and text.count("[image]") == 50
    body, _, err = wp._page_note_check(note(*fifty, img("/api/note-images/51")), images_ok=True)
    assert body is None and "at most 50 images" in err


# ── Saving a note with images ────────────────────────────────────────────────

def test_a_notes_tab_saves_a_stored_image(client, db):
    up = upload(client, PNG_3x2).get_json()
    r = put_note(client, "notes-watchlist", note({"insert": "Chart "}, img(up["url"])))
    assert r.status_code == 200 and r.get_json()["changed"] is True
    got = client.get("/api/page-notes/notes-watchlist").get_json()
    assert got["delta"]["ops"][1] == {"insert": {"image": up["url"]}} and got["text"] == "Chart [image]"
    assert got["empty"] is False


def test_an_added_tab_saves_images_too(client, db):
    assert client.post("/api/note-tabs", json={"label": "Charts"}).status_code == 201
    up = upload(client, WEBP_LOSSLESS_7x3).get_json()
    assert put_note(client, "notes-t1", note(img(up["url"]))).status_code == 200


def test_an_image_that_isnt_stored_is_refused(client, db):
    up = upload(client, PNG_3x2).get_json()
    r = put_note(client, "notes-nuggets", note(img(up["url"]), img("/api/note-images/99")))
    assert r.status_code == 400 and "isn't stored" in r.get_json()["error"]
    assert db.execute("SELECT COUNT(*) FROM page_notes").fetchone()[0] == 0


def test_the_spot_panel_refuses_even_a_stored_image(client, db):
    up = upload(client, PNG_3x2).get_json()
    r = put_note(client, "spot", note(img(up["url"])))
    assert r.status_code == 400 and "only text" in r.get_json()["error"]
    assert db.execute("SELECT COUNT(*) FROM page_notes").fetchone()[0] == 0


def test_images_are_never_deleted(client, db):
    up = upload(client, PNG_3x2).get_json()
    first = put_note(client, "notes-watchlist", note(img(up["url"]))).get_json()
    put_note(client, "notes-watchlist", note({"insert": "image removed"}), first["id"])
    assert len(rows(db)) == 1 and client.get(up["url"]).status_code == 200
