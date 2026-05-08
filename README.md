# DeFi Portfolio Dashboard

A self-hosted DeFi portfolio analytics platform. Tracks token holdings, LP positions, lending, and perpetual hedges across multiple chains and protocols with AI-powered market analysis, automated snapshots, and Telegram notifications.

## Features

### Portfolio Tracking
- Token holdings grouped by asset class (ETH, BTC, Stablecoins, Yield) with chain and wallet filters
- Wallet roles (active / treasury) for separating hot and cold storage
- Bitcoin balance from xpub/ypub/zpub via HD address derivation (Ledger compatible)
- Dust filter toggle and value masking (hide dollar amounts)

### DeFi Positions
- **Uniswap V3** — concentrated liquidity positions with fee tracking, daily APR, and price range visualization
- **Uniswap V2 / Aerodrome / Camelot** — classic AMM positions
- **AAVE V3** — supply/borrow positions with health factor, LTV, and liquidation price
- **GMX V2** — perpetual positions with PnL, leverage, liquidation price, stop-loss/take-profit orders

### Market Data
- Live prices (BTC, ETH, SOL, TAO, SUI) with 24h change
- Funding rates, open interest, and derivatives metrics
- Fear & Greed index, BTC dominance, stablecoin supply
- AAVE/Compound lending rates with 7-day trends
- FRED macro indicators (US10Y, DXY, M2 money supply, Fed Funds rate)

### AI Advisor
- LLM-powered daily market brief with regime detection (bull/bear/sideways probabilities)
- Portfolio assessment (alignment, risk alerts, liquidation warnings)
- Actionable recommendations ranked by priority
- Review of previous recommendations and their outcomes
- Configurable strategy preferences per market regime
- Providers: **OpenAI** (GPT-4o), **Anthropic Claude** (Sonnet, Opus, Haiku), **AWS Bedrock**

### LP Tools
- Impermanent loss calculator
- Monte Carlo range optimizer (regime-mixture model with fee projections)
- Hedge calculator (leverage sizing, capital allocation, breakeven analysis)

### History & Snapshots
- Automated portfolio snapshots every 2 hours
- Market data snapshots every 3 hours
- Portfolio value charts (7d, 30d, 90d, custom range)
- Fee collection history and closed position tracking

### Notifications
- Telegram daily digest (portfolio summary, regime, LP status, risk alerts)
- Configurable schedule (UTC hour)

### Security
- Password-protected with bcrypt hashing
- Rate-limited login (5 attempts per 5 minutes)
- Flask sessions with 24-hour lifetime
- Security headers (X-Frame-Options, CSP, XSS protection)

## Supported Chains

| Chain | Type | Protocols |
|-------|------|-----------|
| Ethereum | EVM (L1) | Uniswap V3, AAVE V3, token holdings |
| Arbitrum | EVM (L2) | Uniswap V3, AAVE V3, GMX V2, Camelot |
| Base | EVM (L2) | Uniswap V3, Aerodrome, AAVE V3 |
| Bitcoin | UTXO | xpub/ypub/zpub balance tracking |

Additional chains (Optimism, Polygon, Avalanche, BSC) are supported via Zerion API for token discovery.

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

On first launch, the app creates `.env` and `wallet_config.json` from templates automatically.

Open `http://localhost:5001` in your browser.

### 3. Set your password

On first visit, you'll see a setup page to create your password. The password is hashed with bcrypt and stored in `.env` as `APP_PASSWORD_HASH`.

Alternatively, set it via CLI:
```bash
python set_password.py
```

### 4. Configure API keys

Go to **Settings** tab in the app, or edit `.env` directly. See the [API Keys](#api-keys) section below.

### 5. Add wallets

Go to **Settings** tab and add your wallet addresses:
- EVM addresses (`0x...`) — scanned on Ethereum, Arbitrum, and Base
- Bitcoin xpub/ypub/zpub keys — BTC balance from Ledger or any HD wallet

## Docker Deployment

```bash
docker-compose up -d
```

The container exposes port `5001` and persists data via Docker volumes:
- `app-data` — SQLite database and snapshots
- `app-config` — `.env` and `wallet_config.json`

On first run, example config files are copied into the config volume automatically.

## API Keys

### Required

| Key | Purpose | Where to get |
|-----|---------|--------------|
| `ETHEREUM_RPC_URL` | Ethereum mainnet RPC | [Alchemy](https://www.alchemy.com) / [Infura](https://www.infura.io) / [QuickNode](https://www.quicknode.com) |
| `ARBITRUM_RPC_URL` | Arbitrum RPC | Same providers above (Arbitrum network) |
| `BASE_RPC_URL` | Base RPC | Same providers above (Base network) |

All three RPC providers offer free tiers sufficient for this app.

### Recommended

| Key | Purpose | Where to get |
|-----|---------|--------------|
| `ETHERSCAN_API_KEY` | LP fee history, position age, tx data | [etherscan.io/apis](https://etherscan.io/apis) (free) |
| `ZERION_API_KEY` | Unified EVM portfolio discovery (tokens, DeFi, lending) | [developers.zerion.io](https://developers.zerion.io) |

### Optional

| Key | Purpose | Where to get |
|-----|---------|--------------|
| `OPENAI_API_KEY` | AI advisor (GPT-4o) | [platform.openai.com](https://platform.openai.com) |
| `ANTHROPIC_API_KEY` | AI advisor (Claude Sonnet/Opus/Haiku) | [console.anthropic.com](https://console.anthropic.com) |
| `AWS_BEARER_TOKEN_BEDROCK` | AI advisor via AWS Bedrock | [AWS Console](https://console.aws.amazon.com/bedrock) |
| `FRED_API_KEY` | Macro indicators (US10Y, DXY, M2, Fed Funds) | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) (free) |
| `COINGECKO_API_KEY` | Price data | [coingecko.com](https://www.coingecko.com/en/api) |
| `ARBISCAN_API_KEY` | Arbitrum tx history | [arbiscan.io/apis](https://arbiscan.io/apis) (free) |
| `BASESCAN_API_KEY` | Base tx history | [basescan.org/apis](https://basescan.org/apis) (free) |

## Architecture

```
web_portfolio.py          Flask app (API + static files)
src/
  connectors/             Chain & protocol integrations
    uniswap_v3.py           Uniswap V3 positions, fees, pools
    uniswap_v2.py           Uniswap V2 pair queries
    aave_v3.py              AAVE V3 lending/borrowing
    gmx_v2.py               GMX V2 perpetuals (Arbitrum)
    aerodrome.py            Aerodrome DEX (Base)
    camelot.py              Camelot DEX (Arbitrum)
    bitcoin.py              BTC xpub/ypub/zpub derivation
    zerion.py               Zerion API client
  engines/                Business logic
    ai_advisor.py           Context building + AI report generation
    llm_providers.py        LLM abstraction (OpenAI, Anthropic, Bedrock)
    range_optimizer.py      Monte Carlo LP range optimization
    snapshot_service.py     Automated snapshot scheduling
    telegram_service.py     Telegram notifications
  storage/
    portfolio_db.py         SQLite schema and queries
  models.py               Shared dataclasses and constants
templates/                HTML (login, setup, main SPA)
static/                   Frontend JS + CSS
data/                     SQLite DB, AI config, runtime state
```

### Tech Stack
- **Backend**: Python 3.11+ / Flask / Gunicorn
- **Frontend**: Vanilla JS, Chart.js, Lucide icons
- **Database**: SQLite (auto-created at `data/portfolio.db`)
- **Auth**: bcrypt + Flask sessions + rate limiting
- **Deployment**: Docker (python:3.11-slim) or local

## Dependencies

### Python packages

| Package | Purpose |
|---------|---------|
| `flask` | Web framework |
| `flask-limiter` | Login rate limiting |
| `web3` | Ethereum/EVM RPC interaction |
| `requests` | HTTP client for external APIs |
| `python-dotenv` | Environment variable management |
| `bcrypt` | Password hashing |
| `hdwallet` | Bitcoin HD wallet address derivation |
| `numpy` | Numerical computing (range optimizer) |
| `anthropic` | Anthropic Claude API client |

### External services

| Service | Used for |
|---------|----------|
| EVM RPC (Alchemy/Infura/QuickNode) | On-chain reads (balances, positions, pool state) |
| Etherscan/Arbiscan/Basescan | Historical transactions, fee events |
| Zerion API | Unified portfolio discovery across chains |
| CoinGecko | Token prices and market data |
| Binance | Funding rates, open interest |
| DeFiLlama | Pool TVL and yield data |
| FRED | US macro economic indicators |
| OpenAI / Anthropic / AWS Bedrock | AI-powered market analysis |
| Telegram Bot API | Daily digest notifications |

## Configuration

### AI Advisor

Configure in **Settings > AI Advisor** or directly in `data/ai_config.json`:

```json
{
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "schedule_utc_hour": 8,
  "auto_enabled": true,
  "custom_system_prompt": "",
  "strategies": {
    "bull": "In bull markets, I prefer...",
    "bear": "In bear markets, I prefer...",
    "sideways": "In sideways markets, I prefer..."
  }
}
```

Supported providers: `openai`, `anthropic`, `bedrock`

### Telegram Notifications

Configure in **Settings > Telegram** or directly in `data/telegram_config.json`:

1. Create a bot via [@BotFather](https://t.me/BotFather)
2. Get your chat ID (send a message to the bot, then check via the Telegram API)
3. Enter bot token and chat ID in settings
4. Use the "Test" button to verify

### Wallet Config

Wallets are stored in `wallet_config.json`:

```json
{
  "0xYourAddress": {
    "label": "metamask",
    "role": "active"
  },
  "xpub6...": {
    "label": "ledger",
    "type": "bitcoin_xpub",
    "role": "treasury"
  }
}
```

Roles: `active` (hot wallet, included in DeFi tracking) or `treasury` (cold storage, shown separately).

## Testing

```bash
pytest
```

## License

Private repository. Not for redistribution.
