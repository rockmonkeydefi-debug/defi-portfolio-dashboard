HANDOFF — LP Advisor Phase B (write paths + refresh routes)

PURPOSE
Continue the LP Advisor workstream (in-app pool evaluation + position
verdicts for the MaxFi dashboard). Discovery (A1-A1.6) and Phase A2
(schema + pure providers) are COMPLETE. This doc is self-contained for
Phase B; the original feature spec lives in the MaxFi Strategy project.

WORKFLOW
Standard two-step: (1) review this doc against the codebase at HEAD,
surface conflicts, confirm plan with Glenn; (2) instruction blocks per
his stored output-format rules. Write-path commits are STOP-gated:
quality check, report, wait for explicit Y. Backend/frontend split per
commit discipline. Post-commit diffs verified against GitHub
(commit/<sha>.diff works unauthenticated).

COMMIT TRAIL (this workstream, all on main, all diff-verified)
- 18a0eb6  A1    maxfi_pooldata.py + GET /api/maxfi/pooldata-probe
                 (DeFiLlama probe)
- 988c01a  A1.5  match_pools_by_underlying + held-token join on probe
- bdadf84  A1.6  maxfi_client additions (ADDITIVE ONLY):
                 SEL_ERC721_BALANCE_OF, SEL_ERC721_TOKEN_OF_OWNER_BY_INDEX,
                 get_npm_balance_of, enumerate_owner_token_ids
                 (multicall3_soft, returns (ids, failed_count)),
                 decode_positions_and_pools(chain, token_ids) — the
                 vault-id decode seam (do NOT use
                 get_wallet_position_snapshot: it derives ids from
                 lens.getUserPositions(wallet), wrong source);
                 + GET /api/maxfi/catalogue-probe/<chain>
- 3fa5e00  A2c1  schema: maxfi_catalogue_pools, maxfi_pool_metrics,
                 maxfi_token_daily, MAXFI_TOKEN_DAILY_MAX_ROWS=35,
                 invariant comment amended
- a9fd3d4  A2c2  providers: DexScreenerError, fetch_dexscreener_pairs
                 (30-addr batch cap, typed error), parse_pair_metrics
                 (None-on-bad-field, never raises),
                 summarize_pair_batches, price_change_pct (±2d
                 tolerance), volume_trend_ratio, downtrend_gate
                 (returns blocked None=unknown, never coerced)
Baseline: 815 tests.

VERIFIED PROBE FACTS (live, Sep 8 2026 — do not re-derive)
- DeFiLlama does NOT index MaxFi (0 project match; 19/24 held tokens
  invisible; volumeUsd1d/7d null on all Robinhood Chain rows). The
  llama functions in maxfi_pooldata.py are retained but role-less;
  removal is a separate decision, never a drive-by.
- No "maxfi" dexId on DexScreener. MaxFi = vault layer over standard
  Uniswap V3; its pools ARE indexed on DexScreener under
  dexId "uniswap", joinable by pool_address == pairAddress
  (case-insensitive). Pair payloads carry priceUsd (STRING), nested
  liquidity.usd, volume.h24/h6/h1, priceChange.h24 (thin pairs omit
  keys — parse_pair_metrics already handles).
- Vault custody premise HOLDS on both chains (NPM NFTs held by vault;
  ERC721Enumerable works; 0 failed indices in 4,059 calls):
  robinhood vault 0x1195c074f898b7644ba732407619c9804dfe6dce —
  npm_position_count 10,943; probe enumerated 3,000 (truncated),
  145 distinct pools / 102 tokens in that sample; full catalogue is
  LARGER (tail holds the low-count/new pools a scout wants).
  base vault 0x7d27cdfbfcc878f7e7349e216d44204bfd2afd55 —
  1,059 positions, 44 pools / 34 tokens, complete.
- Full robinhood enumeration ≈ 22k eth_calls via multicall — fine at
  1-2x/day through Alchemy.
- GT candles: keyed CoinGecko onchain quota (COINGECKO_API_KEY is SET
  on Railway; ~10k/mo). fetch_pool_ohlcv self-paces 3.0s and raises
  GTRateLimitError on 429 (route aborts run). GT_CALL_BUDGET_PER_RUN=25
  per invocation, resumable-route pattern proven by the GT backfill
  route (api_maxfi_backfill_history — copy its structure).

LOCKED DECISIONS (Glenn, this session)
- Catalogue refresh: full budgeted enumeration 1-2x/day, resumable
  route pattern. Incremental Transfer-log indexing = v2 only.
- GT candle gating: liquidity floor (configurable, default $10k) +
  ALWAYS include tokens of held positions. Never candles for every
  catalogue token.
- Bucket tracking (33/33/33) deferred to v1.1; ship only the 30%
  total-exposure cap (manual total-capital figure).
- S-class ATH Δ: suppress for stock-class rows, show Open Δ only
  (frontend-only, Phase D). No equities data source.
- Monday pre-open S-class alert: in-app banner v1; push waits for the
  separate Telegram workstream.
- Probe tag: entry_stage column on maxfi_position_user_data via
  guarded ALTER (Phase E). Never a column on maxfi_positions.
- Advisor settings (capital figure, cap %, cadences, claim-age alert,
  liquidity floor): DISPLAY_PREFS-style validated JSON file + GET/POST
  (parallel ADVISOR_SETTINGS_PATH), not scanner_settings.json.

PHASE B SCOPE (this fresh chat) — three commits, each STOP-gated
(write paths):
B1 Catalogue refresh route POST /api/maxfi/catalogue-refresh/<chain>:
   get_vault -> get_npm_balance_of -> enumerate_owner_token_ids
   (budgeted/resumable: accept offset+count or internal cursor via
   worklist-rebuild like the backfill route; handle the 10,943-position
   reality) -> decode_positions_and_pools -> aggregate distinct pools
   -> UPSERT maxfi_catalogue_pools: INSERT sets first_seen_at (INSERT-
   only invariant, zero UPDATE sites — pinned by a test like
   test_rebalance_updates_token_id_keeps_first_seen_at); ON CONFLICT
   updates position_count/symbols/last_seen_at/last_enumerated_at only.
   Addresses lowercased on write (schema comment contract). dry_run
   param: route requires exact 'true' — replicate the backfill route's
   convention AND its frontend lesson (the ?dry_run=1 defect, fixed in
   8eb2458): any future button must send 'true'.
B2 Metrics refresh route: read catalogue pools (+ held pools not yet
   in catalogue) -> summarize_pair_batches -> fetch_dexscreener_pairs
   per batch (per-batch error isolation: one DexScreenerError skips
   that batch, never aborts the run) -> parse_pair_metrics -> UPSERT
   maxfi_pool_metrics OVERWRITE-ALWAYS (schema contract). Note
   dexscreener_slug registry exists in web_portfolio.py (~line 1950).
B3 Token-daily refresh route: pick each token's deepest pool by
   liquidity_usd from maxfi_pool_metrics (fallback: any catalogue
   pool); apply liquidity floor + held-token override; GT day candles
   via maxfi_history.fetch_pool_ohlcv (reuse, do not modify; shared
   budget counter; GTRateLimitError aborts run); resolve token side
   via maxfi_history.resolve_token_side; write close_usd rows to
   maxfi_token_daily; PRUNE oldest beyond MAXFI_TOKEN_DAILY_MAX_ROWS
   per (chain,address) IN THE SAME TRANSACTION as the insert (schema
   contract "bounded by contract").
All three: ensure_maxfi_tables(conn) at top; per-request connection;
failure isolation per unit; every payload row carries fetched_at /
*_at timestamps. NO scheduler in Phase B — routes are manually/
frontend triggered; scheduling is a later decision.

PHASES AFTER B (own chats)
C  maxfi_advisor.py pure module (run-rate %/day, decay from 7d/30d,
   2x rule -> HOLD/CLOSE/insufficient_data; entry score = fee-APR
   estimate (24h vol x fee_tier/1e6 / TVL... verify units against
   fee_tier storage: raw int e.g. 3000 = 0.3%) x volume-trend
   multiplier; downtrend gate wired) + advisor endpoint + tests.
   Verdicts NEVER auto-execute anything; sunk cost never a verdict
   input.
D  Held-grid frontend: Run-rate/Decay/Verdict columns (thread through
   mxSortValue + sortableTh), S-class ATH suppression, claim-age
   alert, S-class weekend delay handling (72h = deliberate parking,
   not overdue). maxfi.js rules: no className, inline styles, 100%
   React.createElement, money columns never right-aligned, Glenn's
   UI/UX visibility standards.
E  Pool Scout page + advisor settings + exposure-cap display + probe
   tagging.

INVARIANTS / HAZARDS (verbatim from house rules; do not violate)
- ensure_maxfi_tables return dict must never gain keys (now pinned by
  a test in test_maxfi_catalogue_schema.py).
- maxfi_positions token addresses NOT normalized — LOWER() on the
  positions side only in joins. New advisor tables store lowercased.
- api() in static/utils.js returns undefined on 401 without throwing —
  every future write handler guards for this (Phase D/E).
- entrypoint.sh never touched. git add by explicit filename only.
- _FlakyConnection hazard lives only in resolve_ambiguous_auto_splits
  tests — Phase B touches no scan-path statements, keep it that way.
- Claude Code summaries are claims; Glenn/chat verifies diffs on
  GitHub after every landing.
- Branch+PR landing fallback: merge stale remote tip non-destructively
  (never force-push), re-run quality gate on merged tree, mark ready
  if draft, self-squash-merge, branch deletion 403s (Glenn deletes in
  UI), stand down watcher. Do not leave a PR parked.

OUT OF SCOPE (unchanged from spec)
Range-width backtesting/leaderboards; AI/LLM advisor layer;
auto-compounding/claiming/execution; scraping maxfi-lp.vercel.app.
