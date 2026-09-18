# HANDOFF — Flip Quality (per-token chop count) for the Trends page

Rulings locked 2026-09-18. Baseline at lock: main @ c4b0e11ce6adc9be0b6f615d4252317122d49aed, 1099 tests. Parent docs: HANDOFF_ma_band_scanner.md, HANDOFF_trends_restyle.md, HANDOFF_intraday_timeframes.md, HANDOFF_band_proximity.md (ruled successor in the Sep 17 next-scanner-workstreams sequence: A = band proximity -> trade-log revival -> B = flip quality -> C = RS vs BTC). This doc scopes B as PATH A ONLY (in-window chop count) — a persisted flip-history table (Path B from the scoping brief) is explicitly QUEUED below, not built here.

## Purpose

Distinguish a flip worth acting on from a chop flipper (HANDOFF_band_proximity.md's own Purpose section named this as the explicit follow-on). v1 = an in-window count of every strict crossover/crossunder compute_noodle_state's existing bar-walk already finds, surfaced as a sortable column plus a sidebar filter — a window-bounded proxy, not a persisted long-run reputation.

## Deferred / explicitly NOT this workstream

- A persisted `noodle_flip_history` table logging every flip event over time, enabling a true "N flips in the last 30/90 days" metric. The window-bounded count here has a real blind spot — a token that chopped hard just outside the current fetch window reads identically to a clean one. Queued as a deliberate follow-on; not built speculatively before this v1 shows whether it's actually needed.
- Recency-as-proxy (using the existing `flip_ts`/`flip_age_unbounded` fields to imply quality) — considered and rejected; it measures recency, not quality, and doesn't answer the Purpose section's actual ask.

## Rulings (locked, do not reopen)

1. Metric = COUNT of every strict crossover/crossunder `compute_noodle_state`'s existing bar-walk finds in the fetched window, full stop — no special-casing the most recent cross, no distinguishing completed pairs from an in-progress run. Per timeframe, all five, like every other field on this page.
2. Window = the SAME per-timeframe candle window already fetched for the existing scan (the `NOODLE_CANDLE_LIMITS` constants) — no second, shorter window. Consistent with the window "To flip" and "% since flip" already implicitly live inside.
3. Engine touch = ADDITIVE ONLY. New key on `compute_noodle_state`'s existing return dict (e.g. `flip_count_window`) — every existing key and existing test stays unchanged. Schema migration goes through `init_db()`'s real `migrations` list (`src/storage/portfolio_db.py`) — NOT `web_portfolio.py` (spec error #15 precedent, on this exact table).
4. The route's explicit SELECT column list (`api_trading_scanner_noodle_state`) must add the new column, or it silently never reaches the payload — the exact trap band-proximity's route hit and caught.
5. Display = BOTH a raw sortable "FLIPS" column (same header-style convention as TO FLIP / TIME SINCE FLIP) AND a sidebar "Hide choppy" toggle + threshold dropdown, same toggle+select shape as the existing Near Flip filter — reuse, no new UI machinery.
6. Threshold scale for the dropdown is NOT locked here. FIRST STEP of the implementation chat: pull a live scan sample and look at the real flip-count distribution across the current scanned universe before proposing numbers — do not guess a scale in the abstract. Candidates to sanity-check against real data, not pre-committed: something in the 2-5 range, on its own scale distinct from Near Flip's 1/2/3/5% (these are counts, not percentages).
7. Column label = "FLIPS".

## Next

Implementation runs in a fresh chat pointed at this doc, opening with ruling 6's live-distribution pull before any display code is written. Path B (persisted flip-history table) remains explicitly queued and unscoped — its own future session, not implied by this landing.
