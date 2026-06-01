/* ===== DASHBOARD SCREEN ===== */

const { useState: useDashState, useEffect: useDashEffect, useMemo: useDashMemo } = React;

function _fgZone(val) {
  if (val == null) return { label: 'N/A', cls: '' };
  if (val < 25) return { label: 'Extreme Fear', cls: 'fail' };
  if (val < 50) return { label: 'Fear', cls: 'warn' };
  if (val < 75) return { label: 'Greed', cls: 'adapt' };
  return { label: 'Extreme Greed', cls: 'ok' };
}

function _yFmt(v) {
  if (Math.abs(v) >= 1_000_000) return '$' + (v / 1_000_000).toFixed(1) + 'M';
  if (Math.abs(v) >= 1_000) return '$' + (v / 1_000).toFixed(0) + 'K';
  return '$' + v.toFixed(0);
}

function DashHeroPill({ label, value }) {
  return (
    <div style={{ background: 'var(--panel2)', borderRadius: 8, padding: '10px 16px', minWidth: 110 }}>
      <div className="tv-label" style={{ marginBottom: 4, fontSize: 10 }}>{label}</div>
      <div className="tv-num" style={{ fontSize: 15 }}>{value}</div>
    </div>
  );
}

function DashBtcCard({ snapshot, fgHistory }) {
  const btc = snapshot?.btc_price;
  const ma200 = snapshot?.btc_200d_ma;
  const fg = snapshot?.fear_greed_index;
  const zone = _fgZone(fg);
  const aboveMa = (btc != null && ma200 != null) ? btc >= ma200 : null;
  const maDiff = (btc && ma200) ? ((btc - ma200) / ma200 * 100) : null;

  return (
    <div className="tv-card">
      <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 10 }}>BTC Macro Zone</div>
      <div className="tv-num" style={{ fontSize: 26, color: aboveMa === null ? 'var(--text)' : aboveMa ? 'var(--ok)' : 'var(--fail)' }}>
        {btc ? fmt(btc, 0) : '—'}
      </div>
      {ma200 != null && (
        <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 4 }}>
          vs 200D MA: {fmt(ma200, 0)}{maDiff != null ? ` (${maDiff >= 0 ? '+' : ''}${maDiff.toFixed(1)}%)` : ''}
        </div>
      )}
      <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span className={`tv-chip ${zone.cls}`}>{fg ?? '—'} {zone.label}</span>
        {fgHistory?.length > 2 && (
          <Sparkline data={[...fgHistory].reverse()} color="var(--accent)" width={80} height={24} />
        )}
      </div>
    </div>
  );
}

function DashLpCard({ lpPositions }) {
  if (!lpPositions?.length) {
    return (
      <div className="tv-card">
        <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 10 }}>LP Health</div>
        <div style={{ color: 'var(--text4)', fontSize: 13 }}>No active LP positions</div>
      </div>
    );
  }
  const inCount = lpPositions.filter(p => p.in_range).length;
  const total = lpPositions.length;
  const allIn = inCount === total;
  const majOut = inCount < total / 2;
  const cls = allIn ? 'ok' : majOut ? 'fail' : 'warn';

  return (
    <div className="tv-card">
      <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 10 }}>LP Health</div>
      <div className="tv-num" style={{ fontSize: 26, color: `var(--${cls})` }}>{inCount} / {total}</div>
      <div style={{ fontSize: 12, color: 'var(--text3)', marginBottom: 10 }}>in range</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {lpPositions.map((pos, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'space-between' }}>
            <span style={{ fontSize: 12, color: 'var(--text2)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{pos.pair}</span>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexShrink: 0 }}>
              {(pos.chain || pos.chain_name) && (
                <span className="tv-chip" style={{ fontSize: 10 }}>{pos.chain || pos.chain_name}</span>
              )}
              <span className={`tv-chip ${pos.in_range ? 'ok' : 'fail'}`} style={{ fontSize: 10 }}>
                {pos.in_range ? 'IN RANGE' : 'OUT'}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DashLendingCard({ aavePositions }) {
  if (!aavePositions?.length) {
    return (
      <div className="tv-card">
        <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 10 }}>Lending Health</div>
        <div style={{ color: 'var(--text4)', fontSize: 13 }}>No active lending positions</div>
      </div>
    );
  }
  const hfs = aavePositions.map(p => p.health_factor).filter(h => h != null && h > 0 && isFinite(h));
  const lowestHF = hfs.length ? Math.min(...hfs) : null;
  const hfCls = lowestHF == null ? 'text' : lowestHF > 2 ? 'ok' : lowestHF > 1.5 ? 'warn' : 'fail';
  const netEquity = aavePositions.reduce((s, p) => s + (p.total_collateral_usd || 0) - (p.total_debt_usd || 0), 0);

  return (
    <div className="tv-card">
      <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 10 }}>Lending Health</div>
      <div className="tv-num" style={{ fontSize: 26, color: `var(--${hfCls})` }}>
        {lowestHF != null ? lowestHF.toFixed(2) : '—'}
      </div>
      <div style={{ fontSize: 12, color: 'var(--text3)', marginBottom: 8 }}>
        Lowest HF · {aavePositions.length} position{aavePositions.length !== 1 ? 's' : ''}
      </div>
      {lowestHF != null && <HealthBar value={lowestHF} max={5} />}
      <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text2)' }}>
        Net equity: <span className="tv-num">{fmt(netEquity)}</span>
      </div>
    </div>
  );
}

function DashSpotPnlCard({ spotPnl }) {
  const unrealized = spotPnl.reduce((s, h) => s + (h.unrealized_pnl_usd || 0), 0);
  const realizedTotal = spotPnl.reduce((s, h) => s + (h.realized_pnl_usd || 0), 0);

  return (
    <div className="tv-card">
      <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 10 }}>Spot P&amp;L</div>
      <div className="tv-num" style={{ fontSize: 26, color: unrealized >= 0 ? 'var(--ok)' : 'var(--fail)' }}>
        {unrealized >= 0 ? '+' : ''}{fmt(unrealized)}
      </div>
      <div className="tv-label" style={{ marginBottom: 6 }}>Unrealized</div>
      <div className="tv-num" style={{ fontSize: 18, color: realizedTotal >= 0 ? 'var(--ok)' : 'var(--fail)' }}>
        {realizedTotal >= 0 ? '+' : ''}{fmt(realizedTotal)}
      </div>
      <div className="tv-label">Realized (all time)</div>
      <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text3)' }}>
        FIFO cost basis · {spotPnl.length} open position{spotPnl.length !== 1 ? 's' : ''}
      </div>
    </div>
  );
}

function DashEquityChart({ data, range, onRangeChange }) {
  const { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } = window.Recharts || {};

  const dayMs = 86_400_000;
  const rangeDayMap = { '7D': 7, '30D': 30, '90D': 90, 'All': null };
  const days = rangeDayMap[range];
  const filtered = useDashMemo(() => {
    if (!days) return data;
    const cutoff = Date.now() - days * dayMs;
    return data.filter(d => new Date(d.timestamp).getTime() >= cutoff);
  }, [data, range]);

  const chartItems = useDashMemo(() => filtered.map(d => ({
    date: new Date(d.timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    value: d.total_value,
  })), [filtered]);

  const rangePills = ['7D', '30D', '90D', 'All'].map(r => (
    <button
      key={r}
      onClick={() => onRangeChange(r)}
      style={{
        padding: '4px 12px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12,
        background: r === range ? 'var(--accent)' : 'var(--panel3)',
        color: r === range ? '#000' : 'var(--text3)',
        fontWeight: r === range ? 600 : 400,
      }}
    >{r}</button>
  ));

  return (
    <div className="tv-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div className="tv-label" style={{ color: 'var(--accent)' }}>Portfolio Equity</div>
        <div style={{ display: 'flex', gap: 6 }}>{rangePills}</div>
      </div>
      {(!AreaChart || chartItems.length < 2) ? (
        <div style={{ color: 'var(--text4)', fontSize: 13, textAlign: 'center', padding: '32px 0' }}>
          {!AreaChart ? 'Chart library not loaded' : 'No portfolio history yet'}
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={180}>
          <AreaChart data={chartItems} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="dashEquityGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="var(--accent)" stopOpacity={0.2} />
                <stop offset="95%" stopColor="var(--accent)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" strokeOpacity={0.3} />
            <XAxis dataKey="date" tick={{ fill: 'var(--text4)', fontSize: 11 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
            <YAxis tickFormatter={_yFmt} tick={{ fill: 'var(--text4)', fontSize: 11 }} tickLine={false} axisLine={false} width={58} />
            <Tooltip
              formatter={(v) => ['$' + v.toLocaleString(undefined, { maximumFractionDigits: 0 }), 'Portfolio']}
              contentStyle={{ background: 'var(--panel)', border: '1px solid var(--line)', fontSize: 12, borderRadius: 6 }}
              labelStyle={{ color: 'var(--text)' }}
            />
            <Area type="monotone" dataKey="value" stroke="var(--accent)" strokeWidth={2} fill="url(#dashEquityGrad)" dot={false} activeDot={{ r: 4 }} />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

function DashAiBriefCard({ digest, setActiveTab }) {
  const [generating, setGenerating] = useDashState(false);

  async function generate() {
    setGenerating(true);
    try { await api('/api/ai/digest', { method: 'POST' }); } catch (_) {}
    setGenerating(false);
    window.location.reload();
  }

  if (!digest || digest.error) {
    return (
      <div className="tv-card" style={{ flex: 1 }}>
        <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 10 }}>Latest AI Brief</div>
        <div style={{ color: 'var(--text4)', fontSize: 13, marginBottom: 12 }}>No brief generated yet</div>
        <button className="tv-btn primary" onClick={generate} disabled={generating}>
          {generating ? 'Generating…' : 'Generate'}
        </button>
      </div>
    );
  }

  const oor = digest.positions_out_of_range || [];
  const opened = digest.positions_opened || [];
  const closed = digest.positions_closed || [];
  const change = digest.value_change_24h_pct;
  const ts = digest.timestamp ? new Date(digest.timestamp).toLocaleDateString() : '';

  function chipLabel(p) {
    return typeof p === 'string' ? p : (p.pair || p.symbol || JSON.stringify(p));
  }

  return (
    <div className="tv-card" style={{ flex: 1 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div className="tv-label" style={{ color: 'var(--accent)' }}>Latest AI Brief</div>
        <div style={{ fontSize: 11, color: 'var(--text4)' }}>{ts}</div>
      </div>
      {change != null && (
        <div style={{ marginBottom: 10 }}>
          <div className="tv-num" style={{ fontSize: 24, color: change >= 0 ? 'var(--ok)' : 'var(--fail)' }}>
            {fmtPct(change)}
          </div>
          <div className="tv-label">24h change</div>
        </div>
      )}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
        {oor.length === 0
          ? <span className="tv-chip ok">All positions in range</span>
          : oor.map((p, i) => <span key={i} className="tv-chip fail">{chipLabel(p)}</span>)
        }
      </div>
      {opened.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 6, alignItems: 'center' }}>
          <span className="tv-label" style={{ marginRight: 2 }}>Opened:</span>
          {opened.map((p, i) => <span key={i} className="tv-chip adapt">{chipLabel(p)}</span>)}
        </div>
      )}
      {closed.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 6, alignItems: 'center' }}>
          <span className="tv-label" style={{ marginRight: 2 }}>Closed:</span>
          {closed.map((p, i) => <span key={i} className="tv-chip">{chipLabel(p)}</span>)}
        </div>
      )}
      <button className="tv-btn" style={{ marginTop: 10 }} onClick={() => setActiveTab && setActiveTab('aibrief')}>
        View Full Report
      </button>
    </div>
  );
}

function DashOpenPositionsCard({ lpPositions, aavePositions, setActiveTab }) {
  const allPositions = [
    ...(lpPositions || []).map(p => ({
      protocol: (p.protocol || 'LP').replace(/^uniswap/i, 'Uni').replace(/^aerodrome/i, 'Aero').slice(0, 8),
      label: p.pair || 'LP Position',
      chain: p.chain || p.chain_name || '',
      value: p.total_value_usd || 0,
      status: p.in_range ? 'IN RANGE' : 'OUT OF RANGE',
      statusCls: p.in_range ? 'ok' : 'fail',
    })),
    ...(aavePositions || []).map(p => {
      const hf = p.health_factor;
      return {
        protocol: 'Aave',
        label: p.wallet_label || p.chain_name || 'Aave V3',
        chain: p.chain_name || '',
        value: p.total_collateral_usd || 0,
        status: !hf ? 'N/A' : hf > 2 ? 'HEALTHY' : hf > 1.5 ? 'AT RISK' : 'DANGER',
        statusCls: !hf ? '' : hf > 2 ? 'ok' : hf > 1.5 ? 'warn' : 'fail',
      };
    }),
  ].sort((a, b) => b.value - a.value).slice(0, 3);

  return (
    <div className="tv-card" style={{ flex: 1 }}>
      <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 10 }}>Open Positions</div>
      {allPositions.length === 0 && (
        <div style={{ color: 'var(--text4)', fontSize: 13 }}>No open positions</div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {allPositions.map((pos, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="tv-chip" style={{ fontSize: 10, minWidth: 36, textAlign: 'center' }}>{pos.protocol}</span>
            <span style={{ flex: 1, fontSize: 13, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{pos.label}</span>
            {pos.chain && <span className="tv-chip" style={{ fontSize: 10 }}>{pos.chain}</span>}
            <span className="tv-num" style={{ fontSize: 13 }}>{fmt(pos.value)}</span>
            <span className={`tv-chip ${pos.statusCls}`} style={{ fontSize: 10, whiteSpace: 'nowrap' }}>{pos.status}</span>
          </div>
        ))}
      </div>
      {setActiveTab && (
        <button className="tv-btn" style={{ marginTop: 12 }} onClick={() => setActiveTab('portfolio')}>
          View All
        </button>
      )}
    </div>
  );
}

function DashboardScreen({ hideValues, setActiveTab }) {
  const [portfolio, setPortfolio] = useDashState(null);
  const [allChartData, setAllChartData] = useDashState([]);
  const [marketData, setMarketData] = useDashState(null);
  const [digest, setDigest] = useDashState(null);
  const [spotPnl, setSpotPnl] = useDashState([]);
  const [stablecoins, setStablecoins] = useDashState(null);
  const [chartRange, setChartRange] = useDashState('30D');
  const [loading, setLoading] = useDashState(true);

  useDashEffect(() => {
    Promise.all([
      fetch('/api/portfolio').then(r => r.json()).catch(() => null),
      fetch('/api/history/portfolio-chart?days=9999').then(r => r.json()).catch(() => []),
      fetch('/api/market-data').then(r => r.json()).catch(() => null),
      fetch('/api/ai/digest/latest').then(r => r.json()).catch(() => null),
      fetch('/api/spot/pnl').then(r => r.json()).catch(() => []),
      fetch('/api/spot/stablecoins').then(r => r.json()).catch(() => null),
    ]).then(([port, chart, mkt, dig, spot, stables]) => {
      setPortfolio(port);
      setAllChartData(Array.isArray(chart) ? chart : (chart?.data || chart?.points || chart?.history || []));
      setMarketData(mkt);
      setDigest(dig?.error ? null : dig);
      setSpotPnl(Array.isArray(spot) ? spot : []);
      setStablecoins(stables);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const spotTotal = spotPnl.reduce((s, h) => s + (h.current_value_usd || 0), 0);
  const stableTotal = stablecoins?.total_usd || 0;
  const lpTotal = (portfolio?.lp_positions || []).reduce((s, p) => s + (p.total_value_usd || 0), 0);
  const lendingTotal = (portfolio?.aave_positions || []).reduce((s, p) => s + (p.total_collateral_usd || 0), 0);
  const defiTotal = portfolio?.total_value || 0;
  const grandTotal = defiTotal + spotTotal + stableTotal;

  const snapshot = marketData?.snapshot || {};
  const fgHistory = marketData?.fg_history || [];

  const change24h = digest?.value_change_24h_pct;
  const change24hUsd = (digest?.total_value_usd && change24h != null)
    ? digest.total_value_usd * change24h / 100
    : null;

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 320, color: 'var(--text4)', fontSize: 14 }}>
        Loading dashboard…
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* ROW 1 — Hero strip */}
      <div className="tv-card" style={{ borderTop: '3px solid var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <div className="tv-label" style={{ marginBottom: 6, fontSize: 11 }}>TOTAL PORTFOLIO VALUE</div>
          <div className="tv-num" style={{ fontSize: 36 }}>
            {hideValues ? '••••••' : fmt(grandTotal, 0)}
          </div>
          {change24h != null && (
            <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
              <span style={{ color: change24h >= 0 ? 'var(--ok)' : 'var(--fail)', fontWeight: 500 }}>
                {fmtPct(change24h)}
              </span>
              {change24hUsd != null && !hideValues && (
                <span style={{ color: change24h >= 0 ? 'var(--ok)' : 'var(--fail)' }}>
                  ({change24hUsd >= 0 ? '+' : ''}{fmt(change24hUsd, 0)})
                </span>
              )}
              <span style={{ color: 'var(--text4)', fontSize: 11 }}>24h</span>
            </div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <DashHeroPill label="Spot" value={hideValues ? '••••' : fmt(spotTotal, 0)} />
          <DashHeroPill label="DeFi LP" value={hideValues ? '••••' : fmt(lpTotal, 0)} />
          <DashHeroPill label="Lending" value={hideValues ? '••••' : fmt(lendingTotal, 0)} />
          <DashHeroPill label="Stablecoins" value={hideValues ? '••••' : fmt(stableTotal, 0)} />
        </div>
      </div>

      {/* ROW 2 — Equity sparkline */}
      <DashEquityChart data={allChartData} range={chartRange} onRangeChange={setChartRange} />

      {/* ROW 3 — 4 KPI cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        <DashBtcCard snapshot={snapshot} fgHistory={fgHistory} />
        <DashLpCard lpPositions={portfolio?.lp_positions} />
        <DashLendingCard aavePositions={portfolio?.aave_positions} />
        <DashSpotPnlCard spotPnl={spotPnl} />
      </div>

      {/* ROW 4 — 2 side-by-side cards */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <DashAiBriefCard digest={digest} setActiveTab={setActiveTab} />
        <DashOpenPositionsCard lpPositions={portfolio?.lp_positions} aavePositions={portfolio?.aave_positions} setActiveTab={setActiveTab} />
      </div>

    </div>
  );
}

window.DashboardScreen = DashboardScreen;
