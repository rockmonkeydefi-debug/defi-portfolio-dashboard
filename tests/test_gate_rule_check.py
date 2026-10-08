"""Landing 17 (HANDOFF_advisor_v1.md section 37): the 1% -> 2% risk gate also
needs the rule check (web_portfolio._trades_rule_gate, run by the trades route
and _perp_risk_gate).

Glenn, Oct 7 (A; Q1-Q3 A): a closed perp trade counts only when, beyond the
gate's own checks, the setup and the POI were tagged before it closed, the
rule check has no enforced fail, it had a take-profit, and every enforced
rule could be checked.

Real init_db() on a tmp_path SQLite file with stored Hyperliquid fills and
order records (the trades and the rule check are built from them, as in
production). No network. A fake wallet address built in code; made-up
prices and sizes.

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
from src.engines import perp_rules as pr

W = "0x" + "c" * 40
MIN = 60000
H = 3600000
DAY = 24 * H


def _ms(iso):
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


T0 = _ms("2026-10-06T10:00:00+00:00")
TFS = ("15m", "30m", "1h", "4h", "12h", "1d", "1w")
CLEAN = {"15m": "touch", "30m": "above", "1h": "above", "4h": "above", "12h": "above", "1d": "above", "1w": "above"}


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
                 (W, "2026-09-01T00:00:00+00:00", "2026-10-07T00:00:00+00:00", "2026-10-07T00:00:00+00:00"))
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def client(db, monkeypatch):
    calls = []
    for name in ("_maybe_kick_hl_trades_refresh", "_maybe_kick_txflow_trades_refresh",
                 "_maybe_kick_hl_accounts_refresh", "_maybe_kick_txflow_refresh", "_trade_snapshot_pass",
                 "_trade_exit_pass_safe", "_trade_snapshot_worker", "_hl_candles_range", "_hl_candles_before"):
        monkeypatch.setattr(wp, name, lambda *a, _n=name, **k: calls.append(_n) or False)
    monkeypatch.setattr(wp.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP")))
    monkeypatch.setattr(wp.requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP")))
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


# ── seeding ──────────────────────────────────────────────────────────────

def _fill(tid, t, side, sz, px, start, oid, pnl="0"):
    return {"coin": "ETH", "tid": tid, "time": t, "side": side, "sz": sz, "px": px, "startPosition": start,
            "closedPnl": pnl, "fee": "0", "builderFee": "0", "dir": "x", "oid": oid, "hash": "0x0"}


def _rec(oid, px, placed, kind, status="open", status_ts=None, trigger=True):
    return {"status": status, "statusTimestamp": status_ts if status_ts is not None else placed,
            "order": {"coin": "ETH", "side": "A", "oid": oid, "timestamp": placed, "triggerPx": str(px),
                      "isTrigger": trigger, "reduceOnly": True, "isPositionTpsl": False, "orderType": kind,
                      "children": []}}


def seed(conn, i, open_ms, followed=1, positions=None, take_profit=True, snapshot=True):
    """One closed ETH long opened at open_ms: 2 from 100, a stop at 95 placed a minute after the open (1R $10).
    With take_profit, a take-profit at 110 (2R) placed with it is filled 5 hours later (R +2); without, the
    stop fills (R -1). Followed unless followed is None / 0; a trend snapshot (positions, CLEAN by default)
    unless snapshot is False. Returns (trade open ms, close ms)."""
    close_ms = open_ms + 5 * H
    stop_oid, tp_oid = 1000 + 10 * i, 1001 + 10 * i
    exit_px, exit_oid, pnl = ("110", tp_oid, "20") if take_profit else ("95", stop_oid, "-10")
    fills = [_fill(2 * i + 1, open_ms, "B", "2", "100", "0", 900 + i),
             _fill(2 * i + 2, close_ms, "A", "2", exit_px, "2", exit_oid, pnl=pnl)]
    recs = [_rec(stop_oid, 95, open_ms + MIN, "Stop Market"),
            _rec(stop_oid, 95, open_ms + MIN, "Stop Market",
                 status="canceled" if take_profit else "triggered", status_ts=close_ms)]
    if take_profit:
        recs += [_rec(tp_oid, 110, open_ms + MIN, "Take Profit Market"),
                 _rec(tp_oid, 110, open_ms + MIN, "Take Profit Market", status="filled", status_ts=close_ms)]
    for f in fills:
        conn.execute("INSERT INTO hl_fills (wallet, tid, coin, time_ms, raw_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (W, f["tid"], f["coin"], f["time"], json.dumps(f), "2026-10-07T00:00:00+00:00"))
    for j, r in enumerate(recs):
        conn.execute("INSERT INTO hl_orders (wallet, oid, coin, status, status_ts, order_ts, raw_json, fetched_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (W, r["order"]["oid"], "ETH", r["status"], r["statusTimestamp"] + j, r["order"]["timestamp"],
                      json.dumps(r), "2026-10-07T00:00:00+00:00"))
    conn.commit()
    return open_ms, close_ms


def ids_by_open(conn):
    trades, _ = wp._trades_build(conn)
    return {wp._trades_dt(t["opened_at"]).timestamp() * 1000: t["trade_id"] for t in trades}


def annotate(conn, tid, followed=1, positions=None, snapshot=True):
    snap = None
    if snapshot:
        pos = positions or CLEAN
        snap = json.dumps({"trend": {"v": 1, "reason": None, "timeframes": {tf: {"position": pos[tf]} for tf in TFS}}})
    conn.execute("INSERT INTO trade_annotations (trade_id, market, followed_rules, scanner_snapshot_json, created_at, "
                 "updated_at) VALUES (?, 'perp', ?, ?, 'x', 'x')", (tid, followed, snap))
    conn.commit()


def tag(conn, tid, at_ms, setup="retest", poi=("order_block", "1h"), brk=(None, None)):
    """Append a trade_tags row saved at at_ms (setup None and poi None = a cleared row)."""
    at = _iso(at_ms)
    conn.execute("INSERT INTO trade_tags (trade_id, setup, break_kind, break_timeframe, setup_tagged_at, poi_type, "
                 "poi_timeframe, poi_tagged_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (tid, setup, brk[0], brk[1], at if setup else None, poi[0] if poi else None,
                  poi[1] if poi else None, at if poi else None, at))
    conn.commit()


def trade_ready(conn, i=0, open_ms=T0, tagged=True, **kw):
    """Seed, annotate and (by default) tag one trade a minute after its open. Returns its trade id."""
    take_profit = kw.pop("take_profit", True)
    o, c = seed(conn, i, open_ms, take_profit=take_profit)
    tid = ids_by_open(conn)[o]
    annotate(conn, tid, **kw)
    if tagged:
        tag(conn, tid, o + MIN)
    return tid, o, c


def get(client):
    r = client.get('/api/trading/trades')
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    return body, {t["trade_id"]: t for t in body["trades"]}


# ── counts / does not count ──────────────────────────────────────────────

def test_a_clean_trade_tagged_before_the_close_counts(db, client):
    tid, _, _ = trade_ready(db)
    body, by_id = get(client)
    assert by_id[tid]["gate"] == {"eligible": True, "reason": None, "rules": [], "why": {}}
    assert body["summary"]["gate"]["eligible_count"] == 1
    assert body["summary"]["gate"]["expectancy_r"] == "2.000000"


def test_an_untagged_trade_is_not_tagged(db, client):
    tid, _, _ = trade_ready(db, tagged=False)
    body, by_id = get(client)
    assert by_id[tid]["gate"] == {"eligible": False, "reason": "not_tagged", "rules": ["E2", "E3"], "why": {}}
    assert body["summary"]["gate"]["eligible_count"] == 0


def test_tags_saved_after_the_close_do_not_count(db, client):
    tid, o, c = trade_ready(db, tagged=False)
    tag(db, tid, c + MIN)
    _, by_id = get(client)
    assert by_id[tid]["gate"] == {"eligible": False, "reason": "tagged_after_close", "rules": ["E2", "E3"],
                                  "why": {}}
    # only the POI added after the close
    tid2, o2, c2 = trade_ready(db, i=1, open_ms=T0 + DAY, tagged=False)
    tag(db, tid2, o2 + MIN, poi=None)
    tag(db, tid2, c2 + MIN)
    _, by_id = get(client)
    assert by_id[tid2]["gate"]["reason"] == "tagged_after_close" and by_id[tid2]["gate"]["rules"] == ["E3"]


def test_a_tag_saved_at_the_close_time_counts(db, client):
    tid, o, c = trade_ready(db, tagged=False)
    tag(db, tid, c)
    _, by_id = get(client)
    assert by_id[tid]["gate"]["eligible"] is True


def test_a_retag_after_the_close_cannot_rescue_a_failed_retest(db, client):
    # retest saved before the close with nothing touching: E2 fails; a breakout saved later is ignored
    tid, o, c = trade_ready(db, positions=dict(CLEAN, **{"15m": "above"}))
    tag(db, tid, c + MIN, setup="breakout", brk=("trendline", "4h"))
    _, by_id = get(client)
    assert by_id[tid]["gate"] == {"eligible": False, "reason": "rule_fail", "rules": ["E2"], "why": {}}


def test_clearing_the_tags_after_the_close_does_not_change_the_verdict(db, client):
    tid, o, c = trade_ready(db)
    tag(db, tid, c + MIN, setup=None, poi=None)
    _, by_id = get(client)
    assert by_id[tid]["gate"]["eligible"] is True


def test_enforced_fails_block_with_their_rule_ids(db, client):
    tid, _, _ = trade_ready(db, positions=dict(CLEAN, **{"1d": "below"}))
    body, by_id = get(client)
    assert by_id[tid]["gate"] == {"eligible": False, "reason": "rule_fail", "rules": ["E1"], "why": {}}
    assert body["summary"]["gate"]["eligible_count"] == 0


def test_no_take_profit_is_no_plan(db, client):
    tid, _, _ = trade_ready(db, take_profit=False)
    _, by_id = get(client)
    assert by_id[tid]["gate"] == {"eligible": False, "reason": "no_plan", "rules": ["R3", "M1"], "why": {}}


def test_a_missing_trend_snapshot_is_unchecked(db, client):
    tid, _, _ = trade_ready(db, snapshot=False)
    _, by_id = get(client)
    assert by_id[tid]["gate"] == {"eligible": False, "reason": "unchecked", "rules": ["E1", "E2"],
                                  "why": {"E1": "not_captured", "E2": "not_captured"}}


def test_a_rule_tracking_when_the_trade_opened_does_not_block(db, client):
    db.execute("INSERT INTO perp_rule_status (rule_id, status, reason, effective_from, created_at) "
               "VALUES ('E1', 'tracking', 'test', ?, ?)", (_iso(T0 - DAY), _iso(T0 - DAY)))
    db.commit()
    tid, _, _ = trade_ready(db, positions=dict(CLEAN, **{"1d": "below"}))
    _, by_id = get(client)
    assert by_id[tid]["gate"]["eligible"] is True


def test_the_gates_own_reasons_come_first_and_keep_their_shape(db, client):
    tid, _, _ = trade_ready(db, followed=0, positions=dict(CLEAN, **{"1d": "below"}))
    old, _, _ = trade_ready(db, i=1, open_ms=_ms("2026-10-03T10:00:00+00:00"))
    _, by_id = get(client)
    assert by_id[tid]["gate"] == {"eligible": False, "reason": "deviated"}
    assert by_id[old]["gate"] == {"eligible": False, "reason": "before_gate_count"}


def test_twenty_clean_trades_unlock_and_one_untagged_keeps_it_locked(db, client):
    for i in range(19):
        trade_ready(db, i=i, open_ms=T0 + i * DAY)
    last, _, _ = trade_ready(db, i=19, open_ms=T0 + 19 * DAY, tagged=False)
    gate = get(client)[0]["summary"]["gate"]
    assert gate["eligible_count"] == 19 and gate["unlocked"] is False
    tag(db, last, T0 + 19 * DAY + MIN)
    gate = get(client)[0]["summary"]["gate"]
    assert gate["eligible_count"] == 20 and gate["unlocked"] is True and gate["expectancy_r"] == "2.000000"


# ── agreement with the advisor and the risk-limits save ──────────────────

def test_the_gate_agrees_with_the_advisor_when_the_tags_did_not_change(db, client):
    tid, _, _ = trade_ready(db, positions=dict(CLEAN, **{"1w": "below"}))
    _, by_id = get(client)
    adv = client.get('/api/trading/advisor/perps').get_json()["trades"][tid]
    assert adv["enforced_fails"] == by_id[tid]["gate"]["rules"] == ["E1"]


def test_perp_risk_gate_matches_the_route(db, client):
    for i in range(3):
        trade_ready(db, i=i, open_ms=T0 + i * DAY, tagged=(i != 1))
    route = get(client)[0]["summary"]["gate"]
    assert wp._perp_risk_gate(db) == route and route["eligible_count"] == 2


def test_raising_the_limit_is_refused_when_followed_trades_fail_the_rule_check(db, client):
    # 20 Followed winners since Oct 5, none tagged: they counted before Landing 17; now the gate stays locked
    for i in range(20):
        trade_ready(db, i=i, open_ms=T0 + i * DAY, tagged=False)
    r = client.put('/api/trading/advisor/perps/risk-limits', json={"per_trade_pct": 2, "total_pct": 5,
                                                                    "reason": "test"})
    assert r.status_code == 409 and r.get_json()["gate"]["eligible_count"] == 0


# ── read-only, cost and failure ──────────────────────────────────────────

def test_the_route_stays_read_only(db, client):
    trade_ready(db)
    trade_ready(db, i=1, open_ms=T0 + DAY, tagged=False)
    before = "\n".join(db.iterdump())
    get(client)
    db2 = portfolio_db.get_connection()
    try:
        assert "\n".join(db2.iterdump()) == before
    finally:
        db2.close()


def test_nothing_is_read_without_a_candidate(db, client, monkeypatch):
    trade_ready(db, followed=0)                         # deviated: not a candidate
    for name in ("_advisor_perp_orders", "_trade_tags_for_gate", "_perp_rule_settings"):
        monkeypatch.setattr(wp, name, lambda *a, _n=name, **k: (_ for _ in ()).throw(AssertionError(_n)))
    body, _ = get(client)
    assert body["summary"]["gate"]["eligible_count"] == 0


def test_a_failing_check_fails_closed(db, client, monkeypatch, capsys):
    tid, _, _ = trade_ready(db)
    monkeypatch.setattr(pr, "evaluate_trade", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    body, by_id = get(client)
    assert by_id[tid]["gate"] == {"eligible": False, "reason": "unchecked", "rules": [], "why": {}}
    assert body["summary"]["gate"]["eligible_count"] == 0
    assert "risk gate rule check failed" in capsys.readouterr().out


def test_grouping_orders_by_coin_gives_the_same_rule_results(db):
    # Another coin's records and fills in the same wallet, interleaved: the per-coin history must judge every
    # trade exactly as a scan of every record does (what _advisor_perp_orders did before Landing 17).
    for i, (positions, tp) in enumerate([(CLEAN, True), (dict(CLEAN, **{"1d": "below"}), True), (CLEAN, False)]):
        tid, _, _ = trade_ready(db, i=i, open_ms=T0 + i * DAY, positions=positions, take_profit=tp)
    for k in range(40):
        other = _rec(5000 + k, 1, T0 + k * H, "Stop Market", status="canceled", status_ts=T0 + k * H + MIN)
        other["order"]["coin"] = "XRP"
        db.execute("INSERT INTO hl_orders (wallet, oid, coin, status, status_ts, order_ts, raw_json, fetched_at) "
                   "VALUES (?, ?, 'XRP', 'canceled', ?, ?, ?, 'x')",
                   (W, 5000 + k, T0 + k * H + MIN, T0 + k * H, json.dumps(other)))
        f = dict(_fill(9000 + k, T0 + k * H, "B", "1", "1", "0", 7000 + k), coin="XRP")
        db.execute("INSERT INTO hl_fills (wallet, tid, coin, time_ms, raw_json, fetched_at) "
                   "VALUES (?, ?, 'XRP', ?, ?, 'x')", (W, f["tid"], f["time"], json.dumps(f)))
    db.commit()
    trades, _ = wp._trades_build(db)
    grouped = wp._advisor_perp_orders(db, trades)
    records = [json.loads(r[0]) for r in db.execute("SELECT raw_json FROM hl_orders WHERE wallet = ? ORDER BY id", (W,))]
    fills = [json.loads(r[0]) for r in db.execute(
        "SELECT raw_json FROM hl_fills WHERE wallet = ? ORDER BY time_ms, id", (W,))]
    perps = [t for t in trades if t["market"] == "perp" and t.get("_order_ref")]
    # 3 closed ETH trades and 40 open XRP trades (one buy fill each)
    assert len(perps) == 43 and set(grouped) == {t["trade_id"] for t in perps}
    for t in perps:
        ref = t["_order_ref"]
        full = pr.trade_orders(records, records, fills, ref["coin"], t["direction"], ref["open_ms"], t["_close_ms"])
        assert pr.evaluate_trade(t, grouped[t["trade_id"]], trades, now_ms=T0 + 30 * DAY) \
            == pr.evaluate_trade(t, full, trades, now_ms=T0 + 30 * DAY)
        assert grouped[t["trade_id"]]["closing"] == full["closing"]
        assert (full["closing"] is not None) == (t["symbol"] == "ETH")


def test_tags_for_gate_picks_the_row_in_force_at_the_close(db):
    tid, o, c = trade_ready(db, tagged=False)
    tag(db, tid, o + MIN, poi=None)                     # setup only
    tag(db, tid, o + 2 * MIN)                           # both: in force at the close
    tag(db, tid, c + MIN, setup=None, poi=None)         # cleared later
    trades, _ = wp._trades_build(db)
    rows = wp._trade_tags_for_gate(db, [t for t in trades if t["trade_id"] == tid])
    at_close, now = rows[tid]
    assert at_close["poi_type"] == "order_block" and at_close["setup"] == "retest" and now is None


def test_tags_for_gate_without_the_table(db):
    trade_ready(db, tagged=False)
    db.execute("DROP TABLE trade_tags")
    trades, _ = wp._trades_build(db)
    assert wp._trade_tags_for_gate(db, trades) == {}
