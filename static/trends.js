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

const TRENDS_TOP_VOLUME_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'top20', label: 'Top 20' },
  { value: 'top50', label: 'Top 50' },
  { value: 'top100', label: 'Top 100' },
];

const TRENDS_ALL_TREND_STATES = ['BULLISH', 'BEARISH', 'WARMUP'];
const TRENDS_ALL_ALIGNMENT_STATES = ['BULLISH', 'BEARISH', 'NEUTRAL'];

const TRENDS_FILTER_DEFAULTS = {
  trend: new Set(TRENDS_ALL_TREND_STATES),
  alignment: new Set(TRENDS_ALL_ALIGNMENT_STATES),
  confluenceAll3: false,
  confluenceDW: false,
  confluence4H: false,
  timeSinceFlipped: 'Any time',
  topVolume: 'all',
  search: '',
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

function _trendsPassesSearchAndSidebar(row, filters, selectedTf, nowMs) {
  const tf = row.timeframes[selectedTf] || {};
  if (!_trendsPassesMultiFilter(filters.trend, TRENDS_ALL_TREND_STATES, tf.state)) return false;
  if (!_trendsPassesMultiFilter(filters.alignment, TRENDS_ALL_ALIGNMENT_STATES, tf.alignment_state)) return false;
  if (filters.confluenceAll3 || filters.confluenceDW || filters.confluence4H) {
    const conf = _trendsConfluence(row.timeframes);
    const matchesAny3 = filters.confluenceAll3 && conf.all3;
    const matchesDW = filters.confluenceDW && conf.dw;
    const matches4H = filters.confluence4H && conf.fourHAgrees;
    if (!matchesAny3 && !matchesDW && !matches4H) return false;
  }
  if (!_trendsPassesTimeSinceFlipped(tf, filters.timeSinceFlipped, nowMs)) return false;
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
          React.createElement('th', { style: thStyle }, 'TIME SINCE FLIP'),
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
            React.createElement('td', { style: tdStyle, title: flipAgeTooltip }, flipAge)
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
    tile('Full confluence', stats.confluence + ' (all 3 TFs agree)', TRENDS_ACCENT)
  );
}

/* ── table ── */

function TrendsTable({ rows, sort, cycleSort, selectedTf, rankMap, expanded, toggleExpand, nowMs, windowDays }) {
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
          sortableTh('TIME SINCE FLIP', 'flip'),
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
                row.symbol
              ),
              React.createElement('td', { style: td }, React.createElement(TrendsTrendCell, { timeframes: row.timeframes, selectedTf })),
              React.createElement('td', { style: td }, React.createElement(TrendsAlignmentChip, { state: tf.alignment_state })),
              React.createElement('td', { style: td }, React.createElement(TrendsPriorAlignmentCell, { tf, nowMs, timeframe: selectedTf, windowDays })),
              React.createElement('td', { style: Object.assign({}, td, { color: pct === null ? TRENDS_TEXT_SECONDARY : (pct >= 0 ? TRENDS_BULL : TRENDS_BEAR) }) },
                pct !== null ? window.fmtPct(pct) : '—'),
              React.createElement('td', { style: td, title: flipTooltip }, flipDisplay),
              React.createElement('td', { style: td }, typeof row.price === 'number' ? window.fmtPrice(row.price) : '—'),
              React.createElement('td', { style: td }, typeof tf.volume_24h === 'number' ? window.fmt(tf.volume_24h, 0) : '—'),
            ),
          ];
          if (isExpanded) {
            rowNodes.push(
              React.createElement('tr', { key: row.symbol + '-sub' },
                React.createElement('td', { colSpan: 9, style: { padding: '0 12px', background: rowBg, borderBottom: '2px solid ' + TRENDS_BORDER } },
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

function TrendsChipToggle({ active, label, onClick, color }) {
  return React.createElement('button', {
    onClick,
    style: {
      padding: '5px 12px', borderRadius: 999, fontSize: 12, cursor: 'pointer',
      border: '1px solid ' + (active ? (color || TRENDS_ACCENT) : TRENDS_BORDER),
      background: active ? (color ? color + '33' : TRENDS_ACCENT_BG) : 'transparent',
      color: active ? TRENDS_TEXT_PRIMARY : TRENDS_TEXT_SECONDARY,
      fontWeight: active ? 700 : 400, marginRight: 6, marginBottom: 6,
    },
  }, label);
}

function TrendsSidebarSection({ title, children }) {
  return React.createElement('div', { style: { marginBottom: 20 } },
    React.createElement('div', {
      style: { fontSize: 11, fontWeight: 700, letterSpacing: '0.05em', color: TRENDS_TEXT_SECONDARY, marginBottom: 8 },
    }, title),
    children
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
  function toggleSetMember(field, value) {
    setFilters((prev) => {
      const next = new Set(prev[field]);
      if (next.has(value)) next.delete(value); else next.add(value);
      return Object.assign({}, prev, { [field]: next });
    });
  }

  const selectStyle = {
    width: '100%', fontSize: 12, padding: '6px 8px', borderRadius: 4,
    border: '1px solid ' + TRENDS_BORDER, background: TRENDS_PANEL_BG, color: TRENDS_TEXT_PRIMARY,
  };

  return React.createElement('div', {
    style: {
      width: 300, flexShrink: 0, background: TRENDS_PANEL_BG, border: '1px solid ' + TRENDS_BORDER,
      borderRadius: 8, padding: 16, alignSelf: 'flex-start', position: 'sticky', top: 12,
    },
  },
    React.createElement(TrendsSidebarSection, { title: 'TREND' },
      React.createElement(TrendsChipToggle, {
        active: filters.trend.has('BULLISH'), label: 'Bullish', color: TRENDS_BULL,
        onClick: () => toggleSetMember('trend', 'BULLISH'),
      }),
      React.createElement(TrendsChipToggle, {
        active: filters.trend.has('BEARISH'), label: 'Bearish', color: TRENDS_BEAR,
        onClick: () => toggleSetMember('trend', 'BEARISH'),
      }),
      React.createElement(TrendsChipToggle, {
        active: filters.trend.has('WARMUP'), label: 'Neutral', color: TRENDS_NEUTRAL,
        onClick: () => toggleSetMember('trend', 'WARMUP'),
      }),
    ),
    React.createElement(TrendsSidebarSection, { title: 'CONFLUENCE' },
      React.createElement(TrendsChipToggle, {
        active: filters.confluenceAll3, label: 'All 3 agree',
        onClick: () => setFilters((prev) => Object.assign({}, prev, { confluenceAll3: !prev.confluenceAll3 })),
      }),
      React.createElement(TrendsChipToggle, {
        active: filters.confluence4H, label: '4H agrees',
        onClick: () => setFilters((prev) => Object.assign({}, prev, { confluence4H: !prev.confluence4H })),
      }),
      React.createElement(TrendsChipToggle, {
        active: filters.confluenceDW, label: 'Daily = Weekly',
        onClick: () => setFilters((prev) => Object.assign({}, prev, { confluenceDW: !prev.confluenceDW })),
      }),
    ),
    React.createElement(TrendsSidebarSection, { title: 'ALIGNMENT (EMA)' },
      React.createElement(TrendsChipToggle, {
        active: filters.alignment.has('BULLISH'), label: 'Bullish', color: TRENDS_BULL,
        onClick: () => toggleSetMember('alignment', 'BULLISH'),
      }),
      React.createElement(TrendsChipToggle, {
        active: filters.alignment.has('BEARISH'), label: 'Bearish', color: TRENDS_BEAR,
        onClick: () => toggleSetMember('alignment', 'BEARISH'),
      }),
      React.createElement(TrendsChipToggle, {
        active: filters.alignment.has('NEUTRAL'), label: 'Neutral', color: TRENDS_NEUTRAL,
        onClick: () => toggleSetMember('alignment', 'NEUTRAL'),
      }),
    ),
    React.createElement(TrendsSidebarSection, { title: 'TIME SINCE FLIPPED' },
      React.createElement('select', {
        value: filters.timeSinceFlipped, style: selectStyle,
        onChange: (e) => setFilters((prev) => Object.assign({}, prev, { timeSinceFlipped: e.target.value })),
      }, TRENDS_TIME_SINCE_FLIPPED_OPTIONS.map((o) =>
        React.createElement('option', { key: o.label, value: o.label }, o.label)))
    ),
    React.createElement(TrendsSidebarSection, { title: 'TIMEFRAME' },
      TRENDS_TIMEFRAMES.map((tfKey) => React.createElement(TrendsChipToggle, {
        key: tfKey, active: selectedTf === tfKey, label: TRENDS_TF_FULL_LABELS[tfKey],
        onClick: () => setSelectedTf(tfKey),
      }))
    ),
    React.createElement(TrendsSidebarSection, { title: 'TOP BY VOLUME' },
      React.createElement('select', {
        value: filters.topVolume, style: selectStyle,
        onChange: (e) => setFilters((prev) => Object.assign({}, prev, { topVolume: e.target.value })),
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
      React.createElement('button', {
        style: {
          width: '100%', fontSize: 12, padding: '8px 10px', borderRadius: 4, cursor: refreshBusy ? 'default' : 'pointer',
          border: '1px solid ' + TRENDS_ACCENT, background: refreshBusy ? 'transparent' : TRENDS_ACCENT_BG,
          color: TRENDS_TEXT_PRIMARY, fontWeight: 700,
        },
        disabled: refreshBusy, onClick: onRefresh,
      }, refreshBusy ? 'Scanning…' : 'Refresh'),
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
    { trend: new Set(TRENDS_ALL_TREND_STATES), alignment: new Set(TRENDS_ALL_ALIGNMENT_STATES) }));
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
    if (filters.topVolume === 'all') return searchAndSidebarFiltered;
    const n = TRENDS_TOP_VOLUME_N[filters.topVolume];
    return searchAndSidebarFiltered.filter((r) => {
      const rank = rankMap.get(r.symbol);
      return typeof rank === 'number' && rank <= n;
    });
  }, [searchAndSidebarFiltered, filters.topVolume, rankMap]);

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
              React.createElement(TrendsTable, { rows: sorted, sort, cycleSort, selectedTf, rankMap, expanded, toggleExpand, nowMs, windowDays })
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
