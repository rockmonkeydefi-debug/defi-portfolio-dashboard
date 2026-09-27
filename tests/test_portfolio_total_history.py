"""Snapshot history for the complete total (HANDOFF_total_history.md).

Covers the portfolio_total_snapshots table and its insert/read helpers, the
read-only GET /api/history/portfolio-total route, the extraction of
/api/portfolio/total's input gathering, and the snapshot writer.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched), so portfolio_snapshots and the new table are the real schema.
No network: Hyperliquid runs only through a stubbed wp._hl_fetch_accounts."""
import json
import sqlite3
from datetime import datetime, timedelta

import pytest

import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

A = "0x" + "a" * 40
B = "0x" + "b" * 40


@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    return path


def _open(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _total_row(ts, status="completed", hl_counted=1, total=100.0, detail=None, **extra):
    row = {"timestamp": ts, "status": status, "definition_version": 1, "total_usd": total,
           "snapshot_total_usd": 90.0, "wallets_total": 2, "wallets_completed": 2, "hl_counted": hl_counted,
           "detail_json": json.dumps(detail) if detail is not None else None}
    row.update(extra)
    return row


# ── commit 1: table, helpers, read route ───────────────────────────────────

def test_init_db_creates_table_with_exact_columns_and_is_idempotent(dbpath):
    portfolio_db.init_db()                                                   # second run raises nothing
    conn = _open(dbpath)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(portfolio_total_snapshots)")]
    idx = [r["name"] for r in conn.execute("PRAGMA index_list(portfolio_total_snapshots)")]
    conn.close()
    assert cols == ["id"] + list(portfolio_db.PORTFOLIO_TOTAL_SNAPSHOT_COLUMNS)
    assert "idx_portfolio_total_snapshots_user_ts" in idx


def test_insert_read_round_trip_order_and_days_filter(dbpath):
    now = datetime.utcnow()
    newer = (now - timedelta(hours=1)).isoformat()
    older = (now - timedelta(hours=3)).isoformat()
    ancient = (now - timedelta(days=40)).isoformat()
    id1 = portfolio_db.insert_portfolio_total_snapshot(_total_row(newer, hyperliquid_usd=7.5, error=None), user_id=1)
    id2 = portfolio_db.insert_portfolio_total_snapshot(_total_row(older, total=50.0))
    id3 = portfolio_db.insert_portfolio_total_snapshot(_total_row(ancient))
    assert id1 and id2 and id3
    rows = portfolio_db.get_portfolio_total_snapshots(user_id=1, days=30)
    assert [r["id"] for r in rows] == [id2, id1]                                         # ascending, ancient excluded
    r1 = rows[1]
    assert set(r1) == {"id"} | set(portfolio_db.PORTFOLIO_TOTAL_SNAPSHOT_COLUMNS)
    assert (r1["timestamp"], r1["status"], r1["definition_version"], r1["total_usd"], r1["hyperliquid_usd"],
            r1["user_id"], r1["stablecoins_usd"]) == (newer, "completed", 1, 100.0, 7.5, 1, None)
    assert [r["id"] for r in portfolio_db.get_portfolio_total_snapshots(user_id=1, days=9999)] == [id3, id2, id1]


def test_route_empty(client, dbpath):
    r = client.get("/api/history/portfolio-total")
    assert r.status_code == 200 and r.get_json() == []


def test_route_usable_and_detail(client, dbpath):
    now = datetime.utcnow()
    detail = {"status": "ok", "total_usd": 100.0, "components": [{"key": "hyperliquid", "counted": True}]}
    rows = [
        _total_row((now - timedelta(hours=4)).isoformat(), detail=detail),                 # usable
        _total_row((now - timedelta(hours=3)).isoformat(), hl_counted=0),                   # HL not counted
        _total_row((now - timedelta(hours=2)).isoformat(), status="partial"),               # partial
        _total_row((now - timedelta(hours=1)).isoformat(), status="failed", total=None, detail_json="{not json"),
    ]
    for row in rows:
        portfolio_db.insert_portfolio_total_snapshot(row)
    body = client.get("/api/history/portfolio-total").get_json()
    assert [b["usable"] for b in body] == [True, False, False, False]
    assert all("detail" not in b and "detail_json" not in b for b in body)
    body = client.get("/api/history/portfolio-total?detail=1&days=2").get_json()
    assert [b["detail"] for b in body] == [detail, None, None, None]                  # unparseable -> None
    assert all("detail_json" not in b for b in body)
    assert client.get("/api/history/portfolio-total?days=0").get_json() == body_without_detail(body)


def body_without_detail(body):
    return [{k: v for k, v in b.items() if k != "detail"} for b in body]


def test_route_unauthenticated_401(dbpath, monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    r = wp.app.test_client().get("/api/history/portfolio-total")
    assert r.status_code == 401
