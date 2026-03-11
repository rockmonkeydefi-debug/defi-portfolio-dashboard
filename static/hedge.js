// ===== HEDGE TAB =====
let hedgeChart;
let selectedLev = 2;

function setLev(lev) {
  selectedLev = lev;
  document.querySelectorAll('.lev-btn').forEach(b => b.classList.toggle('active', parseInt(b.dataset.lev) === lev));
  setTimeout(computeHedge, 0);
}

function computeHedge() {
  const pair = document.getElementById('pair').value.trim();
  const pLow = parseFloat(document.getElementById('pLow').value);
  const pHigh = parseFloat(document.getElementById('pHigh').value);
  const pEntry = parseFloat(document.getElementById('pEntry').value);
  const notional = parseFloat(document.getElementById('notional').value);
  const feeApr = parseFloat(document.getElementById('feeApr').value);
  const hedgePct = parseFloat(document.getElementById('hedgePct').value) / 100;
  const leverage = selectedLev;
  const fundingApr = parseFloat(document.getElementById('fundingApr').value);
  const hEntry = parseFloat(document.getElementById('hedgeEntry').value) || pEntry;
  if ([pLow, pHigh, pEntry, notional, feeApr, fundingApr].some(isNaN) || pLow >= pHigh) return;

  const parts = pair.split('/'), base = esc(parts[0] || '?'), quote = esc(parts[1] || '?');

  // LP math
  const sp = Math.sqrt(pEntry), sl = Math.sqrt(pLow), sh = Math.sqrt(pHigh);
  const L = notional / (2 * sp - pEntry / sh - sl);
  function lpVal(P) {
    if (P <= pLow) return L * (1 / sl - 1 / sh) * P;
    if (P >= pHigh) return L * (sh - sl);
    return L * (Math.sqrt(P) - sl) + L * (1 / Math.sqrt(P) - 1 / sh) * P;
  }

  // Hedge: short perp
  const hedgeNotional = notional * hedgePct;
  const margin = hedgeNotional / leverage;
  const shortSize = hedgeNotional / hEntry;
  const liqPrice = hEntry + margin / shortSize;

  const dailyFees = notional * (feeApr / 100) / 365;
  const dailyFunding = hedgeNotional * (fundingApr / 100) / 365;

  // Stop loss: price where net PnL = -2% of notional
  const targetLoss = -0.02 * notional;
  let stopLoss = hEntry;
  for (let p = hEntry + 1; p < liqPrice; p += 0.5) {
    const net = (lpVal(p) - notional) + (-shortSize * (p - hEntry));
    if (net <= targetLoss) { stopLoss = p; break; }
  }

  // Table rows sorted high to low
  const pricePoints = [
    { label: `${base} +15%`, price: pEntry * 1.15 },
    { label: `LP Upper Range (${((pHigh/pEntry-1)*100).toFixed(0)}%)`, price: pHigh },
    { label: 'Entry (LP)', price: pEntry, isEntry: true },
    { label: 'Entry (Hedge)', price: hEntry, isEntry: true },
    { label: `${base} -15%`, price: pEntry * 0.85 },
    { label: `LP Lower Range (${((pLow/pEntry-1)*100).toFixed(0)}%)`, price: pLow },
  ];
  if (stopLoss > hEntry) pricePoints.push({ label: '⚠️ Stop Loss', price: stopLoss, isStop: true });
  pricePoints.sort((a, b) => b.price - a.price);

  const fmt = v => (v >= 0 ? '+' : '-') + '$' + Math.abs(Math.round(v)).toLocaleString();
  const fmtPct = v => (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
  const cls = v => v >= 0 ? 'positive' : 'negative';

  let tableHTML = `<table class="hedge-table"><thead><tr>
    <th style="text-align:left">Price Point</th><th>${base} Price</th><th>LP P&L</th><th>Hedge P&L</th><th>Net P&L</th><th>Net %</th>
  </tr></thead><tbody>`;
  pricePoints.forEach(pt => {
    const lpPnl = lpVal(pt.price) - notional;
    const hedgePnl = -shortSize * (pt.price - hEntry);
    const net = lpPnl + hedgePnl;
    const netPct = net / notional * 100;
    const rowCls = pt.isEntry ? ' class="row-entry"' : pt.isStop ? ' class="row-stop"' : '';
    tableHTML += `<tr${rowCls}>
      <td>${pt.label}</td><td>$${Math.round(pt.price).toLocaleString()}</td>
      <td class="${cls(lpPnl)}">${fmt(lpPnl)}</td><td class="${cls(hedgePnl)}">${fmt(hedgePnl)}</td>
      <td class="${cls(net)}" style="font-weight:700">${fmt(net)}</td>
      <td class="${cls(netPct)}" style="font-weight:700">${fmtPct(netPct)}</td></tr>`;
  });
  tableHTML += '</tbody></table>';
  document.getElementById('hedgeTable').innerHTML = tableHTML;

  // Chart
  const chartPrices = [], chartLp = [], chartHedge = [], chartNet = [];
  const lo = pLow * 0.9, hi = pHigh * 1.1;
  for (let i = 0; i < 200; i++) {
    const P = lo + (hi - lo) * i / 199;
    chartPrices.push(P);
    chartLp.push(lpVal(P) - notional);
    chartHedge.push(-shortSize * (P - hEntry));
    chartNet.push((lpVal(P) - notional) + (-shortSize * (P - hEntry)));
  }

  const vLine = (x, c, l) => ({ type: 'line', xMin: x, xMax: x, borderColor: c, borderWidth: 1.5, borderDash: [6, 4], label: { display: true, content: l, position: 'start', color: c, font: { size: 10 }, backgroundColor: 'transparent' } });
  const annotations = {
    lLow: vLine(pLow, 'rgba(255,107,107,0.6)', `${pLow}`),
    lHigh: vLine(pHigh, 'rgba(255,107,107,0.6)', `${pHigh}`),
    lEntry: vLine(pEntry, 'rgba(150,150,150,0.6)', `LP ${pEntry}`),
    lZero: { type: 'line', yMin: 0, yMax: 0, borderColor: 'rgba(255,255,255,0.2)', borderWidth: 1 },
    lLiq: vLine(liqPrice, 'rgba(255,50,50,0.8)', `Liq $${Math.round(liqPrice)}`),
  };
  if (hEntry !== pEntry) annotations.lHEntry = vLine(hEntry, 'rgba(255,165,0,0.6)', `Hedge ${hEntry}`);
  if (stopLoss > hEntry) annotations.lStop = vLine(stopLoss, 'rgba(255,200,50,0.7)', `SL $${Math.round(stopLoss)}`);

  if (hedgeChart) hedgeChart.destroy();
  hedgeChart = new Chart(document.getElementById('hedgeChartCanvas'), {
    type: 'line',
    data: { labels: chartPrices, datasets: [
      { label: 'LP P&L', data: chartLp.map((v, i) => ({ x: chartPrices[i], y: v })), borderColor: '#4dabf7', borderWidth: 2, pointRadius: 0, fill: false },
      { label: 'Hedge P&L', data: chartHedge.map((v, i) => ({ x: chartPrices[i], y: v })), borderColor: '#ffa94d', borderWidth: 2, pointRadius: 0, borderDash: [6, 3], fill: false },
      { label: 'Net P&L', data: chartNet.map((v, i) => ({ x: chartPrices[i], y: v })), borderColor: '#64ffda', borderWidth: 2.5, pointRadius: 0, fill: { target: 'origin', above: 'rgba(100,255,218,0.1)', below: 'rgba(255,107,107,0.1)' } },
    ]},
    options: {
      responsive: true, maintainAspectRatio: false, animation: { duration: 200 },
      interaction: { mode: 'index', intersect: false },
      plugins: { tooltip: { mode: 'index', intersect: false, callbacks: { title: items => `${base} Price: $${Math.round(items[0].parsed.x).toLocaleString()}`, label: item => `${item.dataset.label}: ${item.parsed.y >= 0 ? '+' : '-'}$${Math.abs(Math.round(item.parsed.y)).toLocaleString()}` } }, title: { display: true, text: 'LP + Hedge P&L', color: '#e0e0e0', font: { size: 13 } }, legend: { labels: { color: '#8892b0', boxWidth: 12, font: { size: 11 } } }, annotation: { annotations } },
      scales: {
        x: { type: 'linear', min: lo, max: hi, ticks: { color: '#8892b0', maxTicksLimit: 10, callback: v => Math.round(v) }, grid: { color: '#1e3050' }, title: { display: true, text: `${base} Price (${quote})`, color: '#8892b0' } },
        y: { ticks: { color: '#8892b0', callback: v => '$' + v.toLocaleString() }, grid: { color: '#1e3050' }, title: { display: true, text: 'P&L ($)', color: '#8892b0' } }
      }
    }
  });

  // Sidebar
  const f0 = v => Math.round(v).toLocaleString();
  const f2 = v => v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  document.getElementById('hedgeSidebar').innerHTML = `
    <div class="section-title">🛡️ HEDGE PARAMETERS</div>
    <div class="row"><span class="label">Hedge</span><span class="value" style="color:#64ffda">${(hedgePct * 100).toFixed(0)}% of capital</span></div>
    <div class="row"><span class="label">Short size</span><span class="value">$${f0(hedgeNotional)}</span></div>
    <div class="row"><span class="label">${base} shorted</span><span class="value">${shortSize.toFixed(4)}</span></div>
    <div class="row"><span class="label">Leverage</span><span class="value" style="color:#64ffda">${leverage}x</span></div>
    <div class="row"><span class="label">Hedge entry</span><span class="value">$${f0(hEntry)}</span></div>

    <div class="section-title">💵 REQUIRED MARGIN</div>
    <div style="text-align:center;padding:8px 0;">
      <div class="highlight">$${f0(margin)}</div>
    </div>

    <div class="section-title">💀 LIQUIDATION PRICE</div>
    <div style="text-align:center;padding:8px 0;">
      <div class="highlight" style="color:#ff6b6b">$${f0(liqPrice)}</div>
      <div style="color:#8892b0;font-size:11px;">${((liqPrice / hEntry - 1) * 100).toFixed(1)}% above hedge entry</div>
    </div>

    <div class="section-title">⚠️ STOP LOSS (2% capital)</div>
    <div style="text-align:center;padding:8px 0;">
      <div class="highlight" style="color:#ffa94d">$${f0(stopLoss)}</div>
      <div style="color:#8892b0;font-size:11px;">${((stopLoss / hEntry - 1) * 100).toFixed(1)}% above hedge entry</div>
    </div>

    <div class="section-title">💰 COSTS & INCOME</div>
    <div class="row"><span class="label">LP fees/day</span><span class="value positive">+$${f2(dailyFees)}</span></div>
    <div class="row"><span class="label">Funding/day</span><span class="value negative">-$${f2(dailyFunding)}</span></div>
    <div class="row"><span class="label">Net/day</span><span class="value ${cls(dailyFees - dailyFunding)}">${fmt(dailyFees - dailyFunding)}</span></div>
    <div class="row"><span class="label">Net/month</span><span class="value ${cls(dailyFees - dailyFunding)}">${fmt((dailyFees - dailyFunding) * 30)}</span></div>

    <div style="margin-top:18px;padding:14px;background:#0a0a1a;border:1px solid #64ffda33;border-radius:8px;text-align:center;">
      <div style="color:#a8b2d1;font-size:11px;letter-spacing:1px;">NET APR (FEES - FUNDING)</div>
      <div class="highlight" style="margin:4px 0;">${((dailyFees - dailyFunding) * 365 / notional * 100).toFixed(1)}%</div>
    </div>`;
}
