"""Tests for maxfi_pooldata (LP Advisor Phase A1 / A1.5): the pure
discover_projects/discover_chains/filter_pools/summarize_field_availability/
match_pools_by_underlying helpers, the single network seam
fetch_llama_pools (monkeypatched requests.get, never a real HTTP call), and
the read-only probe route GET /api/maxfi/pooldata-probe.

Uses the same client-fixture pattern as tests/test_maxfi_claims_routes.py.
Route tests that exercise the Phase A1.5 held-token DB join use the iv_db
shared-cache sqlite pattern from tests/test_maxfi_valuation_route.py:308
(not tests/test_maxfi_token_price_stats.py, which is schema-only) - a
shared-cache URI is needed because the route opens and closes its OWN
connection per call, so a bare ":memory:" would lose all seeded state the
instant the route's own conn.close() ran.
"""
import sqlite3
import uuid

import pytest
import requests

import maxfi_client
import maxfi_pooldata
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
def pooldata_db(monkeypatch):
    uri = f"file:maxfi_pooldata_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
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


def _seed_token_price_stats(db, chain, address, symbol):
    db.execute(
        """
        INSERT INTO maxfi_token_price_stats
            (chain, address, symbol, last_price_usd, last_price_at,
             ath_price_usd, ath_at, first_recorded_at)
        VALUES (?, ?, ?, 1.0, '2026-01-01T00:00:00+00:00',
                1.0, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
        """,
        (chain, address, symbol),
    )
    db.commit()


# ── discover_projects / discover_chains ─────────────────────────────────

def test_discover_projects_case_insensitive_and_skips_non_dict_rows():
    pools = [
        {"project": "MaxFi-V1"},
        {"project": "maxfi-v2"},
        {"project": "uniswap-v3"},
        "not-a-dict",
        {"no_project_key": True},
    ]
    assert maxfi_pooldata.discover_projects(pools, keyword="maxfi") == ["MaxFi-V1", "maxfi-v2"]


def test_discover_chains_case_insensitive_and_skips_non_dict_rows():
    pools = [
        {"chain": "Robinhood"},
        {"chain": "robinhood-chain"},
        {"chain": "Base"},
        42,
        {"no_chain_key": True},
    ]
    assert maxfi_pooldata.discover_chains(pools, keyword="robinhood") == ["Robinhood", "robinhood-chain"]


# ── filter_pools ─────────────────────────────────────────────────────────

def test_filter_pools_by_project_only():
    pools = [
        {"project": "maxfi", "chain": "Base"},
        {"project": "uniswap", "chain": "Base"},
    ]
    result = maxfi_pooldata.filter_pools(pools, projects=["maxfi"])
    assert result == [{"project": "maxfi", "chain": "Base"}]


def test_filter_pools_by_chain_only():
    pools = [
        {"project": "maxfi", "chain": "Base"},
        {"project": "maxfi", "chain": "Robinhood"},
    ]
    result = maxfi_pooldata.filter_pools(pools, chains=["Robinhood"])
    assert result == [{"project": "maxfi", "chain": "Robinhood"}]


def test_filter_pools_by_project_and_chain_case_insensitive_exact():
    pools = [
        {"project": "MaxFi", "chain": "Robinhood"},
        {"project": "MaxFi", "chain": "Base"},
        {"project": "Uniswap", "chain": "Robinhood"},
    ]
    result = maxfi_pooldata.filter_pools(pools, projects=["maxfi"], chains=["robinhood"])
    assert result == [{"project": "MaxFi", "chain": "Robinhood"}]


def test_filter_pools_passes_everything_through_when_both_falsy():
    pools = [{"project": "a"}, {"project": "b"}, "not-a-dict"]
    result = maxfi_pooldata.filter_pools(pools)
    assert result == pools


# ── summarize_field_availability ────────────────────────────────────────

def test_summarize_field_availability_distinguishes_absent_from_present_none():
    pools = [
        {"pool": "p1", "tvlUsd": 100.0},          # tvlUsd present, non-null
        {"pool": "p2", "tvlUsd": None},           # tvlUsd present, null
        {"pool": "p3"},                            # tvlUsd absent entirely
        "not-a-dict",                               # skipped for field counts
    ]
    summary = maxfi_pooldata.summarize_field_availability(pools)
    assert summary["row_count"] == 4   # non-dict row still counted here
    assert summary["tvlUsd"] == {"present": 2, "non_null": 1}
    assert summary["pool"] == {"present": 3, "non_null": 3}


def test_summarize_field_availability_empty_list():
    summary = maxfi_pooldata.summarize_field_availability([])
    assert summary["row_count"] == 0
    assert summary["pool"] == {"present": 0, "non_null": 0}


# ── match_pools_by_underlying ────────────────────────────────────────────

def test_match_pools_by_underlying_case_insensitive_address_match():
    held_tokens = [{"chain": "robinhood", "address": "0xabc", "symbol": "STONKBROKER"}]
    pools = [
        {"project": "some-project", "chain": "Robinhood", "pool": "p1",
         "underlyingTokens": ["0xABC", "0xDEF"]},
    ]
    report = maxfi_pooldata.match_pools_by_underlying(pools, held_tokens)
    assert len(report["matched_pools"]) == 1
    assert report["matched_pools"][0]["matched_tokens"] == [
        {"address": "0xabc", "symbol": "STONKBROKER", "chain": "robinhood"}
    ]
    assert report["unmatched_held_tokens"] == []


def test_match_pools_by_underlying_two_tokens_one_pool_and_project_aggregation():
    held_tokens = [
        {"chain": "robinhood", "address": "0xaaa", "symbol": "TENDIES"},
        {"chain": "robinhood", "address": "0xbbb", "symbol": "HOOKR"},
    ]
    pools = [
        {"project": "proj-x", "chain": "Robinhood", "pool": "p1",
         "underlyingTokens": ["0xAAA", "0xBBB"]},
        {"project": "proj-x", "chain": "Robinhood", "pool": "p2",
         "underlyingTokens": ["0xAAA"]},
    ]
    report = maxfi_pooldata.match_pools_by_underlying(pools, held_tokens)
    assert len(report["matched_pools"]) == 2
    p1 = next(p for p in report["matched_pools"] if p["llama_pool_id"] == "p1")
    assert [t["address"] for t in p1["matched_tokens"]] == ["0xaaa", "0xbbb"]
    assert report["projects"]["proj-x"] == {
        "pool_count": 2,
        "matched_token_addresses": ["0xaaa", "0xbbb"],
        "matched_token_symbols": ["HOOKR", "TENDIES"],
    }
    assert report["unmatched_held_tokens"] == []


def test_match_pools_by_underlying_skips_non_dict_rows_and_non_str_underlying():
    held_tokens = [{"chain": "base", "address": "0xaaa", "symbol": "X"}]
    pools = [
        "not-a-dict",
        {"project": "proj", "chain": "Base", "pool": "p1",
         "underlyingTokens": ["0xAAA", None, 42, "0xBBB"]},
    ]
    report = maxfi_pooldata.match_pools_by_underlying(pools, held_tokens)
    assert len(report["matched_pools"]) == 1
    assert report["matched_pools"][0]["matched_tokens"] == [
        {"address": "0xaaa", "symbol": "X", "chain": "base"}
    ]


def test_match_pools_by_underlying_unmatched_held_tokens_reported():
    held_tokens = [
        {"chain": "base", "address": "0xaaa", "symbol": "MATCHED"},
        {"chain": "base", "address": "0xbbb", "symbol": "ORPHAN"},
    ]
    pools = [
        {"project": "proj", "chain": "Base", "pool": "p1", "underlyingTokens": ["0xAAA"]},
    ]
    report = maxfi_pooldata.match_pools_by_underlying(pools, held_tokens)
    assert report["unmatched_held_tokens"] == [
        {"chain": "base", "address": "0xbbb", "symbol": "ORPHAN"}
    ]


def test_match_pools_by_underlying_empty_inputs_return_empty_structures():
    assert maxfi_pooldata.match_pools_by_underlying([], []) == {
        "matched_pools": [], "projects": {}, "unmatched_held_tokens": [],
    }
    held_tokens = [{"chain": "base", "address": "0xaaa", "symbol": "X"}]
    report = maxfi_pooldata.match_pools_by_underlying([], held_tokens)
    assert report["matched_pools"] == []
    assert report["unmatched_held_tokens"] == held_tokens


# ── fetch_llama_pools ─────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, json_error=None):
        self.status_code = status_code
        self._json_data = json_data
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._json_data


def test_fetch_llama_pools_success_returns_data_list(monkeypatch):
    fake_data = [{"project": "maxfi", "chain": "Robinhood"}]
    monkeypatch.setattr(
        maxfi_pooldata.requests, "get",
        lambda *a, **k: _FakeResponse(200, {"data": fake_data}),
    )
    assert maxfi_pooldata.fetch_llama_pools() == fake_data


def test_fetch_llama_pools_non_2xx_raises(monkeypatch):
    monkeypatch.setattr(
        maxfi_pooldata.requests, "get",
        lambda *a, **k: _FakeResponse(500, {"data": []}),
    )
    with pytest.raises(maxfi_pooldata.LlamaError):
        maxfi_pooldata.fetch_llama_pools()


def test_fetch_llama_pools_non_json_body_raises(monkeypatch):
    monkeypatch.setattr(
        maxfi_pooldata.requests, "get",
        lambda *a, **k: _FakeResponse(200, json_error=ValueError("not json")),
    )
    with pytest.raises(maxfi_pooldata.LlamaError):
        maxfi_pooldata.fetch_llama_pools()


def test_fetch_llama_pools_data_not_a_list_raises(monkeypatch):
    monkeypatch.setattr(
        maxfi_pooldata.requests, "get",
        lambda *a, **k: _FakeResponse(200, {"data": {"not": "a list"}}),
    )
    with pytest.raises(maxfi_pooldata.LlamaError):
        maxfi_pooldata.fetch_llama_pools()


def test_fetch_llama_pools_request_exception_raises(monkeypatch):
    def _boom(*a, **k):
        raise requests.RequestException("connection failed")
    monkeypatch.setattr(maxfi_pooldata.requests, "get", _boom)
    with pytest.raises(maxfi_pooldata.LlamaError):
        maxfi_pooldata.fetch_llama_pools()


# ── route: GET /api/maxfi/pooldata-probe ────────────────────────────────

_FAKE_CATALOGUE = [
    {"project": "maxfi-v1", "chain": "Robinhood", "pool": "p1", "tvlUsd": 1000.0},
    {"project": "uniswap-v3", "chain": "Base", "pool": "p2", "tvlUsd": 2000.0},
    "not-a-dict-row",
]


def test_probe_route_reports_candidates_and_passes_raw_dicts_through(client, pooldata_db, monkeypatch):
    # Phase A1.5: the route now also performs a real DB read (zero rows
    # seeded here) - the pooldata_db fixture lets that read succeed
    # cleanly instead of hitting an unconfigured real database.
    monkeypatch.setattr(maxfi_pooldata, "fetch_llama_pools", lambda: _FAKE_CATALOGUE)

    r = client.get("/api/maxfi/pooldata-probe")
    assert r.status_code == 200
    body = r.get_json()

    assert body["candidate_projects"] == ["maxfi-v1"]
    assert body["robinhood_chains"] == ["Robinhood"]
    assert body["total_pool_count"] == 3
    assert body["sample_project_matched"] == [_FAKE_CATALOGUE[0]]
    assert "held_token_join_error" not in body
    assert body["held_token_count"] == 0
    assert body["held_token_projects"] == {}


def test_probe_route_returns_502_on_llama_error(client, monkeypatch):
    def _boom():
        raise maxfi_pooldata.LlamaError("simulated failure")
    monkeypatch.setattr(maxfi_pooldata, "fetch_llama_pools", _boom)

    r = client.get("/api/maxfi/pooldata-probe")
    assert r.status_code == 502
    body = r.get_json()
    assert body["error"] == "LlamaError"
    assert body["detail"] == "simulated failure"


def test_probe_route_joins_held_tokens_against_underlying_tokens(client, pooldata_db, monkeypatch):
    catalogue = [
        {"project": "maxfi-v1", "chain": "Robinhood", "pool": "p1",
         "underlyingTokens": ["0xSTONKBROKER"]},
        {"project": "uniswap-v3", "chain": "Base", "pool": "p2",
         "underlyingTokens": ["0xUNRELATED"]},
    ]
    monkeypatch.setattr(maxfi_pooldata, "fetch_llama_pools", lambda: catalogue)
    _seed_token_price_stats(pooldata_db, "robinhood", "0xstonkbroker", "STONKBROKER")
    _seed_token_price_stats(pooldata_db, "base", "0xorphan", "ORPHAN")

    r = client.get("/api/maxfi/pooldata-probe")
    assert r.status_code == 200
    body = r.get_json()

    assert body["held_token_count"] == 2
    assert "maxfi-v1" in body["held_token_projects"]
    assert body["held_token_projects"]["maxfi-v1"]["matched_token_addresses"] == ["0xstonkbroker"]
    assert body["unmatched_held_tokens"] == [
        {"chain": "base", "address": "0xorphan", "symbol": "ORPHAN"}
    ]


def test_probe_route_degrades_gracefully_on_db_failure(client, monkeypatch):
    monkeypatch.setattr(maxfi_pooldata, "fetch_llama_pools", lambda: _FAKE_CATALOGUE)

    def _boom():
        raise RuntimeError("simulated DB failure")
    monkeypatch.setattr(portfolio_db, "get_connection", _boom)

    r = client.get("/api/maxfi/pooldata-probe")
    assert r.status_code == 200
    body = r.get_json()

    assert body["held_token_join_error"] == "simulated DB failure"
    # Llama-side results computed before the DB join must survive intact.
    assert body["candidate_projects"] == ["maxfi-v1"]
    assert body["total_pool_count"] == 3
    assert "held_token_count" not in body


# ── route: GET /api/maxfi/catalogue-probe/<chain> (LP Advisor A1.6) ────────

_A16_VAULT = "0x9999999999999999999999999999999999999999"


def _symbol_word(s):
    return s.encode().hex().ljust(64, '0')


def test_catalogue_probe_route_premise_failed_when_balance_zero(client, monkeypatch):
    monkeypatch.setattr(maxfi_client, "get_vault", lambda chain: (_A16_VAULT, []))
    monkeypatch.setattr(maxfi_client, "get_npm_balance_of", lambda chain, owner: 0)

    def _boom(*a, **k):
        raise AssertionError("must not enumerate when balance is 0")
    monkeypatch.setattr(maxfi_client, "enumerate_owner_token_ids", _boom)

    r = client.get("/api/maxfi/catalogue-probe/base")
    assert r.status_code == 200
    body = r.get_json()
    assert body["premise_holds"] is False
    assert body["npm_position_count"] == 0
    assert body["vault_address"] == _A16_VAULT
    assert "note" in body


def test_catalogue_probe_route_happy_path_aggregates_pools_and_symbols(client, monkeypatch):
    monkeypatch.setattr(maxfi_client, "get_vault", lambda chain: (_A16_VAULT, []))
    monkeypatch.setattr(maxfi_client, "get_npm_balance_of", lambda chain, owner: 3)
    monkeypatch.setattr(
        maxfi_client, "enumerate_owner_token_ids",
        lambda chain, owner, count, chunk_size=None: ([1, 2, 3], 0),
    )

    decoded = [
        {"token_id": "1", "pool_address": "0xpoola", "token0_address": "0xtoka",
         "token1_address": "0xtokb", "fee_tier": 3000},
        {"token_id": "2", "pool_address": "0xpoola", "token0_address": "0xtoka",
         "token1_address": "0xtokb", "fee_tier": 3000},
        {"token_id": "3", "pool_address": "0xpoolb", "token0_address": "0xtokc",
         "token1_address": "0xtokd", "fee_tier": 500},
    ]
    monkeypatch.setattr(
        maxfi_client, "decode_positions_and_pools",
        lambda chain, token_ids, chunk_size=None: decoded,
    )

    symbols = {"0xtoka": "TOKA", "0xtokb": "TOKB", "0xtokc": "TOKC", "0xtokd": "TOKD"}

    def _fake_multicall3_soft(chain, calls, chunk_size=None):
        return [(True, "0x" + _symbol_word(symbols[addr])) for addr, _cd in calls]
    monkeypatch.setattr(maxfi_client, "multicall3_soft", _fake_multicall3_soft)

    r = client.get("/api/maxfi/catalogue-probe/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["premise_holds"] is True
    assert body["npm_position_count"] == 3
    assert body["enumerated_count"] == 3
    assert body["truncated"] is False
    assert body["enumeration_failed_indices"] == 0
    assert body["distinct_pool_count"] == 2
    # Sorted descending by position_count: pool A (2 positions) before pool B (1).
    assert [p["pool_address"] for p in body["pools"]] == ["0xpoola", "0xpoolb"]
    assert body["pools"][0]["position_count"] == 2
    assert body["pools"][1]["position_count"] == 1
    assert body["pools"][0]["token0_symbol"] == "TOKA"
    assert body["pools"][0]["token1_symbol"] == "TOKB"
    assert body["distinct_token_count"] == 4


def test_catalogue_probe_route_returns_502_on_maxfi_error(client, monkeypatch):
    def _boom(chain):
        raise maxfi_client.MaxFiError("simulated RPC failure")
    monkeypatch.setattr(maxfi_client, "get_vault", _boom)

    r = client.get("/api/maxfi/catalogue-probe/base")
    assert r.status_code == 502
    body = r.get_json()
    assert body["error"] == "MaxFiRpcProbeError"
    assert body["detail"] == "simulated RPC failure"


def test_catalogue_probe_route_max_positions_caps_enumeration(client, monkeypatch):
    monkeypatch.setattr(maxfi_client, "get_vault", lambda chain: (_A16_VAULT, []))
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

    r = client.get("/api/maxfi/catalogue-probe/base?max_positions=1")
    assert r.status_code == 200
    body = r.get_json()

    assert captured["count"] == 1
    assert body["enumerated_count"] == 1
    assert body["truncated"] is True
    assert body["npm_position_count"] == 5


# ── LP Advisor Phase A2 commit 2: fetch_dexscreener_pairs ──────────────────

class _FakeDexResponse:
    def __init__(self, status_code=200, json_data=None, json_error=None):
        self.status_code = status_code
        self._json_data = json_data
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._json_data


def test_fetch_dexscreener_pairs_success_returns_pairs_list(monkeypatch):
    fake_pairs = [{"pairAddress": "0xabc"}]
    monkeypatch.setattr(
        maxfi_pooldata.requests, "get",
        lambda *a, **k: _FakeDexResponse(200, {"pairs": fake_pairs}),
    )
    assert maxfi_pooldata.fetch_dexscreener_pairs("base", ["0xabc"]) == fake_pairs


def test_fetch_dexscreener_pairs_null_pairs_normalized_to_empty_list(monkeypatch):
    monkeypatch.setattr(
        maxfi_pooldata.requests, "get",
        lambda *a, **k: _FakeDexResponse(200, {"pairs": None}),
    )
    assert maxfi_pooldata.fetch_dexscreener_pairs("base", ["0xabc"]) == []


def test_fetch_dexscreener_pairs_non_2xx_raises(monkeypatch):
    monkeypatch.setattr(
        maxfi_pooldata.requests, "get",
        lambda *a, **k: _FakeDexResponse(500, {"pairs": []}),
    )
    with pytest.raises(maxfi_pooldata.DexScreenerError):
        maxfi_pooldata.fetch_dexscreener_pairs("base", ["0xabc"])


def test_fetch_dexscreener_pairs_non_json_body_raises(monkeypatch):
    monkeypatch.setattr(
        maxfi_pooldata.requests, "get",
        lambda *a, **k: _FakeDexResponse(200, json_error=ValueError("not json")),
    )
    with pytest.raises(maxfi_pooldata.DexScreenerError):
        maxfi_pooldata.fetch_dexscreener_pairs("base", ["0xabc"])


def test_fetch_dexscreener_pairs_request_exception_raises(monkeypatch):
    def _boom(*a, **k):
        raise requests.RequestException("connection failed")
    monkeypatch.setattr(maxfi_pooldata.requests, "get", _boom)
    with pytest.raises(maxfi_pooldata.DexScreenerError):
        maxfi_pooldata.fetch_dexscreener_pairs("base", ["0xabc"])


def test_fetch_dexscreener_pairs_bad_shape_pairs_raises(monkeypatch):
    monkeypatch.setattr(
        maxfi_pooldata.requests, "get",
        lambda *a, **k: _FakeDexResponse(200, {"pairs": {"not": "a list"}}),
    )
    with pytest.raises(maxfi_pooldata.DexScreenerError):
        maxfi_pooldata.fetch_dexscreener_pairs("base", ["0xabc"])


def test_fetch_dexscreener_pairs_oversized_batch_raises_without_network_call(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must not call requests.get for an oversized batch")
    monkeypatch.setattr(maxfi_pooldata.requests, "get", _boom)

    addresses = [f"0x{i:040x}" for i in range(maxfi_pooldata.DEXSCREENER_PAIRS_BATCH_MAX + 1)]
    with pytest.raises(maxfi_pooldata.DexScreenerError):
        maxfi_pooldata.fetch_dexscreener_pairs("base", addresses)


def test_fetch_dexscreener_pairs_empty_addresses_raises_without_network_call(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must not call requests.get for empty pool_addresses")
    monkeypatch.setattr(maxfi_pooldata.requests, "get", _boom)

    with pytest.raises(maxfi_pooldata.DexScreenerError):
        maxfi_pooldata.fetch_dexscreener_pairs("base", [])


def test_fetch_dexscreener_pairs_builds_url_with_slug_and_joined_addresses(monkeypatch):
    captured = {}

    def _fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        return _FakeDexResponse(200, {"pairs": []})
    monkeypatch.setattr(maxfi_pooldata.requests, "get", _fake_get)

    maxfi_pooldata.fetch_dexscreener_pairs("robinhood", ["0xaaa", "0xbbb"])

    assert "robinhood" in captured["url"]
    assert "0xaaa,0xbbb" in captured["url"]


# ── parse_pair_metrics ───────────────────────────────────────────────────

def _full_pair(**overrides):
    # Representative DexScreener pairs-endpoint shape (priceUsd as string,
    # nested liquidity/volume/priceChange) - not a literal captured payload
    # (none was retained in this repo from the live probe), but matches the
    # documented/observed field shapes this module's docstrings describe.
    pair = {
        "pairAddress": "0xPoolAddress",
        "priceUsd": "1.2345",
        "liquidity": {"usd": 50000.0},
        "volume": {"h24": 100000.0, "h6": 25000.0, "h1": 4000.0},
        "priceChange": {"h24": -3.2},
    }
    pair.update(overrides)
    return pair


def test_parse_pair_metrics_full_pair_parses_all_fields():
    result = maxfi_pooldata.parse_pair_metrics(_full_pair())
    assert result == {
        "pool_address": "0xpooladdress",
        "price_usd": 1.2345,
        "liquidity_usd": 50000.0,
        "volume_h24": 100000.0,
        "volume_h6": 25000.0,
        "volume_h1": 4000.0,
        "price_change_h24": -3.2,
    }


def test_parse_pair_metrics_thin_pair_missing_fields_are_none_others_intact():
    pair = _full_pair(priceChange={}, liquidity={})
    result = maxfi_pooldata.parse_pair_metrics(pair)
    assert result["price_change_h24"] is None
    assert result["liquidity_usd"] is None
    assert result["price_usd"] == 1.2345
    assert result["volume_h24"] == 100000.0


def test_parse_pair_metrics_missing_pair_address_returns_none():
    pair = _full_pair()
    del pair["pairAddress"]
    assert maxfi_pooldata.parse_pair_metrics(pair) is None


def test_parse_pair_metrics_nan_and_inf_volume_become_none():
    pair = _full_pair()
    pair["volume"]["h24"] = float("nan")
    pair["volume"]["h6"] = float("inf")
    result = maxfi_pooldata.parse_pair_metrics(pair)
    assert result["volume_h24"] is None
    assert result["volume_h6"] is None
    assert result["volume_h1"] == 4000.0


# ── summarize_pair_batches ───────────────────────────────────────────────

def test_summarize_pair_batches_splits_preserving_order():
    addresses = [f"0x{i:04x}" for i in range(65)]
    batches = maxfi_pooldata.summarize_pair_batches(addresses)
    assert [len(b) for b in batches] == [30, 30, 5]
    assert [addr for batch in batches for addr in batch] == addresses


def test_summarize_pair_batches_empty_input():
    assert maxfi_pooldata.summarize_pair_batches([]) == []


# ── price_change_pct ─────────────────────────────────────────────────────

def test_price_change_pct_exact_7d_window():
    daily_rows = [("2026-01-01", 100.0), ("2026-01-08", 110.0)]
    pct = maxfi_pooldata.price_change_pct(daily_rows, "2026-01-08", 7)
    assert pct == pytest.approx(10.0)


def test_price_change_pct_gappy_data_hits_tolerance():
    # Target base date is 2026-01-01; nearest actual row is 2026-01-02 (1 day
    # off, within the +/-2 day tolerance).
    daily_rows = [("2026-01-02", 100.0), ("2026-01-08", 120.0)]
    pct = maxfi_pooldata.price_change_pct(daily_rows, "2026-01-08", 7)
    assert pct == pytest.approx(20.0)


def test_price_change_pct_base_beyond_tolerance_is_none():
    # Target base date is 2026-01-01; nearest row is 2026-01-05 (4 days off).
    daily_rows = [("2026-01-05", 100.0), ("2026-01-08", 120.0)]
    pct = maxfi_pooldata.price_change_pct(daily_rows, "2026-01-08", 7)
    assert pct is None


def test_price_change_pct_base_close_zero_is_none():
    daily_rows = [("2026-01-01", 0.0), ("2026-01-08", 110.0)]
    pct = maxfi_pooldata.price_change_pct(daily_rows, "2026-01-08", 7)
    assert pct is None


def test_price_change_pct_empty_rows_is_none():
    assert maxfi_pooldata.price_change_pct([], "2026-01-08", 7) is None


# ── volume_trend_ratio ───────────────────────────────────────────────────

def test_volume_trend_ratio_normal():
    assert maxfi_pooldata.volume_trend_ratio(150.0, 100.0) == pytest.approx(1.5)


def test_volume_trend_ratio_none_input():
    assert maxfi_pooldata.volume_trend_ratio(None, 100.0) is None
    assert maxfi_pooldata.volume_trend_ratio(150.0, None) is None


def test_volume_trend_ratio_zero_trailing_is_none():
    assert maxfi_pooldata.volume_trend_ratio(150.0, 0.0) is None


# ── downtrend_gate ───────────────────────────────────────────────────────

def test_downtrend_gate_both_negative_is_blocked_true():
    daily_rows = [
        ("2025-12-09", 200.0),  # ~30d base
        ("2026-01-01", 150.0),  # ~7d base
        ("2026-01-08", 100.0),  # as-of
    ]
    result = maxfi_pooldata.downtrend_gate(daily_rows, "2026-01-08")
    assert result["pct_7d"] < 0
    assert result["pct_30d"] < 0
    assert result["blocked"] is True


def test_downtrend_gate_one_positive_is_blocked_false():
    # Phase E v1.3: this fixture's 7d move is (100-150)/150*100 = -33.33%,
    # well past POOLDATA_SHARP_DUMP_PCT_7D (-15.0) - the sharp-dump clause
    # now blocks it REGARDLESS of the positive 30d window. Before v1.3 this
    # asserted `assert result["blocked"] is False` (one-positive-window
    # passes); the sharp-dump override is exactly what now prevents that.
    daily_rows = [
        ("2025-12-09", 80.0),   # ~30d base, below as-of -> pct_30d positive
        ("2026-01-01", 150.0),  # ~7d base, above as-of -> pct_7d negative
        ("2026-01-08", 100.0),  # as-of
    ]
    result = maxfi_pooldata.downtrend_gate(daily_rows, "2026-01-08")
    assert result["pct_30d"] >= 0
    assert result["pct_7d"] < 0
    assert result["sharp_dump"] is True
    assert result["blocked"] is True


def test_downtrend_gate_missing_30d_history_is_blocked_true_via_sharp_dump():
    # Phase E v1.3: same -33.33% 7d move as above, but with NO 30d history
    # at all. Before v1.3 this asserted `assert result["blocked"] is None`
    # (unknown 30d -> unresolved). The sharp-dump extension deliberately
    # blocks on a KNOWN sharp weekly dump even when the 30d window is
    # unknown - this is the documented one-directional exception to
    # "unknown surfaces as unknown."
    daily_rows = [
        ("2026-01-01", 150.0),
        ("2026-01-08", 100.0),
    ]
    result = maxfi_pooldata.downtrend_gate(daily_rows, "2026-01-08")
    assert result["pct_7d"] is not None
    assert result["pct_30d"] is None
    assert result["sharp_dump"] is True
    assert result["blocked"] is True


# ── Phase E v1.3: sharp-dump clause ──────────────────────────────────────

def test_downtrend_gate_ai_case_sharp_dump_blocks_despite_strong_month():
    # The live case that motivated the fix: 7d -21.7%, 30d +2245% - the
    # plain both-negative rule passed this (30d is wildly positive), but a
    # -21.7% week is a live dump regardless of the month.
    daily_rows = [
        ("2025-12-09", 3.339019189765458),  # 30d base
        ("2026-01-01", 100.0),              # 7d base
        ("2026-01-08", 78.3),               # as-of / latest
    ]
    result = maxfi_pooldata.downtrend_gate(daily_rows, "2026-01-08")
    assert result["pct_7d"] == pytest.approx(-21.7)
    assert result["pct_30d"] == pytest.approx(2245.0)
    assert result["sharp_dump"] is True
    assert result["blocked"] is True


def test_downtrend_gate_exactly_at_sharp_dump_boundary_is_not_sharp():
    # Strictness: pct_7d exactly -15.0 is NOT sharp (strict <). 30d positive
    # here too, so the old rule alone would also give blocked False - this
    # pins that the boundary itself doesn't misfire, not just the outcome.
    daily_rows = [
        ("2025-12-09", 50.0),   # 30d base -> pct_30d = +70%
        ("2026-01-01", 100.0),  # 7d base
        ("2026-01-08", 85.0),   # as-of -> pct_7d = exactly -15.0
    ]
    result = maxfi_pooldata.downtrend_gate(daily_rows, "2026-01-08")
    assert result["pct_7d"] == pytest.approx(-15.0)
    assert result["sharp_dump"] is False
    assert result["blocked"] is False


def test_downtrend_gate_mild_dip_and_recovery_entry_types_preserved():
    # Neither leg of a normal (non-dump) entry pattern trips the new clause.
    mild_dip = [
        ("2025-12-09", 64.66666666666667),  # 30d base -> pct_30d = +50%
        ("2026-01-01", 100.0),
        ("2026-01-08", 97.0),               # pct_7d = -3%
    ]
    result = maxfi_pooldata.downtrend_gate(mild_dip, "2026-01-08")
    assert result["pct_7d"] == pytest.approx(-3.0)
    assert result["sharp_dump"] is False
    assert result["blocked"] is False

    recovery = [
        ("2025-12-09", 180.0),  # 30d base -> pct_30d = -40%
        ("2026-01-01", 100.0),
        ("2026-01-08", 108.0),  # pct_7d = +8%
    ]
    result = maxfi_pooldata.downtrend_gate(recovery, "2026-01-08")
    assert result["pct_7d"] == pytest.approx(8.0)
    assert result["sharp_dump"] is False
    assert result["blocked"] is False


def test_downtrend_gate_both_mildly_negative_old_rule_intact():
    # -3% 7d / -5% 30d: both negative but neither sharp - the old
    # both-negative rule alone decides, byte-identical to pre-v1.3.
    daily_rows = [
        ("2025-12-09", 102.10526315789474),  # 30d base -> pct_30d = -5%
        ("2026-01-01", 100.0),
        ("2026-01-08", 97.0),                # pct_7d = -3%
    ]
    result = maxfi_pooldata.downtrend_gate(daily_rows, "2026-01-08")
    assert result["pct_7d"] == pytest.approx(-3.0)
    assert result["pct_30d"] == pytest.approx(-5.0)
    assert result["sharp_dump"] is False
    assert result["blocked"] is True


def test_downtrend_gate_sharp_dump_with_unknown_30d_still_blocks():
    # The extension itself: a known sharp 7d dump (-20%) with NO 30d history
    # at all blocks outright - an unknown 30d no longer rescues a known
    # sharp dump into an unresolved None.
    daily_rows = [
        ("2026-01-01", 100.0),
        ("2026-01-08", 80.0),  # pct_7d = -20%
    ]
    result = maxfi_pooldata.downtrend_gate(daily_rows, "2026-01-08")
    assert result["pct_7d"] == pytest.approx(-20.0)
    assert result["pct_30d"] is None
    assert result["sharp_dump"] is True
    assert result["blocked"] is True


def test_downtrend_gate_unknown_7d_leaves_sharp_dump_none():
    # An unknown 7d still tells you nothing - sharp_dump stays None (never
    # coerced to False), and blocked follows the ordinary either-is-None
    # -> None path.
    result = maxfi_pooldata.downtrend_gate([], "2026-01-08")
    assert result["pct_7d"] is None
    assert result["sharp_dump"] is None
    assert result["blocked"] is None
