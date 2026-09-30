"""Alpha Chasers: a Bittensor trading bot's performance measured in TAO, not
dollars (GET /api/bittensor/performance).

PURE: no Flask, no DB, no network and no clock reads. The route reads the
portfolio cache, the hand-entered bittensor_flows rows, the wallet's
token_snapshots rows and market TAO prices, and passes now_utc in.

Formulas:
- result = TAO-equivalent now - net TAO deposited
- simple % = result / net deposited x 100
- dollar gain vs just holding the deposited TAO = result x today's TAO price

TAO-equivalent per snapshot run: within a run every Bittensor row was valued
at ONE TAO price, and the TAO-denominated rows (TAO, TAO reserved, TAO root,
TAO liquidity, TAO other) carry that price in price_usd, so
TAO-equivalent = sum(value_usd) / that price, exactly. A run with no such row
(alpha only) uses the market TAO price nearest the run, within
MARKET_PRICE_MAX_HOURS; with none, the run is skipped.

The simple % is exact for a single deposit. With several deposits it gives a
late deposit full credit for the whole period (a time-weighted return is a
later option).
"""
from maxfi_advisor import parse_utc

RAO_PER_TAO = 10 ** 9
TAO_ROW_SYMBOLS = ("TAO", "TAO reserved", "TAO root", "TAO liquidity", "TAO other")
MARKET_PRICE_MAX_HOURS = 6


def _num(v):
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def run_price(rows):
    """The run's TAO price: price_usd of the first TAO-denominated row with a
    price > 0, else None."""
    for r in rows:
        if r.get("symbol") in TAO_ROW_SYMBOLS and _num(r.get("price_usd")) > 0:
            return _num(r.get("price_usd"))
    return None


def _market_price_near(ts, market_prices):
    best = None
    for at, price in market_prices or []:
        if at is None or not price or price <= 0:
            continue
        gap = abs((at - ts).total_seconds())
        if gap <= MARKET_PRICE_MAX_HOURS * 3600 and (best is None or gap < best[0]):
            best = (gap, float(price))
    return best[1] if best else None


def build_series(rows, market_prices):
    """[{"t": UTC ISO, "tao_eq": float}] oldest first, one point per snapshot
    run of ONE wallet's rows ({timestamp, symbol, price_usd, value_usd}).
    market_prices: [(aware datetime, price)]."""
    runs = {}
    for r in rows or []:
        ts = parse_utc(r.get("timestamp"))
        if ts is None:
            continue
        runs.setdefault(ts, []).append(r)
    out = []
    for ts in sorted(runs):
        run = runs[ts]
        price = run_price(run) or _market_price_near(ts, market_prices)
        if not price or price <= 0:
            continue
        out.append({"t": ts.isoformat(), "tao_eq": sum(_num(r.get("value_usd")) for r in run) / price})
    return out


def build_wallet(wallet, label, status, flows, rows, market_prices, now_utc):
    """One wallet's card data (see the module docstring for the formulas)."""
    status = status or {}
    parsed = [(parse_utc(f.get("flow_at")), f) for f in flows or []]
    counted = [f for at, f in parsed if at is not None and at <= now_utc]
    net_rao = sum(int(f.get("amount_rao") or 0) for f in counted)
    state = status.get("state") or "unavailable"
    live = state in ("fresh", "stale")
    tao_now = status.get("tao_amount") if live else None
    usd_now = status.get("value_usd") if live else None
    tao_usd = status.get("price_usd")
    net_deposited = net_rao / RAO_PER_TAO if counted else None
    result_tao = tao_now - net_deposited if tao_now is not None and net_deposited is not None else None
    result_pct = (result_tao / net_deposited * 100
                  if result_tao is not None and net_deposited is not None and net_deposited > 0 else None)
    result_usd = result_tao * tao_usd if result_tao is not None and tao_usd is not None else None

    ordered = sorted((p for p in parsed if p[0] is not None), key=lambda p: (p[0], p[1].get("id") or 0))
    deposits, running = [], 0
    for at, f in ordered:
        running += int(f.get("amount_rao") or 0)
        deposits.append({"t": at.isoformat(), "net_tao": running / RAO_PER_TAO})
    flows_out = [{"id": f.get("id"), "flow_at": f.get("flow_at"),
                  "amount_tao": int(f.get("amount_rao") or 0) / RAO_PER_TAO, "note": f.get("note")}
                 for _at, f in reversed(ordered)]

    return {"wallet": wallet, "label": label, "state": state, "reason": status.get("reason"),
            "as_of": status.get("as_of"), "age_hours": status.get("age_hours"),
            "tao_now": tao_now, "usd_now": usd_now, "tao_usd": tao_usd,
            "net_deposited_tao": net_deposited, "result_tao": result_tao, "result_pct": result_pct,
            "result_usd": result_usd, "series": build_series(rows, market_prices),
            "deposits": deposits, "flows": flows_out}


def compose(wallets, labels, bittensor_status, flows_by_wallet, rows_by_wallet, market_prices, now_utc):
    """{"status": "ok", "as_of", "wallets": [build_wallet(...)]} in the given
    wallet order. A wallet missing from bittensor_status is "unavailable"
    ("not in the portfolio cache")."""
    out = []
    for w in wallets:
        status = (bittensor_status or {}).get(w)
        if status is None:
            status = {"state": "unavailable", "reason": "not in the portfolio cache"}
        out.append(build_wallet(w, (labels or {}).get(w) or "Bittensor", status,
                                (flows_by_wallet or {}).get(w) or [], (rows_by_wallet or {}).get(w) or [],
                                market_prices, now_utc))
    return {"status": "ok", "as_of": now_utc.isoformat(), "wallets": out}
