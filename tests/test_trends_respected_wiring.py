"""Trends "Respected trend" setup (Landing 50, Oct 17).

Glenn asked for the timeframe a coin is respecting, as watch-list information
(not entry triggers), with higher timeframes winning ties, both directions, a
"retesting now" option and 1H included (marked history limited when the run
started before the scanned bars). static/trends.js reads the four respect_*
columns the scan stores on the 1h / 4h / 12h / 1d rows (src/engines/
respected_trend.py). Browser checks (1920, 1250 and 390px) are in the
landing record; these pin the wiring.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(ROOT, "static", "trends.js"), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def test_constants_and_defaults():
    js = _js()
    assert "const TRENDS_RESPECT_MIN_TAGS = 2;" in js
    assert "const TRENDS_RESPECT_WINDOW_BARS = 30;" in js
    assert "const TRENDS_RESPECT_TFS = ['1d', '12h', '4h', '1h'];" in js
    assert "const TRENDS_RESPECT_TF_SECONDS = { '1d': 86400, '12h': 43200, '4h': 14400, '1h': 3600 };" in js
    defaults = _between(js, "const TRENDS_FILTER_DEFAULTS = {", "};")
    assert "  respected: false," in defaults and "  respectedRetest: false," in defaults


def test_helper_reads_the_columns_fails_closed_and_ties_go_to_the_higher_timeframe():
    body = _between(_js(), "function _trendsRespected(rowTimeframes, nowMs) {", "function _trendsRespectedLabel(")
    assert "for (const tfKey of TRENDS_RESPECT_TFS) {" in body
    assert "if (!r || (r.respect_dir !== 'BULLISH' && r.respect_dir !== 'BEARISH')) continue;" in body
    assert "if (typeof r.respect_tags !== 'number' || r.respect_tags < TRENDS_RESPECT_MIN_TAGS) continue;" in body
    assert "if (typeof r.respect_last_ts !== 'number' || typeof r.computed_at !== 'string') continue;" in body
    assert "const lastClosedOpen = Math.floor(computedSec / tfSec) * tfSec - tfSec;" in body
    assert "if (barsAgo >= TRENDS_RESPECT_WINDOW_BARS) continue;" in body
    assert "if (best && r.respect_tags <= best.tags) continue;" in body
    assert "r.price >= r.lower_band && r.price <= r.upper_band" in body


def test_filter_tag_sidebar_and_tips_are_wired():
    js = _js()
    passes = _between(js, "function _trendsPassesSearchAndSidebar(", "function _trendsSortValue(")
    assert "if (filters.respected || filters.respectedRetest) {" in passes
    assert "if (filters.respectedRetest && !resp.retesting) return false;" in passes
    assert "const resp = respectedOn ? _trendsRespected(row.timeframes, nowMs) : null;" in js
    assert "_trendsRespectedLabel(resp)" in js
    assert "respectedOn: filters.respected || filters.respectedRetest," in js
    label = _between(js, "function _trendsRespectedLabel(x) {", "// Every sidebar filter")
    assert "parts.push('last ' + age + ' ago');" in label
    assert "parts.push('retesting');" in label
    assert "parts.push('history limited');" in label
    side = _between(js, "function TrendsSidebar(", "/* ── main screen ── */")
    setups = _between(side, "{ title: 'SETUPS' }", "{ title: 'TREND',")
    assert setups.index("label: 'Compression under Weekly'") < setups.index("label: 'Respected trend'")
    assert setups.index("label: 'Respected trend'") < setups.index("label: 'Retesting now'")
    assert "checked: filters.respected, onCheck: (v) => set({ respected: v })," in setups
    assert "checked: filters.respectedRetest, onCheck: (v) => set({ respectedRetest: v })," in setups
    tip = _between(js, "  respected: {", "  respectedRetest: {")
    assert "the higher timeframe wins a tie" in tip
    assert "two candles in a row close beyond the far edge" in tip
    assert "it is not an entry signal" in tip


def _run_helper(rows, now_ms):
    """Run the real _trendsRespected / _trendsRespectedLabel text in node."""
    js = _js()
    nl = chr(10)
    consts = nl.join(re.findall(r"^const TRENDS_RESPECT_[A-Za-z_0-9]+ = .*;$", js, re.M))
    fn = "function _trendsRespected(" + _between(js, "function _trendsRespected(", "// Every sidebar filter")
    script = nl.join([
        consts,
        "function _trendsAgeFromTs(nowMs, t) { return typeof t !== 'number' ? null : Math.max(0, Math.floor(nowMs / 1000) - t); }",
        "function _trendsFmtAge(s, tf) { return s === null ? null : Math.floor(s / 3600) + 'h'; }",
        fn,
        "const out = JSON.parse(process.argv[1]).map((r) => {",
        "  const x = _trendsRespected(r.tfs, r.now);",
        "  return x === null ? null : Object.assign({}, x, { label: _trendsRespectedLabel(x) });",
        "});",
        "console.log(JSON.stringify(out));",
    ])
    res = subprocess.run(["node", "-e", script, json.dumps([{"tfs": r, "now": now_ms} for r in rows])],
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_behaviour_window_tie_break_retesting_and_fail_closed():
    computed = "2026-10-18T12:30:00+00:00"          # 12:30 UTC: last closed 1h bar opened 11:00
    base = 1792324200                                # 2026-10-18T12:30:00Z in unix seconds
    last_open = {"1h": 11 * 3600, "4h": 4 * 3600, "12h": 0, "1d": -86400}
    day = base - base % 86400

    def row(tf, ago, tags=2, direction="BULLISH", price=100.0):
        tf_sec = {"1h": 3600, "4h": 14400, "12h": 43200, "1d": 86400}[tf]
        return {"respect_dir": direction, "respect_tags": tags,
                "respect_last_ts": day + last_open[tf] - ago * tf_sec,
                "respect_unbounded": False, "computed_at": computed,
                "price": price, "lower_band": 95.0, "upper_band": 105.0}

    now_ms = base * 1000
    cases = [
        {"1h": row("1h", 0)},                                        # newest closed bar counts
        {"1h": row("1h", 29)},                                       # the 30th bar still counts
        {"1h": row("1h", 30)},                                       # the 31st does not
        {"1h": row("1h", 0, tags=1)},                                # one tag is not enough
        {"1h": row("1h", 3, tags=3), "1d": row("1d", 3, tags=3)},    # tie: higher timeframe wins
        {"1h": row("1h", 3, tags=4), "1d": row("1d", 3, tags=3)},    # more tags beats the higher timeframe
        {"4h": row("4h", 2, price=120.0)},                           # price outside the band: not retesting
        {"4h": row("4h", 2, price=95.0)},                            # on the lower edge: retesting
        {"4h": dict(row("4h", 2), respect_dir=None)},                # no run: fails closed
        {"4h": dict(row("4h", 2), computed_at=None)},                # no scan time: fails closed
        {"4h": dict(row("4h", 2), respect_unbounded=True)},          # history limited
        {},
    ]
    got = _run_helper(cases, now_ms)
    assert got[0] is not None and got[0]["barsAgo"] == 0
    assert got[1] is not None and got[1]["barsAgo"] == 29
    assert got[2] is None
    assert got[3] is None
    assert got[4]["tf"] == "1d" and got[5]["tf"] == "1h" and got[5]["tags"] == 4
    assert got[6]["retesting"] is False and "retesting" not in got[6]["label"]
    assert got[7]["retesting"] is True and got[7]["label"].endswith("retesting")
    assert got[8] is None and got[9] is None
    assert got[10]["unbounded"] is True and got[10]["label"].endswith("history limited")
    assert got[11] is None
