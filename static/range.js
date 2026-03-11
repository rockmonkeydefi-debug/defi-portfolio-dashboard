// ===== RANGE OPTIMIZER TAB =====
let rangeChart = null, rangeRows = [], rangePrices = [], rangeTimestamps = [], rangeP0 = 0;
let coinList = [];

// Load coin list once for autocomplete
(async function() {
  try {
    const r = await fetch('https://api.coingecko.com/api/v3/coins/list');
    if (r.ok) coinList = await r.json();
  } catch(e) {}
})();

function setupCoinAutocomplete() {
  const input = document.getElementById('rangeCoin');
  const wrap = input.parentElement;
  wrap.style.position = 'relative';
  let dropdown = document.getElementById('coinDropdown');
  if (!dropdown) {
    dropdown = document.createElement('div');
    dropdown.id = 'coinDropdown';
    dropdown.style.cssText = 'position:absolute;top:100%;left:0;right:0;max-height:200px;overflow-y:auto;background:#0a0a1a;border:1px solid #333;border-radius:0 0 6px 6px;z-index:99;display:none;font-size:13px';
    wrap.appendChild(dropdown);
  }
  input.addEventListener('input', function() {
    const q = this.value.trim().toLowerCase();
    if (q.length < 1 || !coinList.length) { dropdown.style.display = 'none'; return; }
    const matches = coinList.filter(c =>
      c.symbol.toLowerCase() === q || c.name.toLowerCase().startsWith(q) || c.id.startsWith(q)
    ).slice(0, 8);
    if (!matches.length) { dropdown.style.display = 'none'; return; }
    // Put exact symbol matches first
    matches.sort((a, b) => (a.symbol.toLowerCase() === q ? -1 : 0) - (b.symbol.toLowerCase() === q ? -1 : 0));
    dropdown.innerHTML = matches.map(c =>
      '<div style="padding:6px 10px;cursor:pointer;color:#a8b2d1;border-bottom:1px solid #1e3050" ' +
      'onmousedown="document.getElementById(\'rangeCoin\').value=\'' + esc(c.id) + '\';document.getElementById(\'coinDropdown\').style.display=\'none\'">' +
      '<span style="color:#64ffda">' + esc(c.symbol.toUpperCase()) + '</span> — ' + esc(c.name) +
      ' <span style="color:#555;font-size:11px">(' + esc(c.id) + ')</span></div>'
    ).join('');
    dropdown.style.display = 'block';
  });
  input.addEventListener('blur', function() { setTimeout(() => dropdown.style.display = 'none', 150); });
}
document.addEventListener('DOMContentLoaded', setupCoinAutocomplete);


function normRand() {
  let u = 0, v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

function runMC(p0, sigma, T, pL, pU, nPaths, horizon) {
  const nSteps = Math.max(horizon, 7);
  const dt = T / nSteps, sqdt = Math.sqrt(dt);
  const logPL = Math.log(pL), logPU = Math.log(pU);
  let tirCount = 0, stepsInRange = 0, totalSteps = 0;
  const finalPrices = [];
  for (let i = 0; i < nPaths; i++) {
    let logP = Math.log(p0), pathInRange = true;
    for (let j = 0; j < nSteps; j++) {
      logP += (-0.5 * sigma * sigma) * dt + sigma * sqdt * normRand();
      totalSteps++;
      if (logP >= logPL && logP <= logPU) stepsInRange++;
      else pathInRange = false;
    }
    if (pathInRange) tirCount++;
    finalPrices.push(Math.exp(logP));
  }
  return { tir: tirCount / nPaths, timeInRange: stepsInRange / totalSteps, finalPrices };
}

function showRangeOnChart(idx) {
  const r = rangeRows[idx];
  if (!r) return;
  document.querySelectorAll('.range-btn').forEach((b, i) => b.classList.toggle('active', i === idx));
  document.querySelectorAll('#rangeBody tr').forEach((tr, i) => tr.classList.toggle('row-entry', i === idx));
  const labels = rangeTimestamps.map(t => new Date(t).toLocaleDateString());
  if (rangeChart) rangeChart.destroy();
  rangeChart = new Chart(document.getElementById('rangeChartCanvas'), {
    type: 'line',
    data: { labels, datasets: [
      { label: 'Price', data: rangePrices, borderColor: '#64ffda', borderWidth: 1.5, pointRadius: 0, fill: false },
      { label: 'Upper (' + r.name + ')', data: Array(rangePrices.length).fill(r.pU), borderColor: '#ff6b6b', borderWidth: 1, borderDash: [5, 5], pointRadius: 0, fill: false },
      { label: 'Lower (' + r.name + ')', data: Array(rangePrices.length).fill(r.pL), borderColor: '#51cf66', borderWidth: 1, borderDash: [5, 5], pointRadius: 0, fill: false },
      { label: 'Entry', data: Array(rangePrices.length).fill(rangeP0), borderColor: '#8892b0', borderWidth: 1, borderDash: [2, 4], pointRadius: 0, fill: false },
    ]},
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#8892b0', font: { size: 11 } } } },
      scales: {
        x: { ticks: { color: '#8892b0', maxTicksLimit: 10, font: { size: 10 } }, grid: { color: '#1e3050' } },
        y: { ticks: { color: '#8892b0', font: { size: 10 } }, grid: { color: '#1e3050' } }
      }
    }
  });
}

async function computeRange() {
  const btn = document.getElementById('rangeBtn'), err = document.getElementById('rangeErr');
  err.style.display = 'none'; btn.disabled = true; btn.textContent = 'Fetching data...';
  await new Promise(r => setTimeout(r, 30));
  try {
    const coin = document.getElementById('rangeCoin').value.trim().toLowerCase();
    const vs = document.getElementById('rangeVs').value;
    const days = Math.min(365, Math.max(7, +document.getElementById('rangeDays').value || 90));
    const horizon = Math.min(90, Math.max(1, +document.getElementById('rangeHorizon').value || 14));
    const bias = Math.min(90, Math.max(10, +document.getElementById('rangeBias').value)) / 100;
    const customLo = document.getElementById('rangeCustomLo').value.trim();
    const customHi = document.getElementById('rangeCustomHi').value.trim();
    const nPaths = 5000;
    const T = horizon / 365;

    const resp = await fetch(`https://api.coingecko.com/api/v3/coins/${coin}/market_chart?vs_currency=${vs}&days=${days}&interval=daily`);
    if (!resp.ok) throw new Error('CoinGecko error — check token ID');
    const data = await resp.json();
    rangePrices = data.prices.map(p => p[1]);
    rangeTimestamps = data.prices.map(p => p[0]);
    if (rangePrices.length < 7) throw new Error('Not enough data');

    const logR = [];
    for (let i = 1; i < rangePrices.length; i++) logR.push(Math.log(rangePrices[i] / rangePrices[i - 1]));
    const mu = logR.reduce((a, b) => a + b, 0) / logR.length;
    const variance = logR.reduce((a, b) => a + (b - mu) ** 2, 0) / (logR.length - 1);
    const annSigma = Math.sqrt(variance) * Math.sqrt(365);
    rangeP0 = rangePrices[rangePrices.length - 1];
    const p0 = rangeP0;

    document.getElementById('rangeStats').innerHTML =
      '<div class="section-title">Market Data</div>' +
      row('Price', p0.toPrecision(6) + ' ' + vs.toUpperCase()) +
      row('Ann. Volatility (σ)', (annSigma * 100).toFixed(1) + '%') +
      row('Horizon', horizon + ' days') +
      row('Bias', (bias * 100).toFixed(0) + '% from bottom');

    function makeRange(name, w, paths) {
      const downW = w * bias, upW = w * (1 - bias);
      const pL = p0 * Math.exp(-downW), pU = p0 * Math.exp(upW);
      const mc = runMC(p0, annSigma, T, pL, pU, paths || nPaths, horizon);
      return { name, pL, pU, w, tir: mc.tir, timeIR: mc.timeInRange, mc };
    }

    const s = annSigma * Math.sqrt(T);

    // Sweep to find optimal width
    btn.textContent = 'Sweeping ranges...';
    await new Promise(r => setTimeout(r, 20));
    let bestMult = 1, bestScore = -Infinity;
    for (let mult = 0.3; mult <= 4.0; mult += 0.1) {
      const w = 2 * mult * s;
      const r = makeRange('', w, 600);
      const score = r.timeIR / Math.sqrt(w);
      if (score > bestScore) { bestScore = score; bestMult = mult; }
    }
    for (let mult = Math.max(0.2, bestMult - 0.3); mult <= bestMult + 0.3; mult += 0.02) {
      const w = 2 * mult * s;
      const r = makeRange('', w, 600);
      const score = r.timeIR / Math.sqrt(w);
      if (score > bestScore) { bestScore = score; bestMult = mult; }
    }

    btn.textContent = 'Running simulations...';
    await new Promise(r => setTimeout(r, 20));

    const opt = Math.round(bestMult * 100) / 100;
    rangeRows = [
      makeRange('⭐ Optimal (' + opt.toFixed(2) + 'σ)', 2 * opt * s),
      makeRange('Narrower (' + (opt * 0.6).toFixed(2) + 'σ)', 2 * opt * 0.6 * s),
      makeRange('Narrow (' + (opt * 0.8).toFixed(2) + 'σ)', 2 * opt * 0.8 * s),
      makeRange('Wide (' + (opt * 1.3).toFixed(2) + 'σ)', 2 * opt * 1.3 * s),
      makeRange('Wider (' + (opt * 1.8).toFixed(2) + 'σ)', 2 * opt * 1.8 * s),
    ];

    if (customLo || customHi) {
      function parseBound(val, p0, isLower) {
        if (!val) return isLower ? p0 * 0.8 : p0 * 1.2;
        val = val.replace(/\s/g, '');
        if (val.endsWith('%')) return p0 * (1 + parseFloat(val) / 100);
        return parseFloat(val);
      }
      const cL = parseBound(customLo, p0, true);
      const cH = parseBound(customHi, p0, false);
      if (cL > 0 && cH > cL) {
        const mc = runMC(p0, annSigma, T, cL, cH, nPaths, horizon);
        rangeRows.push({ name: 'Custom', pL: cL, pU: cH, w: Math.log(cH / cL), tir: mc.tir, timeIR: mc.timeInRange, mc });
      }
    }

    // Table
    document.getElementById('rangeBody').innerHTML = rangeRows.map((r, i) => {
      const pctDown = ((1 - r.pL / p0) * 100).toFixed(1);
      const pctUp = ((r.pU / p0 - 1) * 100).toFixed(1);
      return '<tr onclick="showRangeOnChart(' + i + ')" class="' + (i === 0 ? 'row-entry' : '') + '">' +
        '<td style="text-align:left">' + esc(r.name) + '</td>' +
        '<td>' + r.pL.toPrecision(5) + ' – ' + r.pU.toPrecision(5) + '</td>' +
        '<td>-' + pctDown + '% / +' + pctUp + '%</td>' +
        '<td>' + (r.tir * 100).toFixed(1) + '%</td>' +
        '<td>' + (r.timeIR * 100).toFixed(1) + '%</td></tr>';
    }).join('');

    // Range selector buttons
    document.getElementById('rangeSelector').innerHTML = rangeRows.map((r, i) =>
      '<button class="lev-btn' + (i === 0 ? ' active' : '') + '" onclick="showRangeOnChart(' + i + ')">' + esc(r.name.replace('⭐ ', '')) + '</button>'
    ).join('');

    // Backtest
    let btHTML = '<div class="section-title">Backtest: Historical TIR</div>';
    rangeRows.forEach(r => {
      let wins = 0, total = 0;
      for (let i = 0; i <= rangePrices.length - horizon - 1; i++) {
        let ok = true;
        for (let j = i; j < i + horizon && j < rangePrices.length; j++) {
          if (rangePrices[j] < r.pL || rangePrices[j] > r.pU) { ok = false; break; }
        }
        total++; if (ok) wins++;
      }
      const pct = total > 0 ? (wins / total * 100).toFixed(1) : 'N/A';
      btHTML += '<div class="row"><span class="label">' + esc(r.name.replace('⭐ ', '')) + '</span><span class="value">' + pct + '%</span></div>';
    });
    btHTML += '<div style="margin-top:8px;font-size:11px;color:#8892b0">Slides a window of ' + horizon + ' days across history.</div>';
    document.getElementById('rangeBacktest').innerHTML = btHTML;

    showRangeOnChart(0);
  } catch (e) {
    err.textContent = e.message; err.style.display = 'block';
  } finally {
    btn.disabled = false; btn.textContent = 'Analyze';
  }
}

function row(label, value) {
  const cls = typeof value === 'string' && value.startsWith('-') ? ' negative' : '';
  return '<div class="row"><span class="label">' + label + '</span><span class="value' + cls + '">' + value + '</span></div>';
}
