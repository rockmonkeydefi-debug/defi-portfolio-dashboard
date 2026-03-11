// ===== HISTORY TAB =====
let histDays = 7;
let histWallet = '';
let histInitialized = false;
let histPortfolioChart, histFeesChart, histTokenChart, histLPValueChart, histLPFeesChart;

const histColors = {
  tokens: 'rgba(77,171,247,0.8)', tokensFill: 'rgba(77,171,247,0.15)',
  lp: 'rgba(168,85,247,0.8)', lpFill: 'rgba(168,85,247,0.15)',
  fees: 'rgba(81,207,102,0.8)', feesFill: 'rgba(81,207,102,0.15)',
  total: 'rgba(224,224,224,0.9)', totalFill: 'rgba(224,224,224,0.05)',
  uncollected: 'rgba(255,169,77,0.8)', uncollectedFill: 'rgba(255,169,77,0.15)',
  balance: 'rgba(99,102,241,0.8)', balanceFill: 'rgba(99,102,241,0.15)',
  value: 'rgba(236,72,153,0.8)', valueFill: 'rgba(236,72,153,0.15)',
};

const histChartOpts = {
  responsive: true, maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: { labels: { color: '#8892b0', font: { size: 11 } } },
    tooltip: {
      backgroundColor: 'rgba(10,10,26,0.95)', titleColor: '#e0e0e0', bodyColor: '#a8b2d1',
      borderColor: '#1e3050', borderWidth: 1,
      callbacks: {
        label: function(ctx) {
          let v = ctx.parsed.y;
          if (ctx.dataset.label.includes('USD') || ctx.dataset.label.includes('Value') || ctx.dataset.label.includes('Fee'))
            return ctx.dataset.label + ': $' + v.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2});
          return ctx.dataset.label + ': ' + v.toLocaleString(undefined, {maximumFractionDigits:6});
        }
      }
    }
  },
  scales: {
    x: {
      type: 'time',
      time: { tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour:'MMM d, HH:mm', day:'MMM d', week:'MMM d', month:'MMM yyyy' } },
      grid: { color: '#1e3050' }, ticks: { color: '#8892b0', maxTicksLimit: 10 }
    },
    y: { grid: { color: '#1e3050' }, ticks: { color: '#8892b0', callback: v => '$' + v.toLocaleString() } }
  }
};

function parseTS(ts) { return new Date(ts.replace(/(\.\d{3})\d+/, '$1')); }
function histFmt(v) { return v == null ? '--' : '$' + parseFloat(v).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}); }
function histWalletParam() { return histWallet ? '&wallet=' + encodeURIComponent(histWallet) : ''; }

function setHistoryRange(days, btn) {
  histDays = days;
  document.querySelectorAll('.history-time-btns .lev-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  loadHistAllCharts();
}

function onHistWalletChange() {
  histWallet = document.getElementById('hist-wallet-filter').value;
  loadHistAllCharts();
}

async function initHistory() {
  if (histInitialized) return;
  histInitialized = true;
  await loadHistWalletFilter();
  await loadHistLatestTime();
  await loadHistAllCharts();
  await loadHistLPPositions();
  await loadHistSnapshotTable();
}

async function loadHistWalletFilter() {
  try {
    const res = await fetch('/api/history/wallets');
    const wallets = await res.json();
    const sel = document.getElementById('hist-wallet-filter');
    sel.innerHTML = '<option value="">All Wallets</option>';
    wallets.forEach(w => {
      const opt = document.createElement('option');
      opt.value = w.address;
      opt.textContent = (w.label || w.short) + ' (' + w.short + ')';
      sel.appendChild(opt);
    });
  } catch(e) {}
}

async function loadHistLatestTime() {
  try {
    const res = await fetch('/api/history/latest');
    const data = await res.json();
    document.getElementById('hist-last-snapshot').textContent = data.latest_snapshot
      ? 'Last snapshot: ' + new Date(data.latest_snapshot).toLocaleString()
      : 'No snapshots taken yet';
  } catch(e) {}
}

async function loadHistAllCharts() {
  await Promise.all([loadHistPortfolioChart(), loadHistFeesChart(), loadHistTokenChart()]);
}

async function loadHistPortfolioChart() {
  try {
    const res = await fetch('/api/history/portfolio?days=' + histDays + histWalletParam());
    const data = await res.json();
    if (!data.length) { updateHistCards(null); return; }

    const labels = data.map(d => parseTS(d.timestamp));
    const latest = data[data.length - 1], first = data[0];
    updateHistCards(latest, first);

    if (histPortfolioChart) histPortfolioChart.destroy();
    histPortfolioChart = new Chart(document.getElementById('histPortfolioChart'), {
      type: 'line',
      data: { labels, datasets: [
        { label:'Total Value (USD)', data:data.map(d=>d.total_value), borderColor:histColors.total, backgroundColor:histColors.totalFill, fill:false, tension:0.3, borderWidth:2, pointRadius:data.length>30?0:3 },
        { label:'Token Holdings (USD)', data:data.map(d=>d.token_value), borderColor:histColors.tokens, backgroundColor:histColors.tokensFill, fill:true, tension:0.3, borderWidth:1.5, pointRadius:0 },
        { label:'LP Positions (USD)', data:data.map(d=>d.lp_value), borderColor:histColors.lp, backgroundColor:histColors.lpFill, fill:true, tension:0.3, borderWidth:1.5, pointRadius:0 },
        { label:'Uncollected Fees (USD)', data:data.map(d=>d.fees_value), borderColor:histColors.fees, backgroundColor:histColors.feesFill, fill:true, tension:0.3, borderWidth:1.5, pointRadius:0 },
      ]},
      options: histChartOpts
    });
  } catch(e) { console.error('History portfolio chart error:', e); }
}

function updateHistCards(latest, first) {
  if (!latest) {
    document.getElementById('hist-total').textContent = 'No data yet';
    document.getElementById('hist-tokens').textContent = '--';
    document.getElementById('hist-lp').textContent = '--';
    document.getElementById('hist-fees').textContent = '--';
    return;
  }
  const hm = v => '<span class="maskable">' + v + '</span>';
  document.getElementById('hist-total').innerHTML = hm(histFmt(latest.total_value));
  document.getElementById('hist-tokens').innerHTML = hm(histFmt(latest.token_value));
  document.getElementById('hist-lp').innerHTML = hm(histFmt(latest.lp_value));
  document.getElementById('hist-fees').innerHTML = hm(histFmt(latest.fees_value));

  if (first && latest.total_value && first.total_value) {
    const change = latest.total_value - first.total_value;
    const pct = ((change / first.total_value) * 100).toFixed(1);
    const el = document.getElementById('hist-total-change');
    const pos = change >= 0;
    el.innerHTML = hm((pos?'+':'') + histFmt(change) + ' (' + (pos?'+':'') + pct + '%)');
    el.style.color = pos ? '#51cf66' : '#ff6b6b';
  }
}

async function loadHistFeesChart() {
  try {
    const res = await fetch('/api/history/fees?days=' + histDays + histWalletParam());
    const data = await res.json();
    if (!data.length) return;
    if (histFeesChart) histFeesChart.destroy();
    histFeesChart = new Chart(document.getElementById('histFeesChart'), {
      type: 'line',
      data: { labels: data.map(d=>parseTS(d.timestamp)), datasets: [
        { label:'Total Fees (USD)', data:data.map(d=>d.total_fees_usd), borderColor:histColors.fees, backgroundColor:histColors.feesFill, fill:true, tension:0.3, borderWidth:2, pointRadius:data.length>30?0:3 },
        { label:'Collected (USD)', data:data.map(d=>d.collected_usd), borderColor:histColors.tokens, backgroundColor:histColors.tokensFill, fill:true, tension:0.3, borderWidth:1.5, pointRadius:0 },
        { label:'Uncollected (USD)', data:data.map(d=>d.uncollected_usd), borderColor:histColors.uncollected, backgroundColor:histColors.uncollectedFill, fill:true, tension:0.3, borderWidth:1.5, pointRadius:0 },
      ]},
      options: histChartOpts
    });
  } catch(e) { console.error('History fees chart error:', e); }
}

async function loadHistTokenChart() {
  try {
    const symbol = document.getElementById('hist-token-select').value;
    const res = await fetch('/api/history/token/' + symbol + '?days=' + histDays + histWalletParam());
    const data = await res.json();
    if (histTokenChart) histTokenChart.destroy();
    if (!data.length) return;

    const byTime = {};
    data.forEach(d => {
      if (!byTime[d.timestamp]) byTime[d.timestamp] = {balance:0, value:0};
      byTime[d.timestamp].balance += d.balance;
      byTime[d.timestamp].value += d.value_usd;
    });
    const ts = Object.keys(byTime).sort();

    histTokenChart = new Chart(document.getElementById('histTokenChart'), {
      type: 'line',
      data: { labels: ts.map(t=>parseTS(t)), datasets: [
        { label:symbol+' Balance', data:ts.map(t=>byTime[t].balance), borderColor:histColors.balance, backgroundColor:histColors.balanceFill, fill:true, tension:0.3, borderWidth:2, yAxisID:'y', pointRadius:ts.length>30?0:3 },
        { label:symbol+' Value (USD)', data:ts.map(t=>byTime[t].value), borderColor:histColors.value, backgroundColor:histColors.valueFill, fill:false, tension:0.3, borderWidth:1.5, yAxisID:'y1', pointRadius:0 },
      ]},
      options: { ...histChartOpts, scales: { ...histChartOpts.scales,
        y: { ...histChartOpts.scales.y, position:'left', ticks:{color:'#8892b0', callback:v=>v.toLocaleString(undefined,{maximumFractionDigits:4})} },
        y1: { position:'right', grid:{drawOnChartArea:false}, ticks:{color:'#8892b0', callback:v=>'$'+v.toLocaleString()} }
      }}
    });
  } catch(e) { console.error('History token chart error:', e); }
}

async function loadHistLPPositions() {
  try {
    const res = await fetch('/api/history/positions');
    const positions = await res.json();
    const sel = document.getElementById('hist-lp-select');
    sel.innerHTML = '<option value="">Select a position...</option>';
    if (!positions || !positions.length) return;
    positions.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.position_id;
      opt.textContent = (p.is_open?'🟢':'🔴') + ' #' + p.position_id + ' ' + p.pool_pair + ' (' + p.chain + ')';
      sel.appendChild(opt);
    });
    sel.value = positions[0].position_id;
    loadHistLPChart();
  } catch(e) {}
}

async function loadHistLPChart() {
  const pid = document.getElementById('hist-lp-select').value;
  if (!pid) return;
  try {
    const res = await fetch('/api/history/lp/' + pid + '?days=' + histDays);
    const data = await res.json();
    if (!data.length) return;
    const labels = data.map(d=>parseTS(d.timestamp));

    if (histLPValueChart) histLPValueChart.destroy();
    histLPValueChart = new Chart(document.getElementById('histLPValueChart'), {
      type:'line',
      data: { labels, datasets: [
        { label:'Total Value (USD)', data:data.map(d=>d.total_value_usd), borderColor:histColors.total, fill:false, tension:0.3, borderWidth:2, pointRadius:data.length>30?0:3 },
        { label:'Liquidity Value (USD)', data:data.map(d=>d.liquidity_value_usd), borderColor:histColors.lp, backgroundColor:histColors.lpFill, fill:true, tension:0.3, borderWidth:1.5, pointRadius:0 },
      ]},
      options: { ...histChartOpts, plugins:{ ...histChartOpts.plugins, title:{display:true, text:'Position Value', color:'#e0e0e0', font:{size:13}} } }
    });

    if (histLPFeesChart) histLPFeesChart.destroy();
    histLPFeesChart = new Chart(document.getElementById('histLPFeesChart'), {
      type:'line',
      data: { labels, datasets: [
        { label:'Uncollected Fees (USD)', data:data.map(d=>d.fees_uncollected_usd), borderColor:histColors.uncollected, backgroundColor:histColors.uncollectedFill, fill:true, tension:0.3, borderWidth:2, pointRadius:data.length>30?0:3 },
        { label:'Collected Fees (USD)', data:data.map(d=>d.fees_collected_usd), borderColor:histColors.fees, backgroundColor:histColors.feesFill, fill:true, tension:0.3, borderWidth:1.5, pointRadius:0 },
      ]},
      options: { ...histChartOpts, plugins:{ ...histChartOpts.plugins, title:{display:true, text:'Fees Tracking', color:'#e0e0e0', font:{size:13}} } }
    });
  } catch(e) { console.error('History LP chart error:', e); }
}

async function loadHistSnapshotTable() {
  try {
    const res = await fetch('/api/history/runs');
    const runs = await res.json();
    const tbody = document.getElementById('hist-snapshot-table');
    if (!runs.length) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#8892b0;padding:20px">No snapshots yet. Use the Snapshot button on the Portfolio tab.</td></tr>';
      return;
    }
    tbody.innerHTML = runs.map(r => {
      const statusCls = r.status==='completed' ? 'positive' : r.status==='failed' ? 'negative' : '';
      const icon = r.status==='completed' ? '✓' : r.status==='failed' ? '✗' : '⏳';
      const dur = r.duration_seconds ? r.duration_seconds.toFixed(1)+'s' : '--';
      const wallet = r.wallet_address ? r.wallet_address.substring(0,6)+'...'+r.wallet_address.substring(38) : '--';
      return '<tr><td style="text-align:left">'+new Date(r.timestamp).toLocaleString()+'</td>' +
        '<td style="text-align:left;font-size:12px;color:#a8b2d1;font-family:monospace">'+wallet+'</td>' +
        '<td class="'+statusCls+'">'+icon+' '+r.status+'</td>' +
        '<td>'+dur+'</td></tr>';
    }).join('');
  } catch(e) {}
}
