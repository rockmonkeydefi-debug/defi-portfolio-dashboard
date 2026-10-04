"""Planned take-profit on perp trades (Landing 5, HANDOFF_spot_perps_rebuild.md
16): hl_trades.planned_targets (the first take-profit set from stored order
records, nearest first, and where it was moved later), txflow.to_hl_take_profits,
the first-sight capture of live take-profits in the snapshot pass, and
"planned_target" on GET /api/trading/trades (stored orders, then the capture,
then a manual perp trade's logged target; spot trades none).

The order fixtures are the recorded, sanitized Hyperliquid exports in
tests/fixtures/hl_trading (prices scaled, R unchanged) and the recorded TxFlow
answers in tests/fixtures/txflow. Real init_db() on a tmp_path SQLite file
(portfolio_db.get_db_path monkeypatched). No network: _hl_post and
_txflow_post raise. Fake wallet addresses only, built in code; made-up prices.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import copy
import json
import os
import threading
from datetime import datetime, timezone
from decimal import Decimal

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

HL_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "hl_trading")
TX_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "txflow")
W = "0x" + "d" * 40
W_TX = "0x" + "c" * 40
MIN = 60000
HOUR = 3600000
DAY = 86400000
T0 = int(datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)


def _hl(name):
    with open(os.path.join(HL_FIX, name)) as f:
        return json.load(f)


def _tx(name):
    with open(os.path.join(TX_FIX, name + ".json")) as f:
        return json.load(f)


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def rec(oid, px, placed, side="A", coin="ETH", status="open", status_ts=None, kind="Take Profit Market",
        reduce_only=True, tpsl=False, trigger=True):
    """One historicalOrders record (Hyperliquid shape)."""
    return {"status": status, "statusTimestamp": status_ts if status_ts is not None else placed,
            "order": {"coin": coin, "side": side, "oid": oid, "timestamp": placed, "triggerPx": str(px),
                      "isTrigger": trigger, "reduceOnly": reduce_only, "isPositionTpsl": tpsl,
                      "orderType": kind, "children": []}}


def cycle(key="k", direction="long", open_ms=T0, close_ms=T0 + DAY, coin="ETH"):
    return {"trade_key": key, "coin": coin, "direction": direction, "open_time": open_ms, "close_time": close_ms}


# ── hl_trades.planned_targets on the recorded exports ────────────────────

def _fixture_plans(wallet):
    orders = _hl(f"{wallet}.hist_orders.json")
    built = hl_trades.build_cycles(wallet, _hl(f"{wallet}.fills.json"), _hl(f"{wallet}.funding.json"), orders)
    return built["cycles"], hl_trades.planned_targets(built["cycles"], orders), orders


def test_recorded_exports_16_of_20_trades_had_a_take_profit():
    plans = {}
    for w in ("rm", "rabby"):
        cycles, got, orders = _fixture_plans(w)
        tp_prices = {Decimal(o["order"]["triggerPx"]) for o in orders if "Take Profit" in o["order"].get("orderType", "")}
        for c in cycles:
            p = got.get(c["trade_key"])
            plans[(w, c["coin"], c["open_time"])] = p
            if p:
                assert p["first"] and all(Decimal(x) in tp_prices for x in p["first"])
                assert [float(x) for x in p["first"]] == sorted(float(x) for x in p["first"])   # longs: lowest first
                assert c["open_time"] - hl_trades.STOP_LOOKBACK_MS <= p["first_set_ms"] <= (c["close_time"] or 10 ** 16)
    assert len(plans) == 20 and sum(1 for p in plans.values() if p) == 16
    rabby = {(k[1], k[2]): v for k, v in plans.items() if k[0] == "rabby"}
    ladders = [v for v in rabby.values() if v and len(v["first"]) == 2]
    moved = sorted(k[0] for k, v in rabby.items() if v and v["last"])
    assert len(ladders) == 1 and ladders[0]["last"] is None                        # a HYPE ladder of two
    assert moved == ["AAVE", "PUMP"]                                              # targets moved further out
    for k, v in rabby.items():
        if v and v["last"]:
            assert float(v["last"]) > float(v["first"][-1]) and v["last_set_ms"] > v["first_set_ms"]


# ── hl_trades.planned_targets rules ──────────────────────────────────────

def test_first_set_is_nearest_first_and_a_later_target_is_moved():
    orders = [rec(1, 110, T0 + 2 * MIN), rec(2, 105, T0 + 2 * MIN + 30000), rec(3, 120, T0 + 2 * HOUR)]
    assert hl_trades.planned_targets([cycle()], orders) == {
        "k": {"first": ["105", "110"], "first_set_ms": T0 + 2 * MIN, "last": "120", "last_set_ms": T0 + 2 * HOUR}}


def test_short_targets_highest_first():
    orders = [rec(1, 90, T0 + MIN, side="B"), rec(2, 95, T0 + MIN, side="B")]
    got = hl_trades.planned_targets([cycle(direction="short")], orders)["k"]
    assert got["first"] == ["95", "90"] and got["last"] is None


def test_grace_window_is_one_minute():
    orders = [rec(1, 105, T0 + MIN), rec(2, 110, T0 + MIN + hl_trades.PLAN_GRACE_MS + 1)]
    got = hl_trades.planned_targets([cycle()], orders)["k"]
    assert got["first"] == ["105"] and got["last"] == "110"


def test_only_the_trades_own_take_profits_count():
    orders = [
        rec(1, 100, T0 - DAY, status="open"), rec(1, 100, T0 - DAY, status="reduceOnlyCanceled", status_ts=T0 - HOUR),
        rec(2, 101, T0 - 4 * DAY),                                         # placed before the 3-day lookback
        rec(3, 102, T0 + 2 * DAY),                                         # after the close
        rec(4, 103, T0 + MIN, side="B"),                                   # the opening side
        rec(5, 104, T0 + MIN, coin="BTC"),                                 # another coin
        rec(6, 95, T0 + MIN, kind="Stop Market"),                          # a stop
        rec(7, 106, T0 + MIN, trigger=False),                              # not a trigger
        rec(8, 0, T0 + MIN),                                               # no trigger price
        rec(9, 107, T0 + MIN, reduce_only=False),                          # neither reduce-only nor position tpsl
    ]
    assert hl_trades.planned_targets([cycle()], orders) == {}


def test_alive_at_open_and_position_tpsl_count():
    orders = [rec(1, 108, T0 - HOUR), rec(2, 109, T0 + 5 * MIN, reduce_only=False, tpsl=True)]
    got = hl_trades.planned_targets([cycle()], orders)["k"]
    assert got["first"] == ["108"] and got["first_set_ms"] == T0 - HOUR and got["last"] == "109"


def test_equal_prices_once_and_an_unchanged_replacement_is_not_a_move():
    orders = [rec(1, 110, T0 + MIN), rec(2, 110, T0 + MIN + 1000), rec(3, 110, T0 + 3 * HOUR)]
    assert hl_trades.planned_targets([cycle()], orders)["k"] == {
        "first": ["110"], "first_set_ms": T0 + MIN, "last": None, "last_set_ms": None}


def test_open_trade_and_several_trades():
    # Trade a's take-profit is cancelled when a closes, as Hyperliquid records it, so b never inherits it.
    orders = [rec(1, 110, T0 + MIN), rec(1, 110, T0 + MIN, status="reduceOnlyCanceled", status_ts=T0 + DAY),
              rec(2, 130, T0 + 3 * DAY + MIN)]
    got = hl_trades.planned_targets([cycle("a"), cycle("b", open_ms=T0 + 3 * DAY, close_ms=None)], orders)
    assert got["a"]["first"] == ["110"] and got["b"]["first"] == ["130"] and got["a"]["last"] is None


def test_odd_records_are_skipped():
    assert hl_trades.planned_targets([cycle()], [None, "x", {"order": None}, rec(1, 110, T0 + MIN)])["k"]["first"] == ["110"]
    assert hl_trades.planned_targets([], [rec(1, 110, T0)]) == {} and hl_trades.planned_targets([cycle()], None) == {}


# ── txflow.to_hl_take_profits ────────────────────────────────────────────

def _tx_order(side, cond, tpsl=True, reduce_only=True, trigger=True, order_type="Market"):
    return {"status": "canceled", "statusTimestamp": 2,
            "order": {"coin": "HYPE", "side": side, "oid": 7, "timestamp": 1, "triggerPx": "110",
                      "isTrigger": trigger, "reduceOnly": reduce_only, "isPositionTpsl": tpsl,
                      "orderType": order_type, "triggerCondition": cond}}


def test_txflow_take_profits_are_converted():
    long_tp, short_tp = _tx_order("A", "Price above 110"), _tx_order("B", "Price below 90", tpsl=False)
    long_stop, short_stop = _tx_order("A", "Price below 90"), _tx_order("B", "Price above 110")
    plain = _tx_order("B", "N/A", tpsl=False, reduce_only=False, trigger=False, order_type="Limit")
    not_reducing = _tx_order("A", "Price above 110", tpsl=False, reduce_only=False)
    recs = [long_tp, short_tp, long_stop, short_stop, plain, not_reducing]
    before = copy.deepcopy(recs)
    out = txflow.to_hl_take_profits(recs)
    assert recs == before
    assert [(r["order"]["orderType"], r["order"]["reduceOnly"]) for r in out[:2]] == [("Take Profit Market", True)] * 2
    assert out[2:] == recs[2:]
    assert txflow.to_hl_take_profits(_tx("historicalOrders")) == _tx("historicalOrders")   # no take-profit recorded
    assert txflow.to_hl_orders(recs)[0] == long_tp                                          # the stop converter is unchanged


# ── the trades route ─────────────────────────────────────────────────────

def fill(coin, tid, t, side, sz, px, start, pnl="0"):
    return {"coin": coin, "tid": tid, "time": t, "side": side, "sz": sz, "px": px, "startPosition": start,
            "closedPnl": pnl, "fee": "0.1", "builderFee": "0", "dir": "x", "oid": tid, "hash": "0x0"}


BTC_OPEN, BTC_CLOSE, ETH_OPEN = T0, T0 + 20 * HOUR, T0 + 5 * DAY


def hl_cache(tps):
    """The accounts cache: an open ETH long, with take-profit orders at `tps`."""
    pos = {"coin": "ETH", "szi": "1", "entry_px": "4000", "unrealized_pnl": "5", "cum_funding_since_open": "0",
           "position_value": "4005", "liquidation_px": "3000", "margin_used": "400", "return_on_equity": "0.1",
           "leverage": 5, "leverage_type": "cross"}
    orders = [{"coin": "ETH", "side": "A", "triggerPx": str(p), "orderType": "Take Profit Market", "isTrigger": True,
               "reduceOnly": True, "isPositionTpsl": False, "oid": 50 + i, "timestamp": 1} for i, p in enumerate(tps)]
    return {"fetched_at": "2026-09-26T00:00:00+00:00", "wallets": {W: {"positions": [pos], "open_orders": orders}}}


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {W: {"label": "HL main"}})
    monkeypatch.setattr(wp, "_hl_post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HL call")))
    monkeypatch.setattr(wp, "_txflow_post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no TxFlow call")))
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": None, "wallets": {}})
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    conn = portfolio_db.get_connection()
    conn.execute("INSERT INTO hl_sync_state (wallet, first_seen_at, last_sync_at, last_ok_at) VALUES (?, ?, ?, ?)",
                 (W, "2026-09-01T00:00:00+00:00", "2026-09-26T00:00:00+00:00", "2026-09-26T00:00:00+00:00"))
    for f in (fill("BTC", 1, BTC_OPEN, "B", "0.01", "100000", "0"),
              fill("BTC", 2, BTC_CLOSE, "A", "0.01", "101000", "0.01", pnl="10"),
              fill("ETH", 3, ETH_OPEN, "B", "1", "4000", "0")):
        conn.execute("INSERT INTO hl_fills (wallet, tid, coin, time_ms, raw_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (W, f["tid"], f["coin"], f["time"], json.dumps(f), "2026-09-26T00:00:00+00:00"))
    for i, r in enumerate((rec(10, 98000, BTC_OPEN, coin="BTC", kind="Stop Market"),
                           rec(11, 104000, BTC_OPEN + MIN, coin="BTC"),
                           rec(11, 104000, BTC_OPEN + MIN, coin="BTC", status="reduceOnlyCanceled", status_ts=BTC_OPEN + 2 * HOUR),
                           rec(12, 106000, BTC_OPEN + 2 * HOUR, coin="BTC"))):
        conn.execute("INSERT INTO hl_orders (wallet, oid, coin, status, status_ts, order_ts, raw_json, fetched_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (W, r["order"]["oid"], r["order"]["coin"], r["status"], r["statusTimestamp"] + i,
                      r["order"]["timestamp"], json.dumps(r), "2026-09-26T00:00:00+00:00"))
    for ticker, target in (("SOL", 115), ("ARB", None)):
        conn.execute("INSERT INTO spot_trade_log (ticker, direction, source, entry_price, stop_price, qty, entered_at, "
                     "market, target_price) VALUES (?, 'long', 'manual', 100, 95, 1, '2026-09-25T10:00:00+00:00', 'perp', ?)",
                     (ticker, target))
    conn.execute("INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, chain, "
                 "contract_address) VALUES ('2026-09-20', 'AAA', 'buy', 100, 100, 100, 'base', ?)", ("0x" + "3" * 40,))
    conn.commit()
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


def trades(client):
    r = client.get('/api/trading/trades')
    text = r.get_data(as_text=True)
    assert W not in text and W[2:] not in text and W_TX[2:] not in text
    return {(t["source"], t["symbol"]): t for t in r.get_json()["trades"]}


def test_route_planned_target_from_stored_orders(db, client):
    by = trades(client)
    assert by[("hyperliquid", "BTC")]["planned_target"] == {
        "prices": ["104000"], "source": "hl_order", "set_at": _iso(BTC_OPEN + MIN),
        "moved_to": "106000", "moved_at": _iso(BTC_OPEN + 2 * HOUR)}
    assert by[("hyperliquid", "ETH")]["planned_target"] is None                       # open, no order, not seen yet
    assert by[("manual", "SOL")]["planned_target"] == {"prices": ["115"], "source": "manual_log", "set_at": None,
                                                       "moved_to": None, "moved_at": None}
    assert by[("manual", "ARB")]["planned_target"] is None
    assert by[("spot_tx", "AAA")]["planned_target"] is None
    perps = client.get('/api/trading/perps/trades').get_json()["trades"]
    btc = next(t for t in perps if t["coin"] == "BTC")
    assert btc["planned_tp"]["first"] == ["104000"]                                    # the cycle route carries it too


def test_route_stays_read_only(db, client):
    before = [tuple(r) for r in db.execute("SELECT * FROM trade_annotations")]
    trades(client)
    trades(client)
    assert [tuple(r) for r in db.execute("SELECT * FROM trade_annotations")] == before == []


def test_live_take_profits_are_captured_once_and_used_as_the_fallback(db, client, monkeypatch):
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: hl_cache([4400, 4300]))
    stats = wp._trade_snapshot_pass(db, cap=0)
    assert (stats["targets"], stats["leverage"]) == (1, 1)
    eth = trades(client)[("hyperliquid", "ETH")]
    seen = json.loads(db.execute("SELECT scanner_snapshot_json FROM trade_annotations").fetchone()[0])["take_profits"]
    assert seen["prices"] == ["4300", "4400"] and wp._trades_dt(seen["seen_at"]) is not None
    assert eth["planned_target"] == {"prices": ["4300", "4400"], "source": "seen_live", "set_at": seen["seen_at"],
                                     "moved_to": None, "moved_at": None}
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: hl_cache([4600]))
    assert wp._trade_snapshot_pass(db, cap=0)["targets"] == 0                          # the first one seen stays
    assert trades(client)[("hyperliquid", "ETH")]["planned_target"]["prices"] == ["4300", "4400"]


def test_no_live_take_profit_is_not_captured(db, monkeypatch):
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: hl_cache([]))
    stats = wp._trade_snapshot_pass(db, cap=0)
    assert (stats["targets"], stats["leverage"]) == (0, 1)
    snap = json.loads(db.execute("SELECT scanner_snapshot_json FROM trade_annotations").fetchone()[0])
    assert "take_profits" not in snap


def test_stored_orders_win_over_the_capture(db, client):
    btc_id = trades(client)[("hyperliquid", "BTC")]["trade_id"]
    db.execute("INSERT INTO trade_annotations (trade_id, market, scanner_snapshot_json, created_at, updated_at) "
               "VALUES (?, 'perp', ?, 'x', 'x')",
               (btc_id, json.dumps({"take_profits": {"prices": ["999"], "seen_at": "2026-09-20T10:05:00+00:00"}})))
    db.commit()
    assert trades(client)[("hyperliquid", "BTC")]["planned_target"]["source"] == "hl_order"


def test_txflow_take_profit_from_the_order_history(db, client, monkeypatch):
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {W: {"label": "HL main"},
                                                           W_TX: {"label": "TxFlow main", "perp_venues": ["txflow"]}})
    pengu_stop = next(r for r in _tx("historicalOrders") if r["order"]["coin"] == "PENGU" and r["order"]["isTrigger"])
    tp = copy.deepcopy(pengu_stop)
    tp["status"] = "canceled"
    tp["order"].update(oid=pengu_stop["order"]["oid"] + 1, triggerCondition="Price above 0.0125", triggerPx="0.0125")
    records = _tx("historicalOrders") + [tp]

    class Post:
        def __call__(self, body):
            kind = body["type"]
            if kind == "clearinghouseState":
                return {"assetPositions": [], "marginSummary": {}, "crossMarginSummary": {}}
            if kind == "userFills":
                return _tx("userFills")
            if kind == "historicalOrders":
                return copy.deepcopy(records)
            raise AssertionError(kind)

    wp._txflow_trades_refresh_worker(now_utc=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), post=Post())
    pengu = trades(client)[("txflow", "PENGU")]
    assert pengu["status"] == "closed"
    assert pengu["planned_target"] == {"prices": ["0.0125"], "source": "txflow_order",
                                       "set_at": _iso(pengu_stop["order"]["timestamp"]), "moved_to": None, "moved_at": None}
    assert pengu["stop"]["source"] == "txflow_order"                                   # the stop rule is unchanged
