"""Open perps (Dashboard OPEN PERPS card, P1): hl_trades.open_position_rows
(stop / take-profit selection, coverage, risk-if-stopped, flags), the extra
per-position fields and the frontendOpenOrders read in _hl_fetch_accounts,
and GET /api/trading/perps/open (cache-only, wallet labels only).

No network: every Hyperliquid call is a fake post, and the route test stubs
_hl_post with a function that raises. Fake wallet addresses only. The
recorded open-orders fixture in tests/fixtures/hl_trading is read-only.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import json
import os
import threading
from decimal import Decimal

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import hl_trades

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "hl_trading")
W1 = "0x" + "1" * 40
W2 = "0x" + "2" * 40
W3 = "0x" + "3" * 40


def pos(coin="ETH", szi="2", entry="100", value="220", upnl="20", **extra):
    p = {"coin": coin, "szi": szi, "entry_px": entry, "unrealized_pnl": upnl, "cum_funding_since_open": "-0.75",
         "position_value": value, "liquidation_px": "60.5", "margin_used": "44", "return_on_equity": "0.45",
         "leverage": 5, "leverage_type": "cross"}
    p.update(extra)
    return p


def order(coin="ETH", side="A", trigger="95", kind="Stop Market", sz="2", reduce_only=True, tpsl=False, trig=True):
    return {"coin": coin, "side": side, "triggerPx": trigger, "orderType": kind, "sz": sz, "isTrigger": trig,
            "reduceOnly": reduce_only, "isPositionTpsl": tpsl, "limitPx": trigger, "oid": 1, "timestamp": 1}


def one(rows):
    assert len(rows) == 1
    return rows[0]


# ── open_position_rows ───────────────────────────────────────────────────

def test_long_with_stop_and_tp():
    r = one(hl_trades.open_position_rows([pos()], [order(), order(trigger="130", kind="Take Profit Market")]))
    assert (r["coin"], r["direction"], r["size"], r["entry_px"]) == ("ETH", "long", "2.000000", "100.000000")
    assert r["mark_px"] == "110.000000" and r["position_value"] == "220.000000"
    assert r["unrealized_pnl"] == "20.000000" and r["unrealized_pct"] == "10.000000"
    assert r["stop_px"] == "95.000000" and r["tp_px"] == "130.000000"
    assert r["if_stopped_pnl"] == "-10.000000"                    # (95 - 100) x 2
    assert r["stop_distance_pct"] == str(((Decimal(95) - 110) / 110 * 100).quantize(Decimal("0.000001")))
    assert (r["liquidation_px"], r["margin_used"], r["leverage"], r["leverage_type"]) == ("60.500000", "44.000000", 5, "cross")
    assert r["funding_since_open"] == "-0.75" and r["flags"] == []
    assert set(r) == {"coin", "direction", "size", "entry_px", "mark_px", "position_value", "unrealized_pnl",
                      "unrealized_pct", "stop_px", "stop_distance_pct", "if_stopped_pnl", "tp_px", "liquidation_px",
                      "leverage", "leverage_type", "margin_used", "funding_since_open", "flags"}


def test_short_with_stop():
    p = pos(szi="-3", entry="50", value="135", upnl="15")          # mark 45, a winning short
    r = one(hl_trades.open_position_rows([p], [order(side="B", trigger="55", sz="3")]))
    assert (r["direction"], r["size"], r["mark_px"]) == ("short", "3.000000", "45.000000")
    assert r["unrealized_pct"] == "10.000000"                     # (45 - 50) / 50 x 100, negated
    assert r["stop_px"] == "55.000000" and r["if_stopped_pnl"] == "-15.000000"   # -(55 - 50) x 3
    assert Decimal(r["stop_distance_pct"]) > 0                     # stop above the mark


def test_two_stops_pick_the_tightest():
    long_ = one(hl_trades.open_position_rows([pos()], [order(trigger="90"), order(trigger="97")]))
    assert long_["stop_px"] == "97.000000"
    short = one(hl_trades.open_position_rows([pos(szi="-2", value="180")],
                                              [order(side="B", trigger="120"), order(side="B", trigger="105")]))
    assert short["stop_px"] == "105.000000"


def test_take_profit_picks_the_nearest():
    long_ = one(hl_trades.open_position_rows([pos()], [order(trigger="150", kind="Take Profit Market"),
                                                       order(trigger="130", kind="Take Profit Limit")]))
    assert long_["tp_px"] == "130.000000"
    short = one(hl_trades.open_position_rows([pos(szi="-2", value="180")],
                                              [order(side="B", trigger="70", kind="Take Profit Market"),
                                               order(side="B", trigger="80", kind="Take Profit Market")]))
    assert short["tp_px"] == "80.000000"


def test_position_tpsl_with_zero_size_covers_everything():
    stop = order(sz="0.0", reduce_only=False, tpsl=True)
    r = one(hl_trades.open_position_rows([pos()], [stop]))
    assert r["stop_px"] == "95.000000" and r["if_stopped_pnl"] == "-10.000000" and "stop_partial" not in r["flags"]


def test_partial_stop():
    r = one(hl_trades.open_position_rows([pos()], [order(sz="0.5")]))
    assert r["flags"] == ["stop_partial"]
    assert r["if_stopped_pnl"] == "-2.500000"                      # (95 - 100) x 0.5


def test_ignored_orders():
    ignored = [order(side="B"),                                    # same side as a long: not a closing order
               order(coin="BTC"),                                  # other coin
               order(reduce_only=False),                           # neither reduce-only nor position TP/SL
               order(trig=False),                                  # not a trigger order
               order(trigger="0.0"),                               # no trigger price
               order(kind="Limit")]                                # neither stop nor take-profit
    r = one(hl_trades.open_position_rows([pos()], ignored))
    assert r["flags"] == ["no_stop"]
    assert (r["stop_px"], r["tp_px"], r["if_stopped_pnl"], r["stop_distance_pct"]) == (None, None, None, None)


def test_no_stop():
    r = one(hl_trades.open_position_rows([pos()], []))
    assert r["flags"] == ["no_stop"] and r["stop_px"] is None and r["if_stopped_pnl"] is None


def test_open_orders_unavailable():
    r = one(hl_trades.open_position_rows([pos()], None))
    assert r["flags"] == ["open_orders_unavailable"]
    assert (r["stop_px"], r["tp_px"], r["if_stopped_pnl"], r["stop_distance_pct"]) == (None, None, None, None)
    assert r["mark_px"] == "110.000000"


def test_zero_or_missing_size_is_skipped():
    assert hl_trades.open_position_rows([pos(szi="0.0"), pos(szi=None), {"coin": "X"}], []) == []


def test_missing_values_give_none():
    r = one(hl_trades.open_position_rows([pos(value=None, entry=None, upnl=None)], [order()]))
    assert (r["mark_px"], r["unrealized_pct"], r["entry_px"], r["position_value"]) == (None, None, None, None)
    assert r["stop_px"] == "95.000000" and r["if_stopped_pnl"] is None and r["stop_distance_pct"] is None


def test_recorded_open_orders_fixture():
    with open(os.path.join(FIX, "rabby.open_orders.json")) as f:
        orders = json.load(f)
    r = one(hl_trades.open_position_rows([pos(coin="ZRO", szi="577.2", entry="1.8", value="1096.68", upnl="57.72")],
                                         orders))
    assert (r["stop_px"], r["tp_px"]) == ("1.570700", "2.422720")
    assert r["flags"] == []                                        # the stop's 577.2 covers the position


# ── _hl_fetch_accounts ───────────────────────────────────────────────────

def _fake_post(open_orders_by_wallet, calls):
    full = {"coin": "ETH", "szi": "1.5", "entryPx": "2000.0", "positionValue": "3150.0", "unrealizedPnl": "150.0",
            "returnOnEquity": "0.25", "liquidationPx": "1500.5", "marginUsed": "630.0",
            "leverage": {"type": "cross", "value": 5}, "cumFunding": {"allTime": "-1.0", "sinceOpen": "-0.5"}}

    def post(payload):
        calls.append(dict(payload))
        t, user = payload["type"], payload.get("user")
        if t == "spotMetaAndAssetCtxs":
            return [{"tokens": [], "universe": []}, []]
        if t == "clearinghouseState":
            if user == W3:
                return {"marginSummary": {"accountValue": "5"}, "assetPositions": [{"position": {}}]}
            return {"marginSummary": {"accountValue": "100"}, "assetPositions": [{"position": full}]}
        if t == "spotClearinghouseState":
            return {"balances": []}
        if t == "userAbstraction":
            return "default"
        if t == "frontendOpenOrders":
            v = open_orders_by_wallet[user]
            if isinstance(v, Exception):
                raise v
            return v
        raise AssertionError(t)
    return post


def test_fetch_accounts_reads_open_orders_only_with_positions():
    calls = []
    oo = [order(coin="ETH", trigger="1900")]
    res = wp._hl_fetch_accounts([W1, W2, W3], post=_fake_post({W1: oo, W2: {"odd": True}}, calls))
    assert res["errors"] == {}
    assert sorted(c["user"] for c in calls if c["type"] == "frontendOpenOrders") == [W1, W2]
    assert res["wallets"][W1]["open_orders"] == oo and "open_orders_error" not in res["wallets"][W1]
    assert res["wallets"][W2]["open_orders"] is None
    assert res["wallets"][W2]["open_orders_error"] == "unexpected frontendOpenOrders response: dict"
    assert res["wallets"][W3]["open_orders"] == [] and res["wallets"][W3]["positions"] == []
    (p,) = res["wallets"][W1]["positions"]
    assert {k: p[k] for k in ("position_value", "liquidation_px", "margin_used", "return_on_equity", "leverage",
                              "leverage_type")} == {"position_value": "3150.0", "liquidation_px": "1500.5",
                                                    "margin_used": "630.0", "return_on_equity": "0.25",
                                                    "leverage": 5, "leverage_type": "cross"}


def test_fetch_accounts_open_orders_failure_keeps_the_wallet():
    res = wp._hl_fetch_accounts([W1], post=_fake_post({W1: ConnectionError("down")}, []))
    assert res["errors"] == {}
    w = res["wallets"][W1]
    assert w["open_orders"] is None and w["open_orders_error"] == "ConnectionError: down"
    assert w["perp_account_value"] == 100.0 and w["mode"] == "default"


# ── GET /api/trading/perps/open ──────────────────────────────────────────

def _never_post(*a, **k):
    raise AssertionError("Hyperliquid must not be called on a request path")


@pytest.fixture
def client(monkeypatch):
    kicks = []
    monkeypatch.setattr(wp, "_hl_post", _never_post)
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", lambda now: kicks.append(now) or False)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {W1: {"label": "Hyperliquid RM"}, W2: {"label": "Rabby"}})
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    c.kicks = kicks
    return c


def _state(fetched_at="2026-10-01T12:00:00+00:00"):
    return {"fetched_at": fetched_at, "error": None, "wallets": {
        W1: {"positions": [pos(), pos(coin="BTC", szi="-0.1", entry="60000", value="5900", upnl="100",
                                  liquidation_px="70000")],
             "open_orders": [order(), order(coin="BTC", side="B", trigger="61000", sz="0.1")]},
        W2: {"stale": True, "error": "ConnectionError: " + W2,
             "positions": [pos(coin="SOL", szi="10", entry="150", value="1400", upnl="-100")],
             "open_orders": None, "open_orders_error": "ConnectionError: timeout for " + W2},
    }}


def test_route_lists_positions_with_labels_only(client, monkeypatch):
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: _state())
    r = client.get('/api/trading/perps/open')
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert W1 not in text and W2 not in text and W1[2:] not in text and W2[2:] not in text
    body = r.get_json()
    ps = body["positions"]
    assert [(p["coin"], p["wallet_label"]) for p in ps] == [("BTC", "Hyperliquid RM"), ("SOL", "Rabby"),
                                                           ("ETH", "Hyperliquid RM")]   # value desc
    assert all(p["venue"] == "Hyperliquid" for p in ps)
    sol = ps[1]
    assert sol["stale"] is True and sol["flags"] == ["open_orders_unavailable"]
    assert sol["open_orders_error"] == "ConnectionError: timeout for Rabby"
    btc = ps[0]
    assert btc["direction"] == "short" and btc["stop_px"] == "61000.000000"
    assert btc["if_stopped_pnl"] == "-100.000000" and btc["stale"] is False and btc["open_orders_error"] is None
    assert body["totals"] == {"open_count": 3, "notional": "7520.000000", "unrealized": "20.000000",
                              "if_stopped": "-110.000000", "no_stop_count": 1}
    assert body["venues"] == [{"venue": "Hyperliquid", "status": "ok", "as_of": "2026-10-01T12:00:00+00:00",
                               "error": None}]
    assert len(client.kicks) == 1


def test_route_loading_and_error(client, monkeypatch):
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": None, "error": None, "wallets": {}})
    body = client.get('/api/trading/perps/open').get_json()
    assert body["positions"] == [] and body["venues"][0]["status"] == "loading"
    assert body["totals"] == {"open_count": 0, "notional": "0.000000", "unrealized": "0.000000",
                              "if_stopped": "0.000000", "no_stop_count": 0}
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {
        "fetched_at": None, "error": "every wallet failed: " + W1 + ": ConnectionError", "wallets": {}})
    r = client.get('/api/trading/perps/open')
    venue = r.get_json()["venues"][0]
    assert venue["status"] == "error" and venue["error"] == "every wallet failed: Hyperliquid RM: ConnectionError"
    assert W1 not in r.get_data(as_text=True)
    assert len(client.kicks) == 2


def test_route_survives_a_failing_kick(client, monkeypatch):
    def boom(now):
        raise RuntimeError("no threads")
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", boom)
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: _state())
    assert client.get('/api/trading/perps/open').status_code == 200
