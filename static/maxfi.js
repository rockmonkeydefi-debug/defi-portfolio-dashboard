/* ===== MAXFI LP POSITIONS (UI slice 2) =====
   Reads GET /api/maxfi/positions/<chain>/<wallet> (fast DB read, includes
   closed rows - filtered to status==='open' client-side here) and GET
   /api/maxfi/valuation/<chain>/<wallet> (RPC-bound, can be slow/fail).
   Writes (Block C2): POST .../initial-value (per-row basis entry, via
   MaxFiBasisCell) and POST .../close (stale-row close, via
   MaxFiCloseButton) - both act on a single DB row id and only ever trigger
   a positions refetch afterward, never a valuation refetch. /api/maxfi/scan
   is a separate POST write path and is still never referenced here.

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

// Uniswap V3 fee tiers are stored as the raw undivided uint24 (500, 3000,
// 10000, ...) - see maxfi_client.decode_npm_position(). Dividing by 10000
// and letting Number.toString() drop trailing zeros gives "0.05%"/"0.3%"/
// "1%" without any manual precision tables.
function mxFeeTierLabel(feeTier) {
  if (typeof feeTier !== 'number' || !isFinite(feeTier)) return null;
  const pct = Math.round((feeTier / 10000) * 10000) / 10000; // guards float noise
  return pct + '%';
}

// ROI% derived from the SAME pnl_usd the dollar P/L figure already renders
// (pnl_usd / basis * 100) - never a second, independently-computed P/L.
// Returns null (never a placeholder - no "N/A", no "—") whenever the ratio
// isn't meaningful: no basis row, a non-finite basis, a zero or negative
// basis (the backend has no range check on initial_value_usd, so a bad
// historical value is reachable here and would otherwise divide by zero or
// flip the sign), or a non-finite result. Magnitude is capped at ±9999.9%
// (a flat numeric cap, not a floating significant-digit scheme) so a
// near-zero basis can't blow out the column width, while every produced
// value still keeps exactly the one decimal place the dollar figure's
// neighbor column expects.
function mxRoiLabel(pnl, basis) {
  if (typeof basis !== 'number' || !isFinite(basis) || basis <= 0) return null;
  const ratio = (pnl / basis) * 100;
  if (!isFinite(ratio)) return null;
  const capped = Math.max(-9999.9, Math.min(9999.9, ratio));
  const sign = capped >= 0 ? '+' : '';
  return sign + capped.toFixed(1) + '%';
}

// row.position is null for an UNTRACKED row (on-chain, no DB row yet) - the
// one shape this helper must never throw on. A half-resolved pair (only one
// symbol back from the census) is deliberately treated the same as fully
// unresolved: "WETH/0x1234…" is not a usable label, so the caller falls back
// to the address instead of showing a half-guess.
function mxPairLabel(position) {
  if (!position) return null;
  const sym0 = position.token0_symbol;
  const sym1 = position.token1_symbol;
  if (!sym0 || !sym1) return null;
  const feeLabel = mxFeeTierLabel(position.fee_tier);
  return sym0 + '/' + sym1 + (feeLabel ? ' ' + feeLabel : '');
}

// Short calendar-date for a narrow column, e.g. "Aug 18". Reuses fmtMxTime's
// exact parse guard (new Date(ts), isNaN(d.getTime()), try/catch) rather than
// inventing a second ISO-parsing path, but does NOT reuse its output format -
// fmtMxTime renders a full PT date+time string, which doesn't fit here. Pinned
// to the same America/Los_Angeles zone as fmtMxTime (not the viewer's local
// zone) so the two dates shown in this panel never silently disagree.
function mxOpenDate(position) {
  const ts = position && position.first_seen_at;
  if (!ts) return '—';
  try {
    var d = new Date(ts);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'America/Los_Angeles' });
  } catch (e) { return '—'; }
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

// first_seen_at_source === 'ambiguity_auto_split_inherited' means the date
// shown was copied from a departing position during an auto-split, not read
// from this row's own chain history - it can be materially wrong (see Block
// C2 discovery: rows 31/32 display Aug 21 but actually opened Aug 29). Wraps
// mxBadge() in a title-bearing span since mxBadge itself takes no title.
function mxInheritedDateBadge() {
  return React.createElement('span', {
    style: { marginLeft: 6 },
    title: 'This open date was inherited from a departing position during an '
      + 'auto-split and is not this position’s true entry date.',
  }, mxBadge('inherited', MX_C.warn, 'rgba(240,120,120,0.14)'));
}

// initialValueSource === 'ambiguity_auto_split' means this basis was never a
// recorded deposit - it was calculated when an ambiguous position change was
// auto-resolved (see maxfi_orchestration.resolve_ambiguous_auto_splits) and
// is an estimate, not a fact. Same shape as mxInheritedDateBadge above:
// mxBadge() wrapped in a title-bearing span, since mxBadge itself takes no
// title. No open row currently has this source (row 31 was hand-corrected to
// manual_override) - this is defensive for a future auto-split, not visible
// in production today.
function mxAutoSplitBasisBadge() {
  return React.createElement('span', {
    style: { marginLeft: 6 },
    title: 'This basis was calculated automatically when an ambiguous position '
      + 'change was resolved. It is an estimate, not a recorded deposit, and '
      + 'can be corrected by editing the value.',
  }, mxBadge('auto-split', MX_C.warn, 'rgba(240,120,120,0.14)'));
}

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

// Small button style shared by MaxFiBasisCell/MaxFiCloseButton - same shape
// as the header's existing Refresh button, just smaller, so new inline
// controls read as part of this panel rather than a foreign widget.
function mxSmallBtnStyle(disabled) {
  return {
    background: '#1a1a3a', border: '1px solid ' + MX_C.border, color: MX_C.primary,
    padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
    cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.6 : 1,
  };
}

// Strips a leading '$' and thousands commas, then parses. Returns null (never
// throws) for NaN, non-finite, or <= 0 - the backend has no range check on
// initial_value_usd, so this inline guard is the only one that exists.
function mxParseBasisInput(raw) {
  const cleaned = String(raw).trim().replace(/^\$/, '').replace(/,/g, '');
  const n = Number(cleaned);
  if (!isFinite(n) || n <= 0) return null;
  return n;
}

// Maps /initial-value's four known error codes to plain language; anything
// unrecognised (including a non-JSON thrown message) falls back to the raw
// text mxExtractErr already pulled out.
function mxBasisErrorMessage(e) {
  const raw = mxExtractErr(e);
  const known = {
    InvalidPositionId: 'Invalid position id.',
    InvalidInitialValue: 'Enter a valid number for the basis.',
    InvalidOnlyIfEmpty: 'Internal error: only_if_empty flag rejected by the server.',
    PositionNotFound: 'Position not found - try refreshing.',
  };
  return known[raw] || raw;
}

// Per-row inline cost-basis entry (Block C2). A sibling of MaxFiScreen, not
// nested inside it, so it can hold its own edit/saving/error state per row
// without that state living in MaxFiScreen's own hooks.
//
// only_if_empty is ALWAYS sent as true on the first attempt (never the
// string "true") - the server-side guard added in Block C1 against
// overwriting a basis that already exists (e.g. an auto-split value a human
// already corrected - the "row 31" case). A skipped:true response is not
// success: it means the row already had a basis, and this component shows
// the EXISTING stored value/source from that response (never the value the
// user just typed) plus an explicit "Overwrite anyway" button, which resends
// the identical request with only_if_empty omitted entirely.
//
// api() returns undefined WITHOUT throwing on a 401 (see static/utils.js) -
// a naive `await` here would silently treat a login-redirect as N successes,
// so every submit path checks for that explicitly before touching onWritten.
function MaxFiBasisCell({ row, hideValues, onWritten }) {
  const [editing, setEditing] = React.useState(false);
  const [inputValue, setInputValue] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [skipInfo, setSkipInfo] = React.useState(null);

  // UNTRACKED - no DB row exists at all, so there is nowhere to write a
  // basis to. Only a scan can create the row this component would edit.
  if (row.dbId === null) {
    return React.createElement('span', null,
      mxNoBasisBadge(),
      React.createElement('span', {
        style: { marginLeft: 6, color: MX_C.secondary, fontSize: 11 },
      }, 'run a scan first'));
  }

  function cancelEdit() {
    setEditing(false);
    setError(null);
    setSkipInfo(null);
    setInputValue('');
  }

  async function doSubmit(overwrite) {
    const n = mxParseBasisInput(inputValue);
    if (n === null) {
      setError('Enter a number greater than 0.');
      return;
    }
    setError(null);
    setSkipInfo(null);
    setSaving(true);
    const body = overwrite
      ? { initial_value_usd: n }
      : { initial_value_usd: n, only_if_empty: true };
    try {
      const resp = await api('/api/maxfi/positions/' + row.dbId + '/initial-value', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      if (resp === undefined || resp === null) {
        setSaving(false);
        setError('session expired');
        return;
      }
      if (resp.skipped === true) {
        setSaving(false);
        setSkipInfo({ value: resp.initial_value_usd, source: resp.source });
        return;
      }
      setSaving(false);
      setEditing(false);
      setInputValue('');
      onWritten();
    } catch (e) {
      setSaving(false);
      setError(mxBasisErrorMessage(e));
    }
  }

  const p = row.position;
  const hasBasis = !!p && p.initial_value_usd !== null && p.initial_value_usd !== undefined;

  if (!editing) {
    return React.createElement('span', { style: { display: 'inline-flex', gap: 6, alignItems: 'center' } },
      hasBasis
        ? React.createElement('span', null, hideValues ? '••••' : fmt(p.initial_value_usd))
        : mxNoBasisBadge(),
      // Annotates the value itself, not the edit affordance - rendered only
      // display-side; write/parse/skip/error logic above is untouched.
      (hasBasis && row.initialValueSource === 'ambiguity_auto_split') ? mxAutoSplitBasisBadge() : null,
      React.createElement('span', {
        onClick: () => {
          setInputValue(hasBasis ? String(p.initial_value_usd) : '');
          setError(null);
          setSkipInfo(null);
          setEditing(true);
        },
        style: { color: MX_C.accent, fontSize: 11, fontWeight: 700, cursor: 'pointer', textDecoration: 'underline' },
      }, hasBasis ? 'edit' : 'set'));
  }

  return React.createElement('span', { style: { display: 'inline-flex', flexDirection: 'column', gap: 4 } },
    React.createElement('span', { style: { display: 'inline-flex', gap: 6, alignItems: 'center' } },
      React.createElement('input', {
        type: 'text',
        value: inputValue,
        disabled: saving,
        onChange: (e) => { setInputValue(e.target.value); setError(null); setSkipInfo(null); },
        onKeyDown: (e) => {
          if (e.key === 'Escape') cancelEdit();
          else if (e.key === 'Enter') doSubmit(false);
        },
        style: { width: 90, fontSize: 12, padding: '3px 6px', borderRadius: 4,
          border: '1px solid ' + MX_C.border, background: MX_C.bg, color: MX_C.primary },
      }),
      React.createElement('button', {
        onClick: () => doSubmit(false), disabled: saving, style: mxSmallBtnStyle(saving),
      }, saving ? '…' : 'Save'),
      React.createElement('button', {
        onClick: cancelEdit, disabled: saving, style: mxSmallBtnStyle(saving),
      }, 'Cancel')),
    error ? React.createElement('span', { style: { color: MX_C.warn, fontSize: 11 } }, error) : null,
    skipInfo ? React.createElement('span', { style: { display: 'inline-flex', flexDirection: 'column', gap: 4 } },
      React.createElement('span', { style: { color: MX_C.warn, fontSize: 11 } },
        'Already has a basis: ' + fmt(skipInfo.value) + ' (' + skipInfo.source + ').'),
      React.createElement('button', {
        onClick: () => doSubmit(true), disabled: saving, style: mxSmallBtnStyle(saving),
      }, 'Overwrite anyway')) : null);
}

// Manual close action (Block C2) - a sibling of MaxFiScreen for the same
// per-row-state reason as MaxFiBasisCell above.
function MaxFiCloseButton({ row, onWritten }) {
  const [confirming, setConfirming] = React.useState(false);
  const [closing, setClosing] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [result, setResult] = React.useState(null);

  // STALE only, and only when a DB row actually exists. Closing a row whose
  // pool is STILL held on-chain is silent data corruption, not a crash: the
  // unique index is ON maxfi_positions(chain, wallet, token_id) WHERE
  // status='open' and does NOT include array_index or pool_address, so the
  // next scan's plain INSERT (no OR IGNORE / ON CONFLICT) sees no conflict
  // at all and creates a duplicate open row with a fresh first_seen_at and
  // no basis, stranding the real basis on the row this button just closed.
  // MATCHED rows are still genuinely held (never offered); UNTRACKED rows
  // have no DB id to close.
  if (row.state !== 'stale' || row.dbId === null) return null;

  async function doClose() {
    setError(null);
    setClosing(true);
    try {
      const resp = await api('/api/maxfi/positions/' + row.dbId + '/close', { method: 'POST' });
      if (resp === undefined || resp === null) {
        setClosing(false);
        setError('session expired');
        return;
      }
      setClosing(false);
      setConfirming(false);
      // already_closed:true (a repeat call, or a concurrent scan that won
      // the race) is a normal outcome, not an error - closed_by is rendered
      // straight from the response, never assumed to be 'manual_ui'.
      setResult({ alreadyClosed: resp.already_closed, closedBy: resp.closed_by });
      onWritten();
    } catch (e) {
      setClosing(false);
      setError(mxExtractErr(e));
    }
  }

  if (result) {
    return React.createElement('span', { style: { color: MX_C.secondary, fontSize: 11 } },
      result.alreadyClosed ? `Already closed (by ${result.closedBy || 'a scan'}).` : 'Closed.');
  }

  if (!confirming) {
    return React.createElement('span', {
      onClick: () => setConfirming(true),
      style: { color: MX_C.warn, fontSize: 11, fontWeight: 700, cursor: 'pointer', textDecoration: 'underline' },
    }, 'Close');
  }

  const p = row.position;
  const pairLabel = mxPairLabel(p);
  const basisText = (p && p.initial_value_usd !== null && p.initial_value_usd !== undefined)
    ? fmt(p.initial_value_usd) : 'no basis';

  return React.createElement('span', { style: { display: 'inline-flex', flexDirection: 'column', gap: 4 } },
    React.createElement('span', { style: { color: MX_C.secondary, fontSize: 11 } },
      'Close ' + (pairLabel || mxTruncateAddr(row.poolAddress)) + ' (' + basisText + ')?'),
    error ? React.createElement('span', { style: { color: MX_C.warn, fontSize: 11 } }, error) : null,
    React.createElement('span', { style: { display: 'inline-flex', gap: 6 } },
      React.createElement('button', {
        onClick: doClose, disabled: closing, style: mxSmallBtnStyle(closing),
      }, closing ? '…' : 'Confirm'),
      React.createElement('button', {
        onClick: () => { setConfirming(false); setError(null); }, disabled: closing, style: mxSmallBtnStyle(closing),
      }, 'Cancel')));
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

  // Wallet selector (Block 2.5) - replaces the module-level MX_WALLET
  // constant. wallets is the maxfi-flagged subset of GET /api/wallets,
  // addresses lowercased on entry since the backend compares with LOWER()
  // (5da8366) - the lowercased form is the only form used from here on.
  const [wallets, setWallets] = React.useState([]);
  const [selectedWallet, setSelectedWallet] = React.useState(null);
  const [walletsLoading, setWalletsLoading] = React.useState(true);
  const [walletsError, setWalletsError] = React.useState(null);

  // epochRef guards against a late response from a previous wallet (or a
  // previous Refresh) landing in state after the input has moved on - the
  // file's first stale-response protection. Incremented on every wallet
  // switch and every Refresh; each loader closes over the epoch it was
  // started with and checks it again immediately before every state write.
  // valuationCacheRef persists valuation per wallet (keyed lowercased) across
  // switches, so returning to an already-valued wallet renders instantly
  // instead of re-running the slow RPC-bound fetch. autoValuationRef ensures
  // valuation auto-runs only for the first wallet shown on tab open - every
  // later switch to an uncached wallet requires an explicit click, since a
  // fresh valuation run is slow.
  const epochRef = React.useRef(0);
  const valuationCacheRef = React.useRef({});
  const autoValuationRef = React.useRef(true);

  const patchPositions = (slug, patch) => setPositions((prev) =>
    Object.assign({}, prev, { [slug]: Object.assign({}, prev[slug], patch) }));
  const patchValuation = (slug, patch) => setValuation((prev) =>
    Object.assign({}, prev, { [slug]: Object.assign({}, prev[slug], patch) }));

  async function loadWallets() {
    setWalletsLoading(true);
    setWalletsError(null);
    try {
      const d = await api('/api/wallets');
      if (d === undefined || d === null) {
        setWalletsError('session expired');
        setWalletsLoading(false);
        return;
      }
      const list = Array.isArray(d) ? d : (d.wallets || []);
      const flagged = list
        .filter((w) => w.maxfi === true)
        .map((w) => ({ address: String(w.address).toLowerCase(), label: w.label || '' }));
      setWallets(flagged);
      let stored = null;
      try { stored = localStorage.getItem('maxfiSelectedWallet'); } catch (e) { stored = null; }
      const storedLower = stored ? String(stored).toLowerCase() : null;
      const initial = (storedLower && flagged.some((w) => w.address === storedLower))
        ? storedLower
        : (flagged.length ? flagged[0].address : null);
      setSelectedWallet(initial);
      setWalletsLoading(false);
    } catch (e) {
      setWalletsError(mxExtractErr(e));
      setWalletsLoading(false);
    }
  }

  React.useEffect(() => { loadWallets(); }, []);

  function selectWallet(addr) {
    const lower = String(addr).toLowerCase();
    setSelectedWallet(lower);
    try { localStorage.setItem('maxfiSelectedWallet', lower); } catch (e) {}
  }

  async function loadPositionsFor(chain, wallet, epoch) {
    if (epochRef.current !== epoch) return;
    patchPositions(chain.slug, { loading: true, error: null });
    try {
      const data = await api(`/api/maxfi/positions/${chain.slug}/${wallet}`);
      if (data === undefined || data === null) {
        if (epochRef.current !== epoch) return;
        patchPositions(chain.slug, { loading: false, error: 'session expired' });
        return;
      }
      if (epochRef.current !== epoch) return;
      patchPositions(chain.slug, { data: Array.isArray(data) ? data : [], loading: false });
    } catch (e) {
      if (epochRef.current !== epoch) return;
      patchPositions(chain.slug, { loading: false, error: mxExtractErr(e) });
    }
  }

  async function loadValuationFor(chain, wallet, epoch) {
    if (epochRef.current !== epoch) return;
    patchValuation(chain.slug, { loading: true, error: null });
    try {
      const data = await api(`/api/maxfi/valuation/${chain.slug}/${wallet}`);
      if (data === undefined || data === null) {
        if (epochRef.current !== epoch) return;
        patchValuation(chain.slug, { loading: false, error: 'session expired' });
        return;
      }
      if (epochRef.current !== epoch) return;
      const entry = { data: data, loading: false, error: null, fetchedAt: Date.now() };
      valuationCacheRef.current[wallet] = valuationCacheRef.current[wallet] || {};
      valuationCacheRef.current[wallet][chain.slug] = entry;
      patchValuation(chain.slug, entry);
    } catch (e) {
      if (epochRef.current !== epoch) return;
      patchValuation(chain.slug, { loading: false, error: mxExtractErr(e) });
    }
  }

  // Phase 1 (positions, both chains in parallel) must fully settle before
  // Phase 2 (valuation, both chains in parallel) starts - deliberate, not
  // collapsed into one Promise.allSettled. runPositionsPhase/runValuationPhase
  // each capture epochRef.current at call time so every chain call in that
  // phase shares one epoch; refreshAll increments the epoch first so a
  // Refresh always invalidates whatever was in flight before it.
  async function runPositionsPhase(wallet) {
    const epoch = epochRef.current;
    await Promise.allSettled(MX_CHAINS.map((c) => loadPositionsFor(c, wallet, epoch)));
  }

  function runValuationPhase(wallet) {
    const epoch = epochRef.current;
    return Promise.allSettled(MX_CHAINS.map((c) => loadValuationFor(c, wallet, epoch)));
  }

  async function refreshAll(wallet) {
    epochRef.current += 1;
    await runPositionsPhase(wallet);
    runValuationPhase(wallet);
  }

  // Mount and wallet-switch effect. First selection ever made (autoValuationRef
  // still true) auto-runs valuation same as today's behaviour - UNTRACKED rows
  // and the LP Portfolio Value total only exist once valuation has loaded, so
  // a positions-only view is a degraded view. Every later switch either
  // renders that wallet's cache instantly (with its fetchedAt) or, if nothing
  // is cached for it yet, leaves valuation for an explicit "Load valuation"
  // click - a fresh valuation run is slow and switching wallets to browse
  // positions should not silently trigger it every time.
  React.useEffect(() => {
    if (!selectedWallet) return;
    epochRef.current += 1;
    const epoch = epochRef.current;
    setValuation(emptyChainState());
    (async () => {
      await runPositionsPhase(selectedWallet);
      if (epochRef.current !== epoch) return;
      const cached = valuationCacheRef.current[selectedWallet];
      if (cached) {
        setValuation((prev) => {
          const next = Object.assign({}, prev);
          MX_CHAINS.forEach((c) => { if (cached[c.slug]) next[c.slug] = cached[c.slug]; });
          return next;
        });
        return;
      }
      if (autoValuationRef.current) {
        autoValuationRef.current = false;
        runValuationPhase(selectedWallet);
      }
    })();
  }, [selectedWallet]);

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
        dbId: p.id, initialValueSource: p.initial_value_source,
        firstSeenAtSource: p.first_seen_at_source, closedBy: p.closed_by,
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
          dbId: null, initialValueSource: null, firstSeenAtSource: null, closedBy: null,
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
    const dollarText = sign + fmt(pnl);
    // ROI% derived from this SAME pnl_usd (Block C3) - basis is null-safe
    // against an UNTRACKED row's position:null. mxRoiLabel returns null (no
    // parentheses at all, never a placeholder) for a missing/non-finite/
    // zero/negative basis or a non-finite ratio, leaving dollarText exactly
    // as it renders today.
    const basis = row.position ? row.position.initial_value_usd : null;
    const roi = mxRoiLabel(pnl, basis);
    const text = hideValues ? '••••' : (roi ? dollarText + ' (' + roi + ')' : dollarText);
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
    React.createElement('select', {
      value: selectedWallet || '',
      disabled: anyBusy || wallets.length === 0,
      onClick: (ev) => ev.stopPropagation(),
      onChange: (ev) => { ev.stopPropagation(); selectWallet(ev.target.value); },
      style: { marginLeft: 'auto', background: '#1a1a3a', border: '1px solid ' + MX_C.border,
        color: MX_C.primary, padding: '4px 8px', borderRadius: 5, fontSize: 12, fontWeight: 600 } },
      wallets.length === 0
        ? React.createElement('option', { value: '' }, '—')
        : wallets.map((w) => React.createElement('option', { key: w.address, value: w.address },
            (w.label ? w.label + ' — ' : '') + mxTruncateAddr(w.address)))),
    React.createElement('button', {
      onClick: (ev) => { ev.stopPropagation(); if (selectedWallet) refreshAll(selectedWallet); },
      disabled: anyBusy || !selectedWallet,
      style: { background: '#1a1a3a', border: '1px solid ' + MX_C.border,
        color: MX_C.primary, padding: '4px 12px', borderRadius: 5, fontSize: 12, fontWeight: 600,
        cursor: (anyBusy || !selectedWallet) ? 'default' : 'pointer', opacity: (anyBusy || !selectedWallet) ? 0.6 : 1 } },
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
        `${chain.label} positions (/api/maxfi/positions/${chain.slug}/${selectedWallet}) failed: ${posState.error}`));
    if (valState.error) statusLines.push(
      React.createElement('div', { key: chain.slug + '-ve', style: { color: MX_C.warn, fontSize: 12, marginBottom: 4, fontWeight: 600 } },
        `${chain.label} valuation (/api/maxfi/valuation/${chain.slug}/${selectedWallet}) failed: ${valState.error}`));
  });

  const tableRows = rows.map((row, i) => {
    const p = row.position;   // null for an untracked row - no DB row exists
    const vcell = valueCell(row);
    const pcell = pnlCell(row);
    const stateBadge = row.state === 'stale' ? mxStaleBadge()
      : row.state === 'untracked' ? mxUntrackedBadge() : null;
    // null for an UNTRACKED row (mxPairLabel's own !position guard) and for
    // any row whose symbols haven't resolved yet - both fall back to the
    // truncated address below, never a guess.
    const pairLabel = mxPairLabel(p);
    const onWritten = () => loadPositionsFor(row.chain, selectedWallet, epochRef.current);
    return React.createElement('tr', {
      key: selectedWallet + '-' + row.chain.slug + '-' + row.arrayIndex + '-' + row.poolAddress,
      style: { background: i % 2 ? MX_C.zebra : 'transparent' } },
      td(row.chain.label),
      td(React.createElement('span', null,
        stateBadge,
        pairLabel
          ? React.createElement('span', { title: row.poolAddress || '' }, pairLabel)
          : React.createElement('span', { title: row.poolAddress || '' },
              mxTruncateAddr(row.poolAddress), ' ',
              React.createElement('span', {
                style: { fontSize: 11, color: MX_C.secondary, fontWeight: 700 },
              }, '(unresolved)')))),
      td(React.createElement('span', null,
        mxOpenDate(p),
        row.firstSeenAtSource === 'ambiguity_auto_split_inherited' ? mxInheritedDateBadge() : null)),
      td(String(row.tokenId)),
      td(React.createElement(MaxFiBasisCell, { row, hideValues, onWritten })),
      td(vcell.text, { color: vcell.color }),
      td(pcell.text, { color: pcell.color }),
      td(React.createElement(MaxFiCloseButton, { row, onWritten })));
  });

  const totalLabel = 'LP PORTFOLIO VALUE' + (partial ? ' (partial)' : '');
  const totalText = hideValues ? '••••' : fmt(total);

  // Wallet-list states are reported distinctly - a loading wallet list, a
  // wallet-fetch error, and "nothing flagged yet" all mean different things
  // and must never collapse into one message or a hardcoded fallback wallet.
  let walletBanner = null;
  if (walletsLoading) {
    walletBanner = React.createElement('div', { style: { color: MX_C.secondary, fontSize: 13 } }, 'Loading wallets…');
  } else if (walletsError) {
    walletBanner = React.createElement('div', { style: { color: MX_C.warn, fontSize: 13, fontWeight: 600 } },
      'Wallets: ' + walletsError);
  } else if (wallets.length === 0) {
    walletBanner = React.createElement('div', { style: { color: MX_C.secondary, fontSize: 13 } },
      'No wallets are flagged for MaxFi. Go to Settings → Wallets and enable the MaxFi toggle on a wallet.');
  }

  const anyValuationLoading = MX_CHAINS.some((c) => valuation[c.slug].loading);
  const hasAnyValuationData = MX_CHAINS.some((c) => valuation[c.slug].data);
  let valFetchedAt = null;
  MX_CHAINS.forEach((c) => {
    const f = valuation[c.slug].fetchedAt;
    if (f && (!valFetchedAt || f > valFetchedAt)) valFetchedAt = f;
  });

  // "as of" reuses fmtMxTime by converting the millisecond fetchedAt to an
  // ISO string first - fmtMxTime's numeric branch expects epoch SECONDS
  // (ts * 1000), so a raw Date.now() would misparse; its string branch just
  // does new Date(ts), which an ISO string satisfies correctly.
  let valuationControl = null;
  if (selectedWallet) {
    if (anyValuationLoading) {
      valuationControl = React.createElement('div', { style: { color: MX_C.secondary, fontSize: 12, marginBottom: 8 } },
        'Loading valuation…');
    } else if (hasAnyValuationData) {
      valuationControl = React.createElement('div', { style: { color: MX_C.secondary, fontSize: 12, marginBottom: 8 } },
        'Valuation as of ' + (valFetchedAt ? fmtMxTime(new Date(valFetchedAt).toISOString()) : '—'));
    } else {
      valuationControl = React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 } },
        React.createElement('button', {
          onClick: () => runValuationPhase(selectedWallet),
          style: mxSmallBtnStyle(false),
        }, 'Load valuation'),
        React.createElement('span', { style: { color: MX_C.secondary, fontSize: 11 } },
          'Valuation can take a couple of minutes per chain.'));
    }
  }

  const panelContent = walletBanner ? walletBanner : React.createElement('div', null,
    valuationControl,
    statusLines,
    rows.length === 0 ? React.createElement('div', {
      style: { color: MX_C.secondary, fontSize: 13 } },
      anyBusy ? 'Loading positions…' : 'No open MaxFi positions found.') : React.createElement('div', {
      style: { border: '1px solid ' + MX_C.border, borderRadius: 6, overflow: 'hidden' } },
      React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse', background: MX_C.bg } },
        React.createElement('thead', { style: { background: MX_C.head } },
          React.createElement('tr', null,
            th('Chain'), th('Pool'), th('Opened'), th('Token ID (current)'), th('Basis'), th('Value'), th('P/L'), th('Actions'))),
        React.createElement('tbody', null, tableRows))),
    React.createElement('div', {
      style: { marginTop: 10, display: 'flex', alignItems: 'center', gap: 8,
        fontSize: 13, fontWeight: 700, color: MX_C.primary } },
      React.createElement('span', { style: { color: MX_C.secondary, fontWeight: 700, letterSpacing: '0.04em' } },
        totalLabel + ':'),
      React.createElement('span', null, totalText)));

  const body = React.createElement('div', {
    style: { background: MX_C.panel, border: '1px solid ' + MX_C.border, borderRadius: 6,
      padding: '12px 16px', marginBottom: 12 } },
    header,
    open ? React.createElement('div', { style: { marginTop: 10 } }, panelContent) : null);

  return React.createElement(MaxFiErrorBoundary, null, body);
}

window.MaxFiScreen = MaxFiScreen;
