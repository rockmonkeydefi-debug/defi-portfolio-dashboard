"""Route tests for the P/L snapshot backend (pl_snapshots + pl_flows) -
commit 1 of 2, backend only, no frontend yet.

Covers: ensure_pl_tables idempotency, the server-computed LP book value
(SUM of open maxfi_positions' last_value_usd per wallet, LOWER()-joined so
config-casing never has to match position-row casing, NULL rows counted as
skipped and excluded from the sum, empty book -> 0.0 not NULL), snapshot
upsert-by-(snapshot_date, wallet) with created_at preserved and updated_at
bumped, all-or-nothing batch validation, the capital-flows ledger, and
GET /api/pl/data's combined {snapshots, flows} shape and ordering.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern in
the other MaxFi/route test files) so no thread starts.

get_connection() is called via a local `from src.storage.portfolio_db
import get_connection` INSIDE each route body, re-resolving the module
attribute on every call - so patching portfolio_db.get_connection itself
(not wp.get_connection, which doesn't exist as a module-level name here)
correctly intercepts every connection a route opens. A shared-cache sqlite
URI (unique per test, via uuid) is used rather than plain ":memory:"
because each route opens and closes its OWN connection per call - a fresh
anonymous ":memory:" db would lose all state the instant that connection
closed (same rationale as test_maxfi_valuation_route.py's iv_db fixture,
which this fixture mirrors).
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

import maxfi_schema
import src.storage.portfolio_db as portfolio_db

# Deliberately mixed casing between the wallet_config entry and the seeded
# maxfi_positions rows, to prove the LOWER() join - config stores the
# checksummed-looking form, positions were recorded all-lowercase.
WALLET_A_CONFIG = "0xAbCdEf0000000000000000000000000000000A"
WALLET_A_POSITIONS = WALLET_A_CONFIG.lower()
WALLET_B_CONFIG = "0x00000000000000000000000000000000000b0b"


@pytest.fixture
def db(monkeypatch):
    uri = f"file:pl_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    keepalive.row_factory = sqlite3.Row
    maxfi_schema.ensure_maxfi_tables(keepalive)

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    yield keepalive
    keepalive.close()


@pytest.fixture
def client(monkeypatch, tmp_path, db):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    monkeypatch.setattr(wp, "WALLET_CONFIG_FILE", str(tmp_path / "wallet_config.json"))
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _write_config(entries):
    wp.save_wallet_config(entries)


def _seed_position(db, wallet, last_value_usd, status='open', chain='base'):
    """Minimal maxfi_positions row - only the columns the LP book-value
    query and its WHERE clause touch matter for these tests."""
    db.execute(
        """
        INSERT INTO maxfi_positions (
            chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, first_seen_block,
            last_scan_at, closed_at, last_value_usd
        ) VALUES (?, ?, ?, 0, '0xPOOL', '0xT0', '0xT1', 3000, ?,
                  '2026-01-01T00:00:00+00:00', 'chain', '1',
                  '2026-01-01T00:00:00+00:00', NULL, ?)
        """,
        (chain, wallet, str(uuid.uuid4()), status, last_value_usd),
    )
    db.commit()


# ── ensure_pl_tables ─────────────────────────────────────────────────────

def test_ensure_pl_tables_idempotent(db):
    wp.ensure_pl_tables(db)
    wp.ensure_pl_tables(db)  # must not raise on rerun
    names = {
        r["name"] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "pl_snapshots" in names
    assert "pl_flows" in names


# ── POST /api/pl/snapshots: happy path + LP computation ─────────────────

def test_post_snapshots_happy_path_computes_lp_value_with_mixed_casing(client, db):
    _write_config({WALLET_A_CONFIG: {"label": "A"}})
    _seed_position(db, WALLET_A_POSITIONS, 100.0)
    _seed_position(db, WALLET_A_POSITIONS, 250.5)
    # NULL last_value_usd: excluded from the sum, counted as skipped.
    _seed_position(db, WALLET_A_POSITIONS, None)
    # Closed position: excluded entirely regardless of value.
    _seed_position(db, WALLET_A_POSITIONS, 9999.0, status='closed')

    r = client.post('/api/pl/snapshots', json={
        "snapshot_date": "2026-09-11",
        "entries": [{"wallet": WALLET_A_POSITIONS, "wallet_total_usd": 5000.0}],
    })
    assert r.status_code == 200
    rows = r.get_json()["snapshots"]
    assert len(rows) == 1
    row = rows[0]
    # Stored under the CONFIG casing, not the (differently-cased) input.
    assert row["wallet"] == WALLET_A_CONFIG
    assert row["wallet_total_usd"] == 5000.0
    assert row["lp_book_value_usd"] == pytest.approx(350.5)
    assert row["lp_skipped_positions"] == 1
    assert row["created_at"] is not None


def test_post_snapshots_empty_lp_book_stores_zero(client, db):
    _write_config({WALLET_A_CONFIG: {"label": "A"}})
    r = client.post('/api/pl/snapshots', json={
        "snapshot_date": "2026-09-11",
        "entries": [{"wallet": WALLET_A_CONFIG, "wallet_total_usd": 10.0}],
    })
    assert r.status_code == 200
    row = r.get_json()["snapshots"][0]
    assert row["lp_book_value_usd"] == 0.0
    assert row["lp_skipped_positions"] == 0


# ── POST /api/pl/snapshots: upsert ───────────────────────────────────────

def test_post_snapshots_upsert_same_date_wallet_updates_in_place(client, db):
    _write_config({WALLET_A_CONFIG: {"label": "A"}})
    _seed_position(db, WALLET_A_POSITIONS, 100.0)

    r1 = client.post('/api/pl/snapshots', json={
        "snapshot_date": "2026-09-11",
        "entries": [{"wallet": WALLET_A_CONFIG, "wallet_total_usd": 1000.0}],
    })
    first = r1.get_json()["snapshots"][0]

    _seed_position(db, WALLET_A_POSITIONS, 400.0)  # book value changes too
    r2 = client.post('/api/pl/snapshots', json={
        "snapshot_date": "2026-09-11",
        "entries": [{"wallet": WALLET_A_CONFIG, "wallet_total_usd": 2000.0}],
    })
    assert r2.status_code == 200
    second = r2.get_json()["snapshots"][0]

    assert second["id"] == first["id"]
    assert second["wallet_total_usd"] == 2000.0
    assert second["lp_book_value_usd"] == pytest.approx(500.0)
    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] is not None

    count = db.execute(
        "SELECT COUNT(*) AS c FROM pl_snapshots WHERE snapshot_date='2026-09-11' AND wallet=?",
        (WALLET_A_CONFIG,),
    ).fetchone()["c"]
    assert count == 1


# ── POST /api/pl/snapshots: validation ───────────────────────────────────

def test_post_snapshots_bad_date_rejected(client, db):
    _write_config({WALLET_A_CONFIG: {"label": "A"}})
    r = client.post('/api/pl/snapshots', json={
        "snapshot_date": "not-a-date",
        "entries": [{"wallet": WALLET_A_CONFIG, "wallet_total_usd": 1.0}],
    })
    assert r.status_code == 400


def test_post_snapshots_empty_entries_rejected(client, db):
    r = client.post('/api/pl/snapshots', json={
        "snapshot_date": "2026-09-11",
        "entries": [],
    })
    assert r.status_code == 400


def test_post_snapshots_non_finite_total_rejected(client, db):
    _write_config({WALLET_A_CONFIG: {"label": "A"}})
    r = client.post('/api/pl/snapshots', json={
        "snapshot_date": "2026-09-11",
        "entries": [{"wallet": WALLET_A_CONFIG, "wallet_total_usd": "not-a-number"}],
    })
    assert r.status_code == 400


def test_post_snapshots_negative_total_rejected(client, db):
    _write_config({WALLET_A_CONFIG: {"label": "A"}})
    r = client.post('/api/pl/snapshots', json={
        "snapshot_date": "2026-09-11",
        "entries": [{"wallet": WALLET_A_CONFIG, "wallet_total_usd": -1.0}],
    })
    assert r.status_code == 400


def test_post_snapshots_unknown_wallet_writes_nothing(client, db):
    _write_config({WALLET_A_CONFIG: {"label": "A"}})
    r = client.post('/api/pl/snapshots', json={
        "snapshot_date": "2026-09-11",
        "entries": [
            {"wallet": WALLET_A_CONFIG, "wallet_total_usd": 1000.0},
            {"wallet": "0xNotConfigured", "wallet_total_usd": 500.0},
        ],
    })
    assert r.status_code == 400

    data = client.get('/api/pl/data').get_json()
    assert data["snapshots"] == []


# ── DELETE /api/pl/snapshots ─────────────────────────────────────────────

def test_delete_snapshots_by_date_removes_only_that_date(client, db):
    _write_config({WALLET_A_CONFIG: {"label": "A"}})
    client.post('/api/pl/snapshots', json={
        "snapshot_date": "2026-09-04",
        "entries": [{"wallet": WALLET_A_CONFIG, "wallet_total_usd": 1.0}],
    })
    client.post('/api/pl/snapshots', json={
        "snapshot_date": "2026-09-11",
        "entries": [{"wallet": WALLET_A_CONFIG, "wallet_total_usd": 2.0}],
    })

    r = client.delete('/api/pl/snapshots?date=2026-09-04')
    assert r.status_code == 200
    assert r.get_json()["deleted"] == 1

    remaining = client.get('/api/pl/data').get_json()["snapshots"]
    assert len(remaining) == 1
    assert remaining[0]["snapshot_date"] == "2026-09-11"


# ── POST /api/pl/flows ────────────────────────────────────────────────────

def test_post_flows_happy_path_positive_and_negative(client, db):
    _write_config({WALLET_A_CONFIG: {"label": "A"}})
    r_in = client.post('/api/pl/flows', json={
        "flow_date": "2026-09-11", "amount_usd": 500.0, "wallet": WALLET_A_CONFIG, "note": "deposit",
    })
    assert r_in.status_code == 200
    assert r_in.get_json()["amount_usd"] == 500.0
    assert r_in.get_json()["wallet"] == WALLET_A_CONFIG

    r_out = client.post('/api/pl/flows', json={
        "flow_date": "2026-09-11", "amount_usd": -200.0,
    })
    assert r_out.status_code == 200
    assert r_out.get_json()["amount_usd"] == -200.0


def test_post_flows_zero_amount_rejected(client, db):
    r = client.post('/api/pl/flows', json={"flow_date": "2026-09-11", "amount_usd": 0})
    assert r.status_code == 400


def test_post_flows_unknown_wallet_rejected(client, db):
    r = client.post('/api/pl/flows', json={
        "flow_date": "2026-09-11", "amount_usd": 100.0, "wallet": "0xNotConfigured",
    })
    assert r.status_code == 400


def test_post_flows_omitted_wallet_stores_null(client, db):
    r = client.post('/api/pl/flows', json={"flow_date": "2026-09-11", "amount_usd": 100.0})
    assert r.status_code == 200
    assert r.get_json()["wallet"] is None


# ── DELETE /api/pl/flows/<id> ─────────────────────────────────────────────

def test_delete_flows_existing_id_removed(client, db):
    created = client.post('/api/pl/flows', json={
        "flow_date": "2026-09-11", "amount_usd": 100.0,
    }).get_json()
    flow_id = created["id"]

    r = client.delete(f'/api/pl/flows/{flow_id}')
    assert r.status_code == 200
    assert r.get_json()["deleted"] == flow_id

    remaining = client.get('/api/pl/data').get_json()["flows"]
    assert remaining == []


def test_delete_flows_missing_id_404(client, db):
    r = client.delete('/api/pl/flows/999999')
    assert r.status_code == 404


# ── GET /api/pl/data ──────────────────────────────────────────────────────

def test_get_pl_data_returns_both_arrays_in_order(client, db):
    _write_config({WALLET_A_CONFIG: {"label": "A"}, WALLET_B_CONFIG: {"label": "B"}})
    client.post('/api/pl/snapshots', json={
        "snapshot_date": "2026-09-11",
        "entries": [
            {"wallet": WALLET_B_CONFIG, "wallet_total_usd": 2.0},
            {"wallet": WALLET_A_CONFIG, "wallet_total_usd": 1.0},
        ],
    })
    client.post('/api/pl/snapshots', json={
        "snapshot_date": "2026-09-04",
        "entries": [{"wallet": WALLET_A_CONFIG, "wallet_total_usd": 0.5}],
    })
    client.post('/api/pl/flows', json={"flow_date": "2026-09-11", "amount_usd": 10.0})
    client.post('/api/pl/flows', json={"flow_date": "2026-09-04", "amount_usd": -5.0})

    data = client.get('/api/pl/data').get_json()
    snap_dates_wallets = [(s["snapshot_date"], s["wallet"]) for s in data["snapshots"]]
    # wallet ASC is a plain string sort: "0x00..." (WALLET_B) precedes
    # "0xAbCd..." (WALLET_A) because '0' < 'A' in ASCII.
    assert snap_dates_wallets == [
        ("2026-09-04", WALLET_A_CONFIG),
        ("2026-09-11", WALLET_B_CONFIG),
        ("2026-09-11", WALLET_A_CONFIG),
    ]
    flow_dates = [f["flow_date"] for f in data["flows"]]
    assert flow_dates == ["2026-09-04", "2026-09-11"]
