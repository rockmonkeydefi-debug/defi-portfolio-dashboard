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

def _pair(base, price, liq, chain="base", vol=0):
    """DexScreener pair fixture: `base` is the baseToken address."""
    return {"chainId": chain, "baseToken": {"address": base},
            "quoteToken": {"address": "0x" + "q" * 40},
            "priceUsd": price, "liquidity": {"usd": liq}, "volume": {"h24": vol}}


def test_dexscreener_parse_picks_highest_liquidity_pair():
    payload = {"pairs": [
        _pair(PLAZM, "1.00", 5000),
        _pair(PLAZM, "1.25", 90000),  # deepest base-side -> wins
        _pair(PLAZM, "0.90", 42000),
    ]}
    assert wp.parse_dexscreener_price(payload, PLAZM, "base") == 1.25


def test_dexscreener_parse_no_pairs_returns_none():
    assert wp.parse_dexscreener_price({"pairs": []}, PLAZM, "base") is None
    assert wp.parse_dexscreener_price({}, PLAZM, "base") is None


def test_dexscreener_parse_skips_pairs_without_price():
    no_price = _pair(PLAZM, None, 100000)
    del no_price["priceUsd"]
    payload = {"pairs": [no_price, _pair(PLAZM, "2.5", 10)]}
    assert wp.parse_dexscreener_price(payload, PLAZM, "base") == 2.5


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
    monkeypatch.setattr(wp, "fetch_dexscreener_price", lambda contract, chain=None, _now=None: 2.0)

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
    monkeypatch.setattr(wp, "fetch_dexscreener_price", lambda contract, chain=None, _now=None: None)
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
    monkeypatch.setattr(wp, "fetch_dexscreener_price", lambda contract, chain=None, _now=None: 1.0)
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
    monkeypatch.setattr(wp, "fetch_dexscreener_price", lambda contract, chain=None, _now=None: 1.0)
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
            return {"pairs": [_pair(PLAZM, "3.0", 100)]}

    monkeypatch.setattr(wp.requests, "get", lambda *a, **k: FakeResp())

    p1 = wp.fetch_dexscreener_price(PLAZM, "base", _now=1000.0)
    p2 = wp.fetch_dexscreener_price(PLAZM, "base", _now=1100.0)   # within 5 min -> cached
    assert p1 == 3.0 and p2 == 3.0
    assert calls["n"] == 1

    p3 = wp.fetch_dexscreener_price(PLAZM, "base", _now=2000.0)   # >5 min -> refetch
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
    monkeypatch.setattr(wp, "fetch_dexscreener_price", lambda contract, chain=None, _now=None: 1.0)
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
    """Fresh hits skip RPC; an expired entry is served stale while a background
    refresh re-reads it (serve-stale-while-refreshing)."""
    import time as _t
    calls = {"n": 0}

    def _fetch(chain, contract, wallet, decimals):
        calls["n"] += 1
        return 7.0 if calls["n"] == 1 else 9.0
    monkeypatch.setattr(wp, "fetch_erc20_balance", _fetch)

    b1 = wp.fetch_erc20_balance_cached("base", PLAZM, WALLET, 18, _now=1000.0)
    b2 = wp.fetch_erc20_balance_cached("base", PLAZM, WALLET, 18, _now=1200.0)  # within TTL
    assert b1 == 7.0 and b2 == 7.0
    assert calls["n"] == 1  # cached, no second RPC

    # TTL expired: the STALE value returns immediately (request never blocks)...
    b3 = wp.fetch_erc20_balance_cached("base", PLAZM, WALLET, 18, _now=2000.0)
    assert b3 == 7.0

    # ...and a background refresh lands the fresh value in the cache.
    for _ in range(100):
        key = ("base", PLAZM.lower(), WALLET.lower())
        if wp._custom_balance_cache[key][0] == 9.0:
            break
        _t.sleep(0.02)
    assert calls["n"] == 2
    assert wp._custom_balance_cache[("base", PLAZM.lower(), WALLET.lower())][0] == 9.0


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
                        lambda contract, chain=None, _now=None: 2.0 if contract == PLAZM else 0.5)
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


# ── Regression: balances vanished after the fast-mutations restructure ────────
# Root causes: (1) a raising worker propagated out of build_custom_token_rows
# and the merge wrapper silently dropped ALL custom rows; (2) caught per-call
# failures were written as balance 0.0 (indistinguishable from a real zero);
# (3) a dead RPC returned 0.0 which the balance cache stored as a success.

def test_failed_balance_read_yields_null_row_not_zero_and_not_cached(monkeypatch):
    _seed()
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [WALLET])
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {WALLET: {"label": "Main"}})
    monkeypatch.setattr(wp, "custom_token_chain_supported", lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_dexscreener_price", lambda contract, chain=None, _now=None: 2.0)

    def _raise(chain, contract, wallet, decimals):
        raise Exception("HTTP 429 Too Many Requests")
    monkeypatch.setattr(wp, "fetch_erc20_balance", _raise)

    rows = wp.build_custom_token_rows()
    assert len(rows) == 1              # row retained, never dropped
    row = rows[0]
    assert row["balance"] is None      # '—' in the UI — NOT 0
    assert row["balance_failed"] is True
    assert row["is_zero_balance"] is False
    assert row["value_usd"] == 0.0
    assert wp._custom_balance_cache == {}  # failure not cached


def test_balance_failure_then_success_recovers(monkeypatch):
    _seed()
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [WALLET])
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {WALLET: {"label": "Main"}})
    monkeypatch.setattr(wp, "custom_token_chain_supported", lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_dexscreener_price", lambda contract, chain=None, _now=None: 2.0)

    state = {"fail": True}
    def _flaky(chain, contract, wallet, decimals):
        if state["fail"]:
            raise Exception("transient RPC outage")
        return 5.0
    monkeypatch.setattr(wp, "fetch_erc20_balance", _flaky)

    rows1 = wp.build_custom_token_rows()
    assert rows1[0]["balance"] is None and rows1[0]["balance_failed"] is True

    state["fail"] = False              # RPC recovers
    rows2 = wp.build_custom_token_rows()
    assert rows2[0]["balance"] == 5.0  # no poisoned cache entry served
    assert rows2[0]["balance_failed"] is False
    assert rows2[0]["value_usd"] == 10.0


def test_worker_exception_does_not_drop_rows(monkeypatch):
    """An unexpected raise in a pool worker degrades that value, never the build.

    Before the fix, one raising worker propagated out of build_custom_token_rows
    and get_portfolio_data's merge wrapper silently dropped every custom row.
    """
    _seed()
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [WALLET])
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {WALLET: {"label": "Main"}})
    monkeypatch.setattr(wp, "custom_token_chain_supported", lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_erc20_balance",
                        lambda chain, contract, wallet, decimals: 3.0)

    def _boom(contract, _now=None):
        raise RuntimeError("unexpected worker error")
    monkeypatch.setattr(wp, "fetch_dexscreener_price", _boom)

    rows = wp.build_custom_token_rows()   # must not raise
    assert len(rows) == 1
    assert rows[0]["balance"] == 3.0      # balance survives the price worker dying
    assert rows[0]["price_usd"] is None   # degraded value renders '—'

    # And the merge keeps the rows too.
    merged = wp.merge_custom_tokens([])
    assert len(merged) == 1


def test_dead_rpc_raises_and_is_not_cached_as_zero(monkeypatch):
    """get_web3 -> None must raise, not return a cacheable 0.0."""
    monkeypatch.setattr("src.models.get_web3", lambda chain: None)
    with pytest.raises(ValueError):
        wp.fetch_erc20_balance("base", PLAZM, WALLET, 18)
    with pytest.raises(ValueError):
        wp.fetch_erc20_balance_cached("base", PLAZM, WALLET, 18, _now=1000.0)
    assert wp._custom_balance_cache == {}  # nothing poisoned


def test_unresolved_pending_row_flagged_and_retried(monkeypatch):
    """Metadata that keeps failing: row still emitted, flagged, retried next build."""
    conn = get_connection()
    conn.execute("INSERT INTO custom_tokens (chain, contract, symbol, decimals, added_at) "
                 "VALUES (?,?,?,?,?)", ("base", PLAZM, "pending", None, "2026-01-01T00:00:00"))
    conn.commit()
    conn.close()

    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [WALLET])
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {WALLET: {"label": "Main"}})
    monkeypatch.setattr(wp, "custom_token_chain_supported", lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_dexscreener_price", lambda contract, chain=None, _now=None: 1.0)
    monkeypatch.setattr(wp, "fetch_erc20_balance",
                        lambda chain, contract, wallet, decimals: 2.0)

    meta_calls = {"n": 0}
    def _meta_fail(chain, contract):
        meta_calls["n"] += 1
        raise Exception("RPC down")
    monkeypatch.setattr(wp, "fetch_erc20_metadata", _meta_fail)

    rows1 = wp.build_custom_token_rows()
    assert rows1[0]["metadata_pending"] is True   # surfaced, not silent
    assert meta_calls["n"] == 1

    rows2 = wp.build_custom_token_rows()          # retried on the next build
    assert meta_calls["n"] == 2

    # RPC recovers -> resolution completes and persists.
    monkeypatch.setattr(wp, "fetch_erc20_metadata", lambda chain, contract: ("PLAZM", 6))
    rows3 = wp.build_custom_token_rows()
    assert rows3[0]["symbol"] == "PLAZM"
    assert rows3[0]["metadata_pending"] is False
    conn = get_connection()
    row = conn.execute("SELECT symbol, decimals FROM custom_tokens").fetchone()
    conn.close()
    assert row["symbol"] == "PLAZM" and row["decimals"] == 6


# ── Post-#73 regressions: 429 bursts + request-path placement ─────────────────

def test_429_then_retry_succeeds(monkeypatch):
    """A rate-limited balanceOf is retried once after backoff and succeeds."""
    monkeypatch.setattr(wp.time, "sleep", lambda s: None)  # skip real backoff
    calls = {"n": 0}

    def _raw(chain, contract, wallet):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("429 Client Error: Too Many Requests")
        return 5 * 10 ** 18
    monkeypatch.setattr(wp, "_balance_of_raw", _raw)

    assert wp.fetch_erc20_balance("base", PLAZM, WALLET, 18) == 5.0
    assert calls["n"] == 2  # one retry, then success


def test_non_rate_limit_error_not_retried(monkeypatch):
    monkeypatch.setattr(wp.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def _raw(chain, contract, wallet):
        calls["n"] += 1
        raise Exception("execution reverted")
    monkeypatch.setattr(wp, "_balance_of_raw", _raw)

    with pytest.raises(Exception):
        wp.fetch_erc20_balance("base", PLAZM, WALLET, 18)
    assert calls["n"] == 1  # no retry burned on a non-429 failure


def test_stale_serve_returns_immediately_and_refreshes(monkeypatch):
    """An expired cache entry is served instantly; the refresh happens off-path."""
    import time as _t
    key = ("base", PLAZM.lower(), WALLET.lower())
    wp._custom_balance_cache[key] = (7.0, 0.0)  # ancient entry

    started = _t.monotonic()
    calls = {"n": 0}

    def _slow_fetch(chain, contract, wallet, decimals):
        calls["n"] += 1
        _t.sleep(0.2)  # slow RPC — must NOT delay the caller
        return 9.0
    monkeypatch.setattr(wp, "fetch_erc20_balance", _slow_fetch)

    b = wp.fetch_erc20_balance_cached("base", PLAZM, WALLET, 18, _now=_t.time())
    elapsed = _t.monotonic() - started
    assert b == 7.0            # stale value served
    assert elapsed < 0.15      # without waiting on the 0.2s RPC

    for _ in range(100):       # background refresh lands
        if wp._custom_balance_cache[key][0] == 9.0:
            break
        _t.sleep(0.02)
    assert wp._custom_balance_cache[key][0] == 9.0
    assert calls["n"] == 1


def test_stale_refresh_deduped(monkeypatch):
    """Concurrent expired reads spawn at most one background refresh."""
    import time as _t
    key = ("base", PLAZM.lower(), WALLET.lower())
    wp._custom_balance_cache[key] = (7.0, 0.0)

    calls = {"n": 0}
    def _slow_fetch(chain, contract, wallet, decimals):
        calls["n"] += 1
        _t.sleep(0.15)
        return 9.0
    monkeypatch.setattr(wp, "fetch_erc20_balance", _slow_fetch)

    for _ in range(5):  # five requests hit the expired entry back-to-back
        assert wp.fetch_erc20_balance_cached("base", PLAZM, WALLET, 18, _now=_t.time()) == 7.0

    for _ in range(100):
        if wp._custom_balance_cache[key][0] == 9.0:
            break
        _t.sleep(0.02)
    assert calls["n"] == 1  # deduped: one in-flight refresh, not five


def test_add_mutation_keeps_cache_no_nuke(client, monkeypatch):
    """Adding a token must not invalidate the portfolio cache (that forced a
    full cold rebuild on the next page-land anywhere on the site)."""
    monkeypatch.setattr(wp, "custom_token_chain_supported",
                        lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_erc20_metadata",
                        lambda chain, contract: ("PLAZM", 18))

    sentinel = {"tokens": [{"symbol": "WETH", "value_usd": 100.0, "source": "zerion"}],
                "total_tokens_value": 100.0, "total_value": 100.0}
    wp._portfolio_cache = sentinel

    applied = {"n": 0}
    monkeypatch.setattr(wp, "_apply_custom_rows_to_cache",
                        lambda: applied.__setitem__("n", applied["n"] + 1))

    resp = client.post("/api/custom-tokens", json={"chain": "base", "contract": PLAZM})
    assert resp.status_code == 200
    assert wp._portfolio_cache is not None          # cache NOT nuked
    assert wp._portfolio_cache["tokens"][0]["symbol"] == "WETH"

    import time as _t
    for _ in range(100):                            # background merge was kicked off
        if applied["n"] == 1:
            break
        _t.sleep(0.02)
    assert applied["n"] == 1


def test_delete_mutation_surgical_cache_update_no_rpc(client, monkeypatch):
    """Deleting a token drops only its rows from the cached payload — no nuke,
    no rebuild, no RPC."""
    monkeypatch.setattr(wp, "custom_token_chain_supported",
                        lambda chain: (True, "BASE_RPC_URL"))
    monkeypatch.setattr(wp, "fetch_erc20_metadata",
                        lambda chain, contract: ("PLAZM", 18))
    tok_id = client.post("/api/custom-tokens",
                         json={"chain": "base", "contract": PLAZM}).get_json()["token"]["id"]

    def _boom(*a, **k):
        raise AssertionError("delete touched RPC/build")
    monkeypatch.setattr(wp, "build_custom_token_rows", _boom)
    monkeypatch.setattr(wp, "merge_custom_tokens", _boom)
    monkeypatch.setattr(wp, "fetch_erc20_balance", _boom)

    wp._portfolio_cache = {
        "tokens": [
            {"symbol": "WETH", "value_usd": 100.0, "source": "zerion"},
            {"symbol": "PLAZM", "value_usd": 40.0, "source": "custom",
             "custom_token_id": tok_id, "contract": PLAZM},
        ],
        "total_tokens_value": 140.0, "total_value": 150.0,
    }

    resp = client.delete(f"/api/custom-tokens/{tok_id}")
    assert resp.status_code == 200
    cache = wp._portfolio_cache
    assert cache is not None                                  # not nuked
    assert [t["symbol"] for t in cache["tokens"]] == ["WETH"]  # only custom row dropped
    assert cache["total_tokens_value"] == 100.0
    assert cache["total_value"] == 110.0                       # 150 - 40


def test_non_portfolio_routes_make_no_custom_token_calls(client, monkeypatch):
    """List/mutation routes never reach balance/price RPC synchronously."""
    def _boom(*a, **k):
        raise AssertionError("non-portfolio route performed custom-token RPC")
    monkeypatch.setattr(wp, "build_custom_token_rows", _boom)
    monkeypatch.setattr(wp, "fetch_erc20_balance", _boom)
    monkeypatch.setattr(wp, "fetch_erc20_balance_cached", _boom)
    monkeypatch.setattr(wp, "fetch_dexscreener_price", _boom)

    assert client.get("/api/custom-tokens").status_code == 200
    assert client.get("/api/wallets").status_code == 200
    assert client.get("/api/config").status_code == 200


# ── Pair selection: base-token-side on the right chain only (ESHARE fix) ──────
# /latest/dex/tokens/{addr} returns pairs where the token sits on EITHER side;
# priceUsd is always the BASE token's price. Max-liquidity selection therefore
# returned the OTHER token's price whenever a deep quote-side pool outranked
# the canonical base-side pair (ESHARE: $0.02 instead of ~$5.73).

ESHARE = "0xb7C10146bA1b618956a38605AB6496523d450871"


def _quote_side_pair(quote, price, liq, chain="base", vol=0):
    """Pair where the queried token is the QUOTE token — priceUsd is not its price."""
    return {"chainId": chain, "baseToken": {"address": "0x" + "b" * 40},
            "quoteToken": {"address": quote},
            "priceUsd": price, "liquidity": {"usd": liq}, "volume": {"h24": vol}}


def test_quote_side_only_response_returns_none():
    payload = {"pairs": [
        _quote_side_pair(ESHARE, "0.02", 240000),
        _quote_side_pair(ESHARE, "0.019", 90000),
    ]}
    assert wp.parse_dexscreener_price(payload, ESHARE, "base") is None


def test_mixed_response_picks_base_side_despite_lower_liquidity():
    """The ESHARE reproduction: deep quote-side pool must lose to the shallower
    base-side canonical pair."""
    payload = {"pairs": [
        _quote_side_pair(ESHARE, "0.02134", 240000),        # deep, wrong side
        _pair(ESHARE, "5.7312", 87000, vol=42000),          # canonical
    ]}
    assert wp.parse_dexscreener_price(payload, ESHARE, "base") == 5.7312


def test_wrong_chain_pairs_excluded():
    payload = {"pairs": [
        _pair(ESHARE, "0.50", 500000, chain="bsc"),   # same-address token elsewhere
        _pair(ESHARE, "5.73", 40000, chain="base"),
    ]}
    assert wp.parse_dexscreener_price(payload, ESHARE, "base") == 5.73
    # And if the token's chain has no pairs at all -> None, never cross-chain.
    assert wp.parse_dexscreener_price(
        {"pairs": [_pair(ESHARE, "0.50", 500000, chain="bsc")]}, ESHARE, "base") is None


def test_base_address_match_case_insensitive():
    payload = {"pairs": [_pair(ESHARE.upper().replace("0X", "0x"), "5.73", 1000)]}
    assert wp.parse_dexscreener_price(payload, ESHARE.lower(), "base") == 5.73


def test_liquidity_tie_broken_by_volume():
    payload = {"pairs": [
        _pair(ESHARE, "5.70", 50000, vol=1000),
        _pair(ESHARE, "5.75", 50000, vol=90000),  # same depth, more volume -> wins
    ]}
    assert wp.parse_dexscreener_price(payload, ESHARE, "base") == 5.75


def test_median_divergence_logged_not_rejected(capsys):
    """A >5x outlier chosen pair is logged for visibility but still returned."""
    payload = {"pairs": [
        _pair(ESHARE, "50.0", 90000),   # deepest -> chosen, but 10x the median
        _pair(ESHARE, "5.0", 100),
        _pair(ESHARE, "5.1", 200),
    ]}
    assert wp.parse_dexscreener_price(payload, ESHARE, "base") == 50.0
    out = capsys.readouterr().out
    assert "price sanity" in out and ">5x" in out


def test_no_divergence_no_log(capsys):
    payload = {"pairs": [
        _pair(ESHARE, "5.7", 90000),
        _pair(ESHARE, "5.6", 100),
    ]}
    assert wp.parse_dexscreener_price(payload, ESHARE, "base") == 5.7
    assert "price sanity" not in capsys.readouterr().out
