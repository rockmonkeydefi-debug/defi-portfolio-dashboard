"""Landing 23 (HANDOFF_advisor_v1.md section 43): R2 follows the risk gate as
it stood when the trade opened.

- perp_rules.rule_r2: a per-trade limit above 1% applies only when the
  trade's "gate_at_open" says unlocked; locked -> 1% with a note; no record ->
  not measurable ("gate_not_recorded"); at or below 1% the record is never
  read.
- web_portfolio: the background snapshot pass records the gate the first time
  it sees a Hyperliquid / TxFlow perp trade opened within
  TRADE_GATE_RECORD_HOURS (_trade_gate_record_pass), from the trades that
  closed before it opened, never overwritten; the trades carry it as
  "gate_at_open"; _trades_rule_gate reports whether it ran.

Pure dicts for the engine; a real init_db() on a tmp_path SQLite file with
synthetic Hyperliquid fills and order records for the pass and the routes.
Times near the real clock, since the record window is measured from now. No
network: _hl_post and _txflow_post raise. A fake wallet address built in
code; made-up prices.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import copy
import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db
from src.engines import perp_rules as pr

W = "0x" + "c" * 40
MIN = 60000
H = 3600000
DAY = 86400000


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


# ── the engine: rule_r2 ──────────────────────────────────────────────────

T0 = int(datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)
NOW = T0 + 10 * DAY
ABOVE = {"trend": {"v": 1, "reason": None,
                   "timeframes": {tf: {"position": "above"} for tf in ("15m", "30m", "1h", "4h", "12h", "1d", "1w")}}}
LOCKED = {"v": 1, "unlocked": False, "eligible_count": 4, "expectancy_r": "0.300000", "recent_expectancy_r": None,
          "target": 20, "min_avg_r": "0.2", "recent_n": 20, "seen_at": iso(T0 + 5 * MIN)}
UNLOCKED = dict(LOCKED, unlocked=True, eligible_count=22, recent_expectancy_r="0.400000")


def trade(tid="t1", opened=T0, size="150", gate=None, **kw):
    """A closed long: entry 100, stop 95 set 2 min in, so 1R = 5 x size:
    size 150 is 1R 750 (1.5% of 50,000), 90 is 0.9%, 210 is 2.1%."""
    t = {"trade_id": tid, "market": "perp", "source": "hyperliquid", "status": "closed", "direction": "long",
         "symbol": "ETH", "opened_at": iso(opened), "closed_at": iso(opened + DAY), "avg_entry": "100",
         "size_peak": size, "stop": {"px": "95", "source": "hl_order", "set_at": iso(opened + 2 * MIN)},
         "planned_target": None, "leverage": None, "net_pnl": "10",
         "annotation": {"followed_rules": True, "notes": None, "deviation_note": None},
         "open_snapshot": copy.deepcopy(ABOVE), "gate_at_open": copy.deepcopy(gate)}
    t.update(kw)
    return t


def risk(per_trade_bps, total_bps=500, at=T0 - DAY):
    return {"risk": [{"per_trade_bps": per_trade_bps, "total_bps": total_bps, "from": iso(at), "reason": "x",
                      "set_at": iso(at)}]}


def r2(t, settings=None, all_trades=None):
    ev = pr.evaluate_trade(t, None, all_trades or [t], now_ms=NOW, settings=settings)
    return next(r for r in ev["rules"] if r["rule"] == "R2")


def test_at_or_below_one_percent_the_record_is_never_read():
    for settings in (None, risk(100), risk(50, 300)):
        for size in ("90", "150"):
            results = [r2(trade(size=size, gate=g), settings) for g in (None, LOCKED, UNLOCKED, {"unlocked": "yes"})]
            assert all(res == results[0] for res in results), (settings, size)
            assert results[0]["verdict"] != "not_measurable"
            assert not any("risk gate" in n for n in results[0].get("notes") or [])


def test_locked_at_the_open_caps_per_trade_at_one_percent():
    res = r2(trade(size="150", gate=LOCKED), risk(200))
    assert res["verdict"] == "fail" and res["evidence"].startswith("over 1% per trade: 1R $750.00 (1.50% of capital)")
    assert res["notes"] == [f"risk gate locked when this trade opened (recorded {pr._iso(T0 + 5 * MIN)}): 1% per "
                            f"trade applied instead of the stored 2%"]
    small = r2(trade(size="90", gate=LOCKED), risk(200))
    assert small["verdict"] == "pass" and small["notes"] == res["notes"]


def test_locked_with_a_fractional_raise():
    res = r2(trade(size="120", gate=LOCKED), risk(150))              # 1.2%, stored 1.5%
    assert res["verdict"] == "fail" and res["evidence"].startswith("over 1% per trade")
    assert res["notes"][-1].endswith("1% per trade applied instead of the stored 1.5%")


def test_unlocked_at_the_open_uses_the_stored_limit():
    res = r2(trade(size="150", gate=UNLOCKED), risk(200))
    assert res["verdict"] == "pass"
    assert res["notes"] == [f"risk gate unlocked when this trade opened (recorded {pr._iso(T0 + 5 * MIN)}): the "
                            f"stored 2% per trade applied"]
    over = r2(trade(size="210", gate=UNLOCKED), risk(200))
    assert over["verdict"] == "fail" and over["evidence"].startswith("over 2% per trade")


def test_no_record_is_not_measurable_without_amounts():
    for gate in (None, {}, {"unlocked": "yes"}, {"unlocked": None}, "locked"):
        res = r2(trade(size="150", gate=gate), risk(200))                # 1.5%: between 1% and the stored 2%
        assert res["verdict"] == "not_measurable" and res["reason"] == "gate_not_recorded", gate
        assert res["evidence"] == ("risk gate at the open not recorded: 1R is between 1% and the stored 2% per "
                                   "trade, so the verdict depends on it")
        assert "$" not in res["evidence"] and "of capital" not in res["evidence"]


NO_RECORD_NOTE = "risk gate at the open not recorded; this verdict is the same whether it was locked or unlocked"


def test_no_record_still_gives_the_verdicts_that_do_not_depend_on_the_gate():
    within = r2(trade(size="90", gate=None), risk(200))               # 0.9%: passes either way
    assert within["verdict"] == "pass" and within["notes"] == [NO_RECORD_NOTE]
    over = r2(trade(size="210", gate=None), risk(200))                # 2.1%: fails either way
    assert over["verdict"] == "fail" and over["evidence"].startswith("over 2% per trade")
    assert over["notes"] == [NO_RECORD_NOTE]
    at_stored = r2(trade(size="200", gate=None), risk(200))           # exactly 2%: depends on the gate
    assert at_stored["reason"] == "gate_not_recorded"
    s = risk(200, 300)
    trades = [trade(f"t{i}", T0 + i * MIN, size="150", gate=None) for i in range(3)]     # 1.5% each, open together
    assert r2(trades[1], s, trades)["reason"] == "gate_not_recorded"                     # 3.0%: within the total
    total = r2(trades[2], s, trades)                                                     # 4.5%: over it either way
    assert total["verdict"] == "fail" and total["evidence"].startswith("over 3% open in total")
    assert total["notes"] == [NO_RECORD_NOTE]
    small_total = [trade(f"u{i}", T0 + i * MIN, size="90", gate=None) for i in range(4)]  # 0.9% each
    last = r2(small_total[3], s, small_total)                                            # 3.6%
    assert last["verdict"] == "fail" and last["evidence"].startswith("over 3% open in total")


def test_earlier_not_measurable_reasons_come_first():
    no_stop = r2(trade(gate=None, stop=None), risk(200))
    assert no_stop["reason"] == "no_stop"
    tiny = r2(trade(size="0.5", gate=None), risk(200))
    assert tiny["reason"] == "negligible_size"


def test_a_record_without_seen_at_has_no_time_in_the_note():
    res = r2(trade(size="150", gate=dict(LOCKED, seen_at=None)), risk(200))
    assert res["notes"] == ["risk gate locked when this trade opened: 1% per trade applied instead of the stored 2%"]


def test_the_total_limit_is_unchanged_by_the_cap():
    s = risk(200, 300)
    trades = [trade(f"t{i}", T0 + i * MIN, size="90", gate=LOCKED) for i in range(4)]   # 0.9% each, all open together
    assert r2(trades[2], s, trades)["verdict"] == "pass"                                # 2.7% open
    last = r2(trades[3], s, trades)                                                     # 3.6% open
    assert last["verdict"] == "fail" and last["evidence"].startswith("over 3% open in total")


def test_the_gate_check_reads_a_missing_record_as_unchecked():
    tags = {"setup": "other", "setup_tagged_at": iso(T0 + MIN), "poi": {"type": "fvg", "timeframe": "1h"}}
    t = trade(size="150", gate=None, planned_target={"prices": ["111"]})          # a 2.2R take-profit
    ev = pr.evaluate_trade(t, None, None, tags=tags, now_ms=NOW, settings=risk(200))
    reason, rules, why = pr.gate_check(ev, tags)
    assert reason == "unchecked" and "R2" in rules and why["R2"] == "gate_not_recorded"


def test_definition_names_the_gate():
    r2_def = next(r for r in pr.RULES if r["id"] == "R2")["definition"]
    assert "risk gate was unlocked when the trade opened" in r2_def and "$" not in r2_def


# ── web_portfolio: the record at first sight ─────────────────────────────

def test_rule_gate_reports_whether_it_ran(monkeypatch):
    assert wp._trades_rule_gate(None, [{"gate": {"eligible": False}}]) is True       # nothing to check
    cand = {"trade_id": "c", "gate": {"eligible": True, "reason": None}}
    monkeypatch.setattr(wp, "_advisor_perp_orders", lambda conn, trades: (_ for _ in ()).throw(RuntimeError("x")))
    assert wp._trades_rule_gate(None, [cand]) is False
    assert cand["gate"] == {"eligible": False, "reason": "unchecked", "rules": [], "why": {}}


NOW_DT = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def syn(tid, opened, closed=None, r="1.000000", eligible=True, source="hyperliquid", market="perp"):
    return {"trade_id": tid, "market": market, "source": source, "status": "closed" if closed else "open",
            "opened_at": opened.isoformat(), "closed_at": closed.isoformat() if closed else None,
            "r_multiple": r if closed else None, "gate": {"eligible": bool(closed) and eligible, "reason": None}}


@pytest.fixture
def capture(monkeypatch):
    """Runs _trade_gate_record_pass on synthetic trades: the rule check is a
    no-op that succeeds, and writes are captured instead of stored."""
    writes = []
    calls = []
    monkeypatch.setattr(wp, "_trades_rule_gate", lambda conn, trades, now_ms=None: calls.append(now_ms) or True)
    monkeypatch.setattr(wp, "_trade_snapshot_write",
                        lambda conn, t, snap, captured_at, now: writes.append((t["trade_id"], snap, captured_at, now)))
    return writes, calls


def test_record_counts_only_trades_closed_before_the_open(capture):
    writes, calls = capture
    start = NOW_DT - timedelta(days=3)
    done = [syn(f"c{i:02d}", start, start + timedelta(minutes=i + 1)) for i in range(20)]   # 20 closed by +20 min
    late = syn("late", start, NOW_DT - timedelta(minutes=10), r="-30.000000")                # closes after the open
    new = syn("new", NOW_DT - timedelta(hours=1))
    snaps = {"new": {"leverage": {"value": "5"}}}
    assert wp._trade_gate_record_pass(None, done + [late, new], snaps, NOW_DT) == 1
    assert len(calls) == 1
    tid, snap, captured_at, now = writes[0]
    assert tid == "new" and captured_at is None and now == NOW_DT.isoformat()
    assert snap["leverage"] == {"value": "5"}                       # the rest of the snapshot kept
    assert snap["gate"] == {"v": 1, "unlocked": True, "eligible_count": 20, "expectancy_r": "1.000000",
                            "recent_expectancy_r": "1.000000", "target": 20, "min_avg_r": "0.2", "recent_n": 20,
                            "seen_at": NOW_DT.isoformat()}
    assert snaps["new"] is snap


def test_record_before_the_twentieth_close_is_locked(capture):
    writes, _ = capture
    opened, new_open = NOW_DT - timedelta(days=2), NOW_DT - timedelta(hours=1)
    done = [syn(f"c{i:02d}", opened, new_open - timedelta(minutes=19 - i)) for i in range(20)]
    new = syn("new", new_open)                                       # the 20th closes AT the open: not before
    assert wp._trade_gate_record_pass(None, done + [new], {}, NOW_DT) == 1
    gate = writes[0][1]["gate"]
    assert gate["eligible_count"] == 19 and gate["unlocked"] is False and gate["recent_expectancy_r"] is None


def test_which_trades_are_due(capture):
    writes, calls = capture
    trades = [syn("open", NOW_DT - timedelta(hours=2)),
              syn("closed", NOW_DT - timedelta(hours=3), NOW_DT - timedelta(hours=2)),     # a closed trade too
              syn("edge", NOW_DT - timedelta(hours=24)),                                    # exactly 24 h: due
              syn("old", NOW_DT - timedelta(hours=24, minutes=1)),                          # too old
              syn("txf", NOW_DT - timedelta(hours=1), source="txflow"),
              syn("manual", NOW_DT - timedelta(hours=1), source="manual"),
              syn("spot", NOW_DT - timedelta(hours=1), source="spot_tx", market="spot"),
              syn("done", NOW_DT - timedelta(hours=1)),
              dict(syn("nodate", NOW_DT - timedelta(hours=1)), opened_at=None)]
    snaps = {"done": {"gate": {"unlocked": False}}}
    assert wp._trade_gate_record_pass(None, trades, snaps, NOW_DT) == 4
    assert sorted(w[0] for w in writes) == ["closed", "edge", "open", "txf"]
    assert snaps["done"] == {"gate": {"unlocked": False}}           # never overwritten


def test_nothing_due_runs_no_rule_check(capture):
    writes, calls = capture
    trades = [syn("old", NOW_DT - timedelta(days=3)), syn("done", NOW_DT - timedelta(hours=1))]
    assert wp._trade_gate_record_pass(None, trades, {"done": {"gate": {"unlocked": True}}}, NOW_DT) == 0
    assert calls == [] and writes == []


def test_a_failed_rule_check_records_nothing(monkeypatch, capsys):
    writes = []
    monkeypatch.setattr(wp, "_trades_rule_gate", lambda conn, trades, now_ms=None: False)
    monkeypatch.setattr(wp, "_trade_snapshot_write", lambda *a: writes.append(a))
    snaps = {}
    assert wp._trade_gate_record_pass(None, [syn("new", NOW_DT - timedelta(hours=1))], snaps, NOW_DT) is None
    assert writes == [] and snaps == {}
    assert "[trade-gate] rule check failed; nothing more recorded (the next pass retries)" in capsys.readouterr().out


def test_a_later_failed_check_keeps_the_records_already_made(monkeypatch, capsys):
    writes, results = [], iter([True, False])
    monkeypatch.setattr(wp, "_trades_rule_gate", lambda conn, trades, now_ms=None: next(results))
    monkeypatch.setattr(wp, "_trade_snapshot_write", lambda conn, t, snap, captured_at, now: writes.append(t["trade_id"]))
    trades = [syn("first", NOW_DT - timedelta(hours=3)), syn("second", NOW_DT - timedelta(hours=1))]
    assert wp._trade_gate_record_pass(None, trades, {}, NOW_DT) == 1
    out = capsys.readouterr().out
    assert writes == ["first"] and "[trade-gate] recorded+=1" in out and "nothing more recorded" in out


def test_a_malformed_record_is_recorded_again(capture):
    writes, _ = capture
    snaps = {"bad": {"gate": {"unlocked": "yes"}, "leverage": {"value": "3"}}}
    assert wp._trade_gate_record_pass(None, [syn("bad", NOW_DT - timedelta(hours=1))], snaps, NOW_DT) == 1
    assert snaps["bad"]["gate"]["unlocked"] is False and snaps["bad"]["leverage"] == {"value": "3"}


def test_due_trades_in_one_pass_see_each_other(monkeypatch):
    """Review finding (Oct 9): X closed before Y opened and both are due in the
    same pass. X counts only once it has its own record (a stored raise makes
    its R2 need one), so Y's record must be made after X's and include it."""
    writes, calls = [], []

    def rule_gate(conn, trades, now_ms=None):
        calls.append([t["trade_id"] for t in trades if (t.get("gate") or {}).get("eligible")])
        for t in trades:
            g = t.get("gate") or {}
            if g.get("eligible") and t.get("needs_record") and t.get("gate_at_open") is None:
                t["gate"] = {"eligible": False, "reason": "unchecked", "rules": ["R2"], "why": {"R2": "gate_not_recorded"}}
        return True
    monkeypatch.setattr(wp, "_trades_rule_gate", rule_gate)
    monkeypatch.setattr(wp, "_trade_snapshot_write",
                        lambda conn, t, snap, captured_at, now: writes.append((t["trade_id"], snap["gate"])))
    start = NOW_DT - timedelta(days=3)
    earlier = [syn(f"c{i:02d}", start, start + timedelta(minutes=i + 1)) for i in range(20)]   # +1R each, old
    x = dict(syn("x", NOW_DT - timedelta(hours=5), NOW_DT - timedelta(hours=3), r="-30.000000"),
             needs_record=True, gate_at_open=None)
    y = syn("y", NOW_DT - timedelta(hours=1))
    assert wp._trade_gate_record_pass(None, earlier + [y, x], {}, NOW_DT) == 2
    assert [w[0] for w in writes] == ["x", "y"]                      # oldest open first
    assert writes[0][1]["unlocked"] is True and writes[0][1]["eligible_count"] == 20
    assert writes[1][1]["eligible_count"] == 21 and writes[1][1]["unlocked"] is False
    assert writes[1][1]["expectancy_r"] == "-0.476190"
    assert len(calls) == 2 and "x" in calls[1]                       # the second check starts from the build's gates
    assert x["gate_at_open"]["unlocked"] is True


def test_public_record(monkeypatch):
    rec = dict(LOCKED, extra="dropped")
    ann = {"scanner_snapshot_json": json.dumps({"gate": rec, "leverage": {"value": "5"}})}
    t = {"market": "perp", "source": "hyperliquid"}
    out = wp._trade_gate_record_public(t, ann)
    assert out == {k: LOCKED[k] for k in wp._TRADE_GATE_RECORD_KEYS} and "extra" not in out
    assert wp._trade_gate_record_public(dict(t, source="manual"), ann) is None
    assert wp._trade_gate_record_public({"market": "spot", "source": "spot_tx"}, ann) is None
    assert wp._trade_gate_record_public(t, None) is None
    bad = {"scanner_snapshot_json": json.dumps({"gate": {"unlocked": "no"}})}
    assert wp._trade_gate_record_public(t, bad) is None
    assert wp._trade_gate_record_public(t, {"scanner_snapshot_json": "not json"}) is None


# ── the pass and the routes on a real database ───────────────────────────

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
    monkeypatch.setattr(wp, "_hl_refresh_universes", lambda: None)       # the trend step stops there
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "crypto", None)
    conn = portfolio_db.get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO hl_sync_state (wallet, first_seen_at, last_sync_at, last_ok_at) VALUES (?, ?, ?, ?)",
                 (W, "2026-09-20T00:00:00+00:00", now, now))
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


def _fill(coin, tid, t, side, sz, px, start, pnl="0"):
    return {"coin": coin, "tid": tid, "time": t, "side": side, "sz": sz, "px": px, "startPosition": start,
            "closedPnl": pnl, "fee": "0", "builderFee": "0", "dir": "x", "oid": tid, "hash": "0x0"}


def _stop(coin, oid, px, placed):
    return {"status": "open", "statusTimestamp": placed,
            "order": {"coin": coin, "side": "A", "oid": oid, "timestamp": placed, "triggerPx": str(px),
                      "isTrigger": True, "reduceOnly": True, "isPositionTpsl": False, "orderType": "Stop Market",
                      "children": []}}


def open_long(conn, coin, opened_ms, tid, size="150"):
    """An open long of `size` from 100 with a stop at 95 a minute in: 1R = 5 x size."""
    f = _fill(coin, tid, opened_ms, "B", size, "100", "0")
    conn.execute("INSERT INTO hl_fills (wallet, tid, coin, time_ms, raw_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (W, tid, coin, opened_ms, json.dumps(f), datetime.now(timezone.utc).isoformat()))
    r = _stop(coin, 5000 + tid, 95, opened_ms + MIN)
    conn.execute("INSERT INTO hl_orders (wallet, oid, coin, status, status_ts, order_ts, raw_json, fetched_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (W, 5000 + tid, coin, "open", opened_ms + MIN, opened_ms + MIN,
                                                     json.dumps(r), datetime.now(timezone.utc).isoformat()))
    conn.commit()


def stored_gate(conn):
    rows = conn.execute("SELECT trade_id, scanner_snapshot_json FROM trade_annotations").fetchall()
    return {r["trade_id"]: json.loads(r["scanner_snapshot_json"]).get("gate") for r in rows}


def trades_by_coin(client):
    return {t["symbol"]: t for t in client.get("/api/trading/trades").get_json()["trades"]}


def r2_of(client, trade_id):
    body = client.get("/api/trading/advisor/perps").get_json()
    return next(r for r in body["trades"][trade_id]["rules"] if r["rule"] == "R2")


def test_pass_records_a_new_trade_once(db, client, monkeypatch, capsys):
    now_ms = int(time.time() * 1000)
    open_long(db, "ETH", now_ms - H, 1)
    open_long(db, "SOL", now_ms - 30 * H, 2)                        # opened 30 h ago: never recorded
    before = trades_by_coin(client)
    assert before["ETH"]["gate_at_open"] is None and before["SOL"]["gate_at_open"] is None
    stats = wp._trade_snapshot_pass(db, cap=0)
    assert set(stats) == {"leverage", "targets", "trend", "unavailable", "failed", "pending"}
    assert "[trade-gate] recorded+=1" in capsys.readouterr().out
    eth = trades_by_coin(client)["ETH"]
    rec = stored_gate(db)[eth["trade_id"]]
    assert rec["unlocked"] is False and rec["eligible_count"] == 0 and rec["v"] == 1
    assert abs(datetime.fromisoformat(rec["seen_at"]).timestamp() - time.time()) < 120
    assert eth["gate_at_open"] == rec
    assert trades_by_coin(client)["SOL"]["gate_at_open"] is None
    # a second pass changes nothing, even if the gate now reads unlocked, and runs no rule check
    calls = []
    real = wp._trades_rule_gate
    monkeypatch.setattr(wp, "_trades_rule_gate", lambda *a, **k: calls.append(1) or real(*a, **k))
    monkeypatch.setattr(wp, "_trades_gate_view", lambda trades, before=None: dict(rec, unlocked=True))
    wp._trade_snapshot_pass(db, cap=0)
    assert stored_gate(db)[eth["trade_id"]] == rec and calls == []
    assert "[trade-gate]" not in capsys.readouterr().out


def test_a_failing_record_step_never_stops_the_pass(db, monkeypatch, capsys):
    open_long(db, "ETH", int(time.time() * 1000) - H, 1)
    monkeypatch.setattr(wp, "_trade_gate_record_pass", lambda *a: 1 / 0)
    stats = wp._trade_snapshot_pass(db, cap=0)
    assert stats["pending"] == 1                                    # the trend step still ran
    assert "[trade-gate] exception ZeroDivisionError; nothing more recorded this pass" in capsys.readouterr().out


def test_r2_end_to_end_with_a_stored_raise(db, client, monkeypatch):
    now_ms = int(time.time() * 1000)
    db.execute("INSERT INTO perp_risk_limits (per_trade_bps, total_bps, reason, effective_from, created_at) "
               "VALUES (200, 500, 'gate unlocked', ?, ?)", (iso(now_ms - 2 * H), iso(now_ms - 2 * H)))
    db.commit()
    open_long(db, "ETH", now_ms - H, 1, size="150")                  # 1R 750 = 1.5%
    tid = trades_by_coin(client)["ETH"]["trade_id"]
    pending = r2_of(client, tid)
    assert pending["verdict"] == "not_measurable" and pending["reason"] == "gate_not_recorded"
    wp._trade_snapshot_pass(db, cap=0)                              # records the gate: locked (nothing counts)
    locked = r2_of(client, tid)
    assert locked["verdict"] == "fail" and locked["evidence"].startswith("over 1% per trade")
    assert locked["notes"][-1].startswith("risk gate locked when this trade opened (recorded ")
    # the same trade recorded unlocked instead
    snap = json.loads(db.execute("SELECT scanner_snapshot_json FROM trade_annotations WHERE trade_id = ?",
                                 (tid,)).fetchone()[0])
    snap["gate"]["unlocked"] = True
    db.execute("UPDATE trade_annotations SET scanner_snapshot_json = ? WHERE trade_id = ?", (json.dumps(snap), tid))
    db.commit()
    unlocked = r2_of(client, tid)
    assert unlocked["verdict"] == "pass" and unlocked["notes"][-1].endswith("the stored 2% per trade applied")
