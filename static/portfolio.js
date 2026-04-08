// ===== PORTFOLIO TAB =====
let portfolioData = null;
let currentWalletFilter = 'all';
let currentChainFilter = 'all';
let valuesMasked = false;
let hideDust = true;

// Lucide icon helper — returns inline SVG string
function li(name, size, color) {
  size = size || 16;
  color = color || 'currentColor';
  try {
    var iconData = lucide.icons[name];
    if (!iconData) return '';
    var svg = iconData[0], attrs = iconData[1];
    var paths = svg.map(function(el) {
      var tag = el[0], a = el[1];
      var attrStr = Object.keys(a).map(function(k) { return k + '="' + a[k] + '"'; }).join(' ');
      return '<' + tag + ' ' + attrStr + '></' + tag + '>';
    }).join('');
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="' + color + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle">' + paths + '</svg>';
  } catch(e) { return ''; }
}

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

var protocolIconUrls = {
  'uniswap_v3': 'https://assets.coingecko.com/coins/images/12504/small/uni.jpg',
  'aave_v3': 'https://assets.coingecko.com/coins/images/12645/small/aave-token-round.png',
  'gmx_v2': 'https://assets.coingecko.com/coins/images/18323/small/arbit.png',
  'camelot': 'https://assets.coingecko.com/coins/images/28416/small/camelot.png',
  'aerodrome': 'https://assets.coingecko.com/coins/images/31745/small/token.png',
};

function protocolIcon(protocol, dynamicUrl) {
  var url = dynamicUrl || protocolIconUrls[(protocol || '').toLowerCase()];
  if (url) return '<img class="chain-icon" src="' + url + '" title="' + esc(protocol) + '" onerror="this.style.display=\'none\'">';
  return '';
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
  // Update all mask toggle buttons
  document.querySelectorAll('.mask-toggle-btn').forEach(function(btn) {
    btn.innerHTML = '';
    var icon = document.createElement('i');
    icon.setAttribute('data-lucide', valuesMasked ? 'eye-off' : 'eye');
    icon.style.width = '16px';
    icon.style.height = '16px';
    btn.appendChild(icon);
    lucide.createIcons({nodes: [btn]});
    btn.classList.toggle('active', valuesMasked);
  });
  // Apply mask to entire app
  document.body.classList.toggle('values-masked', valuesMasked);
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
  document.getElementById('portfolioBtn').style.display = view === 'live' ? '' : 'none';
  if (view === 'history') {
    initHistory();
    loadHistoryCharts();  // Always re-fetch from DB when switching to performance
  }
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

function toggleDustFilter() {
  hideDust = !hideDust;
  var btn = document.getElementById('pf-dust-toggle');
  if (btn) {
    btn.textContent = hideDust ? 'Show all' : 'Hide dust';
    btn.classList.toggle('active', hideDust);
  }
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
  var filteredLending = (d.aave_positions || []).filter(function(a) {
    if (currentWalletFilter !== 'all' && a.wallet !== currentWalletFilter) return false;
    return true;
  });
  var filteredHedges = (d.gmx_positions || []).filter(function(p) {
    if (currentWalletFilter !== 'all' && p.wallet !== currentWalletFilter) return false;
    return true;
  });
  // Lending collateral NOT added to total — aTokens in token list already represent it
  const hedgeVal = filteredHedges.reduce((s, p) => s + (p.collateral_amount || 0), 0);
  const totalVal = tokensVal + lpVal + feesVal + hedgeVal;

  document.getElementById('pf-total').innerHTML = m(fmt2(totalVal));
  document.getElementById('pf-total').style.color = '';
  var now = new Date();
  if (d.fetched_at) {
    now = new Date(d.fetched_at);
  }
  document.getElementById('pf-last-updated').textContent = 'Last Updated: ' +
    String(now.getDate()).padStart(2,'0') + '.' + String(now.getMonth()+1).padStart(2,'0') + '.' + now.getFullYear() + ' ' +
    String(now.getHours()).padStart(2,'0') + ':' + String(now.getMinutes()).padStart(2,'0');
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
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#8892b0;padding:20px;font-size:13px">No tokens found</td></tr>';
  } else {
    var tokenGroupDefs = {
      'ETH': ['ETH','WETH','stETH','wstETH','cbETH','rETH','weETH','eETH'],
      'BTC': ['BTC','WBTC','cbBTC','tBTC','sBTC'],
      'Stablecoins': ['USDC','USDT','DAI','FRAX','LUSD','TUSD','BUSD','GUSD','USDP','sUSD','crvUSD','GHO','PYUSD','USDe','USDS','USDC.e','USDT0'],
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
    
    // Pattern-based stablecoin detection (catches syrupUSDC, aEthUSDC, USDT0, etc.)
    function isStablecoin(sym) {
      if (tokenGroupDefs['Stablecoins'].indexOf(sym) !== -1) return true;
      var s = sym.toLowerCase();
      return s.indexOf('usdc') >= 0 || s.indexOf('usdt') >= 0 || s.indexOf('usd') >= 0 || s.indexOf('dai') >= 0;
    }

    var grouped = {}; groupOrder.forEach(function(g){ grouped[g] = []; });
    tokens.forEach(function(t) {
      if (hideDust && t.value_usd < 0.01) return;
      var found = false;
      // Check ETH/BTC exact matches first
      for (var gk in tokenGroupDefs) {
        if (gk === 'Stablecoins') continue;
        if (tokenGroupDefs[gk].indexOf(t.symbol) !== -1) { grouped[gk].push(t); found = true; break; }
      }
      // Exact stablecoin match (USDC, USDT, DAI, USDT0, etc.)
      if (!found && tokenGroupDefs['Stablecoins'].indexOf(t.symbol) !== -1) { grouped['Stablecoins'].push(t); found = true; }
      // Yield-bearing stablecoins (syrupUSDC, aEthUSDC, sUSDe) → Yield
      if (!found && isYieldToken(t.symbol)) { grouped['Yield'].push(t); found = true; }
      // Pattern-based stablecoin fallback (anything else with usd/dai in name)
      if (!found && isStablecoin(t.symbol)) { grouped['Stablecoins'].push(t); found = true; }
      if (!found) grouped['Other'].push(t);
    });

    // Sort tokens within each group by value descending
    groupOrder.forEach(function(gk) {
      grouped[gk].sort(function(a, b) { return b.value_usd - a.value_usd; });
    });

    // Sort groups by total value descending
    groupOrder.sort(function(a, b) {
      var aTotal = grouped[a].reduce(function(s, t) { return s + t.value_usd; }, 0);
      var bTotal = grouped[b].reduce(function(s, t) { return s + t.value_usd; }, 0);
      return bTotal - aTotal;
    });
    
    var thtml = '';
    groupOrder.forEach(function(gk) {
      var items = grouped[gk];
      if (items.length === 0) return;
      var gTotal = items.reduce(function(s,t){ return s + t.value_usd; }, 0);
      var gPct = totalPortfolio > 0 ? (gTotal / totalPortfolio * 100) : 0;
      var gIcon = {ETH: li('hexagon',14,'#627eea'), BTC: li('bitcoin',14,'#f7931a'), Stablecoins: li('banknote',14,'#51cf66'), Yield: li('sprout',14,'#fdcb6e'), Other: li('circle-dot',14,'#8892b0')}[gk] || '';
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
          '<td class="col-wallet" style="text-align:left"><span class="wallet-badge">' + esc(t.wallet_label) + '</span></td></tr>';
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
        ? '<span class="status-badge status-in-range">' + li('check-circle',14,'#51cf66') + ' IN RANGE</span>'
        : '<span class="status-badge status-out-range">' + li('x-circle',14,'#ff6b6b') + ' OUT OF RANGE</span>';
      const hasRange = pos.price_upper > 0 && pos.price_lower >= 0 && pos.price_upper !== pos.price_lower;
      const pricePct = hasRange ? ((pos.current_price - pos.price_lower) / (pos.price_upper - pos.price_lower)) * 100 : 50;
      const ageText = pos.age_days !== null ? pos.age_days + 'd ' + pos.age_hours + 'h' : 'N/A';
      const chainNameCap = pos.chain.charAt(0).toUpperCase() + pos.chain.slice(1);

      let feesHTML = '';
      if (pos.total_earned_fees_usd > 0.01) {
        feesHTML = '<div class="lp-fees-section">' +
          '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">' +
          '<span style="font-size:16px">' + li('circle-dollar-sign',16,'#51cf66') + '</span>' +
          '<span style="color:#51cf66;font-weight:700;font-size:14px">Total Fees</span>' +
          '<span style="color:#51cf66;font-weight:700;font-size:18px;margin-left:auto">' + m(fmt2(pos.total_earned_fees_usd)) + '</span></div>';
        if (pos.collected_fees_0 > 0 || pos.collected_fees_1 > 0) {
          feesHTML += '<div style="font-size:12px;color:#a8b2d1">';
          if (pos.collected_fees_0 > 0) feesHTML += '<div>Collected: ' + fmtNum(pos.collected_fees_0, 6) + ' ' + esc(pos.token0_symbol) + ' (' + m(fmt2(pos.collected_fees_0_usd)) + ')</div>';
          if (pos.collected_fees_1 > 0) feesHTML += '<div>Collected: ' + fmtNum(pos.collected_fees_1, 6) + ' ' + esc(pos.token1_symbol) + ' (' + m(fmt2(pos.collected_fees_1_usd)) + ')</div>';
          feesHTML += '</div>';
        } else if ((pos.total_collected_fees_usd || 0) > 0.01) {
          feesHTML += '<div style="font-size:12px;color:#a8b2d1">Collected: ' + m(fmt2(pos.total_collected_fees_usd)) + '</div>';
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
              chainIcon(chainNameCap) + protocolIcon(pos.protocol, pos.protocol_icon_url) +
              (pos.position_module === 'farming' ? '<span class="status-badge" style="background:rgba(253,203,110,0.15);color:#fdcb6e;font-size:10px;padding:2px 6px">' + li('sprout',12,'#fdcb6e') + ' Farming</span>' : '') +
              (hasRange ? rangeBadge : '') +
              '<span class="wallet-badge">' + esc(pos.wallet_label || '') + '</span>' +
            '</div>' +
            '<div style="color:#e0e0e0;font-size:18px;font-weight:700">' + esc(pos.pair) + '</div>' +
            '<div style="color:#8892b0;font-size:12px">' + (pos.fee_tier ? fmtNum(pos.fee_tier) + '% fee tier • ' : '') + 'Age: ' + ageText + '</div>' +
          '</div>' +
          '<div style="text-align:right">' +
            '<div style="color:#e0e0e0;font-size:22px;font-weight:700">' + m(fmt2(pos.total_value_usd)) + '</div>' +
            '<div style="color:#8892b0;font-size:12px">Position Value</div>' +
          '</div>' +
        '</div>' +
        // Price range bar (only for concentrated liquidity positions)
        (hasRange ? (
        '<div class="lp-range-bar">' +
          '<div style="display:flex;justify-content:space-between;font-size:12px;color:#8892b0;margin-bottom:4px">' +
            '<span>Min: ' + fmtNum(pos.price_lower) + '</span>' +
            '<span style="color:#e0e0e0;font-weight:600">Current: ' + fmtNum(pos.current_price) + '</span>' +
            '<span>Max: ' + fmtNum(pos.price_upper) + '</span>' +
          '</div>' +
          '<div class="range-track"><div class="range-fill"></div><div class="range-needle" style="left:' + Math.max(0, Math.min(100, pricePct)) + '%"></div></div>' +
        '</div>'
        ) : '') +
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
  
  // Manual positions
  loadManualPositions();
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
          '<td>' + (s.collateral_enabled ? li('check-circle',14,'#51cf66') : li('x-circle',14,'#ff6b6b')) + '</td></tr>'
        ).join('') +
        '</tbody></table></div>';
    }
    
    let borrowedHTML = '';
    if (pos.borrowed.length > 0) {
      borrowedHTML = '<div style="margin-bottom:12px">' +
        '<div style="color:#ff6b6b;font-weight:600;font-size:13px;margin-bottom:6px">' + li('arrow-up-right',14,'#ff6b6b') + ' Borrowed</div>' +
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
            '<span style="color:#8892b0;font-size:12px">'+li('alert-triangle',14,'#ffa94d')+' ' + esc(lp.description) + '</span>' +
            '<span style="color:' + liqColor + ';font-weight:700;font-size:16px">' + m(fmt2(lp.liquidation_price)) + ' <span style="font-size:12px;color:#8892b0">(current: ' + m(fmt2(lp.current_price)) + ', ' + fmtNum(pctAway, 1) + '% away)</span></span></div>';
        }
        if (lp.type === 'debt_rise' && lp.current_price > 0) {
          var pctAway = ((lp.liquidation_price - lp.current_price) / lp.current_price * 100);
          var liqColor = pctAway < 15 ? '#ff6b6b' : pctAway < 30 ? '#ffa94d' : '#51cf66';
          return '<div style="padding:10px 14px;background:#0a0a1a;border:1px solid #1e3050;border-radius:8px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center">' +
            '<span style="color:#8892b0;font-size:12px">'+li('alert-triangle',14,'#ffa94d')+' ' + esc(lp.description) + '</span>' +
            '<span style="color:' + liqColor + ';font-weight:700;font-size:16px">' + m(fmt2(lp.liquidation_price)) + ' <span style="font-size:12px;color:#8892b0">(current: ' + m(fmt2(lp.current_price)) + ', ' + fmtNum(pctAway, 1) + '% away)</span></span></div>';
        }
        if (lp.type === 'collateral_drop_pct') {
          return '<div style="padding:10px 14px;background:#0a0a1a;border:1px solid #1e3050;border-radius:8px;margin-bottom:10px">' +
            '<span style="color:#8892b0;font-size:12px">'+li('alert-triangle',14,'#ffa94d')+' ' + esc(lp.description) + '</span> <span style="color:#ffa94d;font-weight:700">' + fmtNum(lp.pct_drop, 1) + '%</span></div>';
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
      ? '<span class="status-badge status-in-range">'+li('trending-up',14,'#51cf66')+' LONG</span>'
      : '<span class="status-badge status-out-range">'+li('trending-down',14,'#ff6b6b')+' SHORT</span>';
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
        slTpHTML += '<div><span style="color:#51cf66;font-weight:600">'+li('target',14,'#51cf66')+' Take Profit:</span> ' + m(fmtNum(o.trigger_price)) + ' (' + m(fmt2(o.size_delta_usd)) + ')</div>';
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
          '<div class="gmx-price-marker gmx-liq" style="left:' + pctOf(pos.liquidation_price) + '%"><div class="gmx-marker-label" style="color:#ff6b6b">'+li('skull',14,'#ff6b6b')+'</div></div>' +
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
        '<th style="text-align:left">Label</th><th style="text-align:left">Address</th><th>Role</th><th>Actions</th>' +
        '</tr></thead><tbody>' +
        wallets.map(w => {
      const masked = w.address.startsWith('xpub') || w.address.startsWith('ypub') || w.address.startsWith('zpub')
            ? w.address.substring(0,8) + '••••' + w.address.substring(w.address.length-4)
            : w.address.substring(0,6) + '••••' + w.address.substring(w.address.length-4);
          var role = w.role || 'active';
          return '<tr>' +
            '<td style="text-align:left">' + esc(w.label) + '</td>' +
            '<td style="text-align:left;font-size:12px;color:#a8b2d1;font-family:monospace">' + masked + '</td>' +
            '<td><select style="padding:3px 6px;border:1px solid #333;border-radius:4px;background:#0a0a1a;color:#e0e0e0;font-size:11px" onchange="updateWalletRole(\'' + esc(w.address) + '\',this.value)">' +
              '<option value="active"' + (role === 'active' ? ' selected' : '') + '>Active</option>' +
              '<option value="treasury"' + (role === 'treasury' ? ' selected' : '') + '>Treasury</option>' +
            '</select></td>' +
            '<td style="white-space:nowrap">' +
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
      { id: 'ETHERSCAN_API_KEY', label: 'Etherscan API Key', value: data.etherscan_api_key, desc: 'Position age & collected fees (Ethereum & Arbitrum)' },
      { id: 'OPENAI_API_KEY', label: 'OpenAI API Key', value: data.openai_api_key, desc: 'AI Daily Brief — GPT-4o or other OpenAI models' },
      { id: 'AWS_BEARER_TOKEN_BEDROCK', label: 'AWS Bedrock Bearer Token', value: data.aws_bearer_token, desc: 'AI Daily Brief — AWS Bedrock (Claude models)' },
      { id: 'ZERION_API_KEY', label: 'Zerion API Key', value: data.zerion_api_key, desc: 'Unified EVM portfolio data (tokens, DeFi positions, lending)' },
      { id: 'FRED_API_KEY', label: 'FRED API Key', value: data.fred_api_key, desc: 'Macro data (optional) — US10Y, DXY, M2, Fed Funds. Free at fred.stlouisfed.org' },
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

function updateWalletRole(addr, role) {
  fetch('/api/wallets/' + encodeURIComponent(addr), {
    method: 'PUT', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ role: role })
  }).then(function() { portfolioData = null; });
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

// ===== SETTINGS SUB-TABS =====
function setSettingsView(view) {
  document.getElementById('settings-config-view').style.display = view === 'config' ? '' : 'none';
  document.getElementById('settings-profile-view').style.display = view === 'profile' ? '' : 'none';
  document.getElementById('settings-ai-view').style.display = view === 'ai' ? '' : 'none';
  document.getElementById('settings-messaging-view').style.display = view === 'messaging' ? '' : 'none';
  document.getElementById('settings-view-config').classList.toggle('active', view === 'config');
  document.getElementById('settings-view-profile').classList.toggle('active', view === 'profile');
  document.getElementById('settings-view-ai').classList.toggle('active', view === 'ai');
  document.getElementById('settings-view-messaging').classList.toggle('active', view === 'messaging');
  if (view === 'profile') loadProfile();
  if (view === 'ai') loadAIConfig();
  if (view === 'messaging') loadTelegramConfig();
}

// ===== TELEGRAM MESSAGING =====
async function loadTelegramConfig() {
  try {
    var resp = await fetch('/api/settings/telegram');
    var data = await resp.json();
    document.getElementById('telegram-bot-token').value = data.bot_token || '';
    document.getElementById('telegram-chat-id').value = data.chat_id || '';
    document.getElementById('telegram-schedule-hour').value = data.schedule_utc_hour != null ? data.schedule_utc_hour : 9;
    document.getElementById('telegram-enabled').value = data.enabled ? 'true' : 'false';
    document.getElementById('telegram-include-digest').checked = data.include_digest !== false;
    document.getElementById('telegram-include-regime').checked = data.include_regime !== false;
  } catch (e) {
    showTelegramStatus('Failed to load config', true);
  }
}

async function saveTelegramConfig() {
  var enabled = document.getElementById('telegram-enabled').value === 'true';
  var includeDigest = document.getElementById('telegram-include-digest').checked;
  var includeRegime = document.getElementById('telegram-include-regime').checked;
  if (enabled && !includeDigest && !includeRegime) {
    showTelegramStatus('At least one content section must be selected when enabled', true);
    return;
  }
  var config = {
    bot_token: document.getElementById('telegram-bot-token').value,
    chat_id: document.getElementById('telegram-chat-id').value,
    schedule_utc_hour: parseInt(document.getElementById('telegram-schedule-hour').value) || 9,
    enabled: enabled,
    include_digest: includeDigest,
    include_regime: includeRegime
  };
  try {
    var resp = await fetch('/api/settings/telegram', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(config)
    });
    var data = await resp.json();
    if (resp.ok) {
      showTelegramStatus('Configuration saved', false);
    } else {
      showTelegramStatus(data.error || 'Failed to save', true);
    }
  } catch (e) {
    showTelegramStatus('Network error saving config', true);
  }
}

async function sendTestMessage() {
  showTelegramStatus('Sending...', false);
  try {
    var resp = await fetch('/api/settings/telegram/test', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        bot_token: document.getElementById('telegram-bot-token').value,
        chat_id: document.getElementById('telegram-chat-id').value
      })
    });
    var data = await resp.json();
    if (resp.ok) {
      showTelegramStatus('Test message sent successfully', false);
    } else {
      showTelegramStatus(data.error || 'Failed to send test message', true);
    }
  } catch (e) {
    showTelegramStatus('Network error sending test', true);
  }
}

function showTelegramStatus(msg, isError) {
  var el = document.getElementById('telegram-status');
  el.textContent = msg;
  el.style.color = isError ? '#ff6b6b' : '#51cf66';
  el.style.display = '';
  if (!isError) setTimeout(function() { el.style.display = 'none'; }, 4000);
}

// ===== INVESTOR PROFILE =====
var profileQuestions = [
  {section: 'Section 1: Investor Profile'},
  {id:'portfolio_structure', type:'textarea', label:'How do you structure your crypto portfolio?', placeholder:'e.g., cold/hot wallet split, CEX accounts'},
  {id:'investment_horizon', type:'select', label:'Primary investment horizon', options:['1 year','3-5 years','5+ years']},
  {section: 'Portfolio Priorities (select top 4, rank 1-4 where 1 is highest)'},
  {id:'priority_accumulation', type:'priority', label:'Asset accumulation (future price appreciation)'},
  {id:'priority_preservation', type:'priority', label:'Capital preservation (drawdown tolerance)'},
  {id:'priority_efficiency', type:'priority', label:'Capital efficiency'},
  {id:'priority_risk', type:'priority', label:'Risk tolerance'},
  {id:'priority_yield', type:'priority', label:'Fee/yield generation'},
  {id:'priority_liquidity', type:'priority', label:'Liquidity'},
  {id:'priority_ease', type:'priority', label:'Ease of management'},
  {section: 'DeFi Experience Level'},
  {id:'exp_lp', type:'select', label:'Liquidity Providing', options:['None','Low','Moderate','High']},
  {id:'exp_hedging', type:'select', label:'Hedging', options:['None','Low','Moderate','High']},
  {id:'exp_lending', type:'select', label:'Lending & Borrowing', options:['None','Low','Moderate','High']},
  {id:'exp_perps', type:'select', label:'Perpetuals', options:['None','Low','Moderate','High']},
  {id:'exp_options', type:'select', label:'Options', options:['None','Low','Moderate','High']},
  {section: 'Targets & Preferences'},
  {id:'target_apy', type:'number', label:'Target APY on total portfolio (%)', placeholder:'e.g., 15'},
  {id:'risk_profile', type:'select', label:'Risk profile', options:['Conservative','Moderate','Aggressive']},
  {id:'open_to_leverage', type:'select', label:'Open to leverage?', options:['No','Yes - low (< 2x)','Yes - moderate (2-5x)','Yes - high (5x+)']},
  {id:'max_ltv', type:'number', label:'Max LTV if using leverage (%)', placeholder:'e.g., 50'},
  {id:'lp_pair_types', type:'textarea', label:'Which LP pair types interest you?', placeholder:'e.g., ETH/Stable, WBTC/Stable, other'},
  {id:'high_risk_pct', type:'number', label:'% of capital for higher-risk / smaller-cap tokens', placeholder:'e.g., 10'},
  {id:'low_maintenance', type:'select', label:'Prefer low-maintenance strategies?', options:['Yes - ease over efficiency','Balanced','No - maximize returns']},
  {section: 'Section 2: Long-Term Token Conviction'},
  {id:'conviction_tokens', type:'textarea', label:'Tokens you are long-term bullish about (token + reason)', placeholder:'BTC - digital gold, store of value\nETH - smart contract platform\nSOL - fast L1'},
  {id:'longterm_timeframe', type:'select', label:'What is "long-term" for you?', options:['1 year+','3 years+','5 years+']},
  {section: 'Section 4: Cashflow Requirements'},
  {id:'zero_yield_ok', type:'select', label:'Is zero yield acceptable during bear markets?', options:['Yes','No']},
  {id:'bear_strategies', type:'checkboxes', label:'Acceptable bear market strategies', options:['Yield farming/staking','Shorting','Accumulating blue chips at lower USD value','Other']},
  {id:'bear_strategies_other', type:'text', label:'Other bear strategy (if selected)', placeholder:'Describe...'},
  {section: 'Section 5: Risk Tolerance'},
  {id:'max_drawdown', type:'number', label:'Maximum acceptable portfolio drawdown (%)', placeholder:'e.g., 30'},
  {id:'drawdown_if_accumulating', type:'select', label:'Is notional drawdown acceptable if token count is increasing?', options:['Yes','No']},
  {id:'hedging_tools', type:'checkboxes', label:'Hedging tools you are comfortable using', options:['Short positions','Long hedges','Options','None']},
  {section: 'Section 6: Operational Preferences'},
  {id:'hours_per_week', type:'number', label:'Average hours per week for portfolio management', placeholder:'e.g., 5'},
  {id:'comfortable_rebalancing', type:'select', label:'Comfortable rebalancing when clearly indicated?', options:['Yes','No']},
  {id:'rebalancing_rules', type:'textarea', label:'Rebalancing rules you follow', placeholder:'e.g., wait 24h before acting on range breaks'},
  {id:'framework_preference', type:'select', label:'Structured framework or fully discretionary?', options:['Structured with tactical flexibility','Fully discretionary','Structured only']},
  {section: 'Section 7: Chain & Protocol Preference'},
  {id:'current_chains', type:'textarea', label:'Chains you currently use', placeholder:'e.g., Ethereum, Arbitrum, Base, Solana'},
  {id:'open_new_chains', type:'select', label:'Open to trying new chains?', options:['Yes','No']},
  {id:'new_chains_which', type:'text', label:'If yes, which new chains?', placeholder:'e.g., Sui, Aptos'},
  {section: 'Section 8: Stablecoin Preference'},
  {id:'stablecoin_prefs', type:'checkboxes', label:'Preferred stablecoins', options:['USDC','USDT','DAI','Yield-bearing','Other']},
  {id:'stablecoin_yield', type:'text', label:'Yield-bearing stablecoin (if selected)', placeholder:'e.g., sDAI, USDe'},
  {id:'synthetic_stables', type:'select', label:'Willing to use synthetic stablecoins?', options:['Yes','No','Short-term only']},
  {section: 'Section 9: Tax Considerations'},
  {id:'tax_factor', type:'select', label:'Factor tax implications into recommendations?', options:['Yes','No']},
  {id:'tax_jurisdiction', type:'text', label:'Tax jurisdiction (if yes)', placeholder:'e.g., US, UK, Germany'},
];

var profileData = {};

async function loadProfile() {
  try {
    var resp = await fetch('/api/profile');
    profileData = await resp.json();
  } catch(e) { profileData = {}; }
  renderProfileForm();
}

function renderProfileForm() {
  var html = '';
  profileQuestions.forEach(function(q) {
    if (q.section) {
      html += '<div class="section-title" style="margin-top:16px">' + esc(q.section) + '</div>';
      return;
    }
    var val = profileData[q.id] || '';
    html += '<div style="margin-bottom:12px">';
    html += '<label style="display:block;color:#a8b2d1;font-size:12px;font-weight:600;margin-bottom:4px">' + esc(q.label) + '</label>';
    if (q.type === 'text' || q.type === 'number') {
      html += '<input id="pq-' + q.id + '" type="' + q.type + '" value="' + esc(String(val)) + '" placeholder="' + esc(q.placeholder||'') + '" style="width:100%;max-width:400px;padding:7px;border:1px solid #333;border-radius:6px;background:#0a0a1a;color:#e0e0e0;font-size:13px">';
    } else if (q.type === 'textarea') {
      html += '<textarea id="pq-' + q.id + '" placeholder="' + esc(q.placeholder||'') + '" style="width:100%;max-width:500px;padding:7px;border:1px solid #333;border-radius:6px;background:#0a0a1a;color:#e0e0e0;font-size:13px;min-height:60px;resize:vertical">' + esc(String(val)) + '</textarea>';
    } else if (q.type === 'priority') {
      var pOpts = ['Not prioritized','1 - Highest','2','3','4 - Lowest'];
      html += '<select id="pq-' + q.id + '" class="priority-select" onchange="checkPriorityDupes()" style="padding:7px;border:1px solid #333;border-radius:6px;background:#0a0a1a;color:#e0e0e0;font-size:13px">';
      html += '<option value="">— Select —</option>';
      pOpts.forEach(function(o) { html += '<option value="' + esc(o) + '"' + (val === o ? ' selected' : '') + '>' + esc(o) + '</option>'; });
      html += '</select> <span id="pqw-' + q.id + '" style="color:#ff6b6b;font-size:11px;display:none">'+li('alert-triangle',12,'#ff6b6b')+' duplicate</span>';
    } else if (q.type === 'select') {
      html += '<select id="pq-' + q.id + '" style="padding:7px;border:1px solid #333;border-radius:6px;background:#0a0a1a;color:#e0e0e0;font-size:13px">';
      html += '<option value="">— Select —</option>';
      q.options.forEach(function(o) { html += '<option value="' + esc(o) + '"' + (val === o ? ' selected' : '') + '>' + esc(o) + '</option>'; });
      html += '</select>';
    } else if (q.type === 'range') {
      var rv = val || 4;
      html += '<input id="pq-' + q.id + '" type="range" min="' + q.min + '" max="' + q.max + '" value="' + rv + '" style="width:200px;accent-color:#64ffda"> <span style="color:#64ffda;font-weight:700" id="pqv-' + q.id + '">' + rv + '</span>';
      html += '<script>document.getElementById("pq-' + q.id + '").oninput=function(){document.getElementById("pqv-' + q.id + '").textContent=this.value}<\/script>';
    } else if (q.type === 'checkboxes') {
      var checked = Array.isArray(val) ? val : [];
      q.options.forEach(function(o) {
        html += '<label style="display:inline-flex;align-items:center;gap:4px;margin-right:12px;color:#e0e0e0;font-size:13px;cursor:pointer"><input type="checkbox" class="pq-cb-' + q.id + '" value="' + esc(o) + '"' + (checked.indexOf(o) !== -1 ? ' checked' : '') + '> ' + esc(o) + '</label>';
      });
    }
    html += '</div>';
  });
  document.getElementById('profile-form').innerHTML = html;
}

function collectProfile() {
  var data = {};
  profileQuestions.forEach(function(q) {
    if (q.section) return;
    if (q.type === 'checkboxes') {
      var cbs = document.querySelectorAll('.pq-cb-' + q.id + ':checked');
      data[q.id] = Array.from(cbs).map(function(cb) { return cb.value; });
    } else if (q.type === 'range' || q.type === 'number') {
      var el = document.getElementById('pq-' + q.id);
      data[q.id] = el ? (el.value ? Number(el.value) : '') : '';
    } else {
      var el = document.getElementById('pq-' + q.id);
      data[q.id] = el ? el.value : '';
    }
  });
  return data;
}

function checkPriorityDupes() {
  var pids = ['priority_accumulation','priority_preservation','priority_efficiency','priority_risk','priority_yield','priority_liquidity','priority_ease'];
  var vals = {};
  pids.forEach(function(pid) {
    var el = document.getElementById('pq-' + pid);
    var w = document.getElementById('pqw-' + pid);
    if (w) w.style.display = 'none';
    if (el) {
      var v = el.value;
      if (v && v !== 'Not prioritized' && v !== '') {
        if (!vals[v]) vals[v] = [];
        vals[v].push(pid);
      }
      el.style.borderColor = '#333';
    }
  });
  for (var v in vals) {
    if (vals[v].length > 1) {
      vals[v].forEach(function(pid) {
        var el = document.getElementById('pq-' + pid);
        var w = document.getElementById('pqw-' + pid);
        if (el) el.style.borderColor = '#ff6b6b';
        if (w) w.style.display = 'inline';
      });
    }
  }
}

async function saveProfile() {
  var data = collectProfile();
  var msgEl = document.getElementById('profile-msg');
  
  // Validate priorities: no duplicate ranks (except "Not prioritized")
  var priorityIds = ['priority_accumulation','priority_preservation','priority_efficiency','priority_risk','priority_yield','priority_liquidity','priority_ease'];
  var usedRanks = {};
  var dupes = false;
  priorityIds.forEach(function(pid) {
    var val = data[pid];
    if (val && val !== 'Not prioritized') {
      if (usedRanks[val]) { dupes = true; }
      usedRanks[val] = (usedRanks[val] || 0) + 1;
    }
  });
  if (dupes) {
    showSettingsMsg(msgEl, 'Portfolio priorities: each rank (1-4) can only be used once', true);
    return;
  }
  var rankedCount = Object.keys(usedRanks).length;
  if (rankedCount > 0 && rankedCount !== 4) {
    showSettingsMsg(msgEl, 'Please select exactly 4 priorities (ranked 1-4)', true);
    return;
  }
  
  try {
    var resp = await fetch('/api/profile', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(data)
    });
    var result = await resp.json();
    if (resp.ok) {
      profileData = data;
      showSettingsMsg(msgEl, 'Profile saved', false);
    } else {
      showSettingsMsg(msgEl, result.error || 'Error saving', true);
    }
  } catch(e) { showSettingsMsg(msgEl, 'Network error', true); }
}

// ===== PROFILE EXPORT/IMPORT =====
async function exportProfile() {
  try {
    var resp = await fetch('/api/profile');
    var data = await resp.json();
    var blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'investor_profile.json';
    a.click();
  } catch(e) {
    showSettingsMsg(document.getElementById('settings-backup-msg'), 'Export failed', true);
  }
}

async function importProfile(input) {
  var file = input.files[0];
  if (!file) return;
  var msgEl = document.getElementById('settings-backup-msg');
  try {
    var text = await file.text();
    var data = JSON.parse(text);
    var resp = await fetch('/api/profile', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(data)
    });
    if (resp.ok) {
      profileData = data;
      showSettingsMsg(msgEl, 'Profile imported', false);
    } else {
      showSettingsMsg(msgEl, 'Import failed', true);
    }
  } catch(e) {
    showSettingsMsg(msgEl, 'Invalid JSON file', true);
  }
  input.value = '';
}

// ===== MANUAL POSITIONS =====
function showManualForm() { document.getElementById('manual-form').style.display = ''; setManualType('lp'); }
function hideManualForm() { document.getElementById('manual-form').style.display = 'none'; }

function setManualType(type) {
  document.getElementById('mp-lp-form').style.display = type === 'lp' ? '' : 'none';
  document.getElementById('mp-hedge-form').style.display = type === 'hedge' ? '' : 'none';
  document.getElementById('mp-type-lp').classList.toggle('active', type === 'lp');
  document.getElementById('mp-type-hedge').classList.toggle('active', type === 'hedge');
}

async function validateManualToken(input, statusId) {
  var sym = input.value.trim().toUpperCase();
  var el = document.getElementById(statusId);
  if (!sym) { el.innerHTML = ''; return; }
  try {
    var resp = await fetch('/api/validate-token/' + encodeURIComponent(sym));
    var data = await resp.json();
    if (data.valid) {
      el.innerHTML = '<span style="color:#51cf66;font-size:11px"> ✓ $' + data.price_usd.toLocaleString(undefined,{maximumFractionDigits:2}) + '</span>';
    } else if (data.known) {
      el.innerHTML = '<span style="color:#ffa94d;font-size:11px">' + li('clock',12,'#ffa94d') + ' rate limited</span>';
    } else {
      el.innerHTML = '<span style="color:#ffa94d;font-size:11px">' + li('alert-triangle',12,'#ffa94d') + ' unknown</span>';
    }
  } catch(e) { el.innerHTML = ''; }
}

async function submitManualPosition() {
  var msgEl = document.getElementById('mp-msg');
  
  // Required fields validation
  var requiredFields = [
    {id: 'mp-token0', label: 'Token0'},
    {id: 'mp-token1', label: 'Token1'},
    {id: 'mp-fee', label: 'Fee Tier'},
    {id: 'mp-amount0', label: 'Amount Token0'},
    {id: 'mp-amount1', label: 'Amount Token1'},
    {id: 'mp-range-low', label: 'Range Low'},
    {id: 'mp-range-high', label: 'Range High'},
  ];
  var missing = [];
  requiredFields.forEach(function(f) {
    var el = document.getElementById(f.id);
    var val = el.value.trim();
    if (!val || (el.type === 'number' && (isNaN(parseFloat(val)) || parseFloat(val) === 0))) {
      el.style.borderColor = '#ff6b6b';
      missing.push(f.label);
    } else {
      el.style.borderColor = '#333';
    }
  });
  if (missing.length > 0) {
    showSettingsMsg(msgEl, 'Required fields missing: ' + missing.join(', '), true);
    return;
  }
  
  var data = {
    chain: document.getElementById('mp-chain').value.trim(),
    protocol: document.getElementById('mp-protocol').value.trim(),
    token0: document.getElementById('mp-token0').value.trim().toUpperCase(),
    token1: document.getElementById('mp-token1').value.trim().toUpperCase(),
    fee_tier: parseFloat(document.getElementById('mp-fee').value) || 0,
    amount0: parseFloat(document.getElementById('mp-amount0').value) || 0,
    amount1: parseFloat(document.getElementById('mp-amount1').value) || 0,
    range_lower: parseFloat(document.getElementById('mp-range-low').value) || 0,
    range_upper: parseFloat(document.getElementById('mp-range-high').value) || 0,
    price0_override: document.getElementById('mp-price0').value ? parseFloat(document.getElementById('mp-price0').value) : null,
    price1_override: document.getElementById('mp-price1').value ? parseFloat(document.getElementById('mp-price1').value) : null,
    notes: document.getElementById('mp-notes').value.trim(),
  };
  if (data.range_lower >= data.range_upper) {
    document.getElementById('mp-range-low').style.borderColor = '#ff6b6b';
    document.getElementById('mp-range-high').style.borderColor = '#ff6b6b';
    showSettingsMsg(msgEl, 'Range low must be less than range high', true); return;
  }
  try {
    var resp = await fetch('/api/manual-positions', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(data)
    });
    var result = await resp.json();
    if (resp.ok) {
      var msg = 'Position saved ($' + (result.value_usd||0).toLocaleString(undefined,{maximumFractionDigits:0}) + ')';
      if (result.warnings && result.warnings.length) msg += ' — ' + result.warnings.join(', ');
      showSettingsMsg(msgEl, msg, false);
      hideManualForm();
      loadManualPositions();
      // Clear form
      ['mp-chain','mp-protocol','mp-token0','mp-token1','mp-fee','mp-amount0','mp-amount1','mp-range-low','mp-range-high','mp-price0','mp-price1','mp-notes'].forEach(function(id) { document.getElementById(id).value = ''; });
      document.getElementById('mp-t0-status').innerHTML = '';
      document.getElementById('mp-t1-status').innerHTML = '';
    } else {
      showSettingsMsg(msgEl, result.error || 'Error', true);
      if (result.need_prices) {
        document.getElementById('mp-price0').style.borderColor = '#ff6b6b';
        document.getElementById('mp-price1').style.borderColor = '#ff6b6b';
      }
    }
  } catch(e) { showSettingsMsg(msgEl, 'Network error', true); }
}

async function loadManualPositions() {
  try {
    var resp = await fetch('/api/manual-positions');
    var positions = await resp.json();
    var resp2 = await fetch('/api/manual-hedges');
    var hedges = await resp2.json();
    renderManualPositions(positions);
    renderManualHedges(hedges);
  } catch(e) {}
}

function renderManualPositions(positions) {
  var el = document.getElementById('pf-manual-positions');
  if (!positions || !positions.length) {
    el.innerHTML = '<div style="color:#8892b0;font-size:13px;padding:10px">No manual positions. Click "Add Position" to track an LP on an unsupported chain.</div>';
    return;
  }
  el.innerHTML = positions.map(function(pos) {
    var pricePct = pos.range_upper > pos.range_lower ? ((pos.current_price - pos.range_lower) / (pos.range_upper - pos.range_lower)) * 100 : 50;
    var rangeBadge = pos.in_range
      ? '<span class="status-badge status-in-range">' + li('check-circle',14,'#51cf66') + ' IN RANGE</span>'
      : '<span class="status-badge status-out-range">' + li('x-circle',14,'#ff6b6b') + ' OUT OF RANGE</span>';
    var totalFees = (pos.fees_uncollected_usd || 0) + (pos.fees_collected_usd || 0);
    return '<div class="lp-card">' +
      '<div class="lp-card-header">' +
        '<div>' +
          '<div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">' +
            '<span class="chain-badge" style="background:#1a2a1a;color:#51cf66">' + esc(pos.chain) + '</span>' +
            rangeBadge +
            '<span class="wallet-badge">'+li('pencil',12)+' Manual</span>' +
          '</div>' +
          '<div style="color:#e0e0e0;font-size:16px;font-weight:700">' + tokenIcon(pos.token0) + ' ' + esc(pos.token0) + '/' + tokenIcon(pos.token1) + ' ' + esc(pos.token1) + '</div>' +
          '<div style="color:#8892b0;font-size:12px">' + esc(pos.protocol || '') + ' • ' + (pos.fee_tier||0) + '% fee' + (pos.notes ? ' • ' + esc(pos.notes) : '') + '</div>' +
        '</div>' +
        '<div style="text-align:right">' +
          '<div style="color:#e0e0e0;font-size:18px;font-weight:700">' + m(fmt2(pos.value_usd || 0)) + '</div>' +
          '<div style="color:#8892b0;font-size:11px">Value</div>' +
        '</div>' +
      '</div>' +
      '<div class="lp-range-bar">' +
        '<div style="display:flex;justify-content:space-between;font-size:11px;color:#8892b0;margin-bottom:4px">' +
          '<span>Min: ' + fmtNum(pos.range_lower||0) + '</span>' +
          '<span style="color:#e0e0e0">Current: ' + fmtNum(pos.current_price||0) + '</span>' +
          '<span>Max: ' + fmtNum(pos.range_upper||0) + '</span>' +
        '</div>' +
        '<div class="range-track"><div class="range-fill"></div><div class="range-needle" style="left:' + Math.max(0,Math.min(100,pricePct)) + '%"></div></div>' +
      '</div>' +
      '<div class="lp-tokens-grid">' +
        '<div class="lp-token-card"><div style="color:#8892b0;font-size:12px">' + esc(pos.token0) + '</div><div style="color:#e0e0e0;font-weight:600">' + m(fmtNum(pos.amount0||0, 4)) + '</div></div>' +
        '<div class="lp-token-card"><div style="color:#8892b0;font-size:12px">' + esc(pos.token1) + '</div><div style="color:#e0e0e0;font-weight:600">' + m(fmtNum(pos.amount1||0, 4)) + '</div></div>' +
      '</div>' +
      (totalFees > 0.01 ? '<div style="color:#51cf66;font-size:13px;font-weight:600;margin-bottom:8px">Fees: ' + m(fmt2(totalFees)) + '</div>' : '') +
      '<div style="display:flex;gap:6px">' +
        '<button class="lev-btn" style="font-size:11px;padding:3px 10px" onclick="updateManualFees(' + pos.id + ')">Update Fees</button>' +
        '<button class="lev-btn" style="font-size:11px;padding:3px 10px;color:#ff6b6b;border-color:#ff6b6b" onclick="closeManualPosition(' + pos.id + ')">Close Position</button>' +
      '</div>' +
    '</div>';
  }).join('');
}

async function updateManualFees(posId) {
  var uncollected = prompt('Enter current uncollected fees (USD):');
  var collected = prompt('Enter total collected fees (USD):');
  if (uncollected === null && collected === null) return;
  var data = {};
  if (uncollected !== null) data.fees_uncollected_usd = parseFloat(uncollected) || 0;
  if (collected !== null) data.fees_collected_usd = parseFloat(collected) || 0;
  await fetch('/api/manual-positions/' + posId, {
    method: 'PUT', headers: {'Content-Type':'application/json'},
    body: JSON.stringify(data)
  });
  loadManualPositions();
}

async function closeManualPosition(posId) {
  if (!confirm('Close this position? It will be marked as inactive and appear in closed positions history.')) return;
  await fetch('/api/manual-positions/' + posId, {
    method: 'PUT', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action: 'close'})
  });
  loadManualPositions();
}

// ===== MANUAL HEDGES =====
async function validateHedgeMarket() {
  var val = document.getElementById('mh-market').value.trim();
  var sym = val.split('/')[0].toUpperCase();
  if (!sym) { document.getElementById('mh-mkt-status').innerHTML = ''; return; }
  try {
    var resp = await fetch('/api/validate-token/' + encodeURIComponent(sym));
    var data = await resp.json();
    document.getElementById('mh-mkt-status').innerHTML = data.valid
      ? '<span style="color:#51cf66;font-size:11px"> ✓ $' + data.price_usd.toLocaleString(undefined,{maximumFractionDigits:2}) + '</span>'
      : '<span style="color:#ffa94d;font-size:11px">' + li('alert-triangle',12,'#ffa94d') + ' unknown</span>';
  } catch(e) { document.getElementById('mh-mkt-status').innerHTML = ''; }
}

async function submitManualHedge() {
  var msgEl = document.getElementById('mp-msg');
  var data = {
    exchange: document.getElementById('mh-exchange').value.trim(),
    market: document.getElementById('mh-market').value.trim().toUpperCase(),
    direction: document.getElementById('mh-direction').value,
    margin_usd: parseFloat(document.getElementById('mh-margin').value) || 0,
    leverage: parseFloat(document.getElementById('mh-leverage').value) || 1,
    entry_price: document.getElementById('mh-entry').value ? parseFloat(document.getElementById('mh-entry').value) : null,
    stop_loss_price: document.getElementById('mh-sl').value ? parseFloat(document.getElementById('mh-sl').value) : null,
    take_profit_price: document.getElementById('mh-tp').value ? parseFloat(document.getElementById('mh-tp').value) : null,
    notes: document.getElementById('mh-notes').value.trim(),
  };
  if (!data.market || !data.margin_usd) {
    showSettingsMsg(msgEl, 'Market and margin are required', true); return;
  }
  try {
    var resp = await fetch('/api/manual-hedges', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(data)
    });
    var result = await resp.json();
    if (resp.ok) {
      showSettingsMsg(msgEl, 'Hedge saved — size $' + (result.size_usd||0).toLocaleString(undefined,{maximumFractionDigits:0}) + ' @ ' + (result.entry_price||0).toLocaleString(undefined,{maximumFractionDigits:2}), false);
      hideManualForm();
      loadManualPositions();
      ['mh-exchange','mh-market','mh-margin','mh-leverage','mh-entry','mh-sl','mh-tp','mh-notes'].forEach(function(id) { document.getElementById(id).value = ''; });
    } else {
      showSettingsMsg(msgEl, result.error || 'Error', true);
    }
  } catch(e) { showSettingsMsg(msgEl, 'Network error', true); }
}

function renderManualHedges(hedges) {
  var container = document.getElementById('pf-manual-positions');
  if (!hedges || !hedges.length) return;
  // Append hedge cards after LP cards
  var html = hedges.map(function(h) {
    var dirBadge = h.direction === 'long'
      ? '<span class="status-badge status-in-range">'+li('trending-up',14,'#51cf66')+' LONG</span>'
      : '<span class="status-badge status-out-range">'+li('trending-down',14,'#ff6b6b')+' SHORT</span>';
    var pnlCls = (h.pnl_usd || 0) >= 0 ? 'positive' : 'negative';
    var pnlSign = (h.pnl_usd || 0) >= 0 ? '+' : '';
    return '<div class="lp-card">' +
      '<div class="lp-card-header">' +
        '<div>' +
          '<div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">' +
            dirBadge +
            '<span class="wallet-badge">'+li('pencil',12)+' ' + esc(h.exchange || 'Manual') + '</span>' +
          '</div>' +
          '<div style="color:#e0e0e0;font-size:16px;font-weight:700">' + tokenIcon(h.market.split('/')[0]) + ' ' + esc(h.market) + '</div>' +
          '<div style="color:#8892b0;font-size:12px">' + (h.leverage||1) + 'x leverage' + (h.notes ? ' • ' + esc(h.notes) : '') + '</div>' +
        '</div>' +
        '<div style="text-align:right">' +
          '<div style="color:#e0e0e0;font-size:18px;font-weight:700">' + m(fmt2(h.size_usd || 0)) + '</div>' +
          '<div style="color:#8892b0;font-size:11px">Size</div>' +
        '</div>' +
      '</div>' +
      '<div class="lp-tokens-grid">' +
        '<div class="lp-token-card"><div style="color:#8892b0;font-size:11px">Entry</div><div style="color:#e0e0e0;font-weight:600">' + m(fmtNum(h.entry_price||0)) + '</div></div>' +
        '<div class="lp-token-card"><div style="color:#8892b0;font-size:11px">Current</div><div style="color:#e0e0e0;font-weight:600">' + m(fmtNum(h.current_price||0)) + '</div></div>' +
        '<div class="lp-token-card"><div style="color:#8892b0;font-size:11px">Margin</div><div style="color:#e0e0e0;font-weight:600">' + m(fmt2(h.margin_usd||0)) + '</div></div>' +
        '<div class="lp-token-card"><div style="color:#8892b0;font-size:11px">Liq. Price</div><div style="color:#ff6b6b;font-weight:600">' + m(fmtNum(h.liquidation_price||0)) + '</div></div>' +
      '</div>' +
      // PnL bar
      '<div style="padding:8px 12px;background:' + ((h.pnl_usd||0) >= 0 ? '#0a1a0a' : '#1a0a0a') + ';border:1px solid ' + ((h.pnl_usd||0) >= 0 ? '#1a3a2a' : '#3a1a1a') + ';border-radius:8px;display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">' +
        '<span style="color:#8892b0;font-size:12px">PnL</span>' +
        '<span class="' + pnlCls + '" style="font-weight:700">' + m(pnlSign + fmt2(h.pnl_usd||0)) + ' (' + pnlSign + fmtNum(h.pnl_pct||0,1) + '%)</span>' +
      '</div>' +
      // Price range bar
      (function() {
        var ep = h.entry_price || 0, cp = h.current_price || 0, lp = h.liquidation_price || 0;
        if (!ep || !cp) return '';
        var pts = [ep, cp, lp].filter(function(p){return p > 0;});
        if (h.stop_loss_price) pts.push(h.stop_loss_price);
        if (h.take_profit_price) pts.push(h.take_profit_price);
        var mn = Math.min.apply(null, pts) * 0.95, mx = Math.max.apply(null, pts) * 1.05;
        var pOf = function(p) { return ((p - mn) / (mx - mn)) * 100; };
        var isLong = h.direction === 'long';
        var labels = [
          {label:'Liq',price:lp,color:'#ff6b6b'},
          {label:'Entry',price:ep,color:'#8892b0'},
          {label:'Current',price:cp,color:'#e0e0e0'}
        ].sort(function(a,b){return a.price-b.price;});
        var markers = '';
        if (h.stop_loss_price) markers += '<div class="gmx-price-marker gmx-sl" style="left:'+pOf(h.stop_loss_price)+'%"><div class="gmx-marker-label">SL</div></div>';
        if (h.take_profit_price) markers += '<div class="gmx-price-marker gmx-tp" style="left:'+pOf(h.take_profit_price)+'%"><div class="gmx-marker-label">TP</div></div>';
        return '<div style="margin-bottom:8px">' +
          '<div style="display:flex;justify-content:space-between;font-size:11px;color:#8892b0;margin-bottom:4px">' +
            '<span style="color:'+labels[0].color+'">'+labels[0].label+': '+fmtNum(labels[0].price)+'</span>' +
            '<span style="color:'+labels[1].color+'">'+labels[1].label+': '+fmtNum(labels[1].price)+'</span>' +
            '<span style="color:'+labels[2].color+'">'+labels[2].label+': '+fmtNum(labels[2].price)+'</span>' +
          '</div>' +
          '<div class="range-track" style="position:relative;height:8px">' +
            '<div style="position:absolute;inset:0;background:linear-gradient(to right,'+(isLong?'#ff6b6b,#333,#51cf66':'#51cf66,#333,#ff6b6b')+');border-radius:4px"></div>' +
            '<div class="gmx-price-marker gmx-liq" style="left:'+pOf(lp)+'%"><div class="gmx-marker-label" style="color:#ff6b6b">'+li('skull',14,'#ff6b6b')+'</div></div>' +
            '<div class="gmx-price-marker gmx-entry" style="left:'+pOf(ep)+'%"><div class="gmx-marker-label">Entry</div></div>' +
            '<div class="range-needle" style="left:'+pOf(cp)+'%;top:-3px;height:14px"></div>' +
            '<div class="gmx-price-marker" style="left:'+pOf(cp)+'%;top:-20px"><div class="gmx-marker-label" style="color:#fff;font-weight:700">▼</div></div>' +
            markers +
          '</div></div>';
      })() +
      '<div style="display:flex;gap:6px">' +
        '<button class="lev-btn" style="font-size:11px;padding:3px 10px;color:#ff6b6b;border-color:#ff6b6b" onclick="closeManualHedge(' + h.id + ')">Close Position</button>' +
      '</div>' +
    '</div>';
  }).join('');
  container.innerHTML += html;
}

async function closeManualHedge(hedgeId) {
  if (!confirm('Close this hedge? Final PnL will be recorded.')) return;
  await fetch('/api/manual-hedges/' + hedgeId, {
    method: 'PUT', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action: 'close'})
  });
  loadManualPositions();
}

// ===== AI CONFIG =====
async function loadAIConfig() {
  try {
    var resp = await fetch('/api/ai/config');
    var config = await resp.json();
    document.getElementById('ai-provider').value = config.provider || 'openai';
    document.getElementById('ai-model').value = config.model || '';
    document.getElementById('ai-schedule').value = config.schedule_utc_hour || 8;
    document.getElementById('ai-auto-enabled').value = config.auto_enabled ? 'true' : 'false';
    document.getElementById('ai-custom-prompt').value = config.custom_system_prompt || '';
    var strats = config.strategies || {};
    document.getElementById('ai-strat-bull').value = strats.bull || '';
    document.getElementById('ai-strat-bear').value = strats.bear || '';
    document.getElementById('ai-strat-sideways').value = strats.sideways || '';
  } catch(e) {}
}

async function saveAIConfig() {
  var config = {
    provider: document.getElementById('ai-provider').value,
    model: document.getElementById('ai-model').value,
    schedule_utc_hour: parseInt(document.getElementById('ai-schedule').value) || 8,
    auto_enabled: document.getElementById('ai-auto-enabled').value === 'true',
    custom_system_prompt: document.getElementById('ai-custom-prompt').value,
    strategies: {
      bull: document.getElementById('ai-strat-bull').value,
      bear: document.getElementById('ai-strat-bear').value,
      sideways: document.getElementById('ai-strat-sideways').value,
    }
  };
  var msgEl = document.getElementById('ai-config-msg');
  try {
    var resp = await fetch('/api/ai/config', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(config)
    });
    if (resp.ok) showSettingsMsg(msgEl, 'AI config saved', false);
    else showSettingsMsg(msgEl, 'Error saving', true);
  } catch(e) { showSettingsMsg(msgEl, 'Network error', true); }
}
