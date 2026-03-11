"""AAVE V3 connector — fetches lending/borrowing positions, rates, and health factor."""

from web3 import Web3

# AAVE V3 Pool addresses per chain
POOL_ADDRESSES = {
    "ethereum": "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
    "arbitrum": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
    "base": "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5",
}

# AAVE V3 PoolDataProvider addresses per chain
DATA_PROVIDER_ADDRESSES = {
    "ethereum": "0x7B4EB56E7CD4b454BA8ff71E4518426c8ef69ba3",
    "arbitrum": "0x69FA688f1Dc47d4B5d8029D5a35FB7a548310654",
    "base": "0x2d8A3C5677189723C4cB8873CfC9C8976FDF38Ac",
}

# Minimal ABIs
POOL_ABI = [
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "getUserAccountData",
        "outputs": [
            {"name": "totalCollateralBase", "type": "uint256"},
            {"name": "totalDebtBase", "type": "uint256"},
            {"name": "availableBorrowsBase", "type": "uint256"},
            {"name": "currentLiquidationThreshold", "type": "uint256"},
            {"name": "ltv", "type": "uint256"},
            {"name": "healthFactor", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

DATA_PROVIDER_ABI = [
    {
        "inputs": [],
        "name": "getAllReservesTokens",
        "outputs": [
            {
                "components": [
                    {"name": "symbol", "type": "string"},
                    {"name": "tokenAddress", "type": "address"},
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
            {"name": "asset", "type": "address"},
            {"name": "user", "type": "address"},
        ],
        "name": "getUserReserveData",
        "outputs": [
            {"name": "currentATokenBalance", "type": "uint256"},
            {"name": "currentStableDebt", "type": "uint256"},
            {"name": "currentVariableDebt", "type": "uint256"},
            {"name": "principalStableDebt", "type": "uint256"},
            {"name": "scaledVariableDebt", "type": "uint256"},
            {"name": "stableBorrowRate", "type": "uint256"},
            {"name": "liquidityRate", "type": "uint256"},
            {"name": "stableRateLastUpdated", "type": "uint40"},
            {"name": "usageAsCollateralEnabled", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "asset", "type": "address"}],
        "name": "getReserveData",
        "outputs": [
            {"name": "unbacked", "type": "uint256"},
            {"name": "accruedToTreasuryScaled", "type": "uint256"},
            {"name": "totalAToken", "type": "uint256"},
            {"name": "totalStableDebt", "type": "uint256"},
            {"name": "totalVariableDebt", "type": "uint256"},
            {"name": "liquidityRate", "type": "uint256"},
            {"name": "variableBorrowRate", "type": "uint256"},
            {"name": "stableBorrowRate", "type": "uint256"},
            {"name": "averageStableBorrowRate", "type": "uint256"},
            {"name": "liquidityIndex", "type": "uint256"},
            {"name": "variableBorrowIndex", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "asset", "type": "address"}],
        "name": "getReserveConfigurationData",
        "outputs": [
            {"name": "decimals", "type": "uint256"},
            {"name": "ltv", "type": "uint256"},
            {"name": "liquidationThreshold", "type": "uint256"},
            {"name": "liquidationBonus", "type": "uint256"},
            {"name": "reserveFactor", "type": "uint256"},
            {"name": "usageAsCollateralEnabled", "type": "bool"},
            {"name": "borrowingEnabled", "type": "bool"},
            {"name": "stableBorrowRateEnabled", "type": "bool"},
            {"name": "isActive", "type": "bool"},
            {"name": "isFrozen", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

RAY = 10**27  # AAVE uses RAY (1e27) for rates


def get_aave_positions(w3: Web3, wallet: str, chain: str) -> dict | None:
    """Fetch AAVE V3 positions for a wallet on a given chain.
    
    Returns None if AAVE is not deployed on this chain or wallet has no positions.
    Returns dict with account summary and per-asset positions.
    """
    if chain not in POOL_ADDRESSES:
        return None
    
    pool_addr = POOL_ADDRESSES[chain]
    dp_addr = DATA_PROVIDER_ADDRESSES[chain]
    
    pool = w3.eth.contract(
        address=Web3.to_checksum_address(pool_addr),
        abi=POOL_ABI
    )
    data_provider = w3.eth.contract(
        address=Web3.to_checksum_address(dp_addr),
        abi=DATA_PROVIDER_ABI
    )
    
    wallet_cs = Web3.to_checksum_address(wallet)
    
    # Get account summary
    try:
        account = pool.functions.getUserAccountData(wallet_cs).call()
    except Exception as e:
        print(f"AAVE: Error fetching account data on {chain}: {e}")
        return None
    
    total_collateral = account[0] / 1e8
    total_debt = account[1] / 1e8
    available_borrows = account[2] / 1e8
    liq_threshold = account[3] / 100
    ltv = account[4] / 100
    health_factor = account[5] / 1e18
    
    if total_collateral == 0 and total_debt == 0:
        return None
    
    # Get all reserve tokens
    try:
        reserves = data_provider.functions.getAllReservesTokens().call()
    except Exception as e:
        print(f"AAVE: Error fetching reserves on {chain}: {e}")
        reserves = []
    
    supplied = []
    borrowed = []
    
    for symbol, token_addr in reserves:
        try:
            user_data = data_provider.functions.getUserReserveData(
                Web3.to_checksum_address(token_addr), wallet_cs
            ).call()
            
            a_token_bal = user_data[0]      # supplied amount (in token decimals)
            stable_debt = user_data[1]       # stable borrow
            variable_debt = user_data[2]     # variable borrow
            collateral_enabled = user_data[8]
            
            # Skip if no position in this asset
            if a_token_bal == 0 and stable_debt == 0 and variable_debt == 0:
                continue
            
            # Get reserve config for decimals and params
            config = data_provider.functions.getReserveConfigurationData(
                Web3.to_checksum_address(token_addr)
            ).call()
            decimals = config[0]
            asset_ltv = config[1] / 100       # basis points to %
            asset_liq_threshold = config[2] / 100
            
            # Get reserve rates
            reserve_data = data_provider.functions.getReserveData(
                Web3.to_checksum_address(token_addr)
            ).call()
            supply_rate = reserve_data[5] / RAY * 100    # APY %
            variable_borrow_rate = reserve_data[6] / RAY * 100
            stable_borrow_rate = reserve_data[7] / RAY * 100
            
            if a_token_bal > 0:
                balance = a_token_bal / (10 ** decimals)
                supplied.append({
                    "symbol": symbol,
                    "token_address": token_addr,
                    "balance": balance,
                    "supply_apy": supply_rate,
                    "collateral_enabled": collateral_enabled,
                    "ltv": asset_ltv,
                    "liquidation_threshold": asset_liq_threshold,
                })
            
            total_borrow = stable_debt + variable_debt
            if total_borrow > 0:
                balance = total_borrow / (10 ** decimals)
                borrow_rate = variable_borrow_rate if variable_debt > stable_debt else stable_borrow_rate
                borrowed.append({
                    "symbol": symbol,
                    "token_address": token_addr,
                    "balance": balance,
                    "borrow_apy": borrow_rate,
                    "is_variable": variable_debt > stable_debt,
                })
                
        except Exception as e:
            print(f"AAVE: Error fetching {symbol} on {chain}: {e}")
            continue
    
    return {
        "chain": chain,
        "total_collateral_usd": total_collateral,
        "total_debt_usd": total_debt,
        "available_borrows_usd": available_borrows,
        "ltv": ltv,
        "liquidation_threshold": liq_threshold,
        "health_factor": health_factor,
        "supplied": supplied,
        "borrowed": borrowed,
    }
