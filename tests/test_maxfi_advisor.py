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


def test_verdict_run_rate_zero_with_positive_decay_closes():
    result = ma.verdict(0.0, 0.1)  # threshold = 0.2; 0.0 < 0.2 -> CLOSE
    assert result["verdict"] == "CLOSE"


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
                    last_value_usd=10000.0, last_value_at="2026-06-01T00:00:00+00:00"):
    db.execute(
        """
        INSERT INTO maxfi_positions (
            id, chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, last_scan_at,
            last_value_usd, last_value_at
        ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, 3000, 'open', ?, 'chain', ?, ?, ?)
        """,
        (position_id, chain, WALLET, str(position_id), pool_address, token0, token1,
         first_seen_at, first_seen_at, last_value_usd, last_value_at),
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
    now = datetime.now(timezone.utc)
    today = now.date()
    _seed_position(advisor_db, 1, first_seen_at=(now - timedelta(days=40)).isoformat())
    _seed_claim(advisor_db, 1, (now - timedelta(days=2)).isoformat(), 20.0)
    _seed_catalogue_pool(advisor_db)
    _seed_metrics(advisor_db)
    # Two daily rows ~7d apart so decay math has something to work with.
    _seed_token_daily(advisor_db, date=(today - timedelta(days=7)).isoformat(), close_usd=1.2)
    _seed_token_daily(advisor_db, date=today.isoformat(), close_usd=1.0)

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
