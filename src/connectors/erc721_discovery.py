"""Shared ERC-721 tokenId discovery via Transfer logs (Etherscan V2 unified API).

Both LP connectors need to find position-NFT tokenIds that `balanceOf` /
`tokenOfOwnerByIndex` can't enumerate:

* Uniswap V4's PositionManager isn't ERC721Enumerable at all, so log scanning
  is the only discovery path.
* Uniswap V3's is, but enumeration only sees NFTs the wallet *currently holds* —
  a position custodied by a manager/staking contract is invisible to it even
  though the wallet still owns it economically (and Zerion still reports it).

Etherscan's V2 unified API covers every chain this app supports (Ethereum,
Arbitrum, Base) behind one key and a `chainid` parameter, and returns full
history in a single request — unlike a chunked RPC `getLogs` scan, which only
ever sees a recent window and would silently miss older positions.
"""

import logging
import os
from typing import Optional

from web3 import Web3

logger = logging.getLogger(__name__)

ETHERSCAN_V2_URL = "https://api.etherscan.io/v2/api"

# Chains reachable through the Etherscan V2 unified API (single key + chainid).
ETHERSCAN_V2_CHAIN_IDS = {1, 42161, 8453}

TRANSFER_EVENT_SIGNATURE = Web3.keccak(text="Transfer(address,address,uint256)").hex()
if not TRANSFER_EVENT_SIGNATURE.startswith("0x"):
    TRANSFER_EVENT_SIGNATURE = "0x" + TRANSFER_EVENT_SIGNATURE


def _address_topic(address: str) -> str:
    return "0x" + address[2:].lower().zfill(64)


def discover_incoming_token_ids(
    chain_id: int,
    contract_address: str,
    wallet: str,
    api_key: Optional[str] = None,
) -> Optional[list[int]]:
    """Return tokenIds of `contract_address` ever transferred **to** `wallet`.

    Ordered oldest-first, deduped. Returns:
      * ``list[int]`` (possibly empty) on a successful query,
      * ``None`` when discovery could not run or failed — callers must treat
        this as "unknown", never as "none exist".

    Being transferred in does not mean still held: callers that care about
    current ownership must check it themselves.
    """
    import requests

    api_key = api_key if api_key is not None else os.getenv("ETHERSCAN_API_KEY")
    if not api_key:
        return None
    if chain_id not in ETHERSCAN_V2_CHAIN_IDS:
        return None

    try:
        wallet_checksum = Web3.to_checksum_address(wallet)
    except Exception as e:
        logger.warning(f"ERC-721 discovery: invalid wallet {wallet}: {e}")
        return None

    try:
        params = {
            "chainid": chain_id,
            "module": "logs",
            "action": "getLogs",
            "address": contract_address,
            "topic0": TRANSFER_EVENT_SIGNATURE,
            "topic2": _address_topic(wallet_checksum),
            "topic0_2_opr": "and",
            "startblock": 1,
            "endblock": 99999999999,
            "sort": "asc",
            "apikey": api_key,
        }
        response = requests.get(ETHERSCAN_V2_URL, params=params, timeout=30)
        if response.status_code != 200:
            logger.warning(f"ERC-721 discovery: Etherscan HTTP {response.status_code}")
            return None

        data = response.json()
        if data.get("status") != "1":
            msg = data.get("message", "")
            if "No records found" in msg or "No records found" in str(data.get("result", "")):
                return []
            logger.warning(f"ERC-721 discovery: Etherscan API error: {msg}")
            return None

        token_ids: list[int] = []
        seen = set()
        for log in data.get("result", []):
            topics = log.get("topics", [])
            if len(topics) < 4:
                continue  # not an ERC-721 Transfer (ERC-20 has 3 topics)
            tid = int(topics[3], 16)
            if tid not in seen:
                seen.add(tid)
                token_ids.append(tid)
        return token_ids

    except Exception as e:
        logger.warning(f"ERC-721 discovery failed: {e}")
        return None
