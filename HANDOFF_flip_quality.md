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

## Implementation landing (2026-09-18)

Commit 1 (backend, `flip_count_window` on `compute_noodle_state` + migration + scan-body persistence + route SELECT): SHA `d3b01b5`. Commit 2 (frontend, `static/trends.js`: FLIPS column + Hide Choppy sidebar filter): SHA `9722f9b`. Both on `main`.

**Live flip-count distribution (session step 2, ruling 6)** — 40 symbols, top-volume perps, real HL data, before any threshold number was proposed:

| TF | n | min | p50 | p75 | p90 | max | mean |
|----|---|-----|-----|-----|-----|-----|------|
| 1w | 40 | 0 | 2 | 2 | 3 | 5 | 1.6 |
| 1d | 40 | 0 | 27 | 32 | 39 | 39 | 25.1 |
| 12h | 40 | 2 | 28 | 33 | 36 | 41 | 27.7 |
| 4h | 40 | 10 | 36 | 39 | 44 | 48 | 34.4 |
| 1h | 40 | 49 | 151 | 172 | 187 | 196 | 152.2 |

Finding: raw flip counts scale ~100x across timeframes (median 2 at 1w vs. 151 at 1h) — purely a function of each timeframe's window length in bars (1w ≈ 200 bars vs. 1h ≈ 1440 bars), not of actual "choppiness." Ruling 6's own candidate scale ("something in the 2-5 range") only fits 1w; at 1d/12h/4h/1h nothing scores below 7. This ruled out a single flat dropdown (the shape ruling 5 describes for reuse) — a **timeframe-aware threshold set** was used instead: the "Hide choppy" dropdown's own `<option>` list changes with the selected TIMEFRAME chip, landed as `TRENDS_HIDE_CHOPPY_THRESHOLDS` in `static/trends.js`:

```
'1w':  [1, 2, 3]
'1d':  [15, 25, 35]
'12h': [15, 25, 35]
'4h':  [20, 30, 40]
'1h':  [80, 120, 160]
```

Documented in-file as v1 calibration constants, not silently hardcoded — and explicitly caveated there as derived from a 40-symbol sample, not the full scanned universe (~237+ symbols); revisit if full-universe behavior looks off once this has been live for a while.

**Null-handling ruling**: a null `flip_count_window` (insufficient history) FAILS the "Hide choppy" filter when active, rather than passing through as "unknown, not choppy." This was checked against existing precedent in `trends.js` before landing, not assumed either way: `_trendsPassesNearFlip`, `_trendsPassesTimeSinceFlipped`, and the TREND/ALIGNMENT multi-filters (once actually narrowed) all fail-closed on a missing measurement — no filter in this file lets a null pass through an active constraint. `_trendsPassesHideChoppy` mirrors that convention exactly.
