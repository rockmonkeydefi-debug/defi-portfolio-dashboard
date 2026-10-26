"""Trends "On-chain" tab (Landing 70, Glenn Oct 25).

Glenn wants to check tokens he cannot open in TradingView because they are on
neither Hyperliquid nor TxFlow. The backend (onchain_scan.py, the compute and
GET /api/trading/scanner/onchain-check in web_portfolio.py; tests/test_onchain_scan.py)
finds the token's most liquid GeckoTerminal pool and returns a noodle-state-shaped
row; nothing is stored. The tab is the page's third (he asked for a tab, not a
collapsible section: he will use it rarely). These pin the wiring. Browser checks
(1920, 1250 and 390px) are in the landing record.

Rulings pinned here: the chains are exactly Spot's seven; no BTC context beside
the token (no RS vs BTC column, no BTC strip); the tab keeps its form and result
while another tab shows; a reload never opens on this tab.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(ROOT, "static", "trends.js"), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def _section():
    return _between(_js(), "/* -- Landing 70: ad hoc on-chain token check", "function TrendsScreen() {")


def test_the_page_has_a_third_tab_after_the_two_board_tabs():
    js = _js()
    tabs = _between(js, "function TrendsTabs({ tab, setTab }) {", "// One timeframe cell")
    assert "btn('trends', 'Trends'), btn('respected', 'Respected trend'), btn('onchain', 'On-chain')" in tabs


def test_a_reload_never_opens_on_the_onchain_tab():
    js = _js()
    set_tab = _between(js, "function setTab(t) {", "const [rsort")
    assert "if (t === 'onchain') return;" in set_tab
    assert set_tab.index("if (t === 'onchain') return;") < set_tab.index("localStorage.setItem(TRENDS_TAB_STORAGE_KEY")
    init = _between(js, "const [tab, setTabState] = React.useState(() => {", "function setTab(t)")
    assert "=== 'respected' ? 'respected' : 'trends'" in init


def test_the_tab_stays_mounted_and_works_with_no_scan_data():
    js = _js()
    assert js.count("React.createElement(TrendsOnchainCheck, null)") == 1
    screen = _between(js, "React.createElement(TrendsTabs, { tab, setTab }),", "React.createElement(TrendsSidebar, {")
    mount = screen.index("React.createElement(TrendsOnchainCheck, null)")
    assert "display: tab === 'onchain' ? 'block' : 'none'" in screen[:mount + 60]
    # mounted before (so outside) the "No scan data yet" branch, which the board tabs alone use
    assert mount < screen.index("rows.length === 0")
    assert "tab === 'onchain' ? null : rows.length === 0" in screen


def test_the_board_tabs_do_not_carry_the_check():
    js = _js()
    board = _between(js, "tab === 'onchain' ? null : rows.length === 0", "React.createElement(TrendsSidebar, {")
    assert "TrendsOnchainCheck" not in board


def test_no_btc_context_beside_the_token():
    sec = _section()
    assert "TrendsBtcStrip" not in sec and "RS VS BTC" not in sec and "rs_vs_btc" not in sec
    assert "TrendsSubTable" not in sec        # that table carries the RS vs BTC column


def test_the_chains_are_exactly_spots_seven():
    import web_portfolio
    sec = _section()
    body = _between(sec, "const TRENDS_ONCHAIN_CHAINS = [", "];")
    lb, rb = re.escape(chr(91)), re.escape(chr(93))
    pairs = re.findall(lb + "'([a-z]+)', '([^']+)'" + rb, body)
    assert [k for k, _ in pairs] == list(web_portfolio.SPOT_CHAINS)
    assert {k: v for k, v in pairs} == {k: c["label"] for k, c in web_portfolio.SPOT_CHAINS.items()}


def test_the_request_and_the_messages():
    sec = _section()
    assert "'/api/trading/scanner/onchain-check?' + qs" in sec
    assert "'chain=' + encodeURIComponent(chain) + '&token=' + encodeURIComponent(tok)" in sec
    assert "'&pool=' + encodeURIComponent(poolAddr)" in sec
    assert "'Enter a token contract address (or a pool address).'" in sec
    assert "_trendsExtractErr(e)" in sec
    assert "Reads price history from GeckoTerminal; nothing is saved." in sec
    assert "about 20 seconds" in sec


def test_the_backend_message_matches_the_frontend_empty_input_message():
    with open(os.path.join(ROOT, "web_portfolio.py"), encoding="utf-8") as fh:
        py = fh.read()
    assert "'Enter a token contract address (or a pool address).'" in py


def test_checking_is_one_at_a_time():
    sec = _section()
    assert sec.count("disabled: busy") == 5          # chain, token, Check, pool, "use this pool"
    assert "if (e.key === 'Enter' && !busy) check();" in sec
    assert sec.count("setBusy(true)") == 1 and sec.count("setBusy(false)") == 1


def test_the_card_reuses_the_boards_cells_and_shows_the_pool_facts():
    sec = _section()
    for piece in ("TrendsStateChip", "TrendsAlignmentChip", "_trendsRespectCell(tf, tfKey, nowMs)",
                  "TrendsRespectCell", "_trendsPctSinceFlip", "_trendsFmtToFlip"):
        assert piece in sec
    for label in ("'DEX'", "'Liquidity'", "'24h volume'", "'Age'", "'use this pool'", "'Close'",
                  "WARMING UP", "needs about "):
        assert label in sec
    assert "tfKey === '1w' ? null : _trendsRespectCell" in sec     # weekly keeps no respected trend


def test_the_notes_come_from_the_backend_and_the_first_is_the_safety_note():
    sec = _section()
    assert "(result.notes || []).map" in sec and "'data-note': i === 0 ? 'safety' : 'warn'" in sec
    with open(os.path.join(ROOT, "web_portfolio.py"), encoding="utf-8") as fh:
        py = fh.read()
    assert "notes = ['No contract-safety check" in py


def test_the_warmup_bar_count_matches_the_engine():
    """The card says "needs about 30" bars: the engine reads a state once it has
    as many closed bars as its slow EMA (28 by default) and says WARMUP before."""
    sec = _section()
    assert "const TRENDS_ONCHAIN_WARMUP_BARS = 30;" in sec
    import web_portfolio
    from src.engines.noodle_bands import compute_noodle_state
    p = web_portfolio._trade_snapshot_settings()
    assert 28 <= TRENDS_WARMUP_BARS_CLAIM and p["slow"] <= TRENDS_WARMUP_BARS_CLAIM

    def bars(n):
        return [{"open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100 + i * 0.5, "volume": 1,
                 "time": 1700000000 + i * 3600} for i in range(n)]
    kw = dict(fast=p["fast"], medium=p["medium"], slow=p["slow"], atr_length=p["atr_length"],
              band_multiplier=p["band_multiplier"], use_atr=p["use_atr"])
    assert compute_noodle_state(bars(p["slow"] - 1), **kw)["state"] == "WARMUP"
    assert compute_noodle_state(bars(p["slow"]), **kw)["state"] != "WARMUP"


TRENDS_WARMUP_BARS_CLAIM = 30


def test_visibility_rules_in_the_section():
    """Glenn's UI rules: no text below 11px, no muted greys on the dark panels."""
    sec = _section()
    sizes = [int(x) for x in re.findall(r"fontSize: ([0-9]+)", sec)]
    assert sizes and min(sizes) >= 11
    assert not re.search(r"#(8b98a5|6e7781)|gray-[45]00", sec)
