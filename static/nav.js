/* ===== NAV COMPONENTS ===== */

const TT_SUBNAV_ITEMS = [
  { id: 'tt-scanner',  label: 'Setups' },
  { id: 'tt-watchlist', label: 'Watchlist' },
  { id: 'tt-validator', label: 'Validator' },
  { id: 'tt-journal',  label: 'Journal' },
  { id: 'tt-reports',  label: 'Reports' },
  { id: 'tt-concepts', label: 'Concepts' },
  { id: 'tt-quiz',     label: 'Quiz' },
  { id: 'tt-settings', label: 'Trading Settings' },
];

const ARCHIVE_SUBNAV_ITEMS = [
  { id: 'lp',                label: 'LP Positions' },
  { id: 'lending',           label: 'Borrow/Lend' },
  { id: 'spot',              label: 'Spot Trades' },
  { id: 'staking',           label: 'DeFi Protocols' },
  { id: 'permanently-hidden', label: 'Hidden From Archive' },
];

// Tabs hidden from the top nav. A tab listed here also hides its whole
// sub-id namespace (e.g. 'tt' hides 'tt-scanner', 'tt-settings', ...).
// Screens and render branches are left intact — unhide by removing the id.
//   aibrief — AI Brief, unused, hidden Sep 2026
//   tt      — Trading Tools, unused, hidden Sep 2026
var HIDDEN_TABS = ['aibrief', 'tt'];

function isHiddenTab(tabId) {
  if (!tabId) return false;
  for (var i = 0; i < HIDDEN_TABS.length; i++) {
    var h = HIDDEN_TABS[i];
    if (tabId === h || tabId.indexOf(h + '-') === 0) return true;
  }
  return false;
}

const TOP_NAV_ITEMS = [
  { id: 'dashboard',          label: 'Dashboard' },
  { id: 'sep-1' },
  { id: 'portfolio-spot',     label: 'Spot Positions',        tab: 'portfolio', sub: 'spot' },
  { id: 'portfolio-tokens',   label: 'Token Holdings',        tab: 'portfolio', sub: 'tokens' },
  { id: 'sep-2' },
  { id: 'maxfi',              label: 'MaxFi' },
  { id: 'portfolio-lp',       label: 'LP Positions',          tab: 'portfolio', sub: 'lp' },
  { id: 'portfolio-borrow',   label: 'Borrow/Lend Positions', tab: 'portfolio', sub: 'borrow' },
  { id: 'sep-3' },
  { id: 'portfolio-protocols', label: 'DeFi Protocols',       tab: 'portfolio', sub: 'protocols' },
  { id: 'sep-4' },
  { id: 'performance',        label: 'Performance' },
  { id: 'sep-5' },
  { id: 'marketdata',         label: 'Market Data' },
  // aibrief and tt remain listed so HIDDEN_TABS keeps governing them; while
  // hidden (current state) they render nothing. If ever unhidden they appear
  // inside the adjacent group without their own separators.
  { id: 'aibrief',            label: 'AI Brief' },
  { id: 'sep-6' },
  { id: 'archive',            label: 'Archive' },
  { id: 'tt',                 label: 'Trading Tools' },
  { id: 'sep-7' },
  { id: 'settings',           label: 'Settings' },
];

function TVNav({
  activeTab, onTabChange,
  hideValues, onToggleHide, onRefresh, refreshing,
  portfolioSubTab, onPortfolioSubTabChange,
  archiveSubTab, onArchiveSubTabChange,
}) {
  const isTT = activeTab && activeTab.startsWith('tt');
  const isArchive = activeTab === 'archive';

  return React.createElement(React.Fragment, null,
    React.createElement('nav', { className: 'tv-nav' },
      React.createElement('div', { style: { display: 'flex', alignItems: 'stretch', flex: 1 } },
        TOP_NAV_ITEMS.filter(item => !isHiddenTab(item.id)).map(item => {
          // Separator - label absent (checked first, before any id-based
          // assumption below; separator ids never collide with a hidden id).
          if (item.label === undefined) {
            return React.createElement('span', {
              key: item.id,
              style: { display: 'inline-block', width: 2, height: '55%',
                       alignSelf: 'center', background: 'rgba(255,255,255,0.28)',
                       margin: '0 10px', pointerEvents: 'none' },
            });
          }
          // Promoted portfolio item - sets activeTab AND portfolioSubTab.
          if (item.tab) {
            return React.createElement('button', {
              key: item.id,
              className: 'tv-nav-item' + ((activeTab === item.tab && portfolioSubTab === item.sub) ? ' active' : ''),
              onClick: () => {
                onTabChange(item.tab);
                onPortfolioSubTabChange && onPortfolioSubTabChange(item.sub);
              },
            }, item.label);
          }
          // Plain item - exactly today's behavior.
          return React.createElement('button', {
            key: item.id,
            className: 'tv-nav-item' + ((item.id === 'tt' ? isTT : activeTab === item.id) ? ' active' : ''),
            onClick: () => {
              if (item.id === 'tt') {
                onTabChange('tt-scanner');
              } else {
                onTabChange(item.id);
              }
            },
          }, item.label);
        })
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
window.ARCHIVE_SUBNAV_ITEMS = ARCHIVE_SUBNAV_ITEMS;
window.HIDDEN_TABS = HIDDEN_TABS;
window.isHiddenTab = isHiddenTab;
