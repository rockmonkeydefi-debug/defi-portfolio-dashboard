"""Tests for maxfi_pooldata (LP Advisor Phase A1): the pure
discover_projects/discover_chains/filter_pools/summarize_field_availability
helpers, the single network seam fetch_llama_pools (monkeypatched
requests.get, never a real HTTP call), and the read-only probe route
GET /api/maxfi/pooldata-probe.

Uses the same client-fixture pattern as tests/test_maxfi_claims_routes.py -
the probe route makes no DB calls at all, so no DB fixture is needed here.
"""
import pytest
import requests

import maxfi_pooldata
import web_portfolio as wp


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


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


def test_probe_route_reports_candidates_and_passes_raw_dicts_through(client, monkeypatch):
    monkeypatch.setattr(maxfi_pooldata, "fetch_llama_pools", lambda: _FAKE_CATALOGUE)

    r = client.get("/api/maxfi/pooldata-probe")
    assert r.status_code == 200
    body = r.get_json()

    assert body["candidate_projects"] == ["maxfi-v1"]
    assert body["robinhood_chains"] == ["Robinhood"]
    assert body["total_pool_count"] == 3
    assert body["sample_project_matched"] == [_FAKE_CATALOGUE[0]]


def test_probe_route_returns_502_on_llama_error(client, monkeypatch):
    def _boom():
        raise maxfi_pooldata.LlamaError("simulated failure")
    monkeypatch.setattr(maxfi_pooldata, "fetch_llama_pools", _boom)

    r = client.get("/api/maxfi/pooldata-probe")
    assert r.status_code == 502
    body = r.get_json()
    assert body["error"] == "LlamaError"
    assert body["detail"] == "simulated failure"
