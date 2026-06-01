/* ===== PERFORMANCE SCREEN ===== */

const { useState: usePerfState, useEffect: usePerfEffect, useMemo: usePerfMemo } = React;

/* ── helpers ── */
function _perfYFmt(v) {
  const a = Math.abs(v);
  if (a >= 1_000_000) return '$' + (v / 1_000_000).toFixed(2) + 'M';
  if (a >= 1_000)     return '$' + (v / 1_000).toFixed(1) + 'K';
  return '$' + v.toFixed(0);
}

function _perfFeeFmt(v) {
  const a = Math.abs(v);
  if (a >= 1_000) return '$' + (v / 1_000).toFixed(2) + 'K';
  return '$' + v.toFixed(2);
}

function _dateTick(ts, range) {
  const d = new Date(ts);
  if (range === '24H') return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function _perfFilter(data, range, customFrom, customTo) {
  if (!data?.length) return [];
  if (range === 'custom' && customFrom && customTo) {
    const from = new Date(customFrom).getTime();
    const to   = new Date(customTo).getTime() + 86_400_000;
    return data.filter(d => {
      const t = new Date(d.timestamp).getTime();
      return t >= from && t <= to;
    });
  }
  const msMap = { '24H': 86_400_000, '7D': 7 * 86_400_000, '30D': 30 * 86_400_000, '1Y': 365 * 86_400_000 };
  const ms = msMap[range];
  if (ms == null) return data;
  const cutoff = Date.now() - ms;
  return data.filter(d => new Date(d.timestamp).getTime() >= cutoff);
}

/* ── KPI card ── */
function PerfKpiCard({ label, value, color }) {
  return (
    <div style={{
      flex: 1,
      background: 'var(--panel2)',
      border: '1px solid var(--line)',
      borderRadius: 10,
      padding: '14px 16px',
    }}>
      <div style={{ fontSize: 13, color: 'var(--text4)', marginBottom: 8 }}>{label}</div>
      <div className="tv-num" style={{ fontSize: 28, color: color || 'var(--text)' }}>{value}</div>
    </div>
  );
}

/* ── Portfolio line chart ── */
function PortfolioLineChart({ data, range }) {
  const R = window.Recharts || {};
  const { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } = R;

  const chartData = usePerfMemo(() => data.map(d => ({
    date:    d.timestamp,
    total:   d.total_value   || 0,
    tokens:  d.tokens_value  || 0,
    lp:      d.lp_value      || 0,
    hedge:   d.hedge_value   || 0,
    lending: d.lending_value || 0,
  })), [data]);

  if (!LineChart || chartData.length < 2) {
    return (
      <div style={{ color: 'var(--text4)', fontSize: 13, textAlign: 'center', padding: '60px 0' }}>
        {!LineChart ? 'Chart library not loaded' : 'No data for this period'}
      </div>
    );
  }

  const tickFmt = (ts) => _dateTick(ts, range);
  const LINES = [
    { key: 'total',   name: 'Total Portfolio', color: '#ffffff' },
    { key: 'tokens',  name: 'Tokens',          color: '#4e9eff' },
    { key: 'lp',      name: 'LP Positions',    color: 'var(--ok)' },
    { key: 'hedge',   name: 'Hedge PnL',       color: '#f97316' },
    { key: 'lending', name: 'Lending Net',     color: '#9b59ff' },
  ];

  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" strokeOpacity={0.2} />
        <XAxis
          dataKey="date"
          tickFormatter={tickFmt}
          tick={{ fill: 'var(--text4)', fontSize: 11 }}
          tickLine={false} axisLine={false}
          interval="preserveStartEnd"
        />
        <YAxis
          tickFormatter={_perfYFmt}
          tick={{ fill: 'var(--text4)', fontSize: 11 }}
          tickLine={false} axisLine={false}
          width={58}
        />
        <Tooltip
          contentStyle={{ background: 'var(--panel)', border: '1px solid var(--line)', fontSize: 12, borderRadius: 6 }}
          labelStyle={{ color: 'var(--text)', marginBottom: 4 }}
          labelFormatter={tickFmt}
          formatter={(v, name) => ['$' + v.toLocaleString(undefined, { maximumFractionDigits: 0 }), name]}
        />
        <Legend
          verticalAlign="top"
          height={28}
          iconType="circle"
          iconSize={8}
          wrapperStyle={{ fontSize: 11, color: 'var(--text3)', paddingBottom: 8 }}
        />
        {LINES.map(l => (
          <Line
            key={l.key}
            type="monotone"
            dataKey={l.key}
            name={l.name}
            stroke={l.color}
            strokeWidth={l.key === 'total' ? 2 : 1.5}
            dot={false}
            activeDot={{ r: 3 }}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

/* ── Fees composed chart ── */
function FeesComposedChart({ data, range }) {
  const R = window.Recharts || {};
  const { ComposedChart, Line, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } = R;

  const chartData = usePerfMemo(() => data.map(d => ({
    date:     d.timestamp,
    lpHedge:  (d.lp_value || 0) + (d.hedge_value || 0),
    fees:     d.total_fees || 0,
  })), [data]);

  if (!ComposedChart || chartData.length < 2) {
    return (
      <div style={{ color: 'var(--text4)', fontSize: 13, textAlign: 'center', padding: '60px 0' }}>
        {!ComposedChart ? 'Chart library not loaded' : 'No data for this period'}
      </div>
    );
  }

  const tickFmt = (ts) => _dateTick(ts, range);

  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="feesAreaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor="#4caf50" stopOpacity={0.4} />
            <stop offset="95%" stopColor="#4caf50" stopOpacity={0.05} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" strokeOpacity={0.2} />
        <XAxis
          dataKey="date"
          tickFormatter={tickFmt}
          tick={{ fill: 'var(--text4)', fontSize: 11 }}
          tickLine={false} axisLine={false}
          interval="preserveStartEnd"
        />
        <YAxis
          yAxisId="left"
          tickFormatter={_perfYFmt}
          tick={{ fill: 'var(--text4)', fontSize: 11 }}
          tickLine={false} axisLine={false}
          width={58}
        />
        <YAxis
          yAxisId="right"
          orientation="right"
          tickFormatter={_perfFeeFmt}
          tick={{ fill: 'var(--text4)', fontSize: 11 }}
          tickLine={false} axisLine={false}
          width={58}
        />
        <Tooltip
          contentStyle={{ background: 'var(--panel)', border: '1px solid var(--line)', fontSize: 12, borderRadius: 6 }}
          labelStyle={{ color: 'var(--text)', marginBottom: 4 }}
          labelFormatter={tickFmt}
          formatter={(v, name) => ['$' + v.toLocaleString(undefined, { maximumFractionDigits: 2 }), name]}
        />
        <Legend
          verticalAlign="top"
          height={28}
          iconType="circle"
          iconSize={8}
          wrapperStyle={{ fontSize: 11, color: 'var(--text3)', paddingBottom: 8 }}
        />
        <Line
          yAxisId="left"
          type="monotone"
          dataKey="lpHedge"
          name="LP + Hedge Value"
          stroke="#9b59ff"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 3 }}
        />
        <Area
          yAxisId="right"
          type="monotone"
          dataKey="fees"
          name="Accrued Fees"
          stroke="#4caf50"
          strokeWidth={1.5}
          fill="url(#feesAreaGrad)"
          dot={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/* ── Closed LP table ── */
function ClosedLpTable({ rows }) {
  if (!rows?.length) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 120, color: 'var(--text4)', fontSize: 13 }}>
        No closed LP positions yet
      </div>
    );
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="tv-table" style={{ width: '100%' }}>
        <thead>
          <tr>
            <th>PAIR</th>
            <th>CHAIN</th>
            <th style={{ textAlign: 'right' }}>ENTRY DATE</th>
            <th style={{ textAlign: 'right' }}>EXIT DATE</th>
            <th style={{ textAlign: 'right' }}>P&amp;L</th>
            <th style={{ textAlign: 'right' }}>FEES EARNED</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const pnl = (r.exit_value || 0) - (r.entry_value || 0) + (r.total_fees || 0);
            return (
              <tr key={i}>
                <td><span className="tv-chip">{r.pair || '—'}</span></td>
                <td style={{ color: 'var(--text3)' }}>{r.chain || '—'}</td>
                <td style={{ textAlign: 'right', color: 'var(--text3)' }}>{r.entry_date || '—'}</td>
                <td style={{ textAlign: 'right', color: 'var(--text3)' }}>{r.exit_date  || '—'}</td>
                <td style={{ textAlign: 'right', color: pnl >= 0 ? 'var(--ok)' : 'var(--fail)', fontWeight: 500 }}>
                  {(pnl >= 0 ? '+' : '') + fmt(pnl)}
                </td>
                <td style={{ textAlign: 'right', color: 'var(--ok)' }}>
                  {fmt(r.total_fees || 0)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ── Closed Hedges table ── */
function ClosedHedgesTable({ rows }) {
  if (!rows?.length) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 120, color: 'var(--text4)', fontSize: 13 }}>
        No closed hedges yet
      </div>
    );
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="tv-table" style={{ width: '100%' }}>
        <thead>
          <tr>
            <th>MARKET</th>
            <th>DIR</th>
            <th style={{ textAlign: 'right' }}>ENTRY PRICE</th>
            <th style={{ textAlign: 'right' }}>EXIT PRICE</th>
            <th style={{ textAlign: 'right' }}>SIZE</th>
            <th style={{ textAlign: 'right' }}>P&amp;L</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td><span className="tv-chip">{r.market || '—'}</span></td>
              <td style={{ color: r.direction === 'long' ? 'var(--ok)' : 'var(--fail)' }}>
                {(r.direction || '—').toUpperCase()}
              </td>
              <td style={{ textAlign: 'right', color: 'var(--text3)' }}>{r.entry_price ? fmt(r.entry_price, 2) : '—'}</td>
              <td style={{ textAlign: 'right', color: 'var(--text3)' }}>{r.exit_price  ? fmt(r.exit_price,  2) : '—'}</td>
              <td style={{ textAlign: 'right' }}>{r.size_usd ? fmt(r.size_usd, 0) : '—'}</td>
              <td style={{ textAlign: 'right', color: (r.pnl_usd || 0) >= 0 ? 'var(--ok)' : 'var(--fail)', fontWeight: 500 }}>
                {r.pnl_usd != null ? (r.pnl_usd >= 0 ? '+' : '') + fmt(r.pnl_usd) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── MAIN SCREEN ── */
function PerformanceScreen({ hideValues }) {
  const [mode,         setMode]         = usePerfState('⚡ Performance');
  const [range,        setRange]        = usePerfState('7D');
  const [customFrom,   setCustomFrom]   = usePerfState('');
  const [customTo,     setCustomTo]     = usePerfState('');
  const [appliedFrom,  setAppliedFrom]  = usePerfState('');
  const [appliedTo,    setAppliedTo]    = usePerfState('');
  const [allChart,     setAllChart]     = usePerfState([]);
  const [closedPos,    setClosedPos]    = usePerfState({ closed_lps: [], closed_hedges: [] });
  const [loading,      setLoading]      = usePerfState(true);

  usePerfEffect(() => {
    Promise.all([
      fetch('/api/history/portfolio-chart?days=9999').then(r => r.json()).catch(() => []),
      fetch('/api/history/closed-positions').then(r => r.json()).catch(() => ({})),
    ]).then(([chart, closed]) => {
      setAllChart(Array.isArray(chart) ? chart : []);
      setClosedPos({ closed_lps: closed?.closed_lps || [], closed_hedges: closed?.closed_hedges || [] });
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const isCustom = range === 'custom';

  const filtered = usePerfMemo(() => {
    if (isCustom && appliedFrom && appliedTo) {
      return _perfFilter(allChart, 'custom', appliedFrom, appliedTo);
    }
    return _perfFilter(allChart, range, null, null);
  }, [allChart, range, appliedFrom, appliedTo, isCustom]);

  function applyCustom() {
    if (!customFrom || !customTo) return;
    setAppliedFrom(customFrom);
    setAppliedTo(customTo);
    setRange('custom');
  }

  /* ── KPI calculations ── */
  const kpis = usePerfMemo(() => {
    if (!filtered.length) return { current: 0, start: 0, changeUsd: 0, changePct: null };
    const first = filtered[0].total_value || 0;
    const last  = filtered[filtered.length - 1].total_value || 0;
    const delta = last - first;
    const pct   = first > 0 ? (delta / first * 100) : null;
    return { current: last, start: first, changeUsd: delta, changePct: pct };
  }, [filtered]);

  const MODES = ['↺ Live', '■ Spot P&L', '⚡ Performance'];
  const RANGES = ['24H', '7D', '30D', '1Y', 'All'];

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 320, color: 'var(--text4)', fontSize: 14 }}>
        Loading performance data…
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* ── ROW 1 — Controls ── */}
      <div className="tv-card" style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>

        {/* Mode pills + hide indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {MODES.map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={m === mode ? 'tv-btn primary' : 'tv-btn'}
              style={{ fontSize: 12, padding: '5px 14px' }}
            >{m}</button>
          ))}
          <div style={{ flex: 1 }} />
          <div
            title={hideValues ? 'Values hidden' : 'Values visible'}
            style={{ fontSize: 18, cursor: 'default', opacity: hideValues ? 0.4 : 1 }}
          >
            {hideValues ? '🙈' : '👁'}
          </div>
        </div>

        {/* Range pills + custom */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <span className="tv-label" style={{ fontSize: 11, flexShrink: 0 }}>RANGE:</span>
          <div style={{ display: 'flex', gap: 6 }}>
            {RANGES.map(r => (
              <button
                key={r}
                onClick={() => setRange(r)}
                style={{
                  padding: '4px 14px', borderRadius: 6, border: (r === range && !isCustom) ? '2px solid var(--accent)' : '1px solid var(--line)',
                  background: 'transparent', cursor: 'pointer', fontSize: 12,
                  color: (r === range && !isCustom) ? 'var(--accent)' : 'var(--text3)',
                  fontWeight: (r === range && !isCustom) ? 600 : 400,
                }}
              >{r}</button>
            ))}
          </div>

          {/* Custom date range */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 8 }}>
            <span className="tv-label" style={{ fontSize: 11, flexShrink: 0 }}>CUSTOM:</span>
            <input
              type="date"
              value={customFrom}
              onChange={e => setCustomFrom(e.target.value)}
              style={{
                background: 'var(--panel2)', border: '1px solid var(--line)', borderRadius: 6,
                color: 'var(--text)', fontSize: 12, padding: '4px 8px', outline: 'none',
              }}
            />
            <span style={{ color: 'var(--text4)', fontSize: 12 }}>→</span>
            <input
              type="date"
              value={customTo}
              onChange={e => setCustomTo(e.target.value)}
              style={{
                background: 'var(--panel2)', border: '1px solid var(--line)', borderRadius: 6,
                color: 'var(--text)', fontSize: 12, padding: '4px 8px', outline: 'none',
              }}
            />
            <button
              className="tv-btn primary"
              style={{ fontSize: 12, padding: '4px 14px' }}
              onClick={applyCustom}
              disabled={!customFrom || !customTo}
            >Apply</button>
            {isCustom && (
              <span style={{ fontSize: 11, color: 'var(--accent)' }}>
                {appliedFrom} → {appliedTo}
              </span>
            )}
          </div>
        </div>

      </div>

      {/* ── ROW 2 — 4 KPI cards ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        <PerfKpiCard
          label="Current Value"
          value={hideValues ? '••••' : fmt(kpis.current, 0)}
        />
        <PerfKpiCard
          label="Period Start"
          value={hideValues ? '••••' : fmt(kpis.start, 0)}
        />
        <PerfKpiCard
          label="Change"
          value={hideValues ? '••••' : (kpis.changeUsd >= 0 ? '+' : '') + fmt(kpis.changeUsd, 0)}
          color={kpis.changeUsd >= 0 ? 'var(--ok)' : 'var(--fail)'}
        />
        <PerfKpiCard
          label="Change %"
          value={kpis.changePct != null
            ? (kpis.changePct >= 0 ? '+' : '') + kpis.changePct.toFixed(2) + '%'
            : '—'}
          color={kpis.changePct == null ? 'var(--text)' : kpis.changePct >= 0 ? 'var(--ok)' : 'var(--fail)'}
        />
      </div>

      {/* ── ROW 3 — Two charts ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div className="tv-card">
          <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 14 }}>Total Portfolio Value</div>
          <PortfolioLineChart data={filtered} range={range} />
        </div>
        <div className="tv-card">
          <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 14 }}>Active Positions &amp; Accrued Fees</div>
          <FeesComposedChart data={filtered} range={range} />
        </div>
      </div>

      {/* ── ROW 4 — Two tables ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div className="tv-card">
          <div className="tv-label" style={{ color: 'var(--text3)', marginBottom: 12 }}>⊟ Closed LP Positions</div>
          <ClosedLpTable rows={closedPos.closed_lps} />
        </div>
        <div className="tv-card">
          <div className="tv-label" style={{ color: 'var(--text3)', marginBottom: 12 }}>⊟ Closed Hedges</div>
          <ClosedHedgesTable rows={closedPos.closed_hedges} />
        </div>
      </div>

    </div>
  );
}

window.PerformanceScreen = PerformanceScreen;
