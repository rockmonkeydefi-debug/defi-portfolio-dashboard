# Requirements Document

## Reference

This document is derived from the full Technical Requirements Document: #[[file:TRD.md]]

This PoC excludes all AI components (US-008 through US-012), Docker deployment, and the Market Regime / AI Recommendations / Prompt Config / Bedrock Config UI tabs.

## Introduction

The DeFi Portfolio Strategy Optimizer PoC is a local-first, read-only portfolio analytics tool. It fetches on-chain data for a given Ethereum wallet across Ethereum, Arbitrum, and Base, discovers all ERC-20 token holdings, resolves LP positions across Uniswap v2/v3, Aerodrome, and Camelot, retrieves Aave v3 lending positions, prices everything dynamically, stores daily snapshots in SQLite, and renders the results in a Streamlit dashboard. All AI agents and Docker deployment are excluded from this PoC.

## Glossary

- **Token_Discovery_Engine**: The component that scans on-chain transfer logs to detect all ERC-20 token contracts held by a wallet.
- **Price_Service**: The component that fetches token prices from external APIs with a tiered fallback strategy.
- **LP_Math_Engine**: The component that computes LP position analytics including fee revenue, impermanent loss, and range metrics for both constant-product (v2) and concentrated-liquidity (v3) pool models.
- **Lending_Risk_Engine**: The component that fetches and computes Aave v3 position analytics including health factor, LTV, and liquidation prices.
- **Snapshot_Recorder**: The component that persists daily portfolio snapshots to SQLite.
- **Dashboard**: The Streamlit-based frontend that renders portfolio data across multiple tabs.
- **RPC_Connector**: The component that communicates with blockchain nodes via JSON-RPC (Alchemy or Ankr).
- **Cache_Layer**: The in-memory caching component that stores API responses with a configurable TTL.
- **Wallet_Address**: A valid Ethereum address (0x-prefixed, 42 hex characters).
- **Wallet_Set**: One or more Wallet_Addresses configured by the user, representing the combined portfolio to analyze.
- **Concentrated_Liquidity_Position**: An LP position in a Uniswap v3-style pool with defined price bounds (tick range).
- **Constant_Product_Position**: An LP position in a Uniswap v2-style pool with full-range liquidity.
- **Health_Factor**: The ratio of collateral value to borrow value in Aave, where values below 1.0 indicate liquidation risk.
- **Impermanent_Loss (IL)**: The loss in value experienced by an LP compared to simply holding the underlying tokens.

## Requirements

### Requirement 1: Multi-Wallet Management

**User Story:** As a user, I want to configure multiple wallet addresses so that my entire portfolio across wallets is analyzed as one combined view.

#### Acceptance Criteria

1. THE Dashboard SHALL allow the user to add, remove, and list Wallet_Addresses in the Wallet_Set via the Strategy Config tab.
2. THE system SHALL persist the Wallet_Set to a local configuration file so that addresses survive application restarts.
3. WHEN the Wallet_Set is empty, THE Dashboard SHALL prompt the user to add at least one Wallet_Address before displaying analytics.
4. WHEN a user adds a Wallet_Address, THE system SHALL validate that it is a well-formed Ethereum address (0x-prefixed, 42 hex characters).
5. IF a user adds a duplicate Wallet_Address, THEN THE system SHALL reject the addition and inform the user.

### Requirement 2: Wallet Token Discovery

**User Story:** As a user, I want the system to fetch all ERC-20 tokens associated with all wallets in my Wallet_Set from Ethereum, Arbitrum, and Base so that no asset is missed.

#### Acceptance Criteria

1. WHEN the Wallet_Set contains one or more addresses, THE Token_Discovery_Engine SHALL query token transfer logs on Ethereum, Arbitrum, and Base via the RPC_Connector for each Wallet_Address to detect all ERC-20 token contracts.
2. WHEN a token contract is detected, THE Token_Discovery_Engine SHALL dynamically fetch the token symbol and decimals from the on-chain contract.
3. THE Token_Discovery_Engine SHALL include reward tokens (e.g., protocol incentives, airdrops) in the discovered token set without requiring a hardcoded token list.
4. WHEN a token contract call for symbol or decimals fails, THE Token_Discovery_Engine SHALL log the failure and skip the token without halting discovery for remaining tokens.
5. WHEN discovery completes, THE Token_Discovery_Engine SHALL return a collated list of token holdings across all wallets, with contract address, symbol, decimals, and aggregated raw balance for each chain.
6. THE Token_Discovery_Engine SHALL aggregate balances for the same token across multiple wallets into a single entry per token per chain.

### Requirement 3: Dynamic Token Pricing

**User Story:** As a user, I want token prices fetched dynamically for every discovered token so that portfolio valuation is complete.

#### Acceptance Criteria

1. WHEN token prices are requested, THE Price_Service SHALL attempt to fetch prices from CoinGecko as the primary source.
2. IF CoinGecko is unavailable or returns no price for a token, THEN THE Price_Service SHALL fall back to Binance, and if Binance also fails, fall back to DefiLlama.
3. WHEN a price is successfully fetched, THE Cache_Layer SHALL store the price with a 5-minute TTL and serve cached values for subsequent requests within that window.
4. IF all three price sources fail for a token, THEN THE Price_Service SHALL assign a price of zero to that token and log a warning.
5. THE Price_Service SHALL return prices denominated in USD for all discovered tokens.

### Requirement 4: LP Position Detail Analytics

**User Story:** As a user, I want a detailed LP breakdown for each position across all wallets so that capital efficiency and risk are visible.

#### Acceptance Criteria

1. WHEN LP positions are fetched, THE LP_Math_Engine SHALL identify positions across Uniswap v2, Uniswap v3, Aerodrome (Base), and Camelot (Arbitrum) for every Wallet_Address in the Wallet_Set.
2. FOR EACH Concentrated_Liquidity_Position, THE LP_Math_Engine SHALL compute: pool name, protocol, chain, price range (lower and upper bounds), current price, percentage distance to upper bound, percentage distance to lower bound, and in-range or out-of-range status.
3. FOR EACH LP position, THE LP_Math_Engine SHALL compute: liquidity share percentage, current pool TVL, fee APR (from real on-chain fees only), and incentive APR (separated from fee APR).
4. FOR EACH LP position, THE LP_Math_Engine SHALL compute: daily expected fee revenue, weekly expected fee revenue, and monthly expected fee revenue.
5. FOR EACH LP position, THE LP_Math_Engine SHALL compute historical fees collected since position inception.
6. FOR EACH LP position, THE LP_Math_Engine SHALL compute estimated impermanent loss at ±20% and ±40% price movement scenarios.
7. FOR EACH Constant_Product_Position, THE LP_Math_Engine SHALL compute the same metrics as criteria 3 through 6, excluding price range and distance-to-bounds fields.

### Requirement 5: Aggregated LP Analytics

**User Story:** As a user, I want aggregated LP analytics so that I see total exposure impact.

#### Acceptance Criteria

1. WHEN individual LP positions have been computed across all wallets, THE LP_Math_Engine SHALL aggregate total LP value in USD across all positions.
2. THE LP_Math_Engine SHALL aggregate total LP fees per day across all positions.
3. THE LP_Math_Engine SHALL compute a weighted IL risk score across all positions.
4. THE LP_Math_Engine SHALL compute the percentage of total portfolio value held in concentrated liquidity positions.

### Requirement 6: Aave v3 Lending Position Analytics

**User Story:** As a user, I want detailed Aave v3 position analytics across all wallets so that lending risk is visible.

#### Acceptance Criteria

1. WHEN the Wallet_Set contains one or more addresses, THE Lending_Risk_Engine SHALL fetch all supplied and borrowed assets from Aave v3 on each supported chain for every Wallet_Address in the Wallet_Set.
2. THE Lending_Risk_Engine SHALL compute the current loan-to-value (LTV) ratio and Health_Factor for each Wallet_Address's Aave positions, and provide an aggregated view across the Wallet_Set.
3. THE Lending_Risk_Engine SHALL retrieve the liquidation threshold for each supplied asset.
4. THE Lending_Risk_Engine SHALL compute the liquidation price for each collateral asset under stress scenarios of -30% and -40% market decline.
5. THE Lending_Risk_Engine SHALL compute the net borrow cost (borrow APR minus supply APR) for each Wallet_Address's Aave positions and aggregate across the Wallet_Set.

### Requirement 7: Daily Portfolio Snapshots

**User Story:** As a user, I want daily portfolio snapshots stored so that notional growth and compounding are measurable.

#### Acceptance Criteria

1. WHEN a snapshot is triggered (every 24 hours), THE Snapshot_Recorder SHALL persist a record to SQLite containing: total USD value (aggregated across all wallets), net BTC equivalent, net ETH equivalent, total fees accrued, total borrow cost, and current LTV.
2. THE Snapshot_Recorder SHALL store snapshots with a UTC timestamp as the primary key.
3. IF a snapshot for the current UTC date already exists, THEN THE Snapshot_Recorder SHALL update the existing record rather than creating a duplicate.

### Requirement 8: Historical Performance Charts

**User Story:** As a user, I want performance charts so that trend and drawdown are visible.

#### Acceptance Criteria

1. WHEN the Historical Performance tab is opened, THE Dashboard SHALL render a notional USD value chart over time from stored snapshots.
2. THE Dashboard SHALL render a BTC-equivalent accumulation chart over time.
3. THE Dashboard SHALL compute and render a realized APY chart based on portfolio value changes.
4. THE Dashboard SHALL compute and render a maximum drawdown chart showing peak-to-trough decline over time.

### Requirement 9: Streamlit Dashboard

**User Story:** As a user, I want a multi-tab Streamlit dashboard so that all portfolio analytics are accessible in one interface.

#### Acceptance Criteria

1. WHEN the Dashboard is launched, THE Dashboard SHALL present five tabs: Portfolio Overview, LP Analytics, Lending Risk, Historical Performance, and Strategy Config.
2. WHEN the Portfolio Overview tab is selected, THE Dashboard SHALL display total portfolio value aggregated across all wallets, token holdings with prices, and a breakdown by chain.
3. WHEN the LP Analytics tab is selected, THE Dashboard SHALL display individual LP position details across all wallets (per Requirement 4) and aggregated LP metrics (per Requirement 5).
4. WHEN the Lending Risk tab is selected, THE Dashboard SHALL display Aave v3 position details across all wallets (per Requirement 6).
5. WHEN the Historical Performance tab is selected, THE Dashboard SHALL display the performance charts (per Requirement 8).
6. WHEN the Strategy Config tab is selected, THE Dashboard SHALL allow the user to manage the Wallet_Set (add/remove addresses) and view and edit basic strategy parameters: target APY, max LTV, max high-beta percentage, and IL tolerance threshold, persisted to a local config file.

### Requirement 10: Caching Layer

**User Story:** As a user, I want API responses cached so that repeated requests are fast and rate limits are respected.

#### Acceptance Criteria

1. THE Cache_Layer SHALL provide an in-memory cache with configurable TTL per data source.
2. WHEN a cached value exists and has not expired, THE Cache_Layer SHALL return the cached value without making an external API call.
3. WHEN a cached value has expired, THE Cache_Layer SHALL fetch a fresh value from the external source and update the cache.

### Requirement 11: Modular Connector Architecture

**User Story:** As a developer, I want modular connectors so that new chains and protocols can be added without modifying core logic.

#### Acceptance Criteria

1. THE system SHALL define abstract interfaces for chain connectors, protocol connectors, and price providers.
2. WHEN a new chain or protocol is added, THE system SHALL require only a new connector implementation conforming to the existing interface, without changes to the analytics engines or Dashboard.

### Requirement 12: Security and Read-Only Operation

**User Story:** As a user, I want the system to operate in read-only mode so that my funds are never at risk.

#### Acceptance Criteria

1. THE system SHALL accept only a Wallet_Address as input and SHALL NOT accept or store private keys or seed phrases.
2. THE system SHALL perform only read operations (eth_call, getLogs) against blockchain nodes and SHALL NOT construct or sign transactions.
3. THE system SHALL store API keys only in environment variables or a .env file, not in source code.
