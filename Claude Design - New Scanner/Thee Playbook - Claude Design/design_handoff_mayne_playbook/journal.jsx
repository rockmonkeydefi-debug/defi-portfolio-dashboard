// journal.jsx — Journal / history screen (dark hi-fi)
// Mixed timeline of trade reasoning records (from validator 5C) and quiz attempts.
// Left: filterable feed grouped by day. Right: detail pane for selected entry.

const JournalHF = () => {
  const [selected, setSelected] = React.useState('t-may23-btc');
  const [kindFilter, setKindFilter] = React.useState('trades'); // 'trades' | 'quizzes'
  const [conceptFilter, setConceptFilter] = React.useState('all'); // 'all' | concept name

  // mixed feed — chronological, grouped client-side by day
  const entries = [
    // -------- May 24 (today) --------
    {
      id: 't-may24-btc',
      kind: 'trade',
      date: '2026-05-24',
      time: '06:51',
      ticker: 'BTCUSD',
      htf: '4H', ltf: '15m',
      dir: 'long',
      readiness: 'READY',
      passed: 5, total: 6,
      thesis: 'Long entry on BTCUSD at 71,830. HTF bullish bias on 4H with price in discount. Sell-side liquidity swept; LTF confirmed via 5m sweep + CHoCH and a virgin bullish FVG.',
      concepts: ['Order Block','FVG','Liquidity Sweep','Killzone'],
      outcome: 'open', // open | win | loss | skipped
      pnl: null,
      entry: '71,830', stop: '71,640', target: '72,300',
      notes: 'London killzone in effect. Already on alert from the daily plan. Holding off entry until 5m gives a clean CHoCH — if it flushes back below 71,800 first I\'m out, no second chance.',
    },
    {
      id: 'q-may24',
      kind: 'quiz',
      date: '2026-05-24',
      time: '—',
      n: 48,
      score: null,
      total: 8,
      status: 'ready',
      concepts: ['Order Block','FVG'],
    },
    // -------- May 23 --------
    {
      id: 't-may23-btc',
      kind: 'trade',
      date: '2026-05-23',
      time: '09:12',
      ticker: 'BTCUSD',
      htf: '4H', ltf: '15m',
      dir: 'long',
      readiness: 'READY',
      passed: 6, total: 6,
      thesis: 'Long off the daily OB tap at 70,920. HTF clearly bullish, premium-to-discount return complete. Strong LTF confirmation: 5m sweep, CHoCH, then re-entry into FVG.',
      concepts: ['Order Block','FVG','BOS / CHoCH'],
      outcome: 'win',
      pnl: '+1.8R',
      entry: '70,940', stop: '70,720', target: '71,500',
      result: 'Hit target at 71,510 · closed at 12:48',
      lesson: 'OB tap + LTF CHoCH continues to be the highest-conviction setup. Sizing felt comfortable at 1.2%.',
      notes: 'Felt no hesitation entering. The 4H structure made this obvious in retrospect — every box checked. Closed at the daily resistance even though my target was a touch higher; better to take the obvious exit than wait for the last tick.',
    },
    {
      id: 'q-may23',
      kind: 'quiz',
      date: '2026-05-23',
      time: '07:14',
      n: 47,
      score: 7, total: 8,
      missed: [{q: 5, concept: 'FVG', why: 'Confused mitigation with a sweep'}],
      concepts: ['FVG','Liquidity Sweep','BOS / CHoCH'],
    },
    // -------- May 22 --------
    {
      id: 'q-may22',
      kind: 'quiz',
      date: '2026-05-22',
      time: '07:02',
      n: 46,
      score: 6, total: 8,
      missed: [
        {q: 3, concept: 'FVG', why: 'Picked the wrong candle as the FVG origin'},
        {q: 7, concept: 'Order Block', why: 'Treated the largest red candle as OB instead of last opposing close'},
      ],
      concepts: ['Order Block','FVG','Killzones'],
    },
    // -------- May 21 --------
    {
      id: 't-may21-es',
      kind: 'trade',
      date: '2026-05-21',
      time: '14:30',
      ticker: 'ES',
      htf: 'D',  ltf: '1H',
      dir: 'short',
      readiness: 'NOT READY',
      passed: 3, total: 6,
      thesis: 'Considered a short on ES at 5,748 — but HTF bias was ambiguous (4H structure was sideways) and there was no clear sweep into premium before entry.',
      concepts: ['Bias','Liquidity Sweep'],
      outcome: 'skipped',
      pnl: null,
      reason: 'Stood aside — bias unclear, no qualifying sweep',
      notes: 'Was tempted because of the move into the level, but the validator was right — nothing on the HTF was confirming. Worth journaling that I almost took this and then watched it chop sideways for two hours.',
    },
    // -------- May 20 --------
    {
      id: 't-may20-aapl',
      kind: 'trade',
      date: '2026-05-20',
      time: '10:48',
      ticker: 'AAPL',
      htf: 'D',  ltf: '1H',
      dir: 'long',
      readiness: 'CONDITIONAL',
      passed: 4, total: 6,
      thesis: 'Long AAPL at 184.20 on a daily OB tap, but HTF 4H bias was weak and dealing range was at equilibrium. Took it anyway with reduced size.',
      concepts: ['Order Block','Bias'],
      outcome: 'loss',
      pnl: '-1.0R',
      entry: '184.20', stop: '183.40', target: '186.50',
      result: 'Stopped out at 183.38 · 11:30',
      lesson: 'Validator said CONDITIONAL — should have skipped or waited for clearer HTF confirmation. Don\'t override the readiness verdict to chase setups.',
      notes: 'I knew this was a stretch. Took it because I hadn\'t traded in two days and was itching. The lesson is real: validator readiness is not a vibe check, it\'s a filter. CONDITIONAL means CONDITIONAL.',
    },
    {
      id: 'q-may20',
      kind: 'quiz',
      date: '2026-05-20',
      time: '06:58',
      n: 44,
      score: 8, total: 8,
      concepts: ['Killzones','Liquidity Sweep'],
    },
    // -------- May 19 --------
    {
      id: 't-may19-nq',
      kind: 'trade',
      date: '2026-05-19',
      time: '15:22',
      ticker: 'NQ',
      htf: 'D',  ltf: '1H',
      dir: 'short',
      readiness: 'READY',
      passed: 5, total: 6,
      thesis: 'Short NQ at 20,310 off buy-side sweep into premium. R:R was tight (1:1.8) so took partial.',
      concepts: ['Liquidity Sweep','FVG'],
      outcome: 'win',
      pnl: '+0.8R',
      entry: '20,310', stop: '20,360', target: '20,220',
      result: 'Partial at 20,260, BE on rest · closed 16:48',
      lesson: 'Taking partials at tight R:R works for me — keeps the win-rate high without giving back.',
      notes: 'Friday afternoon, low conviction overall but the sweep was clean. Half off at +0.8R, stop to BE, walked away. No regret about not letting the rest run.',
    },
  ];

  // apply filters
  const filteredEntries = entries.filter(e => {
    const kindMatch = kindFilter === 'trades' ? e.kind === 'trade' : e.kind === 'quiz';
    const conceptMatch = conceptFilter === 'all' || (e.concepts || []).includes(conceptFilter);
    return kindMatch && conceptMatch;
  });

  // re-select first visible entry if current selection isn't in view
  React.useEffect(() => {
    if (!filteredEntries.find(e => e.id === selected) && filteredEntries.length > 0) {
      setSelected(filteredEntries[0].id);
    }
  }, [kindFilter, conceptFilter]);

  // group by date
  const byDate = filteredEntries.reduce((acc, e) => {
    (acc[e.date] = acc[e.date] || []).push(e);
    return acc;
  }, {});

  const selectedEntry = entries.find(e => e.id === selected);

  // 30-day stats
  const taken = entries.filter(e => e.kind === 'trade' && (e.outcome === 'win' || e.outcome === 'loss'));
  const wins = taken.filter(e => e.outcome === 'win').length;
  const losses = taken.filter(e => e.outcome === 'loss').length;
  const skipped = entries.filter(e => e.kind === 'trade' && e.outcome === 'skipped').length;
  const totalR = taken.reduce((s,e) => s + parseFloat(e.pnl), 0).toFixed(1);

  return (
    <div className="tv-frame" style={{display: 'flex', flexDirection: 'column'}}>
      <TVNav active="Journal"/>
    <TTSubNav active="Journal"/>

      <div style={{flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden'}}>
        {/* LEFT: timeline */}
        <div style={{flex: 1.3, display: 'flex', flexDirection: 'column',
            borderRight: `1px solid ${TV.line}`, minWidth: 0, minHeight: 0, overflow: 'hidden'}}>

          {/* header + filters */}
          <div style={{padding: '18px 22px 14px', borderBottom: `1px solid ${TV.line}`}}>
            <div style={{display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12}}>
              <div>
                <div className="tv-uppercase">Journal · history</div>
                <div style={{fontSize: 22, fontWeight: 600, color: TV.text, marginTop: 4}}>Last 30 days</div>
              </div>
              <div style={{display: 'flex', alignItems: 'center', gap: 14, fontSize: 13, color: TV.text2}}>
                <span><span className="tv-num" style={{color: TV.ok, fontWeight: 600}}>{wins}W</span> /
                  <span className="tv-num" style={{color: TV.fail, fontWeight: 600}}> {losses}L</span></span>
                <span style={{color: TV.text4}}>·</span>
                <span><span className="tv-num" style={{color: TV.text, fontWeight: 600}}>{skipped}</span> skipped</span>
                <span style={{color: TV.text4}}>·</span>
                <span>net <span className="tv-num" style={{color: parseFloat(totalR) >= 0 ? TV.ok : TV.fail, fontWeight: 600}}>{parseFloat(totalR) >= 0 ? '+' : ''}{totalR}R</span></span>
                <span style={{color: TV.text4}}>·</span>
                <span><span className="tv-num" style={{color: TV.text, fontWeight: 600}}>4 / 5</span> quizzes</span>
              </div>
            </div>

            {/* filter row */}
            <div style={{display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap'}}>
              {/* kind toggle — exclusive */}
              <div style={{display: 'inline-flex', border: `1px solid ${TV.line}`, borderRadius: 5, padding: 2,
                  background: TV.panel2}}>
                {['trades', 'quizzes'].map(k => {
                  const sel = kindFilter === k;
                  const count = entries.filter(e => k === 'trades' ? e.kind === 'trade' : e.kind === 'quiz').length;
                  return (
                    <div key={k} onClick={() => setKindFilter(k)} style={{
                      padding: '4px 12px', borderRadius: 3, fontSize: 12, fontWeight: 500,
                      cursor: 'pointer', textTransform: 'capitalize',
                      color: sel ? TV.text : TV.text3,
                      background: sel ? TV.panel3 : 'transparent',
                      borderBottom: sel ? `1.5px solid ${TV.accent}` : '1.5px solid transparent',
                      transition: 'all .12s',
                    }}>
                      {k} · {count}
                    </div>
                  );
                })}
              </div>

              <div style={{width: 1, height: 18, background: TV.line, margin: '0 4px'}}/>

              <span style={{fontSize: 11, color: TV.text3, marginRight: 4, fontWeight: 600, letterSpacing: '.04em', textTransform: 'uppercase'}}>concept</span>
              {['all', 'Order Block', 'FVG', 'Liquidity Sweep', 'BOS / CHoCH', 'Killzones'].map(c => {
                const sel = conceptFilter === c;
                return (
                  <span key={c} onClick={() => setConceptFilter(c)} className={sel ? 'tv-chip accent' : 'tv-chip'}
                      style={{cursor: 'pointer', textTransform: c === 'all' ? 'lowercase' : 'none'}}>
                    {sel && <span className="tv-dot"/>}{c}
                  </span>
                );
              })}
              <span className="tv-chip" style={{borderStyle: 'dashed', color: TV.text3, cursor: 'pointer'}}>+ more</span>

              <div style={{flex: 1}}/>
              <span style={{fontSize: 12, color: TV.text3}}>search</span>
              <div className="tv-card" style={{padding: '4px 10px', fontSize: 12, color: TV.text3,
                  background: TV.panel2, width: 160}}>by ticker · concept · text…</div>
            </div>
          </div>

          {/* feed */}
          <div style={{flex: 1, overflow: 'auto', minHeight: 0, padding: '0 6px'}}>
            {Object.entries(byDate).map(([date, items]) => (
              <div key={date}>
                <div style={{padding: '14px 16px 8px', display: 'flex', alignItems: 'baseline', gap: 12,
                    position: 'sticky', top: 0, background: TV.bg, zIndex: 1}}>
                  <div className="tv-uppercase">{formatDate(date)}</div>
                  <div style={{flex: 1, height: 1, background: TV.lineSoft}}/>
                  <div style={{fontSize: 11, color: TV.text4}}>{items.length} {items.length === 1 ? 'entry' : 'entries'}</div>
                </div>
                {items.map(e => (
                  <JournalRow key={e.id} entry={e} selected={selected === e.id} onSelect={() => setSelected(e.id)}/>
                ))}
              </div>
            ))}
          </div>
        </div>

        {/* RIGHT: detail */}
        <div style={{flex: 1, display: 'flex', flexDirection: 'column', background: TV.panel,
            minHeight: 0, overflow: 'hidden'}}>
          {selectedEntry ? <JournalDetail entry={selectedEntry}/> : null}
        </div>
      </div>
    </div>
  );
};

// ---------- helpers ----------
function formatDate(iso) {
  const d = new Date(iso + 'T00:00:00');
  const today = new Date('2026-05-24T00:00:00');
  const days = Math.floor((today - d) / 86400000);
  const fmt = d.toLocaleDateString('en-US', {weekday: 'short', month: 'short', day: 'numeric'});
  if (days === 0) return `Today · ${fmt}`;
  if (days === 1) return `Yesterday · ${fmt}`;
  return fmt;
}

function readinessColor(r) {
  return r === 'READY' ? TV.ok : r === 'CONDITIONAL' ? TV.warn : TV.fail;
}

function outcomeChip(o, pnl) {
  if (o === 'win')     return <span className="tv-chip ok"><span className="tv-dot"/>win {pnl}</span>;
  if (o === 'loss')    return <span className="tv-chip fail"><span className="tv-dot"/>loss {pnl}</span>;
  if (o === 'skipped') return <span className="tv-chip" style={{color: TV.text3}}><span className="tv-dot" style={{background: TV.text4}}/>skipped</span>;
  if (o === 'open')    return <span className="tv-chip warn"><span className="tv-dot"/>open</span>;
  return null;
}

// ---------- row ----------
const JournalRow = ({entry: e, selected, onSelect}) => {
  const isQuiz = e.kind === 'quiz';
  return (
    <div onClick={onSelect} style={{
      padding: '12px 16px', margin: '2px 0',
      borderRadius: 6, cursor: 'pointer',
      background: selected ? TV.panel3 : 'transparent',
      borderLeft: selected ? `2px solid ${TV.accent}` : '2px solid transparent',
      display: 'grid', gridTemplateColumns: '40px 1fr auto', gap: 14, alignItems: 'center',
      transition: 'background .12s',
    }}>
      {/* type icon */}
      <div style={{
        width: 32, height: 32, borderRadius: 6,
        background: isQuiz ? TV.panel2 : (e.outcome === 'win' ? TV.okSoft :
            e.outcome === 'loss' ? TV.failSoft : e.outcome === 'open' ? TV.warnSoft : TV.panel2),
        border: `1px solid ${isQuiz ? TV.line :
            e.outcome === 'win' ? 'rgba(63,178,127,.35)' :
            e.outcome === 'loss' ? 'rgba(217,83,79,.35)' :
            e.outcome === 'open' ? 'rgba(224,179,65,.35)' : TV.line}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 14, fontWeight: 700,
        color: isQuiz ? TV.text2 :
            e.outcome === 'win' ? TV.ok :
            e.outcome === 'loss' ? TV.fail :
            e.outcome === 'open' ? TV.warn : TV.text3,
      }}>
        {isQuiz ? 'Q' : 'T'}
      </div>

      {/* body */}
      {isQuiz ? (
        <div style={{minWidth: 0}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2}}>
            <span style={{fontSize: 14, color: TV.text, fontWeight: 500}}>Quiz #{e.n}</span>
            {e.score != null
              ? <span className="tv-chip" style={{fontSize: 11, padding: '1px 6px',
                  color: e.score === e.total ? TV.ok : e.score / e.total >= 0.8 ? TV.text : TV.warn,
                  borderColor: e.score === e.total ? 'rgba(63,178,127,.35)' :
                    e.score / e.total >= 0.8 ? TV.line : 'rgba(224,179,65,.35)'}}>
                  {e.score} / {e.total}
                </span>
              : <span className="tv-chip ok" style={{fontSize: 11, padding: '1px 6px'}}><span className="tv-dot"/>ready</span>}
          </div>
          <div style={{fontSize: 12, color: TV.text3, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap'}}>
            <span>{e.time}</span>
            <span>·</span>
            {e.concepts.slice(0, 3).map(c => <span key={c}>{c}</span>).reduce((p, c, i) => i === 0 ? [c] : [...p, <span key={i + 'sep'} style={{color: TV.text4}}>·</span>, c], [])}
            {e.missed && <>
              <span style={{color: TV.text4}}>·</span>
              <span style={{color: TV.warn}}>missed {e.missed.length} on {e.missed[0].concept}{e.missed.length > 1 ? ' & more' : ''}</span>
            </>}
          </div>
        </div>
      ) : (
        <div style={{minWidth: 0}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3}}>
            <span className="tv-num" style={{fontSize: 14, color: TV.text, fontWeight: 600}}>{e.ticker}</span>
            <TfPair htf={e.htf} ltf={e.ltf}/>
            <span style={{fontSize: 12, color: e.dir === 'long' ? TV.ok : TV.fail, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '.04em'}}>{e.dir}</span>
            <span className="tv-chip" style={{fontSize: 10, padding: '1px 6px',
                color: readinessColor(e.readiness),
                borderColor: e.readiness === 'READY' ? 'rgba(63,178,127,.35)' :
                  e.readiness === 'CONDITIONAL' ? 'rgba(224,179,65,.35)' : 'rgba(217,83,79,.35)'}}>
              {e.readiness} · {e.passed}/{e.total}
            </span>
            {outcomeChip(e.outcome, e.pnl)}
          </div>
          <div style={{fontSize: 13, color: TV.text2, overflow: 'hidden',
              textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
            {e.thesis}
          </div>
        </div>
      )}

      <div style={{fontSize: 11, color: TV.text3, textAlign: 'right', whiteSpace: 'nowrap'}}>
        {e.time !== '—' ? e.time : ''}
        <div style={{color: TV.text4, marginTop: 2}}>›</div>
      </div>
    </div>
  );
};

// ---------- detail pane ----------
const JournalDetail = ({entry: e}) => {
  if (e.kind === 'quiz') return <QuizDetail entry={e}/>;
  return <TradeDetail entry={e}/>;
};

const TradeDetail = ({entry: e}) => {
  const rcolor = readinessColor(e.readiness);
  const oColor = e.outcome === 'win' ? TV.ok : e.outcome === 'loss' ? TV.fail : e.outcome === 'open' ? TV.warn : TV.text3;
  return (
    <>
      {/* header */}
      <div style={{padding: '18px 24px 14px', borderBottom: `1px solid ${TV.line}`}}>
        <div className="tv-uppercase">Pre-trade reasoning · {formatDate(e.date)}</div>
        <div style={{display: 'flex', alignItems: 'center', gap: 10, marginTop: 6}}>
          <div style={{fontSize: 20, fontWeight: 600, color: TV.text}}>{e.ticker}</div>
          <TfPair htf={e.htf} ltf={e.ltf}/>
          <div style={{fontSize: 12, color: e.dir === 'long' ? TV.ok : TV.fail, fontWeight: 600,
              textTransform: 'uppercase', letterSpacing: '.06em'}}>{e.dir}</div>
          <div style={{flex: 1}}/>
          <span className="tv-chip" style={{color: rcolor, borderColor: rcolor === TV.ok ? 'rgba(63,178,127,.4)' : rcolor === TV.warn ? 'rgba(224,179,65,.4)' : 'rgba(217,83,79,.4)',
              background: rcolor === TV.ok ? TV.okSoft : rcolor === TV.warn ? TV.warnSoft : TV.failSoft}}>
            {e.readiness} · {e.passed}/{e.total}
          </span>
          {outcomeChip(e.outcome, e.pnl)}
        </div>
      </div>

      <div style={{flex: 1, overflow: 'auto', minHeight: 0, padding: '18px 24px',
          display: 'flex', flexDirection: 'column', gap: 16}}>

        {/* thesis */}
        <div>
          <div className="tv-uppercase" style={{marginBottom: 6}}>Thesis</div>
          <div style={{fontSize: 14, color: TV.text, lineHeight: 1.6, padding: '10px 12px',
              borderRadius: 6, border: `1px dashed ${TV.line}`, background: 'rgba(255,255,255,.015)'}}>
            {e.thesis}
          </div>
        </div>

        {/* plan grid (only if taken/open) */}
        {e.entry && (
          <div className="tv-card" style={{padding: 14}}>
            <div className="tv-uppercase" style={{marginBottom: 8}}>Execution plan</div>
            <div style={{display: 'grid', gridTemplateColumns: 'auto 1fr auto 1fr', gap: '6px 18px', fontSize: 13}}>
              <span style={{color: TV.text3}}>Entry</span>
              <span className="tv-num" style={{color: TV.text, fontWeight: 600}}>{e.entry}</span>
              <span style={{color: TV.text3}}>Stop</span>
              <span className="tv-num" style={{color: TV.text}}>{e.stop}</span>
              <span style={{color: TV.text3}}>Target</span>
              <span className="tv-num" style={{color: TV.text}}>{e.target}</span>
              <span style={{color: TV.text3}}>Time</span>
              <span className="tv-num" style={{color: TV.text2}}>{e.time}</span>
            </div>
          </div>
        )}

        {/* concepts */}
        <div>
          <div className="tv-uppercase" style={{marginBottom: 6}}>Concepts</div>
          <div style={{display: 'flex', gap: 6, flexWrap: 'wrap'}}>
            {e.concepts.map(c => <span key={c} className="tv-chip">{c}</span>)}
          </div>
        </div>

        {/* screenshots strip — preview only; full grid on entry page */}
        <div>
          <div style={{display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 6}}>
            <div className="tv-uppercase">Screenshots</div>
            <span style={{fontSize: 11, color: TV.text3}}>
              <span className="tv-num" style={{color: TV.text2}}>{e.outcome === 'open' ? 3 : 9}</span> attached · open full page to add more →
            </span>
          </div>
          <div style={{display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 6}}>
            {['HTF', 'LTF', 'Entry', 'Manage', 'Exit'].map((tag, i) => (
              <div key={tag} style={{
                aspectRatio: '4 / 3',
                borderRadius: 4,
                border: `1px solid ${TV.line}`,
                background:
                  `repeating-linear-gradient(45deg, ${TV.panel2} 0 8px, ${TV.panel3} 8px 16px)`,
                position: 'relative', overflow: 'hidden',
              }}>
                <div style={{position: 'absolute', top: 4, left: 4, fontSize: 9, color: TV.text3,
                    fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase',
                    background: 'rgba(13,16,24,.7)', padding: '1px 5px', borderRadius: 2}}>{tag}</div>
              </div>
            ))}
          </div>
        </div>

        {/* free-text notes — editable */}
        <div>
          <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6}}>
            <div className="tv-uppercase">Notes</div>
            <span style={{fontSize: 11, color: TV.text4}}>your own observations · markdown supported</span>
            <div style={{flex: 1}}/>
            <span style={{fontSize: 11, color: TV.text3, display: 'inline-flex', alignItems: 'center', gap: 4}}>
              <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
                <path d="M11.5 2.5 L13.5 4.5 L5 13 L2 14 L3 11 L11.5 2.5 Z" stroke={TV.text3} strokeWidth="1.4" strokeLinejoin="round"/>
              </svg>
              click to edit
            </span>
          </div>
          <div
            contentEditable
            suppressContentEditableWarning
            spellCheck={false}
            style={{
              fontSize: 14, color: TV.text, lineHeight: 1.6,
              padding: '12px 14px', borderRadius: 6,
              border: `1px dashed ${TV.line}`,
              background: 'rgba(255,255,255,0.015)',
              outline: 'none', cursor: 'text',
              minHeight: 60,
              fontFamily: TV.font,
            }}
          >
            {e.notes || <span style={{color: TV.text3, fontStyle: 'italic'}}>Add your own notes — what you were feeling, what you saw on the chart that's not in the validator, anything you want to remember…</span>}
          </div>
          <div style={{fontSize: 11, color: TV.text4, marginTop: 4, display: 'flex', justifyContent: 'space-between'}}>
            <span>last edited · 1h ago</span>
            <span>⌘S to save</span>
          </div>
        </div>

        {/* outcome block */}
        {e.outcome === 'win' || e.outcome === 'loss' ? (
          <div className="tv-card" style={{padding: 14, borderColor: oColor,
              background: e.outcome === 'win' ? TV.okSoft : TV.failSoft}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6}}>
              <span className="tv-uppercase" style={{color: oColor}}>Outcome · {e.outcome.toUpperCase()} {e.pnl}</span>
            </div>
            <div style={{fontSize: 13, color: TV.text, marginBottom: 8}}>{e.result}</div>
            {e.lesson && <>
              <div className="tv-uppercase" style={{marginTop: 8, marginBottom: 4}}>Lesson</div>
              <div style={{fontSize: 13, color: TV.text2, lineHeight: 1.55,
                  borderLeft: `2px solid ${oColor}`, paddingLeft: 10}}>
                {e.lesson}
              </div>
            </>}
          </div>
        ) : e.outcome === 'skipped' ? (
          <div className="tv-card" style={{padding: 14}}>
            <div className="tv-uppercase" style={{marginBottom: 6}}>Why I stood aside</div>
            <div style={{fontSize: 13, color: TV.text2, lineHeight: 1.55}}>{e.reason}</div>
          </div>
        ) : (
          <div className="tv-card" style={{padding: 14, borderColor: TV.warn, background: TV.warnSoft}}>
            <div className="tv-uppercase" style={{color: TV.warn, marginBottom: 6}}>Open · awaiting outcome</div>
            <div style={{fontSize: 13, color: TV.text, marginBottom: 10}}>Trade is live. Mark the result when closed.</div>
            <div style={{display: 'flex', gap: 8}}>
              <button className="tv-btn" style={{fontSize: 13}}>Mark as W</button>
              <button className="tv-btn" style={{fontSize: 13}}>Mark as L</button>
              <button className="tv-btn ghost" style={{fontSize: 13}}>Mark as breakeven</button>
            </div>
          </div>
        )}

        <div style={{flex: 1}}/>

        <div style={{display: 'flex', gap: 8, alignItems: 'center'}}>
          <button className="tv-btn ghost" style={{fontSize: 13}}>← Edit</button>
          <button className="tv-btn ghost" style={{fontSize: 13}}>Copy as text</button>
          <div style={{flex: 1}}/>
          <button className="tv-btn ghost" style={{fontSize: 13}}>Re-open validator →</button>
          <button className="tv-btn primary" style={{fontSize: 13}}>Open full page ↗</button>
        </div>
      </div>
    </>
  );
};

const QuizDetail = ({entry: e}) => (
  <>
    <div style={{padding: '18px 24px 14px', borderBottom: `1px solid ${TV.line}`}}>
      <div className="tv-uppercase">Quiz · {formatDate(e.date)}</div>
      <div style={{display: 'flex', alignItems: 'center', gap: 10, marginTop: 6}}>
        <div style={{fontSize: 20, fontWeight: 600, color: TV.text}}>Quiz #{e.n}</div>
        <div style={{flex: 1}}/>
        {e.score != null ? (
          <span style={{
            padding: '4px 12px', borderRadius: 6,
            border: `1px solid ${e.score === e.total ? TV.ok : e.score / e.total >= 0.8 ? TV.text2 : TV.warn}`,
            background: e.score === e.total ? TV.okSoft : e.score / e.total >= 0.8 ? 'transparent' : TV.warnSoft,
            fontSize: 14, fontWeight: 600,
            color: e.score === e.total ? TV.ok : e.score / e.total >= 0.8 ? TV.text : TV.warn,
          }}>
            {e.score} / {e.total}
          </span>
        ) : (
          <span className="tv-chip ok"><span className="tv-dot"/>ready · not yet taken</span>
        )}
      </div>
    </div>

    <div style={{flex: 1, overflow: 'auto', minHeight: 0, padding: '18px 24px',
        display: 'flex', flexDirection: 'column', gap: 16}}>
      <div>
        <div className="tv-uppercase" style={{marginBottom: 6}}>Concepts covered</div>
        <div style={{display: 'flex', gap: 6, flexWrap: 'wrap'}}>
          {e.concepts.map(c => <span key={c} className="tv-chip">{c}</span>)}
        </div>
      </div>

      {e.missed && e.missed.length > 0 && (
        <div>
          <div className="tv-uppercase" style={{marginBottom: 6}}>Missed · {e.missed.length}</div>
          <div className="tv-card" style={{overflow: 'hidden'}}>
            {e.missed.map((m, i) => (
              <div key={i} style={{
                padding: '12px 14px',
                borderBottom: i < e.missed.length - 1 ? `1px solid ${TV.lineSoft}` : 'none',
                display: 'grid', gridTemplateColumns: '28px 1fr', gap: 12, alignItems: 'flex-start',
              }}>
                <div style={{width: 22, height: 22, borderRadius: '50%',
                    background: TV.failSoft, border: `1px solid ${TV.fail}`,
                    color: TV.fail, fontWeight: 700, fontSize: 12,
                    display: 'flex', alignItems: 'center', justifyContent: 'center'}}>×</div>
                <div>
                  <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2}}>
                    <span style={{fontSize: 13, color: TV.text, fontWeight: 600}}>Q{m.q}</span>
                    <span className="tv-chip accent" style={{fontSize: 11}}>{m.concept}</span>
                  </div>
                  <div style={{fontSize: 13, color: TV.text2, lineHeight: 1.5}}>{m.why}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {e.score != null && e.score === e.total && (
        <div className="tv-card" style={{padding: 14, borderColor: TV.ok, background: TV.okSoft,
            fontSize: 13, color: TV.text, display: 'flex', gap: 10, alignItems: 'center'}}>
          <div style={{width: 24, height: 24, borderRadius: '50%', background: TV.ok, color: '#0d1018',
              fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>✓</div>
          Perfect score. Killzones and Liquidity Sweep both moving toward mastery.
        </div>
      )}

      {e.score == null && (
        <div className="tv-card" style={{padding: 14, fontSize: 13, color: TV.text2, lineHeight: 1.5}}>
          Quiz generated at 06:00 UTC and is waiting on the Dashboard. Concepts above were chosen because they're your lowest-mastery this week.
        </div>
      )}

      <div style={{flex: 1}}/>

      <div style={{display: 'flex', gap: 8}}>
        <button className="tv-btn ghost" style={{fontSize: 13}}>← Edit notes</button>
        <div style={{flex: 1}}/>
        {e.score != null
          ? <button className="tv-btn" style={{fontSize: 13}}>Review questions →</button>
          : <button className="tv-btn primary" style={{fontSize: 13}}>Start quiz now →</button>}
      </div>
    </div>
  </>
);

Object.assign(window, {JournalHF});
