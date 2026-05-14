# Strategy Playbook Guide

A practical guide to writing the **Strategy Playbook** that the AI Advisor uses to assess your portfolio and generate recommendations.

---

## What is the playbook?

The playbook is a free-text document you write that tells the AI:

- What your portfolio is supposed to look like (allocation targets, hard limits)
- How you classify the market (bull / bear / consolidation criteria)
- What rules you follow per protocol (Aave LTV bands, LP range widths, hedging limits)
- What you never do (static constraints)
- What triggers an emergency action

It lives in **Settings → AI Advisor Configuration → Strategy Playbook and Custom Instructions**. The system stores it under `data/ai_config.json` and prepends it to every AI report request as the user message section `## STRATEGY PLAYBOOK AND CUSTOM INSTRUCTIONS`.

The base system prompt explicitly instructs the LLM to:

- **Step 5 (Capital Budget & Candidates)** — compare current allocation to your playbook for the identified regime; source funds from idle / over-allocated sleeves before suggesting new borrows.
- **Step 7 (Validation)** — check the projected portfolio against playbook targets and flag any violations.
- Fall back to its own judgment if a topic isn't addressed.

The more concretely you write the playbook, the more the AI's recommendations will look like they came from you instead of a generic advisor.

---

## How specific should you be?

Specific enough that two different LLM runs would reach the same conclusion. Vague rules ("hold some stables for safety") produce vague recommendations. Quantified rules ("stablecoin reserve target 8%, flag if < 4%") produce actionable ones.

Rule of thumb: if a rule has a number, name it. If it has a threshold, name it. If it's qualitative ("only LP on majors"), say so explicitly so the AI doesn't infer otherwise.

---

## Recommended structure

You don't have to follow this exactly — but the AI parses any structure better when sections are clearly delimited and each rule is on its own line. The sections below are the ones that pay off most for AI-driven analysis.

### 1. Portfolio composition targets

State, by sleeve, the **min / target / max** percentages. Bands matter more than point targets — the AI uses them to tell whether a sleeve is genuinely off-target or just drifting.

> **Example — from a BTC/ETH-focused playbook:**
> ```
> | Sleeve | Min | Target | Max |
> |---|---|---|---|
> | BTC treasury reserve            | 20% | 25% | 30% |
> | WBTC / cbBTC on Aave (collat.)  | 17% | 20% | 27% |
> | ETH / WETH (idle + accumulate)  | 15% | 25% | 35% |
> | Active LP positions             | 15% | 22% | 30% |
> | Stablecoin reserve              |  5% |  8% | 20% |
> ```

### 2. Hard limits — flag immediately if breached

These become candidates for `risk_alerts` in the report. Keep them quantified.

> **Example:**
> ```
> - BTC treasury reserve < 15%        → FLAG: treasury underfunded
> - Total WBTC exposure > 30%         → FLAG: counterparty concentration
> - ETH allocation > 35%              → FLAG: ETH overweight, trim
> - Stablecoin reserve < 4%           → FLAG: no dry powder
> - Single LP position > 20% of total → FLAG: LP concentration risk
> - LP capital from borrowed funds > 15% of total → FLAG: leverage overextended
> - Any LP position out-of-range > 72h → FLAG: dead position, zero fees
> ```

### 3. Market regime classification

The AI computes its own bull/bear/sideways probabilities, but if you have a personal definition of regime, write it down. The AI will adopt it.

> **Example — bull regime requires ALL of:**
> ```
> - BTC price > BTC 200D MA
> - BTC dominance stable or declining (< 0.5% weekly) OR ETH/BTC ratio rising
> - Fear & Greed 7D average > 55
> - BTC funding rate: positive but < 0.08% per 8h
> - OI growing but not parabolic (< 30% monthly growth)
> - M2 money supply: flat or expanding
> - DXY: flat or declining (< 103)
> ```
>
> **Bear regime requires ANY TWO of:**
> ```
> - BTC price < BTC 200D MA on weekly close
> - Fear & Greed 7D average < 30
> - BTC funding rate: negative or zero for 5+ days
> - OI collapsing (> 20% monthly decline)
> - DXY rising sharply (> 105 and trending up)
> - M2 contracting
> - BTC dominance > 58% and rising
> ```

If you have **regime change triggers** that fire mid-period, list them too:

> ```
> - Funding rate spikes > 0.15%/8h for 3+ days → late-bull / overheated
> - Funding rate goes negative for 3+ days → bear confirmation
> - Fear & Greed drops > 25 points in 7 days → bear re-evaluation
> ```

### 4. Per-protocol rules

For each protocol you use, give the AI bands and decision rules. **Aave** is the highest-leverage example, so it deserves the most detail.

> **Example — Aave LTV / health-factor bands:**
> ```
> | Zone          | LTV    | HF        | Status                          |
> |---------------|--------|-----------|---------------------------------|
> | Underutilised | 0–28%  | > 4.0     | Consider deploying more         |
> | Green         | 28–35% | 2.5–4.0   | Normal operations               |
> | Target        | 35–40% | 2.0–2.5   | Optimal                         |
> | Caution       | 40–50% | 1.5–2.0   | Stop new deployments            |
> | Danger        | 50–60% | 1.2–1.5   | Repay or add collateral in 48h  |
> | Emergency     | > 60%  | < 1.2     | Immediate action: pull LP, repay|
> ```
>
> **Decision rules:**
> ```
> - LTV < 28% AND regime = BULL → suggest more WBTC collateral
> - LTV > 42% → halt all new LP deployments regardless of regime
> - LTV > 50% → close lowest-APR LP, use proceeds to repay
> - Aave WBTC borrow rate > LP fee APR (7D) + 2% → close LP, repay
> ```

### 5. LP strategy rules

If you run a layered LP structure (core / shell / outer ranges), put the layer definitions and rebalance triggers here.

> **Example:**
> ```
> | Layer | Range width | Capital % | Borrowed | Rebalance trigger    |
> |-------|-------------|-----------|----------|----------------------|
> | Core  | ±5–8%       | 35–40%    | No       | Price exits range    |
> | Shell | ±12–18%     | 30–35%    | Yes      | APR drop > 40% / 3wk |
> | Outer | ±25–40%     | 20–25%    | No       | Monthly or full exit |
> ```
>
> **Fee-APR thresholds:**
> ```
> - LP fee APR (7D) < 8% annualised        → flag underperforming
> - LP fee APR (7D) < Aave borrow rate     → mandatory review
> - LP fee APR (7D) drops > 50% from entry → re-evaluate range or pool
> ```

If your range widths or layer sizing depend on regime or volatility, list those too:

> ```
> - In BULL: shell ±15–18%, core ±6%
> - In CONSOLIDATION: shell ±8–12%, core ±5%  (tighter for fee density)
> - In BEAR: outer layer only, no borrowed capital
> - Vol < 30%: tighten ranges. Vol > 60%: widen or outer-only.
> ```

### 6. Hedging rules

If you hedge LP delta or downside, write the trigger conditions explicitly. Mention max leverage, funding-cost limits, and when to drop the hedge.

> **Example — perp short hedge for downside protection:**
> ```
> | Trigger                          | Action                         |
> |----------------------------------|--------------------------------|
> | BTC +40% in 60d AND HF < 2.5     | Open short = 20% of WBTC value |
> | HF < 2.0                         | Open short = 25% of WBTC value |
> | Funding > 0.15%/8h for 3+ days   | Reduce or close long hedge     |
> | MVRV Z-score > 6                 | Open short = 25% of BTC+ETH    |
> | BTC -20% from hedge entry        | Take profit, close hedge       |
>
> Max short hedge: 30% of total BTC+ETH exposure.
> Never hedge > 30% in bull (caps upside unacceptably).
> ```

### 7. Exit ladder (DCA-out)

If you scale out at fixed price levels, name them. The AI will check whether a new rung has been triggered since the last report and recommend the matching action.

> **Example — measured from BTC cycle entry:**
> ```
> | BTC move | Action                                                        |
> |----------|---------------------------------------------------------------|
> | +20%     | Close core LP. Convert 50% freed capital to stables.          |
> | +40%     | Sell 20% of ETH. Close borrowed-capital LPs. Repay Aave to LTV 28%. |
> | +60%     | Sell 30% remaining ETH. Stables target 20–25%. Open BTC short 15–20%. |
> | +80%     | Close all LPs. Sell 40% remaining ETH. Stables 30–35%.        |
> | +100%    | ETH to 5% of portfolio. Stables > 40%. Watch cycle-top signals.|
> ```
>
> **What's never sold:**
> ```
> - BTC treasury reserve: never sold at any rung
> - Reduced only by 3+ independent cycle-top indicators simultaneously
> ```

### 8. Macro signal integration

You don't need to list every metric — the AI already has DXY, M2, Fed funds, Fear & Greed, OI, funding, BTC dominance, MVRV in its context. List only the **thresholds and actions you care about**, otherwise the AI applies textbook readings.

> **Example — DXY:**
> ```
> | DXY level / trend | Implication                                  |
> |-------------------|----------------------------------------------|
> | < 100, falling    | Risk-on; deploy LP capital fully             |
> | 100–103, flat     | Neutral                                      |
> | 103–106, rising   | Caution; reduce LP; build stable reserve     |
> | > 106, rising     | Risk-off; treat as BEAR; increase hedge      |
> ```

Apply the same treatment to whichever signals matter to your strategy: M2 trend, funding rate bands, OI growth, Fear & Greed thresholds, MVRV Z-score, etc.

### 9. Static constraints — never override

The shortest, most important section. List rules that hold regardless of regime, market state, or AI judgment.

> **Example:**
> ```
> - BTC treasury reserve: never sold, never used as LP capital, never as Aave collateral
> - Mainnet: Aave only; no LPs (gas destroys returns at this size)
> - Max perp leverage: 1x
> - Max short hedge: 30% of total BTC+ETH
> - Max single LP position: 20% of portfolio
> - Max WBTC counterparty exposure (Aave + LPs combined): 30% of portfolio
> - Borrowed capital: only in shell-layer LPs, never core, never outer
> ```

### 10. Emergency protocol

What triggers it, and the exact unwind sequence. The AI will produce these as `risk_alerts` with `severity: critical` if a trigger is active.

> **Example:**
> ```
> Triggers (any one):
> - Aave HF < 1.3
> - BTC single-day drop > 20%
> - Any LP protocol reports active exploit
> - WBTC depeg > 1% from BTC spot
>
> Actions, in order:
> 1. Close all borrowed-capital LPs (Arbitrum first, then Base)
> 2. Bridge to Mainnet, repay Aave borrowed balance
> 3. Do not add new collateral until HF > 1.5 from repayment alone
> 4. Hold remaining LP fees as USDC
> 5. No re-entry until HF > 2.0 AND BTC flat ±5% for 48h
> ```

### 11. Weekly review checklist (optional)

If you want the AI to systematically check certain things every report, list them as a numbered checklist. The AI will run through them and surface flags.

> **Example items:**
> ```
> 1. Aave HF > 2.0?
> 2. Aave LTV in 30–40% target?
> 3. All LPs in-range and earning fees?
> 4. Per position: unrealised IL < accumulated fees?
> 5. Per borrowed-capital LP: 7D APR > Aave borrow rate?
> 6. AERO rewards unclaimed > 5 days?
> 7. Regime classification changed vs last week?
> 8. Has BTC moved through a new exit-ladder rung?
> 9. Any sleeve outside its min/max band?
> ```

---

## Minimal skeleton

If the structure above is too much, this is the smallest playbook that still gives the AI useful guidance:

```markdown
## Portfolio
- 25% BTC treasury (cold, never deployed)
- 20% WBTC on Aave as collateral
- 25% ETH (idle + LP fuel)
- 22% LP positions
- 8% stablecoin reserve

## Hard limits
- Aave LTV must stay < 50%; target 35-40%
- No LP position > 20% of portfolio
- BTC treasury never sold
- Max perp leverage: 1x

## Regime
- Bull: BTC > 200D MA, F&G > 55, funding 0–0.08%/8h
- Bear: BTC < 200D MA OR F&G < 30 OR funding negative 5+ days
- Otherwise: consolidation

## Per-regime LP behaviour
- Bull: shell ±15%, core ±6%, borrowed capital allowed in shell
- Consolidation: shell ±10%, core ±5%
- Bear: outer layer only, no borrowed capital

## Exit ladder (BTC from cycle entry)
- +20%: close core LP, 50% to stables
- +40%: sell 20% ETH, repay Aave to LTV 28%
- +60%: open BTC short hedge 15–20%, stables to 25%
- +80%: close all LPs, stables to 35%

## Emergency: HF < 1.3 OR BTC -20% in a day OR LP exploit
- Close borrowed-capital LPs first
- Repay Aave to HF > 1.5
- All idle to USDC until BTC stable 48h
```

---

## Tips for writing yours

- **Use tables for bands, numbered lists for sequences.** Markdown tables are parsed reliably; bullet lists less so.
- **Quantify or omit.** A vague rule is worse than no rule — the AI will infer it loosely. "Reduce ETH if overheated" is unhelpful; "If MVRV Z > 6, sell 30% of ETH" is actionable.
- **Name the regime in the rule.** "In bull, prefer ±15% ranges" beats "prefer wider ranges when trending up", because the AI is already reasoning about regime probabilities.
- **Order matters for triggers.** If you have priority ("Aave HF first, then LP APR check"), say so.
- **Mention what you don't do.** "Never LP on Mainnet" / "Never short ETH while BTC is bullish" / "Borrowed capital never enters the core layer" — these are easy to omit but exactly the kind of constraint the AI would otherwise violate.
- **Update the date at the top.** When you change the strategy, bump a `Last updated: YYYY-MM` line so old AI reports stay traceable to the playbook version that generated them.

---

## Common pitfalls

- **Conflicting rules.** "Never sell BTC" + "At +100% sell BTC down to 5%" — the AI will pick one and look inconsistent. Resolve conflicts in writing.
- **Implicit knowledge.** "Use the snuggle method" — fine for you, but the AI doesn't know what your snuggles look like unless you define them. If the term isn't industry-standard, define it inline.
- **Stale numbers.** A playbook written when ETH was $1,800 with absolute price targets gets weird at $4,500. Prefer thresholds expressed as % from 200D MA, % from cycle entry, or relative to other portfolio sleeves.
- **Over-specifying tactics, under-specifying intent.** The AI is better at "rebalance shell layer if APR drops 40%" than at "use this exact tick range on this exact pool". Pool-specific tactics rot fast; rules of behaviour don't.
- **No fall-through case.** If your bull and bear definitions don't cover everything in between, define the default explicitly (e.g., "consolidation = anything not bull or bear").

---

## How the AI uses your playbook (quick reference)

| AI step | What the playbook drives |
|---|---|
| Step 1 — Regime assessment | Adopts your regime definitions if provided; otherwise uses textbook signals. |
| Step 3 — Portfolio assessment | Compares actual sleeves against your targets; surfaces drift in `concerns`. |
| Step 4 — Risk alerts | Quantified hard-limit breaches surface here with `severity` levels. |
| Step 5 — Capital budget & candidates | Identifies under/over-allocated sleeves vs your targets and routes idle capital before suggesting new borrows. |
| Step 6 — Projected portfolio | Models the sleeves as your playbook defines them. |
| Step 7 — Validation | Checks projected state against your targets, max LTV, and any explicit limits you wrote. |

If you only write one section, write **portfolio composition targets + hard limits**. That alone makes Step 3, Step 4, Step 5, and Step 7 dramatically more useful.
