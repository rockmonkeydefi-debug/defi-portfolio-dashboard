# Database Schema

SQLite database at `data/portfolio.db`. All tables include `user_id` for future multi-user support (default: 1).

## Tables

### `users`
Single default user for now. Password stored in `.env`, not DB.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| username | TEXT UNIQUE | Default: "default" |
| created_at | TIMESTAMP | |

### `portfolio_snapshots`
Master record per snapshot run. Scheduled every 2 hours.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| user_id | INTEGER FK → users | |
| timestamp | TIMESTAMP | |
| wallet | TEXT | Wallet address or xpub |
| total_value_usd | REAL | tokens + lp + lending_net + hedge_collateral |
| total_tokens_usd | REAL | Token holdings only |
| total_lp_usd | REAL | LP positions only |
| total_lending_usd | REAL | Net (collateral - debt) |
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
| protocol | TEXT | uniswap_v3 / aerodrome / camelot |
| position_id | TEXT | NFT token ID or unique identifier |
| token0 | TEXT | Symbol |
| token1 | TEXT | Symbol |
| fee_tier | REAL | 0.05, 0.3, 1.0 |
| amount0 | REAL | Token0 amount in position |
| amount1 | REAL | Token1 amount in position |
| price0_usd | REAL | Token0 price at snapshot |
| price1_usd | REAL | Token1 price at snapshot |
| value_usd | REAL | amount0 × price0 + amount1 × price1 |
| range_lower | REAL | |
| range_upper | REAL | |
| current_price | REAL | |
| in_range | BOOLEAN | |
| fees_uncollected_usd | REAL | |
| fees_collected_usd | REAL | Historical total |
| total_earned_fees_usd | REAL | collected + uncollected |
| daily_apr | REAL | |
| monthly_apr | REAL | |

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
Market data captured 3x daily (01:00, 07:00, 13:00 UTC ≈ Shanghai/Berlin/NYC 9 AM).

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| timestamp | TIMESTAMP | |
| session | TEXT | asia / europe / us |
| btc_price | REAL | |
| eth_price | REAL | |
| sol_price | REAL | |
| tao_price | REAL | |
| sui_price | REAL | |
| btc_dominance | REAL | % |
| eth_dominance | REAL | % |
| total_market_cap | REAL | |
| total_volume_24h | REAL | |
| stablecoin_supply | REAL | |
| fear_greed_index | INTEGER | 0-100 |
| btc_funding_rate | REAL | Per-period rate |
| eth_funding_rate | REAL | |
| sol_funding_rate | REAL | |
| btc_open_interest | REAL | USD |
| eth_open_interest | REAL | USD |
| btc_index_price | REAL | Deribit |
| eth_btc_ratio | REAL | |
| total_defi_tvl | REAL | |
| eth_gas_price | REAL | Gwei |
| eth_staking_apr | REAL | % |
| aave_usdc_supply_apy | REAL | % |
| aave_usdc_borrow_apy | REAL | % |
| eth_usdc_fee_apr | REAL | % — DeFiLlama yields |
| wbtc_usdc_fee_apr | REAL | % |

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

### `manual_positions`
User-managed positions (mirrors LP snapshot structure). For positions the app can't auto-detect.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| user_id | INTEGER FK → users | |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |
| chain | TEXT | |
| protocol | TEXT | |
| position_id | TEXT | User-defined identifier |
| token0 | TEXT | |
| token1 | TEXT | |
| fee_tier | REAL | |
| value_usd | REAL | |
| range_lower | REAL | |
| range_upper | REAL | |
| current_price | REAL | |
| in_range | BOOLEAN | |
| fees_uncollected_usd | REAL | |
| fees_collected_usd | REAL | |
| notes | TEXT | |
| is_active | BOOLEAN | Default true |

## Derived Fields (not stored, calculated from DB)

- `btc_return_7d`, `btc_return_30d` — from `token_prices_daily`
- `btc_funding_zscore` — from historical `btc_funding_rate` in `market_snapshots`
- `btc_oi_change_7d` — from historical `btc_open_interest`
- `stablecoin_change_7d` — from historical `stablecoin_supply`
- `fear_greed_7d_avg` — from historical `fear_greed_index`
- `btc_realized_vol_30d`, `eth_realized_vol_30d` — from `token_prices_daily` log returns
- `btc_range_14d`, `eth_range_14d` — from `token_prices_daily` high/low

## Snapshot Schedule

| Data | Frequency | UTC Times |
|------|-----------|-----------|
| Portfolio snapshot | Every 2 hours | 00:00, 02:00, 04:00, ... |
| Market data | 3x daily | 01:00 (Asia), 07:00 (Europe), 13:00 (US) |
| Token daily prices | Once per day | 00:00 |

## Indexes

- `portfolio_snapshots`: (user_id, timestamp), (user_id, wallet, timestamp)
- `token_snapshots`: (snapshot_id), (user_id, timestamp, symbol)
- `lp_snapshots`: (snapshot_id), (user_id, timestamp)
- `hedge_snapshots`: (snapshot_id), (user_id, timestamp)
- `lending_snapshots`: (snapshot_id), (user_id, timestamp)
- `lending_account_snapshots`: (snapshot_id)
- `market_snapshots`: (timestamp), (session, timestamp)
- `token_prices_daily`: (timestamp, symbol) UNIQUE
- `manual_positions`: (user_id, is_active)
