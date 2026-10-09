"""Landing 23 (HANDOFF_advisor_v1.md section 43): the 1% -> 2% risk gate is
unlocked while TRADES_GATE_TARGET+ trades count, their average R is above
TRADES_GATE_MIN_AVG_R and the last TRADES_GATE_RECENT of them by close time
average above 0R (web_portfolio._trades_gate_view, summary.gate, and the
risk-limits save's 409 text).

Hand-built trade dicts in the trades route's shape for the gate view; a real
init_db() on a tmp_path SQLite file for the save route. No network.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import random
import threading
from datetime import datetime, timedelta, timezone

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db

T0 = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def tr(i, r, closed=None, eligible=True, tid=None, **kw):
    """A counted (eligible) closed perp trade closing i hours after T0 with R r."""
    closed = T0 + timedelta(hours=i) if closed is None else closed
    t = {"trade_id": tid or f"t{i:03d}", "market": "perp", "book": "trading", "status": "closed",
         "before_rule": False, "opened_at": (T0 - timedelta(days=1)).isoformat(),
         "closed_at": closed.isoformat() if isinstance(closed, datetime) else closed,
         "r_multiple": f"{r:.6f}" if isinstance(r, (int, float)) else r, "net_pnl": "1", "attention": None,
         "annotation": {"followed_rules": True}, "gate": {"eligible": eligible, "reason": None if eligible else "x"}}
    t.update(kw)
    return t


def view(trades, before=None):
    return wp._trades_gate_view(trades, before=before)


# ── constants and shape ──────────────────────────────────────────────────

def test_constants():
    assert (wp.TRADES_GATE_TARGET, wp.TRADES_GATE_MIN_AVG_R, wp.TRADES_GATE_RECENT) == (20, "0.2", 20)


def test_empty():
    assert view([]) == {"target": 20, "eligible_count": 0, "expectancy_r": None, "min_avg_r": "0.2", "recent_n": 20,
                        "recent_expectancy_r": None, "checks": {"count": False, "average": False, "recent": False},
                        "unlocked": False}


def test_fewer_than_twenty_never_unlock():
    v = view([tr(i, 3) for i in range(19)])
    assert v["eligible_count"] == 19 and v["expectancy_r"] == "3.000000" and v["recent_expectancy_r"] is None
    assert v["checks"] == {"count": False, "average": True, "recent": False} and v["unlocked"] is False


def test_twenty_strong_trades_unlock():
    v = view([tr(i, 2) for i in range(20)])
    assert v["checks"] == {"count": True, "average": True, "recent": True} and v["unlocked"] is True
    assert v["expectancy_r"] == v["recent_expectancy_r"] == "2.000000"      # at 20 the two windows are the same


# ── the +0.2R bar (strictly above) ──────────────────────────────────────────

def test_average_must_be_above_the_bar():
    at_bar = [tr(i, 0.2) for i in range(20)]
    v = view(at_bar)
    assert v["expectancy_r"] == "0.200000" and v["checks"]["average"] is False and v["unlocked"] is False
    above = [tr(i, 0.21) for i in range(20)]
    assert view(above)["unlocked"] is True


def test_a_positive_average_under_the_bar_stays_locked():
    v = view([tr(i, 1.0 if i % 2 else -0.7) for i in range(20)])         # average +0.15R
    assert v["expectancy_r"] == "0.150000"
    assert v["checks"] == {"count": True, "average": False, "recent": True} and v["unlocked"] is False


# ── the last 20 ──────────────────────────────────────────────────────────

def test_a_bad_recent_run_locks_it_again():
    trades = [tr(i, 5) for i in range(5)] + [tr(i, -0.1) for i in range(5, 25)]
    v = view(trades)
    assert v["expectancy_r"] == "0.920000" and v["recent_expectancy_r"] == "-0.100000"
    assert v["checks"] == {"count": True, "average": True, "recent": False} and v["unlocked"] is False


def test_last_twenty_is_by_close_time_not_list_order_or_id():
    trades = [tr(i, 5, tid=f"z{99 - i}") for i in range(5)] + [tr(i, -0.1, tid=f"a{i}") for i in range(5, 25)]
    random.Random(4).shuffle(trades)
    assert view(trades)["recent_expectancy_r"] == "-0.100000"
    # the same trades, the winners closing last: the last 20 are 5 winners and 15 small losers
    late = [tr(i + 100, 5, tid=f"w{i}") for i in range(5)] + [tr(i, -0.1, tid=f"l{i}") for i in range(20)]
    random.Random(5).shuffle(late)
    v = view(late)
    assert v["recent_expectancy_r"] == "1.175000" and v["unlocked"] is True        # (25 - 1.5) / 20


def test_equal_close_times_order_by_trade_id():
    same = T0 - timedelta(days=1)
    trades = [tr(0, 10, closed=same, tid="a"), tr(0, -10, closed=same, tid="b")] + [tr(i, 0.5) for i in range(1, 20)]
    v = view(trades)                 # 21 trades: "a" (the lower id) is the oldest and leaves the window
    assert v["eligible_count"] == 21 and v["recent_expectancy_r"] == "-0.025000" and v["unlocked"] is False


def test_an_unreadable_close_time_sorts_oldest():
    trades = [tr(0, 30, closed="not a date", tid="x")] + [tr(i, -0.1) for i in range(1, 21)]
    v = view(trades)
    assert v["eligible_count"] == 21 and v["recent_expectancy_r"] == "-0.100000"


def test_only_eligible_trades_count():
    trades = [tr(i, 1) for i in range(20)] + [tr(i, -50, eligible=False) for i in range(20, 30)]
    v = view(trades)
    assert v["eligible_count"] == 20 and v["unlocked"] is True


# ── the gate as it stood at a time (before=) ─────────────────────────────

def test_before_counts_only_trades_closed_before_it():
    trades = [tr(i, 1) for i in range(25)]
    assert view(trades, before=T0 + timedelta(hours=20))["eligible_count"] == 20      # closes 0-19h
    assert view(trades, before=T0 + timedelta(hours=19))["eligible_count"] == 19      # a close AT the time is out
    assert view(trades, before=T0 + timedelta(hours=19))["unlocked"] is False
    assert view(trades, before=T0 - timedelta(hours=1))["eligible_count"] == 0


def test_before_leaves_out_an_unreadable_close_time():
    trades = [tr(0, 1, closed="not a date", tid="x")] + [tr(i, 1) for i in range(1, 21)]
    assert view(trades)["eligible_count"] == 21
    assert view(trades, before=T0 + timedelta(days=5))["eligible_count"] == 20


# ── summary.gate ─────────────────────────────────────────────────────────

def test_summary_gate_carries_the_view():
    trades = [tr(i, 5) for i in range(5)] + [tr(i, -0.1) for i in range(5, 25)]
    gate = wp._trades_summary(trades)["gate"]
    assert gate["start"] == "2026-09-13" and gate["count_from"] == "2026-10-05"
    assert {k: gate[k] for k in ("target", "eligible_count", "expectancy_r", "min_avg_r", "recent_n",
                                 "recent_expectancy_r", "checks", "unlocked")} == view(trades)
    assert gate["by_market"] == {"perp": {"eligible_count": 25, "expectancy_r": "0.920000"}}
    assert gate["unlocked"] is False


# ── the risk-limits save's 409 text ──────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def test_locked_save_names_both_averages(client, monkeypatch):
    gate = dict(view([tr(i, 5) for i in range(5)] + [tr(i, -0.1) for i in range(5, 25)]),
                start="2026-09-13", count_from="2026-10-05", by_market={})
    monkeypatch.setattr(wp, "_perp_risk_gate", lambda conn: gate)
    r = client.put("/api/trading/advisor/perps/risk-limits",
                   json={"per_trade_pct": 2, "total_pct": 5, "reason": "try"})
    assert r.status_code == 409
    err = r.get_json()["error"]
    assert err == ("the risk gate is locked (Stay at 1%): per trade can go above 1% only once 20+ rule-following "
                   "perp trades opened since 2026-10-05 average above +0.2R and the last 20 above 0R (now 25, "
                   "average 0.920000R, last 20 -0.100000R)")


def test_locked_save_text_before_twenty_trades(client, monkeypatch):
    gate = dict(view([tr(i, 1) for i in range(3)]), start="2026-09-13", count_from="2026-10-05", by_market={})
    monkeypatch.setattr(wp, "_perp_risk_gate", lambda conn: gate)
    err = client.put("/api/trading/advisor/perps/risk-limits",
                     json={"per_trade_pct": 2, "total_pct": 5, "reason": "try"}).get_json()["error"]
    assert err.endswith("(now 3, average 1.000000R, last 20 —)")
