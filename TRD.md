📄 Technical Requirements Document
DeFi Portfolio Strategy Optimizer v2.0

Local-first → Dockerized → AI-Driven

1. System Architecture Overview
Core Components

Data Ingestion Layer

On-chain RPC connectors

Protocol indexer connectors

Token discovery engine

Historical snapshot recorder

Portfolio Analytics Engine

Exposure normalization

LP math engine (v2 + v3 style)

Lending risk engine

Fee accrual modeling

Yield decomposition

Scenario engine (read-only)

AI Agent Layer

Market Research Agent (auto-regime detection)

Portfolio Optimisation Agent

Data Validation Agent

Frontend

Streamlit UI (local)

Configurable prompts & Bedrock settings

Detailed LP analytics dashboard

Storage

SQLite (local)

Time-series snapshots

Config persistence

Deployment

Docker container

Linux compatible

2. Supported Chains & Protocol Scope (Explicit)
Chains (v1 mandatory)

Ethereum

Arbitrum

Base

Lending

Aave v3 (primary)

LP Engines
Must Support:

Uniswap v2 style pools

Uniswap v3 concentrated liquidity

Aerodrome (Base)

Camelot (Arbitrum)

Architecture must allow plugin for:

PancakeSwap

Curve

Balancer

3. Functional Requirements — User Stories
3.1 Wallet & Token Discovery

US-001 (Rewritten)
As a user, I want the system to fetch all ERC20 tokens associated with my wallet from Ethereum, Arbitrum and Base using RPC + token indexers so that no asset is missed.

Acceptance Criteria:

Use Alchemy or Ankr RPC

Use token transfer logs to detect all token contracts

Pull decimals + symbol dynamically

No hardcoded token list

Reward tokens included automatically

US-002
As a user, I want token prices fetched dynamically for every discovered token so that portfolio valuation is complete.

Acceptance:

CoinGecko primary

Binance fallback

DefiLlama fallback

Graceful failure handling

Cache 5 minutes

3.2 LP Position Analytics

US-003
As a user, I want detailed LP breakdown for each position so that capital efficiency and risk are visible.

For each LP:

Pool name

Protocol

Chain

Price range

Current price

% distance to upper bound

% distance to lower bound

In-range or out-of-range

Liquidity share %

Current pool TVL

Fee APR (real fees only)

Incentive APR (separate)

Daily expected fee revenue

Weekly expected fee revenue

Monthly expected fee revenue

Historical fees collected (since inception)

Estimated IL at ±20%, ±40%

US-004
As a user, I want aggregated LP analytics so that I see total exposure impact.

Acceptance:

Total LP value

Total LP fees per day

Total IL risk weighted

% portfolio in concentrated liquidity

3.3 Lending & Risk

US-005
As a user, I want detailed Aave position analytics.

Display:

Supplied assets

Borrowed assets

LTV

Health factor

Liquidation threshold

Liquidation price under stress (-30%, -40%)

Net borrow cost

3.4 Historical Tracking

US-006
As a user, I want daily portfolio snapshots stored so that notional growth and compounding are measurable.

Acceptance:

Snapshot every 24h

Store:

Total USD value

Net BTC equivalent

Net ETH equivalent

Total fees accrued

Total borrow cost

LTV

SQLite storage

US-007
As a user, I want performance charts so that trend and drawdown are visible.

Charts:

Notional USD

BTC-equivalent accumulation

APY realized

Max drawdown

3.5 Auto Market Regime Detection (AI Agent)

No manual input.

US-008
As a user, I want the system to automatically detect market regime using AI so that optimisation is context-aware.

Agent responsibilities:

Fetch:

BTC dominance

Fear & Greed Index

Funding rates

RSI (BTC, ETH)

Open interest

Volatility index

Recent macro headlines

Tools:

CoinGecko API

Binance API

Alternative.me Fear Index API

Web search via Bedrock agent retrieval

Agent output:

{
  "short_term_regime": "bullish / bearish / neutral",
  "mid_term_regime": "...",
  "volatility_state": "...",
  "risk_environment_score": 0-10,
  "supporting_evidence": [...]
}

Must cite data sources.

3.6 Research Agent (Mandatory)

US-009
As a user, I want an AI research agent to autonomously fetch relevant technical and fundamental analysis so that optimisation is informed by current insights.

Requirements:

Use Bedrock Agents with web retrieval

Fetch latest:

Institutional research

On-chain analytics reports

Derivatives sentiment

Summarize into structured context

Must list URLs

No manual bias input allowed.

3.7 AI Portfolio Optimisation Engine

US-010 (Critical)
As a user, I want AI optimisation to generate actionable steps strictly within my defined strategy constraints.

Inputs:

PortfolioState

LP analytics

Lending risk

Historical trends

Auto regime output

Research summary

StrategyConfig

StrategyConfig must include:

Target APY

Max LTV

Blue-chip priority weight

Max high-beta %

Max maintenance complexity score

IL tolerance threshold

AI must:

Check constraint violations.

Identify inefficient capital.

Detect LP out-of-range positions.

Detect negative carry.

Detect underperforming yield vs risk.

Recommend reallocation steps.

Output Schema:

{
  "action_required": true/false,
  "priority_level": "low/medium/high",
  "reallocation_steps": [],
  "hedge_adjustments": [],
  "lp_adjustments": [],
  "risk_warnings": [],
  "expected_effect": {
     "apy_change": "",
     "risk_change": "",
     "exposure_change": ""
  },
  "confidence_score": 0-1
}

AI forbidden to invent yields or prices.

3.8 UI Requirements (Streamlit)
Tabs

Portfolio Overview

LP Analytics

Lending Risk

Historical Performance

Market Regime

AI Recommendations

Strategy Config

Prompt Config

Bedrock Config

US-011
As a user, I want prompts editable via UI so that AI reasoning can evolve.

Acceptance:

Text editor

Save to config file

Version stored

US-012
As a user, I want Bedrock credentials configurable via UI so that environment portability is possible.

Acceptance:

Access key input

Region input

Model selection dropdown

Saved to .env

Masked display

4. AI Agents Architecture

Three agents:

Market Agent

Research Agent

Optimisation Agent

Coordinator ensures:

Sequential execution

Data passed explicitly

No hidden assumptions

5. Non-Functional Requirements

Fully local

Dockerfile included

Linux compatible

Modular connectors

Caching layer

Unit tests for LP math

Schema validation for AI I/O

6. Security

Read-only wallet

No private keys

No transaction signing

API keys encrypted in env

7. Deployment

Docker container includes:

Python runtime

SQLite

Streamlit

Bedrock SDK

Cron scheduler

Launch:

docker-compose up
🔎 LOGIC INTEGRITY VALIDATION

Now critical review:

✔ No Hardcoded Assets

Token discovery via logs.
Prices fetched dynamically.
Compliant.

✔ Regime Detection Without Manual Bias

Uses quantitative indicators + AI interpretation.
Valid.

✔ LP Engines Scope

Explicit.
Extensible via plugin pattern.
Valid.

✔ Research Agent Mandatory

Explicit.
Autonomous.
Cites sources.
Valid.

✔ Historical Tracking

SQLite snapshots.
Time-series charts.
Valid.

⚠ Architectural Risks

LP math for v3 concentrated liquidity must be precise.
→ Requires careful implementation.

Web retrieval agent must filter noise.
→ Needs strict schema + ranking logic.

Docker + Bedrock credentials must be handled securely.

Token discovery via transfer logs may miss inactive tokens.
→ Should combine with balanceOf sweep.