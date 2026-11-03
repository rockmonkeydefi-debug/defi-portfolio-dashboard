"""Landing 89: a Spot position's dated updates written in the Notes page editor.

Covers: the list rows' "delta" / "version" / "legacy"; POST /api/spot/note-updates with {"delta"} (the
document, the plain-text mirror in "body", images that must be stored, the Notes page's 10,000-character
limit, a blank document refused, "body" and "delta" never together); PUT /api/spot/note-updates/<id> with
{"delta", "base_id"} (the version token, the 409 with the stored update as "current", an equal document
writes nothing, the earlier text and document kept in note_revisions, a plain update converted only when
saved in the editor); the refusal of a plain write over a formatted update; DELETE keeping the document in
the revision; that an image an update names (hidden, edited away or deleted) stays referenced; and - the
data-loss paths - the races (one winner per version, an edit against a delete, a double delete, a plain
write against an editor save, concurrent adds).

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path monkeypatched). No network.
web_portfolio spawns a background scheduler on non-__main__ import; we neutralize
threading.Thread.start during import (established pattern).
"""
import json
import threading
from datetime import datetime, timedelta

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db

UPD = "/api/spot/note-updates"
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


def doc(text, *lead_ops):
    return {"ops": list(lead_ops) + [{"insert": text + "\n"}]}


def img_op(image_id, width=None):
    op = {"insert": {"image": f"/api/note-images/{image_id}"}}
    if width:
        op["attributes"] = {"width": str(width)}
    return op


def _img(db, n, size=100):
    """Store an image whose sha256 is n repeated; returns its id."""
    db.execute("INSERT INTO note_images (sha256, mime, width, height, bytes, data, created_at) "
               "VALUES (?, 'image/png', 4, 4, ?, ?, 'now')", (("%02x" % n) * 32, size, b"x" * size))
    db.commit()
    return db.execute("SELECT id FROM note_images WHERE sha256 = ?", (("%02x" % n) * 32,)).fetchone()[0]


def post(client, delta, chain=CHAIN, addr=ADDR, **extra):
    return client.post(UPD, json={"chain": chain, "contract_address": addr, "delta": delta, **extra})


def add(client, delta, **kw):
    r = post(client, delta, **kw)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def edit(client, update_id, delta, base, **extra):
    return client.put(f"{UPD}/{update_id}", json={"delta": delta, "base_id": base, **extra})


def listing(client, chain=CHAIN, addr=ADDR):
    r = client.get(UPD, query_string={"chain": chain, "contract_address": addr})
    assert r.status_code == 200
    return r.get_json()


def stored(db, update_id):
    return dict(db.execute("SELECT * FROM spot_note_updates WHERE id = ?", (update_id,)).fetchone())


def revisions(db):
    return [dict(r) for r in db.execute("SELECT kind, ref, old_text, old_json, action FROM note_revisions ORDER BY id")]


def _legacy(db, body="old **plain** update", chain=CHAIN, addr=ADDR, trade_id=None):
    cur = db.execute("INSERT INTO spot_note_updates (chain, contract_address, body, created_at, trade_id) "
                     "VALUES (?, ?, ?, '2026-10-05T00:00:00+00:00', ?)", (chain, addr, body, trade_id))
    db.commit()
    return cur.lastrowid


def utc(s):
    d = datetime.fromisoformat(s)
    assert d.utcoffset() == timedelta(0)
    return d


def canon(delta):
    return json.dumps(delta, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


# -- the list ---------------------------------------------------------------------------------------------------


def test_a_list_row_carries_the_document_the_version_and_whether_it_is_plain_text(client, db):
    legacy_id = _legacy(db)
    rich = add(client, doc("formatted", {"insert": "bold ", "attributes": {"bold": True}}))
    rows = {r["id"]: r for r in listing(client)}
    old, new = rows[legacy_id], rows[rich["id"]]
    assert old["legacy"] is True and old["delta"] is None and old["body"] == "old **plain** update"
    assert new["legacy"] is False and new["delta"]["ops"][0] == {"insert": "bold ", "attributes": {"bold": True}}
    for r in (old, new):
        assert len(r["version"]) == 16 and all(c in "0123456789abcdef" for c in r["version"])
        assert r["version"] == wp._spot_note_token(r["body"], stored(db, r["id"])["body_json"])
    assert old["version"] != new["version"]
    for key in ("chain", "contract_address", "position_key", "created_at", "edited_at", "trade_id"):
        assert key in old and key in new                                   # the earlier fields stay


# -- POST -------------------------------------------------------------------------------------------------------


def test_add_a_document_stores_it_with_the_plain_text_mirror(client, db):
    d = doc("Weekly bullish.", {"insert": "bold ", "attributes": {"bold": True}})
    r = client.post(UPD, json={"chain": " solana ", "contract_address": " " + ADDR + " ", "delta": d})
    assert r.status_code == 201
    u = r.get_json()
    assert u["chain"] == "solana" and u["contract_address"] == ADDR            # trimmed, case kept
    assert u["position_key"] == "solana " + ADDR
    assert u["body"] == "bold Weekly bullish." and u["edited_at"] is None and u["legacy"] is False
    assert u["delta"] == d and u["trade_id"] is None
    utc(u["created_at"])
    s = stored(db, u["id"])
    assert s["body_json"] == canon(d) and s["body"] == u["body"] and s["deleted_at"] is None
    assert u["version"] == wp._spot_note_token(s["body"], s["body_json"])
    assert revisions(db) == []


def test_an_update_of_only_a_picture_is_not_blank(client, db):
    a = _img(db, 1)
    u = add(client, {"ops": [img_op(a, 300), {"insert": "\n"}]})
    assert u["body"] == "[image]"
    assert wp._spot_note_image_ids(db) == {a}


def test_a_document_may_run_to_the_notes_page_limit(client):
    ok = add(client, doc("x" * 10000))
    assert len(ok["body"]) == 10000
    r = post(client, doc("x" * 10001))
    assert r.status_code == 400 and "10,000" in r.get_json()["error"]


BAD_DOCS = [
    ("not a document", "must be an editor document"),
    (None, "must be an editor document"),
    (["ops"], "must be an editor document"),
    ({"ops": []}, "no content"),
    ({"ops": [{"insert": "\n"}]}, "body must be a non-empty string"),
    ({"ops": [{"insert": "  \n"}]}, "body must be a non-empty string"),
    ({"ops": [{"insert": {"formula": "x"}}, {"insert": "\n"}]}, "only text and images"),
]


@pytest.mark.parametrize("delta, message", BAD_DOCS)
def test_add_rejects_a_bad_document_and_writes_nothing(client, db, delta, message):
    r = post(client, delta)
    assert r.status_code == 400 and message in r.get_json()["error"]
    assert db.execute("SELECT COUNT(*) FROM spot_note_updates").fetchone()[0] == 0


def test_add_needs_the_position_and_refuses_body_and_delta_together(client, db):
    assert client.post(UPD, json={"contract_address": ADDR, "delta": doc("x")}).get_json() == {"error": "chain is required"}
    assert client.post(UPD, json={"chain": CHAIN, "delta": doc("x")}).get_json() == {"error": "contract_address is required"}
    r = post(client, doc("x"), body="plain")
    assert r.status_code == 400 and "either body or delta" in r.get_json()["error"]
    assert db.execute("SELECT COUNT(*) FROM spot_note_updates").fetchone()[0] == 0


def test_add_refuses_an_image_that_is_not_stored_and_writes_nothing(client, db):
    a = _img(db, 1)
    r = post(client, doc("pic", img_op(a), img_op(a + 99)))
    assert r.status_code == 400 and "isn't stored" in r.get_json()["error"]
    assert db.execute("SELECT COUNT(*) FROM spot_note_updates").fetchone()[0] == 0


def test_add_refuses_more_images_than_a_note_holds(client, db):
    ids = [_img(db, n) for n in range(1, wp.PAGE_NOTE_IMAGES_MAX + 2)]
    r = post(client, doc("many", *[img_op(i) for i in ids]))
    assert r.status_code == 400 and "at most" in r.get_json()["error"]
    assert db.execute("SELECT COUNT(*) FROM spot_note_updates").fetchone()[0] == 0


def test_the_plain_add_still_works_for_a_page_loaded_before_the_full_editor(client, db):
    r = client.post(UPD, json={"chain": "base", "contract_address": EVM, "body": "Weekly **bullish**."})
    assert r.status_code == 201
    u = r.get_json()
    assert u["legacy"] is True and u["delta"] is None and u["body"] == "Weekly **bullish**."
    assert stored(db, u["id"])["body_json"] is None
    assert client.post(UPD, json={"chain": "base", "contract_address": EVM, "body": "x" * 2001}).status_code == 400


# -- PUT --------------------------------------------------------------------------------------------------------


def test_an_edit_keeps_the_earlier_text_and_document_and_the_original_date(client, db):
    first = doc("first take", {"insert": "bold ", "attributes": {"bold": True}})
    u = add(client, first)
    second = doc("second take")
    r = edit(client, u["id"], second, u["version"])
    assert r.status_code == 200
    e = r.get_json()
    assert e["changed"] is True and e["body"] == "second take" and e["delta"] == second
    assert e["created_at"] == u["created_at"] and utc(e["edited_at"]) >= utc(u["created_at"])
    assert e["version"] != u["version"] and e["legacy"] is False
    s = stored(db, u["id"])
    assert s["body_json"] == canon(second) and s["body"] == "second take" and s["edited_at"] == e["edited_at"]
    revs = revisions(db)
    assert len(revs) == 1
    assert (revs[0]["kind"], revs[0]["ref"], revs[0]["old_text"], revs[0]["action"]) == \
        ("spot_update", str(u["id"]), "bold first take", "edit")
    assert revs[0]["old_json"] == canon(first)


def test_an_edit_to_the_same_document_changes_nothing(client, db):
    d = doc("same", {"insert": "b", "attributes": {"italic": True}})
    u = add(client, d)
    r = edit(client, u["id"], d, u["version"])
    assert r.status_code == 200
    e = r.get_json()
    assert e["changed"] is False and e["edited_at"] is None and e["version"] == u["version"]
    assert revisions(db) == [] and stored(db, u["id"])["edited_at"] is None


def test_a_stale_version_is_a_409_with_the_stored_update_and_writes_nothing(client, db):
    u = add(client, doc("start"))
    a = edit(client, u["id"], doc("tab A"), u["version"])
    assert a.status_code == 200
    r = edit(client, u["id"], doc("tab B"), u["version"])                      # started from the old version
    assert r.status_code == 409
    body = r.get_json()
    assert "another tab or device" in body["error"]
    assert body["current"]["version"] == a.get_json()["version"]
    assert body["current"]["delta"] == doc("tab A") and body["current"]["body"] == "tab A"
    assert body["current"]["id"] == u["id"]
    assert stored(db, u["id"])["body"] == "tab A"
    assert len(revisions(db)) == 1


def test_the_base_version_rules(client, db):
    u = add(client, doc("start"))
    r = edit(client, u["id"], doc("no base"), None)                            # an existing update needs its version
    assert r.status_code == 409
    for bad in ("short", "A" * 16, "g" * 16, "0" * 17, 5, ["x"]):
        r = edit(client, u["id"], doc("bad base"), bad)
        assert r.status_code == 400 and r.get_json() == {"error": "base_id must be a version token or null"}, bad
    r = client.put(f"{UPD}/{u['id']}", json={"delta": doc("missing base")})
    assert r.status_code == 409
    assert stored(db, u["id"])["body"] == "start" and revisions(db) == []


def test_edit_rejects_a_bad_document_an_unstored_image_and_unknown_or_deleted_ids(client, db):
    a = _img(db, 1)
    u = add(client, doc("keep"))
    for bad, message in BAD_DOCS:
        r = edit(client, u["id"], bad, u["version"])
        assert r.status_code == 400 and message in r.get_json()["error"]
    r = edit(client, u["id"], doc("pic", img_op(a + 50)), u["version"])
    assert r.status_code == 400 and "isn't stored" in r.get_json()["error"]
    r = client.put(f"{UPD}/{u['id']}", json={"delta": doc("x"), "base_id": u["version"], "body": "also"})
    assert r.status_code == 400 and "either body or delta" in r.get_json()["error"]
    r = edit(client, 999, doc("x"), u["version"])
    assert r.status_code == 404 and r.get_json() == {"error": "update not found"}
    assert client.delete(f"{UPD}/{u['id']}").status_code == 200
    assert edit(client, u["id"], doc("x"), u["version"]).status_code == 404
    assert stored(db, u["id"])["body"] == "keep"


def test_a_plain_update_is_converted_only_when_saved_in_the_editor(client, db):
    uid = _legacy(db, "old **plain** update", trade_id="tp1")
    before = listing(client)[0]
    assert before["legacy"] is True and before["trade_id"] == "tp1"
    new = doc("old plain update", {"insert": "now ", "attributes": {"bold": True}})
    r = edit(client, uid, new, before["version"])
    assert r.status_code == 200
    e = r.get_json()
    assert e["legacy"] is False and e["delta"] == new and e["body"] == "now old plain update"
    assert e["trade_id"] == "tp1" and e["created_at"] == "2026-10-05T00:00:00+00:00"
    revs = revisions(db)
    assert [(x["old_text"], x["old_json"], x["action"]) for x in revs] == [("old **plain** update", None, "edit")]


def test_a_plain_write_over_a_formatted_update_is_refused(client, db):
    u = add(client, doc("formatted", {"insert": "b", "attributes": {"bold": True}}))
    r = client.put(f"{UPD}/{u['id']}", json={"body": "plain over it"})
    assert r.status_code == 409 and "reload the page" in r.get_json()["error"]
    s = stored(db, u["id"])
    assert s["body"] == u["body"] and s["body_json"] is not None and s["edited_at"] is None
    assert revisions(db) == []
    same = client.put(f"{UPD}/{u['id']}", json={"body": u["body"]})            # even the same text is refused
    assert same.status_code == 409


def test_a_plain_edit_of_a_plain_update_still_works(client, db):
    uid = _legacy(db, "first take")
    r = client.put(f"{UPD}/{uid}", json={"body": "second take"})
    assert r.status_code == 200
    e = r.get_json()
    assert e["body"] == "second take" and e["legacy"] is True and e["delta"] is None
    assert [(x["old_text"], x["old_json"]) for x in revisions(db)] == [("first take", None)]
    assert client.put(f"{UPD}/{uid}", json={"body": "second take"}).status_code == 200
    assert len(revisions(db)) == 1                                              # the same text writes nothing
    assert client.put(f"{UPD}/{uid}", json={"body": "  "}).status_code == 400
    assert client.put(f"{UPD}/{uid}", json={"body": "x" * 2001}).status_code == 400


# -- DELETE -----------------------------------------------------------------------------------------------------


def test_a_delete_keeps_the_document_in_the_revision_and_on_the_hidden_row(client, db):
    a = _img(db, 1)
    d = doc("pic", img_op(a), {"insert": "bold ", "attributes": {"bold": True}})
    u = add(client, d)
    r = client.delete(f"{UPD}/{u['id']}")
    assert r.status_code == 200 and r.get_json()["id"] == u["id"]
    utc(r.get_json()["deleted_at"])
    s = stored(db, u["id"])
    assert s["deleted_at"] == r.get_json()["deleted_at"] and s["body_json"] == canon(d)
    revs = revisions(db)
    assert [(x["kind"], x["ref"], x["action"], x["old_json"]) for x in revs] == \
        [("spot_update", str(u["id"]), "delete", canon(d))]
    assert revs[0]["old_text"] == u["body"]
    assert listing(client) == []
    assert client.delete(f"{UPD}/{u['id']}").status_code == 404
    assert len(revisions(db)) == 1
    assert wp._spot_note_image_ids(db) == {a}                                   # hidden, still a reference


def test_deleting_a_plain_update_keeps_a_plain_revision(client, db):
    uid = _legacy(db, "gone soon")
    assert client.delete(f"{UPD}/{uid}").status_code == 200
    assert [(x["old_text"], x["old_json"], x["action"]) for x in revisions(db)] == [("gone soon", None, "delete")]


def test_an_image_an_edit_removed_is_still_named_by_the_earlier_version(client, db):
    a = _img(db, 1)
    u = add(client, doc("pic", img_op(a)))
    e = edit(client, u["id"], doc("no picture now"), u["version"]).get_json()
    assert "[image]" not in e["body"] and "note-images" not in stored(db, u["id"])["body_json"]
    assert wp._spot_note_image_ids(db) == {a}                                   # only note_revisions.old_json names it
    assert client.delete(f"{UPD}/{u['id']}").status_code == 200
    assert wp._spot_note_image_ids(db) == {a}


def test_an_image_survives_a_watch_list_style_scan_whether_or_not_the_update_is_hidden(client, db):
    a, b = _img(db, 1), _img(db, 2)
    add(client, doc("one", img_op(a)))
    hidden = add(client, doc("two", img_op(b)))
    client.delete(f"{UPD}/{hidden['id']}")
    assert wp._spot_note_image_ids(db) == {a, b}


def test_a_delete_cannot_commit_between_the_image_check_and_the_insert(client, db, monkeypatch):
    """The image check and the INSERT of a new update are one write lock: a Watch List or Notes tab delete that frees
    an image cannot slip in between (it would leave an update naming an image that is gone)."""
    import sqlite3
    a = _img(db, 1)
    path = portfolio_db.get_db_path()
    real = wp._spot_update_images_stored
    outcome = {}

    def checked_then_delete(conn, ids):
        ok = real(conn, ids)
        other = sqlite3.connect(path, timeout=0.3)
        try:
            other.execute("DELETE FROM note_images WHERE id = ?", (a,))
            other.commit()
            outcome["freed"] = True
        except sqlite3.OperationalError:                    # database is locked: the lock is held
            outcome["freed"] = False
        finally:
            other.close()
        return ok

    monkeypatch.setattr(wp, "_spot_update_images_stored", checked_then_delete)
    r = post(client, doc("pic", img_op(a)))
    assert outcome["freed"] is False, "the image was freed between the check and the insert"
    assert r.status_code == 201 and wp._spot_note_image_ids(db) == {a}
    assert db.execute("SELECT COUNT(*) FROM note_images").fetchone()[0] == 1


def test_the_same_lock_holds_when_an_edit_checks_its_images(client, db, monkeypatch):
    import sqlite3
    a = _img(db, 1)
    u = add(client, doc("start"))
    path = portfolio_db.get_db_path()
    real = wp._spot_update_images_stored
    outcome = {}

    def checked_then_delete(conn, ids):
        ok = real(conn, ids)
        other = sqlite3.connect(path, timeout=0.3)
        try:
            other.execute("DELETE FROM note_images WHERE id = ?", (a,))
            other.commit()
            outcome["freed"] = True
        except sqlite3.OperationalError:
            outcome["freed"] = False
        finally:
            other.close()
        return ok

    monkeypatch.setattr(wp, "_spot_update_images_stored", checked_then_delete)
    r = edit(client, u["id"], doc("pic", img_op(a)), u["version"])
    assert outcome["freed"] is False and r.status_code == 200
    assert db.execute("SELECT COUNT(*) FROM note_images").fetchone()[0] == 1


# -- races (a client of its own per thread: the shared fixture forbids threads) ----------------------------------


def _fresh_client(monkeypatch):
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
    u = add(c, doc("start"))
    for rnd in range(5):
        current = listing(c)[0]["version"]
        calls = [(lambda cl, n=n: edit(cl, u["id"], doc("writer %d round %d" % (n, rnd)), current)) for n in range(8)]
        codes = _race(monkeypatch, calls)
        assert sorted(codes) == [200] + [409] * 7, codes
    assert db.execute("SELECT COUNT(*) FROM note_revisions WHERE kind = 'spot_update'").fetchone()[0] == 5


def test_an_edit_racing_a_delete_cannot_both_leave_the_update_half_done(db, monkeypatch):
    c = _fresh_client(monkeypatch)
    for rnd in range(6):
        u = add(c, doc("round %d original" % rnd), addr="addr%d" % rnd)
        codes = _race(monkeypatch, [
            lambda cl: edit(cl, u["id"], doc("round %d edited" % rnd), u["version"]),
            lambda cl: cl.delete(f"{UPD}/{u['id']}"),
        ])
        assert codes[1] == 200 and codes[0] in (200, 404), codes
        s = stored(db, u["id"])
        assert s["deleted_at"] is not None
        revs = [r for r in revisions(db) if r["ref"] == str(u["id"])]
        deletes = [r for r in revs if r["action"] == "delete"]
        edits = [r for r in revs if r["action"] == "edit"]
        assert len(deletes) == 1
        if codes[0] == 200:                                  # the edit won: the delete saw the edited text
            assert len(edits) == 1 and edits[0]["old_text"] == "round %d original" % rnd
            assert deletes[0]["old_text"] == "round %d edited" % rnd and s["body"] == "round %d edited" % rnd
        else:                                                # the delete won: the edit found nothing
            assert edits == [] and deletes[0]["old_text"] == "round %d original" % rnd
            assert s["body"] == "round %d original" % rnd


def test_a_double_delete_has_one_winner_and_one_revision(db, monkeypatch):
    c = _fresh_client(monkeypatch)
    u = add(c, doc("once"))
    codes = _race(monkeypatch, [(lambda cl: cl.delete(f"{UPD}/{u['id']}")) for _ in range(6)])
    assert sorted(codes) == [200] + [404] * 5, codes
    assert len(revisions(db)) == 1


def test_a_plain_write_against_an_editor_save_never_leaves_a_mixed_row(db, monkeypatch):
    c = _fresh_client(monkeypatch)
    for rnd in range(8):
        uid = _legacy(db, "plain %d start" % rnd, addr="mix%d" % rnd)
        version = wp._spot_note_token("plain %d start" % rnd, None)
        codes = _race(monkeypatch, [
            lambda cl: cl.put(f"{UPD}/{uid}", json={"body": "plain %d later" % rnd}),
            lambda cl: edit(cl, uid, doc("rich %d later" % rnd), version),
        ])
        s = stored(db, uid)
        if s["body_json"] is None:                           # the plain write was last: no document
            assert s["body"] in ("plain %d later" % rnd, "plain %d start" % rnd)
        else:                                                # the editor save was last: its text and document agree
            assert s["body"] == "rich %d later" % rnd and json.loads(s["body_json"]) == doc("rich %d later" % rnd)
        assert sorted(codes)[0] in (200, 409), codes


def test_concurrent_adds_all_succeed_with_their_own_ids(db, monkeypatch):
    c = _fresh_client(monkeypatch)
    calls = [(lambda cl, n=n: post(cl, doc("add %d" % n))) for n in range(8)]
    codes = _race(monkeypatch, calls)
    assert codes == [201] * 8
    assert db.execute("SELECT COUNT(DISTINCT id) FROM spot_note_updates").fetchone()[0] == 8
    assert len(listing(c)) == 8
