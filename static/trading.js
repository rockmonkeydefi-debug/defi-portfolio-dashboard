/* ===== TRADING TOOLS v2 ===== */

const { useState: useTdS, useEffect: useTdE, useCallback: useTdCb, useMemo: useTdMemo, useRef: useTdRef } = React;

const STATUS_CONFIG = {
  active:   { color: '#4fdd8e', label: 'Setup Ready'  },
  forming:  { color: '#ffb52e', label: 'POI Waiting'  },
  watching: { color: '#f0c040', label: 'Trend Only', chipBg: 'rgba(240,192,64,0.12)', chipBorder: '1px solid rgba(240,192,64,0.35)' },
  quiet:    { color: 'var(--text4)', label: 'No Trend' },
};

// v3 setup-state display model. setup_state is more granular than status
// (status maps PENDING_TAP and POI_TAPPED both to 'forming'). Prefer
// setup_state for labels/colors; fall back to status vocab when absent.
const SETUP_STATE_CONFIG = {
  SETUP_READY: { color: '#4fdd8e', label: 'Setup Ready · Confirmed' },
  POI_TAPPED:  { color: '#ffb52e', label: 'POI Tapped · Pending CHoCH' },
  PENDING_TAP: { color: '#f0a500', label: 'Pending POI Tap' },
  TREND_ONLY:  { color: '#f0c040', label: 'Trend Only' },
  NO_TREND:    { color: 'var(--text4)', label: 'No Trend' },
};
function resolveState(pair) {
  if (!pair) return { color: 'var(--text4)', label: '—' };
  const ss = pair.setup_state;
  if (ss && SETUP_STATE_CONFIG[ss]) return SETUP_STATE_CONFIG[ss];
  const st = pair.status || 'quiet';
  return STATUS_CONFIG[st] || { color: 'var(--text4)', label: st };
}

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

// Format any scan timestamp (ISO string or epoch) in the user's LOCAL timezone
// as "MMM D, h:mm A". An ISO string with a Z suffix is parsed as UTC and
// toLocaleString converts it to local time.
function fmtScanTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
    hour12: true,
  });
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
  const rs = resolveState(pair);
  const color = rs.color;
  const stateLabel = rs.label;

  return React.createElement('div', {
    style: { display: 'flex', alignItems: 'center', gap: 5, padding: '2px 0' }
  },
    React.createElement('span', {
      style: { width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0 }
    }),
    React.createElement('span', { style: { fontSize: 11, color, fontWeight: 600 } }, stateLabel)
  );
}

function SetupPanel({ pair, def }) {
  if (!pair) return React.createElement('div', {
    style: { background: 'var(--panel3)', border: '1px solid var(--line)', borderRadius: 10,
             padding: '14px 16px', color: 'var(--text4)', fontSize: 12,
             boxShadow: '0 2px 8px rgba(0,0,0,0.25)' }
  }, 'No data for this timeframe');

  const rs = resolveState(pair);
  const stateColor = rs.color;
  const stateLabel = rs.label;

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
    style: { fontSize: size === 'lg' ? 13 : 11, fontWeight: 800,
             color: size === 'lg' ? 'var(--text1)' : 'var(--text2)',
             letterSpacing: '0.08em', textTransform: 'uppercase',
             marginTop: size === 'lg' ? 12 : 10, marginBottom: 4 }
  }, label);

  return React.createElement('div', {
    style: { background: 'var(--panel3)', border: '1px solid var(--line)', borderRadius: 10,
             padding: '14px 16px',
             boxShadow: '0 2px 8px rgba(0,0,0,0.25)' }
  },
    // Header line 1 — centered, enlarged timeframe pair
    React.createElement('div', {
      style: { display: 'flex', alignItems: 'center', justifyContent: 'center',
               gap: 8, marginBottom: 8 }
    },
      React.createElement('span', {
        style: { fontSize: 16, fontWeight: 800, color: 'var(--text1)',
                 letterSpacing: '0.04em' }
      }, def.htfLabel),
      React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, '→'),
      React.createElement('span', {
        style: { fontSize: 16, fontWeight: 800, color: 'var(--text1)',
                 letterSpacing: '0.04em' }
      }, def.ltfLabel)
    ),
    // Header line 2 — all badges on one line, centered
    React.createElement('div', {
      style: { display: 'flex', alignItems: 'center', justifyContent: 'center',
               gap: 6, marginBottom: 12, whiteSpace: 'nowrap' }
    },
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
        style: { fontSize: 10, fontWeight: 700, color: stateColor,
                 background: 'rgba(0,0,0,0.25)', padding: '2px 7px',
                 borderRadius: 4, whiteSpace: 'nowrap' }
      }, stateLabel),
      choch.fired && React.createElement('span', {
        style: { fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 3,
                 background: 'rgba(79,221,142,0.15)', color: '#4fdd8e',
                 border: '1px solid rgba(79,221,142,0.3)', whiteSpace: 'nowrap' }
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
    (pair.ote_low != null && pair.ote_high != null && pair.current_price != null) && (() => {
      const px = pair.current_price;
      const lo = Math.min(pair.ote_low, pair.ote_high);
      const hi = Math.max(pair.ote_low, pair.ote_high);
      if (px >= lo && px <= hi) return null;   // in zone → omit (shown elsewhere)
      const nearEdge = px > hi ? hi : lo;
      const pct = Math.abs((px - nearEdge) / nearEdge) * 100;
      return row('Price → OTE', pct.toFixed(1) + '%', 'var(--text2)');
    })(),

    // POI
    poiData && sectionHead(
      `POI · ${(poiSource || '').toUpperCase()}${poiData.tier === 'strict' ? ' · Strict' : ''}`
    ),
    poiData && row('Top',    fmt(poiData.top),    '#ffb52e'),
    poiData && row('Bottom', fmt(poiData.bottom), '#ffb52e'),
    poiData && poiData.tier_reason && row('Tier', poiData.tier_reason, 'var(--text3)'),

    // LTF CHoCH — strong visual break from the HTF block above
    React.createElement('div', {
      style: { borderTop: '3px solid rgba(255,255,255,0.18)', marginTop: 16,
               marginBottom: 4, borderRadius: 2 }
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

/* ===== TRIAGE UI (The Playbook) ===== */

// --- Primitive badges -------------------------------------------------------

const TF_COLORS = {
  '1W':  { bg: '#8b7ad6', fg: '#fff' },
  '1D':  { bg: '#e8853a', fg: '#fff' },
  '12H': { bg: '#2180c8', fg: '#fff' },
  '4H':  { bg: '#2fb4e8', fg: '#0a2a47' },
  '1H':  { bg: '#4fdd8e', fg: '#0a2a47' },
  '15M': { bg: '#3dc87a', fg: '#0a2a47' },
  '5M':  { bg: '#3dc87a', fg: '#0a2a47' },
};

function TFBadge({ tf, sm }) {
  const c = TF_COLORS[tf] || { bg: '#3a4a6a', fg: '#fff' };
  return React.createElement('span', {
    style: {
      background: c.bg, color: c.fg,
      padding: sm ? '1px 5px' : '2px 7px',
      fontSize: sm ? 10 : 11, fontWeight: 700, borderRadius: 3,
    }
  }, tf);
}

function TFPairBadge({ htf, ltf }) {
  return React.createElement('span', { style: { display: 'inline-flex', alignItems: 'center' } },
    React.createElement(TFBadge, { tf: htf }),
    React.createElement('span', { style: { color: '#888', margin: '0 4px' } }, '→'),
    React.createElement(TFBadge, { tf: ltf })
  );
}

function DirBadge({ direction }) {
  const isLong = String(direction || '').toUpperCase() === 'LONG';
  const s = isLong
    ? { background: '#0d2b1a', border: '1px solid #1a6b3a', color: '#4ade80' }
    : { background: '#2b0d0d', border: '1px solid #6b1a1a', color: '#f87171' };
  return React.createElement('span', {
    style: { ...s, fontSize: 11, padding: '2px 8px', borderRadius: 4, fontWeight: 600 }
  }, isLong ? 'LONG' : 'SHORT');
}

function FreshnessPill({ tier }) {
  const map = {
    fresh: { background: '#0d2b1a', color: '#4ade80' },
    aging: { background: '#2b2200', color: '#facc15' },
    stale: { background: '#2b0d0d', color: '#f87171' },
  };
  const s = map[tier] || map.stale;
  return React.createElement('span', {
    style: { ...s, fontSize: 11, padding: '2px 8px', borderRadius: 10 }
  }, tier);
}

// --- Risk / Position-Size modal ---------------------------------------------

function RiskModal({ setup, onClose }) {
  const entryLow = parseFloat(setup.entryLow);
  const entryHigh = parseFloat(setup.entryHigh);
  const entryMid = (entryLow + entryHigh) / 2;

  const [accountSize, setAccountSize] = useTdS('');
  const [entry, setEntry] = useTdS(isNaN(entryMid) ? '' : entryMid.toFixed(2));
  const [riskPct, setRiskPct] = useTdS('0.5');

  const targets = setup.targets || [];
  const t1Price = targets[0] ? parseFloat(targets[0].price) : null;
  const t2Price = targets[1] ? parseFloat(targets[1].price) : null;

  const entryVal = parseFloat(entry);
  const stopVal = parseFloat(setup.stop);
  const accountVal = parseFloat(accountSize);
  const riskPctVal = parseFloat(riskPct);

  const riskUSD = accountVal * (riskPctVal / 100);
  const riskPerUnit = Math.abs(entryVal - stopVal);
  const units = riskPerUnit > 0 ? riskUSD / riskPerUnit : NaN;
  const positionUSD = units * entryVal;
  const rrT1 = (t1Price !== null && riskPerUnit > 0) ? Math.abs(t1Price - entryVal) / riskPerUnit : null;
  const rrT2 = (t2Price !== null && riskPerUnit > 0) ? Math.abs(t2Price - entryVal) / riskPerUnit : null;

  const fmt = (v, dp) => (v === null || v === undefined || isNaN(v)) ? '—' : Number(v).toFixed(dp);

  const inputLabelStyle = {
    color: '#888', fontSize: 11, fontWeight: 600,
    textTransform: 'uppercase', letterSpacing: '0.5px',
  };
  const inputStyle = {
    width: '100%', background: '#1a1a2e', border: '1px solid #333', color: '#fff',
    padding: '8px 10px', borderRadius: 6, fontSize: 14, boxSizing: 'border-box',
    marginTop: 4, marginBottom: 12,
  };

  const inputRow = (label, value, onChange, opts) => React.createElement('div', null,
    React.createElement('div', { style: inputLabelStyle }, label),
    React.createElement('input', {
      type: 'number',
      value,
      onChange: onChange ? (e => onChange(e.target.value)) : undefined,
      readOnly: opts && opts.readOnly,
      disabled: opts && opts.readOnly,
      placeholder: opts && opts.placeholder,
      step: opts && opts.step,
      style: (opts && opts.readOnly)
        ? { ...inputStyle, background: '#111', color: '#888' }
        : inputStyle,
    })
  );

  const outputCell = (label, value) => React.createElement('div', null,
    React.createElement('div', {
      style: { color: '#888', fontSize: 10, fontWeight: 600, textTransform: 'uppercase' }
    }, label),
    React.createElement('div', {
      style: { color: '#fff', fontSize: 18, fontWeight: 700, marginTop: 2 }
    }, value)
  );

  return React.createElement('div', {
    style: {
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    },
    onClick: onClose,
  },
    React.createElement('div', {
      onClick: e => e.stopPropagation(),
      style: {
        background: '#0f0f1a', border: '1px solid #333', borderRadius: 10,
        padding: 24, width: 420, maxWidth: '90vw', position: 'relative',
      }
    },
      // header
      React.createElement('button', {
        onClick: onClose,
        style: {
          position: 'absolute', top: 16, right: 16, background: 'none', border: 'none',
          color: '#888', fontSize: 18, cursor: 'pointer',
        }
      }, '✕'),
      React.createElement('div', {
        style: { color: '#fff', fontSize: 16, fontWeight: 700 }
      }, `${setup.ticker} · ${setup.htf}→${setup.ltf}`),
      React.createElement('div', {
        style: { display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }
      },
        React.createElement(DirBadge, { direction: setup.direction }),
        React.createElement('span', { style: { color: '#888', fontSize: 12 } }, 'Position Sizing')
      ),
      // inputs
      React.createElement('div', { style: { marginTop: 16 } },
        inputRow('Account Size (USD)', accountSize, setAccountSize, { placeholder: 'e.g. 10000' }),
        inputRow('Entry', entry, setEntry, { placeholder: isNaN(entryMid) ? '' : entryMid.toFixed(2) }),
        inputRow('Stop', fmt(stopVal, 2), null, { readOnly: true }),
        inputRow('Risk %', riskPct, setRiskPct, { placeholder: '0.5', step: '0.1' })
      ),
      // outputs
      React.createElement('div', {
        style: {
          marginTop: 16, background: '#080810', borderRadius: 8, padding: 16,
          display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12,
        }
      },
        outputCell('Risk $', fmt(riskUSD, 2)),
        outputCell('Position $', fmt(positionUSD, 2)),
        outputCell('Units', fmt(units, 4)),
        outputCell('R:R to T1', rrT1 !== null && !isNaN(rrT1) ? `${rrT1.toFixed(2)}R` : '—'),
        outputCell('R:R to T2', rrT2 !== null && !isNaN(rrT2) ? `${rrT2.toFixed(2)}R` : '—'),
        outputCell('Stop Dist', fmt(riskPerUnit, 2))
      ),
      // footer
      React.createElement('div', {
        style: { marginTop: 20, display: 'flex', gap: 10 }
      },
        React.createElement('button', {
          onClick: onClose,
          style: {
            background: '#1a3a1a', border: '1px solid #2a6a2a', color: '#4ade80',
            padding: '10px 16px', borderRadius: 6, fontSize: 13, flex: 1, cursor: 'pointer',
          }
        }, 'Log this trade'),
        React.createElement('button', {
          onClick: onClose,
          style: {
            background: '#1a1a2e', border: '1px solid #333', color: '#888',
            padding: '10px 16px', borderRadius: 6, fontSize: 13, cursor: 'pointer',
          }
        }, 'Close')
      )
    )
  );
}

// --- ACT TODAY card ---------------------------------------------------------

function ActTodayCard({ setup, rank, onSwitchTab }) {
  const [showRiskModal, setShowRiskModal] = useTdS(false);
  const targets = setup.targets || [];
  const t1 = targets[0];
  const t2 = targets[1];
  const isLong = String(setup.direction || '').toUpperCase() === 'LONG';

  // Adaptive price formatter: thousands separators, magnitude-based decimals.
  const fmtPx = (v) => {
    if (v === null || v === undefined || isNaN(v)) return '—';
    const n = Number(v);
    const abs = Math.abs(n);
    const dp = abs >= 1000 ? 0 : abs >= 1 ? 2 : 4;
    return n.toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp });
  };

  // --- ladder geometry --------------------------------------------------
  const stop = parseFloat(setup.stop);
  const entryLow = parseFloat(setup.entryLow);
  const entryHigh = parseFloat(setup.entryHigh);
  const t1p = t1 ? parseFloat(t1.price) : null;
  const t2p = t2 ? parseFloat(t2.price) : null;

  const prices = [stop, entryLow, entryHigh, t1p, t2p]
    .filter(v => v !== null && v !== undefined && !isNaN(v));
  const high = prices.length ? Math.max(...prices) : 1;
  const low = prices.length ? Math.min(...prices) : 0;
  const span = (high - low) || 1;
  const pct = (price) => (high - price) / span * 100; // high=0% (top), low=100% (bottom)

  const stopPct = pct(stop);
  const entryLoPct = pct(entryLow);
  const entryHiPct = pct(entryHigh);
  const t1Pct = t1p !== null ? pct(t1p) : null;
  const t2Pct = t2p !== null ? pct(t2p) : null;
  const entryMidPct = (entryHiPct + entryLoPct) / 2;

  const GREEN = 'rgba(79,221,142,0.26)';
  const RED = 'rgba(255,138,138,0.26)';
  const topZoneColor = isLong ? GREEN : RED;     // LONG: targets on top · SHORT: stop on top
  const bottomZoneColor = isLong ? RED : GREEN;
  const topTickColor = isLong ? '#4fdd8e' : '#ff8a8a';
  const bottomTickColor = isLong ? '#ff8a8a' : '#4fdd8e';

  const ladderValid = prices.length >= 2 &&
    !isNaN(entryLoPct) && !isNaN(entryHiPct) && !isNaN(stopPct);

  const rail = React.createElement('div', {
    style: {
      position: 'relative', width: 8, flexShrink: 0, borderRadius: 4,
      background: 'rgba(255,255,255,0.07)',
    }
  },
    // top zone (down to entry top)
    React.createElement('div', {
      style: {
        position: 'absolute', left: 0, right: 0, top: 0,
        height: `${entryHiPct}%`, background: topZoneColor, borderRadius: '4px 4px 0 0',
      }
    }),
    // entry zone band (slightly wider)
    React.createElement('div', {
      style: {
        position: 'absolute', left: -3, right: -3, top: `${entryHiPct}%`,
        height: `${entryLoPct - entryHiPct}%`, background: 'rgba(255,181,46,0.42)',
        borderTop: '1px solid #ffb52e', borderBottom: '1px solid #ffb52e',
      }
    }),
    // bottom zone (entry bottom to rail end)
    React.createElement('div', {
      style: {
        position: 'absolute', left: 0, right: 0, top: `${entryLoPct}%`,
        height: `${100 - entryLoPct}%`, background: bottomZoneColor, borderRadius: '0 0 4px 4px',
      }
    }),
    // top tick
    React.createElement('div', {
      style: {
        position: 'absolute', left: -2, right: -2, top: 0,
        height: 2, background: topTickColor, borderRadius: 1,
      }
    }),
    // T1 tick (middle)
    t1Pct !== null && React.createElement('div', {
      style: {
        position: 'absolute', left: -2, right: -2, top: `${t1Pct}%`,
        transform: 'translateY(-50%)', height: 2, background: '#4fdd8e', borderRadius: 1,
      }
    }),
    // bottom tick
    React.createElement('div', {
      style: {
        position: 'absolute', left: -2, right: -2, bottom: 0,
        height: 2, background: bottomTickColor, borderRadius: 1,
      }
    })
  );

  // ladder labels — each self-positions by its inverted pct
  const labelRow = (top, tag, price, color, rr) => React.createElement('div', {
    key: tag,
    style: {
      position: 'absolute', left: 0, right: 0, top: `${top}%`,
      transform: 'translateY(-50%)', display: 'flex', alignItems: 'baseline', gap: 8,
      whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums',
    }
  },
    React.createElement('span', {
      style: {
        minWidth: 66, fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
        letterSpacing: '0.07em', color,
      }
    }, tag),
    React.createElement('span', { style: { fontSize: 13, fontWeight: 700, color } }, price),
    rr ? React.createElement('span', { style: { fontSize: 10, color: '#b6cbe8' } }, rr) : null
  );

  const labels = React.createElement('div', { style: { position: 'relative', flex: 1 } },
    t2p !== null && labelRow(t2Pct, 'Target 2', fmtPx(t2p), '#4fdd8e',
      (t2 && t2.rr !== undefined && t2.rr !== null) ? `${t2.rr}× R:R` : null),
    t1p !== null && labelRow(t1Pct, 'Target 1', fmtPx(t1p), '#4fdd8e',
      (t1 && t1.rr !== undefined && t1.rr !== null) ? `${t1.rr}× R:R` : null),
    labelRow(entryMidPct, 'Entry zone', `${fmtPx(entryLow)} – ${fmtPx(entryHigh)}`, '#ffb52e', null),
    labelRow(stopPct, 'Stop', fmtPx(stop), '#ff8a8a', null)
  );

  const ladder = ladderValid ? React.createElement('div', {
    style: { position: 'relative', display: 'flex', gap: 14, height: 168, width: '100%' }
  }, rail, labels) : null;

  // --- freshness dot color ---------------------------------------------
  const freshColor = setup.freshness === 'fresh' ? '#4fdd8e'
    : setup.freshness === 'aging' ? '#ffb52e' : '#ff8a8a';

  // ── COLUMN 1: card-info ──────────────────────────────────────────────
  const cardInfo = React.createElement('div', {
    style: {
      padding: '20px 22px', display: 'flex', flexDirection: 'column', justifyContent: 'flex-start',
      borderRight: '1px solid rgba(255,255,255,0.08)', minWidth: 0,
    }
  },
    // header row (card-id) — pinned to top
    React.createElement('div', {
      style: {
        display: 'flex', alignItems: 'center', gap: 10,
        flexWrap: 'wrap', rowGap: 8, marginBottom: 0,
      }
    },
      React.createElement('span', {
        style: {
          fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 3,
          letterSpacing: '0.07em', color: '#ffb52e',
          border: '1px solid rgba(255,181,46,0.27)', background: 'rgba(255,181,46,0.15)',
        }
      }, `#${rank}`),
      React.createElement('span', {
        style: { fontSize: 22, fontWeight: 800, color: '#fff', letterSpacing: '-0.3px' }
      }, fmtSymbol(setup.ticker)),
      React.createElement(DirBadge, { direction: setup.direction }),
      React.createElement(TFPairBadge, { htf: setup.htf, ltf: setup.ltf }),
      React.createElement('span', {
        style: { display: 'flex', alignItems: 'center', gap: 5, marginLeft: 'auto' }
      },
        React.createElement('span', {
          style: { width: 5, height: 5, borderRadius: '50%', flexShrink: 0, background: freshColor }
        }),
        React.createElement('span', {
          style: { color: freshColor, fontSize: 11, fontWeight: 600 }
        }, `${Math.round(setup.triggeredMins)}m ago`)
      )
    ),
    // rationale (full, no truncation) — vertically centered in remaining space
    React.createElement('div', {
      style: { flex: 1, display: 'flex', alignItems: 'center' }
    },
      React.createElement('div', {
        style: { fontSize: 13.5, color: '#d7e5f6', lineHeight: 1.6, fontStyle: 'italic' }
      }, setup.rationale || '')
    )
  );

  // ── COLUMN 2: card-mid (ladder) ──────────────────────────────────────
  const cardMid = React.createElement('div', {
    style: {
      padding: '18px 22px', display: 'flex', alignItems: 'center',
      borderRight: '1px solid rgba(255,255,255,0.08)',
    }
  }, ladder);

  // ── COLUMN 3: card-acts ──────────────────────────────────────────────
  const ghostBtnStyle = {
    width: '100%', justifyContent: 'center', display: 'flex', alignItems: 'center',
    background: 'transparent', border: '1px solid rgba(255,255,255,0.12)', color: '#b6cbe8',
    padding: '6px 12px', fontSize: 12, borderRadius: 5, cursor: 'pointer',
  };
  const cardActs = React.createElement('div', {
    style: {
      padding: '18px 20px', display: 'flex', flexDirection: 'column',
      justifyContent: 'center', gap: 9,
    }
  },
    React.createElement('button', {
      onClick: () => setShowRiskModal(true),
      style: {
        width: '100%', justifyContent: 'center', display: 'flex', alignItems: 'center',
        background: '#ffb52e', color: '#1a0f08', border: 'none', fontWeight: 700,
        padding: '8px 14px', fontSize: 13, borderRadius: 5, cursor: 'pointer',
      }
    }, 'Size this trade →'),
    React.createElement('button', {
      onClick: () => { if (onSwitchTab) onSwitchTab('tt-validator'); },
      style: ghostBtnStyle,
    }, 'Validate setup →'),
    React.createElement('button', {
      onClick: () => window.open(
        `https://www.tradingview.com/chart/?symbol=BINANCE:${setup.ticker}`, '_blank'),
      style: ghostBtnStyle,
    }, 'Open chart ↗'),
    showRiskModal && React.createElement(RiskModal, {
      setup,
      onClose: () => setShowRiskModal(false),
    })
  );

  return React.createElement('div', {
    style: {
      display: 'grid',
      gridTemplateColumns: 'minmax(260px,1fr) 340px minmax(160px,180px)',
      alignItems: 'stretch', borderRadius: 10, background: '#0f0f1a',
      border: '1px solid #2a4a6a', borderLeft: '4px solid #ffb52e',
      boxShadow: '0 2px 16px rgba(0,0,0,0.4)',
      overflow: 'hidden', marginBottom: 12,
    }
  }, cardInfo, cardMid, cardActs);
}

// --- ON WATCH row -----------------------------------------------------------

function WatchRow({ item }) {
  const waiting = item.waitingFor || '';
  const waitingText = waiting.length > 60 ? waiting.slice(0, 60) + '…' : waiting;
  return React.createElement('div', {
    style: {
      display: 'flex', alignItems: 'center', padding: '10px 12px',
      borderBottom: '1px solid #1a1a2e',
    }
  },
    React.createElement('span', {
      style: { color: '#fff', fontSize: 14, fontWeight: 600, width: 80 }
    }, fmtSymbol(item.ticker)),
    React.createElement('span', { style: { marginRight: 12 } },
      React.createElement(TFPairBadge, { htf: item.htf, ltf: item.ltf })
    ),
    React.createElement(DirBadge, { direction: item.direction }),
    React.createElement('span', {
      style: { color: '#888', fontSize: 12, flex: 1, marginLeft: 12,
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }
    }, waitingText)
  );
}

// --- TriageScreen -----------------------------------------------------------

function TriageScreen({ onSwitchTab }) {
  const [results, setResults] = useTdS(null);
  const [loading, setLoading] = useTdS(false);
  const [error, setError] = useTdS(null);

  const loadResults = useTdCb(async () => {
    try {
      const data = await api('/api/trading/scanner/results');
      setResults(data);
      setError(null);
    } catch (e) {
      setError(e.message || String(e));
    }
  }, []);

  useTdE(() => { loadResults(); }, [loadResults]);

  async function runScan() {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      await api('/api/trading/scanner/run', { method: 'POST', body: JSON.stringify({}) });
      await new Promise(resolve => setTimeout(resolve, 2000));
      await loadResults();
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  const sectionHeader = (label) => React.createElement('div', {
    style: { color: '#fff', fontSize: 13, fontWeight: 700, letterSpacing: '1px', marginBottom: 12 }
  }, label);

  const emptyState = (text) => React.createElement('div', {
    style: {
      color: '#666', fontSize: 13, padding: 20, textAlign: 'center',
      background: '#0a0a14', borderRadius: 6,
    }
  }, text);

  // header row
  const header = React.createElement('div', {
    style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }
  },
    React.createElement('div', null,
      React.createElement('div', { style: { color: '#fff', fontSize: 18, fontWeight: 700 } }, 'THE PLAYBOOK'),
      React.createElement('div', { style: { color: '#888', fontSize: 12 } }, 'ICT Swing Scanner')
    ),
    React.createElement('button', {
      onClick: runScan,
      disabled: loading,
      style: {
        background: '#1a1a3a', border: '1px solid #444', color: '#fff',
        padding: '8px 16px', borderRadius: 6, fontSize: 13,
        cursor: loading ? 'default' : 'pointer', opacity: loading ? 0.6 : 1,
      }
    }, loading ? 'Scanning…' : 'Scan All')
  );

  // scannedAt row
  const scannedAt = React.createElement('div', {
    style: { color: '#666', fontSize: 11, marginBottom: 20 }
  }, (results && results.scannedAt)
    ? `Last scan: ${formatDate ? formatDate(results.scannedAt) : new Date(results.scannedAt).toLocaleString()}`
    : 'No scan run yet');

  let body;
  if (loading && !results) {
    body = React.createElement('div', {
      style: { textAlign: 'center', color: '#888', padding: 40 }
    }, 'Scanning…');
  } else if (!results) {
    body = null;
  } else {
    const setups = results.setups || [];
    const watchItems = results.watchItems || [];
    const swingSetups = setups.filter(s => s.tier === 'swing');
    const intradaySetups = setups.filter(s => s.tier === 'intraday');

    let actToday;
    if (swingSetups.length === 0 && intradaySetups.length === 0) {
      // both empty → single combined empty state
      actToday = React.createElement('div', null,
        sectionHeader('ACT TODAY'),
        emptyState('No setups qualify right now.')
      );
    } else {
      // SECTION 1 — swing (always shown when not both-empty)
      const swingSection = React.createElement('div', null,
        sectionHeader('ACT TODAY · SWING'),
        swingSetups.length === 0
          ? emptyState('No swing setups qualify right now.')
          : swingSetups.map((s, i) => React.createElement(ActTodayCard, { key: `s${i}`, setup: s, rank: i + 1, onSwitchTab }))
      );
      // SECTION 2 — intraday (only when it has setups; rank restarts at #1)
      const intradaySection = intradaySetups.length > 0
        ? React.createElement('div', { style: { marginTop: 24 } },
            sectionHeader('ACT TODAY · INTRADAY'),
            intradaySetups.map((s, i) => React.createElement(ActTodayCard, { key: `i${i}`, setup: s, rank: i + 1, onSwitchTab }))
          )
        : null;
      actToday = React.createElement('div', null, swingSection, intradaySection);
    }

    const onWatch = React.createElement('div', { style: { marginTop: 24 } },
      sectionHeader('ON WATCH'),
      watchItems.length === 0
        ? emptyState('Nothing on watch.')
        : React.createElement('div', {
            style: { background: '#0a0a14', borderRadius: 6, overflow: 'hidden' }
          }, watchItems.map((w, i) => React.createElement(WatchRow, { key: i, item: w })))
    );

    body = React.createElement('div', null, actToday, onWatch);
  }

  return React.createElement('div', { style: { width: '100%', padding: 20 } },
    header,
    scannedAt,
    error && React.createElement('div', {
      style: { color: '#f87171', fontSize: 13, marginBottom: 16 }
    }, error),
    body
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

  // Telegram Digest settings (token is write-only — never displayed)
  const [tgToken, setTgToken] = useTsS('');
  const [tgChatId, setTgChatId] = useTsS('');
  const [tgEnabled, setTgEnabled] = useTsS(false);
  const [tgSaving, setTgSaving] = useTsS(false);
  const [tgStatus, setTgStatus] = useTsS(null);        // null | 'saved' | 'error'
  const [tgTesting, setTgTesting] = useTsS(false);
  const [tgTestResult, setTgTestResult] = useTsS(null); // null | 'sent' | string (error)

  // Scheduled-scan settings
  const [autoScanEnabled, setAutoScanEnabled] = useTsS(false);
  const [scanMinVolRaw, setScanMinVolRaw] = useTsS('100000');  // accepts shorthand (100k / 1M)
  const [scanMaxTickers, setScanMaxTickers] = useTsS('250');
  const [scanTimes, setScanTimes] = useTsS(['11:00', '18:00', '21:30']);  // 3 UTC "HH:MM"; '' = off
  const [displayTz, setDisplayTz] = useTsS(() => {   // view-only; never saved to backend
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; }
    catch (_) { return 'UTC'; }
  });
  const [scanSaving, setScanSaving] = useTsS(false);
  const [scanStatus, setScanStatus] = useTsS(null);   // null | 'saved' | string (error msg)

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

  useTsE(() => {
    api('/api/settings/telegram-digest')
      .then(d => {
        setTgChatId(d.chat_id || '');
        setTgEnabled(!!d.enabled);
        // token intentionally left blank — server returns a masked value
      })
      .catch(() => {});
  }, []);

  useTsE(() => {
    api('/api/trading/scanner/settings')
      .then(d => {
        setAutoScanEnabled(!!d.auto_scan_enabled);
        if (d.scan_min_volume != null) setScanMinVolRaw(String(Math.round(d.scan_min_volume)));
        if (d.scan_max_tickers != null) setScanMaxTickers(String(d.scan_max_tickers));
        if (Array.isArray(d.scan_times_utc)) {
          // normalize to exactly 3 slots: take first 3, pad with '' to length 3
          const t = d.scan_times_utc.slice(0, 3).map(x => (x == null ? '' : String(x)));
          while (t.length < 3) t.push('');
          setScanTimes(t);
        }
      })
      .catch(() => {});
  }, []);

  // Local volume-shorthand parser (parseVolShorthand lives inside ScannerScreen).
  // Returns NaN for non-empty invalid input so save can flag it; '' → 0.
  function parseScanVol(s) {
    const t = String(s == null ? '' : s).trim().toUpperCase();
    if (!t) return 0;
    const m = t.match(/^([\d.]+)\s*([KMB]?)$/);
    if (!m) return NaN;
    return parseFloat(m[1]) * ({ K: 1e3, M: 1e6, B: 1e9 }[m[2]] || 1);
  }

  // Timezone dropdown options (view-only). Browser-detected zone is ensured
  // present so the default is always selectable.
  const TZ_COMMON = [
    'UTC',
    'America/Los_Angeles', 'America/Denver', 'America/Chicago',
    'America/New_York', 'America/Sao_Paulo',
    'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Europe/Moscow',
    'Asia/Dubai', 'Asia/Kolkata', 'Asia/Singapore',
    'Asia/Hong_Kong', 'Asia/Tokyo',
    'Australia/Sydney',
  ];

  // Render a UTC "HH:MM" as the local equivalent in `tz` (display only). '' → ''.
  function fmtUtcInTz(t, tz) {
    if (!t) return '';
    const parts = String(t).split(':');
    const h = Number(parts[0]), m = Number(parts[1]);
    if (isNaN(h) || isNaN(m)) return '';
    const d = new Date();
    d.setUTCHours(h, m, 0, 0);
    try {
      return d.toLocaleTimeString('en-US', {
        timeZone: tz, hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
      });
    } catch (_) {
      return '';
    }
  }

  // Estimate ticker count from the volume floor via piecewise interpolation of
  // the observed HL distribution. Clamped to [0, 230].
  function estimateTickerCount(floorUSD) {
    const pts = [
      [0, 230], [100000, 151], [1000000, 55],
      [10000000, 13], [50000000, 5],
    ];
    if (floorUSD <= 0) return 230;
    if (floorUSD >= 50000000) return 5;
    for (let i = 0; i < pts.length - 1; i++) {
      const [x0, y0] = pts[i], [x1, y1] = pts[i + 1];
      if (floorUSD >= x0 && floorUSD <= x1) {
        const t = (floorUSD - x0) / (x1 - x0);
        return Math.round(y0 + t * (y1 - y0));
      }
    }
    return 5;
  }

  // Live scan-coverage/duration estimate from the current volume floor + cap.
  function scanEstimate() {
    const floor = parseScanVol(scanMinVolRaw);
    const floorUSD = Number.isFinite(floor) ? Math.max(0, floor) : 0;
    const floorCount = estimateTickerCount(floorUSD);
    const maxT = parseInt(scanMaxTickers, 10);
    const cap = (Number.isFinite(maxT) && maxT > 0) ? maxT : floorCount;
    const effectiveTickers = Math.min(floorCount, cap);
    const fetches = effectiveTickers * 5;            // ~5 fetches/ticker after cache dedup
    const RATE_CAP = 55;                             // fetches/min — matches backend cap
    const estMinutes = Math.max(1, Math.ceil(fetches / RATE_CAP));
    return { effectiveTickers, estMinutes, capped: floorCount > cap };
  }

  // Mask scan-time input to a valid partial/complete 24-hour HH:MM. '' allowed
  // (empty = disabled slot). The backend re-validates + zero-pads on save.
  function handleScanTimeChange(i, raw) {
    let v = raw.replace(/[^\d:]/g, '');
    // collapse extra colons into a single hh:mm separator
    const parts = v.split(':');
    if (parts.length > 2) v = parts[0] + ':' + parts.slice(1).join('');
    // auto-insert colon after 2 digits when 3-4 digits typed with no colon
    if (/^\d{3,4}$/.test(v)) {
      v = v.slice(0, 2) + ':' + v.slice(2);
    }
    // soft-clamp hours 00-23, minutes 00-59 (only once each part is complete)
    const m = v.match(/^(\d{1,2}):?(\d{0,2})$/);
    if (m) {
      let hh = m[1], mm = m[2];
      if (hh.length === 2 && parseInt(hh) > 23) hh = '23';
      if (mm.length === 2 && parseInt(mm) > 59) mm = '59';
      v = v.includes(':') ? `${hh}:${mm}` : hh;
    }
    v = v.slice(0, 5);
    const next = [...scanTimes];
    next[i] = v;
    setScanTimes(next);
  }

  // On blur, normalize a complete value to zero-padded HH:MM (e.g. "3:2" →
  // "03:02"). Incomplete/empty values are left as-is.
  function handleScanTimeBlur(i) {
    const v = scanTimes[i];
    const m = /^(\d{1,2}):(\d{1,2})$/.exec(v || '');
    if (!m) return;
    const padded = `${m[1].padStart(2, '0')}:${m[2].padStart(2, '0')}`;
    if (padded === v) return;
    const next = [...scanTimes];
    next[i] = padded;
    setScanTimes(next);
  }

  async function saveScheduledScan() {
    const minVol = parseScanVol(scanMinVolRaw);
    const maxT = parseInt(scanMaxTickers, 10);
    if (isNaN(minVol)) {
      setScanStatus('Invalid volume — use a number or shorthand like 100k, 1M');
      setTimeout(() => setScanStatus(null), 4000);
      return;
    }
    if (isNaN(maxT) || maxT < 1) {
      setScanStatus('Max tickers must be a positive integer');
      setTimeout(() => setScanStatus(null), 4000);
      return;
    }
    setScanSaving(true); setScanStatus(null);
    try {
      await api('/api/trading/scanner/settings', {
        method: 'PUT',
        body: JSON.stringify({
          auto_scan_enabled: autoScanEnabled,
          scan_min_volume: minVol,
          scan_max_tickers: maxT,
          scan_times_utc: scanTimes,
        }),
      });
      setScanStatus('saved');
      setTimeout(() => setScanStatus(null), 2000);
    } catch (e) {
      // api() throws Error(responseText); the body is JSON { error }
      let msg = 'Save failed';
      try { msg = JSON.parse(e.message).error || msg; } catch (_) { msg = e.message || msg; }
      setScanStatus(msg);
      setTimeout(() => setScanStatus(null), 4000);
    }
    setScanSaving(false);
  }

  async function saveTelegram() {
    setTgSaving(true); setTgStatus(null);
    try {
      const body = { chat_id: tgChatId, enabled: tgEnabled, ...(tgToken ? { bot_token: tgToken } : {}) };
      await api('/api/settings/telegram-digest', { method: 'PUT', body: JSON.stringify(body) });
      setTgStatus('saved');
      setTgToken('');
      setTimeout(() => setTgStatus(null), 4000);
    } catch (_) {
      setTgStatus('error');
      setTimeout(() => setTgStatus(null), 4000);
    }
    setTgSaving(false);
  }

  async function testTelegram() {
    setTgTesting(true); setTgTestResult(null);
    try {
      const res = await api('/api/telegram/test', { method: 'POST' });
      if (res && res.ok) setTgTestResult('sent');
      else setTgTestResult((res && res.error) || 'error');
    } catch (e) {
      // api() throws on non-2xx; the 400 body is JSON { ok:false, error }
      let msg = 'error';
      try { msg = JSON.parse(e.message).error || 'error'; } catch (_) { msg = e.message || 'error'; }
      setTgTestResult(msg);
    }
    setTgTesting(false);
    setTimeout(() => setTgTestResult(null), 4000);
  }

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
        ),
        /* Scheduled Scan subsection */
        React.createElement('div', { style: { borderTop: '1px solid var(--line)', paddingTop: 12, marginTop: 2, display: 'flex', flexDirection: 'column', gap: 20 } },
          React.createElement('div', { style: { fontSize: 13, fontWeight: 600, color: 'var(--text2)' } }, 'Scheduled Scan'),
          /* Enable toggle */
          React.createElement('div', null,
            React.createElement('label', { style: { display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 } },
              React.createElement('input', { type: 'checkbox', checked: autoScanEnabled, onChange: e => setAutoScanEnabled(e.target.checked) }),
              'Enable scheduled background scans'
            ),
            React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginTop: 4 } },
              'Runs an automatic wide scan at the times set below, covering all tickers above the volume floor. Setups are saved to the triage screen, and a Telegram alert is sent when each scan finishes.')
          ),
          /* Minimum 24h volume */
          React.createElement('div', null,
            lbl('Minimum 24h volume (USD)'),
            React.createElement('input', {
              className: 'tv-input', value: scanMinVolRaw,
              style: { width: 140, fontSize: 13 }, placeholder: 'e.g. 100k, 1M',
              onChange: e => setScanMinVolRaw(e.target.value),
            }),
            React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginTop: 4 } },
              'Only scan tickers above this 24h notional volume. Lower = wider. On Hyperliquid: ~$100k ≈ 150 tickers, ~$1M ≈ 55, ~$50M ≈ 5.')
          ),
          /* Max tickers */
          React.createElement('div', null,
            lbl('Max tickers'),
            React.createElement('input', {
              className: 'tv-input', type: 'number', value: scanMaxTickers,
              style: { width: 90, fontSize: 13 },
              onChange: e => setScanMaxTickers(e.target.value),
            }),
            React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginTop: 4 } }, 'Safety cap on scan universe size.'),
            (() => {
              const est = scanEstimate();
              return React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginTop: 8, fontStyle: 'italic' } },
                `≈ ${est.effectiveTickers} tickers per scan · est. ~${est.estMinutes} min to complete${est.capped ? ' (capped at max tickers)' : ''} (approximate; longer if Hyperliquid throttles).`);
            })()
          ),
          /* Scan times (UTC) — 3 slots, empty = disabled. Inputs stay UTC; the
             beside-text shows the local equivalent in displayTz (view-only). */
          React.createElement('div', { style: { borderTop: '1px solid var(--line)', paddingTop: 16 } },
            lbl('Scan times (UTC)'),
            /* Timezone dropdown (view-only) */
            React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 } },
              React.createElement('span', { style: { fontSize: 12, color: 'var(--text4)' } }, 'Show times in:'),
              React.createElement('select', {
                className: 'tv-input', value: displayTz, style: { fontSize: 12, width: 'auto' },
                onChange: e => setDisplayTz(e.target.value),
              },
                (TZ_COMMON.includes(displayTz) ? TZ_COMMON : [displayTz, ...TZ_COMMON]).map(tz =>
                  React.createElement('option', { key: tz, value: tz }, tz)
                )
              )
            ),
            React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
              [0, 1, 2].map(i =>
                React.createElement('div', { key: i, style: { display: 'flex', alignItems: 'center', gap: 10 } },
                  React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)', width: 64 } }, `Window ${i + 1}`),
                  React.createElement('input', {
                    className: 'tv-input', type: 'text', inputMode: 'numeric',
                    placeholder: 'HH:MM', maxLength: 5, value: scanTimes[i] || '',
                    style: { width: 90, fontSize: 13 },
                    onChange: e => handleScanTimeChange(i, e.target.value),
                    onBlur: () => handleScanTimeBlur(i),
                  }),
                  React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)', minWidth: 96 } },
                    scanTimes[i] ? `→ ${fmtUtcInTz(scanTimes[i], displayTz)}` : ''),
                  React.createElement('button', {
                    title: 'Clear (disable this window)',
                    style: { background: 'none', border: 'none', color: 'var(--text4)', cursor: 'pointer', fontSize: 14, padding: '0 2px' },
                    onClick: () => setScanTimes(prev => { const next = [...prev]; next[i] = ''; return next; }),
                  }, '✕')
                )
              )
            ),
            React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginTop: 8 } },
              'Each window is the scan START time in UTC. A Telegram alert is sent when that scan finishes. Leave a slot empty to disable it.')
          ),
          /* Save + status */
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 10 } },
            React.createElement('button', { className: 'tv-btn primary', style: { fontSize: 12 }, disabled: scanSaving, onClick: saveScheduledScan }, scanSaving ? 'Saving…' : 'Save'),
            scanStatus === 'saved' && React.createElement('span', { style: { color: 'var(--ok)', fontSize: 12 } }, 'Saved ✓'),
            scanStatus && scanStatus !== 'saved' && React.createElement('span', { style: { color: 'var(--fail)', fontSize: 12 } }, scanStatus)
          )
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
    ),

    /* ── SECTION 4: Telegram Digest ── */
    React.createElement('div', null,
      React.createElement('div', { style: { fontSize: 15, fontWeight: 700, color: 'var(--accent)', marginBottom: 4 } }, 'Telegram Digest'),
      React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', marginBottom: 12 } }, 'Scanner triage digest sent at 5AM, 12PM, and 3:30PM Pacific (12:00, 19:00, 22:30 UTC)'),
      React.createElement('div', { className: 'tv-card', style: { display: 'flex', flexDirection: 'column', gap: 10 } },
        /* Bot Token (write-only) */
        React.createElement('div', null,
          lbl('Bot Token'),
          React.createElement('input', {
            className: 'tv-input',
            type: 'password',
            placeholder: 'Enter new token to update',
            value: tgToken,
            style: { width: '100%' },
            onChange: e => setTgToken(e.target.value),
          }),
          React.createElement('div', { style: { fontSize: 11, color: '#666', marginTop: 3 } }, 'Leave blank to keep existing token')
        ),
        /* Chat ID */
        React.createElement('div', null,
          lbl('Chat ID'),
          React.createElement('input', {
            className: 'tv-input',
            type: 'text',
            placeholder: 'e.g. 987654321',
            value: tgChatId,
            style: { width: '100%' },
            onChange: e => setTgChatId(e.target.value),
          })
        ),
        /* Enabled toggle */
        React.createElement('div', null,
          lbl('Enabled'),
          React.createElement('label', { style: { display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 } },
            React.createElement('input', { type: 'checkbox', checked: tgEnabled, onChange: e => setTgEnabled(e.target.checked) }),
            'Send scheduled digests'
          )
        ),
        /* Actions */
        React.createElement('div', { style: { display: 'flex', gap: 8 } },
          React.createElement('button', { className: 'tv-btn primary', style: { fontSize: 12 }, disabled: tgSaving, onClick: saveTelegram }, tgSaving ? 'Saving…' : 'Save'),
          React.createElement('button', { className: 'tv-btn', style: { fontSize: 12 }, disabled: tgTesting, onClick: testTelegram }, tgTesting ? 'Sending…' : 'Send Test Digest')
        ),
        /* Status messages */
        tgStatus === 'saved' && React.createElement('div', { style: { color: 'var(--ok)', fontSize: 12 } }, '✓ Saved'),
        tgStatus === 'error' && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 12 } }, '✗ Save failed'),
        tgTestResult === 'sent' && React.createElement('div', { style: { color: 'var(--ok)', fontSize: 12 } }, '✓ Digest sent — check Telegram'),
        tgTestResult && tgTestResult !== 'sent' && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 12 } }, tgTestResult)
      )
    )
  );
}

/* ===== SCANNER (Watchlist tab) — restored from 92158d7 ===== */
function ScannerScreen({ onSwitchTab }) {
  const [watchlist, setWatchlist] = useTdS([]);
  const [signals, setSignals] = useTdS([]);   // kept ONLY to source per-symbol price
  const [showViewResults, setShowViewResults] = useTdS(false);
  const [scanReadyCount, setScanReadyCount] = useTdS(0);
  const [scanProgress, setScanProgress] = useTdS(null);  // null = idle; else { done, total }
  const [staleMode, setStaleMode] = useTdS('all');       // 'all'|'never'|'30'|'60'|'240'
  const [hlVolumes, setHlVolumes] = useTdS({});
  const [running, setRunning] = useTdS(false);
  const [error, setError] = useTdS(null);
  const [checkedKeys, setCheckedKeys] = useTdS(new Set());
  const [filterType, setFilterType] = useTdS('all');
  const [filterTicker, setFilterTicker] = useTdS('');
  const [tickerInput, setTickerInput] = useTdS('');
  const [addError, setAddError] = useTdS('');
  const [sortCol, setSortCol] = useTdS('symbol');
  const [sortDir, setSortDir] = useTdS('asc');
  const [scannerStrategies, setScannerStrategies] = useTdS([]);
  const [selectedScanStrategies, setSelectedScanStrategies] = useTdS([]);

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

  // Live server-side scan status (manual or scheduled), polled every 5s.
  const [scanStatus, setScanStatus] = useTdS(null);
  const [cancelling, setCancelling] = useTdS(false);
  const [cancelNote, setCancelNote] = useTdS(null);
  const [stalled, setStalled] = useTdS(false);   // done hasn't advanced for a while
  const lastDoneRef = useTdRef(null);
  const lastDoneChangedAtRef = useTdRef(0);
  const cancelLoopRef = useTdRef(false);   // set by cancelScan; runScanBatched stops between batches

  // Last scheduled scan summary (collapsible section below the table)
  const [lastSched, setLastSched] = useTdS(null);
  const [schedOpen, setSchedOpen] = useTdS(false);
  const wasRunningRef = useTdRef(false);   // to detect running → not-running edge

  const PAIRS_PER_TICKER = 4;   // V3_PAIRS has 4 entries
  const BATCH_SIZE = 20;

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

  function loadLastSched() {
    api('/api/trading/scanner/last-scheduled-scan')
      .then(d => setLastSched(d))
      .catch(() => {});
  }

  useTdE(() => {
    api('/api/trading/strategies').then(data => setScannerStrategies(data || [])).catch(() => {});
    load();
    loadLastSched();
  }, []);

  // Poll scan status every 5s while mounted — catches scheduled scans that
  // start while you're viewing the page, and drives the progress banner.
  useTdE(() => {
    let alive = true;
    const poll = async () => {
      try {
        const s = await api('/api/trading/scanner/status');
        if (!alive) return;
        if (s && s.running) {
          // stall detection: has `done` advanced since the last poll?
          if (lastDoneRef.current !== s.done) {
            lastDoneRef.current = s.done;
            lastDoneChangedAtRef.current = Date.now();
            setStalled(false);
          } else {
            setStalled(Date.now() - (lastDoneChangedAtRef.current || Date.now()) > 45000);
          }
        } else {
          // idle → reset stall tracking + cancel UI
          lastDoneRef.current = null;
          lastDoneChangedAtRef.current = 0;
          setStalled(false);
          setCancelling(false);
          setCancelNote(null);
        }
        // On a running → not-running edge, a scan just finished — refetch the
        // last-scheduled-scan summary so a fresh scheduled run shows up.
        const nowRunning = !!(s && s.running);
        if (wasRunningRef.current && !nowRunning) {
          loadLastSched();
        }
        wasRunningRef.current = nowRunning;
        setScanStatus(s);
      } catch (e) { /* ignore poll errors */ }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const scanRunning = scanStatus && scanStatus.running;

  // Banner routing. A scan is "local" when this tab started it (scanProgress /
  // running are set by runScanBatched). A "recovered" scan is one running
  // server-side that this tab has no local state for — covers a post-refresh
  // manual scan, a scheduled scan, or a scan started in another tab. The two
  // are mutually exclusive by construction, so exactly one banner shows.
  const localScanActive = scanProgress != null || running;
  const serverScanActive = scanStatus && scanStatus.running;
  const recoveredScan = serverScanActive && !localScanActive;

  function fmtEta(sec) {
    if (sec == null) return '';
    if (sec < 60) return `~${sec}s`;
    const m = Math.floor(sec / 60), s = sec % 60;
    return `~${m}m ${s}s`;
  }

  // Format an ISO timestamp in the browser's LOCAL timezone, e.g.
  // "Jun 21, 9:23 AM PDT" (the short zone abbreviation comes from the browser).
  function fmtSchedTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString('en-US', {
      month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit',
      timeZoneName: 'short',
    });
  }

  // Outcome → badge style for the Last Scheduled Scan list.
  function schedBadge(outcome, reason) {
    const isErr = typeof reason === 'string' && reason.startsWith('error');
    if (outcome === 'SETUP_READY')
      return { label: 'READY', bg: 'rgba(79,221,142,0.15)', color: '#4fdd8e', border: '1px solid rgba(79,221,142,0.4)' };
    if (outcome === 'POI_WAITING')
      return { label: 'WATCH', bg: 'rgba(99,179,237,0.15)', color: '#63b3ed', border: '1px solid rgba(99,179,237,0.4)' };
    if (isErr)
      return { label: 'ERROR', bg: 'rgba(255,138,138,0.15)', color: '#f87171', border: '1px solid rgba(255,138,138,0.4)' };
    return { label: 'DROPPED', bg: 'var(--panel3)', color: 'var(--text4)', border: '1px solid var(--line)' };
  }

  async function cancelScan() {
    if (cancelling) return;
    setCancelling(true);
    try {
      await api('/api/trading/scanner/cancel', { method: 'POST' });
      // Also stop a local batched loop (if this tab is running one) between batches.
      cancelLoopRef.current = true;
      setCancelNote('Cancel requested — stopping at the next ticker (may take a few seconds).');
      // keep cancelling=true (button stays "Cancelling…") until status flips
      // running:false, which the poll handles.
    } catch (e) {
      // 409 (no scan running — race) or other error → re-enable; the next poll
      // clears the banner if the scan already ended.
      setCancelling(false);
    }
  }

  // Per-symbol current price, sourced from the latest signal group for that symbol.
  const sigPriceMap = useTdMemo(() => {
    const m = {};
    signals.forEach(s => { if (s && s.symbol) m[s.symbol] = s.current_price; });
    return m;
  }, [signals]);

  // Build display rows — keyed on watchlist; attach volume/type/price/last-scan.
  const allRows = useTdMemo(() => {
    return watchlist.map(w => {
      const volEntry = hlVolumes[(w.symbol || '').toUpperCase()];
      return {
        symbol: w.symbol,
        wl: w,
        vol24h: volEntry ? volEntry.volume_24h : null,
        assetType: w.asset_type || 'crypto',
        // Live price from the same hl-volumes map the volume uses (populates
        // every row with a volume entry, not just previously-scanned ones).
        price: (volEntry && volEntry.price != null) ? volEntry.price : null,
        lastScannedAt: w.last_scanned_at || null,
      };
    });
  }, [watchlist, hlVolumes]);

  // Filter + sort
  const displayRows = useTdMemo(() => {
    let rows = allRows;
    if (filterTicker.trim()) {
      const q = filterTicker.trim().toLowerCase();
      rows = rows.filter(r => fmtSymbol(r.symbol).toLowerCase().includes(q));
    }
    if (filterType !== 'all') {
      rows = rows.filter(r => r.assetType === filterType);
    }
    const keyFn = {
      symbol:   r => fmtSymbol(r.symbol).toLowerCase(),
      type:     r => r.assetType || '',
      vol:      r => r.vol24h || 0,
      price:    r => (r.price == null ? 0 : r.price),
      lastscan: r => (r.lastScannedAt ? (new Date(r.lastScannedAt).getTime() || 0) : 0),
    }[sortCol] || (r => fmtSymbol(r.symbol).toLowerCase());
    const dir = sortDir === 'asc' ? 1 : -1;
    rows = [...rows].sort((a, b) => {
      const ka = keyFn(a), kb = keyFn(b);
      if (ka < kb) return -1 * dir;
      if (ka > kb) return 1 * dir;
      return 0;
    });
    return rows;
  }, [allRows, filterTicker, filterType, sortCol, sortDir]);

  function sortBy(col) {
    if (sortCol === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortCol(col); setSortDir('asc');
    }
  }

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

  // Batch large scans into chunks so each POST stays well under the
  // gunicorn 360s worker timeout. The /run route accepts a `symbols`
  // filter (SELECT ... WHERE symbol IN (...)), so each batch scans only
  // Human-readable label for the staleMode dropdown values (used in notes).
  const STALE_LABELS = { all: 'All', never: 'Never scanned', '30': 'Stale >30m', '60': 'Stale >1h', '240': 'Stale >4h' };

  // Decide whether a row is stale (i.e. eligible to scan) under the current
  // staleMode. Mirrors the server-side stale_minutes filter so the client
  // pre-filter and the backend agree — the progress total then reflects only
  // the tickers that will actually be scanned.
  function isRowStale(lastScannedAt, mode) {
    if (mode === 'all') return true;   // no filter
    if (!lastScannedAt) return true;   // never scanned = always stale
    const last = new Date(
      // normalize: space-form → T, ensure parseable; treat naive stamps as UTC
      (lastScannedAt.includes('T') ? lastScannedAt : lastScannedAt.replace(' ', 'T'))
      + (lastScannedAt.endsWith('Z') || lastScannedAt.includes('+') ? '' : 'Z')
    );
    if (isNaN(last.getTime())) return true; // unparseable = treat as stale
    const minutesMap = { never: 525600, '30': 30, '60': 60, '240': 240 };
    const cutoffMin = minutesMap[mode] ?? 0;
    const ageMin = (Date.now() - last.getTime()) / 60000;
    return ageMin >= cutoffMin;
  }

  // its slice. No tiers → backend defaults to all tiers.
  async function runScanBatched(symbolList) {
    const batches = [];
    for (let i = 0; i < symbolList.length; i += BATCH_SIZE) {
      batches.push(symbolList.slice(i, i + BATCH_SIZE));
    }

    // Freshness filter: 'all' = no filter; 'never' = a 1-year cutoff so only
    // truly never-scanned (NULL) rows pass; else the minute value.
    const staleMin = staleMode === 'all' ? undefined
      : (staleMode === 'never' ? 525600 : parseInt(staleMode, 10));

    setShowViewResults(false);
    setScanReadyCount(0);
    setError(null);
    setRunning(true);
    setScanProgress({ done: 0, total: symbolList.length });
    cancelLoopRef.current = false;   // fresh scan — clear any prior cancel request

    let totalReady = 0;
    try {
      for (let b = 0; b < batches.length; b++) {
        // Cancelled mid-scan (server cancel also flips this) → stop sending batches.
        if (cancelLoopRef.current) break;
        const batch = batches[b];
        const body = { symbols: batch };
        if (selectedScanStrategies.length > 0) body.strategy_ids = selectedScanStrategies;
        if (staleMin != null) body.stale_minutes = staleMin;
        const resp = await api('/api/trading/scanner/run', {
          method: 'POST',
          body: JSON.stringify(body),
        });
        if (resp && typeof resp.setupReadyCount === 'number') {
          totalReady += resp.setupReadyCount;
        }
        setScanProgress({
          done: Math.min((b + 1) * BATCH_SIZE, symbolList.length),
          total: symbolList.length,
        });
      }
      await load();            // refresh watchlist rows (last scan, price)
      setScanReadyCount(totalReady);
      setShowViewResults(true);
    } catch (e) {
      setError('Scan failed: ' + (e.message || 'upstream error'));
    } finally {
      setRunning(false);
      setScanProgress(null);
    }
  }

  // Drop rows that aren't stale under the current staleMode, then start the
  // scan. If the filter leaves nothing, show an inline note instead of kicking
  // off an empty scan (so "X of Y" stays accurate to the real scan scope).
  function startScanFiltered(candidateRows) {
    const eligible = candidateRows.filter(r => isRowStale(r.lastScannedAt, staleMode));
    const symbols = eligible.map(r => r.symbol);
    if (staleMode !== 'all' && symbols.length === 0) {
      setError(`No tickers match '${STALE_LABELS[staleMode] || staleMode}' — nothing to scan.`);
      return;
    }
    setError(null);
    runScanBatched(symbols);
  }

  function runScanSelected() {
    if (!checkedKeys.size) return;
    const selectedRows = allRows.filter(r => checkedKeys.has(r.symbol));
    startScanFiltered(selectedRows);
  }

  function runScanAll() {
    // All watchlist rows, honoring the active Type filter (not the ticker search).
    const candidateRows = allRows.filter(r => filterType === 'all' || r.assetType === filterType);
    startScanFiltered(candidateRows);
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
    const cost = n * _costRate() * 3; // ~pairs per symbol
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

  const _grpLabel = (txt) => React.createElement('span', {
    style: { fontSize: 10, fontWeight: 700, color: 'var(--text4)',
             letterSpacing: '0.06em', textTransform: 'uppercase', marginRight: 2 }
  }, txt);

  // Filter bar — ticker filter + type filter
  const filterBar = React.createElement('div', {
    style: { display: 'flex', gap: 6, padding: '8px 14px',
             borderBottom: '1px solid var(--line-soft)', alignItems: 'center',
             flexWrap: 'wrap' }
  },
    React.createElement('input', {
      className: 'tv-input', placeholder: 'Filter ticker…', value: filterTicker,
      style: { fontSize: 11, padding: '2px 8px', width: 110 },
      onChange: e => setFilterTicker(e.target.value),
    }),
    React.createElement('span', { style: { width: 1, height: 16, background: 'var(--line)', margin: '0 10px' } }),
    _grpLabel('Type'),
    ...['all','crypto','tradfi'].map(t =>
      React.createElement('span', {
        key: 'ty-' + t, onClick: () => setFilterType(t),
        style: {
          fontSize: 11, cursor: 'pointer', padding: '3px 10px', borderRadius: 12,
          background: filterType === t ? 'var(--accent)' : 'var(--panel3)',
          color: filterType === t ? '#000' : 'var(--text3)',
          border: filterType === t ? 'none' : '1px solid var(--line)',
          textTransform: 'capitalize', fontWeight: 500,
        }
      }, t)
    ),
    React.createElement('div', { style: { flex: 1 } }),
    React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)' } },
      checkedKeys.size > 0
        ? ('Scan Selected: ' + checkedKeys.size + ' symbols')
        : ('Scan All: ' + watchlist.length + ' symbols')
    )
  );

  // Top bar
  const topBar = React.createElement('div', {
    style: { display: 'flex', gap: 8, padding: '10px 14px', borderBottom: '1px solid var(--line-soft)',
             alignItems: 'center', flexWrap: 'wrap' }
  },
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
    React.createElement('label', {
      style: { fontSize: 11, color: 'var(--text4)', display: 'flex', alignItems: 'center', gap: 4 },
      title: 'Skip symbols scanned more recently than this',
    },
      'Scan:',
      React.createElement('select', {
        className: 'tv-input',
        style: { fontSize: 12, padding: '2px 4px' },
        value: staleMode,
        disabled: running || scanRunning,
        onChange: e => setStaleMode(e.target.value),
      },
        React.createElement('option', { value: 'all' }, 'All'),
        React.createElement('option', { value: 'never' }, 'Never scanned'),
        React.createElement('option', { value: '30' }, 'Stale >30m'),
        React.createElement('option', { value: '60' }, 'Stale >1h'),
        React.createElement('option', { value: '240' }, 'Stale >4h')
      )
    ),
    React.createElement('button', {
      className: 'tv-btn primary', style: { fontSize: 12 },
      disabled: running || scanRunning || checkedKeys.size === 0,
      onClick: runScanSelected,
      title: scanRunning ? 'A scan is already in progress'
        : (checkedKeys.size === 0 ? 'Select symbols to scan' : `${fmtCost(checkedKeys.size)} (${checkedKeys.size} symbols)`),
    }, running ? 'Scanning…' : '▶ Scan Selected'),
    React.createElement('button', {
      className: 'tv-btn', style: { fontSize: 12 },
      disabled: running || scanRunning,
      onClick: runScanAll,
      title: scanRunning ? 'A scan is already in progress' : `${fmtCost(watchlist.length)} (${watchlist.length} symbols)`,
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

  // Table — [checkbox] TICKER | TYPE | 24H VOL | PRICE | LAST SCAN | [remove]
  const colTemplate = '22px minmax(90px,1.4fr) 90px 110px 130px minmax(140px,1fr) 26px';
  const thStyle = { fontSize: 12, color: 'var(--text3)', fontWeight: 700, letterSpacing: '0.08em',
                    textTransform: 'uppercase', padding: '8px 6px', userSelect: 'none' };

  const sortArrow = (col) => sortCol === col ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '';
  const th = (label, col) => React.createElement('div', {
    style: { ...thStyle, cursor: 'pointer' },
    onClick: () => sortBy(col),
  }, label + sortArrow(col));

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
    th('TICKER', 'symbol'),
    th('TYPE', 'type'),
    th('24H VOL', 'vol'),
    th('PRICE', 'price'),
    th('LAST SCAN', 'lastscan'),
    React.createElement('div', { style: thStyle }),
  );

  function fmtVol(v) {
    if (!v) return '—';
    if (v >= 1e9) return '$' + (v/1e9).toFixed(1) + 'B';
    if (v >= 1e6) return '$' + (v/1e6).toFixed(0) + 'M';
    if (v >= 1e3) return '$' + (v/1e3).toFixed(0) + 'K';
    return '$' + v.toFixed(0);
  }

  const tableRows = displayRows.map(row => {
    const sym = row.symbol;
    const wl = row.wl;
    const assetType = row.assetType;
    const isChecked = checkedKeys.has(sym);

    return React.createElement('div', {
      key: sym,
      style: {
        display: 'grid', gridTemplateColumns: colTemplate, gap: '0 10px',
        padding: '8px 14px', borderBottom: '1px solid var(--line-soft)',
        alignItems: 'center',
      }
    },
      // Checkbox
      React.createElement('div', null,
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
      // 24H Vol
      React.createElement('div', { style: { fontSize: 12, color: 'var(--text3)' } }, fmtVol(row.vol24h)),
      // Price
      React.createElement('div', { style: { fontSize: 12, color: 'var(--text2)', fontVariantNumeric: 'tabular-nums' } },
        row.price != null ? `$${Number(row.price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}` : '—'
      ),
      // Last scan (from watchlist row's last_scanned_at)
      React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)' } },
        fmtScanTime(row.lastScannedAt)
      ),
      // Remove
      React.createElement('div', {
        onClick: () => { wl && removeTicker(sym); },
        style: { cursor: wl ? 'pointer' : 'default', color: wl ? 'var(--fail)' : 'transparent',
                 textAlign: 'center', fontSize: 14, fontWeight: 700 }
      }, wl ? '×' : '')
    );
  });

  // Filter active label
  const filterLabel = filterTicker.trim() && React.createElement('div', {
    style: { fontSize: 11, color: 'var(--text4)', textAlign: 'center', padding: '5px 0', fontStyle: 'italic' }
  }, `Filters active — showing ${displayRows.length} of ${allRows.length}`);

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 0 } },
    topBar,
    /* Case B — recovered/other scan: a scan is running server-side that this
       tab has no local state for (post-refresh manual scan, scheduled scan, or
       a scan from another tab). Driven entirely by scanStatus, with a cancel
       button. Mutually exclusive with the orange Case A banner below, since
       recoveredScan is false whenever a local scan is active. */
    recoveredScan && React.createElement('div', {
      style: {
        background: '#103f63', border: '1px solid #266594', borderRadius: 6,
        padding: '12px 16px', marginBottom: 12,
      }
    },
      React.createElement('div', { style: { color: '#d7e5f6', fontSize: 13, fontWeight: 600, marginBottom: 6 } },
        scanStatus.kind === 'scheduled' ? '⏳ Scheduled scan in progress' : '⏳ Scan in progress'),
      React.createElement('div', { style: { color: '#b6cbe8', fontSize: 12, marginBottom: 6 } },
        // Show TICKER progress (cap/settings are in tickers); the bar fill below
        // stays at pair granularity for smooth motion.
        `${Math.floor((scanStatus.done || 0) / PAIRS_PER_TICKER)} / ${Math.ceil((scanStatus.total || 0) / PAIRS_PER_TICKER)} tickers`
        + (scanStatus.current ? ` · scanning ${fmtSymbol(scanStatus.current)}…` : '')
        + (scanStatus.etaSeconds != null ? ` · ${fmtEta(scanStatus.etaSeconds)} remaining` : '')),
      React.createElement('div', { style: { height: 6, background: 'rgba(255,255,255,0.1)', borderRadius: 3, overflow: 'hidden', marginBottom: 8 } },
        React.createElement('div', { style: {
          height: 6, background: '#2180c8',
          width: `${scanStatus.total ? (scanStatus.done / scanStatus.total) * 100 : 0}%`,
          transition: 'width 0.3s',
        } })
      ),
      stalled && React.createElement('div', { style: { color: '#ffb52e', fontSize: 11, marginBottom: 8 } },
        '⚠ No progress for a while — the scan may be stuck. You can cancel below.'),
      React.createElement('button', {
        disabled: cancelling, onClick: cancelScan,
        style: {
          background: cancelling ? 'var(--panel3)' : '#2b0d0d', border: '1px solid #6b1a1a',
          color: '#f87171', padding: '6px 14px', borderRadius: 5, fontSize: 12,
          cursor: cancelling ? 'default' : 'pointer',
        },
      }, cancelling ? 'Cancelling…' : 'Cancel scan'),
      cancelNote && React.createElement('div', { style: { color: '#b6cbe8', fontSize: 11, marginTop: 6 } }, cancelNote),
      React.createElement('div', { style: { color: '#6b8299', fontSize: 11, marginTop: 6 } },
        "If the scan doesn't stop within ~30s it may be stuck — a redeploy will force-clear it.")
    ),
    scanProgress && React.createElement('div', {
      style: {
        background: '#3a2410', border: '2px solid #ffb52e', borderRadius: 8,
        padding: '14px 18px', marginBottom: 12,
      }
    },
      React.createElement('div', { style: { color: '#ffb52e', fontSize: 14, fontWeight: 700, marginBottom: 6 } },
        `Scanning ${scanProgress.done} of ${scanProgress.total}…`),
      React.createElement('div', { style: { height: 6, background: 'rgba(255,181,46,0.15)', borderRadius: 3, overflow: 'hidden' } },
        React.createElement('div', { style: {
          height: 6, background: '#ffb52e',
          width: `${scanProgress.total ? (scanProgress.done / scanProgress.total) * 100 : 0}%`,
          transition: 'width 0.3s',
        } })
      ),
      React.createElement('div', { style: {
        color: '#ffb52e', fontSize: 13, fontWeight: 700, marginTop: 8, marginBottom: 8,
        background: 'rgba(255,181,46,0.12)', padding: '6px 10px', borderRadius: 4,
      } },
        '⚠ Keep this tab open until the scan completes — closing it will stop the scan.'),
      React.createElement('button', {
        disabled: cancelling, onClick: cancelScan,
        style: {
          background: cancelling ? 'var(--panel3)' : '#2b0d0d', border: '1px solid #6b1a1a',
          color: '#f87171', padding: '6px 14px', borderRadius: 5, fontSize: 12,
          cursor: cancelling ? 'default' : 'pointer',
        },
      }, cancelling ? 'Cancelling…' : 'Cancel scan'),
      cancelNote && React.createElement('div', { style: { color: '#e0b878', fontSize: 11, marginTop: 6 } }, cancelNote),
      React.createElement('div', { style: { color: '#a88a5a', fontSize: 11, marginTop: 6 } },
        "If the scan doesn't stop within ~30s it may be stuck — a redeploy will force-clear it.")
    ),
    showViewResults && React.createElement('div', {
      style: {
        background: '#1a3a1a', border: '1px solid #2a6a2a', borderRadius: 6,
        padding: '10px 16px', marginBottom: 12,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }
    },
      React.createElement('span', { style: { color: '#4ade80', fontSize: 13, fontWeight: 600 } },
        scanReadyCount > 0
          ? `✓ Scan complete · ${scanReadyCount} setup${scanReadyCount === 1 ? '' : 's'} ready`
          : '✓ Scan complete · no setups ready'
      ),
      React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
        React.createElement('button', {
          style: {
            background: '#4ade80', color: '#0a2a00', border: 'none', fontWeight: 700,
            padding: '6px 14px', borderRadius: 5, fontSize: 12, cursor: 'pointer',
          },
          onClick: () => { if (onSwitchTab) onSwitchTab('tt-scanner'); },
        }, 'View results →'),
        React.createElement('button', {
          style: { background: 'none', border: 'none', color: '#4ade80', fontSize: 16, cursor: 'pointer', padding: '0 4px' },
          onClick: () => setShowViewResults(false),
        }, '✕')
      )
    ),
    filterBar,
    importPanel,
    error && React.createElement('div', { style: { padding: '8px 14px', color: 'var(--fail)', fontSize: 12 } }, `Error: ${error}`),
    React.createElement('div', { className: 'tv-card', style: { padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' } },
      React.createElement('div', { style: { maxHeight: 'calc(100vh - 280px)', overflowY: 'auto', overflowX: 'auto' } },
        tableHeader,
        React.createElement('div', null, ...tableRows),
        filterLabel
      )
    ),
    /* ── Last Scheduled Scan (collapsible) ── */
    (() => {
      const hasData = lastSched && lastSched.scannedAt;
      const tickers = (lastSched && lastSched.tickers) || [];
      return React.createElement('div', { style: { marginTop: 16 } },
        // header (clickable when there's data)
        React.createElement('div', {
          onClick: hasData ? () => setSchedOpen(o => !o) : undefined,
          style: {
            display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
            background: 'var(--panel2)', border: '1px solid var(--line)', borderRadius: 6,
            cursor: hasData ? 'pointer' : 'default', fontSize: 12,
          }
        },
          hasData
            ? React.createElement('span', { style: { color: 'var(--text3)', fontSize: 11 } }, schedOpen ? '▾' : '▸')
            : null,
          React.createElement('span', { style: { fontWeight: 600, color: 'var(--text2)' } }, 'Last Scheduled Scan'),
          hasData
            ? React.createElement('span', { style: { color: 'var(--text4)', marginLeft: 'auto' } },
                `${lastSched.tickerCount || tickers.length} tickers · ${lastSched.setupReadyCount || 0} ready · ${fmtSchedTime(lastSched.scannedAt)}`)
            : React.createElement('span', { style: { color: 'var(--text4)', marginLeft: 'auto' } }, '— none yet')
        ),
        // body
        hasData && schedOpen && React.createElement('div', {
          style: { border: '1px solid var(--line)', borderTop: 'none', borderRadius: '0 0 6px 6px', padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 2 }
        },
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginBottom: 6 } },
            `Scanned ${lastSched.tickerCount || tickers.length} tickers above $${Number(lastSched.minVolume || 0).toLocaleString('en-US')} · ${lastSched.errorCount || 0} errors`),
          tickers.length === 0
            ? React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', fontStyle: 'italic', padding: '4px 0' } }, 'No tickers recorded.')
            : tickers.map((t, i) => {
                const b = schedBadge(t.outcome, t.reason);
                return React.createElement('div', {
                  key: t.symbol + i,
                  style: { display: 'flex', alignItems: 'center', gap: 10, padding: '3px 0', borderBottom: i < tickers.length - 1 ? '1px solid var(--line-soft)' : 'none' }
                },
                  React.createElement('span', { style: { fontSize: 13, fontWeight: 600, color: 'var(--text1)', width: 72 } }, fmtSymbol(t.symbol)),
                  React.createElement('span', { style: {
                    fontSize: 9, fontWeight: 700, letterSpacing: '0.05em', padding: '2px 6px', borderRadius: 3,
                    background: b.bg, color: b.color, border: b.border, width: 58, textAlign: 'center', flexShrink: 0,
                  } }, b.label),
                  React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, t.reason || '')
                );
              })
        )
      );
    })()
  );
}


/* ===== EXPORTS ===== */
window.TriageScreen   = TriageScreen;
window.ScannerScreen  = ScannerScreen;
window.JournalScreen  = JournalScreen;
window.ValidatorScreen = ValidatorScreen;
window.ReportsScreen   = ReportsScreen;
window.TradingSettingsScreen = TradingSettingsScreen;
