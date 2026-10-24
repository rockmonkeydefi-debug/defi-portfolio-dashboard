"""Landing 65 (Oct 24, Glenn "your recs": A, A, A), the Trends page side of the
deeper weekly noodle (static/trends.js).

The weekly noodle now reads about 99 weeks, so weekly flip counts rose (mostly
0-3 on the old ~41 weeks, 2-13 on a 13-coin sample). The Weekly "Hide choppy"
choices move from 1 / 2 / 3 to 8 / 10 / 12, which let through about the same
share of that sample as the old choices did on the old window; the other
timeframes keep theirs. The three tips that name the weekly window say about
99 weeks. The backend side is in tests/test_weekly_noodle_depth.py.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)


def _js():
    with open(os.path.join(ROOT, "static", "trends.js"), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    assert start in text, start
    rest = text.split(start, 1)[1]
    assert end in rest, end
    return rest.split(end, 1)[0]


def test_weekly_hide_choppy_choices():
    js = _js()
    table = _between(js, "const TRENDS_HIDE_CHOPPY_THRESHOLDS = {", "};")
    assert "'1w': [8, 10, 12]," in table
    for kept in ("'1d': [15, 25, 35],", "'12h': [15, 25, 35],", "'4h': [20, 30, 40],", "'1h': [80, 120, 160],"):
        assert kept in table, kept
    assert "75% / 94% / 99% (was 74% / 92% / 97%)" in js                 # how the choices were picked
    assert "(1w's whole range tops out at 12)" in js


def test_the_tips_name_the_new_weekly_window():
    js = _js()
    tips = _between(js, "const TRENDS_TIPS = {", NL + "};" + NL)
    assert "about 300 days on Daily, about 99 weeks on Weekly). Frequent flips" in tips     # Hide choppy
    assert "D about 300 days, W about 99 weeks." in tips                                    # the TF chips
    assert "about 300 on Daily, about 99 weeks on Weekly)." in js                           # the FLIPS column
    assert "41 weeks" not in js
