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
def _clear_pool_tokens_cache():
    mlp._POOL_TOKENS_CACHE.clear()
    yield
    mlp._POOL_TOKENS_CACHE.clear()


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
