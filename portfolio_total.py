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
3. Hyperliquid (HyperCore) priced spot balances, plus the perp account value
   only for standard-mode accounts; unified / portfolio-margin accounts hold
   their perp equity inside spot USDC, so their perp is reported, not counted
   (an unknown or unread account mode counts spot only, with a warning). From
   a 15-minute background cache.
4. Zerion's staking bucket is reported, NOT counted.
5. History (snapshots, the chart, Telegram) keeps today's definition - nothing
   here writes anywhere.
6. Uncounted value is warned about, never counted: unpriced or failed token
   rows at the last good price, and Zerion LP groups with no deposit leg
   (level-shift investigation, Sep 28). One short line per part; the per-row
   information is in that part's detail["uncounted"]. The estimates come from
   the optional history_hints the callers read; no value here changes.
7. Custom-token prices carried from custom_token_price_snapshot (at most
   24 h old) are counted and flagged with one line per part (level-shift
   PR 3, Sep 29).
8. (Sep 29, level-shift step 3; definition_version 2) DexFi (formerly Dex
   Finance) bonds are counted in Other LP at DEXFI_BOND_REDEMPTION_FACTOR
   (90%: redemption pays 90% of NAV) from DexFi's public bond API (the
   callers' background cache, dexfi_state): value = the wallet's
   bondsHoldShare x bondFundWalletUsd. A value fetched more than
   DEXFI_BOND_STALE_HOURS ago is not counted (warned); one fetched more than
   DEXFI_BOND_FLAG_HOURS ago is counted and flagged. No double count: a
   wallet whose Zerion Dex Finance row is itself valued (> $0) keeps
   Zerion's value and its DexFi row is reported only. The reward legs of
   Zerion LP groups with NO deposit leg (the bonds' pending USDC) are counted
   in LP uncollected. Caveat: DexFi's share denominator (~124,488 bonds) is
   smaller than totalSupply, so share x fund runs ~0.5% above units x price.
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

# Hyperliquid account modes (info request {"type": "userAbstraction"}).
# Hyperliquid docs (account abstraction modes): "For API users, unified account
# and portfolio margin show all balances and holds in the spot clearinghouse
# state." - so for those modes spot USDC already holds the perp equity, and
# adding marginSummary.accountValue on top counts it twice.
# Mode strings: 'unifiedAccount' (ccxt issue #28093); a third-party doc lists
# 'unifiedAccount', 'portfolioMargin', 'disabled', 'default'. [Unverified]
# 'disabled' = standard (perp margin separate from spot).
# Any other value, or no mode, counts spot only with a warning.
HL_MODES_PERP_INSIDE_SPOT = ('unifiedAccount', 'portfolioMargin')
HL_MODES_PERP_SEPARATE = ('disabled',)

# Uncounted-value warnings (ruling 6): warn when the estimate reaches this.
UNCOUNTED_WARN_USD = 500.0

# DexFi bonds (ruling 8): counted at 90% (redemption pays 90% of NAV); a value
# older than DEXFI_BOND_STALE_HOURS is not counted, one older than
# DEXFI_BOND_FLAG_HOURS is counted and flagged.
DEXFI_BOND_REDEMPTION_FACTOR = 0.90
DEXFI_BOND_STALE_HOURS = 24
DEXFI_BOND_FLAG_HOURS = 3
# Zerion's protocol key for DexFi rows (map_zerion_lp_to_app lowercases the
# display name, "Dex Finance" -> "dex_finance"; "dexfi" covers the rebrand).
DEXFI_ZERION_PROTOCOL_KEYS = ('dex_finance', 'dexfi')
# How far back the callers look for a last good price / a last read balance.
TOKEN_PRICE_LOOKBACK_DAYS = 30
TOKEN_BALANCE_LOOKBACK_DAYS = 7


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


# ── uncounted-value hints (ruling 6); shared with web_portfolio.py ─────────

def token_hint_key(row):
    """(lower chain, ident) for a token row: ident is the lowercased contract
    (row token_address or contract) - never the symbol, which spam tokens
    reuse - or "sym:" + upper symbol for a native token with no address."""
    ident = _lower(row.get('token_address') or row.get('contract')).strip()
    if not ident:
        ident = 'sym:' + str(row.get('symbol') or '').upper()
    return (_lower(row.get('chain')), ident)


def is_uncounted_token_row(row):
    """A token row the total counts as $0: a failed balance read, or a
    positive balance with no price."""
    if row.get('balance_failed') is True:
        return True
    return _num(row.get('balance')) > 0 and _num(row.get('price_usd')) == 0


def lp_hint_key(lp):
    return (_lower(lp.get('wallet')), _lower(lp.get('chain')), _lower(lp.get('protocol')))


def is_no_deposit_lp(lp):
    """A Zerion LP group with no deposit leg (counted as $0). On-chain rows
    carry no deposit_legs field and are never flagged."""
    return lp.get('deposit_legs') == 0


def _hours_since(at, now_utc):
    dt = parse_utc(at) if at else None
    return max(0.0, (now_utc - dt).total_seconds() / 3600.0) if dt else None


def _uncounted_tokens(rows, hints, now_utc):
    """(warning text or None, detail dict or None) for one token component.
    Counts in the text are distinct tokens (token_hint_key); detail "rows"
    counts wallet holdings."""
    prices = hints.get('token_prices') or {}
    balances = hints.get('token_balances') or {}
    n = unknown = 0
    est_tokens, unknown_tokens = set(), set()
    est = 0.0
    symbols = []
    oldest_h = None
    for row in rows:
        if not is_uncounted_token_row(row):
            continue
        key = token_hint_key(row)
        used_at = []
        price = _num(row.get('price_usd'))
        if price <= 0:
            ph = prices.get(key)
            price = _num(ph.get('price_usd')) if ph else 0.0
            if price > 0:
                used_at.append(ph.get('at'))
        if row.get('balance_failed') is True:
            bh = balances.get((_lower(row.get('wallet')),) + key)
            if not bh:
                continue
            balance = _num(bh.get('balance'))
            used_at.append(bh.get('at'))
        else:
            balance = _num(row.get('balance'))
        if price <= 0:
            if row.get('source') == 'custom':
                unknown += 1
                unknown_tokens.add(key)
            continue        # a Zerion row never priced: spam, not reported
        n += 1
        est_tokens.add(key)
        est += balance * price
        sym = str(row.get('symbol') or '?')
        if sym not in symbols:
            symbols.append(sym)
        for at in used_at:
            h = _hours_since(at, now_utc)
            if h is not None and (oldest_h is None or h > oldest_h):
                oldest_h = h
    n_tok, k_tok = len(est_tokens), len(unknown_tokens)
    if n and est >= UNCOUNTED_WARN_USD:
        text = (f"{n_tok} token{'' if n_tok == 1 else 's'} unpriced — about ${est:,.0f} not counted "
                f"({', '.join(symbols[:3])})")
        if k_tok:
            text += f"; {k_tok} more with no price history"
    elif k_tok:
        text = f"{k_tok} custom token{'' if k_tok == 1 else 's'} unpriced — value unknown"
    else:
        text = None
    detail = ({"rows": n, "tokens": n_tok, "est_usd": est, "unknown_value_rows": unknown,
               "unknown_value_tokens": k_tok, "symbols": symbols, "price_oldest_hours": oldest_h}
              if n else None)
    return text, detail


def _stale_tokens(rows, now_utc):
    """(warning text or None, detail dict or None) for one token component's
    rows priced at a carried last good price (price_stale, ruling 7). They are
    already counted through their value_usd; this only flags them. Only
    rows worth more than $0 count (a carried price lands on every wallet's
    row, empty ones too). Counts in the text are distinct tokens
    (token_hint_key); detail "rows" counts wallet holdings."""
    n = 0
    tokens = set()
    est = 0.0
    symbols = []
    oldest_h = None
    for row in rows:
        if row.get('price_stale') is not True or _num(row.get('value_usd')) <= 0:
            continue
        n += 1
        tokens.add(token_hint_key(row))
        est += _num(row.get('value_usd'))
        sym = str(row.get('symbol') or '?')
        if sym not in symbols:
            symbols.append(sym)
        h = _hours_since(row.get('price_as_of'), now_utc)
        if h is not None and (oldest_h is None or h > oldest_h):
            oldest_h = h
    if not n:
        return None, None
    n_tok = len(tokens)
    detail = {"rows": n, "tokens": n_tok, "est_usd": est, "symbols": symbols, "price_oldest_hours": oldest_h}
    if est < UNCOUNTED_WARN_USD:
        return None, detail
    age = f", {oldest_h:.0f} h old" if oldest_h is not None else ""
    text = (f"{n_tok} token{'' if n_tok == 1 else 's'} at last good price — about ${est:,.0f} "
            f"({', '.join(symbols[:3])}{age})")
    return text, detail


def _uncounted_lps(rows, lp_last, label_for, skip_wallets=frozenset()):
    """(warning text or None, detail dict or None) for one LP component: ONE
    line for all its Zerion LP groups with no deposit leg; the per-row
    information goes into the detail. The estimate is the principal only
    (the last valued lp_snapshots row): the groups' reward legs are counted in
    LP uncollected (ruling 8). Groups in skip_wallets (lowercased; wallets
    with a DexFi bonds row) are left out - DexFi values them."""
    flagged = [lp for lp in rows if is_no_deposit_lp(lp) and _lower(lp.get('wallet')) not in skip_wallets]
    if not flagged:
        return None, None
    est = 0.0
    oldest = None
    out = []
    for lp in flagged:
        last = lp_last.get(lp_hint_key(lp))
        uncounted = _num(lp.get('uncounted_legs_usd'))
        est += _num(last.get('value_usd')) if last else 0.0
        at = parse_utc(last.get('at')) if last and last.get('at') else None
        if at is not None and (oldest is None or at < oldest):
            oldest = at
        out.append({"wallet_label": label_for(lp.get('wallet')),
                    "protocol": lp.get('protocol_display') or lp.get('protocol'),
                    "uncounted_legs_usd": uncounted,
                    "last_valued": ({"token0": last.get('token0'), "amount0": _num(last.get('amount0')),
                                     "value_usd": _num(last.get('value_usd')), "at": last.get('at')}
                                    if last else None)})
    detail = {"est_usd": est, "rows": out}
    if est < UNCOUNTED_WARN_USD:
        return None, detail
    names = {r["protocol"] for r in out}
    name = names.pop() if len(names) == 1 else "LP"
    n = len(flagged)
    text = f"{n} {name} position{'' if n == 1 else 's'} not counted — about ${est:,.0f}"
    if oldest is not None:
        text += f" (last seen {oldest:%b} {oldest.day})"
    return text, detail


def compose_total(portfolio, maxfi_rows, ledger_head_closed_ids, ledger_ok, latest_scan_by_key, hl_state, now_utc,
                  *, history_hints=None, dexfi_state=None):
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
    history_hints: optional, in-memory only (never serialized), for the
        uncounted-value warnings of ruling 6 - display-only, no value uses it:
        {"token_prices":   {token_hint_key: {"price_usd", "at"}},
         "token_balances": {(lower wallet,) + token_hint_key: {"balance", "at"}},
         "lp_last_valued": {lp_hint_key: {"value_usd", "token0", "amount0",
                                          "token1", "amount1", "at"}}}.
        None or {} gives exactly today's output.
    dexfi_state: optional, the DexFi bonds cache snapshot (ruling 8)
        {"fetched_at", "info", "wallets": {addr: {"share", "value_usd",
        "units_est", "fetched_at", "stale"?}}, "error"}. None, {} or no
        wallets gives exactly the output without DexFi bonds.

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
    token_warnings = {"wallet_tokens": [], "stablecoins": []}
    token_detail = {"wallet_tokens": {"rows": len(other_rows), "excludes": list(STABLECOIN_SYMBOLS)},
                    "stablecoins": {"rows": len(stable_rows), "symbols": list(STABLECOIN_SYMBOLS)}}
    for key, rows in (("wallet_tokens", other_rows), ("stablecoins", stable_rows)):
        # Rulings 6-7: display-only; the values below never read these. ONE
        # line per part: carried prices first, then uncounted value.
        stale_text, stale = _stale_tokens(rows, now_utc)
        uncounted_text = uncounted = None
        if history_hints:
            uncounted_text, uncounted = _uncounted_tokens(rows, history_hints, now_utc)
        text = "; ".join(t for t in (stale_text, uncounted_text) if t)
        if text:
            token_warnings[key].append(text)
        if stale:
            token_detail[key]["stale"] = stale
        if uncounted:
            token_detail[key]["uncounted"] = uncounted
    components.append(_component(
        "wallet_tokens", "Wallet tokens", sum(_num(t.get("value_usd")) for t in other_rows), True, fetched_at,
        "Zerion wallet positions + custom tokens + BTC/SOL (portfolio cache)",
        warnings=token_warnings["wallet_tokens"], detail=token_detail["wallet_tokens"]))
    components.append(_component(
        "stablecoins", "Stablecoins", sum(_num(t.get("value_usd")) for t in stable_rows), True, fetched_at,
        "Zerion wallet positions (portfolio cache)",
        warnings=token_warnings["stablecoins"], detail=token_detail["stablecoins"]))

    # 3-5. LP principal (MaxFi via Zerion / other) and LP uncollected fees
    maxfi_lp = [lp for lp in lp_rows if _is_maxfi_lp(lp)]
    other_lp = [lp for lp in lp_rows if not _is_maxfi_lp(lp)]
    lp_warnings = {"maxfi_lp": [], "other_lp": []}
    lp_detail = {"maxfi_lp": {"rows": len(maxfi_lp)}, "other_lp": {"rows": len(other_lp)}}

    # DexFi bonds (ruling 8): each wallet row gets exactly one status.
    dexfi_state = dexfi_state or {}
    zerion_valued_dexfi = {_lower(lp.get("wallet")) for lp in lp_rows
                           if _lower(lp.get("protocol")) in DEXFI_ZERION_PROTOCOL_KEYS
                           and _num(lp.get("total_value_usd")) > 0}
    dexfi_rows = []
    for addr, row in sorted((dexfi_state.get("wallets") or {}).items()):
        value = _num(row.get("value_usd"))
        if value <= 0:
            continue
        age_h = _hours_since(row.get("fetched_at"), now_utc)
        if _lower(addr) in zerion_valued_dexfi:
            status = "zerion_valued"
        elif age_h is None or age_h > DEXFI_BOND_STALE_HOURS:
            status = "expired"
        else:
            status = "counted"
        dexfi_rows.append({"wallet": _lower(addr), "wallet_label": label_for(addr), "value_usd": value,
                           "counted_usd": value * DEXFI_BOND_REDEMPTION_FACTOR if status == "counted" else 0.0,
                           "units_est": row.get("units_est"), "fetched_at": row.get("fetched_at"),
                           "age_hours": age_h, "status": status})
    dexfi_wallets = {r["wallet"] for r in dexfi_rows}
    dexfi_counted = [r for r in dexfi_rows if r["status"] == "counted"]
    dexfi_counted_usd = sum(r["counted_usd"] for r in dexfi_counted)

    if history_hints:   # ruling 6: display-only
        lp_last = history_hints.get("lp_last_valued") or {}
        for key, rows in (("maxfi_lp", maxfi_lp), ("other_lp", other_lp)):
            text, uncounted = _uncounted_lps(rows, lp_last, label_for, dexfi_wallets)
            if text:
                lp_warnings[key].append(text)
            if uncounted:
                lp_detail[key]["uncounted"] = uncounted
    if dexfi_rows:
        dexfi_texts = []
        flagged = [r for r in dexfi_counted if r["age_hours"] > DEXFI_BOND_FLAG_HOURS]
        flagged_usd = sum(r["counted_usd"] for r in flagged)
        if flagged and flagged_usd >= UNCOUNTED_WARN_USD:
            n = len(flagged)
            dexfi_texts.append(f"{n} DexFi bond position{'' if n == 1 else 's'} at last good value — "
                               f"about ${flagged_usd:,.0f} ({max(r['age_hours'] for r in flagged):.0f} h old)")
        expired = [r for r in dexfi_rows if r["status"] == "expired"]
        expired_usd = sum(r["value_usd"] * DEXFI_BOND_REDEMPTION_FACTOR for r in expired)
        if expired and expired_usd >= UNCOUNTED_WARN_USD:
            n = len(expired)
            dexfi_texts.append(f"{n} DexFi bond position{'' if n == 1 else 's'} not updated for over "
                               f"{DEXFI_BOND_STALE_HOURS} h — about ${expired_usd:,.0f} not counted")
        if dexfi_texts:
            if lp_warnings["other_lp"]:
                lp_warnings["other_lp"] = ["; ".join(lp_warnings["other_lp"] + dexfi_texts)]
            else:
                lp_warnings["other_lp"].append("; ".join(dexfi_texts))
        lp_detail["other_lp"]["dexfi_bonds"] = {
            "factor": DEXFI_BOND_REDEMPTION_FACTOR, "counted_usd": dexfi_counted_usd,
            "full_value_usd": sum(r["value_usd"] for r in dexfi_counted),
            "info": dexfi_state.get("info"), "info_fetched_at": dexfi_state.get("fetched_at"),
            "rows": [{k: r[k] for k in ("wallet_label", "value_usd", "counted_usd", "units_est", "fetched_at",
                                        "age_hours", "status")} for r in dexfi_rows]}

    components.append(_component(
        "maxfi_lp", "MaxFi LP (Zerion)", sum(_num(lp.get("total_value_usd")) for lp in maxfi_lp), True, fetched_at,
        "Zerion LP groups with protocol " + "/".join(MAXFI_PROTOCOL_KEYS), warnings=lp_warnings["maxfi_lp"],
        detail=lp_detail["maxfi_lp"]))
    other_source = "LP positions (portfolio cache)"
    if dexfi_rows:
        other_source += " + DexFi bonds at %d%% (DexFi public API, background cache)" % round(
            DEXFI_BOND_REDEMPTION_FACTOR * 100)
    components.append(_component(
        "other_lp", "Other LP", sum(_num(lp.get("total_value_usd")) for lp in other_lp) + dexfi_counted_usd, True,
        fetched_at, other_source, warnings=lp_warnings["other_lp"], detail=lp_detail["other_lp"]))
    # LP uncollected (ruling 8): + the reward legs of Zerion LP groups with NO
    # deposit leg; a normal group's third-token reward legs are not added.
    no_dep = [lp for lp in lp_rows if is_no_deposit_lp(lp)]
    no_dep_rewards = sum(_num(lp.get("uncounted_legs_usd")) for lp in no_dep)
    unc_detail = {"rows": len(lp_rows)}
    unc_source = "total_fees_usd over every LP row (portfolio cache)"
    if no_dep:
        unc_detail["no_deposit_reward_legs_usd"] = no_dep_rewards
        unc_source = ("total_fees_usd over every LP row + reward legs of Zerion LP groups with no deposit leg "
                      "(portfolio cache)")
    components.append(_component(
        "lp_uncollected", "LP uncollected fees",
        sum(_num(lp.get("total_fees_usd")) for lp in lp_rows) + no_dep_rewards, True,
        fetched_at, unc_source, detail=unc_detail))

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
            mode = w.get("mode")
            if mode in HL_MODES_PERP_INSIDE_SPOT:
                perp_treatment = 'inside_spot'
            elif mode in HL_MODES_PERP_SEPARATE:
                perp_treatment = 'counted'
                hl_value += perp
            else:
                perp_treatment = 'not_counted_unknown_mode'
                if perp != 0:
                    if isinstance(mode, str) and mode:
                        hl_warnings.append(f"{label_for(addr)}: account mode {mode!r} not recognised — "
                                           f"perp ${perp:,.2f} not counted (spot only)")
                    else:
                        hl_warnings.append(f"{label_for(addr)}: account mode unavailable "
                                           f"({w.get('mode_error') or 'not read'}) — perp ${perp:,.2f} not counted (spot only)")
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
                            "open_perps": w.get("open_perps", 0), "spot": spot_out, "stale": bool(w.get("stale")),
                            "mode": mode, "perp_treatment": perp_treatment})
        for addr, err in sorted((hl_state.get("wallet_errors") or {}).items()):
            if addr not in (hl_state.get("wallets") or {}):
                hl_warnings.append(f"{label_for(addr)}: refresh failed ({err}) — no data")
        if hl_state.get("error"):
            hl_warnings.append("last Hyperliquid refresh failed: " + str(hl_state.get("error")))
    components.append(_component(
        "hyperliquid", "Hyperliquid", hl_value, bool(hl_fetched), hl_fetched,
        "Hyperliquid info API: priced spot balances + perp accountValue for standard-mode accounts only "
        "(unified / portfolio-margin accounts hold perp equity inside spot USDC) (15-min background cache)",
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
