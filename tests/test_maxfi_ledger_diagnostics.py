"""Route-level tests for GET /api/maxfi/ledger/diagnostics/unpriceable/<chain>
(HANDOFF_maxfi_ledger.md, Commit 3b.3 step 1) - the read-only diagnostic
that enumerates pool_address/token0/token1 for every position whose pool
resolved but whose due basis/exit price is still missing.

No network: maxfi_ledger_ingest.eth_call (the ONE transport primitive
maxfi_ledger_pricing.get_pool_tokens() uses) is monkeypatched directly,
the same boundary tests/test_maxfi_ledger_pricing.py uses. DB rows are
constructed directly (no scan/derive/backfill involved), same as
tests/test_maxfi_ledger_reconciliation.py. Fixture shapes mirror
tests/test_maxfi_ledger_backfill_route.py (in-memory shared-cache
sqlite, portfolio_db.get_connection monkeypatched, threading neutralized
during the web_portfolio import).
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

import maxfi_ledger_ingest as mli
import maxfi_ledger_pricing as mlp
import maxfi_schema
import src.storage.portfolio_db as portfolio_db

URL = "/api/maxfi/ledger/diagnostics/unpriceable/base"
VAULT = mli.CHAINS["base"]["vault"]
POOL_A = "0x" + "a1" * 20
POOL_B = "0x" + "b2" * 20
TOKEN_A0 = "0x" + "c3" * 20
TOKEN_A1 = "0x" + "d4" * 20


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
    uri = f"file:maxfi_ledger_diag_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
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
    """Commit 3b.3 step 1b: gained _DECIMALS_CACHE alongside
    _POOL_TOKENS_CACHE - the hop-probe tests below pin exact rpc_calls
    counts, which a warm decimals() cache from a prior test would skew.
    No existing test in this file reads decimals, so their behavior is
    unchanged."""
    mlp._POOL_TOKENS_CACHE.clear()
    mlp._DECIMALS_CACHE.clear()
    yield
    mlp._POOL_TOKENS_CACHE.clear()
    mlp._DECIMALS_CACHE.clear()


def _insert(db, token_id, pool_address, basis_block=None, basis_price=None,
            closed_block=None, exit_price=None, chain="base"):
    db.execute(
        """
        INSERT INTO maxfi_ledger_positions
        (chain, vault, npm, token_id, pool_address, basis_block, basis_price_usd,
         closed_block, exit_price_usd, computed_at)
        VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, '2026-09-21T00:00:00+00:00')
        """,
        (chain, VAULT, str(token_id), pool_address, basis_block, basis_price, closed_block, exit_price),
    )
    db.commit()


def _addr_word(address):
    return address[2:].lower().zfill(64)


def _fake_eth_call_factory(calls):
    """POOL_A resolves (token0/token1); POOL_B's RPC raises; anything else
    is a test bug. `calls` counts every real call, for the cache test."""
    def fake_eth_call(chain, to, data, timeout=30):
        calls.append(to)
        if to == POOL_A:
            if data.startswith(mlp.SEL_POOL_TOKEN0):
                return "0x" + _addr_word(TOKEN_A0)
            if data.startswith(mlp.SEL_POOL_TOKEN1):
                return "0x" + _addr_word(TOKEN_A1)
        if to == POOL_B:
            raise mli.MaxFiRpcError("boom")
        raise AssertionError(f"unexpected eth_call: to={to} data={data[:10]}")
    return fake_eth_call


def test_invalid_chain_returns_400(client, db):
    r = client.get("/api/maxfi/ledger/diagnostics/unpriceable/not-a-real-chain")
    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidChain"


def test_resolves_tokens_and_soft_isolates_a_failing_pool(client, db, monkeypatch):
    """Two unpriced rows: POOL_A resolves, POOL_B's RPC fails - the
    failure lands in that row's resolution_error only, the other row is
    unaffected, and the caveat is returned verbatim."""
    _insert(db, 100, POOL_A, basis_block=500)
    _insert(db, 101, POOL_B, basis_block=600)
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call_factory([]))

    r = client.get(URL)
    assert r.status_code == 200
    body = r.get_json()

    assert body["chain"] == "base"
    assert body["count"] == 2
    assert body["caveat"] == (
        "Rows are selected by missing basis/exit price, not by the unpriceable_pair "
        "reason code specifically (reason codes are not persisted). As of this run "
        "both chains have zero deferred lookups in any other category, so this set "
        "is currently equivalent to unpriceable_pair — but that equivalence is not "
        "guaranteed to hold after a future backfill run."
    )
    assert body["caveat"] == wp.MAXFI_LEDGER_UNPRICEABLE_CAVEAT
    assert body["selection"] == wp.MAXFI_LEDGER_UNPRICEABLE_SELECTION

    by_token = {row["token_id"]: row for row in body["rows"]}
    a, b = by_token["100"], by_token["101"]
    assert a == {
        "vault": VAULT, "npm": None, "token_id": "100", "pool_address": POOL_A,
        "missing": ["basis"], "token0": TOKEN_A0, "token1": TOKEN_A1, "resolution_error": None,
    }
    assert b["pool_address"] == POOL_B
    assert b["token0"] is None and b["token1"] is None
    assert b["resolution_error"] == "pool_tokens_unresolved"


def test_selection_mirrors_pricing_gates(client, db, monkeypatch):
    """Excluded: fully priced closed row; OPEN row with basis priced (exit
    is NULL only because no closed_block exists); row with no
    pool_address; row with no basis_block (never priced at all).
    Included: closed row with basis priced but exit unpriced (missing
    ["exit"]); open row with basis_block set but basis unpriced (missing
    ["basis"]); closed row missing both."""
    _insert(db, 200, POOL_A, basis_block=500, basis_price=10.0, closed_block=900, exit_price=12.0)  # excluded
    _insert(db, 201, POOL_A, basis_block=500, basis_price=10.0)                                     # excluded: open
    _insert(db, 202, None, basis_block=500)                                                          # excluded: no pool
    _insert(db, 203, POOL_A)                                                                         # excluded: no basis_block
    _insert(db, 204, POOL_A, basis_block=500, basis_price=10.0, closed_block=900)                   # included: exit
    _insert(db, 205, POOL_A, basis_block=500)                                                        # included: basis
    _insert(db, 206, POOL_A, basis_block=500, closed_block=900)                                     # included: both
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call_factory([]))

    body = client.get(URL).get_json()

    assert body["count"] == 3
    assert {row["token_id"]: row["missing"] for row in body["rows"]} == {
        "204": ["exit"], "205": ["basis"], "206": ["basis", "exit"],
    }


def test_other_chain_rows_are_not_returned(client, db, monkeypatch):
    _insert(db, 300, POOL_A, basis_block=500, chain="robinhood")
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call_factory([]))

    body = client.get(URL).get_json()

    assert body["count"] == 0 and body["rows"] == []


def test_reuses_get_pool_tokens_cache_no_rpc_on_second_call(client, db, monkeypatch):
    """Proves reuse of maxfi_ledger_pricing.get_pool_tokens(), not a
    private re-implementation: the first call costs exactly its two
    eth_calls (token0(), token1()); a second call for the same pool is a
    _POOL_TOKENS_CACHE hit and costs none."""
    _insert(db, 400, POOL_A, basis_block=500)
    calls = []
    monkeypatch.setattr(mli, "eth_call", _fake_eth_call_factory(calls))

    assert client.get(URL).get_json()["count"] == 1
    assert calls == [POOL_A, POOL_A]
    assert client.get(URL).get_json()["rows"][0]["token0"] == TOKEN_A0
    assert calls == [POOL_A, POOL_A]  # no additional RPC


def test_escaping_rpc_exception_is_recorded_per_row(client, db, monkeypatch):
    """get_pool_tokens() never raises today; the route's own per-row
    try/except (3b.1.3 precedent) still catches a MaxFiIngestError that
    escapes it, records it, and keeps going."""
    _insert(db, 500, POOL_A, basis_block=500)
    _insert(db, 501, POOL_B, basis_block=600)

    def fake_get_pool_tokens(chain, pool_address, _counter=None):
        if pool_address == POOL_B:
            raise mli.MaxFiRpcError("[base] upstream 502")
        return {"token0": TOKEN_A0, "token1": TOKEN_A1}

    monkeypatch.setattr(mlp, "get_pool_tokens", fake_get_pool_tokens)

    body = client.get(URL).get_json()

    by_token = {row["token_id"]: row for row in body["rows"]}
    assert by_token["500"]["resolution_error"] is None
    assert by_token["501"]["resolution_error"] == "rpc_error: [base] upstream 502"
    assert body["count"] == 2


# ── Commit 3b.3 step 1b: GET /api/maxfi/ledger/diagnostics/hop-probe/<chain> ──
# Same eth_call seam. The fake dispatches on the calldata selector, so
# every reused helper (get_factory / get_pool / get_decimals) and the
# route's own symbol()/liquidity()/slot0() calls hit the one fake.

import maxfi_client as mc

PROBE_URL = "/api/maxfi/ledger/diagnostics/hop-probe/base"
TOKEN = "0x" + "e5" * 20
FACTORY = "0x" + "f1" * 20
POOL_X = "0x" + "a7" * 20
SQRT_PRICE_NONZERO = 2 ** 96


def _uint_word(value):
    return format(value, "064x")


def _abi_string(text):
    b = text.encode()
    return "0x" + _uint_word(32) + _uint_word(len(b)) + b.hex().ljust(64, "0")


def _bytes32_symbol(text):
    return "0x" + text.encode().hex().ljust(64, "0")


def _slot0_words(sqrt_price_x96):
    return "0x" + _uint_word(sqrt_price_x96) + _uint_word(0) * 6


def _probe_fake_eth_call(calls, *, symbol_raw=_abi_string("cbBTC"), symbol_raises=False,
                         pool_for=(mlp.ADDR_BASE_USDC, 500), liquidity=12345):
    """One pool exists (USDC/500 by default) with the given liquidity and
    an initialized slot0; every other (anchor, fee) is the zero address."""
    def fake_eth_call(chain, to, data, timeout=30):
        calls.append((to, data[:10]))
        if data.startswith(mlp.SEL_NPM_FACTORY):
            return "0x" + _addr_word(FACTORY)
        if data.startswith(mlp.SEL_FACTORY_GET_POOL):
            anchor = "0x" + data[10 + 64:10 + 128][-40:]
            fee = int(data[-64:], 16)
            if pool_for is not None and (anchor, fee) == (pool_for[0].lower(), pool_for[1]):
                return "0x" + _addr_word(POOL_X)
            return "0x" + _uint_word(0)
        if data.startswith(mlp.SEL_ERC20_DECIMALS):
            return "0x" + _uint_word(8)
        if data.startswith(mc.SEL_ERC20_SYMBOL):
            if symbol_raises:
                raise mli.MaxFiRpcError("[base] symbol() reverted")
            return symbol_raw
        if to == POOL_X and data.startswith(wp.SEL_POOL_LIQUIDITY):
            return "0x" + _uint_word(liquidity)
        if to == POOL_X and data.startswith(mc.SEL_POOL_SLOT0):
            return _slot0_words(SQRT_PRICE_NONZERO)
        raise AssertionError(f"unexpected eth_call: to={to} data={data[:10]}")
    return fake_eth_call


def test_hop_probe_happy_path_one_pool_with_liquidity(client, db, monkeypatch):
    calls = []
    monkeypatch.setattr(mli, "eth_call", _probe_fake_eth_call(calls))

    r = client.get(PROBE_URL + f"?tokens={TOKEN}")
    assert r.status_code == 200
    body = r.get_json()

    assert body["chain"] == "base"
    assert body["factory"] == FACTORY and body["factory_error"] is None
    assert body["anchors"] == {"WETH": mlp.ADDR_BASE_WETH, "USDC": mlp.ADDR_BASE_USDC}
    assert body["fee_tiers"] == [100, 500, 3000, 10000]
    assert len(body["tokens"]) == 1
    tok = body["tokens"][0]
    assert tok["address"] == TOKEN
    assert tok["symbol"] == "cbBTC" and tok["symbol_error"] is None
    assert tok["decimals"] == 8 and tok["decimals_error"] is None
    assert len(tok["pools"]) == 8  # 2 anchors x 4 fee tiers
    hit = [p for p in tok["pools"] if p["pool_address"] is not None]
    assert hit == [{
        "anchor": "USDC", "fee": 500, "pool_address": POOL_X,
        "liquidity": "12345", "initialized": True, "error": None,
    }]
    assert all(p["error"] is None for p in tok["pools"])
    assert tok["has_anchor_path"] is True
    # factory + symbol + decimals + 8 getPool + liquidity + slot0
    assert body["rpc_calls"] == 1 + 1 + 1 + 8 + 2 == len(calls)


def test_hop_probe_all_zero_address_pools(client, db, monkeypatch):
    calls = []
    monkeypatch.setattr(mli, "eth_call", _probe_fake_eth_call(calls, pool_for=None))

    tok = client.get(PROBE_URL + f"?tokens={TOKEN}").get_json()["tokens"][0]

    assert all(p["pool_address"] is None for p in tok["pools"])
    assert all(p["liquidity"] is None and p["initialized"] is None for p in tok["pools"])
    assert all(p["error"] is None for p in tok["pools"])
    assert tok["symbol_error"] is None and tok["decimals_error"] is None
    assert tok["has_anchor_path"] is False
    assert len(calls) == 1 + 1 + 1 + 8  # no liquidity/slot0 calls on a zero-address pool


def test_hop_probe_symbol_bytes32_fallback(client, db, monkeypatch):
    monkeypatch.setattr(mli, "eth_call", _probe_fake_eth_call([], symbol_raw=_bytes32_symbol("cbBTC")))

    tok = client.get(PROBE_URL + f"?tokens={TOKEN}").get_json()["tokens"][0]

    assert tok["symbol"] == "cbBTC"
    assert tok["symbol_error"] is None


def test_hop_probe_symbol_rpc_failure_is_isolated(client, db, monkeypatch):
    monkeypatch.setattr(mli, "eth_call", _probe_fake_eth_call([], symbol_raises=True))

    r = client.get(PROBE_URL + f"?tokens={TOKEN}")
    assert r.status_code == 200
    tok = r.get_json()["tokens"][0]

    assert tok["symbol"] is None
    assert tok["symbol_error"].startswith("rpc_error:")
    assert tok["decimals"] == 8 and tok["decimals_error"] is None  # rest still populated
    assert tok["has_anchor_path"] is True
    assert [p for p in tok["pools"] if p["pool_address"]][0]["liquidity"] == "12345"


def test_hop_probe_input_validation(client, db, monkeypatch):
    monkeypatch.setattr(mli, "eth_call", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no RPC on a 400")))

    assert client.get("/api/maxfi/ledger/diagnostics/hop-probe/not-a-real-chain?tokens=" + TOKEN).status_code == 400
    assert client.get(PROBE_URL).status_code == 400  # tokens missing
    assert client.get(PROBE_URL + "?tokens=").status_code == 400  # tokens empty
    five = ",".join("0x" + f"{i:02x}" * 20 for i in range(1, 6))
    assert client.get(PROBE_URL + "?tokens=" + five).status_code == 400  # cap is 4
    assert client.get(PROBE_URL + "?tokens=0xnothex").status_code == 400  # malformed address
