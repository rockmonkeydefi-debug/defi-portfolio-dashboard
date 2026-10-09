"""Landing 22 (HANDOFF_advisor_v1.md section 42): the frontend of the "not
ready to count" nudge. static/utils.js reads the trades route's gate_prep
(gateMissing) and counts perpNotReady in tradesNavCounts; static/app.js
keeps the count from the 'trades-attention' events; static/nav.js draws a
cyan dot on the Perps badge (never the warning colour); static/perps.js
shows "Not ready to count" with the missing parts on the Open row.

Reads the source files only; no app or database.
"""
import os
import re

from src.engines import perp_rules as pr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _lum(hex_color):
    h = hex_color.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _token(css, name):
    m = re.search(r"--" + name + r":\s*(#[0-9a-fA-F]{6});", css)
    assert m, name
    return m.group(1)


def test_part_names_match_the_engine():
    src = _read("static/utils.js")
    m = re.search(r"const GATE_PREP_PARTS = \[([^\]]*)\];", src)
    assert m
    assert tuple(re.findall(r"'(\w+)'", m.group(1))) == pr.GATE_PREP_PARTS
    labels = re.search(r"const GATE_PREP_LABELS = \{([^}]*)\};", src)
    assert labels and set(re.findall(r"(\w+):", labels.group(1))) == set(pr.GATE_PREP_PARTS)
    acts = re.search(r"const PRP_PREP_ACTIONS = \{([^}]*)\};", _read("static/perps.js"))
    assert acts and set(re.findall(r"(\w+):", acts.group(1))) == set(pr.GATE_PREP_PARTS)


def test_nav_counts_carry_not_ready():
    src = _read("static/utils.js")
    body = src[src.index("function tradesNavCounts(d)"):src.index("window.tradesNavCounts")]
    assert "perpNotReady: perps.filter(t => t.status !== 'closed' && gateMissing(t).length > 0).length" in body
    assert "window.gateMissing = gateMissing;" in src and "window.GATE_PREP_LABELS = GATE_PREP_LABELS;" in src
    # Every sender of 'trades-attention' counts through tradesNavCounts, so each carries perpNotReady.
    for rel in ("static/perps.js", "static/dashboard.js"):
        s = _read(rel)
        assert s.count("'trades-attention'") == 1 and "tradesNavCounts(d)" in s


def test_app_keeps_the_count_from_events():
    src = _read("static/app.js")
    assert re.search(r"setTradeAttention\(\{ spot: v\.spot, perpOpen: v\.perpOpen, perpNeedsStop: v\.perpNeedsStop,\s*"
                     r"perpNotReady: typeof v\.perpNotReady === 'number' \? v\.perpNotReady : 0 \}\)", src)
    # An event without the new count still lands (its stop warning is not dropped).
    listener = src[src.index("function onTradesAttention(e)"):src.index("readAttention();\n")]
    assert "typeof v.perpNotReady === 'number' &&" not in listener and "&& typeof v.perpNotReady" not in listener


def test_nav_draws_a_separate_marker():
    src = _read("static/nav.js")
    assert "const p = Number(att.perpNotReady) || 0;" in src
    assert "prep: p > 0" in src and "' not ready to count'" in src
    assert "b.prep ? React.createElement('span', { className: 'tv-side-badge-dot' }) : null" in src
    # The warning colour (badge and menu-button dot) still follows needs-a-stop only.
    assert "warn: s > 0, prep: p > 0" in src
    assert "const anyWarn = quick.some(x => x.b.warn);" in src


def test_dot_is_styled_cyan_and_visible():
    css = _read("static/style.css")
    rule = re.search(r"\.tv-side-badge-dot \{([^}]*)\}", css)
    assert rule and "background: var(--adapt)" in rule.group(1) and "box-shadow: 0 0 0 2px var(--panel)" in rule.group(1)
    assert re.search(r"\.tv-side-badge \{ position: relative;", css)
    adapt, panel, warn = _token(css, "adapt"), _token(css, "panel"), _token(css, "warn")
    assert _contrast(adapt, panel) >= 3.0           # a non-text marker against its ring
    assert adapt.lower() != warn.lower()


def test_open_row_shows_the_missing_parts():
    src = _read("static/perps.js")
    row = src[src.index("function PerpsOpenRow("):src.index("function PerpsOpenTab(")]
    assert "const missing = gateMissing(t);" in row
    assert "{missing.length > 0 && <PerpsGatePrep missing={missing} />}" in row
    chip = src[src.index("function PerpsGatePrep("):src.index("function PerpsOpenRow(")]
    assert ">Not ready to count</span>" in chip and "{'Missing: '}" in chip
    assert "<span style={{ whiteSpace: 'nowrap' }}>{GATE_PREP_LABELS[p] || p}</span>" in chip
    assert "color: 'var(--text)'" in chip                 # white chip text, not the cyan (contrast)
    assert "Tags saved after the close don't count." in chip
    assert "A take-profit set on the venue shows here after the next venue read (up to 15 minutes)." in chip


def test_the_tip_matches_the_venue_cache_interval():
    """The chip's hover promises up to 15 minutes for a new take-profit: the
    Hyperliquid and TxFlow live caches refresh on that interval."""
    src = _read("web_portfolio.py")
    assert re.search(r"^HL_ACCOUNTS_TTL_MINUTES = 15$", src, re.M)
    assert re.search(r"^TXFLOW_TTL_MINUTES = 15$", src, re.M)
