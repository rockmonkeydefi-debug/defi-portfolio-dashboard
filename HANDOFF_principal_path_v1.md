# HANDOFF — Principal-path damage v1 (scoped Sep 12)

Scoped in the Phase E v2 session-2 chat; baseline at scoping time main @ 3cd7484, 1023 tests.
This doc is the canonical carrier for the workstream. Implementation chats point here. House
rules apply in full: read-first step-1 before any change, file wins over spec, write paths
review-gated STOP-before-commit, no drive-by cleanup, instruction blocks per the standing
format, backend and frontend in separate commits.

## The gap (on record)

The advisor's verdict rule is fee-side only: 7d run-rate APR vs 2.0 x decay. It never sees
principal-path damage. Confirming case (Sep 10, live): the WETH/PONS book — all 4 positions
down 12–17% while PONS was +41% since open — each auto-rebalance crystallizes IL (buys back
near the top, sells low after the dump). Narrowest width (30%) lost most; the 80% width was
the only green one. A position can bleed principal faster than it earns fees and read HOLD
indefinitely. This is a correctness defect in the advisor's promise, not a missing nicety.

## Scope decisions (locked Sep 12, Glenn A/A/A + scope approval A)

- Primary purpose: fix misleading HOLDs via a detector on held positions. Measurement feeds
  the Russian Doll / width evaluation over time as a byproduct.
- Verdict stance: DISPLAY-ONLY this phase. No verdict changes. Verdict integration (see TRIM
  below) is explicitly deferred until an observed live hit-rate on the badge exists — same
  observe-then-rule sequence as the crash badge and the 2.0 multiplier.
- Own workstream, own doc (this file) — not a Phase E rider.

## v1 scope — measure and display

1. Path-damage badge (frontend, crash-badge pattern, display-only):
   - Fires when principal P/L <= a judgment-set threshold WHILE the volatile token trades at
     or above its open price — the WETH/PONS signature, where market beta cannot explain the
     loss. Deliberately asymmetric: when the token is below open, beta masks path damage and
     the badge stays silent (accepted limitation, recorded).
   - Starting threshold: -10% principal, judgment-set constant (tunable), named per the
     MAXFI_CRASH_BADGE_DROP_PCT precedent. Rationale: the PONS book sat at -12..-17% with the
     token +41%; -10% catches all four while staying clear of ordinary drawdown noise.
   - Tooltip carries the evidence: principal P/L % and token-vs-open %.
   - Badge renders nothing on missing/NULL inputs (crash-badge guard pattern).
2. Checklist content line (construction guidance, content-only edit, same implementation
   chat, frontend commit): tight ranges + frequent auto-rebalances on pump-prone tokens are
   the damage profile — default wider; widen-vs-close at rebalance time is human judgment.

## Step-1 questions for the implementation chat (answer before design lock)

1. Open-price provenance: distribution of open_token_price_usd_source (recorded / seeded /
   backfilled) across OPEN positions, and whether non-recorded opens are trustworthy enough
   to arm the badge. NULL open price => badge silent, always.
2. Input availability at render time: which payloads carry the four inputs — basis
   (initial_value_usd), current position value, current token price, open token price. The
   valuation payload's volatile_token block is believed to carry both prices (client-side
   computation expected, like the crash badge) — verify, don't assume.
3. Principal definition: does current_value_usd include uncollected fees? The badge must
   compare PRINCIPAL-only against basis — define the comparison precisely against what C1.1
   established (last_uncollected_usd is persisted separately at valuation time). [Unverified
   at scoping time — a step-1 finding.]
4. Composition storage (v2 feasibility, not needed for v1): is entry composition (token
   amounts at open) stored anywhere? Gates the LP-vs-HODL benchmark below.

## Recorded and deferred (do not build in v1)

- TRIM verdict: the named candidate follow-on verdict string — partial de-risk when path
  damage is confirmed while fees are still strong; reactive, non-predictive, coherent.
  Deferred until observed badge hit-rate. Adding it triggers the standing bundling rule:
  MX_VERDICT_STYLE and MX_VERDICT_RANK (two maps) must be fixed in the same session that
  introduces any new verdict string.
- Rebalance-frequency surfacing: C1.4 (02b169a) writes a set_by='system' claim per sweep, so
  per-position rebalance-event data accumulates forward regardless. Surfacing (count/recency
  in expanded panel or column) deferred.
- Principal-health columns (principal %/day, total-return %/day): context-only metrics,
  same status as lifetime run-rate; deferred.
- LP-vs-HODL benchmark: gold-standard metric; gated on step-1 Q4 (composition storage).
  Basis + open price under an assumed 50/50 split is a labeled APPROXIMATION if used.
- Closed-position post-mortem view: realized path damage on closes, feeding the Russian Doll
  and width evaluations; v2-shaped measurement infrastructure.
- Momentum/directional signal chips (Close/Trim–Hold–Wait with HOT/COOLING momentum
  multipliers, as seen in MaxFi's own pool-ranking UI): NOT adopted. The Sep 9 lock stands —
  verdicts stay purely reactive, no predictive/directional TA. Reopening that lock is a
  deliberate separate decision, never a rider on this workstream.

## Standing disciplines (restated, unchanged)

Autocompound OFF book-wide. New capital as $25–50 probes only; full size only as scale-up on
a measured probe. Russian Doll 2–3 layer cap, every layer counts fully against sizing caps.
Closes against one fresh advisor pull in one sitting; harvest claims first.

## v1 landed (Sep 12) — step-1 answers and design rulings of record

Step-1 (read-only, on 17bdcfd, verified independently in chat against main):
- Q1: 'recorded' only when valuation ran within 1h of first_seen_at; else 'seeded'
  (live price at an arbitrary later cycle — not a true open); 'backfilled' = real GT
  hour-candle, upgrades 'seeded' rows only. Provenance distribution is per-wallet
  only (valuation route); no all-wallets surface.
- Q2: all four inputs already client-side (position.initial_value_usd,
  valuation.current_value_usd, volatile_token.current_price_usd/.open_price_usd —
  the last previously read by zero frontend files). No backend change needed.
- Q3: current_value_usd is principal-only (liquidity_to_amounts composition;
  uncollected_usd computed/persisted independently). Comparison is
  current_value_usd / initial_value_usd - 1, nothing subtracted.
- Q4: no entry composition stored anywhere — LP-vs-HODL benchmark stays gated on a
  new capture path or the labeled 50/50 approximation.

Design rulings (Glenn, C/A/A/A):
- Seeded open prices: badge arms on ALL sources; tooltip appends "open price seeded
  (approx)" on seeded rows. Operational companion: drain the seeded worklist via the
  existing backfill route (re-fire per chain until deferred=0) — badge quality
  improves as rows upgrade to 'backfilled'; no code dependency either way.
- Principal input: valuation.current_value_usd (snapshot-consistent with the token
  price in the same payload), not persisted last_value_usd.
- Color: violet #c084fc, fifth distinct color in the Pool cell.
- Single frontend commit: maxfi.js badge + checklist construction line + this append.

As landed: MAXFI_PATH_DAMAGE_PRINCIPAL_DROP_PCT = 10 (judgment-set, tunable). Fires
when principal drop >= 10% AND live volatile price >= open price; silent below open
(asymmetry accepted on record) and on any missing input. Label "path -N%"; tooltip
carries principal % vs basis + token % vs open. Display-only — no verdict change;
TRIM remains deferred per the scope section above.
