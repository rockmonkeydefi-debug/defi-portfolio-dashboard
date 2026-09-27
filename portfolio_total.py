"""Total portfolio value - ONE total plus its parts, each with provenance
(GET /api/portfolio/total).

PURE: no Flask, no DB, no network and no clock reads. The route assembles the
inputs (the in-memory get_portfolio_data cache, the open maxfi_positions rows
of visible MaxFi wallets, the ledger's withdrawn-head ids, the latest MaxFi
scan per wallet/chain, and the Hyperliquid accounts cache snapshot) and passes
`now_utc` in.

Rulings (Glenn, Sep 27):
1. MaxFi principal is Zerion's own LP rows for the MaxFi vault (protocol
   "snuggle"), already in lp_positions. maxfi_positions supplies ONLY MaxFi
   uncollected fees, counted at MAXFI_UNCOLLECTED_NET_FACTOR. Rows whose ledger
   lineage head is withdrawn are excluded; rows valued more than
   MAXFI_VALUE_STALE_HOURS ago are flagged but still counted.
2. Lending is counted NET (collateral - debt); gross collateral and debt are
   reported beside it.
3. Hyperliquid (HyperCore) perp account value + priced spot balances, from a
   15-minute background cache.
4. Zerion's staking bucket is reported, NOT counted.
5. History (snapshots, the chart, Telegram) keeps today's definition - nothing
   here writes anywhere.
"""
from datetime import timedelta

from maxfi_advisor import parse_utc

# The exact tuple api_spot_stablecoins used locally (same symbols, same order);
# that route now imports this one.
STABLECOIN_SYMBOLS = ('USDC', 'USDT', 'DAI', 'FRAX', 'LUSD', 'BUSD', 'TUSD', 'USDS', 'CRVUSD')

# Zerion's protocol key for MaxFi vault LP rows (matched case-insensitively
# against an lp_positions row's "protocol").
MAXFI_PROTOCOL_KEYS = ('snuggle',)

# Gross uncollected fees lose MaxFi's 15% performance fee at harvest, so a
# position's uncollected balance is worth 85% of its gross figure to the
# wallet. The 85/15/0 split (wallet / performance fee / referrer) was verified
# on-chain for these wallets - no referrer.
MAXFI_UNCOLLECTED_NET_FACTOR = 0.85

# A maxfi_positions.last_value_at older than this is flagged (still counted).
MAXFI_VALUE_STALE_HOURS = 24

# MaxFi Zerion-vs-DB drift: warn when |zerion_sum - db_sum| exceeds the larger
# of MAXFI_DRIFT_ABS_USD and MAXFI_DRIFT_PCT % of the larger sum.
MAXFI_DRIFT_ABS_USD = 25.0
MAXFI_DRIFT_PCT = 5.0


def _num(value):
    """A finite float, or 0.0 for None / non-numeric / non-finite."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return f if f == f and f not in (float('inf'), float('-inf')) else 0.0


def _iso(dt):
    return dt.isoformat() if dt is not None else None


def _lower(value):
    return str(value or '').lower()


def _component(key, label, value_usd, counted, as_of, source, warnings=None, detail=None):
    return {
        "key": key, "label": label, "value_usd": value_usd, "counted": counted,
        "as_of": as_of, "source": source, "warnings": list(warnings or []), "detail": dict(detail or {}),
    }


def _is_maxfi_lp(lp):
    return _lower(lp.get('protocol')) in MAXFI_PROTOCOL_KEYS


def compose_total(portfolio, maxfi_rows, ledger_head_closed_ids, ledger_ok, latest_scan_by_key, hl_state, now_utc):
    """Compose the total and its parts.

    portfolio: the cached get_portfolio_data dict.
    maxfi_rows: open maxfi_positions rows (dicts) for visible MaxFi wallets -
        id, chain, wallet, token_id, last_value_usd, last_value_at, last_uncollected_usd.
    ledger_head_closed_ids: ids of those rows whose ledger lineage head is withdrawn.
    ledger_ok: False when the ledger could not be read (nothing is excluded then).
    latest_scan_by_key: {(lower wallet, chain): ISO of the newest scan/close}.
    hl_state: the Hyperliquid accounts cache snapshot
        {"fetched_at", "wallets": {addr: row}, "error", "wallets_checked"}.
    now_utc: aware UTC datetime (callers pass it; nothing here reads a clock).

    Returns {"status", "total_usd", "portfolio_total_value", "components",
    "maxfi_drift", "as_of", "warnings"}. total_usd sums the counted
    components only.
    """
    portfolio = portfolio or {}
    maxfi_rows = list(maxfi_rows or [])
    closed_ids = set(ledger_head_closed_ids or ())
    latest_scan_by_key = latest_scan_by_key or {}
    hl_state = hl_state or {}
    fetched_at = portfolio.get("fetched_at")
    wallet_labels = {_lower(a): lbl for a, lbl in (portfolio.get("wallet_labels") or {}).items()}

    def label_for(wallet):
        return wallet_labels.get(_lower(wallet)) or wallet

    tokens = portfolio.get("tokens") or []
    lp_rows = portfolio.get("lp_positions") or []
    components = []

    # 1-2. wallet tokens / stablecoins
    stable_rows = [t for t in tokens if str(t.get("symbol") or '').upper() in STABLECOIN_SYMBOLS]
    other_rows = [t for t in tokens if str(t.get("symbol") or '').upper() not in STABLECOIN_SYMBOLS]
    components.append(_component(
        "wallet_tokens", "Wallet tokens", sum(_num(t.get("value_usd")) for t in other_rows), True, fetched_at,
        "Zerion wallet positions + custom tokens + BTC/SOL (portfolio cache)",
        detail={"rows": len(other_rows), "excludes": list(STABLECOIN_SYMBOLS)}))
    components.append(_component(
        "stablecoins", "Stablecoins", sum(_num(t.get("value_usd")) for t in stable_rows), True, fetched_at,
        "Zerion wallet positions (portfolio cache)",
        detail={"rows": len(stable_rows), "symbols": list(STABLECOIN_SYMBOLS)}))

    # 3-5. LP principal (MaxFi via Zerion / other) and LP uncollected fees
    maxfi_lp = [lp for lp in lp_rows if _is_maxfi_lp(lp)]
    other_lp = [lp for lp in lp_rows if not _is_maxfi_lp(lp)]
    components.append(_component(
        "maxfi_lp", "MaxFi LP (Zerion)", sum(_num(lp.get("total_value_usd")) for lp in maxfi_lp), True, fetched_at,
        "Zerion LP groups with protocol " + "/".join(MAXFI_PROTOCOL_KEYS), detail={"rows": len(maxfi_lp)}))
    components.append(_component(
        "other_lp", "Other LP", sum(_num(lp.get("total_value_usd")) for lp in other_lp), True, fetched_at,
        "LP positions (portfolio cache)", detail={"rows": len(other_lp)}))
    components.append(_component(
        "lp_uncollected", "LP uncollected fees", sum(_num(lp.get("total_fees_usd")) for lp in lp_rows), True,
        fetched_at, "total_fees_usd over every LP row (portfolio cache)", detail={"rows": len(lp_rows)}))

    # 6. MaxFi uncollected (DB, net of the performance fee)
    zerion_fee_keys = {(_lower(lp.get("wallet")), _lower(lp.get("chain")))
                       for lp in maxfi_lp if _num(lp.get("total_fees_usd")) > 0}
    mx_warnings = []
    mx_value = mx_gross = 0.0
    excluded_closed = no_data = stale = counted_rows = 0
    skipped_keys = set()
    oldest_value_at = None
    stale_cutoff = now_utc - timedelta(hours=MAXFI_VALUE_STALE_HOURS)
    for row in maxfi_rows:
        key = (_lower(row.get("wallet")), _lower(row.get("chain")))
        if ledger_ok and row.get("id") in closed_ids:
            excluded_closed += 1
            continue
        if key in zerion_fee_keys:
            skipped_keys.add(key)
            continue
        uncollected = row.get("last_uncollected_usd")
        if uncollected is None:
            no_data += 1
            continue
        mx_gross += _num(uncollected)
        mx_value += _num(uncollected) * MAXFI_UNCOLLECTED_NET_FACTOR
        counted_rows += 1
        value_at = parse_utc(row.get("last_value_at"))
        if value_at is None or value_at < stale_cutoff:
            stale += 1
        if value_at is not None and (oldest_value_at is None or value_at < oldest_value_at):
            oldest_value_at = value_at
    if not ledger_ok:
        mx_warnings.append("ledger unavailable — withdrawn-position guard off")
    if excluded_closed:
        mx_warnings.append(f"{excluded_closed} position(s) excluded: the ledger shows them withdrawn")
    if no_data:
        mx_warnings.append(f"{no_data} position(s) have no uncollected data — not counted")
    if stale:
        mx_warnings.append(f"{stale} position(s) valued more than {MAXFI_VALUE_STALE_HOURS} h ago — counted, may be out of date")
    for wallet, chain in sorted(skipped_keys):
        mx_warnings.append(f"Zerion now reports MaxFi fees for {label_for(wallet)}/{chain}; DB uncollected skipped")
    components.append(_component(
        "maxfi_uncollected", "MaxFi uncollected fees", mx_value, True, _iso(oldest_value_at),
        "maxfi_positions.last_uncollected_usd x %.2f (net of MaxFi's 15%% performance fee)" % MAXFI_UNCOLLECTED_NET_FACTOR,
        mx_warnings,
        {"open_rows": len(maxfi_rows), "counted_rows": counted_rows, "gross_uncollected_usd": mx_gross,
         "net_factor": MAXFI_UNCOLLECTED_NET_FACTOR, "excluded_ledger_withdrawn": excluded_closed,
         "no_uncollected_data": no_data, "stale_values": stale,
         "zerion_fee_skipped": [{"wallet": label_for(w), "chain": c} for w, c in sorted(skipped_keys)]}))

    # 7. Hyperliquid (HyperCore) accounts
    hl_fetched = hl_state.get("fetched_at")
    hl_warnings = []
    hl_rows = []
    hl_value = 0.0
    if not hl_fetched:
        hl_warnings.append("Hyperliquid loading")
        if hl_state.get("error"):
            hl_warnings.append("last Hyperliquid refresh failed: " + str(hl_state.get("error")))
    else:
        for addr, w in sorted((hl_state.get("wallets") or {}).items()):
            perp = _num(w.get("perp_account_value"))
            hl_value += perp
            spot_out = []
            for s in w.get("spot") or []:
                price = s.get("price")
                value = s.get("value")
                entry = {"coin": s.get("coin"), "amount": s.get("amount"), "price": price, "value": value}
                spot_out.append(entry)
                if price is None or value is None:
                    hl_warnings.append(f"{label_for(addr)}: {s.get('coin')} has no USDC price — not counted")
                else:
                    hl_value += _num(value)
            if w.get("stale"):
                hl_warnings.append(f"{label_for(addr)}: last refresh failed ({w.get('error')}) — showing last good values")
            hl_rows.append({"wallet": addr, "label": label_for(addr), "perp_account_value": perp,
                            "open_perps": w.get("open_perps", 0), "spot": spot_out, "stale": bool(w.get("stale"))})
        for addr, err in sorted((hl_state.get("wallet_errors") or {}).items()):
            if addr not in (hl_state.get("wallets") or {}):
                hl_warnings.append(f"{label_for(addr)}: refresh failed ({err}) — no data")
        if hl_state.get("error"):
            hl_warnings.append("last Hyperliquid refresh failed: " + str(hl_state.get("error")))
    components.append(_component(
        "hyperliquid", "Hyperliquid", hl_value, bool(hl_fetched), hl_fetched,
        "Hyperliquid info API: perp accountValue + spot balances priced in USDC (15-min background cache)",
        hl_warnings, {"wallets": hl_rows, "wallets_checked": hl_state.get("wallets_checked", 0)}))

    # 8. Lending, net
    lend_rows = portfolio.get("aave_positions") or []
    gross_collateral = sum(_num(r.get("total_collateral_usd")) for r in lend_rows)
    debt = sum(_num(r.get("total_debt_usd")) for r in lend_rows)
    components.append(_component(
        "lending_net", "Lending (net)", gross_collateral - debt, True, fetched_at,
        "Zerion/Aave lending positions: collateral - debt (portfolio cache)",
        detail={"gross_collateral_usd": gross_collateral, "debt_usd": debt,
                "rows": [{"wallet_label": r.get("wallet_label"), "chain": r.get("chain"),
                          "protocol": r.get("protocol_name"),
                          "collateral_usd": _num(r.get("total_collateral_usd")),
                          "debt_usd": _num(r.get("total_debt_usd")),
                          "health_factor": r.get("health_factor")} for r in lend_rows]}))

    # 9. GMX - stable collateral only
    gmx_rows = portfolio.get("gmx_positions") or []
    gmx_value = 0.0
    gmx_warnings = []
    gmx_not_counted = []
    for r in gmx_rows:
        if str(r.get("collateral_symbol") or '').upper() in STABLECOIN_SYMBOLS:
            gmx_value += _num(r.get("collateral_amount"))
        else:
            gmx_not_counted.append({"market": r.get("market"), "collateral_symbol": r.get("collateral_symbol"),
                                    "collateral_amount": r.get("collateral_amount")})
    if gmx_not_counted:
        gmx_warnings.append(f"{len(gmx_not_counted)} position(s): collateral in token units (known gmx_v2 units bug) — not counted")
    components.append(_component(
        "gmx", "GMX collateral", gmx_value, True, fetched_at,
        "gmx_v2 collateral_amount, stablecoin collateral only (portfolio cache)", gmx_warnings,
        {"rows": len(gmx_rows), "not_counted": gmx_not_counted, "pnl": "not included"}))

    # 10. Zerion staking bucket - reported, not counted
    if "staking_positions" in portfolio:
        st_rows = portfolio.get("staking_positions") or []
        st_detail = {"rows": [{"wallet_label": r.get("wallet_label"), "chain": r.get("chain"),
                               "protocol": r.get("protocol"), "position_type": r.get("position_type"),
                               "symbol": r.get("symbol"), "value_usd": _num(r.get("value_usd"))} for r in st_rows]}
        st_value = sum(_num(r.get("value_usd")) for r in st_rows)
    else:
        st_detail = {"rows": [], "note": "not reported by this portfolio payload"}
        st_value = 0.0
    components.append(_component(
        "zerion_staking", "Staked / locked (Zerion)", st_value, False, fetched_at,
        "Zerion staking/deposit/locked/reward positions - reported, not counted", detail=st_detail))

    # MaxFi drift: Zerion snuggle rows vs maxfi_positions, per wallet/chain (informational)
    portfolio_fetched = parse_utc(fetched_at)
    drift_keys = {(_lower(lp.get("wallet")), _lower(lp.get("chain"))) for lp in maxfi_lp}
    drift_keys |= {(_lower(r.get("wallet")), _lower(r.get("chain"))) for r in maxfi_rows}
    drift = []
    for wallet, chain in sorted(drift_keys):
        z = [lp for lp in maxfi_lp if (_lower(lp.get("wallet")), _lower(lp.get("chain"))) == (wallet, chain)]
        d = [r for r in maxfi_rows if (_lower(r.get("wallet")), _lower(r.get("chain"))) == (wallet, chain)]
        zerion_sum = sum(_num(lp.get("total_value_usd")) for lp in z)
        db_values = [r.get("last_value_usd") for r in d if r.get("last_value_usd") is not None]
        db_sum = sum(_num(v) for v in db_values)
        latest_scan = latest_scan_by_key.get((wallet, chain))
        warnings = []
        if len(z) != len(d):
            warnings.append(f"count mismatch: Zerion {len(z)} vs DB {len(d)} open")
        threshold = max(MAXFI_DRIFT_ABS_USD, MAXFI_DRIFT_PCT / 100.0 * max(abs(zerion_sum), abs(db_sum)))
        if abs(zerion_sum - db_sum) > threshold:
            warnings.append(f"value drift: Zerion ${zerion_sum:,.2f} vs DB ${db_sum:,.2f}")
        scan_dt = parse_utc(latest_scan)
        if scan_dt is not None and portfolio_fetched is not None and scan_dt > portfolio_fetched:
            warnings.append("portfolio data predates your last MaxFi scan — press Refresh")
        drift.append({"wallet": wallet, "wallet_label": label_for(wallet), "chain": chain,
                      "zerion_count": len(z), "zerion_sum": zerion_sum, "db_open": len(d), "db_sum": db_sum,
                      "db_null_values": len(d) - len(db_values), "latest_scan_at": latest_scan,
                      "portfolio_fetched_at": fetched_at, "warnings": warnings})

    all_warnings = [{"component": c["key"], "warning": w} for c in components for w in c["warnings"]]
    all_warnings += [{"component": "maxfi_drift", "warning": f"{e['wallet_label']}/{e['chain']}: {w}"}
                     for e in drift for w in e["warnings"]]
    return {
        "status": "ok",
        "total_usd": sum(c["value_usd"] for c in components if c["counted"]),
        "portfolio_total_value": portfolio.get("total_value"),
        "components": components,
        "maxfi_drift": drift,
        "as_of": {"portfolio": fetched_at, "hyperliquid": hl_fetched, "maxfi_values_oldest": _iso(oldest_value_at)},
        "warnings": all_warnings,
    }
