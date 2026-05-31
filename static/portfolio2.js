/* ===== PORTFOLIO SCREEN — Playbook Phase 2 ===== */
const { useState, useEffect, useCallback, useMemo } = React;

// ─── constants ────────────────────────────────────────────────────────────────

const CG_ICONS = {
  BTC:'https://assets.coingecko.com/coins/images/1/small/bitcoin.png',
  ETH:'https://assets.coingecko.com/coins/images/279/small/ethereum.png',
  WETH:'https://assets.coingecko.com/coins/images/2518/small/weth.png',
  USDC:'https://assets.coingecko.com/coins/images/6319/small/usdc.png',
  USDT:'https://assets.coingecko.com/coins/images/325/small/Tether.png',
  DAI:'https://assets.coingecko.com/coins/images/9956/small/Badge_Dai.png',
  WBTC:'https://assets.coingecko.com/coins/images/7598/small/wrapped_bitcoin_wbtc.png',
  ARB:'https://assets.coingecko.com/coins/images/16547/small/arb.jpg',
  cbBTC:'https://assets.coingecko.com/coins/images/40143/small/cbbtc.webp',
  AAVE:'https://assets.coingecko.com/coins/images/12645/small/aave-token-round.png',
  LINK:'https://assets.coingecko.com/coins/images/877/small/chainlink-new-logo.png',
  UNI:'https://assets.coingecko.com/coins/images/12504/small/uni.jpg',
};
const CHAIN_COLORS = { Ethereum:'#627eea', Arbitrum:'#28a0f0', Base:'#0052ff', Bitcoin:'#f7931a', Optimism:'#ff0420', Polygon:'#8247e5' };
const TOKEN_GROUPS = {
  ETH:['ETH','WETH','stETH','wstETH','cbETH','rETH','weETH','eETH'],
  BTC:['BTC','WBTC','cbBTC','tBTC','sBTC'],
  Stablecoins:['USDC','USDT','DAI','FRAX','LUSD','TUSD','BUSD','GHO','USDe','USDS','USDC.e','USDT0','crvUSD'],
};
const JOURNAL_ACTIONS = ['note','rebalance','added','removed','collected_fees','other'];
const LP_CHAINS = ['ethereum','arbitrum','base','bitcoin','polygon','optimism'];

// ─── helpers ──────────────────────────────────────────────────────────────────

function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''; }
function mv(v, hide) { return hide ? '••••' : fmt(v); }
function mvn(v, d, hide) { return hide ? '••••' : fmtNum(v, d); }

function tokenSymbolColor(sym) {
  var h = 0;
  for (var i = 0; i < sym.length; i++) h = sym.charCodeAt(i) + ((h << 5) - h);
  return 'hsl(' + (h & 0x7fffffff) % 360 + ',55%,55%)';
}

function isYieldToken(sym) {
  return /^a[A-Z]/.test(sym) || /^wa[A-Z]/.test(sym) || /^c[A-Z]/.test(sym) ||
    /^stk/.test(sym) || /^PT-|^YT-/.test(sym) || /\.v\d/.test(sym) ||
    ['sDAI','sUSDe','sFRAX'].includes(sym);
}
function isStablecoin(sym) {
  if (TOKEN_GROUPS.Stablecoins.includes(sym)) return true;
  var s = sym.toLowerCase();
  return s.includes('usdc')||s.includes('usdt')||s.includes('usd')||s.includes('dai');
}
function tokenGroup(sym) {
  for (var g in TOKEN_GROUPS) if (TOKEN_GROUPS[g].includes(sym)) return g;
  if (isYieldToken(sym)) return 'Yield';
  if (isStablecoin(sym)) return 'Stablecoins';
  return 'Other';
}

function normLP(pos, source) {
  var chain = (pos.chain || '').toLowerCase();
  return {
    ...pos,
    _source: source,
    _key: source === 'manual'
      ? 'manual-' + pos.id
      : 'zerion-' + [pos.wallet, pos.protocol, pos.chain, pos.pair].join('-'),
    pair: pos.pair || ((pos.token0||pos.token0_symbol||'?')+'/'+(pos.token1||pos.token1_symbol||'?')),
    chain_display: cap(chain),
    token0_symbol: pos.token0 || pos.token0_symbol || '?',
    token1_symbol: pos.token1 || pos.token1_symbol || '?',
    total_value_usd: pos.total_value_usd || pos.value_usd || 0,
    fees_uncollected: pos.total_fees_usd || pos.fees_uncollected_usd || 0,
    fees_collected: pos.fees_collected_usd || 0,
    entry_value_usd: pos.entry_value_usd || (pos.pnl ? pos.pnl.entry_value : null),
    price_lower: pos.price_lower || pos.range_lower || 0,
    price_upper: pos.price_upper || pos.range_upper || 0,
    current_price: pos.current_price || 0,
    in_range: pos.in_range != null ? pos.in_range : null,
    age_days: pos.age_days != null ? pos.age_days : null,
    age_hours: pos.age_hours || 0,
    wallet_label: pos.wallet_label || '',
    wallet: pos.wallet || '',
    pnl: source === 'manual' ? pos.pnl : null,
  };
}

// ─── tiny UI components ───────────────────────────────────────────────────────

function TokenAvatar({ symbol, size=24 }) {
  const [err, setErr] = useState(false);
  const url = CG_ICONS[symbol];
  if (!url || err) {
    return <div style={{ width:size, height:size, borderRadius:'50%', background:tokenSymbolColor(symbol||'?'),
      display:'inline-flex', alignItems:'center', justifyContent:'center',
      fontSize:size*0.42, fontWeight:700, color:'#fff', flexShrink:0, verticalAlign:'middle' }}>
      {(symbol||'?')[0].toUpperCase()}
    </div>;
  }
  return <img src={url} width={size} height={size} style={{ borderRadius:'50%', verticalAlign:'middle', flexShrink:0 }} onError={() => setErr(true)} alt={symbol} />;
}

function ChainBadge({ chain }) {
  const c = cap(chain);
  return <span style={{ fontSize:10, fontWeight:600, padding:'1px 6px', borderRadius:4, border:'1px solid var(--line)', color:'var(--text)', background:'var(--panel3)', whiteSpace:'nowrap' }}>{c}</span>;
}

function WalletBadge({ label }) {
  if (!label) return null;
  return <span style={{ fontSize:10, padding:'1px 6px', borderRadius:4, border:'1px solid var(--line)', color:'var(--text4)', background:'var(--panel2)', whiteSpace:'nowrap' }}>{label}</span>;
}

function SegTabs({ tabs, active, onChange }) {
  return <div style={{ display:'flex', gap:4, marginBottom:20 }}>
    {tabs.map(t => <button key={t.id} className="tv-btn"
      style={{ background:active===t.id?'var(--panel3)':'transparent', borderColor:active===t.id?'var(--accent-line)':'var(--line)',
        color:active===t.id?'var(--text)':'var(--text3)', fontWeight:active===t.id?600:400 }}
      onClick={() => onChange(t.id)}>{t.label}</button>)}
  </div>;
}

function SummaryCard({ label, value, sub, color }) {
  return <div className="tv-card" style={{ flex:1, minWidth:130 }}>
    <div className="tv-label" style={{ marginBottom:6 }}>{label}</div>
    <div className="tv-num" style={{ fontSize:18, fontWeight:700, color:color||'var(--text)' }}>{value}</div>
    {sub && <div style={{ fontSize:11, color:'var(--text4)', marginTop:2 }}>{sub}</div>}
  </div>;
}

function Modal({ title, onClose, children, width=520 }) {
  return <div style={{ position:'fixed', inset:0, background:'rgba(0,0,0,0.75)', zIndex:1000, display:'flex', alignItems:'center', justifyContent:'center', padding:16 }}>
    <div className="tv-card" style={{ width, maxWidth:'95vw', maxHeight:'90vh', overflowY:'auto' }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16 }}>
        <h3 style={{ margin:0, fontSize:15 }}>{title}</h3>
        <button onClick={onClose} style={{ background:'none', border:'none', color:'var(--text3)', fontSize:20, cursor:'pointer', lineHeight:1 }}>×</button>
      </div>
      {children}
    </div>
  </div>;
}

function Field({ label, children, help }) {
  return <div>
    <div style={{ fontSize:11, color:'var(--text4)', marginBottom:3 }}>{label}</div>
    {children}
    {help && <div style={{ fontSize:10, color:'var(--text4)', marginTop:2 }}>{help}</div>}
  </div>;
}

function Spinner() {
  return <div style={{ padding:40, textAlign:'center', color:'var(--text4)' }}>
    <div style={{ display:'inline-block', width:24, height:24, border:'2px solid var(--line)', borderTopColor:'var(--accent)', borderRadius:'50%' }} className="spin" />
  </div>;
}

// ─── Journal section ──────────────────────────────────────────────────────────

function JournalSection({ positionType, positionId }) {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [action, setAction] = useState('note');
  const [details, setDetails] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api(`/api/defi-journal/${positionType}/${encodeURIComponent(positionId)}`)
      .then(d => setEntries(Array.isArray(d) ? d : (d.entries || [])))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [open]);

  async function save() {
    if (!details.trim()) return;
    setSaving(true);
    try {
      await api('/api/defi-journal', { method:'POST', body:JSON.stringify({ position_type:positionType, position_id:String(positionId), action, details }) });
      setDetails(''); setShowForm(false);
      const d = await api(`/api/defi-journal/${positionType}/${encodeURIComponent(positionId)}`);
      setEntries(Array.isArray(d) ? d : (d.entries || []));
    } catch(e) {} finally { setSaving(false); }
  }

  async function del(id) {
    if (!confirm('Delete entry?')) return;
    await api(`/api/defi-journal/${id}`, { method:'DELETE' }).catch(() => {});
    setEntries(entries.filter(e => e.id !== id));
  }

  return <div style={{ borderTop:'1px solid var(--line-soft)', marginTop:10, paddingTop:8 }}>
    <button className="tv-btn" style={{ fontSize:11, padding:'3px 10px' }} onClick={() => setOpen(!open)}>
      {open ? '▼' : '▶'} Journal{!open && entries.length > 0 ? ` (${entries.length})` : ''}
    </button>
    {open && <div style={{ marginTop:8, fontSize:12 }}>
      {loading && <div style={{ color:'var(--text4)' }}>Loading…</div>}
      {entries.map(e => <div key={e.id} style={{ padding:'5px 0', borderBottom:'1px solid var(--line-soft)', display:'flex', gap:8, alignItems:'flex-start' }}>
        <div style={{ flex:1 }}>
          <span className="tv-chip accent" style={{ fontSize:10, marginRight:6 }}>{e.action}</span>
          <span style={{ color:'var(--text2)' }}>{e.details}</span>
          <div style={{ color:'var(--text4)', fontSize:10, marginTop:2 }}>{formatDate(e.created_at)}</div>
        </div>
        <button style={{ background:'none', border:'none', color:'var(--fail)', cursor:'pointer', fontSize:16, padding:'0 2px', lineHeight:1 }} onClick={() => del(e.id)}>×</button>
      </div>)}
      {!loading && entries.length === 0 && <div style={{ color:'var(--text4)', padding:'4px 0' }}>No entries yet.</div>}
      {showForm
        ? <div style={{ display:'flex', gap:6, flexWrap:'wrap', marginTop:8 }}>
            <select className="tv-select" value={action} onChange={e => setAction(e.target.value)} style={{ fontSize:11, padding:'4px 8px', width:130 }}>
              {JOURNAL_ACTIONS.map(a => <option key={a} value={a}>{a}</option>)}
            </select>
            <textarea className="tv-input" placeholder="Details…" value={details} onChange={e => setDetails(e.target.value)} rows={2}
              style={{ flex:1, minWidth:160, fontSize:12, resize:'vertical' }} />
            <div style={{ display:'flex', gap:4, alignItems:'flex-start' }}>
              <button className="tv-btn primary" onClick={save} disabled={saving} style={{ fontSize:11, padding:'4px 10px' }}>Save</button>
              <button className="tv-btn" onClick={() => setShowForm(false)} style={{ fontSize:11, padding:'4px 10px' }}>Cancel</button>
            </div>
          </div>
        : <button className="tv-btn" onClick={() => setShowForm(true)} style={{ fontSize:11, padding:'3px 10px', marginTop:6 }}>+ Add Entry</button>
      }
    </div>}
  </div>;
}

// ─── Fee Claims section ───────────────────────────────────────────────────────

function FeeClaimsSection({ pos, onTotalClaimed }) {
  // Works for both manual (numeric id) and Zerion (string _key) positions
  const posId = pos._source === 'manual' ? pos.id : pos._key;
  const today = new Date().toISOString().split('T')[0];
  const [open, setOpen] = useState(false);
  const [claims, setClaims] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ claimed_at: today, token0_amount:'', token1_amount:'', value_usd:'', notes:'' });
  const [saving, setSaving] = useState(false);

  function loadClaims() {
    if (!posId) return;
    setLoading(true);
    api(`/api/lp/fee-claims/${encodeURIComponent(posId)}`)
      .then(d => {
        const list = Array.isArray(d) ? d : (d.claims || []);
        setClaims(list);
        const total = list.reduce((s, c) => s + (c.value_usd || 0), 0);
        onTotalClaimed && onTotalClaimed(total);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  // Fetch on mount so the total is always available to the parent
  useEffect(() => { loadClaims(); }, []);

  if (!posId) return null;

  async function record() {
    if (!form.claimed_at || !form.value_usd) return;
    setSaving(true);
    try {
      await api('/api/lp/fee-claim', { method:'POST', body:JSON.stringify({
        position_id: posId,
        claimed_at: form.claimed_at,
        token0_amount: parseFloat(form.token0_amount) || 0,
        token1_amount: parseFloat(form.token1_amount) || 0,
        value_usd: parseFloat(form.value_usd),
        notes: form.notes,
      })});
      setForm({ claimed_at: today, token0_amount:'', token1_amount:'', value_usd:'', notes:'' });
      setShowForm(false);
      loadClaims();
    } catch(e) {} finally { setSaving(false); }
  }

  async function deleteClaim(id) {
    if (!confirm('Delete this claim record?')) return;
    await api(`/api/lp/fee-claims/${id}`, { method:'DELETE' }).catch(() => {});
    loadClaims();
  }

  const totalClaimed = claims.reduce((s, c) => s + (c.value_usd || 0), 0);

  return <div style={{ borderTop:'1px solid var(--line-soft)', marginTop:8, paddingTop:8 }}>
    <div style={{ display:'flex', gap:8, alignItems:'center', justifyContent:'space-between' }}>
      <div style={{ display:'flex', gap:8, alignItems:'center' }}>
        <button className="tv-btn" style={{ fontSize:11, padding:'3px 10px' }}
          onClick={() => { setOpen(o => !o); }}>
          {open ? '▼' : '▶'} Claimed Fees{claims.length > 0 ? ` (${claims.length})` : ''}
        </button>
        {open && <button className="tv-btn" style={{ fontSize:11, padding:'3px 10px' }}
          onClick={() => setShowForm(f => !f)}>
          {showForm ? 'Cancel' : '+ Record Claim'}
        </button>}
      </div>
      {totalClaimed > 0 && <span className="tv-num ok" style={{ fontSize:12, fontWeight:600 }}>Total: {fmt(totalClaimed)}</span>}
    </div>

    {open && <>
      {showForm && <div style={{ marginTop:8, padding:10, background:'var(--panel2)', borderRadius:8 }}>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:8, marginBottom:8 }}>
          <Field label="Date">
            <input className="tv-input" type="date" value={form.claimed_at}
              onChange={e => setForm({...form, claimed_at:e.target.value})} />
          </Field>
          <Field label="Value USD *">
            <input className="tv-input" type="number" placeholder="0.00" value={form.value_usd}
              onChange={e => setForm({...form, value_usd:e.target.value})} />
          </Field>
          <Field label={`${pos.token0_symbol} Amount`}>
            <input className="tv-input" type="number" placeholder="0" value={form.token0_amount}
              onChange={e => setForm({...form, token0_amount:e.target.value})} />
          </Field>
          <Field label={`${pos.token1_symbol} Amount`}>
            <input className="tv-input" type="number" placeholder="0" value={form.token1_amount}
              onChange={e => setForm({...form, token1_amount:e.target.value})} />
          </Field>
          <Field label="Notes">
            <input className="tv-input" type="text" value={form.notes}
              onChange={e => setForm({...form, notes:e.target.value})} />
          </Field>
        </div>
        <div style={{ display:'flex', gap:6 }}>
          <button className="tv-btn primary" style={{ fontSize:11 }} onClick={record} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button className="tv-btn" style={{ fontSize:11 }} onClick={() => setShowForm(false)}>Cancel</button>
        </div>
      </div>}

      <div style={{ marginTop:8, fontSize:12 }}>
        {loading && <div style={{ color:'var(--text4)' }}>Loading…</div>}
        {!loading && claims.length === 0 && <div style={{ color:'var(--text4)', padding:'4px 0' }}>No claims recorded.</div>}
        {claims.map(c => <div key={c.id} style={{ padding:'5px 0', borderBottom:'1px solid var(--line-soft)', display:'flex', justifyContent:'space-between', alignItems:'center', gap:8 }}>
          <div style={{ flex:1 }}>
            <span style={{ color:'var(--text2)', marginRight:8 }}>{c.claimed_at}</span>
            {c.token0_amount > 0 && <span style={{ color:'var(--text4)', marginRight:6 }}>{fmtNum(c.token0_amount,4)} {pos.token0_symbol}</span>}
            {c.token1_amount > 0 && <span style={{ color:'var(--text4)', marginRight:6 }}>{fmtNum(c.token1_amount,4)} {pos.token1_symbol}</span>}
            {c.notes && <span style={{ color:'var(--text4)', fontStyle:'italic' }}>{c.notes}</span>}
          </div>
          <span className="tv-num ok" style={{ fontWeight:700, whiteSpace:'nowrap' }}>{fmt(c.value_usd)}</span>
          <button style={{ background:'none', border:'none', color:'var(--fail)', cursor:'pointer', fontSize:16, padding:'0 2px', lineHeight:1 }}
            onClick={() => deleteClaim(c.id)}>×</button>
        </div>)}
      </div>
    </>}
  </div>;
}

// ─── LP Edit modal ────────────────────────────────────────────────────────────

const LP_FIELDS = [
  {k:'chain',l:'Chain',t:'select',opts:LP_CHAINS},{k:'protocol',l:'Protocol',t:'text'},
  {k:'token0',l:'Token 0',t:'text'},{k:'token1',l:'Token 1',t:'text'},
  {k:'amount0',l:'Amount Token 0',t:'number'},{k:'amount1',l:'Amount Token 1',t:'number'},
  {k:'range_lower',l:'Range Lower',t:'number'},{k:'range_upper',l:'Range Upper',t:'number'},
  {k:'fee_tier',l:'Fee Tier %',t:'number'},
  {k:'entry_value_usd',l:'Entry Value (USD)',t:'number',placeholder:'Auto-calculated if left blank',help:'Override for legacy positions where original cost basis is known'},
  {k:'price0_override',l:'Token 0 Price Override',t:'number'},{k:'price1_override',l:'Token 1 Price Override',t:'number'},
  {k:'notes',l:'Notes',t:'textarea'},
];

function LPEditModal({ pos, onClose, onSaved }) {
  const isNew = !pos;
  const [form, setForm] = useState(() => {
    if (pos) return { chain:pos.chain||'ethereum', protocol:pos.protocol||'', token0:pos.token0_symbol||'',
      token1:pos.token1_symbol||'', amount0:pos.amount0||'', amount1:pos.amount1||'',
      range_lower:pos.price_lower||'', range_upper:pos.price_upper||'', fee_tier:pos.fee_tier||'',
      entry_value_usd:pos.entry_value_usd||'', price0_override:'', price1_override:'', notes:pos.notes||'' };
    return { chain:'ethereum', protocol:'', token0:'', token1:'', amount0:'', amount1:'',
      range_lower:'', range_upper:'', fee_tier:'', entry_value_usd:'', price0_override:'', price1_override:'', notes:'' };
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  async function save() {
    if (!form.token0 || !form.token1 || !form.amount0) { setErr('Token 0, Token 1 and Amount 0 are required.'); return; }
    setSaving(true); setErr('');
    try {
      const body = {};
      LP_FIELDS.forEach(f => { if (form[f.k] !== '') body[f.k] = f.t==='number' ? parseFloat(form[f.k]) : form[f.k]; });
      if (isNew) {
        await api('/api/manual-positions', { method:'POST', body:JSON.stringify(body) });
      } else {
        await api(`/api/manual-positions/${pos.id}`, { method:'PUT', body:JSON.stringify({action:'edit',...body}) });
      }
      onSaved();
    } catch(e) { setErr(String(e)); } finally { setSaving(false); }
  }

  return <Modal title={isNew?'Add LP Position':'Edit LP Position'} onClose={onClose}>
    <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:10 }}>
      {LP_FIELDS.map(f => <Field key={f.k} label={f.l} help={f.help}>
        {f.t === 'select'
          ? <select className="tv-select" style={{ width:'100%' }} value={form[f.k]} onChange={e => setForm({...form,[f.k]:e.target.value})}>
              {f.opts.map(o => <option key={o} value={o}>{cap(o)}</option>)}
            </select>
          : f.t === 'textarea'
            ? <textarea className="tv-input" value={form[f.k]} onChange={e => setForm({...form,[f.k]:e.target.value})} rows={2} style={{ gridColumn:'1/-1' }} />
            : <input className="tv-input" type={f.t} placeholder={f.placeholder||''} value={form[f.k]} onChange={e => setForm({...form,[f.k]:e.target.value})} />
        }
      </Field>)}
    </div>
    {err && <div style={{ color:'var(--fail)', fontSize:12, marginTop:8 }}>{err}</div>}
    <div style={{ display:'flex', gap:8, marginTop:14, justifyContent:'flex-end' }}>
      <button className="tv-btn" onClick={onClose}>Cancel</button>
      <button className="tv-btn primary" onClick={save} disabled={saving}>{saving?'Saving…':'Save'}</button>
    </div>
  </Modal>;
}

// ─── LP Card ──────────────────────────────────────────────────────────────────

function LPCard({ pos, hideValues, onRefetch, onRemove }) {
  const [showEdit, setShowEdit] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [claimedTotal, setClaimedTotal] = useState(0);
  const isManual = pos._source === 'manual';
  const hasRange = pos.price_lower > 0 && pos.price_upper > 0 && pos.price_upper !== pos.price_lower;
  const ageText = pos.age_days != null ? `${pos.age_days}d ${pos.age_hours||0}h` : 'N/A';

  const totalPnl = pos.pnl ? pos.pnl.total_pnl : null;
  const totalPnlPct = pos.pnl ? pos.pnl.total_pnl_pct : null;

  async function archive() {
    if (!confirm('Archive this position? It will move to Archive → LP Positions.')) return;
    setArchiving(true);
    try {
      if (isManual) {
        await api(`/api/manual-positions/${pos.id}`, { method:'PUT', body:JSON.stringify({ action:'close' }) });
      } else {
        await api('/api/archive/zerion-lp', { method:'POST', body:JSON.stringify({ position_key: pos._key, pair: pos.pair, chain: pos.chain, wallet: pos.wallet || '', protocol: pos.protocol || '' }) });
      }
      onRemove && onRemove();
    } catch(e) {
      console.error('LP archive failed:', e);
    } finally {
      setArchiving(false);
    }
  }
  async function del() {
    if (!confirm('Permanently delete this position and all its history? This cannot be undone.')) return;
    try {
      await api(`/api/manual-positions/${pos.id}`, { method:'DELETE' });
      onRemove && onRemove();
    } catch(e) {
      console.error('LP delete failed:', e);
    }
  }

  return <div className="tv-card" style={{ marginBottom:12, borderColor:'var(--accent)', borderWidth:'1.5px' }}>
    {/* Header */}
    <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:10 }}>
      <div style={{ display:'flex', flexWrap:'wrap', gap:6, alignItems:'center' }}>
        <TokenAvatar symbol={pos.token0_symbol} size={20} />
        <TokenAvatar symbol={pos.token1_symbol} size={20} />
        <span style={{ fontWeight:700, fontSize:15, color:'var(--text)' }}>{pos.pair}</span>
        <ChainBadge chain={pos.chain_display} />
        {pos.protocol && <span style={{ fontSize:11, color:'var(--text4)' }}>{pos.protocol}</span>}
        {pos.in_range === true && <span className="tv-chip ok" style={{ fontSize:10 }}>● IN RANGE</span>}
        {pos.in_range === false && <span className="tv-chip fail" style={{ fontSize:10 }}>● OUT OF RANGE</span>}
        <WalletBadge label={pos.wallet_label} />
        {pos.fee_tier > 0 && <span style={{ fontSize:10, color:'var(--text4)' }}>{pos.fee_tier}% fee</span>}
        <span style={{ fontSize:10, color:'var(--text4)' }}>Age: {ageText}</span>
      </div>
      <div style={{ textAlign:'right', flexShrink:0 }}>
        <div className="tv-num" style={{ fontSize:20, fontWeight:700, color:'var(--text)' }}>{mv(pos.total_value_usd, hideValues)}</div>
        <div style={{ fontSize:11, color:'var(--text4)', marginBottom:8 }}>Position Value</div>
        <div style={{ display:'flex', gap:4, justifyContent:'flex-end' }}>
          <button className="tv-btn" style={{ fontSize:11, padding:'3px 10px', opacity:isManual?1:0.45 }}
            onClick={isManual ? () => setShowEdit(true) : undefined}
            disabled={!isManual} title={!isManual ? 'Zerion-managed' : undefined}>Edit</button>
          <button className="tv-btn" style={{ fontSize:11, padding:'3px 10px' }} onClick={archive} disabled={archiving}>Archive</button>
          <button className="tv-btn danger" style={{ fontSize:11, padding:'3px 10px', opacity:isManual?1:0.45 }}
            onClick={isManual ? del : undefined}
            disabled={!isManual} title={!isManual ? 'Zerion-managed' : undefined}>✕</button>
        </div>
      </div>
    </div>

    {/* Price range bar */}
    {hasRange && <div style={{ marginBottom:10 }}>
      <PriceRangeBar lower={pos.price_lower} upper={pos.price_upper} current={pos.current_price} />
    </div>}

    {/* Metric row */}
    <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(100px,1fr))', gap:8, marginBottom:10 }}>
      {[{l:'Token 0',v:`${mvn(pos.amount0,4,hideValues)} ${pos.token0_symbol}`},
        {l:'Token 1',v:`${mvn(pos.amount1,4,hideValues)} ${pos.token1_symbol}`},
        {l:'Uncollected Fees',v:mv(pos.fees_uncollected,hideValues),c:'var(--ok)'},
        claimedTotal > 0 && {l:'Total Claimed',v:mv(claimedTotal,hideValues),c:'var(--ok)'},
        pos.daily_apr > 0 && {l:'Daily APR',v:fmtNum(pos.daily_apr,2)+'%',c:'var(--accent)'},
        pos.monthly_apr > 0 && {l:'Monthly APR',v:fmtNum(pos.monthly_apr,2)+'%',c:'var(--accent)'},
      ].filter(Boolean).map((m,i) => <div key={i} className="tv-card-2" style={{ padding:'8px 10px' }}>
        <div style={{ fontSize:10, color:'var(--text4)', marginBottom:2 }}>{m.l}</div>
        <div className="tv-num" style={{ fontSize:13, fontWeight:600, color:m.c||'var(--text2)' }}>{m.v}</div>
      </div>)}
    </div>

    {/* P&L row (manual positions only) */}
    {pos.pnl && <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:8, marginBottom:10, padding:10, background:'var(--panel2)', borderRadius:8 }}>
      {[{l:'Entry Value',v:mv(pos.pnl.entry_value,hideValues)},
        {l:'Current Value',v:mv(pos.pnl.current_value,hideValues)},
        {l:'Total Fees',v:mv(pos.pnl.total_fees,hideValues),c:'var(--ok)'},
        {l:'Total P&L',v:(totalPnl>=0?'+':'')+mv(totalPnl,hideValues)+' ('+fmtPct(totalPnlPct)+')',c:totalPnl>=0?'var(--ok)':'var(--fail)'},
      ].map((m,i) => <div key={i}>
        <div style={{ fontSize:10, color:'var(--text4)', marginBottom:2 }}>{m.l}</div>
        <div className="tv-num" style={{ fontSize:13, fontWeight:600, color:m.c||'var(--text2)' }}>{m.v}</div>
      </div>)}
    </div>}

    {/* Reward strip */}
    {(pos.reward_pending_usd > 0.01 || pos.reward_claimed_usd > 0.01) && <div style={{ fontSize:12, color:'var(--warn)', marginBottom:8 }}>
      Staking rewards ({pos.reward_symbol}): {mvn(pos.reward_pending,4,hideValues)} pending ({mv(pos.reward_pending_usd,hideValues)})
      {pos.reward_claimed > 0 && ` · ${mvn(pos.reward_claimed,4,hideValues)} claimed`}
    </div>}

    <FeeClaimsSection pos={pos} onTotalClaimed={setClaimedTotal} />
    <JournalSection positionType="lp" positionId={pos._key} />

    {showEdit && <LPEditModal pos={isManual ? pos : null} onClose={() => setShowEdit(false)} onSaved={() => { setShowEdit(false); onRefetch(); }} />}
  </div>;
}

// ─── Lending Card ─────────────────────────────────────────────────────────────

function LendingCard({ pos, hideValues, onRefetch, onRemove }) {
  const hf = pos.health_factor || 0;
  const hfColor = hf > 3 ? 'var(--ok)' : hf > 2 ? 'var(--adapt)' : hf > 1.5 ? 'var(--warn)' : 'var(--fail)';
  const hfLabel = hf > 3 ? 'Safe' : hf > 2 ? 'Good' : hf > 1.5 ? 'Caution' : hf > 1 ? 'Danger' : 'CRITICAL';
  const netEquity = (pos.total_collateral_usd||0) - (pos.total_debt_usd||0);
  const currentLtv = pos.total_collateral_usd > 0 ? (pos.total_debt_usd / pos.total_collateral_usd * 100) : 0;
  const posKey = `${pos.chain_name}:${pos.wallet}:${pos.protocol_name||'aave'}`;
  const [archiving, setArchiving] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [editNote, setEditNote] = useState('');
  const [savingNote, setSavingNote] = useState(false);

  async function archive() {
    if (!confirm('Archive this position?')) return;
    setArchiving(true);
    await api('/api/archive/lending', { method:'POST', body:JSON.stringify({
      position_key: posKey, protocol: pos.protocol_name||'aave',
      chain: pos.chain_name, wallet: pos.wallet, snapshot: pos,
    })}).catch(() => {});
    setArchiving(false);
    onRemove && onRemove();
  }

  async function deletePermanently() {
    if (!confirm('Permanently delete this position and all its history? This cannot be undone.')) return;
    await api('/api/archive/lending', { method:'POST', body:JSON.stringify({
      position_key: posKey, protocol: pos.protocol_name||'aave',
      chain: pos.chain_name, wallet: pos.wallet, snapshot: pos,
    })}).catch(() => {});
    await api(`/api/archive/lending/${encodeURIComponent(posKey)}`, { method:'DELETE' }).catch(() => {});
    onRemove && onRemove();
  }

  async function saveNote() {
    if (!editNote.trim()) return;
    setSavingNote(true);
    await api('/api/defi-journal', { method:'POST', body:JSON.stringify({
      position_type: 'lending', position_id: posKey, action: 'note', details: editNote,
    })}).catch(() => {});
    setSavingNote(false);
    setEditNote('');
    setShowEdit(false);
  }

  return <div className="tv-card" style={{ marginBottom:12, borderColor:'var(--accent)', borderWidth:'1.5px' }}>
    <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:12 }}>
      <div>
        <div style={{ display:'flex', gap:6, alignItems:'center', marginBottom:6 }}>
          <ChainBadge chain={pos.chain_name} />
          <WalletBadge label={pos.wallet_label} />
        </div>
        <div style={{ fontSize:15, fontWeight:700 }}>{pos.protocol_name || 'AAVE V3'} — {pos.chain_name}</div>
      </div>
      <div style={{ textAlign:'right' }}>
        <div style={{ fontSize:11, color:'var(--text4)' }}>Health Factor</div>
        <div className="tv-num" style={{ fontSize:28, fontWeight:700, color:hfColor }}>{hf > 100 ? '∞' : mv(hf, hideValues, false) || hf.toFixed(2)}</div>
        <div style={{ fontSize:11, color:hfColor, marginBottom:8 }}>{hfLabel}</div>
        <div style={{ display:'flex', gap:4, justifyContent:'flex-end' }}>
          <button className="tv-btn" style={{ fontSize:11, padding:'3px 10px' }} onClick={() => setShowEdit(true)}>Edit</button>
          <button className="tv-btn" style={{ fontSize:11, padding:'3px 10px' }} onClick={archive} disabled={archiving}>Archive</button>
          <button className="tv-btn danger" style={{ fontSize:11, padding:'3px 10px' }} onClick={deletePermanently}>✕</button>
        </div>
      </div>
    </div>

    {/* Health bar */}
    <div style={{ marginBottom:12 }}>
      <div style={{ display:'flex', justifyContent:'space-between', fontSize:10, color:'var(--text4)', marginBottom:4 }}>
        <span>Liquidation (1.0)</span><span>Safe (5.0+)</span>
      </div>
      <HealthBar value={hf} />
    </div>

    {/* 5-metric row */}
    <div style={{ display:'grid', gridTemplateColumns:'repeat(5,1fr)', gap:8, marginBottom:12 }}>
      {[{l:'Health Factor',v:hf>100?'∞':hf.toFixed(2),c:hfColor},
        {l:'Current LTV',v:fmtNum(currentLtv,1)+'%',c:currentLtv>pos.liquidation_threshold?'var(--fail)':currentLtv>pos.ltv?'var(--warn)':'var(--text2)'},
        {l:'Net Equity',v:mv(netEquity,hideValues),c:'var(--ok)'},
        {l:'Borrow Remaining',v:mv(Math.max(0,(pos.total_collateral_usd||0)*((pos.ltv||0)/100)-(pos.total_debt_usd||0)),hideValues)},
        {l:'Net APY',v:fmtNum((pos.net_apy||0),2)+'%',c:'var(--adapt)'},
      ].map((m,i) => <div key={i} className="tv-card-2" style={{ padding:'8px 10px' }}>
        <div style={{ fontSize:10, color:'var(--text4)', marginBottom:2 }}>{m.l}</div>
        <div className="tv-num" style={{ fontSize:13, fontWeight:600, color:m.c||'var(--text2)' }}>{m.v}</div>
      </div>)}
    </div>

    {/* Liquidation price */}
    {pos.liquidation_price && pos.liquidation_price.current_price > 0 && (() => {
      const lp = pos.liquidation_price;
      const pctAway = lp.type === 'collateral_drop'
        ? ((lp.current_price - lp.liquidation_price) / lp.current_price * 100)
        : ((lp.liquidation_price - lp.current_price) / lp.current_price * 100);
      const liqColor = pctAway < 15 ? 'var(--fail)' : pctAway < 30 ? 'var(--warn)' : 'var(--ok)';
      return <div style={{ padding:'8px 12px', background:'var(--panel2)', borderRadius:8, marginBottom:10, display:'flex', justifyContent:'space-between', alignItems:'center' }}>
        <span style={{ fontSize:11, color:'var(--text4)' }}>⚠ {lp.description}</span>
        <span className="tv-num" style={{ color:liqColor, fontWeight:700 }}>
          {mv(lp.liquidation_price, hideValues)}
          <span style={{ fontSize:10, color:'var(--text4)', marginLeft:6 }}>current: {mv(lp.current_price, hideValues)} · {fmtNum(pctAway,1)}% away</span>
        </span>
      </div>;
    })()}

    {/* Supplied */}
    {pos.supplied?.length > 0 && <div style={{ marginBottom:10 }}>
      <div style={{ fontSize:12, color:'var(--ok)', fontWeight:600, marginBottom:6 }}>↓ Supplied</div>
      <table className="tv-table" style={{ fontSize:12 }}>
        <thead><tr><th>Asset</th><th>Balance</th><th>Value</th><th>APY</th><th>Collateral</th></tr></thead>
        <tbody>{pos.supplied.map((s,i) => <tr key={i}>
          <td><TokenAvatar symbol={s.symbol} size={16} />{' '}{s.symbol}</td>
          <td className="num">{mvn(s.balance,4,hideValues)}</td>
          <td className="num">{mv(s.value_usd,hideValues)}</td>
          <td className="num ok">{fmtNum(s.supply_apy,2)}%</td>
          <td className="num">{s.collateral_enabled ? '✓' : '—'}</td>
        </tr>)}</tbody>
      </table>
    </div>}

    {/* Borrowed */}
    {pos.borrowed?.length > 0 && <div style={{ marginBottom:10 }}>
      <div style={{ fontSize:12, color:'var(--fail)', fontWeight:600, marginBottom:6 }}>↑ Borrowed</div>
      <table className="tv-table" style={{ fontSize:12 }}>
        <thead><tr><th>Asset</th><th>Balance</th><th>Value</th><th>APR</th><th>Type</th></tr></thead>
        <tbody>{pos.borrowed.map((b,i) => <tr key={i}>
          <td><TokenAvatar symbol={b.symbol} size={16} />{' '}{b.symbol}</td>
          <td className="num">{mvn(b.balance,4,hideValues)}</td>
          <td className="num">{mv(b.value_usd,hideValues)}</td>
          <td className="num fail">{fmtNum(b.borrow_apy,2)}%</td>
          <td className="num">{b.is_variable ? 'Variable' : 'Fixed'}</td>
        </tr>)}</tbody>
      </table>
    </div>}

    <JournalSection positionType="lending" positionId={posKey} />

    {showEdit && <Modal title="Add Note" onClose={() => setShowEdit(false)} width={420}>
      <div style={{ marginBottom:10, fontSize:12, color:'var(--text4)' }}>
        Notes are saved as journal entries for this position. Zerion data cannot be locally overridden.
      </div>
      <Field label="Note">
        <textarea className="tv-input" rows={4} value={editNote} onChange={e => setEditNote(e.target.value)}
          placeholder="Enter a note about this position…" style={{ resize:'vertical' }} />
      </Field>
      <div style={{ display:'flex', gap:8, marginTop:14, justifyContent:'flex-end' }}>
        <button className="tv-btn" onClick={() => setShowEdit(false)}>Cancel</button>
        <button className="tv-btn primary" onClick={saveNote} disabled={savingNote}>{savingNote ? 'Saving…' : 'Save Note'}</button>
      </div>
    </Modal>}
  </div>;
}

// ─── Staking section ──────────────────────────────────────────────────────────

const STAKING_FIELDS = [
  {k:'app_name',l:'App Name',t:'text',req:true},{k:'chain',l:'Chain',t:'text',req:true},
  {k:'position_label',l:'Position Label',t:'text'},{k:'token_symbol',l:'Token Symbol',t:'text',req:true},
  {k:'staked_amount',l:'Staked Amount',t:'number',req:true},{k:'staked_value_usd',l:'Staked Value USD',t:'number'},
  {k:'reward_token',l:'Reward Token',t:'text'},{k:'reward_amount',l:'Reward Amount',t:'number'},
  {k:'reward_value_usd',l:'Reward Value USD',t:'number'},{k:'entry_date',l:'Entry Date',t:'date'},
  {k:'lock_end_date',l:'Lock End Date',t:'date'},{k:'wallet_address',l:'Wallet Address',t:'text'},
  {k:'notes',l:'Notes',t:'textarea'},
];
const STAKING_BLANK = Object.fromEntries(STAKING_FIELDS.map(f => [f.k,'']));

function StakingCard({ pos, hideValues, onRefetch }) {
  const locked = pos.lock_end_date && new Date(pos.lock_end_date) > new Date();
  async function hide() {
    await api(`/api/defi-staking/${pos.id}/hide`, { method:'PUT' }).catch(() => {});
    onRefetch();
  }
  async function archive() {
    if (!confirm('Archive this staking position? It will move to the Archive tab.')) return;
    await api(`/api/defi-staking/${pos.id}/archive`, { method:'PUT' }).catch(() => {});
    onRefetch();
  }
  async function del() {
    if (!confirm('Permanently delete this staking position?')) return;
    await api(`/api/defi-staking/${pos.id}`, { method:'DELETE' }).catch(() => {});
    onRefetch();
  }
  return <div className="tv-card" style={{ marginBottom:10, borderColor:'var(--adapt)', borderWidth:'1.5px' }}>
    <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:8 }}>
      <div>
        <div style={{ display:'flex', gap:6, alignItems:'center', flexWrap:'wrap', marginBottom:4 }}>
          <span style={{ fontWeight:700, color:'var(--text)' }}>{pos.app_name}</span>
          <ChainBadge chain={pos.chain} />
          {pos.wallet_address && <WalletBadge label={pos.wallet_address.slice(0,6)+'…'+pos.wallet_address.slice(-4)} />}
          {pos.position_label && <span style={{ fontSize:11, color:'var(--text4)' }}>{pos.position_label}</span>}
          {locked && <span className="tv-chip warn" style={{ fontSize:10 }}>🔒 Locked until {formatDateShort(pos.lock_end_date)}</span>}
        </div>
        <div style={{ fontSize:13, color:'var(--text2)' }}>
          <span className="tv-num">{mvn(pos.staked_amount,4,hideValues)}</span> {pos.token_symbol}
          {pos.staked_value_usd > 0 && <span style={{ color:'var(--text4)', marginLeft:6 }}>({mv(pos.staked_value_usd,hideValues)})</span>}
        </div>
      </div>
      <div style={{ textAlign:'right', flexShrink:0 }}>
        <div className="tv-num" style={{ fontSize:18, fontWeight:700, color:'var(--accent)' }}>{mv(pos.staked_value_usd||0,hideValues)}</div>
        <div style={{ fontSize:11, color:'var(--text4)' }}>Staked Value</div>
      </div>
    </div>
    {(pos.reward_amount > 0 || pos.reward_token) && <div style={{ fontSize:12, color:'var(--ok)', marginBottom:8 }}>
      Rewards: {mvn(pos.reward_amount,4,hideValues)} {pos.reward_token}
      {pos.reward_value_usd > 0 && <span style={{ color:'var(--text4)', marginLeft:4 }}>({mv(pos.reward_value_usd,hideValues)})</span>}
    </div>}
    {pos.notes && <div style={{ fontSize:12, color:'var(--text4)', marginBottom:8 }}>{pos.notes}</div>}
    <div style={{ display:'flex', gap:6 }}>
      <button className="tv-btn" style={{ fontSize:11, padding:'3px 10px' }} onClick={hide} title="Hide from portfolio view">Hide</button>
      <button className="tv-btn danger" style={{ fontSize:11, padding:'3px 10px' }} onClick={archive}>Archive</button>
      <button className="tv-btn danger" style={{ fontSize:11, padding:'3px 10px' }} onClick={del}>✕ Delete</button>
    </div>
    <JournalSection positionType="staking" positionId={String(pos.id)} />
  </div>;
}

function ProtocolsTab({ hideValues }) {
  const [staking, setStaking] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState(STAKING_BLANK);
  const [saving, setSaving] = useState(false);
  const [selectedProtocol, setSelectedProtocol] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    api('/api/defi-staking').then(d => {
      const rows = Array.isArray(d) ? d : (d.positions||[]);
      setStaking(rows);
      if (rows.length > 0 && !selectedProtocol) {
        setSelectedProtocol(rows[0].app_name);
      }
    }).catch(()=>{}).finally(()=>setLoading(false));
  }, []);
  useEffect(load, []);

  async function add() {
    if (!form.app_name || !form.token_symbol || !form.staked_amount) return;
    setSaving(true);
    const body = {};
    STAKING_FIELDS.forEach(f => { if (form[f.k] !== '') body[f.k] = f.t==='number' ? parseFloat(form[f.k]) : form[f.k]; });
    await api('/api/defi-staking', { method:'POST', body:JSON.stringify(body) }).catch(()=>{});
    setForm(STAKING_BLANK); setShowAdd(false); setSaving(false); load();
  }

  const protocols = useMemo(() => {
    const map = {};
    staking.forEach(p => {
      if (!map[p.app_name]) map[p.app_name] = { positions:[], total:0, rewards:0 };
      map[p.app_name].positions.push(p);
      map[p.app_name].total += p.staked_value_usd||0;
      map[p.app_name].rewards += p.reward_value_usd||0;
    });
    return map;
  }, [staking]);

  const protocolNames = Object.keys(protocols).sort();
  const activeProtocol = selectedProtocol && protocols[selectedProtocol] ? selectedProtocol : protocolNames[0] || null;
  const activePositions = activeProtocol ? protocols[activeProtocol].positions : [];
  const totalStaked = staking.reduce((s,p) => s+(p.staked_value_usd||0), 0);
  const totalRewards = staking.reduce((s,p) => s+(p.reward_value_usd||0), 0);

  return <div>
    <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12 }}>
      <div>
        {staking.length > 0 && <div style={{ fontSize:12, color:'var(--text4)' }}>
          Total: {mv(totalStaked,hideValues)} · Rewards: {mv(totalRewards,hideValues)}
        </div>}
      </div>
      <button className="tv-btn primary" style={{ fontSize:12 }} onClick={() => setShowAdd(!showAdd)}>+ Add Staking Position</button>
    </div>

    {showAdd && <div className="tv-card" style={{ marginBottom:12 }}>
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:8, marginBottom:10 }}>
        {STAKING_FIELDS.map(f => <Field key={f.k} label={f.l + (f.req?' *':'')}>
          {f.t === 'textarea'
            ? <textarea className="tv-input" value={form[f.k]} onChange={e => setForm({...form,[f.k]:e.target.value})} rows={2} />
            : <input className="tv-input" type={f.t} value={form[f.k]} onChange={e => setForm({...form,[f.k]:e.target.value})} />}
        </Field>)}
      </div>
      <div style={{ display:'flex', gap:8 }}>
        <button className="tv-btn primary" onClick={add} disabled={saving}>{saving?'Saving…':'Add Position'}</button>
        <button className="tv-btn" onClick={() => setShowAdd(false)}>Cancel</button>
      </div>
    </div>}

    {loading ? <Spinner /> : staking.length === 0
      ? <div style={{ color:'var(--text4)', fontSize:13, padding:'12px 0' }}>No DeFi protocol positions. Add one above.</div>
      : <>
          {/* Protocol sub-nav */}
          {protocolNames.length > 1 && <div style={{ display:'flex', gap:6, flexWrap:'wrap', marginBottom:16, paddingBottom:10, borderBottom:'1px solid var(--line-soft)' }}>
            {protocolNames.map(name => {
              const proto = protocols[name];
              const isActive = name === activeProtocol;
              return <button key={name} className="tv-btn"
                style={{ fontSize:12, padding:'4px 12px', background:isActive?'var(--panel3)':'transparent', borderColor:isActive?'var(--accent-line)':'var(--line)', color:isActive?'var(--text)':'var(--text3)' }}
                onClick={() => setSelectedProtocol(name)}>
                {name}
                <span style={{ marginLeft:6, fontSize:10, color:'var(--text4)' }}>{mv(proto.total,hideValues)}</span>
              </button>;
            })}
          </div>}

          {/* Active protocol positions */}
          {activePositions.map(p => <StakingCard key={p.id} pos={p} hideValues={hideValues} onRefetch={load} />)}
        </>
    }
  </div>;
}

// ─── LP Positions tab ─────────────────────────────────────────────────────────

function LPPositionsTab({ portfolio, manualPositions, hideValues, onRefetchManual }) {
  const [removedKeys, setRemovedKeys] = useState(new Set());

  const zerionLPs = (portfolio?.lp_positions || []).map(p => normLP(p, 'zerion'));
  const manualLPs = (manualPositions || []).map(p => normLP(p, 'manual'));
  const allLPs = [...zerionLPs, ...manualLPs]
    .sort((a,b) => b.total_value_usd - a.total_value_usd);
  const visibleLPs = allLPs.filter(p => !removedKeys.has(p._key));

  const totalLP = visibleLPs.reduce((s,p) => s+p.total_value_usd, 0);
  const inRange = visibleLPs.filter(p => p.in_range === true).length;

  function removeLP(key) {
    setRemovedKeys(prev => { const n = new Set(prev); n.add(key); return n; });
  }

  return <div>
    {visibleLPs.length > 0 && <div style={{ display:'flex', gap:10, flexWrap:'wrap', marginBottom:16 }}>
      <SummaryCard label="Total LP Value" value={mv(totalLP,hideValues)} color="var(--accent)" />
      <SummaryCard label="In Range" value={`${inRange} / ${visibleLPs.filter(p=>p.in_range!=null).length}`} sub={`${visibleLPs.length} positions`} />
      <SummaryCard label="Uncollected Fees" value={mv(visibleLPs.reduce((s,p)=>s+p.fees_uncollected,0),hideValues)} color="var(--ok)" />
    </div>}

    <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12 }}>
      <div className="tv-label">LP Positions ({visibleLPs.length})</div>
      <button className="tv-btn primary" style={{ fontSize:12 }} onClick={() => { window._openAddLP && window._openAddLP(); }}>+ Add Manual LP</button>
    </div>

    {visibleLPs.length === 0
      ? <div className="tv-card" style={{ textAlign:'center', color:'var(--text4)', padding:32 }}>
          No LP positions.{' '}
          <button className="tv-btn primary" style={{ fontSize:12, marginLeft:8 }} onClick={() => { window._openAddLP && window._openAddLP(); }}>Add Manual LP</button>
        </div>
      : visibleLPs.map(pos => <LPCard key={pos._key} pos={pos} hideValues={hideValues} onRefetch={onRefetchManual} onRemove={() => removeLP(pos._key)} />)
    }
  </div>;
}

// ─── Borrow/Lend tab ──────────────────────────────────────────────────────────

function BorrowLendTab({ portfolio, hideValues, onRefetch }) {
  const [removedKeys, setRemovedKeys] = useState(new Set());

  const allLending = portfolio?.aave_positions || [];
  const lending = allLending.filter(p => {
    const key = `${p.chain_name}:${p.wallet}:${p.protocol_name||'aave'}`;
    return !removedKeys.has(key);
  });

  const netEquity = lending.reduce((s,p) => s+(p.total_collateral_usd||0)-(p.total_debt_usd||0), 0);
  const totalLent = lending.reduce((s,p) => s+(p.total_collateral_usd||0), 0);
  const totalBorrowed = lending.reduce((s,p) => s+(p.total_debt_usd||0), 0);
  const avgHF = lending.length ? lending.reduce((s,p) => s+(p.health_factor||0), 0) / lending.length : 0;

  function removeLending(key) {
    setRemovedKeys(prev => { const n = new Set(prev); n.add(key); return n; });
  }

  return <div>
    {lending.length > 0 && <div style={{ display:'flex', gap:10, flexWrap:'wrap', marginBottom:16 }}>
      <SummaryCard label="Net Equity" value={mv(netEquity,hideValues)} color="var(--ok)" />
      <SummaryCard label="Avg Health Factor" value={avgHF > 100 ? '∞' : fmtNum(avgHF,2)} color={avgHF > 2 ? 'var(--ok)' : avgHF > 1.5 ? 'var(--warn)' : 'var(--fail)'} />
      <SummaryCard label="Total Supplied" value={mv(totalLent,hideValues)} />
      <SummaryCard label="Total Borrowed" value={mv(totalBorrowed,hideValues)} color="var(--fail)" />
    </div>}

    {lending.length === 0
      ? <div className="tv-card" style={{ textAlign:'center', color:'var(--text4)', padding:32 }}>No lending positions found.</div>
      : lending.map((pos,i) => {
          const key = `${pos.chain_name}:${pos.wallet}:${pos.protocol_name||'aave'}`;
          return <LendingCard key={i} pos={pos} hideValues={hideValues} onRefetch={onRefetch} onRemove={() => removeLending(key)} />;
        })
    }
  </div>;
}

// ─── Token Holdings tab ───────────────────────────────────────────────────────

function TokenHoldings({ portfolio, wallets, hideValues, config }) {
  const [selectedWallets, setSelectedWallets] = useState(new Set());
  const [chainFilter, setChainFilter] = useState('all');
  const [groupMode, setGroupMode] = useState('type');
  const [showDust, setShowDust] = useState(false);
  const dustThreshold = config?.dust_threshold || 0.01;

  const allTokens = portfolio?.tokens || [];
  const allWallets = wallets || [];

  const filtered = useMemo(() => {
    return allTokens.filter(t => {
      if (selectedWallets.size > 0 && !selectedWallets.has(t.wallet)) return false;
      if (chainFilter !== 'all' && t.chain !== chainFilter) return false;
      return true;
    });
  }, [allTokens, selectedWallets, chainFilter]);

  const { visible, dustCount } = useMemo(() => {
    const vis = [], dust = [];
    filtered.forEach(t => (showDust || t.value_usd >= dustThreshold ? vis : dust).push(t));
    return { visible: vis, dustCount: dust.length };
  }, [filtered, showDust, dustThreshold]);

  const chains = useMemo(() => [...new Set(allTokens.map(t => t.chain))].sort(), [allTokens]);
  const totalVal = visible.reduce((s,t) => s+t.value_usd, 0);
  const lpVal = (portfolio?.lp_positions||[]).reduce((s,p) => s+(p.total_value_usd||0), 0);
  const defiVal = lpVal + (portfolio?.aave_positions||[]).reduce((s,p) => s+(p.total_collateral_usd||0), 0);

  function toggleWallet(addr) {
    setSelectedWallets(prev => { const n = new Set(prev); n.has(addr) ? n.delete(addr) : n.add(addr); return n; });
  }

  const grouped = useMemo(() => {
    if (groupMode === 'wallet') {
      const map = {};
      visible.forEach(t => {
        const k = t.wallet; if (!map[k]) map[k] = { label: t.wallet_label || t.wallet, tokens: [], total: 0 };
        map[k].tokens.push(t); map[k].total += t.value_usd;
      });
      return Object.values(map).sort((a,b) => b.total - a.total).map(g => ({ key:g.label, label:g.label, tokens:g.tokens.sort((a,b)=>b.value_usd-a.value_usd), total:g.total }));
    }
    const map = { ETH:[], BTC:[], Stablecoins:[], Yield:[], Other:[] };
    visible.forEach(t => { const g = tokenGroup(t.symbol); (map[g]||map.Other).push(t); });
    return Object.entries(map).filter(([,v])=>v.length>0)
      .map(([key,tokens]) => ({ key, label:key, tokens:tokens.sort((a,b)=>b.value_usd-a.value_usd), total:tokens.reduce((s,t)=>s+t.value_usd,0) }))
      .sort((a,b) => b.total - a.total);
  }, [visible, groupMode]);

  return <div>
    {/* Summary strip */}
    <div style={{ display:'flex', gap:10, flexWrap:'wrap', marginBottom:16 }}>
      <SummaryCard label="Total Value" value={mv(totalVal+(portfolio?.total_lp_value||0),hideValues)} color="var(--accent)" />
      <SummaryCard label="Token Holdings" value={visible.length} sub={`${chains.length} chains`} />
      <SummaryCard label="DeFi Value" value={mv(defiVal,hideValues)} />
    </div>

    {/* Wallet filter */}
    {allWallets.length > 1 && <div style={{ display:'flex', gap:6, flexWrap:'wrap', marginBottom:10 }}>
      <button className="tv-btn" style={{ fontSize:11, padding:'3px 10px', borderColor:selectedWallets.size===0?'var(--accent)':'var(--line)', background:selectedWallets.size===0?'var(--accent)':'transparent', color:selectedWallets.size===0?'var(--bg)':'var(--text3)' }}
        onClick={() => setSelectedWallets(new Set())}>All</button>
      {allWallets.map(w => <button key={w.address} className="tv-btn"
        style={{ fontSize:11, padding:'3px 10px', borderColor:selectedWallets.has(w.address)?'var(--accent)':'var(--line)', background:selectedWallets.has(w.address)?'var(--accent)':'transparent', color:selectedWallets.has(w.address)?'var(--bg)':'var(--text3)' }}
        onClick={() => toggleWallet(w.address)}>{w.label || w.address.slice(0,8)}</button>)}
    </div>}

    {/* Chain filter */}
    <div style={{ display:'flex', gap:6, flexWrap:'wrap', marginBottom:12 }}>
      {['all',...chains].map(c => <button key={c} className="tv-btn"
        style={{ fontSize:11, padding:'3px 10px', borderColor:chainFilter===c?'var(--accent)':'var(--line)', background:chainFilter===c?'var(--accent-soft)':'transparent', color:chainFilter===c?'var(--accent)':'var(--text3)' }}
        onClick={() => setChainFilter(c)}>{c === 'all' ? 'All Chains' : cap(c)}</button>)}
    </div>

    {/* Controls row */}
    <div style={{ display:'flex', gap:8, alignItems:'center', marginBottom:12 }}>
      <span className="tv-label">Group by:</span>
      <button className="tv-btn" style={{ fontSize:11, padding:'3px 10px', background:groupMode==='type'?'var(--panel3)':'transparent', borderColor:groupMode==='type'?'var(--accent-line)':'var(--line)' }}
        onClick={() => setGroupMode('type')}>By Type</button>
      <button className="tv-btn" style={{ fontSize:11, padding:'3px 10px', background:groupMode==='wallet'?'var(--panel3)':'transparent', borderColor:groupMode==='wallet'?'var(--accent-line)':'var(--line)' }}
        onClick={() => setGroupMode('wallet')}>By Wallet</button>
    </div>

    {/* Dust notice */}
    {dustCount > 0 && <div style={{ fontSize:12, color:'var(--text4)', marginBottom:8 }}>
      {dustCount} token{dustCount!==1?'s':''} hidden below {fmt(dustThreshold)}.{' '}
      <button style={{ background:'none', border:'none', color:'var(--accent)', cursor:'pointer', fontSize:12, padding:0 }} onClick={() => setShowDust(!showDust)}>
        {showDust ? 'Hide dust' : 'Show all'}
      </button>
    </div>}

    {/* Token table */}
    <div className="tv-card" style={{ padding:0, overflow:'hidden' }}>
      <table className="tv-table">
        <thead><tr>
          <th>Token</th><th>Chain</th><th className="num">Balance</th>
          <th className="num">Price</th><th className="num">Value</th><th>Wallet</th>
        </tr></thead>
        <tbody>
          {grouped.map(g => <>
            <tr key={g.key+'_hdr'} style={{ background:'var(--panel2)' }}>
              <td colSpan={6} style={{ padding:'6px 12px', fontWeight:700, color:'var(--accent)', fontSize:12 }}>
                {g.label}
                <span style={{ float:'right', color:'var(--text3)', fontWeight:400 }} className="tv-num">{mv(g.total,hideValues)}</span>
              </td>
            </tr>
            {g.tokens.map((t,i) => <tr key={t.wallet+t.symbol+t.chain+i}>
              <td style={{ display:'flex', alignItems:'center', gap:8 }}>
                <TokenAvatar symbol={t.symbol} size={20} />
                <span style={{ fontWeight:600, color:'var(--text)' }}>{t.symbol}</span>
              </td>
              <td><ChainBadge chain={t.chain} /></td>
              <td className="num">{mvn(t.balance,4,hideValues)}</td>
              <td className="num">{t.price_usd > 0 ? mv(t.price_usd,hideValues) : '—'}</td>
              <td className="num" style={{ color:'var(--text)', fontWeight:600 }}>{t.value_usd > 0 ? mv(t.value_usd,hideValues) : '—'}</td>
              <td><WalletBadge label={t.wallet_label} /></td>
            </tr>)}
          </>)}
          {grouped.length === 0 && <tr><td colSpan={6} style={{ textAlign:'center', color:'var(--text4)', padding:20 }}>No tokens found.</td></tr>}
        </tbody>
      </table>
    </div>
  </div>;
}

// ─── LP Tools ─────────────────────────────────────────────────────────────────

function LPOptimizer() {
  const [form, setForm] = useState({ chain:'', symbol:'', min_tvl:'500000' });
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [err, setErr] = useState('');

  async function search() {
    setLoading(true); setErr(''); setResults(null);
    try {
      const body = { min_tvl: parseFloat(form.min_tvl)||500000 };
      if (form.chain) body.chain = form.chain;
      if (form.symbol) body.symbol = form.symbol.trim().toUpperCase();
      const d = await api('/api/optimizer/pools', { method:'POST', body:JSON.stringify(body) });
      setResults(d.pools || d || []);
    } catch(e) { setErr(String(e)); } finally { setLoading(false); }
  }

  return <div>
    <div className="tv-label" style={{ marginBottom:12 }}>LP Optimizer</div>
    <div style={{ display:'flex', gap:10, flexWrap:'wrap', marginBottom:16 }}>
      <Field label="Chain">
        <select className="tv-select" value={form.chain} onChange={e => setForm({...form,chain:e.target.value})}>
          <option value="">All Chains</option>
          {LP_CHAINS.map(c => <option key={c} value={c}>{cap(c)}</option>)}
        </select>
      </Field>
      <Field label="Symbol / Pair (optional)">
        <input className="tv-input" placeholder="e.g. ETH" value={form.symbol} onChange={e => setForm({...form,symbol:e.target.value})} style={{ width:140 }} />
      </Field>
      <Field label="Min TVL ($)">
        <input className="tv-input" type="number" value={form.min_tvl} onChange={e => setForm({...form,min_tvl:e.target.value})} style={{ width:120 }} />
      </Field>
      <div style={{ display:'flex', alignItems:'flex-end' }}>
        <button className="tv-btn primary" onClick={search} disabled={loading}>{loading ? 'Searching…' : 'Search Pools'}</button>
      </div>
    </div>
    {err && <div style={{ color:'var(--fail)', fontSize:12, marginBottom:10 }}>{err}</div>}
    {results && <div className="tv-card" style={{ padding:0, overflow:'hidden' }}>
      <table className="tv-table">
        <thead><tr><th>Pool</th><th>Chain</th><th className="num">TVL</th><th className="num">24h Vol</th><th className="num">Fee APR</th><th>Fee Tier</th></tr></thead>
        <tbody>{results.length === 0
          ? <tr><td colSpan={6} style={{ textAlign:'center', color:'var(--text4)', padding:20 }}>No pools found.</td></tr>
          : results.map((p,i) => <tr key={i}>
              <td style={{ fontWeight:600 }}>{p.symbol || p.name || `${p.token0}/${p.token1}`}</td>
              <td><ChainBadge chain={p.chain} /></td>
              <td className="num">{fmt(p.tvl_usd||p.tvl||0)}</td>
              <td className="num">{fmt(p.volume_24h_usd||p.volume_24h||0)}</td>
              <td className="num ok">{fmtNum(p.fee_apr||0,2)}%</td>
              <td>{p.fee_tier ? fmtNum(p.fee_tier,3)+'%' : '—'}</td>
            </tr>)}
        </tbody>
      </table>
    </div>}
  </div>;
}

function ILCalculator() {
  const [form, setForm] = useState({ pair:'ETH/USDC', pLow:'', pHigh:'', pEntry:'', notional:'10000', feeApr:'30' });
  const [result, setResult] = useState(null);

  function calc() {
    const pLow=parseFloat(form.pLow), pHigh=parseFloat(form.pHigh), pEntry=parseFloat(form.pEntry);
    const notional=parseFloat(form.notional), feeApr=parseFloat(form.feeApr);
    if ([pLow,pHigh,pEntry,notional,feeApr].some(isNaN)||pLow>=pHigh||pEntry<=0) return;
    const sp=Math.sqrt(pEntry), sl=Math.sqrt(pLow), sh=Math.sqrt(pHigh);
    const denom = 2*sp - pEntry/sh - sl;
    if (denom <= 0) return;
    const L = notional / denom;
    function nvCalc(P) {
      if (P <= pLow) return L*(1/sl-1/sh)*P;
      if (P >= pHigh) return L*(sh-sl);
      return L*(Math.sqrt(P)-sl) + L*(1/Math.sqrt(P)-1/sh)*P;
    }
    const x0=L*(1/sp-1/sh), y0=L*(sp-sl);
    function hodl(P) { return x0*P + y0; }
    const range=pHigh-pLow, pad=range*0.15, lo=pLow-pad, hi=pHigh+pad;
    const N=100, prices=[], lpVals=[], hodlVals=[], ilPcts=[];
    for(let i=0;i<N;i++){const P=lo+(hi-lo)*i/(N-1);prices.push(P);const v=nvCalc(P),h=hodl(P);lpVals.push(v);hodlVals.push(h);ilPcts.push((v-h)/h*100);}
    const vLow=nvCalc(pLow), vEntry=nvCalc(pEntry), vHigh=nvCalc(pHigh);
    const hLow=hodl(pLow), hHigh=hodl(pHigh);
    const ilLow=vLow-hLow, ilHigh=vHigh-hHigh;
    const dailyFees=notional*(feeApr/100)/365;
    const beWorst=Math.ceil(Math.max(Math.abs(ilLow),Math.abs(ilHigh))/dailyFees);
    setResult({ prices, lpVals, hodlVals, ilPcts, vLow, vEntry, vHigh, hLow, hHigh, ilLow, ilHigh, ilPctLow:ilLow/hLow*100, ilPctHigh:ilHigh/hHigh*100, dailyFees, beWorst, pLow, pHigh, pEntry, notional, feeApr });
  }

  const parts = form.pair.split('/');
  const base = parts[0]||'Token0', quote = parts[1]||'Token1';

  return <div>
    <div className="tv-label" style={{ marginBottom:12 }}>IL Calculator — Concentrated Liquidity V3</div>
    <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(160px,1fr))', gap:10, marginBottom:12 }}>
      {[{l:'Pair',k:'pair',t:'text',ph:'ETH/USDC'},{l:'Range Low',k:'pLow',t:'number'},{l:'Range High',k:'pHigh',t:'number'},
        {l:'Entry Price',k:'pEntry',t:'number'},{l:'Notional USD',k:'notional',t:'number'},{l:'Fee APR %',k:'feeApr',t:'number'}]
        .map(f => <Field key={f.k} label={f.l}>
          <input className="tv-input" type={f.t} placeholder={f.ph||''} value={form[f.k]} onChange={e => setForm({...form,[f.k]:e.target.value})} />
        </Field>)}
    </div>
    <button className="tv-btn primary" style={{ marginBottom:16 }} onClick={calc}>Calculate</button>

    {result && <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
      <div>
        <div className="tv-label" style={{ marginBottom:8 }}>LP Value vs 50/50 HODL</div>
        <div style={{ background:'var(--panel2)', borderRadius:8, padding:8, overflow:'hidden' }}>
          <svg width="100%" viewBox={`0 0 400 160`} style={{ display:'block' }}>
            {(() => {
              const vals=[...result.lpVals,...result.hodlVals];
              const mn=Math.min(...vals), mx=Math.max(...vals), rng=mx-mn||1;
              const pad=12, W=400, H=160, w=W-pad*2, h=H-pad*2;
              const x=i=>pad+(i/(result.prices.length-1))*w;
              const y=v=>pad+((mx-v)/rng)*h;
              const lp=result.lpVals.map((v,i)=>`${x(i)},${y(v)}`).join(' ');
              const hd=result.hodlVals.map((v,i)=>`${x(i)},${y(v)}`).join(' ');
              return <>
                <polyline points={lp} fill="none" stroke="var(--adapt)" strokeWidth="2" />
                <polyline points={hd} fill="none" stroke="var(--ok)" strokeWidth="1.5" strokeDasharray="6,3" />
                <line x1={x(result.prices.findIndex(p=>p>=result.pLow))} y1={pad} x2={x(result.prices.findIndex(p=>p>=result.pLow))} y2={H-pad} stroke="var(--fail)" strokeWidth="1" strokeDasharray="4,3" opacity="0.5" />
                <line x1={x(result.prices.findIndex(p=>p>=result.pHigh))} y1={pad} x2={x(result.prices.findIndex(p=>p>=result.pHigh))} y2={H-pad} stroke="var(--fail)" strokeWidth="1" strokeDasharray="4,3" opacity="0.5" />
              </>;
            })()}
          </svg>
          <div style={{ display:'flex', gap:12, fontSize:10, color:'var(--text4)', paddingLeft:12 }}>
            <span style={{ color:'var(--adapt)' }}>— LP</span>
            <span style={{ color:'var(--ok)' }}>- - HODL</span>
          </div>
        </div>

        <div className="tv-label" style={{ marginBottom:8, marginTop:12 }}>IL vs HODL (%)</div>
        <div style={{ background:'var(--panel2)', borderRadius:8, padding:8, overflow:'hidden' }}>
          <svg width="100%" viewBox="0 0 400 120" style={{ display:'block' }}>
            {(() => {
              const vals=result.ilPcts, mn=Math.min(...vals,0), mx=Math.max(...vals,0), rng=mx-mn||1;
              const pad=8, W=400, H=120, w=W-pad*2, h=H-pad*2;
              const x=i=>pad+(i/(result.prices.length-1))*w;
              const y=v=>pad+((mx-v)/rng)*h;
              const pts=vals.map((v,i)=>`${x(i)},${y(v)}`).join(' ');
              const zeroY=y(0);
              return <>
                <line x1={pad} y1={zeroY} x2={W-pad} y2={zeroY} stroke="var(--line)" strokeWidth="1" />
                <polyline points={pts} fill="none" stroke="var(--fail)" strokeWidth="2" />
              </>;
            })()}
          </svg>
        </div>
      </div>

      <div style={{ display:'flex', flexDirection:'column', gap:8, fontSize:12 }}>
        <div className="tv-card-2">
          <div className="tv-label" style={{ marginBottom:8 }}>Position Summary</div>
          {[{l:`Range`,v:`${result.pLow} – ${result.pHigh} ${quote}`},
            {l:'Range Width',v:fmtNum((result.pHigh-result.pLow)/result.pEntry*100,1)+'%'},
            {l:'Notional',v:fmt(result.notional),c:'var(--accent)'},
            {l:`At Range Low (100% ${base})`,v:`${fmt(result.vLow)} (${fmtNum(result.ilPctLow,1)}% IL)`,c:'var(--fail)'},
            {l:`At Range High (100% ${quote})`,v:`${fmt(result.vHigh)} (${fmtNum(result.ilPctHigh,1)}% IL)`,c:'var(--fail)'},
          ].map(r => <div key={r.l} style={{ display:'flex', justifyContent:'space-between', padding:'3px 0', borderBottom:'1px solid var(--line-soft)' }}>
            <span style={{ color:'var(--text4)' }}>{r.l}</span>
            <span className="tv-num" style={{ color:r.c||'var(--text2)' }}>{r.v}</span>
          </div>)}
        </div>
        <div className="tv-card-2">
          <div className="tv-label" style={{ marginBottom:8 }}>Fee Income</div>
          {[{l:'Daily',v:fmt(result.dailyFees)},{l:'Monthly',v:fmt(result.dailyFees*30)},{l:'Yearly',v:fmt(result.dailyFees*365)}]
            .map(r => <div key={r.l} style={{ display:'flex', justifyContent:'space-between', padding:'3px 0', borderBottom:'1px solid var(--line-soft)' }}>
              <span style={{ color:'var(--text4)' }}>{r.l}</span><span className="tv-num ok">{r.v}</span>
            </div>)}
        </div>
        <div className="tv-card-2" style={{ textAlign:'center', padding:16 }}>
          <div className="tv-label" style={{ marginBottom:4 }}>Break-Even</div>
          <div className="tv-num" style={{ fontSize:24, fontWeight:700, color:'var(--accent)' }}>~{result.beWorst} days</div>
          <div style={{ fontSize:11, color:'var(--text4)' }}>to offset worst-case IL</div>
        </div>
      </div>
    </div>}
  </div>;
}

function HedgeCalculator() {
  const [lev, setLev] = useState(2);
  const [form, setForm] = useState({ pair:'ETH/USDC', pLow:'', pHigh:'', pEntry:'', notional:'10000', feeApr:'30', hedgePct:'50', fundingApr:'30', hedgeEntry:'' });
  const [result, setResult] = useState(null);

  function calc() {
    const pLow=parseFloat(form.pLow), pHigh=parseFloat(form.pHigh), pEntry=parseFloat(form.pEntry);
    const notional=parseFloat(form.notional), feeApr=parseFloat(form.feeApr);
    const hedgePct=parseFloat(form.hedgePct)/100, fundingApr=parseFloat(form.fundingApr);
    const hEntry=parseFloat(form.hedgeEntry)||pEntry;
    if ([pLow,pHigh,pEntry,notional,feeApr,fundingApr].some(isNaN)||pLow>=pHigh) return;
    const sp=Math.sqrt(pEntry), sl=Math.sqrt(pLow), sh=Math.sqrt(pHigh);
    const L=notional/(2*sp-pEntry/sh-sl);
    function lpVal(P){ if(P<=pLow)return L*(1/sl-1/sh)*P; if(P>=pHigh)return L*(sh-sl); return L*(Math.sqrt(P)-sl)+L*(1/Math.sqrt(P)-1/sh)*P; }
    const hedgeNotional=notional*hedgePct, shortSize=hedgeNotional/hEntry;
    const margin=hedgeNotional/lev, liqPrice=hEntry+margin/shortSize;
    const dailyFees=notional*(feeApr/100)/365, dailyFunding=hedgeNotional*(fundingApr/100)/365;
    const points=[
      {label:`+15%`,price:pEntry*1.15},{label:`Upper (${fmtNum((pHigh/pEntry-1)*100,0)}%)`,price:pHigh},
      {label:`Entry`,price:pEntry},{label:`Lower (${fmtNum((pLow/pEntry-1)*100,0)}%)`,price:pLow},{label:`-15%`,price:pEntry*0.85},
    ].map(pt => {
      const lpPnl=lpVal(pt.price)-notional;
      const hedgePnl=shortSize*(hEntry-pt.price);
      return {...pt, lpPnl, hedgePnl, netPnl:lpPnl+hedgePnl};
    });
    setResult({ points, liqPrice, margin, shortSize, hedgeNotional, dailyFunding });
  }

  return <div>
    <div className="tv-label" style={{ marginBottom:12 }}>Hedge Calculator</div>
    <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(150px,1fr))', gap:10, marginBottom:10 }}>
      {[{l:'Pair',k:'pair',t:'text'},{l:'Range Low',k:'pLow',t:'number'},{l:'Range High',k:'pHigh',t:'number'},
        {l:'Entry Price',k:'pEntry',t:'number'},{l:'Notional USD',k:'notional',t:'number'},{l:'Fee APR %',k:'feeApr',t:'number'},
        {l:'Hedge % of Notional',k:'hedgePct',t:'number'},{l:'Funding APR %',k:'fundingApr',t:'number'},{l:'Hedge Entry (blank=LP)',k:'hedgeEntry',t:'number'}]
        .map(f => <Field key={f.k} label={f.l}>
          <input className="tv-input" type={f.t} value={form[f.k]} onChange={e => setForm({...form,[f.k]:e.target.value})} />
        </Field>)}
    </div>
    <div style={{ display:'flex', gap:6, marginBottom:12, alignItems:'center' }}>
      <span className="tv-label">Leverage:</span>
      {[1,2,3,5,10].map(l => <button key={l} className="tv-btn"
        style={{ fontSize:12, padding:'3px 10px', background:lev===l?'var(--accent)':'transparent', borderColor:lev===l?'var(--accent)':'var(--line)', color:lev===l?'var(--bg)':'var(--text3)' }}
        onClick={() => { setLev(l); }}>{l}x</button>)}
    </div>
    <button className="tv-btn primary" style={{ marginBottom:16 }} onClick={calc}>Calculate</button>

    {result && <>
      <div style={{ display:'flex', gap:10, flexWrap:'wrap', marginBottom:12 }}>
        <SummaryCard label="Liquidation Price" value={fmtNum(result.liqPrice,2)} color="var(--fail)" />
        <SummaryCard label="Hedge Notional" value={fmt(result.hedgeNotional)} />
        <SummaryCard label="Daily Funding Cost" value={fmt(result.dailyFunding)} color="var(--warn)" />
      </div>
      <div className="tv-card" style={{ padding:0, overflow:'hidden' }}>
        <table className="tv-table">
          <thead><tr><th>Scenario</th><th>Price</th><th className="num">LP P&L</th><th className="num">Hedge P&L</th><th className="num">Net P&L</th></tr></thead>
          <tbody>{result.points.map((p,i) => <tr key={i}>
            <td style={{ color:'var(--text4)' }}>{p.label}</td>
            <td className="num tv-num">{fmtNum(p.price,2)}</td>
            <td className={`num tv-num ${p.lpPnl>=0?'ok':'fail'}`}>{p.lpPnl>=0?'+':''}{fmt(p.lpPnl)}</td>
            <td className={`num tv-num ${p.hedgePnl>=0?'ok':'fail'}`}>{p.hedgePnl>=0?'+':''}{fmt(p.hedgePnl)}</td>
            <td className={`num tv-num ${p.netPnl>=0?'ok':'fail'}`} style={{ fontWeight:700 }}>{p.netPnl>=0?'+':''}{fmt(p.netPnl)}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </>}
  </div>;
}

function LPTools() {
  const [tool, setTool] = useState('optimizer');
  return <div>
    <SegTabs tabs={[{id:'optimizer',label:'LP Optimizer'},{id:'il',label:'IL Calculator'},{id:'hedge',label:'Hedge Calculator'}]} active={tool} onChange={setTool} />
    {tool === 'optimizer' && <LPOptimizer />}
    {tool === 'il' && <ILCalculator />}
    {tool === 'hedge' && <HedgeCalculator />}
  </div>;
}

// ─── Portfolio Screen root ─────────────────────────────────────────────────────

function PortfolioScreen({ hideValues, portfolioSubTab, refreshTrigger }) {
  const [portfolio, setPortfolio] = useState(null);
  const [wallets, setWallets] = useState([]);
  const [manualPositions, setManualPositions] = useState([]);
  const [config, setConfig] = useState({});
  const [loading, setLoading] = useState(true);
  const [showAddLP, setShowAddLP] = useState(false);

  window._openAddLP = () => setShowAddLP(true);

  const loadManual = useCallback(() => {
    api('/api/manual-positions').then(d => setManualPositions(Array.isArray(d) ? d : (d.positions||[]))).catch(() => {});
  }, []);

  const loadPortfolio = useCallback(() => {
    setLoading(true);
    Promise.all([
      api('/api/portfolio'),
      api('/api/wallets'),
      api('/api/config'),
    ]).then(([pf, wl, cfg]) => {
      setPortfolio(pf);
      setWallets(wl.wallets || []);
      setConfig(cfg || {});
    }).catch(() => {}).finally(() => setLoading(false));
    loadManual();
  }, [loadManual]);

  useEffect(() => { loadPortfolio(); }, [refreshTrigger]);

  const activeTab = portfolioSubTab || 'tokens';

  if (loading) return <Spinner />;

  function renderSpotTab() {
    const SpotScreen = window.SpotPnlScreen;
    return SpotScreen ? <SpotScreen hideValues={hideValues} refreshTrigger={refreshTrigger} /> : <div style={{ color:'var(--text4)', padding:20 }}>Loading Spot P&L…</div>;
  }

  return <div>
    {activeTab === 'spot' && renderSpotTab()}
    {activeTab === 'tokens' && <TokenHoldings portfolio={portfolio} wallets={wallets} hideValues={hideValues} config={config} />}
    {activeTab === 'lp' && <LPPositionsTab portfolio={portfolio} manualPositions={manualPositions} hideValues={hideValues} onRefetchManual={loadManual} />}
    {activeTab === 'lptools' && <LPTools />}
    {activeTab === 'borrow' && <BorrowLendTab portfolio={portfolio} hideValues={hideValues} onRefetch={loadPortfolio} />}
    {activeTab === 'protocols' && <ProtocolsTab hideValues={hideValues} />}
    {showAddLP && <LPEditModal pos={null} onClose={() => setShowAddLP(false)} onSaved={() => { setShowAddLP(false); loadManual(); }} />}
  </div>;
}

window.PortfolioScreen = PortfolioScreen;
