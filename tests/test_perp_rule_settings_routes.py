"""Advisor v1, Landing 8b-2: the append-only perp_rule_status and perp_capital
tables, GET /api/trading/advisor/perps/settings, PUT
/api/trading/advisor/perps/rules/<rule_id>/status, PUT
/api/trading/advisor/perps/capital, and the advisor route reading the stored
settings.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). No network. Fake wallet addresses only, built in code;
made-up prices and sizes.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import json
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db
from src.engines import perp_rules as pr

W = "0x" + "d" * 40
MIN = 60000
HOUR = 3600000
DAY = 86400000
T0 = int(datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)
BTC_OPEN, BTC_CLOSE = T0, T0 + 20 * HOUR
SOL_OPEN = T0 + 3 * DAY


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def fill(coin, tid, t, side, sz, px, start, oid, pnl="0"):
    return {"coin": coin, "tid": tid, "time": t, "side": side, "sz": sz, "px": px, "startPosition": start,
            "closedPnl": pnl, "fee": "0", "builderFee": "0", "dir": "x", "oid": oid, "hash": "0x0"}


def rec(oid, px, placed, coin, status="open", status_ts=None, kind="Stop Market"):
    return {"status": status, "statusTimestamp": status_ts if status_ts is not None else placed,
            "order": {"coin": coin, "side": "A", "oid": oid, "timestamp": placed, "triggerPx": str(px),
                      "isTrigger": True, "reduceOnly": True, "isPositionTpsl": False, "orderType": kind,
                      "children": []}}


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {W: {"label": "HL main"}})
    monkeypatch.setattr(wp, "_hl_post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HL call")))
    monkeypatch.setattr(wp, "_txflow_post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no TxFlow call")))
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": None, "wallets": {}})
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    conn = portfolio_db.get_connection()
    conn.execute("INSERT INTO hl_sync_state (wallet, first_seen_at, last_sync_at, last_ok_at) VALUES (?, ?, ?, ?)",
                 (W, "2026-09-01T00:00:00+00:00", "2026-09-26T00:00:00+00:00", "2026-09-26T00:00:00+00:00"))
    # BTC: a closed long (stop hit; 1R 10); SOL: an open long.
    for f in (fill("BTC", 1, BTC_OPEN, "B", "0.01", "100000", "0", 101),
              fill("BTC", 2, BTC_CLOSE, "A", "0.01", "99000", "0.01", 11, pnl="-10"),
              fill("SOL", 3, SOL_OPEN, "B", "10", "150", "0", 103)):
        conn.execute("INSERT INTO hl_fills (wallet, tid, coin, time_ms, raw_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (W, f["tid"], f["coin"], f["time"], json.dumps(f), "2026-09-26T00:00:00+00:00"))
    records = [rec(11, 99000, BTC_OPEN + MIN, "BTC"), rec(11, 99000, BTC_OPEN + MIN, "BTC", "triggered", BTC_CLOSE),
               rec(15, 145, SOL_OPEN + MIN, "SOL")]
    for i, r in enumerate(records):
        conn.execute("INSERT INTO hl_orders (wallet, oid, coin, status, status_ts, order_ts, raw_json, fetched_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (W, r["order"]["oid"], r["order"]["coin"], r["status"], r["statusTimestamp"] + i,
                      r["order"]["timestamp"], json.dumps(r), "2026-09-26T00:00:00+00:00"))
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def client(db, monkeypatch):
    calls = []
    for name in ("_maybe_kick_hl_trades_refresh", "_maybe_kick_txflow_trades_refresh",
                 "_maybe_kick_hl_accounts_refresh", "_maybe_kick_txflow_refresh", "_trade_snapshot_pass",
                 "_trade_exit_pass_safe", "_trade_snapshot_worker", "_hl_candles_range", "_hl_candles_before"):
        monkeypatch.setattr(wp, name, lambda *a, _n=name, **k: calls.append(_n) or
                            (_ for _ in ()).throw(AssertionError(f"{_n} called")))
    monkeypatch.setattr(wp.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP")))
    monkeypatch.setattr(wp.requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP")))
    monkeypatch.setattr(threading.Thread, "start", lambda self, *a, **k: calls.append("thread"))
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    c.calls = calls
    return c


def put_status(client, rule_id, body):
    return client.put(f"/api/trading/advisor/perps/rules/{rule_id}/status", json=body)


def put_capital(client, body):
    return client.put("/api/trading/advisor/perps/capital", json=body)


def status_rows(db):
    return [dict(r) for r in db.execute("SELECT * FROM perp_rule_status ORDER BY id")]


def capital_rows(db):
    return [dict(r) for r in db.execute("SELECT * FROM perp_capital ORDER BY id")]


def advisor(client):
    r = client.get("/api/trading/advisor/perps")
    assert r.status_code == 200, r.get_data(as_text=True)
    text = r.get_data(as_text=True)
    assert re.search(r"0x[0-9a-fA-F]{40}", text) is None and W[2:] not in text
    return r.get_json()


def btc_id(db):
    trades, _ = wp._trades_build(db)
    return next(t["trade_id"] for t in trades if t["symbol"] == "BTC")


def rules_of(body, tid):
    return {x["rule"]: x for x in body["trades"][tid]["rules"]}


# ── the tables ───────────────────────────────────────────────────────────

def test_tables_created_with_check_constraints(db):
    cols = lambda t: [r[1] for r in db.execute(f"PRAGMA table_info({t})")]
    assert cols("perp_rule_status") == ["id", "rule_id", "status", "reason", "effective_from", "created_at"]
    assert cols("perp_capital") == ["id", "from_date", "capital_usd", "created_at"]
    for sql, args in (("INSERT INTO perp_rule_status (rule_id, status, effective_from, created_at) VALUES (?, ?, 'x', 'x')",
                       ("E1", "off")),
                      ("INSERT INTO perp_capital (from_date, capital_usd, created_at) VALUES (?, ?, 'x')",
                       ("2026-10-01", 0)),
                      ("INSERT INTO perp_capital (from_date, capital_usd, created_at) VALUES (?, ?, 'x')",
                       ("2026-10-01", 1.5)),
                      ("INSERT INTO perp_capital (from_date, capital_usd, created_at) VALUES (?, ?, 'x')",
                       ("Oct 1", 60000))):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(sql, args)
    db.execute("INSERT INTO perp_capital (from_date, capital_usd, created_at) VALUES ('2026-10-01', NULL, 'x')")
    db.execute("INSERT INTO perp_rule_status (rule_id, status, effective_from, created_at) "
               "VALUES ('NEW9', 'tracking', 'x', 'x')")                     # rule ids are checked by the route only
    db.rollback()


def test_init_db_twice_and_upgrade_from_an_older_database(db):
    db.execute("INSERT INTO trade_tags (trade_id, setup, created_at) VALUES ('tKEEP', 'retest', 'x')")
    db.commit()
    db.execute("DROP TABLE perp_rule_status")                              # as before Landing 8b-2
    db.execute("DROP TABLE perp_capital")
    db.commit()
    portfolio_db.init_db()
    assert status_rows(db) == [] and capital_rows(db) == []
    db.execute("INSERT INTO perp_rule_status (rule_id, status, reason, effective_from, created_at) "
               "VALUES ('E3', 'tracking', 'r', '2026-10-06T00:00:00+00:00', '2026-10-06T00:00:00+00:00')")
    db.execute("INSERT INTO perp_capital (from_date, capital_usd, created_at) VALUES ('2026-10-01', 60000, 'x')")
    db.commit()
    before = (status_rows(db), capital_rows(db))
    portfolio_db.init_db()
    portfolio_db.init_db()
    assert (status_rows(db), capital_rows(db)) == before
    assert db.execute("SELECT COUNT(*) FROM trade_tags WHERE trade_id = 'tKEEP'").fetchone()[0] == 1
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


# ── GET settings ─────────────────────────────────────────────────────────

def test_get_settings_defaults_without_a_trade_build(db, client, monkeypatch):
    monkeypatch.setattr(wp, "_trades_build", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no build")))
    r = client.get("/api/trading/advisor/perps/settings")
    assert r.status_code == 200
    body = r.get_json()
    assert body == json.loads(json.dumps(pr.settings_view(None)))
    assert {x["id"]: x["flippable"] for x in body["rules"]}["M3"] is False
    assert body["capital"] == {"usd": 50000, "from": "2026-09-13"} and body["capital_start"] == "2026-09-13"
    assert client.calls == []


# ── PUT status ───────────────────────────────────────────────────────────

def test_status_put_validation(db, client):
    assert put_status(client, "Z9", {"status": "tracking", "reason": "x"}).status_code == 404
    assert put_status(client, "r1", {"status": "tracking", "reason": "x"}).status_code == 404
    r = put_status(client, "M3", {"status": "enforced"})
    assert r.status_code == 400 and "fixed" in r.get_json()["error"]
    assert client.put("/api/trading/advisor/perps/rules/E1/status", data="x",
                      content_type="application/json").status_code == 400
    for body in ([], {}, {"status": "off"}, {"status": True}, {"status": "tracking", "reason": 5},
                 {"status": "tracking", "reason": "x" * 501}, {"status": "tracking"},
                 {"status": "tracking", "reason": "   "}, {"status": "tracking", "reason": None}):
        r = put_status(client, "E1", body)
        assert r.status_code == 400, body
    assert "reason is required" in put_status(client, "E1", {"status": "tracking"}).get_json()["error"]
    assert status_rows(db) == []


def test_status_relax_then_tighten(db, client):
    r = put_status(client, "E3", {"status": "tracking", "reason": "  tagging is not a habit yet  "})
    assert r.status_code == 200
    body = r.get_json()
    assert body["id"] == "E3" and body["status"] == "tracking" and body["default_status"] == "enforced"
    assert body["status_reason"] == "tagging is not a habit yet" and body["flippable"] is True
    rows = status_rows(db)
    assert len(rows) == 1 and rows[0]["effective_from"] == rows[0]["created_at"] == body["status_since"]
    r = put_status(client, "E3", {"status": "enforced"})                     # tightening needs no reason
    assert r.status_code == 200 and r.get_json()["status"] == "enforced" and r.get_json()["status_reason"] is None
    rows = status_rows(db)
    assert len(rows) == 2 and rows[1]["reason"] is None
    view = client.get("/api/trading/advisor/perps/settings").get_json()
    assert [(c["rule"], c["status"], c["reason"]) for c in view["status_changes"]] == [
        ("E3", "tracking", "tagging is not a habit yet"), ("E3", "enforced", None)]
    assert view["settings_changed_at"] == rows[1]["created_at"]


def test_same_status_writes_nothing(db, client):
    assert put_status(client, "E1", {"status": "enforced"}).status_code == 200
    assert put_status(client, "R4", {"status": "tracking", "reason": "x"}).status_code == 200
    assert status_rows(db) == []
    put_status(client, "E1", {"status": "tracking", "reason": "first"})
    r = put_status(client, "E1", {"status": "tracking", "reason": "second"})
    assert r.status_code == 200 and r.get_json()["status_reason"] == "first"
    assert len(status_rows(db)) == 1


def test_r4_can_be_enforced_without_a_reason(db, client):
    r = put_status(client, "R4", {"status": "enforced"})
    assert r.status_code == 200 and r.get_json()["status"] == "enforced"
    assert [(x["rule_id"], x["status"], x["reason"]) for x in status_rows(db)] == [("R4", "enforced", None)]


# ── PUT capital ──────────────────────────────────────────────────────────

def test_capital_put_validation(db, client):
    far = (datetime.now(timezone.utc).date() + timedelta(days=wp.PERP_CAPITAL_MAX_AHEAD_DAYS + 1)).isoformat()
    bad = [[], {}, {"from": "2026-10-01"}, {"usd": 60000},
           {"from": "2026-9-13", "usd": 60000}, {"from": "2026-09-31", "usd": 60000},
           {"from": "20260913", "usd": 60000}, {"from": 20260913, "usd": 60000}, {"from": None, "usd": 60000},
           {"from": "2026-09-12", "usd": 60000}, {"from": far, "usd": 60000},
           {"from": "2026-10-01", "usd": True}, {"from": "2026-10-01", "usd": "60000"},
           {"from": "2026-10-01", "usd": 0}, {"from": "2026-10-01", "usd": -1},
           {"from": "2026-10-01", "usd": 1.5}, {"from": "2026-10-01", "usd": wp.PERP_CAPITAL_MAX_USD + 1}]
    for body in bad:
        r = put_capital(client, body)
        assert r.status_code == 400, body
    assert "before 2026-09-13" in put_capital(client, {"from": "2026-09-12", "usd": 1}).get_json()["error"]
    assert capital_rows(db) == []


def test_capital_set_supersede_and_remove(db, client):
    def periods(r):
        assert r.status_code == 200, r.get_data(as_text=True)
        return [(p["from"], p["usd"]) for p in r.get_json()["capital_periods"]]

    assert periods(put_capital(client, {"from": "2026-09-13", "usd": 50000})) == [("2026-09-13", 50000)]
    assert capital_rows(db) == []                                           # same as the default: nothing written
    assert periods(put_capital(client, {"from": "2026-10-01", "usd": 60000})) == [("2026-09-13", 50000),
                                                                                   ("2026-10-01", 60000)]
    put_capital(client, {"from": "2026-10-01", "usd": 60000})                # unchanged: nothing written
    assert len(capital_rows(db)) == 1
    put_capital(client, {"from": "2026-10-01", "usd": 70000.0})              # a whole-number float is fine
    assert capital_rows(db)[-1]["capital_usd"] == 70000 and isinstance(capital_rows(db)[-1]["capital_usd"], int)
    assert periods(put_capital(client, {"from": "2026-10-01", "usd": None})) == [("2026-09-13", 50000)]
    assert len(capital_rows(db)) == 3
    put_capital(client, {"from": "2026-10-01", "usd": None})                 # already removed
    put_capital(client, {"from": "2026-10-09", "usd": None})                 # nothing stored that day
    assert len(capital_rows(db)) == 3
    assert periods(put_capital(client, {"from": "2026-09-13", "usd": 60000})) == [("2026-09-13", 60000)]
    assert periods(put_capital(client, {"from": "2026-09-13", "usd": 50000})) == [("2026-09-13", 50000)]
    r = put_capital(client, {"from": "2026-09-13", "usd": None})             # the stored 50000 goes; the default stays
    assert r.get_json()["capital_periods"] == [{"from": "2026-09-13", "usd": 50000, "set_at": None}]
    assert [x["capital_usd"] for x in capital_rows(db)] == [60000, 70000, None, 60000, 50000, None]
    assert r.get_json()["capital"] == {"usd": 50000, "from": "2026-09-13"}


# ── the advisor reads the settings ───────────────────────────────────────

def test_no_settings_leaves_the_advisor_unchanged_and_missing_tables_fall_back(db, client):
    body = advisor(client)
    assert set(body) == {"definition_version", "capital", "rules", "trades", "tally", "note"}
    assert body["rules"] == [dict(r) for r in pr.RULES] and body["capital"] == {"usd": 50000, "from": "2026-09-13"}
    for ev in body["trades"].values():
        for r in ev["rules"]:
            assert r["status"] == pr._STATUS[r["rule"]]
            assert "notes" not in r or r["rule"] == "M2"
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    assert wp._perp_rule_settings(mem) == {"status": [], "capital": []}
    mem.close()
    db.execute("DROP TABLE perp_rule_status")
    db.execute("DROP TABLE perp_capital")
    db.commit()
    assert advisor(client) == body
    assert client.get("/api/trading/advisor/perps/settings").get_json() == json.loads(json.dumps(pr.settings_view(None)))


def test_advisor_judges_each_trade_by_the_status_at_its_open(db, client):
    tid = btc_id(db)                                                           # opened 2026-09-20
    assert put_status(client, "R1", {"status": "tracking", "reason": "testing"}).status_code == 200
    body = advisor(client)
    r1 = rules_of(body, tid)["R1"]
    assert r1["status"] == "enforced" and len(r1["notes"]) == 1
    assert r1["notes"][0].startswith("enforced when this trade opened; tracking since ")
    assert {r["id"]: r["status"] for r in body["rules"]}["R1"] == "tracking"


def test_advisor_uses_dated_capital_with_a_note_when_backdated(db, client):
    tid = btc_id(db)
    before = rules_of(advisor(client), tid)["R2"]
    assert before["verdict"] == "pass" and "(0.02% of capital)" in before["evidence"] and "notes" not in before
    assert put_capital(client, {"from": "2026-09-13", "usd": 10000}).status_code == 200
    body = advisor(client)
    r2 = rules_of(body, tid)["R2"]
    assert "(0.10% of capital)" in r2["evidence"]
    assert len(r2["notes"]) == 1 and r2["notes"][0].startswith("capital entry for 2026-09-13 made ")
    assert r2["notes"][0].endswith(", after the trade opened") and "$" not in r2["notes"][0]
    assert body["capital"] == {"usd": 10000, "from": "2026-09-13"}


def test_reads_stay_read_only_and_rows_only_grow(db, client):
    put_status(client, "E1", {"status": "tracking", "reason": "a"})
    put_capital(client, {"from": "2026-10-01", "usd": 60000})
    before = "\n".join(db.iterdump())
    advisor(client)
    client.get("/api/trading/advisor/perps/settings")
    db2 = portfolio_db.get_connection()
    try:
        assert "\n".join(db2.iterdump()) == before
    finally:
        db2.close()
    s0, c0 = status_rows(db), capital_rows(db)
    put_status(client, "E1", {"status": "enforced"})
    put_capital(client, {"from": "2026-10-01", "usd": None})
    s1, c1 = status_rows(db), capital_rows(db)
    assert s1[:len(s0)] == s0 and len(s1) == len(s0) + 1
    assert c1[:len(c0)] == c0 and len(c1) == len(c0) + 1
    assert client.calls == []
