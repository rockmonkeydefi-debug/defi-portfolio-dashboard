/* ===== TRADING TOOLS ===== */

const { useState: useTdS, useEffect: useTdE, useCallback: useTdCb, useMemo: useTdMemo, useRef: useTdRef } = React;

const STATUS_CONFIG = {
  active:   { color: '#f0a500', label: 'Active'   },
  forming:  { color: '#f0e000', label: 'Forming'  },
  watching: { color: '#4e9eff', label: 'Watching' },
  quiet:    { color: 'var(--text4)', label: 'Quiet' },
};

const TV_INTERVAL = { '1d': 'D', '4h': '240', '1h': '60', '15m': '15', '5m': '5' };

const INTERVAL_COLORS = {
  '1d': '#7B2FBE', '4h': '#1565C0', '1h': '#00695C', '15m': '#2E7D32', '5m': '#F57F17',
};

const CONCEPT_CATS = [
  'entry_signals','risk_management','position_sizing','market_regimes',
  'lp_strategy','defi_strategy','technical_analysis','macro_context','mindset',
];

const MOOD_LABELS = ['','😞','😕','😐','🙂','😊'];

function SparkLine({ closes, width = 60, height = 24 }) {
  if (!closes || closes.length < 2) return null;
  const mn = Math.min(...closes);
  const mx = Math.max(...closes);
  const range = mx - mn || 1;
  const pts = closes.map((v, i) => {
    const x = (i / (closes.length - 1)) * width;
    const y = height - ((v - mn) / range) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const up = closes[closes.length - 1] >= closes[0];
  return React.createElement('svg', { width, height, style: { display: 'block' } },
    React.createElement('polyline', {
      points: pts,
      fill: 'none',
      stroke: up ? 'var(--ok)' : 'var(--fail)',
      strokeWidth: 1.5,
      strokeLinejoin: 'round',
    })
  );
}

function ConfBar({ score }) {
  const color = score >= 70 ? 'var(--accent)' : score >= 50 ? '#f0a500' : 'var(--text4)';
  return React.createElement('div', { style: { width: 80, height: 4, background: 'var(--line)', borderRadius: 2, overflow: 'hidden' } },
    React.createElement('div', {
      style: { width: `${Math.min(100, score || 0)}%`, height: '100%', background: color, borderRadius: 2 }
    })
  );
}

function normalizeSymbol(raw) {
  const s = raw.trim().toUpperCase();
  const QUOTE_SUFFIXES = ['USDT', 'USDC', 'BTC', 'ETH'];
  if (QUOTE_SUFFIXES.some(q => s.endsWith(q))) return s;
  return s + 'USDT';
}

/* ===== SCANNER ===== */
function ScannerScreen() {
  const [watchlist, setWatchlist] = useTdS([]);
  const [signals, setSignals] = useTdS([]);
  const [selected, setSelected] = useTdS(null);
  const [running, setRunning] = useTdS(false);
  const [loading, setLoading] = useTdS(true);
  const [showAdd, setShowAdd] = useTdS(false);
  const [newSymbol, setNewSymbol] = useTdS('');
  const [newHtf, setNewHtf] = useTdS('4h');
  const [newLtf, setNewLtf] = useTdS('15m');
  const [notes, setNotes] = useTdS({});
  const [error, setError] = useTdS(null);
  const [lastScanAt, setLastScanAt] = useTdS(null);

  function load() {
    return Promise.all([
      api('/api/trading/scanner/watchlist'),
      api('/api/trading/scanner/signals?limit=50'),
    ]).then(([wl, sig]) => {
      setWatchlist(wl.watchlist || []);
      const sigs = sig.signals || [];
      setSignals(sigs);
      const latest = sigs.reduce((acc, s) => {
        const t = s.scanned_at || s.detected_at;
        return (!acc || t > acc) ? t : acc;
      }, null);
      setLastScanAt(latest);
      const n = {};
      sigs.forEach(s => { n[s.symbol] = s.notes || ''; });
      setNotes(n);
      setLoading(false);
    }).catch(e => { setError(e.message); setLoading(false); });
  }

  useTdE(() => { load(); }, []);

  function saveNote(symbol, value) {
    const item = watchlist.find(w => w.symbol === symbol);
    if (!item) return;
    api(`/api/trading/scanner/watchlist/${item.id}`, {
      method: 'PUT',
      body: JSON.stringify({ notes: value }),
    }).catch(() => {});
  }

  function addSymbol() {
    const sym = normalizeSymbol(newSymbol);
    if (!sym) return;
    api('/api/trading/scanner/watchlist', {
      method: 'POST',
      body: JSON.stringify({ symbol: sym, htf_timeframe: newHtf, ltf_timeframe: newLtf }),
    }).then(() => { setNewSymbol(''); setShowAdd(false); load(); })
      .catch(e => setError(e.message));
  }

  function removeSymbol(id) {
    api(`/api/trading/scanner/watchlist/${id}`, { method: 'DELETE' })
      .then(() => { setSelected(null); load(); })
      .catch(e => setError(e.message));
  }

  async function runScan() {
    setRunning(true);
    setError(null);
    try {
      await api('/api/trading/scanner/run', { method: 'POST', body: '{}' });
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  }

  const sortedSignals = useTdMemo(() => {
    const ORDER = { active: 0, forming: 1, watching: 2, quiet: 3 };
    return [...signals].sort((a, b) => {
      const os = (ORDER[a.status] ?? 3) - (ORDER[b.status] ?? 3);
      if (os !== 0) return os;
      return (b.confidence_score || 0) - (a.confidence_score || 0);
    });
  }, [signals]);

  const allRows = useTdMemo(() => {
    const sigMap = {};
    signals.forEach(s => { sigMap[s.symbol] = s; });
    const rows = sortedSignals.map(s => ({ ...s, _hasSignal: true }));
    watchlist.forEach(w => {
      if (!sigMap[w.symbol]) rows.push({ ...w, _hasSignal: false, status: 'quiet' });
    });
    return rows;
  }, [sortedSignals, signals, watchlist]);

  function timeAgo(isoStr) {
    if (!isoStr) return null;
    const diff = Date.now() - new Date(isoStr).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  }

  if (loading) return React.createElement('div', { className: 'tv-label', style: { padding: 32 } }, 'Loading…');

  const sel = selected ? (signals.find(s => s.symbol === selected) || watchlist.find(w => w.symbol === selected)) : null;
  const wlSel = sel ? watchlist.find(w => w.symbol === sel.symbol) : null;
  const statusCounts = {};
  signals.forEach(s => { statusCounts[s.status] = (statusCounts[s.status] || 0) + 1; });

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 12, padding: '16px 0' } },
    error && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13, padding: '0 4px' } }, error),

    /* Top bar */
    React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
      ['active', 'forming', 'watching'].map(st => {
        const cnt = statusCounts[st] || 0;
        if (!cnt) return null;
        const cfg = STATUS_CONFIG[st];
        return React.createElement('span', {
          key: st,
          style: {
            fontSize: 11, padding: '2px 8px', borderRadius: 10,
            background: `${cfg.color}22`, color: cfg.color,
            border: `1px solid ${cfg.color}44`,
          }
        }, `${cnt} ${cfg.label}`);
      }),
      React.createElement('div', { style: { flex: 1 } }),
      lastScanAt && React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)' } },
        `Last scan ${timeAgo(lastScanAt)}`),
      React.createElement('button', {
        className: running ? 'tv-btn' : 'tv-btn primary',
        disabled: running || watchlist.length === 0,
        onClick: runScan,
        style: { fontSize: 12, padding: '4px 12px' },
      }, running ? 'Scanning…' : '▶ Scan'),
      React.createElement('button', {
        className: 'tv-btn',
        onClick: () => setShowAdd(v => !v),
        style: { fontSize: 12, padding: '4px 12px' },
      }, showAdd ? '✕' : '+ Add')
    ),

    /* Inline add form */
    showAdd && React.createElement('div', {
      className: 'tv-card',
      style: { display: 'flex', gap: 8, alignItems: 'center', padding: '10px 14px' }
    },
      React.createElement('input', {
        className: 'tv-input',
        placeholder: 'e.g. BTC or ETHUSDT',
        value: newSymbol,
        style: { flex: 1 },
        onChange: e => setNewSymbol(e.target.value),
        onKeyDown: e => e.key === 'Enter' && addSymbol(),
        autoFocus: true,
      }),
      React.createElement('label', { style: { fontSize: 11, color: 'var(--text4)', whiteSpace: 'nowrap' } }, 'HTF'),
      React.createElement('select', {
        className: 'tv-input', value: newHtf, style: { width: 68 },
        onChange: e => setNewHtf(e.target.value),
      }, ['1d', '4h', '1h'].map(v => React.createElement('option', { key: v, value: v }, v))),
      React.createElement('label', { style: { fontSize: 11, color: 'var(--text4)', whiteSpace: 'nowrap' } }, 'LTF'),
      React.createElement('select', {
        className: 'tv-input', value: newLtf, style: { width: 68 },
        onChange: e => setNewLtf(e.target.value),
      }, ['1h', '15m', '5m'].map(v => React.createElement('option', { key: v, value: v }, v))),
      React.createElement('button', { className: 'tv-btn primary', onClick: addSymbol }, '+ Add')
    ),

    /* Two-column body */
    React.createElement('div', { style: { display: 'flex', gap: 14 } },

      /* Left 60% — signal table */
      React.createElement('div', { style: { flex: '0 0 60%', minWidth: 0 } },
        allRows.length === 0
          ? React.createElement('div', { className: 'tv-card', style: { color: 'var(--text4)', fontSize: 13, padding: 32, textAlign: 'center' } },
              'No symbols in watchlist. Add some and run a scan.')
          : React.createElement('div', { className: 'tv-card', style: { padding: 0, overflow: 'hidden' } },
              React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse' } },
                React.createElement('thead', null,
                  React.createElement('tr', { style: { borderBottom: '1px solid var(--line)' } },
                    ['Symbol', 'TF', 'Status', 'Conf', 'Price', 'Trend'].map(h =>
                      React.createElement('th', {
                        key: h,
                        style: {
                          padding: '8px 10px', textAlign: 'left', fontSize: 10,
                          color: 'var(--text4)', fontWeight: 500,
                          letterSpacing: '0.05em', textTransform: 'uppercase',
                        }
                      }, h)
                    )
                  )
                ),
                React.createElement('tbody', null,
                  allRows.map(row => {
                    const isSel = selected === row.symbol;
                    const cfg = STATUS_CONFIG[row.status] || STATUS_CONFIG.quiet;
                    const htf = row.htf_timeframe || row.interval || '4h';
                    const ltf = row.ltf_timeframe || '15m';
                    const closes = row.recent_closes_ltf || row.recent_closes_htf || [];
                    return React.createElement('tr', {
                      key: row.symbol,
                      onClick: () => setSelected(isSel ? null : row.symbol),
                      style: {
                        cursor: 'pointer',
                        borderBottom: '1px solid var(--line)',
                        background: isSel ? 'var(--panel3)' : 'transparent',
                      }
                    },
                      React.createElement('td', { style: { padding: '9px 10px' } },
                        React.createElement('strong', { style: { fontSize: 13 } }, row.symbol)
                      ),
                      React.createElement('td', { style: { padding: '9px 10px' } },
                        React.createElement('span', {
                          style: {
                            fontSize: 10, padding: '1px 5px', borderRadius: 3, marginRight: 3,
                            background: `${INTERVAL_COLORS[htf] || '#555'}33`,
                            color: INTERVAL_COLORS[htf] || 'var(--text3)',
                          }
                        }, htf),
                        React.createElement('span', {
                          style: {
                            fontSize: 10, padding: '1px 5px', borderRadius: 3,
                            background: `${INTERVAL_COLORS[ltf] || '#555'}33`,
                            color: INTERVAL_COLORS[ltf] || 'var(--text3)',
                          }
                        }, ltf)
                      ),
                      React.createElement('td', { style: { padding: '9px 10px' } },
                        row._hasSignal
                          ? React.createElement('span', {
                              style: {
                                fontSize: 11, padding: '2px 7px', borderRadius: 10,
                                background: `${cfg.color}22`, color: cfg.color,
                              }
                            }, cfg.label)
                          : React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)' } }, '—')
                      ),
                      React.createElement('td', { style: { padding: '9px 10px' } },
                        row._hasSignal
                          ? React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 3 } },
                              React.createElement(ConfBar, { score: row.confidence_score || 0 }),
                              React.createElement('span', { style: { fontSize: 10, color: 'var(--text4)' } },
                                `${row.confidence_score || 0}%`)
                            )
                          : null
                      ),
                      React.createElement('td', { style: { padding: '9px 10px', fontSize: 12, fontFamily: 'Fira Code, monospace' } },
                        row.current_price ? fmt(row.current_price, 4) : '—'
                      ),
                      React.createElement('td', { style: { padding: '9px 10px' } },
                        React.createElement(SparkLine, { closes, width: 60, height: 22 })
                      )
                    );
                  })
                )
              )
            )
      ),

      /* Right 40% — detail panel */
      React.createElement('div', { style: { flex: '0 0 calc(40% - 14px)', display: 'flex', flexDirection: 'column', gap: 12 } },
        !sel
          ? React.createElement('div', { className: 'tv-card', style: { color: 'var(--text4)', fontSize: 13, padding: 32, textAlign: 'center' } },
              'Select a symbol to view details')
          : [
              /* Header */
              React.createElement('div', { key: 'hdr', className: 'tv-card', style: { padding: '12px 14px' } },
                React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 } },
                  React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
                    React.createElement('strong', { style: { fontSize: 15 } }, sel.symbol),
                    sel.status && React.createElement('span', {
                      style: {
                        fontSize: 11, padding: '2px 8px', borderRadius: 10,
                        background: `${(STATUS_CONFIG[sel.status] || STATUS_CONFIG.quiet).color}22`,
                        color: (STATUS_CONFIG[sel.status] || STATUS_CONFIG.quiet).color,
                      }
                    }, (STATUS_CONFIG[sel.status] || STATUS_CONFIG.quiet).label)
                  ),
                  wlSel && React.createElement('button', {
                    className: 'tv-btn',
                    style: { fontSize: 11, padding: '2px 8px', color: 'var(--fail)' },
                    onClick: () => removeSymbol(wlSel.id),
                  }, 'Remove')
                ),
                sel.signal_text && React.createElement('div', { style: { fontSize: 13, color: 'var(--text2)', lineHeight: 1.5 } }, sel.signal_text)
              ),

              /* HTF chart */
              sel.htf_timeframe && React.createElement('div', { key: 'htf', className: 'tv-card', style: { padding: 0, overflow: 'hidden' } },
                React.createElement('div', { style: { padding: '6px 12px', borderBottom: '1px solid var(--line)', fontSize: 11, color: 'var(--text4)' } },
                  `HTF · ${sel.htf_timeframe}`),
                React.createElement('iframe', {
                  key: `htf-${sel.symbol}`,
                  src: `https://s.tradingview.com/widgetembed/?symbol=BINANCE%3A${sel.symbol}&interval=${TV_INTERVAL[sel.htf_timeframe] || '240'}&theme=dark&style=1&hide_side_toolbar=1&allow_symbol_change=0`,
                  style: { width: '100%', height: 220, border: 'none', display: 'block' },
                  title: `${sel.symbol} HTF`,
                })
              ),

              /* LTF chart */
              sel.ltf_timeframe && React.createElement('div', { key: 'ltf', className: 'tv-card', style: { padding: 0, overflow: 'hidden' } },
                React.createElement('div', { style: { padding: '6px 12px', borderBottom: '1px solid var(--line)', fontSize: 11, color: 'var(--text4)' } },
                  `LTF · ${sel.ltf_timeframe}`),
                React.createElement('iframe', {
                  key: `ltf-${sel.symbol}`,
                  src: `https://s.tradingview.com/widgetembed/?symbol=BINANCE%3A${sel.symbol}&interval=${TV_INTERVAL[sel.ltf_timeframe] || '15'}&theme=dark&style=1&hide_side_toolbar=1&allow_symbol_change=0`,
                  style: { width: '100%', height: 200, border: 'none', display: 'block' },
                  title: `${sel.symbol} LTF`,
                })
              ),

              /* Market context */
              (sel.htf_label || sel.ltf_label) && React.createElement('div', { key: 'ctx', className: 'tv-card' },
                React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 } }, 'Market Context'),
                sel.htf_label && React.createElement('div', { style: { marginBottom: 6 } },
                  React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)', marginRight: 6 } }, `${sel.htf_timeframe || 'HTF'}:`),
                  React.createElement('span', { style: { fontSize: 13 } }, sel.htf_label)
                ),
                sel.ltf_label && React.createElement('div', null,
                  React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)', marginRight: 6 } }, `${sel.ltf_timeframe || 'LTF'}:`),
                  React.createElement('span', { style: { fontSize: 13 } }, sel.ltf_label)
                )
              ),

              /* Why flagged */
              sel.why_flagged && React.createElement('div', { key: 'why', className: 'tv-card' },
                React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 } }, 'Why Flagged'),
                React.createElement('div', { style: { fontSize: 13, color: 'var(--text2)', lineHeight: 1.6, whiteSpace: 'pre-wrap' } }, sel.why_flagged)
              ),

              /* Concepts triggered */
              sel.concepts_triggered && sel.concepts_triggered.length > 0 && React.createElement('div', { key: 'concepts', className: 'tv-card' },
                React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 } }, 'Concepts Triggered'),
                React.createElement('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap' } },
                  sel.concepts_triggered.map((c, i) =>
                    React.createElement('span', { key: i, className: 'tv-chip adapt' }, c)
                  )
                )
              ),

              /* Proposed plan */
              (sel.proposed_entry || sel.proposed_stop || sel.proposed_target) && React.createElement('div', { key: 'plan', className: 'tv-card' },
                React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 } }, 'Proposed Plan'),
                React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px', fontSize: 13 } },
                  [
                    { label: 'Entry',  val: sel.proposed_entry,  mono: true,  accent: false },
                    { label: 'Stop',   val: sel.proposed_stop,   mono: true,  accent: false },
                    { label: 'Target', val: sel.proposed_target, mono: true,  accent: false },
                    { label: 'R:R',    val: sel.rr_ratio,        mono: false, accent: true  },
                  ].map(({ label, val, mono, accent }) =>
                    React.createElement('div', { key: label },
                      React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', marginBottom: 2 } }, label),
                      React.createElement('div', {
                        style: {
                          fontFamily: mono ? 'Fira Code, monospace' : 'inherit',
                          color: accent ? 'var(--accent)' : 'var(--text)',
                        }
                      }, val != null ? (accent ? `${val}R` : fmt(val, 4)) : '—')
                    )
                  )
                )
              ),

              /* Notes */
              React.createElement('div', { key: 'notes', className: 'tv-card' },
                React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 } }, 'Notes'),
                React.createElement('textarea', {
                  className: 'tv-input',
                  placeholder: 'Personal notes…',
                  value: notes[sel.symbol] || '',
                  rows: 3,
                  style: { resize: 'vertical', width: '100%', boxSizing: 'border-box', fontFamily: 'inherit', fontSize: 13 },
                  onChange: e => setNotes(prev => ({ ...prev, [sel.symbol]: e.target.value })),
                  onBlur: e => saveNote(sel.symbol, e.target.value),
                })
              ),
            ]
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
      const r = await api('/api/trading/extract-concepts', { method: 'POST', body: '{}' });
      const skipped = r.docs_skipped ? ` (${r.docs_skipped} already done)` : '';
      setExtractMsg(`Extracted ${r.concepts_created} concepts from ${r.docs_processed} documents${skipped}.`);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setExtracting(false);
    }
  }

  const displayed = useTdMemo(() => concepts, [concepts]);

  if (loading) return React.createElement('div', { className: 'tv-label', style: { padding: 32 } }, 'Loading…');

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 16, padding: '16px 0' } },
    error && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13 } }, error),
    extractMsg && React.createElement('div', { style: { color: 'var(--ok)', fontSize: 13 } }, extractMsg),

    React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
      React.createElement('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap' } },
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
          }, `${cat.replace(/_/g, ' ')} (${count})`);
        })
      ),
      React.createElement('button', {
        className: extracting ? 'tv-btn' : 'tv-btn primary',
        disabled: extracting,
        onClick: extractConcepts,
        style: { whiteSpace: 'nowrap' },
      }, extracting ? 'Extracting…' : '⚡ Extract from Docs')
    ),

    concepts.length === 0
      ? React.createElement('div', { className: 'tv-card', style: { textAlign: 'center', color: 'var(--text4)', padding: 32 } },
          'No concepts yet. Upload strategy docs in Settings, then click Extract.')
      : React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
          displayed.map(c =>
            React.createElement('div', {
              key: c.id,
              className: 'tv-card',
              style: { cursor: 'pointer' },
              onClick: () => setExpanded(expanded === c.id ? null : c.id),
            },
              React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' } },
                React.createElement('div', null,
                  React.createElement('div', { style: { fontWeight: 600, fontSize: 14, marginBottom: 4 } }, c.title),
                  React.createElement('div', { style: { fontSize: 12, color: 'var(--text3)' } }, c.summary)
                ),
                React.createElement('div', { style: { display: 'flex', gap: 6, alignItems: 'center', flexShrink: 0, marginLeft: 12 } },
                  c.category && React.createElement('span', { className: 'tv-chip' }, c.category.replace(/_/g, ' ')),
                  React.createElement('span', { style: { color: 'var(--text4)', fontSize: 12 } }, expanded === c.id ? '▲' : '▼')
                )
              ),
              expanded === c.id && React.createElement('div', { style: { marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--line)' } },
                c.source_doc && React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', marginBottom: 6 } }, `Source: ${c.source_doc}`),
                c.tags && c.tags.length > 0 && React.createElement('div', { style: { display: 'flex', gap: 4, flexWrap: 'wrap' } },
                  c.tags.map((t, i) => React.createElement('span', { key: i, className: 'tv-chip' }, t))
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
      .catch(() => { setQuiz(null); setLoading(false); });
  }

  useTdE(() => { loadToday(); }, []);

  async function generateQuiz() {
    setGenerating(true);
    setError(null);
    try {
      await api('/api/trading/quiz/generate', { method: 'POST', body: '{}' });
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
        method: 'POST', body: JSON.stringify({ answers: payload }),
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

  if (loading) return React.createElement('div', { className: 'tv-label', style: { padding: 32 } }, 'Loading…');

  const questions = quiz?.questions || [];
  const streak = quiz?.streak || {};
  const allAnswered = questions.length > 0 && Object.keys(answers).length === questions.length;

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 16, padding: '16px 0' } },
    error && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13 } }, error),

    React.createElement('div', { className: 'tv-card', style: { display: 'flex', gap: 24, alignItems: 'center' } },
      React.createElement('div', null,
        React.createElement('div', { style: { color: 'var(--text4)', fontSize: 11, textTransform: 'uppercase', marginBottom: 2 } }, 'Streak'),
        React.createElement('div', { className: 'tv-num', style: { fontSize: 20 } }, `🔥 ${streak.current_streak || 0}`)
      ),
      React.createElement('div', null,
        React.createElement('div', { style: { color: 'var(--text4)', fontSize: 11, textTransform: 'uppercase', marginBottom: 2 } }, 'Best'),
        React.createElement('div', { className: 'tv-num' }, streak.longest_streak || 0)
      ),
      React.createElement('div', null,
        React.createElement('div', { style: { color: 'var(--text4)', fontSize: 11, textTransform: 'uppercase', marginBottom: 2 } }, 'All-time'),
        React.createElement('div', { className: 'tv-num' }, `${streak.total_correct || 0}/${streak.total_attempted || 0}`)
      ),
      React.createElement('div', { style: { marginLeft: 'auto' } },
        React.createElement('button', {
          className: generating ? 'tv-btn' : 'tv-btn primary',
          disabled: generating,
          onClick: generateQuiz,
        }, generating ? 'Generating…' : quiz ? '↺ New Quiz' : '⚡ Generate Quiz')
      )
    ),

    submitted && result && React.createElement('div', {
      className: 'tv-card',
      style: { background: result.score_pct >= 70 ? 'var(--ok-soft)' : 'var(--fail-soft)', textAlign: 'center' }
    },
      React.createElement('div', { style: { fontSize: 22, fontWeight: 700 } }, `${result.score_pct}%`),
      React.createElement('div', { style: { color: 'var(--text3)', fontSize: 13 } },
        `${result.correct} / ${result.submitted} correct`)
    ),

    !quiz && React.createElement('div', { className: 'tv-card', style: { textAlign: 'center', color: 'var(--text4)', padding: 32 } },
      'No quiz for today. Generate one to start.'),

    questions.map((q, idx) => {
      const opts = shuffles[q.id] || [q.answer_text, ...q.distractors];
      const selected = answers[q.id];
      const showResult = submitted;
      return React.createElement('div', { key: q.id, className: 'tv-card' },
        React.createElement('div', { style: { marginBottom: 8 } },
          React.createElement('div', { style: { color: 'var(--text4)', fontSize: 11, marginBottom: 4 } }, `Q${idx + 1} · ${q.concept_title || ''}`),
          React.createElement('div', { style: { fontWeight: 600, fontSize: 14 } }, q.question_text)
        ),
        React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
          opts.map((opt, i) => {
            const isSelected = selected === opt;
            const isCorrect = opt === q.answer_text;
            let bg = 'var(--panel2)';
            let border = '1px solid var(--line)';
            if (showResult && isSelected && isCorrect)  { bg = 'var(--ok-soft)';   border = '1px solid var(--ok)';   }
            else if (showResult && isSelected && !isCorrect) { bg = 'var(--fail-soft)'; border = '1px solid var(--fail)'; }
            else if (showResult && !isSelected && isCorrect) { bg = 'var(--ok-soft)';   border = '1px solid var(--ok)';   }
            else if (!showResult && isSelected) { border = '1px solid var(--accent)'; bg = 'var(--panel3)'; }
            return React.createElement('div', {
              key: i,
              onClick: () => !submitted && setAnswers(prev => ({ ...prev, [q.id]: opt })),
              style: {
                background: bg, border, borderRadius: 4, padding: '8px 12px',
                fontSize: 13, cursor: submitted ? 'default' : 'pointer', lineHeight: 1.4,
              }
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
        style: { alignSelf: 'flex-start' },
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
  const [form, setForm] = useTdS({ title: '', body: '', mood: 3, market_regime: '', entry_date: '', tags: '' });
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
    setForm({ title: '', body: '', mood: 3, market_regime: '', entry_date: today, tags: '' });
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
        await api(`/api/trading/journal/${editId}`, { method: 'PUT', body: JSON.stringify(payload) });
      } else {
        await api('/api/trading/journal', { method: 'POST', body: JSON.stringify(payload) });
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
      await api(`/api/trading/journal/${id}`, { method: 'DELETE' });
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  if (loading) return React.createElement('div', { className: 'tv-label', style: { padding: 32 } }, 'Loading…');

  const REGIMES = ['', 'bull', 'bear', 'sideways', 'unknown'];

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 16, padding: '16px 0' } },
    error && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13 } }, error),

    React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
      React.createElement('div', { className: 'tv-label' }, `Journal (${total} entries)`),
      React.createElement('button', { className: 'tv-btn primary', onClick: openNewForm }, '+ New Entry')
    ),

    showForm && React.createElement('div', { className: 'tv-card', style: { display: 'flex', flexDirection: 'column', gap: 10 } },
      React.createElement('div', { className: 'tv-label', style: { marginBottom: 4 } }, editId ? 'Edit Entry' : 'New Entry'),
      React.createElement('div', { style: { display: 'flex', gap: 8 } },
        React.createElement('input', {
          className: 'tv-input', placeholder: 'Date', type: 'date',
          value: form.entry_date, style: { width: 140 },
          onChange: e => setForm(p => ({ ...p, entry_date: e.target.value })),
        }),
        React.createElement('select', {
          className: 'tv-input', value: form.market_regime, style: { width: 120 },
          onChange: e => setForm(p => ({ ...p, market_regime: e.target.value })),
        }, REGIMES.map(r => React.createElement('option', { key: r, value: r }, r || 'Regime…'))),
        React.createElement('select', {
          className: 'tv-input', value: form.mood, style: { width: 80 },
          onChange: e => setForm(p => ({ ...p, mood: e.target.value })),
        }, [1, 2, 3, 4, 5].map(m => React.createElement('option', { key: m, value: m }, `${MOOD_LABELS[m]} ${m}`)))
      ),
      React.createElement('input', {
        className: 'tv-input', placeholder: 'Title',
        value: form.title,
        onChange: e => setForm(p => ({ ...p, title: e.target.value })),
      }),
      React.createElement('textarea', {
        className: 'tv-input', placeholder: 'Notes, observations, lessons…',
        value: form.body, rows: 5,
        style: { resize: 'vertical', fontFamily: 'inherit' },
        onChange: e => setForm(p => ({ ...p, body: e.target.value })),
      }),
      React.createElement('input', {
        className: 'tv-input', placeholder: 'Tags (comma-separated)',
        value: form.tags,
        onChange: e => setForm(p => ({ ...p, tags: e.target.value })),
      }),
      React.createElement('div', { style: { display: 'flex', gap: 8 } },
        React.createElement('button', {
          className: 'tv-btn primary', disabled: saving, onClick: saveEntry,
        }, saving ? 'Saving…' : editId ? 'Update' : 'Save'),
        React.createElement('button', { className: 'tv-btn', onClick: () => setShowForm(false) }, 'Cancel')
      )
    ),

    entries.length === 0 && !showForm
      ? React.createElement('div', { className: 'tv-card', style: { textAlign: 'center', color: 'var(--text4)', padding: 32 } },
          'No journal entries yet.')
      : entries.map(e =>
          React.createElement('div', { key: e.id, className: 'tv-card' },
            React.createElement('div', {
              style: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', cursor: 'pointer' },
              onClick: () => setExpanded(expanded === e.id ? null : e.id),
            },
              React.createElement('div', null,
                React.createElement('div', { style: { fontWeight: 600, fontSize: 14 } }, e.title),
                React.createElement('div', { style: { display: 'flex', gap: 8, marginTop: 4, fontSize: 12, color: 'var(--text4)' } },
                  React.createElement('span', null, e.entry_date),
                  e.market_regime && React.createElement('span', { className: 'tv-chip' }, e.market_regime),
                  e.mood && React.createElement('span', null, MOOD_LABELS[e.mood])
                )
              ),
              React.createElement('span', { style: { color: 'var(--text4)', fontSize: 12 } }, expanded === e.id ? '▲' : '▼')
            ),
            expanded === e.id && React.createElement('div', { style: { marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--line)' } },
              e.body && React.createElement('div', { style: { fontSize: 13, color: 'var(--text2)', whiteSpace: 'pre-wrap', marginBottom: 8 } }, e.body),
              e.tags && e.tags.length > 0 && React.createElement('div', { style: { display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 } },
                e.tags.map((t, i) => React.createElement('span', { key: i, className: 'tv-chip' }, t))
              ),
              React.createElement('div', { style: { display: 'flex', gap: 8 } },
                React.createElement('button', { className: 'tv-btn', onClick: () => openEditForm(e) }, 'Edit'),
                React.createElement('button', { className: 'tv-btn', style: { color: 'var(--fail)' }, onClick: () => deleteEntry(e.id) }, 'Delete')
              )
            )
          )
        )
  );
}

/* ===== PLACEHOLDER SCREENS ===== */
function ValidatorScreen() { return React.createElement('div', { className: 'tv-label', style: { padding: 32, color: 'var(--text4)' } }, 'Validator — coming soon'); }
function ReportsScreen()   { return React.createElement('div', { className: 'tv-label', style: { padding: 32, color: 'var(--text4)' } }, 'Reports — coming soon');   }

/* ===== EXPORTS ===== */
window.ScannerScreen  = ScannerScreen;
window.ConceptsScreen = ConceptsScreen;
window.QuizScreen     = QuizScreen;
window.JournalScreen  = JournalScreen;
window.ValidatorScreen = ValidatorScreen;
window.ReportsScreen   = ReportsScreen;
