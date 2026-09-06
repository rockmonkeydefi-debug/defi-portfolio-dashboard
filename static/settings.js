/* ===== SETTINGS SCREEN ===== */

const { useState: useSState, useEffect: useSEffect, useRef: useSRef } = React;

const SETTINGS_SECTIONS = [
  { id: 'display',      label: 'Display Preferences' },
  { id: 'wallets',      label: 'Wallets' },
  { id: 'integrations', label: 'Integrations' },
  { id: 'ai',           label: 'AI Config' },
  { id: 'documents',    label: 'Document Uploads' },
  { id: 'spotpnl',      label: 'Price Sources & Contract Addresses' },
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
  const [valueBand, setValueBand] = useSState('');
  const [valueDanger, setValueDanger] = useSState('');
  const [valueSaving, setValueSaving] = useSState(false);
  const [valueStatus, setValueStatus] = useSState('');

  useSEffect(() => {
    api('/api/settings/display')
      .then(d => {
        if (d.dust_threshold != null) setDust(String(d.dust_threshold));
        if (d.lending_threshold != null) setLending(String(d.lending_threshold));
        if (d.maxfi_value_band_pct != null) setValueBand(String(d.maxfi_value_band_pct));
        if (d.maxfi_value_danger_pct != null) setValueDanger(String(d.maxfi_value_danger_pct));
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

  async function saveValueColors() {
    setValueSaving(true);
    setValueStatus('');
    try {
      // Both keys posted together (not per-field) so the server's
      // cross-field band < danger check always sees the effective pair,
      // never a stale saved value on one side of a partial update.
      await api('/api/settings/display', {
        method: 'POST',
        body: JSON.stringify({
          maxfi_value_band_pct: Number(valueBand),
          maxfi_value_danger_pct: Number(valueDanger),
        }),
      });
      setValueStatus('Saved');
    } catch (e) {
      setValueStatus('Error saving');
    } finally {
      setValueSaving(false);
      setTimeout(() => setValueStatus(''), 2500);
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
    ),

    // MaxFi Value Colors
    React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      React.createElement('div', { className: 'tv-label', style: { marginBottom: 14 } }, 'MaxFi Value Colors'),
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 14 } },
        React.createElement('div', null,
          React.createElement('label', { style: { fontSize: 12, color: 'var(--text4)', display: 'block', marginBottom: 6 } }, 'Neutral band (±%)'),
          React.createElement('input', { type: 'number', value: valueBand, onChange: e => setValueBand(e.target.value), className: 'tv-input', style: { width: 180 }, placeholder: '15' })
        ),
        React.createElement('div', null,
          React.createElement('label', { style: { fontSize: 12, color: 'var(--text4)', display: 'block', marginBottom: 6 } }, 'Danger threshold (%)'),
          React.createElement('input', { type: 'number', value: valueDanger, onChange: e => setValueDanger(e.target.value), className: 'tv-input', style: { width: 180 }, placeholder: '30' })
        ),
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12 } },
          React.createElement('button', { className: 'tv-btn', style: { fontSize: 12, padding: '5px 16px' }, onClick: saveValueColors, disabled: valueSaving }, valueSaving ? 'Saving…' : 'Save'),
          React.createElement(StatusText, { msg: valueStatus })
        )
      )
    )
  );
}

// ── 2. Wallets ─────────────────────────────────────────────────────────────

// api() throws new Error(<raw response text>) on a non-OK, non-401 response
// (see static/utils.js) - for this route that raw text is this subsystem's
// own {"error": "<prose>"} JSON, not a plain string, so it must be unwrapped
// the same way maxfi.js's mxExtractErr does. Never returns '' - a caller
// must never render an empty error.
function extractWalletError(e) {
  let msg = (e && e.message) ? e.message : String(e);
  try {
    const j = JSON.parse(msg);
    if (j && j.error) msg = j.error;
  } catch (e2) {}
  return msg || 'Failed to save';
}

function WalletsSection() {
  const [wallets, setWallets] = useSState([]);
  const [loading, setLoading] = useSState(true);
  const [newAddr, setNewAddr] = useSState('');
  const [newLabel, setNewLabel] = useSState('');
  const [adding, setAdding] = useSState(false);
  const [status, setStatus] = useSState('');
  // Per-wallet write state, keyed on ADDRESS (not array index - the list is
  // refetched and reordered by the backend's dict order, so an index-keyed
  // error would attach to the wrong row after a refetch). Shape per address:
  // { busy: bool, error: string|null }.
  const [rowState, setRowState] = useSState({});

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

  // Shared by the Visible and MaxFi toggles: applies `patch` optimistically,
  // sends it, and reconciles or reverts based on the real outcome.
  async function writeWallet(w, patch) {
    const addr = w.address;
    const previous = w; // snapshot to revert to - taken before the optimistic patch
    setWallets(prev => prev.map(x => x.address === addr ? Object.assign({}, x, patch) : x));
    setRowState(prev => Object.assign({}, prev, { [addr]: Object.assign({}, prev[addr], { busy: true }) }));
    try {
      const resp = await api(`/api/wallets/${addr}`, { method: 'PUT', body: JSON.stringify(patch) });
      if (resp === undefined || resp === null) {
        // api() returns undefined without throwing on a 401 (it redirects to
        // /login) - a naive await here would report a false success.
        setWallets(prev => prev.map(x => x.address === addr ? previous : x));
        setRowState(prev => Object.assign({}, prev, { [addr]: { busy: false, error: 'session expired' } }));
        return;
      }
      setRowState(prev => Object.assign({}, prev, { [addr]: { busy: false, error: null } }));
      fetchWallets(); // reconcile with the server rather than drift
    } catch (e) {
      setWallets(prev => prev.map(x => x.address === addr ? previous : x));
      setRowState(prev => Object.assign({}, prev, { [addr]: { busy: false, error: extractWalletError(e) } }));
    }
  }

  function toggleVisible(w) {
    return writeWallet(w, { visible: !w.visible });
  }

  function toggleMaxfi(w) {
    return writeWallet(w, { maxfi: !w.maxfi });
  }

  async function removeWallet(w) {
    if (!confirm(`Remove wallet "${w.label || maskAddr(w.address)}"?`)) return;
    try {
      const resp = await api(`/api/wallets/${w.address}`, { method: 'DELETE' });
      if (resp === undefined || resp === null) {
        setRowState(prev => Object.assign({}, prev, { [w.address]: { busy: false, error: 'session expired' } }));
        return;
      }
      fetchWallets();
    } catch (e) {
      setRowState(prev => Object.assign({}, prev, { [w.address]: { busy: false, error: extractWalletError(e) } }));
    }
  }

  async function addWallet() {
    if (!newAddr.trim()) return;
    setAdding(true);
    setStatus('');
    try {
      const resp = await api('/api/wallets', { method: 'POST', body: JSON.stringify({ address: newAddr.trim(), label: newLabel.trim() }) });
      if (resp === undefined || resp === null) {
        setStatus('session expired');
        setTimeout(() => setStatus(''), 2500);
        return;
      }
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
              React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '14px 1fr 1fr auto auto auto', gap: '0 14px', paddingBottom: 8, fontSize: 11, color: 'var(--text4)' } },
                React.createElement('div'),
                React.createElement('div', null, 'Label'),
                React.createElement('div', null, 'Address'),
                React.createElement('div', null, 'MaxFi'),
                React.createElement('div', null, 'Visible'),
                React.createElement('div')
              ),
              wallets.map((w, i) => {
                const rs = rowState[w.address] || {};
                return React.createElement('div', {
                  key: w.address || i,
                  style: { display: 'grid', gridTemplateColumns: '14px 1fr 1fr auto auto auto', gap: '0 14px', alignItems: 'center', borderTop: '1px solid var(--line)', padding: '8px 0', fontSize: 13, position: 'relative' },
                },
                  React.createElement('div', { style: { width: 10, height: 10, borderRadius: '50%', background: w.color || 'var(--accent)' } }),
                  React.createElement('div', { style: { color: 'var(--text2)' } }, w.label || '—'),
                  React.createElement('div', { style: { color: 'var(--text4)', fontFamily: 'Fira Code', fontSize: 12 } }, maskAddr(w.address)),
                  React.createElement('button', { className: 'tv-btn', style: { fontSize: 11, padding: '2px 10px', opacity: w.maxfi ? 1 : 0.5 }, disabled: !!rs.busy, onClick: () => toggleMaxfi(w) }, 'MaxFi'),
                  React.createElement('button', { className: 'tv-btn', style: { fontSize: 11, padding: '2px 10px', opacity: w.visible === false ? 0.5 : 1 }, disabled: !!rs.busy, onClick: () => toggleVisible(w) }, w.visible === false ? 'Hidden' : 'Visible'),
                  React.createElement('button', { className: 'tv-btn danger', style: { fontSize: 11, padding: '2px 10px' }, onClick: () => removeWallet(w) }, 'Remove'),
                  // Absolutely positioned so a failed write never reflows the
                  // row (or shifts the rows below it) - it overlays just
                  // beneath the row instead of growing its height.
                  rs.error && React.createElement('div', {
                    style: { position: 'absolute', top: '100%', left: 0, zIndex: 1, marginTop: 2,
                      background: 'var(--panel)', color: 'var(--fail)', fontSize: 11, pointerEvents: 'none',
                      padding: '3px 8px', borderRadius: 4, border: '1px solid var(--fail)', whiteSpace: 'nowrap' },
                  }, rs.error)
                );
              })
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
function DropZone({ category, categoryOptions, onUpload }) {
  const inputRef = useSRef(null);
  const [dragging, setDragging] = useSState(false);
  const [uploading, setUploading] = useSState(false);
  const [status, setStatus] = useSState('');
  const [selectedCategory, setSelectedCategory] = useSState(
    categoryOptions ? categoryOptions[0] : category
  );

  const effectiveCategory = categoryOptions ? selectedCategory : category;

  async function upload(file) {
    setUploading(true); setStatus('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('category', effectiveCategory);
      const resp = await fetch('/api/strategies/upload', { method: 'POST', body: fd });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || 'Upload failed');
      }
      setStatus('Uploaded');
      onUpload();
    } catch (e) { setStatus(e.message || 'Upload failed'); }
    finally { setUploading(false); setTimeout(() => setStatus(''), 4000); }
  }

  return React.createElement('div', null,
    categoryOptions && React.createElement('div', { style: { marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 } },
      React.createElement('span', { style: { fontSize: 12, color: 'var(--text4)' } }, 'Category:'),
      React.createElement('select', {
        value: selectedCategory,
        onChange: e => setSelectedCategory(e.target.value),
        onClick: e => e.stopPropagation(),
        style: { background: 'var(--panel2)', border: '1px solid var(--line)', borderRadius: 6, color: 'var(--text)', fontSize: 12, padding: '3px 8px', cursor: 'pointer', outline: 'none' },
      },
        categoryOptions.map(opt => React.createElement('option', { key: opt, value: opt }, opt))
      )
    ),
    React.createElement('div', {
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

  function DocGroup({ title, category, categoryOptions }) {
    const [open, setOpen] = useSState(false);
    const filtered = categoryOptions
      ? docs.filter(d => categoryOptions.includes(d.category))
      : docs.filter(d => d.category === category);
    return React.createElement('div', null,
      React.createElement('div', {
        onClick: () => setOpen(o => !o),
        style: { display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', userSelect: 'none' },
      },
        React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' } }, title),
        React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)' } }, `${filtered.length} doc${filtered.length !== 1 ? 's' : ''}`),
        React.createElement('span', { style: { fontSize: 12, color: 'var(--text4)', marginLeft: 2 } }, open ? '▾' : '▸')
      ),
      open && React.createElement('div', { style: { marginTop: 12 } },
        React.createElement(DropZone, { category, categoryOptions, onUpload: fetchDocs }),
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
      )
    );
  }

  if (loading) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…');

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
    React.createElement('div', { className: 'tv-label' }, 'Document Uploads'),
    React.createElement('div', { className: 'tv-card', style: { padding: 20 } }, React.createElement(DocGroup, { title: 'DeFi Strategy', categoryOptions: ['bear', 'bull', 'stablecoin', 'cashflow_other'] })),
    React.createElement('div', { className: 'tv-card', style: { padding: 20 } }, React.createElement(DocGroup, { title: 'Trading Strategy', category: 'trading' }))
  );
}

// ── 6. Price Sources & Contract Addresses ──────────────────────────────────
function SpotPnLSection() {
  const [tokens, setTokens] = useSState([]);
  const [loading, setLoading] = useSState(true);
  const [edits, setEdits] = useSState({});
  const [testResults, setTestResults] = useSState({});
  const [statuses, setStatuses] = useSState({});

  // Add-row (contract-first) form state.
  const [newAddress, setNewAddress] = useSState('');
  const [resolving, setResolving] = useSState(false);
  const [resolveResult, setResolveResult] = useSState(null);
  const [resolveError, setResolveError] = useSState('');
  const [newSymbol, setNewSymbol] = useSState('');
  const [newCgId, setNewCgId] = useSState('');
  const [newPriceSource, setNewPriceSource] = useSState('coingecko');
  const [addSaving, setAddSaving] = useSState(false);
  const [addStatus, setAddStatus] = useSState('');
  // Which pool row is currently previewed. DISPLAY ONLY — never sent to the
  // server; see saveNewRow, which posts only symbol/contract_address/chain/
  // cg_id/price_source and never reads this index or any pool field.
  const [selectedPoolIdx, setSelectedPoolIdx] = useSState(0);

  function loadTokens() {
    return api('/api/spot/token-config')
      .then(d => {
        const list = Array.isArray(d) ? d : (d.tokens || []);
        setTokens(list);
        const e = {};
        list.forEach(t => { e[t.symbol] = { contract_address: t.contract_address || '', price_source: t.price_source || 'coingecko', cg_id: t.cg_id || '' }; });
        setEdits(e);
      })
      .catch(() => setTokens([]));
  }

  useSEffect(() => { loadTokens().finally(() => setLoading(false)); }, []);

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
        // cg_id now sends the EDITED value (edits[sym] is seeded from the
        // loaded row and only diverges once the user types) — previously this
        // always sent orig.cg_id, so cg_id could never actually be changed.
        cg_id:            e.cg_id            || '',
        chain:            orig.chain          || '',
        notes:            orig.notes          || '',
      }) });
      setStatuses(s => ({ ...s, [sym]: 'Saved' }));
    } catch (e) { setStatuses(s => ({ ...s, [sym]: 'Error' })); }
    setTimeout(() => setStatuses(s => ({ ...s, [sym]: '' })), 2500);
  }

  async function deleteToken(sym) {
    if (!confirm(`Remove the price-source config for ${sym}? This does NOT delete any transactions or affect your position — it only removes how the price is looked up for this symbol.`)) return;
    setStatuses(s => ({ ...s, [sym]: 'Deleting…' }));
    try {
      await api(`/api/spot/token-config/${sym}`, { method: 'DELETE' });
      await loadTokens();
    } catch (e) {
      setStatuses(s => ({ ...s, [sym]: 'Error' }));
      setTimeout(() => setStatuses(s => ({ ...s, [sym]: '' })), 2500);
    }
  }

  async function resolveContract() {
    const addr = newAddress.trim();
    if (!addr) return;
    setResolving(true);
    setResolveError('');
    setResolveResult(null);
    setSelectedPoolIdx(0);
    try {
      const d = await api(`/api/spot/resolve-contract/${addr}`);
      setResolveResult(d);
      setNewSymbol((d.symbol || '').toUpperCase());
      setNewCgId(d.cg_id || '');
      setNewPriceSource(d.source_suggestion || 'coingecko');
      // Default the preview to the auto-picked (deepest-liquidity) pool.
      const winnerIdx = Array.isArray(d.pools) ? d.pools.findIndex(p => p.is_winner) : -1;
      setSelectedPoolIdx(winnerIdx >= 0 ? winnerIdx : 0);
    } catch (e) {
      setResolveError('Could not reach the resolver. Try again.');
    }
    setResolving(false);
  }

  async function saveNewRow() {
    // CRITICAL: spot_token_config.symbol is UNIQUE but case-SENSITIVE (no
    // COLLATE NOCASE) and every pricing path queries it upper-cased. A
    // lowercase symbol here would silently create a shadow duplicate row
    // that no pricing code would ever find.
    const symbol = newSymbol.trim().toUpperCase();
    if (!symbol) { setAddStatus('Symbol is required'); setTimeout(() => setAddStatus(''), 2500); return; }
    setAddSaving(true);
    try {
      // Note: selectedPoolIdx / the pool picker is display-only and is
      // deliberately NOT read here. Pricing always re-derives the deepest
      // pool itself, live, on every call — see _get_dexscreener_price.
      await api('/api/spot/token-config', { method: 'POST', body: JSON.stringify({
        symbol:           symbol,
        contract_address: newAddress.trim(),
        chain:            (resolveResult && resolveResult.chain) || '',
        cg_id:            newCgId || '',
        price_source:     newPriceSource || 'coingecko',
        notes:            '',
      }) });
      setAddStatus('Saved');
      setNewAddress(''); setResolveResult(null); setResolveError('');
      setNewSymbol(''); setNewCgId(''); setNewPriceSource('coingecko');
      setSelectedPoolIdx(0);
      await loadTokens();
    } catch (e) {
      setAddStatus('Error');
    }
    setAddSaving(false);
    setTimeout(() => setAddStatus(''), 2500);
  }

  if (loading) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…');

  const addPanel = React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { style: { fontSize: 13, fontWeight: 600, color: 'var(--text2)', marginBottom: 14 } }, 'Add a token'),
    React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' } },
      React.createElement('input', {
        type: 'text', value: newAddress, onChange: ev => setNewAddress(ev.target.value),
        onKeyDown: ev => { if (ev.key === 'Enter') resolveContract(); },
        className: 'tv-input', placeholder: 'Paste contract address (0x…)',
        style: { flex: 1, minWidth: 220, maxWidth: 420, fontSize: 13 },
      }),
      React.createElement('button', {
        className: 'tv-btn', style: { fontSize: 13, padding: '6px 16px' },
        onClick: resolveContract, disabled: resolving || !newAddress.trim(),
      }, resolving ? 'Resolving…' : 'Resolve')
    ),
    resolveError && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13, marginTop: 10 } }, resolveError),
    resolveResult && (() => {
      // pools (backend commit fb7b2b1) is every matching liquidity pool,
      // winner included; every current response shape always sends it
      // (as [] or populated) — never absent. Still coerced defensively
      // rather than assumed present, in case of a version-skewed deploy:
      // pools absent or malformed renders nothing in this whole area below.
      const pools = Array.isArray(resolveResult.pools) ? resolveResult.pools : null;
      const selectedPool = (pools && pools[selectedPoolIdx]) ? pools[selectedPoolIdx] : null;
      const displayPrice = selectedPool ? selectedPool.price_usd : resolveResult.price_usd;
      const displayLiquidity = selectedPool ? selectedPool.liquidity_usd : resolveResult.winner_liquidity_usd;
      const displayChain = selectedPool ? selectedPool.chain : resolveResult.chain;

      return React.createElement('div', { style: { marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--line)' } },
        resolveResult.resolved
          ? React.createElement('div', { style: { color: 'var(--text3)', fontSize: 13, marginBottom: 10 } },
              `Resolved via ${resolveResult.source_suggestion}: ${resolveResult.name || '(no name)'} on ${displayChain || '?'}`
              + (displayPrice != null ? ` — $${fmtNum(displayPrice, 6)}` : ' — price unavailable')
              + (displayLiquidity != null ? ` — $${fmtNum(displayLiquidity, 0)} liquidity` : ''))
          : React.createElement('div', { style: { color: 'var(--text3)', fontSize: 13, marginBottom: 10 } },
              resolveResult.reason || 'Not resolved. You can still add it manually below.'),

        // New pool picker (Commit 1's "pools" field present and non-empty).
        pools && pools.length > 0 && React.createElement('div', { style: { marginBottom: 14 } },
          React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)', marginBottom: 6 } }, 'Liquidity pools for this token'),
          React.createElement('div', { style: { border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden' } },
            pools.map((p, idx) => {
              const selected = idx === selectedPoolIdx;
              return React.createElement('div', {
                key: p.pair_address || `${p.chain}-${p.dex_id}-${idx}`,
                onClick: () => setSelectedPoolIdx(idx),
                style: {
                  display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10,
                  padding: '8px 10px', cursor: 'pointer',
                  background: selected ? 'var(--panel3)' : 'transparent',
                  borderBottom: '2px solid var(--line)',
                  fontWeight: selected ? 700 : 400,
                },
              },
                React.createElement('span', { style: { fontSize: 13, color: 'var(--accent)', width: 12, flexShrink: 0 } }, selected ? '●' : ''),
                React.createElement('span', { style: { fontSize: 12, color: 'var(--text2)', minWidth: 100 } }, p.dex_id || '(unknown DEX)'),
                React.createElement('span', { style: { fontSize: 12, color: 'var(--text2)', fontFamily: 'Fira Code', minWidth: 120 } },
                  `${resolveResult.symbol || '?'} / ${p.quote_symbol || '?'}`),
                React.createElement('span', { style: { fontSize: 12, color: 'var(--text3)', minWidth: 70 } }, p.chain || '?'),
                React.createElement('span', { style: { fontSize: 12, color: 'var(--text2)', fontFamily: 'Fira Code', minWidth: 100 } },
                  p.liquidity_usd != null ? `$${fmtNum(p.liquidity_usd, 0)}` : '—'),
                React.createElement('span', { style: { fontSize: 12, color: 'var(--text2)', fontFamily: 'Fira Code' } },
                  p.price_usd != null ? `$${fmtNum(p.price_usd, 6)}` : '—'),
                p.is_winner && React.createElement('span', { style: { fontSize: 12, color: 'var(--ok)', fontWeight: 700, marginLeft: 'auto' } }, 'Deepest liquidity (auto)')
              );
            })
          ),
          React.createElement('div', { style: { color: 'var(--text3)', fontSize: 13, marginTop: 8 } },
            'Pricing always uses the deepest-liquidity pool automatically, every time it looks up a price. Clicking a row above only previews it here — it is not saved and does not pin a pool.')
        ),

        // A non-winner-pools summary would render here if pools were ever
        // absent from the response — but that condition is unreachable
        // against any current response shape (pools is always sent, as []
        // or populated), and there is no other field left to build such a
        // summary from, so nothing renders in that case: same "render
        // nothing" outcome as before this migration.

        React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'flex-end' } },
        React.createElement('div', null,
          React.createElement('label', { style: { fontSize: 13, color: 'var(--text3)', display: 'block', marginBottom: 4 } }, 'Symbol (editable)'),
          React.createElement('input', {
            type: 'text', value: newSymbol, onChange: ev => setNewSymbol(ev.target.value),
            className: 'tv-input', placeholder: 'e.g. CVX', style: { width: 120, fontSize: 13 },
          })
        ),
        React.createElement('div', null,
          React.createElement('label', { style: { fontSize: 13, color: 'var(--text3)', display: 'block', marginBottom: 4 } }, 'Price source'),
          React.createElement('select', {
            value: newPriceSource, onChange: ev => setNewPriceSource(ev.target.value),
            className: 'tv-input', style: { width: 130, fontSize: 13 },
          }, ['coingecko', 'dexscreener', 'manual'].map(s => React.createElement('option', { key: s, value: s }, s)))
        ),
        newPriceSource === 'coingecko' && React.createElement('div', null,
          React.createElement('label', { style: { fontSize: 13, color: 'var(--text3)', display: 'block', marginBottom: 4 } }, 'CoinGecko id'),
          React.createElement('input', {
            type: 'text', value: newCgId, onChange: ev => setNewCgId(ev.target.value),
            className: 'tv-input', placeholder: 'e.g. convex-finance', style: { width: 160, fontSize: 13 },
          })
        ),
        React.createElement('button', {
          className: 'tv-btn primary', style: { fontSize: 13, padding: '6px 16px' },
          onClick: saveNewRow, disabled: addSaving || !newSymbol.trim(),
        }, addSaving ? 'Saving…' : 'Save'),
        React.createElement(StatusText, { msg: addStatus })
      )
      );
    })()
  );

  const existingRows = React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    tokens.length === 0
      ? React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'No tokens configured')
      : tokens.map((tok, i) => {
          const e = edits[tok.symbol] || { contract_address: '', price_source: 'coingecko', cg_id: '' };
          return React.createElement('div', { key: tok.symbol, style: { borderTop: i > 0 ? '1px solid var(--line)' : 'none', padding: '12px 0' } },
            React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10 } },
              React.createElement('span', { style: { fontSize: 13, fontWeight: 600, color: 'var(--text)', width: 72, flexShrink: 0 } }, tok.symbol),
              React.createElement('input', { type: 'text', value: e.contract_address, onChange: ev => setEdit(tok.symbol, 'contract_address', ev.target.value), className: 'tv-input', placeholder: 'Contract override (0x…)', style: { flex: 1, minWidth: 180, maxWidth: 420, fontSize: 12 } }),
              React.createElement('select', { value: e.price_source, onChange: ev => setEdit(tok.symbol, 'price_source', ev.target.value), className: 'tv-input', style: { width: 130, fontSize: 12 } },
                ['coingecko', 'dexscreener', 'manual'].map(s => React.createElement('option', { key: s, value: s }, s))
              ),
              e.price_source === 'coingecko' && React.createElement('input', {
                type: 'text', value: e.cg_id || '', onChange: ev => setEdit(tok.symbol, 'cg_id', ev.target.value),
                className: 'tv-input', placeholder: 'CoinGecko id', style: { width: 140, fontSize: 12 },
              }),
              React.createElement('button', { className: 'tv-btn', style: { fontSize: 11, padding: '3px 10px' }, onClick: () => testPrice(tok.symbol) }, 'Test'),
              React.createElement('button', { className: 'tv-btn', style: { fontSize: 11, padding: '3px 10px' }, onClick: () => saveToken(tok.symbol) }, 'Save'),
              React.createElement('button', { className: 'tv-btn danger', style: { fontSize: 12, padding: '3px 10px' }, onClick: () => deleteToken(tok.symbol) }, 'Delete'),
              statuses[tok.symbol] && React.createElement(StatusText, { msg: statuses[tok.symbol] }),
              testResults[tok.symbol] && React.createElement('span', { style: { fontSize: 11, color: 'var(--text2)', fontFamily: 'Fira Code' } }, testResults[tok.symbol])
            )
          );
        })
  );

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
    React.createElement('div', { className: 'tv-label' }, 'Price Sources & Contract Addresses'),
    React.createElement('div', { style: { fontSize: 12, color: '#c9d1d9', lineHeight: 1.5, maxWidth: 720, marginBottom: 8 } },
      'Live Holdings prices each position using the chain and contract address stored on its own transactions, not the address below. The dropdown here selects the price source (DexScreener, CoinGecko, or manual). The address below is used by the Test button, and as a fallback when a position has no address of its own.'),
    addPanel,
    existingRows
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
  const [cfg, setCfg] = useSState({ bot_token: '', chat_id: '', utc_hour: 8, enabled: false, content: { daily_digest: true, market_regime: true } });
  const [loading, setLoading] = useSState(true);
  const [saving, setSaving] = useSState(false);
  const [testing, setTesting] = useSState(false);
  const [saveStatus, setSaveStatus] = useSState('');
  const [testResult, setTestResult] = useSState('');
  const [testOk, setTestOk] = useSState(false);

  useSEffect(() => {
    api('/api/settings/telegram')
      .then(d => setCfg(prev => ({ ...prev, ...d })))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  function setField(k, v) { setCfg(c => ({ ...c, [k]: v })); }
  function setContent(k, v) { setCfg(c => ({ ...c, content: { ...(c.content || {}), [k]: v } })); }

  async function save() {
    setSaving(true); setSaveStatus('');
    try {
      await api('/api/settings/telegram', { method: 'POST', body: JSON.stringify(cfg) });
      setSaveStatus('Saved ✓');
    } catch (e) { setSaveStatus('Error saving'); }
    finally { setSaving(false); setTimeout(() => setSaveStatus(''), 2000); }
  }

  async function sendTest() {
    setTesting(true); setTestResult(''); setTestOk(false);
    try {
      await api('/api/settings/telegram/test', { method: 'POST' });
      setTestResult('Test message sent'); setTestOk(true);
    } catch (e) { setTestResult('Failed to send'); setTestOk(false); }
    finally { setTesting(false); }
  }

  if (loading) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…');

  const content = cfg.content || {};

  return React.createElement('div', { className: 'tv-card', style: { padding: 24 } },

    // Header
    React.createElement('div', { style: { fontSize: 16, fontWeight: 700, color: 'var(--accent)', marginBottom: 6 } }, '📨  Telegram Notifications'),
    React.createElement('div', { style: { fontSize: 13, color: 'var(--text4)', marginBottom: 22, lineHeight: 1.55, maxWidth: 640 } },
      'Receive daily portfolio digests and market regime assessments via Telegram. Create a bot with @BotFather to get your bot token.'
    ),

    // Four-column input row
    React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 } },

      // Col 1: Bot Token
      React.createElement('div', null,
        React.createElement('div', { className: 'tv-label', style: { marginBottom: 6 } }, 'BOT TOKEN'),
        React.createElement('input', {
          type: 'password',
          value: cfg.bot_token || '',
          onChange: e => setField('bot_token', e.target.value),
          className: 'tv-input',
          placeholder: 'Paste value',
          style: { width: '100%' },
        })
      ),

      // Col 2: Chat ID
      React.createElement('div', null,
        React.createElement('div', { className: 'tv-label', style: { marginBottom: 6 } }, 'CHAT ID'),
        React.createElement('input', {
          type: 'text',
          value: cfg.chat_id || '',
          onChange: e => setField('chat_id', e.target.value),
          className: 'tv-input',
          placeholder: 'Paste value',
          style: { width: '100%' },
        })
      ),

      // Col 3: Schedule UTC Hour
      React.createElement('div', null,
        React.createElement('div', { className: 'tv-label', style: { marginBottom: 6 } }, 'SCHEDULE (UTC HOUR)'),
        React.createElement('input', {
          type: 'number',
          min: 0, max: 23,
          value: cfg.utc_hour != null ? cfg.utc_hour : 8,
          onChange: e => setField('utc_hour', Number(e.target.value)),
          className: 'tv-input',
          style: { width: '100%' },
        })
      ),

      // Col 4: Enabled dropdown
      React.createElement('div', null,
        React.createElement('div', { className: 'tv-label', style: { marginBottom: 6 } }, 'ENABLED'),
        React.createElement('select', {
          value: cfg.enabled ? 'enabled' : 'disabled',
          onChange: e => setField('enabled', e.target.value === 'enabled'),
          className: 'tv-input',
          style: { width: '100%' },
        },
          React.createElement('option', { value: 'enabled' }, 'Enabled'),
          React.createElement('option', { value: 'disabled' }, 'Disabled')
        )
      )
    ),

    // Notification Content
    React.createElement('div', { style: { fontSize: 13, fontWeight: 600, color: 'var(--accent)', marginBottom: 12 } }, 'Notification Content'),
    React.createElement('div', { style: { display: 'flex', gap: 28, marginBottom: 24 } },
      [['daily_digest', '✓ Daily Digest'], ['market_regime', '✓ Market Regime Assessment']].map(([k, lbl]) =>
        React.createElement('label', { key: k, style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text2)', cursor: 'pointer' } },
          React.createElement('input', {
            type: 'checkbox',
            checked: !!content[k],
            onChange: e => setContent(k, e.target.checked),
            style: { accentColor: 'var(--accent)', width: 15, height: 15 },
          }),
          lbl
        )
      )
    ),

    // Button row
    React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' } },
      React.createElement('button', { className: 'tv-btn', style: { fontSize: 13, padding: '6px 20px' }, onClick: save, disabled: saving },
        saving ? 'Saving…' : 'Save'
      ),
      React.createElement('button', { className: 'tv-btn primary', style: { fontSize: 13, padding: '6px 20px' }, onClick: sendTest, disabled: testing },
        testing ? 'Sending…' : 'Send Test Message'
      ),
      saveStatus && React.createElement('span', { style: { fontSize: 12, color: saveStatus.includes('✓') ? 'var(--ok)' : 'var(--fail)' } }, saveStatus),
      testResult && React.createElement('span', { style: { fontSize: 12, color: testOk ? 'var(--ok)' : 'var(--fail)' } }, testResult)
    )
  );
}

// ── Main Settings Screen ───────────────────────────────────────────────────
function SettingsScreen({ hideValues, setHideValues }) {
  // Deliberately non-sticky one-shot jump: the Contracts link on the Spot P&L
  // screen sets window.__settingsSectionJump right before switching to this
  // tab. Read-and-clear here means the jump fires exactly once - every
  // subsequent visit to Settings opens on Display Preferences as it always
  // has, unlike portfolioSubTab and spotSubTab, which persist to localStorage
  // and are sticky by design. This only works because SettingsScreen
  // unmounts when you leave the Settings tab (app.js renders exactly one
  // active screen, never all screens hidden by CSS) - so this initializer
  // re-runs fresh on every visit.
  const [active, setActive] = useSState(() => {
    const jump = window.__settingsSectionJump;
    window.__settingsSectionJump = undefined;
    return jump || 'display';
  });

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

/* ===== TRADING SETTINGS (Scanner Rules) ===== */
function TradingSettingsScreen() {
  const [prompt, setPrompt] = useSState('');
  const [loading, setLoading] = useSState(true);
  const [saving, setSaving] = useSState(false);
  const [saved, setSaved] = useSState(false);
  const [error, setError] = useSState(null);

  useSEffect(() => {
    api('/api/trading/scanner-prompt')
      .then(r => { setPrompt(r.prompt || ''); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  async function save() {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      await api('/api/trading/scanner-prompt', {
        method: 'POST',
        body: JSON.stringify({ prompt }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  if (loading) return React.createElement('div', { className: 'tv-label', style: { padding: 32 } }, 'Loading…');

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 16, padding: '16px 0', maxWidth: 860 } },
    React.createElement('div', { className: 'tv-card' },
      React.createElement('div', { style: { marginBottom: 4 } },
        React.createElement('span', { style: { fontSize: 15, fontWeight: 600, color: '#f0a500' } }, 'Scanner Rules'),
      ),
      React.createElement('div', { style: { fontSize: 13, color: 'var(--text4)', marginBottom: 14 } },
        'ICT/SMC evaluation instructions sent to Claude on every scan. Edit to tune signal criteria.'
      ),
      error && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13, marginBottom: 8 } }, error),
      React.createElement('textarea', {
        className: 'tv-input',
        value: prompt,
        rows: 28,
        style: {
          width: '100%', boxSizing: 'border-box', resize: 'vertical',
          fontFamily: 'Fira Code, monospace', fontSize: 12, lineHeight: 1.6,
          minHeight: 500,
        },
        onChange: e => setPrompt(e.target.value),
      }),
      React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12, marginTop: 12 } },
        React.createElement('button', {
          className: saving ? 'tv-btn' : 'tv-btn primary',
          disabled: saving,
          onClick: save,
        }, saving ? 'Saving…' : 'Save Rules'),
        saved && React.createElement('span', { style: { color: 'var(--ok)', fontSize: 13 } }, 'Saved ✓')
      )
    )
  );
}

window.TradingSettingsScreen = TradingSettingsScreen;
