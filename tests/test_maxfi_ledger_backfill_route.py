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
import maxfi_ledger_pricing as mlp
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


@pytest.fixture(autouse=True)
def _last_run_path(monkeypatch, tmp_path):
    """Commit 3b.2.3: every backfill run now persists its own response to
    LEDGER_BACKFILL_LAST_RUN_PATH - tmp_path-patched (DISPLAY_PREFS_PATH/
    ADVISOR_SETTINGS_PATH's own established test convention) so this
    whole file's tests, old and new alike, never touch the real data/
    directory."""
    monkeypatch.setattr(wp, "LEDGER_BACKFILL_LAST_RUN_PATH", str(tmp_path / "ledger_backfill_last_run_{chain}.json"))


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
    assert "3b.1.5" in body["unverified_event_types_note"]


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


# ── Commit 3b.2: Swap-log USD pricing, real run persists basis_price_usd ──

def _addr_word(address):
    h = address[2:] if address.startswith("0x") else address
    return h.lower().zfill(64)


def _sqrt_price_x96_for(price_t1_per_t0, decimals0, decimals1):
    from decimal import Decimal
    Q96 = 2 ** 96
    ratio_squared = Decimal(price_t1_per_t0) / (Decimal(10) ** (decimals0 - decimals1))
    return int(ratio_squared.sqrt() * Q96)


@pytest.fixture
def _clear_pricing_caches():
    """maxfi_ledger_pricing's pool/decimals/hop-pool caches are
    process-global (same write-only-on-success contract as
    maxfi_client._VAULT_CACHE) - cleared before AND after so this test's
    real pool resolution can never leak a stale/wrong entry into a
    different test's identically-shaped (chain, token_id) key, in either
    direction."""
    mlp._DECIMALS_CACHE.clear()
    mlp._POOL_RESOLUTION_CACHE.clear()
    mlp._HOP_POOL_CACHE.clear()
    yield
    mlp._DECIMALS_CACHE.clear()
    mlp._POOL_RESOLUTION_CACHE.clear()
    mlp._HOP_POOL_CACHE.clear()


def test_real_run_persists_basis_price_usd_via_pricing_pipeline(client, db, monkeypatch, _clear_pricing_caches):
    """End-to-end (Commit 3b.2): stubs the underlying RPC functions (not
    scan_chain() wholesale, mirroring 3b.1.6's own end-to-end precedent
    above) so the REAL scan_chain() AND the REAL pricing pipeline
    (maxfi_ledger_pricing.token0_token1_usd_at_block, direct-stable case:
    the position pool's token1 is Base USDC) both run, proving
    basis_price_usd actually reaches the maxfi_ledger_positions DB row on
    a REAL (non-dry_run) backfill - not just that a stubbed value passes
    through unchanged."""
    token_id = 100
    tx = "0x" + "aa" * 32
    npm_address = "0x" + "33" * 20
    pool_address = "0x" + "99" * 20
    factory_address = "0x" + "88" * 20
    alt_token = "0x" + "cc" * 20
    # amount0 = 2 ALT (18 decimals) at $3/ALT = $6; amount1 = 500 USDC
    # (6 decimals) at $1 = $500; total basis = $506.
    amount0_wei = 2 * 10**18
    amount1_wei = 500 * 10**6

    pc_log = _position_created_log(token_id, tx_hash=tx, log_index=0)

    def fake_eth_get_logs(c, address, topics, from_block, to_block, timeout=30):
        group = set(topics[0]) if topics and topics[0] else set()
        if group == {ml.TOPIC_POSITION_CREATED, ml.TOPIC_POSITION_WITHDRAWN, ml.TOPIC_FEES_HARVESTED}:
            return [pc_log]
        if group == {ml.TOPIC_SNUGGLE_REBALANCED}:
            return []
        if group == {ml.TOPIC_PROTOCOL_FEES_DISTRIBUTED, ml.TOPIC_FEES_COMPOUNDED, ml.TOPIC_FEES_HARVESTED_DIRECT}:
            return []
        if address == pool_address and group == {ml.TOPIC_SWAP}:
            sqrt_price_x96 = _sqrt_price_x96_for(3.0, decimals0=18, decimals1=6)
            words = [_word(0), _word(0), _word(sqrt_price_x96), _word(0), _word(0)]
            return [{
                "address": pool_address,
                "topics": [ml.TOPIC_SWAP, "0x" + "11" * 32, "0x" + "22" * 32],
                "data": "0x" + "".join(words),
                "blockNumber": hex(to_block),
                "timeStamp": hex(1700000000 + to_block),
                "transactionHash": "0x" + format(to_block, "x").rjust(64, "0"),
                "logIndex": "0x0",
            }]
        raise AssertionError(f"unexpected eth_get_logs call: {address} {topics}")

    def fake_eth_get_transaction_receipt(c, tx_hash, timeout=30):
        il_log = {
            "address": npm_address,
            "blockNumber": hex(100),
            "transactionHash": tx,
            "logIndex": hex(1),
            "topics": [ml.TOPIC_INCREASE_LIQUIDITY, mli.encode_topic_uint256(token_id)],
            "data": "0x" + "".join(_word(w) for w in (1000, amount0_wei, amount1_wei)),
        }
        return {"logs": [il_log]}

    def fake_eth_call(chain, to, data, timeout=30):
        if data.startswith(mlp.SEL_NPM_POSITIONS):
            words = [_word(0)] * 12
            words[2] = _addr_word(alt_token)
            words[3] = _addr_word(mlp.ADDR_BASE_USDC)
            words[4] = _word(500)
            return "0x" + "".join(words)
        if data.startswith(mlp.SEL_NPM_FACTORY):
            return "0x" + _addr_word(factory_address)
        if data.startswith(mlp.SEL_FACTORY_GET_POOL):
            return "0x" + _addr_word(pool_address)
        if data.startswith(mlp.SEL_ERC20_DECIMALS):
            return "0x" + _word(18 if to == alt_token else 6)
        raise AssertionError(f"unexpected eth_call: {data}")

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)
    monkeypatch.setattr(mli, "eth_get_transaction_receipt", fake_eth_get_transaction_receipt)
    monkeypatch.setattr(mli, "eth_call", fake_eth_call)
    monkeypatch.setattr(mli, "eth_block_number", lambda chain, timeout=30: mli.CHAINS["base"]["start_block"] + 100)

    r = client.post(BACKFILL_URL)
    assert r.status_code == 200
    body = r.get_json()
    assert body["dry_run"] is False
    assert body["pricing_priced"] == 1
    assert body["pricing_failed"] == 0

    row = db.execute(
        "SELECT basis_price_usd, basis_price_source FROM maxfi_ledger_positions WHERE token_id = ?",
        (str(token_id),),
    ).fetchone()
    assert row is not None
    assert abs(row["basis_price_usd"] - 506.0) < 1e-6
    assert row["basis_price_source"] == "swap_log"


def test_real_run_resolves_pool_from_mint_receipt_not_npm_positions(client, db, monkeypatch, _clear_pricing_caches):
    """End-to-end (Commit 3b.2.1, spec error #25's fix): the receipt's own
    pool Mint log pairs to the kept IncreaseLiquidity log by value, so
    resolve_position_pool() uses the pool's own token0()/token1() -
    NEVER npm.positions() at "latest", which reverts for a burned NFT.
    eth_call is stubbed to ONLY answer token0()/token1()/decimals() and
    raise on anything else, so positions()/factory()/getPool() being
    called at all would fail this test loudly. Also proves pool_address
    persists on the written row and pool_resolved is reported."""
    token_id = 300
    tx = "0x" + "dd" * 32
    npm_address = "0x" + "33" * 20
    pool_address = "0x" + "99" * 20
    alt_token = "0x" + "cc" * 20
    amount0_wei = 2 * 10**18
    amount1_wei = 500 * 10**6
    liquidity = 1000

    pc_log = _position_created_log(token_id, tx_hash=tx, log_index=0)

    def fake_eth_get_logs(c, address, topics, from_block, to_block, timeout=30):
        group = set(topics[0]) if topics and topics[0] else set()
        if group == {ml.TOPIC_POSITION_CREATED, ml.TOPIC_POSITION_WITHDRAWN, ml.TOPIC_FEES_HARVESTED}:
            return [pc_log]
        if group == {ml.TOPIC_SNUGGLE_REBALANCED}:
            return []
        if group == {ml.TOPIC_PROTOCOL_FEES_DISTRIBUTED, ml.TOPIC_FEES_COMPOUNDED, ml.TOPIC_FEES_HARVESTED_DIRECT}:
            return []
        if address == pool_address and group == {ml.TOPIC_SWAP}:
            sqrt_price_x96 = _sqrt_price_x96_for(3.0, decimals0=18, decimals1=6)
            words = [_word(0), _word(0), _word(sqrt_price_x96), _word(0), _word(0)]
            return [{
                "address": pool_address,
                "topics": [ml.TOPIC_SWAP, "0x" + "11" * 32, "0x" + "22" * 32],
                "data": "0x" + "".join(words),
                "blockNumber": hex(to_block),
                "timeStamp": hex(1700000000 + to_block),
                "transactionHash": "0x" + format(to_block, "x").rjust(64, "0"),
                "logIndex": "0x0",
            }]
        raise AssertionError(f"unexpected eth_get_logs call: {address} {topics}")

    def fake_eth_get_transaction_receipt(c, tx_hash, timeout=30):
        il_log = {
            "address": npm_address,
            "blockNumber": hex(100),
            "transactionHash": tx,
            "logIndex": hex(1),
            "topics": [ml.TOPIC_INCREASE_LIQUIDITY, mli.encode_topic_uint256(token_id)],
            "data": "0x" + "".join(_word(w) for w in (liquidity, amount0_wei, amount1_wei)),
        }
        mint_log = {
            "address": pool_address,
            "blockNumber": hex(100),
            "transactionHash": tx,
            "logIndex": hex(2),
            "topics": [mli.TOPIC_POOL_MINT, "0x" + "aa" * 32, "0x" + "bb" * 32, "0x" + "cc" * 32],
            "data": "0x" + "".join(_word(w) for w in (0, liquidity, amount0_wei, amount1_wei)),
        }
        return {"logs": [il_log, mint_log]}

    def fake_eth_call(chain, to, data, timeout=30):
        if data.startswith(mlp.SEL_POOL_TOKEN0):
            return "0x" + _addr_word(alt_token)
        if data.startswith(mlp.SEL_POOL_TOKEN1):
            return "0x" + _addr_word(mlp.ADDR_BASE_USDC)
        if data.startswith(mlp.SEL_ERC20_DECIMALS):
            return "0x" + _word(18 if to == alt_token else 6)
        raise AssertionError(
            f"unexpected eth_call - npm.positions()/factory()/getPool() must never "
            f"be called on the mint_receipt path: {data}"
        )

    monkeypatch.setattr(mli, "eth_get_logs", fake_eth_get_logs)
    monkeypatch.setattr(mli, "eth_get_transaction_receipt", fake_eth_get_transaction_receipt)
    monkeypatch.setattr(mli, "eth_call", fake_eth_call)
    monkeypatch.setattr(mli, "eth_block_number", lambda chain, timeout=30: mli.CHAINS["base"]["start_block"] + 100)

    r = client.post(BACKFILL_URL)
    assert r.status_code == 200
    body = r.get_json()
    assert body["dry_run"] is False
    assert body["pricing_priced"] == 1
    assert body["pricing_failed"] == 0
    assert body["pool_resolved"] == 1

    row = db.execute(
        "SELECT pool_address, basis_price_usd FROM maxfi_ledger_positions WHERE token_id = ?",
        (str(token_id),),
    ).fetchone()
    assert row is not None
    assert row["pool_address"] == pool_address.lower()
    assert abs(row["basis_price_usd"] - 506.0) < 1e-6


# ── Commit 3b.2 amendment: exit pricing is principal-only ────────────────
# PositionWithdrawn's amounts are NET and INCLUDE any same-tx harvested
# fees (HANDOFF's own verified ground truth: "exit principal =
# PositionWithdrawn − FeesHarvested x0.85, don't double-count"). Both
# tests below run the REAL pricing block (mli.scan_chain mocked wholesale,
# same boundary most of this file's other tests use) with
# maxfi_ledger_pricing.token0_token1_usd_at_block stubbed directly to a
# known price - no real RPC pool resolution is exercised here (that's
# already proven by the basis end-to-end test above); these two are
# scoped narrowly to the principal-only subtraction itself. SYNTHETIC: no
# real PositionWithdrawn+FeesHarvested+ProtocolFeesDistributed fixture
# exists in this repo for a same-tx exit.

def _position_withdrawn_log(token_id, owner, amount0, amount1, address, block_number, tx_hash, log_index=0):
    topics = [ml.TOPIC_POSITION_WITHDRAWN, mli.encode_topic_uint256(token_id), mli.encode_topic_address(owner)]
    return _make_log(address, topics, [amount0, amount1], block_number, tx_hash, log_index)


def _fees_harvested_log(token_id, owner, fees0, fees1, address, block_number, tx_hash, log_index=0):
    topics = [ml.TOPIC_FEES_HARVESTED, mli.encode_topic_uint256(token_id), mli.encode_topic_address(owner)]
    return _make_log(address, topics, [fees0, fees1], block_number, tx_hash, log_index)


def _protocol_fees_distributed_log(token_id, treasury0, treasury1, referral0, referral1, address,
                                    block_number, tx_hash, log_index=0):
    topics = [ml.TOPIC_PROTOCOL_FEES_DISTRIBUTED, mli.encode_topic_uint256(token_id)]
    return _make_log(address, topics, [treasury0, treasury1, referral0, referral1], block_number, tx_hash, log_index)


def _synthetic_exit_scan(token_id, tx_open, tx_close, amount0, amount1, fees0, fees1, treasury0, treasury1):
    """A same-tx PositionWithdrawn + FeesHarvested + ProtocolFeesDistributed
    bundle, so derive_all() computes REAL exit_net_fee0_wei/exit_net_fee1_wei
    via _tx_net_claim() - not hand-set, the actual derive-side computation
    this amendment must read from."""
    pool_id = "0x" + "11" * 32
    staking_manager = mli.CHAINS["base"]["staking_manager"]
    pc_log = _position_created_log(token_id, pool_id=pool_id, tx_hash=tx_open, block_number=100, log_index=0)
    pw_log = _position_withdrawn_log(token_id, _WALLET, amount0, amount1, _VAULT, 200, tx_close, log_index=0)
    fh_log = _fees_harvested_log(token_id, _WALLET, fees0, fees1, _VAULT, 200, tx_close, log_index=1)
    pfd_log = _protocol_fees_distributed_log(
        token_id, treasury0, treasury1, 0, 0, staking_manager, 200, tx_close, log_index=2
    )
    return _empty_scan(
        raw_logs=[pc_log, pw_log, fh_log, pfd_log],
        token_ids=[str(token_id)],
        npm_resolutions=[{"npm_address": "0x" + "33" * 20, "token_ids": [token_id]}],
        event_type_counts={
            "PositionCreated": 1, "PositionWithdrawn": 1,
            "FeesHarvested": 1, "ProtocolFeesDistributed": 1,
        },
    )


def test_exit_price_usd_is_principal_only_not_gross(client, db, monkeypatch):
    token_id = 200
    tx_open = "0x" + "dd" * 32
    tx_close = "0x" + "ee" * 32
    # principal0 = 1000 (dec18), net_fee0 = 85 (dec18) -> amount0 = 1085.
    # principal1 = 500 (dec6), net_fee1 = 85 (dec6) -> amount1 = 585.
    amount0, amount1 = 1085 * 10**18, 585 * 10**6
    fees0, fees1 = 100 * 10**18, 100 * 10**6
    treasury0, treasury1 = 15 * 10**18, 15 * 10**6  # 85/15 split, referral 0

    scan = _synthetic_exit_scan(token_id, tx_open, tx_close, amount0, amount1, fees0, fees1, treasury0, treasury1)
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)
    monkeypatch.setattr(
        mlp, "token0_token1_usd_at_block",
        lambda chain, npm_address, tid, block, pool=None, pool_address=None: (
            2.0, 1.0, {"pool_address": "0x" + "99" * 20, "token0": "0x" + "aa" * 20, "token1": "0x" + "bb" * 20, "decimals0": 18, "decimals1": 6}, {"swap_walk_calls": 0, "windows_checked": 0, "reason": None, "rpc_calls": 0},
        ),
    )

    r = client.post(BACKFILL_URL)
    assert r.status_code == 200
    body = r.get_json()
    assert body["pricing_priced"] == 1
    assert body["pricing_failed"] == 0

    row = db.execute(
        "SELECT exit_price_usd, exit_price_source, exit_amount0_wei, exit_net_fee0_wei "
        "FROM maxfi_ledger_positions WHERE token_id = ?",
        (str(token_id),),
    ).fetchone()
    assert row is not None
    assert row["exit_amount0_wei"] == str(amount0)  # gross, unchanged - only the USD figure is net
    assert row["exit_net_fee0_wei"] == str(85 * 10**18)  # derive_all()'s own real computation
    # principal-only: (1000 @ $2) + (500 @ $1) = $2500, NOT gross (1085@$2 + 585@$1 = $2755).
    assert abs(row["exit_price_usd"] - 2500.0) < 1e-6
    assert row["exit_price_source"] == "swap_log"


def test_exit_price_usd_skipped_when_net_fee_exceeds_withdrawal(client, db, monkeypatch):
    """An impossible-on-chain shape (net fee bigger than the withdrawal
    itself, side 0) - must not price a negative principal; counted as
    pricing_failed with a specific reason, exit_price_usd stays None."""
    token_id = 201
    tx_open = "0x" + "ff" * 32
    tx_close = "0x" + "12" * 32
    amount0, amount1 = 50 * 10**18, 100 * 10**6
    fees0, fees1 = 60 * 10**18, 10 * 10**6  # net_fee0 = 60 > amount0 = 50
    treasury0, treasury1 = 0, 0

    scan = _synthetic_exit_scan(token_id, tx_open, tx_close, amount0, amount1, fees0, fees1, treasury0, treasury1)
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)
    monkeypatch.setattr(
        mlp, "token0_token1_usd_at_block",
        lambda chain, npm_address, tid, block, pool=None, pool_address=None: (
            2.0, 1.0, {"pool_address": "0x" + "99" * 20, "token0": "0x" + "aa" * 20, "token1": "0x" + "bb" * 20, "decimals0": 18, "decimals1": 6}, {"swap_walk_calls": 0, "windows_checked": 0, "reason": None, "rpc_calls": 0},
        ),
    )

    r = client.post(BACKFILL_URL)
    assert r.status_code == 200
    body = r.get_json()
    assert body["pricing_priced"] == 0
    assert body["pricing_failed"] == 1
    assert body["pricing_failed_sample"][0] == {
        "token_id": str(token_id), "field": "exit", "reason": "net_fee_exceeds_withdrawal",
        "pool_address": "0x" + "99" * 20, "token0": "0x" + "aa" * 20, "token1": "0x" + "bb" * 20,
        "hop_anchor": None,  # Commit 3b.3a - additive sample key (3b.2.2 precedent)
    }

    row = db.execute(
        "SELECT exit_price_usd FROM maxfi_ledger_positions WHERE token_id = ?", (str(token_id),)
    ).fetchone()
    assert row is not None
    assert row["exit_price_usd"] is None


# ── Commit 3b.2.2: pricing failure samples carry the pool's tokens ───────
# The resolution dict (pool_address, token0, token1, decimals0, decimals1)
# is already in hand at the point each pricing_failed_sample entry is
# built, so a non-None pool must carry its own address/token0/token1 into
# the sample - whatever the failure reason - while a None pool (nothing
# resolved) leaves the sample unchanged. Reuses the same exit-branch
# scan/stub boundary as the two tests directly above.

def test_pricing_failed_sample_carries_pool_tokens_when_unpriceable(client, db, monkeypatch):
    """unpriceable_pair (pool resolved but neither side has a USD price) -
    the sample must gain pool_address/token0/token1 alongside the
    existing token_id/field/reason keys."""
    token_id = 202
    tx_open = "0x" + "13" * 32
    tx_close = "0x" + "14" * 32
    amount0, amount1 = 50 * 10**18, 100 * 10**6
    fees0, fees1 = 0, 0
    treasury0, treasury1 = 0, 0

    scan = _synthetic_exit_scan(token_id, tx_open, tx_close, amount0, amount1, fees0, fees1, treasury0, treasury1)
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)
    monkeypatch.setattr(
        mlp, "token0_token1_usd_at_block",
        lambda chain, npm_address, tid, block, pool=None, pool_address=None: (
            None, None,
            {"pool_address": "0x" + "99" * 20, "token0": "0x" + "aa" * 20, "token1": "0x" + "bb" * 20,
             "decimals0": 18, "decimals1": 6},
            {"swap_walk_calls": 0, "windows_checked": 0, "reason": "unpriceable_pair", "rpc_calls": 0},
        ),
    )

    r = client.post(BACKFILL_URL)
    assert r.status_code == 200
    body = r.get_json()
    assert body["pricing_priced"] == 0
    assert body["pricing_failed"] == 1
    assert body["pricing_failed_sample"][0] == {
        "token_id": str(token_id), "field": "exit", "reason": "unpriceable_pair",
        "pool_address": "0x" + "99" * 20, "token0": "0x" + "aa" * 20, "token1": "0x" + "bb" * 20,
        "hop_anchor": None,  # Commit 3b.3a - additive sample key (3b.2.2 precedent)
    }


def test_pricing_failed_sample_omits_pool_tokens_when_pool_unresolved(client, db, monkeypatch):
    """pool_unresolved (pool is None) - nothing to carry, the sample keeps
    its original token_id/field/reason shape only."""
    token_id = 203
    tx_open = "0x" + "15" * 32
    tx_close = "0x" + "16" * 32
    amount0, amount1 = 50 * 10**18, 100 * 10**6
    fees0, fees1 = 0, 0
    treasury0, treasury1 = 0, 0

    scan = _synthetic_exit_scan(token_id, tx_open, tx_close, amount0, amount1, fees0, fees1, treasury0, treasury1)
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)
    monkeypatch.setattr(
        mlp, "token0_token1_usd_at_block",
        lambda chain, npm_address, tid, block, pool=None, pool_address=None: (
            None, None, None,
            {"swap_walk_calls": 0, "windows_checked": 0, "reason": "pool_unresolved", "rpc_calls": 0},
        ),
    )

    r = client.post(BACKFILL_URL)
    assert r.status_code == 200
    body = r.get_json()
    assert body["pricing_priced"] == 0
    assert body["pricing_failed"] == 1
    assert body["pricing_failed_sample"][0] == {
        "token_id": str(token_id), "field": "exit", "reason": "pool_unresolved",
        "hop_anchor": None,  # Commit 3b.3a - additive sample key (3b.2.2 precedent)
    }


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


# ── Commit 3b.2.3: price carry-forward + reprice ──────────────────────────
# All four tests reuse the exit-branch scan/stub boundary the 3b.2/3b.2.2
# exit tests above already established: mli.scan_chain mocked wholesale,
# mlp.token0_token1_usd_at_block stubbed directly to a known
# price/pool/stats shape (now including "rpc_calls" - Commit 3b.2.3's own
# additive stats key).

def _fake_pricing_priced(chain, npm_address, tid, block, pool=None, pool_address=None):
    return (
        2.0, 1.0,
        {"pool_address": "0x" + "99" * 20, "token0": "0x" + "aa" * 20, "token1": "0x" + "bb" * 20,
         "decimals0": 18, "decimals1": 6},
        {"swap_walk_calls": 1, "windows_checked": 1, "reason": None, "rpc_calls": 1},
    )


def test_carry_forward_skips_repricing_an_already_priced_row(client, db, monkeypatch):
    """A row priced by a first run stays priced (in the DB and in the
    response) on a second run, with ZERO pricing calls made for it -
    carry-forward, not a re-price."""
    token_id = 300
    tx_open, tx_close = "0x" + "20" * 32, "0x" + "21" * 32
    amount0, amount1 = 50 * 10**18, 100 * 10**6

    scan = _synthetic_exit_scan(token_id, tx_open, tx_close, amount0, amount1, 0, 0, 0, 0)
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)
    call_count = {"n": 0}

    def fake_pricing(chain, npm_address, tid, block, pool=None, pool_address=None):
        call_count["n"] += 1
        return _fake_pricing_priced(chain, npm_address, tid, block, pool=pool, pool_address=pool_address)

    monkeypatch.setattr(mlp, "token0_token1_usd_at_block", fake_pricing)

    r1 = client.post(BACKFILL_URL)
    assert r1.status_code == 200
    body1 = r1.get_json()
    assert body1["pricing_priced"] == 1
    assert call_count["n"] == 1

    r2 = client.post(BACKFILL_URL)
    assert r2.status_code == 200
    body2 = r2.get_json()
    assert body2["pricing_priced"] == 0  # not re-priced this run
    assert body2["pricing_failed"] == 0
    assert body2["pricing_carried_forward"] == {"basis": 0, "exit": 1, "pool_address": 1}
    assert body2["reprice"] is False
    assert call_count["n"] == 1  # no pricing call made on the second run

    row = db.execute(
        "SELECT exit_price_usd FROM maxfi_ledger_positions WHERE token_id = ?", (str(token_id),)
    ).fetchone()
    assert abs(row["exit_price_usd"] - 200.0) < 1e-6  # 50@$2 + 100@$1, unchanged by the second run


def test_reprice_true_reprices_an_already_priced_row(client, db, monkeypatch):
    token_id = 304
    tx_open, tx_close = "0x" + "26" * 32, "0x" + "27" * 32
    amount0, amount1 = 50 * 10**18, 100 * 10**6

    scan = _synthetic_exit_scan(token_id, tx_open, tx_close, amount0, amount1, 0, 0, 0, 0)
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)
    call_count = {"n": 0}

    def fake_pricing(chain, npm_address, tid, block, pool=None, pool_address=None):
        call_count["n"] += 1
        return _fake_pricing_priced(chain, npm_address, tid, block, pool=pool, pool_address=pool_address)

    monkeypatch.setattr(mlp, "token0_token1_usd_at_block", fake_pricing)

    r1 = client.post(BACKFILL_URL)
    assert r1.status_code == 200
    assert call_count["n"] == 1

    r2 = client.post(BACKFILL_URL + "?reprice=true")
    assert r2.status_code == 200
    body2 = r2.get_json()
    assert body2["reprice"] is True
    assert body2["pricing_priced"] == 1  # re-priced, not carried
    assert body2["pricing_carried_forward"] == {"basis": 0, "exit": 0, "pool_address": 0}
    assert call_count["n"] == 2  # a second pricing call WAS made


def test_carry_forward_pool_address_even_when_still_unpriced(client, db, monkeypatch):
    """pool_address carries forward even for a row whose price stayed
    None (a real RPC failure) - the pool resolution itself is still
    valid/reusable even when the walk that follows it failed."""
    token_id = 301
    tx_open, tx_close = "0x" + "22" * 32, "0x" + "23" * 32
    amount0, amount1 = 50 * 10**18, 100 * 10**6

    scan = _synthetic_exit_scan(token_id, tx_open, tx_close, amount0, amount1, 0, 0, 0, 0)
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)

    def fake_pricing_unpriceable(chain, npm_address, tid, block, pool=None, pool_address=None):
        return (
            None, None,
            {"pool_address": "0x" + "99" * 20, "token0": "0x" + "aa" * 20, "token1": "0x" + "bb" * 20,
             "decimals0": 18, "decimals1": 6},
            {"swap_walk_calls": 0, "windows_checked": 0, "reason": "unpriceable_pair", "rpc_calls": 1},
        )

    monkeypatch.setattr(mlp, "token0_token1_usd_at_block", fake_pricing_unpriceable)

    r1 = client.post(BACKFILL_URL)
    assert r1.status_code == 200
    body1 = r1.get_json()
    assert body1["pricing_failed"] == 1
    assert body1["pool_resolved"] == 1

    row1 = db.execute(
        "SELECT pool_address FROM maxfi_ledger_positions WHERE token_id = ?", (str(token_id),)
    ).fetchone()
    assert row1["pool_address"] == "0x" + "99" * 20

    r2 = client.post(BACKFILL_URL)
    assert r2.status_code == 200
    body2 = r2.get_json()
    assert body2["pricing_carried_forward"]["pool_address"] == 1
    assert body2["pricing_carried_forward"]["exit"] == 0  # still unpriced - nothing to carry there
    assert body2["pricing_failed"] == 1  # exit was re-attempted (still unpriced) and failed again


# ── Commit 3b.2.3: pricing call budget ────────────────────────────────────

def test_budget_defers_rows_once_exhausted_but_still_upserts_all(client, db, monkeypatch):
    """budget=1, two unpriced rows needing exit pricing - exactly one is
    priced, one deferred; BOTH rows are still upserted (the budget never
    skips the write)."""
    token_id_a, token_id_b = 302, 303
    tx_open_a, tx_close_a = "0x" + "24" * 32, "0x" + "25" * 32
    tx_open_b, tx_close_b = "0x" + "28" * 32, "0x" + "29" * 32
    amount0, amount1 = 50 * 10**18, 100 * 10**6

    scan_a = _synthetic_exit_scan(token_id_a, tx_open_a, tx_close_a, amount0, amount1, 0, 0, 0, 0)
    scan_b = _synthetic_exit_scan(token_id_b, tx_open_b, tx_close_b, amount0, amount1, 0, 0, 0, 0)
    combined = _empty_scan(
        raw_logs=scan_a["raw_logs"] + scan_b["raw_logs"],
        token_ids=[str(token_id_a), str(token_id_b)],
        npm_resolutions=[{"npm_address": "0x" + "33" * 20, "token_ids": [token_id_a, token_id_b]}],
        event_type_counts={
            "PositionCreated": 2, "PositionWithdrawn": 2, "FeesHarvested": 2, "ProtocolFeesDistributed": 2,
        },
    )
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: combined)
    monkeypatch.setattr(mlp, "token0_token1_usd_at_block", _fake_pricing_priced)

    r = client.post(BACKFILL_URL + "?max_pricing_calls=1")
    assert r.status_code == 200
    body = r.get_json()
    assert body["pricing_priced"] == 1
    assert body["pricing_failed"] == 0
    assert body["pricing_deferred"] == {"basis": 0, "exit": 1}
    assert body["pricing_calls_used"] == 1
    assert body["pricing_call_budget"] == 1

    rows = db.execute(
        "SELECT token_id, exit_price_usd FROM maxfi_ledger_positions WHERE chain = 'base' ORDER BY token_id"
    ).fetchall()
    assert len(rows) == 2  # both upserted regardless of the budget
    priced_count = sum(1 for r in rows if r["exit_price_usd"] is not None)
    assert priced_count == 1  # the other kept exit_price_usd None (deferred, not carried)


def test_default_budget_is_module_constant(client, db, monkeypatch):
    scan = _empty_scan()
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)

    r = client.post(BACKFILL_URL)
    assert r.status_code == 200
    assert r.get_json()["pricing_call_budget"] == wp.MAXFI_LEDGER_PRICING_CALL_BUDGET


def test_max_pricing_calls_non_int_returns_400(client, db):
    r = client.post(BACKFILL_URL + "?max_pricing_calls=abc")
    assert r.status_code == 400
    assert "max_pricing_calls" in r.get_json()["error"]


def test_max_pricing_calls_zero_returns_400(client, db):
    r = client.post(BACKFILL_URL + "?max_pricing_calls=0")
    assert r.status_code == 400


def test_max_pricing_calls_negative_returns_400(client, db):
    r = client.post(BACKFILL_URL + "?max_pricing_calls=-5")
    assert r.status_code == 400


# ── Commit 3b.2.3: persisted last-run + GET .../last-run ──────────────────

LAST_RUN_URL = "/api/maxfi/ledger/backfill/base/last-run"


def test_last_run_returns_404_before_any_run(client, db):
    r = client.get(LAST_RUN_URL)
    assert r.status_code == 404
    assert r.get_json()["error"] == "no run recorded"


def test_last_run_invalid_chain_returns_400(client, db):
    r = client.get("/api/maxfi/ledger/backfill/not-a-real-chain/last-run")
    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidChain"


def test_last_run_returns_persisted_result_after_a_run(client, db, monkeypatch):
    pc_log = _position_created_log(6039568)
    scan = _empty_scan(raw_logs=[pc_log], token_ids=["6039568"], event_type_counts={"PositionCreated": 1})
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)

    r1 = client.post(BACKFILL_URL)
    assert r1.status_code == 200
    body1 = r1.get_json()

    r2 = client.get(LAST_RUN_URL)
    assert r2.status_code == 200
    body2 = r2.get_json()
    assert body2["run_at"] == body1["run_at"]
    assert body2["chain"] == "base"
    assert body2["positions_upserted"] == body1["positions_upserted"]


def test_last_run_persists_dry_run_result_too(client, db, monkeypatch):
    pc_log = _position_created_log(6039568)
    scan = _empty_scan(raw_logs=[pc_log], token_ids=["6039568"], event_type_counts={"PositionCreated": 1})
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)

    r1 = client.post(BACKFILL_URL + "?dry_run=true")
    assert r1.status_code == 200

    r2 = client.get(LAST_RUN_URL)
    assert r2.status_code == 200
    assert r2.get_json()["dry_run"] is True


def test_last_run_write_failure_does_not_fail_the_request(client, db, monkeypatch):
    """os.replace() raising (e.g. a full disk) is swallowed - the
    backfill request itself must still succeed."""
    scan = _empty_scan()
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)
    monkeypatch.setattr(wp.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))

    r = client.post(BACKFILL_URL)
    assert r.status_code == 200


# ── Commit 3b.2.5: werkzeug HTTPExceptions pass through handle_exception ──
# App-level, not backfill-specific - lives here because this is the
# workstream's route-test home and no dedicated app-level test file exists.

def test_favicon_probe_returns_404_not_500(client):
    """No /favicon.ico route exists (the file is only under /static/), so
    the browser's probe is a werkzeug NotFound. handle_exception used to
    re-raise it - two tracebacks per probe, the Sep 20 Railway log flood -
    it must pass through as a plain 404."""
    r = client.get("/favicon.ico")
    assert r.status_code == 404


def test_unknown_api_path_returns_404_not_500(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
