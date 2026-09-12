"""Tests for maxfi_advisor.py (LP Advisor Phase C1): the pure verdict
module. Most tests here call the module directly with plain values/dicts -
no network, no DB, no Flask. A small route-level section at the end
exercises GET /api/maxfi/advisor end-to-end, same client/monkeypatch
fixture pattern as tests/test_maxfi_token_daily_refresh.py; same
shared-cache sqlite URI pattern as tests/test_maxfi_valuation_route.py:308.
"""
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import maxfi_advisor as ma
import maxfi_schema
import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp


def _dt(iso):
    return datetime.fromisoformat(iso)


# ── parse_utc (C1 hotfix: timezone normalization) ────────────────────────

def test_parse_utc_naive_string_treated_as_utc():
    result = ma.parse_utc("2026-06-10T00:00:00")
    assert result == datetime(2026, 6, 10, 0, 0, 0, tzinfo=timezone.utc)
    assert result.tzinfo is not None


def test_parse_utc_offset_string():
    result = ma.parse_utc("2026-06-10T00:00:00+00:00")
    assert result == datetime(2026, 6, 10, 0, 0, 0, tzinfo=timezone.utc)


def test_parse_utc_z_suffix_string():
    result = ma.parse_utc("2026-06-10T00:00:00Z")
    assert result == datetime(2026, 6, 10, 0, 0, 0, tzinfo=timezone.utc)


def test_parse_utc_naive_datetime_treated_as_utc():
    result = ma.parse_utc(datetime(2026, 6, 10, 12, 0, 0))
    assert result == datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_utc_aware_non_utc_datetime_converted():
    from datetime import timedelta as _td
    minus_five = timezone(_td(hours=-5))
    aware = datetime(2026, 6, 10, 12, 0, 0, tzinfo=minus_five)
    result = ma.parse_utc(aware)
    assert result == datetime(2026, 6, 10, 17, 0, 0, tzinfo=timezone.utc)
    assert result.tzinfo == timezone.utc


def test_parse_utc_none_is_none():
    assert ma.parse_utc(None) is None


def test_parse_utc_empty_string_is_none():
    assert ma.parse_utc("") is None


def test_parse_utc_malformed_string_is_none():
    assert ma.parse_utc("not-a-timestamp") is None


def test_parse_utc_non_string_non_datetime_is_none():
    assert ma.parse_utc(12345) is None


# ── run_rate_pct_per_day ─────────────────────────────────────────────────

def test_run_rate_happy_path():
    # $70 earned over 7 days on a $10,000 position -> 10/10000*100 = 0.1%/day
    result = ma.run_rate_pct_per_day(70.0, 7, 10000.0)
    assert result == pytest.approx(0.1)


def test_run_rate_zero_days_is_none():
    assert ma.run_rate_pct_per_day(70.0, 0, 10000.0) is None


def test_run_rate_negative_days_is_none():
    assert ma.run_rate_pct_per_day(70.0, -1, 10000.0) is None


def test_run_rate_none_current_value_is_none():
    assert ma.run_rate_pct_per_day(70.0, 7, None) is None


def test_run_rate_zero_current_value_is_none():
    assert ma.run_rate_pct_per_day(70.0, 7, 0.0) is None


def test_run_rate_none_earned_is_none():
    assert ma.run_rate_pct_per_day(None, 7, 10000.0) is None


def test_run_rate_zero_earned_is_valid_zero():
    assert ma.run_rate_pct_per_day(0.0, 7, 10000.0) == 0.0


# ── window_earnings_usd ──────────────────────────────────────────────────

def test_window_earnings_claim_inside_window_counted():
    as_of = _dt("2026-06-10T00:00:00+00:00")
    claims = [("2026-06-05T00:00:00+00:00", 50.0)]
    result = ma.window_earnings_usd(claims, 0.0, 0, as_of, window_days=7)
    assert result == pytest.approx(50.0)


def test_window_earnings_claim_outside_window_excluded():
    as_of = _dt("2026-06-10T00:00:00+00:00")
    claims = [("2026-06-02T00:00:00+00:00", 50.0)]  # 8 days before as_of
    result = ma.window_earnings_usd(claims, 0.0, 0, as_of, window_days=7)
    assert result == pytest.approx(0.0)


def test_window_earnings_claim_exactly_on_as_of_counted():
    as_of = _dt("2026-06-10T00:00:00+00:00")
    claims = [("2026-06-10T00:00:00+00:00", 50.0)]
    result = ma.window_earnings_usd(claims, 0.0, 0, as_of, window_days=7)
    assert result == pytest.approx(50.0)


def test_window_earnings_claim_exactly_at_window_start_excluded():
    as_of = _dt("2026-06-10T00:00:00+00:00")
    claims = [("2026-06-03T00:00:00+00:00", 50.0)]  # exactly 7 days before
    result = ma.window_earnings_usd(claims, 0.0, 0, as_of, window_days=7)
    assert result == pytest.approx(0.0)


def test_window_earnings_proration_when_accrual_predates_window():
    # Uncollected has been accruing for 14 days (twice the 7d window) ->
    # only 7/14 = half of the balance is attributable to the window.
    as_of = _dt("2026-06-10T00:00:00+00:00")
    result = ma.window_earnings_usd([], 100.0, 14, as_of, window_days=7)
    assert result == pytest.approx(50.0)


def test_window_earnings_proration_never_claimed_full_amount_within_window():
    # Accrual (3 days) is SHORTER than the window (7 days) -> full amount.
    as_of = _dt("2026-06-10T00:00:00+00:00")
    result = ma.window_earnings_usd([], 30.0, 3, as_of, window_days=7)
    assert result == pytest.approx(30.0)


def test_window_earnings_accrual_days_zero_adds_full_amount():
    as_of = _dt("2026-06-10T00:00:00+00:00")
    result = ma.window_earnings_usd([], 42.0, 0, as_of, window_days=7)
    assert result == pytest.approx(42.0)


def test_window_earnings_accrual_days_negative_adds_full_amount():
    as_of = _dt("2026-06-10T00:00:00+00:00")
    result = ma.window_earnings_usd([], 42.0, -5, as_of, window_days=7)
    assert result == pytest.approx(42.0)


def test_window_earnings_claim_with_none_usd_skipped():
    as_of = _dt("2026-06-10T00:00:00+00:00")
    claims = [("2026-06-05T00:00:00+00:00", None), ("2026-06-06T00:00:00+00:00", 20.0)]
    result = ma.window_earnings_usd(claims, 0.0, 0, as_of, window_days=7)
    assert result == pytest.approx(20.0)


def test_window_earnings_combines_claims_and_prorated_uncollected():
    as_of = _dt("2026-06-10T00:00:00+00:00")
    claims = [("2026-06-05T00:00:00+00:00", 50.0)]
    result = ma.window_earnings_usd(claims, 100.0, 14, as_of, window_days=7)
    assert result == pytest.approx(50.0 + 50.0)


# ── decay_pct_per_day ────────────────────────────────────────────────────

def _daily_rows_for(prices_by_date):
    return list(prices_by_date.items())


def test_decay_falling_token_clamp_not_engaged():
    # 7 days ago: 2.0, today: 1.0 -> -50% over 7d -> raw = 50/7 = ~7.14/day,
    # positive already, clamp is a no-op.
    rows = _daily_rows_for({"2026-06-03": 2.0, "2026-06-10": 1.0})
    result = ma.decay_pct_per_day(rows, "2026-06-10")
    assert result["pct_7d"] == pytest.approx(-50.0)
    assert result["decay_raw_pct_day"] == pytest.approx(50.0 / 7.0)
    assert result["decay_pct_day"] == pytest.approx(50.0 / 7.0)


def test_decay_rising_token_clamped_to_zero():
    # 7 days ago: 1.0, today: 2.0 -> +100% over 7d -> raw is NEGATIVE,
    # clamped to 0.0 (Glenn decision A).
    rows = _daily_rows_for({"2026-06-03": 1.0, "2026-06-10": 2.0})
    result = ma.decay_pct_per_day(rows, "2026-06-10")
    assert result["pct_7d"] == pytest.approx(100.0)
    assert result["decay_raw_pct_day"] < 0
    assert result["decay_pct_day"] == 0.0


def test_decay_flat_token_zero():
    rows = _daily_rows_for({"2026-06-03": 1.0, "2026-06-10": 1.0})
    result = ma.decay_pct_per_day(rows, "2026-06-10")
    assert result["pct_7d"] == pytest.approx(0.0)
    assert result["decay_raw_pct_day"] == pytest.approx(0.0)
    assert result["decay_pct_day"] == pytest.approx(0.0)


def test_decay_none_history_all_decay_fields_none():
    result = ma.decay_pct_per_day([], "2026-06-10")
    assert result["pct_7d"] is None
    assert result["decay_pct_day"] is None
    assert result["decay_raw_pct_day"] is None


def test_decay_pct_30d_is_context_only_independent_of_pct_7d():
    # 30d history present and computable, but no row near the 7d mark.
    rows = _daily_rows_for({"2026-05-11": 1.0, "2026-06-10": 2.0})
    result = ma.decay_pct_per_day(rows, "2026-06-10")
    assert result["pct_7d"] is None
    assert result["decay_pct_day"] is None
    assert result["pct_30d"] == pytest.approx(100.0)


# ── verdict ──────────────────────────────────────────────────────────────

def test_verdict_close_below_threshold():
    result = ma.verdict(0.5, 0.5)  # threshold = 2*0.5 = 1.0; 0.5 < 1.0
    assert result["verdict"] == "CLOSE"
    assert result["threshold_pct_day"] == pytest.approx(1.0)
    assert result["margin_pct_day"] == pytest.approx(-0.5)


def test_verdict_hold_at_exact_equality():
    result = ma.verdict(1.0, 0.5)  # threshold = 1.0; equality = HOLD
    assert result["verdict"] == "HOLD"
    assert result["margin_pct_day"] == pytest.approx(0.0)


def test_verdict_hold_above_threshold():
    result = ma.verdict(2.0, 0.5)
    assert result["verdict"] == "HOLD"
    assert result["margin_pct_day"] == pytest.approx(1.0)


def test_verdict_insufficient_on_none_run_rate():
    result = ma.verdict(None, 0.5)
    assert result["verdict"] == "insufficient_data"
    assert result["threshold_pct_day"] is None
    assert result["margin_pct_day"] is None


def test_verdict_insufficient_on_none_decay():
    result = ma.verdict(1.0, None)
    assert result["verdict"] == "insufficient_data"
    assert result["threshold_pct_day"] is None
    assert result["margin_pct_day"] is None


def test_verdict_run_rate_zero_with_decay_zero_holds():
    result = ma.verdict(0.0, 0.0)  # threshold = 0; 0.0 < 0.0 is False -> HOLD
    assert result["verdict"] == "HOLD"


def test_verdict_run_rate_zero_with_small_decay_floored_to_hold():
    # Phase E v1.2: decay 0.1 is inside the de-minimis floor band
    # (0, ADVISOR_DEMINIMIS_DECAY_PCT_DAY=0.25), so the verdict math treats
    # it as an effective 0.0 - threshold 0.0, margin = run_rate (0.0) -> HOLD.
    # Before the floor existed this test asserted CLOSE (threshold 0.2;
    # 0.0 < 0.2 -> CLOSE), which the floor now correctly prevents.
    result = ma.verdict(0.0, 0.1)
    assert result["verdict"] == "HOLD"
    assert result["decay_floored"] is True
    assert result["threshold_pct_day"] == pytest.approx(0.0)
    assert result["margin_pct_day"] == pytest.approx(0.0)


# ── Phase E v1.2: de-minimis decay floor ────────────────────────────────

def test_verdict_decay_inside_band_is_floored_to_hold():
    # decay 0.10 is inside (0, 0.25). Without the floor: threshold =
    # 2.0*0.10 = 0.20, and run_rate 0.05 < 0.20 -> CLOSE (the raw inequality
    # WOULD flip it - this pins that the floor is what prevents it, not a
    # coincidence of the numbers chosen).
    raw_threshold = ma.ADVISOR_DECAY_MULTIPLIER * 0.10
    assert 0.05 < raw_threshold  # sanity: without the floor this would CLOSE

    result = ma.verdict(0.05, 0.10)
    assert result["verdict"] == "HOLD"
    assert result["decay_floored"] is True
    assert result["threshold_pct_day"] == pytest.approx(0.0)
    assert result["margin_pct_day"] == pytest.approx(0.05)  # margin == run_rate


def test_verdict_decay_exactly_at_floor_constant_is_not_floored():
    # Strictness: decay exactly equal to ADVISOR_DEMINIMIS_DECAY_PCT_DAY
    # (0.25) is NOT floored - the upper bound is a strict "<".
    result = ma.verdict(1.0, ma.ADVISOR_DEMINIMIS_DECAY_PCT_DAY)
    assert result["decay_floored"] is False
    assert result["threshold_pct_day"] == pytest.approx(0.50)  # 2.0 * 0.25, unfloored
    assert result["verdict"] == "HOLD"  # 1.0 >= 0.50


def test_verdict_decay_above_band_is_byte_identical_to_pre_floor_behavior():
    result = ma.verdict(0.10, 0.30)  # threshold = 0.60; 0.10 < 0.60 -> CLOSE
    assert result["verdict"] == "CLOSE"
    assert result["decay_floored"] is False
    assert result["threshold_pct_day"] == pytest.approx(0.60)
    assert result["margin_pct_day"] == pytest.approx(-0.50)


def test_verdict_flat_rising_clamp_zero_decay_is_not_floored():
    # decay exactly 0.0 (the flat/rising clamp's own output) fails the
    # floor's "0 < decay_pct_day" condition - it was already zero, so it is
    # not "floored," it just IS zero. decay_floored must read False here,
    # never True.
    result = ma.verdict(0.0, 0.0)
    assert result["decay_floored"] is False
    assert result["threshold_pct_day"] == pytest.approx(0.0)
    assert result["verdict"] == "HOLD"


def test_verdict_decay_none_is_insufficient_data_with_decay_floored_none():
    result = ma.verdict(1.0, None)
    assert result["verdict"] == "insufficient_data"
    assert result["decay_floored"] is None


# ── advise_position ──────────────────────────────────────────────────────

def _base_pos(**overrides):
    as_of = _dt("2026-06-10T00:00:00+00:00")
    pos = {
        "current_value_usd": 10000.0,
        "uncollected_usd": 0.0,
        "uncollected_accrual_days": 10.0,
        "claims": [],
        "first_seen_at_utc": as_of - timedelta(days=30),
        "as_of_utc": as_of,
        "daily_rows": _daily_rows_for({"2026-06-03": 1.0, "2026-06-10": 1.0}),
        "volatile_side_resolved": True,
    }
    pos.update(overrides)
    return pos


def test_advise_position_too_young_flag_alone():
    as_of = _dt("2026-06-10T00:00:00+00:00")
    pos = _base_pos(first_seen_at_utc=as_of - timedelta(days=1))
    result = ma.advise_position(pos)
    assert "too_young" in result["flags"]
    assert result["verdict"] == "insufficient_data"


def test_advise_position_no_current_value_flag_alone():
    pos = _base_pos(current_value_usd=None)
    result = ma.advise_position(pos)
    assert "no_current_value" in result["flags"]
    assert result["verdict"] == "insufficient_data"


def test_advise_position_no_token_history_flag_alone():
    pos = _base_pos(daily_rows=[])
    result = ma.advise_position(pos)
    assert "no_token_history" in result["flags"]
    assert result["verdict"] == "insufficient_data"


def test_advise_position_volatile_side_unresolved_flag_alone():
    pos = _base_pos(volatile_side_resolved=False)
    result = ma.advise_position(pos)
    assert "volatile_side_unresolved" in result["flags"]
    assert result["verdict"] == "insufficient_data"


def test_advise_position_happy_path_reports_every_intermediate():
    as_of = _dt("2026-06-10T00:00:00+00:00")
    pos = _base_pos(
        current_value_usd=10000.0,
        uncollected_usd=35.0,
        uncollected_accrual_days=3.0,
        claims=[("2026-06-08T00:00:00+00:00", 35.0)],
        first_seen_at_utc=as_of - timedelta(days=30),
        daily_rows=_daily_rows_for({"2026-06-03": 2.0, "2026-06-10": 1.0}),  # -50% over 7d
    )
    result = ma.advise_position(pos)

    assert result["flags"] == []
    assert result["days_open"] == pytest.approx(30.0)
    # window: 35 claimed + 35 uncollected (accrual 3d < window 7d -> full) = 70
    assert result["window_earned_usd"] == pytest.approx(70.0)
    assert result["run_rate_7d_pct_day"] == pytest.approx((70.0 / 7.0) / 10000.0 * 100)
    assert result["lifetime_earned_usd"] == pytest.approx(35.0 + 35.0)
    assert result["run_rate_lifetime_pct_day"] == pytest.approx((70.0 / 30.0) / 10000.0 * 100)
    assert result["pct_7d"] == pytest.approx(-50.0)
    assert result["decay_pct_day"] == pytest.approx(50.0 / 7.0)
    assert result["decay_raw_pct_day"] == pytest.approx(50.0 / 7.0)
    assert result["threshold_pct_day"] == pytest.approx(2.0 * (50.0 / 7.0))
    assert result["margin_pct_day"] is not None
    assert result["verdict"] in ("HOLD", "CLOSE")


def test_advise_position_end_to_end_floored_verdict_reports_raw_decay():
    # Phase E v1.2 end-to-end: a position whose real decay (0.10%/day) sits
    # inside the de-minimis floor band and whose run_rate_7d (0.05%/day)
    # would CLOSE under the raw threshold (0.20). The payload must show
    # decay_floored True and verdict HOLD, while decay_pct_day/
    # decay_raw_pct_day still report the RAW 0.10 - the floor changes only
    # the verdict math, never the reported figures.
    as_of = _dt("2026-06-10T00:00:00+00:00")
    pos = _base_pos(
        current_value_usd=10000.0,
        uncollected_usd=35.0,
        uncollected_accrual_days=3.0,
        claims=[],
        first_seen_at_utc=as_of - timedelta(days=30),
        # -0.7% over 7d -> decay_raw_pct_day = 0.7/7 = 0.10
        daily_rows=_daily_rows_for({"2026-06-03": 1.0, "2026-06-10": 0.993}),
    )
    result = ma.advise_position(pos)

    assert result["flags"] == []
    assert result["decay_pct_day"] == pytest.approx(0.10)
    assert result["decay_raw_pct_day"] == pytest.approx(0.10)
    # window: 35 uncollected (accrual 3d < window 7d -> full) = 35;
    # run_rate_7d = (35/7)/10000*100 = 0.05
    assert result["run_rate_7d_pct_day"] == pytest.approx(0.05)
    assert result["decay_floored"] is True
    assert result["threshold_pct_day"] == pytest.approx(0.0)
    assert result["margin_pct_day"] == pytest.approx(0.05)
    assert result["verdict"] == "HOLD"


def test_advise_position_lifetime_vs_7d_divergence():
    # An old, historically strong earner that has gone dead in the last
    # week: lifetime run-rate stays high, but the 7d verdict reflects
    # only the recent (zero) window and should CLOSE against any real decay.
    as_of = _dt("2026-06-10T00:00:00+00:00")
    pos = _base_pos(
        current_value_usd=10000.0,
        uncollected_usd=0.0,
        uncollected_accrual_days=7.0,
        # A large claim from long ago (outside the 7d window) inflates
        # lifetime earnings but contributes nothing to the 7d window.
        claims=[("2026-01-01T00:00:00+00:00", 5000.0)],
        first_seen_at_utc=as_of - timedelta(days=180),
        daily_rows=_daily_rows_for({"2026-06-03": 2.0, "2026-06-10": 1.0}),  # -50% over 7d, decaying
    )
    result = ma.advise_position(pos)

    assert result["window_earned_usd"] == pytest.approx(0.0)
    assert result["run_rate_7d_pct_day"] == pytest.approx(0.0)
    assert result["run_rate_lifetime_pct_day"] == pytest.approx((5000.0 / 180.0) / 10000.0 * 100)
    assert result["run_rate_lifetime_pct_day"] > result["run_rate_7d_pct_day"]
    # decay is positive (falling token) -> run_rate_7d (0.0) < threshold -> CLOSE
    assert result["decay_pct_day"] > 0
    assert result["verdict"] == "CLOSE"


def test_advise_position_mixed_naive_aware_timestamps():
    # Reproduces the production 500: naive first_seen_at (no offset),
    # aware as_of, and claims mixing "Z"-suffixed and naive formats. Must
    # return a verdict dict, never raise.
    as_of = _dt("2026-06-10T00:00:00+00:00")
    pos = _base_pos(
        first_seen_at_utc="2026-05-01T00:00:00",  # naive string
        as_of_utc=as_of,  # aware datetime
        claims=[
            ("2026-06-08T00:00:00Z", 10.0),        # Z-suffixed
            ("2026-06-05T00:00:00", 5.0),          # naive string
        ],
        daily_rows=_daily_rows_for({"2026-06-03": 1.2, "2026-06-10": 1.0}),
    )
    result = ma.advise_position(pos)

    assert result["verdict"] in ("HOLD", "CLOSE", "insufficient_data")
    assert "bad_timestamp" not in result["flags"]
    assert result["days_open"] is not None
    assert result["window_earned_usd"] == pytest.approx(15.0)


def test_window_boundary_exact_under_mixed_formats():
    # A claim exactly 7 days old in "Z" form vs a naive as_of - the
    # boundary itself (window_start, exclusive) must still land correctly
    # once both sides are normalized to aware UTC.
    as_of_naive = "2026-06-10T00:00:00"
    exactly_at_window_start = "2026-06-03T00:00:00Z"  # exactly 7 days before
    just_inside_window = "2026-06-03T00:00:01Z"  # one second after window_start

    result_at_boundary = ma.window_earnings_usd(
        [(exactly_at_window_start, 50.0)], 0.0, 0, as_of_naive, window_days=7,
    )
    assert result_at_boundary == pytest.approx(0.0)  # exclusive - not counted

    result_inside = ma.window_earnings_usd(
        [(just_inside_window, 50.0)], 0.0, 0, as_of_naive, window_days=7,
    )
    assert result_inside == pytest.approx(50.0)


# ── entry_score ──────────────────────────────────────────────────────────

def test_entry_score_known_numbers_fee_tier_3000():
    # volume_h24=100000, fee_tier=3000 (0.3%), liquidity=500000, mult=1.0
    # fee_apr_est_pct = 100000 * 0.003 / 500000 * 365 * 100 = 21.9
    result = ma.entry_score(100000.0, 3000, 500000.0, 1.0)
    assert result["fee_apr_est_pct"] == pytest.approx(21.9)
    assert result["entry_score"] == pytest.approx(21.9)
    assert result["tvl_source"] == "dexscreener_liquidity_proxy"
    assert result["flags"] == []


def test_entry_score_none_volume_mult_defaults_to_one_and_flags():
    result = ma.entry_score(100000.0, 3000, 500000.0, None)
    assert result["entry_score"] == pytest.approx(result["fee_apr_est_pct"] * 1.0)
    assert "volume_trend_unavailable" in result["flags"]


def test_entry_score_zero_liquidity_is_none():
    result = ma.entry_score(100000.0, 3000, 0.0, 1.0)
    assert result["fee_apr_est_pct"] is None
    assert result["entry_score"] is None
    assert result["tvl_source"] == "dexscreener_liquidity_proxy"


def test_entry_score_none_volume_h24_is_none():
    result = ma.entry_score(None, 3000, 500000.0, 1.0)
    assert result["fee_apr_est_pct"] is None
    assert result["entry_score"] is None


def test_entry_score_tvl_source_literal_always_present():
    result = ma.entry_score(None, None, None, None)
    assert result["tvl_source"] == "dexscreener_liquidity_proxy"


# ── entry_volume_multiplier ──────────────────────────────────────────────

def test_entry_volume_multiplier_h6x4_above_h24():
    # h6=30000 -> annualized 120000, vs h24=100000 -> ratio 1.2
    result = ma.entry_volume_multiplier(30000.0, 100000.0)
    assert result == pytest.approx(1.2)


def test_entry_volume_multiplier_h6x4_below_h24():
    # h6=10000 -> annualized 40000, vs h24=100000 -> ratio 0.4
    result = ma.entry_volume_multiplier(10000.0, 100000.0)
    assert result == pytest.approx(0.4)


def test_entry_volume_multiplier_none_input_is_none():
    assert ma.entry_volume_multiplier(None, 100000.0) is None
    assert ma.entry_volume_multiplier(30000.0, None) is None


# ── route: GET /api/maxfi/advisor ─────────────────────────────────────────

WALLET = "0x" + "c" * 40
BASE_ETH_ANCHOR = "0x4200000000000000000000000000000000000006"
VOLATILE_TOKEN = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
POOL_A = "0xpoola"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


@pytest.fixture
def advisor_db(monkeypatch):
    uri = f"file:maxfi_advisor_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    keepalive.row_factory = sqlite3.Row
    maxfi_schema.ensure_maxfi_tables(keepalive)

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    yield keepalive
    keepalive.close()


def _seed_position(db, position_id, chain="base", pool_address=POOL_A,
                    token0=VOLATILE_TOKEN, token1=BASE_ETH_ANCHOR,
                    first_seen_at="2026-01-01T00:00:00+00:00",
                    last_value_usd=10000.0, last_value_at="2026-06-01T00:00:00+00:00",
                    last_uncollected_usd=None, last_rebalanced_at=None):
    db.execute(
        """
        INSERT INTO maxfi_positions (
            id, chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, last_scan_at,
            last_value_usd, last_value_at, last_uncollected_usd, last_rebalanced_at
        ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, 3000, 'open', ?, 'chain', ?, ?, ?, ?, ?)
        """,
        (position_id, chain, WALLET, str(position_id), pool_address, token0, token1,
         first_seen_at, first_seen_at, last_value_usd, last_value_at, last_uncollected_usd,
         last_rebalanced_at),
    )
    db.commit()


def _seed_claim(db, position_id, claimed_at, proceeds_usd):
    db.execute(
        """
        INSERT INTO maxfi_claims (position_id, claimed_at, proceeds_usd, set_at, set_by)
        VALUES (?, ?, ?, '2026-01-01T00:00:00+00:00', 'system')
        """,
        (position_id, claimed_at, proceeds_usd),
    )
    db.commit()


def _seed_catalogue_pool(db, chain="base", pool_address=POOL_A, token0=VOLATILE_TOKEN,
                          token1=BASE_ETH_ANCHOR, sym0="VOLT", sym1="ETH",
                          ts="2026-01-01T00:00:00+00:00"):
    db.execute(
        """
        INSERT INTO maxfi_catalogue_pools (
          chain, pool_address, token0_address, token1_address,
          token0_symbol, token1_symbol, fee_tier, position_count,
          first_seen_at, last_seen_at, last_enumerated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 3000, 1, ?, ?, ?)
        """,
        (chain, pool_address, token0, token1, sym0, sym1, ts, ts, ts),
    )
    db.commit()


def _seed_metrics(db, chain="base", pool_address=POOL_A, liquidity_usd=500000.0,
                   volume_h24=100000.0, volume_h6=25000.0, fetched_at="2026-06-10T00:00:00+00:00"):
    db.execute(
        """
        INSERT INTO maxfi_pool_metrics (
          chain, pool_address, price_usd, liquidity_usd, volume_h24,
          volume_h6, volume_h1, price_change_h24, fetched_at
        ) VALUES (?, ?, 1.0, ?, ?, ?, 1000.0, 0.5, ?)
        """,
        (chain, pool_address, liquidity_usd, volume_h24, volume_h6, fetched_at),
    )
    db.commit()


def _seed_token_daily(db, chain="base", address=VOLATILE_TOKEN, date="2026-06-10", close_usd=1.0,
                       source_pool_address=POOL_A, fetched_at="2026-06-10T00:00:00+00:00"):
    db.execute(
        """
        INSERT INTO maxfi_token_daily (
          chain, address, date, close_usd, source_pool_address, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (chain, address.lower(), date, close_usd, source_pool_address, fetched_at),
    )
    db.commit()


def test_advisor_route_happy_path_position_and_entry_candidate(client, advisor_db):
    # The route stamps as_of from the REAL current time (datetime.now), so
    # every date fixture here is computed relative to it, not hardcoded.
    # Phase E v1 item 1: the verdict path now reads completed candles only,
    # so this fixture's two rows are both pre-today (today-8, today-1) - a
    # today row here would have collapsed latest/base onto the same point
    # and silently stopped exercising a real 7-day trend. NOTE: (today-14,
    # today-7) does NOT work here - price_change_pct's base search targets
    # (as_of - 7) = today-7 directly, so with as_of=today those two dates
    # collapse onto the SAME row (today-7) as both latest and base,
    # degenerating to a 0.0 same-point comparison. (today-8, today-1) keeps
    # latest and base on two different rows.
    now = datetime.now(timezone.utc)
    today = now.date()
    _seed_position(advisor_db, 1, first_seen_at=(now - timedelta(days=40)).isoformat())
    _seed_claim(advisor_db, 1, (now - timedelta(days=2)).isoformat(), 20.0)
    _seed_catalogue_pool(advisor_db)
    _seed_metrics(advisor_db)
    # Two daily rows ~7d apart so decay math has something to work with.
    _seed_token_daily(advisor_db, date=(today - timedelta(days=8)).isoformat(), close_usd=1.2)
    _seed_token_daily(advisor_db, date=(today - timedelta(days=1)).isoformat(), close_usd=1.0)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    body = r.get_json()

    assert "as_of" in body
    assert body["constants"]["multiplier"] == ma.ADVISOR_DECAY_MULTIPLIER
    assert body["constants"]["window_days"] == ma.ADVISOR_WINDOW_DAYS
    assert body["constants"]["min_days_open"] == ma.ADVISOR_MIN_DAYS_OPEN

    assert len(body["positions"]) == 1
    pos = body["positions"][0]
    assert pos["id"] == 1
    assert pos["chain"] == "base"
    assert pos["pool_address"] == POOL_A
    assert pos["symbols"] == {"token0": "VOLT", "token1": "ETH"}
    assert pos["current_value_usd"] == 10000.0
    assert "uncollected_unavailable" in pos["data_flags"]
    assert pos["verdict"] in ("HOLD", "CLOSE")
    assert pos["days_open"] is not None
    assert pos["pct_7d"] is not None

    assert len(body["entry_candidates"]) == 1
    cand = body["entry_candidates"][0]
    assert cand["chain"] == "base"
    assert cand["pool_address"] == POOL_A
    assert cand["fee_apr_est_pct"] is not None
    assert cand["tvl_source"] == "dexscreener_liquidity_proxy"
    assert cand["downtrend_gate"]["blocked"] in (True, False, None)
    assert cand["volume_mult_source"] == "same_snapshot_h6x4_vs_h24"


def test_advisor_route_anchor_unresolved_flags_position(client, advisor_db):
    # Both sides of the pool are registered anchors -> volatile side
    # cannot be resolved.
    base_usdc_anchor = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    _seed_position(advisor_db, 1, token0=BASE_ETH_ANCHOR, token1=base_usdc_anchor)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    body = r.get_json()

    pos = body["positions"][0]
    assert "volatile_side_unresolved" in pos["flags"]
    assert pos["verdict"] == "insufficient_data"


def test_advisor_route_no_positions_or_pools_returns_empty_lists(client, advisor_db):
    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    body = r.get_json()
    assert body["positions"] == []
    assert body["entry_candidates"] == []


def test_advisor_route_catalogue_pool_without_metrics_still_appears(client, advisor_db):
    _seed_catalogue_pool(advisor_db)
    # No maxfi_pool_metrics row seeded - LEFT JOIN should still surface it.

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    body = r.get_json()

    assert len(body["entry_candidates"]) == 1
    cand = body["entry_candidates"][0]
    assert cand["liquidity_usd"] is None
    assert cand["fee_apr_est_pct"] is None
    assert cand["metrics_fetched_at"] is None


# ── Phase E v1.3: liquidity display floor ────────────────────────────────

def test_advisor_route_below_liquidity_floor_true_for_thin_pool(client, advisor_db):
    _seed_catalogue_pool(advisor_db)
    _seed_metrics(advisor_db, liquidity_usd=5000.0)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    cand = r.get_json()["entry_candidates"][0]
    assert cand["liquidity_usd"] == pytest.approx(5000.0)
    assert cand["below_liquidity_floor"] is True
    # Display-only: the score itself is untouched by the flag.
    assert cand["fee_apr_est_pct"] is not None
    assert cand["entry_score"] is not None


def test_advisor_route_below_liquidity_floor_false_for_healthy_pool(client, advisor_db):
    _seed_catalogue_pool(advisor_db)
    _seed_metrics(advisor_db, liquidity_usd=50000.0)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    cand = r.get_json()["entry_candidates"][0]
    assert cand["liquidity_usd"] == pytest.approx(50000.0)
    assert cand["below_liquidity_floor"] is False


def test_advisor_route_below_liquidity_floor_exactly_at_constant_is_not_below(client, advisor_db):
    # Strictness: exactly $10,000 is NOT below the floor (strict <).
    _seed_catalogue_pool(advisor_db)
    _seed_metrics(advisor_db, liquidity_usd=ma.ADVISOR_ENTRY_LIQUIDITY_FLOOR_USD)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    cand = r.get_json()["entry_candidates"][0]
    assert cand["liquidity_usd"] == pytest.approx(10000.0)
    assert cand["below_liquidity_floor"] is False


def test_advisor_route_below_liquidity_floor_none_when_liquidity_unknown(client, advisor_db):
    # No maxfi_pool_metrics row at all -> liquidity_usd is None -> the flag
    # stays None too (unknown stays unknown, never coerced to a boolean).
    _seed_catalogue_pool(advisor_db)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    cand = r.get_json()["entry_candidates"][0]
    assert cand["liquidity_usd"] is None
    assert cand["below_liquidity_floor"] is None
    assert cand["fee_apr_est_pct"] is None
    assert "downtrend_gate" in cand


# ── route: C1.1 last_uncollected_usd (commit 2 of 2) ───────────────────────
#
# All three seed a position with no claims and first_seen_at 5 days ago, so
# with no claims uncollected_accrual_days == days_open == 5, which is both
# >= ADVISOR_MIN_DAYS_OPEN (3.0, avoids "too_young") and < ADVISOR_WINDOW_DAYS
# (7, so window_earnings_usd's accrual_days < window_days branch adds the
# FULL uncollected_usd, not a prorated fraction) - lifetime_earned_usd and
# window_earned_usd should therefore both equal last_uncollected_usd exactly
# when it is a real number, and 0.0 when NULL.

def _seed_for_uncollected_case(db, last_uncollected_usd):
    now = datetime.now(timezone.utc)
    today = now.date()
    _seed_position(
        db, 1, first_seen_at=(now - timedelta(days=5)).isoformat(),
        last_uncollected_usd=last_uncollected_usd,
    )
    _seed_catalogue_pool(db)
    _seed_token_daily(db, date=(today - timedelta(days=7)).isoformat(), close_usd=1.2)
    _seed_token_daily(db, date=today.isoformat(), close_usd=1.0)


def test_advisor_route_null_uncollected_flags_unavailable_and_inputs_zero(client, advisor_db):
    _seed_for_uncollected_case(advisor_db, last_uncollected_usd=None)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]

    assert "uncollected_unavailable" in pos["data_flags"]
    assert pos["lifetime_earned_usd"] == pytest.approx(0.0)
    assert pos["window_earned_usd"] == pytest.approx(0.0)


def test_advisor_route_zero_uncollected_drops_flag(client, advisor_db):
    _seed_for_uncollected_case(advisor_db, last_uncollected_usd=0.0)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]

    assert "uncollected_unavailable" not in pos["data_flags"]
    assert pos["lifetime_earned_usd"] == pytest.approx(0.0)
    assert pos["window_earned_usd"] == pytest.approx(0.0)


def test_advisor_route_positive_uncollected_flows_into_earnings(client, advisor_db):
    _seed_for_uncollected_case(advisor_db, last_uncollected_usd=42.5)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]

    assert "uncollected_unavailable" not in pos["data_flags"]
    assert pos["lifetime_earned_usd"] == pytest.approx(42.5)
    assert pos["window_earned_usd"] == pytest.approx(42.5)


# ── route: C1.2 accrual anchor = max(last_claim_at, last_rebalanced_at) ────
#
# first_seen_at is fixed 20 days ago in every case here (comfortably past
# ADVISOR_MIN_DAYS_OPEN=3.0, and outside ADVISOR_WINDOW_DAYS=7 so a fallback
# to it is distinguishable from an anchor inside the window). uncollected_usd
# is a fixed 70.0. window_earnings_usd's proration rule means ANY accrual
# anchor within the 7-day window yields the FULL 70.0 (min(window_days,
# accrual_days) == accrual_days when accrual_days <= window_days, so the
# ratio is 1) - so "does the right anchor win" is provable by picking one
# candidate at 2 days ago (inside window -> full 70.0) against another at 20
# days ago or absent (outside window / fallback to first_seen_at -> a
# prorated ~24.5 = 70 * 7/20). Claims here carry proceeds_usd=0.0 so they
# set last_claim_at without adding their own amount to window_earned_usd,
# isolating the proration signal to which anchor was selected. No
# catalogue/token-daily seeding needed - window_earned_usd/lifetime_earned_usd
# are computed independently of the flags/verdict machinery that needs those.

UNCOLLECTED_FOR_ANCHOR_CASES = 70.0
FIRST_SEEN_DAYS_AGO_FOR_ANCHOR_CASES = 20
FALLBACK_PRORATED_USD = UNCOLLECTED_FOR_ANCHOR_CASES * 7 / FIRST_SEEN_DAYS_AGO_FOR_ANCHOR_CASES


def _seed_lineage(db, arriving_position_id, created_at, departing_position_id=999,
                   split_group_id="test-split", arriving_current_value_usd=100.0):
    db.execute(
        """
        INSERT INTO maxfi_position_lineage
            (departing_position_id, arriving_position_id, split_group_id,
             arriving_current_value_usd, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (departing_position_id, arriving_position_id, split_group_id,
         arriving_current_value_usd, created_at),
    )
    db.commit()


def _seed_for_anchor_case(db, claim_days_ago=None, rebalanced_days_ago=None,
                           rebalanced_at_raw=None, lineage_days_ago=None):
    now = datetime.now(timezone.utc)
    if rebalanced_at_raw is not None:
        last_rebalanced_at = rebalanced_at_raw
    elif rebalanced_days_ago is not None:
        last_rebalanced_at = (now - timedelta(days=rebalanced_days_ago)).isoformat()
    else:
        last_rebalanced_at = None
    _seed_position(
        db, 1, first_seen_at=(now - timedelta(days=FIRST_SEEN_DAYS_AGO_FOR_ANCHOR_CASES)).isoformat(),
        last_uncollected_usd=UNCOLLECTED_FOR_ANCHOR_CASES,
        last_rebalanced_at=last_rebalanced_at,
    )
    if claim_days_ago is not None:
        _seed_claim(db, 1, (now - timedelta(days=claim_days_ago)).isoformat(), 0.0)
    if lineage_days_ago is not None:
        _seed_lineage(db, 1, (now - timedelta(days=lineage_days_ago)).isoformat())


def test_advisor_route_anchor_claim_only_uses_claim_time(client, advisor_db):
    _seed_for_anchor_case(advisor_db, claim_days_ago=2)  # inside window, no rebalance

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]
    assert pos["window_earned_usd"] == pytest.approx(UNCOLLECTED_FOR_ANCHOR_CASES)


def test_advisor_route_anchor_rebalance_only_uses_rebalance_time(client, advisor_db):
    _seed_for_anchor_case(advisor_db, rebalanced_days_ago=2)  # inside window, no claim

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]
    assert pos["window_earned_usd"] == pytest.approx(UNCOLLECTED_FOR_ANCHOR_CASES)


def test_advisor_route_anchor_prefers_rebalance_when_later(client, advisor_db):
    # Claim far outside the window, rebalance inside it - max() must pick
    # the rebalance, not just "whichever exists first" or the claim alone.
    _seed_for_anchor_case(advisor_db, claim_days_ago=20, rebalanced_days_ago=2)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]
    assert pos["window_earned_usd"] == pytest.approx(UNCOLLECTED_FOR_ANCHOR_CASES)


def test_advisor_route_anchor_prefers_claim_when_later(client, advisor_db):
    # Rebalance far outside the window, claim inside it - proves the max()
    # doesn't just always prefer the rebalance side.
    _seed_for_anchor_case(advisor_db, claim_days_ago=2, rebalanced_days_ago=20)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]
    assert pos["window_earned_usd"] == pytest.approx(UNCOLLECTED_FOR_ANCHOR_CASES)


def test_advisor_route_anchor_falls_back_to_first_seen_at_when_neither(client, advisor_db):
    _seed_for_anchor_case(advisor_db)  # no claim, no rebalance

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]
    assert pos["lifetime_earned_usd"] == pytest.approx(UNCOLLECTED_FOR_ANCHOR_CASES)
    assert pos["window_earned_usd"] == pytest.approx(FALLBACK_PRORATED_USD, rel=1e-2)


def test_advisor_route_malformed_last_rebalanced_at_treated_as_none(client, advisor_db):
    # Malformed string -> parse_utc returns None -> treated exactly like no
    # rebalance at all (falls back to first_seen_at here, since no claim
    # either) - never an exception, never a 500.
    _seed_for_anchor_case(advisor_db, rebalanced_at_raw="not-a-timestamp")

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]
    assert pos["window_earned_usd"] == pytest.approx(FALLBACK_PRORATED_USD, rel=1e-2)


# ── route: C1.3 accrual anchor adds maxfi_position_lineage.created_at ──────
#
# Same signal technique as the C1.2 anchor tests above: an anchor inside the
# 7-day window yields the FULL 70.0 uncollected figure, one outside it (or
# the first_seen_at fallback, fixed 20 days back) yields the prorated
# ~24.5 - so "did lineage win/lose the max()" is provable the same way
# "did rebalance win/lose" was.

def test_advisor_route_anchor_lineage_only_uses_lineage_time(client, advisor_db):
    _seed_for_anchor_case(advisor_db, lineage_days_ago=2)  # inside window, no claim/rebalance

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]
    assert pos["window_earned_usd"] == pytest.approx(UNCOLLECTED_FOR_ANCHOR_CASES)


def test_advisor_route_anchor_prefers_claim_when_later_than_lineage(client, advisor_db):
    # Lineage far outside the window, claim inside it - max() must pick the
    # claim, not just "whichever candidate exists first."
    _seed_for_anchor_case(advisor_db, lineage_days_ago=20, claim_days_ago=2)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]
    assert pos["window_earned_usd"] == pytest.approx(UNCOLLECTED_FOR_ANCHOR_CASES)


def test_advisor_route_anchor_prefers_rebalance_when_later_than_lineage(client, advisor_db):
    # Lineage far outside the window, rebalance inside it - proves lineage
    # doesn't unconditionally win just by being present.
    _seed_for_anchor_case(advisor_db, lineage_days_ago=20, rebalanced_days_ago=2)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]
    assert pos["window_earned_usd"] == pytest.approx(UNCOLLECTED_FOR_ANCHOR_CASES)


def test_advisor_route_anchor_prefers_lineage_when_latest(client, advisor_db):
    # Claim and rebalance both far outside the window, lineage inside it -
    # lineage must win when it is genuinely the latest candidate.
    _seed_for_anchor_case(
        advisor_db, lineage_days_ago=2, claim_days_ago=20, rebalanced_days_ago=20,
    )

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]
    assert pos["window_earned_usd"] == pytest.approx(UNCOLLECTED_FOR_ANCHOR_CASES)


def test_advisor_route_anchor_no_lineage_row_falls_back_unchanged(client, advisor_db):
    # No claim, no rebalance, no lineage row at all (the pre-lineage-table
    # gap-window case) - behavior must be byte-identical to the pre-C1.3
    # fallback: first_seen_at, same prorated figure as before this change.
    _seed_for_anchor_case(advisor_db)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]
    assert pos["lifetime_earned_usd"] == pytest.approx(UNCOLLECTED_FOR_ANCHOR_CASES)
    assert pos["window_earned_usd"] == pytest.approx(FALLBACK_PRORATED_USD, rel=1e-2)


def test_advisor_route_anchor_multiple_lineage_rows_uses_max(client, advisor_db):
    # Two lineage rows for the SAME arriving_position_id with two DIFFERENT
    # created_at values - production always binds one identical value to
    # every row in a split group, but the schema permits more than one row
    # per arriving position (no UNIQUE constraint - see maxfi_schema.py),
    # so this proves the route's MAX(created_at) picks the later one rather
    # than an arbitrary row, defensively, even though today's write path
    # never actually produces divergent values.
    now = datetime.now(timezone.utc)
    _seed_position(
        advisor_db, 1,
        first_seen_at=(now - timedelta(days=FIRST_SEEN_DAYS_AGO_FOR_ANCHOR_CASES)).isoformat(),
        last_uncollected_usd=UNCOLLECTED_FOR_ANCHOR_CASES,
    )
    _seed_lineage(advisor_db, 1, (now - timedelta(days=20)).isoformat(), departing_position_id=997)
    _seed_lineage(advisor_db, 1, (now - timedelta(days=2)).isoformat(), departing_position_id=998)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]
    assert pos["window_earned_usd"] == pytest.approx(UNCOLLECTED_FOR_ANCHOR_CASES)


# ── Phase E v1 item 1: verdict stabilizer, candle-half ──────────────────────
# The position/verdict path now reads the last COMPLETED daily candle only -
# a route-local filter at the daily_rows lookup, applied only in the position
# loop. The entry-candidates loop is untouched by design and still consumes
# today's row. as_of_utc itself is never shifted, so days_open and the claims
# window are unaffected by the filter.

def test_advisor_route_today_row_excluded_from_verdict_path(client, advisor_db):
    # Mild decline through the last completed candle (today-8 -> today-1),
    # then a sharp drop recorded in today's still-forming row. Including
    # today's row would read a steep decay (-50% / 7d, decay 7.14%/day);
    # the completed-candles-only fix must read the milder, pre-today trend
    # (-10% / 7d, decay ~1.43%/day) instead. NOTE: (today-14, today-7) does
    # NOT work for the completed-only reading here - price_change_pct's
    # base search targets (as_of - 7) = today-7 directly, so with as_of=
    # today those two dates would collapse onto the SAME row as both
    # latest and base once today is filtered out, degenerating to a
    # same-point 0.0 rather than a real trend.
    now = datetime.now(timezone.utc)
    today = now.date()
    _seed_position(advisor_db, 1, first_seen_at=(now - timedelta(days=40)).isoformat())
    _seed_token_daily(advisor_db, date=(today - timedelta(days=8)).isoformat(), close_usd=1.0)
    _seed_token_daily(advisor_db, date=(today - timedelta(days=1)).isoformat(), close_usd=0.9)
    _seed_token_daily(advisor_db, date=today.isoformat(), close_usd=0.5)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]

    assert pos["pct_7d"] == pytest.approx(-10.0)
    assert pos["decay_pct_day"] == pytest.approx(1.4285714285714284)


def test_advisor_route_entry_candidates_still_see_today_row(client, advisor_db):
    # Deliberate-scope pin: the SAME today-inclusive row set as the verdict
    # test above, but read through the entry-candidates path. Unlike the
    # position path, entry_candidates must still see today's partial candle -
    # the fix is position-loop-only, never the shared token_daily_by_key
    # lookup the entry loop reads from.
    today = datetime.now(timezone.utc).date()
    _seed_catalogue_pool(advisor_db)
    _seed_metrics(advisor_db)
    _seed_token_daily(advisor_db, date=(today - timedelta(days=14)).isoformat(), close_usd=1.0)
    _seed_token_daily(advisor_db, date=(today - timedelta(days=7)).isoformat(), close_usd=1.0)
    _seed_token_daily(advisor_db, date=today.isoformat(), close_usd=0.5)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    cand = r.get_json()["entry_candidates"][0]

    assert cand["downtrend_gate"]["pct_7d"] == pytest.approx(-50.0)


def test_advisor_route_as_of_utc_not_shifted_for_claims_and_days_open(client, advisor_db):
    # as_of decoupling pin: a claim timestamped a couple hours ago (today,
    # the still-partial day) must still count in window_earned_usd, and
    # days_open must reflect the real now - proving the candle-half filter
    # never touches advisor_input["as_of_utc"] itself. A shifted as_of_utc
    # (e.g. rolled back to yesterday) would exclude this claim and understate
    # days_open by about a day.
    now = datetime.now(timezone.utc)
    _seed_position(advisor_db, 1, first_seen_at=(now - timedelta(days=10, hours=1)).isoformat())
    _seed_claim(advisor_db, 1, (now - timedelta(hours=2)).isoformat(), 15.0)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]

    assert pos["days_open"] == pytest.approx(10 + 1 / 24, abs=0.05)
    assert pos["window_earned_usd"] == pytest.approx(15.0, rel=1e-3)


def test_advisor_route_token_with_only_todays_row_is_insufficient_data(client, advisor_db):
    # Young-token rider: a token whose ONLY maxfi_token_daily row is today's
    # still-forming candle has NO completed candle at all. Post-filter the
    # verdict path sees an empty daily_rows list - the existing
    # no_token_history floor must fire (insufficient_data), never a
    # synthetic/fabricated trend value.
    now = datetime.now(timezone.utc)
    today = now.date()
    _seed_position(advisor_db, 1, first_seen_at=(now - timedelta(days=40)).isoformat())
    _seed_token_daily(advisor_db, date=today.isoformat(), close_usd=1.0)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]

    assert pos["pct_7d"] is None
    assert "no_token_history" in pos["flags"]
    assert pos["verdict"] == "insufficient_data"


def test_advisor_route_completed_only_history_unchanged_by_filter(client, advisor_db):
    # No-op case: a token with two already-completed candles (today-8,
    # today-1) and no today row at all. The filter drops nothing here, so
    # this pins that completed-only history reads exactly as it always has.
    now = datetime.now(timezone.utc)
    today = now.date()
    _seed_position(advisor_db, 1, first_seen_at=(now - timedelta(days=40)).isoformat())
    _seed_token_daily(advisor_db, date=(today - timedelta(days=8)).isoformat(), close_usd=1.3)
    _seed_token_daily(advisor_db, date=(today - timedelta(days=1)).isoformat(), close_usd=1.0)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]

    assert pos["pct_7d"] == pytest.approx(-23.076923076923077)
    assert pos["decay_pct_day"] == pytest.approx(3.2967032967032965)


# ── Grid surgery session 1: last_completed_close_usd (crash badge feed) ─────

def test_advisor_route_last_completed_close_excludes_today_row(client, advisor_db):
    # Rows at (today-8), (today-1), and today - the v1.1 filter excludes
    # today's still-forming candle from the verdict path, so the newest
    # SURVIVING row is (today-1); last_completed_close_usd must reflect that
    # close, not today's.
    now = datetime.now(timezone.utc)
    today = now.date()
    _seed_position(advisor_db, 1, first_seen_at=(now - timedelta(days=40)).isoformat())
    _seed_token_daily(advisor_db, date=(today - timedelta(days=8)).isoformat(), close_usd=1.3)
    _seed_token_daily(advisor_db, date=(today - timedelta(days=1)).isoformat(), close_usd=1.0)
    _seed_token_daily(advisor_db, date=today.isoformat(), close_usd=0.5)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]

    assert pos["last_completed_close_usd"] == pytest.approx(1.0)


def test_advisor_route_last_completed_close_none_when_only_todays_row(client, advisor_db):
    # Same young-token rider fixture as the v1.1 insufficient_data test: a
    # token whose ONLY row is today's has no completed candle at all, so
    # last_completed_close_usd must be None - never a synthetic/fabricated
    # value - and the existing insufficient_data behavior is unchanged.
    now = datetime.now(timezone.utc)
    today = now.date()
    _seed_position(advisor_db, 1, first_seen_at=(now - timedelta(days=40)).isoformat())
    _seed_token_daily(advisor_db, date=today.isoformat(), close_usd=1.0)

    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]

    assert pos["last_completed_close_usd"] is None
    assert pos["pct_7d"] is None
    assert "no_token_history" in pos["flags"]
    assert pos["verdict"] == "insufficient_data"
