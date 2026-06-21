// validator.jsx — Trade Setup Validator (dark hi-fi)
// First hi-fi screen in the dark UI direction from the original brief.
// 3 artboards: mid-flow, adaptive-branch moment, summary record.
//
// Concept palette is strictly limited to: market structure, bias,
// liquidity sweeps, dealing ranges, fair value gaps, trade entries.
// TODO: replace question copy with text sourced from transcript corpus
// once episodes are ingested — current copy is structurally faithful
// placeholder.

const TV = {
  bg: '#0a2a47',
  panel: '#103f63',
  panel2: '#154a72',
  panel3: '#1c5a85',
  line: '#266594',
  lineSoft: 'rgba(255,255,255,0.12)',
  text: '#ffffff',
  text2: '#eef4fd',
  text3: '#d7e5f6',
  text4: '#b6cbe8',
  accent: '#ffb52e', // single highlight color (gold)
  accentSoft: 'rgba(255,181,46,0.18)',
  accentLine: 'rgba(255,181,46,0.5)',
  ok: '#4fdd8e',
  okSoft: 'rgba(79,221,142,0.18)',
  warn: '#ffd23f',
  warnSoft: 'rgba(255,210,63,0.16)',
  fail: '#ff8a8a',
  failSoft: 'rgba(255,138,138,0.18)',
  adapt: '#2fb4e8', // distinct hue for "path adapted" cue (cyan)
  adaptSoft: 'rgba(47,180,232,0.2)',
  font: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif"
};

// ---- Blue theme experiment (navy base · gold/green/white accents) ----
// Swappable palette + React context. Screen components read their palette via
// `const TV = React.useContext(ThemeCtx)`, defaulting to the dark TV above, so
// wrapping a screen in <ThemeCtx.Provider value={TV_BLUE}> recolors it.
const TV_BLUE = {
  bg: '#0a2a47',
  panel: '#103f63',
  panel2: '#154a72',
  panel3: '#1c5a85',
  line: '#266594',
  lineSoft: 'rgba(255,255,255,0.12)',
  text: '#f1f7fd',
  text2: '#c8dbef',
  text3: '#9fbbda',
  text4: '#7b9cc4',
  accent: '#ffb52e',
  accentSoft: 'rgba(255,181,46,0.18)',
  accentLine: 'rgba(255,181,46,0.5)',
  ok: '#4fdd8e',
  okSoft: 'rgba(79,221,142,0.18)',
  warn: '#ffd23f',
  warnSoft: 'rgba(255,210,63,0.16)',
  fail: '#ff8a8a',
  failSoft: 'rgba(255,138,138,0.18)',
  adapt: '#2fb4e8',
  adaptSoft: 'rgba(47,180,232,0.2)',
  font: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif"
};

// ---- Indigo theme experiment (With-Jack: violet base · coral headings · gold CTA) ----
const TV_INDIGO = {
  bg: '#232560',
  panel: '#313473',
  panel2: '#3a3d86',
  panel3: '#474b9c',
  line: '#4a4ea0',
  lineSoft: 'rgba(255,255,255,0.12)',
  text: '#f4f3fb',
  text2: '#cdcdec',
  text3: '#a6a7d8',
  text4: '#8385c2',
  accent: '#f0856b',
  accentSoft: 'rgba(240,133,107,0.16)',
  accentLine: 'rgba(240,133,107,0.45)',
  ok: '#5fd39a',
  okSoft: 'rgba(95,211,154,0.16)',
  warn: '#f5a623',
  warnSoft: 'rgba(245,166,35,0.16)',
  fail: '#ef6b6b',
  failSoft: 'rgba(239,107,107,0.16)',
  adapt: '#8f8fe6',
  adaptSoft: 'rgba(143,143,230,0.2)',
  font: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif"
};

// ---- Card-blue draft (deep navy ground · brighter royal-blue cards) ----
const TV_CARDBLUE = {
  bg: '#0a2a47',
  panel: '#1f5aa6',
  panel2: '#2766b8',
  panel3: '#2f72c6',
  line: '#3d77bc',
  lineSoft: 'rgba(255,255,255,0.16)',
  text: '#f6faff',
  text2: '#dcebfb',
  text3: '#bbd5f2',
  text4: '#94bce8',
  accent: '#ffb52e',
  accentSoft: 'rgba(255,181,46,0.2)',
  accentLine: 'rgba(255,181,46,0.55)',
  ok: '#27e0a0',
  okSoft: 'rgba(39,224,160,0.2)',
  warn: '#ffd23f',
  warnSoft: 'rgba(255,210,63,0.2)',
  fail: '#ff8a8a',
  failSoft: 'rgba(255,138,138,0.2)',
  adapt: '#38bdf8',
  adaptSoft: 'rgba(56,189,248,0.22)',
  font: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif"
};

// lime-green positives variant of the card-blue draft (everything else identical)
const TV_CARDBLUE_LIME = {...TV_CARDBLUE, ok: '#a3e635', okSoft: 'rgba(163,230,53,0.2)'};
const ThemeCtx = React.createContext(TV);

if (!document.getElementById('tv-styles')) {
  const s = document.createElement('style');
  s.id = 'tv-styles';
  s.textContent = `
    .tv-frame{background:${TV.bg};color:${TV.text};font-family:${TV.font};
      width:100%;height:100%;overflow:hidden;font-size:14px;line-height:1.45;
      font-feature-settings:"ss01","cv11";font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
    .tv-frame *{box-sizing:border-box}
    .tv-num{font-variant-numeric:tabular-nums;font-feature-settings:"tnum","cv11"}
    .tv-uppercase{text-transform:uppercase;letter-spacing:.08em;font-size:11px;font-weight:600;color:#dbe7f6}
    .tv-btn{display:inline-flex;align-items:center;gap:8px;padding:10px 16px;border-radius:6px;
      border:1px solid ${TV.line};background:${TV.panel2};color:${TV.text};
      font-family:inherit;font-size:14px;font-weight:500;cursor:pointer;
      transition:background .12s,border-color .12s}
    .tv-btn:hover{background:${TV.panel3};border-color:${TV.text4}}
    .tv-btn.primary{background:${TV.accent};border-color:${TV.accent};color:#231905;font-weight:600}
    .tv-btn.primary:hover{background:#ffc457;border-color:#ffc457}
    .tv-btn.ghost{background:transparent;border-color:transparent;color:${TV.text2}}
    .tv-btn.ghost:hover{background:${TV.panel2};color:${TV.text}}
    .tv-chip{display:inline-flex;align-items:center;gap:6px;padding:3px 9px;border-radius:4px;
      border:1px solid ${TV.line};background:${TV.panel};font-size:12px;font-weight:500;color:${TV.text2}}
    .tv-chip.accent{border-color:${TV.accentLine};background:${TV.accentSoft};color:${TV.accent}}
    .tv-chip.ok{border-color:rgba(79,221,142,.4);background:${TV.okSoft};color:${TV.ok}}
    .tv-chip.warn{border-color:rgba(255,210,63,.4);background:${TV.warnSoft};color:${TV.warn}}
    .tv-chip.fail{border-color:rgba(255,138,138,.4);background:${TV.failSoft};color:${TV.fail}}
    .tv-chip.adapt{border-color:rgba(47,180,232,.4);background:${TV.adaptSoft};color:${TV.adapt}}
    .tv-dot{width:6px;height:6px;border-radius:50%;display:inline-block;background:currentColor}
    .tv-card{background:${TV.panel};border:1px solid ${TV.line};border-radius:8px}
    .tv-divider{height:1px;background:${TV.line}}

    /* ---- Blue theme experiment: scoped utility-class overrides ---- */
    .theme-blue .tv-frame{background:#0a2a47}
    .theme-blue .tv-card{background:#103f63;border-color:#266594}
    .theme-blue .tv-btn{background:#154a72;border-color:#266594;color:#f1f7fd}
    .theme-blue .tv-btn:hover{background:#1c5a85;border-color:#7b9cc4}
    .theme-blue .tv-btn.primary{background:#ffb52e;border-color:#ffb52e;color:#231905}
    .theme-blue .tv-btn.primary:hover{background:#ffc457;border-color:#ffc457}
    .theme-blue .tv-btn.ghost{background:transparent;border-color:transparent;color:#c8dbef}
    .theme-blue .tv-btn.ghost:hover{background:#154a72;color:#f1f7fd}
    .theme-blue .tv-chip{background:#103f63;border-color:#266594;color:#c8dbef}
    .theme-blue .tv-chip.accent{border-color:rgba(255,181,46,.5);background:rgba(255,181,46,.18);color:#ffb52e}
    .theme-blue .tv-chip.ok{border-color:rgba(79,221,142,.4);background:rgba(79,221,142,.18);color:#4fdd8e}
    .theme-blue .tv-chip.warn{border-color:rgba(255,210,63,.4);background:rgba(255,210,63,.16);color:#ffd23f}
    .theme-blue .tv-chip.fail{border-color:rgba(255,138,138,.4);background:rgba(255,138,138,.18);color:#ff8a8a}
    .theme-blue .tv-uppercase{color:#c8dbef}

    /* ---- Indigo theme experiment: scoped utility-class overrides ---- */
    .theme-indigo .tv-frame{background:#232560}
    .theme-indigo .tv-card{background:#313473;border-color:#4a4ea0}
    .theme-indigo .tv-btn{background:#3a3d86;border-color:#4a4ea0;color:#f4f3fb}
    .theme-indigo .tv-btn:hover{background:#474b9c;border-color:#8385c2}
    .theme-indigo .tv-btn.primary{background:#f5a623;border-color:#f5a623;color:#3a2400}
    .theme-indigo .tv-btn.primary:hover{background:#ffb53e;border-color:#ffb53e}
    .theme-indigo .tv-btn.ghost{background:transparent;border-color:transparent;color:#cdcdec}
    .theme-indigo .tv-btn.ghost:hover{background:#3a3d86;color:#f4f3fb}
    .theme-indigo .tv-chip{background:#313473;border-color:#4a4ea0;color:#cdcdec}
    .theme-indigo .tv-chip.accent{border-color:rgba(240,133,107,.45);background:rgba(240,133,107,.16);color:#f0856b}
    .theme-indigo .tv-chip.ok{border-color:rgba(95,211,154,.4);background:rgba(95,211,154,.16);color:#5fd39a}
    .theme-indigo .tv-chip.warn{border-color:rgba(245,166,35,.4);background:rgba(245,166,35,.16);color:#f5a623}
    .theme-indigo .tv-chip.fail{border-color:rgba(239,107,107,.4);background:rgba(239,107,107,.16);color:#ef6b6b}
    .theme-indigo .tv-uppercase{color:#cdcdec}

    /* ---- Card-blue draft: scoped utility-class overrides ---- */
    .theme-cardblue .tv-frame{background:#0a2a47}
    .theme-cardblue .tv-card{background:#1f5aa6;border-color:#3d77bc}
    .theme-cardblue .tv-btn{background:#2766b8;border-color:#3d77bc;color:#f6faff}
    .theme-cardblue .tv-btn:hover{background:#2f72c6;border-color:#6fa0db}
    .theme-cardblue .tv-btn.primary{background:#ffb52e;border-color:#ffb52e;color:#231905}
    .theme-cardblue .tv-btn.primary:hover{background:#ffc457;border-color:#ffc457}
    .theme-cardblue .tv-btn.ghost{background:transparent;border-color:transparent;color:#dcebfb}
    .theme-cardblue .tv-btn.ghost:hover{background:#2766b8;color:#f6faff}
    .theme-cardblue .tv-chip{background:#2766b8;border-color:#3d77bc;color:#dcebfb}
    .theme-cardblue .tv-chip.accent{border-color:rgba(255,181,46,.55);background:rgba(255,181,46,.2);color:#ffd27a}
    .theme-cardblue .tv-chip.ok{border-color:rgba(39,224,160,.45);background:rgba(39,224,160,.2);color:#5fe9bc}
    .theme-cardblue-lime .tv-chip.ok{border-color:rgba(163,230,53,.45);background:rgba(163,230,53,.2);color:#c2ee6e}
    .theme-cardblue .tv-chip.warn{border-color:rgba(255,210,63,.45);background:rgba(255,210,63,.2);color:#ffe07a}
    .theme-cardblue .tv-chip.fail{border-color:rgba(255,138,138,.45);background:rgba(255,138,138,.2);color:#ffb0b0}
    .theme-cardblue .tv-uppercase{color:#dcebfb}
  `;
  document.head.appendChild(s);
}

// ---------- shared shell ----------
const NAV_ITEMS = ['Dashboard', 'Portfolio', 'Spot P&L', 'Performance', 'Market Data', 'AI Brief', 'Trading Tools', 'Settings'];

// maps individual screen names → their Trading Tools parent so TVNav highlights correctly
const NAV_GROUP = {
  'Scanner':'Trading Tools','Validator':'Trading Tools','Journal':'Trading Tools',
  'Reports':'Trading Tools','Concepts':'Trading Tools','Quiz':'Trading Tools',
  'Trading Settings':'Trading Tools',
};

// Trading Tools sub-nav (shown inside each Trading Tools screen)
const TT_ITEMS = ['Scanner','Validator','Journal','Reports','Concepts','Quiz','Trading Settings'];
const TTSubNav = ({active}) => (
  <div style={{borderBottom:`1px solid ${TV.line}`, background:TV.panel2,
      padding:'0 22px', display:'flex', gap:2, alignItems:'flex-end', flexShrink:0}}>
    {TT_ITEMS.map(it => {
      const on = it === active;
      return (
        <div key={it} style={{padding:'7px 13px', fontSize:13, fontWeight:on?600:400,
            color:on?TV.text:TV.text2, cursor:'pointer', whiteSpace:'nowrap',
            borderBottom:on?`2px solid ${TV.accent}`:'2px solid transparent',
            background:on?`${TV.panel3}88`:'transparent'}}>{it}</div>
      );
    })}
  </div>
);

const TVNav = ({ active = 'Validator' }) => {
  const TV = React.useContext(ThemeCtx);
  return (
<div style={{
  borderBottom: `1px solid ${TV.line}`, background: TV.panel,
  display: 'flex', alignItems: 'center', padding: '10px 22px', gap: 18, flexShrink: 0
}}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{
      width: 28, height: 28, borderRadius: 6, background: TV.accent,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: '#1a0f08', fontWeight: 800, fontSize: 14
    }}>P</div>
      <div style={{ fontSize: 14, fontWeight: 600, color: TV.text, letterSpacing: '-.1px' }}>
        The Playbook
      </div>
    </div>

    <div style={{ display: 'flex', alignItems: 'center', gap: 2, marginLeft: 14 }}>
      {NAV_ITEMS.map((it) =>
    <div key={it} style={{
      padding: '5px 8px', borderRadius: 5,
      fontSize: 13, fontWeight: 500, letterSpacing: '.01em',
      color: (it === active || NAV_GROUP[active] === it) ? TV.text : TV.text2,
      background: (it === active || NAV_GROUP[active] === it) ? TV.panel3 : 'transparent',
      borderBottom: (it === active || NAV_GROUP[active] === it) ? `2px solid ${TV.accent}` : '2px solid transparent',
      cursor: 'pointer'
    }}>
          {it}
        </div>
    )}
    </div>

    <div style={{ flex: 1 }} />
    <div style={{ fontSize: 12, color: TV.text3 }}>day 47 · streak 12</div>
    <div style={{
    width: 30, height: 30, borderRadius: '50%', border: `1px solid ${TV.line}`,
    background: TV.panel2, fontSize: 11, color: TV.text2,
    display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 600
  }}>JM</div>
  </div>
);
};


// ---------- Step indicator ----------
// Nodes can be: fixed (filled circle), adaptive (diamond), pending (open circle)
const StepIndicator = ({ steps, currentIndex, adaptedAtIndex = null }) =>
<div style={{ display: 'flex', alignItems: 'center', gap: 0, width: '100%' }}>
    {steps.map((step, i) => {
    const done = i < currentIndex;
    const current = i === currentIndex;
    const adapted = step.adaptive;
    const justAdapted = adaptedAtIndex === i;
    const color = current ? TV.accent : done ? TV.text2 : TV.text4;
    const bg = current ? TV.accent : done ? TV.text2 : 'transparent';
    const border = adapted ? `1.5px dashed ${justAdapted ? TV.adapt : color}` : `1.5px solid ${color}`;
    return (
      <React.Fragment key={i}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 7, minWidth: 0 }}>
            <div style={{
            width: 22, height: 22,
            ...(adapted ?
            { transform: 'rotate(45deg)', borderRadius: 3 } :
            { borderRadius: '50%' }),
            border,
            background: done && !adapted ? bg : current && !adapted ? bg : adapted && (done || current) ? justAdapted ? TV.adapt : TV.panel3 : 'transparent',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 11, fontWeight: 700,
            color: current ? '#1a0f08' : color,
            boxShadow: justAdapted ? `0 0 0 4px ${TV.adaptSoft}` : 'none',
            transition: 'all .2s'
          }}>
              <span style={{ transform: adapted ? 'rotate(-45deg)' : 'none' }}>
                {done ? '✓' : i + 1}
              </span>
            </div>
            <div style={{ fontSize: 11, color: current ? TV.text : color, fontWeight: current ? 600 : 500,
            whiteSpace: 'nowrap', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              {step.leg &&
                <span style={{
                  fontSize: 8, fontWeight: 700, letterSpacing: '.08em',
                  color: step.leg === 'htf' ? TV.adapt : TV.ok,
                  padding: '0 5px', borderRadius: 2,
                  background: step.leg === 'htf' ? TV.adaptSoft : TV.okSoft,
                  border: `1px solid ${step.leg === 'htf' ? 'rgba(139,122,214,.35)' : 'rgba(63,178,127,.35)'}`,
                  textTransform: 'uppercase'
                }}>{step.leg}</span>
              }
              <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                {step.label}
                {adapted && <span style={{
                color: justAdapted ? TV.adapt : TV.text4, fontSize: 9, fontWeight: 600,
                letterSpacing: '.05em', textTransform: 'uppercase'
              }}>· adapt</span>}
              </span>
            </div>
          </div>
          {i < steps.length - 1 &&
        <div style={{
          flex: 1, height: 1.5, margin: '0 6px', marginBottom: 24,
          background: i < currentIndex ? TV.text2 : TV.line,
          borderTop: steps[i + 1].adaptive ? `1.5px dashed ${i < currentIndex ? TV.text2 : TV.line}` : 'none',
          ...(steps[i + 1].adaptive ? { background: 'transparent', height: 0 } : {})
        }} />
        }
        </React.Fragment>);

  })}
  </div>;


// ---------- Previous-answers summary rail ----------
const AnswerRow = ({ label, value, status = 'ok', concept }) => {
  const color = status === 'ok' ? TV.ok : status === 'warn' ? TV.warn : status === 'fail' ? TV.fail : TV.text2;
  return (
    <div style={{ padding: '10px 14px', borderBottom: `1px solid ${TV.lineSoft}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
        <div className="tv-uppercase">{label}</div>
        {concept && <div style={{ fontSize: 10, color: TV.text4, fontWeight: 500 }}>{concept}</div>}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0 }} />
        <div style={{ fontSize: 15, color: TV.text, fontWeight: 500 }}>{value}</div>
      </div>
    </div>);

};

const SummaryRail = ({ answers, hint, adaptedNote }) =>
<div style={{
  width: 280, borderRight: `1px solid ${TV.line}`, background: TV.panel,
  display: 'flex', flexDirection: 'column', overflow: 'hidden'
}}>
    <div style={{ padding: '14px 14px 10px', borderBottom: `1px solid ${TV.line}` }}>
      <div className="tv-uppercase">Setup so far</div>
      <div style={{ fontSize: 13, color: TV.text2, marginTop: 2 }}>BTCUSD · 1H · 06:48</div>
    </div>
    <div style={{ flex: 1, overflow: 'auto' }}>
      {answers.map((a, i) => <AnswerRow key={i} {...a} />)}
      {adaptedNote &&
    <div style={{ padding: '12px 14px', background: TV.adaptSoft, borderTop: `1px solid ${TV.line}` }}>
          <div className="tv-uppercase" style={{ color: TV.adapt }}>Path adapted</div>
          <div style={{ fontSize: 13, color: TV.text, marginTop: 4, lineHeight: 1.5 }}>{adaptedNote}</div>
        </div>
    }
    </div>
    {hint &&
  <div style={{ padding: '12px 14px', borderTop: `1px solid ${TV.line}`, background: TV.panel2 }}>
        <div style={{ fontSize: 12, color: TV.text3, lineHeight: 1.5 }}>{hint}</div>
      </div>
  }
  </div>;


// ---------- Option card ----------
const OptionCard = ({ letter, label, sub, selected, branchInfo }) =>
<div style={{
  border: `1px solid ${selected ? TV.accent : TV.line}`,
  background: selected ? TV.accentSoft : TV.panel,
  borderRadius: 8, padding: '14px 16px',
  display: 'flex', alignItems: 'flex-start', gap: 14,
  cursor: 'pointer', transition: 'all .12s'
}}>
    <div style={{
    width: 28, height: 28, borderRadius: 6,
    border: `1px solid ${selected ? TV.accent : TV.line}`,
    background: selected ? TV.accent : TV.panel2,
    color: selected ? '#1a0f08' : TV.text2,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: 13, fontWeight: 700, flexShrink: 0
  }}>{letter}</div>
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: 16, color: TV.text, fontWeight: 500, marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 13, color: TV.text2, lineHeight: 1.45 }}>{sub}</div>
    </div>
    {branchInfo &&
  <div style={{
    display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 3,
    fontSize: 11, color: TV.text3, flexShrink: 0
  }}>
        <span className="tv-chip adapt" style={{ fontSize: 10, padding: '2px 6px' }}>↳ branches</span>
        <span style={{ color: TV.text3 }}>{branchInfo}</span>
      </div>
  }
  </div>;


// =============================================================
// SCREEN 5A — Mid-flow (Step 4 of 7) — at the branching question
// =============================================================
const ValidatorA = () => {
  const steps = [
  { label: 'HTF Bias',          leg: 'htf' },
  { label: 'Dealing Range',     leg: 'htf' },
  { label: 'HTF Liquidity',     leg: 'htf' },
  { label: 'Entry Trigger',     leg: 'ltf' },
  { label: 'Confirmation',      leg: 'ltf', adaptive: true },
  { label: 'Risk / Invalidation' },
  { label: 'Review' }];

  const answers = [
  { label: 'HTF Bias · 4H', value: 'Bullish — last BOS to upside', status: 'ok', concept: 'market structure' },
  { label: 'Dealing Range · 4H', value: 'Discount — price below 0.5 of range', status: 'ok', concept: 'dealing range' },
  { label: 'Liquidity', value: 'Sell-side swept at 71,640 (Asia low)', status: 'ok', concept: 'liquidity sweep' }];


  return (
    <div className="tv-frame" style={{ display: 'flex', flexDirection: 'column' }}>
      <TVNav active="Validator" />
    <TTSubNav active="Validator"/>
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
      <SummaryRail answers={answers} hint="Remaining steps adapt based on your entry trigger choice." />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* top bar */}
        <div style={{ padding: '14px 28px', borderBottom: `1px solid ${TV.line}`,
          display: 'flex', alignItems: 'center', gap: 16 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 600, color: TV.text }}>Trade Setup Validator</div>
            <div style={{ fontSize: 12, color: TV.text3, marginTop: 1 }}>BTCUSD · 1H · adaptive · 7 steps</div>
          </div>
          <div style={{ flex: 1 }} />
          <span className="tv-chip"><span style={{ color: TV.text3 }}>step</span> 4 / 7</span>
          <button className="tv-btn ghost" style={{ padding: '6px 10px' }}>Save & exit</button>
        </div>

        {/* step indicator */}
        <div style={{ padding: '20px 32px 16px', borderBottom: `1px solid ${TV.line}`, background: TV.panel }}>
          <StepIndicator steps={steps} currentIndex={3} />
        </div>

        {/* question */}
        <div style={{ flex: 1, padding: '24px 32px', overflow: 'auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span className="tv-chip accent"><span className="tv-dot" /> entry trigger</span>
            <span className="tv-chip">single select</span>
            <span style={{ fontSize: 12, color: TV.text3 }}>each option leads to a different question path</span>
          </div>

          <div style={{ fontSize: 22, fontWeight: 600, color: TV.text, lineHeight: 1.3, marginBottom: 6, maxWidth: 760 }}>
            What is your entry trigger on the lower timeframe?
          </div>
          <div style={{ fontSize: 15, color: TV.text2, marginBottom: 22, maxWidth: 760 }}>
            With HTF bias bullish, price in discount, and sell-side liquidity already swept — pick the trigger you're waiting for.
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 760 }}>
            <OptionCard
              letter="A"
              label="Bullish Fair Value Gap (FVG)"
              sub="Price returns to an unmitigated FVG inside the discount array; entry on the FVG mid or low."
              branchInfo="3 follow-ups"
              selected={false} />
            
            <OptionCard
              letter="B"
              label="Liquidity sweep + structure shift (LTF)"
              sub="Wait for another sweep on the lower timeframe followed by a BOS / CHoCH before entry."
              branchInfo="2 follow-ups"
              selected={true} />
            
            <OptionCard
              letter="C"
              label="Inside an HTF bullish order block"
              sub="Price taps an OB defined on the 4H bias timeframe; entry at the OB high or 50%."
              branchInfo="3 follow-ups" />
            
            <OptionCard
              letter="D"
              label="No trigger yet — observing only"
              sub="Stand aside; criteria not met for a managed entry."
              branchInfo="ends flow" />
            
          </div>
        </div>

        {/* footer */}
        <div style={{ padding: '14px 32px', borderTop: `1px solid ${TV.line}`,
          display: 'flex', alignItems: 'center', gap: 12, background: TV.panel }}>
          <button className="tv-btn ghost">← Back</button>
          <div style={{ fontSize: 12, color: TV.text3 }}>← / → to move · ⌘↵ to submit</div>
          <div style={{ flex: 1 }} />
          <button className="tv-btn primary">Continue →</button>
        </div>
      </div>
      </div>
    </div>);

};

// =============================================================
// SCREEN 5B — Adaptive branch moment (Step 5 of 7, just adapted)
// =============================================================
const ValidatorB = () => {
  const steps = [
  { label: 'HTF Bias',          leg: 'htf' },
  { label: 'Dealing Range',     leg: 'htf' },
  { label: 'HTF Liquidity',     leg: 'htf' },
  { label: 'Entry Trigger',     leg: 'ltf' },
  { label: 'LTF Sweep',         leg: 'ltf', adaptive: true },
  { label: 'Risk / Invalidation' },
  { label: 'Review' }];

  const answers = [
  { label: 'HTF Bias · 4H', value: 'Bullish — last BOS to upside', status: 'ok', concept: 'market structure' },
  { label: 'Dealing Range · 4H', value: 'Discount — price below 0.5 of range', status: 'ok', concept: 'dealing range' },
  { label: 'Liquidity', value: 'Sell-side swept at 71,640 (Asia low)', status: 'ok', concept: 'liquidity sweep' },
  { label: 'Entry Trigger', value: 'Sweep + structure shift on LTF', status: 'ok', concept: 'trade entries' }];


  return (
    <div className="tv-frame" style={{ display: 'flex', flexDirection: 'column' }}>
      <TVNav active="Validator" />
    <TTSubNav active="Validator"/>
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
      <SummaryRail
        answers={answers}
        adaptedNote='Because you chose "Sweep + LTF structure shift", the next 2 steps now ask about LTF sweep location and CHoCH confirmation — instead of FVG mitigation questions.'
        hint="Diamonds = adaptive steps · path differs based on your answers." />
      

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ padding: '14px 28px', borderBottom: `1px solid ${TV.line}`,
          display: 'flex', alignItems: 'center', gap: 16 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 600, color: TV.text }}>Trade Setup Validator</div>
            <div style={{ fontSize: 12, color: TV.text3, marginTop: 1 }}>BTCUSD · 1H · adaptive · 7 steps</div>
          </div>
          <div style={{ flex: 1 }} />
          <span className="tv-chip adapt"><span className="tv-dot" /> path adapted</span>
          <span className="tv-chip"><span style={{ color: TV.text3 }}>step</span> 5 / 7</span>
          <button className="tv-btn ghost" style={{ padding: '6px 10px' }}>Save & exit</button>
        </div>

        {/* step indicator with adapt cue */}
        <div style={{ padding: '20px 32px 12px', borderBottom: `1px solid ${TV.line}`, background: TV.panel,
          position: 'relative' }}>
          <StepIndicator steps={steps} currentIndex={4} adaptedAtIndex={4} />
          <div style={{
            marginTop: 14, padding: '8px 12px', borderRadius: 6,
            background: TV.adaptSoft, border: `1px solid rgba(139,122,214,.3)`,
            display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: TV.text
          }}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M2 4 L6 4 L8 2 L10 4 L14 4 M2 12 L6 12 L8 14 L10 12 L14 12" stroke={TV.adapt} strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <div>
              <span style={{ color: TV.adapt, fontWeight: 600 }}>Step 5 adapted.</span>
              <span style={{ color: TV.text2 }}> Replaced "FVG mitigation" with "LTF sweep & CHoCH" based on your Step 4 choice.</span>
            </div>
            <div style={{ flex: 1 }} />
            <span style={{ fontSize: 11, color: TV.text3, cursor: 'pointer' }}>why?</span>
          </div>
        </div>

        <div style={{ flex: 1, padding: '22px 32px', overflow: 'auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span className="tv-chip accent"><span className="tv-dot" /> LTF sweep</span>
            <span className="tv-chip">single select</span>
            <span className="tv-chip adapt">↳ adaptive</span>
          </div>

          <div style={{ fontSize: 22, fontWeight: 600, color: TV.text, lineHeight: 1.3, marginBottom: 6, maxWidth: 760 }}>
            On the lower timeframe, where has price swept liquidity that signals reversal?
          </div>
          <div style={{ fontSize: 15, color: TV.text2, marginBottom: 22, maxWidth: 760 }}>
            For a long entry you need a sell-side sweep on the LTF — followed by a CHoCH — before considering entry.
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 760 }}>
            <OptionCard letter="A" label="Equal lows on 5m — clean sweep with rejection wick"
            sub="Recent equal lows at 71,720 swept by ~8 ticks, immediate reclaim. Classic LTF sweep."
            selected={true} />
            <OptionCard letter="B" label="Session low (NY open) — partial wick"
            sub="NY session low at 71,690 touched but no decisive reclaim yet." />
            <OptionCard letter="C" label="Trendline liquidity (sloped lows)"
            sub="A sloped diagonal of lows on 15m has been broken and recovered." />
            <OptionCard letter="D" label="No qualifying sweep yet"
            sub="Stand aside until a clean LTF sweep prints." />
          </div>

          <div style={{ marginTop: 18, padding: '12px 14px', borderRadius: 6, background: TV.panel,
            border: `1px solid ${TV.line}`, fontSize: 13, color: TV.text2, maxWidth: 760 }}>
            <span style={{ color: TV.text3, textTransform: 'uppercase', fontSize: 10, fontWeight: 600, letterSpacing: '.06em' }}>Next adaptive step</span>
            <span style={{ marginLeft: 8 }}>If you confirm a sweep here, Step 6 asks about CHoCH timeframe & invalidation — otherwise it asks why you're standing aside.</span>
          </div>
        </div>

        <div style={{ padding: '14px 32px', borderTop: `1px solid ${TV.line}`,
          display: 'flex', alignItems: 'center', gap: 12, background: TV.panel }}>
          <button className="tv-btn ghost">← Back</button>
          <div style={{ fontSize: 12, color: TV.text3 }}>← / → to move · ⌘↵ to submit</div>
          <div style={{ flex: 1 }} />
          <button className="tv-btn primary">Continue →</button>
        </div>
      </div>
      </div>
    </div>);

};

// =============================================================
// SCREEN 5C — Summary / pre-trade reasoning record (the screenshot)
// =============================================================
const ValidatorC = () => {
  const [openIdx, setOpenIdx] = React.useState(null);

  const flowSteps = [
  { label: 'HTF Bias',          leg: 'htf' },
  { label: 'Dealing Range',     leg: 'htf' },
  { label: 'HTF Liquidity',     leg: 'htf' },
  { label: 'Entry Trigger',     leg: 'ltf' },
  { label: 'LTF Sweep',         leg: 'ltf', adaptive: true },
  { label: 'Risk' },
  { label: 'Review' }];


  const criteria = [
  {
    label: 'HTF Bias',
    concept: 'market structure',
    value: 'Bullish — 4H BOS to upside on 2026-05-22',
    detail: 'Most recent decisive break of structure is to the upside; lower-high not yet printed.',
    status: 'pass',
    step: 1,
    question: 'What is the higher-timeframe directional bias on the 4H chart?',
    chose: 'Bullish — last decisive break of structure is to the upside',
    otherOptions: ['Bearish — last decisive break is down', 'Unclear — both sides of structure still in play', 'Counter-trend — fighting the HTF bias']
  },
  {
    label: 'Dealing Range Location',
    concept: 'dealing range',
    value: 'Discount — price at 0.38 of 4H range',
    detail: 'Range from 71,200 (low) to 73,400 (high). Premium/discount split at 72,300.',
    status: 'pass',
    step: 2,
    question: 'Where is current price sitting inside the active dealing range?',
    chose: 'Discount — below 0.5 (priced at 0.38)',
    otherOptions: ['Premium — above 0.5', 'Equilibrium — near 0.5', 'Outside range — already extended']
  },
  {
    label: 'Liquidity Swept',
    concept: 'liquidity sweep',
    value: 'Sell-side — Asia session low (71,640) taken & reclaimed',
    detail: 'Clean sweep, no follow-through. Reclaim within 2 candles on 1H.',
    status: 'pass',
    step: 3,
    question: 'Has a relevant pool of liquidity been swept on the HTF?',
    chose: 'Sell-side — Asia session low at 71,640 swept and reclaimed',
    otherOptions: ['Buy-side — recent high taken', 'Both sides taken (chop)', 'No qualifying sweep yet']
  },
  {
    label: 'Entry Trigger',
    concept: 'trade entries',
    value: 'LTF sweep + CHoCH (5m)',
    detail: 'Equal lows at 71,720 swept on 5m, followed by CHoCH at 71,890.',
    status: 'pass',
    step: 4,
    question: 'What is your entry trigger on the lower timeframe?',
    chose: 'Liquidity sweep + structure shift (LTF)',
    otherOptions: ['Bullish Fair Value Gap', 'Inside an HTF bullish order block', 'No trigger yet — observing only']
  },
  {
    label: 'Confluence · unmitigated FVG',
    concept: 'fair value gap',
    value: 'Bullish 5m FVG between 71,815 – 71,845',
    detail: 'Created by 3-candle displacement out of the LTF sweep. Virgin (no return).',
    status: 'pass',
    step: 5,
    adaptive: true,
    question: 'On the lower timeframe, where has price swept liquidity that signals reversal?',
    chose: 'Equal lows on 5m — clean sweep at 71,720 with rejection wick',
    otherOptions: ['Session low (NY open) — partial wick', 'Trendline liquidity (sloped lows)', 'No qualifying sweep yet'],
    adaptNote: 'Step 5 came from the "sweep + LTF shift" branch — FVG mitigation questions were skipped.'
  },
  {
    label: 'Risk : Reward',
    concept: 'invalidation',
    value: '1 : 2.4 — below 1 : 3 target',
    detail: 'Entry 71,830 · Stop 71,640 · Target 72,300 (range midpoint). Tightening stop to OB high improves to 1 : 3.1.',
    status: 'warn',
    step: 6,
    question: 'Where is the structural invalidation, and what is the resulting R:R to the next opposing array?',
    chose: 'Stop below swept low (71,640) → 1 : 2.4 to range midpoint',
    otherOptions: ['Stop below OB high (71,790) → 1 : 3.1', 'Stop below previous structure low (71,500) → 1 : 1.9']
  }];

  const passed = criteria.filter((c) => c.status === 'pass').length;
  const total = criteria.length;
  const readiness = passed >= 5 ? 'READY' : passed >= 4 ? 'CONDITIONAL' : 'NOT READY';
  const readinessColor = readiness === 'READY' ? TV.ok : readiness === 'CONDITIONAL' ? TV.warn : TV.fail;

  return (
    <div className="tv-frame" style={{ display: 'flex', flexDirection: 'column' }}>
      <TVNav active="Validator" />
    <TTSubNav active="Validator"/>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'auto' }}>
        {/* header — designed to look right when screenshotted */}
        <div style={{ padding: '18px 32px 14px', borderBottom: `1px solid ${TV.line}`,
          display: 'flex', alignItems: 'center', gap: 16 }}>
          <div>
            <div style={{ fontSize: 11, color: TV.text3, fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase' }}>
              Pre-trade reasoning record
            </div>
            <div style={{ fontSize: 22, fontWeight: 600, color: TV.text, marginTop: 4 }}>
              BTCUSD · 1H · long bias
            </div>
          </div>
          <div style={{ flex: 1 }} />
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 12, color: TV.text3, fontWeight: 500 }}>2026-05-24 · 06:51 UTC</div>
            <div style={{ fontSize: 11, color: TV.text4, marginTop: 2 }}>Validator v0.1 · 7-step adaptive · ref ep. 14,18,22</div>
          </div>
        </div>

        {/* big verdict band */}
        <div style={{ padding: '22px 32px', display: 'flex', alignItems: 'center', gap: 28,
          borderBottom: `1px solid ${TV.line}`, background: TV.panel }}>
          <div style={{
            padding: '14px 22px', borderRadius: 10,
            border: `1.5px solid ${readinessColor}`,
            background: readiness === 'READY' ? TV.okSoft : readiness === 'CONDITIONAL' ? TV.warnSoft : TV.failSoft,
            minWidth: 220
          }}>
            <div style={{ fontSize: 11, color: TV.text3, fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase' }}>Readiness</div>
            <div style={{ fontSize: 32, fontWeight: 700, color: readinessColor, letterSpacing: '-.5px', lineHeight: 1.1, marginTop: 4 }}>
              {readiness}
            </div>
            <div style={{ fontSize: 13, color: TV.text2, marginTop: 4 }}>
              {passed} of {total} criteria met
              {readiness === 'CONDITIONAL' && ' · 1 warning'}
            </div>
          </div>

          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <div style={{ fontSize: 11, color: TV.text3, fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase' }}>
                Thesis
              </div>
              <span className="tv-chip adapt" style={{ fontSize: 10, padding: '1px 7px' }}>drafted by Claude</span>
              <div style={{ flex: 1 }} />
              <span style={{ fontSize: 11, color: TV.text3, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
                  <path d="M11.5 2.5 L13.5 4.5 L5 13 L2 14 L3 11 L11.5 2.5 Z" stroke={TV.text3} strokeWidth="1.4" strokeLinejoin="round" />
                </svg>
                click to edit
              </span>
            </div>
            <div
              contentEditable
              suppressContentEditableWarning
              spellCheck={false}
              style={{
                fontSize: 15, color: TV.text, lineHeight: 1.55,
                padding: '8px 10px', margin: '0 -10px',
                borderRadius: 6,
                border: `1px dashed ${TV.line}`,
                background: 'rgba(255,255,255,0.015)',
                outline: 'none',
                cursor: 'text'
              }}>
              
              Long entry on BTCUSD at 71,830. HTF bullish bias on 4H with price in discount of the dealing range.
              Sell-side liquidity has been swept and reclaimed; LTF confirmed via 5m sweep + CHoCH and a virgin
              bullish FVG. R:R is below target — consider tightening stop to the OB high before sizing in full.
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 6, padding: '0 2px' }}>
              <div style={{ fontSize: 11, color: TV.text4 }}>
                drafted from 6 answers · last edited 06:51 UTC
              </div>
              <div style={{ display: 'flex', gap: 10, fontSize: 11, color: TV.text3 }}>
                <span style={{ cursor: 'pointer' }}>↻ regenerate</span>
                <span style={{ cursor: 'pointer' }}>↩ revert to draft</span>
              </div>
            </div>
          </div>
        </div>

        {/* flow taken — completed step indicator */}
        <div style={{ padding: '18px 32px 4px' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 14 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: TV.text, letterSpacing: '.02em', textTransform: 'uppercase' }}>Flow taken</div>
            <div style={{ fontSize: 12, color: TV.text3 }}>7 steps · 1 adaptive branch · 4m 28s</div>
            <div style={{ flex: 1, height: 1, background: TV.line }} />
            <span className="tv-chip adapt"><span className="tv-dot" />step 5 adapted</span>
          </div>
          <StepIndicator steps={flowSteps} currentIndex={flowSteps.length} adaptedAtIndex={4} />
        </div>

        {/* criteria table */}
        <div style={{ padding: '20px 32px' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 12 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: TV.text, letterSpacing: '.02em', textTransform: 'uppercase' }}>Criteria</div>
            <div style={{ fontSize: 12, color: TV.text3 }}>click any row to see the question</div>
            <div style={{ flex: 1, height: 1, background: TV.line }} />
            <span className="tv-chip ok"><span className="tv-dot" />5 pass</span>
            <span className="tv-chip warn"><span className="tv-dot" />1 warn</span>
            <span className="tv-chip"><span style={{ color: TV.text4 }}>●</span>0 fail</span>
          </div>

          <div className="tv-card" style={{ overflow: 'hidden' }}>
            {criteria.map((c, i) => {
              const statusColor = c.status === 'pass' ? TV.ok : c.status === 'warn' ? TV.warn : TV.fail;
              const statusLabel = c.status === 'pass' ? 'PASS' : c.status === 'warn' ? 'WARN' : 'FAIL';
              const statusGlyph = c.status === 'pass' ? '✓' : c.status === 'warn' ? '!' : '×';
              const open = openIdx === i;
              return (
                <React.Fragment key={i}>
                  <div
                    onClick={() => setOpenIdx(open ? null : i)}
                    style={{
                      display: 'grid', gridTemplateColumns: '36px 200px 1fr 80px 24px',
                      padding: '14px 16px',
                      borderBottom: i < criteria.length - 1 && !open ? `1px solid ${TV.lineSoft}` : 'none',
                      alignItems: 'flex-start', gap: 14,
                      cursor: 'pointer',
                      background: open ? TV.panel2 : 'transparent',
                      transition: 'background .12s'
                    }}>
                    
                    <div style={{
                      width: 26, height: 26, borderRadius: '50%',
                      background: c.status === 'pass' ? TV.okSoft : c.status === 'warn' ? TV.warnSoft : TV.failSoft,
                      border: `1px solid ${statusColor}`,
                      color: statusColor, fontWeight: 700, fontSize: 14,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      marginTop: 1
                    }}>{statusGlyph}</div>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <div style={{ fontSize: 15, color: TV.text, fontWeight: 600 }}>{c.label}</div>
                        {c.adaptive &&
                        <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase',
                          color: TV.adapt, padding: '1px 5px', border: `1px solid rgba(139,122,214,.4)`,
                          borderRadius: 3, background: TV.adaptSoft }}>adapt</span>
                        }
                      </div>
                      <div style={{ fontSize: 11, color: TV.text3, marginTop: 2, letterSpacing: '.04em', textTransform: 'uppercase' }}>
                        step {c.step} · {c.concept}
                      </div>
                    </div>
                    <div>
                      <div style={{ fontSize: 15, color: TV.text, marginBottom: 3 }}>{c.value}</div>
                      <div style={{ fontSize: 13, color: TV.text2, lineHeight: 1.5 }}>{c.detail}</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.08em', color: statusColor }}>
                        {statusLabel}
                      </div>
                    </div>
                    <div style={{
                      color: TV.text3, fontSize: 14, marginTop: 4,
                      transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
                      transition: 'transform .15s'
                    }}>›</div>
                  </div>

                  {open &&
                  <div style={{
                    padding: '4px 16px 18px 60px',
                    borderBottom: i < criteria.length - 1 ? `1px solid ${TV.lineSoft}` : 'none',
                    background: TV.panel2,
                    display: 'flex', flexDirection: 'column', gap: 12
                  }}>
                      <div>
                        <div className="tv-uppercase" style={{ marginBottom: 4 }}>Question asked</div>
                        <div style={{ fontSize: 15, color: TV.text, fontWeight: 500, lineHeight: 1.45 }}>
                          {c.question}
                        </div>
                      </div>

                      <div>
                        <div className="tv-uppercase" style={{ marginBottom: 6 }}>Your answer</div>
                        <div style={{
                        padding: '10px 12px', borderRadius: 6,
                        border: `1px solid ${statusColor}`,
                        background: c.status === 'pass' ? TV.okSoft : c.status === 'warn' ? TV.warnSoft : TV.failSoft,
                        display: 'flex', alignItems: 'flex-start', gap: 10
                      }}>
                          <div style={{
                          width: 20, height: 20, borderRadius: 4,
                          border: `1px solid ${statusColor}`, background: statusColor, color: '#0d1018',
                          fontSize: 11, fontWeight: 700, display: 'flex',
                          alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 1
                        }}>✓</div>
                          <div style={{ fontSize: 14, color: TV.text, fontWeight: 500, flex: 1 }}>{c.chose}</div>
                        </div>
                      </div>

                      {c.otherOptions && c.otherOptions.length > 0 &&
                    <div>
                          <div className="tv-uppercase" style={{ marginBottom: 6 }}>Options not taken</div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                            {c.otherOptions.map((opt, j) =>
                        <div key={j} style={{
                          padding: '6px 12px', borderRadius: 4,
                          border: `1px dashed ${TV.line}`, background: 'transparent',
                          fontSize: 13, color: TV.text3, display: 'flex', alignItems: 'center', gap: 8
                        }}>
                                <span style={{
                            width: 14, height: 14, borderRadius: 3,
                            border: `1px solid ${TV.text4}`, flexShrink: 0
                          }} />
                                {opt}
                              </div>
                        )}
                          </div>
                        </div>
                    }

                      {c.adaptNote &&
                    <div style={{
                      padding: '8px 12px', borderRadius: 6,
                      background: TV.adaptSoft, border: `1px solid rgba(139,122,214,.3)`,
                      fontSize: 12, color: TV.text2, lineHeight: 1.5
                    }}>
                          <span style={{ color: TV.adapt, fontWeight: 600 }}>↳ adaptive · </span>
                          {c.adaptNote}
                        </div>
                    }

                      <div style={{ display: 'flex', gap: 12, fontSize: 12, color: TV.text3, marginTop: 2 }}>
                        <span style={{ cursor: 'pointer' }}>↻ change my answer</span>
                        <span style={{ cursor: 'pointer' }}>↗ jump to step {c.step}</span>
                        <span style={{ cursor: 'pointer' }}>📖 source: ep. 14, 18, 22</span>
                      </div>
                    </div>
                  }
                </React.Fragment>);

            })}
          </div>
        </div>

        {/* execution block */}
        <div style={{ padding: '4px 32px 22px', display: 'grid', gridTemplateColumns: '1.3fr 1fr', gap: 16 }}>
          <div className="tv-card" style={{ padding: 16 }}>
            <div className="tv-uppercase" style={{ marginBottom: 10 }}>Execution plan</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '8px 18px', fontSize: 15 }}>
              <div style={{ color: TV.text3 }}>Entry</div>
              <div style={{ color: TV.text, fontWeight: 600 }}>71,830 (FVG mid)</div>
              <div style={{ color: TV.text3 }}>Stop</div>
              <div style={{ color: TV.text }}>71,640 — below swept low</div>
              <div style={{ color: TV.text3 }}>Target 1</div>
              <div style={{ color: TV.text }}>72,300 — range midpoint</div>
              <div style={{ color: TV.text3 }}>Target 2</div>
              <div style={{ color: TV.text2 }}>72,950 — premium array high</div>
              <div style={{ color: TV.text3 }}>Invalidation</div>
              <div style={{ color: TV.text }}>Close below 71,640 on 1H</div>
            </div>
          </div>
          <div className="tv-card" style={{ padding: 16 }}>
            <div className="tv-uppercase" style={{ marginBottom: 10 }}>Concepts referenced</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
              <span className="tv-chip">market structure</span>
              <span className="tv-chip">bias</span>
              <span className="tv-chip">dealing range</span>
              <span className="tv-chip">liquidity sweep</span>
              <span className="tv-chip">fair value gap</span>
              <span className="tv-chip">trade entries</span>
            </div>
            <div style={{ fontSize: 12, color: TV.text3, lineHeight: 1.55 }}>
              Question logic drawn from ingested transcripts. Concepts shown are the only ones currently active in the validator — extend by adding new episodes.
            </div>
          </div>
        </div>

        {/* footer actions */}
        <div style={{ padding: '14px 32px', borderTop: `1px solid ${TV.line}`,
          display: 'flex', alignItems: 'center', gap: 12, background: TV.panel, marginTop: 'auto' }}>
          <button className="tv-btn ghost">← Edit answers</button>
          <div style={{ fontSize: 12, color: TV.text3 }}>screenshot-ready · ⌘S to save to journal</div>
          <div style={{ flex: 1 }} />
          <button className="tv-btn">Copy as text</button>
          <button className="tv-btn">Save to journal</button>
          <button className="tv-btn primary">Mark as taken →</button>
        </div>
      </div>
    </div>);

};

Object.assign(window, { ValidatorA, ValidatorB, ValidatorC, ValidatorD });

// =============================================================
// SCREEN 5D — C-style question screen
// Hybrid: question structure of A/B + polish/density of C +
// step-indicator breadcrumb prominent at top.
// =============================================================
function ValidatorD() {
  const steps = [
  { label: 'HTF Bias',          leg: 'htf' },
  { label: 'Dealing Range',     leg: 'htf' },
  { label: 'HTF Liquidity',     leg: 'htf' },
  { label: 'Entry Trigger',     leg: 'ltf' },
  { label: 'LTF Sweep',         leg: 'ltf', adaptive: true },
  { label: 'Risk / Invalidation' },
  { label: 'Review' }];

  const answers = [
  { label: 'HTF Bias', concept: 'market structure', value: 'Bullish — 4H BOS up', status: 'pass' },
  { label: 'Dealing Range', concept: 'dealing range', value: 'Discount (0.38 of range)', status: 'pass' },
  { label: 'Liquidity', concept: 'liquidity sweep', value: 'Sell-side · Asia low 71,640', status: 'pass' },
  { label: 'Entry Trigger', concept: 'trade entries', value: 'Sweep + LTF structure shift', status: 'pass' }];


  return (
    <div className="tv-frame" style={{ display: 'flex', flexDirection: 'column' }}>
      <TVNav active="Validator" />
    <TTSubNav active="Validator"/>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* C-style header */}
        <div style={{ padding: '18px 32px 14px', borderBottom: `1px solid ${TV.line}`,
          display: 'flex', alignItems: 'center', gap: 16 }}>
          <div>
            <div style={{ fontSize: 11, color: TV.text3, fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase' }}>
              Pre-trade reasoning · in progress
            </div>
            <div style={{ fontSize: 22, fontWeight: 600, color: TV.text, marginTop: 4 }}>
              BTCUSD · 1H · long bias
            </div>
          </div>
          <div style={{ flex: 1 }} />
          <span className="tv-chip adapt"><span className="tv-dot" /> path adapted</span>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 12, color: TV.text3, fontWeight: 500 }}>2026-05-24 · 06:50 UTC</div>
            <div style={{ fontSize: 11, color: TV.text4, marginTop: 2 }}>Validator v0.1 · step 5 / 7</div>
          </div>
        </div>

        {/* Breadcrumb step indicator — full-width band */}
        <div style={{ padding: '20px 32px 18px', borderBottom: `1px solid ${TV.line}`, background: TV.panel }}>
          <div className="tv-uppercase" style={{ marginBottom: 14 }}>Flow</div>
          <StepIndicator steps={steps} currentIndex={4} adaptedAtIndex={4} />
        </div>

        {/* Body: question card + answers-so-far card */}
        <div style={{ flex: 1, padding: '20px 32px', display: 'grid',
          gridTemplateColumns: '1.5fr 1fr', gap: 16, overflow: 'auto', alignContent: 'start' }}>

          {/* Question card */}
          <div className="tv-card" style={{ padding: 22, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div className="tv-uppercase">Step 5 · LTF Sweep</div>
              <div style={{ display: 'flex', gap: 6 }}>
                <span className="tv-chip accent"><span className="tv-dot" /> liquidity sweep</span>
                <span className="tv-chip adapt">↳ adaptive</span>
                <span className="tv-chip">single select</span>
              </div>
            </div>

            <div>
              <div style={{ fontSize: 22, fontWeight: 600, color: TV.text, lineHeight: 1.3 }}>
                On the lower timeframe, where has price swept liquidity that signals reversal?
              </div>
              <div style={{ fontSize: 14, color: TV.text2, marginTop: 8, lineHeight: 1.55 }}>
                For a long entry you need a sell-side sweep on the LTF — followed by a CHoCH — before considering entry.
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <OptionCard letter="A" label="Equal lows on 5m — clean sweep with rejection wick"
              sub="Recent equal lows at 71,720 swept by ~8 ticks, immediate reclaim."
              selected={true} />
              <OptionCard letter="B" label="Session low (NY open) — partial wick"
              sub="NY session low at 71,690 touched but no decisive reclaim yet." />
              <OptionCard letter="C" label="Trendline liquidity (sloped lows)"
              sub="A sloped diagonal of lows on 15m has been broken and recovered." />
              <OptionCard letter="D" label="No qualifying sweep yet"
              sub="Stand aside until a clean LTF sweep prints." />
            </div>

            <div style={{
              padding: '10px 14px', borderRadius: 6, background: TV.adaptSoft,
              border: `1px solid rgba(139,122,214,.3)`, fontSize: 13, color: TV.text, lineHeight: 1.5,
              display: 'flex', alignItems: 'center', gap: 10
            }}>
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                <path d="M2 4 L6 4 L8 2 L10 4 L14 4 M2 12 L6 12 L8 14 L10 12 L14 12" stroke={TV.adapt} strokeWidth="1.5" strokeLinecap="round" />
              </svg>
              <div>
                <span style={{ color: TV.adapt, fontWeight: 600 }}>Why this question?</span>
                <span style={{ color: TV.text2 }}> Your Step 4 choice (sweep + LTF structure shift) replaced the FVG mitigation branch with LTF-sweep questions.</span>
              </div>
            </div>
          </div>

          {/* Setup so far — C-style mini criteria card */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div className="tv-card" style={{ overflow: 'hidden' }}>
              <div style={{ padding: '12px 16px', borderBottom: `1px solid ${TV.line}`,
                display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div className="tv-uppercase">Setup so far</div>
                <span className="tv-chip ok"><span className="tv-dot" /> 4 / 4 pass</span>
              </div>
              {answers.map((a, i) =>
              <div key={i} style={{
                display: 'grid', gridTemplateColumns: '26px 1fr',
                padding: '12px 16px',
                borderBottom: i < answers.length - 1 ? `1px solid ${TV.lineSoft}` : 'none',
                alignItems: 'flex-start', gap: 12
              }}>
                  <div style={{
                  width: 22, height: 22, borderRadius: '50%',
                  background: TV.okSoft, border: `1px solid ${TV.ok}`,
                  color: TV.ok, fontWeight: 700, fontSize: 12,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  marginTop: 1
                }}>✓</div>
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
                      <div style={{ fontSize: 14, color: TV.text, fontWeight: 600 }}>{a.label}</div>
                      <div style={{ fontSize: 10, color: TV.text4, fontWeight: 500, letterSpacing: '.04em', textTransform: 'uppercase' }}>
                        {a.concept}
                      </div>
                    </div>
                    <div style={{ fontSize: 13, color: TV.text2, marginTop: 2 }}>{a.value}</div>
                  </div>
                </div>
              )}
            </div>

            <div className="tv-card" style={{ padding: 14 }}>
              <div className="tv-uppercase" style={{ marginBottom: 8 }}>Remaining</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 7, fontSize: 13, color: TV.text2 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: TV.text }}>5 · LTF Sweep</span>
                  <span className="tv-chip adapt" style={{ fontSize: 10, padding: '1px 6px' }}>active</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>6 · Risk / Invalidation</span><span style={{ color: TV.text4 }}>pending</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>7 · Review</span><span style={{ color: TV.text4 }}>pending</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div style={{ padding: '14px 32px', borderTop: `1px solid ${TV.line}`,
          display: 'flex', alignItems: 'center', gap: 12, background: TV.panel }}>
          <button className="tv-btn ghost">← Back</button>
          <div style={{ fontSize: 12, color: TV.text3 }}>← / → to move · ⌘↵ to submit · ⌘S to save & exit</div>
          <div style={{ flex: 1 }} />
          <button className="tv-btn">Skip & flag for review</button>
          <button className="tv-btn primary">Continue →</button>
        </div>
      </div>
    </div>);

}