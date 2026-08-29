/* ===== MAXFI LP POSITIONS (UI slice 1) =====
   Read-only. Reads GET /api/maxfi/positions/<chain>/<wallet> (fast DB read,
   includes closed rows - filtered to status==='open' client-side here) and
   GET /api/maxfi/valuation/<chain>/<wallet> (RPC-bound, can be slow/fail).
   No write endpoint is called from this file - /api/maxfi/scan is a POST
   write path and is never referenced here.

   Loading is deliberately two-phase: positions first (fast), valuation
   second (slow), so the table is usable before pricing completes. Each
   chain's positions fetch and valuation fetch carries its own independent
   loading/error state, so a Base failure never blanks Robinhood's rows. */

const MX_C = {
  primary: '#e6edf3', secondary: '#c9d1d9',
  border: 'rgba(255,255,255,0.25)', sep: 'rgba(255,255,255,0.32)',
  bg: '#12161c', panel: '#0d1117', head: '#1b2129', zebra: '#161b22',
  accent: '#7ee2a8', warn: '#f0a0a0',
};

// Local PT timestamp formatter - deliberately NOT the trading.js fmtDiagTime
// (that one isn't exported/global). Same behavior, own copy.
function fmtMxTime(ts) {
  if (ts === null || ts === undefined || ts === ''
      || (typeof ts === 'number' && isNaN(ts))) return '—';
  try {
    var d = (typeof ts === 'string') ? new Date(ts) : new Date(ts * 1000);
    if (isNaN(d.getTime())) return '—';
    var p = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit',
      day: '2-digit', hour: 'numeric', minute: '2-digit', hour12: true,
    }).formatToParts(d).reduce(function (a, x) {
      a[x.type] = x.value; return a;
    }, {});
    return p.year + '-' + p.month + '-' + p.day + ' '
      + p.hour + ':' + p.minute + ' ' + p.dayPeriod + ' PT';
  } catch (e) { return String(ts); }
}

const MX_WALLET = '0xaB7A515c6e2Eea5140eD8A5b09A7D782F3B26743';
const MX_CHAINS = [
  { slug: 'robinhood', label: 'Robinhood' },
  { slug: 'base', label: 'Base' },
];

// Same "extract a structured error from api()'s thrown text" pattern used
// throughout trading.js.
function mxExtractErr(e) {
  let msg = (e && e.message) ? e.message : String(e);
  try { const j = JSON.parse(msg); if (j && j.error) msg = j.error; } catch (e2) {}
  return msg;
}

function mxTruncateAddr(addr) {
  if (!addr) return '—';
  if (addr.length <= 12) return addr;
  return addr.slice(0, 6) + '…' + addr.slice(-4);
}

/* Error boundary, modeled on trading.js's CascadeErrorBoundary - a payload
   surprise renders an inline error box instead of crashing the tab. */
class MaxFiErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { err: null }; }
  static getDerivedStateFromError(err) { return { err: err }; }
  componentDidCatch(err, info) {
    try { console.error('[maxfi] view error:', err, info); } catch (e) {}
  }
  render() {
    if (this.state.err) {
      const msg = (this.state.err && this.state.err.message) ? String(this.state.err.message) : String(this.state.err);
      return React.createElement('div', {
        style: { background: '#2b0d0d', border: '1px solid #6b1a1a', borderRadius: 6,
          padding: '12px 16px', marginBottom: 12, color: MX_C.primary, fontSize: 13 } },
        React.createElement('div', { style: { color: '#f87171', fontWeight: 700, marginBottom: 4 } },
          'MaxFi view failed'),
        React.createElement('div', { style: { color: MX_C.secondary } },
          'This panel hit an error and was contained — the rest of the page keeps working. ' + msg));
    }
    return this.props.children;
  }
}

function MaxFiScreen({ hideValues }) {
  const [open, setOpen] = React.useState(true);

  const emptyChainState = () => {
    const o = {};
    MX_CHAINS.forEach((c) => { o[c.slug] = { data: null, loading: false, error: null }; });
    return o;
  };
  const [positions, setPositions] = React.useState(emptyChainState);
  const [valuation, setValuation] = React.useState(emptyChainState);

  const patchPositions = (slug, patch) => setPositions((prev) =>
    Object.assign({}, prev, { [slug]: Object.assign({}, prev[slug], patch) }));
  const patchValuation = (slug, patch) => setValuation((prev) =>
    Object.assign({}, prev, { [slug]: Object.assign({}, prev[slug], patch) }));

  async function loadPositionsFor(chain) {
    patchPositions(chain.slug, { loading: true, error: null });
    try {
      const data = await api(`/api/maxfi/positions/${chain.slug}/${MX_WALLET}`);
      patchPositions(chain.slug, { data: Array.isArray(data) ? data : [], loading: false });
    } catch (e) {
      patchPositions(chain.slug, { loading: false, error: mxExtractErr(e) });
    }
  }

  async function loadValuationFor(chain) {
    patchValuation(chain.slug, { loading: true, error: null });
    try {
      const data = await api(`/api/maxfi/valuation/${chain.slug}/${MX_WALLET}`);
      patchValuation(chain.slug, { data: data, loading: false });
    } catch (e) {
      patchValuation(chain.slug, { loading: false, error: mxExtractErr(e) });
    }
  }

  // Phase 1 (positions, both chains in parallel) must fully settle before
  // Phase 2 (valuation, both chains in parallel) starts - deliberate, not
  // collapsed into one Promise.allSettled.
  async function runBothPhases() {
    await Promise.allSettled(MX_CHAINS.map(loadPositionsFor));
    Promise.allSettled(MX_CHAINS.map(loadValuationFor));
  }

  React.useEffect(() => { runBothPhases(); }, []);

  function valuationEntryFor(chainSlug, tokenId) {
    const v = valuation[chainSlug];
    if (!v || !v.data || !Array.isArray(v.data.positions)) return null;
    return v.data.positions.find((p) => String(p.token_id) === String(tokenId)) || null;
  }

  // Row model: built from the positions payload only (open rows, per chain).
  // A valuation entry with no matching position row is never used to
  // synthesize a row - only positions rows produce rows.
  const rows = [];
  MX_CHAINS.forEach((chain) => {
    const posState = positions[chain.slug];
    const list = (posState.data || []).filter((p) => p.status === 'open');
    list.forEach((p) => {
      rows.push({ chain, position: p, valuation: valuationEntryFor(chain.slug, p.token_id) });
    });
  });

  function mostRecentScan() {
    let best = null;
    MX_CHAINS.forEach((chain) => {
      const list = positions[chain.slug].data;
      if (!list) return;
      list.forEach((p) => {
        if (!p.last_scan_at) return;
        if (!best || new Date(p.last_scan_at) > new Date(best)) best = p.last_scan_at;
      });
    });
    return best;
  }

  function valueCell(row) {
    const vState = valuation[row.chain.slug];
    if (vState.error) return { text: 'unavailable', color: MX_C.warn };
    if (!vState.data) return { text: '…', color: MX_C.secondary };
    const cv = row.valuation ? row.valuation.current_value_usd : null;
    if (cv === null || cv === undefined) return { text: 'unavailable', color: MX_C.secondary };
    return { text: hideValues ? '••••' : fmt(cv), color: MX_C.primary };
  }

  function pnlCell(row) {
    const perf = row.valuation ? row.valuation.performance : null;
    const pnl = perf ? perf.pnl_usd : null;
    if (pnl === null || pnl === undefined) return { text: '—', color: MX_C.secondary };
    const sign = pnl >= 0 ? '+' : '';
    const text = hideValues ? '••••' : (sign + fmt(pnl));
    return { text, color: pnl >= 0 ? MX_C.accent : MX_C.warn };
  }

  // Section total - LP-only, never folded into portfolio NAV. Partial
  // whenever any row's value is still loading, unavailable, or a chain
  // errored - an incomplete number is never presented as complete.
  let total = 0;
  let partial = false;
  rows.forEach((row) => {
    const vState = valuation[row.chain.slug];
    if (vState.loading || !vState.data || vState.error) { partial = true; return; }
    const cv = row.valuation ? row.valuation.current_value_usd : null;
    if (cv === null || cv === undefined) { partial = true; return; }
    total += cv;
  });

  const anyBusy = MX_CHAINS.some((c) => positions[c.slug].loading || valuation[c.slug].loading);

  const th = (txt) => React.createElement('th', {
    style: { textAlign: 'left', padding: '5px 9px', fontSize: 12,
      color: MX_C.secondary, fontWeight: 700, borderBottom: '1px solid ' + MX_C.border,
      whiteSpace: 'nowrap' } }, txt);
  const td = (children, extra) => React.createElement('td', {
    style: Object.assign({ padding: '6px 9px', fontSize: 12, color: MX_C.primary,
      borderBottom: '1px solid ' + MX_C.sep, verticalAlign: 'top' }, extra || {}) }, children);

  const header = React.createElement('div', {
    onClick: () => setOpen((o) => !o),
    style: { display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer',
      color: MX_C.primary, fontSize: 13, fontWeight: 700, letterSpacing: '0.06em' } },
    React.createElement('span', { style: { color: MX_C.secondary, fontSize: 12 } }, open ? '▾' : '▸'),
    'MAXFI LP POSITIONS',
    React.createElement('span', {
      style: { color: MX_C.secondary, fontSize: 12, fontWeight: 400, letterSpacing: 0 } },
      'as of ' + fmtMxTime(mostRecentScan())),
    React.createElement('button', {
      onClick: (ev) => { ev.stopPropagation(); runBothPhases(); },
      disabled: anyBusy,
      style: { marginLeft: 'auto', background: '#1a1a3a', border: '1px solid ' + MX_C.border,
        color: MX_C.primary, padding: '4px 12px', borderRadius: 5, fontSize: 12, fontWeight: 600,
        cursor: anyBusy ? 'default' : 'pointer', opacity: anyBusy ? 0.6 : 1 } },
      anyBusy ? 'Loading…' : 'Refresh'));

  const statusLines = [];
  MX_CHAINS.forEach((chain) => {
    const posState = positions[chain.slug];
    const valState = valuation[chain.slug];
    if (posState.loading) statusLines.push(
      React.createElement('div', { key: chain.slug + '-pl', style: { color: MX_C.secondary, fontSize: 12, marginBottom: 4 } },
        `Loading ${chain.label} positions…`));
    if (posState.error) statusLines.push(
      React.createElement('div', { key: chain.slug + '-pe', style: { color: MX_C.warn, fontSize: 12, marginBottom: 4, fontWeight: 600 } },
        `${chain.label} positions (/api/maxfi/positions/${chain.slug}/<wallet>) failed: ${posState.error}`));
    if (valState.error) statusLines.push(
      React.createElement('div', { key: chain.slug + '-ve', style: { color: MX_C.warn, fontSize: 12, marginBottom: 4, fontWeight: 600 } },
        `${chain.label} valuation (/api/maxfi/valuation/${chain.slug}/<wallet>) failed: ${valState.error}`));
  });

  const tableRows = rows.map((row, i) => {
    const p = row.position;
    const vcell = valueCell(row);
    const pcell = pnlCell(row);
    const hasBasis = p.initial_value_usd !== null && p.initial_value_usd !== undefined;
    return React.createElement('tr', {
      key: row.chain.slug + '-' + p.token_id + '-' + p.id,
      style: { background: i % 2 ? MX_C.zebra : 'transparent' } },
      td(row.chain.label),
      td(React.createElement('span', { title: p.pool_address || '' }, mxTruncateAddr(p.pool_address))),
      td(String(p.token_id)),
      td(hasBasis
        ? (hideValues ? '••••' : fmt(p.initial_value_usd))
        : React.createElement('span', {
            style: { display: 'inline-block', color: MX_C.warn, border: '1px solid ' + MX_C.warn,
              background: 'rgba(240,120,120,0.14)', borderRadius: 4, padding: '1px 6px',
              fontSize: 11, fontWeight: 700 } }, 'NO BASIS')),
      td(vcell.text, { color: vcell.color }),
      td(pcell.text, { color: pcell.color }));
  });

  const totalLabel = 'LP PORTFOLIO VALUE' + (partial ? ' (partial)' : '');
  const totalText = hideValues ? '••••' : fmt(total);

  const body = React.createElement('div', {
    style: { background: MX_C.panel, border: '1px solid ' + MX_C.border, borderRadius: 6,
      padding: '12px 16px', marginBottom: 12 } },
    header,
    open ? React.createElement('div', { style: { marginTop: 10 } },
      statusLines,
      rows.length === 0 ? React.createElement('div', {
        style: { color: MX_C.secondary, fontSize: 13 } },
        anyBusy ? 'Loading positions…' : 'No open MaxFi positions found.') : React.createElement('div', {
        style: { border: '1px solid ' + MX_C.border, borderRadius: 6, overflow: 'hidden' } },
        React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse', background: MX_C.bg } },
          React.createElement('thead', { style: { background: MX_C.head } },
            React.createElement('tr', null,
              th('Chain'), th('Pool'), th('Token ID'), th('Basis'), th('Value'), th('P/L'))),
          React.createElement('tbody', null, tableRows))),
      React.createElement('div', {
        style: { marginTop: 10, display: 'flex', alignItems: 'center', gap: 8,
          fontSize: 13, fontWeight: 700, color: MX_C.primary } },
        React.createElement('span', { style: { color: MX_C.secondary, fontWeight: 700, letterSpacing: '0.04em' } },
          totalLabel + ':'),
        React.createElement('span', null, totalText))
    ) : null);

  return React.createElement(MaxFiErrorBoundary, null, body);
}

window.MaxFiScreen = MaxFiScreen;
