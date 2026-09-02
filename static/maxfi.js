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
  // zebra was #161b22, an ~2% brightness step above bg - too faint to track
  // a row across seven columns. Widened to ~8% (the top of the project's
  // 5-8% banding standard). hover sits ~16% above zebra / ~24% above bg -
  // clearly stronger than the banding delta regardless of which band the
  // hovered row started on.
  bg: '#12161c', panel: '#0d1117', head: '#1b2129', zebra: '#262a30', hover: '#4e5258',
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
  { slug: 'robinhood', label: 'RH' },
  { slug: 'base', label: 'Base' },
];

// Same "extract a structured error from api()'s thrown text" pattern used
// throughout trading.js.
function mxExtractErr(e) {
  let msg = (e && e.message) ? e.message : String(e);
  try { const j = JSON.parse(msg); if (j && j.error) msg = j.error; } catch (e2) {}
  return msg;
}

// api() throws on any non-2xx with only the raw response TEXT as
// Error.message, which would discard FullCloseRefused's open_count. This
// helper never throws for an HTTP error status - callers branch on
// .ok/.status instead - so the scan runner can read structured error
// bodies directly.
async function mxScanFetch(path) {
  const res = await fetch(path, { method: 'POST' });
  if (res.status === 401) {
    window.location.href = '/login';
    return null;
  }
  let body = {};
  try { body = await res.json(); } catch (e) {}
  return { ok: res.ok, status: res.status, body: body };
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

// Same shape as mxOpenDate, but takes the raw ISO string directly (closed_at
// has no wrapping position-shaped object the way first_seen_at does) - NOT
// formatDateShort, which has no timezone pin and would sit next to
// mxOpenDate's PT-pinned dates in the same row showing a different zone.
function mxClosedDate(iso) {
  if (!iso) return '—';
  try {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'America/Los_Angeles' });
  } catch (e) { return '—'; }
}

// fmt(null) renders '$0.00', indistinguishable from a genuine zero. Use this
// instead of fmt() directly for any figure that can be legitimately absent
// (no basis recorded, no closing value entered yet).
function mxFmtOrDash(value) {
  if (value === null || value === undefined) return '—';
  return fmt(value);
}

// Mirrors mxParseBasisInput's cleaning exactly, but accepts 0 - the backend's
// closing_value_usd rule rejects only < 0 (a position can genuinely drain to
// zero), unlike /initial-value's basis rule which mxParseBasisInput enforces.
function mxParseClosingInput(raw) {
  const cleaned = String(raw).trim().replace(/^\$/, '').replace(/,/g, '');
  const n = Number(cleaned);
  if (!isFinite(n) || n < 0) return null;
  return n;
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

// Wraps mxBadge() in a title-bearing span, same pattern as
// mxInheritedDateBadge/mxAutoSplitBasisBadge above (mxBadge itself takes no
// title). `reason` is the ambiguous_flagged entry's own reason string -
// there is more than one distinct reason across entries, so it is shown
// verbatim as the tooltip rather than paraphrased into one fixed sentence.
function mxNeedsReviewBadge(reason) {
  return React.createElement('span', {
    style: { marginLeft: 6 },
    title: reason,
  }, mxBadge('needs review', MX_C.warn, 'rgba(240,120,120,0.14)'));
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
        onClick: (ev) => {
          ev.stopPropagation();
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
        onClick: (ev) => ev.stopPropagation(),
        onChange: (e) => { setInputValue(e.target.value); setError(null); setSkipInfo(null); },
        onKeyDown: (e) => {
          e.stopPropagation();
          if (e.key === 'Escape') cancelEdit();
          else if (e.key === 'Enter') doSubmit(false);
        },
        style: { width: 90, fontSize: 12, padding: '3px 6px', borderRadius: 4,
          border: '1px solid ' + MX_C.border, background: MX_C.bg, color: MX_C.primary },
      }),
      React.createElement('button', {
        onClick: (ev) => { ev.stopPropagation(); doSubmit(false); }, disabled: saving, style: mxSmallBtnStyle(saving),
      }, saving ? '…' : 'Save'),
      React.createElement('button', {
        onClick: (ev) => { ev.stopPropagation(); cancelEdit(); }, disabled: saving, style: mxSmallBtnStyle(saving),
      }, 'Cancel')),
    error ? React.createElement('span', { style: { color: MX_C.warn, fontSize: 11 } }, error) : null,
    skipInfo ? React.createElement('span', { style: { display: 'inline-flex', flexDirection: 'column', gap: 4 } },
      React.createElement('span', { style: { color: MX_C.warn, fontSize: 11 } },
        'Already has a basis: ' + fmt(skipInfo.value) + ' (' + skipInfo.source + ').'),
      React.createElement('button', {
        onClick: (ev) => { ev.stopPropagation(); doSubmit(true); }, disabled: saving, style: mxSmallBtnStyle(saving),
      }, 'Overwrite anyway')) : null);
}

// Inline closing-value entry for the closed positions table. Mirrors
// MaxFiBasisCell's edit/saving/error local-state shape, but targets
// /user-data (not /initial-value): only closing_value_usd is ever sent -
// user_note is left absent so the route's _MISSING semantics leave any
// existing note untouched, never risking clobbering it. There is no
// only_if_empty/skip concept here (unlike basis, a closing value is always
// directly editable) and no overwrite-confirm branch.
function MaxFiClosingValueCell({ dbId, closingValueUsd, onWritten }) {
  const [editing, setEditing] = React.useState(false);
  const [inputValue, setInputValue] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState(null);

  function cancelEdit(ev) {
    ev.stopPropagation();
    setEditing(false);
    setError(null);
    setInputValue('');
  }

  async function doSubmit(ev) {
    ev.stopPropagation();
    const n = mxParseClosingInput(inputValue);
    if (n === null) {
      setError('Enter a number 0 or greater.');
      return;
    }
    setError(null);
    setSaving(true);
    try {
      const resp = await api('/api/maxfi/positions/' + dbId + '/user-data', {
        method: 'POST',
        body: JSON.stringify({ closing_value_usd: n }),
      });
      if (resp === undefined || resp === null) {
        setSaving(false);
        setError('session expired');
        return;
      }
      setSaving(false);
      setEditing(false);
      setInputValue('');
      onWritten();
    } catch (e) {
      setSaving(false);
      setError(mxNotesErrorMessage(e));
    }
  }

  const hasValue = closingValueUsd !== null && closingValueUsd !== undefined;

  if (!editing) {
    return React.createElement('span', { style: { display: 'inline-flex', gap: 6, alignItems: 'center' } },
      React.createElement('span', null, mxFmtOrDash(closingValueUsd)),
      React.createElement('span', {
        onClick: (ev) => {
          ev.stopPropagation();
          setInputValue(hasValue ? String(closingValueUsd) : '');
          setError(null);
          setEditing(true);
        },
        style: { color: MX_C.accent, fontSize: 11, fontWeight: 700, cursor: 'pointer', textDecoration: 'underline' },
      }, hasValue ? 'edit' : 'set'));
  }

  return React.createElement('span', { style: { display: 'inline-flex', flexDirection: 'column', gap: 4 } },
    React.createElement('span', { style: { display: 'inline-flex', gap: 6, alignItems: 'center' } },
      React.createElement('input', {
        type: 'text',
        value: inputValue,
        disabled: saving,
        onClick: (ev) => ev.stopPropagation(),
        onChange: (e) => { setInputValue(e.target.value); setError(null); },
        onKeyDown: (e) => {
          e.stopPropagation();
          if (e.key === 'Escape') cancelEdit(e);
          else if (e.key === 'Enter') doSubmit(e);
        },
        style: { width: 90, fontSize: 12, padding: '3px 6px', borderRadius: 4,
          border: '1px solid ' + MX_C.border, background: MX_C.bg, color: MX_C.primary },
      }),
      React.createElement('button', {
        onClick: doSubmit, disabled: saving, style: mxSmallBtnStyle(saving),
      }, saving ? '…' : 'Save'),
      React.createElement('button', {
        onClick: cancelEdit, disabled: saving, style: mxSmallBtnStyle(saving),
      }, 'Cancel')),
    error ? React.createElement('span', { style: { color: MX_C.warn, fontSize: 11 } }, error) : null);
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
      onClick: (ev) => { ev.stopPropagation(); setConfirming(true); },
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
        onClick: (ev) => { ev.stopPropagation(); doClose(); }, disabled: closing, style: mxSmallBtnStyle(closing),
      }, closing ? '…' : 'Confirm'),
      React.createElement('button', {
        onClick: (ev) => { ev.stopPropagation(); setConfirming(false); setError(null); }, disabled: closing, style: mxSmallBtnStyle(closing),
      }, 'Cancel')));
}

// Pool cell: badge + pair label/address, tooltip carrying BOTH the pool
// address and the token id (the Token ID column this replaces), and
// click-to-copy for the token id. A sibling of MaxFiScreen, same reason as
// MaxFiBasisCell/MaxFiCloseButton above - the transient "Copied" indicator
// is per-row state that has no reason to live in MaxFiScreen's own hooks.
// No existing click-to-copy pattern exists anywhere else in this file to
// reuse.
function MaxFiPoolCell({ row, ambiguousReason, hasNote, canExpand }) {
  const [copied, setCopied] = React.useState(false);
  const stateBadge = row.state === 'stale' ? mxStaleBadge()
    : row.state === 'untracked' ? mxUntrackedBadge() : null;
  // null for an UNTRACKED row (mxPairLabel's own !position guard) and for
  // any row whose symbols haven't resolved yet - both fall back to the
  // truncated address below, never a guess.
  const pairLabel = mxPairLabel(row.position);
  const hasTokenId = row.tokenId !== null && row.tokenId !== undefined && row.tokenId !== '';
  const title = 'Pool ' + mxTruncateAddr(row.poolAddress)
    + (hasTokenId ? ' · Token ' + row.tokenId : '');

  function doCopy(ev) {
    ev.stopPropagation();
    if (!hasTokenId) return;
    navigator.clipboard.writeText(String(row.tokenId)).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  }

  return React.createElement('span', {
    title: title,
    onClick: hasTokenId ? doCopy : undefined,
    style: hasTokenId ? { cursor: 'pointer' } : undefined,
  },
    stateBadge,
    pairLabel
      ? React.createElement('span', null, pairLabel)
      : React.createElement('span', null,
          mxTruncateAddr(row.poolAddress), ' ',
          React.createElement('span', {
            style: { fontSize: 11, color: MX_C.secondary, fontWeight: 700 },
          }, '(unresolved)')),
    // Moved in from the old chevron cell (removed) - a row with no DB row
    // (canExpand false) gets no dot at all, never a hollow one: hasNote is
    // false for BOTH "no note" and "no DB row", so canExpand is passed
    // separately rather than inferred from hasNote alone.
    canExpand ? React.createElement('span', {
      title: hasNote ? 'Has a note' : 'No note',
      style: { marginLeft: 6, fontSize: 11, color: MX_C.secondary },
    }, hasNote ? '●' : '○') : null,
    copied ? React.createElement('span', {
      style: { marginLeft: 6, fontSize: 11, color: MX_C.accent, fontWeight: 700 },
    }, 'Copied') : null,
    // Non-interactive - a title tooltip only, no button/link. Chosen for
    // this cell because the ambiguity is fundamentally about the pool/
    // position identity (a manual exit and re-entry that reused an array
    // index), and this is already the cell that carries every other
    // identity signal (state badge, pair label, pool address).
    ambiguousReason ? mxNeedsReviewBadge(ambiguousReason) : null);
}

// The stored value is the full word ('crypto'/'stock'); the letter is
// display-only. Anything else (null, or an unrecognised future value)
// renders as an empty string rather than guessing.
function mxAssetClassLetter(assetClass) {
  if (assetClass === 'crypto') return 'C';
  if (assetClass === 'stock') return 'S';
  return '';
}

// Maps /user-data's {"error","detail"} shape into "Code: detail" - unlike
// mxBasisErrorMessage, there's no established plain-language mapping for
// these three codes yet, so the backend's own detail prose is shown
// directly rather than re-worded.
function mxNotesErrorMessage(e) {
  try {
    const parsed = JSON.parse((e && e.message) || '');
    if (parsed && parsed.error) {
      return parsed.error + (parsed.detail ? ': ' + parsed.detail : '');
    }
  } catch (e2) {}
  return mxExtractErr(e);
}

// Per-row notes editor for the expanding panel below a row - a sibling of
// MaxFiScreen, same local-state pattern as MaxFiBasisCell/MaxFiCloseButton.
// This slice is the notes editor ONLY - not the auto-split JSON, not
// identity fields, not closing value (closing_value_usd stays console-only:
// the positions list has no status filter and shows only open rows, so a
// closed row's value can't be verified in this UI yet).
//
// api() returns undefined WITHOUT throwing on a 401 (see static/utils.js) -
// same guard as every other write path in this file, so a login-redirect
// is never reported as a successful save.
function MaxFiNotesEditor({ row, onWritten }) {
  const [value, setValue] = React.useState(row.userNote || '');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState(null);

  async function doSave() {
    setError(null);
    setSaving(true);
    try {
      // user_note ONLY - closing_value_usd is never sent from this UI.
      const resp = await api('/api/maxfi/positions/' + row.dbId + '/user-data', {
        method: 'POST',
        body: JSON.stringify({ user_note: value }),
      });
      if (resp === undefined || resp === null) {
        setSaving(false);
        setError('session expired');
        return;
      }
      setSaving(false);
      onWritten();
    } catch (e) {
      setSaving(false);
      setError(mxNotesErrorMessage(e));
    }
  }

  function doCancel() {
    setValue(row.userNote || '');
    setError(null);
  }

  const remaining = 2000 - value.length;

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, flex: 1, minWidth: 360, maxWidth: 960 } },
    React.createElement('textarea', {
      value: value,
      disabled: saving,
      rows: 3,
      // Hard client-side cap - matches the backend's 2000-char limit so the
      // user is never surprised by an InvalidUserNote rejection after typing.
      onChange: (e) => { setValue(e.target.value.slice(0, 2000)); setError(null); },
      style: { width: '100%', boxSizing: 'border-box', fontSize: 12, padding: '6px 8px',
        borderRadius: 4, border: '1px solid ' + MX_C.border, background: MX_C.bg,
        color: MX_C.primary, resize: 'vertical', fontFamily: 'inherit' },
    }),
    React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
      React.createElement('button', {
        onClick: doSave, disabled: saving, style: mxSmallBtnStyle(saving),
      }, saving ? '…' : 'Save'),
      React.createElement('button', {
        onClick: doCancel, disabled: saving, style: mxSmallBtnStyle(saving),
      }, 'Cancel'),
      React.createElement('span', {
        style: { color: remaining < 0 ? MX_C.warn : MX_C.secondary, fontSize: 11 },
      }, remaining + ' characters left')),
    error ? React.createElement('span', { style: { color: MX_C.warn, fontSize: 11 } }, error) : null);
}

// Local browser-day 'YYYY-MM-DD', built from getFullYear/getMonth/getDate -
// deliberately NOT toISOString(), which converts to UTC first and would show
// yesterday's date for anyone west of UTC in the evening local time.
function mxTodayLocalDateString() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return y + '-' + m + '-' + day;
}

// Formats a bare 'YYYY-MM-DD' claimed_at string directly from its Y/M/D
// components - deliberately NOT mxOpenDate/mxClosedDate's new Date(iso) +
// toLocaleDateString(..., {timeZone: 'America/Los_Angeles'}) approach. Those
// two are built for a FULL ISO datetime+offset string (first_seen_at/
// closed_at are both written server-side via
// datetime.now(timezone.utc).isoformat()), which new Date() parses
// unambiguously before re-rendering in Pacific time. A bare 'YYYY-MM-DD'
// claimed_at has no time component, so new Date('2026-06-15') parses as UTC
// MIDNIGHT - re-rendering that in America/Los_Angeles (always behind UTC)
// would show "Jun 14" for a date the user picked as "Jun 15", a guaranteed
// off-by-one-day bug. A claim date is a plain calendar date with nothing to
// convert, so this reads the string directly - no Date object, no timezone
// involved at all - matching mxOpenDate/mxClosedDate's "MMM D" display shape.
const MX_MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function mxClaimDateLabel(claimedAt) {
  if (typeof claimedAt !== 'string') return '—';
  const m = claimedAt.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return '—';
  const monthIdx = parseInt(m[2], 10) - 1;
  const day = parseInt(m[3], 10);
  if (monthIdx < 0 || monthIdx > 11 || !day) return '—';
  return MX_MONTH_ABBR[monthIdx] + ' ' + day;
}

// Per-row claims list + entry form, rendered beside MaxFiNotesEditor inside
// MaxFiExpandedPanel. Sends ONLY claimed_at and proceeds_usd - token symbol/
// amount and note exist in the schema for later display but are deliberately
// not on this form (see this block's own rationale: nothing cross-checks a
// claim's proceeds against any other record, so fewer inputs means less typo
// surface). Never triggers a valuation: onWritten() re-runs loadPositionsFor
// only, which refreshes the Claimed column - a live P/L walk costs ~2m25s
// per chain and must never start from a write path.
//
// No ev.stopPropagation() anywhere in this component, unlike
// MaxFiBasisCell/MaxFiCloseButton - this panel lives in the expanded row's
// own separate <tr>, which has no onClick of its own (same reasoning
// MaxFiNotesEditor already relies on), so there is nothing to bubble into.
function MaxFiClaimsPanel({ row, onWritten, hideValues }) {
  const [claims, setClaims] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState(null);
  const [dateValue, setDateValue] = React.useState(mxTodayLocalDateString());
  const [amountValue, setAmountValue] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [saveError, setSaveError] = React.useState(null);
  const [savedNote, setSavedNote] = React.useState(false);
  const [confirmingDeleteId, setConfirmingDeleteId] = React.useState(null);
  const [deletingId, setDeletingId] = React.useState(null);

  function fetchClaims() {
    return api('/api/maxfi/positions/' + row.dbId + '/claims');
  }

  // First useEffect in a MaxFi row component - collapsing the row unmounts
  // this component mid-flight, so every setState after the await is guarded
  // by `cancelled`, set true in the cleanup.
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetchClaims();
        if (cancelled) return;
        if (resp === undefined || resp === null) {
          setLoadError('session expired');
          setLoading(false);
          return;
        }
        setClaims(Array.isArray(resp) ? resp : []);
        setLoading(false);
      } catch (e) {
        if (cancelled) return;
        setLoadError(mxNotesErrorMessage(e));
        setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [row.dbId]);

  async function doSave() {
    setSaveError(null);
    if (!dateValue) {
      setSaveError('Enter a date.');
      return;
    }
    // An empty amount means "swept but not yet sold" -> proceeds_usd: null,
    // NOT 0 - so blank is checked BEFORE parsing, never fed into
    // mxParseClosingInput itself (Number('') is 0 in JS, which would
    // silently turn a blank field into a real zero).
    const trimmedAmount = amountValue.trim();
    let proceedsUsd = null;
    if (trimmedAmount !== '') {
      // Same rule MaxFiClosingValueCell uses (mxParseClosingInput): accepts
      // 0, rejects < 0 - proceeds of exactly zero is a real, legal outcome.
      // mxParseBasisInput's <= 0 rule does not apply to proceeds.
      const n = mxParseClosingInput(trimmedAmount);
      if (n === null) {
        setSaveError('Enter a number 0 or greater, or leave it blank.');
        return;
      }
      proceedsUsd = n;
    }

    setSaving(true);
    try {
      const resp = await api('/api/maxfi/positions/' + row.dbId + '/claims', {
        method: 'POST',
        body: JSON.stringify({ claimed_at: dateValue, proceeds_usd: proceedsUsd }),
      });
      if (resp === undefined || resp === null) {
        setSaving(false);
        setSaveError('session expired');
        return;
      }
      setSaving(false);
      setAmountValue('');
      setDateValue(mxTodayLocalDateString());
      // Local refetch (this panel's own list) and onWritten() (the Claimed
      // column, via loadPositionsFor) are two different refreshes - neither
      // substitutes for the other.
      const listResp = await fetchClaims();
      if (Array.isArray(listResp)) setClaims(listResp);
      onWritten();
      setSavedNote(true);
    } catch (e) {
      setSaving(false);
      setSaveError(mxNotesErrorMessage(e));
    }
  }

  // Delete errors render in this same saveError slot rather than inline per
  // claim row - one error slot for every write this panel can make, same
  // shape as every other sibling component in this file (one `error` state
  // per component, not one per action).
  async function doDelete(claimId) {
    setDeletingId(claimId);
    try {
      const resp = await api('/api/maxfi/claims/' + claimId, { method: 'DELETE' });
      if (resp === undefined || resp === null) {
        setDeletingId(null);
        setSaveError('session expired');
        return;
      }
      setDeletingId(null);
      setConfirmingDeleteId(null);
      const listResp = await fetchClaims();
      if (Array.isArray(listResp)) setClaims(listResp);
      onWritten();
    } catch (e) {
      setDeletingId(null);
      setSaveError(mxNotesErrorMessage(e));
    }
  }

  let listBlock;
  if (loading) {
    listBlock = React.createElement('div', { style: { color: MX_C.secondary, fontSize: 12, marginBottom: 6 } }, '…');
  } else if (loadError) {
    listBlock = React.createElement('div', { style: { color: MX_C.warn, fontSize: 12, marginBottom: 6 } }, loadError);
  } else if (claims.length === 0) {
    listBlock = React.createElement('div', { style: { color: MX_C.secondary, fontSize: 12, marginBottom: 6 } }, 'No claims recorded');
  } else {
    listBlock = React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 6 } },
      claims.map((c) => {
        const isConfirming = confirmingDeleteId === c.id;
        const isDeleting = deletingId === c.id;
        return React.createElement('div', {
          key: c.id,
          style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: MX_C.primary },
        },
          React.createElement('span', { style: { minWidth: 44 } }, mxClaimDateLabel(c.claimed_at)),
          React.createElement('span', { style: { minWidth: 70 } }, hideValues ? '••••' : mxFmtOrDash(c.proceeds_usd)),
          isConfirming
            ? React.createElement('span', { style: { display: 'inline-flex', gap: 6 } },
                React.createElement('button', {
                  onClick: () => doDelete(c.id), disabled: isDeleting, style: mxSmallBtnStyle(isDeleting),
                }, isDeleting ? '…' : 'Confirm'),
                React.createElement('button', {
                  onClick: () => setConfirmingDeleteId(null), disabled: isDeleting, style: mxSmallBtnStyle(isDeleting),
                }, 'Cancel'))
            : React.createElement('span', {
                onClick: () => setConfirmingDeleteId(c.id),
                style: { color: MX_C.warn, fontSize: 11, fontWeight: 700, cursor: 'pointer', textDecoration: 'underline' },
              }, 'delete'));
      }));
  }

  const inputStyle = { fontSize: 12, padding: '3px 6px', borderRadius: 4,
    border: '1px solid ' + MX_C.border, background: MX_C.bg, color: MX_C.primary };

  return React.createElement('div', { style: { flex: 1, minWidth: 360 } },
    React.createElement('div', { style: { color: MX_C.secondary, fontSize: 11, fontWeight: 700, marginBottom: 6 } }, 'CLAIMS'),
    listBlock,
    React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
      React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
        React.createElement('input', {
          type: 'date',
          value: dateValue,
          disabled: saving,
          onChange: (e) => { setDateValue(e.target.value); setSavedNote(false); setSaveError(null); },
          style: inputStyle,
        }),
        React.createElement('input', {
          type: 'text',
          value: amountValue,
          disabled: saving,
          placeholder: 'Proceeds (optional)',
          onChange: (e) => { setAmountValue(e.target.value); setSavedNote(false); setSaveError(null); },
          style: Object.assign({ width: 130 }, inputStyle),
        }),
        React.createElement('button', {
          onClick: doSave, disabled: saving, style: mxSmallBtnStyle(saving),
        }, saving ? '…' : 'Save')),
      saveError ? React.createElement('span', { style: { color: MX_C.warn, fontSize: 11 } }, saveError) : null,
      // P/L needs a live valuation, which this panel must never trigger -
      // the Claimed column already refreshed via onWritten() by the time
      // this renders, but adjusted P/L has not, so this says so once.
      savedNote ? React.createElement('span', { style: { color: MX_C.secondary, fontSize: 11 } },
        'Saved. P/L updates on the next Refresh.') : null));
}

// Lays the expanded row panel's two independent halves side by side -
// claims (left) and notes (right). flexWrap lets the claims column drop
// below the notes editor on a narrow viewport rather than crushing either
// one; there are no media queries anywhere in this file and none are added
// here - flexWrap is the only responsive mechanism available.
function MaxFiExpandedPanel({ row, onWritten, hideValues }) {
  return React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 16 } },
    React.createElement(MaxFiClaimsPanel, { row, onWritten, hideValues }),
    React.createElement(MaxFiNotesEditor, { row, onWritten }));
}

// Legend data - a plain array of {label, meaning, action}, mapped over by
// MaxFiLegend below. A later task appends rows here; it never needs to
// touch the rendering markup to do so. action is null where there is
// nothing to do about it (a permanent or informational state).
const MX_LEGEND = [
  { label: 'NO BASIS', meaning: 'No cost basis recorded, so P/L cannot be computed.',
    action: 'Click "set" in that row.' },
  { label: 'run a scan first',
    meaning: 'The position is held on-chain but has no saved row yet, so there is nothing to attach a basis to.',
    action: 'Run a Scan.' },
  { label: 'UNTRACKED',
    meaning: 'Held on-chain with no saved row. Appears only after a valuation has run.',
    action: 'Run a Scan.' },
  { label: 'STALE', meaning: 'A saved row whose pool is no longer held on-chain.',
    action: 'Click "Close" in that row.' },
  { label: 'inherited',
    meaning: 'The open date was carried over from a previous position in the same pool and may '
      + 'be inaccurate. This is a known limitation with no correction available.',
    action: null },
  { label: 'auto-split',
    meaning: 'The basis was derived automatically when two positions in one pool were exchanged.',
    action: null },
  { label: '(unresolved)',
    meaning: 'Token symbols could not be resolved. This is permanent for pools no longer held '
      + 'and is correct, not an error.',
    action: null },
  { label: 'needs review',
    meaning: 'A Scan found a position it could not match to a saved row, usually a manual exit '
      + 'and re-entry that reused an array index. It will keep reporting on every scan until '
      + 'resolved by hand.',
    action: null },
  { label: 'unavailable', meaning: 'The live price lookup failed for that row.',
    action: 'Refresh to retry.' },
  { label: 'C', meaning: 'Asset class: crypto. The Class column shows the letter; the full '
      + 'word is stored and shown in the cell’s tooltip.', action: null },
  { label: 'S', meaning: 'Asset class: stock. Same column and tooltip as crypto, above.',
    action: null },
  { label: '● / ○',
    meaning: 'Clicking anywhere on a row expands it to add or edit a note for that position. '
      + 'A filled dot in the Pool column means a note already exists; an open dot means it '
      + 'does not. Untracked rows have no saved position to attach a note to, so they show '
      + 'no dot and do not expand.',
    action: null },
  { label: null,
    meaning: 'Positions come from a Scan; values are priced live on a separate Refresh - the '
      + '"Positions as of" and "Valuation as of" timestamps above refer to these two different actions.',
    action: null },
  { label: 'CLOSED POSITIONS',
    meaning: 'The section below the main table lists positions that are no longer held. A '
      + 'closing value can be entered inline to compute final ROI. Closed rows are never '
      + 'priced live, so they show no current value or live P/L.',
    action: null },
  { label: 'Claimed',
    meaning: 'Fees swept to the wallet when a position rebalanced, and since '
      + 'sold. These left the position, so they are counted on top of its current '
      + 'value when P/L is computed. A dash means no claims are recorded for that '
      + 'position.',
    action: null },
  { label: 'unavailable (Claimed)',
    meaning: 'The claims lookup failed for that request, so claimed totals could '
      + 'not be loaded. P/L still shows, but understates any position with claims.',
    action: 'Refresh to retry.' },
  { label: 'CLAIMS',
    meaning: 'Expand a row to record fees that were swept to the wallet when a '
      + 'position rebalanced and have since been sold. Enter the date and the '
      + 'proceeds; leave proceeds empty if the tokens have not been sold yet. '
      + 'The Claimed column updates immediately, but P/L updates on the next '
      + 'Refresh.',
    action: null },
  { label: 'CLOSED CLAIMS',
    meaning: 'Closed rows expand too. Fee tokens are often sold after a position '
      + 'is closed, so a claim can be recorded against a closed position; its '
      + 'Claimed, P/L and ROI update immediately, with no Refresh needed, because '
      + 'closed rows are never priced live.',
    action: null },
  { label: 'SUMMARY',
    meaning: 'Totals for this wallet across both chains. Unrealised covers open '
      + 'positions, realised covers closed ones. A figure showing an ellipsis is '
      + 'still loading and is never shown as a number until every chain has '
      + 'reported. Any rows a total could not include are counted underneath.',
    action: null },
];

function MaxFiLegend({ entries }) {
  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
    entries.map((e, i) => React.createElement('div', {
      key: i, style: { fontSize: 12, color: MX_C.secondary } },
      e.label ? React.createElement('span', {
        style: { color: MX_C.primary, fontWeight: 700, marginRight: 6 },
      }, e.label) : null,
      e.meaning,
      e.action ? React.createElement('span', {
        style: { color: MX_C.accent, fontWeight: 600 },
      }, ' ' + e.action) : null)));
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

  // Scan state. scanning drives the Scan button's label/disabled state;
  // scanResult holds the per-chain outcome to render until dismissed or a
  // new scan starts; scanConfirm holds a pending FullCloseRefused prompt
  // (or null) as {slug, label, openCount}.
  const [scanning, setScanning] = React.useState(false);
  const [scanResult, setScanResult] = React.useState(null);
  const [scanConfirm, setScanConfirm] = React.useState(null);

  // Row hover highlight: ONE state variable holding the hovered row's own
  // key (not one flag per row), set/cleared on each <tr>'s onMouseEnter/
  // onMouseLeave - React inline styles can't express :hover and this file
  // has no className mechanism for a real :hover rule.
  const [hoveredRowKey, setHoveredRowKey] = React.useState(null);
  // Legend starts collapsed - with 25+ rows it would otherwise push the
  // table below the fold.
  const [legendOpen, setLegendOpen] = React.useState(false);

  // Closed positions section - collapsed by default, same plain in-memory
  // pattern as open/legendOpen above (no localStorage). closedShowAll has no
  // collapse-back control once set true, matching the legend's own one-way
  // set-and-forget shape for state that only ever grows more open.
  const [closedOpen, setClosedOpen] = React.useState(false);
  const [closedShowAll, setClosedShowAll] = React.useState(false);

  // Raw ambiguous_flagged entries per chain slug, so a row can be marked
  // "needs review" rather than only counted in the dismissible scan
  // summary. In-memory only - lost on reload until the next scan; that is
  // accepted for this slice. Keyed by slug (mirroring scanResult's merge)
  // so a Base-only re-scan cannot clear Robinhood's entries, and cleared
  // per-wallet in the wallet-switch effect below since these are per-wallet
  // facts.
  const [ambiguousByChain, setAmbiguousByChain] = React.useState({});
  // Expanded per-row notes panel, keyed on the existing rowKey expression
  // (already includes the wallet) - never on array_index, which re-sorts
  // and is reused across a manual exit/re-entry.
  const [expandedRowKeys, setExpandedRowKeys] = React.useState({});

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
      // Cache write happens BEFORE the epoch check: the cache is keyed by
      // the wallet the request was made FOR, so a late write cannot corrupt
      // another wallet's entry - discarding a completed ~2m25s valuation
      // because the user switched wallets mid-flight is pure loss. The
      // STATE write stays epoch-guarded below because that would paint the
      // wrong wallet's data on screen.
      const entry = { data: data, loading: false, error: null, fetchedAt: Date.now() };
      valuationCacheRef.current[wallet] = valuationCacheRef.current[wallet] || {};
      valuationCacheRef.current[wallet][chain.slug] = entry;
      if (epochRef.current !== epoch) return;
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

  // Runs a scan for `wallet` SEQUENTIALLY (a plain for...of with await,
  // never Promise.all) over `chainSlugs` - each chain is independent, so
  // one chain's failure must never prevent the next from being attempted.
  // `chainSlugs` (a Set of slugs) restricts which of MX_CHAINS are scanned;
  // absent or empty means all of them, which is the normal Scan button's
  // behaviour and must not change. `permittedFullClose` is a Set of chain
  // slugs allowed to pass allow_full_close=true; empty for a normal scan.
  // Never touches valuation and never increments epochRef - a scan is a
  // positions-only write/reload, not a wallet switch.
  async function runScan(wallet, permittedFullClose, chainSlugs) {
    permittedFullClose = permittedFullClose || new Set();
    const restricted = !!(chainSlugs && chainSlugs.size > 0);
    const chainsToScan = restricted ? MX_CHAINS.filter((c) => chainSlugs.has(c.slug)) : MX_CHAINS;
    const startEpoch = epochRef.current;
    setScanning(true);
    // A restricted (single-chain) re-scan must not blank the sibling
    // chain's already-displayed result while it runs - only a full scan
    // clears the slate immediately like this.
    if (!restricted) {
      setScanResult(null);
    }
    setScanConfirm(null);

    const outcomes = [];
    let anySucceeded = false;
    for (const chain of chainsToScan) {
      const allowFullClose = permittedFullClose.has(chain.slug);
      const path = `/api/maxfi/scan/${chain.slug}/${wallet}`
        + (allowFullClose ? '?allow_full_close=true' : '');
      const resp = await mxScanFetch(path);
      if (resp === null) {
        // 401 - the page is already navigating to /login. Abort the whole
        // run rather than continue to the next chain.
        return;
      }
      if (resp.ok) {
        anySucceeded = true;
        const flagged = resp.body.ambiguous_flagged;
        const ambiguousList = Array.isArray(flagged) ? flagged : [];
        outcomes.push({
          chain: chain, ok: true, written: resp.body.written,
          ambiguousCount: ambiguousList.length, ambiguous: ambiguousList,
        });
      } else if (resp.body && resp.body.error === 'FullCloseRefused') {
        outcomes.push({
          chain: chain, ok: false, needsConfirm: true,
          openCount: resp.body.open_count,
        });
      } else {
        outcomes.push({
          chain: chain, ok: false,
          error: (resp.body && resp.body.error) || String(resp.status),
          detail: (resp.body && resp.body.detail) || '',
        });
      }
    }

    if (epochRef.current !== startEpoch) {
      // The user switched wallets mid-scan. The scans already committed
      // server-side for the wallet they were run against - that's correct
      // and harmless - but painting their outcome over the NEW wallet's
      // screen would not be. Write no state at all.
      return;
    }

    setScanning(false);
    // Merge by chain slug rather than overwrite outright: a full scan's
    // outcomes already cover every slug, so this replaces everything as
    // before; a restricted re-scan's outcome (Set of one) only overwrites
    // that one chain's entry, leaving the sibling chain's earlier result
    // in place rather than silently dropping it. Always rendered back out
    // in MX_CHAINS order regardless of which chain was merged in last.
    setScanResult((prev) => {
      const bySlug = {};
      (prev || []).forEach((o) => { bySlug[o.chain.slug] = o; });
      outcomes.forEach((o) => { bySlug[o.chain.slug] = o; });
      return MX_CHAINS.filter((c) => bySlug[c.slug]).map((c) => bySlug[c.slug]);
    });
    // Only the chains actually scanned this run overwrite their slug's
    // entry - a chain that errored (no ambiguous_flagged at all) keeps
    // whatever was last known rather than being cleared on no information.
    // A chain that succeeded with an EMPTY array still overwrites with []
    // deliberately, clearing stale entries rather than leaving them.
    setAmbiguousByChain((prev) => {
      const next = Object.assign({}, prev);
      outcomes.forEach((o) => { if (o.ok) next[o.chain.slug] = o.ambiguous; });
      return next;
    });
    const needingConfirm = outcomes.filter((o) => o.needsConfirm);
    if (needingConfirm.length > 0) {
      // Only the first prompt is surfaced as an active confirm - the rest
      // stay visible in scanResult's per-chain lines. Never stack prompts.
      const first = needingConfirm[0];
      setScanConfirm({ slug: first.chain.slug, label: first.chain.label, openCount: first.openCount });
    }

    // Positions only, never valuation, and never epochRef - reuse the
    // existing phase runner rather than duplicating its logic.
    if (anySucceeded) {
      runPositionsPhase(wallet);
    }
  }

  function confirmFullClose() {
    if (!scanConfirm || !selectedWallet) return;
    // Restricted to the affected chain alone in BOTH the permitted-full-
    // close set and the chains-to-scan set, so confirming Base re-scans
    // Base only - Robinhood's already-completed result is left untouched.
    const slug = scanConfirm.slug;
    runScan(selectedWallet, new Set([slug]), new Set([slug]));
  }

  function cancelFullClose() {
    setScanConfirm(null);
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
    // ambiguousByChain entries are per-wallet facts from a prior scan of
    // THIS wallet - they say nothing about the newly selected one.
    setAmbiguousByChain({});
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
        // Hoisted onto the row rather than read through row.position at each
        // site - untracked rows (below) have position: null, so hoisting
        // means every reader gets a plain value/null without its own guard.
        assetClass: p.asset_class, userNote: p.user_note, closingValueUsd: p.closing_value_usd,
        claimedUsd: p.claimed_usd, claimsUnavailable: p.claims_unavailable,
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
          // No DB row exists for an untracked entry, so none of the three
          // exist either - always null, never read through row.position.
          assetClass: null, userNote: null, closingValueUsd: null,
          // No DB row means no claims are possible - null (not 0.0) says
          // "not applicable", and claimsUnavailable is false because
          // nothing was attempted for a row with nothing to look up.
          claimedUsd: null, claimsUnavailable: false,
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

  // Closed positions - built entirely separately from `rows` above. No
  // valuation join of any kind: a closed position is positions-only data by
  // definition (it is not held on-chain any more, so there is nothing live
  // to price), so this never touches valState/valByKey/mxIdentityKey.
  const closedRows = [];
  MX_CHAINS.forEach((chain) => {
    const posState = positions[chain.slug];
    const dbList = (posState.data || []).filter((p) => p.status === 'closed');
    dbList.forEach((p) => {
      closedRows.push({
        chain, position: p, dbId: p.id, poolAddress: p.pool_address,
        closedAt: p.closed_at, closedBy: p.closed_by,
        initialValueUsd: p.initial_value_usd, closingValueUsd: p.closing_value_usd,
        firstSeenAtSource: p.first_seen_at_source,
        claimedUsd: p.claimed_usd, claimsUnavailable: p.claims_unavailable,
        // MaxFiNotesEditor reads row.userNote directly (its initial textarea
        // value) - without this, expanding a closed row would open the notes
        // box blank and a save would silently wipe an existing note.
        userNote: p.user_note,
      });
    });
  });
  // Most recent close first, across all chains together (the Chain column
  // already carries that information, so grouping by chain first would only
  // separate what closed_at DESC already orders correctly). A null closed_at
  // sorts last rather than first/throwing - defensive only, every close path
  // writes closed_at unconditionally.
  closedRows.sort((a, b) => {
    if (!a.closedAt && !b.closedAt) return 0;
    if (!a.closedAt) return 1;
    if (!b.closedAt) return -1;
    return new Date(b.closedAt).getTime() - new Date(a.closedAt).getTime();
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

  // claimsUnavailable beats hideValues beats zero, matching valueCell's own
  // precedence (its vState.error/missing-data unavailable checks are also
  // resolved before hideValues is ever consulted). Zero is deliberately
  // dashed here even though neither valueCell nor pnlCell dashes a zero -
  // the backend returns 0.0 (never null) for "no claims recorded", so
  // mxFmtOrDash (null/undefined only) would render '$0.00' on every row
  // with no claims, which is noise across dozens of rows.
  function claimedCell(row) {
    if (row.claimsUnavailable) return { text: 'unavailable', color: MX_C.warn };
    if (hideValues) return { text: '••••', color: MX_C.primary };
    const v = row.claimedUsd;
    if (v === null || v === undefined || v === 0) return { text: '—', color: MX_C.secondary };
    return { text: fmt(v), color: MX_C.primary };
  }

  // ── Per-wallet summary totals (Phase D.3.5) ───────────────────────────────
  // Two data rows - UNREALISED (from `rows`, open positions) and REALISED
  // (from `closedRows`) - sharing one set of columns so the two groups
  // compare by reading straight down a column. Honesty is the whole point: a
  // total that silently omits a row is worse than no total, so every sum
  // tracks its own completeness signal (a *Partial boolean for a
  // still-loading/errored chain, an *Excluded count for a row with a
  // genuinely missing figure) instead of just adding whatever happens to be
  // present.

  // Shared by every plain BASIS/CLAIMED/VALUE/PNL sum below: adds each
  // finite value, counts everything else (null, undefined, NaN, a
  // non-number) as excluded rather than silently treating it as zero - not
  // used by UNREALISED/VALUE or UNREALISED/PNL, which need a per-CHAIN
  // loading signal folded in alongside the per-row one and stay as their
  // own explicit loops below.
  function mxSumFinite(items, getValue) {
    let sum = 0;
    let excluded = 0;
    items.forEach((item) => {
      const v = getValue(item);
      if (typeof v === 'number' && isFinite(v)) sum += v;
      else excluded += 1;
    });
    return { sum, excluded };
  }

  // UNREALISED / COUNT - provisional before valuation loads: UNTRACKED rows
  // are only synthesized once a chain's valuation succeeds, so both
  // rows.length and the state split are incomplete until every chain has
  // reported.
  const unrealisedCountPartial = MX_CHAINS.some((c) => {
    const vState = valuation[c.slug];
    return vState.loading || !vState.data || vState.error;
  });

  // UNREALISED / BASIS - UNTRACKED rows have position: null and contribute
  // nothing; a row with a position but no recorded initial_value_usd is
  // excluded the same way.
  const unrealisedBasis = mxSumFinite(rows, (row) => row.position ? row.position.initial_value_usd : null);

  // UNREALISED / VALUE - repurposed in place from the old LP PORTFOLIO VALUE
  // computation rather than duplicated: this IS that same sum (the removed
  // rendering block below used to read it as `total`/`partial`). Answers
  // "what is my LP capital worth right now" - a chain question - so it sums
  // matched + untracked (everything the chain currently reports as held)
  // and excludes stale (confirmed no longer held, contributes nothing).
  // Partial whenever any row's value is still loading, unavailable, or a
  // chain errored - an incomplete number is never presented as complete.
  let unrealisedValueTotal = 0;
  let unrealisedValuePartial = false;
  rows.forEach((row) => {
    const vState = valuation[row.chain.slug];
    if (vState.loading || !vState.data || vState.error) { unrealisedValuePartial = true; return; }
    if (row.state === 'stale') return;
    const cv = row.valuation ? row.valuation.current_value_usd : null;
    if (cv === null || cv === undefined) { unrealisedValuePartial = true; return; }
    unrealisedValueTotal += cv;
  });

  // UNREALISED / CLAIMED - claimsUnavailable is a per-chain lookup failure,
  // not a per-row exclusion, so it gets its own flag rather than folding
  // into an excluded count; a claims-less row's null claimedUsd simply isn't
  // added (mxSumFinite's own excluded count is unused here - nothing renders
  // it, since claimsPartial is the completeness signal this column shows).
  let unrealisedClaimsPartial = false;
  rows.forEach((row) => { if (row.claimsUnavailable) unrealisedClaimsPartial = true; });
  const unrealisedClaimed = mxSumFinite(rows, (row) => row.claimedUsd);

  // UNREALISED / P/L - skips stale (no value to derive a P/L from), flips
  // partial on the same per-chain triple-check VALUE uses above, and simply
  // never adds a non-stale row whose pnl_usd is null/undefined - that is the
  // server suppressing P/L for a missing basis (see compute_performance),
  // and it is the single most likely reason this total would read low.
  let unrealisedPnlTotal = 0;
  let unrealisedPnlPartial = false;
  rows.forEach((row) => {
    if (row.state === 'stale') return;
    const vState = valuation[row.chain.slug];
    if (vState.loading || !vState.data || vState.error) { unrealisedPnlPartial = true; return; }
    const perf = row.valuation ? row.valuation.performance : null;
    const pnl = perf ? perf.pnl_usd : null;
    if (typeof pnl === 'number' && isFinite(pnl)) unrealisedPnlTotal += pnl;
  });

  // REALISED (closedRows) - never partial: a closed row needs no live
  // valuation, so every figure here is either a real sum or an excluded
  // count, never a "still loading" state.
  const realisedBasis = mxSumFinite(closedRows, (row) => row.initialValueUsd);
  const realisedValue = mxSumFinite(closedRows, (row) => row.closingValueUsd);
  let realisedClaimsPartial = false;
  closedRows.forEach((row) => { if (row.claimsUnavailable) realisedClaimsPartial = true; });
  const realisedClaimed = mxSumFinite(closedRows, (row) => row.claimedUsd);
  // The EXACT closed-row expression the table's own P/L and ROI cells use
  // (same guard, same formula) - never a second, independently-computed
  // figure. On current production data most closed rows have no closing
  // value recorded, so this exclusion count will be large and non-zero -
  // that reflects real missing data, not a bug here.
  const realisedPnl = mxSumFinite(closedRows, (row) =>
    (typeof row.closingValueUsd === 'number' && isFinite(row.closingValueUsd)
      && typeof row.initialValueUsd === 'number' && isFinite(row.initialValueUsd))
      ? row.closingValueUsd - row.initialValueUsd + (row.claimedUsd || 0) : null);

  const anyBusy = MX_CHAINS.some((c) => positions[c.slug].loading || valuation[c.slug].loading);

  const th = (txt) => React.createElement('th', {
    style: { textAlign: 'left', padding: '5px 9px', fontSize: 12,
      color: MX_C.secondary, fontWeight: 700, borderBottom: '2px solid ' + MX_C.border,
      whiteSpace: 'nowrap' } }, txt);
  // title is optional and undefined for every pre-existing call site - React
  // omits the attribute entirely when a prop is undefined, so this is a
  // purely additive extension with no behaviour change for any cell that
  // doesn't pass one.
  const td = (children, extra, title) => React.createElement('td', {
    title: title,
    style: Object.assign({ padding: '6px 9px', fontSize: 12, color: MX_C.primary,
      borderBottom: '2px solid ' + MX_C.sep, verticalAlign: 'top' }, extra || {}) }, children);

  // The ONE column-count constant - Chain, Class, Pool, Opened, Basis,
  // Value, Claimed, P/L, Actions. Used only by the notes-panel colSpan
  // below; the header and body cells stay individually written out, not
  // driven from this number.
  const MX_COLUMN_COUNT = 9;
  // The closed table's OWN column count - Chain, Pool, Opened, Closed,
  // Basis, Closing Value, Claimed, P/L, ROI. A separate constant, not a
  // reuse of MX_COLUMN_COUNT: the two tables have different columns
  // (Class/Actions vs Closed/ROI) and happen to both total 9 only by
  // coincidence - sharing one constant would silently desync the moment
  // either table's column count changes independently of the other.
  const MX_CLOSED_COLUMN_COUNT = 9;

  const header = React.createElement('div', {
    onClick: () => setOpen((o) => !o),
    style: { display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer',
      color: MX_C.primary, fontSize: 13, fontWeight: 700, letterSpacing: '0.06em' } },
    React.createElement('span', { style: { color: MX_C.secondary, fontSize: 12 } }, open ? '▾' : '▸'),
    'MAXFI LP POSITIONS',
    React.createElement('span', {
      style: { color: MX_C.secondary, fontSize: 12, fontWeight: 400, letterSpacing: 0 } },
      'Positions as of ' + fmtMxTime(mostRecentScan())),
    React.createElement('select', {
      value: selectedWallet || '',
      disabled: anyBusy || scanning || wallets.length === 0,
      onClick: (ev) => ev.stopPropagation(),
      onChange: (ev) => { ev.stopPropagation(); selectWallet(ev.target.value); },
      style: { marginLeft: 'auto', background: '#1a1a3a', border: '1px solid ' + MX_C.border,
        color: MX_C.primary, padding: '4px 8px', borderRadius: 5, fontSize: 12, fontWeight: 600 } },
      wallets.length === 0
        ? React.createElement('option', { value: '' }, '—')
        : wallets.map((w) => React.createElement('option', { key: w.address, value: w.address },
            (w.label ? w.label + ' — ' : '') + mxTruncateAddr(w.address)))),
    // title sits on a wrapping span, not the button itself: a disabled
    // element suppresses mouse events, so a native title on the button
    // would not reliably show while a scan is in flight - exactly when the
    // label most needs explaining. inline-flex with no padding/margin so
    // the span is a transparent wrapper that doesn't add a visual gap or
    // change the header's existing flex layout.
    React.createElement('span', {
      title: 'Re-reads saved positions and re-prices them live. Does not check the chain for '
        + 'new or exited pools. Slow — about 2-3 minutes per chain.',
      style: { display: 'inline-flex' },
    },
      React.createElement('button', {
        onClick: (ev) => { ev.stopPropagation(); if (selectedWallet) refreshAll(selectedWallet); },
        disabled: anyBusy || scanning || !selectedWallet,
        style: { background: '#1a1a3a', border: '1px solid ' + MX_C.border,
          color: MX_C.primary, padding: '4px 12px', borderRadius: 5, fontSize: 12, fontWeight: 600,
          cursor: (anyBusy || scanning || !selectedWallet) ? 'default' : 'pointer',
          opacity: (anyBusy || scanning || !selectedWallet) ? 0.6 : 1 } },
        anyBusy ? 'Loading…' : 'Refresh')),
    React.createElement('span', {
      title: 'Checks the chain for new and exited pools and updates saved positions. Does not '
        + 'update prices. Fast.',
      style: { display: 'inline-flex' },
    },
      React.createElement('button', {
        onClick: (ev) => { ev.stopPropagation(); if (selectedWallet) runScan(selectedWallet, new Set()); },
        disabled: scanning || anyBusy || !selectedWallet,
        style: { background: '#1a1a3a', border: '1px solid ' + MX_C.border,
          color: MX_C.primary, padding: '4px 12px', borderRadius: 5, fontSize: 12, fontWeight: 600,
          cursor: (scanning || anyBusy || !selectedWallet) ? 'default' : 'pointer',
          opacity: (scanning || anyBusy || !selectedWallet) ? 0.6 : 1 } },
        scanning ? 'Scanning…' : 'Scan')));

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

  const mxTabularNums = { fontVariantNumeric: 'tabular-nums' };

  function toggleExpanded(key) {
    setExpandedRowKeys((prev) => {
      const next = Object.assign({}, prev);
      if (next[key]) delete next[key]; else next[key] = true;
      return next;
    });
  }

  // A flat array built by push, not .map() - an expanded row needs to
  // contribute a SECOND <tr> immediately after its own, which .map()'s
  // one-element-per-iteration shape can't express.
  const tableRows = [];
  rows.forEach((row, i) => {
    const p = row.position;   // null for an untracked row - no DB row exists
    const vcell = valueCell(row);
    const ccell = claimedCell(row);
    const pcell = pnlCell(row);
    const onWritten = () => loadPositionsFor(row.chain, selectedWallet, epochRef.current);
    const rowKey = selectedWallet + '-' + row.chain.slug + '-' + row.arrayIndex + '-' + row.poolAddress;
    // Hover wins outright over banding - it's a flat, stronger colour
    // regardless of which band (i%2) the row started on, so a hovered row
    // is unambiguous either way.
    const rowBg = hoveredRowKey === rowKey ? MX_C.hover : (i % 2 ? MX_C.zebra : 'transparent');

    // Matched on token_id ONLY (never array_index or pool_address): both
    // rows of an ambiguous pair share the same array_index by definition,
    // and pool_address casing between the scan snapshot and the valuation
    // snapshot is unverified. Both sides of an entry are checked, since
    // either a stale row (the position exited) or an untracked row (what
    // it became) can be the one currently rendering.
    const chainAmbiguous = ambiguousByChain[row.chain.slug] || [];
    const ambiguousMatch = chainAmbiguous.find((entry) => {
      const cur = entry.current, prev = entry.previous;
      return (cur && String(cur.token_id) === String(row.tokenId))
        || (prev && String(prev.token_id) === String(row.tokenId));
    });

    // UNTRACKED rows have dbId === null - no DB row exists to expand a
    // notes editor onto, so they get no dot and the row does not expand.
    const canExpand = row.dbId !== null;
    const isExpanded = canExpand && !!expandedRowKeys[rowKey];
    const hasNote = row.userNote !== null && row.userNote !== undefined && row.userNote !== '';

    tableRows.push(React.createElement('tr', {
      key: rowKey,
      onMouseEnter: () => setHoveredRowKey(rowKey),
      onMouseLeave: () => setHoveredRowKey(null),
      onClick: () => {
        if (!canExpand) return;
        // Don't collapse/expand the row out from under a drag-select of a
        // cell's text - only toggle on a genuine click, never on the
        // mouseup that ends a selection.
        const sel = window.getSelection();
        if (sel && String(sel).length > 0) return;
        toggleExpanded(rowKey);
      },
      style: { background: rowBg, cursor: canExpand ? 'pointer' : undefined } },
      td(row.chain.label),
      td(mxAssetClassLetter(row.assetClass), null, row.assetClass || undefined),
      td(React.createElement(MaxFiPoolCell, {
        row, ambiguousReason: ambiguousMatch ? ambiguousMatch.reason : null,
        hasNote, canExpand,
      })),
      td(React.createElement('span', null,
        mxOpenDate(p),
        row.firstSeenAtSource === 'ambiguity_auto_split_inherited' ? mxInheritedDateBadge() : null)),
      td(React.createElement(MaxFiBasisCell, { row, hideValues, onWritten }), mxTabularNums),
      td(vcell.text, Object.assign({ color: vcell.color }, mxTabularNums)),
      td(ccell.text, Object.assign({ color: ccell.color }, mxTabularNums)),
      td(pcell.text, Object.assign({ color: pcell.color }, mxTabularNums)),
      td(React.createElement(MaxFiCloseButton, { row, onWritten }))));

    if (isExpanded) {
      tableRows.push(React.createElement('tr', { key: rowKey + '-notes' },
        React.createElement('td', {
          colSpan: MX_COLUMN_COUNT,
          style: { padding: '8px 9px', borderBottom: '2px solid ' + MX_C.sep, background: MX_C.panel },
        }, React.createElement(MaxFiExpandedPanel, { row, onWritten, hideValues }))));
    }
  });

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
  // All four counters render always, including zeros, so the reader can add
  // them up themselves - no "already up to date" special case for the
  // all-zero result. Guards a missing/malformed `written` to 0 per field
  // rather than printing undefined.
  function mxScanOutcomeLine(o) {
    if (o.ok) {
      const w = o.written || {};
      const n = (x) => (typeof x === 'number' ? x : 0);
      return `${o.chain.label}: ${n(w.opened)} opened, ${n(w.closed)} closed, `
        + `${n(w.rebalanced)} rebalanced, ${n(w.matched)} matched`;
    }
    if (o.needsConfirm) {
      return `${o.chain.label}: needs confirmation - see below`;
    }
    return `${o.chain.label}: ${o.error}` + (o.detail ? ' - ' + o.detail : '');
  }

  // Dismissible; also naturally superseded the moment a new scan starts
  // (runScan clears it at entry) - not wired to Refresh as a second,
  // separate clearing path.
  let scanResultBlock = null;
  if (scanResult) {
    const anyPositionsChanged = scanResult.some((o) =>
      o.ok && o.written && (o.written.opened > 0 || o.written.closed > 0));
    scanResultBlock = React.createElement('div', {
      style: { marginBottom: 8, display: 'flex', flexDirection: 'column', gap: 2 } },
      scanResult.map((o) => {
        // ambiguous_flagged's LENGTH only - never its contents (reason
        // strings/token ids/pool addresses belong to the legend, a later
        // task) - rendered as its own warn-coloured, bold fragment so it
        // stands out from the reconciling counters beside it.
        const ambiguousCount = o.ok ? (o.ambiguousCount || 0) : 0;
        return React.createElement('div', {
          key: 'scan-' + o.chain.slug,
          style: { color: o.ok ? MX_C.secondary : MX_C.warn, fontSize: 12, fontWeight: o.ok ? 400 : 600 },
        },
          mxScanOutcomeLine(o),
          ambiguousCount > 0 ? React.createElement('span', {
            style: { color: MX_C.warn, fontWeight: 700 },
          }, ', ' + ambiguousCount + (ambiguousCount === 1 ? ' needs review' : ' need review')) : null);
      }),
      anyPositionsChanged ? React.createElement('div', {
        style: { color: MX_C.warn, fontSize: 12, fontWeight: 600 },
      }, 'Valuation is stale — Refresh to reprice.') : null,
      React.createElement('span', {
        onClick: () => setScanResult(null),
        style: { color: MX_C.secondary, fontSize: 11, fontWeight: 700, cursor: 'pointer',
          textDecoration: 'underline', alignSelf: 'flex-start' },
      }, 'Dismiss'));
  }

  // Inline confirm, same shape as MaxFiCloseButton's - a message line, then
  // a Confirm/Cancel button pair via mxSmallBtnStyle. Confirm is destructive:
  // its own distinct label text ("Yes, close all N") plus a warn-coloured
  // border/text carry the distinction, not colour alone.
  let scanConfirmBlock = null;
  if (scanConfirm) {
    scanConfirmBlock = React.createElement('div', {
      style: { display: 'inline-flex', flexDirection: 'column', gap: 4, marginBottom: 8 } },
      React.createElement('span', { style: { color: MX_C.warn, fontSize: 12, fontWeight: 600 } },
        `Scanning ${scanConfirm.label} found zero live positions but ${scanConfirm.openCount} rows are open. `
        + 'Closing all of them cannot be undone.'),
      React.createElement('span', { style: { display: 'inline-flex', gap: 6 } },
        React.createElement('button', {
          onClick: confirmFullClose, disabled: scanning,
          style: Object.assign({}, mxSmallBtnStyle(scanning),
            { border: '1px solid ' + MX_C.warn, color: MX_C.warn, fontWeight: 700 }),
        }, scanning ? '…' : `Yes, close all ${scanConfirm.openCount}`),
        React.createElement('button', {
          onClick: cancelFullClose, disabled: scanning, style: mxSmallBtnStyle(scanning),
        }, 'Cancel')));
  }

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

  // Summary grid (Phase D.3.5) - 6 columns: a row label, then
  // COUNT/BASIS/VALUE/CLAIMED/P/L. Built the same way legendBlock/closedBlock
  // are: one flat CSS-grid container with 18 direct child cells (6 heading +
  // 6 UNREALISED + 6 REALISED) - CSS Grid auto-places children into rows from
  // the column template alone, so no per-row wrapper element is needed.
  const summaryHeadCell = (text) => React.createElement('div', {
    style: { padding: '5px 9px', background: MX_C.head, borderBottom: '2px solid ' + MX_C.sep,
      fontSize: 11, color: MX_C.secondary, fontWeight: 700, letterSpacing: '0.04em' } }, text);
  const summaryHeadNumCell = (text) => React.createElement('div', {
    style: { padding: '5px 9px', background: MX_C.head, borderBottom: '2px solid ' + MX_C.sep,
      fontSize: 11, color: MX_C.secondary, fontWeight: 700, letterSpacing: '0.04em', textAlign: 'right' } }, text);
  const summaryLabelCell = (text, extra) => React.createElement('div', {
    style: Object.assign({ padding: '5px 9px', fontSize: 12, color: MX_C.secondary,
      fontWeight: 700, letterSpacing: '0.04em' }, extra || {}) }, text);
  const summaryDataCell = (text, color, extra) => React.createElement('div', {
    style: Object.assign({ padding: '5px 9px', fontSize: 13, color: color || MX_C.primary,
      textAlign: 'right' }, mxTabularNums, extra || {}) }, text);

  const unrealisedRowExtra = { borderBottom: '2px solid ' + MX_C.sep };
  const realisedRowExtra = { background: MX_C.zebra };

  // claimsUnavailable beats hideValues beats zero - same precedence
  // claimedCell itself documents and uses, mirrored here so the summary
  // agrees with the per-row cells it is totalling.
  const unrealisedValueText = unrealisedValuePartial ? '…' : (hideValues ? '••••' : fmt(unrealisedValueTotal));
  const unrealisedValueColor = unrealisedValuePartial ? MX_C.secondary : MX_C.primary;
  const unrealisedBasisText = hideValues ? '••••' : fmt(unrealisedBasis.sum);
  const unrealisedClaimedText = unrealisedClaimsPartial ? 'unavailable'
    : (hideValues ? '••••' : (unrealisedClaimed.sum === 0 ? '—' : fmt(unrealisedClaimed.sum)));
  const unrealisedClaimedColor = unrealisedClaimsPartial ? MX_C.warn
    : (!hideValues && unrealisedClaimed.sum === 0 ? MX_C.secondary : MX_C.primary);
  const unrealisedPnlText = unrealisedPnlPartial ? '…'
    : (hideValues ? '••••' : (unrealisedPnlTotal >= 0 ? '+' : '') + fmt(unrealisedPnlTotal));
  const unrealisedPnlColor = unrealisedPnlPartial ? MX_C.secondary
    : (unrealisedPnlTotal >= 0 ? MX_C.accent : MX_C.warn);

  const realisedBasisText = hideValues ? '••••' : fmt(realisedBasis.sum);
  const realisedValueText = hideValues ? '••••' : fmt(realisedValue.sum);
  const realisedClaimedText = realisedClaimsPartial ? 'unavailable'
    : (hideValues ? '••••' : (realisedClaimed.sum === 0 ? '—' : fmt(realisedClaimed.sum)));
  const realisedClaimedColor = realisedClaimsPartial ? MX_C.warn
    : (!hideValues && realisedClaimed.sum === 0 ? MX_C.secondary : MX_C.primary);
  const realisedPnlText = hideValues ? '••••' : (realisedPnl.sum >= 0 ? '+' : '') + fmt(realisedPnl.sum);
  const realisedPnlColor = realisedPnl.sum >= 0 ? MX_C.accent : MX_C.warn;

  const summaryBlock = React.createElement('div', {
    style: { display: 'grid', gridTemplateColumns: 'minmax(0,132px) repeat(5, minmax(0,1fr))',
      border: '1px solid ' + MX_C.border, borderRadius: 6, overflow: 'hidden',
      background: MX_C.bg, marginBottom: 12 } },
    summaryHeadCell(''), summaryHeadNumCell('COUNT'), summaryHeadNumCell('BASIS'),
    summaryHeadNumCell('VALUE'), summaryHeadNumCell('CLAIMED'), summaryHeadNumCell('P/L'),

    summaryLabelCell('UNREALISED', unrealisedRowExtra),
    // Count is never masked by hideValues (not monetary) and, unlike every
    // other cell here, keeps rendering the real number under partial - it
    // gets its own ' (partial)' suffix rather than becoming '…' outright.
    React.createElement('div', {
      style: Object.assign({ padding: '5px 9px', fontSize: 13, color: MX_C.primary, textAlign: 'right' },
        mxTabularNums, unrealisedRowExtra) },
      String(rows.length),
      unrealisedCountPartial ? React.createElement('span', {
        style: { color: MX_C.secondary, fontSize: 11 } }, ' (partial)') : null),
    summaryDataCell(unrealisedBasisText, MX_C.primary, unrealisedRowExtra),
    summaryDataCell(unrealisedValueText, unrealisedValueColor, unrealisedRowExtra),
    summaryDataCell(unrealisedClaimedText, unrealisedClaimedColor, unrealisedRowExtra),
    summaryDataCell(unrealisedPnlText, unrealisedPnlColor, unrealisedRowExtra),

    summaryLabelCell('REALISED', realisedRowExtra),
    summaryDataCell(String(closedRows.length), MX_C.primary, realisedRowExtra),
    summaryDataCell(realisedBasisText, MX_C.primary, realisedRowExtra),
    summaryDataCell(realisedValueText, MX_C.primary, realisedRowExtra),
    summaryDataCell(realisedClaimedText, realisedClaimedColor, realisedRowExtra),
    summaryDataCell(realisedPnlText, realisedPnlColor, realisedRowExtra));

  // Exclusion line - one sentence per group, rendered ONLY when that
  // group's count is non-zero; nothing at all when both are zero, per this
  // block's own "never render an empty element" rule.
  const summaryExclusionParts = [];
  if (unrealisedBasis.excluded > 0) {
    summaryExclusionParts.push('Unrealised excludes ' + unrealisedBasis.excluded
      + ' row' + (unrealisedBasis.excluded === 1 ? '' : 's') + ' with no basis recorded.');
  }
  if (realisedValue.excluded > 0) {
    summaryExclusionParts.push('Realised excludes ' + realisedValue.excluded
      + ' row' + (realisedValue.excluded === 1 ? '' : 's') + ' with no closing value recorded.');
  }
  const summaryExclusionLine = summaryExclusionParts.length === 0 ? null
    : React.createElement('div', { style: { fontSize: 11, color: MX_C.secondary, marginBottom: 12 } },
        summaryExclusionParts.join(' '));

  // Collapsed by default - a legend below 25+ rows is one nobody scrolls
  // to. Placed directly above the table itself (not above the scan/
  // valuation status lines) so opening it doesn't push those out of view.
  const legendBlock = React.createElement('div', { style: { marginBottom: legendOpen ? 8 : 12 } },
    React.createElement('div', {
      onClick: () => setLegendOpen((o) => !o),
      style: { display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer',
        color: MX_C.secondary, fontSize: 12, fontWeight: 700 } },
      React.createElement('span', { style: { fontSize: 11 } }, legendOpen ? '▾' : '▸'),
      'WHAT THE BADGES MEAN'),
    legendOpen ? React.createElement('div', {
      style: { marginTop: 8, padding: '10px 12px', border: '1px solid ' + MX_C.border,
        borderRadius: 6, background: MX_C.panel } },
      React.createElement(MaxFiLegend, { entries: MX_LEGEND })) : null);

  // Closed positions - a SEPARATE table, not a second tbody on the open
  // table above. Still no live valuation join of any kind (closed rows are
  // never priced live), but it DOES click-to-expand now - a fee claim can be
  // recorded and sold well after a position closes, so the claims + notes
  // panel is reachable here exactly like the open table. A flat array built
  // by forEach + push, not .map() - same reason as the open table's own
  // tableRows above: an expanded row needs to contribute a SECOND <tr>
  // immediately after its own, which .map()'s one-element-per-iteration
  // shape can't express.
  const closedRowElements = [];
  (closedShowAll ? closedRows : closedRows.slice(0, 25)).forEach((row, i) => {
    const pairLabel = mxPairLabel(row.position);
    const pnl = (typeof row.closingValueUsd === 'number' && isFinite(row.closingValueUsd)
      && typeof row.initialValueUsd === 'number' && isFinite(row.initialValueUsd))
      ? row.closingValueUsd - row.initialValueUsd + (row.claimedUsd || 0) : null;
    const roi = (pnl !== null) ? mxRoiLabel(pnl, row.initialValueUsd) : null;
    const roiColor = (pnl === null || roi === null) ? MX_C.secondary : (pnl >= 0 ? MX_C.accent : MX_C.warn);
    // Same pnl feeds both the new dollar P/L cell and the existing ROI cell
    // below - never a second, independently-computed figure.
    const pnlText = pnl === null ? '—' : (hideValues ? '••••' : ((pnl >= 0 ? '+' : '') + fmt(pnl)));
    const pnlColor = pnl === null ? MX_C.secondary : (pnl >= 0 ? MX_C.accent : MX_C.warn);
    // claimedCell is defined above in this same MaxFiScreen closure (it
    // closes over hideValues from this function's own scope, not anything
    // open-table-specific), so it is directly reusable here - closed rows
    // already carry the same hoisted claimedUsd/claimsUnavailable fields.
    const ccell = claimedCell(row);
    const onWritten = () => loadPositionsFor(row.chain, selectedWallet, epochRef.current);
    const rowKey = selectedWallet + '-closed-' + row.chain.slug + '-' + row.dbId;
    // Every closed row comes from a real DB row (dbList is a status==='closed'
    // filter over posState.data), so dbId is always present - no canExpand
    // guard is needed the way the open table needs one for UNTRACKED rows.
    const isClosedExpanded = !!expandedRowKeys[rowKey];
    // Hover wins outright over banding, matching the open row's own
    // precedence exactly - hoveredRowKey is shared state; the two tables'
    // rowKey formats are structurally distinct (this one always contains the
    // literal '-closed-' segment, which no chain.slug value can produce), so
    // there is no collision between an open row and a closed row hovering or
    // expanding at once.
    const rowBg = hoveredRowKey === rowKey ? MX_C.hover : (i % 2 ? MX_C.zebra : 'transparent');

    closedRowElements.push(React.createElement('tr', {
      key: rowKey,
      onMouseEnter: () => setHoveredRowKey(rowKey),
      onMouseLeave: () => setHoveredRowKey(null),
      onClick: () => {
        // Same drag-select guard as the open row's onClick - don't collapse/
        // expand the row out from under a text selection.
        const sel = window.getSelection();
        if (sel && String(sel).length > 0) return;
        toggleExpanded(rowKey);
      },
      style: { background: rowBg, cursor: 'pointer' } },
      td(row.chain.label),
      td(pairLabel
        ? React.createElement('span', null, pairLabel)
        : React.createElement('span', null,
            mxTruncateAddr(row.poolAddress), ' ',
            React.createElement('span', {
              style: { fontSize: 11, color: MX_C.secondary, fontWeight: 700 },
            }, '(unresolved)'))),
      td(mxOpenDate(row.position)),
      td(mxClosedDate(row.closedAt)),
      td(mxFmtOrDash(row.initialValueUsd), mxTabularNums),
      td(React.createElement(MaxFiClosingValueCell, {
        dbId: row.dbId, closingValueUsd: row.closingValueUsd, onWritten,
      }), mxTabularNums),
      td(ccell.text, Object.assign({ color: ccell.color }, mxTabularNums)),
      td(pnlText, Object.assign({ color: pnlColor }, mxTabularNums)),
      td(pnl === null ? '—' : (roi || '—'), Object.assign({ color: roiColor }, mxTabularNums))));

    if (isClosedExpanded) {
      closedRowElements.push(React.createElement('tr', { key: rowKey + '-panel' },
        React.createElement('td', {
          colSpan: MX_CLOSED_COLUMN_COUNT,
          style: { padding: '8px 9px', borderBottom: '2px solid ' + MX_C.sep, background: MX_C.panel },
        }, React.createElement(MaxFiExpandedPanel, { row, onWritten, hideValues }))));
    }
  });

  const closedHeaderText = 'CLOSED POSITIONS (' + closedRows.length + ')';
  const closedBlock = closedRows.length === 0
    ? React.createElement('div', {
        style: { marginTop: 16, display: 'inline-flex', alignItems: 'center', gap: 6,
          color: MX_C.secondary, fontSize: 12, fontWeight: 700 } },
        closedHeaderText)
    : React.createElement('div', { style: { marginTop: 16 } },
        React.createElement('div', {
          onClick: () => setClosedOpen((o) => !o),
          style: { display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer',
            color: MX_C.secondary, fontSize: 12, fontWeight: 700 } },
          React.createElement('span', { style: { fontSize: 11 } }, closedOpen ? '▾' : '▸'),
          closedHeaderText),
        closedOpen ? React.createElement('div', { style: { marginTop: 8 } },
          React.createElement('div', {
            style: { border: '1px solid ' + MX_C.border, borderRadius: 6, overflow: 'hidden' } },
            React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse', background: MX_C.bg } },
              React.createElement('thead', { style: { background: MX_C.head } },
                React.createElement('tr', null,
                  th('Chain'), th('Pool'), th('Opened'), th('Closed'), th('Basis'), th('Closing Value'), th('Claimed'), th('P/L'), th('ROI'))),
              React.createElement('tbody', null, closedRowElements))),
          (!closedShowAll && closedRows.length > 25) ? React.createElement('div', {
            onClick: () => setClosedShowAll(true),
            style: { marginTop: 8, fontSize: 12, color: MX_C.accent, cursor: 'pointer' } },
            'Show all ' + closedRows.length + ' closed positions') : null) : null);

  const panelContent = walletBanner ? walletBanner : React.createElement('div', null,
    scanResultBlock,
    scanConfirmBlock,
    valuationControl,
    statusLines,
    legendBlock,
    summaryBlock,
    summaryExclusionLine,
    rows.length === 0 ? React.createElement('div', {
      style: { color: MX_C.secondary, fontSize: 13 } },
      anyBusy ? 'Loading positions…' : 'No open MaxFi positions found.') : React.createElement('div', {
      style: { border: '1px solid ' + MX_C.border, borderRadius: 6, overflow: 'hidden' } },
      React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse', background: MX_C.bg } },
        React.createElement('thead', { style: { background: MX_C.head } },
          React.createElement('tr', null,
            th('Chain'), th('Class'), th('Pool'), th('Opened'), th('Basis'), th('Value'), th('Claimed'), th('P/L'), th('Actions'))),
        React.createElement('tbody', null, tableRows))),
    closedBlock);

  const body = React.createElement('div', {
    style: { background: MX_C.panel, border: '1px solid ' + MX_C.border, borderRadius: 6,
      padding: '12px 16px', marginBottom: 12 } },
    header,
    open ? React.createElement('div', { style: { marginTop: 10 } }, panelContent) : null);

  return React.createElement(MaxFiErrorBoundary, null, body);
}

window.MaxFiScreen = MaxFiScreen;
