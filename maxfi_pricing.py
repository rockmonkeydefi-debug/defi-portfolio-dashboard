"""MaxFi position valuation — Phase D. PURE FUNCTIONS ONLY.

No RPC, no HTTP, no database, no scanner_settings.json reads, no clock
reads except where a timestamp arrives as an argument. Everything this
module needs is passed in by the caller (a web_portfolio.py route). This
is what makes it fully testable offline (see tests/test_maxfi_pricing.py).

Integer math stays integer until the final division: liquidity, feeGrowth
and sqrtPriceX96 are uint128/uint256 and Python ints are arbitrary
precision, so casting to float early is a silent correctness bug. The
uncollected-fee and liquidity->amounts on-chain math itself lives in
maxfi_math.py (fee_growth_inside/uncollected_fees/liquidity_to_amounts) —
this module's job is decimals adjustment (the "final division") and USD
conversion on top of that raw math.

A missing or failed price produces None, never 0.0 and never a silent
zero standing in for "unknown" — see value_position()/compute_performance().

KNOWN DIVERGENCE (Phase D.1) — collected-fee valuation vs. maxfi.tech:
maxfi.tech's own card values COLLECTED fees noticeably lower than this
module does. Reconciled against a live capture (position #757217, block
47938836): the card showed a collected figure implying roughly $20.52,
while current-price valuation of the same cumulativeFees0/1 gives $24.16 —
a 17.7% gap. Solving for a single WETH/STONKBROKER price pair that would
satisfy BOTH the card's total position value AND its collected figure
implies a pool rate of ~71048, a 2.1x disagreement with the pool's actual
slot0-derived rate of ~152386 at capture time. No single current-price pair
explains both numbers.

Conclusion: MaxFi appears to value collected fees at whatever price
prevailed WHEN they were collected, not at the current price. This is not
reproducible here — cumulativeFees0/1 (from the vault struct) are bare
token amounts with no accompanying timestamps, so the historical price at
each collection event is unrecoverable from chain state alone.
Current-price valuation (what this module does) is the defensible answer
available to us, not a bug to chase.

Direction: our figure reads HIGHER than MaxFi's own when the counterparty
(non-anchor) token has appreciated since the fees were collected, and would
read lower if it had depreciated instead.

Affected fields: collected_usd, total_earned_usd, usd_per_day, apr_percent
(all derive from collected_usd). NOT affected: current_value_usd,
uncollected_usd, or pnl_usd — P/L deliberately excludes collected fees
already (see compute_performance()), so this divergence never reaches P/L.
The valuation endpoint surfaces this via a "collected_valuation_basis":
"current_price" field on every priced position, so a future UI can label
the figure rather than leave the discrepancy unexplained on screen.
"""

import maxfi_math


def pool_price_token1_per_token0(sqrt_price_x96, decimals0, decimals1):
    """token1-per-token0 price from a pool's current sqrtPriceX96.

    Thin wrapper over maxfi_math.sqrt_price_x96_to_price(), which already
    does exactly this (Decimal-based squaring, one float cast at the end)
    — reused rather than reimplemented to avoid a second copy of the same
    math."""
    return maxfi_math.sqrt_price_x96_to_price(sqrt_price_x96, decimals0, decimals1)


def derive_usd_prices(token0, token1, anchor_side, anchor_usd_price, sqrt_price_x96,
                       decimals0, decimals1):
    """Derive the non-anchor side's USD price from the pool's current rate.

    anchor_side is 'token0' or 'token1'. token0/token1 (addresses or
    symbols — not used in the math, carried through only for error
    context) are address-sorted, not semantic: the anchor can legitimately
    sit on either side, so getting the inversion direction right matters
    more than it looks like it should. See tests/test_maxfi_pricing.py for
    both directions.

    price_t1_per_t0 = token1 per 1 token0.
      - If token0 is the anchor (price P0 known): 1 token0 = P0 USD, and
        1 token0 = price_t1_per_t0 token1, so 1 token1 = P0 / price_t1_per_t0.
      - If token1 is the anchor (price P1 known): 1 token1 = P1 USD, and
        price_t1_per_t0 token1 = 1 token0, so 1 token0 = price_t1_per_t0 * P1.

    Returns {"token0_usd": float|None, "token1_usd": float|None,
    "derived_side": str}. None (never 0.0) if the pool rate is degenerate
    (zero) and a division would otherwise be required.
    """
    if anchor_side not in ("token0", "token1"):
        raise ValueError(f"anchor_side must be 'token0' or 'token1', got {anchor_side!r}")
    if anchor_usd_price is None:
        return {"token0_usd": None, "token1_usd": None,
                "derived_side": "token1" if anchor_side == "token0" else "token0"}

    price_t1_per_t0 = pool_price_token1_per_token0(sqrt_price_x96, decimals0, decimals1)

    if anchor_side == "token0":
        derived_side = "token1"
        if price_t1_per_t0 <= 0:
            return {"token0_usd": anchor_usd_price, "token1_usd": None, "derived_side": derived_side}
        return {
            "token0_usd": anchor_usd_price,
            "token1_usd": anchor_usd_price / price_t1_per_t0,
            "derived_side": derived_side,
        }
    else:
        derived_side = "token0"
        return {
            "token0_usd": anchor_usd_price * price_t1_per_t0,
            "token1_usd": anchor_usd_price,
            "derived_side": derived_side,
        }


def value_position(liquidity, tick_lower, tick_upper, current_tick, sqrt_price_x96,
                    decimals0, decimals1, token0_usd, token1_usd,
                    uncollected0, uncollected1, collected0, collected1):
    """Value one position from decoded on-chain state plus resolved prices.

    liquidity/tick_lower/tick_upper/current_tick/sqrt_price_x96: decoded
    position/pool state (raw on-chain ints). decimals0/decimals1: token
    decimals. token0_usd/token1_usd: resolved USD prices, or None if
    pricing failed — every *_usd field derived from a None price is also
    None, never 0.0. uncollected0/uncollected1 and collected0/collected1
    are already decimals-adjusted human-unit token amounts (the caller
    computes these via maxfi_math.fee_growth_inside()/uncollected_fees()
    for uncollected, and from the vault's cumulativeFees0/1 for collected
    — both decimals-divided before being passed in here).

    Returns a dict with amount0/amount1, amount0_usd/amount1_usd,
    current_value_usd, uncollected0/uncollected1/uncollected_usd,
    collected0/collected1/collected_usd, and total_earned_usd
    (collected_usd + uncollected_usd — a display figure only, never
    folded into P/L, see compute_performance()).
    """
    amount0_raw, amount1_raw = maxfi_math.liquidity_to_amounts(
        liquidity, tick_lower, tick_upper, current_tick, sqrt_price_x96
    )
    amount0 = amount0_raw / (10 ** decimals0)
    amount1 = amount1_raw / (10 ** decimals1)

    have_prices = token0_usd is not None and token1_usd is not None

    amount0_usd = amount0 * token0_usd if token0_usd is not None else None
    amount1_usd = amount1 * token1_usd if token1_usd is not None else None
    current_value_usd = (
        amount0_usd + amount1_usd
        if amount0_usd is not None and amount1_usd is not None
        else None
    )

    uncollected_usd = (uncollected0 * token0_usd + uncollected1 * token1_usd) if have_prices else None
    collected_usd = (collected0 * token0_usd + collected1 * token1_usd) if have_prices else None
    total_earned_usd = (
        collected_usd + uncollected_usd
        if collected_usd is not None and uncollected_usd is not None
        else None
    )

    return {
        "amount0": amount0,
        "amount1": amount1,
        "amount0_usd": amount0_usd,
        "amount1_usd": amount1_usd,
        "current_value_usd": current_value_usd,
        "uncollected0": uncollected0,
        "uncollected1": uncollected1,
        "uncollected_usd": uncollected_usd,
        "collected0": collected0,
        "collected1": collected1,
        "collected_usd": collected_usd,
        "total_earned_usd": total_earned_usd,
    }


def compute_performance(current_value_usd, initial_value_usd, uncollected_usd, collected_usd,
                         first_seen_at_utc, now_utc):
    """P/L and derived performance figures for one position.

    P/L FORMULA (locked): pnl_usd = current_value_usd + uncollected_usd - initial_value_usd.
    Collected fees are excluded from P/L: for an auto-compounding position
    they've already been folded back into liquidity and therefore into
    current_value_usd — adding them again would double-count. total_earned_usd
    (collected + uncollected) is reported separately and must never be summed
    into pnl_usd by a caller.

    first_seen_at_utc may be None (e.g. no matching maxfi_positions row was
    found for a live position — see the valuation endpoint's 'partial'
    status) — every days_held-derived figure becomes None in that case,
    same as any other missing input.

    Every figure returns None (never 0.0, never inf) when its inputs are
    unavailable — division-by-zero guards: days_held <= 0 -> usd_per_day
    is None; current_value_usd in (0, None) -> apr_percent is None;
    initial_value_usd is None -> pnl_usd is None. `notes` names each
    suppressed figure and why.
    """
    notes = []

    if initial_value_usd is None:
        pnl_usd = None
        notes.append("pnl_usd suppressed: initial_value_usd is null")
    elif current_value_usd is None or uncollected_usd is None:
        pnl_usd = None
        notes.append("pnl_usd suppressed: current_value_usd or uncollected_usd unavailable")
    else:
        pnl_usd = current_value_usd + uncollected_usd - initial_value_usd

    if first_seen_at_utc is None:
        days_held = None
        notes.append("days_held unavailable: first_seen_at is unknown")
    else:
        days_held = (now_utc - first_seen_at_utc).total_seconds() / 86400.0

    if collected_usd is not None and uncollected_usd is not None:
        total_earned_usd = collected_usd + uncollected_usd
    else:
        total_earned_usd = None
        notes.append("total_earned_usd suppressed: collected_usd or uncollected_usd unavailable")

    if days_held is None:
        usd_per_day = None
        notes.append("usd_per_day suppressed: days_held is unavailable")
    elif days_held <= 0:
        usd_per_day = None
        notes.append("usd_per_day suppressed: days_held is zero or negative")
    elif total_earned_usd is None:
        usd_per_day = None
        notes.append("usd_per_day suppressed: total_earned_usd unavailable")
    else:
        usd_per_day = total_earned_usd / days_held

    if not current_value_usd:  # covers both None and exactly 0.0
        apr_percent = None
        notes.append("apr_percent suppressed: current_value_usd is zero or null")
    elif usd_per_day is None:
        apr_percent = None
        notes.append("apr_percent suppressed: usd_per_day unavailable")
    else:
        apr_percent = (usd_per_day / current_value_usd) * 365 * 100

    return {
        "pnl_usd": pnl_usd,
        "days_held": days_held,
        "usd_per_day": usd_per_day,
        "apr_percent": apr_percent,
        "total_earned_usd": total_earned_usd,
        "notes": notes,
    }


def sanity_check_price(pool_derived_usd, external_usd, tolerance_frac):
    """Advisory only — never blocks or overrides a value. Compares a
    pool-derived USD price against an independently-known external price
    (e.g. when both sides of a pair are anchors and both have their own
    resolved price) and flags divergence beyond tolerance_frac.

    Returns {"diverged": bool|None, "ratio": float|None}. None/None when
    either input is missing or external_usd is zero — there's nothing to
    compare, which is not the same as "not diverged"."""
    if pool_derived_usd is None or external_usd is None or external_usd == 0:
        return {"diverged": None, "ratio": None}
    ratio = pool_derived_usd / external_usd
    return {"diverged": abs(ratio - 1.0) > tolerance_frac, "ratio": ratio}
