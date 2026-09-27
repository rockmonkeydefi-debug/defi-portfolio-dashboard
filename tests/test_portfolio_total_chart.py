"""Dashboard chart series over portfolio_total_snapshots: the pure
portfolio_total_chart.build_chart and GET /api/history/portfolio-total-chart
(HANDOFF_total_history.md, "Chart route (Dashboard redesign)").

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). Synthetic values only; no network."""
import sqlite3
from datetime import datetime, timedelta

import pytest

import portfolio_total_chart as ptc
import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

EMPTY = {"points": [], "seams": [], "excluded": {"not_usable": 0, "incomplete": 0, "unparseable": 0}, "benchmarks": []}


@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    return path


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _row(i, ts, v=1, total=100.0, snap=80.0, hl=15.0, status="completed", hl_counted=1, wt=2, wc=2):
    return {"id": i, "timestamp": ts, "status": status, "definition_version": v, "total_usd": total,
            "snapshot_total_usd": snap, "hyperliquid_usd": hl, "hl_counted": hl_counted,
            "wallets_total": wt, "wallets_completed": wc}


# ── build_chart ────────────────────────────────────────────────────────────

def test_t1_points_basis0_and_seam():
    rows = [_row(1, "2026-09-27T10:00:00", v=0, total=95.0, snap=80.0, hl=15.0),
            _row(2, "2026-09-27T12:00:00", v=0, total=96.0, snap=81.0, hl=15.0),
            _row(3, "2026-09-27T18:58:12.345678", v=1, total=110.0, snap=90.0, hl=15.0),
            _row(4, "2026-09-27T20:00:00", v=1, total=111.0, snap=91.0, hl=14.5)]
    out = ptc.build_chart(rows, [])
    assert [p["id"] for p in out["points"]] == [1, 2, 3, 4]
    assert out["points"][2]["t"] == "2026-09-27T18:58:12.345Z"
    assert out["points"][0] == {"id": 1, "t": "2026-09-27T10:00:00.000Z", "v": 0, "total": 95.0, "basis0": 95.0}
    assert all(p["basis0"] == p["total"] for p in out["points"] if p["v"] == 0)
    assert [p["basis0"] for p in out["points"] if p["v"] == 1] == [105.0, 105.5]
    assert out["seams"] == [{"t": "2026-09-27T18:58:12.345Z", "from_v": 0, "to_v": 1}]
    assert out["excluded"] == {"not_usable": 0, "incomplete": 0, "unparseable": 0}


def test_t2_exclusions():
    rows = [_row(1, "2026-09-27T10:00:00"),
            _row(2, "2026-09-27T10:01:00", status="partial"),
            _row(3, "2026-09-27T10:02:00", status="failed", total=None),
            _row(4, "2026-09-27T10:03:00", hl_counted=0),
            _row(5, "2026-09-27T10:04:00", wt=4, wc=3),
            _row(6, "2026-09-27T10:05:00", wt=None),
            _row(7, "2026-09-27T10:06:00", wt=0, wc=0),
            _row(8, "not-a-date"),
            _row(9, "2026-09-27T10:08:00")]
    out = ptc.build_chart(rows, [])
    assert out["excluded"] == {"not_usable": 3, "incomplete": 3, "unparseable": 1}
    assert [p["id"] for p in out["points"]] == [1, 9]


def test_t3_seams():
    one = [_row(1, "2026-09-27T10:00:00", v=1), _row(2, "2026-09-27T11:00:00", v=1)]
    assert ptc.build_chart(one, [])["seams"] == []
    two = one + [_row(3, "2026-09-27T12:00:00", v=2), _row(4, "2026-09-27T13:00:00", v=2)]
    assert ptc.build_chart(two, [])["seams"] == [{"t": "2026-09-27T12:00:00.000Z", "from_v": 1, "to_v": 2}]


def test_t4_timestamp_forms_to_utc_ms():
    forms = ["2026-09-27T18:58:12", "2026-09-27 18:58:12", "2026-09-27T18:58:12Z", "2026-09-27T18:58:12+00:00",
             "2026-09-27T11:58:12-07:00"]
    out = ptc.build_chart([_row(i, ts) for i, ts in enumerate(forms)], [])
    assert [p["t"] for p in out["points"]] == ["2026-09-27T18:58:12.000Z"] * 5


def test_t5_basis0_none_when_snapshot_total_missing():
    out = ptc.build_chart([_row(1, "2026-09-27T10:00:00", snap=None), _row(2, "2026-09-27T11:00:00", hl=None)], [])
    assert [p["basis0"] for p in out["points"]] == [None, None]
    assert [p["total"] for p in out["points"]] == [100.0, 100.0]


def test_t6_benchmarks():
    market = [{"timestamp": "2026-09-27T09:00:00", "btc_price": None, "eth_price": None},
              {"timestamp": "2026-09-27T10:00:00", "btc_price": 60000.0, "eth_price": None},
              {"timestamp": "2026-09-27 12:00:00", "btc_price": 61000.0, "eth_price": 2500.0},
              {"timestamp": "bad", "btc_price": 1.0, "eth_price": 1.0}]
    assert ptc.build_chart([], market)["benchmarks"] == [
        {"t": "2026-09-27T10:00:00.000Z", "btc": 60000.0, "eth": None},
        {"t": "2026-09-27T12:00:00.000Z", "btc": 61000.0, "eth": 2500.0}]


def test_t7_empty_inputs():
    assert ptc.build_chart([], []) == EMPTY


# ── route ──────────────────────────────────────────────────────────────────

def test_t8_route_empty_db(client, dbpath):
    r = client.get("/api/history/portfolio-total-chart")
    assert r.status_code == 200 and r.get_json() == EMPTY


def _seed(path):
    now = datetime.utcnow()
    old, recent = (now - timedelta(days=40)).isoformat(), (now - timedelta(days=2)).isoformat()
    newest = (now - timedelta(hours=1)).isoformat()
    for ts, v, total in ((old, 0, 90.0), (recent, 0, 95.0), (newest, 1, 110.0)):
        portfolio_db.insert_portfolio_total_snapshot({
            "timestamp": ts, "status": "completed", "definition_version": v, "total_usd": total,
            "snapshot_total_usd": total - 15.0, "hyperliquid_usd": 15.0, "hl_counted": 1,
            "wallets_total": 2, "wallets_completed": 2})
    for ts, btc in ((old, 50000.0), (recent, 60000.0)):
        portfolio_db.insert_market_snapshot({"timestamp": ts, "session": "test", "btc_price": btc, "eth_price": 2000.0})
    return old


def _counts(path):
    conn = sqlite3.connect(path)
    out = tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("portfolio_total_snapshots", "market_snapshots"))
    conn.close()
    return out


def test_t9_route_days_window(client, dbpath):
    _seed(dbpath)
    full = client.get("/api/history/portfolio-total-chart").get_json()
    assert [p["total"] for p in full["points"]] == [90.0, 95.0, 110.0]
    assert [b["btc"] for b in full["benchmarks"]] == [50000.0, 60000.0]
    assert full["seams"] == [{"t": full["points"][2]["t"], "from_v": 0, "to_v": 1}]
    month = client.get("/api/history/portfolio-total-chart?days=30").get_json()
    assert [p["total"] for p in month["points"]] == [95.0, 110.0]
    assert [b["btc"] for b in month["benchmarks"]] == [60000.0]
    assert client.get("/api/history/portfolio-total-chart?days=0").get_json() == full
    assert client.get("/api/history/portfolio-total-chart?days=abc").get_json() == full


def test_t10_route_is_read_only(client, dbpath):
    _seed(dbpath)
    before = _counts(dbpath)
    assert client.get("/api/history/portfolio-total-chart").status_code == 200
    assert _counts(dbpath) == before


def test_t11_route_unauthenticated_401(dbpath, monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    r = wp.app.test_client().get("/api/history/portfolio-total-chart")
    assert r.status_code == 401
