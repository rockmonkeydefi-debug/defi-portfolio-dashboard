"""Landing 77: the note image storage meter ("Images: 23.4 of 100 MB").

Source-level wiring checks, in the style of the other dashboard wiring tests:
the shared component and its model in static/dashboard.js, the Dashboard card
that mounts it, the stylesheet rules, and the route reply the meter reads.
The behaviour (text, bar, colours, failure handling) is checked in a headless
browser, not here.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _between(text, start, end):
    assert start in text, start
    rest = text.split(start, 1)[1]
    assert end in rest, end
    return rest.split(end, 1)[0]


def _model():
    return _between(_read("static/dashboard.js"), "function _dashImageMeterModel(", NL + "}" + NL)


def _meter():
    return _between(_read("static/dashboard.js"), "function ImageStorageMeter(", NL + "}" + NL)


def test_the_model_builds_the_ruled_text_and_thresholds():
    m = _model()
    assert "'Images: ' + mb(bytes).toFixed(1) + ' of ' + mb(max).toFixed(1).replace(/\\.0$/, '') + ' MB'" in m
    assert "const mb = (n) => n / (1024 * 1024);" in m
    assert "pct >= 95 ? 'neg' : pct >= 80 ? 'warn' : 'ok'" in m
    assert "Math.min(100, (bytes / max) * 100)" in m
    # unusable replies give null, never a guess
    assert "max <= 0" in m and "bytes < 0" in m and "!isFinite(bytes)" in m and "!isFinite(max)" in m


def test_the_component_reads_the_usage_route_and_keeps_the_last_good_figures():
    c = _meter()
    assert "fetch('/api/note-images/usage')" in c
    assert "}, [refreshKey]);" in c
    assert "if (alive)" in c and "alive = false" in c                    # no state set after unmount
    assert "'Images: unavailable'" in c and "'Images: ' + String.fromCharCode(0x2026)" in c
    assert "setFailed(true)" in c and "setUsage(null)" not in c          # a failed read keeps what was shown
    assert "minWidth: model.pct > 0 ? 2 : 0" in c and "min-width" not in _between(_read("static/style.css"), ".img-meter-fill {", "}")
    assert 'role="progressbar"' in c and 'aria-label="Note image storage used"' in c


def test_the_component_is_shared_and_the_dashboard_mounts_it_last():
    js = _read("static/dashboard.js")
    assert "window.ImageStorageMeter = ImageStorageMeter;" in js
    screen = js.split("function DashboardScreen(", 1)[1]
    card = '<div className="dash-card">' + NL + "        <ImageStorageMeter refreshKey={refreshTrigger} />"
    assert card in screen
    assert screen.index("<DashLendingCard") < screen.index("<ImageStorageMeter")
    assert js.count("<ImageStorageMeter") == 1


def test_no_other_script_defines_the_names():
    for name in ("ImageStorageMeter", "_dashImageMeterModel"):
        owners = []
        for fn in sorted(os.listdir(os.path.join(ROOT, "static"))):
            if fn.endswith(".js") and re.search(r"(function|const|let|var)\s+" + name + r"\b", _read("static/" + fn)):
                owners.append(fn)
        assert owners == ["dashboard.js"], (name, owners)


def test_the_stylesheet_keeps_the_meter_readable():
    css = _read("static/style.css")
    assert ".img-meter-text { font-size:13px; color:var(--dash-text);" in css
    track = _between(css, ".img-meter-track {", "}")
    assert "height:8px" in track
    assert "rgba(255,255,255,0.18)" in track and "1px solid rgba(255,255,255,0.28)" in track
    assert "background:var(--dash-pos)" in _between(css, ".img-meter-ok {", "}")      # green, not the orange accent (it reads as the warning)
    assert "background:var(--dash-warn)" in _between(css, ".img-meter-warn {", "}")
    assert "background:var(--dash-neg)" in _between(css, ".img-meter-neg {", "}")


def test_the_route_still_returns_the_fields_the_meter_reads():
    py = _read("web_portfolio.py")
    usage = _between(py, "def _note_images_usage(conn):", NL + NL)
    for key in ('"count"', '"bytes"', '"max_bytes"'):
        assert key in usage, key
    assert "@app.route('/api/note-images/usage', methods=['GET'])" in py
