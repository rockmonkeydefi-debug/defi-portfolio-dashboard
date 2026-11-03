"""Landing 91: MaxFi is hidden (Glenn, Nov 2 and Nov 3). Source-text checks; the behaviour is checked by the
headless-browser runs.

- static/nav.js: the five MaxFi pages are on the hide list, so the menu's MaxFi section has no visible item and is
  not drawn; app.js already opens the Dashboard for a stored hidden tab. The pages themselves stay.
- static/dashboard.js: no MaxFi card, hero badge or MaxFi requests; the MaxFi LP / fees breakdown rows show only
  when non-zero or warning (the total still counts them). _dashFinite, which sat with the MaxFi card, is kept. The total's math (portfolio_total.py) and the MaxFi backend are untouched.
- static/style.css: Dashboard row 4 has two columns (Market, Lending).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


MAXFI_PAGES = ("maxfi", "pl", "scout", "actionplan", "checklist")


def test_the_maxfi_pages_are_on_the_hide_list():
    nav = _read("static/nav.js")
    assert "var HIDDEN_TABS = ['aibrief', 'tt', 'maxfi', 'pl', 'scout', 'actionplan', 'checklist'];" in nav
    # the MaxFi section lists exactly these pages, so none of its items is drawn and the group is skipped
    assert "{ key: 'maxfi',    heading: 'MaxFi',    ids: ['maxfi', 'pl', 'scout', 'actionplan', 'checklist'] }," in nav
    assert "const items = g.ids.map(id => byId[id]).filter(it => it && !isHiddenTab(it.id));" in nav
    assert "if (!items.length) return null;" in nav
    # the pages are hidden, not removed: still in the catalogue and still routed
    for page in MAXFI_PAGES:
        assert "{ id: '%s'," % page in nav
    app = _read("static/app.js")
    assert "window.isHiddenTab(stored)" in app and "localStorage.setItem('activeTab', 'dashboard');" in app
    for screen in ("MaxFiScreen", "PLScreen", "ScoutScreen", "ActionPlanScreen", "ChecklistScreen"):
        assert "window." + screen in app


def test_the_hide_list_hides_no_other_page():
    nav = _read("static/nav.js")
    ids = re.findall(r"\{ id: '([a-z0-9-]+)',", nav[nav.index("const TOP_NAV_ITEMS = ["):nav.index("/* ===== SIDEBAR MENU")])
    hidden = ("aibrief", "tt") + MAXFI_PAGES
    for i in ids:
        by_prefix = any(i == h or i.startswith(h + "-") for h in hidden)
        assert by_prefix == (i in hidden), i                                  # e.g. 'portfolio-lp' is not caught by 'pl'


def test_the_dashboard_has_no_maxfi_card_badge_or_requests():
    js = _read("static/dashboard.js")
    for gone in ("DashMaxfiCard", "_dashMaxfiModel", "DASH_MAXFI_CHAINS", "DASH_RANGE_TIMEOUT_MS", "runRange",
                 "maxfiAttention", "goMaxfi", "dash-maxfi", "/api/maxfi/", "'/api/wallets'", "setAdvisor",
                 "mxWallets", "mxRange", "setActiveTab('maxfi')", "_dashChainLabel", "_dashVerdict", "_dashPair"):
        assert gone not in js, gone
    assert "function DashHeroCard({ model, hideValues, refreshing, totalIdle, onRefresh }) {" in js
    assert "totalIdle={totalState === 'idle'} onRefresh={handleRefresh} />" in js
    assert "  }, [fetchTotal, loadBtPerf, loadPerpsOpen]);" in js
    # kept: used across the page
    assert js.count("function _dashFinite(v) {") == 1


def test_the_maxfi_rows_stay_but_show_only_when_non_zero_or_warning():
    """Glenn, Nov 3 (A): the total still counts MaxFi, and every counted part keeps a breakdown row
    (tests/test_dashboard_txflow_part.py), so the two rows stay; the always-show rule for MaxFi LP is gone."""
    js = _read("static/dashboard.js")
    rows = js[js.index("const DASH_PART_ROWS = ["):js.index("];", js.index("const DASH_PART_ROWS = ["))]
    assert "['maxfi_lp', 'MaxFi LP']" in rows and "['maxfi_uncollected', 'MaxFi fees']" in rows
    assert "key === 'maxfi_lp' ||" not in js                                 # no longer shown at $0
    assert js.count("if (!(warnings.length || pending || _dashNonZero(value))) continue;") == 1
    assert js.count("if (!_dashNonZero(value || 0)) continue;") == 1          # the snapshot fallback
    assert "if (key === 'maxfi_lp') warnings = warnings.concat(drift);" in js  # a drift warning still shows the row
    assert "const DASH_IDLE_KEYS = ['wallet_tokens', 'stablecoins', 'hyperliquid'];" in js     # no loading placeholders


def test_row_four_has_two_columns_and_no_maxfi_rules():
    css = re.sub(r"/[*].*?[*]/", "", _read("static/style.css"), flags=re.S)
    assert ".dash-row4 { display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:16px; align-items:stretch; }" in css
    assert "#dash-maxfi" not in css and ".dash-maxfi-" not in css
    js = _read("static/dashboard.js")
    row4 = js[js.index('<div className="dash-row4">'):]
    row4 = row4[:row4.index("</div>")]
    assert "<DashBtcCard " in row4 and "<DashLendingCard " in row4


def test_the_total_and_the_maxfi_backend_are_untouched():
    total = _read("portfolio_total.py")
    assert "maxfi_lp" in total and "maxfi_uncollected" in total
    wp = _read("web_portfolio.py")
    assert "/api/maxfi/advisor" in wp
