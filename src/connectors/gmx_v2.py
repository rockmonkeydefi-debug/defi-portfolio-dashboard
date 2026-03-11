"""GMX V2 connector — fetches perpetual positions and orders from Arbitrum."""

from web3 import Web3

# GMX V2 contract addresses (Arbitrum)
DATASTORE_ADDRESS = "0xFD70de6b91282D8017aA4E741e9Ae325CAb992d8"
READER_ADDRESS = "0x470fbC46bcC0f16532691Df360A07d8Bf5ee0789"

# Minimal ABIs
READER_ABI = [
    {
        "inputs": [
            {"name": "dataStore", "type": "address"},
            {"name": "account", "type": "address"},
            {"name": "start", "type": "uint256"},
            {"name": "end", "type": "uint256"},
        ],
        "name": "getAccountPositions",
        "outputs": [
            {
                "components": [
                    {
                        "components": [
                            {"name": "account", "type": "address"},
                            {"name": "market", "type": "address"},
                            {"name": "collateralToken", "type": "address"},
                        ],
                        "name": "addresses",
                        "type": "tuple",
                    },
                    {
                        "components": [
                            {"name": "sizeInUsd", "type": "uint256"},
                            {"name": "sizeInTokens", "type": "uint256"},
                            {"name": "collateralAmount", "type": "uint256"},
                            {"name": "borrowingFactor", "type": "uint256"},
                            {"name": "fundingFeeAmountPerSize", "type": "uint256"},
                            {"name": "longTokenClaimableFundingAmountPerSize", "type": "uint256"},
                            {"name": "shortTokenClaimableFundingAmountPerSize", "type": "uint256"},
                            {"name": "increasedAtTime", "type": "uint256"},
                            {"name": "decreasedAtTime", "type": "uint256"},
                        ],
                        "name": "numbers",
                        "type": "tuple",
                    },
                    {
                        "components": [
                            {"name": "isLong", "type": "bool"},
                        ],
                        "name": "flags",
                        "type": "tuple",
                    },
                ],
                "name": "",
                "type": "tuple[]",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "dataStore", "type": "address"},
            {"name": "account", "type": "address"},
            {"name": "start", "type": "uint256"},
            {"name": "end", "type": "uint256"},
        ],
        "name": "getAccountOrders",
        "outputs": [
            {
                "components": [
                    {
                        "components": [
                            {"name": "account", "type": "address"},
                            {"name": "receiver", "type": "address"},
                            {"name": "cancellationReceiver", "type": "address"},
                            {"name": "callbackContract", "type": "address"},
                            {"name": "uiFeeReceiver", "type": "address"},
                            {"name": "market", "type": "address"},
                            {"name": "initialCollateralToken", "type": "address"},
                            {"name": "swapPath", "type": "address[]"},
                        ],
                        "name": "addresses",
                        "type": "tuple",
                    },
                    {
                        "components": [
                            {"name": "orderType", "type": "uint256"},
                            {"name": "decreasePositionSwapType", "type": "uint256"},
                            {"name": "sizeDeltaUsd", "type": "uint256"},
                            {"name": "initialCollateralDeltaAmount", "type": "uint256"},
                            {"name": "triggerPrice", "type": "uint256"},
                            {"name": "acceptablePrice", "type": "uint256"},
                            {"name": "executionFee", "type": "uint256"},
                            {"name": "callbackGasLimit", "type": "uint256"},
                            {"name": "minOutputAmount", "type": "uint256"},
                            {"name": "updatedAtTime", "type": "uint256"},
                            {"name": "validFromTime", "type": "uint256"},
                        ],
                        "name": "numbers",
                        "type": "tuple",
                    },
                    {
                        "components": [
                            {"name": "isLong", "type": "bool"},
                            {"name": "shouldUnwrapNativeToken", "type": "bool"},
                            {"name": "isFrozen", "type": "bool"},
                            {"name": "autoCancel", "type": "bool"},
                        ],
                        "name": "flags",
                        "type": "tuple",
                    },
                ],
                "name": "",
                "type": "tuple[]",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "dataStore", "type": "address"},
            {"name": "start", "type": "uint256"},
            {"name": "end", "type": "uint256"},
        ],
        "name": "getMarkets",
        "outputs": [
            {
                "components": [
                    {"name": "marketToken", "type": "address"},
                    {"name": "indexToken", "type": "address"},
                    {"name": "longToken", "type": "address"},
                    {"name": "shortToken", "type": "address"},
                ],
                "name": "",
                "type": "tuple[]",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

ERC20_ABI = [
    {"inputs": [], "name": "symbol", "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"type": "uint8"}], "stateMutability": "view", "type": "function"},
]

# Known GMX V2 index token mappings (Arbitrum)
# Some markets use synthetic/internal token addresses that don't have standard ERC20 interfaces
GMX_INDEX_TOKENS = {
    "0x47904963fc8b2340414262125aF798B9655E58Cd".lower(): {"symbol": "BTC", "decimals": 8},
    "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1".lower(): {"symbol": "WETH", "decimals": 18},
    "0xf97f4df75117a78c1A5a0DBb814Af92458539FB4".lower(): {"symbol": "LINK", "decimals": 18},
    "0xFa7F8980b0f1E64A2062791cc3b0871572f1F7f0".lower(): {"symbol": "UNI", "decimals": 18},
    "0x912CE59144191C1204E64559FE8253a0e49E6548".lower(): {"symbol": "ARB", "decimals": 18},
    "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f".lower(): {"symbol": "WBTC", "decimals": 8},
    "0xaf88d065e77c8cC2239327C5EDb3A432268e5831".lower(): {"symbol": "USDC", "decimals": 6},
    "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9".lower(): {"symbol": "USDT", "decimals": 6},
    "0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1".lower(): {"symbol": "DAI", "decimals": 18},
    "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8".lower(): {"symbol": "USDC.e", "decimals": 6},
    "0x5979D7b546E38E9Ab8049E5B973B3F5a2e0A1233".lower(): {"symbol": "wstETH", "decimals": 18},
    "0x35751007a407ca6FEFfE80b3cB397736D2cf4dbe".lower(): {"symbol": "weETH", "decimals": 18},
    "0x2bcC6D6CdBbDC0a4071e48bb3B969b06B3330c07".lower(): {"symbol": "SOL", "decimals": 9},
    "0xaC800FD6159c2a2CB8fC31EF74621eB430287a5A".lower(): {"symbol": "DOGE", "decimals": 8},
    "0xB46A094Bc4B0adBD801E14b9DB95e05E28962764".lower(): {"symbol": "XRP", "decimals": 6},
}
ORDER_TYPES = {
    0: "MarketSwap",
    1: "LimitSwap",
    2: "MarketIncrease",
    3: "LimitIncrease",
    4: "MarketDecrease",
    5: "LimitDecrease",      # Take Profit
    6: "StopLossDecrease",   # Stop Loss
    7: "Liquidation",
}


def get_gmx_positions(w3: Web3, wallet: str) -> list:
    """Fetch all open GMX V2 perpetual positions and associated orders for a wallet.
    
    Returns list of position dicts, each with SL/TP orders attached.
    """
    reader = w3.eth.contract(
        address=Web3.to_checksum_address(READER_ADDRESS),
        abi=READER_ABI
    )
    ds = Web3.to_checksum_address(DATASTORE_ADDRESS)
    wallet_cs = Web3.to_checksum_address(wallet)
    
    # Fetch positions
    try:
        raw_positions = reader.functions.getAccountPositions(ds, wallet_cs, 0, 50).call()
    except Exception as e:
        print(f"GMX: Error fetching positions: {e}")
        return []
    
    if not raw_positions:
        return []
    
    # Fetch orders (for SL/TP)
    orders_by_market = {}
    try:
        raw_orders = reader.functions.getAccountOrders(ds, wallet_cs, 0, 100).call()
        for order in raw_orders:
            addresses = order[0]
            numbers = order[1]
            flags = order[2]
            
            order_type = numbers[0]
            market = addresses[5]
            
            # Only care about StopLoss and LimitDecrease (TP)
            if order_type not in (5, 6):
                continue
            
            trigger_price = numbers[4] / 1e30  # GMX uses 30 decimals for USD prices
            size_delta = numbers[2] / 1e30
            is_long = flags[0]
            
            order_info = {
                "type": "take_profit" if order_type == 5 else "stop_loss",
                "trigger_price": trigger_price,
                "size_delta_usd": size_delta,
                "is_long": is_long,
            }
            
            key = market.lower()
            if key not in orders_by_market:
                orders_by_market[key] = []
            orders_by_market[key].append(order_info)
    except Exception as e:
        print(f"GMX: Error fetching orders: {e}")
    
    # Build market cache for token symbols
    market_cache = {}
    
    # Process positions
    positions = []
    for pos in raw_positions:
        addresses = pos[0]
        numbers = pos[1]
        flags = pos[2]
        
        market_addr = addresses[1]
        collateral_token = addresses[2]
        
        size_usd = numbers[0] / 1e30
        size_tokens = numbers[1]
        collateral_amount_raw = numbers[2]
        is_long = flags[0]
        
        if size_usd == 0:
            continue
        
        # Get market info (index token symbol)
        market_key = market_addr.lower()
        if market_key not in market_cache:
            market_cache[market_key] = _get_market_info(w3, reader, ds, market_addr)
        
        market_info = market_cache[market_key]
        index_symbol = market_info.get("index_symbol", "?")
        index_decimals = market_info.get("index_decimals", 18)
        
        # Get collateral token info
        collateral_info = _get_token_info(w3, collateral_token)
        collateral_symbol = collateral_info["symbol"]
        collateral_decimals = collateral_info["decimals"]
        collateral_amount = collateral_amount_raw / (10 ** collateral_decimals)
        
        # Calculate entry price: sizeInUsd / sizeInTokens (adjusted for decimals)
        if size_tokens > 0:
            entry_price = size_usd / (size_tokens / (10 ** index_decimals))
        else:
            entry_price = 0
        
        # Leverage
        leverage = size_usd / collateral_amount if collateral_amount > 0 else 0
        
        # Attach SL/TP orders
        sl_orders = []
        tp_orders = []
        for order in orders_by_market.get(market_key, []):
            if order["is_long"] == is_long:
                if order["type"] == "stop_loss":
                    sl_orders.append(order)
                else:
                    tp_orders.append(order)
        
        positions.append({
            "market": f"{index_symbol}/USD",
            "market_address": market_addr,
            "index_symbol": index_symbol,
            "collateral_symbol": collateral_symbol,
            "collateral_token": collateral_token,
            "size_usd": size_usd,
            "collateral_amount": collateral_amount,
            "entry_price": entry_price,
            "leverage": leverage,
            "is_long": is_long,
            "stop_loss": sl_orders,
            "take_profit": tp_orders,
        })
    
    return positions


# Token info cache
_token_cache = {}

def _get_token_info(w3: Web3, token_addr: str) -> dict:
    """Get symbol and decimals for a token."""
    key = token_addr.lower()
    if key in _token_cache:
        return _token_cache[key]
    # Check known GMX index tokens first
    if key in GMX_INDEX_TOKENS:
        _token_cache[key] = GMX_INDEX_TOKENS[key]
        return _token_cache[key]
    try:
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(token_addr),
            abi=ERC20_ABI
        )
        symbol = contract.functions.symbol().call()
        decimals = contract.functions.decimals().call()
        _token_cache[key] = {"symbol": symbol, "decimals": decimals}
    except Exception:
        _token_cache[key] = {"symbol": "?", "decimals": 18}
    return _token_cache[key]


def _get_market_info(w3: Web3, reader, ds: str, market_addr: str) -> dict:
    """Get index token info for a GMX market."""
    try:
        markets = reader.functions.getMarkets(ds, 0, 500).call()
        for m in markets:
            if m[0].lower() == market_addr.lower():
                index_token = m[1]
                info = _get_token_info(w3, index_token)
                return {
                    "index_token": index_token,
                    "index_symbol": info["symbol"],
                    "index_decimals": info["decimals"],
                    "long_token": m[2],
                    "short_token": m[3],
                }
    except Exception as e:
        print(f"GMX: Error fetching market info: {e}")
    return {"index_symbol": "?", "index_decimals": 18}
