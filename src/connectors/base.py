"""Abstract base classes for connectors."""

from abc import ABC, abstractmethod
from typing import Protocol

from src.models import (
    TokenMetadata,
    TokenTransfer,
    RawLPPosition,
    PoolData,
)


class ChainConnector(ABC):
    """Abstract interface for chain-specific RPC interactions."""

    @abstractmethod
    def get_token_transfers(self, wallet: str) -> list[TokenTransfer]:
        """Fetch ERC-20 Transfer logs for a wallet.
        
        Args:
            wallet: Ethereum address to fetch transfers for
            
        Returns:
            List of TokenTransfer events
        """
        ...

    @abstractmethod
    def get_token_balance(self, wallet: str, token_address: str) -> int:
        """Fetch raw balance of a token for a wallet.
        
        Args:
            wallet: Ethereum address to check balance for
            token_address: Token contract address
            
        Returns:
            Raw token balance (not adjusted for decimals)
        """
        ...

    @abstractmethod
    def get_token_metadata(self, token_address: str) -> TokenMetadata:
        """Fetch symbol and decimals for a token contract.
        
        Args:
            token_address: Token contract address
            
        Returns:
            TokenMetadata with symbol, decimals, and chain info
        """
        ...

    @abstractmethod
    def get_block_timestamp(self, block_number: int) -> int:
        """Fetch timestamp for a block number.
        
        Args:
            block_number: Block number to fetch timestamp for
            
        Returns:
            Unix timestamp of the block
        """
        ...


class PriceProvider(ABC):
    """Abstract interface for price data sources."""

    @abstractmethod
    def get_prices(self, token_addresses: list[str], chain: str) -> dict[str, float]:
        """Fetch USD prices for a list of token addresses.
        
        Args:
            token_addresses: List of token contract addresses
            chain: Chain name (ethereum, arbitrum, base)
            
        Returns:
            Dictionary mapping address to USD price
        """
        ...


class LPConnector(ABC):
    """Abstract interface for LP protocol connectors."""

    @abstractmethod
    def get_positions(self, wallet: str, chain: str) -> list[RawLPPosition]:
        """Fetch all LP positions for a wallet on a chain.
        
        Args:
            wallet: Ethereum address to fetch positions for
            chain: Chain name (ethereum, arbitrum, base)
            
        Returns:
            List of raw LP positions
        """
        ...

    @abstractmethod
    def get_pool_data(self, pool_address: str) -> PoolData:
        """Fetch current pool state (reserves, tick, fee tier, TVL).
        
        Args:
            pool_address: LP pool contract address
            
        Returns:
            PoolData with current pool state
        """
        ...


class LendingConnector(ABC):
    """Abstract interface for lending protocol connectors."""

    @abstractmethod
    def get_positions(self, wallet: str, chain: str) -> dict:
        """Fetch supply and borrow positions for a wallet.
        
        Args:
            wallet: Ethereum address to fetch positions for
            chain: Chain name (ethereum, arbitrum, base)
            
        Returns:
            Dictionary with raw lending position data
        """
        ...
