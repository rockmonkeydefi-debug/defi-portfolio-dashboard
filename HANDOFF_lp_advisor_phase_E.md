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
   - **Status (implemented, review-gated, session 1 step 2):** seam decision
     is a route-local filter on daily_rows at the position loop's own
     lookup site in api_maxfi_advisor - `as_of_utc` itself is never shifted,
     so days_open and the claims window are unaffected. The shared
     token_daily_by_key dict is not mutated, and the entry-candidates loop's
     own daily_rows lookup / downtrend_gate call is untouched by design -
     entry candidates deliberately still see today's partial candle. The
     happy-path route test's token-daily fixture was moved from
     (today-7, today) to (today-8, today-1): with today's row present, that
     fixture's two points collapsed onto the same date once filtered
     (today's the row that would have been dropped), which would have
     silently stopped exercising a real 7-day trend even though its loose
     assertions kept passing - moved forward to two genuinely completed
     candles instead. (An initial pass landed (today-14, today-7), which
     turned out to be equally degenerate - price_change_pct's base search
     targets as_of-7 = today-7 directly, so those two dates collapse onto
     the same row once as_of=today; corrected to (today-8, today-1), which
     keeps latest and base on two different rows.) Convention note:
     "completed" is defined as
     date < today (UTC) - maxfi_token_daily's schema carries no completeness
     marker of its own (see maxfi_schema.py), so this is the only definition
     available. 5 new tests added; 949 total.

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

## v2 session 1 landings (Sep 12)

Three commits, in order, closing out v2's first implementation session.

- **C1 `c908195`** - advisor settings file (ADVISOR_SETTINGS_PATH) +
  GET/POST /api/settings/advisor, same file-backed defaults-merge
  contract as the existing DISPLAY_PREFS pattern. Keys:
  total_capital_usd (nullable), maxfi_exposure_cap_pct (default 30.0),
  metrics_staleness_hours (default 12.0), metrics_auto_refresh_enabled
  (default true). Unknown keys reject with 400 - a deliberate deviation
  from display-prefs' more permissive pass-through, made because these
  values feed exposure/dry-powder math downstream and a typo'd key
  silently no-op'ing is worse than an immediate 400. The liquidity
  floors named earlier in this doc's v1 section are still NOT migrated
  into this settings file - their module-level constants
  (MAXFI_TOKEN_DAILY_LIQUIDITY_FLOOR_USD, ADVISOR_ENTRY_LIQUIDITY_FLOOR_USD)
  remain authoritative for the landed verdict/entry-gate paths; migrating
  a landed verdict-path constant into user-editable settings stays its
  own future diff, not bundled into this session.
- **C2 `48298dc`** - the metrics-refresh route body extracted into
  `_run_metrics_refresh(chain, dry_run) -> (dict, status)`, Flask-context-
  free, because the app's global auth gate blocks an HTTP self-call from
  inside another route. A non-blocking `_METRICS_REFRESH_LOCK` serializes
  the manual Scout "Refresh metrics" button against the new auto-trigger -
  whichever loses the race gets a 409 RefreshBusy rather than blocking or
  double-running. The advisor GET route now kicks a background per-chain
  refresh when that chain's metrics are stale, judged by MAX(fetched_at)
  across the chain's pools - MAX, not MIN, deliberately, so a pool that
  has never been reindexed doesn't hold an ancient timestamp that keeps
  triggering a refresh forever once one other pool in the chain is fresh.
  Additive `metrics_refresh_kicked` key on the advisor response. Smoke
  passed live.
- **ITEM 9 STATUS CORRECTION**: the refresh scheduler named in this doc's
  v2 list landed as its ON-VIEW STALENESS HALF only (the trigger inside
  C2 above). The timer-daemon half (a scan-loop template inside
  snapshot_service) is DEFERRED, not dropped - Glenn's explicit ruling
  was on-view now, timer later if it turns out to still be wanted once
  on-view is observed in practice. Token-daily itself remains
  console-invoked under the 25-call GT budget and is untouched by the
  scheduler by design - the scheduler covers DexScreener pool metrics
  only, so verdict-side (token-daily-driven decay) freshness still rides
  entirely on the manual daily runs, unchanged by this session.
- **C3 `5467d4c`** - the Action Plan screen (frontend-only:
  static/actionplan.js plus nav/app/index wiring; nav order lands
  P/L -> Action Plan -> Scout). Rulings on record from this landing: the
  probe shortlist is strictly gate-clear + above-floor + not-held, top 5
  by entry_score; ungated/null-gate young tokens are EXCLUDED from the
  recommendation surface entirely (uncleared is not the same as cleared -
  a count line points the user to Scout instead); all sizing is phrased
  as $25-50 probes, never anything larger, per the probe-rule discipline
  above; the freed-capital sum excludes stale valuations (current value
  older than 24h, or flagged uncollected_unavailable); the dry-powder
  card computes capital x cap% - exposure, with an over-cap guardrail
  banner, and carries the app's first inline settings inputs (the
  capital figure and cap % write straight to the C1 settings file). An
  entry_stage probe tag (which would need a guarded ALTER on
  maxfi_position_user_data) was considered and deliberately deferred
  again - scale-up-eligible sizing stays a manual judgment call for now,
  not a tracked field. Production eyeball passed Sep 12.
- **Test counts**: 991 -> 1002 -> 1009 -> 1009 across the three commits
  above (C1, C2, C3 respectively - C3 is frontend-only, hence unchanged).

## Catalogue-wide asset-class heuristic (Sep 12, `5f72ad9`)

Design step A only (per the Sep 12 ruling: A-then-B) - a Scout inline
class override remains step B, a separate later session.

- **Registry**: `MAXFI_STOCK_TICKER_REGISTRY`, a code constant only,
  deliberately WITHOUT a settings-file override (ruled), placed beside
  the `MAXFI_ANCHOR_REGISTRY_DEFAULTS` precedent it mirrors in kind. 39
  robinhood tickers (32 equities + ETFs GLD/QQQ/SGOV/SLV/SPY/USO + the
  private-market token SPCX); base is deliberately empty. Deliberate
  exclusions despite real-ticker collisions, recorded so nobody "fixes"
  them back in later: SPX on base is the SPX6900 meme, not the S&P 500;
  FOX and CB on robinhood collide with real tickers (Fox Corp, Chubb) but
  are meme tokens on this catalogue; TAO is Bittensor, a crypto token
  that happens to pair against the USDG anchor.
- **Rule**: any-side exact, case-sensitive symbol match -> stock, else
  default crypto - the locked Sep 9 rule that stock-anchored meme tokens
  (STONKBROKER, NASDANQ, TENDIES, ...) stay Crypto-class regardless of
  what they're named. A NULL/empty symbol on either side is skipped
  entirely - nothing is ever written on missing evidence.
- **Route**: `POST /api/maxfi/pool-classify`, `dry_run` per the same
  convention as `api_maxfi_catalogue_refresh` (query param or JSON body).
  Writes carry `set_by='heuristic'`, upserted under
  `WHERE maxfi_pool_meta.set_by = 'heuristic'` - a manual (`glenn`) row
  from the held-grid Class editor can never be overwritten by this route
  regardless of write ordering, and a re-run only ever updates the
  heuristic's own prior rows. No schema change was needed - `set_by` was
  already the provenance column `maxfi_pool_meta` was built with.
- **Validation**: a pre-land simulation reproduced all 27 manual
  Class-editor calls with zero disagreements against the registry; the
  production `dry_run` then matched that simulation exactly (base: 44
  crypto; robinhood: 65 stock + 56 crypto + 27 skipped_manual). The real
  run wrote 165 rows, and a post-run Scout pass confirmed the full
  catalogue is now classified - Unclassified is gone from the facet.
- **Maintenance loop**: re-fire `/api/maxfi/pool-classify` after any
  catalogue refresh or registry edit (dry_run first when the registry
  itself changed, to eyeball the diff before committing). A newly
  catalogued pool sits Unclassified until this route is re-fired - an
  automatic refresh-hook was considered and deliberately deferred, not
  dropped, same treatment as Item 9's timer half above.
- **Test count**: 1022 (1009 + 13 new in
  `tests/test_maxfi_pool_classify.py`).

## Scout Gate facet + Gate legend (Sep 12, `b989645`)

- **Rulings on record**: a GATE chip row with Clear/Blocked/Unknown
  buckets, rendered in fixed semantic order (never alphabetical); sharp
  dump is folded INTO the Blocked bucket rather than getting its own chip
  (the badge suffix " — sharp dump" is retained, and this is promotable to
  its own chip later if hunting sharp-dumps specifically becomes a real
  workflow - not ruled out, just not built now). `_scoutGateBucket` is the
  single source of truth for the three buckets; `_scoutGateInfo` (the
  table's own badge) was refactored to derive its display from that same
  function rather than duplicating the blocked/sharp_dump logic - verified
  display-identical (text/color/bg byte-for-byte unchanged) for every
  input before landing. The gate facet's counts follow the existing
  never-own-dimension convention the chain/asset-class facets already use
  (each chip counts what would remain visible under every OTHER active
  filter). A collapsible Gate legend panel lives in the filter card, its
  four explainer lines mirroring `maxfi_pooldata.downtrend_gate`'s own
  docstring rather than restating the rule in new words.
- **Threshold plumbing**: `POOLDATA_SHARP_DUMP_PCT_7D` is now shipped
  additively as `constants.sharp_dump_pct_7d` on the advisor payload (one
  backend line, via the `maxfi_pooldata` module import already in
  `web_portfolio.py` - no new import). The legend renders this threshold
  FROM the payload, with a graceful `'the sharp-dump threshold'` fallback
  when the key is absent/non-numeric - never hardcoded client-side. The
  new standalone test asserts both the wiring (matches the live module
  constant) AND the judgment-set value itself (`-15.0`), so a future
  retune of the constant fails a test immediately and forces a conscious
  legend-and-doc update instead of drifting unnoticed.
- **Deviation found and corrected pre-land**: the instruction block's
  step 3 phrasing ("add one new route-level test beside the existing
  constants assertions") was ambiguous between adding assertions inline
  into the existing happy-path test versus a new standalone test
  function. The inline reading was tried first; the quality gate's
  explicit "expect 1023 passed (1022 + 1)" caught it immediately, since
  inline assertions don't move a pass count - corrected to a standalone
  test before commit. Recorded here as the explicit-expected-count gate
  working exactly as designed, not as a landed defect.
- **Scope**: exactly 3 files touched - `web_portfolio.py` (one additive
  constants-dict line), `static/scout.js`, `tests/test_maxfi_advisor.py`
  (one new test) - diff-verified in chat before commit.
- **Test count**: 1022 -> 1023. Production eyeball passed Sep 12 (chip
  behavior, facet count sums, composition with the existing chain/asset-
  class/search/toggle filters, and the legend's threshold line rendering
  from the live payload rather than a hardcoded number).

## Phase E v2 session 2 (Sep 12) — S-class ATH suppression + weekend-delay handling: both CLOSED without code

Baseline main @ 6ed4012 (1023 tests). Step-1 read-only review executed clean; live data pulled
directly from the GeckoTerminal public API in chat (no production DB access needed — the
token-daily write path is a verified pass-through: INSERT OR REPLACE per returned candle date,
no gap-fill, no flat-candle detection, so the table's shape equals the feed's shape).

Nav reorder recorded (deferred mention from the prior session): 6ed4012 — static/nav.js only,
MaxFi section order is now MaxFi → P/L → Scout → Action Plan → Checklist.

ATH suppression: CLOSED — satisfied by prior removal. af11a0b (Token Δ removal) eliminated every
ATH consumer: grep-verified zero frontend readers of ath_price_usd/ath_at/ath_since/ath_source in
static/*.js; maxfi_advisor.py and maxfi_pooldata.py contain zero ATH references — no verdict,
gate, or entry-score math consumes ATH. The only remaining carrier is the valuation payload's
volatile_token block, which nothing renders. RULING (standing): never build a consumer on S-class
ATH values — recorded ATHs for tokenized stocks are launch-spike artifacts. Empirical
confirmation from the live pull: GLD's Aug 30 candle shows close ~$1,493 / high ~$2,030 vs ~$400
real — early thin-liquidity distortion baked permanently into the recorded ATH.

Weekend-delay handling: CLOSED — not applicable. The brief's premise ("weekend candles are flat
or absent; Monday reopens gap") is contradicted by the data on both halves. GT daily OHLCV pulled
Sep 12 for QQQ, MSTR, and GLD pools (robinhood chain, 14-day windows): every calendar day
present, including Sat/Sun Sep 5–6 AND Labor Day Mon Sep 7; weekend candles carry real price
discovery and real volume (QQQ Sat Sep 5 volume $7.2M exceeded several weekdays; MSTR moved +4.0%
that Saturday). These pools trade 24/7 on-chain; the DEX price floats while the underlying is
closed and re-anchors at reopen (MSTR re-anchor: −6.9% on Tue Sep 8 after the 3-day holiday
weekend). Re-anchor moves are real moves in the token the LP position holds — composition, IL,
and decay follow the on-chain price, so the advisor SHOULD see them; under the candle-half filter
it does, one day later, as a completed candle. There is no market-closed artifact in the series
for the math to be made honest about. Residual value captured as practice, not math: the
Friday-tighten / Monday-widen S-class parking discipline goes into the checklist page as content
(PLAYBOOK UPDATES chat, separate session). Evidence caveat: 3 large pools, 14 days, one chain —
a dust-liquidity stock pool could still print occasional zero-trade gap days; price_change_pct's
±2-day tolerance and the None-propagating gate already degrade gracefully there.

Findings of record from step-1 (documented, deliberately NOT built):
- asset_class is absent from the advisor route's per-position query and payload (present only in
  the entry_candidates path, via the pmeta LEFT JOIN). Any future per-position class-aware logic
  needs that join added first — additive, mirrors entry_candidates.
- No pool-class → volatile-token mapping exists in code. _maxfi_advisor_resolve_volatile is
  anchor-registry-only and never reads asset_class. The working premise "stock-class pool with a
  resolved volatile side ⇒ the volatile token is the stock" holds only while every registered
  anchor is crypto (currently true: ETH/USDG/WETH/USDC); registering a stock token as an anchor
  would silently break it. cbBTC/MSTR resolves as volatile_side_unresolved because NEITHER side
  is a registered anchor — an anchor-registry fact, not a stock-classification fact.
- Entry-candidates path has no candle-half filter (deliberate E v1 ruling) — sharp_dump can fire
  off a partial same-day candle on the entry side, the same same-day-flip risk the stabilizer
  removed for positions. Logged to Phase E backlog as its own future decision; not stock-specific.
- Young stock pools: when a pool ages to ~30 days, pct_30d's base row transiently lands in the
  launch-spike window and reads massively negative for roughly a week — generic young-pool
  behavior, contained by the existing gate structure and the $25–50 probe rule.
- No HTTP surface exposes raw maxfi_token_daily rows (advisor consumes them internally;
  token-daily-refresh responses return counts only). Established workaround for inspection:
  direct GT public API pulls per pool (network slug robinhood/base), token=quote variant when
  the token of interest is the quote side.

Phase E v2 remaining after this session: Action Plan follow-ons if any, timer-daemon half of the
scheduler (deferred not dropped), stabilizer 2-snapshot persistence half (only if observed churn
warrants), MX_VERDICT_STYLE/MX_VERDICT_RANK gap (bundled into whichever future item adds a
verdict string — no verdict string was added this session), Scout inline class override
(session B). Suggested next scoping candidate on record: principal-drawdown / path-damage gap
(fee-side-only verdict never sees principal-path damage).
