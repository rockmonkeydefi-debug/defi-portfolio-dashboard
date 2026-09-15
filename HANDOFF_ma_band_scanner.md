# HANDOFF — MA-Band Trend Scanner ("Noodle Scanner")

Design locked 2026-09-14 (chat session). Baseline at lock: main @ 732b6d6,
1023 tests. Step-1 read-only discovery completed and independently verified
against main in-chat. This doc is the contract for the implementation chats.

## Purpose and strategy context

A second scanner surface, independent of the existing ICT/cascade scanner. It
ports the TradingView indicator "RM Money Noodle v3" across the Hyperliquid
perp universe on three timeframes (12h / 1d / 1w) and renders a view-only page
of per-token trend state. Strategy role: candidate feed for Glenn's ~5-position
spot book (entries timed separately; this page only surfaces trend flips).
It makes directional trend calls BY DESIGN. The MaxFi LP advisor's
"reactive-only, no directional TA" lock (Sep 9) applies to the advisor
subsystem only — neither subsystem's rules leak into the other.

## Indicator spec (port target — replicate verbatim, do not "improve")

Inputs (canonical, from Glenn's live TradingView settings, NOT script defaults):
  fast EMA 12, medium EMA 21, slow/basis EMA 25, band multiplier 0.01,
  ATR length 20, use_atr ON.
Per (symbol, timeframe) series of candles:
  ema_f  = EMA(close, 12);  ema_m = EMA(close, 21);  ema_s = EMA(close, 25)
  atr    = RMA-smoothed ATR(20)   [Wilder smoothing — matches Pine ta.atr]
  offset = use_atr ? atr * band_multiplier * 40 : ema_s * band_multiplier
           (the *40 constant is a quirk of the source script — replicate
            exactly or nothing will match Glenn's chart)
  upper  = ema_s + offset;  lower = ema_s - offset
Signal events (Pine semantics):
  crossover(close, upper)  -> BULLISH flip
  crossunder(close, lower) -> BEARISH flip
Trend state is HYSTERETIC: state = direction of the most recent flip, and it
persists while price trades back inside the band. The band interior is a dead
zone, not a state. Flip metadata captured at each flip: timestamp and close
price (drives time-since-flip and %-change-since-flip columns).
Secondary metric: EMA alignment score 0-3 per side
  bull = (ema_f>ema_m) + (ema_f>ema_s) + (ema_m>ema_s); bear = mirrored.

Flip-lookback boundary (v1 documented default): if no crossing exists within
the fetched candle window but the current close sits OUTSIDE the band, state =
that side with flip age displayed as "> window"; if price sits INSIDE the band
with no locatable flip, display WARMUP. Revisitable later.

WARMUP is a FIRST-CLASS state, not an edge case: any (symbol, timeframe) whose
history cannot converge EMA(25)+ATR(20) (weekly needs roughly 100+ weekly bars;
many newer HL listings simply do not have them) renders WARMUP until it ages in.

## Locked architecture (option A of the design session)

1. Pure engine module: src/engines/noodle_bands.py — cascade_composer
   precedent. Pure functions over candle lists (list-of-dicts as returned by
   _hl_fetch_candles). No Flask, no network, no SQLite. Contents: generic
   EMA(period), RMA-based ATR(period), band computation, hysteresis walk-back
   returning (state, flip_ts, flip_price, alignment_bull, alignment_bear).
   DO NOT reuse _ict_atr (it is SMA-of-TR — will not match TradingView) or
   _ict_ema20 (hardcoded 20-period). Write both fresh, generic, in the module.
2. Results persistence: new table noodle_state in src/storage/portfolio_db.py
   (mirror cascade_state's shape): symbol TEXT, timeframe TEXT, state TEXT
   (BULLISH|BEARISH|WARMUP), flip_ts, flip_price, alignment fields, ema/band
   snapshot values as useful for tooltips, computed_at. PK (symbol, timeframe).
   RAW CANDLES ARE NOT PERSISTED in v1 — candles are live-fetched per pass,
   as everywhere else in the codebase. (Candle store = designated v2, below.)
3. Fetch shape (MANDATORY): per symbol, TWO HL calls — 12h native and 1d
   native; weekly DERIVED from the same daily fetch via _weekly_from_dailies
   (Monday-realigned; matches TV crypto weekly). Never call
   _hl_fetch_candles('1w', ...) per-symbol in the scan loop — it re-fetches
   dailies internally and burns 50% more rate budget for nothing. Reuse
   _hl_resolve_coin, _hl_fetch_candles, _weekly_from_dailies,
   _hl_fetch_top_volume. All HL traffic already routes through _hl_post's
   global 55/min token bucket — do not add a second limiter.
4. Universe: _hl_fetch_top_volume(n=None, limit=None) enumeration, sliced to
   the new noodle_max_tickers setting. Independent of the ICT scanner's
   scan_max_tickers — the two universes are deliberately uncoupled.
5. Settings (flat keys in _SCANNER_SETTINGS_DEFAULTS + explicit validation
   stanzas in api_scanner_settings_put, per house pattern; per-timeframe
   overrides later via the _1w/_1d/_12h suffix precedent, NOT nested dicts):
     noodle_ema_fast 12 | noodle_ema_medium 21 | noodle_ema_slow 25
     noodle_atr_length 20 | noodle_band_multiplier 0.01 | noodle_use_atr true
     noodle_max_tickers 250 | noodle_staleness_hours 6
6. Refresh model (copy the _maybe_kick_metrics_auto_refresh precedent, commit
   48298dc, adapted): page GET serves persisted noodle_state rows instantly
   and NEVER blocks on a scan. On-view trigger compares MAX(computed_at)
   against noodle_staleness_hours and, when stale, spawns one daemon thread
   running an extracted _run_noodle_scan_body() (no Flask context, own DB
   connection, non-blocking global lock; concurrent trigger loses with 409).
   Manual "Refresh" button hits the same body through the same lock.
   PROGRESSIVE PERSISTENCE: each symbol's rows are written as computed, so a
   mid-pass reload shows partial fresh data. No frontend polling in v1.
   Reality note: a full pass is ~400-500 HL requests ≈ 7-9 minutes minimum on
   the shared 55/min budget, longer if the ICT scanner runs concurrently.
7. Frontend: new top-level nav entry, working name "Trends" (id 'trends') —
   NOT under the hidden 'tt' group (HIDDEN_TABS would make it unreachable).
   House conventions: React.createElement, no JSX, no build step; inline
   styles + shared tv-* classes; register via TOP_NAV_ITEMS, PHASE1_TABS,
   App.renderContent() branch, window.TrendsScreen export. v1 columns (lean):
   token, price, three per-timeframe state chips (BULLISH green / BEARISH red /
   WARMUP amber), time-since-flip and %-change-since-flip for a selected
   timeframe (default 1d), alignment score as tooltip/chip detail. Sortable,
   filterable by state. Visual style modeled on Glenn's reference screenshot
   (dark table, state pills). UI/UX visibility standards apply (contrast,
   min font sizes, visible separators).

## Parity harness (implementation gate)

Before the page ships, the engine must reproduce TradingView to acceptable
tolerance. Glenn captures, from TV at the canonical settings above: basis EMA,
upper band, lower band, and current state for 2-3 tokens per timeframe. Those
values freeze as test constants (the frozen-OB-values discipline). The harness
targets exactly the known drift risks: RMA vs SMA smoothing, EMA seeding,
weekly bar alignment. Engine commit does not merge until the harness passes.

## Commit sequence for implementation chats (each review-gated per house rules)

  Commit 1: engine module + unit tests + parity harness (pure code, no routes)
  Commit 2: noodle_state schema + settings keys/validation + scan body +
            staleness kick + routes
  Commit 3: frontend Trends page + nav registration
Direct-to-main, Railway auto-deploys; review gate = diff verified on GitHub
before the next commit builds on it.

## Explicitly out of scope for v1 (parked, in priority order)

  - Raw candle persistence + incremental fetch (collapses pass to ~1-2 min) —
    the designated v2 optimization IF pass duration hurts in practice
  - CoinGecko universe widening beyond HL + market cap column/filter
    (requires a symbol-mapping layer HL cannot provide)
  - Near-ATH / 200WMA proximity indicators
  - Telegram alerts on flips (couples to unbuilt Phase 6 alert plumbing)
  - Per-timeframe parameter overrides (config-shape ready via suffix keys)
  - Frontend auto-polling during a pass

## Non-goals / do-not-touch

No changes to the ICT/cascade scanner, its settings keys, or its routes. No
changes to any MaxFi module. No new rate limiter. No pandas dependency —
engine math is hand-rolled loops (numpy optional but not required; codebase
precedent is plain Python).
