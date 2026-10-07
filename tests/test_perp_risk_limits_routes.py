"""Advisor v1, Landing 16: the append-only perp_risk_limits table, PUT
/api/trading/advisor/perps/risk-limits (bounds, reasons, the risk gate), the
settings GET's risk keys, and the advisor route judging R2 by the stored
limits.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). No network. Fake wallet addresses only, built in code;
made-up prices and sizes.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import json
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
from src.engines import perp_rules as pr

W = "0x" + "e" * 40
MIN = 60000
HOUR = 3600000
T0 = int(datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)
LOCKED = {"start": "2026-09-13", "count_from": "2026-10-05", "target": 20, "eligible_count": 3,
          "expectancy_r": "0.400000", "unlocked": False, "by_market": {}}
UNLOCKED = dict(LOCKED, eligible_count=21, unlocked=True)


def fill(coin, tid, t, side, sz, px, start, oid, pnl="0"):
    return {"coin": coin, "tid": tid, "time": t, "side": side, "sz": sz, "px": px, "startPosition": start,
            "closedPnl": pnl, "fee": "0", "builderFee": "0", "dir": "x", "oid": oid, "hash": "0x0"}


def rec(oid, px, placed, coin, status="open", status_ts=None):
    return {"status": status, "statusTimestamp": status_ts if status_ts is not None else placed,
            "order": {"coin": coin, "side": "A", "oid": oid, "timestamp": placed, "triggerPx": str(px),
                      "isTrigger": True, "reduceOnly": True, "isPositionTpsl": False, "orderType": "Stop Market",
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
    # BTC: a closed long opened Sep 20, stop 99,000 placed a minute in and hit: 1R = 0.01 x 1,000 = $10.
    for f in (fill("BTC", 1, T0, "B", "0.01", "100000", "0", 101),
              fill("BTC", 2, T0 + 20 * HOUR, "A", "0.01", "99000", "0.01", 11, pnl="-10")):
        conn.execute("INSERT INTO hl_fills (wallet, tid, coin, time_ms, raw_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (W, f["tid"], f["coin"], f["time"], json.dumps(f), "2026-09-26T00:00:00+00:00"))
    for i, r in enumerate([rec(11, 99000, T0 + MIN, "BTC"), rec(11, 99000, T0 + MIN, "BTC", "triggered", T0 + 20 * HOUR)]):
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


@pytest.fixture
def gate(monkeypatch):
    """The risk gate as _perp_risk_gate reports it; set state["gate"] to change it. Counts the reads."""
    state = {"gate": LOCKED, "reads": 0}

    def fake(conn):
        state["reads"] += 1
        return state["gate"]
    monkeypatch.setattr(wp, "_perp_risk_gate", fake)
    return state


def put(client, body):
    return client.put("/api/trading/advisor/perps/risk-limits", json=body)


def rows(db):
    return [dict(r) for r in db.execute("SELECT * FROM perp_risk_limits ORDER BY id")]


# ── the table ──────────────────────────────────────────────────────────────

def test_table_columns_and_checks(db):
    cols = [r["name"] for r in db.execute("PRAGMA table_info(perp_risk_limits)")]
    assert cols == ["id", "per_trade_bps", "total_bps", "reason", "effective_from", "created_at"]
    sql = "INSERT INTO perp_risk_limits (per_trade_bps, total_bps, effective_from, created_at) VALUES (?, ?, 'x', 'x')"
    for bad in ((0, 500), (-5, 500), (150, 100), (100, 10001), (1.5, 500), (None, 500), (100, None)):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(sql, bad)
    db.execute(sql, (200, 500))
    db.execute(sql, ("100", 500))               # INTEGER affinity stores the text "100" as the integer 100
    db.commit()
    portfolio_db.init_db()                      # idempotent: the rows survive a second start
    assert [(r["per_trade_bps"], r["total_bps"]) for r in rows(db)] == [(200, 500), (100, 500)]
    assert db.execute("SELECT typeof(per_trade_bps) FROM perp_risk_limits WHERE id = 2").fetchone()[0] == "integer"


def test_settings_without_the_table(db):
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    assert wp._perp_rule_settings(mem) == {"status": [], "capital": [], "risk": []}
    mem.close()


# ── the settings GET ───────────────────────────────────────────────────────

def test_settings_get_has_the_risk_keys_without_a_trade_build(db, client, monkeypatch):
    monkeypatch.setattr(wp, "_trades_build", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no build")))
    body = client.get("/api/trading/advisor/perps/settings").get_json()
    assert body == json.loads(json.dumps(pr.settings_view(None)))
    assert body["risk_limits"] == {"per_trade_bps": 100, "total_bps": 500, "since": None, "reason": None}
    assert body["risk_bounds"] == {"min_bps": 10, "per_trade_max_bps": 200, "total_max_bps": 500, "locked_max_bps": 100}


# ── PUT: validation ────────────────────────────────────────────────────────

@pytest.mark.parametrize("body,needle", [
    (["x"], "JSON object"),
    ({"per_trade_pct": 1}, "required"),
    ({"total_pct": 5}, "required"),
    ({"per_trade_pct": True, "total_pct": 5}, "per_trade_pct must be a number"),
    ({"per_trade_pct": "1", "total_pct": 5}, "per_trade_pct must be a number"),
    ({"per_trade_pct": None, "total_pct": 5}, "per_trade_pct must be a number"),
    ({"per_trade_pct": 1, "total_pct": "5"}, "total_pct must be a number"),
    ({"per_trade_pct": 1.234, "total_pct": 5}, "at most 2 decimals"),
    ({"per_trade_pct": 1, "total_pct": 4.999}, "at most 2 decimals"),
    ({"per_trade_pct": float("nan"), "total_pct": 5}, "per_trade_pct"),
    ({"per_trade_pct": 0.05, "total_pct": 5}, "from 0.1 to 2"),
    ({"per_trade_pct": 0, "total_pct": 5}, "from 0.1 to 2"),
    ({"per_trade_pct": 2.5, "total_pct": 5}, "from 0.1 to 2"),
    ({"per_trade_pct": 1, "total_pct": 6}, "at most 5"),
    ({"per_trade_pct": 1.5, "total_pct": 1}, "at least per_trade_pct"),
    ({"per_trade_pct": 0.5, "total_pct": 3, "reason": 5}, "reason must be text"),
    ({"per_trade_pct": 0.5, "total_pct": 3, "reason": "x" * 501}, "500 characters"),
])
def test_bad_bodies_are_refused(db, client, gate, body, needle):
    r = put(client, body)
    assert r.status_code == 400 and needle in r.get_json()["error"], r.get_json()
    assert rows(db) == [] and gate["reads"] == 0


# ── PUT: lowering, raising, reasons ────────────────────────────────────────

def test_same_limits_write_nothing(db, client, gate):
    r = put(client, {"per_trade_pct": 1, "total_pct": 5})
    assert r.status_code == 200 and rows(db) == []
    assert r.get_json()["risk_limits"] == {"per_trade_bps": 100, "total_bps": 500, "since": None, "reason": None}


def test_lowering_needs_no_reason_and_no_gate(db, client, gate):
    r = put(client, {"per_trade_pct": 0.5, "total_pct": 3})
    assert r.status_code == 200 and gate["reads"] == 0
    (row,) = rows(db)
    assert (row["per_trade_bps"], row["total_bps"], row["reason"]) == (50, 300, None)
    assert row["effective_from"] == row["created_at"]
    body = r.get_json()
    assert body["risk_limits"]["per_trade_bps"] == 50 and body["risk_limits"]["since"] == row["effective_from"]
    assert body["risk_changes"] == [{"per_trade_bps": 50, "total_bps": 300, "from": row["effective_from"], "reason": None}]


def test_raising_needs_a_reason(db, client, gate):
    put(client, {"per_trade_pct": 0.5, "total_pct": 3})
    for body in ({"per_trade_pct": 0.75, "total_pct": 3}, {"per_trade_pct": 0.5, "total_pct": 4},
                 {"per_trade_pct": 0.75, "total_pct": 4, "reason": "   "}):
        r = put(client, body)
        assert r.status_code == 400 and "reason is required" in r.get_json()["error"]
    r = put(client, {"per_trade_pct": 1, "total_pct": 5, "reason": "  back to the defaults  "})
    assert r.status_code == 200 and rows(db)[-1]["reason"] == "back to the defaults"
    assert gate["reads"] == 0                                          # never above 1%


def test_raising_above_1_percent_is_refused_while_the_gate_is_locked(db, client, gate):
    r = put(client, {"per_trade_pct": 2, "total_pct": 5, "reason": "sizing up"})
    assert r.status_code == 409 and gate["reads"] == 1 and rows(db) == []
    body = r.get_json()
    assert body["error"].startswith("the risk gate is locked (Stay at 1%): per trade can go above 1% only once 20+")
    assert "since 2026-10-05" in body["error"] and "now 3, average 0.400000R" in body["error"]
    assert body["gate"] == LOCKED
    assert put(client, {"per_trade_pct": 1.01, "total_pct": 5, "reason": "x"}).status_code == 409


def test_raising_to_2_percent_once_the_gate_is_unlocked(db, client, gate):
    gate["gate"] = UNLOCKED
    r = put(client, {"per_trade_pct": 2, "total_pct": 5, "reason": "gate unlocked"})
    assert r.status_code == 200 and gate["reads"] == 1
    assert [(x["per_trade_bps"], x["total_bps"], x["reason"]) for x in rows(db)] == [(200, 500, "gate unlocked")]


def test_a_stored_raise_survives_the_gate_locking_again(db, client, gate):
    gate["gate"] = UNLOCKED
    put(client, {"per_trade_pct": 2, "total_pct": 5, "reason": "gate unlocked"})
    gate["gate"] = LOCKED
    gate["reads"] = 0
    # lowering the total (per trade stays 2%) and lowering per trade need no gate
    assert put(client, {"per_trade_pct": 2, "total_pct": 4}).status_code == 200
    assert put(client, {"per_trade_pct": 1.5, "total_pct": 4}).status_code == 200
    assert gate["reads"] == 0
    # going back up from 1.5% to 2% is above both 1% and the limit now: the gate is read again and refuses
    r = put(client, {"per_trade_pct": 2, "total_pct": 4, "reason": "again"})
    assert r.status_code == 409 and gate["reads"] == 1
    assert "above 1.5% only once" in r.get_json()["error"]
    assert [(x["per_trade_bps"], x["total_bps"]) for x in rows(db)] == [(200, 500), (200, 400), (150, 400)]


def test_up_to_1_percent_never_reads_the_gate(db, client, gate):
    put(client, {"per_trade_pct": 0.25, "total_pct": 1})
    assert put(client, {"per_trade_pct": 1, "total_pct": 5, "reason": "x"}).status_code == 200
    assert gate["reads"] == 0


def test_the_real_gate_is_read_and_locked_without_trades(db, client):
    # No stub: the trades are built once and the seeded BTC trade (unreviewed) doesn't count.
    r = put(client, {"per_trade_pct": 2, "total_pct": 5, "reason": "x"})
    assert r.status_code == 409 and r.get_json()["gate"]["unlocked"] is False
    assert r.get_json()["gate"]["eligible_count"] == 0 and rows(db) == [] and client.calls == []


# ── the advisor route reads the stored limits ──────────────────────────────

def test_advisor_judges_r2_by_the_stored_limits(db, client):
    def r2():
        body = client.get("/api/trading/advisor/perps").get_json()
        (ev,) = body["trades"].values()
        return next(r for r in ev["rules"] if r["rule"] == "R2")
    # Capital 5,000 from Sep 13: the BTC trade's 1R $10 is 0.2% of it.
    db.execute("INSERT INTO perp_capital (from_date, capital_usd, created_at) VALUES ('2026-09-13', 5000, '2026-09-13T00:00:00+00:00')")
    db.commit()
    assert r2()["verdict"] == "pass"
    # A 0.1% per-trade limit in force before the trade opened (inserted directly: the route only saves forward).
    db.execute("INSERT INTO perp_risk_limits (per_trade_bps, total_bps, reason, effective_from, created_at) "
               "VALUES (10, 500, NULL, '2026-09-01T00:00:00+00:00', '2026-09-01T00:00:00+00:00')")
    db.commit()
    res = r2()
    assert res["verdict"] == "fail" and res["evidence"].startswith("over 0.1% per trade")
    # A later change (made now) leaves the trade judged at 0.1%, with a note.
    assert client.put("/api/trading/advisor/perps/risk-limits",
                      json={"per_trade_pct": 1, "total_pct": 5, "reason": "back to 1%"}).status_code == 200
    res = r2()
    assert res["verdict"] == "fail" and res["notes"][-1].startswith("limits 0.1% / 5% when this trade opened; 1% / 5% since")
