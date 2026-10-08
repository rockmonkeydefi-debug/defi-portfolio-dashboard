"""Settled stop (Landing 6, HANDOFF_spot_perps_rebuild.md 18): the stop in
force 10 minutes after the open (or just before an earlier close) is the
stop a synced perp trade's R, 1R and gate use - Glenn often corrects a stop
placed in a hurry at entry within minutes. hl_trades.settled_stops, the
trades route's "stop" and "stop_correction", and the annotation stop still
winning.

The order fixtures are the recorded, sanitized Hyperliquid exports in
tests/fixtures/hl_trading (prices scaled, R unchanged). Real init_db() on a
tmp_path SQLite file (portfolio_db.get_db_path monkeypatched). No network.
Fake wallet addresses only, built in code; made-up prices.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
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
import src.storage.portfolio_db as portfolio_db

HL_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "hl_trading")
W = "0x" + "d" * 40
MIN = 60000
HOUR = 3600000
DAY = 86400000
T0 = int(datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)


def _hl(name):
    with open(os.path.join(HL_FIX, name)) as f:
        return json.load(f)


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def rec(oid, px, placed, side="A", coin="ETH", status="open", status_ts=None, kind="Stop Market", reduce_only=True,
        trigger=True):
    """One historicalOrders record (Hyperliquid shape)."""
    return {"status": status, "statusTimestamp": status_ts if status_ts is not None else placed,
            "order": {"coin": coin, "side": side, "oid": oid, "timestamp": placed, "triggerPx": str(px),
                      "isTrigger": trigger, "reduceOnly": reduce_only, "isPositionTpsl": False,
                      "orderType": kind, "children": []}}


def ended(oid, px, placed, at, status="canceled", **kw):
    """A stop placed at `placed` and ended at `at` (both records, as Hyperliquid keeps them)."""
    return [rec(oid, px, placed, **kw), rec(oid, px, placed, status=status, status_ts=at, **kw)]


def cycle(key="k", direction="long", open_ms=T0, close_ms=T0 + DAY, coin="ETH"):
    return {"trade_key": key, "coin": coin, "direction": direction, "open_time": open_ms, "close_time": close_ms}


# ── the recorded exports ─────────────────────────────────────────────────

def _fixture(wallet):
    orders = _hl(f"{wallet}.hist_orders.json")
    cycles = hl_trades.build_cycles(wallet, _hl(f"{wallet}.fills.json"), _hl(f"{wallet}.funding.json"), orders)["cycles"]
    return cycles, hl_trades.settled_stops(cycles, orders)


def _r(c, stop_px):
    risk = abs(Decimal(c["avg_entry_px"]) - Decimal(stop_px)) * Decimal(c["peak_size"])
    return float(Decimal(c["net_pnl"]) / risk)


def test_recorded_exports_eight_stops_corrected_after_entry():
    corrected = []
    for w in ("rm", "rabby"):
        cycles, settled = _fixture(w)
        for c in cycles:
            s = settled.get(c["trade_key"])
            assert s is not None and c["initial_stop_px"] is not None                  # every recorded trade has both
            if Decimal(s["px"]) != Decimal(c["initial_stop_px"]):
                assert c["open_time"] - hl_trades.STOP_LOOKBACK_MS <= s["placed"] <= c["open_time"] + hl_trades.SETTLE_MS
                corrected.append((w, c["coin"], round(float(c["r_multiple"]), 2) if c["r_multiple"] else None,
                                  round(_r(c, s["px"]), 2) if c["status"] == "closed" else None))
    assert len(corrected) == 8
    by = {(w, coin, r): new for w, coin, r, new in corrected}
    assert by[("rabby", "HYPE", -3.27)] == pytest.approx(-1.04, abs=0.01)                 # a 30-second placeholder stop
    assert by[("rabby", "ZEC", -0.31)] == pytest.approx(-1.06, abs=0.01)                  # corrected tighter: a full loss
    assert by[("rm", "BTC", -1.37)] == pytest.approx(-1.1, abs=0.01)


# ── hl_trades.settled_stops rules ────────────────────────────────────────

def test_a_stop_corrected_within_ten_minutes_is_the_settled_stop():
    orders = ended(1, 95, T0, T0 + 2 * MIN) + [rec(2, 92, T0 + 2 * MIN)]
    assert hl_trades.settled_stops([cycle()], orders) == {"k": {"px": "92", "placed": T0 + 2 * MIN}}


def test_a_later_move_does_not_change_it():
    orders = ended(1, 95, T0, T0 + 15 * MIN) + [rec(2, 99, T0 + 15 * MIN)]
    assert hl_trades.settled_stops([cycle()], orders)["k"]["px"] == "95"


def test_several_corrections_the_last_one_in_the_window_wins():
    orders = (ended(1, 95, T0, T0 + MIN) + ended(2, 90, T0 + MIN, T0 + 4 * MIN) + ended(3, 93, T0 + 4 * MIN, T0 + 30 * MIN)
              + [rec(4, 99, T0 + 30 * MIN)])
    assert hl_trades.settled_stops([cycle()], orders)["k"] == {"px": "93", "placed": T0 + 4 * MIN}


def test_a_trade_closed_inside_the_window_uses_the_stop_just_before_the_close():
    close = T0 + 3 * MIN
    orders = ended(1, 95, T0, T0 + MIN) + ended(2, 97, T0 + MIN, close, status="filled")
    assert hl_trades.settled_stops([cycle(close_ms=close)], orders)["k"]["px"] == "97"


def test_no_stop_in_force_at_ten_minutes_is_absent():
    orders = ended(1, 95, T0, T0 + 5 * MIN) + [rec(2, 96, T0 + 20 * MIN)]
    assert hl_trades.settled_stops([cycle()], orders) == {}


def test_open_trades_short_trades_and_other_orders():
    orders = [rec(1, 95, T0 + MIN),
              rec(2, 105, T0 + 2 * MIN, kind="Take Profit Market"),            # a take-profit
              rec(3, 94, T0 + 3 * MIN, side="B"),                              # the opening side
              rec(4, 93, T0 + 3 * MIN, coin="BTC"),                            # another coin
              rec(5, 92, T0 + 3 * MIN, reduce_only=False),                     # not reduce-only
              rec(6, 91, T0 + 3 * MIN, trigger=False),                         # not a trigger
              rec(7, 90, T0 - 4 * DAY)]                                        # before the lookback
    short = cycle("s", direction="short", coin="SOL")
    got = hl_trades.settled_stops([cycle(close_ms=None), short], orders + [rec(8, 108, T0 + MIN, side="B", coin="SOL")])
    assert got == {"k": {"px": "95", "placed": T0 + MIN}, "s": {"px": "108", "placed": T0 + MIN}}
    assert hl_trades.settled_stops([], orders) == {} and hl_trades.settled_stops([cycle()], None) == {}
    assert hl_trades.settled_stops([cycle()], [None, "x", {"order": None}] + orders)["k"]["px"] == "95"


# ── the trades route ─────────────────────────────────────────────────────

def fill(coin, tid, t, side, sz, px, start, pnl="0"):
    return {"coin": coin, "tid": tid, "time": t, "side": side, "sz": sz, "px": px, "startPosition": start,
            "closedPnl": pnl, "fee": "0", "builderFee": "0", "dir": "x", "oid": tid, "hash": "0x0"}


BTC_OPEN, BTC_CLOSE = T0, T0 + 20 * HOUR
ETH_OPEN, ETH_CLOSE = T0 + 2 * DAY, T0 + 2 * DAY + 5 * HOUR


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
    # BTC: a long from 100,000 that lost $10 on 0.01; a hurried stop at 99,900 corrected 2 minutes in to 99,000, hit at close.
    # ETH: a long with one stop, never corrected.
    for f in (fill("BTC", 1, BTC_OPEN, "B", "0.01", "100000", "0"),
              fill("BTC", 2, BTC_CLOSE, "A", "0.01", "99000", "0.01", pnl="-10"),
              fill("ETH", 3, ETH_OPEN, "B", "1", "4000", "0"),
              fill("ETH", 4, ETH_CLOSE, "A", "1", "4100", "1", pnl="100")):
        conn.execute("INSERT INTO hl_fills (wallet, tid, coin, time_ms, raw_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (W, f["tid"], f["coin"], f["time"], json.dumps(f), "2026-09-26T00:00:00+00:00"))
    records = (ended(10, 99900, BTC_OPEN, BTC_OPEN + 2 * MIN, coin="BTC")
               + ended(11, 99000, BTC_OPEN + 2 * MIN, BTC_CLOSE, coin="BTC", status="filled")
               + ended(12, 3950, ETH_OPEN, ETH_CLOSE, coin="ETH", status="reduceOnlyCanceled"))
    for i, r in enumerate(records):
        conn.execute("INSERT INTO hl_orders (wallet, oid, coin, status, status_ts, order_ts, raw_json, fetched_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (W, r["order"]["oid"], r["order"]["coin"], r["status"], r["statusTimestamp"] + i,
                      r["order"]["timestamp"], json.dumps(r), "2026-09-26T00:00:00+00:00"))
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
    assert W not in text and W[2:] not in text
    return {t["symbol"]: t for t in r.get_json()["trades"]}


def test_route_uses_the_settled_stop_for_r(db, client):
    btc = trades(client)["BTC"]
    assert btc["stop"] == {"px": "99000", "source": "hl_order", "set_at": _iso(BTC_OPEN + 2 * MIN)}
    assert btc["stop_correction"] == {"from_px": "99900", "from_set_at": _iso(BTC_OPEN), "to_px": "99000",
                                      "to_set_at": _iso(BTC_OPEN + 2 * MIN), "minutes_after_open": 2.0}
    assert btc["r_multiple"] == "-1.000000"                     # -10 / (1,000 x 0.01), not -10 / (100 x 0.01)
    eng = next(c for c in wp._hl_trade_cycles(db)["cycles"] if c["coin"] == "BTC")
    assert eng["initial_stop_px"] == "99900" and eng["r_multiple"] == "-10.000000"   # the engine's own rule is unchanged


def test_an_uncorrected_stop_has_no_correction(db, client):
    eth = trades(client)["ETH"]
    assert eth["stop"]["px"] == "3950" and eth["stop_correction"] is None and eth["r_multiple"] == "2.000000"


def test_the_annotation_stop_still_wins(db, client):
    btc_id = trades(client)["BTC"]["trade_id"]
    db.execute("INSERT INTO trade_annotations (trade_id, market, stop_px, stop_set_at, stop_source, created_at, updated_at) "
               "VALUES (?, 'perp', '99500', ?, 'manual', 'x', 'x')", (btc_id, _iso(BTC_OPEN + MIN)))
    db.commit()
    btc = trades(client)["BTC"]
    assert btc["stop"]["source"] == "manual" and btc["stop"]["px"] == "99500" and btc["stop_correction"] is None
    assert btc["r_multiple"] == "-2.000000"


def test_gate_counts_the_corrected_trade(db, client):
    btc_id = trades(client)["BTC"]["trade_id"]
    db.execute("INSERT INTO trade_annotations (trade_id, market, followed_rules, created_at, updated_at) "
               "VALUES (?, 'perp', 1, 'x', 'x')", (btc_id,))
    db.commit()
    btc = trades(client)["BTC"]
    assert btc["gate"] == {"eligible": True, "reason": None} and btc["r_multiple"] == "-1.000000"


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
