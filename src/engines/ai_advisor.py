"""AI Advisor — builds context from portfolio + market data and generates reports via LLM."""

import os
import json
import math
from datetime import datetime, timezone

SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "ai_system_prompt.txt")
AI_CONFIG_PATH = os.path.join("data", "ai_config.json")


def load_ai_config() -> dict:
    """Load AI configuration."""
    if os.path.exists(AI_CONFIG_PATH):
        try:
            with open(AI_CONFIG_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"provider": "openai", "model": "gpt-4o", "schedule_utc_hour": 8}


def save_ai_config(config: dict):
    """Save AI configuration."""
    try:
        os.makedirs(os.path.dirname(AI_CONFIG_PATH), exist_ok=True)
        with open(AI_CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)
    except (IOError, OSError) as e:
        print(f"Error saving AI config: {e}")


def load_system_prompt() -> str:
    """Load the base system prompt."""
    try:
        with open(SYSTEM_PROMPT_PATH, 'r') as f:
            return f.read()
    except (IOError, OSError) as e:
        print(f"Error loading system prompt from {SYSTEM_PROMPT_PATH}: {e}")
        return "You are a DeFi portfolio advisor. Respond in JSON format."


def build_full_system_prompt(config: dict) -> str:
    """Return the base system prompt as-is.

    The user's strategy playbook is delivered via the user-message context
    (see build_context's CUSTOM INSTRUCTIONS section), not the system prompt,
    so this function is now a thin wrapper kept for call-site compatibility.
    """
    return load_system_prompt()


def build_context(get_portfolio_fn, get_wallets_fn) -> tuple:
    """Build the user message context from all data sources.
    Uses DB data first, falls back to API if stale (>4 hours).
    Returns (context_string, freshness_dict).
    """
    freshness = {}
    sections = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # --- Strategy Playbook and Custom Instructions (from AI config) ---
    # This is the user's authoritative source of strategy preferences.
    # The previous bull/bear/sideways structured fields were removed; users
    # now express the entire playbook (including regime-specific guidance)
    # in a single textarea here.
    config = load_ai_config()
    custom = config.get("custom_system_prompt", "")
    if custom and custom.strip():
        sections.append("## STRATEGY PLAYBOOK AND CUSTOM INSTRUCTIONS (apply to all recommendations)")
        sections.append(custom.strip())

    # --- Market Data (DB only) ---
    market = _get_market_data_smart(freshness)
    sections.append(f"## MARKET DATA (as of {ts})")
    sections.append(market)

    # --- Macro Indicators (FRED, from cache or fresh) ---
    macro_text = _get_fred_macro_context(freshness)
    if macro_text:
        sections.append("## MACRO INDICATORS")
        sections.append(macro_text)

    # --- Derived Analytics (Z-scores, changes from DB history) ---
    analytics = _calc_derived_analytics(freshness)
    if analytics:
        sections.append("## DERIVED ANALYTICS")
        sections.append(analytics)

    # --- Support/Resistance ---
    sr = _calc_support_resistance(freshness)
    if sr:
        sections.append("## SUPPORT / RESISTANCE (weekly pivot points)")
        sections.append(sr)

    # --- Portfolio ---
    portfolio_text = _build_portfolio_context(get_portfolio_fn, get_wallets_fn, freshness)
    sections.append("## PORTFOLIO COMPOSITION")
    sections.append(portfolio_text)

    # --- Previous Recommendations ---
    prev_recs = _get_previous_recommendations()
    if prev_recs:
        sections.append("## PREVIOUS RECOMMENDATIONS (from last report)")
        sections.append(prev_recs)

    return "\n\n".join(sections), freshness


def _get_fred_macro_context(freshness: dict) -> str:
    """Get FRED macro indicators — uses shared cache, fallback to fresh fetch."""
    try:
        from web_portfolio import fetch_fred_macro
        data = fetch_fred_macro(force=False)  # uses 24h cache
        if data and data.get("llm_text"):
            freshness['macro'] = f'fred ({data.get("fetched_at", "?")})'
            return data["llm_text"]
        return ""
    except Exception as e:
        freshness['macro'] = f'error: {e}'
        return ""


def _get_market_data_smart(freshness: dict) -> str:
    """Get market data from DB only — no API calls."""
    from src.storage.portfolio_db import get_connection
    
    market_text = ""
    
    try:
        conn = get_connection()
        # Use the latest snapshot that has price data for the main display
        row = conn.execute(
            "SELECT * FROM market_snapshots WHERE btc_price IS NOT NULL ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if not row:
            # Fallback to absolute latest
            row = conn.execute(
                "SELECT * FROM market_snapshots ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        conn.close()
        
        if row:
            row = dict(row)
            from datetime import datetime as dt
            try:
                snap_time = dt.fromisoformat(row['timestamp'].replace('Z', ''))
                age_hours = (datetime.now(timezone.utc).replace(tzinfo=None) - snap_time).total_seconds() / 3600
            except Exception:
                age_hours = 999
            
            freshness['market'] = f'db (age: {age_hours:.1f}h)'
            market_text = _format_market_from_db(row)
        else:
            freshness['market'] = 'no_data'
            market_text = "No market snapshots in DB yet"
    except Exception as e:
        freshness['market'] = f'error: {str(e)}'
        market_text = "Market data unavailable"
    
    # Always append DB-stored DeFi rates and volatility
    db_extras = _get_db_defi_context(freshness)
    if db_extras:
        market_text += "\n" + db_extras
    
    return market_text


def _get_db_defi_context(freshness: dict) -> str:
    """Get lending rates, LP pool data, volatility, and 7d trends from DB."""
    from src.storage.portfolio_db import get_connection
    lines = []

    def _trend(current, prior):
        """Return trend direction string."""
        if current is None or prior is None or prior == 0:
            return "insufficient_data"
        pct_change = abs(current - prior) / abs(prior) * 100
        if pct_change < 10:
            return "flat"
        return "rising" if current > prior else "declining"

    def _vol_trend(current, prior):
        if current is None or prior is None or prior == 0:
            return "insufficient_data"
        pct_change = abs(current - prior) / abs(prior) * 100
        if pct_change < 5:
            return "flat"
        return "expanding" if current > prior else "contracting"

    try:
        conn = get_connection()

        # --- Lending rates with 7d trend ---
        latest_rate_ts = conn.execute("SELECT MAX(timestamp) as ts FROM defi_rates").fetchone()
        prior_rate_ts = conn.execute(
            "SELECT MAX(timestamp) as ts FROM defi_rates WHERE timestamp <= datetime((SELECT MAX(timestamp) FROM defi_rates), '-5 days') AND timestamp >= datetime((SELECT MAX(timestamp) FROM defi_rates), '-9 days')"
        ).fetchone()

        if latest_rate_ts and latest_rate_ts['ts']:
            lending_rows = conn.execute(
                "SELECT chain, asset, supply_apy, borrow_apy FROM defi_rates WHERE timestamp=? AND rate_type='lending' ORDER BY chain, asset",
                (latest_rate_ts['ts'],)
            ).fetchall()
            # Get prior lending rates
            prior_lending = {}
            if prior_rate_ts and prior_rate_ts['ts']:
                for r in conn.execute("SELECT chain, asset, borrow_apy FROM defi_rates WHERE timestamp=? AND rate_type='lending'", (prior_rate_ts['ts'],)).fetchall():
                    prior_lending[f"{r['chain']}_{r['asset']}"] = r['borrow_apy']

            if lending_rows:
                rate_parts = []
                for r in lending_rows:
                    key = f"{r['chain']}_{r['asset']}"
                    prior_borrow = prior_lending.get(key)
                    trend_str = f", trend: {_trend(r['borrow_apy'], prior_borrow)}" if prior_borrow is not None else ""
                    rate_parts.append(f"{r['asset']} ({r['chain']}): supply {r['supply_apy']:.1f}% / borrow {r['borrow_apy']:.1f}%{trend_str}")
                lines.append("Lending (Aave V3): " + " | ".join(rate_parts))

            # --- LP pools with 7d APR trend ---
            lp_rows = conn.execute(
                "SELECT chain, asset, fee_apr, reward_apr, tvl, volume_1d FROM defi_rates WHERE timestamp=? AND rate_type='lp' AND fee_apr > 0 ORDER BY tvl DESC",
                (latest_rate_ts['ts'],)
            ).fetchall()
            prior_lp = {}
            if prior_rate_ts and prior_rate_ts['ts']:
                for r in conn.execute("SELECT chain, asset, fee_apr FROM defi_rates WHERE timestamp=? AND rate_type='lp'", (prior_rate_ts['ts'],)).fetchall():
                    prior_lp[f"{r['chain']}_{r['asset']}"] = r['fee_apr']

            if lp_rows:
                preferred_chains = ('arbitrum', 'base')
                your_pools = [r for r in lp_rows if r['chain'] in preferred_chains]
                ref_pools = [r for r in lp_rows if r['chain'] not in preferred_chains]

                def _fmt_pool(r):
                    key = f"{r['chain']}_{r['asset']}"
                    reward_str = f" + {r['reward_apr']:.1f}% rewards" if (r['reward_apr'] or 0) > 0.1 else ""
                    vol_str = f", ${(r['volume_1d'] or 0)/1e6:.0f}M vol" if (r['volume_1d'] or 0) > 0 else ""
                    prior_apr = prior_lp.get(key)
                    trend_str = f", trend: {_trend(r['fee_apr'], prior_apr)}" if prior_apr is not None else ""
                    return f"{r['asset']} ({r['chain']}): {r['fee_apr']:.1f}% APR{reward_str}, ${(r['tvl'] or 0)/1e6:.1f}M TVL{vol_str}{trend_str}"

                if your_pools:
                    lines.append("LP Pools — Your Chains (arbitrum, base): " + " | ".join(_fmt_pool(r) for r in your_pools))
                if ref_pools:
                    lines.append("LP Pools — Reference (ethereum): " + " | ".join(_fmt_pool(r) for r in ref_pools))

            freshness['defi_rates'] = f'db ({latest_rate_ts["ts"][:16]})'

            # --- Borrow-to-LP spreads (pre-calculated) ---
            if lending_rows and lp_rows:
                # Build borrow rate lookup: (chain, stable_symbol) -> borrow_apy
                borrow_lookup = {}
                for r in lending_rows:
                    if r['asset'] in ('USDC', 'USDT', 'DAI'):
                        borrow_lookup[(r['chain'], r['asset'])] = r['borrow_apy']

                spread_parts = []
                for lp in lp_rows:
                    if lp['chain'] not in ('arbitrum', 'base'):
                        continue
                    # Determine which stablecoin to borrow (match from pool name)
                    pool_name = lp['asset'] or ''
                    borrow_asset = None
                    for stable in ('USDC', 'USDT', 'DAI'):
                        if stable in pool_name:
                            borrow_asset = stable
                            break
                    if not borrow_asset:
                        continue
                    borrow_rate = borrow_lookup.get((lp['chain'], borrow_asset))
                    if borrow_rate is not None and lp['fee_apr']:
                        net = lp['fee_apr'] - borrow_rate
                        spread_parts.append(f"{lp['asset']} ({lp['chain']}) funded by borrowing {borrow_asset}: {lp['fee_apr']:.1f}% - {borrow_rate:.1f}% = {net:+.1f}% net")

                if spread_parts:
                    lines.append("Borrow-to-LP Spreads: " + " | ".join(spread_parts))

        # --- Volatility with trend ---
        vol_row = conn.execute(
            "SELECT btc_vol_30d, eth_vol_30d, btc_return_7d, btc_return_30d, eth_return_7d, eth_return_30d, btc_range_14d, eth_range_14d, eth_staking_apr FROM market_snapshots WHERE btc_vol_30d IS NOT NULL ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        prior_vol = conn.execute(
            "SELECT btc_vol_30d, eth_vol_30d FROM market_snapshots WHERE btc_vol_30d IS NOT NULL AND timestamp <= datetime((SELECT MAX(timestamp) FROM market_snapshots), '-5 days') ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()

        if vol_row:
            vol_parts = []
            for prefix, label in [('btc', 'BTC'), ('eth', 'ETH')]:
                vol = vol_row[f'{prefix}_vol_30d']
                r7 = vol_row[f'{prefix}_return_7d']
                r30 = vol_row[f'{prefix}_return_30d']
                rng = vol_row[f'{prefix}_range_14d']
                if vol is not None:
                    regime = "Low" if vol < 30 else "Normal" if vol < 60 else "High"
                    parts = [f"30d vol {vol:.0f}% ({regime})"]
                    if prior_vol:
                        pv = prior_vol[f'{prefix}_vol_30d']
                        if pv is not None:
                            parts.append(f"7d prior: {pv:.0f}%, trend: {_vol_trend(vol, pv)}")
                    if r7 is not None: parts.append(f"7d ret {r7:+.1f}%")
                    if r30 is not None: parts.append(f"30d ret {r30:+.1f}%")
                    if rng is not None: parts.append(f"14d range {rng:.1f}%")
                    vol_parts.append(f"{label}: " + ", ".join(parts))
            if vol_parts:
                lines.append("Volatility: " + " | ".join(vol_parts))
            if vol_row['eth_staking_apr']:
                lines.append(f"ETH staking APR: {vol_row['eth_staking_apr']:.1f}%")

        # --- Funding rate 7d trend ---
        funding_trends = []
        prior_market = conn.execute(
            "SELECT * FROM market_snapshots WHERE timestamp <= datetime((SELECT MAX(timestamp) FROM market_snapshots), '-5 days') ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        latest_market = conn.execute("SELECT * FROM market_snapshots ORDER BY timestamp DESC LIMIT 1").fetchone()
        if latest_market and prior_market:
            for prefix, label in [('btc', 'BTC'), ('eth', 'ETH'), ('sol', 'SOL')]:
                curr_fr = latest_market[f'{prefix}_funding_rate']
                prior_fr = prior_market[f'{prefix}_funding_rate']
                if curr_fr is not None and prior_fr is not None:
                    curr_ann = curr_fr * 3 * 365 * 100
                    prior_ann = prior_fr * 3 * 365 * 100
                    funding_trends.append(f"{label}: {curr_ann:+.1f}% (7d prior: {prior_ann:+.1f}%, trend: {_trend(curr_ann, prior_ann)})")
            # OI delta
            oi_trends = []
            for prefix, label in [('btc', 'BTC'), ('eth', 'ETH')]:
                curr_oi = latest_market[f'{prefix}_open_interest']
                prior_oi = prior_market[f'{prefix}_open_interest']
                if curr_oi and prior_oi:
                    delta_pct = ((curr_oi - prior_oi) / prior_oi) * 100
                    direction = "increasing" if delta_pct > 2 else "decreasing" if delta_pct < -2 else "stable"
                    oi_trends.append(f"{label}: ${curr_oi/1e9:.2f}B (7d prior: ${prior_oi/1e9:.2f}B, {delta_pct:+.1f}%, {direction})")
            if oi_trends:
                lines.append("OI Trends: " + " | ".join(oi_trends))
        if funding_trends:
            lines.append("Funding Trends: " + " | ".join(funding_trends))

        conn.close()
    except Exception as e:
        freshness['defi_rates'] = f'error: {str(e)}'

    return "\n".join(lines)


def _format_market_from_db(row: dict) -> str:
    """Format market data from a DB snapshot row — compact single-line groups."""
    lines = []
    # Prices line
    prices = []
    for prefix, label in [('btc','BTC'),('eth','ETH'),('sol','SOL'),('tao','TAO'),('sui','SUI')]:
        p = row.get(f'{prefix}_price')
        if p:
            chg = row.get(f'{prefix}_24h_change')
            chg_str = f" ({chg:+.1f}%)" if chg else ""
            prices.append(f"{label} ${p:,.0f}{chg_str}")
    if prices:
        lines.append("Prices: " + " | ".join(prices))

    # Global line
    parts = []
    if row.get('btc_dominance'): parts.append(f"BTC Dom: {row['btc_dominance']:.1f}%")
    if row.get('total_market_cap'): parts.append(f"MCap: ${row['total_market_cap']/1e12:.2f}T")
    if row.get('fear_greed_index') is not None: parts.append(f"Fear & Greed: {row['fear_greed_index']}")
    if row.get('stablecoin_supply'): parts.append(f"Stablecoins: ${row['stablecoin_supply']/1e9:.1f}B")
    if parts:
        lines.append(" | ".join(parts))

    # Funding line
    funding = []
    for prefix, label in [('btc','BTC'),('eth','ETH'),('sol','SOL')]:
        fr = row.get(f'{prefix}_funding_rate')
        if fr is not None:
            ann = fr * 3 * 365 * 100
            funding.append(f"{label} {fr*100:.4f}% (ann {ann:+.1f}%)")
    if funding:
        lines.append("Funding: " + " | ".join(funding))

    # OI line
    oi_parts = []
    for prefix, label in [('btc','BTC'),('eth','ETH'),('sol','SOL')]:
        oi = row.get(f'{prefix}_open_interest')
        if oi: oi_parts.append(f"{label} ${oi/1e9:.2f}B")
    if oi_parts:
        lines.append("OI: " + " | ".join(oi_parts))

    # Market overview extras
    extras = []
    if row.get('total_volume_24h'):
        extras.append(f"24h Volume: ${row['total_volume_24h']/1e9:.1f}B")
    if row.get('total_defi_tvl'):
        extras.append(f"DeFi TVL: ${row['total_defi_tvl']/1e9:.1f}B")
    if row.get('btc_index_price') and row.get('btc_price'):
        spread = row['btc_price'] - row['btc_index_price']
        extras.append(f"BTC Deribit Index: ${row['btc_index_price']:,.0f} (spot-index spread: ${spread:+,.0f})")
    if extras:
        lines.append(" | ".join(extras))

    return "\n".join(lines) if lines else "Market data from DB (limited fields)"


def _calc_derived_analytics(freshness: dict) -> str:
    """Calculate Z-scores, changes, and percentiles from DB history."""
    from src.storage.portfolio_db import get_connection
    lines = []
    
    try:
        conn = get_connection()
        
        # Get all market snapshots for calculations
        rows = conn.execute(
            "SELECT * FROM market_snapshots ORDER BY timestamp ASC"
        ).fetchall()
        
        if len(rows) < 3:
            freshness['analytics'] = f'insufficient_data ({len(rows)} snapshots)'
            conn.close()
            return f"Derived analytics unavailable — only {len(rows)} market snapshots in DB (need 3+)"
        
        snapshots = [dict(r) for r in rows]
        latest = snapshots[-1]
        freshness['analytics'] = f'computed ({len(snapshots)} snapshots)'
        
        # --- Funding Rate Z-scores ---
        for prefix, label in [('btc', 'BTC'), ('eth', 'ETH'), ('sol', 'SOL')]:
            key = f'{prefix}_funding_rate'
            values = [s[key] for s in snapshots if s.get(key) is not None]
            if len(values) >= 3 and latest.get(key) is not None:
                mean = sum(values) / len(values)
                std = (sum((v - mean)**2 for v in values) / (len(values) - 1)) ** 0.5
                if std > 0:
                    zscore = (latest[key] - mean) / std
                    ann = latest[key] * 3 * 365 * 100
                    lines.append(f"{label} Funding Z-score: {zscore:+.2f} (current ann: {ann:+.1f}%, mean ann: {mean*3*365*100:+.1f}%)")
        
        # --- OI Changes ---
        for prefix, label in [('btc', 'BTC'), ('eth', 'ETH')]:
            key = f'{prefix}_open_interest'
            current = latest.get(key)
            if current:
                # Find snapshot ~7 days ago
                values_with_ts = [(s.get(key), s['timestamp']) for s in snapshots if s.get(key)]
                if len(values_with_ts) >= 2:
                    oldest = values_with_ts[0][0]
                    pct_change = ((current - oldest) / oldest) * 100
                    lines.append(f"{label} OI change (period): {pct_change:+.1f}% (${current/1e9:.2f}B vs ${oldest/1e9:.2f}B)")
                
                # OI percentile
                all_oi = [s.get(key) for s in snapshots if s.get(key)]
                if all_oi:
                    rank = sum(1 for v in all_oi if v <= current) / len(all_oi) * 100
                    lines.append(f"{label} OI percentile: {rank:.0f}th (vs {len(all_oi)} observations)")
        
        # --- Fear & Greed ---
        fg_values = [s.get('fear_greed_index') for s in snapshots if s.get('fear_greed_index') is not None]
        if fg_values:
            fg_mean = sum(fg_values) / len(fg_values)
            fg_current = latest.get('fear_greed_index')
            if fg_current is not None:
                recent = fg_values[-min(7, len(fg_values)):]
                fg_7d_avg = sum(recent) / len(recent)
                trend = "improving" if fg_7d_avg > fg_mean else "declining"
                lines.append(f"Fear & Greed: current={fg_current}, 7d avg={fg_7d_avg:.0f}, overall avg={fg_mean:.0f}, trend={trend}")
        
        # --- Stablecoin Supply Change ---
        sc_values = [(s.get('stablecoin_supply'), s['timestamp']) for s in snapshots if s.get('stablecoin_supply')]
        if len(sc_values) >= 2:
            sc_current = sc_values[-1][0]
            sc_oldest = sc_values[0][0]
            sc_change = ((sc_current - sc_oldest) / sc_oldest) * 100
            lines.append(f"Stablecoin supply change (period): {sc_change:+.2f}% (${sc_current/1e9:.1f}B vs ${sc_oldest/1e9:.1f}B)")

        # --- BTC Dominance Change ---
        dom_values = [s.get('btc_dominance') for s in snapshots if s.get('btc_dominance')]
        if len(dom_values) >= 2:
            dom_current = dom_values[-1]
            dom_7d = dom_values[-min(7, len(dom_values))]
            dom_change = dom_current - dom_7d
            trend = "rising" if dom_change > 0.3 else "declining" if dom_change < -0.3 else "stable"
            lines.append(f"BTC Dominance: {dom_current:.1f}% (7d prior: {dom_7d:.1f}%, change: {dom_change:+.1f}pp, trend: {trend})")

        # --- ETH/BTC Ratio Trend ---
        ratio_values = [s.get('eth_btc_ratio') for s in snapshots if s.get('eth_btc_ratio')]
        if len(ratio_values) >= 2:
            ratio_current = ratio_values[-1]
            ratio_7d = ratio_values[-min(7, len(ratio_values))]
            ratio_change = ((ratio_current - ratio_7d) / ratio_7d) * 100
            trend = "rising" if ratio_change > 1 else "declining" if ratio_change < -1 else "flat"
            lines.append(f"ETH/BTC Ratio: {ratio_current:.6f} (7d prior: {ratio_7d:.6f}, change: {ratio_change:+.1f}%, trend: {trend})")

        # --- BTC vs 200D MA ---
        btc_200d = latest.get('btc_200d_ma')
        btc_price = latest.get('btc_price')
        if btc_200d and btc_price:
            pct_above = ((btc_price - btc_200d) / btc_200d) * 100
            position = "above" if pct_above > 0 else "below"
            lines.append(f"BTC 200D MA: ${btc_200d:,.0f} — current ${btc_price:,.0f} is {pct_above:+.1f}% {position}")
        
        conn.close()
        
    except Exception as e:
        freshness['analytics'] = f'error: {str(e)}'
        return f"Analytics calculation error: {e}"
    
    return "\n".join(lines) if lines else "No derived analytics available yet"


def _calc_support_resistance(freshness: dict) -> str:
    """Calculate weekly pivot points from DB market snapshots.
    Uses the full prior 7 calendar days for high/low/close."""
    from src.storage.portfolio_db import get_connection
    lines = []
    try:
        conn = get_connection()
        # Get snapshots from the prior 7 calendar days (not just last N rows)
        rows = conn.execute(
            "SELECT btc_price, eth_price, timestamp FROM market_snapshots WHERE btc_price IS NOT NULL AND timestamp >= datetime('now', '-7 days') ORDER BY timestamp ASC"
        ).fetchall()
        
        if len(rows) < 3:
            # Fall back to all available data if < 7 days
            rows = conn.execute(
                "SELECT btc_price, eth_price, timestamp FROM market_snapshots WHERE btc_price IS NOT NULL ORDER BY timestamp ASC"
            ).fetchall()
        
        conn.close()
        
        if len(rows) < 3:
            freshness['support_resistance'] = f'insufficient_data ({len(rows)} snapshots)'
            return ""
        
        # Calculate time span for context
        try:
            from datetime import datetime as dt
            first_ts = dt.fromisoformat(rows[0]['timestamp'].replace('Z', ''))
            last_ts = dt.fromisoformat(rows[-1]['timestamp'].replace('Z', ''))
            span_days = (last_ts - first_ts).total_seconds() / 86400
        except Exception:
            span_days = 0
        
        freshness['support_resistance'] = f'db ({len(rows)} snapshots, {span_days:.1f}d span)'
        
        for coin, key in [('BTC', 'btc_price'), ('ETH', 'eth_price')]:
            prices = [r[key] for r in rows if r[key]]
            if len(prices) < 3:
                continue
            high = max(prices)
            low = min(prices)
            close = prices[-1]  # most recent
            
            pivot = (high + low + close) / 3
            r1 = 2 * pivot - low
            r2 = pivot + (high - low)
            s1 = 2 * pivot - high
            s2 = pivot - (high - low)
            
            if close > r1: status = "Above R1, testing R2"
            elif close > pivot: status = "Above pivot, below R1"
            elif close > s1: status = "Below pivot, above S1"
            else: status = "Below S1, testing S2"
            
            lines.append(f"{coin}: R2={r2:,.0f} R1={r1:,.0f} Pivot={pivot:,.0f} S1={s1:,.0f} S2={s2:,.0f}")
            lines.append(f"  Current: {close:,.0f} — {status}")
            lines.append(f"  Weekly range: {low:,.0f} - {high:,.0f} ({(high-low)/close*100:.1f}% spread)")
    except Exception as e:
        freshness['support_resistance'] = f'error: {str(e)}'
    
    return "\n".join(lines) if lines else ""




def _build_portfolio_context(get_portfolio_fn, get_wallets_fn, freshness: dict) -> str:
    """Build portfolio section from latest DB snapshots — each section uses its own latest timestamp."""
    from src.storage.portfolio_db import get_connection

    def _latest_ts(conn, table):
        r = conn.execute(f"SELECT MAX(strftime('%Y-%m-%dT%H:%M:00', timestamp)) as ts FROM {table}").fetchone()
        return r['ts'] if r else None

    try:
        conn = get_connection()

        # Totals from portfolio_snapshots
        ps_ts = _latest_ts(conn, "portfolio_snapshots WHERE status='completed'")
        total = 0
        tokens_val = 0
        lp_val = 0
        if ps_ts:
            totals = conn.execute(
                "SELECT SUM(total_value_usd) as total, SUM(total_tokens_usd) as tokens, SUM(total_lp_usd) as lp FROM portfolio_snapshots WHERE status='completed' AND strftime('%Y-%m-%dT%H:%M:00', timestamp)=?",
                (ps_ts,)
            ).fetchone()
            total = totals['total'] or 0
            tokens_val = totals['tokens'] or 0
            lp_val = totals['lp'] or 0

        freshness['portfolio'] = f'db ({ps_ts[:16] if ps_ts else "no_data"})'
        if not ps_ts:
            conn.close()
            return "No portfolio snapshots in DB yet"

        lines = [f"## PORTFOLIO (Total: ${total:,.0f})"]

        # --- Tokens (own latest) ---
        tk_ts = _latest_ts(conn, "token_snapshots")
        if tk_ts:
            token_rows = conn.execute(
                "SELECT symbol, chain, balance, price_usd, value_usd, wallet FROM token_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=? ORDER BY value_usd DESC",
                (tk_ts,)
            ).fetchall()

            # Load wallet roles
            import os as _os
            wallet_roles = {}
            try:
                wc_path = _os.getenv("WALLET_CONFIG_PATH", "wallet_config.json")
                with open(wc_path) as _f:
                    wc = json.load(_f)
                for addr, info in wc.items():
                    wallet_roles[addr] = info.get('role', 'active')
            except Exception:
                pass

            from src.models import ETH_SYMBOLS, BTC_SYMBOLS, STABLECOIN_SYMBOLS, is_stablecoin, is_yield_stablecoin
            eth_syms = ETH_SYMBOLS
            btc_syms = BTC_SYMBOLS

            groups = {'ETH': [], 'BTC': [], 'Stablecoins': [], 'Yield Stablecoins': []}
            other_tokens = []
            for r in token_rows:
                t = dict(r)
                if t['symbol'] in eth_syms: groups['ETH'].append(t)
                elif t['symbol'] in btc_syms: groups['BTC'].append(t)
                elif is_stablecoin(t['symbol']): groups['Stablecoins'].append(t)
                elif is_yield_stablecoin(t['symbol']): groups['Yield Stablecoins'].append(t)
                else: other_tokens.append(t)

            lines.append(f"\nTokens (${tokens_val:,.0f}, {tokens_val/total*100:.1f}%):" if total > 0 else "\nTokens ($0):")
            
            # Split each group by wallet role (treasury vs active)
            for gname, gtokens in [('BTC', groups['BTC']), ('ETH', groups['ETH'])]:
                if not gtokens:
                    continue
                treasury = [t for t in gtokens if wallet_roles.get(t.get('wallet', ''), 'active') == 'treasury']
                active = [t for t in gtokens if wallet_roles.get(t.get('wallet', ''), 'active') != 'treasury']
                
                if treasury:
                    tval = sum(t['value_usd'] for t in treasury)
                    tpct = tval / total * 100 if total > 0 else 0
                    breakdown = ", ".join(f"{t['balance']:.4f} {t['symbol']} ({t.get('chain','?')})" for t in treasury if t['value_usd'] >= 1)
                    lines.append(f"  {gname} (cold wallet / treasury): ${tval:,.0f} ({tpct:.1f}%) — {breakdown}")
                if active:
                    aval = sum(t['value_usd'] for t in active)
                    apct = aval / total * 100 if total > 0 else 0
                    sym_label = active[0]['symbol'] if len(set(t['symbol'] for t in active)) == 1 else gname
                    breakdown = ", ".join(f"{t['balance']:.4f} {t['symbol']} ({t.get('chain','?')})" for t in active if t['value_usd'] >= 1)
                    lines.append(f"  {sym_label} (hot wallet / active): ${aval:,.0f} ({apct:.1f}%) — {breakdown}")
            
            # Stablecoins — show as one group
            stables = groups['Stablecoins']
            if stables:
                sval = sum(t['value_usd'] for t in stables)
                spct = sval / total * 100 if total > 0 else 0
                breakdown = ", ".join(f"{t['balance']:.4f} {t['symbol']} ({t.get('chain','?')})" for t in stables if t['value_usd'] >= 1)
                lines.append(f"  Stablecoins: ${sval:,.0f} ({spct:.1f}%) — {breakdown}")
            
            yield_stables = groups['Yield Stablecoins']
            if yield_stables:
                yval = sum(t['value_usd'] for t in yield_stables)
                ypct = yval / total * 100 if total > 0 else 0
                breakdown = ", ".join(f"{t['balance']:.4f} {t['symbol']} ({t.get('chain','?')})" for t in yield_stables if t['value_usd'] >= 1)
                lines.append(f"  Yield Stablecoins: ${yval:,.0f} ({ypct:.1f}%) — {breakdown}")
            
            for t in other_tokens:
                if t['value_usd'] >= 1:
                    pct = t['value_usd'] / total * 100 if total > 0 else 0
                    lines.append(f"  {t['symbol']}: ${t['value_usd']:,.0f} ({pct:.1f}%) — {t['balance']:.4f} on {t.get('chain','?')}")

        # --- LPs (own latest) ---
        lp_ts = _latest_ts(conn, "lp_snapshots")
        if lp_ts:
            lp_rows = conn.execute(
                "SELECT token0, token1, chain, protocol, value_usd, range_lower, range_upper, in_range, total_earned_fees_usd, fees_uncollected_usd, fees_collected_usd, daily_apr FROM lp_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?",
                (lp_ts,)
            ).fetchall()
            if lp_rows:
                lines.append(f"\nLPs (${lp_val:,.0f}, {lp_val/total*100:.1f}%):" if total > 0 else "\nLPs:")
                for lp in lp_rows:
                    lp = dict(lp)
                    status = "IN RANGE" if lp.get('in_range') else "OUT OF RANGE"
                    uncollected = lp.get('fees_uncollected_usd', 0) or 0
                    collected = lp.get('fees_collected_usd', 0) or 0
                    fee_str = f", uncollected fees ${uncollected:,.2f}"
                    if collected > 0:
                        fee_str += f", collected ${collected:,.2f}"
                    apr_str = f", APR {lp['daily_apr']*365:.1f}%" if lp.get('daily_apr') else ""
                    pl = lp.get('range_lower', 0)
                    pu = lp.get('range_upper', 0)
                    range_str = f"range {pl:,.0f}-{pu:,.0f}" if pl and pu else "range unavailable"
                    lines.append(f"  [{lp.get('chain','')}] {lp.get('token0','')}/{lp.get('token1','')}: ${lp.get('value_usd',0):,.0f}, {range_str}, {status}{fee_str}{apr_str}")

        # --- Hedges (from latest completed portfolio snapshot) ---
        latest_snap = conn.execute(
            "SELECT id FROM portfolio_snapshots WHERE status='completed' ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if latest_snap:
            hedge_rows = conn.execute(
                "SELECT market, direction, leverage, size_usd, entry_price, current_price, pnl_usd, liquidation_price FROM hedge_snapshots WHERE snapshot_id=?",
                (latest_snap['id'],)
            ).fetchall()
            # Also include active manual hedges
            manual_h = conn.execute(
                "SELECT market, direction, leverage, size_usd, entry_price, current_price, pnl_usd, liquidation_price FROM hedge_positions WHERE is_active=1"
            ).fetchall()
            all_hedges = [dict(h) for h in hedge_rows] + [dict(h) for h in manual_h]
            if all_hedges:
                lines.append("\nHedges:")
                for h in all_hedges:
                    lines.append(f"  [{h.get('market','')}] {h.get('direction','').upper()} {h.get('leverage',0):.0f}x: size ${h.get('size_usd',0):,.0f}, entry {h.get('entry_price',0):,.0f}, PnL ${h.get('pnl_usd',0):+,.2f}, liq {h.get('liquidation_price',0):,.0f}")

        # --- Lending (own latest) ---
        la_ts = _latest_ts(conn, "lending_account_snapshots")
        if la_ts:
            lending_rows = conn.execute(
                "SELECT chain, protocol, total_collateral_usd, total_debt_usd, health_factor, ltv FROM lending_account_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?",
                (la_ts,)
            ).fetchall()
            # Cross-check with live data to exclude closed positions
            live_lending_chains = set()
            try:
                from web_portfolio import get_portfolio_data
                live = get_portfolio_data()
                for aave in live.get('aave_positions', []):
                    if (aave.get('total_collateral_usd', 0) or 0) > 1:
                        live_lending_chains.add(aave.get('chain', ''))
            except Exception:
                live_lending_chains = None  # can't verify, show all

            active_lending = []
            for a in lending_rows:
                a = dict(a)
                coll = a.get('total_collateral_usd', 0) or 0
                debt = a.get('total_debt_usd', 0) or 0
                if coll < 1 and debt < 1:
                    continue
                # If we have live data, only show positions that still exist on-chain
                if live_lending_chains is not None and a.get('chain', '') not in live_lending_chains:
                    continue
                active_lending.append(a)
            if active_lending:
                lines.append("\nLending:")
                for a in active_lending:
                    hf = a.get('health_factor', 0) or 0
                    coll = a.get('total_collateral_usd', 0) or 0
                    debt = a.get('total_debt_usd', 0) or 0
                    current_ltv = (debt / coll * 100) if coll > 0 else 0
                    lines.append(f"  [{a.get('chain','')}] collateral ${coll:,.0f}, debt ${debt:,.0f}, current LTV {current_ltv:.1f}%, HF {hf:.2f}")

        conn.close()
        return "\n".join(lines)

    except Exception as e:
        freshness['portfolio'] = f'error: {str(e)}'
        return f"Portfolio data error: {e}"




def _get_previous_recommendations() -> str:
    """Get recommendations from the most recent AI report with review status if available."""
    try:
        from src.storage.portfolio_db import get_connection
        conn = get_connection()
        row = conn.execute(
            "SELECT full_report_json FROM ai_reports ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row and row['full_report_json']:
            report = json.loads(row['full_report_json'])
            recs = report.get('recommendations', [])
            # Build status lookup from the review section
            reviews = report.get('previous_recommendations_review', [])
            review_map = {}
            for rv in reviews:
                review_map[rv.get('recommendation', '')] = {
                    'status': rv.get('status', 'unknown'),
                    'comment': rv.get('comment', ''),
                }
            if recs:
                lines = []
                for i, rec in enumerate(recs, 1):
                    action = rec.get('action', '').strip()
                    priority = rec.get('priority', 'medium')
                    parts = [f"action: {action}", f"priority: {priority}"]
                    # Try to find matching review status
                    rv = review_map.get(action, {})
                    if rv:
                        status = rv.get('status', 'unknown')
                        comment = rv.get('comment', '')
                        parts.append(f"status: {status}")
                        if comment:
                            parts.append(f"note: {comment}")
                    lines.append(f"{i}. " + " | ".join(parts))
                return "\n".join(lines)
    except Exception:
        pass
    return ""


def generate_report(get_portfolio_fn, get_wallets_fn) -> dict:
    """Generate a full AI advisor report."""
    config = load_ai_config()
    
    # Build prompts
    system_prompt = build_full_system_prompt(config)
    user_context, freshness = build_context(get_portfolio_fn, get_wallets_fn)
    
    # Call LLM
    from src.engines.llm_providers import get_provider
    provider = get_provider(config)
    result = provider.complete(system_prompt, user_context)
    
    report = result["response"]
    
    # Store in DB
    from src.storage.portfolio_db import get_connection
    conn = get_connection()
    conn.execute("""INSERT INTO ai_reports
        (user_id, timestamp, provider, model, market_regime_json, portfolio_alignment,
         summary, full_report_json, previous_recs_review_json, prompt_tokens,
         completion_tokens, data_freshness_json)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now(timezone.utc).isoformat(),
         result["provider"], result["model"],
         json.dumps(report.get("market_regime")),
         report.get("portfolio_assessment", {}).get("alignment", ""),
         report.get("market_analysis", {}).get("summary", ""),
         json.dumps(report),
         json.dumps(report.get("previous_recommendations_review")),
         result["prompt_tokens"], result["completion_tokens"],
         json.dumps(freshness)))
    conn.commit()
    
    # Keep only the latest 5 reports, delete older
    conn.execute("DELETE FROM ai_reports WHERE id NOT IN (SELECT id FROM ai_reports ORDER BY timestamp DESC LIMIT 5)")
    conn.commit()
    conn.close()
    
    return {
        "report": report,
        "freshness": freshness,
        "tokens": {"prompt": result["prompt_tokens"], "completion": result["completion_tokens"]},
    }


def generate_daily_digest(user_id: int = 1) -> dict:
    """Generate a pure DB-driven daily digest — no LLM needed."""
    from src.storage.portfolio_db import get_connection
    conn = get_connection()
    now = datetime.now(timezone.utc)
    ts = now.isoformat()
    
    digest = {
        "timestamp": ts,
        "total_value_usd": 0,
        "value_change_24h_pct": None,
        "value_change_24h_usd": None,
        "token_count": 0,
        "lp_count": 0,
        "lending_count": 0,
        "hedge_count": 0,
        "positions_opened": [],
        "positions_closed": [],
        "positions_out_of_range": [],
        "lp_summary": [],
        "lending_health": [],
        "hedge_health": [],
        "fees_24h_usd": 0,
        "total_fees_usd": 0,
        "average_apr": 0,
    }
    
    # Latest portfolio total — use the timestamp with the most wallets (avoids partial snapshots)
    latest = conn.execute("""
        SELECT strftime('%Y-%m-%dT%H:%M:00', timestamp) as ts, 
               SUM(total_value_usd) as total,
               COUNT(*) as wallet_count
        FROM portfolio_snapshots WHERE status='completed' AND user_id=?
        GROUP BY ts
        HAVING wallet_count >= (SELECT COUNT(DISTINCT wallet) FROM portfolio_snapshots WHERE status='completed' AND user_id=?)
        ORDER BY ts DESC LIMIT 1
    """, (user_id, user_id)).fetchone()
    
    if not latest:
        # Fallback: just use the latest timestamp with highest total
        latest = conn.execute("""
            SELECT strftime('%Y-%m-%dT%H:%M:00', timestamp) as ts, SUM(total_value_usd) as total
            FROM portfolio_snapshots WHERE status='completed' AND user_id=?
            GROUP BY ts ORDER BY ts DESC LIMIT 1
        """, (user_id,)).fetchone()
    
    if latest:
        digest["total_value_usd"] = latest["total"] or 0
        latest_ts_str = latest["ts"]
        
        # Find a complete snapshot from ~24h ago (22-26h window, matching time slot)
        prev = conn.execute("""
            SELECT strftime('%Y-%m-%dT%H:%M:00', timestamp) as ts, SUM(total_value_usd) as total, COUNT(*) as wc
            FROM portfolio_snapshots WHERE status='completed' AND user_id=?
            AND datetime(timestamp) BETWEEN datetime('now', '-26 hours') AND datetime('now', '-22 hours')
            GROUP BY ts
            ORDER BY ABS(
                strftime('%H', timestamp) * 60 + strftime('%M', timestamp)
                - ? * 60 - ?
            ) ASC LIMIT 1
        """, (user_id,
              int(latest_ts_str[11:13]),
              int(latest_ts_str[14:16]),
        )).fetchone()
        
        if not prev:
            # Fallback: widen window to 20-28h and take the best available
            prev = conn.execute("""
                SELECT strftime('%Y-%m-%dT%H:%M:00', timestamp) as ts, SUM(total_value_usd) as total
                FROM portfolio_snapshots WHERE status='completed' AND user_id=?
                AND datetime(timestamp) BETWEEN datetime('now', '-28 hours') AND datetime('now', '-20 hours')
                GROUP BY ts ORDER BY total DESC LIMIT 1
            """, (user_id,)).fetchone()
        
        if not prev:
            # No snapshot within 28h — leave change as 0 / N/A
            pass
        
        if prev and prev["total"] and prev["total"] > 0:
            change = digest["total_value_usd"] - prev["total"]
            digest["value_change_24h_usd"] = change
            digest["value_change_24h_pct"] = (change / prev["total"]) * 100
    
    # Position counts — use the same timestamp as the total
    snap_ts = latest['ts'] if latest else None
    if snap_ts:
        tc = conn.execute("SELECT COUNT(DISTINCT symbol) as c FROM token_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?", (snap_ts,)).fetchone()
        digest["token_count"] = tc['c'] if tc else 0
        lc = conn.execute("SELECT COUNT(DISTINCT position_id) as c FROM lp_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?", (snap_ts,)).fetchone()
        digest["lp_count"] = lc['c'] if lc else 0
        lac = conn.execute("SELECT COUNT(*) as c FROM lending_account_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?", (snap_ts,)).fetchone()
        digest["lending_count"] = lac['c'] if lac else 0
        hc_snap = conn.execute("SELECT id FROM portfolio_snapshots WHERE status='completed' ORDER BY timestamp DESC LIMIT 1").fetchone()
        hc = conn.execute("SELECT COUNT(*) as c FROM hedge_snapshots WHERE snapshot_id=?", (hc_snap['id'],)).fetchone() if hc_snap else None
        digest["hedge_count"] = (hc['c'] if hc else 0) + conn.execute("SELECT COUNT(*) as c FROM hedge_positions WHERE is_active=1 AND user_id=?", (user_id,)).fetchone()['c']

    # Positions out of range (from latest LP snapshots)
    latest_ts = conn.execute(
        "SELECT MAX(strftime('%Y-%m-%dT%H:%M:00', timestamp)) as ts FROM lp_snapshots WHERE user_id=?", (user_id,)
    ).fetchone()
    if latest_ts and latest_ts['ts']:
        oor = conn.execute(
            "SELECT token0, token1, chain FROM lp_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=? AND in_range=0",
            (latest_ts['ts'],)
        ).fetchall()
        digest["positions_out_of_range"] = [f"{r['token0']}/{r['token1']} ({r['chain']})" for r in oor]
    
    # Also check manual LPs
    manual_oor = conn.execute(
        "SELECT token0, token1, chain FROM lp_positions WHERE is_active=1 AND in_range=0 AND user_id=?", (user_id,)
    ).fetchall()
    for r in manual_oor:
        digest["positions_out_of_range"].append(f"{r['token0']}/{r['token1']} ({r['chain']}) [manual]")
    
    # Positions opened/closed in last 24h
    opened_lps = conn.execute(
        "SELECT token0, token1, chain FROM lp_positions WHERE user_id=? AND created_at >= datetime('now', '-24 hours')",
        (user_id,)
    ).fetchall()
    digest["positions_opened"] += [f"LP: {r['token0']}/{r['token1']} ({r['chain']})" for r in opened_lps]
    
    opened_hedges = conn.execute(
        "SELECT market, direction, exchange FROM hedge_positions WHERE user_id=? AND created_at >= datetime('now', '-24 hours')",
        (user_id,)
    ).fetchall()
    digest["positions_opened"] += [f"Hedge: {r['market']} {r['direction']} ({r['exchange']})" for r in opened_hedges]
    
    closed_lps = conn.execute(
        "SELECT token0, token1, chain FROM lp_positions WHERE user_id=? AND is_active=0 AND updated_at >= datetime('now', '-24 hours')",
        (user_id,)
    ).fetchall()
    digest["positions_closed"] += [f"LP: {r['token0']}/{r['token1']} ({r['chain']})" for r in closed_lps]
    
    closed_hedges = conn.execute(
        "SELECT market, direction, exchange FROM hedge_positions WHERE user_id=? AND is_active=0 AND updated_at >= datetime('now', '-24 hours')",
        (user_id,)
    ).fetchall()
    digest["positions_closed"] += [f"Hedge: {r['market']} {r['direction']} ({r['exchange']})" for r in closed_hedges]
    
    # Hedge health (from latest hedge snapshots + manual)
    # Use the latest COMPLETED portfolio snapshot's hedge data to ensure
    # closed positions are excluded (they won't appear in new snapshots)
    latest_snap = conn.execute(
        "SELECT id FROM portfolio_snapshots WHERE status='completed' ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    if latest_snap:
        hedges = conn.execute(
            "SELECT market, direction, pnl_usd, pnl_pct, liquidation_price, current_price, leverage "
            "FROM hedge_snapshots WHERE snapshot_id=? AND current_price > 0",
            (latest_snap['id'],)
        ).fetchall()
        for h in hedges:
            h = dict(h)
            cp = h.get('current_price', 0)
            if not cp or cp == 0:
                digest["hedge_health"].append({
                    "market": h.get('market'), "direction": h.get('direction'),
                    "leverage": round(h.get('leverage', 0)),
                    "price_unavailable": True
                })
                continue
            liq_dist = abs(h.get('liquidation_price', 0) - cp) / cp * 100
            digest["hedge_health"].append({
                "market": h.get('market'), "direction": h.get('direction'),
                "pnl_usd": h.get('pnl_usd', 0), "leverage": round(h.get('leverage', 0)),
                "liq_distance_pct": liq_dist
            })
    
    manual_hedges = conn.execute(
        "SELECT market, direction, pnl_usd, leverage, liquidation_price, current_price FROM hedge_positions WHERE is_active=1 AND user_id=?",
        (user_id,)
    ).fetchall()
    for h in manual_hedges:
        h = dict(h)
        cp = h.get('current_price', 0)
        if not cp or cp == 0:
            digest["hedge_health"].append({
                "market": h.get('market'), "direction": h.get('direction'),
                "leverage": round(h.get('leverage', 0)),
                "price_unavailable": True, "source": "manual"
            })
            continue
        liq_dist = abs(h.get('liquidation_price', 0) - cp) / cp * 100
        digest["hedge_health"].append({
            "market": h.get('market'), "direction": h.get('direction'),
            "pnl_usd": h.get('pnl_usd', 0), "leverage": round(h.get('leverage', 0)),
            "liq_distance_pct": liq_dist, "source": "manual"
        })
    
    # Total fees and APR — actual 24h delta per position
    # For each LP with a position_id, compare current total_earned_fees_usd
    # against the closest snapshot ~24h ago. This gives real fees earned in
    # the last day and a true daily APR (annualised in average_apr).
    if latest_ts and latest_ts['ts']:
        # Current total fees (lifetime, for the total_fees_usd field)
        fee_now = conn.execute(
            "SELECT SUM(fees_uncollected_usd + fees_collected_usd) as fees FROM lp_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?",
            (latest_ts['ts'],)
        ).fetchone()
        digest["total_fees_usd"] = (fee_now["fees"] or 0) if fee_now else 0

        # Fetch current LP snapshots
        lp_rows = conn.execute(
            "SELECT token0, token1, chain, protocol, range_lower, range_upper, current_price, in_range, value_usd, daily_apr, total_earned_fees_usd, fees_uncollected_usd, fees_collected_usd, position_id FROM lp_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?",
            (latest_ts['ts'],)
        ).fetchall()

        total_fees_24h = 0.0
        apr_weighted_sum = 0.0   # sum of (daily_apr_24h * value_usd) for weighted avg
        apr_value_sum = 0.0      # sum of value_usd for positions with known 24h data

        for lp in lp_rows:
            lp = dict(lp)
            pair = f"{lp.get('token0','?')}/{lp.get('token1','?')}"
            rl = lp.get('range_lower') or 0
            ru = lp.get('range_upper') or 0
            cp = lp.get('current_price') or 0
            in_range = lp.get('in_range', True)
            value_usd = lp.get('value_usd', 0)
            pid = lp.get('position_id', '')

            # High-water-mark for lifetime total earned
            total_earned = lp.get('total_earned_fees_usd', 0)
            uncollected = lp.get('fees_uncollected_usd', 0)
            if pid and pid != 'None':
                hwm = conn.execute(
                    "SELECT MAX(total_earned_fees_usd) as fees FROM lp_snapshots WHERE position_id=?",
                    (pid,)
                ).fetchone()
                if hwm and hwm['fees'] and hwm['fees'] > total_earned:
                    total_earned = hwm['fees']
                collected = max(0, total_earned - uncollected)
            else:
                collected = lp.get('fees_collected_usd', 0)

            # --- 24h fee delta: find closest snapshot ~24h ago for this position ---
            pos_fees_24h = 0.0
            pos_daily_apr = None  # None = unknown (no prior snapshot)
            has_24h_data = False

            if pid and pid != 'None':
                # Use the CURRENT snapshot's total_earned (not the HWM) for a fair 24h diff
                current_earned = lp.get('total_earned_fees_usd', 0) or 0

                # Find the snapshot closest to 24h ago (18-30h window, ordered by proximity to 24h)
                prev_snap = conn.execute("""
                    SELECT total_earned_fees_usd,
                           ABS(julianday('now') - julianday(timestamp) - 1.0) as dist
                    FROM lp_snapshots
                    WHERE position_id = ?
                      AND datetime(timestamp) BETWEEN datetime('now', '-30 hours') AND datetime('now', '-18 hours')
                    ORDER BY dist ASC LIMIT 1
                """, (pid,)).fetchone()

                if prev_snap:
                    prev_earned = prev_snap['total_earned_fees_usd'] or 0
                    pos_fees_24h = max(0, current_earned - prev_earned)
                    if value_usd > 0:
                        pos_daily_apr = (pos_fees_24h / value_usd) * 100
                    else:
                        pos_daily_apr = 0.0
                    has_24h_data = True

            # Accumulate for digest-level totals (only positions with known 24h data)
            if has_24h_data:
                total_fees_24h += pos_fees_24h
                if value_usd > 0 and pos_daily_apr is not None:
                    apr_weighted_sum += pos_daily_apr * value_usd
                    apr_value_sum += value_usd

            # Position within range as percentage
            range_pct = ((cp - rl) / (ru - rl) * 100) if ru > rl else 50
            range_pct = max(0, min(100, range_pct))
            digest["lp_summary"].append({
                "pair": pair,
                "chain": lp.get('chain', ''),
                "in_range": in_range,
                "range_pct": round(range_pct),
                "range_lower": rl,
                "range_upper": ru,
                "current_price": cp,
                "value_usd": value_usd,
                "apr": (pos_daily_apr * 365) if pos_daily_apr is not None else None,
                "daily_apr": pos_daily_apr,
                "fees_24h": pos_fees_24h,
                "total_earned_fees_usd": total_earned,
                "fees_uncollected_usd": uncollected,
                "fees_collected_usd": collected,
            })

        digest["fees_24h_usd"] = total_fees_24h
        # Weighted average APR (annualised) — only from positions with known 24h data
        if apr_value_sum > 0:
            digest["average_apr"] = (apr_weighted_sum / apr_value_sum) * 365
        else:
            digest["average_apr"] = 0

    # Enrich LP data from live portfolio — replace snapshot LPs with live data
    # This ensures the digest shows current positions (not stale/closed ones)
    # and avoids Zerion duplicates by only including positions with a token_id.
    try:
        from web_portfolio import get_portfolio_data
        live = get_portfolio_data()
        live_lps = [lp for lp in live.get('lp_positions', []) if lp.get('token_id')]
        if live_lps:
            digest["lp_summary"] = []
            digest["lp_count"] = len(live_lps)
            # Rebuild out-of-range from live data (replaces stale DB snapshot data)
            digest["positions_out_of_range"] = []
            for live_lp in live_lps:
                pair = f"{live_lp.get('token0_symbol','?')}/{live_lp.get('token1_symbol','?')}"
                rl = live_lp.get('price_lower') or 0
                ru = live_lp.get('price_upper') or 0
                cp = live_lp.get('current_price') or 0
                in_range = live_lp.get('in_range', True)
                value_usd = live_lp.get('total_value_usd', 0)
                uncollected = live_lp.get('total_fees_usd', 0)
                total_earned = live_lp.get('total_earned_fees_usd', 0)
                collected = max(0, total_earned - uncollected)
                daily_apr = live_lp.get('daily_apr')
                apr = (daily_apr * 365) if daily_apr is not None else None

                range_pct = ((cp - rl) / (ru - rl) * 100) if ru > rl else 50
                range_pct = max(0, min(100, range_pct))

                digest["lp_summary"].append({
                    "pair": pair,
                    "chain": live_lp.get('chain', ''),
                    "in_range": in_range,
                    "range_pct": round(range_pct),
                    "range_lower": rl,
                    "range_upper": ru,
                    "current_price": cp,
                    "value_usd": value_usd,
                    "apr": apr,
                    "daily_apr": daily_apr,
                    "fees_24h": digest.get("fees_24h_usd", 0) if len(live_lps) == 1 else 0,
                    "total_earned_fees_usd": total_earned,
                    "fees_uncollected_usd": uncollected,
                    "fees_collected_usd": collected,
                })
                if not in_range:
                    digest["positions_out_of_range"].append(f"{pair} ({live_lp.get('chain', '')})")
    except Exception as e:
        print(f"Digest: could not enrich LP fees from live data: {e}")

    # Lending health from latest lending account snapshots
    if snap_ts:
        lending_rows = conn.execute(
            "SELECT chain, protocol, total_collateral_usd, total_debt_usd, health_factor, ltv FROM lending_account_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?",
            (snap_ts,)
        ).fetchall()
        for la in lending_rows:
            la = dict(la)
            if (la.get('total_collateral_usd') or 0) > 0:
                # Pull the per-asset supplied/borrowed legs for the same chain+protocol
                # at the same snapshot timestamp.
                asset_rows = conn.execute(
                    "SELECT side, symbol, balance, value_usd, apy "
                    "FROM lending_snapshots "
                    "WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=? "
                    "AND chain=? AND protocol=?",
                    (snap_ts, la.get('chain', ''), la.get('protocol', ''))
                ).fetchall()
                supplied = []
                borrowed = []
                for ar in asset_rows:
                    ar = dict(ar)
                    entry = {
                        "symbol": ar.get('symbol', ''),
                        "balance": ar.get('balance') or 0,
                        "value_usd": ar.get('value_usd') or 0,
                        "apy": ar.get('apy') or 0,
                    }
                    if ar.get('side') == 'supply':
                        supplied.append(entry)
                    elif ar.get('side') == 'borrow':
                        borrowed.append(entry)
                digest["lending_health"].append({
                    "chain": la.get('chain', ''),
                    "protocol": la.get('protocol', ''),
                    "collateral_usd": la.get('total_collateral_usd', 0),
                    "debt_usd": la.get('total_debt_usd', 0),
                    "health_factor": la.get('health_factor', 0),
                    "ltv": la.get('ltv', 0),
                    "supplied": supplied,
                    "borrowed": borrowed,
                })

    # Also add manual LP fees
    manual_fees = conn.execute(
        "SELECT SUM(fees_uncollected_usd + fees_collected_usd) as fees FROM lp_positions WHERE is_active=1 AND user_id=?",
        (user_id,)
    ).fetchone()
    if manual_fees and manual_fees["fees"]:
        digest["total_fees_usd"] += manual_fees["fees"]
    
    # Save to DB
    conn.execute("""INSERT INTO daily_digests
        (user_id, timestamp, total_value_usd, value_change_24h_pct, value_change_24h_usd,
         positions_opened, positions_closed, positions_out_of_range,
         hedge_health_json, total_fees_usd, average_apr, digest_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, ts, digest["total_value_usd"], digest["value_change_24h_pct"],
         digest["value_change_24h_usd"],
         json.dumps(digest["positions_opened"]), json.dumps(digest["positions_closed"]),
         json.dumps(digest["positions_out_of_range"]),
         json.dumps(digest["hedge_health"]),
         digest["total_fees_usd"], digest["average_apr"],
         json.dumps(digest)))
    conn.commit()
    conn.close()
    
    return digest
