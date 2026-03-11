"""Arbitrum chain connector implementation."""

import os
import logging
from typing import Optional
import requests
from web3 import Web3
from web3.exceptions import ContractLogicError

from src.connectors.base import ChainConnector
from src.models import TokenMetadata, TokenTransfer, Chain


logger = logging.getLogger(__name__)

# ERC-20 Transfer event signature
TRANSFER_EVENT_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# ERC-20 ABI fragments for the methods we need
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
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    }
]


class ArbitrumConnector(ChainConnector):
    """Arbitrum mainnet RPC connector."""

    def __init__(self, rpc_url: Optional[str] = None):
        """Initialize Arbitrum connector.
        
        Args:
            rpc_url: Optional RPC URL. If not provided, reads from ARBITRUM_RPC_URL env var.
        """
        self.rpc_url = rpc_url or os.getenv("ARBITRUM_RPC_URL")
        if not self.rpc_url:
            raise ValueError("ARBITRUM_RPC_URL environment variable not set")
        
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        self.chain = Chain.ARBITRUM
        logger.info(f"Connected to Arbitrum at {self.rpc_url}")

    def get_token_transfers(self, wallet: str) -> list[TokenTransfer]:
        """Fetch ERC-20 Transfer logs for a wallet using Alchemy's native API.
        
        Uses alchemy_getTokenBalances to efficiently get all tokens without scanning logs.
        
        Args:
            wallet: Ethereum address to fetch transfers for
            
        Returns:
            List of TokenTransfer events (one per token with non-zero balance)
        """
        try:
            wallet_checksum = Web3.to_checksum_address(wallet)
            
            # Use Alchemy's native token balance API
            payload = {
                "id": 1,
                "jsonrpc": "2.0",
                "method": "alchemy_getTokenBalances",
                "params": [wallet_checksum, "erc20"]
            }
            
            response = requests.post(self.rpc_url, json=payload, timeout=30)
            
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
            
            result = response.json()
            
            if "error" in result:
                raise Exception(f"RPC error: {result['error']}")
            
            token_balances = result.get("result", {}).get("tokenBalances", [])
            
            # Convert to TokenTransfer format (one per token with non-zero balance)
            transfers = []
            
            for token in token_balances:
                balance_hex = token.get("tokenBalance", "0x0")
                balance = int(balance_hex, 16)
                
                if balance > 0:
                    token_address = token.get("contractAddress")
                    
                    # Create a pseudo-transfer to indicate this token exists
                    transfers.append(TokenTransfer(
                        token_address=Web3.to_checksum_address(token_address),
                        from_address="0x0000000000000000000000000000000000000000",
                        to_address=wallet_checksum,
                        block_number=0  # Not relevant for Alchemy API
                    ))
            
            logger.info(f"Found {len(transfers)} unique tokens for {wallet} on Arbitrum")
            return transfers
            
        except Exception as e:
            logger.error(f"Failed to fetch token transfers for {wallet}: {e}")
            raise ConnectionError(f"Failed to fetch token transfers: {e}")

    def get_token_balance(self, wallet: str, token_address: str) -> int:
        """Fetch raw balance of a token for a wallet.
        
        Args:
            wallet: Ethereum address to check balance for
            token_address: Token contract address
            
        Returns:
            Raw token balance (not adjusted for decimals)
        """
        try:
            wallet_checksum = Web3.to_checksum_address(wallet)
            token_checksum = Web3.to_checksum_address(token_address)
            
            contract = self.w3.eth.contract(address=token_checksum, abi=ERC20_ABI)
            balance = contract.functions.balanceOf(wallet_checksum).call()
            
            return balance
            
        except Exception as e:
            logger.error(f"Failed to fetch balance for {token_address}: {e}")
            raise

    def get_token_metadata(self, token_address: str) -> TokenMetadata:
        """Fetch symbol and decimals for a token contract using Alchemy's API.
        
        Args:
            token_address: Token contract address
            
        Returns:
            TokenMetadata with symbol, decimals, and chain info
        """
        try:
            token_checksum = Web3.to_checksum_address(token_address)
            
            # Use Alchemy's token metadata API
            payload = {
                "id": 1,
                "jsonrpc": "2.0",
                "method": "alchemy_getTokenMetadata",
                "params": [token_checksum]
            }
            
            response = requests.post(self.rpc_url, json=payload, timeout=30)
            
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
            
            result = response.json()
            
            if "error" in result:
                raise Exception(f"RPC error: {result['error']}")
            
            metadata = result.get("result", {})
            symbol = metadata.get("symbol", "UNKNOWN")
            decimals = metadata.get("decimals", 18)
            
            return TokenMetadata(
                address=token_checksum,
                symbol=symbol,
                decimals=decimals,
                chain=self.chain
            )
            
        except Exception as e:
            logger.error(f"Failed to fetch metadata for {token_address}: {e}")
            raise

    def get_block_timestamp(self, block_number: int) -> int:
        """Fetch timestamp for a block number.
        
        Args:
            block_number: Block number to fetch timestamp for
            
        Returns:
            Unix timestamp of the block
        """
        try:
            block = self.w3.eth.get_block(block_number)
            return block["timestamp"]
            
        except Exception as e:
            logger.error(f"Failed to fetch block {block_number}: {e}")
            raise
