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
        "decode_failed": 0,
        "decode_failures": [],
        "chunk_stats": {
            "pass1_vault": {"calls": 1, "chunk_halvings": 0, "retries_429": 0, "final_chunk_size": mli.DEFAULT_CHUNK_SIZE},
            "pass1_snuggle_rebalanced": {"calls": 1, "chunk_halvings": 0, "retries_429": 0, "final_chunk_size": mli.DEFAULT_CHUNK_SIZE},
            "pass2_staking_manager": {"calls": 0, "chunk_halvings": 0, "retries_429": 0, "final_chunk_size": None},
            "receipts": {
                "txs": 0, "calls": 0, "null_receipts": 0,
                "increase_liquidity_kept": 0, "increase_liquidity_dropped": 0,
            },
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

    # Commit 3b.1.6: pool_added/pass3_npm retired, receipts is the new key.
    assert "receipts" in body["chunk_stats"]
    assert "pool_added" not in body["chunk_stats"]
    assert "pass3_npm" not in body["chunk_stats"]

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
    # Commit 3b.1.6 (ruling 9 amended, receipt-based NPM resolution) -
    # shape is {"npm_address", "token_ids": [...]} grouped by emitter,
    # not the retired {"pool_id", "npm_address"} shape.
    scan = _empty_scan(
        raw_logs=[],
        npm_resolutions=[{"npm_address": "0x" + "33" * 20, "token_ids": [6039568]}],
    )
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)

    r = client.post(BACKFILL_URL)
    body = r.get_json()
    assert body["npm_resolutions"] == [{"npm_address": "0x" + "33" * 20, "token_ids": [6039568]}]


# ── end-to-end dry_run: receipt-based NPM resolution + basis (Commit   ──
# ── 3b.1.6, ruling 9 amended) ────────────────────────────────────────────
# Unlike every other test in this file, this one does NOT monkeypatch
# scan_chain() wholesale - it stubs the underlying RPC functions
# (mirroring tests/test_maxfi_ledger_ingest.py's own receipt-walk tests)
# so the REAL scan_chain() runs inside the route end to end, proving
# IncreaseLiquidity actually reaches "fetched" and the derived position
# actually carries a non-null basis - not just that scan_chain()'s
# return value gets echoed back, which the mocked-scan_chain tests above
# already cover.

def test_dry_run_end_to_end_shows_increase_liquidity_and_position_basis(client, db, monkeypatch):
    token_id = 100
    tx = "0x" + "aa" * 32
    npm_address = "0x" + "33" * 20
    pool_id = "0x" + "11" * 32

    pc_log = _position_created_log(token_id, pool_id=pool_id, tx_hash=tx, log_index=0)

    def fake_eth_get_logs(c, address, topics, from_block, to_block, timeout=30):
        group = set(topics[0])
        if group == {ml.TOPIC_POSITION_CREATED, ml.TOPIC_POSITION_WITHDRAWN, ml.TOPIC_FEES_HARVESTED}:
            return [pc_log]
        if group == {ml.TOPIC_SNUGGLE_REBALANCED}:
            return []
        if group == {ml.TOPIC_PROTOCOL_FEES_DISTRIBUTED, ml.TOPIC_FEES_COMPOUNDED, ml.TOPIC_FEES_HARVESTED_DIRECT}:
            return []
        raise AssertionError(f"unexpected eth_get_logs call: {address} {topics}")

    def fake_eth_get_transaction_receipt(c, tx_hash, timeout=30):
        il_log = {
            "address": npm_address,
            "blockNumber": hex(100),
            "transactionHash": tx,
            "logIndex": hex(1),
            "topics": [ml.TOPIC_INCREASE_LIQUIDITY, mli.encode_topic_uint256(token_id)],
            "data": "0x" + "".join(_word(w) for w in (3000, 4000, 5000)),
        }
        return {"logs": [il_log]}

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)
    monkeypatch.setattr(mli, "eth_get_transaction_receipt", fake_eth_get_transaction_receipt)
    monkeypatch.setattr(mli, "eth_block_number", lambda chain, timeout=30: mli.CHAINS["base"]["start_block"] + 100)

    r = client.post(f"{BACKFILL_URL}?dry_run=true")
    assert r.status_code == 200
    body = r.get_json()
    assert body["dry_run"] is True
    assert body["fetched"].get("IncreaseLiquidity") == 1
    assert body["fetched"].get("PositionCreated") == 1
    assert body["positions_upserted"] == 1
    assert body["npm_resolutions"] == [{"npm_address": npm_address, "token_ids": [token_id]}]

    # dry_run computes derive_all() internally (positions_upserted above)
    # but never exposes per-position basis fields over HTTP - independently
    # reconstruct the same derivation from the same stubbed RPC inputs.
    # Basis field names read from maxfi_ledger.derive_position_ledger()
    # first: basis_liquidity_wei/basis_amount0_wei/basis_amount1_wei/
    # basis_block/basis_at.
    scan = mli.scan_chain("base", [_WALLET])
    decoded_events = []
    for raw_log in scan["raw_logs"]:
        record = mli.safe_decode_log(raw_log, [], sample_limit=1)
        assert record is not None
        record["chain"] = "base"
        decoded_events.append(record)
    derived = ml.derive_all(decoded_events)
    row = next(r for r in derived if r["token_id"] == str(token_id))
    assert row["basis_liquidity_wei"] == "3000"
    assert row["basis_amount0_wei"] == "4000"
    assert row["basis_amount1_wei"] == "5000"


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


# ── Hotfix 3b.1.3: per-log decode isolation ──────────────────────────────

def test_undecodable_log_is_isolated_reported_and_excluded_from_insert(client, db, monkeypatch):
    """One bad log among scan["raw_logs"] must never 500 the route, must
    never be written to maxfi_ledger_events, and must be surfaced via
    decode_failed/decode_failed_sample/warning."""
    good_log = _position_created_log(6039568)
    bad_log = _make_log(
        _VAULT,
        # Real PositionCreated topic0, only 3 topics - missing pool_id at
        # topics[3], the exact IndexError shape the first production
        # dry_run actually hit.
        [ml.TOPIC_POSITION_CREATED, mli.encode_topic_uint256(999), mli.encode_topic_address(_WALLET)],
        [100, 200, 5000, 0],
        block_number=100,
        tx_hash="0x" + "bb" * 32,
        log_index=1,
    )
    scan = _empty_scan(
        raw_logs=[good_log, bad_log],
        token_ids=["6039568"],
        event_type_counts={"PositionCreated": 1},
        # scan_chain() already found this failure internally (it decodes
        # raw_logs too, for event_type_counts) - the route's own
        # safe_decode_log call over the same raw_logs list will hit it
        # again; the response must report exactly ONE entry, not two.
        decode_failed=1,
        decode_failures=[{
            "tx_hash": bad_log["transactionHash"], "log_index": bad_log["logIndex"],
            "block_number": bad_log["blockNumber"], "contract_address": _VAULT,
            "topic0": ml.TOPIC_POSITION_CREATED, "topic_count": 3, "data_word_count": 4,
            "error": "IndexError: list index out of range",
        }],
    )
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)

    r = client.post(BACKFILL_URL)
    assert r.status_code == 200
    body = r.get_json()

    assert body["decode_failed"] == 1
    assert len(body["decode_failed_sample"]) == 1
    assert body["decode_failed_sample"][0]["error"].startswith("IndexError")
    assert "warning" in body
    assert "decode_failed_sample" in body["warning"]

    assert body["inserted"] == {"PositionCreated": 1}  # only the good log
    event_rows = db.execute("SELECT * FROM maxfi_ledger_events WHERE chain = 'base'").fetchall()
    assert len(event_rows) == 1
    assert event_rows[0]["token_id"] == "6039568"  # the bad log's tx never reached the DB


def test_clean_scan_has_zero_decode_failed_and_no_warning_key(client, db, monkeypatch):
    pc_log = _position_created_log(6039568)
    scan = _empty_scan(raw_logs=[pc_log], token_ids=["6039568"], event_type_counts={"PositionCreated": 1})
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)

    r = client.post(BACKFILL_URL)
    assert r.status_code == 200
    body = r.get_json()

    assert body["decode_failed"] == 0
    assert body["decode_failed_sample"] == []
    assert "warning" not in body
