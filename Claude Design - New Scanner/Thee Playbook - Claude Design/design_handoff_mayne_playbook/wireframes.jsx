// wireframes.jsx — sketchy wireframe primitives + 12 screen variations
// Aesthetic: paper #faf7f0, ink #1a1a1a, accent #d64525 (orange), ok #5b8c5a (green)
// Fonts: Caveat (annotations/headlines), Kalam (body), JetBrains Mono (data)

// ---------- shared tokens & primitives ----------
const WF = {
  paper: '#faf7f0',
  paperAlt: '#f3efe5',
  ink: '#1a1a1a',
  ink2: '#3a342c',
  ink3: 'rgba(26,26,26,0.55)',
  ink4: 'rgba(26,26,26,0.35)',
  hair: 'rgba(26,26,26,0.18)',
  accent: '#d64525',
  accentSoft: 'rgba(214,69,37,0.12)',
  ok: '#5b8c5a',
  okSoft: 'rgba(91,140,90,0.15)',
  hand: "'Inter', system-ui, sans-serif",
  body: "'Inter', system-ui, sans-serif",
  mono: "'Inter', system-ui, sans-serif"
};

// inject once
if (!document.getElementById('wf-styles')) {
  const s = document.createElement('style');
  s.id = 'wf-styles';
  s.textContent = `
    .wf-frame{background:${WF.paper};color:${WF.ink};font-family:${WF.body};
      background-image:radial-gradient(${WF.hair} 1px,transparent 1px);
      background-size:18px 18px;background-position:9px 9px;
      width:100%;height:100%;position:relative;overflow:hidden;font-size:14px;line-height:1.35}
    .wf-box{border:1.5px solid ${WF.ink};border-radius:4px;background:rgba(255,255,255,0.45);position:relative}
    .wf-box.dashed{border-style:dashed}
    .wf-box.soft{border-color:${WF.ink3}}
    .wf-rot-a{transform:rotate(-0.25deg)}
    .wf-rot-b{transform:rotate(0.3deg)}
    .wf-rot-c{transform:rotate(-0.15deg)}
    .wf-h{font-family:${WF.hand};font-weight:600;letter-spacing:.2px}
    .wf-mono{font-family:${WF.mono};letter-spacing:-.1px;font-size:12px;font-variant-numeric:tabular-nums;font-feature-settings:"tnum","cv11";font-weight:500}
    .wf-bar{height:8px;border-radius:2px;background:${WF.ink};opacity:.85}
    .wf-bar.thin{height:5px;opacity:.55}
    .wf-bar.short{width:40%}
    .wf-bar.med{width:65%}
    .wf-bar.full{width:92%}
    .wf-chip{display:inline-flex;align-items:center;gap:6px;padding:3px 9px;border:1.25px solid ${WF.ink2};
      border-radius:999px;font-family:${WF.hand};font-size:16px;background:${WF.paper}}
    .wf-chip.accent{border-color:${WF.accent};color:${WF.accent};background:${WF.accentSoft}}
    .wf-chip.ok{border-color:${WF.ok};color:${WF.ok};background:${WF.okSoft}}
    .wf-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;
      padding:9px 18px;border:1.5px solid ${WF.ink};border-radius:6px;font-family:${WF.hand};
      font-weight:600;font-size:18px;background:${WF.paper};cursor:pointer}
    .wf-btn.primary{background:${WF.accent};color:${WF.paper};border-color:${WF.accent}}
    .wf-btn.ghost{background:transparent}
    .wf-dot{width:9px;height:9px;border-radius:50%;display:inline-block}
    .wf-dot.ink{background:${WF.ink}}
    .wf-dot.accent{background:${WF.accent}}
    .wf-dot.ok{background:${WF.ok}}
    .wf-dot.empty{background:transparent;border:1.5px solid ${WF.ink2}}
    .wf-hatch{background-image:repeating-linear-gradient(45deg,${WF.ink3} 0,${WF.ink3} 1px,transparent 1px,transparent 7px)}
    .wf-shade{background-image:repeating-linear-gradient(135deg,rgba(0,0,0,.05) 0,rgba(0,0,0,.05) 2px,transparent 2px,transparent 6px)}
    .wf-arrow{font-family:${WF.hand};color:${WF.accent};font-size:18px;font-weight:600}
    .wf-pencil{color:${WF.ink3};font-family:${WF.hand};font-size:15px}
    .wf-note{position:absolute;font-family:${WF.hand};color:${WF.accent};font-size:14px;
      transform:rotate(-2deg);pointer-events:none;white-space:nowrap}
    .wf-note::before{content:'';position:absolute;left:-14px;top:8px;width:10px;height:1px;
      background:${WF.accent};transform:rotate(20deg)}
    .wf-frame *{box-sizing:border-box}
    .wf-scroll{overflow:hidden}
  `;
  document.head.appendChild(s);
}

// ---------- tiny building blocks ----------
const Logo = ({ size = 16 }) =>
<span style={{ fontFamily: WF.hand, fontWeight: 700, fontSize: size, letterSpacing: '.3px' }}>
    The Mayne Playbook
  </span>;


const SideNav = ({ active = 'Dashboard', items = ['Dashboard', 'Quiz', 'Scanner', 'Transcripts'] }) =>
<div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '18px 14px',
  borderRight: `1.5px solid ${WF.ink}`, background: WF.paperAlt, minWidth: 140 }}>
    <div style={{ marginBottom: 14 }}><Logo size={18} /></div>
    {items.map((it) =>
  <div key={it} style={{
    padding: '7px 10px', borderRadius: 5,
    fontFamily: WF.body, fontSize: 15,
    background: it === active ? WF.ink : 'transparent',
    color: it === active ? WF.paper : WF.ink,
    border: it === active ? `1.5px solid ${WF.ink}` : '1.5px solid transparent'
  }}>{it}</div>
  )}
    <div style={{ flex: 1 }} />
    <div className="wf-pencil" style={{ fontSize: 13, opacity: .7 }}>day 47 · streak 12</div>
  </div>;


const TopNav = ({ active = 'Dashboard', items = ['Dashboard', 'Quiz', 'Scanner', 'Transcripts'] }) =>
<div style={{ display: 'flex', alignItems: 'center', gap: 18, padding: '12px 22px',
  borderBottom: `1.5px solid ${WF.ink}`, background: WF.paperAlt }}>
    <Logo size={18} />
    <div style={{ flex: 1 }} />
    {items.map((it) =>
  <div key={it} style={{
    padding: '5px 12px', borderRadius: 4, fontFamily: WF.body, fontSize: 15,
    background: it === active ? WF.ink : 'transparent',
    color: it === active ? WF.paper : WF.ink
  }}>{it}</div>
  )}
    <div className="wf-pencil" style={{ marginLeft: 18, fontSize: 13 }}>streak · 12d</div>
  </div>;


// Sketchy candlestick chart placeholder
const ChartBox = ({ h = 180, label = 'candlestick chart · 4h · ES' }) =>
<div className="wf-box" style={{ height: h, padding: 10, display: 'flex', flexDirection: 'column' }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: WF.mono, fontSize: 11, color: WF.ink3 }}>
      <span>{label}</span>
      <span>5742.25 ▲</span>
    </div>
    <div style={{ flex: 1, display: 'flex', alignItems: 'flex-end', justifyContent: 'space-around', gap: 3, padding: '10px 4px' }}>
      {[18, 28, 22, 38, 30, 46, 40, 55, 48, 62, 58, 70, 64, 52, 60, 72, 66, 78].map((v, i) => {
      const up = i % 3 !== 0;
      return (
        <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', height: '100%', justifyContent: 'flex-end' }}>
            <div style={{ width: 1, height: v * 0.4, background: WF.ink2 }} />
            <div style={{ width: 7, height: v * 0.6, background: up ? WF.ok : WF.accent, border: `1px solid ${WF.ink}` }} />
            <div style={{ width: 1, height: v * 0.25, background: WF.ink2 }} />
          </div>);

    })}
    </div>
    <div className="wf-pencil" style={{ fontSize: 13, opacity: .7, marginTop: 4 }}>↳ pattern marked here</div>
  </div>;


const Sparkline = ({ trend = 'up' }) =>
<svg viewBox="0 0 80 24" width="80" height="24" style={{ display: 'block' }}>
    <polyline
    points={trend === 'up' ? "0,18 10,15 20,17 30,12 40,14 50,9 60,11 70,6 80,4" :
    trend === 'down' ? "0,6 10,9 20,7 30,12 40,10 50,15 60,13 70,18 80,20" :
    "0,12 10,10 20,14 30,11 40,13 50,10 60,14 70,12 80,11"}
    fill="none" stroke={trend === 'up' ? WF.ok : trend === 'down' ? WF.accent : WF.ink2} strokeWidth="1.5" />
  </svg>;


const HandLine = ({ w = '100%' }) =>
<div style={{ width: w, height: 1.5, background: WF.ink, opacity: .7, borderRadius: 1 }} />;


// =============================================================
// SCREEN 1 — DASHBOARD (3 variations)
// =============================================================

// 1A · Quiz-Hero: sidebar + giant "today's quiz" card, weak concepts as chip row, scanner pulse
const DashA = () =>
<div className="wf-frame" style={{ display: 'flex', flexDirection: 'column' }}>
    <TopNav active="Dashboard" />
    <div style={{ flex: 1, padding: '16px 28px 20px', overflow: 'hidden', display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      {/* 1/3 quiz · 2/3 scanner */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 16, minHeight: 0 }}>

        {/* hero quiz card — 1/3 */}
        <div className="wf-box wf-rot-a" style={{ padding: 18, background: WF.paper, flex: 1,
            display: 'flex', alignItems: 'center', gap: 18, minHeight: 0, overflow: 'hidden' }}>
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span className="wf-chip ok"><span className="wf-dot ok" /> ready</span>
              <span className="wf-pencil">generated 06:00</span>
            </div>
            <div className="wf-h" style={{ fontSize: 26, lineHeight: 1.1 }}>Today's Quiz</div>
            <div style={{ color: WF.ink3, fontSize: 14 }}>
              8 questions · ~6 min · weighted toward order blocks & FVGs
            </div>
          </div>

          {/* buttons stacked on the right */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'stretch', flexShrink: 0 }}>
            <button className="wf-btn primary" style={{ padding: '9px 18px', fontSize: 15 }}>Start quiz →</button>
            <button className="wf-btn ghost" style={{ padding: '9px 18px', fontSize: 15 }}>Preview</button>
          </div>

          <div className="wf-note" style={{ right: 16, top: 12 }}>generated by cron @ 06:00 daily</div>
        </div>

        {/* scanner pulse — 2/3, two rows */}
        <div className="wf-box soft" style={{ padding: 14, flex: 2,
            display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
            <div className="wf-h" style={{ fontSize: 16 }}>Scanner pulse</div>
            <div className="wf-pencil">last scan · 4m ago →</div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gridTemplateRows: '1fr 1fr',
              gap: 10, flex: 1, minHeight: 0 }}>
            {[
              ['ES', 'forming', 'up'], ['NQ', 'none', 'flat'], ['BTC', 'active', 'up'],
              ['EURUSD', 'none', 'down'], ['AAPL', 'forming', 'up'], ['GOLD', 'none', 'flat'],
              ['ETH', 'forming', 'up'], ['TSLA', 'active', 'up'], ['GBPUSD', 'none', 'flat'],
              ['USDJPY', 'forming', 'down'], ['OIL', 'none', 'down'], ['DXY', 'none', 'up'],
            ].map(([t, s, tr]) =>
          <div key={t} className="wf-box" style={{ padding: '8px 10px', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span className="wf-mono" style={{ fontWeight: 600, fontSize: 13 }}>{t}</span>
                  <span className={`wf-dot ${s === 'active' ? 'accent' : s === 'forming' ? 'ink' : 'empty'}`} />
                </div>
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', minHeight: 0 }}>
                  <Sparkline trend={tr} />
                </div>
                <div className="wf-pencil" style={{ fontSize: 11 }}>{s}</div>
              </div>
          )}
          </div>
        </div>
      </div>
    </div>
  </div>;


// 1B · Split: top nav, quiz left / scanner right 50/50, weak concepts strip bottom
const DashB = () =>
<div className="wf-frame" style={{ display: 'flex', flexDirection: 'column' }}>
    <TopNav active="Dashboard" />
    <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, padding: 18 }}>
      {/* quiz panel */}
      <div className="wf-box wf-rot-a" style={{ padding: 18, display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <div className="wf-h" style={{ fontSize: 22 }}>Daily Quiz</div>
          <span className="wf-chip ok"><span className="wf-dot ok" /> ready</span>
        </div>
        <div className="wf-h" style={{ fontSize: 54, lineHeight: 1, margin: '18px 0 4px' }}>8</div>
        <div className="wf-pencil">questions waiting · weighted to your weak spots</div>
        <div style={{ flex: 1 }} />
        <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
          <button className="wf-btn primary" style={{ flex: 1 }}>Start →</button>
          <button className="wf-btn ghost">Skip</button>
        </div>
      </div>

      {/* scanner panel */}
      <div className="wf-box wf-rot-c" style={{ padding: 18, display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
          <div className="wf-h" style={{ fontSize: 22 }}>Scanner</div>
          <span className="wf-pencil">2 forming · 1 active</span>
        </div>
        {[
      ['BTC', 'active', 'order block tap · 1h', 'up'],
      ['ES', 'forming', 'FVG forming · 4h', 'up'],
      ['AAPL', 'forming', 'sweep + BOS · D', 'flat'],
      ['NQ', '—', 'no setup', 'down']].
      map(([t, s, why, tr]) =>
      <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 4px', borderBottom: `1px dashed ${WF.hair}` }}>
            <span className={`wf-dot ${s === 'active' ? 'accent' : s === 'forming' ? 'ink' : 'empty'}`} />
            <span className="wf-mono" style={{ width: 60, fontWeight: 600 }}>{t}</span>
            <span style={{ flex: 1, fontSize: 14, color: WF.ink2 }}>{why}</span>
            <Sparkline trend={tr} />
          </div>
      )}
        <div className="wf-pencil" style={{ marginTop: 'auto', paddingTop: 8 }}>open scanner →</div>
      </div>
    </div>
    {/* weak concepts strip */}
    <div style={{ borderTop: `1.5px solid ${WF.ink}`, padding: '12px 22px', background: WF.paperAlt, display: 'flex', alignItems: 'center', gap: 12 }}>
      <span className="wf-h" style={{ fontSize: 16 }}>Weak →</span>
      <span className="wf-chip accent">Order Block 38%</span>
      <span className="wf-chip accent">FVG 44%</span>
      <span className="wf-chip">Liquidity 61%</span>
      <span className="wf-chip">BOS 70%</span>
      <span className="wf-chip">Killzones 82%</span>
      <span style={{ flex: 1 }} />
      <span className="wf-pencil">based on last 30 questions</span>
    </div>
  </div>;


// 1C · Feed: vertical feed, quiz card, weak concepts ring, scanner sparkline row, recent activity
const DashC = () =>
<div className="wf-frame" style={{ display: 'flex', flexDirection: 'column' }}>
    <TopNav active="Dashboard" />
    <div style={{ flex: 1, padding: '18px 24px', overflow: 'hidden', minHeight: 0 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 16 }}>
        {/* left rail: weak concepts ring (moved from right) */}
        <div className="wf-box wf-rot-b" style={{ padding: 18 }}>
          <div className="wf-h" style={{ fontSize: 18, marginBottom: 10 }}>Weak concepts</div>
          <div className="wf-pencil" style={{ marginBottom: 14 }}>% correct over last 30</div>
          {[
        ['Order Block', 38, 'accent'],
        ['Fair Value Gap', 44, 'accent'],
        ['Liquidity Sweep', 61, 'ink'],
        ['BOS / CHoCH', 70, 'ink'],
        ['Killzones', 82, 'ok'],
        ['Optimal Trade Entry', 55, 'accent']].
        map(([name, pct, c]) =>
        <div key={name} style={{ marginBottom: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, marginBottom: 3 }}>
                <span>{name}</span>
                <span className="wf-mono">{pct}%</span>
              </div>
              <div style={{ height: 6, background: WF.paperAlt, border: `1px solid ${WF.hair}`, borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${pct}%`, background: c === 'accent' ? WF.accent : c === 'ok' ? WF.ok : WF.ink }} />
              </div>
            </div>
        )}
          <div className="wf-pencil" style={{ marginTop: 8 }}>↳ next quiz weights ≈ 60% to top 3</div>
        </div>

        {/* right feed col (moved from left) */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="wf-box wf-rot-a" style={{ padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
              <span className="wf-h" style={{ fontSize: 14, textTransform: 'uppercase', letterSpacing: 1 }}>06:00 · today</span>
              <span className="wf-chip ok" style={{ fontSize: 14 }}><span className="wf-dot ok" /> quiz ready</span>
            </div>
            <div className="wf-h" style={{ fontSize: 22, marginBottom: 4 }}>8 questions on order blocks & FVGs</div>
            <div className="wf-pencil" style={{ marginBottom: 12 }}>generated from ep. 14, 18, 22 · ~6 min</div>
            <button className="wf-btn primary">Start →</button>
          </div>

          <div className="wf-box soft" style={{ padding: 14 }}>
            <div className="wf-h" style={{ fontSize: 14, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6, color: WF.ink3 }}>scanner · 4m ago</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8 }}>
              {[['BTC', 'active'], ['ES', 'forming'], ['AAPL', 'forming']].map(([t, s]) =>
            <div key={t} className="wf-box" style={{ padding: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span className="wf-mono" style={{ fontWeight: 600 }}>{t}</span>
                    <span className={`wf-dot ${s === 'active' ? 'accent' : 'ink'}`} />
                  </div>
                  <Sparkline trend="up" />
                  <div className="wf-pencil" style={{ fontSize: 12 }}>{s}</div>
                </div>
            )}
            </div>
          </div>

          <div className="wf-box soft" style={{ padding: 14 }}>
            <div className="wf-h" style={{ fontSize: 14, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6, color: WF.ink3 }}>yesterday</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span className="wf-dot ok" />
              <span style={{ fontSize: 15 }}>completed quiz · 6/8 · missed 2 on FVG</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>;


// =============================================================
// SCREEN 2 — QUIZ (3 variations)
// =============================================================

// 2A · Chart-Forward: big chart top, question + options below, sidebar progress
const QuizA = () =>
<div className="wf-frame" style={{ display: 'flex' }}>
    {/* progress rail */}
    <div style={{ width: 64, borderRight: `1.5px solid ${WF.ink}`, padding: '18px 0', display: 'flex',
    flexDirection: 'column', alignItems: 'center', gap: 10, background: WF.paperAlt }}>
      <div className="wf-h" style={{ fontSize: 13, writingMode: 'vertical-rl', transform: 'rotate(180deg)', color: WF.ink3 }}>
        Q 3 of 8
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
        {[1, 2, 3, 4, 5, 6, 7, 8].map((n) =>
      <div key={n} style={{
        width: 24, height: 24, borderRadius: '50%',
        border: `1.5px solid ${WF.ink}`,
        background: n < 3 ? WF.ok : n === 3 ? WF.accent : WF.paper,
        color: n <= 3 ? WF.paper : WF.ink,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: WF.mono, fontSize: 11
      }}>{n}</div>
      )}
      </div>
    </div>

    <div style={{ flex: 1, padding: '16px 24px', display: 'flex', flexDirection: 'column', gap: 12, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className="wf-chip accent">Order Block</span>
          <span className="wf-chip">identify pattern</span>
          <span className="wf-pencil">ep. 14 · "OB basics"</span>
        </div>
        <span className="wf-pencil">⌘+1-4 to answer</span>
      </div>

      <ChartBox h={260} label="ES · 4h · last 18 candles" />

      <div className="wf-h" style={{ fontSize: 20, lineHeight: 1.2 }}>
        Where is the most recent bullish <u style={{ textDecorationStyle: 'wavy', textDecorationColor: WF.accent }}>order block</u> on this chart?
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {[
      ['A', 'Candle 4 — last down close before the impulse up'],
      ['B', 'Candle 9 — biggest red bar in the sequence'],
      ['C', 'Candle 12 — bullish engulfing pattern'],
      ['D', 'Candle 16 — high of the recent range']].
      map(([k, t]) =>
      <div key={k} className="wf-box" style={{ padding: '8px 12px', display: 'flex', gap: 10, alignItems: 'flex-start',
        background: k === 'A' ? WF.accentSoft : 'rgba(255,255,255,.5)' }}>
            <div style={{ width: 20, height: 20, border: `1.5px solid ${WF.ink}`, borderRadius: 4,
          display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: WF.hand, fontWeight: 600, fontSize: 13 }}>
              {k}
            </div>
            <div style={{ fontSize: 14, flex: 1 }}>{t}</div>
          </div>
      )}
      </div>

      {/* post-answer feedback preview (from panel B) */}
      <div className="wf-box" style={{ padding: '10px 12px', background: WF.okSoft, borderColor: WF.ok }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <div className="wf-h" style={{ fontSize: 15, color: WF.ok, flexShrink: 0 }}>
            ✓ correct
          </div>
          <div style={{ fontSize: 13, color: WF.ink2, lineHeight: 1.45 }}>
            An order block is the last opposing candle before an impulsive displacement — here, candle 4 is the last down-close before price ran higher.
          </div>
        </div>
        <div className="wf-pencil" style={{ marginTop: 4, fontSize: 12 }}>↳ source: ep. 14, 02:18</div>
      </div>

      <div style={{ display: 'flex', gap: 10, marginTop: 'auto' }}>
        <button className="wf-btn ghost">Why?</button>
        <button className="wf-btn ghost">Skip</button>
        <div style={{ flex: 1 }} />
        <button className="wf-btn primary">Next →</button>
      </div>
    </div>
  </div>;


// 2B · Split-Pane: chart left, question/options right, feedback in-pane
const QuizB = () =>
<div className="wf-frame" style={{ display: 'flex', flexDirection: 'column' }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '10px 18px', borderBottom: `1.5px solid ${WF.ink}` }}>
      <Logo size={16} />
      <span className="wf-pencil">·</span>
      <span className="wf-h" style={{ fontSize: 16 }}>Daily Quiz</span>
      <div style={{ flex: 1 }} />
      <div style={{ display: 'flex', gap: 5 }}>
        {[1, 2, 3, 4, 5, 6, 7, 8].map((n) =>
      <div key={n} style={{ width: 18, height: 6, borderRadius: 3,
        background: n < 4 ? WF.ok : n === 4 ? WF.accent : WF.hair }} />
      )}
      </div>
      <span className="wf-mono" style={{ color: WF.ink3, marginLeft: 8 }}>4 / 8</span>
      <button className="wf-btn ghost" style={{ padding: '4px 10px', fontSize: 14 }}>esc · exit</button>
    </div>

    <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1.1fr 1fr' }}>
      {/* chart pane */}
      <div style={{ padding: 18, borderRight: `1.5px solid ${WF.ink}`, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span className="wf-h" style={{ fontSize: 16 }}>BTCUSD · 1h</span>
          <span className="wf-mono" style={{ fontSize: 12, color: WF.ink3 }}>72,450 · +1.2%</span>
        </div>
        <ChartBox h={260} label="annotate where the FVG is →" />
        <div className="wf-pencil">↳ click on a candle to mark your answer</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <span className="wf-chip">marked: candle 11</span>
          <span className="wf-chip">clear</span>
        </div>
      </div>

      {/* question pane */}
      <div style={{ padding: '18px 22px', display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <span className="wf-chip accent">FVG</span>
          <span className="wf-chip">true / false</span>
        </div>
        <div className="wf-h" style={{ fontSize: 24, lineHeight: 1.25 }}>
          The Fair Value Gap on this chart was created by a 3-candle bullish displacement and price has not yet returned to fill it.
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {['True', 'False'].map((t) =>
        <div key={t} className="wf-box" style={{ padding: '12px 14px', fontSize: 18, fontFamily: WF.hand, fontWeight: 600 }}>
              <span style={{ marginRight: 10, color: WF.ink3 }}>○</span>{t}
            </div>
        )}
        </div>

        {/* post-answer feedback preview */}
        <div className="wf-box" style={{ padding: 14, background: WF.okSoft, borderColor: WF.ok, marginTop: 6 }}>
          <div className="wf-h" style={{ fontSize: 16, color: WF.ok, marginBottom: 4 }}>
            ✓ correct — feedback preview
          </div>
          <div style={{ fontSize: 14, color: WF.ink2 }}>
            FVG = imbalance left by candle 2 in a 3-candle move where wicks of candle 1 & 3 don't overlap. Price seeks to rebalance.
          </div>
          <div className="wf-pencil" style={{ marginTop: 6 }}>↳ source: ep. 18, 03:42</div>
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 'auto' }}>
          <button className="wf-btn ghost">Why?</button>
          <div style={{ flex: 1 }} />
          <button className="wf-btn primary">Next →</button>
        </div>
      </div>
    </div>
  </div>;


// 2C · Stepper: minimal centered card, dots top, single column, distraction-free
const QuizC = () =>
<div className="wf-frame" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '20px 28px' }}>
    {/* minimal top */}
    <div style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
      <Logo size={15} />
      <div style={{ display: 'flex', gap: 7 }}>
        {[1, 2, 3, 4, 5, 6, 7, 8].map((n) =>
      <span key={n} className={`wf-dot ${n < 5 ? 'ok' : n === 5 ? 'accent' : 'empty'}`} />
      )}
      </div>
      <span className="wf-pencil">5 / 8 · 3:14</span>
    </div>

    <div className="wf-box wf-rot-a" style={{ width: '78%', maxWidth: 680, padding: 24, background: WF.paper }}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
        <span className="wf-chip accent">Liquidity</span>
        <span className="wf-chip">short answer</span>
      </div>
      <div className="wf-h" style={{ fontSize: 26, lineHeight: 1.25, marginBottom: 16 }}>
        In ICT terms, what is "buy-side liquidity" and where is it typically resting?
      </div>

      <div className="wf-box" style={{ padding: 12, minHeight: 90, background: 'rgba(255,255,255,.5)' }}>
        <div className="wf-pencil" style={{ fontSize: 15 }}>Type your answer… Claude will grade against ep. 22 definition.</div>
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 14 }}>
        <span className="wf-pencil">↵ submit · ⌘k for hint</span>
        <div style={{ flex: 1 }} />
        <button className="wf-btn ghost">I don't know</button>
        <button className="wf-btn primary">Submit →</button>
      </div>
    </div>

    <div className="wf-pencil" style={{ marginTop: 14, fontSize: 14 }}>
      one question · one screen · no scrolling
    </div>

    <div className="wf-note" style={{ left: 30, bottom: 30, transform: 'rotate(2deg)' }}>
      "Cmd+Enter" power-user shortcut
    </div>
  </div>;


// =============================================================
// SCREEN 3 — TRANSCRIPT ADMIN (3 variations)
// =============================================================

// 3A · Single textarea, meta up top, big paste area, save right
const TransA = () =>
<div className="wf-frame" style={{ display: 'flex', flexDirection: 'column' }}>
    <TopNav active="Transcripts" />
    <div style={{ flex: 1, padding: '20px 28px', display: 'flex', flexDirection: 'column', gap: 14, overflow: 'hidden', minHeight: 0 }}>
      <div className="wf-h" style={{ fontSize: 24 }}>Add transcript</div>

      <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr 120px 1fr', gap: 10, alignItems: 'center' }}>
        <label className="wf-pencil">episode #</label>
        <div className="wf-box" style={{ padding: '8px 10px', fontFamily: WF.mono }}>23</div>
        <label className="wf-pencil">date</label>
        <div className="wf-box" style={{ padding: '8px 10px', fontFamily: WF.mono }}>2026-05-22</div>
        <label className="wf-pencil">title</label>
        <div className="wf-box" style={{ padding: '8px 10px', gridColumn: '2 / span 3' }}>
          Killzones & Session Liquidity — London Open into NY AM
        </div>
        <label className="wf-pencil">tags</label>
        <div style={{ gridColumn: '2 / span 3', display: 'flex', gap: 6 }}>
          <span className="wf-chip">killzones</span>
          <span className="wf-chip">sessions</span>
          <span className="wf-chip">liquidity</span>
          <span className="wf-chip soft" style={{ borderStyle: 'dashed', color: WF.ink3 }}>+ add</span>
        </div>
      </div>

      <div className="wf-box wf-rot-a" style={{ flex: 1, padding: 14, position: 'relative', background: WF.paper, minHeight: 160 }}>
        <div className="wf-pencil" style={{ position: 'absolute', top: 8, right: 14, fontSize: 13 }}>paste full transcript here · ~7,400 words</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div className="wf-bar full" /><div className="wf-bar med" /><div className="wf-bar full" />
          <div className="wf-bar" style={{ width: '85%' }} /><div className="wf-bar med" />
          <div className="wf-bar full" /><div className="wf-bar" style={{ width: '72%' }} />
          <div className="wf-bar short" />
          <div className="wf-pencil" style={{ marginTop: 6, fontSize: 13 }}>… 348 more lines</div>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="wf-pencil">⏱ Claude will extract ~12 concepts on save</span>
        <div style={{ flex: 1 }} />
        <button className="wf-btn ghost">Cancel</button>
        <button className="wf-btn primary">Save transcript</button>
      </div>
    </div>
  </div>;


// 3B · Two-column: episode list left, paste area right
const TransB = () =>
<div className="wf-frame" style={{ display: 'flex', flexDirection: 'column' }}>
    <TopNav active="Transcripts" />
    <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '260px 1fr', overflow: 'hidden' }}>
      {/* list */}
      <div style={{ borderRight: `1.5px solid ${WF.ink}`, padding: '14px 12px', background: WF.paperAlt, overflow: 'hidden' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <span className="wf-h" style={{ fontSize: 16 }}>Episodes</span>
          <button className="wf-btn primary" style={{ padding: '4px 10px', fontSize: 14 }}>+ new</button>
        </div>
        <div className="wf-box" style={{ padding: '6px 8px', marginBottom: 10, fontSize: 13, color: WF.ink3 }}>🔍 search…</div>
        {[
      ['23', 'Killzones & Session Liquidity', 'new', true],
      ['22', 'Buy-side / Sell-side Liquidity', '3d ago'],
      ['21', 'Optimal Trade Entry', '5d ago'],
      ['20', 'BOS vs CHoCH revisited', '1w ago'],
      ['18', 'FVG deep dive', '2w ago'],
      ['14', 'Order Block basics', '3w ago']].
      map(([ep, t, when, active]) =>
      <div key={ep} style={{ padding: '8px 8px', borderRadius: 4, marginBottom: 3,
        background: active ? WF.ink : 'transparent',
        color: active ? WF.paper : WF.ink }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: WF.mono, fontSize: 12, opacity: .7 }}>
              <span>ep {ep}</span><span>{when}</span>
            </div>
            <div style={{ fontSize: 14, fontFamily: WF.body }}>{t}</div>
          </div>
      )}
      </div>

      {/* editor */}
      <div style={{ padding: '18px 22px', display: 'flex', flexDirection: 'column', gap: 12, overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <span className="wf-mono" style={{ color: WF.ink3 }}>ep 23</span>
          <div className="wf-box" style={{ padding: '6px 10px', flex: 1, fontSize: 16, fontFamily: WF.hand, fontWeight: 600 }}>
            Killzones & Session Liquidity — London Open into NY AM
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <span className="wf-chip">killzones</span>
          <span className="wf-chip">sessions</span>
          <span className="wf-chip">liquidity</span>
          <span className="wf-chip soft" style={{ borderStyle: 'dashed', color: WF.ink3 }}>+ tag</span>
        </div>

        <div className="wf-box" style={{ flex: 1, padding: 14, background: WF.paper, position: 'relative' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div className="wf-bar full" /><div className="wf-bar med" /><div className="wf-bar full" />
            <div className="wf-bar" style={{ width: '80%' }} /><div className="wf-bar short" />
            <div className="wf-bar full" /><div className="wf-bar" style={{ width: '70%' }} />
            <div className="wf-bar med" />
          </div>
          <div className="wf-pencil" style={{ position: 'absolute', right: 14, bottom: 10, fontSize: 13 }}>7,412 words · 348 lines</div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span className="wf-chip ok"><span className="wf-dot ok" /> saved 2m ago</span>
          <span className="wf-pencil">12 concepts extracted</span>
          <div style={{ flex: 1 }} />
          <button className="wf-btn ghost">Delete</button>
          <button className="wf-btn primary">Re-extract concepts</button>
        </div>
      </div>
    </div>
  </div>;


// 3C · Minimal centered: one-shot paste form, list shown beneath as compact table
const TransC = () =>
<div className="wf-frame" style={{ padding: '24px 32px', display: 'flex', flexDirection: 'column', gap: 18, overflow: 'hidden' }}>
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
      <div>
        <Logo size={16} />
        <div className="wf-h" style={{ fontSize: 26, marginTop: 6 }}>Transcripts</div>
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        {['Dashboard', 'Quiz', 'Scanner', 'Transcripts'].map((it) =>
      <span key={it} className="wf-chip" style={{ background: it === 'Transcripts' ? WF.ink : WF.paper, color: it === 'Transcripts' ? WF.paper : WF.ink }}>
            {it}
          </span>
      )}
      </div>
    </div>

    {/* paste form, single row of meta + textarea */}
    <div className="wf-box wf-rot-a" style={{ padding: 16, background: WF.paper }}>
      <div style={{ display: 'flex', gap: 10, marginBottom: 10, alignItems: 'center' }}>
        <div className="wf-box" style={{ padding: '6px 10px', width: 70, fontFamily: WF.mono }}>ep #</div>
        <div className="wf-box" style={{ padding: '6px 10px', flex: 1 }}>title of episode…</div>
        <span className="wf-pencil">tags →</span>
        <div className="wf-box dashed" style={{ padding: '6px 10px', width: 160, color: WF.ink3 }}>order block, fvg…</div>
      </div>
      <div className="wf-box dashed" style={{ padding: 14, minHeight: 120, background: 'rgba(255,255,255,.4)', position: 'relative' }}>
        <div className="wf-pencil" style={{ fontSize: 16 }}>paste transcript text here…</div>
        <div className="wf-pencil" style={{ position: 'absolute', right: 14, bottom: 10, fontSize: 12 }}>⌘V to paste · ⌘↵ to save</div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 10, gap: 8 }}>
        <button className="wf-btn ghost">Clear</button>
        <button className="wf-btn primary">Save & extract concepts</button>
      </div>
    </div>

    {/* compact table */}
    <div style={{ flex: 1, overflow: 'hidden' }}>
      <div className="wf-h" style={{ fontSize: 16, marginBottom: 6 }}>Saved · 23 episodes</div>
      <div className="wf-box" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '60px 1fr 200px 100px 60px',
        padding: '7px 12px', borderBottom: `1.5px solid ${WF.ink}`,
        fontFamily: WF.mono, fontSize: 11, textTransform: 'uppercase', color: WF.ink3, background: WF.paperAlt }}>
          <span>ep</span><span>title</span><span>tags</span><span>concepts</span><span>added</span>
        </div>
        {[
      ['23', 'Killzones & Session Liquidity', 'killzones · sessions', '12', '2d'],
      ['22', 'Buy/Sell-side Liquidity', 'liquidity · sweep', '9', '3d'],
      ['21', 'Optimal Trade Entry', 'OTE · fib', '8', '5d'],
      ['20', 'BOS vs CHoCH revisited', 'structure', '11', '7d'],
      ['18', 'FVG deep dive', 'fvg · imbalance', '14', '14d']].
      map((row, i) =>
      <div key={i} style={{ display: 'grid', gridTemplateColumns: '60px 1fr 200px 100px 60px',
        padding: '8px 12px', borderBottom: `1px dashed ${WF.hair}`, fontSize: 14, alignItems: 'center' }}>
            <span className="wf-mono" style={{ color: WF.ink3 }}>{row[0]}</span>
            <span>{row[1]}</span>
            <span className="wf-pencil" style={{ fontSize: 13 }}>{row[2]}</span>
            <span className="wf-mono">{row[3]}</span>
            <span className="wf-mono" style={{ color: WF.ink3 }}>{row[4]}</span>
          </div>
      )}
      </div>
    </div>
  </div>;


// =============================================================
// SCREEN 4 — SETUP SCANNER (3 variations)
// =============================================================

// 4A · Dense table + detail drawer (right)
const ScanA = () =>
<div className="wf-frame" style={{ display: 'flex', flexDirection: 'column' }}>
    <TopNav active="Scanner" />
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
      {/* table */}
      <div style={{ flex: 1.3, padding: '18px 20px', overflow: 'hidden' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
          <div className="wf-h" style={{ fontSize: 22 }}>Setup Scanner</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span className="wf-pencil">scanned 4m ago</span>
            <button className="wf-btn ghost" style={{ padding: '4px 10px', fontSize: 14 }}>↻ rescan</button>
            <button className="wf-btn ghost" style={{ padding: '4px 10px', fontSize: 14 }}>+ ticker</button>
          </div>
        </div>

        <div className="wf-box" style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '24px 80px 80px 1fr 70px 90px 100px',
          padding: '8px 12px', borderBottom: `1.5px solid ${WF.ink}`,
          fontFamily: WF.mono, fontSize: 11, textTransform: 'uppercase', color: WF.ink3, background: WF.paperAlt }}>
            <span></span><span>ticker</span><span>status</span><span>signal</span><span>tf</span><span>conf</span><span>chart</span>
          </div>
          {[
        ['BTC', 'active', 'order block tap @ 71,800 · bullish OB', '1h', 82, 'up', true],
        ['ES', 'forming', 'FVG forming under premium · waiting', '4h', 64, 'up'],
        ['AAPL', 'forming', 'sweep of equal lows + BOS · LTF entry', 'D', 58, 'flat'],
        ['EURUSD', '—', 'no setup · ranging', '1h', 12, 'down'],
        ['NQ', '—', 'no setup', '4h', 8, 'down'],
        ['GOLD', 'watching', 'approaching daily OB', 'D', 41, 'up']].
        map(([t, s, why, tf, conf, tr, sel], i) =>
        <div key={t} style={{ display: 'grid', gridTemplateColumns: '24px 80px 80px 1fr 70px 90px 100px',
          padding: '10px 12px', borderBottom: `1px dashed ${WF.hair}`, alignItems: 'center',
          background: sel ? WF.accentSoft : 'transparent' }}>
              <span className={`wf-dot ${s === 'active' ? 'accent' : s === 'forming' ? 'ink' : s === 'watching' ? 'ink' : 'empty'}`} />
              <span className="wf-mono" style={{ fontWeight: 600 }}>{t}</span>
              <span className="wf-pencil" style={{ fontSize: 13 }}>{s}</span>
              <span style={{ fontSize: 14 }}>{why}</span>
              <span className="wf-mono" style={{ color: WF.ink3 }}>{tf}</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{ flex: 1, height: 5, background: WF.paperAlt, border: `1px solid ${WF.hair}`, borderRadius: 2 }}>
                  <div style={{ height: '100%', width: `${conf}%`, background: conf > 70 ? WF.accent : conf > 40 ? WF.ink : WF.ink3 }} />
                </div>
                <span className="wf-mono" style={{ fontSize: 11 }}>{conf}</span>
              </div>
              <Sparkline trend={tr} />
            </div>
        )}
        </div>
      </div>

      {/* detail drawer */}
      <div style={{ width: 340, borderLeft: `1.5px solid ${WF.ink}`, padding: '18px 18px', background: WF.paperAlt,
      display: 'flex', flexDirection: 'column', gap: 12, overflow: 'hidden' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <span className="wf-mono" style={{ fontSize: 16, fontWeight: 600 }}>BTCUSD</span>
            <span className="wf-chip accent" style={{ marginLeft: 8 }}><span className="wf-dot accent" /> active</span>
          </div>
          <span className="wf-pencil">×</span>
        </div>
        <ChartBox h={140} label="BTC · 1h" />
        <div>
          <div className="wf-h" style={{ fontSize: 15, marginBottom: 4 }}>Why this is flagged</div>
          <div style={{ fontSize: 14, color: WF.ink2, lineHeight: 1.45 }}>
            Bullish order block at 71,800 was just tapped after a 3-candle FVG impulse. Confluence with London killzone.
          </div>
        </div>
        <div>
          <div className="wf-h" style={{ fontSize: 15, marginBottom: 4 }}>Concepts triggered</div>
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            <span className="wf-chip accent">Order Block</span>
            <span className="wf-chip">FVG</span>
            <span className="wf-chip">Killzone</span>
          </div>
        </div>
        <div style={{ flex: 1 }} />
        <div className="wf-box dashed" style={{ padding: 10, minHeight: 60 }}>
          <div className="wf-pencil" style={{ fontSize: 13 }}>notes… (e.g. "waiting for LTF CHoCH")</div>
        </div>
        <button className="wf-btn ghost" style={{ fontSize: 14 }}>Open in TradingView →</button>
      </div>
    </div>
  </div>;


// 4B · Card grid (3 columns), each ticker = card with sparkline + signal
const ScanB = () =>
<div className="wf-frame" style={{ display: 'flex', flexDirection: 'column' }}>
    <TopNav active="Scanner" />
    <div style={{ flex: 1, padding: '18px 22px', overflow: 'hidden' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
        <div className="wf-h" style={{ fontSize: 22 }}>Watchlist · 6 tickers</div>
        <div style={{ display: 'flex', gap: 6 }}>
          <span className="wf-chip accent">1 active</span>
          <span className="wf-chip">2 forming</span>
          <span className="wf-chip soft" style={{ color: WF.ink3 }}>3 quiet</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 14 }}>
        {[
      ['BTC', 'active', 'Order block tap', '1h', 82, 'up', WF.accent],
      ['ES', 'forming', 'FVG forming', '4h', 64, 'up', WF.ink],
      ['AAPL', 'forming', 'Sweep + BOS', 'D', 58, 'flat', WF.ink],
      ['GOLD', 'watching', 'Approaching OB', 'D', 41, 'up', WF.ink3],
      ['EURUSD', 'quiet', 'No setup', '1h', 12, 'down', WF.ink4],
      ['NQ', 'quiet', 'No setup', '4h', 8, 'down', WF.ink4]].
      map(([t, s, why, tf, conf, tr, c], i) =>
      <div key={t} className={`wf-box ${i % 2 ? 'wf-rot-c' : 'wf-rot-a'}`} style={{ padding: 14, background: WF.paper }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <span className="wf-mono" style={{ fontSize: 18, fontWeight: 600 }}>{t}</span>
              <span className="wf-chip" style={{ borderColor: c, color: c, fontSize: 14 }}>
                <span className="wf-dot" style={{ background: c }} /> {s}
              </span>
            </div>
            <Sparkline trend={tr} />
            <div className="wf-h" style={{ fontSize: 17, marginTop: 6 }}>{why}</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
              <span className="wf-pencil">{tf} · conf {conf}</span>
              <span className="wf-pencil">→</span>
            </div>
            <div style={{ height: 5, background: WF.paperAlt, border: `1px solid ${WF.hair}`, borderRadius: 2, marginTop: 6 }}>
              <div style={{ height: '100%', width: `${conf}%`, background: c }} />
            </div>
          </div>
      )}
      </div>

      <div className="wf-note" style={{ left: 24, bottom: 20, transform: 'rotate(-1deg)' }}>
        ↳ cards re-rank by confidence every scan
      </div>
    </div>
  </div>;


// 4C · Ranked list (left) + big detail panel (right) — split, focus on one setup
const ScanC = () =>
<div className="wf-frame" style={{ display: 'flex', flexDirection: 'column' }}>
    <TopNav active="Scanner" />
    <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '220px 1fr', overflow: 'hidden', minHeight: 0 }}>
      {/* ranked list */}
      <div style={{ borderRight: `1.5px solid ${WF.ink}`, padding: '14px 12px', background: WF.paperAlt,
      display: 'flex', flexDirection: 'column', gap: 6, overflow: 'hidden' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
          <span className="wf-h" style={{ fontSize: 16 }}>Ranked</span>
          <span className="wf-pencil" style={{ fontSize: 12 }}>by conf</span>
        </div>
        {[
      ['BTC', 82, 'active', true],
      ['ES', 64, 'forming'],
      ['AAPL', 58, 'forming'],
      ['GOLD', 41, 'watching'],
      ['EURUSD', 12, 'quiet'],
      ['NQ', 8, 'quiet']].
      map(([t, conf, s, sel]) =>
      <div key={t} className="wf-box" style={{ padding: '8px 10px',
        background: sel ? WF.ink : WF.paper,
        color: sel ? WF.paper : WF.ink,
        borderColor: sel ? WF.ink : WF.hair }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span className="wf-mono" style={{ fontWeight: 600 }}>{t}</span>
              <span className={`wf-dot ${s === 'active' ? 'accent' : s === 'forming' ? sel ? 'empty' : 'ink' : 'empty'}`}
          style={sel && s === 'forming' ? { background: WF.paper } : {}} />
            </div>
            <div className="wf-pencil" style={{ fontSize: 12, color: sel ? 'rgba(250,247,240,.7)' : WF.ink3 }}>
              {s} · conf {conf}
            </div>
          </div>
      )}
        <div style={{ flex: 1 }} />
        <button className="wf-btn ghost" style={{ fontSize: 13, padding: '4px 10px' }}>+ ticker</button>
      </div>

      {/* detail panel */}
      <div style={{ padding: '20px 26px', display: 'flex', flexDirection: 'column', gap: 14, overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <span className="wf-mono" style={{ fontSize: 24, fontWeight: 600 }}>BTCUSD</span>
          <span className="wf-chip accent"><span className="wf-dot accent" /> active setup</span>
          <span className="wf-pencil">1h · scanned 4m ago</span>
          <div style={{ flex: 1 }} />
          <span className="wf-mono" style={{ color: WF.ink3 }}>71,840  ▲ +1.2%</span>
        </div>

        <ChartBox h={200} label="BTC · 1h · order block highlighted" />

        <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 14 }}>
          <div className="wf-box" style={{ padding: 12 }}>
            <div className="wf-h" style={{ fontSize: 16, marginBottom: 6 }}>Why this is flagged</div>
            <div style={{ fontSize: 14, color: WF.ink2, lineHeight: 1.5 }}>
              Bullish order block at <span className="wf-mono">71,800</span> just tapped after a 3-candle FVG impulse off NY low.
              Confluence: London killzone, sweep of equal lows, LTF CHoCH on 5m.
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
              <span className="wf-chip accent">Order Block</span>
              <span className="wf-chip accent">FVG</span>
              <span className="wf-chip">Sweep</span>
              <span className="wf-chip">CHoCH</span>
              <span className="wf-chip">Killzone</span>
            </div>
          </div>
          <div className="wf-box" style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div className="wf-h" style={{ fontSize: 16 }}>Plan</div>
            <div style={{ fontSize: 14 }}>
              <div>Entry · <span className="wf-mono">71,820</span></div>
              <div>Stop · <span className="wf-mono">71,640</span></div>
              <div>Target · <span className="wf-mono">72,500</span></div>
              <div className="wf-pencil" style={{ marginTop: 4 }}>R:R ≈ 3.8</div>
            </div>
            <div className="wf-box dashed" style={{ padding: 8, fontSize: 13, color: WF.ink3, marginTop: 'auto' }}>
              notes / journal entry…
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>;


// ---------- export ----------
Object.assign(window, {
  DashA, DashB, DashC,
  QuizA, QuizB, QuizC,
  TransA, TransB, TransC,
  ScanA, ScanB, ScanC
});