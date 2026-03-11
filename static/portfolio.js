// ===== PORTFOLIO TAB =====
let portfolioData = null;
let currentWalletFilter = 'all';
let valuesMasked = false;

function toggleMask() {
  valuesMasked = !valuesMasked;
  document.getElementById('mask-toggle').textContent = valuesMasked ? '🙈' : '👁️';
  document.getElementById('mask-toggle').classList.toggle('active', valuesMasked);
  // Apply mask class to both views
  document.getElementById('tab-portfolio').classList.toggle('values-masked', valuesMasked);
}

function setPfView(view) {
  document.getElementById('pf-live-view').style.display = view === 'live' ? '' : 'none';
  document.getElementById('pf-history-view').style.display = view === 'history' ? '' : 'none';
  document.getElementById('pf-view-live').classList.toggle('active', view === 'live');
  document.getElementById('pf-view-history').classList.toggle('active', view === 'history');
  if (view === 'history') initHistory();
}

const fmt = v => '$' + Math.round(v).toLocaleString();
const fmt2 = v => '$' + v.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const fmtNum = (v, d) => v.toLocaleString('en-US', {minimumFractionDigits: d || 2, maximumFractionDigits: d || 2});
const m = v => '<span class="maskable">' + v + '</span>';

async function loadPortfolio(force) {
  if (portfolioData && !force) { renderPortfolio(); return; }
  const btn = document.getElementById('portfolioBtn');
  btn.disabled = true; btn.textContent = 'Loading...';
  try {
    const url = force ? '/api/portfolio?refresh=true' : '/api/portfolio';
    const resp = await fetch(url);
    portfolioData = await resp.json();
    renderPortfolio();
  } catch (e) {
    document.getElementById('pf-total').textContent = 'Error loading data';
    document.getElementById('pf-total').style.color = '#ff6b6b';
  } finally {
    btn.disabled = false; btn.textContent = 'Refresh';
  }
}

function refreshPortfolio(force) { loadPortfolio(force); }

async function takeSnapshot() {
  const btn = document.getElementById('snapshotBtn');
  btn.disabled = true; btn.textContent = 'Taking...';
  try {
    const resp = await fetch('/api/snapshot', { method: 'POST' });
    const data = await resp.json();
    btn.textContent = data.status === 'success' ? '✓ Done' : 'Error';
    setTimeout(() => { btn.textContent = '📸 Snapshot'; }, 2000);
  } catch (e) {
    btn.textContent = 'Error';
    setTimeout(() => { btn.textContent = '📸 Snapshot'; }, 2000);
  } finally {
    btn.disabled = false;
  }
}

function filterWallet(wallet, btnEl) {
  currentWalletFilter = wallet;
  document.querySelectorAll('#pf-wallet-filter .lev-btn').forEach(b => b.classList.remove('active'));
  if (btnEl) btnEl.classList.add('active');
  renderPortfolio();
}

function renderPortfolio() {
  if (!portfolioData) return;
  const d = portfolioData;

  let tokens = d.tokens || [];
  let lps = d.lp_positions || [];

  if (currentWalletFilter !== 'all') {
    tokens = tokens.filter(t => t.wallet === currentWalletFilter);
    lps = lps.filter(lp => lp.wallet === currentWalletFilter);
  }

  const tokensVal = tokens.reduce((s, t) => s + t.value_usd, 0);
  const lpVal = lps.reduce((s, lp) => s + lp.total_value_usd, 0);
  const feesVal = lps.reduce((s, lp) => s + (lp.total_fees_usd || 0), 0);
  const totalVal = tokensVal + lpVal + feesVal;

  document.getElementById('pf-total').innerHTML = m(fmt2(totalVal));
  document.getElementById('pf-wallet-count').textContent = (d.wallet_count || 0) + ' wallet' + (d.wallet_count > 1 ? 's' : '');
  document.getElementById('pf-tokens-value').innerHTML = m(fmt2(tokensVal));
  document.getElementById('pf-tokens-count').textContent = tokens.length + ' tokens';
  document.getElementById('pf-lp-value').innerHTML = m(fmt2(lpVal));
  document.getElementById('pf-lp-count').textContent = lps.length + ' positions';
  document.getElementById('pf-fees-value').innerHTML = m(fmt2(feesVal));

  // Wallet filter buttons
  if (d.wallet_count > 1 && d.wallet_labels) {
    document.getElementById('pf-wallet-filter').style.display = 'flex';
    document.getElementById('pf-wallet-buttons').innerHTML = Object.entries(d.wallet_labels).map(([addr, label]) =>
      '<button class="lev-btn' + (currentWalletFilter === addr ? ' active' : '') + '" onclick="filterWallet(\'' + addr + '\', this)">' + esc(label) + '</button>'
    ).join('');
  }

  // Tokens table
  const tbody = document.getElementById('pf-tokens-table');
  if (tokens.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#8892b0;padding:20px">No tokens found</td></tr>';
  } else {
    tbody.innerHTML = tokens.map(t => {
      const chainCls = {'Ethereum':'eth','Arbitrum':'arb','Base':'base'}[t.chain] || '';
      const val = t.value_usd > 0 ? m(fmt2(t.value_usd)) : '<span style="color:#555">Unknown</span>';
      const price = t.price_usd > 0 ? m(fmt2(t.price_usd)) : '<span style="color:#555">—</span>';
      return '<tr>' +
        '<td style="text-align:left"><span class="chain-badge chain-' + chainCls + '">' + esc(t.chain) + '</span></td>' +
        '<td style="text-align:left;color:#e0e0e0;font-weight:600">' + esc(t.symbol) + '</td>' +
        '<td>' + fmtNum(t.balance, 3) + '</td>' +
        '<td>' + price + '</td>' +
        '<td style="color:#e0e0e0;font-weight:600">' + val + '</td>' +
        '<td style="text-align:left"><span class="wallet-badge">' + esc(t.wallet_label) + '</span></td>' +
        '</tr>';
    }).join('');
  }

  // LP Positions
  const lpDiv = document.getElementById('pf-lp-positions');
  if (lps.length === 0) {
    lpDiv.innerHTML = '<div style="color:#8892b0;padding:20px;text-align:center">No LP positions found</div>';
  } else {
    lpDiv.innerHTML = lps.map(pos => {
      const chainCls = {'ethereum':'eth','arbitrum':'arb','base':'base'}[pos.chain] || '';
      const rangeBadge = pos.in_range
        ? '<span class="status-badge status-in-range">✅ IN RANGE</span>'
        : '<span class="status-badge status-out-range">❌ OUT OF RANGE</span>';
      const pricePct = ((pos.current_price - pos.price_lower) / (pos.price_upper - pos.price_lower)) * 100;
      const ageText = pos.age_days !== null ? pos.age_days + 'd ' + pos.age_hours + 'h' : 'N/A';

      let feesHTML = '';
      if (pos.total_earned_fees_usd > 0.01) {
        feesHTML = '<div class="lp-fees-section">' +
          '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">' +
          '<span style="font-size:16px">💰</span>' +
          '<span style="color:#51cf66;font-weight:700;font-size:14px">Total Fees</span>' +
          '<span style="color:#51cf66;font-weight:700;font-size:18px;margin-left:auto">' + m(fmt2(pos.total_earned_fees_usd)) + '</span></div>';
        if (pos.collected_fees_0 > 0 || pos.collected_fees_1 > 0) {
          feesHTML += '<div style="font-size:12px;color:#a8b2d1">';
          if (pos.collected_fees_0 > 0) feesHTML += '<div>Collected: ' + fmtNum(pos.collected_fees_0, 6) + ' ' + esc(pos.token0_symbol) + ' (' + m(fmt2(pos.collected_fees_0_usd)) + ')</div>';
          if (pos.collected_fees_1 > 0) feesHTML += '<div>Collected: ' + fmtNum(pos.collected_fees_1, 6) + ' ' + esc(pos.token1_symbol) + ' (' + m(fmt2(pos.collected_fees_1_usd)) + ')</div>';
          feesHTML += '</div>';
        }
        if (pos.total_fees_usd > 0.01) {
          feesHTML += '<div style="color:#ffa94d;font-weight:600;font-size:12px;margin-top:4px">+' + m(fmt2(pos.total_fees_usd)) + ' uncollected</div>';
        }
        feesHTML += '</div>';
      }

      let aprHTML = '';
      if (pos.daily_apr !== null && pos.daily_apr > 0) {
        aprHTML = '<div class="lp-apr-grid">' +
          '<div class="lp-apr-card"><div class="lp-apr-label">Daily APR</div>' +
          '<div class="lp-apr-value">' + fmtNum(pos.daily_apr) + '%</div>' +
          '<div style="color:#8892b0;font-size:11px">~' + m(fmt2(pos.daily_earnings)) + '/day</div></div>' +
          '<div class="lp-apr-card lp-apr-monthly"><div class="lp-apr-label" style="color:#a78bfa">Monthly APR</div>' +
          '<div class="lp-apr-value" style="color:#a78bfa">' + fmtNum(pos.monthly_apr) + '%</div>' +
          '<div style="color:#8892b0;font-size:11px">~' + m(fmt2(pos.daily_earnings * 30)) + '/month</div></div>' +
          '</div>';
      } else if (pos.daily_apr === null) {
        aprHTML = '<div class="lp-apr-na"><div style="color:#8892b0;font-size:12px">APR: N/A</div>' +
          '<div style="color:#555;font-size:11px">Position age unavailable</div></div>';
      }

      return '<div class="lp-card">' +
        '<div class="lp-card-header">' +
          '<div>' +
            '<div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">' +
              '<span class="chain-badge chain-' + chainCls + '">' + esc(pos.chain) + '</span>' +
              rangeBadge +
              '<span class="wallet-badge">' + esc(pos.wallet_label || '') + '</span>' +
            '</div>' +
            '<div style="color:#e0e0e0;font-size:18px;font-weight:700">' + esc(pos.pair) + '</div>' +
            '<div style="color:#8892b0;font-size:12px">' + fmtNum(pos.fee_tier) + '% fee tier • Age: ' + ageText + '</div>' +
          '</div>' +
          '<div style="text-align:right">' +
            '<div style="color:#e0e0e0;font-size:22px;font-weight:700">' + m(fmt2(pos.total_value_usd)) + '</div>' +
            '<div style="color:#8892b0;font-size:12px">Position Value</div>' +
          '</div>' +
        '</div>' +
        // Price range bar
        '<div class="lp-range-bar">' +
          '<div style="display:flex;justify-content:space-between;font-size:12px;color:#8892b0;margin-bottom:4px">' +
            '<span>Min: ' + fmtNum(pos.price_lower) + '</span>' +
            '<span style="color:#e0e0e0;font-weight:600">Current: ' + fmtNum(pos.current_price) + '</span>' +
            '<span>Max: ' + fmtNum(pos.price_upper) + '</span>' +
          '</div>' +
          '<div class="range-track"><div class="range-fill"></div><div class="range-needle" style="left:' + Math.max(0, Math.min(100, pricePct)) + '%"></div></div>' +
        '</div>' +
        // Token amounts
        '<div class="lp-tokens-grid">' +
          '<div class="lp-token-card"><div style="color:#8892b0;font-size:12px">' + esc(pos.token0_symbol) + '</div>' +
            '<div style="color:#e0e0e0;font-weight:600">' + fmtNum(pos.amount0, 6) + '</div>' +
            '<div style="color:#8892b0;font-size:12px">' + m(fmt2(pos.value0_usd)) + '</div></div>' +
          '<div class="lp-token-card"><div style="color:#8892b0;font-size:12px">' + esc(pos.token1_symbol) + '</div>' +
            '<div style="color:#e0e0e0;font-weight:600">' + fmtNum(pos.amount1, 6) + '</div>' +
            '<div style="color:#8892b0;font-size:12px">' + m(fmt2(pos.value1_usd)) + '</div></div>' +
        '</div>' +
        feesHTML + aprHTML +
      '</div>';
    }).join('');
  }
}

// ===== SETTINGS TAB =====
function maskKey(key) {
  if (!key || key.length < 8) return '***';
  return key.substring(0, 4) + '*'.repeat(key.length - 8) + key.substring(key.length - 4);
}

async function loadSettings() {
  await Promise.all([loadSettingsWallets(), loadSettingsApiKeys()]);
}

async function loadSettingsWallets() {
  try {
    const resp = await fetch('/api/wallets');
    const data = await resp.json();
    const wallets = data.wallets || [];
    const container = document.getElementById('settings-wallets');
    if (wallets.length === 0) {
      container.innerHTML = '<div style="color:#8892b0;padding:10px">No wallets configured</div>';
    } else {
      container.innerHTML = '<table class="hedge-table"><thead><tr>' +
        '<th style="text-align:left">Label</th><th style="text-align:left">Address</th><th>Actions</th>' +
        '</tr></thead><tbody>' +
        wallets.map(w => {
          const masked = w.address.substring(0,6) + '••••' + w.address.substring(w.address.length-4);
          return '<tr>' +
            '<td style="text-align:left">' + esc(w.label) + '</td>' +
            '<td style="text-align:left;font-size:12px;color:#a8b2d1;font-family:monospace">' + masked + '</td>' +
            '<td style="white-space:nowrap">' +
              '<button class="lev-btn" style="font-size:11px;padding:3px 10px;margin-right:4px" onclick="editWalletLabel(\'' + esc(w.address) + '\',\'' + esc(w.label) + '\')">✏️ Edit</button>' +
              '<button class="lev-btn" style="font-size:11px;padding:3px 10px;color:#ff6b6b;border-color:#ff6b6b" onclick="removeWallet(\'' + esc(w.address) + '\')">Remove</button>' +
            '</td></tr>';
        }).join('') +
        '</tbody></table>';
    }
  } catch (e) {
    document.getElementById('settings-wallets').innerHTML = '<div style="color:#ff6b6b">Error loading wallets</div>';
  }
}

async function loadSettingsApiKeys() {
  try {
    const resp = await fetch('/api/config');
    const data = await resp.json();
    const keys = [
      { id: 'ALCHEMY_API_KEY', label: 'Alchemy API Key', value: data.alchemy_api_key, desc: 'RPC connections to Ethereum, Arbitrum, Base' },
      { id: 'ETHERSCAN_API_KEY', label: 'Etherscan API Key', value: data.etherscan_api_key, desc: 'Position age & collected fees (Ethereum & Arbitrum)' },
      { id: 'BRAVE_API_KEY', label: 'Brave Search API Key', value: data.brave_api_key, desc: 'Token discovery (optional)' },
    ];
    document.getElementById('settings-api-keys').innerHTML = keys.map(k => {
      const masked = k.value ? maskKey(k.value) : '';
      return '<div style="margin-bottom:12px">' +
        '<div style="display:flex;gap:8px;align-items:end">' +
          '<div class="field" style="flex:1;align-items:stretch"><label>' + esc(k.label) + '</label>' +
            '<input id="api-' + k.id + '" value="' + masked + '" placeholder="Enter key..." ' +
            'onfocus="if(this.value.includes(\'*\')){this.value=\'\';this.placeholder=\'Enter new key...\'}" ' +
            'style="width:100%;font-family:monospace;font-size:12px"></div>' +
          '<button class="update-btn" style="padding:7px 16px;font-size:13px" onclick="saveApiKey(\'' + k.id + '\')">Save</button>' +
        '</div>' +
        '<div style="color:#8892b0;font-size:11px;margin-top:2px">' + esc(k.desc) + '</div>' +
      '</div>';
    }).join('');
  } catch(e) {
    document.getElementById('settings-api-keys').innerHTML = '<div style="color:#ff6b6b">Error loading API keys</div>';
  }
}

async function saveApiKey(keyName) {
  const input = document.getElementById('api-' + keyName);
  const value = input.value.trim();
  const msgEl = document.getElementById('settings-api-msg');
  if (value.includes('*')) { showSettingsMsg(msgEl, 'Enter a new key (clear the field first)', true); return; }
  if (!value) { showSettingsMsg(msgEl, 'Please enter a key', true); return; }
  try {
    const resp = await fetch('/api/config', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ key: keyName, value: value })
    });
    if (resp.ok) {
      input.value = maskKey(value);
      showSettingsMsg(msgEl, keyName.replace(/_/g,' ') + ' saved', false);
    } else {
      const data = await resp.json();
      showSettingsMsg(msgEl, data.error || 'Failed to save', true);
    }
  } catch(e) { showSettingsMsg(msgEl, 'Network error', true); }
}

function editWalletLabel(addr, currentLabel) {
  const newLabel = prompt('Enter new label:', currentLabel);
  if (newLabel && newLabel.trim() && newLabel !== currentLabel) {
    fetch('/api/wallets/' + encodeURIComponent(addr), {
      method: 'PUT', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ label: newLabel.trim() })
    }).then(() => { portfolioData = null; loadSettingsWallets(); });
  }
}

function showSettingsMsg(el, msg, isError) {
  el.textContent = msg;
  el.style.color = isError ? '#ff6b6b' : '#51cf66';
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 3000);
}

async function importDB(input) {
  const file = input.files[0];
  if (!file) return;
  if (!confirm('Replace current snapshot database? A backup will be kept.')) { input.value=''; return; }
  const fd = new FormData(); fd.append('file', file);
  const msgEl = document.getElementById('settings-backup-msg');
  try {
    const resp = await fetch('/api/backup/db', { method:'POST', body:fd });
    const data = await resp.json();
    showSettingsMsg(msgEl, resp.ok ? (data.message||'DB imported') : (data.error||'Import failed'), !resp.ok);
  } catch(e) { showSettingsMsg(msgEl, 'Network error', true); }
  input.value = '';
}

async function importConfig(input) {
  const file = input.files[0];
  if (!file) return;
  if (!confirm('This will overwrite API keys and wallet config. A backup will be kept. Continue?')) { input.value=''; return; }
  const fd = new FormData(); fd.append('file', file);
  const msgEl = document.getElementById('settings-backup-msg');
  try {
    const resp = await fetch('/api/backup/config', { method:'POST', body:fd });
    const data = await resp.json();
    showSettingsMsg(msgEl, resp.ok ? (data.message||'Config imported') : (data.error||'Import failed'), !resp.ok);
    if (resp.ok) { portfolioData = null; setTimeout(() => loadSettings(), 1000); }
  } catch(e) { showSettingsMsg(msgEl, 'Network error', true); }
  input.value = '';
}

async function addWallet() {
  const addr = document.getElementById('new-wallet-addr').value.trim();
  const label = document.getElementById('new-wallet-label').value.trim() || addr.slice(0, 10) + '...';
  const errEl = document.getElementById('settings-wallet-err');
  errEl.style.display = 'none';
  if (!addr || !addr.startsWith('0x') || addr.length !== 42) {
    errEl.textContent = 'Invalid address format'; errEl.style.display = 'block'; return;
  }
  try {
    const resp = await fetch('/api/wallets', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({address: addr, label: label})
    });
    const data = await resp.json();
    if (!resp.ok) { errEl.textContent = data.error || 'Error'; errEl.style.display = 'block'; return; }
    document.getElementById('new-wallet-addr').value = '';
    document.getElementById('new-wallet-label').value = '';
    portfolioData = null; // clear cache
    loadSettings();
  } catch (e) {
    errEl.textContent = 'Network error'; errEl.style.display = 'block';
  }
}

async function removeWallet(addr) {
  if (!confirm('Remove wallet ' + addr + '?')) return;
  try {
    await fetch('/api/wallets/' + addr, { method: 'DELETE' });
    portfolioData = null;
    loadSettings();
  } catch (e) {}
}

async function backupDb() {
  window.location.href = '/api/backup/db';
}

async function exportConfig() {
  window.location.href = '/api/backup/config';
}

// ===== PASSWORD CHANGE =====
async function changePassword() {
  const current = document.getElementById('pw-current').value;
  const newPw = document.getElementById('pw-new').value;
  const confirmPw = document.getElementById('pw-confirm').value;
  const msgEl = document.getElementById('settings-pw-msg');
  if (!newPw || newPw.length < 6) { showSettingsMsg(msgEl, 'New password must be at least 6 characters', true); return; }
  if (newPw !== confirmPw) { showSettingsMsg(msgEl, 'Passwords don\'t match', true); return; }
  try {
    const resp = await fetch('/api/change-password', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ current: current, new: newPw })
    });
    const data = await resp.json();
    if (resp.ok) {
      showSettingsMsg(msgEl, 'Password updated', false);
      document.getElementById('pw-current').value = '';
      document.getElementById('pw-new').value = '';
      document.getElementById('pw-confirm').value = '';
    } else {
      showSettingsMsg(msgEl, data.error || 'Failed to update password', true);
    }
  } catch(e) { showSettingsMsg(msgEl, 'Network error', true); }
}
