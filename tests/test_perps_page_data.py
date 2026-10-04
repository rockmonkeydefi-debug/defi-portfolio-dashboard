"""Perps page data (Landing 3a, HANDOFF_spot_perps_rebuild.md 3.4 and 11):
the pure take-profit helpers (hl_trades.take_profits, txflow.take_profits),
the "live" view on open Hyperliquid and TxFlow trades, "leverage" /
"leverage_type" / "target_px" on every trade, "untracked_positions" (live
venue positions with no open trade yet) and the per-venue "sync" status in
GET /api/trading/trades.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). Hyperliquid trades come from synthetic fills written
straight into hl_fills; TxFlow trades from the recorded fixtures in
tests/fixtures/txflow through the real sync worker and a fake post. The
venue caches are set in memory. No network: _hl_post and _txflow_post
raise. Fake wallet addresses only, built in code; amounts are made up.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import copy
import json
import os
import threading
from datetime import datetime, timezone

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import hl_trades
import txflow
import src.storage.portfolio_db as portfolio_db

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "txflow")
W_HL = "0x" + "d" * 40
W_HL2 = "0x" + "e" * 40
W_TX = "0x" + "c" * 40
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
T0 = 1790000000000                      # 2026-09-21: after the gate start
H = 3600000
CONFIG = {W_HL: {"label": "HL main"}, W_HL2: {"label": "HL side"},
          W_TX: {"label": "TxFlow main", "perp_venues": ["txflow"]}}


def _never(*a, **k):
    raise AssertionError("no venue call here")


def _load(name):
    with open(os.path.join(FIX, f"{name}.json")) as f:
        return json.load(f)


class FakeTxPost:
    """The recorded TxFlow answers by request type (tests/test_txflow_trades.py)."""

    def __init__(self, state):
        self.state = state

    def __call__(self, body):
        kind = body["type"]
        if kind == "clearinghouseState":
            return copy.deepcopy(self.state)
        if kind == "userFills":
            return _load("userFills")
        if kind == "historicalOrders":
            return _load("historicalOrders")
        raise AssertionError(f"unexpected request {kind}")


def pos(coin="ETH", szi="2", entry="100", value="220", upnl="20", lev=5, lev_type="cross", liq="60.5"):
    """One cached Hyperliquid position (_hl_positions_from_state's shape)."""
    return {"coin": coin, "szi": szi, "entry_px": entry, "unrealized_pnl": upnl, "cum_funding_since_open": "-0.75",
            "position_value": value, "liquidation_px": liq, "margin_used": "44", "return_on_equity": "0.45",
            "leverage": lev, "leverage_type": lev_type}


def order(coin="ETH", side="A", trigger="95", kind="Stop Market", sz="2", reduce_only=True, tpsl=False, trig=True):
    return {"coin": coin, "side": side, "triggerPx": trigger, "orderType": kind, "sz": sz, "isTrigger": trig,
            "reduceOnly": reduce_only, "isPositionTpsl": tpsl, "limitPx": trigger, "oid": 1, "timestamp": 1}


def fill(coin, tid, time_ms, side, sz, px, start, closed_pnl="0", fee="0.1"):
    return {"coin": coin, "tid": tid, "time": time_ms, "side": side, "sz": sz, "px": px, "startPosition": start,
            "closedPnl": closed_pnl, "fee": fee, "builderFee": "0", "dir": "Open Long", "oid": tid, "hash": "0x0"}


def add_fills(conn, wallet, fills):
    conn.execute("INSERT OR IGNORE INTO hl_sync_state (wallet, first_seen_at, last_sync_at, last_ok_at) "
                 "VALUES (?, ?, ?, ?)", (wallet, "2026-09-20T00:00:00+00:00", "2026-10-01T11:50:00+00:00",
                                         "2026-10-01T11:50:00+00:00"))
    for f in fills:
        conn.execute("INSERT INTO hl_fills (wallet, tid, coin, time_ms, raw_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (wallet, f["tid"], f["coin"], f["time"], json.dumps(f), "2026-10-01T11:50:00+00:00"))
    conn.commit()


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: CONFIG)
    monkeypatch.setattr(wp, "_hl_post", _never)
    monkeypatch.setattr(wp, "_txflow_post", _never)
    monkeypatch.setattr(wp, "_HL_TRADES_IN_FLIGHT", False)
    monkeypatch.setattr(wp, "_TXFLOW_TRADES_IN_FLIGHT", False)
    monkeypatch.setattr(wp, "_TXFLOW_TRADES_LAST_KICK", {"at": None})
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": None, "wallets": {}})
    conn = portfolio_db.get_connection()
    yield conn
    conn.close()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(wp, "_maybe_kick_hl_trades_refresh", lambda now, force=False: False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_trades_refresh", lambda now, force=False: False)
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", lambda now: False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", lambda now: False)
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def hl_cache(monkeypatch, wallets, fetched_at=NOW.isoformat()):
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": fetched_at, "wallets": wallets})


def tx_seed(db, monkeypatch, state=None):
    state = state if state is not None else _load("clearinghouseState")
    wp._txflow_trades_refresh_worker(now_utc=NOW, post=FakeTxPost(state))
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": NOW.isoformat(), "error": None,
                                              "wallets": {W_TX: {"state": state, "fetched_at": NOW.isoformat()}}})
    return state


def get(client):
    r = client.get('/api/trading/trades')
    assert r.status_code == 200, r.get_data(as_text=True)
    return r


def open_eth_long(db):
    add_fills(db, W_HL, [fill("ETH", 1, T0, "B", "2", "100", "0")])


# ── a. hl_trades.take_profits ────────────────────────────────────────────

def test_hl_take_profits_long_nearest_first():
    orders = [order(side="A", trigger="130", kind="Take Profit Market"),
              order(side="A", trigger="115", kind="Take Profit Limit"),
              order(side="A", trigger="95", kind="Stop Market")]
    assert hl_trades.take_profits([pos()], orders) == {"ETH": ["115", "130"]}


def test_hl_take_profits_short_nearest_first():
    orders = [order(side="B", trigger="70", kind="Take Profit Market"),
              order(side="B", trigger="85.5", kind="Take Profit Market")]
    assert hl_trades.take_profits([pos(szi="-2")], orders) == {"ETH": ["85.5", "70"]}


def test_hl_take_profits_rules():
    orders = [order(side="B", trigger="130", kind="Take Profit Market"),                    # opening side
              order(side="A", trigger="131", kind="Take Profit Market", reduce_only=False),  # not reduce-only
              order(side="A", trigger="132", kind="Take Profit Market", reduce_only=False, tpsl=True),
              order(side="A", trigger="133", kind="Take Profit Market", trig=False),         # not a trigger
              order(side="A", trigger="0", kind="Take Profit Market"),
              order(coin="BTC", side="A", trigger="140", kind="Take Profit Market"),
              order(side="A", trigger="132.0", kind="Take Profit Market"),                  # same price again
              "not a dict"]
    assert hl_trades.take_profits([pos(), pos(coin="SOL", szi="0")], orders) == {"ETH": ["132"]}


def test_hl_take_profits_none_and_unavailable():
    assert hl_trades.take_profits([pos()], []) == {"ETH": []}
    assert hl_trades.take_profits([pos()], None) == {}
    assert hl_trades.take_profits(None, []) == {}


def test_hl_take_profits_small_prices_keep_their_digits():
    orders = [order(side="A", trigger="0.000012345", kind="Take Profit Market")]
    assert hl_trades.take_profits([pos(coin="kPEPE")], [dict(orders[0], coin="kPEPE")]) == {"kPEPE": ["0.000012345"]}


def test_open_position_rows_are_unchanged():
    row = hl_trades.open_position_rows([pos()], [order(side="A", trigger="130", kind="Take Profit Market")])[0]
    assert "take_profits" not in row and row["tp_px"] == "130"


# ── b. txflow.take_profits ───────────────────────────────────────────────

def test_txflow_take_profits_on_the_fixture():
    assert txflow.take_profits(_load("clearinghouseState")) == {"HYPE": ["104.86"]}


def test_txflow_take_profits_order_and_shapes():
    state = _load("clearinghouseState")
    ap = state["assetPositions"][0]
    ap["tpsl"] += [{"tpTriggerPrice": "99.5"}, {"tpTriggerPrice": "104.860"}, {"tpTriggerPrice": ""}, "x"]
    assert txflow.take_profits(state) == {"HYPE": ["99.5", "104.86"]}
    short = copy.deepcopy(state)
    short["assetPositions"][0]["position"]["szi"] = "-22.14"
    assert txflow.take_profits(short) == {"HYPE": ["104.86", "99.5"]}
    none = copy.deepcopy(state)
    none["assetPositions"][0]["tpsl"] = []
    assert txflow.take_profits(none) == {"HYPE": []}
    unknown = copy.deepcopy(state)
    unknown["assetPositions"][0]["tpsl"] = None
    assert txflow.take_profits(unknown) == {}
    assert txflow.take_profits(None) == {} and txflow.take_profits({"assetPositions": "x"}) == {}


# ── c. the live view on open Hyperliquid trades ──────────────────────────

def test_open_hl_trade_carries_its_live_view(db, client, monkeypatch):
    open_eth_long(db)
    hl_cache(monkeypatch, {W_HL: {"positions": [pos(lev=10, lev_type="isolated")],
                                  "open_orders": [order(side="A", trigger="95"),
                                                  order(side="A", trigger="130", kind="Take Profit Market"),
                                                  order(side="A", trigger="115", kind="Take Profit Market")]}})
    body = get(client).get_json()
    t = next(x for x in body["trades"] if x["source"] == "hyperliquid")
    assert t["status"] == "open" and t["leverage"] == "10" and t["leverage_type"] == "isolated"
    assert t["live"] == {"direction": "long", "size": "2.000000", "entry_px": "100", "mark_px": "110",
                         "position_value": "220.000000", "unrealized_pnl": "20.000000", "leverage": "10",
                         "leverage_type": "isolated", "liquidation_px": "60.5", "stop_px": "95",
                         "take_profits": ["115", "130"], "flags": [], "as_of": NOW.isoformat(), "stale": False}
    assert t["target_px"] is None and body["untracked_positions"] == []


def test_live_view_without_a_cached_position_is_none(db, client):
    open_eth_long(db)
    t = next(x for x in get(client).get_json()["trades"] if x["source"] == "hyperliquid")
    assert t["status"] == "open" and t["live"] is None and t["leverage"] is None


def test_live_view_when_open_orders_failed(db, client, monkeypatch):
    open_eth_long(db)
    hl_cache(monkeypatch, {W_HL: {"positions": [pos()], "open_orders": None, "stale": True}})
    live = next(x for x in get(client).get_json()["trades"] if x["source"] == "hyperliquid")["live"]
    assert live["take_profits"] is None and live["stop_px"] is None
    assert live["flags"] == ["open_orders_unavailable"] and live["stale"] is True


def test_closed_hl_trade_has_no_live_view(db, client, monkeypatch):
    add_fills(db, W_HL, [fill("ETH", 1, T0, "B", "2", "100", "0"),
                         fill("ETH", 2, T0 + H, "A", "2", "110", "2", closed_pnl="20")])
    hl_cache(monkeypatch, {W_HL: {"positions": [pos()], "open_orders": []}})        # a newer position, same coin
    body = get(client).get_json()
    t = next(x for x in body["trades"] if x["source"] == "hyperliquid")
    assert t["status"] == "closed" and t["live"] is None and t["leverage"] is None
    assert [u["symbol"] for u in body["untracked_positions"]] == ["ETH"]


# ── d. untracked positions ───────────────────────────────────────────────

def test_cached_positions_without_an_open_trade_are_untracked(db, client, monkeypatch):
    open_eth_long(db)
    hl_cache(monkeypatch, {W_HL: {"positions": [pos(), pos(coin="SOL", szi="-3", entry="150", value="420")],
                                  "open_orders": []},
                           W_HL2: {"positions": [pos(coin="BTC", szi="0.01", entry="60000", value="610")],
                                   "open_orders": []}})
    body = get(client).get_json()
    assert [(u["venue"], u["wallet_label"], u["symbol"], u["direction"]) for u in body["untracked_positions"]] == [
        ("Hyperliquid", "HL main", "SOL", "short"), ("Hyperliquid", "HL side", "BTC", "long")]
    sol = body["untracked_positions"][0]["live"]
    assert sol["size"] == "3.000000" and sol["take_profits"] == [] and "no_stop" in sol["flags"]
    assert set(body["untracked_positions"][0]) == {"venue", "wallet_label", "symbol", "direction", "live"}


def test_untracked_positions_are_sorted_and_cover_txflow(db, client, monkeypatch):
    state = _load("clearinghouseState")
    extra = copy.deepcopy(state["assetPositions"][0])
    extra["position"]["coin"] = "BTC-USDC"
    state["assetPositions"].append(extra)
    tx_seed(db, monkeypatch, state)
    hl_cache(monkeypatch, {W_HL2: {"positions": [pos(coin="SOL")], "open_orders": []}})
    body = get(client).get_json()
    assert [(u["venue"], u["symbol"]) for u in body["untracked_positions"]] == [("Hyperliquid", "SOL"),
                                                                               ("TxFlow", "BTC")]


# ── e. TxFlow ────────────────────────────────────────────────────────────

def test_open_txflow_trade_carries_its_live_view(db, client, monkeypatch):
    tx_seed(db, monkeypatch)
    body = get(client).get_json()
    h = next(x for x in body["trades"] if x["source"] == "txflow" and x["symbol"] == "HYPE")
    assert h["status"] == "open" and h["leverage"] == "10" and h["leverage_type"] == "cross"
    live = h["live"]
    assert live["take_profits"] == ["104.86"] and live["stop_px"] == "90.21491" and live["size"] == "22.140000"
    assert live["mark_px"] == "93.45594" and live["entry_px"] == "95.9683" and live["as_of"] == NOW.isoformat()
    p = next(x for x in body["trades"] if x["source"] == "txflow" and x["symbol"] == "PENGU")
    assert p["status"] == "closed" and p["live"] is None
    assert body["untracked_positions"] == []


# ── f. manual and spot trades ────────────────────────────────────────────

def test_manual_and_spot_trades_get_the_new_keys(db, client):
    db.execute("INSERT INTO spot_trade_log (ticker, direction, source, entry_price, stop_price, qty, target_price, "
               "entered_at, market) VALUES ('SOL', 'long', 'manual', 100, 95, 2, 112.5, '2026-09-25T10:00:00+00:00', 'perp')")
    db.execute("INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, chain, "
               "contract_address) VALUES ('2026-09-22', 'AAA', 'buy', 10, 1, 10, 'base', ?)", ("0x" + "5" * 40,))
    db.commit()
    trades = get(client).get_json()["trades"]
    m = next(t for t in trades if t["source"] == "manual")
    s = next(t for t in trades if t["source"] == "spot_tx")
    assert (m["live"], m["leverage"], m["leverage_type"], m["target_px"]) == (None, None, None, "112.5")
    assert (s["live"], s["leverage"], s["leverage_type"], s["target_px"]) == (None, None, None, None)


# ── g. sync status ───────────────────────────────────────────────────────

def test_sync_status_per_venue_with_labels_only(db, client, monkeypatch):
    open_eth_long(db)
    db.execute("INSERT INTO hl_sync_state (wallet, first_seen_at, last_sync_at, last_ok_at, last_error) "
               "VALUES (?, ?, ?, ?, ?)", (W_HL2, "2026-09-20T00:00:00+00:00", "2026-10-01T11:55:00+00:00",
                                          "2026-10-01T11:40:00+00:00", "timeout reading " + W_HL2))
    db.commit()
    tx_seed(db, monkeypatch)
    monkeypatch.setattr(wp, "_HL_TRADES_IN_FLIGHT", True)
    r = get(client)
    text = r.get_data(as_text=True)
    for w in (W_HL, W_HL2, W_TX):
        assert w not in text and w[2:] not in text and w.upper()[2:] not in text
    sync = {v["venue"]: v for v in r.get_json()["sync"]}
    assert sync["Hyperliquid"] == {"venue": "Hyperliquid", "wallets": 2, "last_ok_at": "2026-10-01T11:40:00+00:00",
                                   "last_sync_at": "2026-10-01T11:55:00+00:00", "failing": ["HL side"],
                                   "in_flight": True}
    assert sync["TxFlow"]["wallets"] == 1 and sync["TxFlow"]["failing"] == [] and sync["TxFlow"]["in_flight"] is False
    assert wp._trades_dt(sync["TxFlow"]["last_ok_at"]) is not None          # the worker stamps its own clock


def test_sync_status_never_synced_and_missing_venues(db, client, monkeypatch):
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {W_HL: {"label": "HL main"}})
    db.execute("INSERT INTO hl_sync_state (wallet, first_seen_at) VALUES (?, ?)", (W_HL, "2026-09-20T00:00:00+00:00"))
    db.commit()
    sync = get(client).get_json()["sync"]
    assert sync == [{"venue": "Hyperliquid", "wallets": 1, "last_ok_at": None, "last_sync_at": None,
                     "failing": [], "in_flight": False}]


def test_a_txflow_wallet_not_synced_yet_counts(db, client):
    sync = {v["venue"]: v for v in get(client).get_json()["sync"]}
    assert "Hyperliquid" not in sync
    assert sync["TxFlow"] == {"venue": "TxFlow", "wallets": 1, "last_ok_at": None, "last_sync_at": None,
                              "failing": [], "in_flight": False}


# ── h. the route stays read-only and compatible ──────────────────────────

def test_get_writes_nothing(db, client, monkeypatch):
    open_eth_long(db)
    tx_seed(db, monkeypatch)
    tables = ("hl_fills", "hl_sync_state", "txflow_fills", "txflow_sync_state", "trade_annotations", "spot_trade_log")
    before = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    get(client)
    get(client)
    assert {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables} == before


def test_cycles_without_the_new_keys_still_work(db, client, monkeypatch):
    """A substitute _hl_trade_cycles (as some older tests use) without
    "untracked" or "live" keeps the route working."""
    real = wp._hl_trade_cycles

    def old_shape(conn):
        built = real(conn)
        for c in built["cycles"]:
            c.pop("live", None)
        return {"cycles": built["cycles"], "by_wallet": built["by_wallet"], "sync_rows": built["sync_rows"]}

    open_eth_long(db)
    monkeypatch.setattr(wp, "_hl_trade_cycles", old_shape)
    body = get(client).get_json()
    t = next(x for x in body["trades"] if x["source"] == "hyperliquid")
    assert t["live"] is None and body["untracked_positions"] == []


def test_perps_trades_route_keeps_addresses_out(db, client, monkeypatch):
    open_eth_long(db)
    hl_cache(monkeypatch, {W_HL: {"positions": [pos()], "open_orders": []}})
    text = client.get('/api/trading/perps/trades').get_data(as_text=True)
    assert W_HL not in text and W_HL[2:] not in text
