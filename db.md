# Database Schema

SQLite database at `data/portfolio.db`, configured with `journal_mode=WAL` and `foreign_keys=ON`. All user-scoped tables include `user_id` for future multi-user support (currently always `1`).

Schema is created and migrated by `src/storage/portfolio_db.py:init_db()` on every startup — `CREATE TABLE IF NOT EXISTS` for the base schema plus an idempotent migrations list (`ALTER TABLE … ADD COLUMN`) that handles incremental column additions without losing data.

## Tables

### `users`
Single default user for now. The login password is bcrypt-hashed in `.env` (`APP_PASSWORD_HASH`), not in the DB.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| username | TEXT UNIQUE | Default row: `'default'` |
| created_at | TIMESTAMP | |

### `portfolio_snapshots`
Master record per snapshot run. Scheduled every 2 hours by `snapshot_service.py`.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| user_id | INTEGER FK → users | |
| timestamp | TIMESTAMP | |
| wallet | TEXT | EVM address or xpub |
| total_value_usd | REAL | tokens + lp + lending_net + hedge_collateral |
| total_tokens_usd | REAL | Token holdings only |
| total_lp_usd | REAL | LP positions only |
| total_lending_usd | REAL | Net (collateral − debt) |
| total_hedge_collateral_usd | REAL | GMX/perp margin locked |
| status | TEXT | pending / completed / failed |
| duration_seconds | REAL | |

### `token_snapshots`
Per-token balance at each snapshot.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| snapshot_id | INTEGER FK → portfolio_snapshots | |
| user_id | INTEGER FK → users | |
| timestamp | TIMESTAMP | |
| wallet | TEXT | |
| chain | TEXT | ethereum / arbitrum / base / bitcoin |
| symbol | TEXT | ETH, WETH, USDC, BTC, etc. |
| token_address | TEXT | Contract address (null for native/BTC) |
| balance | REAL | Token amount held |
| price_usd | REAL | Price per 1 token |
| value_usd | REAL | balance × price_usd |
| entry_price | REAL | Price when first seen in any snapshot. Carried forward. |

### `lp_snapshots`
LP positions at each snapshot.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| snapshot_id | INTEGER FK → portfolio_snapshots | |
| user_id | INTEGER FK → users | |
| timestamp | TIMESTAMP | |
| wallet | TEXT | |
| chain | TEXT | |
| protocol | TEXT | `uniswap_v3` / `aerodrome_slipstream` / `aerodrome_v3` (legacy) / `camelot` / `manual` |
| position_id | TEXT | NFT token ID or unique identifier |
| token0 | TEXT | Symbol |
| token1 | TEXT | Symbol |
| fee_tier | REAL | e.g. 0.05, 0.3, 1.0 |
| amount0 | REAL | Token0 amount in position |
| amount1 | REAL | Token1 amount in position |
| price0_usd | REAL | Token0 price at snapshot |
| price1_usd | REAL | Token1 price at snapshot |
| value_usd | REAL | amount0 × price0 + amount1 × price1 |
| entry_value_usd | REAL | Value at first snapshot of this position. Migration-added. |
| range_lower | REAL | |
| range_upper | REAL | |
| current_price | REAL | |
| in_range | BOOLEAN | |
| fees_uncollected_usd | REAL | Live `earned()` value at snapshot time |
| fees_collected_usd | REAL | High-water-mark grown by snapshot delta-detection |
| total_earned_fees_usd | REAL | collected + uncollected |
| daily_apr | REAL | Includes AERO rewards when present |
| monthly_apr | REAL | |
| reward_symbol | TEXT | `AERO` for Aerodrome staked positions; null otherwise |
| reward_pending | REAL | Pending reward token amount (raw, not USD) |
| reward_pending_usd | REAL | USD value of pending reward |
| reward_claimed_total | REAL | Cumulative claimed reward amount (delta-detection) |
| reward_claimed_total_usd | REAL | USD value of claimed reward |

The five reward columns are populated by Aerodrome Slipstream enrichment via the CL gauge's `earned()` and `rewardToken()` methods. `reward_claimed_total` is a high-water-mark — when `reward_pending` drops between consecutive snapshots, the diff is added to `reward_claimed_total`.

### `hedge_snapshots`
Perpetual positions (GMX V2, Hyperliquid, etc.) at each snapshot.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| snapshot_id | INTEGER FK → portfolio_snapshots | |
| user_id | INTEGER FK → users | |
| timestamp | TIMESTAMP | |
| wallet | TEXT | |
| exchange | TEXT | gmx_v2 / hyperliquid / dydx |
| market | TEXT | BTC/USD, ETH/USD |
| direction | TEXT | long / short |
| size_usd | REAL | Notional position size |
| collateral_usd | REAL | Margin locked |
| entry_price | REAL | |
| current_price | REAL | |
| liquidation_price | REAL | |
| pnl_usd | REAL | Unrealized PnL |
| pnl_pct | REAL | PnL as % of collateral |
| leverage | REAL | |
| stop_loss_price | REAL | Null if none |
| take_profit_price | REAL | Null if none |

### `lending_snapshots`
Per-asset lending/borrowing rows (one row per supplied or borrowed asset).

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| snapshot_id | INTEGER FK → portfolio_snapshots | |
| user_id | INTEGER FK → users | |
| timestamp | TIMESTAMP | |
| wallet | TEXT | |
| chain | TEXT | |
| protocol | TEXT | aave_v3 |
| side | TEXT | supply / borrow |
| symbol | TEXT | USDC, ETH, etc. |
| token_address | TEXT | |
| balance | REAL | Amount supplied or borrowed |
| price_usd | REAL | |
| value_usd | REAL | |
| apy | REAL | Supply APY or borrow APY |
| collateral_enabled | BOOLEAN | Supply side only |
| is_variable | BOOLEAN | Borrow side only |

### `lending_account_snapshots`
Account-level lending summary (health factor, LTV) per wallet/chain.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| snapshot_id | INTEGER FK → portfolio_snapshots | |
| user_id | INTEGER FK → users | |
| timestamp | TIMESTAMP | |
| wallet | TEXT | |
| chain | TEXT | |
| protocol | TEXT | |
| total_collateral_usd | REAL | |
| total_debt_usd | REAL | |
| health_factor | REAL | |
| ltv | REAL | Current LTV % |
| liquidation_threshold | REAL | Max before liquidation % |

### `market_snapshots`
Market data captured every 3 hours UTC by `snapshot_service.py`.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| timestamp | TIMESTAMP | |
| session | TEXT | `asia` (00, 03 UTC) / `europe` (06, 09) / `us` (12, 15) / `evening` (18, 21) |
| btc_price, eth_price, sol_price, tao_price, sui_price | REAL | Spot prices (CoinGecko) |
| btc_dominance, eth_dominance | REAL | % |
| total_market_cap | REAL | |
| total_volume_24h | REAL | |
| stablecoin_supply | REAL | DeFiLlama total |
| fear_greed_index | INTEGER | 0–100 |
| btc_funding_rate, eth_funding_rate, sol_funding_rate | REAL | Per-period rate (Bybit) |
| btc_open_interest, eth_open_interest | REAL | USD |
| btc_index_price | REAL | Deribit |
| eth_btc_ratio | REAL | |
| total_defi_tvl | REAL | DeFiLlama |
| eth_gas_price | REAL | Gwei (RPC `eth_gasPrice`) |
| eth_staking_apr | REAL | % |
| aave_usdc_supply_apy, aave_usdc_borrow_apy | REAL | % |
| eth_usdc_fee_apr, wbtc_usdc_fee_apr | REAL | % — DeFiLlama yields |
| lending_rates_json | TEXT | JSON snapshot of full lending-rates table |
| lp_pools_json | TEXT | JSON snapshot of LP pool TVL/APY data |
| btc_vol_30d, eth_vol_30d | REAL | 30-day annualized realized volatility |
| btc_return_7d, btc_return_30d | REAL | % return over window |
| eth_return_7d, eth_return_30d | REAL | % return over window |
| btc_range_14d, eth_range_14d | REAL | (high − low) / current as % over 14 days |
| btc_200d_ma | REAL | BTC 200-day moving average |

Several derived metrics (returns, vol, ranges, 200d MA) are **persisted** in this table — they're computed by snapshot_service from CoinGecko market_chart data at snapshot time, not derived on the fly at query time.

### `token_prices_daily`
Daily price data for tracked tokens. Once per day at 00:00 UTC.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| timestamp | TIMESTAMP | Date (00:00 UTC) |
| symbol | TEXT | BTC, ETH, SOL, TAO, SUI |
| price_usd | REAL | |
| high_24h | REAL | For range/volatility calculations |
| low_24h | REAL | |
| volume_24h | REAL | |

Unique constraint on (timestamp, symbol).

### `defi_rates`
Per-asset, per-chain lending and LP rates from DeFiLlama Yields. Refreshed each market snapshot.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| timestamp | TIMESTAMP | |
| chain | TEXT | ethereum / arbitrum / base / etc. |
| protocol | TEXT | aave-v3 / uniswap-v3 / aerodrome-slipstream / etc. |
| asset | TEXT | USDC, WETH, etc. |
| rate_type | TEXT | `lending` / `lp` |
| supply_apy | REAL | Lending side |
| borrow_apy | REAL | Lending side |
| fee_apr | REAL | LP swap-fee APR |
| reward_apr | REAL | LP token incentives |
| tvl | REAL | Pool/market TVL |
| volume_1d | REAL | LP 24h volume (migration-added) |

### `lp_positions`
Current state of all LP positions — both auto-detected and manually entered. (Replaces the older `manual_positions` table; that table still exists as a stub.)

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| user_id | INTEGER FK → users | |
| source | TEXT | `auto` or `manual` |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |
| wallet | TEXT | Wallet address (for auto) |
| chain | TEXT | |
| protocol | TEXT | uniswap_v3 / aerodrome_slipstream / camelot / manual |
| position_id | TEXT | NFT token ID or user-defined |
| token0, token1 | TEXT | Symbols |
| fee_tier | REAL | |
| amount0, amount1 | REAL | Token amounts |
| price0_usd, price1_usd | REAL | Token prices |
| value_usd | REAL | Current total value |
| entry_value_usd | REAL | Value at creation |
| range_lower, range_upper | REAL | |
| current_price | REAL | Token1 per token0 |
| in_range | BOOLEAN | |
| fees_uncollected_usd, fees_collected_usd | REAL | |
| total_earned_fees_usd | REAL | High water mark |
| daily_apr, monthly_apr | REAL | |
| notes | TEXT | |
| is_active | BOOLEAN | Default true |

### `hedge_positions`
Current state of all hedge/perp positions — both auto-detected (GMX) and manually entered.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| user_id | INTEGER FK → users | |
| source | TEXT | `auto` or `manual` |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |
| wallet | TEXT | |
| exchange | TEXT | gmx_v2 / hyperliquid / bybit |
| market | TEXT | e.g. BTC/USD |
| direction | TEXT | long / short |
| margin_usd | REAL | Collateral amount |
| leverage | REAL | |
| size_usd | REAL | margin × leverage |
| entry_price | REAL | |
| current_price | REAL | Live-updated |
| liquidation_price | REAL | Calculated |
| pnl_usd | REAL | |
| pnl_pct | REAL | % of margin |
| stop_loss_price | REAL | Optional |
| take_profit_price | REAL | Optional |
| notes | TEXT | |
| is_active | BOOLEAN | Default true |

### `ai_reports`
LLM-generated portfolio analysis reports. One row per `/api/ai/generate` call (manual or scheduled).

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| user_id | INTEGER FK → users | |
| timestamp | TIMESTAMP | UTC time of generation |
| provider | TEXT | openai / anthropic / bedrock |
| model | TEXT | Model ID used |
| market_regime_json | TEXT | Regime block JSON (bull/bear/sideways probabilities + reasoning) |
| portfolio_alignment | TEXT | aligned / partially_aligned / misaligned |
| summary | TEXT | Market analysis summary |
| full_report_json | TEXT | Complete JSON report |
| previous_recs_review_json | TEXT | LLM's review of last report's recommendations |
| prompt_tokens | INTEGER | Input tokens (provider-reported) |
| completion_tokens | INTEGER | Output tokens |
| data_freshness_json | TEXT | Per-section freshness map (live / db age / failed) |

### `daily_digests`
DB-driven daily digest, generated without an LLM. Used by both the dashboard's quick-summary view and the Telegram daily message.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| user_id | INTEGER FK → users | |
| timestamp | TIMESTAMP | |
| total_value_usd | REAL | |
| value_change_24h_pct | REAL | |
| value_change_24h_usd | REAL | |
| positions_opened | TEXT | JSON list |
| positions_closed | TEXT | JSON list |
| positions_out_of_range | TEXT | JSON list |
| hedge_health_json | TEXT | JSON of hedge PnL / liquidation distance |
| total_fees_usd | REAL | Across all LPs |
| average_apr | REAL | Weighted by position value |
| digest_json | TEXT | Full digest payload (renders into Telegram + dashboard) |

### `manual_positions`, `manual_hedges`
Empty stub tables kept for backward compatibility with old database imports. Live data has moved to `lp_positions` and `hedge_positions`.

## Snapshot Schedule

| Data | Frequency | Code |
|------|-----------|------|
| Portfolio snapshot | Every 2 hours | `PORTFOLIO_INTERVAL = 7200` in `snapshot_service.py` |
| Market data | Every 3 hours UTC | `MARKET_SNAPSHOT_HOURS = [0, 3, 6, 9, 12, 15, 18, 21]` |
| Token daily prices | Once per day at 00:00 UTC | `snapshot_service.py` |
| AI report | Once per day at configured UTC hour | `ai_config.json:schedule_utc_hour` (default 8). Requires `auto_enabled: true`. |
| Daily digest | Once per day, before Telegram send | Triggered by `ai_report_loop` |
| Telegram message | Once per day at configured UTC hour | `telegram_config.json:schedule_utc_hour` |

Session labels for `market_snapshots`:

| UTC hour | Session |
|---|---|
| 00, 03 | asia |
| 06, 09 | europe |
| 12, 15 | us |
| 18, 21 | evening |

## Indexes

Created in `init_db()`:

- `portfolio_snapshots`: `(user_id, timestamp)`, `(user_id, wallet, timestamp)`
- `token_snapshots`: `(snapshot_id)`, `(user_id, timestamp, symbol)`
- `lp_snapshots`: `(snapshot_id)`, `(user_id, timestamp)`
- `hedge_snapshots`: `(snapshot_id)`, `(user_id, timestamp)`
- `lending_snapshots`: `(snapshot_id)`, `(user_id, timestamp)`
- `lending_account_snapshots`: `(snapshot_id)`
- `lp_positions`: `(user_id, is_active)`
- `hedge_positions`: `(user_id, is_active)`
- `market_snapshots`: `(timestamp)`, `(session, timestamp)`
- `token_prices_daily`: `(timestamp, symbol)` UNIQUE
- `defi_rates`: `(timestamp, chain, protocol)`, `(asset, chain, timestamp)`
- `manual_positions`: `(user_id, is_active)` (legacy)
- `ai_reports`: `(user_id, timestamp)`
- `daily_digests`: `(user_id, timestamp)`
