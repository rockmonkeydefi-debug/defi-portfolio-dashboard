# C1.1 — Persist uncollected fees for the LP Advisor (REVIEW-GATED)

## Why
- GET /api/maxfi/advisor is live and mathematically verified, but it
  counts uncollected fees as $0 (flag "uncollected_unavailable").
- Live eyeball (Sep 9): 14 of ~15 CLOSE verdicts showed
  window_earned_usd = 0.0 while same-pool sibling positions with claims
  held comfortably. Glenn confirmed all 14 are open and never claimed —
  100% of their earnings are uncollected on-chain fees, invisible to the
  verdict. The CLOSE flags are earnings-gap noise, not decay signal.

## Decided architecture (Glenn, Sep 9 — do not reopen)
- Option B: persist the uncollected-fees USD figure at valuation time.
- Add column `last_uncollected_usd REAL` (nullable) to `maxfi_positions`,
  following the established additive-migration pattern in
  maxfi_schema.py / ensure_maxfi_tables.
- Write it at the exact code point where the existing valuation path
  writes `last_value_usd` — the number is already computed in a local
  variable there; it is currently discarded. Same write moment =
  snapshot-consistent with `last_value_usd` / `last_value_at`
  (that consistency is the reason Option B won over live RPC reads).
- The advisor route then reads `last_uncollected_usd` instead of
  hardcoding 0.0, passes it as `uncollected_usd` with
  `uncollected_accrual_days` = days since last claim (or days since
  open if never claimed — the route already computes this).
- Flag behavior: keep "uncollected_unavailable" ONLY when the column is
  NULL (row not yet re-valued since the migration); drop it once a real
  value is present, including a real 0.0.
- Rejected alternatives, for the record: live extraction from the
  valuation route (mixes fresh uncollected with stale value; adds RPC
  latency to a pure-read route); advisor-side on-chain reads (a second
  valuation path — forbidden).

## Constraints for the C1.1 session
- REVIEW-GATED: schema migration + an edit inside the live valuation
  write path (money path). The instruction block must end at the
  summary — NO commit step. Manual commit approval by Glenn only.
- Standard step-1 read-only codebase review first: locate by name the
  valuation write site, the migration pattern, and the advisor route's
  uncollected stub before proposing the block.
- No behavior change to valuation math itself — persist an
  already-computed number, nothing more.
- maxfi_advisor.py (the pure module) should need zero changes; if the
  session concludes otherwise, that's a finding to surface, not to fix
  silently.

## Verification plan after landing
- Trigger a valuation refresh so the column populates, then re-eyeball
  GET /api/maxfi/advisor.
- Expected: the 14 previously-flagged positions re-verdict on real
  uncollected earnings; remaining CLOSEs (if any) are then signal.
  The two thin-margin AI CLOSEs (token_ids 949271, 955454; margins
  −0.67 / −0.30 %/day) are the sensitivity check — real uncollected
  plausibly flips both.

## Landing SHAs to date (LP Advisor workstream)
- B1 edaa051 (PR #116) · B2 87edac2 (PR #117) · B3 7873985 (PR #118)
- B1.1 soft-decode b705659 (PR #119)
- C1 advisor module + route c7aad75 (PR #120)
- C1 timezone hotfix (parse_utc) fb23984 (PR #121)

## Unchanged context
- Verdict rule and constants unchanged: 7d run-rate vs 2.0 × decay,
  decay clamped at 0, min_days_open 3.0, lifetime run-rate context-only.
- Open in parallel, not part of C1.1: base + robinhood token-daily runs
  (entry gates null until done); possible future de-minimis decay floor
  (noted only); entry-score liquidity floor (Phase E display decision).
