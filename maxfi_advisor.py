"""LP Advisor Phase C1: pure verdict module for MaxFi LP positions.

No network, no DB, no Flask - every function here is pure, taking plain
values/dicts and returning plain values/dicts. The route
(GET /api/maxfi/advisor in web_portfolio.py) does all I/O and hands this
module already-assembled inputs.

VERDICT LOGIC (locked spec, Glenn): compares two per-position numbers -
run_rate_7d_pct_day (what the position paid over the LAST 7 DAYS, as %/day
of current position value) against decay_pct_day (the volatile token's 7d
price trend expressed as %/day LOST, clamped at a minimum of 0 - a flat or
rising token costs 0/day). CLOSE when run_rate_7d < ADVISOR_DECAY_MULTIPLIER
x decay; equality or better is HOLD. Lifetime run-rate is computed and
reported as CONTEXT ONLY - it never enters the verdict. There is NO
predictive/directional TA anywhere in this module, and sunk cost (initial
cost basis, unrealized P/L) is never a verdict input. insufficient_data is
returned - never a fabricated verdict - whenever an input fails a floor.
"""

from datetime import datetime, timedelta

from maxfi_pooldata import price_change_pct, volume_trend_ratio, downtrend_gate  # noqa: F401 - downtrend_gate re-exported for route convenience

# Judgment-set buffer (measurement noise + opportunity cost) - NOT derived
# from data. Tunable later against resolution data (comparing verdicts
# issued against what a position actually went on to do).
ADVISOR_DECAY_MULTIPLIER = 2.0

# The run-rate window: "the last 7 days" per the locked spec.
ADVISOR_WINDOW_DAYS = 7

# Documented assumption: a position younger than this has too little
# history for a 7-day run-rate to mean anything yet - insufficient_data
# rather than a noisy/misleading number.
ADVISOR_MIN_DAYS_OPEN = 3.0

# Provenance label for entry_volume_multiplier's feed - a route including
# an entry_volume_multiplier result in a response dict should carry this
# string alongside it, so the approximation is always self-labeled.
ENTRY_VOLUME_MULTIPLIER_SOURCE = "same_snapshot_h6x4_vs_h24"

# Provenance label for entry_score's TVL input - liquidity_usd (DexScreener)
# is a proxy for true in-range Uniswap V3 TVL, not verified equivalent.
ENTRY_SCORE_TVL_SOURCE = "dexscreener_liquidity_proxy"


def run_rate_pct_per_day(earned_usd, days, current_value_usd):
    """Earnings rate as %/day of current position value:
    (earned_usd / days) / current_value_usd * 100.

    None-safe: returns None when days is None or <= 0, current_value_usd
    is None or <= 0, or earned_usd is None. Never raises."""
    if earned_usd is None:
        return None
    if days is None or days <= 0:
        return None
    if current_value_usd is None or current_value_usd <= 0:
        return None
    return (earned_usd / days) / current_value_usd * 100


def window_earnings_usd(claims, uncollected_usd, uncollected_accrual_days,
                         as_of_utc, window_days=ADVISOR_WINDOW_DAYS):
    """Total USD earned by a position within the last `window_days` days
    ending at as_of_utc: realized claims that fall inside the window, plus
    a linearly-prorated share of currently-uncollected fees.

    claims: an iterable of (iso_utc_ts, usd) tuples - a claim is counted
    when its timestamp falls in (as_of_utc - window_days, as_of_utc] (a
    claim exactly ON as_of_utc counts; one exactly window_days before it
    does not). A claim with usd=None or an unparseable timestamp is
    skipped, never raised on.

    uncollected_accrual_days is how many days the CURRENT uncollected-fee
    balance has been accruing - days since the last claim, or days since
    the position opened if it has never been claimed. The prorated share
    is uncollected_usd * min(window_days, uncollected_accrual_days) /
    uncollected_accrual_days: if fees have been accruing for less than the
    window, ALL of the current uncollected balance is attributable to the
    window (it could not have accrued before that); otherwise only the
    window's fraction of the accrual period is counted. accrual_days <= 0
    (or None) adds the FULL uncollected_usd rather than dividing by zero -
    documented as a deliberate edge case, not a fallback to guess at.

    LINEAR-ACCRUAL ATTRIBUTION IS A DOCUMENTED ASSUMPTION: fees do not
    actually accrue at a constant rate (they track pool volume), but a
    constant-rate approximation is the only estimate available without a
    fee-growth history table, which does not exist yet.

    Always returns a float (never None) - a position with no claims and no
    uncollected balance in the window simply earned 0.0."""
    total = 0.0
    window_start = as_of_utc - timedelta(days=window_days)
    for iso_ts, usd in claims:
        if usd is None:
            continue
        try:
            ts = datetime.fromisoformat(iso_ts)
        except (TypeError, ValueError):
            continue
        if window_start < ts <= as_of_utc:
            total += usd

    if uncollected_usd is None:
        uncollected_usd = 0.0
    if uncollected_accrual_days is None or uncollected_accrual_days <= 0:
        prorated = uncollected_usd
    else:
        prorated = uncollected_usd * min(window_days, uncollected_accrual_days) / uncollected_accrual_days

    return total + prorated


def decay_pct_per_day(daily_rows, as_of_date):
    """The volatile token's price decay, expressed as %/day lost.

    Uses price_change_pct(daily_rows, as_of_date, 7) and (..., 30) - the
    Phase A2 trend primitive over (date_str, close_usd) rows. pct_30d is
    CONTEXT ONLY and never enters the verdict.

    decay_raw_pct_day = -(pct_7d / 7.0) - the 7-day price change spread
    evenly over 7 days, negated so a FALLING price gives a POSITIVE decay
    figure ("%/day lost"). decay_pct_day = max(0.0, decay_raw_pct_day) -
    clamped at a minimum of 0: a flat or RISING token costs the position
    nothing in decay terms, never a negative "cost" (Glenn decision).

    pct_7d is None (insufficient token-daily history) -> decay_pct_day and
    decay_raw_pct_day are both None too; pct_30d is still reported
    whenever it is independently available.

    Returns {"pct_7d", "pct_30d", "decay_pct_day", "decay_raw_pct_day"}."""
    pct_7d = price_change_pct(daily_rows, as_of_date, 7)
    pct_30d = price_change_pct(daily_rows, as_of_date, 30)

    if pct_7d is None:
        decay_raw_pct_day = None
        decay_pct_day = None
    else:
        decay_raw_pct_day = -(pct_7d / 7.0)
        decay_pct_day = max(0.0, decay_raw_pct_day)

    return {
        "pct_7d": pct_7d,
        "pct_30d": pct_30d,
        "decay_pct_day": decay_pct_day,
        "decay_raw_pct_day": decay_raw_pct_day,
    }


def verdict(run_rate_7d, decay_pct_day, multiplier=ADVISOR_DECAY_MULTIPLIER):
    """The verdict rule itself: CLOSE when run_rate_7d < multiplier x
    decay_pct_day (strict inequality - equality is HOLD); insufficient_data
    when either input is None (a run_rate of exactly 0.0 is a VALID input,
    never treated as missing - only a real None is).

    Returns {"verdict": "HOLD"|"CLOSE"|"insufficient_data",
    "threshold_pct_day", "margin_pct_day"} - both derived fields are None
    under insufficient_data."""
    if run_rate_7d is None or decay_pct_day is None:
        return {"verdict": "insufficient_data", "threshold_pct_day": None, "margin_pct_day": None}

    threshold_pct_day = multiplier * decay_pct_day
    margin_pct_day = run_rate_7d - threshold_pct_day
    verdict_str = "CLOSE" if run_rate_7d < threshold_pct_day else "HOLD"

    return {
        "verdict": verdict_str,
        "threshold_pct_day": threshold_pct_day,
        "margin_pct_day": margin_pct_day,
    }


def advise_position(pos):
    """Full per-position verdict assembly. `pos` is a plain dict with keys:
    current_value_usd, uncollected_usd, uncollected_accrual_days, claims
    (iterable of (iso_utc_ts, usd)), first_seen_at_utc (datetime, UTC),
    as_of_utc (datetime, UTC), daily_rows (the volatile token's
    (date_str, close_usd) rows), volatile_side_resolved (bool).

    FLOORS - any of these fires insufficient_data regardless of what the
    underlying numbers happen to compute to, named in the returned `flags`
    list (a position can fail more than one at once):
      - "too_young": days_open is unknown or < ADVISOR_MIN_DAYS_OPEN.
      - "no_current_value": current_value_usd is None or <= 0.
      - "no_token_history": the volatile token's 7d price change (pct_7d)
        could not be computed from daily_rows.
      - "volatile_side_unresolved": volatile_side_resolved is falsy.

    Lifetime run-rate (run_rate_lifetime_pct_day) is computed from ALL
    claims plus the FULL uncollected balance (never prorated) over the
    position's entire days_open - reported as CONTEXT ONLY, never fed into
    the verdict. Sunk cost (initial cost basis, unrealized P/L) is not an
    input anywhere in this function.

    Returns every intermediate: run_rate_7d_pct_day,
    run_rate_lifetime_pct_day, days_open, window_earned_usd,
    lifetime_earned_usd, pct_7d, pct_30d, decay_pct_day, decay_raw_pct_day,
    threshold_pct_day, margin_pct_day, verdict, flags."""
    current_value_usd = pos.get("current_value_usd")
    uncollected_usd = pos.get("uncollected_usd")
    uncollected_accrual_days = pos.get("uncollected_accrual_days")
    claims = list(pos.get("claims") or [])
    first_seen_at_utc = pos.get("first_seen_at_utc")
    as_of_utc = pos.get("as_of_utc")
    daily_rows = pos.get("daily_rows") or []
    volatile_side_resolved = pos.get("volatile_side_resolved")

    flags = []

    days_open = None
    if first_seen_at_utc is not None and as_of_utc is not None:
        days_open = (as_of_utc - first_seen_at_utc).total_seconds() / 86400.0

    if days_open is None or days_open < ADVISOR_MIN_DAYS_OPEN:
        flags.append("too_young")
    if current_value_usd is None or current_value_usd <= 0:
        flags.append("no_current_value")
    if not volatile_side_resolved:
        flags.append("volatile_side_unresolved")

    as_of_date = as_of_utc.date().isoformat() if as_of_utc is not None else None
    if as_of_date is not None:
        decay = decay_pct_per_day(daily_rows, as_of_date)
    else:
        decay = {"pct_7d": None, "pct_30d": None, "decay_pct_day": None, "decay_raw_pct_day": None}
    if decay["pct_7d"] is None:
        flags.append("no_token_history")

    lifetime_claims_total = sum(usd for _ts, usd in claims if usd is not None)
    lifetime_earned_usd = lifetime_claims_total + (uncollected_usd if uncollected_usd is not None else 0.0)
    run_rate_lifetime_pct_day = run_rate_pct_per_day(lifetime_earned_usd, days_open, current_value_usd)

    window_earned_usd = None
    run_rate_7d_pct_day = None
    if as_of_utc is not None and days_open is not None:
        window_earned_usd = window_earnings_usd(
            claims, uncollected_usd, uncollected_accrual_days, as_of_utc, ADVISOR_WINDOW_DAYS,
        )
        run_rate_days = min(ADVISOR_WINDOW_DAYS, days_open)
        run_rate_7d_pct_day = run_rate_pct_per_day(window_earned_usd, run_rate_days, current_value_usd)

    if flags:
        v = {"verdict": "insufficient_data", "threshold_pct_day": None, "margin_pct_day": None}
    else:
        v = verdict(run_rate_7d_pct_day, decay["decay_pct_day"])

    return {
        "run_rate_7d_pct_day": run_rate_7d_pct_day,
        "run_rate_lifetime_pct_day": run_rate_lifetime_pct_day,
        "days_open": days_open,
        "window_earned_usd": window_earned_usd,
        "lifetime_earned_usd": lifetime_earned_usd,
        "pct_7d": decay["pct_7d"],
        "pct_30d": decay["pct_30d"],
        "decay_pct_day": decay["decay_pct_day"],
        "decay_raw_pct_day": decay["decay_raw_pct_day"],
        "threshold_pct_day": v["threshold_pct_day"],
        "margin_pct_day": v["margin_pct_day"],
        "verdict": v["verdict"],
        "flags": flags,
    }


def entry_volume_multiplier(volume_h6, volume_h24):
    """Approximates a recent-vs-trailing volume trend from a SINGLE
    DexScreener snapshot: volume_h6 annualized to a 24h-equivalent rate
    (x4.0) compared against the actual volume_h24 via
    maxfi_pooldata.volume_trend_ratio.

    SAME-SNAPSHOT APPROXIMATION - a documented assumption, not a true
    recent-vs-trailing comparison (that would need two DIFFERENT snapshots
    taken 24h apart, i.e. a metrics-history table, which does not exist
    yet). A caller that surfaces this figure should label it with
    ENTRY_VOLUME_MULTIPLIER_SOURCE ("same_snapshot_h6x4_vs_h24") so the
    approximation is never presented as more than it is. This function's
    signature will not need to change when a metrics-history table
    eventually replaces the feed - only the caller's inputs would.

    Returns None if either input is None (volume_trend_ratio's own None/
    non-finite/non-positive-denominator guards apply beyond that)."""
    if volume_h6 is None or volume_h24 is None:
        return None
    return volume_trend_ratio(volume_h6 * 4.0, volume_h24)


def entry_score(volume_h24, fee_tier, liquidity_usd, volume_mult):
    """Pool entry score: a fee-APR estimate scaled by a volume-trend
    multiplier.

    fee_apr_est_pct = volume_h24 * (fee_tier / 1e6) / liquidity_usd * 365
    * 100 - fee_tier is the raw on-chain integer (e.g. 3000 = 0.3%,
    matching maxfi_positions/maxfi_catalogue_pools storage), so dividing
    by 1e6 gives the fraction.

    entry_score = fee_apr_est_pct * volume_mult. volume_mult=None is
    treated as 1.0 (neutral - neither boosts nor penalizes the estimate)
    and flagged "volume_trend_unavailable" in the returned `flags` list,
    rather than propagating None through the whole score.

    Any CORE input (volume_h24, fee_tier, liquidity_usd) that is None or
    <= 0 makes fee_apr_est_pct and entry_score both None - there is no
    meaningful fee-APR estimate for a pool with zero/unknown liquidity,
    volume, or fee tier.

    tvl_source is ALWAYS the literal ENTRY_SCORE_TVL_SOURCE
    ("dexscreener_liquidity_proxy") - liquidity_usd is DexScreener's
    liquidity figure, a proxy for true in-range Uniswap V3 TVL, not
    verified equivalent to it. Labeled on every call, not just when a
    score is actually produced, so a consumer can never lose track of
    what liquidity_usd actually is.

    Returns {"fee_apr_est_pct", "entry_score", "tvl_source", "flags"}."""
    flags = []
    if volume_mult is None:
        volume_mult = 1.0
        flags.append("volume_trend_unavailable")

    core_inputs = (volume_h24, fee_tier, liquidity_usd)
    if any(v is None or v <= 0 for v in core_inputs):
        return {
            "fee_apr_est_pct": None,
            "entry_score": None,
            "tvl_source": ENTRY_SCORE_TVL_SOURCE,
            "flags": flags,
        }

    fee_apr_est_pct = volume_h24 * (fee_tier / 1e6) / liquidity_usd * 365 * 100
    entry_score_val = fee_apr_est_pct * volume_mult

    return {
        "fee_apr_est_pct": fee_apr_est_pct,
        "entry_score": entry_score_val,
        "tvl_source": ENTRY_SCORE_TVL_SOURCE,
        "flags": flags,
    }
