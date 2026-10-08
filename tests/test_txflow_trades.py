"""TxFlow trades (HANDOFF_trading_performance.md Commit 4c): the pure
txflow helpers (to_hl_fills, to_hl_orders, funding_rows, build_cycles,
live_stops), the txflow_fills / txflow_orders / txflow_funding_obs /
txflow_sync_state tables, the background sync and its kick, the funding
readings recorded by the open-perps refresh, and TxFlow trades in
GET /api/trading/trades and the annotation PUT.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). The recorded TxFlow answers in tests/fixtures/txflow are
served by a fake post (read-only); _hl_post and _txflow_post raise. Fake
wallet address only, built in code.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import copy
import json
import os
import threading
from datetime import datetime, timezone
from decimal import Context, Decimal, localcontext

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import txflow
import src.storage.portfolio_db as portfolio_db

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "txflow")
W = "0x" + "c" * 40
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
PENGU_OPEN, PENGU_CLOSE, HYPE_OPEN = 1788788808275, 1788818617396, 1788867408967
DAY = 86400000


def _load(name):
    with open(os.path.join(FIX, f"{name}.json")) as f:
        return json.load(f)


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def _never(*a, **k):
    raise AssertionError("no venue call here")


class FakeTxPost:
    """Serves the recorded TxFlow answers by request type. userFunding /
    userFillsByTime are refused by TxFlow and must never be asked for."""

    def __init__(self, state=None, fail=False, shift_days=0):
        self.calls = []
        self.state = state if state is not None else _load("clearinghouseState")
        self.fail = fail
        self.shift_days = shift_days

    def __call__(self, body):
        self.calls.append(dict(body))
        assert body.get("user") == W
        if self.fail:
            raise ConnectionError("down")
        kind = body["type"]
        assert kind not in ("userFunding", "userFillsByTime")
        if kind == "clearinghouseState":
            return copy.deepcopy(self.state)
        if kind == "userFills":
            return shift(_load("userFills"), self.shift_days)
        if kind == "historicalOrders":
            return shift(_load("historicalOrders"), self.shift_days)
        raise AssertionError(f"unexpected request {kind}")


def shift(obj, days):
    """A copy with every timestamp field moved by whole days."""
    if not days:
        return copy.deepcopy(obj)
    if isinstance(obj, list):
        return [shift(x, days) for x in obj]
    if isinstance(obj, dict):
        return {k: (v + days * DAY if k in ("time", "timestamp", "statusTimestamp", "createTime", "updateTime")
                    and isinstance(v, int) else shift(v, days)) for k, v in obj.items()}
    return obj


# ── a. build_cycles on the fixtures ──────────────────────────────────────

def test_build_cycles_on_the_fixtures():
    res = txflow.build_cycles(W, _load("userFills"), _load("historicalOrders"), [])
    pengu, hype = res["cycles"]
    assert (pengu["coin"], pengu["direction"], pengu["status"], pengu["fill_count"]) == ("PENGU", "long", "closed", 4)
    assert pengu["peak_size"] == "161458.000000"
    assert pengu["avg_entry_px"] == "0.01105614262569832402234636872"
    assert pengu["avg_exit_px"] == "0.01017251825799898425596749619"
    assert (pengu["gross_closed_pnl"], pengu["fees"], pengu["funding"], pengu["net_pnl"]) == \
           ("-142.668223", "1.542392", "0.000000", "-144.210615")
    assert pengu["initial_stop_px"] == "0.01017463"
    assert pengu["stop_placed"] == pengu["open_time"] == PENGU_OPEN and pengu["close_time"] == PENGU_CLOSE
    assert pengu["r_multiple"] == "-1.013233" and pengu["flags"] == ["funding_missing"]
    assert (hype["coin"], hype["status"], hype["avg_entry_px"], hype["peak_size"]) == ("HYPE", "open", "95.9683", "22.140000")
    assert (hype["fees"], hype["net_pnl"], hype["initial_stop_px"]) == ("0.956132", "-0.956132", None)
    assert "stop_missing" in hype["flags"] and "funding_missing" in hype["flags"]
    assert all(c["trade_key"].startswith("txflow|") for c in res["cycles"])
    assert pengu["trade_key"] == f"txflow|{W}|PENGU|{pengu['first_tid']}"


# ── b. funding readings ──────────────────────────────────────────────────

def _with_obs(obs):
    return {c["coin"]: c for c in txflow.build_cycles(W, _load("userFills"), _load("historicalOrders"), obs)["cycles"]}


def test_a_reading_inside_the_cycle_is_its_funding():
    got = _with_obs([{"coin": "PENGU-USDC", "observed_ms": PENGU_OPEN + 1000, "since_open": "-0.5"}])
    p = got["PENGU"]
    assert (p["funding"], p["net_pnl"]) == ("-0.500000", "-144.710615") and p["flags"] == ["funding_approx"]
    assert "funding_missing" in got["HYPE"]["flags"]


def test_readings_outside_the_window_are_ignored():
    got = _with_obs([{"coin": "PENGU", "observed_ms": PENGU_OPEN, "since_open": "-9"},          # at open: excluded
                     {"coin": "PENGU", "observed_ms": PENGU_CLOSE + 1, "since_open": "-9"}])     # after close
    assert got["PENGU"]["funding"] == "0.000000" and got["PENGU"]["flags"] == ["funding_missing"]
    got = _with_obs([{"coin": "PENGU", "observed_ms": PENGU_CLOSE, "since_open": "-0.3"}])      # at close: included
    assert got["PENGU"]["funding"] == "-0.300000"


def test_the_latest_reading_wins():
    got = _with_obs([{"coin": "PENGU", "observed_ms": PENGU_OPEN + 2000, "since_open": "-0.5"},
                     {"coin": "PENGU", "observed_ms": PENGU_OPEN + 1000, "since_open": "-0.2"}])
    assert got["PENGU"]["funding"] == "-0.500000"


def test_a_reading_applies_to_the_open_cycle():
    got = _with_obs([{"coin": "HYPE-USDC", "observed_ms": HYPE_OPEN + 1, "since_open": "-0.0172009883"}])
    h = got["HYPE"]
    assert (h["funding"], h["net_pnl"]) == ("-0.017201", "-0.973333")
    assert "funding_approx" in h["flags"] and "funding_missing" not in h["flags"]


def test_funding_rows_shape():
    cycles = txflow.build_cycles(W, _load("userFills"), _load("historicalOrders"), [])["cycles"]
    rows, found = txflow.funding_rows(cycles, [{"coin": "PENGU", "observed_ms": PENGU_OPEN + 5, "since_open": "-1"}])
    assert rows == [{"time": PENGU_OPEN + 5, "delta": {"coin": "PENGU", "usdc": "-1", "szi": None, "nSamples": None}}]
    assert found == {cycles[0]["trade_key"]: True, cycles[1]["trade_key"]: False}


# ── c. conversions ───────────────────────────────────────────────────────

def test_to_hl_fills():
    fills = _load("userFills")
    before = copy.deepcopy(fills)
    out = txflow.to_hl_fills(fills)
    assert fills == before                                                   # inputs never mutated
    for f, g in zip(fills, out):
        if f["reduceOnly"]:
            with localcontext(Context(prec=100)):
                assert g["closedPnl"] == str(Decimal(f["closedPnl"]) + Decimal(f["fee"]))
            assert {k: v for k, v in g.items() if k != "closedPnl"} == {k: v for k, v in f.items() if k != "closedPnl"}
        else:
            assert g == f
    assert out[1]["closedPnl"] == "-138.9048908440223463687150789"
    short = [{"side": "A", "startPosition": "0", "sz": "10", "closedPnl": "0", "fee": "0.5"},       # opens a short
             {"side": "A", "startPosition": "-10", "sz": "2", "closedPnl": "0", "fee": "0.1"},      # adds to it
             {"side": "B", "startPosition": "-12", "sz": "4", "closedPnl": "5", "fee": "0.25"}]     # reduces it
    got = txflow.to_hl_fills(short)
    assert got[0] == short[0] and got[1] == short[1] and got[2]["closedPnl"] == "5.25"


def _order(side, cond, trigger=True, tpsl=True, reduce_only=True, order_type="Market"):
    return {"order": {"coin": "HYPE", "side": side, "oid": 1, "timestamp": 1, "isTrigger": trigger,
                      "isPositionTpsl": tpsl, "reduceOnly": reduce_only, "orderType": order_type,
                      "triggerCondition": cond, "triggerPx": "90", "children": []},
            "status": "open", "statusTimestamp": 1}


def test_to_hl_orders():
    long_stop = _order("A", "Price below 90")
    long_tp = _order("A", "Price above 110")
    short_stop = _order("B", "Price above 110", tpsl=False)
    short_tp = _order("B", "Price below 90")
    plain = _order("B", "N/A", trigger=False, tpsl=False, reduce_only=False, order_type="Limit")
    not_reducing = _order("A", "Price below 90", tpsl=False, reduce_only=False)
    recs = [long_stop, long_tp, short_stop, short_tp, plain, not_reducing]
    before = copy.deepcopy(recs)
    out = txflow.to_hl_orders(recs)
    assert recs == before
    assert (out[0]["order"]["orderType"], out[0]["order"]["reduceOnly"]) == ("Stop Market", True)
    assert out[1] == long_tp and out[3] == short_tp and out[4] == plain and out[5] == not_reducing
    assert (out[2]["order"]["orderType"], out[2]["order"]["reduceOnly"]) == ("Stop Market", True)
    fixture = txflow.to_hl_orders(_load("historicalOrders"))
    assert [r["order"]["orderType"] for r in fixture] == ["Limit", "Market", "Stop Market", "Market", "Limit"]


# ── d. live stops ────────────────────────────────────────────────────────

def test_live_stops():
    state = _load("clearinghouseState")
    stop_entry = next(t for t in state["assetPositions"][0]["tpsl"] if t["slTriggerPrice"])
    assert txflow.live_stops(state) == {"HYPE": {"px": "90.21491", "set_at_ms": stop_entry["createTime"]}}
    short = {"assetPositions": [{"position": {"coin": "ETH-USDC", "szi": "-1"},
                                 "tpsl": [{"slTriggerPrice": "120", "createTime": 1},
                                          {"slTriggerPrice": "110", "createTime": 2},
                                          {"slTriggerPrice": "", "tpTriggerPrice": "90", "createTime": 3}]},
                                {"position": {"coin": "BTC-USDC", "szi": "1"}, "tpsl": []}]}
    assert txflow.live_stops(short) == {"ETH": {"px": "110", "set_at_ms": 2}}
    assert txflow.live_stops(None) == {} and txflow.live_stops({"assetPositions": "x"}) == {}


# ── e. sync ──────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {W: {"label": "TxFlow main", "perp_venues": ["txflow"]}})
    monkeypatch.setattr(wp, "_hl_post", _never)
    monkeypatch.setattr(wp, "_txflow_post", _never)
    monkeypatch.setattr(wp, "_TXFLOW_TRADES_IN_FLIGHT", False)
    monkeypatch.setattr(wp, "_TXFLOW_TRADES_LAST_KICK", {"at": None})
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    conn = portfolio_db.get_connection()
    yield conn
    conn.close()


def counts(conn):
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("txflow_fills", "txflow_orders", "txflow_funding_obs", "txflow_sync_state")}


def test_tables_and_init_db_idempotent(db):
    cols = lambda t: {r["name"] for r in db.execute(f"PRAGMA table_info({t})")}
    assert cols("txflow_fills") == {"id", "wallet", "tid", "coin", "time_ms", "raw_json", "fetched_at"}
    assert cols("txflow_orders") == cols("hl_orders")
    assert cols("txflow_funding_obs") == {"id", "wallet", "coin", "observed_ms", "since_open", "szi", "fetched_at"}
    assert cols("txflow_sync_state") == cols("hl_sync_state")
    portfolio_db.init_db()


def test_sync_inserts_then_nothing_then_a_changed_reading(db, monkeypatch, capsys):
    post = FakeTxPost()
    monkeypatch.setattr(wp, "_TXFLOW_TRADES_IN_FLIGHT", True)
    wp._txflow_trades_refresh_worker(now_utc=NOW, post=post)
    assert wp._TXFLOW_TRADES_IN_FLIGHT is False
    assert counts(db) == {"txflow_fills": 5, "txflow_orders": 5, "txflow_funding_obs": 1, "txflow_sync_state": 1}
    assert [c["type"] for c in post.calls] == ["clearinghouseState", "userFills", "historicalOrders"]
    st = dict(db.execute("SELECT * FROM txflow_sync_state").fetchone())
    assert st["wallet"] == W and st["last_ok_at"] and st["last_error"] is None and st["first_seen_at"] == NOW.isoformat()
    obs = dict(db.execute("SELECT coin, observed_ms, since_open, szi FROM txflow_funding_obs").fetchone())
    assert obs == {"coin": "HYPE", "observed_ms": post.state["time"], "since_open": "-0.0172009883", "szi": "22.14"}
    out = capsys.readouterr().out
    assert "[txflow-trades] wallets=1 errors=0 fills+=5 orders+=5 obs+=1" in out and W[2:] not in out

    wp._txflow_trades_refresh_worker(now_utc=NOW, post=FakeTxPost())                # unchanged reading
    assert counts(db)["txflow_funding_obs"] == 1 and counts(db)["txflow_fills"] == 5 and counts(db)["txflow_orders"] == 5

    changed = _load("clearinghouseState")
    changed["time"] += 3600000
    changed["assetPositions"][0]["position"]["cumFunding"]["sinceOpen"] = "-0.0300000000"
    wp._txflow_trades_refresh_worker(now_utc=NOW, post=FakeTxPost(state=changed))
    assert counts(db)["txflow_funding_obs"] == 2

    later = copy.deepcopy(changed)
    later["time"] += 3600000                                                       # same values, later: no row
    wp._txflow_trades_refresh_worker(now_utc=NOW, post=FakeTxPost(state=later))
    assert counts(db)["txflow_funding_obs"] == 2


def test_a_failing_wallet_is_recorded(db, monkeypatch, capsys):
    wp._txflow_trades_refresh_worker(now_utc=NOW, post=FakeTxPost())
    ok_at = db.execute("SELECT last_ok_at FROM txflow_sync_state").fetchone()[0]
    monkeypatch.setattr(wp, "_TXFLOW_TRADES_IN_FLIGHT", True)
    wp._txflow_trades_refresh_worker(now_utc=NOW, post=FakeTxPost(fail=True))
    st = dict(db.execute("SELECT * FROM txflow_sync_state").fetchone())
    assert st["last_error"] == "ConnectionError: down" and st["last_ok_at"] == ok_at and st["last_sync_at"]
    assert wp._TXFLOW_TRADES_IN_FLIGHT is False
    assert "errors=1" in capsys.readouterr().out


@pytest.mark.parametrize("kind,bad", [("userFills", {"x": 1}), ("historicalOrders", None), ("clearinghouseState", [])])
def test_unexpected_answers_raise(db, kind, bad):
    post = FakeTxPost()
    real = post.__call__
    fake = lambda body: bad if body["type"] == kind else real(body)
    with pytest.raises(ValueError):
        wp._txflow_trades_sync_wallet(db, W, post=fake, now_utc=NOW)


def test_kick(db, monkeypatch):
    spawned = []
    monkeypatch.setattr(wp, "_spawn_txflow_trades_refresh_thread", lambda: spawned.append(1))
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {})
    assert wp._maybe_kick_txflow_trades_refresh(NOW) is False and spawned == []
    assert wp._TXFLOW_TRADES_IN_FLIGHT is False and wp._TXFLOW_TRADES_LAST_KICK["at"] is None
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {W: {"perp_venues": ["txflow"]}})
    assert wp._maybe_kick_txflow_trades_refresh(NOW) is True and spawned == [1]
    assert wp._maybe_kick_txflow_trades_refresh(NOW, force=True) is False             # one in flight
    monkeypatch.setattr(wp, "_TXFLOW_TRADES_IN_FLIGHT", False)
    assert wp._maybe_kick_txflow_trades_refresh(NOW) is False                          # inside the TTL
    assert wp._maybe_kick_txflow_trades_refresh(NOW, force=True) is True and len(spawned) == 2

    def boom():
        raise RuntimeError("no threads")
    monkeypatch.setattr(wp, "_TXFLOW_TRADES_IN_FLIGHT", False)
    monkeypatch.setattr(wp, "_spawn_txflow_trades_refresh_thread", boom)
    assert wp._maybe_kick_txflow_trades_refresh(NOW, force=True) is False and wp._TXFLOW_TRADES_IN_FLIGHT is False


def test_snapshot_path_kicks_the_txflow_sync(db, monkeypatch):
    kicks = []
    monkeypatch.setattr(wp, "_tao_state_for_snapshot", lambda now: None)
    monkeypatch.setattr(wp, "_maybe_kick_hl_trades_refresh", lambda now, force=False: True)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_trades_refresh", lambda now, force=False: kicks.append(now) or True)
    monkeypatch.setattr(wp, "get_portfolio_data", lambda force_refresh=False: {"ok": force_refresh})
    assert wp._get_portfolio_data_for_snapshot(force_refresh=True) == {"ok": True} and len(kicks) == 1

    def boom(now, force=False):
        raise RuntimeError("kick failed")
    monkeypatch.setattr(wp, "_maybe_kick_txflow_trades_refresh", boom)
    assert wp._get_portfolio_data_for_snapshot(force_refresh=True) == {"ok": True}


# ── f. funding readings from the open-perps refresh ──────────────────────

def test_open_perps_refresh_records_readings(db, monkeypatch):
    state = _load("clearinghouseState")
    monkeypatch.setattr(wp, "_txflow_fetch_states", lambda wallets, post=None: {
        "wallets": {W: {"state": state, "fetched_at": NOW.isoformat()}}, "errors": {}})
    wp._txflow_refresh_worker([W], now_utc=NOW)
    assert wp._txflow_cache_copy()["wallets"][W]["state"] == state
    rows = [dict(r) for r in db.execute("SELECT wallet, coin, observed_ms, since_open FROM txflow_funding_obs")]
    assert rows == [{"wallet": W, "coin": "HYPE", "observed_ms": state["time"], "since_open": "-0.0172009883"}]
    wp._txflow_refresh_worker([W], now_utc=NOW)                                       # unchanged: no new row
    assert counts(db)["txflow_funding_obs"] == 1


def test_open_perps_refresh_survives_a_db_failure(db, monkeypatch, capsys):
    state = _load("clearinghouseState")
    monkeypatch.setattr(wp, "_txflow_fetch_states", lambda wallets, post=None: {
        "wallets": {W: {"state": state, "fetched_at": NOW.isoformat()}}, "errors": {}})

    def boom(*a, **k):
        raise RuntimeError("db locked")
    monkeypatch.setattr(wp, "_txflow_record_funding_obs", boom)
    monkeypatch.setattr(wp, "_TXFLOW_IN_FLIGHT", True)
    wp._txflow_refresh_worker([W], now_utc=NOW)
    c = wp._txflow_cache_copy()
    assert c["wallets"][W]["state"] == state and c["fetched_at"] == NOW.isoformat() and c["error"] is None
    assert wp._TXFLOW_IN_FLIGHT is False
    out = capsys.readouterr().out
    assert "[txflow] funding obs failed RuntimeError" in out and "db locked" not in out and W[2:] not in out


# ── g. GET /api/trading/trades and the annotation PUT ────────────────────

@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(wp, "_maybe_kick_hl_trades_refresh", lambda now, force=False: False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_trades_refresh", lambda now, force=False: False)
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", lambda now: False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", lambda now: False)
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": None, "wallets": {}})
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def seed(db, monkeypatch, shift_days=0):
    state = shift(_load("clearinghouseState"), shift_days)
    wp._txflow_trades_refresh_worker(now_utc=NOW, post=FakeTxPost(state=state, shift_days=shift_days))
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": NOW.isoformat(), "error": None,
                                              "wallets": {W: {"state": state, "fetched_at": NOW.isoformat()}}})
    return state


def trades_by_symbol(body, source):
    return {t["symbol"]: t for t in body["trades"] if t["source"] == source}


def test_route_lists_txflow_trades(db, client, monkeypatch):
    seed(db, monkeypatch)
    r = client.get('/api/trading/trades')
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert W not in text and W[2:] not in text and W.upper()[2:] not in text
    body = r.get_json()
    tx = trades_by_symbol(body, "txflow")
    assert set(tx) == {"PENGU", "HYPE"}
    p, h = tx["PENGU"], tx["HYPE"]
    assert (p["market"], p["venue"], p["wallet_label"], p["status"]) == ("perp", "TxFlow", "TxFlow main", "closed")
    assert p["stop"] == {"px": "0.01017463", "source": "txflow_order", "set_at": _iso(PENGU_OPEN)}
    assert (p["r_multiple"], p["r_basis"], p["net_pnl"]) == ("-1.013233", "net", "-144.210615")
    assert "funding_missing" in p["flags"] and p["before_rule"] is True
    assert p["gate"] == {"eligible": False, "reason": "before_rule"}
    assert h["status"] == "open" and h["stop"] == {"px": "90.21491", "source": "txflow_tpsl", "set_at": _iso(HYPE_OPEN)}
    assert h["unrealized_pnl"] == "-55.623046" and "funding_approx" in h["flags"]
    assert h["funding"] == "-0.017201" and h["r_multiple"] is None
    perp = body["summary"]["perp"]
    assert perp["all_time"] == {"closed_count": 1, "net_pnl": "-144.210615"}
    assert perp["closed_count"] == 0 and perp["open_count"] == 0                     # both opened before the rule


def test_route_panels_count_txflow_trades_after_the_rule(db, client, monkeypatch):
    seed(db, monkeypatch, shift_days=10)                                             # Sep 17-18: inside the gate
    body = client.get('/api/trading/trades').get_json()
    tx = trades_by_symbol(body, "txflow")
    assert tx["PENGU"]["before_rule"] is False and tx["PENGU"]["attention"] == "needs_review"
    assert tx["PENGU"]["gate"]["reason"] == "needs_review"
    assert tx["HYPE"]["attention"] is None                                          # it has the live stop
    perp = body["summary"]["perp"]
    assert (perp["closed_count"], perp["open_count"], perp["net_pnl"], perp["loss_count"]) == (1, 1, "-144.210615", 1)
    assert perp["needs_review_count"] == 1 and perp["needs_stop_count"] == 0
    assert perp["avg_r"] == "-1.013233"


def test_put_annotation_on_a_txflow_trade(db, client, monkeypatch):
    seed(db, monkeypatch, shift_days=10)
    pid = trades_by_symbol(client.get('/api/trading/trades').get_json(), "txflow")["PENGU"]["trade_id"]
    r = client.put(f'/api/trading/trades/{pid}/annotation', json={"followed_rules": True})
    assert r.status_code == 200
    a = r.get_json()["annotation"]
    assert a["market"] == "perp" and a["followed_rules"] is True
    p = trades_by_symbol(client.get('/api/trading/trades').get_json(), "txflow")["PENGU"]
    assert p["gate"] == {"eligible": True, "reason": None} and p["stop"]["source"] == "txflow_order"
    gate = client.get('/api/trading/trades').get_json()["summary"]["gate"]
    assert gate["by_market"]["perp"] == {"eligible_count": 1, "expectancy_r": "-1.013233"}
    # an annotation stop overrides the order stop; one set after the close fails the gate
    r = client.put(f'/api/trading/trades/{pid}/annotation', json={"stop_px": "0.0101"})
    p = trades_by_symbol(client.get('/api/trading/trades').get_json(), "txflow")["PENGU"]
    assert p["stop"]["source"] == "manual" and p["gate"]["reason"] == "stop_after_close"


def test_same_address_on_both_venues_gets_distinct_ids(db, client, monkeypatch):
    seed(db, monkeypatch)
    db.execute("INSERT INTO hl_sync_state (wallet, first_seen_at) VALUES (?, ?)", (W, NOW.isoformat()))
    for f in _load("userFills"):
        if f["coin"] == "PENGU":
            db.execute("INSERT INTO hl_fills (wallet, tid, coin, time_ms, raw_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                       (W, f["tid"], f["coin"], f["time"], json.dumps(f), NOW.isoformat()))
    db.commit()
    r = client.get('/api/trading/trades')
    text = r.get_data(as_text=True)
    assert W not in text and W[2:] not in text
    body = r.get_json()
    hl, tx = trades_by_symbol(body, "hyperliquid")["PENGU"], trades_by_symbol(body, "txflow")["PENGU"]
    assert hl["trade_id"] != tx["trade_id"]
    ids = [t["trade_id"] for t in body["trades"]]
    assert len(ids) == len(set(ids))


def test_wallets_no_longer_listed_are_left_out(db, client, monkeypatch):
    seed(db, monkeypatch)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {})
    body = client.get('/api/trading/trades').get_json()
    assert trades_by_symbol(body, "txflow") == {}


def test_stop_missing_follows_the_live_stop(db, client, monkeypatch):
    state = seed(db, monkeypatch, shift_days=10)
    h = trades_by_symbol(client.get('/api/trading/trades').get_json(), "txflow")["HYPE"]
    assert h["stop"]["source"] == "txflow_tpsl" and "stop_missing" not in h["flags"] and "funding_approx" in h["flags"]
    bare = copy.deepcopy(state)
    for ap in bare["assetPositions"]:
        ap["tpsl"] = []
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": NOW.isoformat(), "error": None,
                                              "wallets": {W: {"state": bare, "fetched_at": NOW.isoformat()}}})
    h = trades_by_symbol(client.get('/api/trading/trades').get_json(), "txflow")["HYPE"]
    assert h["stop"] is None and "stop_missing" in h["flags"] and h["attention"] == "needs_stop"


@pytest.fixture(autouse=True)
def _gate_counts_every_date(monkeypatch):
    """Landing 15: the gate counts only perp trades opened on or after
    TRADES_GATE_COUNT_FROM. This file's trades are dated before it and test
    the other gate checks, so the count date is set to 1970-01-01 here, which
    is the gate as it was before Landing 15 (before_rule is still the only
    date check). tests/test_gate_count_from.py tests the date itself."""
    monkeypatch.setattr(wp, "TRADES_GATE_COUNT_FROM", "1970-01-01")


@pytest.fixture(autouse=True)
def _gate_without_rule_check(monkeypatch):
    """Landing 17: a trade that passes the gate's own checks also needs the
    rule check (_trades_rule_gate). This file's trades carry no setup / POI
    tags and test the gate's own checks, so the rule check is turned off
    here, which is the gate as it was before Landing 17.
    tests/test_gate_rule_check.py tests the rule check itself."""
    monkeypatch.setattr(wp, "_trades_rule_gate", lambda conn, trades, now_ms=None: None)
