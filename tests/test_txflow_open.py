"""TxFlow on the open-perps view (P3): txflow.open_position_rows (the recorded
clearinghouseState fixture plus synthetic states), the TXFLOW_WALLETS
parsing, the TxFlow background cache (fetch, refresh worker, kick) and the
TxFlow rows / venue on GET /api/trading/perps/open.

No network: every TxFlow call is a fake post, and the route tests stub
_txflow_post and _hl_post with functions that raise. Fake wallet addresses
only. The fixture in tests/fixtures/txflow is read-only.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
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

import hl_trades
import txflow

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "txflow", "clearinghouseState.json")
TA = "0x" + "a" * 40
TB = "0x" + "b" * 40
TC = "0x" + "c" * 40
H1 = "0x" + "1" * 40


def _fixture():
    with open(FIX) as f:
        return json.load(f)


def state(*entries):
    return {"assetPositions": list(entries)}


def entry(szi="2", coin="ETH-USDC", entry_px="100", mark="110", value="220", upnl="20", liq="60", tpsl=(), **extra):
    p = {"coin": coin, "szi": szi, "entryPx": entry_px, "markPx": mark, "positionValue": value, "unrealizedPnl": upnl,
         "liquidationPx": liq, "marginUsed": "22", "leverage": {"type": "Cross", "value": 10},
         "cumFunding": {"allTime": "", "sinceOpen": "-0.5", "sinceChange": "-0.5"}}
    p.update(extra)
    e = {"position": p, "type": "OneWay"}
    if tpsl is not None:
        e["tpsl"] = list(tpsl)
    return e


def sl(price, qty=""):
    return {"slTriggerPrice": str(price), "tpTriggerPrice": "", "quantity": str(qty)}


def tp(price, qty=""):
    return {"slTriggerPrice": "", "tpTriggerPrice": str(price), "quantity": str(qty)}


def one(rows):
    assert len(rows) == 1
    return rows[0]


# ── txflow.open_position_rows ────────────────────────────────────────────

def test_fixture_row():
    r = one(txflow.open_position_rows(_fixture()))
    assert r == {"coin": "HYPE", "direction": "long", "size": "22.140000", "entry_px": "95.9683",
                 "mark_px": "93.45594", "position_value": "2069.115115", "unrealized_pnl": "-55.623046",
                 "unrealized_pct": "-2.617906", "stop_px": "90.21491", "stop_distance_pct": "-3.467976",
                 "if_stopped_pnl": "-127.380055", "tp_px": "104.86", "liquidation_px": "69.7105", "leverage": 10,
                 "leverage_type": "cross", "margin_used": "206.911511", "funding_since_open": "0.017201",
                 "flags": []}
    hl_row = one(hl_trades.open_position_rows([{"coin": "ETH", "szi": "1", "entry_px": "100", "position_value": "100"}], []))
    assert set(r) == set(hl_row)


def test_short_picks_lowest_stop_and_highest_tp():
    e = entry(szi="-3", entry_px="50", mark="45", value="135", upnl="15",
              tpsl=[sl("60", "3"), sl("55", "3"), tp("40"), tp("42")])
    r = one(txflow.open_position_rows(state(e)))
    assert (r["direction"], r["stop_px"], r["tp_px"]) == ("short", "55", "42")
    assert r["if_stopped_pnl"] == "-15.000000"                     # -(55 - 50) x 3
    assert r["unrealized_pct"] == "10.000000" and r["flags"] == []


def test_long_picks_highest_stop():
    r = one(txflow.open_position_rows(state(entry(tpsl=[sl("90"), sl("97")]))))
    assert r["stop_px"] == "97" and r["if_stopped_pnl"] == "-6.000000"   # (97 - 100) x 2


def test_partial_stop():
    r = one(txflow.open_position_rows(state(entry(tpsl=[sl("95", "0.5")]))))
    assert r["flags"] == ["stop_partial"] and r["if_stopped_pnl"] == "-2.500000"


@pytest.mark.parametrize("qty", ["", "0"])
def test_empty_or_zero_quantity_covers_the_position(qty):
    r = one(txflow.open_position_rows(state(entry(tpsl=[sl("95", qty)]))))
    assert r["flags"] == [] and r["if_stopped_pnl"] == "-10.000000"


def test_only_take_profits_is_no_stop():
    r = one(txflow.open_position_rows(state(entry(tpsl=[tp("130")]))))
    assert r["flags"] == ["no_stop"] and r["stop_px"] is None and r["tp_px"] == "130"


def test_tpsl_missing_is_unavailable():
    r = one(txflow.open_position_rows(state(entry(tpsl=None))))
    assert r["flags"] == ["open_orders_unavailable"]
    assert (r["stop_px"], r["tp_px"], r["if_stopped_pnl"], r["stop_distance_pct"]) == (None, None, None, None)


@pytest.mark.parametrize("liq", ["", "0"])
def test_no_liquidation_price(liq):
    assert one(txflow.open_position_rows(state(entry(liq=liq))))["liquidation_px"] is None


def test_mark_computed_without_mark_price():
    e = entry(szi="3", value="10")
    del e["position"]["markPx"]
    assert one(txflow.open_position_rows(state(e)))["mark_px"] == "3.333333333"


def test_coin_names():
    assert txflow.coin_name("HYPE-USDC") == "HYPE" and txflow.coin_name("eth-usdc") == "eth"
    assert txflow.coin_name("BTC") == "BTC" and txflow.coin_name(None) == ""
    assert one(txflow.open_position_rows(state(entry(coin="SOL"))))["coin"] == "SOL"


def test_skipped_entries():
    no_szi = entry()
    del no_szi["position"]["szi"]
    rows = txflow.open_position_rows(state(entry(szi="0"), no_szi, "x", {"position": "x"}, entry(coin="BTC-USDC")))
    assert [r["coin"] for r in rows] == ["BTC"]


def test_funding_missing():
    e = entry()
    del e["position"]["cumFunding"]
    assert one(txflow.open_position_rows(state(e)))["funding_since_open"] is None
    assert one(txflow.open_position_rows(state(entry())))["funding_since_open"] == "0.500000"   # -(-0.5)


@pytest.mark.parametrize("bad", [None, {}, {"assetPositions": "x"}, [], "x"])
def test_bad_states(bad):
    assert txflow.open_position_rows(bad) == []


# ── TXFLOW_WALLETS ───────────────────────────────────────────────────────

def test_wallets_parsing(monkeypatch, capsys):
    monkeypatch.setenv("TXFLOW_WALLETS", TA + ", " + TB + "\n not-an-address\t" + TA.upper().replace("0X", "0x"))
    assert wp._txflow_wallets() == [TA, TB]
    out = capsys.readouterr().out
    assert "[txflow] ignored 1 invalid TXFLOW_WALLETS entries" in out and "not-an-address" not in out
    monkeypatch.setenv("TXFLOW_WALLETS", "")
    assert wp._txflow_wallets() == []
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    assert wp._txflow_wallets() == []


# ── fetch, worker, kick ──────────────────────────────────────────────────

@pytest.fixture
def fresh_cache(monkeypatch):
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    monkeypatch.setattr(wp, "_TXFLOW_IN_FLIGHT", False)
    monkeypatch.setattr(wp, "_TXFLOW_LAST_KICK", {"at": None})


def test_fetch_states_splits_wallets_and_errors():
    def post(body):
        assert body["type"] == "clearinghouseState"
        if body["user"] == TA:
            return _fixture()
        if body["user"] == TB:
            raise ConnectionError("down")
        return {"odd": True}
    res = wp._txflow_fetch_states([TA, TB, TC], post=post)
    assert set(res["wallets"]) == {TA} and res["wallets"][TA]["state"] == _fixture()
    assert res["wallets"][TA]["fetched_at"]
    assert res["errors"] == {TB: "ConnectionError: down", TC: "ValueError: unexpected clearinghouseState"}


def test_refresh_worker(fresh_cache, monkeypatch):
    from datetime import datetime, timezone
    t1, t2 = datetime(2026, 10, 1, 12, tzinfo=timezone.utc), datetime(2026, 10, 1, 13, tzinfo=timezone.utc)
    good = lambda addrs: {"wallets": {a: {"state": {"assetPositions": []}, "fetched_at": "x"} for a in addrs}, "errors": {}}
    monkeypatch.setattr(wp, "_txflow_fetch_states", lambda wallets, post=None: good(wallets))
    monkeypatch.setattr(wp, "_TXFLOW_IN_FLIGHT", True)
    wp._txflow_refresh_worker([TA, TB], now_utc=t1)
    c = wp._txflow_cache_copy()
    assert set(c["wallets"]) == {TA, TB} and c["fetched_at"] == t1.isoformat() and c["error"] is None
    assert wp._TXFLOW_IN_FLIGHT is False

    monkeypatch.setattr(wp, "_txflow_fetch_states", lambda wallets, post=None: {
        "wallets": {TA: {"state": {"assetPositions": []}, "fetched_at": "y"}}, "errors": {TB: "ConnectionError: down"}})
    monkeypatch.setattr(wp, "_TXFLOW_IN_FLIGHT", True)
    wp._txflow_refresh_worker([TA, TB], now_utc=t2)
    c = wp._txflow_cache_copy()
    assert c["wallets"][TA] == {"state": {"assetPositions": []}, "fetched_at": "y"}
    assert c["wallets"][TB]["stale"] is True and c["wallets"][TB]["error"] == "ConnectionError: down"
    assert c["wallets"][TB]["fetched_at"] == "x" and c["fetched_at"] == t2.isoformat()
    assert wp._TXFLOW_IN_FLIGHT is False

    monkeypatch.setattr(wp, "_txflow_fetch_states", lambda wallets, post=None: {
        "wallets": {}, "errors": {TA: "ConnectionError: down", TB: "ConnectionError: down"}})
    monkeypatch.setattr(wp, "_TXFLOW_IN_FLIGHT", True)
    wp._txflow_refresh_worker([TA, TB])
    c = wp._txflow_cache_copy()
    assert c["error"].startswith("every wallet failed: ") and c["fetched_at"] == t2.isoformat()
    assert set(c["wallets"]) == {TA, TB}
    assert wp._TXFLOW_IN_FLIGHT is False

    def boom(wallets, post=None):
        raise RuntimeError("bad")
    monkeypatch.setattr(wp, "_txflow_fetch_states", boom)
    monkeypatch.setattr(wp, "_TXFLOW_IN_FLIGHT", True)
    wp._txflow_refresh_worker([TA])
    assert wp._txflow_cache_copy()["error"] == "RuntimeError: bad" and wp._TXFLOW_IN_FLIGHT is False


def test_kick(fresh_cache, monkeypatch):
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    spawned = []
    monkeypatch.setattr(wp, "_spawn_txflow_refresh_thread", lambda wallets: spawned.append(list(wallets)))
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    assert wp._maybe_kick_txflow_refresh(now) is False and spawned == []
    monkeypatch.setenv("TXFLOW_WALLETS", TA)
    assert wp._maybe_kick_txflow_refresh(now) is True and spawned == [[TA]]
    monkeypatch.setattr(wp, "_TXFLOW_IN_FLIGHT", False)
    assert wp._maybe_kick_txflow_refresh(now + timedelta(minutes=5)) is False
    assert len(spawned) == 1


# ── GET /api/trading/perps/open ──────────────────────────────────────────

def _never(*a, **k):
    raise AssertionError("no venue call on a request path")


def _hl_pos(value):
    return {"coin": "ETH", "szi": "1", "entry_px": "100", "unrealized_pnl": "5", "cum_funding_since_open": "0.1",
            "position_value": value, "liquidation_px": None, "margin_used": "10", "return_on_equity": "0.1",
            "leverage": 5, "leverage_type": "cross"}


@pytest.fixture
def client(monkeypatch, fresh_cache):
    kicks = {"hl": [], "tx": []}
    monkeypatch.setattr(wp, "_hl_post", _never)
    monkeypatch.setattr(wp, "_txflow_post", _never)
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", lambda now: kicks["hl"].append(now) or False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", lambda now: kicks["tx"].append(now) or False)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {H1: {"label": "Hyperliquid RM"}})
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {
        "fetched_at": "2026-10-01T12:00:00+00:00", "error": None,
        "wallets": {H1: {"positions": [_hl_pos("3000"), dict(_hl_pos("1000"), coin="SOL")], "open_orders": []}}})
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    c.kicks = kicks
    return c


def _tx_cache(monkeypatch, wallets, fetched_at="2026-10-01T12:05:00+00:00", error=None):
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": fetched_at, "error": error, "wallets": wallets})


def test_route_without_txflow_wallets(client, monkeypatch):
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    body = client.get('/api/trading/perps/open').get_json()
    assert [v["venue"] for v in body["venues"]] == ["Hyperliquid"]
    assert all(p["venue"] == "Hyperliquid" for p in body["positions"]) and client.kicks["tx"] == []
    assert len(client.kicks["hl"]) == 1


def test_route_with_txflow(client, monkeypatch):
    monkeypatch.setenv("TXFLOW_WALLETS", TA)
    _tx_cache(monkeypatch, {TA: {"state": _fixture(), "fetched_at": "2026-10-01T12:05:00+00:00"}})
    r = client.get('/api/trading/perps/open')
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert TA not in text and TA[2:] not in text and H1 not in text
    body = r.get_json()
    assert [(p["venue"], p["coin"]) for p in body["positions"]] == [("Hyperliquid", "ETH"), ("TxFlow", "HYPE"),
                                                                    ("Hyperliquid", "SOL")]   # value desc
    tx = body["positions"][1]
    assert tx["wallet_label"] == "TxFlow" and tx["stale"] is False and tx["open_orders_error"] is None
    assert tx["funding_since_open"] == "0.017201"
    assert body["totals"]["open_count"] == 3 and body["totals"]["notional"] == "6069.115115"
    assert body["venues"][1] == {"venue": "TxFlow", "status": "ok", "as_of": "2026-10-01T12:05:00+00:00", "error": None}
    assert len(client.kicks["tx"]) == 1


def test_route_uses_the_wallet_config_label(client, monkeypatch):
    monkeypatch.setenv("TXFLOW_WALLETS", TA)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {H1: {"label": "Hyperliquid RM"}, TA: {"label": "TxFlow main"}})
    _tx_cache(monkeypatch, {TA: {"state": _fixture()}})
    body = client.get('/api/trading/perps/open').get_json()
    assert [p["wallet_label"] for p in body["positions"] if p["venue"] == "TxFlow"] == ["TxFlow main"]


def test_route_ignores_wallets_no_longer_listed(client, monkeypatch):
    monkeypatch.setenv("TXFLOW_WALLETS", TB)
    _tx_cache(monkeypatch, {TA: {"state": _fixture()}})
    body = client.get('/api/trading/perps/open').get_json()
    assert all(p["venue"] == "Hyperliquid" for p in body["positions"])
    assert body["venues"][1]["status"] == "ok"


def test_route_txflow_loading_and_error(client, monkeypatch):
    monkeypatch.setenv("TXFLOW_WALLETS", TA + "," + TB)
    _tx_cache(monkeypatch, {}, fetched_at=None)
    assert client.get('/api/trading/perps/open').get_json()["venues"][1]["status"] == "loading"
    _tx_cache(monkeypatch, {}, fetched_at=None, error="every wallet failed: " + TA + ": ConnectionError: down")
    r = client.get('/api/trading/perps/open')
    venue = r.get_json()["venues"][1]
    assert venue["status"] == "error"
    assert venue["error"] == "every wallet failed: TxFlow …" + TA[-4:] + ": ConnectionError: down"
    assert TA not in r.get_data(as_text=True)


def test_route_survives_a_failing_txflow_kick(client, monkeypatch):
    monkeypatch.setenv("TXFLOW_WALLETS", TA)
    def boom(now):
        raise RuntimeError("no threads")
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", boom)
    _tx_cache(monkeypatch, {TA: {"state": _fixture()}})
    assert client.get('/api/trading/perps/open').status_code == 200
