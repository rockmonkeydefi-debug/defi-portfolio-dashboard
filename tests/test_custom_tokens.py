"""Tests for user-added custom tokens on the holdings page.

Covers the add/list/remove route round-trip (RPC mocked), on-chain balance
scaling by decimals, DexScreener price parsing (highest-liquidity pair wins),
retention of missing-price rows with a null price, and duplicate-add rejection.

web_portfolio spawns a background scheduler on non-__main__ import; we neutralize
threading.Thread.start during import (established pattern) so no thread starts.
"""
import threading

import pytest

# ── Import web_portfolio import-safe (suppress scheduler autostart) ──
_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

from src.storage.portfolio_db import get_connection

# Real PLAZM-on-Base target from the feature spec.
PLAZM = "0xA1FBB38bF486b97108aA87E92008187CA06998f6"
WALLET = "0x1111111111111111111111111111111111111111"


@pytest.fixture(autouse=True)
def clean_custom_tokens():
    """Start each test with an empty custom_tokens table and clear caches."""
    conn = get_connection()
    conn.execute("DELETE FROM custom_tokens")
    conn.commit()
    conn.close()
    wp._dexscreener_price_cache.clear()
    wp._custom_balance_cache.clear()
    wp._portfolio_cache = None
    yield
    conn = get_connection()
    conn.execute("DELETE FROM custom_tokens")
    conn.commit()
    conn.close()


@pytest.fixture
def client(monkeypatch):
    """Authenticated Flask test client (auth bypassed via a stubbed password)."""
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


# ── DexScreener price parsing ────────────────────────────────────────────────

def test_dexscreener_parse_picks_highest_liquidity_pair():
    payload = {
        "pairs": [
            {"priceUsd": "1.00", "liquidity": {"usd": 5000}},
            {"priceUsd": "1.25", "liquidity": {"usd": 90000}},  # deepest -> wins
            {"priceUsd": "0.90", "liquidity": {"usd": 42000}},
        ]
    }
    assert wp.parse_dexscreener_price(payload) == 1.25


def test_dexscreener_parse_no_pairs_returns_none():
    assert wp.parse_dexscreener_price({"pairs": []}) is None
    assert wp.parse_dexscreener_price({}) is None


def test_dexscreener_parse_skips_pairs_without_price():
    payload = {"pairs": [
        {"liquidity": {"usd": 100000}},               # no priceUsd -> skipped
        {"priceUsd": "2.5", "liquidity": {"usd": 10}},
    ]}
    assert wp.parse_dexscreener_price(payload) == 2.5


# ── Add / list / remove round-trip (RPC mocked) ──────────────────────────────

def test_add_list_remove_roundtrip(client, monkeypatch):
    monkeypatch.setattr(wp, "custom_token_chain_supported",
                        lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_erc20_metadata",
                        lambda chain, contract: ("PLAZM", 18))

    # add
    resp = client.post("/api/custom-tokens",
                       json={"chain": "base", "contract": PLAZM})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["success"] is True
    assert body["token"]["symbol"] == "PLAZM"
    assert body["token"]["decimals"] == 18
    token_id = body["token"]["id"]

    # list
    resp = client.get("/api/custom-tokens")
    listed = resp.get_json()["tokens"]
    assert len(listed) == 1
    assert listed[0]["contract"] == PLAZM
    assert listed[0]["symbol"] == "PLAZM"

    # remove by id
    resp = client.delete(f"/api/custom-tokens/{token_id}")
    assert resp.status_code == 200
    assert client.get("/api/custom-tokens").get_json()["tokens"] == []


def test_remove_by_contract(client, monkeypatch):
    monkeypatch.setattr(wp, "custom_token_chain_supported",
                        lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_erc20_metadata",
                        lambda chain, contract: ("PLAZM", 18))
    client.post("/api/custom-tokens", json={"chain": "base", "contract": PLAZM})

    # case-insensitive contract delete
    resp = client.delete(f"/api/custom-tokens/{PLAZM.lower()}")
    assert resp.status_code == 200
    assert client.get("/api/custom-tokens").get_json()["tokens"] == []


def test_duplicate_add_rejected(client, monkeypatch):
    monkeypatch.setattr(wp, "custom_token_chain_supported",
                        lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_erc20_metadata",
                        lambda chain, contract: ("PLAZM", 18))
    first = client.post("/api/custom-tokens", json={"chain": "base", "contract": PLAZM})
    assert first.status_code == 200

    # same contract, different casing -> rejected (case-insensitive UNIQUE)
    dup = client.post("/api/custom-tokens",
                      json={"chain": "base", "contract": PLAZM.lower()})
    assert dup.status_code == 409
    assert "already" in dup.get_json()["error"].lower()
    assert len(client.get("/api/custom-tokens").get_json()["tokens"]) == 1


def test_add_rejects_bad_address(client, monkeypatch):
    monkeypatch.setattr(wp, "custom_token_chain_supported",
                        lambda chain: (True, "BASE_RPC_URL"))
    resp = client.post("/api/custom-tokens", json={"chain": "base", "contract": "0xnope"})
    assert resp.status_code == 400
    assert "invalid" in resp.get_json()["error"].lower()


def test_add_rejects_unsupported_chain(client, monkeypatch):
    # Chain valid but RPC missing -> names the required env var.
    monkeypatch.setattr(wp, "custom_token_chain_supported",
                        lambda chain: (False, "BASE_RPC_URL"))
    resp = client.post("/api/custom-tokens", json={"chain": "base", "contract": PLAZM})
    assert resp.status_code == 400
    assert "BASE_RPC_URL" in resp.get_json()["error"]


# ── Balance scaling + row building ───────────────────────────────────────────

def _seed(chain="base", contract=PLAZM, symbol="PLAZM", decimals=18):
    conn = get_connection()
    conn.execute(
        "INSERT INTO custom_tokens (chain, contract, symbol, decimals, added_at) "
        "VALUES (?,?,?,?,?)", (chain, contract, symbol, decimals, "2026-01-01T00:00:00"))
    conn.commit()
    conn.close()


def test_balance_scaled_by_decimals(monkeypatch):
    _seed(decimals=18)
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [WALLET])
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {WALLET: {"label": "Main"}})
    monkeypatch.setattr(wp, "custom_token_chain_supported", lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_dexscreener_price", lambda contract, _now=None: 2.0)

    # raw balanceOf of 5 * 10**18 -> 5.0 tokens
    def fake_balance(chain, contract, wallet, decimals):
        return (5 * 10 ** 18) / (10 ** decimals)
    monkeypatch.setattr(wp, "fetch_erc20_balance", fake_balance)

    rows = wp.build_custom_token_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["balance"] == 5.0
    assert row["price_usd"] == 2.0
    assert row["value_usd"] == 10.0
    assert row["source"] == "custom"
    assert row["is_zero_balance"] is False
    assert row["chain"] == "Base"


def test_missing_price_row_retained_with_null(monkeypatch):
    _seed(decimals=6)
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [WALLET])
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {WALLET: {"label": "Main"}})
    monkeypatch.setattr(wp, "custom_token_chain_supported", lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_dexscreener_price", lambda contract, _now=None: None)
    monkeypatch.setattr(wp, "fetch_erc20_balance",
                        lambda chain, contract, wallet, decimals: 1234.5)

    rows = wp.build_custom_token_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["price_usd"] is None       # null price -> UI shows '—'
    assert row["value_usd"] == 0.0
    assert row["balance"] == 1234.5       # balance still present, row not dropped


def test_zero_balance_row_flagged_and_kept(monkeypatch):
    _seed()
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [WALLET])
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {WALLET: {"label": "Main"}})
    monkeypatch.setattr(wp, "custom_token_chain_supported", lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_dexscreener_price", lambda contract, _now=None: 1.0)
    monkeypatch.setattr(wp, "fetch_erc20_balance",
                        lambda chain, contract, wallet, decimals: 0.0)

    rows = wp.build_custom_token_rows()
    assert len(rows) == 1
    assert rows[0]["is_zero_balance"] is True


def test_merge_dedupes_by_contract(monkeypatch):
    _seed()
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [WALLET])
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {WALLET: {"label": "Main"}})
    monkeypatch.setattr(wp, "custom_token_chain_supported", lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_dexscreener_price", lambda contract, _now=None: 1.0)
    monkeypatch.setattr(wp, "fetch_erc20_balance",
                        lambda chain, contract, wallet, decimals: 3.0)

    # Zerion already reports the same contract for the same wallet.
    zerion_rows = [{
        "chain": "Base", "symbol": "PLAZM", "balance": 3.0, "value_usd": 3.0,
        "price_usd": 1.0, "contract": PLAZM.lower(), "wallet": WALLET,
        "wallet_label": "Main",
    }]
    merged = wp.merge_custom_tokens(list(zerion_rows))

    # Zerion row dropped; only the custom row survives (no double count).
    assert len(merged) == 1
    assert merged[0]["source"] == "custom"


def test_dexscreener_price_cached(monkeypatch):
    calls = {"n": 0}

    class FakeResp:
        ok = True
        def json(self):
            calls["n"] += 1
            return {"pairs": [{"priceUsd": "3.0", "liquidity": {"usd": 100}}]}

    monkeypatch.setattr(wp.requests, "get", lambda *a, **k: FakeResp())

    p1 = wp.fetch_dexscreener_price(PLAZM, _now=1000.0)
    p2 = wp.fetch_dexscreener_price(PLAZM, _now=1100.0)   # within 5 min -> cached
    assert p1 == 3.0 and p2 == 3.0
    assert calls["n"] == 1

    p3 = wp.fetch_dexscreener_price(PLAZM, _now=2000.0)   # >5 min -> refetch
    assert p3 == 3.0
    assert calls["n"] == 2


# ── Performance restructure: fast mutations, balance cache, parallel fetch ────

def test_add_mutation_does_no_balance_or_price_calls(client, monkeypatch):
    """The add mutation must not touch balanceOf or DexScreener — only metadata."""
    monkeypatch.setattr(wp, "custom_token_chain_supported",
                        lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_erc20_metadata",
                        lambda chain, contract: ("PLAZM", 18))

    def _boom(*a, **k):  # any call here means the mutation did slow work
        raise AssertionError("mutation performed a balance/price fetch")
    monkeypatch.setattr(wp, "fetch_erc20_balance", _boom)
    monkeypatch.setattr(wp, "fetch_erc20_balance_cached", _boom)
    monkeypatch.setattr(wp, "fetch_dexscreener_price", _boom)
    monkeypatch.setattr(wp, "merge_custom_tokens", _boom)
    monkeypatch.setattr(wp, "build_custom_token_rows", _boom)

    resp = client.post("/api/custom-tokens", json={"chain": "base", "contract": PLAZM})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["pending"] is False


def test_delete_mutation_does_no_balance_or_price_calls(client, monkeypatch):
    monkeypatch.setattr(wp, "custom_token_chain_supported",
                        lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_erc20_metadata",
                        lambda chain, contract: ("PLAZM", 18))
    tok_id = client.post("/api/custom-tokens",
                         json={"chain": "base", "contract": PLAZM}).get_json()["token"]["id"]

    def _boom(*a, **k):
        raise AssertionError("delete performed a balance/price fetch")
    monkeypatch.setattr(wp, "fetch_erc20_balance", _boom)
    monkeypatch.setattr(wp, "fetch_erc20_balance_cached", _boom)
    monkeypatch.setattr(wp, "fetch_dexscreener_price", _boom)
    monkeypatch.setattr(wp, "build_custom_token_rows", _boom)

    resp = client.delete(f"/api/custom-tokens/{tok_id}")
    assert resp.status_code == 200


def test_add_slow_metadata_stored_pending(client, monkeypatch):
    """A slow RPC (metadata past the timeout) stores the token as 'pending'."""
    import time as _t
    monkeypatch.setattr(wp, "custom_token_chain_supported",
                        lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "_CUSTOM_METADATA_TIMEOUT", 0.1)

    def _slow(chain, contract):
        _t.sleep(0.5)
        return ("PLAZM", 18)
    monkeypatch.setattr(wp, "fetch_erc20_metadata", _slow)

    resp = client.post("/api/custom-tokens", json={"chain": "base", "contract": PLAZM})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["pending"] is True
    assert body["token"]["symbol"] == "pending"

    conn = get_connection()
    row = conn.execute("SELECT symbol, decimals FROM custom_tokens WHERE contract=?",
                       (PLAZM,)).fetchone()
    conn.close()
    assert row["symbol"] == "pending"
    assert row["decimals"] is None


def test_pending_metadata_resolved_during_build(monkeypatch):
    """build_custom_token_rows resolves 'pending' metadata and persists it."""
    conn = get_connection()
    conn.execute("INSERT INTO custom_tokens (chain, contract, symbol, decimals, added_at) "
                 "VALUES (?,?,?,?,?)", ("base", PLAZM, "pending", None, "2026-01-01T00:00:00"))
    conn.commit()
    conn.close()

    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [WALLET])
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {WALLET: {"label": "Main"}})
    monkeypatch.setattr(wp, "custom_token_chain_supported", lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_erc20_metadata", lambda chain, contract: ("PLAZM", 6))
    monkeypatch.setattr(wp, "fetch_dexscreener_price", lambda contract, _now=None: 1.0)
    monkeypatch.setattr(wp, "fetch_erc20_balance",
                        lambda chain, contract, wallet, decimals: 2.0)

    rows = wp.build_custom_token_rows()
    assert rows[0]["symbol"] == "PLAZM"

    # DB updated so the next build skips the metadata RPC.
    conn = get_connection()
    row = conn.execute("SELECT symbol, decimals FROM custom_tokens WHERE contract=?",
                       (PLAZM,)).fetchone()
    conn.close()
    assert row["symbol"] == "PLAZM" and row["decimals"] == 6


def test_balance_cache_ttl_respected(monkeypatch):
    calls = {"n": 0}

    def _fetch(chain, contract, wallet, decimals):
        calls["n"] += 1
        return 7.0
    monkeypatch.setattr(wp, "fetch_erc20_balance", _fetch)

    b1 = wp.fetch_erc20_balance_cached("base", PLAZM, WALLET, 18, _now=1000.0)
    b2 = wp.fetch_erc20_balance_cached("base", PLAZM, WALLET, 18, _now=1200.0)  # within TTL
    assert b1 == 7.0 and b2 == 7.0
    assert calls["n"] == 1  # cached, no second RPC

    b3 = wp.fetch_erc20_balance_cached("base", PLAZM, WALLET, 18, _now=2000.0)  # TTL expired
    assert b3 == 7.0
    assert calls["n"] == 2


def test_parallel_build_matches_serial_payload(monkeypatch):
    """The parallelized build produces the same rows a serial build would."""
    wallets = [
        "0x1111111111111111111111111111111111111111",
        "0x2222222222222222222222222222222222222222",
        "0x3333333333333333333333333333333333333333",
    ]
    other = "0xbBBBbBbbBbBBBbBbbbbbBBbBBbbbbBbBbbbBBBBb0"
    conn = get_connection()
    for c, s, d in [("base", PLAZM, 18), ("base", other, 6)]:
        conn.execute("INSERT INTO custom_tokens (chain, contract, symbol, decimals, added_at) "
                     "VALUES (?,?,?,?,?)", (c, s, s[:6], d, "2026-01-01T00:00:00"))
    conn.commit()
    conn.close()

    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: wallets)
    monkeypatch.setattr(wp, "load_wallet_config",
                        lambda: {w: {"label": f"W{i}"} for i, w in enumerate(wallets)})
    monkeypatch.setattr(wp, "custom_token_chain_supported", lambda chain: (True, "BASE_RPC_URL"))
    # Deterministic per-contract price and per-(contract,wallet) balance.
    monkeypatch.setattr(wp, "fetch_dexscreener_price",
                        lambda contract, _now=None: 2.0 if contract == PLAZM else 0.5)
    monkeypatch.setattr(wp, "fetch_erc20_balance",
                        lambda chain, contract, wallet, decimals: float(int(wallet[3], 16)))

    rows = wp.build_custom_token_rows()

    # Serial reference: same contracts x wallets, same math.
    def _norm(rs):
        return sorted((r["contract"], r["wallet"], r["balance"], r["price_usd"], r["value_usd"])
                      for r in rs)
    expected = []
    for contract, price in [(PLAZM, 2.0), (other, 0.5)]:
        for w in wallets:
            bal = float(int(w[3], 16))
            expected.append({"contract": contract, "wallet": w, "balance": bal,
                             "price_usd": price, "value_usd": bal * price})
    assert _norm(rows) == _norm(expected)
    assert len(rows) == len(wallets) * 2
