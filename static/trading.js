/* ===== TRADING TOOLS ===== */

const { useState: useTdS, useEffect: useTdE, useCallback: useTdCb, useMemo: useTdMemo, useRef: useTdRef } = React;

const STATUS_CONFIG = {
  active:   { color: '#f0a500', label: 'Active'   },
  forming:  { color: '#f0e000', label: 'Forming'  },
  watching: { color: '#f0c040', label: 'Watching', chipBg: 'rgba(240,192,64,0.12)', chipBorder: '1px solid rgba(240,192,64,0.35)' },
  quiet:    { color: 'var(--text4)', label: 'Quiet' },
};

const TV_INTERVAL = { '1w': 'W', '1d': 'D', '12h': '720', '4h': '240', '1h': '60', '30m': '30', '15m': '15', '5m': '5' };

const INTERVAL_COLORS = {
  '1w': '#4A148C', '1d': '#7B2FBE', '12h': '#01579B', '4h': '#1565C0',
  '1h': '#00695C', '30m': '#E65100', '15m': '#2E7D32', '5m': '#F57F17',
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

function CandleChart({ symbol, interval, height, indicatorsJson, contractAddress }) {
  const containerRef = useTdRef(null);
  const [showFallback, setShowFallback] = useTdS(false);

  // Reset fallback when key identity props change
  useTdE(() => { setShowFallback(false); }, [symbol, interval, contractAddress]);

  useTdE(() => {
    if (showFallback) return;
    const el = containerRef.current;
    if (!el || !window.LightweightCharts) return;

    const chart = window.LightweightCharts.createChart(el, {
      width: el.clientWidth,
      height: height || 260,
      layout: {
        background: { color: 'transparent' },
        textColor: 'rgba(255,255,255,0.5)',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.05)' },
        horzLines: { color: 'rgba(255,255,255,0.05)' },
      },
      crosshair: { mode: window.LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: 'rgba(255,255,255,0.1)',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: 'rgba(255,255,255,0.1)',
        timeVisible: true,
        secondsVisible: false,
      },
      watermark: { visible: false },
    });

    const series = chart.addCandlestickSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderVisible: false,
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
      lastValueVisible: false,
      priceLineVisible: false,
    });

    const emaLine = chart.addLineSeries({
      color: '#f0a500',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });


    fetch(`/api/trading/scanner/ohlcv?symbol=${symbol}&interval=${interval}&limit=100`)
      .then(r => r.json())
      .then(data => {
        if (!data.candles || !data.candles.length) {
          if (contractAddress) setShowFallback(true);
          return;
        }
        const candles = data.candles;
        series.setData(candles);

        if (candles.length >= 20) {
          const closes = candles.map(c => c.close);
          const mult = 2 / 21;
          let ema = closes.slice(0, 20).reduce((a, b) => a + b, 0) / 20;
          const emaData = [];
          candles.forEach((c, i) => {
            if (i < 19) return;
            if (i > 19) ema = c.close * mult + ema * (1 - mult);
            emaData.push({ time: c.time, value: ema });
          });
          emaLine.setData(emaData);
        }

        if (indicatorsJson) {
          try {
            const ind = typeof indicatorsJson === 'string' ? JSON.parse(indicatorsJson) : indicatorsJson;

            if (ind.dr && ind.dr.high != null && ind.dr.low != null) {
              const _drLineOpts = { lineWidth: 2, lineStyle: 0, axisLabelVisible: false, lastValueVisible: false, title: '' };
              series.createPriceLine({ price: ind.dr.high, color: 'rgba(180,180,180,0.6)', ..._drLineOpts });
              series.createPriceLine({ price: ind.dr.low,  color: 'rgba(180,180,180,0.6)', ..._drLineOpts });
              if (ind.dr.eq != null) {
                series.createPriceLine({ price: ind.dr.eq, color: 'rgba(180,180,180,0.35)', lineWidth: 1, lineStyle: 2, axisLabelVisible: false, lastValueVisible: false, title: '' });
              }
            }

            if (ind.fvg && ind.fvg.top != null && ind.fvg.bottom != null) {
              series.createPriceLine({ price: ind.fvg.top, color: 'rgba(255,230,100,0.7)', lineWidth: 1, lineStyle: 1, axisLabelVisible: false, lastValueVisible: false, title: 'FVG T' });
              series.createPriceLine({ price: ind.fvg.bottom, color: 'rgba(255,230,100,0.7)', lineWidth: 1, lineStyle: 1, axisLabelVisible: false, lastValueVisible: false, title: 'FVG B' });
            }

            (ind.swing_highs || []).forEach(sh => {
              const price = typeof sh === 'object' ? sh.price : sh;
              if (price && price > 0) series.createPriceLine({
                price, color: 'rgba(240,165,0,0.5)', lineWidth: 1, lineStyle: 3,
                axisLabelVisible: false, title: '',
              });
            });
            (ind.swing_lows || []).forEach(sl => {
              const price = typeof sl === 'object' ? sl.price : sl;
              if (price && price > 0) series.createPriceLine({
                price, color: 'rgba(78,158,255,0.5)', lineWidth: 1, lineStyle: 3,
                axisLabelVisible: false, title: '',
              });
            });
          } catch (err) {
            console.error('Indicator overlay error:', err);
          }
        }

        chart.timeScale().fitContent();
      })
      .catch(err => {
        if (contractAddress) setShowFallback(true);
        else console.error('OHLCV fetch error:', err);
      });

    const ro = new ResizeObserver(() => {
      if (el) chart.applyOptions({ width: el.clientWidth });
    });
    ro.observe(el);

    return () => { ro.disconnect(); chart.remove(); };
  }, [symbol, interval, height, indicatorsJson, contractAddress, showFallback]);

  if (showFallback && contractAddress) {
    return React.createElement('iframe', {
      src: `https://dexscreener.com/ethereum/${contractAddress}?embed=1&theme=dark&trades=0&info=0`,
      style: { display: 'block', border: 'none', borderRadius: 8, width: '100%', height: `${height || 260}px` },
      frameBorder: '0',
    });
  }

  return React.createElement('div', {
    ref: containerRef,
    style: { width: '100%', height: `${height || 260}px`, overflow: 'hidden' },
  });
}

function normalizeSymbol(raw) {
  const s = raw.trim().toUpperCase();
  const QUOTES = ['USDT', 'USDC', 'BTC', 'ETH', 'BNB', 'BUSD'];
  const hasQuote = QUOTES.some(q => s.endsWith(q) && s.length > q.length);
  return hasQuote ? s : s + 'USDT';
}

/* ===== SCANNER ===== */
function ScannerScreen() {
  const [watchlist, setWatchlist] = React.useState([]);
  const [signals, setSignals] = useTdS([]);
  const [selectedKey, setSelectedKey] = useTdS(null);
  const [checkedKeys, setCheckedKeys] = useTdS(new Set());
  const [running, setRunning] = useTdS(false);
  const [loading, setLoading] = useTdS(true);
  const [showAdd, setShowAdd] = useTdS(false);
  const [newSymbol, setNewSymbol] = useTdS('');
  const [newHtf, setNewHtf] = useTdS('4h');
  const [newLtf, setNewLtf] = useTdS('15m');
  const [newContractAddress, setNewContractAddress] = useTdS('');
  const [notes, setNotes] = useTdS({});
  const [error, setError] = useTdS(null);
  const [lastScanAt, setLastScanAt] = useTdS(null);

  function rowKey(r) {
    const sym = r.symbol ? r.symbol.toUpperCase().trim() : '';
    const normalized = ['USDT','USDC','BTC','ETH','BNB'].some(q => sym.endsWith(q) && sym.length > q.length) ? sym : sym + 'USDT';
    return `${normalized}|${r.htf_timeframe || r.interval || '4h'}|${r.ltf_timeframe || '15m'}`;
  }

  async function load() {
    try {
      const [wlData, sigData] = await Promise.all([
        api('/api/trading/scanner/watchlist'),
        api('/api/trading/scanner/signals?limit=50'),
      ]);
      const wl = wlData.watchlist || [];
      const wlSymbols = new Set(wl.map(w => w.symbol.toUpperCase().trim()));
      const sigs = (sigData.signals || []).filter(s => wlSymbols.has(s.symbol.toUpperCase().trim()));
      sigs.forEach(s => {
        try { s._indicators = JSON.parse(s.raw_indicators_json); } catch (e) {}
      });
      setWatchlist(wl);
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
    } catch (e) { setError(e.message); setLoading(false); }
  }

  useTdE(() => { load(); }, []);

  const sortedSignals = useTdMemo(() => {
    const ORDER = { active: 0, forming: 1, watching: 2, quiet: 3 };
    return [...signals].sort((a, b) => {
      const os = (ORDER[a.status] ?? 3) - (ORDER[b.status] ?? 3);
      if (os !== 0) return os;
      return (b.confidence_score || 0) - (a.confidence_score || 0);
    });
  }, [signals]);

  const allRows = useTdMemo(() => {
    const norm = s => s.toUpperCase().trim();
    const withQuote = s => {
      const n = norm(s);
      return ['USDT', 'USDC', 'BTC', 'ETH', 'BNB'].some(q => n.endsWith(q)) ? n : n + 'USDT';
    };
    const rk = (sym, h, l) => `${norm(sym)}|${h || '4h'}|${l || '15m'}`;
    const rows = sortedSignals.map(s => ({ ...s, _hasSignal: true }));
    const sigKeys = new Set(rows.map(r => rk(r.symbol, r.htf_timeframe, r.ltf_timeframe)));
    watchlist.forEach(w => {
      const displaySym = withQuote(w.symbol);
      const htf = w.htf_timeframe || w.interval || '4h';
      const ltf = w.ltf_timeframe || '15m';
      if (!sigKeys.has(rk(displaySym, htf, ltf))) {
        rows.push({ ...w, symbol: displaySym, _hasSignal: false, status: 'quiet' });
      }
    });
    return rows;
  }, [sortedSignals, signals, watchlist]);

  useTdE(() => {
    if (allRows.length === 0) return;
    setCheckedKeys(prev => {
      const next = new Set(prev);
      allRows.forEach(r => { next.add(rowKey(r)); });
      return next;
    });
  }, [allRows]);

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

  function saveNote(symbol, value) {
    const item = watchlist.find(w => w.symbol === symbol);
    if (!item) return;
    api(`/api/trading/scanner/watchlist/${item.id}`, {
      method: 'PUT', body: JSON.stringify({ notes: value }),
    }).catch(() => {});
  }

  function addSymbol() {
    if (!newSymbol.trim()) return;
    const sym = normalizeSymbol(newSymbol);
    setNewSymbol(sym);
    api('/api/trading/scanner/watchlist', {
      method: 'POST',
      body: JSON.stringify({
        symbol: sym,
        htf_timeframe: newHtf,
        ltf_timeframe: newLtf,
        contract_address: newContractAddress.trim(),
      }),
    }).then(() => { setNewSymbol(''); setNewContractAddress(''); setShowAdd(false); load(); })
      .catch(e => setError(e.message));
  }

  const handleRemove = async (watchlistId) => {
    try {
      const resp = await fetch(`/api/trading/scanner/watchlist/${watchlistId}`, { method: 'DELETE' });
      const data = await resp.json();
      if (data.success) {
        const removed = watchlist.find(w => w.id === watchlistId);
        setWatchlist(prev => prev.filter(w => w.id !== watchlistId));
        setSignals(prev => prev.filter(s => !removed || s.symbol !== removed.symbol));
        if (removed) {
          const k = rowKey(removed);
          setCheckedKeys(prev => { const next = new Set(prev); next.delete(k); return next; });
          if (selectedKey === k) setSelectedKey(null);
        }
      }
    } catch (e) {
      console.error('Delete failed:', e);
    }
  };

  async function runScanSelected() {
    const symList = [...new Set([...checkedKeys].map(k => k.split('|')[0]))];
    if (!symList.length) return;
    setRunning(true); setError(null);
    try {
      await api('/api/trading/scanner/run', { method: 'POST', body: JSON.stringify({ symbols: symList }) });
      await load();
    } catch (e) { setError(e.message); }
    finally { setRunning(false); }
  }

  async function runScanAll() {
    setRunning(true); setError(null);
    try {
      await api('/api/trading/scanner/run', { method: 'POST', body: '{}' });
      await load();
    } catch (e) { setError(e.message); }
    finally { setRunning(false); }
  }

  function toggleChecked(k) {
    setCheckedKeys(prev => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k); else next.add(k);
      return next;
    });
  }

  if (loading) return React.createElement('div', { className: 'tv-label', style: { padding: 32 } }, 'Loading…');

  const allKeys = allRows.map(r => rowKey(r));
  const allChecked = allKeys.length > 0 && allKeys.every(k => checkedKeys.has(k));
  const someChecked = !allChecked && allKeys.some(k => checkedKeys.has(k));
  const statusCounts = {};
  signals.forEach(s => { statusCounts[s.status] = (statusCounts[s.status] || 0) + 1; });
  const sel = selectedKey ? allRows.find(r => rowKey(r) === selectedKey) : null;
  const wlSel = sel ? watchlist.find(w => rowKey(w) === selectedKey) : null;
  const selectedSignal = sel ? signals.find(s => s.symbol === sel.symbol) : null;
  let selIndicators = null;
  if (selectedSignal && selectedSignal.raw_indicators_json) {
    try {
      selIndicators = typeof selectedSignal.raw_indicators_json === 'string'
        ? JSON.parse(selectedSignal.raw_indicators_json)
        : selectedSignal.raw_indicators_json;
    } catch (e) {}
  }

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 12, padding: '16px 0' } },
    error && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13, padding: '0 4px' } }, error),

    /* TOP — full-width table card */
    React.createElement('div', { className: 'tv-card', style: { padding: 0, overflow: 'hidden' } },

      /* Header bar */
      React.createElement('div', {
        style: { display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderBottom: '1px solid var(--line)', flexWrap: 'wrap' }
      },
        ['active', 'forming', 'watching'].map(st => {
          const cnt = statusCounts[st] || 0;
          if (!cnt) return null;
          const cfg = STATUS_CONFIG[st];
          return React.createElement('span', {
            key: st,
            style: { fontSize: 11, padding: '2px 8px', borderRadius: 10, background: `${cfg.color}22`, color: cfg.color, border: `1px solid ${cfg.color}44` }
          }, `${cnt} ${cfg.label}`);
        }),
        React.createElement('div', { style: { flex: 1, textAlign: 'center' } },
          lastScanAt && React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)' } }, `Last scan ${timeAgo(lastScanAt)}`)
        ),
        React.createElement('button', {
          className: 'tv-btn primary',
          disabled: running || checkedKeys.size === 0,
          onClick: runScanSelected,
          style: { fontSize: 12, padding: '4px 12px' },
        }, running ? 'Scanning…' : '▶ Scan Selected'),
        React.createElement('button', {
          className: 'tv-btn',
          disabled: running || watchlist.length === 0,
          onClick: runScanAll,
          style: { fontSize: 12, padding: '4px 12px' },
        }, 'Scan All'),
        React.createElement('button', {
          className: 'tv-btn',
          onClick: () => setShowAdd(v => !v),
          style: { fontSize: 12, padding: '4px 12px' },
        }, showAdd ? '✕ Cancel' : '+ Add')
      ),

      /* Inline add form */
      showAdd && React.createElement('div', {
        style: { display: 'flex', flexDirection: 'column', gap: 10, padding: '12px 14px', borderBottom: '1px solid var(--line)' }
      },
        /* Row 1 — symbol + HTF + LTF */
        React.createElement('div', { style: { display: 'flex', gap: 12, alignItems: 'center' } },
          React.createElement('input', {
            className: 'tv-input',
            placeholder: 'e.g. BTC or ETHUSDT',
            value: newSymbol,
            style: { width: 200, flexShrink: 0 },
            onChange: e => setNewSymbol(e.target.value),
            onKeyDown: e => e.key === 'Enter' && addSymbol(),
            autoFocus: true,
          }),
          React.createElement('div', { style: { display: 'flex', alignItems: 'center' } },
            React.createElement('span', { style: { fontSize: 13, color: 'var(--text4)', marginRight: 6, whiteSpace: 'nowrap' } }, 'HTF'),
            React.createElement('select', {
              className: 'tv-input', value: newHtf, style: { minWidth: 90 },
              onChange: e => setNewHtf(e.target.value),
            }, ['1w', '1d', '12h', '4h', '1h'].map(v => React.createElement('option', { key: v, value: v }, v)))
          ),
          React.createElement('div', { style: { display: 'flex', alignItems: 'center' } },
            React.createElement('span', { style: { fontSize: 13, color: 'var(--text4)', marginRight: 6, whiteSpace: 'nowrap' } }, 'LTF'),
            React.createElement('select', {
              className: 'tv-input', value: newLtf, style: { minWidth: 90 },
              onChange: e => setNewLtf(e.target.value),
            }, ['1d', '12h', '4h', '1h', '30m', '15m', '5m'].map(v => React.createElement('option', { key: v, value: v }, v)))
          )
        ),
        /* Row 2 — contract address */
        React.createElement('div', null,
          React.createElement('label', { style: { display: 'block', fontSize: 12, color: 'var(--text4)', marginBottom: 4 } }, 'Contract Address (optional)'),
          React.createElement('input', {
            className: 'tv-input',
            placeholder: '0x... (for tokens not on Hyperliquid perps)',
            value: newContractAddress,
            style: { width: '100%', boxSizing: 'border-box', fontFamily: 'Fira Code, monospace', fontSize: 12 },
            onChange: e => setNewContractAddress(e.target.value),
          })
        ),
        /* Row 3 — submit */
        React.createElement('div', null,
          React.createElement('button', { className: 'tv-btn primary', onClick: addSymbol }, '+ Add')
        )
      ),

      /* Scrollable table */
      React.createElement('div', { style: { maxHeight: 420, overflowY: 'auto' } },
        allRows.length === 0
          ? React.createElement('div', { style: { color: 'var(--text4)', fontSize: 13, padding: 32, textAlign: 'center' } },
              'No symbols in watchlist. Add some and run a scan.')
          : React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse' } },
              React.createElement('thead', { style: { position: 'sticky', top: 0, background: 'var(--panel)', zIndex: 1 } },
                React.createElement('tr', { style: { borderBottom: '1px solid var(--line)' } },
                  React.createElement('th', { style: { padding: '8px 10px', width: 32 } },
                    React.createElement('input', {
                      type: 'checkbox',
                      checked: allChecked,
                      ref: el => { if (el) el.indeterminate = someChecked; },
                      onChange: () => setCheckedKeys(allChecked ? new Set() : new Set(allKeys)),
                    })
                  ),
                  ['Ticker', '', 'Status', 'Signal', 'HTF → LTF', 'Confidence', 'Price', 'Remove'].map(h =>
                    React.createElement('th', {
                      key: h,
                      style: {
                        padding: '8px 10px', fontSize: 12, color: 'var(--text4)', fontWeight: 500,
                        letterSpacing: '0.08em', textTransform: 'uppercase', textAlign: h === 'Remove' ? 'center' : 'left',
                      }
                    }, h)
                  )
                )
              ),
              React.createElement('tbody', null,
                allRows.map(row => {
                  const k = rowKey(row);
                  const isSel = selectedKey === k;
                  const cfg = STATUS_CONFIG[row.status] || STATUS_CONFIG.quiet;
                  const htf = row.htf_timeframe || row.interval || '4h';
                  const ltf = row.ltf_timeframe || '15m';
                  const htfCloses = (row.recent_closes_htf || []).slice(-5);
                  const ltfCloses = (row.recent_closes_ltf || []).slice(-5);
                  const STATUS_COLORS = { active: 'var(--accent)', forming: '#f0c040', watching: '#f0c040', quiet: 'var(--text4)' };
                  const wlItem = watchlist.find(w => rowKey(w) === k);
                  return React.createElement('tr', {
                    key: k,
                    onClick: () => setSelectedKey(isSel ? null : k),
                    style: { cursor: 'pointer', borderBottom: '1px solid var(--line)', background: isSel ? 'var(--panel3)' : 'transparent' }
                  },
                    React.createElement('td', { style: { padding: '9px 10px', width: 32 } },
                      React.createElement('input', {
                        type: 'checkbox',
                        checked: checkedKeys.has(k),
                        onClick: e => e.stopPropagation(),
                        onChange: () => toggleChecked(k),
                      })
                    ),
                    React.createElement('td', { style: { padding: '9px 10px' } },
                      React.createElement('strong', { style: { fontSize: 14, fontWeight: 600 } }, row.symbol)
                    ),
                    React.createElement('td', { style: { padding: '9px 6px', width: 14 } },
                      React.createElement('span', {
                        title: cfg.label,
                        style: { display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: cfg.color }
                      })
                    ),
                    React.createElement('td', { style: { padding: '9px 10px', minWidth: 80 } },
                      React.createElement('span', {
                        style: { fontSize: 13, color: row._hasSignal ? (STATUS_COLORS[row.status] || 'var(--text4)') : 'var(--text4)' }
                      }, row._hasSignal ? (row.status || '—') : '—')
                    ),
                    React.createElement('td', {
                      style: { padding: '9px 10px', minWidth: 120, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }
                    },
                      React.createElement('span', {
                        style: { fontSize: 13, color: row._hasSignal && row.status !== 'quiet' ? 'var(--text2)' : 'var(--text4)' }
                      }, !row._hasSignal ? '—' : row.status === 'quiet' ? 'No setup' : (() => { const t = row.signal_text || cfg.label; const p = t.split('·')[0].trim(); return p.length > 45 ? p.slice(0, 45) + '…' : p; })())
                    ),
                    React.createElement('td', { style: { padding: '9px 10px', whiteSpace: 'nowrap' } },
                      React.createElement('span', {
                        style: { fontSize: 12, padding: '2px 6px', borderRadius: 3, marginRight: 3, background: INTERVAL_COLORS[htf] || '#555', color: '#fff', fontWeight: 600 }
                      }, htf),
                      React.createElement('span', {
                        style: { fontSize: 12, padding: '2px 6px', borderRadius: 3, background: INTERVAL_COLORS[ltf] || '#555', color: '#fff', fontWeight: 600 }
                      }, ltf)
                    ),
                    React.createElement('td', { style: { padding: '9px 10px' } },
                      row._hasSignal
                        ? React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 3 } },
                            React.createElement(ConfBar, { score: row.confidence_score || 0 }),
                            React.createElement('span', { style: { fontSize: 10, color: 'var(--text4)' } }, `${row.confidence_score || 0}%`)
                          )
                        : null
                    ),
                    React.createElement('td', { style: { padding: '9px 10px', fontSize: 13, fontFamily: 'Fira Code, monospace' } },
                      row.current_price ? fmt(row.current_price, 4) : '—'
                    ),
                    React.createElement('td', { style: { padding: '9px 4px', textAlign: 'center' } },
                      wlItem && React.createElement('button', {
                        style: { color: 'var(--fail)', fontSize: 12, cursor: 'pointer', background: 'none', border: 'none', padding: '4px 8px' },
                        onClick: e => { e.stopPropagation(); handleRemove(wlItem.id); },
                      }, '✕')
                    )
                  );
                })
              )
            )
      )
    ),

    /* BOTTOM — detail section when a row is selected */
    sel && React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 12 } },

      /* WHY FLAGGED */
      React.createElement('div', { className: 'tv-card', style: { padding: '12px 14px', background: 'var(--panel2)' } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 } },
          React.createElement('strong', { style: { fontSize: 13 } }, sel.symbol),
          sel.status && React.createElement('span', {
            style: {
              fontSize: 11, padding: '2px 8px', borderRadius: 10,
              background: (STATUS_CONFIG[sel.status] || STATUS_CONFIG.quiet).chipBg || `${(STATUS_CONFIG[sel.status] || STATUS_CONFIG.quiet).color}22`,
              color: (STATUS_CONFIG[sel.status] || STATUS_CONFIG.quiet).color,
              border: (STATUS_CONFIG[sel.status] || STATUS_CONFIG.quiet).chipBorder,
            }
          }, (STATUS_CONFIG[sel.status] || STATUS_CONFIG.quiet).label),
          sel.htf_label && React.createElement('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 4 } },
            React.createElement('span', { style: { color: 'var(--accent)', fontWeight: 700, fontSize: 11 } }, 'HTF'),
            React.createElement('span', { style: { fontSize: 13, color: 'var(--text3)' } }, sel.htf_label)
          ),
          (sel.htf_label && sel.ltf_label) && React.createElement('span', { style: { color: 'var(--text4)' } }, '·'),
          sel.ltf_label && React.createElement('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 4 } },
            React.createElement('span', { style: { color: '#26a69a', fontWeight: 700, fontSize: 11 } }, 'LTF'),
            React.createElement('span', { style: { fontSize: 13, color: 'var(--text3)' } }, sel.ltf_label)
          )
        ),
        React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)', lineHeight: 1.6, whiteSpace: 'pre-wrap' } },
          sel.why_flagged || React.createElement('span', { style: { color: 'var(--text4)' } }, 'No active setup detected.')
        )
      ),

      /* Two charts side by side */
      React.createElement('div', { style: { display: 'flex', gap: 12 } },
        React.createElement('div', { style: { flex: 1, minWidth: 0 }, className: 'tv-card' },
          React.createElement('div', {
            style: { padding: '6px 12px', borderBottom: '1px solid var(--line)', fontSize: 11, color: 'var(--text4)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }
          },
            React.createElement('span', null, `HTF · ${sel.htf_timeframe || '4h'}`),
            React.createElement('a', {
              href: `https://www.tradingview.com/chart/?symbol=BINANCE:${sel.symbol}&interval=${TV_INTERVAL[sel.htf_timeframe] || '240'}`,
              target: '_blank', rel: 'noopener noreferrer',
              style: { fontSize: 10, color: 'var(--accent)', textDecoration: 'none' },
            }, 'Open in TradingView ↗')
          ),
          React.createElement(CandleChart, {
            symbol: sel.symbol,
            interval: sel.htf_timeframe || '4h',
            height: 240,
            indicatorsJson: selIndicators ? selIndicators.htf || null : null,
            contractAddress: wlSel ? (wlSel.contract_address || '') : '',
          })
        ),
        React.createElement('div', { style: { flex: 1, minWidth: 0 }, className: 'tv-card' },
          React.createElement('div', {
            style: { padding: '6px 12px', borderBottom: '1px solid var(--line)', fontSize: 11, color: 'var(--text4)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }
          },
            React.createElement('span', null, `LTF · ${sel.ltf_timeframe || '15m'}`),
            React.createElement('a', {
              href: `https://www.tradingview.com/chart/?symbol=BINANCE:${sel.symbol}&interval=${TV_INTERVAL[sel.ltf_timeframe] || '15'}`,
              target: '_blank', rel: 'noopener noreferrer',
              style: { fontSize: 10, color: 'var(--accent)', textDecoration: 'none' },
            }, 'Open in TradingView ↗')
          ),
          React.createElement(CandleChart, {
            symbol: sel.symbol,
            interval: sel.ltf_timeframe || '15m',
            height: 240,
            indicatorsJson: selIndicators ? selIndicators.ltf || null : null,
            contractAddress: wlSel ? (wlSel.contract_address || '') : '',
          })
        )
      ),

      /* 3-column detail grid */
      React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 } },

        /* CONCEPTS */
        React.createElement('div', { className: 'tv-card' },
          React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 } }, 'Concepts'),
          sel.concepts_triggered && sel.concepts_triggered.length > 0
            ? React.createElement('div', { style: { display: 'flex', gap: 5, flexWrap: 'wrap' } },
                sel.concepts_triggered.map((c, i) =>
                  React.createElement('span', { key: i, className: 'tv-chip adapt' }, c)
                )
              )
            : React.createElement('span', { style: { fontSize: 12, color: 'var(--text4)' } }, '—')
        ),

        /* PROPOSED PLAN */
        React.createElement('div', { className: 'tv-card' },
          React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 } }, 'Proposed Plan'),
          (sel.proposed_entry != null || sel.proposed_stop != null || sel.proposed_target != null || sel.rr_ratio != null)
            ? React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 } },
                [
                  { label: 'Entry', val: sel.proposed_entry, mono: true },
                  { label: 'Stop', val: sel.proposed_stop, mono: true },
                  { label: 'Target', val: sel.proposed_target, mono: true },
                  { label: 'R:R', val: sel.rr_ratio, mono: false, accent: true },
                ].map(({ label, val, mono, accent }) =>
                  React.createElement('div', { key: label, style: { display: 'flex', justifyContent: 'space-between' } },
                    React.createElement('span', { style: { color: 'var(--text4)' } }, label),
                    React.createElement('span', {
                      style: { fontFamily: mono ? 'Fira Code, monospace' : 'inherit', color: accent ? 'var(--accent)' : 'var(--text)' }
                    }, val != null ? (accent ? `${val}R` : fmt(val, 4)) : '—')
                  )
                )
              )
            : React.createElement('span', { style: { fontSize: 12, color: 'var(--text4)' } }, '—')
        ),

        /* NOTES */
        React.createElement('div', { className: 'tv-card' },
          React.createElement('div', { style: { fontSize: 10, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 } }, 'Notes'),
          React.createElement('textarea', {
            className: 'tv-input',
            placeholder: 'Personal notes…',
            value: notes[sel.symbol] || '',
            style: { resize: 'vertical', width: '100%', boxSizing: 'border-box', fontFamily: 'inherit', fontSize: 12, minHeight: 80 },
            onChange: e => setNotes(prev => ({ ...prev, [sel.symbol]: e.target.value })),
            onBlur: e => saveNote(sel.symbol, e.target.value),
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
