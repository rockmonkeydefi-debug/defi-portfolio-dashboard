/* ===== CONCEPTS SCREEN ===== */

const { useState: useCxS, useEffect: useCxE, useMemo: useCxM } = React;

function ConceptsScreen() {
  const [concepts, setConcepts] = useCxS([]);
  const [loading, setLoading] = useCxS(true);
  const [error, setError] = useCxS(null);
  const [selectedId, setSelectedId] = useCxS(null);
  const [detailData, setDetailData] = useCxS(null);
  const [loadingDetail, setLoadingDetail] = useCxS(false);
  const [detailError, setDetailError] = useCxS(null);
  const [searchQuery, setSearchQuery] = useCxS('');
  const [activeCategory, setActiveCategory] = useCxS('all');
  const [editMode, setEditMode] = useCxS(false);
  const [editForm, setEditForm] = useCxS({ title: '', summary: '', full_text: '' });
  const [saving, setSaving] = useCxS(false);
  const [confirmDelete, setConfirmDelete] = useCxS(false);
  const [extracting, setExtracting] = useCxS(false);
  const [extractMsg, setExtractMsg] = useCxS(null);

  function load() {
    setError(null);
    api('/api/trading/concepts')
      .then(r => { setConcepts(r.concepts || []); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }

  useCxE(() => { load(); }, []);

  function selectConcept(id) {
    if (selectedId === id) return;
    setSelectedId(id);
    setDetailData(null);
    setDetailError(null);
    setEditMode(false);
    setConfirmDelete(false);
    setLoadingDetail(true);
    api(`/api/trading/concepts/${id}`)
      .then(r => {
        setDetailData(r);
        setEditForm({ title: r.title || '', summary: r.summary || '', full_text: r.full_text || '' });
        setLoadingDetail(false);
      })
      .catch(e => { setDetailError(e.message); setLoadingDetail(false); });
  }

  async function saveConcept() {
    setSaving(true);
    try {
      await api(`/api/trading/concepts/${selectedId}`, {
        method: 'PUT',
        body: JSON.stringify(editForm),
      });
      setDetailData(prev => ({ ...prev, ...editForm }));
      setConcepts(prev => prev.map(c =>
        c.id === selectedId ? { ...c, title: editForm.title, summary: editForm.summary } : c
      ));
      setEditMode(false);
    } catch (e) {
      setDetailError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function deleteConcept() {
    try {
      await api(`/api/trading/concepts/${selectedId}`, { method: 'DELETE' });
      setConcepts(prev => prev.filter(c => c.id !== selectedId));
      setSelectedId(null);
      setDetailData(null);
      setConfirmDelete(false);
    } catch (e) {
      setDetailError(e.message);
    }
  }

  async function extractConcepts() {
    setExtracting(true);
    setExtractMsg(null);
    setError(null);
    try {
      const r = await api('/api/trading/extract-concepts', { method: 'POST', body: '{}' });
      const skipped = r.docs_skipped ? ` (${r.docs_skipped} already done)` : '';
      setExtractMsg(`Extracted ${r.concepts_created} concepts from ${r.docs_processed} docs${skipped}.`);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setExtracting(false);
    }
  }

  const categories = useCxM(() => {
    const cats = new Set();
    concepts.forEach(c => { if (c.category) cats.add(c.category); });
    return Array.from(cats).sort();
  }, [concepts]);

  const filtered = useCxM(() => {
    let out = concepts;
    if (activeCategory !== 'all') out = out.filter(c => c.category === activeCategory);
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      out = out.filter(c => (c.title || '').toLowerCase().includes(q) || (c.summary || '').toLowerCase().includes(q));
    }
    return out;
  }, [concepts, activeCategory, searchQuery]);

  function confColor(conf) {
    if (!conf || conf <= 0) return 'var(--text4)';
    return conf >= 70 ? 'var(--ok)' : conf >= 40 ? 'var(--warn)' : 'var(--fail)';
  }

  if (loading) return React.createElement('div', { className: 'tv-label', style: { padding: 32 } }, 'Loading…');

  return React.createElement('div', {
    style: { display: 'flex', gap: 0, padding: '16px 0', alignItems: 'flex-start', minHeight: 400 }
  },

    // ── LEFT COLUMN — list ──
    React.createElement('div', {
      style: { width: 360, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 10, paddingRight: 16, borderRight: '1px solid var(--line)' }
    },
      // Header
      React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
          React.createElement('div', { style: { fontWeight: 600, fontSize: 15 } }, 'Concepts'),
          React.createElement('span', { className: 'tv-chip' }, String(concepts.length))
        ),
        React.createElement('button', {
          className: extracting ? 'tv-btn' : 'tv-btn primary',
          disabled: extracting,
          onClick: extractConcepts,
          style: { fontSize: 11, padding: '3px 10px', whiteSpace: 'nowrap' },
        }, extracting ? 'Extracting…' : '⚡ Extract from Docs')
      ),

      error && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 12 } }, error),
      extractMsg && React.createElement('div', { style: { color: 'var(--ok)', fontSize: 12 } }, extractMsg),

      // Search
      React.createElement('input', {
        className: 'tv-input',
        placeholder: 'Search concepts…',
        value: searchQuery,
        onChange: e => setSearchQuery(e.target.value),
        style: { width: '100%', boxSizing: 'border-box', fontSize: 13 },
      }),

      // Category pills
      React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 5 } },
        React.createElement('button', {
          className: activeCategory === 'all' ? 'tv-chip adapt' : 'tv-chip',
          onClick: () => setActiveCategory('all'),
        }, `All (${concepts.length})`),
        categories.map(cat =>
          React.createElement('button', {
            key: cat,
            className: activeCategory === cat ? 'tv-chip adapt' : 'tv-chip',
            onClick: () => setActiveCategory(activeCategory === cat ? 'all' : cat),
          }, `${cat.replace(/_/g, ' ')} (${concepts.filter(c => c.category === cat).length})`)
        )
      ),

      // Concept list
      filtered.length === 0
        ? React.createElement('div', {
            className: 'tv-card',
            style: { textAlign: 'center', color: 'var(--text4)', padding: 28, fontSize: 13, lineHeight: 1.6 }
          },
            concepts.length === 0
              ? 'No concepts yet. Upload a strategy document in Settings → Document Uploads and use Extract from Docs.'
              : 'No concepts match your search.'
          )
        : React.createElement('div', {
            style: { display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 'calc(100vh - 260px)', overflowY: 'auto' }
          },
            filtered.map(c =>
              React.createElement('div', {
                key: c.id,
                className: 'tv-card',
                onClick: () => selectConcept(c.id),
                style: {
                  cursor: 'pointer', padding: '10px 12px',
                  border: selectedId === c.id ? '1px solid var(--accent)' : undefined,
                  background: selectedId === c.id ? 'var(--panel2)' : undefined,
                  transition: 'border 0.1s',
                },
              },
                React.createElement('div', { style: { fontWeight: 600, fontSize: 13, marginBottom: 4 } }, c.title),
                React.createElement('div', { style: { display: 'flex', gap: 5, flexWrap: 'wrap', marginBottom: 6 } },
                  c.category && React.createElement('span', { className: 'tv-chip' }, c.category.replace(/_/g, ' ')),
                  (c.tags || []).slice(0, 3).map((t, i) =>
                    React.createElement('span', { key: i, className: 'tv-chip', style: { opacity: 0.65 } }, t)
                  )
                ),
                c.confidence > 0
                  ? React.createElement('div', null,
                      React.createElement('div', {
                        style: { display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text4)', marginBottom: 3 }
                      },
                        React.createElement('span', null, 'Confidence'),
                        React.createElement('span', { style: { color: confColor(c.confidence) } }, `${c.confidence}%`)
                      ),
                      React.createElement('div', { style: { height: 3, background: 'var(--line)', borderRadius: 2 } },
                        React.createElement('div', {
                          style: { width: `${Math.min(100, c.confidence)}%`, height: '100%', background: confColor(c.confidence), borderRadius: 2 }
                        })
                      )
                    )
                  : React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)' } }, 'Not evaluated'),
                c.source_doc && React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', marginTop: 4 } },
                  `📄 ${c.source_doc}`)
              )
            )
          )
    ),

    // ── RIGHT COLUMN — detail ──
    React.createElement('div', { style: { flex: 1, minWidth: 0, paddingLeft: 20 } },
      !selectedId
        ? React.createElement('div', {
            style: { display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 200, color: 'var(--text4)', fontSize: 13 }
          }, 'Select a concept to view details')
        : loadingDetail
          ? React.createElement('div', { className: 'tv-label', style: { padding: 32 } }, 'Loading…')
          : detailError && !detailData
            ? React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13, padding: 16 } }, detailError)
            : detailData && React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 14 } },

                // Header row
                React.createElement('div', { style: { display: 'flex', alignItems: 'flex-start', gap: 12 } },
                  React.createElement('div', { style: { flex: 1, minWidth: 0 } },
                    editMode
                      ? React.createElement('input', {
                          className: 'tv-input',
                          value: editForm.title,
                          onChange: e => setEditForm(p => ({ ...p, title: e.target.value })),
                          style: { fontSize: 17, fontWeight: 700, width: '100%', marginBottom: 8 },
                        })
                      : React.createElement('div', { style: { fontSize: 18, fontWeight: 700, lineHeight: 1.3, marginBottom: 8 } }, detailData.title),
                    React.createElement('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' } },
                      detailData.category && React.createElement('span', { className: 'tv-chip accent' }, detailData.category.replace(/_/g, ' ')),
                      (detailData.tags || []).map((t, i) => React.createElement('span', { key: i, className: 'tv-chip' }, t)),
                      detailData.source_doc && React.createElement('span', { className: 'tv-chip', style: { opacity: 0.7 } }, `📄 ${detailData.source_doc}`)
                    )
                  ),
                  // Action buttons
                  React.createElement('div', { style: { display: 'flex', gap: 6, flexShrink: 0, flexWrap: 'wrap' } },
                    !editMode && React.createElement('button', {
                      className: 'tv-btn', onClick: () => { setEditMode(true); setConfirmDelete(false); },
                      style: { fontSize: 12 },
                    }, 'Edit'),
                    !editMode && !confirmDelete && React.createElement('button', {
                      className: 'tv-btn danger', onClick: () => setConfirmDelete(true),
                      style: { fontSize: 12 },
                    }, 'Delete'),
                    !editMode && confirmDelete && React.createElement('button', {
                      className: 'tv-btn danger', onClick: deleteConcept, style: { fontSize: 12 },
                    }, 'Confirm Delete'),
                    !editMode && confirmDelete && React.createElement('button', {
                      className: 'tv-btn', onClick: () => setConfirmDelete(false), style: { fontSize: 12 },
                    }, 'Cancel')
                  )
                ),

                detailError && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 12 } }, detailError),

                // Confidence bar
                React.createElement('div', { className: 'tv-card', style: { padding: '10px 14px' } },
                  React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 12 } },
                    React.createElement('span', { style: { color: 'var(--text4)' } }, 'Confidence Score'),
                    React.createElement('span', { style: { color: confColor(detailData.confidence), fontWeight: 600 } },
                      detailData.confidence > 0 ? `${detailData.confidence} / 100` : 'Not evaluated')
                  ),
                  React.createElement('div', { style: { height: 6, background: 'var(--line)', borderRadius: 3 } },
                    detailData.confidence > 0 && React.createElement('div', {
                      style: { width: `${Math.min(100, detailData.confidence)}%`, height: '100%', background: confColor(detailData.confidence), borderRadius: 3 }
                    })
                  )
                ),

                // Summary
                React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
                  React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.07em' } }, 'Summary'),
                  editMode
                    ? React.createElement('textarea', {
                        className: 'tv-input',
                        value: editForm.summary,
                        rows: 3,
                        style: { width: '100%', resize: 'vertical', fontFamily: 'inherit', fontSize: 13 },
                        onChange: e => setEditForm(p => ({ ...p, summary: e.target.value })),
                      })
                    : React.createElement('div', { style: { fontSize: 14, color: 'var(--text2)', lineHeight: 1.6 } }, detailData.summary || '—')
                ),

                // Full text
                (editMode || detailData.full_text) && React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
                  React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.07em' } }, 'Full Notes'),
                  editMode
                    ? React.createElement('textarea', {
                        className: 'tv-input',
                        value: editForm.full_text,
                        rows: 8,
                        style: { width: '100%', resize: 'vertical', fontFamily: 'inherit', fontSize: 13 },
                        onChange: e => setEditForm(p => ({ ...p, full_text: e.target.value })),
                      })
                    : React.createElement('div', {
                        style: { fontSize: 13, color: 'var(--text3)', whiteSpace: 'pre-wrap', lineHeight: 1.6, background: 'var(--panel)', padding: '10px 12px', borderRadius: 6, fontFamily: 'Fira Code, monospace' }
                      }, detailData.full_text)
                ),

                // Edit save/cancel
                editMode && React.createElement('div', { style: { display: 'flex', gap: 8 } },
                  React.createElement('button', {
                    className: 'tv-btn primary', disabled: saving, onClick: saveConcept, style: { fontSize: 13 },
                  }, saving ? 'Saving…' : 'Save'),
                  React.createElement('button', {
                    className: 'tv-btn',
                    onClick: () => {
                      setEditMode(false);
                      setEditForm({ title: detailData.title || '', summary: detailData.summary || '', full_text: detailData.full_text || '' });
                    },
                    style: { fontSize: 13 },
                  }, 'Cancel')
                )
              )
    )
  );
}

window.ConceptsScreen = ConceptsScreen;
