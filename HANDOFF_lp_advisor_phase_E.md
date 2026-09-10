# LP Advisor — Phase E scope (locked Sep 10)

This doc is the scope lock for Phase E, produced in a scoping-only session
(no code, no instruction blocks) after C1.3 landed (3370ca5, 944 tests) and
Phase D (held-grid verdict columns) shipped. It records WHAT is in v1 vs v2
and WHY, plus design notes captured during scoping so implementation
sessions don't have to re-derive them. It does not itself implement
anything. Reference HANDOFF_lp_advisor_C1_2_and_phase_D.md for prior
history (C1.x landing SHAs, Phase D status, unchanged-context constants) -
not repeated here except where v2 builds directly on it.

## v1 (locked)

In priority order. Each is its own implementation session unless noted.

1. **Verdict stabilizer — candle-half only.** Single computation on the
   last COMPLETED daily candle (not the in-progress one), addressing the
   Sep 10 finding of ~9 verdicts flipping in 15 minutes on same-day
   token-daily runs. The 2-consecutive-snapshot persistence half of the
   original stabilizer idea is OUT of v1 - see v2 item below.
   - Design note from scoping: `maxfi_advisor.advise_position()` is a pure
     function over (claims, uncollected, daily_rows, as_of_utc), and
     maxfi_token_daily already retains multi-day history per token. The
     candle-half needs no new table and no new write path - it's a
     route-side choice of which as_of_utc/daily_rows to feed in.
   - Young-token edge case (confirmed during scoping): a token with no
     completed candle yet stays on the EXISTING null-gate / insufficient_data
     path. No synthetic candle, no invented value.

2. **De-minimis decay floor.** Near-flat tokens hair-trigger the strict
   verdict inequality today. Threshold is JUDGMENT-SET at implementation
   time, then tuned later against observed data - same treatment as the
   2x close multiplier got (see "Bucket A/B derivation discipline" below).
   Not derived up front from a formula.

3. **Liquidity display floor + entry-gate fix** — combine into one session
   if both land in the same entry_score/downtrend_gate path (confirmed
   during scoping: both are pure-module logic already touching that path).
   - Liquidity floor: tiny-liquidity pools inflate entry scores today;
     needs a display/sort floor on entry candidates.
   - Entry-gate fix: both-windows-negative definition currently passes
     pumped-then-dumping tokens (e.g. AI passed at -21.7% 7d on +2245%
     30d). Operationally contained today only by the $25-50 probe rule -
     this closes the gap in the gate itself.

4. **Pool scout frontend.** Surfaces the catalogue's entry candidates.
   Confirmed during scoping: GET /api/maxfi/advisor already computes and
   returns `entry_candidates` in full (entry_score, fee_apr_est_pct,
   downtrend_gate, volume_mult, liquidity_usd, all present) - this is a
   frontend-only consumption task, same shape as Phase D was for verdicts.
   No backend/route change expected.

### Explicitly NOT in v1 (moved from the original candidate list)

- **Action Plan** (close verdicts -> freed capital -> probe candidates ->
  dry-powder remainder) - v2. Would otherwise be built on unstabilized
  verdicts and unfloored/ungated entry candidates; sequencing it after v1
  avoids a guaranteed rebuild.
- **Flagged-vs-resolved tracking for the 2x multiplier** - stays MANUAL
  (by hand), no write path in v1. The clock-start concern (every day
  without tracking is a day of Bucket-B outcomes lost) is addressed by the
  manual log itself capturing outcomes as they happen.
- **S-class ATH suppression + weekend-delay handling** - v2, and
  preconditioned on confirming S-class is actually populated after the
  pending Class editor pass. No bundled v1 session for these.
- **Claim-age alert** - backlog, not v2. Scoping found the original
  "requires a route change" blocker is now a one-line exposure
  (last_claim_at is already computed inside api_maxfi_advisor for the
  accrual anchor, just never added to the response dict) - but it was
  deprioritized on VALUE, not cost: C1.1-C1.3 already solved the
  motivating problem (false-CLOSE from stale accrual anchors). The reduced
  cost does not restore its priority.

## v2 (locked, not yet ordered within itself)

- **Action Plan.** Independent surface from pool scout - both read
  entry_candidates directly, no hard ordering dependency between them.
  Action Plan's own consumption question (does it embed pool-scout-style
  ranking, or just read the raw candidates) is decided when v2 starts, not
  here.
- **Refresh scheduler (item 9).** PAIRED with Action Plan - lands with or
  before it. This is a locked correction to the prior doc's framing:
  catalogue/metrics/token-daily cadence is NOT "deliberately unbuilt"
  going forward and NOT indefinitely parked; it has a landing point now.
- **Stabilizer, snapshot-persistence half.** The "CLOSE must persist across
  two consecutive snapshots" mechanism from the original candidate,
  triggered ONLY if observation after the v1 candle-half ships shows
  day-over-day churn persists. Preferred design (recorded from scoping,
  not yet decided as final): recompute route-side by calling
  advise_position twice with as_of_utc shifted back one day each,
  reusing maxfi_token_daily's existing multi-day history - no new table.
- **S-class ATH suppression + weekend-delay handling** (see v1 section for
  the precondition).
- **Flagged-vs-resolved analysis/UI** - only relevant once there's a
  manual log worth analyzing; no write path is being built for this in
  either v1 or v2.
- **MX_VERDICT_STYLE / MX_VERDICT_RANK gap.** Both constants cover
  CLOSE/HOLD only (confirmed identical gap in both during scoping - the
  original candidate list only named MX_VERDICT_STYLE). Bundle the fix
  into whichever v2 item is the first to introduce a new verdict string -
  don't fix preemptively since v1 introduces none.

## Backlog (unscoped, no phase assigned)

- **Principal-path damage is invisible to the fee-side rule.** New finding
  from live session data on the day of scoping: the WETH/PONS book lost
  12-17% in principal value while its fee-side run-rate-vs-decay verdict
  looked fine throughout. The advisor's verdict rule only ever measured
  fee accrual against token decay - it has no notion of principal
  drawdown at all. Unscoped; a Phase E+ discussion, not assigned to v1 or
  v2 here.

## C1.4 candidate (own fresh chat, NOT Phase E)

Explicitly out of this doc's scope, recorded here only so it isn't lost:
rebalance/auto-split sweeps send unclaimed rewards to the wallet with no
corresponding maxfi_claims row being written. Candidate fix: a
provenance-labeled ESTIMATED claim, written by the REBALANCED branch, using
the old row's last_uncollected_usd as the estimate. This is a write-path
change to the claims/rebalance machinery, not an advisor-route change - it
belongs in its own review-gated session, separate from Phase E's
route/frontend work.

## Carried forward from the C1_2_and_phase_D doc (referenced, not restated)

Two disciplines from that doc's "Session decisions on record" section that
v2's Action Plan builds directly on - see that doc for the full text:
- **Probe rule**: new capital is always phrased as $25-50 probes; full
  size only ships as "scale-up eligible" on an already-measured probe.
- **Bucket A/B derivation discipline**: Bucket A = 7d run-rate below the
  token's RAW 1x decay; Bucket B = between 1x and 2x, held as the tracked
  cohort that eventually tunes the 2.0x multiplier. Execution deferred to
  a fresh advisor pull after the day's candle completes - no closes on a
  partial-candle snapshot. (This is the same discipline the de-minimis
  floor threshold above will eventually be tuned against.)

Everything else on record in that doc (verdict rule constants, Russian
Doll layer handling, landing SHAs, wallet-staleness caveat) is unchanged
and not repeated here.

## Note on live counts

No point-in-time position/bucket counts are recorded in this doc. Scoping
session found counts go stale within a day (Bucket A moved 16->23
overnight during this same session) - a number written here would be
wrong before the first v1 implementation session starts. This doc records
disciplines and derivation methods (above), not counts; each implementation
session pulls its own fresh numbers.
