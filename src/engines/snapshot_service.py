"""Snapshot service - captures portfolio state and persists to DB."""

import os
import sys
import time
import logging
from datetime import datetime
from typing import Optional, Set, List

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.storage.portfolio_db import (
    init_db, create_snapshot_run, complete_snapshot_run, fail_snapshot_run,
    insert_token_snapshot, insert_lp_snapshot, insert_fee_event,
    get_connection
)

logger = logging.getLogger(__name__)


def detect_fee_collection(position_id: str, current_uncollected_0: float,
                          current_uncollected_1: float) -> Optional[dict]:
    """Compare current uncollected fees with previous snapshot to detect collections.
    
    If uncollected fees decreased, the user likely collected them.
    Returns the delta if a collection is detected.
    """
    conn = get_connection()
    prev = conn.execute("""
        SELECT ls.token0_fees_uncollected, ls.token1_fees_uncollected,
               ls.token0_price_usd, ls.token1_price_usd,
               ls.token0_symbol, ls.token1_symbol, ls.pool_pair,
               ls.chain, ls.protocol, ls.wallet_address
        FROM lp_snapshots ls
        JOIN snapshot_runs sr ON sr.id = ls.run_id
        WHERE ls.position_id = ? AND sr.status = 'completed'
        ORDER BY sr.timestamp DESC LIMIT 1
    """, (position_id,)).fetchone()
    conn.close()

    if not prev:
        return None

    prev_0 = prev['token0_fees_uncollected']
    prev_1 = prev['token1_fees_uncollected']

    # If uncollected fees dropped significantly, user collected
    if current_uncollected_0 < prev_0 * 0.5 or current_uncollected_1 < prev_1 * 0.5:
        collected_0 = max(0, prev_0 - current_uncollected_0)
        collected_1 = max(0, prev_1 - current_uncollected_1)
        value_usd = (collected_0 * prev['token0_price_usd'] +
                     collected_1 * prev['token1_price_usd'])
        return {
            'wallet': prev['wallet_address'],
            'chain': prev['chain'],
            'protocol': prev['protocol'],
            'position_id': position_id,
            'pool_pair': prev['pool_pair'],
            'token0_symbol': prev['token0_symbol'],
            'token1_symbol': prev['token1_symbol'],
            'token0_amount': collected_0,
            'token1_amount': collected_1,
            'value_usd': value_usd
        }
    return None


def detect_position_closure(run_id: int, wallet: str, current_position_ids: Set[str]):
    """Detect positions that existed in previous snapshot but not in current one."""
    conn = get_connection()
    
    # Get the previous run for this wallet
    prev_run = conn.execute("""
        SELECT id FROM snapshot_runs 
        WHERE wallet_address = ? AND status = 'completed' AND id < ?
        ORDER BY timestamp DESC LIMIT 1
    """, (wallet, run_id)).fetchone()
    
    if not prev_run:
        conn.close()
        return
    
    # Get positions from previous run
    prev_positions = conn.execute("""
        SELECT DISTINCT position_id, pool_pair, chain, protocol,
               token0_symbol, token1_symbol,
               token0_fees_uncollected, token1_fees_uncollected,
               token0_price_usd, token1_price_usd
        FROM lp_snapshots
        WHERE run_id = ? AND is_open = 1
    """, (prev_run['id'],)).fetchall()
    
    for pos in prev_positions:
        if pos['position_id'] not in current_position_ids:
            # Position was closed - record final fee event
            fee_value = (pos['token0_fees_uncollected'] * pos['token0_price_usd'] +
                         pos['token1_fees_uncollected'] * pos['token1_price_usd'])
            
            if fee_value > 0:
                insert_fee_event(
                    wallet=wallet, chain=pos['chain'], protocol=pos['protocol'],
                    position_id=pos['position_id'], pool_pair=pos['pool_pair'],
                    event_type='position_closed',
                    token0_symbol=pos['token0_symbol'], token1_symbol=pos['token1_symbol'],
                    token0_amount=pos['token0_fees_uncollected'],
                    token1_amount=pos['token1_fees_uncollected'],
                    value_usd=fee_value
                )
            
            # Insert a final snapshot marking position as closed
            insert_lp_snapshot(
                run_id=run_id, wallet=wallet, chain=pos['chain'],
                protocol=pos['protocol'], position_id=pos['position_id'],
                pool_pair=pos['pool_pair'],
                token0_symbol=pos['token0_symbol'], token1_symbol=pos['token1_symbol'],
                token0_amount=0, token1_amount=0,
                token0_fees_uncollected=0, token1_fees_uncollected=0,
                token0_fees_collected=pos['token0_fees_uncollected'],
                token1_fees_collected=pos['token1_fees_uncollected'],
                token0_price_usd=pos['token0_price_usd'],
                token1_price_usd=pos['token1_price_usd'],
                liquidity_value_usd=0, fees_uncollected_usd=0,
                fees_collected_usd=fee_value, total_value_usd=0,
                in_range=False, is_open=False
            )
            logger.info(f"Position {pos['position_id']} closed, final fees: ${fee_value:.2f}")
    
    conn.close()


def take_snapshot(wallet: str, portfolio_data: dict) -> int:
    """Take a full portfolio snapshot using data from get_portfolio_data().
    
    Args:
        wallet: Wallet address
        portfolio_data: Dict from web_portfolio.get_portfolio_data()
        
    Returns:
        run_id of the completed snapshot
    """
    init_db()
    start_time = time.time()
    run_id = create_snapshot_run(wallet)
    
    try:
        # --- Token snapshots ---
        for token in portfolio_data.get('tokens', []):
            if token.get('wallet', '').lower() != wallet.lower():
                continue
            insert_token_snapshot(
                run_id=run_id,
                wallet=wallet,
                chain=token['chain'],
                symbol=token['symbol'],
                address=token.get('token_address'),
                balance=token['balance'],
                price_usd=token.get('price_usd', 0),
                value_usd=token.get('value_usd', 0)
            )
        
        # --- LP position snapshots ---
        current_position_ids = set()
        
        for pos in portfolio_data.get('lp_positions', []):
            if pos.get('wallet', '').lower() != wallet.lower():
                continue
            
            position_id = str(pos['token_id'])
            current_position_ids.add(position_id)
            protocol = pos.get('protocol', 'uniswap_v3')
            
            fees_owed0 = pos.get('fees_owed0', 0)
            fees_owed1 = pos.get('fees_owed1', 0)
            
            # Detect fee collection events
            collection = detect_fee_collection(position_id, fees_owed0, fees_owed1)
            if collection:
                insert_fee_event(
                    wallet=wallet,
                    chain=collection['chain'],
                    protocol=collection['protocol'],
                    position_id=position_id,
                    pool_pair=collection['pool_pair'],
                    event_type='fee_collected',
                    token0_symbol=collection['token0_symbol'],
                    token1_symbol=collection['token1_symbol'],
                    token0_amount=collection['token0_amount'],
                    token1_amount=collection['token1_amount'],
                    value_usd=collection['value_usd']
                )
                logger.info(f"Fee collection detected for position {position_id}: ${collection['value_usd']:.2f}")
            
            # Get price per token from position data
            amount0 = pos.get('amount0', 0)
            amount1 = pos.get('amount1', 0)
            value0 = pos.get('value0_usd', 0)
            value1 = pos.get('value1_usd', 0)
            price0 = value0 / amount0 if amount0 > 0 else 0
            price1 = value1 / amount1 if amount1 > 0 else 0
            
            insert_lp_snapshot(
                run_id=run_id,
                wallet=wallet,
                chain=pos.get('chain', ''),
                protocol=protocol,
                position_id=position_id,
                pool_pair=pos.get('pair', ''),
                token0_symbol=pos.get('token0_symbol', ''),
                token1_symbol=pos.get('token1_symbol', ''),
                token0_amount=amount0,
                token1_amount=amount1,
                token0_fees_uncollected=fees_owed0,
                token1_fees_uncollected=fees_owed1,
                token0_fees_collected=pos.get('collected_fees_0', 0),
                token1_fees_collected=pos.get('collected_fees_1', 0),
                token0_price_usd=price0,
                token1_price_usd=price1,
                liquidity_value_usd=pos.get('total_value_usd', 0),
                fees_uncollected_usd=pos.get('total_fees_usd', 0),
                fees_collected_usd=pos.get('total_collected_fees_usd', 0),
                total_value_usd=pos.get('total_value_usd', 0) + pos.get('total_fees_usd', 0),
                in_range=pos.get('in_range', True),
                is_open=True
            )
        
        # Detect closed positions
        detect_position_closure(run_id, wallet, current_position_ids)
        
        duration = time.time() - start_time
        complete_snapshot_run(run_id, duration)
        logger.info(f"Snapshot completed for {wallet} in {duration:.1f}s (run_id={run_id})")
        return run_id
        
    except Exception as e:
        duration = time.time() - start_time
        fail_snapshot_run(run_id, duration)
        logger.error(f"Snapshot failed for {wallet}: {e}")
        raise


def take_full_snapshot(get_portfolio_func, wallet_addresses: List[str]) -> List[int]:
    """Take snapshots for all wallets.
    
    Args:
        get_portfolio_func: Callable that returns portfolio data dict
        wallet_addresses: List of wallet addresses
        
    Returns:
        List of run_ids
    """
    # Force refresh to get latest data
    portfolio_data = get_portfolio_func(force_refresh=True)
    
    run_ids = []
    for wallet in wallet_addresses:
        try:
            run_id = take_snapshot(wallet, portfolio_data)
            run_ids.append(run_id)
        except Exception as e:
            logger.error(f"Failed snapshot for {wallet}: {e}")
    
    return run_ids
