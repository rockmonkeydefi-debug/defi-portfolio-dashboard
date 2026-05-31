/* ===== NAV COMPONENTS ===== */

const TT_SUBNAV_ITEMS = [
  { id: 'tt-scanner',  label: 'Scanner' },
  { id: 'tt-validator', label: 'Validator' },
  { id: 'tt-journal',  label: 'Journal' },
  { id: 'tt-reports',  label: 'Reports' },
  { id: 'tt-concepts', label: 'Concepts' },
  { id: 'tt-quiz',     label: 'Quiz' },
  { id: 'tt-settings', label: 'Trading Settings' },
];

const TOP_NAV_ITEMS = [
  { id: 'dashboard',   label: 'Dashboard' },
  { id: 'portfolio',   label: 'Portfolio' },
  { id: 'spotpnl',     label: 'Spot P&L' },
  { id: 'performance', label: 'Performance' },
  { id: 'marketdata',  label: 'Market Data' },
  { id: 'aibrief',     label: 'AI Brief' },
  { id: 'tt',          label: 'Trading Tools' },
  { id: 'settings',    label: 'Settings' },
];

function TVNav({ activeTab, onTabChange, hideValues, onToggleHide, onRefresh, refreshing }) {
  const isTT = activeTab && activeTab.startsWith('tt');

  return React.createElement(React.Fragment, null,
    React.createElement('nav', { className: 'tv-nav' },
      React.createElement('div', { style: { display: 'flex', alignItems: 'stretch', flex: 1 } },
        TOP_NAV_ITEMS.map(item =>
          React.createElement('button', {
            key: item.id,
            className: 'tv-nav-item' + ((item.id === 'tt' ? isTT : activeTab === item.id) ? ' active' : ''),
            onClick: () => {
              if (item.id === 'tt') {
                onTabChange('tt-scanner');
              } else {
                onTabChange(item.id);
              }
            },
          }, item.label)
        )
      ),
      React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, paddingRight: 8 } },
        React.createElement('button', {
          className: 'tv-btn',
          style: { fontSize: 12, padding: '4px 10px' },
          onClick: onToggleHide,
          title: hideValues ? 'Show values' : 'Hide values',
        }, hideValues ? '👁 Show' : '👁 Hide'),
        React.createElement('button', {
          className: 'tv-btn',
          style: { fontSize: 12, padding: '4px 10px' },
          onClick: onRefresh,
          disabled: refreshing,
        }, refreshing ? '↻ Refreshing…' : '↻ Refresh'),
        React.createElement('a', {
          href: '/logout',
          className: 'tv-btn',
          style: { fontSize: 12, padding: '4px 10px', textDecoration: 'none' },
        }, 'Logout')
      )
    ),
    isTT && React.createElement('div', { className: 'tv-subnav' },
      TT_SUBNAV_ITEMS.map(item =>
        React.createElement('button', {
          key: item.id,
          className: 'tv-subnav-item' + (activeTab === item.id ? ' active' : ''),
          onClick: () => onTabChange(item.id),
        }, item.label)
      )
    )
  );
}

window.TVNav = TVNav;
window.TT_SUBNAV_ITEMS = TT_SUBNAV_ITEMS;
window.TOP_NAV_ITEMS = TOP_NAV_ITEMS;
