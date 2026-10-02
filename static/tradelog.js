/* ===== TRADE LOG SCREEN (HANDOFF_trading_performance.md rulings 2, 9, 10, 12, 14) =====
   Built on GET /api/trading/trades: spot trades from spot_transactions,
   Hyperliquid and TxFlow perp trades from the stored fills, and manual
   trades from spot_trade_log, each with its effective stop, R, attention and
   gate verdict. Spot unrealized P&L comes from GET /api/spot/pnl.

   Writes:
     spot / perp trades: PUT /api/trading/trades/<trade_id>/annotation
     manual trades:      POST / PUT / DELETE /api/spot/trade-log[/<id>]

   House theme (tv-* classes, CSS variables), JSX + Babel standalone. Every
   number in the API response is a string; it is parsed only for display.
   Trades tagged long_term / bot_capital (book !== 'trading') are left out of
   this page (ruling 2). The scanner snapshot (ruling 13) is parked.

   Glenn's Oct 2 rulings: the 1% -> 2% risk gate is perps-only (spot trades'
   gate reason is 'spot'), and spot has no price stops - its exit is the
   token's weekly trend on the Trends scanner flipping bearish
   (trade.weekly_trend; attention 'exit_signal'). */
const { useState: useTLState, useEffect: useTLEffect, useRef: useTLRef } = React;

const TL_COLD_RETRY_MS = 15000;      // re-read while open perps still lack unrealized P&L (cold caches)
const TL_COLD_RETRY_MAX = 4;         // at most this many such re-reads per mount
const TL_SAVED_MS = 3000;            // how long "Saved" stays
const TL_NOTE_MAX = 2000;
const TL_LINE = '1px solid rgba(255,255,255,0.25)';
const TL_HEAD_LINE = '2px solid rgba(255,255,255,0.35)';
const TL_MONO = "'Fira Code', monospace";
// The page font (style.css body), for words inside a monospace number cell.
const TL_SANS = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif";

const TL_STOP_SOURCE = {
  manual: 'Entered here',
  hl_order: 'Hyperliquid stop order',
  txflow_order: 'TxFlow stop order',
  txflow_tpsl: 'TxFlow position stop',
  manual_log: 'Manual log',
};

const TL_GATE_SHORT = {
  open: 'Open',
  before_rule: 'Before the rule',
  not_trading_book: 'Tagged holding',
  needs_review: 'Needs review',
  deviated: 'Deviated',
  no_stop: 'No stop',
  stop_after_close: 'Stop set after close',
  spot: 'Not gated',
  no_r: 'No R',
};

const TL_GATE_LONG = {
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

const TL_FLAGS = {
  orphan_sell: 'Sell with no open buy',
  after_close_sell: 'Sold more after the close',
  funding_approx: 'Funding approximate',
  funding_missing: 'Funding not recorded',
  stop_missing: 'No stop order found',
  liquidated: 'Liquidated',
  flip_split: 'Flipped direction',
  chain_gap: 'Fill history gap',
};

/* ── display helpers ─────────────────────────────────────────────────── */

function _tlNum(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return isFinite(n) ? n : null;
}

function _tlUsd(v, hide, signed) {
  if (hide) return '••••';
  const n = _tlNum(v);
  if (n === null) return '—';
  const abs = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (abs === '0.00') return '$0.00';
  if (n < 0) return '-$' + abs;
  return (signed ? '+$' : '$') + abs;
}

function _tlPx(v) {
  const n = _tlNum(v);
  if (n === null) return '—';
  if (n > 0 && n < 0.01) return window.fmtPrice(n);
  return '$' + n.toLocaleString('en-US', { maximumSignificantDigits: 6 });
}

function _tlSize(v, hide) {
  if (hide) return '••••';
  const n = _tlNum(v);
  if (n === null) return '—';
  return n.toLocaleString('en-US', { maximumSignificantDigits: 6 });
}

function _tlR(v) {
  const n = _tlNum(v);
  if (n === null) return '—';
  return (n > 0 ? '+' : '') + n.toFixed(2) + 'R';
}

function _tlDate(v, withTime) {
  if (!v) return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(v));
  // A bare date (spot trades) is a local calendar day, so it never shows the previous day west of UTC.
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(v);
  if (isNaN(d.getTime())) return String(v);
  const opts = { month: 'short', day: 'numeric' };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
  let s = d.toLocaleDateString('en-US', opts);
  if (withTime && !m) {
    s += ', ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  return s;
}

function _tlColor(v) {
  const n = _tlNum(v);
  if (n === null || n === 0) return 'var(--text2)';
  return n > 0 ? 'var(--ok)' : 'var(--fail)';
}

function _tlMoneyColor(v, hide) {
  // Hidden amounts stay neutral so the color does not give away gain or loss.
  return hide ? 'var(--text2)' : _tlColor(v);
}

function _tlErr(e) {
  const text = (e && e.message) || String(e || 'Request failed');
  let out = text;
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed.error === 'string') out = parsed.error;
  } catch (err) { /* not JSON: keep the text */ }
  return out.length > 200 ? out.slice(0, 200) : out;
}

function _tlPositive(s) {
  const t = String(s || '').trim();
  if (t === '') return false;
  const n = Number(t);
  return isFinite(n) && n > 0;
}

function _tlOneR(t) {
  // 1R = |avg entry - stop| x peak size; null when it cannot be computed or is 0.
  const entry = _tlNum(t.avg_entry);
  const stop = t.stop ? _tlNum(t.stop.px) : null;
  const size = _tlNum(t.size_peak);
  if (entry === null || stop === null || size === null) return null;
  const r = Math.abs(entry - stop) * size;
  return r > 0 ? r : null;
}

function _tlVenueLine(t) {
  if (t.source === 'manual') {
    return (!t.venue || t.venue === 'Manual') ? 'Manual entry' : 'Manual · ' + t.venue;
  }
  if (t.source === 'spot_tx') return '';
  return (!t.wallet_label || t.wallet_label === t.venue) ? t.venue : t.venue + ' · ' + t.wallet_label;
}

function _tlBtn(disabled, extra) {
  // tv-btn has no disabled style of its own.
  return Object.assign({}, extra || {}, { opacity: disabled ? 0.5 : 1, cursor: disabled ? 'default' : 'pointer' });
}

function _tlNowLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

function _tlLocalToIso(value) {
  if (!value) return null;
  const d = new Date(value);
  return isNaN(d.getTime()) ? null : d.toISOString();
}

function _tlTextOrNull(s) {
  return String(s || '').trim() === '' ? null : s;
}

/* ── small pieces ────────────────────────────────────────────────────── */

function TLMarketCell({ trade }) {
  const sub = _tlVenueLine(trade);
  return <div>
    {trade.market === 'perp'
      ? <span className="tv-chip adapt">Perp</span>
      : <span className="tv-chip accent">Spot</span>}
    {sub && <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 3, whiteSpace: 'nowrap' }}>{sub}</div>}
  </div>;
}

function TLSymbolCell({ trade }) {
  const hasNotes = !!(trade.annotation && trade.annotation.notes && String(trade.annotation.notes).trim());
  return <span style={{ fontWeight: 700, color: 'var(--text)' }}>
    {trade.symbol}
    {hasNotes && <span title="Has notes" style={{ marginLeft: 6, color: 'var(--text3)', fontWeight: 400 }}>✎</span>}
  </span>;
}

function TLSideCell({ trade }) {
  const long = trade.direction === 'long';
  const text = trade.direction ? trade.direction.charAt(0).toUpperCase() + trade.direction.slice(1) : '—';
  return <span style={{ color: long ? 'var(--ok)' : (trade.direction === 'short' ? 'var(--fail)' : 'var(--text2)') }}>{text}</span>;
}

function TLStopShown({ stop }) {
  const label = TL_STOP_SOURCE[stop.source] || stop.source;
  return <div title={label + ' · set ' + _tlDate(stop.set_at, true)}>
    <div style={{ fontFamily: TL_MONO }}>{_tlPx(stop.px)}</div>
    <div style={{ fontSize: 11, color: 'var(--text3)', fontFamily: TL_SANS }}>{label}</div>
  </div>;
}

const TL_WEEKLY = {
  BULLISH: { text: '▲ Weekly bullish', color: 'var(--ok)' },
  BEARISH: { text: '▼ Weekly bearish', color: 'var(--fail)' },
  WARMUP: { text: 'Weekly neutral', color: 'var(--text3)' },
};
const TL_NOT_IN_SCANNER = "The Trends scanner reads Hyperliquid perp markets; this token isn't one of them, so its weekly trend can't be tracked here.";

function TLWeeklyShown({ wt }) {
  if (!wt) return '—';
  const w = TL_WEEKLY[wt.state];
  if (!w) {
    return <span title={TL_NOT_IN_SCANNER} style={{ fontSize: 12, color: 'var(--text3)', fontFamily: TL_SANS }}>Not in scanner</span>;
  }
  return <div title={'Trends scanner, weekly · as of ' + _tlDate(wt.as_of, true)} style={{ fontFamily: TL_SANS }}>
    <div style={{ fontSize: 13, color: w.color, whiteSpace: 'nowrap' }}>{w.text}</div>
    {wt.flipped_at && <div style={{ fontSize: 11, color: 'var(--text3)' }}>since {_tlDate(wt.flipped_at)}</div>}
  </div>;
}

function TLFact({ label, children, mono, color }) {
  return <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12,
                       padding: '6px 0', borderBottom: TL_LINE }}>
    <span style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text3)' }}>{label}</span>
    <span style={{ fontSize: 13, color: color || 'var(--text2)', fontFamily: mono ? TL_MONO : 'inherit', textAlign: 'right' }}>{children}</span>
  </div>;
}

function TLStatus({ saving, status }) {
  if (saving) return <span style={{ fontSize: 13, color: 'var(--text3)' }}>Saving…</span>;
  if (status === 'saved') return <span style={{ fontSize: 13, color: 'var(--ok)' }}>Saved</span>;
  if (status && status.error) return <span style={{ fontSize: 13, color: 'var(--fail)' }}>{status.error}</span>;
  return null;
}

/* ── one trade: main row, error row, detail row ──────────────────────── */

function _tlUseFollowingDraft(stored) {
  // A text draft starts from the stored value and follows it when the stored
  // value changes, unless the user has an unsaved edit.
  const [draft, setDraft] = useTLState(stored);
  const prevRef = useTLRef(stored);
  useTLEffect(() => {
    const prev = prevRef.current;
    if (stored !== prev) {
      setDraft(d => (d === prev || d === stored) ? stored : d);
      prevRef.current = stored;
    }
  }, [stored]);
  return [draft, setDraft];
}

function TLTradeRow({ trade, kind, cols, expanded, onToggle, onExpand, hide, spotRow, onSaved, gateStart }) {
  const isManual = trade.source === 'manual';
  const ann = trade.annotation || {};
  const storedDev = ann.deviation_note || '';
  const storedNotes = ann.notes || '';
  const [stopDraft, setStopDraft] = useTLState('');
  const [devDraft, setDevDraft] = _tlUseFollowingDraft(storedDev);
  const [notesDraft, setNotesDraft] = _tlUseFollowingDraft(storedNotes);
  const [exitDraft, setExitDraft] = useTLState('');
  const [exitAtDraft, setExitAtDraft] = useTLState(_tlNowLocal());
  const [closeFollowed, setCloseFollowed] = useTLState('');
  const [saving, setSaving] = useTLState(false);
  const [status, setStatus] = useTLState(null);
  const aliveRef = useTLRef(true);
  const savedTimerRef = useTLRef(null);

  useTLEffect(() => () => {
    aliveRef.current = false;
    clearTimeout(savedTimerRef.current);
  }, []);

  function send(path, options) {
    setSaving(true);
    setStatus(null);
    clearTimeout(savedTimerRef.current);
    return api(path, options).then(() => {
      if (!aliveRef.current) return true;
      setSaving(false);
      setStatus('saved');
      savedTimerRef.current = setTimeout(() => { if (aliveRef.current) setStatus(null); }, TL_SAVED_MS);
      onSaved();
      return true;
    }).catch(e => {
      if (aliveRef.current) {
        setSaving(false);
        setStatus({ error: _tlErr(e) });
      }
      return false;
    });
  }

  function saveAnnotation(body) {
    return send('/api/trading/trades/' + encodeURIComponent(trade.trade_id) + '/annotation',
                { method: 'PUT', body: JSON.stringify(body) });
  }

  function saveManual(body) {
    return send('/api/spot/trade-log/' + trade.manual_id, { method: 'PUT', body: JSON.stringify(body) });
  }

  function saveStop() {
    if (saving || isManual || !_tlPositive(stopDraft)) return;
    saveAnnotation({ stop_px: stopDraft.trim() }).then(ok => { if (ok && aliveRef.current) setStopDraft(''); });
  }

  function clearStop() {
    if (saving || isManual) return;
    saveAnnotation({ stop_px: null });
  }

  function saveFollowed(value) {
    if (saving) return;
    if (isManual) saveManual({ followed_rules: value ? 1 : 0 });
    else saveAnnotation({ followed_rules: value });
  }

  function saveTexts() {
    if (saving) return;
    const body = { deviation_note: _tlTextOrNull(devDraft), notes: _tlTextOrNull(notesDraft) };
    const req = isManual ? saveManual(body) : saveAnnotation(body);
    req.then(ok => {
      if (ok && aliveRef.current) {
        setDevDraft(body.deviation_note || '');
        setNotesDraft(body.notes || '');
      }
    });
  }

  function closeManual() {
    if (saving || !_tlPositive(exitDraft) || closeFollowed === '') return;
    saveManual({
      exit_price: Number(exitDraft.trim()),
      exited_at: _tlLocalToIso(exitAtDraft),
      followed_rules: Number(closeFollowed),
      deviation_note: _tlTextOrNull(devDraft),
    });
  }

  function deleteManual() {
    if (saving) return;
    const ok = window.confirm('Delete the manual ' + trade.symbol + ' trade logged ' + _tlDate(trade.opened_at) +
                              "? This can't be undone.");
    if (!ok) return;
    send('/api/spot/trade-log/' + trade.manual_id, { method: 'DELETE' });
  }

  const followed = ann.followed_rules;
  const td = { padding: '10px 10px', borderBottom: TL_LINE, verticalAlign: 'top' };
  const tdNum = Object.assign({}, td, { textAlign: 'right', fontFamily: TL_MONO, whiteSpace: 'nowrap' });
  const first = Object.assign({}, td, trade.attention ? { boxShadow: 'inset 3px 0 0 var(--warn)' } : {});
  const stopValid = _tlPositive(stopDraft);

  let stopCell;
  if (kind === 'open' && trade.market === 'spot') {
    // Spot has no price stops (Oct 2 ruling R2): its exit is the weekly trend.
    stopCell = <TLWeeklyShown wt={trade.weekly_trend} />;
  } else if (trade.stop) {
    stopCell = <TLStopShown stop={trade.stop} />;
  } else if (kind === 'open' && trade.market === 'perp' && !isManual) {
    stopCell = <div style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
      <input className="tv-input" style={{ width: 96, padding: '5px 8px', fontFamily: TL_MONO }} inputMode="decimal"
             placeholder="Stop" value={stopDraft} disabled={saving}
             onChange={e => setStopDraft(e.target.value)}
             onKeyDown={e => { if (e.key === 'Enter') saveStop(); }} />
      <button className="tv-btn" style={_tlBtn(!stopValid || saving, { padding: '5px 10px' })}
              disabled={!stopValid || saving} onClick={saveStop}>Save</button>
    </div>;
  } else {
    stopCell = '—';
  }

  const toggleBtn = <button className="tv-btn" style={{ padding: '5px 10px', whiteSpace: 'nowrap' }}
                            aria-expanded={expanded} onClick={() => onToggle(trade.trade_id)}>
    {expanded ? 'Hide ▴' : 'Details ▾'}
  </button>;

  let cells;
  if (kind === 'open') {
    let unrealized = null;
    if (trade.source === 'spot_tx') unrealized = spotRow ? spotRow.unrealized_pnl_usd : null;
    else if (trade.market === 'perp' && !isManual) unrealized = trade.unrealized_pnl;
    const oneR = _tlOneR(trade);
    const unrealizedN = _tlNum(unrealized);
    const realizedN = _tlNum(trade.net_pnl);
    cells = [
      <td key="m" style={first}><TLMarketCell trade={trade} /></td>,
      <td key="s" style={td}><TLSymbolCell trade={trade} /></td>,
      <td key="d" style={td}><TLSideCell trade={trade} /></td>,
      <td key="o" style={Object.assign({}, td, { whiteSpace: 'nowrap' })}>{_tlDate(trade.opened_at, true)}</td>,
      <td key="z" style={tdNum}>{_tlSize(trade.size_peak, hide)}</td>,
      <td key="e" style={tdNum}>{_tlPx(trade.avg_entry)}</td>,
      <td key="st" style={tdNum}>{stopCell}</td>,
      <td key="u" style={tdNum}>
        {isManual ? '—' : <span style={{ color: _tlMoneyColor(unrealizedN, hide) }}>{_tlUsd(unrealizedN, hide, true)}</span>}
        {!isManual && trade.status === 'open' && trade.stop && oneR !== null && unrealizedN !== null &&
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>≈ {_tlR(unrealizedN / oneR)}</div>}
      </td>,
      <td key="r" style={tdNum}>
        {realizedN === null || realizedN === 0 ? '—'
          : <span style={{ color: _tlMoneyColor(realizedN, hide) }}>{_tlUsd(realizedN, hide, true)}</span>}
      </td>,
      <td key="c" style={td}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {trade.attention === 'needs_stop' && <span className="tv-chip warn">Needs stop</span>}
          {trade.attention === 'exit_signal' &&
            <span className="tv-chip fail" title="The weekly trend flipped bearish after this trade opened: your spot exit rule">Exit signal</span>}
          {trade.status === 'partly_closed' && <span className="tv-chip adapt">Partly closed</span>}
          {trade.before_rule && <TLBeforeChip gateStart={gateStart} />}
        </div>
      </td>,
      <td key="b" style={Object.assign({}, td, { textAlign: 'right' })}>{toggleBtn}</td>,
    ];
  } else {
    let review;
    if (followed === true) review = <span className="tv-chip ok">Followed</span>;
    else if (followed === false) review = <span className="tv-chip fail">Deviated</span>;
    else review = <div style={{ display: 'flex', gap: 6 }}>
      <button className="tv-btn" disabled={saving}
              style={_tlBtn(saving, { padding: '4px 8px', fontSize: 12, color: 'var(--ok)', borderColor: 'var(--ok)' })}
              onClick={() => saveFollowed(true)}>Followed</button>
      <button className="tv-btn" disabled={saving}
              style={_tlBtn(saving, { padding: '4px 8px', fontSize: 12, color: 'var(--fail)', borderColor: 'var(--fail)' })}
              onClick={() => { saveFollowed(false); onExpand(trade.trade_id); }}>Deviated</button>
    </div>;
    const g = trade.gate || {};
    cells = [
      <td key="m" style={first}><TLMarketCell trade={trade} /></td>,
      <td key="s" style={td}><TLSymbolCell trade={trade} /></td>,
      <td key="d" style={td}><TLSideCell trade={trade} /></td>,
      <td key="o" style={Object.assign({}, td, { whiteSpace: 'nowrap' })}>
        {_tlDate(trade.opened_at)} → {_tlDate(trade.closed_at)}
      </td>,
      <td key="e" style={tdNum}>
        {_tlPx(trade.avg_entry)}
        <div style={{ fontSize: 12, color: 'var(--text3)' }}>→ {_tlPx(trade.avg_exit)}</div>
      </td>,
      <td key="st" style={tdNum}>{stopCell}</td>,
      <td key="n" style={Object.assign({}, tdNum, { color: _tlMoneyColor(trade.net_pnl, hide) })}>{_tlUsd(trade.net_pnl, hide, true)}</td>,
      <td key="r" style={Object.assign({}, tdNum, { color: _tlColor(trade.r_multiple) })}>
        {_tlR(trade.r_multiple)}{trade.r_multiple !== null && trade.r_basis === 'price' ? '*' : ''}
      </td>,
      <td key="v" style={td}>{review}</td>,
      <td key="g" style={td}>
        {g.eligible ? <span className="tv-chip ok">Counts</span>
          : <span style={{ fontSize: 13, color: 'var(--text3)' }}>{TL_GATE_SHORT[g.reason] || g.reason || '—'}</span>}
      </td>,
      <td key="b" style={Object.assign({}, td, { textAlign: 'right' })}>{toggleBtn}</td>,
    ];
  }

  const showErrorRow = !expanded && status && status.error;

  return <React.Fragment>
    <tr style={expanded ? { background: 'var(--panel2)' } : undefined}>{cells}</tr>
    {showErrorRow && <tr>
      <td colSpan={cols} style={{ padding: '6px 10px', borderBottom: TL_LINE, color: 'var(--fail)', fontSize: 13 }}>
        {status.error}
      </td>
    </tr>}
    {expanded && <tr style={{ background: 'var(--panel2)' }}>
      <td colSpan={cols} style={{ padding: 12, borderBottom: TL_LINE }}>
        <TLDetail trade={trade} hide={hide} isManual={isManual} saving={saving} status={status}
                  stopDraft={stopDraft} setStopDraft={setStopDraft} saveStop={saveStop} clearStop={clearStop}
                  devDraft={devDraft} setDevDraft={setDevDraft} notesDraft={notesDraft} setNotesDraft={setNotesDraft}
                  storedDev={storedDev} storedNotes={storedNotes} saveTexts={saveTexts} saveFollowed={saveFollowed}
                  exitDraft={exitDraft} setExitDraft={setExitDraft} exitAtDraft={exitAtDraft}
                  setExitAtDraft={setExitAtDraft} closeFollowed={closeFollowed} setCloseFollowed={setCloseFollowed}
                  closeManual={closeManual} deleteManual={deleteManual} />
      </td>
    </tr>}
  </React.Fragment>;
}

function TLBeforeChip({ gateStart }) {
  const start = gateStart ? _tlDate(gateStart) : 'the gate start';
  return <span className="tv-chip" style={{ color: 'var(--text3)', borderColor: 'rgba(255,255,255,0.35)' }}>
    Before {start}
  </span>;
}

function TLDetail(p) {
  const t = p.trade;
  const isClosed = t.status === 'closed';
  const oneR = _tlOneR(t);
  const flags = t.flags || [];
  const g = t.gate || {};
  const dirty = p.devDraft !== p.storedDev || p.notesDraft !== p.storedNotes;
  const stopValid = _tlPositive(p.stopDraft);
  const followed = (t.annotation || {}).followed_rules;
  const label = { fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text3)', marginBottom: 6 };
  const hint = { fontSize: 12, color: 'var(--text3)', marginTop: 6 };
  const section = { marginBottom: 16 };
  let funding = null;
  if (t.funding !== null && t.funding !== undefined) {
    funding = _tlUsd(t.funding, p.hide, true);
    if (flags.indexOf('funding_missing') >= 0) funding += ' (not recorded)';
    else if (flags.indexOf('funding_approx') >= 0) funding += ' (approximate)';
  }
  const feeEffect = (t.fees !== null && t.fees !== undefined) ? -(_tlNum(t.fees) || 0) : null;
  const isSpot = t.market === 'spot';
  const wt = t.weekly_trend;
  const weeklyStyle = wt ? TL_WEEKLY[wt.state] : null;

  function reviewBtn(value, text, color) {
    const active = followed === value;
    const style = _tlBtn(p.saving, {
      padding: '5px 12px',
      color: active ? 'var(--bg)' : color,
      borderColor: color,
      background: active ? color : 'transparent',
      fontWeight: active ? 700 : 400,
    });
    return <button className="tv-btn" style={style} disabled={p.saving} onClick={() => p.saveFollowed(value)}>{text}</button>;
  }

  return <div style={{ background: 'var(--bg)', border: '1px solid var(--line)', borderRadius: 8, padding: 16,
                       display: 'grid', gridTemplateColumns: 'minmax(260px,1fr) minmax(320px,1.4fr)', gap: 20 }}>
    <div>
      <TLFact label="Venue">{t.source === 'spot_tx' ? 'Spot wallets' : _tlVenueLine(t)}</TLFact>
      <TLFact label="Opened">{_tlDate(t.opened_at, true)}</TLFact>
      <TLFact label="Closed">{t.closed_at ? _tlDate(t.closed_at, true) : 'Open'}</TLFact>
      <TLFact label="Peak size" mono>{_tlSize(t.size_peak, p.hide)}</TLFact>
      <TLFact label="Avg entry" mono>{_tlPx(t.avg_entry)}</TLFact>
      <TLFact label="Avg exit" mono>{_tlPx(t.avg_exit)}</TLFact>
      <TLFact label={isClosed ? 'Net P&L' : 'Realized so far'} mono color={_tlMoneyColor(t.net_pnl, p.hide)}>
        {_tlUsd(t.net_pnl, p.hide, true)}
      </TLFact>
      {feeEffect !== null && <TLFact label="Fees" mono color={_tlMoneyColor(feeEffect, p.hide)}>{_tlUsd(feeEffect, p.hide, true)}</TLFact>}
      {funding !== null && <TLFact label="Funding" mono color={_tlMoneyColor(t.funding, p.hide)}>{funding}</TLFact>}
      {oneR !== null && <TLFact label="1R (peak size to stop)" mono>{_tlUsd(oneR, p.hide)}</TLFact>}
      {t.r_multiple !== null && t.r_multiple !== undefined &&
        <TLFact label="R" mono color={_tlColor(t.r_multiple)}>
          {_tlR(t.r_multiple)}{t.r_basis === 'price' ? ' (price-based)' : ''}
        </TLFact>}
      {_tlNum(t.after_close_realized) !== null && _tlNum(t.after_close_realized) !== 0 &&
        <TLFact label="Sold after close" mono color={_tlMoneyColor(t.after_close_realized, p.hide)}>
          {_tlUsd(t.after_close_realized, p.hide, true)}
        </TLFact>}
      <TLFact label="Gate" color={g.eligible ? 'var(--ok)' : 'var(--text2)'}>
        {isSpot ? TL_GATE_LONG.spot
          : g.eligible ? 'Counts toward the gate' : (TL_GATE_LONG[g.reason] || g.reason || '—')}
      </TLFact>
      {flags.length > 0 && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
        {flags.map(f => <span key={f} className="tv-chip warn">{TL_FLAGS[f] || f}</span>)}
      </div>}
    </div>

    <div>
      {isSpot ? <div style={section}>
        <div style={label}>Exit rule</div>
        <div style={{ fontSize: 13, color: 'var(--text2)', marginBottom: 6 }}>The weekly trend flips bearish (Trends scanner).</div>
        {!weeklyStyle
          ? <div style={{ fontSize: 13, color: 'var(--text3)' }}>{TL_NOT_IN_SCANNER}</div>
          : <div style={{ fontSize: 13, color: 'var(--text2)' }}>
              <span style={{ color: weeklyStyle.color }}>{weeklyStyle.text}</span>
              {wt.flipped_at ? ' since ' + _tlDate(wt.flipped_at) : ''}
              {t.exit_signal && <span style={{ color: 'var(--fail)', fontWeight: 700 }}> · exit signal: it flipped after you opened</span>}
              {!t.exit_signal && wt.state === 'BEARISH' && !isClosed &&
                <span style={{ color: 'var(--text3)' }}> · already bearish when you opened</span>}
            </div>}
        {t.stop && <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 6 }}>
          Recorded stop: <span style={{ fontFamily: TL_MONO }}>{_tlPx(t.stop.px)}</span>
          {' · ' + (TL_STOP_SOURCE[t.stop.source] || t.stop.source)}
        </div>}
      </div> : <div style={section}>
        <div style={label}>Stop</div>
        <div style={{ fontSize: 13, color: 'var(--text2)', marginBottom: 8 }}>
          {t.stop
            ? <span><span style={{ fontFamily: TL_MONO }}>{_tlPx(t.stop.px)}</span>
                {' · ' + (TL_STOP_SOURCE[t.stop.source] || t.stop.source) + ' · set ' + _tlDate(t.stop.set_at, true)}</span>
            : 'No stop recorded.'}
        </div>
        {!p.isManual && <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <input className="tv-input" style={{ width: 160, fontFamily: TL_MONO }} inputMode="decimal" placeholder="Stop price"
                 value={p.stopDraft} disabled={p.saving} onChange={e => p.setStopDraft(e.target.value)}
                 onKeyDown={e => { if (e.key === 'Enter') p.saveStop(); }} />
          <button className="tv-btn primary" style={_tlBtn(!stopValid || p.saving)} disabled={!stopValid || p.saving}
                  onClick={p.saveStop}>Save stop</button>
          {t.stop && t.stop.source === 'manual' &&
            <button className="tv-btn" style={_tlBtn(p.saving)} disabled={p.saving} onClick={p.clearStop}>Clear</button>}
        </div>}
        <div style={hint}>
          {p.isManual ? 'Manual trades keep the stop they were logged with.'
            : isClosed ? 'Entered after the close, a stop gives this trade an R but it will not count toward the gate.'
            : 'A stop entered here replaces the venue stop for R and the gate.'}
        </div>
      </div>}

      {p.isManual && !isClosed
        ? <div style={section}>
            <div style={label}>Close this trade</div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <input className="tv-input" style={{ width: 140, fontFamily: TL_MONO }} inputMode="decimal" placeholder="Exit price"
                     value={p.exitDraft} disabled={p.saving} onChange={e => p.setExitDraft(e.target.value)} />
              <input className="tv-input" type="datetime-local" style={{ width: 210 }} value={p.exitAtDraft}
                     disabled={p.saving} onChange={e => p.setExitAtDraft(e.target.value)} />
              <select className="tv-select" value={p.closeFollowed} disabled={p.saving} required
                      onChange={e => p.setCloseFollowed(e.target.value)}>
                <option value="">Followed the rules?</option>
                <option value="1">Followed</option>
                <option value="0">Deviated</option>
              </select>
              <button className="tv-btn primary"
                      style={_tlBtn(!_tlPositive(p.exitDraft) || p.closeFollowed === '' || p.saving)}
                      disabled={!_tlPositive(p.exitDraft) || p.closeFollowed === '' || p.saving}
                      onClick={p.closeManual}>Close trade</button>
            </div>
          </div>
        : <div style={section}>
            <div style={label}>{isSpot ? 'Followed the rules? (optional for spot)' : 'Followed the rules?'}</div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {reviewBtn(true, 'Followed', 'var(--ok)')}
              {reviewBtn(false, 'Deviated', 'var(--fail)')}
              {!p.isManual && reviewBtn(null, 'Not reviewed', 'var(--text3)')}
            </div>
          </div>}

      <div style={section}>
        <div style={label}>Deviation note</div>
        <input className="tv-input" maxLength={TL_NOTE_MAX} placeholder="What was different from the plan (optional)"
               value={p.devDraft} disabled={p.saving} onChange={e => p.setDevDraft(e.target.value)} />
      </div>

      <div style={section}>
        <div style={label}>Notes</div>
        <textarea className="tv-input" rows={6} maxLength={TL_NOTE_MAX} style={{ resize: 'vertical', fontFamily: 'inherit' }}
                  placeholder="Setup, reasons, what you would repeat or change"
                  value={p.notesDraft} disabled={p.saving} onChange={e => p.setNotesDraft(e.target.value)} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}>
          <button className="tv-btn primary" style={_tlBtn(!dirty || p.saving)} disabled={!dirty || p.saving}
                  onClick={p.saveTexts}>Save notes</button>
          {dirty && <span style={{ fontSize: 12, color: 'var(--warn)' }}>Unsaved changes</span>}
          <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text3)', fontFamily: TL_MONO }}>
            {p.notesDraft.length} / {TL_NOTE_MAX}
          </span>
        </div>
      </div>

      {p.isManual && <div style={section}>
        <button className="tv-btn danger" style={_tlBtn(p.saving)} disabled={p.saving} onClick={p.deleteManual}>
          Delete manual trade
        </button>
      </div>}

      <TLStatus saving={p.saving} status={p.status} />
    </div>
  </div>;
}

/* ── tables ──────────────────────────────────────────────────────────── */

const TL_OPEN_COLS = [
  ['Market'], ['Symbol'], ['Side'], ['Opened'], ['Peak size', 1], ['Avg entry', 1], ['Stop / exit', 1],
  ['Unrealized', 1], ['Realized', 1], ['Status'], [''],
];
const TL_CLOSED_COLS = [
  ['Market'], ['Symbol'], ['Side'], ['Opened → closed'], ['Entry → exit', 1], ['Stop', 1], ['Net P&L', 1],
  ['R', 1], ['Review'], ['Gate'], [''],
];

function TLTable({ kind, trades, expanded, onToggle, onExpand, hide, spotRows, onSaved, gateStart }) {
  const cols = kind === 'open' ? TL_OPEN_COLS : TL_CLOSED_COLS;
  return <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14, color: 'var(--text2)' }}>
    <thead>
      <tr>
        {cols.map(([h, right], i) =>
          <th key={i} style={{ textAlign: right ? 'right' : 'left', padding: '10px 10px', fontSize: 12, fontWeight: 600,
                               textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text3)',
                               borderBottom: TL_HEAD_LINE, whiteSpace: 'nowrap' }}>{h}</th>)}
      </tr>
    </thead>
    <tbody>
      {trades.map(t =>
        <TLTradeRow key={t.trade_id} trade={t} kind={kind} cols={cols.length} expanded={!!expanded[t.trade_id]}
                    onToggle={onToggle} onExpand={onExpand} hide={hide}
                    spotRow={t.position_key ? spotRows[t.position_key] : null} onSaved={onSaved}
                    gateStart={gateStart} />)}
    </tbody>
  </table>;
}

/* ── gate card and panels ────────────────────────────────────────────── */

function TLGateCard({ summary }) {
  // The perp risk gate as a verdict plus its two checks (Oct 2 rulings R1, R4).
  const gate = summary.gate || {};
  const target = Number(gate.target) || 0;
  const count = Number(gate.eligible_count) || 0;
  const unlocked = !!gate.unlocked;
  const exp = _tlNum(gate.expectancy_r);
  const dev = summary.deviated || {};
  const check = (ok, text, value) =>
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 14, color: 'var(--text2)', marginTop: 6 }}>
      <span style={{ color: ok ? 'var(--ok)' : 'var(--fail)', fontWeight: 700, width: 14 }}>{ok ? '✓' : '✗'}</span>
      <span>{text}</span>
      <span style={{ fontFamily: TL_MONO, color: 'var(--text)' }}>{value}</span>
    </div>;
  return <div className="tv-card" style={{ marginBottom: 16 }}>
    <span className="tv-label">Perp risk gate · 1% → 2%</span>
    <div style={{ fontSize: 22, fontWeight: 700, marginTop: 8, color: unlocked ? 'var(--ok)' : 'var(--warn)' }}>
      {unlocked ? '2% risk per perp trade is allowed' : 'Stay at 1% risk per perp trade'}
    </div>
    {check(count >= target, target + '+ rule-following perp trades', '(' + count + ')')}
    {check(exp !== null && exp > 0, 'Average R above 0', '(' + _tlR(gate.expectancy_r) + ')')}
    <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 10 }}>
      Counts closed perp trades opened since {_tlDate(gate.start)} that you marked Followed, with a stop placed before
      they closed. Both must be checked to move to 2%. Deviated perp trades: {dev.count || 0}
      {_tlNum(dev.avg_r) !== null ? ' (avg ' + _tlR(dev.avg_r) + ')' : ''}. Spot trades don't count.
    </div>
  </div>;
}

function TLPanel({ title, panel, market, hide, onAttention }) {
  const p = panel || {};
  const all = p.all_time || {};
  const pill = { fontSize: 12, padding: '3px 10px', cursor: 'pointer', fontFamily: 'inherit' };
  return <div className="tv-card" style={{ flex: '1 1 340px', minWidth: 0 }}>
    <div className="tv-label">{title}</div>
    <div style={{ fontSize: 24, fontWeight: 700, fontFamily: TL_MONO, color: _tlMoneyColor(p.net_pnl, hide), marginTop: 8 }}>
      {_tlUsd(p.net_pnl, hide, true)}
    </div>
    <div style={{ fontSize: 13, color: 'var(--text2)', marginTop: 6 }}>
      {p.closed_count || 0} closed · {p.win_count || 0}W / {p.loss_count || 0}L{market === 'perp' ? ' · avg ' + _tlR(p.avg_r) : ''}
    </div>
    <div style={{ fontSize: 13, color: 'var(--text2)', marginTop: 4 }}>
      {p.open_count || 0} open{p.partly_closed_count ? ' · ' + p.partly_closed_count + ' partly closed' : ''}
    </div>
    {(p.needs_stop_count > 0 || p.needs_review_count > 0 || p.exit_signal_count > 0) &&
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
      {p.needs_stop_count > 0 && <button className="tv-chip warn" style={pill} onClick={() => onAttention(market)}>
        {p.needs_stop_count === 1 ? '1 needs a stop' : p.needs_stop_count + ' need a stop'}
      </button>}
      {p.needs_review_count > 0 && <button className="tv-chip warn" style={pill} onClick={() => onAttention(market)}>
        {p.needs_review_count === 1 ? '1 needs review' : p.needs_review_count + ' need review'}
      </button>}
      {p.exit_signal_count > 0 && <button className="tv-chip fail" style={pill} onClick={() => onAttention(market)}>
        {p.exit_signal_count === 1 ? '1 exit signal' : p.exit_signal_count + ' exit signals'}
      </button>}
    </div>}
    <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 10 }}>
      All time: {all.closed_count || 0} closed · <span style={{ fontFamily: TL_MONO }}>{_tlUsd(all.net_pnl, hide, true)}</span>
    </div>
  </div>;
}

/* ── unattached annotations ──────────────────────────────────────────── */

function TLUnattached({ items }) {
  return <div className="tv-card" style={{ marginTop: 16 }}>
    <div className="tv-label">Notes no longer attached to a trade ({items.length})</div>
    <div style={{ fontSize: 13, color: 'var(--text2)', margin: '8px 0' }}>
      Their trade changed shape (for example, its first buy was edited). Nothing was deleted.
    </div>
    {items.map(a => <div key={a.trade_id} style={{ fontSize: 13, color: 'var(--text2)', padding: '6px 0', borderTop: TL_LINE }}>
      {a.market === 'perp' ? 'Perp' : 'Spot'} · last edited {_tlDate(a.updated_at, true)} ·{' '}
      {a.has_notes ? 'has notes' : 'stop or review only'}
    </div>)}
  </div>;
}

/* ── manual-trade form (ruling 12) ───────────────────────────────────── */

function _tlEmptyForm() {
  return { market: 'spot', ticker: '', direction: 'long', venue: '', entry_price: '', stop_price: '', qty: '',
           target_price: '', entered_at: _tlNowLocal(), notes: '' };
}

function TLManualForm({ onSaved }) {
  const [open, setOpen] = useTLState(false);
  const [form, setForm] = useTLState(_tlEmptyForm);
  const [tickers, setTickers] = useTLState(null);
  const [saving, setSaving] = useTLState(false);
  const [error, setError] = useTLState(null);
  const aliveRef = useTLRef(true);

  useTLEffect(() => () => { aliveRef.current = false; }, []);

  useTLEffect(() => {
    if (!open || tickers !== null) return;
    api('/api/trading/scanner/noodle-state').then(d => {
      if (!aliveRef.current) return;
      const list = (d && Array.isArray(d.symbols) ? d.symbols : []).map(s => s && s.symbol).filter(Boolean);
      setTickers(list);
    }).catch(() => { if (aliveRef.current) setTickers([]); });
  }, [open]);

  function set(k, v) { setForm(f => Object.assign({}, f, { [k]: v })); }

  const entry = Number(form.entry_price);
  const stop = Number(form.stop_price);
  const sameEntryStop = _tlPositive(form.entry_price) && _tlPositive(form.stop_price) && entry === stop;
  const targetOk = String(form.target_price).trim() === '' || _tlPositive(form.target_price);
  const valid = form.ticker.trim() !== '' && _tlPositive(form.entry_price) && _tlPositive(form.stop_price) &&
                _tlPositive(form.qty) && !sameEntryStop && targetOk;

  function submit() {
    if (!valid || saving) return;
    setSaving(true);
    setError(null);
    const body = {
      ticker: form.ticker.trim(),
      direction: form.direction,
      market: form.market,
      source: 'manual',
      venue: form.venue.trim() || null,
      entry_price: entry,
      stop_price: stop,
      qty: Number(form.qty),
      target_price: String(form.target_price).trim() === '' ? null : Number(form.target_price),
      entered_at: _tlLocalToIso(form.entered_at),
      notes: _tlTextOrNull(form.notes),
    };
    api('/api/spot/trade-log', { method: 'POST', body: JSON.stringify(body) }).then(() => {
      if (!aliveRef.current) return;
      setSaving(false);
      setForm(_tlEmptyForm());
      onSaved();
    }).catch(e => {
      if (!aliveRef.current) return;
      setSaving(false);
      setError(_tlErr(e));
    });
  }

  if (!open) {
    return <div style={{ marginTop: 16 }}>
      <button className="tv-btn" onClick={() => setOpen(true)}>+ Add a manual trade</button>
    </div>;
  }

  const field = { display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12, color: 'var(--text3)' };
  return <div className="tv-card" style={{ marginTop: 16 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
      <span className="tv-label">Add a manual trade · venues without a feed</span>
      <button className="tv-btn" onClick={() => setOpen(false)}>Close</button>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 12 }}>
      <label style={field}>Market
        <select className="tv-select" value={form.market} onChange={e => set('market', e.target.value)}>
          <option value="spot">Spot</option>
          <option value="perp">Perp</option>
        </select>
      </label>
      <label style={field}>Ticker
        <input className="tv-input" list="tl-ticker-options" value={form.ticker} placeholder="Ticker"
               onChange={e => set('ticker', e.target.value)} />
        <datalist id="tl-ticker-options">
          {(tickers || []).map(s => <option key={s} value={s} />)}
        </datalist>
      </label>
      <label style={field}>Direction
        <select className="tv-select" value={form.direction} onChange={e => set('direction', e.target.value)}>
          <option value="long">Long</option>
          <option value="short">Short</option>
        </select>
      </label>
      <label style={field}>Venue
        <input className="tv-input" value={form.venue} placeholder="Venue (e.g. Kraken)"
               onChange={e => set('venue', e.target.value)} />
      </label>
      <label style={field}>Entry price
        <input className="tv-input" inputMode="decimal" value={form.entry_price} placeholder="Entry"
               onChange={e => set('entry_price', e.target.value)} />
      </label>
      <label style={field}>Stop price
        <input className="tv-input" inputMode="decimal" value={form.stop_price} placeholder="Stop"
               onChange={e => set('stop_price', e.target.value)} />
      </label>
      <label style={field}>Quantity
        <input className="tv-input" inputMode="decimal" value={form.qty} placeholder="Quantity"
               onChange={e => set('qty', e.target.value)} />
      </label>
      <label style={field}>Target (optional)
        <input className="tv-input" inputMode="decimal" value={form.target_price} placeholder="Target"
               onChange={e => set('target_price', e.target.value)} />
      </label>
      <label style={field}>Entered at
        <input className="tv-input" type="datetime-local" value={form.entered_at}
               onChange={e => set('entered_at', e.target.value)} />
      </label>
    </div>
    <label style={Object.assign({}, field, { marginTop: 12 })}>Notes
      <textarea className="tv-input" rows={3} style={{ resize: 'vertical', fontFamily: 'inherit' }} value={form.notes}
                onChange={e => set('notes', e.target.value)} />
    </label>
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12, flexWrap: 'wrap' }}>
      <button className="tv-btn primary" style={_tlBtn(!valid || saving)} disabled={!valid || saving} onClick={submit}>
        {saving ? 'Saving…' : 'Log trade'}
      </button>
      {sameEntryStop && <span style={{ fontSize: 13, color: 'var(--fail)' }}>Entry and stop can't be equal (zero risk).</span>}
      {error && <span style={{ fontSize: 13, color: 'var(--fail)' }}>{error}</span>}
    </div>
  </div>;
}

/* ── the screen ──────────────────────────────────────────────────────── */

function TradeLogScreen({ hideValues, refreshTrigger }) {
  const [data, setData] = useTLState(null);
  const [spotRows, setSpotRows] = useTLState({});
  const [loading, setLoading] = useTLState(false);
  const [loadError, setLoadError] = useTLState(null);
  const [updateError, setUpdateError] = useTLState(null);
  const [updatedAt, setUpdatedAt] = useTLState(null);
  const [expanded, setExpanded] = useTLState({});
  const [market, setMarket] = useTLState('all');
  const [attentionOnly, setAttentionOnly] = useTLState(false);
  const [includeEarlier, setIncludeEarlier] = useTLState(false);
  const reqRef = useTLRef(0);
  const hasDataRef = useTLRef(false);
  const coldTimerRef = useTLRef(null);
  const coldCountRef = useTLRef(0);
  const firstRef = useTLRef(true);

  function load() {
    const mine = ++reqRef.current;
    setLoading(true);
    Promise.all([api('/api/trading/trades'), api('/api/spot/pnl').catch(() => null)]).then(([d, pnl]) => {
      if (mine !== reqRef.current) return;
      if (!d || !Array.isArray(d.trades) || !d.summary) throw new Error('Unexpected response');
      const map = {};
      (Array.isArray(pnl) ? pnl : []).forEach(r => { if (r && r.position_key) map[r.position_key] = r; });
      hasDataRef.current = true;
      setData(d);
      setSpotRows(map);
      setLoadError(null);
      setUpdateError(null);
      setUpdatedAt(new Date());
      setLoading(false);
      window.dispatchEvent(new CustomEvent('trades-attention', { detail: d.summary.attention_count }));
      const cold = d.trades.some(t => t.market === 'perp' && t.source !== 'manual' && t.status !== 'closed' &&
                                      t.unrealized_pnl === null);
      if (cold && coldCountRef.current < TL_COLD_RETRY_MAX) {
        coldCountRef.current += 1;
        clearTimeout(coldTimerRef.current);
        coldTimerRef.current = setTimeout(load, TL_COLD_RETRY_MS);
      }
    }).catch(e => {
      if (mine !== reqRef.current) return;
      setLoading(false);
      if (hasDataRef.current) setUpdateError(_tlErr(e));
      else setLoadError(_tlErr(e));
    });
  }

  useTLEffect(() => {
    load();
    return () => {
      reqRef.current += 1;              // late answers are ignored after unmount
      clearTimeout(coldTimerRef.current);
    };
  }, []);

  useTLEffect(() => {
    if (firstRef.current) { firstRef.current = false; return; }
    load();
  }, [refreshTrigger]);

  function toggle(id) { setExpanded(x => Object.assign({}, x, { [id]: !x[id] })); }
  function expand(id) { setExpanded(x => Object.assign({}, x, { [id]: true })); }
  function showAttention(m) { setMarket(m); setAttentionOnly(true); }

  if (!data && loadError) {
    return <div>
      <div className="tv-page-title">Trade Log</div>
      <div className="tv-card" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span style={{ color: 'var(--fail)', fontSize: 14 }}>Couldn't load trades: {loadError}</span>
        <button className="tv-btn" style={_tlBtn(loading)} disabled={loading} onClick={load}>Retry</button>
      </div>
    </div>;
  }
  if (!data) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 240, gap: 10,
                         color: 'var(--text3)', fontSize: 14 }}>
      <span style={{ display: 'inline-block', animation: 'spin 0.8s linear infinite', fontSize: 18 }}>↻</span>
      Loading trades…
    </div>;
  }

  const summary = data.summary;
  const gateStart = (summary.gate && summary.gate.start) || null;
  const startText = _tlDate(gateStart);
  const trading = data.trades.filter(t => t.book === 'trading');
  const taggedCount = data.trades.length - trading.length;
  const attentionCount = trading.filter(t => t.attention).length;
  const beforeCount = trading.filter(t => t.before_rule).length;
  // A trade that needs attention always shows: a spot exit signal can sit on a trade opened before the rule.
  const shown = trading.filter(t => (includeEarlier || !t.before_rule || t.attention !== null) &&
                                    (market === 'all' || t.market === market) &&
                                    (!attentionOnly || t.attention !== null));
  const openRows = shown.filter(t => t.status === 'open' || t.status === 'partly_closed');
  const closedRows = shown.filter(t => t.status === 'closed');
  const unattached = data.unattached_annotations || [];
  const updatedText = updatedAt
    ? 'Updated ' + String(updatedAt.getHours()).padStart(2, '0') + ':' + String(updatedAt.getMinutes()).padStart(2, '0')
    : '';
  const seg = (value, text) => {
    const active = market === value;
    return <button key={value} className="tv-btn" onClick={() => setMarket(value)}
                   style={{ border: 'none', borderRadius: 0, padding: '6px 14px',
                            background: active ? 'var(--accent)' : 'transparent',
                            color: active ? 'var(--bg)' : 'var(--text2)', fontWeight: active ? 700 : 400 }}>{text}</button>;
  };
  const check = { display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--text2)', cursor: 'pointer' };
  const tableProps = { expanded, onToggle: toggle, onExpand: expand, hide: hideValues, spotRows, onSaved: load, gateStart };

  return <div>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap',
                  marginBottom: 16 }}>
      <div>
        <div className="tv-page-title" style={{ marginBottom: 4 }}>Trade Log</div>
        <div style={{ fontSize: 13, color: 'var(--text3)' }}>
          Built from your spot buys and perp fills. Add perp stops, followed or deviated, and notes; spot exits follow the weekly trend.
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        {updateError && <span style={{ fontSize: 13, color: 'var(--fail)' }}>Update failed: {updateError}</span>}
        <span style={{ fontSize: 13, color: 'var(--text3)' }}>{loading ? 'Updating…' : updatedText}</span>
        <button className="tv-btn" style={_tlBtn(loading)} disabled={loading} onClick={load}>Reload</button>
      </div>
    </div>

    <TLGateCard summary={summary} />

    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, marginBottom: 16 }}>
      <TLPanel title={'Spot · since ' + startText} panel={summary.spot} market="spot" hide={hideValues}
               onAttention={showAttention} />
      <TLPanel title={'Perps · since ' + startText} panel={summary.perp} market="perp" hide={hideValues}
               onAttention={showAttention} />
    </div>

    <div style={{ display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap', marginBottom: 16 }}>
      <div style={{ display: 'inline-flex', border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden' }}>
        {seg('all', 'All')}{seg('spot', 'Spot')}{seg('perp', 'Perps')}
      </div>
      <label style={check}>
        <input type="checkbox" checked={attentionOnly} onChange={e => setAttentionOnly(e.target.checked)} />
        Needs attention only ({attentionCount})
      </label>
      <label style={check}>
        <input type="checkbox" checked={includeEarlier} onChange={e => setIncludeEarlier(e.target.checked)} />
        Include trades before {startText} ({beforeCount})
      </label>
    </div>

    <div className="tv-section-title">Open trades ({openRows.length})</div>
    <div className="tv-card" style={{ padding: 0, overflowX: 'auto', marginBottom: 20 }}>
      {openRows.length
        ? <TLTable kind="open" trades={openRows} {...tableProps} />
        : <div style={{ padding: 16, fontSize: 14, color: 'var(--text3)' }}>No open trades match these filters.</div>}
    </div>

    <div className="tv-section-title">Closed trades ({closedRows.length})</div>
    <div className="tv-card" style={{ padding: 0, overflowX: 'auto' }}>
      {closedRows.length
        ? <TLTable kind="closed" trades={closedRows} {...tableProps} />
        : <div style={{ padding: 16, fontSize: 14, color: 'var(--text3)' }}>No closed trades match these filters.</div>}
    </div>

    <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 10 }}>
      * R from prices (manual trades have no fee data).
      {taggedCount > 0 ? ' ' + taggedCount + (taggedCount === 1 ? ' trade in long-term or bot holdings is not shown'
        : ' trades in long-term or bot holdings are not shown') + '; tags are set on Spot Positions.' : ''}
      {' Perp fills sync every 10 minutes while this page or the Dashboard is open, and every 2 hours otherwise.'}
    </div>

    {unattached.length > 0 && <TLUnattached items={unattached} />}

    <TLManualForm onSaved={load} />
  </div>;
}

window.TradeLogScreen = TradeLogScreen;
