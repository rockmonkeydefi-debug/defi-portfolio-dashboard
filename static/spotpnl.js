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

  const mv = v => hideValues ? '••••' : fmt(v);
  const mvn = (v, d) => hideValues ? '••••' : fmtNum(v, d || 8);

  function load() {
    setLoading(true);
    api('/api/spot/transactions').then(setRows).catch(()=>{}).finally(()=>setLoading(false));
  }
  useEffect(load, []);

  function openAdd() {
    setEditId(null);
    setForm({ trade_date: new Date().toISOString().slice(0,10), symbol:'', side:'buy', units:'', price_usd:'', platform:'', notes:'' });
    setErr('');
    setShowForm(true);
  }
  function openEdit(r) {
    setEditId(r.id);
    setForm({ trade_date: r.trade_date, symbol: r.symbol, side: r.side, units: String(r.units), price_usd: String(r.price_usd), platform: r.platform||'', notes: r.notes||'' });
    setErr('');
    setShowForm(true);
  }

  async function save() {
    if (!form.trade_date || !form.symbol || !form.units || !form.price_usd) { setErr('Date, Symbol, Units, and Price are required.'); return; }
    setSaving(true); setErr('');
    try {
      const payload = { ...form, symbol: form.symbol.trim().toUpperCase() };
      const url = editId ? `/api/spot/transactions/${editId}` : '/api/spot/transactions';
      const method = editId ? 'PUT' : 'POST';
      const d = await api(url, { method, body: JSON.stringify(payload) });
      if (d.error) { setErr(d.error); return; }
      setShowForm(false);
      load();
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

  return <div>
    {/* Actions bar */}
    <div style={{ display:'flex', gap:8, marginBottom:16, alignItems:'center', flexWrap:'wrap' }}>
      <button className="tv-btn primary" onClick={openAdd}>+ Add Transaction</button>
      <label className="tv-btn" style={{ cursor:'pointer' }}>
        {csvImporting ? 'Importing…' : '⬆ Import CSV'}
        <input type="file" accept=".csv" style={{ display:'none' }} onChange={importCsv} />
      </label>
    </div>

    {/* Add/Edit form */}
    {showForm && <div className="tv-card" style={{ marginBottom:16 }}>
      <div style={{ fontSize:14, fontWeight:600, marginBottom:12 }}>{editId ? 'Edit Transaction' : 'Add Transaction'}</div>
      <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(140px,1fr))', gap:10, marginBottom:10 }}>
        <div><div style={{ fontSize:11, color:'var(--text4)', marginBottom:3 }}>Date</div>
          <input className="tv-input" type="date" value={form.trade_date} onChange={e => setForm({...form,trade_date:e.target.value})} /></div>
        <div><div style={{ fontSize:11, color:'var(--text4)', marginBottom:3 }}>Symbol *</div>
          <input className="tv-input" placeholder="BTC" value={form.symbol} onChange={e => setForm({...form,symbol:e.target.value})} /></div>
        <div><div style={{ fontSize:11, color:'var(--text4)', marginBottom:3 }}>Side</div>
          <select className="tv-select" value={form.side} onChange={e => setForm({...form,side:e.target.value})} style={{ width:'100%' }}>
            <option value="buy">Buy</option><option value="sell">Sell</option>
          </select></div>
        <div><div style={{ fontSize:11, color:'var(--text4)', marginBottom:3 }}>Units *</div>
          <input className="tv-input" type="number" value={form.units} onChange={e => setForm({...form,units:e.target.value})} /></div>
        <div><div style={{ fontSize:11, color:'var(--text4)', marginBottom:3 }}>Price USD *</div>
          <input className="tv-input" type="number" value={form.price_usd} onChange={e => setForm({...form,price_usd:e.target.value})} /></div>
        <div><div style={{ fontSize:11, color:'var(--text4)', marginBottom:3 }}>Platform</div>
          <input className="tv-input" placeholder="e.g. Binance" value={form.platform} onChange={e => setForm({...form,platform:e.target.value})} /></div>
        <div style={{ gridColumn:'span 2' }}><div style={{ fontSize:11, color:'var(--text4)', marginBottom:3 }}>Notes</div>
          <input className="tv-input" value={form.notes} onChange={e => setForm({...form,notes:e.target.value})} /></div>
      </div>
      {err && <div style={{ color:'var(--fail)', fontSize:12, marginBottom:8 }}>{err}</div>}
      <div style={{ display:'flex', gap:8 }}>
        <button className="tv-btn primary" onClick={save} disabled={saving}>{saving?'Saving…':'Save'}</button>
        <button className="tv-btn" onClick={() => setShowForm(false)}>Cancel</button>
      </div>
    </div>}

    {/* Table */}
    {loading ? <div style={{ padding:40, textAlign:'center', color:'var(--text4)' }}><div className="spin" style={{ display:'inline-block', width:24, height:24, border:'2px solid var(--line)', borderTopColor:'var(--accent)', borderRadius:'50%' }} /></div>
    : !rows || rows.length === 0
      ? <div style={{ color:'var(--text4)', padding:20, textAlign:'center' }}>No transactions yet.</div>
      : <div className="tv-card" style={{ padding:0, overflow:'hidden' }}>
          <table className="tv-table">
            <thead><tr>
              <th>Date</th><th>Side</th><th>Token</th><th className="num">Units</th>
              <th className="num">Price</th><th className="num">Total</th><th>Platform</th><th>Notes</th><th></th>
            </tr></thead>
            <tbody>{rows.map(r => {
              const isBuy = r.side === 'buy';
              const total = (r.units || 0) * (r.price_usd || 0);
              return <tr key={r.id}>
                <td style={{ whiteSpace:'nowrap' }}>{r.trade_date}</td>
                <td><span className={`tv-chip ${isBuy?'ok':'fail'}`} style={{ fontSize:10 }}>{r.side.toUpperCase()}</span></td>
                <td style={{ fontWeight:700, color:'var(--text)' }}>{r.symbol}</td>
                <td className="num tv-num">{mvn(r.units)}</td>
                <td className="num tv-num">{mv(r.price_usd)}</td>
                <td className="num tv-num" style={{ fontWeight:600 }}>{mv(total)}</td>
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
