/* ===== MARKET DATA SCREEN ===== */

const { useState: useMDState, useEffect: useMDEffect } = React;

function _fgCls(change) {
  return change > 0 ? 'ok' : change < 0 ? 'fail' : '';
}

function _valCls(val) {
  const n = parseFloat(String(val).replace(/[^0-9.\-]/g, ''));
  if (isNaN(n)) return '';
  return n > 0 ? 'ok' : n < 0 ? 'fail' : '';
}

function _fmtCompact(v) {
  if (v == null || isNaN(v)) return '—';
  const n = Number(v);
  if (n >= 1e12) return '$' + (n / 1e12).toFixed(2) + 'T';
  if (n >= 1e9)  return '$' + (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6)  return '$' + (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3)  return '$' + (n / 1e3).toFixed(0) + 'K';
  return '$' + n.toFixed(2);
}

// ── Price Strip ────────────────────────────────────────────────────────────
function PriceStrip({ data, onRefresh, refreshing }) {
  const s = (data && data.snapshot) ? data.snapshot : null;

  const coins = [
    { symbol: 'BTC', price: s && s.btc_price, change: s && s.btc_24h_change },
    { symbol: 'ETH', price: s && s.eth_price, change: s && s.eth_24h_change },
    { symbol: 'SOL', price: s && s.sol_price, change: null },
    { symbol: 'SUI', price: s && s.sui_price, change: null },
    { symbol: 'TAO', price: s && s.tao_price, change: null },
  ];

  const summaryChips = s ? [
    { label: 'Market Cap', value: _fmtCompact(s.total_market_cap) },
    { label: 'BTC Dom', value: s.btc_dominance != null ? fmtNum(s.btc_dominance, 1) + '%' : '—' },
    { label: 'Stablecoins', value: _fmtCompact(s.stablecoin_supply) },
  ] : [];

  return React.createElement('div', { className: 'tv-card', style: { padding: '12px 16px' } },
    React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 } },
      React.createElement('span', { className: 'tv-label' }, 'Prices'),
      React.createElement('button', {
        className: 'tv-btn', style: { fontSize: 12, padding: '3px 10px' },
        onClick: onRefresh, disabled: refreshing,
      }, refreshing ? 'Refreshing…' : '↻ Refresh')
    ),
    React.createElement('div', { style: { display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 4 } },
      !s
        ? React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…')
        : coins.map(p =>
            React.createElement('div', {
              key: p.symbol,
              style: { background: 'var(--panel2)', borderRadius: 8, padding: '8px 14px', minWidth: 110, flexShrink: 0 }
            },
              React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', marginBottom: 2 } }, p.symbol),
              React.createElement('div', { className: 'tv-num', style: { fontSize: 15 } },
                p.price != null ? fmt(p.price) : '—'
              ),
              p.change != null && React.createElement('div', {
                className: _fgCls(p.change), style: { fontSize: 12, marginTop: 2 }
              }, (p.change >= 0 ? '+' : '') + fmtNum(p.change, 2) + '%')
            )
          )
    ),
    summaryChips.length > 0 && React.createElement('div', { style: { display: 'flex', gap: 16, marginTop: 10, flexWrap: 'wrap' } },
      summaryChips.map(c =>
        React.createElement('div', { key: c.label, style: { display: 'flex', alignItems: 'center', gap: 6 } },
          React.createElement('span', { style: { fontSize: 11, color: 'var(--text4)' } }, c.label),
          React.createElement('span', { className: 'tv-num', style: { fontSize: 13 } }, c.value)
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

function FGSparkline({ history }) {
  if (!history || history.length < 2) return null;
  const W = 160, H = 28;
  const min = Math.min(...history);
  const max = Math.max(...history);
  const range = max - min || 1;
  const pts = history.map((v, i) => [
    (i / (history.length - 1)) * W,
    H - ((v - min) / range) * H,
  ]);
  const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ');
  return React.createElement('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, style: { display: 'block', marginTop: 8, opacity: 0.7 } },
    React.createElement('path', { d, fill: 'none', stroke: 'var(--accent)', strokeWidth: 1.5 })
  );
}

function FearGreedGauge({ data }) {
  const s = data && data.snapshot;
  const history = data && data.fg_history;
  const value = s && s.fear_greed_index != null ? Number(s.fear_greed_index) : null;

  if (value === null) return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-label', style: { marginBottom: 8 } }, 'Fear & Greed Index'),
    React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Not available')
  );

  const [label, cls] = _fearLabel(value);
  const pct = value / 100;
  const R = 60, cx = 80, cy = 75;
  const sweep = pct * Math.PI;
  const vEndX = cx + R * Math.cos(Math.PI - sweep);
  const vEndY = cy - R * Math.sin(Math.PI - sweep);
  const largArc = sweep > Math.PI / 2 ? 1 : 0;
  const bgPath = `M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy}`;
  const vPath   = `M ${cx - R} ${cy} A ${R} ${R} 0 ${largArc} 1 ${vEndX} ${vEndY}`;
  const strokeColor = cls === 'ok' ? 'var(--ok)' : cls === 'fail' ? 'var(--fail)' : 'var(--warn)';

  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-label', style: { marginBottom: 12 } }, 'Fear & Greed Index'),
    React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 24 } },
      React.createElement('div', null,
        React.createElement('svg', { width: 160, height: 80, viewBox: '0 0 160 80' },
          React.createElement('path', { d: bgPath, fill: 'none', stroke: 'var(--panel3)', strokeWidth: 10, strokeLinecap: 'round' }),
          React.createElement('path', { d: vPath,  fill: 'none', stroke: strokeColor, strokeWidth: 10, strokeLinecap: 'round' }),
          React.createElement('circle', { cx: vEndX, cy: vEndY, r: 6, fill: strokeColor }),
          React.createElement('text', { x: cx, y: cy - 6, textAnchor: 'middle', fill: 'var(--text)', fontSize: 22, fontWeight: 700, fontFamily: 'Fira Code' }, value)
        ),
        React.createElement(FGSparkline, { history })
      ),
      React.createElement('div', null,
        React.createElement('div', { className: cls, style: { fontSize: 18, fontWeight: 700 } }, label),
        React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', marginTop: 4 } }, '30-day trend →')
      )
    )
  );
}

// ── BTC Macro Cycle Dashboard ──────────────────────────────────────────────
function MacroDashboard({ macroData, macroLoading, macroError, snapshot }) {
  const inner = () => {
    if (macroLoading) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…');

    const apiRows = (macroData && macroData.rows) ? macroData.rows : [];
    const llmText = macroData && macroData.llm_text;

    const snapshotRows = snapshot ? [
      { metric: 'BTC Price',        value: snapshot.btc_price != null ? fmt(snapshot.btc_price) : '—',                    comment: snapshot.btc_200d_ma != null ? '200d MA: ' + fmt(snapshot.btc_200d_ma) : '' },
      { metric: 'BTC 7d Return',    value: snapshot.btc_return_7d != null ? fmtNum(snapshot.btc_return_7d, 2) + '%' : '—', comment: '' },
      { metric: 'BTC 30d Return',   value: snapshot.btc_return_30d != null ? fmtNum(snapshot.btc_return_30d, 2) + '%' : '—', comment: '' },
      { metric: 'BTC Dominance',    value: snapshot.btc_dominance != null ? fmtNum(snapshot.btc_dominance, 1) + '%' : '—', comment: '' },
      { metric: 'BTC Funding Rate', value: snapshot.btc_funding_rate != null ? fmtNum(snapshot.btc_funding_rate, 4) : '—', comment: '' },
      { metric: 'ETH/BTC Ratio',    value: snapshot.eth_btc_ratio != null ? fmtNum(snapshot.eth_btc_ratio, 4) : '—',       comment: '' },
      { metric: 'Total DeFi TVL',   value: snapshot.total_defi_tvl != null ? _fmtCompact(snapshot.total_defi_tvl) : '—',   comment: '' },
    ] : [];

    const allRows = [...snapshotRows, ...apiRows];

    if (!allRows.length && !llmText) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, macroError || 'Not available');

    return React.createElement('div', null,
      allRows.length > 0 && React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse' } },
        React.createElement('thead', null,
          React.createElement('tr', null,
            ['Metric', 'Value', 'Note'].map((h, i) =>
              React.createElement('th', { key: h, style: { textAlign: i === 0 ? 'left' : i === 1 ? 'right' : 'left', fontSize: 11, color: 'var(--text4)', padding: '0 0 8px', fontWeight: 500, paddingLeft: i === 2 ? 16 : 0 } }, h)
            )
          )
        ),
        React.createElement('tbody', null,
          allRows.map((row, i) => {
            const valStr = row.value != null ? String(row.value) : '—';
            const vcls = _valCls(valStr);
            return React.createElement('tr', { key: i, style: { borderTop: '1px solid var(--line)' } },
              React.createElement('td', { style: { padding: '7px 0', fontSize: 13, color: 'var(--text2)' } }, row.metric),
              React.createElement('td', { style: { padding: '7px 0', textAlign: 'right', fontFamily: 'Fira Code', fontSize: 13, color: vcls ? undefined : 'var(--text)', paddingRight: 0 }, className: vcls || undefined }, valStr),
              React.createElement('td', { style: { padding: '7px 0 7px 16px', fontSize: 12, color: 'var(--text4)' } }, row.comment || '')
            );
          })
        )
      ),
      llmText && React.createElement('div', { style: { marginTop: 16, paddingTop: 16, borderTop: allRows.length ? '1px solid var(--line)' : 'none', fontSize: 13, color: 'var(--text2)', lineHeight: 1.7, whiteSpace: 'pre-wrap' } }, llmText)
    );
  };

  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-label', style: { marginBottom: 12 } }, 'BTC Macro Cycle Dashboard'),
    inner()
  );
}

// ── LP Pool Stats ──────────────────────────────────────────────────────────
function LPPoolStats({ data, loading, error }) {
  const inner = () => {
    if (loading) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…');
    const poolsObj = data && data.lp_pools;
    if (error || !poolsObj) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, error || 'Not available');
    const pools = Object.values(poolsObj).sort((a, b) => (b.tvl || 0) - (a.tvl || 0));
    if (!pools.length) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'No pool data');

    return React.createElement('div', { style: { overflowX: 'auto' } },
      React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr', gap: '0 16px', minWidth: 480 } },
        ['Pair', 'Chain', 'TVL', '24h Volume', 'APY'].map((h, i) =>
          React.createElement('div', { key: h, style: { fontSize: 11, color: 'var(--text4)', paddingBottom: 8, textAlign: i >= 2 ? 'right' : 'left' } }, h)
        ),
        ...pools.map((p, i) => [
          React.createElement('div', { key: `n${i}`, style: { padding: '5px 0', borderTop: '1px solid var(--line)', fontSize: 13, color: 'var(--text2)' } }, p.asset || '—'),
          React.createElement('div', { key: `c${i}`, style: { padding: '5px 0', borderTop: '1px solid var(--line)', fontSize: 12, color: 'var(--text4)' } }, p.chain || '—'),
          React.createElement('div', { key: `t${i}`, className: 'tv-num', style: { padding: '5px 0', borderTop: '1px solid var(--line)', fontSize: 13, textAlign: 'right' } }, _fmtCompact(p.tvl)),
          React.createElement('div', { key: `v${i}`, className: 'tv-num', style: { padding: '5px 0', borderTop: '1px solid var(--line)', fontSize: 13, textAlign: 'right' } }, _fmtCompact(p.vol1d)),
          React.createElement('div', { key: `a${i}`, className: 'tv-num ok', style: { padding: '5px 0', borderTop: '1px solid var(--line)', fontSize: 13, textAlign: 'right' } },
            p.apyBase != null ? fmtNum(p.apyBase, 2) + '%' : '—'
          ),
        ]).flat()
      )
    );
  };

  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-label', style: { marginBottom: 16 } }, 'LP Pool Stats'),
    inner()
  );
}

// ── Stablecoin Supply Bars ─────────────────────────────────────────────────
function StablecoinBars({ data, loading, error }) {
  const inner = () => {
    if (loading) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…');

    const arr = Array.isArray(data) ? data : [];
    if (error || !arr.length) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, error || 'Data unavailable');

    const rows = arr
      .map(item => ({
        name: item.name || '?',
        value: (item.totalCirculatingUSD && item.totalCirculatingUSD.peggedUSD) || 0,
      }))
      .filter(r => r.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 15);

    if (!rows.length) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'No data');

    const total = rows.reduce((s, r) => s + r.value, 0);
    const maxVal = rows[0].value;
    const BAR_W = 280;

    return React.createElement('div', null,
      React.createElement('div', { style: { marginBottom: 14 } },
        React.createElement('span', { style: { fontSize: 12, color: 'var(--text4)' } }, 'Total (top 15 chains)  '),
        React.createElement('span', { className: 'tv-num', style: { fontSize: 18 } }, _fmtCompact(total))
      ),
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
        rows.map((r, i) => {
          const barPx = Math.max(2, (r.value / maxVal) * BAR_W);
          return React.createElement('div', { key: r.name, style: { display: 'flex', alignItems: 'center', gap: 10 } },
            React.createElement('div', { style: { fontSize: 12, color: 'var(--text2)', width: 120, flexShrink: 0, textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' } }, r.name),
            React.createElement('svg', { width: BAR_W, height: 16, viewBox: `0 0 ${BAR_W} 16`, style: { flexShrink: 0 } },
              React.createElement('rect', { x: 0, y: 3, width: BAR_W, height: 10, rx: 3, fill: 'var(--panel3)' }),
              React.createElement('rect', { x: 0, y: 3, width: barPx, height: 10, rx: 3, fill: 'var(--accent)', opacity: 0.75 })
            ),
            React.createElement('div', { className: 'tv-num', style: { fontSize: 12, color: 'var(--text2)', minWidth: 60 } }, _fmtCompact(r.value))
          );
        })
      )
    );
  };

  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-label', style: { marginBottom: 14 } }, 'Stablecoin Supply by Chain'),
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
    api('/api/market/stablecoin-supply')
      .then(d => setScData(d))
      .catch(() => setScError('Not available'))
      .finally(() => setScLoading(false));
  }, []);

  async function handleRefresh() {
    if (refreshing) return;
    setRefreshing(true);
    try { await api('/api/market-data/refresh', { method: 'POST' }); } catch (e) {}
    fetchMarket();
    setRefreshing(false);
  }

  const snapshot = marketData && marketData.snapshot;

  return React.createElement('div', { style: { padding: 24, display: 'flex', flexDirection: 'column', gap: 20 } },
    marketLoading
      ? React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
          React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading market data…')
        )
      : React.createElement(PriceStrip, { data: marketData, onRefresh: handleRefresh, refreshing }),
    React.createElement(FearGreedGauge, { data: marketData }),
    React.createElement(MacroDashboard, { macroData, macroLoading, macroError, snapshot }),
    React.createElement(LPPoolStats, { data: marketData, loading: marketLoading, error: !marketData ? 'Not available' : null }),
    React.createElement(StablecoinBars, { data: scData, loading: scLoading, error: scError })
  );
}

window.MarketDataScreen = MarketDataScreen;
