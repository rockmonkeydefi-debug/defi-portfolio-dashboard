"""Uniswap V3 LP connector implementation."""

import os
import logging
from typing import Optional
from web3 import Web3

from src.connectors.base import LPConnector
from src.models import RawLPPosition, PoolData, TokenMetadata, LPType, Protocol, Chain


logger = logging.getLogger(__name__)

# Uniswap V3 NonfungiblePositionManager ABI fragments
POSITION_MANAGER_ABI = [
    {
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "positions",
        "outputs": [
            {"name": "nonce", "type": "uint96"},
            {"name": "operator", "type": "address"},
            {"name": "token0", "type": "address"},
            {"name": "token1", "type": "address"},
            {"name": "fee", "type": "uint24"},
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
    },
    {
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "ownerOf",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Uniswap V3 Pool ABI fragments
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
            {"name": "feeProtocol", "type": "uint8"},
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
            {"name": "feeGrowthOutside0X128", "type": "uint256"},
            {"name": "feeGrowthOutside1X128", "type": "uint256"},
            {"name": "tickCumulativeOutside", "type": "int56"},
            {"name": "secondsPerLiquidityOutsideX128", "type": "uint160"},
            {"name": "secondsOutside", "type": "uint32"},
            {"name": "initialized", "type": "bool"}
        ],
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

# Uniswap V3 NonfungiblePositionManager addresses by chain
POSITION_MANAGER_ADDRESSES = {
    Chain.ETHEREUM: "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
    Chain.ARBITRUM: "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
    Chain.BASE: "0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1"
}


class UniswapV3Connector(LPConnector):
    """Uniswap V3 concentrated liquidity LP connector."""

    def __init__(self, rpc_url: Optional[str] = None, chain: Chain = Chain.ETHEREUM):
        """Initialize Uniswap V3 connector.
        
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
        
        # Get position manager address for this chain
        if chain not in POSITION_MANAGER_ADDRESSES:
            raise ValueError(f"Uniswap V3 not supported on {chain.value}")
        
        self.position_manager_address = POSITION_MANAGER_ADDRESSES[chain]
        self.position_manager = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.position_manager_address),
            abi=POSITION_MANAGER_ABI
        )
        
        logger.info(f"Connected to Uniswap V3 on {chain.value}")

    def get_positions(self, wallet: str, chain: str) -> list[RawLPPosition]:
        """Fetch all Uniswap V3 NFT positions for a wallet.
        
        Args:
            wallet: Ethereum address to fetch positions for
            chain: Chain name (ethereum, arbitrum, base)
            
        Returns:
            List of raw LP positions
        """
        try:
            wallet_checksum = Web3.to_checksum_address(wallet)
            
            # Get number of NFTs owned by wallet
            balance = self.position_manager.functions.balanceOf(wallet_checksum).call()
            
            if balance == 0:
                logger.info(f"No Uniswap V3 positions found for {wallet}")
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
                    # position_data: (nonce, operator, token0, token1, fee, tickLower, tickUpper, 
                    #                 liquidity, feeGrowthInside0LastX128, feeGrowthInside1LastX128,
                    #                 tokensOwed0, tokensOwed1)
                    token0 = position_data[2]
                    token1 = position_data[3]
                    fee = position_data[4]
                    tick_lower = position_data[5]
                    tick_upper = position_data[6]
                    liquidity = position_data[7]
                    
                    # Skip positions with zero liquidity
                    if liquidity == 0:
                        continue
                    
                    # Compute pool address (deterministic from token0, token1, fee)
                    pool_address = self._compute_pool_address(token0, token1, fee)
                    
                    positions.append(RawLPPosition(
                        token_id=token_id,
                        pool_address=pool_address,
                        liquidity=liquidity,
                        tick_lower=tick_lower,
                        tick_upper=tick_upper,
                        lp_type=LPType.V3,
                        protocol=Protocol.UNISWAP_V3,
                        chain=self.chain,
                        wallet=wallet_checksum
                    ))
                    
                except Exception as e:
                    logger.error(f"Failed to fetch position {i} for {wallet}: {e}")
                    continue
            
            logger.info(f"Found {len(positions)} Uniswap V3 positions for {wallet}")
            return positions

        except Exception as e:
            logger.error(f"Failed to fetch positions for {wallet}: {e}")
            raise

    def discover_unenumerated_positions(
        self, wallet: str, wanted_pair_keys: dict, pair_key_fn, exclude_token_ids=None,
    ) -> list[RawLPPosition]:
        """Find open positions that `get_positions` can't see, for specific pairs.

        `balanceOf`/`tokenOfOwnerByIndex` only enumerate NFTs the wallet
        *currently holds*, so a position custodied by a manager or staking
        contract is invisible to it — even though the wallet still owns it
        economically and Zerion still reports it. `positions(tokenId)` is a
        public getter that works regardless of ownership, so given a tokenId we
        can still read that position's ticks.

        Args:
            wallet: owner to search Transfer history for.
            wanted_pair_keys: {pair_key: how many positions are still missing}.
                Only pairs listed here are considered, and never more than the
                stated count — this method exists to close a known gap, not to
                discover positions nothing else reported.
            pair_key_fn: callable(symbol0, symbol1) -> pair_key, so the caller's
                pair-identity convention is the one used here.
            exclude_token_ids: tokenIds already enriched by `get_positions`.

        Safety: a candidate is only accepted when it is unambiguous. If more
        candidates match a pair than are missing, none are returned for that
        pair — an ambiguous match could attribute a *different* position's range
        to this row (e.g. an older closed-and-reopened position on the same
        pair), and wrong range data is worse than none. Same for any candidate
        whose NFT now sits with a different EOA (i.e. sold, not custodied).
        Returns [] rather than raising: this is a best-effort gap filler and
        every failure mode must degrade to "no extra positions found".
        """
        from src.connectors.erc721_discovery import discover_incoming_token_ids

        if not wanted_pair_keys:
            return []
        exclude = set(exclude_token_ids or ())

        try:
            wallet_checksum = Web3.to_checksum_address(wallet)
            chain_id = self.w3.eth.chain_id
        except Exception as e:
            logger.warning(f"V3 gap discovery: could not read chain state: {e}")
            return []

        candidate_ids = discover_incoming_token_ids(
            chain_id, self.position_manager_address, wallet_checksum
        )
        if not candidate_ids:
            # None (no key / query failed) or [] (nothing ever received) —
            # either way there is nothing safe to add.
            return []

        # Group candidates by pair, keeping only open positions this wallet
        # still plausibly owns.
        by_pair: dict = {}
        for token_id in candidate_ids:
            if token_id in exclude:
                continue
            try:
                data = self.position_manager.functions.positions(token_id).call()
                token0, token1 = data[2], data[3]
                fee, tick_lower, tick_upper, liquidity = data[4], data[5], data[6], data[7]
                if liquidity == 0:
                    continue  # closed position — no live range to show

                owner = self.position_manager.functions.ownerOf(token_id).call()
                owner = Web3.to_checksum_address(owner)
                if owner != wallet_checksum:
                    # Held by someone else. A contract is consistent with a
                    # manager/gauge custodying it for this wallet; another EOA
                    # means it was sold and is no longer this wallet's position.
                    if self.w3.eth.get_code(owner) in (b"", "0x", None):
                        continue

                key = pair_key_fn(
                    self._get_token_metadata(token0).symbol,
                    self._get_token_metadata(token1).symbol,
                )
                if key not in wanted_pair_keys:
                    continue
                by_pair.setdefault(key, []).append(RawLPPosition(
                    token_id=token_id,
                    pool_address=self._compute_pool_address(token0, token1, fee),
                    liquidity=liquidity,
                    tick_lower=tick_lower,
                    tick_upper=tick_upper,
                    lp_type=LPType.V3,
                    protocol=Protocol.UNISWAP_V3,
                    chain=self.chain,
                    wallet=wallet_checksum,
                ))
            except Exception as e:
                logger.warning(f"V3 gap discovery: could not inspect token {token_id}: {e}")
                continue

        found: list[RawLPPosition] = []
        for key, wanted in wanted_pair_keys.items():
            matches = by_pair.get(key, [])
            if not matches:
                continue
            if len(matches) != wanted:
                # Ambiguous: cannot tell which candidate is the reported
                # position. Leave it to tier-3 nulls rather than guess.
                logger.info(
                    f"V3 gap discovery: {len(matches)} candidate(s) for pair {key} "
                    f"but {wanted} missing — ambiguous, leaving unenriched"
                )
                continue
            found.extend(matches)

        if found:
            logger.info(
                f"V3 gap discovery: recovered {len(found)} manager-held position(s) "
                f"for {wallet_checksum}"
            )
        return found

    def get_pool_data(self, pool_address: str) -> PoolData:
        """Fetch current pool state for a Uniswap V3 pool.
        
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
            
            # Get slot0 (current price and tick)
            slot0 = pool_contract.functions.slot0().call()
            sqrt_price_x96 = slot0[0]
            tick = slot0[1]
            
            # Get liquidity
            liquidity = pool_contract.functions.liquidity().call()
            
            # Get fee tier
            fee = pool_contract.functions.fee().call()
            fee_tier = fee // 100  # Convert from fee (e.g., 3000) to basis points (30)
            
            # Calculate current price from sqrtPriceX96
            # price = (sqrtPriceX96 / 2^96)^2
            # Adjust for token decimals
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
                reserves=(0, 0)  # V3 doesn't have simple reserves
            )
            
        except Exception as e:
            logger.error(f"Failed to fetch pool data for {pool_address}: {e}")
            raise

    def _compute_pool_address(self, token0: str, token1: str, fee: int) -> str:
        """Compute Uniswap V3 pool address from token pair and fee.
        
        This is a simplified version. In production, you would use the actual
        CREATE2 computation with the factory address and init code hash.
        
        Args:
            token0: Token0 address
            token1: Token1 address
            fee: Fee tier
            
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
        
        # Return a placeholder that can be used for testing
        return Web3.to_checksum_address(token0)  # Placeholder

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

