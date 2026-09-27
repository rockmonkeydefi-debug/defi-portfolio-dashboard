"""Snapshot history for the complete total (HANDOFF_total_history.md).

Covers the portfolio_total_snapshots table and its insert/read helpers, the
read-only GET /api/history/portfolio-total route, the extraction of
/api/portfolio/total's input gathering, and the snapshot writer.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched), so portfolio_snapshots and the new table are the real schema.
No network: Hyperliquid runs only through a stubbed wp._hl_fetch_accounts."""
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import maxfi_schema
import portfolio_total as pt
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


# ── commit 2: /api/portfolio/total input extraction ────────────────────────
# Same fixture state as tests/test_portfolio_total.py's
# test_route_warm_cache_cache_only_no_writes, reproduced here (that file is
# not modified).

H = "0x" + "c" * 40          # a hidden wallet


def _portfolio():
    return {
        "tokens": [
            {"symbol": "ETH", "value_usd": 2000.0, "wallet": A},
            {"symbol": "USDC", "value_usd": 300.0, "wallet": A},
            {"symbol": "usdt", "value_usd": 200.0, "wallet": B},
        ],
        "lp_positions": [
            {"protocol": "snuggle", "chain": "robinhood", "wallet": A, "total_value_usd": 700.0, "total_fees_usd": 0},
            {"protocol": "uniswap_v3", "chain": "base", "wallet": A, "total_value_usd": 500.0, "total_fees_usd": 5.0},
        ],
        "aave_positions": [], "gmx_positions": [], "staking_positions": [],
        "total_tokens_value": 2500.0, "total_lp_value": 1200.0, "total_uncollected_fees": 5.0, "total_value": 3705.0,
        "wallet_labels": {A: "Rabby", B: "Other"},
        "fetched_at": "2026-09-27T11:50:00",
    }


@pytest.fixture
def mem_db(monkeypatch):
    uri = f"file:portfolio_total_history_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    maxfi_schema.ensure_maxfi_tables(keepalive)
    keepalive.commit()

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    yield keepalive
    keepalive.close()


def _seed(db, pid, wallet, uncollected, chain="robinhood", status="open", value=700.0,
          value_at="2026-09-27T11:00:00+00:00", scan="2026-09-27T10:00:00+00:00"):
    db.execute(
        """INSERT INTO maxfi_positions (id, chain, wallet, token_id, array_index, pool_address, token0_address,
             token1_address, fee_tier, status, first_seen_at, first_seen_at_source, last_scan_at,
             last_value_usd, last_value_at, last_uncollected_usd)
           VALUES (?, ?, ?, ?, ?, '0xpool', '0xt0', '0xt1', 3000, ?, '2026-01-01T00:00:00+00:00', 'chain', ?, ?, ?, ?)""",
        (pid, chain, wallet, str(pid), pid, status, scan, value, value_at, uncollected))
    db.commit()


def _warm_route_state(db, monkeypatch):
    config = {A: {"label": "Rabby", "maxfi": True}, B: {"label": "Other"},
              H: {"label": "Hidden", "hidden": True, "maxfi": True}}
    monkeypatch.setattr(wp, "load_wallet_config", lambda: config)
    cache = _portfolio()
    monkeypatch.setattr(wp, "_portfolio_cache", cache)

    def _never(*a, **k):
        raise AssertionError("get_portfolio_data must not be called")
    monkeypatch.setattr(wp, "get_portfolio_data", _never)
    _seed(db, 1, A.upper().replace("0X", "0x"), 10.0)
    _seed(db, 2, A, 20.0)
    _seed(db, 3, A, 99.0, status="closed", scan="2026-09-27T11:59:00+00:00")
    _seed(db, 4, H, 50.0)
    monkeypatch.setattr(wp, "_maxfi_ledger_load_inputs", lambda conn, chain=None: {"x": 1})
    monkeypatch.setattr(wp, "_maxfi_ledger_position_claims",
                        lambda **kw: {1: {"ledger_head_closed": False}, 2: {"ledger_head_closed": True}})
    return cache


def test_route_equals_compose_total_of_the_extracted_helpers(client, mem_db, monkeypatch):
    cache = _warm_route_state(mem_db, monkeypatch)
    r = client.get("/api/portfolio/total")
    now_utc = datetime.now(timezone.utc)
    assert r.status_code == 200
    inputs = wp._portfolio_total_db_inputs()
    assert sorted(inputs) == ["latest_scan_by_key", "ledger_head_closed_ids", "ledger_ok", "maxfi_rows"]
    assert inputs["ledger_head_closed_ids"] == {2} and inputs["ledger_ok"] is True
    expected = pt.compose_total(cache, inputs["maxfi_rows"], inputs["ledger_head_closed_ids"], inputs["ledger_ok"],
                                inputs["latest_scan_by_key"], wp._hl_accounts_cache_copy(), now_utc)
    assert r.get_json() == json.loads(wp.app.json.dumps(expected))
    assert r.get_json()["total_usd"] == pytest.approx(3705.0 + 8.5)
