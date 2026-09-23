"""Emissions step 1 - read-only staking-reward diagnostic route
(GET /api/maxfi/ledger/diagnostics/rewards/<chain>) and its pure summarizer
_maxfi_ledger_rewards_summary. StakingManager logs come from the REAL
fixture page 0x2a9d8a6; every synthetic log builds its data words with
format(value, "064x") and its topics with encode_topic_uint256 /
encode_topic_address - never hand-typed hex."""
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

import maxfi_client
import maxfi_ledger_ingest as mli
import maxfi_ledger_pricing as mlp
import maxfi_schema
import src.storage.portfolio_db as portfolio_db

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "maxfi_ledger")

BASE_VAULT = mli.CHAINS["base"]["vault"]
BASE_SM = mli.CHAINS["base"]["staking_manager"]
CAKE = "0x3055913c90fcc1a6ce9a358911721eeb942013a1"
WALLET = "0xb502ec60fa723bce996ead192a39d204d97818ed"
OTHER_WALLET = "0x8fc4000000000000000000000000000000000001"
MASTERCHEF = "0xc6a2db661d5a5690172d8eb0a7dea2d3008665a3"
FIXTURE_TX = "0x05e6a1113258f96f376e353384c5651e0b133f7d385b8db129a3128f1d003231"
FIXTURE_BLOCK = "0x2a9d8a6"
FIXTURE_TS = "0x69de0e2f"

SRC = wp._REWARDS_TOPIC_STAKING_REWARDS_CLAIMED
PFC = wp._REWARDS_TOPIC_PERFORMANCE_FEE_COLLECTED
STAKED = wp._REWARDS_TOPIC_POSITION_STAKED
UNSTAKED = wp._REWARDS_TOPIC_POSITION_UNSTAKED


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
    uri = f"file:maxfi_ledger_rewards_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
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


@pytest.fixture(autouse=True)
def _clear_pricing_caches():
    mlp._POOL_TOKENS_CACHE.clear()
    mlp._DECIMALS_CACHE.clear()
    yield
    mlp._POOL_TOKENS_CACHE.clear()
    mlp._DECIMALS_CACHE.clear()


# ── synthetic log builders ------------------------------------------------

def _words(*values):
    return "0x" + "".join(format(v, "064x") for v in values)


def _log(address, topics, data="0x", tx=FIXTURE_TX, block=FIXTURE_BLOCK, log_index=0, ts=FIXTURE_TS):
    log = {
        "address": address, "topics": topics, "data": data,
        "blockNumber": block, "transactionHash": tx, "logIndex": hex(log_index),
    }
    if ts is not None:
        log["blockTimestamp"] = ts
    return log


def _vault_claim(token_id, owner, reward_token, amount, **kw):
    return _log(BASE_VAULT, [SRC, mli.encode_topic_uint256(token_id), mli.encode_topic_address(owner),
                             mli.encode_topic_address(reward_token)], _words(amount), **kw)


def _vault_fee(token_id, token, fee, treasury, referral, **kw):
    return _log(BASE_VAULT, [PFC, mli.encode_topic_uint256(token_id), mli.encode_topic_address(token)],
                _words(fee, treasury, referral), **kw)


def _sm_claim(token_id, owner_slot, reward_token, amount, **kw):
    return _log(BASE_SM, [SRC, mli.encode_topic_uint256(token_id), mli.encode_topic_address(owner_slot),
                          mli.encode_topic_address(reward_token)], _words(amount), **kw)


def _fixture_sm_logs():
    with open(os.path.join(FIXTURES, "base_staking_manager_page_0x2a9d8a6.json")) as fh:
        rows = json.load(fh)
    by_index = {r["logIndex"]: r for r in rows}
    return [by_index["0x85"], by_index["0x8d"], by_index["0xb0"]]


def _summary(vault_logs=(), sm_logs=(), positions=(), claims_rows=(), token_meta=None):
    return wp._maxfi_ledger_rewards_summary(
        "base", BASE_VAULT, list(vault_logs), list(sm_logs), list(positions), list(claims_rows), token_meta or {})


def _meta(decimals=18, symbol="CAKE"):
    return {"symbol": symbol, "symbol_error": None, "decimals": decimals, "decimals_error": None}


def _seed_position(db, token_id, owner, rebalanced_from=None, chain="base"):
    db.execute(
        "INSERT INTO maxfi_ledger_positions (chain, vault, npm, token_id, owner, rebalanced_from_token_id, computed_at) "
        "VALUES (?, ?, NULL, ?, ?, ?, '2026-09-23T00:00:00+00:00')",
        (chain, BASE_VAULT, str(token_id), owner, rebalanced_from),
    )
    db.commit()


# ── pure summarizer --------------------------------------------------------

def test_reward_topic_constants_pinned():
    assert SRC == "0xe6d1ff392bdc1cf53105ebfcb0e3f7b024a8b0915b1f131907da7a9f84f52b86"
    assert PFC == "0x55ffbf9681080527dff42e69485eb3b96f061a1d0c61f43b4dfcc59263b5c5b0"
    assert STAKED == "0x627009b4f6918ee0f41065d4adffdb5142a9ef54c66cc350bb8396c1c82a409c"
    assert UNSTAKED == "0xdd8df9cdfbfa0633e022e142f0da49c4cb7f22a3cf1c8a632425282652aefeff"


def test_summary_real_sm_fixture_with_synthetic_vault_logs():
    vault_logs = [
        _vault_claim(1916844, WALLET, CAKE, 505283128181122, log_index=0x80),
        _vault_fee(1916844, CAKE, 89167610855491, 89167610855491, 0, log_index=0x81),
    ]
    positions = [
        {"token_id": "1916844", "owner": WALLET, "rebalanced_from_token_id": None},
        {"token_id": "1917295", "owner": WALLET, "rebalanced_from_token_id": "1916844"},
    ]
    out = _summary(vault_logs, _fixture_sm_logs(), positions, token_meta={CAKE: _meta(18)})

    claims = out["claims"]
    assert claims["count"] == 1
    assert claims["owner_matched"] == 1
    assert claims["distinct_lineages"] == 1
    assert claims["by_lineage"][0]["root_token_id"] == "1916844"
    tok = claims["by_reward_token"][0]
    assert tok["total_amount_wei"] == "505283128181122"
    assert tok["total_amount"] == 505283128181122 / 1e18

    split = out["split"]
    assert split["joined"] == 1
    assert split["vault_plus_fee_equals_sm"] == 1
    assert split["fee_equals_treasury_plus_referral"] == 1
    assert split["fee_share_bps"] == {"min": 1500.0, "median": 1500.0, "max": 1500.0}

    assert out["sm_claims"]["owner_slot_values"] == {BASE_VAULT: 1}
    assert out["staking"]["staked_events"] == 1
    assert out["staking"]["unstaked_events"] == 1
    assert out["staking"]["staking_contracts"] == {MASTERCHEF: 2}
    assert out["samples"][0]["block_at"] == "2026-04-14T09:51:43+00:00"
    assert out["samples"][0]["block_number"] == 44685478


def test_summary_owner_mismatch_excluded_from_totals():
    positions = [{"token_id": "1916844", "owner": WALLET, "rebalanced_from_token_id": None}]
    out = _summary([_vault_claim(1916844, OTHER_WALLET, CAKE, 1000)], positions=positions,
                   token_meta={CAKE: _meta(18)})
    claims = out["claims"]
    assert claims["owner_mismatch"] == 1
    assert claims["owner_matched"] == 0
    assert claims["by_reward_token"] == []
    assert claims["owner_mismatch_sample"][0]["owner_slot"] == OTHER_WALLET
    assert claims["owner_mismatch_sample"][0]["expected_owner"] == WALLET


def test_summary_unpaired_counts():
    positions = [{"token_id": "7", "owner": WALLET, "rebalanced_from_token_id": None}]
    out = _summary(
        vault_logs=[_vault_fee(7, CAKE, 300, 300, 0, log_index=1)],
        sm_logs=[_sm_claim(7, BASE_VAULT, CAKE, 2000, log_index=2)],
        positions=positions,
    )
    assert out["split"]["unpaired"]["sm_claim_without_vault_claim"] == 1
    assert out["split"]["unpaired"]["fee_without_vault_claim"] == 1
    assert out["split"]["joined"] == 0


def test_summary_claims_key_collision():
    tx_a = "0x" + format(0xA, "064x")
    tx_b = "0x" + format(0xB, "064x")
    positions = [
        {"token_id": "11", "owner": WALLET, "rebalanced_from_token_id": None},
        {"token_id": "12", "owner": WALLET, "rebalanced_from_token_id": None},
    ]
    claims_rows = [
        {"tx_hash": tx_a, "token_id": "11", "claimed_price_source": "zero_net"},
        {"tx_hash": tx_b, "token_id": "12", "claimed_price_source": "swap_log"},
    ]
    out = _summary(
        [_vault_claim(11, WALLET, CAKE, 5, tx=tx_a), _vault_claim(12, WALLET, CAKE, 6, tx=tx_b)],
        positions=positions, claims_rows=claims_rows,
    )
    assert out["claims_key_collision"] == {
        "vault_claims_with_existing_claims_row": 2,
        "of_which_zero_net": 1,
        "of_which_non_zero": 1,
    }


def test_summary_large_amount_is_exact_string():
    positions = [{"token_id": "21", "owner": WALLET, "rebalanced_from_token_id": None}]
    out = _summary([_vault_claim(21, WALLET, CAKE, 215760000000000000000)], positions=positions,
                   token_meta={CAKE: _meta(18)})
    tok = out["claims"]["by_reward_token"][0]
    assert tok["total_amount_wei"] == "215760000000000000000"
    assert tok["total_amount"] == 215.76


def test_summary_lineage_cycle_guard():
    positions = [
        {"token_id": "31", "owner": WALLET, "rebalanced_from_token_id": "32"},
        {"token_id": "32", "owner": WALLET, "rebalanced_from_token_id": "31"},
    ]
    out = _summary([_vault_claim(31, WALLET, CAKE, 1)], positions=positions)
    assert out["lineage_cycles"] == 1
    assert out["claims"]["distinct_lineages"] == 1


# ── route ------------------------------------------------------------------

def test_route_invalid_chain_400(client, db):
    resp = client.get("/api/maxfi/ledger/diagnostics/rewards/nope")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "InvalidChain"
    assert "detail" in body
    assert body["valid_chains"] == sorted(wp.MAXFI_CHAINS)


def test_route_empty_ledger_zero_rpc(client, db, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("no RPC on an empty ledger")

    monkeypatch.setattr(mli, "scan_logs_chunked", _boom)
    monkeypatch.setattr(mli, "eth_block_number", _boom)
    resp = client.get("/api/maxfi/ledger/diagnostics/rewards/base")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["claims"]["count"] == 0
    assert body["rpc_calls"] == {"log_calls": 0, "eth_calls": 0}


def _fake_eth_call(symbol_fails=False):
    def fake(chain, to_address, data_hex, timeout=30):
        if data_hex.startswith(maxfi_client.SEL_ERC20_SYMBOL):
            if symbol_fails:
                raise mli.MaxFiRpcError("symbol boom")
            body = "CAKE".encode().hex().ljust(64, "0")
            return "0x" + format(32, "064x") + format(4, "064x") + body
        if data_hex.startswith(mlp.SEL_ERC20_DECIMALS):
            return "0x" + format(18, "064x")
        raise AssertionError(f"unexpected eth_call {data_hex}")
    return fake


def _install_scan(monkeypatch, calls, vault_logs, sm_logs):
    def fake_scan(chain, address, topics, from_block, to_block, chunk_size=None):
        calls.append({"address": address, "topics": topics})
        stats = {"calls": 1, "chunk_halvings": 0, "retries_429": 0, "final_chunk_size": 10000}
        if address == BASE_VAULT:
            return vault_logs, stats
        if address == BASE_SM:
            return sm_logs, stats
        raise AssertionError(f"unexpected address {address}")

    monkeypatch.setattr(mli, "eth_block_number", lambda chain, timeout=30: 50_000_000)
    monkeypatch.setattr(mli, "scan_logs_chunked", fake_scan)


def test_route_happy_path_filters_and_shape(client, db, monkeypatch):
    _seed_position(db, 1917295, WALLET, rebalanced_from="1916844")
    _seed_position(db, 1916844, WALLET)
    calls = []
    vault_logs = [
        _vault_claim(1916844, WALLET, CAKE, 505283128181122, log_index=0x80),
        _vault_fee(1916844, CAKE, 89167610855491, 89167610855491, 0, log_index=0x81),
    ]
    _install_scan(monkeypatch, calls, vault_logs, _fixture_sm_logs())
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call())

    resp = client.get("/api/maxfi/ledger/diagnostics/rewards/base")
    assert resp.status_code == 200
    body = resp.get_json()

    token_topics = [mli.encode_topic_uint256(t) for t in sorted(["1917295", "1916844"], key=int)]
    by_address = {c["address"]: c["topics"] for c in calls}
    assert by_address[BASE_VAULT] == [[SRC, PFC], token_topics]
    assert by_address[BASE_SM] == [[SRC, STAKED, UNSTAKED], token_topics]
    assert body["rpc_calls"]["log_calls"] == 2
    for key in ("chain", "token_ids_scanned", "caveat", "claims", "split", "sm_claims", "staking",
                "claims_key_collision", "samples", "ignored_logs", "lineage_cycles", "chunk_stats", "rpc_calls"):
        assert key in body, key
    assert set(body["chunk_stats"]) == {"vault_rewards", "staking_manager_rewards"}


def test_route_rpc_failure_returns_502_json(client, db, monkeypatch):
    _seed_position(db, 1916844, WALLET)

    def fake_scan(chain, address, topics, from_block, to_block, chunk_size=None):
        if address == BASE_VAULT:
            raise mli.MaxFiRpcError("vault getLogs boom")
        return [], {"calls": 1}

    monkeypatch.setattr(mli, "eth_block_number", lambda chain, timeout=30: 50_000_000)
    monkeypatch.setattr(mli, "scan_logs_chunked", fake_scan)
    resp = client.get("/api/maxfi/ledger/diagnostics/rewards/base")
    assert resp.status_code == 502
    body = resp.get_json()
    assert body["error"] == "rpc_error"
    assert body["pass"] == "vault_rewards"


def test_route_symbol_failure_is_soft(client, db, monkeypatch):
    _seed_position(db, 1916844, WALLET)
    calls = []
    _install_scan(monkeypatch, calls, [_vault_claim(1916844, WALLET, CAKE, 1000)], [])
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call(symbol_fails=True))

    resp = client.get("/api/maxfi/ledger/diagnostics/rewards/base")
    assert resp.status_code == 200
    tok = resp.get_json()["claims"]["by_reward_token"][0]
    assert tok["reward_token"] == CAKE
    assert tok["symbol"] is None
    assert tok["symbol_error"].startswith("rpc_error")
