"""Trends "Daily cross under Weekly" filter (Landing 44, reworked in Landing 47).

Glenn's setup 1 (claude/doc_paragon/SPEC_doc_system.md Part F). Since Landing
47 (Oct 16 rulings) it reads Doc's trend EMAs, not the noodle: the Daily Trend
(EMA 100 / 200 of 4H closes, the 4h row's doc_* fields) fast EMA crossed above
its slow EMA within the chosen window (default 3 days), and the whole Daily
Trend band sits at or under the top of the Weekly Trend band (EMA 100 / 200 of
daily closes, the 1d row) - inside it, touching its lower edge, or below it by
at most 10% (top of the Daily Trend to the bottom of the Weekly Trend). The
backend side is tests/test_doc_trend.py. The helper's behavior is checked
chat-side with a Node harness and the browser checks (1920, 1250 and 390px) in
the landing record; these pin the wiring.
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
    assert "const TRENDS_SETUP1_DEFAULT_RECENCY = '3 days';" in js   # Landing 48, Glenn Oct 17
    assert "{ label: '3 days', seconds: 3 * 86400 }" in js
    assert "const TRENDS_SETUP1_MAX_GAP_PCT = 10;" in js
    defaults = js.split("const TRENDS_FILTER_DEFAULTS = {", 1)[1].split("};", 1)[0]
    assert "setup1: false," in defaults
    assert "setup1Recency: TRENDS_SETUP1_DEFAULT_RECENCY," in defaults


def test_helper_reads_doc_trends_and_fails_closed():
    js = _js()
    assert "const TRENDS_SETUP1_DAILY_TF = '4h';" in js
    assert "const TRENDS_SETUP1_WEEKLY_TF = '1d';" in js
    body = js.split("function _trendsSetup1(rowTimeframes, recencyLabel, nowMs) {", 1)[1].split("function _trendsSetup1Label", 1)[0]
    assert "const d = rowTimeframes[TRENDS_SETUP1_DAILY_TF];" in body
    assert "const w = rowTimeframes[TRENDS_SETUP1_WEEKLY_TF];" in body
    assert "if (!d || !w || d.doc_cross_state !== 'BULLISH') return null;" in body
    assert "if (d.doc_cross_unbounded === true || typeof d.doc_cross_ts !== 'number') return null;" in body
    assert "const ageSeconds = _trendsAgeFromTs(nowMs, d.doc_cross_ts);" in body
    assert "if (ageSeconds > opt.seconds) return null;" in body
    assert "const emas = [d.doc_ema_fast, d.doc_ema_slow, w.doc_ema_fast, w.doc_ema_slow];" in body
    assert "if (!emas.every((x) => typeof x === 'number' && isFinite(x) && x > 0)) return null;" in body
    assert "if (dailyTop > weeklyTop) return null;" in body
    assert "if (dailyBottom >= weeklyBottom) return { position: 'inside', gapPct: 0, ageSeconds };" in body
    assert "if (dailyTop >= weeklyBottom) return { position: 'touching', gapPct: 0, ageSeconds };" in body
    assert "const gapPct = (weeklyBottom / dailyTop - 1) * 100;" in body
    assert "return gapPct <= TRENDS_SETUP1_MAX_GAP_PCT ? { position: 'below', gapPct, ageSeconds } : null;" in body
    for old in ("alignment_state", "alignment_changed", "upper_band", "lower_band", "rowTimeframes['1w']"):
        assert old not in body


def test_tag_names_the_weekly_trend_and_the_cross_age():
    js = _js()
    label = js.split("function _trendsSetup1Label(s1) {", 1)[1].split("// Every sidebar filter but SETUPS", 1)[0]
    assert "'Inside weekly trend'" in label and "'Touching weekly trend'" in label
    assert "s1.gapPct.toFixed(1) + '% below weekly trend'" in label
    assert "const age = _trendsFmtAge(s1.ageSeconds, TRENDS_SETUP1_DAILY_TF);" in label
    assert "' · crossed ' + age + ' ago'" in label
    assert "weekly band" not in js


def test_filter_sidebar_and_row_tag_are_wired():
    js = _js()
    assert "if (filters.setup1 && !_trendsSetup1(row.timeframes, filters.setup1Recency, nowMs)) return false;" in js
    sidebar = js.split("function TrendsSidebar(", 1)[1]
    assert sidebar.index("{ title: 'SETUPS' }") < sidebar.index("{ title: 'TREND',")
    assert "label: 'Daily cross under Weekly'" in sidebar
    assert "TRENDS_SETUP1_RECENCY_OPTIONS.map((o) =>" in sidebar
    assert "const s1 = setup1Recency ? _trendsSetup1(row.timeframes, setup1Recency, nowMs) : null;" in js
    assert "_trendsSetup1Label(s1)" in js
    assert "setup1Recency: filters.setup1 ? filters.setup1Recency : null," in js
