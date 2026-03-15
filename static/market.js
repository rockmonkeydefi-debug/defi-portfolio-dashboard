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
  ];

  await Promise.all(tasks);
  marketCache = results;

  const fmt = v => '$' + v.toLocaleString('en-US', { maximumFractionDigits: 0 });
  const fmtB = v => '$' + (v / 1e9).toFixed(1) + 'B';
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

  if (results.fgValue != null) {
    html += '<div class="market-card market-card-wide">' +
      '<div class="section-title" style="margin-top:0">😱 Fear & Greed Index</div>' +
      fgGauge(results.fgValue) +
      '<div style="text-align:center;color:' + fgColor(results.fgValue) + ';font-weight:700;font-size:20px;margin-top:-8px">' + results.fgValue + ' — ' + esc(results.fgLabel) + '</div></div>';
  }

  html += '<div class="market-card">' +
    '<div class="section-title" style="margin-top:0">'+li('bitcoin',16,'#f7931a')+' Bitcoin</div>' +
    '<div class="highlight" style="font-size:22px">' + (results.btc ? fmt(results.btc) : 'N/A') + '</div>' +
    '<div style="margin:4px 0">' + chg(results.btcChg) + ' (24h)</div>' +
    (results.btcDom ? '<div class="row"><span class="label">Dominance</span><span class="value">' + results.btcDom.toFixed(1) + '%</span></div>' : '') +
    '</div>';

  html += '<div class="market-card">' +
    '<div class="section-title" style="margin-top:0">Ξ Ethereum</div>' +
    '<div class="highlight" style="font-size:22px">' + (results.eth ? fmt(results.eth) : 'N/A') + '</div>' +
    '<div style="margin:4px 0">' + chg(results.ethChg) + ' (24h)</div>' +
    (results.ethDom ? '<div class="row"><span class="label">Dominance</span><span class="value">' + results.ethDom.toFixed(1) + '%</span></div>' : '') +
    (results.eth && results.btc ? '<div class="row"><span class="label">ETH/BTC</span><span class="value">' + (results.eth / results.btc).toFixed(5) + '</span></div>' : '') +
    '</div>';

  html += '<div class="market-card">' +
    '<div class="section-title" style="margin-top:0">🌍 Market Overview</div>' +
    (results.totalMcap ? '<div class="row"><span class="label">Total Market Cap</span><span class="value">' + fmtT(results.totalMcap) + '</span></div>' : '') +
    (results.totalVol ? '<div class="row"><span class="label">24h Volume</span><span class="value">' + fmtB(results.totalVol) + '</span></div>' : '') +
    (results.stablecoinSupply ? '<div class="row"><span class="label">Stablecoin Supply</span><span class="value">' + fmtB(results.stablecoinSupply) + '</span></div>' : '') +
    '</div>';

  html += '<div class="market-card">' +
    '<div class="section-title" style="margin-top:0">'+li('bar-chart-3',16)+' Futures (Bybit)</div>' +
    '<table class="hedge-table" style="font-size:12px"><thead><tr><th style="text-align:left"></th><th>Funding</th><th>Ann. Rate</th><th>Open Interest</th></tr></thead><tbody>';
  if (results.btcFunding != null) {
    const ann = results.btcFunding * 3 * 365 * 100;
    html += '<tr><td>BTC</td><td>' + (results.btcFunding * 100).toFixed(4) + '%</td><td class="' + (ann >= 0 ? 'positive' : 'negative') + '">' + ann.toFixed(1) + '%</td><td>' + fmtB(results.btcOIVal) + '</td></tr>';
  }
  if (results.ethFunding != null) {
    const ann = results.ethFunding * 3 * 365 * 100;
    html += '<tr><td>ETH</td><td>' + (results.ethFunding * 100).toFixed(4) + '%</td><td class="' + (ann >= 0 ? 'positive' : 'negative') + '">' + ann.toFixed(1) + '%</td><td>' + fmtB(results.ethOIVal) + '</td></tr>';
  }
  html += '</tbody></table></div>';

  if (results.btcIndex) {
    html += '<div class="market-card">' +
      '<div class="section-title" style="margin-top:0">'+li('landmark',16)+' Deribit</div>' +
      '<div class="row"><span class="label">BTC Index Price</span><span class="value">' + fmt(results.btcIndex) + '</span></div>' +
      (results.btc ? '<div class="row"><span class="label">Spot-Index Spread</span><span class="value">' + fmt(results.btc - results.btcIndex) + '</span></div>' : '') +
      '</div>';
  }

  // === ANALYTICS CARD ===
  html += buildAnalyticsCard(results);

  const errKeys = Object.keys(errors);
  if (errKeys.length) {
    html += '<div class="market-card market-card-wide" style="border-color:#ff6b6b33">' +
      '<div class="section-title" style="margin-top:0;color:#ff6b6b">'+li('alert-triangle',16,'#ff6b6b')+' Errors</div>';
    errKeys.forEach(k => { html += '<div class="row"><span class="label">' + esc(k) + '</span><span class="value negative">' + esc(errors[k]) + '</span></div>'; });
    html += '</div>';
  }

  html += '<div style="width:100%;text-align:right;font-size:11px;color:#555;margin-top:4px">Updated: ' + new Date().toLocaleTimeString() + '</div>';

  out.innerHTML = html;
  btn.disabled = false; btn.textContent = 'Refresh';
}


function buildAnalyticsCard(r) {
  var rows = '';
  function arow(label, value, cls) {
    return '<div class="row"><span class="label">' + label + '</span><span class="value ' + (cls||'') + '">' + value + '</span></div>';
  }
  function pct(v) { return v != null ? (v >= 0 ? '+' : '') + v.toFixed(2) + '%' : 'N/A'; }
  function pcls(v) { return v >= 0 ? 'positive' : 'negative'; }

  // Realized Volatility
  function realizedVol(prices) {
    if (!prices || prices.length < 3) return null;
    var rets = [];
    for (var i = 1; i < prices.length; i++) rets.push(Math.log(prices[i] / prices[i-1]));
    var mean = rets.reduce(function(a,b){return a+b;},0) / rets.length;
    var variance = rets.reduce(function(a,r)
{return a + (r-mean)*(r-mean);},0) / (rets.length - 1);
    return Math.sqrt(variance) * Math.sqrt(365) * 100;
  }

  var btcVol = realizedVol(r.btcPriceHistory);
  var ethVol = realizedVol(r.ethPriceHistory);

  // Returns
  var bp = r.btcPriceHistory || [];
  var btc7d = bp.length >= 7 ? ((bp[bp.length-1] / bp[bp.length-7]) - 1) * 100 : null;
  var btc30d = bp.length >= 2 ? ((bp[bp.length-1] / bp[0]) - 1) * 100 : null;

  // Range 14d
  function range14d(prices) {
    if (!prices || prices.length < 14) return null;
    var s = prices.slice(-14);
    var hi = Math.max.apply(null, s), lo = Math.min.apply(null, s);
    return ((hi - lo) / ((hi + lo) / 2)) * 100;
  }
  var btcRange = range14d(r.btcPriceHistory);
  var ethRange = range14d(r.ethPriceHistory);

  // F&G averages
  var fg = r.fgHistory || [];
  var fg7d = fg.length >= 7 ? fg.slice(0,7).reduce(function(a,b){return a+b;},0) / 7 : null;
  var fg30d = fg.length > 0 ? fg.reduce(function(a,b){return a+b;},0) / fg.length : null;

  // Funding annualized
  var btcFundAnn = r.btcFunding != null ? r.btcFunding * 3 * 365 * 100 : null;
  var ethFundAnn = r.ethFunding != null ? r.ethFunding * 3 * 365 * 100 : null;
  var solFundAnn = r.solFunding != null ? r.solFunding * 3 * 365 * 100 : null;

  // Funding Z-score (rough: typical mean ~10%, std ~15%)
  var btcFundZ = btcFundAnn != null ? ((btcFundAnn - 10) / 15).toFixed(2) : 'N/A';

  // Vol regime
  function volRegime(v) {
    if (v == null) return 'N/A';
    if (v < 30) return '<span class="positive">Low (' + v.toFixed(0) + '%)</span>';
    if (v < 60) return 'Normal (' + v.toFixed(0) + '%)';
    return '<span class="negative">High (' + v.toFixed(0) + '%)</span>';
  }

  rows += '<div class="section-title" style="margin-top:0">'+li('activity',16)+' Volatility & Returns</div>';
  rows += arow('BTC 30d Realized Vol', volRegime(btcVol));
  rows += arow('ETH 30d Realized Vol', volRegime(ethVol));
  rows += arow('BTC 7d Return', btc7d != null ? pct(btc7d) : 'N/A', btc7d != null ? pcls(btc7d) : '');
  rows += arow('BTC 30d Return', btc30d != null ? pct(btc30d) : 'N/A', btc30d != null ? pcls(btc30d) : '');
  rows += arow('BTC 14d Range', btcRange != null ? btcRange.toFixed(1) + '%' : 'N/A');
  rows += arow('ETH 14d Range', ethRange != null ? ethRange.toFixed(1) + '%' : 'N/A');

  rows += '<div class="section-title">'+li('trending-up',16)+' Leverage & Funding</div>';
  rows += arow('BTC Funding (ann)', btcFundAnn != null ? pct(btcFundAnn) : 'N/A', btcFundAnn != null ? pcls(btcFundAnn) : '');
  rows += arow('ETH Funding (ann)', ethFundAnn != null ? pct(ethFundAnn) : 'N/A', ethFundAnn != null ? pcls(ethFundAnn) : '');
  rows += arow('SOL Funding (ann)', solFundAnn != null ? pct(solFundAnn) : 'N/A', solFundAnn != null ? pcls(solFundAnn) : '');
  rows += arow('BTC Funding Z-score', btcFundZ, parseFloat(btcFundZ) > 1 ? 'negative' : parseFloat(btcFundZ) < -1 ? 'positive' : '');
  if (r.solOIVal) rows += arow('SOL Open Interest', '$' + (r.solOIVal / 1e9).toFixed(2) + 'B');

  rows += '<div class="section-title">😱 Sentiment</div>';
  rows += arow('F&G 7d Average', fg7d != null ? fg7d.toFixed(0) : 'N/A');
  rows += arow('F&G 30d Average', fg30d != null ? fg30d.toFixed(0) : 'N/A');
  var fgTrend = (fg7d != null && fg30d != null) ? (fg7d > fg30d ? '<span class="positive">↑ Improving</span>' : '<span class="negative">↓ Declining</span>') : 'N/A';
  rows += arow('F&G Trend', fgTrend);

  rows += '<div class="section-title">🔮 DB-Derived (needs 30+ snapshots)</div>';
  rows += arow('Funding Z-scores', '<span style="color:#555">Accumulating data...</span>');
  rows += arow('OI Percentile', '<span style="color:#555">Accumulating data...</span>');
  rows += arow('OI 7d Change', '<span style="color:#555">Accumulating data...</span>');
  rows += arow('Stablecoin 7d Change', '<span style="color:#555">Accumulating data...</span>');

  return '<div class="market-card market-card-wide">' +
    '<div class="section-title" style="margin-top:0">🧮 Market Analytics</div>' +
    rows + '</div>';
}
