/* ===== SETTINGS SCREEN ===== */

const { useState: useSState, useEffect: useSEffect, useRef: useSRef } = React;

const SETTINGS_SECTIONS = [
  { id: 'display',      label: 'Display Preferences' },
  { id: 'wallets',      label: 'Wallets' },
  { id: 'integrations', label: 'Integrations' },
  { id: 'ai',           label: 'AI Config' },
  { id: 'documents',    label: 'Document Uploads' },
  { id: 'spotpnl',      label: 'Spot P&L Config' },
  { id: 'backup',       label: 'Backup & Security' },
  { id: 'messaging',    label: 'Messaging' },
];

// ── Shared: Masked Input ──────────────────────────────────────────────────
function MaskedInput({ value, onChange, placeholder, style: extraStyle }) {
  const [show, setShow] = useSState(false);
  return React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center', ...extraStyle } },
    React.createElement('input', {
      type: show ? 'text' : 'password',
      value: value,
      onChange: e => onChange(e.target.value),
      className: 'tv-input',
      placeholder: placeholder || '••••••••',
      style: { flex: 1, maxWidth: 320 },
    }),
    React.createElement('button', { className: 'tv-btn', style: { fontSize: 11, padding: '2px 8px' }, onClick: () => setShow(s => !s) },
      show ? 'Hide' : 'Show'
    )
  );
}

// ── Shared: Toggle Switch ─────────────────────────────────────────────────
function Toggle({ value, onChange }) {
  return React.createElement('div', {
    style: { width: 44, height: 24, borderRadius: 12, position: 'relative', cursor: 'pointer', background: value ? 'var(--accent)' : 'var(--panel3)', transition: 'background 0.2s', flexShrink: 0 },
    onClick: () => onChange(!value),
  },
    React.createElement('div', {
      style: { position: 'absolute', top: 2, left: value ? 22 : 2, width: 20, height: 20, borderRadius: 10, background: value ? '#000' : 'var(--text4)', transition: 'left 0.2s' }
    })
  );
}

// ── Shared: Status text ────────────────────────────────────────────────────
function StatusText({ msg }) {
  if (!msg) return null;
  const ok = msg === 'Saved' || msg.includes('sent') || msg.includes('changed');
  return React.createElement('span', { style: { fontSize: 12, color: ok ? 'var(--ok)' : 'var(--fail)' } }, msg);
}

// ── 1. Display Preferences ────────────────────────────────────────────────
function DisplaySection({ hideValues, setHideValues }) {
  const [dust, setDust] = useSState('');
  const [lending, setLending] = useSState('');
  const [saving, setSaving] = useSState(false);
  const [status, setStatus] = useSState('');

  useSEffect(() => {
    api('/api/settings/display')
      .then(d => {
        if (d.dust_threshold != null) setDust(String(d.dust_threshold));
        if (d.lending_threshold != null) setLending(String(d.lending_threshold));
      })
      .catch(() => {});
  }, []);

  function handleToggle() {
    const next = !hideValues;
    setHideValues(next);
    localStorage.setItem('hideValues', String(next));
    api('/api/settings/display', { method: 'POST', body: JSON.stringify({ hide_values: next }) }).catch(() => {});
  }

  async function saveThresholds() {
    setSaving(true);
    setStatus('');
    try {
      await api('/api/settings/display', {
        method: 'POST',
        body: JSON.stringify({ dust_threshold: Number(dust), lending_threshold: Number(lending) }),
      });
      setStatus('Saved');
    } catch (e) {
      setStatus('Error saving');
    } finally {
      setSaving(false);
      setTimeout(() => setStatus(''), 2500);
    }
  }

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
    React.createElement('div', { className: 'tv-label' }, 'Display Preferences'),

    // Hide Values card
    React.createElement('div', {
      className: 'tv-card',
      style: { padding: 20, border: '2px solid var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer' },
      onClick: handleToggle,
    },
      React.createElement('div', null,
        React.createElement('div', { style: { fontSize: 14, fontWeight: 600, color: 'var(--text)' } }, 'Hide Values'),
        React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', marginTop: 4 } }, 'Mask all monetary values across the dashboard')
      ),
      React.createElement(Toggle, { value: hideValues, onChange: handleToggle })
    ),

    // Thresholds
    React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      React.createElement('div', { className: 'tv-label', style: { marginBottom: 14 } }, 'Filter Thresholds'),
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 14 } },
        React.createElement('div', null,
          React.createElement('label', { style: { fontSize: 12, color: 'var(--text4)', display: 'block', marginBottom: 6 } }, 'Dust Threshold (USD)'),
          React.createElement('input', { type: 'number', value: dust, onChange: e => setDust(e.target.value), className: 'tv-input', style: { width: 180 }, placeholder: '0' })
        ),
        React.createElement('div', null,
          React.createElement('label', { style: { fontSize: 12, color: 'var(--text4)', display: 'block', marginBottom: 6 } }, 'Lending Threshold (USD)'),
          React.createElement('input', { type: 'number', value: lending, onChange: e => setLending(e.target.value), className: 'tv-input', style: { width: 180 }, placeholder: '0' })
        ),
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12 } },
          React.createElement('button', { className: 'tv-btn', style: { fontSize: 12, padding: '5px 16px' }, onClick: saveThresholds, disabled: saving }, saving ? 'Saving…' : 'Save'),
          React.createElement(StatusText, { msg: status })
        )
      )
    )
  );
}

// ── 2. Wallets ─────────────────────────────────────────────────────────────
function WalletsSection() {
  const [wallets, setWallets] = useSState([]);
  const [loading, setLoading] = useSState(true);
  const [newAddr, setNewAddr] = useSState('');
  const [newLabel, setNewLabel] = useSState('');
  const [adding, setAdding] = useSState(false);
  const [status, setStatus] = useSState('');

  function fetchWallets() {
    api('/api/wallets')
      .then(d => setWallets(Array.isArray(d) ? d : (d.wallets || [])))
      .catch(() => setWallets([]))
      .finally(() => setLoading(false));
  }
  useSEffect(() => { fetchWallets(); }, []);

  function maskAddr(addr) {
    if (!addr || addr.length < 12) return addr;
    return addr.slice(0, 6) + '…' + addr.slice(-4);
  }

  async function toggleVisible(w) {
    try {
      await api(`/api/wallets/${w.address}`, { method: 'PUT', body: JSON.stringify({ visible: !w.visible }) });
      fetchWallets();
    } catch (e) {}
  }

  async function removeWallet(w) {
    if (!confirm(`Remove wallet "${w.label || maskAddr(w.address)}"?`)) return;
    try {
      await api(`/api/wallets/${w.address}`, { method: 'DELETE' });
      fetchWallets();
    } catch (e) {}
  }

  async function addWallet() {
    if (!newAddr.trim()) return;
    setAdding(true);
    setStatus('');
    try {
      await api('/api/wallets', { method: 'POST', body: JSON.stringify({ address: newAddr.trim(), label: newLabel.trim() }) });
      setNewAddr(''); setNewLabel('');
      fetchWallets();
    } catch (e) {
      setStatus('Error adding wallet');
      setTimeout(() => setStatus(''), 2500);
    } finally {
      setAdding(false);
    }
  }

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
    React.createElement('div', { className: 'tv-label' }, 'Wallets'),
    React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      loading
        ? React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…')
        : wallets.length === 0
          ? React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'No wallets configured')
          : React.createElement('div', null,
              React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '14px 1fr 1fr auto auto', gap: '0 14px', paddingBottom: 8, fontSize: 11, color: 'var(--text4)' } },
                React.createElement('div'),
                React.createElement('div', null, 'Label'),
                React.createElement('div', null, 'Address'),
                React.createElement('div', null, 'Visible'),
                React.createElement('div')
              ),
              wallets.map((w, i) =>
                React.createElement('div', { key: w.address || i, style: { display: 'grid', gridTemplateColumns: '14px 1fr 1fr auto auto', gap: '0 14px', alignItems: 'center', borderTop: '1px solid var(--line)', padding: '8px 0', fontSize: 13 } },
                  React.createElement('div', { style: { width: 10, height: 10, borderRadius: '50%', background: w.color || 'var(--accent)' } }),
                  React.createElement('div', { style: { color: 'var(--text2)' } }, w.label || '—'),
                  React.createElement('div', { style: { color: 'var(--text4)', fontFamily: 'Fira Code', fontSize: 12 } }, maskAddr(w.address)),
                  React.createElement('button', { className: 'tv-btn', style: { fontSize: 11, padding: '2px 10px', opacity: w.visible === false ? 0.5 : 1 }, onClick: () => toggleVisible(w) }, w.visible === false ? 'Hidden' : 'Visible'),
                  React.createElement('button', { className: 'tv-btn danger', style: { fontSize: 11, padding: '2px 10px' }, onClick: () => removeWallet(w) }, 'Remove')
                )
              )
            )
    ),
    React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      React.createElement('div', { className: 'tv-label', style: { marginBottom: 14 } }, 'Add Wallet'),
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 10 } },
        React.createElement('input', { type: 'text', value: newAddr, onChange: e => setNewAddr(e.target.value), className: 'tv-input', placeholder: '0x…', style: { maxWidth: 420 } }),
        React.createElement('input', { type: 'text', value: newLabel, onChange: e => setNewLabel(e.target.value), className: 'tv-input', placeholder: 'Label (optional)', style: { maxWidth: 420 } }),
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12 } },
          React.createElement('button', { className: 'tv-btn', style: { fontSize: 12, padding: '5px 16px' }, onClick: addWallet, disabled: adding || !newAddr.trim() }, adding ? 'Adding…' : 'Add Wallet'),
          React.createElement(StatusText, { msg: status })
        )
      )
    )
  );
}

// ── 3. Integrations ────────────────────────────────────────────────────────
function IntegrationsSection() {
  const [fields, setFields] = useSState({});
  const [loading, setLoading] = useSState(true);
  const [statuses, setStatuses] = useSState({});

  useSEffect(() => {
    api('/api/config').then(d => setFields(d)).catch(() => {}).finally(() => setLoading(false));
  }, []);

  function setField(k, v) { setFields(f => ({ ...f, [k]: v })); }
  function fieldVal(k) { return fields[k] || ''; }

  async function save(k, statusKey) {
    const sk = statusKey || k;
    setStatuses(s => ({ ...s, [sk]: 'Saving…' }));
    try {
      await api('/api/config', { method: 'POST', body: JSON.stringify({ [k]: fieldVal(k) }) });
      setStatuses(s => ({ ...s, [sk]: 'Saved' }));
    } catch (e) {
      setStatuses(s => ({ ...s, [sk]: 'Error' }));
    }
    setTimeout(() => setStatuses(s => ({ ...s, [sk]: '' })), 2500);
  }

  function Row({ label, k, masked }) {
    return React.createElement('div', { style: { marginBottom: 14 } },
      React.createElement('label', { style: { fontSize: 12, color: 'var(--text4)', display: 'block', marginBottom: 6 } }, label),
      React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center' } },
        masked
          ? React.createElement(MaskedInput, { value: fieldVal(k), onChange: v => setField(k, v) })
          : React.createElement('input', { type: 'text', value: fieldVal(k), onChange: e => setField(k, e.target.value), className: 'tv-input', style: { flex: 1, maxWidth: 360 } }),
        React.createElement('button', { className: 'tv-btn', style: { fontSize: 11, padding: '3px 12px' }, onClick: () => save(k) }, 'Save'),
        React.createElement(StatusText, { msg: statuses[k] || '' })
      )
    );
  }

  function APIKeyRow({ label, k, badge }) {
    const badgeCls = badge === 'REQUIRED' ? 'fail' : badge === 'RECOMMENDED' ? 'warn' : 'adapt';
    return React.createElement('div', { style: { marginBottom: 14 } },
      React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 } },
        React.createElement('label', { style: { fontSize: 12, color: 'var(--text4)' } }, label),
        badge && React.createElement('span', { className: `tv-chip ${badgeCls}`, style: { fontSize: 10, padding: '1px 6px' } }, badge)
      ),
      React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center' } },
        React.createElement(MaskedInput, { value: fieldVal(k), onChange: v => setField(k, v) }),
        React.createElement('button', { className: 'tv-btn', style: { fontSize: 11, padding: '3px 12px' }, onClick: () => save(k) }, 'Save'),
        React.createElement(StatusText, { msg: statuses[k] || '' })
      )
    );
  }

  if (loading) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…');

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
    React.createElement('div', { className: 'tv-label' }, 'Integrations'),
    React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      React.createElement('div', { className: 'tv-label', style: { marginBottom: 14, fontSize: 12 } }, 'RPC Endpoints'),
      React.createElement(Row, { label: 'Ethereum RPC', k: 'eth_rpc' }),
      React.createElement(Row, { label: 'Arbitrum RPC', k: 'arb_rpc' }),
      React.createElement(Row, { label: 'Base RPC', k: 'base_rpc' })
    ),
    React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      React.createElement('div', { className: 'tv-label', style: { marginBottom: 14, fontSize: 12 } }, 'AI Provider Keys'),
      React.createElement(Row, { label: 'Anthropic API Key', k: 'anthropic_api_key', masked: true }),
      React.createElement(Row, { label: 'OpenAI API Key', k: 'openai_api_key', masked: true })
    ),
    React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      React.createElement('div', { className: 'tv-label', style: { marginBottom: 14, fontSize: 12 } }, 'Other APIs'),
      React.createElement(APIKeyRow, { label: 'Zerion API Key', k: 'zerion_api_key', badge: 'REQUIRED' }),
      React.createElement(APIKeyRow, { label: 'Etherscan API Key', k: 'etherscan_api_key', badge: 'RECOMMENDED' }),
      React.createElement(APIKeyRow, { label: 'FRED API Key', k: 'fred_api_key', badge: 'OPTIONAL' })
    )
  );
}

// ── 4. AI Config ───────────────────────────────────────────────────────────
function AIConfigSection() {
  const [provider, setProvider] = useSState('anthropic');
  const [model, setModel] = useSState('');
  const [models, setModels] = useSState([]);
  const [saving, setSaving] = useSState(false);
  const [status, setStatus] = useSState('');

  useSEffect(() => {
    api('/api/ai/config')
      .then(d => { if (d.provider) setProvider(d.provider); if (d.model) setModel(d.model); })
      .catch(() => {});
  }, []);

  useSEffect(() => {
    api(`/api/ai/models/${provider}`)
      .then(d => {
        const list = Array.isArray(d) ? d : (d.models || []);
        setModels(list);
      })
      .catch(() => setModels([]));
  }, [provider]);

  async function save() {
    setSaving(true); setStatus('');
    try {
      await api('/api/ai/config', { method: 'POST', body: JSON.stringify({ provider, model }) });
      setStatus('Saved');
    } catch (e) { setStatus('Error'); }
    finally { setSaving(false); setTimeout(() => setStatus(''), 2500); }
  }

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
    React.createElement('div', { className: 'tv-label' }, 'AI Config'),
    React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 16 } },
        React.createElement('div', null,
          React.createElement('label', { style: { fontSize: 12, color: 'var(--text4)', display: 'block', marginBottom: 8 } }, 'Provider'),
          React.createElement('div', { style: { display: 'flex', borderRadius: 6, overflow: 'hidden', border: '1px solid var(--line)', width: 'fit-content' } },
            ['anthropic', 'openai'].map(p =>
              React.createElement('button', {
                key: p, onClick: () => setProvider(p),
                style: { padding: '6px 20px', fontSize: 13, cursor: 'pointer', border: 'none', background: provider === p ? 'var(--accent)' : 'var(--panel2)', color: provider === p ? '#000' : 'var(--text2)', fontWeight: provider === p ? 600 : 400 }
              }, p === 'anthropic' ? 'Anthropic' : 'OpenAI')
            )
          )
        ),
        React.createElement('div', null,
          React.createElement('label', { style: { fontSize: 12, color: 'var(--text4)', display: 'block', marginBottom: 8 } }, 'Model'),
          models.length > 0
            ? React.createElement('select', { value: model, onChange: e => setModel(e.target.value), className: 'tv-input', style: { width: 300 } },
                models.map(m => React.createElement('option', { key: m, value: m }, m))
              )
            : React.createElement('input', { type: 'text', value: model, onChange: e => setModel(e.target.value), className: 'tv-input', style: { width: 300 }, placeholder: 'Model name' })
        ),
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12 } },
          React.createElement('button', { className: 'tv-btn', style: { fontSize: 12, padding: '5px 16px' }, onClick: save, disabled: saving }, saving ? 'Saving…' : 'Save'),
          React.createElement(StatusText, { msg: status })
        )
      )
    )
  );
}

// ── 5. Document Uploads ────────────────────────────────────────────────────
function DropZone({ category, onUpload }) {
  const inputRef = useSRef(null);
  const [dragging, setDragging] = useSState(false);
  const [uploading, setUploading] = useSState(false);
  const [status, setStatus] = useSState('');

  async function upload(file) {
    setUploading(true); setStatus('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('category', category);
      const resp = await fetch('/api/strategies/upload', { method: 'POST', body: fd });
      if (!resp.ok) throw new Error();
      setStatus('Uploaded');
      onUpload();
    } catch (e) { setStatus('Upload failed'); }
    finally { setUploading(false); setTimeout(() => setStatus(''), 3000); }
  }

  return React.createElement('div', {
    style: { border: `2px dashed ${dragging ? 'var(--accent)' : 'var(--line)'}`, borderRadius: 8, padding: '16px 20px', textAlign: 'center', cursor: 'pointer', background: dragging ? 'var(--panel2)' : 'transparent', transition: 'all 0.15s' },
    onClick: () => inputRef.current && inputRef.current.click(),
    onDragOver: e => { e.preventDefault(); setDragging(true); },
    onDragLeave: () => setDragging(false),
    onDrop: e => { e.preventDefault(); setDragging(false); if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); },
  },
    React.createElement('input', { ref: inputRef, type: 'file', accept: '.md,.pdf,.docx,.xlsx,.csv', style: { display: 'none' }, onChange: e => { if (e.target.files[0]) upload(e.target.files[0]); } }),
    uploading
      ? React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Uploading…')
      : React.createElement('div', null,
          React.createElement('div', { style: { fontSize: 13, color: 'var(--text2)' } }, 'Drop file here or click to browse'),
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginTop: 4 } }, '.md  .pdf  .docx  .xlsx  .csv'),
          status && React.createElement('div', { style: { fontSize: 12, color: status === 'Uploaded' ? 'var(--ok)' : 'var(--fail)', marginTop: 6 } }, status)
        )
  );
}

function DocUploadsSection() {
  const [docs, setDocs] = useSState([]);
  const [loading, setLoading] = useSState(true);

  function fetchDocs() {
    api('/api/strategies')
      .then(d => setDocs(Array.isArray(d) ? d : (d.strategies || [])))
      .catch(() => setDocs([]))
      .finally(() => setLoading(false));
  }
  useSEffect(() => { fetchDocs(); }, []);

  async function deleteDoc(id) {
    if (!confirm('Delete this document?')) return;
    try { await api(`/api/strategies/${id}`, { method: 'DELETE' }); fetchDocs(); } catch (e) {}
  }

  function DocGroup({ title, category }) {
    const filtered = docs.filter(d => d.category === category);
    return React.createElement('div', null,
      React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 } }, title),
      React.createElement(DropZone, { category, onUpload: fetchDocs }),
      filtered.length > 0 && React.createElement('div', { style: { marginTop: 10 } },
        filtered.map((doc, i) =>
          React.createElement('div', { key: doc.id || i, style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0', borderTop: '1px solid var(--line)', fontSize: 13 } },
            React.createElement('div', null,
              React.createElement('div', { style: { color: 'var(--text2)' } }, doc.filename || doc.name),
              doc.uploaded_at && React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginTop: 2 } }, new Date(doc.uploaded_at).toLocaleDateString())
            ),
            React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center' } },
              React.createElement('span', { className: 'tv-chip adapt', style: { fontSize: 10, padding: '1px 6px' } }, doc.category),
              React.createElement('button', { className: 'tv-btn danger', style: { fontSize: 11, padding: '2px 8px' }, onClick: () => deleteDoc(doc.id) }, 'Delete')
            )
          )
        )
      )
    );
  }

  if (loading) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…');

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
    React.createElement('div', { className: 'tv-label' }, 'Document Uploads'),
    React.createElement('div', { className: 'tv-card', style: { padding: 20 } }, React.createElement(DocGroup, { title: 'DeFi Strategy', category: 'defi' })),
    React.createElement('div', { className: 'tv-card', style: { padding: 20 } }, React.createElement(DocGroup, { title: 'Trading Strategy', category: 'trading' }))
  );
}

// ── 6. Spot P&L Config ─────────────────────────────────────────────────────
function SpotPnLSection() {
  const [tokens, setTokens] = useSState([]);
  const [loading, setLoading] = useSState(true);
  const [edits, setEdits] = useSState({});
  const [testResults, setTestResults] = useSState({});
  const [statuses, setStatuses] = useSState({});

  useSEffect(() => {
    api('/api/spot/token-config')
      .then(d => {
        const list = Array.isArray(d) ? d : (d.tokens || []);
        setTokens(list);
        const e = {};
        list.forEach(t => { e[t.symbol] = { contract_address: t.contract_address || '', price_source: t.price_source || 'coingecko' }; });
        setEdits(e);
      })
      .catch(() => setTokens([]))
      .finally(() => setLoading(false));
  }, []);

  function setEdit(sym, k, v) { setEdits(e => ({ ...e, [sym]: { ...e[sym], [k]: v } })); }

  async function testPrice(sym) {
    setTestResults(r => ({ ...r, [sym]: 'Testing…' }));
    try {
      const d = await api(`/api/spot/price-test/${sym}`);
      setTestResults(r => ({ ...r, [sym]: d.price != null ? `$${fmtNum(d.price, 4)} (${d.source})` : 'No price' }));
    } catch (e) { setTestResults(r => ({ ...r, [sym]: 'Error' })); }
  }

  async function saveToken(sym) {
    setStatuses(s => ({ ...s, [sym]: 'Saving…' }));
    try {
      const e = edits[sym] || {};
      const orig = tokens.find(t => t.symbol === sym) || {};
      await api('/api/spot/token-config', { method: 'POST', body: JSON.stringify({
        symbol:           sym,
        contract_address: e.contract_address || '',
        price_source:     e.price_source     || 'coingecko',
        cg_id:            orig.cg_id         || '',
        chain:            orig.chain          || '',
        notes:            orig.notes          || '',
      }) });
      setStatuses(s => ({ ...s, [sym]: 'Saved' }));
    } catch (e) { setStatuses(s => ({ ...s, [sym]: 'Error' })); }
    setTimeout(() => setStatuses(s => ({ ...s, [sym]: '' })), 2500);
  }

  if (loading) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…');

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
    React.createElement('div', { className: 'tv-label' }, 'Spot P&L Config'),
    React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      tokens.length === 0
        ? React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'No tokens configured')
        : tokens.map((tok, i) => {
            const e = edits[tok.symbol] || { contract_address: '', price_source: 'coingecko' };
            return React.createElement('div', { key: tok.symbol, style: { borderTop: i > 0 ? '1px solid var(--line)' : 'none', padding: '12px 0' } },
              React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10 } },
                React.createElement('span', { style: { fontSize: 13, fontWeight: 600, color: 'var(--text)', width: 72, flexShrink: 0 } }, tok.symbol),
                React.createElement('input', { type: 'text', value: e.contract_address, onChange: ev => setEdit(tok.symbol, 'contract_address', ev.target.value), className: 'tv-input', placeholder: 'Contract override (0x…)', style: { flex: 1, minWidth: 180, maxWidth: 300, fontSize: 12 } }),
                React.createElement('select', { value: e.price_source, onChange: ev => setEdit(tok.symbol, 'price_source', ev.target.value), className: 'tv-input', style: { width: 130, fontSize: 12 } },
                  ['coingecko', 'dexscreener', 'manual'].map(s => React.createElement('option', { key: s, value: s }, s))
                ),
                React.createElement('button', { className: 'tv-btn', style: { fontSize: 11, padding: '3px 10px' }, onClick: () => testPrice(tok.symbol) }, 'Test'),
                React.createElement('button', { className: 'tv-btn', style: { fontSize: 11, padding: '3px 10px' }, onClick: () => saveToken(tok.symbol) }, 'Save'),
                statuses[tok.symbol] && React.createElement(StatusText, { msg: statuses[tok.symbol] }),
                testResults[tok.symbol] && React.createElement('span', { style: { fontSize: 11, color: 'var(--text2)', fontFamily: 'Fira Code' } }, testResults[tok.symbol])
              )
            );
          })
    )
  );
}

// ── 7. Backup & Security ───────────────────────────────────────────────────
function BackupSection() {
  const [pwCurrent, setPwCurrent] = useSState('');
  const [pwNew, setPwNew] = useSState('');
  const [pwConfirm, setPwConfirm] = useSState('');
  const [pwStatus, setPwStatus] = useSState('');
  const [importing, setImporting] = useSState({ db: false, cfg: false });
  const dbRef = useSRef(null);
  const cfgRef = useSRef(null);

  async function changePassword() {
    if (pwNew !== pwConfirm) { setPwStatus('Passwords do not match'); return; }
    setPwStatus('Saving…');
    try {
      await api('/api/change-password', { method: 'POST', body: JSON.stringify({ current: pwCurrent, new: pwNew }) });
      setPwStatus('Password changed');
      setPwCurrent(''); setPwNew(''); setPwConfirm('');
    } catch (e) { setPwStatus('Error changing password'); }
    setTimeout(() => setPwStatus(''), 3000);
  }

  async function importFile(type, file) {
    setImporting(s => ({ ...s, [type]: true }));
    const fd = new FormData();
    fd.append('file', file);
    try {
      const resp = await fetch(`/api/backup/${type}`, { method: 'POST', body: fd });
      if (!resp.ok) throw new Error();
      alert('Import successful. The page will reload.');
      window.location.reload();
    } catch (e) { alert('Import failed'); }
    finally { setImporting(s => ({ ...s, [type]: false })); }
  }

  const pwFields = [
    ['Current Password', pwCurrent, setPwCurrent],
    ['New Password', pwNew, setPwNew],
    ['Confirm New Password', pwConfirm, setPwConfirm],
  ];

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
    React.createElement('div', { className: 'tv-label' }, 'Backup & Security'),

    // Two-column backup card
    React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      React.createElement('div', { style: { display: 'flex', gap: 32, flexWrap: 'wrap' } },

        // Left: Snapshot Database
        React.createElement('div', { style: { flex: 1, minWidth: 200 } },
          React.createElement('div', { style: { fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 4 } }, 'Snapshot Database'),
          React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', marginBottom: 14, lineHeight: 1.5 } }, 'Full SQLite snapshot of all portfolio data, transactions, and history.'),
          React.createElement('input', { ref: dbRef, type: 'file', style: { display: 'none' }, onChange: e => { if (e.target.files[0]) importFile('db', e.target.files[0]); } }),
          React.createElement('div', { style: { display: 'flex', gap: 10 } },
            React.createElement('button', { className: 'tv-btn', style: { fontSize: 12, padding: '5px 16px' }, onClick: () => { window.location = '/api/backup/db'; } }, 'Export DB'),
            React.createElement('button', { className: 'tv-btn primary', style: { fontSize: 12, padding: '5px 16px' }, onClick: () => dbRef.current && dbRef.current.click(), disabled: importing.db }, importing.db ? 'Importing…' : 'Import DB')
          )
        ),

        // Divider
        React.createElement('div', { style: { width: 1, background: 'var(--line)', alignSelf: 'stretch' } }),

        // Right: All Settings
        React.createElement('div', { style: { flex: 1, minWidth: 200 } },
          React.createElement('div', { style: { fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 4 } }, 'All Settings'),
          React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', marginBottom: 14, lineHeight: 1.5 } }, 'API keys, wallets, AI config, display preferences, and profile.'),
          React.createElement('input', { ref: cfgRef, type: 'file', style: { display: 'none' }, onChange: e => { if (e.target.files[0]) importFile('config', e.target.files[0]); } }),
          React.createElement('div', { style: { display: 'flex', gap: 10 } },
            React.createElement('button', { className: 'tv-btn', style: { fontSize: 12, padding: '5px 16px' }, onClick: () => { window.location = '/api/backup/config'; } }, 'Export Settings'),
            React.createElement('button', { className: 'tv-btn primary', style: { fontSize: 12, padding: '5px 16px' }, onClick: () => cfgRef.current && cfgRef.current.click(), disabled: importing.cfg }, importing.cfg ? 'Importing…' : 'Import Settings')
          )
        )
      ),

      // Warning notice
      React.createElement('div', { style: { marginTop: 20, background: 'var(--warn-soft)', border: '1px solid var(--warn)', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: 'var(--warn)' } },
        '⚠ Importing will overwrite existing data. Export a backup first. Database imports restart the app.'
      )
    ),
    React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      React.createElement('div', { className: 'tv-label', style: { marginBottom: 14, fontSize: 12 } }, 'Change Password'),
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 320 } },
        pwFields.map(([lbl, val, setter]) =>
          React.createElement('div', { key: lbl },
            React.createElement('label', { style: { fontSize: 12, color: 'var(--text4)', display: 'block', marginBottom: 4 } }, lbl),
            React.createElement('input', { type: 'password', value: val, onChange: e => setter(e.target.value), className: 'tv-input', style: { width: '100%' } })
          )
        ),
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12 } },
          React.createElement('button', { className: 'tv-btn', style: { fontSize: 12, padding: '5px 16px' }, onClick: changePassword }, 'Change Password'),
          React.createElement(StatusText, { msg: pwStatus })
        )
      )
    )
  );
}

// ── 8. Messaging ───────────────────────────────────────────────────────────
function MessagingSection() {
  const [cfg, setCfg] = useSState({ bot_token: '', chat_id: '', utc_hour: 8, enabled: false, content: { daily_digest: true, market_regime: false } });
  const [loading, setLoading] = useSState(true);
  const [saving, setSaving] = useSState(false);
  const [testing, setTesting] = useSState(false);
  const [status, setStatus] = useSState('');
  const [testResult, setTestResult] = useSState('');

  useSEffect(() => {
    api('/api/settings/telegram')
      .then(d => setCfg(prev => ({ ...prev, ...d })))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  function setField(k, v) { setCfg(c => ({ ...c, [k]: v })); }
  function setContent(k, v) { setCfg(c => ({ ...c, content: { ...(c.content || {}), [k]: v } })); }

  async function save() {
    setSaving(true); setStatus('');
    try {
      await api('/api/settings/telegram', { method: 'POST', body: JSON.stringify(cfg) });
      setStatus('Saved');
    } catch (e) { setStatus('Error saving'); }
    finally { setSaving(false); setTimeout(() => setStatus(''), 2500); }
  }

  async function sendTest() {
    setTesting(true); setTestResult('');
    try {
      await api('/api/settings/telegram/test', { method: 'POST' });
      setTestResult('Test sent');
    } catch (e) { setTestResult('Failed to send'); }
    finally { setTesting(false); }
  }

  if (loading) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…');

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
    React.createElement('div', { className: 'tv-label' }, 'Messaging'),
    React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 14 } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between' } },
          React.createElement('label', { style: { fontSize: 13, color: 'var(--text2)' } }, 'Telegram Notifications'),
          React.createElement(Toggle, { value: !!cfg.enabled, onChange: v => setField('enabled', v) })
        ),
        React.createElement('div', null,
          React.createElement('label', { style: { fontSize: 12, color: 'var(--text4)', display: 'block', marginBottom: 6 } }, 'Bot Token'),
          React.createElement(MaskedInput, { value: cfg.bot_token || '', onChange: v => setField('bot_token', v) })
        ),
        React.createElement('div', null,
          React.createElement('label', { style: { fontSize: 12, color: 'var(--text4)', display: 'block', marginBottom: 6 } }, 'Chat ID'),
          React.createElement('input', { type: 'text', value: cfg.chat_id || '', onChange: e => setField('chat_id', e.target.value), className: 'tv-input', style: { width: 200 } })
        ),
        React.createElement('div', null,
          React.createElement('label', { style: { fontSize: 12, color: 'var(--text4)', display: 'block', marginBottom: 6 } }, 'UTC Hour (0–23)'),
          React.createElement('input', { type: 'number', min: 0, max: 23, value: cfg.utc_hour != null ? cfg.utc_hour : 8, onChange: e => setField('utc_hour', Number(e.target.value)), className: 'tv-input', style: { width: 80 } })
        ),
        React.createElement('div', null,
          React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', marginBottom: 8 } }, 'Notification Content'),
          [['daily_digest', 'Daily Digest'], ['market_regime', 'Market Regime Assessment']].map(([k, lbl]) =>
            React.createElement('label', { key: k, style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text2)', cursor: 'pointer', marginBottom: 6 } },
              React.createElement('input', { type: 'checkbox', checked: !!((cfg.content || {})[k]), onChange: e => setContent(k, e.target.checked), style: { accentColor: 'var(--accent)' } }),
              lbl
            )
          )
        ),
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' } },
          React.createElement('button', { className: 'tv-btn', style: { fontSize: 12, padding: '5px 16px' }, onClick: save, disabled: saving }, saving ? 'Saving…' : 'Save'),
          React.createElement('button', { className: 'tv-btn', style: { fontSize: 12, padding: '5px 16px' }, onClick: sendTest, disabled: testing }, testing ? 'Sending…' : 'Send Test'),
          React.createElement(StatusText, { msg: status }),
          testResult && React.createElement(StatusText, { msg: testResult })
        )
      )
    )
  );
}

// ── Main Settings Screen ───────────────────────────────────────────────────
function SettingsScreen({ hideValues, setHideValues }) {
  const [active, setActive] = useSState('display');

  function renderSection() {
    switch (active) {
      case 'display':      return React.createElement(DisplaySection, { hideValues, setHideValues });
      case 'wallets':      return React.createElement(WalletsSection);
      case 'integrations': return React.createElement(IntegrationsSection);
      case 'ai':           return React.createElement(AIConfigSection);
      case 'documents':    return React.createElement(DocUploadsSection);
      case 'spotpnl':      return React.createElement(SpotPnLSection);
      case 'backup':       return React.createElement(BackupSection);
      case 'messaging':    return React.createElement(MessagingSection);
      default:             return null;
    }
  }

  return React.createElement('div', { style: { display: 'flex', minHeight: 'calc(100vh - 80px)' } },
    // Sidebar
    React.createElement('div', { style: { width: 220, flexShrink: 0, background: 'var(--panel)', borderRight: '1px solid var(--line)', paddingTop: 16 } },
      SETTINGS_SECTIONS.map(s =>
        React.createElement('button', {
          key: s.id, onClick: () => setActive(s.id),
          style: {
            display: 'block', width: '100%', textAlign: 'left',
            padding: '10px 20px', fontSize: 13, cursor: 'pointer', border: 'none',
            borderLeft: active === s.id ? '3px solid var(--accent)' : '3px solid transparent',
            background: active === s.id ? 'var(--panel3)' : 'transparent',
            color: active === s.id ? 'var(--text)' : 'var(--text2)',
            fontWeight: active === s.id ? 600 : 400,
            transition: 'all 0.12s',
          }
        }, s.label)
      )
    ),
    // Main content
    React.createElement('div', { style: { flex: 1, padding: 28, overflowY: 'auto' } },
      renderSection()
    )
  );
}

window.SettingsScreen = SettingsScreen;
