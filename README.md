# DeFi Portfolio Dashboard

A unified DeFi dashboard for tracking your portfolio across multiple chains, LP positions, lending/borrowing, and perpetual hedges.

## Features

- **Portfolio Tracker** — Token holdings grouped by asset type (ETH, BTC, Stablecoins, Yield), with chain and wallet filters
- **LP Positions** — Uniswap V3 positions with fee tracking, APR, and price range visualization
- **Bitcoin (Ledger)** — BTC balance from xpub/ypub/zpub key via address derivation
- **AAVE V3** — Lending/borrowing positions with health factor, LTV, and liquidation price
- **GMX V2** — Perpetual positions with PnL, leverage, liquidation price, stop-loss/take-profit orders
- **Market Data** — Live prices, funding rates, fear & greed index
- **LP Tools** — IL calculator, range optimizer (Monte Carlo), hedge calculator
- **History** — Portfolio snapshots with charts over time
- **Authentication** — Password-protected with bcrypt hashing and rate limiting
- **Value Masking** — Hide dollar amounts with one click

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/rockyale/defi-portfolio-poc.git
cd defi-portfolio-poc
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run the app

```bash
python web_portfolio.py
```

On first launch, the app automatically creates `.env` and `wallet_config.json` from templates.

Open `http://localhost:5001` in your browser.

### 3. Set your password

On first visit, you'll see a setup page to create your password. This password is hashed with bcrypt and stored in `.env` as `APP_PASSWORD_HASH`.

Alternatively, set it via CLI:
```bash
python set_password.py
```

### 4. Configure API keys

Go to **Settings** tab in the app, or edit `.env` directly:

```
ALCHEMY_API_KEY=your_key_here
ETHERSCAN_API_KEY=your_key_here
ETHEREUM_RPC_URL=https://eth-mainnet.g.alchemy.com/v2/your_key
ARBITRUM_RPC_URL=https://arb-mainnet.g.alchemy.com/v2/your_key
BASE_RPC_URL=https://base-mainnet.g.alchemy.com/v2/your_key
```

### 5. Add wallets

Go to **Settings** tab and add your wallet addresses. Supports:
- Ethereum addresses (`0x...`) — scanned on Ethereum, Arbitrum, and Base
- Bitcoin xpub/ypub/zpub keys — BTC balance from Ledger or any HD wallet

## API Keys

| Key | Required | Purpose |
|-----|----------|---------|
| `ALCHEMY_API_KEY` | Yes | RPC access for Ethereum, Arbitrum, Base |
| `ETHERSCAN_API_KEY` | Recommended | LP fee history, position age (free tier works) |
| `BRAVE_API_KEY` | Optional | Token discovery features |

Get free keys at:
- Alchemy: https://www.alchemy.com
- Etherscan: https://etherscan.io/apis

## Architecture

- **Backend**: Python/Flask serving API endpoints + static files
- **Frontend**: Vanilla JS with Chart.js, single-page tab-based UI
- **Database**: SQLite for portfolio snapshots
- **Auth**: bcrypt password hashing, Flask sessions, rate-limited login

Designed to run locally or deploy to AWS (App Runner, ECS Fargate).
