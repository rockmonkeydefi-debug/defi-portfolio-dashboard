/* ===== QUIZ SCREEN ===== */

const { useState: useQS, useEffect: useQE, useMemo: useQM } = React;

function QuizScreen() {
  const [phase, setPhase] = useQS('loading');      // loading | empty | quiz | results
  const [questions, setQuestions] = useQS([]);     // ordered from /today/answers
  const [answersMap, setAnswersMap] = useQS({});   // { qid: full question object }
  const [shuffles, setShuffles] = useQS({});       // { qid: [opt, opt, opt, opt] }
  const [quizDate, setQuizDate] = useQS('');
  const [streak, setStreak] = useQS({});
  const [currentIdx, setCurrentIdx] = useQS(0);
  const [pending, setPending] = useQS({});         // { qid: selectedOptionString }
  const [submitted, setSubmitted] = useQS(new Set());
  const [generating, setGenerating] = useQS(false);
  const [error, setError] = useQS(null);
  const [reviewExpanded, setReviewExpanded] = useQS(null);

  async function load() {
    setError(null);
    try {
      // /today/answers returns answer_text for all questions even before submission
      const data = await api('/api/trading/quiz/today/answers');
      const qs = data.questions || [];
      setQuizDate(data.quiz_date || '');
      setStreak(data.streak || {});
      setQuestions(qs);

      const aMap = {};
      const sh = {};
      const subIds = new Set();
      qs.forEach(q => {
        aMap[q.id] = q;
        if (q.answer_text) {
          sh[q.id] = [q.answer_text, ...(q.distractors || [])].sort(() => Math.random() - 0.5);
        }
        if (q.user_answer != null) subIds.add(q.id);
      });
      setAnswersMap(aMap);
      setShuffles(prev => {
        // Preserve any already-shuffled order for questions in progress
        const merged = { ...sh };
        Object.keys(prev).forEach(k => { if (prev[k] && !subIds.has(parseInt(k))) merged[k] = prev[k]; });
        return merged;
      });
      setSubmitted(subIds);

      if (qs.length === 0) {
        setPhase('empty');
      } else if (subIds.size === qs.length) {
        setPhase('results');
      } else {
        const firstUnanswered = qs.findIndex(q => q.user_answer == null);
        setCurrentIdx(firstUnanswered >= 0 ? firstUnanswered : 0);
        setPhase('quiz');
      }
    } catch (_e) {
      // 404 or any error = no quiz today
      setPhase('empty');
    }
  }

  useQE(() => { load(); }, []);

  // Keyboard shortcuts — active only during quiz phase
  useQE(() => {
    if (phase !== 'quiz') return;
    const q = questions[currentIdx];
    if (!q) return;
    const opts = shuffles[q.id] || [];
    const isSubmitted = submitted.has(q.id);
    const isLast = currentIdx === questions.length - 1;

    function onKey(e) {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
      if (!isSubmitted && ['1', '2', '3', '4'].includes(e.key)) {
        const opt = opts[parseInt(e.key) - 1];
        if (opt) setPending(p => ({ ...p, [q.id]: opt }));
      }
      if (e.key === 'Enter' && !isSubmitted) {
        setPending(p => { if (p[q.id]) confirmAnswer(q.id, p[q.id]); return p; });
      }
      if (e.key === 'ArrowRight' && isSubmitted) {
        if (!isLast) setCurrentIdx(i => i + 1);
        else setPhase('results');
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [phase, currentIdx, questions, shuffles, submitted]);

  async function confirmAnswer(qid, answer) {
    try {
      await api('/api/trading/quiz/submit', {
        method: 'POST',
        body: JSON.stringify({ answers: [{ question_id: qid, user_answer: answer }] }),
      });
      const data = await api('/api/trading/quiz/today/answers');
      const qs = data.questions || [];
      setStreak(data.streak || {});
      const aMap = {};
      const subIds = new Set();
      qs.forEach(q => { aMap[q.id] = q; if (q.user_answer != null) subIds.add(q.id); });
      setAnswersMap(aMap);
      setSubmitted(subIds);
    } catch (e) {
      setError(e.message);
    }
  }

  async function generateQuiz() {
    setGenerating(true);
    setError(null);
    try {
      await api('/api/trading/quiz/generate', { method: 'POST', body: '{}' });
    } catch (e) {
      if (!e.message.includes('already') && !e.message.includes('409')) setError(e.message);
    }
    setSubmitted(new Set());
    setShuffles({});
    setPending({});
    await load();
    setGenerating(false);
  }

  // ── LOADING ──
  if (phase === 'loading') {
    return React.createElement('div', { className: 'tv-label', style: { padding: 32 } }, 'Loading…');
  }

  // ── EMPTY ──
  if (phase === 'empty') {
    return React.createElement('div', {
      style: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 320, gap: 12 }
    },
      error && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13, marginBottom: 4 } }, error),
      React.createElement('div', { style: { fontSize: 32 } }, '📚'),
      React.createElement('div', { style: { fontSize: 17, fontWeight: 600 } }, 'No quiz today yet.'),
      React.createElement('div', { style: { fontSize: 13, color: 'var(--text4)', marginBottom: 8 } }, "Generate today's quiz from your concepts library."),
      React.createElement('button', {
        className: 'tv-btn primary',
        disabled: generating,
        onClick: generateQuiz,
        style: { fontSize: 14, padding: '8px 24px' },
      }, generating ? 'Generating questions…' : '⚡ Generate Quiz')
    );
  }

  // ── RESULTS ──
  if (phase === 'results') {
    const total = questions.length;
    const correct = questions.filter(q => (answersMap[q.id] || {}).is_correct).length;
    const pct = total > 0 ? Math.round((correct / total) * 100) : 0;
    const scoreColor = pct >= 80 ? 'var(--ok)' : pct >= 50 ? 'var(--warn)' : 'var(--fail)';

    return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 14, padding: '16px 0', maxWidth: 680 } },
      // Score hero
      React.createElement('div', { className: 'tv-card', style: { textAlign: 'center', padding: '28px 24px' } },
        React.createElement('div', { style: { fontSize: 52, fontWeight: 700, color: scoreColor, lineHeight: 1 } }, `${pct}%`),
        React.createElement('div', { style: { fontSize: 16, color: 'var(--text3)', marginTop: 6 } }, `${correct} / ${total} correct`),
        React.createElement('div', { style: { width: '60%', height: 6, background: 'var(--line)', borderRadius: 3, margin: '14px auto 0' } },
          React.createElement('div', { style: { width: `${pct}%`, height: '100%', background: scoreColor, borderRadius: 3 } })
        )
      ),
      // Streak card
      React.createElement('div', { className: 'tv-card', style: { display: 'flex', gap: 28, alignItems: 'center', padding: '12px 16px', flexWrap: 'wrap' } },
        React.createElement('div', null,
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 2 } }, 'Current Streak'),
          React.createElement('div', { style: { fontSize: 18, fontWeight: 700 } }, `🔥 ${streak.current_streak || 0} days`)
        ),
        React.createElement('div', null,
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 2 } }, 'Best'),
          React.createElement('div', { style: { fontSize: 15, fontWeight: 600 } }, `${streak.longest_streak || 0} days`)
        ),
        React.createElement('div', { style: { marginLeft: 'auto' } },
          React.createElement('button', {
            className: 'tv-btn',
            onClick: generateQuiz,
            disabled: generating,
            style: { fontSize: 12 },
          }, generating ? 'Generating…' : '↺ New Quiz')
        )
      ),
      // Question review list
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
        questions.map(q => {
          const qd = answersMap[q.id] || {};
          const isCorrect = qd.is_correct;
          const isExp = reviewExpanded === q.id;
          const opts = shuffles[q.id] || [qd.answer_text, ...(qd.distractors || [])];
          return React.createElement('div', {
            key: q.id,
            className: 'tv-card',
            style: { cursor: 'pointer', padding: '10px 14px' },
            onClick: () => setReviewExpanded(isExp ? null : q.id),
          },
            React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 10 } },
              React.createElement('span', {
                style: { fontSize: 15, color: isCorrect ? 'var(--ok)' : 'var(--fail)', flexShrink: 0, width: 16 }
              }, isCorrect ? '✓' : '✗'),
              React.createElement('div', { style: { flex: 1, minWidth: 0 } },
                qd.concept_title && React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', marginBottom: 1 } }, qd.concept_title),
                React.createElement('div', {
                  style: { fontSize: 13, color: 'var(--text2)', overflow: 'hidden', textOverflow: isExp ? 'unset' : 'ellipsis', whiteSpace: isExp ? 'normal' : 'nowrap' }
                }, q.question_text)
              ),
              React.createElement('span', { style: { color: 'var(--text4)', fontSize: 11, flexShrink: 0 } }, isExp ? '▲' : '▼')
            ),
            isExp && React.createElement('div', { style: { marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--line)' } },
              React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 5, marginBottom: 10 } },
                opts.map((opt, i) => {
                  const isCor = opt === qd.answer_text;
                  const isWrong = opt === qd.user_answer && !isCorrect;
                  return React.createElement('div', {
                    key: i,
                    style: {
                      padding: '6px 12px', borderRadius: 4, fontSize: 12,
                      background: isCor ? 'var(--ok-soft)' : isWrong ? 'var(--fail-soft)' : 'var(--panel2)',
                      border: `1px solid ${isCor ? 'var(--ok)' : isWrong ? 'var(--fail)' : 'var(--line)'}`,
                      opacity: !isCor && !isWrong ? 0.55 : 1,
                    }
                  }, opt);
                })
              ),
              qd.concept_summary && React.createElement('div', {
                style: { fontSize: 12, color: 'var(--text3)', fontStyle: 'italic', padding: '8px 10px', background: 'var(--panel)', borderRadius: 4, borderLeft: '2px solid var(--accent)', lineHeight: 1.5 }
              }, qd.concept_summary)
            )
          );
        })
      ),
      React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', textAlign: 'center', padding: '4px 0' } },
        'One quiz per day — come back tomorrow!')
    );
  }

  // ── QUIZ PHASE ──
  const q = questions[currentIdx];
  if (!q) return null;
  const opts = shuffles[q.id] || [];
  const qd = answersMap[q.id] || {};
  const isSubmitted = submitted.has(q.id);
  const selectedOpt = pending[q.id];
  const isLast = currentIdx === questions.length - 1;

  return React.createElement('div', { style: { display: 'flex', gap: 20, padding: '16px 0', alignItems: 'flex-start' } },

    // LEFT RAIL
    React.createElement('div', { style: { width: 176, flexShrink: 0 } },
      React.createElement('div', { className: 'tv-card', style: { padding: '14px 12px', display: 'flex', flexDirection: 'column', gap: 14 } },
        React.createElement('div', null,
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 3 } }, 'Daily Quiz'),
          quizDate && React.createElement('div', { style: { fontSize: 12, color: 'var(--text3)' } }, quizDate)
        ),
        // Progress dots
        React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 7 } },
          questions.map((tq, i) => {
            const tqd = answersMap[tq.id] || {};
            const isDone = submitted.has(tq.id);
            const isCur = i === currentIdx;
            let bg = 'transparent';
            let border = '2px solid rgba(255,255,255,0.2)';
            let shadow = 'none';
            if (isDone && tqd.is_correct)       { bg = 'var(--ok)';   border = '2px solid var(--ok)'; }
            else if (isDone && !tqd.is_correct) { bg = 'var(--fail)'; border = '2px solid var(--fail)'; }
            else if (isCur)                     { border = '2px solid var(--accent)'; shadow = '0 0 0 3px var(--accent-soft)'; }
            return React.createElement('div', {
              key: tq.id,
              title: `Q${i + 1}`,
              onClick: () => setCurrentIdx(i),
              style: {
                width: 18, height: 18, borderRadius: '50%',
                background: bg, border, boxShadow: shadow,
                cursor: 'pointer', transition: 'all 0.12s',
              }
            });
          })
        ),
        React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)' } },
          `🔥 ${streak.current_streak || 0} day streak`)
      )
    ),

    // MAIN AREA
    React.createElement('div', { style: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 } },
      error && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13 } }, error),
      React.createElement('div', { className: 'tv-card', style: { display: 'flex', flexDirection: 'column', gap: 16 } },
        // Header
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
          React.createElement('span', { style: { fontSize: 12, color: 'var(--text4)' } },
            `Question ${currentIdx + 1} of ${questions.length}`),
          q.concept_title && React.createElement('span', { className: 'tv-chip adapt' }, q.concept_title)
        ),
        // Question text
        React.createElement('div', { style: { fontSize: 16, fontWeight: 500, lineHeight: 1.6, color: 'var(--text)' } },
          q.question_text),
        // Options 2×2
        React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 } },
          opts.map((opt, i) => {
            const isCor = opt === qd.answer_text;
            const isUserWrong = qd.user_answer === opt && !qd.is_correct;
            const isSel = selectedOpt === opt;
            let bg = 'var(--panel2)';
            let border = '1px solid var(--line)';
            let opacity = 1;
            if (isSubmitted) {
              if (isCor)            { bg = 'var(--ok-soft)';   border = '1px solid var(--ok)'; }
              else if (isUserWrong) { bg = 'var(--fail-soft)'; border = '1px solid var(--fail)'; }
              else                  { opacity = 0.4; }
            } else if (isSel) {
              bg = 'var(--accent-soft)'; border = '1px solid var(--accent)';
            }
            return React.createElement('div', {
              key: i,
              onClick: () => !isSubmitted && setPending(p => ({ ...p, [q.id]: opt })),
              style: {
                background: bg, border, borderRadius: 6, padding: '10px 14px',
                fontSize: 13, lineHeight: 1.4, cursor: isSubmitted ? 'default' : 'pointer',
                opacity, display: 'flex', gap: 8, alignItems: 'flex-start', transition: 'border 0.1s, background 0.1s',
              }
            },
              React.createElement('span', {
                style: {
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  minWidth: 20, height: 20, borderRadius: '50%', fontSize: 10, flexShrink: 0,
                  background: isSel && !isSubmitted ? 'var(--accent)' : 'var(--panel3)',
                  color: isSel && !isSubmitted ? '#000' : 'var(--text4)',
                  fontWeight: 600, marginTop: 1,
                }
              }, i + 1),
              opt
            );
          })
        ),
        // Post-submit explanation
        isSubmitted && qd.concept_summary && React.createElement('div', {
          style: { fontSize: 13, color: 'var(--text3)', background: 'var(--panel)', padding: '10px 14px', borderRadius: 6, borderLeft: '3px solid var(--accent)', lineHeight: 1.5 }
        }, qd.concept_summary),
        // Action row
        React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' } },
          !isSubmitted && currentIdx > 0 && React.createElement('button', {
            className: 'tv-btn', onClick: () => setCurrentIdx(i => i - 1), style: { fontSize: 13 },
          }, '← Back'),
          !isSubmitted && React.createElement('button', {
            className: 'tv-btn primary',
            disabled: !selectedOpt,
            onClick: () => selectedOpt && confirmAnswer(q.id, selectedOpt),
            style: { fontSize: 13 },
          }, 'Confirm ↵'),
          isSubmitted && !isLast && React.createElement('button', {
            className: 'tv-btn primary', onClick: () => setCurrentIdx(i => i + 1), style: { fontSize: 13 },
          }, 'Next →'),
          isSubmitted && isLast && React.createElement('button', {
            className: 'tv-btn primary', onClick: () => setPhase('results'), style: { fontSize: 13 },
          }, 'See Results →'),
          React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)' } },
            isSubmitted ? '→ to advance' : '1–4 select · Enter confirm')
        )
      )
    )
  );
}

window.QuizScreen = QuizScreen;
