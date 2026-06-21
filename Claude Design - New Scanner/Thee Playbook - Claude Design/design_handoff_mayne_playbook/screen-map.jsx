// screen-map.jsx — Static IA flow diagram for handoff
// Shows which screens lead to which. Not interactive — reference only.

const ScreenMapHF = () => {
  // Screens grouped by lane. Coordinates are in SVG units (1300 × 900 canvas).
  const screens = [
    // entry / daily loop
    {id: 'dashboard',     label: 'Dashboard',       lane: 'home',     x:  600, y:  60, w: 200, h: 70, hint: 'home · daily entry'},

    // quiz loop
    {id: 'quiz',          label: 'Quiz',            lane: 'learn',    x:  220, y:  200, w: 180, h: 60, hint: 'one Q at a time · 8 total'},
    {id: 'quiz-complete', label: 'Quiz Complete',   lane: 'learn',    x:  220, y:  310, w: 180, h: 60, hint: 'score · mastery delta · recap'},

    // trade loop
    {id: 'scanner',       label: 'Scanner',         lane: 'trade',    x:  920, y:  200, w: 180, h: 60, hint: 'watchlist · setup status'},
    {id: 'validator',     label: 'Validator',       lane: 'trade',    x:  920, y:  310, w: 180, h: 60, hint: 'adaptive 7-step check'},
    {id: 'journal',       label: 'Journal',         lane: 'trade',    x:  920, y:  450, w: 180, h: 60, hint: 'trade + quiz history'},
    {id: 'reports',       label: 'Reports',         lane: 'trade',    x:  920, y:  560, w: 180, h: 60, hint: 'analytics across all data'},

    // knowledge surface
    {id: 'concepts',      label: 'Concepts',        lane: 'learn',    x:  600, y:  450, w: 200, h: 70, hint: 'every concept · mastery · sources'},

    // admin (overflow menu)
    {id: 'settings',      label: 'Settings',        lane: 'admin',    x:  600, y:  720, w: 200, h: 60, hint: 'schedule · watchlist · …'},
    {id: 'transcripts',   label: 'Transcripts',     lane: 'admin',    x:  220, y:  720, w: 180, h: 60, hint: 'admin · paste Mayne episodes', dashed: true},
  ];

  // Arrows: { from, to, label, kind }
  // kind: 'flow' (solid orange), 'data' (dashed purple — populates the destination), 'ref' (gray — cross-reference)
  const arrows = [
    // quiz loop
    {from: 'dashboard',  to: 'quiz',          label: 'Start quiz →',         kind: 'flow', curve: 'left'},
    {from: 'quiz',       to: 'quiz-complete', label: 'finish Q8',            kind: 'flow'},
    {from: 'quiz-complete', to: 'dashboard',  label: 'Done →',               kind: 'flow', curve: 'leftBack'},
    {from: 'quiz-complete', to: 'journal',    label: 'auto-saved',           kind: 'data', curve: 'cross1'},
    {from: 'quiz-complete', to: 'concepts',   label: 'jump to concept',      kind: 'ref',  curve: 'down'},

    // trade loop
    {from: 'dashboard',  to: 'scanner',       label: 'Open scanner →',       kind: 'flow', curve: 'right'},
    {from: 'scanner',    to: 'validator',     label: 'Validate setup →',     kind: 'flow'},
    {from: 'validator',  to: 'journal',       label: 'Save to journal →',    kind: 'flow'},
    {from: 'journal',    to: 'reports',       label: '',                     kind: 'data'},
    {from: 'journal',    to: 'validator',     label: 'Re-open',              kind: 'ref',  curve: 'back'},

    // knowledge
    {from: 'dashboard',  to: 'concepts',      label: 'Targeting →',          kind: 'flow', curve: 'down'},
    {from: 'concepts',   to: 'quiz',          label: '"Test me" →',          kind: 'flow', curve: 'left2'},
    {from: 'reports',    to: 'concepts',      label: 'click bar',            kind: 'ref',  curve: 'back2'},

    // admin
    {from: 'dashboard',  to: 'settings',      label: 'nav · ⚙',              kind: 'ref',  curve: 'downRight'},
    {from: 'settings',   to: 'transcripts',   label: 'admin · transcripts',  kind: 'ref'},
  ];

  // utility — find screen by id
  const find = (id) => screens.find(s => s.id === id);

  // anchor point on an edge of a screen rect facing toward another
  const anchor = (from, to, side) => {
    const f = find(from), t = find(to);
    if (side === 'auto') {
      if (Math.abs(t.x - f.x) > Math.abs(t.y - f.y)) {
        side = t.x > f.x ? 'right' : 'left';
      } else {
        side = t.y > f.y ? 'bottom' : 'top';
      }
    }
    switch (side) {
      case 'right':  return [f.x + f.w, f.y + f.h / 2];
      case 'left':   return [f.x,        f.y + f.h / 2];
      case 'bottom': return [f.x + f.w / 2, f.y + f.h];
      case 'top':    return [f.x + f.w / 2, f.y];
    }
  };

  // arrow path builder (cubic bezier)
  const arrowPath = ({from, to, curve}) => {
    let p1, p2;
    switch (curve) {
      case 'left':       p1 = anchor(from, to, 'left');   p2 = anchor(to, from, 'top');   break;
      case 'leftBack':   p1 = anchor(from, to, 'right');  p2 = anchor(to, from, 'left');  break;
      case 'cross1':     p1 = anchor(from, to, 'right');  p2 = anchor(to, from, 'left');  break;
      case 'down':       p1 = anchor(from, to, 'bottom'); p2 = anchor(to, from, 'top');   break;
      case 'downRight':  p1 = anchor(from, to, 'bottom'); p2 = anchor(to, from, 'top');   break;
      case 'right':      p1 = anchor(from, to, 'right');  p2 = anchor(to, from, 'top');   break;
      case 'back':       p1 = anchor(from, to, 'left');   p2 = anchor(to, from, 'bottom'); break;
      case 'left2':      p1 = anchor(from, to, 'left');   p2 = anchor(to, from, 'bottom'); break;
      case 'back2':      p1 = anchor(from, to, 'left');   p2 = anchor(to, from, 'right');  break;
      default:           p1 = anchor(from, to, 'auto');   p2 = anchor(to, from, 'auto');   break;
    }
    const [x1, y1] = p1, [x2, y2] = p2;
    const dx = Math.abs(x2 - x1), dy = Math.abs(y2 - y1);
    const c = Math.min(80, Math.max(20, (dx + dy) * 0.25));
    // bias control points along the natural curve
    const cp1 = [x1 + (x2 > x1 ? c : x2 < x1 ? -c : 0), y1 + (y2 > y1 ? c * 0.4 : -c * 0.4)];
    const cp2 = [x2 - (x2 > x1 ? c : x2 < x1 ? -c : 0), y2 - (y2 > y1 ? c * 0.4 : -c * 0.4)];
    return {d: `M ${x1} ${y1} C ${cp1[0]} ${cp1[1]}, ${cp2[0]} ${cp2[1]}, ${x2} ${y2}`,
            mid: [(x1 + x2) / 2, (y1 + y2) / 2 - 6], end: [x2, y2]};
  };

  const colorFor = (kind) => kind === 'flow' ? TV.accent : kind === 'data' ? TV.adapt : TV.text3;
  const dashFor  = (kind) => kind === 'flow' ? null : kind === 'data' ? '5 4' : '2 3';
  const laneColor = (lane) => ({
    home:  TV.accent,
    learn: TV.ok,
    trade: TV.adapt,
    admin: TV.text3,
  })[lane] || TV.text3;

  return (
    <div className="tv-frame" style={{display: 'flex', flexDirection: 'column'}}>
      <TVNav active="Screen map"/>

      <div style={{flex: 1, overflow: 'auto', padding: '20px 28px', display: 'flex', flexDirection: 'column'}}>
        <div style={{display: 'flex', alignItems: 'baseline', gap: 16, marginBottom: 16}}>
          <div>
            <div className="tv-uppercase">Information architecture</div>
            <div style={{fontSize: 22, fontWeight: 600, color: TV.text, marginTop: 4}}>Screen map</div>
            <div style={{fontSize: 13, color: TV.text3, marginTop: 4}}>
              Primary user flows, data dependencies, and cross-references between all screens. Reference for routing & handoff.
            </div>
          </div>
          <div style={{flex: 1}}/>
          <Legend/>
        </div>

        <div className="tv-card" style={{flex: 1, padding: 18, background: TV.panel,
            display: 'flex', justifyContent: 'center', alignItems: 'center'}}>
          <svg viewBox="0 0 1300 830" width="100%" style={{maxWidth: 1300, display: 'block'}}>
            <defs>
              <marker id="arr-accent" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"
                  markerUnits="strokeWidth">
                <path d="M 0 0 L 6 3 L 0 6 z" fill={TV.accent}/>
              </marker>
              <marker id="arr-adapt" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"
                  markerUnits="strokeWidth">
                <path d="M 0 0 L 6 3 L 0 6 z" fill={TV.adapt}/>
              </marker>
              <marker id="arr-text3" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"
                  markerUnits="strokeWidth">
                <path d="M 0 0 L 6 3 L 0 6 z" fill={TV.text3}/>
              </marker>
            </defs>

            {/* lane backgrounds */}
            <rect x={130} y={170} width={380} height={420} rx={10}
                  fill="none" stroke={TV.lineSoft} strokeDasharray="3 4"/>
            <text x={140} y={190} fontSize="10" fontWeight="700" fill={TV.ok}
                  style={{letterSpacing: '.1em', textTransform: 'uppercase'}}>Learning loop</text>

            <rect x={820} y={170} width={380} height={490} rx={10}
                  fill="none" stroke={TV.lineSoft} strokeDasharray="3 4"/>
            <text x={830} y={190} fontSize="10" fontWeight="700" fill={TV.adapt}
                  style={{letterSpacing: '.1em', textTransform: 'uppercase'}}>Trading loop</text>

            <rect x={130} y={690} width={780} height={110} rx={10}
                  fill="none" stroke={TV.lineSoft} strokeDasharray="3 4"/>
            <text x={140} y={710} fontSize="10" fontWeight="700" fill={TV.text3}
                  style={{letterSpacing: '.1em', textTransform: 'uppercase'}}>Admin · "…" menu</text>

            {/* arrows (rendered before boxes so they go behind) */}
            {arrows.map((a, i) => {
              const {d, mid} = arrowPath(a);
              const color = colorFor(a.kind);
              const dash = dashFor(a.kind);
              const markerId = a.kind === 'flow' ? 'arr-accent' : a.kind === 'data' ? 'arr-adapt' : 'arr-text3';
              return (
                <g key={i}>
                  <path d={d} fill="none" stroke={color} strokeWidth={a.kind === 'flow' ? 2 : 1.5}
                        strokeDasharray={dash} markerEnd={`url(#${markerId})`}
                        opacity={a.kind === 'ref' ? 0.7 : 0.95}/>
                  {a.label && (
                    <g>
                      <rect x={mid[0] - a.label.length * 3.2 - 6} y={mid[1] - 9}
                            width={a.label.length * 6.4 + 12} height={16}
                            fill={TV.panel} stroke={color} strokeOpacity="0.35" strokeWidth="1" rx="3"/>
                      <text x={mid[0]} y={mid[1] + 2} fontSize="10" fontWeight="600"
                            fill={color} textAnchor="middle"
                            style={{fontFamily: TV.font}}>{a.label}</text>
                    </g>
                  )}
                </g>
              );
            })}

            {/* screen boxes */}
            {screens.map(s => (
              <g key={s.id}>
                <rect x={s.x} y={s.y} width={s.w} height={s.h} rx={8}
                      fill={TV.panel2}
                      stroke={laneColor(s.lane)} strokeWidth="1.5"
                      strokeDasharray={s.dashed ? '4 3' : null}/>
                {/* left accent strip */}
                <rect x={s.x} y={s.y} width={3} height={s.h}
                      fill={laneColor(s.lane)} rx={1}/>
                <text x={s.x + 14} y={s.y + 24} fontSize="14" fontWeight="600" fill={TV.text}
                      style={{fontFamily: TV.font}}>{s.label}</text>
                <text x={s.x + 14} y={s.y + 42} fontSize="11" fill={TV.text3}
                      style={{fontFamily: TV.font}}>{s.hint}</text>
                {s.h > 60 && (
                  <text x={s.x + 14} y={s.y + 60} fontSize="10" fill={TV.text4}
                        style={{fontFamily: TV.font, letterSpacing: '.06em', textTransform: 'uppercase'}}>
                    {s.lane}
                  </text>
                )}
              </g>
            ))}
          </svg>
        </div>

        {/* notes */}
        <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginTop: 14}}>
          <div className="tv-card" style={{padding: 14}}>
            <div className="tv-uppercase" style={{color: TV.accent, marginBottom: 4}}>Daily entry</div>
            <div style={{fontSize: 12, color: TV.text2, lineHeight: 1.55}}>
              Dashboard is the home. 06:00 cron lands a quiz; scanner pulse runs continuously while watchlist active.
            </div>
          </div>
          <div className="tv-card" style={{padding: 14}}>
            <div className="tv-uppercase" style={{color: TV.adapt, marginBottom: 4}}>Data flows ←→</div>
            <div style={{fontSize: 12, color: TV.text2, lineHeight: 1.55}}>
              Purple dashed arrows are auto-population: quiz results → journal, validator → journal, journal → reports. No UI gesture needed.
            </div>
          </div>
          <div className="tv-card" style={{padding: 14}}>
            <div className="tv-uppercase" style={{color: TV.text3, marginBottom: 4}}>Cross-references</div>
            <div style={{fontSize: 12, color: TV.text2, lineHeight: 1.55}}>
              Gray arrows are "jump to" links — clickable concept chips, "re-open in validator" from a journal entry, etc. Not required for the primary flow.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

const Legend = () => (
  <div className="tv-card" style={{padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 16}}>
    <span style={{fontSize: 10, fontWeight: 700, color: TV.text3, letterSpacing: '.08em', textTransform: 'uppercase'}}>Legend</span>
    <LegendItem color={TV.accent}    label="primary flow"/>
    <LegendItem color={TV.adapt}     label="data populates" dashed/>
    <LegendItem color={TV.text3}     label="cross-reference" dashed/>
    <div style={{width: 1, height: 18, background: TV.line, margin: '0 4px'}}/>
    <LegendDot color={TV.accent}  label="home"/>
    <LegendDot color={TV.ok}      label="learn"/>
    <LegendDot color={TV.adapt}   label="trade"/>
    <LegendDot color={TV.text3}   label="admin"/>
  </div>
);

const LegendItem = ({color, label, dashed}) => (
  <div style={{display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: TV.text2}}>
    <svg width="28" height="6"><line x1="0" y1="3" x2="28" y2="3" stroke={color} strokeWidth="2"
        strokeDasharray={dashed ? '4 3' : null}/></svg>
    {label}
  </div>
);

const LegendDot = ({color, label}) => (
  <div style={{display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: TV.text2}}>
    <span style={{width: 8, height: 8, borderRadius: 2, background: color}}/>
    {label}
  </div>
);

Object.assign(window, {ScreenMapHF});
