/* ===== TRADING TOOLS v2 ===== */

const { useState: useTdS, useEffect: useTdE, useCallback: useTdCb, useMemo: useTdMemo, useRef: useTdRef } = React;

const STATUS_CONFIG = {
  active:   { color: '#4fdd8e', label: 'Setup Ready'  },
  forming:  { color: '#ffb52e', label: 'POI Waiting'  },
  watching: { color: '#f0c040', label: 'Trend Only', chipBg: 'rgba(240,192,64,0.12)', chipBorder: '1px solid rgba(240,192,64,0.35)' },
  quiet:    { color: 'var(--text4)', label: 'No Trend' },
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

// Strip quote suffix from a symbol for display (BTCUSDT -> BTC)
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

// ===== Scanner v3 HTF definitions =====
// pair_key matches the DB pair_key column (uppercase HTF name).
const HTF_DEFS = [
  { key: '1W',  htf: '1w',  ltf: '4h',  htfLabel: '1W',  ltfLabel: '4H'  },
  { key: '1D',  htf: '1d',  ltf: '1h',  htfLabel: '1D',  ltfLabel: '1H'  },
  { key: '12H', htf: '12h', ltf: '1h',  htfLabel: '12H', ltfLabel: '1H'  },
  { key: '4H',  htf: '4h',  ltf: '15m', htfLabel: '4H',  ltfLabel: '15M' },
  { key: '1H',  htf: '1h',  ltf: '5m',  htfLabel: '1H',  ltfLabel: '5M'  },
];
// Keep PAIR_DEFS as alias so any remaining references don't break during transition
const PAIR_DEFS = HTF_DEFS;

// v3 aesthetic: one uniform pill style for all timeframes
const TF_PILL_UNIFORM = { bg: 'var(--panel3)', fg: 'var(--text2)' };
const TF_PILL_STYLE = {
  '1W':  TF_PILL_UNIFORM, '1D':  TF_PILL_UNIFORM, '12H': TF_PILL_UNIFORM,
  '4H':  TF_PILL_UNIFORM, '1H':  TF_PILL_UNIFORM, '15M': TF_PILL_UNIFORM,
  '5M':  TF_PILL_UNIFORM,
};

function TfPill({ label }) {
  const s = TF_PILL_STYLE[label.toUpperCase()] || TF_PILL_UNIFORM;
  return React.createElement('span', {
    style: {
      fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 3,
      background: s.bg, color: s.fg, fontVariantNumeric: 'tabular-nums',
      whiteSpace: 'nowrap', border: '1px solid var(--line)',
    }
  }, label.toUpperCase());
}

function ConfBar({ value }) {
  const pct = Math.max(0, Math.min(100, value || 0));
  const color = pct > 55 ? '#4fdd8e' : pct >= 35 ? '#ffb52e' : '#7b9cc4';
  return React.createElement('div', {
    style: { height: 3, background: 'var(--line)', borderRadius: 2, overflow: 'hidden', flex: 1, minWidth: 40 }
  }, React.createElement('div', {
    style: { height: '100%', width: `${pct}%`, background: color, borderRadius: 2, transition: 'width 0.3s' }
  }));
}

function PairCell({ pair, def }) {
  if (!pair) return React.createElement('div', {
    style: { color: 'var(--text4)', fontSize: 11, padding: '2px 0' }
  }, '—');
  const status = pair.status || 'quiet';
  const STATE_COLORS = {
    active:   '#4fdd8e',
    forming:  '#ffb52e',
    watching: '#f0c040',
    quiet:    'var(--text4)',
  };
  const color = STATE_COLORS[status] || 'var(--text4)';
  const stateLabel = (STATUS_CONFIG[status] || {}).label || status;

  // Resolve POI from raw_indicators — handles both OB and FVG sources
  const raw = pair.raw_indicators_json || {};
  const htfRaw = raw.htf || {};
  const poiSource = htfRaw.poi_source ||
    (htfRaw.ob ? 'ob' : (htfRaw.fvg ? 'fvg' : null));
  const poiData = poiSource === 'ob' ? htfRaw.ob :
                  poiSource === 'fvg' ? htfRaw.fvg : null;
  const poiLabel = poiData
    ? `${(poiSource || '').toUpperCase()} ${poiData.bottom != null ? poiData.bottom.toFixed(2) : ''}–${poiData.top != null ? poiData.top.toFixed(2) : ''}`
    : null;

  return React.createElement('div', {
    style: { display: 'flex', flexDirection: 'column', gap: 3, padding: '2px 0' }
  },
    React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 5 } },
      React.createElement('span', {
        style: { width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0 }
      }),
      React.createElement('span', { style: { fontSize: 11, color, fontWeight: 600 } }, stateLabel),
      pair.choch_fired && React.createElement('span', {
        style: {
          fontSize: 9, fontWeight: 700, padding: '1px 4px', borderRadius: 3,
          background: 'rgba(79,221,142,0.15)', color: '#4fdd8e',
          border: '1px solid rgba(79,221,142,0.3)', marginLeft: 2,
        }
      }, 'CHoCH')
    ),
    poiLabel && React.createElement('div', {
      style: { fontSize: 10, color: 'var(--text3)', paddingLeft: 11 }
    }, poiLabel)
  );
}

function SetupPanel({ pair, def }) {
  if (!pair) return React.createElement('div', {
    style: { background: 'var(--panel3)', border: '1px solid var(--line)', borderRadius: 10,
             padding: '14px 16px', color: 'var(--text4)', fontSize: 12,
             boxShadow: '0 2px 8px rgba(0,0,0,0.25)' }
  }, 'No data for this timeframe');

  const status = pair.status || 'quiet';
  const STATE_COLORS = { active: '#4fdd8e', forming: '#ffb52e', watching: '#f0c040', quiet: 'var(--text4)' };
  const stateColor = STATE_COLORS[status] || 'var(--text4)';
  const stateLabel = (STATUS_CONFIG[status] || {}).label || status;

  // Resolve POI — handles both OB and FVG sources
  const raw = pair.raw_indicators_json || {};
  const htfRaw = raw.htf || {};
  const ltfRaw = raw.ltf || {};
  const choch  = ltfRaw.choch || {};
  const dr     = htfRaw.dr || null;

  const poiSource = htfRaw.poi_source ||
    (htfRaw.ob ? 'ob' : (htfRaw.fvg ? 'fvg' : null));
  const poiData = poiSource === 'ob'  ? htfRaw.ob  :
                  poiSource === 'fvg' ? htfRaw.fvg : null;

  const fmt = (v, digits) => v != null ? Number(v).toLocaleString('en-US', {
    minimumFractionDigits: digits || 2, maximumFractionDigits: digits || 4
  }) : '—';

  const row = (label, value, valueColor) => React.createElement('div', {
    style: { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
             padding: '4px 0', borderBottom: '1px solid rgba(255,255,255,0.04)' }
  },
    React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)' } }, label),
    React.createElement('span', { style: { fontSize: 12, color: valueColor || 'var(--text2)',
                                            fontVariantNumeric: 'tabular-nums', fontWeight: 500 } }, value)
  );

  // size: 'lg' for HTF/LTF timeframe heads, default for sub-sections
  const sectionHead = (label, color, size) => React.createElement('div', {
    style: { fontSize: size === 'lg' ? 13 : 10, fontWeight: 700,
             color: size === 'lg' ? 'var(--text1)' : 'var(--text4)',
             letterSpacing: '0.08em', textTransform: 'uppercase',
             marginTop: size === 'lg' ? 12 : 10, marginBottom: 4 }
  }, label);

  return React.createElement('div', {
    style: { background: 'var(--panel3)', border: '1px solid var(--line)', borderRadius: 10,
             padding: '14px 16px',
             boxShadow: '0 2px 8px rgba(0,0,0,0.25)' }
  },
    // Header — TF pills + direction + state badge
    React.createElement('div', {
      style: { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12, flexWrap: 'wrap' }
    },
      React.createElement(TfPill, { label: def.htfLabel }),
      React.createElement('span', { style: { color: 'var(--text4)', fontSize: 10 } }, '→'),
      React.createElement(TfPill, { label: def.ltfLabel }),
      (htfRaw.structure === 'bullish' || htfRaw.structure === 'bearish') &&
        React.createElement('span', {
          style: {
            fontSize: 10, fontWeight: 800, padding: '2px 7px', borderRadius: 4,
            letterSpacing: '0.06em',
            background: htfRaw.structure === 'bullish' ? 'rgba(79,221,142,0.15)' : 'rgba(255,107,107,0.15)',
            color:      htfRaw.structure === 'bullish' ? '#4fdd8e' : '#ff6b6b',
            border:     htfRaw.structure === 'bullish' ? '1px solid rgba(79,221,142,0.35)' : '1px solid rgba(255,107,107,0.35)',
          }
        }, htfRaw.structure === 'bullish' ? 'LONG' : 'SHORT'),
      React.createElement('span', {
        style: { fontSize: 11, fontWeight: 700, color: stateColor,
                 background: 'rgba(0,0,0,0.25)', padding: '2px 8px',
                 borderRadius: 4, marginLeft: 4 }
      }, stateLabel),
      choch.fired && React.createElement('span', {
        style: { fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 3,
                 background: 'rgba(79,221,142,0.15)', color: '#4fdd8e',
                 border: '1px solid rgba(79,221,142,0.3)' }
      }, '✓ CHoCH')
    ),

    // HTF Structure
    sectionHead(`HTF · ${def.htfLabel}`, null, 'lg'),
    row('Trend', htfRaw.structure || '—',
        htfRaw.structure === 'bullish' ? '#4fdd8e' :
        htfRaw.structure === 'bearish' ? '#ff6b6b' : 'var(--text3)'),

    // Dealing Range
    dr && sectionHead('Dealing Range'),
    dr && row('DR High', fmt(dr.high), '#ff6bff'),
    dr && row('EQ', fmt(dr.eq), 'var(--text2)'),
    dr && row('DR Low', fmt(dr.low), '#4fdd8e'),
    dr && row('Zone', dr.zone || '—',
              dr.zone === 'discount' ? '#4fdd8e' : '#ffb52e'),

    // OTE Band
    (pair.ote_low != null || pair.ote_high != null) && sectionHead('OTE Band (61.8–78.6)'),
    pair.ote_high != null && row('OTE Top (61.8)', fmt(pair.ote_high), '#f0a500'),
    pair.ote_low  != null && row('OTE Bot (78.6)', fmt(pair.ote_low),  '#f0a500'),

    // POI
    poiData && sectionHead(
      `POI · ${(poiSource || '').toUpperCase()}${poiData.tier === 'strict' ? ' · Strict' : ''}`
    ),
    poiData && row('Top',    fmt(poiData.top),    '#ffb52e'),
    poiData && row('Bottom', fmt(poiData.bottom), '#ffb52e'),
    poiData && poiData.tier_reason && row('Tier', poiData.tier_reason, 'var(--text3)'),

    // LTF CHoCH — strong visual break from the HTF block above
    React.createElement('div', {
      style: { borderTop: '2px solid var(--line)', marginTop: 14, marginBottom: 2 }
    }),
    sectionHead(`LTF · ${def.ltfLabel}`, null, 'lg'),
    row('CHoCH',
        choch.fired
          ? `Fired @ ${fmt(choch.level)}`
          : (choch.level ? `Watching ${fmt(choch.level)}` : 'Not detected'),
        choch.fired ? '#4fdd8e' : 'var(--text4)'
    ),

    // Signal text
    pair.signal_text && React.createElement('div', {
      style: { marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--line)',
               fontSize: 11, color: 'var(--text3)', fontStyle: 'italic' }
    }, pair.signal_text)
  );
}
// Keep AnalysisPanel as alias so any remaining references render correctly
const AnalysisPanel = SetupPanel;

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

              // OTE zone — shaded band between 61.8 and 78.6 fib levels
              if (ind.ote_low != null && ind.ote_high != null) {
                const oteTop = Math.max(ind.ote_low, ind.ote_high);
                const oteBot = Math.min(ind.ote_low, ind.ote_high);
                drawBoundedLine(oteTop, 'rgba(240,165,0,0.55)', 1, 1);
                drawBoundedLine(oteBot, 'rgba(240,165,0,0.55)', 1, 1);
                series.createPriceLine({ price: oteTop, color: 'rgba(240,165,0,0.55)',
                  title: '61.8', lineWidth: 0, lineStyle: 1,
                  axisLabelVisible: true, lastValueVisible: false });
                series.createPriceLine({ price: oteBot, color: 'rgba(240,165,0,0.55)',
                  title: '78.6', lineWidth: 0, lineStyle: 1,
                  axisLabelVisible: true, lastValueVisible: false });
              }

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
  const [watchlist, setWatchlist] = useTdS([]);
  const [signals, setSignals] = useTdS([]);   // array of grouped {symbol, pairs:{swing,intra,scalp}}
  const [hlVolumes, setHlVolumes] = useTdS({});
  const [running, setRunning] = useTdS(false);
  const [error, setError] = useTdS(null);
  const [checkedKeys, setCheckedKeys] = useTdS(new Set());
  const [expandedSym, setExpandedSym] = useTdS(null);
  const [filterType, setFilterType] = useTdS('all');
  const [filterTicker, setFilterTicker] = useTdS('');
  const [tickerInput, setTickerInput] = useTdS('');
  const [addError, setAddError] = useTdS('');
  const [sortCol, setSortCol] = useTdS('symbol');
  const [sortDir, setSortDir] = useTdS('asc');
  const [scannerStrategies, setScannerStrategies] = useTdS([]);
  const [selectedScanStrategies, setSelectedScanStrategies] = useTdS([]);
  const [activeStatusFilters, setActiveStatusFilters] = useTdS(new Set());

  // Import panel state
  const [showImport, setShowImport] = useTdS(false);
  const [importN, setImportN] = useTdS(20);
  const [importNRaw, setImportNRaw] = useTdS('20');
  const [importMinVolRaw, setImportMinVolRaw] = useTdS('');
  const [importTypeFilter, setImportTypeFilter] = useTdS('all');
  const [importBusy, setImportBusy] = useTdS(false);
  const [importPreview, setImportPreview] = useTdS(null);
  const [importSelected, setImportSelected] = useTdS(new Set());
  const [importMsg, setImportMsg] = useTdS('');

  function load() {
    Promise.all([
      api('/api/trading/scanner/watchlist'),
      api('/api/trading/scanner/signals'),
    ]).then(([wlData, sigData]) => {
      setWatchlist(wlData.watchlist || []);
      setSignals(sigData.signals || []);
    }).catch(e => setError(e.message));
    api('/api/trading/scanner/hl-volumes')
      .then(r => setHlVolumes(r.volumes || {}))
      .catch(() => {});
  }

  useTdE(() => {
    api('/api/trading/strategies').then(data => setScannerStrategies(data || [])).catch(() => {});
    load();
  }, []);

  // Build display rows — merge watchlist + signals grouped data
  const allRows = useTdMemo(() => {
    const sigMap = {};
    signals.forEach(s => { sigMap[s.symbol] = s; });
    // Start from watchlist
    const wlSyms = new Set(watchlist.map(w => w.symbol));
    const rows = watchlist.map(w => ({
      symbol: w.symbol,
      wl: w,
      sig: sigMap[w.symbol] || null,
    }));
    // Add orphan signals not in watchlist
    signals.forEach(s => {
      if (!wlSyms.has(s.symbol)) {
        rows.push({ symbol: s.symbol, wl: null, sig: s });
      }
    });
    return rows;
  }, [watchlist, signals]);

  // Status counts for chips
  const statusCounts = useTdMemo(() => {
    const counts = {};
    allRows.forEach(row => {
      const pairs = row.sig ? row.sig.pairs : {};
      // Use best status across pairs
      const statuses = Object.values(pairs).map(p => p.status || 'quiet');
      const priority = ['active', 'forming', 'watching', 'quiet', 'error'];
      const best = priority.find(s => statuses.includes(s)) || 'quiet';
      counts[best] = (counts[best] || 0) + 1;
    });
    return counts;
  }, [allRows]);

  // Filter + sort
  const displayRows = useTdMemo(() => {
    let rows = allRows;
    if (filterTicker.trim()) {
      const q = filterTicker.trim().toLowerCase();
      rows = rows.filter(r => fmtSymbol(r.symbol).toLowerCase().includes(q));
    }
    if (filterType !== 'all') {
      rows = rows.filter(r => {
        const entry = hlVolumes[(r.symbol || '').toUpperCase()];
        const t = entry ? entry.asset_type : 'crypto';
        return t === filterType;
      });
    }
    if (activeStatusFilters.size > 0) {
      rows = rows.filter(r => {
        const pairs = r.sig ? r.sig.pairs : {};
        const statuses = Object.values(pairs).map(p => p.status || 'quiet');
        const priority = ['active', 'forming', 'watching', 'quiet', 'error'];
        const best = priority.find(s => statuses.includes(s)) || 'quiet';
        return activeStatusFilters.has(best);
      });
    }
    return rows;
  }, [allRows, filterTicker, filterType, activeStatusFilters, hlVolumes]);

  async function addTicker() {
    const sym = tickerInput.trim().toUpperCase();
    if (!sym) return;
    setAddError('');
    try {
      await api('/api/trading/scanner/watchlist', {
        method: 'POST',
        body: JSON.stringify({ symbol: sym, htf_timeframe: '1d', ltf_timeframe: '4h' }),
      });
      setTickerInput('');
      await load();
    } catch (e) { setAddError(e.message); }
  }

  async function removeTicker(sym) {
    const item = watchlist.find(w => w.symbol === sym);
    if (!item) return;
    if (!confirm(`Remove ${fmtSymbol(sym)} from watchlist?`)) return;
    await api(`/api/trading/scanner/watchlist/${item.id}`, { method: 'DELETE' });
    load();
  }

  async function removeAll() {
    if (!confirm('Remove all tickers from watchlist? This cannot be undone.')) return;
    await api('/api/trading/scanner/watchlist/all', { method: 'DELETE' });
    load();
  }

  async function runScanSelected() {
    const combos = [...checkedKeys].map(sym => ({ symbol: sym }));
    if (!combos.length) return;
    setRunning(true); setError(null);
    try {
      const body = { combos };
      if (selectedScanStrategies.length > 0) body.strategy_ids = selectedScanStrategies;
      await api('/api/trading/scanner/run', { method: 'POST', body: JSON.stringify(body) });
      await load();
    } catch (e) { setError(e.message); }
    finally { setRunning(false); }
  }

  async function runScanAll() {
    setRunning(true); setError(null);
    try {
      const body = selectedScanStrategies.length > 0 ? { strategy_ids: selectedScanStrategies } : {};
      await api('/api/trading/scanner/run', { method: 'POST', body: JSON.stringify(body) });
      await load();
    } catch (e) { setError(e.message); }
    finally { setRunning(false); }
  }

  // Import helpers — preserve all existing import logic
  function parseVolShorthand(s) {
    if (!s) return 0;
    const m = String(s).trim().toUpperCase().match(/^([\d.]+)\s*([KMB]?)$/);
    if (!m) return 0;
    const n = parseFloat(m[1]);
    const mult = { K: 1e3, M: 1e6, B: 1e9 }[m[2]] || 1;
    return n * mult;
  }
  function fmtVolFull(n) {
    if (!n) return '';
    return '= $' + n.toLocaleString('en-US', { maximumFractionDigits: 0 });
  }
  const _costRate = () => parseFloat(localStorage.getItem('scanner_cost_per_symbol') || '0.012') || 0.012;
  function fmtCost(n) {
    const cost = n * _costRate() * 3; // 3 pairs per symbol
    return cost < 0.01 ? '<$0.01' : `~$${cost.toFixed(2)}`;
  }

  async function hlPreview() {
    setImportBusy(true); setImportPreview(null); setImportMsg('');
    try {
      const minVol = parseVolShorthand(importMinVolRaw);
      const typeParam = importTypeFilter !== 'all' ? `&asset_type=${importTypeFilter}` : '';
      const data = await api(`/api/trading/scanner/hl-top-volume?n=${importN}${minVol > 0 ? `&min_volume=${minVol}` : ''}${typeParam}`);
      const assets = data.assets || [];
      setImportPreview(assets);
      setImportSelected(new Set(assets.filter(a => !a.in_watchlist).map(a => a.symbol)));
    } catch (e) { setImportMsg(`Error: ${e.message}`); }
    finally { setImportBusy(false); }
  }

  async function hlImport() {
    setImportBusy(true); setImportMsg('');
    try {
      const minVol = parseVolShorthand(importMinVolRaw);
      const res = await api('/api/trading/scanner/hl-import', {
        method: 'POST',
        body: JSON.stringify({
          n: importN,
          ...(minVol > 0 ? { min_volume: minVol } : {}),
          ...(importTypeFilter !== 'all' ? { asset_type: importTypeFilter } : {}),
          symbols: importSelected.size > 0 ? [...importSelected] : undefined,
        }),
      });
      setImportMsg(`Imported ${res.added} new, skipped ${res.skipped} existing, removed ${res.removed} quiet`);
      await load();
      setTimeout(() => { setShowImport(false); setImportMsg(''); setImportPreview(null); }, 2000);
    } catch (e) { setImportMsg(`Error: ${e.message}`); }
    finally { setImportBusy(false); }
  }

  const allKeys = displayRows.map(r => r.symbol);
  const allChecked = allKeys.length > 0 && allKeys.every(k => checkedKeys.has(k));

  // ── RENDER ──

  // Status chips
  const STATUS_CONFIG_LOCAL = {
    active:   { color: '#4fdd8e', label: 'Active'   },
    forming:  { color: '#ffb52e', label: 'Forming'  },
    watching: { color: '#f0c040', label: 'Watching' },
    quiet:    { color: 'var(--text4)', label: 'Quiet' },
  };
  const CHIP_ORDER = ['active', 'forming', 'watching', 'quiet'];

  const statusChips = React.createElement('div', {
    style: { display: 'flex', gap: 6, padding: '8px 14px', borderBottom: '1px solid var(--line-soft)', flexWrap: 'wrap' }
  },
    CHIP_ORDER.filter(st => statusCounts[st] > 0).map(st => {
      const cfg = STATUS_CONFIG_LOCAL[st] || {};
      const isActive = activeStatusFilters.has(st);
      return React.createElement('span', {
        key: st,
        onClick: () => setActiveStatusFilters(prev => {
          const next = new Set(prev);
          next.has(st) ? next.delete(st) : next.add(st);
          return next;
        }),
        style: {
          fontSize: 11, cursor: 'pointer', padding: '3px 10px', borderRadius: 12,
          background: isActive ? (cfg.color || 'var(--accent)') : 'var(--panel3)',
          color: isActive ? '#000' : 'var(--text3)',
          border: isActive ? 'none' : `1px solid ${cfg.color || 'var(--line)'}`,
          fontWeight: 500,
        }
      }, `${statusCounts[st]} ${cfg.label || st}`);
    })
  );

  // Top bar
  const topBar = React.createElement('div', {
    style: { display: 'flex', gap: 8, padding: '10px 14px', borderBottom: '1px solid var(--line-soft)',
             alignItems: 'center', flexWrap: 'wrap' }
  },
    // Ticker input
    React.createElement('input', {
      className: 'tv-input',
      placeholder: 'Add ticker…',
      value: tickerInput,
      style: { width: 120, fontSize: 12, textTransform: 'uppercase' },
      onChange: e => setTickerInput(e.target.value.toUpperCase()),
      onKeyDown: e => e.key === 'Enter' && addTicker(),
    }),
    React.createElement('button', { className: 'tv-btn', style: { fontSize: 12 }, onClick: addTicker }, '+ Add'),
    addError && React.createElement('span', { style: { fontSize: 11, color: 'var(--fail)' } }, addError),
    React.createElement('div', { style: { flex: 1 } }),
    // Scan Selected
    React.createElement('button', {
      className: 'tv-btn primary', style: { fontSize: 12 },
      disabled: running || checkedKeys.size === 0,
      onClick: runScanSelected,
      title: checkedKeys.size === 0 ? 'Select symbols to scan' : `${fmtCost(checkedKeys.size)} (${checkedKeys.size} symbols × 3 pairs)`,
    }, running ? 'Scanning…' : '▶ Scan Selected'),
    React.createElement('button', {
      className: 'tv-btn', style: { fontSize: 12 },
      disabled: running,
      onClick: runScanAll,
      title: `${fmtCost(watchlist.length)} (${watchlist.length} symbols × 3 pairs)`,
    }, running ? 'Scanning…' : 'Scan All'),
    React.createElement('button', {
      className: 'tv-btn', style: { fontSize: 12 },
      onClick: () => { setShowImport(v => !v); setImportPreview(null); setImportMsg(''); },
    }, '↓ Import HL'),
    React.createElement('button', {
      className: 'tv-btn', style: { fontSize: 12, color: 'var(--fail)', borderColor: 'var(--fail)' },
      onClick: removeAll,
    }, 'Remove All')
  );

  // Type filter + cost bar
  const typeFilterBar = React.createElement('div', {
    style: { display: 'flex', gap: 8, padding: '6px 14px', borderBottom: '1px solid var(--line-soft)',
             alignItems: 'center' }
  },
    React.createElement('input', {
      className: 'tv-input', placeholder: 'Filter ticker…', value: filterTicker,
      style: { fontSize: 11, padding: '2px 8px', width: 110 },
      onChange: e => setFilterTicker(e.target.value),
    }),
    React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)', marginLeft: 4 } }, 'Type:'),
    ['all', 'crypto', 'tradfi'].map(t =>
      React.createElement('span', {
        key: t, onClick: () => setFilterType(t),
        style: {
          fontSize: 11, cursor: 'pointer', padding: '2px 8px', borderRadius: 10,
          background: filterType === t ? 'var(--accent)' : 'var(--panel3)',
          color: filterType === t ? '#000' : 'var(--text3)',
          border: filterType === t ? 'none' : '1px solid var(--line)',
          textTransform: 'capitalize',
        }
      }, t)
    ),
    React.createElement('div', { style: { flex: 1 } }),
    React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)' } },
      checkedKeys.size > 0
        ? `Scan Selected: ${checkedKeys.size} symbols × 5 HTFs`
        : `Scan All: ${watchlist.length} symbols × 5 HTFs`
    )
  );

  // Import panel
  const importPanel = showImport && React.createElement('div', {
    style: { padding: '10px 14px', borderBottom: '1px solid var(--line-soft)',
             background: 'var(--panel2)', display: 'flex', flexDirection: 'column', gap: 8 }
  },
    React.createElement('div', { style: { display: 'flex', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' } },
      React.createElement('div', null,
        React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginBottom: 4 } }, 'Top N by volume'),
        React.createElement('input', {
          className: 'tv-input', type: 'text', inputMode: 'numeric', pattern: '[0-9]*',
          value: importNRaw, style: { width: 60, fontSize: 12 },
          onChange: e => {
            const raw = e.target.value.replace(/[^0-9]/g, '');
            setImportNRaw(raw);
            const n = parseInt(raw);
            if (n >= 1 && n <= 200) setImportN(n);
          },
          onBlur: () => {
            const n = parseInt(importNRaw);
            const clamped = (!n || n < 1) ? 1 : n > 200 ? 200 : n;
            setImportN(clamped); setImportNRaw(String(clamped));
          },
        })
      ),
      React.createElement('div', null,
        React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 4 } },
          React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)' } }, 'Min 24h Vol'),
          (() => { const v = parseVolShorthand(importMinVolRaw); return v > 0 ? React.createElement('span', { style: { fontSize: 10, color: 'var(--text4)', opacity: 0.7 } }, fmtVolFull(v)) : null; })()
        ),
        React.createElement('input', {
          className: 'tv-input', placeholder: 'e.g. 10M', value: importMinVolRaw,
          style: { width: 90, fontSize: 12 },
          onChange: e => setImportMinVolRaw(e.target.value),
        })
      ),
      React.createElement('div', { style: { display: 'flex', gap: 6, alignItems: 'flex-end', paddingBottom: 0 } },
        React.createElement('button', { className: 'tv-btn', style: { fontSize: 12 }, disabled: importBusy, onClick: hlPreview }, importBusy ? '…' : 'Preview'),
        React.createElement('button', { className: 'tv-btn primary', style: { fontSize: 12 }, disabled: importBusy, onClick: hlImport }, importBusy ? 'Importing…' : 'Import'),
        React.createElement('button', { className: 'tv-btn', style: { fontSize: 12 }, onClick: () => { setShowImport(false); setImportMsg(''); setImportPreview(null); } }, 'Cancel')
      )
    ),
    React.createElement('div', { style: { display: 'flex', gap: 6, alignItems: 'center' } },
      React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)' } }, 'Type:'),
      ['all', 'crypto', 'tradfi'].map(t =>
        React.createElement('span', {
          key: t, onClick: () => setImportTypeFilter(t),
          style: {
            fontSize: 11, cursor: 'pointer', padding: '2px 8px', borderRadius: 10,
            background: importTypeFilter === t ? 'var(--accent)' : 'var(--panel3)',
            color: importTypeFilter === t ? '#000' : 'var(--text3)',
            border: importTypeFilter === t ? 'none' : '1px solid var(--line)',
            textTransform: 'capitalize',
          }
        }, t)
      )
    ),
    importMsg && React.createElement('div', { style: { fontSize: 12, color: importMsg.startsWith('Error') ? 'var(--fail)' : 'var(--ok)' } }, importMsg),
    importPreview && React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 300, overflowY: 'auto' } },
      React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 } },
        React.createElement('input', {
          type: 'checkbox',
          checked: importPreview.filter(a => !a.in_watchlist).every(a => importSelected.has(a.symbol)),
          onChange: e => setImportSelected(e.target.checked ? new Set(importPreview.filter(a => !a.in_watchlist).map(a => a.symbol)) : new Set())
        }),
        React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)' } },
          `${importSelected.size} selected · ${importPreview.filter(a => !a.in_watchlist).length} new, ${importPreview.filter(a => a.in_watchlist).length} in watchlist`
        )
      ),
      importPreview.map((a, i) =>
        React.createElement('div', { key: a.symbol, style: { display: 'flex', gap: 8, fontSize: 11, alignItems: 'center', opacity: a.in_watchlist ? 0.5 : 1 } },
          React.createElement('input', {
            type: 'checkbox', disabled: a.in_watchlist,
            checked: importSelected.has(a.symbol),
            onChange: e => setImportSelected(prev => { const next = new Set(prev); e.target.checked ? next.add(a.symbol) : next.delete(a.symbol); return next; })
          }),
          React.createElement('span', { style: { color: 'var(--text4)', width: 16, textAlign: 'right' } }, i + 1),
          React.createElement('span', { style: { fontWeight: 600, width: 80 } }, fmtSymbol(a.symbol)),
          React.createElement('span', { style: { color: 'var(--text4)', width: 60 } }, a.volume_display),
          a.asset_type && React.createElement('span', { style: {
            fontSize: 10, padding: '1px 5px', borderRadius: 4,
            background: a.asset_type === 'tradfi' ? 'rgba(99,179,237,0.15)' : 'rgba(72,187,120,0.15)',
            color: a.asset_type === 'tradfi' ? '#63b3ed' : '#48bb78',
          } }, a.asset_type === 'tradfi' ? 'TradFi' : 'Crypto'),
          a.in_watchlist && React.createElement('span', { style: { fontSize: 10, color: 'var(--text4)', padding: '1px 5px', borderRadius: 4, background: 'var(--panel3)', border: '1px solid var(--line)' } }, 'in watchlist')
        )
      )
    )
  );

  // Table header
  const colTemplate = '22px 80px 100px 72px 68px 1fr 1fr 1fr 1fr 1fr 120px 110px 26px';
  const thStyle = { fontSize: 12, color: 'var(--text3)', fontWeight: 700, letterSpacing: '0.08em',
                    textTransform: 'uppercase', padding: '8px 6px', userSelect: 'none' };

  const tableHeader = React.createElement('div', {
    style: { display: 'grid', gridTemplateColumns: colTemplate, gap: '0 10px',
             padding: '0 14px', borderBottom: '1px solid var(--line)',
             position: 'sticky', top: 0, background: 'var(--panel)', zIndex: 2 }
  },
    React.createElement('div', { style: thStyle },
      React.createElement('input', {
        type: 'checkbox',
        checked: allChecked && allKeys.length > 0,
        onChange: e => setCheckedKeys(e.target.checked ? new Set(allKeys) : new Set()),
      })
    ),
    React.createElement('div', { style: thStyle }, 'TICKER'),
    React.createElement('div', { style: thStyle }, 'STATUS'),
    React.createElement('div', { style: thStyle }, '24H VOL'),
    React.createElement('div', { style: thStyle }, 'TYPE'),
    // HTF column headers (v3 — 5 timeframes)
    ...HTF_DEFS.map(def =>
      React.createElement('div', { key: def.key, style: { ...thStyle, display: 'flex', alignItems: 'center', gap: 4 } },
        React.createElement(TfPill, { label: def.htfLabel }),
        React.createElement('span', { style: { color: 'var(--text4)', fontSize: 9 } }, '→'),
        React.createElement(TfPill, { label: def.ltfLabel }),
      )
    ),
    React.createElement('div', { style: thStyle }, 'PRICE'),
    React.createElement('div', { style: thStyle }, 'LAST SCAN'),
    React.createElement('div', { style: thStyle }),
  );

  // Table rows
  const tableRows = displayRows.map(row => {
    const sym = row.symbol;
    const wl = row.wl;
    const sig = row.sig;
    const pairs = sig ? sig.pairs : {};
    const isExpanded = expandedSym === sym;
    const isChecked = checkedKeys.has(sym);

    const volEntry = hlVolumes[sym.toUpperCase()];
    const vol24h = volEntry ? volEntry.volume_24h : null;
    const assetType = volEntry ? volEntry.asset_type : null;
    function fmtVol(v) {
      if (!v) return '—';
      if (v >= 1e9) return '$' + (v/1e9).toFixed(1) + 'B';
      if (v >= 1e6) return '$' + (v/1e6).toFixed(0) + 'M';
      if (v >= 1e3) return '$' + (v/1e3).toFixed(0) + 'K';
      return '$' + v.toFixed(0);
    }

    // Best price across pairs
    const price = sig ? sig.current_price : null;
    const scannedAt = sig ? sig.scanned_at : null;

    // Best status
    const allStatuses = Object.values(pairs).map(p => p.status || 'quiet');
    const priority = ['active', 'forming', 'watching', 'quiet', 'error'];
    const bestStatus = priority.find(s => allStatuses.includes(s)) || (wl ? 'quiet' : null);
    const STATUS_COLORS = { active: '#4fdd8e', forming: '#ffb52e', watching: '#f0c040', quiet: 'var(--text4)' };

    const rowEl = React.createElement('div', {
      key: sym,
      onClick: () => setExpandedSym(prev => prev === sym ? null : sym),
      style: {
        display: 'grid', gridTemplateColumns: colTemplate, gap: '0 10px',
        padding: '8px 14px', borderBottom: '1px solid var(--line-soft)',
        cursor: 'pointer', alignItems: 'center',
        background: isExpanded ? 'var(--panel2)' : 'transparent',
        borderLeft: isExpanded ? '2.5px solid #ffb52e' : '2.5px solid transparent',
      }
    },
      // Checkbox
      React.createElement('div', { onClick: e => e.stopPropagation() },
        React.createElement('input', {
          type: 'checkbox', checked: isChecked,
          onChange: e => setCheckedKeys(prev => {
            const next = new Set(prev);
            e.target.checked ? next.add(sym) : next.delete(sym);
            return next;
          })
        })
      ),
      // Ticker
      React.createElement('div', { style: { fontWeight: 700, fontSize: 14, color: 'var(--text1)' } },
        fmtSymbol(sym)
      ),
      // Status
      React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 5 } },
        React.createElement('span', { style: { width: 7, height: 7, borderRadius: '50%', background: STATUS_COLORS[bestStatus] || 'var(--text4)', flexShrink: 0 } }),
        React.createElement('span', { style: { fontSize: 12, color: STATUS_COLORS[bestStatus] || 'var(--text4)' } },
          bestStatus || '—'
        )
      ),
      // 24H Vol
      React.createElement('div', { style: { fontSize: 12, color: 'var(--text3)' } }, fmtVol(vol24h)),
      // Type badge
      React.createElement('div', null,
        assetType && React.createElement('span', { style: {
          fontSize: 10, padding: '2px 7px', borderRadius: 10, fontWeight: 600,
          letterSpacing: '0.05em', textTransform: 'uppercase',
          background: assetType === 'tradfi' ? 'rgba(99,179,237,0.15)' : 'rgba(72,187,120,0.15)',
          color: assetType === 'tradfi' ? '#63b3ed' : '#48bb78',
          border: assetType === 'tradfi' ? '1px solid rgba(99,179,237,0.3)' : '1px solid rgba(72,187,120,0.3)',
        } }, assetType === 'tradfi' ? 'TradFi' : 'Crypto')
      ),
      // Five HTF cells (v3)
      ...HTF_DEFS.map(def =>
        React.createElement('div', { key: def.key },
          React.createElement(PairCell, { pair: pairs[def.key] || null, def })
        )
      ),
      // Price
      React.createElement('div', { style: { fontSize: 12, color: 'var(--text2)', fontVariantNumeric: 'tabular-nums' } },
        price ? `$${Number(price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}` : '—'
      ),
      // Last scan
      React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)' } },
        scannedAt ? (() => {
          const d = new Date(scannedAt.replace(' ', 'T') + 'Z');
          return isNaN(d) ? scannedAt : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ', ' + d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
        })() : '—'
      ),
      // Remove
      React.createElement('div', {
        onClick: e => { e.stopPropagation(); wl && removeTicker(sym); },
        style: { cursor: wl ? 'pointer' : 'default', color: wl ? 'var(--fail)' : 'transparent',
                 textAlign: 'center', fontSize: 14, fontWeight: 700 }
      }, wl ? '×' : '')
    );

    // Expanded analysis panels
    const expandedEl = isExpanded && React.createElement('div', {
      key: sym + '-exp',
      style: {
        display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr 1fr', gap: 14,
        padding: '14px 14px 18px', borderBottom: '1px solid var(--line)',
        borderLeft: '2.5px solid #ffb52e',
        background: 'rgba(0,0,0,0.25)',
      }
    },
      ...HTF_DEFS.map(def =>
        React.createElement(SetupPanel, { key: def.key, pair: pairs[def.key] || null, def })
      )
    );

    return [rowEl, expandedEl].filter(Boolean);
  });

  // Filter active label
  const filterLabel = filterTicker.trim() && React.createElement('div', {
    style: { fontSize: 11, color: 'var(--text4)', textAlign: 'center', padding: '5px 0', fontStyle: 'italic' }
  }, `Filters active — showing ${displayRows.length} of ${allRows.length}`);

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 0 } },
    statusChips,
    topBar,
    typeFilterBar,
    importPanel,
    error && React.createElement('div', { style: { padding: '8px 14px', color: 'var(--fail)', fontSize: 12 } }, `Error: ${error}`),
    React.createElement('div', { className: 'tv-card', style: { padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' } },
      React.createElement('div', { style: { maxHeight: 'calc(100vh - 280px)', overflowY: 'auto', overflowX: 'auto' } },
        tableHeader,
        React.createElement('div', null, ...tableRows.flat()),
        filterLabel
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
