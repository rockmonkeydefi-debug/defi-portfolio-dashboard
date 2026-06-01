/* ===== TRADING TOOLS ===== */

const { useState: useTdS, useEffect: useTdE, useCallback: useTdCb, useMemo: useTdMemo } = React;

const SIGNAL_LABELS = {
  rsi_oversold:    { label: 'RSI Oversold',    cls: 'ok'   },
  rsi_overbought:  { label: 'RSI Overbought',  cls: 'fail' },
  ema20_cross_up:  { label: 'EMA20 Cross ↑',   cls: 'ok'   },
  ema20_cross_down:{ label: 'EMA20 Cross ↓',   cls: 'fail' },
  macd_bullish:    { label: 'MACD Bullish',     cls: 'ok'   },
  macd_bearish:    { label: 'MACD Bearish',     cls: 'fail' },
  bb_lower_touch:  { label: 'BB Lower Touch',   cls: 'warn' },
  bb_upper_touch:  { label: 'BB Upper Touch',   cls: 'warn' },
};

const CONCEPT_CATS = [
  'entry_signals','risk_management','position_sizing','market_regimes',
  'lp_strategy','defi_strategy','technical_analysis','macro_context','mindset',
];

const MOOD_LABELS = ['','😞','😕','😐','🙂','😊'];

function TdPlaceholder({ label }) {
  return React.createElement('div', {
    style: { display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center',
             minHeight:320, gap:12, color:'var(--text4)' }
  },
    React.createElement('div', { style:{ fontSize:32 } }, '🚧'),
    React.createElement('div', { className:'tv-label' }, label),
    React.createElement('div', { style:{ fontSize:13 } }, 'Coming in next phase')
  );
}

/* ===== SCANNER ===== */
function ScannerScreen() {
  const [watchlist, setWatchlist] = useTdS([]);
  const [signals, setSignals] = useTdS([]);
  const [running, setRunning] = useTdS(false);
  const [loading, setLoading] = useTdS(true);
  const [newSymbol, setNewSymbol] = useTdS('');
  const [newInterval, setNewInterval] = useTdS('4h');
  const [error, setError] = useTdS(null);

  function load() {
    Promise.all([
      api('/api/trading/scanner/watchlist'),
      api('/api/trading/scanner/signals?limit=50'),
    ]).then(([wl, sig]) => {
      setWatchlist(wl.watchlist || []);
      setSignals(sig.signals || []);
      setLoading(false);
    }).catch(e => { setError(e.message); setLoading(false); });
  }

  useTdE(() => { load(); }, []);

  function normalizeSymbol(raw) {
    const s = raw.trim().toUpperCase();
    const QUOTE_SUFFIXES = ['USDT', 'USDC', 'BTC', 'ETH'];
    if (QUOTE_SUFFIXES.some(q => s.endsWith(q))) return s;
    return s + 'USDT';
  }

  function addSymbol() {
    const sym = normalizeSymbol(newSymbol);
    if (!sym) return;
    api('/api/trading/scanner/watchlist', {
      method: 'POST',
      body: JSON.stringify({ symbol: sym, interval: newInterval }),
    }).then(() => { setNewSymbol(''); load(); }).catch(e => setError(e.message));
  }

  function removeSymbol(id) {
    api(`/api/trading/scanner/watchlist/${id}`, { method: 'DELETE' })
      .then(() => load()).catch(e => setError(e.message));
  }

  async function runScan() {
    setRunning(true);
    setError(null);
    try {
      const r = await api('/api/trading/scanner/run', { method: 'POST', body: '{}' });
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  }

  if (loading) return React.createElement('div', { className:'tv-label', style:{padding:32} }, 'Loading…');

  return React.createElement('div', { style:{ display:'flex', flexDirection:'column', gap:16, padding:'16px 0' } },
    error && React.createElement('div', { style:{ color:'var(--fail)', fontSize:13, padding:'0 4px' } }, error),

    /* Watchlist + add */
    React.createElement('div', { className:'tv-card' },
      React.createElement('div', { style:{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12 } },
        React.createElement('div', { className:'tv-label' }, `Watchlist (${watchlist.length})`),
        React.createElement('button', {
          className: running ? 'tv-btn' : 'tv-btn primary',
          disabled: running || watchlist.length === 0,
          onClick: runScan,
        }, running ? 'Scanning…' : '▶ Run Scan')
      ),
      React.createElement('div', { style:{ display:'flex', gap:8, marginBottom:12 } },
        React.createElement('input', {
          className:'tv-input', placeholder:'BTC or ETHUSDT', value:newSymbol,
          style:{ flex:1 },
          onChange: e => setNewSymbol(e.target.value),
          onKeyDown: e => e.key === 'Enter' && addSymbol(),
        }),
        React.createElement('select', {
          className:'tv-input', value:newInterval, style:{ width:80 },
          onChange: e => setNewInterval(e.target.value),
        }, ['15m','1h','4h','1d'].map(v => React.createElement('option', { key:v, value:v }, v))),
        React.createElement('button', { className:'tv-btn primary', onClick:addSymbol }, '+ Add')
      ),
      watchlist.length === 0
        ? React.createElement('div', { style:{ color:'var(--text4)', fontSize:13 } }, 'No symbols in watchlist')
        : React.createElement('div', { style:{ display:'flex', flexWrap:'wrap', gap:6 } },
            watchlist.map(item =>
              React.createElement('div', {
                key: item.id,
                style:{ display:'flex', alignItems:'center', gap:4, background:'var(--panel2)',
                        borderRadius:4, padding:'3px 8px', fontSize:13 }
              },
                React.createElement('span', null, item.symbol),
                React.createElement('span', { style:{color:'var(--text4)'} }, item.interval),
                React.createElement('button', {
                  onClick: () => removeSymbol(item.id),
                  style:{ background:'none', border:'none', color:'var(--text4)', cursor:'pointer',
                          fontSize:12, padding:'0 2px', marginLeft:2 }
                }, '×')
              )
            )
          )
    ),

    /* Signals table */
    React.createElement('div', { className:'tv-card' },
      React.createElement('div', { className:'tv-label', style:{marginBottom:12} }, `Recent Signals (${signals.length})`),
      signals.length === 0
        ? React.createElement('div', { style:{color:'var(--text4)', fontSize:13} }, 'No signals yet. Run a scan.')
        : React.createElement('table', { className:'tv-table', style:{width:'100%'} },
            React.createElement('thead', null,
              React.createElement('tr', null,
                ['Symbol','Interval','Signal','Price','Detected'].map(h =>
                  React.createElement('th', { key:h }, h)
                )
              )
            ),
            React.createElement('tbody', null,
              signals.map(s => {
                const meta = SIGNAL_LABELS[s.signal_type] || { label: s.signal_type, cls: 'adapt' };
                return React.createElement('tr', { key:s.id },
                  React.createElement('td', null, React.createElement('strong', null, s.symbol)),
                  React.createElement('td', null, s.interval),
                  React.createElement('td', null,
                    React.createElement('span', { className:`tv-chip ${meta.cls}` }, meta.label)
                  ),
                  React.createElement('td', { className:'tv-num' }, s.price ? fmt(s.price, 4) : '—'),
                  React.createElement('td', { style:{color:'var(--text4)', fontSize:12} },
                    s.detected_at ? s.detected_at.slice(0, 16).replace('T',' ') : '—'
                  )
                );
              })
            )
          )
    )
  );
}

/* ===== CONCEPTS ===== */
function ConceptsScreen() {
  const [concepts, setConcepts] = useTdS([]);
  const [loading, setLoading] = useTdS(true);
  const [extracting, setExtracting] = useTdS(false);
  const [catFilter, setCatFilter] = useTdS('');
  const [expanded, setExpanded] = useTdS(null);
  const [error, setError] = useTdS(null);
  const [extractMsg, setExtractMsg] = useTdS(null);

  function load() {
    const url = catFilter ? `/api/trading/concepts?category=${catFilter}` : '/api/trading/concepts';
    api(url).then(r => { setConcepts(r.concepts || []); setLoading(false); })
            .catch(e => { setError(e.message); setLoading(false); });
  }

  useTdE(() => { load(); }, [catFilter]);

  async function extractConcepts() {
    setExtracting(true);
    setExtractMsg(null);
    setError(null);
    try {
      const r = await api('/api/trading/extract-concepts', { method:'POST', body:'{}' });
      setExtractMsg(`Extracted ${r.extracted} concepts from ${r.docs_processed} documents.`);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setExtracting(false);
    }
  }

  const displayed = useTdMemo(() => concepts, [concepts]);

  if (loading) return React.createElement('div', { className:'tv-label', style:{padding:32} }, 'Loading…');

  return React.createElement('div', { style:{ display:'flex', flexDirection:'column', gap:16, padding:'16px 0' } },
    error && React.createElement('div', { style:{ color:'var(--fail)', fontSize:13 } }, error),
    extractMsg && React.createElement('div', { style:{ color:'var(--ok)', fontSize:13 } }, extractMsg),

    React.createElement('div', { style:{ display:'flex', justifyContent:'space-between', alignItems:'center' } },
      React.createElement('div', { style:{ display:'flex', gap:8, flexWrap:'wrap' } },
        React.createElement('button', {
          className: catFilter === '' ? 'tv-chip adapt' : 'tv-chip',
          onClick: () => setCatFilter(''),
        }, `All (${concepts.length})`),
        CONCEPT_CATS.map(cat => {
          const count = concepts.filter(c => c.category === cat).length;
          if (count === 0) return null;
          return React.createElement('button', {
            key: cat,
            className: catFilter === cat ? 'tv-chip adapt' : 'tv-chip',
            onClick: () => setCatFilter(catFilter === cat ? '' : cat),
          }, `${cat.replace(/_/g,' ')} (${count})`);
        })
      ),
      React.createElement('button', {
        className: extracting ? 'tv-btn' : 'tv-btn primary',
        disabled: extracting,
        onClick: extractConcepts,
        style:{ whiteSpace:'nowrap' },
      }, extracting ? 'Extracting…' : '⚡ Extract from Docs')
    ),

    concepts.length === 0
      ? React.createElement('div', { className:'tv-card', style:{textAlign:'center', color:'var(--text4)', padding:32} },
          'No concepts yet. Upload strategy docs in Settings, then click Extract.')
      : React.createElement('div', { style:{ display:'flex', flexDirection:'column', gap:8 } },
          displayed.map(c =>
            React.createElement('div', {
              key: c.id,
              className: 'tv-card',
              style:{ cursor:'pointer' },
              onClick: () => setExpanded(expanded === c.id ? null : c.id),
            },
              React.createElement('div', { style:{ display:'flex', justifyContent:'space-between', alignItems:'flex-start' } },
                React.createElement('div', null,
                  React.createElement('div', { style:{ fontWeight:600, fontSize:14, marginBottom:4 } }, c.title),
                  React.createElement('div', { style:{ fontSize:12, color:'var(--text3)' } }, c.summary)
                ),
                React.createElement('div', { style:{ display:'flex', gap:6, alignItems:'center', flexShrink:0, marginLeft:12 } },
                  c.category && React.createElement('span', { className:'tv-chip' }, c.category.replace(/_/g,' ')),
                  React.createElement('span', { style:{ color:'var(--text4)', fontSize:12 } }, expanded === c.id ? '▲' : '▼')
                )
              ),
              expanded === c.id && React.createElement('div', { style:{ marginTop:12, paddingTop:12, borderTop:'1px solid var(--line)' } },
                c.source_doc && React.createElement('div', { style:{ fontSize:12, color:'var(--text4)', marginBottom:6 } }, `Source: ${c.source_doc}`),
                c.tags && c.tags.length > 0 && React.createElement('div', { style:{ display:'flex', gap:4, flexWrap:'wrap' } },
                  c.tags.map((t, i) => React.createElement('span', { key:i, className:'tv-chip' }, t))
                )
              )
            )
          )
        )
  );
}

/* ===== QUIZ ===== */
function QuizScreen() {
  const [quiz, setQuiz] = useTdS(null);
  const [loading, setLoading] = useTdS(true);
  const [generating, setGenerating] = useTdS(false);
  const [submitting, setSubmitting] = useTdS(false);
  const [submitted, setSubmitted] = useTdS(false);
  const [answers, setAnswers] = useTdS({});
  const [result, setResult] = useTdS(null);
  const [shuffles, setShuffles] = useTdS({});
  const [error, setError] = useTdS(null);

  function loadToday() {
    api('/api/trading/quiz/today/answers')
      .then(r => {
        setQuiz(r);
        // Rebuild shuffled options from stored data
        const sh = {};
        for (const q of (r.questions || [])) {
          if (!shuffles[q.id]) {
            const opts = [q.answer_text, ...q.distractors].sort(() => Math.random() - 0.5);
            sh[q.id] = opts;
          }
        }
        if (Object.keys(sh).length > 0) setShuffles(prev => ({ ...prev, ...sh }));
        if (r.total_attempted === (r.questions || []).length && r.total_attempted > 0) setSubmitted(true);
        setLoading(false);
      })
      .catch(() => {
        // No quiz today
        setQuiz(null);
        setLoading(false);
      });
  }

  useTdE(() => { loadToday(); }, []);

  async function generateQuiz() {
    setGenerating(true);
    setError(null);
    try {
      await api('/api/trading/quiz/generate', { method:'POST', body:'{}' });
      setSubmitted(false);
      setAnswers({});
      setShuffles({});
      loadToday();
    } catch (e) {
      setError(e.message);
    } finally {
      setGenerating(false);
    }
  }

  async function submitAnswers() {
    setSubmitting(true);
    try {
      const payload = Object.entries(answers).map(([qid, ans]) => ({
        question_id: parseInt(qid), user_answer: ans,
      }));
      const r = await api('/api/trading/quiz/submit', {
        method:'POST', body: JSON.stringify({ answers: payload }),
      });
      setResult(r);
      setSubmitted(true);
      loadToday();
    } catch (e) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return React.createElement('div', { className:'tv-label', style:{padding:32} }, 'Loading…');

  const questions = quiz?.questions || [];
  const streak = quiz?.streak || {};
  const allAnswered = questions.length > 0 && Object.keys(answers).length === questions.length;

  return React.createElement('div', { style:{ display:'flex', flexDirection:'column', gap:16, padding:'16px 0' } },
    error && React.createElement('div', { style:{ color:'var(--fail)', fontSize:13 } }, error),

    /* Streak bar */
    React.createElement('div', { className:'tv-card', style:{ display:'flex', gap:24, alignItems:'center' } },
      React.createElement('div', null,
        React.createElement('div', { style:{color:'var(--text4)', fontSize:11, textTransform:'uppercase', marginBottom:2} }, 'Streak'),
        React.createElement('div', { className:'tv-num', style:{fontSize:20} }, `🔥 ${streak.current_streak || 0}`)
      ),
      React.createElement('div', null,
        React.createElement('div', { style:{color:'var(--text4)', fontSize:11, textTransform:'uppercase', marginBottom:2} }, 'Best'),
        React.createElement('div', { className:'tv-num' }, streak.longest_streak || 0)
      ),
      React.createElement('div', null,
        React.createElement('div', { style:{color:'var(--text4)', fontSize:11, textTransform:'uppercase', marginBottom:2} }, 'All-time'),
        React.createElement('div', { className:'tv-num' }, `${streak.total_correct || 0}/${streak.total_attempted || 0}`)
      ),
      React.createElement('div', { style:{marginLeft:'auto'} },
        React.createElement('button', {
          className: generating ? 'tv-btn' : 'tv-btn primary',
          disabled: generating,
          onClick: generateQuiz,
        }, generating ? 'Generating…' : quiz ? '↺ New Quiz' : '⚡ Generate Quiz')
      )
    ),

    /* Result banner */
    submitted && result && React.createElement('div', {
      className:'tv-card',
      style:{ background: result.score_pct >= 70 ? 'var(--ok-soft)' : 'var(--fail-soft)', textAlign:'center' }
    },
      React.createElement('div', { style:{fontSize:22, fontWeight:700} }, `${result.score_pct}%`),
      React.createElement('div', { style:{color:'var(--text3)', fontSize:13} },
        `${result.correct} / ${result.submitted} correct`
      )
    ),

    /* No quiz */
    !quiz && React.createElement('div', { className:'tv-card', style:{textAlign:'center', color:'var(--text4)', padding:32} },
      'No quiz for today. Generate one to start.'
    ),

    /* Questions */
    questions.map((q, idx) => {
      const opts = shuffles[q.id] || [q.answer_text, ...q.distractors];
      const selected = answers[q.id];
      const showResult = submitted;
      return React.createElement('div', { key:q.id, className:'tv-card' },
        React.createElement('div', { style:{marginBottom:8} },
          React.createElement('div', { style:{color:'var(--text4)', fontSize:11, marginBottom:4} }, `Q${idx+1} · ${q.concept_title || ''}`),
          React.createElement('div', { style:{fontWeight:600, fontSize:14} }, q.question_text)
        ),
        React.createElement('div', { style:{display:'flex', flexDirection:'column', gap:6} },
          opts.map((opt, i) => {
            const isSelected = selected === opt;
            const isCorrect = opt === q.answer_text;
            let bg = 'var(--panel2)';
            let border = '1px solid var(--line)';
            if (showResult && isSelected && isCorrect) { bg = 'var(--ok-soft)'; border = '1px solid var(--ok)'; }
            else if (showResult && isSelected && !isCorrect) { bg = 'var(--fail-soft)'; border = '1px solid var(--fail)'; }
            else if (showResult && !isSelected && isCorrect) { bg = 'var(--ok-soft)'; border = '1px solid var(--ok)'; }
            else if (!showResult && isSelected) { border = '1px solid var(--accent)'; bg = 'var(--panel3)'; }
            return React.createElement('div', {
              key: i,
              onClick: () => !submitted && setAnswers(prev => ({ ...prev, [q.id]: opt })),
              style:{ background:bg, border, borderRadius:4, padding:'8px 12px', fontSize:13,
                      cursor: submitted ? 'default' : 'pointer', lineHeight:1.4 }
            }, opt);
          })
        )
      );
    }),

    questions.length > 0 && !submitted &&
      React.createElement('button', {
        className: allAnswered ? 'tv-btn primary' : 'tv-btn',
        disabled: !allAnswered || submitting,
        onClick: submitAnswers,
        style:{ alignSelf:'flex-start' },
      }, submitting ? 'Submitting…' : 'Submit Answers')
  );
}

/* ===== JOURNAL ===== */
function JournalScreen() {
  const [entries, setEntries] = useTdS([]);
  const [total, setTotal] = useTdS(0);
  const [loading, setLoading] = useTdS(true);
  const [showForm, setShowForm] = useTdS(false);
  const [editId, setEditId] = useTdS(null);
  const [expanded, setExpanded] = useTdS(null);
  const [form, setForm] = useTdS({ title:'', body:'', mood:3, market_regime:'', entry_date:'', tags:'' });
  const [saving, setSaving] = useTdS(false);
  const [error, setError] = useTdS(null);

  function load() {
    api('/api/trading/journal?limit=20')
      .then(r => { setEntries(r.entries || []); setTotal(r.total || 0); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }

  useTdE(() => { load(); }, []);

  function openNewForm() {
    const today = new Date().toISOString().slice(0, 10);
    setForm({ title:'', body:'', mood:3, market_regime:'', entry_date:today, tags:'' });
    setEditId(null);
    setShowForm(true);
  }

  function openEditForm(e) {
    setForm({
      title: e.title, body: e.body || '', mood: e.mood || 3,
      market_regime: e.market_regime || '', entry_date: e.entry_date,
      tags: (e.tags || []).join(', '),
    });
    setEditId(e.id);
    setShowForm(true);
    setExpanded(null);
  }

  async function saveEntry() {
    if (!form.title.trim()) return;
    setSaving(true);
    try {
      const payload = {
        ...form,
        mood: parseInt(form.mood),
        tags: form.tags.split(',').map(t => t.trim()).filter(Boolean),
      };
      if (editId) {
        await api(`/api/trading/journal/${editId}`, { method:'PUT', body: JSON.stringify(payload) });
      } else {
        await api('/api/trading/journal', { method:'POST', body: JSON.stringify(payload) });
      }
      setShowForm(false);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function deleteEntry(id) {
    if (!confirm('Delete this journal entry?')) return;
    try {
      await api(`/api/trading/journal/${id}`, { method:'DELETE' });
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  if (loading) return React.createElement('div', { className:'tv-label', style:{padding:32} }, 'Loading…');

  const REGIMES = ['', 'bull', 'bear', 'sideways', 'unknown'];

  return React.createElement('div', { style:{ display:'flex', flexDirection:'column', gap:16, padding:'16px 0' } },
    error && React.createElement('div', { style:{ color:'var(--fail)', fontSize:13 } }, error),

    /* Header */
    React.createElement('div', { style:{ display:'flex', justifyContent:'space-between', alignItems:'center' } },
      React.createElement('div', { className:'tv-label' }, `Journal (${total} entries)`),
      React.createElement('button', { className:'tv-btn primary', onClick: openNewForm }, '+ New Entry')
    ),

    /* Form */
    showForm && React.createElement('div', { className:'tv-card', style:{ display:'flex', flexDirection:'column', gap:10 } },
      React.createElement('div', { className:'tv-label', style:{marginBottom:4} }, editId ? 'Edit Entry' : 'New Entry'),
      React.createElement('div', { style:{display:'flex', gap:8} },
        React.createElement('input', {
          className:'tv-input', placeholder:'Date', type:'date',
          value: form.entry_date, style:{width:140},
          onChange: e => setForm(p => ({...p, entry_date: e.target.value})),
        }),
        React.createElement('select', {
          className:'tv-input', value: form.market_regime, style:{width:120},
          onChange: e => setForm(p => ({...p, market_regime: e.target.value})),
        }, REGIMES.map(r => React.createElement('option', { key:r, value:r }, r || 'Regime…'))),
        React.createElement('select', {
          className:'tv-input', value: form.mood, style:{width:80},
          onChange: e => setForm(p => ({...p, mood: e.target.value})),
        }, [1,2,3,4,5].map(m => React.createElement('option', { key:m, value:m }, `${MOOD_LABELS[m]} ${m}`)))
      ),
      React.createElement('input', {
        className:'tv-input', placeholder:'Title',
        value: form.title,
        onChange: e => setForm(p => ({...p, title: e.target.value})),
      }),
      React.createElement('textarea', {
        className:'tv-input', placeholder:'Notes, observations, lessons…',
        value: form.body, rows:5,
        style:{ resize:'vertical', fontFamily:'inherit' },
        onChange: e => setForm(p => ({...p, body: e.target.value})),
      }),
      React.createElement('input', {
        className:'tv-input', placeholder:'Tags (comma-separated)',
        value: form.tags,
        onChange: e => setForm(p => ({...p, tags: e.target.value})),
      }),
      React.createElement('div', { style:{display:'flex', gap:8} },
        React.createElement('button', {
          className:'tv-btn primary', disabled:saving, onClick:saveEntry,
        }, saving ? 'Saving…' : editId ? 'Update' : 'Save'),
        React.createElement('button', { className:'tv-btn', onClick:() => setShowForm(false) }, 'Cancel')
      )
    ),

    /* Entries */
    entries.length === 0 && !showForm
      ? React.createElement('div', { className:'tv-card', style:{textAlign:'center', color:'var(--text4)', padding:32} },
          'No journal entries yet.')
      : entries.map(e =>
          React.createElement('div', {
            key: e.id, className:'tv-card',
          },
            React.createElement('div', {
              style:{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', cursor:'pointer' },
              onClick: () => setExpanded(expanded === e.id ? null : e.id),
            },
              React.createElement('div', null,
                React.createElement('div', { style:{fontWeight:600, fontSize:14} }, e.title),
                React.createElement('div', { style:{display:'flex', gap:8, marginTop:4, fontSize:12, color:'var(--text4)'} },
                  React.createElement('span', null, e.entry_date),
                  e.market_regime && React.createElement('span', { className:'tv-chip' }, e.market_regime),
                  e.mood && React.createElement('span', null, MOOD_LABELS[e.mood])
                )
              ),
              React.createElement('span', { style:{color:'var(--text4)', fontSize:12} }, expanded === e.id ? '▲' : '▼')
            ),
            expanded === e.id && React.createElement('div', { style:{ marginTop:12, paddingTop:12, borderTop:'1px solid var(--line)' } },
              e.body && React.createElement('div', { style:{ fontSize:13, color:'var(--text2)', whiteSpace:'pre-wrap', marginBottom:8 } }, e.body),
              e.tags && e.tags.length > 0 && React.createElement('div', { style:{ display:'flex', gap:4, flexWrap:'wrap', marginBottom:8 } },
                e.tags.map((t, i) => React.createElement('span', { key:i, className:'tv-chip' }, t))
              ),
              React.createElement('div', { style:{ display:'flex', gap:8 } },
                React.createElement('button', { className:'tv-btn', onClick: () => openEditForm(e) }, 'Edit'),
                React.createElement('button', { className:'tv-btn', style:{color:'var(--fail)'}, onClick: () => deleteEntry(e.id) }, 'Delete')
              )
            )
          )
        )
  );
}

/* ===== PLACEHOLDER SCREENS ===== */
function ValidatorScreen() { return React.createElement(TdPlaceholder, { label:'Validator' }); }
function ReportsScreen()   { return React.createElement(TdPlaceholder, { label:'Reports'   }); }
function TradingSettingsScreen() { return React.createElement(TdPlaceholder, { label:'Trading Settings' }); }

/* ===== EXPORTS ===== */
window.ScannerScreen          = ScannerScreen;
window.ConceptsScreen         = ConceptsScreen;
window.QuizScreen             = QuizScreen;
window.JournalScreen          = JournalScreen;
window.ValidatorScreen        = ValidatorScreen;
window.ReportsScreen          = ReportsScreen;
window.TradingSettingsScreen  = TradingSettingsScreen;
