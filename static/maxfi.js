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

// Shared small-pill style for NO BASIS / STALE / UNTRACKED - same shape as
// the original NO BASIS badge, parameterized on color/background so the two
// new informational badges (secondary, not warn-red - they describe normal
// DB/chain divergence, not an error) share one definition.
function mxBadge(text, color, bg, marginRight) {
  return React.createElement('span', {
    style: { display: 'inline-block', color: color, border: '1px solid ' + color,
      background: bg, borderRadius: 4, padding: '1px 6px',
      fontSize: 11, fontWeight: 700, marginRight: marginRight || 0 } }, text);
}
const mxNoBasisBadge = () => mxBadge('NO BASIS', MX_C.warn, 'rgba(240,120,120,0.14)');
const mxStaleBadge = () => mxBadge('STALE', MX_C.secondary, 'rgba(201,209,217,0.14)', 6);
const mxUntrackedBadge = () => mxBadge('UNTRACKED', MX_C.secondary, 'rgba(201,209,217,0.14)', 6);

// Position identity per this codebase's core rule: the vault burns and mints
// NFTs on rebalance, so token_id is NOT durable - array_index + pool_address
// is. Lowercased because checksum casing can differ between the DB's stored
// value and a live chain read.
function mxIdentityKey(arrayIndex, poolAddr) {
  return arrayIndex + '|' + String(poolAddr || '').toLowerCase();
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

  // Row model: a UNION of the DB's open positions and the chain's live
  // valuation snapshot, joined on array_index + pool_address (never
  // token_id - token_id is minted fresh on every rebalance, per this
  // project's core identity rule). Three resulting states:
  //   matched   - in both. Basis from the DB, value/P&L from valuation.
  //   stale     - open in the DB, not on-chain any more (user exited,
  //               scan hasn't caught up). Value/P&L are a confirmed
  //               em-dash - not "unavailable", which means "we don't
  //               know," not "we know it's gone."
  //   untracked - on-chain, no DB row (entered since the last scan). No
  //               basis exists to show; value/P&L come from valuation.
  // A row's state can only be determined once THAT CHAIN's valuation has
  // loaded successfully - before that (still loading) or on a valuation
  // failure, state stays null: absence of data is not evidence the
  // position is gone, so nothing is badged stale/untracked either way.
  // DB rows with status 'closed' are excluded entirely, exactly as before -
  // closed is a resolved state, not a disagreement between the two sources.
  const rows = [];
  MX_CHAINS.forEach((chain) => {
    const posState = positions[chain.slug];
    const valState = valuation[chain.slug];
    const dbList = (posState.data || []).filter((p) => p.status === 'open');
    // Valuation's own field is "pool", not "pool_address" - different shape
    // from the positions payload, deliberately per the two endpoints' own
    // documented contracts.
    const valList = (valState.data && Array.isArray(valState.data.positions)) ? valState.data.positions : [];
    const valuationLoaded = !!valState.data && !valState.error;

    const valByKey = {};
    valList.forEach((v) => { valByKey[mxIdentityKey(v.array_index, v.pool)] = v; });

    const matchedKeys = {};
    dbList.forEach((p) => {
      const key = mxIdentityKey(p.array_index, p.pool_address);
      const match = valByKey[key] || null;
      if (match) matchedKeys[key] = true;
      const state = !valuationLoaded ? null : (match ? 'matched' : 'stale');
      rows.push({
        chain, position: p, valuation: match, state,
        arrayIndex: p.array_index, poolAddress: p.pool_address, tokenId: p.token_id,
      });
    });

    // UNTRACKED - a valuation entry with no matching open DB row. Only
    // synthesized once valuation has actually loaded successfully; an
    // entry we have no data for cannot become a row at all.
    if (valuationLoaded) {
      valList.forEach((v) => {
        const key = mxIdentityKey(v.array_index, v.pool);
        if (matchedKeys[key]) return;
        rows.push({
          chain, position: null, valuation: v, state: 'untracked',
          arrayIndex: v.array_index, poolAddress: v.pool, tokenId: v.token_id,
        });
      });
    }
  });

  // Sort so problems surface: within each chain, untracked first, then
  // stale, then matched (and unresolved/null - phase-1-only - last). A
  // stable sort (guaranteed by the spec for Array.prototype.sort) keeps
  // each group's original array_index order exactly as the two endpoints
  // themselves returned it.
  const mxChainOrder = {};
  MX_CHAINS.forEach((c, i) => { mxChainOrder[c.slug] = i; });
  const mxStatePriority = { untracked: 0, stale: 1, matched: 2 };
  rows.sort((a, b) => {
    const chainDiff = mxChainOrder[a.chain.slug] - mxChainOrder[b.chain.slug];
    if (chainDiff !== 0) return chainDiff;
    const pa = a.state in mxStatePriority ? mxStatePriority[a.state] : 3;
    const pb = b.state in mxStatePriority ? mxStatePriority[b.state] : 3;
    return pa - pb;
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
    // Stale is a CONFIRMED fact once valuation has loaded (the position
    // genuinely isn't there any more) - a definite em-dash, never the same
    // "unavailable" used when we simply don't have data.
    if (row.state === 'stale') return { text: '—', color: MX_C.secondary };
    const vState = valuation[row.chain.slug];
    if (vState.error) return { text: 'unavailable', color: MX_C.warn };
    if (!vState.data) return { text: '…', color: MX_C.secondary };
    const cv = row.valuation ? row.valuation.current_value_usd : null;
    if (cv === null || cv === undefined) return { text: 'unavailable', color: MX_C.secondary };
    return { text: hideValues ? '••••' : fmt(cv), color: MX_C.primary };
  }

  function pnlCell(row) {
    if (row.state === 'stale') return { text: '—', color: MX_C.secondary };
    const perf = row.valuation ? row.valuation.performance : null;
    const pnl = perf ? perf.pnl_usd : null;
    if (pnl === null || pnl === undefined) return { text: '—', color: MX_C.secondary };
    const sign = pnl >= 0 ? '+' : '';
    const text = hideValues ? '••••' : (sign + fmt(pnl));
    return { text, color: pnl >= 0 ? MX_C.accent : MX_C.warn };
  }

  // Section total - LP-only, never folded into portfolio NAV. Answers "what
  // is my LP capital worth right now" - a chain question - so it sums
  // matched + untracked (everything the chain currently reports as held)
  // and excludes stale (confirmed no longer held, contributes nothing).
  // Partial whenever any row's value is still loading, unavailable, or a
  // chain errored - an incomplete number is never presented as complete.
  let total = 0;
  let partial = false;
  rows.forEach((row) => {
    const vState = valuation[row.chain.slug];
    if (vState.loading || !vState.data || vState.error) { partial = true; return; }
    if (row.state === 'stale') return;
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
    const p = row.position;   // null for an untracked row - no DB row exists
    const vcell = valueCell(row);
    const pcell = pnlCell(row);
    const hasBasis = !!p && p.initial_value_usd !== null && p.initial_value_usd !== undefined;
    const stateBadge = row.state === 'stale' ? mxStaleBadge()
      : row.state === 'untracked' ? mxUntrackedBadge() : null;
    return React.createElement('tr', {
      key: row.chain.slug + '-' + row.arrayIndex + '-' + row.poolAddress,
      style: { background: i % 2 ? MX_C.zebra : 'transparent' } },
      td(row.chain.label),
      td(React.createElement('span', null,
        stateBadge,
        React.createElement('span', { title: row.poolAddress || '' }, mxTruncateAddr(row.poolAddress)))),
      td(String(row.tokenId)),
      td(hasBasis
        ? (hideValues ? '••••' : fmt(p.initial_value_usd))
        : mxNoBasisBadge()),
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
