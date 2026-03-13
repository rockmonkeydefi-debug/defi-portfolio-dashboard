"""Flask web app for DeFi Portfolio Visualization."""

import sys
import os
import math
import requests
import warnings
import re
import json
from datetime import datetime
from dotenv import load_dotenv, set_key, find_dotenv
from web3 import Web3
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import bcrypt
from functools import wraps

# Suppress urllib3 SSL warning
warnings.filterwarnings('ignore', message='.*OpenSSL.*')

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.connectors.uniswap_v3 import UniswapV3Connector, POOL_ABI, ERC20_ABI
from src.models import Chain

# Auto-create config files from examples on first run
if not os.path.exists(".env") and os.path.exists(".env.example"):
    import shutil
    shutil.copy(".env.example", ".env")
    print("Created .env from .env.example — edit it with your API keys")

if not os.path.exists("wallet_config.json"):
    with open("wallet_config.json", "w") as f:
        f.write("{}")

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(32).hex())

# --- Authentication ---
# Rate limiting for login
_login_attempts = {}  # ip -> (count, first_attempt_time)
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300  # 5 minutes


def get_password_hash():
    """Get the stored bcrypt password hash from .env."""
    return os.getenv("APP_PASSWORD_HASH", "")


def check_rate_limit(ip):
    """Check if IP has exceeded login attempt limit."""
    now = datetime.now().timestamp()
    if ip in _login_attempts:
        count, first_time = _login_attempts[ip]
        if now - first_time > LOGIN_WINDOW_SECONDS:
            _login_attempts[ip] = (1, now)
            return True
        if count >= MAX_LOGIN_ATTEMPTS:
            return False
        _login_attempts[ip] = (count + 1, first_time)
        return True
    _login_attempts[ip] = (1, now)
    return True


def login_required(f):
    """Decorator to require authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        pw_hash = get_password_hash()
        # If no password is set, skip auth (local dev convenience)
        if not pw_hash:
            return f(*args, **kwargs)
        if not session.get('authenticated'):
            # For API calls, return 401; for pages, redirect to login
            if request.path.startswith('/api/'):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated


@app.before_request
def require_auth():
    """Global auth check — all routes except login/logout/static."""
    # Skip auth for login, logout, and static files
    if request.path in ('/login', '/logout') or request.path.startswith('/static/'):
        return
    pw_hash = get_password_hash()
    if not pw_hash:
        # No password set — redirect to setup (which is the login page)
        if request.path != '/login':
            return redirect(url_for('login_page'))
        return
    if not session.get('authenticated'):
        if request.path.startswith('/api/'):
            return jsonify({"error": "Authentication required"}), 401
        return redirect(url_for('login_page'))

# Configuration
ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY")
WALLET_CONFIG_FILE = "wallet_config.json"

# Cache for portfolio data
_portfolio_cache = None

def load_wallet_config():
    """Load wallet configuration from JSON file."""
    if os.path.exists(WALLET_CONFIG_FILE):
        try:
            with open(WALLET_CONFIG_FILE, 'r') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}

def save_wallet_config(config):
    """Save wallet configuration to JSON file."""
    with open(WALLET_CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def get_wallet_addresses():
    """Get wallet addresses from config file."""
    config = load_wallet_config()
    return list(config.keys())

def get_wallet_label(address):
    """Get label for a wallet address."""
    config = load_wallet_config()
    return config.get(address, {}).get('label', address[:10] + '...')

def save_wallet_addresses(addresses):
    """Save wallet addresses to .env file (for backward compatibility)."""
    env_file = find_dotenv()
    if not env_file:
        env_file = ".env"
    
    wallet_str = ",".join(addresses)
    set_key(env_file, "WALLET_ADDRESS", wallet_str)
    
    # Reload environment variables
    load_dotenv(override=True)

def is_valid_address(address):
    """Validate Ethereum address format."""
    if not address:
        return False
    if not address.startswith("0x"):
        return False
    if len(address) != 42:
        return False
    try:
        int(address[2:], 16)
        return True
    except ValueError:
        return False

FACTORY_ADDRESSES = {
    Chain.ETHEREUM: "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    Chain.ARBITRUM: "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    Chain.BASE: "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
}

FACTORY_ABI = [
    {
        "inputs": [
            {"name": "tokenA", "type": "address"},
            {"name": "tokenB", "type": "address"},
            {"name": "fee", "type": "uint24"}
        ],
        "name": "getPool",
        "outputs": [{"name": "pool", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    }
]

_price_cache = {}


def get_token_price_usd(symbol: str, address: str = None, chain: str = "ethereum") -> float:
    """Get token price in USD using DeFiLlama API."""
    cache_key = f"{chain}:{address}" if address else symbol
    
    if cache_key in _price_cache:
        return _price_cache[cache_key]
    
    try:
        if symbol == "ETH" and not address:
            address = "0x0000000000000000000000000000000000000000"
        
        # Bitcoin — use CoinGecko ID via DeFiLlama
        if symbol == "BTC" and chain == "bitcoin":
            try:
                url = "https://coins.llama.fi/prices/current/coingecko:bitcoin"
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    price = response.json().get("coins", {}).get("coingecko:bitcoin", {}).get("price", 0.0)
                    if price > 0:
                        _price_cache[cache_key] = price
                        return price
            except Exception:
                pass
        
        if address:
            try:
                url = f"https://coins.llama.fi/prices/current/{chain}:{address}"
                response = requests.get(url, timeout=5)
                
                if response.status_code == 200:
                    data = response.json()
                    price = data.get("coins", {}).get(f"{chain}:{address}", {}).get("price", 0.0)
                    if price > 0:
                        _price_cache[cache_key] = price
                        return price
            except Exception:
                pass
        
        _price_cache[cache_key] = 0.0
        return 0.0
        
    except Exception:
        _price_cache[cache_key] = 0.0
        return 0.0


def get_token_balances_alchemy(rpc_url: str, wallet: str, chain_name: str) -> list:
    """Get all ERC-20 token balances using Alchemy's native API."""
    payload = {
        "id": 1,
        "jsonrpc": "2.0",
        "method": "alchemy_getTokenBalances",
        "params": [wallet, "erc20"]
    }
    
    response = requests.post(rpc_url, json=payload)
    
    if response.status_code != 200:
        return []
    
    result = response.json()
    
    if "error" in result:
        return []
    
    token_balances = result.get("result", {}).get("tokenBalances", [])
    tokens_with_balance = []
    
    for token in token_balances:
        balance_hex = token.get("tokenBalance", "0x0")
        balance = int(balance_hex, 16)
        
        if balance > 0:
            token_address = token.get("contractAddress")
            
            metadata_payload = {
                "id": 1,
                "jsonrpc": "2.0",
                "method": "alchemy_getTokenMetadata",
                "params": [token_address]
            }
            
            metadata_response = requests.post(rpc_url, json=metadata_payload)
            
            if metadata_response.status_code == 200:
                metadata_result = metadata_response.json()
                metadata = metadata_result.get("result", {})
                
                symbol = metadata.get("symbol", "UNKNOWN")
                decimals = metadata.get("decimals")
                
                if decimals is None:
                    continue
                
                scam_patterns = [
                    "t.me/", "telegram", "@", "visit", "claim", "tge soon",
                    "www.", ".com", ".io", "airdrop", "bonus", "reward"
                ]
                symbol_lower = symbol.lower()
                if any(pattern in symbol_lower for pattern in scam_patterns):
                    continue
                
                human_balance = balance / (10 ** decimals)
                price_usd = get_token_price_usd(symbol, token_address, chain_name)
                value_usd = human_balance * price_usd
                
                if value_usd < 0.01 and human_balance < 100:
                    continue
                
                tokens_with_balance.append({
                    "address": token_address,
                    "symbol": symbol,
                    "decimals": decimals,
                    "balance": human_balance,
                    "price_usd": price_usd,
                    "value_usd": value_usd
                })
    
    return tokens_with_balance


def calculate_token_amounts(liquidity: int, tick_lower: int, tick_upper: int, current_tick: int,
                           sqrt_price_x96: int, token0_decimals: int, token1_decimals: int):
    """Calculate the actual token amounts from liquidity."""
    try:
        sqrt_price_lower = math.sqrt(1.0001 ** tick_lower)
        sqrt_price_upper = math.sqrt(1.0001 ** tick_upper)
        sqrt_price_current = sqrt_price_x96 / (2 ** 96)
        
        if current_tick < tick_lower:
            amount0 = liquidity * (1/sqrt_price_lower - 1/sqrt_price_upper)
            amount1 = 0
        elif current_tick >= tick_upper:
            amount0 = 0
            amount1 = liquidity * (sqrt_price_upper - sqrt_price_lower)
        else:
            amount0 = liquidity * (1/sqrt_price_current - 1/sqrt_price_upper)
            amount1 = liquidity * (sqrt_price_current - sqrt_price_lower)
        
        amount0_adjusted = amount0 / (10 ** token0_decimals)
        amount1_adjusted = amount1 / (10 ** token1_decimals)
        
        return amount0_adjusted, amount1_adjusted
    except Exception:
        return 0, 0


def subIn256(x: int, y: int) -> int:
    """Handle underflow for 256-bit subtraction (wraps around)."""
    Q256 = 2 ** 256
    difference = x - y
    if difference < 0:
        return Q256 + difference
    return difference


def calculate_uncollected_fees(
    liquidity: int,
    tick_lower: int,
    tick_upper: int,
    tick_current: int,
    fee_growth_global_0: int,
    fee_growth_global_1: int,
    fee_growth_outside_lower_0: int,
    fee_growth_outside_lower_1: int,
    fee_growth_outside_upper_0: int,
    fee_growth_outside_upper_1: int,
    fee_growth_inside_last_0: int,
    fee_growth_inside_last_1: int
) -> tuple[int, int]:
    """Calculate uncollected fees for a Uniswap V3 position."""
    # Calculate fee growth below lower tick
    if tick_current >= tick_lower:
        fee_growth_below_0 = fee_growth_outside_lower_0
        fee_growth_below_1 = fee_growth_outside_lower_1
    else:
        fee_growth_below_0 = subIn256(fee_growth_global_0, fee_growth_outside_lower_0)
        fee_growth_below_1 = subIn256(fee_growth_global_1, fee_growth_outside_lower_1)
    
    # Calculate fee growth above upper tick
    if tick_current >= tick_upper:
        fee_growth_above_0 = subIn256(fee_growth_global_0, fee_growth_outside_upper_0)
        fee_growth_above_1 = subIn256(fee_growth_global_1, fee_growth_outside_upper_1)
    else:
        fee_growth_above_0 = fee_growth_outside_upper_0
        fee_growth_above_1 = fee_growth_outside_upper_1
    
    # Calculate fee growth inside the position range
    fee_growth_inside_0 = subIn256(
        subIn256(fee_growth_global_0, fee_growth_below_0),
        fee_growth_above_0
    )
    fee_growth_inside_1 = subIn256(
        subIn256(fee_growth_global_1, fee_growth_below_1),
        fee_growth_above_1
    )
    
    # Calculate uncollected fees
    Q128 = 2 ** 128
    uncollected_fees_0 = (liquidity * subIn256(fee_growth_inside_0, fee_growth_inside_last_0)) // Q128
    uncollected_fees_1 = (liquidity * subIn256(fee_growth_inside_1, fee_growth_inside_last_1)) // Q128
    
    return uncollected_fees_0, uncollected_fees_1


def get_position_creation_time(
    w3: Web3,
    position_manager_address: str,
    token_id: int,
    pool_address: str = None,
    tick_lower: int = None,
    tick_upper: int = None,
    from_block: int = 0
) -> int:
    """Get position creation timestamp using Etherscan V2 API or RPC fallback."""
    try:
        chain_id = w3.eth.chain_id
        api_key = os.getenv("ETHERSCAN_API_KEY")

        api_url = "https://api.etherscan.io/v2/api"
        
        # Base chain: no free Etherscan API, Alchemy RPC rejects getLogs
        if chain_id == 8453:
            return None

        # Try Etherscan V2 API first (Ethereum, Arbitrum)
        if api_key and chain_id in [1, 42161]:
            try:
                print(f"Using Etherscan V2 API (chain {chain_id}) for position {token_id} creation time")

                # Use getLogs to find the Transfer(address(0), to, tokenId) mint event
                transfer_topic = Web3.keccak(text="Transfer(address,address,uint256)").hex()
                if not transfer_topic.startswith('0x'):
                    transfer_topic = '0x' + transfer_topic
                # from = zero address (mint)
                zero_topic = '0x' + '0' * 64
                token_id_topic = '0x' + hex(token_id)[2:].zfill(64)

                params = {
                    "chainid": chain_id,
                    "module": "logs",
                    "action": "getLogs",
                    "address": position_manager_address,
                    "topic0": transfer_topic,
                    "topic1": zero_topic,
                    "topic3": token_id_topic,
                    "topic0_1_opr": "and",
                    "topic1_3_opr": "and",
                    "startblock": 1,
                    "endblock": 99999999999,
                    "sort": "asc",
                    "apikey": api_key
                }

                response = requests.get(api_url, params=params, timeout=30)

                if response.status_code == 200:
                    data = response.json()

                    if data.get("status") == "1" and data.get("result"):
                        log = data["result"][0]
                        timestamp = int(log["timeStamp"], 16) if log["timeStamp"].startswith("0x") else int(log["timeStamp"])
                        block_number = int(log["blockNumber"], 16) if log["blockNumber"].startswith("0x") else int(log["blockNumber"])
                        print(f"Position {token_id} minted at block {block_number}, timestamp {timestamp}")
                        return timestamp
                    else:
                        msg = data.get("message", "")
                        if "No records found" in msg or "No records found" in str(data.get("result", "")):
                            print(f"No mint event found for token {token_id}")
                        else:
                            print(f"Etherscan API: {msg} | {data.get('result', '')}")
            except Exception as e:
                print(f"Etherscan V2 API failed for token {token_id}: {e}")
                print("Falling back to RPC method...")

        # Fallback: RPC with chunked scanning
        current_block = w3.eth.block_number

        # Chain-aware lookback and chunk sizes
        if chain_id == 42161:  # Arbitrum
            lookback = 700_000  # ~2 days
            chunk_size = 5_000
        elif chain_id == 8453:  # Base
            lookback = 130_000  # ~3 days
            chunk_size = 2_000
        else:  # Ethereum
            lookback = 50_000  # ~7 days
            chunk_size = 50_000

        scan_from = max(1, current_block - lookback)

        print(f"Using RPC to search for position {token_id} creation from block {scan_from} to {current_block}")

        transfer_event_sig = w3.keccak(text="Transfer(address,address,uint256)").hex()
        token_id_topic = '0x' + hex(token_id)[2:].zfill(64)

        earliest_block = None

        while scan_from <= current_block:
            scan_to = min(scan_from + chunk_size - 1, current_block)

            try:
                logs = w3.eth.get_logs({
                    'fromBlock': scan_from,
                    'toBlock': scan_to,
                    'address': Web3.to_checksum_address(position_manager_address),
                    'topics': [
                        transfer_event_sig,
                        None,  # from
                        None,  # to
                        token_id_topic
                    ]
                })

                if logs:
                    block_num = min(log['blockNumber'] for log in logs)
                    if earliest_block is None or block_num < earliest_block:
                        earliest_block = block_num
                    break  # Found it, no need to scan further

            except Exception as e:
                if chunk_size > 500:
                    chunk_size = chunk_size // 2
                    continue
                else:
                    print(f"RPC scan failed for blocks {scan_from}-{scan_to}: {e}")
                    scan_from = scan_to + 1
                    continue

            scan_from = scan_to + 1

        if earliest_block:
            block = w3.eth.get_block(earliest_block)
            print(f"Position {token_id} minted at block {earliest_block}, timestamp {block['timestamp']}")
            return block['timestamp']

        print(f"Could not find creation event for position {token_id}")
        return 0

    except Exception as e:
        print(f"Error fetching position creation time for token {token_id}: {e}")
        return 0


def get_collected_fees_from_events(
    w3: Web3,
    position_manager_address: str,
    token_id: int,
    token0_decimals: int,
    token1_decimals: int
) -> tuple[float, float]:
    """Query NonfungiblePositionManager Collect events for a specific tokenId."""
    try:
        chain_id = w3.eth.chain_id
        api_key = os.getenv("ETHERSCAN_API_KEY")

        # Base chain: no free API support, Alchemy RPC rejects getLogs — skip entirely
        if chain_id == 8453:
            return 0.0, 0.0

        # Use Etherscan V2 API for supported chains
        if api_key and chain_id in [1, 42161]:  # Ethereum, Arbitrum
            result = _get_collected_fees_etherscan(
                chain_id, api_key, position_manager_address, token_id,
                token0_decimals, token1_decimals
            )
            if result is not None:
                return result
            print("Etherscan API failed, falling back to RPC...")

        # Fallback: RPC log scanning
        return _get_collected_fees_rpc(
            w3, position_manager_address, token_id,
            token0_decimals, token1_decimals
        )

    except Exception as e:
        print(f"Warning: Could not fetch collected fees from events: {e}")
        return 0.0, 0.0


def _get_collected_fees_etherscan(
    chain_id: int,
    api_key: str,
    position_manager_address: str,
    token_id: int,
    token0_decimals: int,
    token1_decimals: int
) -> tuple[float, float] | None:
    """Fetch collected fees using Etherscan V2 API getLogs on NonfungiblePositionManager.

    NonfungiblePositionManager Collect event:
      Collect(uint256 indexed tokenId, address recipient, uint256 amount0Collect, uint256 amount1Collect)
    Topics: [event_sig, tokenId]
    Data: [recipient, amount0Collect, amount1Collect]
    """
    try:
        api_url = "https://api.etherscan.io/v2/api"
        collect_topic = Web3.keccak(text="Collect(uint256,address,uint256,uint256)").hex()
        if not collect_topic.startswith('0x'):
            collect_topic = '0x' + collect_topic
        token_id_topic = '0x' + hex(token_id)[2:].zfill(64)

        params = {
            "chainid": chain_id,
            "module": "logs",
            "action": "getLogs",
            "address": position_manager_address,
            "topic0": collect_topic,
            "topic1": token_id_topic,
            "topic0_1_opr": "and",
            "startblock": 1,
            "endblock": 99999999999,
            "sort": "asc",
            "apikey": api_key
        }

        response = requests.get(api_url, params=params, timeout=30)

        if response.status_code != 200:
            print(f"Etherscan API HTTP error: {response.status_code}")
            return None

        data = response.json()

        if data.get("status") != "1":
            msg = data.get("message", "")
            result_str = data.get("result", "")
            if "No records found" in msg or "No records found" in str(result_str):
                return 0.0, 0.0
            print(f"Etherscan API error: {msg} | result: {result_str}")
            return None

        total_collected_0 = 0
        total_collected_1 = 0

        for log in data["result"]:
            # Data layout: recipient (32 bytes) + amount0Collect (32 bytes) + amount1Collect (32 bytes)
            log_data = log["data"]
            if log_data.startswith("0x"):
                log_data = log_data[2:]

            # Skip recipient (first 64 hex chars = 32 bytes)
            amount0 = int(log_data[64:128], 16)
            amount1 = int(log_data[128:192], 16)

            total_collected_0 += amount0
            total_collected_1 += amount1

        collected_0 = total_collected_0 / (10 ** token0_decimals)
        collected_1 = total_collected_1 / (10 ** token1_decimals)

        print(f"Etherscan: found {len(data['result'])} Collect events for token {token_id}, fees {collected_0:.6f} token0, {collected_1:.6f} token1")
        return collected_0, collected_1

    except Exception as e:
        print(f"Etherscan collected fees lookup failed: {e}")
        return None


def _get_collected_fees_rpc(
    w3: Web3,
    position_manager_address: str,
    token_id: int,
    token0_decimals: int,
    token1_decimals: int
) -> tuple[float, float]:
    """Fallback: fetch collected fees via RPC getLogs on NonfungiblePositionManager.

    NonfungiblePositionManager Collect event:
      Collect(uint256 indexed tokenId, address recipient, uint256 amount0Collect, uint256 amount1Collect)
    Topics: [event_sig, tokenId]
    Data: [recipient, amount0Collect, amount1Collect]
    """
    try:
        collect_event_signature = w3.keccak(text="Collect(uint256,address,uint256,uint256)").hex()
        token_id_topic = '0x' + hex(token_id)[2:].zfill(64)
        current_block = w3.eth.block_number
        chain_id = w3.eth.chain_id

        # Conservative RPC lookback
        if chain_id == 42161:  # Arbitrum
            default_lookback = 700_000
            chunk_size = 5_000
        elif chain_id == 8453:  # Base
            default_lookback = 130_000
            chunk_size = 2_000
        else:  # Ethereum
            default_lookback = 50_000
            chunk_size = 50_000

        from_block = max(1, current_block - default_lookback)

        total_collected_0 = 0
        total_collected_1 = 0

        scan_from = from_block
        while scan_from <= current_block:
            scan_to = min(scan_from + chunk_size - 1, current_block)

            try:
                logs = w3.eth.get_logs({
                    'fromBlock': scan_from,
                    'toBlock': scan_to,
                    'address': Web3.to_checksum_address(position_manager_address),
                    'topics': [
                        collect_event_signature,
                        token_id_topic
                    ]
                })
            except Exception as chunk_err:
                if chunk_size > 500:
                    chunk_size = chunk_size // 2
                    continue
                else:
                    print(f"Warning: Could not fetch logs for blocks {scan_from}-{scan_to}: {chunk_err}")
                    scan_from = scan_to + 1
                    continue

            for log in logs:
                # Data: recipient (32 bytes) + amount0Collect (32 bytes) + amount1Collect (32 bytes)
                data = log['data'].hex() if isinstance(log['data'], bytes) else log['data']
                if data.startswith('0x'):
                    data = data[2:]

                # Skip recipient (first 64 hex chars)
                amount0 = int(data[64:128], 16)
                amount1 = int(data[128:192], 16)

                total_collected_0 += amount0
                total_collected_1 += amount1

            scan_from = scan_to + 1

        collected_0 = total_collected_0 / (10 ** token0_decimals)
        collected_1 = total_collected_1 / (10 ** token1_decimals)

        return collected_0, collected_1

    except Exception as e:
        print(f"Warning: RPC collected fees scan failed: {e}")
        return 0.0, 0.0


def check_lp_position(connector: UniswapV3Connector, token_id: int, chain: Chain) -> dict:
    """Check a single LP position and return data."""
    try:
        position_data = connector.position_manager.functions.positions(token_id).call()
        
        token0 = position_data[2]
        token1 = position_data[3]
        fee = position_data[4]
        tick_lower = position_data[5]
        tick_upper = position_data[6]
        liquidity = position_data[7]
        fee_growth_inside0_last = position_data[8]
        fee_growth_inside1_last = position_data[9]
        tokens_owed0 = position_data[10]
        tokens_owed1 = position_data[11]
        
        if liquidity == 0:
            return None
        
        token0_contract = connector.w3.eth.contract(
            address=Web3.to_checksum_address(token0),
            abi=ERC20_ABI
        )
        token1_contract = connector.w3.eth.contract(
            address=Web3.to_checksum_address(token1),
            abi=ERC20_ABI
        )
        
        token0_symbol = token0_contract.functions.symbol().call()
        token1_symbol = token1_contract.functions.symbol().call()
        token0_decimals = token0_contract.functions.decimals().call()
        token1_decimals = token1_contract.functions.decimals().call()
        
        factory_address = FACTORY_ADDRESSES[chain]
        factory = connector.w3.eth.contract(
            address=Web3.to_checksum_address(factory_address),
            abi=FACTORY_ABI
        )
        pool_address = factory.functions.getPool(token0, token1, fee).call()
        
        pool_contract = connector.w3.eth.contract(
            address=Web3.to_checksum_address(pool_address),
            abi=POOL_ABI
        )
        
        slot0 = pool_contract.functions.slot0().call()
        sqrt_price_x96 = slot0[0]
        current_tick = slot0[1]
        
        # Get global fee growth and tick data
        fee_growth_global_0 = pool_contract.functions.feeGrowthGlobal0X128().call()
        fee_growth_global_1 = pool_contract.functions.feeGrowthGlobal1X128().call()
        
        tick_lower_data = pool_contract.functions.ticks(tick_lower).call()
        tick_upper_data = pool_contract.functions.ticks(tick_upper).call()
        
        fee_growth_outside_lower_0 = tick_lower_data[2]
        fee_growth_outside_lower_1 = tick_lower_data[3]
        fee_growth_outside_upper_0 = tick_upper_data[2]
        fee_growth_outside_upper_1 = tick_upper_data[3]
        
        # Calculate uncollected fees
        uncollected_fees_0, uncollected_fees_1 = calculate_uncollected_fees(
            liquidity,
            tick_lower,
            tick_upper,
            current_tick,
            fee_growth_global_0,
            fee_growth_global_1,
            fee_growth_outside_lower_0,
            fee_growth_outside_lower_1,
            fee_growth_outside_upper_0,
            fee_growth_outside_upper_1,
            fee_growth_inside0_last,
            fee_growth_inside1_last
        )
        
        # Get historical collected fees
        collected_fees_0, collected_fees_1 = get_collected_fees_from_events(
            connector.w3,
            connector.position_manager_address,
            token_id,
            token0_decimals,
            token1_decimals
        )
        
        # Get position creation time
        creation_timestamp = get_position_creation_time(
            connector.w3,
            connector.position_manager_address,
            token_id,
            pool_address,
            tick_lower,
            tick_upper
        )
        
        sqrt_price = sqrt_price_x96 / (2 ** 96)
        current_price_raw = sqrt_price ** 2
        decimal_adjustment = 10 ** (token0_decimals - token1_decimals)
        current_price_adjusted = current_price_raw * decimal_adjustment
        
        price_lower_raw = 1.0001 ** tick_lower
        price_upper_raw = 1.0001 ** tick_upper
        price_lower = price_lower_raw * decimal_adjustment
        price_upper = price_upper_raw * decimal_adjustment
        
        amount0, amount1 = calculate_token_amounts(
            liquidity, tick_lower, tick_upper, current_tick,
            sqrt_price_x96, token0_decimals, token1_decimals
        )
        
        price0_usd = get_token_price_usd(token0_symbol, token0, chain.value)
        price1_usd = get_token_price_usd(token1_symbol, token1, chain.value)
        
        value0_usd = amount0 * price0_usd
        value1_usd = amount1 * price1_usd
        total_value_usd = value0_usd + value1_usd
        
        # Calculate fee values
        total_fees_0 = uncollected_fees_0 + tokens_owed0
        total_fees_1 = uncollected_fees_1 + tokens_owed1
        
        fees_owed0 = total_fees_0 / (10 ** token0_decimals)
        fees_owed1 = total_fees_1 / (10 ** token1_decimals)
        
        fees0_usd = fees_owed0 * price0_usd
        fees1_usd = fees_owed1 * price1_usd
        total_fees_usd = fees0_usd + fees1_usd
        
        collected_fees_0_usd = collected_fees_0 * price0_usd
        collected_fees_1_usd = collected_fees_1 * price1_usd
        total_collected_fees_usd = collected_fees_0_usd + collected_fees_1_usd
        
        total_earned_fees_0 = collected_fees_0 + fees_owed0
        total_earned_fees_1 = collected_fees_1 + fees_owed1
        total_earned_fees_usd = total_collected_fees_usd + total_fees_usd
        
        # Calculate position age (after we have fee values for fallback estimation)
        current_time = datetime.now().timestamp()
        
        # Handle None (N/A) for Base positions
        if creation_timestamp is None:
            # Base chain - no age data available
            age_days = None
            age_hours = None
            age_display = "N/A"
            daily_apr = None
            monthly_apr = None
            daily_earnings = None
            print(f"Position {token_id}: Age not available (Base chain)")
        elif creation_timestamp > 0:
            age_seconds = current_time - creation_timestamp
            age_days = int(age_seconds // 86400)
            age_hours = int((age_seconds % 86400) // 3600)
            age_display = f"{age_days}d {age_hours}h"
            print(f"Position {token_id} created at {datetime.fromtimestamp(creation_timestamp)}")
            
            # Calculate APR
            daily_apr = 0.0
            monthly_apr = 0.0
            daily_earnings = 0.0
            
            if age_days > 0 and total_value_usd > 0:
                # Daily earnings = total earned fees / days
                daily_earnings = total_earned_fees_usd / age_days
                # Daily APR = (daily earnings / position value) * 100
                daily_apr = (daily_earnings / total_value_usd) * 100
                # Monthly APR = daily APR * 30
                monthly_apr = daily_apr * 30
        else:
            # Fallback: Use total earned fees to estimate age
            # Typical Uniswap V3 0.3% pool earns ~0.1-0.5% daily on active positions
            # Conservative estimate: if we have $100 in fees, position is at least 30-60 days old
            if total_earned_fees_usd > 10:
                # Estimate based on fees: assume 0.2% daily return
                estimated_days = (total_earned_fees_usd / total_value_usd) / 0.002 if total_value_usd > 0 else 30
                estimated_days = max(7, min(estimated_days, 365))  # Clamp between 7-365 days
                age_seconds = estimated_days * 86400
                print(f"Position {token_id}: Estimated age {int(estimated_days)} days based on ${total_earned_fees_usd:.2f} fees")
            elif collected_fees_0 > 0 or collected_fees_1 > 0:
                age_seconds = 30 * 86400  # 30 days if has collected fees
                print(f"Position {token_id}: Using 30 day estimate (has collected fees)")
            else:
                age_seconds = 7 * 86400  # 7 days for new positions
                print(f"Position {token_id}: Using 7 day estimate (new position)")
            
            age_days = int(age_seconds // 86400)
            age_hours = int((age_seconds % 86400) // 3600)
            age_display = f"{age_days}d {age_hours}h (est)"
            
            # Calculate APR
            daily_apr = 0.0
            monthly_apr = 0.0
            daily_earnings = 0.0
            
            if age_days > 0 and total_value_usd > 0:
                # Daily earnings = total earned fees / days
                daily_earnings = total_earned_fees_usd / age_days
                # Daily APR = (daily earnings / position value) * 100
                daily_apr = (daily_earnings / total_value_usd) * 100
                # Monthly APR = daily APR * 30
                monthly_apr = daily_apr * 30
        
        in_range = tick_lower <= current_tick <= tick_upper
        
        return {
            "token_id": token_id,
            "chain": chain.value,
            "pair": f"{token0_symbol}/{token1_symbol}",
            "token0_symbol": token0_symbol,
            "token1_symbol": token1_symbol,
            "amount0": amount0,
            "amount1": amount1,
            "price0_usd": price0_usd,
            "price1_usd": price1_usd,
            "value0_usd": value0_usd,
            "value1_usd": value1_usd,
            "total_value_usd": total_value_usd,
            "fees_owed0": fees_owed0,
            "fees_owed1": fees_owed1,
            "fees0_usd": fees0_usd,
            "fees1_usd": fees1_usd,
            "total_fees_usd": total_fees_usd,
            "collected_fees_0": collected_fees_0,
            "collected_fees_1": collected_fees_1,
            "collected_fees_0_usd": collected_fees_0_usd,
            "collected_fees_1_usd": collected_fees_1_usd,
            "total_collected_fees_usd": total_collected_fees_usd,
            "total_earned_fees_0": total_earned_fees_0,
            "total_earned_fees_1": total_earned_fees_1,
            "total_earned_fees_usd": total_earned_fees_usd,
            "age_days": age_days,
            "age_hours": age_hours,
            "daily_apr": daily_apr,
            "monthly_apr": monthly_apr,
            "daily_earnings": daily_earnings,
            "in_range": in_range,
            "fee_tier": fee / 10000,
            "current_price": current_price_adjusted,
            "price_lower": price_lower,
            "price_upper": price_upper
        }
        
    except Exception:
        return None


STABLECOINS = {'USDC', 'USDT', 'DAI', 'FRAX', 'LUSD', 'TUSD', 'BUSD', 'GUSD', 'USDP', 'sUSD', 'crvUSD', 'GHO', 'PYUSD', 'USDe', 'USDS'}


def _calc_aave_liquidation_price(aave_data: dict) -> dict | None:
    """Calculate liquidation price for an AAVE position.
    
    Only meaningful when one side is volatile and the other is stable.
    Returns dict with price info or None if not calculable.
    """
    supplied = aave_data.get('supplied', [])
    borrowed = aave_data.get('borrowed', [])
    liq_threshold = aave_data.get('liquidation_threshold', 0) / 100  # Convert % to decimal
    
    if not supplied or not borrowed or liq_threshold == 0:
        return None
    
    # Classify assets as stable or volatile
    stable_supply = [s for s in supplied if s['symbol'] in STABLECOINS]
    volatile_supply = [s for s in supplied if s['symbol'] not in STABLECOINS]
    stable_borrow = [b for b in borrowed if b['symbol'] in STABLECOINS]
    volatile_borrow = [b for b in borrowed if b['symbol'] not in STABLECOINS]
    
    # Case 1: Volatile collateral, stable debt (e.g., ETH supplied, USDC borrowed)
    if volatile_supply and not volatile_borrow and stable_borrow:
        # Liquidation when: collateral_value * liq_threshold = debt_value
        # collateral_value = sum(amount * price), debt is stable (~fixed USD)
        total_debt_usd = sum(b.get('value_usd', 0) for b in stable_borrow)
        # If single volatile collateral, we can give a specific price
        if len(volatile_supply) == 1:
            s = volatile_supply[0]
            # liq_price * amount * liq_threshold = total_debt
            if s['balance'] > 0 and liq_threshold > 0:
                liq_price = total_debt_usd / (s['balance'] * liq_threshold)
                return {
                    "type": "collateral_drop",
                    "asset": s['symbol'],
                    "current_price": s.get('price_usd', 0),
                    "liquidation_price": liq_price,
                    "description": f"{s['symbol']} price must drop to"
                }
        # Multiple volatile collaterals — show as % drop needed
        total_volatile_collateral = sum(s.get('value_usd', 0) for s in volatile_supply)
        if total_volatile_collateral > 0:
            liq_ratio = total_debt_usd / (total_volatile_collateral * liq_threshold)
            pct_drop = (1 - liq_ratio) * 100
            return {
                "type": "collateral_drop_pct",
                "pct_drop": pct_drop,
                "description": "Collateral must drop by"
            }
    
    # Case 2: Stable collateral, volatile debt (e.g., USDC supplied, ETH borrowed)
    if stable_supply and not stable_borrow and volatile_borrow:
        total_collateral_usd = sum(s.get('value_usd', 0) for s in stable_supply)
        max_debt_usd = total_collateral_usd * liq_threshold
        if len(volatile_borrow) == 1:
            b = volatile_borrow[0]
            if b['balance'] > 0:
                liq_price = max_debt_usd / b['balance']
                return {
                    "type": "debt_rise",
                    "asset": b['symbol'],
                    "current_price": b.get('price_usd', 0),
                    "liquidation_price": liq_price,
                    "description": f"{b['symbol']} price must rise to"
                }
    
    # Both stable or both volatile — no simple liquidation price
    return None


def get_portfolio_data(force_refresh=False):
    """Fetch complete portfolio data with caching."""
    global _portfolio_cache
    
    # Return cached data if available and not forcing refresh
    if _portfolio_cache is not None and not force_refresh:
        return _portfolio_cache
    
    WALLET_ADDRESSES = get_wallet_addresses()
    
    chains_config = {
        "Ethereum": (Chain.ETHEREUM, os.getenv("ETHEREUM_RPC_URL"), "ethereum"),
        "Arbitrum": (Chain.ARBITRUM, os.getenv("ARBITRUM_RPC_URL"), "arbitrum"),
        "Base": (Chain.BASE, os.getenv("BASE_RPC_URL"), "base")
    }
    
    all_tokens = []
    all_lp_positions = []
    total_tokens_value = 0.0
    total_lp_value = 0.0
    
    for wallet in WALLET_ADDRESSES:
        wallet_label = get_wallet_label(wallet)
        
        # Skip non-EVM wallets (e.g., Bitcoin xpub)
        config = load_wallet_config()
        if config.get(wallet, {}).get("type") == "bitcoin_xpub":
            continue
        
        for chain_name, (chain_enum, rpc_url, llama_chain) in chains_config.items():
            if not rpc_url:
                continue
            
            try:
                w3 = Web3(Web3.HTTPProvider(rpc_url))
                if w3.is_connected():
                    native_balance = w3.eth.get_balance(wallet)
                    native_eth = w3.from_wei(native_balance, 'ether')
                    
                    if native_eth > 0:
                        price_usd = get_token_price_usd("ETH", None, llama_chain)
                        value_usd = float(native_eth) * price_usd
                        all_tokens.append({
                            "chain": chain_name,
                            "symbol": "ETH",
                            "balance": float(native_eth),
                            "value_usd": value_usd,
                            "price_usd": price_usd,
                            "wallet": wallet,
                            "wallet_label": wallet_label
                        })
                        total_tokens_value += value_usd
                
                tokens = get_token_balances_alchemy(rpc_url, wallet, llama_chain)
                for token in tokens:
                    all_tokens.append({
                        "chain": chain_name,
                        "symbol": token["symbol"],
                        "balance": token["balance"],
                        "value_usd": token["value_usd"],
                        "price_usd": token["price_usd"],
                        "wallet": wallet,
                        "wallet_label": wallet_label
                    })
                    total_tokens_value += token["value_usd"]
                
            except Exception as e:
                print(f"Error fetching tokens from {chain_name}: {e}")
    
    # Get LP positions (hardcoded for now)
    if len(WALLET_ADDRESSES) > 0:
        lp_positions_config = [
            (5322036, Chain.ARBITRUM, WALLET_ADDRESSES[0] if len(WALLET_ADDRESSES) > 0 else None),
            (4691631, Chain.BASE, WALLET_ADDRESSES[0] if len(WALLET_ADDRESSES) > 0 else None)
        ]
        
        for token_id, chain, wallet in lp_positions_config:
            if wallet:
                try:
                    connector = UniswapV3Connector(chain=chain)
                    position_data = check_lp_position(connector, token_id, chain)
                    if position_data:
                        position_data['wallet'] = wallet
                        position_data['wallet_label'] = get_wallet_label(wallet)
                        position_data['protocol'] = 'uniswap_v3'
                        all_lp_positions.append(position_data)
                        total_lp_value += position_data["total_value_usd"]
                except Exception as e:
                    print(f"Error fetching LP position {token_id}: {e}")
    
    all_tokens.sort(key=lambda x: x["value_usd"], reverse=True)
    
    # Fetch Bitcoin balances from xpub wallets
    for wallet_key in WALLET_ADDRESSES:
        config = load_wallet_config()
        wallet_info = config.get(wallet_key, {})
        if wallet_info.get("type") == "bitcoin_xpub":
            try:
                from src.connectors.bitcoin import get_btc_balance_for_xpub
                print(f"Fetching BTC balance for xpub wallet: {wallet_info.get('label', 'BTC')}")
                btc_data = get_btc_balance_for_xpub(wallet_key)
                btc_balance = btc_data["total_btc"]
                if btc_balance > 0:
                    btc_price = get_token_price_usd("BTC", None, "bitcoin")
                    btc_value = btc_balance * btc_price
                    all_tokens.append({
                        "chain": "Bitcoin",
                        "symbol": "BTC",
                        "balance": btc_balance,
                        "value_usd": btc_value,
                        "price_usd": btc_price,
                        "wallet": wallet_key,
                        "wallet_label": get_wallet_label(wallet_key)
                    })
                    total_tokens_value += btc_value
                    print(f"BTC balance: {btc_balance:.8f} BTC (${btc_value:.2f}), {btc_data['addresses_used']} addresses used")
            except Exception as e:
                print(f"Error fetching BTC balance: {e}")
    
    all_tokens.sort(key=lambda x: x["value_usd"], reverse=True)
    
    # Calculate total uncollected fees
    total_uncollected_fees = sum(pos.get('total_fees_usd', 0) for pos in all_lp_positions)
    
    # Fetch AAVE V3 positions
    all_aave_positions = []
    for wallet in WALLET_ADDRESSES:
        config = load_wallet_config()
        if config.get(wallet, {}).get("type") == "bitcoin_xpub":
            continue
        wallet_label = get_wallet_label(wallet)
        for chain_name, (chain_enum, rpc_url, llama_chain) in chains_config.items():
            if not rpc_url:
                continue
            try:
                from src.connectors.aave_v3 import get_aave_positions
                w3 = Web3(Web3.HTTPProvider(rpc_url))
                aave_data = get_aave_positions(w3, wallet, llama_chain)
                if aave_data:
                    aave_data['wallet'] = wallet
                    aave_data['wallet_label'] = wallet_label
                    aave_data['chain_name'] = chain_name
                    # Add USD values to supplied/borrowed using our price function
                    for s in aave_data['supplied']:
                        price = get_token_price_usd(s['symbol'], s['token_address'], llama_chain)
                        s['price_usd'] = price
                        s['value_usd'] = s['balance'] * price
                    for b in aave_data['borrowed']:
                        price = get_token_price_usd(b['symbol'], b['token_address'], llama_chain)
                        b['price_usd'] = price
                        b['value_usd'] = b['balance'] * price
                    
                    # Calculate liquidation price if one side is stable
                    aave_data['liquidation_price'] = _calc_aave_liquidation_price(aave_data)
                    
                    all_aave_positions.append(aave_data)
                    print(f"AAVE {chain_name}: collateral=${aave_data['total_collateral_usd']:.2f}, debt=${aave_data['total_debt_usd']:.2f}, HF={aave_data['health_factor']:.2f}")
            except Exception as e:
                print(f"Error fetching AAVE on {chain_name}: {e}")
    
    # Fetch GMX V2 perpetual positions (Arbitrum only)
    all_gmx_positions = []
    arb_rpc = os.getenv("ARBITRUM_RPC_URL")
    if arb_rpc:
        for wallet in WALLET_ADDRESSES:
            config = load_wallet_config()
            if config.get(wallet, {}).get("type") == "bitcoin_xpub":
                continue
            try:
                from src.connectors.gmx_v2 import get_gmx_positions
                w3 = Web3(Web3.HTTPProvider(arb_rpc))
                gmx_pos = get_gmx_positions(w3, wallet)
                for p in gmx_pos:
                    p['wallet'] = wallet
                    p['wallet_label'] = get_wallet_label(wallet)
                    # Get current price for PnL calculation
                    current_price = get_token_price_usd(p['index_symbol'], None, "arbitrum")
                    if current_price == 0:
                        # Try coingecko mapping for common tokens
                        cg_map = {"WETH": "ETH", "WBTC": "BTC", "BTC": "BTC", "ETH": "ETH"}
                        mapped = cg_map.get(p['index_symbol'], p['index_symbol'])
                        if mapped == "BTC":
                            current_price = get_token_price_usd("BTC", None, "bitcoin")
                        else:
                            current_price = get_token_price_usd(mapped, None, "ethereum")
                    p['current_price'] = current_price
                    # Calculate PnL
                    if p['entry_price'] > 0 and current_price > 0:
                        if p['is_long']:
                            p['pnl_usd'] = p['size_usd'] * (current_price - p['entry_price']) / p['entry_price']
                        else:
                            p['pnl_usd'] = p['size_usd'] * (p['entry_price'] - current_price) / p['entry_price']
                        p['pnl_pct'] = (p['pnl_usd'] / p['collateral_amount']) * 100 if p['collateral_amount'] > 0 else 0
                    else:
                        p['pnl_usd'] = 0
                        p['pnl_pct'] = 0
                    # Estimate liquidation price (simplified: when losses = collateral)
                    if p['entry_price'] > 0 and p['size_usd'] > 0:
                        liq_move = p['collateral_amount'] / p['size_usd'] * p['entry_price']
                        if p['is_long']:
                            p['liquidation_price'] = p['entry_price'] - liq_move
                        else:
                            p['liquidation_price'] = p['entry_price'] + liq_move
                    else:
                        p['liquidation_price'] = 0
                    all_gmx_positions.append(p)
                if gmx_pos:
                    print(f"GMX: Found {len(gmx_pos)} positions for {get_wallet_label(wallet)}")
            except Exception as e:
                print(f"Error fetching GMX positions: {e}")
    
    # Get unique wallet labels for filtering
    wallet_labels = {}
    for wallet in WALLET_ADDRESSES:
        wallet_labels[wallet] = get_wallet_label(wallet)
    
    result = {
        "tokens": all_tokens,
        "lp_positions": all_lp_positions,
        "aave_positions": all_aave_positions,
        "gmx_positions": all_gmx_positions,
        "total_tokens_value": total_tokens_value,
        "total_lp_value": total_lp_value,
        "total_uncollected_fees": total_uncollected_fees,
        "total_value": total_tokens_value + total_lp_value + total_uncollected_fees,
        "wallet_count": len(WALLET_ADDRESSES),
        "wallet_labels": wallet_labels
    }
    
    # Cache the result
    _portfolio_cache = result
    
    return result


@app.route('/login', methods=['GET', 'POST'])
def login_page():
    """Login page, or first-time setup if no password exists."""
    pw_hash = get_password_hash()

    # No password set — show one-time setup page
    if not pw_hash:
        error = None
        if request.method == 'POST':
            password = request.form.get('password', '')
            confirm = request.form.get('confirm', '')
            if len(password) < 6:
                error = "Password must be at least 6 characters"
            elif password != confirm:
                error = "Passwords don't match"
            else:
                new_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                env_file = find_dotenv() or ".env"
                set_key(env_file, "APP_PASSWORD_HASH", new_hash)
                load_dotenv(override=True)
                session['authenticated'] = True
                session.permanent = True
                return redirect(url_for('index'))
        return render_template('setup.html', error=error)

    # Already authenticated
    if session.get('authenticated'):
        return redirect(url_for('index'))

    error = None
    if request.method == 'POST':
        ip = request.remote_addr
        if not check_rate_limit(ip):
            error = "Too many attempts. Try again in 5 minutes."
        else:
            password = request.form.get('password', '')
            if bcrypt.checkpw(password.encode('utf-8'), pw_hash.encode('utf-8')):
                session['authenticated'] = True
                session.permanent = True
                _login_attempts.pop(ip, None)
                return redirect(url_for('index'))
            else:
                error = "Invalid password"

    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    """Log out and clear session."""
    session.clear()
    return redirect(url_for('login_page'))


@app.route('/api/change-password', methods=['POST'])
def api_change_password():
    """Change the app password."""
    data = request.json
    current = data.get('current', '')
    new_pw = data.get('new', '')

    if not new_pw or len(new_pw) < 6:
        return jsonify({"error": "New password must be at least 6 characters"}), 400

    pw_hash = get_password_hash()
    # If a password is set, verify current password
    if pw_hash and not bcrypt.checkpw(current.encode('utf-8'), pw_hash.encode('utf-8')):
        return jsonify({"error": "Current password is incorrect"}), 403

    # Generate new hash and save to .env
    new_hash = bcrypt.hashpw(new_pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    env_file = find_dotenv() or ".env"
    set_key(env_file, "APP_PASSWORD_HASH", new_hash)
    load_dotenv(override=True)

    return jsonify({"status": "success", "message": "Password updated"})


@app.route('/')
def index():
    """Render the unified dashboard."""
    return render_template('index.html')


@app.route('/settings')
def settings():
    """Render the settings page."""
    return render_template('settings.html')


@app.route('/api/portfolio')
def api_portfolio():
    """API endpoint for portfolio data."""
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    data = get_portfolio_data(force_refresh=force_refresh)
    return jsonify(data)


@app.route('/api/wallets', methods=['GET'])
def api_get_wallets():
    """Get list of wallet addresses with labels."""
    config = load_wallet_config()
    wallets = [
        {
            "address": addr,
            "label": info.get("label", addr[:10] + "...")
        }
        for addr, info in config.items()
    ]
    return jsonify({"wallets": wallets})


@app.route('/api/wallets', methods=['POST'])
def api_add_wallet():
    """Add a new wallet address or Bitcoin xpub with optional label."""
    global _portfolio_cache
    data = request.json
    address = data.get('address', '').strip()
    label = data.get('label', '').strip()

    # Detect if this is a Bitcoin xpub/ypub/zpub
    is_xpub = address.startswith(('xpub', 'ypub', 'zpub'))

    if not is_xpub and not is_valid_address(address):
        return jsonify({"error": "Invalid address format. Use an Ethereum address (0x...) or Bitcoin xpub/ypub/zpub."}), 400

    if is_xpub and len(address) < 100:
        return jsonify({"error": "Invalid xpub key — too short"}), 400

    config = load_wallet_config()

    # Check for duplicates
    if address in config:
        return jsonify({"error": "Wallet already exists"}), 400

    # Add wallet with label and type
    wallet_entry = {
        "label": label if label else ("BTC Ledger" if is_xpub else f"Wallet {len(config) + 1}"),
        "added_at": datetime.now().isoformat()
    }
    if is_xpub:
        wallet_entry["type"] = "bitcoin_xpub"

    config[address] = wallet_entry
    save_wallet_config(config)
    save_wallet_addresses(list(config.keys()))

    _portfolio_cache = None

    wallets = [
        {"address": addr, "label": info.get("label", addr[:10] + "...")}
        for addr, info in config.items()
    ]
    return jsonify({"success": True, "wallets": wallets})


@app.route('/api/wallets/<address>', methods=['PUT'])
def api_update_wallet(address):
    """Update wallet label."""
    global _portfolio_cache
    data = request.json
    label = data.get('label', '').strip()
    
    if not label:
        return jsonify({"error": "Label cannot be empty"}), 400
    
    config = load_wallet_config()
    
    # Find wallet (case-insensitive)
    wallet_key = None
    for key in config.keys():
        if key.lower() == address.lower():
            wallet_key = key
            break
    
    if not wallet_key:
        return jsonify({"error": "Wallet not found"}), 404
    
    config[wallet_key]["label"] = label
    save_wallet_config(config)
    
    # Clear cache when labels change
    _portfolio_cache = None
    
    return jsonify({"success": True})


@app.route('/api/wallets/<address>', methods=['DELETE'])
def api_remove_wallet(address):
    """Remove a wallet address."""
    global _portfolio_cache
    config = load_wallet_config()
    
    # Find and remove the address (case-insensitive)
    wallet_key = None
    for key in config.keys():
        if key.lower() == address.lower():
            wallet_key = key
            break
    
    if wallet_key:
        del config[wallet_key]
        save_wallet_config(config)
        save_wallet_addresses(list(config.keys()))
        
        # Clear cache when wallets change
        _portfolio_cache = None
    
    wallets = [
        {"address": addr, "label": info.get("label", addr[:10] + "...")}
        for addr, info in config.items()
    ]
    return jsonify({"success": True, "wallets": wallets})


@app.route('/api/config', methods=['GET'])
def api_get_config():
    """Get API keys (masked)."""
    return jsonify({
        "alchemy_api_key": os.getenv("ALCHEMY_API_KEY", ""),
        "etherscan_api_key": os.getenv("ETHERSCAN_API_KEY", ""),
        "brave_api_key": os.getenv("BRAVE_API_KEY", "")
    })


@app.route('/api/config', methods=['POST'])
def api_update_config():
    """Update API key in .env file."""
    try:
        data = request.json
        key_name = data.get('key')
        key_value = data.get('value', '').strip()
        
        if not key_name or not key_value:
            return jsonify({"error": "Missing key or value"}), 400
        
        # Validate key name
        valid_keys = ['ALCHEMY_API_KEY', 'ETHERSCAN_API_KEY', 'BRAVE_API_KEY']
        if key_name not in valid_keys:
            return jsonify({"error": "Invalid key name"}), 400
        
        # Read current .env file
        env_path = '.env'
        env_lines = []
        key_found = False
        
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                env_lines = f.readlines()
        
        # Update or add the key
        new_lines = []
        for line in env_lines:
            if line.strip().startswith(f'{key_name}='):
                new_lines.append(f'{key_name}={key_value}\n')
                key_found = True
            else:
                new_lines.append(line)
        
        # If key wasn't found, add it
        if not key_found:
            new_lines.append(f'\n{key_name}={key_value}\n')
        
        # Write back to .env
        with open(env_path, 'w') as f:
            f.writelines(new_lines)
        
        # Update environment variable for current session
        os.environ[key_name] = key_value
        
        return jsonify({"success": True, "message": f"{key_name} updated successfully"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


PROFILE_FILE = os.path.join("data", "investor_profile.json")


@app.route('/api/manual-positions', methods=['GET'])
def api_get_manual_positions():
    """Get all active manual LP positions."""
    from src.storage.portfolio_db import get_connection
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM lp_positions WHERE is_active=1 ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/manual-positions', methods=['POST'])
def api_add_manual_position():
    """Add a new manual LP position."""
    from src.storage.portfolio_db import get_connection
    data = request.json
    
    # Validate required fields
    required = ['chain', 'protocol', 'token0', 'token1', 'amount0', 'amount1', 'range_lower', 'range_upper', 'fee_tier']
    missing = [f for f in required if not data.get(f) and data.get(f) != 0]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
    
    # Validate and fetch token prices (use overrides if provided)
    price0 = float(data['price0_override']) if data.get('price0_override') else _get_coingecko_price(data['token0'])
    price1 = float(data['price1_override']) if data.get('price1_override') else _get_coingecko_price(data['token1'])
    
    # Retry once if rate limited
    import time as _time
    if price0 is None and not data.get('price0_override'):
        _time.sleep(1.5)
        price0 = _get_coingecko_price(data['token0'])
    if price1 is None and not data.get('price1_override'):
        _time.sleep(1.5)
        price1 = _get_coingecko_price(data['token1'])
    
    token0_valid = price0 is not None
    token1_valid = price1 is not None
    
    # If price not available and no override, reject
    price_errors = []
    if not token0_valid:
        price_errors.append(f"{data['token0']} price not found — enter Price Token0 manually")
    if not token1_valid:
        price_errors.append(f"{data['token1']} price not found — enter Price Token1 manually")
    if price_errors:
        return jsonify({"error": "; ".join(price_errors), "need_prices": True}), 400
    
    price0 = price0 or 0
    price1 = price1 or 0
    
    amount0 = float(data['amount0'])
    amount1 = float(data['amount1'])
    value_usd = amount0 * price0 + amount1 * price1
    
    # Calculate current price (token1 per token0)
    current_price = price0 / price1 if price1 > 0 else 0
    in_range = float(data['range_lower']) <= current_price <= float(data['range_upper'])
    
    conn = get_connection()
    c = conn.cursor()
    c.execute("""INSERT INTO lp_positions
        (user_id, source, chain, protocol, position_id, token0, token1, fee_tier,
         value_usd, range_lower, range_upper, current_price, in_range,
         fees_uncollected_usd, fees_collected_usd, notes, is_active,
         amount0, amount1, price0_usd, price1_usd, entry_value_usd)
        VALUES (1, 'manual', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 1, ?, ?, ?, ?, ?)""",
        (data['chain'], data['protocol'], data.get('position_id', ''),
         data['token0'], data['token1'], float(data['fee_tier']),
         value_usd, float(data['range_lower']), float(data['range_upper']),
         current_price, in_range, data.get('notes', ''),
         amount0, amount1, price0, price1, value_usd))
    pos_id = c.lastrowid
    conn.commit()
    conn.close()
    
    return jsonify({
        "success": True, "id": pos_id,
        "value_usd": value_usd,
        "current_price": current_price,
        "in_range": in_range,
        "token0_valid": token0_valid,
        "token1_valid": token1_valid,
        "warnings": [] if (token0_valid and token1_valid) else
            [f"Price not found for: {', '.join([data['token0']] * (not token0_valid) + [data['token1']] * (not token1_valid))}"]
    })


@app.route('/api/manual-positions/<int:pos_id>', methods=['PUT'])
def api_update_manual_position(pos_id):
    """Update a manual position (fees, notes, or close it)."""
    from src.storage.portfolio_db import get_connection
    data = request.json
    conn = get_connection()
    
    if data.get('action') == 'close':
        # Fetch current prices for exit value
        row = conn.execute("SELECT * FROM lp_positions WHERE id=?", (pos_id,)).fetchone()
        if row:
            price0 = _get_coingecko_price(row['token0']) or 0
            price1 = _get_coingecko_price(row['token1']) or 0
            exit_value = (row['amount0'] or 0) * price0 + (row['amount1'] or 0) * price1
            conn.execute(
                "UPDATE lp_positions SET is_active=0, updated_at=CURRENT_TIMESTAMP, value_usd=?, current_price=? WHERE id=?",
                (exit_value, price0 / price1 if price1 > 0 else 0, pos_id))
        else:
            conn.execute("UPDATE lp_positions SET is_active=0, updated_at=CURRENT_TIMESTAMP WHERE id=?", (pos_id,))
    else:
        updates = []
        params = []
        for field in ['fees_uncollected_usd', 'fees_collected_usd', 'notes', 'amount0', 'amount1']:
            if field in data:
                updates.append(f"{field}=?")
                params.append(data[field])
        if updates:
            updates.append("updated_at=CURRENT_TIMESTAMP")
            params.append(pos_id)
            conn.execute(f"UPDATE lp_positions SET {', '.join(updates)} WHERE id=?", params)
            
            # Recalculate value if amounts changed
            if 'amount0' in data or 'amount1' in data:
                row = conn.execute("SELECT * FROM lp_positions WHERE id=?", (pos_id,)).fetchone()
                if row:
                    price0 = _get_coingecko_price(row['token0']) or 0
                    price1 = _get_coingecko_price(row['token1']) or 0
                    value_usd = (row['amount0'] or 0) * price0 + (row['amount1'] or 0) * price1
                    current_price = price0 / price1 if price1 > 0 else 0
                    in_range = row['range_lower'] <= current_price <= row['range_upper']
                    conn.execute("UPDATE lp_positions SET value_usd=?, current_price=?, in_range=? WHERE id=?",
                        (value_usd, current_price, in_range, pos_id))
    
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route('/api/validate-token/<symbol>')
def api_validate_token(symbol):
    """Check if a token symbol is recognized and return its price."""
    # First check if it's in our known mapping
    cg_map = {
        'BTC': 'bitcoin', 'ETH': 'ethereum', 'WETH': 'ethereum', 'WBTC': 'bitcoin',
        'SOL': 'solana', 'USDC': 'usd-coin', 'USDT': 'tether', 'DAI': 'dai',
        'ARB': 'arbitrum', 'OP': 'optimism', 'LINK': 'chainlink', 'UNI': 'uniswap',
        'AAVE': 'aave', 'SUI': 'sui', 'TAO': 'bittensor', 'DOGE': 'dogecoin',
        'AVAX': 'avalanche-2', 'MATIC': 'matic-network', 'NEAR': 'near',
        'DOT': 'polkadot', 'ATOM': 'cosmos', 'XRP': 'ripple',
        'stETH': 'staked-ether', 'wstETH': 'wrapped-steth', 'cbBTC': 'bitcoin',
        'USDe': 'ethena-usde', 'GHO': 'gho', 'CRV': 'curve-dao-token',
        'PEPE': 'pepe', 'INJ': 'injective-protocol', 'TIA': 'celestia',
    }
    sym_upper = symbol.upper()
    known = sym_upper in cg_map or symbol in cg_map
    price = _get_coingecko_price(symbol)
    return jsonify({
        "symbol": symbol,
        "valid": price is not None,
        "known": known,
        "price_usd": price or 0,
        "message": "" if price else ("Rate limited — try again" if known else "Token not recognized")
    })


@app.route('/api/manual-hedges', methods=['GET'])
def api_get_manual_hedges():
    """Get all active manual hedge positions with live prices."""
    from src.storage.portfolio_db import get_connection
    conn = get_connection()
    rows = conn.execute("SELECT * FROM hedge_positions WHERE is_active=1 ORDER BY created_at DESC").fetchall()
    conn.close()
    results = []
    for row in rows:
        h = dict(row)
        # Refresh current price and recalculate PnL
        symbol = h['market'].split('/')[0] if '/' in h['market'] else h['market']
        price = _get_coingecko_price(symbol)
        if price:
            h['current_price'] = price
            if h['entry_price'] and h['size_usd']:
                if h['direction'] == 'long':
                    h['pnl_usd'] = h['size_usd'] * (price - h['entry_price']) / h['entry_price']
                else:
                    h['pnl_usd'] = h['size_usd'] * (h['entry_price'] - price) / h['entry_price']
                h['pnl_pct'] = (h['pnl_usd'] / h['margin_usd'] * 100) if h['margin_usd'] > 0 else 0
        results.append(h)
    return jsonify(results)


@app.route('/api/manual-hedges', methods=['POST'])
def api_add_manual_hedge():
    """Add a new manual hedge position."""
    from src.storage.portfolio_db import get_connection
    data = request.json
    
    required = ['market', 'direction', 'margin_usd', 'leverage']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400
    
    margin = float(data['margin_usd'])
    leverage = float(data['leverage'])
    size_usd = margin * leverage
    direction = data['direction']
    
    # Get entry price (user-provided or fetched)
    symbol = data['market'].split('/')[0] if '/' in data['market'] else data['market']
    entry_price = float(data['entry_price']) if data.get('entry_price') else None
    if not entry_price:
        entry_price = _get_coingecko_price(symbol) or 0
    
    current_price = _get_coingecko_price(symbol) or entry_price
    
    # Calculate liquidation price
    if entry_price > 0 and size_usd > 0:
        liq_move = margin / size_usd * entry_price
        liq_price = (entry_price - liq_move) if direction == 'long' else (entry_price + liq_move)
    else:
        liq_price = 0
    
    # Calculate PnL
    pnl_usd = 0
    if entry_price > 0 and current_price > 0:
        if direction == 'long':
            pnl_usd = size_usd * (current_price - entry_price) / entry_price
        else:
            pnl_usd = size_usd * (entry_price - current_price) / entry_price
    pnl_pct = (pnl_usd / margin * 100) if margin > 0 else 0
    
    conn = get_connection()
    c = conn.cursor()
    c.execute("""INSERT INTO hedge_positions
        (user_id, source, exchange, market, direction, margin_usd, leverage, size_usd,
         entry_price, current_price, liquidation_price, pnl_usd, pnl_pct,
         stop_loss_price, take_profit_price, notes, is_active)
        VALUES (1, 'manual', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        (data.get('exchange', ''), data['market'], direction, margin, leverage, size_usd,
         entry_price, current_price, liq_price, pnl_usd, pnl_pct,
         float(data['stop_loss_price']) if data.get('stop_loss_price') else None,
         float(data['take_profit_price']) if data.get('take_profit_price') else None,
         data.get('notes', '')))
    hedge_id = c.lastrowid
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "id": hedge_id, "entry_price": entry_price,
                    "size_usd": size_usd, "liquidation_price": liq_price})


@app.route('/api/manual-hedges/<int:hedge_id>', methods=['PUT'])
def api_update_manual_hedge(hedge_id):
    """Update or close a manual hedge."""
    from src.storage.portfolio_db import get_connection
    data = request.json
    conn = get_connection()
    
    if data.get('action') == 'close':
        row = conn.execute("SELECT * FROM hedge_positions WHERE id=?", (hedge_id,)).fetchone()
        if row:
            symbol = row['market'].split('/')[0] if '/' in row['market'] else row['market']
            price = _get_coingecko_price(symbol) or row['current_price']
            if row['direction'] == 'long':
                pnl = row['size_usd'] * (price - row['entry_price']) / row['entry_price'] if row['entry_price'] else 0
            else:
                pnl = row['size_usd'] * (row['entry_price'] - price) / row['entry_price'] if row['entry_price'] else 0
            conn.execute(
                "UPDATE hedge_positions SET is_active=0, updated_at=CURRENT_TIMESTAMP, current_price=?, pnl_usd=? WHERE id=?",
                (price, pnl, hedge_id))
        else:
            conn.execute("UPDATE hedge_positions SET is_active=0, updated_at=CURRENT_TIMESTAMP WHERE id=?", (hedge_id,))
    else:
        updates = []
        params = []
        for field in ['stop_loss_price', 'take_profit_price', 'notes', 'margin_usd']:
            if field in data:
                updates.append(f"{field}=?")
                params.append(data[field])
        if updates:
            updates.append("updated_at=CURRENT_TIMESTAMP")
            params.append(hedge_id)
            conn.execute(f"UPDATE hedge_positions SET {', '.join(updates)} WHERE id=?", params)
    
    conn.commit()
    conn.close()
    return jsonify({"success": True})


_cg_price_cache = {}  # symbol -> (price, timestamp)

def _get_coingecko_price(symbol: str) -> float | None:
    """Get token price from CoinGecko by symbol. Caches for 60 seconds."""
    import time as _t
    cache_key = symbol.upper()
    if cache_key in _cg_price_cache:
        price, ts = _cg_price_cache[cache_key]
        if _t.time() - ts < 60:  # Cache for 60 seconds
            return price
    
    cg_map = {
        'BTC': 'bitcoin', 'ETH': 'ethereum', 'WETH': 'ethereum', 'WBTC': 'bitcoin',
        'SOL': 'solana', 'USDC': 'usd-coin', 'USDT': 'tether', 'DAI': 'dai',
        'ARB': 'arbitrum', 'OP': 'optimism', 'MATIC': 'matic-network', 'AVAX': 'avalanche-2',
        'LINK': 'chainlink', 'UNI': 'uniswap', 'AAVE': 'aave', 'CRV': 'curve-dao-token',
        'SUI': 'sui', 'TAO': 'bittensor', 'DOGE': 'dogecoin', 'XRP': 'ripple',
        'DOT': 'polkadot', 'ATOM': 'cosmos', 'NEAR': 'near', 'FTM': 'fantom',
        'APT': 'aptos', 'INJ': 'injective-protocol', 'TIA': 'celestia',
        'STX': 'blockstack', 'SEI': 'sei-network', 'PEPE': 'pepe',
        'cbBTC': 'bitcoin', 'stETH': 'staked-ether', 'wstETH': 'wrapped-steth',
        'rETH': 'rocket-pool-eth', 'USDe': 'ethena-usde', 'GHO': 'gho',
    }
    cg_id = cg_map.get(symbol.upper(), cg_map.get(symbol))
    if not cg_id:
        # Try lowercase as CoinGecko ID directly
        cg_id = symbol.lower()
    try:
        r = requests.get(f'https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd', timeout=5)
        if r.ok:
            price = r.json().get(cg_id, {}).get('usd')
            if price and price > 0:
                _cg_price_cache[cache_key] = (float(price), _t.time())
                return float(price)
        elif r.status_code == 429:
            # Rate limited — retry once after delay
            import time
            time.sleep(1)
            r = requests.get(f'https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd', timeout=5)
            if r.ok:
                price = r.json().get(cg_id, {}).get('usd')
                if price and price > 0:
                    _cg_price_cache[cache_key] = (float(price), _t.time())
                    return float(price)
    except Exception:
        pass
    return None


@app.route('/api/profile', methods=['GET'])
def api_get_profile():
    """Get the investor profile questionnaire answers."""
    if os.path.exists(PROFILE_FILE):
        try:
            with open(PROFILE_FILE, 'r') as f:
                return jsonify(json.load(f))
        except Exception:
            pass
    return jsonify({})


@app.route('/api/profile', methods=['POST'])
def api_save_profile():
    """Save the investor profile questionnaire answers."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
    os.makedirs(os.path.dirname(PROFILE_FILE), exist_ok=True)
    with open(PROFILE_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    return jsonify({"status": "success", "message": "Profile saved"})


# --- History / Snapshot Routes ---

from src.storage.portfolio_db import (
    init_db,
    get_db_path,
    get_portfolio_timeseries,
    get_market_timeseries,
    get_token_price_history,
)

# Initialize DB on startup
init_db()

# Background scheduler
_scheduler_started = False


def start_snapshot_scheduler():
    """Start background scheduler for portfolio (2h) and market (3x daily) snapshots."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    from src.engines.snapshot_service import start_scheduler
    start_scheduler(get_portfolio_data, get_wallet_addresses)


@app.route('/api/snapshot', methods=['POST'])
def api_take_snapshot():
    """Manually trigger a portfolio snapshot."""
    try:
        wallets = get_wallet_addresses()
        if not wallets:
            return jsonify({"error": "No wallets configured"}), 400
        from src.engines.snapshot_service import take_portfolio_snapshot
        take_portfolio_snapshot(get_portfolio_data, wallets)
        return jsonify({"status": "success", "message": f"Snapshot completed for {len(wallets)} wallet(s)"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/history/portfolio')
def api_history_portfolio():
    """Get portfolio value timeseries for charts."""
    days = request.args.get('days', 90, type=int)
    wallet = request.args.get('wallet')
    data = get_portfolio_timeseries(days=days, wallet=wallet)
    return jsonify(data)


@app.route('/api/history/portfolio-chart')
def api_history_portfolio_chart():
    """Get aggregated portfolio chart data — sums across all wallets per timestamp."""
    from src.storage.portfolio_db import get_connection
    conn = get_connection()
    
    days = request.args.get('days', 30, type=int)
    date_from = request.args.get('from')
    date_to = request.args.get('to')
    
    if date_from:
        query = """SELECT strftime('%Y-%m-%dT%H:%M:00', timestamp) as ts,
            SUM(total_tokens_usd) as tokens_value,
            SUM(total_lp_usd) as lp_value,
            SUM(total_lending_usd) as lending_value,
            SUM(total_hedge_collateral_usd) as hedge_value,
            SUM(total_value_usd) as total_value
            FROM portfolio_snapshots
            WHERE status='completed' AND timestamp >= ? AND timestamp <= ?
            GROUP BY ts ORDER BY ts ASC"""
        rows = conn.execute(query, (date_from, date_to + 'T23:59:59' if date_to else '9999-12-31')).fetchall()
    else:
        query = """SELECT strftime('%Y-%m-%dT%H:%M:00', timestamp) as ts,
            SUM(total_tokens_usd) as tokens_value,
            SUM(total_lp_usd) as lp_value,
            SUM(total_lending_usd) as lending_value,
            SUM(total_hedge_collateral_usd) as hedge_value,
            SUM(total_value_usd) as total_value
            FROM portfolio_snapshots
            WHERE status='completed'"""
        if days < 9999:
            query += f" AND timestamp >= datetime('now', '-{days} days')"
        query += " GROUP BY ts ORDER BY ts ASC"
        rows = conn.execute(query).fetchall()
    
    # Also get total fees per timestamp from lp_snapshots
    result = []
    for r in rows:
        ts = r['ts']
        fees_row = conn.execute(
            "SELECT COALESCE(SUM(total_earned_fees_usd), 0) as total_fees FROM lp_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?", (ts,)
        ).fetchone()
        result.append({
            'timestamp': ts,
            'tokens_value': r['tokens_value'] or 0,
            'lp_value': r['lp_value'] or 0,
            'lending_value': r['lending_value'] or 0,
            'hedge_value': r['hedge_value'] or 0,
            'total_value': r['total_value'] or 0,
            'total_fees': fees_row['total_fees'] if fees_row else 0,
        })
    
    conn.close()
    return jsonify(result)


@app.route('/api/history/token/<symbol>')
def api_history_token(symbol):
    """Get token price history."""
    days = request.args.get('days', 90, type=int)
    data = get_token_price_history(symbol, days=days)
    return jsonify(data)


@app.route('/api/history/closed-positions')
def api_history_closed_positions():
    """Get closed LP and hedge positions by comparing snapshots."""
    from src.storage.portfolio_db import get_connection
    conn = get_connection()
    
    days = request.args.get('days', 9999, type=int)
    date_from = request.args.get('from')
    date_to = request.args.get('to')
    
    # Build date filter
    if date_from:
        date_filter = f"AND timestamp >= '{date_from}' AND timestamp <= '{date_to}T23:59:59'" if date_to else f"AND timestamp >= '{date_from}'"
    elif days < 9999:
        date_filter = f"AND timestamp >= datetime('now', '-{days} days')"
    else:
        date_filter = ""
    
    # Get the latest snapshot timestamp (rounded to minute)
    latest = conn.execute(
        "SELECT MAX(strftime('%Y-%m-%dT%H:%M:00', timestamp)) as ts FROM portfolio_snapshots WHERE status='completed'"
    ).fetchone()
    if not latest or not latest['ts']:
        # No snapshots yet, but check manual positions
        closed_lps = []
        closed_hedges = []
        manual_lps_early = conn.execute(
            f"SELECT * FROM lp_positions WHERE is_active=0 {date_filter.replace('timestamp', 'updated_at')}"
        ).fetchall()
        for mp in manual_lps_early:
            mp = dict(mp)
            entry_value = mp.get('entry_value_usd') or mp.get('value_usd') or 0
            exit_value = mp.get('value_usd') or 0
            total_fees = (mp.get('fees_uncollected_usd') or 0) + (mp.get('fees_collected_usd') or 0)
            try:
                from datetime import datetime as dt
                t0 = dt.fromisoformat(str(mp.get('created_at', '')).replace('Z', ''))
                t1 = dt.fromisoformat(str(mp.get('updated_at', '')).replace('Z', ''))
                days_held = max((t1 - t0).total_seconds() / 86400, 1)
            except Exception:
                days_held = 1
            total_return = ((exit_value - entry_value + total_fees) / entry_value * 100) if entry_value > 0 else 0
            annual_apr = total_return * (365 / days_held) if days_held > 0 else 0
            closed_lps.append({
                'pair': (mp.get('token0') or '?') + '/' + (mp.get('token1') or '?'),
                'chain': mp.get('chain') or 'Manual',
                'entry_value': entry_value, 'exit_value': exit_value,
                'range_lower': mp.get('range_lower'), 'range_upper': mp.get('range_upper'),
                'total_fees': total_fees, 'total_return_pct': total_return,
                'annual_apr': annual_apr, 'days_held': int(days_held),
                'entry_date': str(mp.get('created_at', ''))[:10],
                'exit_date': str(mp.get('updated_at', ''))[:10],
            })
        manual_hedges_early = conn.execute(
            f"SELECT * FROM hedge_positions WHERE is_active=0 {date_filter.replace('timestamp', 'updated_at')}"
        ).fetchall()
        for mh in manual_hedges_early:
            mh = dict(mh)
            closed_hedges.append({
                'market': mh.get('market') or '?', 'direction': mh.get('direction') or '?',
                'entry_price': mh.get('entry_price') or 0, 'exit_price': mh.get('current_price') or 0,
                'size_usd': mh.get('size_usd') or 0, 'pnl_usd': mh.get('pnl_usd') or 0,
                'entry_date': str(mh.get('created_at', ''))[:10],
                'exit_date': str(mh.get('updated_at', ''))[:10],
            })
        conn.close()
        return jsonify({'closed_lps': closed_lps, 'closed_hedges': closed_hedges})
    latest_ts = latest['ts']
    
    # Get position_ids in the latest snapshot
    active_lp_ids = set(r['position_id'] for r in conn.execute(
        "SELECT DISTINCT position_id FROM lp_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?", (latest_ts,)
    ).fetchall())
    
    # Get all position_ids that existed within the date range
    all_lp_ids = set(r['position_id'] for r in conn.execute(
        f"SELECT DISTINCT position_id FROM lp_snapshots WHERE 1=1 {date_filter}"
    ).fetchall())
    
    closed_lp_ids = all_lp_ids - active_lp_ids
    
    closed_lps = []
    for pid in closed_lp_ids:
        # First snapshot = entry
        first = conn.execute(
            "SELECT * FROM lp_snapshots WHERE position_id=? ORDER BY timestamp ASC LIMIT 1", (pid,)
        ).fetchone()
        # Last snapshot = exit
        last = conn.execute(
            "SELECT * FROM lp_snapshots WHERE position_id=? ORDER BY timestamp DESC LIMIT 1", (pid,)
        ).fetchone()
        # Max fees ever
        max_fees = conn.execute(
            "SELECT MAX(total_earned_fees_usd) as fees FROM lp_snapshots WHERE position_id=?", (pid,)
        ).fetchone()
        
        if first and last:
            entry_value = first['value_usd'] or 0
            exit_value = last['value_usd'] or 0
            total_fees = max_fees['fees'] if max_fees and max_fees['fees'] else 0
            # Calculate days held
            from datetime import datetime as dt
            try:
                t0 = dt.fromisoformat(first['timestamp'].replace('Z',''))
                t1 = dt.fromisoformat(last['timestamp'].replace('Z',''))
                days_held = max((t1 - t0).total_seconds() / 86400, 1)
            except Exception:
                days_held = 1
            # Total return = (exit - entry + fees) / entry
            total_return = ((exit_value - entry_value + total_fees) / entry_value * 100) if entry_value > 0 else 0
            # Annualized APR
            annual_apr = total_return * (365 / days_held) if days_held > 0 else 0
            
            closed_lps.append({
                'pair': first['token0'] + '/' + first['token1'],
                'chain': first['chain'],
                'entry_value': entry_value,
                'exit_value': exit_value,
                'range_lower': first['range_lower'],
                'range_upper': first['range_upper'],
                'total_fees': total_fees,
                'total_return_pct': total_return,
                'annual_apr': annual_apr,
                'days_held': int(days_held),
                'entry_date': first['timestamp'][:10],
                'exit_date': last['timestamp'][:10],
            })
    
    # Closed hedges
    active_hedge_keys = set()
    for r in conn.execute(
        "SELECT DISTINCT market, direction, wallet FROM hedge_snapshots WHERE strftime('%Y-%m-%dT%H:%M:00', timestamp)=?", (latest_ts,)
    ).fetchall():
        active_hedge_keys.add((r['market'], r['direction'], r['wallet']))
    
    all_hedge_keys = set()
    for r in conn.execute(f"SELECT DISTINCT market, direction, wallet FROM hedge_snapshots WHERE 1=1 {date_filter}").fetchall():
        all_hedge_keys.add((r['market'], r['direction'], r['wallet']))
    
    closed_hedge_keys = all_hedge_keys - active_hedge_keys
    
    closed_hedges = []
    for market, direction, wallet in closed_hedge_keys:
        first = conn.execute(
            "SELECT * FROM hedge_snapshots WHERE market=? AND direction=? AND wallet=? ORDER BY timestamp ASC LIMIT 1",
            (market, direction, wallet)
        ).fetchone()
        last = conn.execute(
            "SELECT * FROM hedge_snapshots WHERE market=? AND direction=? AND wallet=? ORDER BY timestamp DESC LIMIT 1",
            (market, direction, wallet)
        ).fetchone()
        if first and last:
            closed_hedges.append({
                'market': market,
                'direction': direction,
                'entry_price': first['entry_price'],
                'exit_price': last['current_price'],
                'size_usd': first['size_usd'],
                'pnl_usd': last['pnl_usd'] or 0,
                'entry_date': first['timestamp'][:10],
                'exit_date': last['timestamp'][:10],
            })
    
    # Also include closed manual LP positions
    manual_lps = conn.execute(
        f"SELECT * FROM lp_positions WHERE is_active=0 {date_filter.replace('timestamp', 'updated_at')}"
    ).fetchall()
    for mp in manual_lps:
        mp = dict(mp)
        entry_value = mp.get('entry_value_usd') or mp.get('value_usd') or 0
        exit_value = mp.get('value_usd') or 0
        total_fees = (mp.get('fees_uncollected_usd') or 0) + (mp.get('fees_collected_usd') or 0)
        try:
            from datetime import datetime as dt
            t0 = dt.fromisoformat(str(mp.get('created_at', '')).replace('Z', ''))
            t1 = dt.fromisoformat(str(mp.get('updated_at', '')).replace('Z', ''))
            days_held = max((t1 - t0).total_seconds() / 86400, 1)
        except Exception:
            days_held = 1
        total_return = ((exit_value - entry_value + total_fees) / entry_value * 100) if entry_value > 0 else 0
        annual_apr = total_return * (365 / days_held) if days_held > 0 else 0
        closed_lps.append({
            'pair': (mp.get('token0') or '?') + '/' + (mp.get('token1') or '?'),
            'chain': mp.get('chain') or 'Manual',
            'entry_value': entry_value,
            'exit_value': exit_value,
            'range_lower': mp.get('range_lower'),
            'range_upper': mp.get('range_upper'),
            'total_fees': total_fees,
            'total_return_pct': total_return,
            'annual_apr': annual_apr,
            'days_held': int(days_held),
            'entry_date': str(mp.get('created_at', ''))[:10],
            'exit_date': str(mp.get('updated_at', ''))[:10],
        })
    
    # Also include closed manual hedges
    manual_hedges = conn.execute(
        f"SELECT * FROM hedge_positions WHERE is_active=0 {date_filter.replace('timestamp', 'updated_at')}"
    ).fetchall()
    for mh in manual_hedges:
        mh = dict(mh)
        closed_hedges.append({
            'market': mh.get('market') or '?',
            'direction': mh.get('direction') or '?',
            'entry_price': mh.get('entry_price') or 0,
            'exit_price': mh.get('current_price') or 0,
            'size_usd': mh.get('size_usd') or 0,
            'pnl_usd': mh.get('pnl_usd') or 0,
            'entry_date': str(mh.get('created_at', ''))[:10],
            'exit_date': str(mh.get('updated_at', ''))[:10],
        })
    
    conn.close()
    return jsonify({'closed_lps': closed_lps, 'closed_hedges': closed_hedges})


@app.route('/api/history/lp/<position_id>')
def api_history_lp(position_id):
    """Get LP position timeseries."""
    return jsonify([])


@app.route('/api/history/fees')
def api_history_fees():
    """Get fees timeseries."""
    return jsonify([])


@app.route('/api/history/runs')
def api_history_runs():
    """Get recent snapshot runs."""
    from src.storage.portfolio_db import get_connection
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/history/positions')
def api_history_positions():
    """Get all tracked LP positions."""
    return jsonify([])


@app.route('/api/history/latest')
def api_history_latest():
    """Get the latest snapshot timestamp."""
    from src.storage.portfolio_db import get_connection
    conn = get_connection()
    row = conn.execute(
        "SELECT MAX(timestamp) as latest FROM portfolio_snapshots WHERE status='completed'"
    ).fetchone()
    conn.close()
    return jsonify({"latest_snapshot": row['latest'] if row else None})


@app.route('/api/history/wallets')
def api_history_wallets():
    """Get wallets that have snapshot data, with labels."""
    from src.storage.portfolio_db import get_connection
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT wallet FROM portfolio_snapshots WHERE status='completed' ORDER BY wallet"
    ).fetchall()
    conn.close()
    
    wallets = []
    for r in rows:
        addr = r['wallet']
        label = get_wallet_label(addr)
        short = addr[:6] + '...' + addr[-4:]
        wallets.append({"address": addr, "label": label, "short": short})
    return jsonify(wallets)


# --- Backup / Export / Import ---

from flask import send_file
import shutil
import io
from src.storage.portfolio_db import get_db_path


@app.route('/api/backup/db', methods=['GET'])
def api_backup_db():
    """Download the SQLite database file."""
    db_path = get_db_path()
    if not os.path.exists(db_path):
        return jsonify({"error": "No database found"}), 404
    
    # Create a safe copy to avoid locking issues
    backup_path = db_path + '.backup'
    shutil.copy2(db_path, backup_path)
    try:
        return send_file(
            backup_path,
            mimetype='application/x-sqlite3',
            as_attachment=True,
            download_name='portfolio_backup.db'
        )
    finally:
        # Clean up backup copy after a delay (Flask sends async)
        pass


def api_import_db():
    """Import/restore a SQLite database file."""
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    db_path = get_db_path()

    # Save uploaded file to a temp location first
    temp_path = db_path + '.import'
    file.save(temp_path)

    # Validate it's a valid SQLite file with at least some expected tables
    try:
        import sqlite3
        conn = sqlite3.connect(temp_path)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t[0] for t in tables]
        conn.close()

        # Must have at least one of our core tables
        known_tables = ['portfolio_snapshots', 'token_snapshots', 'lp_snapshots',
                        'hedge_snapshots', 'lending_snapshots', 'lending_account_snapshots',
                        'market_snapshots', 'lp_positions', 'hedge_positions',
                        'manual_positions', 'manual_hedges',
                        'users', 'token_prices_daily']
        found = [t for t in known_tables if t in table_names]
        if not found:
            os.remove(temp_path)
            return jsonify({"error": "Not a valid portfolio database — no recognized tables found"}), 400
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({"error": f"Invalid SQLite file: {e}"}), 400

    # Replace current DB
    if os.path.exists(db_path):
        shutil.copy2(db_path, db_path + '.pre_import')  # safety backup
    shutil.move(temp_path, db_path)

    # Re-initialize to add any missing tables from newer schema
    from src.storage.portfolio_db import init_db
    init_db()

    return jsonify({
        "success": True,
        "message": f"Database imported ({len(found)} tables recognized: {', '.join(found)})"
    })


@app.route('/api/backup/config', methods=['GET'])
def api_export_config():
    """Export all config: .env variables + wallet config as JSON."""
    # Read .env
    env_data = {}
    if os.path.exists('.env'):
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    env_data[key.strip()] = value.strip().strip("'\"")
    
    # Read wallet config
    wallet_config = load_wallet_config()
    
    export = {
        "env": env_data,
        "wallets": wallet_config,
        "exported_at": datetime.now().isoformat()
    }
    
    buf = io.BytesIO()
    buf.write(json.dumps(export, indent=2).encode('utf-8'))
    buf.seek(0)
    
    return send_file(
        buf,
        mimetype='application/json',
        as_attachment=True,
        download_name='portfolio_config.json'
    )


@app.route('/api/backup/config', methods=['POST'])
def api_import_config():
    """Import config: restore .env variables + wallet config from JSON."""
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400
    
    try:
        data = json.loads(file.read().decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return jsonify({"error": f"Invalid JSON file: {e}"}), 400
    
    restored = []
    
    # Restore .env
    if 'env' in data and isinstance(data['env'], dict):
        env_path = '.env'
        # Read existing lines to preserve comments
        existing_lines = []
        existing_keys = set()
        if os.path.exists(env_path):
            # Backup first
            shutil.copy2(env_path, env_path + '.pre_import')
            with open(env_path, 'r') as f:
                existing_lines = f.readlines()
        
        # Update existing keys, track which ones we've seen
        new_lines = []
        for line in existing_lines:
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and '=' in stripped:
                key = stripped.split('=', 1)[0].strip()
                if key in data['env']:
                    new_lines.append(f"{key}={data['env'][key]}\n")
                    existing_keys.add(key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        # Add new keys not in existing file
        for key, value in data['env'].items():
            if key not in existing_keys:
                new_lines.append(f"{key}={value}\n")
        
        with open(env_path, 'w') as f:
            f.writelines(new_lines)
        
        # Update current process env
        for key, value in data['env'].items():
            os.environ[key] = value
        
        restored.append('environment variables')
    
    # Restore wallet config
    if 'wallets' in data and isinstance(data['wallets'], dict):
        # Backup first
        if os.path.exists(WALLET_CONFIG_FILE):
            shutil.copy2(WALLET_CONFIG_FILE, WALLET_CONFIG_FILE + '.pre_import')
        save_wallet_config(data['wallets'])
        restored.append('wallet configuration')
    
    if not restored:
        return jsonify({"error": "No valid data found in file"}), 400
    
    return jsonify({
        "success": True,
        "message": f"Restored: {', '.join(restored)}"
    })


if __name__ == '__main__':
    start_snapshot_scheduler()
    app.run(debug=True, port=5001)
else:
    # Running under gunicorn — start scheduler on import
    start_snapshot_scheduler()

