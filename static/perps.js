/* ===== PERPS PAGE — Landings 3a and 3b (HANDOFF_spot_perps_rebuild.md 3.2, 3.4, 11) =====
   The Perps menu item (activeTab 'perps', static/app.js). Tabs: Open
   positions · History · Transactions (synced-fills status and manual perp
   trades, which moved here from the retired Trade Log in Landing 3b).

   One read feeds the page: GET /api/trading/trades. Perp trades are built
   from the stored Hyperliquid and TxFlow fills plus manual perp trades from
   the trade log. An open synced trade carries "live" (the venue's view of
   its position: current size, mark, leverage, liquidation, venue stop and
   every take-profit); "untracked_positions" are live venue positions with no
   trade yet (fills not synced, or opened before the sync window); "sync" is
   the fill-sync status per venue. Every number arrives as a string and is
   parsed only for display.

   Writes:
     synced trades: PUT /api/trading/trades/<trade_id>/annotation
     manual trades: POST /api/spot/trade-log (perp only, with leverage; a
                    finished trade in one step), PUT / DELETE /api/spot/trade-log/<id>

   Rulings (section 11): Open risk at stops = entry to the effective stop x
   current size, a stop at or past entry counting 0. Target = the nearest
   take-profit with R = |tp - entry| / |entry - stop|, "+N more" with all of
   them on hover; a take-profit on the losing side of entry, or a stop at or
   past entry, shows the price without an R chip. Hide values masks size,
   money and funding; prices, leverage and R stay visible.

   Rows use the shared stacked-card grid (.spot-grid-row and friends in
   static/style.css), so the page never scrolls sideways: a table at 1250px
   and wider, stacked cards below. Every top-level name here starts with prp /
   PRP / Perps: Babel turns top-level declarations into shared globals. */
const { useState: usePRPState, useEffect: usePRPEffect, useRef: usePRPRef } = React;

const PRP_COLD_RETRY_MS = 15000;     // re-read while open synced trades still lack live data (cold caches)
const PRP_COLD_RETRY_MAX = 4;        // at most this many such re-reads per mount
const PRP_SAVED_MS = 3000;           // how long "Saved" stays
const PRP_NOTE_MAX = 2000;           // TRADE_NOTE_MAX on the server
const PRP_LINE = '2px solid rgba(255,255,255,0.25)';
const PRP_HEAD_LINE = '2px solid rgba(255,255,255,0.35)';
const PRP_MONO = "'Fira Code', monospace";
const PRP_SMALL_BTN = { fontSize: 13, padding: '4px 12px', minHeight: 32 };
// tv-btn has no disabled style of its own: a disabled button is dimmed so it doesn't look clickable.
function prpBtn(disabled, base) {
  return Object.assign({}, base || {}, disabled ? { opacity: 0.5, cursor: 'default' } : {});
}
const PRP_OPEN_GRID = 'minmax(150px,1.3fr) minmax(52px,0.5fr) minmax(48px,0.45fr) minmax(92px,0.8fr) '
  + 'repeat(4,minmax(80px,0.9fr)) minmax(120px,1.2fr) minmax(90px,1fr) minmax(76px,0.8fr) minmax(100px,1fr)';
const PRP_HIST_GRID = 'minmax(150px,1.3fr) minmax(52px,0.5fr) minmax(48px,0.45fr) minmax(120px,1.1fr) '
  + 'minmax(170px,1.5fr) minmax(84px,0.8fr) minmax(90px,0.9fr) minmax(70px,0.7fr) minmax(100px,1fr) minmax(100px,1fr)';
const PRP_TABS = [{ id: 'open', label: 'Open positions' }, { id: 'history', label: 'History' }, { id: 'transactions', label: 'Transactions' }];

const PRP_STOP_SOURCE = {
  manual: 'Entered here',
  hl_order: 'Hyperliquid stop order',
  txflow_order: 'TxFlow stop order',
  txflow_tpsl: 'TxFlow position stop',
  manual_log: 'Logged with the trade',
};

const PRP_GATE_SHORT = {
  open: 'Open', before_rule: 'Before the rule', not_trading_book: 'Tagged holding', needs_review: 'Needs review',
  deviated: 'Deviated', no_stop: 'No stop', stop_after_close: 'Stop set after close', spot: 'Not gated', no_r: 'No R',
};

const PRP_GATE_LONG = {
  open: 'Still open — only closed trades count.',
  before_rule: 'Opened before the gate start, so it does not count.',
  not_trading_book: 'Tagged as a long-term or bot holding.',
  needs_review: 'Mark it followed or deviated to decide whether it counts.',
  deviated: 'Deviated trades are tracked separately and never count.',
  no_stop: 'No stop was recorded for this trade.',
  stop_after_close: 'The stop was recorded after the trade closed.',
  spot: "Spot trades don't count toward the perp risk gate.",
  no_r: 'R could not be calculated (entry equals stop, or a price is missing).',
};

const PRP_FLAGS = {
  funding_approx: 'Funding approximate', funding_missing: 'Funding not recorded', stop_missing: 'No stop order found',
  liquidated: 'Liquidated', flip_split: 'Flipped direction', chain_gap: 'Fill history gap',
};

/* ── display helpers ─────────────────────────────────────────────────── */

function prpNum(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return isFinite(n) ? n : null;
}

function prpUsd(v, hide, signed) {
  if (hide) return '••••';
  const n = prpNum(v);
  if (n === null) return '—';
  const abs = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (abs === '0.00') return '$0.00';
  if (n < 0) return '-$' + abs;
  return (signed ? '+$' : '$') + abs;
}

// A price: sub-cent via fmtPrice; else up to 6 significant digits, and at
// least 2 decimals below $1,000 ("$1.30", not "$1.3").
function prpPx(v) {
  const n = prpNum(v);
  if (n === null) return '—';
  if (n > 0 && n < 0.01) return fmtPrice(n);
  let s = n.toLocaleString('en-US', { maximumSignificantDigits: 6 });
  if (Math.abs(n) < 1000 && (s.split('.')[1] || '').length < 2) {
    s = n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  return '$' + s;
}

function prpSize(v, hide) {
  if (hide) return '••••';
  const n = prpNum(v);
  if (n === null) return '—';
  return n.toLocaleString('en-US', { maximumSignificantDigits: 6 });
}

function prpR(v) {
  const n = prpNum(v);
  if (n === null) return '—';
  return (n > 0 ? '+' : '') + n.toFixed(2) + 'R';
}

function prpDate(v, withTime) {
  if (!v) return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(v));
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(v);
  if (isNaN(d.getTime())) return String(v);
  const opts = { month: 'short', day: 'numeric' };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
  let s = d.toLocaleDateString('en-US', opts);
  if (withTime && !m) s += ', ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  return s;
}

function prpAgo(iso) {
  const ms = Date.parse(iso || '');
  if (isNaN(ms)) return null;
  const min = Math.max(0, Math.round((Date.now() - ms) / 60000));
  if (min < 1) return 'just now';
  if (min < 60) return min + ' min ago';
  const h = Math.round(min / 60);
  if (h < 48) return h + ' h ago';
  return Math.round(h / 24) + ' days ago';
}

function prpColor(v) {
  const n = prpNum(v);
  if (n === null || n === 0) return 'var(--text2)';
  return n > 0 ? 'var(--ok)' : 'var(--fail)';
}

function prpMoneyColor(v, hide) {
  // Hidden amounts stay neutral so the color does not give away gain or loss.
  return hide ? 'var(--text2)' : prpColor(v);
}

function prpErr(e) {
  const text = (e && e.message) || String(e || 'Request failed');
  let out = text;
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed.error === 'string') out = parsed.error;
  } catch (err) { /* not JSON: keep the text */ }
  return out.length > 200 ? out.slice(0, 200) : out;
}

function prpPositive(s) {
  const t = String(s || '').trim();
  if (t === '') return false;
  const n = Number(t);
  return isFinite(n) && n > 0;
}

function prpTextOrNull(s) {
  return String(s || '').trim() === '' ? null : s;
}

function prpNowLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

function prpLocalToIso(value) {
  if (!value) return null;
  const d = new Date(value);
  return isNaN(d.getTime()) ? null : d.toISOString();
}

function prpReadLocal(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch (_e) { return fallback; }
}

function prpWriteLocal(key, v) {
  try { localStorage.setItem(key, v); } catch (_e) { /* the choice still applies until reload */ }
}

function prpVenueLine(t) {
  if (t.source === 'manual') return (!t.venue || t.venue === 'Manual') ? 'Manual entry' : 'Manual · ' + t.venue;
  return (!t.wallet_label || t.wallet_label === t.venue) ? t.venue : t.venue + ' · ' + t.wallet_label;
}

function prpSide(direction) {
  const long = direction === 'long';
  const text = direction ? direction.charAt(0).toUpperCase() + direction.slice(1) : '—';
  return <span style={{ color: long ? 'var(--ok)' : direction === 'short' ? 'var(--fail)' : 'var(--text2)' }}>{text}</span>;
}

// "10x" and its hover text; '—' when unknown (closed synced trades until the trade-open snapshot).
function prpLev(lev, type) {
  const n = prpNum(lev);
  if (n === null) return { text: '—', tip: 'Leverage is recorded for open positions; closed trades get it from the trade-open snapshot (coming).' };
  const text = (Number.isInteger(n) ? String(n) : String(+n.toFixed(2))) + 'x';
  return { text, tip: text + (type ? ' ' + type : '') };
}

// The current size of an open trade: the venue's live size, else the peak (manual trades, cold caches).
function prpOpenSize(t) {
  return t.live && prpNum(t.live.size) !== null ? prpNum(t.live.size) : prpNum(t.size_peak);
}

// 1R = |avg entry - stop| x peak size, the same basis as R at the close; null when it can't be computed.
function prpOneR(t) {
  const entry = prpNum(t.avg_entry);
  const stop = t.stop ? prpNum(t.stop.px) : null;
  const size = prpNum(t.size_peak);
  if (entry === null || stop === null || size === null) return null;
  const r = Math.abs(entry - stop) * size;
  return r > 0 ? r : null;
}

// Planned risk of one open trade (ruling 2): (entry - stop) x current size in
// the losing direction; 0 when the stop is at or past entry; null without a stop or a price.
function prpOpenRisk(t) {
  const entry = prpNum(t.avg_entry);
  const stop = t.stop ? prpNum(t.stop.px) : null;
  const size = prpOpenSize(t);
  if (entry === null || stop === null || size === null) return null;
  const perUnit = (entry - stop) * (t.direction === 'short' ? -1 : 1);
  return Math.max(0, perUnit) * Math.abs(size);
}

// The Target cell's model. tps: take-profit prices nearest first (strings),
// or null when unknown. Returns {nearest, more, r, why}.
function prpTarget(direction, entryV, stopV, tps) {
  if (!Array.isArray(tps)) return null;
  if (!tps.length) return { nearest: null, more: [], r: null, why: 'No take-profit order found' };
  const nearest = tps[0];
  const entry = prpNum(entryV);
  const stop = prpNum(stopV);
  const tp = prpNum(nearest);
  const sign = direction === 'short' ? -1 : 1;
  let r = null, why = null;
  if (stop === null) why = 'R needs a stop';
  else if (entry === null || tp === null) why = 'A price is missing';
  else if ((entry - stop) * sign <= 0) why = 'The stop is at or past entry, so the target has no R';
  else if ((tp - entry) * sign <= 0) why = 'This take-profit is on the losing side of entry, so it has no R';
  else r = Math.abs(tp - entry) / Math.abs(entry - stop);
  return { nearest, more: tps.slice(1), r, why };
}

function PerpsTargetCell({ model, unknownTip }) {
  if (!model) return <span title={unknownTip || "Take-profit orders couldn't be read"} style={{ color: 'var(--text3)' }}>—</span>;
  if (!model.nearest) return <span title={model.why} style={{ color: 'var(--text3)' }}>—</span>;
  const all = [model.nearest].concat(model.more).map(prpPx).join(', ');
  const tip = (model.more.length ? 'Take-profits, nearest first: ' + all : 'Take-profit ' + all)
    + (model.r !== null ? ' · ' + model.r.toFixed(2) + 'R from entry' : model.why ? ' · ' + model.why : '');
  return <div title={tip}>
    <div>
      <span style={{ fontFamily: PRP_MONO }}>{prpPx(model.nearest)}</span>
      {model.r !== null
        ? <span style={{ marginLeft: 6, fontSize: 12, fontWeight: 600, padding: '1px 6px', borderRadius: 999, border: '1px solid rgba(255,255,255,0.45)', color: 'var(--text)', whiteSpace: 'nowrap' }}>{model.r.toFixed(1) + 'R'}</span>
        : model.why === 'R needs a stop' && <div style={{ fontSize: 12, color: 'var(--warn)' }}>R needs a stop</div>}
    </div>
    {model.more.length > 0 && <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 2 }}>{'+' + model.more.length + ' more'}</div>}
  </div>;
}

function PerpsKpi({ label, value, color, sub, title, children }) {
  return <div className="tv-card" title={title} style={{ flex: '1 1 240px', minWidth: 0, padding: '14px 18px' }}>
    <div className="tv-label" style={{ fontSize: 12 }}>{label}</div>
    {value !== undefined && <div className="tv-num" style={{ fontSize: 20, fontWeight: 700, marginTop: 6, color: color || 'var(--text)', overflowWrap: 'anywhere' }}>{value}</div>}
    {sub}
    {children}
  </div>;
}

function PerpsFact({ label, children, mono, color }) {
  return <React.Fragment>
    <span style={{ fontSize: 13, color: 'var(--text3)' }}>{label}</span>
    <span style={{ fontSize: 13, color: color || 'var(--text2)', fontFamily: mono ? PRP_MONO : 'inherit', overflowWrap: 'anywhere' }}>{children}</span>
  </React.Fragment>;
}

function PerpsStatus({ saving, status }) {
  if (saving) return <span role="status" style={{ fontSize: 13, color: 'var(--text3)' }}>Saving…</span>;
  if (status === 'saved') return <span role="status" style={{ fontSize: 13, color: 'var(--ok)' }}>Saved</span>;
  if (status && status.error) return <span role="alert" style={{ fontSize: 13, color: 'var(--fail)' }}>{status.error}</span>;
  return null;
}

const PRP_SECTION = { fontSize: 12, lineHeight: '16px', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text3)' };
const PRP_FACTS = { display: 'grid', gridTemplateColumns: 'minmax(110px,150px) minmax(0,1fr)', rowGap: 8, columnGap: 12, alignContent: 'start' };

/* ── saving ──────────────────────────────────────────────────────────── */

// A text draft starts from the stored value and follows it when the stored
// value changes, unless the user has an unsaved edit.
function prpUseFollowingDraft(stored) {
  const [draft, setDraft] = usePRPState(stored);
  const prevRef = usePRPRef(stored);
  usePRPEffect(() => {
    const prev = prevRef.current;
    if (stored !== prev) {
      setDraft(d => (d === prev || d === stored) ? stored : d);
      prevRef.current = stored;
    }
  }, [stored]);
  return [draft, setDraft];
}

// One trade's writes: the annotation route for synced trades, the trade-log
// route for manual ones. onSaved re-reads the page.
function prpUseSaver(trade, onSaved) {
  const [saving, setSaving] = usePRPState(false);
  const [status, setStatus] = usePRPState(null);
  const aliveRef = usePRPRef(true);
  const timerRef = usePRPRef(null);
  usePRPEffect(() => () => { aliveRef.current = false; clearTimeout(timerRef.current); }, []);

  function send(path, options) {
    setSaving(true);
    setStatus(null);
    clearTimeout(timerRef.current);
    return api(path, options).then(() => {
      if (!aliveRef.current) return true;
      setSaving(false);
      setStatus('saved');
      timerRef.current = setTimeout(() => { if (aliveRef.current) setStatus(null); }, PRP_SAVED_MS);
      onSaved();
      return true;
    }).catch(e => {
      if (aliveRef.current) { setSaving(false); setStatus({ error: prpErr(e) }); }
      return false;
    });
  }
  const isManual = trade.source === 'manual';
  return {
    saving, status, aliveRef, isManual,
    annotate: body => send('/api/trading/trades/' + encodeURIComponent(trade.trade_id) + '/annotation',
                           { method: 'PUT', body: JSON.stringify(body) }),
    manual: body => send('/api/spot/trade-log/' + trade.manual_id, { method: 'PUT', body: JSON.stringify(body) }),
    remove: () => send('/api/spot/trade-log/' + trade.manual_id, { method: 'DELETE' }),
  };
}

/* ── shared pieces of an expanded row ────────────────────────────────── */

function PerpsStopEditor({ trade, saver, closed }) {
  const [draft, setDraft] = usePRPState('');
  const valid = prpPositive(draft);
  const id = 'prp-stop-' + trade.trade_id;
  function save() {
    if (saver.saving || !valid) return;
    saver.annotate({ stop_px: draft.trim() }).then(ok => { if (ok && saver.aliveRef.current) setDraft(''); });
  }
  const s = trade.stop;
  const hint = closed ? "A stop entered now, after the close, gives this trade an R but won't count toward the gate."
    : s ? (s.source === 'manual' ? 'Entered here. It is not an order on the venue; a venue stop order would be used once you clear this.'
           : 'From the ' + (PRP_STOP_SOURCE[s.source] || s.source).toLowerCase() + '. A stop entered here replaces it for R and the gate.')
    : 'No stop order found on ' + trade.venue + '. A stop entered here counts for R and the gate.';
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
    <label htmlFor={id} style={PRP_SECTION}>Stop</label>
    <div style={{ fontSize: 13, color: 'var(--text2)' }}>
      {s ? <span><span style={{ fontFamily: PRP_MONO }}>{prpPx(s.px)}</span>
             {' · ' + (PRP_STOP_SOURCE[s.source] || s.source) + (s.set_at ? ' · set ' + prpDate(s.set_at, true) : '')}</span>
        : 'No stop recorded.'}
    </div>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <input id={id} className="tv-input" style={{ width: 170, fontFamily: PRP_MONO }} inputMode="decimal"
        placeholder="Stop price" value={draft} disabled={saver.saving}
        onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') save(); }} />
      <button type="button" className="tv-btn primary" style={prpBtn(!valid || saver.saving, PRP_SMALL_BTN)} disabled={!valid || saver.saving} onClick={save}>Save stop</button>
      {s && s.source === 'manual' && <button type="button" className="tv-btn" style={prpBtn(saver.saving, PRP_SMALL_BTN)} disabled={saver.saving}
        onClick={() => saver.annotate({ stop_px: null })}>Clear</button>}
    </div>
    <div style={{ fontSize: 12, color: 'var(--text3)' }}>{hint}</div>
  </div>;
}

// Trade notes (and, on a closed trade, the deviation note): saved together.
function PerpsNotesEditor({ trade, saver, withDeviation }) {
  const ann = trade.annotation || {};
  const storedNotes = ann.notes || '';
  const storedDev = ann.deviation_note || '';
  const [notes, setNotes] = prpUseFollowingDraft(storedNotes);
  const [dev, setDev] = prpUseFollowingDraft(storedDev);
  const dirty = notes !== storedNotes || (withDeviation && dev !== storedDev);
  const idN = 'prp-notes-' + trade.trade_id;
  const idD = 'prp-dev-' + trade.trade_id;
  function save() {
    if (saver.saving || !dirty) return;
    const body = withDeviation ? { deviation_note: prpTextOrNull(dev), notes: prpTextOrNull(notes) } : { notes: prpTextOrNull(notes) };
    (saver.isManual ? saver.manual(body) : saver.annotate(body)).then(ok => {
      if (ok && saver.aliveRef.current) {
        setNotes(body.notes || '');
        if (withDeviation) setDev(body.deviation_note || '');
      }
    });
  }
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
    {withDeviation && <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label htmlFor={idD} style={PRP_SECTION}>Deviation note</label>
      <input id={idD} className="tv-input" maxLength={PRP_NOTE_MAX} placeholder="What was different from the plan (optional)"
        value={dev} disabled={saver.saving} onChange={e => setDev(e.target.value)} />
    </div>}
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label htmlFor={idN} style={PRP_SECTION}>Trade notes</label>
      <textarea id={idN} className="tv-input" rows={4} maxLength={PRP_NOTE_MAX}
        style={{ resize: 'vertical', fontFamily: 'inherit', fontSize: 14, lineHeight: '21px' }}
        placeholder={withDeviation ? "What went right, what you'd change" : 'Why you took it and the plan'}
        value={notes} disabled={saver.saving} onChange={e => setNotes(e.target.value)} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <button type="button" className="tv-btn primary" style={prpBtn(!dirty || saver.saving, PRP_SMALL_BTN)} disabled={!dirty || saver.saving} onClick={save}>
          Save notes</button>
        {dirty && <span style={{ fontSize: 12, color: 'var(--warn)' }}>Unsaved changes</span>}
        <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text3)', fontFamily: PRP_MONO }}>{notes.length} / {PRP_NOTE_MAX}</span>
      </div>
    </div>
  </div>;
}

function PerpsReviewButtons({ trade, saver }) {
  const followed = (trade.annotation || {}).followed_rules;
  function pick(value) {
    if (saver.saving) return;
    if (saver.isManual) saver.manual({ followed_rules: value ? 1 : 0 });
    else saver.annotate({ followed_rules: value });
  }
  const btn = (value, label, color) => {
    const active = followed === value;
    return <button key={label} type="button" className="tv-btn" aria-pressed={active} disabled={saver.saving}
      onClick={() => pick(value)}
      style={prpBtn(saver.saving, { ...PRP_SMALL_BTN, borderRadius: 999, background: active ? 'var(--panel3)' : 'transparent',
               borderColor: active ? color : 'var(--line)', color: active ? color : 'var(--text3)', fontWeight: active ? 600 : 400 })}>{label}</button>;
  };
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
    <span style={PRP_SECTION}>Did you follow your rules?</span>
    <div role="group" aria-label={'Review for the ' + trade.symbol + ' ' + trade.direction} style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {btn(true, 'Followed', 'var(--ok)')}
      {btn(false, 'Deviated', 'var(--fail)')}
      {!saver.isManual && btn(null, 'Not reviewed', 'var(--text3)')}
    </div>
  </div>;
}

function PerpsManualClose({ trade, saver }) {
  const [exit, setExit] = usePRPState('');
  const [at, setAt] = usePRPState(prpNowLocal());
  const [followed, setFollowed] = usePRPState('');
  const valid = prpPositive(exit) && followed !== '';
  function close() {
    if (saver.saving || !valid) return;
    saver.manual({ exit_price: Number(exit.trim()), exited_at: prpLocalToIso(at), followed_rules: Number(followed) });
  }
  const id = 'prp-exit-' + trade.trade_id;
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
    <label htmlFor={id} style={PRP_SECTION}>Close this trade</label>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      <input id={id} className="tv-input" style={{ width: 140, fontFamily: PRP_MONO }} inputMode="decimal" placeholder="Exit price"
        value={exit} disabled={saver.saving} onChange={e => setExit(e.target.value)} />
      <input className="tv-input" type="datetime-local" aria-label="Closed at" style={{ width: 210 }} value={at}
        disabled={saver.saving} onChange={e => setAt(e.target.value)} />
      <select className="tv-select" aria-label="Followed the rules?" value={followed} disabled={saver.saving}
        onChange={e => setFollowed(e.target.value)}>
        <option value="">Followed the rules?</option>
        <option value="1">Followed</option>
        <option value="0">Deviated</option>
      </select>
      <button type="button" className="tv-btn primary" style={prpBtn(!valid || saver.saving, PRP_SMALL_BTN)} disabled={!valid || saver.saving} onClick={close}>Close trade</button>
    </div>
  </div>;
}

function PerpsManualDelete({ trade, saver }) {
  function del() {
    if (saver.saving) return;
    const ok = window.confirm('Delete the manual ' + trade.symbol + ' trade logged ' + prpDate(trade.opened_at) + "? This can't be undone.");
    if (ok) saver.remove();
  }
  return <div><button type="button" className="tv-btn danger" style={prpBtn(saver.saving, PRP_SMALL_BTN)} disabled={saver.saving} onClick={del}>Delete manual trade</button></div>;
}

/* ── Open positions ──────────────────────────────────────────────────── */

const PRP_TP_SOURCE = { hyperliquid: 'Hyperliquid take-profit orders', txflow: 'TxFlow position take-profits' };

function PerpsOpenRow({ trade: t, open, onToggle, hide, onSaved }) {
  const saver = prpUseSaver(t, onSaved);
  const isManual = t.source === 'manual';
  const live = t.live;
  const lev = prpLev(t.leverage, t.leverage_type);
  const size = prpOpenSize(t);
  const tps = isManual ? (t.target_px ? [t.target_px] : []) : live ? live.take_profits : null;
  const target = prpTarget(t.direction, t.avg_entry, t.stop ? t.stop.px : null, tps);
  const unknownTip = isManual ? undefined : live ? "This venue's take-profit orders couldn't be read" : 'No live data for this position yet';
  const unr = prpNum(t.unrealized_pnl);
  const oneR = prpOneR(t);
  const fundingApprox = (t.flags || []).indexOf('funding_approx') >= 0;
  const fundingMissing = (t.flags || []).indexOf('funding_missing') >= 0;
  const fundingText = isManual || t.funding == null ? '—' : fundingMissing ? 'Not recorded'
    : (fundingApprox ? '≈ ' : '') + prpUsd(t.funding, hide, true);
  const sym = String(t.symbol || '');
  const num = (label, content, style, title) => <div className="spot-cell tv-num" data-label={label} title={title}
    style={{ textAlign: 'right', fontFamily: PRP_MONO, ...style }}>{content}</div>;

  let status;
  if (t.attention === 'needs_stop') status = <span className="tv-chip warn" style={{ fontSize: 12, fontWeight: 600 }}>Needs a stop</span>;
  else if (!t.stop) status = <span style={{ color: 'var(--text3)' }} title="Opened before the gate start, so it isn't flagged">No stop</span>;
  else status = <span style={{ color: 'var(--text3)' }}>Stop set</span>;
  let statusNote = null;
  if (isManual) statusNote = 'Manual · no price feed';
  else if (!live) statusNote = 'No live data';
  else if (live.stale) statusNote = 'Price may be stale';
  const statusTip = isManual ? 'Manual trades have no price feed, so Mark and Unrealized stay empty.'
    : !live ? 'The venue cache has no open position for this trade: it is still loading, or the position closed on the venue and the next fill sync (every 10 minutes) will close this trade.'
    : live.stale ? 'The last venue read for this wallet failed; these are the previous figures.' : undefined;

  const row = <div id={'prp-row-' + t.trade_id} className="spot-grid-row" style={{ gridTemplateColumns: PRP_OPEN_GRID, padding: '10px 16px', borderBottom: PRP_LINE,
                                                      fontSize: 13, color: 'var(--text2)', background: open ? 'var(--panel2)' : undefined }}>
    <div className="spot-span" style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
      <button type="button" className="tv-btn" aria-expanded={open}
        aria-label={(open ? 'Hide' : 'Show') + ' details for the ' + sym + ' ' + t.direction}
        onClick={() => onToggle(t.trade_id)}
        style={{ width: 32, height: 32, padding: 0, flex: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, color: 'var(--text)' }}>
        {open ? '▾' : '▸'}</button>
      <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <span style={{ fontWeight: 700, color: 'var(--text)', fontSize: 14 }}>
          {sym}{(t.annotation || {}).notes && String(t.annotation.notes).trim()
            ? <span title="Has trade notes" aria-label="Has trade notes" style={{ marginLeft: 6, color: 'var(--text3)', fontWeight: 400 }}>✎</span> : null}
        </span>
        <span style={{ fontSize: 12, color: 'var(--text3)', overflowWrap: 'anywhere' }}>{prpVenueLine(t)}</span>
      </div>
    </div>
    <div className="spot-cell" data-label="Side">{prpSide(t.direction)}</div>
    {num('Leverage', lev.text, null, lev.tip)}
    <div className="spot-cell spot-pad-left" data-label="Opened" style={{ color: 'var(--text3)', whiteSpace: 'nowrap' }}>{prpDate(t.opened_at, true)}</div>
    {num('Size', prpSize(size, hide), null, live ? undefined : isManual ? 'Logged size' : 'Peak size (no live data)')}
    {num('Entry', prpPx(t.avg_entry))}
    {num('Mark', isManual ? '—' : live ? prpPx(live.mark_px) : '—', null, isManual ? 'Manual trades have no price feed' : undefined)}
    {num('Stop', t.stop ? prpPx(t.stop.px) : '—', null,
         t.stop ? (PRP_STOP_SOURCE[t.stop.source] || t.stop.source) + (t.stop.set_at ? ' · set ' + prpDate(t.stop.set_at, true) : '') : 'No stop recorded')}
    <div className="spot-cell" data-label="Target" style={{ textAlign: 'right' }}><PerpsTargetCell model={target} unknownTip={unknownTip} /></div>
    <div className="spot-cell tv-num" data-label="Unrealized" style={{ textAlign: 'right', fontFamily: PRP_MONO }}>
      <div style={{ fontWeight: 600, color: isManual ? 'var(--text3)' : prpMoneyColor(unr, hide) }}>{isManual ? '—' : prpUsd(unr, hide, true)}</div>
      {!isManual && unr !== null && oneR !== null && <div style={{ fontSize: 11, color: 'var(--text3)' }}>{'≈ ' + prpR(unr / oneR)}</div>}
    </div>
    {num('Funding', fundingText, { color: fundingMissing ? 'var(--text3)' : prpMoneyColor(t.funding, hide) },
         fundingApprox ? 'TxFlow funding is approximate (from position readings)' : fundingMissing ? 'TxFlow funding was not recorded for this trade' : 'Funding so far (negative = paid)')}
    <div className="spot-cell spot-pad-left" data-label="Status" title={statusTip} style={{ display: 'flex', flexDirection: 'column', gap: 3, alignItems: 'flex-start' }}>
      {status}
      {statusNote && <span style={{ fontSize: 11, color: live && live.stale ? 'var(--warn)' : 'var(--text3)' }}>{statusNote}</span>}
    </div>
  </div>;
  if (!open) return row;

  const tpList = Array.isArray(tps) && tps.length ? tps.map(prpPx).join(', ') : null;
  return <React.Fragment>
    {row}
    <div className="spot-detail" style={{ padding: '16px 16px 20px 56px', borderBottom: PRP_LINE, background: 'var(--bg)',
                                          display: 'flex', flexWrap: 'wrap', gap: 28 }}>
      <div style={{ ...PRP_FACTS, flex: '1 1 280px' }}>
        <PerpsFact label="Venue">{prpVenueLine(t)}</PerpsFact>
        <PerpsFact label="Opened">{prpDate(t.opened_at, true)}</PerpsFact>
        <PerpsFact label="Leverage" mono>{lev.tip === lev.text ? lev.text : lev.text === '—' ? '—' : lev.tip}</PerpsFact>
        <PerpsFact label="Peak size" mono>{prpSize(t.size_peak, hide)}</PerpsFact>
        {!isManual && <PerpsFact label="Fees so far" mono color={prpMoneyColor(t.fees == null ? null : -prpNum(t.fees), hide)}>
          {t.fees == null ? '—' : prpUsd(-prpNum(t.fees), hide, true)}</PerpsFact>}
        {!isManual && <PerpsFact label="Funding so far" mono>{fundingText}</PerpsFact>}
        <PerpsFact label="1R at the stop" mono>{oneR === null ? '—' : prpUsd(oneR, hide)}</PerpsFact>
        {!isManual && <PerpsFact label="Liquidation" mono>{live && live.liquidation_px ? prpPx(live.liquidation_px) : '—'}</PerpsFact>}
        <PerpsFact label="Take-profit">
          {tpList ? (isManual ? 'Target logged with the trade: ' : (PRP_TP_SOURCE[t.source] || 'Take-profits') + ': ') + tpList
            : Array.isArray(tps) ? 'No take-profit order found' : unknownTip}
        </PerpsFact>
        {!isManual && live && live.as_of && <PerpsFact label="Live data">{'As of ' + prpDate(live.as_of, true)}</PerpsFact>}
      </div>
      <div style={{ flex: '2 1 420px', display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}>
        {isManual ? <PerpsManualClose trade={t} saver={saver} /> : <PerpsStopEditor trade={t} saver={saver} closed={false} />}
        <PerpsNotesEditor trade={t} saver={saver} withDeviation={false} />
        <span style={{ fontSize: 13, color: 'var(--text3)' }}>Followed or deviated is set once the trade closes, in History.</span>
        {isManual && <PerpsManualDelete trade={t} saver={saver} />}
        <PerpsStatus saving={saver.saving} status={saver.status} />
      </div>
    </div>
  </React.Fragment>;
}

// A live venue position with no trade yet: live fields only, nothing to save.
function PerpsUntrackedRow({ row: u, hide }) {
  const live = u.live || {};
  const lev = prpLev(live.leverage, live.leverage_type);
  const target = prpTarget(u.direction, live.entry_px, live.stop_px, live.take_profits);
  const num = (label, content, style, title) => <div className="spot-cell tv-num" data-label={label} title={title}
    style={{ textAlign: 'right', fontFamily: PRP_MONO, ...style }}>{content}</div>;
  const unr = prpNum(live.unrealized_pnl);
  return <div className="spot-grid-row" style={{ gridTemplateColumns: PRP_OPEN_GRID, padding: '10px 16px', borderBottom: PRP_LINE,
                                                 fontSize: 13, color: 'var(--text2)' }}>
    <div className="spot-span" style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
      <span aria-hidden="true" style={{ width: 32, flex: 'none' }} />
      <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <span style={{ fontWeight: 700, color: 'var(--text)', fontSize: 14 }}>{u.symbol}</span>
        <span style={{ fontSize: 12, color: 'var(--text3)', overflowWrap: 'anywhere' }}>
          {(!u.wallet_label || u.wallet_label === u.venue) ? u.venue : u.venue + ' · ' + u.wallet_label}</span>
      </div>
    </div>
    <div className="spot-cell" data-label="Side">{prpSide(u.direction)}</div>
    {num('Leverage', lev.text, null, lev.tip)}
    <div className="spot-cell spot-pad-left" data-label="Opened" style={{ color: 'var(--text3)' }}>—</div>
    {num('Size', prpSize(live.size, hide))}
    {num('Entry', prpPx(live.entry_px), null, "The venue's average entry")}
    {num('Mark', prpPx(live.mark_px))}
    {num('Stop', live.stop_px ? prpPx(live.stop_px) : '—', null, live.stop_px ? 'Venue stop order' : 'No stop order found')}
    <div className="spot-cell" data-label="Target" style={{ textAlign: 'right' }}><PerpsTargetCell model={target} /></div>
    {num('Unrealized', prpUsd(unr, hide, true), { fontWeight: 600, color: prpMoneyColor(unr, hide) })}
    {num('Funding', '—')}
    <div className="spot-cell spot-pad-left" data-label="Status"
      title="This position is open on the venue but not in your trade history yet: its fills haven't synced, or it opened before the sync window. Stops, notes and reviews attach once it becomes a trade.">
      <span className="tv-chip adapt" style={{ fontSize: 12, fontWeight: 600 }}>Not in trade history yet</span>
    </div>
  </div>;
}

function PerpsOpenTab({ trades, untracked, expanded, onToggle, hide, onSaved }) {
  const head = { fontSize: 12, lineHeight: '16px', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text3)' };
  const right = { textAlign: 'right' };
  if (!trades.length && !untracked.length) {
    return <div className="tv-card" style={{ color: 'var(--text3)', padding: 20, textAlign: 'center', fontSize: 14 }}>No open perp positions.</div>;
  }
  return <div>
    <div className="tv-card" style={{ padding: 0, overflow: 'hidden' }}>
      <div className="spot-grid-row spot-grid-head" style={{ ...head, gridTemplateColumns: PRP_OPEN_GRID, alignItems: 'end',
                                                             padding: '12px 16px', borderBottom: PRP_HEAD_LINE }}>
        <span>Symbol</span><span>Side</span><span style={right}>Lev</span><span className="spot-pad-left">Opened</span>
        <span style={right}>Size</span><span style={right}>Entry</span><span style={right}>Mark</span><span style={right}>Stop</span>
        <span style={right}>Target</span><span style={right}>Unrealized</span><span style={right}>Funding</span>
        <span className="spot-pad-left">Status</span>
      </div>
      {trades.map(t => <PerpsOpenRow key={t.trade_id} trade={t} open={!!expanded[t.trade_id]} onToggle={onToggle} hide={hide} onSaved={onSaved} />)}
      {untracked.map(u => <PerpsUntrackedRow key={u.venue + '|' + u.wallet_label + '|' + u.symbol} row={u} hide={hide} />)}
    </div>
    <div style={{ fontSize: 13, color: 'var(--text3)', marginTop: 10 }}>
      Target shows the nearest take-profit and its distance from entry in R (1R = entry to stop). Size is the venue's current size; 1R uses the peak size, like R at the close.
    </div>
  </div>;
}

/* ── History ─────────────────────────────────────────────────────────── */

function PerpsHistoryRow({ trade: t, open, onToggle, hide, onSaved, gateStart }) {
  const saver = prpUseSaver(t, onSaved);
  const isManual = t.source === 'manual';
  const lev = prpLev(t.leverage, t.leverage_type);
  const followed = (t.annotation || {}).followed_rules;
  const g = t.gate || {};
  const sym = String(t.symbol || '');
  const flags = t.flags || [];
  const num = (label, content, style, title) => <div className="spot-cell tv-num" data-label={label} title={title}
    style={{ textAlign: 'right', fontFamily: PRP_MONO, ...style }}>{content}</div>;
  let review;
  if (followed === true) review = <span style={{ color: 'var(--ok)' }}>Followed</span>;
  else if (followed === false) review = <span style={{ color: 'var(--fail)' }}>Deviated</span>;
  else if (t.attention === 'needs_review') review = <span className="tv-chip warn" style={{ fontSize: 12, fontWeight: 600 }}>Needs review</span>;
  else review = <span style={{ color: 'var(--text3)' }}>Not reviewed</span>;
  const fundingMissing = flags.indexOf('funding_missing') >= 0;
  const fundingText = isManual || t.funding == null ? '—' : fundingMissing ? 'Not recorded'
    : (flags.indexOf('funding_approx') >= 0 ? '≈ ' : '') + prpUsd(t.funding, hide, true);
  const oneR = prpOneR(t);

  const row = <div id={'prp-row-' + t.trade_id} className="spot-grid-row" style={{ gridTemplateColumns: PRP_HIST_GRID, padding: '10px 16px', borderBottom: PRP_LINE,
                                                      fontSize: 13, color: 'var(--text2)', background: open ? 'var(--panel2)' : undefined }}>
    <div className="spot-span" style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
      <button type="button" className="tv-btn" aria-expanded={open}
        aria-label={(open ? 'Hide' : 'Show') + ' details for the ' + sym + ' ' + t.direction + ' closed ' + prpDate(t.closed_at)}
        onClick={() => onToggle(t.trade_id)}
        style={{ width: 32, height: 32, padding: 0, flex: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, color: 'var(--text)' }}>
        {open ? '▾' : '▸'}</button>
      <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <span style={{ fontWeight: 700, color: 'var(--text)', fontSize: 14 }}>
          {sym}{(t.annotation || {}).notes && String(t.annotation.notes).trim()
            ? <span title="Has trade notes" aria-label="Has trade notes" style={{ marginLeft: 6, color: 'var(--text3)', fontWeight: 400 }}>✎</span> : null}
        </span>
        <span style={{ fontSize: 12, color: 'var(--text3)', overflowWrap: 'anywhere' }}>{prpVenueLine(t)}</span>
      </div>
    </div>
    <div className="spot-cell" data-label="Side">{prpSide(t.direction)}</div>
    {num('Leverage', lev.text, null, lev.tip)}
    <div className="spot-cell spot-pad-left" data-label="Opened → closed" style={{ color: 'var(--text3)' }}>{prpDate(t.opened_at) + ' → ' + prpDate(t.closed_at)}</div>
    {num('Entry → exit', prpPx(t.avg_entry) + ' → ' + prpPx(t.avg_exit))}
    {num('Stop', t.stop ? prpPx(t.stop.px) : '—', null, t.stop ? (PRP_STOP_SOURCE[t.stop.source] || t.stop.source) : 'No stop recorded')}
    {num('Net P&L', prpUsd(t.net_pnl, hide, true), { fontWeight: 600, color: prpMoneyColor(t.net_pnl, hide) })}
    {num('R', prpR(t.r_multiple) + (t.r_multiple != null && t.r_basis === 'price' ? '*' : ''), { color: prpColor(t.r_multiple) },
         t.r_basis === 'price' ? 'R from prices (manual trades have no fee data)' : undefined)}
    <div className="spot-cell spot-pad-left" data-label="Review">{review}</div>
    <div className="spot-cell" data-label="Gate" title={g.eligible ? 'Counts toward the gate' : PRP_GATE_LONG[g.reason]}>
      {g.eligible ? <span className="tv-chip ok" style={{ fontSize: 12, fontWeight: 600 }}>Counts</span>
        : <span style={{ color: 'var(--text3)' }}>{PRP_GATE_SHORT[g.reason] || g.reason || '—'}</span>}
    </div>
  </div>;
  if (!open) return row;

  const gateText = g.eligible ? 'Counts toward the gate' : (PRP_GATE_LONG[g.reason] || g.reason || '—');
  return <React.Fragment>
    {row}
    <div className="spot-detail" style={{ padding: '16px 16px 20px 56px', borderBottom: PRP_LINE, background: 'var(--bg)',
                                          display: 'flex', flexWrap: 'wrap', gap: 28 }}>
      <div style={{ flex: '1 1 280px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={PRP_FACTS}>
          <PerpsFact label="Venue">{prpVenueLine(t)}</PerpsFact>
          <PerpsFact label="Opened">{prpDate(t.opened_at, true)}</PerpsFact>
          <PerpsFact label="Closed">{prpDate(t.closed_at, true)}</PerpsFact>
          <PerpsFact label="Peak size" mono>{prpSize(t.size_peak, hide)}</PerpsFact>
          {!isManual && <PerpsFact label="Fees" mono color={prpMoneyColor(t.fees == null ? null : -prpNum(t.fees), hide)}>
            {t.fees == null ? '—' : prpUsd(-prpNum(t.fees), hide, true)}</PerpsFact>}
          {!isManual && <PerpsFact label="Funding" mono>{fundingText}</PerpsFact>}
          <PerpsFact label="1R (peak size to stop)" mono>{oneR === null ? '—' : prpUsd(oneR, hide)}</PerpsFact>
          <PerpsFact label="Stop source">{t.stop ? (PRP_STOP_SOURCE[t.stop.source] || t.stop.source) : 'No stop recorded'}</PerpsFact>
          <PerpsFact label="Gate" color={g.eligible ? 'var(--ok)' : undefined}>{gateText}</PerpsFact>
        </div>
        {flags.filter(f => PRP_FLAGS[f]).length > 0 && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {flags.filter(f => PRP_FLAGS[f]).map(f => <span key={f} className="tv-chip warn">{PRP_FLAGS[f]}</span>)}
        </div>}
        {t.before_rule && <div style={{ fontSize: 12, color: 'var(--text3)' }}>{'Opened before ' + (gateStart ? prpDate(gateStart) : 'the gate start') + ', so it does not count toward the gate.'}</div>}
      </div>
      <div style={{ flex: '2 1 420px', display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}>
        <PerpsReviewButtons trade={t} saver={saver} />
        <PerpsNotesEditor trade={t} saver={saver} withDeviation={true} />
        {!isManual && <PerpsStopEditor trade={t} saver={saver} closed={true} />}
        {isManual && <PerpsManualDelete trade={t} saver={saver} />}
        <PerpsStatus saving={saver.saving} status={saver.status} />
      </div>
    </div>
  </React.Fragment>;
}

function PerpsUnattached({ items }) {
  return <div className="tv-card" style={{ marginTop: 16 }}>
    <div className="tv-label" style={{ fontSize: 12 }}>{'Notes no longer attached to a trade (' + items.length + ')'}</div>
    <div style={{ fontSize: 13, color: 'var(--text2)', margin: '8px 0' }}>
      Their trade changed shape (for example, its first fill was corrected). Nothing was deleted.
    </div>
    {items.map(a => <div key={a.trade_id} style={{ fontSize: 13, color: 'var(--text2)', padding: '6px 0', borderTop: PRP_LINE }}>
      {(a.market === 'perp' ? 'Perp' : 'Spot') + ' · last edited ' + prpDate(a.updated_at, true) + ' · '
        + (a.has_notes ? 'has notes' : 'stop or review only')}
    </div>)}
  </div>;
}

function PerpsHistoryTab({ trades, expanded, onToggle, hide, onSaved, gateStart, unattached }) {
  const [earlier, setEarlierState] = usePRPState(() => prpReadLocal('perpsHistoryEarlier', '0') === '1');
  function setEarlier(v) { setEarlierState(v); prpWriteLocal('perpsHistoryEarlier', v ? '1' : '0'); }
  const earlierCount = trades.filter(t => t.before_rule).length;
  const when = v => { const ms = Date.parse(v || ''); return isNaN(ms) ? -Infinity : ms; };
  // Newest close first, then newest open (like Spot History by trade).
  const rows = trades.filter(t => earlier || !t.before_rule)
    .sort((a, b) => when(b.closed_at) - when(a.closed_at) || when(b.opened_at) - when(a.opened_at));
  const head = { fontSize: 12, lineHeight: '16px', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text3)' };
  const right = { textAlign: 'right' };
  const sinceText = gateStart ? prpDate(gateStart) : 'Sep 13';
  const toReview = rows.filter(t => t.attention === 'needs_review').length;
  return <div>
    <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap', marginBottom: 12, fontSize: 13, color: 'var(--text3)' }}>
      <span>{rows.length + ' closed' + (toReview ? ' · ' + toReview + ' to review' : '')}</span>
      <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
        <input type="checkbox" checked={earlier} onChange={e => setEarlier(e.target.checked)} />
        {'Show trades opened before ' + sinceText + ' (' + earlierCount + ')'}
      </label>
    </div>
    {trades.length === 0 ? <div className="tv-card" style={{ color: 'var(--text3)', padding: 20, textAlign: 'center', fontSize: 14 }}>No closed perp trades yet.</div>
    : rows.length === 0 ? <div className="tv-card" style={{ color: 'var(--text3)', padding: 20, textAlign: 'center', fontSize: 14 }}>No closed trades in this view.</div>
    : <div className="tv-card" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="spot-grid-row spot-grid-head" style={{ ...head, gridTemplateColumns: PRP_HIST_GRID, alignItems: 'end',
                                                               padding: '12px 16px', borderBottom: PRP_HEAD_LINE }}>
          <span>Symbol</span><span>Side</span><span style={right}>Lev</span><span className="spot-pad-left">Opened → closed</span>
          <span style={right}>Entry → exit</span><span style={right}>Stop</span><span style={right}>Net P&L</span>
          <span style={right}>R</span><span className="spot-pad-left">Review</span><span>Gate</span>
        </div>
        {rows.map(t => <PerpsHistoryRow key={t.trade_id} trade={t} open={!!expanded[t.trade_id]} onToggle={onToggle}
          hide={hide} onSaved={onSaved} gateStart={gateStart} />)}
      </div>}
    <div style={{ fontSize: 13, color: 'var(--text3)', marginTop: 10 }}>
      * R from prices (manual trades have no fee data). Lev shows "—" on closed synced trades until the trade-open snapshot records it.
    </div>
    {unattached.length > 0 && <PerpsUnattached items={unattached} />}
  </div>;
}

/* ── the top cards ───────────────────────────────────────────────────── */

function PerpsCards({ summary, openTrades, hide }) {
  const perp = summary.perp || {};
  const all = perp.all_time || {};
  const gate = summary.gate || {};
  const sinceText = gate.start ? prpDate(gate.start) : 'Sep 13';

  const net = prpNum(perp.net_pnl);
  const closedSub = (perp.closed_count || 0) + ' closed · ' + (perp.win_count || 0) + 'W / ' + (perp.loss_count || 0) + 'L'
    + (perp.avg_r != null ? ' · avg ' + prpR(perp.avg_r) : '');

  const synced = openTrades.filter(t => t.source !== 'manual');
  const manualOpen = openTrades.length - synced.length;
  const unrKnown = synced.filter(t => prpNum(t.unrealized_pnl) !== null);
  const unr = unrKnown.reduce((s, t) => s + prpNum(t.unrealized_pnl), 0);
  const funding = synced.reduce((s, t) => s + (prpNum(t.funding) || 0), 0);
  const unrSubParts = [openTrades.length + ' open'];
  if (synced.length) unrSubParts.push('funding ' + prpUsd(funding, hide, true));
  if (manualOpen) unrSubParts.push(manualOpen + ' manual, no price feed');
  if (unrKnown.length < synced.length) unrSubParts.push((synced.length - unrKnown.length) + ' waiting for prices');

  let risk = 0, noStop = 0, unpriced = 0, freeRide = 0;
  openTrades.forEach(t => {
    if (!t.stop) { noStop += 1; return; }
    const r = prpOpenRisk(t);
    if (r === null) { unpriced += 1; return; }
    if (r === 0) freeRide += 1;
    risk += r;
  });
  const riskNotes = [];
  if (noStop) riskNotes.push(noStop === 1 ? '1 open trade has no stop' : noStop + ' open trades have no stop');
  if (freeRide) riskNotes.push(freeRide === 1 ? '1 stop at or past entry (no risk)' : freeRide + ' stops at or past entry (no risk)');
  if (unpriced) riskNotes.push(unpriced + ' without a price');

  const target = Number(gate.target) || 0;
  const count = Number(gate.eligible_count) || 0;
  const exp = prpNum(gate.expectancy_r);
  const unlocked = !!gate.unlocked;
  const check = (ok, text, need) => <span>
    <span aria-hidden="true" style={{ color: ok ? 'var(--ok)' : 'var(--fail)', fontWeight: 700, marginRight: 6 }}>{ok ? '✓' : '✗'}</span>
    <span style={{ color: 'var(--text)' }}>{text}</span>
    <span style={{ color: 'var(--text3)' }}>{' (' + need + ')'}</span>
    <span className="sr-only" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>{ok ? ' passed' : ' not passed'}</span>
  </span>;

  return <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
    <PerpsKpi label={'Closed since ' + sinceText} value={net === null ? '—' : prpUsd(net, hide, true)} color={prpMoneyColor(net, hide)}
      title={'All time: ' + (all.closed_count || 0) + ' closed · ' + prpUsd(all.net_pnl, hide, true)}
      sub={<div style={{ fontSize: 13, color: 'var(--text3)', marginTop: 4 }}>{closedSub}</div>} />
    <PerpsKpi label="Open unrealized" value={synced.length ? prpUsd(unr, hide, true) : '—'} color={synced.length ? prpMoneyColor(unr, hide) : undefined}
      sub={<div style={{ fontSize: 13, color: 'var(--text3)', marginTop: 4 }}>{unrSubParts.join(' · ')}</div>} />
    <PerpsKpi label="Open risk at stops" value={prpUsd(risk, hide)}
      title="What every open perp trade would lose from entry to its stop, at its current size. A stop at or past entry counts as no risk. Stops entered here count, even though they aren't orders on the venue."
      sub={<div style={{ fontSize: 13, marginTop: 4, color: noStop ? 'var(--warn)' : 'var(--text3)' }}>
        {riskNotes.length ? riskNotes.join(' · ') : 'entry to stop · current size'}</div>} />
    <PerpsKpi label="Risk gate · 1% → 2%"
      title={'Counts closed perp trades opened since ' + sinceText + ' that you marked Followed, with a stop placed before they closed. Both checks must pass to move to 2%.'}>
      <div style={{ fontSize: 20, lineHeight: '26px', fontWeight: 700, marginTop: 6, color: unlocked ? 'var(--ok)' : 'var(--warn)' }}>
        {unlocked ? '2% allowed' : 'Stay at 1%'}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 4, fontSize: 13, color: 'var(--text2)' }}>
        {check(count >= target, count + ' rule-following trades', target + '+ needed')}
        {check(exp !== null && exp > 0, 'Average R ' + (exp === null ? '—' : (exp > 0 ? '+' : '') + exp.toFixed(2)), 'above 0 needed')}
      </div>
    </PerpsKpi>
  </div>;
}

/* ── Transactions (Landing 3b) ───────────────────────────────────────── */

const PRP_TX_GRID = 'minmax(130px,1fr) minmax(56px,0.5fr) minmax(52px,0.45fr) minmax(170px,1.4fr) '
  + 'repeat(4,minmax(80px,0.8fr)) minmax(96px,0.8fr)';
const PRP_LEV_MAX = 1000;            // TRADE_LOG_LEVERAGE_MAX on the server

function prpEmptyForm() {
  return { ticker: '', direction: 'long', leverage: '', qty: '', entry_price: '', stop_price: '', target_price: '',
           venue: '', entered_at: prpNowLocal(), exit_price: '', exited_at: '', followed: '', deviation_note: '', notes: '' };
}

// The synced-fills card: one line per venue (wallet labels only).
function PerpsSyncCard({ sync }) {
  const venues = Array.isArray(sync) ? sync : [];
  return <div className="tv-card" style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '16px 20px' }}>
    <span style={PRP_SECTION}>Synced fills</span>
    {venues.length === 0 && <span style={{ fontSize: 14, color: 'var(--text3)' }}>No perp wallets are synced yet.</span>}
    {venues.map(v => <div key={v.venue} style={{ fontSize: 14, color: 'var(--text2)', display: 'flex', flexWrap: 'wrap', gap: '4px 10px' }}>
      <span style={{ fontWeight: 600, color: 'var(--text)' }}>{v.venue}</span>
      <span style={{ color: 'var(--text3)' }}>{v.wallets === 1 ? '1 wallet' : v.wallets + ' wallets'}</span>
      <span style={{ color: 'var(--text3)' }}>{v.in_flight ? 'syncing now'
        : v.last_ok_at ? 'last good sync ' + prpAgo(v.last_ok_at) + ' (' + prpDate(v.last_ok_at, true) + ')' : 'not synced yet'}</span>
      {v.failing && v.failing.length > 0 && <span role="status" style={{ color: 'var(--warn)' }}>{'last attempt failed for ' + v.failing.join(', ')}</span>}
    </div>)}
    <span style={{ fontSize: 13, color: 'var(--text3)' }}>Every 10 minutes while the app is open, every 2 hours otherwise. Trades are built from these fills automatically.</span>
  </div>;
}

// The manual perp trade form (moved from Trade Log; perp only, ruling 3):
// Leverage, and a finished trade can be logged in one step (ruling 5):
// Exit price with Followed / Deviated required, Closed and the deviation note optional.
function PerpsManualForm({ onSaved, onClose }) {
  const [form, setForm] = usePRPState(prpEmptyForm);
  const [tickers, setTickers] = usePRPState(null);
  const [saving, setSaving] = usePRPState(false);
  const [error, setError] = usePRPState(null);
  const aliveRef = usePRPRef(true);
  usePRPEffect(() => () => { aliveRef.current = false; }, []);
  usePRPEffect(() => {
    api('/api/trading/scanner/noodle-state').then(d => {
      if (!aliveRef.current) return;
      setTickers((d && Array.isArray(d.symbols) ? d.symbols : []).map(x => x && x.symbol).filter(Boolean));
    }).catch(() => { if (aliveRef.current) setTickers([]); });
  }, []);
  function set(k, v) { setForm(f => Object.assign({}, f, { [k]: v })); }

  const blank = v => String(v).trim() === '';
  const closing = !blank(form.exit_price);
  const problems = [];
  if (blank(form.ticker)) problems.push('a symbol');
  if (!prpPositive(form.qty)) problems.push('a size above 0');
  if (!prpPositive(form.entry_price)) problems.push('an entry price above 0');
  if (!prpPositive(form.stop_price)) problems.push('a stop price above 0');
  const sameEntryStop = prpPositive(form.entry_price) && prpPositive(form.stop_price) && Number(form.entry_price) === Number(form.stop_price);
  const levBad = !blank(form.leverage) && !(prpPositive(form.leverage) && Number(form.leverage) <= PRP_LEV_MAX);
  const targetBad = !blank(form.target_price) && !prpPositive(form.target_price);
  const exitBad = closing && !prpPositive(form.exit_price);
  const followedMissing = closing && form.followed === '';
  const openedMs = Date.parse(form.entered_at || '');
  const closedMs = Date.parse(form.exited_at || '');
  const closedEarly = closing && !isNaN(openedMs) && !isNaN(closedMs) && closedMs < openedMs;
  const closedWithoutExit = !closing && !blank(form.exited_at);
  const valid = !problems.length && !sameEntryStop && !levBad && !targetBad && !exitBad && !followedMissing && !closedEarly && !closedWithoutExit;
  const messages = [];
  if (sameEntryStop) messages.push("Entry and stop can't be equal (zero risk).");
  if (levBad) messages.push('Leverage must be above 0 and at most ' + PRP_LEV_MAX + '.');
  if (targetBad) messages.push('Target must be above 0, or blank.');
  if (exitBad) messages.push('Exit price must be above 0, or blank while the trade is open.');
  if (followedMissing) messages.push('A closed trade needs Followed or Deviated.');
  if (closedEarly) messages.push("Closed can't be before Opened.");
  if (closedWithoutExit) messages.push('Closed needs an exit price.');

  function submit() {
    if (!valid || saving) return;
    setSaving(true);
    setError(null);
    const body = {
      ticker: form.ticker.trim(), direction: form.direction, market: 'perp', source: 'manual',
      venue: form.venue.trim() || null,
      entry_price: Number(form.entry_price), stop_price: Number(form.stop_price), qty: Number(form.qty),
      target_price: blank(form.target_price) ? null : Number(form.target_price),
      leverage: blank(form.leverage) ? null : Number(form.leverage),
      entered_at: prpLocalToIso(form.entered_at),
      notes: prpTextOrNull(form.notes),
    };
    if (closing) {
      body.exit_price = Number(form.exit_price);
      body.followed_rules = Number(form.followed);
      if (!blank(form.exited_at)) body.exited_at = prpLocalToIso(form.exited_at);
      if (!blank(form.deviation_note)) body.deviation_note = form.deviation_note;
    }
    api('/api/spot/trade-log', { method: 'POST', body: JSON.stringify(body) }).then(() => {
      if (!aliveRef.current) return;
      setSaving(false);
      setForm(prpEmptyForm());
      onSaved();
      onClose();
    }).catch(e => {
      if (!aliveRef.current) return;
      setSaving(false);
      setError(prpErr(e));
    });
  }

  const field = { display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13, fontWeight: 500, color: 'var(--text3)' };
  const input = (k, label, extra) => <label style={field}>{label}
    <input className="tv-input" value={form[k]} onChange={e => set(k, e.target.value)} {...(extra || {})} />
  </label>;
  return <div className="tv-card" style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
      <span style={PRP_SECTION}>Add a manual perp trade · venues without a feed</span>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
      <label style={field}>Symbol
        <input className="tv-input" list="prp-ticker-options" value={form.ticker} placeholder="e.g. BTC"
          onChange={e => set('ticker', e.target.value)} />
        <datalist id="prp-ticker-options">{(tickers || []).map(x => <option key={x} value={x} />)}</datalist>
      </label>
      <label style={field}>Side
        <select className="tv-select" value={form.direction} onChange={e => set('direction', e.target.value)}>
          <option value="long">Long</option>
          <option value="short">Short</option>
        </select>
      </label>
      {input('leverage', 'Leverage', { inputMode: 'decimal', placeholder: 'e.g. 5' })}
      {input('qty', 'Size', { inputMode: 'decimal', placeholder: 'Units' })}
      {input('entry_price', 'Entry price', { inputMode: 'decimal', placeholder: '0.00' })}
      {input('stop_price', 'Stop price', { inputMode: 'decimal', placeholder: '0.00' })}
      {input('target_price', 'Target (optional)', { inputMode: 'decimal', placeholder: '0.00' })}
      {input('venue', 'Venue', { placeholder: 'e.g. Kraken' })}
      {input('entered_at', 'Opened', { type: 'datetime-local' })}
      {input('exit_price', 'Exit price', { inputMode: 'decimal', placeholder: 'Blank if still open' })}
      {input('exited_at', 'Closed', { type: 'datetime-local', disabled: !closing, title: closing ? 'Blank = now' : 'Fill the exit price first' })}
      <label style={field}>Followed the rules?
        <select className="tv-select" value={form.followed} disabled={!closing} onChange={e => set('followed', e.target.value)}>
          <option value="">{closing ? 'Choose…' : 'Once closed'}</option>
          <option value="1">Followed</option>
          <option value="0">Deviated</option>
        </select>
      </label>
    </div>
    {closing && <label style={field}>Deviation note (optional)
      <input className="tv-input" maxLength={PRP_NOTE_MAX} value={form.deviation_note} placeholder="What was different from the plan"
        onChange={e => set('deviation_note', e.target.value)} />
    </label>}
    <label style={field}>Trade notes
      <textarea className="tv-input" rows={3} maxLength={PRP_NOTE_MAX} style={{ resize: 'vertical', fontFamily: 'inherit', fontSize: 14 }}
        value={form.notes} placeholder="Why you took it and the plan" onChange={e => set('notes', e.target.value)} />
    </label>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <button type="button" className="tv-btn primary" style={prpBtn(!valid || saving)} disabled={!valid || saving} onClick={submit}>{saving ? 'Saving…' : 'Save trade'}</button>
      <button type="button" className="tv-btn" style={prpBtn(saving)} disabled={saving} onClick={onClose}>Cancel</button>
      {!valid && problems.length > 0 && <span style={{ fontSize: 13, color: 'var(--text3)' }}>{'Needs ' + problems.join(', ') + '.'}</span>}
      {messages.map(m => <span key={m} style={{ fontSize: 13, color: 'var(--fail)' }}>{m}</span>)}
      {error && <span role="alert" style={{ fontSize: 13, color: 'var(--fail)' }}>{error}</span>}
    </div>
  </div>;
}

function PerpsTransactionsTab({ trades, sync, hide, onSaved, onJump }) {
  const [adding, setAdding] = usePRPState(false);
  const manual = trades.filter(t => t.source === 'manual');
  const head = { fontSize: 12, lineHeight: '16px', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text3)' };
  const right = { textAlign: 'right' };
  const num = (label, content) => <div className="spot-cell tv-num" data-label={label} style={{ textAlign: 'right', fontFamily: PRP_MONO }}>{content}</div>;
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
    <PerpsSyncCard sync={sync} />
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
      <span style={PRP_SECTION}>{'Manual trades · ' + (manual.length === 1 ? '1 trade' : manual.length + ' trades')}</span>
      {!adding && <button type="button" className="tv-btn" onClick={() => setAdding(true)}>+ Add manual trade</button>}
    </div>
    {adding && <PerpsManualForm onSaved={onSaved} onClose={() => setAdding(false)} />}
    {manual.length === 0
      ? <div className="tv-card" style={{ color: 'var(--text3)', padding: 20, textAlign: 'center', fontSize: 14 }}>
          No manual perp trades. Use them for venues without a fill feed.</div>
      : <div className="tv-card" style={{ padding: 0, overflow: 'hidden' }}>
          <div className="spot-grid-row spot-grid-head" style={{ ...head, gridTemplateColumns: PRP_TX_GRID, alignItems: 'end',
                                                                 padding: '12px 16px', borderBottom: PRP_HEAD_LINE }}>
            <span>Symbol</span><span>Side</span><span style={right}>Lev</span><span className="spot-pad-left">Opened → closed</span>
            <span style={right}>Size</span><span style={right}>Entry</span><span style={right}>Stop</span><span style={right}>Exit</span>
            <span className="spot-pad-left"></span>
          </div>
          {manual.map(t => {
            const lev = prpLev(t.leverage, t.leverage_type);
            const closed = t.status === 'closed';
            return <div key={t.trade_id} className="spot-grid-row" style={{ gridTemplateColumns: PRP_TX_GRID, padding: '10px 16px',
                                                                            borderBottom: PRP_LINE, fontSize: 13, color: 'var(--text2)' }}>
              <div className="spot-span" style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                <span style={{ fontWeight: 700, color: 'var(--text)', fontSize: 14 }}>{t.symbol}</span>
                <span style={{ fontSize: 12, color: 'var(--text3)' }}>{prpVenueLine(t)}</span>
              </div>
              <div className="spot-cell" data-label="Side">{prpSide(t.direction)}</div>
              {num('Leverage', lev.text)}
              <div className="spot-cell spot-pad-left" data-label="Opened → closed" style={{ color: 'var(--text3)' }}>
                {prpDate(t.opened_at) + ' → ' + (closed ? prpDate(t.closed_at) : 'open')}</div>
              {num('Size', prpSize(t.size_peak, hide))}
              {num('Entry', prpPx(t.avg_entry))}
              {num('Stop', t.stop ? prpPx(t.stop.px) : '—')}
              {num('Exit', closed ? prpPx(t.avg_exit) : '—')}
              <div className="spot-cell spot-pad-left">
                <button type="button" className="tv-btn" style={PRP_SMALL_BTN} onClick={() => onJump(t)}
                  aria-label={'Open the ' + t.symbol + ' ' + t.direction + ' trade in ' + (closed ? 'History' : 'Open positions')}>
                  {closed ? 'In History' : 'In Open positions'}</button>
              </div>
            </div>;
          })}
        </div>}
    <div style={{ fontSize: 13, color: 'var(--text3)' }}>
      Close, review, add notes to or delete a manual trade from its row in Open positions or History. Manual trades have no price feed, so they show no mark or unrealized P&L.
    </div>
  </div>;
}

/* ── the screen ──────────────────────────────────────────────────────── */

function prpSyncLine(sync) {
  const venues = Array.isArray(sync) ? sync : [];
  if (!venues.length) return { text: '', tip: '', warn: false };
  const oks = venues.map(v => v.last_ok_at);
  const oldest = oks.some(x => !x) ? null : oks.slice().sort((a, b) => Date.parse(a) - Date.parse(b))[0];
  const failing = venues.filter(v => v.failing && v.failing.length);
  const busy = venues.some(v => v.in_flight);
  const tip = venues.map(v => v.venue + ': ' + (v.last_ok_at ? 'last good sync ' + prpDate(v.last_ok_at, true) : 'not synced yet')
    + (v.failing && v.failing.length ? ' · last attempt failed for ' + v.failing.join(', ') : '')).join('\n');
  const text = busy ? 'Syncing fills…' : oldest ? 'Fills synced ' + prpAgo(oldest) : 'Fills not synced yet';
  return { text: text + (failing.length ? ' · a sync failed' : ''), tip, warn: failing.length > 0 };
}

function PerpsScreen({ hideValues, refreshTrigger }) {
  const [data, setData] = usePRPState(null);
  const [loading, setLoading] = usePRPState(false);
  const [loadError, setLoadError] = usePRPState(null);
  const [updateError, setUpdateError] = usePRPState(null);
  const [updatedAt, setUpdatedAt] = usePRPState(null);
  const [expanded, setExpanded] = usePRPState({});
  const [tab, setTabState] = usePRPState(() => {
    const v = prpReadLocal('perpsSubTab', 'open');
    return PRP_TABS.some(t => t.id === v) ? v : 'open';
  });
  const reqRef = usePRPRef(0);
  const hasDataRef = usePRPRef(false);
  const coldTimerRef = usePRPRef(null);
  const coldCountRef = usePRPRef(0);
  const firstRef = usePRPRef(true);

  function setTab(v) { setTabState(v); prpWriteLocal('perpsSubTab', v); }

  function load() {
    const mine = ++reqRef.current;
    setLoading(true);
    api('/api/trading/trades').then(d => {
      if (mine !== reqRef.current) return;
      if (!d || !Array.isArray(d.trades) || !d.summary) throw new Error('Unexpected response');
      hasDataRef.current = true;
      setData(d);
      setLoadError(null);
      setUpdateError(null);
      setUpdatedAt(new Date());
      setLoading(false);
      const s = d.summary;
      window.dispatchEvent(new CustomEvent('trades-attention', { detail: {
        spot: Number((s.spot || {}).exit_signal_count) || 0,
        perp: (Number((s.perp || {}).needs_stop_count) || 0) + (Number((s.perp || {}).needs_review_count) || 0) } }));
      const cold = d.trades.some(t => t.market === 'perp' && t.source !== 'manual' && t.status !== 'closed'
                                      && (t.live === null || t.unrealized_pnl === null));
      if (cold && coldCountRef.current < PRP_COLD_RETRY_MAX) {
        coldCountRef.current += 1;
        clearTimeout(coldTimerRef.current);
        coldTimerRef.current = setTimeout(load, PRP_COLD_RETRY_MS);
      }
    }).catch(e => {
      if (mine !== reqRef.current) return;
      setLoading(false);
      if (hasDataRef.current) setUpdateError(prpErr(e));
      else setLoadError(prpErr(e));
    });
  }

  usePRPEffect(() => {
    load();
    return () => {
      reqRef.current += 1;              // late answers are ignored after unmount
      clearTimeout(coldTimerRef.current);
    };
  }, []);

  usePRPEffect(() => {
    if (firstRef.current) { firstRef.current = false; return; }
    load();
  }, [refreshTrigger]);

  function toggle(id) { setExpanded(x => Object.assign({}, x, { [id]: !x[id] })); }
  // From the Transactions list: open the trade's row where it lives (an older
  // closed trade turns on History's Show earlier first) and scroll to it.
  function jump(t) {
    const closed = t.status === 'closed';
    if (closed && t.before_rule) prpWriteLocal('perpsHistoryEarlier', '1');
    setExpanded(x => Object.assign({}, x, { [t.trade_id]: true }));
    setTab(closed ? 'history' : 'open');
    setTimeout(() => {
      const el = document.getElementById('prp-row-' + t.trade_id);
      if (el && el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 60);
  }

  const title = <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
    <h1 style={{ margin: 0, fontSize: 20, lineHeight: '26px', fontWeight: 700, color: 'var(--text)' }}>Perps</h1>
    <div style={{ fontSize: 13, lineHeight: '18px', color: 'var(--text3)' }}>Hyperliquid and TxFlow trades, built from your fills, plus trades you enter by hand.</div>
  </div>;

  if (!data && loadError) {
    return <div>
      <div style={{ marginBottom: 16 }}>{title}</div>
      <div className="tv-card" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span role="alert" style={{ color: 'var(--fail)', fontSize: 14 }}>{"Couldn't load trades: " + loadError}</span>
        <button type="button" className="tv-btn" style={prpBtn(loading)} disabled={loading} onClick={load}>Retry</button>
      </div>
    </div>;
  }
  if (!data) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 240, gap: 10, color: 'var(--text3)', fontSize: 14 }}>
      <span style={{ display: 'inline-block', animation: 'spin 0.8s linear infinite', fontSize: 18 }}>↻</span>
      Loading trades…
    </div>;
  }

  const perps = data.trades.filter(t => t.market === 'perp');
  const openTrades = perps.filter(t => t.status !== 'closed');
  const closedTrades = perps.filter(t => t.status === 'closed');
  const untracked = Array.isArray(data.untracked_positions) ? data.untracked_positions : [];
  const unattached = Array.isArray(data.unattached_annotations) ? data.unattached_annotations : [];
  const gateStart = (data.summary.gate && data.summary.gate.start) || null;
  const sync = prpSyncLine(data.sync);
  const updatedText = updatedAt ? 'Updated ' + String(updatedAt.getHours()).padStart(2, '0') + ':' + String(updatedAt.getMinutes()).padStart(2, '0') : '';
  const attention = { open: openTrades.filter(t => t.attention === 'needs_stop').length,
                      history: closedTrades.filter(t => t.attention === 'needs_review').length };

  return <div>
    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
      {title}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', fontSize: 13 }}>
        {updateError && <span role="alert" style={{ color: 'var(--fail)' }}>{'Update failed: ' + updateError}</span>}
        {sync.text && <span title={sync.tip} style={{ color: sync.warn ? 'var(--warn)' : 'var(--text3)' }}>{sync.text}</span>}
        <span style={{ color: 'var(--text3)' }}>{loading ? 'Updating…' : updatedText}</span>
        <button type="button" className="tv-btn" style={prpBtn(loading, { fontSize: 13 })} disabled={loading} onClick={load}>Reload</button>
      </div>
    </div>

    <PerpsCards summary={data.summary} openTrades={openTrades} hide={hideValues} />

    <div role="group" aria-label="Perps sections" style={{ display: 'flex', gap: 4, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
      {PRP_TABS.map(t => <button key={t.id} type="button" className="tv-btn" aria-pressed={tab === t.id}
        style={{ background: tab === t.id ? 'var(--panel3)' : 'transparent', borderColor: tab === t.id ? 'var(--accent-line)' : 'var(--line)',
                 color: tab === t.id ? 'var(--text)' : 'var(--text3)', fontWeight: tab === t.id ? 600 : 400 }}
        onClick={() => setTab(t.id)}>
        {t.label}
        {attention[t.id] > 0 && <span className="tv-chip warn" style={{ marginLeft: 6, fontSize: 11, padding: '0 6px' }}
          aria-label={attention[t.id] + (t.id === 'open' ? ' need a stop' : ' need review')}
          title={t.id === 'open' ? 'Needs a stop' : 'Needs review'}>{attention[t.id]}</span>}
      </button>)}
    </div>

    {tab === 'open' && <PerpsOpenTab trades={openTrades} untracked={untracked} expanded={expanded} onToggle={toggle}
      hide={hideValues} onSaved={load} />}
    {tab === 'history' && <PerpsHistoryTab trades={closedTrades} expanded={expanded} onToggle={toggle} hide={hideValues}
      onSaved={load} gateStart={gateStart} unattached={unattached} />}
    {tab === 'transactions' && <PerpsTransactionsTab trades={perps} sync={data.sync} hide={hideValues} onSaved={load} onJump={jump} />}

    {tab !== 'transactions' && <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 12 }}>
      Perp fills sync every 10 minutes while the app is open, and every 2 hours otherwise. Trades on venues without a feed are added by hand on the Transactions tab.
    </div>}
  </div>;
}

window.PerpsScreen = PerpsScreen;
