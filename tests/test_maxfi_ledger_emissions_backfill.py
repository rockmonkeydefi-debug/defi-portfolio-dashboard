"""Emissions C3 - POST /api/maxfi/ledger/backfill/<chain> reports
response["emissions"] on dry AND real runs, writes NOTHING for emissions,
isolates an emissions RPC failure, draws on the remaining pricing budget,
and leaves the pinned pricing maps unchanged.

No network: scan_chain is monkeypatched wholesale (this file's ledger
rows), the new reward passes go through the REAL scan_reward_events with
eth_block_number/eth_get_logs/eth_get_transaction_receipt stubbed from the
synthetic-but-exact fixture, and reward pricing is stubbed at
maxfi_ledger_pricing.reward_token_usd_at_block."""
import datetime
import json
import os
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
import maxfi_ledger_emissions as mle
import maxfi_ledger_ingest as mli
import maxfi_ledger_pricing as mlp
import maxfi_schema
import src.storage.portfolio_db as portfolio_db

BACKFILL_URL = "/api/maxfi/ledger/backfill/base"
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "maxfi_ledger", "base_emissions_claims_synthetic.json")
WALLET = "0xab7a515c6e2eea5140ed8a5b09a7d782f3b26743"
VAULT = mli.CHAINS["base"]["vault"]
SM = mli.CHAINS["base"]["staking_manager"]
AERO = "0x940181a94a35a4569e4529a3cdfb74e38fd98631"
EMISSIONS_TOPICS = {mle.TOPIC_STAKING_REWARDS_CLAIMED, mle.TOPIC_PERFORMANCE_FEE_COLLECTED,
                    mle.TOPIC_POSITION_STAKED, mle.TOPIC_POSITION_UNSTAKED}


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
    uri = f"file:maxfi_ledger_emissions_backfill_{uuid.uuid4().hex}?mode=memory&cache=shared"
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
    monkeypatch.setattr(wp, "LEDGER_BACKFILL_LAST_RUN_PATH", str(tmp_path / "ledger_backfill_last_run_{chain}.json"))


def _fx():
    with open(FIXTURE) as fh:
        return json.load(fh)


def _w(*vals):
    return "0x" + "".join(format(v, "064x") for v in vals)


def _ledger_log(topics, data, block, tx, idx=0):
    return {"address": VAULT, "topics": topics, "data": data, "blockNumber": hex(block),
            "timeStamp": hex(1_700_000_000 + block), "transactionHash": tx, "logIndex": hex(idx)}


def _ledger_scan(fx):
    """67658300 opened at 45.0M and rebalanced (-> 68060759) in the keeper
    tx's block; 71122634 opened at 46.0M and withdrawn in the withdrawal
    tx's block - so all three fixture claims are in-window."""
    keeper_block = fx["txs"][1]["block_number"]
    withdrawal_block = fx["txs"][2]["block_number"]
    owner = mli.encode_topic_address(WALLET)
    raw = [
        _ledger_log([ml.TOPIC_POSITION_CREATED, mli.encode_topic_uint256(67658300), owner, "0x" + "11" * 32],
                    _w(100, 200, 5000, 0), 45_000_000, "0x" + "e1" * 32),
        _ledger_log([ml.TOPIC_SNUGGLE_REBALANCED, mli.encode_topic_uint256(67658300),
                     mli.encode_topic_uint256(68060759), owner],
                    _w(100, 200, 0, 0, 0, 1), keeper_block, fx["txs"][1]["tx_hash"], 5),
        _ledger_log([ml.TOPIC_POSITION_CREATED, mli.encode_topic_uint256(71122634), owner, "0x" + "22" * 32],
                    _w(100, 200, 5000, 0), 46_000_000, "0x" + "e3" * 32),
        _ledger_log([ml.TOPIC_POSITION_WITHDRAWN, mli.encode_topic_uint256(71122634), owner],
                    _w(1, 1), withdrawal_block, fx["txs"][2]["tx_hash"], 5),
    ]
    empty = {"calls": 0, "chunk_halvings": 0, "retries_429": 0, "final_chunk_size": None}
    return {
        "raw_logs": raw, "wallets_scanned": [WALLET], "token_ids": ["67658300", "68060759", "71122634"],
        "npm_resolutions": [], "event_type_counts": {}, "decode_failed": 0, "decode_failures": [],
        "chunk_stats": {"pass1_vault": dict(empty), "pass1_snuggle_rebalanced": dict(empty),
                        "pass2_staking_manager": dict(empty), "receipts": {"txs": 0, "calls": 0, "null_receipts": 0}},
    }


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _install(monkeypatch, fx, price_age_seconds=3600, reward_getlogs_error=None):
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: _ledger_scan(fx))
    monkeypatch.setattr(mli, "eth_block_number", lambda chain, timeout=30: 47_000_000)

    def fake_get_logs(chain, address, topics, from_block, to_block, timeout=30):
        if reward_getlogs_error is not None:
            raise reward_getlogs_error
        # Honor the block range like a real node: the scan spans more than
        # one DEFAULT_CHUNK_SIZE chunk, so an unfiltered stub would repeat logs.
        return [log for t in fx["txs"] for log in t["get_logs"]
                if log["address"] == address and from_block <= int(log["blockNumber"], 16) <= to_block]

    receipts = {t["tx_hash"]: t["receipt"] for t in fx["txs"]}
    monkeypatch.setattr(mli, "eth_get_logs", fake_get_logs)
    monkeypatch.setattr(mli, "eth_get_transaction_receipt", lambda chain, tx, timeout=30: receipts[tx])

    ts_by_block = {t["block_number"]: int(t["get_logs"][0]["blockTimestamp"], 16) for t in fx["txs"]}
    seen = []

    def fake_price(chain, token, block):
        seen.append((token, block))
        age = price_age_seconds(block) if callable(price_age_seconds) else price_age_seconds
        return {"usd": 0.5, "reason": None, "rpc_calls": 3, "decimals": 18, "price_source": "swap_log",
                "pool_address": mlp.BASE_AERO_WETH_POOL, "hop_anchor": "WETH",
                "price_block": block - age // 2, "price_block_timestamp": _iso(ts_by_block[block] - age),
                "hop_price_block": block - 5, "hop_price_block_timestamp": _iso(ts_by_block[block] - 10)}

    monkeypatch.setattr(mlp, "reward_token_usd_at_block", fake_price)
    return seen


def _post(client, url=BACKFILL_URL):
    r = client.post(url)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def test_dry_run_reports_three_verified_aero_claims(client, db, monkeypatch):
    fx = _fx()
    _install(monkeypatch, fx)
    body = _post(client, f"{BACKFILL_URL}?dry_run=true")
    em = body["emissions"]
    assert em["status"] == "ok" and em["error"] is None
    assert em["writes"] == "disabled (C3 compute-and-report)"
    assert em["token_ids_scanned"] == 3
    assert em["events"] == {"vault_claims": 2, "sm_claims": 2, "fees": 3, "staked": 0, "unstaked": 2,
                            "rejected": 0, "decode_failed": 0}
    # start_block..47.0M spans two DEFAULT_CHUNK_SIZE chunks -> 2 getLogs calls per pass
    assert em["scan"]["rpc_calls"] == {"block_number": 1, "log_calls": 4, "timestamp_lookups": 0,
                                       "receipt_calls": 3, "total": 8}
    assert em["keys_total"] == 3 and em["keys_truncated"] is False
    assert em["summary"]["by_status"]["verified"] == 3
    expected_net = sum(int(t["net_wei"]) for t in fx["txs"])
    totals = em["summary"]["counted_totals"][AERO]
    assert totals["keys"] == 3 and totals["net_wei"] == str(expected_net) and totals["unpriced_keys"] == 0
    assert abs(totals["net_usd"] - expected_net / 1e18 * 0.5) < 1e-9
    assert em["pricing"]["priced"] == 3 and em["pricing"]["calls_used"] == 9 and em["pricing"]["deferred"] == 0
    acc = em["acceptance"]
    assert (acc["fee_keys"], acc["claim_keys"]) == (3, 3)
    assert acc["max_price_age_seconds"] == 3600 and acc["keys_over_24h"] == 0
    assert len(acc["price_ages"]) == 3


def test_key_rows_carry_every_c1_column_and_exact_wei(client, db, monkeypatch):
    fx = _fx()
    _install(monkeypatch, fx)
    em = _post(client, f"{BACKFILL_URL}?dry_run=true")["emissions"]
    c1_columns = {r[1] for r in db.execute("PRAGMA table_info(maxfi_ledger_reward_claims)")}
    by_tx = {k["tx_hash"]: k for k in em["keys"]}
    for t in fx["txs"]:
        k = by_tx[t["tx_hash"]]
        assert c1_columns <= set(k)
        assert (k["gross_wei"], k["fee_wei"], k["net_wei"], k["transfer_wei"]) == (
            t["gross_wei"], t["fee_wei"], t["net_wei"], t["net_wei"])
        assert k["treasury_wei"] == t["fee_wei"] and k["referral_wei"] == "0"
        assert k["owner"] == WALLET and k["owner_is_tracked"] is True and k["in_window"] is True
        assert k["verification_status"] == "verified" and k["price_age_seconds"] == 3600
    assert by_tx[fx["txs"][1]["tx_hash"]]["owner_source"] == "ledger"  # keeper path


def test_real_run_writes_no_emissions_rows_or_event_types(client, db, monkeypatch):
    _install(monkeypatch, _fx())
    body = _post(client)
    assert body["dry_run"] is False and body["emissions"]["status"] == "ok"
    assert body["emissions"]["keys_total"] == 3
    assert db.execute("SELECT COUNT(*) FROM maxfi_ledger_reward_claims").fetchone()[0] == 0
    topics = {r[0] for r in db.execute("SELECT DISTINCT topic0 FROM maxfi_ledger_events")}
    assert topics and not (topics & EMISSIONS_TOPICS)
    types = {r[0] for r in db.execute("SELECT DISTINCT event_type FROM maxfi_ledger_events")}
    assert types == {"PositionCreated", "SnuggleRebalanced", "PositionWithdrawn"}
    assert db.execute("SELECT COUNT(*) FROM maxfi_ledger_positions").fetchone()[0] == body["positions_upserted"] == 3


def test_emissions_rpc_error_is_isolated_from_positions_and_claims(client, db, monkeypatch):
    fx = _fx()
    _install(monkeypatch, fx)
    baseline = _post(client, f"{BACKFILL_URL}?dry_run=true")

    _install(monkeypatch, fx, reward_getlogs_error=mli.MaxFiRpcError("reward getLogs down"))
    body = _post(client)
    em = body["emissions"]
    assert em["status"] == "error" and em["error"]["type"] == "rpc_error"
    assert "reward getLogs down" in em["error"]["detail"]
    assert em["keys"] == [] and em["writes"] == "disabled (C3 compute-and-report)"
    for field in ("positions_upserted", "claims_upserted", "fetched", "pricing_priced", "pricing_failed",
                  "pricing_deferred", "pricing_carried_forward", "pricing_calls_used"):
        assert body[field] == baseline[field], field
    assert db.execute("SELECT COUNT(*) FROM maxfi_ledger_positions").fetchone()[0] == 3
    assert db.execute("SELECT COUNT(*) FROM maxfi_ledger_reward_claims").fetchone()[0] == 0


def test_pinned_pricing_maps_keep_their_exact_keys(client, db, monkeypatch):
    _install(monkeypatch, _fx())
    body = _post(client, f"{BACKFILL_URL}?dry_run=true")
    assert set(body["pricing_deferred"]) == {"basis", "exit", "claim"}
    assert set(body["pricing_carried_forward"]) == {"basis", "exit", "pool_address", "claim"}
    assert set(body["chunk_stats"]) == {"pass1_vault", "pass1_snuggle_rebalanced", "pass2_staking_manager", "receipts"}
    assert body["pricing_calls_used"] == 0  # emissions spend is reported inside emissions only


def test_emissions_pricing_defers_once_the_remaining_budget_is_spent(client, db, monkeypatch):
    seen = _install(monkeypatch, _fx())
    em = _post(client, f"{BACKFILL_URL}?dry_run=true&max_pricing_calls=1")["emissions"]
    assert em["pricing"]["budget_available"] == 1
    assert (em["pricing"]["priced"], em["pricing"]["deferred"], em["pricing"]["calls_used"]) == (1, 2, 3)
    assert len(seen) == 1
    assert em["summary"]["unpriced"] == 2
    assert em["summary"]["counted_totals"][AERO]["unpriced_keys"] == 2


def test_acceptance_counts_price_ages_over_24h(client, db, monkeypatch):
    fx = _fx()
    old_block = fx["txs"][0]["block_number"]
    _install(monkeypatch, fx, price_age_seconds=lambda b: 90_000 if b == old_block else 600)
    acc = _post(client, f"{BACKFILL_URL}?dry_run=true")["emissions"]["acceptance"]
    assert acc["max_price_age_seconds"] == 90_000 and acc["keys_over_24h"] == 1
    assert acc["price_age_limit_seconds"] == 86_400


def test_last_run_persists_the_emissions_section(client, db, monkeypatch):
    _install(monkeypatch, _fx())
    _post(client, f"{BACKFILL_URL}?dry_run=true")
    r = client.get(f"{BACKFILL_URL}/last-run")
    assert r.status_code == 200
    em = r.get_json()["emissions"]
    assert em["status"] == "ok" and em["keys_total"] == 3


def test_no_token_ids_means_no_emissions_rpc(client, db, monkeypatch):
    fx = _fx()
    _install(monkeypatch, fx)
    scan = _ledger_scan(fx)
    scan.update({"raw_logs": [], "token_ids": []})
    monkeypatch.setattr(mli, "scan_chain", lambda chain, wallets: scan)
    for name in ("eth_block_number", "eth_get_logs", "eth_get_transaction_receipt"):
        monkeypatch.setattr(mli, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError("no rpc")))
    em = _post(client, f"{BACKFILL_URL}?dry_run=true")["emissions"]
    assert em["status"] == "ok" and em["token_ids_scanned"] == 0 and em["keys_total"] == 0
    assert em["scan"]["rpc_calls"]["total"] == 0
