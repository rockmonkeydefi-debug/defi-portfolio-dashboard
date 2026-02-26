# Implementation Plan: DeFi Portfolio PoC

## Overview

Incremental implementation of the DeFi Portfolio PoC in Python. Each task builds on previous ones, starting with infrastructure (models, config, cache), then data connectors, analytics engines, storage, and finally the Streamlit UI. All code lives in a Python venv. Tests are co-located with implementation tasks to catch errors early.

## Tasks

- [ ] 1. Project scaffolding and core data models
  - [ ] 1.1 Create venv, install dependencies (`web3`, `requests`, `streamlit`, `plotly`, `hypothesis`, `pytest`, `python-dotenv`), generate `requirements.txt`
    - Create `venv/` via `python -m venv venv`
    - Create `requirements.txt` with pinned versions
    - Create `src/__init__.py`, `src/connectors/__init__.py`, `src/connectors/prices/__init__.py`, `src/engines/__init__.py`, `src/storage/__init__.py`, `src/ui/__init__.py`, `tests/__init__.py`
    - Create `.env.example` with placeholder API keys
    - _Requirements: 12.3_
  - [ ] 1.2 Implement data models in `src/models.py`
    - Define `Chain`, `LPType`, `Protocol` enums
    - Define all dataclasses: `TokenMetadata`, `TokenHolding`, `TokenTransfer`, `PoolData`, `RawLPPosition`, `LPPositionAnalytics`, `AggregatedLPAnalytics`, `LendingPosition`, `PortfolioSnapshot`, `StrategyConfig`
    - _Requirements: 4.2, 4.3, 5.1, 6.2_

- [ ] 2. Config manager and cache layer
  - [ ] 2.1 Implement `ConfigManager` in `src/config.py`
    - Wallet add/remove/list with validation and duplicate detection
    - Strategy config get/update
    - JSON persistence to `config.json`
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 9.6_
  - [ ]* 2.2 Write property tests for ConfigManager
    - **Property 1: Wallet configuration round-trip**
    - **Property 2: Address validation and uniqueness**
    - **Validates: Requirements 1.2, 1.4, 1.5**
  - [ ] 2.3 Implement `CacheLayer` in `src/cache.py`
    - In-memory TTL cache with `get`, `set`, `clear`
    - Configurable TTL per entry
    - _Requirements: 10.1, 10.2, 10.3_
  - [ ]* 2.4 Write property test for CacheLayer
    - **Property 6: Cache TTL behavior**
    - **Validates: Requirements 3.3, 10.1, 10.2, 10.3**

- [ ] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Abstract connector interfaces and chain connectors
  - [ ] 4.1 Define abstract interfaces in `src/connectors/base.py`
    - `ChainConnector`, `PriceProvider`, `LPConnector`, `LendingConnector` ABCs
    - _Requirements: 11.1, 11.2_
  - [ ] 4.2 Implement chain connectors: `src/connectors/ethereum.py`, `src/connectors/arbitrum.py`, `src/connectors/base_chain.py`
    - Each wraps `web3.py` with chain-specific RPC URL from `.env`
    - Implement `get_token_transfers`, `get_token_balance`, `get_token_metadata`, `get_block_timestamp`
    - Use ERC-20 Transfer event topic for log scanning
    - _Requirements: 2.1, 2.2_

- [ ] 5. Token discovery engine
  - [ ] 5.1 Implement `TokenDiscoveryEngine` in `src/engines/token_discovery.py`
    - Iterate Wallet_Set × chains, scan transfer logs, deduplicate token contracts
    - Fetch metadata (symbol, decimals) per token, skip on failure
    - Fetch balances, aggregate same token across wallets per chain
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  - [ ]* 5.2 Write property tests for token discovery
    - **Property 3: Token balance aggregation**
    - **Property 4: Token discovery fault tolerance**
    - **Validates: Requirements 2.4, 2.6**

- [ ] 6. Price service and providers
  - [ ] 6.1 Implement price providers in `src/connectors/prices/`
    - `CoinGeckoProvider` in `coingecko.py` — REST API, map contract addresses to prices
    - `BinanceProvider` in `binance.py` — REST API, symbol-based lookup
    - `DefiLlamaProvider` in `defillama.py` — REST API, chain:address format
    - _Requirements: 3.1_
  - [ ] 6.2 Implement `PriceService` in `src/engines/price_service.py`
    - Tiered fallback: CoinGecko → Binance → DefiLlama
    - Integrate with CacheLayer (5-min TTL)
    - Assign price=0 and log warning when all providers fail
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  - [ ]* 6.3 Write property test for price fallback
    - **Property 5: Price fallback chain ordering**
    - **Validates: Requirements 3.2, 3.4**

- [ ] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. LP connectors
  - [ ] 8.1 Implement `UniswapV2Connector` in `src/connectors/uniswap_v2.py`
    - Fetch LP token balances, pool reserves, token pair info
    - _Requirements: 4.1, 4.7_
  - [ ] 8.2 Implement `UniswapV3Connector` in `src/connectors/uniswap_v3.py`
    - Fetch NFT positions via NonfungiblePositionManager
    - Fetch pool state (slot0, liquidity, fee growth)
    - _Requirements: 4.1, 4.2_
  - [ ] 8.3 Implement `AerodromeConnector` in `src/connectors/aerodrome.py`
    - Base chain, v2-style pools with gauge rewards
    - _Requirements: 4.1_
  - [ ] 8.4 Implement `CamelotConnector` in `src/connectors/camelot.py`
    - Arbitrum, v3-style concentrated liquidity
    - _Requirements: 4.1_

- [ ] 9. LP math engine
  - [ ] 9.1 Implement `LPMathEngine` in `src/engines/lp_math.py`
    - `compute_v3_amounts`: token amounts from liquidity and sqrt prices
    - `compute_il` (v2) and `compute_v3_il` (concentrated)
    - `distance_to_bound`, `is_in_range`
    - `compute_fee_apr`, `compute_fee_revenue`
    - Per-position analytics builder that produces `LPPositionAnalytics`
    - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_
  - [ ] 9.2 Implement LP aggregation in `src/engines/lp_math.py`
    - `aggregate_lp_analytics`: total value, total fees/day, weighted IL risk, concentrated %
    - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - [ ]* 9.3 Write property tests for LP math
    - **Property 7: Concentrated liquidity range metrics**
    - **Property 8: Fee APR and revenue consistency**
    - **Property 9: Impermanent loss bounds**
    - **Property 10: LP aggregation invariants**
    - **Validates: Requirements 4.2, 4.3, 4.4, 4.6, 5.1, 5.2, 5.3, 5.4**

- [ ] 10. Lending connector and risk engine
  - [ ] 10.1 Implement `AaveV3Connector` in `src/connectors/aave_v3.py`
    - Fetch user account data from Aave Pool contract
    - Fetch reserve data for supply/borrow APRs
    - _Requirements: 6.1, 6.3_
  - [ ] 10.2 Implement `LendingRiskEngine` in `src/engines/lending_risk.py`
    - `compute_health_factor`, `compute_ltv`, `compute_liquidation_price`, `compute_net_borrow_cost`
    - Build `LendingPosition` from raw Aave data
    - _Requirements: 6.2, 6.3, 6.4, 6.5_
  - [ ]* 10.3 Write property tests for lending risk math
    - **Property 11: Lending risk math**
    - **Validates: Requirements 6.2, 6.4, 6.5**

- [ ] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Snapshot recorder and historical computations
  - [ ] 12.1 Implement `SnapshotRecorder` in `src/storage/snapshots.py`
    - SQLite table creation, `record` (upsert), `get_all`
    - UTC date as primary key
    - _Requirements: 7.1, 7.2, 7.3_
  - [ ]* 12.2 Write property tests for snapshots
    - **Property 12: Snapshot persistence round-trip**
    - **Property 13: Snapshot idempotence**
    - **Validates: Requirements 7.1, 7.3**
  - [ ] 12.3 Implement chart computation helpers in `src/engines/charts.py`
    - `compute_realized_apy(snapshots)` → list of APY values over time
    - `compute_max_drawdown(snapshots)` → list of drawdown values over time
    - _Requirements: 8.3, 8.4_
  - [ ]* 12.4 Write property tests for chart computations
    - **Property 14: Realized APY computation**
    - **Property 15: Maximum drawdown bounds**
    - **Validates: Requirements 8.3, 8.4**

- [ ] 13. Portfolio aggregator
  - [ ] 13.1 Implement `PortfolioAggregator` in `src/engines/aggregator.py`
    - Orchestrates: iterate Wallet_Set → token discovery → pricing → LP positions → lending → snapshot
    - Produces complete portfolio state for Dashboard consumption
    - _Requirements: 2.5, 2.6, 5.1, 9.2_

- [ ] 14. Streamlit dashboard
  - [ ] 14.1 Implement main app shell in `src/ui/app.py`
    - Tab layout: Portfolio Overview, LP Analytics, Lending Risk, Historical Performance, Strategy Config
    - Wallet_Set empty check → prompt to add wallet
    - _Requirements: 9.1, 1.3_
  - [ ] 14.2 Implement Portfolio Overview tab in `src/ui/portfolio_tab.py`
    - Total portfolio value, token holdings table with prices, chain breakdown
    - _Requirements: 9.2_
  - [ ] 14.3 Implement LP Analytics tab in `src/ui/lp_tab.py`
    - Individual LP position table (all fields from Requirement 4)
    - Aggregated LP metrics cards (Requirement 5)
    - _Requirements: 9.3_
  - [ ] 14.4 Implement Lending Risk tab in `src/ui/lending_tab.py`
    - Supplied/borrowed assets, LTV, health factor, liquidation prices, net borrow cost
    - _Requirements: 9.4_
  - [ ] 14.5 Implement Historical Performance tab in `src/ui/history_tab.py`
    - Plotly charts: notional USD, BTC-equivalent, realized APY, max drawdown
    - _Requirements: 9.5, 8.1, 8.2, 8.3, 8.4_
  - [ ] 14.6 Implement Strategy Config tab in `src/ui/config_tab.py`
    - Wallet management: add/remove/list addresses
    - Strategy parameter editing: target APY, max LTV, max high-beta %, IL tolerance
    - Persist on save
    - _Requirements: 9.6, 1.1, 1.4, 1.5_

- [ ] 15. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- All Python code runs inside the venv created in task 1.1
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
