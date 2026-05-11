"""Aerodrome Slipstream (concentrated liquidity) connector for Base chain.

Aerodrome Slipstream is a Uniswap V3 fork with two key differences:
1. Pools are identified by (token0, token1, tickSpacing) instead of (token0, token1, fee)
2. The positions() call returns tickSpacing at index 4 instead of fee
3. Fee tier is stored on the pool itself, not fixed per tickSpacing (CustomSwapFeeModule)

Contracts follow the same NFT position manager pattern as Uniswap V3, so the overall
flow (balanceOf → tokenOfOwnerByIndex → positions()) is identical.
"""

import os
import logging
from typing import Optional
from web3 import Web3

from src.connectors.base import LPConnector
from src.models import RawLPPosition, PoolData, TokenMetadata, LPType, Protocol, Chain


logger = logging.getLogger(__name__)

# Aerodrome Slipstream NonfungiblePositionManager ABI fragments
# Note: positions() returns tickSpacing at index 4 instead of fee (like Uniswap V3)
POSITION_MANAGER_ABI = [
    {
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "positions",
        "outputs": [
            {"name": "nonce", "type": "uint96"},
            {"name": "operator", "type": "address"},
            {"name": "token0", "type": "address"},
            {"name": "token1", "type": "address"},
            {"name": "tickSpacing", "type": "int24"},
            {"name": "tickLower", "type": "int24"},
            {"name": "tickUpper", "type": "int24"},
            {"name": "liquidity", "type": "uint128"},
            {"name": "feeGrowthInside0LastX128", "type": "uint256"},
            {"name": "feeGrowthInside1LastX128", "type": "uint256"},
            {"name": "tokensOwed0", "type": "uint128"},
            {"name": "tokensOwed1", "type": "uint128"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "index", "type": "uint256"}
        ],
        "name": "tokenOfOwnerByIndex",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Aerodrome Slipstream Pool ABI fragments
# Same as Uniswap V3 but the pool's `fee()` is dynamic (set by SwapFeeModule)
POOL_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "observationIndex", "type": "uint16"},
            {"name": "observationCardinality", "type": "uint16"},
            {"name": "observationCardinalityNext", "type": "uint16"},
            {"name": "unlocked", "type": "bool"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "liquidity",
        "outputs": [{"name": "", "type": "uint128"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "tickSpacing",
        "outputs": [{"name": "", "type": "int24"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "fee",
        "outputs": [{"name": "", "type": "uint24"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "feeGrowthGlobal0X128",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "feeGrowthGlobal1X128",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"name": "tick", "type": "int24"}],
        "name": "ticks",
        "outputs": [
            {"name": "liquidityGross", "type": "uint128"},
            {"name": "liquidityNet", "type": "int128"},
            {"name": "stakedLiquidityNet", "type": "int128"},
            {"name": "feeGrowthOutside0X128", "type": "uint256"},
            {"name": "feeGrowthOutside1X128", "type": "uint256"},
            {"name": "rewardGrowthOutsideX128", "type": "uint256"},
            {"name": "tickCumulativeOutside", "type": "int56"},
            {"name": "secondsPerLiquidityOutsideX128", "type": "uint160"},
            {"name": "secondsOutside", "type": "uint32"},
            {"name": "initialized", "type": "bool"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

# Aerodrome Slipstream PoolFactory ABI
# getPool takes tickSpacing instead of fee
POOL_FACTORY_ABI = [
    {
        "inputs": [
            {"name": "tokenA", "type": "address"},
            {"name": "tokenB", "type": "address"},
            {"name": "tickSpacing", "type": "int24"}
        ],
        "name": "getPool",
        "outputs": [{"name": "pool", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Voter resolves pool -> CL gauge. Staked NFTs are owned by the gauge,
# not the wallet, so positionManager.balanceOf(wallet) misses them.
VOTER_ABI = [
    {
        "inputs": [{"name": "pool", "type": "address"}],
        "name": "gauges",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# CL Gauge:
#   stakedValues(depositor)        — tokenIds the wallet has staked
#   pool()                          — underlying pool (used when we only know the gauge addr)
#   earned(account, tokenId)        — pending reward token (AERO) for this position
#   rewardToken()                   — address of the reward token (AERO on Base)
CL_GAUGE_ABI = [
    {
        "inputs": [{"name": "depositor", "type": "address"}],
        "name": "stakedValues",
        "outputs": [{"name": "", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "pool",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "tokenId", "type": "uint256"}
        ],
        "name": "earned",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "rewardToken",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# ERC-20 ABI fragments
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    }
]

# Aerodrome Slipstream deployed contracts on Base (Initial Deployment)
# Source: https://github.com/aerodrome-finance/slipstream
POSITION_MANAGER_ADDRESS = "0x827922686190790b37229fd06084350E74485b72"
POOL_FACTORY_ADDRESS = "0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A"
VOTER_ADDRESS = "0x16613524e02ad97eDfeF371bC883F2F5d6C480A5"


class AerodromeSlipstreamConnector(LPConnector):
    """Aerodrome Slipstream concentrated liquidity LP connector (Base only)."""

    def __init__(self, rpc_url: Optional[str] = None):
        """Initialize Aerodrome Slipstream connector.

        Args:
            rpc_url: Optional RPC URL. If not provided, reads BASE_RPC_URL from env.
        """
        self.chain = Chain.BASE
        self.rpc_url = rpc_url or os.getenv("BASE_RPC_URL")

        if not self.rpc_url:
            raise ValueError("BASE_RPC_URL not configured")

        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))

        self.position_manager_address = POSITION_MANAGER_ADDRESS
        self.position_manager = self.w3.eth.contract(
            address=Web3.to_checksum_address(POSITION_MANAGER_ADDRESS),
            abi=POSITION_MANAGER_ABI
        )
        self.pool_factory_address = POOL_FACTORY_ADDRESS
        self.pool_factory = self.w3.eth.contract(
            address=Web3.to_checksum_address(POOL_FACTORY_ADDRESS),
            abi=POOL_FACTORY_ABI
        )
        self.voter_address = VOTER_ADDRESS
        self.voter = self.w3.eth.contract(
            address=Web3.to_checksum_address(VOTER_ADDRESS),
            abi=VOTER_ABI
        )

        logger.info("Connected to Aerodrome Slipstream on Base")

    def resolve_gauge(self, address: str) -> Optional[str]:
        """Resolve a gauge address from either a pool or gauge address.

        Zerion's `pool_address` for staked positions returns the gauge directly,
        for unstaked positions it returns the pool. This helper accepts either:
          1. Voter.gauges(addr) — if non-zero, addr was a pool and we got the gauge.
          2. Otherwise treat addr as a gauge and confirm via gauge.pool().

        Returns the checksummed gauge address, or None if neither path resolves.
        """
        try:
            addr_cs = Web3.to_checksum_address(address)
            try:
                resolved = self.voter.functions.gauges(addr_cs).call()
                if int(resolved, 16) != 0:
                    return Web3.to_checksum_address(resolved)
            except Exception:
                pass
            # Treat addr as a gauge directly — confirm by calling pool() on it
            gauge = self.w3.eth.contract(address=addr_cs, abi=CL_GAUGE_ABI)
            try:
                gauge.functions.pool().call()
                return addr_cs
            except Exception:
                return None
        except Exception as e:
            logger.error(f"Failed to resolve gauge for {address}: {e}")
            return None

    def gauge_for_pool(self, pool_address: str) -> Optional[str]:
        """Return the checksummed gauge address for a given pool, or None."""
        try:
            pool_cs = Web3.to_checksum_address(pool_address)
            gauge_addr = self.voter.functions.gauges(pool_cs).call()
            if int(gauge_addr, 16) == 0:
                return None
            return Web3.to_checksum_address(gauge_addr)
        except Exception as e:
            logger.error(f"Failed to look up gauge for pool {pool_address}: {e}")
            return None

    def get_staked_token_ids(self, wallet: str, address: str) -> list[int]:
        """Return tokenIds the wallet has staked, given a pool OR gauge address.

        Aerodrome's CL gauge takes custody of the NFT, so the regular
        balanceOf(wallet) on the position manager misses staked positions.
        Returns an empty list if no gauge can be resolved or on any RPC error.
        """
        gauge_addr = self.resolve_gauge(address)
        if not gauge_addr:
            return []
        try:
            wallet_cs = Web3.to_checksum_address(wallet)
            gauge = self.w3.eth.contract(address=gauge_addr, abi=CL_GAUGE_ABI)
            return list(gauge.functions.stakedValues(wallet_cs).call())
        except Exception as e:
            logger.error(
                f"Failed to fetch staked token ids for wallet {wallet} addr {address}: {e}"
            )
            return []

    def get_pending_aero(self, gauge_address: str, wallet: str, token_id: int) -> int:
        """Return pending reward (AERO, raw wei) for a staked position. 0 on error."""
        try:
            gauge_cs = Web3.to_checksum_address(gauge_address)
            wallet_cs = Web3.to_checksum_address(wallet)
            gauge = self.w3.eth.contract(address=gauge_cs, abi=CL_GAUGE_ABI)
            return int(gauge.functions.earned(wallet_cs, token_id).call())
        except Exception as e:
            logger.error(
                f"Failed to fetch pending reward for token {token_id} on gauge {gauge_address}: {e}"
            )
            return 0

    def get_reward_token(self, gauge_address: str) -> Optional[str]:
        """Return the reward token address for a gauge (AERO on Base), or None."""
        try:
            gauge_cs = Web3.to_checksum_address(gauge_address)
            gauge = self.w3.eth.contract(address=gauge_cs, abi=CL_GAUGE_ABI)
            return Web3.to_checksum_address(gauge.functions.rewardToken().call())
        except Exception as e:
            logger.error(f"Failed to fetch reward token for gauge {gauge_address}: {e}")
            return None

    def get_positions(self, wallet: str, chain: str) -> list[RawLPPosition]:
        """Fetch all Aerodrome Slipstream NFT positions for a wallet.

        Args:
            wallet: EVM address to fetch positions for
            chain: Chain name (must be "base")

        Returns:
            List of raw LP positions (liquidity > 0 only)
        """
        try:
            wallet_checksum = Web3.to_checksum_address(wallet)
            balance = self.position_manager.functions.balanceOf(wallet_checksum).call()

            if balance == 0:
                logger.info(f"No Aerodrome Slipstream positions for {wallet}")
                return []

            positions = []
            for i in range(balance):
                try:
                    token_id = self.position_manager.functions.tokenOfOwnerByIndex(
                        wallet_checksum, i
                    ).call()
                    position_data = self.position_manager.functions.positions(token_id).call()

                    # position_data: (nonce, operator, token0, token1, tickSpacing,
                    #                 tickLower, tickUpper, liquidity, ...)
                    token0 = position_data[2]
                    token1 = position_data[3]
                    tick_spacing = position_data[4]
                    tick_lower = position_data[5]
                    tick_upper = position_data[6]
                    liquidity = position_data[7]

                    if liquidity == 0:
                        continue

                    # Resolve pool address via factory
                    pool_address = self.pool_factory.functions.getPool(
                        token0, token1, tick_spacing
                    ).call()

                    positions.append(RawLPPosition(
                        token_id=token_id,
                        pool_address=pool_address,
                        liquidity=liquidity,
                        tick_lower=tick_lower,
                        tick_upper=tick_upper,
                        lp_type=LPType.V3,
                        protocol=Protocol.AERODROME,
                        chain=Chain.BASE,
                        wallet=wallet_checksum
                    ))

                except Exception as e:
                    logger.error(f"Failed to fetch Aerodrome Slipstream position {i} for {wallet}: {e}")
                    continue

            logger.info(f"Found {len(positions)} Aerodrome Slipstream positions for {wallet}")
            return positions

        except Exception as e:
            logger.error(f"Failed to fetch Aerodrome Slipstream positions for {wallet}: {e}")
            raise

    def get_pool_data(self, pool_address: str) -> PoolData:
        """Fetch current pool state for an Aerodrome Slipstream pool."""
        try:
            pool_checksum = Web3.to_checksum_address(pool_address)
            pool_contract = self.w3.eth.contract(address=pool_checksum, abi=POOL_ABI)

            token0_address = pool_contract.functions.token0().call()
            token1_address = pool_contract.functions.token1().call()
            token0_metadata = self._get_token_metadata(token0_address)
            token1_metadata = self._get_token_metadata(token1_address)

            slot0 = pool_contract.functions.slot0().call()
            sqrt_price_x96 = slot0[0]
            tick = slot0[1]
            liquidity = pool_contract.functions.liquidity().call()
            fee = pool_contract.functions.fee().call()
            fee_tier = fee / 10000  # convert to percent

            sqrt_price = sqrt_price_x96 / (2 ** 96)
            price_raw = sqrt_price ** 2
            decimal_adjustment = 10 ** (token1_metadata.decimals - token0_metadata.decimals)
            current_price = price_raw * decimal_adjustment

            return PoolData(
                address=pool_checksum,
                token0=token0_metadata,
                token1=token1_metadata,
                fee_tier=fee_tier,
                tvl_usd=0.0,
                current_price=current_price,
                sqrt_price_x96=sqrt_price_x96,
                tick=tick,
                reserves=(0, 0)
            )
        except Exception as e:
            logger.error(f"Failed to fetch Aerodrome Slipstream pool data for {pool_address}: {e}")
            raise

    def _get_token_metadata(self, token_address: str) -> TokenMetadata:
        """Fetch token metadata (symbol, decimals) from an ERC-20 contract."""
        try:
            token_checksum = Web3.to_checksum_address(token_address)
            token_contract = self.w3.eth.contract(address=token_checksum, abi=ERC20_ABI)
            symbol = token_contract.functions.symbol().call()
            decimals = token_contract.functions.decimals().call()
            return TokenMetadata(
                address=token_checksum,
                symbol=symbol,
                decimals=decimals,
                chain=self.chain
            )
        except Exception as e:
            logger.error(f"Failed to fetch token metadata for {token_address}: {e}")
            return TokenMetadata(
                address=Web3.to_checksum_address(token_address),
                symbol="UNKNOWN",
                decimals=18,
                chain=self.chain
            )
