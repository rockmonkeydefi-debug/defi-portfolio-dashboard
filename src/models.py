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


class LPType(Enum):
    """LP position types."""
    V2 = "v2"  # Constant product (Uniswap v2, Aerodrome stable/volatile)
    V3 = "v3"  # Concentrated liquidity (Uniswap v3, Camelot v3)


class Protocol(Enum):
    """Supported DeFi protocols."""
    UNISWAP_V2 = "uniswap_v2"
    UNISWAP_V3 = "uniswap_v3"
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
