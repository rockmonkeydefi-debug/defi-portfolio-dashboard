"""Snapshot service — captures portfolio and market data to DB on schedule."""

import os
import json
import time
import threading
import requests
from datetime import datetime, timezone

from src.storage.portfolio_db import (
    get_connection,
    create_portfolio_snapshot, complete_portfolio_snapshot, fail_portfolio_snapshot,
    insert_token_snapshot, insert_lp_snapshot, insert_hedge_snapshot,
    insert_lending_snapshot, insert_lending_account_snapshot,
    insert_market_snapshot, insert_token_price_daily,
    insert_defi_rates,
    get_lp_fee_high_water_mark,
)

# Market snapshot schedule: every 3 hours UTC
MARKET_SNAPSHOT_HOURS = [0, 3, 6, 9, 12, 15, 18, 21]
# Portfolio snapshot interval in seconds (2 hours)
PORTFOLIO_INTERVAL = 7200


def take_portfolio_snapshot(get_portfolio_data_fn, wallets: list, user_id: int = 1):
    """Take a full portfolio snapshot for all wallets and write to DB.
    Validates data against previous snapshot to prevent writing incomplete data.
    """
    print(f"[Snapshot] Starting portfolio snapshot at {datetime.utcnow().isoformat()}")

    portfolio = get_portfolio_data_fn(force_refresh=True)
    ts = datetime.utcnow().isoformat()

    # Validation: check if any critical APIs failed during data fetch
    api_failures = portfolio.get('api_failures', [])
    is_partial = len(api_failures) > 0
    
    if is_partial:
        print(f"[Snapshot] API failures detected: {api_failures}")
        # If ALL chains failed for tokens, skip entirely
        token_failures = [f for f in api_failures if f.startswith('tokens:') or f.startswith('zerion:')]
        lp_failures = [f for f in api_failures if f.startswith('lp:')]
        if len(token_failures) >= 3:  # All 3 chains failed
            print(f"[Snapshot] SKIPPING: all token APIs failed")
            return

    for wallet in wallets:
        start = time.time()
        snapshot_id = create_portfolio_snapshot(wallet, user_id, timestamp=ts)

        try:
            tokens_total = 0.0
            for t in portfolio.get('tokens', []):
                if t.get('wallet') != wallet:
                    continue
                insert_token_snapshot(snapshot_id, {
                    'timestamp': ts, 'wallet': wallet, 'chain': t['chain'],
                    'symbol': t['symbol'], 'token_address': t.get('token_address'),
                    'balance': t['balance'], 'price_usd': t['price_usd'], 'value_usd': t['value_usd'],
                }, user_id)
                tokens_total += t['value_usd']

            lp_total = 0.0
            for lp in portfolio.get('lp_positions', []):
                if lp.get('wallet') != wallet:
                    continue
                position_id = str(lp.get('token_id', ''))
                fees_uncollected = lp.get('total_fees_usd', 0)

                # Track collected fees by detecting drops in uncollected
                # When uncollected drops between snapshots, the difference was collected
                try:
                    _conn = get_connection()
                    prev_snap = _conn.execute(
                        "SELECT fees_uncollected_usd, fees_collected_usd, reward_pending, reward_claimed_total FROM lp_snapshots WHERE position_id=? AND user_id=? ORDER BY timestamp DESC LIMIT 1",
                        (position_id, user_id)
                    ).fetchone() if position_id else None
                    _conn.close()
                except Exception:
                    prev_snap = None

                if prev_snap:
                    prev_uncollected = prev_snap['fees_uncollected_usd'] or 0
                    prev_collected = prev_snap['fees_collected_usd'] or 0
                    if fees_uncollected < prev_uncollected:
                        newly_collected = prev_uncollected - fees_uncollected
                        fees_collected = prev_collected + newly_collected
                    else:
                        fees_collected = prev_collected
                else:
                    fees_collected = 0  # new position — start clean, drop-detection handles the rest

                total_earned = fees_collected + fees_uncollected

                # AERO staking-reward delta-detection: when pending drops, grow claimed total
                reward_pending = lp.get('reward_pending') or 0
                reward_pending_usd = lp.get('reward_pending_usd') or 0
                reward_price = lp.get('reward_price_usd') or 0
                if prev_snap is not None:
                    try:
                        prev_pending = prev_snap['reward_pending'] or 0
                        prev_claimed = prev_snap['reward_claimed_total'] or 0
                    except (IndexError, KeyError):
                        prev_pending = 0
                        prev_claimed = 0
                    if reward_pending < prev_pending:
                        newly_claimed = prev_pending - reward_pending
                        reward_claimed_total = prev_claimed + newly_claimed
                    else:
                        reward_claimed_total = prev_claimed
                else:
                    # New position: seed from current connector value (may be 0)
                    reward_claimed_total = lp.get('reward_claimed') or 0
                reward_claimed_total_usd = reward_claimed_total * reward_price

                insert_lp_snapshot(snapshot_id, {
                    'timestamp': ts, 'wallet': wallet,
                    'chain': lp.get('chain', ''), 'protocol': lp.get('protocol', 'uniswap_v3'),
                    'position_id': position_id,
                    'token0': lp.get('token0_symbol', ''), 'token1': lp.get('token1_symbol', ''),
                    'fee_tier': lp.get('fee_tier'),
                    'amount0': lp.get('amount0'), 'amount1': lp.get('amount1'),
                    'price0_usd': lp.get('price0_usd'), 'price1_usd': lp.get('price1_usd'),
                    'value_usd': lp.get('total_value_usd', 0),
                    'entry_value_usd': lp.get('entry_value_usd'),
                    'range_lower': lp.get('price_lower'), 'range_upper': lp.get('price_upper'),
                    'current_price': lp.get('current_price'), 'in_range': lp.get('in_range'),
                    'fees_uncollected_usd': fees_uncollected, 'fees_collected_usd': fees_collected,
                    'total_earned_fees_usd': total_earned,
                    'daily_apr': lp.get('daily_apr'), 'monthly_apr': lp.get('monthly_apr'),
                    'reward_symbol': lp.get('reward_symbol'),
                    'reward_pending': reward_pending,
                    'reward_pending_usd': reward_pending_usd,
                    'reward_claimed_total': reward_claimed_total,
                    'reward_claimed_total_usd': reward_claimed_total_usd,
                }, user_id)
                lp_total += lp.get('total_value_usd', 0)

            fees_total = sum(
                lp.get('total_fees_usd', 0)
                for lp in portfolio.get('lp_positions', [])
                if lp.get('wallet') == wallet
            )

            hedge_total = 0.0
            for h in portfolio.get('gmx_positions', []):
                if h.get('wallet') != wallet:
                    continue
                sl_price = h['stop_loss'][0]['trigger_price'] if h.get('stop_loss') else None
                tp_price = h['take_profit'][0]['trigger_price'] if h.get('take_profit') else None
                insert_hedge_snapshot(snapshot_id, {
                    'timestamp': ts, 'wallet': wallet, 'exchange': 'gmx_v2',
                    'market': h.get('market', ''),
                    'direction': 'long' if h.get('is_long') else 'short',
                    'size_usd': h.get('size_usd', 0), 'collateral_usd': h.get('collateral_amount', 0),
                    'entry_price': h.get('entry_price'), 'current_price': h.get('current_price'),
                    'liquidation_price': h.get('liquidation_price'),
                    'pnl_usd': h.get('pnl_usd'), 'pnl_pct': h.get('pnl_pct'),
                    'leverage': h.get('leverage'),
                    'stop_loss_price': sl_price, 'take_profit_price': tp_price,
                }, user_id)
                hedge_total += h.get('collateral_amount', 0)

            lending_net = 0.0
            active_lending_chains = set()
            for aave in portfolio.get('aave_positions', []):
                if aave.get('wallet') != wallet:
                    continue
                active_lending_chains.add(aave.get('chain', ''))
                for s in aave.get('supplied', []):
                    insert_lending_snapshot(snapshot_id, {
                        'timestamp': ts, 'wallet': wallet, 'chain': aave.get('chain', ''),
                        'protocol': 'aave_v3', 'side': 'supply', 'symbol': s['symbol'],
                        'token_address': s.get('token_address'), 'balance': s['balance'],
                        'price_usd': s.get('price_usd'), 'value_usd': s.get('value_usd'),
                        'apy': s.get('supply_apy'), 'collateral_enabled': s.get('collateral_enabled'),
                        'is_variable': None,
                    }, user_id)
                for b in aave.get('borrowed', []):
                    insert_lending_snapshot(snapshot_id, {
                        'timestamp': ts, 'wallet': wallet, 'chain': aave.get('chain', ''),
                        'protocol': 'aave_v3', 'side': 'borrow', 'symbol': b['symbol'],
                        'token_address': b.get('token_address'), 'balance': b['balance'],
                        'price_usd': b.get('price_usd'), 'value_usd': b.get('value_usd'),
                        'apy': b.get('borrow_apy'), 'collateral_enabled': None,
                        'is_variable': b.get('is_variable'),
                    }, user_id)
                insert_lending_account_snapshot(snapshot_id, {
                    'timestamp': ts, 'wallet': wallet, 'chain': aave.get('chain', ''),
                    'protocol': 'aave_v3',
                    'total_collateral_usd': aave.get('total_collateral_usd'),
                    'total_debt_usd': aave.get('total_debt_usd'),
                    'health_factor': aave.get('health_factor'),
                    'ltv': aave.get('ltv'),
                    'liquidation_threshold': aave.get('liquidation_threshold'),
                }, user_id)
                lending_net += aave.get('total_collateral_usd', 0)

            # Write zero-balance closure rows for previously-active lending
            # positions that are no longer reported (position was closed).
            # Only write once — skip if the latest row already has $0 collateral.
            try:
                _conn = get_connection()
                prev_chains = _conn.execute(
                    "SELECT chain, total_collateral_usd FROM lending_account_snapshots "
                    "WHERE wallet=? AND user_id=? AND chain NOT IN (?) "
                    "GROUP BY chain HAVING MAX(timestamp) ORDER BY timestamp DESC",
                    (wallet, user_id, ','.join(active_lending_chains) if active_lending_chains else '')
                ).fetchall()
                # Simpler: for each previously-seen chain, check the latest row
                seen_chains = _conn.execute(
                    "SELECT DISTINCT chain FROM lending_account_snapshots WHERE wallet=? AND user_id=?",
                    (wallet, user_id)
                ).fetchall()
                _conn.close()
                for row in seen_chains:
                    ch = row['chain']
                    if ch in active_lending_chains:
                        continue  # still active
                    # Check if we already wrote a closure row
                    _conn2 = get_connection()
                    latest = _conn2.execute(
                        "SELECT total_collateral_usd FROM lending_account_snapshots "
                        "WHERE wallet=? AND user_id=? AND chain=? ORDER BY timestamp DESC LIMIT 1",
                        (wallet, user_id, ch)
                    ).fetchone()
                    _conn2.close()
                    if latest and (latest['total_collateral_usd'] or 0) < 1:
                        continue  # already closed
                    insert_lending_account_snapshot(snapshot_id, {
                        'timestamp': ts, 'wallet': wallet, 'chain': ch,
                        'protocol': 'aave_v3',
                        'total_collateral_usd': 0, 'total_debt_usd': 0,
                        'health_factor': 0, 'ltv': 0, 'liquidation_threshold': 0,
                    }, user_id)
                    print(f"[Snapshot] Wrote closure row for lending on {ch} wallet {wallet[:10]}...")
            except Exception as e:
                print(f"[Snapshot] Lending closure check failed: {e}")

            duration = time.time() - start
            status = 'partial' if is_partial else 'completed'
            complete_portfolio_snapshot(snapshot_id, {
                'total_value_usd': tokens_total + lp_total + fees_total + hedge_total,
                'total_tokens_usd': tokens_total,
                'total_lp_usd': lp_total,
                'total_lending_usd': lending_net,
                'total_hedge_collateral_usd': hedge_total,
            }, duration)

            # Override status if partial
            if is_partial:
                conn2 = get_connection()
                conn2.execute("UPDATE portfolio_snapshots SET status='partial' WHERE id=?", (snapshot_id,))
                conn2.commit()
                conn2.close()

            print(f"[Snapshot] Wallet {wallet[:10]}... done in {duration:.1f}s [{status}]")

        except Exception as e:
            duration = time.time() - start
            fail_portfolio_snapshot(snapshot_id, duration)
            print(f"[Snapshot] Wallet {wallet[:10]}... FAILED: {e}")


def take_market_snapshot(session: str):
    """Capture market data and write to DB."""
    print(f"[Market] Starting {session} market snapshot at {datetime.utcnow().isoformat()}")
    ts = datetime.utcnow().isoformat()
    data = {'timestamp': ts, 'session': session}
    
    # BTC 200-day moving average — runs FIRST (once per day only)
    # Placed before other CoinGecko calls to avoid rate limit exhaustion
    try:
        from src.storage.portfolio_db import get_connection as _gc
        _c = _gc()
        has_today = _c.execute(
            "SELECT btc_200d_ma FROM market_snapshots WHERE btc_200d_ma IS NOT NULL AND date(timestamp) = date('now') LIMIT 1"
        ).fetchone()
        _c.close()
        if has_today:
            data['btc_200d_ma'] = has_today['btc_200d_ma']
            print(f"[Market] BTC 200D MA: ${data['btc_200d_ma']:,.0f} (cached from today)")
        else:
            r = requests.get(
                'https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=200&interval=daily',
                timeout=20
            )
            if r.ok:
                prices_200d = [p[1] for p in r.json().get('prices', [])]
                if len(prices_200d) >= 100:
                    data['btc_200d_ma'] = sum(prices_200d) / len(prices_200d)
                    print(f"[Market] BTC 200D MA: ${data['btc_200d_ma']:,.0f} ({len(prices_200d)} days, fresh)")
            else:
                print(f"[Market] BTC 200D MA: CoinGecko returned {r.status_code}")
            time.sleep(3)  # Cooldown before next CoinGecko call
    except Exception as e:
        print(f"[Market] BTC 200D MA error: {e}")

    # Prices from CoinGecko
    try:
        r = requests.get(
            'https://api.coingecko.com/api/v3/simple/price'
            '?ids=bitcoin,ethereum,solana,bittensor,sui'
            '&vs_currencies=usd&include_24hr_change=true'
            '&include_24hr_high=true&include_24hr_low=true&include_24hr_vol=true',
            timeout=10
        )
        if r.ok:
            p = r.json()
            data['btc_price'] = p.get('bitcoin', {}).get('usd')
            data['eth_price'] = p.get('ethereum', {}).get('usd')
            data['sol_price'] = p.get('solana', {}).get('usd')
            data['tao_price'] = p.get('bittensor', {}).get('usd')
            data['sui_price'] = p.get('sui', {}).get('usd')
            if data['btc_price'] and data['eth_price']:
                data['eth_btc_ratio'] = data['eth_price'] / data['btc_price']
    except Exception as e:
        print(f"[Market] CoinGecko prices error: {e}")
    
    # Global market data
    try:
        time.sleep(2)  # Rate limit — CoinGecko free tier
        r = requests.get('https://api.coingecko.com/api/v3/global', timeout=10)
        if r.ok:
            g = r.json().get('data', {})
            data['btc_dominance'] = g.get('market_cap_percentage', {}).get('btc')
            data['eth_dominance'] = g.get('market_cap_percentage', {}).get('eth')
            data['total_market_cap'] = g.get('total_market_cap', {}).get('usd')
            data['total_volume_24h'] = g.get('total_volume', {}).get('usd')
    except Exception as e:
        print(f"[Market] CoinGecko global error: {e}")
    
    # Funding rates & OI from Bybit
    try:
        for sym, prefix in [('BTCUSDT', 'btc'), ('ETHUSDT', 'eth'), ('SOLUSDT', 'sol')]:
            r = requests.get(f'https://api.bybit.com/v5/market/tickers?category=linear&symbol={sym}', timeout=10)
            if r.ok:
                item = r.json().get('result', {}).get('list', [{}])[0]
                data[f'{prefix}_funding_rate'] = float(item.get('fundingRate', 0))
                data[f'{prefix}_open_interest'] = float(item.get('openInterestValue', 0))
    except Exception as e:
        print(f"[Market] Bybit error: {e}")
    
    # Stablecoin supply from DeFiLlama
    try:
        r = requests.get('https://stablecoins.llama.fi/stablecoinchains', timeout=10)
        if r.ok:
            total = 0
            for chain in r.json():
                circ = chain.get('totalCirculatingUSD')
                if isinstance(circ, dict):
                    total += sum(circ.values())
                elif circ:
                    total += float(circ)
            data['stablecoin_supply'] = total
    except Exception as e:
        print(f"[Market] DeFiLlama stablecoins error: {e}")
    
    # Fear & Greed Index
    try:
        r = requests.get('https://api.alternative.me/fng/?limit=1', timeout=10)
        if r.ok:
            data['fear_greed_index'] = int(r.json()['data'][0]['value'])
    except Exception as e:
        print(f"[Market] Fear & Greed error: {e}")
    
    # Deribit BTC index
    try:
        r = requests.get('https://www.deribit.com/api/v2/public/get_index_price?index_name=btc_usd', timeout=10)
        if r.ok:
            data['btc_index_price'] = r.json().get('result', {}).get('index_price')
    except Exception as e:
        print(f"[Market] Deribit error: {e}")
    
    # BTC/ETH volatility and returns from CoinGecko price history
    import math as _math
    for coin, cg_id, prefix in [('BTC', 'bitcoin', 'btc'), ('ETH', 'ethereum', 'eth')]:
        try:
            time.sleep(3)  # Rate limit — CoinGecko free tier
            r = requests.get(f'https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart?vs_currency=usd&days=30&interval=daily', timeout=10)
            if r.ok:
                prices = [p[1] for p in r.json().get('prices', [])]
                if len(prices) >= 7:
                    # Returns
                    data[f'{prefix}_return_7d'] = ((prices[-1] / prices[-min(7, len(prices))]) - 1) * 100
                    data[f'{prefix}_return_30d'] = ((prices[-1] / prices[0]) - 1) * 100
                    # Realized volatility (annualized)
                    rets = [_math.log(prices[i] / prices[i-1]) for i in range(1, len(prices))]
                    if rets:
                        mean_r = sum(rets) / len(rets)
                        var = sum((r - mean_r)**2 for r in rets) / (len(rets) - 1)
                        data[f'{prefix}_vol_30d'] = (_math.sqrt(var) * _math.sqrt(365)) * 100
                    # 14d range (high-low as % of current)
                    recent = prices[-min(14, len(prices)):]
                    if recent:
                        data[f'{prefix}_range_14d'] = ((max(recent) - min(recent)) / prices[-1]) * 100
        except Exception as e:
            print(f"[Market] {coin} price history error: {e}")

    # DeFi TVL from DeFiLlama
    try:
        r = requests.get('https://api.llama.fi/v2/historicalChainTvl', timeout=10)
        if r.ok:
            tvl_data = r.json()
            if tvl_data:
                data['total_defi_tvl'] = tvl_data[-1].get('tvl')
    except Exception as e:
        print(f"[Market] DeFiLlama TVL error: {e}")
    
    # ETH gas price
    try:
        eth_rpc = os.getenv('ETHEREUM_RPC_URL')
        if eth_rpc:
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider(eth_rpc))
            gas = w3.eth.gas_price
            data['eth_gas_price'] = float(w3.from_wei(gas, 'gwei'))
    except Exception as e:
        print(f"[Market] Gas price error: {e}")
    
    # LP fee APRs and lending rates from DeFiLlama Yields
    try:
        r = requests.get('https://yields.llama.fi/pools', timeout=15)
        if r.ok:
            pools = r.json().get('data', [])
            # Collect lending rates across chains
            lending_rates = {}  # (chain, project, symbol) -> {supply, borrow}
            lp_pools = {}  # (chain, project, symbol) -> {apyBase, apyReward, tvl}
            
            for pool in pools:
                project = pool.get('project', '')
                chain = pool.get('chain', '').lower()
                symbol = pool.get('symbol', '')
                apy_base = pool.get('apyBase')
                apy_reward = pool.get('apyReward') or 0
                tvl = pool.get('tvlUsd') or 0
                
                # LP pool data (Uniswap V3 on our chains)
                if project == 'uniswap-v3' and chain in ('arbitrum', 'base', 'ethereum'):
                    if ('USDC' in symbol or 'USDT' in symbol) and ('ETH' in symbol or 'WETH' in symbol or 'WBTC' in symbol):
                        if tvl > 1_000_000:  # Only pools with >$1M TVL
                            lp_pools[f"{chain}_{symbol}"] = {
                                'apyBase': apy_base or 0,
                                'apyReward': apy_reward,
                                'tvl': tvl,
                                'vol1d': pool.get('volumeUsd1d') or 0,
                            }
                
                # Backward compat: specific fields
                if project == 'uniswap-v3' and 'USDC' in symbol and ('ETH' in symbol or 'WETH' in symbol):
                    if chain in ('arbitrum', 'ethereum') and apy_base is not None:
                        if data.get('eth_usdc_fee_apr') is None or chain == 'arbitrum':
                            data['eth_usdc_fee_apr'] = apy_base
                if project == 'uniswap-v3' and 'USDC' in symbol and 'WBTC' in symbol:
                    if chain in ('arbitrum', 'ethereum') and apy_base is not None:
                        if data.get('wbtc_usdc_fee_apr') is None or chain == 'arbitrum':
                            data['wbtc_usdc_fee_apr'] = apy_base
                if project == 'lido' and symbol == 'STETH' and chain == 'ethereum':
                    data['eth_staking_apr'] = pool.get('apy')
            
            # Lending rates from on-chain (accurate borrow rates)
            from src.connectors.aave_v3 import get_aave_market_rates
            for chain_name in ['arbitrum', 'base', 'ethereum']:
                rpc_env = {"ethereum": "ETHEREUM_RPC_URL", "arbitrum": "ARBITRUM_RPC_URL", "base": "BASE_RPC_URL"}
                rpc_url = os.getenv(rpc_env.get(chain_name, ""))
                if rpc_url:
                    try:
                        from web3 import Web3 as W3
                        w3 = W3(W3.HTTPProvider(rpc_url))
                        rates = get_aave_market_rates(w3, chain_name)
                        for r in rates:
                            lending_rates[f"{chain_name}_{r['asset'].lower()}"] = {
                                'supply': r['supply_apy'], 'borrow': r['borrow_apy']
                            }
                    except Exception as e:
                        print(f"[Market] Aave on-chain rates error ({chain_name}): {e}")
            
            # Write lending rates and LP pool data to defi_rates table
            defi_rows = []
            for key, r in lending_rates.items():
                chain, sym = key.split('_', 1)
                defi_rows.append({
                    'chain': chain, 'protocol': 'aave-v3', 'asset': sym.upper(),
                    'rate_type': 'lending', 'supply_apy': r['supply'], 'borrow_apy': r['borrow'],
                })
            for key, p in lp_pools.items():
                chain, sym = key.split('_', 1)
                defi_rows.append({
                    'chain': chain, 'protocol': 'uniswap-v3', 'asset': sym,
                    'rate_type': 'lp', 'fee_apr': p['apyBase'], 'reward_apr': p['apyReward'], 'tvl': p['tvl'], 'volume_1d': p.get('vol1d', 0),
                })
            if defi_rows:
                insert_defi_rates(ts, defi_rows)
    except Exception as e:
        print(f"[Market] DeFiLlama yields error: {e}")
    
    # Write to DB
    insert_market_snapshot(data)
    print(f"[Market] {session} snapshot saved with {sum(1 for v in data.values() if v is not None)} data points")
    
    # Also write daily token prices (if this is the first snapshot of the day)
    _save_daily_token_prices(data)


def _save_daily_token_prices(market_data: dict):
    """Save daily token prices from market snapshot data."""
    today = datetime.utcnow().strftime('%Y-%m-%dT00:00:00')
    
    token_map = {
        'BTC': 'btc_price',
        'ETH': 'eth_price',
        'SOL': 'sol_price',
        'TAO': 'tao_price',
        'SUI': 'sui_price',
    }
    
    for symbol, key in token_map.items():
        price = market_data.get(key)
        if price:
            try:
                # Get 24h high/low from CoinGecko (already fetched with include_24hr_high)
                insert_token_price_daily({
                    'timestamp': today,
                    'symbol': symbol,
                    'price_usd': price,
                    'high_24h': None,  # Could be enriched later
                    'low_24h': None,
                    'volume_24h': None,
                })
            except Exception:
                pass  # UNIQUE constraint will skip duplicates


def start_scheduler(get_portfolio_data_fn, get_wallets_fn):
    """Start background threads for portfolio (2h), market (3x daily), and AI report (daily)."""

    def portfolio_loop():
        while True:
            time.sleep(PORTFOLIO_INTERVAL)
            try:
                wallets = get_wallets_fn()
                if wallets:
                    take_portfolio_snapshot(get_portfolio_data_fn, wallets)
            except Exception as e:
                print(f"[Scheduler] Portfolio snapshot error: {e}")

    def market_loop():
        while True:
            now = datetime.now(timezone.utc)
            current_hour = now.hour
            next_hours = [h for h in MARKET_SNAPSHOT_HOURS if h > current_hour]
            if next_hours:
                next_hour = next_hours[0]
                wait_seconds = (next_hour - current_hour) * 3600 - now.minute * 60 - now.second
            else:
                next_hour = MARKET_SNAPSHOT_HOURS[0]
                wait_seconds = (24 - current_hour + next_hour) * 3600 - now.minute * 60 - now.second

            session_map = {0: 'asia', 3: 'asia', 6: 'europe', 9: 'europe', 12: 'us', 15: 'us', 18: 'evening', 21: 'evening'}
            session = session_map.get(next_hour, 'scheduled')

            print(f"[Scheduler] Next market snapshot ({session}) in {wait_seconds//3600}h {(wait_seconds%3600)//60}m")
            time.sleep(max(wait_seconds, 60))

            try:
                take_market_snapshot(session)
            except Exception as e:
                print(f"[Scheduler] Market snapshot error: {e}")

    def ai_report_loop():
        """Run AI report daily at the configured UTC hour."""
        while True:
            try:
                from src.engines.ai_advisor import load_ai_config, generate_report, generate_daily_digest
                config = load_ai_config()

                if not config.get('auto_enabled', False):
                    time.sleep(300)  # Check every 5 min if enabled
                    continue

                schedule_hour = config.get('schedule_utc_hour', 8)
                now = datetime.now(timezone.utc)

                # Calculate wait until next scheduled hour
                if now.hour < schedule_hour:
                    wait = (schedule_hour - now.hour) * 3600 - now.minute * 60 - now.second
                else:
                    wait = (24 - now.hour + schedule_hour) * 3600 - now.minute * 60 - now.second

                print(f"[Scheduler] Next AI report in {wait//3600}h {(wait%3600)//60}m (UTC {schedule_hour}:00)")
                time.sleep(max(wait, 60))

                # Re-check if still enabled
                config = load_ai_config()
                if not config.get('auto_enabled', False):
                    continue

                # Generate daily digest first (no LLM)
                try:
                    generate_daily_digest()
                    print(f"[Scheduler] Daily digest generated")
                except Exception as e:
                    print(f"[Scheduler] Daily digest error: {e}")

                # Generate AI report
                try:
                    generate_report(get_portfolio_data_fn, get_wallets_fn)
                    print(f"[Scheduler] AI report generated at {datetime.now(timezone.utc).isoformat()}")
                except Exception as e:
                    print(f"[Scheduler] AI report error: {e}")

            except Exception as e:
                print(f"[Scheduler] AI scheduler error: {e}")
                time.sleep(300)

    def telegram_loop():
        """Send Telegram notification daily at the configured UTC hour."""
        while True:
            try:
                from src.engines.telegram_service import load_telegram_config, send_daily_notification
                config = load_telegram_config()

                if not config.get('enabled', False):
                    time.sleep(300)  # Check every 5 min if enabled
                    continue

                schedule_hour = config.get('schedule_utc_hour', 9)
                now = datetime.now(timezone.utc)

                # Calculate wait until next scheduled hour
                if now.hour < schedule_hour:
                    wait = (schedule_hour - now.hour) * 3600 - now.minute * 60 - now.second
                else:
                    wait = (24 - now.hour + schedule_hour) * 3600 - now.minute * 60 - now.second

                print(f"[Scheduler] Next Telegram notification in {wait//3600}h {(wait%3600)//60}m (UTC {schedule_hour}:00)")
                time.sleep(max(wait, 60))

                # Re-check if still enabled
                config = load_telegram_config()
                if not config.get('enabled', False):
                    continue

                send_daily_notification()
                print(f"[Scheduler] Telegram notification sent at {datetime.now(timezone.utc).isoformat()}")

            except Exception as e:
                print(f"[Scheduler] Telegram notification error: {e}")

    SEND_TIMES_UTC = [
        (12,  0,  'Morning'),
        (19,  0,  'Lunch'),
        (22, 30,  'Afternoon'),
    ]

    SCAN_TIMES_UTC = [(11, 0), (18, 0), (21, 30)]  # 1hr before each digest window
    # Fires one fast test scan ~60s after boot to verify wiring end-to-end.
    # Wiring confirmed — leave the boot-test block in place but gated off; flip
    # back to True + redeploy to re-verify if needed.
    SCAN_TEST_FIRE_ON_BOOT = False

    def triage_digest_loop():
        """Fire the triage Telegram digest at fixed UTC windows. Helpers live in
        web_portfolio (imported lazily to avoid a circular import at module load)."""
        import time as _time
        fired_today = set()  # tracks (day_key, hour, minute) fired this UTC day
        while True:
            try:
                import web_portfolio as _wp
                now_utc = _time.gmtime()
                day_key = (now_utc.tm_year, now_utc.tm_mon, now_utc.tm_mday)
                for (h, m, label) in SEND_TIMES_UTC:
                    window_key = (day_key, h, m)
                    if window_key in fired_today:
                        continue
                    # fire within a 4-minute window after the target time
                    if now_utc.tm_hour == h and m <= now_utc.tm_min < m + 4:
                        cfg = _wp._telegram_settings()
                        if not cfg.get('enabled'):
                            fired_today.add(window_key)
                            continue
                        try:
                            results = _wp._build_triage_results(tiers=None)
                        except Exception as _be:
                            print(f"[Telegram] {label} digest build error: {_be}", flush=True)
                            fired_today.add(window_key)
                            continue
                        text = _wp._format_triage_digest(results, label)
                        ok, err = _wp._send_telegram(text)
                        if ok:
                            print(f"[Telegram] {label} digest sent", flush=True)
                        else:
                            print(f"[Telegram] {label} digest FAILED: {err}", flush=True)
                        fired_today.add(window_key)
                # prune fired_today to only today's entries
                today = _time.gmtime()
                today_key = (today.tm_year, today.tm_mon, today.tm_mday)
                fired_today = {k for k in fired_today if k[0] == today_key}
            except Exception as e:
                print(f"[Telegram] digest loop error: {e}", flush=True)
            _time.sleep(60)

    def reminders_loop():
        """Fire custom Telegram reminders at their configured UTC times. Mirrors
        triage_digest_loop: poll every 60s, 4-minute fire window, fired_today
        dedupe keyed per (day, reminder id, hour, minute)."""
        import time as _time
        fired_today = set()
        while True:
            try:
                import web_portfolio as _wp
                settings = _wp._telegram_settings()
                if not settings.get('enabled'):
                    fired_today = set()
                    _time.sleep(60)
                    continue
                reminders = settings.get('reminders') or []
                now_utc = _time.gmtime()
                today_key = (now_utc.tm_year, now_utc.tm_mon, now_utc.tm_mday)
                fired_today = {k for k in fired_today if k[0] == today_key}
                for reminder in reminders:
                    if not reminder.get('enabled'):
                        continue
                    message = reminder.get('message', '').strip()
                    if not message:
                        continue
                    for time_str in (reminder.get('times_utc') or []):
                        try:
                            h, m = int(time_str.split(':')[0]), int(time_str.split(':')[1])
                        except Exception:
                            continue
                        window_key = (today_key, reminder.get('id'), h, m)
                        if window_key in fired_today:
                            continue
                        if now_utc.tm_hour == h and m <= now_utc.tm_min < m + 4:
                            ok, err = _wp._send_telegram(message)
                            if ok:
                                print(f"[REMINDERS] Sent reminder '{reminder.get('id')}' at {h:02d}:{m:02d} UTC", flush=True)
                            else:
                                print(f"[REMINDERS] Failed to send reminder '{reminder.get('id')}': {err}", flush=True)
                            fired_today.add(window_key)
            except Exception as e:
                print(f"[REMINDERS] Loop error: {e}", flush=True)
            _time.sleep(60)

    def scheduled_scan_loop():
        """Fire the volume-filtered wide-scan at fixed UTC windows (1hr before
        each digest). Helpers live in web_portfolio (imported lazily to avoid a
        circular import at module load)."""
        import time as _time
        _time.sleep(60)   # let the app settle before first action
        fired_today = set()
        did_boot_test = False
        while True:
            try:
                import web_portfolio as _wp
                now_utc = _time.gmtime()
                day_key = (now_utc.tm_year, now_utc.tm_mon, now_utc.tm_mday)

                # ── TEMP boot test: one fast scan to prove wiring ──
                if SCAN_TEST_FIRE_ON_BOOT and not did_boot_test:
                    did_boot_test = True
                    print("[SCHEDULED SCAN] BOOT TEST firing "
                          "(high min_volume for speed)", flush=True)
                    # high floor → ~5 tickers → ~1 min, just proves wiring
                    result = _wp._run_scheduled_scan(min_volume_override=50_000_000)
                    if result is None:
                        print("[SCHEDULED SCAN] BOOT TEST skipped "
                              "(another scan running)", flush=True)
                    else:
                        _wp._check_scan_health_and_alert(result, label='BOOT TEST')
                        try:
                            _wp._send_telegram(
                                f"✅ Scheduled-scan wiring test OK: "
                                f"{result.get('attemptedPairs',0)} pairs scanned, "
                                f"{result.get('setupReadyCount',0)} setups ready, "
                                f"{result.get('errorCount',0)} errors.")
                        except Exception:
                            pass
                        print(f"[SCHEDULED SCAN] BOOT TEST done: "
                              f"{result.get('setupReadyCount',0)} ready", flush=True)

                # ── Real scheduled windows (read live from settings each poll,
                # so edits take effect without a redeploy) ──
                cfg = _wp._scanner_settings()
                raw_times = cfg.get('scan_times_utc', ['11:00', '18:00', '21:30'])
                active_windows = []
                for t in raw_times:
                    t = (t or '').strip()
                    if not t:
                        continue   # empty slot = disabled
                    try:
                        hh, mm = t.split(':')
                        active_windows.append((int(hh), int(mm)))
                    except (ValueError, AttributeError):
                        continue
                for (h, m) in active_windows:
                    window_key = (day_key, h, m)
                    if window_key in fired_today:
                        continue
                    # 10-min fire window so a brief manual-scan collision can
                    # clear and retry
                    if now_utc.tm_hour == h and m <= now_utc.tm_min < m + 10:
                        if not _wp._scanner_settings().get('auto_scan_enabled'):
                            fired_today.add(window_key)   # disabled → skip this window
                            continue
                        result = _wp._run_scheduled_scan()
                        if result is None:
                            # blocked by another scan — DON'T mark fired; retry on
                            # next poll within the window
                            print("[SCHEDULED SCAN] blocked, will "
                                  "retry within window", flush=True)
                        else:
                            _wp._check_scan_health_and_alert(
                                result, label=f"{h:02d}:{m:02d} UTC")
                            print(f"[SCHEDULED SCAN] {h:02d}:{m:02d} "
                                  f"done: {result.get('setupReadyCount',0)} "
                                  f"ready, {result.get('errorCount',0)} errors",
                                  flush=True)
                            if result:
                                _wp._send_telegram(
                                    f"✅ Scan complete ({h:02d}:{m:02d} UTC) — "
                                    f"{result.get('attemptedPairs', '?')} pairs scanned, "
                                    f"{result.get('setupReadyCount', 0)} setups ready, "
                                    f"{result.get('errorCount', 0)} errors."
                                )
                            fired_today.add(window_key)

                # prune fired_today to today only
                fired_today = {k for k in fired_today if k[0] == day_key}
            except Exception as e:
                print(f"[SCHEDULED SCAN] loop error: {e}", flush=True)
            _time.sleep(60)

    t1 = threading.Thread(target=portfolio_loop, daemon=True, name='portfolio-scheduler')
    t1.start()

    t2 = threading.Thread(target=market_loop, daemon=True, name='market-scheduler')
    t2.start()

    t3 = threading.Thread(target=ai_report_loop, daemon=True, name='ai-report-scheduler')
    t3.start()

    t4 = threading.Thread(target=telegram_loop, daemon=True, name='telegram-scheduler')
    t4.start()

    t_digest = threading.Thread(target=triage_digest_loop, daemon=True, name='triage-digest-scheduler')
    t_digest.start()

    t_scan = threading.Thread(target=scheduled_scan_loop, daemon=True, name='scheduled-scan-scheduler')
    t_scan.start()

    t_reminders = threading.Thread(target=reminders_loop, daemon=True, name='reminders')
    t_reminders.start()

    print(f"[Scheduler] Portfolio every {PORTFOLIO_INTERVAL//3600}h, market at UTC {MARKET_SNAPSHOT_HOURS}, AI report daily, Telegram daily, triage digest at UTC {[(h, m) for (h, m, _l) in SEND_TIMES_UTC]}, scheduled scan at UTC {SCAN_TIMES_UTC}")
