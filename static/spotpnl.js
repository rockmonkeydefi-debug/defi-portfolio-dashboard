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

function LiveHoldings({ hideValues, refreshTrigger }) {
  const [data, setData] = useState(null);
  const [stables, setStables] = useState(0);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editingKey, setEditingKey] = useState(null);
  const [draftNote, setDraftNote] = useState('');
  const [noteError, setNoteError] = useState('');
  const skipNoteSaveRef = React.useRef(false);

  useEffect(() => {
    setLoading(true);
    Promise.all([api('/api/spot/pnl'), api('/api/spot/stablecoins'), api('/api/spot/history')])
      .then(([rows, sc, hist]) => {
        setData(rows);
        setStables(sc.total_usd || 0);
        setHistory(Array.isArray(hist) ? hist : []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [refreshTrigger]);

  if (loading) return <div style={{ padding:40, textAlign:'center', color:'var(--text4)' }}><div className="spin" style={{ display:'inline-block', width:24, height:24, border:'2px solid var(--line)', borderTopColor:'var(--accent)', borderRadius:'50%' }} /></div>;
  if (!data) return <div style={{ color:'var(--fail)', padding:20 }}>Failed to load holdings.</div>;

  const totalCost = data.reduce((s,r) => s+(r.total_cost_basis||0), 0);
  // Null-price holdings are EXCLUDED here, not coerced to 0 — a null value
  // means "unknown", not "worth nothing", and folding it into the total as 0
  // silently understates the denominator every other holding's Port % divides by.
  const totalVal = data.reduce((s,r) => r.current_value_usd != null ? s + r.current_value_usd : s, 0);
  // Same fix as totalVal above: a null unrealized_pnl_usd means "unknown", not
  // "no change" — excluded from the total rather than coerced to 0.
  const totalUnr = data.reduce((s,r) => r.unrealized_pnl_usd != null ? s + r.unrealized_pnl_usd : s, 0);
  const totalReal = data.reduce((s,r) => s+(r.realized_pnl_usd||0), 0);

  const realizedMap = {};
  for (const h of history) {
    if (h.symbol != null && h.realized_pnl != null) {
      realizedMap[h.symbol] = (realizedMap[h.symbol] || 0) + h.realized_pnl;
    }
  }

  const mv = (v, d) => hideValues ? '••••' : fmt(v, d);
  const mvn = (v, d) => hideValues ? '••••' : fmtNum(v, d || 4);

  const totalWithStables = totalVal + stables;
  const dryPowderPct = totalWithStables > 0 ? stables / totalWithStables * 100 : 0;

  async function saveNote(row) {
    if (skipNoteSaveRef.current) { skipNoteSaveRef.current = false; return; }
    const noteToSave = draftNote;
    if (noteToSave === (row.note || '')) { setEditingKey(null); return; }

    // position_key is chain and contract_address joined by a single literal
    // space (_stringify_spot_position_key). Split on the FIRST space only -
    // never .split(' '), which would break on a value containing more than
    // one space - and never change case: Solana addresses are base58 and
    // case-sensitive, so lowercasing would collide two distinct tokens.
    const sepIdx = row.position_key.indexOf(' ');
    const chain = row.position_key.slice(0, sepIdx);
    const contract_address = row.position_key.slice(sepIdx + 1);

    try {
      const d = await api('/api/spot/position-notes', {
        method: 'PUT',
        body: JSON.stringify({ chain, contract_address, note: noteToSave }),
      });
      // api() returns undefined (no throw) on a 401 - that is a failure,
      // never a success. A 400/500 THROWS instead of resolving with an
      // `error` field - the catch block below is what actually sees a
      // rejected note, not this branch.
      if (d === undefined || d.error) {
        setNoteError(extractApiErrorMessage(d));
        setEditingKey(null);
      } else {
        setNoteError('');
        // Patch only this row's note in local state rather than triggering
        // the full three-endpoint refresh (pnl + stablecoins + history) -
        // re-running every live price lookup for a text edit is
        // disproportionate.
        setData(prev => prev.map(r =>
          r.position_key === row.position_key ? { ...r, note: noteToSave } : r));
        setEditingKey(null);
      }
    } catch (e) {
      setNoteError(extractApiErrorMessage(e));
      setEditingKey(null);
    }
  }

  return <div>
    {/* KPI strip */}
    <div style={{ display:'flex', gap:10, flexWrap:'wrap', marginBottom:16 }}>
      {[
        {l:'Cost Basis', v:mv(totalCost)},
        {l:'Current Value', v:mv(totalVal), c:'var(--text)'},
        {l:'Unrealized P&L', v:mv(totalUnr), c:totalUnr>=0?'var(--ok)':'var(--fail)'},
        {l:'Realized P&L', v:mv(totalReal), c:totalReal>=0?'var(--ok)':'var(--fail)'},
        ...(stables > 0 ? [{l:'Dry Powder', v: hideValues ? '••••' : `${fmt(stables)} | ${fmtNum(dryPowderPct,1)}%`, c:'var(--ok)'}] : []),
      ].map(s => <div key={s.l} className="tv-card" style={{ flex:1, minWidth:130 }}>
        <div className="tv-label" style={{ marginBottom:4 }}>{s.l}</div>
        <div className="tv-num" style={{ fontSize:16, fontWeight:700, color:s.c||'var(--text)' }}>{s.v}</div>
      </div>)}
    </div>

    <div style={{ fontSize:12, color:'#c9d1d9', marginBottom:8 }}>FIFO cost basis</div>

    {data.length === 0 ? <div style={{ color:'var(--text4)', padding:20, textAlign:'center' }}>No open positions. Add buy transactions to get started.</div>
    : <div className="tv-card" style={{ padding:0, overflow:'hidden' }}>
        <table className="tv-table">
          <thead><tr>
            <th>Token</th><th className="num">Units</th><th className="num">Avg Cost</th>
            <th className="num">Price</th><th className="num">Cost Basis</th>
            <th className="num">Value</th><th className="num">Unrealized P&L</th>
            <th className="num">Realized P&L</th><th className="num">Unr %</th>
            <th className="num">Port %</th><th className="num">Tok %</th><th>Notes</th>
          </tr></thead>
          <tbody>{data.map(r => {
            const unrColor = r.unrealized_pnl_usd >= 0 ? 'var(--ok)' : 'var(--fail)';
            const priced = r.price_status === 'ok';
            const portfolioPct = priced && totalWithStables > 0 ? r.current_value_usd / totalWithStables * 100 : null;
            const tokenPct = priced && totalVal > 0 ? r.current_value_usd / totalVal * 100 : null;
            const hasRealized = r.symbol in realizedMap;
            const realized = hasRealized ? realizedMap[r.symbol] : null;
            const realColor = realized != null ? (realized >= 0 ? 'var(--ok)' : 'var(--fail)') : 'var(--text4)';
            // price_status explains WHY there's no price, distinct from a
            // plain '—': "no_source" (nothing configured — user action needed)
            // vs "source_configured_no_result" (a source IS configured but the
            // lookup came back empty) are different problems and must read
            // differently. "manual" stays a plain em dash — that's deliberate.
            const priceCell = r.price_status === 'no_source' ? 'No price source'
              : r.price_status === 'source_configured_no_result' ? 'No price data'
              : r.current_price_usd != null ? mv(r.current_price_usd, 4) : '—';
            // A symbol-fallback position (blank chain and contract_address)
            // has a position_key with no space in it - just a bare uppercased
            // symbol. The backend rejects notes for such positions, so their
            // cells are non-interactive here rather than offering an edit
            // that would always fail.
            const hasAddress = r.position_key.indexOf(' ') !== -1;
            const isEditingNote = editingKey === r.position_key;
            return <tr key={r.position_key}>
              <td style={{ fontWeight:700, color:'var(--text)' }}>{r.symbol}</td>
              <td className="num tv-num">{mvn(r.units, 8)}</td>
              <td className="num tv-num">{mv(r.avg_cost_usd, 4)}</td>
              <td className="num tv-num">{priceCell}</td>
              <td className="num tv-num">{mv(r.total_cost_basis)}</td>
              <td className="num tv-num" style={{ fontWeight:600 }}>{r.current_value_usd != null ? mv(r.current_value_usd) : '—'}</td>
              <td className="num tv-num" style={{ color:unrColor, fontWeight:600 }}>{r.unrealized_pnl_usd != null ? (r.unrealized_pnl_usd>=0?'+':'')+mv(r.unrealized_pnl_usd) : '—'}</td>
              <td className="num tv-num" style={{ color:realColor, fontWeight:600 }}>{realized != null ? (realized>=0?'+':'')+mv(realized) : '—'}</td>
              <td className="num tv-num" style={{ color:unrColor }}>{r.unrealized_pct != null ? fmtPct(r.unrealized_pct) : '—'}</td>
              <td className="num tv-num">{portfolioPct != null ? (hideValues ? '••••' : fmtNum(portfolioPct,1)+'%') : '—'}</td>
              <td className="num tv-num">{tokenPct != null ? (hideValues ? '••••' : fmtNum(tokenPct,1)+'%') : '—'}</td>
              <td style={{ maxWidth:220 }}>
                {isEditingNote
                  ? <input
                      className="tv-input"
                      autoFocus
                      maxLength={500}
                      value={draftNote}
                      onChange={e => setDraftNote(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === 'Enter') { e.target.blur(); }
                        else if (e.key === 'Escape') { skipNoteSaveRef.current = true; setEditingKey(null); }
                      }}
                      onBlur={() => saveNote(r)}
                      style={{ width:'100%', fontSize:12 }}
                    />
                  : hasAddress
                  ? <div
                      onClick={() => { setEditingKey(r.position_key); setDraftNote(r.note || ''); setNoteError(''); }}
                      title={r.note || ''}
                      style={{ cursor:'pointer', whiteSpace:'nowrap', overflow:'hidden',
                        textOverflow:'ellipsis', maxWidth:200, fontSize:12, color:'#c9d1d9',
                        padding:'3px 5px', borderRadius:4, background:'transparent' }}
                      onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.08)'; }}
                      onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                    >
                      {r.note || ''}
                    </div>
                  : <span style={{ fontSize:12 }}></span>}
              </td>
            </tr>;
          })}</tbody>
        </table>
      </div>}
      <div style={{ fontSize:12, color:'#c9d1d9', marginTop:8 }}>This page shows tokens added manually via Spot Transactions. It does not show all connected wallet holdings.</div>
      {noteError && <div style={{ color:'var(--fail)', fontSize:12, marginTop:8 }}>{noteError}</div>}
  </div>;
}

function TradeHistory({ hideValues }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api('/api/spot/history').then(setData).catch(()=>{}).finally(()=>setLoading(false));
  }, []);

  if (loading) return <div style={{ padding:40, textAlign:'center', color:'var(--text4)' }}><div className="spin" style={{ display:'inline-block', width:24, height:24, border:'2px solid var(--line)', borderTopColor:'var(--accent)', borderRadius:'50%' }} /></div>;
  if (!data) return <div style={{ color:'var(--fail)', padding:20 }}>Failed to load history.</div>;

  const mv = v => hideValues ? '••••' : fmt(v);
  const totalInv = data.reduce((s,r)=>s+(r.total_invested||0),0);
  const totalProc = data.reduce((s,r)=>s+(r.total_proceeds||0),0);
  const totalReal = data.reduce((s,r)=>s+(r.realized_pnl||0),0);

  return <div>
    <div style={{ display:'flex', gap:10, flexWrap:'wrap', marginBottom:16 }}>
      {[{l:'Total Invested',v:mv(totalInv)},{l:'Total Proceeds',v:mv(totalProc)},
        {l:'Realized P&L',v:(totalReal>=0?'+':'')+mv(totalReal),c:totalReal>=0?'var(--ok)':'var(--fail)'},
      ].map(s => <div key={s.l} className="tv-card" style={{ flex:1, minWidth:130 }}>
        <div className="tv-label" style={{ marginBottom:4 }}>{s.l}</div>
        <div className="tv-num" style={{ fontSize:16, fontWeight:700, color:s.c||'var(--text)' }}>{s.v}</div>
      </div>)}
    </div>
    {data.length === 0 ? <div style={{ color:'var(--text4)', padding:20, textAlign:'center' }}>No closed positions yet.</div>
    : <div className="tv-card" style={{ padding:0, overflow:'hidden' }}>
        <table className="tv-table">
          <thead><tr>
            <th>Symbol</th><th className="num">Invested</th><th className="num">Proceeds</th>
            <th className="num">Realized P&L</th><th className="num">ROI %</th><th>Last Sell</th>
          </tr></thead>
          <tbody>{data.map(r => {
            const c = r.realized_pnl >= 0 ? 'var(--ok)' : 'var(--fail)';
            return <tr key={r.position_key}>
              <td style={{ fontWeight:700 }}>{r.symbol}</td>
              <td className="num tv-num">{mv(r.total_invested)}</td>
              <td className="num tv-num">{mv(r.total_proceeds)}</td>
              <td className="num tv-num" style={{ color:c, fontWeight:600 }}>{r.realized_pnl>=0?'+':''}{mv(r.realized_pnl)}</td>
              <td className="num tv-num" style={{ color:c }}>{fmtPct(r.roi_pct)}</td>
              <td>{r.last_sell_date || '—'}</td>
            </tr>;
          })}</tbody>
        </table>
      </div>}
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

// Token cell for the Transactions table body row only (LiveHoldings' Token
// cell is untouched). A sibling component, not inline in Transactions, so
// the transient "Copied" indicator is per-row state - same reason
// MaxFiPoolCell in static/maxfi.js is its own component rather than living
// in its parent's hooks. Mirrors MaxFiPoolCell's click-to-copy pattern
// (navigator.clipboard.writeText + stopPropagation + a 1500ms transient
// state), the only other click-to-copy in this codebase. A row with no
// chain and no address renders the exact original plain cell - no title,
// no click handler, no added markup.
function SpotTokenCell({ row }) {
  const [copied, setCopied] = useState(false);
  const hasChain = !!row.chain;
  const hasAddress = !!row.contract_address;

  if (!hasChain && !hasAddress) {
    return <td style={{ fontWeight:700, color:'var(--text)' }}>{row.symbol}</td>;
  }

  function doCopy(ev) {
    ev.stopPropagation();
    if (!hasAddress) return;
    navigator.clipboard.writeText(row.contract_address).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  }

  return <td
    style={{ fontWeight:700, color:'var(--text)', cursor: hasAddress ? 'pointer' : undefined }}
    title={hasAddress ? row.contract_address : undefined}
    onClick={hasAddress ? doCopy : undefined}>
    {row.symbol}
    {hasChain && <span style={{ display:'inline-flex', alignItems:'center', borderRadius:6, padding:'1px 6px',
      fontSize:11, border:'1px solid rgba(255,255,255,0.25)', color:'#c9d1d9', marginLeft:6 }}>
      {chainLabelFor(row.chain)}
    </span>}
    {copied && <span style={{ fontSize:11, color:'var(--ok)', marginLeft:6 }}>Copied</span>}
  </td>;
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
    if (!form.trade_date || !form.symbol || !form.units || !form.price_usd) { setErr('Date, Symbol, Units, and Tx Amt are required.'); return; }
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

  function SortTh({ col, label, className }) {
    const active = sortCol === col;
    return <th className={className} onClick={() => handleSort(col)}
      style={{ cursor:'pointer', userSelect:'none', whiteSpace:'nowrap',
               color: active ? 'var(--text)' : undefined }}>
      {label}{active ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
    </th>;
  }

  const lbl = (t) => <div style={{ fontSize:11, color:'var(--text4)', marginBottom:3 }}>{t}</div>;

  return <div>
    {/* Delete-all modal */}
    {deleteAllModal && <div style={{ position:'fixed', inset:0, background:'rgba(0,0,0,0.6)', zIndex:1000, display:'flex', alignItems:'center', justifyContent:'center' }}>
      <div className="tv-card" style={{ width:420, padding:24, display:'flex', flexDirection:'column', gap:14 }}>
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
        <div>{lbl('Tx Amt (USD) *')}
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
        <div>{lbl('Tx Amt Min')}<input className="tv-input" type="number" placeholder="0" value={filterMinAmt} style={{ width:90 }} onChange={e => setFilterMinAmt(e.target.value)} /></div>
        <div>{lbl('Tx Amt Max')}<input className="tv-input" type="number" placeholder="∞" value={filterMaxAmt} style={{ width:90 }} onChange={e => setFilterMaxAmt(e.target.value)} /></div>
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
            <table className="tv-table">
              <thead><tr>
                <SortTh col="date"     label="Date" />
                <SortTh col="side"     label="Side" />
                <SortTh col="token"    label="Token" />
                <th className="num">Units</th>
                <th className="num">Avg Cost/unit</th>
                <SortTh col="tx_amt"   label="Tx Amt" className="num" />
                <SortTh col="platform" label="Platform" />
                <th>Notes</th><th></th>
              </tr></thead>
              <tbody>{processed.map(r => {
                const isBuy = r.side === 'buy';
                const txAmt   = r.price_usd || 0;
                const avgCost = r.units > 0 ? txAmt / r.units : 0;
                const isEditing = editingId === r.id;
                return <React.Fragment key={r.id}>
                  <tr style={{ background: isEditing ? 'var(--panel2)' : undefined }}>
                    <td style={{ whiteSpace:'nowrap' }}>{r.trade_date}</td>
                    <td><span className={`tv-chip ${isBuy?'ok':'fail'}`} style={{ fontSize:10 }}>{r.side.toUpperCase()}</span></td>
                    <SpotTokenCell row={r} />
                    <td className="num tv-num">{mvn(r.units)}</td>
                    <td className="num tv-num">{mv(avgCost)}</td>
                    <td className="num tv-num" style={{ fontWeight:600 }}>{mv(txAmt)}</td>
                    <td style={{ color:'var(--text4)' }}>{r.platform || ''}</td>
                    <td style={{ color:'var(--text4)', fontSize:11, maxWidth:160, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{r.notes || ''}</td>
                    <td style={{ whiteSpace:'nowrap' }}>
                      <button className="tv-btn" style={{ fontSize:11, padding:'2px 8px', marginRight:4 }}
                        onClick={() => isEditing ? (setEditingId(null), setEditId(null), setErr('')) : openEdit(r)}>
                        {isEditing ? '✕' : 'Edit'}
                      </button>
                      {!isEditing && <button className="tv-btn danger" style={{ fontSize:11, padding:'2px 8px' }} onClick={() => del(r.id)}>✕</button>}
                    </td>
                  </tr>
                  {isEditing && <tr id={`edit-row-${r.id}`}>
                    <td colSpan={9} style={{ padding:0, borderTop:'1px solid var(--accent-line)', borderBottom:'1px solid var(--accent-line)' }}>
                      <div style={{ background:'var(--panel2)', padding:'14px 16px', borderLeft:'3px solid var(--accent)' }}>
                        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(140px,1fr))', gap:10, marginBottom:10 }}>
                          <div>{lbl('Date')}<input className="tv-input" type="date" value={form.trade_date} onChange={e => setForm({...form,trade_date:e.target.value})} /></div>
                          <div>{lbl('Symbol *')}<input className="tv-input" placeholder="BTC" value={form.symbol} onChange={e => setForm({...form,symbol:e.target.value})} /></div>
                          <div>{lbl('Side')}<select className="tv-select" value={form.side} onChange={e => setForm({...form,side:e.target.value})} style={{ width:'100%' }}>
                            <option value="buy">Buy</option><option value="sell">Sell</option>
                          </select></div>
                          <div>{lbl('Units *')}<input className="tv-input" type="number" value={form.units} onChange={e => setForm({...form,units:e.target.value})} /></div>
                          <div>{lbl('Tx Amt (USD) *')}<input className="tv-input" type="number" placeholder="Total paid incl. fees" value={form.price_usd} onChange={e => setForm({...form,price_usd:e.target.value})} /></div>
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
                    </td>
                  </tr>}
                </React.Fragment>;
              })}</tbody>
            </table>
          </div>}
  </div>;
}

// Backfill panel for ONE symbol - a sibling component (same reason as
// SpotTokenCell/MaxFiPoolCell: the selection Set, the chain/address inputs,
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
          return <div key={r.id} style={{ display:'flex', alignItems:'center', gap:10, padding:'4px 0',
            fontSize:12, borderBottom:'1px solid var(--line-soft)' }}>
            <input type="checkbox" checked={selected.has(r.id)} onChange={e => toggleRow(r.id, e.target.checked)} />
            <span style={{ color:'var(--text3)', whiteSpace:'nowrap' }}>{r.trade_date}</span>
            <span className={`tv-chip ${r.side==='buy'?'ok':'fail'}`} style={{ fontSize:10 }}>{r.side.toUpperCase()}</span>
            <span style={{ color:'var(--text3)', whiteSpace:'nowrap' }}>{mvn(r.units)} units</span>
            <span style={{ color:'var(--text3)', whiteSpace:'nowrap' }}>{mv(r.price_usd)}</span>
            <span style={{ color:'var(--text4)' }}>{r.platform || ''}</span>
            <span style={{ marginLeft:'auto', fontSize:11, color: isSet ? '#c9d1d9' : 'var(--text4)',
              whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis', maxWidth:280 }}>
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

function SpotPnlScreen({ hideValues, refreshTrigger, setActiveTab }) {
  const [subTab, setSubTab] = useState(() => localStorage.getItem('spotSubTab') || 'holdings');
  function changeTab(t) { setSubTab(t); localStorage.setItem('spotSubTab', t); }
  const TABS = [{id:'holdings',label:'Live Holdings'},{id:'history',label:'Trade History'},{id:'transactions',label:'Transactions'},{id:'backfill',label:'Backfill'}];
  return <div>
    <div style={{ display:'flex', gap:4, marginBottom:20 }}>
      {TABS.map(t => <button key={t.id} className="tv-btn"
        style={{ background:subTab===t.id?'var(--panel3)':'transparent', borderColor:subTab===t.id?'var(--accent-line)':'var(--line)',
          color:subTab===t.id?'var(--text)':'var(--text3)', fontWeight:subTab===t.id?600:400 }}
        onClick={() => changeTab(t.id)}>{t.label}</button>)}
      <button className="tv-btn"
        style={{ marginLeft:'auto', fontSize:12, color:'#c9d1d9' }}
        title="Open Price Sources & Contract Addresses in Settings"
        onClick={() => { window.__settingsSectionJump = 'spotpnl'; setActiveTab && setActiveTab('settings'); }}>
        Contracts
      </button>
    </div>
    {subTab === 'holdings' && <LiveHoldings hideValues={hideValues} refreshTrigger={refreshTrigger} />}
    {subTab === 'history' && <TradeHistory hideValues={hideValues} />}
    {subTab === 'transactions' && <Transactions hideValues={hideValues} />}
    {subTab === 'backfill' && <BackfillScreen hideValues={hideValues} />}
  </div>;
}

window.SpotPnlScreen = SpotPnlScreen;
