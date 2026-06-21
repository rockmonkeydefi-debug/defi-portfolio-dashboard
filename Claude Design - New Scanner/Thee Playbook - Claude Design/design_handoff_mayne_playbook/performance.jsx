// performance.jsx — Performance tab
// Reuses TV.*, .tv-*, PF_CARD/TITLE/SUB/METRIC, TVNav (global).

// ── chart helpers ──────────────────────────────────────────────
const X_LABELS = ['May 25\n23:00','May 26\n11:00','May 26\n23:00','May 27\n11:00',
  'May 27\n23:00','May 28\n11:00','May 28\n23:00','May 29\n11:00','May 29\n23:00','May 30\n11:00'];
const N = X_LABELS.length;

// portfolio series data
const S_TOTAL  = [47800,47900,48200,48400,48700,49100,49800,49500,48600,49206];
const S_TOKENS = [43000,43200,43600,43900,44200,44700,45100,44800,43900,44400];
const S_LP     = [6800,6820,6900,6850,6900,6950,6800,6750,6700,6780];
const S_HEDGE  = [10,15,12,8,20,30,50,40,25,15];
const S_LEND   = [280,290,295,300,310,320,330,340,320,330];

// active positions + fees
const S_LPHV   = [7200,7190,7170,7100,7050,7010,6980,6950,6900,6820];
const S_FEES   = [2,4,6,8,12,16,20,22,26,30];

const chartPts = (vals, minV, maxV, W, H, padL, padR, padT, padB) => {
  const iW = W - padL - padR, iH = H - padT - padB;
  const rng = maxV - minV || 1;
  return vals.map((v, i) => [padL + (i / (vals.length - 1)) * iW, padT + iH - ((v - minV) / rng) * iH]);
};
const pts2poly = pts => pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
const pts2path = (pts, H, padB) => {
  const lastX = pts[pts.length - 1][0], firstX = pts[0][0];
  const base = H - padB;
  return `M ${pts.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join(' L ')} L ${lastX.toFixed(1)} ${base} L ${firstX.toFixed(1)} ${base} Z`;
};

const GridLines = ({count, W, H, padL, padR, padT, padB, minV, maxV, prefix = '$', right = false}) => {
  const steps = Array.from({length: count + 1}, (_, i) => minV + ((maxV - minV) / count) * i);
  const iH = H - padT - padB;
  return (
    <>
      {steps.map(v => {
        const y = padT + iH - ((v - minV) / (maxV - minV)) * iH;
        const label = prefix === '$'
          ? v >= 1000 ? `$${(v / 1000).toFixed(0)}k` : `$${v}`
          : `$${v}`;
        return (
          <g key={v}>
            <line x1={padL} x2={W - padR} y1={y} y2={y}
                stroke={TV.lineSoft} strokeWidth="1"/>
            {right
              ? <text x={W - padR + 6} y={y + 4} fontSize="9" fill={TV.text4} fontFamily={TV.font}>{label}</text>
              : <text x={padL - 4} y={y + 4} fontSize="9" fill={TV.text4} textAnchor="end" fontFamily={TV.font}>{label}</text>}
          </g>
        );
      })}
    </>
  );
};

const XLabels = ({labels, W, H, padL, padR, padB}) => {
  const iW = W - padL - padR;
  return (
    <>
      {labels.map((lbl, i) => {
        const x = padL + (i / (labels.length - 1)) * iW;
        const lines = lbl.split('\n');
        return (
          <g key={i}>
            {lines.map((l, li) => (
              <text key={li} x={x} y={H - padB + 14 + li * 12} fontSize="9" fill={TV.text4}
                  textAnchor="middle" fontFamily={TV.font}>{l}</text>
            ))}
          </g>
        );
      })}
    </>
  );
};

const LegendItem = ({color, dash, label}) => (
  <span style={{display:'inline-flex', alignItems:'center', gap:5, fontSize:11, color:TV.text3}}>
    <svg width="22" height="10"><line x1="0" y1="5" x2="22" y2="5"
        stroke={color} strokeWidth={dash?'1.5':'2'} strokeDasharray={dash?'4 3':null}/></svg>
    {label}
  </span>
);

// ── Total Portfolio Value chart ────────────────────────────────
const PortfolioChart = () => {
  const W = 640, H = 280, pL = 58, pR = 14, pT = 16, pB = 44;
  const minV = 0, maxV = 60000;
  const series = [
    {d: S_TOTAL, c: TV.text,    w: '2', label:'Total Portfolio'},
    {d: S_TOKENS, c: '#4db6e8', w: '1.5', label:'Tokens'},
    {d: S_LP,    c: '#9b79f5',  w: '1.5', label:'LP Positions'},
    {d: S_HEDGE, c: '#f97316',  w: '1.5', label:'Hedge PnL'},
    {d: S_LEND,  c: TV.ok,      w: '1.5', label:'Lending Net'},
  ];
  return (
    <div style={{display:'flex', flexDirection:'column', gap:8}}>
      <div style={{fontSize:12.5, fontWeight:600, color:TV.text, textAlign:'center'}}>Total Portfolio Value</div>
      <div style={{display:'flex', flexWrap:'wrap', gap:'6px 14px', justifyContent:'center'}}>
        {series.map(s => <LegendItem key={s.label} color={s.c} label={s.label}/>)}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} style={{display:'block'}}>
        <GridLines count={6} W={W} H={H} padL={pL} padR={pR} padT={pT} padB={pB}
            minV={minV} maxV={maxV} prefix="$"/>
        {series.map(s => {
          const pts = chartPts(s.d, minV, maxV, W, H, pL, pR, pT, pB);
          return <polyline key={s.label} points={pts2poly(pts)} fill="none"
              stroke={s.c} strokeWidth={s.w} strokeLinejoin="round" strokeLinecap="round"/>;
        })}
        <XLabels labels={X_LABELS} W={W} H={H} padL={pL} padR={pR} padB={pB}/>
      </svg>
    </div>
  );
};

// ── Active Positions & Accrued Fees chart (dual-axis) ─────────
const ActivePosChart = () => {
  const W = 620, H = 280, pL = 58, pR = 50, pT = 16, pB = 44;
  const minL = 5400, maxL = 7400;
  const minR = 0,    maxR = 35;
  const ptsLPHV = chartPts(S_LPHV, minL, maxL, W, H, pL, pR, pT, pB);
  const ptsFees = chartPts(S_FEES, minR, maxR, W, H, pL, pR, pT, pB);
  const feesPath = pts2path(ptsFees, H, pB);
  return (
    <div style={{display:'flex', flexDirection:'column', gap:8}}>
      <div style={{fontSize:12.5, fontWeight:600, color:TV.text, textAlign:'center'}}>Active Positions &amp; Fees</div>
      <div style={{display:'flex', gap:14, justifyContent:'center'}}>
        <LegendItem color="#9b79f5" label="LP + Hedge Value"/>
        <LegendItem color={TV.ok}  label="Total Accrued Fees"/>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} style={{display:'block'}}>
        <GridLines count={5} W={W} H={H} padL={pL} padR={pR} padT={pT} padB={pB}
            minV={minL} maxV={maxL} prefix="$" right={false}/>
        {/* fees area (right axis) */}
        <path d={feesPath} fill={TV.ok} fillOpacity="0.25"/>
        <polyline points={pts2poly(ptsFees)} fill="none"
            stroke={TV.ok} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"/>
        {/* LP+Hedge line (left axis) */}
        <polyline points={pts2poly(ptsLPHV)} fill="none"
            stroke="#9b79f5" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"/>
        {/* right-axis labels */}
        <GridLines count={5} W={W} H={H} padL={pL} padR={pR} padT={pT} padB={pB}
            minV={minR} maxV={maxR} prefix="$" right={true}/>
        <XLabels labels={X_LABELS} W={W} H={H} padL={pL} padR={pR} padB={pB}/>
        {/* axis labels */}
        <text x={10} y={H/2} fontSize="9" fill={TV.text4} textAnchor="middle"
            transform={`rotate(-90, 10, ${H/2})`} fontFamily={TV.font}>Position Value</text>
        <text x={W-6} y={H/2} fontSize="9" fill={TV.text4} textAnchor="middle"
            transform={`rotate(90, ${W-6}, ${H/2})`} fontFamily={TV.font}>Accrued Fees</text>
      </svg>
    </div>
  );
};

// ── empty-state card ───────────────────────────────────────────
const EmptyCard = ({title}) => (
  <div style={PF_CARD}>
    <div style={{...PF_TITLE, color: TV.adapt, marginBottom:12}}>▤ {title}</div>
    <div style={{padding:'22px 0', textAlign:'center', color:TV.text3, fontSize:13}}>No {title.toLowerCase()} yet</div>
  </div>
);

// ── main ───────────────────────────────────────────────────────
const PerformanceHF = () => (
  <div className="tv-frame" style={{display:'flex', flexDirection:'column'}}>
    <TVNav active="Performance"/>

    <div style={{flex:1, padding:'24px 36px 32px', display:'flex', flexDirection:'column', gap:18,
        overflowY:'auto', minHeight:0}}>

      {/* view switcher + range */}
      <div style={{display:'flex', flexDirection:'column', gap:14, flexShrink:0}}>
        {/* top buttons (Live | Spot P&L | Performance) */}
        <div style={{display:'flex', alignItems:'center', gap:10}}>
          {['Live','Spot P&L','Performance'].map(v => (
            <button key={v} className={v==='Performance'?'tv-btn primary':'tv-btn'}
                style={{padding:'7px 16px', fontSize:13}}>
              {v==='Live'?'↻ ':''}
              {v==='Spot P&L'?'▦ ':''}
              {v==='Performance'?'↗ ':''}
              {v}
            </button>
          ))}
          <div style={{flex:1}}/>
          <button className="tv-btn ghost" style={{padding:'7px 12px', fontSize:14}}>👁</button>
        </div>

        {/* range selector */}
        <div style={{display:'flex', alignItems:'center', gap:10, flexWrap:'wrap'}}>
          <span style={{fontSize:13, fontWeight:600, color:TV.text3}}>RANGE:</span>
          {['24H','7D','30D','1Y','All'].map(r => (
            <button key={r} className={r==='7D'?'tv-btn primary':'tv-btn'}
                style={{padding:'5px 12px', fontSize:13, minWidth:44}}>{r}</button>
          ))}
          <span style={{fontSize:13, color:TV.text3, marginLeft:6}}>CUSTOM:</span>
          <div style={{background:TV.panel2, border:`1px solid ${TV.line}`, borderRadius:7, padding:'5px 11px',
              fontSize:13, color:TV.text4, fontFamily:TV.font, width:130}}>mm/dd/yyyy</div>
          <span style={{fontSize:13, color:TV.text3}}>to</span>
          <div style={{background:TV.panel2, border:`1px solid ${TV.line}`, borderRadius:7, padding:'5px 11px',
              fontSize:13, color:TV.text4, fontFamily:TV.font, width:130}}>mm/dd/yyyy</div>
          <button className="tv-btn primary" style={{padding:'5px 14px', fontSize:13}}>Apply</button>
        </div>
      </div>

      {/* KPI strip */}
      <div style={{display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:14, flexShrink:0}}>
        {[
          ['Current Value', '$49,206', '', TV.text],
          ['Period Start',  '$47,927', '', TV.text],
          ['Change',        '+$1,279', '', TV.ok],
          ['Change %',      '+2.67%',  '', TV.ok],
        ].map(([lbl,val,,col]) => (
          <div key={lbl} style={{...PF_METRIC, display:'flex', flexDirection:'column', gap:5}}>
            <div style={{fontSize:12, color:TV.text3}}>{lbl}</div>
            <div className="tv-num" style={{fontSize:24, fontWeight:700, color:col, letterSpacing:'-.3px'}}>{val}</div>
          </div>
        ))}
      </div>

      {/* charts */}
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:18, flexShrink:0}}>
        <div style={PF_CARD}>
          <div style={{...PF_TITLE, marginBottom:14}}>Total Portfolio Value</div>
          <PortfolioChart/>
        </div>
        <div style={PF_CARD}>
          <div style={{...PF_TITLE, marginBottom:14}}>Active Positions &amp; Accrued Fees</div>
          <ActivePosChart/>
        </div>
      </div>

      {/* closed positions */}
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:18, flexShrink:0}}>
        <EmptyCard title="Closed LP Positions"/>
        <EmptyCard title="Closed Hedges"/>
      </div>
    </div>
  </div>
);
