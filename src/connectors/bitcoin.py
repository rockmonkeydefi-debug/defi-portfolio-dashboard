"""Bitcoin connector — derives addresses from xpub/ypub/zpub and fetches balances via Blockstream API."""

import requests
import time
import base58

GAP_LIMIT = 20
API_BASE = "https://blockstream.info/api"

# Version bytes for extended public keys
VERSION_BYTES = {
    "xpub": bytes.fromhex("0488b21e"),
    "ypub": bytes.fromhex("049d7cb2"),
    "zpub": bytes.fromhex("04b24746"),
}


def _to_xpub(key_str: str) -> str:
    """Convert ypub/zpub to xpub format by swapping version bytes."""
    if key_str.startswith("xpub"):
        return key_str
    raw = base58.b58decode_check(key_str)
    xpub_raw = VERSION_BYTES["xpub"] + raw[4:]
    return base58.b58encode_check(xpub_raw).decode()


def get_btc_balance_for_xpub(xpub_str: str) -> dict:
    """Get total BTC balance for an xpub/ypub/zpub by scanning derived addresses.
    
    Returns:
        {"total_btc": float, "addresses_used": int, "address_balances": [...]}
    """
    from hdwallet import HDWallet
    from hdwallet.cryptocurrencies import Bitcoin
    from hdwallet.hds import BIP32HD
    from hdwallet.derivations import CustomDerivation
    from hdwallet.addresses import P2WPKHAddress, P2WPKHInP2SHAddress, P2PKHAddress
    
    # Pick address type based on original key prefix
    # Note: Ledger exports xpub even for BIP84 (native segwit) accounts
    # Default xpub to native segwit since most modern wallets use BIP84
    if xpub_str.startswith("zpub") or xpub_str.startswith("xpub"):
        addr_cls = P2WPKHAddress         # native segwit bc1q...
    elif xpub_str.startswith("ypub"):
        addr_cls = P2WPKHInP2SHAddress   # wrapped segwit 3...
    else:
        addr_cls = P2PKHAddress          # legacy 1...
    
    # Convert to xpub format for hdwallet compatibility
    xpub_normalized = _to_xpub(xpub_str)
    
    total_sats = 0
    addresses_used = 0
    address_balances = []
    
    for chain_name, chain_idx in [("external", 0), ("change", 1)]:
        gap = 0
        i = 0
        
        while gap < GAP_LIMIT:
            hdw = HDWallet(cryptocurrency=Bitcoin, hd=BIP32HD, address=addr_cls)
            hdw.from_xpublic_key(xpublic_key=xpub_normalized, strict=False)
            hdw.from_derivation(derivation=CustomDerivation(path=f"m/{chain_idx}/{i}"))
            addr = hdw.address()
            
            try:
                balance_sats, has_history = _get_address_info(addr)
                time.sleep(0.3)
            except Exception as e:
                # Retry once after backoff
                time.sleep(2)
                try:
                    balance_sats, has_history = _get_address_info(addr)
                    time.sleep(0.3)
                except Exception:
                    gap += 1
                    i += 1
                    continue
            
            if balance_sats > 0:
                total_sats += balance_sats
                addresses_used += 1
                address_balances.append({
                    "address": addr,
                    "balance_btc": balance_sats / 1e8,
                    "chain": chain_name
                })
                gap = 0
            elif has_history:
                addresses_used += 1
                gap = 0
            else:
                gap += 1
            
            i += 1
        
        print(f"  BTC {chain_name}: scanned {i} addresses, gap reached")
    
    return {
        "total_btc": total_sats / 1e8,
        "addresses_used": addresses_used,
        "address_balances": address_balances
    }


def _get_address_info(address: str) -> tuple:
    """Get (balance_sats, has_history) for a Bitcoin address."""
    try:
        resp = requests.get(f"{API_BASE}/address/{address}", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        stats = data.get("chain_stats", {})
        funded = stats.get("funded_txo_sum", 0)
        spent = stats.get("spent_txo_sum", 0)
        tx_count = stats.get("tx_count", 0)
        return funded - spent, tx_count > 0
    except requests.exceptions.RequestException as e:
        print(f"BTC address lookup failed for {address[:12]}...: {e}")
        raise
