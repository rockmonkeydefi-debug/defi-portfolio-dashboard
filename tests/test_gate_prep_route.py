"""Landing 22 (HANDOFF_advisor_v1.md section 42): GET /api/trading/trades
carries "gate_prep" on every trade - {"missing": [...]} on an open perp
trade that can still count toward the risk gate, None on every other trade
(web_portfolio._trades_gate_prep, perp_rules.gate_prep).

A nudge, not a gate: nothing here may change a gate verdict, and when it
fails it flags nothing.

Real init_db() on a tmp_path SQLite file. Hyperliquid trades come from
synthetic fills and order records written straight into hl_fills /
hl_orders; the accounts cache is set in memory. No network: _hl_post and
_txflow_post raise. A fake wallet address built in code; made-up prices.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import json
import threading
from datetime import datetime, timezone

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db

W = "0x" + "d" * 40
MIN = 60000
H = 3600000
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def _ms(iso):
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


T_OPEN = _ms("2026-10-08T10:00:00+00:00")       # after the gate's count date (Oct 5)
T_EARLY = _ms("2026-10-03T10:00:00+00:00")      # after the rule start, before the count date


def _never(*a, **k):
    raise AssertionError("no venue call here")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {W: {"label": "HL main"}})
    monkeypatch.setattr(wp, "_hl_post", _never)
    monkeypatch.setattr(wp, "_txflow_post", _never)
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": None, "wallets": {}})
    conn = portfolio_db.get_connection()
    conn.execute("INSERT INTO hl_sync_state (wallet, first_seen_at, last_sync_at, last_ok_at) VALUES (?, ?, ?, ?)",
                 (W, "2026-09-20T00:00:00+00:00", "2026-10-09T11:50:00+00:00", "2026-10-09T11:50:00+00:00"))
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def client(db, monkeypatch):
    for name in ("_maybe_kick_hl_trades_refresh", "_maybe_kick_txflow_trades_refresh",
                 "_maybe_kick_hl_accounts_refresh", "_maybe_kick_txflow_refresh"):
        monkeypatch.setattr(wp, name, lambda *a, **k: False)
    monkeypatch.setattr(wp.requests, "get", _never)
    monkeypatch.setattr(wp.requests, "post", _never)
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


# ── seeding ──────────────────────────────────────────────────────────────

def _fill(coin, tid, t, side, sz, px, start, pnl="0", oid=None):
    return {"coin": coin, "tid": tid, "time": t, "side": side, "sz": sz, "px": px, "startPosition": start,
            "closedPnl": pnl, "fee": "0", "builderFee": "0", "dir": "x", "oid": oid or tid, "hash": "0x0"}


def _rec(coin, oid, px, placed, kind, status="open"):
    return {"status": status, "statusTimestamp": placed,
            "order": {"coin": coin, "side": "A", "oid": oid, "timestamp": placed, "triggerPx": str(px),
                      "isTrigger": True, "reduceOnly": True, "isPositionTpsl": False, "orderType": kind,
                      "children": []}}


def add_fills(conn, fills):
    for f in fills:
        conn.execute("INSERT INTO hl_fills (wallet, tid, coin, time_ms, raw_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (W, f["tid"], f["coin"], f["time"], json.dumps(f), "2026-10-09T11:50:00+00:00"))
    conn.commit()


def add_orders(conn, recs):
    for j, r in enumerate(recs):
        conn.execute("INSERT INTO hl_orders (wallet, oid, coin, status, status_ts, order_ts, raw_json, fetched_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (W, r["order"]["oid"], r["order"]["coin"], r["status"], r["statusTimestamp"] + j,
                      r["order"]["timestamp"], json.dumps(r), "2026-10-09T11:50:00+00:00"))
    conn.commit()


def open_long(conn, coin="ETH", at=T_OPEN, tid=1, stop=True, take_profit=False):
    """An open long of 2 from 100; a stop at 95 a minute after the open; with
    take_profit, a stored take-profit order at 110 placed with it."""
    add_fills(conn, [_fill(coin, tid, at, "B", "2", "100", "0")])
    recs = []
    if stop:
        recs.append(_rec(coin, 5000 + tid, 95, at + MIN, "Stop Market"))
    if take_profit:
        recs.append(_rec(coin, 6000 + tid, 110, at + MIN, "Take Profit Market"))
    add_orders(conn, recs)


def closed_long(conn, coin="SOL", at=T_OPEN, tid=20):
    add_fills(conn, [_fill(coin, tid, at, "B", "2", "100", "0"),
                     _fill(coin, tid + 1, at + 5 * H, "A", "2", "95", "2", pnl="-10")])
    add_orders(conn, [_rec(coin, 5000 + tid, 95, at + MIN, "Stop Market", status="triggered")])


def pos(coin="ETH"):
    return {"coin": coin, "szi": "2", "entry_px": "100", "unrealized_pnl": "20", "cum_funding_since_open": "0",
            "position_value": "220", "liquidation_px": "60", "margin_used": "44", "return_on_equity": "0.4",
            "leverage": 5, "leverage_type": "cross"}


def order(coin="ETH", trigger="95", kind="Stop Market"):
    return {"coin": coin, "side": "A", "triggerPx": trigger, "orderType": kind, "sz": "2", "isTrigger": True,
            "reduceOnly": True, "isPositionTpsl": False, "limitPx": trigger, "oid": 1, "timestamp": 1}


def hl_cache(monkeypatch, positions, open_orders):
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {
        "fetched_at": NOW.isoformat(), "wallets": {W: {"positions": positions, "open_orders": open_orders}}})


def body(client):
    r = client.get('/api/trading/trades')
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def perp(b, coin):
    return next(t for t in b["trades"] if t["market"] == "perp" and t["symbol"] == coin)


def put_tags(client, trade_id, payload):
    r = client.put(f'/api/trading/trades/{trade_id}/tags', json=payload)
    assert r.status_code == 200, r.get_data(as_text=True)


def status_row(conn, rule, status, frm):
    conn.execute("INSERT INTO perp_rule_status (rule_id, status, reason, effective_from, created_at) "
                 "VALUES (?, ?, ?, ?, ?)", (rule, status, "test", frm, frm))
    conn.commit()


# ── the field on the route ───────────────────────────────────────────────

def test_open_untagged_trade_without_a_live_read(db, client):
    open_long(db)
    t = perp(body(client), "ETH")
    assert t["status"] == "open" and t["live"] is None
    assert t["gate_prep"] == {"missing": ["setup", "poi"]}           # take-profit unknown, so not flagged


def test_live_read_with_no_take_profit_flags_it(db, client, monkeypatch):
    open_long(db)
    hl_cache(monkeypatch, [pos()], [order()])                        # a stop, no take-profit
    t = perp(body(client), "ETH")
    assert t["live"]["take_profits"] == []
    assert t["gate_prep"] == {"missing": ["setup", "poi", "take_profit"]}


def test_live_take_profit_counts(db, client, monkeypatch):
    open_long(db)
    hl_cache(monkeypatch, [pos()], [order(), order(trigger="110", kind="Take Profit Market")])
    assert perp(body(client), "ETH")["gate_prep"] == {"missing": ["setup", "poi"]}


def test_failed_take_profit_read_is_not_missing(db, client, monkeypatch):
    open_long(db)
    hl_cache(monkeypatch, [pos()], None)                             # the venue's open-orders read failed
    t = perp(body(client), "ETH")
    assert t["live"]["take_profits"] is None
    assert t["gate_prep"] == {"missing": ["setup", "poi"]}


def test_stale_live_read_is_not_missing(db, client, monkeypatch):
    open_long(db)
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {
        "fetched_at": NOW.isoformat(),
        "wallets": {W: {"positions": [pos()], "open_orders": [order()], "stale": True}}})
    t = perp(body(client), "ETH")
    assert t["live"]["take_profits"] == [] and t["live"]["stale"] is True
    assert t["gate_prep"] == {"missing": ["setup", "poi"]}


def test_stored_take_profit_order_counts(db, client, monkeypatch):
    open_long(db, take_profit=True)
    hl_cache(monkeypatch, [pos()], [order()])                        # the live read shows none
    t = perp(body(client), "ETH")
    assert (t["planned_target"] or {}).get("prices")
    assert t["gate_prep"] == {"missing": ["setup", "poi"]}


def test_tag_saves_clear_the_parts(db, client, monkeypatch):
    open_long(db)
    hl_cache(monkeypatch, [pos()], [order(), order(trigger="110", kind="Take Profit Market")])
    tid = perp(body(client), "ETH")["trade_id"]
    put_tags(client, tid, {"setup": "retest"})
    assert perp(body(client), "ETH")["gate_prep"] == {"missing": ["poi"]}
    put_tags(client, tid, {"poi": {"type": "fvg", "timeframe": "1h"}})
    assert perp(body(client), "ETH")["gate_prep"] == {"missing": []}
    put_tags(client, tid, {"setup": None, "poi": None})               # cleared: a cleared row is no tags
    assert perp(body(client), "ETH")["gate_prep"] == {"missing": ["setup", "poi"]}


def test_breakout_without_what_broke_cannot_be_saved_and_stays_flagged(db, client):
    open_long(db)
    tid = perp(body(client), "ETH")["trade_id"]
    assert client.put(f'/api/trading/trades/{tid}/tags', json={"setup": "breakout"}).status_code == 400
    assert perp(body(client), "ETH")["gate_prep"] == {"missing": ["setup", "poi"]}
    put_tags(client, tid, {"setup": "breakout", "break_what": {"kind": "trendline", "timeframe": "4h"}})
    assert perp(body(client), "ETH")["gate_prep"] == {"missing": ["poi"]}


def test_rule_tracking_at_the_open_drops_its_part(db, client):
    open_long(db)
    status_row(db, "E3", "tracking", "2026-10-07T00:00:00+00:00")     # before the open
    status_row(db, "E2", "tracking", "2026-10-09T00:00:00+00:00")     # after the open: forward only
    assert perp(body(client), "ETH")["gate_prep"] == {"missing": ["setup"]}


def test_trades_that_cannot_count_carry_none(db, client, monkeypatch):
    open_long(db, coin="BTC", at=T_EARLY, tid=40)                     # opened before the count date
    closed_long(db)                                                  # closed
    open_long(db, coin="ETH")
    hl_cache(monkeypatch, [pos("BTC"), pos("ETH")], [])
    b = body(client)
    assert perp(b, "BTC")["status"] == "open" and perp(b, "BTC")["gate_prep"] is None
    assert perp(b, "SOL")["status"] == "closed" and perp(b, "SOL")["gate_prep"] is None
    assert perp(b, "ETH")["gate_prep"] == {"missing": ["setup", "poi", "take_profit"]}
    assert all("gate_prep" in t for t in b["trades"])


def test_reduced_trade_is_still_flagged(db, client):
    """A perp trade reduced but not closed stays open (partly_closed is a
    spot status) and is still flagged."""
    add_fills(db, [_fill("ETH", 1, T_OPEN, "B", "2", "100", "0"),
                   _fill("ETH", 2, T_OPEN + H, "A", "1", "105", "2", pnl="5")])
    add_orders(db, [_rec("ETH", 5001, 95, T_OPEN + MIN, "Stop Market")])
    t = perp(body(client), "ETH")
    assert t["status"] == "open"
    assert t["gate_prep"] == {"missing": ["setup", "poi"]}


# ── reads, failure and the gate left alone ───────────────────────────────

def test_no_candidate_reads_nothing(db, client, monkeypatch):
    closed_long(db)
    monkeypatch.setattr(wp, "_perp_rule_settings", lambda conn: (_ for _ in ()).throw(AssertionError("read")))
    calls = []
    real = wp._trade_tags_latest
    monkeypatch.setattr(wp, "_trade_tags_latest", lambda conn, trade_id=None: calls.append(1) or real(conn, trade_id))
    b = body(client)
    assert perp(b, "SOL")["gate_prep"] is None and calls == []


def test_one_read_each_with_candidates(db, client, monkeypatch):
    open_long(db, coin="ETH", tid=1)
    open_long(db, coin="BTC", tid=2)
    counts = {"tags": 0, "settings": 0}
    real_tags, real_settings = wp._trade_tags_latest, wp._perp_rule_settings

    def tags(conn, trade_id=None):
        counts["tags"] += 1
        return real_tags(conn, trade_id)

    def settings(conn):
        counts["settings"] += 1
        return real_settings(conn)

    monkeypatch.setattr(wp, "_trade_tags_latest", tags)
    monkeypatch.setattr(wp, "_perp_rule_settings", settings)
    b = body(client)
    assert perp(b, "ETH")["gate_prep"] and perp(b, "BTC")["gate_prep"]
    assert counts == {"tags": 1, "settings": 1}          # no closed candidate, so the gate's rule check reads none


def test_failure_flags_nothing_and_logs(db, client, monkeypatch, capsys):
    open_long(db)
    monkeypatch.setattr(wp, "_perp_rule_settings", lambda conn: (_ for _ in ()).throw(RuntimeError("boom")))
    b = body(client)
    assert all(t["gate_prep"] is None for t in b["trades"])
    assert "[trades] gate prep failed; no trade flagged" in capsys.readouterr().out


def test_everything_else_in_the_response_is_unchanged(db, client, monkeypatch):
    """With the step turned off the response differs only by gate_prep."""
    open_long(db, coin="ETH", tid=1)
    open_long(db, coin="BTC", at=T_EARLY, tid=40)
    closed_long(db)
    hl_cache(monkeypatch, [pos("ETH"), pos("BTC")], [order()])
    with_step = body(client)
    monkeypatch.setattr(wp, "_trades_gate_prep", lambda conn, trades, now_ms=None: None)
    without = body(client)
    strip = lambda b: dict(b, trades=[{k: v for k, v in t.items() if k != "gate_prep"} for t in b["trades"]])
    assert strip(with_step) == without
    assert all("gate_prep" not in t for t in without["trades"])


# ── the candidate rule and the date helper ───────────────────────────────

def _t(**kw):
    base = {"market": "perp", "status": "open", "book": "trading", "source": "hyperliquid", "before_rule": False,
            "opened_at": "2026-10-08T10:00:00+00:00"}
    base.update(kw)
    return base


def test_candidate_rule():
    assert wp._trades_gate_prep_candidate(_t())
    assert wp._trades_gate_prep_candidate(_t(source="txflow"))
    assert wp._trades_gate_prep_candidate(_t(status="partly_closed"))
    assert not wp._trades_gate_prep_candidate(_t(status="closed"))
    assert not wp._trades_gate_prep_candidate(_t(market="spot"))
    assert not wp._trades_gate_prep_candidate(_t(source="manual"))
    assert not wp._trades_gate_prep_candidate(_t(book="holding"))
    assert not wp._trades_gate_prep_candidate(_t(before_rule=True))
    assert not wp._trades_gate_prep_candidate(_t(opened_at="2026-10-04T23:59:59+00:00"))
    assert not wp._trades_gate_prep_candidate(_t(opened_at=None))


def test_date_helper_agrees_with_the_gate():
    """_trades_counts_from_day says True exactly when _trades_gate_reason gets
    past its count-date check (UTC day, offsets, bare dates, naive times,
    unreadable dates)."""
    samples = ["2026-10-05T00:00:00+00:00", "2026-10-04T23:59:59+00:00", "2026-10-04T20:00:00-07:00",
               "2026-10-04T16:59:59-07:00", "2026-10-05T03:00:00+05:00", "2026-10-05T06:00:00+05:00",
               "2026-10-05", "2026-10-04", "2026-10-05T00:00:00", "2026-10-04T23:00:00", "2026-11-01T00:00:00Z",
               "not a date", "", None]
    for s in samples:
        t = {"status": "closed", "market": "perp", "before_rule": False, "opened_at": s, "book": "trading",
             "annotation": {"followed_rules": None}, "stop": None, "source": "hyperliquid", "r_multiple": None}
        past = wp._trades_gate_reason(t) != "before_gate_count"
        assert wp._trades_counts_from_day(t) is past, s
