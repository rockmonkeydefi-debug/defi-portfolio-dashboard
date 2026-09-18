# HANDOFF — RS vs BTC (Trends scanner, Commit C)

Rulings locked 2026-09-18. Baseline at lock: main @ 4540eae, 1125 tests. Parent context: Sep 17 next-scanner-workstreams ruling (A = band proximity, done 4faf972; B = flip quality, done ccfafb7; C = RS vs BTC) — C is next in the ruled sequence, following the completed trade-log revival (819c8e5 backend / 56a569e frontend / 4540eae close-out), which was inserted between B and C by a later ruling.

## Purpose

Add "RS vs BTC" as a new per-timeframe metric on the Trends page: how much a token's price move since its own flip is outperforming or underperforming BTC's move over that same window. Answers a question band proximity and flip quality don't: is this token actually leading, or just riding BTC's own move.

## Why scan-body computation, not read-time (ruled — do not reopen)

Band proximity and flip quality were both read-time derivations off fields already persisted in `noodle_state` (band edges, flip_ts, flip_price). RS vs BTC can't work that way: it needs BTC's raw candle series at the token's flip timestamp, and `noodle_state` only ever stores final computed indicator state, never the underlying OHLC candles used to get there. Once a scan pass finishes, that candle data is gone. This forces computation inside the scan body itself, while BTC's candles are still in memory for that pass, with the result persisted as an additive column. BTC is reliably present in the scanned universe (volume-sorted, effectively always #1 by volume on HL perps), so pulling its candles for cross-reference costs a few extra fetches on top of data the scan already needs, not a new dependency.

## Deferred / explicitly NOT this workstream

- Persisted BTC candle-history table for read-time recomputation between scans — no stated need; v1 recomputes fresh every scan like every other noodle feature.
- A sidebar "Outperforming BTC" filter — column only in v1; a filter can follow once real numbers are visible in production.
- Any RS metric anchored on BTC's own flip, or on a fixed lookback window instead of the token's flip.

## Rulings (locked, do not reopen)

1. Formula: `rs_vs_btc_pct = token_pct_change_since_flip − btc_pct_change_over_same_window` (percentage-point spread, not a ratio). `token_pct_change_since_flip = (last_close − flip_price) / flip_price × 100` — reuses the existing "% since flip" semantics already displayed elsewhere on Trends, not a new calc. `btc_pct_change_over_same_window = (btc_last_close − btc_price_at_token_flip_ts) / btc_price_at_token_flip_ts × 100`, where `btc_price_at_token_flip_ts` is the close of the BTC candle on that same timeframe whose timestamp is the first one at-or-after the token's `flip_ts`.
2. Anchor is always the token's own `flip_ts` — never BTC's own flip, never a fixed lookback window.
3. Computed per-timeframe, all five (1h/4h/12h/Daily/Weekly), alongside each existing per-timeframe `noodle_state` row.
4. Returns NULL when not computable: token's `flip_age_unbounded` is true, OR the token's `flip_ts` predates BTC's fetched candle window on that timeframe, OR the row being computed is BTC itself (self-comparison is undefined, not zero).
5. Architecture: an explicit BTC candle pre-fetch (1d/12h/1h; weekly derived the same way as every other symbol) runs ONCE at the start of the scan body, before the main per-symbol loop, and is held in memory for the whole pass. This does not depend on where BTC lands in the volume-sorted loop order. Adds roughly 3 extra HL calls total per full scan pass — negligible against the 55/min budget.
6. Storage: new nullable column `rs_vs_btc_pct` (REAL) added to `noodle_state` via `init_db()`'s `migrations` list — an ADDITIVE column on the existing table (mirrors `last_close`'s precedent from band proximity), NOT a new base-table column and NOT a new table.
7. Frontend: new sortable "RS vs BTC" column/tile on the Trends page, per-timeframe, alongside the existing "To flip" (dist-to-flip) column; green/red colored by sign; dash for NULL. No new sidebar filter in v1 (ruling 4 above, deferred).
8. Commit plan: two commits, same shape as band proximity and flip quality. Commit 1 backend (migration, BTC pre-fetch, scan-body RS computation, route SELECT/emit, tests — STOP-gated, report before Commit 2). Commit 2 frontend (trends.js column only, zero backend diff). Doc close-out append with both SHAs.

## Next

Implementation runs in a fresh chat pointed at this doc: step-1 read-only confirm pass (exact scan-body insertion point for the BTC pre-fetch given current line numbers, re-confirm the migrations-list pattern against its most recent precedent, locate the existing "% since flip" display calc to reuse for `token_pct_change_since_flip` rather than reinventing it, confirm how the scan body currently identifies BTC's row in `perp_universe` for the pre-fetch), then Commit 1 (STOP-gated), then Commit 2, then the close-out append.

## Implementation landing (2026-09-18)

Commit 1 (backend: `rs_vs_btc_pct` column, BTC candle pre-fetch, `_rs_vs_btc_pct` pure helper, scan-body wiring, route SELECT addition, 13 tests in `tests/test_rs_vs_btc.py`): SHA `8e32a10`. Commit 2 (frontend: `static/trends.js` RS vs BTC column only, zero backend diff): SHA `2e4bc2f`. Both on `main`, 1138 tests passing (1125 baseline + 13 Commit-1 tests, unchanged through Commit 2).

**Ruling-1 flag, resolved before any code was written**: ruling 1 anchors `token_pct_change_since_flip` on `last_close` (closed-candle), which on its face looked like it broke HANDOFF_band_proximity.md's ruled "`% since flip` is mark-anchored (`price`), `To flip` is closed-candle-anchored, never unify them" precedent — the existing frontend "% since flip" display (`static/trends.js`, `_trendsPctSinceFlip`) does still call with `tf.price`, confirmed untouched. The resolution: `noodle_state.price` is a single **current** mark-price snapshot per symbol (`web_portfolio.py`'s scan body sets it once from `_hl_fetch_top_volume`'s live quote, never a historical series) — there is no historical mark price to look up BTC's price at an arbitrary past `flip_ts`. Candle closes are the only historical price source that exists at all, so both sides of the RS spread necessarily share that basis. This is a deliberate, correct exception specific to RS vs BTC's own internal calc; it does not touch or "unify" the existing display column in any way.

Frontend note: `_trendsFmtToFlip` (originally written for `dist_to_flip_pct`, band-proximity Commit 2) was reused as-is for `rs_vs_btc_pct` rather than duplicating an identical one-decimal-signed-percent formatter — its comment was extended to note the shared use rather than renamed, to avoid an unrelated diff against band-proximity's landed code.

No further scanner workstream is currently ruled. RS vs BTC (C) was the last item in the Sep 17 sequence (A band proximity, B flip quality, C this one) — check with Glenn for what's next rather than assuming a D.
