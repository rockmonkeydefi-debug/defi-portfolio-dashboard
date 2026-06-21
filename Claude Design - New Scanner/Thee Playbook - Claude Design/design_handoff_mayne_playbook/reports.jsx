// reports.jsx — Reports / analytics screen (dark hi-fi)
// Headline KPIs, equity curve, calendar heatmap, and a 3×2 grid of breakdowns
// where each tile picks its own dimension. Plus skipped-but-watched, lesson-tag
// clustering, and quiz×trade correlation.

const ReportsHF = () => {
  // ----- mocked aggregates for 90D window -----
  const range = '90D';
  const totalTrades = 64;
  const wins = 38, losses = 22, breakeven = 4;
  const winRate = Math.round((wins / (wins + losses)) * 100);
  const netR = '+18.6R';
  const expectancy = '+0.29R';
  const profitFactor = '1.82';
  const maxDD = '-4.2R';
  const longestWin = 7;
  const longestLoss = 3;

  // mock equity curve — 64 trade increments, ending around +18.6R
  const equityPoints = (() => {
    const seed = [0, 1.8, 0.8, 2.4, 1.4, 3.2, 2.2, 4.0, 3.6, 5.4, 4.2, 5.8, 4.8, 6.2, 5.4,
                  6.8, 8.0, 7.2, 8.4, 9.6, 8.8, 10.0, 11.2, 10.4, 9.4, 11.0, 12.4, 11.6, 12.8,
                  14.2, 13.0, 14.4, 13.6, 12.2, 13.4, 14.8, 14.0, 15.4, 14.6, 13.2, 14.8, 16.2,
                  15.4, 16.6, 15.8, 17.0, 16.2, 17.6, 16.8, 18.2, 17.4, 16.0, 17.4, 18.8, 18.0,
                  19.2, 18.4, 19.6, 18.8, 17.4, 18.6];
    return seed;
  })();
  const maxEq = Math.max(...equityPoints);
  const minEq = Math.min(...equityPoints);

  // calendar heatmap — 13 weeks × 7 days = 91 cells, ~64 traded
  const heatmap = (() => {
    const cells = [];
    let i = 0;
    for (let w = 0; w < 13; w++) {
      for (let d = 0; d < 7; d++) {
        const isWeekend = d === 5 || d === 6;
        if (isWeekend) { cells.push({r: null, kind: 'weekend'}); continue; }
        // pattern: most weekdays traded, some skipped
        const skip = (w * 7 + d) % 9 === 0;
        if (skip) { cells.push({r: 0, kind: 'skip'}); continue; }
        // pseudo-random r value
        const seed = Math.sin((w + 1) * 12.9898 + (d + 1) * 78.233) * 43758.5453;
        const r = ((seed - Math.floor(seed)) - 0.42) * 2.4;
        cells.push({r: parseFloat(r.toFixed(2)), kind: 'traded'});
        i++;
      }
    }
    return cells;
  })();

  return (
    <div className="tv-frame" style={{display: 'flex', flexDirection: 'column'}}>
      <TVNav active="Reports"/>
    <TTSubNav active="Reports"/>

      <div style={{flex: 1, overflow: 'auto', minHeight: 0}}>
        {/* HEADER */}
        <div style={{padding: '20px 28px 14px', borderBottom: `1px solid ${TV.line}`,
            display: 'flex', alignItems: 'center', gap: 16}}>
          <div>
            <div className="tv-uppercase">Reports · performance</div>
            <div style={{fontSize: 24, fontWeight: 600, color: TV.text, marginTop: 4}}>
              Trade analytics
            </div>
          </div>
          <div style={{flex: 1}}/>
          <div style={{display: 'inline-flex', border: `1px solid ${TV.line}`, borderRadius: 5, padding: 2,
              background: TV.panel2}}>
            {['7D','30D','90D','6M','1Y','Lifetime'].map(r => (
              <div key={r} style={{
                padding: '5px 12px', borderRadius: 3, fontSize: 12, fontWeight: 500,
                cursor: 'pointer',
                color: r === range ? TV.text : TV.text3,
                background: r === range ? TV.panel3 : 'transparent',
                borderBottom: r === range ? `1.5px solid ${TV.accent}` : '1.5px solid transparent',
              }}>{r}</div>
            ))}
            <div style={{padding: '5px 10px', fontSize: 12, color: TV.text4, borderLeft: `1px solid ${TV.line}`, marginLeft: 2, cursor: 'pointer'}}>custom</div>
          </div>
          <button className="tv-btn ghost" style={{padding: '5px 10px', fontSize: 12}}>↗ export</button>
        </div>

        {/* KPI STRIP */}
        <div style={{padding: '18px 28px', display: 'grid',
            gridTemplateColumns: 'repeat(8, 1fr)', gap: 12}}>
          <KPI label="Win rate" value={`${winRate}%`} sub={`${wins} W · ${losses} L · ${breakeven} BE`} sentiment="ok"/>
          <KPI label="Expectancy" value={expectancy} sub="avg R / trade" sentiment="ok"/>
          <KPI label="Profit factor" value={profitFactor} sub="gross win ÷ loss" sentiment="ok"/>
          <KPI label="Net R" value={netR} sub={`${totalTrades} trades`} sentiment="ok"/>
          <KPI label="Max drawdown" value={maxDD} sub="May 4 → May 8" sentiment="warn"/>
          <KPI label="Avg hold" value="2h 14m" sub="winners 1h 48m · losers 2h 52m"/>
          <KPI label="Longest streak" value={`${longestWin} W`} sub={`worst: ${longestLoss} L`} sentiment="ok"/>
          <KPI label="Quiz · 30d avg" value="74%" sub="47 of 64 questions correct" sentiment="ok"/>
        </div>

        {/* EQUITY + HEATMAP */}
        <div style={{padding: '4px 28px 16px', display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 14}}>
          <EquityCurve points={equityPoints} maxEq={maxEq} minEq={minEq}/>
          <CalendarHeatmap cells={heatmap}/>
        </div>

        {/* BREAKDOWN GRID — 3×2 */}
        <div style={{padding: '4px 28px 16px'}}>
          <div style={{display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 12}}>
            <div className="tv-uppercase">Breakdowns</div>
            <div style={{fontSize: 12, color: TV.text3}}>each panel: pick a dimension · win % bar, net R, sample size</div>
            <div style={{flex: 1, height: 1, background: TV.line}}/>
            <button className="tv-btn ghost" style={{padding: '4px 10px', fontSize: 12}}>+ add breakdown</button>
          </div>

          <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14}}>
            <BreakdownCard
              title="By readiness verdict"
              dimension="Readiness"
              note="should be the cleanest signal — does the validator earn its keep?"
              rows={[
                {label: 'READY',       win: 73, n: 38, netR: '+19.4R'},
                {label: 'CONDITIONAL', win: 38, n: 18, netR: '-1.2R',  highlight: 'warn'},
                {label: 'NOT READY (taken)', win: 12, n: 8,  netR: '-3.6R', highlight: 'fail'},
              ]}
              footer="32 trades skipped on NOT READY — 6 of those would have been wins (regret: +2.4R)."
            />

            <BreakdownCard
              title="By concept"
              dimension="Concept"
              rows={[
                {label: 'Order Block',     win: 78, n: 28, netR: '+12.4R'},
                {label: 'FVG',             win: 52, n: 22, netR: '+2.8R'},
                {label: 'Liquidity Sweep', win: 64, n: 19, netR: '+5.4R'},
                {label: 'BOS / CHoCH',     win: 47, n: 11, netR: '-0.6R', highlight: 'warn'},
                {label: 'Killzones (alone)', win: 33, n: 6, netR: '-1.4R', highlight: 'fail'},
              ]}
              footer="OB-based trades have ~2× the expectancy of structure-only entries."
            />

            <BreakdownCard
              title="By session"
              dimension="Session"
              rows={[
                {label: 'London open',  win: 68, n: 22, netR: '+9.8R'},
                {label: 'NY AM',        win: 64, n: 24, netR: '+8.4R'},
                {label: 'London close', win: 50, n: 8,  netR: '+0.6R'},
                {label: 'NY PM',        win: 38, n: 8,  netR: '-1.2R', highlight: 'warn'},
                {label: 'Asia',         win: 0,  n: 2,  netR: '-1.0R', highlight: 'fail'},
              ]}
              footer="Asia trades are noise — consider not validating outside killzones."
            />

            <BreakdownCard
              title="By direction"
              dimension="Direction"
              rows={[
                {label: 'Long',  win: 64, n: 42, netR: '+14.8R'},
                {label: 'Short', win: 45, n: 22, netR: '+3.8R',  highlight: 'warn'},
              ]}
              footer="Slight long bias. Worth re-checking short bias-checks in the validator."
            />

            <BreakdownCard
              title="By R:R bucket"
              dimension="R:R"
              rows={[
                {label: '1:1.5–2',  win: 72, n: 18, netR: '+6.4R'},
                {label: '1:2–3',    win: 56, n: 28, netR: '+7.8R'},
                {label: '1:3+',     win: 38, n: 14, netR: '+5.0R'},
                {label: '< 1:1.5',  win: 75, n: 4,  netR: '+0.8R'},
              ]}
              footer="Hit rate on 1:3+ feels low — but expectancy still wins. Don't shrink targets."
            />

            <BreakdownCard
              title="By day of week"
              dimension="Day of week"
              note="day the trade was opened (NY time)"
              rows={[
                {label: 'Mon', win: 50, n: 12, netR: '+1.8R'},
                {label: 'Tue', win: 67, n: 15, netR: '+5.4R'},
                {label: 'Wed', win: 64, n: 14, netR: '+5.8R'},
                {label: 'Thu', win: 58, n: 12, netR: '+3.6R'},
                {label: 'Fri', win: 45, n: 11, netR: '+2.0R', highlight: 'warn'},
              ]}
              footer="Friday afternoons drag the week. Stop trading after 14:00 NY?"
            />

            <BreakdownCard
              title="By time of day · open"
              dimension="4-hour block"
              note="entry time (NY time) · 4-hour blocks"
              rows={[
                {label: '00:00 – 04:00', win: 0,  n: 2,  netR: '-1.0R', highlight: 'fail'},
                {label: '04:00 – 08:00', win: 68, n: 22, netR: '+9.8R'},
                {label: '08:00 – 12:00', win: 64, n: 24, netR: '+8.4R'},
                {label: '12:00 – 16:00', win: 46, n: 11, netR: '+0.4R', highlight: 'warn'},
                {label: '16:00 – 20:00', win: 40, n: 5,  netR: '+1.0R'},
                {label: '20:00 – 24:00', win: 0,  n: 0,  netR: '—'},
              ]}
              footer="04:00–12:00 NY (London + NY AM) carries the book. Afternoon entries break even."
            />

            <BreakdownCard
              title="By HTF leg"
              dimension="HTF"
              note="higher-timeframe where the point of interest was identified"
              rows={[
                {label: 'D · point of interest',  win: 64, n: 28, netR: '+11.4R'},
                {label: '4H · point of interest', win: 62, n: 30, netR: '+9.2R'},
                {label: 'W · point of interest',  win: 50, n: 4,  netR: '+0.6R'},
                {label: '1H · point of interest', win: 25, n: 2,  netR: '-2.6R', highlight: 'warn'},
              ]}
              footer="HTF on 1H is the wrong tool — fewer than 5 setups and net negative. Cap HTF at 4H minimum."
            />

            <BreakdownCard
              title="By LTF leg"
              dimension="LTF"
              note="lower-timeframe where the entry trigger formed"
              rows={[
                {label: '1H · entry trigger',  win: 62, n: 28, netR: '+10.8R'},
                {label: '15m · entry trigger', win: 64, n: 26, netR: '+9.4R'},
                {label: '5m · entry trigger',  win: 50, n: 8,  netR: '+1.2R'},
                {label: '4H · entry trigger',  win: 50, n: 2,  netR: '-2.8R', highlight: 'warn'},
              ]}
              footer="1H and 15m LTF triggers are the bread & butter. 5m is acceptable but lower hit-rate."
            />

            <BreakdownCard
              title="By ticker"
              dimension="Asset"
              rows={[
                {label: 'BTC',    win: 68, n: 19, netR: '+8.4R'},
                {label: 'ES',     win: 64, n: 14, netR: '+5.2R'},
                {label: 'NQ',     win: 58, n: 12, netR: '+3.6R'},
                {label: 'TSLA',   win: 55, n: 11, netR: '+2.4R'},
                {label: 'AAPL',   win: 33, n: 6,  netR: '-1.4R', highlight: 'warn'},
                {label: 'EURUSD', win: 0,  n: 2,  netR: '-0.8R', highlight: 'fail'},
              ]}
              footer="FX continues to underperform indices/crypto. Drop or re-train?"
            />

            <BreakdownCard
              title="By hold time"
              dimension="Hold time"
              rows={[
                {label: '< 30 min', win: 71, n: 14, netR: '+4.8R'},
                {label: '30m – 2h', win: 64, n: 28, netR: '+9.2R'},
                {label: '2h – 6h',  win: 52, n: 16, netR: '+4.2R'},
                {label: '> 6h',     win: 33, n: 6,  netR: '+0.4R', highlight: 'warn'},
              ]}
              footer="Quick scalps and 30m-2h holds carry me. Anything past 6h is mostly hope."
            />
          </div>
        </div>

        {/* SECONDARY ROW: skipped-but-watched · behavioral · quiz×trade · lesson tags */}
        <div style={{padding: '4px 28px 16px', display: 'grid',
            gridTemplateColumns: '1fr 1fr', gap: 14}}>

          {/* skipped-but-watched */}
          <div className="tv-card" style={{padding: 16}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12}}>
              <div className="tv-uppercase">Skipped-but-watched</div>
              <div style={{fontSize: 12, color: TV.text3}}>validator's "stand aside" calls · 90D</div>
              <div style={{flex: 1}}/>
              <span className="tv-chip">32 skips</span>
            </div>
            <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12}}>
              <SkipBlock
                title="System worked"
                detail="26 skips that would have lost"
                sub="net regret avoided"
                value="+7.8R"
                color={TV.ok}
                pct={81}
              />
              <SkipBlock
                title="System cost me"
                detail="6 skips that would have won"
                sub="net regret"
                value="-2.4R"
                color={TV.warn}
                pct={19}
              />
            </div>
            <div style={{fontSize: 12, color: TV.text2, marginTop: 12, lineHeight: 1.5,
                padding: '10px 12px', borderRadius: 6, background: TV.panel2}}>
              Net validator value over the window: <span style={{color: TV.ok, fontWeight: 600}}>+5.4R</span> from
              correctly skipped losers vs missed winners. Keep trusting CONDITIONAL=skip.
            </div>
          </div>

          {/* behavioral patterns */}
          <div className="tv-card" style={{padding: 16}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12}}>
              <div className="tv-uppercase">Behavioral patterns</div>
              <div style={{fontSize: 12, color: TV.text3}}>discipline check · 90D</div>
            </div>
            <div style={{display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: '10px 14px', fontSize: 13}}>
              <span style={{color: TV.text3}}>After 2+ trades same day</span>
              <BehaviorBar pct={36} color={TV.warn}/>
              <span style={{color: TV.warn, fontWeight: 600, textAlign: 'right'}}>36% · -1.6R</span>

              <span style={{color: TV.text3}}>Trade after a loss</span>
              <BehaviorBar pct={42} color={TV.warn}/>
              <span style={{color: TV.warn, fontWeight: 600, textAlign: 'right'}}>42% · -0.8R</span>

              <span style={{color: TV.text3}}>Trade after a win</span>
              <BehaviorBar pct={68} color={TV.ok}/>
              <span style={{color: TV.ok, fontWeight: 600, textAlign: 'right'}}>68% · +3.4R</span>

              <span style={{color: TV.text3}}>After dry spell ({'>'}3d)</span>
              <BehaviorBar pct={71} color={TV.ok}/>
              <span style={{color: TV.ok, fontWeight: 600, textAlign: 'right'}}>71% · +4.2R</span>

              <span style={{color: TV.text3}}>High-vol days (top 20%)</span>
              <BehaviorBar pct={64} color={TV.ok}/>
              <span style={{color: TV.ok, fontWeight: 600, textAlign: 'right'}}>64% · +6.8R</span>

              <span style={{color: TV.text3}}>News day (FOMC / CPI / NFP)</span>
              <BehaviorBar pct={29} color={TV.fail}/>
              <span style={{color: TV.fail, fontWeight: 600, textAlign: 'right'}}>29% · -3.2R</span>
            </div>
            <div style={{fontSize: 12, color: TV.text2, marginTop: 12, lineHeight: 1.5,
                padding: '10px 12px', borderRadius: 6, background: TV.panel2}}>
              <span style={{color: TV.warn, fontWeight: 600}}>Revenge-trade pattern</span> after losses is real.
              <span style={{color: TV.fail, fontWeight: 600}}> News-day trades</span> are a clear money-loser.
            </div>
          </div>
        </div>

        {/* THIRD ROW: lesson tags + quiz × trade correlation */}
        <div style={{padding: '4px 28px 22px', display: 'grid',
            gridTemplateColumns: '1fr 1fr', gap: 14}}>

          {/* lesson tag clustering */}
          <div className="tv-card" style={{padding: 16}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12}}>
              <div className="tv-uppercase">Lesson themes</div>
              <div style={{fontSize: 12, color: TV.text3}}>auto-clustered from your notes &amp; lessons · 90D</div>
              <div style={{flex: 1}}/>
              <button className="tv-btn ghost" style={{padding: '4px 8px', fontSize: 11}}>re-cluster</button>
            </div>
            {[
              {tag: 'overrode validator', count: 7, netR: -4.2, color: TV.fail},
              {tag: 'tight LTF stop', count: 12, netR: +5.4, color: TV.ok},
              {tag: 'no LTF confirm', count: 5, netR: -2.6, color: TV.fail},
              {tag: 'patient OB tap', count: 14, netR: +8.6, color: TV.ok},
              {tag: 'partial @ tight RR', count: 9, netR: +3.2, color: TV.ok},
              {tag: 'chased breakout', count: 4, netR: -1.8, color: TV.fail},
              {tag: 'killzone alignment', count: 18, netR: +9.4, color: TV.ok},
            ].map(t => (
              <div key={t.tag} style={{display: 'grid', gridTemplateColumns: '1fr 60px 80px',
                  alignItems: 'center', gap: 12, padding: '6px 0', borderBottom: `1px solid ${TV.lineSoft}`}}>
                <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
                  <span style={{width: 6, height: 6, borderRadius: '50%', background: t.color}}/>
                  <span style={{fontSize: 13, color: TV.text}}>{t.tag}</span>
                </div>
                <span className="tv-num" style={{fontSize: 12, color: TV.text3}}>{t.count}× tagged</span>
                <span className="tv-num" style={{fontSize: 13, fontWeight: 600,
                    color: t.color, textAlign: 'right'}}>
                  {t.netR > 0 ? '+' : ''}{t.netR.toFixed(1)}R
                </span>
              </div>
            ))}
            <div style={{fontSize: 12, color: TV.text2, marginTop: 10, lineHeight: 1.5}}>
              <span style={{color: TV.fail, fontWeight: 600}}>"Overrode validator"</span> is the costliest theme.
              Most common positive: <span style={{color: TV.ok, fontWeight: 600}}>killzone alignment</span> and
              <span style={{color: TV.ok, fontWeight: 600}}> patient OB taps</span>.
            </div>
          </div>

          {/* quiz × trade correlation */}
          <div className="tv-card" style={{padding: 16}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12}}>
              <div className="tv-uppercase">Quiz × trade</div>
              <div style={{fontSize: 12, color: TV.text3}}>does morning mastery predict afternoon execution?</div>
            </div>
            <ScatterPlot/>
            <div style={{fontSize: 12, color: TV.text2, marginTop: 10, lineHeight: 1.5,
                padding: '10px 12px', borderRadius: 6, background: TV.panel2}}>
              Mild positive correlation (r = +0.31). Days with <span className="tv-num" style={{color: TV.ok, fontWeight: 600}}>7+/8</span> quiz scores
              average <span className="tv-num" style={{color: TV.ok, fontWeight: 600}}>+0.6R</span> trading vs
              <span className="tv-num" style={{color: TV.warn, fontWeight: 600}}> -0.1R</span> on sub-6/8 days.
            </div>
          </div>
        </div>

        {/* CONCEPT MASTERY PROGRESSION */}
        <div style={{padding: '4px 28px 28px'}}>
          <div className="tv-card" style={{padding: 16}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12}}>
              <div className="tv-uppercase">Concept mastery · progression</div>
              <div style={{fontSize: 12, color: TV.text3}}>quiz hit-rate per concept, month over month</div>
              <div style={{flex: 1}}/>
              <button className="tv-btn ghost" style={{padding: '4px 8px', fontSize: 11}}>view as table</button>
            </div>
            <ProgressionChart/>
          </div>
        </div>
      </div>
    </div>
  );
};

// ---------- KPI card ----------
const KPI = ({label, value, sub, sentiment}) => {
  const color = sentiment === 'ok' ? TV.ok : sentiment === 'warn' ? TV.warn : sentiment === 'fail' ? TV.fail : TV.text;
  return (
    <div className="tv-card" style={{padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 2}}>
      <div className="tv-uppercase">{label}</div>
      <div className="tv-num" style={{fontSize: 22, fontWeight: 700, color, letterSpacing: '-.4px', marginTop: 2}}>{value}</div>
      <div style={{fontSize: 11, color: TV.text3, lineHeight: 1.35}}>{sub}</div>
    </div>
  );
};

// ---------- equity curve ----------
const EquityCurve = ({points, maxEq, minEq}) => {
  const W = 600, H = 220, pad = 24;
  const yRange = (maxEq - minEq) || 1;
  const pts = points.map((y, i) => {
    const x = pad + (i / (points.length - 1)) * (W - pad * 2);
    const yy = H - pad - ((y - minEq) / yRange) * (H - pad * 2);
    return [x, yy];
  });
  const pathD = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p[0]} ${p[1]}`).join(' ');
  const lastPt = pts[pts.length - 1];

  return (
    <div className="tv-card" style={{padding: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10}}>
        <div className="tv-uppercase">Equity curve</div>
        <div style={{fontSize: 12, color: TV.text3}}>cumulative R · 90D</div>
        <div style={{flex: 1}}/>
        <span className="tv-num" style={{fontSize: 18, fontWeight: 700, color: TV.ok}}>+18.6R</span>
        <span style={{fontSize: 12, color: TV.text3}}>· peak +19.6R · trough -0.4R</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none">
        {/* zero line */}
        <line x1={pad} x2={W - pad}
              y1={H - pad - ((0 - minEq) / yRange) * (H - pad * 2)}
              y2={H - pad - ((0 - minEq) / yRange) * (H - pad * 2)}
              stroke={TV.line} strokeWidth="1" strokeDasharray="3 4"/>
        {/* gridlines */}
        {[5, 10, 15, 20].map(g => (
          <g key={g}>
            <line x1={pad} x2={W - pad}
                  y1={H - pad - ((g - minEq) / yRange) * (H - pad * 2)}
                  y2={H - pad - ((g - minEq) / yRange) * (H - pad * 2)}
                  stroke={TV.lineSoft} strokeWidth="1"/>
            <text x={4} y={H - pad - ((g - minEq) / yRange) * (H - pad * 2) + 4}
                  fontSize="10" fill={TV.text4}>{g}R</text>
          </g>
        ))}
        {/* fill */}
        <path d={`${pathD} L ${lastPt[0]} ${H - pad} L ${pad} ${H - pad} Z`}
              fill={TV.accent} fillOpacity="0.08"/>
        {/* line */}
        <path d={pathD} fill="none" stroke={TV.accent} strokeWidth="1.8"
              strokeLinecap="round" strokeLinejoin="round"/>
        {/* end dot */}
        <circle cx={lastPt[0]} cy={lastPt[1]} r="4" fill={TV.accent}/>
        <circle cx={lastPt[0]} cy={lastPt[1]} r="8" fill={TV.accent} fillOpacity="0.25"/>
      </svg>
    </div>
  );
};

// ---------- calendar heatmap ----------
const CalendarHeatmap = ({cells}) => {
  const cellColor = (c) => {
    if (c.kind === 'weekend') return 'transparent';
    if (c.kind === 'skip')    return TV.panel2;
    const r = c.r;
    if (r === 0) return TV.panel3;
    if (r > 0) {
      const a = Math.min(1, Math.abs(r) / 2);
      return `rgba(63,178,127,${0.18 + a * 0.7})`;
    }
    const a = Math.min(1, Math.abs(r) / 2);
    return `rgba(217,83,79,${0.18 + a * 0.7})`;
  };

  // reorganize into 7 rows (M-Su) × 13 cols (weeks)
  const grid = [];
  for (let d = 0; d < 7; d++) {
    const row = [];
    for (let w = 0; w < 13; w++) row.push(cells[w * 7 + d]);
    grid.push(row);
  }

  return (
    <div className="tv-card" style={{padding: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10}}>
        <div className="tv-uppercase">Daily P&amp;L heatmap</div>
        <div style={{flex: 1}}/>
        <div style={{display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: TV.text4}}>
          <span>-2R</span>
          <span style={{width: 12, height: 8, background: 'rgba(217,83,79,.7)', borderRadius: 1}}/>
          <span style={{width: 12, height: 8, background: 'rgba(217,83,79,.35)', borderRadius: 1}}/>
          <span style={{width: 12, height: 8, background: TV.panel3, borderRadius: 1}}/>
          <span style={{width: 12, height: 8, background: 'rgba(63,178,127,.35)', borderRadius: 1}}/>
          <span style={{width: 12, height: 8, background: 'rgba(63,178,127,.7)', borderRadius: 1}}/>
          <span>+2R</span>
        </div>
      </div>
      <div style={{display: 'flex', flexDirection: 'column', gap: 3}}>
        {grid.map((row, di) => (
          <div key={di} style={{display: 'flex', gap: 3, alignItems: 'center'}}>
            <div style={{width: 26, fontSize: 10, color: TV.text4, fontWeight: 600, letterSpacing: '.04em'}}>
              {['MON','TUE','WED','THU','FRI','SAT','SUN'][di]}
            </div>
            {row.map((c, wi) => (
              <div key={wi} title={c.kind === 'weekend' ? '' : c.kind === 'skip' ? 'no trade' : `${c.r > 0 ? '+' : ''}${c.r}R`}
                  style={{
                    flex: 1, aspectRatio: '1 / 1', maxHeight: 18,
                    background: cellColor(c),
                    border: c.kind !== 'weekend' ? `1px solid ${TV.lineSoft}` : 'none',
                    borderRadius: 2,
                  }}/>
            ))}
          </div>
        ))}
      </div>
      <div style={{display: 'flex', justifyContent: 'space-between', marginTop: 8, paddingLeft: 28,
          fontSize: 10, color: TV.text4}}>
        <span>13 weeks ago</span>
        <span>today</span>
      </div>
    </div>
  );
};

// ---------- breakdown card ----------
const BreakdownCard = ({title, dimension, note, rows, footer}) => (
  <div className="tv-card" style={{padding: 14}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4}}>
      <div style={{fontSize: 14, fontWeight: 600, color: TV.text}}>{title}</div>
      <div style={{flex: 1}}/>
      <div style={{padding: '3px 9px', borderRadius: 4, fontSize: 11, fontWeight: 500,
          color: TV.text2, background: TV.panel2, border: `1px solid ${TV.line}`,
          display: 'inline-flex', alignItems: 'center', gap: 4, cursor: 'pointer'}}>
        {dimension} <span style={{color: TV.text4}}>▾</span>
      </div>
    </div>
    {note && <div style={{fontSize: 11, color: TV.text4, marginBottom: 8, fontStyle: 'italic'}}>{note}</div>}
    <div style={{display: 'flex', flexDirection: 'column', gap: 4, marginTop: note ? 0 : 4}}>
      {rows.map((r, i) => {
        const win = r.win;
        const barColor = r.highlight === 'fail' ? TV.fail : r.highlight === 'warn' ? TV.warn :
            win >= 60 ? TV.ok : win >= 45 ? TV.text2 : TV.warn;
        const netRColor = r.netR.startsWith('+') ? TV.ok : r.netR.startsWith('-') ? TV.fail : TV.text2;
        return (
          <div key={i} style={{display: 'grid', gridTemplateColumns: '1fr 60px 30px 60px',
              alignItems: 'center', gap: 8, padding: '4px 0',
              borderBottom: i < rows.length - 1 ? `1px solid ${TV.lineSoft}` : 'none'}}>
            <span style={{fontSize: 12, color: TV.text}}>{r.label}</span>
            <div style={{display: 'flex', alignItems: 'center', gap: 6}}>
              <div style={{flex: 1, height: 4, background: TV.panel3, borderRadius: 2, overflow: 'hidden'}}>
                <div style={{height: '100%', width: `${win}%`, background: barColor}}/>
              </div>
            </div>
            <span className="tv-num" style={{fontSize: 11, color: TV.text3, textAlign: 'right'}}>{win}%</span>
            <span className="tv-num" style={{fontSize: 12, color: netRColor, fontWeight: 600, textAlign: 'right'}}>
              {r.netR}
              <span style={{color: TV.text4, fontWeight: 400, marginLeft: 4, fontSize: 10}}>n={r.n}</span>
            </span>
          </div>
        );
      })}
    </div>
    {footer && (
      <div style={{fontSize: 11, color: TV.text2, marginTop: 10, paddingTop: 8,
          borderTop: `1px solid ${TV.lineSoft}`, lineHeight: 1.5}}>
        ↳ {footer}
      </div>
    )}
  </div>
);

// ---------- helper: skipped-but-watched block ----------
const SkipBlock = ({title, detail, sub, value, color, pct}) => (
  <div style={{padding: '14px 16px', borderRadius: 6,
      border: `1px solid ${color}`, background: color === TV.ok ? TV.okSoft : color === TV.warn ? TV.warnSoft : TV.failSoft}}>
    <div style={{fontSize: 11, fontWeight: 600, color, letterSpacing: '.06em', textTransform: 'uppercase'}}>{title}</div>
    <div className="tv-num" style={{fontSize: 24, fontWeight: 700, color, marginTop: 4, letterSpacing: '-.4px'}}>{value}</div>
    <div style={{fontSize: 12, color: TV.text, marginTop: 4}}>{detail}</div>
    <div style={{fontSize: 11, color: TV.text3, marginTop: 2}}>{sub} · {pct}% of skips</div>
  </div>
);

// ---------- helper: behavior bar ----------
const BehaviorBar = ({pct, color}) => (
  <div style={{height: 4, background: TV.panel3, borderRadius: 2, overflow: 'hidden'}}>
    <div style={{height: '100%', width: `${pct}%`, background: color}}/>
  </div>
);

// ---------- scatter plot for quiz × trade ----------
const ScatterPlot = () => {
  const W = 360, H = 180, pad = 30;
  const points = [
    [3,-1.4],[4,-0.6],[4,-1.2],[5,0.2],[5,0.6],[5,-0.4],[5,-0.8],[5,0.8],
    [6,0.4],[6,1.2],[6,0.6],[6,-0.4],[6,0.8],[6,1.0],[6,-0.6],[6,1.4],
    [7,1.2],[7,1.8],[7,0.8],[7,-0.4],[7,1.4],[7,2.2],[7,1.6],[7,0.6],
    [8,2.4],[8,1.8],[8,1.2],[8,2.0],[8,0.8],[8,1.6],
  ];
  const xS = x => pad + (x / 8) * (W - pad * 2);
  const yS = y => H - pad - ((y + 2) / 4) * (H - pad * 2);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none">
      {/* axes */}
      <line x1={pad} x2={W - pad} y1={yS(0)} y2={yS(0)} stroke={TV.line} strokeDasharray="2 3"/>
      <line x1={pad} x2={pad} y1={pad} y2={H - pad} stroke={TV.line}/>
      {[0,2,4,6,8].map(v => (
        <g key={v}>
          <text x={xS(v)} y={H - 8} fontSize="10" fill={TV.text4} textAnchor="middle">{v}</text>
        </g>
      ))}
      {[-2,-1,0,1,2].map(v => (
        <text key={v} x={4} y={yS(v) + 3} fontSize="10" fill={TV.text4}>{v > 0 ? '+' : ''}{v}R</text>
      ))}
      {/* trend line — least-squares-ish */}
      <line x1={xS(3)} y1={yS(-0.4)} x2={xS(8)} y2={yS(1.5)}
            stroke={TV.adapt} strokeWidth="1.5" strokeDasharray="4 3"/>
      {/* dots */}
      {points.map(([x,y],i) => (
        <circle key={i} cx={xS(x)} cy={yS(y)} r="3.5"
                fill={y > 0 ? TV.ok : TV.fail}
                fillOpacity="0.7" stroke={y > 0 ? TV.ok : TV.fail} strokeWidth="0.5"/>
      ))}
      <text x={W - pad - 4} y={pad + 4} fontSize="10" fill={TV.text4} textAnchor="end">net R</text>
      <text x={W - pad - 4} y={H - 8} fontSize="10" fill={TV.text4} textAnchor="end">quiz score (of 8)</text>
    </svg>
  );
};

// ---------- progression chart (line per concept) ----------
const ProgressionChart = () => {
  const W = 800, H = 200, pad = 32;
  const months = ['Feb', 'Mar', 'Apr', 'May'];
  const concepts = [
    {name: 'Order Block',     color: TV.accent, values: [42, 52, 64, 78]},
    {name: 'FVG',             color: '#5da6e6', values: [38, 41, 48, 52]},
    {name: 'Liquidity Sweep', color: TV.ok,     values: [55, 58, 61, 64]},
    {name: 'BOS / CHoCH',     color: '#e89a4d', values: [48, 52, 64, 70]},
    {name: 'Killzones',       color: TV.adapt,  values: [62, 71, 78, 82]},
  ];
  const xS = i => pad + (i / (months.length - 1)) * (W - pad * 2);
  const yS = v => H - pad - (v / 100) * (H - pad * 2);

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none">
        {[25, 50, 75, 100].map(g => (
          <g key={g}>
            <line x1={pad} x2={W - pad} y1={yS(g)} y2={yS(g)} stroke={TV.lineSoft}/>
            <text x={4} y={yS(g) + 3} fontSize="10" fill={TV.text4}>{g}%</text>
          </g>
        ))}
        {months.map((m,i) => (
          <text key={m} x={xS(i)} y={H - 10} fontSize="10" fill={TV.text4} textAnchor="middle">{m}</text>
        ))}
        {concepts.map(c => {
          const pathD = c.values.map((v,i) => `${i === 0 ? 'M' : 'L'} ${xS(i)} ${yS(v)}`).join(' ');
          return (
            <g key={c.name}>
              <path d={pathD} fill="none" stroke={c.color} strokeWidth="1.8"
                    strokeLinecap="round" strokeLinejoin="round"/>
              {c.values.map((v,i) => (
                <circle key={i} cx={xS(i)} cy={yS(v)} r="3" fill={c.color}/>
              ))}
            </g>
          );
        })}
      </svg>
      <div style={{display: 'flex', gap: 18, flexWrap: 'wrap', marginTop: 6, paddingLeft: pad}}>
        {concepts.map(c => (
          <div key={c.name} style={{display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: TV.text2}}>
            <span style={{width: 10, height: 2, background: c.color, borderRadius: 1}}/>
            {c.name}
            <span style={{color: TV.text4}}>{c.values[c.values.length - 1]}%</span>
          </div>
        ))}
      </div>
    </div>
  );
};

Object.assign(window, {ReportsHF});
