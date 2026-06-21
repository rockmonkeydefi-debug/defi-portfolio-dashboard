// lp-tools.jsx — LP Tools sub-tab within Portfolio
// Reuses TV.*, .tv-*, PF_CARD/TITLE/SUB/METRIC, TVNav, MDLine (from marketdata.jsx), ChainBadge (global).

// Portfolio sub-nav (Token Holdings | DeFi Positions | LP Tools)
const PFSubNav = ({active}) => (
  <div style={{borderBottom:`1px solid ${TV.line}`, background:TV.panel2,
      padding:'0 36px', display:'flex', gap:2, alignItems:'flex-end', flexShrink:0}}>
    {['Token Holdings','DeFi Positions','LP Tools'].map(it => {
      const on = it === active;
      return (
        <div key={it} style={{padding:'9px 18px', fontSize:14, fontWeight:on?600:400,
            color:on?TV.text:TV.text2, cursor:'pointer',
            borderBottom:on?`2px solid ${TV.accent}`:'2px solid transparent',
            background:on?`${TV.panel3}88`:'transparent'}}>{it}</div>
      );
    })}
  </div>
);

// LP tool sub-nav
const LPToolSubNav = ({active}) => (
  <div style={{display:'flex', gap:3, padding:3, borderRadius:8, background:TV.panel2, border:`1px solid ${TV.line}`, width:'fit-content'}}>
    {['LP Optimizer','IL Calculator','Hedge Calculator'].map(it => {
      const on = it === active;
      return (
        <span key={it} style={{padding:'7px 16px', borderRadius:6, fontSize:13.5, fontWeight:on?600:500,
            color:on?TV.text:TV.text3, background:on?TV.panel3:'transparent',
            boxShadow:on?`inset 0 -2px 0 ${TV.accent}`:'none', cursor:'pointer'}}>{it}</span>
      );
    })}
  </div>
);

const ToolDesc = ({text}) => (
  <div style={{...PF_SUB, lineHeight:1.6, marginBottom:0}}>{text}</div>
);

// ── LP Optimizer ───────────────────────────────────────────────
const LP_OPT_ROWS = [
  ['WETH-USDC', 'BASE', '$123.9M', '$12.3M', '10.8%', '0.3%'],
  ['WETH-USDC', 'BASE', '$12.5M',  '$5.4M',  '7.9%',  '0.05%'],
  ['WETH-USDC', 'BASE', '$603K',   '$1.8K',  '1.1%',  '1%'],
  ['WETH-USDC', 'BASE', '$436.3K', '$2.0M',  '16.7%', '0.01%'],
];
const OPT_COLS = 'minmax(140px,1.5fr) 90px 110px 110px 110px 90px';

const LPOptimizerTool = () => (
  <div style={{display:'flex', flexDirection:'column', gap:18}}>
    <div style={PF_CARD}>
      <div style={{...PF_TITLE, marginBottom:8}}>How this tool works</div>
      <ToolDesc text="Finds optimal concentrated liquidity ranges by evaluating candidates across bull, bear, and sideways market regimes. Uses price data from CoinGecko, pool data from DeFiLlama, on-chain liquidity from RPC, and AI-derived regime probabilities from your Daily Brief. Each candidate range is scored on expected fee income minus impermanent loss and rebalancing costs."/>
    </div>
    {/* search form */}
    <div style={PF_CARD}>
      <div style={{display:'grid', gridTemplateColumns:'140px 160px 140px auto 1fr', gap:12, alignItems:'end', marginBottom:20}}>
        {[['Chain','Base',false],['Token Pair','WETH-USDC',false],['Min TVL ($)','100000',false]].map(([lbl,val])=>(
          <div key={lbl}>
            <div style={{fontSize:11, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em', marginBottom:6}}>{lbl}</div>
            <div style={{background:TV.panel2, border:`1px solid ${TV.line}`, borderRadius:7, padding:'8px 12px',
                fontSize:13, color:TV.text, display:'flex', justifyContent:'space-between'}}>
              <span>{val}</span><span style={{color:TV.text3}}>▾</span>
            </div>
          </div>
        ))}
        <button className="tv-btn primary" style={{padding:'9px 20px', fontSize:13, alignSelf:'end'}}>Search Pools</button>
        <div>
          <div style={{fontSize:11, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em', marginBottom:6}}>Portfolio Position</div>
          <div style={{background:TV.panel2, border:`1px solid ${TV.line}`, borderRadius:7, padding:'8px 12px',
              fontSize:13, color:TV.text4, display:'flex', justifyContent:'space-between'}}>
            <span>Select position…</span><span style={{color:TV.text3}}>▾</span>
          </div>
        </div>
      </div>
      <div style={{borderRadius:10, border:`1px solid ${TV.line}`, overflow:'hidden'}}>
        <div style={{display:'grid', gridTemplateColumns:OPT_COLS, gap:12, padding:'10px 16px',
            background:TV.panel, fontSize:11, fontWeight:700, color:TV.text3, letterSpacing:'.05em', textTransform:'uppercase'}}>
          <span>Symbol</span><span>Chain</span>
          <span style={{textAlign:'right'}}>TVL</span><span style={{textAlign:'right'}}>24h Vol</span>
          <span style={{textAlign:'right'}}>Fee APR</span><span style={{textAlign:'right'}}>Fee Tier</span>
        </div>
        {LP_OPT_ROWS.map(([sym,chain,tvl,vol,apr,tier],i)=>(
          <div key={i} style={{display:'grid', gridTemplateColumns:OPT_COLS, gap:12, padding:'12px 16px',
              borderTop:`1px solid ${TV.lineSoft}`, alignItems:'center', fontSize:13}}>
            <span className="tv-num" style={{fontWeight:700, color:TV.text}}>{sym}</span>
            <ChainBadge chain={chain}/>
            <span className="tv-num" style={{textAlign:'right', color:TV.text2}}>{tvl}</span>
            <span className="tv-num" style={{textAlign:'right', color:TV.text2}}>{vol}</span>
            <span className="tv-num" style={{textAlign:'right', color:TV.ok, fontWeight:700}}>{apr}</span>
            <span className="tv-num" style={{textAlign:'right', color:TV.text3}}>{tier}</span>
          </div>
        ))}
      </div>
    </div>
  </div>
);

// ── IL Calculator ─────────────────────────────────────────────
// LP value curve data (price 1752→2248 in 10 steps)
const ILC_PRICES = [1752,1850,1900,1950,2000,2050,2100,2150,2200,2248];
const ILC_LP     = [9255,9612,9748,9884,10000,10092,10154,10196,10232,10248];
const ILC_HODL   = [9000,9280,9400,9520,9640,9760,9880,10000,10120,10234]; // 50/50 hold value
const IL_VS_HODL = ILC_PRICES.map((_,i)=>((ILC_LP[i]-ILC_HODL[i])/ILC_HODL[i]*100));

const ILCalculatorTool = () => {
  const W=580, H=240, pL=56, pR=12, pT=10, pB=30;
  const W2=560, H2=160;
  const minV=8800, maxV=10400;
  const ilMin=-4.5, ilMax=0.2;
  return (
    <div style={{display:'flex', flexDirection:'column', gap:18}}>
      <div style={PF_CARD}>
        <div style={{...PF_TITLE, marginBottom:8}}>How this tool works</div>
        <ToolDesc text="Visualize how your concentrated LP position value changes as price moves across your range. See impermanent loss at any price point compared to simply holding, estimate how many days of fee income are needed to recover it, and understand your token composition at each price level."/>
      </div>
      <div style={PF_CARD}>
        {/* inputs */}
        <div style={{display:'grid', gridTemplateColumns:'repeat(6,1fr) auto', gap:10, alignItems:'end', marginBottom:20}}>
          {[['Pair','WETH/USDC'],['Range Low','1800'],['Range High','2200'],['Entry Price','2000'],['Notional ($)','10000'],['Fee APR (%)','60']].map(([l,v])=>(
            <div key={l}>
              <div style={{fontSize:10.5, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.04em', marginBottom:5}}>{l}</div>
              <div style={{background:TV.panel2, border:`1px solid ${TV.line}`, borderRadius:7, padding:'7px 10px', fontSize:13, color:TV.text}}>{v}</div>
            </div>
          ))}
          <button className="tv-btn primary" style={{padding:'8px 16px', fontSize:13, alignSelf:'end'}}>Update</button>
        </div>
        {/* main layout */}
        <div style={{display:'grid', gridTemplateColumns:'1fr 220px', gap:18}}>
          <div>
            <div style={{fontSize:12, fontWeight:600, color:TV.text, textAlign:'center', marginBottom:6}}>WETH/USDC Concentrated LP</div>
            <div style={{display:'flex', gap:12, justifyContent:'center', marginBottom:8, flexWrap:'wrap'}}>
              {[['LP balance',TV.adapt],[`HODL 50/50`,TV.warn]].map(([l,c])=>(
                <span key={l} style={{display:'inline-flex',alignItems:'center',gap:5,fontSize:11,color:TV.text3}}>
                  <svg width="18" height="8"><line x1="0" y1="4" x2="18" y2="4" stroke={c} strokeWidth="2"/></svg>{l}
                </span>
              ))}
            </div>
            <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} style={{display:'block'}}>
              <MDLine pts={ILC_HODL} minV={minV} maxV={maxV} W={W} H={H} pL={pL} pR={pR} pT={pT} pB={pB} color={TV.warn} width="1.5" dash="5 4"/>
              <MDLine pts={ILC_LP}   minV={minV} maxV={maxV} W={W} H={H} pL={pL} pR={pR} pT={pT} pB={pB} color={TV.adapt} width="2"/>
              {/* boundary markers */}
              {[1,8].map(i=>{
                const x = pL+(i/(ILC_PRICES.length-1))*(W-pL-pR);
                return <line key={i} x1={x} x2={x} y1={pT} y2={H-pB} stroke={TV.text4} strokeWidth="1" strokeDasharray="3 3"/>;
              })}
              {ILC_PRICES.map((p,i)=>{
                if(i%3!==0)return null;
                const x=pL+(i/(ILC_PRICES.length-1))*(W-pL-pR);
                return <text key={p} x={x} y={H-6} fontSize="9" fill={TV.text4} textAnchor="middle" fontFamily={TV.font}>{p}</text>;
              })}
              {[8800,9200,9600,10000,10400].map(v=>{
                const y=pT+(H-pT-pB)-(v-minV)/(maxV-minV)*(H-pT-pB);
                return <text key={v} x={pL-4} y={y+3} fontSize="9" fill={TV.text4} textAnchor="end" fontFamily={TV.font}>${(v/1000).toFixed(1)}k</text>;
              })}
            </svg>
            {/* IL chart */}
            <div style={{fontSize:12, fontWeight:600, color:TV.text, textAlign:'center', margin:'12px 0 6px'}}>Impermanent Loss vs 50/50 HODL</div>
            <svg viewBox={`0 0 ${W2} ${H2}`} width="100%" height={H2} style={{display:'block'}}>
              <MDLine pts={IL_VS_HODL} minV={ilMin} maxV={ilMax} W={W2} H={H2} pL={pL} pR={pR} pT={8} pB={24}
                  color={TV.fail} width="2" fillColor={TV.fail}/>
              {IL_VS_HODL.map((_,i)=>{
                if(i%3!==0)return null;
                const x=pL+(i/(ILC_PRICES.length-1))*(W2-pL-pR);
                return <text key={i} x={x} y={H2-6} fontSize="9" fill={TV.text4} textAnchor="middle" fontFamily={TV.font}>{ILC_PRICES[i]}</text>;
              })}
            </svg>
          </div>
          {/* summary panel */}
          <div style={{display:'flex', flexDirection:'column', gap:12}}>
            <div style={{padding:14, borderRadius:10, border:`1px solid ${TV.line}`, background:TV.panel2}}>
              <div style={{fontSize:11, fontWeight:700, color:TV.adapt, textTransform:'uppercase', marginBottom:8}}>Position Summary</div>
              {[['Pair','WETH/USDC'],['Range','1800 – 2200 USDC'],['Range width','20.0%'],['Entry','2000 USDC'],['Notional','$10,000']].map(([k,v])=>(
                <div key={k} style={{display:'flex', justifyContent:'space-between', fontSize:12.5, padding:'3px 0', borderBottom:`1px solid ${TV.lineSoft}`}}>
                  <span style={{color:TV.text3}}>{k}</span><span className="tv-num" style={{color:TV.text}}>{v}</span>
                </div>
              ))}
            </div>
            <div style={{padding:14, borderRadius:10, border:`1px solid ${TV.line}`, background:TV.panel2}}>
              <div style={{fontSize:11, fontWeight:700, color:TV.ok, textTransform:'uppercase', marginBottom:8}}>Fee Income</div>
              {[['APR','60%'],['Daily','+$16.44'],['Monthly','+$493'],['Yearly','+$6,000']].map(([k,v])=>(
                <div key={k} style={{display:'flex', justifyContent:'space-between', fontSize:12.5, padding:'3px 0', borderBottom:`1px solid ${TV.lineSoft}`}}>
                  <span style={{color:TV.text3}}>{k}</span><span className="tv-num" style={{color:TV.ok, fontWeight:600}}>{v}</span>
                </div>
              ))}
            </div>
            <div style={{padding:14, borderRadius:10, border:`1px solid ${TV.warn}55`, background:TV.warnSoft}}>
              <div style={{fontSize:11, fontWeight:700, color:TV.warn, textTransform:'uppercase', marginBottom:6}}>Break-even (IL)</div>
              <div className="tv-num" style={{fontSize:22, fontWeight:700, color:TV.text}}>~17 days</div>
              <div style={{fontSize:11.5, color:TV.text3}}>to cover worst-case IL</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

// ── Hedge Calculator ──────────────────────────────────────────
const HEDGE_ROWS = [
  ['WETH +15%', '$2,300', '+$232', TV.ok,  '-$750', TV.fail, '-$518', TV.fail, '-5.18%'],
  ['LP Upper Range (10%)', '$2,200', '+$232', TV.ok,  '-$500', TV.fail, '-$268', TV.fail, '-2.68%'],
  ['⚠ Stop Loss', '$2,171', '+$227', TV.ok,  '-$427', TV.fail, '-$200', TV.fail, '-2.00%'],
  ['Entry (LP)', '$2,000', '+$0', TV.text3, '+$0', TV.text3, '+$0', TV.text3, '+0.00%'],
  ['Entry (Hedge)', '$2,000', '+$0', TV.text3, '+$0', TV.text3, '+$0', TV.text3, '+0.00%'],
  ['LP Lower Range (-10%)', '$1,800', '-$745', TV.fail, '+$500', TV.ok, '-$245', TV.fail, '-2.45%'],
  ['WETH -15%', '$1,700', '-$1,259', TV.fail, '+$750', TV.ok, '-$509', TV.fail, '-5.09%'],
];
const H_COLS = 'minmax(160px,1fr) 90px 90px 90px 90px 80px';

const HedgeCalculatorTool = () => {
  // chart data: price 1620→2420, LP P&L (parabola), hedge P&L (straight negative)
  const prices = Array.from({length:20},(_,i)=>1620+i*40);
  const lp_pnl = prices.map(p=>{
    if(p<1800) return -1500+(p-1800)*0.4;
    if(p>2200) return -400-(p-2200)*0.6;
    return 250*Math.sin(Math.PI*(p-1800)/400)-300;
  });
  const hedge_pnl = prices.map(p=>(2000-p)*0.5);
  const net_pnl = prices.map((_,i)=>lp_pnl[i]+hedge_pnl[i]);
  const W=580,H=220,pL=58,pR=12,pT=12,pB=30;
  const minV=-1600,maxV=1100;
  return (
    <div style={{display:'flex', flexDirection:'column', gap:18}}>
      <div style={PF_CARD}>
        <div style={{...PF_TITLE, marginBottom:8}}>How this tool works</div>
        <ToolDesc text="Design a hedging strategy for your LP position by tuning capital allocation, leverage, and entry price. Find the right balance to break even across your range, protect against downside below the range, or minimize overall portfolio risk."/>
        <div style={{fontSize:12.5, color:TV.adapt, marginTop:6}}>ℹ Pair and range are taken from the IL Calculator tab.</div>
      </div>
      <div style={PF_CARD}>
        {/* controls */}
        <div style={{display:'flex', alignItems:'center', gap:16, marginBottom:18, flexWrap:'wrap'}}>
          <div style={{display:'flex', flexDirection:'column', gap:5, flex:1, maxWidth:280}}>
            <div style={{display:'flex', justifyContent:'space-between', fontSize:12.5, color:TV.text3}}>
              <span>HEDGE % OF CAPITAL</span><span style={{color:TV.text, fontWeight:600}}>50%</span>
            </div>
            <div style={{height:8, borderRadius:4, background:TV.panel3, position:'relative'}}>
              <div style={{width:'50%', height:'100%', background:TV.adapt, borderRadius:4}}/>
              <div style={{position:'absolute', left:'50%', top:'50%', width:14, height:14, borderRadius:'50%',
                  background:TV.text, border:`2px solid ${TV.adapt}`, transform:'translate(-50%,-50%)'}}/>
            </div>
          </div>
          <div style={{display:'flex', flexDirection:'column', gap:5}}>
            <div style={{fontSize:11, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em'}}>Leverage</div>
            <div style={{display:'flex', gap:4}}>
              {['1x','2x','3x','5x','10x'].map(l=>(
                <button key={l} className={l==='2x'?'tv-btn primary':'tv-btn'} style={{padding:'5px 10px', fontSize:12.5}}>{l}</button>
              ))}
            </div>
          </div>
          {[['Hedge Entry Price','2000'],['Funding Rate APR (%)','10']].map(([l,v])=>(
            <div key={l} style={{display:'flex', flexDirection:'column', gap:5}}>
              <div style={{fontSize:11, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em'}}>{l}</div>
              <div style={{background:TV.panel2, border:`1px solid ${TV.line}`, borderRadius:7, padding:'7px 12px', fontSize:13, color:TV.text, width:110}}>{v}</div>
            </div>
          ))}
          <button className="tv-btn primary" style={{padding:'8px 18px', fontSize:13, alignSelf:'end'}}>Update</button>
        </div>
        {/* main layout */}
        <div style={{display:'grid', gridTemplateColumns:'1fr 200px', gap:18}}>
          <div>
            {/* table */}
            <div style={{borderRadius:10, border:`1px solid ${TV.line}`, overflow:'hidden', marginBottom:16}}>
              <div style={{display:'grid', gridTemplateColumns:H_COLS, gap:10, padding:'9px 14px',
                  background:TV.panel, fontSize:11, fontWeight:700, color:TV.text3, letterSpacing:'.05em', textTransform:'uppercase'}}>
                <span>Price Point</span><span style={{textAlign:'right'}}>WETH Price</span>
                <span style={{textAlign:'right'}}>LP P&L</span><span style={{textAlign:'right'}}>Hedge P&L</span>
                <span style={{textAlign:'right'}}>Net P&L</span><span style={{textAlign:'right'}}>Net %</span>
              </div>
              {HEDGE_ROWS.map(([pt,wp,lp,lpc,hp,hpc,np,npc,pct],i)=>(
                <div key={i} style={{display:'grid', gridTemplateColumns:H_COLS, gap:10, padding:'10px 14px',
                    borderTop:`1px solid ${TV.lineSoft}`, alignItems:'center', fontSize:12.5,
                    background:i===3?`${TV.adapt}12`:'transparent'}}>
                  <span style={{color:TV.text2, fontSize:12}}>{pt}</span>
                  <span className="tv-num" style={{textAlign:'right', color:TV.text}}>{wp}</span>
                  <span className="tv-num" style={{textAlign:'right', color:lpc, fontWeight:600}}>{lp}</span>
                  <span className="tv-num" style={{textAlign:'right', color:hpc, fontWeight:600}}>{hp}</span>
                  <span className="tv-num" style={{textAlign:'right', color:npc, fontWeight:700}}>{np}</span>
                  <span className="tv-num" style={{textAlign:'right', color:npc}}>{pct}</span>
                </div>
              ))}
            </div>
            {/* chart */}
            <div style={{fontSize:12, textAlign:'center', marginBottom:6, color:TV.text}}>LP + Hedge P&L</div>
            <div style={{display:'flex', gap:12, justifyContent:'center', marginBottom:6}}>
              {[['LP P&L',TV.adapt],['Hedge P&L',TV.warn],['Net P&L',TV.ok]].map(([l,c])=>(
                <span key={l} style={{display:'inline-flex',alignItems:'center',gap:5,fontSize:11,color:TV.text3}}>
                  <svg width="18" height="8"><line x1="0" y1="4" x2="18" y2="4" stroke={c} strokeWidth="2"/></svg>{l}
                </span>
              ))}
            </div>
            <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} style={{display:'block'}}>
              <line x1={pL} x2={W-pR} y1={pT+(H-pT-pB)*(1100/(1100+1600))} y2={pT+(H-pT-pB)*(1100/(1100+1600))}
                    stroke={TV.lineSoft} strokeWidth="1"/>
              <MDLine pts={lp_pnl}   minV={minV} maxV={maxV} W={W} H={H} pL={pL} pR={pR} pT={pT} pB={pB} color={TV.adapt} width="2"/>
              <MDLine pts={hedge_pnl} minV={minV} maxV={maxV} W={W} H={H} pL={pL} pR={pR} pT={pT} pB={pB} color={TV.warn} width="1.5" dash="5 4"/>
              <MDLine pts={net_pnl}   minV={minV} maxV={maxV} W={W} H={H} pL={pL} pR={pR} pT={pT} pB={pB} color={TV.ok} width="2"/>
              {[0,5,10,15,19].map(i=>(
                <text key={i} x={pL+(i/(prices.length-1))*(W-pL-pR)} y={H-6} fontSize="9"
                    fill={TV.text4} textAnchor="middle" fontFamily={TV.font}>{prices[i]}</text>
              ))}
              {[-1500,-1000,-500,0,500,1000].map(v=>{
                const y=pT+(H-pT-pB)-(v-minV)/(maxV-minV)*(H-pT-pB);
                return <text key={v} x={pL-4} y={y+3} fontSize="9" fill={TV.text4} textAnchor="end" fontFamily={TV.font}>${v}</text>;
              })}
            </svg>
          </div>
          {/* params panel */}
          <div style={{display:'flex', flexDirection:'column', gap:10}}>
            {[
              {title:'Hedge Parameters', color:TV.adapt, rows:[['Hedge','50% of capital'],['Short size','$5,000'],['WETH shorted','2.500'],['Leverage','2x'],['Hedge entry','$2,000']]},
              {title:'Required Margin', color:TV.ok, big:'$2,500'},
              {title:'💀 Liquidation Price', color:TV.fail, big:'$3,000', sub:'50.0% above hedge entry'},
              {title:'⚠ Stop Loss (2% capital)', color:TV.warn, big:'$2,171', sub:'8.5% above hedge entry'},
              {title:'Costs & Income', color:TV.text2, rows:[['LP fees/day','+$16.44',TV.ok],['Funding/day','-$1.37',TV.fail],['Net/day','+$15',TV.ok],['Net/month','+$452',TV.ok]]},
            ].map(sec=>(
              <div key={sec.title} style={{padding:12, borderRadius:9, border:`1px solid ${TV.line}`, background:TV.panel2}}>
                <div style={{fontSize:11, fontWeight:700, color:sec.color, textTransform:'uppercase', letterSpacing:'.05em', marginBottom:6}}>{sec.title}</div>
                {sec.big && <div className="tv-num" style={{fontSize:20, fontWeight:700, color:sec.color}}>{sec.big}</div>}
                {sec.sub && <div style={{fontSize:11, color:TV.text3}}>{sec.sub}</div>}
                {sec.rows && sec.rows.map(([k,v,vc])=>(
                  <div key={k} style={{display:'flex', justifyContent:'space-between', fontSize:12, padding:'2px 0', borderBottom:`1px solid ${TV.lineSoft}`}}>
                    <span style={{color:TV.text3}}>{k}</span>
                    <span className="tv-num" style={{color:vc||TV.text, fontWeight:600}}>{v}</span>
                  </div>
                ))}
              </div>
            ))}
            <div style={{padding:14, borderRadius:9, border:`1px solid ${TV.ok}55`, background:TV.okSoft, textAlign:'center'}}>
              <div style={{fontSize:10.5, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em', marginBottom:4}}>Net APR (fees − funding)</div>
              <div className="tv-num" style={{fontSize:24, fontWeight:800, color:TV.ok}}>55.0%</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

// ── main screen ───────────────────────────────────────────────
const LPToolsHF = ({tool = 'optimizer'}) => {
  const toolLabel = tool==='optimizer'?'LP Optimizer': tool==='ilcalc'?'IL Calculator':'Hedge Calculator';
  return (
    <div className="tv-frame" style={{display:'flex', flexDirection:'column'}}>
      <TVNav active="Portfolio"/>
      <PFSubNav active="LP Tools"/>
      <div style={{padding:'20px 36px 6px', flexShrink:0}}>
        <LPToolSubNav active={toolLabel}/>
      </div>
      <div style={{flex:1, padding:'16px 36px 32px', overflowY:'auto', minHeight:0}}>
        {tool==='optimizer' && <LPOptimizerTool/>}
        {tool==='ilcalc'    && <ILCalculatorTool/>}
        {tool==='hedge'     && <HedgeCalculatorTool/>}
      </div>
    </div>
  );
};
