/* ===== AI BRIEF SCREEN ===== */

const { useState: useABState, useEffect: useABEffect } = React;

// ── Helpers ────────────────────────────────────────────────────────────────
function fmtABDate(ts) {
  if (!ts) return '—';
  try {
    const d = new Date(typeof ts === 'number' ? ts * 1000 : ts);
    const dd = String(d.getDate()).padStart(2, '0');
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    return `${dd}/${mm}/${d.getFullYear()} ${hh}:${mi}`;
  } catch (e) { return String(ts); }
}

function alignmentChip(alignment) {
  const a = (alignment || '').toLowerCase();
  const cls = a.includes('misalign') ? 'fail' : a.includes('partial') ? 'warn' : a.includes('align') ? 'ok' : 'adapt';
  return React.createElement('span', { className: `tv-chip ${cls}`, style: { fontSize: 11, padding: '2px 8px' } }, alignment || 'Unknown');
}

function priorityBorder(priority) {
  const p = (priority || '').toLowerCase();
  if (p === 'high' || p === 'critical') return 'var(--fail)';
  if (p === 'medium' || p === 'med')    return 'var(--warn)';
  return 'var(--line)';
}

function priorityChip(priority) {
  const p = (priority || '').toLowerCase();
  const cls = (p === 'high' || p === 'critical') ? 'fail' : p === 'low' ? 'ok' : 'warn';
  return React.createElement('span', { className: `tv-chip ${cls}`, style: { fontSize: 10, padding: '2px 7px' } }, (priority || 'MED').toUpperCase());
}

function deadlineChip(deadline) {
  const d = (deadline || '').toLowerCase();
  let label = deadline ? deadline.replace(/_/g, ' ').toUpperCase() : '—';
  if (d.includes('immediate') || d === 'now') label = 'IMMEDIATE';
  else if (d.includes('week'))  label = 'THIS WEEK';
  else if (d.includes('convenient') || d.includes('when')) label = 'WHEN CONVENIENT';
  return React.createElement('span', { className: 'tv-chip adapt', style: { fontSize: 10, padding: '2px 7px' } }, label);
}

function deadlineOrder(deadline) {
  const d = (deadline || '').toLowerCase();
  if (d.includes('immediate') || d === 'now') return 0;
  if (d.includes('week')) return 1;
  return 2;
}

function severityChip(severity) {
  const s = (severity || '').toLowerCase();
  if (s === 'critical')          return React.createElement('span', { className: 'tv-chip fail',  style: { fontSize: 10, padding: '2px 7px', flexShrink: 0 } }, 'CRITICAL');
  if (s === 'warning' || s === 'warn') return React.createElement('span', { className: 'tv-chip warn',  style: { fontSize: 10, padding: '2px 7px', flexShrink: 0 } }, 'FLAG');
  if (s === 'monitor')           return React.createElement('span', { className: 'tv-chip warn',  style: { fontSize: 10, padding: '2px 7px', flexShrink: 0 } }, 'MONITOR');
  return React.createElement('span', { className: 'tv-chip adapt', style: { fontSize: 10, padding: '2px 7px', flexShrink: 0 } }, 'ALERT');
}

function metricValColor(val) {
  const v = String(val || '');
  if (v.startsWith('-') || v.includes(' -')) return 'var(--fail)';
  const positive = ['bull', 'rising', 'strong', 'high', 'above', 'positive', 'expanding'];
  if (positive.some(w => v.toLowerCase().includes(w))) return 'var(--ok)';
  return 'var(--text)';
}

// ── Header Bar ─────────────────────────────────────────────────────────────
function HeaderBar({ report, onGenerate, generating, generateError, onOpenPrompt, onDailyDigest, dailyBriefGenerating }) {
  const ts          = report && report.timestamp;
  const alignment   = report && report.portfolio_alignment;

  return React.createElement('div', { style: { display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 4 } },
    React.createElement('div', null,
      React.createElement('h1', { style: { fontSize: 22, fontWeight: 700, color: 'var(--text)', margin: '0 0 6px' } }, 'AI Brief'),
      React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 12, color: 'var(--text4)' } },
        ts && React.createElement('span', null, 'Generated: ' + fmtABDate(ts)),
        alignment && alignmentChip(alignment),
        React.createElement('span', null, '· Prompt: Strategy Playbook · Docs: DeFi Strategy')
      )
    ),
    React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 } },
      React.createElement('button', { className: 'tv-btn', style: { fontSize: 12, padding: '5px 14px' }, onClick: onOpenPrompt }, '⚙ Prompt'),
      React.createElement('button', {
        className: 'tv-btn',
        style: { fontSize: 12, padding: '5px 14px' },
        onClick: onDailyDigest,
        disabled: dailyBriefGenerating,
      }, dailyBriefGenerating ? '↺ Generating…' : 'Daily Digest'),
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 } },
        React.createElement('button', {
          className: 'tv-btn primary',
          style: { fontSize: 12, padding: '6px 16px' },
          onClick: onGenerate,
          disabled: generating,
        }, generating ? '↺ Generating…' : '↺ Generate Report'),
        generateError && React.createElement('span', { style: { fontSize: 11, color: 'var(--fail)' } }, generateError)
      )
    )
  );
}

// ── Prompt Modal ───────────────────────────────────────────────────────────
function PromptModal({ text, onChange, saving, saved, onSave, onClose }) {
  return React.createElement('div', {
    style: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 },
    onClick: e => { if (e.target === e.currentTarget) onClose(); },
  },
    React.createElement('div', {
      style: { background: 'var(--panel)', borderRadius: 12, padding: 28, width: '100%', maxWidth: 800, display: 'flex', flexDirection: 'column', gap: 16, maxHeight: '90vh', overflow: 'hidden' }
    },
      React.createElement('div', null,
        React.createElement('div', { style: { fontSize: 18, fontWeight: 700, color: 'var(--text)', marginBottom: 6 } }, 'Strategy Prompt'),
        React.createElement('div', { style: { fontSize: 13, color: 'var(--text4)', lineHeight: 1.5 } }, 'This prompt is injected into every AI report as your strategy playbook.')
      ),
      React.createElement('textarea', {
        value: text,
        onChange: e => onChange(e.target.value),
        style: { minHeight: 400, fontSize: 13, fontFamily: "'Fira Code', monospace", background: 'var(--bg)', border: '1px solid var(--line)', color: 'var(--text)', padding: 12, borderRadius: 8, width: '100%', resize: 'vertical', boxSizing: 'border-box', outline: 'none' },
        placeholder: 'Enter your strategy playbook here…',
      }),
      React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12 } },
        React.createElement('button', { className: 'tv-btn', onClick: onClose }, 'Cancel'),
        React.createElement('button', { className: 'tv-btn primary', onClick: onSave, disabled: saving }, saving ? 'Saving…' : 'Save Prompt'),
        saved && React.createElement('span', { style: { fontSize: 12, color: 'var(--ok)' } }, 'Saved ✓')
      )
    )
  );
}

// ── Daily Brief Card ───────────────────────────────────────────────────────
function DailyBriefCard({ brief }) {
  const [briefSending, setBriefSending] = useABState(false);
  const [briefMsg,     setBriefMsg]     = useABState('');

  if (!brief || !brief.brief_text) return null;

  async function sendToTelegram() {
    setBriefSending(true); setBriefMsg('');
    try {
      await api('/api/settings/telegram/test', { method: 'POST', body: JSON.stringify({ message: brief.brief_text }) });
      setBriefMsg('Sent ✓');
    } catch (e) { setBriefMsg('Failed'); }
    finally { setBriefSending(false); }
  }

  const fmtMoney = n => n != null ? '$' + Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 }) : null;
  const btcLabel = fmtMoney(brief.btc_price);
  const pvLabel  = fmtMoney(brief.portfolio_value);

  return React.createElement('div', { className: 'tv-card', style: { borderLeft: '3px solid var(--accent)', padding: 20 } },
    React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 } },
      React.createElement('div', { className: 'tv-label' }, 'Daily Brief'),
      React.createElement('span', { style: { fontSize: 12, color: 'var(--text4)' } }, fmtABDate(brief.timestamp))
    ),
    React.createElement('div', { style: { fontSize: 14, color: 'var(--text)', lineHeight: 1.6, marginBottom: 14, whiteSpace: 'pre-line' } }, brief.brief_text),
    React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' } },
      btcLabel && React.createElement('span', { className: 'tv-chip adapt', style: { fontSize: 11, padding: '2px 8px' } }, 'BTC ' + btcLabel),
      pvLabel  && React.createElement('span', { className: 'tv-chip adapt', style: { fontSize: 11, padding: '2px 8px' } }, 'Portfolio ' + pvLabel),
      React.createElement('button', { className: 'tv-btn', style: { marginLeft: 'auto', fontSize: 12, padding: '4px 14px' }, onClick: sendToTelegram, disabled: briefSending }, briefSending ? 'Sending…' : 'Send to Telegram'),
      briefMsg && React.createElement('span', { style: { fontSize: 12, color: briefMsg.includes('✓') ? 'var(--ok)' : 'var(--fail)' } }, briefMsg)
    )
  );
}

// ── Alert Banner ───────────────────────────────────────────────────────────
function AlertBanner({ alerts }) {
  if (!alerts || !alerts.length) return null;
  const critical = alerts.filter(a => (a.severity || '').toLowerCase() === 'critical');
  if (!critical.length) return null;
  const preview = critical.slice(0, 2).map(a => a.message).join(' · ');
  const truncated = preview.length > 120 ? preview.slice(0, 120) + '…' : preview;
  return React.createElement('div', {
    style: { border: '1px solid var(--fail)', background: 'var(--fail-soft)', borderRadius: 8, padding: '12px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }
  },
    React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 10, flex: 1 } },
      React.createElement('span', { style: { fontSize: 18 } }, '⚠'),
      React.createElement('span', { style: { fontSize: 13, color: 'var(--fail)' } },
        critical.length + ' critical violation' + (critical.length > 1 ? 's' : '') + ' detected — ' + truncated
      )
    ),
    React.createElement('span', { className: 'tv-chip fail', style: { fontSize: 11, padding: '3px 10px', flexShrink: 0 } },
      alerts.length + ' ACTIVE ALERT' + (alerts.length > 1 ? 'S' : '')
    )
  );
}

// ── Regime Bar ─────────────────────────────────────────────────────────────
function RegimeBar({ label, data }) {
  const [expanded, setExpanded] = useABState(false);
  if (!data) return null;
  const bull     = Number(data.bull     || 0);
  const bear     = Number(data.bear     || 0);
  const sideways = Number(data.sideways || 0);
  const total    = bull + bear + sideways || 100;
  const bPct = bull     / total * 100;
  const sPct = sideways / total * 100;
  const rPct = bear     / total * 100;
  const dominant = bull >= bear && bull >= sideways ? { label: 'Bull ' + bull + '%', cls: 'ok' }
    : bear >= sideways ? { label: 'Bear ' + bear + '%', cls: 'fail' }
    : { label: 'Sideways ' + sideways + '%', cls: 'warn' };

  return React.createElement('div', { style: { marginBottom: 14 } },
    React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 } },
      React.createElement('span', { style: { fontSize: 12, color: 'var(--text2)', fontWeight: 600 } }, label),
      React.createElement('span', { className: `tv-chip ${dominant.cls}`, style: { fontSize: 10, padding: '2px 8px' } }, dominant.label)
    ),
    React.createElement('div', {
      style: { display: 'flex', height: 10, borderRadius: 5, overflow: 'hidden', cursor: 'pointer', gap: 1 },
      onClick: () => setExpanded(e => !e),
    },
      React.createElement('div', { style: { width: bPct + '%', background: 'var(--ok)',   minWidth: bPct > 0 ? 2 : 0 } }),
      React.createElement('div', { style: { width: sPct + '%', background: 'var(--warn)', minWidth: sPct > 0 ? 2 : 0 } }),
      React.createElement('div', { style: { width: rPct + '%', background: 'var(--fail)', minWidth: rPct > 0 ? 2 : 0 } })
    ),
    React.createElement('div', { style: { display: 'flex', gap: 12, marginTop: 5, fontSize: 11, color: 'var(--text4)' } },
      React.createElement('span', { className: 'ok' },  'Bull '     + bull     + '%'),
      React.createElement('span', { className: 'warn' }, 'Sideways ' + sideways + '%'),
      React.createElement('span', { className: 'fail' }, 'Bear '     + bear     + '%'),
      React.createElement('button', { onClick: () => setExpanded(e => !e), style: { marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text4)', fontSize: 11 } }, expanded ? '▴' : '▾ reasoning')
    ),
    expanded && data.reasoning && React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', fontStyle: 'italic', marginTop: 6, lineHeight: 1.6, paddingLeft: 4 } }, data.reasoning)
  );
}

// ── Market Regime Card ─────────────────────────────────────────────────────
function MarketRegimeCard({ regime }) {
  return React.createElement('div', { className: 'tv-card', style: { flex: 1, padding: 20 } },
    React.createElement('div', { style: { fontSize: 12, color: 'var(--accent)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 14 } }, 'Market Regime Assessment'),
    regime
      ? React.createElement('div', null,
          React.createElement(RegimeBar, { label: 'Short-term (7D)', data: regime.short_term_7d }),
          React.createElement(RegimeBar, { label: 'Mid-term (30D)',  data: regime.mid_term_30d }),
          regime.macro_environment && React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', fontStyle: 'italic', marginTop: 10, lineHeight: 1.6 } }, regime.macro_environment),
          regime.data_confidence && React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginTop: 6 } }, 'Confidence: ' + regime.data_confidence)
        )
      : React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'No regime data')
  );
}

// ── Portfolio Status Card ──────────────────────────────────────────────────
const PLAYBOOK_ROWS = [
  { category: 'BTC (treasury)',    target: '15–20%' },
  { category: 'ETH deployment',    target: '≥15%' },
  { category: 'LP deployed',       target: '15–25%' },
  { category: 'Stablecoins (idle)', target: '15–20%' },
];

function extractPct(text) {
  if (!text) return null;
  const m = text.match(/(\d+(?:\.\d+)?)\s*%/);
  return m ? m[1] + '%' : null;
}

function statusChip(text) {
  const t = (text || '').toLowerCase();
  if (t.includes('critical')) return React.createElement('span', { className: 'tv-chip fail', style: { fontSize: 10, padding: '2px 7px' } }, 'CRITICAL');
  if (t.includes('flag'))     return React.createElement('span', { className: 'tv-chip warn', style: { fontSize: 10, padding: '2px 7px' } }, 'FLAG');
  if (t.includes('review'))   return React.createElement('span', { className: 'tv-chip warn', style: { fontSize: 10, padding: '2px 7px' } }, 'REVIEW');
  if (t.includes('over'))     return React.createElement('span', { className: 'tv-chip adapt',style: { fontSize: 10, padding: '2px 7px' } }, 'OVER');
  return React.createElement('span', { className: 'tv-chip ok', style: { fontSize: 10, padding: '2px 7px' } }, 'OK');
}

function PortfolioStatusCard({ assessment }) {
  if (!assessment) return React.createElement('div', { className: 'tv-card', style: { flex: 1, padding: 20 } },
    React.createElement('div', { style: { fontSize: 12, color: 'var(--accent)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 12 } }, 'Portfolio Status'),
    React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'No data')
  );

  const concerns  = assessment.concerns  || [];
  const strengths = assessment.strengths || [];
  const allText   = [...concerns, ...strengths];

  const rows = PLAYBOOK_ROWS.map(row => {
    const match = allText.find(t => t.toLowerCase().includes(row.category.split(' ')[0].toLowerCase()));
    const actual = match ? extractPct(match) : null;
    return { ...row, actual, statusText: match || '' };
  });

  const canShowTable = rows.some(r => r.actual);

  return React.createElement('div', { className: 'tv-card', style: { flex: 1, padding: 20 } },
    React.createElement('div', { style: { fontSize: 12, color: 'var(--accent)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 14 } }, 'Portfolio Status'),
    canShowTable
      ? React.createElement('div', null,
          React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1.5fr 1fr 1fr auto', gap: '0 12px', fontSize: 10, color: 'var(--text4)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 } },
            React.createElement('div', null, 'Category'),
            React.createElement('div', null, 'Target'),
            React.createElement('div', null, 'Actual'),
            React.createElement('div', null, 'Status')
          ),
          rows.map((r, i) =>
            React.createElement('div', { key: i, style: { display: 'grid', gridTemplateColumns: '1.5fr 1fr 1fr auto', gap: '0 12px', borderTop: '1px solid var(--line)', padding: '6px 0', alignItems: 'center' } },
              React.createElement('div', { style: { fontSize: 12, color: 'var(--text2)' } }, r.category),
              React.createElement('div', { style: { fontSize: 12, fontFamily: 'Fira Code', color: 'var(--text4)' } }, r.target),
              React.createElement('div', { style: { fontSize: 12, fontFamily: 'Fira Code', color: 'var(--text)' } }, r.actual || '—'),
              statusChip(r.statusText)
            )
          )
        )
      : React.createElement('div', { style: { fontSize: 13, color: 'var(--text2)', lineHeight: 1.7 } }, assessment.summary || 'No assessment available'),
    assessment.summary && canShowTable && React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', fontStyle: 'italic', marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--line)', lineHeight: 1.6 } }, assessment.summary)
  );
}

// ── Recommendations ────────────────────────────────────────────────────────
function RecommendationCard({ rec, index }) {
  const [expanded, setExpanded] = useABState(false);
  const firstSentence = (rec.action || '').split(/[.!?]/)[0].trim();
  const tagWords = (rec.action || '').split(/\s+/).slice(0, 3).join(' ');

  return React.createElement('div', {
    className: 'tv-card-2',
    style: { borderLeft: '3px solid ' + priorityBorder(rec.priority), padding: '14px 18px', cursor: 'pointer', marginBottom: 10 },
    onClick: () => setExpanded(e => !e),
  },
    React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 } },
      React.createElement('span', { style: { fontSize: 12, color: 'var(--text4)', fontFamily: 'Fira Code' } }, '#' + (index + 1)),
      priorityChip(rec.priority),
      rec.deadline && deadlineChip(rec.deadline),
      React.createElement('span', { style: { marginLeft: 'auto', fontSize: 11 } },
        React.createElement('span', { className: 'tv-chip adapt', style: { fontSize: 10, padding: '2px 7px' } }, tagWords)
      )
    ),
    React.createElement('div', { style: { fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 6, lineHeight: 1.4 } }, firstSentence || rec.action),
    rec.action && rec.action !== firstSentence && React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)', lineHeight: 1.6, marginBottom: 6 } }, rec.action),
    rec.impact && React.createElement('div', { style: { fontSize: 13, color: 'var(--accent)', fontStyle: 'italic' } }, '↳ ' + rec.impact),
    expanded && rec.rationale && React.createElement('div', { style: { marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--line)', fontSize: 13, color: 'var(--text4)', lineHeight: 1.7 } }, rec.rationale)
  );
}

function RecommendationsSection({ recs }) {
  if (!recs || !recs.length) return null;
  return React.createElement('div', null,
    React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 } },
      React.createElement('div', { style: { fontSize: 13, color: 'var(--accent)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em' } }, 'Recommendations'),
      React.createElement('span', { className: 'tv-label', style: { color: 'var(--text4)' } }, 'NOT FINANCIAL ADVICE — USE YOUR OWN JUDGEMENT')
    ),
    recs.map((r, i) => React.createElement(RecommendationCard, { key: i, rec: r, index: i }))
  );
}

// ── Market Analysis + Risk Alerts ──────────────────────────────────────────
function MarketAnalysisCard({ analysis }) {
  const metrics = (analysis && analysis.key_metrics) || [];
  const summary = analysis && analysis.summary;

  return React.createElement('div', { className: 'tv-card', style: { flex: 1, padding: 20 } },
    React.createElement('div', { style: { fontSize: 12, color: 'var(--accent)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 14 } }, 'Market Analysis'),
    metrics.length > 0
      ? React.createElement('div', null,
          React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1fr auto 1.5fr', gap: '0 14px', fontSize: 10, color: 'var(--text4)', fontWeight: 700, letterSpacing: '0.06em', marginBottom: 6 } },
            React.createElement('div', null, 'METRIC'),
            React.createElement('div', { style: { textAlign: 'right' } }, 'VALUE'),
            React.createElement('div', null, 'INTERPRETATION')
          ),
          metrics.map((m, i) =>
            React.createElement('div', { key: i, style: { display: 'grid', gridTemplateColumns: '1fr auto 1.5fr', gap: '0 14px', borderTop: '1px solid var(--line)', padding: '6px 0', alignItems: 'start' } },
              React.createElement('div', { style: { fontSize: 12, color: 'var(--text2)' } }, m.metric),
              React.createElement('div', { style: { fontSize: 12, fontFamily: 'Fira Code', color: metricValColor(m.value), textAlign: 'right', whiteSpace: 'nowrap' } }, m.value != null ? String(m.value) : '—'),
              React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', lineHeight: 1.4 } }, m.interpretation || '')
            )
          )
        )
      : React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'No metrics available'),
    summary && React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)', lineHeight: 1.7, marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--line)' } }, summary)
  );
}

function RiskAlertsCard({ alerts }) {
  return React.createElement('div', { className: 'tv-card', style: { flex: 1, padding: 20 } },
    React.createElement('div', { style: { fontSize: 12, color: 'var(--accent)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 14 } }, 'Risk Alerts'),
    (!alerts || !alerts.length)
      ? React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'No active alerts')
      : React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
          alerts.map((a, i) =>
            React.createElement('div', { key: i, style: { display: 'flex', alignItems: 'flex-start', gap: 10 } },
              severityChip(a.severity),
              React.createElement('span', { style: { fontSize: 13, color: 'var(--text2)', lineHeight: 1.5 } }, a.message || '')
            )
          )
        )
  );
}

// ── Housekeeping ───────────────────────────────────────────────────────────
function HousekeepingSection({ items }) {
  const [open, setOpen] = useABState(false);
  if (!items || !items.length) return null;
  const sorted = [...items].sort((a, b) => deadlineOrder(a.deadline) - deadlineOrder(b.deadline));
  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', {
      style: { display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', userSelect: 'none' },
      onClick: () => setOpen(o => !o),
    },
      React.createElement('span', { style: { fontSize: 13, fontWeight: 700, color: 'var(--text)' } }, 'Housekeeping'),
      React.createElement('span', { className: 'tv-chip adapt', style: { fontSize: 10, padding: '1px 7px' } }, items.length),
      React.createElement('span', { style: { marginLeft: 'auto', fontSize: 13, color: 'var(--text4)' } }, open ? '▴' : '▾')
    ),
    open && React.createElement('div', { style: { marginTop: 14, display: 'flex', flexDirection: 'column', gap: 0 } },
      sorted.map((item, i) =>
        React.createElement('div', { key: i, style: { display: 'flex', alignItems: 'flex-start', gap: 10, borderTop: '1px solid var(--line)', padding: '8px 0' } },
          deadlineChip(item.deadline),
          React.createElement('span', { style: { fontSize: 13, color: 'var(--text2)', lineHeight: 1.5 } }, item.action || '')
        )
      )
    )
  );
}

// ── Saved Reports ──────────────────────────────────────────────────────────
function SavedReports({ reports, activeId, onSelect }) {
  if (!reports || !reports.length) return null;
  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { style: { fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 14 } }, 'Previous Reports'),
    reports.map((r, i) =>
      React.createElement('div', { key: r.id || i,
        style: {
          display: 'flex', alignItems: 'center', gap: 12, padding: '8px 10px', borderTop: '1px solid var(--line)',
          borderRadius: 6, cursor: 'pointer',
          background: r.id === activeId ? 'var(--panel3)' : 'transparent',
        },
        onClick: () => onSelect(r.id),
      },
        React.createElement('span', { style: { fontSize: 12, color: 'var(--text2)', flex: 1 } }, fmtABDate(r.timestamp || r.created_at)),
        alignmentChip(r.portfolio_alignment || r.alignment),
        React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)' } }, r.model || ''),
        React.createElement('button', {
          className: 'tv-btn', style: { fontSize: 11, padding: '2px 10px' },
          onClick: e => { e.stopPropagation(); onSelect(r.id); }
        }, 'View')
      )
    )
  );
}

// ── Empty / Loading States ─────────────────────────────────────────────────
function SkeletonCard({ height }) {
  return React.createElement('div', { className: 'tv-card', style: { padding: 20, height: height || 120 } },
    React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…')
  );
}

// ── Main Screen ────────────────────────────────────────────────────────────
function AIBriefScreen({ hideValues, setActiveTab }) {
  const [reports,              setReports]              = useABState([]);
  const [activeId,             setActiveId]             = useABState(null);
  const [report,               setReport]               = useABState(null);
  const [loading,              setLoading]              = useABState(true);
  const [generating,           setGenerating]           = useABState(false);
  const [generateError,        setGenerateError]        = useABState('');
  const [showPromptModal,      setShowPromptModal]      = useABState(false);
  const [promptText,           setPromptText]           = useABState('');
  const [promptSaving,         setPromptSaving]         = useABState(false);
  const [promptSaved,          setPromptSaved]          = useABState(false);
  const [dailyBrief,           setDailyBrief]           = useABState(null);
  const [dailyBriefGenerating, setDailyBriefGenerating] = useABState(false);

  function fetchReports(selectId) {
    setLoading(true);
    api('/api/ai/reports')
      .then(list => {
        const arr = Array.isArray(list) ? list : [];
        setReports(arr);
        const id = selectId != null ? selectId : (arr.length ? arr[0].id : null);
        if (id != null) {
          setActiveId(id);
          return api(`/api/ai/reports/${id}`);
        }
        return null;
      })
      .then(detail => { if (detail) setReport(detail); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  function selectReport(id) {
    setActiveId(id);
    api(`/api/ai/reports/${id}`).then(d => setReport(d)).catch(() => {});
  }

  function fetchDailyBrief() {
    api('/api/ai/daily-brief/latest')
      .then(d => { if (d && d.brief_text) setDailyBrief(d); })
      .catch(() => {});
  }

  useABEffect(() => { fetchReports(); fetchDailyBrief(); }, []);

  async function handleGenerate() {
    if (generating) return;
    setGenerating(true); setGenerateError('');
    try {
      await api('/api/ai/generate', { method: 'POST' });
      fetchReports();
    } catch (e) {
      setGenerateError('Generation failed — check AI config');
    } finally { setGenerating(false); }
  }

  async function handleOpenPrompt() {
    setShowPromptModal(true);
    try {
      const d = await api('/api/ai/prompt');
      setPromptText(d.prompt || '');
    } catch (e) {}
  }

  async function handleSavePrompt() {
    setPromptSaving(true);
    try {
      await api('/api/ai/prompt', { method: 'POST', body: JSON.stringify({ prompt: promptText }) });
      setPromptSaved(true);
      setTimeout(() => { setPromptSaved(false); setShowPromptModal(false); }, 1200);
    } catch (e) {}
    finally { setPromptSaving(false); }
  }

  async function handleDailyDigest() {
    if (dailyBriefGenerating) return;
    setDailyBriefGenerating(true);
    try {
      await api('/api/ai/daily-brief', { method: 'POST' });
      fetchDailyBrief();
    } catch (e) {}
    finally { setDailyBriefGenerating(false); }
  }

  const frj          = report && report.full_report_json;
  const regime       = frj && frj.market_regime;
  const assessment   = frj && frj.portfolio_assessment;
  const recs         = (frj && frj.recommendations) || [];
  const alerts       = (frj && frj.risk_alerts)      || [];
  const analysis     = frj && frj.market_analysis;
  const housekeeping = (frj && frj.housekeeping)     || [];

  const headerBarProps = {
    report, onGenerate: handleGenerate, generating, generateError,
    onOpenPrompt: handleOpenPrompt, onDailyDigest: handleDailyDigest, dailyBriefGenerating,
  };

  if (!loading && !reports.length) {
    return React.createElement('div', { style: { padding: 24, display: 'flex', flexDirection: 'column', gap: 20 } },
      React.createElement(HeaderBar, headerBarProps),
      dailyBrief && React.createElement(DailyBriefCard, { brief: dailyBrief }),
      React.createElement('div', { style: { marginTop: 24, display: 'flex', justifyContent: 'center' } },
        React.createElement('div', { className: 'tv-card', style: { padding: 40, textAlign: 'center', maxWidth: 420 } },
          React.createElement('div', { style: { fontSize: 15, color: 'var(--text4)', marginBottom: 16 } }, 'No reports generated yet'),
          React.createElement('button', {
            className: 'tv-btn primary', style: { fontSize: 13, padding: '8px 24px' },
            onClick: handleGenerate, disabled: generating,
          }, generating ? '↺ Generating…' : '↺ Generate Report'),
          generateError && React.createElement('div', { style: { fontSize: 12, color: 'var(--fail)', marginTop: 10 } }, generateError)
        )
      ),
      showPromptModal && React.createElement(PromptModal, {
        text: promptText, onChange: setPromptText,
        saving: promptSaving, saved: promptSaved,
        onSave: handleSavePrompt, onClose: () => setShowPromptModal(false),
      })
    );
  }

  return React.createElement('div', { style: { padding: 24, display: 'flex', flexDirection: 'column', gap: 20 } },

    React.createElement(HeaderBar, headerBarProps),

    loading && React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 16 } },
      React.createElement('div', { style: { display: 'flex', gap: 16 } },
        React.createElement(SkeletonCard, { height: 180 }),
        React.createElement(SkeletonCard, { height: 180 })
      ),
      React.createElement(SkeletonCard, { height: 220 }),
      React.createElement(SkeletonCard, { height: 140 })
    ),

    !loading && report && React.createElement(React.Fragment, null,

      // Daily brief above alert banner
      React.createElement(DailyBriefCard, { brief: dailyBrief }),

      React.createElement(AlertBanner, { alerts }),

      React.createElement('div', { style: { display: 'flex', gap: 16 } },
        React.createElement(MarketRegimeCard, { regime }),
        React.createElement(PortfolioStatusCard, { assessment })
      ),

      React.createElement(RecommendationsSection, { recs }),

      React.createElement('div', { style: { display: 'flex', gap: 16 } },
        React.createElement(MarketAnalysisCard, { analysis }),
        React.createElement(RiskAlertsCard, { alerts })
      ),

      React.createElement(HousekeepingSection, { items: housekeeping }),
    ),

    !loading && React.createElement(SavedReports, { reports, activeId, onSelect: selectReport }),

    showPromptModal && React.createElement(PromptModal, {
      text: promptText, onChange: setPromptText,
      saving: promptSaving, saved: promptSaved,
      onSave: handleSavePrompt, onClose: () => setShowPromptModal(false),
    })
  );
}

window.AIBriefScreen = AIBriefScreen;
