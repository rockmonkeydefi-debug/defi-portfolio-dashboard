// concepts.jsx — Concept library (dark hi-fi)
// Browseable list of every concept the system tracks. Click any concept,
// see definition, mastery trend, source episodes, recent missed questions,
// trades that used it, and related concepts.

const CONCEPT_DATA = [
  {
    id: 'order-block',
    name: 'Order Block',
    family: 'entries',
    short: 'OB',
    mastery: 38,
    trend: -14,
    history: [60, 52, 45, 38],
    timesTested: 28,
    correct: 11,
    incorrect: 17,
    definition: 'The last opposing candle before an impulsive displacement away from a level. In a bullish move, the order block is the last down-close candle (or set of candles) before price ran up — interpreted as where institutional buy orders filled, and where price often returns to rebalance before continuation.',
    sources: [
      {ep: 14, title: '"Order Block basics"', at: '02:18'},
      {ep: 18, title: '"FVG deep dive"',       at: '15:42'},
      {ep: 22, title: '"Buy/Sell-side Liquidity"', at: '08:30'},
    ],
    related: ['Fair Value Gap', 'Liquidity Sweep', 'BOS / CHoCH'],
    missed: [
      {quiz: 46, date: '2026-05-22', q: '"Which candle marks the most recent bullish OB on this 1H chart of NQ?"',
        chose: 'Candle 11 — biggest red bar in the sequence',
        right: 'Candle 7 — last down-close before the impulse',
        why: 'Confused OB with "the largest bearish candle." Size is irrelevant — origin matters.'},
      {quiz: 44, date: '2026-05-20', q: '"In an HTF bullish OB on the 4H, where is the optimal LTF entry?"',
        chose: 'At the OB low (worst-case fill)',
        right: 'At the OB 50% / mean threshold',
        why: 'Defaulted to the bottom edge. Mayne consistently teaches the mean as the optimal fill.'},
      {quiz: 41, date: '2026-05-17', q: '"True or false: an OB is invalidated when price closes through its origin."',
        chose: 'False',
        right: 'True',
        why: 'Wick-through vs close-through — was thinking about wick tests.'},
    ],
    tradesN: 28,
    tradesW: 22,
    tradesL: 6,
    tradesNetR: '+12.4R',
    bestTrade: 'BTCUSD long · 2026-05-23 · +1.8R',
    worstTrade: 'AAPL long · 2026-05-20 · -1.0R',
  },
  {
    id: 'fvg',
    name: 'Fair Value Gap',
    family: 'imbalance',
    short: 'FVG',
    mastery: 44,
    trend: -8,
    history: [56, 52, 48, 44],
    timesTested: 24,
    correct: 11, incorrect: 13,
    definition: 'A 3-candle imbalance where the wick of the first and third candle do not overlap, leaving an inefficient price delivery. Price seeks to return and rebalance the gap (a "virgin" FVG has not been mitigated).',
    sources: [{ep: 18, title: '"FVG deep dive"', at: '03:42'}, {ep: 22, title: '"Buy/Sell-side Liquidity"', at: '11:15'}],
    related: ['Order Block', 'Mitigation', 'Trade Entries'],
    missed: [
      {quiz: 47, date: '2026-05-23', q: '"Has this 3-candle move created a valid bullish FVG?"',
        chose: 'No — the wicks overlap',
        right: 'Yes — the bodies overlap but wicks do not',
        why: 'Was looking at body overlap instead of wick overlap.'},
    ],
    tradesN: 22, tradesW: 12, tradesL: 8, tradesNetR: '+2.8R',
    bestTrade: 'ES long · 2026-05-16 · +2.2R',
    worstTrade: 'EURUSD short · 2026-05-09 · -1.0R',
  },
  {
    id: 'liquidity-sweep',
    name: 'Liquidity Sweep',
    family: 'liquidity',
    short: 'Sweep',
    mastery: 61,
    trend: +6,
    history: [52, 55, 58, 61],
    timesTested: 19,
    correct: 12, incorrect: 7,
    definition: 'A controlled run on a pool of resting orders (equal highs/lows, session high/low, prior day H/L) followed by rejection and reclaim. The presence and reclaim is the signal — the sweep itself is just liquidity acquisition.',
    sources: [{ep: 22, title: '"Buy/Sell-side Liquidity"', at: '00:48'}, {ep: 23, title: '"Killzones & Session Liquidity"', at: '04:12'}],
    related: ['Killzones', 'BOS / CHoCH', 'Trade Entries'],
    missed: [
      {quiz: 39, date: '2026-05-15', q: '"Was the move into equal lows on this 5m a valid sell-side sweep?"',
        chose: 'No — wick was too small',
        right: 'Yes — sweep magnitude does not matter, reclaim does',
        why: 'Looking for a "big" sweep. Magnitude is misleading; reclaim is what matters.'},
    ],
    tradesN: 19, tradesW: 12, tradesL: 7, tradesNetR: '+5.4R',
    bestTrade: 'NQ short · 2026-05-19 · +0.8R',
    worstTrade: 'GBPUSD long · 2026-05-02 · -1.2R',
  },
  {
    id: 'bos-choch',
    name: 'BOS / CHoCH',
    family: 'structure',
    short: 'Structure',
    mastery: 70,
    trend: +6,
    history: [58, 64, 64, 70],
    timesTested: 18,
    correct: 13, incorrect: 5,
    definition: 'Break of Structure (BOS): continuation of trend, price takes the most recent same-side swing. Change of Character (CHoCH): first opposite break — signals exhaustion of one side and a potential shift. Mayne treats CHoCH on the LTF as the highest-conviction entry trigger.',
    sources: [{ep: 20, title: '"BOS vs CHoCH revisited"', at: '00:00'}],
    related: ['Market Structure', 'Trade Entries', 'Liquidity Sweep'],
    missed: [
      {quiz: 38, date: '2026-05-14', q: '"After a buy-side sweep into premium, the first 5m bearish break is..."',
        chose: 'A BOS',
        right: 'A CHoCH',
        why: 'Bias was up but this is the FIRST break against trend — CHoCH, not BOS.'},
    ],
    tradesN: 14, tradesW: 9, tradesL: 5, tradesNetR: '+3.2R',
    bestTrade: 'BTC long · 2026-05-23 · +1.8R',
  },
  {
    id: 'killzones',
    name: 'Killzones',
    family: 'sessions',
    short: 'KZ',
    mastery: 82,
    trend: +4,
    history: [70, 76, 78, 82],
    timesTested: 14,
    correct: 11, incorrect: 3,
    definition: 'Specific windows inside each session where price is statistically most likely to deliver — i.e. sweep liquidity, shift structure, and offer high-probability entries. London open (02:00–05:00 NY), NY AM (07:00–10:00 NY), London close (10:00–12:00 NY).',
    sources: [{ep: 23, title: '"Killzones & Session Liquidity"', at: '00:42'}],
    related: ['Liquidity Sweep', 'Bias'],
    missed: [
      {quiz: 33, date: '2026-05-08', q: '"Best killzone for a USD-denominated long bias setup is..."',
        chose: 'NY PM',
        right: 'NY AM',
        why: 'PM has less volume and less delivery — AM aligns with the bigger move.'},
    ],
    tradesN: 18, tradesW: 13, tradesL: 5, tradesNetR: '+9.4R',
    bestTrade: 'TSLA long · 2026-05-13 · +2.4R',
  },
  {
    id: 'bias',
    name: 'Bias',
    family: 'structure',
    short: 'Bias',
    mastery: 76,
    trend: +8,
    history: [60, 65, 70, 76],
    timesTested: 20,
    correct: 15, incorrect: 5,
    definition: 'The current directional lean drawn from HTF market structure. Bullish bias requires the most recent decisive HTF break to be to the upside without a subsequent lower-high printed.',
    sources: [{ep: 20, title: '"BOS vs CHoCH revisited"', at: '06:30'}],
    related: ['Market Structure', 'Dealing Range'],
    missed: [],
    tradesN: 22, tradesW: 14, tradesL: 8, tradesNetR: '+4.6R',
  },
  {
    id: 'dealing-range',
    name: 'Dealing Range',
    family: 'structure',
    short: 'DR',
    mastery: 68,
    trend: +2,
    history: [62, 66, 66, 68],
    timesTested: 12,
    correct: 8, incorrect: 4,
    definition: 'The most relevant high-to-low range on the HTF. Split into premium (above 0.5) and discount (below 0.5). In a bullish bias, you want longs from discount; in a bearish bias, shorts from premium.',
    sources: [{ep: 17, title: '"Premium / Discount basics"', at: '01:24'}, {ep: 22, title: '"Buy/Sell-side Liquidity"', at: '05:48'}],
    related: ['Premium / Discount', 'Bias'],
    missed: [],
    tradesN: 18, tradesW: 11, tradesL: 7, tradesNetR: '+3.4R',
  },
  {
    id: 'premium-discount',
    name: 'Premium / Discount',
    family: 'structure',
    short: 'P/D',
    mastery: 64,
    trend: +4,
    history: [56, 60, 60, 64],
    timesTested: 11,
    correct: 7, incorrect: 4,
    definition: 'The two halves of the dealing range divided at 0.5 (equilibrium). Premium = above 0.5 = where shorts are taken in a bearish bias. Discount = below 0.5 = where longs are taken in a bullish bias.',
    sources: [{ep: 17, title: '"Premium / Discount basics"', at: '04:30'}],
    related: ['Dealing Range', 'Bias'],
    missed: [],
    tradesN: 15, tradesW: 9, tradesL: 6, tradesNetR: '+1.8R',
  },
  {
    id: 'mitigation',
    name: 'Mitigation',
    family: 'imbalance',
    short: 'Mit.',
    mastery: 52,
    trend: -2,
    history: [54, 56, 54, 52],
    timesTested: 9,
    correct: 5, incorrect: 4,
    definition: 'The act of price returning to an unfilled imbalance (FVG, order block, breaker) and rebalancing it before continuing. A "virgin" FVG has not been mitigated; a "tapped" or "filled" one has.',
    sources: [{ep: 18, title: '"FVG deep dive"', at: '12:18'}],
    related: ['Fair Value Gap', 'Order Block'],
    missed: [],
    tradesN: 8, tradesW: 4, tradesL: 4, tradesNetR: '-0.4R',
  },
  {
    id: 'trade-entries',
    name: 'Trade Entries',
    family: 'entries',
    short: 'Entry',
    mastery: 58,
    trend: +6,
    history: [48, 52, 54, 58],
    timesTested: 16,
    correct: 9, incorrect: 7,
    definition: 'The specific LTF trigger that opens the position. Mayne emphasizes 3 valid triggers: (1) bullish/bearish FVG return inside HTF array, (2) order block tap with LTF confirmation, (3) liquidity sweep + CHoCH on LTF.',
    sources: [{ep: 21, title: '"Optimal Trade Entry"', at: '00:00'}, {ep: 23, title: '"Killzones & Session Liquidity"', at: '14:18'}],
    related: ['Fair Value Gap', 'Order Block', 'Liquidity Sweep', 'BOS / CHoCH'],
    missed: [],
    tradesN: 64, tradesW: 38, tradesL: 22, tradesNetR: '+18.6R',
  },
  {
    id: 'invalidation',
    name: 'Invalidation',
    family: 'risk',
    short: 'Inv.',
    mastery: 78,
    trend: +2,
    history: [72, 74, 76, 78],
    timesTested: 8,
    correct: 6, incorrect: 2,
    definition: 'The structural level that, if violated on a close, says "the setup is wrong." Mayne uses this for both stop placement and emotional discipline — don\'t move the invalidation, don\'t pre-empt it.',
    sources: [{ep: 21, title: '"Optimal Trade Entry"', at: '10:30'}],
    related: ['Trade Entries', 'Market Structure'],
    missed: [],
    tradesN: 64, tradesW: 38, tradesL: 22, tradesNetR: '+18.6R',
  },
  {
    id: 'optimal-trade-entry',
    name: 'Optimal Trade Entry',
    family: 'entries',
    short: 'OTE',
    mastery: 55,
    trend: -4,
    history: [62, 60, 58, 55],
    timesTested: 12,
    correct: 6, incorrect: 6,
    definition: 'The narrow zone (~0.62 to 0.79 fib of a swing) that combines with FVG / OB / discount-premium logic to give the highest-RR LTF entry. Mayne stresses confluence, not the fib alone.',
    sources: [{ep: 21, title: '"Optimal Trade Entry"', at: '04:12'}],
    related: ['Trade Entries', 'Premium / Discount'],
    missed: [],
    tradesN: 9, tradesW: 5, tradesL: 4, tradesNetR: '+1.4R',
  },
];

// ============================================
const ConceptsHF = () => {
  const [selected, setSelected] = React.useState('order-block');
  const [filter, setFilter] = React.useState('all'); // all | weak | strong
  const [sort, setSort] = React.useState('weakness'); // weakness | a-z | tested

  let list = [...CONCEPT_DATA];
  if (filter === 'weak')   list = list.filter(c => c.mastery < 60);
  if (filter === 'strong') list = list.filter(c => c.mastery >= 70);

  list.sort((a, b) => {
    if (sort === 'weakness') return a.mastery - b.mastery;
    if (sort === 'a-z')      return a.name.localeCompare(b.name);
    return b.timesTested - a.timesTested;
  });

  const c = CONCEPT_DATA.find(x => x.id === selected);

  // counts for header
  const totals = {
    all: CONCEPT_DATA.length,
    weak: CONCEPT_DATA.filter(c => c.mastery < 60).length,
    forming: CONCEPT_DATA.filter(c => c.mastery >= 60 && c.mastery < 70).length,
    strong: CONCEPT_DATA.filter(c => c.mastery >= 70).length,
  };

  return (
    <div className="tv-frame" style={{display: 'flex', flexDirection: 'column'}}>
      <TVNav active="Concepts"/>
    <TTSubNav active="Concepts"/>

      <div style={{flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden'}}>
        {/* LEFT — list */}
        <div style={{width: 340, borderRight: `1px solid ${TV.line}`, display: 'flex', flexDirection: 'column',
            minHeight: 0, overflow: 'hidden', background: TV.panel}}>

          <div style={{padding: '16px 18px 12px', borderBottom: `1px solid ${TV.line}`}}>
            <div className="tv-uppercase">Concept library</div>
            <div style={{fontSize: 18, fontWeight: 600, color: TV.text, marginTop: 4}}>
              {totals.all} concepts
            </div>
            <div style={{fontSize: 12, color: TV.text3, marginTop: 4}}>
              <span style={{color: TV.fail, fontWeight: 600}}>{totals.weak} weak</span>
              <span style={{color: TV.text4, margin: '0 6px'}}>·</span>
              <span style={{color: TV.text, fontWeight: 600}}>{totals.forming} forming</span>
              <span style={{color: TV.text4, margin: '0 6px'}}>·</span>
              <span style={{color: TV.ok, fontWeight: 600}}>{totals.strong} strong</span>
            </div>
          </div>

          {/* filter + sort */}
          <div style={{padding: '10px 14px', borderBottom: `1px solid ${TV.line}`,
              display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap'}}>
            {['all', 'weak', 'strong'].map(f => (
              <span key={f} onClick={() => setFilter(f)}
                  className={filter === f ? 'tv-chip accent' : 'tv-chip'}
                  style={{cursor: 'pointer', textTransform: 'capitalize'}}>
                {filter === f && <span className="tv-dot"/>}{f}
              </span>
            ))}
            <div style={{flex: 1}}/>
            <span style={{fontSize: 11, color: TV.text3}}>sort</span>
            <select value={sort} onChange={e => setSort(e.target.value)} style={{
              background: TV.panel2, border: `1px solid ${TV.line}`, color: TV.text,
              fontFamily: TV.font, fontSize: 11, padding: '2px 6px', borderRadius: 3, outline: 'none',
            }}>
              <option value="weakness">weakness ↓</option>
              <option value="a-z">A–Z</option>
              <option value="tested">most tested</option>
            </select>
          </div>

          {/* concept rows */}
          <div style={{flex: 1, overflow: 'auto', minHeight: 0}}>
            {list.map(item => {
              const isSel = item.id === selected;
              const mc = item.mastery < 50 ? TV.fail : item.mastery < 70 ? TV.warn : TV.ok;
              return (
                <div key={item.id} onClick={() => setSelected(item.id)} style={{
                  padding: '10px 16px', cursor: 'pointer',
                  background: isSel ? TV.panel3 : 'transparent',
                  borderLeft: isSel ? `2px solid ${TV.accent}` : '2px solid transparent',
                  borderBottom: `1px solid ${TV.lineSoft}`,
                }}>
                  <div style={{display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 4}}>
                    <span style={{fontSize: 14, color: TV.text, fontWeight: 500}}>{item.name}</span>
                    <span style={{fontSize: 10, color: TV.text4, padding: '1px 5px',
                        borderRadius: 3, background: TV.panel2, textTransform: 'capitalize'}}>{item.family}</span>
                    <div style={{flex: 1}}/>
                    <span className="tv-num" style={{fontSize: 12, fontWeight: 600, color: mc}}>{item.mastery}%</span>
                  </div>
                  <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
                    <div style={{flex: 1, height: 4, background: TV.panel3, borderRadius: 2, overflow: 'hidden'}}>
                      <div style={{height: '100%', width: `${item.mastery}%`, background: mc}}/>
                    </div>
                    <span className="tv-num" style={{fontSize: 10, color: item.trend > 0 ? TV.ok : item.trend < 0 ? TV.fail : TV.text3,
                        whiteSpace: 'nowrap'}}>
                      {item.trend > 0 ? '▲' : item.trend < 0 ? '▼' : '·'} {Math.abs(item.trend)}%
                    </span>
                    <span className="tv-num" style={{fontSize: 10, color: TV.text4, whiteSpace: 'nowrap'}}>{item.timesTested} tests</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* RIGHT — detail */}
        <div style={{flex: 1, overflow: 'auto', minHeight: 0}}>
          {c && <ConceptDetail c={c}/>}
        </div>
      </div>
    </div>
  );
};

// ============================================
const ConceptDetail = ({c}) => {
  const mc = c.mastery < 50 ? TV.fail : c.mastery < 70 ? TV.warn : TV.ok;
  const tradeWinRate = Math.round((c.tradesW / (c.tradesW + c.tradesL)) * 100);

  return (
    <div>
      {/* HEADER */}
      <div style={{padding: '20px 28px 16px', borderBottom: `1px solid ${TV.line}`,
          display: 'flex', alignItems: 'flex-start', gap: 20}}>
        <div style={{flex: 1}}>
          <div className="tv-uppercase">{c.family} · concept</div>
          <div style={{fontSize: 28, fontWeight: 600, color: TV.text, marginTop: 4, letterSpacing: '-.5px',
              display: 'flex', alignItems: 'center', gap: 12}}>
            {c.name}
            <span style={{
              padding: '3px 10px', borderRadius: 4,
              border: `1px solid ${mc}`, background: mc === TV.fail ? TV.failSoft : mc === TV.warn ? TV.warnSoft : TV.okSoft,
              color: mc, fontSize: 12, fontWeight: 600, letterSpacing: '.04em', textTransform: 'uppercase',
            }}>
              {c.mastery < 50 ? 'WEAK' : c.mastery < 70 ? 'FORMING' : 'STRONG'} · {c.mastery}%
            </span>
          </div>
          <div style={{fontSize: 13, color: TV.text3, marginTop: 6, display: 'flex', alignItems: 'center', gap: 12}}>
            <span><span className="tv-num" style={{color: TV.text2, fontWeight: 600}}>{c.timesTested}</span> times tested</span>
            <span style={{color: TV.text4}}>·</span>
            <span><span className="tv-num" style={{color: TV.ok, fontWeight: 600}}>{c.correct}</span> correct
              <span style={{color: TV.text4}}> / </span>
              <span className="tv-num" style={{color: TV.fail, fontWeight: 600}}>{c.incorrect}</span> missed</span>
            <span style={{color: TV.text4}}>·</span>
            <span><span className="tv-num" style={{color: TV.text2, fontWeight: 600}}>{c.tradesN}</span> trades used this</span>
            <span style={{color: TV.text4}}>·</span>
            <span>net <span className="tv-num" style={{color: c.tradesNetR.startsWith('+') ? TV.ok : TV.fail, fontWeight: 600}}>{c.tradesNetR}</span></span>
          </div>
        </div>

        <div style={{display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end', flexShrink: 0}}>
          <button className="tv-btn primary" style={{padding: '9px 16px'}}>Test me on this →</button>
          <button className="tv-btn ghost" style={{fontSize: 12, padding: '5px 10px'}}>Edit definition</button>
        </div>
      </div>

      {/* DEFINITION + MASTERY CHART */}
      <div style={{padding: '20px 28px', display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 18}}>
        <div className="tv-card" style={{padding: 16, display: 'flex', flexDirection: 'column', gap: 14}}>
          <div>
            <div className="tv-uppercase" style={{marginBottom: 8}}>Definition</div>
            <div style={{fontSize: 15, color: TV.text, lineHeight: 1.65}}>{c.definition}</div>
            <div style={{display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap'}}>
              {c.related.map(r => (
                <span key={r} className="tv-chip" style={{cursor: 'pointer'}}>↗ {r}</span>
              ))}
            </div>
          </div>

          {/* concept chart illustration */}
          {CHARTS_BY_CONCEPT[c.id] && (
            <div style={{borderTop: `1px solid ${TV.lineSoft}`, paddingTop: 14}}>
              <div className="tv-uppercase" style={{marginBottom: 8}}>Example · annotated</div>
              <ConceptChart {...CHARTS_BY_CONCEPT[c.id]}/>
            </div>
          )}
        </div>

        <div className="tv-card" style={{padding: 16}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10}}>
            <div className="tv-uppercase">Mastery · last 4 weeks</div>
            <div style={{flex: 1}}/>
            <span className="tv-num" style={{fontSize: 12,
                color: c.trend > 0 ? TV.ok : c.trend < 0 ? TV.fail : TV.text3, fontWeight: 600}}>
              {c.trend > 0 ? '▲ +' : c.trend < 0 ? '▼ -' : '·'}{Math.abs(c.trend)}% wk-over-wk
            </span>
          </div>
          <MasterySpark history={c.history} color={mc}/>
        </div>
      </div>

      {/* SOURCE EPISODES */}
      <div style={{padding: '0 28px 18px'}}>
        <div className="tv-card" style={{padding: 14}}>
          <div className="tv-uppercase" style={{marginBottom: 10}}>Source episodes · where Mayne teaches this</div>
          <div style={{display: 'flex', flexDirection: 'column', gap: 8}}>
            {c.sources.map((s,i) => (
              <div key={i} style={{display: 'grid', gridTemplateColumns: '60px 1fr auto auto', gap: 14,
                  padding: '8px 10px', borderRadius: 5, background: TV.panel2, alignItems: 'center'}}>
                <span style={{fontSize: 11, color: TV.text3, fontWeight: 600, letterSpacing: '.06em'}}>EP {s.ep}</span>
                <span style={{fontSize: 14, color: TV.text}}>{s.title}</span>
                <span className="tv-num" style={{fontSize: 12, color: TV.text2}}>@ {s.at}</span>
                <button className="tv-btn ghost" style={{padding: '3px 9px', fontSize: 11}}>open ↗</button>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* RECENT MISSED QUESTIONS */}
      <div style={{padding: '0 28px 18px'}}>
        <div className="tv-card" style={{padding: 14}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12}}>
            <div className="tv-uppercase">Recent misses</div>
            <span style={{fontSize: 12, color: TV.text3}}>questions you've gotten wrong on this concept</span>
            <div style={{flex: 1}}/>
            {c.missed.length > 0 && <span className="tv-chip fail"><span className="tv-dot"/>{c.missed.length} this month</span>}
          </div>

          {c.missed.length === 0 ? (
            <div style={{padding: '20px 16px', background: TV.okSoft, border: `1px solid rgba(63,178,127,.25)`,
                borderRadius: 6, display: 'flex', alignItems: 'center', gap: 10}}>
              <div style={{width: 24, height: 24, borderRadius: '50%', background: TV.ok, color: '#0d1018',
                  fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>✓</div>
              <span style={{fontSize: 13, color: TV.text}}>No recent misses on this concept. Solid foundation.</span>
            </div>
          ) : (
            <div style={{display: 'flex', flexDirection: 'column', gap: 8}}>
              {c.missed.map((m,i) => (
                <div key={i} style={{padding: 12, borderRadius: 6, background: TV.panel2, border: `1px solid ${TV.lineSoft}`}}>
                  <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6}}>
                    <span style={{fontSize: 11, color: TV.text3, fontWeight: 600}}>QUIZ #{m.quiz}</span>
                    <span style={{color: TV.text4}}>·</span>
                    <span style={{fontSize: 11, color: TV.text3}}>{m.date}</span>
                  </div>
                  <div style={{fontSize: 14, color: TV.text, marginBottom: 8, fontStyle: 'italic'}}>{m.q}</div>
                  <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 8}}>
                    <div style={{padding: '6px 10px', borderRadius: 4, background: TV.failSoft,
                        border: `1px solid rgba(217,83,79,.3)`}}>
                      <div style={{fontSize: 10, color: TV.fail, fontWeight: 600, letterSpacing: '.06em',
                          textTransform: 'uppercase', marginBottom: 2}}>you chose</div>
                      <div style={{fontSize: 13, color: TV.text}}>{m.chose}</div>
                    </div>
                    <div style={{padding: '6px 10px', borderRadius: 4, background: TV.okSoft,
                        border: `1px solid rgba(63,178,127,.3)`}}>
                      <div style={{fontSize: 10, color: TV.ok, fontWeight: 600, letterSpacing: '.06em',
                          textTransform: 'uppercase', marginBottom: 2}}>correct</div>
                      <div style={{fontSize: 13, color: TV.text}}>{m.right}</div>
                    </div>
                  </div>
                  <div style={{fontSize: 12, color: TV.text2, lineHeight: 1.5, paddingLeft: 10,
                      borderLeft: `2px solid ${TV.adapt}`}}>
                    <span style={{color: TV.adapt, fontWeight: 600}}>↳ why I got it wrong: </span>{m.why}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* TRADES USING THIS CONCEPT */}
      <div style={{padding: '0 28px 22px'}}>
        <div className="tv-card" style={{padding: 14}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12}}>
            <div className="tv-uppercase">Trades using this concept</div>
            <div style={{flex: 1}}/>
            <span className="tv-chip"><span className="tv-num">{c.tradesN}</span> trades</span>
            <span className="tv-chip ok"><span className="tv-num">{c.tradesW}W</span></span>
            <span className="tv-chip fail"><span className="tv-num">{c.tradesL}L</span></span>
          </div>

          <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 14}}>
            {/* win rate */}
            <div style={{padding: 12, borderRadius: 6, background: TV.panel2, border: `1px solid ${TV.lineSoft}`}}>
              <div className="tv-uppercase">Win rate</div>
              <div className="tv-num" style={{fontSize: 22, fontWeight: 700, color: tradeWinRate >= 60 ? TV.ok : tradeWinRate >= 45 ? TV.text : TV.warn,
                  marginTop: 2, letterSpacing: '-.4px'}}>{tradeWinRate}%</div>
              <div style={{height: 4, background: TV.panel3, borderRadius: 2, overflow: 'hidden', marginTop: 8}}>
                <div style={{height: '100%', width: `${tradeWinRate}%`,
                    background: tradeWinRate >= 60 ? TV.ok : tradeWinRate >= 45 ? TV.text2 : TV.warn}}/>
              </div>
            </div>
            {/* net R */}
            <div style={{padding: 12, borderRadius: 6, background: TV.panel2, border: `1px solid ${TV.lineSoft}`}}>
              <div className="tv-uppercase">Net R</div>
              <div className="tv-num" style={{fontSize: 22, fontWeight: 700,
                  color: c.tradesNetR.startsWith('+') ? TV.ok : TV.fail, marginTop: 2, letterSpacing: '-.4px'}}>{c.tradesNetR}</div>
              <div style={{fontSize: 11, color: TV.text3, marginTop: 6}}>
                avg <span className="tv-num">{(parseFloat(c.tradesNetR) / c.tradesN).toFixed(2)}R</span> / trade
              </div>
            </div>
            {/* best / worst */}
            <div style={{padding: 12, borderRadius: 6, background: TV.panel2, border: `1px solid ${TV.lineSoft}`}}>
              <div className="tv-uppercase">Best / worst</div>
              {c.bestTrade && (
                <div style={{fontSize: 12, color: TV.text, marginTop: 4, display: 'flex', alignItems: 'center', gap: 6}}>
                  <span style={{color: TV.ok, fontWeight: 700, fontSize: 11}}>▲</span>
                  <span>{c.bestTrade}</span>
                </div>
              )}
              {c.worstTrade && (
                <div style={{fontSize: 12, color: TV.text, marginTop: 4, display: 'flex', alignItems: 'center', gap: 6}}>
                  <span style={{color: TV.fail, fontWeight: 700, fontSize: 11}}>▼</span>
                  <span>{c.worstTrade}</span>
                </div>
              )}
            </div>
          </div>

          <div style={{marginTop: 12, display: 'flex', justifyContent: 'flex-end'}}>
            <button className="tv-btn" style={{fontSize: 12, padding: '5px 10px'}}>View all {c.tradesN} in Journal →</button>
          </div>
        </div>
      </div>
    </div>
  );
};

// ============================================
const MasterySpark = ({history, color}) => {
  const W = 360, H = 110, pad = 24;
  const maxV = 100, minV = 0;
  const pts = history.map((v,i) => [
    pad + (i / (history.length - 1)) * (W - pad * 2),
    H - pad - (v / 100) * (H - pad * 2),
  ]);
  const pathD = pts.map((p,i) => `${i === 0 ? 'M' : 'L'} ${p[0]} ${p[1]}`).join(' ');
  const lastPt = pts[pts.length - 1];

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none">
        {[25, 50, 75].map(g => (
          <g key={g}>
            <line x1={pad} x2={W - pad}
                  y1={H - pad - (g / 100) * (H - pad * 2)}
                  y2={H - pad - (g / 100) * (H - pad * 2)}
                  stroke={TV.lineSoft} strokeDasharray="2 4"/>
            <text x={4} y={H - pad - (g / 100) * (H - pad * 2) + 3}
                  fontSize="9" fill={TV.text4}>{g}%</text>
          </g>
        ))}
        <path d={`${pathD} L ${lastPt[0]} ${H - pad} L ${pad} ${H - pad} Z`}
              fill={color} fillOpacity="0.08"/>
        <path d={pathD} fill="none" stroke={color} strokeWidth="1.8"
              strokeLinecap="round" strokeLinejoin="round"/>
        {pts.map((p,i) => (
          <circle key={i} cx={p[0]} cy={p[1]} r="3" fill={color}/>
        ))}
        {/* week labels */}
        {['-3w','-2w','-1w','now'].map((lbl, i) => (
          <text key={lbl} x={pad + (i / 3) * (W - pad * 2)} y={H - 6} fontSize="9" fill={TV.text4} textAnchor="middle">
            {lbl}
          </text>
        ))}
      </svg>
    </div>
  );
};

Object.assign(window, {ConceptsHF});
