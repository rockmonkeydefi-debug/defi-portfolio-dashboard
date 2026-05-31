/* ===== ARCHIVE SCREEN ===== */
const { useState, useEffect } = React;

function ArchivedLPTab({ hideValues }) {
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api('/api/archive/lp').then(d => setPositions(Array.isArray(d) ? d : [])).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, []);

  async function restore(id) {
    await api(`/api/restore/lp/${id}`, { method:'POST' }).catch(() => {});
    load();
  }
  async function del(id) {
    if (!confirm('Permanently delete this archived LP position?')) return;
    await api(`/api/archive/lp/${id}`, { method:'DELETE' }).catch(() => {});
    load();
  }

  if (loading) return <div style={{ padding:40, textAlign:'center', color:'var(--text4)' }}><div className="spin" style={{ display:'inline-block', width:24, height:24, border:'2px solid var(--line)', borderTopColor:'var(--accent)', borderRadius:'50%' }} /></div>;

  if (positions.length === 0) return <div style={{ color:'var(--text4)', textAlign:'center', padding:40 }}>No archived LP positions.</div>;

  return <div>
    <div style={{ fontSize:12, color:'var(--text4)', marginBottom:12 }}>{positions.length} archived position{positions.length !== 1 ? 's' : ''}</div>
    {positions.map(pos => {
      const pair = `${pos.token0||'?'}/${pos.token1||'?'}`;
      const chain = pos.chain ? (pos.chain.charAt(0).toUpperCase() + pos.chain.slice(1)) : '—';
      return <div key={pos.id} className="tv-card" style={{ marginBottom:10, borderColor:'var(--line)', opacity:0.9 }}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start' }}>
          <div>
            <div style={{ fontWeight:700, fontSize:14, color:'var(--text)', marginBottom:4 }}>{pair}</div>
            <div style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
              <span style={{ fontSize:10, fontWeight:600, padding:'1px 6px', borderRadius:4, border:'1px solid var(--line)', color:'var(--text)', background:'var(--panel3)' }}>{chain}</span>
              {pos.protocol && <span style={{ fontSize:11, color:'var(--text4)' }}>{pos.protocol}</span>}
              {pos.notes && <span style={{ fontSize:11, color:'var(--text4)', fontStyle:'italic' }}>{pos.notes}</span>}
            </div>
          </div>
          <div style={{ textAlign:'right', flexShrink:0 }}>
            <div className="tv-num" style={{ fontSize:16, fontWeight:700, color:'var(--text3)' }}>{hideValues ? '••••' : (pos.value_usd ? fmt(pos.value_usd) : '—')}</div>
            <div style={{ fontSize:10, color:'var(--text4)' }}>at close</div>
          </div>
        </div>
        {pos.updated_at && <div style={{ fontSize:10, color:'var(--text4)', marginTop:6 }}>Archived: {formatDate(pos.updated_at)}</div>}
        <div style={{ display:'flex', gap:6, marginTop:10 }}>
          <button className="tv-btn primary" style={{ fontSize:11, padding:'3px 10px' }} onClick={() => restore(pos.id)}>↩ Restore</button>
          <button className="tv-btn danger" style={{ fontSize:11, padding:'3px 10px' }} onClick={() => del(pos.id)}>✕ Delete</button>
        </div>
      </div>;
    })}
  </div>;
}

function ArchivedLendingTab({ hideValues }) {
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api('/api/archive/lending').then(d => setPositions(Array.isArray(d) ? d : [])).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, []);

  async function restore(key) {
    await api(`/api/restore/lending/${encodeURIComponent(key)}`, { method:'POST' }).catch(() => {});
    load();
  }
  async function del(key) {
    if (!confirm('Permanently remove this archived lending position?')) return;
    await api(`/api/archive/lending/${encodeURIComponent(key)}`, { method:'DELETE' }).catch(() => {});
    load();
  }

  if (loading) return <div style={{ padding:40, textAlign:'center', color:'var(--text4)' }}><div className="spin" style={{ display:'inline-block', width:24, height:24, border:'2px solid var(--line)', borderTopColor:'var(--accent)', borderRadius:'50%' }} /></div>;

  if (positions.length === 0) return <div style={{ color:'var(--text4)', textAlign:'center', padding:40 }}>No archived lending positions.</div>;

  return <div>
    <div style={{ fontSize:12, color:'var(--text4)', marginBottom:12 }}>{positions.length} archived position{positions.length !== 1 ? 's' : ''}</div>
    {positions.map(pos => {
      const snap = pos.snapshot || {};
      const hf = snap.health_factor || 0;
      const hfColor = hf > 3 ? 'var(--ok)' : hf > 2 ? 'var(--adapt)' : hf > 1.5 ? 'var(--warn)' : 'var(--fail)';
      return <div key={pos.position_key} className="tv-card" style={{ marginBottom:10, borderColor:'var(--line)', opacity:0.9 }}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start' }}>
          <div>
            <div style={{ fontWeight:700, fontSize:14, color:'var(--text)', marginBottom:4 }}>{pos.protocol || 'AAVE'} — {pos.chain}</div>
            <div style={{ fontSize:11, color:'var(--text4)' }}>{pos.wallet ? pos.wallet.slice(0,8)+'…'+pos.wallet.slice(-4) : '—'}</div>
          </div>
          {hf > 0 && <div style={{ textAlign:'right' }}>
            <div className="tv-num" style={{ fontSize:18, fontWeight:700, color:hfColor }}>{hf > 100 ? '∞' : fmtNum(hf,2)}</div>
            <div style={{ fontSize:10, color:'var(--text4)' }}>HF at archive</div>
          </div>}
        </div>
        {snap.total_collateral_usd > 0 && <div style={{ fontSize:12, color:'var(--text4)', marginTop:6 }}>
          Supplied: {hideValues ? '••••' : fmt(snap.total_collateral_usd)} · Borrowed: {hideValues ? '••••' : fmt(snap.total_debt_usd||0)}
        </div>}
        <div style={{ fontSize:10, color:'var(--text4)', marginTop:4 }}>Archived: {formatDate(pos.archived_at)}</div>
        <div style={{ display:'flex', gap:6, marginTop:10 }}>
          <button className="tv-btn primary" style={{ fontSize:11, padding:'3px 10px' }} onClick={() => restore(pos.position_key)}>↩ Restore</button>
          <button className="tv-btn danger" style={{ fontSize:11, padding:'3px 10px' }} onClick={() => del(pos.position_key)}>✕ Delete</button>
        </div>
      </div>;
    })}
  </div>;
}

function ArchivedSpotTradesTab({ hideValues }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api('/api/spot/history').then(d => setData(Array.isArray(d) ? d : (d.trades || d))).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) return <div style={{ padding:40, textAlign:'center', color:'var(--text4)' }}><div className="spin" style={{ display:'inline-block', width:24, height:24, border:'2px solid var(--line)', borderTopColor:'var(--accent)', borderRadius:'50%' }} /></div>;

  const trades = Array.isArray(data) ? data : [];
  if (trades.length === 0) return <div style={{ color:'var(--text4)', textAlign:'center', padding:40 }}>No trade history. Add buy/sell transactions to get started.</div>;

  const totalReal = trades.reduce((s,r) => s+(r.realized_pnl_usd||0), 0);
  const totalFees = trades.reduce((s,r) => s+(r.fees_usd||0), 0);

  return <div>
    <div style={{ display:'flex', gap:10, flexWrap:'wrap', marginBottom:16 }}>
      <div className="tv-card" style={{ flex:1, minWidth:130 }}>
        <div className="tv-label" style={{ marginBottom:4 }}>Realized P&L</div>
        <div className="tv-num" style={{ fontSize:16, fontWeight:700, color:totalReal>=0?'var(--ok)':'var(--fail)' }}>{hideValues ? '••••' : (totalReal>=0?'+':'')+fmt(totalReal)}</div>
      </div>
      <div className="tv-card" style={{ flex:1, minWidth:130 }}>
        <div className="tv-label" style={{ marginBottom:4 }}>Closed Trades</div>
        <div className="tv-num" style={{ fontSize:16, fontWeight:700 }}>{trades.length}</div>
      </div>
      {totalFees > 0 && <div className="tv-card" style={{ flex:1, minWidth:130 }}>
        <div className="tv-label" style={{ marginBottom:4 }}>Total Fees</div>
        <div className="tv-num" style={{ fontSize:16, fontWeight:700, color:'var(--warn)' }}>{hideValues ? '••••' : fmt(totalFees)}</div>
      </div>}
    </div>

    <div className="tv-card" style={{ padding:0, overflow:'hidden' }}>
      <table className="tv-table">
        <thead><tr>
          <th>Symbol</th>
          <th className="num">Avg Buy</th><th className="num">Avg Sell</th>
          <th className="num">Units Sold</th><th className="num">Realized P&L</th><th className="num">P&L %</th>
        </tr></thead>
        <tbody>{trades.map((r,i) => {
          const pnlColor = r.realized_pnl_usd >= 0 ? 'var(--ok)' : 'var(--fail)';
          return <tr key={i}>
            <td style={{ fontWeight:700, color:'var(--text)' }}>{r.symbol}</td>
            <td className="num tv-num">{r.avg_buy_price != null ? (hideValues ? '••••' : fmtNum(r.avg_buy_price,4)) : '—'}</td>
            <td className="num tv-num">{r.avg_sell_price != null ? (hideValues ? '••••' : fmtNum(r.avg_sell_price,4)) : '—'}</td>
            <td className="num tv-num">{r.units_sold != null ? fmtNum(r.units_sold,4) : '—'}</td>
            <td className="num tv-num" style={{ color:pnlColor, fontWeight:600 }}>{r.realized_pnl_usd != null ? (r.realized_pnl_usd>=0?'+':'')+( hideValues ? '••••' : fmt(r.realized_pnl_usd)) : '—'}</td>
            <td className="num tv-num" style={{ color:pnlColor }}>{r.realized_pnl_pct != null ? fmtPct(r.realized_pnl_pct) : '—'}</td>
          </tr>;
        })}</tbody>
      </table>
    </div>
  </div>;
}

function ArchivedStakingTab({ hideValues }) {
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api('/api/archive/staking').then(d => setPositions(Array.isArray(d) ? d : [])).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, []);

  async function restore(id) {
    await api(`/api/restore/staking/${id}`, { method:'POST' }).catch(() => {});
    load();
  }
  async function del(id) {
    if (!confirm('Permanently delete this archived staking position?')) return;
    await api(`/api/archive/staking/${id}`, { method:'DELETE' }).catch(() => {});
    load();
  }

  if (loading) return <div style={{ padding:40, textAlign:'center', color:'var(--text4)' }}><div className="spin" style={{ display:'inline-block', width:24, height:24, border:'2px solid var(--line)', borderTopColor:'var(--accent)', borderRadius:'50%' }} /></div>;

  if (positions.length === 0) return <div style={{ color:'var(--text4)', textAlign:'center', padding:40 }}>No archived DeFi protocol positions.</div>;

  return <div>
    <div style={{ fontSize:12, color:'var(--text4)', marginBottom:12 }}>{positions.length} archived position{positions.length !== 1 ? 's' : ''}</div>
    {positions.map(pos => {
      const locked = pos.lock_end_date && new Date(pos.lock_end_date) > new Date();
      return <div key={pos.id} className="tv-card" style={{ marginBottom:10, borderColor:'var(--line)', opacity:0.9 }}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start' }}>
          <div>
            <div style={{ display:'flex', gap:6, alignItems:'center', flexWrap:'wrap', marginBottom:4 }}>
              <span style={{ fontWeight:700, color:'var(--text)' }}>{pos.app_name}</span>
              <span style={{ fontSize:10, fontWeight:600, padding:'1px 6px', borderRadius:4, border:'1px solid var(--line)', color:'var(--text)', background:'var(--panel3)' }}>{pos.chain}</span>
              {pos.position_label && <span style={{ fontSize:11, color:'var(--text4)' }}>{pos.position_label}</span>}
              {locked && <span style={{ fontSize:10, padding:'1px 6px', borderRadius:4, background:'var(--warn)', color:'#000' }}>🔒 Locked</span>}
            </div>
            <div style={{ fontSize:13, color:'var(--text2)' }}>
              {fmtNum(pos.staked_amount,4)} {pos.token_symbol}
              {pos.staked_value_usd > 0 && <span style={{ color:'var(--text4)', marginLeft:6 }}>({hideValues ? '••••' : fmt(pos.staked_value_usd)})</span>}
            </div>
          </div>
          <div style={{ textAlign:'right', flexShrink:0 }}>
            <div className="tv-num" style={{ fontSize:16, fontWeight:700, color:'var(--text3)' }}>{hideValues ? '••••' : fmt(pos.staked_value_usd||0)}</div>
          </div>
        </div>
        {pos.notes && <div style={{ fontSize:12, color:'var(--text4)', marginTop:4 }}>{pos.notes}</div>}
        <div style={{ display:'flex', gap:6, marginTop:10 }}>
          <button className="tv-btn primary" style={{ fontSize:11, padding:'3px 10px' }} onClick={() => restore(pos.id)}>↩ Restore</button>
          <button className="tv-btn danger" style={{ fontSize:11, padding:'3px 10px' }} onClick={() => del(pos.id)}>✕ Delete</button>
        </div>
      </div>;
    })}
  </div>;
}

function ArchiveScreen({ hideValues, archiveSubTab }) {
  const activeTab = archiveSubTab || 'lp';

  return <div>
    {activeTab === 'lp' && <ArchivedLPTab hideValues={hideValues} />}
    {activeTab === 'lending' && <ArchivedLendingTab hideValues={hideValues} />}
    {activeTab === 'spot' && <ArchivedSpotTradesTab hideValues={hideValues} />}
    {activeTab === 'staking' && <ArchivedStakingTab hideValues={hideValues} />}
  </div>;
}

window.ArchiveScreen = ArchiveScreen;
