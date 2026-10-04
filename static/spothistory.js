/* ===== SPOT HISTORY: BY TRADE — Landing 2b (HANDOFF_spot_perps_rebuild.md 3.3, Oct 4 rulings) =====
   Closed spot trades from GET /api/trading/trades (spot_tx trades from
   spot_transactions, plus manual spot trades from the trade log). Trades
   opened since the gate start (Sep 13) show by default; "Show earlier" adds
   the rest. A row opens to its review (Followed / Deviated and the deviation
   note, optional for spot), the notes for that trade and the full journal.

   The notes for a trade are its position's journal updates that either carry
   its trade_id (Trade Log notes moved into the journal by the one-time move
   of Oct 4, since removed) or carry no trade_id and are
   dated, in local time, between the trade's open and close days. A Trade Log
   note not moved yet shows on its own.

   Loaded after static/spotjournal.js and before static/spotpnl.js; it uses
   their globals (SJNoteText, sjParseTime, sjStamp, SpotJournal, SpotCopyAddress,
   spotHoldChainLabel, spotHoldAddressOf, spotFmtDay, spotFmtPx, spotBookOf,
   spotBookPasses, SpotBookFilterBar, SPOT_BOOK_OPTIONS, extractApiErrorMessage)
   at render time only. Every top-level name here starts with shx / SHX /
   SpotHistory: Babel turns top-level declarations into shared globals. */

const { useState: useSHXState, useEffect: useSHXEffect } = React;

const SHX_GRID = 'minmax(150px,1.3fr) minmax(130px,1fr) minmax(170px,1.3fr) minmax(100px,0.9fr) '
  + 'minmax(76px,0.6fr) minmax(90px,0.7fr) minmax(64px,0.5fr)';
const SHX_LINE = '2px solid rgba(255,255,255,0.25)';
const SHX_SECTION = { fontSize: 12, lineHeight: '16px', fontWeight: 600, letterSpacing: '0.08em',
                      textTransform: 'uppercase', color: 'var(--text3)' };
const SHX_SMALL_BTN = { fontSize: 13, padding: '4px 12px', minHeight: 32 };
const SHX_NOTE_MAX = 2000;      // TRADE_NOTE_MAX on the server

// A local calendar day "YYYY-MM-DD": a bare date stays as it is, a time becomes its local day.
function shxDayKey(s) {
  const str = String(s || '').trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(str)) return str;
  const ms = sjParseTime(str);
  if (!isFinite(ms)) return null;
  const d = new Date(ms);
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

// The journal updates that belong to trade t (see the file header). updates: newest first.
function shxTradeUpdates(t, updates) {
  const open = shxDayKey(t.opened_at);
  const close = shxDayKey(t.closed_at);
  return (updates || []).filter(u => {
    if (u.trade_id) return u.trade_id === t.trade_id;
    const day = shxDayKey(u.created_at);
    return !!(open && close && day && day >= open && day <= close);
  });
}

function shxNum(v) {
  const n = Number(v);
  return v == null || v === '' || !isFinite(n) ? null : n;
}

function shxReadEarlier() {
  try { return localStorage.getItem('spotHistoryEarlier') === '1'; } catch (_e) { return false; }
}

function shxWriteEarlier(v) {
  try { localStorage.setItem('spotHistoryEarlier', v ? '1' : '0'); } catch (_e) { /* the toggle still applies */ }
}

function shxHasJournal(t) {
  return t.source === 'spot_tx' && !!spotHoldAddressOf(t);
}

// Followed / Deviated / Not reviewed and the deviation note for one spot_tx
// trade (PUT /api/trading/trades/<id>/annotation). Manual trades are edited
// in Trade Log, so they get a read-only line.
function SpotHistoryReview({ trade, onSaved }) {
  const ann = trade.annotation || {};
  const storedFollowed = ann.followed_rules == null ? null : ann.followed_rules;
  const storedDev = ann.deviation_note || '';
  const [followed, setFollowed] = useSHXState(storedFollowed);
  const [dev, setDev] = useSHXState(storedDev);
  const [busy, setBusy] = useSHXState(false);
  const [error, setError] = useSHXState('');
  const [saved, setSaved] = useSHXState(false);

  if (trade.source !== 'spot_tx') {
    const word = storedFollowed === true ? 'Followed' : storedFollowed === false ? 'Deviated' : 'Not reviewed';
    return <div style={{ fontSize: 13, color: 'var(--text3)' }}>
      {'Review: ' + word + (storedDev ? ' · ' + storedDev : '') + '. Manual trades are edited in Trade Log.'}
    </div>;
  }

  const dirty = followed !== storedFollowed || dev.replace(/\s+$/, '') !== storedDev;
  async function save() {
    if (busy || !dirty) return;
    const deviation_note = dev.replace(/\s+$/, '') || null;
    setBusy(true);
    try {
      const d = await api('/api/trading/trades/' + encodeURIComponent(trade.trade_id) + '/annotation',
                          { method: 'PUT', body: JSON.stringify({ followed_rules: followed, deviation_note }) });
      if (d === undefined || d.error || !d.annotation) setError(extractApiErrorMessage(d));
      else {
        setError('');
        setSaved(true);
        setTimeout(() => setSaved(false), 2500);
        onSaved(trade.trade_id, { followed_rules: d.annotation.followed_rules, deviation_note: d.annotation.deviation_note });
      }
    } catch (err) { setError(extractApiErrorMessage(err)); }
    finally { setBusy(false); }
  }
  const pick = (value, label, color) => <button type="button" className="tv-btn" aria-pressed={followed === value}
    disabled={busy} onClick={() => setFollowed(value)}
    style={{ ...SHX_SMALL_BTN, background: followed === value ? 'var(--panel3)' : 'transparent',
             borderColor: followed === value ? color : 'var(--line)', color: followed === value ? color : 'var(--text3)',
             fontWeight: followed === value ? 600 : 400 }}>{label}</button>;

  return <div className="spot-j75" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <span style={SHX_SECTION}>Review</span>
      <span role="group" aria-label={'Review for ' + trade.symbol} style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
        {pick(true, 'Followed', 'var(--ok)')}
        {pick(false, 'Deviated', 'var(--fail)')}
        {pick(null, 'Not reviewed', 'var(--text3)')}
      </span>
      <span style={{ fontSize: 12, color: 'var(--text3)' }}>Optional for spot; spot trades don't count toward the risk gate.</span>
    </div>
    <input className="tv-input" maxLength={SHX_NOTE_MAX} value={dev} disabled={busy}
      aria-label={'Deviation note for ' + trade.symbol} placeholder="What was different from the plan (optional)"
      onChange={e => setDev(e.target.value)}
      onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); save(); } }} />
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <button type="button" className="tv-btn primary" style={SHX_SMALL_BTN} disabled={busy || !dirty} onClick={save}>
        {busy ? 'Saving…' : 'Save review'}</button>
      {saved && <span role="status" style={{ fontSize: 13, color: 'var(--ok)' }}>Saved</span>}
      {error && <span role="alert" style={{ fontSize: 13, color: 'var(--fail)' }}>{error}</span>}
    </div>
  </div>;
}

// journal: the Spot page's journal state (drafts and composing by position_key);
// jumpTradeId: a trade to open on arrival (from Trade Log's pointer).
function SpotHistoryByTrade({ hideValues, refreshTrigger, bookFilter, setBookFilter, journal, jumpTradeId }) {
  const [trades, setTrades] = useSHXState(null);
  const [loadError, setLoadError] = useSHXState(false);
  const [gateStart, setGateStart] = useSHXState(null);
  const [updatesByKey, setUpdatesByKey] = useSHXState({});
  const [notesError, setNotesError] = useSHXState(false);
  const [summaries, setSummaries] = useSHXState({});
  const [earlier, setEarlierState] = useSHXState(shxReadEarlier);
  const [openIds, setOpenIds] = useSHXState(() => new Set(jumpTradeId ? [jumpTradeId] : []));
  const [fullJournal, setFullJournal] = useSHXState(() => new Set());
  function setEarlier(v) { setEarlierState(v); shxWriteEarlier(v); }

  useSHXEffect(() => {
    let alive = true;
    api('/api/trading/trades').then(d => {
      if (!alive) return;
      if (!d || !Array.isArray(d.trades)) { setLoadError(true); return; }
      const spot = d.trades.filter(t => t && t.market === 'spot');
      setTrades(spot);
      setLoadError(false);
      setGateStart(d.summary && d.summary.gate ? d.summary.gate.start : null);
      const jumped = jumpTradeId && spot.find(t => t.trade_id === jumpTradeId);
      if (jumped && jumped.before_rule) setEarlierState(true);
    }).catch(() => { if (alive) setLoadError(true); });
    api('/api/spot/note-updates').then(list => {
      if (!alive) return;
      if (!Array.isArray(list)) { setNotesError(true); return; }
      const byKey = {};
      for (const u of list) (byKey[u.position_key] = byKey[u.position_key] || []).push(u);
      setUpdatesByKey(byKey);
      setNotesError(false);
    }).catch(() => { if (alive) setNotesError(true); });
    api('/api/spot/position-notes').then(list => {
      if (!alive || !Array.isArray(list)) return;
      const byKey = {};
      for (const n of list) byKey[n.chain + ' ' + n.contract_address] = n.note || '';
      setSummaries(byKey);
    }).catch(() => {});
    return () => { alive = false; };
  }, [refreshTrigger]);

  useSHXEffect(() => {
    if (!jumpTradeId || !trades) return;
    const t = setTimeout(() => {
      const el = document.getElementById('shx-trade-' + jumpTradeId);
      if (el && el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 50);
    return () => clearTimeout(t);
  }, [trades]);

  if (trades === null && !loadError) return <div style={{ padding: 40, textAlign: 'center', color: 'var(--text4)' }}><div className="spin" style={{ display: 'inline-block', width: 24, height: 24, border: '2px solid var(--line)', borderTopColor: 'var(--accent)', borderRadius: '50%' }} /></div>;
  if (trades === null) return <div style={{ color: 'var(--fail)', padding: 20 }}>Failed to load trades.</div>;

  const closed = trades.filter(t => t.status === 'closed');
  const inBook = closed.filter(t => spotBookPasses(t, bookFilter));
  const earlierCount = inBook.filter(t => t.before_rule).length;
  const rows = inBook.filter(t => earlier || !t.before_rule);
  const dayMs = s => { const k = shxDayKey(s); return k ? Date.parse(k + 'T00:00:00Z') : -Infinity; };
  rows.sort((a, b) => dayMs(b.closed_at) - dayMs(a.closed_at) || dayMs(b.opened_at) - dayMs(a.opened_at)
    || String(a.trade_id).localeCompare(String(b.trade_id)));
  const bookCounts = { all: closed.length, trading: closed.filter(t => spotBookOf(t) === 'trading').length,
                       other: closed.filter(t => spotBookOf(t) !== 'trading').length };
  const sinceText = spotFmtDay(gateStart) || 'Sep 13';

  const mv = v => hideValues ? '••••' : fmt(v);
  const signColor = v => hideValues || v == null ? undefined : v >= 0 ? 'var(--ok)' : 'var(--fail)';
  const nets = rows.map(t => shxNum(t.net_pnl));
  const wins = nets.filter(n => n != null && n > 0).length;
  const losses = nets.filter(n => n != null && n <= 0).length;
  const net = nets.reduce((s, n) => s + (n || 0), 0);

  function toggle(id) {
    setOpenIds(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  }
  function toggleJournal(id) {
    setFullJournal(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  }
  function onReviewSaved(id, patch) {
    setTrades(prev => prev.map(t => t.trade_id === id ? { ...t, annotation: { ...(t.annotation || {}), ...patch } } : t));
  }
  function onUpdatesChanged(key, fn) {
    setUpdatesByKey(prev => ({ ...prev, [key]: fn(prev[key] || []) }));
  }
  function onSummarySaved(key, note) {
    setSummaries(prev => ({ ...prev, [key]: note }));
  }

  const num = (label, content, style, title) => <div className="spot-cell tv-num" data-label={label} title={title}
    style={{ textAlign: 'right', ...style }}>{content}</div>;

  function tradeRow(t) {
    const id = t.trade_id;
    const open = openIds.has(id);
    const hasJournal = shxHasJournal(t);
    const key = t.position_key;
    const ups = hasJournal ? shxTradeUpdates(t, updatesByKey[key]) : [];
    const legacy = ((t.annotation || {}).notes || '').trim();
    const noteCount = ups.length + (legacy ? 1 : 0);
    const n = shxNum(t.net_pnl);
    const cost = shxNum(t.cost_sold);
    const ret = n != null && cost != null && cost > 0 ? n / cost * 100 : null;
    const followed = (t.annotation || {}).followed_rules;
    const review = followed === true ? 'Followed' : followed === false ? 'Deviated' : '—';
    const reviewColor = followed === true ? 'var(--ok)' : followed === false ? 'var(--fail)' : 'var(--text3)';
    const openDay = shxDayKey(t.opened_at);
    const closeDay = shxDayKey(t.closed_at);
    const dates = (spotFmtDay(openDay) || '—') + ' → ' + (spotFmtDay(closeDay) || '—');
    const prices = hideValues ? '•••• → ••••'
      : (shxNum(t.avg_entry) != null ? spotFmtPx(shxNum(t.avg_entry)) : '—') + ' → '
        + (shxNum(t.avg_exit) != null ? spotFmtPx(shxNum(t.avg_exit)) : '—');
    const sub = t.source === 'spot_tx' ? spotHoldChainLabel(t) : (t.venue || 'Manual');
    const sym = String(t.symbol || '').toUpperCase();
    const flags = t.flags || [];
    const after = shxNum(t.after_close_realized);
    const bookLabel = (SPOT_BOOK_OPTIONS.find(o => o.value === spotBookOf(t)) || { label: 'Trading' }).label;

    const row = <div id={'shx-trade-' + id} key={id} className="spot-grid-row"
      style={{ gridTemplateColumns: SHX_GRID, padding: '10px 16px', borderBottom: SHX_LINE, fontSize: 13, color: 'var(--text2)' }}>
      <div className="spot-span" style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
        <button type="button" className="tv-btn" aria-expanded={open}
          aria-label={(open ? 'Hide' : 'Show') + ' details for the ' + sym + ' trade closed ' + (spotFmtDay(closeDay) || '')}
          onClick={() => toggle(id)}
          style={{ width: 32, height: 32, padding: 0, flex: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center',
                   fontSize: 13, color: 'var(--text)' }}>{open ? '▾' : '▸'}</button>
        <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <span style={{ fontWeight: 700, color: 'var(--text)', fontSize: 14 }}>
            {hasJournal ? <SpotCopyAddress row={t}>{t.symbol}</SpotCopyAddress> : t.symbol}
          </span>
          <span style={{ fontSize: 12, color: 'var(--text3)', overflowWrap: 'anywhere' }}>{sub}</span>
        </div>
      </div>
      <div className="spot-cell" data-label="Opened → closed" style={{ color: 'var(--text3)' }}>{dates}</div>
      {num('Entry → exit', prices)}
      {num('Net P&L', n == null ? '—' : hideValues ? '••••' : (n > 0 ? '+' : '') + fmt(n), { color: signColor(n), fontWeight: 600 },
           !hideValues && after ? 'Includes ' + (after > 0 ? '+' : '') + fmt(after) + ' from a sale after the trade closed' : undefined)}
      {num('Return', ret == null ? '—' : hideValues ? '••%' : fmtPct(ret), { color: signColor(ret) })}
      <div className="spot-cell spot-pad-left" data-label="Review" style={{ color: reviewColor }}>{review}</div>
      <div className="spot-cell" data-label="Notes" style={{ color: 'var(--text3)' }}
        title={noteCount ? noteCount + (noteCount === 1 ? ' note' : ' notes') + ' for this trade' : 'No notes for this trade'}>
        {noteCount ? '✎ ' + noteCount : '—'}</div>
    </div>;
    if (!open) return row;

    const summary = hasJournal ? (summaries[key] || '') : '';
    const showFull = fullJournal.has(id);
    const legacyWhy = t.source !== 'spot_tx' ? 'Trade Log note'
      : hasJournal ? "Trade Log note (not moved into the journal yet)"
      : "Trade Log note (this position has no contract address, so it can't join a journal)";
    return <React.Fragment key={id}>
      {row}
      <div className="spot-detail" style={{ padding: '16px 16px 20px 56px', borderBottom: SHX_LINE, background: 'var(--bg)',
                                            display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div className="spot-j75" style={{ fontSize: 13, fontWeight: 600, color: 'var(--text3)' }}>
          {sym + ' trade · ' + (spotFmtDay(openDay) || '—') + ' – ' + (spotFmtDay(closeDay) || '—') + ' · ' + bookLabel + ' book'}
        </div>
        {(flags.indexOf('after_close_sell') >= 0 || flags.indexOf('orphan_sell') >= 0) &&
          <div className="spot-j75" style={{ fontSize: 13, color: 'var(--warn)' }}>
            {[flags.indexOf('after_close_sell') >= 0 && !hideValues && after
                ? 'Net P&L includes ' + (after > 0 ? '+' : '') + fmt(after) + ' from a sale after the trade closed.' : null,
              flags.indexOf('after_close_sell') >= 0 && (hideValues || !after) ? 'Net P&L includes a sale after the trade closed.' : null,
              flags.indexOf('orphan_sell') >= 0 ? 'A sale with no matching buy is part of this trade.' : null]
              .filter(Boolean).join(' ')}
          </div>}
        <SpotHistoryReview key={'review-' + id} trade={t} onSaved={onReviewSaved} />
        <div className="spot-j75" style={{ borderTop: '2px solid rgba(255,255,255,0.4)', paddingTop: 12, display: 'flex',
                                           alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <span style={SHX_SECTION}>Notes for this trade</span>
          {hasJournal && <button type="button" className="tv-btn" style={SHX_SMALL_BTN} aria-expanded={showFull}
            onClick={() => toggleJournal(id)}>{showFull ? 'Hide full journal' : 'Show full journal'}</button>}
        </div>
        {notesError && hasJournal && <div role="alert" style={{ color: 'var(--fail)', fontSize: 13 }}>Couldn't load the journal updates. Refresh to try again.</div>}
        {showFull && hasJournal
          ? <SpotJournal row={{ position_key: key, symbol: t.symbol, note: summary }} updates={updatesByKey[key] || []}
              notesError={notesError} onSummarySaved={onSummarySaved} onUpdatesChanged={onUpdatesChanged}
              draft={journal.drafts[key] || ''} onDraftChange={v => journal.setDrafts(prev => ({ ...prev, [key]: v }))}
              composing={!!journal.composing[key]} setComposing={v => journal.setComposing(prev => ({ ...prev, [key]: v }))} />
          : <React.Fragment>
              {hasJournal && <div className="spot-j75" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, color: 'var(--text3)' }}>Summary</span>
                {summary.trim() ? <SJNoteText text={summary} />
                  : <span style={{ fontSize: 13, color: 'var(--text3)' }}>No summary yet.</span>}
              </div>}
              {ups.map(u => {
                const at = sjParseTime(u.created_at);
                return <div key={u.id} className="spot-j75" style={{ display: 'flex', flexDirection: 'column', gap: 6, paddingTop: 10, borderTop: SHX_LINE }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
                    <span style={{ fontFamily: "'Fira Code', monospace", fontSize: 13, fontWeight: 500, color: 'var(--text)' }}>{sjStamp(at)}</span>
                    {u.trade_id && <span style={{ fontSize: 12, color: 'var(--text3)' }}>from Trade Log</span>}
                    {u.edited_at && <span style={{ fontSize: 12, color: 'var(--text3)' }} title={'Edited ' + sjStamp(sjParseTime(u.edited_at))}>edited</span>}
                  </div>
                  <SJNoteText text={u.body} />
                </div>;
              })}
              {legacy && <div className="spot-j75" style={{ display: 'flex', flexDirection: 'column', gap: 6, paddingTop: 10, borderTop: SHX_LINE }}>
                <span style={{ fontSize: 12, color: 'var(--text3)' }}>{legacyWhy}</span>
                <SJNoteText text={(t.annotation || {}).notes} />
              </div>}
              {!ups.length && !legacy && <div style={{ fontSize: 13, color: 'var(--text3)' }}>
                {hasJournal ? 'No updates were written for this trade.' : 'No notes for this trade.'}</div>}
            </React.Fragment>}
      </div>
    </React.Fragment>;
  }

  const head = { fontSize: 12, lineHeight: '16px', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text3)' };
  const right = { textAlign: 'right' };

  return <div>
    <SpotBookFilterBar value={bookFilter} onChange={setBookFilter} counts={bookCounts} />
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 12, fontSize: 13, color: 'var(--text3)' }}>
      <span>
        {rows.length + ' closed · ' + wins + 'W / ' + losses + 'L · net '}
        <span className="tv-num" style={{ color: signColor(net), fontWeight: 600 }}>{hideValues ? '••••' : (net > 0 ? '+' : '') + fmt(net)}</span>
      </span>
      <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
        <input type="checkbox" checked={earlier} onChange={e => setEarlier(e.target.checked)} />
        {'Show trades opened before ' + sinceText + ' (' + earlierCount + ')'}
      </label>
    </div>
    {closed.length === 0 ? <div style={{ color: 'var(--text4)', padding: 20, textAlign: 'center' }}>No closed spot trades yet.</div>
    : rows.length === 0 ? <div style={{ color: 'var(--text4)', padding: 20, textAlign: 'center' }}>No closed trades in this view.</div>
    : <div className="tv-card" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="spot-grid-row spot-grid-head" style={{ ...head, gridTemplateColumns: SHX_GRID, alignItems: 'end',
                                                               padding: '12px 16px', borderBottom: '2px solid rgba(255,255,255,0.35)' }}>
          <span>Token</span><span>Opened → closed</span><span style={right}>Entry → exit</span>
          <span style={right}>Net P&L</span><span style={right}>Return</span><span className="spot-pad-left">Review</span><span>Notes</span>
        </div>
        {rows.map(tradeRow)}
      </div>}
    <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 8 }}>
      Return = net P&L ÷ what the sold units cost (FIFO). A trade's notes are its journal updates written between its open and close days, plus Trade Log notes moved for it.
    </div>
  </div>;
}

window.SpotHistoryByTrade = SpotHistoryByTrade;
window.shxTradeUpdates = shxTradeUpdates;
window.shxDayKey = shxDayKey;
