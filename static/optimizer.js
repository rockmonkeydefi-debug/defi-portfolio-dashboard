// ===== LP OPTIMIZER TAB =====
let optChart = null;
let optCandidates = [];
let optPrices = [];
let optTimestamps = [];
let optCurrentPrice = 0;
let optSelectedPool = null;

// --- 6.5: Initialization and portfolio position loading ---

function loadOptimizer() {
  fetch('/api/optimizer/portfolio-positions')
    .then(r => r.ok ? r.json() : [])
    .then(positions => {
      const sel = document.getElementById('optPortfolioPos');
      sel.innerHTML = '<option value="">Select position...</option>';
      if (!positions.length) {
        sel.innerHTML += '<option value="" disabled>No V3 positions found</option>';
      }
      positions.forEach((p, i) => {
        const label = esc(p.symbol || (p.token0 + '-' + p.token1)) + ' (' + esc(p.chain) + ')';
        sel.innerHTML += '<option value="' + i + '">' + label + '</option>';
      });
      window._optPositions = positions;
    })
    .catch(() => {});
  loadRegimes(document.getElementById('optHorizon').value);
}

// --- 6.1: Pool search and selection ---

function searchPools() {
  const chain = document.getElementById('optChain').value;
  const symbol = document.getElementById('optSymbol').value.trim();
  const minTvl = parseFloat(document.getElementById('optMinTvl').value) || 500000;
  const err = document.getElementById('optErr');
  err.style.display = 'none';

  const body = {};
  if (chain) body.chain = chain;
  if (symbol) body.symbol = symbol;
  body.min_tvl = minTvl;

  fetch('/api/optimizer/pools', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
    .then(r => {
      if (!r.ok) return r.json().then(d => { throw new Error(d.error || 'Pool search failed'); });
      return r.json();
    })
    .then(pools => {
      const wrap = document.getElementById('optPoolResults');
      const tbody = document.getElementById('optPoolBody');
      if (!pools.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#8892b0;padding:12px">No pools found</td></tr>';
        wrap.style.display = '';
        return;
      }
      tbody.innerHTML = pools.map((p, i) =>
        '<tr style="cursor:pointer" onclick="selectPool(' + i + ')">' +
        '<td style="text-align:left">' + esc(p.symbol) + '</td>' +
        '<td>' + esc(p.chain) + '</td>' +
        '<td>$' + optFmtNum(p.tvl) + '</td>' +
        '<td>$' + optFmtNum(p.volume_24h) + '</td>' +
        '<td>' + (p.fee_apr || 0).toFixed(1) + '%</td>' +
        '<td>' + esc(p.fee_meta || '—') + '</td></tr>'
      ).join('');
      wrap.style.display = '';
      window._optPools = pools;
    })
    .catch(e => {
      err.textContent = e.message;
      err.style.display = 'block';
    });
}

function selectPool(idx) {
  const pool = (window._optPools || [])[idx];
  if (!pool) return;
  optSelectedPool = pool;
  // Highlight selected row
  document.querySelectorAll('#optPoolBody tr').forEach((tr, i) =>
    tr.classList.toggle('row-entry', i === idx)
  );
  // Show params section and pre-fill position size if empty
  document.getElementById('optParams').style.display = '';
}

function selectPortfolioPosition(val) {
  if (val === '' || val === undefined) return;
  const pos = (window._optPositions || [])[parseInt(val)];
  if (!pos) return;
  // Auto-populate chain and symbol fields
  if (pos.chain) document.getElementById('optChain').value = pos.chain;
  var sym = pos.symbol || (pos.token0 + '-' + pos.token1);
  document.getElementById('optSymbol').value = sym;
  if (pos.value_usd) document.getElementById('optPositionSize').value = Math.round(pos.value_usd);
  document.getElementById('optParams').style.display = '';

  // Search for matching pools from DeFiLlama, then auto-select the best match
  var chain = document.getElementById('optChain').value;
  var body = { min_tvl: 0 };
  if (chain) body.chain = chain;
  // Use individual token names for better DeFiLlama matching
  var searchSym = sym.replace('/', '-');
  var searchTokens = searchSym.split('-');
  // Search by first non-stable token for broader matching
  var stables = ['USDC','USDT','DAI','USDS','USDbC','FRAX','GHO','PYUSD','USDe','LUSD'];
  var nonStable = searchTokens.filter(function(t) { return stables.indexOf(t.toUpperCase()) < 0; });
  body.symbol = nonStable.length > 0 ? nonStable[0] : searchSym;

  fetch('/api/optimizer/pools', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
    .then(function(r) { return r.ok ? r.json() : []; })
    .then(function(pools) {
      var wrap = document.getElementById('optPoolResults');
      var tbody = document.getElementById('optPoolBody');
      window._optPools = pools;
      if (pools.length) {
        tbody.innerHTML = pools.map(function(p, i) {
          return '<tr style="cursor:pointer" onclick="selectPool(' + i + ')">' +
            '<td style="text-align:left">' + esc(p.symbol) + '</td>' +
            '<td>' + esc(p.chain) + '</td>' +
            '<td>$' + optFmtNum(p.tvl) + '</td>' +
            '<td>$' + optFmtNum(p.volume_24h) + '</td>' +
            '<td>' + (p.fee_apr || 0).toFixed(1) + '%</td>' +
            '<td>' + esc(p.fee_meta || '\u2014') + '</td></tr>';
        }).join('');
        wrap.style.display = '';
        // Auto-select the first (highest TVL) matching pool
        optSelectedPool = pools[0];
        // Merge portfolio-specific data
        optSelectedPool.coin_id = optSelectedPool.coin_id || pos.coin_id || '';
        document.querySelectorAll('#optPoolBody tr').forEach(function(tr, i) {
          tr.classList.toggle('row-entry', i === 0);
        });
      } else {
        // No DeFiLlama match — use position data with zeros for volume
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#8892b0;padding:12px">No matching pools found on DeFiLlama</td></tr>';
        wrap.style.display = '';
        optSelectedPool = {
          chain: pos.chain || '',
          symbol: sym,
          tvl: 0,
          volume_24h: 0,
          fee_meta: pos.fee_tier ? (pos.fee_tier + '%') : '',
          coin_id: pos.coin_id || ''
        };
      }
    })
    .catch(function() {
      optSelectedPool = {
        chain: pos.chain || '',
        symbol: sym,
        tvl: 0,
        volume_24h: 0,
        fee_meta: pos.fee_tier ? (pos.fee_tier + '%') : '',
        coin_id: pos.coin_id || ''
      };
    });
}

// --- 6.2: Regime loading and override UI ---

function loadRegimes(horizon) {
  fetch('/api/optimizer/regimes?horizon=' + horizon)
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!data) return;
      updateRegimeSliders(data);
    })
    .catch(() => {});
}

function updateRegimeSliders(regimes) {
  var bull = regimes.bull || 30;
  var sideways = regimes.sideways || 45;
  // If values look like fractions (0-1 range), convert to percentages
  if (bull <= 1 && sideways <= 1) { bull *= 100; sideways *= 100; }
  bull = Math.round(bull);
  sideways = Math.round(sideways);
  var bear = Math.max(0, 100 - bull - sideways);
  document.getElementById('optBull').value = bull;
  document.getElementById('optSideways').value = sideways;
  document.getElementById('optBear').value = bear;
  var src = regimes.source === 'default' ? '⚠️ Using default probabilities (no AI report)' : 'Source: AI Daily Brief';
  document.getElementById('optRegimeSource').textContent = src;
}

function updateBearAuto() {
  var bull = parseInt(document.getElementById('optBull').value) || 0;
  var sideways = parseInt(document.getElementById('optSideways').value) || 0;
  var bear = Math.max(0, 100 - bull - sideways);
  document.getElementById('optBear').value = bear;
  document.getElementById('optRegimeSource').textContent = 'Manual override';
}

// --- 6.3: Optimization run and results display ---

function runOptimization() {
  var err = document.getElementById('optErr');
  err.style.display = 'none';
  if (!optSelectedPool) {
    err.textContent = 'Select a pool first (search or pick a portfolio position).';
    err.style.display = 'block';
    return;
  }
  var bull = parseInt(document.getElementById('optBull').value) || 30;
  var sideways = parseInt(document.getElementById('optSideways').value) || 45;
  var bear = parseInt(document.getElementById('optBear').value) || 25;
  var params = {
    chain: optSelectedPool.chain || '',
    symbol: optSelectedPool.symbol || '',
    fee_meta: optSelectedPool.fee_meta || '',
    volume_24h: optSelectedPool.volume_24h || 0,
    tvl: optSelectedPool.tvl || 0,
    fee_apr: optSelectedPool.fee_apr || 0,
    horizon_days: parseInt(document.getElementById('optHorizon').value) || 14,
    position_size: parseFloat(document.getElementById('optPositionSize').value) || 10000,
    regime_override: { bull: bull, bear: bear, sideways: sideways },
    coin_id: optSelectedPool.coin_id || '',
    pool_address: optSelectedPool.pool_address || ''
  };

  // Show loading state
  var resultsGrid = document.getElementById('optResultsGrid');
  resultsGrid.style.display = '';
  document.getElementById('optResultsBody').innerHTML =
    '<tr><td colspan="11" style="text-align:center;color:#8892b0;padding:20px">Running optimization...</td></tr>';

  fetch('/api/optimizer/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params)
  })
    .then(r => {
      if (!r.ok) return r.json().then(d => { throw new Error(d.error || 'Optimization failed'); });
      return r.json();
    })
    .then(data => {
      optCandidates = data.candidates || [];
      optPrices = data.prices || [];
      optTimestamps = data.timestamps || [];
      optCurrentPrice = data.current_price || 0;
      renderResultsTable(optCandidates, data.optimal_index || 0);
      if (optCandidates.length > 0) {
        renderPriceChart(optPrices, optTimestamps, optCandidates[data.optimal_index || 0]);
      }
      renderSidebar(data);
    })
    .catch(e => {
      err.textContent = e.message;
      err.style.display = 'block';
      document.getElementById('optResultsBody').innerHTML = '';
      resultsGrid.style.display = 'none';
    });
}

function renderResultsTable(candidates, optimalIndex) {
  var tbody = document.getElementById('optResultsBody');
  if (!candidates.length) {
    tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;color:#8892b0;padding:12px">No results</td></tr>';
    return;
  }
  tbody.innerHTML = candidates.map(function(c, i) {
    var cls = i === optimalIndex ? ' class="row-entry"' : '';
    var prefix = i === optimalIndex ? '⭐ ' : '';
    return '<tr' + cls + ' style="cursor:pointer" onclick="selectOptResult(' + i + ')">' +
      '<td style="text-align:left">' + prefix + esc(c.label) + '</td>' +
      '<td>' + fmtPrice(c.L) + '</td>' +
      '<td>' + fmtPrice(c.U) + '</td>' +
      '<td>' + c.pct_lower.toFixed(1) + '% / +' + c.pct_upper.toFixed(1) + '%</td>' +
      '<td>$' + c.expected_fees_usd.toFixed(2) + '</td>' +
      '<td>' + (c.raw_apr_pct || 0).toFixed(1) + '%</td>' +
      '<td>' + c.apr_pct.toFixed(1) + '%</td>' +
      '<td>' + c.time_in_range_pct.toFixed(1) + '%</td>' +
      '<td>' + c.il_at_lower_pct.toFixed(1) + '%</td>' +
      '<td>' + c.il_at_upper_pct.toFixed(1) + '%</td>' +
      '<td class="' + (c.expected_return_usd >= 0 ? 'positive' : 'negative') + '">$' +
        c.expected_return_usd.toFixed(2) + '</td></tr>';
  }).join('');
}

function selectOptResult(idx) {
  var c = optCandidates[idx];
  if (!c) return;
  document.querySelectorAll('#optResultsBody tr').forEach(function(tr, i) {
    tr.classList.toggle('row-entry', i === idx);
  });
  renderPriceChart(optPrices, optTimestamps, c);
}

// --- 6.4: Chart.js price chart with range overlay ---

function renderPriceChart(prices, timestamps, selectedRange) {
  if (!prices || !prices.length) return;
  var labels = timestamps.map(function(t) { return new Date(t).toLocaleDateString(); });
  var datasets = [
    {
      label: 'Price',
      data: prices,
      borderColor: '#64ffda',
      borderWidth: 1.5,
      pointRadius: 0,
      fill: false
    }
  ];
  if (optCurrentPrice) {
    datasets.push({
      label: 'Current (' + fmtPrice(optCurrentPrice) + ')',
      data: Array(prices.length).fill(optCurrentPrice),
      borderColor: '#8892b0',
      borderWidth: 1,
      borderDash: [2, 4],
      pointRadius: 0,
      fill: false
    });
  }
  if (selectedRange) {
    datasets.push({
      label: 'Upper (' + fmtPrice(selectedRange.U) + ')',
      data: Array(prices.length).fill(selectedRange.U),
      borderColor: '#ff6b6b',
      borderWidth: 1,
      borderDash: [5, 5],
      pointRadius: 0,
      fill: false
    });
    datasets.push({
      label: 'Lower (' + fmtPrice(selectedRange.L) + ')',
      data: Array(prices.length).fill(selectedRange.L),
      borderColor: '#51cf66',
      borderWidth: 1,
      borderDash: [5, 5],
      pointRadius: 0,
      fill: false
    });
  }
  if (optChart) optChart.destroy();
  optChart = new Chart(document.getElementById('optChartCanvas'), {
    type: 'line',
    data: { labels: labels, datasets: datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 200 },
      plugins: {
        legend: { labels: { color: '#8892b0', font: { size: 11 } } },
        tooltip: {
          mode: 'index',
          intersect: false,
          callbacks: {
            label: function(item) {
              return item.dataset.label + ': ' + fmtPrice(item.parsed.y);
            }
          }
        }
      },
      scales: {
        x: { ticks: { color: '#8892b0', maxTicksLimit: 10, font: { size: 10 } }, grid: { color: '#1e3050' } },
        y: { ticks: { color: '#8892b0', font: { size: 10 } }, grid: { color: '#1e3050' } }
      }
    }
  });
}

// --- Sidebar rendering ---

function renderSidebar(data) {
  var sb = document.getElementById('optSidebar');
  var html = '<div class="section-title">📊 Market Data</div>';
  html += optRow('Price', fmtPrice(data.current_price));
  html += optRow('Ann. Volatility', data.vol_ann_pct.toFixed(1) + '%');
  html += optRow('7d Return', data.ret_7d_pct.toFixed(1) + '%');
  html += optRow('30d Return', data.ret_30d_pct.toFixed(1) + '%');
  html += '<div class="section-title">🎯 Regime Probabilities</div>';
  var reg = data.regimes || {};
  html += optRow('Bull', (reg.bull || 0) + '%');
  html += optRow('Sideways', (reg.sideways || 0) + '%');
  html += optRow('Bear', (reg.bear || 0) + '%');
  html += optRow('Source', reg.source === 'default' ? 'Default' : 'AI Report');
  if (data.pool_address) {
    html += '<div class="section-title">🔗 Pool Info</div>';
    html += optRow('Address', '<span style="cursor:pointer;text-decoration:underline dotted;color:#64ffda" title="Click to copy" onclick="navigator.clipboard.writeText(\'' + data.pool_address + '\');this.textContent=\'Copied!\';setTimeout(()=>this.textContent=\'' + data.pool_address.slice(0, 6) + '...' + data.pool_address.slice(-4) + '\',1500)">' + data.pool_address.slice(0, 6) + '...' + data.pool_address.slice(-4) + '</span>');
    if (optSelectedPool && optSelectedPool.tvl) html += optRow('TVL', '$' + optFmtNum(optSelectedPool.tvl));
    if (optSelectedPool && optSelectedPool.volume_24h) html += optRow('24h Volume', '$' + optFmtNum(optSelectedPool.volume_24h));
  }
  if (optCandidates.length > 0) {
    var best = optCandidates[0];
    html += '<div class="section-title">⭐ Optimal Range</div>';
    html += optRow('Label', best.label);
    html += optRow('Lower', fmtPrice(best.L));
    html += optRow('Upper', fmtPrice(best.U));
    html += optRow('Exp. Fees', '$' + best.expected_fees_usd.toFixed(2));
    html += optRow('APR (in range)', (best.raw_apr_pct || 0).toFixed(1) + '%');
    html += optRow('Adj. APR', best.apr_pct.toFixed(1) + '%');
    html += optRow('TIR', best.time_in_range_pct.toFixed(1) + '%');
    var retCls = best.expected_return_usd >= 0 ? 'positive' : 'negative';
    html += '<div style="margin-top:12px;padding:14px;background:#0a0a1a;border:1px solid #64ffda33;border-radius:8px;text-align:center;">';
    html += '<div style="color:#a8b2d1;font-size:11px;letter-spacing:1px;">EXPECTED RETURN</div>';
    html += '<div class="highlight ' + retCls + '" style="margin:4px 0;">$' + best.expected_return_usd.toFixed(2) + '</div>';
    html += '</div>';
  }
  sb.innerHTML = html;
}

// --- Helpers ---

function optRow(label, value) {
  return '<div class="row"><span class="label">' + label + '</span><span class="value">' + value + '</span></div>';
}

function optFmtNum(n) {
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return Math.round(n).toLocaleString();
}

function fmtPrice(p) {
  if (p >= 1000) return Math.round(p).toLocaleString();
  if (p >= 1) return p.toFixed(2);
  if (p >= 0.01) return p.toFixed(4);
  return p.toPrecision(4);
}
