# HANDOFF — Intraday Timeframes (1H / 4H) for the Trends page

Rulings locked 2026-09-17 in the async-scan chat. Baseline at lock: main @
9a25bda (async noodle scan + progress landed), 1077 tests. Parent docs:
HANDOFF_ma_band_scanner.md (engine, fetch shape, settings keys) and
HANDOFF_trends_restyle.md (Bullmania page, rulings 1-9, amendments A1-A5,
Commit 3 close-out). This doc un-parks the "1 Hour / 4 Hours" item from the
restyle doc's parked list; Monthly stays parked.

## Purpose

Add 1H and 4H as scanner timeframes and Trends-page selections, within the
existing Hyperliquid data source and the shared 55/min call budget, without
changing the engine, the flip-state semantics, or the async scan model.

## Rulings (locked, do not reopen)

1. Fetch strategy = 1H NATIVE, 4H DERIVED. Fetch 1h candles from HL per
   symbol; build 4h candles by aggregating 4 consecutive UTC-aligned 1h
   bars (00:00, 04:00, 08:00 ... boundaries), modeled on the existing
   _weekly_from_dailies precedent. 12H stays NATIVE (do not replace a
   live, parity-tested series with a derived one). Net: 3 HL fetches per
   symbol instead of 2 (~1.5x pass length), not 4.
2. Derived-4H parity is a GATE, not an assumption: Commit 1 includes a
   fixture of real HL 4h candles for at least two symbols captured
   alongside their 1h candles, and a test asserting the aggregated OHLCV
   equals the native series bar-for-bar (volume summed, open of first,
   close of last, high/low extremes). If parity fails at any bar, STOP
   and report — do not ship 4H on a series that disagrees with HL.
3. Confluence semantics UNCHANGED: "All 3 agree" and the Full-confluence
   stat remain defined over 12H / Daily / Weekly only. 1H and 4H are shown
   as tiles for context. One new sidebar toggle "4H agrees" = the 4H
   flip-state equals the shared 12H/D/W state (passes only when all 3
   already agree AND 4H matches). 1H is excluded from every confluence
   definition.
4. Staleness UNCHANGED for v1: the single noodle_staleness_hours rule
   (default 6) governs all five timeframes. 1H/4H are "current as of last
   scan"; the page already shows the scan time. Revisit only if the
   intraday columns turn out to matter for entries.
5. Default table timeframe stays Daily.
6. Engine untouched: compute_noodle_state runs on the 1h and derived 4h
   series with the same parameters as today. If the scanner settings turn
   out to hold per-timeframe EMA/ATR parameters, 1H and 4H take the same
   values as 12H unless Glenn amends at step 1.
7. Schema: no new columns. noodle_state is keyed per (symbol, timeframe)
   with timeframe TEXT; rows for '1h' and '4h' land in the same table via
   the same upsert. NOODLE_CANDLE_LIMITS gains '1h'; NOODLE_WINDOW_DAYS
   gains '1h' and '4h' with values computed from the fetched depth.
8. 1H history depth is decided at Commit 1 step 1, not here (see Open
   engineering questions). Minimum acceptable: the 1h flip walk-back must
   cover at least 60 days, else the column is not worth shipping.
9. The restyle-era forbidden-string check that treated "1 hour" / "4 hours"
   as parked-feature leaks is retired for this workstream; "monthly",
   "market cap", "near ath", "200wma" stay forbidden.

## Open engineering questions (Commit 1 step 1, read-only, answered before
## any edit)

(a) HL candle endpoint: max bars per request, and whether a start/end
    time window is supported, so 1h depth can be planned as one call or
    several. Report the exact API shape from the existing
    _hl_fetch_candles implementation and its caller.
(b) Rate limiter: how the 55/min budget is enforced today (helper name,
    where the sleep/backoff lives), so the third fetch per symbol goes
    through it unchanged.
(c) Whether _weekly_from_dailies handles a partial trailing bucket, so the
    4h aggregator mirrors that behavior exactly (the forming 4h bar must
    be dropped the same way candles[:-1] drops the forming bar today).
(d) Whether scanner settings hold per-timeframe engine parameters
    (ruling 6).
(e) Pass-length estimate from the current rate-limited call count, so the
    progress bar's expectation and the abandoned threshold (5 min of
    silence) remain valid with three fetches per symbol.

## Commit sequence (each review-gated per house rules)

### Commit 1 — backend (STOP-gated: step-1 report, then quality gate)
- Constants: NOODLE_CANDLE_LIMITS['1h'], NOODLE_WINDOW_DAYS['1h'/'4h'].
- New helper _h4_from_h1(candles, limit) beside _weekly_from_dailies.
- Scan body: fetch 1h through the existing limiter, derive 4h, add
  ('4h', h4) and ('1h', h1) to the per-symbol timeframe tuple, same
  candles[:-1] treatment, same upsert, same per-symbol isolation and
  commit. Progress writes unchanged (per symbol, not per fetch).
- noodle-state route: no shape change; rows for '1h'/'4h' appear under
  timeframes; meta.window_days gains the two keys.
- Retention/retirement: confirm the existing retire-past-retention logic
  keys on (symbol, timeframe) and needs no change.
- Tests: parity fixture + test (ruling 2), aggregator unit tests (UTC
  alignment, partial-bucket drop, limit), scan-body writes five
  timeframes, route payload carries them and the two new window_days keys.
- Gate: py_compile + full pytest (1077 + new); MaxFi pins re-run in
  isolation. Push to main only after "Y".

### Commit 2 — frontend (static/trends.js only; zero backend diff)
- TIMEFRAME chips: 1 Hour / 4 Hours / 12 Hours / Daily / Weekly, single-
  select, default Daily. Order everywhere is 1H, 4H, 12H, D, W.
- Confluence tiles: five (1 / 4 / 12 / D / W), colored by flip-state, no
  outline (per polish). Marker band, sub-table (five rows, selected one
  tagged VIEW), stats strip unchanged except nothing new is added.
- Sidebar CONFLUENCE: "All 3 agree", "4H agrees", "Daily = Weekly".
- Age formatter resolution: '1h' -> D/h only, "< 1h" under an hour;
  '4h' -> D/h only, "< 4h" under four hours. Existing 12h/1d/1w rules
  unchanged. "> Nd" uses meta.window_days for the new keys.
- Gate: node --check, NUL check, forbidden strings per ruling 9, git diff
  vs HEAD scoped to trends.js, full pytest unchanged from post-Commit-1.
  Push to main after the report (frontend-only; no second STOP needed).

## Non-goals / do-not-touch

No Monthly timeframe. No new rate limiter. No engine or band-math change.
No staleness change. No confluence redefinition beyond ruling 3. No MaxFi,
ICT/cascade, or style.css changes. No change to the async scan / progress
model from 9a25bda.

## Close-out (2026-09-17)

Landed. Doc at 0acc65c; Commit 1 (backend) at c9c163b, 1077 -> 1086
tests; Commit 2 (frontend) at 76e968c, tests unchanged at 1086. Deploy-
verified: 1H and 4H tiles and sub-table rows populate after the first
post-c9c163b scan. Monthly remains parked. Ruling 4 (staleness) still
stands as v1 — revisit only if the intraday columns matter for entries.

### Step-1 findings that became design facts

- (a) _hl_fetch_candles requests a TIME WINDOW (startTime/endTime from
  ms_per_bar * limit), not a bar count. No client-side cap and no
  pagination. Live probe: a 1440-bar 1h request for BTC returned 1441
  bars spanning 60.00 days — an off-by-one in the MORE direction, not
  truncation. Ruling 8's 60-day minimum is met in one request.
- (b) The 55/min budget is a token bucket (_hl_rate_acquire) acquired
  once per logical fetch inside _hl_post, the single HL request path.
  The third fetch per symbol needed a call site, not limiter code.
- (c) _weekly_from_dailies does NOT drop a partial trailing bucket; the
  shared candles[:-1] in _run_noodle_scan_body's timeframe loop does,
  uniformly. _h4_from_h1 mirrors this: aggregate everything, drop
  nothing inside the helper.
- (d) Scanner EMA/ATR/band settings are global, not per-timeframe.
  Ruling 6's conditional never triggered; 1h/4h use the same values.
- (e) At the 250-ticker cap, steady-state pass length is ~13.6 min with
  three fetches (was ~9.1). The 5-minute "abandoned" check is idle time
  since the last per-symbol updated_ts write, not total pass time, so it
  is unaffected. Progress writes stayed per-symbol.

### Learnings not in the rulings

- Parity test scope: the captured 1h fixture's first 4h bucket holds
  only 1 of 4 bars (fetch window start is not 4h-aligned) and its last
  holds 3 of 4 (forming bar trimmed). Both diverge from HL's native 4h
  by construction. The parity test therefore compares only buckets
  built from exactly 4 contributing 1h bars — 49 of 49 match for BTC
  and ETH. The aggregator was never adjusted to pass. Do not "fix" this
  by widening the comparison.
- Fixtures: tests/fixtures/noodle_h1_{btc,eth}.json and
  noodle_h4_native_{btc,eth}.json, deliberately separate from the
  ICT/cascade fixtures (btc_h1_mar2026.json, btc_h4_feb2026.json) to
  avoid coupling test suites.
- Depth guard (ruling 8, permanent): after the off-by-one slice, if
  fewer than NOODLE_CANDLE_LIMITS['1h'] bars were returned, the scan
  prints "[noodle-scan] {symbol}: 1h depth short - requested=... 
  returned=... depth_days=..." and continues. Log-only by decision —
  never counted in errors, never surfaced in the API/UI. A young symbol
  with less than 60 days of history will legitimately trigger it.
- Retention: the retire-past-retention DELETE is age-only (computed_at),
  with no timeframe filter; 1h/4h rows retire by the same rule with no
  change. noodle_state has UNIQUE(symbol, timeframe) and no CHECK on
  timeframe values.
- Route: no code change was needed for 1h/4h rows or the two new
  meta.window_days keys — both flow through existing generic code.
- Frontend: TRENDS_TIMEFRAMES drives chips, tiles, and sub-table rows in
  one place. Absent 1h/4h rows (pre-first-scan) render neutral via the
  pre-existing `row.timeframes[tf] || {}` pattern; nothing new was
  invented for it. "4H agrees" uses an explicit presence check on the
  4h row and fails closed. The '1h' age formatter shares the existing
  '12h' branch; '4h' has its own branch with a "< 4h" floor. The 1h
  "< 1h" floor was not separately verified on deploy.
- Constants: NOODLE_CANDLE_LIMITS['1h'] = 1440;
  NOODLE_WINDOW_DAYS['1h'] = NOODLE_WINDOW_DAYS['4h'] = 60. No
  NOODLE_CANDLE_LIMITS['4h'] — 4h is derived.
