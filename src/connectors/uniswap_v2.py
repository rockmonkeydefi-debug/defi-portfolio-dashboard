"""Uniswap V2 LP connector implementation."""

import os
import logging
from typing import Optional
from web3 import Web3

from src.connectors.base import LPConnector
from src.models import RawLPPosition, PoolData, TokenMetadata, LPType, Protocol, Chain


logger = logging.getLogger(__name__)

# Uniswap V2 Pair ABI fragments
PAIR_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "getReserves",
        "outputs": [
            {"name": "reserve0", "type": "uint112"},
            {"name": "reserve1", "type": "uint112"},
            {"name": "blockTimestampLast", "type": "uint32"}
        ],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
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


class UniswapV2Connector(LPConnector):
    """Uniswap V2 style LP connector for Ethereum mainnet."""

    def __init__(self, rpc_url: Optional[str] = None, chain: Chain = Chain.ETHEREUM):
        """Initialize Uniswap V2 connector.
        
        Args:
            rpc_url: Optional RPC URL. If not provided, reads from env var based on chain.
            chain: Chain to connect to (default: Ethereum)
        """
        self.chain = chain
        
        # Get RPC URL based on chain
        if rpc_url:
            self.rpc_url = rpc_url
        elif chain == Chain.ETHEREUM:
            self.rpc_url = os.getenv("ETHEREUM_RPC_URL")
        elif chain == Chain.ARBITRUM:
            self.rpc_url = os.getenv("ARBITRUM_RPC_URL")
        elif chain == Chain.BASE:
            self.rpc_url = os.getenv("BASE_RPC_URL")
        else:
            raise ValueError(f"Unsupported chain: {chain}")
        
        if not self.rpc_url:
            raise ValueError(f"RPC URL not configured for {chain.value}")
        
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        logger.info(f"Connected to Uniswap V2 on {chain.value}")

    def get_positions(self, wallet: str, chain: str) -> list[RawLPPosition]:
        """Fetch all Uniswap V2 LP positions for a wallet.
        
        This is a simplified implementation that requires pool addresses to be provided.
        In production, you would scan for LP token balances or use a subgraph.
        
        Args:
            wallet: Ethereum address to fetch positions for
            chain: Chain name (ethereum, arbitrum, base)
            
        Returns:
            List of raw LP positions
        """
        # Note: This is a minimal implementation
        # Production would scan for LP token balances or use The Graph
        logger.warning("UniswapV2Connector.get_positions requires pool addresses")
        return []

    def get_position_for_pool(self, wallet: str, pool_address: str) -> Optional[RawLPPosition]:
        """Fetch LP position for a specific pool.
        
        Args:
            wallet: Ethereum address to check
            pool_address: Uniswap V2 pair contract address
            
        Returns:
            RawLPPosition if wallet has balance, None otherwise
        """
        try:
            wallet_checksum = Web3.to_checksum_address(wallet)
            pool_checksum = Web3.to_checksum_address(pool_address)
            
            # Get LP token balance
            pair_contract = self.w3.eth.contract(address=pool_checksum, abi=PAIR_ABI)
            balance = pair_contract.functions.balanceOf(wallet_checksum).call()
            
            if balance == 0:
                return None
            
            return RawLPPosition(
                token_id=None,  # V2 doesn't use NFTs
                pool_address=pool_checksum,
                liquidity=balance,
                tick_lower=None,  # V2 doesn't have ticks
                tick_upper=None,
                lp_type=LPType.V2,
                protocol=Protocol.UNISWAP_V2,
                chain=self.chain,
                wallet=wallet_checksum
            )
            
        except Exception as e:
            logger.error(f"Failed to fetch position for pool {pool_address}: {e}")
            return None

    def get_pool_data(self, pool_address: str) -> PoolData:
        """Fetch current pool state for a Uniswap V2 pair.
        
        Args:
            pool_address: LP pool contract address
            
        Returns:
            PoolData with current pool state
        """
        try:
            pool_checksum = Web3.to_checksum_address(pool_address)
            pair_contract = self.w3.eth.contract(address=pool_checksum, abi=PAIR_ABI)
            
            # Get token addresses
            token0_address = pair_contract.functions.token0().call()
            token1_address = pair_contract.functions.token1().call()
            
            # Get token metadata
            token0_metadata = self._get_token_metadata(token0_address)
            token1_metadata = self._get_token_metadata(token1_address)
            
            # Get reserves
            reserves = pair_contract.functions.getReserves().call()
            reserve0 = reserves[0]
            reserve1 = reserves[1]
            
            # Calculate current price (token1 per token0)
            if reserve0 > 0:
                # Adjust for decimals
                reserve0_adjusted = reserve0 / (10 ** token0_metadata.decimals)
                reserve1_adjusted = reserve1 / (10 ** token1_metadata.decimals)
                current_price = reserve1_adjusted / reserve0_adjusted if reserve0_adjusted > 0 else 0
            else:
                current_price = 0
            
            # V2 has 0.3% fee (30 basis points)
            fee_tier = 30
            
            return PoolData(
                address=pool_checksum,
                token0=token0_metadata,
                token1=token1_metadata,
                fee_tier=fee_tier,
                tvl_usd=0.0,  # Would need price data to calculate
                current_price=current_price,
                sqrt_price_x96=0,  # V2 doesn't use sqrt price
                tick=0,  # V2 doesn't use ticks
                reserves=(reserve0, reserve1)
            )
            
        except Exception as e:
            logger.error(f"Failed to fetch pool data for {pool_address}: {e}")
            raise

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

