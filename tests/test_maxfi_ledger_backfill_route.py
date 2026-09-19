"""Route-level tests for POST /api/maxfi/ledger/backfill/<chain>
(HANDOFF_maxfi_ledger.md, MaxFi ledger Commit 3b.1).

No network - every maxfi_ledger_ingest call the route makes goes through
its single entry point, maxfi_ledger_ingest.scan_chain(), which is
monkeypatched wholesale in every test below (same boundary
tests/test_maxfi_catalogue_refresh.py uses against maxfi_client's
functions). Wallet enumeration (wp._maxfi_tracked_wallets) is monkeypatched
too, so no real wallet_config.json is read.

No network. web_portfolio spawns a background scheduler on non-__main__
import; threading.Thread.start is neutralized during import (established
pattern - see tests/test_maxfi_ledger_reconciliation.py).
"""
import json
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

import maxfi_ledger as ml
import maxfi_ledger_ingest as mli
import maxfi_schema
import src.storage.portfolio_db as portfolio_db

BACKFILL_URL = "/api/maxfi/ledger/backfill/base"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


@pytest.fixture
def db(monkeypatch):
    uri = f"file:maxfi_ledger_backfill_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
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


@pytest.fixture(autouse=True)
def _wallets(monkeypatch):
    monkeypatch.setattr(wp, "_maxfi_tracked_wallets", lambda: ["0xaB7A515c6e2Eea5140eD8A5b09A7D782F3B26743"])


# ── raw log builders (Etherscan shape) - mirrors
# tests/test_maxfi_ledger_ingest.py's own builders, kept separate since
# this file's fixtures don't need to share state with that module. ──────

_VAULT = mli.CHAINS["base"]["vault"]
_WALLET = "0xaB7A515c6e2Eea5140eD8A5b09A7D782F3B26743"


def _word(value):
    return format(value, "064x")


def _make_log(address, topics, data_words, block_number, tx_hash, log_index=0):
    return {
        "address": address,
        "blockNumber": hex(block_number),
        "timeStamp": hex(1700000000 + block_number),
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
        "topics": topics,
        "data": "0x" + "".join(_word(w) for w in data_words),
    }


def _position_created_log(token_id, owner=_WALLET, pool_id=None, block_number=100,
                           tx_hash="0x" + "aa" * 32, log_index=0):
    if pool_id is None:
        pool_id = "0x" + "11" * 32
    topics = [
        ml.TOPIC_POSITION_CREATED,
        mli.encode_topic_uint256(token_id),
        mli.encode_topic_address(owner),
        pool_id,
    ]
    return _make_log(_VAULT, topics, [100, 200, 5000, 0], block_number, tx_hash, log_index)


def _empty_scan(**overrides):
    scan = {
        "raw_logs": [],
        "wallets_scanned": [_WALLET],
        "token_ids": [],
        "npm_resolutions": [],
        "event_type_counts": {},
        "chunk_stats": {
            "pass1_vault": {"calls": 1, "chunk_halvings": 0, "retries_429": 0, "final_chunk_size": mli.DEFAULT_CHUNK_SIZE},
            "pass1_snuggle_rebalanced": {"calls": 1, "chunk_halvings": 0, "retries_429": 0, "final_chunk_size": mli.DEFAULT_CHUNK_SIZE},
            "pool_added": {"calls": 1, "chunk_halvings": 0, "retries_429": 0, "final_chunk_size": mli.DEFAULT_CHUNK_SIZE},
            "pass2_staking_manager": {"calls": 0, "chunk_halvings": 0, "retries_429": 0, "final_chunk_size": None},
            "pass3_npm": {},
        },
    }
    scan.update(overrides)
    return scan


# ── InvalidChain ──────────────────────────────────────────────────────────

def test_invalid_chain_returns_400(client, db):
    r = client.post("/api/maxfi/ledger/backfill/not-a-real-chain")
    assert r.status_code == 400
    body = r.get_json()
    assert body["error"] == "InvalidChain"
    assert "valid_chains" in body


# ── real run: insert + derive + upsert ───────────────────────────────────

def test_real_run_inserts_event_and_upserts_position(client, db, monkeypatch):
    pc_log = _position_created_log(6039568)
    scan = _empty_scan(
        raw_logs=[pc_log],
        token_ids=["6039568"],
        event_type_counts={"PositionCreated": 1},
    )
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)

    r = client.post(BACKFILL_URL)
    assert r.status_code == 200
    body = r.get_json()

    assert body["chain"] == "base"
    assert body["wallets_scanned"] == [_WALLET]
    assert body["dry_run"] is False
    assert body["fetched"] == {"PositionCreated": 1}
    assert body["inserted"] == {"PositionCreated": 1}
    assert body["ignored_duplicate"] == {}
    assert body["positions_upserted"] == 1
    assert body["unverified_event_types"] == {"FeesCompounded": 0, "FeesHarvestedDirect": 0}
    assert "unverified_event_types_note" not in body

    event_rows = db.execute("SELECT * FROM maxfi_ledger_events WHERE chain = 'base'").fetchall()
    assert len(event_rows) == 1
    assert event_rows[0]["event_type"] == "PositionCreated"
    assert event_rows[0]["token_id"] == "6039568"

    position_rows = db.execute("SELECT * FROM maxfi_ledger_positions WHERE chain = 'base'").fetchall()
    assert len(position_rows) == 1
    assert position_rows[0]["token_id"] == "6039568"
    assert position_rows[0]["vault"] == _VAULT
    assert position_rows[0]["npm"] is None
    assert position_rows[0]["computed_at"] == body["run_at"]


# ── idempotent re-run via the UNIQUE INDEX ───────────────────────────────

def test_rerun_is_idempotent_and_reports_duplicates(client, db, monkeypatch):
    pc_log = _position_created_log(6039568)
    scan = _empty_scan(
        raw_logs=[pc_log],
        token_ids=["6039568"],
        event_type_counts={"PositionCreated": 1},
    )
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)

    r1 = client.post(BACKFILL_URL)
    assert r1.status_code == 200
    assert r1.get_json()["inserted"] == {"PositionCreated": 1}

    r2 = client.post(BACKFILL_URL)
    assert r2.status_code == 200
    body2 = r2.get_json()
    assert body2["inserted"] == {}
    assert body2["ignored_duplicate"] == {"PositionCreated": 1}

    event_rows = db.execute("SELECT * FROM maxfi_ledger_events WHERE chain = 'base'").fetchall()
    assert len(event_rows) == 1  # UNIQUE INDEX (chain, tx_hash, log_index) - no duplicate row

    position_rows = db.execute("SELECT * FROM maxfi_ledger_positions WHERE chain = 'base'").fetchall()
    assert len(position_rows) == 1  # UPSERT, not a second row
    assert position_rows[0]["computed_at"] == body2["run_at"]  # re-derived, computed_at refreshed


# ── dry_run: zero writes, accurate classification ────────────────────────

def test_dry_run_writes_nothing_and_classifies_correctly(client, db, monkeypatch):
    pc_log = _position_created_log(6039568)
    scan = _empty_scan(
        raw_logs=[pc_log],
        token_ids=["6039568"],
        event_type_counts={"PositionCreated": 1},
    )
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)

    r = client.post(f"{BACKFILL_URL}?dry_run=true")
    assert r.status_code == 200
    body = r.get_json()

    assert body["dry_run"] is True
    assert body["inserted"] == {"PositionCreated": 1}
    assert body["ignored_duplicate"] == {}
    assert body["positions_upserted"] == 1

    assert db.execute("SELECT COUNT(*) c FROM maxfi_ledger_events").fetchone()["c"] == 0
    assert db.execute("SELECT COUNT(*) c FROM maxfi_ledger_positions").fetchone()["c"] == 0


def test_dry_run_classifies_pre_existing_rows_as_duplicate(client, db, monkeypatch):
    pc_log = _position_created_log(6039568)
    scan = _empty_scan(
        raw_logs=[pc_log],
        token_ids=["6039568"],
        event_type_counts={"PositionCreated": 1},
    )
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)

    r1 = client.post(BACKFILL_URL)
    assert r1.status_code == 200

    r2 = client.post(f"{BACKFILL_URL}?dry_run=true")
    body2 = r2.get_json()
    assert body2["inserted"] == {}
    assert body2["ignored_duplicate"] == {"PositionCreated": 1}
    # Still just the one real row from the first (non-dry) run.
    assert db.execute("SELECT COUNT(*) c FROM maxfi_ledger_events").fetchone()["c"] == 1


def test_dry_run_string_one_is_treated_as_a_real_run(client, db, monkeypatch):
    # Pins the exact-'true' convention (8eb2458 defect class) - shared
    # across every MaxFi refresh route in this file.
    pc_log = _position_created_log(6039568)
    scan = _empty_scan(raw_logs=[pc_log], token_ids=["6039568"], event_type_counts={"PositionCreated": 1})
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)

    r = client.post(f"{BACKFILL_URL}?dry_run=1")
    assert r.status_code == 200
    body = r.get_json()
    assert body["dry_run"] is False
    assert db.execute("SELECT COUNT(*) c FROM maxfi_ledger_events").fetchone()["c"] == 1


# ── unverified_event_types (ruling: flag, don't block) ───────────────────

def test_unverified_event_types_reported_with_note(client, db, monkeypatch):
    scan = _empty_scan(
        raw_logs=[],
        event_type_counts={"FeesCompounded": 2, "FeesHarvestedDirect": 1},
    )
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)

    r = client.post(BACKFILL_URL)
    assert r.status_code == 200
    body = r.get_json()

    assert body["unverified_event_types"] == {"FeesCompounded": 2, "FeesHarvestedDirect": 1}
    assert "unverified_event_types_note" in body
    assert "Blockscout" in body["unverified_event_types_note"]


def test_no_unverified_events_omits_note(client, db, monkeypatch):
    scan = _empty_scan(raw_logs=[], event_type_counts={})
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)

    r = client.post(BACKFILL_URL)
    body = r.get_json()
    assert body["unverified_event_types"] == {"FeesCompounded": 0, "FeesHarvestedDirect": 0}
    assert "unverified_event_types_note" not in body


# ── npm_resolutions pass-through ─────────────────────────────────────────

def test_npm_resolutions_passed_through_in_response(client, db, monkeypatch):
    scan = _empty_scan(
        raw_logs=[],
        npm_resolutions=[{"pool_id": "0x" + "11" * 32, "npm_address": "0x" + "33" * 20}],
    )
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)

    r = client.post(BACKFILL_URL)
    body = r.get_json()
    assert body["npm_resolutions"] == [{"pool_id": "0x" + "11" * 32, "npm_address": "0x" + "33" * 20}]


# ── MaxFiLedgerIngestError -> 502 ─────────────────────────────────────────

def test_ingest_error_returns_502(client, db, monkeypatch):
    def _boom(chain, wallets):
        raise mli.MaxFiRpcError("[base] no RPC URL configured (env var BASE_RPC_URL unset)")
    monkeypatch.setattr(mli, "scan_chain", _boom)

    r = client.post(BACKFILL_URL)
    assert r.status_code == 502
    body = r.get_json()
    assert body["error"] == "MaxFiLedgerIngestError"
    assert "BASE_RPC_URL" in body["detail"]

    # No partial writes on a failure that happens entirely within the RPC
    # phase, before the DB connection ever opens.
    assert db.execute("SELECT COUNT(*) c FROM maxfi_ledger_events").fetchone()["c"] == 0


# ── busy lock ─────────────────────────────────────────────────────────────

def test_concurrent_call_returns_409_busy(client, db):
    assert wp._LEDGER_BACKFILL_LOCK.acquire(blocking=False)
    try:
        r = client.post(BACKFILL_URL)
        assert r.status_code == 409
        body = r.get_json()
        assert body["error"] == "RefreshBusy"
    finally:
        wp._LEDGER_BACKFILL_LOCK.release()


# ── empty wallet set ───────────────────────────────────────────────────

def test_no_tracked_wallets_still_runs_cleanly(client, db, monkeypatch):
    monkeypatch.setattr(wp, "_maxfi_tracked_wallets", lambda: [])
    scan = _empty_scan(wallets_scanned=[])
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)

    r = client.post(BACKFILL_URL)
    assert r.status_code == 200
    body = r.get_json()
    assert body["wallets_scanned"] == []
    assert body["positions_upserted"] == 0
