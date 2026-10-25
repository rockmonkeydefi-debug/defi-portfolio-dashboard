"""Trends "BTC context" strip (Landing 68, Glenn Oct 25).

Glenn: alt trades are better entered in confluence with BTC. An alt long while
BTC tests support is good; while BTC tests resistance and may struggle to move
up it is a reason to hold off. The strip above both Trends tabs shows where BTC
sits against its own noodle band and POI on 1D / 4H / 1H. It is display only: it
filters nothing and feeds no rule (the advisor waits for counted trades; a later
landing records the same reading at entry). It adds no backend field: it reads
the BTC row of the noodle-state response the page already loads.

A rising band is support, a falling band is resistance, a flat band makes no
claim. "Testing" = price inside the band or within a quarter of the band's width
of its edge (the band's width is ATR-proportional, so band widths stand in for
ATR). A POI exists only where the scan found one for a respected trend; below
price it is support, above price resistance, price inside it follows the band's
slope; "approaching" = outside it but within one band width of its edge.
Browser checks (1920, 1250 and 390px) are in the landing record; these pin the
constants, the wiring and the readings.
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


def test_constants():
    js = _js()
    assert "const TRENDS_BTC_SYMBOL = 'BTC';" in js
    assert "const TRENDS_BTC_TFS = ['1d', '4h', '1h'];" in js
    assert "const TRENDS_BTC_TESTING_BAND_WIDTHS = 0.25;" in js
    assert "const TRENDS_BTC_APPROACH_BAND_WIDTHS = 1;" in js
    assert "const TRENDS_BTC_STALE_BARS = 2;" in js


def test_the_strip_sits_above_the_search_box_on_both_tabs_and_reads_the_unfiltered_rows():
    js = _js()
    screen = js.split("function TrendsScreen() {", 1)[1]
    call = "React.createElement(TrendsBtcStrip, { rows, nowMs }),"
    assert screen.count(call) == 1
    # inside the branch shared by both tabs, before the search box
    assert screen.index(call) < screen.index("placeholder: 'Search name, symbol")
    assert screen.index("tab === 'trends' ? React.createElement('div', { style: { marginBottom: 16 } },") < screen.index(call)
    # `rows` is the raw response, not a filtered list
    assert "const rows = data.symbols;" in screen


def test_the_strip_is_display_only():
    js = _js()
    strip = _between(js, "function TrendsBtcStrip({ rows, nowMs }) {", "respected trend tab (Landing 50c)")
    for banned in ("fetch(", "setFilters", "setSort", "onClick", "localStorage", "setInterval", "setTimeout", "useEffect"):
        assert banned not in strip, banned
    assert "rows.find((r) => r.symbol === TRENDS_BTC_SYMBOL)" in strip
    # the tip is the existing header tip, with the explanation text in it
    assert "React.createElement(TrendsHeaderTip, { tip: TRENDS_BTC_TIP, text: 'BTC CONTEXT', arrow: '' })" in strip
    tip = _between(js, "const TRENDS_BTC_TIP = {", "};")
    assert "title: 'BTC context'" in tip and "Display only: it does not filter the table." in tip
    assert "TRENDS_BTC_TESTING_BAND_WIDTHS" in tip and "TRENDS_BTC_APPROACH_BAND_WIDTHS" in tip
    # no explanation text left under the strip
    assert "Testing = price inside" not in js


def test_a_missing_btc_row_says_so():
    js = _js()
    strip = _between(js, "function TrendsBtcStrip({ rows, nowMs }) {", "respected trend tab (Landing 50c)")
    assert "'BTC is not in the scan yet.'" in strip
    assert "No row for this timeframe yet" in strip and "Row has no usable band or price" in strip
    assert "No POI on this timeframe" in strip


def _run(cases):
    """Run the real _trendsBtcReading from static/trends.js in node."""
    js = _js()
    nl = chr(10)
    consts = nl.join(re.findall(r"^const TRENDS_BTC_[A-Z_]+ = .*;$", js, re.M)
                     + re.findall(r"^const TRENDS_RESPECT_TF_SECONDS = .*;$", js, re.M))
    poi = "function _trendsPoi(r) {" + _between(js, "function _trendsPoi(r) {", nl + "}" + nl) + nl + "}"
    reading = "function _trendsBtcReading(" + _between(js, "function _trendsBtcReading(", "function TrendsBtcChip(")
    script = nl.join([
        consts, poi, reading,
        "const cases = JSON.parse(process.argv[1]);",
        "console.log(JSON.stringify(cases.map((c) => _trendsBtcReading(c.tf, c.row, c.now))));",
    ])
    res = subprocess.run(["node", "-e", script, json.dumps(cases)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


NOW = 1792324200000                       # 2026-10-18T12:30:00Z in ms
FRESH = "2026-10-18T12:24:00+00:00"       # 6 minutes old


def _row(state, lo, up, price, poi=None, computed=FRESH):
    r = {"state": state, "lower_band": lo, "upper_band": up, "price": price, "computed_at": computed}
    if poi:
        r.update(poi_type=poi[0], poi_top=poi[1], poi_bottom=poi[2])
    return r


def _read(tf, row, now=NOW):
    return _run([{"tf": tf, "row": row, "now": now}])[0]


KINDS = [
    # state, band 100..200 (width 100), price -> kind
    ("BULLISH", 150, "sup"), ("BULLISH", 100, "sup"), ("BULLISH", 200, "sup"),
    ("BULLISH", 225, "sup"), ("BULLISH", 226, "ext"), ("BULLISH", 300, "ext"),
    ("BULLISH", 75, "sup"), ("BULLISH", 74, "lost"), ("BULLISH", 10, "lost"),
    ("BEARISH", 150, "res"), ("BEARISH", 75, "res"), ("BEARISH", 74, "ext"), ("BEARISH", 10, "ext"),
    ("BEARISH", 225, "res"), ("BEARISH", 226, "reclaim"), ("BEARISH", 400, "reclaim"),
    ("WARMUP", 150, "flat"), ("WARMUP", 226, "ext"), ("WARMUP", 74, "ext"), ("WARMUP", 225, "flat"),
    (None, 150, "flat"),
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_reading_of_a_band_for_every_side_and_distance():
    cases = [{"tf": "4h", "row": _row(st, 100, 200, p), "now": NOW} for st, p, _ in KINDS]
    for (st, p, want), got in zip(KINDS, _run(cases)):
        assert got["kind"] == want, (st, p, got)
        assert got["poi"] is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_distance_is_in_band_widths_not_price_units():
    # the same shape at a different scale reads the same
    for scale in (1, 0.001, 650):
        got = _read("1d", _row("BULLISH", 100 * scale, 200 * scale, 220 * scale))
        assert got["kind"] == "sup" and got["side"] == "above"
        assert abs(got["gap"] - 0.20) < 1e-9
        got = _read("1d", _row("BULLISH", 100 * scale, 200 * scale, 230 * scale))
        assert got["kind"] == "ext" and abs(got["gap"] - 0.30) < 1e-9


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_side_and_gap_are_reported():
    assert _read("4h", _row("BULLISH", 100, 200, 150))["side"] == "in"
    assert _read("4h", _row("BULLISH", 100, 200, 150))["gap"] == 0
    g = _read("4h", _row("BULLISH", 100, 200, 60))
    assert g["side"] == "below" and abs(g["gap"] - 0.4) < 1e-9
    g = _read("4h", _row("BEARISH", 100, 200, 260))
    assert g["side"] == "above" and abs(g["gap"] - 0.6) < 1e-9


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_unusable_rows_read_as_no_data():
    bad = [None, {}, _row("BULLISH", 100, 200, None), _row("BULLISH", None, 200, 150), _row("BULLISH", 100, None, 150),
           _row("BULLISH", 200, 100, 150), _row("BULLISH", 100, 100, 100), _row("BULLISH", "100", 200, 150),
           _row("BULLISH", 100, 200, "150")]
    for got in _run([{"tf": "1d", "row": b, "now": NOW} for b in bad]):
        assert got == {"kind": "nodata"}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_a_poi_below_price_is_support_above_price_resistance_and_inside_follows_the_slope():
    # band 100..200 bullish, price 150 (inside the band)
    below = _read("4h", _row("BULLISH", 100, 200, 150, ("OB", 130, 120)))["poi"]
    assert below["side"] == "sup" and below["kind"] == "near" and abs(below["gap"] - 0.2) < 1e-9
    above = _read("4h", _row("BULLISH", 100, 200, 150, ("FVG", 170, 160)))["poi"]
    assert above["side"] == "res" and above["kind"] == "near" and abs(above["gap"] - 0.1) < 1e-9
    inside_bull = _read("4h", _row("BULLISH", 100, 200, 150, ("OB", 155, 145)))["poi"]
    assert inside_bull["side"] == "sup" and inside_bull["kind"] == "at" and inside_bull["gap"] == 0
    inside_bear = _read("4h", _row("BEARISH", 100, 200, 150, ("OB", 155, 145)))["poi"]
    assert inside_bear["side"] == "res" and inside_bear["kind"] == "at"
    inside_flat = _read("4h", _row("WARMUP", 100, 200, 150, ("OB", 155, 145)))["poi"]
    assert inside_flat["side"] == "sup" and inside_flat["kind"] == "at"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_a_poi_is_approaching_within_one_band_width_and_not_close_beyond():
    # price 150; POI bottom 250 is 100 above = exactly one band width (inclusive)
    assert _read("4h", _row("BULLISH", 100, 200, 150, ("OB", 260, 250)))["poi"]["kind"] == "near"
    assert _read("4h", _row("BULLISH", 100, 200, 150, ("OB", 261, 251)))["poi"]["kind"] == "far"
    # and below price: top 50 is 100 below
    assert _read("4h", _row("BULLISH", 100, 200, 150, ("OB", 50, 40)))["poi"]["kind"] == "near"
    assert _read("4h", _row("BULLISH", 100, 200, 150, ("OB", 49, 40)))["poi"]["kind"] == "far"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_price_inside_a_poi_decides_a_mid_range_reading():
    # bullish band far below price: mid-range on the band alone, support when price is inside an order block
    assert _read("4h", _row("BULLISH", 100, 200, 400))["kind"] == "ext"
    assert _read("4h", _row("BULLISH", 100, 200, 400, ("OB", 410, 390)))["kind"] == "sup"
    assert _read("4h", _row("BEARISH", 100, 200, 20, ("FVG", 30, 10)))["kind"] == "res"
    # not inside it: no change
    assert _read("4h", _row("BULLISH", 100, 200, 400, ("OB", 380, 370)))["kind"] == "ext"
    # a band reading is never overridden
    assert _read("4h", _row("BULLISH", 100, 200, 10, ("OB", 20, 5)))["kind"] == "lost"
    assert _read("4h", _row("BEARISH", 100, 200, 250, ("FVG", 260, 240)))["kind"] == "reclaim"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_an_incomplete_or_unknown_poi_is_no_poi():
    base = _row("BULLISH", 100, 200, 150)
    for extra in ({"poi_type": "OB", "poi_top": 160}, {"poi_type": "OB", "poi_bottom": 140},
                  {"poi_type": "BB", "poi_top": 160, "poi_bottom": 140},
                  {"poi_type": None, "poi_top": 160, "poi_bottom": 140},
                  {"poi_type": "OB", "poi_top": "160", "poi_bottom": 140}):
        assert _read("1h", dict(base, **extra))["poi"] is None, extra


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_a_row_is_stale_after_two_bars_of_its_timeframe():
    # 1h: 2 bars = 120 min; 4h: 480 min; 1d: 2880 min
    def at(minutes):
        ms = NOW - minutes * 60000
        import datetime
        return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    for tf, limit in (("1h", 120), ("4h", 480), ("1d", 2880)):
        assert _read(tf, _row("BULLISH", 100, 200, 150, computed=at(limit)))["stale"] is False, tf
        assert _read(tf, _row("BULLISH", 100, 200, 150, computed=at(limit + 1)))["stale"] is True, tf
        assert _read(tf, _row("BULLISH", 100, 200, 150, computed=at(1)))["stale"] is False, tf
    # an unreadable or missing time is not stale (the age line is skipped)
    for bad in (None, "not a time", 12345):
        got = _read("4h", _row("BULLISH", 100, 200, 150, computed=bad))
        assert got["stale"] is False and got["ageMs"] is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_a_price_exactly_on_an_edge_is_inside_the_band_and_inside_the_poi():
    for p in (100, 200):
        got = _read("4h", _row("BULLISH", 100, 200, p))
        assert got["side"] == "in" and got["gap"] == 0, p
    for p in (145, 155):
        got = _read("4h", _row("BULLISH", 100, 200, p, ("OB", 155, 145)))["poi"]
        assert got["kind"] == "at" and got["gap"] == 0, p
