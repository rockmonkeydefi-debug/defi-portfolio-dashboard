// hifi.jsx — dark hi-fi screens promoted from wireframe winners
// Matches the design language of ValidatorC (validator.jsx).
// Uses the same TV.* tokens and .tv-* utility classes — assumes validator.jsx
// loaded first so those styles are present.

// shared HTF→LTF pair display for table cells, journal rows, scanner cards
const TfPair = ({htf, ltf, layout = 'inline'}) => {
  const TV = React.useContext(ThemeCtx);
  if (layout === 'stacked') {
    return (
      <div style={{display: 'flex', flexDirection: 'column', gap: 1, alignItems: 'flex-start',
          fontFamily: TV.font, fontVariantNumeric: 'tabular-nums', fontSize: 10, lineHeight: 1.2}}>
        <span style={{color: TV.adapt, fontWeight: 600}}>{htf}</span>
        <span style={{color: TV.ok, fontWeight: 600}}>{ltf}</span>
      </div>
    );
  }
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      fontFamily: TV.font, fontVariantNumeric: 'tabular-nums',
      fontSize: 11, fontWeight: 600,
    }}>
      <span style={{color: TV.adapt, padding: '1px 5px', borderRadius: 3, background: TV.adaptSoft,
          border: `1px solid rgba(47,180,232,.35)`, minWidth: 24, textAlign: 'center'}}>{htf}</span>
      <span style={{color: TV.text4}}>→</span>
      <span style={{color: TV.ok, padding: '1px 5px', borderRadius: 3, background: TV.okSoft,
          border: `1px solid rgba(79,221,142,.35)`, minWidth: 24, textAlign: 'center'}}>{ltf}</span>
    </span>
  );
};

// shared candlestick chart for dark hi-fi
const HFChart = ({h = 240, ticker = 'ES', tf = '4H', last = '5,742.25', change = '+1.2%', up = true, annotate = null}) => {
  const TV = React.useContext(ThemeCtx);
  return (
  <div className="tv-card" style={{padding: 14, display: 'flex', flexDirection: 'column', overflow: 'hidden'}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10}}>
      <span style={{fontSize: 13, fontWeight: 600, color: TV.text}}>{ticker}</span>
      <span style={{fontSize: 11, color: TV.text3, padding: '2px 6px', borderRadius: 3, border: `1px solid ${TV.line}`}}>{tf}</span>
      <span className="tv-num" style={{fontSize: 13, color: TV.text2, marginLeft: 'auto'}}>{last}</span>
      <span className="tv-num" style={{fontSize: 12, color: up ? TV.ok : TV.fail, fontWeight: 600}}>{up ? '▲' : '▼'} {change}</span>
    </div>
    <div style={{flex: 1, height: h - 60, display: 'flex', alignItems: 'flex-end', justifyContent: 'space-around',
        gap: 3, padding: '6px 4px', position: 'relative',
        background: `linear-gradient(${TV.lineSoft} 1px, transparent 1px) 0 0 / 100% 25%`,
        backgroundColor: 'rgba(255,255,255,0.005)',
        borderRadius: 4, border: `1px solid ${TV.lineSoft}`}}>
      {[18,28,22,38,30,46,40,55,48,62,58,70,64,52,60,72,66,78,70,84,76].map((v,i) => {
        const u = i % 3 !== 0;
        return (
          <div key={i} style={{display: 'flex', flexDirection: 'column', alignItems: 'center', height: '100%', justifyContent: 'flex-end'}}>
            <div style={{width: 1, height: v * 0.45, background: u ? TV.ok : TV.accent, opacity: 0.55}}/>
            <div style={{width: 8, height: v * 0.7, background: u ? TV.ok : TV.accent, borderRadius: 1}}/>
            <div style={{width: 1, height: v * 0.25, background: u ? TV.ok : TV.accent, opacity: 0.55}}/>
          </div>
        );
      })}
      {annotate && (
        <div style={{position: 'absolute', left: '22%', top: '60%',
            border: `1.5px dashed ${TV.accent}`, borderRadius: 4,
            padding: '4px 8px', fontSize: 11, color: TV.accent, fontWeight: 600,
            background: TV.accentSoft, pointerEvents: 'none'}}>
          {annotate}
        </div>
      )}
    </div>
  </div>
);
};

const HFSparkline = ({trend = 'up', w = 100, h = 28}) => {
  const TV = React.useContext(ThemeCtx);
  return (
  <svg viewBox="0 0 100 28" width={w} height={h} style={{display: 'block'}}>
    <polyline
      points={trend === 'up' ? "0,22 12,18 24,20 36,14 48,16 60,11 72,13 84,7 100,4"
        : trend === 'down' ? "0,6 12,9 24,7 36,12 48,10 60,15 72,13 84,18 100,22"
        : "0,14 12,11 24,15 36,12 48,14 60,11 72,15 84,13 100,12"}
      fill="none"
      stroke={trend === 'up' ? TV.ok : trend === 'down' ? TV.fail : TV.text3}
      strokeWidth="1.5"
    />
  </svg>
);
};

// =============================================================
// 1A · Dashboard (dark hi-fi)
// Performance-led: KPI strip + equity · screener · open trades · slim quiz bar
// =============================================================

// compact equity sparkline for the performance strip
const EquityMini = ({pts, w = 150, h = 46}) => {
  const TV = React.useContext(ThemeCtx);
  const min = Math.min(...pts, 0), max = Math.max(...pts);
  const range = (max - min) || 1;
  const X = i => (i / (pts.length - 1)) * w;
  const Y = v => h - ((v - min) / range) * h;
  const d = pts.map((v, i) => `${i === 0 ? 'M' : 'L'} ${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(' ');
  const last = pts.length - 1;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} style={{display: 'block'}} preserveAspectRatio="none">
      <line x1="0" x2={w} y1={Y(0)} y2={Y(0)} stroke={TV.line} strokeWidth="1" strokeDasharray="2 3"/>
      <path d={`${d} L ${w} ${h} L 0 ${h} Z`} fill={TV.accent} fillOpacity="0.08"/>
      <path d={d} fill="none" stroke={TV.accent} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round"/>
      <circle cx={X(last)} cy={Y(pts[last])} r="2.6" fill={TV.accent}/>
    </svg>
  );
};

// one open position row — entry/now and a stop→target progress track
const OpenTradeRow = ({t, dir, htf, ltf, entry, now, stop, target, ur, urUp, entryPct, nowPct, trend}) => {
  const TV = React.useContext(ThemeCtx);
  return (
  <div style={{padding: 16, borderRadius: 10, border: `1px solid ${TV.line}`,
      background: TV.panel2, display: 'flex', flexDirection: 'column', gap: 11}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
      <span className="tv-num" style={{fontSize: 16, fontWeight: 700, color: TV.text}}>{t}</span>
      <span className="tv-chip" style={{fontSize: 11, padding: '1px 7px',
          color: dir === 'long' ? TV.ok : TV.fail,
          borderColor: dir === 'long' ? 'rgba(63,178,127,.35)' : 'rgba(217,83,79,.35)',
          background: dir === 'long' ? TV.okSoft : TV.failSoft}}>
        {dir === 'long' ? '▲ long' : '▼ short'}
      </span>
      <TfPair htf={htf} ltf={ltf}/>
      <div style={{flex: 1}}/>
      <span className="tv-num" style={{fontSize: 16, fontWeight: 700, color: urUp ? TV.ok : TV.fail}}>{ur}</span>
    </div>
    <div style={{display: 'flex', alignItems: 'center', gap: 12}}>
      <HFSparkline trend={trend} w={72} h={20}/>
      <div style={{display: 'flex', gap: 14, fontSize: 12.5}}>
        <span style={{color: TV.text3}}>entry <span className="tv-num" style={{color: TV.text}}>{entry}</span></span>
        <span style={{color: TV.text3}}>now <span className="tv-num" style={{color: TV.text, fontWeight: 700}}>{now}</span></span>
      </div>
    </div>
    {/* stop → target track */}
    <div style={{position: 'relative', height: 7, borderRadius: 3.5, background: TV.bg, marginTop: 2}}>
      <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: `${entryPct}%`,
          background: TV.failSoft, borderRadius: '3.5px 0 0 3.5px'}}/>
      <div style={{position: 'absolute', left: `${entryPct}%`, right: 0, top: 0, bottom: 0,
          background: TV.okSoft, borderRadius: '0 3.5px 3.5px 0'}}/>
      {/* entry tick */}
      <div style={{position: 'absolute', left: `${entryPct}%`, top: -2, bottom: -2, width: 1.5,
          background: TV.text2, transform: 'translateX(-50%)'}}/>
      {/* current marker */}
      <div style={{position: 'absolute', left: `${nowPct}%`, top: '50%',
          width: 10, height: 10, borderRadius: '50%', background: TV.text,
          border: `2px solid ${TV.panel2}`, transform: 'translate(-50%,-50%)',
          boxShadow: `0 0 0 1px ${TV.text4}`}}/>
    </div>
    <div style={{display: 'flex', justifyContent: 'space-between', fontSize: 11.5, color: TV.text3}}>
      <span className="tv-num">stop {stop}</span>
      <span className="tv-num">target {target}</span>
    </div>
  </div>
);
};

// Reference-inspired type & spacing system (DeFi-Buddy feel):
//   · card title  → accent, 17px / 700, sentence-case (not tiny uppercase)
//   · big metric  → white, 32px / 700
//   · sub-label   → muted, 13.5px
//   · cards       → 24px padding, 14px radius, 20px gaps · page allowed to scroll
const DCARD = {background: TV.panel, border: `1px solid ${TV.line}`, borderRadius: 14, padding: 24};
const DTITLE = {fontSize: 17, fontWeight: 700, color: TV.accent, letterSpacing: '-.1px'};
const DSUB = {fontSize: 13.5, color: TV.text3};

// quiz availability indicator — sits next to the page title.
// quizzes are launched from the top menu; this only signals state.
const QuizStatusPill = ({status = 'ready'}) => {
  const TV = React.useContext(ThemeCtx);
  const map = {
    ready:   {label: 'Quiz Ready',   color: TV.ok},
    pending: {label: 'Quiz Pending', color: TV.fail},
    cooking: {label: 'Quiz Cooking', color: TV.warn},
  };
  const s = map[status] || map.ready;
  return (
    <span style={{display: 'inline-flex', alignItems: 'center', gap: 8, padding: '6px 12px',
        borderRadius: 999, border: `1px solid ${TV.line}`, background: TV.panel2,
        fontSize: 13, fontWeight: 600, color: TV.text2, whiteSpace: 'nowrap'}}>
      <span style={{width: 9, height: 9, borderRadius: '50%', background: s.color,
          boxShadow: `0 0 0 3px ${s.color}22`}}/>
      {s.label}
    </span>
  );
};

// smaller perf-card metric style (~20% down from the section metric scale)
const PCARD = {background: TV.panel, border: `1px solid ${TV.line}`, borderRadius: 12, padding: 18};
const PTITLE = {fontSize: 14.5, fontWeight: 700, color: TV.accent, letterSpacing: '-.1px'};

const DashHF = () => {
  const TV = React.useContext(ThemeCtx);
  const DCARD = {background: TV.panel, border: `1px solid ${TV.line}`, borderRadius: 14, padding: 20};
  const DTITLE = {fontSize: 15, fontWeight: 700, color: TV.accent, letterSpacing: '-.1px', marginBottom: 14};
  const DSUB = {fontSize: 13, color: TV.text3};
  const KCARD = {background: TV.panel, border: `1px solid ${TV.line}`, borderRadius: 12, padding: '14px 18px',
      display: 'flex', flexDirection: 'column', gap: 4};
  return (
  <div className="tv-frame" style={{display: 'flex', flexDirection: 'column'}}>
    <TVNav active="Dashboard"/>

    <div style={{flex: 1, padding: '20px 28px 24px', display: 'flex', flexDirection: 'column', gap: 16,
        overflowY: 'auto', minHeight: 0}}>

      {/* ===== HERO ROW ===== */}
      <div style={{display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16, flexShrink: 0}}>

        {/* Left: total portfolio value */}
        <div style={{...DCARD, display: 'flex', flexDirection: 'column', gap: 0}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6}}>
            <span style={{fontSize: 13, fontWeight: 600, color: TV.text3, textTransform: 'uppercase', letterSpacing: '.06em'}}>Total Portfolio Value</span>
            <span style={{fontSize: 12, color: TV.text4}}>Updated just now · 30 May 2026</span>
            <div style={{flex: 1}}/>
            <button className="tv-btn" style={{padding: '5px 10px', fontSize: 12}}>↻ Refresh</button>
            <QuizStatusPill status="ready"/>
          </div>
          <div style={{display: 'flex', alignItems: 'flex-end', gap: 18, marginBottom: 10}}>
            <div className="tv-num" style={{fontSize: 52, fontWeight: 800, color: TV.text, letterSpacing: '-2px', lineHeight: 1}}>$456,230</div>
            <div style={{paddingBottom: 6, display: 'flex', flexDirection: 'column', gap: 2}}>
              <span className="tv-num" style={{fontSize: 18, fontWeight: 700, color: TV.ok}}>+$8,340</span>
              <span className="tv-num" style={{fontSize: 14, color: TV.ok}}>+1.86% · 24h</span>
            </div>
          </div>
          <EquityMini w={540} h={52} pts={[0,8,5,14,22,18,28,38,32,44,56,48,64,68,74,70,80,92,86,98,108,102,116,112,122,118,128,124]}/>
          {/* portfolio breakdown pills */}
          <div style={{display: 'flex', gap: 10, marginTop: 12, flexWrap: 'wrap'}}>
            {[
              ['Spot',     '$182,400', TV.adapt],
              ['DeFi LP',  '$128,600', TV.ok],
              ['Lending',  '$94,200',  TV.warn],
              ['Cash',     '$51,030',  TV.text3],
            ].map(([l,v,c]) => (
              <div key={l} style={{display: 'flex', alignItems: 'center', gap: 7, padding: '5px 12px',
                  borderRadius: 8, background: TV.panel2, border: `1px solid ${TV.lineSoft}`}}>
                <span style={{width: 7, height: 7, borderRadius: '50%', background: c}}/>
                <span style={{fontSize: 12, color: TV.text3}}>{l}</span>
                <span className="tv-num" style={{fontSize: 13, fontWeight: 700, color: TV.text}}>{v}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right: macro + DeFi health */}
        <div style={{display: 'flex', flexDirection: 'column', gap: 14}}>
          {/* BTC macro zone */}
          <div style={{...DCARD, flex: 1, display: 'flex', flexDirection: 'column', gap: 8}}>
            <div style={{fontSize: 12, fontWeight: 700, color: TV.text3, textTransform: 'uppercase', letterSpacing: '.06em'}}>BTC Macro Zone</div>
            <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
              <div style={{flex: 1, height: 8, borderRadius: 4, background: `linear-gradient(to right, ${TV.fail}, ${TV.warn}, ${TV.ok}, ${TV.adapt})`, position: 'relative'}}>
                {/* marker at ~68% = Value Window */}
                <div style={{position: 'absolute', left: '68%', top: '50%', width: 14, height: 14, borderRadius: '50%',
                    background: TV.text, border: `2.5px solid ${TV.ok}`, transform: 'translate(-50%,-50%)',
                    boxShadow: `0 0 0 3px ${TV.ok}44`}}/>
              </div>
            </div>
            <div style={{display: 'flex', justifyContent: 'space-between', fontSize: 10, color: TV.text4}}>
              <span>Bear</span><span>Accum.</span><span>Value Window</span><span>Bull</span><span>Euphoria</span>
            </div>
            <div style={{display: 'flex', alignItems: 'center', gap: 8, marginTop: 4}}>
              <span style={{fontSize: 20, fontWeight: 800, color: TV.ok}}>Value Window</span>
              <span className="tv-chip" style={{fontSize: 11, color: TV.ok, borderColor: 'rgba(79,221,142,.4)', background: TV.okSoft}}>Favorable</span>
            </div>
            <div style={{fontSize: 12, color: TV.text3}}>PI Cycle · MVRV Z · NUPL · Puell Multiple</div>
          </div>
          {/* LP + Lending health */}
          <div style={{...DCARD, display: 'flex', gap: 16}}>
            {[
              ['LP Health', '3 positions', 'All in range', TV.ok],
              ['Lending',   'HF 2.41',    'Safe zone',    TV.ok],
            ].map(([title, val, sub, col]) => (
              <div key={title} style={{flex: 1, display: 'flex', flexDirection: 'column', gap: 3}}>
                <div style={{fontSize: 11, fontWeight: 700, color: TV.text3, textTransform: 'uppercase', letterSpacing: '.05em'}}>{title}</div>
                <div className="tv-num" style={{fontSize: 17, fontWeight: 700, color: col}}>{val}</div>
                <div style={{fontSize: 12, color: TV.text3}}>{sub}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ===== AI BRIEF STRIP ===== */}
      <div style={{flexShrink: 0, padding: '11px 18px', borderRadius: 12,
          border: `1px solid ${TV.accentLine}`, background: TV.accentSoft,
          display: 'flex', alignItems: 'center', gap: 14}}>
        <span style={{fontSize: 15}}>⚡</span>
        <span style={{fontSize: 13, fontWeight: 700, color: TV.accent}}>AI Brief · Today</span>
        <span className="tv-chip" style={{fontSize: 11, color: TV.fail, borderColor: 'rgba(255,138,138,.4)', background: TV.failSoft}}>3 alerts</span>
        <div style={{width: 1, height: 18, background: TV.accentLine}}/>
        <span style={{fontSize: 13.5, color: TV.text, flex: 1}}>
          <span style={{fontWeight: 600}}>Top rec:</span> Rotate idle USDC into ETH/USDC LP on Base (0.05% tier) — Fee APR 61% · BTC in Value Window · Macro: neutral/risk-on
        </span>
        <button className="tv-btn" style={{padding: '7px 14px', fontSize: 13, flexShrink: 0}}>View full brief →</button>
      </div>

      {/* ===== MAIN 2-COL: SCREENER (left) · TRADES + P&L (right) ===== */}
      <div style={{display: 'grid', gridTemplateColumns: '1.55fr 1fr', gap: 16, flexShrink: 0, alignItems: 'start'}}>

        {/* SCREENER */}
        <div style={DCARD}>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, flexWrap: 'wrap'}}>
            <span style={DTITLE}>Screener</span>
            <span className="tv-chip accent" style={{fontSize: 11, marginBottom: 14}}><span className="tv-dot"/>2 active</span>
            <span className="tv-chip" style={{fontSize: 11, marginBottom: 14}}>3 forming</span>
            <div style={{flex: 1}}/>
            <span style={{...DSUB, marginBottom: 14}}>scan · 4m ago</span>
            <button className="tv-btn" style={{padding: '6px 11px', fontSize: 12, marginBottom: 14}}>Open scanner →</button>
          </div>

          <div style={{display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 12}}>
            {[
              ['BTC',  'active',  'OB tap',      '71,840', '+1.2%', 'up',   '4H', '15m'],
              ['TSLA', 'active',  'sweep + BOS', '238.40', '+0.6%', 'up',   'D',  '1H'],
              ['ES',   'forming', 'FVG fill',    '5,742',  '+0.4%', 'up',   'D',  '1H'],
              ['ETH',  'forming', 'OB retest',   '3,612',  '+0.9%', 'up',   '4H', '15m'],
              ['AAPL', 'forming', 'sweep',        '186.20', '+0.1%', 'flat', 'D',  '1H'],
              ['GOLD', 'watching','approach',     '2,348',  '+0.2%', 'up',   'D',  '1H'],
            ].map(([t,s,why,px,ch,tr,htf,ltf]) => {
              const c = s==='active' ? TV.accent : s==='forming' ? TV.text : TV.text3;
              return (
                <div key={t} style={{padding: 12, borderRadius: 10,
                    border: `1px solid ${s==='active' ? TV.accentLine : TV.line}`,
                    background: s==='active' ? TV.accentSoft : TV.panel2,
                    display: 'flex', flexDirection: 'column', gap: 8}}>
                  <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                    <span className="tv-num" style={{fontSize: 14, fontWeight: 700, color: TV.text}}>{t}</span>
                    <span style={{width: 7, height: 7, borderRadius: '50%', background: c}}/>
                  </div>
                  <div style={{display: 'flex', justifyContent: 'space-between', fontSize: 12.5}}>
                    <span className="tv-num" style={{color: TV.text2}}>{px}</span>
                    <span className="tv-num" style={{color: tr==='up' ? TV.ok : tr==='down' ? TV.fail : TV.text3, fontWeight: 600}}>{ch}</span>
                  </div>
                  <HFSparkline trend={tr} w="100%" h={26}/>
                  <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                    <span style={{fontSize: 12, color: c, fontWeight: s!=='quiet' ? 600 : 400}}>{why}</span>
                    <TfPair htf={htf} ltf={ltf}/>
                  </div>
                </div>
              );
            })}
          </div>
          <div style={{marginTop: 14, textAlign: 'center'}}>
            <button className="tv-btn ghost" style={{fontSize: 12.5}}>View all 14 watched markets →</button>
          </div>
        </div>

        {/* RIGHT COL: Open Trades + Spot P&L */}
        <div style={{display: 'flex', flexDirection: 'column', gap: 14}}>

          {/* OPEN TRADES */}
          <div style={DCARD}>
            <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16}}>
              <span style={DTITLE}>Open trades</span>
              <span className="tv-chip" style={{fontSize: 11, marginBottom: 14}}>3 live</span>
              <div style={{flex: 1}}/>
              <span style={{...DSUB, marginBottom: 14}}>unreal. <span className="tv-num" style={{color: TV.ok, fontWeight: 700}}>+2.7R</span></span>
              <button className="tv-btn" style={{padding: '6px 11px', fontSize: 12, marginBottom: 14}}>Journal →</button>
            </div>
            <div style={{display: 'flex', flexDirection: 'column', gap: 12}}>
              <OpenTradeRow t="BTCUSD" dir="long" htf="4H" ltf="15m"
                  entry="71,830" now="72,010" stop="71,640" target="72,300"
                  ur="+0.9R" urUp={true} entryPct={29} nowPct={56} trend="up"/>
              <OpenTradeRow t="TSLA" dir="long" htf="D" ltf="1H"
                  entry="238.40" now="239.30" stop="237.60" target="240.20"
                  ur="+1.1R" urUp={true} entryPct={31} nowPct={65} trend="up"/>
              <OpenTradeRow t="ES" dir="short" htf="D" ltf="1H"
                  entry="5,742" now="5,729" stop="5,756" target="5,710"
                  ur="+0.7R" urUp={true} entryPct={30} nowPct={48} trend="down"/>
            </div>
          </div>

          {/* SPOT P&L SUMMARY */}
          <div style={DCARD}>
            <div style={DTITLE}>Spot P&L</div>
            <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14}}>
              {[
                ['Unrealized', '+$2,340', '+1.84%', TV.ok],
                ['Realized · 30D', '+$12,450', '+6.2%', TV.ok],
              ].map(([l,v,pct,col]) => (
                <div key={l} style={{padding: '12px 14px', borderRadius: 10, background: TV.panel2,
                    border: `1px solid ${TV.lineSoft}`, display: 'flex', flexDirection: 'column', gap: 4}}>
                  <div style={{fontSize: 11, color: TV.text3, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.05em'}}>{l}</div>
                  <div className="tv-num" style={{fontSize: 20, fontWeight: 800, color: col}}>{v}</div>
                  <div className="tv-num" style={{fontSize: 12, color: col}}>{pct}</div>
                </div>
              ))}
            </div>
            {/* top performers */}
            <div style={{fontSize: 12, fontWeight: 700, color: TV.text3, textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 8}}>Top movers · 24h</div>
            {[
              ['BTC',  '+$1,240', TV.ok],
              ['ETH',  '+$680',   TV.ok],
              ['AAPL', '-$210',   TV.fail],
            ].map(([sym,val,col]) => (
              <div key={sym} style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '6px 0', borderBottom: `1px solid ${TV.lineSoft}`, fontSize: 13.5}}>
                <span className="tv-num" style={{fontWeight: 700, color: TV.text}}>{sym}</span>
                <span className="tv-num" style={{color: col, fontWeight: 700}}>{val}</span>
              </div>
            ))}
            <div style={{marginTop: 12, textAlign: 'right'}}>
              <button className="tv-btn ghost" style={{fontSize: 12.5}}>Full P&L →</button>
            </div>
          </div>
        </div>
      </div>

      {/* ===== PERFORMANCE FOOTER ===== */}
      <div style={{display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 14, flexShrink: 0}}>
        {[
          ['Net P&L · 90D', '+18.6R', '64 trades · 38W · 22L', TV.ok, [0,1.8,0.8,2.4,3.2,2.2,4,5.4,4.8,6.8,8,7.2,9.6,10,11.2,10.4,12.4,14.2,13,14.8,16.2,15.8,17.6,16.8,18.2,17.4,18.8,18.6]],
          ['Win rate',      '59%',    'last 30 · 63%',          TV.text, null],
          ['Profit factor', '1.82',   'expectancy +0.29R',       TV.text, null],
          ['Open risk',     '2.4R',   '3 positions live',        TV.warn, null],
        ].map(([label, val, sub, col, pts]) => (
          <div key={label} style={{...KCARD}}>
            <div style={{fontSize: 11, fontWeight: 700, color: TV.accent, textTransform: 'uppercase', letterSpacing: '.06em'}}>{label}</div>
            <div className="tv-num" style={{fontSize: 24, fontWeight: 800, color: col, letterSpacing: '-.4px'}}>{val}</div>
            {pts && <EquityMini w={220} h={28} pts={pts}/>}
            <div style={{fontSize: 12, color: TV.text3}}>{sub}</div>
          </div>
        ))}
      </div>
    </div>
  </div>
);
};



// =============================================================
// 2A · Quiz (dark hi-fi)
// =============================================================
const QuizHF = () => {
  const TV = React.useContext(ThemeCtx);
  return (
  <div className="tv-frame" style={{display: 'flex', flexDirection: 'column'}}>
    <TVNav active="Quiz"/>
    <TTSubNav active="Quiz"/>

    <div style={{flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden'}}>
      {/* progress rail */}
      <div style={{width: 64, borderRight: `1px solid ${TV.line}`, background: TV.panel,
          padding: '20px 0', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12}}>
        <div className="tv-uppercase" style={{writingMode: 'vertical-rl', transform: 'rotate(180deg)', marginBottom: 6}}>
          Q 3 / 8
        </div>
        <div style={{display: 'flex', flexDirection: 'column', gap: 8}}>
          {[1,2,3,4,5,6,7,8].map(n => {
            const done = n < 3;
            const current = n === 3;
            return (
              <div key={n} style={{
                width: 26, height: 26, borderRadius: '50%',
                border: `1.5px solid ${done ? TV.ok : current ? TV.accent : TV.line}`,
                background: done ? TV.ok : current ? TV.accent : 'transparent',
                color: done || current ? '#0d1018' : TV.text3,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 11, fontWeight: 700, fontVariantNumeric: 'tabular-nums',
              }}>
                {done ? '✓' : n}
              </div>
            );
          })}
        </div>
        <div style={{flex: 1}}/>
        <div style={{fontSize: 10, color: TV.text4, transform: 'rotate(-90deg)', whiteSpace: 'nowrap'}}>2 / 2 correct</div>
      </div>

      {/* main */}
      <div style={{flex: 1, padding: '20px 28px', display: 'flex', flexDirection: 'column', gap: 14,
          overflow: 'auto', minHeight: 0}}>
        {/* meta row */}
        <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
            <span className="tv-chip accent"><span className="tv-dot"/>Order Block</span>
            <span className="tv-chip">identify pattern</span>
            <span style={{fontSize: 12, color: TV.text3}}>source · ep. 14 "OB basics" @ 02:18</span>
          </div>
          <span style={{fontSize: 12, color: TV.text3}}>⌘+1-4 to answer · ⌘↵ submit</span>
        </div>

        {/* chart */}
        <HFChart h={280} ticker="ES" tf="4H" last="5,742.25" change="+1.2%" up={true} annotate="candidate · OB"/>

        {/* question */}
        <div style={{fontSize: 22, fontWeight: 600, color: TV.text, lineHeight: 1.3, maxWidth: 880}}>
          Where is the most recent bullish <span style={{
            borderBottom: `2px wavy ${TV.accent}`, textUnderlineOffset: 4,
          }}>order block</span> on this chart?
        </div>

        {/* options grid */}
        <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10}}>
          {[
            ['A', 'Candle 4 — last down-close before the impulse up', true],
            ['B', 'Candle 9 — biggest red bar in the sequence', false],
            ['C', 'Candle 12 — bullish engulfing pattern', false],
            ['D', 'Candle 16 — high of the recent range', false],
          ].map(([k,t,sel]) => (
            <div key={k} style={{
              border: `1px solid ${sel ? TV.ok : TV.line}`,
              background: sel ? TV.okSoft : TV.panel,
              borderRadius: 8, padding: '12px 14px',
              display: 'flex', alignItems: 'center', gap: 12, cursor: 'pointer',
            }}>
              <div style={{
                width: 28, height: 28, borderRadius: 6,
                border: `1px solid ${sel ? TV.ok : TV.line}`,
                background: sel ? TV.ok : TV.panel2,
                color: sel ? '#0d1018' : TV.text2,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 13, fontWeight: 700, flexShrink: 0,
              }}>{k}</div>
              <div style={{fontSize: 15, color: TV.text, fontWeight: sel ? 500 : 400}}>{t}</div>
              {sel && <span className="tv-chip ok" style={{marginLeft: 'auto', fontSize: 11}}>✓ correct</span>}
            </div>
          ))}
        </div>

        {/* feedback */}
        <div className="tv-card" style={{padding: 14, borderColor: TV.ok, background: TV.okSoft,
            display: 'flex', gap: 14, alignItems: 'flex-start'}}>
          <div style={{
            width: 28, height: 28, borderRadius: '50%',
            background: TV.ok, color: '#0d1018', fontWeight: 700, fontSize: 16,
            display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          }}>✓</div>
          <div style={{flex: 1}}>
            <div style={{fontSize: 14, fontWeight: 600, color: TV.ok, marginBottom: 3}}>Correct.</div>
            <div style={{fontSize: 14, color: TV.text, lineHeight: 1.55}}>
              An order block is the last opposing candle before an impulsive displacement. Here, candle 4 is the
              last down-close before the bullish impulse — it's where institutional orders are presumed to have
              filled, and where price often returns to mitigate before continuation.
            </div>
            <div style={{fontSize: 12, color: TV.text3, marginTop: 6}}>
              ↳ source: ep. 14 "OB basics" @ 02:18 · also referenced in ep. 22 @ 14:30
            </div>
          </div>
        </div>

        {/* footer */}
        <div style={{display: 'flex', alignItems: 'center', gap: 10, marginTop: 'auto', paddingTop: 6}}>
          <button className="tv-btn ghost">Why?</button>
          <button className="tv-btn ghost">Flag question</button>
          <div style={{flex: 1}}/>
          <span style={{fontSize: 12, color: TV.text3}}>3 of 8 · 2 correct so far</span>
          <button className="tv-btn primary">Next →</button>
        </div>
      </div>
    </div>
  </div>
);
};

// =============================================================
// 3A · Transcript admin (dark hi-fi)
// =============================================================
const TransHF = () => (
  <div className="tv-frame" style={{display: 'flex', flexDirection: 'column'}}>
    <TVNav active="Settings"/>

    <div style={{flex: 1, padding: '22px 32px', display: 'flex', flexDirection: 'column', gap: 18,
        overflow: 'hidden', minHeight: 0}}>

      {/* header */}
      <div style={{display: 'flex', alignItems: 'baseline', justifyContent: 'space-between'}}>
        <div>
          <div className="tv-uppercase">Documents · admin</div>
          <div style={{fontSize: 22, fontWeight: 600, color: TV.text, marginTop: 4}}>Add document</div>
        </div>
        <div style={{display: 'flex', alignItems: 'center', gap: 14, fontSize: 13, color: TV.text3}}>
          <span><span className="tv-num" style={{color: TV.text, fontWeight: 600}}>6</span> documents ingested</span>
          <span style={{color: TV.text4}}>·</span>
          <span><span className="tv-num" style={{color: TV.text, fontWeight: 600}}>187</span> concepts extracted</span>
        </div>
      </div>

      {/* meta fields */}
      <div className="tv-card" style={{padding: 16, display: 'grid',
          gridTemplateColumns: 'auto 1fr auto', gap: '12px 14px', alignItems: 'center'}}>
        <div className="tv-uppercase">Topic</div>
        <div className="tv-card" style={{padding: '8px 12px', fontSize: 14, color: TV.text, background: TV.panel2,
            gridColumn: '2 / -1'}}>
          Killzones &amp; Session Liquidity — London Open into NY AM
        </div>

        <div className="tv-uppercase" style={{gridColumn: 1}}>Tags</div>
        <div style={{gridColumn: 2, display: 'flex', gap: 6, flexWrap: 'wrap'}}>
          <span className="tv-chip"><span className="tv-dot" style={{color: TV.text3}}/>killzones</span>
          <span className="tv-chip"><span className="tv-dot" style={{color: TV.text3}}/>sessions</span>
          <span className="tv-chip"><span className="tv-dot" style={{color: TV.text3}}/>liquidity</span>
          <span className="tv-chip" style={{borderStyle: 'dashed', color: TV.text3, cursor: 'pointer'}}>+ add tag</span>
        </div>
        <div style={{fontSize: 13, color: TV.text2, whiteSpace: 'nowrap'}}>~7,412 words · 348 lines</div>
      </div>

      {/* big paste area */}
      <div style={{flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column'}}>
        <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8}}>
          <div className="tv-uppercase">Document text</div>
          <span style={{fontSize: 12, color: TV.text3}}>paste summary or transcript · plaintext, markdown, or PDF text</span>
          <div style={{flex: 1}}/>
          <span className="tv-chip"><span className="tv-dot" style={{color: TV.text3}}/>auto-saved 12s ago</span>
        </div>
        <div className="tv-card" style={{flex: 1, padding: 16, minHeight: 0, overflow: 'auto',
            fontSize: 13, color: TV.text2, lineHeight: 1.6, background: TV.panel2, fontFamily: TV.font}}>
          <p style={{margin: 0, marginBottom: 10, color: TV.text}}>
            <span style={{color: TV.accent, fontWeight: 600}}>[00:00:08]</span> All right, today we're going to be looking at killzones and session liquidity and how those two work together as we move from London Open into New York AM.
          </p>
          <p style={{margin: 0, marginBottom: 10}}>
            <span style={{color: TV.accent, fontWeight: 600}}>[00:00:42]</span> So before we get into the chart, let's quickly review what we mean by a killzone. A killzone is a specific window of time inside a session where price is most likely to deliver — meaning sweep liquidity, shift structure, and offer the highest-probability entries…
          </p>
          <p style={{margin: 0, marginBottom: 10}}>
            <span style={{color: TV.accent, fontWeight: 600}}>[00:02:15]</span> Now here's where it gets interesting. The London Open killzone runs roughly 02:00 to 05:00 New York time. What you're typically looking for is a sweep of either Asia high or Asia low…
          </p>
          <p style={{margin: 0, color: TV.text3}}>
            … 344 more lines · scroll to view
          </p>
        </div>
      </div>

      {/* footer */}
      <div style={{display: 'flex', alignItems: 'center', gap: 12, paddingTop: 4}}>
        <span style={{fontSize: 12, color: TV.text3}}>
          ⏱ Claude will extract ~12 concepts on save and weight future quizzes
        </span>
        <div style={{flex: 1}}/>
        <button className="tv-btn ghost">Cancel</button>
        <button className="tv-btn">Save as draft</button>
        <button className="tv-btn primary">Save &amp; extract concepts →</button>
      </div>
    </div>
  </div>
);

// =============================================================
// 4A · Setup Scanner (dark hi-fi) — dense table + detail drawer
// =============================================================
const ScanHF = () => (
  <div className="tv-frame" style={{display: 'flex', flexDirection: 'column'}}>
    <TVNav active="Scanner"/>
    <TTSubNav active="Scanner"/>

    <div style={{flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden'}}>
      {/* table side */}
      <div style={{flex: 1.4, display: 'flex', flexDirection: 'column', padding: '20px 24px',
          gap: 14, minHeight: 0, overflow: 'hidden'}}>
        <div style={{display: 'flex', alignItems: 'baseline', justifyContent: 'space-between'}}>
          <div>
            <div className="tv-uppercase">Setup scanner</div>
            <div style={{fontSize: 22, fontWeight: 600, color: TV.text, marginTop: 4}}>Watchlist · 12 tickers</div>
          </div>
          <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
            <span className="tv-chip accent"><span className="tv-dot"/>2 active</span>
            <span className="tv-chip"><span className="tv-dot"/>3 forming</span>
            <span className="tv-chip" style={{color: TV.text3}}>1 watching</span>
            <span style={{fontSize: 12, color: TV.text3, marginLeft: 8}}>last scan · 4m ago</span>
            <button className="tv-btn ghost" style={{padding: '6px 12px', fontSize: 12}}>↻ rescan</button>
            <button className="tv-btn" style={{padding: '6px 12px', fontSize: 12}}>+ ticker</button>
          </div>
        </div>

        {/* table */}
        <div className="tv-card" style={{padding: 0, overflow: 'hidden', flex: 1, display: 'flex',
            flexDirection: 'column', minHeight: 0}}>
          <div style={{
            display: 'grid', gridTemplateColumns: '24px 80px 90px 1fr 100px 100px 90px 80px',
            padding: '10px 14px', borderBottom: `1px solid ${TV.line}`,
            background: TV.panel2, fontSize: 11, fontWeight: 600,
            color: TV.text3, letterSpacing: '.06em', textTransform: 'uppercase',
            alignItems: 'center', gap: 12,
          }}>
            <span></span>
            <span>Ticker</span>
            <span>Status</span>
            <span>Signal</span>
            <span style={{display: 'inline-flex', alignItems: 'center', gap: 5}}>
              HTF
              <span style={{color: TV.text4}}>→</span>
              LTF
            </span>
            <span>Confidence</span>
            <span>Chart</span>
            <span style={{textAlign: 'right'}}>Price</span>
          </div>
          <div style={{flex: 1, overflow: 'auto', minHeight: 0}}>
            {[
              ['BTC',    'active',   'Bullish OB tap @ 71,800 · LTF CHoCH printing', '4H', '15m', 82, 'up',   '71,840',  '+1.2%', true],
              ['TSLA',   'active',   'D OB tap · 1H sweep + BOS · entry ready',      'D',  '1H',  78, 'up',   '238.40',  '+0.6%'],
              ['ES',     'forming',  'D FVG under premium · awaiting 1H trigger',    'D',  '1H',  64, 'up',   '5,742',   '+0.4%'],
              ['AAPL',   'forming',  'D OB approach · 1H sweep of equal lows',       'D',  '1H',  58, 'flat', '186.20',  '+0.1%'],
              ['ETH',    'forming',  '4H OB approach · waiting 15m CHoCH',           '4H', '15m', 54, 'up',   '3,612',   '+0.9%'],
              ['GOLD',   'watching', 'Approaching D OB at 2,340 · no LTF yet',       'D',  '1H',  41, 'up',   '2,348',   '+0.2%'],
              ['USDJPY', 'forming',  '4H buy-side sweep · watching 15m shift',       '4H', '15m', 36, 'down', '155.20',  '-0.2%'],
              ['NQ',     'quiet',    'No setup · 4H ranging inside D range',         'D',  '1H',  12, 'down', '20,140',  '-0.3%'],
              ['EURUSD', 'quiet',    'No setup',                                      '4H', '15m',  8, 'down', '1.0832',  '-0.1%'],
              ['GBPUSD', 'quiet',    'No setup',                                      '4H', '15m',  6, 'flat', '1.2710',  '+0.0%'],
              ['OIL',    'quiet',    'No setup',                                      'D',  '1H',   4, 'down', '78.40',   '-0.5%'],
              ['DXY',    'quiet',    'No setup',                                      'W',  '4H',   3, 'up',   '104.22',  '+0.1%'],
            ].map(([t,s,why,htf,ltf,conf,tr,px,ch,sel],i) => {
              const c = s === 'active' ? TV.accent : s === 'forming' ? TV.text : s === 'watching' ? TV.text2 : TV.text4;
              return (
                <div key={t} style={{
                  display: 'grid', gridTemplateColumns: '24px 80px 90px 1fr 100px 100px 90px 80px',
                  padding: '11px 14px',
                  borderBottom: i < 11 ? `1px solid ${TV.lineSoft}` : 'none',
                  alignItems: 'center', gap: 12,
                  background: sel ? TV.accentSoft : 'transparent',
                  borderLeft: sel ? `2px solid ${TV.accent}` : '2px solid transparent',
                  cursor: 'pointer',
                }}>
                  <span style={{width: 8, height: 8, borderRadius: '50%', background: c}}/>
                  <span className="tv-num" style={{fontWeight: 600, color: TV.text}}>{t}</span>
                  <span style={{fontSize: 12, color: c, fontWeight: 500, textTransform: 'capitalize'}}>{s}</span>
                  <span style={{fontSize: 13, color: TV.text2}}>{why}</span>
                  <TfPair htf={htf} ltf={ltf}/>
                  <div style={{display: 'flex', alignItems: 'center', gap: 6}}>
                    <div style={{flex: 1, height: 5, background: TV.panel3, borderRadius: 2, overflow: 'hidden'}}>
                      <div style={{height: '100%', width: `${conf}%`,
                          background: conf > 70 ? TV.accent : conf > 40 ? TV.text2 : TV.text4}}/>
                    </div>
                    <span className="tv-num" style={{fontSize: 11, color: TV.text3, width: 22, textAlign: 'right'}}>{conf}</span>
                  </div>
                  <HFSparkline trend={tr} w={80} h={20}/>
                  <div style={{textAlign: 'right'}}>
                    <div className="tv-num" style={{fontSize: 12, color: TV.text}}>{px}</div>
                    <div className="tv-num" style={{fontSize: 11,
                        color: tr === 'up' ? TV.ok : tr === 'down' ? TV.fail : TV.text3}}>{ch}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* detail drawer */}
      <div style={{width: 380, borderLeft: `1px solid ${TV.line}`, background: TV.panel,
          display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden'}}>
        <div style={{padding: '16px 18px', borderBottom: `1px solid ${TV.line}`,
            display: 'flex', alignItems: 'center', gap: 10}}>
          <div>
            <div className="tv-uppercase">Detail</div>
            <div style={{fontSize: 18, fontWeight: 600, color: TV.text, marginTop: 2,
                display: 'flex', alignItems: 'center', gap: 8}}>
              BTCUSD
              <TfPair htf="4H" ltf="15m"/>
              <span className="tv-chip accent" style={{fontSize: 11}}><span className="tv-dot"/>active</span>
            </div>
          </div>
          <div style={{flex: 1}}/>
          <span style={{fontSize: 16, color: TV.text3, cursor: 'pointer'}}>×</span>
        </div>

        <div style={{padding: 16, display: 'flex', flexDirection: 'column', gap: 14,
            overflow: 'auto', flex: 1, minHeight: 0}}>
          {/* HTF context */}
          <div>
            <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6}}>
              <span style={{fontSize: 10, fontWeight: 700, color: TV.adapt, padding: '2px 6px',
                  borderRadius: 3, background: TV.adaptSoft, border: `1px solid rgba(139,122,214,.35)`,
                  letterSpacing: '.08em', textTransform: 'uppercase'}}>HTF · 4H</span>
              <span style={{fontSize: 11, color: TV.text3}}>point of interest</span>
            </div>
            <HFChart h={130} ticker="BTC" tf="4H" last="71,840" change="+1.2%" up={true} annotate="bullish OB"/>
          </div>

          {/* LTF trigger */}
          <div>
            <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6}}>
              <span style={{fontSize: 10, fontWeight: 700, color: TV.ok, padding: '2px 6px',
                  borderRadius: 3, background: TV.okSoft, border: `1px solid rgba(63,178,127,.35)`,
                  letterSpacing: '.08em', textTransform: 'uppercase'}}>LTF · 15m</span>
              <span style={{fontSize: 11, color: TV.text3}}>entry trigger</span>
            </div>
            <HFChart h={130} ticker="BTC" tf="15m" last="71,840" change="+1.2%" up={true} annotate="CHoCH printing"/>
          </div>

          <div>
            <div className="tv-uppercase" style={{marginBottom: 6}}>Why flagged</div>
            <div style={{fontSize: 14, color: TV.text, lineHeight: 1.55}}>
              On the <span style={{color: TV.adapt, fontWeight: 600}}>4H (HTF)</span>: bullish order block at <span className="tv-num" style={{fontWeight: 600}}>71,800</span> just
              tapped after a 3-candle FVG impulse. On the <span style={{color: TV.ok, fontWeight: 600}}>15m (LTF)</span>: equal lows swept and CHoCH at 71,890. London killzone confluence.
            </div>
          </div>

          <div>
            <div className="tv-uppercase" style={{marginBottom: 6}}>Concepts triggered</div>
            <div style={{display: 'flex', gap: 6, flexWrap: 'wrap'}}>
              <span className="tv-chip accent">Order Block</span>
              <span className="tv-chip accent">FVG</span>
              <span className="tv-chip">Liquidity Sweep</span>
              <span className="tv-chip">CHoCH</span>
              <span className="tv-chip">Killzone</span>
            </div>
          </div>

          <div className="tv-card" style={{padding: 12}}>
            <div className="tv-uppercase" style={{marginBottom: 8}}>Proposed plan</div>
            <div style={{display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px 14px', fontSize: 13}}>
              <span style={{color: TV.text3}}>Entry</span>
              <span className="tv-num" style={{color: TV.text, fontWeight: 600}}>71,830 (FVG mid)</span>
              <span style={{color: TV.text3}}>Stop</span>
              <span className="tv-num" style={{color: TV.text}}>71,640 — below swept low</span>
              <span style={{color: TV.text3}}>Target</span>
              <span className="tv-num" style={{color: TV.text}}>72,300 — range mid</span>
              <span style={{color: TV.text3}}>R:R</span>
              <span className="tv-num" style={{color: TV.warn}}>1:2.4</span>
            </div>
          </div>

          <div>
            <div className="tv-uppercase" style={{marginBottom: 6}}>Notes</div>
            <div className="tv-card" style={{padding: 10, minHeight: 60, fontSize: 13, color: TV.text3,
                background: TV.panel2, borderStyle: 'dashed'}}>
              Waiting for LTF CHoCH confirmation before sizing in. Tighten stop to OB high if 5m confirms.
            </div>
          </div>

          <div style={{display: 'flex', gap: 8, marginTop: 'auto'}}>
            <button className="tv-btn" style={{flex: 1, fontSize: 13}}>Open in TradingView ↗</button>
            <button className="tv-btn primary" style={{fontSize: 13}}>Validate setup →</button>
          </div>
        </div>
      </div>
    </div>
  </div>
);

Object.assign(window, {DashHF, QuizHF, TransHF, ScanHF, TfPair, HFChart, HFSparkline});
