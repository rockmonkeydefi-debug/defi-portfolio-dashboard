// ===== AI DAILY BRIEF =====

function setMarketView(view) {
  document.getElementById('mkt-live-view').style.display = view === 'live' ? '' : 'none';
  document.getElementById('mkt-ai-view').style.display = view === 'ai' ? '' : 'none';
  document.getElementById('mkt-view-live').classList.toggle('active', view === 'live');
  document.getElementById('mkt-view-ai').classList.toggle('active', view === 'ai');
  if (view === 'ai') { loadAIReportList(); loadLatestDigest(); }
}

async function loadAIReportList() {
  try {
    var resp = await fetch('/api/ai/reports?limit=20');
    var reports = await resp.json();
    var sel = document.getElementById('ai-report-select');
    sel.innerHTML = '<option value="">Select previous report...</option>';
    reports.forEach(function(r) {
      var opt = document.createElement('option');
      opt.value = r.id;
      opt.textContent = r.timestamp.substring(0, 16).replace('T', ' ') + ' — ' + (r.portfolio_alignment || 'N/A');
      sel.appendChild(opt);
    });
    // Auto-load latest
    if (reports.length > 0) {
      sel.value = reports[0].id;
      loadAIReport(reports[0].id);
    }
  } catch(e) {}
}

async function generateAIReport() {
  var btn = document.getElementById('ai-generate-btn');
  var status = document.getElementById('ai-status');
  btn.disabled = true; btn.textContent = 'Generating...';
  status.textContent = 'Fetching data and calling LLM...';
  status.style.color = '#ffa94d';
  try {
    var resp = await fetch('/api/ai/generate', {method: 'POST'});
    var data = await resp.json();
    if (resp.ok) {
      status.textContent = 'Report generated';
      status.style.color = '#51cf66';
      renderAIReport(data.report);
      loadAIReportList();
    } else {
      status.textContent = data.error || 'Error generating report';
      status.style.color = '#ff6b6b';
    }
  } catch(e) {
    status.textContent = 'Network error: ' + e.message;
    status.style.color = '#ff6b6b';
  } finally {
    btn.disabled = false; btn.textContent = 'Generate Report';
  }
}

async function loadAIReport(reportId) {
  if (!reportId) return;
  try {
    var resp = await fetch('/api/ai/reports/' + reportId);
    var data = await resp.json();
    if (data.full_report_json) {
      renderAIReport(typeof data.full_report_json === 'string' ? JSON.parse(data.full_report_json) : data.full_report_json);
    }
  } catch(e) {}
}

function renderAIReport(report) {
  var el = document.getElementById('ai-report-content');
  var html = '';
  
  // Market Regime
  var regime = report.market_regime || {};
  html += '<div class="market-card market-card-wide">';
  html += '<div class="section-title" style="margin-top:0">📊 Market Regime Assessment</div>';
  ['short_term_7d', 'mid_term_30d'].forEach(function(period) {
    var r = regime[period];
    if (!r) return;
    var label = period === 'short_term_7d' ? 'Short-term (7d)' : 'Mid-term (30d)';
    html += '<div style="margin-bottom:12px">';
    html += '<div style="color:#e0e0e0;font-weight:600;margin-bottom:4px">' + label + '</div>';
    html += '<div style="display:flex;gap:4px;margin-bottom:4px">';
    html += '<div style="flex:' + (r.bull||0) + ';background:#51cf66;height:8px;border-radius:4px" title="Bull ' + (r.bull||0) + '%"></div>';
    html += '<div style="flex:' + (r.sideways||0) + ';background:#ffa94d;height:8px;border-radius:4px" title="Sideways ' + (r.sideways||0) + '%"></div>';
    html += '<div style="flex:' + (r.bear||0) + ';background:#ff6b6b;height:8px;border-radius:4px" title="Bear ' + (r.bear||0) + '%"></div>';
    html += '</div>';
    html += '<div style="display:flex;justify-content:space-between;font-size:11px">';
    html += '<span class="positive">Bull ' + (r.bull||0) + '%</span>';
    html += '<span style="color:#ffa94d">Sideways ' + (r.sideways||0) + '%</span>';
    html += '<span class="negative">Bear ' + (r.bear||0) + '%</span>';
    html += '</div>';
    if (r.reasoning) html += '<div style="color:#a8b2d1;font-size:12px;margin-top:4px">' + esc(r.reasoning) + '</div>';
    html += '</div>';
  });
  if (regime.data_confidence) html += '<div style="color:#8892b0;font-size:11px">Data confidence: ' + esc(regime.data_confidence) + '</div>';
  html += '</div>';
  
  // Market Analysis
  var analysis = report.market_analysis || {};
  if (analysis.summary) {
    html += '<div class="market-card market-card-wide">';
    html += '<div class="section-title" style="margin-top:0">📈 Market Analysis</div>';
    html += '<div style="color:#e0e0e0;line-height:1.6;margin-bottom:8px">' + esc(analysis.summary) + '</div>';
    if (analysis.key_metrics) {
      html += '<table class="hedge-table" style="font-size:12px"><thead><tr><th style="text-align:left">Metric</th><th>Value</th><th style="text-align:left">Interpretation</th></tr></thead><tbody>';
      analysis.key_metrics.forEach(function(m) {
        html += '<tr><td style="text-align:left">' + esc(m.metric) + '</td><td>' + esc(String(m.value)) + '</td><td style="text-align:left;color:#a8b2d1">' + esc(m.interpretation) + '</td></tr>';
      });
      html += '</tbody></table>';
    }
    var sr = analysis.support_resistance;
    if (sr) {
      html += '<div style="margin-top:8px">';
      ['btc', 'eth'].forEach(function(coin) {
        var s = sr[coin];
        if (!s) return;
        html += '<div style="color:#8892b0;font-size:12px;margin-top:4px"><span style="color:#e0e0e0;font-weight:600">' + coin.toUpperCase() + ':</span> S2=' + (s.s2||0).toLocaleString() + ' S1=' + (s.s1||0).toLocaleString() + ' <span style="color:#64ffda">Pivot=' + (s.pivot||0).toLocaleString() + '</span> R1=' + (s.r1||0).toLocaleString() + ' R2=' + (s.r2||0).toLocaleString();
        if (s.status) html += ' — ' + esc(s.status);
        html += '</div>';
      });
      html += '</div>';
    }
    html += '</div>';
  }

  // Portfolio Assessment
  var pa = report.portfolio_assessment || {};
  if (pa.summary) {
    var alignColor = {'aligned':'#51cf66','partially_aligned':'#ffa94d','misaligned':'#ff6b6b'}[pa.alignment] || '#8892b0';
    html += '<div class="market-card market-card-wide">';
    html += '<div class="section-title" style="margin-top:0">💼 Portfolio Assessment <span style="color:' + alignColor + ';font-size:12px;margin-left:8px">' + esc(pa.alignment || '').replace('_', ' ').toUpperCase() + '</span></div>';
    html += '<div style="color:#e0e0e0;line-height:1.6;margin-bottom:8px">' + esc(pa.summary) + '</div>';
    if (pa.strengths && pa.strengths.length) {
      html += '<div style="margin-bottom:4px">';
      pa.strengths.forEach(function(s) { html += '<div style="color:#51cf66;font-size:12px">✅ ' + esc(s) + '</div>'; });
      html += '</div>';
    }
    if (pa.concerns && pa.concerns.length) {
      pa.concerns.forEach(function(c) { html += '<div style="color:#ffa94d;font-size:12px">⚠️ ' + esc(c) + '</div>'; });
    }
    html += '</div>';
  }
  
  // Risk Alerts
  var alerts = report.risk_alerts || [];
  if (alerts.length) {
    html += '<div class="market-card market-card-wide" style="border-color:#ff6b6b33">';
    html += '<div class="section-title" style="margin-top:0;color:#ff6b6b">🚨 Risk Alerts</div>';
    alerts.forEach(function(a) {
      var color = a.severity === 'critical' ? '#ff6b6b' : a.severity === 'warning' ? '#ffa94d' : '#8892b0';
      html += '<div style="color:' + color + ';font-size:13px;margin-bottom:4px">• [' + esc(a.type || '') + '] ' + esc(a.message) + '</div>';
    });
    html += '</div>';
  }
  
  // Recommendations
  var recs = report.recommendations || [];
  if (recs.length) {
    html += '<div class="market-card market-card-wide">';
    html += '<div class="section-title" style="margin-top:0">💡 Recommendations</div>';
    recs.forEach(function(r, i) {
      var prColor = r.priority === 'high' ? '#ff6b6b' : r.priority === 'medium' ? '#ffa94d' : '#8892b0';
      html += '<div style="background:#0a0a1a;border:1px solid #1e3050;border-radius:8px;padding:10px;margin-bottom:6px">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">';
      html += '<span style="color:#e0e0e0;font-weight:600">' + (i+1) + '. ' + esc(r.action) + '</span>';
      html += '<span style="color:' + prColor + ';font-size:11px;text-transform:uppercase">' + esc(r.priority || '') + '</span>';
      html += '</div>';
      html += '<div style="color:#a8b2d1;font-size:12px;line-height:1.5">' + esc(r.rationale) + '</div>';
      if (r.strategy_reference) html += '<div style="color:#64ffda;font-size:11px;margin-top:4px">Strategy: ' + esc(r.strategy_reference) + '</div>';
      html += '</div>';
    });
    html += '</div>';
  }
  
  // Previous Recommendations Review
  var prevRecs = report.previous_recommendations_review || [];
  if (prevRecs.length) {
    html += '<div class="market-card market-card-wide">';
    html += '<div class="section-title" style="margin-top:0">📋 Previous Recommendations Review</div>';
    prevRecs.forEach(function(pr) {
      var statusColor = pr.status === 'implemented' ? '#51cf66' : pr.status === 'partially' ? '#ffa94d' : '#8892b0';
      html += '<div style="font-size:12px;margin-bottom:4px">';
      html += '<span style="color:' + statusColor + '">[' + esc(pr.status || 'unknown') + ']</span> ';
      html += '<span style="color:#e0e0e0">' + esc(pr.recommendation) + '</span>';
      if (pr.comment) html += ' — <span style="color:#a8b2d1">' + esc(pr.comment) + '</span>';
      html += '</div>';
    });
    html += '</div>';
  }
  
  el.innerHTML = html || '<div style="color:#8892b0;padding:20px">Empty report</div>';
}


// ===== DAILY DIGEST =====
async function generateDigest() {
  var status = document.getElementById('ai-status');
  status.textContent = 'Generating digest...'; status.style.color = '#ffa94d';
  try {
    var resp = await fetch('/api/ai/digest', {method: 'POST'});
    var data = await resp.json();
    if (resp.ok) {
      renderDigest(data);
      status.textContent = 'Digest generated'; status.style.color = '#51cf66';
    } else {
      status.textContent = data.error || 'Error'; status.style.color = '#ff6b6b';
    }
  } catch(e) { status.textContent = 'Network error'; status.style.color = '#ff6b6b'; }
}

async function loadLatestDigest() {
  try {
    var resp = await fetch('/api/ai/digest/latest');
    if (resp.ok) {
      var data = await resp.json();
      renderDigest(data.digest_json || data);
    }
  } catch(e) {}
}

function renderDigest(d) {
  var el = document.getElementById('ai-digest-content');
  var chgColor = (d.value_change_24h_pct || 0) >= 0 ? '#51cf66' : '#ff6b6b';
  var chgSign = (d.value_change_24h_pct || 0) >= 0 ? '+' : '';
  
  var html = '<div class="market-card market-card-wide" style="border-color:#64ffda33">';
  html += '<div class="section-title" style="margin-top:0">📋 Daily Digest</div>';
  
  // Value change
  html += '<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:10px">';
  html += '<div><span style="color:#8892b0;font-size:12px">Total Value</span><div class="highlight">' + m('$' + Math.round(d.total_value_usd || 0).toLocaleString()) + '</div></div>';
  html += '<div><span style="color:#8892b0;font-size:12px">24h Change</span><div style="color:' + chgColor + ';font-size:18px;font-weight:700">' + m(chgSign + (d.value_change_24h_pct || 0).toFixed(2) + '%') + ' (' + m(chgSign + '$' + Math.round(Math.abs(d.value_change_24h_usd || 0)).toLocaleString()) + ')</div></div>';
  html += '<div><span style="color:#8892b0;font-size:12px">Total Fees (all LPs)</span><div style="color:#51cf66;font-size:18px;font-weight:700">' + m('$' + (d.total_fees_usd || 0).toLocaleString(undefined,{maximumFractionDigits:2})) + '</div></div>';
  html += '<div><span style="color:#8892b0;font-size:12px">Avg LP APR</span><div style="color:#64ffda;font-size:18px;font-weight:700">' + (d.average_apr || 0).toFixed(1) + '%</div></div>';
  html += '</div>';
  
  // Positions out of range
  var oor = d.positions_out_of_range || [];
  if (oor.length > 0) {
    html += '<div style="margin-bottom:6px"><span style="color:#ff6b6b;font-size:12px;font-weight:600">⚠️ Out of Range:</span> ';
    html += oor.map(function(p) { return '<span style="color:#ffa94d;font-size:12px">' + esc(p) + '</span>'; }).join(', ');
    html += '</div>';
  }
  
  // Opened/Closed
  var opened = d.positions_opened || [];
  var closed = d.positions_closed || [];
  if (opened.length > 0) {
    html += '<div style="margin-bottom:4px"><span style="color:#51cf66;font-size:12px">📈 Opened (24h):</span> ' + opened.map(function(p){return esc(p);}).join(', ') + '</div>';
  }
  if (closed.length > 0) {
    html += '<div style="margin-bottom:4px"><span style="color:#8892b0;font-size:12px">📕 Closed (24h):</span> ' + closed.map(function(p){return esc(p);}).join(', ') + '</div>';
  }
  
  // Hedge health
  var hedges = d.hedge_health || [];
  if (hedges.length > 0) {
    html += '<div style="margin-top:6px"><span style="color:#8892b0;font-size:12px;font-weight:600">Hedge Health:</span></div>';
    hedges.forEach(function(h) {
      var pnlCls = (h.pnl_usd || 0) >= 0 ? 'positive' : 'negative';
      html += '<div style="font-size:12px;color:#a8b2d1">' + esc(h.market || '') + ' ' + esc(h.direction || '') + ' ' + (h.leverage||0) + 'x — PnL: <span class="' + pnlCls + '">$' + (h.pnl_usd||0).toFixed(2) + '</span>, Liq distance: ' + (h.liq_distance_pct||0).toFixed(1) + '%</div>';
    });
  }
  
  html += '</div>';
  el.innerHTML = html;
}
