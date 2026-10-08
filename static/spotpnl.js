/* ===== SPOT P&L SCREEN — Playbook Phase 2 ===== */

// Mirrors SPOT_CHAINS in web_portfolio.py; the backend is the validation authority.
const SPOT_CHAINS = [
  { slug: 'ethereum', label: 'Ethereum' },
  { slug: 'base', label: 'Base' },
  { slug: 'arbitrum', label: 'Arbitrum' },
  { slug: 'bsc', label: 'BNB Chain' },
  { slug: 'robinhood', label: 'Robinhood Chain' },
  { slug: 'sonic', label: 'Sonic' },
  { slug: 'solana', label: 'Solana' },
];

// Spot stale-serve 3/3: how old the price shown in the Price column is.
// price_as_of (added in commit 2) is null for a manual-source or
// never-priced position - those render exactly as before. Returns null on a
// falsy/unparseable timestamp so the caller can skip the age line entirely
// rather than showing a nonsense value. ageSec is clamped to >= 0 to guard
// against client-clock skew making a just-fetched price look negative-old.
function fmtPriceAge(iso) {
  if (!iso) return null;
  const ts = Date.parse(iso);
  if (isNaN(ts)) return null;
  const ageSec = Math.max(0, (Date.now() - ts) / 1000);
  let label;
  if (ageSec < 60) label = Math.floor(ageSec) + 's ago';
  else if (ageSec < 3600) label = Math.floor(ageSec / 60) + 'm ago';
  else if (ageSec < 172800) label = Math.floor(ageSec / 3600) + 'h ago';
  else label = Math.floor(ageSec / 86400) + 'd ago';
  // 300s (5 min) — beyond several failed background-refresh cycles at the
  // backend's 60s serve-fresh TTL, worth flagging rather than just labeling.
  return { label, stale: ageSec > 300, ageSec };
}

// Holding book per position (HANDOFF_trading_performance.md rulings 1-2):
// PUT /api/spot/position-books; a missing book reads as 'trading'.
const SPOT_BOOK_OPTIONS = [{value:'trading',label:'Trading'},{value:'long_term',label:'Long-term'},{value:'bot_capital',label:'Bot capital'}];
const SPOT_BOOK_FILTERS = [{id:'all',label:'All'},{id:'trading',label:'Trading'},{id:'other',label:'Long-term & bot'}];

function spotBookOf(r) {
  return r && r.book ? r.book : 'trading';
}

function spotBookPasses(r, filter) {
  if (filter === 'trading') return spotBookOf(r) === 'trading';
  if (filter === 'other') return spotBookOf(r) !== 'trading';
  return true;
}

function spotReadBookFilter(key) {
  try {
    const v = localStorage.getItem(key);
    return SPOT_BOOK_FILTERS.some(f => f.id === v) ? v : 'all';
  } catch (_e) {
    return 'all';
  }
}

function spotWriteBookFilter(key, v) {
  try { localStorage.setItem(key, v); } catch (_e) { /* storage unavailable - the filter still applies */ }
}

function SpotBookChip({ book }) {
  if (book === 'long_term') return <span className="tv-chip accent" style={{ marginLeft:6 }}>Long-term</span>;
  if (book === 'bot_capital') return <span className="tv-chip adapt" style={{ marginLeft:6 }}>Bot capital</span>;
  return null;
}

function SpotBookFilterBar({ value, onChange, counts }) {
  return <div role="group" aria-label="Book filter" style={{ display:'flex', gap:4, marginBottom:12, flexWrap:'wrap' }}>
    {SPOT_BOOK_FILTERS.map(f => <button key={f.id} type="button" className="tv-btn" aria-pressed={value===f.id}
      style={{ fontSize:13, background:value===f.id?'var(--panel3)':'transparent', borderColor:value===f.id?'var(--accent-line)':'var(--line)',
        color:value===f.id?'var(--text)':'var(--text3)', fontWeight:value===f.id?600:400 }}
      onClick={() => onChange(f.id)}>{f.label + ' (' + ((counts && counts[f.id]) || 0) + ')'}</button>)}
  </div>;
}

// Controlled by row.book: a failed save keeps showing the old value.
function SpotBookSelect({ row, onSaved, onError }) {
  const [saving, setSaving] = useState(false);
  async function change(e) {
    const book = e.target.value;
    setSaving(true);
    try {
      const d = await api('/api/spot/position-books', {
        method: 'PUT',
        body: JSON.stringify({ position_key: row.position_key, book }),
      });
      // api() returns undefined (no throw) on a 401; a 400/500 throws.
      if (d === undefined || d.error) onError(extractApiErrorMessage(d));
      else onSaved(row.position_key, d.book);
    } catch (err) {
      onError(extractApiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }
  return <select className="tv-select" style={{ fontSize:13, padding:'4px 8px' }} value={spotBookOf(row)}
    disabled={saving} onChange={change} aria-label={'Book for ' + row.symbol}>
    {SPOT_BOOK_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
  </select>;
}

// ── Holdings helpers (Open positions and Trade History) ──
// Units: fewer decimals as the amount grows; the cell title keeps the full value.
function spotHoldFmtUnits(v) {
  const a = Math.abs(Number(v) || 0);
  return fmtNum(v, a >= 1000 ? 2 : a >= 1 ? 4 : 8);
}

// The chain part of a position_key ("chain address"); '' for symbol-only keys.
function spotHoldChainOf(row) {
  const key = String((row && row.position_key) || '');
  const i = key.indexOf(' ');
  return i === -1 ? '' : key.slice(0, i);
}

function spotHoldChainLabel(row) {
  const chain = spotHoldChainOf(row);
  return chain ? chainLabelFor(chain) : 'No chain';
}

// The contract-address part of a position_key, exactly as stored - never
// change case (Solana base58 is case-sensitive). '' for a symbol-only key.
// The no-whitespace / 32+ character guard keeps a symbol-only key that
// happens to contain a space from being read as "chain address".
function spotHoldAddressOf(row) {
  if (!spotHoldChainOf(row)) return '';
  const key = String(row.position_key);
  const address = key.slice(key.indexOf(' ') + 1);
  return address.length >= 32 && !/\s/.test(address) ? address : '';
}

// Copies text to the clipboard; resolves true when a copy path reported
// success, false otherwise - never throws. The async clipboard API needs a
// secure context (https on Railway); the execCommand fallback covers an
// http dev origin and puts keyboard focus back where it was.
function spotCopyText(text) {
  const fallback = () => {
    const prev = document.activeElement;
    const ta = document.createElement('textarea');
    try {
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      return document.execCommand('copy');
    } catch (_e) {
      return false;
    } finally {
      if (ta.parentNode) ta.parentNode.removeChild(ta);
      if (prev && prev.focus) prev.focus();
    }
  };
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(() => true, () => fallback());
    }
  } catch (_e) { /* fall through to the fallback */ }
  return Promise.resolve(fallback());
}

// Click-to-copy for a holding's contract address (Open positions and Trade
// History). A real button, so Tab then Enter or Space copies too; the
// browser's own tooltip shows the full address on hover (on a phone a tap
// copies). The "Copied" / "Copy failed" chip lasts 1500ms, like the
// Transactions tab's, but floats just above the label (absolutely
// positioned) so the Token column never widens and the table never
// reflows. Contract addresses are public token identifiers, not balances,
// so Hide values leaves them alone. Callers render this only when
// spotHoldAddressOf(row) is non-empty.
function SpotCopyAddress({ row, children }) {
  const [status, setStatus] = useState(null); // null | 'ok' | 'fail'
  const timer = React.useRef(null);
  const alive = React.useRef(true);
  useEffect(() => () => {
    alive.current = false;
    if (timer.current) clearTimeout(timer.current);
  }, []);
  const address = spotHoldAddressOf(row);
  const symbol = String(row.symbol || '').toUpperCase();
  const chain = spotHoldChainLabel(row);

  function copy(ev) {
    ev.stopPropagation();
    spotCopyText(address).then(ok => {
      if (!alive.current) return;
      if (timer.current) clearTimeout(timer.current);
      setStatus(ok ? 'ok' : 'fail');
      timer.current = setTimeout(() => { timer.current = null; setStatus(null); }, 1500);
    });
  }

  const tone = status === 'ok' ? 'var(--ok)' : 'var(--fail)';
  return <span style={{ position:'relative', display:'inline-block' }}>
    <button type="button" onClick={copy}
      title={'Copy contract address · ' + chain + ' · ' + address}
      aria-label={'Copy contract address for ' + symbol + ' on ' + chain}
      style={{ background:'none', border:'none', padding:0, margin:0, font:'inherit', color:'inherit', cursor:'pointer' }}>
      {children}
    </button>
    <span role="status" style={status ? { position:'absolute', left:'50%', bottom:'calc(100% + 4px)',
      transform:'translateX(-50%)', zIndex:2, whiteSpace:'nowrap', fontSize:11, fontWeight:600, lineHeight:'16px',
      padding:'1px 6px', borderRadius:6, background:'var(--bg)', border:'1px solid ' + tone, color:tone } : undefined}>
      {status === 'ok' ? 'Copied' : status === 'fail' ? 'Copy failed' : ''}
    </span>
  </span>;
}

// ── Open positions (Landing 2a, HANDOFF_spot_perps_rebuild.md 3.3) ─────────
// One flat row per position (token and chain). The grid below fits at 1250px
// and wider; narrower, each row becomes a stacked card with small labels
// (static/style.css, .spot-* rules), so the page never scrolls sideways. A
// row expands to its Book selector and notes journal (static/spotjournal.js).
// Landing 2a.1: the book is not in the table (only the expanded row's Book
// selector shows it), and the Trend column is wider, with left padding
// (.spot-trend) so its dots stand clear of % of spot.
// Token · Units · Avg cost · Price · Basis · Value · Unrealized · Unr % · Realized · % of spot · Trend · Trade opened
const SPOT_OPEN_GRID = 'minmax(140px,1.4fr) repeat(6,minmax(84px,1fr)) '
  + 'minmax(56px,0.6fr) minmax(84px,1fr) minmax(56px,0.6fr) 172px minmax(60px,0.6fr)';
const SPOT_ROW_LINE = '2px solid rgba(255,255,255,0.25)';
const SPOT_TREND_TFS = [['4h', '4H'], ['12h', '12H'], ['1d', '1D'], ['1w', '1W']];
const SPOT_TREND_WORD = { above: 'above', touch: 'touching', below: 'below' };
const SPOT_TREND_COLOR = { above: 'var(--ok)', touch: 'var(--warn)', below: 'var(--fail)' };
const SPOT_NOT_IN_SCANNER = "The Trends scanner reads Hyperliquid perp markets; this token isn't one of them, so its trend can't be shown here.";

// Avg cost and Price: 2 decimals from $100 up (the prototype's rule, so the
// grid fits at 1250px), else 4; fmtPrice handles sub-cent prices. The rule
// lives in static/utils.js (fmtTokenPrice) since Token Holdings shares it.
function spotFmtPx(v) {
  return fmtTokenPrice(v);
}

// "Sep 18" for a "YYYY-MM-DD" day (with the year when it isn't this year); null when unreadable.
function spotFmtDay(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s || ''));
  if (!m) return null;
  const d = new Date(+m[1], +m[2] - 1, +m[3]);
  const opts = { month: 'short', day: 'numeric' };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
  return d.toLocaleDateString('en-US', opts);
}

// The same for a full ISO time, in local time.
function spotFmtDate(iso) {
  const ms = Date.parse(iso || '');
  if (isNaN(ms)) return null;
  const d = new Date(ms);
  const opts = { month: 'short', day: 'numeric' };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
  return d.toLocaleDateString('en-US', opts);
}

// Open spot trades from GET /api/trading/trades, by position_key (FIFO keeps
// at most one open trade per position).
function spotOpenTrades(trades) {
  const map = {};
  for (const t of trades || []) {
    if (t && t.market === 'spot' && t.source === 'spot_tx' && t.status !== 'closed' && t.position_key) map[t.position_key] = t;
  }
  return map;
}

// "+$12.34" / "-$5.00" / "$0.00" (a value that rounds to zero cents gets no sign).
function spotSignedUsd(v) {
  const cents = Math.round(Number(v) * 100) / 100;
  if (!isFinite(cents) || cents === 0) return fmt(0);
  return (cents > 0 ? '+' : '') + fmt(cents);
}

// Open positions' Realized cell (Landing 18): the realized P&L of the CURRENT
// trade (its sells since the position last opened), from the open trade in
// GET /api/trading/trades (net_pnl; spot_trades.py splits FIFO's realized P&L
// per trade). lifetime = /api/spot/pnl's realized_pnl_usd (every sell of the
// token, earlier trades and orphan sells included), shown on hover when it
// differs. Under Hide values the amount, its sign and its colour are hidden,
// on hover too. Returns {text, color, title}.
function spotRealizedCell(t, tradesStatus, lifetime, hideValues) {
  const life = Number(lifetime);
  const hasLife = lifetime != null && isFinite(life);
  const lifeNote = differs => hasLife && differs
    ? 'All sells of this token, earlier trades included: ' + (hideValues ? 'amount hidden' : spotSignedUsd(life)) : null;
  const join = parts => parts.filter(Boolean).join(' · ');
  if (tradesStatus === 'loading') return { text: '…', color: undefined, title: 'Loading trades' };
  if (tradesStatus === 'error') return { text: '—', color: undefined, title: "Couldn't load trades" };
  if (!t) {
    return { text: '—', color: undefined,
             title: join(["No open trade: what's left is under 1% of the last trade's peak, so that trade counts as closed",
                          lifeNote(Math.round(life * 100) !== 0)]) };
  }
  const opened = spotFmtDay(t.opened_at);
  if (t.status !== 'partly_closed') {
    return { text: '—', color: undefined,
             title: join(['Nothing sold in this trade yet' + (opened ? ' (opened ' + opened + ')' : ''),
                          lifeNote(Math.round(life * 100) !== 0)]) };
  }
  const v = Number(t.net_pnl);
  if (t.net_pnl == null || !isFinite(v)) return { text: '—', color: undefined, title: 'No realized figure for this trade' };
  const cents = Math.round(v * 100);
  return {
    text: hideValues ? '••••' : spotSignedUsd(v),
    color: hideValues || cents === 0 ? undefined : cents > 0 ? 'var(--ok)' : 'var(--fail)',
    title: join(['Realized in this trade' + (opened ? ', sells since ' + opened : '') + ': '
                   + (hideValues ? 'amount hidden' : spotSignedUsd(v)),
                 lifeNote(Math.round(life * 100) !== cents)]),
  };
}

function SpotTrendDot({ pos }) {
  const color = SPOT_TREND_COLOR[pos];
  return <span style={{ width: 10, height: 10, borderRadius: 999, display: 'inline-block', flex: 'none',
    background: color || 'transparent', border: color ? 'none' : '1.5px solid rgba(255,255,255,0.6)' }} />;
}

// Trend dots (4H · 12H · 1D · 1W) from GET /api/spot/trend-dots, plus the Exit chip.
// trend = {status: 'loading' | 'ok' | 'error', symbols}.
function SpotTrendCell({ symbol, trend, exit, exitTip }) {
  let body;
  const key = String(symbol || '').trim().toUpperCase();
  const t = trend.status === 'ok' ? trend.symbols[key] : undefined;
  if (t === null) {
    body = <span style={{ fontSize: 12, color: 'var(--text3)' }} title={SPOT_NOT_IN_SCANNER}>Not in scanner</span>;
  } else if (!t) {
    const why = trend.status === 'loading' ? 'Loading the trend dots' : trend.status === 'error' ? "Couldn't load the trend dots" : 'No trend data';
    body = <span style={{ fontSize: 13, color: 'var(--text3)' }} title={why} aria-label={why}>—</span>;
  } else {
    const parts = SPOT_TREND_TFS.map(([tf, label]) => {
      const x = t.tf && t.tf[tf];
      return { tf, label, pos: x && SPOT_TREND_WORD[x.position] ? x.position : null };
    });
    const asOf = sjParseTime(t.as_of);
    const text = 'Price vs the noodle: ' + parts.map(p => p.label + ' ' + (p.pos ? SPOT_TREND_WORD[p.pos] : 'no data')).join(', ')
      + (t.scanner_symbol && String(t.scanner_symbol).toUpperCase() !== key ? ' · scanner market ' + t.scanner_symbol : '')
      + (isFinite(asOf) ? ' · as of ' + sjStamp(asOf) : '');
    body = <span role="img" aria-label={text} title={text} style={{ display: 'inline-flex' }}>
      {parts.map(p => <span key={p.tf} style={{ width: 24, height: 18, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
        <SpotTrendDot pos={p.pos} />
      </span>)}
    </span>;
  }
  return <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
    {body}
    {exit && <span className="tv-chip fail" title={exitTip} aria-label={'Exit signal: ' + exitTip} style={{ fontSize: 12, fontWeight: 600 }}>Exit</span>}
  </div>;
}

function SpotKpi({ label, value, color, sub }) {
  return <div className="tv-card" style={{ flex: '1 1 190px', minWidth: 0, padding: '14px 18px' }}>
    <div className="tv-label">{label}</div>
    <div className="tv-num" style={{ fontSize: 18, fontWeight: 700, marginTop: 6, color: color || 'var(--text)', overflowWrap: 'anywhere' }}>{value}</div>
    {sub && <div style={{ fontSize: 13, color: 'var(--text3)', marginTop: 4 }}>{sub}</div>}
  </div>;
}

// journal = the page-level journal state (SpotPnlScreen): openRows (Set of
// position_key), drafts / composing (maps by position_key) and their setters.
function SpotOpenPositions({ hideValues, refreshTrigger, journal }) {
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [stables, setStables] = useState(null);           // null until loaded
  const [updatesByKey, setUpdatesByKey] = useState({});
  const [notesError, setNotesError] = useState(false);
  const notesLoaded = React.useRef(false);
  const [trades, setTrades] = useState({ status: 'loading', open: {}, spot: null, start: null });
  const [trend, setTrend] = useState({ status: 'loading', symbols: {} });
  const [bookFilter, setBookFilterState] = useState(() => spotReadBookFilter('spotHoldingsBookFilter'));
  const [bookError, setBookError] = useState('');
  function setBookFilter(v) { setBookFilterState(v); spotWriteBookFilter('spotHoldingsBookFilter', v); }

  // Holdings gate the table; stablecoins, updates, trades and trend dots fill
  // in as they arrive. A failed refresh keeps the figures already shown.
  useEffect(() => {
    let alive = true;
    api('/api/spot/pnl').then(rows => {
      if (!alive) return;
      if (Array.isArray(rows)) { setData(rows); setLoadError(false); } else setLoadError(true);
    }).catch(() => { if (alive) setLoadError(true); });
    api('/api/spot/stablecoins').then(sc => {
      if (alive && sc && typeof sc.total_usd === 'number') setStables(sc.total_usd);
    }).catch(() => {});
    api('/api/spot/note-updates').then(list => {
      if (!alive) return;
      if (!Array.isArray(list)) { if (!notesLoaded.current) setNotesError(true); return; }
      const byKey = {};
      for (const u of list) (byKey[u.position_key] = byKey[u.position_key] || []).push(u);
      notesLoaded.current = true;
      setUpdatesByKey(byKey);
      setNotesError(false);
    }).catch(() => { if (alive && !notesLoaded.current) setNotesError(true); });
    api('/api/trading/trades').then(d => {
      if (!alive) return;
      if (!d || !Array.isArray(d.trades)) { setTrades(prev => prev.status === 'ok' ? prev : { ...prev, status: 'error' }); return; }
      const s = d.summary || {};
      setTrades({ status: 'ok', open: spotOpenTrades(d.trades), spot: s.spot || null, start: s.gate ? s.gate.start : null });
    }).catch(() => { if (alive) setTrades(prev => prev.status === 'ok' ? prev : { ...prev, status: 'error' }); });
    api('/api/spot/trend-dots').then(d => {
      if (!alive) return;
      if (d && d.symbols && typeof d.symbols === 'object') setTrend({ status: 'ok', symbols: d.symbols });
      else setTrend(prev => prev.status === 'ok' ? prev : { ...prev, status: 'error' });
    }).catch(() => { if (alive) setTrend(prev => prev.status === 'ok' ? prev : { ...prev, status: 'error' }); });
    return () => { alive = false; };
  }, [refreshTrigger]);

  if (data === null && !loadError) return <div style={{ padding:40, textAlign:'center', color:'var(--text4)' }}><div className="spin" style={{ display:'inline-block', width:24, height:24, border:'2px solid var(--line)', borderTopColor:'var(--accent)', borderRadius:'50%' }} /></div>;
  if (data === null) return <div style={{ color:'var(--fail)', padding:20 }}>Failed to load holdings.</div>;

  // Book filter: Cost basis, Current value and Unrealized follow it; % of spot
  // and Dry powder keep the all-books denominator (totalVal).
  const rows = data.filter(r => spotBookPasses(r, bookFilter));
  const bookCounts = { all: data.length, trading: data.filter(r => spotBookOf(r) === 'trading').length,
                       other: data.filter(r => spotBookOf(r) !== 'trading').length };
  const bookSuffix = bookFilter === 'all' ? '' : ' · ' + SPOT_BOOK_FILTERS.find(f => f.id === bookFilter).label;
  const totalCost = rows.reduce((s, r) => s + (r.total_cost_basis || 0), 0);
  // A null value or unrealized P&L means "unknown", not zero: excluded, never coerced.
  const viewVal = rows.reduce((s, r) => r.current_value_usd != null ? s + r.current_value_usd : s, 0);
  const totalUnr = rows.reduce((s, r) => r.unrealized_pnl_usd != null ? s + r.unrealized_pnl_usd : s, 0);
  const totalVal = data.reduce((s, r) => r.current_value_usd != null ? s + r.current_value_usd : s, 0);

  const mv = (v, d) => hideValues ? '••••' : fmt(v, d);
  const signColor = v => v >= 0 ? 'var(--ok)' : 'var(--fail)';

  // KPI: closed trading-book spot trades since the gate start (summary.spot).
  const sinceText = spotFmtDay(trades.start) || 'Sep 13';
  let tradesKpi = { value: '…', sub: null, color: null };
  if (trades.status === 'error') tradesKpi = { value: '—', sub: "Couldn't load trades", color: null };
  else if (trades.status === 'ok' && trades.spot) {
    const p = trades.spot;
    const net = p.net_pnl == null ? 0 : Number(p.net_pnl);
    tradesKpi = { value: hideValues ? '••••' : (net > 0 ? '+' : '') + fmt(net),
                  color: hideValues ? null : signColor(net),
                  sub: (p.closed_count || 0) + ' closed · ' + (p.win_count || 0) + 'W / ' + (p.loss_count || 0) + 'L' };
  }
  const dryPct = stables != null && totalVal + stables > 0 ? stables / (totalVal + stables) * 100 : null;

  function onBookSaved(key, book) {
    setData(prev => prev.map(r => r.position_key === key ? { ...r, book } : r));
    setBookError('');
  }
  function onNoteSaved(key, note) {
    setData(prev => prev.map(r => r.position_key === key ? { ...r, note } : r));
  }
  function onUpdatesChanged(key, fn) {
    setUpdatesByKey(prev => ({ ...prev, [key]: fn(prev[key] || []) }));
  }
  function toggle(key) {
    journal.setOpenRows(prev => { const n = new Set(prev); if (n.has(key)) n.delete(key); else n.add(key); return n; });
  }

  // Largest value first; positions with no price last.
  const byValue = (a, b) => (a.current_value_usd == null) - (b.current_value_usd == null)
    || (b.current_value_usd || 0) - (a.current_value_usd || 0);
  const sorted = rows.slice().sort(byValue);

  const pctCell = v => v != null ? (hideValues ? '••••' : fmtNum(v, 1) + '%') : '—';
  const ageTag = asOf => {
    // A fresh price (<=60s old) gets no tag at all. price_as_of is null for manual/never-priced rows.
    const priceAge = fmtPriceAge(asOf);
    return priceAge != null && priceAge.ageSec > 60
      ? <div style={{ fontSize:11, color: priceAge.stale ? 'var(--warn)' : 'var(--text3)', whiteSpace:'nowrap' }} title={asOf}>{priceAge.label}</div>
      : null;
  };
  const num = (label, content, style, title) => <div className="spot-cell tv-num" data-label={label} title={title}
    style={{ textAlign: 'right', ...style }}>{content}</div>;

  function positionRow(r) {
    const key = r.position_key;
    const sym = String(r.symbol || '').toUpperCase();
    const chainLabel = spotHoldChainLabel(r);
    const hasAddress = !!spotHoldAddressOf(r);
    const open = journal.openRows.has(key);
    const book = spotBookOf(r);
    const isTrading = book === 'trading';
    const t = trades.open[key];
    const exit = !!(isTrading && t && t.exit_signal);
    const flipped = t && t.weekly_trend ? spotFmtDate(t.weekly_trend.flipped_at) : null;
    const exitTip = 'Weekly trend flipped bearish' + (flipped ? ' on ' + flipped : '') + ', after this trade opened';
    const opened = !isTrading ? '—' : trades.status === 'loading' ? '…' : (t && spotFmtDay(t.opened_at)) || '—';
    const ups = updatesByKey[key] || [];
    const latestMs = ups.length ? sjParseTime(ups[0].created_at) : NaN;
    const summary = (r.note || '').trim();
    const hasNotes = !!(summary || ups.length);
    const tip = [summary ? sjPlain(r.note) : '', ups.length ? 'Latest ' + sjStamp(latestMs) + ': ' + sjPlain(ups[0].body) : '']
      .filter(Boolean).join(' · ');
    const priced = r.price_status === 'ok';
    const share = priced && totalVal > 0 ? r.current_value_usd / totalVal * 100 : null;
    const unrColor = r.unrealized_pnl_usd != null ? signColor(r.unrealized_pnl_usd) : undefined;
    const pctColor = r.unrealized_pct != null ? signColor(r.unrealized_pct) : undefined;
    const realized = spotRealizedCell(t, trades.status, r.realized_pnl_usd, hideValues);
    // price_status explains WHY there's no price: "no_source" (nothing
    // configured) vs "source_configured_no_result" (the lookup came back
    // empty). "manual" stays a plain em dash.
    const priceText = r.price_status === 'no_source' ? 'No price source'
      : r.price_status === 'source_configured_no_result' ? 'No price data'
      : r.current_price_usd != null ? (hideValues ? '••••' : spotFmtPx(r.current_price_usd)) : '—';

    const row = <div key={key} className="spot-grid-row" style={{ gridTemplateColumns: SPOT_OPEN_GRID, padding: '10px 16px',
                                                                  borderBottom: SPOT_ROW_LINE, fontSize: 13, color: 'var(--text2)' }}>
      <div className="spot-span" style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
        <button type="button" className="tv-btn" aria-expanded={open}
          aria-label={(open ? 'Hide' : 'Show') + ' notes for ' + sym + ' on ' + chainLabel} onClick={() => toggle(key)}
          style={{ width: 32, height: 32, padding: 0, flex: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center',
                   fontSize: 13, color: 'var(--text)' }}>{open ? '▾' : '▸'}</button>
        <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <span style={{ fontWeight: 700, color: 'var(--text)', fontSize: 14 }}>
            {hasAddress ? <SpotCopyAddress row={r}>{r.symbol}</SpotCopyAddress> : r.symbol}
          </span>
          <span style={{ fontSize: 12, color: 'var(--text3)', overflowWrap: 'anywhere' }}>
            {chainLabel}
            {hasNotes && <span> · <span role="img" aria-label={'Notes: ' + tip} title={tip}>✎</span>
              {isFinite(latestMs) && <span title={sjStamp(latestMs)}>{' ' + sjShortAge(latestMs)}</span>}</span>}
          </span>
        </div>
      </div>
      {num('Units', hideValues ? '••••' : spotHoldFmtUnits(r.units), null, hideValues ? undefined : fmtNum(r.units, 12))}
      {num('Avg cost', hideValues ? '••••' : spotFmtPx(r.avg_cost_usd))}
      {num('Price', <React.Fragment><div>{priceText}</div>{ageTag(r.price_as_of)}</React.Fragment>)}
      {num('Basis', mv(r.total_cost_basis))}
      {num('Value', r.current_value_usd != null ? mv(r.current_value_usd) : '—', { fontWeight: 600, color: 'var(--text)' })}
      {num('Unrealized', r.unrealized_pnl_usd != null ? (r.unrealized_pnl_usd >= 0 ? '+' : '') + mv(r.unrealized_pnl_usd) : '—', { color: unrColor })}
      {num('Unr %', r.unrealized_pct != null ? fmtPct(r.unrealized_pct) : '—', { color: pctColor })}
      {num('Realized', realized.text, { color: realized.color }, realized.title)}
      {num('% of spot', pctCell(share))}
      <div className="spot-cell spot-trend" data-label="Trend 4H · 12H · 1D · 1W">
        <SpotTrendCell symbol={r.symbol} trend={trend} exit={exit} exitTip={exitTip} />
      </div>
      <div className="spot-cell" data-label="Trade opened" style={{ color: 'var(--text3)' }}
        title={isTrading && t && t.opened_at ? 'Trade opened ' + t.opened_at : undefined}>{opened}</div>
    </div>;
    if (!open) return row;
    return <React.Fragment key={key}>
      {row}
      <div className="spot-detail" style={{ padding: '16px 16px 20px 56px', borderBottom: SPOT_ROW_LINE, background: 'var(--bg)',
                                            display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div className="spot-j75" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text3)' }}>{'Notes · ' + sym + ' · ' + chainLabel}</span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text3)' }}>
            Book <SpotBookSelect row={r} onSaved={onBookSaved} onError={setBookError} />
          </span>
        </div>
        {hasAddress
          ? <SpotJournal row={r} updates={ups} notesError={notesError} onSummarySaved={onNoteSaved} onUpdatesChanged={onUpdatesChanged}
              draft={journal.drafts[key] || ''} onDraftChange={v => journal.setDrafts(prev => ({ ...prev, [key]: v }))}
              composing={!!journal.composing[key]} setComposing={v => journal.setComposing(prev => ({ ...prev, [key]: v }))} />
          : <div style={{ fontSize: 13, color: 'var(--text3)' }}>Notes need a chain and contract address - add them on the Backfill tab.</div>}
      </div>
    </React.Fragment>;
  }

  const head = { fontSize: 12, lineHeight: '16px', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text3)' };
  const right = { textAlign: 'right' };

  return <div>
    <SpotBookFilterBar value={bookFilter} onChange={setBookFilter} counts={bookCounts} />
    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
      <SpotKpi label={'Cost basis' + bookSuffix} value={mv(totalCost)} />
      <SpotKpi label={'Current value' + bookSuffix} value={mv(viewVal)} />
      <SpotKpi label={'Unrealized P&L' + bookSuffix} value={(totalUnr > 0 && !hideValues ? '+' : '') + mv(totalUnr)}
        color={hideValues ? null : signColor(totalUnr)} />
      <SpotKpi label={'Spot trades since ' + sinceText} value={tradesKpi.value} color={tradesKpi.color} sub={tradesKpi.sub} />
      <SpotKpi label="Dry powder" value={stables == null ? '—' : mv(stables)}
        sub={dryPct == null ? null : (hideValues ? '••••' : fmtNum(dryPct, 1) + '%') + ' of spot plus cash'} />
    </div>
    {loadError && <div role="alert" style={{ color: 'var(--fail)', fontSize: 13, marginBottom: 8 }}>Refresh failed - showing the last loaded figures.</div>}
    <div style={{ fontSize: 12, color: 'var(--text3)', marginBottom: 8 }}>FIFO cost basis</div>

    {data.length === 0 ? <div style={{ color: 'var(--text4)', padding: 20, textAlign: 'center' }}>No open positions. Add buy transactions to get started.</div>
    : rows.length === 0 ? <div style={{ color: 'var(--text4)', padding: 20, textAlign: 'center' }}>No positions in this view.</div>
    : <div className="tv-card" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="spot-grid-row spot-grid-head" style={{ ...head, gridTemplateColumns: SPOT_OPEN_GRID, alignItems: 'end',
                                                               padding: '12px 16px', borderBottom: '2px solid rgba(255,255,255,0.35)' }}>
          <span>Token</span><span style={right}>Units</span><span style={right}>Avg cost</span>
          <span style={right}>Price</span><span style={right}>Basis</span><span style={right}>Value</span>
          <span style={right}>Unrealized</span><span style={right}>Unr %</span>
          <span style={right} title="Realized P&L from this trade's sells, since the position last opened. Hover a cell for every sell of the token, earlier trades included.">Realized</span>
          <span style={right} title="This position's value as a share of every priced spot position on this page (all books, whichever filter is on)">% of spot</span>
          <div className="spot-trend" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span>Trend</span>
            <span style={{ display: 'flex', fontSize: 11, letterSpacing: 0, textTransform: 'none' }}>
              {SPOT_TREND_TFS.map(([tf, label]) => <span key={tf} style={{ width: 24, textAlign: 'center' }}>{label}</span>)}
            </span>
          </div>
          <span>Trade opened</span>
        </div>
        {sorted.map(positionRow)}
      </div>}
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px 16px', fontSize: 13, color: 'var(--text3)', marginTop: 10 }}>
      <span>Trend dots, left to right 4H · 12H · 1D · 1W:</span>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><SpotTrendDot pos="above" />price above the noodle</span>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><SpotTrendDot pos="touch" />touching it</span>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><SpotTrendDot pos="below" />below it</span>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><SpotTrendDot pos={null} />no data</span>
      <span>· Exit: a Trading-book token whose weekly trend flipped bearish after the trade opened.</span>
    </div>
    <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 8 }}>This page shows tokens added manually via Spot Transactions. It does not show all connected wallet holdings.</div>
    {bookError && <div role="alert" style={{ color: 'var(--fail)', fontSize: 13, marginTop: 8 }}>{bookError}</div>}
  </div>;
}

// By token (History tab): every position with sells - today's Trade History
// table on the shared grid, so it turns into stacked cards below 1250px.
// bookFilter / setBookFilter come from the History tab (one filter for both views).
const SPOT_TOKEN_GRID = 'minmax(130px,1.2fr) minmax(130px,0.9fr) repeat(3,minmax(96px,1fr)) '
  + 'repeat(2,minmax(68px,0.6fr)) minmax(92px,0.7fr)';

function TradeHistory({ hideValues, bookFilter, setBookFilter }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [bookError, setBookError] = useState('');

  useEffect(() => {
    api('/api/spot/history').then(setData).catch(()=>{}).finally(()=>setLoading(false));
  }, []);

  if (loading) return <div style={{ padding:40, textAlign:'center', color:'var(--text4)' }}><div className="spin" style={{ display:'inline-block', width:24, height:24, border:'2px solid var(--line)', borderTopColor:'var(--accent)', borderRadius:'50%' }} /></div>;
  if (!data) return <div style={{ color:'var(--fail)', padding:20 }}>Failed to load history.</div>;

  const rows = data.filter(r => spotBookPasses(r, bookFilter));
  const bookCounts = { all: data.length, trading: data.filter(r => spotBookOf(r) === 'trading').length,
                       other: data.filter(r => spotBookOf(r) !== 'trading').length };
  const bookSuffix = bookFilter === 'all' ? '' : ' · ' + SPOT_BOOK_FILTERS.find(f => f.id === bookFilter).label;
  function onBookSaved(key, book) {
    setData(prev => prev.map(r => r.position_key === key ? { ...r, book } : r));
    setBookError('');
  }

  const mv = v => hideValues ? '••••' : fmt(v);
  // FIFO cost of the units actually sold (= proceeds − realized P&L).
  const costSold = r => r.cost_basis_sold ?? ((r.total_proceeds || 0) - (r.realized_pnl || 0));
  const totalCostSold = rows.reduce((s,r)=>s+(costSold(r)||0),0);
  const totalProc = rows.reduce((s,r)=>s+(r.total_proceeds||0),0);
  const totalReal = rows.reduce((s,r)=>s+(r.realized_pnl||0),0);
  // Masked values carry no sign and no sign color.
  const signed = v => hideValues ? mv(v) : (v>=0?'+':'') + mv(v);
  const signColor = v => hideValues ? 'var(--text)' : v>=0 ? 'var(--ok)' : 'var(--fail)';
  const head = { fontSize:12, lineHeight:'16px', fontWeight:600, letterSpacing:'0.06em', textTransform:'uppercase', color:'var(--text3)' };
  const right = { textAlign:'right' };
  const num = (label, content, style, title) => <div className="spot-cell tv-num" data-label={label} title={title}
    style={{ textAlign:'right', ...style }}>{content}</div>;

  return <div>
    <SpotBookFilterBar value={bookFilter} onChange={setBookFilter} counts={bookCounts} />
    <div style={{ display:'flex', gap:10, flexWrap:'wrap', marginBottom:16 }}>
      {[{l:'Cost of Sold' + bookSuffix,v:mv(totalCostSold)},{l:'Total Proceeds' + bookSuffix,v:mv(totalProc)},
        {l:'Realized P&L' + bookSuffix,v:signed(totalReal),c:signColor(totalReal)},
      ].map(s => <div key={s.l} className="tv-card" style={{ flex:'1 1 190px', minWidth:0 }}>
        <div className="tv-label" style={{ marginBottom:4 }}>{s.l}</div>
        <div className="tv-num" style={{ fontSize:16, fontWeight:700, color:s.c||'var(--text)', overflowWrap:'anywhere' }}>{s.v}</div>
      </div>)}
    </div>
    {data.length === 0 ? <div style={{ color:'var(--text4)', padding:20, textAlign:'center' }}>No closed positions yet.</div>
    : rows.length === 0 ? <div style={{ color:'var(--text4)', padding:20, textAlign:'center' }}>No positions in this view.</div>
    : <div className="tv-card" style={{ padding:0, overflow:'hidden' }}>
        <div className="spot-grid-row spot-grid-head" style={{ ...head, gridTemplateColumns: SPOT_TOKEN_GRID, alignItems:'end',
                                                               padding:'12px 16px', borderBottom:'2px solid rgba(255,255,255,0.35)' }}>
          <span>Token</span><span>Book</span><span style={right}>Cost of sold</span><span style={right}>Proceeds</span>
          <span style={right}>Realized P&L</span><span style={right}>ROI %</span><span style={right}>% sold</span><span className="spot-pad-left">Last sell</span>
        </div>
        {rows.map(r => {
          const c = signColor(r.realized_pnl);
          const pct = r.pct_sold;
          const over = pct != null && pct > 100.05;
          return <div key={r.position_key} className="spot-grid-row" style={{ gridTemplateColumns: SPOT_TOKEN_GRID, padding:'10px 16px',
                                                                              borderBottom: SPOT_ROW_LINE, fontSize:13, color:'var(--text2)' }}>
            <div className="spot-span" style={{ minWidth:0 }}>
              <span style={{ fontWeight:700, color:'var(--text)', fontSize:14 }}>
                {spotHoldAddressOf(r) ? <SpotCopyAddress row={r}>{r.symbol}</SpotCopyAddress> : r.symbol}
              </span>
              <SpotBookChip book={spotBookOf(r)} />
              <div style={{ fontSize:12, color:'var(--text3)' }}>{spotHoldChainLabel(r)}</div>
            </div>
            <div className="spot-cell" data-label="Book"><SpotBookSelect row={r} onSaved={onBookSaved} onError={setBookError} /></div>
            {num('Cost of sold', mv(costSold(r)))}
            {num('Proceeds', mv(r.total_proceeds))}
            {num('Realized P&L', signed(r.realized_pnl), { color:c, fontWeight:600 })}
            {num('ROI %', hideValues ? '••%' : fmtPct(r.roi_pct), { color:c })}
            {num('% sold', pct == null ? '—' : hideValues ? '••%' : over ? '⚠ ' + Math.round(pct) + '%' : pct.toFixed(1) + '%',
                 { color: hideValues ? 'var(--text)' : over ? 'var(--warn)' : 'var(--text3)' },
                 !hideValues && over ? 'More units sold than bought — a buy is missing' : undefined)}
            <div className="spot-cell spot-pad-left" data-label="Last sell" style={{ color:'var(--text3)' }}>{r.last_sell_date || '—'}</div>
          </div>;
        })}
      </div>}
    {bookError && <div role="alert" style={{ color:'var(--fail)', fontSize:13, marginTop:8 }}>{bookError}</div>}
  </div>;
}

// The History tab (Landing 2b, HANDOFF_spot_perps_rebuild.md 3.3): By trade
// (static/spothistory.js) or By token (TradeHistory), with one book filter
// for both.
const SPOT_HISTORY_VIEWS = [{ id: 'trade', label: 'By trade' }, { id: 'token', label: 'By token' }];

function spotReadHistoryView() {
  try { return localStorage.getItem('spotHistoryView') === 'token' ? 'token' : 'trade'; } catch (_e) { return 'trade'; }
}

function SpotHistoryTab({ hideValues, refreshTrigger, journal }) {
  const [view, setViewState] = useState(() => spotReadHistoryView());
  const [bookFilter, setBookFilterState] = useState(() => spotReadBookFilter('spotHistoryBookFilter'));
  function setView(v) {
    setViewState(v);
    try { localStorage.setItem('spotHistoryView', v); } catch (_e) { /* the view still changes */ }
  }
  function setBookFilter(v) { setBookFilterState(v); spotWriteBookFilter('spotHistoryBookFilter', v); }
  return <div>
    <div role="group" aria-label="History view" style={{ display:'flex', gap:4, marginBottom:12, flexWrap:'wrap' }}>
      {SPOT_HISTORY_VIEWS.map(v => <button key={v.id} type="button" className="tv-btn" aria-pressed={view === v.id}
        style={{ fontSize:13, background: view === v.id ? 'var(--panel3)' : 'transparent',
                 borderColor: view === v.id ? 'var(--accent-line)' : 'var(--line)',
                 color: view === v.id ? 'var(--text)' : 'var(--text3)', fontWeight: view === v.id ? 600 : 400 }}
        onClick={() => setView(v.id)}>{v.label}</button>)}
    </div>
    {view === 'trade'
      ? <SpotHistoryByTrade hideValues={hideValues} refreshTrigger={refreshTrigger} bookFilter={bookFilter}
          setBookFilter={setBookFilter} journal={journal} />
      : <TradeHistory hideValues={hideValues} bookFilter={bookFilter} setBookFilter={setBookFilter} />}
  </div>;
}

// Extracts a clean, backend-authored message from any of api()'s three
// outcomes: a thrown Error (api() throws on any non-2xx, 400 and 500 alike,
// with the RAW response text as the message - try to pull its JSON `error`
// field so the backend's actual sentence is shown instead of a stringified
// JSON blob, falling back to the raw text if the body wasn't JSON), a
// resolved response object carrying an `error` field, or `undefined` (what
// api() returns, without throwing, on a 401 - session expiry, not a generic
// failure, and must not be shown as one).
function extractApiErrorMessage(x) {
  if (x === undefined) return 'Not authorised — please sign in again.';
  if (x instanceof Error) {
    try {
      const parsed = JSON.parse(x.message);
      if (parsed && parsed.error) return String(parsed.error);
    } catch (_e) { /* not JSON - fall through to the raw text */ }
    return x.message || String(x);
  }
  if (x && x.error) return String(x.error);
  return 'Unknown error.';
}

function chainLabelFor(slug) {
  const c = SPOT_CHAINS.find(c => c.slug === slug);
  return c ? c.label : slug;
}

// Transactions (Landing 2b): Date · Token · Side · Units · Price · Total ·
// Chain · Platform · Notes, on the shared grid (stacked cards below 1250px).
// The Token cell copies the contract address with SpotCopyAddress (a real
// button, so the keyboard works too); a row without both a chain and an
// address shows the plain symbol.
const SPOT_TX_GRID = 'minmax(92px,0.8fr) minmax(90px,0.9fr) minmax(56px,0.5fr) minmax(90px,1fr) minmax(84px,0.9fr) '
  + 'minmax(90px,1fr) minmax(84px,0.8fr) minmax(90px,0.9fr) minmax(110px,1.2fr) 108px';

function SpotTxTokenCell({ row }) {
  const pseudo = { position_key: row.chain && row.contract_address ? row.chain + ' ' + row.contract_address : String(row.symbol || ''),
                   symbol: row.symbol };
  return <div className="spot-cell" data-label="Token" style={{ fontWeight:700, color:'var(--text)' }}>
    {spotHoldAddressOf(pseudo) ? <SpotCopyAddress row={pseudo}>{row.symbol}</SpotCopyAddress> : row.symbol}
  </div>;
}

function Transactions({ hideValues }) {
  const [rows, setRows] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState(null);
  const [form, setForm] = useState({ trade_date: new Date().toISOString().slice(0,10), symbol:'', side:'buy', units:'', price_usd:'', platform:'', notes:'', chain:'', contract_address:'' });
  const [err, setErr] = useState('');
  const [saving, setSaving] = useState(false);
  const [csvImporting, setCsvImporting] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [copyLabel, setCopyLabel] = useState('Copy for Sheets');
  const [copyErr, setCopyErr] = useState('');
  const [deleteAllModal, setDeleteAllModal] = useState(false);
  const [deleteAllInput, setDeleteAllInput] = useState('');
  const [deleteAllError, setDeleteAllError] = useState('');
  const [deleteAllBusy, setDeleteAllBusy] = useState(false);

  // Sort state
  const [sortCol, setSortCol] = useState('date');
  const [sortDir, setSortDir] = useState('desc');

  // Filter state
  const [filterFrom, setFilterFrom]       = useState('');
  const [filterTo, setFilterTo]           = useState('');
  const [filterSide, setFilterSide]       = useState('all');
  const [filterToken, setFilterToken]     = useState('');
  const [filterMinAmt, setFilterMinAmt]   = useState('');
  const [filterMaxAmt, setFilterMaxAmt]   = useState('');
  const [filterPlatform, setFilterPlatform] = useState('');

  const mv  = v => hideValues ? '••••' : fmt(v);
  const mvn = (v, d) => hideValues ? '••••' : fmtNum(v, d || 8);

  // Parse M/D/YYYY or YYYY-MM-DD to a Date object for sorting/filtering
  function parseDate(s) {
    if (!s) return null;
    const md = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    if (md) return new Date(parseInt(md[3]), parseInt(md[1]) - 1, parseInt(md[2]));  // M/D/YYYY
    const iso = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (iso) return new Date(parseInt(iso[1]), parseInt(iso[2]) - 1, parseInt(iso[3]));
    return null;
  }
  // Convert stored M/D/YYYY (or ISO) → YYYY-MM-DD for <input type="date">
  function toIsoDate(s) {
    const d = parseDate(s);
    if (!d) return s || '';
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  function load() {
    setLoading(true);
    api('/api/spot/transactions').then(setRows).catch(()=>{}).finally(()=>setLoading(false));
  }
  useEffect(load, []);

  function openAdd() {
    setEditId(null);
    setEditingId(null);
    setForm({ trade_date: new Date().toISOString().slice(0,10), symbol:'', side:'buy', units:'', price_usd:'', platform:'', notes:'', chain:'', contract_address:'' });
    setErr(''); setShowForm(true);
  }
  function openEdit(r) {
    setEditId(r.id);
    setEditingId(r.id);
    setShowForm(false);
    setForm({ trade_date: toIsoDate(r.trade_date), symbol: r.symbol, side: r.side, units: String(r.units), price_usd: String(r.price_usd), platform: r.platform||'', notes: r.notes||'', chain: r.chain||'', contract_address: r.contract_address||'' });
    setErr('');
  }

  useEffect(() => {
    if (!editingId) return;
    const t = setTimeout(() => {
      document.getElementById(`edit-row-${editingId}`)?.scrollIntoView({ behavior:'smooth', block:'nearest' });
    }, 30);
    return () => clearTimeout(t);
  }, [editingId]);

  async function save() {
    if (!form.trade_date || !form.symbol || !form.units || !form.price_usd) { setErr('Date, Symbol, Units, and Total are required.'); return; }
    const chainVal = form.chain.trim();
    const addressVal = form.contract_address.trim();
    if (Boolean(chainVal) !== Boolean(addressVal)) { setErr('Chain and Contract Address must both be filled in, or both left blank.'); return; }
    setSaving(true); setErr('');
    try {
      const payload = { ...form, symbol: form.symbol.trim().toUpperCase(), chain: chainVal, contract_address: addressVal };
      const url = editId ? `/api/spot/transactions/${editId}` : '/api/spot/transactions';
      const method = editId ? 'PUT' : 'POST';
      const d = await api(url, { method, body: JSON.stringify(payload) });
      if (d === undefined || d.error) { setErr(extractApiErrorMessage(d)); return; }
      setEditingId(null); setEditId(null); setShowForm(false);
      load();
    } catch(e) { setErr(extractApiErrorMessage(e)); } finally { setSaving(false); }
  }

  async function del(id) {
    if (!confirm('Delete this transaction?')) return;
    await api(`/api/spot/transactions/${id}`, { method:'DELETE' }).catch(()=>{});
    load();
  }

  async function importCsv(e) {
    const file = e.target.files[0]; if (!file) return;
    setCsvImporting(true);
    const fd = new FormData(); fd.append('file', file);
    try {
      const res = await fetch('/api/spot/import-csv', { method:'POST', body: fd });
      if (!res.ok) { const d = await res.json().catch(()=>({})); alert(d.error || 'Import failed'); }
      else load();
    } catch(ex) { alert(String(ex)); } finally { setCsvImporting(false); e.target.value = ''; }
  }

  function handleSort(col) {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortCol(col); setSortDir('desc'); }
  }

  const hasActiveFilters = filterFrom || filterTo || filterSide !== 'all' || filterToken || filterMinAmt || filterMaxAmt || filterPlatform;

  function clearFilters() {
    setFilterFrom(''); setFilterTo(''); setFilterSide('all');
    setFilterToken(''); setFilterMinAmt(''); setFilterMaxAmt(''); setFilterPlatform('');
  }

  // Filter → sort pipeline
  const processed = useMemo(() => {
    if (!rows) return [];
    let out = [...rows];

    if (filterFrom) { const ff = parseDate(filterFrom); out = out.filter(r => { const d = parseDate(r.trade_date); return d && ff ? d >= ff : true; }); }
    if (filterTo)   { const ft = parseDate(filterTo);   out = out.filter(r => { const d = parseDate(r.trade_date); return d && ft ? d <= ft : true; }); }
    if (filterSide !== 'all')    out = out.filter(r => r.side === filterSide);
    if (filterToken.trim()) {
      const q = filterToken.trim().toLowerCase();
      out = out.filter(r => (r.symbol||'').toLowerCase().includes(q));
    }
    if (filterMinAmt !== '')     out = out.filter(r => (parseFloat(r.price_usd)||0) >= parseFloat(filterMinAmt));
    if (filterMaxAmt !== '')     out = out.filter(r => (parseFloat(r.price_usd)||0) <= parseFloat(filterMaxAmt));
    if (filterPlatform.trim()) {
      const q = filterPlatform.trim().toLowerCase();
      out = out.filter(r => (r.platform||'').toLowerCase().includes(q));
    }

    out.sort((a, b) => {
      let av, bv;
      switch (sortCol) {
        case 'date':     av = (parseDate(a.trade_date) || new Date(0)).getTime(); bv = (parseDate(b.trade_date) || new Date(0)).getTime(); break;
        case 'side':     av = a.side||''; bv = b.side||''; break;
        case 'token':    av = a.symbol||''; bv = b.symbol||''; break;
        case 'tx_amt':   av = parseFloat(a.price_usd)||0; bv = parseFloat(b.price_usd)||0; break;
        case 'platform': av = a.platform ? a.platform.toLowerCase() : '￿'; bv = b.platform ? b.platform.toLowerCase() : '￿'; break;
        default:         av = 0; bv = 0;
      }
      if (typeof av === 'string') { av = av.toLowerCase(); bv = bv.toLowerCase(); }
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sortDir === 'asc' ? cmp : -cmp;
    });

    return out;
  }, [rows, sortCol, sortDir, filterFrom, filterTo, filterSide, filterToken, filterMinAmt, filterMaxAmt, filterPlatform]);

  function exportCsv() {
    const escape = v => `"${String(v||'').replace(/"/g,'""')}"`;
    const fmtDate = d => d || '';  // stored as D/M/YYYY already
    const today = new Date().toISOString().slice(0,10);
    const headers = ['Date','Type','Symbol','Units','Unit_Price','Tx Amount','Platform','Notes'];
    const lines = [headers.join(','), ...processed.map(r => {
      const txAmt  = parseFloat(r.price_usd) || 0;
      const unitPr = r.units > 0 ? txAmt / r.units : 0;
      return [fmtDate(r.trade_date),
              (r.side||'').charAt(0).toUpperCase()+(r.side||'').slice(1),
              r.symbol||'',
              r.units||0,
              unitPr.toFixed(4),
              txAmt.toFixed(2),
              escape(r.platform),
              escape(r.notes)].join(',');
    })];
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `spot_transactions_${today}.csv`; a.click();
    URL.revokeObjectURL(url);
  }

  async function copyForSheets() {
    setCopyErr('');
    const headers = ['Date','Type','Symbol','Units','Unit Price','Tx Amount','Platform','Notes'];
    const lines = [headers.join('\t'), ...processed.map(r => {
      const txAmt  = parseFloat(r.price_usd) || 0;
      const unitPr = r.units > 0 ? txAmt / r.units : 0;
      return [r.trade_date||'',
              (r.side||'').charAt(0).toUpperCase()+(r.side||'').slice(1),
              r.symbol||'',
              r.units||0,
              unitPr.toFixed(4),
              txAmt.toFixed(2),
              r.platform||'',
              r.notes||''].join('\t');
    })];
    try {
      await navigator.clipboard.writeText(lines.join('\n'));
      setCopyLabel('✓ Copied!');
      setTimeout(() => setCopyLabel('Copy for Sheets'), 2000);
    } catch (_e) {
      setCopyErr('Copy failed — try Export CSV instead.');
    }
  }

  async function deleteAll() {
    setDeleteAllBusy(true); setDeleteAllError('');
    try {
      const d = await api('/api/spot/transactions/all', { method: 'DELETE' });
      if (d.error) { setDeleteAllError(d.error); return; }
      setRows([]);
      setDeleteAllModal(false);
      setDeleteAllInput('');
    } catch(e) { setDeleteAllError(String(e)); }
    finally { setDeleteAllBusy(false); }
  }

  // A plain function, not a nested component: a component defined inside
  // Transactions would be a new type on every render, so React would remount
  // the button and keyboard focus would be lost after each sort.
  function sortTh(col, label, right) {
    const active = sortCol === col;
    return <button key={col} type="button" onClick={() => handleSort(col)}
      aria-label={'Sort by ' + label + (active ? (sortDir === 'asc' ? ', ascending' : ', descending') : '')}
      style={{ background:'none', border:'none', padding:0, margin:0, font:'inherit', letterSpacing:'inherit',
               textTransform:'inherit', textAlign: right ? 'right' : 'left', cursor:'pointer', userSelect:'none',
               whiteSpace:'nowrap', color: active ? 'var(--text)' : 'inherit' }}>
      {label}{active ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
    </button>;
  }

  const lbl = (t) => <div style={{ fontSize:11, color:'var(--text4)', marginBottom:3 }}>{t}</div>;

  return <div>
    {/* Delete-all modal */}
    {deleteAllModal && <div style={{ position:'fixed', inset:0, background:'rgba(0,0,0,0.6)', zIndex:1000, display:'flex', alignItems:'center', justifyContent:'center' }}>
      <div className="tv-card" style={{ width:'min(420px, calc(100vw - 32px))', padding:24, display:'flex', flexDirection:'column', gap:14 }}>
        <div style={{ fontSize:16, fontWeight:700 }}>Delete all transactions?</div>
        <div style={{ fontSize:13, color:'var(--text3)', lineHeight:1.6 }}>
          This will permanently delete every spot transaction. This cannot be undone. Type <strong>DELETE ALL</strong> below to confirm.
        </div>
        <input className="tv-input" placeholder="Type DELETE ALL" value={deleteAllInput}
          onChange={e => { setDeleteAllInput(e.target.value); setDeleteAllError(''); }}
          style={{ fontFamily:'Fira Code, monospace' }} />
        {deleteAllError && <div style={{ color:'var(--fail)', fontSize:12 }}>{deleteAllError}</div>}
        <div style={{ display:'flex', gap:8 }}>
          <button className="tv-btn danger" disabled={deleteAllInput !== 'DELETE ALL' || deleteAllBusy} onClick={deleteAll}>
            {deleteAllBusy ? 'Deleting…' : 'Confirm Delete'}
          </button>
          <button className="tv-btn" onClick={() => { setDeleteAllModal(false); setDeleteAllInput(''); setDeleteAllError(''); }}>Cancel</button>
        </div>
      </div>
    </div>}

    {/* Actions bar */}
    <div style={{ display:'flex', gap:8, marginBottom:12, alignItems:'center', flexWrap:'wrap' }}>
      <button className="tv-btn primary" onClick={openAdd}>+ Add Transaction</button>
      <label className="tv-btn" style={{ cursor:'pointer' }}>
        {csvImporting ? 'Importing…' : '⬆ Import CSV'}
        <input type="file" accept=".csv" style={{ display:'none' }} onChange={importCsv} />
      </label>
      <button className="tv-btn" onClick={exportCsv} disabled={!processed.length}>⬇ Export CSV</button>
      <button className="tv-btn" onClick={copyForSheets} disabled={!processed.length}>{copyLabel}</button>
      {copyErr && <span style={{ fontSize:12, color:'var(--fail)' }}>{copyErr}</span>}
      <button className="tv-btn danger" onClick={() => { setDeleteAllModal(true); setDeleteAllInput(''); setDeleteAllError(''); }}
        disabled={!rows || rows.length === 0}>
        Delete All
      </button>
    </div>

    {/* Add Transaction form */}
    {showForm && <div className="tv-card" style={{ marginBottom:16 }}>
      <div style={{ fontSize:14, fontWeight:600, marginBottom:12 }}>Add Transaction</div>
      <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(140px,1fr))', gap:10, marginBottom:10 }}>
        <div>{lbl('Date')}<input className="tv-input" type="date" value={form.trade_date} onChange={e => setForm({...form,trade_date:e.target.value})} /></div>
        <div>{lbl('Symbol *')}<input className="tv-input" placeholder="BTC" value={form.symbol} onChange={e => setForm({...form,symbol:e.target.value})} /></div>
        <div>{lbl('Side')}<select className="tv-select" value={form.side} onChange={e => setForm({...form,side:e.target.value})} style={{ width:'100%' }}>
          <option value="buy">Buy</option><option value="sell">Sell</option>
        </select></div>
        <div>{lbl('Units *')}<input className="tv-input" type="number" value={form.units} onChange={e => setForm({...form,units:e.target.value})} /></div>
        <div>{lbl('Total (USD) *')}
          <input className="tv-input" type="number" placeholder="Total paid incl. fees" value={form.price_usd} onChange={e => setForm({...form,price_usd:e.target.value})} />
          <div style={{ fontSize:10, color:'var(--text4)', marginTop:3 }}>Total USD sent/received including fees &amp; slippage</div></div>
        <div>{lbl('Platform')}<input className="tv-input" placeholder="e.g. Binance" value={form.platform} onChange={e => setForm({...form,platform:e.target.value})} /></div>
        <div>{lbl('Chain')}<select className="tv-select" value={form.chain} onChange={e => setForm({...form,chain:e.target.value})} style={{ width:'100%' }}>
          <option value="">—</option>
          {SPOT_CHAINS.map(c => <option key={c.slug} value={c.slug}>{c.label}</option>)}
        </select></div>
        <div style={{ gridColumn:'span 2' }}>{lbl('Contract Address')}<input className="tv-input" placeholder="0x… or Solana address" value={form.contract_address} onChange={e => setForm({...form,contract_address:e.target.value})} /></div>
        <div style={{ gridColumn:'span 2' }}>{lbl('Notes')}<input className="tv-input" value={form.notes} onChange={e => setForm({...form,notes:e.target.value})} /></div>
      </div>
      {err && <div style={{ color:'var(--fail)', fontSize:12, marginBottom:8 }}>{err}</div>}
      <div style={{ display:'flex', gap:8 }}>
        <button className="tv-btn primary" onClick={save} disabled={saving}>{saving?'Saving…':'Save'}</button>
        <button className="tv-btn" onClick={() => setShowForm(false)}>Cancel</button>
      </div>
    </div>}

    {/* Filter bar */}
    {rows && rows.length > 0 && <div className="tv-card" style={{ marginBottom:12, padding:'10px 14px' }}>
      <div style={{ display:'flex', gap:10, flexWrap:'wrap', alignItems:'flex-end' }}>
        <div>{lbl('From')}<input className="tv-input" type="date" value={filterFrom} style={{ width:130 }} onChange={e => setFilterFrom(e.target.value)} /></div>
        <div>{lbl('To')}<input className="tv-input" type="date" value={filterTo} style={{ width:130 }} onChange={e => setFilterTo(e.target.value)} /></div>
        <div>{lbl('Side')}
          <div style={{ display:'flex', gap:0 }}>
            {['all','buy','sell'].map(s =>
              <button key={s} onClick={() => setFilterSide(s)}
                style={{ padding:'4px 10px', fontSize:12, cursor:'pointer', borderRadius: s==='all'?'4px 0 0 4px':s==='sell'?'0 4px 4px 0':'0',
                  background: filterSide===s ? 'var(--accent)' : 'var(--panel2)',
                  color: filterSide===s ? '#000' : 'var(--text)',
                  border: `1px solid ${filterSide===s ? 'var(--accent)' : 'var(--line)'}`,
                  borderLeft: s!=='all' ? 'none' : undefined }}>
                {s.charAt(0).toUpperCase()+s.slice(1)}
              </button>
            )}
          </div>
        </div>
        <div>{lbl('Token')}<input className="tv-input" placeholder="Filter…" value={filterToken} style={{ width:90 }} onChange={e => setFilterToken(e.target.value)} /></div>
        <div>{lbl('Total min')}<input className="tv-input" type="number" placeholder="0" value={filterMinAmt} style={{ width:90 }} onChange={e => setFilterMinAmt(e.target.value)} /></div>
        <div>{lbl('Total max')}<input className="tv-input" type="number" placeholder="∞" value={filterMaxAmt} style={{ width:90 }} onChange={e => setFilterMaxAmt(e.target.value)} /></div>
        <div>{lbl('Platform')}<input className="tv-input" placeholder="Filter…" value={filterPlatform} style={{ width:100 }} onChange={e => setFilterPlatform(e.target.value)} /></div>
      </div>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginTop:8 }}>
        <span style={{ fontSize:12, color:'var(--text4)' }}>{processed.length} transaction{processed.length!==1?'s':''}</span>
        {hasActiveFilters && <button style={{ background:'none', border:'none', color:'var(--accent)', fontSize:12, cursor:'pointer' }} onClick={clearFilters}>Clear filters</button>}
      </div>
    </div>}

    {/* Table */}
    {loading ? <div style={{ padding:40, textAlign:'center', color:'var(--text4)' }}><div className="spin" style={{ display:'inline-block', width:24, height:24, border:'2px solid var(--line)', borderTopColor:'var(--accent)', borderRadius:'50%' }} /></div>
    : !rows || rows.length === 0
      ? <div style={{ color:'var(--text4)', padding:20, textAlign:'center' }}>No transactions yet.</div>
      : processed.length === 0
        ? <div style={{ color:'var(--text4)', padding:20, textAlign:'center' }}>No transactions match the current filters.</div>
        : <div className="tv-card" style={{ padding:0, overflow:'hidden' }}>
            <div className="spot-grid-row spot-grid-head" style={{ gridTemplateColumns: SPOT_TX_GRID, alignItems:'end', padding:'12px 16px',
                                                                   borderBottom:'2px solid rgba(255,255,255,0.35)', fontSize:12, lineHeight:'16px',
                                                                   fontWeight:600, letterSpacing:'0.06em', textTransform:'uppercase', color:'var(--text3)' }}>
              {sortTh('date', 'Date')}
              {sortTh('token', 'Token')}
              {sortTh('side', 'Side')}
              <span style={{ textAlign:'right' }}>Units</span>
              <span style={{ textAlign:'right' }}>Price</span>
              {sortTh('tx_amt', 'Total', true)}
              <span className="spot-pad-left">Chain</span>
              {sortTh('platform', 'Platform')}
              <span>Notes</span>
              <span />
            </div>
            {processed.map(r => {
              const isBuy = r.side === 'buy';
              const txAmt   = r.price_usd || 0;
              const avgCost = r.units > 0 ? txAmt / r.units : 0;
              const isEditing = editingId === r.id;
              return <React.Fragment key={r.id}>
                <div className="spot-grid-row" style={{ gridTemplateColumns: SPOT_TX_GRID, padding:'10px 16px', borderBottom: SPOT_ROW_LINE,
                                                        fontSize:13, color:'var(--text2)', background: isEditing ? 'var(--panel2)' : undefined }}>
                  <div className="spot-cell" data-label="Date" style={{ whiteSpace:'nowrap' }}>{r.trade_date}</div>
                  <SpotTxTokenCell row={r} />
                  <div className="spot-cell" data-label="Side"><span className={`tv-chip ${isBuy?'ok':'fail'}`} style={{ fontSize:11 }}>{r.side.toUpperCase()}</span></div>
                  <div className="spot-cell tv-num" data-label="Units" style={{ textAlign:'right' }}>{mvn(r.units)}</div>
                  <div className="spot-cell tv-num" data-label="Price" style={{ textAlign:'right' }}>{hideValues ? '••••' : fmtPrice(avgCost, 4)}</div>
                  <div className="spot-cell tv-num" data-label="Total" style={{ textAlign:'right', fontWeight:600 }}>{mv(txAmt)}</div>
                  <div className="spot-cell spot-pad-left" data-label="Chain" style={{ color:'var(--text3)' }}>{r.chain ? chainLabelFor(r.chain) : '—'}</div>
                  <div className="spot-cell" data-label="Platform" style={{ color:'var(--text3)' }}>{r.platform || ''}</div>
                  <div className="spot-cell spot-tx-notes" data-label="Notes" title={r.notes || undefined} style={{ color:'var(--text3)', fontSize:12 }}>{r.notes || ''}</div>
                  <div className="spot-cell spot-span" style={{ whiteSpace:'nowrap', textAlign:'right' }}>
                    <button type="button" className="tv-btn" style={{ fontSize:12, padding:'2px 10px', marginRight:4 }}
                      aria-label={(isEditing ? 'Close the edit form for ' : 'Edit ') + r.symbol + ' ' + r.side + ' on ' + r.trade_date}
                      onClick={() => isEditing ? (setEditingId(null), setEditId(null), setErr('')) : openEdit(r)}>
                      {isEditing ? '✕' : 'Edit'}
                    </button>
                    {!isEditing && <button type="button" className="tv-btn danger" style={{ fontSize:12, padding:'2px 10px' }}
                      aria-label={'Delete ' + r.symbol + ' ' + r.side + ' on ' + r.trade_date} onClick={() => del(r.id)}>✕</button>}
                  </div>
                </div>
                {isEditing && <div id={`edit-row-${r.id}`} style={{ borderTop:'1px solid var(--accent-line)', borderBottom:'1px solid var(--accent-line)' }}>
                  <div style={{ background:'var(--panel2)', padding:'14px 16px', borderLeft:'3px solid var(--accent)' }}>
                    <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(140px,1fr))', gap:10, marginBottom:10 }}>
                      <div>{lbl('Date')}<input className="tv-input" type="date" value={form.trade_date} onChange={e => setForm({...form,trade_date:e.target.value})} /></div>
                      <div>{lbl('Symbol *')}<input className="tv-input" placeholder="BTC" value={form.symbol} onChange={e => setForm({...form,symbol:e.target.value})} /></div>
                      <div>{lbl('Side')}<select className="tv-select" value={form.side} onChange={e => setForm({...form,side:e.target.value})} style={{ width:'100%' }}>
                        <option value="buy">Buy</option><option value="sell">Sell</option>
                      </select></div>
                      <div>{lbl('Units *')}<input className="tv-input" type="number" value={form.units} onChange={e => setForm({...form,units:e.target.value})} /></div>
                      <div>{lbl('Total (USD) *')}<input className="tv-input" type="number" placeholder="Total paid incl. fees" value={form.price_usd} onChange={e => setForm({...form,price_usd:e.target.value})} /></div>
                      <div>{lbl('Platform')}<input className="tv-input" placeholder="e.g. Binance" value={form.platform} onChange={e => setForm({...form,platform:e.target.value})} /></div>
                      <div>{lbl('Chain')}<select className="tv-select" value={form.chain} onChange={e => setForm({...form,chain:e.target.value})} style={{ width:'100%' }}>
                        <option value="">—</option>
                        {SPOT_CHAINS.map(c => <option key={c.slug} value={c.slug}>{c.label}</option>)}
                      </select></div>
                      <div style={{ gridColumn:'span 2' }}>{lbl('Contract Address')}<input className="tv-input" placeholder="0x… or Solana address" value={form.contract_address} onChange={e => setForm({...form,contract_address:e.target.value})} /></div>
                      <div style={{ gridColumn:'span 2' }}>{lbl('Notes')}<input className="tv-input" value={form.notes} onChange={e => setForm({...form,notes:e.target.value})} /></div>
                    </div>
                    {err && <div style={{ color:'var(--fail)', fontSize:12, marginBottom:8 }}>{err}</div>}
                    <div style={{ display:'flex', gap:8, justifyContent:'flex-end' }}>
                      <button className="tv-btn primary" onClick={save} disabled={saving}>{saving?'Saving…':'Save'}</button>
                      <button className="tv-btn" onClick={() => { setEditingId(null); setEditId(null); setErr(''); }}>Cancel</button>
                    </div>
                  </div>
                </div>}
              </React.Fragment>;
            })}
          </div>}
  </div>;
}

// Backfill panel for ONE symbol - a sibling component (same reason as
// MaxFiPoolCell: the selection Set, the chain/address inputs,
// and the apply-in-flight state are all per-symbol and have no reason to
// live in BackfillScreen's own hooks). Selection defaults to the symbol's
// currently-unfilled rows on mount AND every time `group` changes identity
// (i.e. after any refresh) - the same "default to unfilled" rule both times,
// which is what lets a symbol be split into two subsets with two different
// addresses without ever silently re-selecting an already-filled row.
function BackfillSymbolRow({ group, expanded, onToggle, refresh, hideValues }) {
  const [selected, setSelected] = useState(() => new Set(
    group.rows.filter(r => !(r.chain && r.contract_address)).map(r => r.id)));
  const [chainVal, setChainVal] = useState('');
  const [addressVal, setAddressVal] = useState('');
  const [pairErr, setPairErr] = useState('');
  const [applying, setApplying] = useState(false);
  const [applyProgress, setApplyProgress] = useState(null);
  const [applyResults, setApplyResults] = useState(null);

  useEffect(() => {
    setSelected(new Set(group.rows.filter(r => !(r.chain && r.contract_address)).map(r => r.id)));
  }, [group]);

  const mv  = v => hideValues ? '••••' : fmt(v);
  const mvn = (v, d) => hideValues ? '••••' : fmtNum(v, d || 8);

  const allSelected = group.rows.length > 0 && group.rows.every(r => selected.has(r.id));

  function toggleRow(id, checked) {
    setSelected(prev => {
      const next = new Set(prev);
      checked ? next.add(id) : next.delete(id);
      return next;
    });
  }

  async function apply() {
    const trimmedChain = chainVal.trim();
    const trimmedAddress = addressVal.trim();
    if (Boolean(trimmedChain) !== Boolean(trimmedAddress)) {
      setPairErr('Chain and Contract Address must both be filled in, or both left blank.');
      return;
    }
    setPairErr('');
    const targetRows = group.rows.filter(r => selected.has(r.id));
    if (targetRows.length === 0) return;

    setApplying(true);
    setApplyResults(null);
    const results = [];
    for (let i = 0; i < targetRows.length; i++) {
      const row = targetRows[i];
      setApplyProgress({ done: i, total: targetRows.length });
      try {
        // Echoes every field the PUT route requires, unchanged, so this
        // backfill never blanks trade_date/symbol/side/units/price_usd/
        // platform/notes - only chain and contract_address change.
        const d = await api(`/api/spot/transactions/${row.id}`, {
          method: 'PUT',
          body: JSON.stringify({
            trade_date: row.trade_date, symbol: row.symbol, side: row.side,
            units: row.units, price_usd: row.price_usd,
            platform: row.platform || '', notes: row.notes || '',
            chain: trimmedChain, contract_address: trimmedAddress,
          }),
        });
        // api() returns undefined (no throw) on a 401 - that is a failure,
        // never a success. A 400/500 THROWS instead of resolving with an
        // `error` field - the catch block below is what actually sees a
        // rejected address, not this branch.
        if (d === undefined || d.error) {
          results.push({ id: row.id, ok: false, error: extractApiErrorMessage(d) });
        } else {
          results.push({ id: row.id, ok: true });
        }
      } catch (e) {
        // A rejected address (malformed format, unknown chain, one-sided
        // pairing) arrives here, as a thrown Error, not above - api() throws
        // on any non-2xx response instead of resolving it with `.error`.
        results.push({ id: row.id, ok: false, error: extractApiErrorMessage(e) });
      }
    }
    setApplyProgress({ done: targetRows.length, total: targetRows.length });
    setApplying(false);
    setApplyResults(results);
    if (results.every(r => r.ok)) { setChainVal(''); setAddressVal(''); }
    // Always refresh from the server, success or partial failure - never
    // patch local state and assume it matches the database.
    refresh();
  }

  const failed = applyResults ? applyResults.filter(r => !r.ok) : [];

  return <React.Fragment>
    <div onClick={() => onToggle(group.symbol)}
      style={{ display:'flex', alignItems:'center', gap:10, padding:'10px 14px', cursor:'pointer',
        borderBottom: expanded ? 'none' : '1px solid var(--line)' }}>
      <span style={{ fontSize:11, color:'var(--text4)' }}>{expanded ? '▾' : '▸'}</span>
      <span style={{ fontWeight:700, color:'var(--text)', fontSize:13, minWidth:90 }}>{group.symbol}</span>
      <span style={{ fontSize:12, color:'var(--text4)' }}>{group.total} row{group.total!==1?'s':''}</span>
      <span style={{ marginLeft:'auto', fontSize:12, fontWeight:600,
        color: group.filledCount===group.total ? 'var(--ok)' : 'var(--text3)' }}>
        {group.filledCount} of {group.total} filled{group.filledCount===group.total ? ' ✓' : ''}
      </span>
    </div>
    {expanded && <div style={{ padding:'12px 14px 16px', borderBottom:'1px solid var(--line)', background:'var(--panel2)' }}>
      <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:8 }}>
        <label style={{ display:'flex', alignItems:'center', gap:6, fontSize:12, color:'var(--text3)', cursor:'pointer' }}>
          <input type="checkbox" checked={allSelected}
            onChange={e => setSelected(e.target.checked ? new Set(group.rows.map(r=>r.id)) : new Set())} />
          Select all
        </label>
        <button className="tv-btn" style={{ fontSize:11, padding:'2px 8px' }} onClick={() => setSelected(new Set())}>Select none</button>
        <span style={{ fontSize:12, color:'var(--text4)', marginLeft:'auto' }}>{selected.size} selected</span>
      </div>

      <div style={{ marginBottom:12 }}>
        {group.rows.map(r => {
          const isSet = !!(r.chain && r.contract_address);
          return <div key={r.id} style={{ display:'flex', alignItems:'center', gap:10, padding:'4px 0', flexWrap:'wrap',
            fontSize:12, borderBottom:'1px solid var(--line-soft)' }}>
            <input type="checkbox" checked={selected.has(r.id)} onChange={e => toggleRow(r.id, e.target.checked)} />
            <span style={{ color:'var(--text3)', whiteSpace:'nowrap' }}>{r.trade_date}</span>
            <span className={`tv-chip ${r.side==='buy'?'ok':'fail'}`} style={{ fontSize:10 }}>{r.side.toUpperCase()}</span>
            <span style={{ color:'var(--text3)', whiteSpace:'nowrap' }}>{mvn(r.units)} units</span>
            <span style={{ color:'var(--text3)', whiteSpace:'nowrap' }}>{mv(r.price_usd)}</span>
            <span style={{ color:'var(--text4)' }}>{r.platform || ''}</span>
            <span style={{ marginLeft:'auto', fontSize:11, color: isSet ? '#c9d1d9' : 'var(--text4)',
              whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis', maxWidth:'min(280px, 100%)', minWidth:0 }}>
              {isSet ? `${chainLabelFor(r.chain)} · ${r.contract_address}` : 'Not set'}
            </span>
          </div>;
        })}
      </div>

      <div style={{ display:'flex', gap:10, alignItems:'flex-end', flexWrap:'wrap' }}>
        <div>
          <div style={{ fontSize:11, color:'var(--text4)', marginBottom:3 }}>Chain</div>
          <select className="tv-select" value={chainVal} onChange={e => setChainVal(e.target.value)} style={{ width:150 }}>
            <option value="">—</option>
            {SPOT_CHAINS.map(c => <option key={c.slug} value={c.slug}>{c.label}</option>)}
          </select>
        </div>
        <div style={{ flex:1, minWidth:200 }}>
          <div style={{ fontSize:11, color:'var(--text4)', marginBottom:3 }}>Contract Address</div>
          <input className="tv-input" placeholder="0x… or Solana address" value={addressVal}
            onChange={e => setAddressVal(e.target.value)} style={{ width:'100%' }} />
        </div>
        <button className="tv-btn primary" onClick={apply} disabled={applying || selected.size === 0}>
          {applying
            ? `Applying… (${applyProgress ? applyProgress.done : 0} of ${applyProgress ? applyProgress.total : selected.size})`
            : `Apply to ${selected.size} row${selected.size!==1?'s':''}`}
        </button>
      </div>
      {pairErr && <div style={{ color:'var(--fail)', fontSize:12, marginTop:6 }}>{pairErr}</div>}

      {applyResults && (failed.length === 0
        ? <div style={{ color:'var(--ok)', fontSize:12, marginTop:8 }}>
            {'✓'} Applied to {applyResults.length} row{applyResults.length!==1?'s':''}.
          </div>
        : <div style={{ marginTop:8 }}>
            <div style={{ color:'var(--fail)', fontSize:12, marginBottom:4 }}>
              {failed.length} of {applyResults.length} failed. This operation is idempotent — re-applying is safe.
            </div>
            {failed.map(f => {
              const row = group.rows.find(r => r.id === f.id);
              return <div key={f.id} style={{ fontSize:11, color:'var(--text3)', marginBottom:2 }}>
                Row {f.id}{row ? ` (${row.trade_date})` : ''}: <span style={{ color:'var(--fail)' }}>{f.error}</span>
              </div>;
            })}
          </div>)}
    </div>}
  </React.Fragment>;
}

function BackfillScreen({ hideValues }) {
  const [rows, setRows] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expandedSymbols, setExpandedSymbols] = useState(() => new Set());

  function load() {
    setLoading(true);
    api('/api/spot/transactions').then(setRows).catch(()=>{}).finally(()=>setLoading(false));
  }
  useEffect(load, []);

  function toggleSymbol(sym) {
    setExpandedSymbols(prev => {
      const next = new Set(prev);
      next.has(sym) ? next.delete(sym) : next.add(sym);
      return next;
    });
  }

  // Group by symbol; sort so the symbols with the most unfilled rows lead -
  // the work list orders itself by what is left to do.
  const symbolGroups = useMemo(() => {
    if (!rows) return [];
    const map = {};
    rows.forEach(r => { (map[r.symbol] = map[r.symbol] || []).push(r); });
    const groups = Object.keys(map).map(symbol => {
      const symRows = map[symbol];
      const filled = symRows.filter(r => r.chain && r.contract_address);
      const distinctPairs = Array.from(new Set(filled.map(r => `${r.chain} ${r.contract_address}`)));
      return {
        symbol, rows: symRows, total: symRows.length,
        filledCount: filled.length, unfilledCount: symRows.length - filled.length,
        distinctPairs,
      };
    });
    groups.sort((a, b) => b.unfilledCount - a.unfilledCount || a.symbol.localeCompare(b.symbol));
    return groups;
  }, [rows]);

  const totalRows = rows ? rows.length : 0;
  const totalFilled = rows ? rows.filter(r => r.chain && r.contract_address).length : 0;

  return <div>
    <div className="tv-card" style={{ marginBottom:16, padding:'12px 14px' }}>
      <div style={{ fontSize:13, color:'var(--text3)' }}>
        <span style={{ fontWeight:700, color:'var(--text)' }}>{totalFilled} of {totalRows}</span> transactions have a chain and address.
      </div>
    </div>

    {/* Only the TRUE initial load (rows still null) swaps to the spinner.
        A post-apply refresh() also flips loading true, but must not unmount
        BackfillSymbolRow here - that would wipe the just-set failure message
        (and any in-progress selection) before the user ever sees it, since
        each row's applyResults/selected state lives in that component, not
        here. Once rows has data at least once, the list stays mounted and
        just re-renders with fresh props when the refetch resolves. */}
    {loading && !rows ? <div style={{ padding:40, textAlign:'center', color:'var(--text4)' }}>
      <div className="spin" style={{ display:'inline-block', width:24, height:24, border:'2px solid var(--line)', borderTopColor:'var(--accent)', borderRadius:'50%' }} />
    </div>
    : !rows || rows.length === 0
      ? <div style={{ color:'var(--text4)', padding:20, textAlign:'center' }}>No transactions yet.</div>
      : <div className="tv-card" style={{ padding:0, overflow:'hidden' }}>
          {symbolGroups.map(group => <BackfillSymbolRow key={group.symbol} group={group}
            expanded={expandedSymbols.has(group.symbol)} onToggle={toggleSymbol} refresh={load} hideValues={hideValues} />)}
        </div>}
  </div>;
}

// The Spot page (HANDOFF_spot_perps_rebuild.md 3.2): the Spot menu item
// (activeTab 'spot', static/app.js). Tabs: Open positions · History ·
// Transactions · Backfill. An old saved 'holdings' tab opens Open positions.
const SPOT_TABS = [{id:'open',label:'Open positions'},{id:'history',label:'History'},{id:'transactions',label:'Transactions'},{id:'backfill',label:'Backfill'}];

function spotReadSubTab() {
  let v = null;
  try { v = localStorage.getItem('spotSubTab'); } catch (_e) { /* storage unavailable */ }
  return SPOT_TABS.some(t => t.id === v) ? v : 'open';
}

function SpotPnlScreen({ hideValues, refreshTrigger, setActiveTab }) {
  const [subTab, setSubTab] = useState(() => spotReadSubTab());
  function changeTab(t) {
    setSubTab(t);
    try { localStorage.setItem('spotSubTab', t); } catch (_e) { /* the tab still changes */ }
  }
  // Journal state lives here so open rows and composer drafts outlive a
  // collapsed row, a tab switch and a Refresh (until the page reloads).
  const [openRows, setOpenRows] = useState(() => new Set());
  const [drafts, setDrafts] = useState({});
  const [composing, setComposing] = useState({});
  const journal = { openRows, setOpenRows, drafts, setDrafts, composing, setComposing };
  return <div>
    <div style={{ display:'flex', flexDirection:'column', gap:4, marginBottom:16 }}>
      <h1 style={{ margin:0, fontSize:20, lineHeight:'26px', fontWeight:700, color:'var(--text)' }}>Spot</h1>
      <div style={{ fontSize:13, lineHeight:'18px', color:'var(--text3)' }}>Tokens you hold, your spot trades, and your notes on each. Long-term and bot holdings included.</div>
    </div>
    <div role="group" aria-label="Spot sections" style={{ display:'flex', gap:4, marginBottom:20, flexWrap:'wrap', alignItems:'center' }}>
      {SPOT_TABS.map(t => <button key={t.id} type="button" className="tv-btn" aria-pressed={subTab===t.id}
        style={{ background:subTab===t.id?'var(--panel3)':'transparent', borderColor:subTab===t.id?'var(--accent-line)':'var(--line)',
          color:subTab===t.id?'var(--text)':'var(--text3)', fontWeight:subTab===t.id?600:400 }}
        onClick={() => changeTab(t.id)}>{t.label}</button>)}
      <button type="button" className="tv-btn"
        style={{ marginLeft:'auto', fontSize:12, color:'#c9d1d9' }}
        title="Open Price Sources & Contract Addresses in Settings"
        onClick={() => { window.__settingsSectionJump = 'spotpnl'; setActiveTab && setActiveTab('settings'); }}>
        Contracts
      </button>
    </div>
    {subTab === 'open' && <SpotOpenPositions hideValues={hideValues} refreshTrigger={refreshTrigger} journal={journal} />}
    {subTab === 'history' && <SpotHistoryTab hideValues={hideValues} refreshTrigger={refreshTrigger} journal={journal} />}
    {subTab === 'transactions' && <Transactions hideValues={hideValues} />}
    {subTab === 'backfill' && <BackfillScreen hideValues={hideValues} />}
  </div>;
}

window.SpotPnlScreen = SpotPnlScreen;
