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
// the TIME SINCE FLIPPED list from 1 day to 1 month. Default 3 days since
// Landing 48 (Glenn, Oct 17): the setup lists watch-list candidates, not
// entries, and a history test found 1, 2 and 3 days alike while the extra
// entries a week allows all sat near the 10% cap (spec Part F).
const TRENDS_SETUP1_DAILY_TF = '4h';
const TRENDS_SETUP1_WEEKLY_TF = '1d';
const TRENDS_SETUP1_RECENCY_OPTIONS = TRENDS_TIME_SINCE_FLIPPED_OPTIONS.filter((o) => o.seconds !== null && o.seconds >= 86400);
const TRENDS_SETUP1_DEFAULT_RECENCY = '3 days';
const TRENDS_SETUP1_MAX_GAP_PCT = 10;
// Compression under Weekly (Landing 49, Glenn Oct 17; spec Part F): the
// Daily Trend (4h row) and Weekly Trend (1d row) EMAs bunched around price -
// all four within TRENDS_COMPRESSION_MAX_WIDTH_PCT of the last daily close
// (highest EMA to lowest), that close within TRENDS_COMPRESSION_PRICE_PCT of
// the bunch, and the Daily Trend below the Weekly Trend (midpoints; Glenn
// ruled the above-side cases out, they tested worse). A watch-list label,
// not a signal: a history test on 43 coins (2018-2026) found these rose no
// more often than ordinary days.
const TRENDS_COMPRESSION_MAX_WIDTH_PCT = 15;
const TRENDS_COMPRESSION_PRICE_PCT = 3;
// Respected trend (Landings 50, 50b, 50c and 51, Glenn Oct 17-18; spec
// SPEC_respected_trend_test.md): the scan stores, per timeframe row (1h / 4h
// / 12h / 1d), the direction of the noodle band's slope while a sloping
// history is open (respect_dir; NULL when the band is flat), its tag count,
// the open time of the latest tag, the open time of the history's first bar
// (respect_since, the "respected for" clock) and its losses (two consecutive
// closes beyond the far edge; respect_losses). The Respected trend tab shows
// every timeframe at once: one passes with at least TRENDS_RESPECT_MIN_TAGS
// tags, at most TRENDS_RESPECT_MAX_LOSSES losses and the latest tag within
// TRENDS_RESPECT_WINDOW_BARS bars. A row with no respect_since was not
// rescanned since Landing 51 and fails closed. One that would pass but for
// an older latest tag is shown dimmed as stale and does not count (Glenn: a
// trend can be intact without a new run high). A band that went flat after a
// respected history shows "Ranging" for TRENDS_RESPECT_WINDOW_BARS bars
// (respect_ranging_since, set by the scan) and does not count. Testing =
// price inside that timeframe's band now. Informational (a watch list), not
// an entry signal: a history test found no reliable direction edge. The pass
// rule is repeated in src/engines/respected_trend.py for the Ranging marker;
// tests/test_trends_respected_wiring.py asserts the two agree.
const TRENDS_RESPECT_MIN_TAGS = 2;
const TRENDS_RESPECT_WINDOW_BARS = 30;
const TRENDS_RESPECT_MAX_LOSSES = 1;
const TRENDS_RESPECT_TFS = ['1d', '12h', '4h', '1h'];
const TRENDS_RESPECT_TF_SECONDS = { '1d': 86400, '12h': 43200, '4h': 14400, '1h': 3600 };
const TRENDS_RESPECT_DIRS = ['BULLISH', 'BEARISH'];
// Which tab the Trends page last showed (this browser only).
const TRENDS_TAB_STORAGE_KEY = 'trends.tab';
// Row links on the Respected trend tab (Glenn Oct 18): the exact Hyperliquid
// market the scan reads, on TradingView and on Hyperliquid.
const TRENDS_TV_CHART_URL = 'https://www.tradingview.com/chart/?symbol=';
const TRENDS_HL_TRADE_URL = 'https://app.hyperliquid.xyz/trade/';
// Landing 53: a TxFlow market opens at <TxFlow name>-USDC. A market only
// TxFlow lists is stored as "txflow:<NAME>" (its symbol here); the route's
// txflow_name is the bare TxFlow name on every coin TxFlow lists.
const TRENDS_TX_TRADE_URL = 'https://app.txflow.com/trade/';
const TRENDS_TXFLOW_PREFIX = 'txflow:';

const TRENDS_TOP_VOLUME_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'top20', label: 'Top 20' },
  { value: 'top50', label: 'Top 50' },
  { value: 'top100', label: 'Top 100' },
];

const TRENDS_ALL_TREND_STATES = ['BULLISH', 'BEARISH', 'WARMUP'];
const TRENDS_ALL_ALIGNMENT_STATES = ['BULLISH', 'BEARISH', 'NEUTRAL'];
// ASSET CLASS (Landing 46): the route's asset_class per symbol ('crypto' |
// 'tradfi' | null, from the cached Hyperliquid market lists). Landing 53 adds
// 'txflow': the markets only TxFlow lists, scanned from TxFlow's own candles.
const TRENDS_ALL_ASSET_CLASSES = ['crypto', 'tradfi', 'txflow'];

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
  compression: false,
  // Respected trend tab (Landing 50c): Direction and Testing now tick like
  // the sections on the Trends tab; respTfs picks the timeframes that count
  // (and the columns shown) and always keeps at least one.
  respDirOn: false,
  respDir: new Set(TRENDS_RESPECT_DIRS),
  respRetest: false,
  respTfs: new Set(TRENDS_RESPECT_TFS),
  // Section ticks (Landing 45): a section filters only while ticked; its
  // settings above are kept while it is not. Near flip, Hide choppy and the
  // setups use their own flags (nearFlip, hideChoppy, setup1, compression)
  // as the tick.
  trendOn: false,
  confluenceOn: false,
  alignmentOn: false,
  timeSinceOn: false,
  topVolumeOn: false,
  // Landing 46: ASSET CLASS, ticked like the other sections.
  assetClassOn: false,
  assetClasses: new Set(TRENDS_ALL_ASSET_CLASSES),
  // Landing 53: ON TXFLOW, a plain tick (no chips): only coins TxFlow lists.
  onTxflow: false,
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
    body: "Crypto: perps on Hyperliquid's main exchange. TradFi: perps on its xyz exchange (stocks, indexes and other traditional markets). TxFlow: markets that only TxFlow lists, scanned from TxFlow's own candles. The scan drops the xyz: prefix, so Crypto and TradFi come from Hyperliquid's market lists; a name listed on both counts as crypto. A coin on none of these (for example, delisted) shows only with all three chips on. Click to include or exclude.",
    use: 'Use it to scan only crypto, only TradFi, only TxFlow-only markets, or any mix.',
  },
  onTxflow: {
    title: 'On TxFlow',
    body: "Shows only coins TxFlow lists. A Hyperliquid perp counts when TxFlow has a market under the same name, or a known alias (such as XAU for GOLD), at a last price within 5% of Hyperliquid's; the same name at a different price is a different market. Markets only TxFlow lists always count. The list of matches is rebuilt by the first scan after it is a day old, so a market TxFlow just added or removed can take about a day to show. On the Respected trend tab these coins carry a TX link to their TxFlow market.",
    use: 'Use it to see which coins you can trade on TxFlow.',
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
  compression: {
    title: 'Compression under Weekly',
    body: 'Shows coins whose Daily Trend (EMA 100 and EMA 200 of 4H closes) and Weekly Trend (EMA 100 and EMA 200 of daily closes) have bunched up around price: all four EMAs within ' + TRENDS_COMPRESSION_MAX_WIDTH_PCT + '% of each other (highest to lowest, as a share of the last daily close), that close within ' + TRENDS_COMPRESSION_PRICE_PCT + '% of the bunch, and the Daily Trend below the Weekly Trend. The tag gives the width. In a history test on 43 coins (2018 to 2026) these rose no more often than ordinary days, so treat it as a watch list, not a signal. It reads the same whatever timeframe is selected, and combines with every other filter.',
    use: 'Use it to find coins basing under the Weekly Trend; the Daily cross under Weekly setup is the turn to watch for.',
  },
  respDirection: {
    title: 'Direction',
    body: 'Keeps coins with a respected timeframe in the chosen direction: Bullish (the noodle band is sloping up) or Bearish (sloping down). Click to include or exclude. With both chips on, nothing is filtered.',
    use: 'Use it to list only long candidates or only short candidates.',
  },
  respTimeframes: {
    title: 'Timeframes',
    body: 'Which timeframes count, and which columns show. The noodle band must be sloping for a timeframe to have a trend history; while it is flat there is none. A timeframe is respected when its current history has at least ' + TRENDS_RESPECT_MIN_TAGS + ' tags, fewer than ' + (TRENDS_RESPECT_MAX_LOSSES + 1) + ' losses, and the latest tag within the last ' + TRENDS_RESPECT_WINDOW_BARS + ' bars of that timeframe (the newest closed bar counts as the first). A tag is a wick into the band that holds, followed by a new high (bullish) or a new low (bearish); the candle does not have to close inside the band. A loss is two candles in a row closing beyond the far edge; one stray close is not a loss. The respected time counts from where the band began to slope. A dimmed cell is stale: the tags and losses qualify but the latest tag is older than ' + TRENDS_RESPECT_WINDOW_BARS + ' bars, so it does not count. Ranging means the band went flat within the last ' + TRENDS_RESPECT_WINDOW_BARS + ' bars after a respected history; it does not count either. History limited means the history began before the scanned candles, so its time and tag count may be low. A coin is listed when at least one ticked timeframe is respected. Closed candles only; at least one timeframe stays ticked.',
    use: 'Use it to focus the list on the timeframes you trade. A watch list, not an entry signal: a history test found no reliable direction edge.',
  },
  respRetest: {
    title: 'Testing now',
    body: "Keeps coins whose price is inside the noodle band right now on at least one respected timeframe, using the scan's latest price. A stale scan shows where price was.",
    use: 'Use it to find respected trends worth setting alerts on while price is at the band.',
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
    body: 'Keeps only the top 20, 50 or 100 coins by 24-hour volume among those passing the other filters; All turns it off. The scan itself covers the 250 Hyperliquid perps with the most 24-hour volume. Markets only TxFlow lists are not ranked (their # shows a dash), so any choice but All hides them.',
    use: 'Use it to focus on the most liquid markets.',
  },
  refresh: {
    title: 'Refresh',
    body: 'Starts a new scan of the 250 Hyperliquid perps with the most 24-hour volume, on all five timeframes, from closed candles. It then scans the markets only TxFlow lists that have at least $50k of 24-hour volume, from TxFlow candles. A scan also starts by itself when Trends opens and the data is more than 6 hours old.',
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

// Compression under Weekly (see TRENDS_COMPRESSION_*): {widthPct} when the
// row qualifies, else null. Reads the 4h row (Daily Trend EMAs) and the 1d
// row (Weekly Trend EMAs and the last closed daily close), whatever
// timeframe the table is showing. Fails closed on anything missing: no 4h /
// 1d row, EMAs not there yet (under 200 bars), or no daily close.
function _trendsCompression(rowTimeframes) {
  const d = rowTimeframes[TRENDS_SETUP1_DAILY_TF];
  const w = rowTimeframes[TRENDS_SETUP1_WEEKLY_TF];
  if (!d || !w) return null;
  const emas = [d.doc_ema_fast, d.doc_ema_slow, w.doc_ema_fast, w.doc_ema_slow];
  const close = w.last_close;
  if (!emas.concat([close]).every((x) => typeof x === 'number' && isFinite(x) && x > 0)) return null;
  const top = Math.max(...emas);
  const bottom = Math.min(...emas);
  const widthPct = (top - bottom) / close * 100;
  if (widthPct > TRENDS_COMPRESSION_MAX_WIDTH_PCT) return null;
  const pad = TRENDS_COMPRESSION_PRICE_PCT / 100;
  if (close < bottom * (1 - pad) || close > top * (1 + pad)) return null;
  const dailyMid = (d.doc_ema_fast + d.doc_ema_slow) / 2;
  const weeklyMid = (w.doc_ema_fast + w.doc_ema_slow) / 2;
  if (!(dailyMid < weeklyMid)) return null;          // Daily Trend below the Weekly Trend only
  return { widthPct };
}

function _trendsCompressionLabel(c) {
  return 'Compressed · ' + c.widthPct.toFixed(1) + '% wide';
}

// Respected trend tab (see TRENDS_RESPECT_*): one timeframe row's respect
// state, or null. 'pass' and 'stale' both need a sloping history
// (respect_dir), a respect_since time (NULL = not rescanned since Landing 51),
// at least TRENDS_RESPECT_MIN_TAGS tags, a known respect_losses of at most
// TRENDS_RESPECT_MAX_LOSSES and a tag time; 'pass' also needs the latest tag
// within TRENDS_RESPECT_WINDOW_BARS bars. 'ranging' is a flat band within
// TRENDS_RESPECT_WINDOW_BARS bars of respect_ranging_since. Ages in bars are
// counted from the scan's own last closed bar (computed_at floored to the
// timeframe, minus one bar), so they do not drift with the clock, and the
// respected time runs to the end of that bar. Anything missing fails closed.
function _trendsRespectCell(r, tfKey, nowMs) {
  if (!r || typeof r.computed_at !== 'string') return null;
  const computedSec = Date.parse(r.computed_at) / 1000;
  if (!isFinite(computedSec)) return null;
  const tfSec = TRENDS_RESPECT_TF_SECONDS[tfKey];
  const lastClosedOpen = Math.floor(computedSec / tfSec) * tfSec - tfSec;
  if (r.respect_dir === null || r.respect_dir === undefined) {      // no sloping history now
    if (typeof r.respect_ranging_since !== 'number') return null;
    const flatBars = Math.max(0, Math.round((lastClosedOpen - r.respect_ranging_since) / tfSec));
    if (flatBars >= TRENDS_RESPECT_WINDOW_BARS) return null;
    return { status: 'ranging', flatBars, ageSeconds: _trendsAgeFromTs(nowMs, r.respect_ranging_since) };
  }
  if (TRENDS_RESPECT_DIRS.indexOf(r.respect_dir) === -1) return null;
  if (typeof r.respect_since !== 'number') return null;
  if (typeof r.respect_tags !== 'number' || r.respect_tags < TRENDS_RESPECT_MIN_TAGS) return null;
  if (typeof r.respect_losses !== 'number' || r.respect_losses > TRENDS_RESPECT_MAX_LOSSES) return null;
  if (typeof r.respect_last_ts !== 'number') return null;
  const barsAgo = Math.max(0, Math.round((lastClosedOpen - r.respect_last_ts) / tfSec));
  const retesting = typeof r.price === 'number' && typeof r.lower_band === 'number' && typeof r.upper_band === 'number'
    && r.price >= r.lower_band && r.price <= r.upper_band;
  return {
    status: barsAgo < TRENDS_RESPECT_WINDOW_BARS ? 'pass' : 'stale',   // the latest bar is 0: bars 0..29 are the last 30
    dir: r.respect_dir, tags: r.respect_tags, losses: r.respect_losses, barsAgo, retesting,
    ageSeconds: _trendsAgeFromTs(nowMs, r.respect_last_ts),
    forSeconds: Math.max(0, lastClosedOpen + tfSec - r.respect_since),
    unbounded: r.respect_unbounded === true,
  };
}

// "Respected for" text: weeks and days from a week up, days and hours under a
// week, hours under a day; "≥" in front when the history began before the
// scanned candles (the real time is at least this).
function _trendsFmtRespectedFor(seconds, unbounded) {
  if (typeof seconds !== 'number' || isNaN(seconds)) return null;
  const s = Math.max(0, Math.floor(seconds));
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s - days * 86400) / 3600);
  let txt;
  if (days >= 7) {
    const weeks = Math.floor(days / 7), rest = days - weeks * 7;
    txt = weeks + 'W' + (rest > 0 ? ' ' + rest + 'D' : '');
  } else if (days >= 1) {
    txt = days + 'D' + (hours > 0 ? ' ' + hours + 'H' : '');
  } else {
    txt = hours >= 1 ? hours + 'H' : '< 1H';
  }
  return (unbounded ? '≥' : '') + txt;
}

// The tab's view of one coin: a cell per ticked timeframe, and the passing
// timeframes that also match Direction and Testing now (`counted`). The
// coin is listed when at least one timeframe is counted.
function _trendsRespectRow(row, filters, nowMs) {
  const cells = {};
  const counted = [];
  for (const tfKey of TRENDS_RESPECT_TFS) {
    if (!filters.respTfs.has(tfKey)) continue;
    const cell = _trendsRespectCell(row.timeframes[tfKey], tfKey, nowMs);
    cells[tfKey] = cell;
    if (!cell || cell.status !== 'pass') continue;
    if (filters.respDirOn && !_trendsPassesMultiFilter(filters.respDir, TRENDS_RESPECT_DIRS, cell.dir)) continue;
    if (filters.respRetest && !cell.retesting) continue;
    counted.push(tfKey);
  }
  return { cells, counted };
}

// TxFlow (Landing 53). A market only TxFlow lists is stored as
// "txflow:<NAME>" so TxFlow's QNT never collides with Hyperliquid's xyz QNT:
// the table, search and name sort show the bare name. txflow_name is set on
// every coin TxFlow lists (a tagged Hyperliquid perp or a TxFlow-only market).
function _trendsIsTxflowOnly(row) {
  return String(row.symbol).indexOf(TRENDS_TXFLOW_PREFIX) === 0;
}

function _trendsDisplayName(row) {
  const s = String(row.symbol);
  return s.indexOf(TRENDS_TXFLOW_PREFIX) === 0 ? s.slice(TRENDS_TXFLOW_PREFIX.length) : s;
}

function _trendsOnTxflow(row) {
  return typeof row.txflow_name === 'string' && row.txflow_name !== '';
}

// The coins on the Respected trend tab, before Top by volume: search, Asset
// class and On TxFlow as on the Trends tab, then at least one counted timeframe.
function _trendsRespectedList(rows, filters, nowMs) {
  const q = filters.search.trim().toUpperCase();
  const out = [];
  for (const row of rows) {
    if (filters.assetClassOn && !_trendsPassesMultiFilter(filters.assetClasses, TRENDS_ALL_ASSET_CLASSES, row.asset_class)) continue;
    if (filters.onTxflow && !_trendsOnTxflow(row)) continue;
    if (q && _trendsDisplayName(row).toUpperCase().indexOf(q) === -1) continue;
    const info = _trendsRespectRow(row, filters, nowMs);
    if (info.counted.length > 0) out.push({ row, info });
  }
  return out;
}

function _trendsRespectVolume(row) {
  for (const tfKey of TRENDS_RESPECT_TFS) {
    const r = row.timeframes[tfKey];
    if (r && typeof r.volume_24h === 'number') return r.volume_24h;
  }
  return null;
}

// Default order: most counted timeframes first, then volume. A timeframe
// column sorts by the tag count of a passing cell (stale and empty sink).
function _trendsRespectSortValue(item, key, rankMap) {
  const row = item.row;
  if (key === 'rank') return rankMap.has(row.symbol) ? rankMap.get(row.symbol) : null;
  if (key === 'symbol') return _trendsDisplayName(row);
  if (key === 'price') return typeof row.price === 'number' ? row.price : null;
  if (key === 'volume') return _trendsRespectVolume(row);
  if (TRENDS_RESPECT_TF_SECONDS[key]) {
    const c = item.info.cells[key];
    return c && c.status === 'pass' ? c.tags : null;
  }
  return null;
}

// Row links: TradingView lists Hyperliquid perps as HYPERLIQUID:<COIN>USDC.P
// (checked for INIT and HYPE, Oct 18). TradFi markets sit on Hyperliquid's
// xyz exchange; their TradingView name is unknown, so they get no chart
// link. A coin on neither market list (asset_class null) gets no links.
function _trendsTvUrl(row) {
  if (row.asset_class !== 'crypto') return null;
  return TRENDS_TV_CHART_URL + encodeURIComponent('HYPERLIQUID:' + row.symbol.toUpperCase() + 'USDC.P');
}

function _trendsHlUrl(row) {
  if (row.asset_class === 'crypto') return TRENDS_HL_TRADE_URL + row.symbol;
  if (row.asset_class === 'tradfi') return TRENDS_HL_TRADE_URL + 'xyz:' + row.symbol;
  return null;
}

// TxFlow link (Landing 53): any coin TxFlow lists, under TxFlow's own name
// (Hyperliquid's kBONK is TxFlow's 1000BONK, GOLD is XAU).
function _trendsTxUrl(row) {
  if (!_trendsOnTxflow(row)) return null;
  return TRENDS_TX_TRADE_URL + encodeURIComponent(row.txflow_name) + '-USDC';
}

// Every sidebar filter but SETUPS follows the selected timeframe; the
// setups always read the 4h and 1d rows (Daily and Weekly Trend) and are
// ANDed with the rest (and with each other), so narrowing TREND or
// ALIGNMENT while viewing another timeframe can hide their matches. A section
// applies only while its tick is on (TRENDS_FILTER_DEFAULTS, Landing 45).
// Top by volume is applied after this, in TrendsScreen.
function _trendsPassesSearchAndSidebar(row, filters, selectedTf, nowMs) {
  const tf = row.timeframes[selectedTf] || {};
  if (filters.assetClassOn && !_trendsPassesMultiFilter(filters.assetClasses, TRENDS_ALL_ASSET_CLASSES, row.asset_class)) return false;
  if (filters.onTxflow && !_trendsOnTxflow(row)) return false;
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
  if (filters.compression && !_trendsCompression(row.timeframes)) return false;
  if (filters.timeSinceOn && !_trendsPassesTimeSinceFlipped(tf, filters.timeSinceFlipped, nowMs)) return false;
  if (!_trendsPassesNearFlip(tf, filters.nearFlip, filters.nearFlipThreshold)) return false;
  if (!_trendsPassesHideChoppy(tf, filters.hideChoppy, filters.hideChoppyThreshold)) return false;
  const q = filters.search.trim().toUpperCase();
  if (q && _trendsDisplayName(row).toUpperCase().indexOf(q) === -1) return false;
  return true;
}

const TRENDS_TOP_VOLUME_N = { top20: 20, top50: 50, top100: 100 };

function _trendsSortValue(row, key, selectedTf, rankMap) {
  const tf = row.timeframes[selectedTf] || {};
  if (key === 'rank') return rankMap.has(row.symbol) ? rankMap.get(row.symbol) : null;
  if (key === 'symbol') return _trendsDisplayName(row);
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

// "TxFlow" marker beside a market only TxFlow lists (Landing 53), so e.g.
// TxFlow's QNT is never read as Hyperliquid's xyz QNT. Same look as the
// "testing" tag on the Respected trend tab.
function TrendsTxflowTag() {
  return React.createElement('span', {
    title: 'A market only TxFlow lists',
    style: {
      display: 'inline-block', marginLeft: 8, padding: '0 6px', borderRadius: 3, fontSize: 11, fontWeight: 700,
      border: '1px solid ' + TRENDS_ACCENT, background: TRENDS_ACCENT_BG, color: TRENDS_TEXT_PRIMARY,
    },
  }, 'TxFlow');
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

/* ── column header tooltips (Landing 54) ── */

// Glenn's Oct 19 texts for five columns of the Trends table. TrendsHeaderTip
// shows them on the main table and on the expanded row's sub-table.
const TRENDS_COLUMN_TIPS = {
  pct: {
    title: 'Δ since flip',
    body: 'Price change from the flip price to the current price.',
  },
  toFlip: {
    title: 'To flip',
    body: 'Distance from the last closed candle to the band edge that will trigger a trend flip, as a % of the closing price. Positive when bearish (price must rise to the upper edge), negative when bullish (price must fall to the lower edge).',
  },
  flip: {
    title: 'Time since flip',
    body: 'Time since the trend last flipped on the selected timeframe. “> Nd” means the flip is older than the scan window, so the age is unknown.',
  },
  flips: {
    title: 'Flips',
    body: 'Number of trend flips inside the scan window for the selected timeframe (60 days on 1H/4H, 150 on 12H, about 300 on Daily, 41 weeks on Weekly).',
  },
  rsVsBtc: {
    title: 'RS vs BTC',
    body: 'Token price change since flip minus BTC’s change over the same stretch as a %. Positive means it beat BTC. Blank for flips older than the scan window or when BTC’s history doesn’t reach back to the flip.',
  },
};

const TRENDS_COL_TIP_WIDTH = 280;
const TRENDS_COL_TIP_SETTLE_MS = 250;

// Header content for one column that has a tooltip: the label, the sort arrow
// and a small "i" button. The tip opens after a short pause on mouse hover
// over the label, at once on keyboard focus of the "i" or a click or tap on
// it, and closes on mouse-out, blur, Escape, a second tap, a tap elsewhere, a
// scroll or a resize. The "i" stops its click from reaching the <th>, so a tap
// opens the tip and does not sort the column. The tip is drawn in a portal on
// document.body with position:fixed from the label's on-screen box, so the
// table's horizontal scroll area and the row hover filter cannot clip or
// move it; it stays inside the viewport and flips above the label when there
// is no room below. aria-describedby points at it while it is open.
function TrendsHeaderTip({ tip, text, arrow }) {
  const id = React.useId();
  const wrapRef = React.useRef(null);
  const tipRef = React.useRef(null);
  const timerRef = React.useRef(null);
  const openedAtRef = React.useRef(0);
  const [anchor, setAnchor] = React.useState(null);
  const [pos, setPos] = React.useState(null);
  React.useEffect(() => () => clearTimeout(timerRef.current), []);

  function measure() {
    const el = wrapRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setAnchor({ left: r.left, top: r.top, bottom: r.bottom });
  }
  function show() {
    openedAtRef.current = Date.now();
    measure();
  }
  function hide() {
    clearTimeout(timerRef.current);
    setAnchor(null);
    setPos(null);
  }
  // A scroll within a moment of opening is the browser bringing a focused or
  // clicked "i" into view in the table's scroll area: follow the label. Any
  // later scroll closes the tip.
  function onScroll() {
    if (Date.now() - openedAtRef.current < TRENDS_COL_TIP_SETTLE_MS) measure(); else hide();
  }
  const vw = typeof document !== 'undefined' ? document.documentElement.clientWidth : 360;
  const width = Math.min(TRENDS_COL_TIP_WIDTH, vw - 16);

  React.useLayoutEffect(() => {
    if (!anchor || !tipRef.current) return;
    const vh = window.innerHeight;
    const h = tipRef.current.offsetHeight;
    const left = Math.min(Math.max(8, anchor.left), vw - width - 8);
    let top = anchor.bottom + 6;
    if (top + h > vh - 8 && anchor.top - 6 - h >= 8) top = anchor.top - 6 - h;
    setPos({ left, top });
  }, [anchor]);

  React.useEffect(() => {
    if (!anchor) return undefined;
    const onDown = (e) => { if (!(wrapRef.current && wrapRef.current.contains(e.target))) hide(); };
    const onKey = (e) => { if (e.key === 'Escape') hide(); };
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', hide);
    document.addEventListener('pointerdown', onDown, true);
    document.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', hide);
      document.removeEventListener('pointerdown', onDown, true);
      document.removeEventListener('keydown', onKey);
    };
  }, [anchor]);

  function onPointerEnter(e) {
    if (e.pointerType === 'touch') return;
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(show, TRENDS_TIP_DELAY_MS);
  }
  function onPointerLeave(e) {
    if (e.pointerType === 'touch') return;
    hide();
  }
  function onInfoClick(e) {
    e.stopPropagation();
    clearTimeout(timerRef.current);
    if (anchor) hide(); else show();
  }
  function onInfoFocus(e) {
    const t = e.target;
    if (t && t.matches && t.matches(':focus-visible')) show();
  }

  // The "i" stays with the last word of the label, so it never wraps alone.
  const cut = text.lastIndexOf(' ') + 1;
  const open = anchor !== null;
  // The "i" is 24px on a touch screen (the table scrolls sideways there, so
  // its width costs nothing) and 16px with a mouse (Landing 54b: the columns
  // must fit the panel).
  const coarse = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    && window.matchMedia('(pointer: coarse)').matches;
  const size = coarse ? 24 : 16;
  return React.createElement('span', { ref: wrapRef, onPointerEnter, onPointerLeave },
    text.slice(0, cut),
    React.createElement('span', { style: { whiteSpace: 'nowrap' } },
      text.slice(cut), arrow,
      React.createElement('button', {
        type: 'button', 'aria-label': 'About ' + tip.title, 'aria-describedby': open ? id : undefined,
        onClick: onInfoClick, onFocus: onInfoFocus, onBlur: hide,
        style: {
          width: size, height: size, padding: 0, marginLeft: coarse ? 6 : 4, borderRadius: 999, cursor: 'help',
          border: '1px solid ' + TRENDS_TEXT_SECONDARY, background: 'transparent', color: TRENDS_TEXT_SECONDARY,
          fontSize: 11, fontWeight: 700, lineHeight: (size - 2) + 'px', fontFamily: 'inherit', textAlign: 'center',
          verticalAlign: 'middle',
        },
      }, 'i')),
    open ? ReactDOM.createPortal(
      React.createElement('div', {
        ref: tipRef, id, role: 'tooltip', className: 'trends-col-tip',
        style: {
          position: 'fixed', zIndex: 1000, left: pos ? pos.left : 0, top: pos ? pos.top : 0, width,
          visibility: pos ? 'visible' : 'hidden',
          background: TRENDS_HEADER_BG, border: '1px solid rgba(255,255,255,0.45)', borderRadius: 6,
          boxShadow: '0 6px 18px rgba(0,0,0,0.55)', padding: '10px 12px', textAlign: 'left',
          fontSize: 13, lineHeight: 1.45, fontWeight: 400, letterSpacing: 'normal', textTransform: 'none',
          color: TRENDS_TEXT_PRIMARY, whiteSpace: 'normal', pointerEvents: 'none',
        },
      },
        React.createElement('div', { style: { fontWeight: 700, marginBottom: 4 } }, tip.title),
        React.createElement('div', null, tip.body)
      ),
      document.body
    ) : null
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
          React.createElement('th', { style: thStyle },
            React.createElement(TrendsHeaderTip, { tip: TRENDS_COLUMN_TIPS.pct, text: 'Δ SINCE FLIP', arrow: '' })),
          React.createElement('th', { style: thStyle },
            React.createElement(TrendsHeaderTip, { tip: TRENDS_COLUMN_TIPS.toFlip, text: 'TO FLIP', arrow: '' })),
          React.createElement('th', { style: thStyle },
            React.createElement(TrendsHeaderTip, { tip: TRENDS_COLUMN_TIPS.flip, text: 'TIME SINCE FLIP', arrow: '' })),
          React.createElement('th', { style: thStyle },
            React.createElement(TrendsHeaderTip, { tip: TRENDS_COLUMN_TIPS.flips, text: 'FLIPS', arrow: '' })),
          React.createElement('th', { style: thStyle },
            React.createElement(TrendsHeaderTip, { tip: TRENDS_COLUMN_TIPS.rsVsBtc, text: 'RS VS BTC', arrow: '' })),
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
    let bullish = 0, bearish = 0, neutral = 0, confluence = 0, total = 0;
    rows.forEach((r) => {
      if (_trendsIsTxflowOnly(r)) return;   // Landing 53: these tiles stay a Hyperliquid scan breadth
      total++;
      const st = (r.timeframes[selectedTf] || {}).state;
      if (st === 'BULLISH') bullish++;
      else if (st === 'BEARISH') bearish++;
      else neutral++;   // WARMUP or missing
      if (_trendsConfluence(r.timeframes).all3) confluence++;
    });
    return { total, bullish, bearish, neutral, confluence };
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

function TrendsTable({ rows, sort, cycleSort, selectedTf, rankMap, expanded, toggleExpand, nowMs, windowDays, setup1Recency, compressionOn }) {
  const thStyle = (key) => ({
    cursor: 'pointer', userSelect: 'none', textAlign: 'left', padding: '10px 10px',
    fontSize: 11, fontWeight: 700, letterSpacing: '0.03em', background: TRENDS_HEADER_BG,
    color: sort.key === key ? TRENDS_TEXT_PRIMARY : TRENDS_TEXT_SECONDARY,
    borderBottom: '2px solid ' + TRENDS_BORDER,
  });
  const sortableTh = (txt, key, tip) => {
    const arrow = sort.key === key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : '';
    const props = { onClick: () => cycleSort(key), style: thStyle(key) };
    return tip
      ? React.createElement('th', props, React.createElement(TrendsHeaderTip, { tip, text: txt, arrow }))
      : React.createElement('th', props, txt, arrow);
  };
  // 10px each side (was 12, Landing 54b): the 12 columns plus the header "i"
  // buttons must fit the panel at 1920px, or Volume 24H is cut off.
  const td = { padding: '10px 10px', fontSize: 13, color: TRENDS_TEXT_PRIMARY, borderBottom: '2px solid ' + TRENDS_BORDER, verticalAlign: 'top' };

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
          sortableTh('Δ SINCE FLIP', 'pct', TRENDS_COLUMN_TIPS.pct),
          sortableTh('TO FLIP', 'toFlip', TRENDS_COLUMN_TIPS.toFlip),
          sortableTh('TIME SINCE FLIP', 'flip', TRENDS_COLUMN_TIPS.flip),
          sortableTh('FLIPS', 'flips', TRENDS_COLUMN_TIPS.flips),
          sortableTh('RS VS BTC', 'rsVsBtc', TRENDS_COLUMN_TIPS.rsVsBtc),
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
          const comp = compressionOn ? _trendsCompression(row.timeframes) : null;
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
                _trendsDisplayName(row),
                _trendsIsTxflowOnly(row) ? React.createElement(TrendsTxflowTag) : null,
                s1 ? React.createElement('div', {
                  style: { fontSize: 11, fontWeight: 400, color: TRENDS_TEXT_SECONDARY, marginTop: 3, marginLeft: 16 },
                }, _trendsSetup1Label(s1)) : null,
                comp ? React.createElement('div', {
                  style: { fontSize: 11, fontWeight: 400, color: TRENDS_TEXT_SECONDARY, marginTop: 3, marginLeft: 16 },
                }, _trendsCompressionLabel(comp)) : null
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

/* ── respected trend tab (Landing 50c) ── */

// The two tabs under the page title (Glenn Oct 18: the respected trend is a
// different kind of information from the flip table).
function TrendsTabs({ tab, setTab }) {
  const btn = (key, label) => React.createElement('button', {
    type: 'button', role: 'tab', 'aria-selected': tab === key, onClick: () => setTab(key),
    style: {
      padding: '8px 16px', fontSize: 13, fontWeight: 700, cursor: 'pointer', background: 'transparent',
      border: 'none', borderBottom: '3px solid ' + (tab === key ? TRENDS_ACCENT : 'transparent'),
      color: tab === key ? TRENDS_TEXT_PRIMARY : TRENDS_TEXT_SECONDARY, fontFamily: 'inherit', marginBottom: -2,
    },
  }, label);
  return React.createElement('div', {
    role: 'tablist', style: { display: 'flex', gap: 4, borderBottom: '2px solid ' + TRENDS_BORDER, marginBottom: 16 },
  }, btn('trends', 'Trends'), btn('respected', 'Respected trend'));
}

// One timeframe cell: the direction, how long the trend has been respected,
// the latest tag's age, then testing and history limited when they apply. A
// stale cell is italic in the secondary colour and gives its age in bars. A
// ranging cell (the band went flat after a respected history) says so and
// how long ago.
function TrendsRespectCell({ cell, tfKey }) {
  if (!cell) return React.createElement('span', { style: { color: TRENDS_TEXT_SECONDARY } }, '—');
  const small = { fontSize: 11, color: TRENDS_TEXT_SECONDARY, marginTop: 2 };
  if (cell.status === 'ranging') {
    const flatAge = _trendsFmtAge(cell.ageSeconds, tfKey);
    return React.createElement('div', { 'data-status': 'ranging' },
      React.createElement('div', {
        style: { fontSize: 13, fontWeight: 700, whiteSpace: 'nowrap', color: TRENDS_TEXT_SECONDARY },
      }, 'Ranging'),
      React.createElement('div', { style: Object.assign({}, small, { whiteSpace: 'nowrap' }) },
        flatAge !== null ? 'went flat ' + flatAge + ' ago' : ''));
  }
  const stale = cell.status === 'stale';
  const age = _trendsFmtAge(cell.ageSeconds, tfKey);
  const forText = _trendsFmtRespectedFor(cell.forSeconds, cell.unbounded);
  return React.createElement('div', { 'data-status': cell.status, style: { fontStyle: stale ? 'italic' : 'normal' } },
    React.createElement('div', {
      style: { fontSize: 13, fontWeight: stale ? 400 : 700, whiteSpace: 'nowrap',
        color: stale ? TRENDS_TEXT_SECONDARY : (cell.dir === 'BULLISH' ? TRENDS_BULL : TRENDS_BEAR) },
    }, TRENDS_STATE_LABELS[cell.dir]),
    forText !== null ? React.createElement('div', { style: Object.assign({}, small, { whiteSpace: 'nowrap' }) },
      'respected ' + forText) : null,
    React.createElement('div', { style: Object.assign({}, small, { whiteSpace: 'nowrap' }) },
      stale ? 'stale · last tag ' + cell.barsAgo + ' bars ago' : (age !== null ? 'last ' + age + ' ago' : '')),
    !stale && cell.retesting ? React.createElement('div', {
      style: { display: 'inline-block', marginTop: 3, padding: '0 6px', borderRadius: 3, fontSize: 11, fontWeight: 700,
        border: '1px solid ' + TRENDS_ACCENT, background: TRENDS_ACCENT_BG, color: TRENDS_TEXT_PRIMARY },
    }, 'testing') : null,
    cell.unbounded ? React.createElement('div', { style: small }, 'history limited') : null
  );
}

function TrendsRespectedTable({ items, sort, cycleSort, rankMap, tfs }) {
  const thStyle = (key) => ({
    cursor: 'pointer', userSelect: 'none', textAlign: 'left', padding: '10px 12px',
    fontSize: 11, fontWeight: 700, letterSpacing: '0.03em', background: TRENDS_HEADER_BG,
    color: sort.key === key ? TRENDS_TEXT_PRIMARY : TRENDS_TEXT_SECONDARY,
    borderBottom: '2px solid ' + TRENDS_BORDER, whiteSpace: 'nowrap',
  });
  const th = (txt, key) => React.createElement('th', { key, onClick: () => cycleSort(key), style: thStyle(key) },
    txt, sort.key === key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : '');
  const td = { padding: '10px 12px', fontSize: 13, color: TRENDS_TEXT_PRIMARY, borderBottom: '2px solid ' + TRENDS_BORDER, verticalAlign: 'top' };
  const linkStyle = {
    fontSize: 11, fontWeight: 700, color: TRENDS_TEXT_PRIMARY, textDecoration: 'none', whiteSpace: 'nowrap',
    border: '1px solid ' + TRENDS_BORDER, borderRadius: 3, padding: '1px 6px',
  };

  if (items.length === 0) {
    return React.createElement('div', { style: { fontSize: 13, color: TRENDS_TEXT_SECONDARY, padding: '24px 16px' } },
      'No coins have a respected trend on the ticked timeframes with these filters.');
  }

  return React.createElement('div', { style: { overflowX: 'auto' } },
    React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse' } },
      React.createElement('thead', null,
        React.createElement('tr', null,
          th('#', 'rank'), th('TOKEN', 'symbol'),
          tfs.map((tfKey) => th(TRENDS_TF_LABELS[tfKey], tfKey)),
          th('PRICE', 'price'), th('VOLUME 24H', 'volume'))
      ),
      React.createElement('tbody', null,
        items.map((item, i) => {
          const row = item.row;
          const tv = _trendsTvUrl(row), hl = _trendsHlUrl(row), tx = _trendsTxUrl(row);
          const vol = _trendsRespectVolume(row);
          return React.createElement('tr', {
            key: row.symbol, className: 'trends-row',
            style: { background: i % 2 === 0 ? TRENDS_BG : TRENDS_PANEL_BG },
          },
            React.createElement('td', { style: Object.assign({}, td, { color: TRENDS_TEXT_SECONDARY }) },
              rankMap.has(row.symbol) ? String(rankMap.get(row.symbol)) : '—'),
            React.createElement('td', { style: Object.assign({}, td, { fontWeight: 700 }) },
              _trendsDisplayName(row),
              _trendsIsTxflowOnly(row) ? React.createElement(TrendsTxflowTag) : null,
              (tv || hl || tx) ? React.createElement('div', { style: { display: 'flex', gap: 6, marginTop: 4 } },
                tv ? React.createElement('a', { href: tv, target: '_blank', rel: 'noopener noreferrer', style: linkStyle,
                  title: 'Open the Hyperliquid perp on TradingView' }, 'TV ↗') : null,
                hl ? React.createElement('a', { href: hl, target: '_blank', rel: 'noopener noreferrer', style: linkStyle,
                  title: 'Open the market on Hyperliquid' }, 'HL ↗') : null,
                tx ? React.createElement('a', { href: tx, target: '_blank', rel: 'noopener noreferrer', style: linkStyle,
                  title: 'Open the market on TxFlow' }, 'TX ↗') : null) : null),
            tfs.map((tfKey) => React.createElement('td', { key: tfKey, style: Object.assign({}, td, { minWidth: 130 }) },
              React.createElement(TrendsRespectCell, { cell: item.info.cells[tfKey], tfKey }))),
            React.createElement('td', { style: td }, typeof row.price === 'number' ? window.fmtPrice(row.price) : '—'),
            React.createElement('td', { style: td }, typeof vol === 'number' ? window.fmt(vol, 0) : '—')
          );
        })
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

function TrendsSidebar({ mode, filters, setFilters, selectedTf, setSelectedTf, refreshBusy, scanRun, scanDoneMsg, nowMs, onRefresh }) {
  // mode 'respected' (Landing 50c): the Respected trend tab keeps ASSET
  // CLASS, TOP BY VOLUME and Refresh, adds DIRECTION, TIMEFRAMES and
  // TESTING NOW, and hides the sections that only the Trends tab uses.
  const resp = mode === 'respected';
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

  function toggleRespTf(tfKey) {
    set((prev) => {
      const next = new Set(prev.respTfs);
      if (next.has(tfKey)) { if (next.size > 1) next.delete(tfKey); } else next.add(tfKey);
      return { respTfs: next };
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
      React.createElement(TrendsChipToggle, {
        active: filters.assetClasses.has('txflow'), label: 'TxFlow',
        onClick: () => toggleSetMember('assetClasses', 'txflow', 'assetClassOn'),
      }),
    ),
    React.createElement(TrendsSidebarSection, { title: 'ON TXFLOW', tip: TRENDS_TIPS.onTxflow,
      checked: filters.onTxflow, onCheck: (v) => set({ onTxflow: v }) },
      React.createElement('div', { style: { fontSize: 11, color: TRENDS_TEXT_SECONDARY, lineHeight: 1.4 } },
        'Coins TxFlow also lists, and the markets only TxFlow lists.')
    ),
    resp && React.createElement(TrendsSidebarSection, { title: 'DIRECTION', tip: TRENDS_TIPS.respDirection,
      checked: filters.respDirOn, onCheck: (v) => set({ respDirOn: v }) },
      React.createElement(TrendsChipToggle, {
        active: filters.respDir.has('BULLISH'), label: 'Bullish', color: TRENDS_BULL,
        onClick: () => toggleSetMember('respDir', 'BULLISH', 'respDirOn'),
      }),
      React.createElement(TrendsChipToggle, {
        active: filters.respDir.has('BEARISH'), label: 'Bearish', color: TRENDS_BEAR,
        onClick: () => toggleSetMember('respDir', 'BEARISH', 'respDirOn'),
      })
    ),
    resp && React.createElement(TrendsSidebarSection, { title: 'TIMEFRAMES', tip: TRENDS_TIPS.respTimeframes },
      TRENDS_RESPECT_TFS.map((tfKey) => React.createElement(TrendsChipToggle, {
        key: tfKey, active: filters.respTfs.has(tfKey), label: TRENDS_TF_LABELS[tfKey],
        onClick: () => toggleRespTf(tfKey),
      }))
    ),
    resp && React.createElement(TrendsSidebarSection, { title: 'TESTING NOW', tip: TRENDS_TIPS.respRetest,
      checked: filters.respRetest, onCheck: (v) => set({ respRetest: v }) },
      React.createElement('div', { style: { fontSize: 11, color: TRENDS_TEXT_SECONDARY, lineHeight: 1.4 } },
        'Price inside the band now on a respected timeframe.')
    ),
    !resp && React.createElement(TrendsSidebarSection, { title: 'SETUPS' },
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
        'Daily Trend at or under the Weekly Trend top; when below it, within ' + TRENDS_SETUP1_MAX_GAP_PCT + '%.'),
      React.createElement('div', { style: { borderTop: '2px solid ' + TRENDS_BORDER, margin: '12px 0 10px' } }),
      React.createElement(TrendsSetupRow, {
        label: 'Compression under Weekly', tip: TRENDS_TIPS.compression,
        checked: filters.compression, onCheck: (v) => set({ compression: v }),
      }),
      React.createElement('div', { style: { fontSize: 11, color: TRENDS_TEXT_SECONDARY, marginTop: 2, lineHeight: 1.4 } },
        'Daily and Weekly Trend EMAs within ' + TRENDS_COMPRESSION_MAX_WIDTH_PCT + '% of each other, price within ' + TRENDS_COMPRESSION_PRICE_PCT + '% of them, Daily Trend below.')
    ),
    !resp && React.createElement(TrendsSidebarSection, { title: 'TREND', tip: TRENDS_TIPS.trend,
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
    !resp && React.createElement(TrendsSidebarSection, { title: 'TREND CONFLUENCE',
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
    !resp && React.createElement(TrendsSidebarSection, { title: 'ALIGNMENT (EMA)', tip: TRENDS_TIPS.alignment,
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
    !resp && React.createElement(TrendsSidebarSection, { title: 'TIME SINCE FLIPPED', tip: TRENDS_TIPS.timeSinceFlipped,
      checked: filters.timeSinceOn, onCheck: (v) => set({ timeSinceOn: v }) },
      React.createElement('select', {
        value: filters.timeSinceFlipped, style: selectStyle, 'aria-label': 'Time since flipped',
        onChange: (e) => set({ timeSinceFlipped: e.target.value, timeSinceOn: true }),
      }, TRENDS_TIME_SINCE_FLIPPED_OPTIONS.map((o) =>
        React.createElement('option', { key: o.label, value: o.label }, o.label)))
    ),
    !resp && React.createElement(TrendsSidebarSection, { title: 'NEAR FLIP', tip: TRENDS_TIPS.nearFlip,
      checked: filters.nearFlip, onCheck: (v) => set({ nearFlip: v }) },
      React.createElement(TrendsTip, { tip: TRENDS_TIPS.nearFlipThreshold, block: true },
        React.createElement('select', {
          value: filters.nearFlipThreshold, style: selectStyle, 'aria-label': 'Near flip distance',
          onChange: (e) => set({ nearFlipThreshold: Number(e.target.value), nearFlip: true }),
        }, TRENDS_NEAR_FLIP_THRESHOLDS.map((t) =>
          React.createElement('option', { key: t, value: t }, '< ' + t + '%'))))
    ),
    !resp && React.createElement(TrendsSidebarSection, { title: 'HIDE CHOPPY', tip: TRENDS_TIPS.hideChoppy,
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
    !resp && React.createElement(TrendsSidebarSection, { title: 'TIMEFRAME', tip: TRENDS_TIPS.timeframe },
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
      respDir: new Set(TRENDS_RESPECT_DIRS), respTfs: new Set(TRENDS_RESPECT_TFS),
      assetClasses: new Set(TRENDS_ALL_ASSET_CLASSES) }));
  const [sort, setSort] = React.useState({ key: 'volume', dir: 'desc' });
  // Landing 50c: the Respected trend tab, remembered in this browser only
  // (storage can be missing or throw; the page then opens on Trends).
  const [tab, setTabState] = React.useState(() => {
    try { return localStorage.getItem(TRENDS_TAB_STORAGE_KEY) === 'respected' ? 'respected' : 'trends'; }
    catch (e) { return 'trends'; }
  });
  function setTab(t) {
    setTabState(t);
    try { localStorage.setItem(TRENDS_TAB_STORAGE_KEY, t); } catch (e) {}
  }
  const [rsort, setRsort] = React.useState({ key: null, dir: null });
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

  // Respected tab headers: a first click sorts numbers high to low (names
  // and rank A to Z / 1 up), a second click reverses, a third goes back to
  // the default order (most counted timeframes, then volume).
  function cycleRsort(key) {
    const first = key === 'symbol' || key === 'rank' ? 'asc' : 'desc';
    setRsort((prev) => prev.key !== key ? { key, dir: first }
      : prev.dir === first ? { key, dir: first === 'asc' ? 'desc' : 'asc' } : { key: null, dir: null });
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
    // Markets only TxFlow lists are not ranked (Landing 53, ruling 6-A): one
    // venue's volume is not comparable with Hyperliquid's, and Top by volume
    // would otherwise mix thin TxFlow markets into Hyperliquid's tail.
    const withVol = searchAndSidebarFiltered
      .filter((r) => !_trendsIsTxflowOnly(r))
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

  // Respected trend tab: listed coins, their volume rank (before Top by
  // volume, as on the Trends tab), the Top-N cut, then the sort.
  const respList = React.useMemo(
    () => (tab === 'respected' ? _trendsRespectedList(rows, filters, nowMs) : []),
    [rows, filters, tab]);
  const respRankMap = React.useMemo(() => {
    const m = new Map();
    respList.filter((it) => !_trendsIsTxflowOnly(it.row))        // not ranked, as on the Trends tab
      .map((it) => ({ symbol: it.row.symbol, vol: _trendsRespectVolume(it.row) }))
      .filter((x) => typeof x.vol === 'number')
      .sort((a, b) => b.vol - a.vol)
      .forEach((x, i) => m.set(x.symbol, i + 1));
    return m;
  }, [respList]);
  const respSorted = React.useMemo(() => {
    let list = respList;
    if (filters.topVolumeOn && filters.topVolume !== 'all') {
      const n = TRENDS_TOP_VOLUME_N[filters.topVolume];
      list = list.filter((it) => { const r = respRankMap.get(it.row.symbol); return typeof r === 'number' && r <= n; });
    }
    const out = list.slice();
    if (!rsort.key) {
      return out.sort((a, b) => (b.info.counted.length - a.info.counted.length)
        || ((_trendsRespectVolume(b.row) || 0) - (_trendsRespectVolume(a.row) || 0)));
    }
    const dirMul = rsort.dir === 'desc' ? -1 : 1;
    return out.sort((a, b) => {
      const va = _trendsRespectSortValue(a, rsort.key, respRankMap), vb = _trendsRespectSortValue(b, rsort.key, respRankMap);
      const aMissing = va === null || va === undefined, bMissing = vb === null || vb === undefined;
      if (aMissing && bMissing) return 0;
      if (aMissing) return 1;
      if (bMissing) return -1;
      if (typeof va === 'string') return dirMul * va.localeCompare(vb);
      return dirMul * (va - vb);
    });
  }, [respList, respRankMap, rsort, filters.topVolume, filters.topVolumeOn]);
  const respTfs = TRENDS_RESPECT_TFS.filter((t) => filters.respTfs.has(t));

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
    React.createElement(TrendsTabs, { tab, setTab }),
    loadError && React.createElement('div', { style: { color: TRENDS_BEAR, fontSize: 13, marginBottom: 12 } }, loadError),
    rows.length === 0
      ? React.createElement('div', { style: { fontSize: 13, color: TRENDS_TEXT_SECONDARY } }, 'No scan data yet.')
      : React.createElement(React.Fragment, null,
          tab === 'trends' ? React.createElement('div', { style: { marginBottom: 16 } },
            React.createElement(TrendsStatsStrip, { rows, selectedTf })
          ) : React.createElement('div', { style: { fontSize: 12, color: TRENDS_TEXT_SECONDARY, marginBottom: 12, lineHeight: 1.5, maxWidth: 900 } },
            'A timeframe counts when its noodle band is sloping and the history has ' + TRENDS_RESPECT_MIN_TAGS + '+ tags, fewer than '
            + (TRENDS_RESPECT_MAX_LOSSES + 1) + ' losses (two closes in a row beyond the band) and its latest tag within '
            + TRENDS_RESPECT_WINDOW_BARS + ' bars. Dimmed cells are stale (latest tag older than ' + TRENDS_RESPECT_WINDOW_BARS
            + ' bars) and do not count; Ranging means the band went flat after a respected history, and does not count either.'),
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
              tab === 'trends' ? React.createElement(TrendsTable, {
                rows: sorted, sort, cycleSort, selectedTf, rankMap, expanded, toggleExpand, nowMs, windowDays,
                setup1Recency: filters.setup1 ? filters.setup1Recency : null,
                compressionOn: filters.compression,
              }) : React.createElement(TrendsRespectedTable, {
                items: respSorted, sort: rsort, cycleSort: cycleRsort, rankMap: respRankMap, tfs: respTfs,
              })
            ),
            React.createElement(TrendsSidebar, {
              mode: tab, filters, setFilters, selectedTf, setSelectedTf,
              refreshBusy, scanRun, scanDoneMsg, nowMs, onRefresh: handleRefresh,
            })
          )
        )
  );
}

window.TrendsScreen = TrendsScreen;
