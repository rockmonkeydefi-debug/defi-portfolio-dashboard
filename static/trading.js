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

function TFBadge({ tf }) {
  return React.createElement('span', {
    style: {
      background: '#1a1a2e', border: '1px solid #444', color: '#fff',
      fontSize: 11, padding: '2px 6px', borderRadius: 4,
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
  const fmt2 = (v) => (v === null || v === undefined || isNaN(v)) ? '—' : Number(v).toFixed(2);
  const targets = setup.targets || [];
  const t1 = targets[0];
  const t2 = targets[1];

  const labelStyle = { color: '#888', fontSize: 10, fontWeight: 600 };

  const level = (label, value, valueColor, rr) => React.createElement('div', null,
    React.createElement('div', { style: labelStyle }, label),
    React.createElement('div', { style: { color: valueColor, fontSize: 14, fontWeight: 600 } },
      value,
      rr ? React.createElement('span', { style: { color: '#888', fontSize: 11, fontWeight: 400, marginLeft: 6 } }, rr) : null
    )
  );

  const rationale = setup.rationale || '';
  const rationaleText = rationale.length > 120 ? rationale.slice(0, 120) + '…' : rationale;

  // --- direction-aware price bar (stop · entry · T1 · T2) ---
  const isLong = String(setup.direction || '').toUpperCase() === 'LONG';
  const entryMid = (parseFloat(setup.entryLow) + parseFloat(setup.entryHigh)) / 2;
  const pStop = { label: 'STOP', price: parseFloat(setup.stop), color: '#f87171' };
  const pEntry = { label: 'ENTRY', price: entryMid, color: '#facc15' };
  const pT1 = t1 ? { label: 'T1', price: parseFloat(t1.price), color: '#4ade80' } : null;
  const pT2 = t2 ? { label: 'T2', price: parseFloat(t2.price), color: '#4ade80' } : null;
  // LONG: stop is lowest → T2 highest. SHORT: T2 lowest → stop highest.
  const orderedPts = (isLong ? [pStop, pEntry, pT1, pT2] : [pT2, pT1, pEntry, pStop])
    .filter(p => p && !isNaN(p.price));
  const barPrices = orderedPts.map(p => p.price);
  const minP = barPrices.length ? Math.min(...barPrices) : 0;
  const maxP = barPrices.length ? Math.max(...barPrices) : 1;
  const spanP = (maxP - minP) || 1;
  const leftPct = (price) => ((price - minP) / spanP) * 100;
  const lineColor = isLong ? '#1a3a1a' : '#3a1a1a';
  let lineLeft = 0, lineWidth = 100;
  if (pStop && !isNaN(pStop.price) && pT2 && !isNaN(pT2.price)) {
    const a = leftPct(pStop.price), b = leftPct(pT2.price);
    lineLeft = Math.min(a, b);
    lineWidth = Math.abs(b - a);
  }
  const priceBar = orderedPts.length >= 2 ? React.createElement('div', {
    style: { position: 'relative', height: 4, background: '#1a1a2e', borderRadius: 2, margin: '12px 0' }
  },
    React.createElement('div', {
      style: {
        position: 'absolute', top: 0, height: 4, borderRadius: 2,
        left: `${lineLeft}%`, width: `${lineWidth}%`, background: lineColor,
      }
    }),
    orderedPts.map((p, i) => React.createElement('div', { key: i },
      React.createElement('div', {
        style: {
          position: 'absolute', top: -4, left: `${leftPct(p.price)}%`,
          transform: 'translateX(-50%)', color: p.color, fontSize: 10, lineHeight: '12px',
        }
      }, '◆'),
      React.createElement('div', {
        style: {
          position: 'absolute', top: 12, left: `${leftPct(p.price)}%`,
          transform: 'translateX(-50%)', color: p.color, fontSize: 10, whiteSpace: 'nowrap',
        }
      }, fmt2(p.price))
    ))
  ) : null;

  return React.createElement('div', {
    style: {
      background: '#0f0f1a', border: '1px solid #333', borderRadius: 8,
      padding: 16, marginBottom: 12,
    }
  },
    // header row
    React.createElement('div', {
      style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' }
    },
      React.createElement('div', { style: { display: 'flex', alignItems: 'center' } },
        React.createElement('div', {
          style: {
            width: 20, height: 20, borderRadius: '50%', background: '#222', color: '#aaa',
            fontSize: 11, display: 'flex', alignItems: 'center', justifyContent: 'center',
          }
        }, rank),
        React.createElement('span', {
          style: { fontSize: 16, fontWeight: 700, color: '#fff', margin: '0 8px' }
        }, setup.ticker),
        React.createElement(TFPairBadge, { htf: setup.htf, ltf: setup.ltf })
      ),
      React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6 } },
        React.createElement(DirBadge, { direction: setup.direction }),
        React.createElement(FreshnessPill, { tier: setup.freshness })
      )
    ),
    // entry zone row
    React.createElement('div', { style: { marginTop: 12 } },
      React.createElement('div', { style: { ...labelStyle, letterSpacing: '0.5px' } }, 'ENTRY ZONE'),
      React.createElement('div', { style: { color: '#fff', fontSize: 14, fontWeight: 600 } },
        `${fmt2(setup.entryLow)}–${fmt2(setup.entryHigh)}`)
    ),
    // levels row
    React.createElement('div', { style: { marginTop: 8, display: 'flex', gap: 24 } },
      level('STOP', fmt2(setup.stop), '#f87171', null),
      level('T1', t1 ? fmt2(t1.price) : '—', '#4ade80', t1 && t1.rr !== undefined && t1.rr !== null ? `${t1.rr}R` : null),
      level('T2', t2 ? fmt2(t2.price) : '—', '#4ade80', t2 && t2.rr !== undefined && t2.rr !== null ? `${t2.rr}R` : null)
    ),
    // direction-aware price bar
    priceBar,
    // rationale row
    React.createElement('div', {
      style: { marginTop: 10, color: '#888', fontSize: 12, fontStyle: 'italic' }
    }, rationaleText),
    // triggered row
    React.createElement('div', {
      style: { marginTop: 6, color: '#666', fontSize: 11 }
    }, `⏱ ${Math.round(setup.triggeredMins)}m ago`),
    // action buttons row
    React.createElement('div', {
      style: { display: 'flex', gap: 8, marginTop: 12 }
    },
      React.createElement('button', {
        onClick: () => { if (onSwitchTab) onSwitchTab('tt-validator'); },
        style: {
          background: '#1a1a2e', border: '1px solid #444', color: '#ccc',
          padding: '7px 14px', borderRadius: 6, fontSize: 12, cursor: 'pointer',
        }
      }, 'Validate →'),
      React.createElement('button', {
        onClick: () => setShowRiskModal(true),
        style: {
          background: '#1a3a1a', border: '1px solid #2a6a2a', color: '#4ade80',
          padding: '7px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer',
        }
      }, 'Size this trade →')
    ),
    // risk / position-size modal
    showRiskModal && React.createElement(RiskModal, {
      setup,
      onClose: () => setShowRiskModal(false),
    })
  );
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
    }, item.ticker),
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

    const actToday = React.createElement('div', null,
      sectionHeader('ACT TODAY'),
      setups.length === 0
        ? emptyState('No setups qualify right now.')
        : setups.map((s, i) => React.createElement(ActTodayCard, { key: i, setup: s, rank: i + 1, onSwitchTab }))
    );

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
window.TriageScreen   = TriageScreen;
window.JournalScreen  = JournalScreen;
window.ValidatorScreen = ValidatorScreen;
window.ReportsScreen   = ReportsScreen;
window.TradingSettingsScreen = TradingSettingsScreen;
