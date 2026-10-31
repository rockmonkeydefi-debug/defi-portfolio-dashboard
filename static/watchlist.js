/* ===== WATCH LIST - Landing 78 =====
   The Trading menu's Watch List page: tokens you watch but don't hold. Each is
   a collapsible row. The row's top line is always visible: the name and chain,
   the price, the trend (four dots for 4H, 12H, 1D and 1W as on the Spot page,
   and the most respected timeframe), a one-line plan summary and an Active
   checkbox. Opened, a row holds the summary field, the item's notes (the Notes
   page's editor, static/pagenotes.js, with tables and images), the trend in
   detail with a Check trend button, and the contract.

   - Data: GET /api/watchlist (items, the saved trend, the scanner's rows),
     GET /api/watchlist/prices (live DexScreener prices of the active items,
     every WL_PRICE_POLL_MS while the page is open), POST /api/watchlist (add),
     PUT /api/watchlist/<key> (name, summary, active), POST
     /api/watchlist/<key>/check (Check trend). Every change answers with the
     whole list, so the page always shows the server's state. Nothing is
     deleted here (Landing 79).
   - Active items are listed first; an item you uncheck drops to "Inactive"
     below, with its notes, summary and saved trend kept, and comes back when
     you check it again.
   - Trend: the Trends scanner's rows when it has a market with the item's
     name (matched like the Spot page: the ticker, else its kilo-prefixed one)
     and the last Check trend result for the item's contract (the on-chain
     check), whichever is fresher (a check you just ran beats a scan from before
     it, so a wrong ticker match can be overruled from the contract; the next
     scan takes over again). The most respected timeframe reuses static/trends.js
     (_trendsRespectCell): the passing timeframe with the most tags, the longer
     timeframe on a tie.
   - A row's body mounts the first time it is opened and is then only hidden, so
     an unsaved note stays while the row is closed; summary drafts live in the
     screen, so they also survive a row moving between Watching and Inactive. A
     row with unsaved edits says so, and the browser asks before a reload or
     leaving the app (window.PageNotesShowPages guards every item's notes; an
     unsaved summary has its own beforeunload guard).
   - Hide values hides the plan summaries and the notes.

   Loaded after static/pagenotes.js, static/spotpnl.js and static/trends.js
   (templates/index.html). Every top-level name here starts with wl / WL / Wl:
   Babel turns top-level declarations into shared globals, so a name used in
   another static/*.js file would be silently overwritten (static/trading.js
   already has a WatchRow). */

const { useState: useWLState, useEffect: useWLEffect, useRef: useWLRef, useCallback: useWLCallback } = React;

const WL_PRICE_POLL_MS = 120000;           // the live prices are re-read this often while the page is open
const WL_CHECK_OLD_MS = 24 * 3600 * 1000;  // a saved trend check older than this is shown as old
const WL_REQUEST_TIMEOUT_MS = 20000;         // longer than the prices route's own 15 s limit
const WL_CHECK_TIMEOUT_MS = 90000;         // Check trend takes about 20 s on the server
const WL_EXPANDED_KEY = 'watchListExpanded';
const WL_INACTIVE_KEY = 'watchListInactiveOpen';
const WL_CHAIN_KEY = 'watchListChain';
const WL_KEY_RE = /^notes-w[1-9][0-9]{0,5}$/;
const WL_RESPECT_TFS = ['1d', '12h', '4h', '1h'];       // longest first (TRENDS_RESPECT_TFS)
const WL_ROW_TFS = ['1w', '1d', '12h', '4h', '1h'];
const WL_TF_LABEL = { '1w': '1W', '1d': '1D', '12h': '12H', '4h': '4H', '1h': '1H' };
const WL_DIR_LABEL = { BULLISH: 'Bullish', BEARISH: 'Bearish' };
const WL_DASH = String.fromCharCode(0x2014);
const WL_MID = String.fromCharCode(0xB7);
const WL_ELLIPSIS = String.fromCharCode(0x2026);
const WL_MASK = String.fromCharCode(0x2022, 0x2022, 0x2022, 0x2022);

function wlReadExpanded() {
  try {
    const v = JSON.parse(localStorage.getItem(WL_EXPANDED_KEY) || '[]');
    return Array.isArray(v) ? v.filter(k => typeof k === 'string' && WL_KEY_RE.test(k)) : [];
  } catch (e) { return []; }
}

function wlWriteExpanded(keys) {
  try { localStorage.setItem(WL_EXPANDED_KEY, JSON.stringify(keys)); } catch (e) { /* storage blocked: the rows stay as they are this visit */ }
}

function wlReadFlag(key) {
  try { return localStorage.getItem(key) === '1'; } catch (e) { return false; }
}

function wlWriteFlag(key, on) {
  try { localStorage.setItem(key, on ? '1' : '0'); } catch (e) { /* the toggle still works */ }
}

// A request that gives up after timeoutMs; {status: 0} when the server can't be reached.
async function wlRequest(method, path, body, timeoutMs) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs || WL_REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(path, {
      method, headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body), signal: ctrl.signal,
    });
    if (res.status === 401) { window.location.href = '/login'; return null; }
    let data = null;
    try { data = await res.json(); } catch (e) { /* not JSON */ }
    return { status: res.status, data };
  } catch (e) {
    return { status: 0, data: null, aborted: !!(e && e.name === 'AbortError') };
  } finally {
    clearTimeout(timer);
  }
}

function wlError(res, fallback) {
  if (res && res.data && typeof res.data.error === 'string' && res.data.error) return res.data.error;
  if (res && res.status === 0) return res.aborted ? 'The request took too long.' : "Couldn't reach the server.";
  return fallback;
}

function wlIsList(res) {
  return !!(res && res.data && Array.isArray(res.data.items));
}

// The summary as the server stores it: trimmed, each run of spaces (a line break too) made one.
function wlCleanSummary(s) {
  return String(s || '').split(/\s+/).filter(Boolean).join(' ');
}

function wlAge(iso) {
  const ms = Date.parse(iso || '');
  if (isNaN(ms)) return null;
  const min = Math.max(0, Math.floor((Date.now() - ms) / 60000));
  if (min < 1) return 'just now';
  if (min < 60) return min + 'm ago';
  if (min < 48 * 60) return Math.floor(min / 60) + 'h ago';
  return Math.floor(min / 1440) + 'd ago';
}

function wlStamp(iso) {
  return (typeof pnSavedLabel === 'function' ? pnSavedLabel(iso) : null) || iso || '';
}

// The rows the trend is read from: the Trends scanner's (when it has a market
// for the name) or the last saved Check trend result, whichever is fresher;
// null when neither has rows.
function wlTrendSource(item) {
  const hasRows = (tfs) => !!tfs && WL_ROW_TFS.some(tf => tfs[tf]);
  const sc = item.scanner && hasRows(item.scanner.timeframes)
    ? { kind: 'scanner', tfs: item.scanner.timeframes, asOf: item.scanner.as_of, symbol: item.scanner.scanner_symbol } : null;
  const ck = item.check && hasRows(item.check.timeframes)
    ? { kind: 'check', tfs: item.check.timeframes, asOf: item.check.computed_at,
        old: Date.now() - Date.parse(item.check.computed_at || '') > WL_CHECK_OLD_MS } : null;
  if (sc && ck) {
    const s = Date.parse(sc.asOf || ''), c = Date.parse(ck.asOf || '');
    return isFinite(c) && (!isFinite(s) || c > s) ? ck : sc;
  }
  return sc || ck;
}

// The most respected timeframe: the passing one with the most tags, the longer
// timeframe on a tie. cells has every timeframe's _trendsRespectCell result.
function wlRespected(tfs, nowMs) {
  const cells = {};
  let best = null;
  for (const tf of WL_RESPECT_TFS) {
    const row = tfs ? tfs[tf] : null;
    const cell = row && typeof _trendsRespectCell === 'function' ? _trendsRespectCell(row, tf, nowMs) : null;
    cells[tf] = cell;
    if (cell && cell.status === 'pass' && (!best || cell.tags > best.cell.tags)) best = { tf, cell };
  }
  return { cells, best };
}

function wlRespectText(tf, cell) {
  if (!cell) return 'No respected trend';
  if (cell.status === 'ranging') return 'Ranging';
  const dir = WL_DIR_LABEL[cell.dir] || cell.dir;
  const forText = typeof _trendsFmtRespectedFor === 'function' ? _trendsFmtRespectedFor(cell.forSeconds, cell.unbounded) : null;
  const base = dir + (forText ? ', respected ' + forText : '') + ', ' + cell.tags + ' tag' + (cell.tags === 1 ? '' : 's');
  return cell.status === 'stale' ? base + ' (stale: last tag ' + cell.barsAgo + ' bars ago)'
    : base + (cell.retesting ? ', testing the band now' : '');
}

// The price shown: the live one, else the last known (never the scanner's
// price of a kilo-prefixed market such as kBONK, which prices 1,000 tokens).
function wlPriceView(item, live) {
  if (typeof live === 'number') return { value: live, live: true, note: 'Live price from DexScreener' };
  const sc = item.scanner;
  const kilo = !!(sc && String(sc.scanner_symbol).toUpperCase() !== String(item.name).trim().toUpperCase());
  if (sc && sc.timeframes && !kilo) {
    for (const tf of ['1h', '4h', '12h', '1d', '1w']) {
      const r = sc.timeframes[tf];
      if (r && typeof r.price === 'number') return { value: r.price, live: false, note: 'Last known price from the Trends scanner, ' + wlStamp(r.computed_at) };
    }
  }
  if (item.check && typeof item.check.price === 'number') {
    return { value: item.check.price, live: false, note: 'Last known price from the saved trend check, ' + wlStamp(item.check.computed_at) };
  }
  return null;
}

function WlTrendDots({ tfs, source, name }) {
  const parts = SPOT_TREND_TFS.map(([tf, label]) => {
    const x = tfs && tfs[tf];
    return { tf, label, pos: x && SPOT_TREND_WORD[x.position] ? x.position : null };
  });
  const text = 'Price vs the noodle: ' + parts.map(p => p.label + ' ' + (p.pos ? SPOT_TREND_WORD[p.pos] : 'no data')).join(', ')
    + (source && source.kind === 'scanner' && source.symbol && String(source.symbol).toUpperCase() !== String(name).trim().toUpperCase()
      ? ' ' + WL_MID + ' scanner market ' + source.symbol : '')
    + (source && source.asOf ? ' ' + WL_MID + ' as of ' + wlStamp(source.asOf) : '')
    + (source && source.kind === 'check' ? ' ' + WL_MID + ' from the contract check' : '');
  return <span role="img" aria-label={text} title={text} style={{ display: 'inline-flex' }}>
    {parts.map(p => <span key={p.tf} className="wl-dot-cell"><SpotTrendDot pos={p.pos} /></span>)}
  </span>;
}

// The detail table: price against the noodle and the respected trend, per timeframe.
function WlTrendDetail({ item, source, checking, checkBusy, onCheck }) {
  const nowMs = Date.now();
  const resp = source ? wlRespected(source.tfs, nowMs) : { cells: {}, best: null };
  const chk = item.check;
  const pool = chk && chk.pool;
  return <div className="wl-sec">
    <div className="wl-sec-title">Trend</div>
    {!source && <div className="wl-muted">No trend yet. The Trends scanner has no market named {item.name}; press Check trend to read it from the contract.</div>}
    {source && <div className="wl-muted">
      {source.kind === 'scanner'
        ? 'From the Trends scanner' + (source.symbol ? ' (market ' + source.symbol + ', matched by name)' : '') + (source.asOf ? ', as of ' + wlStamp(source.asOf) : '') + '.'
        : 'From the contract check' + (source.asOf ? ' of ' + wlStamp(source.asOf) + ' (' + wlAge(source.asOf) + ')' : '') + (source.old ? ', which is old' : '') + '.'}
    </div>}
    {source && <table className="wl-trend-table">
      <thead><tr><th scope="col">Timeframe</th><th scope="col">Price vs the noodle</th><th scope="col">Respected trend</th></tr></thead>
      <tbody>
        {WL_ROW_TFS.map(tf => {
          const row = source.tfs[tf];
          const pos = row && SPOT_TREND_WORD[row.position] ? row.position : null;
          return <tr key={tf}>
            <th scope="row">{WL_TF_LABEL[tf]}</th>
            <td>{pos ? <span className="wl-pos"><SpotTrendDot pos={pos} /> {SPOT_TREND_WORD[pos]}</span> : <span className="wl-muted">{row ? 'no band' : 'no data'}</span>}</td>
            <td>{tf === '1w' ? <span className="wl-muted">not computed</span>
              : <span className={resp.cells[tf] && resp.cells[tf].status === 'pass' ? '' : 'wl-muted'}>{wlRespectText(tf, resp.cells[tf])}</span>}</td>
          </tr>;
        })}
      </tbody>
    </table>}
    {pool && <div className="wl-muted">Pool {pool.name || WL_DASH}{pool.dex ? ' on ' + pool.dex : ''}
      {typeof pool.liquidity_usd === 'number' ? ' ' + WL_MID + ' liquidity $' + Math.round(pool.liquidity_usd).toLocaleString('en-US') : ''}
      {typeof pool.age_days === 'number' ? ' ' + WL_MID + ' ' + (pool.age_days < 1 ? 'under a day' : Math.round(pool.age_days) + ' days') + ' old' : ''}</div>}
    {chk && Array.isArray(chk.notes) && chk.notes.slice(1).map((n, i) => <div key={i} className="wl-muted">{n}</div>)}
    <div className="wl-actions">
      <button type="button" className="tv-btn" disabled={checkBusy} onClick={onCheck}
        title={checkBusy && !checking ? 'Another trend check is running' : 'Reads the trend from the contract (about 20 seconds)'}>
        {checking ? 'Checking' + WL_ELLIPSIS : chk ? 'Check trend again' : 'Check trend'}</button>
      {checking && <span className="wl-muted" role="status">About 20 seconds. You can keep working.</span>}
    </div>
  </div>;
}

function WlSummaryField({ item, draft, setDraft, limit, hideValues, saving, onSave }) {
  const clean = wlCleanSummary(draft);
  const dirty = clean !== wlCleanSummary(item.summary);
  const tooLong = Array.from(clean).length > limit;
  if (hideValues) {
    return <div className="wl-sec"><div className="wl-sec-title">Plan summary</div><div className="wl-muted">Hidden while Hide values is on.</div></div>;
  }
  return <div className="wl-sec">
    <label className="wl-sec-title" htmlFor={'wl-sum-' + item.key}>Plan summary (one line, shown in the row)</label>
    <div className="wl-sumrow">
      <input id={'wl-sum-' + item.key} className="tv-input" type="text" value={draft} maxLength={limit * 2}
        placeholder="Your plan in a sentence, e.g. buy the 4H retest of the band, stop under the swing low"
        onChange={e => setDraft(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' && dirty && !tooLong && !saving) { e.preventDefault(); onSave(); }
          if (e.key === 'Escape') setDraft(undefined);
        }} />
      <button type="button" className="tv-btn primary" disabled={!dirty || tooLong || saving} onClick={onSave}>{saving ? 'Saving' + WL_ELLIPSIS : 'Save'}</button>
      {dirty && !saving && <button type="button" className="tv-btn" onClick={() => setDraft(undefined)}>Discard</button>}
    </div>
    <div className={'wl-count' + (tooLong ? ' wl-count--over' : '')}>{Array.from(clean).length} / {limit}{dirty ? ' ' + WL_MID + ' not saved yet' : ''}</div>
  </div>;
}

function WlItemRow({ item, expanded, onToggle, live, busy, checking, checkBusy, notice, limits, hideValues, draftRaw, onDraft, onPatch, onCheck, onDismiss }) {
  const [opened, setOpened] = useWLState(expanded);
  const [savingSummary, setSavingSummary] = useWLState(false);
  const [noteDraft, setNoteDraft] = useWLState(false);
  const [copied, setCopied] = useWLState(false);
  const [pendingActive, setPendingActive] = useWLState(null);     // the box shows your click at once; the server's answer then decides
  useWLEffect(() => { if (expanded) setOpened(true); }, [expanded]);
  useWLEffect(() => {
    if (!opened) return undefined;
    const tick = () => setNoteDraft(typeof window.PageNotesHasDraft === 'function' && !!window.PageNotesHasDraft(item.key));
    tick();
    const t = setInterval(tick, 1500);
    return () => clearInterval(t);
  }, [opened, item.key]);

  const source = wlTrendSource(item);
  const nowMs = Date.now();
  const resp = source ? wlRespected(source.tfs, nowMs) : { cells: {}, best: null };
  const price = wlPriceView(item, live);
  // The summary draft lives in the screen (draftRaw is undefined when there is none), so it survives this row moving
  // between Watching and Inactive (which remounts it).
  const draft = draftRaw === undefined ? item.summary : draftRaw;
  const summaryDirty = draftRaw !== undefined && wlCleanSummary(draftRaw) !== wlCleanSummary(item.summary);
  const unsaved = summaryDirty || noteDraft;
  const body = 'wl-body-' + item.key;
  // An unsaved summary makes the browser ask before a reload (unsaved notes are guarded by pagenotes.js).
  useWLEffect(() => {
    if (!summaryDirty) return undefined;
    const warn = e => { e.preventDefault(); e.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [summaryDirty]);

  async function saveSummary() {
    const sent = draftRaw;
    if (sent === undefined) return;
    setSavingSummary(true);
    const r = await onPatch({ summary: sent });
    setSavingSummary(false);
    if (r && r.ok) onDraft(sent, true);        // drops the draft unless you typed more while it saved
  }

  function copyContract() {
    try {
      navigator.clipboard.writeText(item.contract).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }, () => {});
    } catch (e) { /* no clipboard: the contract is selectable below */ }
  }

  const checkBtn = (label) => <button type="button" className="tv-btn wl-check-btn" disabled={checkBusy}
    aria-label={label + ' for ' + item.name}
    title={checkBusy && !checking ? 'Another trend check is running' : 'Reads the trend from the contract (about 20 seconds)'}
    onClick={onCheck}>{checking ? 'Checking' + WL_ELLIPSIS : label}</button>;

  return <div className={'wl-row tv-card' + (item.active ? '' : ' wl-row--inactive')} data-key={item.key} data-active={item.active ? '1' : '0'}>
    <div className="wl-head" onClick={e => { if (!(e.target.closest && e.target.closest('button, input, label, a, select, textarea'))) onToggle(); }}>
      <div className="wl-c-name">
        <button type="button" className="wl-toggle" aria-expanded={expanded} aria-controls={opened ? body : undefined} onClick={onToggle}>
          <span className="wl-chev" aria-hidden="true" />
          <span className="wl-name">{item.name}</span>
          <span className="tv-chip wl-chain" title={item.contract}>{item.chain_label}</span>
          {unsaved && <span className="tv-chip warn" title="This row has edits that are not saved yet">unsaved</span>}
        </button>
      </div>
      <div className="wl-c-price tv-num" title={price ? price.note : 'No price yet'}>
        {price ? <span className={price.live ? '' : 'wl-stale'}>{window.fmtTokenPrice(price.value)}</span> : <span className="wl-muted">{WL_DASH}</span>}
      </div>
      <div className="wl-c-trend">
        {source ? <>
          <WlTrendDots tfs={source.tfs} source={source} name={item.name} />
          {source.kind === 'check' && <span className={'wl-age' + (source.old ? ' wl-age--old' : '')} title={'Contract check of ' + wlStamp(source.asOf)}>{wlAge(source.asOf)}</span>}
          {source.kind === 'check' && checkBtn('Re-check')}
        </> : <>
          <span className="wl-muted">No trend yet</span>
          {checkBtn('Check trend')}
        </>}
      </div>
      <div className="wl-c-resp" title={source ? WL_RESPECT_TFS.map(tf => WL_TF_LABEL[tf] + ': ' + wlRespectText(tf, resp.cells[tf])).join('. ') : undefined}>
        {!source ? null : resp.best
          ? <span><strong>{WL_TF_LABEL[resp.best.tf]} {WL_DIR_LABEL[resp.best.cell.dir] || resp.best.cell.dir}</strong>
            <span className="wl-muted">{' ' + WL_MID + ' ' + resp.best.cell.tags + ' tags'}</span>
            {resp.best.cell.retesting && <span className="tv-chip accent wl-testing">testing</span>}</span>
          : <span className="wl-muted">No respected trend</span>}
      </div>
      <div className="wl-c-summary">
        {hideValues ? <span className="wl-muted">{WL_MASK}</span>
          : item.summary ? <span className="wl-summary-text" title={item.summary}>{item.summary}</span>
          : <span className="wl-summary-empty">No plan yet</span>}
      </div>
      <label className="wl-c-active">
        <input type="checkbox" checked={pendingActive === null ? item.active : pendingActive} disabled={busy} aria-label={'Actively watching ' + item.name}
          onChange={e => { setPendingActive(e.target.checked); onPatch({ active: e.target.checked }).then(() => setPendingActive(null)); }} />
        <span>Active</span>
      </label>
    </div>
    {notice && <div className="wl-notice" role="alert">{notice} <button type="button" className="tv-btn wl-dismiss" onClick={onDismiss}>Dismiss</button></div>}
    {opened && <div className="wl-body" id={body} hidden={!expanded}>
      <WlSummaryField item={item} draft={draft} setDraft={v => onDraft(v)} limit={limits.summary_max} hideValues={hideValues}
        saving={savingSummary} onSave={saveSummary} />
      <div className="wl-sec">
        <window.PageNotesPanel page={item.key} hideValues={hideValues} label={item.name + ' notes'} variant="page" />
      </div>
      <WlTrendDetail item={item} source={source} checking={checking} checkBusy={checkBusy} onCheck={onCheck} />
      <div className="wl-sec">
        <div className="wl-sec-title">Token</div>
        <div className="wl-muted">{item.chain_label}</div>
        <div className="wl-contract tv-num">{item.contract}</div>
        <div className="wl-actions"><button type="button" className="tv-btn" onClick={copyContract}>{copied ? 'Copied' : 'Copy contract'}</button></div>
      </div>
    </div>}
  </div>;
}

function WlAddForm({ chains, limits, onAdd }) {
  const [open, setOpen] = useWLState(false);
  const [name, setName] = useWLState('');
  const [chain, setChain] = useWLState(() => {
    try { const c = localStorage.getItem(WL_CHAIN_KEY); if (c && chains.some(x => x.key === c)) return c; } catch (e) { /* default */ }
    return chains.length ? chains[0].key : '';
  });
  const [contract, setContract] = useWLState('');
  const [busy, setBusy] = useWLState(false);
  const [error, setError] = useWLState('');
  const nameRef = useWLRef(null);
  useWLEffect(() => { if (open && nameRef.current) nameRef.current.focus(); }, [open]);

  async function submit(e) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    const r = await onAdd({ name, chain, contract: contract.trim() });
    setBusy(false);
    if (r && r.ok) {
      try { localStorage.setItem(WL_CHAIN_KEY, chain); } catch (err) { /* the choice lasts this visit */ }
      setName(''); setContract(''); setOpen(false);
    } else {
      setError((r && r.error) || "The token wasn't added.");
    }
  }

  if (!open) {
    return <div><button type="button" className="tv-btn primary" onClick={() => setOpen(true)}>+ Add token</button></div>;
  }
  return <form className="tv-card wl-add" onSubmit={submit} aria-label="Add a token to the watch list">
    <div className="wl-add-grid">
      <div className="wl-field">
        <label htmlFor="wl-add-name" className="wl-sec-title">Ticker or name</label>
        <input id="wl-add-name" ref={nameRef} className="tv-input" type="text" value={name} maxLength={limits.name_max * 2}
          placeholder="e.g. WIF" onChange={e => setName(e.target.value)} />
      </div>
      <div className="wl-field">
        <label htmlFor="wl-add-chain" className="wl-sec-title">Chain</label>
        <select id="wl-add-chain" className="tv-select" value={chain} onChange={e => setChain(e.target.value)}>
          {chains.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
      </div>
      <div className="wl-field wl-field--wide">
        <label htmlFor="wl-add-contract" className="wl-sec-title">Contract address</label>
        <input id="wl-add-contract" className="tv-input tv-num" type="text" value={contract} spellCheck={false} autoComplete="off"
          placeholder="0x... or the Solana mint" onChange={e => setContract(e.target.value)} />
      </div>
    </div>
    <div className="wl-muted">The ticker is also how the Trends scanner is matched, so use the scanner's name when the token is in it (BONK matches kBONK).</div>
    {error && <div className="wl-notice" role="alert">{error}</div>}
    <div className="wl-actions">
      <button type="submit" className="tv-btn primary" disabled={busy || !name.trim() || !contract.trim()}>{busy ? 'Adding' + WL_ELLIPSIS : 'Add'}</button>
      <button type="button" className="tv-btn" disabled={busy} onClick={() => { setOpen(false); setError(''); }}>Cancel</button>
    </div>
  </form>;
}

function WatchListScreen({ hideValues, refreshTrigger }) {
  const [state, setState] = useWLState({ status: 'loading', data: null });
  const [prices, setPrices] = useWLState({});
  const [expandedKeys, setExpandedKeys] = useWLState(wlReadExpanded);
  const [inactiveOpen, setInactiveOpen] = useWLState(() => wlReadFlag(WL_INACTIVE_KEY));
  const [busy, setBusy] = useWLState({});
  const [checking, setChecking] = useWLState(null);
  const [notices, setNotices] = useWLState({});
  const [flash, setFlash] = useWLState('');
  const [meterKey, setMeterKey] = useWLState(0);
  const [drafts, setDrafts] = useWLState({});          // key -> summary text being edited
  const aliveRef = useWLRef(true);
  const mutationsRef = useWLRef(0);                    // counts the replies that set the list, so an older read can't overwrite them
  const flashRef = useWLRef(0);
  const inactiveOpenRef = useWLRef(inactiveOpen);
  inactiveOpenRef.current = inactiveOpen;
  useWLEffect(() => { aliveRef.current = true; return () => { aliveRef.current = false; }; }, []);

  // A failed refresh keeps what is already shown.
  const load = useWLCallback(() => {
    const seen = mutationsRef.current;
    return wlRequest('GET', '/api/watchlist').then(res => {
      if (!aliveRef.current || !res || mutationsRef.current !== seen) return;
      if (res.status === 200 && wlIsList(res)) setState({ status: 'ok', data: res.data });
      else setState(prev => (prev.status === 'ok' ? prev : { status: 'error', data: null }));
    });
  }, []);
  useWLEffect(() => { load(); }, [refreshTrigger]);

  const items = state.status === 'ok' ? state.data.items : [];
  const activeKeys = items.filter(i => i.active).map(i => i.key).join(',');
  const allKeys = items.map(i => i.key).join(',');

  const loadPrices = useWLCallback(() => wlRequest('GET', '/api/watchlist/prices').then(res => {
    if (!aliveRef.current || !res || res.status !== 200 || !res.data || typeof res.data.prices !== 'object' || !res.data.prices) return;
    setPrices(res.data.prices);
  }), []);
  useWLEffect(() => {
    if (!activeKeys) return undefined;
    loadPrices();
    const t = setInterval(() => { if (document.visibilityState === 'visible') loadPrices(); }, WL_PRICE_POLL_MS);
    return () => clearInterval(t);
  }, [activeKeys, refreshTrigger]);

  // Keep every item's notes guarded: the browser asks before a reload while one has unsaved edits.
  useWLEffect(() => {
    if (!allKeys || typeof window.PageNotesShowPages !== 'function') return undefined;
    return window.PageNotesShowPages(allKeys.split(','));
  }, [allKeys]);

  function setNotice(key, msg) { setNotices(n => ({ ...n, [key]: msg })); }
  function applyList(res) { mutationsRef.current += 1; setState({ status: 'ok', data: res.data }); }

  function setDraftFor(key, value, clearIfSame) {
    setDrafts(d => {
      const drop = () => { if (!(key in d)) return d; const n = { ...d }; delete n[key]; return n; };
      if (clearIfSame) return d[key] === value ? drop() : d;
      return value === undefined ? drop() : { ...d, [key]: value };
    });
  }

  // A short message for screen readers and the eye; it clears itself.
  function showFlash(msg) {
    const id = ++flashRef.current;
    setFlash(msg);
    setTimeout(() => { if (aliveRef.current && flashRef.current === id) setFlash(''); }, 8000);
  }

  function setExpandedFor(key, on) {
    setExpandedKeys(prev => {
      const next = on ? (prev.indexOf(key) === -1 ? prev.concat([key]) : prev) : prev.filter(k => k !== key);
      wlWriteExpanded(next);
      return next;
    });
  }

  function toggle(key) {
    setExpandedFor(key, expandedKeys.indexOf(key) === -1);
    setMeterKey(k => k + 1);       // the image storage line re-reads after you open or close a row
  }

  async function patchItem(key, body) {
    setBusy(b => ({ ...b, [key]: true }));
    setNotice(key, '');
    const res = await wlRequest('PUT', '/api/watchlist/' + key, body);
    if (!aliveRef.current) return { ok: false };
    setBusy(b => ({ ...b, [key]: false }));
    if (res && res.status === 200 && wlIsList(res)) {
      applyList(res);
      if (typeof body.active === 'boolean') {
        const it = res.data.items.find(i => i.key === key);
        showFlash((it ? it.name : 'The token') + (body.active ? ' is active again.' : ' moved to Inactive.'));
        // The row is remounted in its new section; put the keyboard focus on it (or on the closed Inactive heading).
        setTimeout(() => {
          const sel = body.active || inactiveOpenRef.current ? '[data-key="' + key + '"] .wl-c-active input' : 'button.wl-sec-toggle';
          const el = document.querySelector(sel);
          if (el && el.focus) el.focus();
        }, 0);
      }
      return { ok: true };
    }
    const msg = wlError(res, "The change wasn't saved.");
    setNotice(key, msg);
    return { ok: false, error: msg };
  }

  async function checkTrend(key) {
    if (checking) return;
    setChecking(key);
    setNotice(key, '');
    const res = await wlRequest('POST', '/api/watchlist/' + key + '/check', undefined, WL_CHECK_TIMEOUT_MS);
    if (!aliveRef.current) return;
    setChecking(null);
    if (res && res.status === 200 && res.data && res.data.check) {
      mutationsRef.current += 1;
      setState(prev => (prev.status !== 'ok' ? prev : {
        status: 'ok', data: { ...prev.data, items: prev.data.items.map(i => (i.key === key ? { ...i, check: res.data.check } : i)) },
      }));
    } else {
      setNotice(key, wlError(res, "The trend check didn't finish."));
    }
  }

  async function addItem(body) {
    showFlash('');
    const res = await wlRequest('POST', '/api/watchlist', body);
    if (!aliveRef.current) return { ok: false };
    if (res && (res.status === 201 || res.status === 200) && wlIsList(res) && res.data.key) {
      applyList(res);
      setExpandedFor(res.data.key, true);
      const it = res.data.items.find(i => i.key === res.data.key);
      if (res.data.reactivated && it) showFlash(it.name + ' was inactive. It is back on your list with its notes and summary.');
      setTimeout(() => {
        const el = document.querySelector('[data-key="' + res.data.key + '"]');
        if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }, 50);
      return { ok: true };
    }
    if (res && res.status === 409 && res.data && res.data.key) {
      if (wlIsList(res)) applyList(res);
      setExpandedFor(res.data.key, true);
    }
    return { ok: false, error: wlError(res, "The token wasn't added.") };
  }

  function toggleInactive() {
    setInactiveOpen(v => { wlWriteFlag(WL_INACTIVE_KEY, !v); return !v; });
  }

  const active = items.filter(i => i.active);
  const inactive = items.filter(i => !i.active);
  const limits = state.status === 'ok' ? state.data.limits : { name_max: 40, summary_max: 160 };
  const chains = state.status === 'ok' ? state.data.chains : [];
  const renderRow = (item) => <WlItemRow key={item.key} item={item} expanded={expandedKeys.indexOf(item.key) !== -1}
    onToggle={() => toggle(item.key)} live={item.active ? prices[item.key] : undefined} busy={!!busy[item.key]} checking={checking === item.key}
    checkBusy={!!checking} notice={notices[item.key] || ''} limits={limits} hideValues={hideValues}
    draftRaw={drafts[item.key]} onDraft={(v, same) => setDraftFor(item.key, v, same)}
    onPatch={body => patchItem(item.key, body)} onCheck={() => checkTrend(item.key)} onDismiss={() => setNotice(item.key, '')} />;

  return <div className="wl-page">
    <div className="wl-top">
      <div>
        <div className="tv-page-title">Watch List</div>
        <div className="wl-sub">Tokens you are watching but don't hold. Open a row for your plan, notes and the trend in detail. Uncheck Active to move a token to Inactive and keep everything.</div>
      </div>
      {typeof window.ImageStorageMeter === 'function' &&
        <div className="wl-meter"><window.ImageStorageMeter refreshKey={String(refreshTrigger) + ':' + meterKey} /></div>}
    </div>

    {state.status === 'loading' && <div className="wl-muted" role="status">Loading the watch list{WL_ELLIPSIS}</div>}
    {state.status === 'error' && <div className="tv-card" role="alert">
      <div>Couldn't load the watch list.</div>
      <div className="wl-actions"><button type="button" className="tv-btn" onClick={load}>Try again</button></div>
    </div>}

    {state.status === 'ok' && <>
      <WlAddForm chains={chains} limits={limits} onAdd={addItem} />
      {flash && <div className="wl-flash" role="status">{flash}</div>}
      <div className="wl-sec-head">Watching ({active.length})</div>
      {active.length === 0 && <div className="wl-muted">{items.length === 0
        ? 'Nothing on your watch list yet. Add a token above.' : 'Nothing is active. Check Active on a token below to watch it again.'}</div>}
      <div className="wl-list">{active.map(renderRow)}</div>
      {inactive.length > 0 && <>
        <button type="button" className="wl-sec-head wl-sec-toggle" aria-expanded={inactiveOpen} aria-controls="wl-inactive" onClick={toggleInactive}>
          <span className="wl-chev" aria-hidden="true" />Inactive ({inactive.length})
        </button>
        <div className="wl-list" id="wl-inactive" hidden={!inactiveOpen}>{inactive.map(renderRow)}</div>
      </>}
    </>}
  </div>;
}

window.WatchListScreen = WatchListScreen;
