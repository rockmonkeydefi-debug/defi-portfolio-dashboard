/* ===== MARKET DATA SCREEN ===== */

const { useState: useMDState, useEffect: useMDEffect } = React;

function _fgCls(change) {
  return change > 0 ? 'ok' : change < 0 ? 'fail' : '';
}

// ── Price Strip ────────────────────────────────────────────────────────────
function PriceStrip({ data, onRefresh, refreshing }) {
  const prices = (data && data.prices) ? data.prices : [];
  return React.createElement('div', { className: 'tv-card', style: { padding: '12px 16px' } },
    React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 } },
      React.createElement('span', { className: 'tv-label' }, 'Prices'),
      React.createElement('button', {
        className: 'tv-btn',
        style: { fontSize: 12, padding: '3px 10px' },
        onClick: onRefresh,
        disabled: refreshing,
      }, refreshing ? 'Refreshing…' : '↻ Refresh')
    ),
    React.createElement('div', { style: { display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 4 } },
      prices.length === 0
        ? React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…')
        : prices.map(p =>
            React.createElement('div', {
              key: p.symbol,
              style: { background: 'var(--panel2)', borderRadius: 8, padding: '8px 14px', minWidth: 110, flexShrink: 0 }
            },
              React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginBottom: 2 } }, p.symbol),
              React.createElement('div', { className: 'tv-num', style: { fontSize: 15 } }, fmt(p.price_usd || 0)),
              p.change_24h != null && React.createElement('div', {
                className: _fgCls(p.change_24h),
                style: { fontSize: 12, marginTop: 2 }
              }, (p.change_24h >= 0 ? '+' : '') + fmtNum(p.change_24h, 2) + '%')
            )
          )
    )
  );
}

// ── Fear & Greed Gauge ─────────────────────────────────────────────────────
function _fearLabel(v) {
  if (v <= 25) return ['Extreme Fear', 'fail'];
  if (v <= 45) return ['Fear', 'fail'];
  if (v <= 55) return ['Neutral', 'warn'];
  if (v <= 75) return ['Greed', 'ok'];
  return ['Extreme Greed', 'ok'];
}

function FearGreedGauge({ data }) {
  const fg = data && data.fear_greed;
  if (!fg) return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-label', style: { marginBottom: 8 } }, 'Fear & Greed Index'),
    React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Not available')
  );
  const value = Number(fg.value != null ? fg.value : fg);
  const [label, cls] = _fearLabel(value);
  const pct = value / 100;
  const R = 60, cx = 80, cy = 80;
  const sweep = pct * Math.PI;
  const vEndX = cx + R * Math.cos(Math.PI - sweep);
  const vEndY = cy - R * Math.sin(Math.PI - sweep);
  const largArc = sweep > Math.PI / 2 ? 1 : 0;
  const needle = { x: cx + R * Math.cos(Math.PI - sweep), y: cy - R * Math.sin(Math.PI - sweep) };
  const bgPath = `M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy}`;
  const vPath = `M ${cx - R} ${cy} A ${R} ${R} 0 ${largArc} 1 ${vEndX} ${vEndY}`;
  const strokeColor = cls === 'ok' ? 'var(--ok)' : cls === 'fail' ? 'var(--fail)' : 'var(--warn)';
  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-label', style: { marginBottom: 12 } }, 'Fear & Greed Index'),
    React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 24 } },
      React.createElement('svg', { width: 160, height: 90, viewBox: '0 0 160 90' },
        React.createElement('path', { d: bgPath, fill: 'none', stroke: 'var(--panel3)', strokeWidth: 10, strokeLinecap: 'round' }),
        React.createElement('path', { d: vPath, fill: 'none', stroke: strokeColor, strokeWidth: 10, strokeLinecap: 'round' }),
        React.createElement('circle', { cx: needle.x, cy: needle.y, r: 6, fill: strokeColor }),
        React.createElement('text', { x: cx, y: cy, textAnchor: 'middle', fill: 'var(--text)', fontSize: 22, fontWeight: 700, fontFamily: 'Fira Code' }, value)
      ),
      React.createElement('div', null,
        React.createElement('div', { className: cls, style: { fontSize: 18, fontWeight: 700 } }, label),
        fg.timestamp && React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', marginTop: 4 } },
          'Updated: ' + new Date(fg.timestamp * 1000 || fg.timestamp).toLocaleDateString()
        )
      )
    )
  );
}

// ── BTC Macro Cycle Dashboard ──────────────────────────────────────────────
function _signalChip(signal) {
  const s = (signal || '').toLowerCase();
  const cls = s.includes('bull') ? 'ok' : s.includes('bear') ? 'fail' : 'warn';
  return React.createElement('span', { className: `tv-chip ${cls}`, style: { fontSize: 11, padding: '2px 8px' } }, signal || 'Neutral');
}

function MacroDashboard({ data, loading, error }) {
  const inner = () => {
    if (loading) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…');
    if (error || !data) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, error || 'Not available');
    const indicators = data.indicators || [];
    const score = data.composite_score != null ? data.composite_score : data.score;
    return React.createElement('div', null,
      React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse' } },
        React.createElement('thead', null,
          React.createElement('tr', null,
            ['Indicator', 'Value', 'Signal'].map((h, i) =>
              React.createElement('th', { key: h, style: { textAlign: i === 0 ? 'left' : 'right', fontSize: 11, color: 'var(--text4)', padding: '0 0 8px', fontWeight: 500 } }, h)
            )
          )
        ),
        React.createElement('tbody', null,
          indicators.map((ind, i) =>
            React.createElement('tr', { key: i, style: { borderTop: '1px solid var(--line)' } },
              React.createElement('td', { style: { padding: '7px 0', fontSize: 13, color: 'var(--text2)' } }, ind.name),
              React.createElement('td', { style: { padding: '7px 0', textAlign: 'right', fontFamily: 'Fira Code', fontSize: 13 } }, ind.value != null ? ind.value : '—'),
              React.createElement('td', { style: { padding: '7px 0 7px 8px', textAlign: 'right' } }, _signalChip(ind.signal))
            )
          )
        )
      ),
      score != null && React.createElement('div', { style: { marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--line)', display: 'flex', alignItems: 'center', gap: 12 } },
        React.createElement('span', { style: { fontSize: 13, color: 'var(--text2)' } }, 'Composite Score'),
        React.createElement('span', { className: 'tv-num', style: { fontSize: 17 } }, fmtNum(score, 1)),
        _signalChip(data.composite_signal || data.signal)
      )
    );
  };
  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-label', style: { marginBottom: 12 } }, 'BTC Macro Cycle Dashboard'),
    inner()
  );
}

// ── Lend / Borrow Stats ────────────────────────────────────────────────────
function LendBorrowStats({ data, loading, error }) {
  const inner = () => {
    if (loading) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…');
    if (error || !data) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, error || 'Not available');
    const lend = data.lending || [];
    const borrow = data.borrowing || data.borrow || [];
    function RateTable({ title, rows, rateKey }) {
      return React.createElement('div', { style: { flex: 1 } },
        React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 } }, title),
        React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1fr auto auto', gap: '0 12px', fontSize: 13 } },
          React.createElement('div', { style: { color: 'var(--text4)', fontSize: 11, paddingBottom: 4 } }, 'Token'),
          React.createElement('div', { style: { color: 'var(--text4)', fontSize: 11, paddingBottom: 4, textAlign: 'right' } }, 'APY'),
          React.createElement('div', { style: { color: 'var(--text4)', fontSize: 11, paddingBottom: 4, textAlign: 'right' } }, 'Protocol'),
          ...rows.map((r, i) => [
            React.createElement('div', { key: `t${i}`, style: { color: 'var(--text2)', padding: '3px 0', borderTop: '1px solid var(--line)' } }, r.token || r.symbol),
            React.createElement('div', { key: `a${i}`, className: 'tv-num ok', style: { padding: '3px 0', borderTop: '1px solid var(--line)', textAlign: 'right', fontSize: 13 } },
              fmtNum((r[rateKey] || r.apy || 0) * 100, 2) + '%'
            ),
            React.createElement('div', { key: `p${i}`, style: { color: 'var(--text4)', padding: '3px 0', borderTop: '1px solid var(--line)', textAlign: 'right', fontSize: 12 } }, r.protocol || '—'),
          ]).flat()
        )
      );
    }
    return React.createElement('div', { style: { display: 'flex', gap: 32 } },
      React.createElement(RateTable, { title: 'Lending', rows: lend, rateKey: 'supply_apy' }),
      React.createElement('div', { style: { width: 1, background: 'var(--line)' } }),
      React.createElement(RateTable, { title: 'Borrowing', rows: borrow, rateKey: 'borrow_apy' })
    );
  };
  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-label', style: { marginBottom: 16 } }, 'Lend / Borrow Rates'),
    inner()
  );
}

// ── Stablecoin Supply Chart ────────────────────────────────────────────────
function StablecoinChart({ data, loading, error }) {
  const inner = () => {
    if (loading) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…');
    const points = (data && data.history) ? data.history : (Array.isArray(data) ? data : []);
    if (error || !points.length) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, error || 'Data unavailable');
    const vals = points.map(p => p.total || p.value || (Array.isArray(p) ? p[1] : 0) || 0);
    const dates = points.map(p => p.date || (Array.isArray(p) ? p[0] : '') || '');
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const range = max - min || 1;
    const W = 600, H = 120, PAD = 40;
    const pts = vals.map((v, i) => [
      PAD + (i / Math.max(vals.length - 1, 1)) * (W - PAD * 2),
      H - PAD / 2 - ((v - min) / range) * (H - PAD),
    ]);
    const pathD = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ');
    const fillD = `${pathD} L ${pts[pts.length - 1][0].toFixed(1)} ${H} L ${pts[0][0].toFixed(1)} ${H} Z`;
    const yLabels = [min, min + range / 2, max];
    return React.createElement('div', { style: { overflowX: 'auto' } },
      React.createElement('svg', { width: W, height: H + 20, viewBox: `0 0 ${W} ${H + 20}`, style: { display: 'block' } },
        React.createElement('path', { d: fillD, fill: 'var(--accent)', opacity: 0.08 }),
        React.createElement('path', { d: pathD, fill: 'none', stroke: 'var(--accent)', strokeWidth: 2 }),
        yLabels.map((v, i) => {
          const y = H - PAD / 2 - (i / 2) * (H - PAD);
          return React.createElement('text', { key: i, x: 2, y: y + 4, fontSize: 10, fill: 'var(--text4)', fontFamily: 'Fira Code' }, (v / 1e9).toFixed(0) + 'B');
        }),
        React.createElement('text', { x: PAD, y: H + 18, fontSize: 10, fill: 'var(--text4)', fontFamily: 'Fira Code' }, dates[0] || ''),
        dates.length > 1 && React.createElement('text', { x: W - PAD, y: H + 18, fontSize: 10, fill: 'var(--text4)', textAnchor: 'end', fontFamily: 'Fira Code' }, dates[dates.length - 1] || '')
      )
    );
  };
  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-label', style: { marginBottom: 12 } }, 'Stablecoin Supply'),
    inner()
  );
}

// ── Main Screen ────────────────────────────────────────────────────────────
function MarketDataScreen({ hideValues }) {
  const [marketData, setMarketData] = useMDState(null);
  const [marketLoading, setMarketLoading] = useMDState(true);
  const [macroData, setMacroData] = useMDState(null);
  const [macroLoading, setMacroLoading] = useMDState(true);
  const [macroError, setMacroError] = useMDState(null);
  const [lendData, setLendData] = useMDState(null);
  const [lendLoading, setLendLoading] = useMDState(true);
  const [lendError, setLendError] = useMDState(null);
  const [scData, setScData] = useMDState(null);
  const [scLoading, setScLoading] = useMDState(true);
  const [scError, setScError] = useMDState(null);
  const [refreshing, setRefreshing] = useMDState(false);

  function fetchMarket() {
    setMarketLoading(true);
    api('/api/market-data')
      .then(d => setMarketData(d))
      .catch(() => setMarketData(null))
      .finally(() => setMarketLoading(false));
  }

  useMDEffect(() => {
    fetchMarket();
    api('/api/market/macro')
      .then(d => setMacroData(d))
      .catch(() => setMacroError('Not available'))
      .finally(() => setMacroLoading(false));
    api('/api/market/lending-rates')
      .then(d => setLendData(d))
      .catch(() => setLendError('Not available'))
      .finally(() => setLendLoading(false));
    api('/api/market/stablecoin-supply')
      .then(d => setScData(d))
      .catch(() => setScError('Not available'))
      .finally(() => setScLoading(false));
  }, []);

  async function handleRefresh() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await api('/api/market-data/refresh', { method: 'POST' });
    } catch (e) {}
    fetchMarket();
    setRefreshing(false);
  }

  return React.createElement('div', { style: { padding: 24, display: 'flex', flexDirection: 'column', gap: 20 } },
    marketLoading
      ? React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
          React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading market data…')
        )
      : React.createElement(PriceStrip, { data: marketData, onRefresh: handleRefresh, refreshing }),
    React.createElement(FearGreedGauge, { data: marketData }),
    React.createElement(MacroDashboard, { data: macroData, loading: macroLoading, error: macroError }),
    React.createElement(LendBorrowStats, { data: lendData, loading: lendLoading, error: lendError }),
    React.createElement(StablecoinChart, { data: scData, loading: scLoading, error: scError })
  );
}

window.MarketDataScreen = MarketDataScreen;
