(function () {
  'use strict';

  let _currentView = 'holdings';
  let _holdingsLoaded = false;
  let _historyLoaded = false;
  let _transactionsLoaded = false;
  let _settingsLoaded = false;

  function fmt$(n, decimals) {
    if (n === null || n === undefined) return '—';
    return '<span class="maskable">$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: decimals ?? 2, maximumFractionDigits: decimals ?? 2 }) + '</span>';
  }
  function fmtPct(n) {
    if (n === null || n === undefined) return '—';
    return '<span class="maskable">' + (n >= 0 ? '+' : '') + Number(n).toFixed(2) + '%</span>';
  }
  function pnlColor(n) {
    if (n === null || n === undefined) return '#8892b0';
    return n >= 0 ? '#64ffda' : '#ff6b6b';
  }
  function pnlSpan(n, fmt) {
    const color = pnlColor(n);
    const text = fmt ? fmt(n) : fmt$(n);
    return `<span style="color:${color}">${text}</span>`;
  }
  function summaryCard(title, value, color) {
    return `<div class="market-card"><div class="section-title" style="margin-top:0">${esc(title)}</div><div class="highlight" style="color:${color || '#ccd6f6'}">${value}</div></div>`;
  }

  window.setSpotView = function (view) {
    if (view === undefined) view = _currentView;
    _currentView = view;
    document.querySelectorAll('#pf-spot-view .spot-panel').forEach(el => el.style.display = 'none');
    const panel = document.getElementById('spot-panel-' + view);
    if (panel) panel.style.display = '';

    document.querySelectorAll('#pf-spot-view .lev-btn[id^="spot-view-"]').forEach(el => el.classList.remove('active'));
    const btn = document.getElementById('spot-view-' + view);
    if (btn) btn.classList.add('active');

    if (view === 'holdings' && !_holdingsLoaded) loadSpotHoldings();
    if (view === 'history' && !_historyLoaded) loadSpotHistory();
    if (view === 'transactions' && !_transactionsLoaded) loadSpotTransactions();
    if (view === 'settings' && !_settingsLoaded) loadSpotSettings();
  };

  window.spotRefreshCurrentView = function () {
    if (_currentView === 'holdings')     { _holdingsLoaded = false;     loadSpotHoldings(); }
    if (_currentView === 'history')      { _historyLoaded = false;      loadSpotHistory(); }
    if (_currentView === 'transactions') { _transactionsLoaded = false; loadSpotTransactions(); }
    if (_currentView === 'settings')     { _settingsLoaded = false;     loadSpotSettings(); }
  };

  function invalidateAll() {
    _holdingsLoaded = false;
    _historyLoaded = false;
    _transactionsLoaded = false;
    _settingsLoaded = false;
  }

  // ── Holdings ──────────────────────────────────────────────────────────────

  function fmtAlloc(n) {
    if (n === null || n === undefined) return '—';
    return '<span class="maskable">' + Number(n).toFixed(2) + '%</span>';
  }

  function loadSpotHoldings() {
    const el = document.getElementById('spot-holdings-content');
    el.innerHTML = '<div style="color:#8892b0;padding:20px;text-align:center">Loading…</div>';
    Promise.all([
      fetch('/api/spot/pnl').then(r => r.json()),
      fetch('/api/spot/stablecoins').then(r => r.json()),
    ])
      .then(([rows, stableData]) => {
        _holdingsLoaded = true;
        const stableTotal = stableData.total_usd || 0;
        if (!rows.length) {
          el.innerHTML = '<div style="color:#8892b0;padding:20px;text-align:center">No open positions. Add buy transactions to get started.</div>';
          return;
        }
        let totalCost = 0, totalValue = 0, totalUnrealized = 0, totalRealized = 0;
        rows.forEach(r => {
          totalCost       += r.total_cost_basis || 0;
          totalValue      += r.current_value_usd || 0;
          totalUnrealized += r.unrealized_pnl_usd || 0;
          totalRealized   += r.realized_pnl_usd || 0;
        });
        const totalWithStable = totalValue + stableTotal;
        const unrColor  = pnlColor(totalUnrealized);
        const realColor = pnlColor(totalRealized);
        let html = `<div class="market-grid" style="margin-bottom:16px">
          ${summaryCard('Total Cost Basis', fmt$(totalCost), '#ccd6f6')}
          ${summaryCard('Current Value', fmt$(totalValue), '#ccd6f6')}
          ${summaryCard('Unrealized P&L', pnlSpan(totalUnrealized), unrColor)}
          ${summaryCard('Realized P&L', pnlSpan(totalRealized), realColor)}
          ${summaryCard('Dry Powder', fmt$(stableTotal), '#8892b0')}
        </div>`;
        html += `<div style="overflow-x:auto"><table class="hedge-table"><thead><tr>
          <th>Symbol</th><th>Units</th><th>Avg Cost</th><th>Cost Basis</th>
          <th>Price</th><th>Value</th><th>Unrealized P&L</th><th>Unr %</th>
          <th>Realized P&L</th><th>% of Portfolio</th><th>% No Stables</th><th>Lots</th><th>Oldest Lot</th>
        </tr></thead><tbody>`;
        rows.forEach(r => {
          const unrColor  = pnlColor(r.unrealized_pnl_usd);
          const realColor = pnlColor(r.realized_pnl_usd);
          const pctOfPortfolio = (r.current_value_usd != null && totalWithStable > 0)
            ? fmtAlloc(r.current_value_usd / totalWithStable * 100) : '—';
          const pctNoStables = (r.current_value_usd != null && totalValue > 0)
            ? fmtAlloc(r.current_value_usd / totalValue * 100) : '—';
          html += `<tr>
            <td><strong>${esc(r.symbol)}</strong></td>
            <td>${r.units != null ? '<span class="maskable">' + Number(r.units).toLocaleString('en-US', {maximumFractionDigits: 8}) + '</span>' : '—'}</td>
            <td>${fmt$(r.avg_cost_usd, 4)}</td>
            <td>${fmt$(r.total_cost_basis)}</td>
            <td>${r.current_price_usd != null ? fmt$(r.current_price_usd, 4) : '—'}</td>
            <td>${r.current_value_usd != null ? fmt$(r.current_value_usd) : '—'}</td>
            <td style="color:${unrColor}">${r.unrealized_pnl_usd != null ? fmt$(r.unrealized_pnl_usd) : '—'}</td>
            <td style="color:${unrColor}">${r.unrealized_pct != null ? fmtPct(r.unrealized_pct) : '—'}</td>
            <td style="color:${realColor}">${fmt$(r.realized_pnl_usd)}</td>
            <td>${pctOfPortfolio}</td>
            <td>${pctNoStables}</td>
            <td>${esc(String(r.lot_count))}</td>
            <td>${esc(r.oldest_lot_date || '—')}</td>
          </tr>`;
        });
        html += '</tbody></table></div>';
        el.innerHTML = html;
        lucide.createIcons();
      })
      .catch(e => {
        el.innerHTML = `<div style="color:#ff6b6b;padding:20px">Error: ${esc(String(e))}</div>`;
      });
  }

  // ── History ───────────────────────────────────────────────────────────────

  function loadSpotHistory() {
    const el = document.getElementById('spot-history-content');
    el.innerHTML = '<div style="color:#8892b0;padding:20px;text-align:center">Loading…</div>';
    fetch('/api/spot/history')
      .then(r => r.json())
      .then(rows => {
        _historyLoaded = true;
        if (!rows.length) {
          el.innerHTML = '<div style="color:#8892b0;padding:20px;text-align:center">No closed positions yet. Sell all units of a symbol to see it here.</div>';
          return;
        }
        let totalInvested = 0, totalProceeds = 0, totalRealized = 0;
        rows.forEach(r => {
          totalInvested  += r.total_invested || 0;
          totalProceeds  += r.total_proceeds || 0;
          totalRealized  += r.realized_pnl   || 0;
        });
        const overallRoi = totalInvested > 0 ? (totalProceeds - totalInvested) / totalInvested * 100 : null;
        const realColor = pnlColor(totalRealized);
        const roiColor  = pnlColor(overallRoi);
        let html = `<div class="market-grid" style="margin-bottom:16px">
          ${summaryCard('Total Invested', fmt$(totalInvested), '#ccd6f6')}
          ${summaryCard('Total Proceeds', fmt$(totalProceeds), '#ccd6f6')}
          ${summaryCard('Realized P&L', pnlSpan(totalRealized), realColor)}
          ${summaryCard('Overall ROI', `<span style="color:${roiColor}">${fmtPct(overallRoi)}</span>`, roiColor)}
        </div>`;
        html += `<div style="overflow-x:auto"><table class="hedge-table"><thead><tr>
          <th>Symbol</th><th>Total Invested</th><th>Total Proceeds</th>
          <th>Realized P&L</th><th>ROI %</th><th>Last Sell</th>
        </tr></thead><tbody>`;
        rows.forEach(r => {
          const c = pnlColor(r.realized_pnl);
          html += `<tr>
            <td><strong>${esc(r.symbol)}</strong></td>
            <td>${fmt$(r.total_invested)}</td>
            <td>${fmt$(r.total_proceeds)}</td>
            <td style="color:${c}">${fmt$(r.realized_pnl)}</td>
            <td style="color:${pnlColor(r.roi_pct)}">${fmtPct(r.roi_pct)}</td>
            <td>${esc(r.last_sell_date || '—')}</td>
          </tr>`;
        });
        html += '</tbody></table></div>';
        el.innerHTML = html;
        lucide.createIcons();
      })
      .catch(e => {
        el.innerHTML = `<div style="color:#ff6b6b;padding:20px">Error: ${esc(String(e))}</div>`;
      });
  }

  // ── Transactions ──────────────────────────────────────────────────────────

  function loadSpotTransactions() {
    const el = document.getElementById('spot-transactions-content');
    el.innerHTML = '<div style="color:#8892b0;padding:20px;text-align:center">Loading…</div>';
    fetch('/api/spot/transactions')
      .then(r => r.json())
      .then(rows => {
        _transactionsLoaded = true;
        if (!rows.length) {
          el.innerHTML = '<div style="color:#8892b0;padding:20px;text-align:center">No transactions yet. Add one above or import a CSV.</div>';
          return;
        }
        let html = `<div style="overflow-x:auto"><table class="hedge-table spot-tx-table"><thead><tr>
          <th>Date</th><th>Symbol</th><th>Side</th><th>Units</th>
          <th>Avg Cost/unit</th><th>Tx Amt (USD)</th><th>Platform</th><th>Notes</th><th>Actions</th>
        </tr></thead><tbody>`;
        rows.forEach(r => {
          const sideColor = r.side === 'buy' ? '#64ffda' : '#ff6b6b';
          const units = Number(r.units).toLocaleString('en-US', {maximumFractionDigits: 8});
          html += `<tr>
            <td>${esc(r.trade_date)}</td>
            <td><strong>${esc(r.symbol)}</strong></td>
            <td style="color:${sideColor};font-weight:600">${esc(r.side.toUpperCase())}</td>
            <td>${units}</td>
            <td>${fmt$(r.units > 0 ? r.price_usd / r.units : 0, 4)}</td>
            <td>${fmt$(r.price_usd)}</td>
            <td>${esc(r.platform || '')}</td>
            <td style="white-space:normal;word-wrap:break-word;max-width:300px">${esc(r.notes || '')}</td>
            <td style="white-space:nowrap">
              <button class="lev-btn" style="font-size:11px;padding:3px 8px" onclick="spotEditRow(${r.id},'${esc(r.trade_date)}','${esc(r.symbol)}','${esc(r.side)}',${r.units},${r.price_usd},'${esc(r.platform||'')}','${esc(r.notes||'')}')">Edit</button>
              <button class="lev-btn" style="font-size:11px;padding:3px 8px;color:#ff6b6b;margin-left:4px" onclick="spotDeleteRow(${r.id})">Del</button>
            </td>
          </tr>`;
        });
        html += '</tbody></table></div>';
        el.innerHTML = html;
        lucide.createIcons();
      })
      .catch(e => {
        el.innerHTML = `<div style="color:#ff6b6b;padding:20px">Error: ${esc(String(e))}</div>`;
      });
  }

  // ── Form helpers ──────────────────────────────────────────────────────────

  window.spotToggleAddForm = function () {
    const form = document.getElementById('spot-tx-form');
    if (form.style.display === 'none' || !form.style.display) {
      document.getElementById('spot-tx-edit-id').value = '';
      document.getElementById('spot-f-date').value = new Date().toISOString().slice(0, 10);
      document.getElementById('spot-f-symbol').value = '';
      document.getElementById('spot-f-side').value = 'buy';
      document.getElementById('spot-f-units').value = '';
      document.getElementById('spot-f-price').value = '';
      document.getElementById('spot-f-platform').value = '';
      document.getElementById('spot-f-notes').value = '';
      document.getElementById('spot-form-err').style.display = 'none';
      form.style.display = '';
    } else {
      form.style.display = 'none';
    }
  };

  window.spotCancelForm = function () {
    document.getElementById('spot-tx-form').style.display = 'none';
  };

  window.spotEditRow = function (id, date, symbol, side, units, price, platform, notes) {
    document.getElementById('spot-tx-edit-id').value = id;
    document.getElementById('spot-f-date').value = date;
    document.getElementById('spot-f-symbol').value = symbol;
    document.getElementById('spot-f-side').value = side;
    document.getElementById('spot-f-units').value = units;
    document.getElementById('spot-f-price').value = price;
    document.getElementById('spot-f-platform').value = platform || '';
    document.getElementById('spot-f-notes').value = notes || '';
    document.getElementById('spot-form-err').style.display = 'none';
    document.getElementById('spot-tx-form').style.display = '';
    document.getElementById('spot-tx-form').scrollIntoView({behavior: 'smooth', block: 'nearest'});
  };

  window.spotSaveTransaction = function () {
    const editId = document.getElementById('spot-tx-edit-id').value;
    const errEl  = document.getElementById('spot-form-err');
    errEl.style.display = 'none';

    const payload = {
      trade_date:         document.getElementById('spot-f-date').value.trim(),
      symbol:             document.getElementById('spot-f-symbol').value.trim().toUpperCase(),
      side:               document.getElementById('spot-f-side').value,
      units:              document.getElementById('spot-f-units').value.trim(),
      price_usd:          document.getElementById('spot-f-price').value.trim(),
      platform:           document.getElementById('spot-f-platform').value.trim(),
      notes:              document.getElementById('spot-f-notes').value.trim(),
    };

    if (!payload.trade_date || !payload.symbol || !payload.units || !payload.price_usd) {
      errEl.textContent = 'Date, Symbol, Units and Price are required.';
      errEl.style.display = '';
      return;
    }

    const url    = editId ? `/api/spot/transactions/${editId}` : '/api/spot/transactions';
    const method = editId ? 'PUT' : 'POST';

    fetch(url, { method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          errEl.textContent = data.error;
          errEl.style.display = '';
          return;
        }
        document.getElementById('spot-tx-form').style.display = 'none';
        invalidateAll();
        loadSpotTransactions();
      })
      .catch(e => {
        errEl.textContent = 'Error: ' + e;
        errEl.style.display = '';
      });
  };

  window.spotDeleteRow = function (id) {
    if (!confirm('Delete this transaction?')) return;
    fetch(`/api/spot/transactions/${id}`, { method: 'DELETE' })
      .then(r => r.json())
      .then(() => {
        invalidateAll();
        loadSpotTransactions();
      });
  };

  // ── Settings ──────────────────────────────────────────────────────────────

  function loadSpotSettings() {
    const el = document.getElementById('spot-settings-content');
    el.innerHTML = '<div style="color:#8892b0;padding:20px;text-align:center">Loading…</div>';
    Promise.all([
      fetch('/api/spot/transactions').then(r => r.json()),
      fetch('/api/spot/token-config').then(r => r.json()),
    ]).then(([txRows, cfgRows]) => {
      _settingsLoaded = true;
      const symbols = [...new Set(txRows.map(r => r.symbol.toUpperCase()))].sort();
      if (!symbols.length) {
        el.innerHTML = '<div style="color:#8892b0;padding:20px;text-align:center">No symbols yet. Add transactions first.</div>';
        return;
      }
      const cfgMap = {};
      cfgRows.forEach(r => { cfgMap[r.symbol.toUpperCase()] = r; });

      const inp = (id, val, placeholder, width, mono) =>
        `<input id="${id}" value="${esc(val || '')}" placeholder="${esc(placeholder)}" style="width:${width};background:#0d1b2e;color:#ccd6f6;border:1px solid #1e3050;border-radius:4px;padding:4px 6px;font-size:12px${mono ? ';font-family:monospace' : ''}">`;

      let html = `<div style="overflow-x:auto"><table class="hedge-table"><thead><tr>
        <th>Symbol</th><th>CoinGecko ID</th><th>Contract Address</th><th>Chain</th><th>Notes</th><th>Actions</th>
      </tr></thead><tbody>`;

      symbols.forEach(sym => {
        const cfg = cfgMap[sym] || {};
        const sid = sym.replace(/[^A-Z0-9]/g, '_');
        html += `<tr>
          <td><strong>${esc(sym)}</strong></td>
          <td>${inp('spot-cfg-cgid-' + sid, cfg.cg_id, 'e.g. bitcoin', '130px', false)}</td>
          <td>${inp('spot-cfg-contract-' + sid, cfg.contract_address, '0x…', '200px', true)}</td>
          <td>${inp('spot-cfg-chain-' + sid, cfg.chain, 'base', '80px', false)}</td>
          <td>${inp('spot-cfg-notes-' + sid, cfg.notes, '', '110px', false)}</td>
          <td style="white-space:nowrap">
            <button class="update-btn" style="font-size:11px;padding:3px 10px" onclick="spotSaveTokenConfig('${sym}')">Save</button>
            <button class="lev-btn" style="font-size:11px;padding:3px 8px;margin-left:4px" onclick="spotTestPrice('${sym}')">Test Price</button>
            <span id="spot-cfg-price-${sid}" style="font-size:11px;margin-left:6px;color:#8892b0"></span>
          </td>
        </tr>`;
      });
      html += '</tbody></table></div>';
      el.innerHTML = html;
      lucide.createIcons();
    }).catch(e => {
      el.innerHTML = `<div style="color:#ff6b6b;padding:20px">Error: ${esc(String(e))}</div>`;
    });
  }

  window.spotSaveTokenConfig = function (sym) {
    const sid = sym.replace(/[^A-Z0-9]/g, '_');
    const priceEl = document.getElementById('spot-cfg-price-' + sid);
    const payload = {
      symbol:           sym,
      cg_id:            document.getElementById('spot-cfg-cgid-' + sid).value.trim(),
      contract_address: document.getElementById('spot-cfg-contract-' + sid).value.trim(),
      chain:            document.getElementById('spot-cfg-chain-' + sid).value.trim(),
      notes:            document.getElementById('spot-cfg-notes-' + sid).value.trim(),
    };
    fetch('/api/spot/token-config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          priceEl.textContent = 'Error: ' + data.error;
          priceEl.style.color = '#ff6b6b';
        } else {
          priceEl.textContent = 'Saved ✓';
          priceEl.style.color = '#64ffda';
          _holdingsLoaded = false;
          _historyLoaded = false;
        }
      })
      .catch(e => {
        priceEl.textContent = 'Error: ' + e;
        priceEl.style.color = '#ff6b6b';
      });
  };

  window.spotTestPrice = function (sym) {
    const sid = sym.replace(/[^A-Z0-9]/g, '_');
    const priceEl = document.getElementById('spot-cfg-price-' + sid);
    priceEl.textContent = 'Testing…';
    priceEl.style.color = '#8892b0';
    fetch('/api/spot/price-test/' + encodeURIComponent(sym))
      .then(r => r.json())
      .then(data => {
        if (data.price != null) {
          const srcLabel = data.source ? ` (${data.source})` : '';
          priceEl.textContent = '$' + Number(data.price).toLocaleString('en-US', {minimumFractionDigits: 4, maximumFractionDigits: 8}) + srcLabel;
          priceEl.style.color = '#64ffda';
        } else {
          priceEl.textContent = 'No price found';
          priceEl.style.color = '#ff6b6b';
        }
      })
      .catch(e => {
        priceEl.textContent = 'Error: ' + e;
        priceEl.style.color = '#ff6b6b';
      });
  };

  window.spotImportCsv = function (input) {
    if (!input.files.length) return;
    const statusEl = document.getElementById('spot-import-status');
    statusEl.textContent = 'Importing…';
    statusEl.style.display = '';
    statusEl.style.color = '#64ffda';
    const fd = new FormData();
    fd.append('file', input.files[0]);
    input.value = '';
    fetch('/api/spot/import-csv', { method: 'POST', body: fd })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          statusEl.textContent = 'Error: ' + data.error;
          statusEl.style.color = '#ff6b6b';
          return;
        }
        let msg = `Imported ${data.imported} row${data.imported !== 1 ? 's' : ''}`;
        if (data.errors && data.errors.length) {
          msg += ` (${data.errors.length} skipped: ${data.errors.slice(0, 2).join('; ')}${data.errors.length > 2 ? '…' : ''})`;
          statusEl.style.color = '#ffa94d';
        }
        statusEl.textContent = msg;
        invalidateAll();
        loadSpotTransactions();
      })
      .catch(e => {
        statusEl.textContent = 'Error: ' + e;
        statusEl.style.color = '#ff6b6b';
      });
  };

})();
