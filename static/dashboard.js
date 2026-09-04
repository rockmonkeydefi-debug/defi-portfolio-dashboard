/* ===== DASHBOARD SCREEN ===== */

const { useState: useDashState, useEffect: useDashEffect, useMemo: useDashMemo, useCallback: useDashCallback } = React;

/* ── helpers ── */
function _dashYFmt(v) {
  const a = Math.abs(v);
  if (a >= 1_000_000) return '$' + (v / 1_000_000).toFixed(1) + 'M';
  if (a >= 1_000)     return '$' + (v / 1_000).toFixed(0) + 'K';
  return '$' + v.toFixed(0);
}

function _filterChartRange(data, label) {
  if (!data?.length) return [];
  if (label === 'ALL') return data;
  const dayMs = 86_400_000;
  const hours = { '24H': 1/24, '1W': 7, '1M': 30, '1Y': 365 };
  const days = hours[label];
  if (days == null) return data;
  const cutoff = Date.now() - days * dayMs * (label === '24H' ? 1 : 1);
  return data.filter(d => new Date(d.timestamp).getTime() >= (
    label === '24H' ? Date.now() - 24 * 3600 * 1000 : Date.now() - days * dayMs
  ));
}

function _pctChange(data) {
  if (!data || data.length < 2) return null;
  const first = data[0].total_value || 0;
  const last  = data[data.length - 1].total_value || 0;
  return first > 0 ? ((last - first) / first * 100) : null;
}

/* ── SVG area sparkline (no axes, no tooltip) ── */
function DashAreaSparkline({ data, height = 60, color = 'var(--accent)', gradientId = 'dashSparkGrad' }) {
  const values = useDashMemo(() => {
    const pts = (data || []).map(d => typeof d === 'object' ? (d.total_value ?? d) : d).filter(v => v != null && isFinite(v));
    return pts;
  }, [data]);

  if (values.length < 2) return null;

  const w = 1000; // viewBox width — scales responsively
  const h = height;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const n = values.length;

  const coords = values.map((v, i) => {
    const x = (i / (n - 1)) * w;
    const y = h - ((v - min) / range) * (h - 2) - 1;
    return [x, y];
  });

  const linePts = coords.map(([x, y]) => `${x},${y}`).join(' ');
  const areaPath = `M 0,${h} L ${coords.map(([x, y]) => `${x},${y}`).join(' L ')} L ${w},${h} Z`;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ width: '100%', height, display: 'block' }}>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor={color} stopOpacity={0.18} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradientId})`} />
      <polyline points={linePts} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/* ── BTC Zone Bar ── */
const BTC_ZONES = [
  { key: 'bear',   label: 'Bear',         color: 'var(--fail)',    chip: 'Risk',      chipCls: 'fail' },
  { key: 'accum',  label: 'Accum.',       color: '#f97316',        chip: 'Caution',   chipCls: 'warn' },
  { key: 'value',  label: 'Value Window', color: 'var(--warn)',    chip: 'Favorable', chipCls: 'ok' },
  { key: 'bull',   label: 'Bull',         color: 'var(--ok-soft)', chip: 'Favorable', chipCls: 'ok' },
  { key: 'euphoria', label: 'Euphoria',   color: 'var(--ok)',      chip: 'Caution',   chipCls: 'warn' },
];

function _deriveZone(btcPrice, ma200, fg) {
  if (!btcPrice || !ma200) return null;
  if (btcPrice < ma200 * 0.85) return 'bear';
  if (btcPrice < ma200)        return 'accum';
  if (btcPrice < ma200 * 1.2 && fg < 50) return 'value';
  if (btcPrice < ma200 * 1.5)  return 'bull';
  return 'euphoria';
}

function BtcZoneBar({ btcPrice, ma200, fg }) {
  const zoneKey = _deriveZone(btcPrice, ma200, fg);
  const zoneIdx = BTC_ZONES.findIndex(z => z.key === zoneKey);
  const zone = zoneIdx >= 0 ? BTC_ZONES[zoneIdx] : null;
  // dot center = (zoneIdx + 0.5) * 20% of bar
  const dotPct = zoneIdx >= 0 ? (zoneIdx + 0.5) * 20 : null;

  return (
    <div>
      {/* Segment bar */}
      <div style={{ display: 'flex', borderRadius: 6, overflow: 'hidden', height: 10, marginBottom: 6, position: 'relative' }}>
        {BTC_ZONES.map(z => (
          <div key={z.key} style={{ flex: 1, background: z.color, opacity: z.key === zoneKey ? 1 : 0.4 }} />
        ))}
        {/* Indicator dot */}
        {dotPct != null && (
          <div style={{
            position: 'absolute',
            left: `${dotPct}%`,
            top: '50%',
            transform: 'translate(-50%, -50%)',
            width: 12,
            height: 12,
            borderRadius: '50%',
            background: '#fff',
            boxShadow: '0 0 0 2px rgba(0,0,0,0.4)',
            border: '2px solid var(--bg)',
          }} />
        )}
      </div>
      {/* Segment labels */}
      <div style={{ display: 'flex', marginBottom: 10 }}>
        {BTC_ZONES.map(z => (
          <div key={z.key} style={{ flex: 1, fontSize: 9, color: z.key === zoneKey ? 'var(--text)' : 'var(--text4)', textAlign: 'center', fontWeight: z.key === zoneKey ? 600 : 400 }}>
            {z.label}
          </div>
        ))}
      </div>
      {/* Zone name + chip */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--accent)' }}>
          {zone ? zone.label : '—'}
        </span>
        {zone && <span className={`tv-chip ${zone.chipCls}`}>{zone.chip}</span>}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text4)' }}>Pi Cycle · MVRV Z · NUPL · Puell Multiple</div>
    </div>
  );
}

/* ── ROW 1 Right: mini cards ── */
function LpMiniCard({ lpPositions }) {
  const total   = lpPositions?.length ?? 0;
  const inCount = (lpPositions || []).filter(p => p.in_range).length;
  const allIn   = total > 0 && inCount === total;
  const cls     = total === 0 ? 'text' : allIn ? 'ok' : 'warn';
  const outCount = total - inCount;

  return (
    <div style={{ flex: 1, background: 'var(--panel3)', borderRadius: 8, padding: '10px 12px' }}>
      <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 6, fontSize: 10 }}>LP HEALTH</div>
      <div className="tv-num" style={{ fontSize: 24, color: `var(--${cls})` }}>
        {total === 0 ? '—' : inCount}
      </div>
      <div style={{ fontSize: 11, marginTop: 3, color: total === 0 ? 'var(--text4)' : outCount > 0 ? 'var(--fail)' : 'var(--ok)' }}>
        {total === 0 ? 'No positions' : allIn ? 'All in range' : `${outCount} out of range`}
      </div>
    </div>
  );
}

function LendingMiniCard({ aavePositions }) {
  const hfs = (aavePositions || []).map(p => p.health_factor).filter(h => h != null && h > 0 && isFinite(h));
  const lowestHF = hfs.length ? Math.min(...hfs) : null;
  const cls = lowestHF == null ? 'text4' : lowestHF > 2 ? 'ok' : lowestHF > 1.5 ? 'warn' : 'fail';
  const label = lowestHF == null ? 'No positions' : lowestHF > 2 ? 'Safe zone' : lowestHF > 1.5 ? 'Caution' : 'Danger';

  return (
    <div style={{ flex: 1, background: 'var(--panel3)', borderRadius: 8, padding: '10px 12px' }}>
      <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 6, fontSize: 10 }}>LENDING</div>
      <div className="tv-num" style={{ fontSize: 24, color: `var(--${cls})` }}>
        {lowestHF != null ? lowestHF.toFixed(2) : '—'}
      </div>
      <div style={{ fontSize: 11, marginTop: 3, color: `var(--${cls})` }}>{label}</div>
    </div>
  );
}

/* ── ROW 2: Comparison chart strip ── */
function ComparisonStrip({ allData, activeRange, onSelect }) {
  const periods = ['24H', '1W', '1M', '1Y'];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginTop: 12 }}>
      {periods.map(p => {
        const filtered = _filterChartRange(allData, p);
        const pct = _pctChange(filtered);
        const isActive = activeRange === p;
        const pctColor = pct == null ? 'var(--text4)' : pct >= 0 ? 'var(--ok)' : 'var(--fail)';

        return (
          <div
            key={p}
            onClick={() => onSelect(p)}
            style={{
              cursor: 'pointer',
              background: isActive ? 'var(--panel3)' : 'var(--panel2)',
              borderRadius: 6,
              padding: '8px 10px',
              border: isActive ? '1px solid var(--accent)' : '1px solid transparent',
              transition: 'border-color 0.15s',
            }}
          >
            <DashAreaSparkline
              data={filtered.length >= 2 ? filtered : allData}
              height={52}
              color={pct != null && pct < 0 ? 'var(--fail)' : 'var(--accent)'}
              gradientId={`compGrad_${p}`}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 6 }}>
              <span style={{ fontSize: 11, color: isActive ? 'var(--text)' : 'var(--text3)', fontWeight: isActive ? 600 : 400 }}>{p}</span>
              <span style={{ fontSize: 11, color: pctColor, fontWeight: 500 }}>
                {pct != null ? (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%' : '—'}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── ROW 2: Main equity chart ── */
function DashEquityChart({ allData, range, onRangeChange }) {
  const { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } = window.Recharts || {};

  const filtered = useDashMemo(() => {
    const f = _filterChartRange(allData, range);
    const tooFew = f.length < 2;
    return tooFew ? allData : f;
  }, [allData, range]);

  const showingAll = useDashMemo(() => {
    const f = _filterChartRange(allData, range);
    return f.length < 2 && allData.length >= 2;
  }, [allData, range]);

  const chartItems = useDashMemo(() => filtered.map(d => ({
    date: range === '24H'
      ? new Date(d.timestamp).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
      : new Date(d.timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    value:   d.total_value   || 0,
    lp:      d.lp_value      || 0,
    tokens:  d.tokens_value  || 0,
    lending: d.lending_value || 0,
  })), [filtered, range]);

  const TIMEFRAMES = ['ALL', '1Y', '1M', '1W', '24H'];

  const pillBtn = (label) => (
    <button
      key={label}
      onClick={() => onRangeChange(label)}
      style={{
        padding: '4px 12px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12,
        background: label === range ? 'var(--accent)' : 'var(--panel3)',
        color: label === range ? '#000' : 'var(--text3)',
        fontWeight: label === range ? 600 : 400,
      }}
    >{label}</button>
  );

  return (
    <div className="tv-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div className="tv-label" style={{ color: 'var(--accent)' }}>Portfolio Equity</div>
        <div style={{ display: 'flex', gap: 6 }}>{TIMEFRAMES.map(pillBtn)}</div>
      </div>
      {showingAll && (
        <div style={{ fontSize: 11, color: 'var(--text4)', marginBottom: 8 }}>Showing all available data</div>
      )}
      {(!AreaChart || chartItems.length < 2) ? (
        <div style={{ color: 'var(--text4)', fontSize: 13, textAlign: 'center', padding: '40px 0' }}>
          {!AreaChart ? 'Chart library not loaded' : 'No portfolio history yet'}
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={chartItems} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="mainEquityGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="var(--accent)" stopOpacity={0.18} />
                <stop offset="95%" stopColor="var(--accent)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" strokeOpacity={0.3} />
            <XAxis dataKey="date" tick={{ fill: 'var(--text4)', fontSize: 11 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
            <YAxis tickFormatter={_dashYFmt} tick={{ fill: 'var(--text4)', fontSize: 11 }} tickLine={false} axisLine={false} width={58} orientation="right" />
            <Tooltip
              contentStyle={{ background: 'var(--panel)', border: '1px solid var(--line)', fontSize: 12, borderRadius: 6 }}
              labelStyle={{ color: 'var(--text)', marginBottom: 4 }}
              formatter={(value, name) => {
                const labels = { value: 'Total', lp: 'LP', tokens: 'Tokens', lending: 'Lending' };
                return ['$' + value.toLocaleString(undefined, { maximumFractionDigits: 0 }), labels[name] || name];
              }}
            />
            <Area type="monotone" dataKey="value"   stroke="var(--accent)"   strokeWidth={2}   fill="url(#mainEquityGrad)" dot={false} activeDot={{ r: 4 }} />
            <Area type="monotone" dataKey="lp"      stroke="var(--ok-soft)"  strokeWidth={1}   fill="none" dot={false} strokeDasharray="3 3" />
            <Area type="monotone" dataKey="tokens"  stroke="var(--warn)"     strokeWidth={1}   fill="none" dot={false} strokeDasharray="3 3" />
            <Area type="monotone" dataKey="lending" stroke="var(--adapt)"    strokeWidth={1}   fill="none" dot={false} strokeDasharray="3 3" />
          </AreaChart>
        </ResponsiveContainer>
      )}
      <ComparisonStrip allData={allData} activeRange={range} onSelect={onRangeChange} />
    </div>
  );
}

/* ── ROW 3 Right: Spot P&L card ── */
function SpotPnlCard({ spotPnl, spotHistory, hideValues }) {
  const unrealized = (spotPnl || []).reduce((s, h) => s + (h.unrealized_pnl_usd || 0), 0);
  const costBasis  = (spotPnl || []).reduce((s, h) => s + (h.total_cost_basis    || 0), 0);
  const unrealPct  = costBasis > 0 ? (unrealized / costBasis * 100) : null;

  // Realized last 30 days: filter by last_sell_date
  const cutoff30d = Date.now() - 30 * 86_400_000;
  const realized30d = (spotHistory || [])
    .filter(p => p.last_sell_date && new Date(p.last_sell_date).getTime() >= cutoff30d)
    .reduce((s, p) => s + (p.realized_pnl || 0), 0);

  // Top movers by abs(unrealized_pct)
  const movers = [...(spotPnl || [])]
    .filter(h => h.unrealized_pct != null)
    .sort((a, b) => Math.abs(b.unrealized_pct) - Math.abs(a.unrealized_pct))
    .slice(0, 3);

  return (
    <div className="tv-card" style={{ marginTop: 12 }}>
      <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 12 }}>Spot P&amp;L</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 14 }}>
        <div style={{ background: 'var(--panel2)', borderRadius: 8, padding: '10px 12px' }}>
          <div className="tv-label" style={{ fontSize: 10, marginBottom: 4 }}>UNREALIZED</div>
          <div className="tv-num" style={{ fontSize: 20, color: unrealized >= 0 ? 'var(--ok)' : 'var(--fail)' }}>
            {hideValues ? '••••' : (unrealized >= 0 ? '+' : '') + fmt(unrealized)}
          </div>
          {unrealPct != null && (
            <div style={{ fontSize: 11, color: 'var(--text4)', marginTop: 3 }}>
              {unrealPct >= 0 ? '+' : ''}{unrealPct.toFixed(1)}% of cost basis
            </div>
          )}
        </div>
        <div style={{ background: 'var(--panel2)', borderRadius: 8, padding: '10px 12px' }}>
          <div className="tv-label" style={{ fontSize: 10, marginBottom: 4 }}>REALIZED · 30D</div>
          <div className="tv-num" style={{ fontSize: 20, color: realized30d >= 0 ? 'var(--ok)' : 'var(--fail)' }}>
            {hideValues ? '••••' : (realized30d >= 0 ? '+' : '') + fmt(realized30d)}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text4)', marginTop: 3 }}>Closed positions</div>
        </div>
      </div>
      {movers.length > 0 && (
        <>
          <div className="tv-label" style={{ fontSize: 10, marginBottom: 8 }}>TOP MOVERS · 24H</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {movers.map((h, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span className="tv-chip" style={{ fontSize: 11 }}>{h.symbol}</span>
                <span style={{ fontSize: 13, fontWeight: 500, color: (h.unrealized_pct || 0) >= 0 ? 'var(--ok)' : 'var(--fail)' }}>
                  {hideValues ? '••••' : fmtPct(h.unrealized_pct || 0)}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/* ── Breakdown pill ── */
function BreakdownPill({ dot, label, value }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      <span style={{ fontSize: 10 }}>{dot}</span>
      <span style={{ fontSize: 11, color: 'var(--text4)' }}>{label}</span>
      <span className="tv-num" style={{ fontSize: 13 }}>{value}</span>
    </div>
  );
}

/* ── MAIN SCREEN ── */
function DashboardScreen({ hideValues, setActiveTab }) {
  const [portfolio,   setPortfolio]   = useDashState(null);
  const [allChart,    setAllChart]    = useDashState([]);
  const [marketData,  setMarketData]  = useDashState(null);
  const [spotPnl,     setSpotPnl]     = useDashState([]);
  const [spotHistory, setSpotHistory] = useDashState([]);
  const [stablecoins, setStablecoins] = useDashState(null);
  const [chartRange,  setChartRange]  = useDashState('ALL');
  const [loading,     setLoading]     = useDashState(true);
  const [refreshing,  setRefreshing]  = useDashState(false);

  const fetchAll = useDashCallback(() => {
    return Promise.all([
      fetch('/api/portfolio').then(r => r.json()).catch(() => null),
      fetch('/api/history/portfolio-chart?days=9999').then(r => r.json()).catch(() => []),
      fetch('/api/market-data').then(r => r.json()).catch(() => null),
      fetch('/api/spot/pnl').then(r => r.json()).catch(() => []),
      fetch('/api/spot/history').then(r => r.json()).catch(() => []),
      fetch('/api/spot/stablecoins').then(r => r.json()).catch(() => null),
    ]).then(([port, chart, mkt, spot, hist, stables]) => {
      setPortfolio(port);
      setAllChart(Array.isArray(chart) ? chart : []);
      setMarketData(mkt);
      setSpotPnl(Array.isArray(spot) ? spot : []);
      setSpotHistory(Array.isArray(hist) ? hist : []);
      setStablecoins(stables);
    });
  }, []);

  useDashEffect(() => {
    fetchAll().finally(() => setLoading(false));
  }, []);

  async function handleRefresh() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await fetch('/api/portfolio?refresh=true');
      await fetchAll();
    } catch (_) {}
    setRefreshing(false);
  }

  /* ── derived values ── */
  const latest = allChart.length ? allChart[allChart.length - 1] : null;
  const stableTotal = stablecoins?.total_usd || 0;
  const grandTotal  = (latest?.total_value || 0) + stableTotal;

  // 24h change from chart data
  const change24h = useDashMemo(() => {
    if (!allChart.length) return null;
    const last = allChart[allChart.length - 1];
    const cutoff = Date.now() - 24 * 3600 * 1000;
    const prev = [...allChart].reverse().find(d => new Date(d.timestamp).getTime() <= cutoff);
    if (!prev || !prev.total_value) return null;
    const deltaUsd = last.total_value - prev.total_value;
    const deltaPct = prev.total_value > 0 ? (deltaUsd / prev.total_value * 100) : null;
    return { usd: deltaUsd, pct: deltaPct };
  }, [allChart]);

  const updatedAt = useDashMemo(() => {
    if (!latest?.timestamp) return '';
    return new Date(latest.timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }, [latest]);

  const snapshot = marketData?.snapshot || {};
  const fgIndex  = snapshot.fear_greed_index ?? 50;

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 320, color: 'var(--text4)', fontSize: 14 }}>
        Loading dashboard…
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* ── ROW 1 — Hero ── */}
      <div style={{ background: 'var(--panel)', borderTop: '3px solid var(--accent)', borderRadius: '0 0 10px 10px', padding: '18px 20px', display: 'grid', gridTemplateColumns: '60% 40%', gap: 20 }}>

        {/* LEFT */}
        <div>
          {/* Label + date + refresh */}
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
            <div className="tv-label" style={{ fontSize: 11, flex: 1 }}>TOTAL PORTFOLIO VALUE</div>
            <span style={{ fontSize: 12, color: 'var(--text4)', marginRight: 10 }}>
              Updated {updatedAt || 'just now'}
            </span>
            <button
              className="tv-btn"
              style={{ fontSize: 11, padding: '3px 10px', opacity: refreshing ? 0.5 : 1 }}
              onClick={handleRefresh}
              disabled={refreshing}
            >
              {refreshing ? '…' : '↺'} Refresh
            </button>
          </div>

          {/* Hero number */}
          <div className="tv-num" style={{ fontSize: 42, lineHeight: 1.1, marginBottom: 8 }}>
            {hideValues ? '••••••' : fmt(grandTotal, 0)}
          </div>

          {/* 24h change */}
          {change24h && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, fontSize: 14 }}>
              <span style={{ color: change24h.usd >= 0 ? 'var(--ok)' : 'var(--fail)', fontWeight: 500 }}>
                {hideValues ? '••••' : (change24h.usd >= 0 ? '+' : '') + fmt(change24h.usd, 0)}
              </span>
              {change24h.pct != null && (
                <span style={{ color: 'var(--text4)', fontSize: 12 }}>
                  {(change24h.pct >= 0 ? '+' : '') + change24h.pct.toFixed(2) + '% · 24h'}
                </span>
              )}
            </div>
          )}

          {/* Inline sparkline */}
          {allChart.length >= 2 && (
            <div style={{ marginBottom: 14 }}>
              <DashAreaSparkline data={allChart} height={60} gradientId="heroSparkGrad" />
            </div>
          )}

          {/* Breakdown pills */}
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <BreakdownPill dot="🟡" label="Spot"       value={hideValues ? '••••' : fmt(latest?.tokens_value  || 0, 0)} />
            <BreakdownPill dot="🔵" label="DeFi LP"    value={hideValues ? '••••' : fmt(latest?.lp_value      || 0, 0)} />
            <BreakdownPill dot="🟣" label="Lending"    value={hideValues ? '••••' : fmt(latest?.lending_value || 0, 0)} />
            <BreakdownPill dot="⚪" label="Cash"       value={hideValues ? '••••' : fmt(stableTotal,              0)} />
          </div>
        </div>

        {/* RIGHT */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {/* BTC Zone card */}
          <div style={{ background: 'var(--panel2)', borderRadius: 10, padding: '14px 16px', flex: 1 }}>
            <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 12, fontSize: 11 }}>BTC MACRO ZONE</div>
            <BtcZoneBar btcPrice={snapshot.btc_price} ma200={snapshot.btc_200d_ma} fg={fgIndex} />
            {snapshot.btc_price && (
              <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text3)', display: 'flex', gap: 12 }}>
                <span>BTC <span className="tv-num" style={{ fontSize: 13 }}>{fmt(snapshot.btc_price, 0)}</span></span>
                {snapshot.btc_200d_ma && (
                  <span>200D MA <span className="tv-num" style={{ fontSize: 13 }}>{fmt(snapshot.btc_200d_ma, 0)}</span></span>
                )}
                {snapshot.fear_greed_index != null && (
                  <span>F&amp;G <span className="tv-num" style={{ fontSize: 13, color: fgIndex < 25 ? 'var(--fail)' : fgIndex < 50 ? 'var(--warn)' : 'var(--ok)' }}>{fgIndex}</span></span>
                )}
              </div>
            )}
          </div>

          {/* LP + Lending mini cards */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <LpMiniCard lpPositions={portfolio?.lp_positions} />
            <LendingMiniCard aavePositions={portfolio?.aave_positions} />
          </div>
        </div>
      </div>

      {/* ── ROW 2 — Equity chart ── */}
      <DashEquityChart allData={allChart} range={chartRange} onRangeChange={setChartRange} />

      {/* ── ROW 3 — Two columns ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '55% 45%', gap: 16, alignItems: 'start' }}>

        {/* RIGHT — Spot P&L */}
        <div>
          <SpotPnlCard spotPnl={spotPnl} spotHistory={spotHistory} hideValues={hideValues} />
        </div>

      </div>

    </div>
  );
}

window.DashboardScreen = DashboardScreen;
