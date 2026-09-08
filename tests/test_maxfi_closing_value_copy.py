"""Tests for MaxFi closing-value capture (commit 3 of 4): close-path
auto-copy of last_value_usd into maxfi_position_user_data.closing_value_usd
('auto_last_observed'), /user-data's 'manual' stamping, and the positions
route's three additive payload keys.

Two harness styles, matching the two kinds of write path under test:
  - Scan-driven (maxfi_orchestration.run_scan_and_persist): plain in-memory
    sqlite3 + monkeypatched get_wallet_position_snapshot/
    get_vault_deposit_info/eth_block_number, same style as
    tests/test_maxfi_orchestration.py.
  - Route-driven (web_portfolio.py's manual close / /user-data / positions
    routes): the iv_db/client fixture pair from
    tests/test_maxfi_valuation_route.py - a shared-cache sqlite URI with
    portfolio_db.get_connection monkeypatched, since each route opens and
    closes its OWN connection per call.
"""
import sqlite3
import threading
import uuid

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import pytest

import maxfi_orchestration as orch
import maxfi_schema
import src.storage.portfolio_db as portfolio_db

CHAIN = "base"
WALLET = "0xWALLET"


# ── Scan-driven harness (mirrors tests/test_maxfi_orchestration.py) ────────

def make_scan_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    maxfi_schema.ensure_maxfi_tables(conn)
    return conn


def pos(idx, token_id, pool="0xPOOL_0", token0="0xTOKEN_A", token1="0xTOKEN_B", fee=3000):
    return {
        "array_index": idx,
        "token_id": token_id,
        "pool_address": pool,
        "token0_address": token0,
        "token1_address": token1,
        "fee_tier": fee,
    }


def _patch_snapshot(monkeypatch, snapshot):
    monkeypatch.setattr(orch, "get_wallet_position_snapshot", lambda chain, wallet: snapshot)


def _patch_block_number(monkeypatch, n=1000):
    monkeypatch.setattr(orch, "eth_block_number", lambda chain: n)


def _patch_enrichment_success(monkeypatch, deposit_timestamp=1700000000, block_number="999"):
    monkeypatch.setattr(
        orch, "get_vault_deposit_info",
        lambda chain, wallet, token_id: {
            "deposit_timestamp": deposit_timestamp,
            "total_rebalances": 0,
            "block_number": block_number,
        },
    )


def _seed_scan(monkeypatch, conn, snapshot, chain=CHAIN, wallet=WALLET):
    _patch_snapshot(monkeypatch, snapshot)
    _patch_block_number(monkeypatch, 1000)
    _patch_enrichment_success(monkeypatch)
    return orch.run_scan_and_persist(conn, chain, wallet)


def _row_id_for_token(conn, token_id):
    return conn.execute("SELECT id FROM maxfi_positions WHERE token_id = ?", (token_id,)).fetchone()[0]


def _user_data_row(conn, position_id):
    return conn.execute(
        "SELECT closing_value_usd, closing_value_source, user_note, set_by "
        "FROM maxfi_position_user_data WHERE position_id = ?",
        (position_id,),
    ).fetchone()


# ── (a) scan close copies last_value_usd ────────────────────────────────

def test_scan_close_copies_last_value(monkeypatch):
    conn = make_scan_db()
    _seed_scan(monkeypatch, conn, [pos(0, "100"), pos(1, "101")])
    conn.execute("UPDATE maxfi_positions SET last_value_usd = 555.5 WHERE token_id = '101'")
    conn.commit()

    _patch_snapshot(monkeypatch, [pos(0, "100")])
    result = orch.run_scan_and_persist(conn, CHAIN, WALLET)
    assert result["written"]["closed"] == 1

    row_id = _row_id_for_token(conn, "101")
    ud = _user_data_row(conn, row_id)
    assert ud is not None
    assert ud[0] == 555.5
    assert ud[1] == "auto_last_observed"
    assert ud[3] == "system"


# ── (b) NULL last_value_usd creates no row ──────────────────────────────

def test_scan_close_with_null_last_value_creates_no_row(monkeypatch):
    conn = make_scan_db()
    _seed_scan(monkeypatch, conn, [pos(0, "100"), pos(1, "101")])
    # last_value_usd left NULL (default).

    _patch_snapshot(monkeypatch, [pos(0, "100")])
    orch.run_scan_and_persist(conn, CHAIN, WALLET)

    row_id = _row_id_for_token(conn, "101")
    assert _user_data_row(conn, row_id) is None


# ── (c) existing closing value never clobbered ──────────────────────────

def test_scan_close_never_clobbers_existing_closing_value(monkeypatch):
    conn = make_scan_db()
    _seed_scan(monkeypatch, conn, [pos(0, "100"), pos(1, "101")])
    conn.execute("UPDATE maxfi_positions SET last_value_usd = 42.0 WHERE token_id = '101'")
    row_id = _row_id_for_token(conn, "101")
    conn.execute(
        "INSERT INTO maxfi_position_user_data (position_id, closing_value_usd, closing_value_source, set_at, set_by) "
        "VALUES (?, 999.0, 'manual', '2026-01-01T00:00:00+00:00', 'glenn')",
        (row_id,),
    )
    conn.commit()

    _patch_snapshot(monkeypatch, [pos(0, "100")])
    orch.run_scan_and_persist(conn, CHAIN, WALLET)

    ud = _user_data_row(conn, row_id)
    assert ud[0] == 999.0
    assert ud[1] == "manual"


# ── (d) fills value, preserves note ─────────────────────────────────────

def test_scan_close_fills_value_but_preserves_note(monkeypatch):
    conn = make_scan_db()
    _seed_scan(monkeypatch, conn, [pos(0, "100"), pos(1, "101")])
    conn.execute("UPDATE maxfi_positions SET last_value_usd = 77.7 WHERE token_id = '101'")
    row_id = _row_id_for_token(conn, "101")
    conn.execute(
        "INSERT INTO maxfi_position_user_data (position_id, closing_value_usd, user_note, set_at, set_by) "
        "VALUES (?, NULL, 'keep me', '2026-01-01T00:00:00+00:00', 'glenn')",
        (row_id,),
    )
    conn.commit()

    _patch_snapshot(monkeypatch, [pos(0, "100")])
    orch.run_scan_and_persist(conn, CHAIN, WALLET)

    ud = _user_data_row(conn, row_id)
    assert ud[0] == 77.7
    assert ud[1] == "auto_last_observed"
    assert ud[2] == "keep me"


# ── Route-driven harness (mirrors tests/test_maxfi_valuation_route.py) ─────

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


@pytest.fixture
def iv_db(monkeypatch):
    uri = f"file:maxfi_cvcopy_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    keepalive.row_factory = sqlite3.Row
    maxfi_schema.ensure_maxfi_tables(keepalive)

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    yield keepalive
    keepalive.close()


def _seed_position(db, position_id, status="open", last_value_usd=None, last_value_at=None,
                    chain=CHAIN, wallet=WALLET):
    db.execute(
        """
        INSERT INTO maxfi_positions (
            id, chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, first_seen_block,
            last_scan_at, closed_at, last_value_usd, last_value_at
        ) VALUES (?, ?, ?, ?, 0, '0xPOOL', '0xT0', '0xT1', 3000, ?,
                  '2026-01-01T00:00:00+00:00', 'chain', '1',
                  '2026-01-01T00:00:00+00:00', NULL, ?, ?)
        """,
        (position_id, chain, wallet, str(position_id), status, last_value_usd, last_value_at),
    )
    db.commit()


def _seed_user_data(db, position_id, closing_value_usd=None, closing_value_source=None,
                     user_note=None, set_at="2026-01-01T00:00:00+00:00", set_by="glenn"):
    db.execute(
        "INSERT INTO maxfi_position_user_data "
        "(position_id, closing_value_usd, closing_value_source, user_note, set_at, set_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (position_id, closing_value_usd, closing_value_source, user_note, set_at, set_by),
    )
    db.commit()


def _user_data_row_client(db, position_id):
    return db.execute(
        "SELECT closing_value_usd, closing_value_source, user_note "
        "FROM maxfi_position_user_data WHERE position_id = ?",
        (position_id,),
    ).fetchone()


# ── (e) manual close copies last_value_usd ──────────────────────────────

def test_manual_close_copies_last_value(client, iv_db):
    _seed_position(iv_db, 200, last_value_usd=321.0)

    r = client.post("/api/maxfi/positions/200/close")
    assert r.status_code == 200

    ud = _user_data_row_client(iv_db, 200)
    assert ud["closing_value_usd"] == 321.0
    assert ud["closing_value_source"] == "auto_last_observed"


# ── (f) repeat close is idempotent, copy not re-run ─────────────────────

def test_manual_close_repeat_is_idempotent(client, iv_db):
    _seed_position(iv_db, 201, last_value_usd=100.0)

    r1 = client.post("/api/maxfi/positions/201/close")
    assert r1.status_code == 200
    body1 = r1.get_json()
    ud1 = _user_data_row_client(iv_db, 201)

    r2 = client.post("/api/maxfi/positions/201/close")
    assert r2.status_code == 200
    body2 = r2.get_json()

    assert body2["already_closed"] is True
    assert body2["closed_at"] == body1["closed_at"]

    ud2 = _user_data_row_client(iv_db, 201)
    assert ud2["closing_value_usd"] == ud1["closing_value_usd"] == 100.0
    assert ud2["closing_value_source"] == ud1["closing_value_source"] == "auto_last_observed"


# ── (g) manual close with NULL last_value_usd creates no row ────────────

def test_manual_close_with_null_last_value_creates_no_row(client, iv_db):
    _seed_position(iv_db, 202)  # last_value_usd left NULL

    r = client.post("/api/maxfi/positions/202/close")
    assert r.status_code == 200

    assert _user_data_row_client(iv_db, 202) is None


# ── (h) /user-data value save stamps 'manual' ───────────────────────────

def test_user_data_value_save_stamps_manual(client, iv_db):
    _seed_position(iv_db, 203)
    _seed_user_data(iv_db, 203, closing_value_usd=50.0, closing_value_source="auto_last_observed")

    r = client.post("/api/maxfi/positions/203/user-data", json={"closing_value_usd": 75.0})
    assert r.status_code == 200
    body = r.get_json()
    assert body["closing_value_usd"] == 75.0
    assert body["closing_value_source"] == "manual"

    row = _user_data_row_client(iv_db, 203)
    assert row["closing_value_usd"] == 75.0
    assert row["closing_value_source"] == "manual"


# ── (i) note-only save preserves source ─────────────────────────────────

def test_user_data_note_only_save_preserves_source(client, iv_db):
    _seed_position(iv_db, 204)
    _seed_user_data(iv_db, 204, closing_value_usd=50.0, closing_value_source="auto_last_observed")

    r = client.post("/api/maxfi/positions/204/user-data", json={"user_note": "a note"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["user_note"] == "a note"
    assert body["closing_value_usd"] == 50.0
    assert body["closing_value_source"] == "auto_last_observed"

    row = _user_data_row_client(iv_db, 204)
    assert row["closing_value_usd"] == 50.0
    assert row["closing_value_source"] == "auto_last_observed"
    assert row["user_note"] == "a note"


# ── (j) explicit null clears value AND source ───────────────────────────

def test_user_data_explicit_null_clears_value_and_source(client, iv_db):
    _seed_position(iv_db, 205)
    _seed_user_data(iv_db, 205, closing_value_usd=50.0, closing_value_source="auto_last_observed")

    r = client.post("/api/maxfi/positions/205/user-data", json={"closing_value_usd": None})
    assert r.status_code == 200
    body = r.get_json()
    assert body["closing_value_usd"] is None
    assert body["closing_value_source"] is None

    row = _user_data_row_client(iv_db, 205)
    assert row["closing_value_usd"] is None
    assert row["closing_value_source"] is None


# ── (k) positions payload carries the three new keys ────────────────────

def test_positions_payload_carries_new_keys(client, iv_db):
    ts = "2026-03-01T00:00:00+00:00"
    _seed_position(iv_db, 206, status="closed", last_value_usd=88.8, last_value_at=ts)
    _seed_user_data(iv_db, 206, closing_value_usd=88.8, closing_value_source="auto_last_observed")

    r = client.get(f"/api/maxfi/positions/{CHAIN}/{WALLET}")
    assert r.status_code == 200
    row = next(p for p in r.get_json() if p["id"] == 206)
    assert row["closing_value_source"] == "auto_last_observed"
    assert row["last_value_usd"] == 88.8
    assert row["last_value_at"] == ts
