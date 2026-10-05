"""Advisor v1, Landing 8b-1: setup and point-of-interest trade tags - the
append-only trade_tags table, PUT /api/trading/trades/<trade_id>/tags,
GET /api/trading/trade-tags, and the advisor route reading the stored tags
(E2 setup, E3 POI).

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
from datetime import datetime, timezone

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db

W = "0x" + "c" * 40
MIN = 60000
HOUR = 3600000
DAY = 86400000
T0 = int(datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)
BTC_OPEN, BTC_CLOSE = T0, T0 + 20 * HOUR
SOL_OPEN = T0 + 3 * DAY
FAKE_ID = "tTEST000000000000001"


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


def snapshot(**pos):
    tfs = {tf: {"position": pos.get(tf, "above")} for tf in ("15m", "30m", "1h", "4h", "12h", "1d", "1w")}
    return json.dumps({"trend": {"v": 1, "reason": None, "timeframes": tfs}})


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
    # BTC: a closed long (stop hit); SOL: an open long.
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
    # A manual perp trade and a manual spot trade.
    for ticker, market in (("DOGE", "perp"), ("PEPE", None)):
        conn.execute("INSERT INTO spot_trade_log (ticker, direction, source, venue, entry_price, stop_price, qty, "
                     "target_price, exit_price, entered_at, exited_at, followed_rules, market, created_at, updated_at) "
                     "VALUES (?, 'long', 'MHC', 'Manual', 0.2, 0.19, 1000, 0.23, 0.22, ?, ?, 1, ?, 'x', 'x')",
                     (ticker, _iso(T0 + HOUR), _iso(T0 + 5 * HOUR), market))
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


def ids(db):
    trades, _ = wp._trades_build(db)
    return {t["symbol"]: t["trade_id"] for t in trades}


def put(client, trade_id, body):
    return client.put(f"/api/trading/trades/{trade_id}/tags", json=body)


def rows(db):
    return [dict(r) for r in db.execute("SELECT * FROM trade_tags ORDER BY id")]


def no_address(text):
    assert re.search(r"0x[0-9a-fA-F]{40}", text) is None and W not in text and W[2:] not in text


BREAK = {"kind": "trendline", "timeframe": "4h"}
POI = {"type": "order_block", "timeframe": "1h"}


# ── the table ────────────────────────────────────────────────────────────

def test_table_created_with_check_constraints(db):
    cols = [r["name"] for r in db.execute("PRAGMA table_info(trade_tags)")]
    assert cols == ["id", "trade_id", "setup", "break_kind", "break_timeframe", "setup_tagged_at", "poi_type",
                    "poi_timeframe", "poi_tagged_at", "created_at"]
    assert any(r["name"] == "idx_trade_tags_trade" for r in db.execute("PRAGMA index_list(trade_tags)"))
    for col, bad in (("setup", "pullback"), ("break_kind", "wedge"), ("break_timeframe", "2h"),
                     ("poi_type", "vwap"), ("poi_timeframe", "3d")):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(f"INSERT INTO trade_tags (trade_id, {col}, created_at) VALUES (?, ?, 'x')", (FAKE_ID, bad))
    db.execute("INSERT INTO trade_tags (trade_id, setup, created_at) VALUES (?, 'retest', 'x')", (FAKE_ID,))
    db.commit()
    portfolio_db.init_db()                                                        # idempotent
    assert len(rows(db)) == 1


# ── PUT ──────────────────────────────────────────────────────────────────

def test_put_retest(db, client):
    tid = ids(db)["BTC"]
    r = put(client, tid, {"setup": "retest"})
    body = r.get_json()
    assert r.status_code == 200 and body["trade_id"] == tid and body["setup"] == "retest"
    assert body["break_what"] is None and body["poi"] is None and body["poi_tagged_at"] is None
    assert body["setup_tagged_at"].endswith("+00:00")
    assert len(rows(db)) == 1 and rows(db)[0]["trade_id"] == tid
    no_address(r.get_data(as_text=True))


def test_put_breakout_needs_break_what(db, client):
    tid = ids(db)["BTC"]
    for body in ({"setup": "breakout"}, {"setup": "breakout", "break_what": None},
                 {"setup": "breakout", "break_what": {"kind": "trendline"}},
                 {"setup": "breakout", "break_what": {"kind": "wedge", "timeframe": "4h"}},
                 {"setup": "breakout", "break_what": {"kind": "trendline", "timeframe": "2h"}}):
        r = put(client, tid, body)
        assert r.status_code == 400 and "break_what" in r.get_json()["error"]
    r = put(client, tid, {"setup": "breakout", "break_what": BREAK})
    assert r.status_code == 200 and r.get_json()["break_what"] == BREAK
    assert rows(db)[-1]["break_kind"] == "trendline" and rows(db)[-1]["break_timeframe"] == "4h"


def test_break_what_only_with_a_breakout(db, client):
    tid = ids(db)["BTC"]
    for body in ({"setup": "retest", "break_what": BREAK}, {"setup": None, "break_what": BREAK},
                 {"poi": POI, "break_what": BREAK}):
        r = put(client, tid, body)
        assert r.status_code == 400 and "break_what" in r.get_json()["error"]
    assert rows(db) == []


def test_poi_both_or_none(db, client):
    tid = ids(db)["BTC"]
    for poi in ({"type": "fvg"}, {"timeframe": "1h"}, {"type": "fvg", "timeframe": None}, "fvg"):
        r = put(client, tid, {"poi": poi})
        assert r.status_code == 400 and "poi" in r.get_json()["error"]
    r = put(client, tid, {"poi": POI})
    assert r.status_code == 200 and r.get_json()["poi"] == POI and r.get_json()["setup"] is None


def test_invalid_values_and_bodies(db, client):
    tid = ids(db)["BTC"]
    for body in ({"setup": "Retest"}, {"setup": True}, {"setup": 1}, {"poi": {"type": 5, "timeframe": "1h"}},
                 {"poi": {"type": "fvg", "timeframe": True}}, {}, {"notes": "x"}):
        r = put(client, tid, body)
        assert r.status_code == 400 and r.get_json()["error"], body
    for raw in ("[1, 2]", '"retest"', "not json", ""):
        r = client.put(f"/api/trading/trades/{tid}/tags", data=raw, content_type="application/json")
        assert r.status_code == 400
    assert rows(db) == []


def test_404_unknown_and_spot_and_manual_perp_allowed(db, client):
    t = ids(db)
    r = put(client, FAKE_ID, {"setup": "retest"})
    assert r.status_code == 404
    r = put(client, t["PEPE"], {"setup": "retest"})                                  # a spot trade
    assert r.status_code == 404
    r = put(client, t["DOGE"], {"setup": "other", "poi": {"type": "sfp", "timeframe": "15m"}})   # manual perp
    assert r.status_code == 200 and r.get_json()["setup"] == "other"
    assert [row["trade_id"] for row in rows(db)] == [t["DOGE"]]


# ── carry-over, unchanged and cleared ────────────────────────────────────

def test_carry_over_both_ways(db, client, monkeypatch):
    tid = ids(db)["BTC"]
    first = put(client, tid, {"setup": "retest"}).get_json()
    second = put(client, tid, {"poi": POI}).get_json()
    assert second["setup"] == "retest" and second["setup_tagged_at"] == first["setup_tagged_at"]
    assert second["poi"] == POI and second["poi_tagged_at"]
    third = put(client, tid, {"setup": "breakout", "break_what": BREAK}).get_json()
    assert third["poi"] == POI and third["poi_tagged_at"] == second["poi_tagged_at"]
    assert third["setup"] == "breakout" and third["setup_tagged_at"] >= second["poi_tagged_at"]
    # A changed break_what alone is a changed setup part.
    fourth = put(client, tid, {"setup": "breakout", "break_what": {"kind": "supply_level", "timeframe": "1d"}}).get_json()
    assert fourth["break_what"] == {"kind": "supply_level", "timeframe": "1d"}
    assert len(rows(db)) == 4


def test_identical_put_writes_nothing(db, client):
    tid = ids(db)["BTC"]
    a = put(client, tid, {"setup": "retest", "poi": POI}).get_json()
    n = len(rows(db))
    b = put(client, tid, {"setup": "retest", "poi": POI})
    assert b.status_code == 200 and dict(b.get_json()) == a and len(rows(db)) == n
    c = put(client, tid, {"poi": POI})
    assert c.get_json() == a and len(rows(db)) == n
    # Clearing a trade that has no tag at all writes nothing either.
    sol = ids(db)["SOL"]
    d = put(client, sol, {"setup": None, "poi": None})
    assert d.status_code == 200 and d.get_json()["setup"] is None and len(rows(db)) == n


def test_clear_appends_an_empty_row_and_get_omits_it(db, client):
    t = ids(db)
    put(client, t["BTC"], {"setup": "retest", "poi": POI})
    put(client, t["SOL"], {"setup": "other"})
    before = rows(db)
    r = put(client, t["BTC"], {"setup": None, "poi": None})
    body = r.get_json()
    assert r.status_code == 200 and body["setup"] is None and body["poi"] is None
    assert body["setup_tagged_at"] is None and body["poi_tagged_at"] is None
    after = rows(db)
    assert after[:len(before)] == before and len(after) == len(before) + 1               # history untouched
    last = after[-1]
    assert last["trade_id"] == t["BTC"] and all(last[k] is None for k in wp._TRADE_TAG_FIELDS)
    tags = client.get("/api/trading/trade-tags").get_json()["tags"]
    assert set(tags) == {t["SOL"]}


def test_rows_only_grow(db, client):
    tid = ids(db)["BTC"]
    seen = []
    for body in ({"setup": "retest"}, {"poi": POI}, {"setup": "other"}, {"setup": None}, {"poi": None},
                 {"setup": "retest"}):
        put(client, tid, body)
        now = rows(db)
        assert now[:len(seen)] == seen
        seen = now
    assert len(seen) == 6


# ── GET ──────────────────────────────────────────────────────────────────

def test_get_returns_the_latest_row_per_trade(db, client):
    t = ids(db)
    put(client, t["BTC"], {"setup": "retest"})
    put(client, t["BTC"], {"setup": "breakout", "break_what": BREAK})
    put(client, t["DOGE"], {"poi": POI})
    db.execute("INSERT INTO trade_tags (trade_id, setup, setup_tagged_at, created_at) VALUES (?, 'other', 'x', 'x')",
               (FAKE_ID,))                                                                # a stored id with no trade
    db.commit()
    r = client.get("/api/trading/trade-tags")
    tags = r.get_json()["tags"]
    assert set(tags) == {t["BTC"], t["DOGE"], FAKE_ID}
    assert tags[t["BTC"]]["setup"] == "breakout" and tags[t["BTC"]]["break_what"] == BREAK
    assert set(tags[t["BTC"]]) == {"setup", "break_what", "setup_tagged_at", "poi", "poi_tagged_at"}
    assert tags[t["DOGE"]]["poi"] == POI and tags[FAKE_ID]["setup"] == "other"
    no_address(r.get_data(as_text=True))


def test_missing_table_fallback(db, client, monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    assert wp._trade_tags_latest(conn) == {} and wp._trade_tags_latest(conn, FAKE_ID) == {}
    conn.close()
    db.execute("DROP TABLE trade_tags")
    db.commit()
    assert client.get("/api/trading/trade-tags").get_json() == {"tags": {}}
    r = client.get("/api/trading/advisor/perps")
    assert r.status_code == 200 and r.get_json()["trades"]


# ── the advisor route reads the stored tags ──────────────────────────────

def advisor(client):
    r = client.get("/api/trading/advisor/perps")
    assert r.status_code == 200, r.get_data(as_text=True)
    no_address(r.get_data(as_text=True))
    return r.get_json()


def rules_of(body, tid):
    return {x["rule"]: x for x in body["trades"][tid]["rules"]}


def set_snapshot(db, tid, **pos):
    db.execute("INSERT INTO trade_annotations (trade_id, market, scanner_snapshot_json, created_at, updated_at) "
               "VALUES (?, 'perp', ?, 'x', 'x') ON CONFLICT(trade_id) DO UPDATE SET scanner_snapshot_json = "
               "excluded.scanner_snapshot_json", (tid, snapshot(**pos)))
    db.commit()


def test_no_stored_tag_leaves_not_tagged(db, client):
    tid = ids(db)["BTC"]
    set_snapshot(db, tid)
    rules = rules_of(advisor(client), tid)
    assert rules["E2"]["verdict"] == "not_tagged" and rules["E3"]["verdict"] == "not_tagged"


def test_retest_tag_drives_e2(db, client):
    tid = ids(db)["BTC"]
    set_snapshot(db, tid, **{"15m": "touch"})
    put(client, tid, {"setup": "retest"})
    assert rules_of(advisor(client), tid)["E2"]["verdict"] == "pass"
    set_snapshot(db, tid)                                                      # nothing touching
    rules = rules_of(advisor(client), tid)
    assert rules["E2"]["verdict"] == "fail" and "no timeframe touching" in rules["E2"]["evidence"]


def test_breakout_tag_is_self_reported(db, client):
    tid = ids(db)["BTC"]
    set_snapshot(db, tid)
    put(client, tid, {"setup": "breakout", "break_what": BREAK})
    assert rules_of(advisor(client), tid)["E2"]["verdict"] == "self_reported"


def test_poi_tag_live_vs_after_close(db, client):
    t = ids(db)
    put(client, t["SOL"], {"poi": POI})                       # the trade is still open: tagged live
    put(client, t["BTC"], {"poi": POI})                       # closed in September: tagged after the close
    body = advisor(client)
    sol, btc = rules_of(body, t["SOL"])["E3"], rules_of(body, t["BTC"])["E3"]
    assert sol["verdict"] == "pass" and "tagged live" in sol["evidence"]
    assert btc["verdict"] == "pass" and "tagged after close" in btc["evidence"]


def test_cleared_and_foreign_tags_are_ignored(db, client):
    t = ids(db)
    set_snapshot(db, t["BTC"])
    put(client, t["BTC"], {"setup": "other"})
    put(client, t["BTC"], {"setup": None})
    db.execute("INSERT INTO trade_tags (trade_id, setup, created_at) VALUES (?, 'retest', 'x')", (t["PEPE"],))
    db.commit()
    body = advisor(client)
    assert rules_of(body, t["BTC"])["E2"]["verdict"] == "not_tagged"
    assert t["PEPE"] not in body["trades"]


def test_advisor_stays_read_only_one_build_no_calls(db, client, monkeypatch):
    t = ids(db)
    set_snapshot(db, t["BTC"], **{"15m": "touch"})
    put(client, t["BTC"], {"setup": "retest", "poi": POI})
    before = "\n".join(db.iterdump())
    builds = []
    real = wp._trades_build
    monkeypatch.setattr(wp, "_trades_build", lambda conn, extras=None: builds.append(1) or real(conn, extras))
    body = advisor(client)
    assert builds == [1] and client.calls == []
    assert rules_of(body, t["BTC"])["E2"]["verdict"] == "pass"
    db2 = portfolio_db.get_connection()
    try:
        assert "\n".join(db2.iterdump()) == before
    finally:
        db2.close()
