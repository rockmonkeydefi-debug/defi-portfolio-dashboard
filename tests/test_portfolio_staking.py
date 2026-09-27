"""/api/portfolio's additive staking_positions list (Total portfolio value,
commit A).

Zerion's staking bucket (position_type staked / locked / deposit / reward) was
categorized by categorize_zerion_positions and then silently dropped by
get_portfolio_data. It is now mapped by map_zerion_staking_to_app and exposed
as staking_positions - reported only, counted in NO total.

No network: every Zerion / RPC seam get_portfolio_data touches is stubbed, and
requests.get/post raise if anything tries to reach the network anyway."""
import pytest
import requests

import web_portfolio as wp
from src.connectors import zerion as zc

WALLET = "0x" + "5" * 40


def _pos(pos_type, symbol, value, chain="base", protocol=None, module=None, app_name=None, quantity=1.0):
    attrs = {
        "position_type": pos_type,
        "quantity": {"float": quantity},
        "value": value,
        "price": value / quantity if quantity else 0.0,
        "fungible_info": {"symbol": symbol, "implementations": [{"chain_id": chain, "address": "0x" + "c" * 40}]},
    }
    if protocol is not None:
        attrs["protocol"] = protocol
    if module is not None:
        attrs["protocol_module"] = module
    if app_name is not None:
        attrs["application_metadata"] = {"name": app_name}
    return {"id": f"{symbol}-{pos_type}", "attributes": attrs,
            "relationships": {"chain": {"data": {"id": chain}}}}


# ── mapper shape ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("pos_type, app_name, protocol, module, want_protocol, want_module", [
    ("staked", "Lido", "lido", "staked", "Lido", "staked"),
    ("locked", None, "velodrome", "locked", "velodrome", "locked"),
    ("deposit", None, None, None, "", ""),
])
def test_staking_mapper_shape(pos_type, app_name, protocol, module, want_protocol, want_module):
    pos = _pos(pos_type, "STK", 40.0, protocol=protocol, module=module, app_name=app_name, quantity=2.0)
    row = zc.map_zerion_staking_to_app(pos, WALLET, "Main")
    base = zc.map_zerion_token_to_app(pos, WALLET, "Main")
    assert {k: row[k] for k in base} == base                  # every token field, unchanged
    assert row["position_type"] == pos_type
    assert row["protocol"] == want_protocol
    assert row["protocol_module"] == want_module
    assert set(row) == set(base) | {"position_type", "protocol", "protocol_module"}
    assert (row["symbol"], row["value_usd"], row["balance"], row["chain"]) == ("STK", 40.0, 2.0, zc.get_chain_name("base"))


def test_categorize_sends_these_to_staking():
    out = zc.categorize_zerion_positions([
        _pos("wallet", "ETH", 100.0), _pos("staked", "STK", 40.0), _pos("locked", "LCK", 1.0),
        _pos("deposit", "DEP", 1.0), _pos("reward", "RWD", 1.0)])
    assert [p["id"] for p in out["staking"]] == ["STK-staked", "LCK-locked", "DEP-deposit", "RWD-reward"]
    assert [p["id"] for p in out["tokens"]] == ["ETH-wallet"]


# ── get_portfolio_data: staking exposed, counted nowhere ───────────────────

@pytest.fixture
def stubbed_portfolio(monkeypatch):
    """One EVM wallet, Zerion configured, every other seam inert."""
    monkeypatch.setattr(wp, "_portfolio_cache", None)
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [WALLET])
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {WALLET: {"label": "Main"}})
    monkeypatch.setattr(wp.ZerionConnector, "is_configured", lambda self: True)
    monkeypatch.setattr(wp.ZerionConnector, "get_wallet_positions",
                        lambda self, wallet: [_pos("wallet", "ETH", 100.0),
                                              _pos("staked", "STK", 40.0, app_name="Lido", module="staked")])
    monkeypatch.setattr(wp.ZerionConnector, "get_wallet_transactions", lambda self, *a, **k: [])
    import src.models
    monkeypatch.setattr(src.models, "get_web3", lambda *a, **k: None)
    monkeypatch.setattr(wp, "build_custom_token_rows", lambda *a, **k: [])

    def _no_network(*a, **k):
        raise AssertionError("network call attempted")
    monkeypatch.setattr(requests, "get", _no_network)
    monkeypatch.setattr(requests, "post", _no_network)
    monkeypatch.setattr(requests.Session, "request", _no_network)
    yield
    wp._portfolio_cache = None


def test_get_portfolio_data_exposes_staking_and_counts_it_nowhere(stubbed_portfolio):
    data = wp.get_portfolio_data(force_refresh=True)
    assert [(r["symbol"], r["value_usd"], r["position_type"], r["protocol"]) for r in data["staking_positions"]] == [
        ("STK", 40.0, "staked", "Lido")]
    assert data["total_tokens_value"] == 100
    assert data["total_value"] == 100
    assert [t["symbol"] for t in data["tokens"]] == ["ETH"]
    assert data["api_failures"] == []


def test_set_cached_tokens_keeps_staking_positions(stubbed_portfolio):
    wp.get_portfolio_data(force_refresh=True)
    wp._set_cached_tokens(list(wp._portfolio_cache["tokens"]))
    assert [r["symbol"] for r in wp._portfolio_cache["staking_positions"]] == ["STK"]
    assert wp._portfolio_cache["total_value"] == 100
