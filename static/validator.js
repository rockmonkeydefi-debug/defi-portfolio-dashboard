/* ===== VALIDATOR SCREEN ===== */

const { useState: useVS, useEffect: useVE, useMemo: useVM, useRef: useVR } = React;

// FALLBACK — used only if strategy API call fails
// ─── FLOW DEFINITION ──────────────────────────────────────────────────────────

const FALLBACK_BASE_FLOW = [
  {
    id: 'setup', label: 'HTF Bias', stepType: 'HTF', concept: 'market structure',
    question: 'What is the HTF bias and market structure?',
    subtext: 'Assess the most recent decisive break of structure on the 4H or daily.',
    options: [
      { key: 'A', title: 'Bullish — last BOS to upside', description: 'Most recent decisive BOS is to the upside; lower-high not yet printed.', branches: 3 },
      { key: 'B', title: 'Bearish — last BOS to downside', description: 'Most recent BOS is to downside; lower-high confirmed.', branches: 3 },
      { key: 'C', title: 'Neutral / ranging', description: 'No clear BOS in either direction; market is consolidating between equal highs/lows.', branches: 2 },
      { key: 'D', title: 'HTF bias unclear — needs more data', description: 'Structure is ambiguous; multiple conflicting BOS signals.', endsFlow: true },
    ],
  },
  {
    id: 'dealing_range', label: 'Dealing Range', stepType: 'HTF', concept: 'dealing range',
    question: 'Where is price within the HTF dealing range?',
    subtext: 'Identify the current 4H or daily range high and low. Is price in premium or discount?',
    options: [
      { key: 'A', title: 'Discount — price below 0.5 of range', description: 'Price is below the 50% equilibrium of the range; looking for longs.', branches: 3 },
      { key: 'B', title: 'Premium — price above 0.5 of range', description: 'Price is above equilibrium; looking for shorts.', branches: 3 },
      { key: 'C', title: 'At equilibrium (0.5)', description: 'Price is at the 50% level — less ideal for entries, higher risk.', branches: 2 },
      { key: 'D', title: 'Outside defined range', description: 'Price has broken beyond the range; reassess HTF structure.', branches: 1 },
    ],
  },
  {
    id: 'htf_liquidity', label: 'HTF Liquidity', stepType: 'HTF', concept: 'liquidity sweep',
    question: 'Has HTF liquidity been swept?',
    subtext: 'Check for swept equal highs/lows, session highs/lows, or significant swing points on 4H/daily.',
    options: [
      { key: 'A', title: 'Yes — sell-side swept and reclaimed', description: 'Sell-side liquidity (lows) taken and price has reclaimed above the swept level.', branches: 3 },
      { key: 'B', title: 'Yes — buy-side swept and reclaimed', description: 'Buy-side liquidity (highs) taken and price has reclaimed below the swept level.', branches: 3 },
      { key: 'C', title: 'Partially swept — no clean reclaim yet', description: "Liquidity targeted but price hasn't clearly reclaimed; setup still forming.", branches: 2 },
      { key: 'D', title: 'No sweep — liquidity still above/below', description: 'Significant liquidity pool remains untested; price may seek it first.', branches: 1 },
    ],
  },
  {
    id: 'entry_trigger', label: 'Entry Trigger', stepType: 'LTF', concept: 'trade entries', isAdaptiveBranch: true,
    question: 'What is your entry trigger on the lower timeframe?',
    subtext: "With HTF context set — pick the LTF trigger you're waiting for.",
    options: [
      { key: 'A', title: 'Bullish Fair Value Gap (FVG)', description: 'Price returns to an unmitigated FVG inside the discount array; entry on the FVG mid or low.', branches: 3 },
      { key: 'B', title: 'Liquidity sweep + structure shift (LTF)', description: 'Wait for a sweep on the lower timeframe followed by a BOS/ChoCH before entry.', branches: 2 },
      { key: 'C', title: 'Inside an HTF bullish order block', description: 'Price taps an OB defined on the 4H bias timeframe; entry at the OB high or 50%.', branches: 3 },
      { key: 'D', title: 'No trigger yet — observing only', description: 'Stand aside; criteria not met for a managed entry.', endsFlow: true },
    ],
  },
];

const FALLBACK_ADAPTIVE_STEPS = {
  A: {
    id: 'confirmation_fvg', label: 'FVG Detail', stepType: 'LTF', concept: 'fair value gap', isAdaptive: true,
    question: "Describe the FVG you're trading.",
    subtext: 'A valid FVG needs displacement (3-candle move), should be unmitigated, and ideally inside the discount array.',
    options: [
      { key: 'A', title: 'Virgin FVG — unmitigated, 3-candle displacement', description: 'Created by strong displacement; price has never returned to it.', branches: 2 },
      { key: 'B', title: 'Partially mitigated FVG — still has lower portion', description: 'Price has touched the top but not filled the full gap.', branches: 2 },
      { key: 'C', title: 'FVG at OB confluence', description: 'FVG aligns with an order block from the same timeframe; higher confluence.', branches: 3 },
      { key: 'D', title: 'FVG but not in discount / not displaced', description: 'FVG exists but context is weak; below-average quality setup.', branches: 1 },
    ],
  },
  B: {
    id: 'ltf_sweep', label: 'LTF Sweep', stepType: 'LTF', concept: 'liquidity sweep', isAdaptive: true,
    question: 'On the lower timeframe, where has price swept liquidity that signals reversal?',
    subtext: 'For a long entry you need a sell-side sweep on the LTF — followed by a ChoCH — before considering entry.',
    options: [
      { key: 'A', title: 'Equal lows on 5m — clean sweep with rejection wick', description: 'Recent equal lows swept by ~8 ticks, immediate reclaim. Classic LTF sweep.', branches: 2 },
      { key: 'B', title: 'Session low (NY open) — partial wick', description: 'NY session low touched but no decisive reclaim yet.', branches: 2 },
      { key: 'C', title: 'Trendline liquidity (sloped lows)', description: 'A sloped diagonal of lows on 15m has been broken and recovered.', branches: 2 },
      { key: 'D', title: 'No qualifying sweep yet', description: 'Stand aside until a clean LTF sweep prints.', endsFlow: true },
    ],
  },
  C: {
    id: 'ob_confirmation', label: 'OB Confirmation', stepType: 'LTF', concept: 'order block', isAdaptive: true,
    question: 'Is the order block confirmed and is price reacting at the level?',
    subtext: 'A valid OB entry requires price to tap the zone and show rejection — not just touch it.',
    options: [
      { key: 'A', title: 'Strong rejection wick at OB high — ChoCH on 5m', description: 'Clean wick rejection and lower-timeframe structure shift confirmed.', branches: 3 },
      { key: 'B', title: 'Price inside OB — no rejection yet', description: 'Price has entered the zone but no confirmation candle yet; wait.', branches: 2 },
      { key: 'C', title: 'OB mitigated — price pushed through', description: 'Price ran through the OB without holding; OB is invalidated.', endsFlow: true },
      { key: 'D', title: 'OB tapped but weak reaction', description: 'Marginal reaction at best; below-average confidence.', branches: 1 },
    ],
  },
};

const FALLBACK_RISK_STEP = {
  id: 'risk', label: 'Risk / Inv.', stepType: 'LTF', concept: 'risk management', isForm: true,
  question: 'Define your risk parameters and invalidation.',
  subtext: 'Set your stop, targets, and the condition that tells you the trade thesis is wrong.',
};

const FALLBACK_STEP_LABELS = ['HTF Bias', 'Dealing Range', 'HTF Liq.', 'Entry Trigger', 'Confirmation', 'Risk / Inv.', 'Review'];

// Build an activeFlow object from a strategy's flow_json, falling back to FALLBACK constants
function buildActiveFlow(flowJson) {
  if (flowJson && flowJson.base_flow && flowJson.base_flow.length > 0) {
    const labels = flowJson.step_labels || flowJson.base_flow.map(s => s.label).concat(['Review']);
    return {
      base_flow: flowJson.base_flow,
      adaptive_steps: flowJson.adaptive_steps || {},
      risk_step: flowJson.risk_step || FALLBACK_RISK_STEP,
      step_labels: labels,
    };
  }
  return {
    base_flow: FALLBACK_BASE_FLOW,
    adaptive_steps: FALLBACK_ADAPTIVE_STEPS,
    risk_step: FALLBACK_RISK_STEP,
    step_labels: FALLBACK_STEP_LABELS,
  };
}

function getFlowStep(idx, answers, activeFlow) {
  const af = activeFlow || buildActiveFlow(null);
  const bf = af.base_flow;
  const adaptiveSteps = af.adaptive_steps || {};
  const riskStep = af.risk_step;
  const hasAdaptive = Object.keys(adaptiveSteps).length > 0;

  if (idx < bf.length) return bf[idx];

  // After base_flow: check if there's an adaptive step for the last adaptive-branch answer
  if (hasAdaptive) {
    // Find the adaptive branch step in base_flow
    const branchStep = bf.find(s => s.isAdaptiveBranch);
    const branchAnswer = branchStep ? answers[branchStep.id] : null;
    const adaptiveIdx = bf.findIndex(s => s.isAdaptiveBranch) + 1;
    if (idx === adaptiveIdx && branchAnswer) {
      return adaptiveSteps[branchAnswer.optionKey] || null;
    }
    if (idx === adaptiveIdx + 1) return riskStep;
  } else {
    if (idx === bf.length) return riskStep;
  }
  return null;
}

// ─── COMPONENT ────────────────────────────────────────────────────────────────

function ValidatorScreen({ onSwitchTab }) {
  const [phase, setPhase] = useVS('setup');
  const [setupForm, setSetupForm] = useVS({ ticker: '', direction: 'long', timeframe: '1h' });
  const [ticker, setTicker] = useVS('');
  const [direction, setDirection] = useVS('long');
  const [timeframe, setTimeframe] = useVS('1h');
  const [currentStepIdx, setCurrentStepIdx] = useVS(0);
  const [answers, setAnswers] = useVS({});
  const [selectedOption, setSelectedOption] = useVS(null);
  const [riskForm, setRiskForm] = useVS({ entry: '', stop: '', tp1: '', tp2: '', invalidation: '' });
  const [saving, setSaving] = useVS(false);
  const [savedId, setSavedId] = useVS(null);
  const [saveMsg, setSaveMsg] = useVS(null);
  // Strategy state
  const [strategies, setStrategies] = useVS([]);
  const [selectedStrategyId, setSelectedStrategyId] = useVS(null);
  const [activeFlow, setActiveFlow] = useVS(() => buildActiveFlow(null));

  // Load strategies on mount
  useVE(() => {
    api('/api/trading/strategies')
      .then(data => {
        setStrategies(data);
        const def = data.find(s => s.is_default === 1) || data[0];
        if (def) {
          setSelectedStrategyId(def.id);
          setActiveFlow(buildActiveFlow(def.flow_json));
          setSetupForm(prev => ({ ...prev, _strategyId: def.id }));
        }
      })
      .catch(() => {}); // silently fall back to FALLBACK constants
  }, []);

  // Re-derive activeFlow when strategy selection changes
  useVE(() => {
    const s = strategies.find(st => st.id === selectedStrategyId);
    setActiveFlow(buildActiveFlow(s ? s.flow_json : null));
  }, [selectedStrategyId, strategies]);

  // Restore draft from sessionStorage on mount
  useVE(() => {
    try {
      const raw = sessionStorage.getItem('validator_draft');
      if (!raw) return;
      const d = JSON.parse(raw);
      sessionStorage.removeItem('validator_draft');
      if (!d.ticker) return;
      setTicker(d.ticker);
      setDirection(d.direction || 'long');
      setTimeframe(d.timeframe || '1h');
      setSetupForm({ ticker: d.ticker, direction: d.direction || 'long', timeframe: d.timeframe || '1h' });
      if (d.answers && Object.keys(d.answers).length > 0) {
        setAnswers(d.answers);
        const lastIdx = Object.keys(d.answers).length;
        setCurrentStepIdx(Math.min(lastIdx, 5));
      }
      setPhase('flow');
    } catch (_) {}
  }, []);

  // Keyboard shortcuts during flow
  useVE(() => {
    if (phase !== 'flow') return;
    const step = getFlowStep(currentStepIdx, answers, activeFlow);
    if (!step || step.isForm) return;
    const opts = step.options || [];
    function onKey(e) {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
      if (['1','2','3','4'].includes(e.key)) {
        const opt = opts[parseInt(e.key) - 1];
        if (opt) setSelectedOption(opt.key);
      }
      if (e.key === 'Enter' && selectedOption) advance();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [phase, currentStepIdx, selectedOption, answers]);

  function beginFlow() {
    const t = setupForm.ticker.trim().toUpperCase();
    if (!t) return;
    setTicker(t); setDirection(setupForm.direction); setTimeframe(setupForm.timeframe);
    setAnswers({}); setSelectedOption(null); setCurrentStepIdx(0);
    setRiskForm({ entry: '', stop: '', tp1: '', tp2: '', invalidation: '' });
    setPhase('flow');
  }

  function calcRR(entry, stop, tp1, dir) {
    const e = parseFloat(entry), s = parseFloat(stop), t = parseFloat(tp1);
    if (isNaN(e) || isNaN(s) || isNaN(t) || e === s) return null;
    const d = dir || direction;
    return d === 'long' ? (t - e) / (e - s) : (e - t) / (s - e);
  }

  function advance() {
    const step = getFlowStep(currentStepIdx, answers, activeFlow);
    if (!step) return;

    if (step.isForm) {
      const { entry, stop, tp1, tp2, invalidation } = riskForm;
      if (!entry || !stop || !tp1 || !invalidation) return;
      const rr = calcRR(entry, stop, tp1);
      const val = `Entry ${entry} · Stop ${stop} · TP1 ${tp1}${tp2 ? ' · TP2 ' + tp2 : ''}`;
      setAnswers(prev => ({ ...prev, [step.id]: { label: step.label, value: val, optionKey: null, form: riskForm, rr } }));
      setPhase('review');
      return;
    }

    if (!selectedOption) return;
    const opt = step.options.find(o => o.key === selectedOption);
    if (!opt) return;
    const newAnswers = { ...answers, [step.id]: { label: step.label, value: opt.title, optionKey: selectedOption, endsFlow: !!opt.endsFlow } };
    setAnswers(newAnswers);
    setSelectedOption(null);
    const totalSteps = activeFlow.base_flow.length + (Object.keys(activeFlow.adaptive_steps).length > 0 ? 1 : 0);
    if (currentStepIdx < totalSteps) setCurrentStepIdx(i => i + 1);
    else { setPhase('review'); }
  }

  function goBack() {
    if (currentStepIdx === 0) { setPhase('setup'); return; }
    const step = getFlowStep(currentStepIdx, answers, activeFlow);
    if (step) {
      setAnswers(prev => { const n = { ...prev }; delete n[step.id]; return n; });
    }
    setCurrentStepIdx(i => i - 1);
    setSelectedOption(null);
  }

  function computeScore(ans) {
    const ids = activeFlow.base_flow.map(s => s.id);
    const branchStep = activeFlow.base_flow.find(s => s.isAdaptiveBranch);
    const s3 = (ans || answers)[branchStep?.id];
    if (s3 && activeFlow.adaptive_steps[s3.optionKey]) ids.push(activeFlow.adaptive_steps[s3.optionKey].id);
    ids.push(activeFlow.risk_step.id);
    const done = ids.filter(id => (ans || answers)[id]).length;
    return `${done}/${ids.length}`;
  }

  function stepStatus(id, ans) {
    if (!ans) return 'pending';
    if (ans.endsFlow) return 'warn';
    const WARN_WORDS = ['No qualifying','unclear','Outside','At equilib','Partially','No sweep','No trigger'];
    if (WARN_WORDS.some(w => (ans.value || '').includes(w))) return 'warn';
    if (id === 'risk' && ans.rr !== undefined && ans.rr !== null && ans.rr < 1.5) return 'warn';
    return 'pass';
  }

  async function saveToJournal(markTaken = false) {
    setSaving(true); setSaveMsg(null);
    try {
      const riskAns = answers['risk'];
      const plan = riskAns?.form || {};
      const concepts = [...new Set(
        activeFlow.base_flow.map(s => s.concept).filter((c, i) => answers[activeFlow.base_flow[i]?.id])
          .concat((() => {
            const branchStep = activeFlow.base_flow.find(s => s.isAdaptiveBranch);
            const s3 = branchStep ? answers[branchStep.id] : null;
            return s3 && activeFlow.adaptive_steps[s3.optionKey] ? [activeFlow.adaptive_steps[s3.optionKey].concept] : [];
          })())
          .concat(['risk management'])
      )];
      const lines = [];
      Object.entries(answers).forEach(([id, a]) => {
        if (id !== 'risk') lines.push(`## ${a.label}\n${a.value}\n`);
      });
      if (plan.invalidation) lines.push(`## Execution\nEntry: ${plan.entry} · Stop: ${plan.stop} · TP1: ${plan.tp1}${plan.tp2?' · TP2: '+plan.tp2:''}\nInvalidation: ${plan.invalidation}\n`);

      const strategyName = (strategies.find(s => s.id === selectedStrategyId)?.name) || 'ICT/SMC';
      const payload = {
        title: `${ticker} ${direction.toUpperCase()} — ${timeframe} [${strategyName}]`,
        body: lines.join('\n'),
        ticker, direction, timeframe,
        outcome: 'open',
        ready_score: computeScore(answers),
        execution_plan_json: plan,
        concepts_json: concepts,
        validator_answers_json: answers,
        tags: [ticker, direction, timeframe, ...concepts],
        mood: 3,
        entry_date: new Date().toISOString().slice(0, 10),
      };

      let res;
      if (savedId && !markTaken) {
        await api(`/api/trading/journal/${savedId}`, { method: 'PUT', body: JSON.stringify(payload) });
        setSaveMsg('✓ Updated journal entry');
      } else {
        res = await api('/api/trading/journal', { method: 'POST', body: JSON.stringify(payload) });
        setSavedId(res.id);
        setSaveMsg(markTaken ? '✓ Trade marked as active in journal' : '✓ Saved to journal');
      }
      if (onSwitchTab) setTimeout(() => onSwitchTab('tt-journal'), 900);
    } catch (e) { setSaveMsg(`Error: ${e.message}`); }
    finally { setSaving(false); }
  }

  function copyAsText() {
    const lines = [`PRE-TRADE REASONING RECORD\n${ticker} · ${timeframe} · ${direction}\n`];
    Object.entries(answers).forEach(([, a]) => lines.push(`${(a.label||'').toUpperCase()}\n${a.value}\n`));
    navigator.clipboard.writeText(lines.join('\n')).catch(() => {});
  }

  // ─── SETUP MODAL ───────────────────────────────────────────────────────────
  if (phase === 'setup') {
    return React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 400, padding: '16px 0' } },
      React.createElement('div', { className: 'tv-card', style: { width: 380, padding: 28, display: 'flex', flexDirection: 'column', gap: 16 } },
        React.createElement('div', { style: { fontSize: 18, fontWeight: 700 } }, 'Trade Setup Validator'),
        React.createElement('div', { style: { fontSize: 13, color: 'var(--text4)' } }, 'Adaptive decision tree validator'),
        strategies.length > 0 && React.createElement('div', null,
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 4 } }, 'Strategy'),
          React.createElement('select', {
            className: 'tv-input', style: { width: '100%' }, value: selectedStrategyId || '',
            onChange: e => setSelectedStrategyId(parseInt(e.target.value) || null),
          },
            strategies.map(s => React.createElement('option', { key: s.id, value: s.id }, s.name + (s.is_default ? ' (default)' : '')))
          )
        ),
        React.createElement('div', null,
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 4 } }, 'Ticker'),
          React.createElement('input', {
            className: 'tv-input', placeholder: 'e.g. BTCUSDT', autoFocus: true,
            value: setupForm.ticker,
            style: { width: '100%', textTransform: 'uppercase', fontSize: 15, fontWeight: 600 },
            onChange: e => setSetupForm(p => ({ ...p, ticker: e.target.value.toUpperCase() })),
            onKeyDown: e => { if (e.key === 'Enter') beginFlow(); },
          })
        ),
        React.createElement('div', null,
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 6 } }, 'Direction'),
          React.createElement('div', { style: { display: 'flex', gap: 6 } },
            ['long', 'short'].map(d =>
              React.createElement('button', {
                key: d, onClick: () => setSetupForm(p => ({ ...p, direction: d })),
                style: {
                  flex: 1, padding: '8px 0', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                  background: setupForm.direction === d ? (d === 'long' ? 'var(--ok)' : 'var(--fail)') : 'var(--panel2)',
                  border: `1px solid ${setupForm.direction === d ? (d === 'long' ? 'var(--ok)' : 'var(--fail)') : 'var(--line)'}`,
                  color: setupForm.direction === d ? '#000' : 'var(--text)',
                }
              }, d.toUpperCase())
            )
          )
        ),
        React.createElement('div', null,
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 6 } }, 'Timeframe'),
          React.createElement('div', { style: { display: 'flex', gap: 4 } },
            ['5m','15m','1h','4h','1d'].map(tf =>
              React.createElement('button', {
                key: tf, onClick: () => setSetupForm(p => ({ ...p, timeframe: tf })),
                style: {
                  flex: 1, padding: '6px 0', borderRadius: 4, fontSize: 11, cursor: 'pointer',
                  background: setupForm.timeframe === tf ? 'var(--accent)' : 'var(--panel2)',
                  border: `1px solid ${setupForm.timeframe === tf ? 'var(--accent)' : 'var(--line)'}`,
                  color: setupForm.timeframe === tf ? '#000' : 'var(--text)',
                }
              }, tf)
            )
          )
        ),
        React.createElement('button', {
          className: 'tv-btn primary', disabled: !setupForm.ticker.trim(), onClick: beginFlow,
          style: { fontSize: 14, padding: '10px 0', marginTop: 4 },
        }, 'Begin Validator →')
      )
    );
  }

  // ─── REVIEW PHASE ──────────────────────────────────────────────────────────
  if (phase === 'review') {
    const riskAns = answers['risk'];
    const plan = riskAns?.form || {};
    const rr = calcRR(plan.entry, plan.stop, plan.tp1);
    const branchStepReview = activeFlow.base_flow.find(s => s.isAdaptiveBranch);
    const s3 = branchStepReview ? answers[branchStepReview.id] : null;
    const allStepIds = activeFlow.base_flow.map(s => s.id);
    if (s3 && activeFlow.adaptive_steps[s3.optionKey]) allStepIds.push(activeFlow.adaptive_steps[s3.optionKey].id);
    allStepIds.push(activeFlow.risk_step.id);
    const counts = { pass: 0, warn: 0 };
    allStepIds.forEach(id => { const s = stepStatus(id, answers[id]); counts[s] = (counts[s] || 0) + 1; });
    const hasEndFlow = Object.values(answers).some(a => a.endsFlow);
    const readiness = hasEndFlow ? 'NOT READY' : (rr !== null && rr < 1.5) ? 'CONDITIONAL' : 'READY';
    const readColor = readiness === 'READY' ? 'var(--ok)' : readiness === 'CONDITIONAL' ? 'var(--warn)' : 'var(--fail)';

    return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 14, padding: '16px 0' } },
      React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 } },
        React.createElement('div', null,
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 } }, 'Pre-Trade Reasoning Record'),
          React.createElement('div', { style: { fontSize: 20, fontWeight: 700 } }, `${ticker} · ${timeframe} · ${direction}`)
        ),
        React.createElement('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap' } },
          React.createElement('button', { className: 'tv-btn', onClick: () => setPhase('flow'), style: { fontSize: 12 } }, '← Edit answers'),
          React.createElement('button', { className: 'tv-btn', onClick: copyAsText, style: { fontSize: 12 } }, 'Copy as text'),
          React.createElement('button', { className: 'tv-btn', disabled: saving, onClick: () => saveToJournal(false), style: { fontSize: 12 } }, saving ? 'Saving…' : 'Save to journal'),
          React.createElement('button', { className: 'tv-btn primary', disabled: saving, onClick: () => saveToJournal(true), style: { fontSize: 12 } }, 'Mark as taken →')
        )
      ),
      saveMsg && React.createElement('div', { style: { color: saveMsg.startsWith('Error') ? 'var(--fail)' : 'var(--ok)', fontSize: 13 } }, saveMsg),

      // Readiness
      React.createElement('div', { style: { display: 'flex', gap: 14, alignItems: 'flex-start', flexWrap: 'wrap' } },
        React.createElement('div', { className: 'tv-card', style: { width: 170, flexShrink: 0, padding: '16px 14px', textAlign: 'center' } },
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 8 } }, 'Readiness'),
          React.createElement('div', { style: { fontSize: 18, fontWeight: 700, color: readColor, marginBottom: 4 } }, readiness),
          React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)' } }, `${counts.pass || 0} of ${allStepIds.length} criteria met`)
        )
      ),

      // Execution Plan (moved above Criteria)
      React.createElement('div', { className: 'tv-card', style: { flex: 1, minWidth: 200 } },
        React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 10 } }, 'Execution Plan'),
        React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 8 } },
          [['Entry', plan.entry], ['Stop', plan.stop], ['Target 1', plan.tp1], ['Target 2', plan.tp2 || '—']].map(([lbl, val]) =>
            React.createElement('div', { key: lbl },
              React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', marginBottom: 2 } }, lbl),
              React.createElement('div', { style: { fontFamily: 'Fira Code, monospace', fontSize: 13, fontWeight: 600 } }, val || '—')
            )
          )
        ),
        plan.invalidation && React.createElement('div', { style: { fontSize: 12, color: 'var(--text3)', marginBottom: 8 } },
          React.createElement('span', { style: { color: 'var(--text4)' } }, 'Invalidation: '), plan.invalidation
        ),
        rr !== null && React.createElement('span', {
          style: { fontSize: 11, padding: '2px 8px', borderRadius: 10, background: rr >= 2 ? 'var(--ok-soft)' : rr >= 1.5 ? 'var(--warn-soft)' : 'var(--fail-soft)', color: rr >= 2 ? 'var(--ok)' : rr >= 1.5 ? 'var(--warn)' : 'var(--fail)', border: `1px solid ${rr >= 2 ? 'var(--ok)' : rr >= 1.5 ? 'var(--warn)' : 'var(--fail)'}` }
        }, `R:R  1 : ${rr.toFixed(1)}  ${rr < 1.5 ? '⚠ below 1:3 target' : rr >= 2 ? '✓ good' : ''}`)
      ),

      // Criteria table
      React.createElement('div', { className: 'tv-card', style: { padding: 0, overflow: 'hidden' } },
        React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderBottom: '1px solid var(--line)' } },
          React.createElement('div', { style: { fontSize: 12, fontWeight: 600 } }, 'Criteria'),
          React.createElement('div', { style: { display: 'flex', gap: 10, fontSize: 11 } },
            React.createElement('span', { style: { color: 'var(--ok)' } }, `● ${counts.pass||0} pass`),
            React.createElement('span', { style: { color: 'var(--warn)' } }, `● ${counts.warn||0} warn`)
          )
        ),
        allStepIds.map((id, i) => {
          const ans = answers[id]; if (!ans) return null;
          const st = stepStatus(id, ans);
          const stColor = st === 'pass' ? 'var(--ok)' : 'var(--warn)';
          return React.createElement('div', {
            key: id,
            style: { display: 'flex', alignItems: 'center', gap: 12, padding: '9px 14px', borderBottom: i < allStepIds.length - 1 ? '1px solid var(--line)' : 'none' }
          },
            React.createElement('span', { style: { color: stColor, fontSize: 13, width: 14, flexShrink: 0 } }, st === 'pass' ? '✓' : '!'),
            React.createElement('div', { style: { flex: 1, minWidth: 0 } },
              React.createElement('div', { style: { display: 'flex', gap: 6, alignItems: 'center', marginBottom: 2 } },
                React.createElement('span', { style: { fontWeight: 600, fontSize: 12 } }, ans.label),
                ans.endsFlow && React.createElement('span', { className: 'tv-chip warn' }, 'flagged')
              ),
              React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, ans.value)
            ),
            React.createElement('span', { style: { fontSize: 10, color: stColor, fontWeight: 600, flexShrink: 0 } }, st.toUpperCase())
          );
        })
      )
    );
  }

  // ─── FLOW PHASE ────────────────────────────────────────────────────────────
  const step = getFlowStep(currentStepIdx, answers, activeFlow);
  const branchStepFlow = activeFlow.base_flow.find(s => s.isAdaptiveBranch);
  const s3ans = branchStepFlow ? answers[branchStepFlow.id] : null;
  const isPathAdapted = !!(s3ans && activeFlow.adaptive_steps[s3ans.optionKey]);
  const rr = step?.isForm ? calcRR(riskForm.entry, riskForm.stop, riskForm.tp1) : null;
  const canAdvance = step?.isForm
    ? !!(riskForm.entry && riskForm.stop && riskForm.tp1 && riskForm.invalidation)
    : !!selectedOption;

  const completedSteps = [];
  for (let i = 0; i < currentStepIdx; i++) {
    const s = getFlowStep(i, answers, activeFlow);
    if (s && answers[s.id]) completedSteps.push({ step: s, answer: answers[s.id] });
  }
  const stepLabels = activeFlow.step_labels;

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 12, padding: '16px 0' } },
    // Top bar
    React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' } },
      React.createElement('div', null,
        React.createElement('div', { style: { fontSize: 17, fontWeight: 700 } }, 'Trade Setup Validator'),
        React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', marginTop: 2, display: 'flex', gap: 8, alignItems: 'center' } },
          `${ticker} · ${timeframe} · ${strategies.find(s=>s.id===selectedStrategyId)?.name||'adaptive'} · ${stepLabels.length} steps`,
          isPathAdapted && React.createElement('span', { className: 'tv-chip adapt' }, '● path adapted')
        )
      ),
      React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center' } },
        React.createElement('span', { style: { fontSize: 12, color: 'var(--text4)' } }, `step ${currentStepIdx + 1} / ${stepLabels.length}`),
        React.createElement('button', { className: 'tv-btn', onClick: () => setPhase('setup'), style: { fontSize: 12 } }, 'Save & exit')
      )
    ),

    // Progress rail
    React.createElement('div', { style: { display: 'flex', alignItems: 'center', padding: '6px 0', overflowX: 'auto' } },
      stepLabels.map((lbl, i) => {
        const isDone = i < currentStepIdx, isCur = i === currentStepIdx;
        const adaptIdx = activeFlow.base_flow.findIndex(s => s.isAdaptiveBranch) + 1;
        const isAdaptNode = i === adaptIdx && isPathAdapted;
        return React.createElement('div', { key: i, style: { display: 'flex', alignItems: 'center', flexShrink: 0 } },
          i > 0 && React.createElement('div', { style: { width: 20, height: 1, background: isDone ? 'var(--ok)' : 'var(--line)', borderTop: i >= 4 ? '1px dashed var(--line)' : undefined } }),
          React.createElement('div', {
            onClick: isDone ? () => { setCurrentStepIdx(i); setSelectedOption(null); } : undefined,
            style: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3, cursor: isDone ? 'pointer' : 'default' }
          },
            React.createElement('div', {
              style: {
                width: isCur ? 22 : 18, height: isCur ? 22 : 18,
                borderRadius: isAdaptNode ? 3 : '50%',
                transform: isAdaptNode ? 'rotate(45deg)' : 'none',
                background: isDone ? 'var(--ok)' : isCur ? 'var(--accent)' : 'var(--panel2)',
                border: `2px solid ${isDone ? 'var(--ok)' : isCur ? 'var(--accent)' : 'var(--line)'}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 9, fontWeight: 700, color: isDone || isCur ? '#000' : 'var(--text4)',
              }
            }, isDone ? '✓' : i + 1),
            React.createElement('div', { style: { fontSize: 8, color: isCur ? 'var(--text)' : 'var(--text4)', textAlign: 'center', maxWidth: 52, lineHeight: 1.2 } }, lbl)
          )
        );
      })
    ),

    // Adaptation banner
    step?.isAdaptive && React.createElement('div', {
      style: { fontSize: 12, color: 'var(--adapt)', background: 'var(--adapt-soft)', borderLeft: '3px solid var(--adapt)', padding: '6px 12px', borderRadius: 4 }
    }, `↻ Step 5 adapted based on your Entry Trigger: "${s3ans?.value || ''}"`),

    // Two-column content
    React.createElement('div', { style: { display: 'flex', gap: 16, alignItems: 'flex-start' } },

      // Left — question
      React.createElement('div', { style: { flex: 3, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 10 } },
        React.createElement('div', { className: 'tv-card' },
          // Meta row
          React.createElement('div', { style: { display: 'flex', gap: 6, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' } },
            React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.07em' } }, `Step ${currentStepIdx + 1} · ${step?.label || ''}`),
            step?.concept && React.createElement('span', { className: 'tv-chip' }, step.concept),
            step?.stepType && React.createElement('span', { style: { fontSize: 10, padding: '1px 5px', borderRadius: 3, background: step.stepType === 'HTF' ? 'var(--accent-soft)' : 'var(--ok-soft)', color: step.stepType === 'HTF' ? 'var(--accent)' : 'var(--ok)' } }, step.stepType),
            step?.isAdaptive && React.createElement('span', { className: 'tv-chip adapt' }, '↓ adaptive')
          ),
          React.createElement('div', { style: { fontSize: 18, fontWeight: 700, marginBottom: 6, lineHeight: 1.4 } }, step?.question || ''),
          step?.subtext && React.createElement('div', { style: { fontSize: 13, color: 'var(--text4)', marginBottom: 16, lineHeight: 1.5 } }, step.subtext),

          // Option cards
          !step?.isForm && step?.options && React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 7 } },
            step.options.map(opt => {
              const isSel = selectedOption === opt.key;
              return React.createElement('div', {
                key: opt.key, onClick: () => setSelectedOption(opt.key),
                style: {
                  display: 'flex', alignItems: 'flex-start', gap: 10, padding: '10px 12px', borderRadius: 6, cursor: 'pointer',
                  background: isSel ? 'var(--accent-soft)' : 'var(--panel2)',
                  border: `1px solid ${isSel ? 'var(--accent)' : 'var(--line)'}`,
                  transition: 'border 0.1s, background 0.1s',
                }
              },
                React.createElement('span', {
                  style: {
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    width: 22, height: 22, borderRadius: 4, fontSize: 11, fontWeight: 700, flexShrink: 0,
                    background: isSel ? 'var(--accent)' : 'var(--panel3)', color: isSel ? '#000' : 'var(--text4)',
                  }
                }, opt.key),
                React.createElement('div', { style: { flex: 1, minWidth: 0 } },
                  React.createElement('div', { style: { fontWeight: 600, fontSize: 13, marginBottom: 2 } }, opt.title),
                  React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', lineHeight: 1.4 } }, opt.description)
                ),
                React.createElement('div', { style: { fontSize: 10, color: opt.endsFlow ? 'var(--warn)' : 'var(--text4)', flexShrink: 0, textAlign: 'right' } },
                  opt.endsFlow ? 'ends flow' : `↓ ${opt.branches}`)
              );
            })
          ),

          // Risk form
          step?.isForm && React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 10 } },
            React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 } },
              [['entry','Entry Price'],['stop','Stop Loss'],['tp1','Target 1'],['tp2','Target 2 (opt)']].map(([field, lbl]) =>
                React.createElement('div', { key: field },
                  React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginBottom: 3, textTransform: 'uppercase' } }, lbl),
                  React.createElement('input', {
                    className: 'tv-input', value: riskForm[field], placeholder: field === 'entry' ? 'e.g. 71830' : '',
                    style: { width: '100%' },
                    onChange: e => setRiskForm(p => ({ ...p, [field]: e.target.value })),
                  })
                )
              )
            ),
            React.createElement('div', null,
              React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginBottom: 3, textTransform: 'uppercase' } }, 'Invalidation Condition'),
              React.createElement('textarea', {
                className: 'tv-input', value: riskForm.invalidation, rows: 2,
                placeholder: 'e.g. Close below 71,640 on 1H',
                style: { width: '100%', resize: 'vertical', fontFamily: 'inherit' },
                onChange: e => setRiskForm(p => ({ ...p, invalidation: e.target.value })),
              })
            ),
            rr !== null && React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center' } },
              React.createElement('span', {
                style: { fontSize: 12, padding: '3px 10px', borderRadius: 10, background: rr >= 2 ? 'var(--ok-soft)' : rr >= 1.5 ? 'var(--warn-soft)' : 'var(--fail-soft)', color: rr >= 2 ? 'var(--ok)' : rr >= 1.5 ? 'var(--warn)' : 'var(--fail)', border: `1px solid ${rr >= 2 ? 'var(--ok)' : rr >= 1.5 ? 'var(--warn)' : 'var(--fail)'}` }
              }, `R:R  1 : ${rr.toFixed(1)}`),
              rr >= 2 ? React.createElement('span', { style: { fontSize: 11, color: 'var(--ok)' } }, '✓ Good R:R')
                      : React.createElement('span', { style: { fontSize: 11, color: 'var(--warn)' } }, '⚠ Below 1:3 target')
            )
          )
        ),

        // Footer bar
        React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
          currentStepIdx > 0
            ? React.createElement('button', { className: 'tv-btn', onClick: goBack, style: { fontSize: 13 } }, '← Back')
            : React.createElement('span', null),
          React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)' } }, '1–4 select · Enter advance'),
          React.createElement('div', { style: { display: 'flex', gap: 8 } },
            React.createElement('button', {
              className: 'tv-btn', style: { fontSize: 12 },
              onClick: () => { if (!selectedOption && step?.options) setSelectedOption(step.options[0].key); advance(); },
            }, 'Skip & flag'),
            React.createElement('button', {
              className: 'tv-btn primary', disabled: !canAdvance, onClick: advance, style: { fontSize: 13 },
            }, currentStepIdx === 5 ? 'Review →' : 'Continue →')
          )
        )
      ),

      // Right — setup so far
      React.createElement('div', { style: { width: 230, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 8 } },
        React.createElement('div', { className: 'tv-card', style: { padding: '12px 14px' } },
          React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 } },
            React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase' } }, 'Setup So Far'),
            React.createElement('span', { style: { fontSize: 11, padding: '1px 6px', borderRadius: 4, background: 'var(--ok-soft)', color: 'var(--ok)' } }, `${completedSteps.length} done`)
          ),
          completedSteps.length === 0
            ? React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', fontStyle: 'italic' } }, 'No answers yet.')
            : completedSteps.map(({ step: s, answer: a }, i) =>
                React.createElement('div', {
                  key: s.id,
                  style: { paddingBottom: 8, marginBottom: i < completedSteps.length - 1 ? 8 : 0, borderBottom: i < completedSteps.length - 1 ? '1px solid var(--line)' : 'none' }
                },
                  React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 2 } },
                    React.createElement('div', { style: { display: 'flex', gap: 4, alignItems: 'center' } },
                      React.createElement('span', { style: { color: 'var(--ok)', fontSize: 11 } }, '✓'),
                      React.createElement('span', { style: { fontWeight: 600, fontSize: 11 } }, s.label)
                    ),
                    React.createElement('span', { style: { fontSize: 9, color: 'var(--text4)' } }, s.stepType)
                  ),
                  React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, a.value)
                )
              )
        ),
        React.createElement('div', { className: 'tv-card', style: { padding: '10px 14px' } },
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 8 } }, 'Remaining'),
          stepLabels.slice(currentStepIdx).map((lbl, i) =>
            React.createElement('div', { key: lbl, style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, marginBottom: 5 } },
              React.createElement('span', { style: { color: i === 0 ? 'var(--text)' : 'var(--text4)' } }, `${currentStepIdx + i + 1} · ${lbl}`),
              i === 0
                ? React.createElement('span', { className: 'tv-chip accent', style: { fontSize: 9 } }, 'active')
                : React.createElement('span', { style: { fontSize: 9, color: 'var(--text4)' } }, 'pending')
            )
          )
        )
      )
    )
  );
}

window.ValidatorScreen = ValidatorScreen;
