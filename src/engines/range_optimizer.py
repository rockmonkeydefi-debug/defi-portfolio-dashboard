"""LP Range Optimizer engine — data fetching, math, and orchestration.

Implements the LP Range Optimization Model:
  1. Regime-mixture lognormal price distribution
  2. Candidate range generation (quantile + volatility)
  3. Asymmetric two-barrier time-in-range
  4. Volume projection & fee model
  5. Concentrated liquidity IL
  6. Expected return optimization

Data sources:
  - CoinGecko: current price, 30d price history (vol + returns)
  - DeFiLlama: pool TVL, 24h volume, fee APR
  - On-chain RPC: pool liquidity, sqrtPriceX96, token decimals
  - ai_reports table: regime probabilities
"""

import math
import os
from dataclasses import dataclass

import numpy as np
import requests
from dotenv import load_dotenv

load_dotenv()


# ============================================================
# CONSTANTS
# ============================================================

SUPPORTED_CHAINS = ["ethereum", "arbitrum", "base", "optimism", "polygon"]

COINGECKO_IDS = {
    "ETH": "ethereum", "WETH": "ethereum", "BTC": "bitcoin", "WBTC": "bitcoin",
    "SOL": "solana", "MATIC": "matic-network", "ARB": "arbitrum",
    "OP": "optimism", "AVAX": "avalanche-2", "BNB": "binancecoin",
    "cbETH": "coinbase-wrapped-staked-eth", "wstETH": "wrapped-steth",
}

_STABLES = {"USDC", "USDT", "DAI", "USDS", "FRAX", "GHO", "PYUSD", "USDe",
            "LUSD", "crvUSD", "USDbC"}

# Runtime cache for CoinGecko search results
_coingecko_id_cache: dict[str, str] = {}


def _search_coingecko_id(symbol: str) -> str:
    """Search CoinGecko API for a coin_id matching the given symbol.

    Caches results to avoid repeated API calls. Returns empty string on failure.
    """
    upper = symbol.upper()
    if upper in _coingecko_id_cache:
        return _coingecko_id_cache[upper]

    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/search",
            params={"query": symbol},
            timeout=10,
        )
        resp.raise_for_status()
        coins = resp.json().get("coins", [])
        # Find exact symbol match (case-insensitive), prefer higher market cap rank
        for coin in coins:
            if coin.get("symbol", "").upper() == upper:
                cg_id = coin.get("id", "")
                _coingecko_id_cache[upper] = cg_id
                return cg_id
        # No exact match — cache empty to avoid retrying
        _coingecko_id_cache[upper] = ""
    except Exception as e:
        print(f"CoinGecko search for '{symbol}' failed: {e}")
        _coingecko_id_cache[upper] = ""

    return ""


def resolve_coin_id(symbol: str) -> str:
    """Resolve CoinGecko coin_id from a pool symbol like 'WETH-USDC'.

    Picks the first non-stablecoin token and looks it up in COINGECKO_IDS.
    Falls back to CoinGecko search API if not in the static map.
    Returns empty string if no match found.
    """
    tokens = symbol.replace("/", "-").split("-")
    non_stable = [t for t in tokens if t.upper() not in _STABLES]
    base = non_stable[0] if non_stable else (tokens[0] if tokens else "")
    # Try static map first
    cg_id = COINGECKO_IDS.get(base.upper(), COINGECKO_IDS.get(base, ""))
    if cg_id:
        return cg_id
    # Fallback: search CoinGecko API
    return _search_coingecko_id(base)

FACTORY_ADDRESSES = {
    "ethereum": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    "arbitrum": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    "base": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
    "polygon": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    "optimism": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
}

KNOWN_TOKENS = {
    "base": {
        "WETH": "0x4200000000000000000000000000000000000006",
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "USDbC": "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA",
        "DAI": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
        "cbETH": "0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22",
        "wstETH": "0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452",
    },
    "arbitrum": {
        "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "USDC.e": "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8",
        "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
        "WBTC": "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f",
        "ARB": "0x912CE59144191C1204E64559FE8253a0e49E6548",
        "DAI": "0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1",
        "wstETH": "0x5979D7b546E38E9Ab8049E5B973B3F5609e16Eda",
        "GMX": "0xfc5A1A6EB076a2C7aD06eD22C90d7E710E35ad0a",
    },
    "ethereum": {
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
        "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "wstETH": "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0",
        "cbETH": "0xBe9895146f7AF43049ca1c1AE358B0541Ea49704",
        "rETH": "0xae78736Cd615f374D3085123A210448E74Fc6393",
        "LINK": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
        "UNI": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
        "MKR": "0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2",
        "PEPE": "0x6982508145454Ce325dDbE47a25d4ec3d2311933",
        "GHO": "0x40D16FC0246aD3160Ccc09B8D0D3A2cD28aE6C2f",
    },
    "polygon": {
        "WETH": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        "WMATIC": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        "USDC": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
        "USDC.e": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
        "USDT": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
        "WBTC": "0x1BFD67037B42Cf73acF2047067bd4F2C47D9BfD6",
    },
    "optimism": {
        "WETH": "0x4200000000000000000000000000000000000006",
        "USDC": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
        "USDC.e": "0x7F5c764cBc14f9669B88837ca1490cCa17c31607",
        "USDT": "0x94b008aA00579c1307B0EF2c499aD98a8ce58e58",
        "WBTC": "0x68f180fcCe6836688e9084f035309E29Bf0A2095",
        "OP": "0x4200000000000000000000000000000000000042",
        "wstETH": "0x1F32b1c2345538c0c6f582fCB022739c4A194Ebb",
        "DAI": "0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1",
    },
}

FEE_TIERS_BPS = {"0.01%": 100, "0.05%": 500, "0.3%": 3000, "0.30%": 3000, "1%": 10000}

STABLES = {"USDC", "USDT", "DAI", "USDS", "USDbC", "FRAX", "LUSD", "PYUSD", "USDe"}

CHAIN_RPC_ENV = {
    "ethereum": "ETHEREUM_RPC_URL",
    "arbitrum": "ARBITRUM_RPC_URL",
    "base": "BASE_RPC_URL",
    "polygon": "POLYGON_RPC_URL",
    "optimism": "OPTIMISM_RPC_URL",
}

POOL_ABI = [
    {"inputs": [], "name": "slot0", "outputs": [
        {"name": "sqrtPriceX96", "type": "uint160"}, {"name": "tick", "type": "int24"},
        {"name": "observationIndex", "type": "uint16"}, {"name": "observationCardinality", "type": "uint16"},
        {"name": "observationCardinalityNext", "type": "uint16"}, {"name": "feeProtocol", "type": "uint8"},
        {"name": "unlocked", "type": "bool"},
    ], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "liquidity", "outputs": [
        {"name": "", "type": "uint128"}
    ], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token0", "outputs": [
        {"name": "", "type": "address"}
    ], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [
        {"name": "", "type": "address"}
    ], "stateMutability": "view", "type": "function"},
]

ERC20_ABI = [
    {"inputs": [], "name": "decimals", "outputs": [
        {"name": "", "type": "uint8"}
    ], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol", "outputs": [
        {"name": "", "type": "string"}
    ], "stateMutability": "view", "type": "function"},
]

FACTORY_ABI = [
    {"inputs": [
        {"name": "tokenA", "type": "address"},
        {"name": "tokenB", "type": "address"},
        {"name": "fee", "type": "uint24"},
    ], "name": "getPool", "outputs": [
        {"name": "pool", "type": "address"}
    ], "stateMutability": "view", "type": "function"},
]


# ============================================================
# REGIME DATACLASS
# ============================================================

@dataclass
class Regime:
    """Market regime with probability, drift, and volatility parameters."""
    name: str        # e.g. "bull", "bear", "sideways"
    prob: float      # P_r (0-1)
    drift: float     # mu_r annualized (e.g. 0.50 = +50%)
    vol: float       # sigma_r annualized (e.g. 0.60 = 60%)


# ============================================================
# DATA FETCHING
# ============================================================

# Cache for price data (coin_id -> (timestamp, data))
_price_cache: dict[str, tuple[float, dict]] = {}
_PRICE_CACHE_TTL = 300  # 5 minutes


def fetch_price_and_vol(coin_id: str = "ethereum",
                        coingecko_api_key: str | None = None) -> dict:
    """Fetch current USD price and 90d daily history from CoinGecko.

    Caches results for 5 minutes to avoid rate limiting.
    Retries once on 429 after a 2-second delay.

    Returns:
        {
            "price": float,
            "vol_ann": float,          # annualized vol as decimal (e.g. 0.65)
            "vol_ann_pct": float,      # annualized vol as percentage (e.g. 65.0)
            "ret_7d_pct": float,
            "ret_30d_pct": float,
            "prices": list[float],     # daily close prices
            "timestamps": list[int],   # epoch ms timestamps
        }
    Raises: requests.RequestException on API failure.
    """
    import time as _time

    # Check cache
    now = _time.time()
    if coin_id in _price_cache:
        cached_at, cached_data = _price_cache[coin_id]
        if now - cached_at < _PRICE_CACHE_TTL:
            return cached_data

    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
    params = {"vs_currency": "usd", "days": 90, "interval": "daily"}
    headers = {}
    if coingecko_api_key:
        headers["x-cg-demo-key"] = coingecko_api_key

    # Retry once on 429
    for attempt in range(2):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            if resp.status_code == 429 and attempt == 0:
                _time.sleep(2)
                continue
            resp.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 0:
                _time.sleep(2)
                continue
            raise

    data = resp.json()
    raw_prices = data.get("prices", [])
    prices = [p[1] for p in raw_prices]
    timestamps = [p[0] for p in raw_prices]

    if len(prices) < 2:
        return {
            "price": prices[0] if prices else 0.0,
            "vol_ann": 0.0,
            "vol_ann_pct": 0.0,
            "ret_7d_pct": 0.0,
            "ret_30d_pct": 0.0,
            "prices": prices,
            "timestamps": timestamps,
        }

    current = prices[-1]

    # Realized vol (annualized) from daily log-returns
    log_rets = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
    vol_daily = float(np.std(log_rets, ddof=1))
    vol_ann = vol_daily * math.sqrt(365)
    vol_ann_pct = vol_ann * 100

    # 7d and 30d returns
    ret_7d = (prices[-1] / prices[-min(7, len(prices))] - 1) * 100
    ret_30d = (prices[-1] / prices[0] - 1) * 100

    result = {
        "price": current,
        "vol_ann": vol_ann,
        "vol_ann_pct": vol_ann_pct,
        "ret_7d_pct": ret_7d,
        "ret_30d_pct": ret_30d,
        "prices": prices,
        "timestamps": timestamps,
    }
    _price_cache[coin_id] = (_time.time(), result)
    return result


def _static_coin_id(symbol: str) -> str:
    """Resolve coin_id using only the static COINGECKO_IDS map. No API calls."""
    tokens = symbol.replace("/", "-").split("-")
    non_stable = [t for t in tokens if t.upper() not in _STABLES]
    base = non_stable[0] if non_stable else (tokens[0] if tokens else "")
    return COINGECKO_IDS.get(base.upper(), COINGECKO_IDS.get(base, ""))


def _extract_pool_address(pool_id: str) -> str:
    """Extract a valid 0x hex address from a DeFiLlama pool ID.

    DeFiLlama uses formats like 'ethereum:0xabc123...' or plain UUIDs.
    Returns the hex address if found, empty string otherwise.
    """
    if ":" in pool_id:
        candidate = pool_id.split(":")[-1]
        if candidate.startswith("0x") and len(candidate) == 42:
            return candidate
    if pool_id.startswith("0x") and len(pool_id) == 42:
        return pool_id
    return ""


def discover_pools(chain: str | None = None,
                   symbol_filter: str | None = None,
                   min_tvl: float = 500_000) -> list[dict]:
    """Query DeFiLlama yields API for Uniswap V3 pools.

    Args:
        chain: Filter by chain name (e.g. "base", "arbitrum"). None = all supported chains.
        symbol_filter: Case-insensitive substring match on pool symbol. None = no filter.
        min_tvl: Minimum TVL in USD. Pools below this are excluded.

    Returns list of dicts sorted by TVL descending:
        {"chain", "symbol", "tvl", "volume_24h", "fee_apr", "fee_meta"}
    Raises: requests.RequestException on API failure.
    """
    try:
        resp = requests.get("https://yields.llama.fi/pools", timeout=15)
        resp.raise_for_status()
    except requests.RequestException:
        raise

    pools = resp.json().get("data", [])
    results = []

    for p in pools:
        if p.get("project") != "uniswap-v3":
            continue

        p_chain = (p.get("chain") or "").lower()
        if p_chain not in SUPPORTED_CHAINS:
            continue

        if chain and p_chain != chain.lower():
            continue

        tvl = p.get("tvlUsd", 0) or 0
        if tvl < min_tvl:
            continue

        sym = p.get("symbol") or ""
        if symbol_filter and symbol_filter.upper() not in sym.upper():
            continue

        results.append({
            "chain": p_chain,
            "symbol": sym,
            "tvl": tvl,
            "volume_24h": p.get("volumeUsd1d", 0) or 0,
            "fee_apr": p.get("apyBase", 0) or 0,
            "fee_meta": p.get("poolMeta", "") or "",
            "coin_id": _static_coin_id(sym),
            "pool_address": _extract_pool_address(p.get("pool") or ""),
        })

    results.sort(key=lambda x: x["tvl"], reverse=True)
    return results


_CHAIN_TO_COINGECKO_PLATFORM = {
    "ethereum": "ethereum",
    "arbitrum": "arbitrum-one",
    "base": "base",
    "polygon": "polygon-pos",
    "optimism": "optimistic-ethereum",
}

# Cache for dynamically resolved token addresses
_token_address_cache: dict[str, str] = {}


def _resolve_token_address(symbol: str, chain: str) -> str | None:
    """Look up a token's contract address via CoinGecko search + coin detail.

    Caches results. Returns checksummed address or None.
    """
    cache_key = f"{chain}:{symbol.upper()}"
    if cache_key in _token_address_cache:
        val = _token_address_cache[cache_key]
        return val if val else None

    platform = _CHAIN_TO_COINGECKO_PLATFORM.get(chain)
    if not platform:
        _token_address_cache[cache_key] = ""
        return None

    try:
        # Search for the coin
        resp = requests.get(
            "https://api.coingecko.com/api/v3/search",
            params={"query": symbol},
            timeout=10,
        )
        resp.raise_for_status()
        coins = resp.json().get("coins", [])

        # Find exact symbol match
        coin_id = None
        for coin in coins:
            if coin.get("symbol", "").upper() == symbol.upper():
                coin_id = coin.get("id")
                break

        if not coin_id:
            _token_address_cache[cache_key] = ""
            return None

        # Get coin detail with platform addresses
        resp2 = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}",
            params={"localization": "false", "tickers": "false",
                    "market_data": "false", "community_data": "false",
                    "developer_data": "false"},
            timeout=10,
        )
        resp2.raise_for_status()
        platforms = resp2.json().get("platforms", {})
        addr = platforms.get(platform, "")
        if addr and addr.startswith("0x"):
            _token_address_cache[cache_key] = addr
            return addr

        _token_address_cache[cache_key] = ""
    except Exception as e:
        print(f"CoinGecko token address lookup for {symbol} on {chain}: {e}")
        _token_address_cache[cache_key] = ""

    return None


def resolve_pool_address(chain: str, symbol: str, fee_meta: str) -> str | None:
    """Resolve Uniswap V3 pool address via factory contract.

    Uses KNOWN_TOKENS mapping and factory getPool() call.
    Returns checksummed address or None if resolution fails.
    """
    rpc_url = os.getenv(CHAIN_RPC_ENV.get(chain, ""))
    if not rpc_url or chain not in FACTORY_ADDRESSES:
        return None

    tokens = KNOWN_TOKENS.get(chain, {})
    parts = symbol.replace("/", "-").split("-")
    if len(parts) < 2:
        return None

    addr0 = tokens.get(parts[0])
    addr1 = tokens.get(parts[1])

    # Dynamic fallback: look up unknown tokens via CoinGecko
    if not addr0:
        addr0 = _resolve_token_address(parts[0], chain)
    if not addr1:
        addr1 = _resolve_token_address(parts[1], chain)

    if not addr0 or not addr1:
        missing = []
        if not addr0:
            missing.append(parts[0])
        if not addr1:
            missing.append(parts[1])
        print(f"Token(s) not resolvable for {chain}: {', '.join(missing)}")
        return None

    # Parse fee tier from metadata string
    fee_bps = 3000  # default 0.3%
    for k, v in FEE_TIERS_BPS.items():
        if k in fee_meta:
            fee_bps = v
            break

    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(rpc_url))

        factory = w3.eth.contract(
            address=Web3.to_checksum_address(FACTORY_ADDRESSES[chain]),
            abi=FACTORY_ABI,
        )
        pool_addr = factory.functions.getPool(
            Web3.to_checksum_address(addr0),
            Web3.to_checksum_address(addr1),
            fee_bps,
        ).call()

        if pool_addr and pool_addr != "0x0000000000000000000000000000000000000000":
            return pool_addr
    except Exception as e:
        print(f"Factory lookup failed for {symbol} on {chain}: {e}")

    return None


def fetch_pool_onchain(chain: str, pool_address: str) -> dict:
    """Fetch pool's active liquidity, sqrtPriceX96, tick, and token decimals from RPC.

    Returns:
        {
            "liquidity": int, "sqrt_price_x96": int, "tick": int,
            "token0_decimals": int, "token1_decimals": int,
            "token0_symbol": str, "token1_symbol": str,
            "token0_is_stable": bool,
        }
    """
    default = {
        "liquidity": 0, "sqrt_price_x96": 0, "tick": 0,
        "token0_decimals": 18, "token1_decimals": 6,
        "token0_symbol": "", "token1_symbol": "",
        "token0_is_stable": False,
    }

    rpc_url = os.getenv(CHAIN_RPC_ENV.get(chain, ""))
    if not rpc_url:
        return default

    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(rpc_url))

        pool_contract = w3.eth.contract(
            address=Web3.to_checksum_address(pool_address), abi=POOL_ABI,
        )
        slot0 = pool_contract.functions.slot0().call()
        liquidity = pool_contract.functions.liquidity().call()
        t0_addr = pool_contract.functions.token0().call()
        t1_addr = pool_contract.functions.token1().call()

        t0 = w3.eth.contract(address=t0_addr, abi=ERC20_ABI)
        t1 = w3.eth.contract(address=t1_addr, abi=ERC20_ABI)
        d0 = t0.functions.decimals().call()
        d1 = t1.functions.decimals().call()
        s0 = t0.functions.symbol().call()
        s1 = t1.functions.symbol().call()

        token0_is_stable = s0.upper() in STABLES

        return {
            "liquidity": liquidity,
            "sqrt_price_x96": slot0[0],
            "tick": slot0[1],
            "token0_decimals": d0,
            "token1_decimals": d1,
            "token0_symbol": s0,
            "token1_symbol": s1,
            "token0_is_stable": token0_is_stable,
        }
    except Exception as e:
        print(f"On-chain fetch failed for {pool_address} on {chain}: {e}")
        # Return default with a flag indicating failure
        default["_fetch_error"] = str(e)

    return default


def load_regime_probabilities(horizon_days: int) -> dict:
    """Load regime probabilities from the latest ai_reports row.

    Args:
        horizon_days: 7, 14, or 30

    Returns:
        {
            "bull": float, "bear": float, "sideways": float,
            "source": "ai_report" | "default",
        }
    For 14d: arithmetic mean of short_term_7d and mid_term_30d.
    Falls back to {"bull": 30, "bear": 25, "sideways": 45, "source": "default"}.
    Raises: ValueError if horizon_days not in {7, 14, 30}.
    """
    if horizon_days not in (7, 14, 30):
        raise ValueError(f"Invalid horizon_days={horizon_days}; must be 7, 14, or 30")

    default = {"bull": 30, "bear": 25, "sideways": 45, "source": "default"}

    try:
        import json
        from src.storage.portfolio_db import get_connection

        conn = get_connection()
        row = conn.execute(
            "SELECT market_regime_json FROM ai_reports ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        conn.close()

        if not row or not row["market_regime_json"]:
            return default

        regime_data = json.loads(row["market_regime_json"])

        short = regime_data.get("short_term_7d")
        mid = regime_data.get("mid_term_30d")

        if horizon_days == 7:
            if not short:
                return default
            return {
                "bull": short.get("bull", 30),
                "bear": short.get("bear", 25),
                "sideways": short.get("sideways", 45),
                "source": "ai_report",
            }
        elif horizon_days == 30:
            if not mid:
                return default
            return {
                "bull": mid.get("bull", 30),
                "bear": mid.get("bear", 25),
                "sideways": mid.get("sideways", 45),
                "source": "ai_report",
            }
        else:  # horizon_days == 14
            if not short or not mid:
                return default
            return {
                "bull": (short.get("bull", 30) + mid.get("bull", 30)) / 2,
                "bear": (short.get("bear", 25) + mid.get("bear", 25)) / 2,
                "sideways": (short.get("sideways", 45) + mid.get("sideways", 45)) / 2,
                "source": "ai_report",
            }
    except Exception as e:
        print(f"Error loading regime probabilities: {e}")
        return default


def parse_fee_tier(meta: str) -> float:
    """Parse fee tier decimal from pool metadata string."""
    if "0.01%" in meta:
        return 0.0001
    if "0.05%" in meta:
        return 0.0005
    if "0.3%" in meta or "0.30%" in meta:
        return 0.003
    if "1%" in meta:
        return 0.01
    return 0.003


# ============================================================
# CORE MATH — ported from prototyping/lp_range_optimizer.py
# ============================================================


def generate_candidate_ranges(
    S0: float, regimes: list[Regime], T: float,
) -> list[tuple[float, float, str]]:
    """Generate candidate [L, U] ranges via quantile + volatility methods.

    Method A (quantile): Sample from the regime-mixture lognormal distribution
    and take symmetric quantiles at alpha = 0.5, 0.6, 0.7, 0.8, 0.9.

    Method B (volatility): Use probability-weighted effective volatility with
    multipliers k = 0.5, 1.0, 1.5, 2.0 centered on current price.

    Args:
        S0: Current spot price (USD).
        regimes: List of Regime dataclass instances.
        T: Horizon in years (e.g. 7/365).

    Returns:
        List of (L, U, label) tuples where L < S0 < U.
    """
    # Effective vol (probability-weighted)
    sigma_eff = sum(r.prob * r.vol for r in regimes)

    candidates: list[tuple[float, float, str]] = []

    # Method A: Quantile-based from mixture distribution
    for alpha in [0.5, 0.6, 0.7, 0.8, 0.9]:
        lo_q = (1 - alpha) / 2
        hi_q = 1 - lo_q

        # Sample from mixture to find quantiles
        samples: list[float] = []
        for r in regimes:
            mu_log = math.log(S0) + (r.drift - 0.5 * r.vol ** 2) * T
            sig_log = r.vol * math.sqrt(T)
            n = int(r.prob * 10000)
            if n > 0 and sig_log > 0:
                samples.extend(np.random.lognormal(mu_log, sig_log, n).tolist())

        if samples:
            L = float(np.percentile(samples, lo_q * 100))
            U = float(np.percentile(samples, hi_q * 100))
            candidates.append((L, U, f"quantile_{int(alpha * 100)}"))

    # Method B: Volatility-based
    for k in [0.5, 1.0, 1.5, 2.0]:
        L = S0 * math.exp(-k * sigma_eff * math.sqrt(T))
        U = S0 * math.exp(+k * sigma_eff * math.sqrt(T))
        candidates.append((L, U, f"vol_{k}x"))

    return candidates


def time_in_range(
    S0: float, L: float, U: float,
    mu: float, sigma: float, T: float,
) -> float:
    """Mean first-exit time from [L, U] starting at S0 under GBM, capped at T.

    Uses the zero-drift diffusion formula as base, with a correction for drift
    that reduces time-in-range when drift pushes toward a boundary.

    Args:
        S0: Current spot price.
        L: Lower range bound.
        U: Upper range bound.
        mu: Annualized drift (e.g. 0.50 = +50%).
        sigma: Annualized volatility (e.g. 0.60 = 60%).
        T: Horizon in years.

    Returns:
        Expected time in range (years), in [0, T].
    """
    if L >= U or sigma <= 0 or T <= 0:
        return 0.0

    a = math.log(S0 / L)   # log-distance to lower
    b = math.log(U / S0)   # log-distance to upper

    if a <= 0 or b <= 0:
        return 0.0

    # Base: zero-drift mean exit time = a*b / sigma^2
    tau_base = a * b / (sigma ** 2)

    # Drift correction: drift pushes price toward one boundary, reducing exit time
    nu = mu - 0.5 * sigma ** 2  # log-price drift
    if abs(nu) > 1e-8:
        drift_per_year = abs(nu)
        closer_boundary = b if nu > 0 else a
        tau_drift = closer_boundary / drift_per_year if drift_per_year > 0 else tau_base
        tau = min(tau_base, tau_drift)
    else:
        tau = tau_base

    return min(T, max(0, tau))


def projected_volume(
    hist_volume_daily: float, hist_vol: float,
    regime_vol: float, T: float,
) -> float:
    """Project total trading volume for a regime period using vol-scaling.

    Formula: V_r = k * sigma_r * T * 365, where k = hist_volume_daily / hist_vol.

    Args:
        hist_volume_daily: Historical daily volume (USD).
        hist_vol: Historical annualized volatility (decimal).
        regime_vol: Regime annualized volatility (decimal).
        T: Horizon in years.

    Returns:
        Projected total volume over the period (USD).
    """
    if hist_vol <= 0:
        return hist_volume_daily * T * 365
    k = hist_volume_daily / hist_vol
    return k * regime_vol * T * 365


def fee_income(
    fee_tier: float, volume_daily: float, time_in_range_val: float, T: float,
    position_size: float, S0: float, L: float, U: float,
    pool_liquidity: int, sqrt_price_x96: int,
    token0_decimals: int = 18, token1_decimals: int = 6,
    pool_tvl: float = 0.0,
    pool_fee_apr: float = 0.0,
    hist_vol: float = 0.0,
) -> float:
    """Expected fee income using V3 liquidity math and on-chain pool data.

    Computes your position's liquidity (L_you) using the V3 concentrated
    liquidity formula, then calculates fee share as L_you / L_pool.

    The V3 liquidity for a position of value P in range [sqrt_L, sqrt_U]
    when current price is sqrt_P:
        L = P_token1 / (sqrt_P - sqrt_L)    (token1 side)

    Where P_token1 = position_size / 2 (half the value is in the quote token).

    Total pool fees come from DeFiLlama fee_apr:
        pool_fees_daily = pool_tvl * (fee_apr / 100) / 365

    Your daily fees while in range:
        your_fees_daily = (L_you / L_pool) * pool_fees_daily_at_tick

    But pool_fees_daily already accounts for all liquidity, so:
        your_fees_daily = (L_you / L_pool) * fee_tier * volume_daily

    Returns:
        Expected fee income (USD), non-negative.
    """
    if T <= 0 or L >= U or position_size <= 0 or S0 <= 0:
        return 0.0
    if pool_liquidity <= 0:
        return 0.0

    # V3 sqrt-price values for the range bounds
    # These are in "real" price space (USD per token), not in on-chain Q96 format
    sqrt_L = math.sqrt(L)
    sqrt_U = math.sqrt(U)
    sqrt_P = math.sqrt(S0)

    if sqrt_P <= sqrt_L or sqrt_P >= sqrt_U:
        return 0.0  # price outside range

    # Your position's liquidity in "USD sqrt-price" units
    # In V3, when price is in range: L = amount1 / (sqrt_P - sqrt_L)
    # amount1 (quote token) ≈ position_size / 2
    # This gives liquidity in USD-sqrt-price units
    token1_value = position_size / 2.0
    your_liq_usd = token1_value / (sqrt_P - sqrt_L)

    # Pool's total liquidity is in on-chain units (token-decimal adjusted)
    # We need to convert to the same units, or use a ratio approach.
    #
    # The on-chain pool_liquidity (L_pool) relates to token amounts as:
    #   amount1_pool = L_pool * (sqrt_P - sqrt_L_tick) / 10^decimals1
    #
    # For the fee share, we need L_you / L_pool in consistent units.
    # Convert your USD liquidity to on-chain units:
    #   L_you_onchain = (amount1_raw) / (sqrt_P_raw - sqrt_L_raw)
    #
    # Where sqrt_P_raw = sqrtPriceX96 / 2^96 (on-chain sqrt price in token ratio)
    # and amount1_raw = token1_value * 10^decimals1 / price_token1_usd
    #
    # For stablecoin pairs (token1=USDC): price_token1_usd ≈ 1
    # For volatile pairs: we need the token1 USD price

    sqrt_p_raw = sqrt_price_x96 / (2 ** 96)
    if sqrt_p_raw <= 0:
        return 0.0

    # Compute on-chain sqrt prices for L and U
    # On-chain price = (token0/token1) in raw units = price_usd * 10^(d1-d0)
    decimal_ratio = 10 ** (token1_decimals - token0_decimals)
    price_raw = S0 * decimal_ratio  # price in token1_raw / token0_raw
    sqrt_L_raw = math.sqrt(L * decimal_ratio)
    sqrt_P_raw_computed = math.sqrt(S0 * decimal_ratio)

    sqrt_diff_raw = sqrt_P_raw_computed - sqrt_L_raw
    if sqrt_diff_raw <= 0:
        return 0.0

    # Your liquidity in on-chain units
    # amount1_raw = (position_size / 2) * 10^token1_decimals (assuming token1 ≈ $1 for stables)
    # For non-stable token1: amount1_raw = (position_size / 2 / token1_price_usd) * 10^d1
    # We approximate token1_price_usd from the pool's price ratio
    # If token0 is priced at S0 USD, and on-chain price = token1/token0,
    # then token1_price_usd = S0 / price_in_token1_per_token0
    # But this gets circular. Simpler: use the on-chain sqrtPrice directly.

    # Direct approach: L_you = amount1_raw / (sqrt_P_onchain - sqrt_L_onchain)
    # amount1_raw = token1_value_usd * 10^d1 / token1_usd_price
    # For USDC (d1=6): token1_usd_price ≈ 1, amount1_raw = token1_value * 1e6
    # For WETH (d1=18): token1_usd_price = ETH_price, amount1_raw = (val/eth_price) * 1e18

    # Use sqrtPriceX96 to derive token1 price:
    # sqrtPriceX96 = sqrt(token0/token1 in raw) * 2^96
    # price_token0_in_token1 = (sqrtPriceX96 / 2^96)^2
    # price_token0_in_usd = S0
    # So token1_usd_price = S0 / price_token0_in_token1_raw * 10^(d0-d1)
    price_t0_in_t1_raw = sqrt_p_raw ** 2
    if price_t0_in_t1_raw <= 0:
        return 0.0
    token1_usd_price = S0 / (price_t0_in_t1_raw * (10 ** (token0_decimals - token1_decimals)))

    if token1_usd_price <= 0:
        token1_usd_price = 1.0  # fallback for stablecoins

    amount1_raw = (token1_value / token1_usd_price) * (10 ** token1_decimals)

    # On-chain sqrt prices for range bounds
    sqrt_L_onchain = sqrt_p_raw * math.sqrt(L / S0)
    sqrt_P_onchain = sqrt_p_raw

    onchain_sqrt_diff = sqrt_P_onchain - sqrt_L_onchain
    if onchain_sqrt_diff <= 0:
        return 0.0

    your_liq_onchain = amount1_raw / onchain_sqrt_diff
    fee_share = your_liq_onchain / pool_liquidity

    # Total pool fees per day
    if pool_fee_apr > 0 and pool_tvl > 0:
        pool_fees_daily = pool_tvl * (pool_fee_apr / 100) / 365
    elif volume_daily > 0:
        pool_fees_daily = fee_tier * volume_daily
    else:
        return 0.0

    days_in_range = time_in_range_val * 365
    return max(0.0, fee_share * pool_fees_daily * days_in_range)


def concentrated_il(S0: float, S_T: float, L: float, U: float) -> float:
    """Impermanent loss for concentrated V3 position in range [L, U].

    Computes the ratio of LP value to HODL value at terminal price S_T,
    minus 1. Returns 0 when S_T == S0 (no price movement), and a negative
    value (loss) when price moves away from S0.

    Args:
        S0: Entry price.
        S_T: Terminal price.
        L: Lower range bound.
        U: Upper range bound.

    Returns:
        IL as a fraction (e.g. -0.03 = 3% loss). Non-positive for boundary prices.
    """
    if L >= U or S0 <= 0:
        return 0.0

    sqrt_S0 = math.sqrt(S0)
    sqrt_L = math.sqrt(L)
    sqrt_U = math.sqrt(U)

    denom0 = 1 / sqrt_L - 1 / sqrt_U
    denom1 = sqrt_U - sqrt_L

    if denom0 <= 0 or denom1 <= 0:
        return 0.0

    # Initial amounts (per unit of liquidity)
    amt0_init = 1 / sqrt_S0 - 1 / sqrt_U
    amt1_init = sqrt_S0 - sqrt_L
    v_init = amt0_init * S0 + amt1_init  # initial value in token1 terms

    if v_init <= 0:
        return 0.0

    # HODL value at S_T
    v_hodl = amt0_init * S_T + amt1_init

    # LP value at S_T
    if S_T <= L:
        # 100% token0
        amt0_final = 1 / sqrt_L - 1 / sqrt_U
        amt1_final = 0.0
    elif S_T >= U:
        # 100% token1
        amt0_final = 0.0
        amt1_final = sqrt_U - sqrt_L
    else:
        sqrt_ST = math.sqrt(S_T)
        amt0_final = 1 / sqrt_ST - 1 / sqrt_U
        amt1_final = sqrt_ST - sqrt_L

    v_lp = amt0_final * S_T + amt1_final

    if v_hodl <= 0:
        return 0.0

    return (v_lp / v_hodl) - 1  # negative = loss


def evaluate_range(
    S0: float, L: float, U: float,
    regimes: list[Regime], T: float,
    fee_tier: float, hist_volume_daily: float, hist_vol: float,
    position_size: float, pool_liquidity: int, sqrt_price_x96: int,
    token0_decimals: int = 18, token1_decimals: int = 6,
    pool_tvl: float = 0.0,
    pool_fee_apr: float = 0.0,
) -> dict:
    """Evaluate a single candidate range across all regimes.

    Probability-weights fee income and time-in-range across regimes,
    computes IL at both boundaries, and returns a metrics dict.

    Args:
        S0: Current spot price (USD).
        L: Lower range bound.
        U: Upper range bound.
        regimes: List of Regime instances.
        T: Horizon in years.
        fee_tier: Pool fee as decimal.
        hist_volume_daily: Historical daily volume (USD).
        hist_vol: Historical annualized volatility (decimal).
        position_size: Position value (USD).
        pool_liquidity: On-chain active liquidity.
        sqrt_price_x96: On-chain sqrtPriceX96.
        token0_decimals: Token0 decimal places.
        token1_decimals: Token1 decimal places.

    Returns:
        Dict with keys: L, U, expected_return_usd, expected_fees_usd,
        expected_time_in_range_days, time_in_range_pct, apr_pct,
        il_at_lower_pct, il_at_lower_usd, il_at_upper_pct, il_at_upper_usd.
    """
    total_fees = 0.0
    total_time_in_range = 0.0
    total_fees_full_tir = 0.0  # fees assuming 100% time-in-range

    for r in regimes:
        tau = time_in_range(S0, L, U, r.drift, r.vol, T)
        vol_daily = (
            projected_volume(hist_volume_daily, hist_vol, r.vol, T) / (T * 365)
            if T > 0
            else hist_volume_daily
        )
        fees = fee_income(
            fee_tier, vol_daily, tau, T, position_size, S0, L, U,
            pool_liquidity, sqrt_price_x96, token0_decimals, token1_decimals,
            pool_tvl=pool_tvl, pool_fee_apr=pool_fee_apr, hist_vol=hist_vol,
        )
        # Fees assuming full time in range (for raw APR display)
        fees_full = fee_income(
            fee_tier, vol_daily, T, T, position_size, S0, L, U,
            pool_liquidity, sqrt_price_x96, token0_decimals, token1_decimals,
            pool_tvl=pool_tvl, pool_fee_apr=pool_fee_apr, hist_vol=hist_vol,
        )
        total_fees += r.prob * fees
        total_fees_full_tir += r.prob * fees_full
        total_time_in_range += r.prob * tau

    il_at_lower = concentrated_il(S0, L, L, U)
    il_at_upper = concentrated_il(S0, U, L, U)

    return {
        "L": L,
        "U": U,
        "expected_return_usd": total_fees,
        "expected_fees_usd": total_fees,
        "expected_time_in_range_days": total_time_in_range * 365,
        "time_in_range_pct": (total_time_in_range / T * 100) if T > 0 else 0,
        "apr_pct": (total_fees / position_size) / T * 100 if T > 0 and position_size > 0 else 0,
        "raw_apr_pct": (total_fees_full_tir / position_size) / T * 100 if T > 0 and position_size > 0 else 0,
        "il_at_lower_pct": il_at_lower * 100,
        "il_at_lower_usd": il_at_lower * position_size,
        "il_at_upper_pct": il_at_upper * 100,
        "il_at_upper_usd": il_at_upper * position_size,
    }


# ============================================================
# ORCHESTRATOR
# ============================================================

def run_optimization(params: dict) -> dict:
    """Full optimization pipeline.

    Args:
        params: {
            "chain": str,
            "symbol": str,           # e.g. "WETH-USDC"
            "fee_meta": str,          # e.g. "0.05%"
            "volume_24h": float,      # historical daily volume (USD)
            "tvl": float,
            "horizon_days": int,      # 7, 14, or 30
            "position_size": float,   # USD
            "regime_override": dict | None,  # {"bull": float, "bear": float, "sideways": float}
            "coin_id": str,           # CoinGecko ID for base token
        }

    Returns:
        {
            "current_price": float,
            "vol_ann_pct": float,
            "ret_7d_pct": float,
            "ret_30d_pct": float,
            "prices": list[float],
            "timestamps": list[int],
            "regimes": dict,
            "candidates": list[dict],
            "optimal_index": int,
            "pool_address": str,
            "pool_liquidity": int,
        }

    Raises:
        ValueError: For missing/invalid params or zero liquidity.
        requests.RequestException: For external API failures.
    """
    # --- Validate required params ---
    required = ["chain", "symbol", "fee_meta", "volume_24h", "tvl",
                 "horizon_days", "position_size", "coin_id"]
    for field in required:
        if field not in params or params[field] is None:
            raise ValueError(f"Missing required field: {field}")

    # Resolve coin_id dynamically if not provided by the static map
    if not params.get("coin_id"):
        params["coin_id"] = resolve_coin_id(params.get("symbol", ""))
    if not params.get("coin_id"):
        tokens = params.get("symbol", "").replace("/", "-").split("-")
        raise ValueError(
            f"Could not identify CoinGecko ID for token(s): {', '.join(tokens)}. "
            "Try a pool with common tokens (ETH, BTC, etc.)."
        )

    chain = params["chain"]
    symbol = params["symbol"]
    fee_meta = params["fee_meta"]
    volume_24h = float(params["volume_24h"])
    horizon_days = int(params["horizon_days"])
    position_size = float(params["position_size"])
    coin_id = params["coin_id"]
    regime_override = params.get("regime_override")

    fee_tier = parse_fee_tier(fee_meta)
    T = horizon_days / 365

    print(f"[Optimizer] {symbol} on {chain}: vol_24h=${volume_24h:,.0f}, fee_tier={fee_tier}, position=${position_size:,.0f}, horizon={horizon_days}d")

    # --- Fetch price and volatility ---
    coingecko_key = os.getenv("COINGECKO_API_KEY")
    price_data = fetch_price_and_vol(coin_id, coingecko_api_key=coingecko_key)
    S0 = price_data["price"]
    hist_vol = price_data["vol_ann"]

    # --- Resolve pool and fetch on-chain data ---
    pool_address = params.get("pool_address") or ""
    # Validate it looks like a hex address
    if not (pool_address.startswith("0x") and len(pool_address) == 42):
        pool_address = resolve_pool_address(chain, symbol, fee_meta)
    if not pool_address:
        raise ValueError(f"Could not resolve pool address for {symbol} on {chain} (fee: {fee_meta}). Token may not be in known tokens list.")

    onchain = fetch_pool_onchain(chain, pool_address)
    pool_liq = onchain["liquidity"]
    sqrt_px96 = onchain["sqrt_price_x96"]
    d0 = onchain.get("token0_decimals", 18)
    d1 = onchain.get("token1_decimals", 6)
    t0_stable = onchain.get("token0_is_stable", False)

    print(f"[Optimizer] On-chain: liq={pool_liq}, sqrtPx96={sqrt_px96}, d0={d0}, d1={d1}, t0_stable={t0_stable}")

    if pool_liq == 0:
        fetch_err = onchain.get("_fetch_error", "")
        if fetch_err:
            raise ValueError(f"On-chain data unavailable for pool {pool_address} on {chain}: {fetch_err}")
        raise ValueError("Pool has no active liquidity")

    # Token decimal ordering for fee calculation
    token0_dec = d0
    token1_dec = d1

    # --- Load regime probabilities ---
    regime_data = load_regime_probabilities(horizon_days)

    # Apply overrides if provided, normalizing to sum to 100%
    if regime_override:
        bull = float(regime_override.get("bull", 0))
        bear = float(regime_override.get("bear", 0))
        sideways = float(regime_override.get("sideways", 0))
        total = bull + bear + sideways
        if total > 0:
            regime_data["bull"] = bull / total * 100
            regime_data["bear"] = bear / total * 100
            regime_data["sideways"] = sideways / total * 100
            regime_data["source"] = "override"

    # Build Regime objects (probabilities as 0-1 fractions)
    p_bull = regime_data["bull"] / 100
    p_bear = regime_data["bear"] / 100
    p_side = regime_data["sideways"] / 100

    regimes = [
        Regime("bull", prob=p_bull, drift=0.50, vol=hist_vol * 0.9),
        Regime("sideways", prob=p_side, drift=0.00, vol=hist_vol * 0.7),
        Regime("bear", prob=p_bear, drift=-0.40, vol=hist_vol * 1.3),
    ]

    # --- Generate and evaluate candidates ---
    candidates_raw = generate_candidate_ranges(S0, regimes, T)
    results = []
    pool_tvl = float(params.get("tvl", 0))
    pool_fee_apr = float(params.get("fee_apr", 0))

    for L, U, label in candidates_raw:
        res = evaluate_range(
            S0, L, U, regimes, T, fee_tier, volume_24h, hist_vol,
            position_size, pool_liq, sqrt_px96, token0_dec, token1_dec,
            pool_tvl=pool_tvl, pool_fee_apr=pool_fee_apr,
        )
        res["label"] = label
        res["pct_lower"] = (L / S0 - 1) * 100
        res["pct_upper"] = (U / S0 - 1) * 100
        results.append(res)

    # Sort by expected_return_usd descending
    results.sort(key=lambda x: x["expected_return_usd"], reverse=True)

    return {
        "current_price": S0,
        "vol_ann_pct": price_data["vol_ann_pct"],
        "ret_7d_pct": price_data["ret_7d_pct"],
        "ret_30d_pct": price_data["ret_30d_pct"],
        "prices": price_data["prices"],
        "timestamps": price_data["timestamps"],
        "regimes": regime_data,
        "candidates": results,
        "optimal_index": 0,
        "pool_address": pool_address,
        "pool_liquidity": pool_liq,
    }
