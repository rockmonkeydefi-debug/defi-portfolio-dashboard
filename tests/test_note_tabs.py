"""Landing 31: tabs on the Notes page that Glenn adds, renames, moves and
archives himself - the append-only note_tabs table and the routes
GET / POST /api/note-tabs, PUT /api/note-tabs/order and
PUT /api/note-tabs/<key>. Watchlist and Nuggets exist without a row
(NOTE_TAB_DEFAULTS); added tabs get the keys notes-t1, notes-t2, ...; a
tab's note is the page_notes note under its key, which the notes routes
now accept, archived tabs included. Landing 83: DELETE /api/note-tabs/<key>
(and its delete-preview) removes a tab for good - a row with deleted = 1,
its notes and the images no other note uses; note_tabs rows themselves are
still never updated or deleted.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). No network.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import json
import re
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

TABS = "/api/note-tabs"
ORDER = "/api/note-tabs/order"


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


def rows(db):
    return [dict(r) for r in db.execute("SELECT * FROM note_tabs ORDER BY id")]


def view(client):
    r = client.get(TABS)
    assert r.status_code == 200
    return r.get_json()


def bar(client):
    """The tab bar as (key, label) pairs, in order."""
    return [(t["key"], t["label"]) for t in view(client)["tabs"] if not t["archived"]]


def archived(client):
    return [(t["key"], t["label"]) for t in view(client)["tabs"] if t["archived"]]


def add(client, label):
    return client.post(TABS, json={"label": label})


def change(client, key, **body):
    return client.put(f"{TABS}/{key}", json=body)


def order(client, keys):
    return client.put(ORDER, json={"keys": keys})


def doc(text):
    return {"ops": [{"insert": text + "\n"}]}


DEFAULT_BAR = [("notes-watchlist", "Watchlist"), ("notes-nuggets", "Nuggets")]


# ── Table ────────────────────────────────────────────────────────────────────

def test_table_and_index_exist_and_init_db_runs_twice(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info(note_tabs)")]
    assert cols == ["id", "tab_key", "label", "position", "archived", "created_at", "deleted"]   # deleted: Landing 83
    assert "idx_note_tabs_key" in {r[1] for r in db.execute("PRAGMA index_list(note_tabs)")}
    portfolio_db.init_db()
    assert [r[1] for r in db.execute("PRAGMA table_info(note_tabs)")] == cols


@pytest.mark.parametrize("key,label,position,archived", [
    ("spot", "x", 0, 0),                      # not a Notes tab key
    ("notes-", "x", 0, 0),                    # nothing after the prefix
    ("notes-foo", "x", 0, 0),                 # neither a default tab nor notes-t<n>
    ("notes-t0", "x", 0, 0),                  # no leading zero
    ("notes-t1x", "x", 0, 0),                 # not a number
    ("notes-t1234567", "x", 0, 0),            # seven digits
    ("notes-Watchlist", "x", 0, 0),           # case matters
    ("notes-t1", "", 0, 0),                   # blank name
    ("notes-t1", "x" * 41, 0, 0),             # name too long
    ("notes-t1", "x", -1, 0),                 # negative position
    ("notes-t1", "x", "first", 0),            # position stored as text
    ("notes-t1", "x", 1.5, 0),                # position not whole
    ("notes-t1", "x", 0, 2),                  # archived not 0 / 1
])
def test_the_table_refuses_bad_rows(db, key, label, position, archived):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO note_tabs (tab_key, label, position, archived, created_at) VALUES (?, ?, ?, ?, 'x')",
                   (key, label, position, archived))


@pytest.mark.parametrize("key", ["notes-watchlist", "notes-nuggets", "notes-t1", "notes-t999999"])
def test_the_table_takes_every_real_key(db, key):
    db.execute("INSERT INTO note_tabs (tab_key, label, position, archived, created_at) VALUES (?, 'x', 0, 0, 'x')", (key,))


def test_the_constants():
    assert wp.NOTE_TAB_DEFAULTS == (("notes-watchlist", "Watchlist"), ("notes-nuggets", "Nuggets"))
    # The default tabs' notes are the pages the notes routes have always served.
    assert wp.PAGE_NOTE_PAGES == ("spot",) + tuple(k for k, _ in wp.NOTE_TAB_DEFAULTS)
    assert wp.NOTE_TAB_LABEL_MAX == 40 and wp.NOTE_TABS_ACTIVE_MAX == 20 and wp.NOTE_TABS_TOTAL_MAX == 200


# ── GET ──────────────────────────────────────────────────────────────────────

def test_get_before_any_change_lists_the_two_default_tabs(client, db):
    v = view(client)
    assert v == {"tabs": [
        {"key": "notes-watchlist", "label": "Watchlist", "archived": False, "default": True, "changed_at": None},
        {"key": "notes-nuggets", "label": "Nuggets", "archived": False, "default": True, "changed_at": None},
    ], "limits": {"label_max": 40, "active_max": 20}}
    assert rows(db) == []


def test_get_writes_nothing(client, db):
    add(client, "Setups")
    before = rows(db)
    for _ in range(3):
        view(client)
    assert rows(db) == before


def test_login_gate(db, monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    c = wp.app.test_client()
    assert c.get(TABS).status_code == 401
    assert c.post(TABS, json={"label": "x"}).status_code == 401
    assert c.put(ORDER, json={"keys": []}).status_code == 401
    assert c.put(f"{TABS}/notes-watchlist", json={"label": "x"}).status_code == 401
    assert rows(db) == []


# ── POST: adding ─────────────────────────────────────────────────────────────

def test_add_puts_the_tab_at_the_end_with_the_next_key(client, db):
    r = add(client, "Setups")
    assert r.status_code == 201
    body = r.get_json()
    assert body["key"] == "notes-t1"
    assert [(t["key"], t["label"]) for t in body["tabs"]] == DEFAULT_BAR + [("notes-t1", "Setups")]
    assert body["tabs"][-1]["default"] is False and body["tabs"][-1]["changed_at"]
    assert add(client, "Macro").get_json()["key"] == "notes-t2"
    assert bar(client) == DEFAULT_BAR + [("notes-t1", "Setups"), ("notes-t2", "Macro")]
    got = rows(db)
    assert [(r["tab_key"], r["label"], r["position"], r["archived"]) for r in got] == [
        ("notes-t1", "Setups", 2, 0), ("notes-t2", "Macro", 3, 0)]


def test_add_trims_the_name_and_collapses_spaces(client):
    r = add(client, "  Weekly \t  review \n ")
    assert r.status_code == 201
    assert bar(client)[-1] == ("notes-t1", "Weekly review")


def test_a_name_of_40_characters_is_accepted_and_41_refused(client, db):
    assert add(client, "x" * 40).status_code == 201
    r = add(client, "y" * 41)
    assert r.status_code == 400 and "40 characters" in r.get_json()["error"]
    # Characters, not bytes: 40 emoji fit.
    assert add(client, "\U0001F4C8" * 40).status_code == 201
    assert len(rows(db)) == 2


@pytest.mark.parametrize("body", [
    None, [], "Setups", {}, {"name": "Setups"}, {"label": "Setups", "extra": 1},
    {"label": None}, {"label": 5}, {"label": ""}, {"label": "   "}, {"label": "a\x00b"}, {"label": "a\x7fb"},
])
def test_bad_bodies_are_400_and_write_nothing(client, db, body):
    r = client.post(TABS, json=body) if body is not None else client.post(TABS, data="not json")
    assert r.status_code == 400
    assert rows(db) == []


def test_a_name_an_open_tab_has_is_refused_ignoring_case(client, db):
    r = add(client, "watchlist")
    assert r.status_code == 400 and '"Watchlist"' in r.get_json()["error"]
    add(client, "Setups")
    assert add(client, "SETUPS").status_code == 400
    assert len(rows(db)) == 1


def test_a_name_refusal_carries_the_current_tabs(client, db):
    # A tab added in another window: the refusal brings the stale page up to date.
    add(client, "Ideas")
    r = add(client, "ideas")
    assert r.status_code == 400 and [t["key"] for t in r.get_json()["tabs"]][-1] == "notes-t1"
    r = change(client, "notes-nuggets", label="IDEAS")
    assert r.status_code == 400 and '"Ideas"' in r.get_json()["error"]
    assert [t["key"] for t in r.get_json()["tabs"]] == ["notes-watchlist", "notes-nuggets", "notes-t1"]


@pytest.mark.parametrize("label", [
    "\u200b", "\u200b\u200b ", "\u2060", "\u00ad",           # invisible only
    "\u202eSetups", "Set\u2066ups", "\u200fmacro",            # text-direction marks
])
def test_invisible_and_direction_marked_names_are_refused(client, db, label):
    assert add(client, label).status_code == 400
    assert rows(db) == []


def test_a_character_python_doesnt_know_yet_counts_as_visible(client):
    # Unassigned in this Python's Unicode tables (as a newer emoji is on the
    # server's Python 3.11); a lone surrogate is refused (not storable).
    assert add(client, "\U0001FAEF").status_code == 201
    assert add(client, "a\ud800b").status_code == 400


def test_emoji_sequences_are_fine(client):
    family = "\U0001F468\u200d\U0001F469\u200d\U0001F467"    # joined with zero-width joiners
    r = add(client, family + " plans")
    assert r.status_code == 201 and bar(client)[-1] == ("notes-t1", family + " plans")


def test_the_name_of_an_archived_tab_can_be_used_again(client):
    add(client, "Setups")
    assert change(client, "notes-t1", archived=True).status_code == 200
    r = add(client, "Setups")
    assert r.status_code == 201 and r.get_json()["key"] == "notes-t2"


def test_the_tab_bar_holds_at_most_20_tabs(client, db):
    for i in range(18):
        assert add(client, f"Tab {i}").status_code == 201
    assert len(bar(client)) == 20
    r = add(client, "One more")
    assert r.status_code == 409
    assert "at most 20" in r.get_json()["error"] and len(r.get_json()["tabs"]) == 20
    assert len(rows(db)) == 18
    # Archiving one frees a place.
    assert change(client, "notes-t3", archived=True).status_code == 200
    assert add(client, "One more").status_code == 201


def test_at_most_200_added_tabs_are_kept(client, db, monkeypatch):
    monkeypatch.setattr(wp, "NOTE_TABS_TOTAL_MAX", 3)
    for i in range(3):
        add(client, f"Tab {i}")
        change(client, f"notes-t{i + 1}", archived=True)
    r = add(client, "Fourth")
    assert r.status_code == 409 and "archived ones included; delete an archived tab first" in r.get_json()["error"]
    assert len(bar(client)) == 2
    # Landing 83: deleting an archived tab frees its place (its key is still never used again).
    assert delete(client, "notes-t2").status_code == 200
    assert add(client, "Fourth").get_json()["key"] == "notes-t4"


def test_keys_are_never_reused(client):
    add(client, "A")
    add(client, "B")
    change(client, "notes-t2", archived=True)
    assert add(client, "C").get_json()["key"] == "notes-t3"


# ── The added tab's note ─────────────────────────────────────────────────────

def test_an_added_tab_has_its_own_note(client, db):
    add(client, "Setups")
    r = client.get("/api/page-notes/notes-t1")
    assert r.status_code == 200 and r.get_json()["empty"] is True
    s = client.put("/api/page-notes/notes-t1", json={"delta": doc("Retest of the 4h breaker"), "base_id": None})
    assert s.status_code == 200 and s.get_json()["page"] == "notes-t1"
    assert client.get("/api/page-notes/notes-t1").get_json()["text"] == "Retest of the 4h breaker"
    assert client.get("/api/page-notes/notes-watchlist").get_json()["empty"] is True


def test_a_tab_key_that_was_never_added_is_404(client, db):
    add(client, "Setups")
    for page in ("notes-t2", "notes-t0", "notes-t01", "notes-T1", "notes-t1x", "notes-other"):
        assert client.get(f"/api/page-notes/{page}").status_code == 404, page
        assert client.put(f"/api/page-notes/{page}", json={"delta": doc("x"), "base_id": None}).status_code == 404
    assert db.execute("SELECT COUNT(*) FROM page_notes").fetchone()[0] == 0


def test_an_archived_tab_keeps_its_note_readable_and_savable(client, db):
    add(client, "Setups")
    first = client.put("/api/page-notes/notes-t1", json={"delta": doc("one"), "base_id": None}).get_json()
    change(client, "notes-t1", archived=True)
    assert client.get("/api/page-notes/notes-t1").get_json()["text"] == "one"
    r = client.put("/api/page-notes/notes-t1", json={"delta": doc("two"), "base_id": first["id"]})
    assert r.status_code == 200 and r.get_json()["changed"] is True
    change(client, "notes-t1", archived=False)
    assert client.get("/api/page-notes/notes-t1").get_json()["text"] == "two"


def test_a_failed_tab_lookup_is_500_not_404(client, monkeypatch):
    def boom(page):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(wp, "_page_note_page_known", boom)
    assert client.get("/api/page-notes/notes-t1").status_code == 500
    assert client.put("/api/page-notes/notes-t1", json={"delta": doc("x"), "base_id": None}).status_code == 500


def test_spot_needs_no_lookup_and_the_default_tabs_are_known_until_deleted(client, monkeypatch):
    # Landing 83: a default tab can be deleted, so knowing one reads note_tabs; the Spot note never does.
    for page in wp.PAGE_NOTE_PAGES:
        assert wp._page_note_page_known(page) is True
    monkeypatch.setattr(portfolio_db, "get_connection", lambda: (_ for _ in ()).throw(AssertionError("no lookup")))
    assert wp._page_note_page_known("spot") is True
    assert wp._page_note_page_known("perps") is False
    assert wp._page_note_page_known("notes-x") is False


# ── PUT <key>: rename, archive, restore ──────────────────────────────────────

def test_rename_keeps_the_key_and_the_note(client, db):
    client.put("/api/page-notes/notes-watchlist", json={"delta": doc("BTC 82k"), "base_id": None})
    r = change(client, "notes-watchlist", label="Tokens")
    assert r.status_code == 200 and r.get_json()["changed"] is True
    assert bar(client) == [("notes-watchlist", "Tokens"), ("notes-nuggets", "Nuggets")]
    assert view(client)["tabs"][0]["default"] is True
    assert client.get("/api/page-notes/notes-watchlist").get_json()["text"] == "BTC 82k"
    assert [(r["tab_key"], r["label"], r["position"], r["archived"]) for r in rows(db)] == [
        ("notes-watchlist", "Tokens", 0, 0)]


def test_the_same_name_writes_nothing(client, db):
    r = change(client, "notes-nuggets", label="  Nuggets ")
    assert r.status_code == 200 and r.get_json()["changed"] is False
    assert rows(db) == []


def test_a_change_of_case_alone_is_a_rename(client, db):
    r = change(client, "notes-nuggets", label="NUGGETS")
    assert r.status_code == 200 and r.get_json()["changed"] is True
    assert bar(client)[1] == ("notes-nuggets", "NUGGETS")


def test_renaming_to_another_open_tabs_name_is_refused(client, db):
    r = change(client, "notes-nuggets", label="WatchList")
    assert r.status_code == 400 and '"Watchlist"' in r.get_json()["error"]
    assert rows(db) == []


@pytest.mark.parametrize("body", [
    {}, {"label": ""}, {"label": 3}, {"archived": "yes"}, {"archived": 1}, {"archived": None},
    {"label": "x", "position": 2}, {"key": "notes-t9"},
])
def test_bad_change_bodies_are_400(client, db, body):
    assert client.put(f"{TABS}/notes-watchlist", json=body).status_code == 400
    assert rows(db) == []


def test_changing_an_unknown_tab_is_404(client, db):
    for key in ("notes-t1", "spot", "nope"):
        assert change(client, key, label="x").status_code == 404
    assert rows(db) == []


def test_archive_moves_the_tab_off_the_bar_and_restore_puts_it_at_the_end(client, db):
    add(client, "Setups")
    add(client, "Macro")
    r = change(client, "notes-watchlist", archived=True)
    assert r.status_code == 200 and r.get_json()["changed"] is True
    assert bar(client) == [("notes-nuggets", "Nuggets"), ("notes-t1", "Setups"), ("notes-t2", "Macro")]
    assert archived(client) == [("notes-watchlist", "Watchlist")]
    # Archiving again changes nothing.
    assert change(client, "notes-watchlist", archived=True).get_json()["changed"] is False
    r = change(client, "notes-watchlist", archived=False)
    assert r.status_code == 200 and r.get_json()["changed"] is True
    assert bar(client) == [("notes-nuggets", "Nuggets"), ("notes-t1", "Setups"), ("notes-t2", "Macro"),
                           ("notes-watchlist", "Watchlist")]
    assert archived(client) == []
    assert len(rows(db)) == 4


def test_archived_tabs_are_listed_most_recently_archived_first(client):
    add(client, "A")
    add(client, "B")
    change(client, "notes-t1", archived=True)
    change(client, "notes-t2", archived=True)
    assert archived(client) == [("notes-t2", "B"), ("notes-t1", "A")]
    assert all(t["changed_at"] for t in view(client)["tabs"] if t["archived"])


def test_the_last_open_tab_cant_be_archived(client, db):
    assert change(client, "notes-watchlist", archived=True).status_code == 200
    r = change(client, "notes-nuggets", archived=True)
    assert r.status_code == 409 and "last open tab" in r.get_json()["error"]
    assert r.get_json()["tabs"][0]["key"] == "notes-nuggets"
    assert bar(client) == [("notes-nuggets", "Nuggets")]


def test_restore_is_refused_when_the_bar_is_full(client, db):
    add(client, "Spare")
    change(client, "notes-t1", archived=True)
    for i in range(18):
        add(client, f"Tab {i}")
    r = change(client, "notes-t1", archived=False)
    assert r.status_code == 409 and "at most 20" in r.get_json()["error"]
    assert ("notes-t1", "Spare") in archived(client)


def test_restore_does_not_check_the_name(client):
    add(client, "Setups")
    change(client, "notes-t1", archived=True)
    add(client, "Setups")
    assert change(client, "notes-t1", archived=False).status_code == 200
    assert [label for _, label in bar(client)].count("Setups") == 2


def test_an_archived_tab_is_checked_against_open_names_only_when_it_opens(client, db):
    add(client, "Setups")
    change(client, "notes-t1", archived=True)
    # Renamed while it stays archived: no open tab is involved.
    assert change(client, "notes-t1", label="Watchlist").status_code == 200
    # Renamed and restored together: it would open next to a tab of that name.
    r = change(client, "notes-t1", archived=False, label="nuggets")
    assert r.status_code == 400 and '"Nuggets"' in r.get_json()["error"]
    assert ("notes-t1", "Watchlist") in archived(client)


def test_rename_and_restore_in_one_change(client, db):
    add(client, "Setups")
    change(client, "notes-t1", archived=True)
    r = change(client, "notes-t1", archived=False, label="Setups (old)")
    assert r.status_code == 200
    assert bar(client)[-1] == ("notes-t1", "Setups (old)")
    assert rows(db)[-1]["archived"] == 0 and rows(db)[-1]["label"] == "Setups (old)"


def test_nothing_is_ever_updated_or_deleted(client, db):
    add(client, "A")
    change(client, "notes-t1", label="B")
    change(client, "notes-t1", archived=True)
    change(client, "notes-t1", archived=False)
    order(client, ["notes-t1", "notes-watchlist", "notes-nuggets"])
    got = rows(db)
    assert [r["id"] for r in got] == sorted(r["id"] for r in got)
    assert [(r["label"], r["archived"]) for r in got if r["tab_key"] == "notes-t1"][:3] == [
        ("A", 0), ("B", 0), ("B", 1)]
    first = got[0]
    change(client, "notes-t1", label="C")
    assert rows(db)[0] == first


# ── PUT order ────────────────────────────────────────────────────────────────

def test_order_moves_tabs_and_writes_only_the_moved_ones(client, db):
    add(client, "Setups")
    r = order(client, ["notes-watchlist", "notes-t1", "notes-nuggets"])
    assert r.status_code == 200 and r.get_json()["changed"] is True
    assert [t["key"] for t in r.get_json()["tabs"]] == ["notes-watchlist", "notes-t1", "notes-nuggets"]
    # Watchlist kept its place: rows for Setups (added, moved) and Nuggets only.
    assert [(r["tab_key"], r["position"]) for r in rows(db)] == [
        ("notes-t1", 2), ("notes-t1", 1), ("notes-nuggets", 2)]
    assert bar(client) == [("notes-watchlist", "Watchlist"), ("notes-t1", "Setups"), ("notes-nuggets", "Nuggets")]


def test_the_same_order_writes_nothing(client, db):
    r = order(client, ["notes-watchlist", "notes-nuggets"])
    assert r.status_code == 200 and r.get_json()["changed"] is False
    assert rows(db) == []


def test_the_same_order_writes_nothing_after_an_archive_left_a_gap(client, db):
    add(client, "A")
    add(client, "B")
    change(client, "notes-nuggets", archived=True)       # places 0, 2, 3 remain
    before = rows(db)
    r = order(client, ["notes-watchlist", "notes-t1", "notes-t2"])
    assert r.status_code == 200 and r.get_json()["changed"] is False
    assert rows(db) == before
    # A real move stores the places 0, 1, 2.
    r = order(client, ["notes-t1", "notes-watchlist", "notes-t2"])
    assert r.get_json()["changed"] is True
    assert bar(client) == [("notes-t1", "A"), ("notes-watchlist", "Watchlist"), ("notes-t2", "B")]
    assert [(r["tab_key"], r["position"]) for r in rows(db)[len(before):]] == [
        ("notes-t1", 0), ("notes-watchlist", 1), ("notes-t2", 2)]


@pytest.mark.parametrize("keys", [
    ["notes-watchlist"],                                      # one missing
    ["notes-watchlist", "notes-nuggets", "notes-t1"],         # an archived one included
    ["notes-watchlist", "notes-nuggets", "notes-t9"],         # unknown
    [],
])
def test_an_order_that_is_not_exactly_the_open_tabs_is_409(client, db, keys):
    add(client, "Setups")
    change(client, "notes-t1", archived=True)
    before = rows(db)
    r = order(client, keys)
    assert r.status_code == 409 and "another window" in r.get_json()["error"]
    assert [t["key"] for t in r.get_json()["tabs"] if not t["archived"]] == ["notes-watchlist", "notes-nuggets"]
    assert rows(db) == before


@pytest.mark.parametrize("body", [
    {}, {"keys": "notes-watchlist"}, {"keys": [1, 2]}, {"keys": ["notes-watchlist", "notes-watchlist"]},
    {"keys": ["notes-watchlist", "notes-nuggets"], "extra": True},
])
def test_bad_order_bodies_are_400(client, db, body):
    assert client.put(ORDER, json=body).status_code == 400
    assert rows(db) == []


def test_a_restored_tab_after_reordering_goes_to_the_end(client):
    add(client, "A")
    add(client, "B")
    order(client, ["notes-t2", "notes-t1", "notes-nuggets", "notes-watchlist"])
    change(client, "notes-t1", archived=True)
    change(client, "notes-t1", archived=False)
    assert [k for k, _ in bar(client)] == ["notes-t2", "notes-nuggets", "notes-watchlist", "notes-t1"]


# -- Copy a tab (Landing 81) --------------------------------------------------------------


def copy(client, key, **kw):
    return client.post(f"{TABS}/{key}/copy", **kw)


def save(client, key, text, base=None):
    r = client.put(f"/api/page-notes/{key}", json={"delta": doc(text), "base_id": base})
    assert r.status_code == 200
    return r.get_json()["id"]


def test_a_copy_goes_right_after_its_tab_with_its_latest_note(client, db):
    add(client, "Setups")
    add(client, "Levels")
    v1 = save(client, "notes-t1", "first draft")
    save(client, "notes-t1", "the latest plan", base=v1)
    r = copy(client, "notes-t1")
    assert r.status_code == 201
    j = r.get_json()
    assert (j["key"], j["label"], j["copied_note"]) == ("notes-t3", "Setups (copy)", True)
    assert bar(client) == DEFAULT_BAR + [("notes-t1", "Setups"), ("notes-t3", "Setups (copy)"), ("notes-t2", "Levels")]
    got = client.get("/api/page-notes/notes-t3").get_json()
    assert got["text"] == "the latest plan"
    assert db.execute("SELECT COUNT(*) FROM page_notes WHERE page = 'notes-t3'").fetchone()[0] == 1   # one version, no history
    assert client.get("/api/page-notes/notes-t1").get_json()["text"] == "the latest plan"           # the original is untouched
    assert db.execute("SELECT COUNT(*) FROM page_notes WHERE page = 'notes-t1'").fetchone()[0] == 2


def test_the_copy_and_the_original_are_then_separate_notes(client):
    add(client, "Setups")
    v = save(client, "notes-t1", "shared start")
    copy(client, "notes-t1")
    c = client.get("/api/page-notes/notes-t2").get_json()["id"]
    save(client, "notes-t2", "only in the copy", base=c)
    assert client.get("/api/page-notes/notes-t1").get_json()["text"] == "shared start"
    save(client, "notes-t1", "only in the original", base=v)
    assert client.get("/api/page-notes/notes-t2").get_json()["text"] == "only in the copy"


def test_copying_a_tab_without_a_note_gives_an_empty_tab(client, db):
    r = copy(client, "notes-nuggets")
    assert r.status_code == 201 and r.get_json()["copied_note"] is False
    assert bar(client) == DEFAULT_BAR + [("notes-t1", "Nuggets (copy)")]
    assert client.get("/api/page-notes/notes-t1").get_json()["empty"] is True


def test_a_default_tab_can_be_copied_and_the_order_rows_are_written(client, db):
    save(client, "notes-watchlist", "WIF, PEPE")
    r = copy(client, "notes-watchlist")
    assert r.status_code == 201
    assert bar(client) == [("notes-watchlist", "Watchlist"), ("notes-t1", "Watchlist (copy)"), ("notes-nuggets", "Nuggets")]
    assert client.get("/api/page-notes/notes-t1").get_json()["text"] == "WIF, PEPE"


def test_copy_names_count_up_and_ignore_case(client):
    add(client, "Setups")
    assert copy(client, "notes-t1").get_json()["label"] == "Setups (copy)"
    assert copy(client, "notes-t1").get_json()["label"] == "Setups (copy 2)"
    add(client, "setups (COPY 3)")
    assert copy(client, "notes-t1").get_json()["label"] == "Setups (copy 4)"
    assert copy(client, "notes-t2").get_json()["label"] == "Setups (copy) (copy)"


def test_an_archived_name_can_be_used_by_a_copy(client):
    add(client, "Setups")
    copy(client, "notes-t1")
    change(client, "notes-t2", archived=True)
    assert copy(client, "notes-t1").get_json()["label"] == "Setups (copy)"


def test_a_long_name_is_cut_to_fit(client):
    name = "x" * 40
    add(client, name)
    lab = copy(client, "notes-t1").get_json()["label"]
    assert lab == "x" * 33 + " (copy)" and len(lab) == 40
    lab2 = copy(client, "notes-t1").get_json()["label"]
    assert lab2 == "x" * 31 + " (copy 2)" and len(lab2) == 40


def test_a_cut_never_leaves_a_trailing_space(client):
    add(client, "a" * 32 + " bcdefg")                 # 39 characters; the cut lands just after the space
    lab = copy(client, "notes-t1").get_json()["label"]
    assert lab == "a" * 32 + " (copy)" and "  " not in lab


def test_an_archived_tab_copies_to_the_end_of_the_bar(client):
    add(client, "Setups")
    add(client, "Levels")
    save(client, "notes-t1", "old idea")
    change(client, "notes-t1", archived=True)
    r = copy(client, "notes-t1")
    assert r.status_code == 201
    assert bar(client)[-1] == ("notes-t3", "Setups (copy)")
    assert client.get("/api/page-notes/notes-t3").get_json()["text"] == "old idea"


def test_images_are_shared_not_duplicated(client, db):
    db.execute("INSERT INTO note_images (sha256, mime, width, height, bytes, data, created_at) "
               "VALUES (?, 'image/png', 4, 4, 8, ?, 'now')", ("a" * 64, b"12345678"))
    db.commit()
    img = db.execute("SELECT id FROM note_images").fetchone()[0]
    add(client, "Charts")
    r = client.put("/api/page-notes/notes-t1", json={"delta": {"ops": [{"insert": {"image": f"/api/note-images/{img}"}},
                                                                       {"insert": "\n"}]}, "base_id": None})
    assert r.status_code == 200
    copy(client, "notes-t1")
    assert db.execute("SELECT COUNT(*) FROM note_images").fetchone()[0] == 1
    assert f"/api/note-images/{img}" in json.dumps(client.get("/api/page-notes/notes-t2").get_json()["delta"])


def test_the_copy_respects_the_bar_and_total_limits(client, db, monkeypatch):
    monkeypatch.setattr(wp, "NOTE_TABS_ACTIVE_MAX", 3)
    add(client, "Setups")
    r = copy(client, "notes-t1")
    assert r.status_code == 409 and "at most 3" in r.get_json()["error"] and r.get_json()["tabs"]
    monkeypatch.setattr(wp, "NOTE_TABS_ACTIVE_MAX", 20)
    monkeypatch.setattr(wp, "NOTE_TABS_TOTAL_MAX", 1)
    r = copy(client, "notes-t1")
    assert r.status_code == 409 and "at most 1" in r.get_json()["error"]
    assert len(rows(db)) == 1 and db.execute("SELECT COUNT(*) FROM page_notes").fetchone()[0] == 0


@pytest.mark.parametrize("key", ["notes-t9", "notes-x", "spot", "notes-w1"])
def test_copying_an_unknown_tab_is_404_and_writes_nothing(client, db, key):
    r = copy(client, key)
    assert r.status_code == 404 and rows(db) == []


@pytest.mark.parametrize("kw", [{"json": {"label": "x"}}, {"json": []}, {"data": "x", "content_type": "text/plain"}])
def test_a_body_other_than_empty_is_refused(client, db, kw):
    assert copy(client, "notes-watchlist", **kw).status_code == 400 and rows(db) == []


def test_an_empty_json_body_is_fine(client):
    assert copy(client, "notes-watchlist", json={}).status_code == 201


def test_a_failure_midway_writes_nothing(client, db, monkeypatch):
    add(client, "Setups")
    save(client, "notes-t1", "plan")
    before = (len(rows(db)), db.execute("SELECT COUNT(*) FROM page_notes").fetchone()[0])
    monkeypatch.setattr(wp, "_page_note_latest", lambda conn, page: (_ for _ in ()).throw(RuntimeError("secret")))
    r = copy(client, "notes-t1")
    assert r.status_code == 500 and "secret" not in r.get_data(as_text=True)
    assert (len(rows(db)), db.execute("SELECT COUNT(*) FROM page_notes").fetchone()[0]) == before


def test_the_copy_counts_toward_the_keys_and_keys_are_not_reused(client, db):
    add(client, "A")
    copy(client, "notes-t1")
    change(client, "notes-t2", archived=True)
    assert add(client, "B").get_json()["key"] == "notes-t3"


# -- Delete a tab (Landing 83) ------------------------------------------------------------


def delete(client, key, **kw):
    return client.delete(f"{TABS}/{key}", **kw)


def preview(client, key, keep=None):
    return client.get(f"{TABS}/{key}/delete-preview" + (f"?keep={keep}" if keep is not None else ""))


def store_image(db, n, size=100):
    cur = db.execute("INSERT INTO note_images (sha256, mime, width, height, bytes, data, created_at) "
                     "VALUES (?, 'image/png', 4, 4, ?, ?, 'now')", (str(n) * 64, size, b"x" * size))
    db.commit()
    return cur.lastrowid


def save_images(client, key, ids, base=None, text="chart"):
    ops = [{"insert": text + " "}] + [{"insert": {"image": f"/api/note-images/{i}"}} for i in ids] + [{"insert": "\n"}]
    r = client.put(f"/api/page-notes/{key}", json={"delta": {"ops": ops}, "base_id": base})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["id"]


def counts(db):
    return (len(rows(db)), db.execute("SELECT COUNT(*) FROM page_notes").fetchone()[0],
            db.execute("SELECT COUNT(*) FROM note_images").fetchone()[0])


def test_the_deleted_column_refuses_anything_but_0_or_1(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO note_tabs (tab_key, label, position, archived, deleted, created_at) "
                   "VALUES ('notes-t1', 'x', 0, 0, 2, 'now')")
    db.execute("INSERT INTO note_tabs (tab_key, label, position, archived, created_at) VALUES ('notes-t1', 'x', 0, 0, 'now')")
    assert db.execute("SELECT deleted FROM note_tabs").fetchone()[0] == 0          # rows written as before read 0


def test_deleting_an_open_tab_removes_it_and_every_saved_version(client, db):
    add(client, "Setups")
    add(client, "Levels")
    v1 = save(client, "notes-t1", "first")
    save(client, "notes-t1", "second", base=v1)
    save(client, "notes-t2", "keep me")
    r = delete(client, "notes-t1")
    assert r.status_code == 200
    j = r.get_json()
    assert (j["deleted"], j["label"], j["note_versions"]) == ("notes-t1", "Setups", 2)
    assert j["freed"] == {"count": 0, "bytes": 0} and j["kept_for_drafts"] == {"count": 0, "bytes": 0}
    assert j["usage"]["count"] == 0 and j["usage"]["max_bytes"] == wp.NOTE_IMAGES_TOTAL_MAX_BYTES
    assert [(t["key"], t["label"]) for t in j["tabs"]] == DEFAULT_BAR + [("notes-t2", "Levels")]
    assert bar(client) == DEFAULT_BAR + [("notes-t2", "Levels")] and archived(client) == []
    assert db.execute("SELECT COUNT(*) FROM page_notes WHERE page = 'notes-t1'").fetchone()[0] == 0
    assert client.get("/api/page-notes/notes-t2").get_json()["text"] == "keep me"
    last = rows(db)[-1]
    assert (last["tab_key"], last["label"], last["archived"], last["deleted"]) == ("notes-t1", "Setups", 0, 1)


def test_a_default_tab_can_be_deleted_and_stays_gone(client, db):
    save(client, "notes-watchlist", "WIF, PEPE")
    save(client, "notes-nuggets", "cut losers")
    r = delete(client, "notes-watchlist")
    assert r.status_code == 200 and r.get_json()["label"] == "Watchlist" and r.get_json()["note_versions"] == 1
    assert bar(client) == [("notes-nuggets", "Nuggets")]
    assert client.get("/api/page-notes/notes-watchlist").status_code == 404
    assert client.put("/api/page-notes/notes-watchlist", json={"delta": doc("x"), "base_id": None}).status_code == 404
    portfolio_db.init_db()                                                             # a restart does not bring it back
    assert bar(client) == [("notes-nuggets", "Nuggets")]
    assert client.get("/api/page-notes/notes-nuggets").get_json()["text"] == "cut losers"
    assert wp._page_note_page_known("notes-watchlist") is False and wp._page_note_page_known("notes-nuggets") is True


def test_an_archived_tab_can_be_deleted(client, db):
    add(client, "Old")
    save(client, "notes-t1", "old idea")
    change(client, "notes-t1", archived=True)
    p = preview(client, "notes-t1").get_json()
    assert (p["archived"], p["last_open"], p["note_versions"]) == (True, False, 1)
    r = delete(client, "notes-t1")
    assert r.status_code == 200
    assert archived(client) == [] and bar(client) == DEFAULT_BAR


def test_the_last_open_tab_cant_be_deleted_but_an_archived_one_can(client, db):
    change(client, "notes-watchlist", archived=True)
    assert preview(client, "notes-nuggets").get_json()["last_open"] is True
    before = counts(db)
    r = delete(client, "notes-nuggets")
    assert r.status_code == 409 and "last open tab" in r.get_json()["error"] and r.get_json()["tabs"]
    assert counts(db) == before
    assert delete(client, "notes-watchlist").status_code == 200                       # archived: fine with one tab open
    assert bar(client) == [("notes-nuggets", "Nuggets")] and archived(client) == []


def test_a_deleted_tab_is_unknown_to_every_route(client, db):
    add(client, "Setups")
    add(client, "Levels")
    delete(client, "notes-t1")
    n = counts(db)
    assert change(client, "notes-t1", label="Back").status_code == 404
    assert change(client, "notes-t1", archived=False).status_code == 404
    assert copy(client, "notes-t1").status_code == 404
    assert delete(client, "notes-t1").status_code == 404
    assert preview(client, "notes-t1").status_code == 404
    assert order(client, ["notes-watchlist", "notes-nuggets", "notes-t1", "notes-t2"]).status_code == 409
    assert client.get("/api/page-notes/notes-t1").status_code == 404
    assert client.put("/api/page-notes/notes-t1", json={"delta": doc("x"), "base_id": None}).status_code == 404
    assert counts(db) == n
    r = order(client, ["notes-t2", "notes-watchlist", "notes-nuggets"])               # the rest still reorder
    assert r.status_code == 200 and [k for k, _ in bar(client)] == ["notes-t2", "notes-watchlist", "notes-nuggets"]


def test_keys_are_never_reused_but_a_deleted_tab_frees_its_place_in_the_limit(client, db, monkeypatch):
    add(client, "A")
    add(client, "B")
    delete(client, "notes-t2")
    assert add(client, "C").get_json()["key"] == "notes-t3"
    assert add(client, "B").get_json()["key"] == "notes-t4"                           # the deleted name is free again
    monkeypatch.setattr(wp, "NOTE_TABS_TOTAL_MAX", 3)                                # t1, t3, t4 are kept
    r = add(client, "D")
    assert r.status_code == 409 and "at most 3" in r.get_json()["error"]
    assert copy(client, "notes-t1").status_code == 409
    delete(client, "notes-t4")
    assert add(client, "D").get_json()["key"] == "notes-t5"


def test_images_only_this_tab_uses_are_freed_and_shared_ones_stay(client, db):
    i1, i2, i3, i4 = (store_image(db, n, size=100 * n) for n in (1, 2, 3, 4))
    add(client, "Charts")
    v1 = save_images(client, "notes-t1", [i1])                    # only in an old version: still this tab's
    v2 = save_images(client, "notes-t1", [i2], base=v1)
    copy(client, "notes-t1")                                      # notes-t2 shares i2
    save_images(client, "notes-t1", [i3, i4], base=v2)
    db.execute("INSERT INTO page_notes (page, body_json, body_text, created_at) VALUES ('notes-w1', ?, 'x', 'now')",
               (json.dumps({"ops": [{"insert": {"image": f"/api/note-images/{i4}"}}, {"insert": "\n"}]}),))
    db.commit()                                                   # a Watch List note shares i4
    p = preview(client, "notes-t1").get_json()
    assert p["note_versions"] == 3
    assert p["images"] == {"count": 4, "bytes": 1000} and p["frees"] == {"count": 2, "bytes": 400}
    r = delete(client, "notes-t1")
    assert r.status_code == 200 and r.get_json()["freed"] == {"count": 2, "bytes": 400}
    assert r.get_json()["usage"]["count"] == 2 and r.get_json()["usage"]["bytes"] == 600
    assert sorted(x[0] for x in db.execute("SELECT id FROM note_images")) == [i2, i4]
    assert f"/api/note-images/{i2}" in json.dumps(client.get("/api/page-notes/notes-t2").get_json()["delta"])
    assert client.get(f"/api/note-images/{i2}").status_code == 200


def test_images_an_unsaved_note_uses_are_kept(client, db):
    i1, i2 = store_image(db, 1), store_image(db, 2)
    add(client, "Charts")
    save_images(client, "notes-t1", [i1, i2])
    p = preview(client, "notes-t1", keep=str(i1)).get_json()
    assert p["frees"]["count"] == 1 and p["kept_for_drafts"]["count"] == 1
    r = delete(client, "notes-t1", json={"keep_image_ids": [i1]})
    assert r.status_code == 200 and r.get_json()["kept_for_drafts"]["count"] == 1 and r.get_json()["freed"]["count"] == 1
    assert [x[0] for x in db.execute("SELECT id FROM note_images")] == [i1]


@pytest.mark.parametrize("kw", [
    {"json": {"x": 1}}, {"json": []}, {"data": "x", "content_type": "text/plain"},
    {"json": {"keep_image_ids": "1"}}, {"json": {"keep_image_ids": [0]}}, {"json": {"keep_image_ids": [True]}},
    {"json": {"keep_image_ids": [1.5]}}, {"json": {"keep_image_ids": list(range(1, 2002))}},
])
def test_bad_delete_bodies_are_400_and_delete_nothing(client, db, kw):
    add(client, "Setups")
    before = counts(db)
    assert delete(client, "notes-t1", **kw).status_code == 400
    assert counts(db) == before and bar(client)[-1] == ("notes-t1", "Setups")


def test_an_empty_body_and_an_empty_keep_list_are_fine(client):
    add(client, "A")
    add(client, "B")
    assert delete(client, "notes-t1", json={}).status_code == 200
    assert delete(client, "notes-t2", json={"keep_image_ids": []}).status_code == 200


@pytest.mark.parametrize("keep", ["abc", "1,,2", "0", "-1", "12345678901"])
def test_a_bad_keep_list_on_the_preview_is_400(client, keep):
    assert preview(client, "notes-watchlist", keep=keep).status_code == 400


@pytest.mark.parametrize("key", ["notes-t9", "notes-x", "spot", "notes-w1"])
def test_deleting_an_unknown_tab_is_404_and_writes_nothing(client, db, key):
    assert delete(client, key).status_code == 404 and preview(client, key).status_code == 404 and rows(db) == []


def test_the_preview_writes_nothing(client, db):
    i1 = store_image(db, 1)
    add(client, "Charts")
    save_images(client, "notes-t1", [i1])
    before = counts(db)
    p = preview(client, "notes-t1").get_json()
    assert (p["key"], p["label"], p["note_versions"], p["frees"]["count"]) == ("notes-t1", "Charts", 1, 1)
    assert counts(db) == before


def test_a_failure_midway_deletes_nothing(client, db, monkeypatch):
    i1 = store_image(db, 1)
    add(client, "Charts")
    save_images(client, "notes-t1", [i1])
    before = counts(db)
    monkeypatch.setattr(wp, "_note_images_usage", lambda conn: (_ for _ in ()).throw(RuntimeError("secret")))
    r = delete(client, "notes-t1")
    assert r.status_code == 500 and "secret" not in r.get_data(as_text=True) and "Nothing was changed" in r.get_json()["error"]
    assert counts(db) == before and bar(client)[-1] == ("notes-t1", "Charts")


@pytest.mark.parametrize("key", ["notes-t1", "notes-watchlist"])
def test_a_save_that_races_a_delete_is_refused(client, db, monkeypatch, key):
    add(client, "Setups")
    delete(client, key)
    n = db.execute("SELECT COUNT(*) FROM page_notes").fetchone()[0]
    monkeypatch.setattr(wp, "_page_note_page_known", lambda page: True)   # the page was looked up before the delete
    r = client.put(f"/api/page-notes/{key}", json={"delta": doc("late save"), "base_id": None})
    assert r.status_code == 404
    assert db.execute("SELECT COUNT(*) FROM page_notes").fetchone()[0] == n


def test_other_notes_are_untouched(client, db):
    client.put("/api/page-notes/spot", json={"delta": doc("spot plan"), "base_id": None})
    save(client, "notes-nuggets", "tip")
    add(client, "Setups")
    save(client, "notes-t1", "gone soon")
    delete(client, "notes-t1")
    assert client.get("/api/page-notes/spot").get_json()["text"] == "spot plan"
    assert client.get("/api/page-notes/notes-nuggets").get_json()["text"] == "tip"


def test_deleting_needs_the_login(db, monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    c = wp.app.test_client()
    assert c.delete(f"{TABS}/notes-watchlist").status_code == 401
    assert c.get(f"{TABS}/notes-watchlist/delete-preview").status_code == 401
    assert rows(db) == []



def test_the_preview_stamp_guards_against_a_change_in_between(client, db):
    add(client, "Setups")
    v1 = save(client, "notes-t1", "first")
    p = preview(client, "notes-t1").get_json()
    assert re.fullmatch(r"[0-9]+:[0-9]+", p["stamp"]) and p["note_versions"] == 1
    save(client, "notes-t1", "saved from the phone", base=v1)                       # lands after the question opened
    before = counts(db)
    r = delete(client, "notes-t1", json={"stamp": p["stamp"]})
    assert r.status_code == 409 and r.get_json()["changed"] is True and r.get_json()["tabs"]
    assert counts(db) == before
    p2 = preview(client, "notes-t1").get_json()
    assert p2["note_versions"] == 2 and p2["stamp"] != p["stamp"]
    change(client, "notes-t1", label="Renamed")                                    # a tab change moves the stamp too
    assert delete(client, "notes-t1", json={"stamp": p2["stamp"]}).status_code == 409
    p3 = preview(client, "notes-t1").get_json()
    r = delete(client, "notes-t1", json={"stamp": p3["stamp"], "keep_image_ids": []})
    assert r.status_code == 200 and r.get_json()["note_versions"] == 2


def test_a_note_saved_while_the_preview_was_being_worked_out_makes_the_delete_a_409(client, db, monkeypatch):
    """Landing 93: the stamp is read before the counts. A save that lands between the two reads leaves the stamp
    older than the state, so the delete that uses it is refused (read in the other order, the stamp would be new and
    the counts old, and the delete would pass)."""
    add(client, "Setups")
    save(client, "notes-t1", "first")
    real = wp._watch_delete_plan
    state = {"first": True}

    def plan_then_a_save_lands(conn, key, keep=frozenset()):
        out = real(conn, key, keep)
        if state["first"]:
            state["first"] = False
            other = portfolio_db.get_connection()
            other.execute("INSERT INTO page_notes (page, body_json, body_text, created_at) VALUES (?, ?, ?, 'now')",
                          (key, json.dumps({"ops": [{"insert": "saved elsewhere" + chr(10)}]}), "saved elsewhere"))
            other.commit()
            other.close()
        return out

    monkeypatch.setattr(wp, "_watch_delete_plan", plan_then_a_save_lands)
    p = preview(client, "notes-t1").get_json()
    assert p["note_versions"] == 1                                       # the counts the question shows are the old ones
    monkeypatch.setattr(wp, "_watch_delete_plan", real)
    before = counts(db)
    r = delete(client, "notes-t1", json={"stamp": p["stamp"]})
    assert r.status_code == 409 and r.get_json()["changed"] is True
    assert counts(db) == before
    assert db.execute("SELECT COUNT(*) FROM page_notes WHERE page = 'notes-t1'").fetchone()[0] == 2
    assert delete(client, "notes-t1", json={"stamp": preview(client, "notes-t1").get_json()["stamp"]}).status_code == 200


def test_a_default_tab_without_rows_has_a_stamp(client):
    p = preview(client, "notes-nuggets").get_json()
    assert p["stamp"] == "0:0"
    assert delete(client, "notes-nuggets", json={"stamp": "0:0"}).status_code == 200


@pytest.mark.parametrize("stamp", [5, "abc", "1:2:3", ":1", "1:", "1:" + "9" * 20, ""])
def test_a_bad_stamp_is_400(client, db, stamp):
    add(client, "Setups")
    before = counts(db)
    assert delete(client, "notes-t1", json={"stamp": stamp}).status_code == 400 and counts(db) == before
