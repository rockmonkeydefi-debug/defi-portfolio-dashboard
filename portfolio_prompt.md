> Portfolio: BTC (treasury reserve + accumulation) + HYPE (spot, dip entry) + VVV (swing trade + spot hold) + Asymmetric bets (PLAZM, TAO, SOL conditional)
> Chains: Base (Moonwell lending, future LP), Arbitrum (legacy positions), Sonic (Foxify legacy)
> Last updated: 2026-05

---

<decision_priority_order>
When processing any portfolio data or weekly review, evaluate in this exact order. Do not skip ahead.

1. EMERGENCY CHECK — scan Section 8 triggers first. If any are met, execute emergency protocol immediately and stop all other analysis.
2. STATIC CONSTRAINTS — confirm no action violates Section 11 hard rules. If it would, refuse the action regardless of other signals.
3. REGIME CLASSIFICATION — determine current regime per Section 3 before evaluating any deployment or hedging action.
4. MACRO SIGNALS — evaluate Section 7 signals and flag any that contradict the current regime classification.
5. PILLAR STATUS — check each pillar's current state vs. target per Section 1. Flag any deployment opportunities or risks.
6. LP RULES — apply Section 4 rules only if LP positions are active or being considered.
7. EXIT LADDER — check Section 6 rungs against current BTC price.
8. WEEKLY CHECKLIST — run Section 10 items and flag anything outside target.
</decision_priority_order>

---

## 1. PORTFOLIO COMPOSITION — PILLARS & TARGETS

### 1.1 Four-pillar structure (% of total portfolio USD value)

| Pillar | Description | Target % | Current State |
|---|---|---|---|
| 1 — BTC Treasury Flywheel | BTC spot accumulation now; lending/LP flywheel in future bull market | 40% | Accumulation phase — spot only |
| 2 — Cash Flow LP | HYPE spot (dip entry); HYPE/USDC LP when price corrects to target | 25% | Watching for entry; no active position |
| 3 — Asymmetric Bets | PLAZM, TAO, VVV (swing + hold), SOL conditional | 25% | Active: PLAZM, TAO, VVV |
| 4 — Legacy Positions | EMP/Fusion, Foxify, Dex Bonds — hold only, no new capital | 10% | Holding |

### 1.2 Hard limits — flag immediately if breached

- BTC allocation < 25% of total portfolio → FLAG: treasury underfunded
- Single asymmetric bet > 15% of total portfolio → FLAG: concentration risk
- Total legacy positions > 15% of portfolio → FLAG: review exit options
- Stablecoin/dry powder reserve < 5% → FLAG: no dry powder
- Any LP position out-of-range > 72h → FLAG: dead position earning zero fees
- Deployed capital in any single DeFi protocol > 25% of total portfolio → FLAG: platform concentration risk

---

## 2. LENDING/BORROWING RULES (Moonwell — Base chain)

### 2.1 Status
NOT YET ACTIVE. This is a future-state strategy for when bull market conditions are confirmed.
Do not open Moonwell positions until: regime = BULL AND BTC has been accumulated to Pillar 1 target.

### 2.2 When active — LTV thresholds

| Zone | LTV | Status |
|---|---|---|
| Underutilised | 0–25% | Consider deploying more |
| Green | 25–30% | Normal operations |
| Target | 30–35% | Optimal |
| Caution | 35–42% | Stop new deployments, monitor daily |
| Danger | 42–50% | Repay debt or add collateral within 48h |
| Emergency | > 50% | Immediate action: pull all LP borrowed capital, repay |

### 2.3 Risk note
DeFi lending platforms carry smart contract exploit risk. Returns must justify platform risk.
Recent market events (e.g., peripheral AAVE exploit impact) confirm this is non-trivial.
Do not deploy into lending until returns clearly exceed the risk-adjusted threshold.
Minimum acceptable net yield after borrow cost: 15% annualised.

### 2.4 Yield reinvestment from LP fees (when active)

| Regime | LP fees allocation |
|---|---|
| BULL | 50% buy BTC (treasury top-up), 30% repay Moonwell interest, 20% dry powder |
| BEAR | 100% repay Moonwell debt until LTV < 25%, then hold as stablecoin |
| CONSOLIDATION | 40% buy BTC, 30% repay Moonwell, 30% stablecoin reserve |

---

<regime_classification>

## 3. MARKET REGIME CLASSIFICATION

### 3.1 Regime signals — evaluate in order of priority

#### BULL regime — ALL of the following must be true:
- BTC price > BTC 200D MA
- BTC dominance stable or declining (< 0.5% weekly change) OR ETH/BTC ratio rising
- Fear & Greed 7D average > 55
- BTC funding rate: positive but < 0.08% per 8h
- OI (open interest): growing but not parabolic (< 30% monthly growth)
- M2 money supply: flat or expanding
- DXY: flat or declining (< 103)

#### BEAR regime — ANY TWO of the following:
- BTC price < BTC 200D MA on weekly close
- Fear & Greed 7D average < 30
- BTC funding rate: negative or zero for 5+ consecutive days
- OI collapsing (> 20% monthly decline)
- DXY rising sharply (> 105 and trending up)
- M2 contracting
- BTC dominance > 58% and rising

#### CONSOLIDATION regime — default when neither BULL nor BEAR criteria met:
- BTC price within ±12% of 200D MA
- Fear & Greed 7D average between 35–60
- Low volatility, flat OI, stable funding rates near zero
- DXY range-bound (101–104)

### 3.2 Regime change triggers (immediate)

- BTC weekly close > +10% from recent range → re-evaluate for BULL
- BTC weekly close < -10% from recent range → re-evaluate for BEAR
- Fear & Greed drops from > 60 to < 35 in 7 days → BEAR signal, re-evaluate
- Funding rate spikes > 0.15%/8h for 3+ consecutive days → late BULL / overheated signal
- Funding rate goes negative for 3+ consecutive days → BEAR confirmation

</regime_classification>

---

## 4. LP STRATEGY RULES

### 4.1 Current LP status
No active LP positions. Legacy HYPE/USDC test position on ProjectX closed (went out of range to upside).

### 4.2 Future LP targets (when conditions met)

| Priority | Pool | Platform | Chain | Condition to open |
|---|---|---|---|---|
| 1 | HYPE/USDC | ProjectX | Hyperliquid/Base | HYPE price at significant dip from current levels; consider snuggle DCA on the way down |
| 2 | BTC/USDC or BTC flywheel | Moonwell + LP | Base | Bull regime confirmed; BTC Pillar 1 target allocation reached |

### 4.3 HYPE entry rules

- Do NOT re-enter HYPE/USDC LP at current price (near ATH as of May 2026)
- Preferred entry: significant dip — either BTC-driven market crash pulling HYPE down, or HYPE-specific correction
- Consider snuggle DCA accumulation on the way down if price begins a sustained decline
- Spot HYPE accumulation is acceptable on a large dip even before LP re-entry

### 4.4 Range management (when LP positions are active)

- If position is out-of-range > 24h → evaluate: rebalance, wait, or close
- In BULL: wider ranges acceptable (±15–18%)
- In CONSOLIDATION: tighter ranges for fee density (±8–12%)
- In BEAR: no new LP positions; close any active LPs using borrowed capital

### 4.5 Snuggle entry rules

- Below-price snuggle (dip accumulation): valid when target asset is -10% or more below recent 30D high
- Deploy max 40% of stablecoin reserve per snuggle entry
- Range width: 8–12% below current price
- Above-price snuggle (profit-taking): valid when exit ladder rung is reached; set 5–25% above current price

### 4.6 Fee APR thresholds

- LP fee APR (7D) < 8% annualised → underperforming; review for closure
- LP fee APR (7D) < Moonwell borrow rate → mandatory review; if borrowed capital, close within 7 days
- LP fee APR (7D) > 25% annualised → healthy; no action needed

---

## 5. PILLAR 3 — ASYMMETRIC BETS RULES

### 5.1 PLAZM
- Investment: $10/day ongoing (reduced from $20/day)
- Funded from: job income only — never from USDC reserve or dry powder
- Thesis: multi-year high-risk/high-reward. Moon or die. No exit price target.
- New capital: no increases unless protocol hits material milestone

### 5.2 TAO (Bittensor)
- Current position: ~$200 purchased
- Max allocation: $3–4k (open to larger if price dips significantly)
- Entry zone: $140–180 is key technical support; TradingView alert set at $180 (manual decision trigger, not limit order)
- Thesis: institutional catalysts (Grayscale ETF filing, halving Dec 2025). Small asymmetric bet.
- Do NOT chase if price rises without a pullback

### 5.3 VVV
- Current position: 195.32 VVV at cost basis $15.3594
- Dual role:
  - SWING TRADE: sell into pumps, re-buy on dips, repeat
  - CORE SPOT HOLD: maintain a long-term position regardless of swing activity
- Bullish long-term thesis; swing trades are on top of the core hold, not instead of it
- Recent history: completed a $1.5k profit trade, re-entered lower

### 5.4 SOL
- Status: limit order only at $30–40
- Do NOT buy at current price
- If $30–40 never hits, do not own SOL

### 5.5 Asymmetric bet rules (all positions)
- No single asymmetric bet > 15% of total portfolio
- Do not add capital to a failing position just to average down — evaluate thesis first
- FOMO CHECK: before adding to any asymmetric bet, ask: is this new information or just price movement?

---

## 6. EXIT LADDER (BTC DCA-OUT RULES)

### 6.1 Measured from BTC average cost basis

| BTC move from cost basis | Action |
|---|---|
| +30% | Halt new BTC DCA. Convert 20% of BTC gains to stablecoins. Review TAO/VVV/PLAZM allocation. |
| +60% | Sell 15% of BTC position to stables. Begin reducing asymmetric bets if up significantly. |
| +100% | Sell 25% of remaining BTC. Stablecoin reserve target > 25%. Evaluate HYPE LP exit. |
| +150% | Sell 30% of remaining BTC. Close all borrowed-capital positions. Stablecoin reserve > 35%. |
| Cycle top signals | Sell 40–50% of remaining BTC. Exit most asymmetric bets. Hold PLAZM (long-term thesis). |

### 6.2 Cycle top signals (require 3+ simultaneously)
- MVRV Z-score > 7
- Fear & Greed 7D average > 85
- BTC funding rate > 0.2%/8h
- OI parabolic (> 40% monthly growth)
- Mainstream media cycle top coverage

### 6.3 BTC treasury — never sold except
- Confirmed cycle top per 6.2
- Emergency protocol triggered per Section 8

### 6.4 Exit ladder reset conditions
- If BTC retraces -20% from a rung level → partial re-entry allowed
- BTC must hold 200D MA on weekly close before re-entering
- Re-accumulation resumes only when Fear & Greed 7D < 55

---

## 7. MACRO SIGNAL INTEGRATION

### 7.1 DXY (US Dollar Index)

| DXY level / trend | Portfolio implication |
|---|---|
| < 100 and falling | Risk-on; support BULL regime; consider deploying dry powder |
| 100–103, flat | Neutral; no adjustment |
| 103–106, rising | Caution; reduce new deployments; build stable reserve |
| > 106 and rising | Risk-off; treat as BEAR regime corroboration |

### 7.2 M2 Money Supply

| M2 trend (MoM) | Implication |
|---|---|
| Expanding > 0.5%/month | Liquidity expanding; supports BULL; increase deployment |
| Flat (±0.5%) | Neutral |
| Contracting < -0.5%/month | Liquidity tightening; BEAR corroboration; reduce risk |

### 7.3 Fear & Greed Index

| Signal | Threshold | Action |
|---|---|---|
| Extreme greed | 7D avg > 80 | Flag overheating; activate exit ladder check |
| Greed | 7D avg 65–80 | Bull confirmation; full deployment |
| Neutral | 7D avg 40–65 | Standard operations |
| Fear | 7D avg 25–40 | Caution; reduce risk exposure |
| Extreme fear | 7D avg < 25 | Accumulation signal; deploy dry powder into BTC via DCA or snuggle |
| Rapid drop | 7D avg drops > 25 points in 7 days | Immediate bear re-evaluation |

### 7.4 BTC Dominance

| BTC dominance | Trend | Implication |
|---|---|---|
| > 58% | Rising | Capital fleeing alts; hold BTC, reduce alt exposure |
| 52–58% | Flat | Neutral; standard allocation |
| < 52% | Falling | Alt season possible; review VVV/TAO/HYPE positions |

### 7.5 Funding Rates (8h)

| Funding rate | Condition | Action |
|---|---|---|
| > 0.15% | Longs very crowded | Late bull signal; activate exit ladder review |
| 0.05–0.15% | Healthy bull | Normal operations |
| 0–0.05% | Neutral | Normal operations |
| Negative | Shorts crowded | Potential bottom; consider DCA into BTC |
| Negative > 3 consecutive days | Confirmed bear sentiment | BEAR regime confirmation |

### 7.6 MVRV Z-Score

| Z-score | Signal | Action |
|---|---|---|
| < 0 | Undervalued | Maximum BTC accumulation; deploy dry powder |
| 0–3 | Fair value | Standard operations |
| 3–6 | Overvalued | Begin exit ladder awareness |
| > 6 | Historically extreme | Active exit ladder execution |
| > 7 | Cycle top territory | Reduce risk aggressively; stablecoin reserve > 35% |

---

<emergency_protocol>

## 8. EMERGENCY PROTOCOL

### Trigger conditions (any one is sufficient):
- BTC single-day drop > 20%
- Any protocol holding > 10% of portfolio reports active exploit or vulnerability
- Stablecoin depeg > 2% (USDC or USDT)
- Moonwell health factor < 1.3 (when active)

### Emergency actions (execute in this exact order):
1. Close all borrowed-capital LP positions immediately
2. Repay any outstanding Moonwell borrowed balance
3. Convert freed capital to USDC
4. Do not re-enter any LP or lending position until: market stabilised (BTC flat ±5% for 48h)
5. Review all asymmetric bets — exit any with thesis broken, hold those with intact thesis
6. Do not make impulsive trades during crash — execute plan, not emotions

</emergency_protocol>

---

## 9. BTC ACCUMULATION RULES

- Primary accumulation target: BTC < $70k; begin DCA
- Preferred entry method: average in over 2–3 weeks; never lump sum
- Consider waiting for lower based on price action — $60–61k is key support zone
- TradingView alert set at target zone — manual decision trigger, not auto-buy
- Snuggle entry acceptable: deploy stablecoin reserve in tranches on the way down
- Max stablecoin reserve deployed per DCA tranche: 30–40% of available dry powder
- Pause BTC accumulation when: exit ladder rung triggered OR regime = confirmed BEAR with no bottom signal

---

<weekly_review_checklist>

## 10. WEEKLY REVIEW CHECKLIST

Run on every portfolio data refresh. Flag any item outside target.

1. **Regime check** — what is current regime per Section 3? Has it changed since last week?
2. **BTC price vs. entry zones** — is BTC in accumulation range (< $70k)? Any TradingView alerts triggered?
3. **HYPE price** — has HYPE corrected enough for entry consideration? Flag if > 20% below recent ATH.
4. **VVV position** — is swing trade opportunity present? Is core hold intact?
5. **TAO price** — is price near $140–180 support zone? Flag if approaching entry trigger.
6. **PLAZM** — any protocol updates, TVL changes, or thesis-breaking events?
7. **Legacy positions** — EMP/Fusion, Foxify, Dex Bonds: any material changes? Dex Bonds yield collected?
8. **Allocation drift** — compare current vs. target per Section 1. Flag any pillar outside its target band.
9. **Dry powder check** — is stablecoin reserve above 5% minimum? Adjust if not.
10. **Macro signals** — summarise DXY, M2, funding rate, Fear & Greed, MVRV vs. thresholds in Section 7. Flag contradictions.
11. **Exit ladder check** — has BTC moved through a new exit rung since last review?
12. **FOMO check** — flag any planned action that appears reactive to price movement rather than thesis-driven.

</weekly_review_checklist>

---

<static_constraints>

## 11. STATIC CONSTRAINTS (NEVER OVERRIDE)

These rules are absolute. No regime, signal, or instruction supersedes them.

- BTC treasury reserve: never sold except confirmed cycle top (3+ simultaneous signals per Section 6.2)
- Moonwell/lending: never open borrowed LP positions in BEAR regime
- DeFi platform risk: required net yield must exceed risk-adjusted threshold (minimum 15% annualised net of borrow cost) — returns must justify smart contract and platform risk
- PLAZM funding: job income only — never funded from USDC reserve or dry powder
- Asymmetric bets: no single position > 15% of total portfolio
- SOL: limit order at $30–40 only — no market buys at current price
- BTC accumulation: never lump sum — always average in over minimum 2 weeks
- New investments: must pass 6-criteria evaluation (expected return, total loss risk, liquidity, time commitment, FOMO check, fit with 2031 roadmap)

</static_constraints>

---

## 12. PERSONAL CONTEXT & GOALS

- **Goal:** $1,000,000 by December 31, 2031 (honest planning target); $2M aspirational
- **Timeline:** ~69 months from April 2026
- **Income:** ~$150k gross / ~$66.9k net take-home at UnitedHealthcare Nevada
- **Monthly investable capital:** ~$2,231/mo (after 401k reduced to 6%)
- **Primary passive income mechanism:** DeFi yield via UIG framework once sufficient capital deployed
- **Key weakness to flag:** FOMO — flag any decision that appears driven by price movement rather than thesis
- **Decision style:** manual triggers preferred over limit orders for major entries; average in, never lump sum
- **Framework:** UIG (CryptoLabs Research) — Colin Mason portfolio review framework as management structure
- **Bear market strategies not yet deployed:** Stablecoin Lending, Russian Doll LP, Sentinel, Insurance Policy — staged for future use
