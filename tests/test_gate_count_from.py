"""Landing 15 (Oct 7): the 1% -> 2% risk gate counts only perp trades opened on
or after TRADES_GATE_COUNT_FROM (UTC day, 2026-10-05). TRADES_GATE_START
(2026-09-13) still marks the rules era: before_rule, the History defaults, the
panels' "since" counts and attention are unchanged.

Real init_db() on a tmp_path SQLite file; Hyperliquid cycles are synthetic
(hl_trades.build_cycles on made-up fills, as test_trades_unified's
test_gate_unlock does) and _hl_trade_cycles is monkeypatched to return them.
No network. Fake addresses only, built in code.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import threading
from datetime import datetime, timezone

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import hl_trades
import src.storage.portfolio_db as portfolio_db

W_RM = "0x" + "a" * 40
H = 3600000
DAY = 24 * H


def _ms(iso):
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


COUNT_FROM_MS = _ms("2026-10-05T00:00:00+00:00")


def _never(*a, **k):
    raise AssertionError("no venue call here")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.setattr(wp, "_HL_TRADES_IN_FLIGHT", False)
    monkeypatch.setattr(wp, "_HL_TRADES_LAST_KICK", {"at": None})
    monkeypatch.setattr(wp, "HL_TRADES_START_MS", _ms("2026-09-01T00:00:00+00:00"))
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
    monkeypatch.setattr(wp, "_maybe_kick_hl_trades_refresh", lambda now, force=False: False)
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", lambda now: False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", lambda now: False)
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _cycles(opens, win=True):
    """One closed ETH long per open time (epoch ms): entry 100, stop 95 (a
    stop order placed at the open), exit 110 (R +2) or 90 (R -2) an hour later."""
    fills, orders = [], []
    for i, t0 in enumerate(opens):
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


def _follow(conn, built, followed=1):
    for c in built["cycles"]:
        conn.execute("INSERT INTO trade_annotations (trade_id, market, followed_rules, created_at, updated_at) "
                     "VALUES (?, 'perp', ?, '2026-10-07T00:00:00+00:00', '2026-10-07T00:00:00+00:00')",
                     (wp._trade_id(c["trade_key"]), followed))
    conn.commit()


def _get(client):
    r = client.get('/api/trading/trades')
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _live(opened_at, **over):
    """A closed, Followed, trading-book perp trade dict that passes every gate check."""
    t = {"status": "closed", "market": "perp", "before_rule": False, "book": "trading", "source": "manual",
         "opened_at": opened_at, "annotation": {"followed_rules": True},
         "stop": {"px": "95", "source": "manual", "set_at": opened_at}, "r_multiple": "2.000000"}
    t.update(over)
    return t


# ── the constants ────────────────────────────────────────────────────────

def test_constants():
    assert wp.TRADES_GATE_COUNT_FROM == "2026-10-05"
    assert wp.TRADES_GATE_START == "2026-09-13"            # the rules era is unchanged
    assert wp.TRADES_GATE_TARGET == 20


# ── the check itself (_trades_gate_reason) ─────────────────────────────────

@pytest.mark.parametrize("opened_at,reason", [
    ("2026-10-04T23:59:59+00:00", "before_gate_count"),
    ("2026-10-05T00:00:00+00:00", None),
    ("2026-10-05", None),                                   # a bare date reads as midnight UTC
    ("2026-10-05T00:00:00", None),                          # a naive time reads as UTC
    ("2026-10-04T18:00:00-07:00", None),                    # Oct 5 01:00 UTC: the UTC day decides
    ("2026-10-05T01:00:00+05:00", "before_gate_count"),     # Oct 4 20:00 UTC
    ("2026-09-20T10:00:00+00:00", "before_gate_count"),     # in the rules era, before the gate count
    ("2026-11-02T08:00:00+00:00", None),
    (None, "before_gate_count"),                            # an unreadable date never counts
    ("not a date", "before_gate_count"),
])
def test_reason_by_open_day(opened_at, reason):
    assert wp._trades_gate_reason(_live(opened_at)) == reason


def test_check_order():
    old = "2026-09-20T10:00:00+00:00"
    # before_rule and the earlier checks still come first
    assert wp._trades_gate_reason(_live(old, before_rule=True)) == "before_rule"
    assert wp._trades_gate_reason(_live(old, status="open")) == "open"
    assert wp._trades_gate_reason(_live(old, market="spot")) == "spot"
    # a trade before the count date reads before_gate_count whatever else is wrong with it
    assert wp._trades_gate_reason(_live(old, annotation={"followed_rules": False})) == "before_gate_count"
    assert wp._trades_gate_reason(_live(old, book="long_term")) == "before_gate_count"
    # from the count date on, every later check is unchanged
    new = "2026-10-06T10:00:00+00:00"
    assert wp._trades_gate_reason(_live(new, book="long_term")) == "not_trading_book"
    assert wp._trades_gate_reason(_live(new, annotation={"followed_rules": None})) == "needs_review"
    assert wp._trades_gate_reason(_live(new, annotation={"followed_rules": False})) == "deviated"
    assert wp._trades_gate_reason(_live(new, stop=None)) == "no_stop"
    assert wp._trades_gate_reason(_live(new, r_multiple=None)) == "no_r"


# ── through the route ───────────────────────────────────────────────────

def test_route_counts_only_trades_from_the_count_date(db, client, monkeypatch):
    # Oct 2 00:00, Oct 4 22:00 (closes 23:00), Oct 5 00:00, Oct 6 00:00 UTC: one ETH long at a time
    opens = [COUNT_FROM_MS - 3 * DAY, COUNT_FROM_MS - 2 * H, COUNT_FROM_MS, COUNT_FROM_MS + DAY]
    built = _cycles(opens)
    monkeypatch.setattr(wp, "_hl_trade_cycles", lambda conn: built)
    _follow(db, built)
    body = _get(client)
    gate = body["summary"]["gate"]
    assert gate["start"] == "2026-09-13" and gate["count_from"] == "2026-10-05" and gate["target"] == 20
    assert gate["eligible_count"] == 2 and gate["expectancy_r"] == "2.000000" and gate["unlocked"] is False
    assert gate["by_market"] == {"perp": {"eligible_count": 2, "expectancy_r": "2.000000"}}
    by_open = sorted(body["trades"], key=lambda t: t["opened_at"])
    assert [t["gate"]["reason"] for t in by_open] == ["before_gate_count", "before_gate_count", None, None]
    assert [t["gate"]["eligible"] for t in by_open] == [False, False, True, True]
    # the rules era is unchanged: none is before_rule, so History shows all four by default,
    # and the Perps panel's "Closed since Sep 13" counts all four
    assert all(t["before_rule"] is False for t in by_open)
    assert body["summary"]["perp"]["closed_count"] == 4


def test_route_unlocks_on_20_trades_from_the_count_date(db, client, monkeypatch):
    built = _cycles([COUNT_FROM_MS + i * DAY for i in range(20)])
    monkeypatch.setattr(wp, "_hl_trade_cycles", lambda conn: built)
    _follow(db, built)
    gate = _get(client)["summary"]["gate"]
    assert gate["eligible_count"] == 20 and gate["expectancy_r"] == "2.000000" and gate["unlocked"] is True


def test_route_ignores_winners_before_the_count_date(db, client, monkeypatch):
    # 20 Followed winners in the rules era (Sep 13 - Oct 4) unlocked the gate before Landing 15; now they don't count
    built = _cycles([COUNT_FROM_MS - (i + 1) * DAY for i in range(20)])
    monkeypatch.setattr(wp, "_hl_trade_cycles", lambda conn: built)
    _follow(db, built)
    gate = _get(client)["summary"]["gate"]
    assert gate["eligible_count"] == 0 and gate["expectancy_r"] is None and gate["unlocked"] is False


def test_attention_is_unchanged_before_the_count_date(db, client, monkeypatch):
    # an unreviewed closed perp opened Sep 20 (rules era, before the count date) still needs a review
    built = _cycles([_ms("2026-09-20T00:00:00+00:00")])
    monkeypatch.setattr(wp, "_hl_trade_cycles", lambda conn: built)
    body = _get(client)
    (t,) = body["trades"]
    assert t["before_rule"] is False and t["attention"] == "needs_review"
    assert t["gate"] == {"eligible": False, "reason": "before_gate_count"}
    assert body["summary"]["perp"]["needs_review_count"] == 1
