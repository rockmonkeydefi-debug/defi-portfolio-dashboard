# AI Portfolio Advisor — Technical Documentation

## Overview

The AI Portfolio Advisor generates data-driven analysis reports by combining market data, on-chain portfolio state, derived analytics, and historical context into a structured prompt sent to an LLM. The output is a structured JSON report with market regime assessment, portfolio evaluation, risk alerts, and actionable recommendations.

Three providers are supported: **OpenAI**, **Anthropic** (native Claude API), and **AWS Bedrock** (Claude models via your AWS account). Pick exactly one — they're mutually exclusive per report.

## Architecture

```
┌───────────────┐     ┌──────────────────┐     ┌─────────────┐     ┌──────────────┐
│  Scheduler /  │────▶│  Context Builder  │────▶│  LLM call   │────▶│  Report DB   │
│  manual button│     │  (ai_advisor.py)  │     │  (provider) │     │  (ai_reports)│
└───────────────┘     └──────────────────┘     └─────────────┘     └──────────────┘
                              │                                            │
                              ▼                                            ▼
                       ┌──────────────┐                              ┌──────────────┐
                       │ Data sources │                              │  Frontend    │
                       │ - DB market  │                              │  (ai.js)     │
                       │   snapshots  │                              │  AI Daily    │
                       │ - Portfolio  │                              │  Brief tab   │
                       │   (cached)   │                              └──────────────┘
                       │ - DB history │
                       │ - FRED cache │
                       └──────────────┘
```

The **context builder makes no live HTTP calls.** Market data, derived analytics, and pivot points are all read from `market_snapshots` in the local SQLite DB. The DB is populated by `snapshot_service.py`, which runs every 3 hours and pulls from CoinGecko, Bybit, DefiLlama, Deribit, Alternative.me, etc. (see main README for the full list of upstream services). Portfolio data comes from a 60-second in-memory cache shared with the rest of the dashboard.

This design keeps report generation fast (single DB read per section) and decouples the LLM from upstream API outages — if a vendor is down, the most recent snapshot is still usable.

## Files

| File | Purpose |
|------|---------|
| `src/engines/ai_advisor.py` | Context builder, orchestration, daily-digest generator, report writer |
| `src/engines/llm_providers.py` | OpenAI / Anthropic / Bedrock provider classes |
| `src/engines/ai_system_prompt.txt` | Base system prompt (git-controlled, defines role + JSON schema) |
| `src/engines/snapshot_service.py` | Background scheduler — runs market snapshots, AI report generation, and Telegram digest |
| `data/ai_config.json` | User configuration (provider, model, schedule, strategy playbook / custom prompt, auto-toggle) |
| `data/investor_profile.json` | Investor questionnaire answers (currently NOT included in the prompt — see [Investor Profile](#investor-profile-currently-disabled)) |
| `static/ai.js` | Frontend rendering for the AI Daily Brief tab |
| `static/portfolio.js` | Settings UI for the AI Advisor Configuration view |

## Triggers

- **Manual**: user clicks *Generate Report* in the AI Daily Brief tab → POST `/api/ai/generate`.
- **Scheduled**: `snapshot_service.ai_report_loop` runs daily at the configured UTC hour. Requires `auto_enabled: true` in `ai_config.json`. Generates the daily digest first (no LLM), then the AI report.
- **Telegram digest** (separate path): the same `generate_daily_digest()` powers the Telegram daily message — purely DB-driven, no LLM.

## Context Building (`build_context`)

The context is assembled into a Markdown-style document with these sections, each optional and skipped if data is unavailable:

### Market Data (DB-only)

Read from the most recent row of `market_snapshots`. Includes:

| Field | Source (populated by snapshot service) |
|---|---|
| BTC, ETH, SOL, TAO, SUI prices + 24h change | CoinGecko `/simple/price` |
| BTC/ETH dominance, market cap, volume | CoinGecko `/global` |
| BTC, ETH, SOL funding rates + open interest | Bybit `/v5/market/tickers` |
| Fear & Greed (current + history via DB) | alternative.me `/fng` |
| Stablecoin total supply | DeFiLlama `/stablecoinchains` |
| BTC, ETH 7d/30d returns + 30d realized vol | CoinGecko `/coins/{id}/market_chart` |
| BTC index price | Deribit |
| BTC 200-day moving average | CoinGecko market_chart |
| ETH gas price (gwei) | Ethereum RPC |
| Total DeFi TVL | DefiLlama |

The freshness dict reports `db (age: X.Xh)` so the LLM is informed about staleness.

### Macro Indicators (FRED, cached)

Read from a shared 24-hour cache via `web_portfolio.fetch_fred_macro`. Includes US10Y, DXY, M2 money supply, and Fed Funds rate. Skipped silently if FRED key isn't configured.

### Derived Analytics

Computed in-memory from the full history of `market_snapshots` (need 3+ rows). Includes:

- BTC/ETH/SOL **funding-rate Z-scores** vs the historical mean
- BTC/ETH **open-interest** change since oldest snapshot in window
- BTC/ETH **OI percentile** vs all observations
- **Fear & Greed** 7-day average vs lifetime mean
- **Stablecoin supply** trend (rising/declining/flat with %)

### Support / Resistance

**Weekly pivot points** computed from `market_snapshots` (not CoinGecko OHLC). For BTC and ETH:

```
Pivot = (High + Low + Close) / 3
R1 = 2*Pivot - Low      R2 = Pivot + (High - Low)
S1 = 2*Pivot - High     S2 = Pivot - (High - Low)
```

The "status" string tells the LLM whether the current price is above R1, between pivot and R1, etc.

### Portfolio Composition

Built from the live (60s-cached) `get_portfolio_data()` plus DB lookups:

| Data | Source |
|---|---|
| Token allocation by group (ETH, BTC, Stables, Yield Stables, Other) | Live cache, classified via `src/models.py` symbol sets |
| Active LP positions (chain, pair, range, in/out, fees, APR, age) | Live cache — Uniswap V3, Aerodrome Slipstream (with AERO rewards), Camelot, etc. |
| Active hedges (GMX V2: direction, size, entry, PnL, liquidation) | Live cache |
| AAVE V3 lending (collateral, debt, HF, supplied/borrowed by asset) | Live cache (RPC enrichment) |
| Manual LP positions / hedges | `lp_positions`, `hedge_positions` tables |
| BTC balance | xpub-derived addresses via Blockstream API |

### Previous Recommendations

The latest report's `recommendations` list is included verbatim. The LLM is asked to compare them against the current portfolio state and emit `previous_recommendations_review` entries with status `implemented | not_implemented | partially | unknown`.

### Investor Profile (currently disabled)

The investor questionnaire (`data/investor_profile.json`) is **commented out** in `build_context` (see TEMPORARILY DISABLED block). The intent was to include risk tolerance, target APY, drawdown limits, etc. — but this was disabled to test LLM accuracy with the strategy playbook alone. The profile UI and storage are still in place; only the prompt injection is off.

## System Prompt

Two layers:

1. **Base prompt** — `src/engines/ai_system_prompt.txt`, git-controlled. Sent as the system message. Defines:
   - Role: institutional-grade crypto portfolio advisor
   - Output: strict JSON matching the schema below
   - Reasoning rules: fact-based, quantitative, no speculation
2. **Strategy Playbook and Custom Instructions** — user-editable in Settings → AI Advisor Configuration. Free-form text the user writes describing their DeFi strategy, regime-specific preferences (bull / bear / sideways inline if they want), risk limits, etc. Prepended to the **user message** (not the system prompt) under the heading `## STRATEGY PLAYBOOK AND CUSTOM INSTRUCTIONS`. The base prompt instructs the LLM to consult this section in Step 5 (capital budget + candidate generation) and Step 7 (validation), and to fall back to its own judgment if no playbook is provided.

## LLM Providers

All three providers force a JSON-only response and use temperature `0.3`.

### OpenAI

- Endpoint: `POST https://api.openai.com/v1/chat/completions`
- Auth: bearer `OPENAI_API_KEY`
- Response format: `json_object`
- Timeout: 120s

### Anthropic (native)

- SDK: `anthropic` Python package
- Auth: `ANTHROPIC_API_KEY`
- Default model: `claude-sonnet-4-6`
- `max_tokens`: 8192
- Up to 3 retries with backoff on rate-limit / timeout / 5xx
- Best-effort JSON repair if the response is truncated mid-array

### AWS Bedrock

- Endpoint: `POST https://bedrock-runtime.{region}.amazonaws.com/model/{model}/converse`
- Auth: bearer `AWS_BEARER_TOKEN_BEDROCK` (region from `AWS_REGION`, default `us-east-1`)
- Default model: `us.anthropic.claude-3-5-haiku-20241022-v1:0`
- `maxTokens`: 8192
- Timeout: 300s
- Use **inference profile IDs** (e.g. `us.anthropic.claude-sonnet-4-6-v1:0`) for newer Claude models, not raw model IDs

## Output Schema

Every report — regardless of provider — returns this JSON shape:

```json
{
  "report_date": "2026-05-13",
  "market_regime": {
    "short_term_7d": {
      "bull": 20, "bear": 55, "sideways": 25,
      "reasoning": "Factual explanation referencing data points"
    },
    "mid_term_30d": {
      "bull": 40, "bear": 30, "sideways": 30,
      "reasoning": "Factual explanation referencing data points"
    },
    "data_confidence": "moderate — note about data availability"
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
      "priority": "high | medium | low"
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

If the LLM returns truncated/invalid JSON, the Anthropic provider attempts a best-effort repair (closing dangling brackets and braces); other providers surface the parse failure to the user.

## Storage

Reports persist in `ai_reports`:

| Column | Type | Content |
|---|---|---|
| `timestamp` | TIMESTAMP | UTC time of generation |
| `provider` | TEXT | `openai` / `anthropic` / `bedrock` |
| `model` | TEXT | Model ID used |
| `market_regime_json` | TEXT | Regime block JSON |
| `portfolio_alignment` | TEXT | `aligned` / `partially_aligned` / `misaligned` |
| `summary` | TEXT | Market analysis summary |
| `full_report_json` | TEXT | Complete JSON report |
| `previous_recs_review_json` | TEXT | Review of last report's recommendations |
| `prompt_tokens` | INTEGER | Input tokens (provider-reported) |
| `completion_tokens` | INTEGER | Output tokens |
| `data_freshness_json` | TEXT | Per-section freshness map (live / db age / failed) |

A separate `daily_digests` table stores DB-driven daily digests produced by `generate_daily_digest()` (no LLM call) — used by the Telegram bot and the dashboard's quick-summary view.

## Frontend Display

Located in **AI Daily Brief**:

- **Market Regime** — probability bars (bull / sideways / bear) for 7d and 30d, with reasoning
- **Market Analysis** — summary, key-metrics table, S/R levels for BTC and ETH
- **Portfolio Assessment** — alignment badge, strengths (green) / concerns (orange)
- **Risk Alerts** — color-coded by severity (info / warning / critical)
- **Recommendations** — numbered cards with action, rationale, priority, deadline, and impact
- **Previous Recommendations Review** — status badges (implemented / not / partially / unknown)
- **Report History** — dropdown to view past reports

## Configuration

### Settings → AI Advisor Configuration

| Field | Description | Default |
|---|---|---|
| Provider | `OpenAI` / `Claude (Anthropic)` / `AWS Bedrock` | openai |
| Model | Provider-specific model ID | gpt-4o |
| Schedule (UTC hour) | When the daily auto-run fires | 8 |
| Auto-generate | Toggle the daily run on/off | Off |
| Strategy Playbook and Custom Instructions | Free-text field for the user's strategy and any standing guidance. Include regime-specific preferences (bull / bear / sideways) inline if desired — there is no separate per-regime field. | empty |

### Settings → API Keys (separate section)

LLM provider API keys live under **Settings → AI Provider Keys**, not under AI Advisor Configuration:

| Variable | Required for | Source |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI provider | platform.openai.com |
| `ANTHROPIC_API_KEY` | Anthropic provider | console.anthropic.com |
| `AWS_BEARER_TOKEN_BEDROCK` (+ optional `AWS_REGION`) | Bedrock provider | AWS Bedrock console |

### Config file: `data/ai_config.json`

```json
{
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "schedule_utc_hour": 8,
  "auto_enabled": true,
  "custom_system_prompt": "Bull regime: lean into concentrated LP ranges on majors with 1.2x hedge coverage, target ~60% LP / 30% lending / 10% idle.\nBear regime: prefer stablecoin lending + WBTC accumulation, max 30% directional exposure.\nSideways: tight LP ranges with active rebalancing, ~50% LP / 40% lending / 10% idle."
}
```

(Old configs may still contain a `strategies` key with `bull`/`bear`/`sideways` sub-fields — it's ignored at load time and dropped on the next save.)

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/ai/config` | Get AI configuration |
| POST | `/api/ai/config` | Save AI configuration |
| POST | `/api/ai/generate` | Generate a new AI report (calls the LLM) |
| POST | `/api/ai/digest` | Generate a daily digest (DB-only, no LLM) |
| GET | `/api/ai/digest/latest` | Latest digest, auto-regenerated if stale |
| GET | `/api/ai/reports?limit=N` | List recent reports (summary) |
| GET | `/api/ai/reports/<id>` | Full report detail |

## Design Decisions

### Why structured JSON output?

- Consistent frontend rendering
- Programmatic analysis of recommendations over time
- Tracking implementation across reports
- Avoids free-form text that's hard to parse

### Why probability-based regime assessment?

- Avoids false confidence in single-label predictions
- Forces uncertainty to be expressed quantitatively
- Useful for strategy selection — 60% bear leans defensive without going all-in

### Why DB-only context (no live API fetches in the prompt)?

- Snapshot service already pulls everything every 3 hours; redundant fetches at report time would just add latency
- Decouples reports from upstream API outages — the most recent snapshot is always usable
- Lets derived analytics (Z-scores, percentiles) read full history in one query

### Why a single playbook field instead of per-regime textareas?

- The original design had three textareas (Bull / Bear / Sideways). In practice users either left two of them empty or wrote essentially the same content in each, and forcing a discrete partition didn't match how strategies are actually written down.
- A single free-text field lets users write whatever structure makes sense for them — bullet points, regime-by-regime sections, decision trees, or a single paragraph of guidance.
- The system prompt still asks the LLM to identify the current regime and apply the matching guidance from the playbook, falling back to its own judgment if the playbook doesn't address that regime.
- Keeping behavior + JSON schema in the git-controlled system prompt and user-specific guidance in the playbook field preserves the same separation of concerns with less ceremony.

### Why pivot points instead of ML for S/R?

- Deterministic, widely used by institutional traders, no training data needed
- Transparent calculation the user can verify
- Computed from data already in `market_snapshots`, not a separate fetch

### Why not integrate the Range Optimizer into the prompt?

- The optimizer assumes a random walk (no directional bias)
- The LLM's regime call is directional
- Combining them would contaminate the statistical model with qualitative judgment

## Token Usage Estimates

| Component | Approx. Tokens |
|---|---|
| System prompt | ~800 |
| Market data | ~500-800 |
| Macro / FRED | ~150-300 |
| Derived analytics | ~200-400 |
| S/R levels | ~200 |
| Portfolio context | ~300-700 |
| Previous recommendations | ~100-300 |
| **Total input** | **~2,200-3,500** |
| **Output** | **~1,500-3,000** |
| **Total per report** | **~3,700-6,500** |

Cost per report (rough, varies with model):

- GPT-4o: ~$0.03-0.07
- Claude Sonnet 4.x: ~$0.05-0.12
- Claude Haiku 4.5: ~$0.005-0.015
- Claude Opus 4.x: ~$0.20-0.45

(Run a few reports and check the `prompt_tokens` / `completion_tokens` columns in `ai_reports` for actual per-report costs against your provider's pricing.)
