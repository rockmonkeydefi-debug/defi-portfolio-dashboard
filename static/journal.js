/* ===== JOURNAL SCREEN ===== */

const { useState: useJS, useEffect: useJE, useMemo: useJM } = React;

const LIMIT = 20;

function JournalScreen({ onSwitchTab }) {
  const [entries, setEntries] = useJS([]);
  const [total, setTotal] = useJS(0);
  const [offset, setOffset] = useJS(0);
  const [loading, setLoading] = useJS(true);
  const [error, setError] = useJS(null);
  const [selectedEntry, setSelectedEntry] = useJS(null);
  const [fullPageId, setFullPageId] = useJS(null);
  const [fullPageData, setFullPageData] = useJS(null);
  const [editMode, setEditMode] = useJS(false);
  const [editBody, setEditBody] = useJS('');
  const [showNewForm, setShowNewForm] = useJS(false);
  const [activeFilter, setActiveFilter] = useJS('all');
  const [searchQuery, setSearchQuery] = useJS('');
  const [outcomeForm, setOutcomeForm] = useJS({ show: false, entryId: null, type: null, rMultiple: '', lesson: '' });
  const [savingOutcome, setSavingOutcome] = useJS(false);
  const [newForm, setNewForm] = useJS({ title: '', body: '', tags: '', mood: 3, entry_date: new Date().toISOString().slice(0,10) });
  const [savingNew, setSavingNew] = useJS(false);
  const [screenshots, setScreenshots] = useJS({});
  const [screenshotUploading, setScreenshotUploading] = useJS(null);

  function load(off = 0) {
    setError(null);
    api(`/api/trading/journal?limit=${LIMIT}&offset=${off}`)
      .then(r => {
        const rows = r.entries || [];
        setEntries(prev => off === 0 ? rows : [...prev, ...rows]);
        setTotal(r.total || 0);
        if (off > 0) setOffset(off);
        setLoading(false);
      })
      .catch(e => { setError(e.message); setLoading(false); });
  }

  useJE(() => { load(0); }, []);

  // Load full page data when fullPageId changes
  useJE(() => {
    if (!fullPageId) { setFullPageData(null); return; }
    const found = entries.find(e => e.id === fullPageId);
    if (found) { setFullPageData(found); return; }
    api(`/api/trading/journal/${fullPageId}`)
      .then(r => setFullPageData(r))
      .catch(() => { setFullPageId(null); });
  }, [fullPageId]);

  // Paste-to-upload: while an entry is open, Ctrl+V / ⌘V of an image uploads it
  // straight into that entry (reuses handleScreenshotUpload — clipboard items'
  // getAsFile() yields File objects, compatible with its FileList loop).
  useJE(function () {
    if (!selectedEntry) return;
    function handlePaste(ev) {
      var items = ev.clipboardData && ev.clipboardData.items;
      if (!items) return;
      var imageFiles = [];
      for (var i = 0; i < items.length; i++) {
        if (items[i].type.indexOf('image/') === 0) {
          var file = items[i].getAsFile();
          if (file) imageFiles.push(file);
        }
      }
      if (!imageFiles.length) return;
      ev.preventDefault();
      handleScreenshotUpload(selectedEntry.id, imageFiles);
    }
    document.addEventListener('paste', handlePaste);
    return function () { document.removeEventListener('paste', handlePaste); };
  }, [selectedEntry]);

  function selectEntry(e) {
    setSelectedEntry(e); setEditMode(false); setEditBody(e.body || '');
    loadScreenshots(e.id);
  }

  function loadScreenshots(entryId) {
    api(`/api/trading/journal/${entryId}/screenshots`)
      .then(data => setScreenshots(prev => ({ ...prev, [entryId]: data })))
      .catch(() => {});
  }

  async function handleScreenshotUpload(entryId, files) {
    if (!files || !files.length) return;
    setScreenshotUploading(entryId);
    for (const file of Array.from(files)) {
      try {
        const dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = ev => resolve(ev.target.result);
          reader.onerror = reject;
          reader.readAsDataURL(file);
        });
        const base64 = dataUrl.split(',')[1];
        const res = await api(`/api/trading/journal/${entryId}/screenshots`, {
          method: 'POST',
          body: JSON.stringify({ filename: file.name, data: base64, mime_type: file.type }),
        });
        setScreenshots(prev => ({
          ...prev,
          [entryId]: [...(prev[entryId] || []), { id: res.id, filename: file.name, mime_type: file.type, data: base64 }],
        }));
      } catch (err) { setError(err.message); }
    }
    setScreenshotUploading(null);
  }

  async function handleScreenshotDelete(entryId, shotId) {
    try {
      await api(`/api/trading/journal/${entryId}/screenshots/${shotId}`, { method: 'DELETE' });
      setScreenshots(prev => ({ ...prev, [entryId]: (prev[entryId] || []).filter(s => s.id !== shotId) }));
    } catch (err) { setError(err.message); }
  }

  async function handleEntryDelete(entryId) {
    if (!confirm('Delete this journal entry and all its screenshots? This cannot be undone.')) return;
    try {
      await api('/api/trading/journal/' + entryId, { method: 'DELETE' });
      setSelectedEntry(null);
      load(0);   // this component's list loader (no loadEntries fn exists)
    } catch (err) { setError(err.message); }
  }

  async function saveBodyEdit() {
    if (!selectedEntry) return;
    try {
      await api(`/api/trading/journal/${selectedEntry.id}`, {
        method: 'PUT', body: JSON.stringify({ body: editBody }),
      });
      const updated = { ...selectedEntry, body: editBody };
      setSelectedEntry(updated);
      setEntries(prev => prev.map(e => e.id === selectedEntry.id ? updated : e));
      setEditMode(false);
    } catch (e) { setError(e.message); }
  }

  async function markOutcome() {
    if (!outcomeForm.entryId) return;
    setSavingOutcome(true);
    try {
      const entry = entries.find(e => e.id === outcomeForm.entryId) || {};
      const append = outcomeForm.lesson ? `\n\n## Lesson\n${outcomeForm.lesson}` : '';
      await api(`/api/trading/journal/${outcomeForm.entryId}`, {
        method: 'PUT',
        body: JSON.stringify({
          outcome: outcomeForm.type,
          r_multiple: outcomeForm.rMultiple ? parseFloat(outcomeForm.rMultiple) : null,
          body: (entry.body || '') + append,
        }),
      });
      setOutcomeForm({ show: false, entryId: null, type: null, rMultiple: '', lesson: '' });
      load(0);
      if (selectedEntry?.id === outcomeForm.entryId) setSelectedEntry(prev => prev ? { ...prev, outcome: outcomeForm.type } : prev);
    } catch (e) { setError(e.message); }
    finally { setSavingOutcome(false); }
  }

  async function saveNewEntry() {
    if (!newForm.title.trim()) return;
    setSavingNew(true);
    try {
      await api('/api/trading/journal', {
        method: 'POST',
        body: JSON.stringify({ ...newForm, tags: newForm.tags.split(',').map(t=>t.trim()).filter(Boolean), mood: parseInt(newForm.mood) }),
      });
      setShowNewForm(false);
      setNewForm({ title: '', body: '', tags: '', mood: 3, entry_date: new Date().toISOString().slice(0,10) });
      load(0);
    } catch (e) { setError(e.message); }
    finally { setSavingNew(false); }
  }

  function reopenValidator(entry) {
    try {
      if (entry?.validator_answers_json) {
        sessionStorage.setItem('validator_draft', JSON.stringify({
          ticker: entry.ticker, direction: entry.direction, timeframe: entry.timeframe,
          answers: entry.validator_answers_json,
        }));
      }
    } catch (_) {}
    if (onSwitchTab) onSwitchTab('tt-validator');
  }

  function copyText(entry) {
    const text = [entry.title || '', '\n', entry.body || ''].join('');
    navigator.clipboard.writeText(text).catch(() => {});
  }

  // ─── DERIVED STATE ─────────────────────────────────────────────────────────

  const filtered = useJM(() => {
    let out = entries;
    if (activeFilter === 'trades') out = out.filter(e => e.ticker);
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      out = out.filter(e => (e.title||'').toLowerCase().includes(q) || (e.ticker||'').toLowerCase().includes(q) || (e.body||'').toLowerCase().includes(q));
    }
    return out;
  }, [entries, activeFilter, searchQuery]);

  const grouped = useJM(() => {
    const g = {};
    filtered.forEach(e => {
      const d = (e.entry_date || (e.created_at||'').slice(0,10)) || 'Unknown';
      (g[d] = g[d] || []).push(e);
    });
    return Object.entries(g).sort((a,b) => b[0].localeCompare(a[0]));
  }, [filtered]);

  const stats = useJM(() => {
    const wins = entries.filter(e=>e.outcome==='win').length;
    const losses = entries.filter(e=>e.outcome==='loss').length;
    const skipped = entries.filter(e=>e.outcome==='skip').length;
    const netR = entries.reduce((s,e) => s + (e.r_multiple||0), 0);
    return { wins, losses, skipped, netR };
  }, [entries]);

  // ─── HELPERS ───────────────────────────────────────────────────────────────

  function fmtDate(d) {
    if (!d) return 'Unknown';
    const dt = new Date(d + 'T12:00:00');
    const today = new Date(); today.setHours(12,0,0,0);
    const yest = new Date(today); yest.setDate(today.getDate()-1);
    if (dt.toDateString()===today.toDateString()) return `TODAY · ${dt.toLocaleDateString('en-US',{month:'short',day:'numeric'})}`;
    if (dt.toDateString()===yest.toDateString()) return `YESTERDAY · ${dt.toLocaleDateString('en-US',{month:'short',day:'numeric'})}`;
    return dt.toLocaleDateString('en-US',{weekday:'short',month:'short',day:'numeric'}).toUpperCase();
  }

  function ocStyle(outcome) {
    if (outcome==='win')  return { color:'var(--ok)',   bg:'var(--ok-soft)',   border:'1px solid var(--ok)' };
    if (outcome==='loss') return { color:'var(--fail)', bg:'var(--fail-soft)', border:'1px solid var(--fail)' };
    if (outcome==='skip') return { color:'var(--text4)', bg:'var(--panel2)', border:'1px solid var(--line)' };
    return { color:'var(--adapt)', bg:'var(--adapt-soft)', border:'1px solid var(--adapt)' };
  }

  function ocLabel(e) {
    const r = e.r_multiple;
    if (e.outcome==='win')  return `● win${r ? ' +'+r+'R' : ''}`;
    if (e.outcome==='loss') return `● loss${r ? ' -'+Math.abs(r)+'R' : ''}`;
    if (e.outcome==='skip') return '● skipped';
    return '● open';
  }

  function parseSections(body) {
    if (!body) return { intro: '', sections: [] };
    const idx = body.indexOf('\n## ');
    const intro = idx >= 0 ? body.slice(0, idx).trim() : body.trim();
    const rest = idx >= 0 ? body.slice(idx) : '';
    const sections = rest.split(/\n(?=## )/).map(p => {
      const lines = p.trim().split('\n');
      return lines[0].startsWith('## ') ? { title: lines[0].slice(3), body: lines.slice(1).join('\n').trim() } : null;
    }).filter(Boolean);
    return { intro, sections };
  }

  // ─── FULL PAGE VIEW ────────────────────────────────────────────────────────

  if (fullPageId) {
    if (!fullPageData) return React.createElement('div', { className: 'tv-label', style: { padding: 32 } }, 'Loading…');
    const e = fullPageData;
    const plan = e.execution_plan_json || {};
    const ocs = ocStyle(e.outcome);
    const { intro, sections } = parseSections(e.body);

    return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 14, padding: '16px 0' } },
      // Header
      React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 } },
        React.createElement('div', null,
          React.createElement('button', { style: { background:'none', border:'none', color:'var(--accent)', fontSize:13, cursor:'pointer', marginBottom:6 }, onClick: () => { setFullPageId(null); setFullPageData(null); } }, '← Back to Journal'),
          React.createElement('div', { style: { fontSize: 20, fontWeight: 700 } }, e.title || ''),
          React.createElement('div', { style: { display: 'flex', gap: 5, marginTop: 6, flexWrap: 'wrap' } },
            e.timeframe && React.createElement('span', { className: 'tv-chip' }, e.timeframe),
            e.direction && React.createElement('span', { className: e.direction==='long'?'tv-chip ok':'tv-chip fail' }, e.direction.toUpperCase()),
            e.ready_score && React.createElement('span', { className: 'tv-chip' }, `READY · ${e.ready_score}`),
            React.createElement('span', { style: { fontSize:11, padding:'2px 7px', borderRadius:10, ...ocs } }, ocLabel(e))
          )
        ),
        React.createElement('div', { style: { display: 'flex', gap: 6 } },
          e.validator_answers_json && React.createElement('button', { className: 'tv-btn', onClick: () => reopenValidator(e), style: { fontSize: 12 } }, '↺ Re-open validator'),
          React.createElement('button', { className: 'tv-btn', onClick: () => copyText(e), style: { fontSize: 12 } }, 'Copy as markdown')
        )
      ),

      // Thesis + plan
      React.createElement('div', { style: { display: 'flex', gap: 14, alignItems: 'flex-start', flexWrap: 'wrap' } },
        React.createElement('div', { className: 'tv-card', style: { flex: 1, minWidth: 200 } },
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 8 } }, 'Thesis'),
          intro
            ? React.createElement('div', { style: { fontSize: 15, lineHeight: 1.7, color: 'var(--text2)' } }, intro)
            : React.createElement('div', { style: { color: 'var(--text4)', fontSize: 13, fontStyle: 'italic' } }, 'No thesis written.')
        ),
        plan.entry && React.createElement('div', { className: 'tv-card', style: { width: 190, flexShrink: 0 } },
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 8 } }, 'Execution'),
          [['Entry',plan.entry],['Stop',plan.stop],['Target',plan.tp1],['Invalidation',plan.invalidation]].map(([lbl,val]) =>
            val && React.createElement('div', { key: lbl, style: { marginBottom: 7 } },
              React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', marginBottom: 1 } }, lbl),
              React.createElement('div', { style: { fontFamily: 'Fira Code, monospace', fontSize: 12 } }, val)
            )
          )
        )
      ),

      // Body sections
      sections.map((sec, i) =>
        React.createElement('div', { key: i, className: 'tv-card' },
          React.createElement('div', { style: { fontWeight: 600, fontSize: 13, marginBottom: 6 } }, sec.title),
          React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)', whiteSpace: 'pre-wrap', lineHeight: 1.6 } }, sec.body)
        )
      ),

      // Concepts
      e.concepts_json?.length > 0 && React.createElement('div', { className: 'tv-card' },
        React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 8 } }, 'Concepts'),
        React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 5 } },
          e.concepts_json.map(c => React.createElement('span', { key: c, className: 'tv-chip adapt' }, c))
        )
      ),

      // Outcome marking
      e.outcome === 'open' && React.createElement('div', { className: 'tv-card' },
        React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 10 } }, 'Mark Outcome'),
        React.createElement('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap' } },
          [['win','var(--ok)'],['loss','var(--fail)'],['skip','var(--text4)']].map(([type, color]) =>
            React.createElement('button', {
              key: type, className: 'tv-btn', style: { fontSize: 12, color, borderColor: color },
              onClick: () => setOutcomeForm({ show: true, entryId: e.id, type, rMultiple: '', lesson: '' }),
            }, `Mark as ${type}`)
          )
        ),
        outcomeForm.show && outcomeForm.entryId === e.id && React.createElement('div', { style: { marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 } },
          React.createElement('input', {
            className: 'tv-input', placeholder: 'R-multiple (e.g. 2.1)', value: outcomeForm.rMultiple, style: { width: 200 },
            onChange: ev => setOutcomeForm(p => ({ ...p, rMultiple: ev.target.value })),
          }),
          React.createElement('textarea', {
            className: 'tv-input', placeholder: 'Lesson learned (optional)', value: outcomeForm.lesson,
            rows: 2, style: { resize: 'vertical', fontFamily: 'inherit' },
            onChange: ev => setOutcomeForm(p => ({ ...p, lesson: ev.target.value })),
          }),
          React.createElement('div', { style: { display: 'flex', gap: 8 } },
            React.createElement('button', { className: 'tv-btn primary', disabled: savingOutcome, onClick: markOutcome }, savingOutcome ? 'Saving…' : 'Confirm'),
            React.createElement('button', { className: 'tv-btn', onClick: () => setOutcomeForm(p => ({ ...p, show: false })) }, 'Cancel')
          )
        )
      )
    );
  }

  // ─── TWO-COLUMN VIEW ───────────────────────────────────────────────────────

  if (loading && entries.length === 0) return React.createElement('div', { className: 'tv-label', style: { padding: 32 } }, 'Loading…');

  return React.createElement('div', { style: { display: 'flex', gap: 0, padding: '16px 0', alignItems: 'flex-start', minHeight: 400 } },

    // Left column — list
    React.createElement('div', { style: { width: 380, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 10, paddingRight: 16, borderRight: '1px solid var(--line)' } },
      // Header
      React.createElement('div', null,
        React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 } },
          React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.08em' } }, 'Journal · History'),
          React.createElement('button', { className: 'tv-btn primary', onClick: () => setShowNewForm(p => !p), style: { fontSize: 11, padding: '3px 10px' } }, showNewForm ? '✕' : '+ New')
        ),
        React.createElement('div', { style: { display: 'flex', gap: 10, fontSize: 11, color: 'var(--text4)', flexWrap: 'wrap' } },
          React.createElement('span', { style: { color: 'var(--ok)' } }, `${stats.wins}W`),
          React.createElement('span', { style: { color: 'var(--fail)' } }, `${stats.losses}L`),
          stats.skipped > 0 && React.createElement('span', null, `${stats.skipped} skip`),
          stats.netR !== 0 && React.createElement('span', { style: { color: stats.netR>=0?'var(--ok)':'var(--fail)' } }, `net ${stats.netR>=0?'+':''}${stats.netR.toFixed(1)}R`)
        )
      ),

      // Filter + search
      React.createElement('div', { style: { display: 'flex', gap: 5, alignItems: 'center' } },
        ['all','trades'].map(f =>
          React.createElement('button', {
            key: f, className: activeFilter===f?'tv-chip adapt':'tv-chip',
            onClick: () => setActiveFilter(f),
          }, f==='all'?`All (${entries.length})`:`Trades (${entries.filter(e=>e.ticker).length})`)
        ),
        React.createElement('input', {
          className: 'tv-input', placeholder: 'search…', value: searchQuery,
          style: { marginLeft: 'auto', width: 100, fontSize: 12, padding: '3px 8px' },
          onChange: e => setSearchQuery(e.target.value),
        })
      ),

      // New entry form
      showNewForm && React.createElement('div', { className: 'tv-card', style: { display: 'flex', flexDirection: 'column', gap: 7, padding: 12 } },
        React.createElement('input', { className: 'tv-input', placeholder: 'Title', value: newForm.title, onChange: e => setNewForm(p => ({ ...p, title: e.target.value })) }),
        React.createElement('input', { className: 'tv-input', type: 'date', value: newForm.entry_date, onChange: e => setNewForm(p => ({ ...p, entry_date: e.target.value })) }),
        React.createElement('textarea', { className: 'tv-input', placeholder: 'Notes…', value: newForm.body, rows: 3, style: { resize: 'vertical', fontFamily: 'inherit', fontSize: 12 }, onChange: e => setNewForm(p => ({ ...p, body: e.target.value })) }),
        React.createElement('input', { className: 'tv-input', placeholder: 'Tags (comma-separated)', value: newForm.tags, style: { fontSize: 12 }, onChange: e => setNewForm(p => ({ ...p, tags: e.target.value })) }),
        React.createElement('div', { style: { display: 'flex', gap: 6 } },
          React.createElement('button', { className: 'tv-btn primary', disabled: savingNew, onClick: saveNewEntry, style: { fontSize: 12 } }, savingNew ? 'Saving…' : 'Save'),
          React.createElement('button', { className: 'tv-btn', onClick: () => setShowNewForm(false), style: { fontSize: 12 } }, 'Cancel')
        )
      ),

      error && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 12 } }, error),

      // Entry list
      filtered.length === 0
        ? React.createElement('div', { className: 'tv-card', style: { textAlign: 'center', color: 'var(--text4)', padding: 24, fontSize: 13 } },
            entries.length === 0
              ? 'No journal entries yet. Complete the Validator to create your first entry.'
              : 'No entries match your filter.'
          )
        : React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 'calc(100vh - 300px)', overflowY: 'auto' } },
            grouped.map(([date, dayEntries]) =>
              React.createElement('div', { key: date },
                React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.07em', padding: '2px 0 6px', display: 'flex', justifyContent: 'space-between' } },
                  fmtDate(date),
                  React.createElement('span', null, dayEntries.length)
                ),
                dayEntries.map(e => {
                  const ocs = ocStyle(e.outcome);
                  const isSel = selectedEntry?.id === e.id;
                  return React.createElement('div', {
                    key: e.id, className: 'tv-card', onClick: () => selectEntry(e),
                    style: { cursor: 'pointer', padding: '8px 10px', marginBottom: 5, borderLeft: isSel ? '3px solid var(--accent)' : '3px solid transparent', background: isSel ? 'var(--panel2)' : undefined },
                  },
                    React.createElement('div', { style: { display: 'flex', alignItems: 'flex-start', gap: 8 } },
                      e.ticker && React.createElement('div', {
                        style: { width: 28, height: 28, borderRadius: '50%', background: 'var(--accent)', color: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700, flexShrink: 0 }
                      }, (e.ticker||'').slice(0,3)),
                      React.createElement('div', { style: { flex: 1, minWidth: 0 } },
                        React.createElement('div', { style: { fontWeight: 600, fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginBottom: 3 } }, e.title || '(untitled)'),
                        React.createElement('div', { style: { display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 3 } },
                          e.timeframe && React.createElement('span', { className: 'tv-chip', style: { fontSize: 9, padding: '1px 4px' } }, e.timeframe),
                          e.direction && React.createElement('span', { className: e.direction==='long'?'tv-chip ok':'tv-chip fail', style: { fontSize: 9, padding: '1px 4px' } }, e.direction.toUpperCase()),
                          e.ready_score && React.createElement('span', { className: 'tv-chip', style: { fontSize: 9, padding: '1px 4px' } }, e.ready_score),
                          React.createElement('span', { style: { fontSize: 9, padding: '1px 5px', borderRadius: 4, background: ocs.bg, color: ocs.color, border: ocs.border } }, ocLabel(e))
                        ),
                        e.body && React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
                          (e.body||'').replace(/#{1,6} /g, '').slice(0, 80))
                      ),
                      React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', flexShrink: 0 } },
                        e.created_at ? new Date(e.created_at).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'}) : '')
                    )
                  );
                })
              )
            ),
            total > (offset + LIMIT) && React.createElement('button', {
              className: 'tv-btn', style: { alignSelf: 'center', fontSize: 12 },
              onClick: () => load(offset + LIMIT),
            }, 'Load more')
          )
    ),

    // Right column — detail
    React.createElement('div', { style: { flex: 1, minWidth: 0, paddingLeft: 20 } },
      !selectedEntry
        ? React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 200, color: 'var(--text4)', fontSize: 13 } }, 'Select a journal entry to view details')
        : renderDetail()
    )
  );

  // ─── DETAIL PANEL ──────────────────────────────────────────────────────────

  function renderDetail() {
    const e = selectedEntry;
    const plan = e.execution_plan_json || {};
    const ocs = ocStyle(e.outcome);
    const { intro, sections } = parseSections(e.body);

    return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 12 } },
      // Header
      React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 } },
        React.createElement('div', null,
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 4 } }, 'Pre-Trade Reasoning'),
          React.createElement('div', { style: { fontSize: 16, fontWeight: 700 } }, e.title || ''),
          React.createElement('div', { style: { display: 'flex', gap: 5, marginTop: 6, flexWrap: 'wrap' } },
            e.timeframe && React.createElement('span', { className: 'tv-chip' }, e.timeframe),
            e.direction && React.createElement('span', { className: e.direction==='long'?'tv-chip ok':'tv-chip fail' }, e.direction.toUpperCase()),
            e.ready_score && React.createElement('span', { className: 'tv-chip' }, e.ready_score),
            React.createElement('span', { style: { fontSize: 11, padding: '2px 7px', borderRadius: 10, background: ocs.bg, color: ocs.color, border: ocs.border } }, ocLabel(e))
          )
        ),
        React.createElement('div', { style: { display: 'flex', gap: 6 } },
          React.createElement('button', {
            className: 'tv-btn',
            onClick: function() { handleEntryDelete(e.id); },
            style: { fontSize: 11, color: 'var(--fail)', borderColor: 'var(--fail)', marginRight: 8 }
          }, '🗑 Delete Entry'),
          e.validator_answers_json && React.createElement('button', { className: 'tv-btn', onClick: () => reopenValidator(e), style: { fontSize: 11 } }, '↺ Re-open validator'),
          React.createElement('button', { className: 'tv-btn', onClick: () => { setFullPageId(e.id); setFullPageData(e); }, style: { fontSize: 11 } }, 'Full page ↗')
        )
      ),

      // Thesis block
      (intro || !e.body) && React.createElement('div', { className: 'tv-card' },
        intro
          ? React.createElement('div', { style: { fontSize: 14, lineHeight: 1.7, color: 'var(--text2)' } }, intro)
          : React.createElement('div', { style: { color: 'var(--text4)', fontSize: 13, fontStyle: 'italic' } }, 'No thesis recorded.')
      ),

      // Execution plan
      (plan.entry || plan.stop) && React.createElement('div', { className: 'tv-card' },
        React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 8 } }, 'Execution Plan'),
        React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 } },
          [['Entry',plan.entry],['Stop',plan.stop],['Target 1',plan.tp1],['Target 2',plan.tp2]].filter(([,v])=>v).map(([lbl,val]) =>
            React.createElement('div', { key: lbl },
              React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', marginBottom: 2 } }, lbl),
              React.createElement('div', { style: { fontFamily: 'Fira Code, monospace', fontSize: 12, fontWeight: 600 } }, val)
            )
          )
        )
      ),

      // Concepts
      e.concepts_json?.length > 0 && React.createElement('div', { className: 'tv-card', style: { padding: '10px 14px' } },
        React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 6 } }, 'Concepts'),
        React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 5 } },
          e.concepts_json.map(c => React.createElement('span', { key: c, className: 'tv-chip adapt' }, c))
        )
      ),

      // Notes
      React.createElement('div', { className: 'tv-card' },
        React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 } },
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase' } }, 'Notes'),
          !editMode && React.createElement('button', { style: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 11, cursor: 'pointer' }, onClick: () => setEditMode(true) }, '✏ edit')
        ),
        editMode
          ? React.createElement('div', null,
              React.createElement('textarea', {
                className: 'tv-input', value: editBody, rows: 6,
                style: { width: '100%', resize: 'vertical', fontFamily: 'inherit', fontSize: 13 },
                onChange: ev => setEditBody(ev.target.value),
              }),
              React.createElement('div', { style: { display: 'flex', gap: 8, marginTop: 6 } },
                React.createElement('button', { className: 'tv-btn primary', onClick: saveBodyEdit, style: { fontSize: 12 } }, 'Save'),
                React.createElement('button', { className: 'tv-btn', onClick: () => setEditMode(false), style: { fontSize: 12 } }, 'Cancel')
              )
            )
          : React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)', whiteSpace: 'pre-wrap', lineHeight: 1.6 } },
              sections.length > 0 ? sections.map(s => `## ${s.title}\n${s.body}`).join('\n\n') : (e.body || '(no notes)'))
      ),

      // Screenshots
      React.createElement('div', { className: 'tv-card', style: { padding: '10px 14px' } },
        React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 } },
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase' } }, 'Screenshots'),
          React.createElement('label', { className: 'tv-btn', style: { fontSize: 11, cursor: 'pointer' } },
            '📷 Add Screenshot',
            React.createElement('input', {
              type: 'file', accept: 'image/*', multiple: true, style: { display: 'none' },
              onChange: ev => { handleScreenshotUpload(e.id, ev.target.files); ev.target.value = ''; },
            })
          )
        ),
        React.createElement('div',
          { style: { fontSize: 11, color: 'var(--text4)', marginBottom: 4 } },
          'Tip: Copy a screenshot and press Ctrl+V / ⌘V to paste directly.'
        ),
        screenshotUploading === e.id && React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', marginBottom: 6 } }, 'Uploading…'),
        (screenshots[e.id] || []).length > 0
          ? React.createElement('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap' } },
              (screenshots[e.id] || []).map(shot =>
                React.createElement('div', { key: shot.id, style: { position: 'relative', flexShrink: 0 } },
                  React.createElement('img', {
                    src: `data:${shot.mime_type};base64,${shot.data}`,
                    title: shot.filename,
                    style: { height: 120, maxWidth: 200, objectFit: 'cover', borderRadius: 4, cursor: 'pointer', border: '1px solid var(--line)', display: 'block' },
                    onClick: () => { const w = window.open('', '_blank'); w.document.write(`<img src="data:${shot.mime_type};base64,${shot.data}" style="max-width:100%;height:auto">`); w.document.close(); },
                  }),
                  React.createElement('button', {
                    onClick: () => handleScreenshotDelete(e.id, shot.id),
                    style: { position: 'absolute', top: 3, right: 3, width: 18, height: 18, borderRadius: '50%', background: 'rgba(0,0,0,0.75)', color: '#fff', border: 'none', cursor: 'pointer', fontSize: 11, lineHeight: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 0 },
                  }, '×')
                )
              )
            )
          : !screenshotUploading && React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', fontStyle: 'italic' } }, 'No screenshots yet.')
      ),

      // Outcome marking
      e.outcome === 'open' && React.createElement('div', { className: 'tv-card', style: { padding: '10px 14px' } },
        React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', marginBottom: 8 } }, 'Mark Outcome'),
        React.createElement('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap' } },
          [['win','var(--ok)'],['loss','var(--fail)'],['skip','var(--text4)']].map(([type, color]) =>
            React.createElement('button', {
              key: type, className: 'tv-btn', style: { fontSize: 12, color, borderColor: color },
              onClick: () => setOutcomeForm({ show: true, entryId: e.id, type, rMultiple: '', lesson: '' }),
            }, `Mark as ${type}`)
          )
        ),
        outcomeForm.show && outcomeForm.entryId === e.id && React.createElement('div', { style: { marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 } },
          React.createElement('input', {
            className: 'tv-input', placeholder: 'R-multiple (e.g. 2.1)', value: outcomeForm.rMultiple,
            style: { width: 180, fontSize: 12 },
            onChange: ev => setOutcomeForm(p => ({ ...p, rMultiple: ev.target.value })),
          }),
          React.createElement('textarea', {
            className: 'tv-input', placeholder: 'Lesson learned (optional)', value: outcomeForm.lesson,
            rows: 2, style: { resize: 'vertical', fontFamily: 'inherit', fontSize: 12 },
            onChange: ev => setOutcomeForm(p => ({ ...p, lesson: ev.target.value })),
          }),
          React.createElement('div', { style: { display: 'flex', gap: 6 } },
            React.createElement('button', { className: 'tv-btn primary', disabled: savingOutcome, onClick: markOutcome, style: { fontSize: 12 } }, savingOutcome ? 'Saving…' : 'Confirm'),
            React.createElement('button', { className: 'tv-btn', onClick: () => setOutcomeForm(p => ({ ...p, show: false })), style: { fontSize: 12 } }, 'Cancel')
          )
        )
      )
    );
  }
}

window.JournalScreen = JournalScreen;
