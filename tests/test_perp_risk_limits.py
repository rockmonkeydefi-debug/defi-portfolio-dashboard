"""Advisor v1, Landing 16: R2's risk limits as dated settings in the pure
evaluator (src/engines/perp_rules.py) - stored in whole basis points, forward
only (a change applies to trades opened at or after it), R2 judged by the
limits in force when the trade opened with a note when they now differ, bad
rows ignored, settings_view's risk keys, and the defaults unchanged.

Hand-built trade dicts in the trades route's shape; made-up prices and sizes.
No DB, no network, no web_portfolio import."""
import copy
from datetime import datetime, timezone

from src.engines import perp_rules as pr

MIN = 60000
HOUR = 3600000
DAY = 86400000


def ms(y, mo, d, h=0, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


def iso(t):
    return datetime.fromtimestamp(t / 1000, timezone.utc).isoformat()


T0 = ms(2026, 10, 10, 10)
NOW = ms(2026, 10, 20, 12)
ABOVE = {"trend": {"v": 1, "reason": None,
                   "timeframes": {tf: {"position": "above"} for tf in ("15m", "30m", "1h", "4h", "12h", "1d", "1w")}}}


def trade(tid="t1", opened=T0, closed=None, size="10", **kw):
    """A closed long: entry 100, stop 95 set 2 min in. 1R = 5 x size: size 10 is
    1R 50 (0.1% of 50,000), size 160 is 1R 800 (1.6%)."""
    closed = opened + DAY if closed is None else closed
    t = {"trade_id": tid, "market": "perp", "source": "hyperliquid", "status": "closed" if closed else "open",
         "direction": "long", "symbol": "ETH", "opened_at": iso(opened), "closed_at": iso(closed) if closed else None,
         "avg_entry": "100", "size_peak": size,
         "stop": {"px": "95", "source": "hl_order", "set_at": iso(opened + 2 * MIN)},
         "planned_target": None, "leverage": None, "net_pnl": "10",
         "annotation": {"followed_rules": True, "notes": None, "deviation_note": None},
         "open_snapshot": copy.deepcopy(ABOVE)}
    t.update(kw)
    return t


def risk_row(per_trade_bps, total_bps, at, reason=None):
    return {"per_trade_bps": per_trade_bps, "total_bps": total_bps, "from": iso(at), "reason": reason, "set_at": iso(at)}


def r2(t, settings=None, now=NOW, all_trades=None):
    ev = pr.evaluate_trade(t, None, all_trades or [t], now_ms=now, settings=settings)
    return next(r for r in ev["rules"] if r["rule"] == "R2")


# ── constants and defaults ────────────────────────────────────────────────

def test_constants():
    assert (pr.RISK_PER_TRADE_PCT, pr.RISK_TOTAL_PCT) == (1, 5)
    assert pr.RISK_DEFAULT == {"per_trade_bps": 100, "total_bps": 500}
    assert (pr.RISK_MIN_BPS, pr.RISK_PER_TRADE_MAX_BPS, pr.RISK_TOTAL_MAX_BPS) == (10, 200, 500)


def test_defaults_without_rows():
    for s in (None, {}, {"status": [], "capital": [], "risk": []}):
        assert pr.risk_at(T0, s) == {"per_trade_bps": 100, "total_bps": 500, "since": None, "reason": None}
    res = r2(trade(size="110"))                                   # 1R 550 = 1.10%
    assert res["verdict"] == "fail" and res["evidence"].startswith("over 1% per trade: 1R $550.00 (1.10% of capital)")
    assert "notes" not in res


def test_percentages_print_without_trailing_zeros():
    assert [pr._bps_pct(b) for b in (100, 500, 150, 25, 200, 10)] == ["1", "5", "1.5", "0.25", "2", "0.1"]


# ── forward only ───────────────────────────────────────────────────────────

def test_a_raise_applies_from_its_time_on():
    s = {"risk": [risk_row(200, 500, T0 + DAY, "gate unlocked")]}
    before = trade("a", T0, size="160")                            # 1.6%, opened before the raise
    after = trade("b", T0 + 2 * DAY, size="160")                   # opened after it
    ra = r2(before, s, all_trades=[before])
    rb = r2(after, s, all_trades=[after])
    assert ra["verdict"] == "fail" and ra["evidence"].startswith("over 1% per trade")
    assert ra["notes"] == [f"limits 1% / 5% when this trade opened; 2% / 5% since {pr._iso(T0 + DAY)}"]
    assert rb["verdict"] == "pass" and "notes" not in rb


def test_a_row_at_the_open_time_applies():
    s = {"risk": [risk_row(200, 500, T0)]}
    assert r2(trade(size="160"), s)["verdict"] == "pass"


def test_lowered_limits_fail_with_their_own_numbers():
    s = {"risk": [risk_row(50, 300, T0 - DAY)]}                   # 0.5% per trade, 3% total
    res = r2(trade(size="60"), s)                                  # 1R 300 = 0.6%
    assert res["verdict"] == "fail" and res["evidence"].startswith("over 0.5% per trade")
    s_total = {"risk": [risk_row(100, 300, T0 - DAY)]}             # 1% per trade, 3% total
    trades = [trade(f"t{i}", T0 + i * MIN, closed=T0 + DAY, size="90") for i in range(4)]   # 0.9% each
    assert r2(trades[2], s_total, all_trades=trades)["verdict"] == "pass"                  # 2.7% open
    last = r2(trades[3], s_total, all_trades=trades)                                       # 3.6% open
    assert last["verdict"] == "fail" and last["evidence"].startswith("over 3% open in total")


def test_fractional_limits():
    s = {"risk": [risk_row(150, 500, T0 - DAY)]}
    assert r2(trade(size="140"), s)["verdict"] == "pass"           # 1.4%
    res = r2(trade(size="160"), s)                                 # 1.6%
    assert res["verdict"] == "fail" and res["evidence"].startswith("over 1.5% per trade")


def test_latest_row_wins_and_same_time_rows_keep_stored_order():
    s = {"risk": [risk_row(200, 500, T0 - 2 * DAY), risk_row(100, 400, T0 - DAY),
                  risk_row(150, 500, T0 - HOUR), risk_row(120, 500, T0 - HOUR)]}
    assert pr.risk_at(T0, s)["per_trade_bps"] == 120
    assert pr.risk_at(T0 - DAY, s)["total_bps"] == 400


def test_no_note_when_the_limits_now_match():
    s = {"risk": [risk_row(200, 500, T0 - 2 * DAY), risk_row(150, 500, T0 - DAY), risk_row(200, 500, T0 + DAY)]}
    res = r2(trade(size="160"), s)                                 # judged at 1.5%; now 2% again
    assert res["verdict"] == "fail" and res["notes"][0].startswith("limits 1.5% / 5% when this trade opened; 2% / 5%")
    s2 = {"risk": [risk_row(150, 500, T0 - DAY)]}
    assert "notes" not in r2(trade(size="140"), s2)


def test_capital_note_and_limits_note_together():
    s = {"capital": [{"from": "2026-10-01", "usd": 40000, "set_at": iso(T0 + HOUR)}],
         "risk": [risk_row(200, 500, T0 + DAY)]}
    res = r2(trade(size="60"), s)                                  # 1R 300 = 0.75% of 40,000
    assert res["verdict"] == "pass"
    assert res["notes"][0].startswith("capital entry for 2026-10-01 made") and res["notes"][1].startswith("limits 1% / 5%")


def test_status_notes_still_follow_the_r2_notes():
    s = {"status": [{"rule": "R2", "status": "tracking", "from": iso(T0 + DAY), "reason": "x", "set_at": iso(T0 + DAY)}],
         "risk": [risk_row(200, 500, T0 + DAY)]}
    res = r2(trade(size="160"), s)
    assert res["status"] == "enforced" and len(res["notes"]) == 2
    assert res["notes"][0].startswith("limits 1% / 5%") and res["notes"][1].startswith("enforced when this trade opened")


# ── bad rows ───────────────────────────────────────────────────────────────

def test_bad_rows_are_ignored():
    bad = [risk_row(250, 500, T0 - DAY),        # above the 2% per-trade ceiling
           risk_row(5, 500, T0 - DAY),          # under the minimum
           risk_row(200, 600, T0 - DAY),        # above the 5% total ceiling
           risk_row(300, 200, T0 - DAY),        # total under per trade
           risk_row(150, 120, T0 - DAY),        # total under per trade
           risk_row(1.5, 500, T0 - DAY),        # not whole basis points
           risk_row(True, 500, T0 - DAY),
           risk_row("150", 500, T0 - DAY),
           {"per_trade_bps": 150, "total_bps": 500, "from": "not a time", "set_at": iso(T0)},
           {"per_trade_bps": 150, "total_bps": 500},
           "not a row", None]
    assert pr.risk_at(T0, {"risk": bad}) == pr.risk_at(T0, None)
    assert r2(trade(size="160"), {"risk": bad}) == r2(trade(size="160"))


def test_settings_are_not_changed_and_no_state_is_kept():
    s = {"risk": [risk_row(200, 500, T0 - DAY)]}
    snapshot = copy.deepcopy(s)
    t = trade(size="160")
    first = r2(t, s)
    assert s == snapshot and pr.RISK_DEFAULT == {"per_trade_bps": 100, "total_bps": 500}
    assert r2(t) != first and r2(t, s) == first


# ── settings_view ──────────────────────────────────────────────────────────

def test_settings_view_risk_keys():
    view = pr.settings_view(None, NOW)
    assert view["risk_limits"] == {"per_trade_bps": 100, "total_bps": 500, "since": None, "reason": None}
    assert view["risk_default"] == {"per_trade_bps": 100, "total_bps": 500}
    assert view["risk_bounds"] == {"min_bps": 10, "per_trade_max_bps": 200, "total_max_bps": 500, "locked_max_bps": 100}
    assert view["risk_changes"] == [] and view["settings_changed_at"] is None
    s = {"risk": [risk_row(200, 500, NOW - DAY, "gate unlocked"), risk_row(150, 400, NOW + DAY)]}
    view = pr.settings_view(s, NOW)
    assert view["risk_limits"] == {"per_trade_bps": 200, "total_bps": 500, "since": iso(NOW - DAY), "reason": "gate unlocked"}
    assert view["risk_changes"] == [{"per_trade_bps": 200, "total_bps": 500, "from": iso(NOW - DAY), "reason": "gate unlocked"},
                                    {"per_trade_bps": 150, "total_bps": 400, "from": iso(NOW + DAY), "reason": None}]
    assert view["settings_changed_at"] == iso(NOW + DAY)


def test_r2_definition_names_the_limits_without_amounts():
    r2_def = next(r for r in pr.RULES if r["id"] == "R2")["definition"]
    assert "in force when the trade opened" in r2_def and "1% of capital by default" in r2_def
    assert "5% by default" in r2_def and "$" not in r2_def


def test_advisor_response_shape_is_unchanged():
    out = pr.evaluate_all([trade()], {}, now_ms=NOW, settings={"risk": [risk_row(200, 500, T0 - DAY)]})
    assert set(out) == {"definition_version", "capital", "rules", "trades", "tally", "note"}
    assert out["definition_version"] == 2
