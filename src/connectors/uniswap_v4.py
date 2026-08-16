"""Uniswap V4 LP connector implementation.

V4 replaces V3's per-pool contracts with a singleton `PoolManager`; pool
state is read through the read-only `StateView` lens contract instead, and
positions are still minted as ERC-721s by a periphery `PositionManager` —
but that PositionManager does *not* implement ERC721Enumerable, so unlike
V3 there is no on-chain `tokenOfOwnerByIndex` to enumerate a wallet's
positions. Discovery instead uses `Transfer` event logs filtered to the
wallet (Etherscan V2 API where available, chunked RPC `get_logs` as a
bounded best-effort fallback), each candidate confirmed still-owned via
`ownerOf`. Any failure here — no RPC, no API key and an out-of-window RPC
scan, chain not supported — must surface as "no positions found", never a
guess.

Position tick bounds come from `PositionManager.getPoolAndPositionInfo`,
which returns a `PoolKey` (the five fields whose keccak256 encoding *is*
the pool's id, unlike V3 where the factory computes a real contract
address) plus a packed `PositionInfo` uint256. See `decode_position_info`
for the exact bit layout.

Contract addresses below were verified against Etherscan/Arbiscan/BaseScan
against Uniswap's own contract tags as of 2026-08; if a chain's on-chain
read starts failing entirely, that's the first thing to re-check.
"""

import logging
import os
from typing import Optional

from eth_abi import encode as abi_encode
from web3 import Web3

from src.connectors.base import LPConnector
from src.models import Chain, LPType, PoolData, Protocol, RawLPPosition

logger = logging.getLogger(__name__)

# Uniswap V4 PositionManager (periphery) — mints/holds the ERC-721 wrapping
# each position; NOT ERC721Enumerable.
POSITION_MANAGER_ADDRESSES = {
    Chain.ETHEREUM: "0xbD216513d74C8cf14cf4747E6AaA6420FF64ee9e",
    Chain.ARBITRUM: "0xd88F38F930b7952f2DB2432Cb002E7abbF3dD869",
    Chain.BASE: "0x7bfCd8722a746D92B3174b82Bd7f19aFe8ec7509",
}

# StateView — read-only lens over PoolManager's transient state, built for
# offchain callers (frontends/analytics), not used in any onchain tx path.
STATE_VIEW_ADDRESSES = {
    Chain.ETHEREUM: "0x7fFE42C4a5DEeA5b0feC41C94C136Cf115597227",
    Chain.ARBITRUM: "0x76Fd297e2D437cd7f76d50F01AfE6160f86e9990",
    Chain.BASE: "0xA3c0c9b65baD0b08107Aa264b0f3dB444b867A71",
}

POSITION_MANAGER_ABI = [
    {
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "getPoolAndPositionInfo",
        "outputs": [
            {
                "name": "poolKey",
                "type": "tuple",
                "components": [
                    {"name": "currency0", "type": "address"},
                    {"name": "currency1", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "tickSpacing", "type": "int24"},
                    {"name": "hooks", "type": "address"},
                ],
            },
            {"name": "info", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "ownerOf",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "getPositionLiquidity",
        "outputs": [{"name": "liquidity", "type": "uint128"}],
        "stateMutability": "view",
        "type": "function",
    },
]

STATE_VIEW_ABI = [
    {
        "inputs": [{"name": "poolId", "type": "bytes32"}],
        "name": "getSlot0",
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "protocolFee", "type": "uint24"},
            {"name": "lpFee", "type": "uint24"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

# Native-currency sentinel: V4 lets a pool hold raw ETH directly as
# currency0/currency1 (no WETH wrapping) — represented as the zero address.
NATIVE_CURRENCY = "0x0000000000000000000000000000000000000000"

TRANSFER_EVENT_SIGNATURE = Web3.keccak(text="Transfer(address,address,uint256)").hex()
if not TRANSFER_EVENT_SIGNATURE.startswith("0x"):
    TRANSFER_EVENT_SIGNATURE = "0x" + TRANSFER_EVENT_SIGNATURE


def decode_position_info(info: int) -> tuple[int, int]:
    """Decode (tickLower, tickUpper) from PositionManager's packed PositionInfo.

    Layout (least significant bit first), per PositionInfoLibrary:
      bits 0-7:    hasSubscriber (uint8)
      bits 8-31:   tickLower (int24)
      bits 32-55:  tickUpper (int24)
      bits 56-255: poolId, truncated to 200 bits (unused here — we derive
                   the full poolId from the PoolKey instead, see
                   compute_pool_id)
    """
    tick_lower_raw = (info >> 8) & 0xFFFFFF
    tick_upper_raw = (info >> 32) & 0xFFFFFF
    if tick_lower_raw >= 0x800000:
        tick_lower_raw -= 0x1000000
    if tick_upper_raw >= 0x800000:
        tick_upper_raw -= 0x1000000
    return tick_lower_raw, tick_upper_raw


def compute_pool_id(currency0: str, currency1: str, fee: int, tick_spacing: int, hooks: str) -> bytes:
    """Replicate PoolIdLibrary.toId(): keccak256 of the PoolKey's 5 fields,
    each padded to a 32-byte memory slot (i.e. `abi.encode`, not `encodePacked`).
    """
    encoded = abi_encode(
        ["address", "address", "uint24", "int24", "address"],
        [
            Web3.to_checksum_address(currency0),
            Web3.to_checksum_address(currency1),
            fee,
            tick_spacing,
            Web3.to_checksum_address(hooks),
        ],
    )
    return Web3.keccak(encoded)


class UniswapV4Connector(LPConnector):
    """Uniswap V4 concentrated liquidity LP connector (PositionManager + StateView)."""

    def __init__(self, rpc_url: Optional[str] = None, chain: Chain = Chain.ETHEREUM):
        self.chain = chain

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

        if chain not in POSITION_MANAGER_ADDRESSES:
            raise ValueError(f"Uniswap V4 not supported on {chain.value}")

        self.position_manager_address = POSITION_MANAGER_ADDRESSES[chain]
        self.position_manager = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.position_manager_address),
            abi=POSITION_MANAGER_ABI,
        )
        self.state_view_address = STATE_VIEW_ADDRESSES[chain]
        self.state_view = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.state_view_address),
            abi=STATE_VIEW_ABI,
        )

        logger.info(f"Connected to Uniswap V4 on {chain.value}")

    def get_positions(self, wallet: str, chain: str) -> list[RawLPPosition]:
        """Discover a wallet's V4 position NFTs.

        No ERC721Enumerable on the V4 PositionManager, so discovery scans
        `Transfer(..., to=wallet, tokenId)` logs (Etherscan V2 API when
        `ETHERSCAN_API_KEY` is set and the chain supports it; a bounded
        recent-block RPC scan otherwise — same tradeoff already accepted
        elsewhere in this codebase for RPC-only environments), then
        confirms current ownership per candidate via `ownerOf` since a
        historical "transferred in" doesn't mean still held (could have
        moved on or been burned since). Returns [] — never raises — on
        any chain/RPC limitation; the caller treats an empty list the same
        as "nothing found".
        """
        try:
            wallet_checksum = Web3.to_checksum_address(wallet)
        except Exception as e:
            logger.error(f"Invalid wallet address {wallet}: {e}")
            return []

        candidate_ids = self._discover_candidate_token_ids(wallet_checksum)
        if not candidate_ids:
            return []

        positions = []
        for token_id in candidate_ids:
            try:
                owner = self.position_manager.functions.ownerOf(token_id).call()
                if Web3.to_checksum_address(owner) != wallet_checksum:
                    continue
                positions.append(RawLPPosition(
                    token_id=token_id,
                    pool_address="",  # V4 has no per-pool address — see compute_pool_id
                    liquidity=0,  # not read here; range enrichment reads ticks directly
                    tick_lower=None,
                    tick_upper=None,
                    lp_type=LPType.V4,
                    protocol=Protocol.UNISWAP_V4,
                    chain=self.chain,
                    wallet=wallet_checksum,
                ))
            except Exception as e:
                logger.warning(f"Could not confirm ownership of V4 token {token_id}: {e}")
                continue

        return positions

    def _discover_candidate_token_ids(self, wallet_checksum: str) -> list[int]:
        try:
            chain_id = self.w3.eth.chain_id
        except Exception as e:
            logger.warning(f"V4 discovery: RPC unavailable: {e}")
            return []

        # Base: no free Etherscan API, Alchemy RPC rejects getLogs — same
        # limitation already documented for V3 fee/age history in web_portfolio.py.
        if chain_id == 8453:
            logger.info("V4 discovery skipped on Base (no reliable getLogs source)")
            return []

        api_key = os.getenv("ETHERSCAN_API_KEY")
        if api_key and chain_id in (1, 42161):
            ids = self._discover_via_etherscan(chain_id, api_key, wallet_checksum)
            if ids is not None:
                return ids
            logger.info("V4 discovery: Etherscan API failed, falling back to RPC")

        return self._discover_via_rpc(wallet_checksum)

    def _discover_via_etherscan(self, chain_id: int, api_key: str, wallet_checksum: str) -> Optional[list[int]]:
        """Full-history discovery via Etherscan V2 getLogs (single call, server-paginated
        range — no chunking needed unlike raw RPC). Returns None on failure so the
        caller falls back to RPC; returns [] (not None) for a clean "no results"."""
        import requests

        try:
            wallet_topic = "0x" + wallet_checksum[2:].lower().zfill(64)
            params = {
                "chainid": chain_id,
                "module": "logs",
                "action": "getLogs",
                "address": self.position_manager_address,
                "topic0": TRANSFER_EVENT_SIGNATURE,
                "topic2": wallet_topic,
                "topic0_2_opr": "and",
                "startblock": 1,
                "endblock": 99999999999,
                "sort": "asc",
                "apikey": api_key,
            }
            response = requests.get("https://api.etherscan.io/v2/api", params=params, timeout=30)
            if response.status_code != 200:
                logger.warning(f"V4 discovery: Etherscan HTTP {response.status_code}")
                return None
            data = response.json()
            if data.get("status") != "1":
                msg = data.get("message", "")
                if "No records found" in msg or "No records found" in str(data.get("result", "")):
                    return []
                logger.warning(f"V4 discovery: Etherscan API error: {msg}")
                return None
            token_ids = []
            for log in data["result"]:
                topics = log.get("topics", [])
                if len(topics) >= 4:
                    token_ids.append(int(topics[3], 16))
            # Dedupe, preserve discovery order
            seen = set()
            unique = []
            for tid in token_ids:
                if tid not in seen:
                    seen.add(tid)
                    unique.append(tid)
            return unique
        except Exception as e:
            logger.warning(f"V4 discovery via Etherscan failed: {e}")
            return None

    def _discover_via_rpc(self, wallet_checksum: str) -> list[int]:
        """Bounded recent-block RPC fallback — same lookback/chunk-size convention as
        get_position_creation_time()'s RPC fallback in web_portfolio.py. Best-effort
        only: without an Etherscan key this can miss positions transferred in outside
        the lookback window, which is an accepted, pre-existing tradeoff in this
        codebase for RPC-only environments — never fabricated, just possibly
        incomplete."""
        try:
            current_block = self.w3.eth.block_number
            chain_id = self.w3.eth.chain_id
        except Exception as e:
            logger.warning(f"V4 RPC discovery: could not read chain state: {e}")
            return []

        if chain_id == 42161:  # Arbitrum
            lookback, chunk_size = 700_000, 5_000
        else:  # Ethereum (Base already excluded by the caller)
            lookback, chunk_size = 50_000, 50_000

        scan_from = max(1, current_block - lookback)
        wallet_topic = "0x" + wallet_checksum[2:].lower().zfill(64)
        token_ids: list[int] = []

        while scan_from <= current_block:
            scan_to = min(scan_from + chunk_size - 1, current_block)
            try:
                logs = self.w3.eth.get_logs({
                    "fromBlock": scan_from,
                    "toBlock": scan_to,
                    "address": Web3.to_checksum_address(self.position_manager_address),
                    "topics": [TRANSFER_EVENT_SIGNATURE, None, wallet_topic],
                })
                for log in logs:
                    topics = log["topics"]
                    if len(topics) >= 4:
                        raw = topics[3]
                        token_ids.append(int(raw.hex(), 16) if isinstance(raw, (bytes, bytearray)) else int(raw, 16))
            except Exception as e:
                if chunk_size > 500:
                    chunk_size = chunk_size // 2
                    continue
                logger.warning(f"V4 RPC discovery: log scan failed for blocks {scan_from}-{scan_to}: {e}")
            scan_from = scan_to + 1

        seen = set()
        unique = []
        for tid in token_ids:
            if tid not in seen:
                seen.add(tid)
                unique.append(tid)
        return unique

    def get_pool_data(self, pool_address: str) -> PoolData:
        """V4 has no per-pool contract address (singleton PoolManager) — pool state
        is read via StateView.getSlot0(poolId) in web_portfolio.check_uniswap_v4_lp_position
        instead. Not used by the enrichment path (mirrors UniswapV3Connector.get_pool_data,
        which is likewise unused there)."""
        raise NotImplementedError(
            "Uniswap V4 has no per-pool address; use StateView.getSlot0(poolId) instead"
        )
