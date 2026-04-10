"""Camelot LP connector implementation for Arbitrum."""

import os
import logging
from typing import Optional
from web3 import Web3

from src.connectors.base import LPConnector
from src.models import RawLPPosition, PoolData, TokenMetadata, LPType, Protocol, Chain


logger = logging.getLogger(__name__)

# Camelot V3 uses Algebra-based concentrated liquidity (similar to Uniswap V3)
# NonfungiblePositionManager ABI fragments
POSITION_MANAGER_ABI = [
    {
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "positions",
        "outputs": [
            {"name": "nonce", "type": "uint96"},
            {"name": "operator", "type": "address"},
            {"name": "token0", "type": "address"},
            {"name": "token1", "type": "address"},
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

# Algebra Pool ABI fragments (Camelot V3 uses Algebra)
POOL_ABI = [
    {
        "inputs": [],
        "name": "globalState",
        "outputs": [
            {"name": "price", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "fee", "type": "uint16"},
            {"name": "timepointIndex", "type": "uint16"},
            {"name": "communityFeeToken0", "type": "uint8"},
            {"name": "communityFeeToken1", "type": "uint8"},
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

# Camelot V3 NonfungiblePositionManager address on Arbitrum
CAMELOT_POSITION_MANAGER = "0x00c7f3082833e796A5b3e4Bd59f6642FF44DCD15"


class CamelotConnector(LPConnector):
    """Camelot V3 concentrated liquidity LP connector for Arbitrum."""

    def __init__(self, rpc_url: Optional[str] = None):
        """Initialize Camelot connector.
        
        Args:
            rpc_url: Optional RPC URL. If not provided, reads from ARBITRUM_RPC_URL env var.
        """
        self.chain = Chain.ARBITRUM
        self.rpc_url = rpc_url or os.getenv("ARBITRUM_RPC_URL")
        
        if not self.rpc_url:
            raise ValueError("ARBITRUM_RPC_URL environment variable not set")
        
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        
        self.position_manager_address = CAMELOT_POSITION_MANAGER
        self.position_manager = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.position_manager_address),
            abi=POSITION_MANAGER_ABI
        )
        
        logger.info(f"Connected to Camelot V3 on Arbitrum")

    def get_positions(self, wallet: str, chain: str) -> list[RawLPPosition]:
        """Fetch all Camelot V3 NFT positions for a wallet.
        
        Args:
            wallet: Ethereum address to fetch positions for
            chain: Chain name (should be "arbitrum")
            
        Returns:
            List of raw LP positions
        """
        try:
            wallet_checksum = Web3.to_checksum_address(wallet)
            
            # Get number of NFTs owned by wallet
            balance = self.position_manager.functions.balanceOf(wallet_checksum).call()
            
            if balance == 0:
                logger.info(f"No Camelot V3 positions found for {wallet}")
                return []
            
            positions = []
            
            # Iterate through all NFTs
            for i in range(balance):
                try:
                    # Get token ID
                    token_id = self.position_manager.functions.tokenOfOwnerByIndex(
                        wallet_checksum, i
                    ).call()
                    
                    # Get position data
                    position_data = self.position_manager.functions.positions(token_id).call()
                    
                    # Extract position details
                    # position_data: (nonce, operator, token0, token1, tickLower, tickUpper,
                    #                 liquidity, feeGrowthInside0LastX128, feeGrowthInside1LastX128,
                    #                 tokensOwed0, tokensOwed1)
                    token0 = position_data[2]
                    token1 = position_data[3]
                    tick_lower = position_data[4]
                    tick_upper = position_data[5]
                    liquidity = position_data[6]
                    
                    # Skip positions with zero liquidity
                    if liquidity == 0:
                        continue
                    
                    # Compute pool address (deterministic from token0, token1)
                    pool_address = self._compute_pool_address(token0, token1)
                    if pool_address is None:
                        logger.warning(f"Skipping Camelot position {token_id}: pool address unavailable")
                        continue
                    
                    positions.append(RawLPPosition(
                        token_id=token_id,
                        pool_address=pool_address,
                        liquidity=liquidity,
                        tick_lower=tick_lower,
                        tick_upper=tick_upper,
                        lp_type=LPType.V3,
                        protocol=Protocol.CAMELOT,
                        chain=self.chain,
                        wallet=wallet_checksum
                    ))
                    
                except Exception as e:
                    logger.error(f"Failed to fetch position {i} for {wallet}: {e}")
                    continue
            
            logger.info(f"Found {len(positions)} Camelot V3 positions for {wallet}")
            return positions
            
        except Exception as e:
            logger.error(f"Failed to fetch positions for {wallet}: {e}")
            raise

    def get_pool_data(self, pool_address: str) -> PoolData:
        """Fetch current pool state for a Camelot V3 pool.
        
        Args:
            pool_address: LP pool contract address
            
        Returns:
            PoolData with current pool state
        """
        try:
            pool_checksum = Web3.to_checksum_address(pool_address)
            pool_contract = self.w3.eth.contract(address=pool_checksum, abi=POOL_ABI)
            
            # Get token addresses
            token0_address = pool_contract.functions.token0().call()
            token1_address = pool_contract.functions.token1().call()
            
            # Get token metadata
            token0_metadata = self._get_token_metadata(token0_address)
            token1_metadata = self._get_token_metadata(token1_address)
            
            # Get globalState (Algebra's equivalent of slot0)
            global_state = pool_contract.functions.globalState().call()
            sqrt_price_x96 = global_state[0]
            tick = global_state[1]
            fee = global_state[2]  # Dynamic fee in Algebra
            
            # Get liquidity
            liquidity = pool_contract.functions.liquidity().call()
            
            # Convert fee to basis points (Algebra uses different fee representation)
            # Algebra fee is in hundredths of a bip (1 bip = 0.01%)
            # So fee of 500 = 0.05% = 5 basis points
            fee_tier = fee // 100 if fee > 0 else 30  # Default to 30 bp if fee is 0
            
            # Calculate current price from sqrtPriceX96
            sqrt_price = sqrt_price_x96 / (2 ** 96)
            price_raw = sqrt_price ** 2
            
            # Adjust for decimals: price is in terms of token1 per token0
            decimal_adjustment = 10 ** (token1_metadata.decimals - token0_metadata.decimals)
            current_price = price_raw * decimal_adjustment
            
            return PoolData(
                address=pool_checksum,
                token0=token0_metadata,
                token1=token1_metadata,
                fee_tier=fee_tier,
                tvl_usd=0.0,  # Would need price data to calculate
                current_price=current_price,
                sqrt_price_x96=sqrt_price_x96,
                tick=tick,
                reserves=(0, 0)  # V3-style doesn't have simple reserves
            )
            
        except Exception as e:
            logger.error(f"Failed to fetch pool data for {pool_address}: {e}")
            raise

    def _compute_pool_address(self, token0: str, token1: str) -> str:
        """Compute Camelot V3 pool address from token pair.
        
        This is a simplified version. In production, you would use the actual
        CREATE2 computation with the factory address and init code hash.
        
        Args:
            token0: Token0 address
            token1: Token1 address
            
        Returns:
            Pool address (checksum)
        """
        # For now, we'll need to query this from the factory or use a subgraph
        # This is a placeholder that returns a deterministic address
        # In production, implement proper CREATE2 address computation
        
        # Sort tokens
        if int(token0, 16) > int(token1, 16):
            token0, token1 = token1, token0
        
        # This is a placeholder - in production, use proper CREATE2 computation
        # or query the factory contract
        logger.debug("Pool address computation is simplified - use factory query in production")
        
        # Return None — caller should skip if pool address can't be computed
        return None

    def _get_token_metadata(self, token_address: str) -> TokenMetadata:
        """Fetch token metadata (symbol, decimals).
        
        Args:
            token_address: Token contract address
            
        Returns:
            TokenMetadata
        """
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
            # Return default values
            return TokenMetadata(
                address=Web3.to_checksum_address(token_address),
                symbol="UNKNOWN",
                decimals=18,
                chain=self.chain
            )

