"""Per-wallet perp venues (P3b): PUT /api/wallets/<address> perp_venues
validation and storage, GET /api/wallets perp_venues + perp_venue_options,
_txflow_wallets (Settings-flagged wallets plus the TXFLOW_WALLETS fallback)
and a Settings-flagged TxFlow wallet on GET /api/trading/perps/open.

In-memory wallet config (load_wallet_config / save_wallet_config stubbed); no
network (TxFlow / Hyperliquid posts raise, kicks are recorded). Fake wallet
addresses only.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import copy
import json
import os
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "txflow", "clearinghouseState.json")
EA = "0x" + "a" * 40
EB = "0x" + "b" * 40
EC = "0x" + "c" * 40
SOL = "So1" + "x" * 41                      # a Solana-style (non-0x) key


def _never(*a, **k):
    raise AssertionError("no venue call on a request path")


@pytest.fixture
def store(monkeypatch):
    cfg = {EA: {"label": "Main", "hidden": False, "maxfi": True},
           EB: {"label": "Hidden one", "hidden": True},
           SOL: {"label": "Phantom", "type": "solana"}}
    box = {"cfg": cfg}
    monkeypatch.setattr(wp, "load_wallet_config", lambda: copy.deepcopy(box["cfg"]))
    monkeypatch.setattr(wp, "save_wallet_config", lambda c: box.__setitem__("cfg", copy.deepcopy(c)))
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    return box


@pytest.fixture
def client(store, monkeypatch):
    kicks = {"hl": [], "tx": []}
    monkeypatch.setattr(wp, "_hl_post", _never)
    monkeypatch.setattr(wp, "_txflow_post", _never)
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", lambda now: kicks["hl"].append(now) or False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", lambda now: kicks["tx"].append(now) or False)
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    c.kicks = kicks
    return c


def put(client, addr, body):
    return client.put('/api/wallets/' + addr, json=body)


# ── PUT /api/wallets/<address> ───────────────────────────────────────────

@pytest.mark.parametrize("bad", ["txflow", ["txflow", 1], ["hyperliquid"], None, {"txflow": True}])
def test_put_rejects_bad_perp_venues(client, store, bad):
    before = copy.deepcopy(store["cfg"])
    r = put(client, EA, {"perp_venues": bad})
    assert r.status_code == 400 and r.get_json() == {"error": "perp_venues must be a list of: txflow"}
    assert store["cfg"] == before


def test_put_txflow_needs_an_0x_wallet(client, store):
    r = put(client, SOL, {"perp_venues": ["txflow"]})
    assert r.status_code == 400 and r.get_json() == {"error": "TxFlow needs an 0x wallet"}
    assert "perp_venues" not in store["cfg"][SOL]
    assert put(client, SOL, {"perp_venues": []}).status_code == 200      # clearing is fine on any wallet


def test_put_stores_sorted_deduped_and_clears(client, store):
    r = put(client, EA, {"perp_venues": ["txflow", "txflow"]})
    assert r.status_code == 200 and r.get_json() == {"success": True}
    assert store["cfg"][EA]["perp_venues"] == ["txflow"]
    assert store["cfg"][EA]["maxfi"] is True and store["cfg"][EA]["hidden"] is False   # untouched
    assert put(client, EA.upper().replace("0X", "0x"), {"perp_venues": []}).status_code == 200
    assert store["cfg"][EA]["perp_venues"] == []


def test_put_nothing_to_update(client):
    r = put(client, EA, {})
    assert r.status_code == 400 and r.get_json() == {"error": "Nothing to update"}


# ── GET /api/wallets ─────────────────────────────────────────────────────

def test_get_returns_perp_venues(client, store):
    store["cfg"][EA]["perp_venues"] = ["txflow", "unknown"]
    store["cfg"][EB]["perp_venues"] = "txflow"
    body = client.get('/api/wallets').get_json()
    by = {w["address"]: w for w in body["wallets"]}
    assert by[EA]["perp_venues"] == ["txflow"]
    assert by[EB]["perp_venues"] == [] and by[SOL]["perp_venues"] == []
    assert by[EA]["maxfi"] is True and by[EB]["visible"] is False and by[EA]["label"] == "Main"
    assert body["perp_venue_options"] == [{"key": "txflow", "label": "TxFlow"}]


# ── _txflow_wallets ──────────────────────────────────────────────────────

def test_txflow_wallets_sources(monkeypatch):
    flagged = {EA: {"perp_venues": ["txflow"]}, EB: {"hidden": True, "perp_venues": ["txflow"]},
               EC: {"perp_venues": []}, SOL: {"perp_venues": ["txflow"]}, "0x" + "d" * 40: "not a dict"}
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    assert wp._txflow_wallets(flagged) == [EA, EB]                       # hidden included; non-0x / non-dict ignored
    monkeypatch.setenv("TXFLOW_WALLETS", EC)
    assert wp._txflow_wallets({}) == [EC]                                # variable only
    monkeypatch.setenv("TXFLOW_WALLETS", EB.upper().replace("0X", "0x") + "," + EC)
    assert wp._txflow_wallets(flagged) == [EA, EB, EC]                   # config first, deduped case-insensitively
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {EA: {"perp_venues": ["txflow"]}})
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    assert wp._txflow_wallets() == [EA]                                  # default reads the wallet config


# ── GET /api/trading/perps/open ──────────────────────────────────────────

def test_route_with_a_settings_flagged_wallet(client, store, monkeypatch):
    store["cfg"][EC] = {"label": "My TxFlow", "perp_venues": ["txflow"]}
    with open(FIX) as f:
        fixture = json.load(f)
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": "2026-10-01T12:00:00+00:00",
                                                               "error": None, "wallets": {}})
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": "2026-10-01T12:05:00+00:00", "error": None,
                                             "wallets": {EC: {"state": fixture}}})
    r = client.get('/api/trading/perps/open')
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert EC not in text and EC[2:] not in text
    body = r.get_json()
    assert [v["venue"] for v in body["venues"]] == ["Hyperliquid", "TxFlow"]
    assert [(p["venue"], p["wallet_label"], p["coin"]) for p in body["positions"]] == [("TxFlow", "My TxFlow", "HYPE")]
    assert len(client.kicks["tx"]) == 1
