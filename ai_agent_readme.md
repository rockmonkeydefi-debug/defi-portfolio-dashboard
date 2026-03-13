# AI Portfolio Advisor — Technical Documentation

## Overview

The AI Portfolio Advisor generates data-driven analysis reports by combining real-time market data, on-chain portfolio state, investor preferences, and historical context into a structured prompt sent to an LLM (OpenAI GPT-4o or AWS Bedrock Claude). The output is a structured JSON report with market regime assessment, portfolio evaluation, risk alerts, and actionable recommendations.

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐     ┌──────────────┐
│  Scheduler   │────▶│  Context Builder  │────▶│  LLM API    │────▶│  Report DB   │
│  or Button   │     │  (ai_advisor.py)  │     │  (providers) │     │  (ai_reports) │
└─────────────┘     └──────────────────┘     └─────────────┘     └──────────────┘
                           │                                            │
                    ┌──────┴──────┐                              ┌──────┴──────┐
                    │ Data Sources │                              │  Frontend   │
                    │ - Market APIs│                              │  (ai.js)    │
                    │ - Portfolio  │                              │  AI Daily   │
                    │ - DB history │                              │  Brief tab  │
                    │ - Profile    │                              └─────────────┘
                    └─────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `src/engines/ai_advisor.py` | Context builder, orchestration, report generation |
| `src/engines/llm_providers.py` | OpenAI and AWS Bedrock LLM provider abstractions |
| `src/engines/ai_system_prompt.txt` | Base system prompt (git-controlled, defines role + output format) |
| `data/ai_config.json` | User configuration (provider, model, schedule, strategies) |
| `data/investor_profile.json` | Investor questionnaire answers |
| `static/ai.js` | Frontend rendering for AI Daily Brief |
| `static/portfolio.js` | AI Config settings UI |

## Data Flow

### 1. Trigger
- **Manual**: User clicks "Generate Report" in Market Data → AI Daily Brief
- **Scheduled**: Configurable UTC hour (default: 08:00) via `schedule_utc_hour` in ai_config.json

### 2. Context Building (`build_context`)

The Context Builder assembles a structured text prompt from multiple data sources:

#### Market Data (live fetch with DB fallback)
| Data Point | Source | Timeout |
|-----------|--------|---------|
| BTC, ETH, SOL, TAO, SUI prices + 24h change | CoinGecko `/simple/price` | 10s |
| BTC/ETH dominance, market cap, volume | CoinGecko `/global` | 10s |
| BTC, ETH, SOL funding rates + open interest | Bybit `/v5/market/tickers` | 10s |
| Fear & Greed index (current + 30d history) | alternative.me `/fng` | 10s |
| Stablecoin total supply | DeFiLlama `/stablecoinchains` | 10s |
| BTC, ETH 7d/30d returns + 30d realized volatility | CoinGecko `/coins/{id}/market_chart` | 10s |

If any API call fails, the freshness dict records `'failed'` and the LLM is informed that data is missing.

#### Support/Resistance Levels
| Data Point | Source | Method |
|-----------|--------|--------|
| BTC, ETH weekly pivot points (S2, S1, Pivot, R1, R2) | CoinGecko `/coins/{id}/ohlc` (14d) | Classic pivot: PP=(H+L+C)/3 |
| Current price position relative to levels | Derived | Compared against pivot/S1/R1 |
| Weekly high/low range | Derived from OHLC | Max high, min low of last 7 candles |

#### Portfolio State
| Data Point | Source |
|-----------|--------|
| Total value breakdown (tokens, LP, lending, hedges) | `get_portfolio_data()` (cached) |
| Token allocation by group (ETH, BTC, Stables, Other) | Derived from token list |
| Active LP positions (chain, pair, range, in/out, fees, APR) | Portfolio data |
| Active hedges (GMX: direction, size, entry, PnL, liquidation) | Portfolio data |
| AAVE lending (collateral, debt, health factor) | Portfolio data |
| Manual LP positions | `lp_positions` table |
| Manual hedges | `hedge_positions` table |

#### Investor Profile
| Data Point | Source |
|-----------|--------|
| Risk tolerance, target APY, max drawdown | `data/investor_profile.json` |
| Portfolio priorities (ranked 1-4) | Profile questionnaire |
| DeFi experience levels | Profile questionnaire |
| Token convictions, chain preferences | Profile questionnaire |
| Operational preferences (hours/week, rebalancing) | Profile questionnaire |

#### Previous Recommendations
| Data Point | Source |
|-----------|--------|
| Last report's recommendations list | `ai_reports` table (most recent) |
| Implementation status | Determined by LLM comparing current portfolio vs recommendations |

### 3. System Prompt

The system prompt has three layers:

1. **Base prompt** (`ai_system_prompt.txt`) — git-controlled, defines:
   - Role: institutional-grade crypto portfolio advisor
   - Rules: factual, data-driven, no speculation
   - Output format: structured JSON schema
   - Required sections: market regime, analysis, portfolio assessment, recommendations

2. **Custom instructions** (user-editable in Settings → AI Config):
   - Additional behavioral instructions
   - Example: "Focus on capital preservation during high volatility"

3. **Strategy preferences** (user-editable):
   - Bull market strategy
   - Bear market strategy
   - Sideways market strategy
   - The LLM selects the appropriate strategy based on its regime assessment

### 4. LLM Call

#### OpenAI Provider
- Endpoint: `POST https://api.openai.com/v1/chat/completions`
- Auth: Bearer token (`OPENAI_API_KEY`)
- Temperature: 0.3 (low creativity, high consistency)
- Response format: `json_object` (enforced JSON output)
- Timeout: 120 seconds

#### AWS Bedrock Provider
- Endpoint: `POST https://bedrock-runtime.{region}.amazonaws.com/model/{model}/converse`
- Auth: Bearer token (`AWS_BEARER_TOKEN_BEDROCK`)
- Temperature: 0.3
- Max tokens: 4096
- Timeout: 120 seconds
- Note: Use inference profile IDs (e.g., `us.anthropic.claude-opus-4-6-v1`) not base model IDs

### 5. Output Format

The LLM returns structured JSON:

```json
{
  "report_date": "2026-03-13",
  "market_regime": {
    "short_term_7d": {
      "bull": 20, "bear": 55, "sideways": 25,
      "reasoning": "Factual explanation with data references"
    },
    "mid_term_30d": {
      "bull": 40, "bear": 30, "sideways": 30,
      "reasoning": "Factual explanation with data references"
    },
    "data_confidence": "moderate — explanation of data availability"
  },
  "market_analysis": {
    "summary": "2-3 sentence market overview",
    "key_metrics": [
      {"metric": "Fear & Greed", "value": "18", "interpretation": "..."}
    ],
    "support_resistance": {
      "btc": {"s1": 68100, "s2": 66500, "r1": 71200, "r2": 72450, "pivot": 69800, "status": "..."},
      "eth": {"s1": 1950, "s2": 1880, "r1": 2100, "r2": 2170, "pivot": 2030, "status": "..."}
    }
  },
  "portfolio_assessment": {
    "alignment": "aligned | partially_aligned | misaligned",
    "summary": "Assessment vs investor profile and market regime",
    "strengths": ["..."],
    "concerns": ["..."]
  },
  "recommendations": [
    {
      "action": "Specific action to take",
      "rationale": "Data-driven reasoning",
      "priority": "high | medium | low",
      "strategy_reference": "bull | bear | sideways"
    }
  ],
  "risk_alerts": [
    {"type": "liquidation | range_break | exposure", "severity": "info | warning | critical", "message": "..."}
  ],
  "previous_recommendations_review": [
    {"recommendation": "...", "status": "implemented | not_implemented | partially | unknown", "comment": "..."}
  ]
}
```

### 6. Storage

Reports are stored in the `ai_reports` table:

| Column | Type | Content |
|--------|------|---------|
| timestamp | TIMESTAMP | UTC time of generation |
| provider | TEXT | openai / bedrock |
| model | TEXT | Model ID used |
| market_regime_json | TEXT | JSON of regime assessment |
| portfolio_alignment | TEXT | aligned/partially_aligned/misaligned |
| summary | TEXT | Market analysis summary |
| full_report_json | TEXT | Complete JSON report |
| previous_recs_review_json | TEXT | Review of last recommendations |
| prompt_tokens | INTEGER | Input token count |
| completion_tokens | INTEGER | Output token count |
| data_freshness_json | TEXT | Which data sources were live vs failed |

### 7. Frontend Display

Located in Market Data → AI Daily Brief:

- **Market Regime**: Probability bars (bull/sideways/bear) for 7d and 30d with reasoning
- **Market Analysis**: Summary, key metrics table, S/R levels
- **Portfolio Assessment**: Alignment badge, strengths (green), concerns (orange)
- **Risk Alerts**: Color-coded by severity (info/warning/critical)
- **Recommendations**: Numbered cards with action, rationale, priority, strategy reference
- **Previous Recommendations Review**: Status badges (implemented/not/partial)
- **Report History**: Dropdown to view past reports

## Configuration

### Settings → AI Config

| Field | Description | Default |
|-------|-------------|---------|
| Provider | OpenAI or AWS Bedrock | openai |
| Model | Model ID | gpt-4o |
| Schedule (UTC hour) | When to auto-generate | 8 |
| Custom Instructions | Additional prompt text | empty |
| Bull Strategy | User's bull market approach | empty |
| Bear Strategy | User's bear market approach | empty |
| Sideways Strategy | User's sideways market approach | empty |

### Environment Variables

| Variable | Required For | Description |
|----------|-------------|-------------|
| `OPENAI_API_KEY` | OpenAI provider | API key from platform.openai.com |
| `AWS_BEARER_TOKEN_BEDROCK` | Bedrock provider | Bearer token for Bedrock REST API |
| `AWS_REGION` | Bedrock provider | AWS region (default: us-east-1) |

### Config File: `data/ai_config.json`

```json
{
  "provider": "bedrock",
  "model": "us.anthropic.claude-opus-4-6-v1",
  "schedule_utc_hour": 8,
  "custom_system_prompt": "Focus on risk-adjusted returns...",
  "strategies": {
    "bull": "In bull markets, I prefer concentrated LP ranges...",
    "bear": "In bear markets, I prefer wider ranges, hedging...",
    "sideways": "In sideways markets, I prefer tight ranges..."
  }
}
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/ai/config` | Get AI configuration |
| POST | `/api/ai/config` | Save AI configuration |
| POST | `/api/ai/generate` | Generate a new report |
| GET | `/api/ai/reports?limit=N` | List recent reports (summary) |
| GET | `/api/ai/reports/<id>` | Get full report detail |

## Design Decisions

### Why structured JSON output?
- Enables consistent frontend rendering
- Allows programmatic analysis of recommendations over time
- Makes it possible to track recommendation implementation
- Prevents free-form text that's hard to parse

### Why probability-based regime assessment?
- Avoids false confidence in single-label predictions
- Forces the LLM to express uncertainty
- Allows the user to see the reasoning behind each probability
- More useful for strategy selection (e.g., 60% bear → lean defensive but don't go all-in)

### Why separate system prompt from strategies?
- System prompt defines behavior and format (stable, git-controlled)
- Strategies are user-specific and change over time (stored in config)
- Custom instructions allow per-user behavioral tweaks without modifying code

### Why not integrate the Range Optimizer?
- The optimizer assumes a random walk (no directional bias)
- The LLM's regime assessment is directional
- Combining them would contaminate the statistical model with qualitative judgment
- Better to give the LLM both pieces separately and let it synthesize

### Why S/R from pivot points instead of ML?
- Pivot points are deterministic and widely used by institutional traders
- No training data needed, works immediately
- Transparent calculation the user can verify
- The LLM can reason about whether levels were broken

## Token Usage Estimates

| Component | Approximate Tokens |
|-----------|-------------------|
| System prompt | ~800 |
| Market data context | ~500-800 |
| S/R levels | ~200 |
| Portfolio context | ~300-600 |
| Investor profile | ~200-400 |
| Previous recommendations | ~100-200 |
| **Total input** | **~2,000-3,000** |
| **Output** | **~1,000-2,000** |
| **Total per report** | **~3,000-5,000** |

Cost per report (approximate):
- GPT-4o: ~$0.02-0.05
- Claude 3.5 Sonnet: ~$0.02-0.04
- Claude Opus: ~$0.10-0.20

## Future Enhancements

- **Scheduled auto-generation**: Background thread triggers at configured UTC hour
- **Range Optimizer integration**: Pre-compute optimal ranges and include in context
- **Multi-model comparison**: Run same prompt through multiple models and compare
- **Recommendation tracking**: Automated detection of whether recommendations were implemented
- **Alert system**: Push notifications for critical risk alerts
- **Historical trend analysis**: Include portfolio performance trends in context
