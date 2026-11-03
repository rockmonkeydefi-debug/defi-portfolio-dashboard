"""Landing 88: a Spot position's Summary written in the Notes page editor.

Covers: the three nullable columns the landing adds (spot_position_notes.body_json,
spot_note_updates.body_json, note_revisions.old_json) and their upgrade of an older
database; GET /api/spot/position-notes/view; PUT /api/spot/position-notes with
{"delta", "base_id"} (the version token, the 409 conflict, the revision kept with its
document, the plain-text mirror, images that must be stored); the refusal of a plain
write over a formatted Summary; and - the data-loss path - that an image a Spot note
uses (Summary, dated update hidden or not, or an earlier version) is never freed by a
Watch List delete or a Notes tab delete.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path monkeypatched). No
network. web_portfolio spawns a background scheduler on non-__main__ import; we
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

NOTES = "/api/spot/position-notes"
VIEW = "/api/spot/position-notes/view"
CHAIN = "solana"
ADDR = "So11111111111111111111111111111111111111112"
EVM = "0x" + "a" * 40


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


def doc(text, *attrs_ops):
    return {"ops": list(attrs_ops) + [{"insert": text + "\n"}]}


def img_op(image_id, width=None):
    op = {"insert": {"image": f"/api/note-images/{image_id}"}}
    if width:
        op["attributes"] = {"width": str(width)}
    return op


def put(client, delta, base=None, chain=CHAIN, addr=ADDR, **extra):
    return client.put(NOTES, json={"chain": chain, "contract_address": addr, "delta": delta, "base_id": base, **extra})


def view(client, chain=CHAIN, addr=ADDR):
    r = client.get(VIEW, query_string={"chain": chain, "contract_address": addr})
    assert r.status_code == 200
    return r.get_json()


def row(db, chain=CHAIN, addr=ADDR):
    r = db.execute("SELECT * FROM spot_position_notes WHERE chain=? AND contract_address=?", (chain, addr)).fetchone()
    return dict(r) if r else None


def revisions(db):
    return [dict(r) for r in db.execute("SELECT kind, ref, old_text, old_json, action FROM note_revisions ORDER BY id")]


def _img(db, n, size=100):
    """Store an image whose sha256 is n repeated; returns its id."""
    db.execute("INSERT INTO note_images (sha256, mime, width, height, bytes, data, created_at) "
               "VALUES (?, 'image/png', 4, 4, ?, ?, 'now')", (("%02x" % n) * 32, size, b"x" * size))
    db.commit()
    return db.execute("SELECT id FROM note_images WHERE sha256 = ?", (("%02x" % n) * 32,)).fetchone()[0]


def _legacy(db, text="old **plain** note", chain=CHAIN, addr=ADDR):
    db.execute("INSERT INTO spot_position_notes (chain, contract_address, note) VALUES (?, ?, ?)", (chain, addr, text))
    db.commit()


def _image_ids(db):
    return [r[0] for r in db.execute("SELECT id FROM note_images ORDER BY id")]


# -- schema -----------------------------------------------------------------------------------------------------


def test_the_new_columns_are_nullable_text_added_at_the_end(db):
    def cols(t):
        return {r[1]: (r[2], r[3], r[4]) for r in db.execute(f"PRAGMA table_info({t})")}
    assert [r[1] for r in db.execute("PRAGMA table_info(spot_position_notes)")] == [
        "id", "chain", "contract_address", "note", "updated_at", "body_json"]
    assert [r[1] for r in db.execute("PRAGMA table_info(spot_note_updates)")][-1] == "body_json"
    assert [r[1] for r in db.execute("PRAGMA table_info(note_revisions)")] == [
        "id", "kind", "ref", "old_text", "action", "revised_at", "old_json"]
    for t, c in (("spot_position_notes", "body_json"), ("spot_note_updates", "body_json"), ("note_revisions", "old_json")):
        assert cols(t)[c] == ("TEXT", 0, None)          # nullable, no default


def test_an_older_database_is_upgraded_and_keeps_every_row(db):
    """Rows written before Landing 88 are untouched; the columns come back as NULL."""
    _legacy(db, "a plain summary")
    db.execute("INSERT INTO spot_note_updates (chain, contract_address, body, created_at) VALUES ('base', ?, 'upd', 't')", (EVM,))
    db.execute("INSERT INTO note_revisions (kind, ref, old_text, action, revised_at) VALUES ('spot_summary', 'k', 'older', 'edit', 't')")
    db.commit()
    for t, c in (("spot_position_notes", "body_json"), ("spot_note_updates", "body_json"), ("note_revisions", "old_json")):
        db.execute(f"ALTER TABLE {t} DROP COLUMN {c}")
    db.commit()
    before = {t: [tuple(r) for r in db.execute(f"SELECT * FROM {t} ORDER BY id")]
              for t in ("spot_position_notes", "spot_note_updates", "note_revisions")}
    portfolio_db.init_db()
    portfolio_db.init_db()                                  # repeatable
    after = {t: [tuple(r) for r in db.execute(f"SELECT * FROM {t} ORDER BY id")]
             for t in before}
    for t in before:
        assert [r + (None,) for r in before[t]] == after[t]      # same rows, the new column NULL
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


# -- view -------------------------------------------------------------------------------------------------------


def test_view_needs_both_parts_and_answers_the_empty_view_for_no_row(client):
    assert client.get(VIEW).status_code == 400
    assert client.get(VIEW, query_string={"chain": CHAIN}).status_code == 400
    assert client.get(VIEW, query_string={"chain": " ", "contract_address": ADDR}).status_code == 400
    assert view(client) == {"id": None, "delta": None, "text": "", "saved_at": None, "empty": True, "legacy": False}


def test_view_of_a_plain_summary_is_legacy_with_no_document(client, db):
    _legacy(db, "watch **this**")
    v = view(client)
    assert v["legacy"] is True and v["delta"] is None and v["text"] == "watch **this**" and v["empty"] is False
    assert v["id"] == wp._spot_note_token("watch **this**", None) and len(v["id"]) == 16
    assert v["saved_at"].endswith("+00:00") and "T" in v["saved_at"]


def test_view_of_a_saved_rich_summary_has_the_document_and_the_plain_mirror(client):
    d = doc("hello", {"insert": "bold", "attributes": {"bold": True}})
    r = put(client, d)
    assert r.status_code == 200
    v = view(client)
    assert v["legacy"] is False and v["delta"]["ops"][0] == {"insert": "bold", "attributes": {"bold": True}}
    assert v["text"] == "boldhello" and v["empty"] is False


def test_the_case_of_an_address_is_kept(client):
    put(client, doc("a"), addr="AbC")
    assert view(client, addr="AbC")["text"] == "a" and view(client, addr="abc")["text"] == ""


# -- rich save --------------------------------------------------------------------------------------------------


def test_a_first_save_stores_the_document_and_the_mirror(client, db):
    r = put(client, doc("first"))
    assert r.status_code == 200
    j = r.get_json()
    assert j["changed"] is True and j["text"] == "first" and j["legacy"] is False
    stored = row(db)
    assert stored["note"] == "first" and json.loads(stored["body_json"]) == {"ops": [{"insert": "first\n"}]}
    assert j["id"] == wp._spot_note_token(stored["note"], stored["body_json"])
    assert revisions(db) == []                                   # nothing earlier to keep


def test_chain_and_contract_are_trimmed_and_required(client, db):
    assert put(client, doc("x"), chain=" solana ", addr=" " + ADDR + " ").status_code == 200
    assert row(db)["note"] == "x"
    assert put(client, doc("x"), chain="").status_code == 400
    assert put(client, doc("x"), addr="  ").status_code == 400


def test_a_second_save_needs_the_current_token(client, db):
    t1 = put(client, doc("one")).get_json()["id"]
    r = put(client, doc("two"), base=t1)
    assert r.status_code == 200 and r.get_json()["text"] == "two"
    assert row(db)["note"] == "two"


def test_a_stale_token_is_a_409_with_the_current_summary_and_writes_nothing(client, db):
    t1 = put(client, doc("one")).get_json()["id"]
    put(client, doc("two"), base=t1)                            # saved from another tab
    r = put(client, doc("mine"), base=t1)
    assert r.status_code == 409
    j = r.get_json()
    assert "another tab" in j["error"] and j["current"]["text"] == "two"
    assert row(db)["note"] == "two" and len(revisions(db)) == 1


def test_a_change_of_formatting_alone_moves_the_version_token(client, db):
    bold = {"ops": [{"insert": "x", "attributes": {"bold": True}}, {"insert": "\n"}]}
    t1 = put(client, bold).get_json()["id"]
    r = put(client, doc("x"), base=t1)                           # the same plain text, no bold: another version
    assert r.status_code == 200 and r.get_json()["changed"] is True and r.get_json()["id"] != t1
    stale = put(client, doc("mine"), base=t1)
    assert stale.status_code == 409 and row(db)["note"] == "x"


def test_a_first_save_over_a_row_that_appeared_meanwhile_is_a_409(client, db):
    _legacy(db, "somebody else saved")
    r = put(client, doc("mine"), base=None)
    assert r.status_code == 409 and r.get_json()["current"]["text"] == "somebody else saved"
    assert row(db)["note"] == "somebody else saved" and row(db)["body_json"] is None


def test_the_same_document_writes_nothing(client, db):
    t1 = put(client, doc("same")).get_json()["id"]
    before = row(db)
    r = put(client, doc("same"), base=t1)
    assert r.status_code == 200 and r.get_json()["changed"] is False and r.get_json()["id"] == t1
    assert row(db) == before and revisions(db) == []


def test_an_edit_keeps_the_earlier_text_and_document(client, db):
    t1 = put(client, doc("one", img_op(_img(db, 1)))).get_json()["id"]
    first = row(db)
    put(client, doc("two"), base=t1)
    revs = revisions(db)
    assert revs == [{"kind": "spot_summary", "ref": CHAIN + " " + ADDR, "old_text": first["note"],
                     "old_json": first["body_json"], "action": "edit"}]
    assert first["note"] == "[image]one"


def test_the_first_edit_of_a_plain_summary_keeps_its_text_with_no_document(client, db):
    _legacy(db, "old **plain** note")
    token = view(client)["id"]
    r = put(client, doc("plain now"), base=token)
    assert r.status_code == 200
    assert revisions(db) == [{"kind": "spot_summary", "ref": CHAIN + " " + ADDR, "old_text": "old **plain** note",
                              "old_json": None, "action": "edit"}]
    assert row(db)["body_json"] is not None and view(client)["legacy"] is False


def test_clearing_keeps_the_row_and_reads_empty(client, db):
    t1 = put(client, doc("something")).get_json()["id"]
    r = put(client, {"ops": [{"insert": "\n"}]}, base=t1)
    assert r.status_code == 200 and r.get_json()["empty"] is True
    assert row(db)["note"] == "" and len(revisions(db)) == 1


@pytest.mark.parametrize("delta", [None, [], {}, {"ops": []}, {"ops": [{"insert": 5}]}, {"ops": "x"},
                                   {"ops": [{"insert": "x\n", "attributes": {"font": "mono"}}]},
                                   {"ops": [{"insert": "x\n"}], "extra": 1}])
def test_a_bad_document_is_a_400_and_writes_nothing(client, db, delta):
    r = put(client, delta)
    assert r.status_code == 400 and "error" in r.get_json()
    assert row(db) is None


def test_the_text_limit_is_the_notes_page_limit(client, db):
    assert put(client, doc("x" * wp.PAGE_NOTE_TEXT_MAX)).status_code == 200
    r = put(client, doc("x" * (wp.PAGE_NOTE_TEXT_MAX + 1)), base=view(client)["id"])
    assert r.status_code == 400 and "limited" in r.get_json()["error"]


@pytest.mark.parametrize("base", [5, "", "XYZ", "g" * 16, "a" * 15, ["a" * 16]])
def test_a_bad_token_is_a_400(client, db, base):
    r = put(client, doc("x"), base=base)
    assert r.status_code == 400 and row(db) is None


def test_note_and_delta_together_are_refused(client, db):
    r = put(client, doc("x"), note="plain")
    assert r.status_code == 400 and row(db) is None


def test_an_image_must_be_stored(client, db):
    r = put(client, doc("pic", img_op(999)))
    assert r.status_code == 400 and "isn't stored" in r.get_json()["error"] and row(db) is None
    a = _img(db, 1)
    r = put(client, doc("pic", img_op(a, 560)))
    assert r.status_code == 200 and r.get_json()["text"] == "[image]pic"
    assert json.loads(row(db)["body_json"])["ops"][0] == {"insert": {"image": f"/api/note-images/{a}"}, "attributes": {"width": "560"}}


def test_a_table_and_other_notes_page_formats_are_kept(client, db):
    d = {"ops": [{"insert": "a"}, {"insert": "\n", "attributes": {"table": "row-1", "cell-bg": "#7d2828"}},
                 {"insert": "b"}, {"insert": "\n", "attributes": {"table": "row-1"}}, {"insert": "\n"}]}
    r = put(client, d)
    assert r.status_code == 200
    assert json.loads(row(db)["body_json"])["ops"][1]["attributes"] == {"cell-bg": "#7d2828", "table": "row-1"}


# -- plain writes -----------------------------------------------------------------------------------------------


def test_a_plain_write_over_a_formatted_summary_is_refused(client, db):
    put(client, doc("formatted"))
    before = row(db)
    r = client.put(NOTES, json={"chain": CHAIN, "contract_address": ADDR, "note": "stale page text"})
    assert r.status_code == 409 and "reload" in r.get_json()["error"]
    assert row(db) == before and revisions(db) == []


def test_a_plain_write_over_a_plain_summary_still_works_and_stays_plain(client, db):
    _legacy(db, "before")
    r = client.put(NOTES, json={"chain": CHAIN, "contract_address": ADDR, "note": "after"})
    assert r.status_code == 200 and r.get_json()["note"] == "after"
    assert row(db)["body_json"] is None
    assert [(x["old_text"], x["old_json"]) for x in revisions(db)] == [("before", None)]


def test_a_plain_write_creates_a_plain_summary(client, db):
    r = client.put(NOTES, json={"chain": CHAIN, "contract_address": ADDR, "note": "brand new"})
    assert r.status_code == 200 and row(db)["body_json"] is None


def test_the_list_carries_the_document_or_none(client, db):
    _legacy(db, "plain one", addr="A1")
    put(client, doc("rich one"), addr="A2")
    got = {r["contract_address"]: r for r in client.get(NOTES).get_json()}
    assert got["A1"]["delta"] is None and got["A1"]["note"] == "plain one"
    assert got["A2"]["delta"] == {"ops": [{"insert": "rich one\n"}]} and got["A2"]["note"] == "rich one"
    assert set(got["A1"]) == {"chain", "contract_address", "note", "updated_at", "delta"}


def test_spot_pnl_keeps_returning_the_plain_mirror(client, db):
    put(client, doc("mirror text", {"insert": "b", "attributes": {"bold": True}}))
    assert wp._spot_position_notes_map(db)[(CHAIN, ADDR)] == "bmirror text"


# -- the stored-image scan (the data-loss path) -----------------------------------------------------------------


def _watch_item(client, name="WIF", contract=ADDR):
    r = client.post("/api/watchlist", json={"name": name, "chain": "solana", "contract": contract})
    assert r.status_code in (200, 201), r.get_json()
    return [i["key"] for i in client.get("/api/watchlist").get_json()["items"]][-1]


def _item_note(client, key, image_ids, text="item note"):
    ops = [{"insert": {"image": f"/api/note-images/{i}"}} for i in image_ids] + [{"insert": text + "\n"}]
    r = client.put(f"/api/page-notes/{key}", json={"delta": {"ops": ops}, "base_id": None})
    assert r.status_code == 200, r.get_json()


def _preview(client, key):
    r = client.get(f"/api/watchlist/{key}/delete-preview")
    assert r.status_code == 200
    return r.get_json()


def test_an_image_a_spot_summary_uses_survives_a_watch_list_delete(client, db):
    a, b = _img(db, 1), _img(db, 2)
    key = _watch_item(client)
    _item_note(client, key, [a, b])
    put(client, doc("pic", img_op(a)))                                       # the Summary shares a
    assert _preview(client, key)["frees"] == {"count": 1, "bytes": 100}       # only b would go
    j = client.delete(f"/api/watchlist/{key}").get_json()
    assert j["freed"] == {"count": 1, "bytes": 100}
    assert _image_ids(db) == [a]
    assert json.loads(row(db)["body_json"])["ops"][0]["insert"]["image"] == f"/api/note-images/{a}"


def test_an_image_only_an_earlier_summary_version_used_survives_too(client, db):
    a = _img(db, 1)
    key = _watch_item(client)
    _item_note(client, key, [a])
    t1 = put(client, doc("pic", img_op(a))).get_json()["id"]
    put(client, doc("no picture now"), base=t1)                                # a is only in note_revisions.old_json now
    assert "[image]" not in row(db)["note"]
    assert _preview(client, key)["frees"]["count"] == 0
    client.delete(f"/api/watchlist/{key}")
    assert _image_ids(db) == [a]


def test_an_image_in_a_dated_update_survives_whether_or_not_the_update_is_hidden(client, db):
    a, b = _img(db, 1), _img(db, 2)
    key = _watch_item(client)
    _item_note(client, key, [a, b])
    d_a = json.dumps(doc("u", img_op(a)))
    d_b = json.dumps(doc("u", img_op(b)))
    db.execute("INSERT INTO spot_note_updates (chain, contract_address, body, created_at, body_json) VALUES (?, ?, 'u', 't', ?)",
               (CHAIN, ADDR, d_a))
    db.execute("INSERT INTO spot_note_updates (chain, contract_address, body, created_at, deleted_at, body_json) "
               "VALUES (?, ?, 'u', 't', 't2', ?)", (CHAIN, ADDR, d_b))             # hidden by a delete: still a reference
    db.commit()
    assert _preview(client, key)["frees"]["count"] == 0
    client.delete(f"/api/watchlist/{key}")
    assert _image_ids(db) == [a, b]


def test_an_image_in_a_revision_of_a_dated_update_survives(client, db):
    a = _img(db, 1)
    key = _watch_item(client)
    _item_note(client, key, [a])
    db.execute("INSERT INTO note_revisions (kind, ref, old_text, action, revised_at, old_json) "
               "VALUES ('spot_update', '7', '[image]u', 'delete', 't', ?)", (json.dumps(doc("u", img_op(a))),))
    db.commit()
    client.delete(f"/api/watchlist/{key}")
    assert _image_ids(db) == [a]


def test_with_no_spot_note_using_it_the_image_is_still_freed(client, db):
    a = _img(db, 1)
    key = _watch_item(client)
    _item_note(client, key, [a])
    put(client, doc("a different picture", img_op(_img(db, 2))))
    assert _preview(client, key)["frees"] == {"count": 1, "bytes": 100}
    assert client.delete(f"/api/watchlist/{key}").get_json()["freed"] == {"count": 1, "bytes": 100}
    assert a not in _image_ids(db)


def test_a_notes_tab_delete_keeps_a_spot_notes_image_too(client, db):
    a, b = _img(db, 1), _img(db, 2)
    assert client.post("/api/note-tabs", json={"label": "Charts"}).status_code in (200, 201)
    key = "notes-t1"
    _item_note(client, key, [a, b])
    put(client, doc("pic", img_op(a)))
    pv = client.get(f"/api/note-tabs/{key}/delete-preview").get_json()
    assert pv["frees"] == {"count": 1, "bytes": 100}
    j = client.delete(f"/api/note-tabs/{key}").get_json()
    assert j["freed"] == {"count": 1, "bytes": 100}
    assert _image_ids(db) == [a]


def test_the_scan_reads_only_documents_and_ignores_rows_without_one(db):
    a = _img(db, 1)
    _legacy(db, f"mentions /api/note-images/{a} in plain text")      # plain text is not a document: no reference
    assert wp._spot_note_image_ids(db) == set()
    db.execute("UPDATE spot_position_notes SET body_json = ?", (json.dumps(doc("x", img_op(a))),))
    db.commit()
    assert wp._spot_note_image_ids(db) == {a}


def test_a_document_is_read_by_any_image_address_in_it(db):
    db.execute("INSERT INTO spot_position_notes (chain, contract_address, note, body_json) VALUES ('c', 'a', 't', "
               "'{\"x\":\"/api/note-images/12 and /api/note-images/34\"}')")
    db.commit()
    assert wp._spot_note_image_ids(db) == {12, 34}                    # a doubtful case keeps the image


# -- review findings (Landing 88): races, revisions of documents, the revisions rebuild --------------------------


def _fresh_client(monkeypatch):
    """A client of its own for a thread (the shared fixture forbids threads)."""
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _race(monkeypatch, calls):
    """Run every call (client -> response) in its own thread, released together; the status codes in call order."""
    barrier = threading.Barrier(len(calls))
    out = [None] * len(calls)

    def run(i, call):
        c = _fresh_client(monkeypatch)
        barrier.wait()
        out[i] = call(c).status_code

    threads = [threading.Thread(target=run, args=(i, call)) for i, call in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert None not in out
    return out


def test_saves_that_start_from_the_same_version_have_one_winner(db, monkeypatch):
    c = _fresh_client(monkeypatch)
    for rnd in range(5):
        base = view(c)["id"]
        calls = [(lambda cl, n=n: put(cl, doc("writer %d round %d" % (n, rnd)), base=base)) for n in range(8)]
        codes = _race(monkeypatch, calls)
        assert sorted(codes) == [200] + [409] * 7, codes
    assert db.execute("SELECT COUNT(*) FROM note_revisions WHERE kind = 'spot_summary'").fetchone()[0] == 4


def test_a_plain_write_and_a_formatted_save_never_leave_a_mixed_row(db, monkeypatch):
    for rnd in range(15):
        addr = "Race%d" % rnd
        _legacy(db, "original", addr=addr)
        token = wp._spot_note_token("original", None)
        codes = _race(monkeypatch, [
            lambda cl: cl.put(NOTES, json={"chain": CHAIN, "contract_address": addr, "note": "plain write"}),
            lambda cl: put(cl, doc("rich write"), base=token, addr=addr),
        ])
        assert sorted(codes) == [200, 409], codes                  # one of them wins, the other is told
        r = row(db, addr=addr)
        if r["body_json"] is None:
            assert r["note"] == "plain write"
        else:
            assert r["note"] == "rich write" and json.loads(r["body_json"]) == {"ops": [{"insert": "rich write\n"}]}


def test_a_document_with_no_text_is_still_kept_when_it_is_replaced(client, db):
    table = {"ops": [{"insert": "\n", "attributes": {"table": "row-1", "cell-bg": "#7d2828"}}, {"insert": "\n"}]}
    t1 = put(client, table).get_json()["id"]
    assert row(db)["note"] == ""                                 # nothing to read in a coloured empty cell
    put(client, doc("now some text"), base=t1)
    assert [(x["old_text"], json.loads(x["old_json"])) for x in revisions(db)] == [("", table)]


def test_an_empty_document_is_not_worth_a_revision(client, db):
    t1 = put(client, {"ops": [{"insert": "\n"}]}).get_json()["id"]
    put(client, doc("text"), base=t1)
    assert revisions(db) == []


def test_plain_revisions_do_not_need_the_new_column(db):
    db.execute("ALTER TABLE note_revisions DROP COLUMN old_json")
    wp._note_revision(db, "trade_notes", "t1", "an old note", "edit")
    db.commit()
    assert [tuple(r) for r in db.execute("SELECT kind, ref, old_text, action FROM note_revisions")] == [
        ("trade_notes", "t1", "an old note", "edit")]


OLD_REVISIONS = """CREATE TABLE note_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('spot_summary','spot_update','trade_notes','trade_deviation_note')),
    ref TEXT NOT NULL,
    old_text TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('edit','delete')),
    revised_at TEXT NOT NULL%s
)"""


def _old_revisions_db(tmp_path, monkeypatch, with_json):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute(OLD_REVISIONS % (",\n    old_json TEXT" if with_json else ""))
    conn.execute("CREATE INDEX idx_note_revisions_ref ON note_revisions (kind, ref)")
    for i in range(1, 4):
        if with_json:
            conn.execute("INSERT INTO note_revisions (kind, ref, old_text, action, revised_at, old_json) VALUES (?, ?, ?, 'edit', ?, ?)",
                         ("spot_summary", "k%d" % i, "[image]t%d" % i, "2026-10-0%d" % i, '{"ops":[{"insert":{"image":"/api/note-images/%d"}}]}' % i))
        else:
            conn.execute("INSERT INTO note_revisions (kind, ref, old_text, action, revised_at) VALUES (?, ?, ?, 'edit', ?)",
                         ("spot_summary", "k%d" % i, "t%d" % i, "2026-10-0%d" % i))
    conn.commit()
    conn.close()
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    return path


def test_the_kinds_rebuild_keeps_the_documents_of_earlier_versions(tmp_path, monkeypatch):
    """A rebuild (a kind added to the CHECK) must not drop old_json: images only an old revision used would
    stop counting as in use (the stored-image scan reads this column)."""
    path = _old_revisions_db(tmp_path, monkeypatch, with_json=True)
    portfolio_db.init_db()
    conn = sqlite3.connect(path)
    got = conn.execute("SELECT id, kind, old_text, old_json FROM note_revisions ORDER BY id").fetchall()
    assert got == [(i, "spot_summary", "[image]t%d" % i, '{"ops":[{"insert":{"image":"/api/note-images/%d"}}]}' % i) for i in (1, 2, 3)]
    assert [r[1] for r in conn.execute("PRAGMA table_info(note_revisions)")].count("old_json") == 1
    conn.row_factory = sqlite3.Row
    assert wp._spot_note_image_ids(conn) == {1, 2, 3}
    conn.close()


def test_an_older_revisions_table_without_the_column_is_rebuilt_and_gains_it(tmp_path, monkeypatch):
    path = _old_revisions_db(tmp_path, monkeypatch, with_json=False)
    portfolio_db.init_db()
    portfolio_db.init_db()
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT id, old_text, old_json FROM note_revisions ORDER BY id").fetchall() == [
        (i, "t%d" % i, None) for i in (1, 2, 3)]
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()
