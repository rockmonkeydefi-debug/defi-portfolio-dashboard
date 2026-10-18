"""Trends "Compression under Weekly" setup (Landing 49, Oct 17).

Glenn asked for coins where the Daily and Weekly Trend bands come together
around price (spec Part F). A history test on 43 coins found these
compressions rose no more often than ordinary days, so he ruled (14:51) a
browser-only watch-list filter with no schema change (1-A) and no above-side
cases (2-B). static/trends.js reads the doc_* EMAs the scan already stores
(Landing 47: Daily Trend on the 4h row, Weekly Trend on the 1d row) and the
1d row's last closed daily close. Browser checks (1920, 1250 and 390px) are
in the landing record; these pin the wiring.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(ROOT, "static", "trends.js"), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def test_constants_and_default():
    js = _js()
    assert "const TRENDS_COMPRESSION_MAX_WIDTH_PCT = 15;" in js
    assert "const TRENDS_COMPRESSION_PRICE_PCT = 3;" in js
    assert "  compression: false," in _between(js, "const TRENDS_FILTER_DEFAULTS = {", "};")


def test_helper_reads_the_doc_emas_and_fails_closed():
    body = _between(_js(), "function _trendsCompression(rowTimeframes) {", "function _trendsCompressionLabel(")
    assert "const d = rowTimeframes[TRENDS_SETUP1_DAILY_TF];" in body
    assert "const w = rowTimeframes[TRENDS_SETUP1_WEEKLY_TF];" in body
    assert "const emas = [d.doc_ema_fast, d.doc_ema_slow, w.doc_ema_fast, w.doc_ema_slow];" in body
    assert "const close = w.last_close;" in body
    assert "if (!emas.concat([close]).every((x) => typeof x === 'number' && isFinite(x) && x > 0)) return null;" in body
    assert "const widthPct = (top - bottom) / close * 100;" in body
    assert "if (widthPct > TRENDS_COMPRESSION_MAX_WIDTH_PCT) return null;" in body
    assert "if (close < bottom * (1 - pad) || close > top * (1 + pad)) return null;" in body
    assert "if (!(dailyMid < weeklyMid)) return null;" in body


def test_filter_tag_sidebar_and_tip_are_wired():
    js = _js()
    passes = _between(js, "function _trendsPassesSearchAndSidebar(", "function _trendsSortValue(")
    assert "if (filters.compression && !_trendsCompression(row.timeframes)) return false;" in passes
    assert "const comp = compressionOn ? _trendsCompression(row.timeframes) : null;" in js
    assert "_trendsCompressionLabel(comp)" in js
    assert "return 'Compressed · ' + c.widthPct.toFixed(1) + '% wide';" in js
    assert "compressionOn: filters.compression," in js
    side = _between(js, "function TrendsSidebar(", "/* ── main screen ── */")
    setups = _between(side, "{ title: 'SETUPS' }", "{ title: 'TREND',")
    assert setups.index("label: 'Daily cross under Weekly'") < setups.index("label: 'Compression under Weekly'")
    assert "checked: filters.compression, onCheck: (v) => set({ compression: v })," in setups
    assert "borderTop: '2px solid ' + TRENDS_BORDER" in setups
    tip = _between(js, "  compression: {", "  trend: {")
    assert "these rose no more often than ordinary days, so treat it as a watch list, not a signal" in tip
    assert "and the Daily Trend below the Weekly Trend" in tip
