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
  tradelog:    'Trade Log',
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
    return stored;
  });
  const [hideValues, setHideValues] = React.useState(() => {
    return localStorage.getItem('hideValues') === 'true';
  });
  const [refreshing, setRefreshing] = React.useState(false);
  const [refreshTrigger, setRefreshTrigger] = React.useState(0);
  const [tradeAttention, setTradeAttention] = React.useState(null);

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

  // Another screen asks to open a tab (Trade Log's spot notes pointer opens
  // the Spot page, Landing 2b): a 'playbook-open-tab' event with the tab id.
  React.useEffect(() => {
    function onOpenTab(e) { if (e && typeof e.detail === 'string' && e.detail) handleTabChange(e.detail); }
    window.addEventListener('playbook-open-tab', onOpenTab);
    return () => window.removeEventListener('playbook-open-tab', onOpenTab);
  }, []);

  React.useEffect(() => {
    function onPlaybookRefresh() { setRefreshTrigger(t => t + 1); }
    window.addEventListener('playbook-refresh', onPlaybookRefresh);
    return () => window.removeEventListener('playbook-refresh', onPlaybookRefresh);
  }, []);

  // Spot and Perps badges (Landing 3a): {spot: exit signals, perp: needs a
  // stop + needs review} from GET /api/trading/trades, read on load, on every
  // refresh and every TRADE_ATTENTION_POLL_MS, and updated by the Perps page's
  // and the Dashboard's 'trades-attention' events (detail {spot, perp}) after
  // each of their reads. A plain-number detail (Trade Log) is ignored.
  React.useEffect(() => {
    let alive = true;
    function readAttention() {
      api('/api/trading/trades').then(d => {
        const s = d && d.summary;
        if (alive && s && s.spot && s.perp) {
          setTradeAttention({ spot: Number(s.spot.exit_signal_count) || 0,
                              perp: (Number(s.perp.needs_stop_count) || 0) + (Number(s.perp.needs_review_count) || 0) });
        }
      }).catch(() => {});
    }
    function onTradesAttention(e) {
      const v = e && e.detail;
      if (alive && v && typeof v === 'object' && typeof v.spot === 'number' && typeof v.perp === 'number') {
        setTradeAttention({ spot: v.spot, perp: v.perp });
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
    if (typeof window.TradeLogScreen !== 'undefined' && activeTab === 'tradelog')
      return React.createElement(window.TradeLogScreen, { hideValues, refreshTrigger });

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

  return React.createElement('div', { className: 'tv-frame' },
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
    React.createElement('div', { className: 'tv-content' + (activeTab === 'maxfi' || activeTab === 'spot' || activeTab === 'perps' ? ' tv-content--wide' : '') },
      renderContent()
    )
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App));
