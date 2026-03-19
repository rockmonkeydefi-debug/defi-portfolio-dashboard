// ===== MARKET DATA TAB =====
let marketCache = null;

async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(r.statusText);
  return r.json();
}

async function computeMarketData(force) {
  if (marketCache && !force) return; // already loaded
  const btn = document.getElementById('marketBtn');
  const out = document.getElementById('marketOutput');
  btn.disabled = true; btn.textContent = 'Fetching...';
  out.innerHTML = '<div style="color:#8892b0">Loading market data...</div>';

  const results = {};
  const errors = {};

  const tasks = [
    (async () => {
      const [global, prices] = await Promise.all([
        fetchJSON('https://api.coingecko.com/api/v3/global'),
        fetchJSON('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true')
      ]);
      results.btc = prices.bitcoin.usd;
      results.btcChg = prices.bitcoin.usd_24h_change;
      results.eth = prices.ethereum.usd;
      results.ethChg = prices.ethereum.usd_24h_change;
      results.btcDom = global.data.market_cap_percentage.btc;
      results.ethDom = global.data.market_cap_percentage.eth;
      results.totalMcap = global.data.total_market_cap.usd;
      results.totalVol = global.data.total_volume.usd;
    })().catch(e => errors.coingecko = e.message),

    (async () => {
      const [btc, eth] = await Promise.all([
        fetchJSON('https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT'),
        fetchJSON('https://api.bybit.com/v5/market/tickers?category=linear&symbol=ETHUSDT')
      ]);
      const b = btc.result.list[0], e = eth.result.list[0];
      results.btcFunding = parseFloat(b.fundingRate);
      results.btcOI = parseFloat(b.openInterest);
      results.btcOIVal = parseFloat(b.openInterestValue);
      results.ethFunding = parseFloat(e.fundingRate);
      results.ethOI = parseFloat(e.openInterest);
      results.ethOIVal = parseFloat(e.openInterestValue);
    })().catch(e => errors.bybit = e.message),

    (async () => {
      const data = await fetchJSON('https://www.deribit.com/api/v2/public/get_index_price?index_name=btc_usd');
      results.btcIndex = data.result.index_price;
    })().catch(e => errors.deribit = e.message),

    (async () => {
      const data = await fetchJSON('https://stablecoins.llama.fi/stablecoinchains');
      let total = 0;
      for (const chain of data) {
        const circ = chain.totalCirculatingUSD;
        if (circ && typeof circ === 'object') total += Object.values(circ).reduce((a, b) => a + b, 0);
        else if (circ) total += parseFloat(circ);
      }
      results.stablecoinSupply = total;
    })().catch(e => errors.defillama = e.message),

    (async () => {
      const data = await fetchJSON('https://api.alternative.me/fng/?limit=1');
      results.fgValue = parseInt(data.data[0].value);
      results.fgLabel = data.data[0].value_classification;
    })().catch(e => errors.fng = e.message),

    // F&G 30-day history for averages
    (async () => {
      const data = await fetchJSON('https://api.alternative.me/fng/?limit=30');
      results.fgHistory = data.data.map(d => parseInt(d.value));
    })().catch(e => {}),

    // BTC 30d price history for vol/returns
    (async () => {
      const data = await fetchJSON('https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=30&interval=daily');
      results.btcPriceHistory = data.prices.map(p => p[1]);
    })().catch(e => {}),

    // ETH 30d price history for vol
    (async () => {
      const data = await fetchJSON('https://api.coingecko.com/api/v3/coins/ethereum/market_chart?vs_currency=usd&days=30&interval=daily');
      results.ethPriceHistory = data.prices.map(p => p[1]);
    })().catch(e => {}),

    // SOL funding from Bybit
    (async () => {
      const data = await fetchJSON('https://api.bybit.com/v5/market/tickers?category=linear&symbol=SOLUSDT');
      const s = data.result.list[0];
      results.solFunding = parseFloat(s.fundingRate);
      results.solOIVal = parseFloat(s.openInterestValue);
    })().catch(e => {}),

    // DeFi Llama yields — LP pool APRs
    (async () => {
      var yieldsResp = await fetchJSON('https://yields.llama.fi/pools');
      var pools = yieldsResp.data || [];
      var lpPools = {};
      pools.forEach(function(p) {
        var proj = p.project || '', ch = (p.chain || '').toLowerCase(), sym = p.symbol || '';
        if (proj === 'uniswap-v3' && ['arbitrum','base','ethereum'].indexOf(ch) >= 0 && (p.tvlUsd || 0) > 1000000) {
          if ((sym.indexOf('USDC') >= 0 || sym.indexOf('USDT') >= 0) && (sym.indexOf('ETH') >= 0 || sym.indexOf('WETH') >= 0 || sym.indexOf('WBTC') >= 0)) {
            lpPools[ch + '_' + sym] = {apyBase: p.apyBase || 0, apyReward: p.apyReward || 0, tvl: p.tvlUsd || 0, vol1d: p.volumeUsd1d || 0, feeTier: p.poolMeta || ''};
          }
        }
        if (proj === 'lido' && sym === 'STETH' && ch === 'ethereum') results.ethStakingApr = p.apy;
      });
      results.lpPools = lpPools;
    })().catch(e => errors.defillama_yields = e.message),

    // On-chain lending rates
    (async () => {
      var lendingResp = await fetchJSON('/api/market/lending-rates');
      results.lendingRates = lendingResp;
    })().catch(e => errors.lending_rates = e.message),

    // Stablecoin 7d change from DB
    (async () => {
      var resp = await fetchJSON('/api/market/stablecoin-7d');
      if (resp && resp.change_pct != null) results.stablecoin7dChange = resp.change_pct;
    })().catch(e => {}),

    // FRED macro indicators (24h cached)
    (async () => {
      var resp = await fetchJSON('/api/market/macro');
      if (resp && resp.rows) results.macroRows = resp.rows;
      if (resp && resp.error) results.macroError = resp.error;
    })().catch(e => {}),
  ];

  await Promise.all(tasks);
  marketCache = results;

  try {

  const fmt = v => '$' + v.toLocaleString('en-US', { maximumFractionDigits: 0 });
  const fmtB = function(v) {
    if (v >= 1e9) return '$' + (v / 1e9).toFixed(1) + 'B';
    if (v >= 1e6) return '$' + (v / 1e6).toFixed(1) + 'M';
    if (v >= 1e3) return '$' + (v / 1e3).toFixed(0) + 'K';
    return '$' + Math.round(v).toLocaleString();
  };
  const fmtT = v => '$' + (v / 1e12).toFixed(2) + 'T';
  const chg = v => v != null ? ('<span class="' + (v >= 0 ? 'positive' : 'negative') + '">' + (v >= 0 ? '+' : '') + v.toFixed(2) + '%</span>') : '';
  const fgColor = v => v >= 75 ? '#51cf66' : v >= 55 ? '#64ffda' : v >= 45 ? '#ffa94d' : v >= 25 ? '#ff922b' : '#ff6b6b';
  const fgGauge = v => {
    // SVG semicircle gauge with needle
    const angle = -90 + (v / 100) * 180; // -90 (left) to +90 (right)
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
    // Needle
    const na = Math.PI + (v / 100) * Math.PI;
    const nx = cx + (r - 10) * Math.cos(na), ny = cy + (r - 10) * Math.sin(na);
    const needle = '<line x1="' + cx + '" y1="' + cy + '" x2="' + nx + '" y2="' + ny + '" stroke="#fff" stroke-width="3" stroke-linecap="round"/>' +
      '<circle cx="' + cx + '" cy="' + cy + '" r="5" fill="#fff"/>';
    // Labels
    const labels = '<text x="12" y="98" fill="#8892b0" font-size="10" font-family="sans-serif">0</text>' +
      '<text x="95" y="10" fill="#8892b0" font-size="10" font-family="sans-serif">50</text>' +
      '<text x="182" y="98" fill="#8892b0" font-size="10" font-family="sans-serif">100</text>';
    return '<div style="text-align:center"><svg viewBox="0 0 200 110" width="240" height="132">' +
      arcs + needle + labels + '</svg></div>';
  };

  let html = '';

  // Pre-compute volatility, returns, ranges for BTC/ETH tiles
  function _realizedVol(prices) {
    if (!prices || prices.length < 3) return null;
    var rets = [];
    for (var i = 1; i < prices.length; i++) rets.push(Math.log(prices[i] / prices[i-1]));
    var mean = rets.reduce(function(a,b){return a+b;},0) / rets.length;
    var variance = rets.reduce(function(a,r){return a + (r-mean)*(r-mean);},0) / (rets.length-1);
    return Math.sqrt(variance) * Math.sqrt(365) * 100;
  }
  function _volLabel(v) {
    if (v == null) return '';
    if (v < 30) return '<span class="positive">Low (' + v.toFixed(0) + '%)</span>';
    if (v < 60) return 'Normal (' + v.toFixed(0) + '%)';
    return '<span class="negative">High (' + v.toFixed(0) + '%)</span>';
  }
  function _range14d(prices) {
    if (!prices || prices.length < 7) return null;
    var s = prices.slice(-14);
    var hi = Math.max.apply(null, s), lo = Math.min.apply(null, s);
    return ((hi - lo) / ((hi + lo) / 2)) * 100;
  }
  var _btcVol = _realizedVol(results.btcPriceHistory);
  var _ethVol = _realizedVol(results.ethPriceHistory);
  var _bp = results.btcPriceHistory || [];
  var _ep = results.ethPriceHistory || [];
  var _btc7d = _bp.length >= 7 ? ((_bp[_bp.length-1] / _bp[_bp.length-7]) - 1) * 100 : null;
  var _btc30d = _bp.length >= 2 ? ((_bp[_bp.length-1] / _bp[0]) - 1) * 100 : null;
  var _eth7d = _ep.length >= 7 ? ((_ep[_ep.length-1] / _ep[_ep.length-7]) - 1) * 100 : null;
  var _eth30d = _ep.length >= 2 ? ((_ep[_ep.length-1] / _ep[0]) - 1) * 100 : null;
  var _btcRange = _range14d(results.btcPriceHistory);
  var _ethRange = _range14d(results.ethPriceHistory);

  // === ROW 1: BTC + ETH (small), Fear&Greed + Macro (small) ===
  html += '<div class="mkt-row">';

  html += '<div class="mkt-sm">' +
    '<div class="section-title" style="margin-top:0">'+li('bitcoin',16,'#f7931a')+' Bitcoin</div>' +
    '<div class="highlight" style="font-size:22px">' + (results.btc ? fmt(results.btc) : 'N/A') + '</div>' +
    '<div style="margin:4px 0">' + chg(results.btcChg) + ' (24h)</div>' +
    (results.btcDom ? '<div class="row"><span class="label">Dominance</span><span class="value">' + results.btcDom.toFixed(1) + '%</span></div>' : '') +
    (_btc7d != null ? '<div class="row"><span class="label">7d Return</span><span class="value ' + (_btc7d >= 0 ? 'positive' : 'negative') + '">' + (_btc7d >= 0 ? '+' : '') + _btc7d.toFixed(2) + '%</span></div>' : '') +
    (_btc30d != null ? '<div class="row"><span class="label">30d Return</span><span class="value ' + (_btc30d >= 0 ? 'positive' : 'negative') + '">' + (_btc30d >= 0 ? '+' : '') + _btc30d.toFixed(2) + '%</span></div>' : '') +
    (_btcVol != null ? '<div class="row"><span class="label">30d Vol</span><span class="value">' + _volLabel(_btcVol) + '</span></div>' : '') +
    (_btcRange != null ? '<div class="row"><span class="label">14d Range</span><span class="value">' + _btcRange.toFixed(1) + '%</span></div>' : '') +
    '</div>';

  html += '<div class="mkt-sm">' +
    '<div class="section-title" style="margin-top:0">Ξ Ethereum</div>' +
    '<div class="highlight" style="font-size:22px">' + (results.eth ? fmt(results.eth) : 'N/A') + '</div>' +
    '<div style="margin:4px 0">' + chg(results.ethChg) + ' (24h)</div>' +
    (results.ethDom ? '<div class="row"><span class="label">Dominance</span><span class="value">' + results.ethDom.toFixed(1) + '%</span></div>' : '') +
    (results.eth && results.btc ? '<div class="row"><span class="label">ETH/BTC</span><span class="value">' + (results.eth / results.btc).toFixed(5) + '</span></div>' : '') +
    (_eth7d != null ? '<div class="row"><span class="label">7d Return</span><span class="value ' + (_eth7d >= 0 ? 'positive' : 'negative') + '">' + (_eth7d >= 0 ? '+' : '') + _eth7d.toFixed(2) + '%</span></div>' : '') +
    (_eth30d != null ? '<div class="row"><span class="label">30d Return</span><span class="value ' + (_eth30d >= 0 ? 'positive' : 'negative') + '">' + (_eth30d >= 0 ? '+' : '') + _eth30d.toFixed(2) + '%</span></div>' : '') +
    (_ethVol != null ? '<div class="row"><span class="label">30d Vol</span><span class="value">' + _volLabel(_ethVol) + '</span></div>' : '') +
    (_ethRange != null ? '<div class="row"><span class="label">14d Range</span><span class="value">' + _ethRange.toFixed(1) + '%</span></div>' : '') +
    '</div>';

  // Fear & Greed with sentiment
  if (results.fgValue != null) {
    var fg = results.fgHistory || [];
    var fg7d = fg.length >= 7 ? fg.slice(0,7).reduce(function(a,b){return a+b;},0) / 7 : null;
    var fg30d = fg.length > 0 ? fg.reduce(function(a,b){return a+b;},0) / fg.length : null;
    var fgTrend = (fg7d != null && fg30d != null) ? (fg7d > fg30d ? '<span class="positive">\u2191 Improving</span>' : '<span class="negative">\u2193 Declining</span>') : '';
    html += '<div class="mkt-sm">' +
      '<div class="section-title" style="margin-top:0">' + li('heart', 16) + ' Fear & Greed</div>' +
      fgGauge(results.fgValue) +
      '<div style="text-align:center;color:' + fgColor(results.fgValue) + ';font-weight:700;font-size:18px;margin-top:-8px">' + results.fgValue + ' \u2014 ' + esc(results.fgLabel) + '</div>' +
      '<div style="margin-top:8px;font-size:12px">' +
      (fg7d != null ? '<div class="row"><span class="label">7d Avg</span><span class="value">' + fg7d.toFixed(0) + '</span></div>' : '') +
      (fg30d != null ? '<div class="row"><span class="label">30d Avg</span><span class="value">' + fg30d.toFixed(0) + '</span></div>' : '') +
      (fgTrend ? '<div class="row"><span class="label">Trend</span><span class="value">' + fgTrend + '</span></div>' : '') +
      '</div></div>';
  } else {
    html += '<div class="mkt-sm"><div style="color:#8892b0;padding:20px">Fear & Greed unavailable</div></div>';
  }

  // Macro indicators (FRED)
  if (results.macroRows && results.macroRows.length > 0) {
    html += '<div class="mkt-sm">' +
      '<div class="section-title" style="margin-top:0">' + li('landmark', 16) + ' Macro</div>' +
      '<table style="width:100%;font-size:11px;border-collapse:collapse">' +
      '<thead><tr style="color:#8892b0;border-bottom:1px solid #222"><th style="text-align:left;padding:2px 4px">Metric</th><th style="text-align:right;padding:2px 4px">Value</th><th style="text-align:left;padding:2px 4px">Comment</th></tr></thead><tbody>';
    results.macroRows.forEach(function(r) {
      html += '<tr style="border-bottom:1px solid #1a1a2e"><td style="padding:3px 4px;color:#e0e0e0;white-space:nowrap">' + esc(r.metric) + '</td>' +
        '<td style="padding:3px 4px;text-align:right;color:#64ffda;font-weight:600;white-space:nowrap">' + esc(r.value) + '</td>' +
        '<td style="padding:3px 4px;color:#8892b0">' + esc(r.comment) + '</td></tr>';
    });
    html += '</tbody></table></div>';
  } else {
    html += '<div class="mkt-sm">' +
      '<div class="section-title" style="margin-top:0">' + li('landmark', 16) + ' Macro</div>' +
      '<div style="color:#8892b0;font-size:12px;padding:12px">' + (results.macroError ? esc(results.macroError) : 'No macro data') + '</div></div>';
  }

  html += '</div>';

  // === ROW 2: Market Overview (with Deribit), Futures ===
  html += '<div class="mkt-row">';

  html += '<div class="mkt-sm">' +
    '<div class="section-title" style="margin-top:0">' + li('globe', 16) + ' Market Overview</div>' +
    (results.totalMcap ? '<div class="row"><span class="label">Total Market Cap</span><span class="value">' + fmtT(results.totalMcap) + '</span></div>' : '') +
    (results.totalVol ? '<div class="row"><span class="label">24h Volume</span><span class="value">' + fmtB(results.totalVol) + '</span></div>' : '') +
    (results.stablecoinSupply ? '<div class="row"><span class="label">Stablecoin Supply</span><span class="value">' + fmtB(results.stablecoinSupply) + '</span></div>' : '') +
    (results.stablecoin7dChange != null ? '<div class="row"><span class="label">Stablecoin 7d</span><span class="value ' + (results.stablecoin7dChange >= 0 ? 'positive' : 'negative') + '">' + (results.stablecoin7dChange >= 0 ? '+' : '') + results.stablecoin7dChange.toFixed(2) + '%</span></div>' : '') +
    (results.ethStakingApr ? '<div class="row"><span class="label">ETH Staking APR</span><span class="value">' + results.ethStakingApr.toFixed(1) + '%</span></div>' : '') +
    (results.btcIndex ? '<div class="row"><span class="label">BTC Deribit Index</span><span class="value">' + fmt(results.btcIndex) + '</span></div>' : '') +
    (results.btcIndex && results.btc ? '<div class="row"><span class="label">Spot-Index Spread</span><span class="value">' + fmt(results.btc - results.btcIndex) + '</span></div>' : '') +
    '</div>';

  html += '<div class="mkt-sm">' +
    '<div class="section-title" style="margin-top:0">'+li('bar-chart-3',16)+' Futures (Bybit)</div>' +
    '<table class="hedge-table" style="font-size:11px"><thead><tr><th style="text-align:left"></th><th>Funding</th><th>Ann.</th><th>Z</th><th>OI</th></tr></thead><tbody>';
  if (results.btcFunding != null) {
    var ann = results.btcFunding * 3 * 365 * 100;
    var z = ((ann - 10) / 15).toFixed(2);
    var zcls = parseFloat(z) > 1 ? 'negative' : parseFloat(z) < -1 ? 'positive' : '';
    html += '<tr><td>BTC</td><td>' + (results.btcFunding * 100).toFixed(4) + '%</td><td class="' + (ann >= 0 ? 'positive' : 'negative') + '">' + ann.toFixed(1) + '%</td><td class="' + zcls + '">' + z + '</td><td>' + fmtB(results.btcOIVal) + '</td></tr>';
  }
  if (results.ethFunding != null) {
    var ann2 = results.ethFunding * 3 * 365 * 100;
    var z2 = ((ann2 - 10) / 15).toFixed(2);
    var zcls2 = parseFloat(z2) > 1 ? 'negative' : parseFloat(z2) < -1 ? 'positive' : '';
    html += '<tr><td>ETH</td><td>' + (results.ethFunding * 100).toFixed(4) + '%</td><td class="' + (ann2 >= 0 ? 'positive' : 'negative') + '">' + ann2.toFixed(1) + '%</td><td class="' + zcls2 + '">' + z2 + '</td><td>' + fmtB(results.ethOIVal) + '</td></tr>';
  }
  if (results.solFunding != null) {
    var ann3 = results.solFunding * 3 * 365 * 100;
    var z3 = ((ann3 - 10) / 15).toFixed(2);
    var zcls3 = parseFloat(z3) > 1 ? 'negative' : parseFloat(z3) < -1 ? 'positive' : '';
    html += '<tr><td>SOL</td><td>' + (results.solFunding * 100).toFixed(4) + '%</td><td class="' + (ann3 >= 0 ? 'positive' : 'negative') + '">' + ann3.toFixed(1) + '%</td><td class="' + zcls3 + '">' + z3 + '</td><td>' + fmtB(results.solOIVal) + '</td></tr>';
  }
  html += '</tbody></table></div>';

  html += '</div>';

  // === ROW 3: Lending, LP Pools, Analytics ===
  var hasLending = results.lendingRates && Object.keys(results.lendingRates).length > 0;
  var hasLpPools = results.lpPools && Object.keys(results.lpPools).length > 0;
  if (hasLending || hasLpPools) {
    html += '<div class="mkt-row">';

    if (hasLending) {
      html += '<div class="mkt-lg">' +
        '<div class="section-title" style="margin-top:0">' + li('landmark', 16) + ' Lending Rates (Aave V3)</div>' +
        '<table class="hedge-table" style="font-size:11px"><thead><tr><th style="text-align:left">Asset</th><th>Chain</th><th>Supply</th><th>Borrow</th><th>Spread</th></tr></thead><tbody>';
      Object.keys(results.lendingRates).sort(function(a, b) {
        var aa = results.lendingRates[a], bb = results.lendingRates[b];
        return (aa.asset || '').localeCompare(bb.asset || '') || (aa.chain || '').localeCompare(bb.chain || '');
      }).forEach(function(key) {
        var r = results.lendingRates[key];
        var chain = (r.chain || '').charAt(0).toUpperCase() + (r.chain || '').slice(1);
        var spread = (r.borrow || 0) - (r.supply || 0);
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
      Object.keys(results.lpPools).sort(function(a, b) {
        var pa = a.split('_'), pb = b.split('_');
        return pa.slice(1).join('_').localeCompare(pb.slice(1).join('_')) || pa[0].localeCompare(pb[0]);
      }).forEach(function(key) {
        var p = results.lpPools[key];
        var parts = key.split('_');
        var chain = parts[0].charAt(0).toUpperCase() + parts[0].slice(1);
        var sym = parts.slice(1).join('/');
        var feeTier = p.feeTier ? ' <span style="color:#555;font-size:10px">' + esc(p.feeTier) + '</span>' : '';
        html += '<tr><td style="text-align:left">' + esc(sym) + feeTier + '</td>' +
          '<td>' + chainIcon(chain) + '</td>' +
          '<td class="positive">' + p.apyBase.toFixed(1) + '%</td>' +
          '<td>' + fmtB(p.tvl) + '</td>' +
          '<td>' + (p.vol1d > 0 ? fmtB(p.vol1d) : '-') + '</td></tr>';
      });
      html += '</tbody></table></div>';
    }

    // Row 3 closed — just Lending + LP Pools, equal width
    html += '</div>';
  }

  const errKeys = Object.keys(errors);
  if (errKeys.length) {
    html += '<div class="market-card market-card-wide" style="border-color:#ff6b6b33">' +
      '<div class="section-title" style="margin-top:0;color:#ff6b6b">'+li('alert-triangle',16,'#ff6b6b')+' Errors</div>';
    errKeys.forEach(k => { html += '<div class="row"><span class="label">' + esc(k) + '</span><span class="value negative">' + esc(errors[k]) + '</span></div>'; });
    html += '</div>';
  }

  html += '<div style="width:100%;text-align:right;font-size:11px;color:#555;margin-top:4px">Updated: ' + new Date().toLocaleTimeString() + '</div>';

  out.innerHTML = html;
  } catch(renderErr) {
    out.innerHTML = '<div style="color:#ff6b6b;padding:20px">Render error: ' + renderErr.message + '</div>';
    console.error('Market render error:', renderErr);
  }
  btn.disabled = false; btn.textContent = 'Refresh';
  // Auto-snapshot market data to DB
  try { fetch('/api/market/snapshot', {method: 'POST'}); } catch(e) {}
}


