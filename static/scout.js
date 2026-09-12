/* ===== POOL SCOUT SCREEN ===== */
//
// Display-only screen over GET /api/maxfi/advisor's entry_candidates (now
// sharp-dump-gated and liquidity-floor-flagged - see maxfi_pooldata.py's
// downtrend_gate and maxfi_advisor.py's ADVISOR_ENTRY_LIQUIDITY_FLOOR_USD).
// This file NEVER recomputes verdict/gate/floor logic - every blocked/
// sharp_dump/below_liquidity_floor value rendered here is read straight off
// the payload. The only "math" in this file is client-side, display-only
// derivation (a pool label from symbols, a VOL/TVL ratio for the column,
// and the two judgment-set volume-temperature thresholds below) plus
// filter/sort predicates over already-computed fields.
//
// Styling convention follows checklist.js/pl.js: React.createElement, the
// tv-* shared classes for chrome, inline styles for bespoke bits.

/* ── judgment-set display constants (NOT verdict/gate logic) ── */

// Volume-temperature badge thresholds on volume_mult (same-snapshot h6x4-
// vs-h24 approximation, see maxfi_advisor.ENTRY_VOLUME_MULTIPLIER_SOURCE).
// Purely a display bucket - never fed back into entry_score or any gate.
const SCOUT_VOL_HEAT = 1.5;
const SCOUT_VOL_COOL = 0.7;

/* ── pure helpers ── */

// api() throws Error(<raw response text>) on any non-2xx - same JSON-first
// extraction as pl.js's _plExtractErr/maxfi.js's mxExtractErr.
function _scoutExtractErr(e) {
  let msg = (e && e.message) ? e.message : String(e);
  try {
    const j = JSON.parse(msg);
    if (j) msg = j.detail || j.error || msg;
  } catch (e2) {}
  return msg;
}

// Display label only - not a chain registry. An unrecognized slug still
// renders (falls back to the raw string), so a new chain never breaks this
// screen; it just shows its slug until this map is extended.
const SCOUT_CHAIN_LABELS = { robinhood: 'RH', base: 'Base' };
function _scoutChainLabel(chain) {
  return SCOUT_CHAIN_LABELS[chain] || chain || '—';
}

function _scoutTruncateAddr(addr) {
  if (!addr) return '—';
  if (addr.length <= 12) return addr;
  return addr.slice(0, 6) + '…' + addr.slice(-4);
}

function _scoutPoolLabel(cand) {
  const t0 = cand.symbols && cand.symbols.token0;
  const t1 = cand.symbols && cand.symbols.token1;
  if (t0 && t1) return t0 + '/' + t1;
  return _scoutTruncateAddr(cand.pool_address);
}

// fee_tier is the raw on-chain integer (3000 = 0.3%) - same convention
// maxfi_advisor.entry_score's own docstring documents.
function _scoutFeeTierPct(feeTier) {
  return typeof feeTier === 'number' ? (feeTier / 10000).toFixed(2) + '%' : '—';
}

function _scoutAssetClassLabel(assetClass) {
  return assetClass || 'Unclassified';
}

// Held-join: a candidate's pool is "held" iff some OPEN position in the
// SAME response payload shares (chain, lowercased pool_address). Both
// sides already carry chain+pool_address (see the advisor route) - this
// is the only join scout.js performs, entirely client-side, no new fetch.
function _scoutIsHeld(cand, positions) {
  const addr = String(cand.pool_address || '').toLowerCase();
  return (positions || []).some((p) =>
    p.chain === cand.chain && String(p.pool_address || '').toLowerCase() === addr);
}

// Display-only ratio - never fed back into entry_score or any gate.
function _scoutVolToLiq(volumeH24, liquidityUsd) {
  if (typeof volumeH24 !== 'number' || typeof liquidityUsd !== 'number' || liquidityUsd <= 0) return null;
  return volumeH24 / liquidityUsd;
}

function _scoutVolHeat(volumeMult) {
  if (volumeMult == null) return null;
  if (volumeMult >= SCOUT_VOL_HEAT) return 'Heating';
  if (volumeMult <= SCOUT_VOL_COOL) return 'Cooling';
  return 'Steady';
}

function _scoutPct1(v) {
  return typeof v === 'number' ? v.toFixed(1) + '%' : '—';
}

// Clipboard: the async API is available everywhere this app actually runs
// (https on Railway), but a plain execCommand fallback keeps copy working
// on an http dev origin, where navigator.clipboard is undefined. Never lets
// a clipboard failure throw into React - both paths are wrapped.
function _scoutCopyFallback(text) {
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  } catch (e) {}
}

function _scoutCopyToClipboard(text) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(() => _scoutCopyFallback(text));
      return;
    }
  } catch (e) {}
  _scoutCopyFallback(text);
}

// Metrics-age disclosure: metrics_fetched_at is pool_metrics.fetched_at
// (an ISO string, possibly absent for a catalogue pool with no metrics
// row yet). Parsed defensively - an absent/unparseable value renders
// nothing anywhere, never "Invalid Date".
function _scoutParseDate(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}

function _scoutFormatMetricsAt(iso) {
  const d = _scoutParseDate(iso);
  return d ? d.toLocaleString() : null;
}

function _scoutGateInfo(gate) {
  if (!gate || gate.blocked == null) {
    return { text: 'Unknown', color: 'var(--text3)', bg: 'rgba(201,209,217,0.14)' };
  }
  if (gate.blocked === true) {
    const suffix = gate.sharp_dump === true ? ' — sharp dump' : '';
    return { text: 'Blocked' + suffix, color: 'var(--fail)', bg: 'rgba(255,138,138,0.16)' };
  }
  return { text: 'Clear', color: 'var(--ok)', bg: 'rgba(79,221,142,0.16)' };
}

function _scoutGateTitle(gate) {
  if (!gate) return '';
  const p7 = typeof gate.pct_7d === 'number' ? gate.pct_7d.toFixed(1) + '%' : 'unknown';
  const p30 = typeof gate.pct_30d === 'number' ? gate.pct_30d.toFixed(1) + '%' : 'unknown';
  return '7d: ' + p7 + ' · 30d: ' + p30;
}

/* ── sort value getter (missing values always sink, same convention as
   maxfi.js's mxSortValue-driven table sort) ── */
function _scoutSortValue(cand, key) {
  if (key === 'score') return typeof cand.entry_score === 'number' ? cand.entry_score : null;
  if (key === 'apr') return typeof cand.fee_apr_est_pct === 'number' ? cand.fee_apr_est_pct : null;
  if (key === 'voltvl') return _scoutVolToLiq(cand.volume_h24, cand.liquidity_usd);
  if (key === 'liquidity') return typeof cand.liquidity_usd === 'number' ? cand.liquidity_usd : null;
  return null;
}

const SCOUT_FILTER_DEFAULTS = {
  chain: 'all', assetClass: 'all', search: '', hideHeld: false, showBelowFloor: false,
};

// below_liquidity_floor === true is excluded unless showBelowFloor; === null
// (unknown liquidity) is NEVER hidden - unknown is not below. Every other
// predicate here reads only already-computed payload fields.
function _scoutPassesFilters(cand, filters, positions) {
  if (filters.chain !== 'all' && cand.chain !== filters.chain) return false;
  if (filters.assetClass !== 'all' && _scoutAssetClassLabel(cand.asset_class) !== filters.assetClass) return false;
  const q = filters.search.trim().toLowerCase();
  if (q && !_scoutPoolLabel(cand).toLowerCase().includes(q)) return false;
  if (filters.hideHeld && _scoutIsHeld(cand, positions)) return false;
  if (!filters.showBelowFloor && cand.below_liquidity_floor === true) return false;
  return true;
}

// Facet counts respect every OTHER active filter (search/toggles/the other
// chip row) but never their own dimension - each chip shows how many rows
// would remain visible if that chip were chosen, given everything else
// already selected.
function _scoutChainFacetCounts(candidates, filters, positions) {
  const base = Object.assign({}, filters, { chain: 'all' });
  const counts = {};
  candidates.forEach((c) => {
    if (!_scoutPassesFilters(c, base, positions)) return;
    counts[c.chain] = (counts[c.chain] || 0) + 1;
  });
  return counts;
}

function _scoutAssetClassFacetCounts(candidates, filters, positions) {
  const base = Object.assign({}, filters, { assetClass: 'all' });
  const counts = {};
  candidates.forEach((c) => {
    if (!_scoutPassesFilters(c, base, positions)) return;
    const ac = _scoutAssetClassLabel(c.asset_class);
    counts[ac] = (counts[ac] || 0) + 1;
  });
  return counts;
}

/* ── small presentational pieces ── */

function ScoutChip({ label, count, active, onClick }) {
  return React.createElement('button', {
    onClick,
    style: {
      padding: '4px 12px', borderRadius: 999, fontSize: 12, cursor: 'pointer',
      border: '1px solid ' + (active ? 'var(--accent)' : 'rgba(255,255,255,0.25)'),
      background: active ? 'var(--accent-soft)' : 'transparent',
      color: active ? 'var(--accent)' : 'var(--text3)',
      fontWeight: active ? 600 : 400,
      display: 'inline-flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap',
    },
  },
    label,
    count != null && React.createElement('span', { style: { fontSize: 11, opacity: 0.85 } }, count)
  );
}

function ScoutBadge({ text, color, bg, title }) {
  return React.createElement('span', {
    title: title,
    style: {
      display: 'inline-block', padding: '2px 8px', borderRadius: 6, fontSize: 11,
      fontWeight: 600, color: color, background: bg, border: '1px solid ' + color,
      whiteSpace: 'nowrap',
    },
  }, text);
}

/* ── filter bar ── */

function ScoutFilterBar({ candidates, positions, filters, setFilters }) {
  const chainCounts = React.useMemo(
    () => _scoutChainFacetCounts(candidates, filters, positions), [candidates, filters, positions]);
  const assetClassCounts = React.useMemo(
    () => _scoutAssetClassFacetCounts(candidates, filters, positions), [candidates, filters, positions]);

  const chains = React.useMemo(
    () => Array.from(new Set(candidates.map((c) => c.chain))).sort(), [candidates]);
  const assetClasses = React.useMemo(() => {
    const set = new Set(candidates.map((c) => _scoutAssetClassLabel(c.asset_class)));
    const rest = Array.from(set).filter((x) => x !== 'Unclassified').sort();
    return set.has('Unclassified') ? rest.concat(['Unclassified']) : rest;
  }, [candidates]);

  const allChainCount = Object.values(chainCounts).reduce((a, b) => a + b, 0);
  const allAssetClassCount = Object.values(assetClassCounts).reduce((a, b) => a + b, 0);

  return React.createElement('div', { className: 'tv-card', style: { padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 12 } },
    React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 } },
      React.createElement('span', { className: 'tv-label', style: { marginRight: 2 } }, 'CHAIN:'),
      React.createElement(ScoutChip, {
        label: 'All', count: allChainCount, active: filters.chain === 'all',
        onClick: () => setFilters((p) => Object.assign({}, p, { chain: 'all' })),
      }),
      chains.map((c) => React.createElement(ScoutChip, {
        key: c, label: _scoutChainLabel(c), count: chainCounts[c] || 0, active: filters.chain === c,
        onClick: () => setFilters((p) => Object.assign({}, p, { chain: c })),
      }))
    ),
    React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 } },
      React.createElement('span', { className: 'tv-label', style: { marginRight: 2 } }, 'ASSET CLASS:'),
      React.createElement(ScoutChip, {
        label: 'All', count: allAssetClassCount, active: filters.assetClass === 'all',
        onClick: () => setFilters((p) => Object.assign({}, p, { assetClass: 'all' })),
      }),
      assetClasses.map((ac) => React.createElement(ScoutChip, {
        key: ac, label: ac, count: assetClassCounts[ac] || 0, active: filters.assetClass === ac,
        onClick: () => setFilters((p) => Object.assign({}, p, { assetClass: ac })),
      }))
    ),
    React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 16 } },
      React.createElement('input', {
        type: 'text', className: 'tv-input', style: { width: 220 },
        placeholder: 'Search pair…', value: filters.search,
        onChange: (e) => setFilters((p) => Object.assign({}, p, { search: e.target.value })),
      }),
      React.createElement('label', { style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--text2)', cursor: 'pointer' } },
        React.createElement('input', {
          type: 'checkbox', checked: filters.hideHeld,
          onChange: (e) => setFilters((p) => Object.assign({}, p, { hideHeld: e.target.checked })),
        }),
        'Hide held'
      ),
      React.createElement('label', { style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--text2)', cursor: 'pointer' } },
        React.createElement('input', {
          type: 'checkbox', checked: filters.showBelowFloor,
          onChange: (e) => setFilters((p) => Object.assign({}, p, { showBelowFloor: e.target.checked })),
        }),
        'Show below-floor'
      )
    )
  );
}

/* ── candidates table ── */

function ScoutTable({ rows, positions, sort, cycleSort }) {
  const [copiedKey, setCopiedKey] = React.useState(null);
  const copyTimeoutRef = React.useRef(null);

  // Guards the "Copied" chip's setTimeout against firing after this table
  // unmounts (e.g. the tab is switched away mid-confirmation) - cleared on
  // every re-click too, so rapid clicks across rows don't leave a stale
  // chip lit on the wrong row.
  React.useEffect(() => {
    return () => { if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current); };
  }, []);

  function handleCopyPool(e, rowKey, poolAddress) {
    e.stopPropagation();
    _scoutCopyToClipboard(poolAddress);
    if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
    setCopiedKey(rowKey);
    copyTimeoutRef.current = setTimeout(() => {
      setCopiedKey(null);
      copyTimeoutRef.current = null;
    }, 1500);
  }

  const sortableTh = (txt, key) => React.createElement('th', {
    onClick: () => cycleSort(key),
    style: {
      cursor: 'pointer', userSelect: 'none',
      color: sort.key === key ? 'var(--text)' : 'var(--text4)',
    },
  }, txt, sort.key === key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : '');

  if (rows.length === 0) {
    return React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)', padding: '20px 0' } },
      'No candidates match the current filters.');
  }

  return React.createElement('div', { style: { overflowX: 'auto' } },
    React.createElement('table', { className: 'tv-table', style: { width: '100%' } },
      React.createElement('thead', null,
        React.createElement('tr', null,
          React.createElement('th', null, 'POOL'),
          React.createElement('th', null, 'CHAIN'),
          sortableTh('SCORE', 'score'),
          sortableTh('FEE APR EST', 'apr'),
          sortableTh('VOL/TVL', 'voltvl'),
          React.createElement('th', null, 'VOLUME'),
          React.createElement('th', null, 'GATE'),
          sortableTh('LIQUIDITY', 'liquidity')
        )
      ),
      React.createElement('tbody', null,
        rows.map((c) => {
          const rowKey = c.chain + ':' + c.pool_address;
          const held = _scoutIsHeld(c, positions);
          const thin = c.below_liquidity_floor === true;
          const ratio = _scoutVolToLiq(c.volume_h24, c.liquidity_usd);
          const heat = _scoutVolHeat(c.volume_mult);
          const gateInfo = _scoutGateInfo(c.downtrend_gate);
          const rowStyle = thin ? { opacity: 0.65 } : null;
          const metricsAgeTitle = _scoutFormatMetricsAt(c.metrics_fetched_at);
          return React.createElement('tr', { key: rowKey, style: rowStyle },
            React.createElement('td', null,
              React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
                React.createElement('div', {
                  onClick: (e) => handleCopyPool(e, rowKey, c.pool_address),
                  title: 'Click to copy pool address',
                  style: { fontSize: 14, color: 'var(--text)', fontWeight: 600, cursor: 'pointer',
                    display: 'flex', alignItems: 'center', gap: 8 },
                },
                  _scoutPoolLabel(c) + '  ' + _scoutFeeTierPct(c.fee_tier),
                  copiedKey === rowKey && React.createElement(ScoutBadge, { text: 'Copied', color: 'var(--ok)', bg: 'rgba(79,221,142,0.16)' })
                ),
                React.createElement('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap' } },
                  React.createElement(ScoutBadge, { text: _scoutAssetClassLabel(c.asset_class), color: 'var(--text3)', bg: 'rgba(201,209,217,0.14)' }),
                  held && React.createElement(ScoutBadge, { text: 'Held', color: 'var(--accent)', bg: 'var(--accent-soft)' }),
                  thin && React.createElement(ScoutBadge, { text: 'Thin', color: 'var(--text3)', bg: 'rgba(201,209,217,0.14)' })
                )
              )
            ),
            React.createElement('td', null, _scoutChainLabel(c.chain)),
            React.createElement('td', null, typeof c.entry_score === 'number' ? c.entry_score.toFixed(1) : '—'),
            React.createElement('td', { title: 'TVL proxy: ' + (c.tvl_source || 'unknown') }, _scoutPct1(c.fee_apr_est_pct)),
            React.createElement('td', null, ratio != null ? ratio.toFixed(1) + 'x' : '—'),
            React.createElement('td', null,
              heat == null ? '—' : React.createElement('span', null,
                heat, ' (', c.volume_mult.toFixed(1), 'x)')
            ),
            React.createElement('td', { title: _scoutGateTitle(c.downtrend_gate) },
              React.createElement(ScoutBadge, { text: gateInfo.text, color: gateInfo.color, bg: gateInfo.bg })
            ),
            React.createElement('td', { title: metricsAgeTitle ? 'as of ' + metricsAgeTitle : undefined },
              typeof c.liquidity_usd === 'number' ? fmt(c.liquidity_usd, 0) : '—')
          );
        })
      )
    )
  );
}

/* ── main screen ── */

function ScoutScreen() {
  const [data, setData] = React.useState({ positions: [], entry_candidates: [] });
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState(null);
  const [fetchedAt, setFetchedAt] = React.useState(null);
  const [filters, setFilters] = React.useState(Object.assign({}, SCOUT_FILTER_DEFAULTS));
  const [sort, setSort] = React.useState({ key: 'score', dir: 'desc' });

  async function load() {
    setLoadError(null);
    try {
      const d = await api('/api/maxfi/advisor');
      if (d === undefined || d === null) {
        setLoadError('session expired');
        setLoading(false);
        return;
      }
      setData({ positions: d.positions || [], entry_candidates: d.entry_candidates || [] });
      // Client clock at fetch completion - no auto-refresh, the underlying
      // data only moves when token-daily/metrics refresh jobs run.
      setFetchedAt(new Date());
      setLoading(false);
    } catch (e) {
      setLoadError(_scoutExtractErr(e));
      setLoading(false);
    }
  }

  React.useEffect(() => { load(); }, []);

  function cycleSort(key) {
    setSort((prev) => prev.key !== key ? { key, dir: 'asc' }
      : prev.dir === 'asc' ? { key, dir: 'desc' } : { key: null, dir: null });
  }

  const candidates = data.entry_candidates;
  const positions = data.positions;

  // "Would this row be visible if every OTHER toggle/filter/search stayed
  // as-is but below-floor rows were shown?" - the count of rows that
  // satisfy everything except the floor-hide itself, minus what's already
  // shown when showBelowFloor is on (0, since none are hidden then).
  const hiddenBelowFloorCount = React.useMemo(() => {
    if (filters.showBelowFloor) return 0;
    const shown = Object.assign({}, filters, { showBelowFloor: true });
    return candidates.filter((c) =>
      c.below_liquidity_floor === true && _scoutPassesFilters(c, shown, positions)).length;
  }, [candidates, filters, positions]);

  const filtered = React.useMemo(
    () => candidates.filter((c) => _scoutPassesFilters(c, filters, positions)),
    [candidates, filters, positions]);

  const sorted = React.useMemo(() => {
    const key = sort.key || 'score';
    const dir = sort.key ? sort.dir : 'desc';
    const dirMul = dir === 'desc' ? -1 : 1;
    // Missing values always sink to the bottom regardless of direction -
    // same convention as maxfi.js's own sortable-table columns.
    return filtered.slice().sort((a, b) => {
      const va = _scoutSortValue(a, key), vb = _scoutSortValue(b, key);
      const aMissing = va === null || va === undefined;
      const bMissing = vb === null || vb === undefined;
      if (aMissing && bMissing) return 0;
      if (aMissing) return 1;
      if (bMissing) return -1;
      return dirMul * (va - vb);
    });
  }, [filtered, sort]);

  // Metrics-age disclosure (header level): oldest-wins across the
  // currently VISIBLE (post-filter) candidates - same honesty convention
  // maxfi.js's valFetchedAt uses for its own aggregate freshness line.
  // Omitted entirely when nothing visible carries a parseable timestamp.
  const oldestMetricsAt = React.useMemo(() => {
    let oldest = null;
    filtered.forEach((c) => {
      const d = _scoutParseDate(c.metrics_fetched_at);
      if (d && (oldest === null || d.getTime() < oldest.getTime())) oldest = d;
    });
    return oldest;
  }, [filtered]);

  if (loading) {
    return React.createElement('div', {
      style: { display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 320, color: 'var(--text3)', fontSize: 14 },
    }, 'Loading Pool Scout…');
  }

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
    React.createElement('div', null,
      React.createElement('div', { className: 'tv-page-title', style: { marginBottom: 4 } }, 'Pool Scout'),
      React.createElement('div', { style: { fontSize: 12, color: 'var(--text3)' } },
        fetchedAt
          ? 'Loaded ' + fetchedAt.toLocaleString()
            + (oldestMetricsAt ? ' · metrics as of ' + oldestMetricsAt.toLocaleString() : '')
          : ''),
      React.createElement('div', { style: { fontSize: 12, color: 'var(--text3)', marginTop: 2 } },
        'New entries are $25–50 probes. Full size only scales up a measured probe.')
    ),
    loadError && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13 } }, loadError),
    candidates.length === 0
      ? React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)' } }, 'No entry candidates yet.')
      : React.createElement(React.Fragment, null,
          React.createElement(ScoutFilterBar, { candidates, positions, filters, setFilters }),
          React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
            hiddenBelowFloorCount > 0 && React.createElement('div', {
              style: { fontSize: 12, color: 'var(--text3)', marginBottom: 12 },
            }, hiddenBelowFloorCount + ' hidden under $10K liquidity'),
            React.createElement(ScoutTable, { rows: sorted, positions, sort, cycleSort })
          )
        )
  );
}

window.ScoutScreen = ScoutScreen;
