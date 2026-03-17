// ===== HISTORY TAB =====
let histInitialized = false;
let histPortfolioChart = null;
let histPositionsChart = null;
let histRange = '7d';
let histCustomFrom = '';
let histCustomTo = '';

function initHistory() {
  if (histInitialized) return;
  histInitialized = true;
  loadHistoryCharts();
  loadClosedPositions();
}

function setHistRange(range, btn) {
  histRange = range;
  document.querySelectorAll('.hist-range-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  // Clear custom dates when using presets
  if (range !== 'custom') {
    document.getElementById('hist-date-from').value = '';
    document.getElementById('hist-date-to').value = '';
  }
  loadHistoryCharts();
}

function applyCustomRange() {
  var from = document.getElementById('hist-date-from').value;
  var to = document.getElementById('hist-date-to').value;
  if (from) {
    histRange = 'custom';
    histCustomFrom = from;
    histCustomTo = to || new Date().toISOString().split('T')[0];
    document.querySelectorAll('.hist-range-btn').forEach(b => b.classList.remove('active'));
    loadHistoryCharts();
  }
}

function getDaysFromRange() {
  if (histRange === '24h') return 1;
  if (histRange === '7d') return 7;
  if (histRange === '30d') return 30;
  if (histRange === '1y') return 365;
  if (histRange === 'all') return 9999;
  return 30;
}

async function loadHistoryCharts() {
  var params = '';
  if (histRange === 'custom' && histCustomFrom) {
    params = '?from=' + histCustomFrom + '&to=' + histCustomTo;
  } else {
    params = '?days=' + getDaysFromRange();
  }

  try {
    var resp = await fetch('/api/history/portfolio-chart' + params);
    var data = await resp.json();
    renderPortfolioChart(data);
    renderPositionsChart(data);
    renderHistSummary(data);
    loadClosedPositions();
  } catch(e) {
    console.error('History load error:', e);
  }
}

function renderHistSummary(data) {
  if (!data.length) {
    document.getElementById('hist-summary').innerHTML = '<span style="color:#8892b0">No snapshot data yet. Snapshots are taken every 2 hours.</span>';
    return;
  }
  var first = data[0], last = data[data.length - 1];
  var change = last.total_value - first.total_value;
  var pct = first.total_value > 0 ? (change / first.total_value * 100) : 0;
  var pos = change >= 0;
  var hm = function(v) { return '<span class="maskable">' + v + '</span>'; };
  document.getElementById('hist-summary').innerHTML =
    '<div class="market-grid">' +
      '<div class="market-card"><div style="color:#8892b0;font-size:11px">Current Value</div><div class="highlight">' + hm('$' + Math.round(last.total_value).toLocaleString()) + '</div></div>' +
      '<div class="market-card"><div style="color:#8892b0;font-size:11px">Period Start</div><div class="highlight">' + hm('$' + Math.round(first.total_value).toLocaleString()) + '</div></div>' +
      '<div class="market-card"><div style="color:#8892b0;font-size:11px">Change</div><div class="highlight" style="color:' + (pos ? '#51cf66' : '#ff6b6b') + '">' + hm((pos?'+':'') + '$' + Math.round(Math.abs(change)).toLocaleString()) + '</div></div>' +
      '<div class="market-card"><div style="color:#8892b0;font-size:11px">Change %</div><div class="highlight" style="color:' + (pos ? '#51cf66' : '#ff6b6b') + '">' + (pos?'+':'') + pct.toFixed(2) + '%</div></div>' +
    '</div>';
}

var histChartDefaults = {
  responsive: true, maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: { labels: { color: '#8892b0', font: { size: 11 } } },
    tooltip: {
      backgroundColor: 'rgba(10,10,26,0.95)', titleColor: '#e0e0e0', bodyColor: '#a8b2d1',
      borderColor: '#1e3050', borderWidth: 1,
      callbacks: {
        label: function(ctx) {
          if (typeof valuesMasked !== 'undefined' && valuesMasked) return ctx.dataset.label + ': ••••';
          return ctx.dataset.label + ': $' + ctx.parsed.y.toLocaleString(undefined, {minimumFractionDigits:0, maximumFractionDigits:0});
        }
      }
    }
  },
  scales: {
    x: {
      type: 'time',
      time: { tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour:'MMM d HH:mm', day:'MMM d', week:'MMM d', month:'MMM yyyy' } },
      grid: { color: '#1e3050' }, ticks: { color: '#8892b0', maxTicksLimit: 10 }
    },
    y: { grid: { color: '#1e3050' }, ticks: { color: '#8892b0', callback: function(v) { return (typeof valuesMasked !== 'undefined' && valuesMasked) ? '••••' : '$' + v.toLocaleString(); } } }
  }
};

function parseTS(ts) { return new Date(ts.replace(/(\.\d{3})\d+/, '$1')); }

function renderPortfolioChart(data) {
  if (!data.length) return;
  var labels = data.map(function(d) { return parseTS(d.timestamp); });
  if (histPortfolioChart) histPortfolioChart.destroy();
  histPortfolioChart = new Chart(document.getElementById('histChart1'), {
    type: 'line',
    data: { labels: labels, datasets: [
      { label: 'Total Portfolio', data: data.map(function(d){return d.total_value;}), borderColor: '#e0e0e0', backgroundColor: 'rgba(224,224,224,0.05)', fill: false, tension: 0.3, borderWidth: 2, pointRadius: data.length > 50 ? 0 : 3 },
      { label: 'Tokens', data: data.map(function(d){return d.tokens_value;}), borderColor: '#4dabf7', backgroundColor: 'rgba(77,171,247,0.1)', fill: true, tension: 0.3, borderWidth: 1.5, pointRadius: 0 },
      { label: 'LP Positions', data: data.map(function(d){return d.lp_value;}), borderColor: '#a78bfa', backgroundColor: 'rgba(167,139,250,0.1)', fill: true, tension: 0.3, borderWidth: 1.5, pointRadius: 0 },
      { label: 'Hedge PnL', data: data.map(function(d){return d.hedge_value;}), borderColor: '#ffa94d', backgroundColor: 'rgba(255,169,77,0.1)', fill: true, tension: 0.3, borderWidth: 1.5, pointRadius: 0 },
      { label: 'Lending Net', data: data.map(function(d){return d.lending_value;}), borderColor: '#51cf66', backgroundColor: 'rgba(81,207,102,0.1)', fill: true, tension: 0.3, borderWidth: 1.5, pointRadius: 0 },
    ]},
    options: { ...histChartDefaults, plugins: { ...histChartDefaults.plugins, title: { display: true, text: 'Total Portfolio Value', color: '#e0e0e0', font: { size: 14 } } } }
  });
}

function renderPositionsChart(data) {
  if (!data.length) return;
  var labels = data.map(function(d) { return parseTS(d.timestamp); });
  if (histPositionsChart) histPositionsChart.destroy();
  histPositionsChart = new Chart(document.getElementById('histChart2'), {
    type: 'line',
    data: { labels: labels, datasets: [
      { label: 'LP + Hedge Value', data: data.map(function(d){return d.lp_value + d.hedge_value;}), borderColor: '#a78bfa', backgroundColor: 'rgba(167,139,250,0.1)', fill: true, tension: 0.3, borderWidth: 2, pointRadius: data.length > 50 ? 0 : 3, yAxisID: 'y' },
      { label: 'Total Accrued Fees', data: data.map(function(d){return d.total_fees;}), borderColor: '#51cf66', backgroundColor: 'rgba(81,207,102,0.15)', fill: true, tension: 0.3, borderWidth: 2, pointRadius: data.length > 50 ? 0 : 3, yAxisID: 'y1' },
    ]},
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#8892b0', font: { size: 11 } } },
        title: { display: true, text: 'Active Positions & Fees', color: '#e0e0e0', font: { size: 14 } },
        tooltip: {
          backgroundColor: 'rgba(10,10,26,0.95)', titleColor: '#e0e0e0', bodyColor: '#a8b2d1',
          borderColor: '#1e3050', borderWidth: 1,
          callbacks: {
            label: function(ctx) {
              if (typeof valuesMasked !== 'undefined' && valuesMasked) return ctx.dataset.label + ': ••••';
              return ctx.dataset.label + ': $' + ctx.parsed.y.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0});
            }
          }
        }
      },
      scales: {
        x: {
          type: 'time',
          time: { tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d', week: 'MMM d', month: 'MMM yyyy' } },
          grid: { color: '#1e3050' }, ticks: { color: '#8892b0', maxTicksLimit: 10 }
        },
        y: {
          position: 'left',
          grid: { color: '#1e3050' },
          ticks: { color: '#a78bfa', callback: function(v) { return (typeof valuesMasked !== 'undefined' && valuesMasked) ? '••••' : '$' + v.toLocaleString(); } },
          title: { display: true, text: 'Position Value', color: '#a78bfa', font: { size: 11 } }
        },
        y1: {
          position: 'right',
          grid: { drawOnChartArea: false },
          ticks: { color: '#51cf66', callback: function(v) { return (typeof valuesMasked !== 'undefined' && valuesMasked) ? '••••' : '$' + v.toLocaleString(); } },
          title: { display: true, text: 'Accrued Fees', color: '#51cf66', font: { size: 11 } }
        }
      }
    }
  });
}



async function loadClosedPositions() {
  var params = '';
  if (histRange === 'custom' && histCustomFrom) {
    params = '?from=' + histCustomFrom + '&to=' + histCustomTo;
  } else {
    params = '?days=' + getDaysFromRange();
  }
  try {
    var resp = await fetch('/api/history/closed-positions' + params);
    var data = await resp.json();
    renderClosedLPs(data.closed_lps || []);
    renderClosedHedges(data.closed_hedges || []);
  } catch(e) {
    console.error('Closed positions error:', e);
  }
}

function renderClosedLPs(lps) {
  var el = document.getElementById('hist-closed-lps');
  if (!lps.length) {
    el.innerHTML = '<span style="color:#8892b0;font-size:13px">No closed LP positions yet</span>';
    return;
  }
  var hm = function(v) { return '<span class="maskable">' + v + '</span>'; };
  var f2 = function(v) { return '$' + v.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}); };
  el.innerHTML = '<table class="hedge-table" style="font-size:12px"><thead><tr>' +
    '<th style="text-align:left">Pair</th><th>Entry</th><th>Exit</th><th>Range</th><th>Fees</th><th>Return</th><th>APR</th><th>Days</th>' +
    '</tr></thead><tbody>' +
    lps.map(function(lp) {
      var retCls = lp.total_return_pct >= 0 ? 'positive' : 'negative';
      return '<tr>' +
        '<td style="text-align:left">' + esc(lp.pair) + '<br><span style="color:#555;font-size:10px">' + esc(lp.chain) + ' • ' + lp.entry_date + ' → ' + lp.exit_date + '</span></td>' +
        '<td>' + hm(f2(lp.entry_value)) + '</td>' +
        '<td>' + hm(f2(lp.exit_value)) + '</td>' +
        '<td style="font-size:11px">' + (lp.range_lower||0).toLocaleString(undefined,{maximumFractionDigits:0}) + ' – ' + (lp.range_upper||0).toLocaleString(undefined,{maximumFractionDigits:0}) + '</td>' +
        '<td class="positive">' + hm(f2(lp.total_fees)) + '</td>' +
        '<td class="' + retCls + '" style="font-weight:600">' + (lp.total_return_pct >= 0 ? '+' : '') + lp.total_return_pct.toFixed(1) + '%</td>' +
        '<td class="' + retCls + '" style="font-weight:600">' + (lp.annual_apr >= 0 ? '+' : '') + lp.annual_apr.toFixed(1) + '%</td>' +
        '<td>' + lp.days_held + 'd</td></tr>';
    }).join('') +
    '</tbody></table>';
}

function renderClosedHedges(hedges) {
  var el = document.getElementById('hist-closed-hedges');
  if (!hedges.length) {
    el.innerHTML = '<span style="color:#8892b0;font-size:13px">No closed hedge positions yet</span>';
    return;
  }
  var hm = function(v) { return '<span class="maskable">' + v + '</span>'; };
  var f2 = function(v) { return '$' + v.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}); };
  el.innerHTML = '<table class="hedge-table" style="font-size:12px"><thead><tr>' +
    '<th style="text-align:left">Market</th><th>Direction</th><th>Entry</th><th>Exit</th><th>Size</th><th>PnL</th><th>Dates</th>' +
    '</tr></thead><tbody>' +
    hedges.map(function(h) {
      var pnlCls = h.pnl_usd >= 0 ? 'positive' : 'negative';
      return '<tr>' +
        '<td style="text-align:left">' + esc(h.market) + '</td>' +
        '<td>' + (h.direction === 'long' ? ''+li('trending-up',14,'#51cf66')+' Long' : ''+li('trending-down',14,'#ff6b6b')+' Short') + '</td>' +
        '<td>' + hm(f2(h.entry_price)) + '</td>' +
        '<td>' + hm(f2(h.exit_price)) + '</td>' +
        '<td>' + hm(f2(h.size_usd)) + '</td>' +
        '<td class="' + pnlCls + '" style="font-weight:600">' + hm((h.pnl_usd >= 0 ? '+' : '') + f2(h.pnl_usd)) + '</td>' +
        '<td style="font-size:11px">' + h.entry_date + ' → ' + h.exit_date + '</td></tr>';
    }).join('') +
    '</tbody></table>';
}
