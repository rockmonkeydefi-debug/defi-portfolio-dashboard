# HANDOFF — Trends Page Restyle (Bullmania model)

Rulings locked 2026-09-16 in the Commit 3 chat. Baseline at lock: main @
4d60621 (Noodle scanner Commit 3/3 landed), 1047 tests. This doc is the
contract for the implementation chats. Parent doc: HANDOFF_ma_band_scanner.md
(engine spec, fetch shape, refresh model, settings keys — all unchanged here).

## Purpose

Restyle the Trends page (static/trends.js, tab id 'trends') to closely
match Glenn's Bullmania reference screenshot in layout, coloring and
functionality — within what the Hyperliquid-only v1 data source can
support. Data-source-bound Bullmania features are parked (list at the end),
NOT smuggled into the restyle.

## Rulings (all locked, do not reopen)

1. Sequence = backend first, then frontend: a volume/alignment backend
   pair of commits precedes the restyle so the frontend reads persisted
   fields rather than deriving them.
2. Palette = Bullmania's purple/black, PAGE-SCOPED ONLY: judgment-set
   constants inside static/trends.js. No edits to static/style.css. Every
   other tab keeps the app's navy theme. Glenn accepted the resulting
   visual inconsistency explicitly.
3. Alignment display drops the L1/L2/L3 levels entirely. Reason of
   record: alignment_bull + alignment_bear always sums to 3, so
   max(bull, bear) is always 2 or 3 — L1 could never fire; the "gradient"
   was two steps in practice (Claude's design miss, corrected here).
4. Alignment 3-state mapping = FULL-STACK-ONLY:
     alignment_bull == 3  -> BULLISH   (fast > medium > slow, fully stacked)
     alignment_bear == 3  -> BEARISH   (fully stacked the other way)
     anything else        -> NEUTRAL   (2-1 / 1-2 / ties = EMAs tangled)
     alignment undefined  -> None      (too-short-history WARMUP variant)
   Majority-wins was rejected: under it NEUTRAL only fires on a float tie,
   so the Bearish->Neutral->Bullish transitions Glenn wants to see would
   never occur. Under full-stack-only, NEUTRAL is common and meaningful.
5. Prior-alignment-state column = ENGINE WALK-BACK (not a write-path diff):
   computed from the same candle window as the flip walk, correct from the
   first post-deploy scan, resolution = the candle timeframe. Write-path
   diffing was rejected (blank until states change post-deploy; quantized
   to the 6h scan cadence).
6. The prior-state column is ALIGNMENT-only. The flip-state is hysteretic
   Bullish<->Bearish and never passes through a middle state (WARMUP is a
   no-history state, not a transition), so "prior flip-state" is always the
   opposite of the current one — a useless column, not built.
7. The 3-state mapping now lives in the BACKEND (engine), single source of
   truth for both the display and the prior-state tracking. The frontend's
   current _trendsAlignmentInfo level logic is deleted in Commit 3, not
   kept in parallel.
8. "Top 20 / 50 / 100" filter = by 24h VOLUME RANK, labeled "by volume" in
   the UI. Never label it market cap: HL gives no market-cap data, and
   volume rank diverges from cap rank materially (memecoins with heavy
   perp volume rank far above their cap). Honest labeling is a hard rule.
9. WARMUP flip-state keeps its "Neutral" display label (Commit 3 ruling);
   API/engine/internal keys stay 'WARMUP'. The alignment NEUTRAL state is a
   different concept that happens to share the word — the UI must make the
   two visually distinct (see Commit 3 spec).

## Reference design (Bullmania screenshot — the spec)

Layout: dark purple/black page; two columns — data table left (~70%),
sticky filter panel right (~30%). Above the table: a search box
("Search name, symbol…"). Above everything: a stats strip of big numbers
(their: Total Market Cap, Total Tokens, Bullish count with green %,
Bearish count with red %).
Table columns (theirs): #, Token (logo + name + symbol), Trend (BULLISH
green / BEARISH red pill), Price Change Since Flip (green/red %), Time
Since Flip ("7M 2W 1D 14h 31m"), Price, Market Cap, chart icon.
Filter panel sections (theirs): TREND chips (BULLISH / BEARISH / WARMUP,
toggleable); TIME SINCE FLIPPED dropdown; TIMEFRAME chips (1 Hour, 4 Hours,
12 Hours, Daily, Weekly, Monthly); PAIR/QUOTE chips (USD, BTC, SPX, ETH,
SOL); PROXIMITY chips (Near ATH, Near 200WMA); FILTER BY MARKET CAP dropdown.
Dropdown option sets captured verbatim from Glenn's screenshots:
  Time since flipped: Any time, 1 hour, 4 hours, 1 day, 2 days, 3 days,
    4 days, 5 days, 6 days, 1 week, 2 weeks, 3 weeks, 1 month
  Market cap:          All, Top 20, Top 50, Top 100
Palette (sampled from the screenshot — approximate, tune in Commit 3):
  page bg ~#0e0a15, panel bg ~#1a1226, borders ~rgba(255,255,255,0.12),
  active chip ~#b3164f on ~rgba(179,22,79,0.25), bullish green #22c55e on
  a dark-green tint, bearish red #ef4444 on a dark-red tint, warmup/neutral
  amber #eab308 on a dark-amber tint, primary text #f3f4f6, secondary
  #c9d1d9. UI/UX visibility standards still apply (no text below ~60%
  brightness on dark, table content >= 12px, secondary labels >= 11px,
  visible separators).

## Feasibility split (decided, drives the commit scope)

Buildable now from HL data:
  layout, palette, stats strip (Total tokens, Bullish/Bearish/Neutral
  counts + %), search, TREND chips, TIME SINCE FLIPPED dropdown, TIMEFRAME
  chips (12 Hours / Daily / Weekly ONLY), granular flip-age format,
  Price Change Since Flip coloring, Top-N BY VOLUME (needs volume_24h
  persisted), Prior Alignment column (needs the engine walk-back).
Parked as v2 — data-source-bound, out of scope for this workstream:
  market-cap column / Total Market Cap stat / true market-cap filter; token
  logos and full names (HL gives bare tickers only; all three unlock
  together with the CoinGecko universe widening parked in the parent doc);
  1 Hour / 4 Hours / Monthly timeframes (new candle fetches, roughly
  doubles HL calls per symbol on the shared 55/min budget); PAIR/QUOTE
  relative trend (engine extension); Near ATH / Near 200WMA (parked in the
  parent doc); per-row chart popup; favorites/watchlist.
  Do NOT render disabled placeholder chips for parked items — omit them.

## Commit sequence (each review-gated per house rules)

### Commit 1 — engine (pure, src/engines/noodle_bands.py + tests)
ADDITIVE only. compute_noodle_state gains four return keys; every existing
key stays byte-identical, existing tests must pass unmodified.
  alignment_state            'BULLISH' | 'BEARISH' | 'NEUTRAL' | None
                             (mapping per ruling 4; None iff alignment_bull
                             is None today)
  alignment_prev_state       the most recent DIFFERENT alignment state
                             before the current run, or None
  alignment_changed_ts       epoch seconds of the FIRST bar of the current
                             alignment run (the bar right after the last
                             differing bar), or None
  alignment_changed_unbounded
                             True iff the current alignment state holds on
                             every bar back to the start of the evaluable
                             window (no differing bar found — the real
                             change predates the fetched candles, so
                             prev_state/changed_ts are None but "unknown",
                             mirroring flip_age_unbounded semantics);
                             False when a change was located; None when
                             alignment is undefined
Walk-back: compute the 3-state alignment per bar over the same bar range
the existing code already evaluates (from first_idx to the last bar — keep
that gate, do not invent a separate EMA-only start index), using the
per-bar ema_f/ema_m/ema_s lists already computed. Walk backward from the
last bar to find the first bar whose state differs. Pure function of the
candles; no I/O. Tests: existing suite unchanged; new tests pin each
mapping case (3-0, 0-3, 2-1, 1-2), a located change with correct
prev/changed_ts, the unbounded case, and the undefined (too-short) case.
Gate: python -m py_compile + python -m pytest tests/ (expect 1047 + new).
Landing: direct push to main (pure additive engine change, no schema).

### Commit 2 — schema + scan body + route (STOP-gated before commit)
Step-1 read-only review FIRST — answer before writing anything:
  (a) How noodle_state columns are migrated in src/storage/portfolio_db.py
      (the cascade_state precedent; the "[startup] scanner column
      migrations applied" startup line suggests a migration block) — add
      the new columns by that file's own pattern, file-wins over this doc.
  (b) Confirm asset['volume_24h'] is present on every entry of the
      _hl_fetch_top_volume list the scan body iterates (it is constructed
      there today — verify, don't assume).
  (c) Confirm nothing here shifts the _FlakyConnection execute() pins in
      tests/test_maxfi_auto_split_write.py (noodle code touches no MaxFi
      path — verify the claim).
New columns on noodle_state: volume_24h REAL, alignment_state TEXT,
alignment_prev_state TEXT, alignment_changed_ts REAL,
alignment_changed_unbounded INTEGER (nullable, mirror
flip_age_unbounded's storage). Scan body: write volume_24h from the asset
dict and the four alignment fields from the engine result, in the same
upsert (additive columns in the INSERT and ON CONFLICT SET lists). Route
GET /api/trading/scanner/noodle-state: add the five fields to the SELECT
and payload; convert alignment_changed_unbounded to bool/None exactly the
way flip_age_unbounded is converted today. Tests: schema/migration tests
per the file's precedent + scan-body write test + route payload test.
Gate: py_compile + full pytest. STOP after the gate and wait for an
explicit "Y" before committing — schema + write path. Push direct to main
after approval.

### Commit 3 — frontend restyle (static/trends.js only; zero backend diff)
Documented default assumption (proceed unless Glenn amends at step-1):
the Bullmania model is ONE selected timeframe driving the whole table via
the sidebar TIMEFRAME chips. The current three-side-by-side timeframe
columns are REPLACED by that model. If Glenn wants both, it's an
amendment in the implementation chat, not a silent addition.
Layout: two columns — table left, sticky filter panel right. Stats strip
above: Total tokens, Bullish n (%), Bearish n (%), Neutral n (%) — counts
over the currently loaded universe for the selected timeframe's
FLIP-state, matching Bullmania's semantics. Search box above the table.
Table columns, in order:
  #                        volume rank (1 = highest volume_24h), sorted by
                           volume_24h desc; "—" if volume_24h null
  Token                    bare ticker (no logo/name — parked)
  Trend                    flip-state chip for the selected timeframe:
                           Bullish green / Bearish red / Neutral amber
                           (WARMUP's display label stays "Neutral")
  Alignment                3-state chip from alignment_state: Bullish /
                           Bearish / Neutral. MUST be visually distinct
                           from the Trend chip so the two "Neutral"s can't
                           be confused: outline-only style for alignment
                           vs filled for trend, plus a fixed "EMA" caption
                           on the column header. "—" when null.
  Prior Alignment          alignment_prev_state as a small chip + age text
                           from alignment_changed_ts in the granular
                           format ("Bearish · 3D 4h"); "> window" when
                           alignment_changed_unbounded is true; "—" when
                           null. Tooltip = the change timestamp.
  Price Change Since Flip  fmtPct(), green when >= 0, red when < 0; "—"
                           when flip_price is null
  Time Since Flip          granular format (see below); "> window" when
                           flip_age_unbounded; "—" when no flip
  Price                    fmtPrice()
  Volume 24h               fmt(volume_24h, 0) — the honest stand-in for
                           Bullmania's Market Cap column; header reads
                           "Volume 24h", never "Market Cap"
All columns sortable via the existing cycleSort pattern; missing values
sink to the bottom regardless of direction (house convention).
Sidebar sections, in order:
  TREND        chips Bullish / Bearish / Neutral — multi-select toggles
               like Bullmania's (all on = no filter); applies to the
               selected timeframe's flip-state
  ALIGNMENT    same three chips, same behavior, applies to alignment_state
               (additive over Bullmania — cheap and on-thesis)
  TIME SINCE FLIPPED  <select> with the 13 options verbatim from the
               reference; filters rows whose selected-timeframe flip age
               <= the chosen window; "> window" rows pass only "Any time"
  TIMEFRAME    chips 12 Hours / Daily / Weekly ONLY (default Daily, per
               the parent doc); no 1 Hour / 4 Hours / Monthly chips at all
  TOP BY VOLUME  <select> All / Top 20 / Top 50 / Top 100 — by volume rank
               (the honest replacement for FILTER BY MARKET CAP)
  PAIR/QUOTE and PROXIMITY sections: omitted entirely (parked).
Granular flip-age format (local helper, replaces _trendsDuration):
  units M (30 days) / W / D / h / m, e.g. "7M 2W 1D 14h 31m"; omit leading
  zero units; minutes always shown for < 1h. Used by Time Since Flip and
  Prior Alignment age.
Refresh button and 409 handling: unchanged from today (blocking
multi-minute POST; "Scanning… (~7-9 min)" label; soft busy message).
Gate: Babel syntax check on trends.js, Python raw-byte NUL check
(data.count(b'\x00') == 0 — never grep), full pytest as the zero-backend-
diff proof (count unchanged from post-Commit-2). Landing: direct push to
main, exactly one file (static/trends.js) plus an append-only close-out
to this doc.

## Parked (v2) — recorded so nobody re-derives it

- CoinGecko universe widening: unlocks logos, full names, market cap
  column/stat/true market-cap filter together (symbol-mapping layer needed)
- 1 Hour / 4 Hours / Monthly timeframes
- PAIR/QUOTE relative trend
- Near ATH / Near 200WMA proximity
- Per-row chart popup; favorites/watchlist
- Frontend auto-polling during a pass (parent doc non-goal, still holds)

## Non-goals / do-not-touch

No changes to the ICT/cascade scanner or its routes/settings. No MaxFi
changes. No global CSS changes. No new rate limiter. No changes to the
flip-state hysteresis semantics or the parity-tested EMA/ATR/band math.

## Commit 3 close-out (2026-09-16)

Commit hash: <hash>

Amendments approved by Glenn in the implementation chat (additions to
Commit 3 scope, not reinterpretations of existing rulings):

  A1. Single-timeframe model CONFIRMED: the sidebar TIMEFRAME chip drives
      the whole table. The three side-by-side timeframe columns are
      replaced.
  A2. Expandable rows: clicking a ticker row toggles an inline accordion
      sub-table directly beneath it showing ALL THREE timeframes (12H /
      Daily / Weekly), one sub-row each, columns: Timeframe, Trend chip,
      Alignment chip, Δ since flip, Time since flip. The currently
      selected timeframe's sub-row is highlighted and tagged "VIEW".
      Multiple rows may be expanded at once. Pure client-side — the
      per-row data for all three timeframes is already in the payload.
  A3. Confluence tiles: every row's Trend cell shows, after the flip-state
      chip, three small colored tiles labeled 12 / D / W — one per
      timeframe, colored by that timeframe's flip-state (green / red /
      amber for WARMUP). The selected timeframe's tile carries a
      1-2px outline. Always visible, no click needed.
  A4. Confluence filter: a new sidebar section CONFLUENCE with two
      toggle chips, "All 3 agree" (all three timeframes share the same
      non-WARMUP flip-state) and "Daily = Weekly". Off by default. Placed
      directly under the TREND section.
  A5. Confluence stat: the stats strip gains a fifth number, "Full
      confluence — N (all 3 TFs agree)", counting rows in the loaded
      universe where all three flip-states match and none is WARMUP.
- 2026-09-17: "1 Hour / 4 Hours timeframes" un-parked — see HANDOFF_intraday_timeframes.md. Monthly remains parked.
- 2026-09-17: "proximity" un-parked under a new definition — see HANDOFF_band_proximity.md. Market-cap framing stays parked.
