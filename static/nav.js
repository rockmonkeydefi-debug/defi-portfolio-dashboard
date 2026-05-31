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

const PORTFOLIO_SUBNAV_ITEMS = [
  { id: 'spot',      label: 'Spot' },
  { id: 'tokens',    label: 'Token Holdings' },
  { id: 'lp',        label: 'LP Positions' },
  { id: 'borrow',    label: 'Borrow/Lend' },
  { id: 'protocols', label: 'DeFi Protocols' },
  { id: 'lptools',   label: 'LP Tools' },
];

const ARCHIVE_SUBNAV_ITEMS = [
  { id: 'lp',                label: 'LP Positions' },
  { id: 'lending',           label: 'Borrow/Lend' },
  { id: 'spot',              label: 'Spot Trades' },
  { id: 'staking',           label: 'DeFi Protocols' },
  { id: 'permanently-hidden', label: 'Hidden From Archive' },
];

const TOP_NAV_ITEMS = [
  { id: 'dashboard',   label: 'Dashboard' },
  { id: 'portfolio',   label: 'Portfolio' },
  { id: 'performance', label: 'Performance' },
  { id: 'marketdata',  label: 'Market Data' },
  { id: 'aibrief',     label: 'AI Brief' },
  { id: 'archive',     label: 'Archive' },
  { id: 'tt',          label: 'Trading Tools' },
  { id: 'settings',    label: 'Settings' },
];

function TVNav({
  activeTab, onTabChange,
  hideValues, onToggleHide, onRefresh, refreshing,
  portfolioSubTab, onPortfolioSubTabChange,
  archiveSubTab, onArchiveSubTabChange,
}) {
  const isTT = activeTab && activeTab.startsWith('tt');
  const isPortfolio = activeTab === 'portfolio';
  const isArchive = activeTab === 'archive';

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
        },
          React.createElement('span', {
            style: { display:'inline-block', animation: refreshing ? 'spin 0.8s linear infinite' : 'none', marginRight: 4 }
          }, '↻'),
          refreshing ? 'Refreshing…' : 'Refresh'
        ),
        React.createElement('a', {
          href: '/logout',
          className: 'tv-btn',
          style: { fontSize: 12, padding: '4px 10px', textDecoration: 'none' },
        }, 'Logout')
      )
    ),
    isPortfolio && onPortfolioSubTabChange && React.createElement('div', { className: 'tv-subnav' },
      PORTFOLIO_SUBNAV_ITEMS.map(item =>
        React.createElement('button', {
          key: item.id,
          className: 'tv-subnav-item' + (portfolioSubTab === item.id ? ' active' : ''),
          onClick: () => onPortfolioSubTabChange(item.id),
        }, item.label)
      )
    ),
    isArchive && onArchiveSubTabChange && React.createElement('div', { className: 'tv-subnav' },
      ARCHIVE_SUBNAV_ITEMS.map(item =>
        React.createElement('button', {
          key: item.id,
          className: 'tv-subnav-item' + (archiveSubTab === item.id ? ' active' : ''),
          onClick: () => onArchiveSubTabChange(item.id),
        }, item.label)
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
window.PORTFOLIO_SUBNAV_ITEMS = PORTFOLIO_SUBNAV_ITEMS;
window.ARCHIVE_SUBNAV_ITEMS = ARCHIVE_SUBNAV_ITEMS;
