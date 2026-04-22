// ===== MARKET DATA TAB — DB-backed with manual refresh =====
let marketCache = null;

async function computeMarketData(force) {
  if (marketCache && !force) return;
  const btn = document.getElementById('marketBtn');
  const out = document.getElementById('marketOutput');
  btn.disabled = true; btn.innerHTML = '<i data-lucide="loader" style="width:14px;height:14px;animation:spin 1s linear infinite"></i>'; lucide.createIcons({nodes:[btn]});
  out.innerHTML = '<div style="color:#8892b0">Loading market data...</div>';

  try {
    const url = force ? '/api/market-data/refresh' : '/api/market-data';
    const opts = force ? {method: 'POST'} : {};
    const resp = await fetch(url, opts);
    if (!resp.ok) throw new Error(resp.statusText);
    const raw = await resp.json();
    marketCache = raw;
    renderMarketData(raw, out);
    var tsEl = document.getElementById('marketLastUpdated');
    if (tsEl) {
      var snap = raw.snapshot || {};
      if (snap.timestamp) {
        var d = new Date(snap.timestamp + 'Z');
        tsEl.textContent = 'Last Updated: ' + d.toLocaleDateString('en-GB', {day:'2-digit',month:'2-digit',year:'numeric'}) + ' ' + d.toLocaleTimeString('en-GB', {hour:'2-digit',minute:'2-digit'});
      }
    }
  } catch (e) {
    out.innerHTML = '<div style="color:#ff6b6b;padding:20px">Error: ' + e.message + '</div>';
  }
  btn.disabled = false; btn.innerHTML = '<i data-lucide="refresh-cw" style="width:14px;height:14px"></i>'; lucide.createIcons({nodes:[btn]});
}

function renderMarketData(raw, out) {
  const s = raw.snapshot || {};
  const lending = raw.lending || {};
  const lpPools = raw.lp_pools || {};
  const fgHist = raw.fg_history || [];
  const sc7d = raw.stablecoin_7d_change;
  const macroRows = raw.macro || [];

  const fmt = v => '$' + Math.round(v).toLocaleString('en-US');
  const fmtB = v => {
    if (v >= 1e12) return '$' + (v / 1e12).toFixed(2) + 'T';
    if (v >= 1e9) return '$' + (v / 1e9).toFixed(1) + 'B';
    if (v >= 1e6) return '$' + (v / 1e6).toFixed(1) + 'M';
    return '$' + Math.round(v).toLocaleString();
  };
  const chg = v => v != null ? ('<span class="' + (v >= 0 ? 'positive' : 'negative') + '">' + (v >= 0 ? '+' : '') + v.toFixed(2) + '%</span>') : '';
  const fgColor = v => v >= 75 ? '#51cf66' : v >= 55 ? '#64ffda' : v >= 45 ? '#ffa94d' : v >= 25 ? '#ff922b' : '#ff6b6b';
  const fgGauge = v => {
    const r = 80, cx = 100, cy = 95, sw = 16;
    const colors = [
      {start:0,end:20,color:'#ff6b6b'},{start:20,end:40,color:'#ff922b'},
      {start:40,end:60,color:'#ffa94d'},{start:60,end:80,color:'#64ffda'},{start:80,end:100,color:'#51cf66'}
    ];
    let arcs = '';
    colors.forEach(c => {
      const a1 = Math.PI + (c.start / 100) * Math.PI;
      const a2 = Math.PI + (c.end / 100) * Math.PI;
      const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
      const x2 = cx + r * Math.cos(a2), y2 = cy + r * Math.sin(a2);
      arcs += '<path d="M' + x1 + ',' + y1 + ' A' + r + ',' + r + ' 0 0 1 ' + x2 + ',' + y2 + '" fill="none" stroke="' + c.color + '" stroke-width="' + sw + '" stroke-linecap="round"/>';
    });
    const na = Math.PI + (v / 100) * Math.PI;
    const nx = cx + (r - 10) * Math.cos(na), ny = cy + (r - 10) * Math.sin(na);
    const needle = '<line x1="' + cx + '" y1="' + cy + '" x2="' + nx + '" y2="' + ny + '" stroke="#fff" stroke-width="3" stroke-linecap="round"/>' +
      '<circle cx="' + cx + '" cy="' + cy + '" r="5" fill="#fff"/>';
    const labels = '<text x="12" y="98" fill="#8892b0" font-size="10" font-family="sans-serif">0</text>' +
      '<text x="95" y="10" fill="#8892b0" font-size="10" font-family="sans-serif">50</text>' +
      '<text x="182" y="98" fill="#8892b0" font-size="10" font-family="sans-serif">100</text>';
    return '<div style="text-align:center"><svg viewBox="0 0 200 110" width="240" height="132">' + arcs + needle + labels + '</svg></div>';
  };

  function volLabel(v) {
    if (v == null) return '';
    if (v < 30) return '<span class="positive">Low (' + v.toFixed(0) + '%)</span>';
    if (v < 60) return 'Normal (' + v.toFixed(0) + '%)';
    return '<span class="negative">High (' + v.toFixed(0) + '%)</span>';
  }

  function row(label, value) {
    var display = (value != null && value !== '') ? value : '<span style="color:#555">N/A</span>';
    return '<div class="row"><span class="label">' + label + '</span><span class="value">' + display + '</span></div>';
  }
  function rowClassed(label, value, cls) {
    if (value == null) return '<div class="row"><span class="label">' + label + '</span><span class="value" style="color:#555">N/A</span></div>';
    return '<div class="row"><span class="label">' + label + '</span><span class="value ' + cls + '">' + value + '</span></div>';
  }

  let html = '';
  const ts = s.timestamp ? new Date(s.timestamp + 'Z').toLocaleString() : 'N/A';

  // === ROW 1: BTC + ETH, Fear&Greed, Macro ===
  html += '<div class="mkt-row">';

  // BTC tile
  html += '<div class="mkt-sm">' +
    '<div class="section-title" style="margin-top:0">' + li('bitcoin', 16, '#f7931a') + ' Bitcoin</div>' +
    '<div class="highlight" style="font-size:22px">' + (s.btc_price ? fmt(s.btc_price) : '<span style="color:#555">N/A</span>') + '</div>' +
    '<div style="margin:4px 0">' + (s.btc_24h_change != null ? chg(s.btc_24h_change) + ' (24h)' : '<span style="color:#555">24h: N/A</span>') + '</div>' +
    row('Dominance', s.btc_dominance != null ? s.btc_dominance.toFixed(1) + '%' : null) +
    row('200D MA', s.btc_200d_ma != null && s.btc_price ? fmt(s.btc_200d_ma) + ' (' + (s.btc_price > s.btc_200d_ma ? '+' : '') + (((s.btc_price - s.btc_200d_ma) / s.btc_200d_ma) * 100).toFixed(1) + '%)' : null) +
    rowClassed('7d Return', s.btc_return_7d != null ? (s.btc_return_7d >= 0 ? '+' : '') + s.btc_return_7d.toFixed(2) + '%' : null, s.btc_return_7d >= 0 ? 'positive' : 'negative') +
    rowClassed('30d Return', s.btc_return_30d != null ? (s.btc_return_30d >= 0 ? '+' : '') + s.btc_return_30d.toFixed(2) + '%' : null, s.btc_return_30d >= 0 ? 'positive' : 'negative') +
    row('30d Vol', s.btc_vol_30d != null ? volLabel(s.btc_vol_30d) : null) +
    row('14d Range', s.btc_range_14d != null ? s.btc_range_14d.toFixed(1) + '%' : null) +
    '</div>';

  // ETH tile
  html += '<div class="mkt-sm">' +
    '<div class="section-title" style="margin-top:0">Ξ Ethereum</div>' +
    '<div class="highlight" style="font-size:22px">' + (s.eth_price ? fmt(s.eth_price) : '<span style="color:#555">N/A</span>') + '</div>' +
    '<div style="margin:4px 0">' + (s.eth_24h_change != null ? chg(s.eth_24h_change) + ' (24h)' : '<span style="color:#555">24h: N/A</span>') + '</div>' +
    row('Dominance', s.eth_dominance != null ? s.eth_dominance.toFixed(1) + '%' : null) +
    row('ETH/BTC', s.eth_btc_ratio != null ? s.eth_btc_ratio.toFixed(5) : null) +
    rowClassed('7d Return', s.eth_return_7d != null ? (s.eth_return_7d >= 0 ? '+' : '') + s.eth_return_7d.toFixed(2) + '%' : null, s.eth_return_7d >= 0 ? 'positive' : 'negative') +
    rowClassed('30d Return', s.eth_return_30d != null ? (s.eth_return_30d >= 0 ? '+' : '') + s.eth_return_30d.toFixed(2) + '%' : null, s.eth_return_30d >= 0 ? 'positive' : 'negative') +
    row('30d Vol', s.eth_vol_30d != null ? volLabel(s.eth_vol_30d) : null) +
    row('14d Range', s.eth_range_14d != null ? s.eth_range_14d.toFixed(1) + '%' : null) +
    '</div>';

  // Fear & Greed
  if (s.fear_greed_index != null) {
    var fg7d = fgHist.length >= 7 ? fgHist.slice(0, 7).reduce((a, b) => a + b, 0) / 7 : null;
    var fg30d = fgHist.length > 0 ? fgHist.reduce((a, b) => a + b, 0) / fgHist.length : null;
    var fgLabel = s.fear_greed_index >= 75 ? 'Extreme Greed' : s.fear_greed_index >= 55 ? 'Greed' : s.fear_greed_index >= 45 ? 'Neutral' : s.fear_greed_index >= 25 ? 'Fear' : 'Extreme Fear';
    var fgTrend = (fg7d != null && fg30d != null) ? (fg7d > fg30d ? '<span class="positive">↑ Improving</span>' : '<span class="negative">↓ Declining</span>') : '';
    html += '<div class="mkt-sm">' +
      '<div class="section-title" style="margin-top:0">' + li('heart', 16) + ' Fear & Greed</div>' +
      fgGauge(s.fear_greed_index) +
      '<div style="text-align:center;color:' + fgColor(s.fear_greed_index) + ';font-weight:700;font-size:18px;margin-top:-8px">' + s.fear_greed_index + ' — ' + fgLabel + '</div>' +
      '<div style="margin-top:8px;font-size:12px">' +
      (fg7d != null ? row('7d Avg', fg7d.toFixed(0)) : '') +
      (fg30d != null ? row('30d Avg', fg30d.toFixed(0)) : '') +
      (fgTrend ? row('Trend', fgTrend) : '') +
      '</div></div>';
  } else {
    html += '<div class="mkt-sm"><div style="color:#8892b0;padding:20px">Fear & Greed unavailable</div></div>';
  }

  // Macro
  if (macroRows.length > 0) {
    html += '<div class="mkt-lg">' +
      '<div class="section-title" style="margin-top:0">' + li('landmark', 16) + ' Macro</div>' +
      '<table style="width:100%;font-size:11px;border-collapse:collapse">' +
      '<thead><tr style="color:#8892b0;border-bottom:1px solid #222"><th style="text-align:left;padding:2px 4px">Metric</th><th style="text-align:right;padding:2px 4px">Value</th><th style="text-align:left;padding:2px 6px">Comment</th></tr></thead><tbody>';
    macroRows.forEach(r => {
      html += '<tr style="border-bottom:1px solid #1a1a2e"><td style="padding:3px 4px;color:#e0e0e0;white-space:nowrap">' + esc(r.metric) + '</td>' +
        '<td style="padding:3px 4px;text-align:right;color:#64ffda;font-weight:600;white-space:nowrap">' + esc(r.value) + '</td>' +
        '<td style="padding:3px 6px;color:#8892b0">' + esc(r.comment) + '</td></tr>';
    });
    html += '</tbody></table></div>';
  } else {
    html += '<div class="mkt-sm"><div class="section-title" style="margin-top:0">' + li('landmark', 16) + ' Macro</div><div style="color:#8892b0;font-size:12px;padding:12px">No macro data</div></div>';
  }

  html += '</div>';

  // === ROW 2: Market Overview + Futures ===
  html += '<div class="mkt-row">';

  html += '<div class="mkt-sm">' +
    '<div class="section-title" style="margin-top:0">' + li('globe', 16) + ' Market Overview</div>' +
    row('Total Market Cap', s.total_market_cap != null ? fmtB(s.total_market_cap) : null) +
    row('24h Volume', s.total_volume_24h != null ? fmtB(s.total_volume_24h) : null) +
    row('Stablecoin Supply', s.stablecoin_supply != null ? fmtB(s.stablecoin_supply) : null) +
    (sc7d != null ? rowClassed('Stablecoin 7d', (sc7d >= 0 ? '+' : '') + sc7d.toFixed(2) + '%', sc7d >= 0 ? 'positive' : 'negative') : row('Stablecoin 7d', null)) +
    row('ETH Staking APR', s.eth_staking_apr != null ? s.eth_staking_apr.toFixed(1) + '%' : null) +
    row('BTC Deribit Index', s.btc_index_price != null ? fmt(s.btc_index_price) : null) +
    row('Spot-Index Spread', s.btc_index_price != null && s.btc_price != null ? fmt(s.btc_price - s.btc_index_price) : null) +
    row('DeFi TVL', s.total_defi_tvl != null ? fmtB(s.total_defi_tvl) : null) +
    '</div>';

  // Futures
  html += '<div class="mkt-sm">' +
    '<div class="section-title" style="margin-top:0">' + li('bar-chart-3', 16) + ' Futures (Bybit)</div>' +
    '<table class="hedge-table" style="font-size:11px"><thead><tr><th style="text-align:left"></th><th>Funding</th><th>Ann.</th><th>OI</th></tr></thead><tbody>';
  [['BTC', 'btc'], ['ETH', 'eth'], ['SOL', 'sol']].forEach(([label, prefix]) => {
    const fr = s[prefix + '_funding_rate'];
    const oi = s[prefix + '_open_interest'];
    if (fr != null) {
      const ann = fr * 3 * 365 * 100;
      html += '<tr><td>' + label + '</td><td>' + (fr * 100).toFixed(4) + '%</td>' +
        '<td class="' + (ann >= 0 ? 'positive' : 'negative') + '">' + ann.toFixed(1) + '%</td>' +
        '<td>' + (oi ? fmtB(oi) : '-') + '</td></tr>';
    }
  });
  html += '</tbody></table></div>';

  html += '</div>';

  // === ROW 3: Lending + LP Pools ===
  const hasLending = Object.keys(lending).length > 0;
  const hasLpPools = Object.keys(lpPools).length > 0;
  if (hasLending || hasLpPools) {
    html += '<div class="mkt-row">';

    if (hasLending) {
      html += '<div class="mkt-lg">' +
        '<div class="section-title" style="margin-top:0">' + li('landmark', 16) + ' Lending Rates (Aave V3)</div>' +
        '<table class="hedge-table" style="font-size:11px"><thead><tr><th style="text-align:left">Asset</th><th>Chain</th><th>Supply</th><th>Borrow</th><th>Spread</th></tr></thead><tbody>';
      Object.keys(lending).sort((a, b) => {
        const aa = lending[a], bb = lending[b];
        return (aa.asset || '').localeCompare(bb.asset || '') || (aa.chain || '').localeCompare(bb.chain || '');
      }).forEach(key => {
        const r = lending[key];
        const chain = (r.chain || '').charAt(0).toUpperCase() + (r.chain || '').slice(1);
        const spread = (r.borrow || 0) - (r.supply || 0);
        html += '<tr><td style="text-align:left">' + tokenIcon(r.asset || '') + ' ' + esc(r.asset || '') + '</td>' +
          '<td>' + chainIcon(chain) + '</td>' +
          '<td class="positive">' + (r.supply || 0).toFixed(2) + '%</td>' +
          '<td class="negative">' + (r.borrow || 0).toFixed(2) + '%</td>' +
          '<td style="color:#8892b0">' + spread.toFixed(2) + '%</td></tr>';
      });
      html += '</tbody></table></div>';
    }

    if (hasLpPools) {
      html += '<div class="mkt-lg">' +
        '<div class="section-title" style="margin-top:0">' + li('droplets', 16) + ' LP Pools (Uniswap V3)</div>' +
        '<table class="hedge-table" style="font-size:11px"><thead><tr><th style="text-align:left">Pool</th><th>Chain</th><th>Fee APR</th><th>TVL</th><th>24h Vol</th></tr></thead><tbody>';
      Object.keys(lpPools).sort((a, b) => {
        const pa = a.split('_'), pb = b.split('_');
        return pa.slice(1).join('_').localeCompare(pb.slice(1).join('_')) || pa[0].localeCompare(pb[0]);
      }).forEach(key => {
        const p = lpPools[key];
        const chain = (p.chain || '').charAt(0).toUpperCase() + (p.chain || '').slice(1);
        html += '<tr><td style="text-align:left">' + esc(p.asset || key.split('_').slice(1).join('/')) + '</td>' +
          '<td>' + chainIcon(chain) + '</td>' +
          '<td class="positive">' + (p.apyBase || 0).toFixed(1) + '%</td>' +
          '<td>' + fmtB(p.tvl || 0) + '</td>' +
          '<td>' + (p.vol1d > 0 ? fmtB(p.vol1d) : '-') + '</td></tr>';
      });
      html += '</tbody></table></div>';
    }

    html += '</div>';
  }

  out.innerHTML = html;
}
