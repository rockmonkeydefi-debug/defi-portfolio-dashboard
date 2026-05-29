"""Flask web app for DeFi Portfolio Visualization."""

import sys
import os
import math
import time
import requests
import warnings
import re
import json
import traceback
from datetime import datetime
from dotenv import load_dotenv, set_key
from web3 import Web3
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import bcrypt
from functools import wraps

# Suppress urllib3 SSL warning
warnings.filterwarnings('ignore', message='.*OpenSSL.*')

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.connectors.uniswap_v3 import UniswapV3Connector, POOL_ABI, ERC20_ABI
from src.connectors.aerodrome_slipstream import (
    AerodromeSlipstreamConnector,
    POOL_ABI as AERO_POOL_ABI,
    POOL_FACTORY_ABI as AERO_FACTORY_ABI,
    POOL_FACTORY_ADDRESS as AERO_FACTORY_ADDRESS,
)
from src.connectors.aave_v3 import get_aave_positions
from src.connectors.zerion import (
    ZerionConnector,
    categorize_zerion_positions,
    map_zerion_token_to_app,
    map_zerion_lending_to_app,
    map_zerion_lp_to_app,
)
from src.models import Chain
from src.engines.telegram_service import (
    load_telegram_config, save_telegram_config, validate_telegram_config,
    mask_bot_token, send_telegram_message, build_notification_content,
)
from src.engines.range_optimizer import (
    discover_pools, run_optimization, load_regime_probabilities,
)

# Auto-create config files from examples on first run (local dev only;
# in Docker the entrypoint handles this via the config volume).
_env_path = os.getenv("DOTENV_PATH", ".env")
if not os.path.exists(_env_path) and os.path.exists(".env.example"):
    import shutil
    shutil.copy(".env.example", _env_path)
    print(f"Created {_env_path} from .env.example — edit it with your API keys")

_wc_path = os.getenv("WALLET_CONFIG_PATH", "wallet_config.json")
if not os.path.exists(_wc_path):
    with open(_wc_path, "w") as f:
        f.write("{}")

# Load environment variables from persistent config path (Docker) or local .env
ENV_FILE = os.getenv("DOTENV_PATH", ".env")
load_dotenv(ENV_FILE)

# Startup validation — warn about missing optional keys
_optional_keys = {
    "ZERION_API_KEY": "Zerion portfolio data",
    "ETHEREUM_RPC_URL": "Ethereum on-chain data",
    "ARBITRUM_RPC_URL": "Arbitrum on-chain data",
    "BASE_RPC_URL": "Base on-chain data",
    "ETHERSCAN_API_KEY": "Position age & collected fees",
    "FRED_API_KEY": "FRED macro indicators (US10Y, DXY, M2, Fed Funds)",
}
for _key, _desc in _optional_keys.items():
    if not os.getenv(_key):
        print(f"[Startup] Warning: {_key} not set — {_desc} will be unavailable")

app = Flask(__name__)
# Persistent secret key — generate once and save to .env if missing
_flask_secret = os.getenv("FLASK_SECRET_KEY")
if not _flask_secret:
    import secrets as _secrets
    _flask_secret = _secrets.token_hex(32)
    set_key(ENV_FILE, "FLASK_SECRET_KEY", _flask_secret)
app.secret_key = _flask_secret
app.permanent_session_lifetime = __import__('datetime').timedelta(hours=24)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB upload limit

# Inject git commit hash into all templates for static asset cache-busting
try:
    import subprocess as _sp
    _git_hash = _sp.check_output(['git', 'rev-parse', '--short', 'HEAD'], stderr=_sp.DEVNULL).decode().strip()
except Exception:
    _git_hash = '1'

@app.context_processor
def inject_static_version():
    return {'static_version': _git_hash}


@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    return response


@app.errorhandler(Exception)
def handle_exception(e):
    """Return JSON errors for API routes, HTML for others."""
    if request.path.startswith('/api/'):
        print(f"API error on {request.path}: {e}")
        return jsonify({"error": str(e)}), 500
    # Let non-API errors propagate to default Flask handler
    raise e


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
WALLET_CONFIG_FILE = os.getenv("WALLET_CONFIG_PATH", "wallet_config.json")

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
    """Get wallet addresses from config file, excluding hidden wallets."""
    config = load_wallet_config()
    return [addr for addr, info in config.items() if not info.get("hidden", False)]

def get_wallet_label(address):
    """Get label for a wallet address."""
    config = load_wallet_config()
    return config.get(address, {}).get('label', address[:10] + '...')

def save_wallet_addresses(addresses):
    """Save wallet addresses to .env file (for backward compatibility)."""
    wallet_str = ",".join(addresses)
    set_key(ENV_FILE, "WALLET_ADDRESS", wallet_str)
    
    # Reload environment variables
    load_dotenv(ENV_FILE)

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
            for attempt in range(3):
                try:
                    url = "https://coins.llama.fi/prices/current/coingecko:bitcoin"
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        price = response.json().get("coins", {}).get("coingecko:bitcoin", {}).get("price", 0.0)
                        if price > 0:
                            _price_cache[cache_key] = price
                            return price
                    if response.status_code == 429 and attempt < 2:
                        import time
                        time.sleep(2)
                        continue
                except Exception as e:
                    if attempt < 2:
                        import time
                        time.sleep(1)
                    else:
                        print(f"Price fetch failed for BTC: {e}")
                    pass
                break
        
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
            except requests.exceptions.RequestException as e:
                print(f"Price fetch failed for {symbol} ({chain}:{address}): {e}")
        _price_cache[cache_key] = 0.0
        return 0.0
        
    except Exception as e:
        print(f"Unexpected error in get_token_price_usd({symbol}): {e}")
        _price_cache[cache_key] = 0.0
        return 0.0




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
    except (ZeroDivisionError, OverflowError, ValueError) as e:
        print(f"Token amount calculation error: {e}")
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
        # Arbitrum: Alchemy free tier rejects getLogs for large ranges — skip RPC fallback
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

        # Fallback: RPC log scanning (Ethereum only — Arbitrum/Base RPCs reject large getLogs)
        if chain_id == 42161:
            print(f"Skipping RPC fallback for Arbitrum (getLogs not supported on free tier)")
            return 0.0, 0.0

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
            
            fractional_days = age_days + age_hours / 24.0
            if fractional_days > 0.04 and total_value_usd > 0:
                # Daily earnings = total earned fees / fractional days
                daily_earnings = total_earned_fees_usd / fractional_days
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
            
            fractional_days = age_days + age_hours / 24.0
            if fractional_days > 0.04 and total_value_usd > 0:
                # Daily earnings = total earned fees / fractional days
                daily_earnings = total_earned_fees_usd / fractional_days
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


def check_aerodrome_slipstream_lp_position(
    connector: AerodromeSlipstreamConnector,
    token_id: int,
) -> dict | None:
    """Check a single Aerodrome Slipstream LP position and return enriched data.

    Mirrors check_lp_position() for Uniswap V3, but adapted for Aerodrome Slipstream's
    NonfungiblePositionManager interface:
      - positions() returns tickSpacing at index 4 (not fee)
      - Pools are resolved via PoolFactory.getPool(token0, token1, tickSpacing)
      - Pool's fee() is dynamic, set by SwapFeeModule

    Returns None if liquidity is 0 or on any error.
    """
    try:
        pm = connector.position_manager
        position_data = pm.functions.positions(token_id).call()

        # position_data layout: (nonce, operator, token0, token1, tickSpacing,
        #                        tickLower, tickUpper, liquidity,
        #                        feeGrowthInside0LastX128, feeGrowthInside1LastX128,
        #                        tokensOwed0, tokensOwed1)
        token0 = position_data[2]
        token1 = position_data[3]
        tick_spacing = position_data[4]
        tick_lower = position_data[5]
        tick_upper = position_data[6]
        liquidity = position_data[7]
        fee_growth_inside0_last = position_data[8]
        fee_growth_inside1_last = position_data[9]
        tokens_owed0 = position_data[10]
        tokens_owed1 = position_data[11]

        if liquidity == 0:
            return None

        # Token metadata
        token0_contract = connector.w3.eth.contract(
            address=Web3.to_checksum_address(token0), abi=ERC20_ABI
        )
        token1_contract = connector.w3.eth.contract(
            address=Web3.to_checksum_address(token1), abi=ERC20_ABI
        )
        token0_symbol = token0_contract.functions.symbol().call()
        token1_symbol = token1_contract.functions.symbol().call()
        token0_decimals = token0_contract.functions.decimals().call()
        token1_decimals = token1_contract.functions.decimals().call()

        # Resolve pool via Aerodrome factory (takes tickSpacing, not fee)
        pool_address = connector.pool_factory.functions.getPool(
            token0, token1, tick_spacing
        ).call()
        pool_contract = connector.w3.eth.contract(
            address=Web3.to_checksum_address(pool_address), abi=AERO_POOL_ABI
        )

        # Current pool state
        slot0 = pool_contract.functions.slot0().call()
        sqrt_price_x96 = slot0[0]
        current_tick = slot0[1]

        # Dynamic fee (may differ from Uniswap V3's fixed tiers)
        try:
            fee_raw = pool_contract.functions.fee().call()  # in hundredths of bps
        except Exception:
            fee_raw = 0

        # Fee growth globals
        fee_growth_global_0 = pool_contract.functions.feeGrowthGlobal0X128().call()
        fee_growth_global_1 = pool_contract.functions.feeGrowthGlobal1X128().call()

        # Tick data — Aerodrome returns 10 fields vs Uniswap's 8.
        # Fee growth outside is at indices 3,4 instead of 2,3.
        tick_lower_data = pool_contract.functions.ticks(tick_lower).call()
        tick_upper_data = pool_contract.functions.ticks(tick_upper).call()
        fee_growth_outside_lower_0 = tick_lower_data[3]
        fee_growth_outside_lower_1 = tick_lower_data[4]
        fee_growth_outside_upper_0 = tick_upper_data[3]
        fee_growth_outside_upper_1 = tick_upper_data[4]

        # Uncollected fees — same math as Uniswap V3 (shared helper)
        uncollected_fees_0, uncollected_fees_1 = calculate_uncollected_fees(
            liquidity, tick_lower, tick_upper, current_tick,
            fee_growth_global_0, fee_growth_global_1,
            fee_growth_outside_lower_0, fee_growth_outside_lower_1,
            fee_growth_outside_upper_0, fee_growth_outside_upper_1,
            fee_growth_inside0_last, fee_growth_inside1_last
        )

        # Collected fees from on-chain Collect events
        collected_fees_0, collected_fees_1 = get_collected_fees_from_events(
            connector.w3,
            connector.position_manager_address,
            token_id,
            token0_decimals,
            token1_decimals,
        )

        # Position creation time
        creation_timestamp = get_position_creation_time(
            connector.w3,
            connector.position_manager_address,
            token_id,
            pool_address,
            tick_lower,
            tick_upper,
        )

        # Price math — identical to Uniswap V3
        sqrt_price = sqrt_price_x96 / (2 ** 96)
        current_price_raw = sqrt_price ** 2
        decimal_adjustment = 10 ** (token0_decimals - token1_decimals)
        current_price_adjusted = current_price_raw * decimal_adjustment

        price_lower = (1.0001 ** tick_lower) * decimal_adjustment
        price_upper = (1.0001 ** tick_upper) * decimal_adjustment

        amount0, amount1 = calculate_token_amounts(
            liquidity, tick_lower, tick_upper, current_tick,
            sqrt_price_x96, token0_decimals, token1_decimals,
        )

        price0_usd = get_token_price_usd(token0_symbol, token0, "base")
        price1_usd = get_token_price_usd(token1_symbol, token1, "base")
        value0_usd = amount0 * price0_usd
        value1_usd = amount1 * price1_usd
        total_value_usd = value0_usd + value1_usd

        # Fee values (include any tokensOwed carried on the NFT)
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

        # Resolve gauge for this pool — caller will use it to fetch pending AERO
        # for staked positions (it already knows which wallet owns the deposit
        # because it discovered this tokenId via get_staked_token_ids).
        gauge_address = connector.gauge_for_pool(pool_address)

        total_earned_fees_0 = collected_fees_0 + fees_owed0
        total_earned_fees_1 = collected_fees_1 + fees_owed1
        total_earned_fees_usd = total_collected_fees_usd + total_fees_usd

        # Age & APR (NOTE: APR recomputed by caller after AERO is folded in)
        current_time = datetime.now().timestamp()
        age_days = None
        age_hours = None
        daily_apr = None
        monthly_apr = None
        daily_earnings = None

        if creation_timestamp and creation_timestamp > 0:
            age_seconds = current_time - creation_timestamp
            age_days = int(age_seconds // 86400)
            age_hours = int((age_seconds % 86400) // 3600)
            fractional_days = age_days + age_hours / 24.0
            if fractional_days > 0.04 and total_value_usd > 0:
                daily_earnings = total_earned_fees_usd / fractional_days
                daily_apr = (daily_earnings / total_value_usd) * 100
                monthly_apr = daily_apr * 30

        in_range = tick_lower <= current_tick <= tick_upper

        # fee_raw is in 1/100 bps; convert to percent (e.g. 500 -> 0.05%)
        fee_tier_pct = (fee_raw / 10000) if fee_raw else 0

        return {
            "token_id": token_id,
            "chain": "base",
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
            "fee_tier": fee_tier_pct,
            "current_price": current_price_adjusted,
            "price_lower": price_lower,
            "price_upper": price_upper,
            "tick_spacing": tick_spacing,
            # Staking-reward placeholders — populated by caller when the position
            # is staked (caller already knows which wallet owns the staked deposit).
            "gauge_address": gauge_address,
            "reward_symbol": "AERO",
            "reward_decimals": 18,
            "reward_address": "",
            "reward_pending": 0.0,
            "reward_pending_usd": 0.0,
            "reward_price_usd": 0.0,
            "reward_claimed": 0.0,
            "reward_claimed_usd": 0.0,
            "reward_total_usd": 0.0,
        }

    except Exception as e:
        print(f"Aerodrome Slipstream position {token_id} fetch failed: {e}")
        return None


def apply_aerodrome_rewards(
    connector: AerodromeSlipstreamConnector,
    position_data: dict,
    wallet: str,
) -> None:
    """Fill in AERO staking-reward fields on an Aerodrome position dict (in place).

    Reads:
      - gauge.earned(wallet, tokenId) for currently-pending AERO
      - rewardToken() + ERC-20 metadata for the reward token (AERO on Base)
      - DB high-water-mark for claimed AERO (lp_aero_claimed_total field;
        snapshot_service uses drop-detection to grow this over time)

    Folds reward USD into total_earned_fees_usd / total_fees_usd so the existing
    APR math (later in the pipeline) treats AERO like swap fees.
    """
    gauge_address = position_data.get("gauge_address")
    token_id = position_data.get("token_id")
    if not gauge_address or token_id is None:
        return

    pending_raw = connector.get_pending_aero(gauge_address, wallet, token_id)
    if pending_raw <= 0 and not position_data.get("reward_claimed"):
        return  # not staked, nothing to add

    reward_token_addr = connector.get_reward_token(gauge_address) or ""
    reward_symbol = "AERO"
    reward_decimals = 18
    if reward_token_addr:
        try:
            erc20 = connector.w3.eth.contract(
                address=Web3.to_checksum_address(reward_token_addr), abi=ERC20_ABI
            )
            reward_symbol = erc20.functions.symbol().call() or "AERO"
            reward_decimals = int(erc20.functions.decimals().call() or 18)
        except Exception:
            pass

    pending = pending_raw / (10 ** reward_decimals)
    reward_price_usd = get_token_price_usd(reward_symbol, reward_token_addr, "base")
    pending_usd = pending * reward_price_usd

    # Claimed history: read high-water-mark for the AERO reward leg.
    # snapshot_service grows this when pending drops between snapshots.
    claimed = 0.0
    claimed_usd = 0.0
    try:
        from src.storage.portfolio_db import get_lp_aero_claimed
        claimed = get_lp_aero_claimed(1, str(token_id))
        claimed_usd = claimed * reward_price_usd
    except Exception:
        pass

    total_reward_usd = pending_usd + claimed_usd

    position_data["reward_symbol"] = reward_symbol
    position_data["reward_decimals"] = reward_decimals
    position_data["reward_address"] = reward_token_addr
    position_data["reward_pending"] = pending
    position_data["reward_pending_usd"] = pending_usd
    position_data["reward_price_usd"] = reward_price_usd
    position_data["reward_claimed"] = claimed
    position_data["reward_claimed_usd"] = claimed_usd
    position_data["reward_total_usd"] = total_reward_usd

    # Fold reward USD into the totals — APR math reads total_earned_fees_usd.
    position_data["total_fees_usd"] = (position_data.get("total_fees_usd") or 0) + pending_usd
    position_data["total_collected_fees_usd"] = (
        position_data.get("total_collected_fees_usd") or 0
    ) + claimed_usd
    position_data["total_earned_fees_usd"] = (
        position_data.get("total_earned_fees_usd") or 0
    ) + total_reward_usd


from src.models import STABLECOIN_SYMBOLS as STABLECOINS


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
    
    # Load wallet config once for the entire function
    _wallet_config = load_wallet_config()
    
    def _label(addr):
        return _wallet_config.get(addr, {}).get('label', addr[:10] + '...')
    
    def _is_xpub(addr):
        return _wallet_config.get(addr, {}).get("type") == "bitcoin_xpub"
    
    evm_wallets = [w for w in WALLET_ADDRESSES if not _is_xpub(w)]
    xpub_wallets = [w for w in WALLET_ADDRESSES if _is_xpub(w)]
    
    def _btc_price_from_tokens(tokens):
        """Fallback: derive BTC price from WBTC/cbBTC in token list."""
        for t in tokens:
            if t.get("symbol") in ("WBTC", "cbBTC") and t.get("price_usd", 0) > 0:
                return t["price_usd"]
        return 0.0
    
    all_tokens = []
    all_lp_positions = []
    all_lending_positions = []
    all_gmx_positions = []
    total_tokens_value = 0.0
    total_lp_value = 0.0
    api_failures = []
    zerion_lp_groups = {}  # group_id -> {positions, wallet, wallet_label}
    
    zerion = ZerionConnector()
    zerion_configured = zerion.is_configured()
    zerion_not_configured_logged = False
    
    for wallet_index, wallet in enumerate(evm_wallets):
        wallet_label = _label(wallet)
        
        if zerion_configured:
            try:
                # Add inter-call delay for free tier rate limiting (skip for first wallet)
                if wallet_index > 0:
                    time.sleep(1)
                
                positions = zerion.get_wallet_positions(wallet)
                categorized = categorize_zerion_positions(positions)
                
                # Map tokens
                for pos in categorized['tokens']:
                    token = map_zerion_token_to_app(pos, wallet, wallet_label)
                    all_tokens.append(token)
                
                # Group lending positions by (chain, protocol) using group_id
                lending_groups = {}
                for pos in categorized['lending']:
                    attrs = pos.get("attributes", {})
                    group_id = attrs.get("group_id")
                    if group_id:
                        key = group_id
                    else:
                        chain_id = (
                            pos.get("relationships", {})
                            .get("chain", {})
                            .get("data", {})
                            .get("id", "unknown")
                        )
                        protocol = attrs.get("protocol", "unknown")
                        key = f"{chain_id}:{protocol}"
                    lending_groups.setdefault(key, []).append(pos)
                
                for group_key, group_positions in lending_groups.items():
                    lending = map_zerion_lending_to_app(group_positions, wallet, wallet_label)
                    all_lending_positions.append(lending)
                
                # Collect LP positions grouped by group_id for later processing
                for pos in categorized['lp_basic']:
                    attrs = pos.get("attributes", {})
                    group_id = attrs.get("group_id") or pos.get("id", f"unknown_{len(zerion_lp_groups)}")
                    if group_id not in zerion_lp_groups:
                        zerion_lp_groups[group_id] = {
                            "positions": [],
                            "wallet": wallet,
                            "wallet_label": wallet_label,
                        }
                    zerion_lp_groups[group_id]["positions"].append(pos)
                
            except Exception as e:
                print(f"Error fetching Zerion data for {wallet}: {e}")
                api_failures.append(f"zerion:{wallet}")
        else:
            if not zerion_not_configured_logged:
                api_failures.append("zerion:not_configured")
                zerion_not_configured_logged = True
    
    # Enrich Aave lending positions with on-chain data (health factor, APYs, liquidation)
    AAVE_NAMES = {"aave v3", "aave", "aave_v3", "aave-v3"}
    LENDING_CHAIN_TO_AAVE = {"ethereum": "ethereum", "arbitrum": "arbitrum", "base": "base"}
    enriched_lending = []
    aave_fetched = set()  # track (wallet, chain) already fetched

    for pos in all_lending_positions:
        protocol = (pos.get("protocol_name") or "").lower()
        chain_id = pos.get("chain", "")
        wallet = pos.get("wallet", "")
        aave_chain = LENDING_CHAIN_TO_AAVE.get(chain_id)

        if protocol in AAVE_NAMES and aave_chain and wallet:
            fetch_key = (wallet, aave_chain)
            if fetch_key in aave_fetched:
                continue  # already enriched for this wallet+chain
            aave_fetched.add(fetch_key)
            try:
                from src.models import get_web3, CHAIN_DISPLAY_NAMES
                w3 = get_web3(aave_chain)
                if w3:
                    aave_data = get_aave_positions(w3, wallet, aave_chain)
                    if aave_data:
                        # Add price info for liquidation calculation
                        for s in aave_data.get('supplied', []):
                            s['price_usd'] = get_token_price_usd(s['symbol'], s.get('token_address'), aave_chain)
                            s['value_usd'] = s['balance'] * s['price_usd']
                        for b in aave_data.get('borrowed', []):
                            b['price_usd'] = get_token_price_usd(b['symbol'], b.get('token_address'), aave_chain)
                            b['value_usd'] = b['balance'] * b['price_usd']

                        chain_name = CHAIN_DISPLAY_NAMES.get(aave_chain, aave_chain)
                        liq_price = _calc_aave_liquidation_price(aave_data)
                        enriched_lending.append({
                            "chain": aave_chain,
                            "chain_name": chain_name,
                            "protocol_name": "Aave V3",
                            "total_collateral_usd": aave_data["total_collateral_usd"],
                            "total_debt_usd": aave_data["total_debt_usd"],
                            "available_borrows_usd": aave_data["available_borrows_usd"],
                            "ltv": aave_data["ltv"],
                            "max_ltv": aave_data.get("max_ltv", 0),
                            "liquidation_threshold": aave_data["liquidation_threshold"],
                            "health_factor": aave_data["health_factor"],
                            "supplied": aave_data["supplied"],
                            "borrowed": aave_data["borrowed"],
                            "wallet": wallet,
                            "wallet_label": _label(wallet),
                            "liquidation_price": liq_price,
                        })
                        continue
            except Exception as e:
                print(f"Error enriching Aave data for {wallet} on {aave_chain}: {e}")
                api_failures.append(f"aave_enrich:{aave_chain}:{wallet[:8]}")
        # Keep Zerion data as fallback for non-Aave or failed enrichment
        enriched_lending.append(pos)

    all_lending_positions = enriched_lending

    # --- Check for previously-seen Aave positions that Zerion no longer reports ---
    # If a (wallet, chain) had lending snapshots before but Zerion didn't mention it
    # this time, do an on-chain check. If confirmed closed (collateral ≈ 0), write a
    # zero-balance snapshot so the DB reflects the closure.
    try:
        from src.storage.portfolio_db import get_connection as _get_conn
        _conn = _get_conn()
        prev_lending = _conn.execute("""
            SELECT DISTINCT wallet, chain FROM lending_account_snapshots
            WHERE total_collateral_usd > 1
        """).fetchall()
        _conn.close()

        for row in prev_lending:
            pw, pc = row['wallet'], row['chain']
            if (pw, pc) in aave_fetched:
                continue  # already checked via Zerion path
            # Zerion didn't report this — verify on-chain
            try:
                from src.models import get_web3
                w3 = get_web3(pc)
                if w3:
                    aave_data = get_aave_positions(w3, pw, pc)
                    coll = aave_data.get('total_collateral_usd', 0) if aave_data else 0
                    if coll < 1:
                        print(f"[Lending] Position {pw[:10]}... on {pc} confirmed closed (collateral ${coll:.2f})")
                    else:
                        # Still active — add to results
                        from src.models import CHAIN_DISPLAY_NAMES
                        for s in aave_data.get('supplied', []):
                            s['price_usd'] = get_token_price_usd(s['symbol'], s.get('token_address'), pc)
                            s['value_usd'] = s['balance'] * s['price_usd']
                        for b in aave_data.get('borrowed', []):
                            b['price_usd'] = get_token_price_usd(b['symbol'], b.get('token_address'), pc)
                            b['value_usd'] = b['balance'] * b['price_usd']
                        liq_price = _calc_aave_liquidation_price(aave_data)
                        all_lending_positions.append({
                            "chain": pc,
                            "chain_name": CHAIN_DISPLAY_NAMES.get(pc, pc),
                            "protocol_name": "Aave V3",
                            "total_collateral_usd": aave_data["total_collateral_usd"],
                            "total_debt_usd": aave_data["total_debt_usd"],
                            "available_borrows_usd": aave_data.get("available_borrows_usd", 0),
                            "ltv": aave_data["ltv"],
                            "max_ltv": aave_data.get("max_ltv", 0),
                            "liquidation_threshold": aave_data["liquidation_threshold"],
                            "health_factor": aave_data["health_factor"],
                            "supplied": aave_data["supplied"],
                            "borrowed": aave_data["borrowed"],
                            "wallet": pw,
                            "wallet_label": _label(pw),
                            "liquidation_price": liq_price,
                        })
                        print(f"[Lending] Position {pw[:10]}... on {pc} still active (${coll:,.0f}), added from on-chain")
                    aave_fetched.add((pw, pc))
            except Exception as e:
                print(f"[Lending] Could not verify {pw[:10]}... on {pc}: {e}")
    except Exception as e:
        print(f"[Lending] Stale position check failed: {e}")
    
    # Process LP positions discovered via Zerion
    # For Uniswap V3 / Aerodrome Slipstream: enrich with on-chain data (fees, range, APR)
    # For other protocols: use Zerion data as-is
    UNISWAP_V3_NAMES = {"uniswap v3", "uniswap_v3", "uniswap-v3"}
    AERODROME_SLIPSTREAM_NAMES = {
        "aerodrome v3", "aerodrome_v3", "aerodrome-v3",
        "aerodrome slipstream", "aerodrome cl",
    }
    CHAIN_TO_ENUM = {"ethereum": Chain.ETHEREUM, "arbitrum": Chain.ARBITRUM, "base": Chain.BASE}
    uniswap_v3_fetched = set()  # track (wallet, chain) pairs already fetched on-chain
    uniswap_v3_onchain_count = {}  # (wallet, chain) -> number of positions found on-chain
    uniswap_v3_zerion_seen = {}  # (wallet, chain) -> number of Zerion groups processed
    aero_fetched = set()
    aero_onchain_count = {}
    aero_zerion_seen = {}
    aero_seen_tids: dict = {}      # (wallet, "base") -> set of tokenIds already enriched
    aero_connector_cache: dict = {}  # (wallet, "base") -> AerodromeSlipstreamConnector

    for group_id, group_data in zerion_lp_groups.items():
        group_positions = group_data["positions"]
        wallet = group_data["wallet"]
        wallet_label = group_data["wallet_label"]

        first_attrs = group_positions[0].get("attributes", {})
        app_meta = first_attrs.get("application_metadata", {})
        protocol_name = (app_meta.get("name") or first_attrs.get("protocol", "")).lower()
        chain_id = (
            group_positions[0].get("relationships", {})
            .get("chain", {})
            .get("data", {})
            .get("id", "unknown")
        )
        chain_enum = CHAIN_TO_ENUM.get(chain_id)

        # Try on-chain enrichment for Uniswap V3 positions
        if protocol_name in UNISWAP_V3_NAMES and chain_enum is not None:
            fetch_key = (wallet, chain_id)
            if fetch_key in uniswap_v3_fetched:
                # Already fetched on-chain for this wallet+chain.
                # If Zerion reports more groups than on-chain positions found,
                # the extras are managed by contracts (e.g. Krystal) — use Zerion data.
                uniswap_v3_zerion_seen[fetch_key] = uniswap_v3_zerion_seen.get(fetch_key, 1) + 1
                if uniswap_v3_zerion_seen[fetch_key] > uniswap_v3_onchain_count.get(fetch_key, 0):
                    lp_data = map_zerion_lp_to_app(group_positions, wallet, wallet_label)
                    all_lp_positions.append(lp_data)
                    total_lp_value += lp_data["total_value_usd"]
                continue
            uniswap_v3_fetched.add(fetch_key)
            uniswap_v3_zerion_seen[fetch_key] = 1  # this is the first group
            try:
                connector = UniswapV3Connector(chain=chain_enum)
                raw_positions = connector.get_positions(wallet, chain_enum.value)
                uniswap_v3_onchain_count[fetch_key] = len(raw_positions)
                for raw_pos in raw_positions:
                    try:
                        position_data = check_lp_position(connector, raw_pos.token_id, chain_enum)
                        if position_data:
                            position_data['wallet'] = wallet
                            position_data['wallet_label'] = wallet_label
                            position_data['protocol'] = 'uniswap_v3'
                            all_lp_positions.append(position_data)
                            total_lp_value += position_data["total_value_usd"]
                    except Exception as e:
                        print(f"Error fetching LP position {raw_pos.token_id} on {chain_enum.value}: {e}")
                        api_failures.append(f"lp:{raw_pos.token_id}")
            except Exception as e:
                # Fallback to Zerion data if on-chain fetch fails
                print(f"On-chain Uniswap V3 fetch failed for {wallet} on {chain_id}, using Zerion data: {e}")
                lp_data = map_zerion_lp_to_app(group_positions, wallet, wallet_label)
                all_lp_positions.append(lp_data)
                total_lp_value += lp_data["total_value_usd"]
        elif protocol_name in AERODROME_SLIPSTREAM_NAMES and chain_id == "base":
            # Aerodrome Slipstream is Base-only; Zerion calls it "Aerodrome V3"
            # Staked positions are owned by the gauge, so we combine
            #   wallet-owned NFTs (positionManager.balanceOf)
            # + gauge-staked NFTs discovered via Zerion's pool_address per group.
            #
            # Discovery is keyed by (wallet, "base") so we only enumerate once per wallet,
            # but we still walk each group to collect pool addresses for gauge lookup.
            fetch_key = (wallet, "base")

            # Collect pool addresses Zerion reported for this group
            group_pools = {
                (p.get("attributes", {}).get("pool_address") or "").lower()
                for p in group_positions
                if p.get("attributes", {}).get("pool_address")
            }
            group_pools.discard("")

            if fetch_key in aero_fetched:
                # Already enriched this wallet — but this is a NEW group for the same
                # wallet (different pool). Look up its staked tokenIds and enrich them.
                try:
                    a_connector = aero_connector_cache.get(fetch_key)
                    if a_connector is None:
                        raise RuntimeError("connector missing from cache")
                    new_tids = []
                    for pa in group_pools:
                        new_tids.extend(a_connector.get_staked_token_ids(wallet, pa))
                    new_tids = [t for t in new_tids if t not in aero_seen_tids[fetch_key]]
                    aero_seen_tids[fetch_key].update(new_tids)
                    enriched_any = False
                    for tid in new_tids:
                        position_data = check_aerodrome_slipstream_lp_position(a_connector, tid)
                        if position_data:
                            position_data['wallet'] = wallet
                            position_data['wallet_label'] = wallet_label
                            position_data['protocol'] = 'aerodrome_slipstream'
                            position_data['protocol_display'] = 'Aerodrome Slipstream'
                            apply_aerodrome_rewards(a_connector, position_data, wallet)
                            all_lp_positions.append(position_data)
                            total_lp_value += position_data["total_value_usd"]
                            enriched_any = True
                    if not enriched_any:
                        # Fall back to Zerion data so the position still appears
                        lp_data = map_zerion_lp_to_app(group_positions, wallet, wallet_label)
                        all_lp_positions.append(lp_data)
                        total_lp_value += lp_data["total_value_usd"]
                except Exception as e:
                    print(f"Aerodrome staked enrichment failed for additional group: {e}")
                    lp_data = map_zerion_lp_to_app(group_positions, wallet, wallet_label)
                    all_lp_positions.append(lp_data)
                    total_lp_value += lp_data["total_value_usd"]
                continue

            aero_fetched.add(fetch_key)
            aero_seen_tids[fetch_key] = set()
            try:
                a_connector = AerodromeSlipstreamConnector()
                aero_connector_cache[fetch_key] = a_connector

                # Wallet-owned NFTs (unstaked)
                raw_positions = a_connector.get_positions(wallet, "base")
                token_ids = [r.token_id for r in raw_positions]

                # Gauge-staked NFTs for this group's pool(s)
                for pa in group_pools:
                    token_ids.extend(a_connector.get_staked_token_ids(wallet, pa))

                # Dedupe while preserving order
                seen = set()
                unique_ids = []
                for t in token_ids:
                    if t not in seen:
                        seen.add(t)
                        unique_ids.append(t)
                aero_seen_tids[fetch_key].update(unique_ids)
                aero_onchain_count[fetch_key] = len(unique_ids)

                enriched_any = False
                for tid in unique_ids:
                    try:
                        position_data = check_aerodrome_slipstream_lp_position(a_connector, tid)
                        if position_data:
                            position_data['wallet'] = wallet
                            position_data['wallet_label'] = wallet_label
                            position_data['protocol'] = 'aerodrome_slipstream'
                            position_data['protocol_display'] = 'Aerodrome Slipstream'
                            apply_aerodrome_rewards(a_connector, position_data, wallet)
                            all_lp_positions.append(position_data)
                            total_lp_value += position_data["total_value_usd"]
                            enriched_any = True
                    except Exception as e:
                        print(f"Error fetching Aerodrome LP position {tid}: {e}")
                        api_failures.append(f"lp:{tid}")

                if not enriched_any:
                    # No on-chain match (e.g. RPC failures) — fall back to Zerion data
                    lp_data = map_zerion_lp_to_app(group_positions, wallet, wallet_label)
                    all_lp_positions.append(lp_data)
                    total_lp_value += lp_data["total_value_usd"]
            except Exception as e:
                print(f"On-chain Aerodrome Slipstream fetch failed for {wallet}, using Zerion data: {e}")
                lp_data = map_zerion_lp_to_app(group_positions, wallet, wallet_label)
                all_lp_positions.append(lp_data)
                total_lp_value += lp_data["total_value_usd"]
        else:
            # Other protocols — use Zerion data directly
            lp_data = map_zerion_lp_to_app(group_positions, wallet, wallet_label)
            all_lp_positions.append(lp_data)
            total_lp_value += lp_data["total_value_usd"]
    
    # Enrich LP positions missing age data using Zerion transactions API
    # For on-chain positions we have token_id — match by NFT token_id in transaction transfers
    # Group by (wallet, chain) for batched API calls
    if zerion_configured:
        age_needed: dict = {}  # (wallet, chain) -> list of (index, token_id)
        for idx, lp in enumerate(all_lp_positions):
            if lp.get("age_days") is None and lp.get("wallet") and lp.get("chain"):
                tid = lp.get("token_id")
                if tid is not None:
                    key = (lp["wallet"], lp["chain"])
                    age_needed.setdefault(key, []).append((idx, str(tid)))

        for (wallet, chain), positions_info in age_needed.items():
            if not positions_info:
                continue
            try:
                time.sleep(1)  # Rate limit
                txns = zerion.get_wallet_transactions(
                    wallet,
                    chain_ids=chain,
                    operation_types="deposit,mint",
                    sort="mined_at",  # oldest first
                    limit=100,
                )

                # Build a token_id -> {mined_at, entry_value} map from transaction transfers
                tid_to_mint: dict = {}
                for tx in txns:
                    tx_attrs = tx.get("attributes", {})
                    mined_at = tx_attrs.get("mined_at", "")
                    if not mined_at:
                        continue
                    transfers = tx_attrs.get("transfers", [])
                    # Check if this transaction involves an NFT we care about
                    tx_nft_tid = None
                    for tr in transfers:
                        nft = tr.get("nft_info", {})
                        nft_tid = str(nft.get("token_id", ""))
                        if nft_tid:
                            tx_nft_tid = nft_tid
                            break
                    if tx_nft_tid and tx_nft_tid not in tid_to_mint:
                        # Sum the USD value of fungible transfers (the deposited tokens)
                        entry_value = 0.0
                        for tr in transfers:
                            if tr.get("nft_info"):
                                continue  # skip the NFT transfer itself
                            tr_value = abs(tr.get("value") or 0.0)
                            entry_value += tr_value
                        tid_to_mint[tx_nft_tid] = {"mined_at": mined_at, "entry_value": entry_value}

                # Apply to positions
                for idx, tid in positions_info:
                    mint_data = tid_to_mint.get(tid)
                    if not mint_data:
                        continue
                    earliest_ts = mint_data["mined_at"]
                    try:
                        from datetime import datetime as dt
                        ts = dt.fromisoformat(earliest_ts.replace("Z", "+00:00"))
                        creation_epoch = ts.timestamp()
                        age_seconds = datetime.now().timestamp() - creation_epoch
                        age_days = int(age_seconds // 86400)
                        age_hours = int((age_seconds % 86400) // 3600)

                        lp = all_lp_positions[idx]
                        lp["age_days"] = age_days
                        lp["age_hours"] = age_hours

                        # Entry value from the mint transaction
                        if mint_data["entry_value"] > 0:
                            lp["entry_value_usd"] = mint_data["entry_value"]

                        print(f"Zerion txns: Position #{tid} on {chain} created {age_days}d ago")
                    except Exception as e:
                        print(f"Error parsing Zerion timestamp for #{tid}: {e}")

            except Exception as e:
                print(f"Error fetching Zerion transactions for {wallet[:8]} on {chain}: {e}")

    # Fetch GMX V2 perpetual positions (Arbitrum only)
    from src.models import get_web3 as _get_web3
    arb_w3 = _get_web3("arbitrum")
    if arb_w3:
        for wallet in evm_wallets:
            try:
                from src.connectors.gmx_v2 import get_gmx_positions
                gmx_pos = get_gmx_positions(arb_w3, wallet)
                for p in gmx_pos:
                    p['wallet'] = wallet
                    p['wallet_label'] = _label(wallet)
                    current_price = get_token_price_usd(p['index_symbol'], None, "arbitrum")
                    if current_price == 0:
                        cg_map = {"WETH": "ETH", "WBTC": "BTC", "BTC": "BTC", "ETH": "ETH"}
                        mapped = cg_map.get(p['index_symbol'], p['index_symbol'])
                        if mapped == "BTC":
                            current_price = get_token_price_usd("BTC", None, "bitcoin")
                        else:
                            current_price = get_token_price_usd(mapped, None, "ethereum")
                    # Fallback: derive from Zerion token prices already fetched
                    if current_price == 0:
                        if p['index_symbol'] in ("BTC", "WBTC"):
                            current_price = _btc_price_from_tokens(all_tokens)
                        else:
                            for t in all_tokens:
                                if t.get("symbol") == p['index_symbol'] and t.get("price_usd", 0) > 0:
                                    current_price = t["price_usd"]
                                    break
                    p['current_price'] = current_price
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
                    print(f"GMX: Found {len(gmx_pos)} positions for {_label(wallet)}")
            except Exception as e:
                print(f"Error fetching GMX positions: {e}")

    # Fetch Bitcoin balances from xpub wallets
    for wallet_key in xpub_wallets:
        try:
            from src.connectors.bitcoin import get_btc_balance_for_xpub
            print(f"Fetching BTC balance for xpub wallet: {_label(wallet_key)}")
            btc_data = get_btc_balance_for_xpub(wallet_key)
            btc_balance = btc_data["total_btc"]
            if btc_balance > 0:
                btc_price = get_token_price_usd("BTC", None, "bitcoin")
                # Fallback: derive from WBTC/cbBTC price already fetched via Zerion
                if btc_price == 0:
                    btc_price = _btc_price_from_tokens(all_tokens)
                btc_value = btc_balance * btc_price
                all_tokens.append({
                    "chain": "Bitcoin",
                    "symbol": "BTC",
                    "balance": btc_balance,
                    "value_usd": btc_value,
                    "price_usd": btc_price,
                    "wallet": wallet_key,
                    "wallet_label": _label(wallet_key)
                })
                total_tokens_value += btc_value
                print(f"BTC balance: {btc_balance:.8f} BTC (${btc_value:.2f}), {btc_data['addresses_used']} addresses used")
        except Exception as e:
            print(f"Error fetching BTC balance: {e}")
    
    # Sort tokens by value descending
    all_tokens.sort(key=lambda x: x["value_usd"], reverse=True)
    
    # Enrich LP positions with DB high water mark for collected fees
    # The high water mark tracks the maximum total_earned_fees_usd ever recorded.
    # collected = high_water_mark - current_uncollected
    try:
        from src.storage.portfolio_db import get_lp_fee_high_water_mark
        for lp in all_lp_positions:
            if lp.get('total_collected_fees_usd', 0) > 0:
                continue  # already has on-chain collected fees
            position_id = str(lp.get('token_id') or '')
            if not position_id:
                continue
            hwm = get_lp_fee_high_water_mark(1, position_id)
            if hwm <= 0:
                continue
            uncollected = lp.get('total_fees_usd', 0)
            total_earned = max(hwm, uncollected)
            collected = max(0, total_earned - uncollected)
            if collected > 0 or total_earned > uncollected:
                lp['total_earned_fees_usd'] = total_earned
                lp['total_collected_fees_usd'] = collected
                lp['collected_fees_0_usd'] = collected / 2
                lp['collected_fees_1_usd'] = collected / 2
    except Exception as e:
        print(f"Error enriching LP fees from DB: {e}")

    # Recalculate APR for all positions using consistent fractional-days formula
    # daily_apr = (total_earned_fees / fractional_days) / position_value * 100
    for lp in all_lp_positions:
        age_d = lp.get('age_days')
        age_h = lp.get('age_hours', 0) or 0
        total_earned = lp.get('total_earned_fees_usd', 0)
        total_value = lp.get('total_value_usd', 0)
        if age_d is not None and total_value > 0 and total_earned > 0:
            fractional_days = age_d + age_h / 24.0
            if fractional_days > 0.04:  # at least ~1 hour
                daily_earnings = total_earned / fractional_days
                lp['daily_earnings'] = daily_earnings
                lp['daily_apr'] = (daily_earnings / total_value) * 100
                lp['monthly_apr'] = lp['daily_apr'] * 30

    # Calculate totals
    # Note: lending collateral is NOT added to total because Aave receipt tokens
    # (aEthWBTC, aEthUSDC, etc.) are already in the token list from Zerion
    total_tokens_value = sum(t["value_usd"] for t in all_tokens)
    total_uncollected_fees = sum(pos.get('total_fees_usd', 0) for pos in all_lp_positions)
    total_hedge_value = sum(p.get('collateral_amount', 0) for p in all_gmx_positions)
    
    # Get unique wallet labels for filtering
    wallet_labels = {}
    for wallet in WALLET_ADDRESSES:
        wallet_labels[wallet] = _label(wallet)
    
    result = {
        "tokens": all_tokens,
        "lp_positions": all_lp_positions,
        "aave_positions": all_lending_positions,
        "gmx_positions": all_gmx_positions,
        "total_tokens_value": total_tokens_value,
        "total_lp_value": total_lp_value,
        "total_uncollected_fees": total_uncollected_fees,
        "total_value": total_tokens_value + total_lp_value + total_uncollected_fees + total_hedge_value,
        "wallet_count": len(WALLET_ADDRESSES),
        "wallet_labels": wallet_labels,
        "api_failures": api_failures,
        "fetched_at": datetime.now().isoformat(),
    }
    
    # Cache the result
    _portfolio_cache = result
    
    return result


@app.route('/login', methods=['GET', 'POST'])
def login_page():
    """Login page, or first-time setup if no password exists."""
    import secrets as _secrets
    pw_hash = get_password_hash()

    def _check_csrf():
        return request.form.get('csrf_token') == session.get('_csrf_token')

    def _set_csrf():
        token = _secrets.token_hex(32)
        session['_csrf_token'] = token
        return token

    # No password set — show one-time setup page
    if not pw_hash:
        error = None
        if request.method == 'POST':
            if not _check_csrf():
                error = "Invalid request. Please try again."
            else:
                password = request.form.get('password', '')
                confirm = request.form.get('confirm', '')
                if len(password) < 6:
                    error = "Password must be at least 6 characters"
                elif password != confirm:
                    error = "Passwords don't match"
                else:
                    new_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    set_key(ENV_FILE, "APP_PASSWORD_HASH", new_hash)
                    session['authenticated'] = True
                    session.permanent = True
                    return redirect(url_for('index'))
        return render_template('setup.html', error=error, csrf_token=_set_csrf())

    # Already authenticated
    if session.get('authenticated'):
        return redirect(url_for('index'))

    error = None
    if request.method == 'POST':
        if not _check_csrf():
            error = "Invalid request. Please try again."
        else:
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

    return render_template('login.html', error=error, csrf_token=_set_csrf())


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
    set_key(ENV_FILE, "APP_PASSWORD_HASH", new_hash)

    return jsonify({"status": "success", "message": "Password updated"})


@app.route('/')
def index():
    """Render the unified dashboard."""
    return render_template('index.html')


@app.route('/settings')
def settings():
    """Render the settings page."""
    return render_template('settings.html')


@app.route('/api/market/lending-rates')
def api_lending_rates():
    """Get current Aave V3 lending/borrow rates from on-chain."""
    from src.connectors.aave_v3 import get_aave_market_rates
    from src.models import get_web3 as _gw3
    results = {}
    for chain_name in ['arbitrum', 'base', 'ethereum']:
        w3 = _gw3(chain_name)
        if w3:
            try:
                rates = get_aave_market_rates(w3, chain_name)
                for r in rates:
                    results[f"{chain_name}_{r['asset'].lower()}"] = {
                        'chain': chain_name, 'asset': r['asset'],
                        'supply': r['supply_apy'], 'borrow': r['borrow_apy'],
                    }
            except Exception:
                pass
    return jsonify(results)


@app.route('/api/market-data')
def api_market_data():
    """Return latest market data from DB — single source of truth for frontend + AI."""
    from src.storage.portfolio_db import get_connection
    conn = get_connection()

    # Latest snapshot with prices — single source, no merging from older snapshots
    snap = conn.execute(
        "SELECT * FROM market_snapshots WHERE btc_price IS NOT NULL ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    if not snap:
        snap = conn.execute("SELECT * FROM market_snapshots ORDER BY timestamp DESC LIMIT 1").fetchone()

    data = dict(snap) if snap else {}

    # Calculate 24h price changes from DB history
    if data.get('btc_price'):
        prev = conn.execute(
            "SELECT btc_price, eth_price FROM market_snapshots WHERE btc_price IS NOT NULL "
            "AND datetime(timestamp) BETWEEN datetime('now', '-28 hours') AND datetime('now', '-20 hours') "
            "ORDER BY ABS(julianday('now') - julianday(timestamp) - 1.0) ASC LIMIT 1"
        ).fetchone()
        if prev and prev['btc_price']:
            data['btc_24h_change'] = ((data['btc_price'] - prev['btc_price']) / prev['btc_price']) * 100
        if prev and prev['eth_price'] and data.get('eth_price'):
            data['eth_24h_change'] = ((data['eth_price'] - prev['eth_price']) / prev['eth_price']) * 100

    # Latest defi rates (lending + LP pools)
    latest_rate_ts = conn.execute("SELECT MAX(timestamp) as ts FROM defi_rates").fetchone()
    lending = {}
    lp_pools = {}
    if latest_rate_ts and latest_rate_ts['ts']:
        for r in conn.execute("SELECT * FROM defi_rates WHERE timestamp=? AND rate_type='lending'", (latest_rate_ts['ts'],)).fetchall():
            lending[f"{r['chain']}_{r['asset']}"] = {
                'chain': r['chain'], 'asset': r['asset'],
                'supply': r['supply_apy'], 'borrow': r['borrow_apy'],
            }
        for r in conn.execute("SELECT * FROM defi_rates WHERE timestamp=? AND rate_type='lp' AND fee_apr > 0 ORDER BY tvl DESC", (latest_rate_ts['ts'],)).fetchall():
            r = dict(r)
            lp_pools[f"{r['chain']}_{r['asset']}"] = {
                'chain': r['chain'], 'asset': r['asset'],
                'apyBase': r['fee_apr'], 'apyReward': r.get('reward_apr') or 0,
                'tvl': r['tvl'] or 0, 'vol1d': r.get('volume_1d') or 0,
            }

    # Stablecoin 7d change
    sc_current = conn.execute("SELECT stablecoin_supply FROM market_snapshots WHERE stablecoin_supply IS NOT NULL ORDER BY timestamp DESC LIMIT 1").fetchone()
    sc_prior = conn.execute("SELECT stablecoin_supply FROM market_snapshots WHERE stablecoin_supply IS NOT NULL AND timestamp <= datetime('now', '-5 days') ORDER BY timestamp DESC LIMIT 1").fetchone()
    sc_7d_change = None
    if sc_current and sc_prior and sc_prior['stablecoin_supply']:
        sc_7d_change = ((sc_current['stablecoin_supply'] - sc_prior['stablecoin_supply']) / sc_prior['stablecoin_supply']) * 100

    # Fear & Greed history (from recent snapshots)
    fg_rows = conn.execute(
        "SELECT fear_greed_index FROM market_snapshots WHERE fear_greed_index IS NOT NULL ORDER BY timestamp DESC LIMIT 30"
    ).fetchall()
    fg_history = [r['fear_greed_index'] for r in fg_rows]

    # Macro indicators
    macro_rows = []
    try:
        macro_result = fetch_fred_macro()
        if macro_result and macro_result.get('rows'):
            macro_rows = macro_result['rows']
    except Exception:
        pass

    conn.close()

    return jsonify({
        'snapshot': data,
        'lending': lending,
        'lp_pools': lp_pools,
        'stablecoin_7d_change': sc_7d_change,
        'fg_history': fg_history,
        'macro': macro_rows,
    })


@app.route('/api/market-data/refresh', methods=['POST'])
def api_market_data_refresh():
    """Trigger a fresh market snapshot, then return updated data."""
    try:
        from src.engines.snapshot_service import take_market_snapshot
        take_market_snapshot('manual')
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return api_market_data()


@app.route('/api/market/snapshot', methods=['POST'])
def api_market_snapshot():
    """Trigger a market data snapshot to DB."""
    import threading
    def _bg():
        try:
            from src.engines.snapshot_service import take_market_snapshot
            take_market_snapshot('manual')
        except Exception as e:
            print(f"Manual market snapshot error: {e}")
    threading.Thread(target=_bg, daemon=True, name='manual-market-snapshot').start()
    return jsonify({"status": "started"})


@app.route('/api/market/stablecoin-7d')
def api_stablecoin_7d():
    """Get stablecoin supply 7d change from DB."""
    from src.storage.portfolio_db import get_connection
    conn = get_connection()
    current = conn.execute("SELECT stablecoin_supply FROM market_snapshots WHERE stablecoin_supply IS NOT NULL ORDER BY timestamp DESC LIMIT 1").fetchone()
    prior = conn.execute("SELECT stablecoin_supply FROM market_snapshots WHERE stablecoin_supply IS NOT NULL AND timestamp <= datetime('now', '-5 days') ORDER BY timestamp DESC LIMIT 1").fetchone()
    conn.close()
    if current and prior and prior['stablecoin_supply'] > 0:
        change = ((current['stablecoin_supply'] - prior['stablecoin_supply']) / prior['stablecoin_supply']) * 100
        return jsonify({"change_pct": change, "current": current['stablecoin_supply'], "prior": prior['stablecoin_supply']})
    return jsonify({"change_pct": None})


@app.route('/api/market/stablecoin-supply')
def api_stablecoin_supply():
    """Proxy DefiLlama stablecoin chains endpoint (avoids CORS)."""
    try:
        resp = requests.get('https://stablecoins.llama.fi/stablecoinchains', timeout=15)
        resp.raise_for_status()
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# --- FRED Macro Data (24h in-memory cache) ---
_fred_cache = {"data": None, "fetched_at": None}
FRED_CACHE_TTL = 86400  # 24 hours

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
FOMC_2026 = [
    __import__('datetime').date(2026, 1, 28), __import__('datetime').date(2026, 3, 18),
    __import__('datetime').date(2026, 4, 29), __import__('datetime').date(2026, 6, 17),
    __import__('datetime').date(2026, 7, 29), __import__('datetime').date(2026, 9, 16),
    __import__('datetime').date(2026, 10, 28), __import__('datetime').date(2026, 12, 9),
]


def _fred_fetch(api_key, series_id, start=None):
    """Fetch FRED observations. Returns list of {date, value}."""
    params = {"series_id": series_id, "api_key": api_key, "file_type": "json", "sort_order": "desc"}
    if start:
        params["observation_start"] = start
    else:
        params["limit"] = 1
    try:
        resp = requests.get(FRED_BASE_URL, params=params, timeout=15)
        resp.raise_for_status()
        return [{"date": o["date"], "value": float(o["value"])}
                for o in resp.json().get("observations", []) if o.get("value") not in (".", "")]
    except Exception as e:
        print(f"FRED fetch error ({series_id}): {e}")
        return []


def fetch_fred_macro(force=False):
    """Fetch all FRED macro indicators. Returns dict with rows for display + LLM text."""
    global _fred_cache
    now_ts = datetime.now().timestamp()
    if not force and _fred_cache["data"] and _fred_cache["fetched_at"] and (now_ts - _fred_cache["fetched_at"]) < FRED_CACHE_TTL:
        return _fred_cache["data"]

    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        return None

    from datetime import timedelta
    rows = []
    llm_lines = []
    today = datetime.now().date()

    # US10Y
    start_14d = (today - timedelta(days=14)).isoformat()
    obs = _fred_fetch(api_key, "DGS10", start=start_14d)
    if obs:
        lat = obs[0]
        target = today - timedelta(days=7)
        pri = next((o for o in obs[1:] if __import__('datetime').date.fromisoformat(o["date"]) <= target), obs[-1] if len(obs) > 1 else None)
        trend = "rising" if pri and lat["value"] > pri["value"] else "declining" if pri and lat["value"] < pri["value"] else "flat"
        prior_str = f"7d prior: {pri['value']:.2f}%" if pri else ""
        rows.append({"metric": "US 10Y Yield", "value": f"{lat['value']:.2f}%", "comment": f"{prior_str}, {trend}"})
        llm_lines.append(f"US10Y: {lat['value']:.2f}% ({prior_str}, trend: {trend})")

    # DXY — real US Dollar Index from Yahoo Finance (DX-Y.NYB)
    try:
        dxy_resp = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB",
            params={"interval": "1d", "range": "7d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if dxy_resp.status_code == 200:
            dxy_data = dxy_resp.json()
            closes = dxy_data.get("chart", {}).get("result", [{}])[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
            closes = [c for c in closes if c is not None]
            if closes:
                dxy_now = closes[-1]
                dxy_7d = closes[0] if len(closes) > 1 else None
                trend = "strengthening" if dxy_7d and dxy_now > dxy_7d else "weakening" if dxy_7d and dxy_now < dxy_7d else "flat"
                prior_str = f"7d prior: {dxy_7d:.2f}" if dxy_7d else ""
                rows.append({"metric": "DXY (USD Index)", "value": f"{dxy_now:.2f}", "comment": f"{prior_str}, {trend}"})
                llm_lines.append(f"DXY: {dxy_now:.2f} ({prior_str}, trend: {trend})")
    except Exception as e:
        print(f"DXY fetch from Yahoo failed: {e}")

    # M2 YoY
    start_500d = (today - timedelta(days=500)).isoformat()
    m2_obs = _fred_fetch(api_key, "WM2NS", start=start_500d)
    if m2_obs:
        m2_lat = m2_obs[0]
        lat_dt = __import__('datetime').date.fromisoformat(m2_lat["date"])
        m2_yoy = next((o for o in m2_obs if (lat_dt - __import__('datetime').date.fromisoformat(o["date"])).days >= 340), None)
        if m2_yoy:
            yoy_pct = (m2_lat["value"] - m2_yoy["value"]) / m2_yoy["value"] * 100
            trend = "expanding" if yoy_pct > 0 else "contracting"
            rows.append({"metric": "M2 Money Supply", "value": f"${m2_lat['value']:,.0f}B", "comment": f"{yoy_pct:+.1f}% YoY, {trend}"})
            llm_lines.append(f"M2: ${m2_lat['value']:,.0f}B, {yoy_pct:+.1f}% YoY (trend: {trend})")

    # Fed Funds + cycle
    obs_u = _fred_fetch(api_key, "DFEDTARU")
    obs_u2 = _fred_fetch(api_key, "DFEDTARU", start=(today - timedelta(days=365)).isoformat())
    obs_l = _fred_fetch(api_key, "DFEDTARL")
    if obs_u and obs_l:
        upper = obs_u[0]["value"]
        lower = obs_l[0]["value"]
        rate_range = f"{lower:.2f}%–{upper:.2f}%"
        # Cycle from last 3 decisions
        cycle = "paused"
        last_action = "N/A"
        last_date = obs_u[0]["date"]
        if len(obs_u2) >= 2:
            change_bp = round((obs_u2[0]["value"] - obs_u2[1]["value"]) * 100)
            last_action = f"+{change_bp}bp" if change_bp > 0 else f"{change_bp}bp" if change_bp < 0 else "held"
            if len(obs_u2) >= 3:
                moves = [round((obs_u2[i]["value"] - obs_u2[i+1]["value"]) * 100) for i in range(min(3, len(obs_u2)-1))]
                cuts = sum(1 for m in moves if m < 0)
                hikes = sum(1 for m in moves if m > 0)
                cycle = "cutting" if cuts > hikes else "hiking" if hikes > cuts else "paused"
        # Next FOMC
        next_fomc = "N/A"
        fomc_days = 0
        for d in FOMC_2026:
            if d >= today:
                next_fomc = d.strftime("%b %d, %Y")
                fomc_days = (d - today).days
                break
        rows.append({"metric": "Fed Funds Rate", "value": rate_range, "comment": f"cycle: {cycle}, last ({last_date}): {last_action}"})
        rows.append({"metric": "Next FOMC", "value": next_fomc, "comment": f"{fomc_days} days"})
        llm_lines.append(f"Fed Funds: {rate_range}, cycle: {cycle}, last FOMC ({last_date}): {last_action}, next FOMC: {next_fomc} ({fomc_days}d)")

    result = {
        "rows": rows,
        "llm_text": "\n".join(llm_lines),
        "fetched_at": datetime.now().isoformat(),
    }
    _fred_cache["data"] = result
    _fred_cache["fetched_at"] = now_ts
    return result


@app.route('/api/market/macro')
def api_market_macro():
    """Get FRED macro indicators (24h cached)."""
    force = request.args.get('refresh', 'false').lower() == 'true'
    data = fetch_fred_macro(force=force)
    if not data:
        return jsonify({"error": "FRED_API_KEY not configured", "rows": []})
    return jsonify(data)


@app.route('/api/portfolio')
def api_portfolio():
    """API endpoint for portfolio data."""
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    data = get_portfolio_data(force_refresh=force_refresh)
    # Auto-snapshot: when fresh data is pulled, save to DB in background
    if force_refresh:
        import threading
        def _bg_snapshot():
            try:
                from src.engines.snapshot_service import take_portfolio_snapshot
                wallets = get_wallet_addresses()
                if wallets:
                    # Pass a lambda that returns cached data (no re-fetch)
                    take_portfolio_snapshot(lambda **_: data, wallets)
            except Exception as e:
                print(f"Auto-snapshot error: {e}")
        threading.Thread(target=_bg_snapshot, daemon=True, name='auto-snapshot').start()
    return jsonify(data)


@app.route('/api/wallets', methods=['GET'])
def api_get_wallets():
    """Get list of wallet addresses with labels and roles."""
    config = load_wallet_config()
    wallets = [
        {
            "address": addr,
            "label": info.get("label", addr[:10] + "..."),
            "role": info.get("role", "active"),
            "hidden": bool(info.get("hidden", False)),
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
    """Update wallet label and/or role."""
    global _portfolio_cache
    data = request.json
    label = data.get('label', '').strip()
    role = data.get('role', '').strip()
    hidden = data.get('hidden', None)

    if not label and not role and hidden is None:
        return jsonify({"error": "Nothing to update"}), 400

    config = load_wallet_config()

    wallet_key = None
    for key in config.keys():
        if key.lower() == address.lower():
            wallet_key = key
            break

    if not wallet_key:
        return jsonify({"error": "Wallet not found"}), 404

    if label:
        config[wallet_key]["label"] = label
    if role and role in ('active', 'treasury'):
        config[wallet_key]["role"] = role
    if hidden is not None:
        config[wallet_key]["hidden"] = bool(hidden)
    save_wallet_config(config)

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
    """Get API keys + RPC endpoints (masked — only first/last 4 chars visible)."""
    def _mask(val):
        if not val or len(val) < 8:
            return "****" if val else ""
        return val[:4] + "•" * (len(val) - 8) + val[-4:]

    def _describe_rpc(url: str) -> dict:
        """Detect provider + key from a known RPC URL pattern, or fall back to custom.

        Used by the Settings UI to round-trip the user's choice without storing
        provider info separately. Detection patterns (the prefix is identical
        for every Alchemy / Infura customer; only the trailing key segment varies):
          - https://eth-mainnet.g.alchemy.com/v2/<KEY>
          - https://arb-mainnet.g.alchemy.com/v2/<KEY>
          - https://base-mainnet.g.alchemy.com/v2/<KEY>
          - https://mainnet.infura.io/v3/<KEY>
          - https://arbitrum-mainnet.infura.io/v3/<KEY>
          - https://base-mainnet.infura.io/v3/<KEY>
        Anything else is reported as 'custom' so the UI shows a plain URL field.
        """
        if not url:
            return {"provider": "", "key_masked": "", "url_masked": ""}
        import re
        m = re.match(r"https://[a-z0-9-]+\.g\.alchemy\.com/v2/(.+)$", url)
        if m:
            return {"provider": "alchemy", "key_masked": _mask(m.group(1)), "url_masked": ""}
        m = re.match(r"https://[a-z0-9-]+\.infura\.io/v3/(.+)$", url)
        if m:
            return {"provider": "infura", "key_masked": _mask(m.group(1)), "url_masked": ""}
        # Unknown provider — mask the whole URL by treating it as the secret
        return {"provider": "custom", "key_masked": "", "url_masked": _mask(url)}

    return jsonify({
        "etherscan_api_key": _mask(os.getenv("ETHERSCAN_API_KEY", "")),
        "openai_api_key": _mask(os.getenv("OPENAI_API_KEY", "")),
        "anthropic_api_key": _mask(os.getenv("ANTHROPIC_API_KEY", "")),
        "aws_bearer_token": _mask(os.getenv("AWS_BEARER_TOKEN_BEDROCK", "")),
        "zerion_api_key": _mask(os.getenv("ZERION_API_KEY", "")),
        "fred_api_key": _mask(os.getenv("FRED_API_KEY", "")),
        "rpc_ethereum": _describe_rpc(os.getenv("ETHEREUM_RPC_URL", "")),
        "rpc_arbitrum": _describe_rpc(os.getenv("ARBITRUM_RPC_URL", "")),
        "rpc_base": _describe_rpc(os.getenv("BASE_RPC_URL", "")),
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
        valid_keys = ['ETHERSCAN_API_KEY',
                      'OPENAI_API_KEY', 'ANTHROPIC_API_KEY',
                      'AWS_BEARER_TOKEN_BEDROCK', 'AWS_REGION',
                      'ZERION_API_KEY', 'FRED_API_KEY',
                      'ETHEREUM_RPC_URL', 'ARBITRUM_RPC_URL', 'BASE_RPC_URL']
        if key_name not in valid_keys:
            return jsonify({"error": "Invalid key name"}), 400
        
        # Read current .env file
        env_path = ENV_FILE
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
    elif data.get('action') == 'edit':
        import time as _time
        price0 = float(data['price0_override']) if data.get('price0_override') else _get_coingecko_price(data['token0'])
        price1 = float(data['price1_override']) if data.get('price1_override') else _get_coingecko_price(data['token1'])
        if price0 is None and not data.get('price0_override'):
            _time.sleep(1.5)
            price0 = _get_coingecko_price(data['token0'])
        if price1 is None and not data.get('price1_override'):
            _time.sleep(1.5)
            price1 = _get_coingecko_price(data['token1'])
        price_errors = []
        if price0 is None:
            price_errors.append(f"{data['token0']} price not found — enter Price manually")
        if price1 is None:
            price_errors.append(f"{data['token1']} price not found — enter Price manually")
        if price_errors:
            conn.close()
            return jsonify({"error": "; ".join(price_errors), "need_prices": True}), 400
        price0 = price0 or 0
        price1 = price1 or 0
        amount0 = float(data['amount0'])
        amount1 = float(data['amount1'])
        value_usd = amount0 * price0 + amount1 * price1
        current_price = price0 / price1 if price1 > 0 else 0
        in_range = float(data['range_lower']) <= current_price <= float(data['range_upper'])
        conn.execute("""
            UPDATE lp_positions SET
              chain=?, protocol=?, token0=?, token1=?, fee_tier=?,
              amount0=?, amount1=?, range_lower=?, range_upper=?, notes=?,
              value_usd=?, entry_value_usd=?, current_price=?, in_range=?,
              price0_usd=?, price1_usd=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (
            data.get('chain', ''), data.get('protocol', ''),
            data['token0'], data['token1'], float(data['fee_tier']),
            amount0, amount1, float(data['range_lower']), float(data['range_upper']),
            data.get('notes', ''), value_usd, value_usd,
            current_price, in_range, price0, price1, pos_id
        ))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "value_usd": value_usd, "current_price": current_price, "in_range": in_range})
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


@app.route('/api/manual-positions/<int:pos_id>', methods=['DELETE'])
def api_delete_manual_position(pos_id):
    """Permanently delete a manual LP position."""
    from src.storage.portfolio_db import get_connection
    conn = get_connection()
    conn.execute("DELETE FROM lp_positions WHERE id=?", (pos_id,))
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

    # Check spot_token_config for a CoinGecko ID override
    _override_cg_id = None
    try:
        from src.storage.portfolio_db import get_connection as _gc
        _cfg_conn = _gc()
        _cfg_row = _cfg_conn.execute(
            "SELECT cg_id FROM spot_token_config WHERE symbol=?", (symbol.upper(),)
        ).fetchone()
        _cfg_conn.close()
        if _cfg_row and _cfg_row['cg_id']:
            _override_cg_id = _cfg_row['cg_id']
    except Exception:
        pass

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
    if _override_cg_id:
        cg_id = _override_cg_id
    else:
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


def _get_dexscreener_price(contract_address: str) -> float | None:
    """Get token price via DexScreener by contract address. Caches for 60 seconds."""
    import time as _t
    cache_key = contract_address.lower()
    if cache_key in _cg_price_cache:
        price, ts = _cg_price_cache[cache_key]
        if _t.time() - ts < 60:
            return price
    try:
        r = requests.get(
            f'https://api.dexscreener.com/latest/dex/tokens/{contract_address}',
            timeout=5
        )
        if not r.ok:
            return None
        pairs = r.json().get('pairs') or []
        # Only consider pairs where our token is the base token
        base_pairs = [
            p for p in pairs
            if (p.get('baseToken') or {}).get('address', '').lower() == cache_key
            and p.get('priceUsd')
        ]
        if not base_pairs:
            return None
        best = max(base_pairs, key=lambda p: float((p.get('liquidity') or {}).get('usd') or 0))
        price = float(best['priceUsd'])
        _cg_price_cache[cache_key] = (price, _t.time())
        return price
    except Exception:
        pass
    return None


def _get_spot_price(symbol: str) -> float | None:
    """Price lookup: DexScreener when contract_address is configured (authoritative),
    otherwise CoinGecko."""
    try:
        from src.storage.portfolio_db import get_connection as _gc
        _conn = _gc()
        _row = _conn.execute(
            "SELECT contract_address FROM spot_token_config WHERE symbol=?", (symbol.upper(),)
        ).fetchone()
        _conn.close()
        if _row and _row['contract_address']:
            return _get_dexscreener_price(_row['contract_address'])
    except Exception:
        pass
    return _get_coingecko_price(symbol)


# --- AI Advisor Routes ---

@app.route('/api/ai/config', methods=['GET'])
def api_ai_config_get():
    """Get AI advisor configuration."""
    from src.engines.ai_advisor import load_ai_config
    return jsonify(load_ai_config())


@app.route('/api/ai/config', methods=['POST'])
def api_ai_config_save():
    """Save AI advisor configuration."""
    from src.engines.ai_advisor import save_ai_config
    data = request.json
    save_ai_config(data)
    return jsonify({"status": "success"})


@app.route('/api/ai/models/<provider>')
def api_ai_models(provider):
    """Fetch available models for a given AI provider, with hardcoded fallbacks."""
    _ANTHROPIC_FALLBACK = [
        'claude-opus-4-8',
        'claude-opus-4-7-20260416',
        'claude-sonnet-4-6',
        'claude-haiku-4-5-20251001',
    ]
    _OPENAI_FALLBACK = [
        'gpt-4o',
        'gpt-4o-mini',
        'gpt-4-turbo',
        'gpt-4',
        'gpt-3.5-turbo',
    ]

    if provider == 'anthropic':
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if api_key:
            try:
                resp = requests.get(
                    'https://api.anthropic.com/v1/models',
                    headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01'},
                    timeout=8,
                )
                if resp.ok:
                    data = resp.json()
                    models = [m['id'] for m in data.get('data', []) if m.get('id', '').startswith('claude-')]
                    if models:
                        return jsonify({'models': models})
            except Exception:
                pass
        return jsonify({'models': _ANTHROPIC_FALLBACK})

    elif provider == 'openai':
        api_key = os.environ.get('OPENAI_API_KEY', '')
        if api_key:
            try:
                resp = requests.get(
                    'https://api.openai.com/v1/models',
                    headers={'Authorization': f'Bearer {api_key}'},
                    timeout=8,
                )
                if resp.ok:
                    data = resp.json()
                    models = sorted(
                        [m['id'] for m in data.get('data', []) if m.get('id', '').startswith('gpt-')],
                        reverse=True,
                    )
                    if models:
                        return jsonify({'models': models})
            except Exception:
                pass
        return jsonify({'models': _OPENAI_FALLBACK})

    else:
        return jsonify({'models': []})


# --- Telegram Settings Routes ---

@app.route('/api/settings/telegram', methods=['GET'])
def api_telegram_config_get():
    """Get Telegram configuration with masked bot token."""
    config = load_telegram_config()
    config["bot_token"] = mask_bot_token(config.get("bot_token", ""))
    return jsonify(config)


@app.route('/api/settings/telegram', methods=['POST'])
def api_telegram_config_save():
    """Validate and save Telegram configuration."""
    data = request.json
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400
    # If the submitted token looks masked (starts with ****), preserve the existing one
    if data.get("bot_token", "").startswith("****"):
        existing = load_telegram_config()
        data["bot_token"] = existing.get("bot_token", "")
    ok, err = validate_telegram_config(data)
    if not ok:
        return jsonify({"error": err}), 400
    save_telegram_config(data)
    return jsonify({"status": "success"})


@app.route('/api/settings/telegram/test', methods=['POST'])
def api_telegram_test():
    """Send a test message with real content via Telegram."""
    data = request.json or {}
    chat_id = data.get("chat_id", "").strip()
    # Always read the real token from disk — the form only has the masked version
    config = load_telegram_config()
    bot_token = config.get("bot_token", "")
    # Allow chat_id override from form, fall back to saved config
    if not chat_id:
        chat_id = config.get("chat_id", "")
    if not bot_token:
        return jsonify({"error": "No bot token configured — save your config first"}), 400
    if not chat_id:
        return jsonify({"error": "No chat ID configured"}), 400
    try:
        messages = build_notification_content(config)
        if not messages:
            messages = ["DeFi Portfolio Dashboard — test notification OK\n\n(No digest or regime data available yet)"]
        for msg in messages:
            send_telegram_message(bot_token, chat_id, msg, timeout=10)
        return jsonify({"status": "success", "message": f"Test sent ({len(messages)} message(s))"})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400


DISPLAY_PREFS_PATH = os.path.join("data", "display_prefs.json")
DISPLAY_PREFS_DEFAULTS = {"dust_threshold": 0.01, "lending_threshold": 1.0}


@app.route('/api/settings/display', methods=['GET'])
def api_display_prefs_get():
    """Return display preferences, falling back to defaults."""
    prefs = dict(DISPLAY_PREFS_DEFAULTS)
    if os.path.exists(DISPLAY_PREFS_PATH):
        try:
            with open(DISPLAY_PREFS_PATH, "r") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                prefs.update(saved)
        except (json.JSONDecodeError, IOError):
            pass
    return jsonify(prefs)


@app.route('/api/settings/display', methods=['POST'])
def api_display_prefs_save():
    """Persist display preferences to disk."""
    data = request.json
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid payload"}), 400
    if "dust_threshold" in data:
        try:
            data["dust_threshold"] = float(data["dust_threshold"])
            if data["dust_threshold"] < 0:
                return jsonify({"error": "dust_threshold must be >= 0"}), 400
        except (TypeError, ValueError):
            return jsonify({"error": "dust_threshold must be a number"}), 400
    if "lending_threshold" in data:
        try:
            data["lending_threshold"] = float(data["lending_threshold"])
            if data["lending_threshold"] < 0:
                return jsonify({"error": "lending_threshold must be >= 0"}), 400
        except (TypeError, ValueError):
            return jsonify({"error": "lending_threshold must be a number"}), 400
    os.makedirs(os.path.dirname(DISPLAY_PREFS_PATH), exist_ok=True)
    existing = dict(DISPLAY_PREFS_DEFAULTS)
    if os.path.exists(DISPLAY_PREFS_PATH):
        try:
            with open(DISPLAY_PREFS_PATH, "r") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                existing.update(saved)
        except (json.JSONDecodeError, IOError):
            pass
    existing.update(data)
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(DISPLAY_PREFS_PATH), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp, DISPLAY_PREFS_PATH)
    except Exception as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": "success"})


@app.route('/api/ai/generate', methods=['POST'])
def api_ai_generate():
    """Generate an AI advisor report."""
    try:
        from src.engines.ai_advisor import generate_report
        result = generate_report(get_portfolio_data, get_wallet_addresses)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/ai/digest', methods=['POST'])
def api_ai_digest_generate():
    """Generate a daily digest (pure DB, no LLM)."""
    try:
        from src.engines.ai_advisor import generate_daily_digest
        digest = generate_daily_digest()
        return jsonify(digest)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/ai/digest/latest')
def api_ai_digest_latest():
    """Get the most recent daily digest. Auto-generates if stale."""
    from src.storage.portfolio_db import get_connection
    conn = get_connection()
    
    # Check if latest digest is older than latest snapshot
    latest_snap = conn.execute(
        "SELECT MAX(timestamp) as ts FROM portfolio_snapshots WHERE status='completed'"
    ).fetchone()
    latest_digest = conn.execute(
        "SELECT MAX(timestamp) as ts FROM daily_digests"
    ).fetchone()
    
    snap_ts = latest_snap['ts'] if latest_snap else None
    digest_ts = latest_digest['ts'] if latest_digest else None
    
    # Auto-generate if no digest exists or if snapshot is newer
    if snap_ts and (not digest_ts or snap_ts > digest_ts):
        conn.close()
        try:
            from src.engines.ai_advisor import generate_daily_digest
            generate_daily_digest()
        except Exception as e:
            print(f"Auto-digest error: {e}")
        conn = get_connection()
    
    row = conn.execute("SELECT * FROM daily_digests ORDER BY timestamp DESC LIMIT 1").fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "No digests yet"}), 404
    result = dict(row)
    for field in ['positions_opened', 'positions_closed', 'positions_out_of_range', 'hedge_health_json', 'digest_json']:
        if result.get(field):
            try: result[field] = json.loads(result[field])
            except: pass
    return jsonify(result)


@app.route('/api/ai/reports', methods=['GET'])
def api_ai_reports():
    """Get AI report history."""
    from src.storage.portfolio_db import get_connection
    conn = get_connection()
    limit = request.args.get('limit', 10, type=int)
    rows = conn.execute(
        "SELECT id, timestamp, provider, model, market_regime_json, portfolio_alignment, summary FROM ai_reports ORDER BY timestamp DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/ai/reports/<int:report_id>')
def api_ai_report_detail(report_id):
    """Get a specific AI report."""
    from src.storage.portfolio_db import get_connection
    conn = get_connection()
    row = conn.execute("SELECT * FROM ai_reports WHERE id=?", (report_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Report not found"}), 404
    result = dict(row)
    # Parse JSON fields
    for field in ['full_report_json', 'market_regime_json', 'previous_recs_review_json', 'data_freshness_json']:
        if result.get(field):
            try:
                result[field] = json.loads(result[field])
            except Exception:
                pass
    return jsonify(result)


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

# Startup diagnostics — module-level so gunicorn always runs them; flush=True bypasses buffering
_startup_db_path = get_db_path()
print(f"[startup] db path: {_startup_db_path}", flush=True)
try:
    import sqlite3 as _sq3
    _diag_conn = _sq3.connect(_startup_db_path)
    _spot_rows = _diag_conn.execute("SELECT COUNT(*) FROM spot_transactions").fetchone()[0]
    print(f"[startup] spot_transactions rows: {_spot_rows}", flush=True)
    _diag_conn.close()
except Exception as _diag_err:
    print(f"[startup] spot_transactions check failed: {_diag_err}", flush=True)
if os.path.exists('/app/data'):
    print(f"[startup] /app/data contents: {os.listdir('/app/data')}", flush=True)
else:
    print("[startup] /app/data does not exist", flush=True)
_zerion_key = os.environ.get("ZERION_API_KEY", "")
if _zerion_key:
    print(f"[startup] zerion key prefix: {_zerion_key[:4]}...", flush=True)
else:
    print("[startup] zerion key: NOT SET", flush=True)

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
        query = """SELECT ts,
            SUM(total_tokens_usd) as tokens_value,
            SUM(total_lp_usd) as lp_value,
            SUM(total_lending_usd) as lending_value,
            SUM(total_hedge_collateral_usd) as hedge_value,
            SUM(total_value_usd) as total_value
            FROM (
                SELECT strftime('%Y-%m-%dT%H:%M:00', timestamp) as ts, wallet,
                    total_tokens_usd, total_lp_usd, total_lending_usd, total_hedge_collateral_usd, total_value_usd,
                    ROW_NUMBER() OVER (PARTITION BY strftime('%Y-%m-%dT%H:%M:00', timestamp), wallet ORDER BY id DESC) as rn
                FROM portfolio_snapshots
                WHERE status='completed' AND timestamp >= ? AND timestamp <= ?
            ) WHERE rn=1
            GROUP BY ts ORDER BY ts ASC"""
        rows = conn.execute(query, (date_from, date_to + 'T23:59:59' if date_to else '9999-12-31')).fetchall()
    else:
        date_filter = f"AND timestamp >= datetime('now', '-{int(days)} days')" if days < 9999 else ""
        query = f"""SELECT ts,
            SUM(total_tokens_usd) as tokens_value,
            SUM(total_lp_usd) as lp_value,
            SUM(total_lending_usd) as lending_value,
            SUM(total_hedge_collateral_usd) as hedge_value,
            SUM(total_value_usd) as total_value
            FROM (
                SELECT strftime('%Y-%m-%dT%H:%M:00', timestamp) as ts, wallet,
                    total_tokens_usd, total_lp_usd, total_lending_usd, total_hedge_collateral_usd, total_value_usd,
                    ROW_NUMBER() OVER (PARTITION BY strftime('%Y-%m-%dT%H:%M:00', timestamp), wallet ORDER BY id DESC) as rn
                FROM portfolio_snapshots
                WHERE status='completed' {date_filter}
            ) WHERE rn=1
            GROUP BY ts ORDER BY ts ASC"""
        rows = conn.execute(query).fetchall()
    
    # Get total fees — for each portfolio timestamp, use the closest LP snapshot
    lp_fee_map = {}
    lp_fee_rows = conn.execute(
        """SELECT ts, COALESCE(SUM(fees_uncollected_usd), 0) as total_fees FROM (
            SELECT strftime('%Y-%m-%dT%H:%M:00', timestamp) as ts, position_id, fees_uncollected_usd,
                ROW_NUMBER() OVER (PARTITION BY strftime('%Y-%m-%dT%H:%M:00', timestamp), position_id ORDER BY id DESC) as rn
            FROM lp_snapshots
        ) WHERE rn=1 GROUP BY ts ORDER BY ts ASC"""
    ).fetchall()
    for fr in lp_fee_rows:
        lp_fee_map[fr['ts']] = fr['total_fees']
    lp_timestamps = sorted(lp_fee_map.keys())
    
    result = []
    for r in rows:
        ts = r['ts']
        # Find the latest LP timestamp <= this portfolio timestamp
        fees = 0
        if lp_timestamps:
            import bisect
            idx = bisect.bisect_right(lp_timestamps, ts)
            if idx > 0:
                fees = lp_fee_map[lp_timestamps[idx - 1]]
        
        result.append({
            'timestamp': ts,
            'tokens_value': r['tokens_value'] or 0,
            'lp_value': r['lp_value'] or 0,
            'lending_value': r['lending_value'] or 0,
            'hedge_value': r['hedge_value'] or 0,
            'total_value': r['total_value'] or 0,
            'total_fees': fees,
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

    # Build a parameterized date filter — `?` placeholders only, no string
    # interpolation of request data. The integer `days` branch is safe because
    # Flask coerces the query param via type=int, but we re-cast defensively.
    if date_from:
        if date_to:
            date_filter = "AND timestamp >= ? AND timestamp <= ?"
            date_params = (date_from, date_to + 'T23:59:59')
        else:
            date_filter = "AND timestamp >= ?"
            date_params = (date_from,)
    elif days < 9999:
        date_filter = f"AND timestamp >= datetime('now', '-{int(days)} days')"
        date_params = ()
    else:
        date_filter = ""
        date_params = ()

    # Same fragment with the `timestamp` column rewritten to `updated_at`
    # for queries against lp_positions / hedge_positions which use that column.
    date_filter_updated_at = date_filter.replace('timestamp', 'updated_at')
    
    # Get the latest snapshot timestamp (rounded to minute)
    latest = conn.execute(
        "SELECT MAX(strftime('%Y-%m-%dT%H:%M:00', timestamp)) as ts FROM portfolio_snapshots WHERE status='completed'"
    ).fetchone()
    if not latest or not latest['ts']:
        # No snapshots yet, but check manual positions
        closed_lps = []
        closed_hedges = []
        manual_lps_early = conn.execute(
            f"SELECT * FROM lp_positions WHERE is_active=0 {date_filter_updated_at}",
            date_params,
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
            f"SELECT * FROM hedge_positions WHERE is_active=0 {date_filter_updated_at}",
            date_params,
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
        f"SELECT DISTINCT position_id FROM lp_snapshots WHERE 1=1 {date_filter}",
        date_params,
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
            entry_value = (first['entry_value_usd'] if 'entry_value_usd' in first.keys() else None) or first['value_usd'] or 0
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
    for r in conn.execute(
        f"SELECT DISTINCT market, direction, wallet FROM hedge_snapshots WHERE 1=1 {date_filter}",
        date_params,
    ).fetchall():
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
        f"SELECT * FROM lp_positions WHERE is_active=0 {date_filter_updated_at}",
        date_params,
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
        f"SELECT * FROM hedge_positions WHERE is_active=0 {date_filter_updated_at}",
        date_params,
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
    """Export all config: .env variables + wallet config + AI config as JSON."""
    env_data = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    env_data[key.strip()] = value.strip().strip("'\"")

    wallet_config = load_wallet_config()

    # AI config
    ai_config = {}
    ai_config_path = os.path.join("data", "ai_config.json")
    if os.path.exists(ai_config_path):
        try:
            with open(ai_config_path, 'r') as f:
                ai_config = json.load(f)
        except Exception:
            pass

    # Telegram config
    telegram_config = {}
    telegram_config_path = os.path.join("data", "telegram_config.json")
    if os.path.exists(telegram_config_path):
        try:
            with open(telegram_config_path, 'r') as f:
                telegram_config = json.load(f)
        except Exception:
            pass

    export = {
        "env": env_data,
        "wallets": wallet_config,
        "ai_config": ai_config,
        "telegram_config": telegram_config,
        "exported_at": datetime.now().isoformat()
    }

    buf = io.BytesIO()
    buf.write(json.dumps(export, indent=2).encode('utf-8'))
    buf.seek(0)

    return send_file(buf, mimetype='application/json', as_attachment=True, download_name='portfolio_config.json')


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
        env_path = ENV_FILE
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
        if os.path.exists(WALLET_CONFIG_FILE):
            shutil.copy2(WALLET_CONFIG_FILE, WALLET_CONFIG_FILE + '.pre_import')
        save_wallet_config(data['wallets'])
        restored.append('wallet configuration')
    
    # Restore AI config
    if 'ai_config' in data and isinstance(data['ai_config'], dict):
        ai_config_path = os.path.join("data", "ai_config.json")
        os.makedirs(os.path.dirname(ai_config_path), exist_ok=True)
        with open(ai_config_path, 'w') as f:
            json.dump(data['ai_config'], f, indent=2)
        restored.append('AI configuration')
    
    # Restore Telegram config
    if 'telegram_config' in data and isinstance(data['telegram_config'], dict):
        telegram_path = os.path.join("data", "telegram_config.json")
        os.makedirs(os.path.dirname(telegram_path), exist_ok=True)
        with open(telegram_path, 'w') as f:
            json.dump(data['telegram_config'], f, indent=2)
        restored.append('Telegram configuration')
    
    if not restored:
        return jsonify({"error": "No valid data found in file"}), 400
    
    return jsonify({
        "success": True,
        "message": f"Restored: {', '.join(restored)}"
    })


# ── LP Optimizer API ─────────────────────────────────────────────────

@app.route('/api/optimizer/pools', methods=['POST'])
def api_optimizer_pools():
    """Search DeFiLlama for Uniswap V3 pools matching filters."""
    data = request.get_json(silent=True) or {}
    chain = data.get("chain") or None
    symbol = data.get("symbol") or None
    min_tvl = data.get("min_tvl", 500_000)
    try:
        min_tvl = float(min_tvl)
    except (TypeError, ValueError):
        return jsonify({"error": "min_tvl must be a number"}), 400
    try:
        pools = discover_pools(chain=chain, symbol_filter=symbol, min_tvl=min_tvl)
        return jsonify(pools)
    except requests.RequestException as e:
        return jsonify({"error": f"Pool data unavailable: {e}"}), 502


@app.route('/api/optimizer/run', methods=['POST'])
def api_optimizer_run():
    """Run the full LP range optimization pipeline."""
    data = request.get_json(silent=True) or {}
    try:
        result = run_optimization(data)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except requests.RequestException as e:
        return jsonify({"error": f"External data unavailable: {e}"}), 502


@app.route('/api/optimizer/regimes', methods=['GET'])
def api_optimizer_regimes():
    """Load regime probabilities for a given horizon."""
    horizon_str = request.args.get("horizon", "")
    try:
        horizon = int(horizon_str)
    except (TypeError, ValueError):
        return jsonify({"error": "horizon must be 7, 14, or 30"}), 400
    try:
        regimes = load_regime_probabilities(horizon)
        return jsonify(regimes)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/optimizer/portfolio-positions', methods=['GET'])
def api_optimizer_portfolio_positions():
    """Return active V3 LP positions from the cached portfolio."""
    from src.engines.range_optimizer import resolve_coin_id
    data = get_portfolio_data()
    lp_positions = data.get("lp_positions", [])
    v3_positions = []
    for pos in lp_positions:
        protocol = (pos.get("protocol") or "").lower()
        if "v3" in protocol or "camelot" in protocol:
            pair = pos.get("pair") or ""
            t0 = pos.get("token0_symbol") or ""
            t1 = pos.get("token1_symbol") or ""
            symbol = pair or (t0 + "-" + t1 if t0 and t1 else "")
            raw_chain = pos.get("chain") or ""
            display_chain = raw_chain.capitalize() if raw_chain else raw_chain
            v3_positions.append({
                "chain": display_chain,
                "symbol": symbol,
                "token0": t0,
                "token1": t1,
                "fee_tier": pos.get("fee_tier"),
                "price_lower": pos.get("price_lower"),
                "price_upper": pos.get("price_upper"),
                "current_price": pos.get("current_price"),
                "value_usd": pos.get("total_value_usd"),
                "coin_id": resolve_coin_id(symbol),
            })
    return jsonify(v3_positions)


def _calculate_spot_fifo(conn):
    """
    FIFO P&L across all spot_transactions rows.
    Returns (open_positions, closed_positions) dicts keyed by uppercase symbol.
    """
    from collections import defaultdict, deque

    rows = conn.execute(
        "SELECT * FROM spot_transactions ORDER BY trade_date ASC, id ASC"
    ).fetchall()

    lots            = defaultdict(deque)   # symbol -> deque of {units, price, date}
    realized_pnl    = defaultdict(float)
    total_invested  = defaultdict(float)
    total_proceeds  = defaultdict(float)
    last_sell_date  = defaultdict(str)
    all_symbols     = set()

    for row in rows:
        sym   = row['symbol'].upper()
        side  = row['side'].lower()
        units = float(row['units'])
        price = float(row['price_usd'])
        total = float(row['total_usd'])
        date  = row['trade_date']

        all_symbols.add(sym)

        if side == 'buy':
            lots[sym].append({'units': units, 'price': price, 'date': date})
            total_invested[sym] += total
        elif side == 'sell':
            remaining  = units
            cost_basis = 0.0
            while remaining > 1e-9 and lots[sym]:
                lot = lots[sym][0]
                if lot['units'] <= remaining + 1e-9:
                    cost_basis += lot['units'] * lot['price']
                    remaining  -= lot['units']
                    lots[sym].popleft()
                else:
                    cost_basis     += remaining * lot['price']
                    lot['units']   -= remaining
                    remaining       = 0.0
            total_proceeds[sym] += total
            realized_pnl[sym]   += total - cost_basis
            last_sell_date[sym]  = date

    open_positions = {}
    for sym, lot_queue in lots.items():
        remaining_units = sum(l['units'] for l in lot_queue)
        if remaining_units > 1e-6:
            total_cost = sum(l['units'] * l['price'] for l in lot_queue)
            open_positions[sym] = {
                'symbol':           sym,
                'units':            remaining_units,
                'avg_cost_usd':     total_cost / remaining_units,
                'total_cost_basis': total_cost,
                'oldest_lot_date':  lot_queue[0]['date'],
                'lot_count':        len(lot_queue),
                'lots':             list(lot_queue),
                'realized_pnl':     realized_pnl.get(sym, 0.0),
            }

    closed_positions = {}
    for sym in all_symbols:
        if sym not in open_positions and total_invested.get(sym, 0) > 0:
            invested = total_invested[sym]
            proceeds = total_proceeds.get(sym, 0.0)
            closed_positions[sym] = {
                'symbol':          sym,
                'realized_pnl':    realized_pnl.get(sym, 0.0),
                'total_invested':  invested,
                'total_proceeds':  proceeds,
                'last_sell_date':  last_sell_date.get(sym, ''),
                'roi_pct':         ((proceeds - invested) / invested * 100) if invested > 0 else 0.0,
            }

    return open_positions, closed_positions


# ── Spot P&L Routes ──

@app.route('/api/spot/transactions', methods=['GET'])
def api_spot_transactions_list():
    try:
        from src.storage.portfolio_db import get_connection
        conn = get_connection()
        symbol = request.args.get('symbol', '').strip().upper()
        if symbol:
            rows = conn.execute(
                "SELECT * FROM spot_transactions WHERE symbol=? ORDER BY trade_date DESC, id DESC", (symbol,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM spot_transactions ORDER BY trade_date DESC, id DESC"
            ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        print(traceback.format_exc(), flush=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/spot/transactions', methods=['POST'])
def api_spot_transactions_create():
    try:
        from src.storage.portfolio_db import get_connection
        data = request.json or {}
        required = ['trade_date', 'symbol', 'side', 'units', 'price_usd']
        missing = [f for f in required if not data.get(f) and data.get(f) != 0]
        if missing:
            return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
        if data['side'] not in ('buy', 'sell'):
            return jsonify({"error": "side must be 'buy' or 'sell'"}), 400
        units = float(data['units'])
        price_usd = float(data['price_usd'])
        total_usd = units * price_usd
        conn = get_connection()
        c = conn.execute(
            """INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, platform, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (data['trade_date'], data['symbol'].upper(), data['side'], units, price_usd, total_usd,
             data.get('platform', ''), data.get('notes', ''))
        )
        new_id = c.lastrowid
        conn.commit()
        conn.close()
        return jsonify({"success": True, "id": new_id, "total_usd": total_usd})
    except Exception as e:
        print(traceback.format_exc(), flush=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/spot/transactions/<int:tx_id>', methods=['PUT'])
def api_spot_transactions_update(tx_id):
    try:
        from src.storage.portfolio_db import get_connection
        data = request.json or {}
        required = ['trade_date', 'symbol', 'side', 'units', 'price_usd']
        missing = [f for f in required if not data.get(f) and data.get(f) != 0]
        if missing:
            return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
        if data['side'] not in ('buy', 'sell'):
            return jsonify({"error": "side must be 'buy' or 'sell'"}), 400
        units = float(data['units'])
        price_usd = float(data['price_usd'])
        total_usd = units * price_usd
        conn = get_connection()
        conn.execute(
            """UPDATE spot_transactions SET trade_date=?, symbol=?, side=?, units=?, price_usd=?, total_usd=?,
               platform=?, notes=? WHERE id=?""",
            (data['trade_date'], data['symbol'].upper(), data['side'], units, price_usd, total_usd,
             data.get('platform', ''), data.get('notes', ''), tx_id)
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True, "total_usd": total_usd})
    except Exception as e:
        print(traceback.format_exc(), flush=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/spot/transactions/<int:tx_id>', methods=['DELETE'])
def api_spot_transactions_delete(tx_id):
    try:
        from src.storage.portfolio_db import get_connection
        conn = get_connection()
        conn.execute("DELETE FROM spot_transactions WHERE id=?", (tx_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        print(traceback.format_exc(), flush=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/spot/token-config', methods=['GET'])
def api_spot_token_config_list():
    try:
        from src.storage.portfolio_db import get_connection
        conn = get_connection()
        rows = conn.execute("SELECT * FROM spot_token_config ORDER BY symbol ASC").fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        print(traceback.format_exc(), flush=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/spot/token-config', methods=['POST'])
def api_spot_token_config_upsert():
    try:
        from src.storage.portfolio_db import get_connection
        data = request.json or {}
        if not data.get('symbol'):
            return jsonify({"error": "symbol is required"}), 400
        conn = get_connection()
        c = conn.execute(
            """INSERT OR REPLACE INTO spot_token_config (symbol, cg_id, contract_address, chain, notes, updated_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (data['symbol'].upper(), data.get('cg_id', ''), data.get('contract_address', ''),
             data.get('chain', ''), data.get('notes', ''))
        )
        new_id = c.lastrowid
        conn.commit()
        conn.close()
        return jsonify({"success": True, "id": new_id})
    except Exception as e:
        print(traceback.format_exc(), flush=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/spot/token-config/<symbol>', methods=['DELETE'])
def api_spot_token_config_delete(symbol):
    try:
        from src.storage.portfolio_db import get_connection
        conn = get_connection()
        conn.execute("DELETE FROM spot_token_config WHERE symbol=?", (symbol.upper(),))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        print(traceback.format_exc(), flush=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/spot/import-csv', methods=['POST'])
def api_spot_import_csv():
    try:
        import csv, io
        from src.storage.portfolio_db import get_connection
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        f = request.files['file']
        content = f.read().decode('utf-8-sig', errors='replace')
        reader = csv.DictReader(io.StringIO(content))

        # Normalize header keys
        def _norm(k):
            return k.lower().strip().replace(' ', '_').replace('$', '')

        DATE_ALIASES    = {'date', 'trade_date'}
        SYMBOL_ALIASES  = {'symbol', 'ticker', 'token'}
        SIDE_ALIASES    = {'side', 'buy_sell', 'type'}
        UNITS_ALIASES   = {'units', 'quantity', 'transacted_units', 'amount'}
        PRICE_ALIASES   = {'price_usd', 'unit_price_usd', 'price', 'unit_price'}
        PLATFORM_ALIASES = {'platform'}
        NOTES_ALIASES   = {'notes'}

        def _find(row_norm, aliases):
            for k in row_norm:
                if k in aliases:
                    return row_norm[k]
            return None

        side_map = {
            'buy': 'buy', 'b': 'buy', 'bought': 'buy',
            'sell': 'sell', 's': 'sell', 'sold': 'sell',
        }

        imported = 0
        errors = []
        conn = get_connection()

        for line_num, row in enumerate(reader, start=2):
            row_norm = {_norm(k): v.strip() if v else '' for k, v in row.items()}
            trade_date = _find(row_norm, DATE_ALIASES)
            symbol     = _find(row_norm, SYMBOL_ALIASES)
            side_raw   = _find(row_norm, SIDE_ALIASES)
            units_raw  = _find(row_norm, UNITS_ALIASES)
            price_raw  = _find(row_norm, PRICE_ALIASES)

            missing = []
            if not trade_date: missing.append('trade_date')
            if not symbol:     missing.append('symbol')
            if not side_raw:   missing.append('side')
            if not units_raw:  missing.append('units')
            if not price_raw:  missing.append('price_usd')
            if missing:
                errors.append(f"Row {line_num}: missing {', '.join(missing)}")
                continue

            side = side_map.get(side_raw.lower())
            if not side:
                errors.append(f"Row {line_num}: unrecognised side '{side_raw}'")
                continue

            try:
                units = float(units_raw.replace(',', ''))
                price_usd = float(price_raw.replace(',', '').replace('$', ''))
            except ValueError as e:
                errors.append(f"Row {line_num}: number parse error — {e}")
                continue

            total_usd = units * price_usd
            platform = _find(row_norm, PLATFORM_ALIASES) or ''
            notes    = _find(row_norm, NOTES_ALIASES) or ''

            conn.execute(
                """INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, platform, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (trade_date, symbol.upper(), side, units, price_usd, total_usd, platform, notes)
            )
            imported += 1

        conn.commit()
        conn.close()
        return jsonify({"success": True, "imported": imported, "errors": errors})
    except Exception as e:
        print(traceback.format_exc(), flush=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/spot/pnl', methods=['GET'])
def api_spot_pnl():
    try:
        from src.storage.portfolio_db import get_connection
        conn = get_connection()
        open_positions, _ = _calculate_spot_fifo(conn)
        conn.close()

        results = []
        for sym, pos in open_positions.items():
            current_price = _get_spot_price(sym)
            current_value = (pos['units'] * current_price) if current_price is not None else None
            unrealized_pnl = (current_value - pos['total_cost_basis']) if current_value is not None else None
            unrealized_pct = (unrealized_pnl / pos['total_cost_basis'] * 100) if (unrealized_pnl is not None and pos['total_cost_basis'] > 0) else None
            results.append({
                'symbol':             sym,
                'units':              pos['units'],
                'avg_cost_usd':       pos['avg_cost_usd'],
                'total_cost_basis':   pos['total_cost_basis'],
                'current_price_usd':  current_price,
                'current_value_usd':  current_value,
                'unrealized_pnl_usd': unrealized_pnl,
                'unrealized_pct':     unrealized_pct,
                'realized_pnl_usd':   pos['realized_pnl'],
                'oldest_lot_date':    pos['oldest_lot_date'],
                'lot_count':          pos['lot_count'],
            })

        results.sort(key=lambda x: (x['current_value_usd'] is None, -(x['current_value_usd'] or 0)))
        return jsonify(results)
    except Exception as e:
        print(traceback.format_exc(), flush=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/spot/price-test/<symbol>', methods=['GET'])
def api_spot_price_test(symbol):
    try:
        from src.storage.portfolio_db import get_connection
        sym = symbol.upper()
        conn = get_connection()
        row = conn.execute(
            "SELECT contract_address FROM spot_token_config WHERE symbol=?", (sym,)
        ).fetchone()
        conn.close()
        contract_address = (row['contract_address'] or '') if row else ''
        if contract_address:
            price = _get_dexscreener_price(contract_address)
            source = 'dexscreener' if price is not None else None
        else:
            price = _get_coingecko_price(sym)
            source = 'coingecko' if price is not None else None
        return jsonify({'symbol': sym, 'price': price, 'source': source})
    except Exception as e:
        print(traceback.format_exc(), flush=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/spot/history', methods=['GET'])
def api_spot_history():
    try:
        from src.storage.portfolio_db import get_connection
        conn = get_connection()
        _, closed_positions = _calculate_spot_fifo(conn)
        conn.close()

        results = list(closed_positions.values())
        results.sort(key=lambda x: x.get('last_sell_date', ''), reverse=True)
        return jsonify(results)
    except Exception as e:
        print(traceback.format_exc(), flush=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/spot/stablecoins', methods=['GET'])
def api_spot_stablecoins():
    try:
        from src.storage.portfolio_db import get_connection
        STABLES = ('USDC', 'USDT', 'DAI', 'FRAX', 'LUSD', 'BUSD', 'TUSD', 'USDS', 'CRVUSD')
        conn = get_connection()
        # Latest completed snapshot id per wallet, then fetch matching stablecoin rows
        rows = conn.execute("""
            SELECT t.symbol, t.value_usd, t.wallet
            FROM token_snapshots t
            JOIN (
                SELECT wallet, MAX(id) AS snap_id
                FROM portfolio_snapshots
                WHERE status = 'completed'
                GROUP BY wallet
            ) latest ON t.snapshot_id = latest.snap_id
            WHERE UPPER(t.symbol) IN ({})
        """.format(','.join('?' * len(STABLES))), STABLES).fetchall()
        conn.close()
        breakdown = [{'symbol': r['symbol'], 'value_usd': r['value_usd'] or 0, 'wallet': r['wallet']} for r in rows]
        total_usd = sum(b['value_usd'] for b in breakdown)
        return jsonify({'total_usd': total_usd, 'breakdown': breakdown})
    except Exception as e:
        print(traceback.format_exc(), flush=True)
        return jsonify({'error': str(e)}), 500


# --- Strategy Documents Routes ---

@app.route('/api/strategies')
def api_strategies_list():
    """List all strategy documents with a short text preview."""
    from src.storage.portfolio_db import get_connection
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, filename, category, file_size_bytes, uploaded_at, notes, substr(extracted_text, 1, 200) as preview FROM strategy_documents ORDER BY uploaded_at DESC"
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500


@app.route('/api/strategies/upload', methods=['POST'])
def api_strategies_upload():
    """Upload and extract text from a strategy document (.md, .pdf, .docx, .xlsx, .csv)."""
    from src.storage.portfolio_db import get_connection
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400
    category = request.form.get('category', '').strip()
    if category not in ('bear', 'bull', 'stablecoin', 'cashflow_other'):
        return jsonify({"error": "Invalid category"}), 400
    notes = request.form.get('notes', '').strip()
    filename = f.filename
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.md', '.pdf', '.docx', '.xlsx', '.csv'):
        return jsonify({"error": "Unsupported file type"}), 400
    raw = f.read()
    file_size = len(raw)
    try:
        if ext in ('.md', '.csv'):
            extracted_text = raw.decode('utf-8', errors='replace')
        elif ext == '.pdf':
            import pdfplumber, io as _io
            with pdfplumber.open(_io.BytesIO(raw)) as pdf:
                extracted_text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
        elif ext == '.docx':
            import docx as _docx, io as _io
            doc = _docx.Document(_io.BytesIO(raw))
            extracted_text = '\n'.join(p.text for p in doc.paragraphs)
        elif ext == '.xlsx':
            import openpyxl, io as _io
            wb = openpyxl.load_workbook(_io.BytesIO(raw), read_only=True, data_only=True)
            parts = []
            for sheet in wb.worksheets:
                for row in sheet.iter_rows(values_only=True):
                    parts.append('\t'.join('' if v is None else str(v) for v in row))
            extracted_text = '\n'.join(parts)
    except Exception as e:
        return jsonify({"error": f"Failed to extract text: {str(e)}"}), 500
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO strategy_documents (filename, category, extracted_text, file_size_bytes, notes) VALUES (?, ?, ?, ?, ?)",
            (filename, category, extracted_text, file_size, notes)
        )
        doc_id = c.lastrowid
        conn.commit()
        conn.close()
        return jsonify({"success": True, "id": doc_id, "filename": filename, "preview": extracted_text[:200]})
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500


@app.route('/api/strategies/<int:doc_id>', methods=['DELETE'])
def api_strategies_delete(doc_id):
    """Hard-delete a strategy document."""
    from src.storage.portfolio_db import get_connection
    conn = get_connection()
    try:
        conn.execute("DELETE FROM strategy_documents WHERE id=?", (doc_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500


@app.route('/api/strategies/for-ai/<regime>')
def api_strategies_for_ai(regime):
    """Return concatenated strategy doc text matching the current market regime."""
    from src.storage.portfolio_db import get_connection
    regime_map = {
        'bear': ['bear'],
        'bull': ['bull'],
        'sideways': ['stablecoin', 'cashflow_other'],
        'unknown': ['cashflow_other'],
    }
    categories = regime_map.get(regime, ['cashflow_other'])
    conn = get_connection()
    try:
        placeholders = ','.join('?' for _ in categories)
        rows = conn.execute(
            f"SELECT filename, category, extracted_text FROM strategy_documents WHERE category IN ({placeholders}) ORDER BY uploaded_at DESC",
            categories
        ).fetchall()
        conn.close()
        parts = [f"=== {r['filename']} ({r['category']}) ===\n{r['extracted_text']}\n" for r in rows]
        return jsonify({
            "regime": regime,
            "categories_used": categories,
            "strategy_text": '\n'.join(parts),
            "doc_count": len(rows),
        })
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    start_snapshot_scheduler()
    # Debug mode is opt-in via FLASK_DEBUG=1 — Werkzeug's debugger exposes
    # an in-browser RCE console (PIN-protected, but a dangerous default).
    # Off by default so accidental binds beyond localhost stay safe.
    debug_mode = os.getenv("FLASK_DEBUG", "").strip() == "1"
    app.run(debug=debug_mode, port=5001)
else:
    # Running under gunicorn — start scheduler on import
    start_snapshot_scheduler()

