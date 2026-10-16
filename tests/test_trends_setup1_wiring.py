"""Trends "Daily cross under Weekly" filter (Landing 44, Oct 16).

Glenn's setup 1 (claude/doc_paragon/SPEC_doc_system.md Part F): the Daily EMA
stack (12 > 21 > 28) turned bullish within the chosen window (default 1 week),
and the whole Daily band sits at or under the Weekly band's top - inside it,
touching its lower edge, or below it by at most 10% (top of the Daily band to
the bottom of the Weekly band). static/trends.js reads the 1d / 1w rows the
noodle-state route already sends; no backend change. The helper's behavior is
checked chat-side with a Node harness and the browser checks (1920, 1250 and
390px) in the landing record; these pin the wiring.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(ROOT, "static", "trends.js"), encoding="utf-8") as fh:
        return fh.read()


def test_constants_and_defaults():
    js = _js()
    assert ("const TRENDS_SETUP1_RECENCY_OPTIONS = TRENDS_TIME_SINCE_FLIPPED_OPTIONS.filter("
            "(o) => o.seconds !== null && o.seconds >= 86400);") in js
    assert "const TRENDS_SETUP1_DEFAULT_RECENCY = '1 week';" in js
    assert "const TRENDS_SETUP1_MAX_GAP_PCT = 10;" in js
    defaults = js.split("const TRENDS_FILTER_DEFAULTS = {", 1)[1].split("};", 1)[0]
    assert "setup1: false," in defaults
    assert "setup1Recency: TRENDS_SETUP1_DEFAULT_RECENCY," in defaults


def test_helper_reads_daily_and_weekly_and_fails_closed():
    js = _js()
    body = js.split("function _trendsSetup1(rowTimeframes, recencyLabel, nowMs) {", 1)[1].split("function _trendsSetup1Label", 1)[0]
    assert "const d = rowTimeframes['1d'];" in body and "const w = rowTimeframes['1w'];" in body
    assert "if (!d || !w || d.alignment_state !== 'BULLISH') return null;" in body
    assert "if (d.alignment_changed_unbounded === true || typeof d.alignment_changed_ts !== 'number') return null;" in body
    assert "if (_trendsAgeFromTs(nowMs, d.alignment_changed_ts) > opt.seconds) return null;" in body
    assert "if (!edges.every((x) => typeof x === 'number' && isFinite(x))) return null;" in body
    assert "if (d.upper_band > w.upper_band) return null;" in body
    assert "if (d.lower_band >= w.lower_band) return { position: 'inside', gapPct: 0 };" in body
    assert "if (d.upper_band >= w.lower_band) return { position: 'touching', gapPct: 0 };" in body
    assert "const gapPct = (w.lower_band / d.upper_band - 1) * 100;" in body
    assert "return gapPct <= TRENDS_SETUP1_MAX_GAP_PCT ? { position: 'below', gapPct } : null;" in body


def test_filter_sidebar_and_row_tag_are_wired():
    js = _js()
    assert "if (filters.setup1 && !_trendsSetup1(row.timeframes, filters.setup1Recency, nowMs)) return false;" in js
    sidebar = js.split("function TrendsSidebar(", 1)[1]
    assert sidebar.index("{ title: 'SETUPS' }") < sidebar.index("{ title: 'TREND' }")
    assert "label: 'Daily cross under Weekly'" in sidebar
    assert "TRENDS_SETUP1_RECENCY_OPTIONS.map((o) =>" in sidebar
    assert "const s1 = setup1Recency ? _trendsSetup1(row.timeframes, setup1Recency, nowMs) : null;" in js
    assert "_trendsSetup1Label(s1)" in js
    assert "setup1Recency: filters.setup1 ? filters.setup1Recency : null," in js
