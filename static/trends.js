/* ===== TRENDS SCREEN (MA-band / "Noodle" scanner) =====
   Display-only screen over GET /api/trading/scanner/noodle-state.
   Never recomputes engine math - state/flip/alignment are read
   straight off the payload; the only client-side "math" here is
   display-only derivation (time-since-flip, %-since-flip, the
   alignment label/color bucket) over already-computed fields.
   Styling convention follows scout.js/pl.js: React.createElement,
   tv-* shared classes for chrome, inline styles for bespoke bits. */

const TRENDS_TIMEFRAMES = ['12h', '1d', '1w'];
const TRENDS_TF_LABELS = { '12h': '12H', '1d': '1D', '1w': '1W' };

// WARMUP's user-facing label is "Neutral" (Glenn, this session) -
// display-only remap. The API's literal string, internal sort ranks,
// and filter values all stay 'WARMUP' - only this label lookup and
// the filter chip's rendered text change.
const TRENDS_STATE_LABELS = { BULLISH: 'Bullish', BEARISH: 'Bearish', WARMUP: 'Neutral' };
const TRENDS_STATE_COLORS = {
  BULLISH: { color: '#4ade80', bg: 'rgba(74,222,128,0.14)' },
  BEARISH: { color: '#f0a0a0', bg: 'rgba(240,120,120,0.14)' },
  WARMUP:  { color: '#facc15', bg: 'rgba(250,204,21,0.14)' },
};
// Judgment-set sort order (not alphabetical) - same convention as
// maxfi.js's MX_VERDICT_RANK. Arbitrary directional ordering:
// bullish first, neutral middle, bearish last.
const TRENDS_STATE_RANK = { BULLISH: 0, WARMUP: 1, BEARISH: 2 };

// Alignment gradient RGB triples reused verbatim from maxfi.js's own
// MX_C.accentBright/MX_C.warn tint formula (rgba(74,222,128,x) /
// rgba(240,120,120,x)) plus its edgeNeutral gray (#8b949e ->
// 139,148,158) - no new hex values invented this session.
const TRENDS_ALIGN_GREEN_RGB = '74,222,128';
const TRENDS_ALIGN_RED_RGB = '240,120,120';
const TRENDS_ALIGN_GRAY = '#8b949e';
const TRENDS_ALIGN_GRAY_BG = 'rgba(139,148,158,0.14)';
// Level 1/2/3 -> increasing background-tint opacity. Color/label carry
// the level, never opacity alone.
const TRENDS_ALIGN_ALPHAS = [0.08, 0.15, 0.24];

const TRENDS_FILTER_DEFAULTS = { state: 'all', search: '' };

/* ── pure helpers ── */

function _trendsExtractErr(e) {
  let msg = (e && e.message) ? e.message : String(e);
  try {
    const j = JSON.parse(msg);
    if (j) msg = j.detail || j.error || msg;
  } catch (e2) {}
  return msg;
}

// Local duration humanizer - epoch seconds in, "Xd Yh" / "Xh Ym" / "Ym"
// out. No existing helper in utils.js covers sub-day granularity
// (daysAgo() is ISO-string, day-only) so this is written fresh here,
// same precedent as scout.js's local display helpers.
function _trendsDuration(nowMs, epochSeconds) {
  if (epochSeconds === null || epochSeconds === undefined) return null;
  const diffSec = Math.max(0, Math.floor(nowMs / 1000) - epochSeconds);
  const days = Math.floor(diffSec / 86400);
  const hours = Math.floor((diffSec % 86400) / 3600);
  if (days > 0) return days + 'd ' + hours + 'h';
  const mins = Math.floor((diffSec % 3600) / 60);
  if (hours > 0) return hours + 'h ' + mins + 'm';
  return mins + 'm';
}

function _trendsPctSinceFlip(currentPrice, flipPrice) {
  if (typeof currentPrice !== 'number' || typeof flipPrice !== 'number' || flipPrice === 0) return null;
  return ((currentPrice - flipPrice) / flipPrice) * 100;
}

// Alignment mapping - see CONTEXT above for the derivation. Returns
// null (render nothing) when alignment is undefined (too-short
// history, the WARMUP variant where nothing at all is computable).
function _trendsAlignmentInfo(bull, bear) {
  if (bull === null || bull === undefined || bear === null || bear === undefined) return null;
  if (bull === bear) {
    return { label: 'Neutral', color: TRENDS_ALIGN_GRAY, bg: TRENDS_ALIGN_GRAY_BG };
  }
  const isBull = bull > bear;
  const level = Math.min(3, Math.max(bull, bear));
  const rgb = isBull ? TRENDS_ALIGN_GREEN_RGB : TRENDS_ALIGN_RED_RGB;
  const color = isBull ? '#4ade80' : '#f0a0a0';
  const alpha = TRENDS_ALIGN_ALPHAS[level - 1];
  return { label: (isBull ? 'Bull L' : 'Bear L') + level, color, bg: 'rgba(' + rgb + ',' + alpha + ')' };
}

function _trendsSortValue(row, key, selectedTf) {
  const tf = row.timeframes[selectedTf] || {};
  if (key === 'symbol') return row.symbol;
  if (key === 'price') return typeof row.price === 'number' ? row.price : null;
  if (key === 'state') return TRENDS_STATE_RANK[tf.state] !== undefined ? TRENDS_STATE_RANK[tf.state] : null;
  if (key === 'flip') {
    if (tf.flip_age_unbounded === true) return -1; // "> window" sorts as oldest
    return typeof tf.flip_ts === 'number' ? tf.flip_ts : null;
  }
  if (key === 'pct') return _trendsPctSinceFlip(tf.price, tf.flip_price);
  return null;
}

function _trendsPassesFilters(row, filters, selectedTf) {
  const tf = row.timeframes[selectedTf] || {};
  if (filters.state !== 'all' && tf.state !== filters.state) return false;
  const q = filters.search.trim().toUpperCase();
  if (q && row.symbol.toUpperCase().indexOf(q) === -1) return false;
  return true;
}

/* ── small presentational pieces ── */

function TrendsStateChip({ state }) {
  if (!state) return React.createElement('span', { style: { color: 'var(--text4)' } }, '—');
  const s = TRENDS_STATE_COLORS[state] || TRENDS_STATE_COLORS.WARMUP;
  const label = TRENDS_STATE_LABELS[state] || state;
  return React.createElement('span', {
    style: { display: 'inline-block', color: s.color, border: '1px solid ' + s.color,
      background: s.bg, borderRadius: 4, padding: '1px 6px', fontSize: 12, fontWeight: 700 },
  }, label);
}

function TrendsAlignmentBadge({ bull, bear }) {
  const info = _trendsAlignmentInfo(bull, bear);
  if (!info) return null;
  return React.createElement('span', {
    style: { display: 'inline-block', color: info.color, border: '1px solid ' + info.color,
      background: info.bg, borderRadius: 4, padding: '0px 5px', fontSize: 11, fontWeight: 600, marginTop: 2 },
  }, info.label);
}

function TrendsTfCell({ tf, nowMs }) {
  if (!tf) return React.createElement('div', { style: { color: 'var(--text4)' } }, '—');
  let flipTitle = null;
  if (tf.flip_age_unbounded === true) flipTitle = 'flip occurred before the fetched candle window';
  else if (tf.flip_ts) flipTitle = 'flipped ' + new Date(tf.flip_ts * 1000).toLocaleString();
  return React.createElement('div', { title: flipTitle, style: { display: 'flex', flexDirection: 'column', gap: 2 } },
    React.createElement(TrendsStateChip, { state: tf.state }),
    React.createElement(TrendsAlignmentBadge, { bull: tf.alignment_bull, bear: tf.alignment_bear })
  );
}

function TrendsTfToggle({ selected, onChange }) {
  return React.createElement('div', { style: { display: 'inline-flex', gap: 4 } },
    TRENDS_TIMEFRAMES.map((tfKey) => React.createElement('button', {
      key: tfKey,
      className: 'tv-btn',
      style: {
        fontSize: 12, padding: '4px 10px',
        borderColor: selected === tfKey ? 'var(--accent)' : undefined,
        color: selected === tfKey ? 'var(--accent)' : undefined,
      },
      onClick: () => onChange(tfKey),
    }, TRENDS_TF_LABELS[tfKey]))
  );
}

function TrendsFilterBar({ filters, setFilters, rows, selectedTf }) {
  // Facet counts respect the search term but never the state dimension
  // itself - same "what would show if this chip were chosen" honesty
  // convention as scout.js's facet counts.
  const counts = React.useMemo(() => {
    const base = Object.assign({}, filters, { state: 'all' });
    const c = { all: 0, BULLISH: 0, WARMUP: 0, BEARISH: 0 };
    rows.forEach((r) => {
      if (!_trendsPassesFilters(r, base, selectedTf)) return;
      c.all++;
      const st = (r.timeframes[selectedTf] || {}).state;
      if (st && c[st] !== undefined) c[st]++;
    });
    return c;
  }, [rows, filters, selectedTf]);

  function chip(stateKey, label) {
    const active = filters.state === stateKey;
    return React.createElement('button', {
      key: stateKey,
      onClick: () => setFilters(Object.assign({}, filters, { state: stateKey })),
      style: {
        padding: '4px 12px', borderRadius: 999, fontSize: 12, cursor: 'pointer',
        border: '1px solid ' + (active ? 'var(--accent)' : 'rgba(255,255,255,0.25)'),
        background: active ? 'var(--accent-soft)' : 'transparent',
        color: active ? 'var(--accent)' : 'var(--text3)',
        fontWeight: active ? 600 : 400,
        display: 'inline-flex', alignItems: 'center', gap: 6,
      },
    }, label, React.createElement('span', { style: { fontSize: 11, opacity: 0.85 } }, counts[stateKey]));
  }

  return React.createElement('div', { style: { display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' } },
    chip('all', 'All'), chip('BULLISH', 'Bullish'), chip('WARMUP', 'Neutral'), chip('BEARISH', 'Bearish'),
    React.createElement('input', {
      type: 'text', placeholder: 'Search token…', value: filters.search,
      onChange: (e) => setFilters(Object.assign({}, filters, { search: e.target.value })),
      className: 'tv-input',
      style: { fontSize: 12, padding: '4px 10px', marginLeft: 8 },
    })
  );
}

function TrendsTable({ rows, sort, cycleSort, selectedTf }) {
  const nowMs = Date.now();
  const sortableTh = (txt, key) => React.createElement('th', {
    onClick: () => cycleSort(key),
    style: { cursor: 'pointer', userSelect: 'none', color: sort.key === key ? 'var(--text)' : 'var(--text4)' },
  }, txt, sort.key === key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : '');

  if (rows.length === 0) {
    return React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)', padding: '20px 0' } },
      'No tokens match the current filters.');
  }

  return React.createElement('div', { style: { overflowX: 'auto' } },
    React.createElement('table', { className: 'tv-table', style: { width: '100%' } },
      React.createElement('thead', null,
        React.createElement('tr', null,
          sortableTh('TOKEN', 'symbol'),
          sortableTh('PRICE', 'price'),
          React.createElement('th', null, '12H'),
          React.createElement('th', null, '1D'),
          React.createElement('th', null, '1W'),
          sortableTh('TIME SINCE FLIP (' + TRENDS_TF_LABELS[selectedTf] + ')', 'flip'),
          sortableTh('% SINCE FLIP (' + TRENDS_TF_LABELS[selectedTf] + ')', 'pct')
        )
      ),
      React.createElement('tbody', null,
        rows.map((row) => {
          const tf = row.timeframes[selectedTf] || {};
          let flipDisplay = '—';
          if (tf.flip_age_unbounded === true) flipDisplay = '> window';
          else if (typeof tf.flip_ts === 'number') flipDisplay = _trendsDuration(nowMs, tf.flip_ts);
          const pct = _trendsPctSinceFlip(tf.price, tf.flip_price);
          return React.createElement('tr', { key: row.symbol },
            React.createElement('td', { style: { fontWeight: 600, color: 'var(--text)' } }, row.symbol),
            React.createElement('td', null, typeof row.price === 'number' ? window.fmtPrice(row.price) : '—'),
            React.createElement('td', null, React.createElement(TrendsTfCell, { tf: row.timeframes['12h'], nowMs })),
            React.createElement('td', null, React.createElement(TrendsTfCell, { tf: row.timeframes['1d'], nowMs })),
            React.createElement('td', null, React.createElement(TrendsTfCell, { tf: row.timeframes['1w'], nowMs })),
            React.createElement('td', null, flipDisplay),
            React.createElement('td', null, pct !== null ? window.fmtPct(pct) : '—')
          );
        })
      )
    )
  );
}

/* ── main screen ── */

function TrendsScreen() {
  const [data, setData] = React.useState({ symbols: [] });
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState(null);
  const [fetchedAt, setFetchedAt] = React.useState(null);
  const [filters, setFilters] = React.useState(Object.assign({}, TRENDS_FILTER_DEFAULTS));
  const [sort, setSort] = React.useState({ key: 'symbol', dir: 'asc' });
  const [selectedTf, setSelectedTf] = React.useState('1d');
  const [refreshBusy, setRefreshBusy] = React.useState(false);
  const [refreshMsg, setRefreshMsg] = React.useState(null);

  const mountedRef = React.useRef(true);
  React.useEffect(() => { return () => { mountedRef.current = false; }; }, []);

  async function load() {
    setLoadError(null);
    try {
      const d = await api('/api/trading/scanner/noodle-state');
      if (d === undefined || d === null) {
        setLoadError('session expired');
        setLoading(false);
        return;
      }
      setData({ symbols: d.symbols || [] });
      setFetchedAt(new Date());
      setLoading(false);
    } catch (e) {
      setLoadError(_trendsExtractErr(e));
      setLoading(false);
    }
  }

  React.useEffect(() => { load(); }, []);

  // CONFIRMED FROM web_portfolio.py: this POST route runs the full scan
  // pass synchronously (no background thread, unlike the on-view
  // auto-trigger) - a full pass is ~7-9 min minimum. The button below
  // says so and stays disabled for the whole wait; a 409 RefreshBusy
  // (an auto-trigger or another manual click already holds the lock)
  // is expected/benign, not an alarm-red error.
  async function handleRefresh() {
    setRefreshMsg(null);
    setRefreshBusy(true);
    try {
      const d = await api('/api/trading/scanner/noodle-refresh', { method: 'POST' });
      if (!mountedRef.current) return;
      if (d === undefined || d === null) {
        setRefreshMsg('session expired');
      } else {
        setRefreshMsg('scanned ' + d.scanned + ' · errors ' + d.errors + ' · retired ' + d.retired);
        await load();
      }
    } catch (e) {
      if (!mountedRef.current) return;
      const msg = _trendsExtractErr(e);
      setRefreshMsg(msg.indexOf('already running') !== -1 ? 'a scan is already running — showing current data' : msg);
    } finally {
      if (mountedRef.current) setRefreshBusy(false);
    }
  }

  function cycleSort(key) {
    setSort((prev) => prev.key !== key ? { key, dir: 'asc' }
      : prev.dir === 'asc' ? { key, dir: 'desc' } : { key: null, dir: null });
  }

  const rows = data.symbols;
  const filtered = React.useMemo(
    () => rows.filter((r) => _trendsPassesFilters(r, filters, selectedTf)),
    [rows, filters, selectedTf]);

  const sorted = React.useMemo(() => {
    const key = sort.key || 'symbol';
    const dir = sort.key ? sort.dir : 'asc';
    const dirMul = dir === 'desc' ? -1 : 1;
    return filtered.slice().sort((a, b) => {
      const va = _trendsSortValue(a, key, selectedTf), vb = _trendsSortValue(b, key, selectedTf);
      const aMissing = va === null || va === undefined;
      const bMissing = vb === null || vb === undefined;
      if (aMissing && bMissing) return 0;
      if (aMissing) return 1;
      if (bMissing) return -1;
      if (typeof va === 'string') return dirMul * va.localeCompare(vb);
      return dirMul * (va - vb);
    });
  }, [filtered, sort, selectedTf]);

  if (loading) {
    return React.createElement('div', {
      style: { display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 320, color: 'var(--text3)', fontSize: 14 },
    }, 'Loading Trends…');
  }

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
    React.createElement('div', null,
      React.createElement('div', { className: 'tv-page-title', style: { marginBottom: 4 } }, 'Trends'),
      React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' } },
        React.createElement(TrendsTfToggle, { selected: selectedTf, onChange: setSelectedTf }),
        React.createElement('div', { style: { fontSize: 12, color: 'var(--text3)' } },
          fetchedAt ? 'Loaded ' + fetchedAt.toLocaleString() : ''),
        React.createElement('button', {
          className: 'tv-btn', style: { fontSize: 12, padding: '4px 10px' },
          disabled: refreshBusy, onClick: handleRefresh,
          title: 'A full scan pass takes roughly 7-9 minutes - this button waits for it.',
        }, refreshBusy ? 'Scanning… (~7-9 min)' : 'Refresh')
      ),
      refreshMsg && React.createElement('div', { style: { fontSize: 12, color: 'var(--text3)', marginTop: 2 } }, refreshMsg)
    ),
    loadError && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13 } }, loadError),
    rows.length === 0
      ? React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)' } }, 'No scan data yet.')
      : React.createElement(React.Fragment, null,
          React.createElement(TrendsFilterBar, { filters, setFilters, rows, selectedTf }),
          React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
            React.createElement(TrendsTable, { rows: sorted, sort, cycleSort, selectedTf })
          )
        )
  );
}

window.TrendsScreen = TrendsScreen;
