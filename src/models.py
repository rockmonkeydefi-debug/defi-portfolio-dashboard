"""Data models for DeFi Portfolio PoC."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Chain(Enum):
    """Supported blockchain networks."""
    ETHEREUM = "ethereum"
    ARBITRUM = "arbitrum"
    BASE = "base"


# --- Shared chain configuration ---
CHAIN_RPC_ENV = {
    "ethereum": "ETHEREUM_RPC_URL",
    "arbitrum": "ARBITRUM_RPC_URL",
    "base": "BASE_RPC_URL",
}

CHAIN_DISPLAY_NAMES = {
    "ethereum": "Ethereum",
    "arbitrum": "Arbitrum",
    "base": "Base",
}

# --- Canonical token group definitions (single source of truth) ---
ETH_SYMBOLS = {'ETH', 'WETH', 'stETH', 'wstETH', 'cbETH', 'rETH', 'weETH', 'eETH'}
BTC_SYMBOLS = {'BTC', 'WBTC', 'cbBTC', 'tBTC', 'sBTC'}
STABLECOIN_SYMBOLS = {
    'USDC', 'USDT', 'DAI', 'FRAX', 'LUSD', 'TUSD', 'BUSD', 'GUSD',
    'USDP', 'sUSD', 'crvUSD', 'GHO', 'PYUSD', 'USDe', 'USDS', 'USDC.e', 'USDT0',
}


def is_stablecoin(symbol: str) -> bool:
    """Check if a token symbol is a plain stablecoin."""
    return symbol in STABLECOIN_SYMBOLS


def is_yield_stablecoin(symbol: str) -> bool:
    """Check if a token is a yield-bearing stablecoin (syrupUSDC, aEthUSDC, etc.)."""
    if symbol in STABLECOIN_SYMBOLS:
        return False
    s = symbol.lower()
    return any(base in s for base in ('usdc', 'usdt', 'usd', 'dai'))


def get_rpc_url(chain: str) -> Optional[str]:
    """Get RPC URL for a chain from environment."""
    import os
    env_key = CHAIN_RPC_ENV.get(chain, "")
    return os.getenv(env_key) if env_key else None


# Cached Web3 instances per RPC URL
_web3_cache: dict = {}


def get_web3(chain: str):
    """Get a cached Web3 instance for a chain. Returns None if RPC URL not configured."""
    url = get_rpc_url(chain)
    if not url:
        return None
    if url not in _web3_cache:
        from web3 import Web3
        _web3_cache[url] = Web3(Web3.HTTPProvider(url))
    return _web3_cache[url]


class LPType(Enum):
    """LP position types."""
    V2 = "v2"  # Constant product (Uniswap v2, Aerodrome stable/volatile)
    V3 = "v3"  # Concentrated liquidity (Uniswap v3, Camelot v3)
    V4 = "v4"  # Concentrated liquidity, singleton PoolManager (Uniswap v4)


class Protocol(Enum):
    """Supported DeFi protocols."""
    UNISWAP_V2 = "uniswap_v2"
    UNISWAP_V3 = "uniswap_v3"
    UNISWAP_V4 = "uniswap_v4"
    AERODROME = "aerodrome"
    CAMELOT = "camelot"


@dataclass
class TokenMetadata:
    """Token contract metadata."""
    address: str
    symbol: str
    decimals: int
    chain: Chain


@dataclass
class TokenHolding:
    """Token balance with pricing information."""
    token: TokenMetadata
    raw_balance: int
    human_balance: float  # raw_balance / 10^decimals
    price_usd: float
    value_usd: float


@dataclass
class TokenTransfer:
    """ERC-20 transfer event."""
    token_address: str
    from_address: str
    to_address: str
    block_number: int


@dataclass
class PoolData:
    """LP pool state data."""
    address: str
    token0: TokenMetadata
    token1: TokenMetadata
    fee_tier: int  # basis points
    tvl_usd: float
    current_price: float  # token0 per token1
    sqrt_price_x96: int  # for v3
    tick: int  # for v3
    reserves: tuple[int, int]  # for v2


@dataclass
class RawLPPosition:
    """Raw LP position data from chain."""
    token_id: Optional[int]  # NFT token ID for v3, None for v2
    pool_address: str
    liquidity: int
    tick_lower: Optional[int]  # v3 only
    tick_upper: Optional[int]  # v3 only
    lp_type: LPType
    protocol: Protocol
    chain: Chain
    wallet: str


@dataclass
class LPPositionAnalytics:
    """Computed LP position analytics."""
    raw: RawLPPosition
    pool: PoolData
    pool_name: str  # e.g., "WETH/USDC"
    protocol: Protocol
    chain: Chain
    lp_type: LPType

    # Value
    token0_amount: float
    token1_amount: float
    value_usd: float

    # Range (v3 only, None for v2)
    price_lower: Optional[float]
    price_upper: Optional[float]
    current_price: float
    pct_distance_upper: Optional[float]
    pct_distance_lower: Optional[float]
    in_range: bool

    # Yield
    liquidity_share_pct: float
    tvl_usd: float
    fee_apr: float
    incentive_apr: float
    daily_fee_revenue: float
    weekly_fee_revenue: float
    monthly_fee_revenue: float
    historical_fees_usd: float

    # Risk
    il_20pct: float  # IL at ±20%
    il_40pct: float  # IL at ±40%


@dataclass
class AggregatedLPAnalytics:
    """Aggregated LP metrics across all positions."""
    total_lp_value_usd: float
    total_fees_per_day: float
    weighted_il_risk: float
    pct_in_concentrated: float


@dataclass
class LendingPosition:
    """Aave v3 lending position with risk metrics."""
    wallet: str
    chain: Chain
    supplied: list[TokenHolding]
    borrowed: list[TokenHolding]
    total_supplied_usd: float
    total_borrowed_usd: float
    ltv: float
    health_factor: float
    liquidation_threshold: float
    liquidation_prices: dict[str, dict[str, float]]  # {token: {"-30%": price, "-40%": price}}
    net_borrow_cost: float


@dataclass
class PortfolioSnapshot:
    """Daily portfolio snapshot for historical tracking."""
    date: str
    total_usd: float
    btc_equivalent: float
    eth_equivalent: float
    total_fees: float
    total_borrow_cost: float
    ltv: float


@dataclass
class StrategyConfig:
    """User-defined strategy parameters."""
    target_apy: float
    max_ltv: float
    max_high_beta_pct: float
    il_tolerance: float
