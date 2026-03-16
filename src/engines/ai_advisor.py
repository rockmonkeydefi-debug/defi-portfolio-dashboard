"""AI Advisor — builds context from portfolio + market data and generates reports via LLM."""

import os
import json
import math
import time
import requests
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
    return {"provider": "openai", "model": "gpt-4o", "schedule_utc_hour": 8, "strategies": {}}


def save_ai_config(config: dict):
    """Save AI configuration."""
    os.makedirs(os.path.dirname(AI_CONFIG_PATH), exist_ok=True)
    with open(AI_CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)


def load_system_prompt() -> str:
    """Load the base system prompt."""
    with open(SYSTEM_PROMPT_PATH, 'r') as f:
        return f.read()


def build_full_system_prompt(config: dict) -> str:
    """Combine base prompt + user custom prompt + strategies."""
    base = load_system_prompt()
    custom = config.get("custom_system_prompt", "")
    strategies = config.get("strategies", {})
    
    parts = [base]
    if custom:
        parts.append(f"\n## Additional Instructions\n{custom}")
    if strategies:
        parts.append("\n## User Strategy Preferences")
        for regime, text in strategies.items():
            if text:
                parts.append(f"### {regime.title()} Market Strategy\n{text}")
    return "\n".join(parts)


def build_context(get_portfolio_fn, get_wallets_fn) -> tuple:
    """Build the user message context from all data sources.
    Uses DB data first, falls back to API if stale (>4 hours).
    Returns (context_string, freshness_dict).
    """
    freshness = {}
    sections = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # --- Market Data (DB first, API fallback) ---
    market = _get_market_data_smart(freshness)
    sections.append(f"## MARKET DATA (as of {ts})")
    sections.append(market)

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

    # --- Investor Profile ---
    profile_text = _build_profile_context()
    if profile_text:
        sections.append("## INVESTOR PROFILE")
        sections.append(profile_text)

    # --- Previous Recommendations ---
    prev_recs = _get_previous_recommendations()
    if prev_recs:
        sections.append("## PREVIOUS RECOMMENDATIONS (from last report)")
        sections.append(prev_recs)

    return "\n\n".join(sections), freshness


def _get_market_data_smart(freshness: dict) -> str:
    """Get market data from DB if fresh (<4h), otherwise fetch from APIs."""
    from src.storage.portfolio_db import get_connection
    
    # Check DB for recent market snapshot
    try:
        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM market_snapshots ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        conn.close()
        
        if row:
            row = dict(row)
            # Check if data is fresh (< 4 hours old)
            from datetime import datetime as dt
            try:
                snap_time = dt.fromisoformat(row['timestamp'].replace('Z', ''))
                age_hours = (datetime.now(timezone.utc).replace(tzinfo=None) - snap_time).total_seconds() / 3600
            except Exception:
                age_hours = 999
            
            if age_hours < 4:
                freshness['market'] = f'db (age: {age_hours:.1f}h)'
                return _format_market_from_db(row)
            else:
                freshness['market_db_age'] = f'{age_hours:.1f}h (stale, fetching fresh)'
    except Exception:
        pass
    
    # DB data is stale or missing — fetch from APIs
    return _fetch_market_data(freshness)


def _format_market_from_db(row: dict) -> str:
    """Format market data from a DB snapshot row."""
    lines = []
    if row.get('btc_price'): lines.append(f"BTC: ${row['btc_price']:,.2f}")
    if row.get('eth_price'): lines.append(f"ETH: ${row['eth_price']:,.2f}")
    if row.get('sol_price'): lines.append(f"SOL: ${row['sol_price']:,.2f}")
    if row.get('tao_price'): lines.append(f"TAO: ${row['tao_price']:,.2f}")
    if row.get('sui_price'): lines.append(f"SUI: ${row['sui_price']:,.2f}")
    if row.get('btc_dominance'): lines.append(f"BTC Dominance: {row['btc_dominance']:.1f}%")
    if row.get('total_market_cap'): lines.append(f"Total Market Cap: ${row['total_market_cap']/1e12:.2f}T")
    if row.get('total_volume_24h'): lines.append(f"24h Volume: ${row['total_volume_24h']/1e9:.1f}B")
    if row.get('stablecoin_supply'): lines.append(f"Stablecoin Supply: ${row['stablecoin_supply']/1e9:.1f}B")
    if row.get('fear_greed_index') is not None: lines.append(f"Fear & Greed: {row['fear_greed_index']}")
    for prefix in ['btc', 'eth', 'sol']:
        fr = row.get(f'{prefix}_funding_rate')
        oi = row.get(f'{prefix}_open_interest')
        if fr is not None:
            ann = fr * 3 * 365 * 100
            oi_str = f", OI: ${oi/1e9:.2f}B" if oi else ""
            lines.append(f"{prefix.upper()} Funding: {fr*100:.4f}% (ann: {ann:+.1f}%){oi_str}")
    if row.get('eth_usdc_fee_apr'): lines.append(f"ETH/USDC LP APR: {row['eth_usdc_fee_apr']:.2f}%")
    if row.get('wbtc_usdc_fee_apr'): lines.append(f"WBTC/USDC LP APR: {row['wbtc_usdc_fee_apr']:.2f}%")
    if row.get('eth_staking_apr'): lines.append(f"ETH Staking APR: {row['eth_staking_apr']:.2f}%")
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
        
        # --- Volatility from token_prices_daily ---
        for symbol in ['BTC', 'ETH']:
            prices = conn.execute(
                "SELECT price_usd FROM token_prices_daily WHERE symbol=? ORDER BY timestamp ASC",
                (symbol,)
            ).fetchall()
            if len(prices) >= 7:
                p = [r['price_usd'] for r in prices]
                rets = [math.log(p[i]/p[i-1]) for i in range(1, len(p))]
                if rets:
                    mean_r = sum(rets) / len(rets)
                    var = sum((r - mean_r)**2 for r in rets) / (len(rets) - 1)
                    vol = (var ** 0.5) * (365 ** 0.5) * 100
                    regime = "Low" if vol < 30 else "Normal" if vol < 60 else "High"
                    # Returns
                    ret_7d = ((p[-1] / p[-min(7, len(p))]) - 1) * 100
                    ret_all = ((p[-1] / p[0]) - 1) * 100
                    lines.append(f"{symbol} Realized Vol: {vol:.1f}% ({regime}), 7d return: {ret_7d:+.2f}%, period return: {ret_all:+.2f}%")
        
        conn.close()
        
    except Exception as e:
        freshness['analytics'] = f'error: {str(e)}'
        return f"Analytics calculation error: {e}"
    
    return "\n".join(lines) if lines else "No derived analytics available yet"
    """Fetch fresh market data with DB fallback."""
    lines = []
    
    # Prices
    try:
        r = requests.get(
            'https://api.coingecko.com/api/v3/simple/price'
            '?ids=bitcoin,ethereum,solana,bittensor,sui'
            '&vs_currencies=usd&include_24hr_change=true',
            timeout=10)
        if r.ok:
            p = r.json()
            for coin, cg in [('BTC','bitcoin'),('ETH','ethereum'),('SOL','solana'),('TAO','bittensor'),('SUI','sui')]:
                price = p.get(cg, {}).get('usd', 0)
                chg = p.get(cg, {}).get('usd_24h_change', 0)
                if price:
                    lines.append(f"{coin}: ${price:,.2f} (24h: {chg:+.2f}%)")
            freshness['prices'] = 'live'
        else:
            freshness['prices'] = 'api_error'
    except Exception:
        freshness['prices'] = 'failed'
    
    time.sleep(0.5)
    
    # Global
    try:
        r = requests.get('https://api.coingecko.com/api/v3/global', timeout=10)
        if r.ok:
            g = r.json().get('data', {})
            lines.append(f"BTC Dominance: {g.get('market_cap_percentage',{}).get('btc',0):.1f}%")
            lines.append(f"Total Market Cap: ${g.get('total_market_cap',{}).get('usd',0)/1e12:.2f}T")
            lines.append(f"24h Volume: ${g.get('total_volume',{}).get('usd',0)/1e9:.1f}B")
            freshness['global'] = 'live'
    except Exception:
        freshness['global'] = 'failed'
    
    # Funding + OI
    try:
        for sym, name in [('BTCUSDT','BTC'),('ETHUSDT','ETH'),('SOLUSDT','SOL')]:
            r = requests.get(f'https://api.bybit.com/v5/market/tickers?category=linear&symbol={sym}', timeout=10)
            if r.ok:
                item = r.json().get('result',{}).get('list',[{}])[0]
                fr = float(item.get('fundingRate', 0))
                oi = float(item.get('openInterestValue', 0))
                ann = fr * 3 * 365 * 100
                lines.append(f"{name} Funding: {fr*100:.4f}% (ann: {ann:+.1f}%), OI: ${oi/1e9:.2f}B")
        freshness['funding'] = 'live'
    except Exception:
        freshness['funding'] = 'failed'
    
    # Fear & Greed
    try:
        r = requests.get('https://api.alternative.me/fng/?limit=30', timeout=10)
        if r.ok:
            fg = r.json().get('data', [])
            current = int(fg[0]['value']) if fg else 0
            vals = [int(d['value']) for d in fg]
            avg7 = sum(vals[:7]) / min(7, len(vals)) if vals else 0
            avg30 = sum(vals) / len(vals) if vals else 0
            trend = "improving" if avg7 > avg30 else "declining"
            lines.append(f"Fear & Greed: {current} (7d avg: {avg7:.0f}, 30d avg: {avg30:.0f}, trend: {trend})")
            freshness['fear_greed'] = 'live'
    except Exception:
        freshness['fear_greed'] = 'failed'
    
    # Stablecoin supply
    try:
        r = requests.get('https://stablecoins.llama.fi/stablecoinchains', timeout=10)
        if r.ok:
            total = 0
            for chain in r.json():
                circ = chain.get('totalCirculatingUSD')
                if isinstance(circ, dict): total += sum(circ.values())
                elif circ: total += float(circ)
            lines.append(f"Stablecoin Supply: ${total/1e9:.1f}B")
            freshness['stablecoins'] = 'live'
    except Exception:
        freshness['stablecoins'] = 'failed'
    
    # BTC/ETH returns and vol from price history
    time.sleep(1)
    for coin, cg_id in [('BTC', 'bitcoin'), ('ETH', 'ethereum')]:
        try:
            r = requests.get(f'https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart?vs_currency=usd&days=30&interval=daily', timeout=10)
            if r.ok:
                prices = [p[1] for p in r.json().get('prices', [])]
                if len(prices) >= 7:
                    ret7 = ((prices[-1] / prices[-7]) - 1) * 100
                    ret30 = ((prices[-1] / prices[0]) - 1) * 100
                    rets = [math.log(prices[i]/prices[i-1]) for i in range(1, len(prices))]
                    mean = sum(rets) / len(rets)
                    var = sum((r - mean)**2 for r in rets) / (len(rets) - 1)
                    vol = math.sqrt(var) * math.sqrt(365) * 100
                    lines.append(f"{coin} 7d return: {ret7:+.2f}%, 30d return: {ret30:+.2f}%, 30d vol: {vol:.1f}%")
                freshness[f'{coin.lower()}_history'] = 'live'
            time.sleep(1)
        except Exception:
            freshness[f'{coin.lower()}_history'] = 'failed'
    
    if not lines:
        lines.append("Market data unavailable — all API calls failed")
    
    return "\n".join(lines)


def _fetch_market_data(freshness: dict) -> str:
    """Fetch fresh market data from APIs (fallback when DB is stale)."""
    lines = []
    try:
        r = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana,bittensor,sui&vs_currencies=usd&include_24hr_change=true', timeout=10)
        if r.ok:
            p = r.json()
            for coin, cg in [('BTC','bitcoin'),('ETH','ethereum'),('SOL','solana'),('TAO','bittensor'),('SUI','sui')]:
                price = p.get(cg, {}).get('usd', 0)
                chg = p.get(cg, {}).get('usd_24h_change', 0)
                if price: lines.append(f"{coin}: ${price:,.2f} (24h: {chg:+.2f}%)")
            freshness['prices'] = 'live'
    except Exception:
        freshness['prices'] = 'failed'
    time.sleep(0.5)
    try:
        r = requests.get('https://api.coingecko.com/api/v3/global', timeout=10)
        if r.ok:
            g = r.json().get('data', {})
            lines.append(f"BTC Dominance: {g.get('market_cap_percentage',{}).get('btc',0):.1f}%")
            lines.append(f"Total Market Cap: ${g.get('total_market_cap',{}).get('usd',0)/1e12:.2f}T")
            freshness['global'] = 'live'
    except Exception:
        freshness['global'] = 'failed'
    try:
        for sym, name in [('BTCUSDT','BTC'),('ETHUSDT','ETH'),('SOLUSDT','SOL')]:
            r = requests.get(f'https://api.bybit.com/v5/market/tickers?category=linear&symbol={sym}', timeout=10)
            if r.ok:
                item = r.json().get('result',{}).get('list',[{}])[0]
                fr = float(item.get('fundingRate', 0))
                oi = float(item.get('openInterestValue', 0))
                lines.append(f"{name} Funding: {fr*100:.4f}% (ann: {fr*3*365*100:+.1f}%), OI: ${oi/1e9:.2f}B")
        freshness['funding'] = 'live'
    except Exception:
        freshness['funding'] = 'failed'
    try:
        r = requests.get('https://api.alternative.me/fng/?limit=1', timeout=10)
        if r.ok:
            fg = r.json().get('data', [])
            if fg: lines.append(f"Fear & Greed: {fg[0]['value']}")
            freshness['fear_greed'] = 'live'
    except Exception:
        freshness['fear_greed'] = 'failed'
    if not lines:
        lines.append("Market data unavailable — all API calls failed")
    return "\n".join(lines)


def _calc_support_resistance(freshness: dict) -> str:
    """Calculate weekly pivot points from OHLC data."""
    lines = []
    for coin, cg_id in [('BTC', 'bitcoin'), ('ETH', 'ethereum')]:
        try:
            r = requests.get(f'https://api.coingecko.com/api/v3/coins/{cg_id}/ohlc?vs_currency=usd&days=14', timeout=10)
            if r.ok:
                ohlc = r.json()  # [[ts, o, h, l, c], ...]
                if len(ohlc) >= 7:
                    # Last 7 days for weekly levels
                    week = ohlc[-7:]
                    high = max(d[2] for d in week)
                    low = min(d[3] for d in week)
                    close = week[-1][4]
                    current = close
                    
                    pivot = (high + low + close) / 3
                    r1 = 2 * pivot - low
                    r2 = pivot + (high - low)
                    s1 = 2 * pivot - high
                    s2 = pivot - (high - low)
                    
                    status = ""
                    if current > r1:
                        status = f"Above R1, testing R2"
                    elif current > pivot:
                        status = f"Above pivot, below R1"
                    elif current > s1:
                        status = f"Below pivot, above S1"
                    else:
                        status = f"Below S1, testing S2"
                    
                    lines.append(f"{coin}: R2={r2:,.0f} R1={r1:,.0f} Pivot={pivot:,.0f} S1={s1:,.0f} S2={s2:,.0f}")
                    lines.append(f"  Current: {current:,.0f} — {status}")
                    lines.append(f"  Weekly range: {low:,.0f} - {high:,.0f}")
                freshness[f'{coin.lower()}_sr'] = 'live'
            time.sleep(1)
        except Exception:
            freshness[f'{coin.lower()}_sr'] = 'failed'
    return "\n".join(lines) if lines else ""


def _build_portfolio_context(get_portfolio_fn, get_wallets_fn, freshness: dict) -> str:
    """Build portfolio section from latest data."""
    try:
        portfolio = get_portfolio_fn(force_refresh=False)  # Use cached data
        freshness['portfolio'] = 'cached'
    except Exception:
        freshness['portfolio'] = 'failed'
        return "Portfolio data unavailable"
    
    lines = []
    total = portfolio.get('total_value', 0)
    lines.append(f"Total Value: ${total:,.0f}")
    lines.append(f"  Tokens: ${portfolio.get('total_tokens_value',0):,.0f} ({portfolio.get('total_tokens_value',0)/total*100:.1f}%)" if total > 0 else "  Tokens: $0")
    lines.append(f"  LP Positions: ${portfolio.get('total_lp_value',0):,.0f} ({portfolio.get('total_lp_value',0)/total*100:.1f}%)" if total > 0 else "  LP: $0")
    
    # Token groups
    tokens = portfolio.get('tokens', [])
    groups = {'ETH': [], 'BTC': [], 'Stablecoins': [], 'Other': []}
    eth_syms = ['ETH','WETH','stETH','wstETH','cbETH','rETH','weETH']
    btc_syms = ['BTC','WBTC','cbBTC']
    stable_syms = ['USDC','USDT','DAI','FRAX','GHO','USDe','USDS']
    for t in tokens:
        if t['symbol'] in eth_syms: groups['ETH'].append(t)
        elif t['symbol'] in btc_syms: groups['BTC'].append(t)
        elif t['symbol'] in stable_syms: groups['Stablecoins'].append(t)
        else: groups['Other'].append(t)
    
    lines.append("\nToken Allocation:")
    for gname, gtokens in groups.items():
        gval = sum(t['value_usd'] for t in gtokens)
        if gval > 0:
            pct = gval / total * 100 if total > 0 else 0
            lines.append(f"  {gname}: ${gval:,.0f} ({pct:.1f}%)")
    
    # LP positions
    lps = portfolio.get('lp_positions', [])
    if lps:
        lines.append("\nActive LP Positions:")
        for lp in lps:
            status = "IN RANGE" if lp.get('in_range') else "OUT OF RANGE"
            fees = lp.get('total_earned_fees_usd', 0)
            apr_str = f", APR {lp['daily_apr']*365:.1f}%" if lp.get('daily_apr') else ""
            lines.append(f"  [{lp.get('chain','')}] {lp.get('pair','')}: ${lp.get('total_value_usd',0):,.0f}, range {lp.get('price_lower',0):,.0f}-{lp.get('price_upper',0):,.0f}, {status}, fees ${fees:,.2f}{apr_str}")
    
    # Hedges
    hedges = portfolio.get('gmx_positions', [])
    if hedges:
        lines.append("\nActive Hedges:")
        for h in hedges:
            direction = "LONG" if h.get('is_long') else "SHORT"
            lines.append(f"  [{h.get('market','')}] {direction} {h.get('leverage',0):.1f}x: size ${h.get('size_usd',0):,.0f}, entry {h.get('entry_price',0):,.0f}, PnL ${h.get('pnl_usd',0):+,.2f}, liq {h.get('liquidation_price',0):,.0f}")
    
    # AAVE
    aave = portfolio.get('aave_positions', [])
    if aave:
        lines.append("\nLending Positions:")
        for a in aave:
            lines.append(f"  [{a.get('chain','')}] Collateral ${a.get('total_collateral_usd',0):,.2f}, Debt ${a.get('total_debt_usd',0):,.2f}, HF {a.get('health_factor',0):.2f}")
    
    # Manual positions
    try:
        from src.storage.portfolio_db import get_connection
        conn = get_connection()
        manual_lps = conn.execute("SELECT * FROM lp_positions WHERE is_active=1").fetchall()
        manual_hedges = conn.execute("SELECT * FROM hedge_positions WHERE is_active=1").fetchall()
        conn.close()
        if manual_lps:
            lines.append("\nManual LP Positions:")
            for m in manual_lps:
                m = dict(m)
                status = "IN RANGE" if m.get('in_range') else "OUT OF RANGE"
                lines.append(f"  [{m.get('chain','')}] {m.get('token0','')}/{m.get('token1','')}: ${m.get('value_usd',0):,.0f}, range {m.get('range_lower',0):,.0f}-{m.get('range_upper',0):,.0f}, {status}")
        if manual_hedges:
            lines.append("\nManual Hedges:")
            for m in manual_hedges:
                m = dict(m)
                lines.append(f"  [{m.get('exchange','')}] {m.get('market','')} {m.get('direction','')}: size ${m.get('size_usd',0):,.0f}, entry {m.get('entry_price',0):,.0f}, PnL ${m.get('pnl_usd',0):+,.2f}")
    except Exception:
        pass
    
    return "\n".join(lines)


def _build_profile_context() -> str:
    """Load investor profile."""
    profile_path = os.path.join("data", "investor_profile.json")
    if not os.path.exists(profile_path):
        return ""
    try:
        with open(profile_path, 'r') as f:
            profile = json.load(f)
        lines = []
        for key, val in profile.items():
            if val and val != '' and val != []:
                label = key.replace('_', ' ').title()
                if isinstance(val, list):
                    lines.append(f"{label}: {', '.join(str(v) for v in val)}")
                else:
                    lines.append(f"{label}: {val}")
        return "\n".join(lines)
    except Exception:
        return ""


def _get_previous_recommendations() -> str:
    """Get recommendations from the most recent AI report."""
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
            if recs:
                lines = []
                for i, rec in enumerate(recs, 1):
                    lines.append(f"{i}. \"{rec.get('action', '')}\" (priority: {rec.get('priority', 'medium')})")
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
        "value_change_24h_pct": 0,
        "value_change_24h_usd": 0,
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
    
    # Latest portfolio total (sum across wallets at most recent timestamp)
    latest = conn.execute("""
        SELECT strftime('%Y-%m-%dT%H:%M:00', timestamp) as ts, SUM(total_value_usd) as total
        FROM portfolio_snapshots WHERE status='completed' AND user_id=?
        GROUP BY ts ORDER BY ts DESC LIMIT 1
    """, (user_id,)).fetchone()
    
    if latest:
        digest["total_value_usd"] = latest["total"] or 0
        latest_ts_str = latest["ts"]
        
        # Find the matching scheduled snapshot from ~24h ago
        # Extract the hour:minute from the latest snapshot, then find the closest
        # snapshot from yesterday at the same time slot
        prev = conn.execute("""
            SELECT strftime('%Y-%m-%dT%H:%M:00', timestamp) as ts, SUM(total_value_usd) as total
            FROM portfolio_snapshots WHERE status='completed' AND user_id=?
            AND timestamp BETWEEN datetime('now', '-26 hours') AND datetime('now', '-22 hours')
            GROUP BY ts ORDER BY ABS(
                strftime('%H', timestamp) * 60 + strftime('%M', timestamp)
                - ? * 60 - ?
            ) ASC LIMIT 1
        """, (user_id,
              int(latest_ts_str[11:13]),  # hour from latest
              int(latest_ts_str[14:16]),  # minute from latest
        )).fetchone()
        
        if prev and prev["total"] and prev["total"] > 0:
            change = digest["total_value_usd"] - prev["total"]
            digest["value_change_24h_usd"] = change
            digest["value_change_24h_pct"] = (change / prev["total"]) * 100
    
    # Position counts from latest snapshots
    latest_snap_ts = conn.execute(
        "SELECT MAX(strftime('%Y-%m-%dT%H:%M:00', timestamp)) as ts FROM portfolio_snapshots WHERE status='completed' AND user_id=?", (user_id,)
    ).fetchone()
    snap_ts = latest_snap_ts['ts'] if latest_snap_ts else None
    if snap_ts:
        tc = conn.execute("SELECT COUNT(DISTINCT symbol) as c FROM token_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?", (snap_ts,)).fetchone()
        digest["token_count"] = tc['c'] if tc else 0
        lc = conn.execute("SELECT COUNT(DISTINCT position_id) as c FROM lp_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?", (snap_ts,)).fetchone()
        digest["lp_count"] = lc['c'] if lc else 0
        lac = conn.execute("SELECT COUNT(*) as c FROM lending_account_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?", (snap_ts,)).fetchone()
        digest["lending_count"] = lac['c'] if lac else 0
        hc = conn.execute("SELECT COUNT(*) as c FROM hedge_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?", (snap_ts,)).fetchone()
        digest["hedge_count"] = hc['c'] if hc else 0

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
    # Hedge health — use the latest hedge snapshot with valid price data
    latest_hedge_ts = conn.execute(
        "SELECT MAX(strftime('%Y-%m-%dT%H:%M:00', timestamp)) as ts FROM hedge_snapshots WHERE current_price > 0"
    ).fetchone()
    hedge_ts = (latest_hedge_ts['ts'] if latest_hedge_ts else None) or (latest_ts['ts'] if latest_ts else None)
    if hedge_ts:
        hedges = conn.execute(
            "SELECT market, direction, pnl_usd, pnl_pct, liquidation_price, current_price, leverage FROM hedge_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?",
            (hedge_ts,)
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
    
    # Total fees and average APR — 24h delta
    if latest_ts and latest_ts['ts']:
        # Current fees
        fee_now = conn.execute(
            "SELECT SUM(total_earned_fees_usd) as fees, AVG(daily_apr) as avg_apr FROM lp_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=? AND daily_apr IS NOT NULL",
            (latest_ts['ts'],)
        ).fetchone()
        current_fees = (fee_now["fees"] or 0) if fee_now else 0
        digest["total_fees_usd"] = current_fees
        digest["average_apr"] = ((fee_now["avg_apr"] or 0) * 365) if fee_now else 0

        # Fees 24h ago
        prev_fee_ts = conn.execute("""
            SELECT MAX(strftime('%Y-%m-%dT%H:%M:00', timestamp)) as ts FROM lp_snapshots
            WHERE timestamp BETWEEN datetime('now', '-26 hours') AND datetime('now', '-22 hours')
        """).fetchone()
        if prev_fee_ts and prev_fee_ts['ts']:
            fee_prev = conn.execute(
                "SELECT SUM(total_earned_fees_usd) as fees FROM lp_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?",
                (prev_fee_ts['ts'],)
            ).fetchone()
            prev_fees = (fee_prev["fees"] or 0) if fee_prev else 0
            digest["fees_24h_usd"] = max(current_fees - prev_fees, 0)

        # LP one-liners: pair, range, current price, in/out
        lp_rows = conn.execute(
            "SELECT token0, token1, chain, protocol, range_lower, range_upper, current_price, in_range, value_usd, daily_apr FROM lp_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?",
            (latest_ts['ts'],)
        ).fetchall()
        for lp in lp_rows:
            lp = dict(lp)
            pair = f"{lp.get('token0','?')}/{lp.get('token1','?')}"
            rl = lp.get('range_lower') or 0
            ru = lp.get('range_upper') or 0
            cp = lp.get('current_price') or 0
            in_range = lp.get('in_range', True)
            # Position within range as percentage
            range_pct = ((cp - rl) / (ru - rl) * 100) if ru > rl else 50
            range_pct = max(0, min(100, range_pct))
            digest["lp_summary"].append({
                "pair": pair,
                "chain": lp.get('chain', ''),
                "in_range": in_range,
                "range_pct": round(range_pct),
                "value_usd": lp.get('value_usd', 0),
                "daily_apr": lp.get('daily_apr'),
            })

    # Lending health from latest lending account snapshots
    if snap_ts:
        lending_rows = conn.execute(
            "SELECT chain, protocol, total_collateral_usd, total_debt_usd, health_factor, ltv FROM lending_account_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?",
            (snap_ts,)
        ).fetchall()
        for la in lending_rows:
            la = dict(la)
            if (la.get('total_collateral_usd') or 0) > 0:
                digest["lending_health"].append({
                    "chain": la.get('chain', ''),
                    "protocol": la.get('protocol', ''),
                    "collateral_usd": la.get('total_collateral_usd', 0),
                    "debt_usd": la.get('total_debt_usd', 0),
                    "health_factor": la.get('health_factor', 0),
                    "ltv": la.get('ltv', 0),
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
