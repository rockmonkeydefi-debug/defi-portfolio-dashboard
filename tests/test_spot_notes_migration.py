"""Tests for Landing 2b's one-time move of Trade Log spot notes into the Spot
journal (HANDOFF_spot_perps_rebuild ruling 5 and Q2-A, Oct 4):
POST /api/spot/note-updates/migrate-trade-notes, the spot_note_updates.trade_id
column it fills, and trade_id in the note-update responses.

Real init_db() on a tmp_path SQLite file and the real _trades_build over
seeded spot_transactions, the pattern test_trades_unified.py uses; network
helpers raise. Token contracts are fake strings built in code (the Solana one
is mixed case on purpose); symbols, amounts and notes are made up.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db

EVM = {k: "0x" + str(k) * 40 for k in range(1, 4)}       # fake token contracts
SOL = "FaKeMiNt" + "AbCdEfGhJk" * 3                      # base58-style, mixed case
ROUTE = '/api/spot/note-updates/migrate-trade-notes'
NOTE_A = "Entered on the **weekly** flip.\n- small size"


def _never(*a, **k):
    raise AssertionError("no network in tests")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.setattr(wp, "_hl_post", _never)
    monkeypatch.setattr(wp, "_txflow_post", _never)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {})
    conn = portfolio_db.get_connection()
    yield conn
    conn.close()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def tx(conn, date, symbol, side, units, total, chain="", addr=""):
    conn.execute("INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, chain, "
                 "contract_address) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (date, symbol, side, units, total, total, chain, addr))
    conn.commit()
    return conn.execute("SELECT MAX(id) FROM spot_transactions").fetchone()[0]


def annotate(conn, trade_id, market="spot", updated_at="2026-09-01T00:00:00+00:00", **fields):
    row = {"trade_id": trade_id, "market": market, "created_at": "2026-09-01T00:00:00+00:00",
           "updated_at": updated_at, **fields}
    cols = list(row)
    conn.execute(f"INSERT INTO trade_annotations ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                 tuple(row[c] for c in cols))
    conn.commit()


@pytest.fixture
def seeded(db):
    ids = {}
    first = tx(db, "2026-09-15", "aaa", "buy", 10, 100, "base", EVM[1])            # closed Sep 20
    tx(db, "2026-09-20", "aaa", "sell", 10, 150, "base", EVM[1])
    ids["AAA"] = wp._trade_id(f"base {EVM[1]}|{first}")
    ids["BBB"] = wp._trade_id(f"solana {SOL}|{tx(db, '2026-09-22', 'bbb', 'buy', 5, 50, 'solana', SOL)}")   # open
    first = tx(db, "2026-09-15", "ccc", "buy", 10, 100)                            # symbol-only position
    tx(db, "2026-09-18", "ccc", "sell", 10, 90)
    ids["CCC"] = wp._trade_id(f"CCC|{first}")
    ids["DDD"] = wp._trade_id(f"base {EVM[2]}|{tx(db, '2026-09-23', 'ddd', 'buy', 1, 10, 'base', EVM[2])}")
    ids["EEE"] = wp._trade_id(f"base {EVM[3]}|{tx(db, '2026-09-24', 'eee', 'buy', 1, 10, 'base', EVM[3])}")
    ids["GONE"] = "t" + "0" * 20
    annotate(db, ids["AAA"], updated_at="2026-10-01T15:30:00-07:00", notes=NOTE_A,
             deviation_note="late", followed_rules=0)
    annotate(db, ids["BBB"], updated_at="2026-09-25T10:00:00+00:00", notes="holding")
    annotate(db, ids["CCC"], notes="no address here")
    annotate(db, ids["DDD"], notes="   ")
    annotate(db, ids["EEE"], updated_at="not a date", notes="bad time")
    annotate(db, ids["GONE"], notes="orphan")
    annotate(db, "tperp", market="perp", notes="perp note")
    return ids


def post(client, body=None):
    return client.post(ROUTE, json=body) if body is not None else client.post(ROUTE)


def snapshot(db):
    return {"updates": [dict(r) for r in db.execute("SELECT * FROM spot_note_updates ORDER BY id")],
            "annotations": [dict(r) for r in db.execute("SELECT * FROM trade_annotations ORDER BY trade_id")],
            "revisions": [dict(r) for r in db.execute("SELECT * FROM note_revisions ORDER BY id")]}


def test_dry_run_is_the_default_and_writes_nothing(client, db, seeded):
    before = snapshot(db)
    for r in (post(client), post(client, {})):
        assert r.status_code == 200, r.get_data(as_text=True)
        d = r.get_json()
        assert d["dry_run"] is True
        assert [(m["trade_id"], m["symbol"], m["chain"], m["created_at"], m["chars"], m["after_close"])
                for m in sorted(d["moved"], key=lambda m: m["symbol"])] == [
            (seeded["AAA"], "AAA", "base", "2026-10-01T22:30:00+00:00", len(NOTE_A), True),
            (seeded["BBB"], "BBB", "solana", "2026-09-25T10:00:00+00:00", 7, False)]
        assert sorted((s["trade_id"], s["reason"]) for s in d["skipped"]) == sorted([
            (seeded["CCC"], "no_address"), (seeded["EEE"], "bad_timestamp"), (seeded["GONE"], "unattached")])
        assert d["counts"] == {"moved": 2, "skipped": 3, "blank": 1, "after_close": 1}
        assert "_notes" not in d["moved"][0] and "_address" not in d["moved"][0]
    assert snapshot(db) == before


def test_real_run_moves_links_and_clears(client, db, seeded):
    r = post(client, {"dry_run": False})
    assert r.status_code == 200 and r.get_json()["dry_run"] is False and r.get_json()["counts"]["moved"] == 2
    ups = {u["trade_id"]: u for u in snapshot(db)["updates"]}
    assert set(ups) == {seeded["AAA"], seeded["BBB"]}
    a, b = ups[seeded["AAA"]], ups[seeded["BBB"]]
    assert (a["chain"], a["contract_address"], a["body"], a["created_at"], a["edited_at"], a["deleted_at"]) == \
           ("base", EVM[1], NOTE_A, "2026-10-01T22:30:00+00:00", None, None)
    assert (b["chain"], b["contract_address"], b["body"]) == ("solana", SOL, "holding")      # Solana case kept
    ann = {x["trade_id"]: x for x in snapshot(db)["annotations"]}
    assert ann[seeded["AAA"]]["notes"] is None and ann[seeded["BBB"]]["notes"] is None
    assert ann[seeded["AAA"]]["deviation_note"] == "late" and ann[seeded["AAA"]]["followed_rules"] == 0
    assert ann[seeded["AAA"]]["updated_at"] > "2026-10-01"
    for k, text in (("CCC", "no address here"), ("EEE", "bad time"), ("GONE", "orphan"), ("DDD", "   ")):
        assert ann[seeded[k]]["notes"] == text                                              # left in place
    assert ann["tperp"]["notes"] == "perp note"
    revs = snapshot(db)["revisions"]
    assert sorted((x["kind"], x["ref"], x["old_text"], x["action"]) for x in revs) == sorted([
        ("trade_notes", seeded["AAA"], NOTE_A, "edit"), ("trade_notes", seeded["BBB"], "holding", "edit")])
    listed = {u["trade_id"]: u for u in client.get('/api/spot/note-updates').get_json()}
    assert listed[seeded["BBB"]]["position_key"] == "solana " + SOL and listed[seeded["AAA"]]["body"] == NOTE_A


def test_second_run_moves_nothing(client, db, seeded):
    post(client, {"dry_run": False})
    after_first = snapshot(db)
    d = post(client, {"dry_run": False}).get_json()
    assert d["counts"] == {"moved": 0, "skipped": 3, "blank": 1, "after_close": 0} and d["moved"] == []
    assert snapshot(db) == after_first


@pytest.mark.parametrize("body", [{"dry_run": "false"}, {"dry_run": 0}, {"dry_run": None}, [1]])
def test_bad_bodies_are_rejected_and_write_nothing(client, db, seeded, body):
    before = snapshot(db)
    r = post(client, body)
    assert r.status_code == 400
    assert snapshot(db) == before


def test_a_failure_moves_nothing(client, db, seeded, monkeypatch):
    before = snapshot(db)
    real = wp._note_revision
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("disk full")
        return real(*a, **k)
    monkeypatch.setattr(wp, "_note_revision", flaky)
    r = post(client, {"dry_run": False})
    assert r.status_code == 500 and r.get_json() == {"error": "disk full"}
    assert snapshot(db) == before


def test_updates_added_on_the_spot_page_have_no_trade_id(client, db):
    r = client.post('/api/spot/note-updates', json={'chain': 'base', 'contract_address': EVM[1], 'body': 'x'})
    assert r.status_code == 201 and r.get_json()["trade_id"] is None
    assert client.get('/api/spot/note-updates').get_json()[0]["trade_id"] is None
