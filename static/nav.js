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

// Every menu item (the catalogue). Spot sits right after Dashboard and
// replaces Spot Positions; Perps follows it (HANDOFF_spot_perps_rebuild.md
// 3.2, Landing 3a). Trade Log is retired (Landing 3b): its manual trades live
// on Perps -> Transactions, and an old saved 'tradelog' tab opens Perps
// (static/app.js). Items with `tab` + `sub` are portfolio sub-tabs promoted
// to the menu. Landing 9: the menu is a left sidebar; NAV_GROUPS below sets
// the sections and their order, so this list carries no separators.
const TOP_NAV_ITEMS = [
  { id: 'dashboard',          label: 'Dashboard' },
  { id: 'spot',               label: 'Spot' },
  { id: 'perps',              label: 'Perps' },
  { id: 'trends',             label: 'Trends' },
  { id: 'notes',              label: 'Notes' },
  { id: 'portfolio-tokens',   label: 'Token Holdings',        tab: 'portfolio', sub: 'tokens' },
  { id: 'portfolio-protocols', label: 'DeFi Protocols',       tab: 'portfolio', sub: 'protocols' },
  { id: 'portfolio-lp',       label: 'LP Positions',          tab: 'portfolio', sub: 'lp' },
  { id: 'portfolio-borrow',   label: 'Borrow/Lend Positions', tab: 'portfolio', sub: 'borrow' },
  { id: 'maxfi',              label: 'MaxFi' },
  { id: 'pl',                 label: 'P/L' },
  { id: 'scout',              label: 'Scout' },
  { id: 'actionplan',         label: 'Action Plan' },
  { id: 'checklist',          label: 'Checklist' },
  { id: 'performance',        label: 'Performance' },
  { id: 'marketdata',         label: 'Market Data' },
  // aibrief and tt stay listed so HIDDEN_TABS keeps governing them; while
  // hidden (current state) they render nothing.
  { id: 'aibrief',            label: 'AI Brief' },
  { id: 'archive',            label: 'Archive' },
  { id: 'tt',                 label: 'Trading Tools' },
  { id: 'settings',           label: 'Settings' },
];

/* ===== SIDEBAR MENU (Landing 9) =====
   At 1880px and wider the menu is a docked left sidebar: 232px expanded or
   a 68px rail (icons + badges), the choice remembered per browser
   (localStorage navRail). Narrower, a 48px top bar holds a menu button, the
   page name and the Spot / Perps badges, and the same sidebar opens as a
   drawer over the page (Escape or the backdrop closes it; focus returns to
   the menu button). Docking only at 1880px+ keeps every page at exactly the
   width it had under the old top bar (MaxFi's grid needs about 1600px), so
   no page layout depends on the menu. Sections fold from their heading
   (localStorage navFolded, every section open by default); a folded section
   still lists the page you are on and shows its badges on the heading.
   Archive's (and Trading Tools') sub-tabs nest under their item. Badges come
   from tradeAttention = tradesNavCounts(...) (static/utils.js): Spot = exit
   signals (warning colour); Perps = open positions, neutral, warning colour
   when a trade needs a stop, and a cyan dot (Landing 22) while an open trade
   still misses a part to count toward the risk gate (tags or a take-profit;
   the menu button's warning dot stays for warnings only). The 1880px figure
   is also in static/style.css (.tv-shell). Top-level names here start with
   nav / NAV_ (shared globals). */
const NAV_DOCK_QUERY = '(min-width: 1880px)';
const NAV_RAIL_KEY = 'navRail';
const NAV_FOLDED_KEY = 'navFolded';
const NAV_GROUPS = [
  { key: 'home',     heading: null,       ids: ['dashboard'] },
  { key: 'trading',  heading: 'Trading',  ids: ['spot', 'perps', 'trends', 'notes', 'tt'] },
  { key: 'holdings', heading: 'Holdings', ids: ['portfolio-tokens', 'portfolio-protocols', 'portfolio-lp', 'portfolio-borrow'] },
  { key: 'maxfi',    heading: 'MaxFi',    ids: ['maxfi', 'pl', 'scout', 'actionplan', 'checklist'] },
  { key: 'analysis', heading: 'Analysis', ids: ['performance', 'marketdata', 'aibrief'] },
  { key: 'admin',    heading: 'Admin',    ids: ['archive', 'settings'] },
];
// One stroke path per item, drawn in a 24x24 box.
const NAV_ICONS = {
  'dashboard': 'M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z',
  'spot': 'M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18M9.5 9.5c0-1.2 1.1-1.8 2.5-1.8s2.5.6 2.5 1.8-1.1 1.6-2.5 1.9-2.5.8-2.5 2 1.1 1.8 2.5 1.8 2.5-.6 2.5-1.8M12 6.3v1.4M12 16.3v1.4',
  'perps': 'M7 20V4M3 8l4-4 4 4M17 4v16M13 16l4 4 4-4',
  'trends': 'M3 17l6-6 4 4 8-8M15 7h6v6',
  'notes': 'M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h5',
  'tt': 'M14.5 4.5a4 4 0 0 0-5 5L4 15v5h5l5.5-5.5a4 4 0 0 0 5-5l-2.5 2.5-3-3z',
  'portfolio-tokens': 'M3 7h15a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3zM3 7l12-4v4M16 13.5h2',
  'portfolio-protocols': 'M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12v9M12 12L4 7.5',
  'portfolio-lp': 'M12 3c3.5 4.5 6 7.6 6 11a6 6 0 0 1-12 0c0-3.4 2.5-6.5 6-11z',
  'portfolio-borrow': 'M3 10l9-6 9 6M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18',
  'maxfi': 'M12 3l7.8 4.5v9L12 21l-7.8-4.5v-9zM12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6',
  'pl': 'M5 20V11M10 20V5M15 20v-7M20 20V8M3 20h18',
  'scout': 'M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14M16 16l5 5',
  'actionplan': 'M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01',
  'checklist': 'M4 4h16v16H4zM8 12l3 3 5-6',
  'performance': 'M3 20h18M5 16l4-5 4 3 6-8',
  'marketdata': 'M3 12h4l3-7 4 14 3-7h4',
  'aibrief': 'M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6',
  'archive': 'M3 5h18v4H3zM5 9v10h14V9M10 13h4',
  'settings': 'M12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1',
};
const NAV_PATH = {
  expand: 'M9 6l6 6-6 6', collapse: 'M15 6l-6 6 6 6', foldOpen: 'M6 9l6 6 6-6',
  menu: 'M4 6h16M4 12h16M4 18h16', close: 'M6 6l12 12M18 6L6 18',
  eye: 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6',
  refresh: 'M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7',
  logout: 'M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 16l-4-4 4-4M6 12h10',
};

function navReadLocal(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch (e) { return fallback; }
}
function navWriteLocal(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* storage blocked: the choice lasts this visit only */ }
}
function navReadFolded() {
  try {
    const a = JSON.parse(navReadLocal(NAV_FOLDED_KEY, '[]'));
    return Array.isArray(a) ? a.filter(k => typeof k === 'string') : [];
  } catch (e) { return []; }
}
function navIcon(d, size) {
  return React.createElement('svg', { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
    strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': 'true', focusable: 'false' },
    React.createElement('path', { d }));
}
// true at NAV_DOCK_QUERY widths; follows window resizes.
function navUseDocked() {
  const [docked, setDocked] = React.useState(() =>
    typeof window.matchMedia === 'function' && window.matchMedia(NAV_DOCK_QUERY).matches);
  React.useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const mq = window.matchMedia(NAV_DOCK_QUERY);
    const on = e => setDocked(!!e.matches);
    if (mq.addEventListener) mq.addEventListener('change', on); else mq.addListener(on);
    setDocked(mq.matches);
    return () => { if (mq.removeEventListener) mq.removeEventListener('change', on); else mq.removeListener(on); };
  }, []);
  return docked;
}

function TVNav({
  activeTab, onTabChange,
  hideValues, onToggleHide, onRefresh, refreshing,
  portfolioSubTab, onPortfolioSubTabChange,
  archiveSubTab, onArchiveSubTabChange,
  tradeAttention,
}) {
  const docked = navUseDocked();
  const [rail, setRailState] = React.useState(() => navReadLocal(NAV_RAIL_KEY, '0') === '1');
  const [folded, setFolded] = React.useState(navReadFolded);
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const menuBtnRef = React.useRef(null);
  const closeBtnRef = React.useRef(null);
  const isTT = !!(activeTab && activeTab.startsWith('tt'));

  function setRail(v) { setRailState(v); navWriteLocal(NAV_RAIL_KEY, v ? '1' : '0'); }
  function toggleFold(key) {
    setFolded(f => {
      const next = f.indexOf(key) >= 0 ? f.filter(k => k !== key) : f.concat([key]);
      navWriteLocal(NAV_FOLDED_KEY, JSON.stringify(next));
      return next;
    });
  }
  function closeDrawer() {
    setDrawerOpen(false);
    setTimeout(() => { if (menuBtnRef.current) menuBtnRef.current.focus(); }, 0);
  }
  // A drawer left open closes when the window widens enough to dock.
  React.useEffect(() => { if (docked) setDrawerOpen(false); }, [docked]);
  // While the drawer is open: focus its close button; Escape closes it.
  React.useEffect(() => {
    if (!drawerOpen) return undefined;
    if (closeBtnRef.current) closeBtnRef.current.focus();
    function onKey(e) { if (e.key === 'Escape') closeDrawer(); }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [drawerOpen]);

  const byId = {};
  TOP_NAV_ITEMS.forEach(it => { byId[it.id] = it; });
  // tradeAttention = {spot, perpOpen, perpNeedsStop, perpNotReady} (tradesNavCounts), or null before the first read.
  const att = tradeAttention && typeof tradeAttention === 'object' ? tradeAttention : null;
  function badgeFor(id) {
    if (!att) return null;
    if (id === 'spot') {
      const n = Number(att.spot) || 0;
      return n > 0 ? { n, warn: true, title: n === 1 ? '1 exit signal' : n + ' exit signals' } : null;
    }
    if (id === 'perps') {
      const n = Number(att.perpOpen) || 0;
      const s = Number(att.perpNeedsStop) || 0;
      const p = Number(att.perpNotReady) || 0;
      if (n <= 0) return null;
      // Landing 22: prep = an open trade still misses a part to count toward the risk gate (a cyan dot, never the warning colour).
      return { n, warn: s > 0, prep: p > 0, title: (n === 1 ? '1 open perp trade' : n + ' open perp trades')
        + (s ? ' · ' + s + (s === 1 ? ' needs a stop' : ' need a stop') : '')
        + (p ? ' · ' + p + ' not ready to count' : '') };
    }
    return null;
  }
  function badgeEl(b, kind, key) {
    return React.createElement('span', { key, className: 'tv-side-badge' + (b.warn ? ' warn' : '') + (kind ? ' ' + kind : ''),
      'aria-hidden': 'true' }, b.n > 99 ? '99+' : String(b.n),
      b.prep ? React.createElement('span', { className: 'tv-side-badge-dot' }) : null);
  }
  function isActive(it) {
    if (it.tab) return activeTab === it.tab && portfolioSubTab === it.sub;
    if (it.id === 'tt') return isTT;
    return activeTab === it.id;
  }
  function subsFor(it) {
    if (it.id === 'archive') return ARCHIVE_SUBNAV_ITEMS.map(s => ({ id: s.id, label: s.label, on: archiveSubTab === s.id,
      pick: () => { onArchiveSubTabChange && onArchiveSubTabChange(s.id); if (!docked) closeDrawer(); } }));
    if (it.id === 'tt') return TT_SUBNAV_ITEMS.map(s => ({ id: s.id, label: s.label, on: activeTab === s.id,
      pick: () => { onTabChange(s.id); if (!docked) closeDrawer(); } }));
    return null;
  }
  function go(it) {
    if (it.tab) {
      onTabChange(it.tab);
      onPortfolioSubTabChange && onPortfolioSubTabChange(it.sub);
    } else if (it.id === 'tt') {
      onTabChange('tt-scanner');
    } else {
      onTabChange(it.id);
    }
    // In the drawer, an item with sub-tabs keeps it open so a sub-tab can be picked next.
    if (!docked && drawerOpen && !subsFor(it)) closeDrawer();
  }

  function renderItem(it, inRail) {
    const active = isActive(it);
    const b = badgeFor(it.id);
    const label = it.label + (b ? ' · ' + b.title : '');
    const subs = active && !inRail ? subsFor(it) : null;
    return React.createElement(React.Fragment, { key: it.id },
      React.createElement('button', {
        type: 'button', className: 'tv-side-item' + (active ? ' active' : ''),
        'aria-current': active ? 'page' : undefined, 'aria-label': label,
        title: inRail ? label : (b ? b.title : undefined),
        onClick: () => go(it),
      },
        React.createElement('span', { className: 'tv-side-icon' },
          navIcon(NAV_ICONS[it.id] || NAV_ICONS.dashboard, 20), b && inRail ? badgeEl(b, 'rail') : null),
        inRail ? null : React.createElement('span', { className: 'tv-side-label' }, it.label),
        b && !inRail ? badgeEl(b, '') : null),
      subs ? React.createElement('div', { className: 'tv-side-subs' }, subs.map(x => React.createElement('button', {
        key: x.id, type: 'button', className: 'tv-side-sub' + (x.on ? ' active' : ''),
        'aria-current': x.on ? 'page' : undefined, onClick: x.pick,
      }, x.label))) : null);
  }

  function renderGroups(inRail) {
    let shownGroups = 0;
    return NAV_GROUPS.map(g => {
      const items = g.ids.map(id => byId[id]).filter(it => it && !isHiddenTab(it.id));
      if (!items.length) return null;
      shownGroups += 1;
      const isFolded = !inRail && !!g.heading && folded.indexOf(g.key) >= 0;
      // A folded section still lists the page you are on.
      const shown = isFolded ? items.filter(isActive) : items;
      const rolled = isFolded ? items.map(it => ({ it, b: badgeFor(it.id) })).filter(x => x.b) : [];
      let head = null;
      if (inRail) {
        if (shownGroups > 1) head = React.createElement('div', { className: 'tv-side-divider', 'aria-hidden': 'true' });
      } else if (g.heading) {
        head = React.createElement('button', {
          type: 'button', className: 'tv-side-heading', 'aria-expanded': !isFolded,
          title: rolled.length ? rolled.map(x => x.it.label + ' · ' + x.b.title).join('\n') : undefined,
          onClick: () => toggleFold(g.key),
        },
          React.createElement('span', { className: 'tv-side-heading-text' }, g.heading),
          rolled.map(x => badgeEl(x.b, '', x.it.id)),
          navIcon(isFolded ? NAV_PATH.expand : NAV_PATH.foldOpen, 14));
      }
      return React.createElement('div', { key: g.key, className: 'tv-side-group', role: 'group', 'aria-label': g.heading || 'Home' },
        head, shown.map(it => renderItem(it, inRail)));
    });
  }

  function renderFooter(inRail) {
    const label = (text) => inRail ? null : React.createElement('span', null, text);
    const hideText = hideValues ? 'Show values' : 'Hide values';
    const refreshText = refreshing ? 'Refreshing…' : 'Refresh';
    return React.createElement('div', { className: 'tv-side-foot' },
      React.createElement('button', { type: 'button', className: 'tv-side-foot-btn', onClick: onToggleHide,
        'aria-pressed': !!hideValues, 'aria-label': hideText, title: hideText }, navIcon(NAV_PATH.eye, 18), label(hideText)),
      React.createElement('button', { type: 'button', className: 'tv-side-foot-btn' + (refreshing ? ' spinning' : ''),
        onClick: onRefresh, disabled: refreshing, 'aria-label': refreshText, title: refreshText }, navIcon(NAV_PATH.refresh, 18), label(refreshText)),
      React.createElement('a', { href: '/logout', className: 'tv-side-foot-btn', 'aria-label': 'Logout', title: 'Logout' },
        navIcon(NAV_PATH.logout, 18), label('Logout')));
  }

  const brand = React.createElement('span', { className: 'tv-side-brand' }, 'The Playbook');

  if (docked) {
    const toggleText = rail ? 'Expand menu' : 'Collapse menu';
    return React.createElement('aside', { className: 'tv-side tv-side--docked' + (rail ? ' tv-side--rail' : '') },
      React.createElement('div', { className: 'tv-side-head' },
        rail ? null : brand,
        React.createElement('button', { type: 'button', className: 'tv-side-iconbtn', onClick: () => setRail(!rail),
          'aria-expanded': !rail, 'aria-label': toggleText, title: toggleText }, navIcon(rail ? NAV_PATH.expand : NAV_PATH.collapse, 18))),
      React.createElement('nav', { className: 'tv-side-scroll', 'aria-label': 'Main menu' }, renderGroups(rail)),
      renderFooter(rail));
  }

  // Narrow window: top bar + drawer.
  const current = TOP_NAV_ITEMS.filter(isActive)[0];
  const quick = ['spot', 'perps'].map(id => ({ it: byId[id], b: badgeFor(id) })).filter(x => x.it && x.b);
  const anyWarn = quick.some(x => x.b.warn);
  return React.createElement(React.Fragment, null,
    React.createElement('header', { className: 'tv-topbar' },
      React.createElement('button', { ref: menuBtnRef, type: 'button', className: 'tv-side-iconbtn tv-topbar-menu',
        'aria-label': anyWarn ? 'Open menu (something needs attention)' : 'Open menu', 'aria-expanded': drawerOpen,
        onClick: () => setDrawerOpen(true) },
        navIcon(NAV_PATH.menu, 20), anyWarn ? React.createElement('span', { className: 'tv-topbar-dot', 'aria-hidden': 'true' }) : null),
      React.createElement('span', { className: 'tv-topbar-title' }, current ? current.label : 'The Playbook'),
      React.createElement('span', { className: 'tv-topbar-badges' }, quick.map(x => React.createElement('button', {
        key: x.it.id, type: 'button', className: 'tv-topbar-badge-btn', onClick: () => go(x.it),
        'aria-label': x.it.label + ' · ' + x.b.title, title: x.it.label + ' · ' + x.b.title,
      }, React.createElement('span', { className: 'tv-topbar-badge-label' }, x.it.label), badgeEl(x.b, ''))))),
    drawerOpen ? React.createElement('div', { className: 'tv-drawer-backdrop', onClick: closeDrawer }) : null,
    drawerOpen ? React.createElement('aside', { className: 'tv-side tv-side--drawer', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Menu' },
      React.createElement('div', { className: 'tv-side-head' }, brand,
        React.createElement('button', { ref: closeBtnRef, type: 'button', className: 'tv-side-iconbtn', onClick: closeDrawer,
          'aria-label': 'Close menu', title: 'Close menu' }, navIcon(NAV_PATH.close, 18))),
      React.createElement('nav', { className: 'tv-side-scroll', 'aria-label': 'Main menu' }, renderGroups(false)),
      renderFooter(false)) : null);
}

window.TVNav = TVNav;
window.TT_SUBNAV_ITEMS = TT_SUBNAV_ITEMS;
window.TOP_NAV_ITEMS = TOP_NAV_ITEMS;
window.ARCHIVE_SUBNAV_ITEMS = ARCHIVE_SUBNAV_ITEMS;
window.HIDDEN_TABS = HIDDEN_TABS;
window.isHiddenTab = isHiddenTab;
