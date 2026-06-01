/* ===== MARKET DATA SCREEN ===== */

const { useState: useMDState, useEffect: useMDEffect } = React;

// ── Helpers ────────────────────────────────────────────────────────────────
function fmtB(n) {
  if (n == null || isNaN(Number(n))) return '—';
  const v = Number(n);
  if (Math.abs(v) >= 1e12) return '$' + (v / 1e12).toFixed(2) + 'T';
  if (Math.abs(v) >= 1e9)  return '$' + (v / 1e9).toFixed(2) + 'B';
  if (Math.abs(v) >= 1e6)  return '$' + (v / 1e6).toFixed(1) + 'M';
  if (Math.abs(v) >= 1e3)  return '$' + (v / 1e3).toFixed(0) + 'K';
  return '$' + v.toFixed(2);
}

function fmtPct(n, digits) {
  if (n == null || isNaN(Number(n))) return { text: '—', cls: '' };
  const v = Number(n);
  const d = digits != null ? digits : 2;
  return { text: (v >= 0 ? '+' : '') + v.toFixed(d) + '%', cls: v > 0 ? 'ok' : v < 0 ? 'fail' : '' };
}

function chainBadge(chain) {
  const c = (chain || '').toLowerCase();
  let bg = 'var(--adapt)';
  if (c === 'ethereum' || c === 'eth') bg = '#1a6af7';
  else if (c === 'arbitrum' || c === 'arb') bg = '#12aaff';
  else if (c === 'base') bg = '#2151f5';
  else if (c === 'optimism' || c === 'opt') bg = '#ff0420';
  else if (c === 'polygon' || c === 'pol') bg = '#8247e5';
  return React.createElement('span', {
    style: { background: bg, color: '#fff', fontSize: 10, padding: '2px 7px', borderRadius: 4, fontWeight: 600, letterSpacing: '0.03em', flexShrink: 0 }
  }, chain || '—');
}

function StatRow({ label, children, style: extraStyle }) {
  return React.createElement('div', {
    style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0', borderTop: '1px solid var(--line)', ...extraStyle }
  },
    React.createElement('span', { style: { fontSize: 12, color: 'var(--text4)' } }, label),
    React.createElement('span', { style: { fontSize: 13, fontFamily: 'Fira Code' } }, children)
  );
}

function CardHeader({ icon, title }) {
  return React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 10 } },
    icon ? icon + '  ' + title : title
  );
}

// ── Row 1: Action Bar ──────────────────────────────────────────────────────
function ActionBar({ snapshot, onRefresh, refreshing, setActiveTab }) {
  const ts = snapshot && snapshot.timestamp;
  let tsLabel = '—';
  if (ts) {
    try {
      const d = new Date(typeof ts === 'number' ? ts * 1000 : ts);
      const dd = String(d.getDate()).padStart(2, '0');
      const mm = String(d.getMonth() + 1).padStart(2, '0');
      const yyyy = d.getFullYear();
      const hh = String(d.getHours()).padStart(2, '0');
      const mi = String(d.getMinutes()).padStart(2, '0');
      tsLabel = `${dd}/${mm}/${yyyy} ${hh}:${mi}`;
    } catch (e) { tsLabel = String(ts); }
  }
  return React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 4 } },
    React.createElement('button', {
      className: 'tv-btn primary',
      style: { fontSize: 13, padding: '6px 16px' },
      onClick: onRefresh,
      disabled: refreshing,
    }, refreshing ? '↺ Refreshing…' : '↺ Live Data'),
    React.createElement('button', {
      className: 'tv-btn',
      style: { fontSize: 13, padding: '6px 16px', background: '#1a4fa0', color: '#fff', border: 'none' },
      onClick: () => setActiveTab && setActiveTab('aibrief'),
    }, '+ AI Daily Brief'),
    React.createElement('span', { style: { fontSize: 12, color: 'var(--text4)', marginLeft: 4 } }, 'Last Updated: ' + tsLabel)
  );
}

// ── Row 2 Card 1: Bitcoin ──────────────────────────────────────────────────
function BitcoinCard({ s }) {
  const price = s && s.btc_price;
  const change24h = fmtPct(s && s.btc_24h_change);
  const ma200 = s && s.btc_200d_ma;
  const maDelta = (price != null && ma200 != null) ? price - ma200 : null;
  const maPct   = (price != null && ma200 != null && ma200 > 0) ? ((price - ma200) / ma200 * 100) : null;
  const maAbove  = price != null && ma200 != null && price >= ma200;
  const ret7d    = fmtPct(s && s.btc_return_7d);
  const ret30d   = fmtPct(s && s.btc_return_30d);
  const vol30    = s && s.btc_vol_30d;
  const range14  = s && s.btc_range_14d;

  return React.createElement('div', { className: 'tv-card', style: { flex: 1, padding: 18 } },
    React.createElement(CardHeader, { icon: '₿', title: 'Bitcoin' }),
    React.createElement('div', { className: 'tv-num', style: { fontSize: 26, color: 'var(--text)', marginBottom: 2 } },
      price != null ? fmt(price) : '—'
    ),
    React.createElement('div', { className: change24h.cls, style: { fontSize: 13, marginBottom: 10 } },
      change24h.text + ' (24h)'
    ),
    React.createElement(StatRow, { label: 'Dominance' },
      React.createElement('span', { style: { color: 'var(--text)' } }, s && s.btc_dominance != null ? fmtNum(s.btc_dominance, 1) + '%' : '—')
    ),
    React.createElement(StatRow, { label: '200D MA' },
      React.createElement('span', { className: maAbove ? 'ok' : 'fail' },
        ma200 != null ? fmt(ma200) : '—',
        maDelta != null ? React.createElement('span', { style: { fontSize: 11, marginLeft: 6 } },
          '(' + (maDelta >= 0 ? '+' : '') + fmtNum(maDelta, 0) + ', ' + (maPct >= 0 ? '+' : '') + fmtNum(maPct, 1) + '%)'
        ) : null
      )
    ),
    React.createElement(StatRow, { label: '7d Return' },
      React.createElement('span', { className: ret7d.cls }, ret7d.text)
    ),
    React.createElement(StatRow, { label: '30d Return' },
      React.createElement('span', { className: ret30d.cls }, ret30d.text)
    ),
    React.createElement(StatRow, { label: '30d Vol' },
      React.createElement('span', { className: vol30 != null && vol30 < 30 ? 'ok' : '' },
        vol30 != null ? (vol30 < 30 ? 'Low (' + fmtNum(vol30, 1) + '%)' : fmtNum(vol30, 1) + '%') : '—'
      )
    ),
    React.createElement(StatRow, { label: '14d Range' },
      React.createElement('span', { style: { color: 'var(--text)' } }, range14 != null ? fmtNum(range14, 1) + '%' : '—')
    )
  );
}

// ── Row 2 Card 2: Ethereum ─────────────────────────────────────────────────
function EthereumCard({ s }) {
  const price    = s && s.eth_price;
  const change24h = fmtPct(s && s.eth_24h_change);
  const ret7d    = fmtPct(s && s.eth_return_7d);
  const ret30d   = fmtPct(s && s.eth_return_30d);
  const vol30    = s && s.eth_vol_30d;
  const range14  = s && s.eth_range_14d;

  return React.createElement('div', { className: 'tv-card', style: { flex: 1, padding: 18 } },
    React.createElement(CardHeader, { icon: 'Ξ', title: 'Ethereum' }),
    React.createElement('div', { className: 'tv-num', style: { fontSize: 26, color: 'var(--text)', marginBottom: 2 } },
      price != null ? fmt(price) : '—'
    ),
    React.createElement('div', { className: change24h.cls, style: { fontSize: 13, marginBottom: 10 } },
      change24h.text + ' (24h)'
    ),
    React.createElement(StatRow, { label: 'Dominance' },
      React.createElement('span', { style: { color: 'var(--text)' } }, s && s.eth_dominance != null ? fmtNum(s.eth_dominance, 1) + '%' : '—')
    ),
    React.createElement(StatRow, { label: 'ETH/BTC' },
      React.createElement('span', { style: { color: 'var(--text)' } }, s && s.eth_btc_ratio != null ? fmtNum(s.eth_btc_ratio, 4) : '—')
    ),
    React.createElement(StatRow, { label: '7d Return' },
      React.createElement('span', { className: ret7d.cls }, ret7d.text)
    ),
    React.createElement(StatRow, { label: '30d Return' },
      React.createElement('span', { className: ret30d.cls }, ret30d.text)
    ),
    React.createElement(StatRow, { label: '30d Vol' },
      React.createElement('span', { className: vol30 != null && vol30 < 30 ? 'ok' : '' },
        vol30 != null ? (vol30 < 30 ? 'Low (' + fmtNum(vol30, 1) + '%)' : fmtNum(vol30, 1) + '%') : '—'
      )
    ),
    React.createElement(StatRow, { label: '14d Range' },
      React.createElement('span', { style: { color: 'var(--text)' } }, range14 != null ? fmtNum(range14, 1) + '%' : '—')
    )
  );
}

// ── Row 2 Card 3: Fear & Greed ─────────────────────────────────────────────
function fearZone(v) {
  if (v <= 25) return { label: 'Extreme Fear', color: '#e03d3d' };
  if (v <= 45) return { label: 'Fear',         color: '#e07c3d' };
  if (v <= 55) return { label: 'Neutral',      color: '#d4b400' };
  if (v <= 75) return { label: 'Greed',        color: '#7abf5e' };
  return              { label: 'Extreme Greed', color: '#3daf5e' };
}

function FearGreedCard({ s, fgHistory }) {
  const value = s && s.fear_greed_index != null ? Number(s.fear_greed_index) : null;
  const hist  = Array.isArray(fgHistory) ? fgHistory : [];

  const avg7  = hist.length >= 7  ? hist.slice(-7).reduce((a, b) => a + b, 0) / 7  : null;
  const avg30 = hist.length >= 30 ? hist.slice(-30).reduce((a, b) => a + b, 0) / 30 : (hist.length ? hist.reduce((a, b) => a + b, 0) / hist.length : null);
  const trend = hist.length >= 2 ? hist[hist.length - 1] - hist[0] : null;

  const zone  = value != null ? fearZone(value) : null;
  const R = 56, cx = 70, cy = 68;

  const ArcGauge = () => {
    if (value === null) return React.createElement('div', { style: { height: 80, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text4)', fontSize: 13 } }, '—');
    const pct   = value / 100;
    const sweep = pct * Math.PI;
    const ex    = cx + R * Math.cos(Math.PI - sweep);
    const ey    = cy - R * Math.sin(Math.PI - sweep);
    const large = sweep > Math.PI / 2 ? 1 : 0;
    const bg    = `M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy}`;
    const arc   = `M ${cx - R} ${cy} A ${R} ${R} 0 ${large} 1 ${ex} ${ey}`;
    return React.createElement('svg', { width: 140, height: 76, viewBox: '0 0 140 76', style: { display: 'block', margin: '0 auto' } },
      React.createElement('path', { d: bg,  fill: 'none', stroke: 'var(--panel3)', strokeWidth: 9, strokeLinecap: 'round' }),
      React.createElement('path', { d: arc, fill: 'none', stroke: zone.color, strokeWidth: 9, strokeLinecap: 'round' }),
      React.createElement('circle', { cx: ex, cy: ey, r: 5, fill: zone.color }),
      React.createElement('text', { x: cx, y: cy - 2, textAnchor: 'middle', fontSize: 20, fontWeight: 700, fontFamily: 'Fira Code', fill: 'var(--text)' }, value)
    );
  };

  return React.createElement('div', { className: 'tv-card', style: { flex: 1, padding: 18 } },
    React.createElement(CardHeader, { title: 'Fear & Greed' }),
    React.createElement(ArcGauge),
    zone && React.createElement('div', { style: { textAlign: 'center', fontSize: 14, fontWeight: 600, color: zone.color, marginTop: 4, marginBottom: 10 } },
      value + ' — ' + zone.label
    ),
    React.createElement(StatRow, { label: '7d Avg' },
      React.createElement('span', { style: { color: 'var(--text)' } }, avg7 != null ? fmtNum(avg7, 1) : '—')
    ),
    React.createElement(StatRow, { label: '30d Avg' },
      React.createElement('span', { style: { color: 'var(--text)' } }, avg30 != null ? fmtNum(avg30, 1) : '—')
    ),
    React.createElement(StatRow, { label: 'Trend' },
      trend != null
        ? React.createElement('span', { className: trend > 0 ? 'ok' : trend < 0 ? 'fail' : '' },
            trend > 0 ? '↑ Rising' : trend < 0 ? '↓ Declining' : '→ Flat'
          )
        : React.createElement('span', { style: { color: 'var(--text4)' } }, '—')
    )
  );
}

// ── Row 2 Card 4: Macro ────────────────────────────────────────────────────
function MacroCard({ macroData, macroLoading }) {
  const rows = (macroData && macroData.rows) ? macroData.rows : [];

  function valColor(value, comment) {
    const vs = String(value || '');
    const cs = String(comment || '').toLowerCase();
    if (vs.includes('-')) return 'var(--fail)';
    if (cs.includes('bullish') || cs.includes('expanding')) return 'var(--ok)';
    return 'var(--text3)';
  }

  const inner = () => {
    if (macroLoading) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading…');
    if (!rows.length) return React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Not available');
    return React.createElement('div', { style: { overflowY: 'auto', maxHeight: 280 } },
      React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: '0 10px', fontSize: 11, color: 'var(--text4)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 } },
        React.createElement('div', null, 'Metric'),
        React.createElement('div', { style: { textAlign: 'right' } }, 'Value'),
        React.createElement('div', null, 'Comment')
      ),
      rows.map((r, i) =>
        React.createElement('div', { key: i, style: { display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: '0 10px', borderTop: '1px solid var(--line)', padding: '5px 0', alignItems: 'start' } },
          React.createElement('div', { style: { fontSize: 12, color: 'var(--text2)' } }, r.metric),
          React.createElement('div', { style: { fontSize: 12, fontFamily: 'Fira Code', color: valColor(r.value, r.comment), textAlign: 'right', whiteSpace: 'nowrap' } }, r.value != null ? String(r.value) : '—'),
          React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)', lineHeight: 1.4 } }, r.comment || '')
        )
      )
    );
  };

  return React.createElement('div', { className: 'tv-card', style: { flex: 1, padding: 18, overflow: 'hidden' } },
    React.createElement(CardHeader, { title: 'Macro' }),
    inner()
  );
}

// ── Row 3 Left: Market Overview ────────────────────────────────────────────
function MarketOverviewCard({ s }) {
  const spread = (s && s.btc_price != null && s.btc_index_price != null) ? s.btc_price - s.btc_index_price : null;
  const sc7d   = fmtPct(s && s.stablecoin_7d_change);

  return React.createElement('div', { className: 'tv-card', style: { flex: 1, padding: 18 } },
    React.createElement('div', { style: { fontSize: 12, color: 'var(--accent)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 12 } }, 'Market Overview'),
    [
      ['Total Market Cap',    s && fmtB(s.total_market_cap)],
      ['24h Volume',          s && fmtB(s.total_volume_24h)],
      ['Stablecoin Supply',   s && fmtB(s.stablecoin_supply)],
    ].map(([label, val]) =>
      React.createElement(StatRow, { key: label, label },
        React.createElement('span', { style: { color: 'var(--text)' } }, val || '—')
      )
    ),
    React.createElement(StatRow, { label: 'Stablecoin 7d' },
      React.createElement('span', { className: sc7d.cls }, sc7d.text)
    ),
    React.createElement(StatRow, { label: 'ETH Staking APR' },
      React.createElement('span', { className: 'ok' }, s && s.eth_staking_apr != null ? fmtNum(s.eth_staking_apr, 2) + '%' : '—')
    ),
    React.createElement(StatRow, { label: 'BTC Deribit Index' },
      React.createElement('span', { style: { color: 'var(--text)' } }, s && s.btc_index_price != null ? fmt(s.btc_index_price) : '—')
    ),
    React.createElement(StatRow, { label: 'Spot-Index Spread' },
      React.createElement('span', { className: spread != null ? (spread < 0 ? 'fail' : 'ok') : '' },
        spread != null ? (spread >= 0 ? '+' : '') + fmt(spread) : '—'
      )
    ),
    React.createElement(StatRow, { label: 'DeFi TVL' },
      React.createElement('span', { style: { color: 'var(--text)' } }, s && fmtB(s.total_defi_tvl) || '—')
    )
  );
}

// ── Row 3 Right: Futures ───────────────────────────────────────────────────
function FuturesCard({ s }) {
  function annualized(rate) {
    if (rate == null) return null;
    return rate * 3 * 365 * 100;
  }

  const coins = [
    { label: 'BTC', funding: s && s.btc_funding_rate, oi: s && s.btc_open_interest },
    { label: 'ETH', funding: s && s.eth_funding_rate, oi: s && s.eth_open_interest },
    { label: 'SOL', funding: s && s.sol_funding_rate, oi: null },
  ];

  return React.createElement('div', { className: 'tv-card', style: { flex: 1, padding: 18 } },
    React.createElement('div', { style: { fontSize: 12, color: 'var(--accent)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 12 } }, 'Futures (Bybit)'),
    React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '3rem 1fr 1fr 1fr', gap: '0 8px' } },
      ['', 'FUNDING', 'ANN.', 'OI'].map((h, i) =>
        React.createElement('div', { key: i, style: { fontSize: 10, color: 'var(--text4)', fontWeight: 700, letterSpacing: '0.06em', paddingBottom: 6, textAlign: i === 0 ? 'left' : 'right' } }, h)
      ),
      ...coins.map((c, i) => {
        const ann = annualized(c.funding);
        const annPct = fmtPct(ann);
        return [
          React.createElement('div', { key: `l${i}`, style: { borderTop: '1px solid var(--line)', padding: '6px 0', fontSize: 13, fontWeight: 600, color: 'var(--text)' } }, c.label),
          React.createElement('div', { key: `f${i}`, style: { borderTop: '1px solid var(--line)', padding: '6px 0', fontSize: 12, fontFamily: 'Fira Code', textAlign: 'right' } },
            c.funding != null ? fmtNum(c.funding * 100, 4) + '%' : '—'
          ),
          React.createElement('div', { key: `a${i}`, style: { borderTop: '1px solid var(--line)', padding: '6px 0', fontSize: 12, fontFamily: 'Fira Code', textAlign: 'right' }, className: ann != null && ann > 0 ? 'ok' : '' },
            ann != null ? annPct.text : '—'
          ),
          React.createElement('div', { key: `o${i}`, style: { borderTop: '1px solid var(--line)', padding: '6px 0', fontSize: 12, fontFamily: 'Fira Code', textAlign: 'right', color: 'var(--text2)' } },
            c.oi != null ? fmtB(c.oi) : '—'
          ),
        ];
      }).flat()
    )
  );
}

// ── Row 4: BTC Macro Cycle Dashboard ──────────────────────────────────────
function MacroCycleDashboard({ s, macroData, macroLoading }) {
  const metricCells = s ? [
    { label: 'BTC PRICE',     value: s.btc_price != null ? fmt(s.btc_price) : '—', sub: '' },
    { label: '200-WEEK MA',   value: s.btc_200d_ma != null ? fmt(s.btc_200d_ma) : '—', sub: 'Long-term floor' },
    { label: '7D RETURN',     value: (() => { const p = fmtPct(s.btc_return_7d); return React.createElement('span', { className: p.cls }, p.text); })(), sub: '' },
    { label: '30D RETURN',    value: (() => { const p = fmtPct(s.btc_return_30d); return React.createElement('span', { className: p.cls }, p.text); })(), sub: '' },
    { label: 'DOMINANCE',     value: s.btc_dominance != null ? fmtNum(s.btc_dominance, 1) + '%' : '—', sub: '' },
    { label: 'FUNDING RATE',  value: s.btc_funding_rate != null ? fmtNum(s.btc_funding_rate * 100, 4) + '%' : '—', sub: '8h rate' },
  ] : [];

  const rows = (macroData && macroData.rows) ? macroData.rows : [];

  function valColor(value, comment) {
    const vs = String(value || '');
    const cs = String(comment || '').toLowerCase();
    if (vs.includes('-')) return 'var(--fail)';
    if (cs.includes('bullish') || cs.includes('expanding')) return 'var(--ok)';
    return 'var(--text3)';
  }

  return React.createElement('div', { className: 'tv-card', style: { padding: 24 } },
    React.createElement('div', { style: { fontSize: 15, color: 'var(--accent)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 18 } }, 'BTC Macro Cycle Dashboard'),

    // 6-cell metric strip
    metricCells.length > 0 && React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12, marginBottom: 24 } },
      metricCells.map((cell, i) =>
        React.createElement('div', { key: i, style: { background: 'var(--panel2)', borderRadius: 8, padding: '12px 14px' } },
          React.createElement('div', { className: 'tv-label', style: { marginBottom: 6 } }, cell.label),
          React.createElement('div', { className: 'tv-num', style: { fontSize: 17, marginBottom: 2 } }, cell.value),
          cell.sub && React.createElement('div', { style: { fontSize: 11, color: 'var(--text4)' } }, cell.sub)
        )
      )
    ),

    // Macro rows table
    !macroLoading && rows.length > 0 && React.createElement('div', null,
      React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1fr auto 2fr', gap: '0 16px', fontSize: 11, color: 'var(--text4)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 } },
        React.createElement('div', null, 'Metric'),
        React.createElement('div', { style: { textAlign: 'right' } }, 'Value'),
        React.createElement('div', null, 'Comment')
      ),
      rows.map((r, i) =>
        React.createElement('div', { key: i, style: { display: 'grid', gridTemplateColumns: '1fr auto 2fr', gap: '0 16px', borderTop: '1px solid var(--line)', padding: '6px 0', alignItems: 'start' } },
          React.createElement('div', { style: { fontSize: 13, color: 'var(--text2)' } }, r.metric),
          React.createElement('div', { style: { fontSize: 13, fontFamily: 'Fira Code', color: valColor(r.value, r.comment), textAlign: 'right', whiteSpace: 'nowrap' } }, r.value != null ? String(r.value) : '—'),
          React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', lineHeight: 1.5 } }, r.comment || '')
        )
      )
    ),
    macroLoading && React.createElement('div', { style: { color: 'var(--text4)', fontSize: 13 } }, 'Loading macro data…')
  );
}

// ── Row 5: LP Pools ────────────────────────────────────────────────────────
function LPPoolsTable({ marketData }) {
  const poolsObj = marketData && marketData.lp_pools;
  const pools = poolsObj ? Object.values(poolsObj).sort((a, b) => (b.apyBase || 0) - (a.apyBase || 0)) : [];

  return React.createElement('div', { className: 'tv-card', style: { padding: 24 } },
    React.createElement('div', { style: { fontSize: 13, fontWeight: 700, color: 'var(--text)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 16 } }, 'LP Pools (Uniswap V3)'),
    !pools.length
      ? React.createElement('span', { style: { color: 'var(--text4)', fontSize: 13 } }, 'No pool data available')
      : React.createElement('div', { style: { overflowX: 'auto' } },
          React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '2fr 100px 1fr 1fr 1fr', gap: '0 16px', minWidth: 540 } },
            ['POOL', 'CHAIN', 'FEE APR', 'TVL', '24H VOL'].map((h, i) =>
              React.createElement('div', { key: h, style: { fontSize: 10, color: 'var(--text4)', fontWeight: 700, letterSpacing: '0.06em', paddingBottom: 8, textAlign: i >= 2 ? 'right' : 'left' } }, h)
            ),
            ...pools.map((p, i) => [
              React.createElement('div', { key: `n${i}`, style: { borderTop: '1px solid var(--line)', padding: '7px 0', fontSize: 13, color: 'var(--text2)' } }, p.asset || '—'),
              React.createElement('div', { key: `c${i}`, style: { borderTop: '1px solid var(--line)', padding: '7px 0' } }, chainBadge(p.chain)),
              React.createElement('div', { key: `a${i}`, style: { borderTop: '1px solid var(--line)', padding: '7px 0', fontFamily: 'Fira Code', fontSize: 13, textAlign: 'right', color: 'var(--ok)' } },
                p.apyBase != null ? fmtNum(p.apyBase, 2) + '%' : '—'
              ),
              React.createElement('div', { key: `t${i}`, style: { borderTop: '1px solid var(--line)', padding: '7px 0', fontFamily: 'Fira Code', fontSize: 13, textAlign: 'right', color: 'var(--text)' } }, fmtB(p.tvl)),
              React.createElement('div', { key: `v${i}`, style: { borderTop: '1px solid var(--line)', padding: '7px 0', fontFamily: 'Fira Code', fontSize: 13, textAlign: 'right', color: 'var(--text2)' } }, fmtB(p.vol1d)),
            ]).flat()
          )
        )
  );
}

// ── Row 6: Lend/Borrow Stats ───────────────────────────────────────────────
function LendBorrowTable({ marketData }) {
  const lending = marketData && marketData.lending;
  const rows = lending && typeof lending === 'object' ? Object.values(lending) : [];

  return React.createElement('div', { className: 'tv-card', style: { padding: 24 } },
    React.createElement('div', { style: { fontSize: 13, fontWeight: 700, color: 'var(--text)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 6 } }, 'Lend / Borrow Stats'),
    React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', marginBottom: 16 } }, 'Current supply and borrow rates across active lending protocols and assets.'),
    !rows.length
      ? React.createElement('div', { style: { color: 'var(--text4)', fontSize: 13, fontStyle: 'italic' } }, 'Lending rate data unavailable — rates will appear here when the data source is active.')
      : React.createElement('div', { style: { overflowX: 'auto' } },
          React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr 1fr 1fr 1fr 1fr', gap: '0 12px', minWidth: 700 } },
            ['PROTOCOL', 'ASSET', 'CHAIN', 'SUPPLY APY', 'BORROW APY', 'UTILIZ.', 'TOTAL SUPPLY', 'AVAILABLE'].map((h, i) =>
              React.createElement('div', { key: h, style: { fontSize: 10, color: 'var(--text4)', fontWeight: 700, letterSpacing: '0.06em', paddingBottom: 8, textAlign: i >= 3 ? 'right' : 'left' } }, h)
            ),
            ...rows.map((r, i) => [
              React.createElement('div', { key: `p${i}`, style: { borderTop: '1px solid var(--line)', padding: '6px 0', fontSize: 12, color: 'var(--text2)' } }, r.protocol || '—'),
              React.createElement('div', { key: `a${i}`, style: { borderTop: '1px solid var(--line)', padding: '6px 0', fontSize: 12 } }, r.asset || r.symbol || '—'),
              React.createElement('div', { key: `c${i}`, style: { borderTop: '1px solid var(--line)', padding: '6px 0' } }, chainBadge(r.chain)),
              React.createElement('div', { key: `s${i}`, style: { borderTop: '1px solid var(--line)', padding: '6px 0', fontFamily: 'Fira Code', fontSize: 12, textAlign: 'right', color: 'var(--ok)' } },
                r.supply_apy != null ? fmtNum(r.supply_apy * 100, 2) + '%' : '—'
              ),
              React.createElement('div', { key: `b${i}`, style: { borderTop: '1px solid var(--line)', padding: '6px 0', fontFamily: 'Fira Code', fontSize: 12, textAlign: 'right', color: 'var(--fail)' } },
                r.borrow_apy != null ? fmtNum(r.borrow_apy * 100, 2) + '%' : '—'
              ),
              React.createElement('div', { key: `u${i}`, style: { borderTop: '1px solid var(--line)', padding: '6px 0', fontFamily: 'Fira Code', fontSize: 12, textAlign: 'right', color: 'var(--text)' } },
                r.utilization != null ? fmtNum(r.utilization * 100, 1) + '%' : '—'
              ),
              React.createElement('div', { key: `t${i}`, style: { borderTop: '1px solid var(--line)', padding: '6px 0', fontFamily: 'Fira Code', fontSize: 12, textAlign: 'right', color: 'var(--text2)' } }, fmtB(r.total_supply)),
              React.createElement('div', { key: `v${i}`, style: { borderTop: '1px solid var(--line)', padding: '6px 0', fontFamily: 'Fira Code', fontSize: 12, textAlign: 'right', color: 'var(--text2)' } }, fmtB(r.available)),
            ]).flat()
          )
        )
  );
}

// ── Main Screen ────────────────────────────────────────────────────────────
function MarketDataScreen({ hideValues, setActiveTab }) {
  const [marketData, setMarketData] = useMDState(null);
  const [marketLoading, setMarketLoading] = useMDState(true);
  const [macroData, setMacroData] = useMDState(null);
  const [macroLoading, setMacroLoading] = useMDState(true);
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
      .catch(() => {})
      .finally(() => setMacroLoading(false));
  }, []);

  async function handleRefresh() {
    if (refreshing) return;
    setRefreshing(true);
    try { await api('/api/market-data/refresh', { method: 'POST' }); } catch (e) {}
    fetchMarket();
    setRefreshing(false);
  }

  const s = marketData && marketData.snapshot;
  const fgHistory = marketData && marketData.fg_history;

  return React.createElement('div', { style: { padding: 24, display: 'flex', flexDirection: 'column', gap: 20 } },

    // Row 1: Action bar
    React.createElement(ActionBar, { snapshot: s, onRefresh: handleRefresh, refreshing, setActiveTab }),

    // Row 2: 4 cards
    React.createElement('div', { style: { display: 'flex', gap: 16 } },
      React.createElement(BitcoinCard, { s }),
      React.createElement(EthereumCard, { s }),
      React.createElement(FearGreedCard, { s, fgHistory }),
      React.createElement(MacroCard, { macroData, macroLoading })
    ),

    // Row 3: 2 cards
    React.createElement('div', { style: { display: 'flex', gap: 16 } },
      React.createElement(MarketOverviewCard, { s }),
      React.createElement(FuturesCard, { s })
    ),

    // Row 4: BTC Macro Cycle Dashboard
    React.createElement(MacroCycleDashboard, { s, macroData, macroLoading }),

    // Row 5: LP Pools
    React.createElement(LPPoolsTable, { marketData }),

    // Row 6: Lend/Borrow
    React.createElement(LendBorrowTable, { marketData })
  );
}

window.MarketDataScreen = MarketDataScreen;
