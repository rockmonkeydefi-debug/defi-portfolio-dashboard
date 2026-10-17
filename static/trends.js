/* ===== TRENDS SCREEN (MA-band / "Noodle" scanner) — Bullmania restyle =====
   Display-only screen over GET /api/trading/scanner/noodle-state.
   Never recomputes engine math - state/flip/alignment are read straight
   off the payload; the only client-side "math" here is display-only
   derivation (time-since-flip/-alignment-change, %-since-flip, volume
   rank, confluence) over already-computed fields.

   Per HANDOFF_trends_restyle.md ruling 2, the Bullmania purple/black
   palette below is PAGE-SCOPED to this file only - no edits to
   static/style.css, every other tab keeps the app's navy theme. This
   file therefore does NOT reuse the shared tv-table/tv-btn/tv-card/
   tv-input classes for anything color-bearing (their CSS variables are
   navy-context and would visually clash) - plain elements with inline
   styles instead, plus one small page-scoped <style> block for the one
   thing inline styles can't do: a row-hover background.

   React.createElement only, no JSX, no build step - house convention. */

/* ── Bullmania palette (page-scoped; see ATOMIC STEP 2) ── */
const TRENDS_BG = '#0e0a15';
const TRENDS_PANEL_BG = '#1a1226';
const TRENDS_HEADER_BG = '#221833';
const TRENDS_BORDER = 'rgba(255,255,255,0.25)';
const TRENDS_ACCENT = '#b3164f';
const TRENDS_ACCENT_BG = 'rgba(179,22,79,0.25)';
const TRENDS_BULL = '#4ade80';
const TRENDS_BULL_BG = 'rgba(34,197,94,0.22)';
const TRENDS_BEAR = '#f87171';
const TRENDS_BEAR_BG = 'rgba(239,68,68,0.22)';
const TRENDS_NEUTRAL = '#facc15';
const TRENDS_NEUTRAL_BG = 'rgba(234,179,8,0.22)';
const TRENDS_TEXT_PRIMARY = '#f3f4f6';
const TRENDS_TEXT_SECONDARY = '#c9d1d9';
const TRENDS_ROOT_CLASS = 'trends-bullmania-root';

// Intraday-timeframes Commit 2 (HANDOFF_intraday_timeframes.md): order
// everywhere on the page is 1H, 4H, 12H, D, W. This one array drives the
// TIMEFRAME chips, the confluence tiles, and the sub-table row order -
// all three map over it directly, so this is the single site that needed
// to grow from three entries to five.
const TRENDS_TIMEFRAMES = ['1h', '4h', '12h', '1d', '1w'];
const TRENDS_TF_LABELS = { '1h': '1H', '4h': '4H', '12h': '12H', '1d': '1D', '1w': '1W' };
const TRENDS_TF_FULL_LABELS = { '1h': '1 Hour', '4h': '4 Hours', '12h': '12 Hours', '1d': 'Daily', '1w': 'Weekly' };
const TRENDS_TF_SHORT = { '1h': '1', '4h': '4', '12h': '12', '1d': 'D', '1w': 'W' };

// WARMUP's user-facing flip-state label is "Neutral" (Commit 3 ruling) -
// display-only remap. The API's literal string, internal sort ranks, and
// filter values all stay 'WARMUP' - only this label lookup changes.
// alignment_state is a SEPARATE literal value space (BULLISH|BEARISH|
// NEUTRAL|None) from the engine's own full-stack-only mapping - its own
// "Neutral" is a different concept that happens to share the word (doc
// ruling 9), kept visually distinct below: Trend chips are FILLED,
// Alignment chips are OUTLINE-ONLY.
const TRENDS_STATE_LABELS = { BULLISH: 'Bullish', BEARISH: 'Bearish', WARMUP: 'Neutral' };
const TRENDS_STATE_COLORS = {
  BULLISH: { color: TRENDS_BULL, bg: TRENDS_BULL_BG },
  BEARISH: { color: TRENDS_BEAR, bg: TRENDS_BEAR_BG },
  WARMUP:  { color: TRENDS_NEUTRAL, bg: TRENDS_NEUTRAL_BG },
};
// Judgment-set sort order (not alphabetical) - same convention as
// maxfi.js's MX_VERDICT_RANK. Bullish first, neutral middle, bearish last.
const TRENDS_STATE_RANK = { BULLISH: 0, WARMUP: 1, BEARISH: 2 };

const TRENDS_ALIGNMENT_LABELS = { BULLISH: 'Bullish', BEARISH: 'Bearish', NEUTRAL: 'Neutral' };
const TRENDS_ALIGNMENT_COLORS = { BULLISH: TRENDS_BULL, BEARISH: TRENDS_BEAR, NEUTRAL: TRENDS_NEUTRAL };
const TRENDS_ALIGNMENT_RANK = { BULLISH: 0, NEUTRAL: 1, BEARISH: 2 };

// Verbatim from the Bullmania reference (HANDOFF_trends_restyle.md).
// `seconds: null` = "Any time" (no threshold).
const TRENDS_TIME_SINCE_FLIPPED_OPTIONS = [
  { label: 'Any time', seconds: null },
  { label: '1 hour', seconds: 3600 },
  { label: '4 hours', seconds: 4 * 3600 },
  { label: '1 day', seconds: 86400 },
  { label: '2 days', seconds: 2 * 86400 },
  { label: '3 days', seconds: 3 * 86400 },
  { label: '4 days', seconds: 4 * 86400 },
  { label: '5 days', seconds: 5 * 86400 },
  { label: '6 days', seconds: 6 * 86400 },
  { label: '1 week', seconds: 7 * 86400 },
  { label: '2 weeks', seconds: 14 * 86400 },
  { label: '3 weeks', seconds: 21 * 86400 },
  { label: '1 month', seconds: 30 * 86400 },
];

// Setup 1 (Glenn's rulings, Oct 16 2026; claude/doc_paragon/
// SPEC_doc_system.md Part F): Doc's Daily Trend fast EMA (EMA 100 of 4H
// closes) has just crossed above its slow EMA (EMA 200 of 4H closes) while
// the whole Daily Trend band (between those two EMAs) still sits at or
// under the top of the Weekly Trend band (EMA 100 and EMA 200 of daily
// closes) - inside it, touching its lower edge, or below it by no more than
// TRENDS_SETUP1_MAX_GAP_PCT (top of the Daily Trend band to the bottom of
// the Weekly Trend band). Since Landing 47 the scan stores the Daily Trend
// on the 4h row and the Weekly Trend on the 1d row (doc_* fields); Landing
// 44 had used the noodle's EMA stack and bands. The recency choices are
// the TIME SINCE FLIPPED list from 1 day to 1 month.
const TRENDS_SETUP1_DAILY_TF = '4h';
const TRENDS_SETUP1_WEEKLY_TF = '1d';
const TRENDS_SETUP1_RECENCY_OPTIONS = TRENDS_TIME_SINCE_FLIPPED_OPTIONS.filter((o) => o.seconds !== null && o.seconds >= 86400);
const TRENDS_SETUP1_DEFAULT_RECENCY = '1 week';
const TRENDS_SETUP1_MAX_GAP_PCT = 10;

const TRENDS_TOP_VOLUME_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'top20', label: 'Top 20' },
  { value: 'top50', label: 'Top 50' },
  { value: 'top100', label: 'Top 100' },
];

const TRENDS_ALL_TREND_STATES = ['BULLISH', 'BEARISH', 'WARMUP'];
const TRENDS_ALL_ALIGNMENT_STATES = ['BULLISH', 'BEARISH', 'NEUTRAL'];
// ASSET CLASS (Landing 46): the route's asset_class per symbol ('crypto' |
// 'tradfi' | null, from the cached Hyperliquid market lists).
const TRENDS_ALL_ASSET_CLASSES = ['crypto', 'tradfi'];

const TRENDS_FILTER_DEFAULTS = {
  trend: new Set(TRENDS_ALL_TREND_STATES),
  alignment: new Set(TRENDS_ALL_ALIGNMENT_STATES),
  confluenceAll3: false,
  confluenceDW: false,
  confluence4H: false,
  timeSinceFlipped: 'Any time',
  topVolume: 'all',
  search: '',
  nearFlip: false,
  nearFlipThreshold: 2,
  hideChoppy: false,
  // null until first enabled - TrendsSidebar sets it to the selected TF's
  // threshold array's middle value on that transition (ruling 6: no flat
  // scale-wide default makes sense, see TRENDS_HIDE_CHOPPY_THRESHOLDS).
  hideChoppyThreshold: null,
  setup1: false,
  setup1Recency: TRENDS_SETUP1_DEFAULT_RECENCY,
  // Section ticks (Landing 45): a section filters only while ticked; its
  // settings above are kept while it is not. Near flip, Hide choppy and
  // Setup 1 use their own flags (nearFlip, hideChoppy, setup1) as the tick.
  trendOn: false,
  confluenceOn: false,
  alignmentOn: false,
  timeSinceOn: false,
  topVolumeOn: false,
  // Landing 46: ASSET CLASS, ticked like the other sections.
  assetClassOn: false,
  assetClasses: new Set(TRENDS_ALL_ASSET_CLASSES),
};

// Band-proximity Commit 2: judgment-set threshold choices for the "Near
// flip" sidebar filter, same style as the crash badge's own threshold set.
const TRENDS_NEAR_FLIP_THRESHOLDS = [1, 2, 3, 5];

// Flip quality Path A (HANDOFF_flip_quality.md ruling 5/6) - v1
// calibration constants (Sep 18 2026) for the "Hide choppy" threshold
// dropdown. Derived from a 40-symbol live-distribution pull, NOT the full
// scanned universe (~237+ symbols) - revisit if full-universe behavior
// looks off once this is live for a while. Unlike Near Flip's single
// flat 1/2/3/5% scale, raw flip counts scale with each timeframe's
// window length in bars (~200 at 1w vs ~1440 at 1h), so the dropdown's
// own OPTIONS change with the selected TIMEFRAME chip - judgment-set,
// not derived, same as the crash badge's own thresholds.
const TRENDS_HIDE_CHOPPY_THRESHOLDS = {
  '1w': [1, 2, 3],
  '1d': [15, 25, 35],
  '12h': [15, 25, 35],
  '4h': [20, 30, 40],
  '1h': [80, 120, 160],
};

// Sidebar tooltips (Landing 45). The section Glenn named TREND CONFLUENCE
// (16:05) is the flip-state agreement of _trendsConfluence, not alignment. Glenn asked (Oct 16) for tooltips that
// explain each sidebar item's purpose and use, then rewrote the text himself
// (15:41) as one tip per section, with separate tips for the three
// Confluence chips and the two limit dropdowns; chat corrected four facts
// in it (15:45 rulings: the Trend wording, 12H history, Top by volume, an
// H4 typo). Every sentence is checked against this file and the scan's
// constants (NOODLE_WINDOW_DAYS, NOODLE_CANDLE_LIMITS, noodle_max_tickers
// 250, noodle_staleness_hours 6 in web_portfolio.py) - change both together.
const TRENDS_TIPS = {
  assetClass: {
    title: 'Asset class',
    body: "Crypto: perps on Hyperliquid's main exchange. TradFi: perps on its xyz exchange (stocks, indexes and other traditional markets). The scan drops the xyz: prefix, so the class comes from Hyperliquid's market lists; a name listed on both counts as crypto. A coin on neither list (for example, delisted) shows only with both chips on. Click to include or exclude.",
    use: 'Use it to scan only crypto, only TradFi, or both.',
  },
  setup1: {
    title: 'Daily cross under Weekly',
    body: 'Shows coins whose Daily Trend just turned up under the Weekly Trend. The Daily Trend is EMA 100 (fast) and EMA 200 (slow) of 4H closes; the Weekly Trend is EMA 100 and EMA 200 of daily closes. A coin shows when the Daily Trend fast EMA crossed above its slow EMA within the window and the whole Daily Trend band (between its two EMAs) sits at or under the top of the Weekly Trend band: inside it, touching its lower edge, or below it by ' + TRENDS_SETUP1_MAX_GAP_PCT + '% or less (top of the Daily Trend to the bottom of the Weekly Trend). A tag under each coin says which and how long ago the cross was. Closed candles only. It needs about 34 days of 4H history and 200 days of daily history, so newer coins never show. It reads the same whatever timeframe is selected, and combines with every other filter.',
    use: 'Use it to find coins starting to turn up from under the Weekly Trend; the cross age in the tag shows which turns are fresh.',
  },
  setup1Recency: {
    title: 'Crossed within',
    body: 'How recently the Daily Trend fast EMA (EMA 100 of 4H closes) must have crossed above its slow EMA (EMA 200 of 4H closes) for a Daily cross under Weekly to include the coin. Counted from the open of the 4H candle whose close made the cross. A fast EMA that has stayed above the slow one for all of the scanned 4H history (about 83 days) never counts.',
    use: 'Use a short window for fresh turns, a longer one to review the last few weeks.',
  },
  trend: {
    title: 'Trend',
    body: "Bullish: the last flip on that TF was a candle closing above the upper band. Bearish: the last flip was a close below the lower band. Closes back inside the band don't change either. Neutral: no flip in the scan's window with price inside the band, or too little history. Click to include or exclude. With all three Trend chips on, nothing is filtered.",
    use: 'Use it with a timeframe chip.',
  },
  confAll3: {
    title: 'All 3 agree',
    body: 'H12, Daily and Weekly trends are all bullish or all bearish (Neutral never counts). Ignores the TF chips. With several Trend Confluence chips on, a coin needs to match only one of them.',
    use: 'Use it to find coins trending the same way on every higher timeframe.',
  },
  conf4H: {
    title: '4H agrees',
    body: 'All 3 agree, and the H4 trend agrees too. A coin with no H4 reading is left out. Ignores the TF chips.',
  },
  confDW: {
    title: 'Daily = Weekly',
    body: 'Daily and Weekly trends point the same way, both bullish or both bearish. H12 may disagree. Ignores the TF chips.',
  },
  alignment: {
    title: 'Alignment (EMA)',
    body: 'All the noodle EMAs on the selected TF are fully stacked up (Bullish: 12 above 21 above 28) or down (Bearish). Neutral means the EMAs are tangled. This is separate from the Trend chips: the trend comes from closes through the band, the alignment from the order of the EMAs. With all three Alignment chips on, nothing is filtered.',
    use: 'Set the Trend and Alignment chips the same (Bullish or Bearish) to require both trend and alignment to agree.',
  },
  timeSinceFlipped: {
    title: 'Time since flipped',
    body: "Coins whose trend on the selected TF flipped within the chosen time. Any time turns it off. A flip older than the scan's window (shown as > Nd) passes only Any time, and coins with no flip are hidden while a time is chosen.",
    use: 'Use it to find fresh flips.',
  },
  nearFlip: {
    title: 'Near flip',
    body: 'Coins whose last closed price is within the chosen distance of the band edge that would flip their trend. A coin that is bearish now is measured to the upper edge, since only a close above it turns it bullish; a coin that is bullish now is measured to the lower edge, since only a close below it turns it bearish. Neutral coins never pass. Reads the selected TF, from the same number as the TO FLIP column.',
    use: 'Use it to spot coins about to flip.',
  },
  nearFlipThreshold: {
    title: 'Near flip distance',
    body: 'Distance to the band that counts as near, as a % of the last candle close. Smaller means closer to the edge. Only used while Near flip is on.',
  },
  hideChoppy: {
    title: 'Hide choppy',
    body: "Hides coins that flipped too often on the selected TF within the scan's window (60 days on 1H and 4H, 150 days on 12H, about 300 days on Daily, about 41 weeks on Weekly). Frequent flips mean price keeps crossing the band instead of respecting it.",
    use: 'Use it to filter out choppy coins and keep ones that trend cleanly.',
  },
  hideChoppyThreshold: {
    title: 'Hide choppy limit',
    body: 'The most flips a coin can have and still show. The choices change with the timeframe, because longer windows hold more flips. Switching to a timeframe whose choices do not include the current limit resets it to the middle choice. Only used while Hide choppy is on.',
    use: 'Lower it to be stricter.',
  },
  timeframe: {
    title: 'Timeframe',
    body: 'Sets the TF for the trend columns in the table and for the Trend, Alignment, Time since flipped, Near flip and Hide choppy filters. Trend Confluence and Setups ignore it. Filters on closed candles only. H1 and H4 keep 60 days of candles, H12 150 days, D about 300 days, W about 41 weeks.',
  },
  topVolume: {
    title: 'Top by volume',
    body: 'Keeps only the top 20, 50 or 100 coins by 24-hour volume among those passing the other filters; All turns it off. The scan itself covers the 250 Hyperliquid perps with the most 24-hour volume.',
    use: 'Use it to focus on the most liquid markets.',
  },
  refresh: {
    title: 'Refresh',
    body: 'Starts a new scan of the 250 Hyperliquid perps with the most 24-hour volume, on all five timeframes, from closed candles. A scan also starts by itself when Trends opens and the data is more than 6 hours old.',
    use: 'Use it after a candle closes on the timeframe you are watching.',
  },
};

/* ── pure helpers ── */

// Unbounded flip/alignment age label (Commit 3: async scan). meta.window_days
// (from GET /noodle-state's top-level meta) gives the real fetched-window
// length per timeframe now that the backend exposes it as a named constant
// - "> Nd" replaces the old "> window" wherever it's available. Falls back
// to the old literal if meta hasn't loaded yet (first paint) or is absent
// for any other reason - never a broken or missing cell.
function _trendsWindowLabel(windowDays, timeframe) {
  const days = windowDays && windowDays[timeframe];
  return typeof days === 'number' ? ('> ' + days + 'd') : '> window';
}

function _trendsExtractErr(e) {
  let msg = (e && e.message) ? e.message : String(e);
  try {
    const j = JSON.parse(msg);
    if (j) msg = j.detail || j.error || msg;
  } catch (e2) {}
  return msg;
}

// Granular age formatter - a duration in seconds in, "7M 2W 1D" out (M =
// 30-day month, W = 7-day week, per the doc). Floors to the given
// timeframe's own candle resolution rather than always going down to the
// minute: '12h'/'1h' keep hours (no minutes) and show "< 1h" below that;
// '4h' keeps hours too, but shows "< 4h" below that (its own candle
// resolution, per Commit 2/HANDOFF_intraday_timeframes.md ruling 6);
// '1d'/'1w' (and any other/unrecognized timeframe, as a safe default)
// keep only days and coarser, showing "< 1D" below that - there is no
// point implying a Daily or Weekly flip's age to hour/minute precision
// when the candle itself only resolves to a day. ALL zero-valued units
// are dropped (not just leading ones), e.g. a zero week count between a
// nonzero month and day count is omitted rather than printed as zero.
function _trendsFmtAge(seconds, timeframe) {
  if (seconds === null || seconds === undefined || isNaN(seconds)) return null;
  let s = Math.max(0, Math.floor(seconds));
  const months = Math.floor(s / (30 * 86400)); s -= months * 30 * 86400;
  const weeks = Math.floor(s / (7 * 86400));   s -= weeks * 7 * 86400;
  const days = Math.floor(s / 86400);          s -= days * 86400;
  const hours = Math.floor(s / 3600);          s -= hours * 3600;

  if (timeframe === '12h' || timeframe === '1h') {
    if (months === 0 && weeks === 0 && days === 0 && hours === 0) return '< 1h';
    return [[months, 'M'], [weeks, 'W'], [days, 'D'], [hours, 'h']]
      .filter(([v]) => v > 0).map(([v, u]) => v + u).join(' ');
  }
  if (timeframe === '4h') {
    if (months === 0 && weeks === 0 && days === 0 && hours < 4) return '< 4h';
    return [[months, 'M'], [weeks, 'W'], [days, 'D'], [hours, 'h']]
      .filter(([v]) => v > 0).map(([v, u]) => v + u).join(' ');
  }
  // '1d' / '1w' / anything else: floor to whole days.
  if (months === 0 && weeks === 0 && days === 0) return '< 1D';
  return [[months, 'M'], [weeks, 'W'], [days, 'D']]
    .filter(([v]) => v > 0).map(([v, u]) => v + u).join(' ');
}

// Band-proximity Commit 2 (HANDOFF_band_proximity.md) - one-decimal signed
// formatter for dist_to_flip_pct. Deliberately NOT window.fmtPct, which is
// two-decimal - this column's own spec is one-decimal. Only ever called
// from behind the usual `typeof x === 'number' ? ... : '—'` guard already
// used for every other nullable numeric cell in this file. Reused as-is
// for rs_vs_btc_pct (RS vs BTC Commit 2, HANDOFF_rs_vs_btc.md ruling 7) -
// same signed one-decimal percentage shape, no need for a second formatter.
function _trendsFmtToFlip(value) {
  const sign = value >= 0 ? '+' : '';
  return sign + value.toFixed(1) + '%';
}

function _trendsAgeFromTs(nowMs, epochSeconds) {
  if (typeof epochSeconds !== 'number') return null;
  return Math.max(0, Math.floor(nowMs / 1000) - epochSeconds);
}

function _trendsFlipLabel(state) {
  return TRENDS_STATE_LABELS[state] || state;
}

function _trendsPctSinceFlip(currentPrice, flipPrice) {
  if (typeof currentPrice !== 'number' || typeof flipPrice !== 'number' || flipPrice === 0) return null;
  return ((currentPrice - flipPrice) / flipPrice) * 100;
}

// {all3, dw, fourHAgrees} from the timeframes' own flip-states. all3
// requires 12h/1d/1w all identical AND non-WARMUP; dw requires
// Daily==Weekly, both non-WARMUP (doc ruling A4/A5). Both stay defined
// over 12h/1d/1w ONLY (ruling 3) - 1h is excluded from every confluence
// definition, and this function is not the place 4h logic gets folded
// into either of those two fields.
//
// fourHAgrees (Commit 2, HANDOFF_intraday_timeframes.md Step 5) is a
// SEPARATE definition layered on top: the 12h/1d/1w trio must already
// agree (all3), AND the 4h row's own flip-state must be present and
// match that shared state. The presence check is explicit - a missing
// 4h row (e.g. before the first post-c9c163b scan has run for this
// symbol) fails closed, it never passes just because all3 is true.
function _trendsConfluence(rowTimeframes) {
  const s12 = (rowTimeframes['12h'] || {}).state;
  const sD = (rowTimeframes['1d'] || {}).state;
  const sW = (rowTimeframes['1w'] || {}).state;
  const directional = (s) => s === 'BULLISH' || s === 'BEARISH';
  const all3 = directional(s12) && directional(sD) && directional(sW) && s12 === sD && sD === sW;
  const dw = directional(sD) && directional(sW) && sD === sW;

  const tf4 = rowTimeframes['4h'];
  const has4h = !!tf4 && typeof tf4.state === 'string';
  const fourHAgrees = all3 && has4h && directional(tf4.state) && tf4.state === s12;

  return { all3, dw, fourHAgrees };
}

// Generic "all selected = no filter" multi-select check (TREND/ALIGNMENT
// sections): if every possible value is selected, nothing is filtered -
// including a row whose value is null/undefined (too-short history),
// which would otherwise never match any specific chip in the Set.
function _trendsPassesMultiFilter(selectedSet, allValues, value) {
  if (selectedSet.size >= allValues.length) return true;
  return selectedSet.has(value);
}

function _trendsPassesTimeSinceFlipped(tf, optionLabel, nowMs) {
  const opt = TRENDS_TIME_SINCE_FLIPPED_OPTIONS.find((o) => o.label === optionLabel);
  if (!opt || opt.seconds === null) return true;               // "Any time"
  if (tf.flip_age_unbounded === true) return false;             // "> window" passes only Any time
  if (typeof tf.flip_ts !== 'number') return false;             // no flip at all
  return _trendsAgeFromTs(nowMs, tf.flip_ts) <= opt.seconds;
}

// Band-proximity Commit 2, ruling 5: "Near flip" passes only when
// dist_to_flip_pct is a real number AND its absolute value is under the
// threshold - a null/missing value (state not BULLISH/BEARISH, or a
// missing input) never passes, matching ruling 2's "NULL... never passes
// the filter" instruction exactly.
function _trendsPassesNearFlip(tf, enabled, threshold) {
  if (!enabled) return true;
  if (typeof tf.dist_to_flip_pct !== 'number') return false;
  return Math.abs(tf.dist_to_flip_pct) < threshold;
}

// Flip quality Path A Commit 2 (HANDOFF_flip_quality.md ruling 5): "Hide
// choppy" passes rows whose flip_count_window is at or below the
// threshold. A null flip_count_window (insufficient history) fails -
// this file's only other active filters (_trendsPassesNearFlip,
// _trendsPassesTimeSinceFlipped, and the TREND/ALIGNMENT multi-filters
// once narrowed) all fail-closed on a missing measurement, so this
// mirrors that convention rather than inventing a different rule.
function _trendsPassesHideChoppy(tf, enabled, threshold) {
  if (!enabled) return true;
  if (typeof tf.flip_count_window !== 'number') return false;
  return tf.flip_count_window <= threshold;
}

// Setup 1 (see TRENDS_SETUP1_*): {position: 'inside' | 'touching' | 'below',
// gapPct, ageSeconds} when the row qualifies, else null. Reads only the 4h
// row (Daily Trend) and the 1d row (Weekly Trend), whatever timeframe the
// table is showing. Fails closed on anything missing: no 4h / 1d row, EMAs
// not there yet (under 200 bars, or a row the scan has not refreshed since
// Landing 47), or a cross age that is unknown or outside the window -
// including doc_cross_unbounded (the fast EMA has been above the slow one
// for all the scanned history, so it did not just cross). The age runs
// from the open of the 4H bar whose close made the cross (doc_cross_ts),
// the same open-of-bar clock as the flip ages.
function _trendsSetup1(rowTimeframes, recencyLabel, nowMs) {
  const d = rowTimeframes[TRENDS_SETUP1_DAILY_TF];
  const w = rowTimeframes[TRENDS_SETUP1_WEEKLY_TF];
  if (!d || !w || d.doc_cross_state !== 'BULLISH') return null;
  const opt = TRENDS_SETUP1_RECENCY_OPTIONS.find((o) => o.label === recencyLabel)
    || TRENDS_SETUP1_RECENCY_OPTIONS.find((o) => o.label === TRENDS_SETUP1_DEFAULT_RECENCY);
  if (d.doc_cross_unbounded === true || typeof d.doc_cross_ts !== 'number') return null;
  const ageSeconds = _trendsAgeFromTs(nowMs, d.doc_cross_ts);
  if (ageSeconds > opt.seconds) return null;
  const emas = [d.doc_ema_fast, d.doc_ema_slow, w.doc_ema_fast, w.doc_ema_slow];
  if (!emas.every((x) => typeof x === 'number' && isFinite(x) && x > 0)) return null;
  const dailyTop = Math.max(d.doc_ema_fast, d.doc_ema_slow);
  const dailyBottom = Math.min(d.doc_ema_fast, d.doc_ema_slow);
  const weeklyTop = Math.max(w.doc_ema_fast, w.doc_ema_slow);
  const weeklyBottom = Math.min(w.doc_ema_fast, w.doc_ema_slow);
  if (dailyTop > weeklyTop) return null;                  // the Daily Trend reaches above the Weekly Trend
  if (dailyBottom >= weeklyBottom) return { position: 'inside', gapPct: 0, ageSeconds };
  if (dailyTop >= weeklyBottom) return { position: 'touching', gapPct: 0, ageSeconds };
  const gapPct = (weeklyBottom / dailyTop - 1) * 100;
  return gapPct <= TRENDS_SETUP1_MAX_GAP_PCT ? { position: 'below', gapPct, ageSeconds } : null;
}

function _trendsSetup1Label(s1) {
  const where = s1.position === 'inside' ? 'Inside weekly trend'
    : s1.position === 'touching' ? 'Touching weekly trend'
    : s1.gapPct.toFixed(1) + '% below weekly trend';
  const age = _trendsFmtAge(s1.ageSeconds, TRENDS_SETUP1_DAILY_TF);
  return age === null ? where : where + ' · crossed ' + age + ' ago';
}

// Every sidebar filter but SETUPS follows the selected timeframe; Setup 1
// always reads the 4h and 1d rows (Daily and Weekly Trend) and is ANDed with the rest, so narrowing TREND or
// ALIGNMENT while viewing another timeframe can hide its matches. A section
// applies only while its tick is on (TRENDS_FILTER_DEFAULTS, Landing 45).
// Top by volume is applied after this, in TrendsScreen.
function _trendsPassesSearchAndSidebar(row, filters, selectedTf, nowMs) {
  const tf = row.timeframes[selectedTf] || {};
  if (filters.assetClassOn && !_trendsPassesMultiFilter(filters.assetClasses, TRENDS_ALL_ASSET_CLASSES, row.asset_class)) return false;
  if (filters.trendOn && !_trendsPassesMultiFilter(filters.trend, TRENDS_ALL_TREND_STATES, tf.state)) return false;
  if (filters.alignmentOn && !_trendsPassesMultiFilter(filters.alignment, TRENDS_ALL_ALIGNMENT_STATES, tf.alignment_state)) return false;
  if (filters.confluenceOn && (filters.confluenceAll3 || filters.confluenceDW || filters.confluence4H)) {
    const conf = _trendsConfluence(row.timeframes);
    const matchesAny3 = filters.confluenceAll3 && conf.all3;
    const matchesDW = filters.confluenceDW && conf.dw;
    const matches4H = filters.confluence4H && conf.fourHAgrees;
    if (!matchesAny3 && !matchesDW && !matches4H) return false;
  }
  if (filters.setup1 && !_trendsSetup1(row.timeframes, filters.setup1Recency, nowMs)) return false;
  if (filters.timeSinceOn && !_trendsPassesTimeSinceFlipped(tf, filters.timeSinceFlipped, nowMs)) return false;
  if (!_trendsPassesNearFlip(tf, filters.nearFlip, filters.nearFlipThreshold)) return false;
  if (!_trendsPassesHideChoppy(tf, filters.hideChoppy, filters.hideChoppyThreshold)) return false;
  const q = filters.search.trim().toUpperCase();
  if (q && row.symbol.toUpperCase().indexOf(q) === -1) return false;
  return true;
}

const TRENDS_TOP_VOLUME_N = { top20: 20, top50: 50, top100: 100 };

function _trendsSortValue(row, key, selectedTf, rankMap) {
  const tf = row.timeframes[selectedTf] || {};
  if (key === 'rank') return rankMap.has(row.symbol) ? rankMap.get(row.symbol) : null;
  if (key === 'symbol') return row.symbol;
  if (key === 'trend') return TRENDS_STATE_RANK[tf.state] !== undefined ? TRENDS_STATE_RANK[tf.state] : null;
  if (key === 'alignment') return TRENDS_ALIGNMENT_RANK[tf.alignment_state] !== undefined ? TRENDS_ALIGNMENT_RANK[tf.alignment_state] : null;
  if (key === 'priorAlignment') {
    if (tf.alignment_state == null) return null;
    // "> window" sinks to the bottom of BOTH sort directions, grouped
    // with null/"—" rows - reusing the sorted useMemo's existing
    // missing-value-sink rule rather than a second mechanism.
    if (tf.alignment_changed_unbounded === true) return null;
    return typeof tf.alignment_changed_ts === 'number' ? tf.alignment_changed_ts : null;
  }
  if (key === 'pct') return _trendsPctSinceFlip(tf.price, tf.flip_price);
  if (key === 'toFlip') return tf.dist_to_flip_pct;
  if (key === 'flips') return tf.flip_count_window;
  if (key === 'rsVsBtc') return tf.rs_vs_btc_pct;
  if (key === 'flip') {
    if (tf.flip_age_unbounded === true) return null;          // same sink-to-bottom treatment
    return typeof tf.flip_ts === 'number' ? tf.flip_ts : null;
  }
  if (key === 'price') return typeof row.price === 'number' ? row.price : null;
  if (key === 'volume') return typeof tf.volume_24h === 'number' ? tf.volume_24h : null;
  return null;
}

/* ── small presentational pieces ── */

// Trend chip - FILLED (background + border + color), the flip-state.
// Pill-radius (999) per the polish pass, like every other chip on this
// page.
function TrendsStateChip({ state }) {
  if (!state) return React.createElement('span', { style: { color: TRENDS_TEXT_SECONDARY, fontSize: 12 } }, '—');
  const s = TRENDS_STATE_COLORS[state] || TRENDS_STATE_COLORS.WARMUP;
  const label = _trendsFlipLabel(state);
  return React.createElement('span', {
    style: {
      display: 'inline-block', color: s.color, border: '1px solid ' + s.color,
      background: s.bg, borderRadius: 999, padding: '2px 9px', fontSize: 12, fontWeight: 700,
    },
  }, label);
}

// Alignment chip - OUTLINE-ONLY (transparent background), the EMA-stack
// state. Deliberately never filled, so it can never be confused with the
// Trend chip above even though both may read "Neutral" (doc ruling 9).
function TrendsAlignmentChip({ state }) {
  if (!state) return React.createElement('span', { style: { color: TRENDS_TEXT_SECONDARY, fontSize: 12 } }, '—');
  const color = TRENDS_ALIGNMENT_COLORS[state] || TRENDS_NEUTRAL;
  const label = TRENDS_ALIGNMENT_LABELS[state] || state;
  return React.createElement('span', {
    style: {
      display: 'inline-block', color, border: '1px solid ' + color,
      background: 'transparent', borderRadius: 999, padding: '2px 9px', fontSize: 12, fontWeight: 600,
    },
  }, label);
}

// Confluence tiles (A3) - always visible, one per timeframe, colored by
// that timeframe's own flip-state. Polish pass: no more per-tile outline
// for the selected timeframe (that's now the single band above the
// column headers, TrendsTimeframeMarker) - every tile gets the same
// plain border, pill-radius per the polish pass.
function TrendsConfluenceTiles({ timeframes }) {
  return React.createElement('div', { style: { display: 'flex', gap: 3, marginTop: 3 } },
    TRENDS_TIMEFRAMES.map((tfKey) => {
      const st = (timeframes[tfKey] || {}).state;
      const c = st ? (TRENDS_STATE_COLORS[st] || TRENDS_STATE_COLORS.WARMUP) : null;
      return React.createElement('span', {
        key: tfKey,
        title: TRENDS_TF_LABELS[tfKey] + ': ' + (st ? _trendsFlipLabel(st) : 'no data'),
        style: {
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 17, height: 15, fontSize: 9, fontWeight: 700, borderRadius: 999, lineHeight: 1,
          color: c ? c.color : TRENDS_TEXT_SECONDARY,
          background: c ? c.bg : 'transparent',
          border: '1px solid ' + TRENDS_BORDER,
        },
      }, TRENDS_TF_SHORT[tfKey]);
    })
  );
}

function TrendsTrendCell({ timeframes, selectedTf }) {
  const tf = timeframes[selectedTf] || {};
  return React.createElement('div', null,
    React.createElement(TrendsStateChip, { state: tf.state }),
    React.createElement(TrendsConfluenceTiles, { timeframes })
  );
}

// Timeframe marker (polish pass) - the single, table-wide indicator of
// which timeframe the Trend/Alignment/flip columns are currently showing,
// replacing the old per-tile outline. One band, not per-column tags.
function TrendsTimeframeMarker({ selectedTf }) {
  return React.createElement('div', {
    style: { display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', background: TRENDS_PANEL_BG },
  },
    React.createElement('span', {
      style: {
        display: 'inline-block', borderRadius: 999, padding: '3px 12px', fontSize: 12, fontWeight: 700,
        color: TRENDS_TEXT_PRIMARY, background: TRENDS_ACCENT, border: '1px solid ' + TRENDS_ACCENT,
      },
    }, TRENDS_TF_FULL_LABELS[selectedTf]),
    React.createElement('span', { style: { fontSize: 12, color: TRENDS_TEXT_SECONDARY } },
      'trend columns follow this timeframe')
  );
}

// Prior Alignment cell: prev-state chip (only when a real prior state
// exists - the engine guarantees alignment_prev_state is None whenever
// alignment_changed_unbounded is True) + granular age, "> window" when
// unbounded, "—" when alignment itself is undefined.
function TrendsPriorAlignmentCell({ tf, nowMs, timeframe, windowDays }) {
  if (!tf || tf.alignment_state === null || tf.alignment_state === undefined) {
    return React.createElement('span', { style: { color: TRENDS_TEXT_SECONDARY, fontSize: 12 } }, '—');
  }
  let ageText = '—';
  let tooltip = null;
  if (tf.alignment_changed_unbounded === true) {
    ageText = _trendsWindowLabel(windowDays, timeframe);
    tooltip = 'flip predates the fetched candle window — age unknown';
  } else if (typeof tf.alignment_changed_ts === 'number') {
    ageText = _trendsFmtAge(_trendsAgeFromTs(nowMs, tf.alignment_changed_ts), timeframe);
    tooltip = new Date(tf.alignment_changed_ts * 1000).toLocaleString();
  }
  return React.createElement('div', { title: tooltip, style: { display: 'flex', flexDirection: 'column', gap: 2 } },
    tf.alignment_prev_state ? React.createElement(TrendsAlignmentChip, { state: tf.alignment_prev_state }) : null,
    React.createElement('span', { style: { fontSize: 11, color: TRENDS_TEXT_SECONDARY } }, ageText)
  );
}

/* ── sub-table (A2: expandable row accordion) ── */

function TrendsSubTable({ row, selectedTf, nowMs, windowDays }) {
  const thStyle = { fontSize: 11, color: TRENDS_TEXT_SECONDARY, textAlign: 'left', padding: '4px 10px', fontWeight: 600 };
  const tdStyle = { padding: '5px 10px', fontSize: 12, color: TRENDS_TEXT_PRIMARY };
  return React.createElement('div', {
    style: { background: TRENDS_HEADER_BG, border: '1px solid ' + TRENDS_BORDER, borderRadius: 4, margin: '4px 0 8px' },
  },
    React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse' } },
      React.createElement('thead', null,
        React.createElement('tr', null,
          React.createElement('th', { style: thStyle }, 'TIMEFRAME'),
          React.createElement('th', { style: thStyle }, 'TREND'),
          React.createElement('th', { style: thStyle }, 'ALIGNMENT (EMA)'),
          React.createElement('th', { style: thStyle }, 'Δ SINCE FLIP'),
          React.createElement('th', { style: thStyle }, 'TO FLIP'),
          React.createElement('th', { style: thStyle }, 'TIME SINCE FLIP'),
          React.createElement('th', { style: thStyle }, 'FLIPS'),
          React.createElement('th', { style: thStyle }, 'RS VS BTC'),
        )
      ),
      React.createElement('tbody', null,
        TRENDS_TIMEFRAMES.map((tfKey) => {
          const tf = row.timeframes[tfKey] || {};
          const isView = tfKey === selectedTf;
          const pct = _trendsPctSinceFlip(tf.price, tf.flip_price);
          let flipAge = '—';
          let flipAgeTooltip = null;
          if (tf.flip_age_unbounded === true) {
            flipAge = _trendsWindowLabel(windowDays, tfKey);
            flipAgeTooltip = 'flip predates the fetched candle window — age unknown';
          } else if (typeof tf.flip_ts === 'number') {
            flipAge = _trendsFmtAge(_trendsAgeFromTs(nowMs, tf.flip_ts), tfKey);
          }
          return React.createElement('tr', {
            key: tfKey,
            style: { background: isView ? TRENDS_ACCENT_BG : 'transparent', borderTop: '1px solid ' + TRENDS_BORDER },
          },
            React.createElement('td', { style: tdStyle },
              TRENDS_TF_LABELS[tfKey],
              isView ? React.createElement('span', {
                style: {
                  marginLeft: 6, fontSize: 10, fontWeight: 700, color: TRENDS_ACCENT,
                  border: '1px solid ' + TRENDS_ACCENT, borderRadius: 3, padding: '0 4px',
                },
              }, 'VIEW') : null
            ),
            React.createElement('td', { style: tdStyle }, React.createElement(TrendsStateChip, { state: tf.state })),
            React.createElement('td', { style: tdStyle }, React.createElement(TrendsAlignmentChip, { state: tf.alignment_state })),
            React.createElement('td', {
              style: Object.assign({}, tdStyle, { color: pct === null ? TRENDS_TEXT_SECONDARY : (pct >= 0 ? TRENDS_BULL : TRENDS_BEAR) }),
            }, pct !== null ? window.fmtPct(pct) : '—'),
            React.createElement('td', {
              style: Object.assign({}, tdStyle, { color: typeof tf.dist_to_flip_pct !== 'number' ? TRENDS_TEXT_SECONDARY : (tf.dist_to_flip_pct >= 0 ? TRENDS_BULL : TRENDS_BEAR) }),
            }, typeof tf.dist_to_flip_pct === 'number' ? _trendsFmtToFlip(tf.dist_to_flip_pct) : '—'),
            React.createElement('td', { style: tdStyle, title: flipAgeTooltip }, flipAge),
            React.createElement('td', { style: tdStyle },
              typeof tf.flip_count_window === 'number' ? String(tf.flip_count_window) : '—'),
            React.createElement('td', {
              style: Object.assign({}, tdStyle, { color: typeof tf.rs_vs_btc_pct !== 'number' ? TRENDS_TEXT_SECONDARY : (tf.rs_vs_btc_pct >= 0 ? TRENDS_BULL : TRENDS_BEAR) }),
            }, typeof tf.rs_vs_btc_pct === 'number' ? _trendsFmtToFlip(tf.rs_vs_btc_pct) : '—')
          );
        })
      )
    )
  );
}

/* ── stats strip ── */

function TrendsStatsStrip({ rows, selectedTf }) {
  const stats = React.useMemo(() => {
    let bullish = 0, bearish = 0, neutral = 0, confluence = 0;
    rows.forEach((r) => {
      const st = (r.timeframes[selectedTf] || {}).state;
      if (st === 'BULLISH') bullish++;
      else if (st === 'BEARISH') bearish++;
      else neutral++;   // WARMUP or missing
      if (_trendsConfluence(r.timeframes).all3) confluence++;
    });
    return { total: rows.length, bullish, bearish, neutral, confluence };
  }, [rows, selectedTf]);

  const pct = (n) => stats.total > 0 ? ((n / stats.total) * 100).toFixed(0) + '%' : '0%';

  function tile(label, value, color) {
    return React.createElement('div', {
      style: {
        background: TRENDS_PANEL_BG, border: '1px solid ' + TRENDS_BORDER, borderRadius: 6,
        padding: '12px 16px', minWidth: 140, flex: '1 1 140px',
      },
    },
      React.createElement('div', { style: { fontSize: 11, color: TRENDS_TEXT_SECONDARY, marginBottom: 4 } }, label),
      React.createElement('div', { style: { fontSize: 20, fontWeight: 700, color: color || TRENDS_TEXT_PRIMARY } }, value)
    );
  }

  return React.createElement('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap' } },
    tile('Total tokens', stats.total, TRENDS_TEXT_PRIMARY),
    tile('Bullish', stats.bullish + ' (' + pct(stats.bullish) + ')', TRENDS_BULL),
    tile('Bearish', stats.bearish + ' (' + pct(stats.bearish) + ')', TRENDS_BEAR),
    tile('Neutral', stats.neutral + ' (' + pct(stats.neutral) + ')', TRENDS_NEUTRAL),
    tile('Full trend confluence', stats.confluence + ' (all 3 TFs agree)', TRENDS_ACCENT)
  );
}

/* ── table ── */

function TrendsTable({ rows, sort, cycleSort, selectedTf, rankMap, expanded, toggleExpand, nowMs, windowDays, setup1Recency }) {
  const thStyle = (key) => ({
    cursor: 'pointer', userSelect: 'none', textAlign: 'left', padding: '10px 12px',
    fontSize: 11, fontWeight: 700, letterSpacing: '0.03em', background: TRENDS_HEADER_BG,
    color: sort.key === key ? TRENDS_TEXT_PRIMARY : TRENDS_TEXT_SECONDARY,
    borderBottom: '2px solid ' + TRENDS_BORDER,
  });
  const sortableTh = (txt, key) => React.createElement('th', {
    onClick: () => cycleSort(key), style: thStyle(key),
  }, txt, sort.key === key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : '');
  const td = { padding: '10px 12px', fontSize: 13, color: TRENDS_TEXT_PRIMARY, borderBottom: '2px solid ' + TRENDS_BORDER, verticalAlign: 'top' };

  if (rows.length === 0) {
    return React.createElement('div', { style: { fontSize: 13, color: TRENDS_TEXT_SECONDARY, padding: '24px 0' } },
      'No tokens match the current filters.');
  }

  return React.createElement(React.Fragment, null,
    React.createElement(TrendsTimeframeMarker, { selectedTf }),
    React.createElement('div', { style: { overflowX: 'auto' } },
    React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse' } },
      React.createElement('thead', null,
        React.createElement('tr', null,
          sortableTh('#', 'rank'),
          sortableTh('TOKEN', 'symbol'),
          sortableTh('TREND', 'trend'),
          sortableTh('ALIGNMENT (EMA)', 'alignment'),
          sortableTh('PRIOR ALIGNMENT', 'priorAlignment'),
          sortableTh('Δ SINCE FLIP', 'pct'),
          sortableTh('TO FLIP', 'toFlip'),
          sortableTh('TIME SINCE FLIP', 'flip'),
          sortableTh('FLIPS', 'flips'),
          sortableTh('RS VS BTC', 'rsVsBtc'),
          sortableTh('PRICE', 'price'),
          sortableTh('VOLUME 24H', 'volume'),
        )
      ),
      React.createElement('tbody', null,
        rows.map((row, i) => {
          const tf = row.timeframes[selectedTf] || {};
          const isExpanded = expanded.has(row.symbol);
          const rowBg = i % 2 === 0 ? TRENDS_BG : TRENDS_PANEL_BG;
          let flipDisplay = '—';
          let flipTooltip = null;
          if (tf.flip_age_unbounded === true) {
            flipDisplay = _trendsWindowLabel(windowDays, selectedTf);
            flipTooltip = 'flip predates the fetched candle window — age unknown';
          } else if (typeof tf.flip_ts === 'number') {
            flipDisplay = _trendsFmtAge(_trendsAgeFromTs(nowMs, tf.flip_ts), selectedTf);
          }
          const pct = _trendsPctSinceFlip(tf.price, tf.flip_price);
          const rank = rankMap.has(row.symbol) ? rankMap.get(row.symbol) : null;
          const s1 = setup1Recency ? _trendsSetup1(row.timeframes, setup1Recency, nowMs) : null;
          const rowNodes = [
            React.createElement('tr', {
              key: row.symbol,
              onClick: () => toggleExpand(row.symbol),
              className: 'trends-row',
              style: { background: isExpanded ? TRENDS_ACCENT_BG : rowBg, cursor: 'pointer' },
            },
              React.createElement('td', { style: td }, rank !== null ? rank : '—'),
              React.createElement('td', { style: Object.assign({}, td, { fontWeight: 700 }) },
                React.createElement('span', { style: { marginRight: 6, display: 'inline-block', width: 10, color: TRENDS_TEXT_SECONDARY } },
                  isExpanded ? '▼' : '▶'),
                row.symbol,
                s1 ? React.createElement('div', {
                  style: { fontSize: 11, fontWeight: 400, color: TRENDS_TEXT_SECONDARY, marginTop: 3, marginLeft: 16 },
                }, _trendsSetup1Label(s1)) : null
              ),
              React.createElement('td', { style: td }, React.createElement(TrendsTrendCell, { timeframes: row.timeframes, selectedTf })),
              React.createElement('td', { style: td }, React.createElement(TrendsAlignmentChip, { state: tf.alignment_state })),
              React.createElement('td', { style: td }, React.createElement(TrendsPriorAlignmentCell, { tf, nowMs, timeframe: selectedTf, windowDays })),
              React.createElement('td', { style: Object.assign({}, td, { color: pct === null ? TRENDS_TEXT_SECONDARY : (pct >= 0 ? TRENDS_BULL : TRENDS_BEAR) }) },
                pct !== null ? window.fmtPct(pct) : '—'),
              React.createElement('td', {
                style: Object.assign({}, td, { color: typeof tf.dist_to_flip_pct !== 'number' ? TRENDS_TEXT_SECONDARY : (tf.dist_to_flip_pct >= 0 ? TRENDS_BULL : TRENDS_BEAR) }),
              }, typeof tf.dist_to_flip_pct === 'number' ? _trendsFmtToFlip(tf.dist_to_flip_pct) : '—'),
              React.createElement('td', { style: td, title: flipTooltip }, flipDisplay),
              React.createElement('td', { style: td },
                typeof tf.flip_count_window === 'number' ? String(tf.flip_count_window) : '—'),
              React.createElement('td', {
                style: Object.assign({}, td, { color: typeof tf.rs_vs_btc_pct !== 'number' ? TRENDS_TEXT_SECONDARY : (tf.rs_vs_btc_pct >= 0 ? TRENDS_BULL : TRENDS_BEAR) }),
              }, typeof tf.rs_vs_btc_pct === 'number' ? _trendsFmtToFlip(tf.rs_vs_btc_pct) : '—'),
              React.createElement('td', { style: td }, typeof row.price === 'number' ? window.fmtPrice(row.price) : '—'),
              React.createElement('td', { style: td }, typeof tf.volume_24h === 'number' ? window.fmt(tf.volume_24h, 0) : '—'),
            ),
          ];
          if (isExpanded) {
            rowNodes.push(
              React.createElement('tr', { key: row.symbol + '-sub' },
                React.createElement('td', { colSpan: 12, style: { padding: '0 12px', background: rowBg, borderBottom: '2px solid ' + TRENDS_BORDER } },
                  React.createElement(TrendsSubTable, { row, selectedTf, nowMs, windowDays })
                )
              )
            );
          }
          return rowNodes;
        })
      )
    )
    )
  );
}

/* ── sidebar ── */

// Tooltip for one sidebar control (TRENDS_TIPS). Opens after a short pause
// on mouse hover, at once on keyboard focus (focus-visible) or a tap, and
// closes on mouse-out, blur or Escape. The text is always in the DOM
// (display:none while closed) so aria-describedby on the control reads it.
// It sits under the control and lines up with the sidebar's inner edges
// (left offset worked out when it opens), so it never leaves the sidebar.
const TRENDS_TIP_DELAY_MS = 350;

function TrendsTip({ tip, block, children }) {
  const id = React.useId();
  const wrapRef = React.useRef(null);
  const timerRef = React.useRef(null);
  const [pos, setPos] = React.useState(null);
  React.useEffect(() => () => clearTimeout(timerRef.current), []);

  function show() {
    const el = wrapRef.current;
    if (!el) return;
    const sidebar = el.offsetParent;
    const pad = 16;
    const inner = sidebar ? sidebar.clientWidth - 2 * pad : 268;
    setPos({ left: pad - el.offsetLeft, width: Math.max(200, inner) });
  }
  function hide() {
    clearTimeout(timerRef.current);
    setPos(null);
  }
  function onMouseEnter() {
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(show, TRENDS_TIP_DELAY_MS);
  }
  function onFocus(e) {
    const t = e.target;
    if (t && t.matches && t.matches(':focus-visible')) show();
  }
  function onTouchStart() {
    clearTimeout(timerRef.current);
    show();
  }

  return React.createElement('span', {
    ref: wrapRef,
    style: { position: 'relative', display: block ? 'block' : 'inline-block' },
    onMouseEnter, onMouseLeave: hide, onFocus, onBlur: hide, onTouchStart,
    onKeyDown: (e) => { if (e.key === 'Escape') hide(); },
  },
    React.cloneElement(children, { 'aria-describedby': id }),
    React.createElement('div', {
      id, role: 'tooltip', className: 'trends-tip',
      style: {
        display: pos ? 'block' : 'none', position: 'absolute', zIndex: 60,
        top: 'calc(100% + 4px)', left: pos ? pos.left : 0, width: pos ? pos.width : 268,
        background: TRENDS_HEADER_BG, border: '1px solid rgba(255,255,255,0.45)', borderRadius: 6,
        boxShadow: '0 6px 18px rgba(0,0,0,0.55)', padding: '10px 12px', textAlign: 'left',
        fontSize: 12, lineHeight: 1.45, fontWeight: 400, color: TRENDS_TEXT_PRIMARY,
        whiteSpace: 'normal', pointerEvents: 'none',
      },
    },
      tip.title ? React.createElement('div', { style: { fontWeight: 700, marginBottom: 4 } }, tip.title) : null,
      React.createElement('div', null, tip.body),
      tip.use ? React.createElement('div', { style: { marginTop: 6, color: TRENDS_TEXT_SECONDARY } }, tip.use) : null
    )
  );
}

function TrendsChipToggle({ active, label, onClick, color, 'aria-describedby': describedBy }) {
  return React.createElement('button', {
    onClick, 'aria-describedby': describedBy,
    style: {
      padding: '5px 12px', borderRadius: 999, fontSize: 12, cursor: 'pointer',
      border: '1px solid ' + (active ? (color || TRENDS_ACCENT) : TRENDS_BORDER),
      background: active ? (color ? color + '33' : TRENDS_ACCENT_BG) : 'transparent',
      color: active ? TRENDS_TEXT_PRIMARY : TRENDS_TEXT_SECONDARY,
      fontWeight: active ? 700 : 400, marginRight: 6, marginBottom: 6,
    },
  }, label);
}

// The "i" next to a section title: a small focusable button that carries the
// section's tooltip (TrendsTip forwards aria-describedby to it).
function TrendsInfoButton({ label, 'aria-describedby': describedBy }) {
  return React.createElement('button', {
    type: 'button', 'aria-label': 'About ' + label, 'aria-describedby': describedBy,
    style: {
      width: 18, height: 18, padding: 0, borderRadius: 999, flexShrink: 0, cursor: 'help',
      border: '1px solid ' + TRENDS_TEXT_SECONDARY, background: 'transparent', color: TRENDS_TEXT_SECONDARY,
      fontSize: 11, fontWeight: 700, lineHeight: '16px', fontFamily: 'inherit', textAlign: 'center',
    },
  }, 'i');
}

const TRENDS_SECTION_TITLE_STYLE = { fontSize: 12, fontWeight: 700, letterSpacing: '0.05em' };

// One sidebar section as its own card (Landing 45, Glenn Oct 16: "each
// section segmented out visually ... and a checkbox by each one to include
// or not in the filter"). Header row: a checkbox when the section is a
// filter (onCheck given), the title, and an "i" with the section's tooltip.
// A ticked section filters the list and gets an accent border; an unticked
// one is ignored but keeps its settings. TrendsSidebar ticks a section
// whenever one of its settings changes. Timeframe passes no onCheck: it picks
// what the table shows, it does not filter.
function TrendsSidebarSection({ title, tip, checked, onCheck, children }) {
  const on = checked === true;
  const titleStyle = Object.assign({}, TRENDS_SECTION_TITLE_STYLE,
    { color: onCheck && !on ? TRENDS_TEXT_SECONDARY : TRENDS_TEXT_PRIMARY });
  return React.createElement('div', {
    className: 'trends-section',
    style: {
      marginBottom: 12, padding: '10px 12px', borderRadius: 6, background: TRENDS_HEADER_BG,
      border: '1px solid ' + (on ? TRENDS_ACCENT : TRENDS_BORDER),
    },
  },
    React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 } },
      onCheck
        ? React.createElement('label', { style: { display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0, cursor: 'pointer' } },
            React.createElement('input', {
              type: 'checkbox', checked: on, onChange: (e) => onCheck(e.target.checked),
              style: { width: 16, height: 16, margin: 0, flexShrink: 0, accentColor: TRENDS_ACCENT, cursor: 'pointer' },
            }),
            React.createElement('span', { style: titleStyle }, title))
        : React.createElement('span', { style: Object.assign({}, titleStyle, { flex: 1 }) }, title),
      tip ? React.createElement(TrendsTip, { tip }, React.createElement(TrendsInfoButton, { label: tip.title })) : null
    ),
    children
  );
}

// One setup inside the SETUPS card: its own checkbox, name and "i" (each
// setup is ticked on its own; more setups will be added here).
function TrendsSetupRow({ label, tip, checked, onCheck }) {
  return React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 } },
    React.createElement('label', { style: { display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0, cursor: 'pointer' } },
      React.createElement('input', {
        type: 'checkbox', checked: checked === true, onChange: (e) => onCheck(e.target.checked),
        style: { width: 16, height: 16, margin: 0, flexShrink: 0, accentColor: TRENDS_ACCENT, cursor: 'pointer' },
      }),
      React.createElement('span', { style: { fontSize: 13, fontWeight: 600, color: TRENDS_TEXT_PRIMARY } }, label)),
    React.createElement(TrendsTip, { tip }, React.createElement(TrendsInfoButton, { label }))
  );
}

// Live progress bar for an async noodle scan (Commit 3) - accent fill on a
// faint track, 2px visible outline per the UI-visibility standard for
// borders on a dark background. Elapsed uses the run's own started_ts, not
// local click time, so it stays correct for a run this tab didn't start
// (an auto-trigger, or someone else's manual click that won the lock).
function TrendsScanProgress({ run, nowMs }) {
  if (!run || run.status !== 'running') return null;
  const total = typeof run.total === 'number' ? run.total : null;
  const pct = total && total > 0 ? Math.min(100, Math.round((run.done / total) * 100)) : 0;
  const elapsedSec = Math.max(0, Math.floor(nowMs / 1000 - run.started_ts));
  const mm = Math.floor(elapsedSec / 60);
  const ss = String(elapsedSec % 60).padStart(2, '0');
  return React.createElement('div', { style: { marginTop: 8 } },
    React.createElement('div', {
      style: {
        width: '100%', height: 8, borderRadius: 999, overflow: 'hidden',
        background: 'rgba(255,255,255,0.12)', border: '2px solid ' + TRENDS_BORDER,
      },
    },
      React.createElement('div', { style: { width: pct + '%', height: '100%', background: TRENDS_ACCENT } })
    ),
    React.createElement('div', { style: { fontSize: 11, color: TRENDS_TEXT_SECONDARY, marginTop: 6 } },
      'Scanning ' + run.done + ' / ' + (total !== null ? total : '—') + ' · ' + mm + ':' + ss + ' elapsed' +
      (run.trigger === 'auto' ? ' (auto)' : ''))
  );
}

function TrendsSidebar({ filters, setFilters, selectedTf, setSelectedTf, refreshBusy, scanRun, scanDoneMsg, nowMs, onRefresh }) {
  // set(patch): merge a change into the filters. A change to a setting inside
  // a section also sets that section's tick (trendOn, setup1, nearFlip, ...),
  // so picking something always takes effect; unticking keeps the settings.
  function set(patch) {
    setFilters((prev) => Object.assign({}, prev, typeof patch === 'function' ? patch(prev) : patch));
  }
  function toggleSetMember(field, value, onFlag) {
    set((prev) => {
      const next = new Set(prev[field]);
      if (next.has(value)) next.delete(value); else next.add(value);
      return { [field]: next, [onFlag]: true };
    });
  }

  const selectStyle = {
    width: '100%', fontSize: 12, padding: '6px 8px', borderRadius: 4,
    border: '1px solid ' + TRENDS_BORDER, background: TRENDS_PANEL_BG, color: TRENDS_TEXT_PRIMARY,
  };

  const hcThresholds = TRENDS_HIDE_CHOPPY_THRESHOLDS[selectedTf] || TRENDS_HIDE_CHOPPY_THRESHOLDS['1d'];
  const hcMiddle = hcThresholds[Math.floor(hcThresholds.length / 2)];
  // A threshold valid for one timeframe (e.g. 25 at 1d/12h) is meaningless
  // at another (1w's whole range tops out at 3) - reset to the new TF's
  // middle option whenever the pill changes while the filter is active.
  React.useEffect(() => {
    if (!filters.hideChoppy) return;
    if (hcThresholds.indexOf(filters.hideChoppyThreshold) === -1) {
      setFilters((prev) => Object.assign({}, prev, { hideChoppyThreshold: hcMiddle }));
    }
  }, [selectedTf]);

  return React.createElement('div', {
    style: {
      width: 300, flexShrink: 0, background: TRENDS_PANEL_BG, border: '1px solid ' + TRENDS_BORDER,
      borderRadius: 8, padding: 16, alignSelf: 'flex-start', position: 'sticky', top: 12,
    },
  },
    React.createElement(TrendsSidebarSection, { title: 'ASSET CLASS', tip: TRENDS_TIPS.assetClass,
      checked: filters.assetClassOn, onCheck: (v) => set({ assetClassOn: v }) },
      React.createElement(TrendsChipToggle, {
        active: filters.assetClasses.has('crypto'), label: 'Crypto',
        onClick: () => toggleSetMember('assetClasses', 'crypto', 'assetClassOn'),
      }),
      React.createElement(TrendsChipToggle, {
        active: filters.assetClasses.has('tradfi'), label: 'TradFi',
        onClick: () => toggleSetMember('assetClasses', 'tradfi', 'assetClassOn'),
      }),
    ),
    React.createElement(TrendsSidebarSection, { title: 'SETUPS' },
      React.createElement(TrendsSetupRow, {
        label: 'Daily cross under Weekly', tip: TRENDS_TIPS.setup1,
        checked: filters.setup1, onCheck: (v) => set({ setup1: v }),
      }),
      React.createElement('div', { style: { fontSize: 11, color: TRENDS_TEXT_SECONDARY, margin: '2px 0 6px' } },
        'Daily Trend fast EMA crossed above slow within'),
      React.createElement(TrendsTip, { tip: TRENDS_TIPS.setup1Recency, block: true },
        React.createElement('select', {
          value: filters.setup1Recency, style: selectStyle,
          onChange: (e) => set({ setup1Recency: e.target.value, setup1: true }),
        }, TRENDS_SETUP1_RECENCY_OPTIONS.map((o) =>
          React.createElement('option', { key: o.label, value: o.label }, o.label)))),
      React.createElement('div', { style: { fontSize: 11, color: TRENDS_TEXT_SECONDARY, marginTop: 6, lineHeight: 1.4 } },
        'Daily Trend at or under the Weekly Trend top; when below it, within ' + TRENDS_SETUP1_MAX_GAP_PCT + '%.')
    ),
    React.createElement(TrendsSidebarSection, { title: 'TREND', tip: TRENDS_TIPS.trend,
      checked: filters.trendOn, onCheck: (v) => set({ trendOn: v }) },
      React.createElement(TrendsChipToggle, {
        active: filters.trend.has('BULLISH'), label: 'Bullish', color: TRENDS_BULL,
        onClick: () => toggleSetMember('trend', 'BULLISH', 'trendOn'),
      }),
      React.createElement(TrendsChipToggle, {
        active: filters.trend.has('BEARISH'), label: 'Bearish', color: TRENDS_BEAR,
        onClick: () => toggleSetMember('trend', 'BEARISH', 'trendOn'),
      }),
      React.createElement(TrendsChipToggle, {
        active: filters.trend.has('WARMUP'), label: 'Neutral', color: TRENDS_NEUTRAL,
        onClick: () => toggleSetMember('trend', 'WARMUP', 'trendOn'),
      }),
    ),
    React.createElement(TrendsSidebarSection, { title: 'TREND CONFLUENCE',
      checked: filters.confluenceOn, onCheck: (v) => set({ confluenceOn: v }) },
      React.createElement(TrendsTip, { tip: TRENDS_TIPS.confAll3 },
        React.createElement(TrendsChipToggle, {
          active: filters.confluenceAll3, label: 'All 3 agree',
          onClick: () => set((prev) => ({ confluenceAll3: !prev.confluenceAll3, confluenceOn: true })),
        })),
      React.createElement(TrendsTip, { tip: TRENDS_TIPS.conf4H },
        React.createElement(TrendsChipToggle, {
          active: filters.confluence4H, label: '4H agrees',
          onClick: () => set((prev) => ({ confluence4H: !prev.confluence4H, confluenceOn: true })),
        })),
      React.createElement(TrendsTip, { tip: TRENDS_TIPS.confDW },
        React.createElement(TrendsChipToggle, {
          active: filters.confluenceDW, label: 'Daily = Weekly',
          onClick: () => set((prev) => ({ confluenceDW: !prev.confluenceDW, confluenceOn: true })),
        })),
    ),
    React.createElement(TrendsSidebarSection, { title: 'ALIGNMENT (EMA)', tip: TRENDS_TIPS.alignment,
      checked: filters.alignmentOn, onCheck: (v) => set({ alignmentOn: v }) },
      React.createElement(TrendsChipToggle, {
        active: filters.alignment.has('BULLISH'), label: 'Bullish', color: TRENDS_BULL,
        onClick: () => toggleSetMember('alignment', 'BULLISH', 'alignmentOn'),
      }),
      React.createElement(TrendsChipToggle, {
        active: filters.alignment.has('BEARISH'), label: 'Bearish', color: TRENDS_BEAR,
        onClick: () => toggleSetMember('alignment', 'BEARISH', 'alignmentOn'),
      }),
      React.createElement(TrendsChipToggle, {
        active: filters.alignment.has('NEUTRAL'), label: 'Neutral', color: TRENDS_NEUTRAL,
        onClick: () => toggleSetMember('alignment', 'NEUTRAL', 'alignmentOn'),
      }),
    ),
    React.createElement(TrendsSidebarSection, { title: 'TIME SINCE FLIPPED', tip: TRENDS_TIPS.timeSinceFlipped,
      checked: filters.timeSinceOn, onCheck: (v) => set({ timeSinceOn: v }) },
      React.createElement('select', {
        value: filters.timeSinceFlipped, style: selectStyle, 'aria-label': 'Time since flipped',
        onChange: (e) => set({ timeSinceFlipped: e.target.value, timeSinceOn: true }),
      }, TRENDS_TIME_SINCE_FLIPPED_OPTIONS.map((o) =>
        React.createElement('option', { key: o.label, value: o.label }, o.label)))
    ),
    React.createElement(TrendsSidebarSection, { title: 'NEAR FLIP', tip: TRENDS_TIPS.nearFlip,
      checked: filters.nearFlip, onCheck: (v) => set({ nearFlip: v }) },
      React.createElement(TrendsTip, { tip: TRENDS_TIPS.nearFlipThreshold, block: true },
        React.createElement('select', {
          value: filters.nearFlipThreshold, style: selectStyle, 'aria-label': 'Near flip distance',
          onChange: (e) => set({ nearFlipThreshold: Number(e.target.value), nearFlip: true }),
        }, TRENDS_NEAR_FLIP_THRESHOLDS.map((t) =>
          React.createElement('option', { key: t, value: t }, '< ' + t + '%'))))
    ),
    React.createElement(TrendsSidebarSection, { title: 'HIDE CHOPPY', tip: TRENDS_TIPS.hideChoppy,
      checked: filters.hideChoppy,
      // Ticking keeps a limit still valid for this timeframe, else takes the middle choice.
      onCheck: (v) => set((prev) => ({
        hideChoppy: v,
        hideChoppyThreshold: v && hcThresholds.indexOf(prev.hideChoppyThreshold) === -1 ? hcMiddle : prev.hideChoppyThreshold,
      })) },
      React.createElement(TrendsTip, { tip: TRENDS_TIPS.hideChoppyThreshold, block: true },
        React.createElement('select', {
          value: filters.hideChoppyThreshold !== null ? filters.hideChoppyThreshold : hcMiddle,
          style: selectStyle, 'aria-label': 'Hide choppy limit',
          onChange: (e) => set({ hideChoppyThreshold: Number(e.target.value), hideChoppy: true }),
        }, hcThresholds.map((t) =>
          React.createElement('option', { key: t, value: t }, '≤ ' + t))))
    ),
    React.createElement(TrendsSidebarSection, { title: 'TIMEFRAME', tip: TRENDS_TIPS.timeframe },
      TRENDS_TIMEFRAMES.map((tfKey) => React.createElement(TrendsChipToggle, {
        key: tfKey, active: selectedTf === tfKey, label: TRENDS_TF_FULL_LABELS[tfKey],
        onClick: () => setSelectedTf(tfKey),
      }))
    ),
    React.createElement(TrendsSidebarSection, { title: 'TOP BY VOLUME', tip: TRENDS_TIPS.topVolume,
      checked: filters.topVolumeOn, onCheck: (v) => set({ topVolumeOn: v }) },
      React.createElement('select', {
        value: filters.topVolume, style: selectStyle, 'aria-label': 'Top by volume',
        onChange: (e) => set({ topVolume: e.target.value, topVolumeOn: true }),
      }, TRENDS_TOP_VOLUME_OPTIONS.map((o) =>
        React.createElement('option', { key: o.value, value: o.value }, o.label)))
    ),
    React.createElement('div', { style: { borderTop: '1px solid ' + TRENDS_BORDER, paddingTop: 16 } },
      // Commit 3: the scan runs on a background thread and this route
      // returns as soon as it's spawned - the button disables only while
      // scanRun.status is 'running' (real live state via GET
      // /noodle-progress, not a synchronous wait), with the bar below it
      // showing done/total and elapsed. A 409 RefreshBusy (an auto-trigger
      // or another manual click already holds the lock) is expected/
      // benign, not an alarm-red error - it just shows that run instead.
      React.createElement(TrendsTip, { tip: TRENDS_TIPS.refresh, block: true },
        React.createElement('button', {
          style: {
            width: '100%', fontSize: 12, padding: '8px 10px', borderRadius: 4, cursor: refreshBusy ? 'default' : 'pointer',
            border: '1px solid ' + TRENDS_ACCENT, background: refreshBusy ? 'transparent' : TRENDS_ACCENT_BG,
            color: TRENDS_TEXT_PRIMARY, fontWeight: 700,
          },
          disabled: refreshBusy, onClick: onRefresh,
        }, refreshBusy ? 'Scanning…' : 'Refresh')),
      React.createElement(TrendsScanProgress, { run: scanRun, nowMs }),
      scanDoneMsg && React.createElement('div', { style: { fontSize: 11, color: TRENDS_TEXT_SECONDARY, marginTop: 6 } }, scanDoneMsg)
    )
  );
}

/* ── main screen ── */

function TrendsScreen() {
  const [data, setData] = React.useState({ symbols: [] });
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState(null);
  const [fetchedAt, setFetchedAt] = React.useState(null);
  const [filters, setFilters] = React.useState(() => Object.assign({}, TRENDS_FILTER_DEFAULTS,
    { trend: new Set(TRENDS_ALL_TREND_STATES), alignment: new Set(TRENDS_ALL_ALIGNMENT_STATES),
      assetClasses: new Set(TRENDS_ALL_ASSET_CLASSES) }));
  const [sort, setSort] = React.useState({ key: 'volume', dir: 'desc' });
  const [selectedTf, setSelectedTf] = React.useState('1d');
  // Commit 3 (async scan): scanRun is the newest noodle_scan_runs row (or
  // null - no run yet this session). scanDoneMsg is a separate, short-
  // lived summary/error line, cleared by its own 10s timeout on 'done' or
  // left standing (until the next refresh) on 'error'/'abandoned' - kept
  // apart from scanRun itself so the progress bar and the post-run message
  // don't fight over the same state slot.
  const [scanRun, setScanRun] = React.useState(null);
  const [scanDoneMsg, setScanDoneMsg] = React.useState(null);
  const [expanded, setExpanded] = React.useState(() => new Set());

  const mountedRef = React.useRef(true);
  const pollRef = React.useRef(null);
  React.useEffect(() => { return () => { mountedRef.current = false; stopPolling(); }; }, []);

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  async function fetchProgress() {
    try {
      const d = await api('/api/trading/scanner/noodle-progress');
      return (d && d.run) ? d.run : null;
    } catch (e) {
      return null;
    }
  }

  // Every 5s while a run is live - covers both a manual click's own run
  // and someone else's (a losing 409, or an auto-triggered run discovered
  // on load()). Stops itself the moment the polled row leaves 'running'.
  function startPolling() {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      const run = await fetchProgress();
      if (!mountedRef.current) return;
      if (!run || run.status !== 'running') {
        stopPolling();
        if (run) {
          setScanRun(run);
          if (run.status === 'done') {
            setScanDoneMsg('Scanned ' + run.total + ' · ' + run.errors + ' errors · ' + run.retired + ' retired');
            setTimeout(() => { if (mountedRef.current) setScanDoneMsg(null); }, 10000);
          } else {
            // 'error' or 'abandoned' - partial results already committed
            // per-symbol during the pass, so the table still has them.
            setScanDoneMsg('Last run did not finish — partial results kept' +
              (run.error_msg ? ' (' + run.error_msg + ')' : ''));
          }
        }
        load();
      } else {
        setScanRun(run);
      }
    }, 5000);
  }

  async function load() {
    setLoadError(null);
    try {
      const d = await api('/api/trading/scanner/noodle-state');
      if (d === undefined || d === null) {
        setLoadError('session expired');
        setLoading(false);
        return;
      }
      setData({ symbols: d.symbols || [], meta: d.meta || null });
      setFetchedAt(new Date());
      setExpanded(new Set());   // expansion state resets on a fresh fetch
      setLoading(false);
    } catch (e) {
      setLoadError(_trendsExtractErr(e));
      setLoading(false);
    }
    // On every load() (mount, and every reload after a finished scan): one
    // progress check. A 'running' row here is an AUTO-triggered scan (the
    // on-view staleness trigger) that nothing else would surface - starts
    // the same polling/progress-bar path a manual click would.
    const run = await fetchProgress();
    if (mountedRef.current && run && run.status === 'running') {
      setScanRun(run);
      startPolling();
    }
  }

  React.useEffect(() => { load(); }, []);

  async function handleRefresh() {
    setScanDoneMsg(null);
    try {
      const d = await api('/api/trading/scanner/noodle-refresh', { method: 'POST' });
      if (!mountedRef.current) return;
      if (d === undefined || d === null) {
        setScanDoneMsg('session expired');
        return;
      }
      // 202: {run_id, status:'running'} - fetch the row once so the bar
      // has real data immediately instead of waiting for the first poll.
      const run = await fetchProgress();
      if (mountedRef.current && run) setScanRun(run);
      startPolling();
    } catch (e) {
      if (!mountedRef.current) return;
      let busyRun = null;
      try { busyRun = JSON.parse(e.message).run || null; } catch (e2) {}
      if (busyRun) {
        // 409 RefreshBusy - someone else's run already holds the lock.
        // Not an error: show it and poll the same way (Commit 3, Step 5a).
        setScanRun(busyRun);
        startPolling();
      } else {
        setScanDoneMsg(_trendsExtractErr(e));
      }
    }
  }

  function cycleSort(key) {
    setSort((prev) => prev.key !== key ? { key, dir: 'asc' }
      : prev.dir === 'asc' ? { key, dir: 'desc' } : { key: null, dir: null });
  }

  function toggleExpand(symbol) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol); else next.add(symbol);
      return next;
    });
  }

  const rows = data.symbols;
  const windowDays = data.meta && data.meta.window_days;
  const refreshBusy = !!(scanRun && scanRun.status === 'running');
  const nowMs = Date.now();

  // Search + sidebar filters EXCLUDING top-by-volume, so volume rank
  // (and the "#" column / Top-N filter) is computed over the same base
  // set - never circularly dependent on the Top-N choice itself.
  const searchAndSidebarFiltered = React.useMemo(
    () => rows.filter((r) => _trendsPassesSearchAndSidebar(r, filters, selectedTf, nowMs)),
    [rows, filters, selectedTf]);

  const rankMap = React.useMemo(() => {
    const withVol = searchAndSidebarFiltered
      .map((r) => ({ symbol: r.symbol, vol: (r.timeframes[selectedTf] || {}).volume_24h }))
      .filter((x) => typeof x.vol === 'number')
      .sort((a, b) => b.vol - a.vol);
    const m = new Map();
    withVol.forEach((x, i) => m.set(x.symbol, i + 1));
    return m;
  }, [searchAndSidebarFiltered, selectedTf]);

  const filtered = React.useMemo(() => {
    if (!filters.topVolumeOn || filters.topVolume === 'all') return searchAndSidebarFiltered;
    const n = TRENDS_TOP_VOLUME_N[filters.topVolume];
    return searchAndSidebarFiltered.filter((r) => {
      const rank = rankMap.get(r.symbol);
      return typeof rank === 'number' && rank <= n;
    });
  }, [searchAndSidebarFiltered, filters.topVolume, filters.topVolumeOn, rankMap]);

  const sorted = React.useMemo(() => {
    const key = sort.key || 'volume';
    const dir = sort.key ? sort.dir : 'desc';
    const dirMul = dir === 'desc' ? -1 : 1;
    return filtered.slice().sort((a, b) => {
      const va = _trendsSortValue(a, key, selectedTf, rankMap), vb = _trendsSortValue(b, key, selectedTf, rankMap);
      const aMissing = va === null || va === undefined;
      const bMissing = vb === null || vb === undefined;
      if (aMissing && bMissing) return 0;
      if (aMissing) return 1;
      if (bMissing) return -1;
      if (typeof va === 'string') return dirMul * va.localeCompare(vb);
      return dirMul * (va - vb);
    });
  }, [filtered, sort, selectedTf, rankMap]);

  if (loading) {
    return React.createElement('div', {
      style: { display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 320, color: TRENDS_TEXT_SECONDARY, fontSize: 14 },
    }, 'Loading Trends…');
  }

  return React.createElement('div', { className: TRENDS_ROOT_CLASS, style: { background: TRENDS_BG, borderRadius: 8, padding: 20 } },
    React.createElement('style', null,
      '.' + TRENDS_ROOT_CLASS + ' .trends-row:hover { filter: brightness(1.15); }'
    ),
    React.createElement('div', { style: { fontSize: 20, fontWeight: 700, color: TRENDS_TEXT_PRIMARY, marginBottom: 4 } }, 'Trends'),
    React.createElement('div', { style: { fontSize: 12, color: TRENDS_TEXT_SECONDARY, marginBottom: 16 } },
      fetchedAt ? 'Loaded ' + fetchedAt.toLocaleString() : ''),
    loadError && React.createElement('div', { style: { color: TRENDS_BEAR, fontSize: 13, marginBottom: 12 } }, loadError),
    rows.length === 0
      ? React.createElement('div', { style: { fontSize: 13, color: TRENDS_TEXT_SECONDARY } }, 'No scan data yet.')
      : React.createElement(React.Fragment, null,
          React.createElement('div', { style: { marginBottom: 16 } },
            React.createElement(TrendsStatsStrip, { rows, selectedTf })
          ),
          React.createElement('div', { style: { marginBottom: 12 } },
            React.createElement('input', {
              type: 'text', placeholder: 'Search name, symbol…', value: filters.search,
              onChange: (e) => setFilters((prev) => Object.assign({}, prev, { search: e.target.value })),
              style: {
                fontSize: 13, padding: '8px 12px', width: 320, maxWidth: '100%', borderRadius: 4,
                border: '1px solid ' + TRENDS_BORDER, background: TRENDS_PANEL_BG, color: TRENDS_TEXT_PRIMARY,
              },
            })
          ),
          React.createElement('div', { style: { display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' } },
            React.createElement('div', { style: { flex: '1 1 500px', minWidth: 0, background: TRENDS_PANEL_BG, border: '1px solid ' + TRENDS_BORDER, borderRadius: 8, overflow: 'hidden' } },
              React.createElement(TrendsTable, {
                rows: sorted, sort, cycleSort, selectedTf, rankMap, expanded, toggleExpand, nowMs, windowDays,
                setup1Recency: filters.setup1 ? filters.setup1Recency : null,
              })
            ),
            React.createElement(TrendsSidebar, {
              filters, setFilters, selectedTf, setSelectedTf,
              refreshBusy, scanRun, scanDoneMsg, nowMs, onRefresh: handleRefresh,
            })
          )
        )
  );
}

window.TrendsScreen = TrendsScreen;
