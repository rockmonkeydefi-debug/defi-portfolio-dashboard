"""Solana custom tokens (Landing 29, Oct 11).

Zerion leaves some Solana SPL tokens out (its spam filter, or not indexed
yet), so they go missing from Token Holdings and the portfolio total. Custom
tokens now take a Solana mint: decimals from getTokenSupply, the symbol from
DexScreener, the balance from getTokenAccountsByOwner (jsonParsed) for each
Solana wallet, priced by DexScreener like every custom token. SOLANA_RPC_URL
must be set (no public default).

Every Solana RPC and DexScreener call is faked; no network. Addresses are
synthetic base58 strings, never a real wallet.
"""
import re
import threading
import traceback

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

from src.storage.portfolio_db import get_connection

BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
MINT = "MintTokenXyz" + "2" * 30              # synthetic Solana mint (mixed case)
SOL_WALLET = "SynthWa11et" + "3" * 30          # synthetic Solana wallet
EVM_WALLET = "0x1111111111111111111111111111111111111111"
EVM_TOKEN = "0xA1FBB38bF486b97108aA87E92008187CA06998f6"
SECRET = "SECRETKEY123"
FAKE_URL = f"https://solana-mainnet.g.alchemy.com/v2/{SECRET}"


def test_synthetic_addresses_are_valid_base58():
    assert BASE58.match(MINT) and BASE58.match(SOL_WALLET)


@pytest.fixture(autouse=True)
def clean_custom_tokens():
    def _wipe():
        conn = get_connection()
        conn.execute("DELETE FROM custom_tokens")
        conn.execute("DELETE FROM custom_token_price_snapshot")
        conn.commit()
        conn.close()
    _wipe()
    wp._dexscreener_price_cache.clear()
    wp._custom_balance_cache.clear()
    wp._portfolio_cache = None
    yield
    _wipe()
    wp._dexscreener_price_cache.clear()
    wp._custom_balance_cache.clear()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _accounts(*amounts, mint=MINT, decimals=6):
    return {"context": {"slot": 1}, "value": [
        {"pubkey": f"Acct{i}", "account": {"data": {"parsed": {"info": {
            "mint": mint, "owner": SOL_WALLET,
            "tokenAmount": {"amount": str(a), "decimals": decimals}}}}}}
        for i, a in enumerate(amounts)]}


@pytest.fixture
def solana_rpc(monkeypatch):
    """Fake Solana RPC behind a configured URL. Set `responses[method]` to a
    result, an _Resp (sent as is), or a list of either (one per call)."""
    monkeypatch.setattr(wp, "_rpc_url_for_chain", lambda chain: FAKE_URL)
    state = {"responses": {"getTokenSupply": {"context": {"slot": 1},
                                              "value": {"amount": "1", "decimals": 6, "uiAmountString": "1"}},
                           "getTokenAccountsByOwner": _accounts(1_500_000)},
             "calls": []}

    def fake_post(url, json=None, timeout=None):
        assert url == FAKE_URL
        method = json["method"]
        state["calls"].append((method, json["params"]))
        r = state["responses"][method]
        if isinstance(r, list):
            r = r.pop(0)
        if isinstance(r, Exception):
            raise r
        if isinstance(r, _Resp):
            return r
        return _Resp(200, {"jsonrpc": "2.0", "id": 1, "result": r})
    monkeypatch.setattr(wp.requests, "post", fake_post)
    monkeypatch.setattr(wp.time, "sleep", lambda s: None)
    return state


def _dex_pairs(*pairs):
    return _Resp(200, {"pairs": list(pairs)})


def _pair(chain="solana", base=MINT, base_sym="MINI", quote="So11111111111111111111111111111111111111112",
          quote_sym="SOL", liq=1000.0, price="0.0026"):
    return {"chainId": chain, "baseToken": {"address": base, "symbol": base_sym},
            "quoteToken": {"address": quote, "symbol": quote_sym},
            "priceUsd": price, "liquidity": {"usd": liq}, "volume": {"h24": 10}}


@pytest.fixture
def dex(monkeypatch):
    state = {"resp": _dex_pairs(_pair())}

    def fake_get(url, timeout=None, **k):
        r = state["resp"]
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(wp.requests, "get", fake_get)
    return state


# ── Registry and support ─────────────────────────────────────────────────────

def test_registry_entry():
    cfg = wp.CUSTOM_TOKEN_CHAINS["solana"]
    assert cfg["label"] == "Solana"
    assert cfg["rpc_env"] == "SOLANA_RPC_URL"
    assert cfg["rpc_default"] is None            # no public fallback (Oct 11 ruling)
    assert cfg["dexscreener_slug"] == "solana"
    assert wp._custom_chain_format("solana") == "base58"
    for key in ("ethereum", "base", "robinhood", "nope", "", None):
        assert wp._custom_chain_format(key) == "evm"


def test_supported_only_when_the_url_is_set(monkeypatch):
    monkeypatch.delenv("SOLANA_RPC_URL", raising=False)
    assert wp.custom_token_chain_supported("solana") == (False, "SOLANA_RPC_URL")
    assert "solana" not in wp.supported_custom_chains()
    monkeypatch.setenv("SOLANA_RPC_URL", FAKE_URL)
    assert wp.custom_token_chain_supported("solana") == (True, "SOLANA_RPC_URL")


def test_chains_route_reports_each_format(client):
    rows = client.get("/api/custom-tokens/chains").get_json()
    by_key = {r["key"]: r for r in rows}
    assert by_key["solana"] == {"key": "solana", "label": "Solana", "format": "base58"}
    assert by_key["base"]["format"] == "evm" and by_key["robinhood"]["format"] == "evm"
    assert all(set(r) == {"key", "label", "format"} for r in rows)


# ── Adding a Solana token ────────────────────────────────────────────────────

def test_add_solana_mint(client, solana_rpc, dex):
    resp = client.post("/api/custom-tokens", json={"chain": "solana", "contract": MINT})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    tok = resp.get_json()["token"]
    assert (tok["chain"], tok["contract"], tok["symbol"], tok["decimals"]) == ("solana", MINT, "MINI", 6)
    assert solana_rpc["calls"] == [("getTokenSupply", [MINT])]
    stored = client.get("/api/custom-tokens").get_json()["tokens"]
    assert stored[0]["contract"] == MINT              # case kept


def test_add_rejects_an_evm_address_on_solana(client, solana_rpc):
    resp = client.post("/api/custom-tokens", json={"chain": "solana", "contract": EVM_TOKEN})
    assert resp.status_code == 400 and "invalid" in resp.get_json()["error"].lower()
    assert solana_rpc["calls"] == []


def test_add_rejects_a_base58_mint_on_an_evm_chain(client, monkeypatch):
    monkeypatch.setattr(wp, "_rpc_url_for_chain", lambda chain: "http://fake-rpc.test/base")
    resp = client.post("/api/custom-tokens", json={"chain": "base", "contract": MINT})
    assert resp.status_code == 400 and "invalid" in resp.get_json()["error"].lower()


def test_add_solana_without_url_is_refused(client, monkeypatch):
    monkeypatch.delenv("SOLANA_RPC_URL", raising=False)
    resp = client.post("/api/custom-tokens", json={"chain": "solana", "contract": MINT})
    assert resp.status_code == 400
    err = resp.get_json()["error"]
    assert "solana" in err and "SOLANA_RPC_URL" not in err


def test_add_solana_403_says_authentication_and_never_shows_the_key(client, solana_rpc, dex, capsys):
    solana_rpc["responses"]["getTokenSupply"] = _Resp(403, {"error": "forbidden"})
    resp = client.post("/api/custom-tokens", json={"chain": "solana", "contract": MINT})
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "authentication failed" in body and SECRET not in body
    assert SECRET not in capsys.readouterr().out
    assert client.get("/api/custom-tokens").get_json()["tokens"] == []


def test_add_solana_not_a_mint_gives_the_generic_message(client, solana_rpc, dex):
    solana_rpc["responses"]["getTokenSupply"] = _Resp(200, {"jsonrpc": "2.0", "id": 1, "error": {
        "code": -32602, "message": "Invalid param: not a Token mint"}})
    resp = client.post("/api/custom-tokens", json={"chain": "solana", "contract": MINT})
    assert resp.status_code == 400
    assert "Could not read token metadata" in resp.get_json()["error"]


def test_add_with_dexscreener_down_stores_the_symbol_as_pending(client, solana_rpc, dex):
    dex["resp"] = wp.requests.exceptions.ConnectionError("down")
    tok = client.post("/api/custom-tokens", json={"chain": "solana", "contract": MINT}).get_json()["token"]
    assert (tok["symbol"], tok["decimals"]) == ("pending", 6)


# ── Symbol lookup ────────────────────────────────────────────────────────────

def test_symbol_falls_back_to_a_short_mint_when_no_pair_names_it(solana_rpc, dex):
    dex["resp"] = _dex_pairs(_pair(chain="base"))      # only another chain
    assert wp.fetch_solana_token_metadata(MINT) == (MINT[:4] + "…" + MINT[-4:], 6)


def test_symbol_from_the_deepest_pair_on_either_side(solana_rpc, dex):
    other = "OtherMint" + "4" * 30
    dex["resp"] = _dex_pairs(
        _pair(base=MINT, base_sym="SHALLOW", liq=10.0),
        _pair(base=other, base_sym="X", quote=MINT, quote_sym="MINI", liq=5000.0),
        _pair(chain="base", base=MINT, base_sym="WRONGCHAIN", liq=1e9))
    assert wp.fetch_solana_token_metadata(MINT)[0] == "MINI"


def test_symbol_match_is_case_sensitive(solana_rpc, dex):
    dex["resp"] = _dex_pairs(_pair(base=MINT.lower(), base_sym="CASECLASH"))
    assert wp.fetch_solana_token_metadata(MINT)[0] == MINT[:4] + "…" + MINT[-4:]


def test_pending_symbol_stays_pending_after_a_build_retry(solana_rpc, dex, monkeypatch):
    conn = get_connection()
    conn.execute("INSERT INTO custom_tokens (chain, contract, symbol, decimals, added_at) "
                 "VALUES ('solana', ?, 'pending', 6, '2026-10-11T00:00:00')", (MINT,))
    conn.commit()
    tid = conn.execute("SELECT id FROM custom_tokens").fetchone()["id"]
    conn.close()
    dex["resp"] = wp.requests.exceptions.ConnectionError("down")
    assert wp.resolve_pending_metadata({"id": tid, "chain": "solana", "contract": MINT,
                                        "symbol": "pending", "decimals": 6}) == ("pending", 6, False)
    dex["resp"] = _dex_pairs(_pair())
    assert wp.resolve_pending_metadata({"id": tid, "chain": "solana", "contract": MINT,
                                        "symbol": "pending", "decimals": 6}) == ("MINI", 6, True)


# ── Balance reads ────────────────────────────────────────────────────────────

def test_balance_sums_every_account_with_its_own_decimals(solana_rpc):
    solana_rpc["responses"]["getTokenAccountsByOwner"] = _accounts(1_000_000, 2_500_000)
    assert wp.fetch_solana_token_balance("solana", MINT, SOL_WALLET, 18) == pytest.approx(3.5)
    method, params = solana_rpc["calls"][0]
    assert method == "getTokenAccountsByOwner"
    assert params == [SOL_WALLET, {"mint": MINT}, {"encoding": "jsonParsed"}]


def test_no_account_is_a_real_zero(solana_rpc):
    solana_rpc["responses"]["getTokenAccountsByOwner"] = {"context": {"slot": 1}, "value": []}
    assert wp.fetch_solana_token_balance("solana", MINT, SOL_WALLET) == 0.0


@pytest.mark.parametrize("bad", [
    _Resp(500, {"error": "boom"}),
    _Resp(200, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "nope"}}),
    _Resp(200, ValueError("not json")),
    _Resp(200, {"jsonrpc": "2.0", "id": 1}),
    {"value": "not a list"},
    {"value": [{"account": {"data": ["base64stuff", "base64"]}}]},   # not parsed
    _accounts(5, mint="AnotherMint" + "5" * 30),                    # wrong mint
])
def test_a_failed_read_raises_and_never_reads_zero(solana_rpc, bad):
    solana_rpc["responses"]["getTokenAccountsByOwner"] = bad
    with pytest.raises(wp.SolanaRpcError):
        wp.fetch_solana_token_balance("solana", MINT, SOL_WALLET)


def test_a_rate_limit_is_retried_once(solana_rpc):
    solana_rpc["responses"]["getTokenAccountsByOwner"] = [_Resp(429, {}), _accounts(2_000_000)]
    assert wp.fetch_solana_token_balance("solana", MINT, SOL_WALLET) == pytest.approx(2.0)
    solana_rpc["responses"]["getTokenAccountsByOwner"] = [_Resp(429, {}), _Resp(429, {})]
    with pytest.raises(wp.SolanaRpcError):
        wp.fetch_solana_token_balance("solana", MINT, SOL_WALLET)


def test_errors_never_carry_the_rpc_url(solana_rpc):
    solana_rpc["responses"]["getTokenAccountsByOwner"] = wp.requests.exceptions.ConnectionError(
        f"HTTPSConnectionPool(host='x', port=443): Max retries exceeded with url: /v2/{SECRET}")
    with pytest.raises(wp.SolanaRpcError) as exc:
        wp.fetch_solana_token_balance("solana", MINT, SOL_WALLET)
    assert SECRET not in str(exc.value)
    assert SECRET not in "".join(traceback.format_exception(exc.type, exc.value, exc.tb))


def test_missing_url_raises_unsupported(monkeypatch):
    monkeypatch.delenv("SOLANA_RPC_URL", raising=False)
    with pytest.raises(wp.UnsupportedChainError):
        wp.fetch_solana_token_balance("solana", MINT, SOL_WALLET)


def test_cache_key_keeps_solana_case_and_evm_keys_are_unchanged(solana_rpc, monkeypatch):
    assert wp.fetch_erc20_balance_cached("solana", MINT, SOL_WALLET, 6, _now=1000.0) == pytest.approx(1.5)
    assert ("solana", MINT, SOL_WALLET) in wp._custom_balance_cache
    monkeypatch.setattr(wp, "fetch_erc20_balance", lambda chain, contract, wallet, decimals: 4.0)
    wp.fetch_erc20_balance_cached("base", EVM_TOKEN, EVM_WALLET, 18, _now=1000.0)
    assert ("base", EVM_TOKEN.lower(), EVM_WALLET.lower()) in wp._custom_balance_cache


# ── Holdings rows ────────────────────────────────────────────────────────────

def _seed(chain, contract, symbol, decimals):
    conn = get_connection()
    conn.execute("INSERT INTO custom_tokens (chain, contract, symbol, decimals, added_at) VALUES (?,?,?,?,?)",
                 (chain, contract, symbol, decimals, "2026-10-11T00:00:00"))
    conn.commit()
    conn.close()


@pytest.fixture
def two_families(monkeypatch, solana_rpc):
    """One EVM wallet and one Solana wallet; one Base token and one Solana token."""
    _seed("base", EVM_TOKEN, "PLAZM", 18)
    _seed("solana", MINT, "MINI", 6)
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [EVM_WALLET, SOL_WALLET])
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {
        EVM_WALLET: {"label": "Main"}, SOL_WALLET: {"label": "Sol Main", "type": "solana"}})
    monkeypatch.setattr(wp, "custom_token_chain_supported", lambda chain: (True, "X"))
    monkeypatch.setattr(wp, "fetch_dexscreener_price",
                        lambda contract, chain=None, _now=None: 2.0 if chain == "base" else 0.004)
    evm_calls = []

    def fake_erc20(chain, contract, wallet, decimals):
        evm_calls.append((chain, contract, wallet))
        return 5.0
    monkeypatch.setattr(wp, "fetch_erc20_balance", fake_erc20)
    solana_rpc["evm_calls"] = evm_calls
    return solana_rpc


def test_each_token_is_read_only_for_its_own_wallets(two_families):
    rows = wp.build_custom_token_rows()
    pairs = sorted((r["symbol"], r["wallet"]) for r in rows)
    assert pairs == [("MINI", SOL_WALLET), ("PLAZM", EVM_WALLET)]
    assert two_families["evm_calls"] == [("base", EVM_TOKEN, EVM_WALLET)]
    assert [p[0] for _, p in two_families["calls"]] == [SOL_WALLET]


def test_solana_row_shape(two_families):
    row = next(r for r in wp.build_custom_token_rows() if r["symbol"] == "MINI")
    assert row["chain"] == "Solana"                    # same name Zerion uses
    assert row["contract"] == MINT and row["wallet"] == SOL_WALLET
    assert row["wallet_label"] == "Sol Main" and row["source"] == "custom"
    assert row["balance"] == pytest.approx(1.5) and row["price_usd"] == 0.004
    assert row["value_usd"] == pytest.approx(0.006)
    assert row["balance_failed"] is False and row["is_zero_balance"] is False


def test_a_failed_solana_read_is_a_dash_not_a_zero(two_families):
    two_families["responses"]["getTokenAccountsByOwner"] = _Resp(503, {})
    row = next(r for r in wp.build_custom_token_rows() if r["symbol"] == "MINI")
    assert row["balance"] is None and row["balance_failed"] is True and row["value_usd"] == 0.0
    assert ("solana", MINT, SOL_WALLET) not in wp._custom_balance_cache


def test_no_solana_wallet_means_no_solana_rows(two_families, monkeypatch):
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [EVM_WALLET])
    rows = wp.build_custom_token_rows()
    assert [r["symbol"] for r in rows] == ["PLAZM"]
    assert two_families["calls"] == []


def test_merge_drops_a_zerion_row_for_the_same_mint_and_wallet(two_families):
    zerion = [{"chain": "Solana", "symbol": "MINI", "contract": MINT, "wallet": SOL_WALLET, "value_usd": 99.0},
              {"chain": "Solana", "symbol": "BONK", "contract": "BonkMint" + "6" * 30,
               "wallet": SOL_WALLET, "value_usd": 1.0}]
    merged = wp.merge_custom_tokens(zerion)
    minis = [t for t in merged if t["symbol"] == "MINI"]
    assert len(minis) == 1 and minis[0]["source"] == "custom"
    assert any(t["symbol"] == "BONK" for t in merged)


def test_solana_rows_match_spot_positions_by_chain_and_mint(two_families):
    row = next(r for r in wp.build_custom_token_rows() if r["symbol"] == "MINI")
    pos = {"symbol": "MINI", "chain": "solana", "contract_address": MINT}
    assert wp._spot_location_row_matches(pos, {"chain": row["chain"], "symbol": row["symbol"],
                                               "token_address": row["contract"]})
    assert not wp._spot_location_row_matches(dict(pos, contract_address=MINT.lower()),
                                             {"chain": row["chain"], "symbol": row["symbol"],
                                              "token_address": row["contract"]})


# ── Review follow-ups ────────────────────────────────────────────────────────

def test_an_untyped_base58_wallet_still_gets_solana_rows(two_families, monkeypatch):
    # An older Settings entry saved without a type lands in the "evm" group.
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {
        EVM_WALLET: {"label": "Main"}, SOL_WALLET: {"label": "Sol Main"}})
    rows = wp.build_custom_token_rows()
    assert ("MINI", SOL_WALLET) in {(r["symbol"], r["wallet"]) for r in rows}
    assert ("MINI", EVM_WALLET) not in {(r["symbol"], r["wallet"]) for r in rows}
    assert [p[0] for _, p in two_families["calls"]] == [SOL_WALLET]


def test_a_solana_token_with_no_solana_wallet_is_logged(two_families, monkeypatch, capsys):
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [EVM_WALLET])
    wp.build_custom_token_rows()
    assert "no Solana wallet in Settings" in capsys.readouterr().out


def test_a_slow_add_returns_at_the_timeout(client, solana_rpc, dex, monkeypatch):
    import time as _t
    monkeypatch.setattr(wp, "_CUSTOM_METADATA_TIMEOUT", 0.2)

    def slow_meta(mint):
        threading.Event().wait(2.0)        # time.sleep is stubbed by the solana_rpc fixture
        return ("MINI", 6)
    monkeypatch.setattr(wp, "fetch_solana_token_metadata", slow_meta)
    t0 = _t.monotonic()
    body = client.post("/api/custom-tokens", json={"chain": "solana", "contract": MINT}).get_json()
    assert _t.monotonic() - t0 < 1.2
    assert body["pending"] is True and body["token"]["symbol"] == "pending"


def test_an_add_whose_rpc_error_holds_the_url_never_shows_or_logs_the_key(client, solana_rpc, dex, capsys):
    solana_rpc["responses"]["getTokenSupply"] = wp.requests.exceptions.ConnectionError(
        f"HTTPSConnectionPool(host='x', port=443): Max retries exceeded with url: /v2/{SECRET}")
    resp = client.post("/api/custom-tokens", json={"chain": "solana", "contract": MINT})
    assert resp.status_code == 400 and SECRET not in resp.get_data(as_text=True)
    assert SECRET not in capsys.readouterr().out


def test_the_background_refresh_reads_solana_balances(solana_rpc):
    key = ("solana", MINT, SOL_WALLET)
    wp._custom_balance_cache[key] = (7.0, 0.0)          # ancient entry
    assert wp.fetch_erc20_balance_cached("solana", MINT, SOL_WALLET, 6, _now=10_000.0) == 7.0
    for _ in range(100):
        if wp._custom_balance_cache[key][0] != 7.0:
            break
        threading.Event().wait(0.02)
    assert wp._custom_balance_cache[key][0] == pytest.approx(1.5)
    assert solana_rpc["calls"][0][0] == "getTokenAccountsByOwner"


def test_a_zerion_solana_row_carries_the_mint_so_merge_dedupes_it(two_families):
    # Shape of a Zerion Solana position as the mapper reads it. Production
    # evidence (Oct 11): Solana spot positions keyed by mint already match
    # their Zerion token_snapshots rows by address in /api/spot/change-24h.
    position = {"attributes": {"quantity": {"float": 3.0}, "value": 9.0, "price": 3.0,
                               "fungible_info": {"symbol": "MINI", "implementations": [
                                   {"chain_id": "solana", "address": MINT, "decimals": 6}]}},
                "relationships": {"chain": {"data": {"id": "solana"}}}}
    from src.connectors.zerion import map_zerion_token_to_app
    row = map_zerion_token_to_app(position, SOL_WALLET, "Sol Main")
    assert (row["chain"], row["contract"], row["wallet"]) == ("Solana", MINT, SOL_WALLET)
    merged = wp.merge_custom_tokens([row])
    minis = [t for t in merged if t["symbol"] == "MINI" and t["wallet"] == SOL_WALLET]
    assert len(minis) == 1 and minis[0]["source"] == "custom"


@pytest.mark.parametrize("pairs", [None, "x", [None, "x", 3, {"chainId": "solana", "baseToken": "x"}]])
def test_malformed_dexscreener_pairs_never_raise(monkeypatch, pairs):
    monkeypatch.setattr(wp.requests, "get", lambda url, timeout=None, **k: _Resp(200, {"pairs": pairs}))
    assert wp._dexscreener_token_symbol(MINT, "solana") == (True, None)
