/* ===== TRADING TOOLS v2 ===== */

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
    let destroyed = false;

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


    fetch(`/api/trading/scanner/ohlcv?symbol=${symbol}&interval=${interval}&limit=500`)
      .then(r => r.json())
      .then(data => {
        if (destroyed) return;
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
              const drHigh = ind.dr.high;
              const drLow  = ind.dr.low;
              const eq     = ind.dr.eq != null ? ind.dr.eq : (drHigh + drLow) / 2;
              const range  = drHigh - drLow;

              const anchorHighTime = ind.dr.anchor_high_time;
              const anchorLowTime  = ind.dr.anchor_low_time;
              const lastCandleTime = candles[candles.length - 1].time;
              const startTime = (anchorHighTime && anchorLowTime)
                ? Math.min(anchorHighTime, anchorLowTime)
                : (anchorHighTime || anchorLowTime || lastCandleTime);

              function drawBoundedLine(price, color, lineWidth, lineStyle) {
                const ls = chart.addLineSeries({
                  color, lineWidth: lineWidth || 1, lineStyle: lineStyle || 0,
                  priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
                });
                ls.setData([
                  { time: startTime, value: price },
                  { time: lastCandleTime, value: price },
                ]);
                return ls;
              }

              // Bounded line series (visual lines with correct horizontal extent)
              drawBoundedLine(drHigh,   'rgba(255,0,255,0.9)',   1, 0);
              drawBoundedLine(eq,       'rgba(200,200,200,0.6)', 1, 2);
              drawBoundedLine(drLow,    'rgba(0,255,100,0.9)',   1, 0);

              // Axis labels only (lineWidth 0 = invisible line, label still renders)
              const _label = { lineWidth: 0, lineStyle: 0, axisLabelVisible: true, lastValueVisible: false };
              series.createPriceLine({ price: drHigh,   color: 'rgba(255,0,255,0.9)',   title: '100',  ..._label });
              series.createPriceLine({ price: eq,       color: 'rgba(200,200,200,0.6)', title: '50',   ..._label });
              series.createPriceLine({ price: drLow,    color: 'rgba(0,255,100,0.9)',   title: '0',    ..._label });
            }

          } catch (err) {
            console.error('Indicator overlay error:', err);
          }
        }

        chart.timeScale().fitContent();
      })
      .catch(err => {
        if (destroyed) return;
        if (contractAddress) setShowFallback(true);
        else console.error('OHLCV fetch error:', err);
      });

    const ro = new ResizeObserver(() => {
      if (el) chart.applyOptions({ width: el.clientWidth });
    });
    ro.observe(el);

    return () => { destroyed = true; ro.disconnect(); chart.remove(); };
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
  const [showImport, setShowImport] = useTdS(false);
  const [importN, setImportN] = useTdS(20);
  const [importNRaw, setImportNRaw] = useTdS('20');
  const [importMinVolRaw, setImportMinVolRaw] = useTdS('');  // display string e.g. "10M"
  const [importPreview, setImportPreview] = useTdS(null);
  const [importBusy, setImportBusy] = useTdS(false);
  const [importMsg, setImportMsg] = useTdS('');
  const [tooltipVisible, setTooltipVisible] = useTdS(null); // 'selected' | 'all' | null
  const [hlVolumes, setHlVolumes] = useTdS({});
  const [filterType, setFilterType] = useTdS('all');
  const [newSymbol, setNewSymbol] = useTdS('');
  const [newHtf, setNewHtf] = useTdS('4h');
  const [newLtf, setNewLtf] = useTdS('15m');
  const [newContractAddress, setNewContractAddress] = useTdS('');
  const [submitting, setSubmitting] = React.useState(false);
  const [notes, setNotes] = useTdS({});
  const [error, setError] = useTdS(null);
  const [activeStatusFilters, setActiveStatusFilters] = useTdS(new Set());
  const [sortCol, setSortCol] = useTdS(null);
  const [sortDir, setSortDir] = useTdS('asc');
  const [filterTicker, setFilterTicker] = useTdS('');
  const [scannerStrategies, setScannerStrategies] = useTdS([]);
  const [selectedScanStrategies, setSelectedScanStrategies] = useTdS(() => {
    try { return JSON.parse(localStorage.getItem('scanner_active_strategies') || '[]'); }
    catch (_) { return []; }
  });

  function rowKey(r) {
    const sym = r.symbol ? r.symbol.toUpperCase().trim() : '';
    const normalized = ['USDT','USDC','BTC','ETH','BNB'].some(q => sym.endsWith(q) && sym.length > q.length) ? sym : sym + 'USDT';
    return `${normalized}|${r.htf_timeframe || r.interval || '4h'}|${r.ltf_timeframe || '15m'}`;
  }

  useTdE(() => {
    api('/api/trading/strategies').then(data => {
      setScannerStrategies(data || []);
      // Default: select default strategy if nothing stored
      const stored = (() => { try { return JSON.parse(localStorage.getItem('scanner_active_strategies') || '[]'); } catch(_) { return []; } })();
      if (stored.length === 0 && data && data.length > 0) {
        const def = data.find(s => s.is_default === 1) || data[0];
        if (def) {
          setSelectedScanStrategies([def.id]);
          localStorage.setItem('scanner_active_strategies', JSON.stringify([def.id]));
        }
      }
    }).catch(() => {});
  }, []);

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
      const n = {};
      sigs.forEach(s => { n[s.symbol] = s.notes || ''; });
      setNotes(n);
      setLoading(false);
    } catch (e) { setError(e.message); setLoading(false); }
    api('/api/trading/scanner/hl-volumes').then(r => setHlVolumes(r.volumes || {})).catch(() => {});
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

  const displayRows = useTdMemo(() => {
    let rows = sortCol ? [...allRows].sort((a, b) => {
      let av = a[sortCol], bv = b[sortCol];
      if (sortCol === 'confidence_score') {
        av = av || 0; bv = bv || 0;
        return sortDir === 'asc' ? av - bv : bv - av;
      }
      av = (av || '').toLowerCase(); bv = (bv || '').toLowerCase();
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    }) : allRows;
    if (activeStatusFilters.size > 0) {
      rows = rows.filter(r => activeStatusFilters.has(r.status));
    }
    if (filterTicker.trim()) {
      const q = filterTicker.trim().toLowerCase();
      rows = rows.filter(r => (r.symbol || '').toLowerCase().includes(q));
    }
    if (filterType !== 'all') {
      rows = rows.filter(r => {
        const v = hlVolumes[(r.symbol || '').toUpperCase()];
        const t = v ? v.asset_type : 'crypto';
        return t === filterType;
      });
    }
    return rows;
  }, [allRows, sortCol, sortDir, activeStatusFilters, filterTicker, filterType, hlVolumes]);


  function saveNote(symbol, value) {
    const item = watchlist.find(w => w.symbol === symbol);
    if (!item) return;
    api(`/api/trading/scanner/watchlist/${item.id}`, {
      method: 'PUT', body: JSON.stringify({ notes: value }),
    }).catch(() => {});
  }

  async function addSymbol() {
    if (!newSymbol.trim() || submitting) return;
    setSubmitting(true);
    const sym = normalizeSymbol(newSymbol);
    try {
      await api('/api/trading/scanner/watchlist', {
        method: 'POST',
        body: JSON.stringify({
          symbol: sym,
          htf_timeframe: newHtf,
          ltf_timeframe: newLtf,
          contract_address: newContractAddress.trim(),
        }),
      });
      setNewSymbol(''); setNewContractAddress(''); setShowAdd(false); load();
    } catch (e) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
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
      const body = { symbols: symList };
      if (selectedScanStrategies.length > 0) body.strategy_ids = selectedScanStrategies;
      await api('/api/trading/scanner/run', { method: 'POST', body: JSON.stringify(body) });
      await load();
    } catch (e) { setError(e.message); }
    finally { setRunning(false); }
  }

  async function runScanAll() {
    setRunning(true); setError(null);
    try {
      const _allBody = selectedScanStrategies.length > 0 ? { strategy_ids: selectedScanStrategies } : {};
      await api('/api/trading/scanner/run', { method: 'POST', body: JSON.stringify(_allBody) });
      await load();
    } catch (e) { setError(e.message); }
    finally { setRunning(false); }
  }

  function fmtSymbol(sym) {
    if (!sym) return sym;
    const upper = sym.toUpperCase();
    for (const suffix of ['-USDT', '-USDC', '-USD', 'USDT', 'USDC', 'USD']) {
      if (upper.endsWith(suffix)) {
        return sym.slice(0, sym.length - suffix.length);
      }
    }
    return sym;
  }

  const _costRate = () => parseFloat(localStorage.getItem('scanner_cost_per_symbol') || '0.012') || 0.012;
  function fmtCost(n) {
    const cost = n * _costRate();
    return cost < 0.01 ? '<$0.01' : '$' + cost.toFixed(2);
  }

  function parseVolShorthand(s) {
    if (!s || !s.trim()) return 0;
    const m = s.trim().toUpperCase().match(/^(\d+\.?\d*)\s*([KMB]?)$/);
    if (!m) return 0;
    const n = parseFloat(m[1]);
    const mult = { K: 1e3, M: 1e6, B: 1e9 }[m[2]] || 1;
    return n * mult;
  }

  function fmtVolFull(n) {
    if (!n) return '';
    return '= $' + n.toLocaleString('en-US', { maximumFractionDigits: 0 });
  }

  async function hlPreview() {
    setImportBusy(true); setImportPreview(null); setImportMsg('');
    try {
      const minVol = parseVolShorthand(importMinVolRaw);
      const data = await api(`/api/trading/scanner/hl-top-volume?n=${importN}${minVol > 0 ? `&min_volume=${minVol}` : ''}`);
      setImportPreview(data.assets || []);
    } catch (e) { setImportMsg(`Error: ${e.message}`); }
    finally { setImportBusy(false); }
  }

  async function hlImport() {
    setImportBusy(true); setImportMsg('');
    try {
      const minVol = parseVolShorthand(importMinVolRaw);
      const res = await api('/api/trading/scanner/hl-import', {
        method: 'POST',
        body: JSON.stringify({ n: importN, ...(minVol > 0 ? { min_volume: minVol } : {}) }),
      });
      setImportMsg(`Imported ${res.added} new symbols, skipped ${res.skipped} already present, removed ${res.removed} quiet entries`);
      await load();
      setTimeout(() => { setShowImport(false); setImportMsg(''); setImportPreview(null); }, 2000);
    } catch (e) { setImportMsg(`Error: ${e.message}`); }
    finally { setImportBusy(false); }
  }

  function toggleChecked(k) {
    setCheckedKeys(prev => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k); else next.add(k);
      return next;
    });
  }

  function handleSort(col) {
    if (sortCol === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortCol(col);
      setSortDir(col === 'confidence_score' ? 'desc' : 'asc');
    }
  }

  if (loading) return React.createElement('div', { className: 'tv-label', style: { padding: 32 } }, 'Loading…');

  const allKeys = allRows.map(r => rowKey(r));
  const allChecked = allKeys.length > 0 && allKeys.every(k => checkedKeys.has(k));
  const someChecked = !allChecked && allKeys.some(k => checkedKeys.has(k));
  const visibleRows = displayRows;
  const statusCounts = {};
  allRows.forEach(r => { if (r.status) statusCounts[r.status] = (statusCounts[r.status] || 0) + 1; });

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 12, padding: '16px 0' } },
    error && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13, padding: '0 4px' } }, error),

    /* TOP — full-width table card */
    /* Strategy selector chips */
    scannerStrategies.length > 0 && React.createElement('div', { style: { display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 4 } },
      React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.06em' } }, 'Strategy:'),
      scannerStrategies.map(s =>
        React.createElement('span', {
          key: s.id,
          onClick: () => setSelectedScanStrategies(prev => {
            const next = prev.includes(s.id) ? prev.filter(x => x !== s.id) : (prev.length >= 3 ? prev : [...prev, s.id]);
            localStorage.setItem('scanner_active_strategies', JSON.stringify(next));
            return next;
          }),
          style: {
            fontSize: 11, padding: '2px 8px', borderRadius: 10, cursor: 'pointer', userSelect: 'none',
            background: selectedScanStrategies.includes(s.id) ? 'var(--accent)' : 'var(--panel)',
            color: selectedScanStrategies.includes(s.id) ? '#000' : 'var(--text4)',
            border: selectedScanStrategies.includes(s.id) ? '1px solid var(--accent)' : '1px solid rgba(255,255,255,0.12)',
          }
        }, s.name + (s.is_default ? ' ✦' : ''))
      )
    ),

    React.createElement('div', { className: 'tv-card', style: { padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' } },

      /* Header bar */
      React.createElement('div', {
        style: { display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderBottom: '1px solid var(--line)', flexWrap: 'wrap' }
      },
        (() => {
          const CHIP_ORDER = ['alert', 'watch', 'active', 'forming', 'watching', 'quiet', 'error'];
          const present = Object.keys(statusCounts);
          const ordered = [
            ...CHIP_ORDER.filter(s => present.includes(s)),
            ...present.filter(s => !CHIP_ORDER.includes(s)).sort(),
          ];
          return ordered.map(st => {
            const cnt = statusCounts[st];
            if (!cnt) return null;
            const cfg = STATUS_CONFIG[st] || { color: 'var(--text3)', label: st };
            const isActive = activeStatusFilters.has(st);
            return React.createElement('span', {
              key: st,
              onClick: () => setActiveStatusFilters(prev => {
                const next = new Set(prev);
                if (next.has(st)) next.delete(st); else next.add(st);
                return next;
              }),
              style: {
                fontSize: 11, padding: '2px 8px', borderRadius: 10, cursor: 'pointer',
                background: isActive ? 'var(--accent)' : 'var(--panel)',
                color: isActive ? '#000' : 'var(--text4)',
                border: isActive ? '1px solid var(--accent)' : '1px solid rgba(255,255,255,0.12)',
                fontWeight: isActive ? 600 : 400,
              },
            }, (isActive ? '✓ ' : '') + `${cnt} ${cfg.label || st}`);
          });
        })(),
        React.createElement('div', { style: { flex: 1, textAlign: 'center' } },
        ),
        // Scan Selected with cost tooltip
        React.createElement('div', { style: { position: 'relative', display: 'inline-block' } },
          React.createElement('button', {
            className: 'tv-btn primary',
            disabled: running || checkedKeys.size === 0,
            onClick: runScanSelected,
            style: { fontSize: 12, padding: '4px 12px' },
            onMouseEnter: () => setTooltipVisible('selected'),
            onMouseLeave: () => setTooltipVisible(null),
          }, running ? 'Scanning…' : '▶ Scan Selected'),
          tooltipVisible === 'selected' && React.createElement('div', {
            style: { position: 'absolute', bottom: '110%', left: '50%', transform: 'translateX(-50%)', background: 'var(--panel2)', border: '1px solid var(--line)', borderRadius: 6, padding: '5px 10px', fontSize: 11, color: 'var(--text4)', whiteSpace: 'nowrap', zIndex: 100, pointerEvents: 'none' }
          }, checkedKeys.size === 0 ? 'Select symbols to scan' : `~${fmtCost(checkedKeys.size)} estimated (${checkedKeys.size} symbols)`)
        ),
        // Scan All with cost tooltip
        React.createElement('div', { style: { position: 'relative', display: 'inline-block' } },
          React.createElement('button', {
            className: 'tv-btn',
            disabled: running || watchlist.length === 0,
            onClick: runScanAll,
            style: { fontSize: 12, padding: '4px 12px' },
            onMouseEnter: () => setTooltipVisible('all'),
            onMouseLeave: () => setTooltipVisible(null),
          }, 'Scan All'),
          tooltipVisible === 'all' && React.createElement('div', {
            style: { position: 'absolute', bottom: '110%', left: '50%', transform: 'translateX(-50%)', background: 'var(--panel2)', border: '1px solid var(--line)', borderRadius: 6, padding: '5px 10px', fontSize: 11, color: 'var(--text4)', whiteSpace: 'nowrap', zIndex: 100, pointerEvents: 'none' }
          }, watchlist.length === 0 ? 'No symbols in watchlist' : `~${fmtCost(watchlist.length)} estimated (${watchlist.length} symbols)`)
        ),
        React.createElement('button', {
          className: 'tv-btn',
          onClick: () => setShowAdd(v => !v),
          style: { fontSize: 12, padding: '4px 12px' },
        }, showAdd ? '✕ Cancel' : '+ Add'),
        React.createElement('button', {
          className: 'tv-btn',
          onClick: () => { setShowImport(v => !v); setImportPreview(null); setImportMsg(''); },
          style: { fontSize: 12, padding: '4px 12px' },
        }, showImport ? '✕' : '⬇ Import HL'),
        React.createElement('button', {
          className: 'tv-btn',
          style: { fontSize: 12, color: 'var(--fail)', borderColor: 'var(--fail)' },
          onClick: async () => {
            if (!confirm('Remove all tickers from watchlist? This cannot be undone.')) return;
            await api('/api/trading/scanner/watchlist/all', { method: 'DELETE' });
            load();
          }
        }, 'Remove All')
      ),

      /* Type filter chips */
      React.createElement('div', { style: { display: 'flex', gap: 6, padding: '6px 14px', borderBottom: '1px solid var(--line-soft)', alignItems: 'center' } },
        React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)', marginRight: 2 } }, 'Type:'),
        ['all', 'crypto', 'tradfi'].map(t =>
          React.createElement('span', {
            key: t,
            onClick: () => setFilterType(t),
            style: {
              fontSize: 11, cursor: 'pointer', padding: '2px 8px', borderRadius: 10,
              background: filterType === t ? 'var(--accent)' : 'var(--panel3)',
              color: filterType === t ? '#000' : 'var(--text3)',
              border: filterType === t ? 'none' : '1px solid var(--line)',
              textTransform: 'capitalize',
            }
          }, t)
        )
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
            onKeyDown: e => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); addSymbol(); } },
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
          ),
          React.createElement('button', { className: 'tv-btn primary', onClick: addSymbol, disabled: submitting }, submitting ? 'Adding…' : '+ Add')
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

      ),

      /* HL Import panel */
      showImport && React.createElement('div', {
        style: { display: 'flex', flexDirection: 'column', gap: 10, padding: '12px 14px', borderBottom: '1px solid var(--line)', background: 'var(--panel)' }
      },
        React.createElement('div', { style: { display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' } },
          // N input
          React.createElement('div', null,
            React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginBottom: 4 } }, 'Top N by volume'),
            React.createElement('input', {
              className: 'tv-input', type: 'text', inputMode: 'numeric', pattern: '[0-9]*', value: importNRaw,
              style: { width: 70, fontSize: 12 },
              onChange: e => {
                const raw = e.target.value.replace(/[^0-9]/g, '');
                setImportNRaw(raw);
                const n = parseInt(raw);
                if (n >= 1 && n <= 200) setImportN(n);
              },
              onBlur: () => {
                const n = parseInt(importNRaw);
                const clamped = (!n || n < 1) ? 1 : n > 200 ? 200 : n;
                setImportN(clamped);
                setImportNRaw(String(clamped));
              },
            })
          ),
          // Min volume input
          React.createElement('div', null,
            React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 4 } },
              React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)' } }, 'Min 24h Vol'),
              (() => {
                const v = parseVolShorthand(importMinVolRaw);
                return v > 0 ? React.createElement('span', { style: { fontSize: 10, color: 'var(--text4)', opacity: 0.7 } }, fmtVolFull(v)) : null;
              })()
            ),
            React.createElement('input', {
              className: 'tv-input', placeholder: 'e.g. 10M', value: importMinVolRaw,
              style: { width: 90, fontSize: 12 },
              onChange: e => setImportMinVolRaw(e.target.value),
            })
          ),
          // Action buttons
          React.createElement('div', { style: { display: 'flex', gap: 6 } },
            React.createElement('button', { className: 'tv-btn', style: { fontSize: 12 }, disabled: importBusy, onClick: hlPreview }, importBusy ? '…' : 'Preview'),
            React.createElement('button', { className: 'tv-btn primary', style: { fontSize: 12 }, disabled: importBusy, onClick: hlImport }, importBusy ? 'Importing…' : 'Import'),
            React.createElement('button', { className: 'tv-btn', style: { fontSize: 12 }, onClick: () => { setShowImport(false); setImportPreview(null); setImportMsg(''); } }, 'Cancel')
          )
        ),
        importMsg && React.createElement('div', { style: { fontSize: 12, color: importMsg.startsWith('Error') ? 'var(--fail)' : 'var(--ok)' } }, importMsg),
        importPreview && React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginBottom: 2 } },
            `${importPreview.filter(a => !a.in_watchlist).length} new, ${importPreview.filter(a => a.in_watchlist).length} already in watchlist`
          ),
          importPreview.map((a, i) =>
            React.createElement('div', { key: a.symbol, style: { display: 'flex', gap: 8, fontSize: 11, alignItems: 'center' } },
              React.createElement('span', { style: { color: 'var(--text4)', width: 20, textAlign: 'right' } }, i + 1),
              React.createElement('span', { style: { fontWeight: 600, width: 80 } }, fmtSymbol(a.symbol)),
              React.createElement('span', { style: { color: 'var(--text4)', width: 60 } }, a.volume_display),
              a.in_watchlist && React.createElement('span', { style: { fontSize: 10, color: 'var(--text4)', padding: '1px 5px', borderRadius: 4, background: 'var(--panel3)', border: '1px solid var(--line)' } }, 'in watchlist')
            )
          )
        )
      ),

      /* Cost estimate bar */
      React.createElement('div', { style: { display: 'flex', gap: 20, padding: '5px 14px', borderTop: '1px solid var(--line-soft)', fontSize: 11, color: 'var(--text4)' } },
        React.createElement('span', null,
          'Scan Selected: ',
          checkedKeys.size === 0
            ? React.createElement('span', null, 'No symbols selected')
            : React.createElement('span', { style: { color: 'var(--text3)' } }, `~${fmtCost(checkedKeys.size)} (${checkedKeys.size} symbols)`)
        ),
        React.createElement('span', null,
          'Scan All: ',
          watchlist.length === 0
            ? React.createElement('span', null, 'No symbols in watchlist')
            : React.createElement('span', { style: { color: 'var(--text3)' } }, `~${fmtCost(watchlist.length)} (${watchlist.length} symbols)`)
        )
      ),

      /* Table */
      React.createElement('div', { style: { maxHeight: 'calc(100vh - 280px)', overflowY: 'auto', overflowX: 'auto' } },
        allRows.length === 0
          ? React.createElement('div', { style: { color: 'var(--text4)', fontSize: 13, padding: 32, textAlign: 'center' } },
              'No symbols in watchlist. Add some and run a scan.')
          : React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse' } },
              React.createElement('thead', { style: { position: 'sticky', top: 0, background: 'var(--panel)', zIndex: 1 } },
                /* Row 1 — labels */
                React.createElement('tr', { style: { borderBottom: '1px solid var(--line-soft)' } },
                  React.createElement('th', { style: { padding: '8px 10px', width: 32 } },
                    React.createElement('input', {
                      type: 'checkbox',
                      checked: allChecked,
                      ref: el => { if (el) el.indeterminate = someChecked; },
                      onChange: () => setCheckedKeys(allChecked ? new Set() : new Set(allKeys)),
                    })
                  ),
                  [
                    { label: 'Ticker', col: 'symbol' },
                    { label: '', col: null },
                    { label: 'Status', col: 'status' },
                    { label: '24h Vol', col: null },
                    { label: 'Type', col: null },
                    { label: 'Signal', col: null },
                    { label: 'HTF → LTF', col: null },
                    { label: 'Confidence', col: 'confidence_score' },
                    { label: 'Price', col: null },
                    { label: 'Last Scan', col: null },
                    { label: 'Strategy', col: null },
                    { label: 'Remove', col: null },
                  ].map(({ label, col }) =>
                    React.createElement('th', {
                      key: label,
                      onClick: col ? () => handleSort(col) : undefined,
                      style: {
                        padding: '8px 10px', fontSize: 12,
                        color: col && sortCol === col ? 'var(--text1)' : 'var(--text4)',
                        fontWeight: 500, letterSpacing: '0.08em', textTransform: 'uppercase',
                        textAlign: label === 'Remove' ? 'center' : 'left',
                        cursor: col ? 'pointer' : 'default',
                        userSelect: col ? 'none' : 'auto',
                      }
                    },
                      label === 'Ticker'
                        ? React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6 } },
                            React.createElement('span', null, 'Ticker' + (sortCol === 'symbol' ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '')),
                            React.createElement('div', { style: { position: 'relative', display: 'flex', alignItems: 'center' } },
                              React.createElement('input', {
                                className: 'tv-input',
                                placeholder: 'Filter…',
                                value: filterTicker,
                                style: { padding: '2px 20px 2px 6px', fontSize: 11, height: 22, width: 130, boxSizing: 'border-box', fontWeight: 400, letterSpacing: 'normal', textTransform: 'none' },
                                onClick: e => e.stopPropagation(),
                                onChange: e => { e.stopPropagation(); setFilterTicker(e.target.value); },
                              }),
                              filterTicker && React.createElement('button', {
                                onClick: e => { e.stopPropagation(); setFilterTicker(''); },
                                style: { position: 'absolute', right: 3, background: 'none', border: 'none', color: 'var(--text4)', cursor: 'pointer', fontSize: 13, lineHeight: 1, padding: 0 },
                              }, '×')
                            )
                          )
                        : label + (col && sortCol === col ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '')
                    )
                  )
              ),
            ),
              React.createElement('tbody', null,
                visibleRows.map(row => {
                  const k = rowKey(row);
                  const isSel = selectedKey === k;
                  const cfg = STATUS_CONFIG[row.status] || STATUS_CONFIG.quiet;
                  const htf = row.htf_timeframe || row.interval || '4h';
                  const ltf = row.ltf_timeframe || '15m';
                  const STATUS_COLORS = { active: 'var(--accent)', forming: '#f0c040', watching: '#f0c040', quiet: 'var(--text4)' };
                  const wlItem = watchlist.find(w => rowKey(w) === k);
                  return React.createElement(React.Fragment, { key: k },
                    React.createElement('tr', {
                    onClick: () => setSelectedKey(isSel ? null : k),
                    style: { cursor: 'pointer', borderBottom: isSel ? 'none' : '1px solid var(--line)', background: isSel ? 'var(--panel3)' : 'transparent' }
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
                      React.createElement('strong', { style: { fontSize: 14, fontWeight: 600 } }, fmtSymbol(row.symbol))
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
                    React.createElement('td', { style: { padding: '9px 10px', fontSize: 11, color: 'var(--text4)' } },
                      (() => {
                        const entry = hlVolumes[(row.symbol || '').toUpperCase()];
                        const v = entry ? entry.volume_24h : null;
                        if (!v) return '—';
                        if (v >= 1e9) return '$' + (v / 1e9).toFixed(1) + 'B';
                        if (v >= 1e6) return '$' + (v / 1e6).toFixed(0) + 'M';
                        if (v >= 1e3) return '$' + (v / 1e3).toFixed(0) + 'K';
                        return '$' + v.toFixed(0);
                      })()
                    ),
                    React.createElement('td', { style: { padding: '9px 10px' } },
                      (() => {
                        const entry = hlVolumes[(row.symbol || '').toUpperCase()];
                        const t = entry ? entry.asset_type : null;
                        if (!t) return React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)' } }, '—');
                        const isTradfi = t === 'tradfi';
                        return React.createElement('span', {
                          style: {
                            fontSize: 10, padding: '2px 7px', borderRadius: 10, fontWeight: 600,
                            letterSpacing: '0.05em', textTransform: 'uppercase',
                            background: isTradfi ? 'rgba(99,179,237,0.15)' : 'rgba(72,187,120,0.15)',
                            color: isTradfi ? '#63b3ed' : '#48bb78',
                            border: isTradfi ? '1px solid rgba(99,179,237,0.3)' : '1px solid rgba(72,187,120,0.3)',
                          }
                        }, isTradfi ? 'TradFi' : 'Crypto')
                      })()
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
                    React.createElement('td', { style: { padding: '9px 10px', fontSize: 11, color: 'var(--text4)', whiteSpace: 'nowrap' } },
                      (() => {
                        const ts = row.scanned_at || row.detected_at || row.updated_at || row.created_at;
                        if (!ts) return '—';
                        const d = new Date(ts + (ts.endsWith('Z') ? '' : 'Z'));
                        if (isNaN(d)) return '—';
                        const userTZ = Intl.DateTimeFormat().resolvedOptions().timeZone;
                        const opts = { timeZone: userTZ, month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true };
                        if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
                        return d.toLocaleString('en-US', opts);
                      })()
                    ),
                    React.createElement('td', { style: { padding: '9px 10px', fontSize: 11, color: 'var(--text4)', whiteSpace: 'nowrap' } },
                      (() => { const s = scannerStrategies.find(st => st.id === row.strategy_id); return s ? s.name : (row.strategy_id ? `#${row.strategy_id}` : '—'); })()
                    ),
                    React.createElement('td', { style: { padding: '9px 4px', textAlign: 'center' } },
                      wlItem && React.createElement('button', {
                        style: { color: 'var(--fail)', fontSize: 12, cursor: 'pointer', background: 'none', border: 'none', padding: '4px 8px' },
                        onClick: e => { e.stopPropagation(); handleRemove(wlItem.id); },
                      }, '✕')
                    )
                  ),
                    isSel && React.createElement('tr', { key: `${k}-detail` },
                      React.createElement('td', { colSpan: 13, style: { padding: 16, background: 'var(--panel2)', borderBottom: '1px solid var(--line)' } },
                        (() => {
                          const brief = row.why_flagged || '';
                          const HTF_KW = ['HTF Stoch','HTF RSI','HTF stoch','HTF rsi','HTF','1w','1d','4h','weekly','daily','dealing range','EQ','bias','BOS','MSB'];
                          const LTF_KW = ['LTF Stoch','LTF RSI','LTF stoch','LTF rsi','LTF','1h','15m','5m','CHoCH','sweep','entry trigger','OB tap','FVG return'];
                          const sentences = brief.split(/(?<=[.!?])\s+|\n+/).map(s => s.trim()).filter(s => s.length > 4);
                          if (sentences.length < 2) {
                            return React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)', lineHeight: 1.6 } },
                              brief || React.createElement('span', { style: { color: 'var(--text4)' } }, 'No active setup detected.')
                            );
                          }
                          const htfBullets = [], ltfBullets = [];
                          sentences.forEach(s => {
                            const su = s.toUpperCase();
                            // Explicit "HTF " / "LTF " prefix takes priority over all other keyword matches
                            const hasHTFPrefix = su.includes('HTF ');
                            const hasLTFPrefix = su.includes('LTF ');
                            let isHTF = hasHTFPrefix || (!hasLTFPrefix && HTF_KW.some(kw => su.includes(kw.toUpperCase())));
                            let isLTF = hasLTFPrefix || (!hasHTFPrefix && LTF_KW.some(kw => su.includes(kw.toUpperCase())));
                            if (hasHTFPrefix && hasLTFPrefix) { isHTF = false; isLTF = true; } // "LTF" wins if both appear
                            if (isHTF && !isLTF) htfBullets.push(s);
                            else if (isLTF && !isHTF) ltfBullets.push(s);
                            else if (htfBullets.length <= ltfBullets.length) htfBullets.push(s);
                            else ltfBullets.push(s);
                          });
                          const htfTF = row.htf_timeframe || row.interval || '';
                          const ltfTF = row.ltf_timeframe || '';
                          const BulletCol = ({ label, tf, color, bullets }) =>
                            React.createElement('div', { style: { flex: 1, minWidth: 0 } },
                              React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 5, marginBottom: 5 } },
                                React.createElement('span', { style: { fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color } }, label),
                                tf && React.createElement('span', { style: { fontSize: 9, color, opacity: 0.7 } }, `· ${tf}`)
                              ),
                              bullets.slice(0, 4).map((b, i) =>
                                React.createElement('div', { key: i, style: { display: 'flex', gap: 5, fontSize: 12, color: 'var(--text3)', lineHeight: 1.4, marginBottom: 3 } },
                                  React.createElement('span', { style: { color, flexShrink: 0, marginTop: 1 } }, '•'),
                                  React.createElement('span', null, b)
                                )
                              )
                            );
                          return React.createElement('div', { style: { display: 'flex', gap: 16 } },
                            React.createElement(BulletCol, { label: 'HTF', tf: htfTF, color: 'var(--accent)', bullets: htfBullets }),
                            React.createElement(BulletCol, { label: 'LTF', tf: ltfTF, color: 'var(--ok)', bullets: ltfBullets })
                          );
                        })()
                      )
                    )
                  );
                })
              )
            ),
        filterTicker.trim() && React.createElement('div', {
          style: { fontSize: 11, color: 'var(--text4)', textAlign: 'center', padding: '5px 0', fontStyle: 'italic' },
        }, `Filters active — showing ${displayRows.length} of ${allRows.length}`)
      )
    )

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

/* ===== TRADING SETTINGS SCREEN ===== */
function TradingSettingsScreen() {
  const { useState: useTsS, useEffect: useTsE, useRef: useTsR } = React;

  const [strategies, setStrategies] = useTsS([]);
  const [loading, setLoading] = useTsS(true);
  const [error, setError] = useTsS(null);
  const [showAddForm, setShowAddForm] = useTsS(false);
  const [addName, setAddName] = useTsS('');
  const [addDesc, setAddDesc] = useTsS('');
  const [addBusy, setAddBusy] = useTsS(false);
  const [expandedTree, setExpandedTree] = useTsS({});   // { [id]: bool }
  const [treeInstr, setTreeInstr] = useTsS({});          // { [id]: string }
  const [treeBusy, setTreeBusy] = useTsS({});            // { [id]: bool }
  const [treeDiff, setTreeDiff] = useTsS({});            // { [id]: {proposed, original} }
  const [promptDraft, setPromptDraft] = useTsS({});      // { [id]: string }
  const [promptSaving, setPromptSaving] = useTsS({});    // { [id]: bool }
  const [descDraft, setDescDraft] = useTsS({});
  const [defaultSaving, setDefaultSaving] = useTsS({});
  const [defaultMsg, setDefaultMsg] = useTsS('');
  const [scannerSelected, setScannerSelected] = useTsS(() => {
    try { return JSON.parse(localStorage.getItem('scanner_active_strategies') || '[]'); }
    catch (_) { return []; }
  });
  const [costPerSymbol, setCostPerSymbol] = useTsS(() => {
    return localStorage.getItem('scanner_cost_per_symbol') || '0.012';
  });

  function loadStrategies() {
    setLoading(true); setError(null);
    api('/api/trading/strategies')
      .then(data => {
        setStrategies(data);
        const drafts = {}; const ddescs = {};
        data.forEach(s => { drafts[s.id] = s.ai_prompt || ''; ddescs[s.id] = s.description || ''; });
        setPromptDraft(drafts); setDescDraft(ddescs);
        setLoading(false);
      })
      .catch(e => { setError(e.message); setLoading(false); });
  }

  useTsE(() => { loadStrategies(); }, []);

  function toggleScanner(id) {
    setScannerSelected(prev => {
      const next = prev.includes(id) ? prev.filter(x => x !== id) : (prev.length >= 3 ? prev : [...prev, id]);
      localStorage.setItem('scanner_active_strategies', JSON.stringify(next));
      return next;
    });
  }

  async function setDefault(id) {
    setDefaultSaving(p => ({ ...p, [id]: true }));
    try {
      await api(`/api/trading/strategies/${id}/set-default`, { method: 'POST' });
      setDefaultMsg('✓ Saved');
      loadStrategies();
      setTimeout(() => setDefaultMsg(''), 2000);
    } catch (e) { setError(e.message); }
    setDefaultSaving(p => ({ ...p, [id]: false }));
  }

  async function softDelete(id, name) {
    if (!confirm(`Remove strategy "${name}"? It will be hidden but not deleted.`)) return;
    try {
      await api(`/api/trading/strategies/${id}`, { method: 'DELETE' });
      loadStrategies();
    } catch (e) { setError(e.message); }
  }

  async function savePrompt(id) {
    setPromptSaving(p => ({ ...p, [id]: true }));
    try {
      await api(`/api/trading/strategies/${id}`, { method: 'PUT', body: JSON.stringify({ ai_prompt: promptDraft[id] || '' }) });
    } catch (e) { setError(e.message); }
    setPromptSaving(p => ({ ...p, [id]: false }));
  }

  async function saveDesc(id) {
    try { await api(`/api/trading/strategies/${id}`, { method: 'PUT', body: JSON.stringify({ description: descDraft[id] || '' }) }); }
    catch (_) {}
  }

  async function addStrategy() {
    if (!addName.trim()) return;
    setAddBusy(true);
    try {
      const stub = { base_flow: [], adaptive_steps: {}, risk_step: { id: 'risk', label: 'Risk / Inv.', stepType: 'LTF', isForm: true, question: 'Define your risk parameters.', subtext: '' } };
      await api('/api/trading/strategies', { method: 'POST', body: JSON.stringify({ name: addName.trim(), description: addDesc.trim(), ai_prompt: '', flow_json: stub }) });
      setAddName(''); setAddDesc(''); setShowAddForm(false);
      loadStrategies();
    } catch (e) { setError(e.message); }
    setAddBusy(false);
  }

  async function applyTreeAI(id) {
    const instr = (treeInstr[id] || '').trim();
    if (!instr) return;
    setTreeBusy(p => ({ ...p, [id]: true }));
    try {
      const res = await api(`/api/trading/strategies/${id}/update-tree`, { method: 'POST', body: JSON.stringify({ instruction: instr }) });
      setTreeDiff(p => ({ ...p, [id]: { proposed: res.proposed_flow_json, original: res.original_flow_json } }));
    } catch (e) { setError(e.message); }
    setTreeBusy(p => ({ ...p, [id]: false }));
  }

  async function confirmTreeUpdate(id) {
    const proposed = treeDiff[id]?.proposed;
    if (!proposed) return;
    try {
      await api(`/api/trading/strategies/${id}`, { method: 'PUT', body: JSON.stringify({ flow_json: proposed }) });
      setTreeDiff(p => { const n = { ...p }; delete n[id]; return n; });
      setTreeInstr(p => { const n = { ...p }; delete n[id]; return n; });
      loadStrategies();
    } catch (e) { setError(e.message); }
  }

  function FlowVisualizer({ flow }) {
    if (!flow) return React.createElement('div', { style: { color: 'var(--text4)', fontSize: 18, fontStyle: 'italic' } }, 'No flow defined.');
    const steps = [...(flow.base_flow || [])];
    if (flow.risk_step) steps.push({ ...flow.risk_step, _isRisk: true });
    return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
      steps.map((step, i) => {
        const isHTF = step.stepType === 'HTF';
        const isRisk = step._isRisk || step.isForm;
        const circleColor = isRisk ? 'var(--adapt)' : isHTF ? 'var(--accent)' : 'var(--ok)';
        return React.createElement('div', { key: step.id || i, style: { display: 'flex', gap: 10, alignItems: 'flex-start' } },
          React.createElement('div', { style: { width: 24, height: 24, borderRadius: '50%', background: circleColor, color: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700, flexShrink: 0 } }, i + 1),
          React.createElement('div', { style: { flex: 1, minWidth: 0 } },
            React.createElement('div', { style: { display: 'flex', gap: 6, alignItems: 'center', marginBottom: 2, flexWrap: 'wrap' } },
              React.createElement('span', { style: { fontWeight: 600, fontSize: 18 } }, step.label),
              React.createElement('span', { style: { fontSize: 9, padding: '1px 4px', borderRadius: 2, background: isRisk ? 'var(--adapt-soft)' : isHTF ? 'var(--accent-soft)' : 'var(--ok-soft)', color: isRisk ? 'var(--adapt)' : isHTF ? 'var(--accent)' : 'var(--ok)' } }, isRisk ? 'Form' : step.stepType)
            ),
            React.createElement('div', { style: { fontSize: 16, color: 'var(--text4)', marginBottom: 4 } }, step.question),
            step.options && React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 2 } },
              step.options.map(opt => React.createElement('div', { key: opt.key, style: { display: 'flex', gap: 6, fontSize: 15, color: 'var(--text3)', alignItems: 'center' } },
                React.createElement('span', { style: { width: 14, height: 14, borderRadius: 2, background: 'var(--panel3)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, fontWeight: 700, fontSize: 9 } }, opt.key),
                React.createElement('span', { style: { flex: 1 } }, opt.title),
                opt.endsFlow && React.createElement('span', { style: { color: 'var(--fail)', fontSize: 9 } }, '⊗ ends flow'),
                opt.branches && !opt.endsFlow && React.createElement('span', { style: { color: 'var(--text4)', fontSize: 9 } }, `↓${opt.branches}`)
              ))
            )
          )
        );
      })
    );
  }

  const lbl = t => React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginBottom: 3, textTransform: 'uppercase', letterSpacing: '0.06em' } }, t);

  if (loading) return React.createElement('div', { className: 'tv-label', style: { padding: 32 } }, 'Loading…');

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 24, padding: '16px 0' } },
    error && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13 } }, error),

    /* ── SECTION 1: Strategies ── */
    React.createElement('div', null,
      React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 } },
        React.createElement('div', { style: { fontSize: 15, fontWeight: 700, color: 'var(--accent)' } }, 'Strategies'),
        React.createElement('button', { className: 'tv-btn primary', style: { fontSize: 12 }, onClick: () => setShowAddForm(p => !p) }, showAddForm ? '✕ Cancel' : 'Add Strategy +')
      ),

      showAddForm && React.createElement('div', { className: 'tv-card', style: { marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 8 } },
        lbl('New Strategy'),
        React.createElement('input', { className: 'tv-input', placeholder: 'Name', value: addName, onChange: e => setAddName(e.target.value) }),
        React.createElement('input', { className: 'tv-input', placeholder: 'Description (optional)', value: addDesc, onChange: e => setAddDesc(e.target.value) }),
        React.createElement('button', { className: 'tv-btn primary', disabled: !addName.trim() || addBusy, onClick: addStrategy, style: { fontSize: 12 } }, addBusy ? 'Creating…' : 'Create Strategy')
      ),

      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 12 } },
        strategies.map(s => {
          const isExpanded = expandedTree[s.id];
          const diff = treeDiff[s.id];
          return React.createElement('div', { key: s.id, className: 'tv-card', style: { display: 'flex', flexDirection: 'column', gap: 12 } },
            /* Top row */
            React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 } },
              React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center' } },
                React.createElement('span', { style: { fontWeight: 700, fontSize: 14 } }, s.name),
                s.is_default === 1 && React.createElement('span', { style: { fontSize: 10, padding: '2px 7px', borderRadius: 10, background: 'var(--accent-soft)', color: 'var(--accent)', border: '1px solid var(--accent-line)', fontWeight: 600 } }, 'DEFAULT')
              ),
              React.createElement('div', { style: { display: 'flex', gap: 6 } },
                s.is_default !== 1 && React.createElement('button', { className: 'tv-btn', style: { fontSize: 11 }, disabled: defaultSaving[s.id], onClick: () => setDefault(s.id) }, 'Set as Default'),
                React.createElement('button', { className: 'tv-btn danger', style: { fontSize: 11 }, onClick: () => softDelete(s.id, s.name) }, 'Remove')
              )
            ),
            /* Description */
            React.createElement('div', null,
              lbl('Description'),
              React.createElement('input', { className: 'tv-input', value: descDraft[s.id] || '', style: { width: '100%' }, onChange: e => setDescDraft(p => ({ ...p, [s.id]: e.target.value })), onBlur: () => saveDesc(s.id) })
            ),
            /* AI Prompt */
            React.createElement('div', null,
              lbl('AI Prompt — used by Scanner and Validator thesis generation'),
              React.createElement('textarea', { className: 'tv-input', rows: 6, value: promptDraft[s.id] || '', style: { width: '100%', fontFamily: 'Fira Code, monospace', fontSize: 12, resize: 'vertical' }, onChange: e => setPromptDraft(p => ({ ...p, [s.id]: e.target.value })) }),
              React.createElement('button', { className: 'tv-btn primary', style: { fontSize: 12, marginTop: 6 }, disabled: promptSaving[s.id], onClick: () => savePrompt(s.id) }, promptSaving[s.id] ? 'Saving…' : 'Save Prompt')
            ),
            /* Validator Tree */
            React.createElement('div', null,
              React.createElement('button', { className: 'tv-btn', style: { fontSize: 12 }, onClick: () => setExpandedTree(p => ({ ...p, [s.id]: !p[s.id] })) }, `${isExpanded ? '▼' : '▶'} Validator Tree`),
              isExpanded && React.createElement('div', { style: { marginTop: 12, display: 'flex', flexDirection: 'column', gap: 12 } },
                /* Diff view or single view */
                diff
                  ? React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } },
                      React.createElement('div', { className: 'tv-card', style: { padding: 12 } },
                        React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginBottom: 8, textTransform: 'uppercase' } }, 'Current'),
                        React.createElement(FlowVisualizer, { flow: diff.original })
                      ),
                      React.createElement('div', { className: 'tv-card', style: { padding: 12, borderColor: 'var(--adapt)' } },
                        React.createElement('div', { style: { fontSize: 11, color: 'var(--adapt)', marginBottom: 8, textTransform: 'uppercase' } }, 'Proposed'),
                        React.createElement(FlowVisualizer, { flow: diff.proposed })
                      )
                    )
                  : React.createElement('div', { className: 'tv-card', style: { padding: 12 } },
                      React.createElement(FlowVisualizer, { flow: s.flow_json })
                    ),
                /* AI edit panel */
                React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
                  React.createElement('textarea', { className: 'tv-input', rows: 3, value: treeInstr[s.id] || '', placeholder: "Describe your change, e.g. 'switch steps 3 and 4' or 'add an OB confirmation step after step 2'", style: { width: '100%', fontFamily: 'inherit', fontSize: 13 }, onChange: e => setTreeInstr(p => ({ ...p, [s.id]: e.target.value })) }),
                  React.createElement('div', { style: { display: 'flex', gap: 8 } },
                    React.createElement('button', { className: 'tv-btn primary', disabled: treeBusy[s.id] || !(treeInstr[s.id] || '').trim(), style: { fontSize: 12 }, onClick: () => applyTreeAI(s.id) }, treeBusy[s.id] ? 'Generating…' : 'Apply with AI →'),
                    diff && React.createElement('button', { className: 'tv-btn primary', style: { fontSize: 12, background: 'var(--ok)', borderColor: 'var(--ok)', color: '#000' }, onClick: () => confirmTreeUpdate(s.id) }, '✓ Confirm & Save'),
                    diff && React.createElement('button', { className: 'tv-btn danger', style: { fontSize: 12 }, onClick: () => { setTreeDiff(p => { const n = { ...p }; delete n[s.id]; return n; }); setTreeInstr(p => ({ ...p, [s.id]: '' })); } }, '✗ Reject')
                  )
                )
              )
            )
          );
        })
      )
    ),

    /* ── SECTION 2: Scanner Settings ── */
    React.createElement('div', null,
      React.createElement('div', { style: { fontSize: 15, fontWeight: 700, color: 'var(--accent)', marginBottom: 12 } }, 'Scanner Settings'),
      React.createElement('div', { className: 'tv-card', style: { display: 'flex', flexDirection: 'column', gap: 10 } },
        React.createElement('div', null,
          lbl('Active Strategies'),
          React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', marginBottom: 8 } }, 'Select up to 3 strategies to run on each scan.'),
          React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
            strategies.map(s =>
              React.createElement('label', { key: s.id, style: { display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 } },
                React.createElement('input', { type: 'checkbox', checked: scannerSelected.includes(s.id), onChange: () => toggleScanner(s.id), disabled: !scannerSelected.includes(s.id) && scannerSelected.length >= 3 }),
                s.name,
                s.is_default === 1 && React.createElement('span', { style: { fontSize: 10, color: 'var(--text4)' } }, '(default)')
              )
            )
          )
        ),
        React.createElement('div', null,
          lbl('Estimated cost per symbol (Claude API)'),
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 } },
            React.createElement('span', { style: { fontSize: 13, color: 'var(--text4)' } }, '$'),
            React.createElement('input', {
              className: 'tv-input',
              value: costPerSymbol,
              style: { width: 90, fontSize: 13 },
              onChange: e => {
                setCostPerSymbol(e.target.value);
                localStorage.setItem('scanner_cost_per_symbol', e.target.value);
              },
            })
          ),
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)' } }, 'Used to estimate scan cost. Adjust if your actual costs differ.')
        )
      )
    ),

    /* ── SECTION 3: Validator Settings ── */
    React.createElement('div', null,
      React.createElement('div', { style: { fontSize: 15, fontWeight: 700, color: 'var(--accent)', marginBottom: 12 } }, 'Validator Settings'),
      React.createElement('div', { className: 'tv-card', style: { display: 'flex', flexDirection: 'column', gap: 10 } },
        React.createElement('div', null,
          lbl('Default Strategy'),
          React.createElement('select', {
            className: 'tv-input',
            style: { width: '100%' },
            value: strategies.find(s => s.is_default === 1)?.id || '',
            onChange: e => { if (e.target.value) setDefault(parseInt(e.target.value)); }
          },
            React.createElement('option', { value: '' }, '— select —'),
            strategies.map(s => React.createElement('option', { key: s.id, value: s.id }, s.name))
          ),
          defaultMsg && React.createElement('div', { style: { color: 'var(--ok)', fontSize: 12, marginTop: 4 } }, defaultMsg)
        )
      )
    )
  );
}

/* ===== EXPORTS ===== */
window.ScannerScreen  = ScannerScreen;
window.JournalScreen  = JournalScreen;
window.ValidatorScreen = ValidatorScreen;
window.ReportsScreen   = ReportsScreen;
window.TradingSettingsScreen = TradingSettingsScreen;
