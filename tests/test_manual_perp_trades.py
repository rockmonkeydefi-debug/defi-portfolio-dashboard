"""Manual perp trades (Landing 3b, HANDOFF_spot_perps_rebuild.md 3.4 and
11.3): spot_trade_log.leverage (guarded ALTER), POST /api/spot/trade-log
with leverage and a trade logged already closed (exit price, followed /
deviated, closed time, deviation note), PUT with leverage, earlier notes and
deviation notes kept in note_revisions on edit and on delete (ruling 4:
existing kinds, ref = the manual trade's opaque trade id), and the manual
trade's leverage in GET /api/trading/trades.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). No network: _hl_post and _txflow_post raise and every
background kick is stubbed. No wallet addresses; amounts are made up.

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

BASE = {"ticker": "SOL", "direction": "long", "entry_price": 100, "stop_price": 95, "qty": 2, "market": "perp",
        "entered_at": "2026-09-20T10:00:00+00:00"}


def _never(*a, **k):
    raise AssertionError("no venue call here")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {})
    monkeypatch.setattr(wp, "_hl_post", _never)
    monkeypatch.setattr(wp, "_txflow_post", _never)
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": None, "wallets": {}})
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    conn = portfolio_db.get_connection()
    yield conn
    conn.close()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(wp, "_maybe_kick_hl_trades_refresh", lambda now, force=False: False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_trades_refresh", lambda now, force=False: False)
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", lambda now: False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", lambda now: False)
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def post(client, **fields):
    return client.post('/api/spot/trade-log', json={**BASE, **fields})


def row(db, trade_id):
    return dict(db.execute("SELECT * FROM spot_trade_log WHERE id = ?", (trade_id,)).fetchone())


def revisions(db):
    return [tuple(r) for r in db.execute("SELECT kind, ref, old_text, action FROM note_revisions ORDER BY id")]


def manual_trade(client, trade_id):
    body = client.get('/api/trading/trades').get_json()
    return next(t for t in body["trades"] if t["manual_id"] == trade_id)


# ── schema ───────────────────────────────────────────────────────────────

def test_leverage_column_added_and_idempotent(db):
    cols = {r["name"]: r["type"] for r in db.execute("PRAGMA table_info(spot_trade_log)")}
    assert cols["leverage"] == "REAL"
    portfolio_db.init_db()                                  # a second call raises nothing
    assert "leverage" in {r["name"] for r in db.execute("PRAGMA table_info(spot_trade_log)")}


# ── POST: leverage ───────────────────────────────────────────────────────

@pytest.mark.parametrize("sent,stored", [(5, 5.0), ("12.5", 12.5), (0.5, 0.5), (1000, 1000.0), (None, None)])
def test_post_stores_leverage(db, client, sent, stored):
    r = post(client, leverage=sent)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert row(db, r.get_json()["id"])["leverage"] == stored


def test_post_without_leverage_leaves_it_null(db, client):
    tid = post(client).get_json()["id"]
    assert row(db, tid)["leverage"] is None


@pytest.mark.parametrize("bad", [0, -2, 1000.5, "abc", "", True, [5], {"x": 1}, float("inf")])
def test_post_rejects_bad_leverage(db, client, bad):
    r = post(client, leverage=bad)
    assert r.status_code == 400
    assert "leverage must be a number above 0" in r.get_json()["error"]
    assert db.execute("SELECT COUNT(*) FROM spot_trade_log").fetchone()[0] == 0


# ── POST: a trade logged already closed ──────────────────────────────────

def test_post_a_closed_trade_in_one_step(db, client):
    r = post(client, leverage=5, exit_price=110, followed_rules=1, exited_at="2026-09-22T10:00:00+00:00",
             deviation_note="Took profit early", target_price=115)
    assert r.status_code == 200, r.get_data(as_text=True)
    stored = row(db, r.get_json()["id"])
    assert (stored["exit_price"], stored["exited_at"], stored["followed_rules"], stored["deviation_note"]) == (
        110.0, "2026-09-22T10:00:00+00:00", 1, "Took profit early")
    t = manual_trade(client, stored["id"])
    assert (t["status"], t["market"], t["net_pnl"], t["leverage"], t["leverage_type"]) == ("closed", "perp", "20.000000", "5", None)
    assert t["r_multiple"] == "2.000000" and t["annotation"]["followed_rules"] is True
    assert t["gate"] == {"eligible": True, "reason": None} and t["target_px"] == "115"


def test_post_closed_defaults_exited_at_to_now(db, client):
    tid = post(client, exit_price=90, followed_rules=0).get_json()["id"]
    stored = row(db, tid)
    assert wp._trades_dt(stored["exited_at"]) >= wp._trades_dt(BASE["entered_at"])
    assert stored["followed_rules"] == 0


@pytest.mark.parametrize("fields,error", [
    ({"exit_price": 110}, "followed_rules (0 or 1) is required to close a trade"),
    ({"exit_price": 110, "followed_rules": 2}, "followed_rules must be 0 or 1"),
    ({"exit_price": 110, "followed_rules": True}, "followed_rules must be 0 or 1"),
    ({"exit_price": 0, "followed_rules": 1}, "exit_price must be a number above 0"),
    ({"exit_price": "x", "followed_rules": 1}, "exit_price must be a number above 0"),
    ({"exit_price": True, "followed_rules": 1}, "exit_price must be a number above 0"),
    ({"exit_price": 110, "followed_rules": 1, "exited_at": "2026-09-19T10:00:00+00:00"},
     "exited_at must be on or after entered_at"),
    ({"exit_price": 110, "followed_rules": 1, "exited_at": "soon"}, "exited_at must be a date and time"),
    ({"exited_at": "2026-09-22T10:00:00+00:00"}, "exited_at needs exit_price"),
    ({"deviation_note": "x" * 2001}, "deviation_note must be a string of up to 2000 characters, or null"),
    ({"deviation_note": 5}, "deviation_note must be a string of up to 2000 characters, or null"),
])
def test_post_closed_validation(db, client, fields, error):
    r = post(client, **fields)
    assert r.status_code == 400 and r.get_json() == {"error": error}
    assert db.execute("SELECT COUNT(*) FROM spot_trade_log").fetchone()[0] == 0


def test_post_followed_without_exit_is_kept(db, client):
    tid = post(client, followed_rules=1).get_json()["id"]
    stored = row(db, tid)
    assert stored["followed_rules"] == 1 and stored["exit_price"] is None
    assert manual_trade(client, tid)["status"] == "open"


# ── PUT: leverage ────────────────────────────────────────────────────────

def test_put_sets_and_clears_leverage(db, client):
    tid = post(client).get_json()["id"]
    assert client.put(f'/api/spot/trade-log/{tid}', json={"leverage": "7.5"}).status_code == 200
    assert row(db, tid)["leverage"] == 7.5
    assert manual_trade(client, tid)["leverage"] == "7.5"
    listed = next(t for t in client.get('/api/spot/trade-log').get_json()["trades"] if t["id"] == tid)
    assert listed["leverage"] == 7.5
    assert client.put(f'/api/spot/trade-log/{tid}', json={"leverage": None}).status_code == 200
    assert row(db, tid)["leverage"] is None and manual_trade(client, tid)["leverage"] is None
    r = client.put(f'/api/spot/trade-log/{tid}', json={"leverage": -1})
    assert r.status_code == 400 and "leverage must be" in r.get_json()["error"]


# ── note revisions ───────────────────────────────────────────────────────

def test_put_keeps_earlier_notes_and_deviation_notes(db, client):
    tid = post(client, notes="first plan").get_json()["id"]
    ref = wp._trade_id(f"manual|{tid}")
    client.put(f'/api/spot/trade-log/{tid}', json={"notes": "first plan"})                 # same text
    client.put(f'/api/spot/trade-log/{tid}', json={"deviation_note": "late entry"})         # from NULL
    assert revisions(db) == []
    client.put(f'/api/spot/trade-log/{tid}', json={"notes": "second plan", "deviation_note": "late entry, sized up"})
    assert revisions(db) == [("trade_notes", ref, "first plan", "edit"),
                             ("trade_deviation_note", ref, "late entry", "edit")]
    client.put(f'/api/spot/trade-log/{tid}', json={"notes": None})
    assert revisions(db)[-1] == ("trade_notes", ref, "second plan", "edit")
    assert row(db, tid)["notes"] is None
    assert manual_trade(client, tid)["trade_id"] == ref                 # the id the trades route emits


def test_put_without_note_fields_adds_no_revision(db, client):
    tid = post(client, notes="plan").get_json()["id"]
    client.put(f'/api/spot/trade-log/{tid}', json={"exit_price": 101, "followed_rules": 1})
    assert revisions(db) == []


def test_delete_keeps_the_texts(db, client):
    tid = post(client, notes="why I took it", deviation_note="moved the stop").get_json()["id"]
    ref = wp._trade_id(f"manual|{tid}")
    assert client.delete(f'/api/spot/trade-log/{tid}').status_code == 200
    assert db.execute("SELECT COUNT(*) FROM spot_trade_log").fetchone()[0] == 0
    assert revisions(db) == [("trade_notes", ref, "why I took it", "delete"),
                             ("trade_deviation_note", ref, "moved the stop", "delete")]


def test_delete_without_notes_or_unknown_id(db, client):
    tid = post(client).get_json()["id"]
    assert client.delete(f'/api/spot/trade-log/{tid}').status_code == 200
    assert client.delete('/api/spot/trade-log/9999').status_code == 200        # unchanged behaviour
    assert revisions(db) == []


# ── trades route ─────────────────────────────────────────────────────────

def test_rows_logged_before_3b_have_no_leverage(db, client):
    db.execute("INSERT INTO spot_trade_log (ticker, direction, source, entry_price, stop_price, qty, entered_at, market) "
               "VALUES ('ARB', 'short', 'manual', 0.8, 0.86, 1000, '2026-09-21T15:00:00+00:00', 'perp')")
    db.commit()
    t = next(x for x in client.get('/api/trading/trades').get_json()["trades"] if x["symbol"] == "ARB")
    assert t["leverage"] is None and t["leverage_type"] is None and t["source"] == "manual"


@pytest.fixture(autouse=True)
def _gate_counts_every_date(monkeypatch):
    """Landing 15: the gate counts only perp trades opened on or after
    TRADES_GATE_COUNT_FROM. This file's trades are dated before it and test
    the other gate checks, so the count date is set to 1970-01-01 here, which
    is the gate as it was before Landing 15 (before_rule is still the only
    date check). tests/test_gate_count_from.py tests the date itself."""
    monkeypatch.setattr(wp, "TRADES_GATE_COUNT_FROM", "1970-01-01")


@pytest.fixture(autouse=True)
def _gate_without_rule_check(monkeypatch):
    """Landing 17: a trade that passes the gate's own checks also needs the
    rule check (_trades_rule_gate). This file's trades carry no setup / POI
    tags and test the gate's own checks, so the rule check is turned off
    here, which is the gate as it was before Landing 17.
    tests/test_gate_rule_check.py tests the rule check itself."""
    monkeypatch.setattr(wp, "_trades_rule_gate", lambda conn, trades, now_ms=None: None)
