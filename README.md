# DeFi Portfolio Analyzer

## Supported Protocols

### Chains
- Ethereum
- Arbitrum
- Base

### DEX Protocols
- **Uniswap V3** - Full support (positions, fees, price ranges)
- **Uniswap V2** - Connector implemented
- **Camelot** (Arbitrum) - Connector implemented
- **Aerodrome** (Base) - Connector implemented

### Token Support
- Native tokens (ETH)
- ERC-20 tokens
- LP position NFTs (Uniswap V3)

## Fee Tracking (Uniswap V3)
- Uncollected fees (real-time calculation)
- Collected fees (historical via event logs)
- Total lifetime earnings

## External API Dependencies

### Required
- **Alchemy API** - RPC provider, token balances
  - `ALCHEMY_API_KEY` required in `.env`
  - Endpoints: `eth-mainnet`, `arb-mainnet`, `base-mainnet`

### Optional (Recommended)
- **Block Explorer APIs** - Accurate position age tracking
  - `ETHERSCAN_API_KEY` (Ethereum)
  - `ARBISCAN_API_KEY` (Arbitrum)
  - `BASESCAN_API_KEY` (Base)
  - See [ETHERSCAN_API_SETUP.md](ETHERSCAN_API_SETUP.md) for setup instructions
  - Without these: Falls back to RPC (limited to recent blocks, may estimate age)

### Optional
- **DeFiLlama** - Token price data
  - No API key required
  - Endpoint: `https://coins.llama.fi/prices/current/{chain}:{address}`

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Add your ALCHEMY_API_KEY and RPC URLs

# Run CLI
python check_full_portfolio.py

# Run web app
python web_portfolio.py
```

## Configuration Files
- `.env` - API keys and RPC URLs
- `wallet_config.json` - Wallet addresses and labels
