"""Ledger-as-source 3c - the verdict's 7-day decay window ends at the newest
completed close.

The bug: advise_position measured decay with decay_pct_per_day(daily_rows,
as_of_date), as_of_date being today's UTC date, while the advisor route
feeds it COMPLETED candles only (date < today, Phase E v1 item 1). So
price_change_pct took latest = the today-1 close and base = the close
nearest today-7: a 6-day change that decay then divided by 7 - every decay
about 1/7 low (1%/day decline: 0.836 vs the true 0.970 %/day), and pct_30d
likewise measured 29 days.

Ruling R1 (Glenn, Sep 26): advise_position measures pct_7d / pct_30d /
decay ending at the NEWEST daily row on or before as_of
(token_history_latest_date, from 3b's close_age_days), not at as_of's date.
The 3b stale guard still measures age against as_of_date; flag order is
unchanged. The stale guard, constants and entry path are unchanged -
decay_pct_per_day, price_change_pct, verdict, close_age_days,
close_is_stale and latest_close_date are untouched, and the entry gate still
sees today's partial candle. Rows that include as_of's own date behave
exactly as before.

Fixtures and seeders are imported from tests/test_maxfi_advisor.py
(underscore helpers and fixtures only); the metrics kick is stubbed."""
import pytest
from datetime import datetime, date, timedelta, timezone

import maxfi_advisor as ma
import maxfi_pooldata
import web_portfolio as wp
from test_maxfi_advisor import (  # noqa: F401  (client/advisor_db are fixtures)
    client, advisor_db, _seed_position, _seed_catalogue_pool, _seed_metrics, _seed_token_daily,
)

AS_OF = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
TRUE_7D = (0.99 ** 7 - 1) * 100
TRUE_30D = (0.99 ** 30 - 1) * 100


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


def test_route_shaped_series_measures_a_true_7_day_change():
    rows = _series("2026-06-09")                       # completed candles only, as the route feeds
    r = ma.advise_position(_pos(rows))
    assert r["pct_7d"] == pytest.approx(TRUE_7D)
    assert r["decay_pct_day"] == pytest.approx(-TRUE_7D / 7)          # ~0.9705
    # the old anchor (as_of's own date) measured only 6 days
    assert ma.decay_pct_per_day(rows, "2026-06-10")["pct_7d"] == pytest.approx((0.99 ** 6 - 1) * 100)


def test_pct_30d_is_a_true_30_day_change():
    assert ma.advise_position(_pos(_series("2026-06-09")))["pct_30d"] == pytest.approx(TRUE_30D)


def test_rows_through_as_of_date_are_unchanged():
    rows = _series("2026-06-10")
    r = ma.advise_position(_pos(rows))
    e = ma.decay_pct_per_day(rows, "2026-06-10")
    assert (r["pct_7d"], r["pct_30d"], r["decay_pct_day"], r["decay_raw_pct_day"]) == (
        e["pct_7d"], e["pct_30d"], e["decay_pct_day"], e["decay_raw_pct_day"])


def test_age_2_series_measures_the_full_window():
    r = ma.advise_position(_pos(_series("2026-06-08")))
    assert r["flags"] == []
    assert r["token_history_age_days"] == 2
    assert r["pct_7d"] == pytest.approx(TRUE_7D)


def test_long_stale_full_history_reports_only_stale():
    r = ma.advise_position(_pos(_series("2026-05-29")))
    assert r["flags"] == ["stale_token_history"]
    assert r["verdict"] == "insufficient_data"
    assert r["pct_7d"] == pytest.approx(TRUE_7D)
    assert r["token_history_age_days"] == 12


def test_no_row_on_or_before_as_of_keeps_decay_none():
    r = ma.advise_position(_pos([("2026-06-11", 1.0)]))
    assert r["pct_7d"] is None
    assert r["decay_pct_day"] is None
    assert r["flags"] == ["no_token_history"]


def test_route_window_ends_at_the_newest_completed_close(client, advisor_db, monkeypatch):
    monkeypatch.setattr(wp, "_maybe_kick_metrics_auto_refresh", lambda: [])
    now = datetime.now(timezone.utc)
    today = now.date()
    _seed_position(advisor_db, 1, first_seen_at=(now - timedelta(days=40)).isoformat())
    _seed_catalogue_pool(advisor_db)
    _seed_metrics(advisor_db)
    rows = []
    for age in range(35, 0, -1):
        d, px = (today - timedelta(days=age)).isoformat(), 100.0 * 0.99 ** (35 - age)
        _seed_token_daily(advisor_db, date=d, close_usd=px)
        rows.append((d, px))
    _seed_token_daily(advisor_db, date=today.isoformat(), close_usd=50.0)    # a wild partial candle
    rows.append((today.isoformat(), 50.0))

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    body = r.get_json()
    pos = next(p for p in body["positions"] if p["id"] == 1)
    assert pos["flags"] == []
    assert pos["token_history_age_days"] == 1
    assert pos["pct_7d"] == pytest.approx(TRUE_7D)
    assert pos["decay_pct_day"] == pytest.approx(-TRUE_7D / 7)
    assert pos["threshold_pct_day"] == pytest.approx(2 * -TRUE_7D / 7)
    assert pos["ledger_shadow"]["threshold_pct_day"] == pytest.approx(2 * -TRUE_7D / 7)
    # the entry path is untouched: it still sees today's partial candle
    assert body["entry_candidates"][0]["downtrend_gate"] == maxfi_pooldata.downtrend_gate(rows, today.isoformat())
