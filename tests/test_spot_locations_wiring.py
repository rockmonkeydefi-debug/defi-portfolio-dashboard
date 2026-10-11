"""Landing 26: the Spot page's Open positions show which tracked wallet holds
each token, on the Token cell's second line ("Base · Desktop Hot +1"), from
GET /api/spot/locations.

Reads the source files and the app's routes. The behaviour is covered by the
route tests (tests/test_spot_locations.py) and the headless browser checks.
"""
import os
import re

import web_portfolio as wp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _function(src, name):
    """The source of one top-level function (up to the next top-level line)."""
    m = re.search(r"^function " + name + r"\(.*?^\}", src, re.S | re.M)
    assert m, name
    return m.group(0)


def test_the_page_reads_the_route_and_the_route_exists():
    spot = _read("static/spotpnl.js")
    assert "api('/api/spot/locations')" in spot
    assert "/api/spot/locations" in {r.rule for r in wp.app.url_map.iter_rules()}


def test_the_tag_sits_on_the_token_cells_second_line():
    spot = _read("static/spotpnl.js")
    assert "const walletTag = spotWalletTag(locs, key, r.symbol, hideValues);" in spot
    # its own line in the Token cell, right after the chain line (which is unchanged)
    assert re.search(r"\{chainLabel\}\s*\{hasNotes &&.*?</span>\}\s*</span>\s*<SpotWalletTag tag=\{walletTag\} />\s*</div>", spot, re.S)


def test_unknown_shows_nothing_and_not_found_says_so():
    fn = _function(_read("static/spotpnl.js"), "spotWalletTag")
    assert "if (!locs || locs.status !== 'ok' || !locs.asOf || !locs.positions) return null;" in fn
    assert "if (!entry) return null;" in fn
    assert "SPOT_NOT_TRACKED = 'not in a tracked wallet'" in _read("static/spotpnl.js")


def test_hide_values_masks_the_units_on_hover():
    fn = _function(_read("static/spotpnl.js"), "spotWalletTag")
    assert "const amount = hideValues ? '••••' : spotHoldFmtUnits(w.units)" in fn


def test_a_long_label_is_cut_with_an_ellipsis():
    css = _read("static/style.css")
    rule = re.search(r"\.spot-wallet-name \{([^}]*)\}", css)
    assert rule
    for part in ("max-width: calc(100% - 28px)", "overflow: hidden", "text-overflow: ellipsis", "white-space: nowrap"):
        assert part in rule.group(1)
    line = re.search(r"\.spot-tok-wallet \{([^}]*)\}", css)
    assert line
    for part in ("display: block", "white-space: nowrap", "overflow: hidden", "text-overflow: ellipsis"):
        assert part in line.group(1)
    assert 'className="spot-wallet-name"' in _function(_read("static/spotpnl.js"), "SpotWalletTag")


def test_the_time_helpers_load_before_the_page():
    html = _read("templates/index.html")
    assert html.index("/static/spotjournal.js") < html.index("/static/spotpnl.js")


def test_the_breakdown_is_also_in_the_expanded_row_and_old_snapshots_show_a_date():
    spot = _read("static/spotpnl.js")
    # The hover text is repeated in the expanded row, so touch and keyboard can reach it.
    assert "{walletTag && <div style={{ fontSize: 13, color: 'var(--text3)', overflowWrap: 'anywhere' }}>{walletTag.detail}</div>}" in spot
    fn = _function(spot, "spotWalletTag")
    assert "note: !old.length ? '' : unread ? ' (not all wallets read)' : dateNote(old[0].as_of)" in fn
    assert "note: wallets[0].stale ? dateNote(wallets[0].as_of) : ''" in fn
    assert "oldWallets: Array.isArray(d.old_wallets) ? d.old_wallets : []" in spot
