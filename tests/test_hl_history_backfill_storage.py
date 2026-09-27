"""Storage for the Hyperliquid history backfill: the hl_history_captures table,
the single-transaction backfill writer and its readers
(src/storage/portfolio_db.py).

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). Synthetic values only."""
import sqlite3

import pytest

import src.storage.portfolio_db as portfolio_db

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


def _all(path, sql, params=()):
    conn = _open(path)
    rows = [dict(r) for r in conn.execute(sql, params)]
    conn.close()
    return rows


def _capture(capture_id="cap1", wallet=A, request_type="portfolio", n=0):
    return {"capture_id": capture_id, "captured_at": "2026-09-01T00:00:00+00:00", "wallet": wallet,
            "request_type": request_type, "request_json": '{"n": %d}' % n, "response_json": "[]"}


def _v0(ts, total=100.0, status="completed"):
    return {"timestamp": ts, "status": status, "definition_version": 0, "total_usd": total,
            "snapshot_total_usd": total - 10.0, "hyperliquid_usd": 10.0, "hl_counted": 1,
            "wallets_total": 2, "wallets_completed": 2, "detail_json": "{}"}


def _v1(ts, total=500.0):
    return {"timestamp": ts, "status": "completed", "definition_version": 1, "total_usd": total,
            "snapshot_total_usd": 400.0, "hyperliquid_usd": 90.0, "maxfi_uncollected_usd": 10.0, "hl_counted": 1,
            "wallets_total": 2, "wallets_completed": 2, "detail_json": '{"status": "ok"}'}


def test_captures_table_columns_index_and_idempotent_init(dbpath):
    portfolio_db.init_db()                                                   # second run raises nothing
    conn = _open(dbpath)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(hl_history_captures)")]
    idx = [r["name"] for r in conn.execute("PRAGMA index_list(hl_history_captures)")]
    conn.close()
    assert cols == ["id"] + list(portfolio_db.HL_HISTORY_CAPTURE_COLUMNS)
    assert "idx_hl_history_captures_capture" in idx


def test_write_then_rewrite_replaces_only_v0_rows(dbpath):
    v1_id = portfolio_db.insert_portfolio_total_snapshot(_v1("2026-09-10T00:00:00"))
    v1_before = _all(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE id=?", (v1_id,))
    res = portfolio_db.write_hl_history_backfill(
        [_capture(n=0), _capture(request_type="ledger", n=1)],
        [_v0("2026-06-01T00:00:00"), _v0("2026-06-02T00:00:00"), _v0("2026-06-03T00:00:00")])
    assert res == {"captures_written": 2, "v0_deleted": 0, "rows_written": 3}
    assert len(_all(dbpath, "SELECT * FROM hl_history_captures")) == 2
    v0 = _all(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE definition_version=0 ORDER BY id")
    assert [r["timestamp"] for r in v0] == ["2026-06-01T00:00:00", "2026-06-02T00:00:00", "2026-06-03T00:00:00"]
    assert v0[0]["maxfi_uncollected_usd"] is None and v0[0]["user_id"] == 1

    res = portfolio_db.write_hl_history_backfill([_capture("cap2")], [_v0("2026-06-05T00:00:00", total=7.0)])
    assert res == {"captures_written": 1, "v0_deleted": 3, "rows_written": 1}
    v0 = _all(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE definition_version=0")
    assert [(r["timestamp"], r["total_usd"]) for r in v0] == [("2026-06-05T00:00:00", 7.0)]
    assert _all(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE id=?", (v1_id,)) == v1_before
    assert len(_all(dbpath, "SELECT * FROM hl_history_captures")) == 3


def test_failure_mid_write_rolls_everything_back(dbpath):
    v1_id = portfolio_db.insert_portfolio_total_snapshot(_v1("2026-09-10T00:00:00"))
    v1_before = _all(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE id=?", (v1_id,))
    portfolio_db.write_hl_history_backfill([_capture()], [_v0("2026-06-01T00:00:00")])
    with pytest.raises(sqlite3.IntegrityError):
        portfolio_db.write_hl_history_backfill(
            [_capture("cap2"), _capture("cap2", request_type="ledger")],
            [_v0("2026-06-02T00:00:00"), _v0("2026-06-03T00:00:00", status=None)])    # status is NOT NULL
    assert [r["capture_id"] for r in _all(dbpath, "SELECT * FROM hl_history_captures")] == ["cap1"]
    assert [r["timestamp"] for r in _all(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE definition_version=0")] == [
        "2026-06-01T00:00:00"]                                              # the old v0 row survives the rollback
    assert _all(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE id=?", (v1_id,)) == v1_before


def test_failure_on_first_write_leaves_nothing(dbpath):
    v1_id = portfolio_db.insert_portfolio_total_snapshot(_v1("2026-09-10T00:00:00"))
    v1_before = _all(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE id=?", (v1_id,))
    with pytest.raises(sqlite3.IntegrityError):
        portfolio_db.write_hl_history_backfill([_capture()], [_v0("2026-06-02T00:00:00"), _v0("2026-06-03T00:00:00", status=None)])
    assert _all(dbpath, "SELECT * FROM hl_history_captures") == []
    assert _all(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE definition_version=0") == []
    assert _all(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE id=?", (v1_id,)) == v1_before


def test_get_hl_history_capture(dbpath):
    portfolio_db.write_hl_history_backfill(
        [_capture(n=0), _capture("other", n=9), _capture(request_type="ledger", n=1), _capture(wallet=B, n=2)], [])
    rows = portfolio_db.get_hl_history_capture("cap1")
    assert [r["request_json"] for r in rows] == ['{"n": 0}', '{"n": 1}', '{"n": 2}']
    assert [r["id"] for r in rows] == sorted(r["id"] for r in rows)
    assert set(rows[0]) == {"id"} | set(portfolio_db.HL_HISTORY_CAPTURE_COLUMNS)
    assert portfolio_db.get_hl_history_capture("nope") == []


def test_get_first_measured_total_row(dbpath):
    assert portfolio_db.get_first_measured_total_row() is None
    portfolio_db.write_hl_history_backfill([], [_v0("2026-01-01T00:00:00")])
    assert portfolio_db.get_first_measured_total_row() is None                # v0 rows are ignored
    later = portfolio_db.insert_portfolio_total_snapshot(_v1("2026-09-12T00:00:00"))
    earlier = portfolio_db.insert_portfolio_total_snapshot(dict(_v1("2026-09-11T00:00:00"), status="failed", total_usd=None))
    first = portfolio_db.get_first_measured_total_row()
    assert first["id"] == earlier and first["status"] == "failed" and later != earlier


def test_get_snapshot_runs_before(dbpath):
    conn = _open(dbpath)
    for ts, wallet, status, total in [
            ("2026-06-02T00:00:00", A, "completed", 10.0), ("2026-06-01T00:00:00", A, "completed", 1.0),
            ("2026-06-01T00:00:00", B, "failed", 0.0), ("2026-06-01T00:00:00.5", A, "partial", 2.0),
            ("2026-06-03T00:00:00", A, "completed", 99.0), ("2026-06-04T00:00:00", A, "completed", 5.0)]:
        conn.execute("INSERT INTO portfolio_snapshots (user_id, timestamp, wallet, status, total_value_usd) VALUES (1,?,?,?,?)",
                     (ts, wallet, status, total))
    conn.commit()
    conn.close()
    runs = portfolio_db.get_snapshot_runs_before("2026-06-03T00:00:00")
    assert runs == [
        {"timestamp": "2026-06-01T00:00:00", "rows": [{"wallet": A, "status": "completed", "total_value_usd": 1.0},
                                                      {"wallet": B, "status": "failed", "total_value_usd": 0.0}]},
        {"timestamp": "2026-06-01T00:00:00.5", "rows": [{"wallet": A, "status": "partial", "total_value_usd": 2.0}]},
        {"timestamp": "2026-06-02T00:00:00", "rows": [{"wallet": A, "status": "completed", "total_value_usd": 10.0}]},
    ]
    assert portfolio_db.get_snapshot_runs_before("2026-01-01T00:00:00") == []
