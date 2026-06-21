// marketdata.jsx — Market Data tab
// Reuses TV.*, .tv-*, PF_CARD/TITLE/SUB/METRIC, TokenIcon, ChainBadge (global).

// ─── Fear & Greed gauge ───────────────────────────────────────
const FearGreedGauge = ({value = 23}) => {
  const W = 200, H = 110, cx = W / 2, cy = H - 8, r = 82;
  const toAngle = v => Math.PI - (v / 100) * Math.PI;
  const pt = a => [cx + r * Math.cos(a), cy - r * Math.sin(a)];
  const arc = (s, e, stroke) => {
    const [x1,y1] = pt(toAngle(s)), [x2,y2] = pt(toAngle(e));
    const lg = (e - s) > 50 ? 1 : 0;
    return `M${x1.toFixed(1)} ${y1.toFixed(1)} A${r} ${r} 0 ${lg} 0 ${x2.toFixed(1)} ${y2.toFixed(1)}`;
  };
  const [nx, ny] = pt(toAngle(value));
  const col = value < 25 ? TV.fail : value < 45 ? '#f97316' : value < 55 ? TV.warn : value < 75 ? '#9be848' : TV.ok;
  const lbl = value < 25 ? 'Extreme Fear' : value < 45 ? 'Fear' : value < 55 ? 'Neutral' : value < 75 ? 'Greed' : 'Extreme Greed';
  const zones = [[0,25,TV.fail],[25,45,'#f97316'],[45,55,TV.warn],[55,75,'#9be848'],[75,100,TV.ok]];
  return (
    <div style={{display:'flex', flexDirection:'column', alignItems:'center', gap:2}}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H}>
        <path d={arc(0,100)} fill="none" stroke={TV.panel3} strokeWidth="14"/>
        {zones.map(([s,e,c]) => <path key={s} d={arc(s,e)} fill="none" stroke={c} strokeWidth="12" strokeLinecap="butt"/>)}
        <line x1={cx} y1={cy} x2={nx.toFixed(1)} y2={ny.toFixed(1)} stroke={TV.text} strokeWidth="2.5" strokeLinecap="round"/>
        <circle cx={cx} cy={cy} r="5" fill={TV.text}/>
        <text x={cx-r-2} y={cy+14} fontSize="9" fill={TV.text4} textAnchor="middle" fontFamily={TV.font}>0</text>
        <text x={cx+r+2} y={cy+14} fontSize="9" fill={TV.text4} textAnchor="middle" fontFamily={TV.font}>100</text>
      </svg>
      <div className="tv-num" style={{fontSize:16, fontWeight:700, color:col}}>{value} — {lbl}</div>
    </div>
  );
};

// ─── schematic chart helper ───────────────────────────────────
const MDLine = ({pts, minV, maxV, W, H, pL, pR, pT, pB, color, width=1.5, dash, fillColor}) => {
  const iW = W-pL-pR, iH = H-pT-pB, rng = maxV-minV||1;
  const mapped = pts.map((v,i) => [pL+(i/(pts.length-1))*iW, pT+iH-((v-minV)/rng)*iH]);
  const poly = mapped.map(([x,y])=>`${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const fillPath = fillColor
    ? `M${mapped[0][0].toFixed(1)} ${mapped[0][1].toFixed(1)} ${mapped.slice(1).map(([x,y])=>`L${x.toFixed(1)} ${y.toFixed(1)}`).join(' ')} L${mapped[mapped.length-1][0].toFixed(1)} ${pT+iH} L${pL} ${pT+iH} Z`
    : null;
  return (
    <g>
      {fillPath && <path d={fillPath} fill={fillColor} opacity="0.22"/>}
      <polyline points={poly} fill="none" stroke={color} strokeWidth={width}
          strokeLinejoin="round" strokeLinecap="round" strokeDasharray={dash||null}/>
    </g>
  );
};

const MDGrid = ({W, H, pL, pR, pT, pB, minV, maxV, count, fmt}) => {
  const iH = H-pT-pB, rng = maxV-minV||1;
  return Array.from({length:count+1}, (_,i) => {
    const v = minV + (rng/count)*i;
    const y = pT + iH - ((v-minV)/rng)*iH;
    return (
      <g key={i}>
        <line x1={pL} x2={W-pR} y1={y} y2={y} stroke={TV.lineSoft} strokeWidth="1"/>
        <text x={pL-3} y={y+3} fontSize="8.5" fill={TV.text4} textAnchor="end" fontFamily={TV.font}>{fmt(v)}</text>
      </g>
    );
  });
};

// ─── BTC Macro cycle data ─────────────────────────────────────
const BTC_PTS  = [20,28,38,52,65,46,32,26,18,24,31,42,56,72,98,126,108,80,64,73.8].map(v=>v*1000);
const MA200W   = [20,22,24.5,28,32,35,36,37,37.5,38.5,40,42,44,47,51,55,57,57.8,58.2,58.5].map(v=>v*1000);
const NUPL_PTS = [0.50,0.55,0.65,0.72,0.65,0.44,0.20,0.10,0.04,0.15,0.25,0.36,0.50,0.63,0.71,0.73,0.60,0.40,0.22,0.15];
const YEAR_LBL = ['\'21','','\'22','','\'22','','\'23','','\'23','','\'24','','\'24','','\'25','','\'25','','\'26','now'];

const BTCCycleCharts = () => {
  const W1=580, W2=380, H=220, pL=46, pR=10, pT=10, pB=28;
  const nupl_zones = [[0,0.25,TV.fail],[0.25,0.5,'#f97316'],[0.5,0.75,TV.warn],[0.75,1,TV.ok]];
  const iH = H-pT-pB;
  return (
    <div style={{display:'grid', gridTemplateColumns:'1.5fr 1fr', gap:16}}>
      {/* BTC price vs 200WMA */}
      <div>
        <div className="tv-uppercase" style={{marginBottom:6}}>BTC Weekly Price vs 200-Week MA</div>
        <div style={{display:'flex', gap:14, marginBottom:6}}>
          <span style={{display:'inline-flex',alignItems:'center',gap:5,fontSize:11,color:TV.text3}}>
            <svg width="18" height="8"><line x1="0" y1="4" x2="18" y2="4" stroke={TV.warn} strokeWidth="2"/></svg>BTC Price
          </span>
          <span style={{display:'inline-flex',alignItems:'center',gap:5,fontSize:11,color:TV.text3}}>
            <svg width="18" height="8"><line x1="0" y1="4" x2="18" y2="4" stroke="#a78bfa" strokeWidth="1.5" strokeDasharray="4 3"/></svg>200WMA
          </span>
        </div>
        <svg viewBox={`0 0 ${W1} ${H}`} width="100%" height={H} style={{display:'block'}}>
          <MDGrid W={W1} H={H} pL={pL} pR={pR} pT={pT} pB={pB} minV={0} maxV={130000} count={5}
              fmt={v=>v>=1000?`$${(v/1000).toFixed(0)}k`:'$0'}/>
          <MDLine pts={MA200W} minV={0} maxV={130000} W={W1} H={H} pL={pL} pR={pR} pT={pT} pB={pB}
              color="#a78bfa" width="1.5" dash="5 4"/>
          <MDLine pts={BTC_PTS} minV={0} maxV={130000} W={W1} H={H} pL={pL} pR={pR} pT={pT} pB={pB}
              color={TV.warn} width="2" fillColor={TV.warn}/>
          {YEAR_LBL.map((l,i) => l ? (
            <text key={i} x={pL+(i/(BTC_PTS.length-1))*(W1-pL-pR)} y={H-6} fontSize="8.5" fill={TV.text4}
                textAnchor="middle" fontFamily={TV.font}>{l}</text>
          ) : null)}
        </svg>
      </div>
      {/* NUPL */}
      <div>
        <div className="tv-uppercase" style={{marginBottom:6}}>NUPL — Net Unrealized P/L</div>
        <svg viewBox={`0 0 ${W2} ${H}`} width="100%" height={H} style={{display:'block'}}>
          {/* zone bands */}
          {nupl_zones.map(([lo,hi,c])=>{
            const y1=pT+iH-((hi-0)/(1-0))*iH, y2=pT+iH-((lo-0)/(1-0))*iH;
            return <rect key={lo} x={pL} y={y1} width={W2-pL-pR} height={y2-y1} fill={c} fillOpacity="0.12"/>;
          })}
          <MDGrid W={W2} H={H} pL={pL} pR={pR} pT={pT} pB={pB} minV={0} maxV={1} count={4}
              fmt={v=>v.toFixed(2)}/>
          {/* zero line */}
          <line x1={pL} x2={W2-pR} y1={pT+iH} y2={pT+iH} stroke={TV.lineSoft} strokeWidth="1"/>
          <MDLine pts={NUPL_PTS} minV={0} maxV={1} W={W2} H={H} pL={pL} pR={pR} pT={pT} pB={pB}
              color={TV.warn} width="2"/>
        </svg>
        {/* zone labels */}
        <div style={{display:'flex', gap:4, marginTop:6, flexWrap:'wrap'}}>
          {[['CAPITULATION','<0',TV.fail],['FEAR','0–0.25','#f97316'],['HOPE','0.25–0.5',TV.warn],['BELIEF','0.5–0.75','#9be848'],['EUPHORIA','>0.75',TV.ok]].map(([z,r,c])=>(
            <div key={z} style={{padding:'3px 7px', borderRadius:4, background:`${c}20`, border:`1px solid ${c}55`,
                fontSize:9.5, color:c, textAlign:'center'}}>
              <div style={{fontWeight:700}}>{z}</div>
              <div>{r}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// ─── section components ───────────────────────────────────────
const StatRow = ({label, value, valueColor}) => (
  <div style={{display:'flex', justifyContent:'space-between', alignItems:'baseline', padding:'4px 0',
      borderBottom:`1px solid ${TV.lineSoft}`, fontSize:13}}>
    <span style={{color:TV.text3}}>{label}</span>
    <span className="tv-num" style={{color:valueColor||TV.text, fontWeight:500}}>{value}</span>
  </div>
);

const PriceCard = ({sym, icon, price, change, changeUp, rows}) => (
  <div style={PF_CARD}>
    <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:6}}>
      <span style={{fontSize:16}}>{icon}</span>
      <div style={{fontSize:15, fontWeight:700, color:TV.accent}}>{sym}</div>
    </div>
    <div className="tv-num" style={{fontSize:26, fontWeight:700, color:TV.text, letterSpacing:'-.4px'}}>{price}</div>
    <div className="tv-num" style={{fontSize:13, color:changeUp?TV.ok:TV.fail, marginBottom:10}}>{change}</div>
    {rows.map(([l,v,vc])=><StatRow key={l} label={l} value={v} valueColor={vc}/>)}
  </div>
);

const MacroCycleSection = () => (
  <div style={{display:'flex', flexDirection:'column', gap:16}}>
    {/* Zone banner */}
    <div style={{padding:20, borderRadius:12, border:`2px solid ${TV.adapt}`,
        background:TV.panel, display:'grid', gridTemplateColumns:'1fr auto', gap:20, alignItems:'start'}}>
      <div>
        <div className="tv-uppercase" style={{color:TV.text3, marginBottom:4}}>Current Cycle Zone</div>
        <div style={{fontSize:28, fontWeight:800, color:TV.adapt, letterSpacing:'-.5px'}}>Value Window</div>
        <div style={{fontSize:12.5, fontWeight:700, color:TV.text, marginTop:4, marginBottom:8}}>Discounted entry in an uptrend.</div>
        <div style={{fontSize:12.5, color:TV.text3, lineHeight:1.6, maxWidth:600}}>
          Price is mid-cycle above the 200WMA floor, but market psychology is reading Fear or Capitulation —
          the crowd is behaving like a bear market when it is not. This divergence has historically marked
          strong mid-cycle accumulation opportunities. Suggested stance: increase buys above your DCA baseline.
        </div>
      </div>
      <div style={{minWidth:260}}>
        <div className="tv-uppercase" style={{marginBottom:10}}>Active Conditions</div>
        {['Multiple 1.15–2.0x (mid-cycle, above floor)', 'NUPL ≤ 0.25 (Fear / Capitulation despite price)'].map(c=>(
          <div key={c} style={{display:'flex', alignItems:'flex-start', gap:8, marginBottom:8, fontSize:12.5, color:TV.text2}}>
            <span style={{color:TV.ok, marginTop:1}}>✓</span>{c}
          </div>
        ))}
      </div>
    </div>
    {/* KPI strip */}
    <div style={{display:'grid', gridTemplateColumns:'repeat(6,1fr)', gap:12}}>
      {[
        ['BTC Price','$73,773','via Coinbase',TV.text],
        ['200-Week MA','$58,525','Long-term floor',TV.text],
        ['Distance to 200WMA','+26.1%','Above 200WMA',TV.ok],
        ['200WMA Multiple','1.26x','Price ÷ 200WMA',TV.text],
        ['NUPL','0.150','FEAR',TV.warn],
        ['Realized Price','$54,703','+34.0% in profit',TV.ok],
      ].map(([lbl,val,sub,col])=>(
        <div key={lbl} style={{...PF_METRIC, padding:14, display:'flex', flexDirection:'column', gap:4}}>
          <div style={{fontSize:10.5, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em'}}>{lbl}</div>
          <div className="tv-num" style={{fontSize:17, fontWeight:700, color:col, letterSpacing:'-.2px'}}>{val}</div>
          <div style={{fontSize:11, color:TV.text3}}>{sub}</div>
        </div>
      ))}
    </div>
    {/* charts */}
    <div style={PF_CARD}><BTCCycleCharts/></div>
    {/* bottom row: zone map + alert log + manual entry */}
    <div style={{display:'grid', gridTemplateColumns:'1.1fr 1fr 1fr', gap:16}}>
      {/* zone map */}
      <div style={PF_CARD}>
        <div style={{...PF_TITLE, marginBottom:12}}>Zone Map</div>
        <div style={{display:'flex', flexDirection:'column', gap:8}}>
          {[['Accumulation',TV.ok,'Multiple ≤1.15 · NUPL ≤0.25'],['Value Window',TV.adapt,'Multiple 1.15–2 · NUPL ≤0.25','CURRENT'],
            ['Neutral',TV.text2,'Multiple 1.15–2 · NUPL 0.25–0.75'],['Caution',TV.warn,'Multiple 2–3 · NUPL ≥0.6'],
            ['Euphoria',TV.fail,'Multiple ≥3 · NUPL ≥0.75']].map(([z,c,r,cur])=>(
            <div key={z} style={{padding:'9px 11px', borderRadius:8,
                border:`1px solid ${cur?c:TV.lineSoft}`, background:cur?`${c}14`:'transparent'}}>
              <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:2}}>
                <span style={{fontSize:13, fontWeight:700, color:c}}>{z}</span>
                {cur&&<span className="tv-chip" style={{fontSize:9.5, color:c, borderColor:`${c}55`, background:`${c}20`}}>CURRENT</span>}
              </div>
              <div style={{fontSize:11, color:TV.text3}}>{r}</div>
            </div>
          ))}
        </div>
      </div>
      {/* alert log */}
      <div style={PF_CARD}>
        <div style={{...PF_TITLE, marginBottom:12}}>Alert Log</div>
        <div style={{padding:'10px 12px', borderRadius:8, border:`1px solid ${TV.ok}40`, background:TV.okSoft}}>
          <div style={{display:'flex', alignItems:'flex-start', gap:8, fontSize:12.5, color:TV.text2}}>
            <span style={{color:TV.ok, marginTop:1}}>✓</span>
            <div>
              <div>Live BTC price loaded: <span className="tv-num" style={{color:TV.text, fontWeight:600}}>$73,773</span></div>
              <div style={{color:TV.text3, marginTop:3}}>Auto-refreshes every 60s</div>
            </div>
          </div>
        </div>
        <div style={{fontSize:12, color:TV.text4, marginTop:10}}>No new zone transitions in the last 7 days.</div>
      </div>
      {/* manual data entry */}
      <div style={PF_CARD}>
        <div style={{...PF_TITLE, marginBottom:12}}>Manual Data Entry</div>
        <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:10}}>
          {[['BTC Price','73773','LIVE ↻'],['200WMA','58525',null],['NUPL Value','0.15',null],['Realized Price','54703',null]].map(([l,v,badge])=>(
            <div key={l}>
              <div style={{display:'flex', alignItems:'center', gap:6, marginBottom:5}}>
                <span style={{fontSize:11, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.04em'}}>{l}</span>
                {badge&&<span style={{fontSize:9.5, color:TV.ok, border:`1px solid ${TV.ok}50`, padding:'1px 5px', borderRadius:4}}>{badge}</span>}
              </div>
              <div style={{background:TV.panel2, border:`1px solid ${TV.line}`, borderRadius:7, padding:'7px 10px',
                  fontSize:13, color:TV.text, fontFamily:"'Fira Code',monospace"}}>$ {v}</div>
            </div>
          ))}
        </div>
        <button className="tv-btn primary" style={{width:'100%', marginTop:14, padding:'11px', fontSize:13.5, fontWeight:700}}>UPDATE DASHBOARD</button>
      </div>
    </div>
  </div>
);

// LP Pools table
const LP_ROWS = [
  ['USDC-WETH', 'ETH', '15.7%', '$4.4M',  '$19.1M'],
  ['WBTC-USDC', 'ARB', '5.7%',  '$7.9M',  '$2.5M'],
  ['WBTC-USDC', 'ETH', '2.0%',  '$28.3M', '$518K'],
  ['WBTC-USDT', 'ARB', '7.2%',  '$12.4M', '$4.9M'],
  ['WBTC-USDT', 'ETH', '4.2%',  '$18.2M', '$4.2M'],
  ['WETH-USDC', 'ETH', '10.9%', '$7.3M',  '$726K'],
];
const LP_COLS = '1.4fr 90px 100px 110px 110px';

// Lend/Borrow Stats table
const LB_ROWS = [
  ['Aave V3',   'WETH', 'BASE', '1.9%', '2.8%', '67%', '$12.4M',  '$4.1M'],
  ['Aave V3',   'USDC', 'ETH',  '4.2%', '5.8%', '82%', '$890M',   '$160M'],
  ['Aave V3',   'WBTC', 'ETH',  '0.8%', '1.4%', '51%', '$3.2B',   '$1.6B'],
  ['Moonwell',  'WETH', 'BASE', '2.1%', '3.4%', '71%', '$8.2M',   '$2.4M'],
  ['Moonwell',  'USDC', 'BASE', '4.8%', '6.2%', '88%', '$24.0M',  '$2.9M'],
  ['Venus',     'XRP',  'BNB',  '0.4%', '8.5%', '18%', '$42.0M',  '$34.4M'],
];
const LB_COLS = '110px 80px 80px 100px 100px 90px 110px 110px';

// ─── main component ───────────────────────────────────────────
const MarketDataHF = () => (
  <div className="tv-frame" style={{display:'flex', flexDirection:'column'}}>
    <TVNav active="Market Data"/>
    <div style={{flex:1, padding:'22px 36px 32px', display:'flex', flexDirection:'column', gap:18,
        overflowY:'auto', minHeight:0}}>

      {/* top controls */}
      <div style={{display:'flex', alignItems:'center', gap:10, flexShrink:0}}>
        <button className="tv-btn primary" style={{padding:'7px 14px', fontSize:13}}>↻ Live Data</button>
        <button className="tv-btn" style={{padding:'7px 14px', fontSize:13}}>✦ AI Daily Brief</button>
        <button className="tv-btn ghost" style={{padding:'7px 10px', fontSize:14}}>↻</button>
        <span style={{fontSize:12.5, color:TV.text3}}>Last Updated: 30/05/2026 14:00</span>
      </div>

      {/* price row */}
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr 1fr', gap:14, flexShrink:0}}>
        <PriceCard sym="Bitcoin" icon="₿" price="$73,851" change="+0.64% (24h)" changeUp={true}
            rows={[['Dominance','57.3%'],['200D MA','$79,939 (-7.6%)',TV.fail],['7d Return','-4.07%',TV.fail],
                   ['30d Return','-3.19%',TV.fail],['30d Vol','Low (27%)',TV.warn],['14d Range','5.6%']]}/>
        <PriceCard sym="Ethereum" icon="Ξ" price="$2,024" change="+0.58% (24h)" changeUp={true}
            rows={[['Dominance','9.5%'],['ETH/BTC','0.02741'],['7d Return','-3.53%',TV.fail],
                   ['30d Return','-10.28%',TV.fail],['30d Vol','Low (29%)',TV.warn],['14d Range','6.1%']]}/>
        {/* Fear & Greed */}
        <div style={PF_CARD}>
          <div style={{fontSize:15, fontWeight:700, color:TV.accent, marginBottom:8}}>Fear &amp; Greed</div>
          <FearGreedGauge value={23}/>
          <div style={{marginTop:8}}>
            {[['7d Avg','23'],['30d Avg','23'],['Trend','↓ Declining',TV.fail]].map(([l,v,vc])=>(
              <StatRow key={l} label={l} value={v} valueColor={vc}/>
            ))}
          </div>
        </div>
        {/* Macro */}
        <div style={PF_CARD}>
          <div style={{fontSize:15, fontWeight:700, color:TV.accent, marginBottom:10}}>Macro</div>
          <div style={{display:'grid', gridTemplateColumns:'1fr auto auto', gap:'6px 12px', fontSize:12, color:TV.text3,
              fontWeight:600, letterSpacing:'.04em', textTransform:'uppercase', paddingBottom:6, borderBottom:`1px solid ${TV.line}`}}>
            <span>Metric</span><span>Value</span><span>Comment</span>
          </div>
          {[['DXY (USD Index)','98.91','7d prior: 99.19, weakening'],['US 10Y Yield','4.42%','Near resistance'],
            ['M2 Money Supply','$21.1T','Slowly expanding'],['BTC Dominance','57.3%','Bullish BTC trend']].map(([l,v,c])=>(
            <div key={l} style={{display:'grid', gridTemplateColumns:'1fr auto auto', gap:'6px 12px',
                padding:'6px 0', borderBottom:`1px solid ${TV.lineSoft}`, fontSize:12.5}}>
              <span style={{color:TV.text}}>{l}</span>
              <span className="tv-num" style={{color:TV.text, fontWeight:600}}>{v}</span>
              <span style={{color:TV.text3, fontSize:11.5}}>{c}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Market Overview + Futures */}
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:14, flexShrink:0}}>
        <div style={PF_CARD}>
          <div style={{fontSize:15, fontWeight:700, color:TV.accent, marginBottom:10}}>Market Overview</div>
          {[['Total Market Cap','$2.58T'],['24h Volume','$60.0B'],['Stablecoin Supply','$314.5B'],
            ['Stablecoin 7d','-0.88%',TV.fail],['ETH Staking APR','2.4%',TV.ok],
            ['BTC Deribit Index','$73,890'],['Spot-Index Spread','$-39',TV.fail],['DeFi TVL','$80.6B']].map(([l,v,vc])=>(
            <StatRow key={l} label={l} value={v} valueColor={vc}/>
          ))}
        </div>
        <div style={PF_CARD}>
          <div style={{fontSize:15, fontWeight:700, color:TV.accent, marginBottom:10}}>Futures (Bybit)</div>
          <div style={{display:'grid', gridTemplateColumns:'80px 1fr 1fr 1fr', gap:10,
              fontSize:11, fontWeight:700, color:TV.text3, letterSpacing:'.05em', textTransform:'uppercase',
              paddingBottom:8, borderBottom:`1px solid ${TV.line}`}}>
            <span></span><span style={{textAlign:'right'}}>Funding</span>
            <span style={{textAlign:'right'}}>Ann.</span><span style={{textAlign:'right'}}>OI</span>
          </div>
          {[['BTC','0.0094%','10.3%','$4.1B'],['ETH','0.0100%','11.0%','$1.7B'],['SOL','0.0056%','6.1%','—']].map(([s,f,a,o])=>(
            <div key={s} style={{display:'grid', gridTemplateColumns:'80px 1fr 1fr 1fr', gap:10,
                padding:'10px 0', borderBottom:`1px solid ${TV.lineSoft}`, alignItems:'center'}}>
              <span className="tv-num" style={{fontWeight:700, color:TV.text}}>{s}</span>
              <span className="tv-num" style={{textAlign:'right', color:TV.text2, fontSize:13}}>{f}</span>
              <span className="tv-num" style={{textAlign:'right', color:TV.ok, fontWeight:700, fontSize:13}}>{a}</span>
              <span className="tv-num" style={{textAlign:'right', color:TV.text2, fontSize:13}}>{o}</span>
            </div>
          ))}
        </div>
      </div>

      {/* BTC Macro Cycle Dashboard */}
      <div style={PF_CARD}>
        <div style={{...PF_TITLE, fontSize:19, marginBottom:16}}>BTC Macro Cycle Dashboard</div>
        <MacroCycleSection/>
      </div>

      {/* LP Pools */}
      <div style={PF_CARD}>
        <div style={{fontSize:15, fontWeight:700, color:TV.adapt, marginBottom:14}}>LP Pools (Uniswap V3)</div>
        <div style={{borderRadius:10, border:`1px solid ${TV.line}`, overflow:'hidden'}}>
          <div style={{display:'grid', gridTemplateColumns:LP_COLS, gap:12, padding:'9px 14px',
              background:TV.panel, fontSize:11, fontWeight:700, color:TV.text3, letterSpacing:'.05em', textTransform:'uppercase'}}>
            <span>Pool</span><span>Chain</span><span style={{textAlign:'right'}}>Fee APR</span>
            <span style={{textAlign:'right'}}>TVL</span><span style={{textAlign:'right'}}>24h Vol</span>
          </div>
          {LP_ROWS.map(([pool, chain, apr, tvl, vol], i) => (
            <div key={i} style={{display:'grid', gridTemplateColumns:LP_COLS, gap:12, padding:'11px 14px',
                alignItems:'center', borderTop:`1px solid ${TV.lineSoft}`, fontSize:13}}>
              <span className="tv-num" style={{fontWeight:700, color:TV.text}}>{pool}</span>
              <ChainBadge chain={chain}/>
              <span className="tv-num" style={{textAlign:'right', color:TV.ok, fontWeight:700}}>{apr}</span>
              <span className="tv-num" style={{textAlign:'right', color:TV.text2}}>{tvl}</span>
              <span className="tv-num" style={{textAlign:'right', color:TV.text2}}>{vol}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Lend / Borrow Stats */}
      <div style={PF_CARD}>
        <div style={{fontSize:15, fontWeight:700, color:TV.adapt, marginBottom:4}}>Lend / Borrow Stats</div>
        <div style={{...PF_SUB, marginBottom:14}}>Current supply and borrow rates across active lending protocols and assets.</div>
        <div style={{borderRadius:10, border:`1px solid ${TV.line}`, overflow:'hidden'}}>
          <div style={{display:'grid', gridTemplateColumns:LB_COLS, gap:10, padding:'9px 14px',
              background:TV.panel, fontSize:11, fontWeight:700, color:TV.text3, letterSpacing:'.05em', textTransform:'uppercase'}}>
            <span>Protocol</span><span>Asset</span><span>Chain</span>
            <span style={{textAlign:'right'}}>Supply APY</span><span style={{textAlign:'right'}}>Borrow APY</span>
            <span style={{textAlign:'right'}}>Utiliz.</span>
            <span style={{textAlign:'right'}}>Total Supply</span><span style={{textAlign:'right'}}>Available</span>
          </div>
          {LB_ROWS.map(([proto,asset,chain,sup,bor,util,total,avail],i)=>(
            <div key={i} style={{display:'grid', gridTemplateColumns:LB_COLS, gap:10, padding:'11px 14px',
                alignItems:'center', borderTop:`1px solid ${TV.lineSoft}`, fontSize:13}}>
              <span style={{fontWeight:600, color:TV.text}}>{proto}</span>
              <span style={{display:'flex', alignItems:'center', gap:7}}>
                <TokenIcon sym={asset} size={18}/>
                <span className="tv-num" style={{fontWeight:700, color:TV.text}}>{asset}</span>
              </span>
              <ChainBadge chain={chain}/>
              <span className="tv-num" style={{textAlign:'right', color:TV.ok, fontWeight:700}}>{sup}</span>
              <span className="tv-num" style={{textAlign:'right', color:TV.fail, fontWeight:700}}>{bor}</span>
              <span className="tv-num" style={{textAlign:'right', color:TV.text2}}>{util}</span>
              <span className="tv-num" style={{textAlign:'right', color:TV.text2}}>{total}</span>
              <span className="tv-num" style={{textAlign:'right', color:TV.text2}}>{avail}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  </div>
);
