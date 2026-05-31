/* ===== APP ROOT ===== */

const PHASE1_TABS = {
  dashboard:   'Dashboard',
  portfolio:   'Portfolio',
  spotpnl:     'Spot P&L',
  performance: 'Performance',
  marketdata:  'Market Data',
  aibrief:     'AI Brief',
  settings:    'Settings',
  'tt-scanner':  'Scanner',
  'tt-validator':'Validator',
  'tt-journal':  'Journal',
  'tt-reports':  'Reports',
  'tt-concepts': 'Concepts',
  'tt-quiz':     'Quiz',
  'tt-settings': 'Trading Settings',
};

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
    return localStorage.getItem('activeTab') || 'dashboard';
  });
  const [hideValues, setHideValues] = React.useState(() => {
    return localStorage.getItem('hideValues') === 'true';
  });
  const [refreshing, setRefreshing] = React.useState(false);

  function handleTabChange(tab) {
    setActiveTab(tab);
    localStorage.setItem('activeTab', tab);
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

  async function handleRefresh() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await api('/api/portfolio?force_refresh=1');
    } catch (e) {
      console.error('Refresh failed:', e);
    } finally {
      setRefreshing(false);
    }
  }

  function renderContent() {
    // Phase 2+ screens will replace these placeholders
    const label = PHASE1_TABS[activeTab] || activeTab;

    if (typeof window.DashboardScreen !== 'undefined' && activeTab === 'dashboard')
      return React.createElement(window.DashboardScreen, { hideValues });
    if (typeof window.PortfolioScreen !== 'undefined' && activeTab === 'portfolio')
      return React.createElement(window.PortfolioScreen, { hideValues });
    if (typeof window.SpotPnlScreen !== 'undefined' && activeTab === 'spotpnl')
      return React.createElement(window.SpotPnlScreen, { hideValues });
    if (typeof window.PerformanceScreen !== 'undefined' && activeTab === 'performance')
      return React.createElement(window.PerformanceScreen, { hideValues });
    if (typeof window.MarketDataScreen !== 'undefined' && activeTab === 'marketdata')
      return React.createElement(window.MarketDataScreen, { hideValues });
    if (typeof window.AIBriefScreen !== 'undefined' && activeTab === 'aibrief')
      return React.createElement(window.AIBriefScreen, { hideValues });
    if (typeof window.SettingsScreen !== 'undefined' && activeTab === 'settings')
      return React.createElement(window.SettingsScreen, { hideValues });

    // Trading Tools screens
    if (activeTab.startsWith('tt-')) {
      const screenMap = {
        'tt-scanner':   window.ScannerScreen,
        'tt-validator': window.ValidatorScreen,
        'tt-journal':   window.JournalScreen,
        'tt-reports':   window.ReportsScreen,
        'tt-concepts':  window.ConceptsScreen,
        'tt-quiz':      window.QuizScreen,
        'tt-settings':  window.TradingSettingsScreen,
      };
      const Screen = screenMap[activeTab];
      if (Screen) return React.createElement(Screen, { hideValues });
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
    }),
    React.createElement('div', { className: 'tv-content' },
      renderContent()
    )
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App));
