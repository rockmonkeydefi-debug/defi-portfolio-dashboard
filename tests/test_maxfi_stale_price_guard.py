"""Ledger-as-source 3b - stale-price guard on verdicts and the entry gate.

Rulings (Glenn, Sep 26):
1. The guard lives in the pure advisor module - a new pure helper in
   maxfi_pooldata (latest_close_date) and the flag set inside
   advise_position - never a route-level patch, never a change to
   price_change_pct.
2. Staleness is measured by candle date: age_days = as_of_date minus the
   date of the newest row on or before as_of_date, in whole UTC days - not
   from fetched_at.
3. Stale means age_days > 2 (module constant ADVISOR_MAX_CLOSE_AGE_DAYS = 2,
   not a setting).
4. A stale position gets the flag "stale_token_history" and its verdict
   becomes insufficient_data through the existing floor short-circuit;
   pct_7d / pct_30d / decay_pct_day / decay_raw_pct_day stay RAW, like every
   other floor. Additive keys: token_history_latest_date (ISO date or None)
   and token_history_age_days (int or None).
5. The entry gate is one-directional: a stale series turns Clear (blocked
   False) into Unknown (blocked None) and appends "stale_token_history" to
   the candidate's flags; a stale Blocked stays Blocked, None stays None.
   downtrend_gate itself is unchanged.
6. Additive route fields: entry candidates get token_history_latest_date /
   token_history_age_days; constants gets "max_close_age_days".

Every new name is referenced as a module attribute inside the test bodies,
so the red run fails per test, not at collection. Fixtures and seeders are
imported from tests/test_maxfi_advisor.py (underscore helpers and fixtures
only); the metrics kick is stubbed so no refresh thread ever starts."""
import pytest
from datetime import datetime, date, timedelta, timezone

import maxfi_advisor as ma
import maxfi_pooldata
import web_portfolio as wp
from test_maxfi_advisor import (  # noqa: F401  (client/advisor_db are fixtures)
    BASE_ETH_ANCHOR, client, advisor_db, _seed_position, _seed_catalogue_pool,
    _seed_metrics, _seed_token_daily,
)

AS_OF = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
ADVISOR_URL = "/api/maxfi/advisor"


def _series(latest_iso):
    """Gapless (date_str, close) rows 2026-05-06 .. latest_iso inclusive,
    starting at 100.0 and falling 1% a day."""
    rows = []
    d, px, end = date(2026, 5, 6), 100.0, date.fromisoformat(latest_iso)
    while d <= end:
        rows.append((d.isoformat(), px))
        d += timedelta(days=1)
        px *= 0.99
    return rows


def _pos(rows, **overrides):
    pos = {
        "current_value_usd": 10000.0, "uncollected_usd": 0.0, "uncollected_accrual_days": 10.0,
        "claims": [], "first_seen_at_utc": AS_OF - timedelta(days=30), "as_of_utc": AS_OF,
        "daily_rows": rows, "volatile_side_resolved": True,
    }
    pos.update(overrides)
    return pos


def _no_kick(monkeypatch):
    monkeypatch.setattr(wp, "_maybe_kick_metrics_auto_refresh", lambda: [])


def _seed_rows(db, ages_px):
    today = datetime.now(timezone.utc).date()
    rows = []
    for age, px in ages_px:
        d = (today - timedelta(days=age)).isoformat()
        _seed_token_daily(db, date=d, close_usd=px)
        rows.append((d, px))
    return rows, today.isoformat()


# ── pure helpers ───────────────────────────────────────────────────────────

def test_latest_close_date_picks_newest_on_or_before_as_of():
    rows = [("2026-06-05", 1.0), ("2026-06-12", 1.0), ("2026-06-01", 1.0), ("2026-06-08", 1.0)]
    assert maxfi_pooldata.latest_close_date(rows, "2026-06-10") == "2026-06-08"


def test_latest_close_date_none_cases():
    rows = [("2026-06-05", 1.0)]
    assert maxfi_pooldata.latest_close_date([], "2026-06-10") is None
    assert maxfi_pooldata.latest_close_date([("2026-06-12", 1.0)], "2026-06-10") is None
    assert maxfi_pooldata.latest_close_date(rows, "not-a-date") is None
    assert maxfi_pooldata.latest_close_date(rows, None) is None
    assert maxfi_pooldata.latest_close_date([("junk", 1.0), ("2026-06-03", 1.0)], "2026-06-10") == "2026-06-03"


def test_latest_close_date_matches_price_change_pct_latest():
    rows = [("2026-06-03", 2.0), ("2026-06-09", None)]
    assert maxfi_pooldata.latest_close_date(rows, "2026-06-10") == "2026-06-09"
    # price_change_pct picked the same (None-close) row as its latest
    assert maxfi_pooldata.price_change_pct(rows, "2026-06-10", 7) is None


def test_close_age_days():
    assert ma.close_age_days(_series("2026-06-08"), "2026-06-10") == ("2026-06-08", 2)
    assert ma.close_age_days([], "2026-06-10") == (None, None)
    assert ma.close_age_days(_series("2026-06-08"), None) == (None, None)


def test_close_is_stale_boundary_and_constant():
    assert ma.ADVISOR_MAX_CLOSE_AGE_DAYS == 2
    assert [ma.close_is_stale(a) for a in (None, 0, 1, 2, 3, 10)] == [False, False, False, False, True, True]


# ── advise_position ────────────────────────────────────────────────────────

def test_advise_position_age_2_keeps_its_verdict():
    r = ma.advise_position(_pos(_series("2026-06-08")))
    assert r["flags"] == []
    assert r["verdict"] in ("HOLD", "CLOSE")
    assert r["token_history_latest_date"] == "2026-06-08"
    assert r["token_history_age_days"] == 2


def test_advise_position_age_3_is_stale_with_raw_figures_kept():
    rows = _series("2026-06-07")
    r = ma.advise_position(_pos(rows))
    # Since 3c the decay window ends at the newest close (2026-06-07), not at as_of's date.
    exp = ma.decay_pct_per_day(rows, "2026-06-07")
    assert r["flags"] == ["stale_token_history"]
    assert r["verdict"] == "insufficient_data"
    assert r["threshold_pct_day"] is None and r["margin_pct_day"] is None and r["decay_floored"] is None
    assert exp["pct_7d"] is not None
    assert r["pct_7d"] == pytest.approx(exp["pct_7d"])
    assert r["decay_pct_day"] == pytest.approx(exp["decay_pct_day"])
    assert r["run_rate_7d_pct_day"] is not None
    assert r["token_history_latest_date"] == "2026-06-07"
    assert r["token_history_age_days"] == 3


def test_advise_position_long_stale_reports_both_flags():
    # Newest close 12 days old AND no row near 2026-05-22 to measure the 7-day window from.
    r = ma.advise_position(_pos([("2026-05-10", 1.0), ("2026-05-29", 1.0)]))
    assert r["flags"] == ["no_token_history", "stale_token_history"]
    assert r["token_history_age_days"] == 12


def test_advise_position_empty_history_is_not_stale():
    r = ma.advise_position(_pos([]))
    assert r["flags"] == ["no_token_history"]
    assert r["token_history_latest_date"] is None
    assert r["token_history_age_days"] is None


def test_advise_position_without_as_of_is_not_stale():
    r = ma.advise_position(_pos(_series("2026-06-07"), as_of_utc=None))
    assert "stale_token_history" not in r["flags"]
    assert r["token_history_age_days"] is None


# ── the advisor route ──────────────────────────────────────────────────────

def _position_scene(db, ages_px):
    now = datetime.now(timezone.utc)
    _seed_position(db, 1, first_seen_at=(now - timedelta(days=40)).isoformat())
    _seed_catalogue_pool(db)
    _seed_metrics(db)
    return _seed_rows(db, ages_px)


def _get(client):
    r = client.get(ADVISOR_URL)
    assert r.status_code == 200
    return r.get_json()


def test_route_stale_position_flag_in_verdict_and_ledger_shadow(client, advisor_db, monkeypatch):
    _no_kick(monkeypatch)
    _position_scene(advisor_db, ((31, 1.0), (9, 1.2), (4, 1.0)))
    today = datetime.now(timezone.utc).date()
    pos = next(p for p in _get(client)["positions"] if p["id"] == 1)
    assert pos["verdict"] == "insufficient_data"
    assert pos["flags"] == ["stale_token_history"]
    assert pos["ledger_shadow"]["flags"] == ["stale_token_history"]
    assert pos["token_history_age_days"] == 4
    assert pos["token_history_latest_date"] == (today - timedelta(days=4)).isoformat()
    assert pos["pct_7d"] == pytest.approx((1.0 - 1.2) / 1.2 * 100)


def test_route_fresh_position_is_unflagged(client, advisor_db, monkeypatch):
    _no_kick(monkeypatch)
    _position_scene(advisor_db, ((8, 1.2), (1, 1.0)))
    pos = next(p for p in _get(client)["positions"] if p["id"] == 1)
    assert pos["flags"] == []
    assert pos["verdict"] in ("HOLD", "CLOSE")
    assert pos["token_history_age_days"] == 1


def test_route_constants_include_max_close_age_days(client, advisor_db, monkeypatch):
    _no_kick(monkeypatch)
    assert _get(client)["constants"]["max_close_age_days"] == ma.ADVISOR_MAX_CLOSE_AGE_DAYS == 2


def _entry_scene(db, ages_px):
    _seed_catalogue_pool(db)
    _seed_metrics(db)
    return _seed_rows(db, ages_px)


def test_route_entry_stale_clear_becomes_unknown(client, advisor_db, monkeypatch):
    _no_kick(monkeypatch)
    rows, today = _entry_scene(advisor_db, ((31, 1.0), (9, 1.1), (4, 1.2)))
    pre = maxfi_pooldata.downtrend_gate(rows, today)
    assert pre["blocked"] is False
    cand = _get(client)["entry_candidates"][0]
    assert cand["downtrend_gate"] == {**pre, "blocked": None}
    assert "stale_token_history" in cand["flags"]
    assert cand["token_history_age_days"] == 4


def test_route_entry_stale_blocked_stays_blocked(client, advisor_db, monkeypatch):
    _no_kick(monkeypatch)
    rows, today = _entry_scene(advisor_db, ((31, 1.0), (9, 1.0), (4, 0.8)))
    pre = maxfi_pooldata.downtrend_gate(rows, today)
    assert pre["blocked"] is True
    cand = _get(client)["entry_candidates"][0]
    assert cand["downtrend_gate"] == pre
    assert "stale_token_history" in cand["flags"]


def test_route_entry_fresh_gate_unchanged(client, advisor_db, monkeypatch):
    _no_kick(monkeypatch)
    rows, today = _entry_scene(advisor_db, ((31, 1.0), (8, 1.1), (1, 1.2)))
    pre = maxfi_pooldata.downtrend_gate(rows, today)
    assert pre["blocked"] is False
    cand = _get(client)["entry_candidates"][0]
    assert cand["downtrend_gate"] == pre
    assert "stale_token_history" not in cand["flags"]
    assert cand["token_history_age_days"] == 1


def test_route_entry_unresolved_side_has_no_age(client, advisor_db, monkeypatch):
    _no_kick(monkeypatch)
    _seed_catalogue_pool(advisor_db, token0=BASE_ETH_ANCHOR, token1="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913")
    _seed_metrics(advisor_db)
    cand = _get(client)["entry_candidates"][0]
    assert cand["token_history_latest_date"] is None
    assert cand["token_history_age_days"] is None
    assert "volatile_side_unresolved" in cand["flags"]
    assert "stale_token_history" not in cand["flags"]
