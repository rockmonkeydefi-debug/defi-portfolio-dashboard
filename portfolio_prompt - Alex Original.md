> Portfolio: BTC (treasury reserve) + WBTC (Aave collateral) + WETH/ETH (LP fuel + accumulation)
> Chains: Arbitrum (primary LP), Base (secondary LP), Mainnet (Aave only – no LP activity)
> Last updated: 2026-04

---

<decision_priority_order>
When processing any portfolio data or weekly review, evaluate in this exact order. Do not skip ahead.

1. EMERGENCY CHECK — scan Section 8 triggers first. If any are met, execute emergency protocol immediately and stop all other analysis.
2. STATIC CONSTRAINTS — confirm no action violates Section 11 hard rules. If it would, refuse the action regardless of other signals.
3. AAVE HEALTH — check HF and LTV per Section 2. If in Danger or Emergency zone, this overrides all LP deployment decisions.
4. REGIME CLASSIFICATION — determine current regime per Section 3 before evaluating any LP or hedging action.
5. MACRO SIGNALS — evaluate Section 7 signals and flag any that contradict the current regime classification.
6. LP RULES — apply Section 4 rules within the confirmed regime context.
7. HEDGING RULES — apply Section 5 only after regime and LP state are known.
8. EXIT LADDER — check Section 6 rungs against current BTC price.
9. WEEKLY CHECKLIST — run Section 10 items and flag anything outside target.
</decision_priority_order>

---

## 1. PORTFOLIO COMPOSITION TARGETS

### 1.1 Baseline allocation (% of total portfolio USD value)

| Sleeve | Min | Target | Max |
|---|---|---|---|
| BTC treasury reserve (native BTC, treasury wallet) | 20% | 25% | 30% |
| WBTC / cbBTC on Aave (collateral) | 17% | 20% | 27% |
| ETH / WETH (idle + accumulation) | 15% | 25% | 35% |
| Active LP positions (all pools combined) | 15% | 22% | 30% |
| Stablecoin reserve (USDC/USDT, not deployed) | 5% | 8% | 20% |

### 1.2 Hard limits – flag immediately if breached

- BTC treasury reserve < 15% → FLAG: treasury reserve underfunded
- Total WBTC exposure (Aave + any LPs) > 30% → FLAG: excessive WBTC counterparty concentration, consider cbBTC
- ETH allocation > 35% → FLAG: ETH overweight, trim required
- Stablecoin reserve < 4% → FLAG: no dry powder
- Single LP position > 20% of total portfolio → FLAG: LP concentration risk
- LP capital from borrowed Aave funds > 15% of total portfolio → FLAG: leverage overextended
- Any LP position out-of-range > 72h → FLAG: dead position, earning zero fees

---

## 2. AAVE V3 RULES (Mainnet)

### 2.1 LTV and health factor thresholds

| Zone | LTV | Health Factor | Status |
|---|---|---|---|
| Underutilised | 0–28% | > 4.0 | Consider deploying more |
| Green | 28–35% | 2.5–4.0 | Normal operations |
| Target | 35–40% | 2.0–2.5 | Optimal |
| Caution | 40–50% | 1.5–2.0 | Stop new deployments, monitor daily |
| Danger | 50–60% | 1.2–1.5 | Repay debt or add collateral within 48h |
| Emergency | > 60% | < 1.2 | Immediate action: pull all LP borrowed capital, repay |

### 2.2 Aave decision rules

- If LTV < 28% AND regime = BULL → suggest increasing WBTC collateral deployment
- If LTV > 42% → halt all new LP deployments regardless of regime
- If LTV > 50% → close lowest-APR LP first, use proceeds to repay
- If LTV > 58% → close ALL borrowed-capital LPs, repay immediately
- If Health Factor < 1.5 → emergency protocol (see Section 8)
- If Aave WBTC borrow rate > LP fee APR (7D, best pool) → borrowed LP is loss-making; flag for closure
- If Aave WBTC borrow rate > LP fee APR (7D) + 2% → close borrowed LP, repay debt

### 2.3 Yield reinvestment from LP fees

| Regime | LP fees allocation |
|---|---|
| BULL | 50% buy ETH, 30% buy BTC (treasury reserve top-up), 20% repay Aave interest |
| BEAR | 100% repay Aave debt until LTV < 28%, then hold as stablecoin |
| CONSOLIDATION | 40% buy ETH (accumulation), 30% repay Aave, 30% stablecoin reserve |

---

<regime_classification>

## 3. MARKET REGIME CLASSIFICATION

### 3.1 Regime signals – evaluate in order of priority

#### BULL regime – ALL of the following must be true:
- BTC price > BTC 200D MA
- BTC dominance stable or declining (< 0.5% weekly change) OR ETH/BTC ratio rising
- Fear & Greed 7D average > 55
- BTC funding rate: positive but < 0.08% per 8h
- OI (open interest): growing but not parabolic (< 30% monthly growth)
- M2 money supply: flat or expanding
- DXY: flat or declining (< 103)
- Volatility regime: low or medium

#### BEAR regime – ANY TWO of the following:
- BTC price < BTC 200D MA on weekly close
- Fear & Greed 7D average < 30
- BTC funding rate: negative or zero for 5+ consecutive days
- OI collapsing (> 20% monthly decline)
- DXY rising sharply (> 105 and trending up)
- M2 contracting
- BTC dominance > 58% and rising (capital fleeing altcoins/ETH)

#### CONSOLIDATION regime – default when neither BULL nor BEAR criteria met:
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

### 4.1 Layer structure (per pool)

| Layer | Range width | Capital allocation | Borrowed capital allowed | Rebalance trigger |
|---|---|---|---|---|
| Core (tight) | ±5–8% | 35–40% of LP sleeve | No | Price exits range |
| Shell (medium) | ±12–18% | 30–35% of LP sleeve | Yes (primary) | APR drop > 40% from entry OR 3 weeks |
| Outer (wide) | ±25–40% | 20–25% of LP sleeve | No | Monthly or on full exit |

### 4.2 Range management rules

- If core layer is out-of-range > 24h → reset core centred on current price
- If shell layer APR (7D) < Aave borrow rate → close shell if it uses borrowed capital
- If outer layer is out-of-range → do NOT reset; outer layer is designed to sit idle until price returns
- In BULL: preferred range = ±15–18% (shell), ±6% (core)
- In CONSOLIDATION: preferred range = ±8–12% (shell), ±5% (core) – tighter for fee density
- In BEAR: collapse to outer layer only, no core or shell, no borrowed capital in any LP

### 4.3 Fee APR thresholds (from DeFiLlama data)

- LP fee APR (7D) < 8% annualised → flag as underperforming; review for closure
- LP fee APR (7D) < Aave borrow rate → mandatory review; if borrowed capital, close within 7 days
- LP fee APR (7D) > 25% annualised → healthy; no action needed
- LP fee APR (7D) drops > 50% from entry APR → re-evaluate range or pool

### 4.4 Pool priority by chain

| Priority | Chain | Pool type | Protocol |
|---|---|---|---|
| 1 | Arbitrum | WETH/USDC | Uniswap v3 |
| 2 | Arbitrum | WBTC/USDC | Uniswap v3 |
| 3 | Base | WETH/USDC | Aerodrome (vAMM) |
| 4 | Base | WETH/stable | Aerodrome (sAMM) |
| 5 | Base or Arbitrum | USDC/USDT | Curve / stable AMM |

- Never LP on Mainnet (gas cost destroys returns at this portfolio size)
- Aerodrome AERO emissions: claim if unclaimed > 5 days
- If pool TVL drops > 30% in 30 days on DeFiLlama → migrate to next priority pool

### 4.5 Snuggle entry rules

- Below-price snuggle (dip accumulation): valid when ETH is -8% or more below recent 30D high; deploy stablecoin reserve (max 40% of stable reserve); range width 8–12% below current price
- Above-price snuggle (profit-taking): valid when exit ladder rung is reached (see Section 6); deploy ETH/WBTC into range set 5–25% above current price; width 8–12%
- If price gaps over a snuggle range without gradual conversion → treat as a limit order fill; review if the resulting position is still in-range

### 4.6 IL rules

- If unrealised IL > 3% of position value → review immediately
- If unrealised IL > accumulated fees (since position opened) → flag as loss-making
- If borrowed-capital position is IL-negative net of fees → close and repay Aave
- ETH/stable pools: higher IL risk during ETH volatility spikes; widen range or switch to Aerodrome sAMM

---

## 5. DELTA-NEUTRAL AND HEDGING RULES

### 5.1 Delta-neutral via perp hedge

- Applicable to: WETH/USDC and WBTC/USDC LP positions only
- Perp platform: Hyperliquid (preferred) or GMX
- Max perp leverage: 1x–2x (hedging only, not speculation)
- Perp size = LP notional × LP delta estimate
  - LP delta estimate: 50% at entry; adjusts toward 0% (fully stable) or 100% (fully crypto) as price moves through range
  - Rebalance perp weekly or when LP composition shifts > 20% from entry
- Funding rate watch: if annualised funding cost on perp > 15% → hedge is expensive; flag and reassess

### 5.2 Perp short hedge (Aave / downside protection)

| Trigger | Action |
|---|---|
| BTC run > 40% in 60 days AND HF < 2.5 | Open BTC short perp = 20% of WBTC collateral value |
| HF < 2.0 | Open BTC short perp = 25% of WBTC collateral value |
| HF < 1.5 | Emergency (see Section 8); close LPs, repay Aave |
| Funding rate > 0.15%/8h for 3+ days | Reduce or close long perp hedge (expensive carry) |
| MVRV Z-score > 6 | Open short hedge = 25% of total BTC+ETH exposure |
| BTC -20% from hedge entry price | Take profit on short; close hedge |

- Max short hedge at any time: 30% of total BTC+ETH portfolio exposure
- Never hedge > 30% in bull market (caps upside unacceptably)
- Short hedge priority: BTC perp first; ETH perp only if BTC hedge is insufficient

### 5.3 Pseudo delta-neutral (LP-only, no perps)

- Valid for CONSOLIDATION regime only
- Structure: above-price snuggle (100% ETH) + core LP (centred on price) + below-price snuggle (100% stables)
- Sizing: 30% above-price / 40% core / 30% below-price of LP sleeve capital
- Exit condition: when regime shifts to BULL or BEAR, collapse to standard single-side structure

---

## 6. EXIT LADDER (DCA-OUT RULES)

### 6.1 Measured from BTC cycle entry price (or last reset price after -30% drawdown)

| BTC move from baseline | Action |
|---|---|
| +20% | Close core LP layer. Convert 50% freed capital to stables. Halt ETH accumulation DCA. Tighten Aave LTV to 30%. |
| +40% | Sell 20% of ETH position to stables. Close all borrowed-capital LPs. Repay Aave borrowed debt partially (target LTV 28%). Set above-price snuggle for remaining ETH. |
| +60% | Sell 30% of remaining ETH. Close shell LP layer. Repay all Aave borrowed debt. Stablecoin reserve target: 20–25%. Open BTC short hedge = 15–20% of BTC exposure. Only outer LP layer remains. |
| +80% | Close all LPs. Sell 40% of remaining ETH. Expand BTC short hedge to 25% of BTC exposure. Stablecoin reserve: 30–35%. Monitor weekly for cycle top signals. |
| +100% | Reduce ETH to 5% of portfolio. Stablecoin reserve > 40%. BTC treasury reserve: hold, never sell. Watch: MVRV Z-score > 7, NUPL > 0.75, funding > 0.2%/8h, Fear & Greed 7D > 85. |

### 6.2 Exit ladder reset conditions

- If BTC retraces -20% from a rung level → partial re-entry of previous rung positions allowed
- Confirm retracement is not trend reversal: BTC must hold 200D MA on weekly close before re-entering
- ETH re-accumulation resumes only when: Fear & Greed 7D < 55 AND BTC stable above 200D MA

### 6.3 What is never sold on exit ladder

- BTC treasury reserve: never sold at any rung
- BTC treasury reserve is only reduced by: confirmed cycle top signals across 3+ independent indicators simultaneously

---

## 7. MACRO SIGNAL INTEGRATION

### 7.1 DXY (US Dollar Index)

| DXY level / trend | Portfolio implication |
|---|---|
| < 100 and falling | Risk-on; support BULL regime; deploy LP capital fully |
| 100–103, flat | Neutral; no adjustment |
| 103–106, rising | Caution; reduce new LP deployments; build stable reserve |
| > 106 and rising | Risk-off signal; treat as BEAR regime corroboration; increase hedge |

### 7.2 M2 Money Supply

| M2 trend (MoM) | Implication |
|---|---|
| Expanding > 0.5%/month | Liquidity expanding; supports BULL; increase LP deployment |
| Flat (±0.5%) | Neutral |
| Contracting < -0.5%/month | Liquidity tightening; BEAR corroboration; reduce leverage |

### 7.3 Fed Funds Rate

- If Fed Funds Rate cut ≥ 25bps in last 90 days → BULL corroboration signal
- If Fed Funds Rate hike ≥ 25bps in last 90 days → BEAR corroboration signal; reduce Aave LTV to 30%
- If rate unchanged > 6 months AND M2 flat → CONSOLIDATION default

### 7.4 Fear & Greed Index

| Signal | Threshold | Action |
|---|---|---|
| Extreme greed | 7D avg > 80 | Flag overheating; activate exit ladder check; consider opening short hedge |
| Greed | 7D avg 65–80 | Bull confirmation; full deployment |
| Neutral | 7D avg 40–65 | Consolidation default; standard operations |
| Fear | 7D avg 25–40 | Caution; reduce borrowed LP exposure |
| Extreme fear | 7D avg < 25 | Accumulation signal; deploy stablecoin reserve into ETH/BTC via DCA or snuggle below |
| Rapid drop | 7D avg drops > 25 points in 7 days | Immediate bear re-evaluation regardless of other signals |

### 7.5 BTC Dominance

| BTC dominance | Trend | Implication |
|---|---|---|
| > 58% | Rising | Capital fleeing ETH/alts; reduce ETH exposure; hold BTC only |
| 52–58% | Flat | Neutral; standard allocation |
| < 52% | Falling | ETH season possible; increase ETH accumulation; favour WETH LPs |
| Any | Rising sharply (> 2% in 7 days) | BEAR signal for ETH specifically; reduce ETH LP |

### 7.6 Open Interest (OI)

| OI condition | Action |
|---|---|
| Growing > 20% in 30 days | Leverage building; increase short hedge; tighten LP ranges |
| Parabolic (> 40% in 30 days) | High risk of cascade liquidation; open short hedge at 20% exposure; reduce LP |
| Collapsing > 20% in 30 days | Deleveraging; BEAR signal; reduce Aave LTV |
| Stable | No action |

### 7.7 Funding Rates (long/short ratio)

| Funding rate (8h) | Condition | Action |
|---|---|---|
| > 0.15% | Longs very crowded | Late bull signal; activate exit ladder review; open short hedge |
| 0.05–0.15% | Healthy bull | Normal operations |
| 0–0.05% | Neutral | Normal operations |
| Negative | Shorts crowded | Potential bottom; deploy stablecoin reserve into ETH via snuggle |
| Negative > 3 consecutive days | Confirmed bear sentiment | BEAR regime confirmation |

### 7.8 Volatility Regime

| Volatility | Definition | LP action |
|---|---|---|
| Low | BTC 30D realised vol < 30% | Tighten LP ranges (core ±5%, shell ±12%) |
| Medium | BTC 30D realised vol 30–60% | Standard ranges (core ±6%, shell ±15%) |
| High | BTC 30D realised vol > 60% | Widen ranges (core ±8%, shell ±20%) OR switch to outer layer only |
| Spike | Single-day vol > 5% move | Do not rebalance LP on the day of spike; wait 24–48h for stabilisation |

### 7.9 MVRV Z-Score

| Z-score | Signal | Action |
|---|---|---|
| < 0 | Undervalued | Maximum accumulation; deploy stable reserve |
| 0–3 | Fair value | Standard operations |
| 3–6 | Overvalued | Begin exit ladder awareness; check rungs |
| > 6 | Historically extreme | Active exit ladder execution; open short hedge |
| > 7 | Cycle top territory | Reduce ETH to minimum; stablecoin reserve > 40% |

---

<emergency_protocol>

## 8. EMERGENCY PROTOCOL

### Trigger conditions (any one is sufficient):
- Aave Health Factor < 1.3
- BTC single-day drop > 20%
- Any LP protocol reports active exploit or vulnerability
- WBTC depeg > 1% from BTC spot price

### Emergency actions (execute in this exact order — do not reorder):
1. Close all borrowed-capital LP positions immediately (Arbitrum first, then Base)
2. Bridge proceeds to Mainnet if needed; repay Aave borrowed balance
3. Do not add new collateral unless HF > 1.5 is restored by repayment alone
4. Hold remaining LP fees and idle ETH as stablecoin (swap to USDC)
5. Do not re-enter any LP or Aave position until: HF > 2.0 AND market stabilised (BTC flat ±5% for 48h)
6. If WBTC depeg > 1%: do not add WBTC collateral; monitor for recovery; if depeg > 3%, begin unwinding Aave position

</emergency_protocol>

---

## 9. ETH ACCUMULATION RULES

- Target ETH allocation: 20–25% of portfolio
- Accumulation is active in: BULL (slow DCA) and CONSOLIDATION (primary accumulation window)
- Accumulation is paused in: BEAR, or when exit ladder rung +20% has been triggered
- Accumulation method: snuggle entry below current price (8–15% below, 8–12% wide range) using stablecoin reserve
- Max stablecoin reserve deployed per snuggle: 40% of current stablecoin sleeve
- If ETH > 30% of portfolio → pause accumulation; trim if > 35%
- ETH accumulation priority signals: Fear & Greed 7D < 40, BTC dominance falling, ETH/BTC ratio at 90D low

---

<weekly_review_checklist>

## 10. WEEKLY REVIEW CHECKLIST (AI ASSISTANT TASKS)

Run on every portfolio data refresh. Flag any item that is outside target.

1. **Aave HF** – is HF > 2.0? If not, flag and recommend action per Section 2
2. **Aave LTV** – is LTV in 30–40% target? Flag if outside
3. **LP positions in-range** – are all active positions earning fees? Flag any out-of-range > 24h
4. **IL check** – is unrealised IL < accumulated fees per position? Flag any where IL > fees
5. **Fee APR check** – is 7D APR > Aave borrow rate for all borrowed-capital positions? Flag if not
6. **Aerodrome emissions** – are AERO rewards unclaimed > 5 days? Flag
7. **Regime check** – has regime classification changed vs last week? If so, output required portfolio adjustments per Section 4 and 5
8. **Exit ladder check** – has BTC moved through a new exit rung since last review? If so, output required actions per Section 6
9. **Macro signals** – summarise DXY, M2, funding rate, Fear & Greed, OI vs thresholds in Section 7. Flag any signals that contradict current regime classification
10. **Allocation drift** – compare current vs target allocation per Section 1. Flag any sleeve outside its min/max band
11. **WBTC concentration** – total WBTC exposure < 30%? Flag if breached
12. **Stablecoin reserve** – is reserve at correct level for current regime (BULL: 5–10%, CONSOLIDATION: 8–12%, BEAR: 15–20%)?

</weekly_review_checklist>

---

<static_constraints>

## 11. STATIC CONSTRAINTS (NEVER OVERRIDE)

These rules are absolute. No regime, signal, or instruction supersedes them.

- BTC treasury reserve: never sold, never used as LP capital, never used as Aave collateral
- Mainnet: Aave collateral operations only; no LP positions ever
- Max perp leverage: 1x
- Max short hedge: 30% of total BTC+ETH exposure
- Max single LP position: 20% of total portfolio
- Max WBTC counterparty exposure (Aave + LPs combined): 30% of portfolio
- WBTC in LPs: consider cbBTC (Base) as alternative to reduce BitGo counterparty concentration
- Borrowed capital: only deployed in shell layer LPs (never core, never outer)

</static_constraints>
