# LP Advisor — C1.2 (accrual-reset fix) and Phase D (held-grid frontend)

## C1.2 — Rebalance resets the accrual clock (REVIEW-GATED, do first)
- Finding (Sep 10, live): an in-place rebalance issues a NEW NFT
  token_id and resets on-chain uncollected fees to ~0, while the
  advisor's accrual window (days since last claim, else days since
  open) still spans the position's full life. Near-zero earnings over
  a full window -> near-zero run-rate -> false CLOSE. Same failure
  class as C1.1's gap, new cause.
- Live artifacts: WETH/MSTR x3 (token_ids 1099843, 1100004, 1100387;
  replaced 953278/953500/953535) and WETH/PENGU (1107725; replaced
  973015), all on wallet 0x8fc4...31ee. Their CLOSE verdicts are
  treated as known-false until this fix lands.
- Locked fix direction (Glenn, Sep 10): accrual anchor becomes
  max(last claim time, last rebalance/re-mint time). The session's
  step-1 read-only review must locate where the scan path records a
  rebalance/new-token_id event (maxfi_orchestration) and what
  timestamp is available to anchor on; if no usable rebalance
  timestamp exists, that is a finding to surface with options, not a
  license to invent one.
- Constraints: REVIEW-GATED session. Standard step-1 read-only review
  first. Instruction blocks end at the summary - NO commit step;
  manual approval by Glenn only. maxfi_pricing valuation math
  untouched. No drive-by cleanup.
- Verification plan: after landing plus a valuation refresh, the 4
  artifact positions re-verdict on a post-rebalance window; a
  rebalanced position with genuinely strong fees should read HOLD.

## C1.3 candidate (confirmed premise)
- Confirmed during C1.2 commit 2/2's review: auto-split arriving rows
  (resolve_ambiguous_auto_splits, via decide_ambiguity_resolution)
  inherit first_seen_at - the EARLIER of the two departing positions'
  first_seen_at values, source ambiguity_auto_split_inherited - while
  being fresh mints whose uncollected fees are reset. Same false-CLOSE
  accrual artifact as the C1.2 rebalance case, different trigger.
- Unlike a plain rebalance, this path already writes maxfi_position_
  lineage (departing_position_id, arriving_position_id, created_at) for
  every arriving row, so the timestamp data a fix would need is already
  captured - this is a smaller lift than C1.2 was.
- Out of scope for C1.2 by decision. Left as a candidate for a future
  session.

## Phase D — held-grid frontend (after C1.2)
- Scope: render GET /api/maxfi/advisor verdicts in the MaxFi tab
  (held-position grid), replacing raw-JSON eyeballs. Frontend-only
  consumption of the existing route; no schema or route changes
  expected. static/*.js layout, no build step - Babel parse + NUL
  check is the frontend gate.
- Must respect Glenn's UI/UX visibility standards (contrast, font
  minimums, separator visibility) already used across the app.
- Do NOT ship Phase E features here (no Action Plan, no pool scout).

## Phase E backlog (parked, in one list)
- Verdict stabilizer: 7d trend from last COMPLETED daily candle,
  and/or CLOSE must persist across two consecutive snapshots before
  surfacing (Sep 10 finding: same-day token-daily runs flipped ~9
  verdicts in 15 minutes).
- De-minimis decay floor (near-flat tokens hair-trigger the strict
  rule).
- Liquidity floor as a display/sort decision on entry candidates.
- Entry-gate caveat: both-windows-negative definition passes
  pumped-then-dumping tokens (e.g. AI passing at -21.7% 7d on a
  +2245% 30d); contained operationally by the $25-50 probe rule.
- Action Plan feature per the Phase B strategy addendum (close
  verdicts -> freed capital -> probe candidates -> dry-powder
  remainder; new capital always phrased as $25-50 probes).

## Session decisions on record (Sep 10, for context - do not reopen)
- Close-list discipline: Bucket A = positions whose 7d run-rate is
  below the token's RAW 1x decay (16 positions at last pull); Bucket
  B = between 1x and 2x (held as the tracked flagged-vs-resolved
  cohort that later tunes the 2.0 multiplier). Execution deferred to
  a fresh advisor pull after the day's candle completes - no closes
  on a partial-candle snapshot.
- Russian Doll layers are evaluated as a unit per the Sep 9 interim
  rule; wide layers are not re-ranged tighter mid-dump. Optional
  structure-preserving move noted for the AI doll: close 949312 (the
  only layer earning below 1x decay) and open a NEW tight layer at
  current price - an add, not a rebalance, so no C1.2 artifact.
- Rebalancing/re-ranging a position resets its uncollected clock and
  (until C1.2) makes its verdict a known-false artifact - factor this
  into any re-range recommendation the advisor UI ever makes.

## Landing SHAs to date (LP Advisor workstream)
- B1 edaa051 (PR #116) · B2 87edac2 (PR #117) · B3 7873985 (PR #118)
- B1.1 soft-decode b705659 (PR #119)
- C1 advisor module + route c7aad75 (PR #120)
- C1 timezone hotfix (parse_utc) fb23984 (PR #121)
- C1.1 schema b51e651 (PR #123) · C1.1 write-path/route 53630ef
  (PR #124)

## Unchanged context
- Verdict rule and constants unchanged: 7d run-rate vs 2.0 x decay,
  decay clamped at 0, min_days_open 3.0, lifetime run-rate
  context-only. Autocompound OFF book-wide. Verdicts purely reactive,
  no predictive TA.
- Routine ops: once-daily token-daily invocation per chain (browser
  console POST), catalogue/metrics refresh as needed; scheduling
  deliberately unbuilt.
- Known open item outside this doc's scope: second wallet
  0xaB7A...6743 valuation staleness (rows still on Sep 9 timestamps;
  needs a wallet-selector valuation run; its 3 positions excluded
  from close actions until refreshed).
