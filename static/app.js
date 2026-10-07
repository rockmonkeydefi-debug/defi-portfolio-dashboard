/* ===== APP ROOT ===== */

const PHASE1_TABS = {
  dashboard:   'Dashboard',
  portfolio:   'Portfolio',
  maxfi:       'MaxFi',
  performance: 'Performance',
  marketdata:  'Market Data',
  aibrief:     'AI Brief',
  archive:     'Archive',
  checklist:   'MaxFi Checklist',
  pl:          'P/L',
  actionplan:  'Action Plan',
  scout:       'Scout',
  trends:      'Trends',
  spot:        'Spot',
  perps:       'Perps',
  settings:    'Settings',
  'tt-scanner':   'Scanner',
  'tt-watchlist': 'Watchlist',
  'tt-validator': 'Validator',
  'tt-journal':   'Journal',
  'tt-reports':   'Reports',
  'tt-concepts':  'Concepts',
  'tt-quiz':      'Quiz',
  'tt-settings':  'Trading Settings',
};

// How often the nav's Spot and Perps badges re-read the attention counts.
const TRADE_ATTENTION_POLL_MS = 10 * 60 * 1000;

// Landing 14: how often an open page asks GET /api/build which frontend
// build the server serves. It also asks on load, on focus, when the tab
// becomes visible and when the page is restored by Back / Forward.
const BUILD_CHECK_MS = 5 * 60 * 1000;
// Height of the narrow-width top bar (.tv-topbar in static/style.css); the
// new-build notice sticks just under it.
const TOPBAR_HEIGHT_PX = 48;

// The frontend build this page loaded: the playbook-build meta that
// templates/index.html fills from the same value as every ?v= (Landing 14).
function readPageBuild() {
  const m = document.querySelector('meta[name="playbook-build"]');
  return (m && m.getAttribute('content')) || '';
}

// Landing 14: shown at the top of the page column while the server serves a
// newer frontend build than this page loaded. An open page keeps running
// the scripts it loaded until it is reloaded (switching tabs and Refresh
// only re-read data), so this is the only sign that a deploy has changed
// the page. It never reloads by itself: open edits would be lost.
function BuildNotice({ top, pageBuild, liveBuild }) {
  return React.createElement('div', {
    role: 'status',
    'data-build-notice': '',
    title: 'Loaded build ' + pageBuild + ' · live build ' + liveBuild,
    style: {
      position: 'sticky', top, zIndex: 90,
      display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '8px 16px',
      padding: '10px 16px', background: 'var(--panel3)', borderBottom: '2px solid var(--accent)',
      color: 'var(--text)', fontSize: 13, lineHeight: 1.4,
    },
  },
    React.createElement('span', { style: { flex: '1 1 260px', minWidth: 0 } },
      React.createElement('strong', null, 'A new version of the Playbook is live. '),
      'Save any open edits, then reload to use it.'),
    React.createElement('button', {
      type: 'button', className: 'tv-btn primary', style: { fontSize: 13, fontWeight: 600 },
      onClick: () => window.location.reload(),
    }, 'Reload')
  );
}

function PlaceholderScreen({ label }) {
  return React.createElement('div', {
    style: {
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: 320,
      gap: 12,
      color: 'var(--text4)',
    }
  },
    React.createElement('div', { style: { fontSize: 32 } }, '🚧'),
    React.createElement('div', { className: 'tv-label' }, label),
    React.createElement('div', { style: { fontSize: 13, color: 'var(--text4)' } }, 'Coming in next phase')
  );
}

function App() {
  const [activeTab, setActiveTab] = React.useState(() => {
    const stored = localStorage.getItem('activeTab');
    if (!stored || (typeof window.isHiddenTab === 'function' && window.isHiddenTab(stored))) {
      localStorage.setItem('activeTab', 'dashboard');
      return 'dashboard';
    }
    // The old Spot Positions page (portfolio tab, spot sub-tab) is now the
    // Spot page (HANDOFF_spot_perps_rebuild.md 3.2).
    if (stored === 'portfolio' && localStorage.getItem('portfolioSubTab') === 'spot') {
      localStorage.setItem('activeTab', 'spot');
      return 'spot';
    }
    // Trade Log is retired (Landing 3b); its old saved tab opens Perps.
    if (stored === 'tradelog') {
      localStorage.setItem('activeTab', 'perps');
      return 'perps';
    }
    return stored;
  });
  const [hideValues, setHideValues] = React.useState(() => {
    return localStorage.getItem('hideValues') === 'true';
  });
  const [refreshing, setRefreshing] = React.useState(false);
  const [refreshTrigger, setRefreshTrigger] = React.useState(0);
  const [tradeAttention, setTradeAttention] = React.useState(null);
  const [pageBuild] = React.useState(readPageBuild);
  const [liveBuild, setLiveBuild] = React.useState(null);
  const docked = navUseDocked();

  const [portfolioSubTab, setPortfolioSubTab] = React.useState(() => {
    const stored = localStorage.getItem('portfolioSubTab') || 'tokens';
    if (stored === 'spot') {
      // Spot moved to its own page (see activeTab above).
      localStorage.setItem('portfolioSubTab', 'tokens');
      return 'tokens';
    }
    return stored;
  });
  const [archiveSubTab, setArchiveSubTab] = React.useState(() => {
    return localStorage.getItem('archiveSubTab') || 'lp';
  });

  function handleTabChange(tab) {
    if (tab === 'tradelog') tab = 'perps';   // Trade Log is retired (Landing 3b)
    setActiveTab(tab);
    localStorage.setItem('activeTab', tab);
  }

  function handlePortfolioSubTabChange(tab) {
    if (tab === 'spot') { handleTabChange('spot'); return; }   // Spot is its own page now
    setPortfolioSubTab(tab);
    localStorage.setItem('portfolioSubTab', tab);
  }

  function handleArchiveSubTabChange(tab) {
    setArchiveSubTab(tab);
    localStorage.setItem('archiveSubTab', tab);
  }

  function handleToggleHide() {
    setHideValues(prev => {
      const next = !prev;
      localStorage.setItem('hideValues', String(next));
      api('/api/settings/display', {
        method: 'POST',
        body: JSON.stringify({ hide_values: next }),
      }).catch(() => {});
      return next;
    });
  }

  React.useEffect(() => {
    function onPlaybookRefresh() { setRefreshTrigger(t => t + 1); }
    window.addEventListener('playbook-refresh', onPlaybookRefresh);
    return () => window.removeEventListener('playbook-refresh', onPlaybookRefresh);
  }, []);

  // Spot and Perps badges (Landing 3a; Perps changed in 8d): {spot: exit
  // signals, perpOpen: open perp positions, perpNeedsStop: open perp trades
  // needing a stop}, counted by tradesNavCounts (utils.js) from GET
  // /api/trading/trades, read on load, on every refresh and every
  // TRADE_ATTENTION_POLL_MS, and updated by the Perps page's and the
  // Dashboard's 'trades-attention' events (the same shape) after each of
  // their reads. Any other detail is ignored.
  React.useEffect(() => {
    let alive = true;
    function readAttention() {
      api('/api/trading/trades').then(d => {
        const counts = tradesNavCounts(d);
        if (alive && counts) setTradeAttention(counts);
      }).catch(() => {});
    }
    function onTradesAttention(e) {
      const v = e && e.detail;
      if (alive && v && typeof v === 'object' && typeof v.spot === 'number'
          && typeof v.perpOpen === 'number' && typeof v.perpNeedsStop === 'number') {
        setTradeAttention({ spot: v.spot, perpOpen: v.perpOpen, perpNeedsStop: v.perpNeedsStop });
      }
    }
    readAttention();
    const id = setInterval(readAttention, TRADE_ATTENTION_POLL_MS);
    window.addEventListener('trades-attention', onTradesAttention);
    return () => {
      alive = false;
      clearInterval(id);
      window.removeEventListener('trades-attention', onTradesAttention);
    };
  }, [refreshTrigger]);

  // New-build check (Landing 14): asks GET /api/build which frontend build
  // the server serves and keeps the answer; BuildNotice shows while it
  // differs from pageBuild (and goes again if the server goes back to it).
  // A failed check (offline, mid-deploy, logged out) changes nothing; the
  // next one tries again. Bare fetch, not api(): a 401 here must not
  // redirect to the login page.
  React.useEffect(() => {
    if (!pageBuild) return undefined;
    let alive = true;
    let busy = false;
    async function check() {
      if (busy) return;
      busy = true;
      try {
        const res = await fetch('/api/build', { cache: 'no-store' });
        if (!res.ok) return;
        const d = await res.json();
        if (alive && d && typeof d.build === 'string' && d.build) setLiveBuild(d.build);
      } catch (e) {
        // try again at the next check
      } finally {
        busy = false;
      }
    }
    function onVisible() { if (document.visibilityState === 'visible') check(); }
    function onPageShow(e) { if (e.persisted) check(); }
    check();
    const id = setInterval(check, BUILD_CHECK_MS);
    window.addEventListener('focus', check);
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('pageshow', onPageShow);
    return () => {
      alive = false;
      clearInterval(id);
      window.removeEventListener('focus', check);
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('pageshow', onPageShow);
    };
  }, [pageBuild]);

  async function handleRefresh() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await api('/api/portfolio?refresh=true');
      setRefreshTrigger(t => t + 1);
    } catch (e) {
      console.error('Refresh failed:', e);
    } finally {
      setRefreshing(false);
    }
  }

  function renderContent() {
    const label = PHASE1_TABS[activeTab] || activeTab;

    if (typeof window.DashboardScreen !== 'undefined' && activeTab === 'dashboard')
      return React.createElement(window.DashboardScreen, { hideValues, refreshTrigger, setActiveTab: handleTabChange, setPortfolioSubTab: handlePortfolioSubTabChange });
    if (typeof window.PortfolioScreen !== 'undefined' && activeTab === 'portfolio')
      return React.createElement(window.PortfolioScreen, { hideValues, portfolioSubTab, refreshTrigger, setActiveTab: handleTabChange });
    if (typeof window.MaxFiScreen !== 'undefined' && activeTab === 'maxfi')
      return React.createElement(window.MaxFiScreen, { hideValues });
    if (typeof window.ArchiveScreen !== 'undefined' && activeTab === 'archive')
      return React.createElement(window.ArchiveScreen, { hideValues, archiveSubTab });
    if (typeof window.PerformanceScreen !== 'undefined' && activeTab === 'performance')
      return React.createElement(window.PerformanceScreen, { hideValues });
    if (typeof window.MarketDataScreen !== 'undefined' && activeTab === 'marketdata')
      return React.createElement(window.MarketDataScreen, { hideValues, setActiveTab: handleTabChange });
    if (typeof window.AIBriefScreen !== 'undefined' && activeTab === 'aibrief')
      return React.createElement(window.AIBriefScreen, { hideValues });
    if (typeof window.SettingsScreen !== 'undefined' && activeTab === 'settings')
      return React.createElement(window.SettingsScreen, { hideValues, setHideValues });
    if (typeof window.ChecklistScreen !== 'undefined' && activeTab === 'checklist')
      return React.createElement(window.ChecklistScreen);
    if (typeof window.PLScreen !== 'undefined' && activeTab === 'pl')
      return React.createElement(window.PLScreen);
    if (typeof window.ActionPlanScreen !== 'undefined' && activeTab === 'actionplan')
      return React.createElement(window.ActionPlanScreen);
    if (typeof window.ScoutScreen !== 'undefined' && activeTab === 'scout')
      return React.createElement(window.ScoutScreen);
    if (typeof window.TrendsScreen !== 'undefined' && activeTab === 'trends')
      return React.createElement(window.TrendsScreen);
    // Spot keeps the error boundary it had inside the Portfolio screen, so a
    // crashed tab shows an inline panel instead of blanking the app.
    if (typeof window.SpotPnlScreen !== 'undefined' && activeTab === 'spot')
      return React.createElement(window.ErrorBoundary || React.Fragment, null,
        React.createElement(window.SpotPnlScreen, { hideValues, refreshTrigger, setActiveTab: handleTabChange }));
    if (typeof window.PerpsScreen !== 'undefined' && activeTab === 'perps')
      return React.createElement(window.ErrorBoundary || React.Fragment, null,
        React.createElement(window.PerpsScreen, { hideValues, refreshTrigger }));

    // Trading Tools screens
    if (activeTab.startsWith('tt-')) {
      const screenMap = {
        'tt-scanner':   window.TriageScreen,
        'tt-watchlist': window.ScannerScreen,
        'tt-validator': window.ValidatorScreen,
        'tt-journal':   window.JournalScreen,
        'tt-reports':   window.ReportsScreen,
        'tt-concepts':  window.ConceptsScreen,
        'tt-quiz':      window.QuizScreen,
        'tt-settings':  window.TradingSettingsScreen,
      };
      const Screen = screenMap[activeTab];
      if (Screen) return React.createElement(Screen, { hideValues, onSwitchTab: handleTabChange });
    }

    return React.createElement(PlaceholderScreen, { label });
  }

  // Landing 9: the menu is a left sidebar (static/nav.js). .tv-shell puts it
  // beside the page at 1880px and wider; narrower, TVNav renders a top bar
  // and a drawer instead and the page column takes the full width.
  return React.createElement('div', { className: 'tv-frame tv-shell' },
    React.createElement(TVNav, {
      activeTab,
      onTabChange: handleTabChange,
      hideValues,
      onToggleHide: handleToggleHide,
      onRefresh: handleRefresh,
      refreshing,
      portfolioSubTab,
      onPortfolioSubTabChange: handlePortfolioSubTabChange,
      archiveSubTab,
      onArchiveSubTabChange: handleArchiveSubTabChange,
      tradeAttention,
    }),
    // Phase D follow-up 2: MaxFi's held grid needs >=1600px to fit its 17
    // columns without horizontal scroll on a wide viewport - tv-content--wide
    // (static/style.css) raises max-width for this tab. The Spot page uses it
    // too, so its Open positions grid has room; every other tab keeps the
    // base 1400px .tv-content layout unchanged. Perps uses it too (Landing 3a).
    React.createElement('div', { className: 'tv-main' },
      pageBuild && liveBuild && liveBuild !== pageBuild
        ? React.createElement(BuildNotice, { top: docked ? 0 : TOPBAR_HEIGHT_PX, pageBuild, liveBuild })
        : null,
      React.createElement('div', { className: 'tv-content' + (activeTab === 'maxfi' || activeTab === 'spot' || activeTab === 'perps' ? ' tv-content--wide' : '') },
        renderContent()
      )
    )
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App));
