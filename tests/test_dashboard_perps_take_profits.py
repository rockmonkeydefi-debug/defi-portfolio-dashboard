"""Landing 66 (Oct 24, Glenn "A, A" after the prototype): the Dashboard's
Open Perps card draws the Perps page's price bar, so GET
/api/trading/perps/open now gives every row its live take-profits.

Each row gains "take_profits": every live take-profit price, nearest first
(hl_trades.take_profits for Hyperliquid, txflow.take_profits for TxFlow, the
lists the Perps page already uses); [] when the position has none; None when
they are unknown (Hyperliquid open orders that could not be read, a TxFlow
position without a tpsl list). "tp_px" (the nearest) is unchanged. The page
side is in tests/test_dashboard_perps_bar_wiring.py.

The routes read the caches only; no venue call, no database. Fake wallet
addresses built in code; web_portfolio spawns a background scheduler on
import, neutralized the usual way.
"""
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

W1 = "0x" + "1" * 40
W2 = "0x" + "2" * 40
TA = "0x" + "a" * 40


def pos(coin="ETH", szi="2", entry="100", value="220", upnl="20"):
    return {"coin": coin, "szi": szi, "entry_px": entry, "unrealized_pnl": upnl, "cum_funding_since_open": "-0.75",
            "position_value": value, "liquidation_px": "60.5", "margin_used": "44", "return_on_equity": "0.45",
            "leverage": 5, "leverage_type": "cross"}


def order(coin="ETH", side="A", trigger="95", kind="Stop Market", sz="2"):
    return {"coin": coin, "side": side, "triggerPx": trigger, "orderType": kind, "sz": sz, "isTrigger": True,
            "reduceOnly": True, "isPositionTpsl": False, "limitPx": trigger, "oid": 1, "timestamp": 1}


def tx_entry(coin, szi, entry_px, mark, value, tpsl):
    p = {"coin": coin, "szi": szi, "entryPx": entry_px, "markPx": mark, "positionValue": value, "unrealizedPnl": "5",
         "liquidationPx": "", "marginUsed": "22", "leverage": {"type": "Cross", "value": 10},
         "cumFunding": {"allTime": "", "sinceOpen": "-0.5", "sinceChange": "-0.5"}}
    e = {"position": p, "type": "OneWay"}
    if tpsl is not None:
        e["tpsl"] = list(tpsl)
    return e


def tp(price):
    return {"slTriggerPrice": "", "tpTriggerPrice": str(price), "quantity": ""}


def sl(price):
    return {"slTriggerPrice": str(price), "tpTriggerPrice": "", "quantity": ""}


def _never(*a, **k):
    raise AssertionError("no venue call on a request path")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "_hl_post", _never)
    monkeypatch.setattr(wp, "_txflow_post", _never)
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", lambda now: False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", lambda now: False)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {W1: {"label": "HL main"}, W2: {"label": "HL two"},
                                                           TA: {"label": "TxFlow main"}})
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": "2026-10-24T12:00:00+00:00", "error": None, "wallets": {
        W1: {"positions": [pos(), pos(coin="BTC", szi="-0.1", entry="60000", value="5900", upnl="100")],
             "open_orders": [order(), order(trigger="130", kind="Take Profit Market", sz="1"),
                             order(trigger="120", kind="Take Profit Market", sz="1"),
                             order(coin="BTC", side="B", trigger="61000", sz="0.1")]},
        W2: {"positions": [pos(coin="SOL", szi="10", entry="150", value="1400", upnl="-100")],
             "open_orders": None, "open_orders_error": "ConnectionError: timeout"}}})
    monkeypatch.setenv("TXFLOW_WALLETS", TA)
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": "2026-10-24T12:05:00+00:00", "error": None, "wallets": {
        TA: {"state": {"assetPositions": [
            tx_entry("HYPE-USDC", "-10", "40", "38", "380", [tp("35"), tp("36"), sl("42")]),
            tx_entry("ARB-USDC", "100", "0.5", "0.52", "52", []),
            tx_entry("OP-USDC", "50", "1.2", "1.3", "65", None)]}}}})
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _rows(client):
    r = client.get('/api/trading/perps/open')
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert W1 not in text and W2 not in text and TA not in text            # labels only, as before
    return {(p["venue"], p["coin"]): p for p in r.get_json()["positions"]}


def test_hyperliquid_rows_carry_every_take_profit(client):
    rows = _rows(client)
    eth = rows[("Hyperliquid", "ETH")]
    assert eth["take_profits"] == ["120", "130"] and eth["tp_px"] == "120"   # nearest first; tp_px unchanged
    assert eth["stop_px"] == "95"
    assert rows[("Hyperliquid", "BTC")]["take_profits"] == []                 # none on the venue
    sol = rows[("Hyperliquid", "SOL")]
    assert sol["take_profits"] is None and sol["flags"] == ["open_orders_unavailable"]   # unknown, not none


def test_txflow_rows_carry_every_take_profit(client):
    rows = _rows(client)
    hype = rows[("TxFlow", "HYPE")]
    assert hype["direction"] == "short" and hype["take_profits"] == ["36", "35"] and hype["tp_px"] == "36"
    assert rows[("TxFlow", "ARB")]["take_profits"] == []
    assert rows[("TxFlow", "OP")]["take_profits"] is None                    # no tpsl list: unknown
    assert all("take_profits" in p for p in rows.values())
