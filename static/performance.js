/* ===== PERFORMANCE SCREEN ===== */

const { useState: usePerfState, useEffect: usePerfEffect, useMemo: usePerfMemo } = React;

const PERF_RANGE_OPTIONS = [
  { label: '7D',  days: 7 },
  { label: '30D', days: 30 },
  { label: '90D', days: 90 },
  { label: '1Y',  days: 365 },
  { label: 'All', days: null },
];

function _perfYFmt(v) {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return '$' + (v / 1_000_000).toFixed(1) + 'M';
  if (abs >= 1_000) return '$' + (v / 1_000).toFixed(0) + 'K';
  return '$' + v.toFixed(0);
}

function _filterByDays(items, dateField, days) {
  if (!items?.length) return [];
  if (!days) return items;
  const cutoff = Date.now() - days * 86_400_000;
  return items.filter(item => {
    const d = item[dateField];
    return d && new Date(d).getTime() >= cutoff;
  });
}

function _filterChartByDays(items, days) {
  if (!items?.length) return [];
  if (!days) return items;
  const cutoff = Date.now() - days * 86_400_000;
  return items.filter(d => new Date(d.timestamp).getTime() >= cutoff);
}

function PerfKpiCard({ label, value, color, sub }) {
  return (
    <div className="tv-card">
      <div className="tv-label" style={{ marginBottom: 6, fontSize: 11 }}>{label}</div>
      <div className="tv-num" style={{ fontSize: 28, color: color || 'var(--text)' }}>{value}</div>
      {sub && <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text4)' }}>{sub}</div>}
    </div>
  );
}

function PerformanceScreen({ hideValues }) {
  const [range, setRange] = usePerfState('30D');
  const [allChartData, setAllChartData] = usePerfState([]);
  const [spotHistory, setSpotHistory] = usePerfState([]);
  const [loading, setLoading] = usePerfState(true);

  usePerfEffect(() => {
    Promise.all([
      fetch('/api/history/portfolio-chart?days=9999').then(r => r.json()).catch(() => []),
      fetch('/api/spot/history').then(r => r.json()).catch(() => []),
    ]).then(([chart, hist]) => {
      setAllChartData(Array.isArray(chart) ? chart : []);
      setSpotHistory(Array.isArray(hist) ? hist : []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const rangeDays = usePerfMemo(() => (PERF_RANGE_OPTIONS.find(r => r.label === range) || PERF_RANGE_OPTIONS[1]).days, [range]);

  const filteredHistory = usePerfMemo(() => _filterByDays(spotHistory, 'last_sell_date', rangeDays), [spotHistory, rangeDays]);
  const filteredChart   = usePerfMemo(() => _filterChartByDays(allChartData, rangeDays), [allChartData, rangeDays]);

  const kpis = usePerfMemo(() => {
    const pos = filteredHistory;
    if (!pos.length) return { netPnl: 0, winRate: 0, profitFactor: 0, expectancy: 0, wins: 0, total: 0 };
    const wins   = pos.filter(p => (p.realized_pnl || 0) > 0);
    const losses = pos.filter(p => (p.realized_pnl || 0) <= 0);
    const netPnl      = pos.reduce((s, p) => s + (p.realized_pnl || 0), 0);
    const winRate     = wins.length / pos.length;
    const lossRate    = losses.length / pos.length;
    const totalWins   = wins.reduce((s, p) => s + p.realized_pnl, 0);
    const totalLosses = Math.abs(losses.reduce((s, p) => s + p.realized_pnl, 0));
    const avgWin      = wins.length   > 0 ? totalWins   / wins.length   : 0;
    const avgLoss     = losses.length > 0 ? totalLosses / losses.length : 0;
    const profitFactor = totalLosses > 0 ? totalWins / totalLosses : (totalWins > 0 ? Infinity : 0);
    const expectancy   = (winRate * avgWin) - (lossRate * avgLoss);
    return { netPnl, winRate, profitFactor, expectancy, wins: wins.length, total: pos.length };
  }, [filteredHistory]);

  const chartItems = usePerfMemo(() => filteredChart.map(d => ({
    date: new Date(d.timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    value: d.total_value,
  })), [filteredChart]);

  const drawdownData = usePerfMemo(() => {
    if (!filteredChart.length) return [];
    let peak = 0;
    return filteredChart.map(d => {
      if (d.total_value > peak) peak = d.total_value;
      const dd = peak > 0 ? (d.total_value - peak) / peak * 100 : 0;
      return {
        date: new Date(d.timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
        drawdown: dd,
      };
    });
  }, [filteredChart]);

  const barData = usePerfMemo(() => filteredHistory.map(p => ({
    symbol: p.symbol,
    pnl: p.realized_pnl || 0,
  })), [filteredHistory]);

  const symbolBreakdown = usePerfMemo(() => {
    const map = {};
    for (const pos of filteredHistory) {
      const sym = pos.symbol;
      if (!map[sym]) map[sym] = { symbol: sym, trades: 0, wins: 0, winPnls: [], lossPnls: [], netPnl: 0, best: -Infinity, worst: Infinity };
      const m = map[sym];
      m.trades++;
      m.netPnl += pos.realized_pnl || 0;
      if ((pos.realized_pnl || 0) > 0) { m.wins++; m.winPnls.push(pos.realized_pnl); }
      else { m.lossPnls.push(pos.realized_pnl || 0); }
      if (pos.realized_pnl > m.best)  m.best  = pos.realized_pnl;
      if (pos.realized_pnl < m.worst) m.worst = pos.realized_pnl;
    }
    return Object.values(map)
      .sort((a, b) => b.netPnl - a.netPnl)
      .map(m => ({
        symbol:   m.symbol,
        trades:   m.trades,
        winRate:  m.trades > 0 ? (m.wins / m.trades * 100).toFixed(0) + '%' : '0%',
        avgWin:   m.winPnls.length  > 0 ? m.winPnls.reduce((s, v) => s + v, 0)  / m.winPnls.length  : 0,
        avgLoss:  m.lossPnls.length > 0 ? m.lossPnls.reduce((s, v) => s + v, 0) / m.lossPnls.length : 0,
        netPnl:   m.netPnl,
        best:     m.best  === -Infinity ? 0 : m.best,
        worst:    m.worst ===  Infinity ? 0 : m.worst,
      }));
  }, [filteredHistory]);

  const R = window.Recharts || {};
  const { AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } = R;
  const hasRecharts = !!AreaChart;

  const tooltipStyle = { background: 'var(--panel)', border: '1px solid var(--line)', fontSize: 12, borderRadius: 6 };
  const labelStyle   = { color: 'var(--text)' };

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 320, color: 'var(--text4)', fontSize: 14 }}>
        Loading performance data…
      </div>
    );
  }

  const pfVal = isFinite(kpis.profitFactor) ? kpis.profitFactor.toFixed(2) : '∞';
  const pfColor = kpis.profitFactor > 1.5 ? 'var(--ok)' : kpis.profitFactor >= 1 ? 'var(--warn)' : 'var(--fail)';
  const wrColor = kpis.winRate >= 0.6 ? 'var(--ok)' : kpis.winRate >= 0.45 ? 'var(--warn)' : 'var(--fail)';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* ROW 1 — Date range picker */}
      <div className="tv-card" style={{ padding: '12px 16px' }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {PERF_RANGE_OPTIONS.map(r => (
            <button
              key={r.label}
              onClick={() => setRange(r.label)}
              style={{
                padding: '6px 18px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 13,
                fontWeight: r.label === range ? 600 : 400,
                background: r.label === range ? 'var(--accent)' : 'var(--panel3)',
                color: r.label === range ? '#000' : 'var(--text2)',
              }}
            >{r.label}</button>
          ))}
        </div>
      </div>

      {/* ROW 2 — 4 KPI cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        <PerfKpiCard
          label="REALIZED P&L"
          value={hideValues ? '••••' : (kpis.netPnl >= 0 ? '+' : '') + fmt(kpis.netPnl)}
          color={kpis.netPnl >= 0 ? 'var(--ok)' : 'var(--fail)'}
          sub={`${kpis.total} closed trade${kpis.total !== 1 ? 's' : ''}`}
        />
        <PerfKpiCard
          label="WIN RATE"
          value={(kpis.winRate * 100).toFixed(0) + '%'}
          color={wrColor}
          sub={`${kpis.wins} wins / ${kpis.total} trades`}
        />
        <PerfKpiCard
          label="PROFIT FACTOR"
          value={pfVal}
          color={pfColor}
          sub="wins / losses ratio"
        />
        <PerfKpiCard
          label="EXPECTANCY"
          value={hideValues ? '••••' : (kpis.expectancy >= 0 ? '+' : '') + fmt(kpis.expectancy)}
          color={kpis.expectancy >= 0 ? 'var(--ok)' : 'var(--fail)'}
          sub="per trade"
        />
      </div>

      {/* ROW 3 — Equity curve */}
      <div className="tv-card">
        <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 14 }}>Portfolio Equity</div>
        {hasRecharts && chartItems.length > 1 ? (
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={chartItems} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="perfEquityGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--accent)" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="var(--accent)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" strokeOpacity={0.3} />
              <XAxis dataKey="date" tick={{ fill: 'var(--text4)', fontSize: 11 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
              <YAxis tickFormatter={_perfYFmt} tick={{ fill: 'var(--text4)', fontSize: 11 }} tickLine={false} axisLine={false} width={60} />
              <Tooltip
                formatter={(v) => ['$' + v.toLocaleString(undefined, { maximumFractionDigits: 0 }), 'Portfolio']}
                contentStyle={tooltipStyle}
                labelStyle={labelStyle}
              />
              <Area type="monotone" dataKey="value" stroke="var(--accent)" strokeWidth={2} fill="url(#perfEquityGrad)" dot={false} activeDot={{ r: 4 }} />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ color: 'var(--text4)', fontSize: 13, textAlign: 'center', padding: '48px 0' }}>
            {!hasRecharts ? 'Chart library not loaded' : 'No portfolio history in this period'}
          </div>
        )}
      </div>

      {/* ROW 4 — 2 charts side by side */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>

        {/* Trade Distribution */}
        <div className="tv-card">
          <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 12 }}>Trade Distribution</div>
          {hasRecharts && barData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={barData} margin={{ top: 4, right: 4, left: 0, bottom: 24 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" strokeOpacity={0.3} />
                <XAxis dataKey="symbol" tick={{ fill: 'var(--text4)', fontSize: 10 }} tickLine={false} axisLine={false} angle={-40} textAnchor="end" interval={0} />
                <YAxis tickFormatter={_perfYFmt} tick={{ fill: 'var(--text4)', fontSize: 11 }} tickLine={false} axisLine={false} width={55} />
                <Tooltip
                  formatter={(v) => [(v >= 0 ? '+' : '') + '$' + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 }), 'P&L']}
                  contentStyle={tooltipStyle}
                  labelStyle={labelStyle}
                />
                <Bar dataKey="pnl" radius={[3, 3, 0, 0]}>
                  {barData.map((entry, i) => (
                    <Cell key={i} fill={entry.pnl >= 0 ? 'var(--ok)' : 'var(--fail)'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ color: 'var(--text4)', fontSize: 13, textAlign: 'center', padding: '48px 0' }}>
              {!hasRecharts ? 'Chart library not loaded' : 'No closed trades in this period'}
            </div>
          )}
        </div>

        {/* Drawdown */}
        <div className="tv-card">
          <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 12 }}>Drawdown</div>
          {hasRecharts && drawdownData.length > 1 ? (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={drawdownData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="var(--fail)" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="var(--fail)" stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" strokeOpacity={0.3} />
                <XAxis dataKey="date" tick={{ fill: 'var(--text4)', fontSize: 11 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                <YAxis tickFormatter={(v) => v.toFixed(1) + '%'} tick={{ fill: 'var(--text4)', fontSize: 11 }} tickLine={false} axisLine={false} width={52} />
                <Tooltip
                  formatter={(v) => [v.toFixed(2) + '%', 'Drawdown']}
                  contentStyle={tooltipStyle}
                  labelStyle={labelStyle}
                />
                <Area type="monotone" dataKey="drawdown" stroke="var(--fail)" strokeWidth={2} fill="url(#ddGrad)" dot={false} activeDot={{ r: 4 }} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ color: 'var(--text4)', fontSize: 13, textAlign: 'center', padding: '48px 0' }}>
              {!hasRecharts ? 'Chart library not loaded' : 'No portfolio history in this period'}
            </div>
          )}
        </div>

      </div>

      {/* ROW 5 — Per-symbol breakdown */}
      <div className="tv-card">
        <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 12 }}>Per-Symbol Breakdown</div>
        {symbolBreakdown.length === 0 ? (
          <div style={{ color: 'var(--text4)', fontSize: 13, textAlign: 'center', padding: '20px 0' }}>
            No closed trades in this period
          </div>
        ) : (
          <table className="tv-table" style={{ width: '100%' }}>
            <thead>
              <tr>
                <th>SYMBOL</th>
                <th style={{ textAlign: 'right' }}>TRADES</th>
                <th style={{ textAlign: 'right' }}>WIN RATE</th>
                <th style={{ textAlign: 'right' }}>AVG WIN</th>
                <th style={{ textAlign: 'right' }}>AVG LOSS</th>
                <th style={{ textAlign: 'right' }}>NET P&amp;L</th>
                <th style={{ textAlign: 'right' }}>BEST</th>
                <th style={{ textAlign: 'right' }}>WORST</th>
              </tr>
            </thead>
            <tbody>
              {symbolBreakdown.map(row => (
                <tr key={row.symbol}>
                  <td><span className="tv-chip">{row.symbol}</span></td>
                  <td style={{ textAlign: 'right' }}>{row.trades}</td>
                  <td style={{ textAlign: 'right' }}>{row.winRate}</td>
                  <td style={{ textAlign: 'right', color: 'var(--ok)' }}>{hideValues ? '••••' : fmt(row.avgWin)}</td>
                  <td style={{ textAlign: 'right', color: 'var(--fail)' }}>{hideValues ? '••••' : fmt(row.avgLoss)}</td>
                  <td style={{ textAlign: 'right', color: row.netPnl >= 0 ? 'var(--ok)' : 'var(--fail)', fontWeight: 500 }}>
                    {hideValues ? '••••' : (row.netPnl >= 0 ? '+' : '') + fmt(row.netPnl)}
                  </td>
                  <td style={{ textAlign: 'right', color: 'var(--ok)' }}>{hideValues ? '••••' : '+' + fmt(row.best)}</td>
                  <td style={{ textAlign: 'right', color: 'var(--fail)' }}>{hideValues ? '••••' : fmt(row.worst)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

    </div>
  );
}

window.PerformanceScreen = PerformanceScreen;
