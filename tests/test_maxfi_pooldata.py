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
