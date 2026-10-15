"""Dashboard equity chart wiring for runs left out of the chart (Landing 42, Oct 15).

static/dashboard.js reads the chart route's left_out list, draws a hollow
amber dot for each run (DashLeftOutDot on a second, invisible Area), lists
the run's reasons in the tooltip, names the change in the tooltip of the
first point after a definition seam, and no longer shows the footer legend
or the "runs left out" note ("Latest snapshot" stays). The browser checks
(1920, 1250 and 390px) are in the landing record; these pin the wiring.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(ROOT, "static", "dashboard.js"), encoding="utf-8") as fh:
        return fh.read()


def test_left_out_runs_are_loaded_and_drawn():
    js = _js()
    assert "leftOut: withMs(d.left_out)" in js
    assert "_dashChartRows(inRange, leftOut, seams, showingAll ? -Infinity : cutoff)" in js
    assert '<Area dataKey="gap" type="linear" stroke="none" fill="none"' in js
    assert "dot={DashLeftOutDot}" in js
    assert 'className="dash-leftout-dot"' in js and 'fill="var(--dash-card)"' in js
    assert 'stroke="var(--dash-warn)"' in js
    assert "connectNulls activeDot" in js                     # the line runs straight past a left-out run


def test_tooltip_lists_reasons_and_names_the_seam():
    js = _js()
    assert "Run left out of the chart" in js
    assert "shown.map((r, i) =>" in js and "lo.leftOut.slice(0, keep - 1)" in js
    assert "'Definition change: ' + (DASH_SEAM_CHANGE[p.seamTo]" in js
    assert "3: 'TxFlow counted from here'" in js
    assert "nearLeftOut={nearLeftOut} narrow={narrow}" in js
    assert "position={narrow ? { x: 72, y: 0 } : undefined}" in js
    assert "const keep = narrow ? 3 : DASH_TIP_REASONS;" in js and "const DASH_TIP_REASONS = 5;" in js
    assert "{'and ' + more + ' more'}" in js
    assert "for (const lo of [...leftOut].sort((a, b) => a.ms - b.ms)) {" in js


def test_footer_keeps_only_latest_snapshot():
    js = _js()
    assert "left out: a wallet failed" not in js
    assert "Total portfolio value" not in js.split("function DashEquityCard", 1)[1].split("function DashboardScreen(", 1)[0]
    assert "'Definition change · '" not in js and "'Definition changes · '" not in js
    assert "Latest snapshot {end ? _dashClock(new Date(end.ms)) : '—'}" in js


def test_derived_figures_still_use_drawn_points_only():
    js = _js()
    # change, 24h change, high / low and the y-axis come from inRange / points, never the merged rows
    assert "const rangeChange = inRange.length >= 2 ? _dashChange(first, last) : null;" in js
    assert "for (const p of inRange) {" in js and "if (!hiP || p.total > hiP.total) hiP = p;" in js
    assert "else if (inRange.length < 2) body = <div style={emptyStyle}>No portfolio history yet</div>;" in js
