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
- **Aerodrome Slipstream** (Base) — concentrated liquidity with full enrichment: fee tier, range, age, swap fees, and AERO staking rewards (pending + claimed via DB delta-detection). Includes gauge-staked NFTs that Zerion alone can't enrich.
- **Uniswap V2 / Aerodrome (V2-style) / Camelot** — classic AMM positions
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
| Base | EVM (L2) | Uniswap V3, Aerodrome Slipstream (CL + AERO rewards), Aerodrome (V2), AAVE V3 |
| Bitcoin | UTXO | xpub/ypub/zpub balance tracking |

Additional chains (Optimism, Polygon, Avalanche, BSC) are supported via Zerion API for token discovery.

## Quick Start (Docker — preferred)

Docker is the recommended way to run the dashboard: it bundles Python, dependencies, and gunicorn in a single container, persists your config and DB on Docker volumes, and survives reboots and updates.

### 1. Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose (Docker Desktop on macOS/Windows already includes both).
- A free RPC API key — sign up at [Alchemy](https://www.alchemy.com) or [Infura](https://www.infura.io). One key works across Ethereum, Arbitrum, and Base.
- A Zerion API key (see [API Keys](#api-keys)).

### 2. Clone and start

```bash
git clone https://github.com/rockyale/defi-portfolio-poc.git
cd defi-portfolio-poc
docker compose up -d --build
```

`-d` runs detached; `--build` builds the image from the `Dockerfile` on first launch (and after code changes).

### 3. Open the dashboard

Open `http://localhost:5001` in your browser. On first visit you'll be prompted to create a password (bcrypt-hashed, stored on the `app-config` volume).

### 4. Configure RPC, API keys, and wallets in the UI

Go to **Settings** in the dashboard:

- **RPC Endpoints** — pick **Alchemy** or **Infura** in the dropdown for each chain (Ethereum / Arbitrum / Base) and paste your API key. The same key works across all three chains. For self-hosted nodes or other providers, choose **Custom URL** and paste the full URL.
- **API Keys** — paste your Zerion key (required), Etherscan (recommended), FRED, and one AI provider key. See [API Keys](#api-keys) for what each does.
- **Wallets** — add the wallets you want to track: EVM addresses (`0x…`) and/or Bitcoin xpub/ypub/zpub keys.

### Common Docker commands

```bash
docker compose logs -f           # follow logs
docker compose restart           # restart after settings change (rarely needed)
docker compose pull && docker compose up -d --build   # update to latest code
docker compose down              # stop the app (volumes preserved)
docker compose down -v           # stop AND wipe volumes (deletes config + DB)
```

### Volumes and data layout

Two named Docker volumes persist state across rebuilds:

| Volume | Mount path | Contents |
|--------|-----------|----------|
| `app-config` | `/app/config` | `.env`, `wallet_config.json` |
| `app-data`   | `/app/data`   | `portfolio.db` (SQLite), AI config, runtime state |

On first run the entrypoint seeds `.env` and `wallet_config.json` from the bundled examples — the UI handles the rest.

To back up or restore, use **Settings → Backup & Restore** in the UI: *Export DB* downloads the SQLite database, *Export Settings* downloads a JSON bundle of API keys and wallet config, and the matching Import buttons restore them.

## Alternative: Run with Python (venv)

If you prefer to run without Docker — for example to debug or develop — install dependencies into a virtualenv and start the Flask dev server. This path is **not** recommended for ongoing use.

```bash
git clone https://github.com/rockyale/defi-portfolio-poc.git
cd defi-portfolio-poc
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python web_portfolio.py
```

On first launch, `.env` and `wallet_config.json` are created from the bundled examples in the project directory. Open `http://localhost:5001`, follow the same setup flow as Docker (password, API keys in Settings, wallets).

## API Keys

Almost everything is configured through the **Settings** tab in the UI, which writes to `.env`. You can also edit `.env` directly if you prefer.

### Required

| Key | Purpose | Where to set | Where to get |
|-----|---------|--------------|--------------|
| `ETHEREUM_RPC_URL`, `ARBITRUM_RPC_URL`, `BASE_RPC_URL` | On-chain reads — needed for LP position analytics (range, fees, age, APR), AAVE health factor, AERO staking rewards, GMX V2 perpetuals, and ETH gas price. Without them, only the high-level Zerion data is shown. | Settings → RPC Endpoints | A free [Alchemy](https://www.alchemy.com) or [Infura](https://www.infura.io) account. The same API key works across all three chains. Self-hosted or other providers: pick **Custom URL** and paste the full URL. |
| `ZERION_API_KEY` | Unified EVM portfolio discovery (tokens, DeFi positions, lending). The app's main data source for cross-chain holdings — without it, no tokens, no lending, and no LP positions are surfaced. | Settings → API Keys | [developers.zerion.io](https://developers.zerion.io) |

### Recommended

| Key | Purpose | Where to set | Where to get |
|-----|---------|--------------|--------------|
| `ETHERSCAN_API_KEY` | LP fee history, position age, on-chain event scans. Single key works across Ethereum, Arbitrum, and Base via the Etherscan V2 multichain API — separate Arbiscan/Basescan keys are not needed. | Settings → API Keys | [etherscan.io/apis](https://etherscan.io/apis) (free) |
| `FRED_API_KEY` | Macro indicators (US10Y, DXY, M2, Fed Funds). Without it, the macro section of the AI Daily Brief is skipped. | Settings → API Keys | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) (free) |

### AI Advisor — pick one (all paid)

The AI Daily Brief and digest features need exactly one LLM provider configured. You don't need all three — pick whichever you already have an account with. All are configurable via Settings → API Keys.

| Key | Provider | Where to get |
|-----|----------|--------------|
| `OPENAI_API_KEY` | OpenAI (GPT-4o and similar) | [platform.openai.com](https://platform.openai.com) |
| `ANTHROPIC_API_KEY` | Anthropic Claude (Sonnet / Opus / Haiku) | [console.anthropic.com](https://console.anthropic.com) |
| `AWS_BEARER_TOKEN_BEDROCK` (+ optional `AWS_REGION`) | AWS Bedrock — Claude models via your AWS account | [AWS Console → Bedrock](https://console.aws.amazon.com/bedrock) |

If no AI provider is configured, the rest of the dashboard still works — you simply won't see AI-generated content.

### Free APIs used without configuration

The app calls a handful of public, no-key endpoints automatically. You don't need to register or do anything — they're listed here so you know where the data comes from.

| Service | Endpoint | Used for |
|---|---|---|
| CoinGecko (anonymous) | `api.coingecko.com` | Token spot prices, BTC/ETH 30d & 200d price history (returns + realized vol), global market cap and BTC/ETH dominance |
| DefiLlama Coins | `coins.llama.fi` | Token price lookup by chain+address (used as a price fallback) |
| DefiLlama Yields | `yields.llama.fi/pools` | LP pool TVL and APY for the range optimizer |
| DefiLlama Stablecoins | `stablecoins.llama.fi` | Total stablecoin supply across chains |
| DefiLlama TVL | `api.llama.fi/v2/historicalChainTvl` | Aggregate DeFi TVL series |
| Bybit | `api.bybit.com` | BTC/ETH/SOL funding rate and open interest |
| Deribit | `www.deribit.com` | BTC index price |
| Alternative.me | `api.alternative.me/fng` | Crypto Fear & Greed Index |
| Yahoo Finance | `query1.finance.yahoo.com` | DXY (US dollar index) snapshot |
| Blockstream Esplora | `blockstream.info/api` | BTC balance lookups for xpub/ypub/zpub-derived addresses |

## Architecture

```
web_portfolio.py          Flask app (API + static files)
src/
  connectors/             Chain & protocol integrations
    uniswap_v3.py           Uniswap V3 positions, fees, pools
    uniswap_v2.py           Uniswap V2 pair queries
    aave_v3.py              AAVE V3 lending/borrowing
    gmx_v2.py               GMX V2 perpetuals (Arbitrum)
    aerodrome.py            Aerodrome V2 pairs (Base)
    aerodrome_slipstream.py Aerodrome concentrated liquidity + CL gauge staking (Base)
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

| Service | Used for | Configured? |
|---------|----------|-------------|
| EVM RPC endpoints (Alchemy / Infura / your node) | On-chain reads (balances, positions, pool state) | Yes — Settings UI |
| Etherscan V2 (multichain) | Historical transactions, fee events across Ethereum / Arbitrum / Base | Yes — Settings UI |
| Zerion API | Unified portfolio discovery across chains | Yes — Settings UI |
| FRED | US macro indicators (US10Y, DXY, M2, Fed Funds) | Yes — Settings UI |
| OpenAI / Anthropic / AWS Bedrock | AI-powered market analysis (one of the three) | Yes — Settings UI |
| Telegram Bot API | Daily digest notifications | Yes — Settings UI |
| CoinGecko | Token prices, BTC/ETH history, market cap & dominance | No — anonymous |
| DefiLlama (coins / yields / stablecoins / TVL) | Token price fallback, LP pool TVL+APY, stablecoin supply, total DeFi TVL | No — anonymous |
| Bybit | BTC/ETH/SOL funding rate and open interest | No — anonymous |
| Deribit | BTC index price | No — anonymous |
| Alternative.me | Crypto Fear & Greed Index | No — anonymous |
| Yahoo Finance | DXY snapshot | No — anonymous |
| Blockstream Esplora | BTC balance lookups for xpub/ypub/zpub addresses | No — anonymous |

## Configuration

All configuration is done through the **Settings** tab in the UI. The sections below describe what to fill in and where the values are persisted.

### AI Advisor Configuration

Open the **AI Advisor Configuration** view in Settings (the API key itself is set under [API Keys](#api-keys), not here). Fill in:

- **Provider** — `OpenAI`, `Claude (Anthropic)`, or `AWS Bedrock`. Match this to whichever AI provider key you saved under API Keys.
- **Model** — exact model identifier for the chosen provider (e.g. `gpt-4o`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`).
- **Schedule (UTC hour)** — when the daily brief auto-runs.
- **Auto-generate** — toggle the daily run on/off.
- **Custom Instructions** — free-text field for your DeFi strategy and any standing guidance you want appended to every AI prompt.
- **Strategy Preferences** — three textareas (Bull / Bear / Sideways) for regime-specific guidance.

Stored at `data/ai_config.json` on the `app-data` Docker volume (or `./data/ai_config.json` on bare-metal).

### Telegram Notifications

Open **Settings → Telegram** and enter your bot token and chat ID, then click **Send Test Message**. To create the bot, follow Telegram's official guide: [How do I create a bot?](https://core.telegram.org/bots#how-do-i-create-a-bot) — talk to [@BotFather](https://t.me/BotFather), pick a name, and copy the token it gives you. Your chat ID can be found via the `getUpdates` endpoint after you send your bot a first message.

Stored at `data/telegram_config.json`.

### Wallets

Add wallets in **Settings → Wallets**. Supported types:
- EVM addresses (`0x…`) — scanned on Ethereum, Arbitrum, and Base.
- Bitcoin xpub/ypub/zpub — balance is derived from HD addresses (Ledger and other HD wallets supported).

Each wallet has a label and a role: `active` (hot wallet, included in DeFi tracking) or `treasury` (cold storage, shown separately). Stored at `wallet_config.json` on the `app-config` volume (or `./wallet_config.json` on bare-metal).

## License

Private repository. Not for redistribution.
