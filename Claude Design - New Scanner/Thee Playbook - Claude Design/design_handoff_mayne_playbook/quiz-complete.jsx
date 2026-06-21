// quiz-complete.jsx — Quiz completion / score screen (dark hi-fi)
// Shown after Q8 of a daily quiz. Score, mastery delta, per-Q recap,
// missed questions ready to drill into. Auto-saves as a journal entry.

const QuizCompleteHF = () => {
  const [openIdx, setOpenIdx] = React.useState(2); // Q3 expanded by default to show the pattern

  const score = 7;
  const total = 8;
  const verdict = score >= 7 ? 'STRONG' : score >= 5 ? 'FORMING' : 'WEAK';
  const vColor = verdict === 'STRONG' ? TV.ok : verdict === 'FORMING' ? TV.warn : TV.fail;
  const vBg    = verdict === 'STRONG' ? TV.okSoft : verdict === 'FORMING' ? TV.warnSoft : TV.failSoft;

  // mastery delta per concept (before → after)
  const masteryDelta = [
    {name: 'Order Block',     was: 38, now: 42, n: 3},
    {name: 'Fair Value Gap',  was: 44, now: 50, n: 3},
    {name: 'Liquidity Sweep', was: 61, now: 64, n: 2},
  ];

  // per-question recap
  const questions = [
    {n: 1, concept: 'Order Block', kind: 'identify pattern',
      q: 'Which candle marks the most recent bullish order block on this 4H chart?',
      correct: true, your: 'Candle 4 — last down-close before the impulse', right: null, time: '0:38'},
    {n: 2, concept: 'FVG', kind: 'true / false',
      q: 'A valid FVG requires that the wicks of candle 1 and candle 3 do not overlap.',
      correct: true, your: 'True', right: null, time: '0:18'},
    {n: 3, concept: 'FVG', kind: 'short answer',
      q: 'In ICT terms, what creates a bullish Fair Value Gap?',
      correct: false,
      your: 'A bullish FVG forms when there\'s a green candle with a big gap below it.',
      right: 'A 3-candle bullish displacement where the high of candle 1 sits below the low of candle 3 — leaving an inefficient delivery between them. Created by aggressive displacement, often after a liquidity sweep.',
      why: 'You described a gap, not a 3-candle imbalance. The defining property is the wick non-overlap, not "a gap."',
      time: '1:14'},
    {n: 4, concept: 'Order Block', kind: 'identify pattern',
      q: 'In an HTF bullish order block on the 4H, where is the optimal LTF entry?',
      correct: true, your: 'At the OB 50% (mean threshold)', right: null, time: '0:42'},
    {n: 5, concept: 'Liquidity Sweep', kind: 'multiple choice',
      q: 'After a clean sell-side sweep, what is the highest-conviction LTF entry trigger?',
      correct: true, your: 'A CHoCH on 5m followed by an FVG return', right: null, time: '0:52'},
    {n: 6, concept: 'Order Block', kind: 'true / false',
      q: 'An order block is invalidated when price closes through its origin level.',
      correct: true, your: 'True', right: null, time: '0:16'},
    {n: 7, concept: 'FVG', kind: 'identify pattern',
      q: 'Is the highlighted 3-candle move on this 5m chart a valid bullish FVG?',
      correct: true, your: 'Yes', right: null, time: '0:28'},
    {n: 8, concept: 'Liquidity Sweep', kind: 'short answer',
      q: 'Why does the size of the sweep wick matter less than the reclaim?',
      correct: true,
      your: 'The sweep itself is just liquidity acquisition. The signal is the reclaim — that\'s what shows the move was a stop-run, not a real break.',
      right: null,
      time: '1:04'},
  ];

  const correctCount = questions.filter(q => q.correct).length;
  const totalTime = '4m 32s';

  return (
    <div className="tv-frame" style={{display: 'flex', flexDirection: 'column'}}>
      <TVNav active="Quiz"/>
    <TTSubNav active="Quiz"/>

      <div style={{flex: 1, overflow: 'auto', minHeight: 0}}>
        {/* HEADER */}
        <div style={{padding: '18px 32px 14px', borderBottom: `1px solid ${TV.line}`,
            display: 'flex', alignItems: 'center', gap: 16}}>
          <div>
            <div className="tv-uppercase">Quiz #48 · complete</div>
            <div style={{fontSize: 22, fontWeight: 600, color: TV.text, marginTop: 4}}>
              Daily quiz · 2026-05-24
            </div>
          </div>
          <div style={{flex: 1}}/>
          <span className="tv-chip ok"><span className="tv-dot"/>saved to journal</span>
          <span style={{fontSize: 12, color: TV.text3}}>06:48 → 06:52 UTC</span>
        </div>

        {/* VERDICT BAND — mirrors validator 5C */}
        <div style={{padding: '24px 32px', display: 'flex', alignItems: 'center', gap: 28,
            borderBottom: `1px solid ${TV.line}`, background: TV.panel}}>
          <div style={{
            padding: '16px 22px', borderRadius: 10,
            border: `1.5px solid ${vColor}`, background: vBg,
            minWidth: 220,
          }}>
            <div className="tv-uppercase">Score</div>
            <div className="tv-num" style={{fontSize: 44, fontWeight: 700, color: vColor,
                letterSpacing: '-1px', lineHeight: 1, marginTop: 4}}>
              {score}<span style={{color: TV.text3, fontWeight: 500}}> / {total}</span>
            </div>
            <div style={{fontSize: 14, color: vColor, fontWeight: 600, marginTop: 6,
                letterSpacing: '.06em', textTransform: 'uppercase'}}>
              {verdict} · {Math.round((score / total) * 100)}%
            </div>
          </div>

          <div style={{flex: 1, minWidth: 0}}>
            <div className="tv-uppercase" style={{marginBottom: 6}}>Recap</div>
            <div style={{fontSize: 15, color: TV.text, lineHeight: 1.55}}>
              Solid run — 7 of 8 correct. The miss was on a <span style={{color: TV.accent, fontWeight: 500}}>Fair Value Gap</span> short
              answer where you described "a gap" instead of a 3-candle imbalance.
              Order Block answers have improved noticeably — you've now correctly identified the mean-threshold
              entry two quizzes in a row.
            </div>
          </div>

          {/* quick stats grid */}
          <div style={{display: 'grid', gridTemplateColumns: 'auto auto', gap: '8px 18px',
              padding: '14px 16px', borderRadius: 8,
              border: `1px solid ${TV.line}`, background: TV.panel2}}>
            <span style={{fontSize: 11, color: TV.text3, fontWeight: 600, letterSpacing: '.06em', textTransform: 'uppercase'}}>Time</span>
            <span className="tv-num" style={{fontSize: 14, color: TV.text, fontWeight: 600, textAlign: 'right'}}>{totalTime}</span>
            <span style={{fontSize: 11, color: TV.text3, fontWeight: 600, letterSpacing: '.06em', textTransform: 'uppercase'}}>Streak</span>
            <span className="tv-num" style={{fontSize: 14, color: TV.ok, fontWeight: 600, textAlign: 'right'}}>13 days ▲</span>
            <span style={{fontSize: 11, color: TV.text3, fontWeight: 600, letterSpacing: '.06em', textTransform: 'uppercase'}}>30d avg</span>
            <span className="tv-num" style={{fontSize: 14, color: TV.text, fontWeight: 600, textAlign: 'right'}}>72% → 74%</span>
            <span style={{fontSize: 11, color: TV.text3, fontWeight: 600, letterSpacing: '.06em', textTransform: 'uppercase'}}>Best run</span>
            <span className="tv-num" style={{fontSize: 14, color: TV.text2, textAlign: 'right'}}>5 · ep 14 prep</span>
          </div>
        </div>

        {/* MASTERY IMPACT */}
        <div style={{padding: '20px 32px'}}>
          <div style={{display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 12}}>
            <div style={{fontSize: 14, fontWeight: 600, color: TV.text, letterSpacing: '.02em', textTransform: 'uppercase'}}>Mastery impact</div>
            <div style={{fontSize: 12, color: TV.text3}}>how this quiz shifted your % correct per concept</div>
            <div style={{flex: 1, height: 1, background: TV.line}}/>
            <span style={{fontSize: 12, color: TV.text3}}>weighted across rolling 30 questions</span>
          </div>

          <div className="tv-card" style={{padding: 0, overflow: 'hidden'}}>
            {masteryDelta.map((m, i) => {
              const wasColor = m.was < 50 ? TV.fail : m.was < 70 ? TV.warn : TV.ok;
              const nowColor = m.now < 50 ? TV.fail : m.now < 70 ? TV.warn : TV.ok;
              const delta = m.now - m.was;
              return (
                <div key={m.name} style={{
                  display: 'grid', gridTemplateColumns: '180px 90px 1fr 90px 70px',
                  padding: '12px 18px', gap: 14, alignItems: 'center',
                  borderBottom: i < masteryDelta.length - 1 ? `1px solid ${TV.lineSoft}` : 'none',
                }}>
                  <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
                    <span style={{fontSize: 14, color: TV.text, fontWeight: 500}}>{m.name}</span>
                    <span style={{fontSize: 11, color: TV.text4}}>· {m.n} Qs</span>
                  </div>
                  <div className="tv-num" style={{fontSize: 13, color: wasColor, fontWeight: 600}}>
                    {m.was}%
                  </div>
                  <div style={{display: 'flex', alignItems: 'center', gap: 0, position: 'relative', height: 22}}>
                    {/* the before/after bar */}
                    <div style={{flex: 1, height: 6, background: TV.panel3, borderRadius: 3, overflow: 'hidden', position: 'relative'}}>
                      <div style={{position: 'absolute', left: 0, top: 0, height: '100%', width: `${m.was}%`, background: wasColor, opacity: 0.5}}/>
                      <div style={{position: 'absolute', left: 0, top: 0, height: '100%', width: `${m.now}%`, background: nowColor}}/>
                      <div style={{position: 'absolute', left: `${m.was}%`, top: -4, height: 14, width: 2, background: TV.text2}}/>
                    </div>
                  </div>
                  <div className="tv-num" style={{fontSize: 14, color: nowColor, fontWeight: 700}}>
                    {m.now}%
                  </div>
                  <div className="tv-num" style={{fontSize: 13, fontWeight: 700,
                      color: delta > 0 ? TV.ok : delta < 0 ? TV.fail : TV.text3, textAlign: 'right'}}>
                    {delta > 0 ? '▲ +' : delta < 0 ? '▼ -' : '·'}{Math.abs(delta)}
                  </div>
                </div>
              );
            })}
          </div>

          <div style={{fontSize: 12, color: TV.text2, marginTop: 10, lineHeight: 1.5,
              padding: '10px 14px', background: TV.panel2, borderRadius: 6,
              border: `1px solid ${TV.lineSoft}`,
              display: 'flex', alignItems: 'center', gap: 10}}>
            <span style={{color: TV.adapt, fontWeight: 600}}>↳ next quiz</span>
            <span>Tomorrow's questions will keep weighting Order Block & FVG until both clear 60%. One more solid quiz on FVG and the weighting will shift to BOS / CHoCH.</span>
          </div>
        </div>

        {/* PER-QUESTION RECAP */}
        <div style={{padding: '0 32px 24px'}}>
          <div style={{display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 12}}>
            <div style={{fontSize: 14, fontWeight: 600, color: TV.text, letterSpacing: '.02em', textTransform: 'uppercase'}}>Recap · all 8 questions</div>
            <div style={{fontSize: 12, color: TV.text3}}>click any row to expand</div>
            <div style={{flex: 1, height: 1, background: TV.line}}/>
            <span className="tv-chip ok"><span className="tv-dot"/>{correctCount} correct</span>
            <span className="tv-chip fail"><span className="tv-dot"/>{total - correctCount} missed</span>
          </div>

          <div className="tv-card" style={{padding: 0, overflow: 'hidden'}}>
            {questions.map((qq, i) => {
              const open = openIdx === i;
              const color = qq.correct ? TV.ok : TV.fail;
              return (
                <React.Fragment key={i}>
                  <div onClick={() => setOpenIdx(open ? null : i)} style={{
                    display: 'grid', gridTemplateColumns: '36px 80px 1fr 60px 28px',
                    padding: '12px 16px', gap: 14, alignItems: 'center',
                    cursor: 'pointer',
                    background: open ? TV.panel2 : 'transparent',
                    borderBottom: (i < questions.length - 1 && !open) ? `1px solid ${TV.lineSoft}` : 'none',
                  }}>
                    <div style={{
                      width: 26, height: 26, borderRadius: '50%',
                      background: qq.correct ? TV.okSoft : TV.failSoft,
                      border: `1px solid ${color}`,
                      color, fontWeight: 700, fontSize: 14,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>{qq.correct ? '✓' : '×'}</div>
                    <div>
                      <div style={{fontSize: 11, color: TV.text3, fontWeight: 600, letterSpacing: '.06em', textTransform: 'uppercase'}}>Q{qq.n}</div>
                      <div className="tv-num" style={{fontSize: 11, color: TV.text4}}>{qq.time}</div>
                    </div>
                    <div>
                      <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2}}>
                        <span className="tv-chip accent" style={{fontSize: 11, padding: '1px 7px'}}>{qq.concept}</span>
                        <span style={{fontSize: 11, color: TV.text3}}>{qq.kind}</span>
                      </div>
                      <div style={{fontSize: 14, color: TV.text, lineHeight: 1.4,
                          overflow: 'hidden', textOverflow: 'ellipsis',
                          whiteSpace: open ? 'normal' : 'nowrap'}}>
                        {qq.q}
                      </div>
                    </div>
                    <div style={{fontSize: 11, fontWeight: 700, color, letterSpacing: '.06em', textAlign: 'right'}}>
                      {qq.correct ? 'CORRECT' : 'MISSED'}
                    </div>
                    <div style={{color: TV.text3, fontSize: 14, transform: open ? 'rotate(90deg)' : 'rotate(0)',
                        transition: 'transform .15s'}}>›</div>
                  </div>

                  {open && (
                    <div style={{
                      padding: '4px 16px 16px 64px', background: TV.panel2,
                      borderBottom: i < questions.length - 1 ? `1px solid ${TV.lineSoft}` : 'none',
                      display: 'flex', flexDirection: 'column', gap: 10,
                    }}>
                      <div>
                        <div className="tv-uppercase" style={{marginBottom: 4}}>Question asked</div>
                        <div style={{fontSize: 14, color: TV.text, fontWeight: 500, lineHeight: 1.5}}>{qq.q}</div>
                      </div>

                      <div>
                        <div className="tv-uppercase" style={{marginBottom: 6}}>Your answer</div>
                        <div style={{
                          padding: '10px 12px', borderRadius: 6,
                          border: `1px solid ${color}`,
                          background: qq.correct ? TV.okSoft : TV.failSoft,
                          fontSize: 14, color: TV.text, lineHeight: 1.5,
                          display: 'flex', alignItems: 'flex-start', gap: 10,
                        }}>
                          <div style={{
                            width: 20, height: 20, borderRadius: 4,
                            background: color, color: '#0d1018',
                            fontSize: 11, fontWeight: 700, display: 'flex',
                            alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 1,
                          }}>{qq.correct ? '✓' : '×'}</div>
                          <div style={{flex: 1}}>{qq.your}</div>
                        </div>
                      </div>

                      {qq.right && (
                        <div>
                          <div className="tv-uppercase" style={{marginBottom: 6}}>Correct answer</div>
                          <div style={{
                            padding: '10px 12px', borderRadius: 6,
                            border: `1px solid ${TV.ok}`,
                            background: TV.okSoft,
                            fontSize: 14, color: TV.text, lineHeight: 1.5,
                          }}>{qq.right}</div>
                        </div>
                      )}

                      {qq.why && (
                        <div style={{padding: '8px 12px', borderRadius: 6,
                            background: TV.adaptSoft, border: `1px solid rgba(139,122,214,.3)`,
                            fontSize: 13, color: TV.text2, lineHeight: 1.55}}>
                          <span style={{color: TV.adapt, fontWeight: 600}}>↳ why I got it wrong · </span>{qq.why}
                        </div>
                      )}

                      <div style={{display: 'flex', gap: 12, fontSize: 12, color: TV.text3, marginTop: 4}}>
                        <span style={{cursor: 'pointer'}}>↗ jump to concept · {qq.concept}</span>
                        <span style={{cursor: 'pointer'}}>📖 source · ep. 14, 18, 22</span>
                        <span style={{cursor: 'pointer'}}>+ add note</span>
                      </div>
                    </div>
                  )}
                </React.Fragment>
              );
            })}
          </div>
        </div>

        {/* FOOTER */}
        <div style={{padding: '14px 32px', borderTop: `1px solid ${TV.line}`,
            display: 'flex', alignItems: 'center', gap: 12, background: TV.panel}}>
          <button className="tv-btn ghost">← Back to dashboard</button>
          <div style={{flex: 1}}/>
          <span style={{fontSize: 12, color: TV.text3}}>auto-saved · ⌘S to export</span>
          <button className="tv-btn">Review missed only</button>
          <button className="tv-btn">Practice these concepts →</button>
          <button className="tv-btn primary">Done</button>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, {QuizCompleteHF});
