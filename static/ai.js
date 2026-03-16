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
  var regime = report.market_regime || {};
  html += '<div class="market-card market-card-wide">';
  html += '<div class="section-title" style="margin-top:0">'+li('bar-chart-3',16)+' Market Regime Assessment</div>';
  ['short_term_7d', 'mid_term_30d'].forEach(function(period) {
    var r = regime[period];
    if (!r) return;
    var label = period === 'short_term_7d' ? 'Short-term (7d)' : 'Mid-term (30d)';
    html += '<div style="margin-bottom:12px"><div style="color:#e0e0e0;font-weight:600;margin-bottom:4px">' + label + '</div>';
    html += '<div style="display:flex;gap:4px;margin-bottom:4px">';
    html += '<div style="flex:' + (r.bull||0) + ';background:#51cf66;height:8px;border-radius:4px"></div>';
    html += '<div style="flex:' + (r.sideways||0) + ';background:#ffa94d;height:8px;border-radius:4px"></div>';
    html += '<div style="flex:' + (r.bear||0) + ';background:#ff6b6b;height:8px;border-radius:4px"></div></div>';
    html += '<div style="display:flex;justify-content:space-between;font-size:11px"><span class="positive">Bull ' + (r.bull||0) + '%</span><span style="color:#ffa94d">Sideways ' + (r.sideways||0) + '%</span><span class="negative">Bear ' + (r.bear||0) + '%</span></div>';
    if (r.reasoning) html += '<div style="color:#a8b2d1;font-size:12px;margin-top:4px">' + esc(r.reasoning) + '</div>';
    html += '</div>';
  });
  if (regime.data_confidence) html += '<div style="color:#8892b0;font-size:11px">Data confidence: ' + esc(regime.data_confidence) + '</div>';
  html += '</div>';
  var analysis = report.market_analysis || {};
  if (analysis.summary) {
    html += '<div class="market-card market-card-wide"><div class="section-title" style="margin-top:0">'+li('trending-up',16)+' Market Analysis</div>';
    html += '<div style="color:#e0e0e0;line-height:1.6;margin-bottom:8px">' + esc(analysis.summary) + '</div>';
    if (analysis.key_metrics) {
      html += '<table class="hedge-table" style="font-size:12px"><thead><tr><th style="text-align:left">Metric</th><th>Value</th><th style="text-align:left">Interpretation</th></tr></thead><tbody>';
      analysis.key_metrics.forEach(function(mk) { html += '<tr><td style="text-align:left">' + esc(mk.metric) + '</td><td>' + esc(String(mk.value)) + '</td><td style="text-align:left;color:#a8b2d1">' + esc(mk.interpretation) + '</td></tr>'; });
      html += '</tbody></table>';
    }
    var sr = analysis.support_resistance;
    if (sr) {
      html += '<div style="margin-top:8px">';
      ['btc','eth'].forEach(function(coin) { var s = sr[coin]; if (!s) return; html += '<div style="color:#8892b0;font-size:12px;margin-top:4px"><span style="color:#e0e0e0;font-weight:600">' + coin.toUpperCase() + ':</span> S2=' + (s.s2||0).toLocaleString() + ' S1=' + (s.s1||0).toLocaleString() + ' <span style="color:#64ffda">Pivot=' + (s.pivot||0).toLocaleString() + '</span> R1=' + (s.r1||0).toLocaleString() + ' R2=' + (s.r2||0).toLocaleString() + (s.status ? ' — ' + esc(s.status) : '') + '</div>'; });
      html += '</div>';
    }
    html += '</div>';
  }
  var pa = report.portfolio_assessment || {};
  if (pa.summary) {
    var alignColor = {'aligned':'#51cf66','partially_aligned':'#ffa94d','misaligned':'#ff6b6b'}[pa.alignment] || '#8892b0';
    html += '<div class="market-card market-card-wide"><div class="section-title" style="margin-top:0">'+li('briefcase',16)+' Portfolio Assessment <span style="color:' + alignColor + ';font-size:12px;margin-left:8px">' + esc(pa.alignment || '').replace('_', ' ').toUpperCase() + '</span></div>';
    html += '<div style="color:#e0e0e0;line-height:1.6;margin-bottom:8px">' + esc(pa.summary) + '</div>';
    if (pa.strengths && pa.strengths.length) { html += '<div style="margin-bottom:4px">'; pa.strengths.forEach(function(s) { html += '<div style="color:#51cf66;font-size:12px">'+li('check-circle',12,'#51cf66')+' ' + esc(s) + '</div>'; }); html += '</div>'; }
    if (pa.concerns && pa.concerns.length) { pa.concerns.forEach(function(c) { html += '<div style="color:#ffa94d;font-size:12px">'+li('alert-triangle',12,'#ffa94d')+' ' + esc(c) + '</div>'; }); }
    html += '</div>';
  }
  var alerts = report.risk_alerts || [];
  if (alerts.length) { html += '<div class="market-card market-card-wide" style="border-color:#ff6b6b33"><div class="section-title" style="margin-top:0;color:#ff6b6b">Risk Alerts</div>'; alerts.forEach(function(a) { var color = a.severity === 'critical' ? '#ff6b6b' : a.severity === 'warning' ? '#ffa94d' : '#8892b0'; html += '<div style="color:' + color + ';font-size:13px;margin-bottom:4px">[' + esc(a.type || '') + '] ' + esc(a.message) + '</div>'; }); html += '</div>'; }
  var recs = report.recommendations || [];
  if (recs.length) { html += '<div class="market-card market-card-wide"><div class="section-title" style="margin-top:0">Recommendations</div>'; recs.forEach(function(r, i) { var prColor = r.priority === 'high' ? '#ff6b6b' : r.priority === 'medium' ? '#ffa94d' : '#8892b0'; html += '<div style="background:#0a0a1a;border:1px solid #1e3050;border-radius:8px;padding:10px;margin-bottom:6px"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px"><span style="color:#e0e0e0;font-weight:600">' + (i+1) + '. ' + esc(r.action) + '</span><span style="color:' + prColor + ';font-size:11px;text-transform:uppercase">' + esc(r.priority || '') + '</span></div><div style="color:#a8b2d1;font-size:12px;line-height:1.5">' + esc(r.rationale) + '</div>' + (r.strategy_reference ? '<div style="color:#64ffda;font-size:11px;margin-top:4px">Strategy: ' + esc(r.strategy_reference) + '</div>' : '') + '</div>'; }); html += '</div>'; }
  var prevRecs = report.previous_recommendations_review || [];
  if (prevRecs.length) { html += '<div class="market-card market-card-wide"><div class="section-title" style="margin-top:0">'+li('clipboard-list',16)+' Previous Recommendations Review</div>'; prevRecs.forEach(function(pr) { var statusColor = pr.status === 'implemented' ? '#51cf66' : pr.status === 'partially' ? '#ffa94d' : '#8892b0'; html += '<div style="font-size:12px;margin-bottom:4px"><span style="color:' + statusColor + '">[' + esc(pr.status || 'unknown') + ']</span> <span style="color:#e0e0e0">' + esc(pr.recommendation) + '</span>' + (pr.comment ? ' — <span style="color:#a8b2d1">' + esc(pr.comment) + '</span>' : '') + '</div>'; }); html += '</div>'; }
  el.innerHTML = html || '<div style="color:#8892b0;padding:20px">Empty report</div>';
}


// ===== DAILY DIGEST =====
async function generateDigest() {
  var status = document.getElementById('ai-status');
  status.textContent = 'Generating digest...'; status.style.color = '#ffa94d';
  try {
    var resp = await fetch('/api/ai/digest', {method: 'POST'});
    var data = await resp.json();
    if (resp.ok) { renderDigest(data); status.textContent = 'Digest generated'; status.style.color = '#51cf66'; }
    else { status.textContent = data.error || 'Error'; status.style.color = '#ff6b6b'; }
  } catch(e) { status.textContent = 'Network error'; status.style.color = '#ff6b6b'; }
}

async function loadLatestDigest() {
  try {
    var resp = await fetch('/api/ai/digest/latest');
    if (resp.ok) { var data = await resp.json(); renderDigest(data.digest_json || data); }
  } catch(e) {}
}

function renderDigest(d) {
  var el = document.getElementById('ai-digest-content');
  var chgColor = (d.value_change_24h_pct || 0) >= 0 ? '#51cf66' : '#ff6b6b';
  var chgSign = (d.value_change_24h_pct || 0) >= 0 ? '+' : '';
  var fd = function(v) { return '$' + Math.round(v || 0).toLocaleString(); };

  var html = '<div class="market-card market-card-wide" style="border-color:#64ffda33">';
  html += '<div class="section-title" style="margin-top:0">' + li('clipboard-list', 16) + ' Daily Digest</div>';
  html += '<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:10px">';
  html += '<div><span style="color:#8892b0;font-size:12px">Total Value</span><div class="highlight">' + m(fd(d.total_value_usd)) + '</div></div>';
  html += '<div><span style="color:#8892b0;font-size:12px">24h Change</span><div style="color:' + chgColor + ';font-size:18px;font-weight:700">' + m(chgSign + (d.value_change_24h_pct || 0).toFixed(2) + '%') + ' (' + m(chgSign + fd(Math.abs(d.value_change_24h_usd || 0))) + ')</div></div>';
  html += '<div><span style="color:#8892b0;font-size:12px">Fees (24h)</span><div style="color:#51cf66;font-size:18px;font-weight:700">' + m('$' + (d.fees_24h_usd || 0).toFixed(2)) + '</div></div>';
  html += '<div><span style="color:#8892b0;font-size:12px">Avg LP APR</span><div style="color:#64ffda;font-size:18px;font-weight:700">' + (d.average_apr || 0).toFixed(1) + '%</div></div>';
  html += '</div>';

  var counts = [];
  if (d.token_count) counts.push(d.token_count + ' tokens');
  if (d.lp_count) counts.push(d.lp_count + ' LPs');
  if (d.lending_count) counts.push(d.lending_count + ' lending');
  if (d.hedge_count) counts.push(d.hedge_count + ' hedges');
  if (counts.length > 0) html += '<div style="color:#8892b0;font-size:12px;margin-bottom:8px">' + counts.join(' \u00b7 ') + '</div>';

  var lps = d.lp_summary || [];
  if (lps.length > 0) {
    html += '<div style="margin-bottom:8px">';
    lps.forEach(function(lp) {
      var st = lp.in_range ? '<span style="color:#51cf66">IN</span>' : '<span style="color:#ff6b6b">OUT</span>';
      var apr = lp.daily_apr != null ? ' \u00b7 ' + (lp.daily_apr * 365).toFixed(0) + '% APR' : '';
      html += '<div style="font-size:12px;color:#a8b2d1;display:flex;align-items:center;gap:6px;margin-bottom:2px">';
      html += '<span style="min-width:120px">' + esc(lp.pair) + '</span><span style="min-width:30px;text-align:center">' + st + '</span>';
      html += '<div style="flex:1;max-width:120px;height:4px;background:#333;border-radius:2px;position:relative"><div style="position:absolute;left:' + lp.range_pct + '%;top:-2px;width:3px;height:8px;background:#fff;border-radius:1px;transform:translateX(-50%)"></div></div>';
      html += '<span style="color:#8892b0;font-size:11px">' + m(fd(lp.value_usd)) + apr + '</span></div>';
    });
    html += '</div>';
  }

  var lending = d.lending_health || [];
  if (lending.length > 0) {
    html += '<div style="margin-bottom:8px">';
    lending.forEach(function(la) {
      var hf = la.health_factor || 0;
      var hfColor = hf > 3 ? '#51cf66' : hf > 2 ? '#64ffda' : hf > 1.5 ? '#ffa94d' : '#ff6b6b';
      html += '<div style="font-size:12px;color:#a8b2d1">' + esc(la.protocol || '') + ' (' + esc(la.chain || '') + ') \u2014 Collateral: ' + m(fd(la.collateral_usd)) + ' \u00b7 Debt: <span style="color:#ff6b6b">' + m(fd(la.debt_usd)) + '</span> \u00b7 HF: <span style="color:' + hfColor + ';font-weight:600">' + hf.toFixed(2) + '</span> \u00b7 LTV: ' + (la.ltv || 0).toFixed(1) + '%</div>';
    });
    html += '</div>';
  }

  var oor = d.positions_out_of_range || [];
  if (oor.length > 0) {
    html += '<div style="margin-bottom:6px"><span style="color:#ff6b6b;font-size:12px;font-weight:600">' + li('alert-triangle', 12, '#ffa94d') + ' Out of Range:</span> ';
    html += oor.map(function(p) { return '<span style="color:#ffa94d;font-size:12px">' + esc(p) + '</span>'; }).join(', ') + '</div>';
  }

  var opened = d.positions_opened || [];
  var closed = d.positions_closed || [];
  if (opened.length > 0) html += '<div style="margin-bottom:4px"><span style="color:#51cf66;font-size:12px">' + li('plus-circle', 12, '#51cf66') + ' Opened (24h):</span> ' + opened.map(function(p) { return esc(p); }).join(', ') + '</div>';
  if (closed.length > 0) html += '<div style="margin-bottom:4px"><span style="color:#8892b0;font-size:12px">' + li('archive', 12, '#8892b0') + ' Closed (24h):</span> ' + closed.map(function(p) { return esc(p); }).join(', ') + '</div>';

  var hedges = d.hedge_health || [];
  if (hedges.length > 0) {
    html += '<div style="margin-top:6px"><span style="color:#8892b0;font-size:12px;font-weight:600">Hedge Health:</span></div>';
    hedges.forEach(function(h) {
      if (h.price_unavailable) {
        html += '<div style="font-size:12px;color:#a8b2d1">' + esc(h.market || '') + ' ' + esc(h.direction || '') + ' ' + Math.round(h.leverage || 0) + 'x \u2014 <span style="color:#ffa94d">price unavailable</span></div>';
      } else {
        var pnlCls = (h.pnl_usd || 0) >= 0 ? 'positive' : 'negative';
        html += '<div style="font-size:12px;color:#a8b2d1">' + esc(h.market || '') + ' ' + esc(h.direction || '') + ' ' + Math.round(h.leverage || 0) + 'x \u2014 PnL: <span class="' + pnlCls + '">' + fd(Math.abs(h.pnl_usd || 0)) + '</span>, Liq: ' + (h.liq_distance_pct || 0).toFixed(1) + '% away</div>';
      }
    });
  }

  html += '</div>';
  el.innerHTML = html;
}
