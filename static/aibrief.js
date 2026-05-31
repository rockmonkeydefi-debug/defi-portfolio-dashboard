/* ===== AI BRIEF SCREEN ===== */

const { useState: useABState, useEffect: useABEffect } = React;

function _alertCls(type) {
  const t = (type || '').toLowerCase();
  if (t === 'danger' || t === 'error') return 'fail';
  if (t === 'warning' || t === 'warn') return 'warn';
  return 'adapt';
}

function _actionCls(action) {
  const a = (action || '').toLowerCase();
  if (a === 'buy') return 'ok';
  if (a === 'avoid' || a === 'sell') return 'fail';
  return 'warn';
}

// ── Report Modal ───────────────────────────────────────────────────────────
function ReportModal({ reportId, onClose }) {
  const [content, setContent] = useABState(null);
  const [loading, setLoading] = useABState(true);

  useABEffect(() => {
    api(`/api/ai/reports/${reportId}`)
      .then(d => setContent(d))
      .catch(() => setContent({ error: 'Failed to load report' }))
      .finally(() => setLoading(false));
  }, [reportId]);

  return React.createElement('div', {
    style: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 },
    onClick: onClose,
  },
    React.createElement('div', {
      className: 'tv-card',
      style: { maxWidth: 720, width: '100%', maxHeight: '80vh', overflowY: 'auto', padding: 28 },
      onClick: e => e.stopPropagation(),
    },
      React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 } },
        React.createElement('span', { className: 'tv-label' }, 'Report Detail'),
        React.createElement('button', { className: 'tv-btn', style: { fontSize: 12, padding: '3px 10px' }, onClick: onClose }, '✕ Close')
      ),
      loading
        ? React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…')
        : content && content.error
          ? React.createElement('span', { style: { color: 'var(--fail)', fontSize: 13 } }, content.error)
          : React.createElement('div', { style: { fontSize: 14, color: 'var(--text2)', lineHeight: 1.7, whiteSpace: 'pre-wrap', fontFamily: 'Fira Code' } },
              typeof content === 'string' ? content : JSON.stringify(content, null, 2)
            )
    )
  );
}

// ── Digest View ────────────────────────────────────────────────────────────
function DigestView({ digest, onRegenerate, regenerating }) {
  const btnStyle = {
    fontSize: 12, padding: '4px 12px',
    background: regenerating ? 'var(--panel3)' : 'var(--accent)',
    color: regenerating ? 'var(--text4)' : '#000',
    border: 'none',
  };

  if (!digest) {
    return React.createElement('div', { className: 'tv-card', style: { padding: 36, textAlign: 'center' } },
      React.createElement('div', { style: { fontSize: 14, color: 'var(--text4)', marginBottom: 16 } }, 'No brief generated yet'),
      React.createElement('button', { className: 'tv-btn', style: { ...btnStyle, fontSize: 14, padding: '8px 24px' }, onClick: onRegenerate, disabled: regenerating },
        regenerating ? '⟳ Generating…' : '⟳ Generate Brief'
      )
    );
  }

  // Free-text digest
  if (typeof digest === 'string') {
    return React.createElement('div', { className: 'tv-card', style: { padding: 24 } },
      React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 } },
        React.createElement('span', { className: 'tv-label' }, 'AI Brief'),
        React.createElement('button', { className: 'tv-btn', style: btnStyle, onClick: onRegenerate, disabled: regenerating },
          regenerating ? '⟳ Regenerating…' : '⟳ Regenerate'
        )
      ),
      React.createElement('div', { style: { fontSize: 14, color: 'var(--text2)', lineHeight: 1.8, whiteSpace: 'pre-wrap' } }, digest)
    );
  }

  const { date, generated_at, top_recommendation, alerts = [], portfolio_analysis, macro_context, recommendations = [], data_sources = [] } = digest;
  const dateStr = date || generated_at;
  const formattedDate = dateStr ? new Date(dateStr).toLocaleString() : '';

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 16 } },
    // Header
    React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
      React.createElement('div', null,
        React.createElement('span', { className: 'tv-label' }, 'AI Brief'),
        formattedDate && React.createElement('span', { style: { fontSize: 12, color: 'var(--text4)', marginLeft: 12 } }, formattedDate)
      ),
      React.createElement('button', { className: 'tv-btn', style: btnStyle, onClick: onRegenerate, disabled: regenerating },
        regenerating ? '⟳ Regenerating…' : '⟳ Regenerate'
      )
    ),

    // Top Recommendation
    top_recommendation && React.createElement('div', { className: 'tv-card', style: { padding: 24, borderColor: 'var(--accent)', borderWidth: 2 } },
      React.createElement('div', { style: { fontSize: 11, color: 'var(--accent)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 } }, 'Top Recommendation'),
      React.createElement('div', { style: { fontSize: 16, color: 'var(--text)', lineHeight: 1.6 } },
        typeof top_recommendation === 'string' ? top_recommendation : (top_recommendation.text || top_recommendation.summary || JSON.stringify(top_recommendation))
      )
    ),

    // Alerts
    alerts.length > 0 && React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      React.createElement('div', { className: 'tv-label', style: { marginBottom: 12 } }, 'Alerts'),
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
        alerts.map((a, i) =>
          React.createElement('div', { key: i, style: { display: 'flex', alignItems: 'flex-start', gap: 10 } },
            React.createElement('span', { className: `tv-chip ${_alertCls(a.type || a.severity)}`, style: { fontSize: 11, padding: '2px 8px', flexShrink: 0 } }, a.type || a.severity || 'Info'),
            React.createElement('span', { style: { fontSize: 13, color: 'var(--text2)', lineHeight: 1.5 } }, a.message || a.text || String(a))
          )
        )
      )
    ),

    // Portfolio Analysis
    portfolio_analysis && React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      React.createElement('div', { className: 'tv-label', style: { marginBottom: 10 } }, 'Portfolio Analysis'),
      React.createElement('div', { style: { fontSize: 14, color: 'var(--text2)', lineHeight: 1.8 } }, portfolio_analysis)
    ),

    // Macro Context
    macro_context && React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      React.createElement('div', { className: 'tv-label', style: { marginBottom: 10 } }, 'Macro Context'),
      React.createElement('div', { style: { fontSize: 14, color: 'var(--text2)', lineHeight: 1.8 } }, macro_context)
    ),

    // Recommendations
    recommendations.length > 0 && React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      React.createElement('div', { className: 'tv-label', style: { marginBottom: 12 } }, 'Recommendations'),
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 0 } },
        recommendations.map((r, i) =>
          React.createElement('div', { key: i, style: { display: 'flex', alignItems: 'flex-start', gap: 12, padding: '10px 0', borderTop: i > 0 ? '1px solid var(--line)' : 'none' } },
            React.createElement('span', { className: `tv-chip ${_actionCls(r.action)}`, style: { fontSize: 11, padding: '2px 8px', flexShrink: 0 } }, r.action || 'Note'),
            React.createElement('div', null,
              r.asset && React.createElement('div', { style: { fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 2 } }, r.asset),
              React.createElement('div', { style: { fontSize: 13, color: 'var(--text2)', lineHeight: 1.5 } }, r.rationale || r.text || String(r))
            )
          )
        )
      )
    ),

    // Data sources
    data_sources.length > 0 && React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)' } },
      'Data sources: ' + data_sources.join(', ')
    ),
  );
}

// ── Saved Reports ──────────────────────────────────────────────────────────
function SavedReports({ reports, loading }) {
  const [selectedId, setSelectedId] = useABState(null);
  if (loading || !reports.length) return null;
  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    selectedId != null && React.createElement(ReportModal, { reportId: selectedId, onClose: () => setSelectedId(null) }),
    React.createElement('div', { className: 'tv-label', style: { marginBottom: 12 } }, 'Saved Reports'),
    reports.map((r, i) =>
      React.createElement('div', {
        key: r.id != null ? r.id : i,
        onClick: () => setSelectedId(r.id),
        style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 0', cursor: 'pointer', borderTop: i > 0 ? '1px solid var(--line)' : 'none' },
      },
        React.createElement('div', null,
          React.createElement('div', { style: { fontSize: 13, color: 'var(--text2)' } }, r.title || r.summary || `Report ${i + 1}`),
          r.created_at && React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginTop: 2 } }, new Date(r.created_at).toLocaleDateString())
        ),
        React.createElement('span', { style: { fontSize: 12, color: 'var(--accent)' } }, '→')
      )
    )
  );
}

// ── Main Screen ────────────────────────────────────────────────────────────
function AIBriefScreen({ hideValues }) {
  const [digest, setDigest] = useABState(null);
  const [digestLoading, setDigestLoading] = useABState(true);
  const [regenerating, setRegenerating] = useABState(false);
  const [reports, setReports] = useABState([]);
  const [reportsLoading, setReportsLoading] = useABState(true);

  function fetchDigest() {
    setDigestLoading(true);
    api('/api/ai/digest/latest')
      .then(d => setDigest(d))
      .catch(() => setDigest(null))
      .finally(() => setDigestLoading(false));
  }

  useABEffect(() => {
    fetchDigest();
    api('/api/ai/reports')
      .then(d => setReports(Array.isArray(d) ? d : []))
      .catch(() => setReports([]))
      .finally(() => setReportsLoading(false));
  }, []);

  async function handleRegenerate() {
    if (regenerating) return;
    setRegenerating(true);
    try {
      await api('/api/ai/digest', { method: 'POST' });
    } catch (e) {}
    fetchDigest();
    setRegenerating(false);
  }

  return React.createElement('div', { style: { padding: 24, display: 'flex', flexDirection: 'column', gap: 20, maxWidth: 800 } },
    digestLoading
      ? React.createElement('div', { className: 'tv-card', style: { padding: 24 } },
          React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading brief…')
        )
      : React.createElement(DigestView, { digest, onRegenerate: handleRegenerate, regenerating }),
    React.createElement(SavedReports, { reports, loading: reportsLoading })
  );
}

window.AIBriefScreen = AIBriefScreen;
