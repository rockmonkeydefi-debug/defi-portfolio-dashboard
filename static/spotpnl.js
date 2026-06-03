/* ===== SPOT P&L SCREEN — Playbook Phase 2 ===== */

function LiveHoldings({ hideValues, refreshTrigger }) {
  const [data, setData] = useState(null);
  const [stables, setStables] = useState(0);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);

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
  const totalVal = data.reduce((s,r) => s+(r.current_value_usd||0), 0);
  const totalUnr = data.reduce((s,r) => s+(r.unrealized_pnl_usd||0), 0);
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

    <div style={{ fontSize:11, color:'var(--text4)', marginBottom:8 }}>FIFO cost basis</div>

    {data.length === 0 ? <div style={{ color:'var(--text4)', padding:20, textAlign:'center' }}>No open positions. Add buy transactions to get started.</div>
    : <div className="tv-card" style={{ padding:0, overflow:'hidden' }}>
        <table className="tv-table">
          <thead><tr>
            <th>Token</th><th className="num">Units</th><th className="num">Avg Cost</th>
            <th className="num">Price</th><th className="num">Cost Basis</th>
            <th className="num">Value</th><th className="num">Unrealized P&L</th>
            <th className="num">Realized P&L</th><th className="num">Unr %</th>
            <th className="num">Port %</th><th className="num">Tok %</th>
          </tr></thead>
          <tbody>{data.map(r => {
            const unrColor = r.unrealized_pnl_usd >= 0 ? 'var(--ok)' : 'var(--fail)';
            const portfolioPct = totalWithStables > 0 ? r.current_value_usd / totalWithStables * 100 : 0;
            const tokenPct = totalVal > 0 ? r.current_value_usd / totalVal * 100 : 0;
            const hasRealized = r.symbol in realizedMap;
            const realized = hasRealized ? realizedMap[r.symbol] : null;
            const realColor = realized != null ? (realized >= 0 ? 'var(--ok)' : 'var(--fail)') : 'var(--text4)';
            return <tr key={r.symbol}>
              <td style={{ fontWeight:700, color:'var(--text)' }}>{r.symbol}</td>
              <td className="num tv-num">{mvn(r.units, 8)}</td>
              <td className="num tv-num">{mv(r.avg_cost_usd, 4)}</td>
              <td className="num tv-num">{r.current_price_usd != null ? mv(r.current_price_usd, 4) : '—'}</td>
              <td className="num tv-num">{mv(r.total_cost_basis)}</td>
              <td className="num tv-num" style={{ fontWeight:600 }}>{r.current_value_usd != null ? mv(r.current_value_usd) : '—'}</td>
              <td className="num tv-num" style={{ color:unrColor, fontWeight:600 }}>{r.unrealized_pnl_usd != null ? (r.unrealized_pnl_usd>=0?'+':'')+mv(r.unrealized_pnl_usd) : '—'}</td>
              <td className="num tv-num" style={{ color:realColor, fontWeight:600 }}>{realized != null ? (realized>=0?'+':'')+mv(realized) : '—'}</td>
              <td className="num tv-num" style={{ color:unrColor }}>{r.unrealized_pct != null ? fmtPct(r.unrealized_pct) : '—'}</td>
              <td className="num tv-num">{hideValues ? '••••' : fmtNum(portfolioPct,1)+'%'}</td>
              <td className="num tv-num">{hideValues ? '••••' : fmtNum(tokenPct,1)+'%'}</td>
            </tr>;
          })}</tbody>
        </table>
      </div>}
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
            return <tr key={r.symbol}>
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

function Transactions({ hideValues }) {
  const [rows, setRows] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState(null);
  const [form, setForm] = useState({ trade_date: new Date().toISOString().slice(0,10), symbol:'', side:'buy', units:'', price_usd:'', platform:'', notes:'' });
  const [err, setErr] = useState('');
  const [saving, setSaving] = useState(false);
  const [csvImporting, setCsvImporting] = useState(false);
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

  // Parse D/M/YYYY or YYYY-MM-DD to a Date object for sorting/filtering
  function parseDate(s) {
    if (!s) return null;
    const dm = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    if (dm) return new Date(parseInt(dm[3]), parseInt(dm[2]) - 1, parseInt(dm[1]));
    const iso = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (iso) return new Date(parseInt(iso[1]), parseInt(iso[2]) - 1, parseInt(iso[3]));
    return null;
  }
  // Convert stored D/M/YYYY (or ISO) → YYYY-MM-DD for <input type="date">
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
    setForm({ trade_date: new Date().toISOString().slice(0,10), symbol:'', side:'buy', units:'', price_usd:'', platform:'', notes:'' });
    setErr(''); setShowForm(true);
  }
  function openEdit(r) {
    setEditId(r.id);
    setForm({ trade_date: toIsoDate(r.trade_date), symbol: r.symbol, side: r.side, units: String(r.units), price_usd: String(r.price_usd), platform: r.platform||'', notes: r.notes||'' });
    setErr(''); setShowForm(true);
  }

  async function save() {
    if (!form.trade_date || !form.symbol || !form.units || !form.price_usd) { setErr('Date, Symbol, Units, and Tx Amt are required.'); return; }
    setSaving(true); setErr('');
    try {
      const payload = { ...form, symbol: form.symbol.trim().toUpperCase() };
      const url = editId ? `/api/spot/transactions/${editId}` : '/api/spot/transactions';
      const method = editId ? 'PUT' : 'POST';
      const d = await api(url, { method, body: JSON.stringify(payload) });
      if (d.error) { setErr(d.error); return; }
      setShowForm(false); load();
    } catch(e) { setErr(String(e)); } finally { setSaving(false); }
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
      <button className="tv-btn danger" onClick={() => { setDeleteAllModal(true); setDeleteAllInput(''); setDeleteAllError(''); }}
        disabled={!rows || rows.length === 0}>
        Delete All
      </button>
    </div>

    {/* Add/Edit form */}
    {showForm && <div className="tv-card" style={{ marginBottom:16 }}>
      <div style={{ fontSize:14, fontWeight:600, marginBottom:12 }}>{editId ? 'Edit Transaction' : 'Add Transaction'}</div>
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
                const txAmt  = r.price_usd || 0;
                const avgCost = r.units > 0 ? txAmt / r.units : 0;
                return <tr key={r.id}>
                  <td style={{ whiteSpace:'nowrap' }}>{r.trade_date}</td>
                  <td><span className={`tv-chip ${isBuy?'ok':'fail'}`} style={{ fontSize:10 }}>{r.side.toUpperCase()}</span></td>
                  <td style={{ fontWeight:700, color:'var(--text)' }}>{r.symbol}</td>
                  <td className="num tv-num">{mvn(r.units)}</td>
                  <td className="num tv-num">{mv(avgCost)}</td>
                  <td className="num tv-num" style={{ fontWeight:600 }}>{mv(txAmt)}</td>
                  <td style={{ color:'var(--text4)' }}>{r.platform || ''}</td>
                  <td style={{ color:'var(--text4)', fontSize:11, maxWidth:160, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{r.notes || ''}</td>
                  <td style={{ whiteSpace:'nowrap' }}>
                    <button className="tv-btn" style={{ fontSize:11, padding:'2px 8px', marginRight:4 }} onClick={() => openEdit(r)}>Edit</button>
                    <button className="tv-btn danger" style={{ fontSize:11, padding:'2px 8px' }} onClick={() => del(r.id)}>✕</button>
                  </td>
                </tr>;
              })}</tbody>
            </table>
          </div>}
  </div>;
}

function SpotPnlScreen({ hideValues, refreshTrigger }) {
  const [subTab, setSubTab] = useState(() => localStorage.getItem('spotSubTab') || 'holdings');
  function changeTab(t) { setSubTab(t); localStorage.setItem('spotSubTab', t); }
  const TABS = [{id:'holdings',label:'Live Holdings'},{id:'history',label:'Trade History'},{id:'transactions',label:'Transactions'}];
  return <div>
    <div style={{ display:'flex', gap:4, marginBottom:20 }}>
      {TABS.map(t => <button key={t.id} className="tv-btn"
        style={{ background:subTab===t.id?'var(--panel3)':'transparent', borderColor:subTab===t.id?'var(--accent-line)':'var(--line)',
          color:subTab===t.id?'var(--text)':'var(--text3)', fontWeight:subTab===t.id?600:400 }}
        onClick={() => changeTab(t.id)}>{t.label}</button>)}
    </div>
    {subTab === 'holdings' && <LiveHoldings hideValues={hideValues} refreshTrigger={refreshTrigger} />}
    {subTab === 'history' && <TradeHistory hideValues={hideValues} />}
    {subTab === 'transactions' && <Transactions hideValues={hideValues} />}
  </div>;
}

window.SpotPnlScreen = SpotPnlScreen;
