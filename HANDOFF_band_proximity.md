# HANDOFF — Band Proximity ("about to flip") for the Trends page

Rulings locked 2026-09-17 after the intraday close-out. Baseline at
lock: main @ 6398a128c305c8e42cb848d3c831623a408cf5f4, 1086 tests. Parent docs: HANDOFF_ma_band_scanner.md
(engine, fetch shape, settings keys), HANDOFF_trends_restyle.md
(Bullmania page, rulings, amendments, parked list), and
HANDOFF_intraday_timeframes.md (1h/4h, five-timeframe row shape). This
doc un-parks "proximity" from the restyle doc's v2 list under its own
definition; market-cap framing is NOT revived.

## Purpose

Surface how close each (symbol, timeframe) row is to flipping its MA-band
state, so a fresh leg can be entered before the flip prints rather than
after. This is a composable filter and a sortable column, not a signal:
near-band price is noisy by nature (the band's hysteresis exists for that
reason), and the follow-on workstream (flip quality per token) is what
separates a flip worth acting on from a chop flipper. No preset, no
alert, no ranking in v1.

## Rulings (locked, do not reopen)

1. Scope = PER TIMEFRAME. Proximity is computed and stored for every
   (symbol, timeframe) row, all five timeframes, and displayed for the
   selected timeframe like every other field. No Daily-only special case.
2. Metric = SIGNED distance-to-flip, in percent of last close:
   dist_to_flip_pct = (flip_edge - last_close) / last_close * 100, where
   flip_edge = the band's upper edge when the row's state is BEARISH and
   the lower edge when BULLISH. Positive means price sits below the edge
   that would flip it bullish; negative means price sits above the edge
   that would flip it bearish. A sign that disagrees with the state
   (BEARISH row with a negative value, or the reverse) means price is
   already through the band and the flip is pending the engine's
   confirmation — that is meaningful and is displayed as-is, never
   clamped. NULL when the state is unknown/neutral or the band is
   unavailable; NULL renders as "—" and never passes the filter.
3. Engine UNTOUCHED: no change to band math, hysteresis, parameters, or
   flip-state semantics. If compute_noodle_state does not already expose
   the band edges it computed, they are exposed ADDITIVELY (extra keys on
   its return, existing keys unchanged, existing tests unchanged).
4. Storage = persist the INPUTS, derive the metric at read time:
   noodle_state gains nullable REAL columns for the band edges and, only
   if not already stored, the last close used by the engine — via the
   codebase's existing add-column migration pattern. dist_to_flip_pct is
   computed in the noodle-state route from those columns, not stored, so
   the sign convention lives in exactly one place and the same columns
   serve the flip-quality workstream later.
5. Threshold = sidebar filter "Near flip" with a dropdown 1 / 2 / 3 / 5
   (percent), default 2, judgment-set like the crash badge. Pass = the
   ABSOLUTE value of dist_to_flip_pct is below the threshold (direction
   is read from the sign and the state chip, not from the filter). Off
   by default. Plus a sortable "To flip" column showing the signed value
   at one decimal with its sign.
6. No "Early entry" preset in v1. Filters stay composable (Near flip +
   TIMEFRAME chip + "4H agrees" + the rest). Presets are earned by the
   trade log, not guessed in the UI.
7. Staleness UNCHANGED: the value is as of the last closed candle at
   scan time under the existing 6h rule. A "near" reading can be through
   the band by the time it is viewed; that is a chart check, not a
   feature. No new copy or badge for this.
8. Forbidden strings unchanged from ruling 9 of the intraday doc:
   "monthly", "market cap", "near ath", "200wma".

## Open engineering questions (Commit 1 step 1, read-only, answered before
## any edit)

(a) What compute_noodle_state returns today: does its result carry the
    upper/lower band values (and the close it evaluated), or only the
    state and flip metadata? Exact return keys with citation.
(b) noodle_state columns today (exact CREATE/ALTER citations): is a
    last-close already persisted (the "% since flip" field implies a
    reference price — confirm what it is and whether it is the last
    close or the flip price), so ruling 4 adds two columns or three.
(c) The existing add-column migration pattern: cite the precedent from
    the restyle's volume/alignment fields and confirm it is idempotent
    on an already-migrated DB.
(d) Frontend: how the "Time since flip" sidebar dropdown and the
    sortable columns in TrendsTable are wired, so "Near flip" and
    "To flip" follow the same two patterns with no new UI machinery.
(e) Where per-row null-handling lives on the page (the `|| {}` pattern
    from the intraday work), so NULL proximity renders "—" through the
    existing path.

## Commit sequence (each review-gated per house rules)

### Commit 1 — backend (STOP-gated: step-1 report, then quality gate)
- Engine: additive return keys only if (a) says they are missing.
- Migration: nullable REAL columns per ruling 4 via the (c) pattern.
- Scan body: persist band edges (and last close if needed) in the same
  per-symbol upsert; no new fetch, no new limiter use, progress writes
  unchanged.
- Route: emit dist_to_flip_pct per timeframe row per ruling 2, NULL when
  inputs are missing; no other shape change.
- Tests: sign convention (BEARISH below upper -> positive; BULLISH above
  lower -> negative; through-band cases keep their sign), NULL on missing
  inputs, migration idempotence, scan-body persists the new columns for
  all five timeframes, route payload carries the field.
- Gate: py_compile + full pytest (1086 + new); MaxFi pins in isolation.
  Push to main only after "Y".

### Commit 2 — frontend (static/trends.js only; zero backend diff)
- "To flip" sortable column (signed, one decimal, "—" for NULL).
- Sidebar "Near flip" toggle + dropdown 1/2/3/5, default 2, off by
  default; pass = abs(value) < threshold; NULL never passes.
- No preset, no badge, no copy about staleness.
- Gate: node --check, NUL check, forbidden strings per ruling 8, diff
  scoped to trends.js, pytest unchanged. Push after the report.

## Non-goals / do-not-touch

No engine math or parameter change. No new timeframe. No preset, alert,
or ranking. No market-cap or ATH framing. No staleness change. No
flip-quality or relative-strength work (separate handoffs). No MaxFi,
ICT/cascade, nav, or style.css changes.

## Commit 1 step-1 findings of record (2026-09-17)

(i) Band edges pre-existed in the base CREATE TABLE
    (src/storage/portfolio_db.py:init_db's noodle_state statement) and
    were already populated per timeframe, before this workstream, by
    _run_noodle_scan_body's own INSERT (result['upper_band'] /
    result['lower_band'] from compute_noodle_state, written for every
    one of a symbol's five timeframe rows on every scan pass).

(ii) The existing `price` column is HL mark/mid (web_portfolio.py:
     _hl_fetch_top_volume's markPx/midPx read), set once per symbol
     before the five-timeframe loop and shared identically across all
     five rows. It is not a candle close and must never be used as
     ruling 2's last_close.

(iii) Therefore ruling 4 resolved to exactly ONE new column,
      last_close REAL, sourced in the scan body from
      closed[-1]['close'] with an empty-list guard
      (last_close = closed[-1]['close'] if closed else None). Engine
      (src/engines/noodle_bands.py) untouched - zero diff.

(iv) Note of record: "% since flip" on the Trends page is anchored to
     `price` (mark) while "To flip" is anchored to last_close (closed
     candle) - this is by design (proximity must share the band's own
     basis or the sign semantics break). Do not later "unify" them onto
     one price.

(v) Test-fixture finding: the suite's noodle_db fixture
    (tests/test_noodle_auto_refresh.py) carries a hand-rolled
    noodle_state schema literal (NOODLE_STATE_SCHEMA), separate from
    src/storage/portfolio_db.py:init_db's real schema. It must gain
    every new column alongside the migrations list, by hand, or every
    scan-body/route test sharing that fixture breaks with
    "no column named <x>". Any future noodle_state column add touches
    that fixture too (tests/test_noodle_band_proximity.py's own
    noodle_db fixture, added this commit, duplicates the same literal
    for the same reason - no test file in this suite imports fixtures
    from another).

## Commit 2 landing (2026-09-18)

Commit 2 (frontend, static/trends.js: "To flip" column + "Near flip"
sidebar filter) SHA: 4faf972 - "trends.js: add To Flip column + Near Flip
sidebar filter (band-proximity Commit 2)".

The through-band "pending confirmation" case described in ruling 2 (a
sign that disagrees with the state) is UNREACHABLE in production: the
scan body only ever evaluates closed candles (candles[:-1] before
compute_noodle_state runs), and a closed bar whose close is already
through the band is exactly the case compute_noodle_state's own
crossover/crossunder walk classifies as a flip on that bar - the state
recorded for that timeframe changes together with last_close, so the
disagreeing-sign combination ruling 2 describes cannot arise from
real scan output. No "pending confirmation" UI was built - confirmed
against production this session, not re-derived.

The mark-price-vs-last-close distinction is already recorded at item
(iv) above (`price` for "% since flip", `last_close` for "To flip") -
not duplicated here.
