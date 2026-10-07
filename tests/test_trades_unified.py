"""Unified trades (HANDOFF_trading_performance.md Commit 4b; rulings 7-14 and
Glenn's Oct 1 rulings G1 / G2): the trade_annotations table and
spot_trade_log.market, GET /api/trading/trades (spot, Hyperliquid and manual
trades; effective stop, R, attention, gate verdict; spot / perp panels and the
gate), PUT /api/trading/trades/<id>/annotation, opaque trade ids, and the
market field on the manual trade-log routes.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). The Hyperliquid tables are filled from the sanitized
fixtures in tests/fixtures/hl_trading through the real sync worker and a fake
post, as tests/test_hl_trades_sync.py does. No network: _hl_post and
_txflow_post raise, the kick is recorded. Fake addresses only, built in code.

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

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "hl_trading")
W_RM = "0x" + "a" * 40
W_RABBY = "0x" + "b" * 40
NAMES = {W_RM: "rm", W_RABBY: "rabby"}
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
ADDR = {k: "0x" + str(k) * 40 for k in range(1, 6)}       # fake token contracts
Q6 = Decimal("0.000001")
H = 3600000
DAY = 24 * H
T_SYN = 1789862400000                                       # 2026-09-20T00:00Z


def _load(name, kind):
    with open(os.path.join(FIX, f"{name}.{kind}.json")) as f:
        return json.load(f)


def _golden():
    with open(os.path.join(FIX, "expected_cycles.json")) as f:
        return json.load(f)


class FakePost:
    """Serves the fixtures by payload type (the tests/test_hl_trades_sync.py fake)."""

    def __call__(self, payload):
        name = NAMES[payload.get("user")]
        kind = payload["type"]
        if kind == "userFillsByTime":
            rows = sorted(_load(name, "fills"), key=lambda r: r["time"])
            return [r for r in rows if r["time"] >= payload["startTime"]][:2000]
        if kind == "userFunding":
            rows = sorted(_load(name, "funding"), key=lambda r: r["time"])
            return [r for r in rows if r["time"] >= payload["startTime"]][:500]
        if kind == "historicalOrders":
            return _load(name, "hist_orders")
        raise AssertionError(f"unexpected payload {payload}")


FIXTURE_START = min(r["time"] for n in ("rm", "rabby") for k in ("fills", "funding") for r in _load(n, k))


def _never(*a, **k):
    raise AssertionError("no venue call here")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.setattr(wp, "_HL_TRADES_IN_FLIGHT", False)
    monkeypatch.setattr(wp, "_HL_TRADES_LAST_KICK", {"at": None})
    monkeypatch.setattr(wp, "HL_TRADES_START_MS", FIXTURE_START)
    monkeypatch.setattr(wp, "_spawn_hl_trades_refresh_thread", lambda: None)
    monkeypatch.setattr(wp, "_hl_post", _never)
    monkeypatch.setattr(wp, "_txflow_post", _never)
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": None, "wallets": {}})
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {W_RM: {"label": "Hyperliquid RM"}})
    conn = portfolio_db.get_connection()
    yield conn
    conn.close()


@pytest.fixture
def client(db, monkeypatch):
    kicks = []
    cache_kicks = []
    monkeypatch.setattr(wp, "_maybe_kick_hl_trades_refresh", lambda now, force=False: kicks.append(now) or False)
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", lambda now: cache_kicks.append("hl_accounts") or False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", lambda now: cache_kicks.append("txflow") or False)
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    c.kicks = kicks
    c.cache_kicks = cache_kicks
    return c


def tx(conn, date, symbol, side, units, total, contract=None):
    chain, addr = ("base", contract) if contract else ("", "")
    conn.execute("INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, chain, "
                 "contract_address) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (date, symbol, side, units, total, total, chain, addr))
    conn.commit()


def annotate(conn, trade_id, market="spot", **fields):
    """Seed an annotation row directly (setup only; the route never deletes)."""
    row = {"trade_id": trade_id, "market": market, "created_at": "2026-09-01T00:00:00+00:00",
           "updated_at": "2026-09-01T00:00:00+00:00", **fields}
    if "stop_px" in fields:
        row.setdefault("stop_source", "manual")
    cols = list(row)
    conn.execute(f"INSERT INTO trade_annotations ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                 tuple(row[c] for c in cols))
    conn.commit()


def manual(conn, **fields):
    row = {"ticker": "SOL", "direction": "long", "source": "manual", "venue": None, "entry_price": 100.0,
           "stop_price": 95.0, "qty": 2.0, "entered_at": "2026-09-20T10:00:00+00:00", **fields}
    cols = list(row)
    cur = conn.execute(f"INSERT INTO spot_trade_log ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                       tuple(row[c] for c in cols))
    conn.commit()
    return cur.lastrowid


def weekly(conn, symbol, state, flip_bar_open_iso, computed_at="2026-09-30T12:00:00+00:00", timeframe="1w"):
    """A Trends scanner row (noodle_state); flip_ts is epoch seconds of the flip bar's open."""
    flip_ts = None if flip_bar_open_iso is None else datetime.fromisoformat(flip_bar_open_iso).timestamp()
    conn.execute("INSERT INTO noodle_state (symbol, timeframe, state, flip_ts, computed_at) VALUES (?, ?, ?, ?, ?)",
                 (symbol, timeframe, state, flip_ts, computed_at))
    conn.commit()


def spot_id(key, first_buy_id):
    return wp._trade_id(f"{key}|{first_buy_id}")


def seed_hl(conn, monkeypatch):
    monkeypatch.setattr(wp, "_hl_accounts_state_for_snapshot", lambda now: {"wallets": {W_RM: {}, W_RABBY: {}}})
    wp._hl_trades_refresh_worker(now_utc=NOW, post=FakePost())
    monkeypatch.setattr(wp, "_hl_accounts_state_for_snapshot", _never)


def seed_spot(conn):
    """One spot trade per gate outcome. Returns {symbol: trade_id}."""
    ids = {}
    k = lambda sym, n=None: ("base " + ADDR[n]) if n else sym
    plan = [  # symbol, contract, rows
        ("AAA", 1, [("2026-08-01", "buy", 10, 100), ("2026-08-05", "sell", 10, 150)]),       # before the rule
        ("BBB", 2, [("2026-09-15", "buy", 10, 100), ("2026-09-20", "sell", 10, 130)]),       # eligible, R 3
        ("CCC", 3, [("2026-09-16", "buy", 10, 100), ("2026-09-22", "sell", 10, 110)]),       # stop set after close
        ("DDD", None, [("2026-09-16", "buy", 100, 100), ("2026-09-18", "sell", 99.5, 199),
                       ("2026-09-19", "sell", 0.5, 5)]),                                     # after-close sale $4.50
        ("EEE", None, [("2026-09-16", "buy", 100, 100), ("2026-09-18", "sell", 99.5, 199),
                       ("2026-09-19", "sell", 0.5, 1.2)]),                                   # after-close dust $0.70
        ("FFF", 4, [("2026-09-20", "buy", 10, 100), ("2026-09-21", "sell", 10, 120)]),       # long_term book
        ("GGG", None, [("2026-09-24", "buy", 10, 100)]),                                     # open, no stop
        ("HHH", None, [("2026-09-20", "buy", 10, 100), ("2026-09-21", "sell", 10, 90)]),     # not reviewed
        ("III", None, [("2026-09-20", "buy", 10, 100), ("2026-09-21", "sell", 10, 80)]),     # deviated
        ("JJJ", None, [("2026-09-20", "buy", 10, 100), ("2026-09-21", "sell", 10, 105)]),    # no stop
        ("KKK", None, [("2026-09-20", "buy", 10, 100), ("2026-09-21", "sell", 10, 105)]),    # stop = entry: no R
        ("LLL", 5, [("2026-09-20", "buy", 10, 100), ("2026-09-21", "sell", 5, 60)]),         # partly closed
    ]
    for sym, n, rows in plan:
        first = None
        for date, side, units, total in rows:
            tx(conn, date, sym.lower(), side, units, total, ADDR[n] if n else None)
            if first is None:
                first = conn.execute("SELECT MAX(id) FROM spot_transactions").fetchone()[0]
        ids[sym] = spot_id(k(sym, n), first)
    before = "2026-09-14T00:00:00+00:00"
    annotate(conn, ids["BBB"], stop_px="9", stop_set_at=before, followed_rules=1)
    annotate(conn, ids["CCC"], stop_px="9", stop_set_at="2026-09-23T08:00:00+00:00", followed_rules=1)
    annotate(conn, ids["DDD"], stop_px="0.9", stop_set_at="2026-09-16T01:00:00+00:00", followed_rules=1)
    annotate(conn, ids["EEE"], stop_px="0.9", stop_set_at="2026-09-16T01:00:00+00:00", followed_rules=1)
    annotate(conn, ids["FFF"], stop_px="9", stop_set_at=before, followed_rules=1)
    annotate(conn, ids["III"], stop_px="9", stop_set_at="2026-09-20T01:00:00+00:00", followed_rules=0,
             deviation_note="chased")
    annotate(conn, ids["JJJ"], followed_rules=1, notes="no stop set")
    annotate(conn, ids["KKK"], stop_px="10", stop_set_at="2026-09-20T01:00:00+00:00", followed_rules=1)
    conn.execute("INSERT INTO spot_position_books (position_key, book, updated_at) VALUES (?, 'long_term', ?)",
                 ("base " + ADDR[4], "2026-09-20T00:00:00+00:00"))
    conn.commit()
    return ids


@pytest.fixture
def seeded(db, client, monkeypatch):
    seed_hl(db, monkeypatch)
    ids = seed_spot(db)
    ids["M_PERP"] = wp._trade_id("manual|%d" % manual(db, ticker="SOL", direction="Long", market="perp",
                                                          venue="TXflow", exit_price=110.0,
                                                          exited_at="2026-09-21T10:00:00+00:00", followed_rules=1))
    ids["M_OPEN"] = wp._trade_id("manual|%d" % manual(db, ticker="kBONK", entered_at="2026-09-25T09:00:00+00:00"))
    return db, client, ids


def get(client):
    r = client.get('/api/trading/trades')
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def by_id(body):
    return {t["trade_id"]: t for t in body["trades"]}


# ── schema ───────────────────────────────────────────────────────────────

def test_schema_and_init_db_idempotent(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(trade_annotations)")}
    assert cols == {"trade_id", "market", "stop_px", "stop_set_at", "stop_source", "followed_rules",
                    "deviation_note", "notes", "scanner_snapshot_json", "scanner_captured_at",
                    "created_at", "updated_at", "exit_reason", "exit_reason_note"}     # exit_reason*: Landing 8c-2
    assert "market" in {r["name"] for r in db.execute("PRAGMA table_info(spot_trade_log)")}
    portfolio_db.init_db()                                  # a second call raises nothing
    with pytest.raises(Exception):
        annotate(db, "t1", market="fx")
    with pytest.raises(Exception):
        annotate(db, "t2", stop_px="1", stop_source="hl_order")


def test_trade_id_shape():
    tid = wp._trade_id("x|1")
    assert tid.startswith("t") and len(tid) == 21 and tid == wp._trade_id("x|1") != wp._trade_id("x|2")


# ── GET: sources, privacy, ids ───────────────────────────────────────────

def test_hl_cycles_match_the_golden_file(seeded):
    db, client, ids = seeded
    body = get(client)
    trades = by_id(body)
    gold = _golden()["cycles"]
    wallet_of = {"rm": W_RM, "rabby": W_RABBY}
    for c in gold:
        t = trades[wp._trade_id(f"{wallet_of[c['wallet']]}|{c['coin']}|{c['first_tid']}")]
        assert (t["market"], t["source"], t["venue"], t["book"]) == ("perp", "hyperliquid", "Hyperliquid", "trading")
        assert t["symbol"] == c["coin"] and t["direction"] == c["direction"] and t["status"] == c["status"]
        assert t["net_pnl"] == c["net_pnl"] and t["size_peak"] == c["peak_size"]
        assert t["fees"] == c["fees"] and t["funding"] == c["funding"]
        assert t["before_rule"] is True and t["position_key"] is None
        assert t["opened_at"] == datetime.fromtimestamp(c["open_time"] / 1000, timezone.utc).isoformat()
    assert sum(1 for t in body["trades"] if t["source"] == "hyperliquid") == 20
    closed_sum = sum((Decimal(c["net_pnl"]) for c in gold if c["status"] == "closed"), Decimal(0))
    perp_all = body["summary"]["perp"]["all_time"]
    assert perp_all["closed_count"] == 19 + 1                               # + the closed manual perp row
    assert Decimal(perp_all["net_pnl"]) == (closed_sum + Decimal("20")).quantize(Q6)
    assert client.kicks and len(client.kicks) == 1


def test_no_wallet_address_in_any_response(seeded):
    _, client, _ = seeded
    for url in ('/api/trading/trades', '/api/trading/perps/trades'):
        text = client.get(url).get_data(as_text=True)
        for w in (W_RM, W_RABBY):
            assert w not in text and w[2:] not in text and w.upper()[2:] not in text
    perps = client.get('/api/trading/perps/trades').get_json()["trades"]
    assert all("wallet" not in t and "trade_key" not in t and t["trade_id"].startswith("t") for t in perps)


def test_trade_ids_unique_and_stable(seeded):
    _, client, _ = seeded
    a = [t["trade_id"] for t in get(client)["trades"]]
    b = [t["trade_id"] for t in get(client)["trades"]]
    assert a == b and len(a) == len(set(a)) == 20 + 12 + 2
    perps = {t["trade_id"] for t in client.get('/api/trading/perps/trades').get_json()["trades"]}
    assert perps <= set(a)


def test_sorted_newest_first(seeded):
    _, client, _ = seeded
    trades = get(client)["trades"]
    when = [wp._trades_dt(t["opened_at"]) for t in trades]
    assert when == sorted(when, reverse=True)
    assert trades[0]["trade_id"] == seeded[2]["M_OPEN"]                      # 2026-09-25T09:00Z


def test_manual_rows(seeded):
    _, client, ids = seeded
    t = by_id(get(client))
    mp, mo = t[ids["M_PERP"]], t[ids["M_OPEN"]]
    assert (mp["market"], mp["source"], mp["venue"], mp["direction"], mp["status"]) == \
           ("perp", "manual", "TXflow", "long", "closed")
    assert mp["net_pnl"] == "20.000000" and mp["size_peak"] == "2" and mp["avg_entry"] == "100"
    assert mp["avg_exit"] == "110" and mp["opened_at"] == "2026-09-20T10:00:00+00:00"
    assert mp["closed_at"] == "2026-09-21T10:00:00+00:00" and mp["flags"] == [] and mp["fees"] is None
    assert mp["annotation"] == {"followed_rules": True, "deviation_note": None, "notes": None,
                                "exit_reason": None, "exit_reason_note": None}
    assert (mo["market"], mo["venue"], mo["status"], mo["net_pnl"], mo["symbol"]) == \
           ("spot", "Manual", "open", None, "kBONK")
    assert mo["attention"] is None                                          # it has the log's stop


# ── stops and R ──────────────────────────────────────────────────────────

def test_stop_precedence_and_r(seeded):
    db, client, ids = seeded
    body = get(client)
    t = by_id(body)
    # spot: annotation stop, net-based R = 30 / (|10 - 9| x 10)
    assert t[ids["BBB"]]["stop"] == {"px": "9", "source": "manual", "set_at": "2026-09-14T00:00:00+00:00"}
    assert (t[ids["BBB"]]["r_multiple"], t[ids["BBB"]]["r_basis"]) == ("3.000000", "net")
    # manual: the log's stop, price-based R = (110 - 100) / 5
    assert t[ids["M_PERP"]]["stop"] == {"px": "95", "source": "manual_log", "set_at": "2026-09-20T10:00:00+00:00"}
    assert (t[ids["M_PERP"]]["r_multiple"], t[ids["M_PERP"]]["r_basis"]) == ("2.000000", "price")
    # perps: the Hyperliquid order stop, then an annotation override recomputes R
    gold = next(c for c in _golden()["cycles"] if c["status"] == "closed" and c["wallet"] == "rm")
    pid = wp._trade_id(f"{W_RM}|{gold['coin']}|{gold['first_tid']}")
    eng = next(c for c in hl_trades.build_cycles(W_RM, _load("rm", "fills"), _load("rm", "funding"),
                                                 _load("rm", "hist_orders"))["cycles"]
               if c["first_tid"] == gold["first_tid"])
    p = t[pid]
    assert p["stop"] == {"px": eng["initial_stop_px"], "source": "hl_order",
                         "set_at": datetime.fromtimestamp(eng["stop_placed"] / 1000, timezone.utc).isoformat()}
    assert p["r_multiple"] == gold["r_multiple"] and p["r_basis"] == "net" and p["avg_entry"] == eng["avg_entry_px"]
    annotate(db, pid, market="perp", stop_px="1000", stop_set_at="2026-08-01T00:00:00+00:00")
    p = by_id(get(client))[pid]
    assert p["stop"]["source"] == "manual" and p["stop"]["px"] == "1000"
    risk = abs(Decimal(eng["avg_entry_px"]) - Decimal("1000")) * Decimal(gold["peak_size"])
    assert p["r_multiple"] == str((Decimal(gold["net_pnl"]) / risk).quantize(Q6))


# ── gate, attention, panels ──────────────────────────────────────────────

def test_every_gate_reason(seeded):
    db, client, ids = seeded
    t = by_id(get(client))
    reason = lambda k: t[ids[k]]["gate"]["reason"]
    # Oct 2 ruling R1: the gate is perps-only, so every closed spot trade reads "spot".
    for k in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "HHH", "III", "JJJ", "KKK"):
        assert t[ids[k]]["gate"] == {"eligible": False, "reason": "spot"}, k
    assert reason("GGG") == "open" and reason("LLL") == "open" and t[ids["LLL"]]["status"] == "partly_closed"
    assert t[ids["AAA"]]["before_rule"] is True and t[ids["FFF"]]["book"] == "long_term"
    assert t[ids["DDD"]]["after_close_realized"] == "4.500000"
    assert "after_close_sell" in t[ids["EEE"]]["flags"]
    assert t[ids["KKK"]]["r_multiple"] is None
    assert reason("M_PERP") is None and reason("M_OPEN") == "open"
    # perps: a stop set after the close fails; every other check on the same live perp dict
    gold = next(c for c in _golden()["cycles"] if c["status"] == "closed")
    late = datetime.fromtimestamp(gold["close_time"] / 1000 + 60, timezone.utc).isoformat()
    wallet = W_RM if gold["wallet"] == "rm" else W_RABBY
    pid = wp._trade_id(f"{wallet}|{gold['coin']}|{gold['first_tid']}")
    assert t[pid]["gate"]["reason"] == "before_rule"
    live = {**t[pid], "before_rule": False, "_close_ms": gold["close_time"], "annotation": {"followed_rules": True}}
    assert wp._trades_gate_reason({**live, "stop": {"px": "1", "source": "manual", "set_at": late}}) == "stop_after_close"
    assert wp._trades_gate_reason(live) is None
    assert wp._trades_gate_reason({**live, "annotation": {"followed_rules": None}}) == "needs_review"
    assert wp._trades_gate_reason({**live, "annotation": {"followed_rules": False}}) == "deviated"
    assert wp._trades_gate_reason({**live, "stop": None}) == "no_stop"
    assert wp._trades_gate_reason({**live, "r_multiple": None}) == "no_r"
    assert wp._trades_gate_reason({**live, "status": "open"}) == "open"


def test_attention_and_panels(seeded):
    _, client, ids = seeded
    body = get(client)
    t = by_id(body)
    # Spot never nags for a stop or a review (R3); the Hyperliquid golden trades are before the rule.
    assert all(x["attention"] is None for x in body["trades"])
    no_row = {"symbol": None, "state": None, "flipped_at": None, "as_of": None}
    for x in body["trades"]:
        if x["market"] == "spot":
            assert x["weekly_trend"] == no_row and x["exit_signal"] is False
        else:
            assert x["weekly_trend"] is None and x["exit_signal"] is False
    s = body["summary"]
    assert s["attention_count"] == 0
    spot = s["spot"]
    # trading book, opened since the rule: BBB CCC DDD EEE HHH III JJJ KKK closed; GGG + manual open; LLL partly
    assert (spot["closed_count"], spot["open_count"], spot["partly_closed_count"]) == (8, 2, 1)
    assert (spot["needs_stop_count"], spot["needs_review_count"], spot["exit_signal_count"]) == (0, 0, 0)
    nets = {"BBB": 30, "CCC": 10, "DDD": 104, "EEE": 100.2, "HHH": -10, "III": -20, "JJJ": 5, "KKK": 5}
    assert spot["net_pnl"] == str(Decimal(str(sum(nets.values()))).quantize(Q6))
    assert (spot["win_count"], spot["loss_count"]) == (6, 2)
    r_closed = [t[ids[k]]["r_multiple"] for k in nets if t[ids[k]]["r_multiple"] is not None]
    assert spot["avg_r"] == wp._trades_mean(r_closed)
    assert spot["all_time"] == {"closed_count": 9, "net_pnl": str(Decimal(str(sum(nets.values()) + 50)).quantize(Q6))}
    perp = s["perp"]
    assert (perp["closed_count"], perp["net_pnl"], perp["open_count"]) == (1, "20.000000", 0)
    gate = s["gate"]
    assert (gate["start"], gate["target"]) == ("2026-09-13", 20)
    assert gate["eligible_count"] == 1 and gate["unlocked"] is False       # the manual perp only
    assert gate["by_market"] == {"perp": {"eligible_count": 1, "expectancy_r": "2.000000"}}
    assert gate["expectancy_r"] == "2.000000"
    assert s["deviated"] == {"count": 0, "avg_r": None}                    # III is spot: perps only
    assert t[ids["III"]]["r_multiple"] == "-2.000000"


def _synthetic_cycles(n, win):
    fills, orders = [], []
    for i in range(n):
        t0 = T_SYN + i * DAY
        px_out, pnl = ("110", "10") if win else ("90", "-10")
        fills.append({"coin": "ETH", "side": "B", "sz": "1", "px": "100", "startPosition": "0", "time": t0,
                      "tid": 2 * i + 1, "closedPnl": "0", "fee": "0", "dir": "Open Long", "feeToken": "USDC"})
        fills.append({"coin": "ETH", "side": "A", "sz": "1", "px": px_out, "startPosition": "1", "time": t0 + H,
                      "tid": 2 * i + 2, "closedPnl": pnl, "fee": "0", "dir": "Close Long", "feeToken": "USDC"})
        orders.append({"order": {"coin": "ETH", "side": "A", "oid": 900 + i, "timestamp": t0, "isTrigger": True,
                                 "reduceOnly": True, "orderType": "Stop Market", "triggerPx": "95", "children": []},
                       "status": "open", "statusTimestamp": t0})
    cycles = hl_trades.build_cycles(W_RM, fills, [], orders)["cycles"]
    for c in cycles:
        c["wallet_label"] = "Hyperliquid RM"
    return {"cycles": cycles, "by_wallet": {}, "sync_rows": []}


@pytest.mark.parametrize("n,win,reviewed,unlocked,expectancy", [
    (20, True, 20, True, "2.000000"),
    (20, True, 19, False, "2.000000"),
    (20, False, 20, False, "-2.000000"),
])
def test_gate_unlock(db, client, monkeypatch, n, win, reviewed, unlocked, expectancy):
    built = _synthetic_cycles(n, win)
    monkeypatch.setattr(wp, "_hl_trade_cycles", lambda conn: built)
    for c in built["cycles"][:reviewed]:
        annotate(db, wp._trade_id(c["trade_key"]), market="perp", followed_rules=1)
    gate = get(client)["summary"]["gate"]
    assert gate["eligible_count"] == reviewed and gate["expectancy_r"] == expectancy
    assert gate["unlocked"] is unlocked
    assert gate["by_market"] == {"perp": {"eligible_count": reviewed, "expectancy_r": expectancy}}


def test_unattached_annotations(seeded):
    db, client, _ = seeded
    annotate(db, "t" + "0" * 20, market="perp", notes="trade edited away")
    annotate(db, "t" + "1" * 20, followed_rules=1)
    body = get(client)
    assert body["unattached_annotations"] == [
        {"trade_id": "t" + "0" * 20, "market": "perp", "updated_at": "2026-09-01T00:00:00+00:00", "has_notes": True},
        {"trade_id": "t" + "1" * 20, "market": "spot", "updated_at": "2026-09-01T00:00:00+00:00", "has_notes": False}]


def test_get_is_read_only(seeded):
    db, client, _ = seeded
    names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    count = lambda: {n: db.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}
    before = count()
    get(client)
    assert count() == before


# ── PUT /api/trading/trades/<id>/annotation ──────────────────────────────

def put(client, tid, body):
    return client.put(f'/api/trading/trades/{tid}/annotation', json=body)


@pytest.mark.parametrize("body,error", [
    ({}, "Nothing to update"),
    ({"other": 1}, "Nothing to update"),
    ({"stop_px": -1}, "stop_px"), ({"stop_px": 0}, "stop_px"), ({"stop_px": "abc"}, "stop_px"),
    ({"stop_px": True}, "stop_px"), ({"stop_px": [1]}, "stop_px"), ({"stop_px": "nan"}, "stop_px"),
    ({"stop_px": "Infinity"}, "stop_px"),
    ({"followed_rules": 1}, "followed_rules"), ({"followed_rules": "true"}, "followed_rules"),
    ({"notes": "x" * 2001}, "notes"), ({"deviation_note": 5}, "deviation_note"),
])
def test_put_validation(seeded, body, error):
    db, client, ids = seeded
    r = put(client, ids["GGG"], body)
    assert r.status_code == 400 and error in r.get_json()["error"]
    assert db.execute("SELECT COUNT(*) FROM trade_annotations WHERE trade_id = ?", (ids["GGG"],)).fetchone()[0] == 0


def test_put_unknown_and_manual(seeded):
    _, client, ids = seeded
    r = put(client, "t" + "f" * 20, {"notes": "x"})
    assert r.status_code == 404 and r.get_json() == {"error": "trade not found"}
    r = put(client, ids["M_PERP"], {"notes": "x"})
    assert r.status_code == 400 and r.get_json() == {"error": "manual trades are edited in the trade log"}


def test_put_stop_lifecycle(seeded):
    db, client, ids = seeded
    tid = ids["GGG"]
    rows = lambda: db.execute("SELECT COUNT(*) FROM trade_annotations").fetchone()[0]
    n0 = rows()
    r = put(client, tid, {"stop_px": "9.50", "notes": "x" * 2000})
    assert r.status_code == 200
    a = r.get_json()["annotation"]
    assert r.get_json()["trade_id"] == tid and a["trade_id"] == tid and a["market"] == "spot"
    assert (a["stop_px"], a["stop_source"]) == ("9.5", "manual") and a["stop_set_at"]
    assert a["created_at"] == a["updated_at"] == a["stop_set_at"] and a["followed_rules"] is None
    assert "scanner_snapshot_json" not in a and "scanner_captured_at" not in a
    assert rows() == n0 + 1
    t = by_id(get(client))[tid]
    assert t["stop"]["px"] == "9.5" and t["attention"] is None              # spot: no stop attention

    old = "2026-09-24T12:00:00+00:00"
    db.execute("UPDATE trade_annotations SET stop_set_at = ? WHERE trade_id = ?", (old, tid))
    db.commit()
    a = put(client, tid, {"stop_px": 9.5, "followed_rules": True}).get_json()["annotation"]
    assert a["stop_set_at"] == old and a["followed_rules"] is True and a["updated_at"] > old   # same value: kept
    a = put(client, tid, {"stop_px": "9.6"}).get_json()["annotation"]
    assert a["stop_px"] == "9.6" and a["stop_set_at"] > old                                 # changed: renewed
    a = put(client, tid, {"stop_px": None, "notes": None, "followed_rules": None}).get_json()["annotation"]
    assert (a["stop_px"], a["stop_set_at"], a["stop_source"], a["notes"]) == (None, None, None, None)
    assert a["created_at"] < a["updated_at"] or a["created_at"] == a["updated_at"]
    assert rows() == n0 + 1                                                 # cleared, never deleted
    assert by_id(get(client))[tid]["attention"] is None                    # spot never needs a stop (R3)


def test_put_on_a_perp_trade(seeded):
    db, client, _ = seeded
    gold = next(c for c in _golden()["cycles"] if c["wallet"] == "rabby")
    pid = wp._trade_id(f"{W_RABBY}|{gold['coin']}|{gold['first_tid']}")
    r = put(client, pid, {"followed_rules": False, "deviation_note": "late entry"})
    assert r.status_code == 200
    a = r.get_json()["annotation"]
    assert a["market"] == "perp" and a["followed_rules"] is False and a["stop_px"] is None
    t = by_id(get(client))[pid]
    assert t["annotation"] == {"followed_rules": False, "deviation_note": "late entry", "notes": None,
                               "exit_reason": None, "exit_reason_note": None}
    assert t["stop"]["source"] == "hl_order"                                # no annotation stop: the order's


# ── manual trade-log market field ────────────────────────────────────────

def test_trade_log_market_field(db, client):
    body = {"ticker": "SOL", "direction": "long", "entry_price": 100, "stop_price": 95, "qty": 1}
    r = client.post('/api/spot/trade-log', json={**body, "market": "fx"})
    assert r.status_code == 400 and r.get_json() == {"error": "market must be spot or perp"}
    r = client.post('/api/spot/trade-log', json={**body, "market": None})
    assert r.status_code == 400
    plain = client.post('/api/spot/trade-log', json=body).get_json()["id"]
    perp = client.post('/api/spot/trade-log', json={**body, "market": "perp"}).get_json()["id"]
    stored = {r["id"]: r["market"] for r in db.execute("SELECT id, market FROM spot_trade_log")}
    assert stored == {plain: None, perp: "perp"}
    listed = {t["id"]: t["market"] for t in client.get('/api/spot/trade-log').get_json()["trades"]}
    assert listed == {plain: "spot", perp: "perp"}
    r = client.put(f'/api/spot/trade-log/{plain}', json={"market": "bad"})
    assert r.status_code == 400 and r.get_json() == {"error": "market must be spot or perp"}
    assert client.put(f'/api/spot/trade-log/{plain}', json={"market": "perp"}).status_code == 200
    assert db.execute("SELECT market FROM spot_trade_log WHERE id = ?", (plain,)).fetchone()[0] == "perp"
    t = by_id(get(client))
    assert t[wp._trade_id(f"manual|{plain}")]["market"] == "perp"


# ── step 5: cache warm-up, manual_id, stop_missing ───────────────────────

def test_the_route_kicks_the_open_perps_caches(seeded):
    _, client, _ = seeded
    get(client)
    assert client.cache_kicks == ["hl_accounts", "txflow"]


def test_a_failing_cache_kick_does_not_break_the_route(seeded, monkeypatch, capsys):
    _, client, _ = seeded

    def boom(now):
        raise RuntimeError("cache down")
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", boom)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", boom)
    capsys.readouterr()
    body = get(client)
    assert body["trades"]
    assert capsys.readouterr().out.count("[trades] cache kick failed") == 2


def test_manual_id_only_on_manual_trades(seeded):
    db, client, ids = seeded
    body = get(client)
    table_ids = {r[0] for r in db.execute("SELECT id FROM spot_trade_log")}
    for t in body["trades"]:
        if t["source"] == "manual":
            assert t["manual_id"] in table_ids and t["trade_id"] == wp._trade_id("manual|%d" % t["manual_id"])
        else:
            assert t["manual_id"] is None
    by = by_id(body)
    assert {by[ids["M_PERP"]]["manual_id"], by[ids["M_OPEN"]]["manual_id"]} == table_ids


def test_stop_missing_is_dropped_once_a_stop_exists(seeded, monkeypatch):
    db, client, _ = seeded
    hl = [t for t in get(client)["trades"] if t["source"] == "hyperliquid"]
    assert hl and all("stop_missing" not in t["flags"] for t in hl)          # every seeded cycle has an order stop

    real = wp._hl_trade_cycles

    def no_stop_on_newest(conn):
        built = real(conn)
        built["cycles"][0]["initial_stop_px"] = None
        built["cycles"][0]["flags"].append("stop_missing")
        return built
    monkeypatch.setattr(wp, "_hl_trade_cycles", no_stop_on_newest)
    first = next(t for t in get(client)["trades"] if t["source"] == "hyperliquid")
    assert first["stop"] is None and "stop_missing" in first["flags"]
    annotate(db, first["trade_id"], market="perp", stop_px="1", stop_set_at="2026-09-14T00:00:00+00:00")
    again = by_id(get(client))[first["trade_id"]]
    assert again["stop"]["source"] == "manual" and "stop_missing" not in again["flags"]


# ── step 6b: perps-only gate, spot weekly exits ──────────────────────────

def test_spot_exit_signals(seeded):
    db, client, ids = seeded
    tx(db, "2026-09-01", "pepe", "buy", 10, 100)                            # open, before the rule
    pepe = spot_id("PEPE", db.execute("SELECT MAX(id) FROM spot_transactions").fetchone()[0])
    weekly(db, "GGG", "BEARISH", "2026-09-21T00:00:00+00:00")             # closes Sep 28, after GGG's Sep 24 open
    weekly(db, "LLL", "BULLISH", "2026-09-14T00:00:00+00:00")
    weekly(db, "kBONK", "BEARISH", "2026-09-07T00:00:00+00:00")           # closes Sep 14, before M_OPEN's Sep 25 open
    weekly(db, "kPEPE", "BEARISH", "2026-09-21T00:00:00+00:00")
    weekly(db, "AAA", "BEARISH", "2026-09-21T00:00:00+00:00")             # a closed trade
    weekly(db, "GGG", "BULLISH", "2026-09-28T00:00:00+00:00", timeframe="1d")   # ignored
    body = get(client)
    t = by_id(body)
    g = t[ids["GGG"]]
    assert g["weekly_trend"] == {"symbol": "GGG", "state": "BEARISH", "flipped_at": "2026-09-28T00:00:00+00:00",
                                 "as_of": "2026-09-30T12:00:00+00:00"}
    assert g["exit_signal"] is True and g["attention"] == "exit_signal"
    assert t[ids["LLL"]]["weekly_trend"]["state"] == "BULLISH" and t[ids["LLL"]]["attention"] is None
    m = t[ids["M_OPEN"]]
    assert m["weekly_trend"]["symbol"] == "kBONK" and m["exit_signal"] is False and m["attention"] is None
    p = t[pepe]
    assert p["before_rule"] is True and p["weekly_trend"]["symbol"] == "kPEPE"
    assert p["exit_signal"] is True and p["attention"] == "exit_signal"
    assert t[ids["AAA"]]["exit_signal"] is False and t[ids["AAA"]]["attention"] is None
    assert t[ids["JJJ"]]["weekly_trend"]["state"] is None
    s = body["summary"]
    assert (s["spot"]["exit_signal_count"], s["perp"]["exit_signal_count"], s["attention_count"]) == (2, 0, 2)
    assert s["spot"]["needs_stop_count"] == 0 and s["spot"]["open_count"] == 2     # PEPE is before the rule


def test_a_spot_stop_changes_nothing_for_the_gate(seeded):
    _, client, ids = seeded
    b = by_id(get(client))[ids["BBB"]]
    assert b["stop"]["source"] == "manual" and b["annotation"]["followed_rules"] is True
    assert b["r_multiple"] == "3.000000"
    assert b["gate"] == {"eligible": False, "reason": "spot"}


@pytest.fixture(autouse=True)
def _gate_counts_every_date(monkeypatch):
    """Landing 15: the gate counts only perp trades opened on or after
    TRADES_GATE_COUNT_FROM. This file's trades are dated before it and test
    the other gate checks, so the count date is set to 1970-01-01 here, which
    is the gate as it was before Landing 15 (before_rule is still the only
    date check). tests/test_gate_count_from.py tests the date itself."""
    monkeypatch.setattr(wp, "TRADES_GATE_COUNT_FROM", "1970-01-01")
