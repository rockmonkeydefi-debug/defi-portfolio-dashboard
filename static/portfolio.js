// ===== PORTFOLIO TAB =====
let portfolioData = null;
let currentWalletFilter = 'all';
let currentChainFilter = 'all';
let valuesMasked = false;

// Chain logo images
const chainIconUrls = {
  'Ethereum': 'https://assets.coingecko.com/coins/images/279/small/ethereum.png',
  'Arbitrum': 'https://assets.coingecko.com/coins/images/16547/small/arb.jpg',
  'Base': 'https://assets.coingecko.com/asset_platforms/images/131/small/base.jpeg',
  'Bitcoin': 'https://assets.coingecko.com/coins/images/1/small/bitcoin.png',
};

// Token logo URL from CoinGecko
function tokenIconUrl(symbol, chain) {
  // Well-known token mappings to CoinGecko asset IDs
  const cgMap = {
    'BTC': 'https://assets.coingecko.com/coins/images/1/small/bitcoin.png',
    'ETH': 'https://assets.coingecko.com/coins/images/279/small/ethereum.png',
    'WETH': 'https://assets.coingecko.com/coins/images/2518/small/weth.png',
    'USDC': 'https://assets.coingecko.com/coins/images/6319/small/usdc.png',
    'USDT': 'https://assets.coingecko.com/coins/images/325/small/Tether.png',
    'DAI': 'https://assets.coingecko.com/coins/images/9956/small/Badge_Dai.png',
    'WBTC': 'https://assets.coingecko.com/coins/images/7598/small/wrapped_bitcoin_wbtc.png',
    'ARB': 'https://assets.coingecko.com/coins/images/16547/small/arb.jpg',
    'LINK': 'https://assets.coingecko.com/coins/images/877/small/chainlink-new-logo.png',
    'UNI': 'https://assets.coingecko.com/coins/images/12504/small/uni.jpg',
    'AAVE': 'https://assets.coingecko.com/coins/images/12645/small/aave-token-round.png',
    'cbBTC': 'https://assets.coingecko.com/coins/images/40143/small/cbbtc.webp',
  };
  return cgMap[symbol] || null;
}

function chainIcon(chainName) {
  const url = chainIconUrls[chainName];
  if (url) {
    return '<img class="chain-icon" src="' + url + '" alt="' + esc(chainName) + '" title="' + esc(chainName) + '" onerror="this.outerHTML=\'<span class=\\\'chain-badge\\\'>' + esc(chainName) + '</span>\'">';
  }
  return '<span class="chain-badge">' + esc(chainName) + '</span>';
}

function tokenIcon(symbol, chain) {
  const url = tokenIconUrl(symbol, chain);
  if (url) {
    return '<img class="token-icon" src="' + url + '" alt="' + esc(symbol) + '" onerror="this.style.display=\'none\'">';
  }
  return '';
}

function toggleMask() {
  valuesMasked = !valuesMasked;
  document.getElementById('mask-toggle').textContent = valuesMasked ? '🙈' : '👁️';
  document.getElementById('mask-toggle').classList.toggle('active', valuesMasked);
  document.getElementById('tab-portfolio').classList.toggle('values-masked', valuesMasked);
  // Re-render history charts if they exist (to update axis labels and tooltips)
  if (histInitialized) {
    [histPortfolioChart, histFeesChart, histTokenChart, histLPValueChart, histLPFeesChart].forEach(function(c) {
      if (c) c.update();
    });
  }
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

function filterChain(chain, btnEl) {
  currentChainFilter = chain;
  // Update active state on all chain buttons (the "All" button + dynamic ones)
  var container = document.getElementById('pf-wallet-filter');
  var chainBtns = container.querySelectorAll('#pf-chain-buttons .lev-btn');
  chainBtns.forEach(b => b.classList.remove('active'));
  // Also handle the "All" button which is a sibling before pf-chain-buttons
  var allBtn = container.querySelector('#pf-chain-buttons').previousElementSibling;
  if (allBtn && allBtn.classList.contains('lev-btn')) allBtn.classList.remove('active');
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
  if (currentChainFilter !== 'all') {
    tokens = tokens.filter(t => t.chain === currentChainFilter);
    lps = lps.filter(lp => {
      var lpChain = lp.chain.charAt(0).toUpperCase() + lp.chain.slice(1);
      return lpChain === currentChainFilter;
    });
  }
  
  // Build chain filter buttons from available chains
  var chains = {};
  (d.tokens || []).forEach(function(t) { chains[t.chain] = true; });
  var chainBtnsContainer = document.getElementById('pf-chain-buttons');
  chainBtnsContainer.innerHTML = Object.keys(chains).sort().map(function(c) {
    return '<button class="lev-btn' + (currentChainFilter === c ? ' active' : '') + '" onclick="filterChain(\'' + esc(c) + '\', this)">' + esc(c) + '</button>';
  }).join('');
  
  // Always show filter bar
  document.getElementById('pf-wallet-filter').style.display = 'flex';

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
    document.getElementById('pf-wallet-buttons').innerHTML = Object.entries(d.wallet_labels).map(([addr, label]) =>
      '<button class="lev-btn' + (currentWalletFilter === addr ? ' active' : '') + '" onclick="filterWallet(\'' + addr + '\', this)">' + esc(label) + '</button>'
    ).join('');
  }

  // Tokens table — grouped by asset category
  const tbody = document.getElementById('pf-tokens-table');
  if (tokens.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#8892b0;padding:20px">No tokens found</td></tr>';
  } else {
    var tokenGroupDefs = {
      'ETH': ['ETH','WETH','stETH','wstETH','cbETH','rETH','weETH','eETH'],
      'BTC': ['BTC','WBTC','cbBTC','tBTC','sBTC'],
      'Stablecoins': ['USDC','USDT','DAI','FRAX','LUSD','TUSD','BUSD','GUSD','USDP','sUSD','crvUSD','GHO','PYUSD','USDe','USDS','USDC.e'],
    };
    // Yield token detection by prefix/pattern
    function isYieldToken(sym) {
      // AAVE aTokens
      if (/^a[A-Z]/.test(sym) && sym.length > 3) return true;
      // Staked/wrapped yield
      if (/^stk/.test(sym)) return true;
      // Syrup (Maple)
      if (/^syrup/i.test(sym)) return true;
      // Compound cTokens
      if (/^c[A-Z]/.test(sym) && sym.length > 3) return true;
      // Spark sDAI, sUSDe etc
      if (/^s[A-Z]/.test(sym) && ['sDAI','sUSDe','sFRAX','sUSDC'].indexOf(sym) !== -1) return true;
      // Wrapped AAVE tokens
      if (/^wa[A-Z]/.test(sym)) return true;
      // Pendle PT/YT tokens
      if (/^PT-|^YT-/.test(sym)) return true;
      // Morpho vault tokens
      if (/^morpho/i.test(sym)) return true;
      // Version suffixed yield tokens
      if (/\.v\d/.test(sym)) return true;
      return false;
    }
    var groupOrder = ['ETH','BTC','Stablecoins','Yield','Other'];
    var totalPortfolio = tokensVal + lpVal + feesVal;
    
    var grouped = {}; groupOrder.forEach(function(g){ grouped[g] = []; });
    tokens.forEach(function(t) {
      var found = false;
      for (var gk in tokenGroupDefs) {
        if (tokenGroupDefs[gk].indexOf(t.symbol) !== -1) { grouped[gk].push(t); found = true; break; }
      }
      if (!found && isYieldToken(t.symbol)) { grouped['Yield'].push(t); found = true; }
      if (!found) grouped['Other'].push(t);
    });
    
    var thtml = '';
    groupOrder.forEach(function(gk) {
      var items = grouped[gk];
      if (items.length === 0) return;
      var gTotal = items.reduce(function(s,t){ return s + t.value_usd; }, 0);
      var gPct = totalPortfolio > 0 ? (gTotal / totalPortfolio * 100) : 0;
      var gIcon = {ETH:'⟠',BTC:'₿',Stablecoins:'💵',Yield:'🌾',Other:'🪙'}[gk] || '';
      thtml += '<tr style="background:#0a0a1a"><td colspan="6" style="padding:8px 10px;font-weight:700;color:#64ffda;font-size:13px">' +
        gIcon + ' ' + esc(gk) + '<span style="float:right;color:#a8b2d1;font-weight:400">' + m(fmt2(gTotal)) + ' <span style="color:#8892b0;font-size:11px">(' + fmtNum(gPct,1) + '% of portfolio)</span></span></td></tr>';
      items.forEach(function(t) {
        var val = t.value_usd > 0 ? m(fmt2(t.value_usd)) : '<span style="color:#555">Unknown</span>';
        var price = t.price_usd > 0 ? m(fmt2(t.price_usd)) : '<span style="color:#555">—</span>';
        thtml += '<tr>' +
          '<td style="text-align:left">' + chainIcon(t.chain) + '</td>' +
          '<td style="text-align:left;color:#e0e0e0;font-weight:600">' + tokenIcon(t.symbol, t.chain) + esc(t.symbol) + '</td>' +
          '<td>' + m(fmtNum(t.balance, 3)) + '</td>' +
          '<td>' + price + '</td>' +
          '<td style="color:#e0e0e0;font-weight:600">' + val + '</td>' +
          '<td style="text-align:left"><span class="wallet-badge">' + esc(t.wallet_label) + '</span></td></tr>';
      });
    });
    tbody.innerHTML = thtml;
  }

  // LP Positions
  const lpDiv = document.getElementById('pf-lp-positions');
  if (lps.length === 0) {
    lpDiv.innerHTML = '<div style="color:#8892b0;padding:20px;text-align:center">No LP positions found</div>';
  } else {
    lpDiv.innerHTML = lps.map(pos => {
      const chainCls = {'ethereum':'eth','arbitrum':'arb','base':'base','bitcoin':'bitcoin'}[pos.chain] || '';
      const rangeBadge = pos.in_range
        ? '<span class="status-badge status-in-range">✅ IN RANGE</span>'
        : '<span class="status-badge status-out-range">❌ OUT OF RANGE</span>';
      const pricePct = ((pos.current_price - pos.price_lower) / (pos.price_upper - pos.price_lower)) * 100;
      const ageText = pos.age_days !== null ? pos.age_days + 'd ' + pos.age_hours + 'h' : 'N/A';
      const chainNameCap = pos.chain.charAt(0).toUpperCase() + pos.chain.slice(1);

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
              chainIcon(chainNameCap) +
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
          '<div class="lp-token-card"><div style="color:#8892b0;font-size:12px">' + tokenIcon(pos.token0_symbol) + esc(pos.token0_symbol) + '</div>' +
            '<div style="color:#e0e0e0;font-weight:600">' + m(fmtNum(pos.amount0, 6)) + '</div>' +
            '<div style="color:#8892b0;font-size:12px">' + m(fmt2(pos.value0_usd)) + '</div></div>' +
          '<div class="lp-token-card"><div style="color:#8892b0;font-size:12px">' + tokenIcon(pos.token1_symbol) + esc(pos.token1_symbol) + '</div>' +
            '<div style="color:#e0e0e0;font-weight:600">' + m(fmtNum(pos.amount1, 6)) + '</div>' +
            '<div style="color:#8892b0;font-size:12px">' + m(fmt2(pos.value1_usd)) + '</div></div>' +
        '</div>' +
        feesHTML + aprHTML +
      '</div>';
    }).join('');
  }

  // AAVE Positions — filter by wallet and chain
  var aaveFiltered = (d.aave_positions || []).filter(function(p) {
    if (currentWalletFilter !== 'all' && p.wallet !== currentWalletFilter) return false;
    if (currentChainFilter !== 'all' && p.chain_name !== currentChainFilter) return false;
    return true;
  });
  renderAavePositions(aaveFiltered);
  
  // GMX Positions — filter by wallet (GMX is Arbitrum only)
  var gmxFiltered = (d.gmx_positions || []).filter(function(p) {
    if (currentWalletFilter !== 'all' && p.wallet !== currentWalletFilter) return false;
    if (currentChainFilter !== 'all' && currentChainFilter !== 'Arbitrum') return false;
    return true;
  });
  renderGmxPositions(gmxFiltered);
}

function renderAavePositions(positions) {
  const section = document.getElementById('pf-aave-section');
  const container = document.getElementById('pf-aave-positions');
  
  if (!positions || positions.length === 0) {
    section.style.display = 'none';
    return;
  }
  
  section.style.display = '';
  
  container.innerHTML = positions.map(pos => {
    const hf = pos.health_factor;
    const currentLtv = pos.total_collateral_usd > 0 ? (pos.total_debt_usd / pos.total_collateral_usd) * 100 : 0;
    const hfColor = hf > 3 ? '#51cf66' : hf > 2 ? '#64ffda' : hf > 1.5 ? '#ffa94d' : '#ff6b6b';
    const hfLabel = hf > 3 ? 'Safe' : hf > 2 ? 'Good' : hf > 1.5 ? 'Caution' : hf > 1 ? 'Danger' : 'LIQUIDATION';
    // Health bar: map HF 1-5 to 0-100%
    const hfPct = Math.min(100, Math.max(0, ((hf - 1) / 4) * 100));
    
    let suppliedHTML = '';
    if (pos.supplied.length > 0) {
      suppliedHTML = '<div style="margin-bottom:12px">' +
        '<div style="color:#51cf66;font-weight:600;font-size:13px;margin-bottom:6px">📥 Supplied</div>' +
        '<table class="hedge-table"><thead><tr>' +
        '<th style="text-align:left">Asset</th><th>Balance</th><th>Value</th><th>APY</th><th>Collateral</th>' +
        '</tr></thead><tbody>' +
        pos.supplied.map(s =>
          '<tr><td style="text-align:left">' + tokenIcon(s.symbol) + esc(s.symbol) + '</td>' +
          '<td>' + m(fmtNum(s.balance, 4)) + '</td>' +
          '<td>' + m(fmt2(s.value_usd)) + '</td>' +
          '<td class="positive">' + fmtNum(s.supply_apy) + '%</td>' +
          '<td>' + (s.collateral_enabled ? '✅' : '❌') + '</td></tr>'
        ).join('') +
        '</tbody></table></div>';
    }
    
    let borrowedHTML = '';
    if (pos.borrowed.length > 0) {
      borrowedHTML = '<div style="margin-bottom:12px">' +
        '<div style="color:#ff6b6b;font-weight:600;font-size:13px;margin-bottom:6px">📤 Borrowed</div>' +
        '<table class="hedge-table"><thead><tr>' +
        '<th style="text-align:left">Asset</th><th>Balance</th><th>Value</th><th>APY</th><th>Type</th>' +
        '</tr></thead><tbody>' +
        pos.borrowed.map(b =>
          '<tr><td style="text-align:left">' + tokenIcon(b.symbol) + esc(b.symbol) + '</td>' +
          '<td>' + m(fmtNum(b.balance, 4)) + '</td>' +
          '<td>' + m(fmt2(b.value_usd)) + '</td>' +
          '<td class="negative">' + fmtNum(b.borrow_apy) + '%</td>' +
          '<td>' + (b.is_variable ? 'Variable' : 'Stable') + '</td></tr>'
        ).join('') +
        '</tbody></table></div>';
    }
    
    return '<div class="lp-card" style="margin-bottom:8px">' +
      '<div class="lp-card-header">' +
        '<div>' +
          '<div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">' +
            chainIcon(pos.chain_name) +
            '<span class="wallet-badge">' + esc(pos.wallet_label || '') + '</span>' +
          '</div>' +
          '<div style="color:#e0e0e0;font-size:16px;font-weight:700">AAVE V3 — ' + esc(pos.chain_name) + '</div>' +
        '</div>' +
        '<div style="text-align:right">' +
          '<div style="font-size:12px;color:#8892b0">Health Factor</div>' +
          '<div style="font-size:28px;font-weight:700;color:' + hfColor + '">' + m(hf > 100 ? '∞' : hf.toFixed(2)) + '</div>' +
          '<div style="font-size:11px;color:' + hfColor + '">' + hfLabel + '</div>' +
        '</div>' +
      '</div>' +
      // Health bar
      '<div style="margin-bottom:14px">' +
        '<div style="display:flex;justify-content:space-between;font-size:11px;color:#8892b0;margin-bottom:4px">' +
          '<span>Liquidation (1.0)</span>' +
          '<span>Safe (5.0+)</span>' +
        '</div>' +
        '<div class="range-track" style="height:8px">' +
          '<div style="position:absolute;inset:0;background:linear-gradient(to right,#ff6b6b,#ffa94d,#51cf66);border-radius:4px"></div>' +
          '<div class="range-needle" style="left:' + hfPct + '%;top:-3px;height:14px"></div>' +
        '</div>' +
      '</div>' +
      // Summary row
      '<div class="lp-tokens-grid" style="grid-template-columns:1fr 1fr 1fr 1fr;margin-bottom:14px">' +
        '<div class="lp-token-card"><div style="color:#8892b0;font-size:11px">Collateral</div><div style="color:#e0e0e0;font-weight:600">' + m(fmt2(pos.total_collateral_usd)) + '</div></div>' +
        '<div class="lp-token-card"><div style="color:#8892b0;font-size:11px">Debt</div><div style="color:#ff6b6b;font-weight:600">' + m(fmt2(pos.total_debt_usd)) + '</div></div>' +
        '<div class="lp-token-card"><div style="color:#8892b0;font-size:11px">Current LTV</div><div style="color:' + (currentLtv > pos.liquidation_threshold ? '#ff6b6b' : currentLtv > pos.ltv ? '#ffa94d' : '#e0e0e0') + ';font-weight:600">' + fmtNum(currentLtv) + '%</div></div>' +
        '<div class="lp-token-card"><div style="color:#8892b0;font-size:11px">Max LTV / Liq.</div><div style="color:#8892b0;font-weight:600">' + fmtNum(pos.ltv) + '% / ' + fmtNum(pos.liquidation_threshold) + '%</div></div>' +
      '</div>' +
      // Liquidation price (when calculable)
      (function() {
        var lp = pos.liquidation_price;
        if (!lp) return '';
        if (lp.type === 'collateral_drop' && lp.current_price > 0) {
          var pctAway = ((lp.current_price - lp.liquidation_price) / lp.current_price * 100);
          var liqColor = pctAway < 15 ? '#ff6b6b' : pctAway < 30 ? '#ffa94d' : '#51cf66';
          return '<div style="padding:10px 14px;background:#0a0a1a;border:1px solid #1e3050;border-radius:8px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center">' +
            '<span style="color:#8892b0;font-size:12px">⚠️ ' + esc(lp.description) + '</span>' +
            '<span style="color:' + liqColor + ';font-weight:700;font-size:16px">' + m(fmt2(lp.liquidation_price)) + ' <span style="font-size:12px;color:#8892b0">(current: ' + m(fmt2(lp.current_price)) + ', ' + fmtNum(pctAway, 1) + '% away)</span></span></div>';
        }
        if (lp.type === 'debt_rise' && lp.current_price > 0) {
          var pctAway = ((lp.liquidation_price - lp.current_price) / lp.current_price * 100);
          var liqColor = pctAway < 15 ? '#ff6b6b' : pctAway < 30 ? '#ffa94d' : '#51cf66';
          return '<div style="padding:10px 14px;background:#0a0a1a;border:1px solid #1e3050;border-radius:8px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center">' +
            '<span style="color:#8892b0;font-size:12px">⚠️ ' + esc(lp.description) + '</span>' +
            '<span style="color:' + liqColor + ';font-weight:700;font-size:16px">' + m(fmt2(lp.liquidation_price)) + ' <span style="font-size:12px;color:#8892b0">(current: ' + m(fmt2(lp.current_price)) + ', ' + fmtNum(pctAway, 1) + '% away)</span></span></div>';
        }
        if (lp.type === 'collateral_drop_pct') {
          return '<div style="padding:10px 14px;background:#0a0a1a;border:1px solid #1e3050;border-radius:8px;margin-bottom:10px">' +
            '<span style="color:#8892b0;font-size:12px">⚠️ ' + esc(lp.description) + '</span> <span style="color:#ffa94d;font-weight:700">' + fmtNum(lp.pct_drop, 1) + '%</span></div>';
        }
        return '';
      })() +
      suppliedHTML + borrowedHTML +
    '</div>';
  }).join('');
}

function renderGmxPositions(positions) {
  const section = document.getElementById('pf-gmx-section');
  const container = document.getElementById('pf-gmx-positions');
  
  if (!positions || positions.length === 0) {
    section.style.display = 'none';
    return;
  }
  
  section.style.display = '';
  
  container.innerHTML = positions.map(pos => {
    const dirBadge = pos.is_long
      ? '<span class="status-badge status-in-range">🟢 LONG</span>'
      : '<span class="status-badge status-out-range">🔴 SHORT</span>';
    const pnlCls = pos.pnl_usd >= 0 ? 'positive' : 'negative';
    const pnlSign = pos.pnl_usd >= 0 ? '+' : '';
    
    // Build price range bar: liquidation — entry — current — SL/TP
    const prices = [pos.liquidation_price, pos.entry_price, pos.current_price];
    pos.stop_loss.forEach(o => prices.push(o.trigger_price));
    pos.take_profit.forEach(o => prices.push(o.trigger_price));
    const minP = Math.min(...prices.filter(p => p > 0)) * 0.95;
    const maxP = Math.max(...prices.filter(p => p > 0)) * 1.05;
    const pctOf = p => ((p - minP) / (maxP - minP)) * 100;
    
    // SL/TP markers
    let markersHTML = '';
    pos.stop_loss.forEach(o => {
      markersHTML += '<div class="gmx-price-marker gmx-sl" style="left:' + pctOf(o.trigger_price) + '%">' +
        '<div class="gmx-marker-label">SL ' + fmtNum(o.trigger_price) + '</div></div>';
    });
    pos.take_profit.forEach(o => {
      markersHTML += '<div class="gmx-price-marker gmx-tp" style="left:' + pctOf(o.trigger_price) + '%">' +
        '<div class="gmx-marker-label">TP ' + fmtNum(o.trigger_price) + '</div></div>';
    });
    
    // SL/TP summary text
    let slTpHTML = '';
    if (pos.stop_loss.length > 0 || pos.take_profit.length > 0) {
      slTpHTML = '<div style="display:flex;gap:16px;margin-top:8px;font-size:12px">';
      pos.stop_loss.forEach(o => {
        slTpHTML += '<div><span style="color:#ff6b6b;font-weight:600">⛔ Stop Loss:</span> ' + m(fmtNum(o.trigger_price)) + ' (' + m(fmt2(o.size_delta_usd)) + ')</div>';
      });
      pos.take_profit.forEach(o => {
        slTpHTML += '<div><span style="color:#51cf66;font-weight:600">🎯 Take Profit:</span> ' + m(fmtNum(o.trigger_price)) + ' (' + m(fmt2(o.size_delta_usd)) + ')</div>';
      });
      slTpHTML += '</div>';
    }
    
    // Build card top section
    var cardTop = '<div class="lp-card-header">' +
        '<div>' +
          '<div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">' +
            chainIcon('Arbitrum') + ' ' + dirBadge +
            '<span class="wallet-badge">' + esc(pos.wallet_label || '') + '</span>' +
          '</div>' +
          '<div style="color:#e0e0e0;font-size:18px;font-weight:700">' + tokenIcon(pos.index_symbol) + ' ' + esc(pos.market) + '</div>' +
          '<div style="color:#8892b0;font-size:12px">Collateral: ' + fmtNum(pos.collateral_amount, 2) + ' ' + esc(pos.collateral_symbol) + '</div>' +
        '</div>' +
        '<div style="text-align:right">' +
          '<div style="color:#e0e0e0;font-size:22px;font-weight:700">' + m(fmt2(pos.size_usd)) + '</div>' +
          '<div style="color:#8892b0;font-size:12px">Position Size</div>' +
        '</div>' +
      '</div>' +
      '<div class="lp-tokens-grid" style="grid-template-columns:1fr 1fr 1fr 1fr;margin-bottom:14px">' +
        '<div class="lp-token-card"><div style="color:#8892b0;font-size:11px">Entry Price</div><div style="color:#e0e0e0;font-weight:600">' + m(fmtNum(pos.entry_price)) + '</div></div>' +
        '<div class="lp-token-card"><div style="color:#8892b0;font-size:11px">Current Price</div><div style="color:#e0e0e0;font-weight:600">' + m(fmtNum(pos.current_price)) + '</div></div>' +
        '<div class="lp-token-card"><div style="color:#8892b0;font-size:11px">Leverage</div><div style="color:#64ffda;font-weight:600">' + fmtNum(pos.leverage, 1) + 'x</div></div>' +
        '<div class="lp-token-card"><div style="color:#8892b0;font-size:11px">Liq. Price</div><div style="color:#ff6b6b;font-weight:600">' + m(fmtNum(pos.liquidation_price)) + ' <span style="font-size:10px;color:#8892b0">(' + fmtNum(Math.abs((pos.liquidation_price - pos.current_price) / pos.current_price * 100), 1) + '% away)</span></div></div>' +
      '</div>' +
      '<div style="margin-bottom:10px;padding:10px 14px;background:' + (pos.pnl_usd >= 0 ? '#0a1a0a' : '#1a0a0a') + ';border:1px solid ' + (pos.pnl_usd >= 0 ? '#1a3a2a' : '#3a1a1a') + ';border-radius:8px;display:flex;justify-content:space-between;align-items:center">' +
        '<div style="color:#8892b0;font-size:13px">Unrealized PnL</div>' +
        '<div style="font-size:18px;font-weight:700" class="' + pnlCls + '">' + m(pnlSign + fmt2(pos.pnl_usd)) + ' <span style="font-size:13px">(' + pnlSign + fmtNum(pos.pnl_pct, 1) + '%)</span></div>' +
      '</div>';
    
    // Price range — sort labels by price low to high
    var priceLabels = [
      {label: 'Liq', price: pos.liquidation_price, color: '#ff6b6b'},
      {label: 'Entry', price: pos.entry_price, color: '#8892b0'},
      {label: 'Current', price: pos.current_price, color: '#e0e0e0'},
    ].sort(function(a,b){ return a.price - b.price; });
    
    return '<div class="lp-card" style="margin-bottom:8px">' + cardTop +
      '<div style="margin-bottom:6px">' +
        '<div style="display:flex;justify-content:space-between;font-size:11px;color:#8892b0;margin-bottom:4px">' +
          '<span style="color:' + priceLabels[0].color + '">' + priceLabels[0].label + ': ' + fmtNum(priceLabels[0].price) + '</span>' +
          '<span style="color:' + priceLabels[1].color + '">' + priceLabels[1].label + ': ' + fmtNum(priceLabels[1].price) + '</span>' +
          '<span style="color:' + priceLabels[2].color + '">' + priceLabels[2].label + ': ' + fmtNum(priceLabels[2].price) + '</span>' +
        '</div>' +
        '<div class="range-track" style="position:relative;height:8px">' +
          '<div style="position:absolute;inset:0;background:linear-gradient(to right,' + (pos.is_long ? '#ff6b6b,#333,#51cf66' : '#51cf66,#333,#ff6b6b') + ');border-radius:4px"></div>' +
          '<div class="gmx-price-marker gmx-liq" style="left:' + pctOf(pos.liquidation_price) + '%"><div class="gmx-marker-label" style="color:#ff6b6b">💀</div></div>' +
          '<div class="gmx-price-marker gmx-entry" style="left:' + pctOf(pos.entry_price) + '%"><div class="gmx-marker-label">Entry</div></div>' +
          '<div class="range-needle" style="left:' + pctOf(pos.current_price) + '%;top:-3px;height:14px"></div>' +
          '<div class="gmx-price-marker" style="left:' + pctOf(pos.current_price) + '%;top:-20px"><div class="gmx-marker-label" style="color:#fff;font-weight:700">▼</div></div>' +
          markersHTML +
        '</div>' +
      '</div>' +
      slTpHTML +
    '</div>';
  }).join('');
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
      const masked = w.address.startsWith('xpub') || w.address.startsWith('ypub') || w.address.startsWith('zpub')
            ? w.address.substring(0,8) + '••••' + w.address.substring(w.address.length-4)
            : w.address.substring(0,6) + '••••' + w.address.substring(w.address.length-4);
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
  if (!addr) {
    errEl.textContent = 'Please enter an address'; errEl.style.display = 'block'; return;
  }
  const isXpub = addr.startsWith('xpub') || addr.startsWith('ypub') || addr.startsWith('zpub');
  if (!isXpub && (!addr.startsWith('0x') || addr.length !== 42)) {
    errEl.textContent = 'Invalid format. Use 0x... address or xpub/ypub/zpub key.'; errEl.style.display = 'block'; return;
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
