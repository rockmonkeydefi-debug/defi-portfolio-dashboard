"""Landing 31: tabs on the Notes page that Glenn adds, renames, moves and
archives himself - the append-only note_tabs table and the routes
GET / POST /api/note-tabs, PUT /api/note-tabs/order and
PUT /api/note-tabs/<key>. Watchlist and Nuggets exist without a row
(NOTE_TAB_DEFAULTS); added tabs get the keys notes-t1, notes-t2, ...; a
tab's note is the page_notes note under its key, which the notes routes
now accept, archived tabs included. Nothing is deleted.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). No network.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
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
    assert cols == ["id", "tab_key", "label", "position", "archived", "created_at"]
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


def test_at_most_200_tabs_are_ever_added(client, db, monkeypatch):
    monkeypatch.setattr(wp, "NOTE_TABS_TOTAL_MAX", 3)
    for i in range(3):
        add(client, f"Tab {i}")
        change(client, f"notes-t{i + 1}", archived=True)
    r = add(client, "Fourth")
    assert r.status_code == 409 and "restore an archived tab" in r.get_json()["error"]
    assert len(bar(client)) == 2


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


def test_spot_and_the_default_tabs_need_no_lookup(client, monkeypatch):
    monkeypatch.setattr(portfolio_db, "get_connection", lambda: (_ for _ in ()).throw(AssertionError("no lookup")))
    for page in wp.PAGE_NOTE_PAGES:
        assert wp._page_note_page_known(page) is True
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
