"""Route-level tests for LP Advisor Phase B, commit 1 (B1): POST
/api/maxfi/catalogue-refresh/<chain> - the write-path sibling of the A1.6
read-only catalogue probe (tests/test_maxfi_pooldata.py). Same
client/monkeypatch fixture pattern as that file and
tests/test_maxfi_claims_routes.py; same shared-cache sqlite URI pattern as
tests/test_maxfi_valuation_route.py:308, since the route opens and closes
its OWN connection per call.

No network - every maxfi_client call the route makes (get_vault,
get_npm_balance_of, enumerate_owner_token_ids, decode_positions_and_pools,
multicall3_soft) is monkeypatched.
"""
import sqlite3
import uuid

import pytest

import maxfi_client
import maxfi_schema
import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


@pytest.fixture
def catalogue_db(monkeypatch):
    uri = f"file:maxfi_catalogue_refresh_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
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


_VAULT = "0x9999999999999999999999999999999999999999"


def _symbol_word(s):
    return s.encode().hex().ljust(64, '0')


def _catalogue_rows(db, chain="base"):
    return {
        row["pool_address"]: dict(row)
        for row in db.execute(
            "SELECT * FROM maxfi_catalogue_pools WHERE chain = ?", (chain,)
        ).fetchall()
    }


def _stub_two_pools(monkeypatch, position_count_1=2, position_count_2=1,
                     mixed_case=False, chain_positions=None):
    """Stubs a 3-position enumeration decoding to two distinct pools
    (2 positions in pool A, 1 in pool B), mirroring the A1.6 probe's own
    happy-path fixture shape. mixed_case=True returns addresses in mixed
    case to prove the route lowercases on write."""
    monkeypatch.setattr(maxfi_client, "get_vault", lambda chain: (_VAULT, []))
    monkeypatch.setattr(maxfi_client, "get_npm_balance_of", lambda chain, owner: 3)
    monkeypatch.setattr(
        maxfi_client, "enumerate_owner_token_ids",
        lambda chain, owner, count, chunk_size=None: ([1, 2, 3], 0),
    )

    if mixed_case:
        pool_a, pool_b = "0xPoolA", "0xPoolB"
        tok_a, tok_b, tok_c, tok_d = "0xTokA", "0xTokB", "0xTokC", "0xTokD"
    else:
        pool_a, pool_b = "0xpoola", "0xpoolb"
        tok_a, tok_b, tok_c, tok_d = "0xtoka", "0xtokb", "0xtokc", "0xtokd"

    decoded = (
        [{"token_id": "1", "pool_address": pool_a, "token0_address": tok_a,
          "token1_address": tok_b, "fee_tier": 3000}] * position_count_1
        + [{"token_id": "3", "pool_address": pool_b, "token0_address": tok_c,
            "token1_address": tok_d, "fee_tier": 500}] * position_count_2
    )
    monkeypatch.setattr(
        maxfi_client, "decode_positions_and_pools",
        lambda chain, token_ids, chunk_size=None: decoded,
    )

    symbols = {tok_a: "TOKA", tok_b: "TOKB", tok_c: "TOKC", tok_d: "TOKD"}

    def _fake_multicall3_soft(chain, calls, chunk_size=None):
        return [(True, "0x" + _symbol_word(symbols[addr])) for addr, _cd in calls]
    monkeypatch.setattr(maxfi_client, "multicall3_soft", _fake_multicall3_soft)

    return pool_a.lower(), pool_b.lower()


# ── fresh insert ─────────────────────────────────────────────────────────

def test_fresh_insert_lowercases_addresses_and_stamps_matching_timestamps(client, catalogue_db, monkeypatch):
    pool_a, pool_b = _stub_two_pools(monkeypatch, mixed_case=True)

    r = client.post("/api/maxfi/catalogue-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["premise_holds"] is True
    assert body["distinct_pools"] == 2
    assert body["distinct_tokens"] == 4
    assert body["inserted"] == 2
    assert body["updated"] == 0
    assert body["dry_run"] is False

    rows = _catalogue_rows(catalogue_db)
    assert set(rows.keys()) == {pool_a, pool_b}
    row_a = rows[pool_a]
    # Stored lowercased even though the monkeypatched decode returned
    # mixed-case addresses.
    assert row_a["token0_address"] == "0xtoka"
    assert row_a["token1_address"] == "0xtokb"
    assert row_a["token0_symbol"] == "TOKA"
    assert row_a["position_count"] == 2
    assert row_a["first_seen_at"] == row_a["last_seen_at"] == row_a["last_enumerated_at"] == body["run_at"]


# ── re-run UPSERT preserves first_seen_at (pinned invariant) ────────────

def test_catalogue_refresh_upsert_keeps_first_seen_at(client, catalogue_db, monkeypatch):
    pool_a, pool_b = _stub_two_pools(monkeypatch, position_count_1=2, position_count_2=1)

    r1 = client.post("/api/maxfi/catalogue-refresh/base")
    assert r1.status_code == 200
    first_seen_at_before = _catalogue_rows(catalogue_db)[pool_a]["first_seen_at"]

    # Second run: same pools but different position_count/symbols.
    monkeypatch.setattr(
        maxfi_client, "enumerate_owner_token_ids",
        lambda chain, owner, count, chunk_size=None: ([1, 2, 3, 4], 0),
    )
    monkeypatch.setattr(
        maxfi_client, "decode_positions_and_pools",
        lambda chain, token_ids, chunk_size=None: (
            [{"token_id": "1", "pool_address": pool_a, "token0_address": "0xtoka",
              "token1_address": "0xtokb", "fee_tier": 3000}] * 3
            + [{"token_id": "3", "pool_address": pool_b, "token0_address": "0xtokc",
                "token1_address": "0xtokd", "fee_tier": 500}] * 1
        ),
    )
    symbols2 = {"0xtoka": "NEWA", "0xtokb": "NEWB", "0xtokc": "TOKC", "0xtokd": "TOKD"}

    def _fake_multicall3_soft2(chain, calls, chunk_size=None):
        return [(True, "0x" + _symbol_word(symbols2[addr])) for addr, _cd in calls]
    monkeypatch.setattr(maxfi_client, "multicall3_soft", _fake_multicall3_soft2)

    r2 = client.post("/api/maxfi/catalogue-refresh/base")
    assert r2.status_code == 200
    body2 = r2.get_json()
    assert body2["inserted"] == 0
    assert body2["updated"] == 2

    rows_after = _catalogue_rows(catalogue_db)
    row_a_after = rows_after[pool_a]
    assert row_a_after["position_count"] == 3
    assert row_a_after["token0_symbol"] == "NEWA"
    assert row_a_after["token1_symbol"] == "NEWB"
    assert row_a_after["last_seen_at"] == body2["run_at"]
    assert row_a_after["last_enumerated_at"] == body2["run_at"]
    # The pinned invariant: first_seen_at is INSERT-only, never touched by
    # the ON CONFLICT UPDATE branch.
    assert row_a_after["first_seen_at"] == first_seen_at_before
    assert row_a_after["first_seen_at"] != body2["run_at"]


# ── dry_run ──────────────────────────────────────────────────────────────

def test_dry_run_true_writes_nothing_and_reports_would_insert(client, catalogue_db, monkeypatch):
    _stub_two_pools(monkeypatch)

    r = client.post("/api/maxfi/catalogue-refresh/base?dry_run=true")
    assert r.status_code == 200
    body = r.get_json()

    assert body["dry_run"] is True
    assert body["would_insert"] == 2
    assert body["would_update"] == 0
    assert "inserted" not in body
    assert "updated" not in body
    assert _catalogue_rows(catalogue_db) == {}


def test_dry_run_string_one_is_treated_as_a_real_run(client, catalogue_db, monkeypatch):
    # Pins the exact-'true' convention against the 8eb2458 defect class:
    # dry_run='1' must NOT be treated as a dry run.
    _stub_two_pools(monkeypatch)

    r = client.post("/api/maxfi/catalogue-refresh/base?dry_run=1")
    assert r.status_code == 200
    body = r.get_json()

    assert body["dry_run"] is False
    assert body["inserted"] == 2
    assert len(_catalogue_rows(catalogue_db)) == 2


# ── vault balance zero ───────────────────────────────────────────────────

def test_vault_balance_zero_premise_holds_false_no_writes(client, catalogue_db, monkeypatch):
    monkeypatch.setattr(maxfi_client, "get_vault", lambda chain: (_VAULT, []))
    monkeypatch.setattr(maxfi_client, "get_npm_balance_of", lambda chain, owner: 0)

    def _boom(*a, **k):
        raise AssertionError("must not enumerate when balance is 0")
    monkeypatch.setattr(maxfi_client, "enumerate_owner_token_ids", _boom)

    r = client.post("/api/maxfi/catalogue-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["premise_holds"] is False
    assert body["npm_position_count"] == 0
    assert body["vault_address"] == _VAULT
    assert "note" in body
    assert _catalogue_rows(catalogue_db) == {}


# ── invalid chain ────────────────────────────────────────────────────────

def test_invalid_chain_returns_400(client, catalogue_db):
    r = client.post("/api/maxfi/catalogue-refresh/not-a-real-chain")
    assert r.status_code == 400
    body = r.get_json()
    assert body["error"] == "InvalidChain"
    assert "valid_chains" in body


# ── max_positions truncation ─────────────────────────────────────────────

def test_max_positions_smaller_than_total_truncates_enumeration(client, catalogue_db, monkeypatch):
    monkeypatch.setattr(maxfi_client, "get_vault", lambda chain: (_VAULT, []))
    monkeypatch.setattr(maxfi_client, "get_npm_balance_of", lambda chain, owner: 5)

    captured = {}

    def _fake_enumerate(chain, owner, count, chunk_size=None):
        captured["count"] = count
        return ([1], 0)
    monkeypatch.setattr(maxfi_client, "enumerate_owner_token_ids", _fake_enumerate)
    monkeypatch.setattr(
        maxfi_client, "decode_positions_and_pools",
        lambda chain, token_ids, chunk_size=None: [
            {"token_id": "1", "pool_address": "0xpoola", "token0_address": "0xtoka",
             "token1_address": "0xtokb", "fee_tier": 3000},
        ],
    )
    monkeypatch.setattr(
        maxfi_client, "multicall3_soft",
        lambda chain, calls, chunk_size=None: [(True, "0x" + _symbol_word("X")) for _ in calls],
    )

    r = client.post("/api/maxfi/catalogue-refresh/base?max_positions=1")
    assert r.status_code == 200
    body = r.get_json()

    assert captured["count"] == 1
    assert body["enumerated_count"] == 1
    assert body["truncated"] is True
    assert body["npm_position_count"] == 5
