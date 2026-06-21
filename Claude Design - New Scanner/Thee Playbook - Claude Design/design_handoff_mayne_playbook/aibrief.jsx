// aibrief.jsx — AI Brief tab (redesigned: recommendations-first, concise)
// Reuses TV.*, .tv-*, PF_CARD/TITLE/SUB, ToggleSwitch, TVNav (global).

// ── helpers ───────────────────────────────────────────────────
const ABSection = ({title, color, children, right}) => (
  <div style={PF_CARD}>
    <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:14}}>
      <div style={{fontSize:15, fontWeight:700, color:color||TV.accent}}>{title}</div>
      {right}
    </div>
    {children}
  </div>
);

const Chip = ({label, color, bg, border}) => (
  <span style={{fontSize:11, fontWeight:700, color:color, padding:'2px 8px', borderRadius:4,
      background:bg, border:`1px solid ${border||color+'55'}`}}>{label}</span>
);

const priorityStyle = {
  'HIGH':  {color:TV.fail, bg:TV.failSoft, border:'rgba(255,138,138,.45)'},
  'MED':   {color:TV.warn, bg:TV.warnSoft, border:'rgba(255,210,63,.45)'},
  'LOW':   {color:TV.ok,   bg:TV.okSoft,   border:'rgba(79,221,142,.45)'},
  'DONE':  {color:TV.text4, bg:'transparent', border:TV.line},
};

// ── data ──────────────────────────────────────────────────────
const RECS = [
  {
    n:1, priority:'HIGH', timing:'NOW · THIS WEEK',
    title:'Accumulate BTC: USDC → cbBTC (Arbitrum)',
    summary:'Allocate $5,000–$7,000 from idle USDC on Base to purchase cbBTC, targeting the cold wallet treasury sleeve. Execute over 2–3 tranches.',
    impact:'Brings BTC treasury from 1.0% → ~16%; resolves most critical allocation violation (Sec 1.2).',
    impactColor: TV.ok,
    tags:['BTC Treasury','Allocation Fix'],
  },
  {
    n:2, priority:'MED', timing:'NOW · THIS WEEK',
    title:'Open ETH/USDC snuggle LP on Base',
    summary:'Allocate $3,000–$4,000 from idle USDC (Arbitrum) to ETH/USDC on Base, range 8–12% below current ETH price. Max 40% of stablecoin reserve.',
    impact:'Converts idle stables to yield-generating LP; ETH allocation rises toward 15% minimum.',
    impactColor: TV.ok,
    tags:['LP Deploy','Yield'],
  },
  {
    n:3, priority:'HIGH', timing:'IMMEDIATE',
    title:'Exit HyperVM USDC/WHYPE LP entirely',
    summary:'Position ($2,209) is on an unsanctioned chain/pair per Playbook Sec 4.4. Withdraw both USDC and WHYPE, swap WHYPE → USDC, bridge to Arbitrum, consolidate.',
    impact:'Eliminates counterparty + smart-contract risk. Stablecoin reserve +$2,209. Eliminates unsanctioned exposure.',
    impactColor: TV.ok,
    tags:['Risk Removal','Unsanctioned Pool'],
  },
];

const RISKS = [
  {sev:'CRITICAL', text:'BTC treasury at $873 (1.0%) — below 15% playbook minimum. Immediate FLAG per Sec 1.2.'},
  {sev:'FLAG',     text:'ETH allocation $1,021 (0.2%) — below 15% minimum. Critically underfunded per Sec 1.1.'},
  {sev:'MONITOR',  text:'Stablecoin reserve $37,103 (75.6%) — above BEAR target 15–20%. No yield-generating infrastructure.'},
  {sev:'ALERT',    text:'HyperVM USDC/WHYPE LP ($2,209, 4.7%) — unsanctioned pool on HyperEVM. Violates Sec 4.4 + Sec 11.'},
  {sev:'ALERT',    text:'ESHARE/7LP ($4,449, 9.4%) — no range data available. Out-of-range >24h triggers mandatory reset per Sec 4.2.'},
];
const sevStyle = {
  CRITICAL:{color:TV.fail, bg:TV.failSoft, border:'rgba(255,138,138,.45)'},
  FLAG:    {color:'#f97316', bg:'rgba(249,115,22,.12)', border:'rgba(249,115,22,.45)'},
  MONITOR: {color:TV.warn, bg:TV.warnSoft, border:'rgba(255,210,63,.45)'},
  ALERT:   {color:TV.adapt, bg:TV.adaptSoft, border:'rgba(47,180,232,.45)'},
};

const MARKET_ROWS = [
  ['BTC vs 200MA', '$72,890 vs $80,228 (−9.2%)', 'Clearly below long-term trend — primary BEAR trigger in playbook'],
  ['Fear & Greed 7D Avg', '22 (Extreme Fear)', 'Historically accumulation signal; BTC to hold 200MA before re-entering'],
  ['BTC OI at 96th Pct', '$4.51B, +8.9B WoW', 'OI at extremes in a declining market — elevated cascade risk'],
  ['ETH/BTC Ratio', '0.0277, −0.4% WoW, flat trend', 'No altcoin rotation; ETH accumulation should remain paused'],
  ['DXY', '98.90, weakening', 'Mild tailwind; softens but does not override crypto-native BEAR'],
  ['BTC Support S1/S2', '$71,473 / $69,940', 'Break below S1 at $69,940 in play and could trigger cascade liquidations'],
];

const HOUSEKEEPING = [
  {done:false, text:'Consolidate BNB positions (7 separate, totalling −$257) — below 2% threshold. Consolidate or swap to USDC → bridge to Arbitrum.'},
  {done:false, text:'Close dust positions: TEVA ($12 total, 2 wallets), VVV ($7), DYOR ($2), GMKR ($1), SIO ($2) — all <0.1%. Swap to USDC.'},
  {done:false, text:'Clarify [Base] ESHARE/7LP ($4,449) — get actual and compare to playbook targets before next report.'},
  {done:false, text:'Collect uncollected fees on HyperVM USDC/WHYPE ($29.13) before or during exit.'},
  {done:false, text:'Move cbBTC hot wallet ($1,204) to cold wallet treasury sleeve once Rec 1 complete.'},
  {done:true,  text:'HYPE token ($41, 0.70% on HyperVM) — swap to USDC or hold only if specific reason; otherwise dust.'},
];

const PORTFOLIO_ROWS = [
  ['Category',           'Target',    'Actual',     'Status'],
  ['BTC (treasury)',     '15–20%',    '1.0%',       'CRITICAL'],
  ['ETH deployment',     '≥15%',      '0.2%',       'FLAG'],
  ['LP deployed',        '15–25%',    '36.2%',      'REVIEW'],
  ['Stablecoins (idle)', '15–20%',    '57.4%',      'OVER'],
];

const PROJECTED = [
  ['BTC treasury (after recs)',    '$6,473 → ~$13K', '1.0% → ~16%'],
  ['ETH deployment (after recs)',  '$1,021 → ~$5K',  '0.2% → ~8%'],
  ['Stablecoins (after recs)',     '$37K → ~$30K',   '57% → ~47%'],
  ['Unsanctioned exposure',        '$2,209 → $0',    'Eliminated'],
];

// ── screen ────────────────────────────────────────────────────
const AIBriefHF = () => (
  <div className="tv-frame" style={{display:'flex', flexDirection:'column'}}>
    <TVNav active="AI Brief"/>
    <div style={{flex:1, padding:'22px 36px 32px', display:'flex', flexDirection:'column', gap:16,
        overflowY:'auto', minHeight:0}}>

      {/* header */}
      <div style={{display:'flex', alignItems:'center', gap:12, flexShrink:0}}>
        <div>
          <div style={{fontSize:28, fontWeight:800, color:TV.text, letterSpacing:'-.5px', lineHeight:1.1}}>AI Brief</div>
          <div style={{fontSize:13, color:TV.text3, marginTop:3}}>Generated: 2026-05-28 17:24 — <span style={{color:TV.warn}}>missaligned</span> · Prompt: Strategy Playbook · Docs: DeFi Strategy</div>
        </div>
        <div style={{flex:1}}/>
        <button className="tv-btn ghost" style={{padding:'7px 12px', fontSize:12.5}}>⚙ Config</button>
        <button className="tv-btn" style={{padding:'7px 14px', fontSize:13}}>Daily Digest</button>
        <button className="tv-btn primary" style={{padding:'8px 18px', fontSize:13}}>↻ Generate Report</button>
      </div>

      {/* critical alert banner */}
      <div style={{padding:'12px 16px', borderRadius:10, border:`1.5px solid ${TV.fail}`,
          background:TV.failSoft, display:'flex', alignItems:'center', gap:12, flexShrink:0}}>
        <span style={{fontSize:16}}>⚠</span>
        <div style={{flex:1}}>
          <span style={{fontWeight:700, color:TV.fail, fontSize:13}}>3 critical violations detected — </span>
          <span style={{color:TV.text2, fontSize:13}}>BTC treasury 1.0% (min 15%), ETH 0.2% (min 15%), HyperVM unsanctioned pool active.</span>
        </div>
        <Chip label="5 ACTIVE ALERTS" color={TV.fail} bg={TV.failSoft}/>
      </div>

      {/* market regime + portfolio health */}
      <div style={{display:'grid', gridTemplateColumns:'1.2fr 1fr', gap:16, flexShrink:0}}>
        {/* market regime */}
        <ABSection title="Market Regime Assessment">
          {[['Short-term (7D)','Bear 60%',[[5,TV.ok,'Bull 5%'],[35,TV.text2,'Sideways 35%'],[60,TV.fail,'Bear 60%']]],
            ['Mid-term (30D)','Bear 50%',[[10,TV.ok,'Bull 10%'],[40,TV.text2,'Sideways 40%'],[50,TV.fail,'Bear 50%']]]].map(([lbl,summary,segs])=>(
            <div key={lbl} style={{marginBottom:12}}>
              <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:5}}>
                <span style={{fontSize:12.5, fontWeight:600, color:TV.text}}>{lbl}</span>
                <Chip label={summary} color={TV.fail} bg={TV.failSoft}/>
              </div>
              <div style={{display:'flex', height:10, borderRadius:5, overflow:'hidden'}}>
                {segs.map(([pct,col])=>(
                  <div key={col} style={{width:`${pct}%`, background:col, opacity:0.9}}/>
                ))}
              </div>
              <div style={{display:'flex', gap:10, marginTop:4}}>
                {segs.map(([pct,col,name])=>(
                  <span key={name} style={{fontSize:10.5, color:col}}>{name}</span>
                ))}
              </div>
            </div>
          ))}
          <div style={{fontSize:12.5, color:TV.text3, marginTop:4, lineHeight:1.5}}>
            Two confirmed BEAR signals (BTC −9.2% below 200MA, F&G 22). Mild sideways probability — one anomaly: BTC OI at 96th pct signals elevated cascade risk.
          </div>
        </ABSection>

        {/* portfolio status */}
        <ABSection title="Portfolio Status">
          <div style={{borderRadius:8, border:`1px solid ${TV.line}`, overflow:'hidden'}}>
            {PORTFOLIO_ROWS.map(([cat,tgt,act,st],i) => {
              const hdr = i===0;
              const stCol = st==='CRITICAL'?TV.fail: st==='FLAG'?'#f97316': st==='REVIEW'?TV.warn: st==='OVER'?TV.adapt: TV.ok;
              return (
                <div key={cat} style={{display:'grid', gridTemplateColumns:'1.3fr 90px 80px 90px', gap:8,
                    padding: hdr?'7px 12px':'9px 12px',
                    background:hdr?TV.panel:i%2===0?'transparent':TV.panel2+'44',
                    borderTop: hdr?'none':`1px solid ${TV.lineSoft}`,
                    fontSize:hdr?11:13, fontWeight:hdr?700:500,
                    color:hdr?TV.text3:TV.text, letterSpacing:hdr?'.04em':'normal', textTransform:hdr?'uppercase':'none'}}>
                  <span>{cat}</span>
                  <span className="tv-num" style={{color:hdr?undefined:TV.text3}}>{tgt}</span>
                  <span className="tv-num" style={{color:hdr?undefined:TV.text, fontWeight:600}}>{act}</span>
                  {hdr ? <span>Status</span>
                    : <Chip label={st} color={stCol} bg={`${stCol}15`} border={`${stCol}55`}/>}
                </div>
              );
            })}
          </div>
        </ABSection>
      </div>

      {/* RECOMMENDATIONS — moved to top (most actionable) */}
      <ABSection title="Recommendations" color={TV.ok}
          right={<span style={{fontSize:12, color:TV.text3}}>NOT FINANCIAL ADVICE · USE YOUR OWN JUDGEMENT</span>}>
        <div style={{display:'flex', flexDirection:'column', gap:12}}>
          {RECS.map(r => {
            const ps = priorityStyle[r.priority];
            return (
              <div key={r.n} style={{padding:16, borderRadius:10, border:`1.5px solid ${ps.border}`,
                  background:`${ps.color}08`, display:'flex', flexDirection:'column', gap:9}}>
                <div style={{display:'flex', alignItems:'center', gap:10, flexWrap:'wrap'}}>
                  <span style={{fontSize:14, fontWeight:800, color:TV.text3}}>#{r.n}</span>
                  <Chip label={r.priority} color={ps.color} bg={ps.bg} border={ps.border}/>
                  <span style={{fontSize:11.5, color:TV.text3, fontWeight:600}}>{r.timing}</span>
                  <div style={{flex:1}}/>
                  {r.tags.map(t=><span key={t} className="tv-chip" style={{fontSize:11}}>{t}</span>)}
                </div>
                <div style={{fontSize:14.5, fontWeight:700, color:TV.text}}>{r.title}</div>
                <div style={{fontSize:13, color:TV.text2, lineHeight:1.5}}>{r.summary}</div>
                <div style={{fontSize:12, color:r.impactColor, lineHeight:1.4}}>↳ {r.impact}</div>
              </div>
            );
          })}
        </div>
      </ABSection>

      {/* market analysis + risk alerts */}
      <div style={{display:'grid', gridTemplateColumns:'1.3fr 1fr', gap:16, flexShrink:0}}>
        {/* market analysis */}
        <ABSection title="Market Analysis">
          <div style={{borderRadius:8, border:`1px solid ${TV.line}`, overflow:'hidden'}}>
            <div style={{display:'grid', gridTemplateColumns:'140px 160px 1fr', gap:10, padding:'7px 12px',
                background:TV.panel, fontSize:11, fontWeight:700, color:TV.text3, letterSpacing:'.04em', textTransform:'uppercase'}}>
              <span>Metric</span><span>Value</span><span>Interpretation</span>
            </div>
            {MARKET_ROWS.map(([m,v,i]) => (
              <div key={m} style={{display:'grid', gridTemplateColumns:'140px 160px 1fr', gap:10,
                  padding:'9px 12px', borderTop:`1px solid ${TV.lineSoft}`, fontSize:12.5, alignItems:'start'}}>
                <span style={{color:TV.text2, fontWeight:600}}>{m}</span>
                <span className="tv-num" style={{color:TV.text}}>{v}</span>
                <span style={{color:TV.text3, lineHeight:1.4}}>{i}</span>
              </div>
            ))}
          </div>
        </ABSection>

        {/* risk alerts */}
        <ABSection title="Risk Alerts">
          <div style={{display:'flex', flexDirection:'column', gap:9}}>
            {RISKS.map((r,i) => {
              const s = sevStyle[r.sev];
              return (
                <div key={i} style={{display:'flex', gap:10, padding:'10px 12px', borderRadius:8,
                    border:`1px solid ${s.border}`, background:s.bg, alignItems:'flex-start'}}>
                  <Chip label={r.sev} color={s.color} bg="transparent" border={s.border}/>
                  <span style={{fontSize:12.5, color:TV.text2, lineHeight:1.45, flex:1}}>{r.text}</span>
                </div>
              );
            })}
          </div>
        </ABSection>
      </div>

      {/* housekeeping + projected portfolio */}
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:16, flexShrink:0}}>
        {/* housekeeping */}
        <ABSection title="Housekeeping">
          <div style={{display:'flex', flexDirection:'column', gap:8}}>
            {HOUSEKEEPING.map((h,i) => (
              <div key={i} style={{display:'flex', gap:10, alignItems:'flex-start'}}>
                <span style={{flexShrink:0, marginTop:1, fontSize:13, color:h.done?TV.ok:TV.text4}}>
                  {h.done?'✓':'○'}
                </span>
                <span style={{fontSize:12.5, color:h.done?TV.text3:TV.text2, lineHeight:1.4,
                    textDecoration:h.done?'line-through':'none'}}>{h.text}</span>
              </div>
            ))}
          </div>
        </ABSection>

        {/* projected portfolio */}
        <ABSection title="Projected Portfolio (after recommendations)">
          <div style={{borderRadius:8, border:`1px solid ${TV.line}`, overflow:'hidden'}}>
            <div style={{display:'grid', gridTemplateColumns:'1fr 130px 90px', gap:8, padding:'7px 12px',
                background:TV.panel, fontSize:11, fontWeight:700, color:TV.text3, letterSpacing:'.04em', textTransform:'uppercase'}}>
              <span>Category</span><span>Change</span><span style={{textAlign:'right'}}>New %</span>
            </div>
            {PROJECTED.map(([cat,chg,pct]) => (
              <div key={cat} style={{display:'grid', gridTemplateColumns:'1fr 130px 90px', gap:8,
                  padding:'10px 12px', borderTop:`1px solid ${TV.lineSoft}`, fontSize:13}}>
                <span style={{color:TV.text, fontWeight:600}}>{cat}</span>
                <span className="tv-num" style={{color:TV.ok, fontSize:12.5}}>{chg}</span>
                <span className="tv-num" style={{textAlign:'right', color:TV.text2}}>{pct}</span>
              </div>
            ))}
          </div>
          <div style={{marginTop:12, padding:'10px 12px', borderRadius:8, background:TV.panel2, border:`1px solid ${TV.line}`}}>
            <div style={{fontSize:12, color:TV.text3, lineHeight:1.5}}>
              Portfolio deploys $10,000–$13,000 from idle stablecoins into BTC treasury + ETH LP, eliminating HyperVM exposure. BTC treasury ~16%, ETH ~8%, stables compress to ~47%.
            </div>
          </div>
        </ABSection>
      </div>

      {/* AI config context footer */}
      <div style={{padding:'12px 16px', borderRadius:8, background:TV.panel, border:`1px solid ${TV.line}`,
          display:'flex', alignItems:'center', gap:16, flexShrink:0, flexWrap:'wrap'}}>
        <span style={{fontSize:11.5, fontWeight:700, color:TV.text3, letterSpacing:'.04em', textTransform:'uppercase'}}>AI Config</span>
        {[['Provider','Claude (Anthropic) · claude-sonnet-4-5'],['Schedule','UTC 08:00 daily'],
          ['Prompt','Strategy Playbook (saved in Settings → AI Config)'],
          ['Documents','DeFi Strategy · Trading Strategy (Settings → Document Uploads)']].map(([k,v])=>(
          <span key={k} style={{fontSize:12.5, color:TV.text3}}>
            <span style={{color:TV.text4}}>{k}: </span>{v}
          </span>
        ))}
        <div style={{flex:1}}/>
        <button className="tv-btn ghost" style={{padding:'5px 12px', fontSize:12}}>Edit Config →</button>
      </div>
    </div>
  </div>
);
