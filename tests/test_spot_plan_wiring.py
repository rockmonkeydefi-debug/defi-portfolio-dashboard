"""Landing 59 (Oct 23): the spot plan on the Spot page.

static/spotplan.js holds the plan (SpotPlan) and Doc's band states at open
(SpotPlanBands). It shows in the Open positions row detail (above the
journal) and in Closed trades by trade (after "At open", before the review).
An open Trading-book trade without a plan gets a "No plan" chip in its Trade
opened cell (read out as "Plan missing"). Browser checks (1920, 1250 and
390px) are in the landing record; these pin the wiring, run the real helpers
in node, and check that the page's rules match the server's
(_spot_plan_from_body) on the same drafts.
"""
import json
import os
import re
import shutil
import subprocess
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_NODE = shutil.which("node") is not None
NL = chr(10)
SEP = " " + chr(0xB7) + " "          # the page's middle-dot separator
MASK = chr(0x2022) * 4                # Hide values


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def _list(js, name):
    """The values of one SPL_* list: [['a', 'A'], ...] -> ('a', ...)."""
    body = _between(js, "const " + name + " = [", "];")
    return tuple(part.split("'", 1)[0] for part in body.split("['")[1:])


def test_the_page_loads_the_file_in_order():
    html = _read("templates/index.html")
    tag = '<script type="text/babel" src="/static/spotplan.js?v={{ static_version }}"></script>'
    assert html.count(tag) == 1
    assert html.index("/static/spotjournal.js") < html.index(tag) < html.index("/static/spothistory.js") < html.index("/static/spotpnl.js")


def test_the_value_lists_match_the_server():
    js = _read("static/spotplan.js")
    assert _list(js, "SPL_BASES") == wp.SPOT_PLAN_BASES
    assert _list(js, "SPL_SETUPS") == wp.SPOT_PLAN_SETUPS
    assert _list(js, "SPL_EXITS") == wp.SPOT_PLAN_EXITS
    assert _list(js, "SPL_CONVICTIONS") == wp.SPOT_PLAN_CONVICTIONS
    assert _list(js, "SPL_HORIZONS") == wp.SPOT_PLAN_HORIZONS
    assert "const SPL_THESIS_MAX = %d;" % wp.SPOT_PLAN_THESIS_MAX in js
    assert "const SPL_PX_CHARS = %d;" % wp.SPOT_PLAN_PX_CHARS in js
    assert "const SPL_FIELDS = [" + ", ".join("'%s'" % k for k in wp._SPOT_PLAN_FIELDS) + "];" in js


def test_the_horizon_and_setup_words_are_glenns():
    js = _read("static/spotplan.js")
    labels = ["Trend continuation retest with POI", "Trend continuation retest with SFP/Sweep", "Range Deviation",
              "Range: 3 drives & MSB", "Expansion Candle", "Compression", "VWAP Trend Continuation", "VWAP Range Reversion"]
    body = _between(js, "const SPL_SETUPS = [", "];")
    assert [part.split("'", 1)[0] for part in body.split("', '")[1:]] == labels
    assert "['cyclical', 'Cyclical', 'About 6 to 12 months; mostly majors.']" in js
    assert "['positional', 'Positional', 'About 1 to 3 months; a pullback in a strong coin already up 50% to 3x.']" in js
    assert "['narrative', 'Narrative/Trenches', 'A newer, smaller coin riding a sector story.']" in js


def test_the_component_saves_through_the_route():
    js = _read("static/spotplan.js")
    comp = _between(js, "function SpotPlan({ trade: t, hideValues, onSaved }) {", "window.SpotPlan = SpotPlan;")
    assert "api('/api/trading/trades/' + encodeURIComponent(t.trade_id) + '/spot-plan'," in comp
    assert "{ method: 'PUT', body: JSON.stringify(body) });" in comp
    assert "onClick={() => send(splBody(draft), 'Plan saved')}" in comp
    assert "onClick={() => send({ basis: null }, 'Plan cleared')}>Clear</button>" in comp
    assert "disabled={busy || problems.length > 0 || same}" in comp
    assert "onPick={v => setDraft(prev => splPickBasis(prev, v))}" in comp
    # clearing asks first, inline (no browser dialog)
    assert "onClick={() => setConfirmClear(true)}>Clear plan</button>}" in comp
    assert "confirm(" not in js and "alert(" not in js
    assert '<span className="tv-chip warn" style={{ fontSize: 12, fontWeight: 600 }}>Plan missing</span>' in comp
    assert "<SpotPlanBands trade={t} />" in comp
    assert "/api/trading/trades/" in {r.rule.split("<")[0] for r in wp.app.url_map.iter_rules() if r.rule.endswith("/spot-plan")}


def test_open_positions_wiring():
    js = _read("static/spotpnl.js")
    row = _between(js, "  function positionRow(r) {", "  const head = {")
    assert "const planTrade = t ? { ...t, book, plan_missing: isTrading && !t.plan } : null;" in row
    assert "{planTrade && planTrade.plan_missing && <div style={{ marginTop: 4 }}>" in row
    assert '<span className="tv-chip warn" role="img" aria-label="Plan missing"' in row
    assert "style={{ fontWeight: 600, whiteSpace: 'nowrap', padding: '2px 6px' }}>No plan</span></div>}" in row
    # the chip sits in the Trade opened cell, after the date
    cell = _between(row, 'data-label="Trade opened"', "    </div>;")
    assert cell.index("{opened}") < cell.index("No plan</span>")
    # the plan sits in the detail, after the wallet line and before the journal
    detail = _between(row, '<div className="spot-detail"', "</React.Fragment>;")
    plan = "{planTrade && <SpotPlan key={'plan-' + planTrade.trade_id} trade={planTrade} hideValues={hideValues} onSaved={onPlanSaved} />}"
    assert detail.count(plan) == 1
    assert detail.index("{walletTag && <div") < detail.index(plan) < detail.index("<SpotJournal row={r}")
    saved = _between(js, "  function onPlanSaved(id, plan) {", NL + "  }" + NL)
    assert "open[k] = x.trade_id === id ? { ...x, plan, plan_missing: splMissing(x, plan) } : x;" in saved


def test_closed_by_trade_wiring():
    js = _read("static/spothistory.js")
    assert NL.join(["        <SpotHistoryAtOpen trade={t} />",
                    "        <SpotPlan key={'plan-' + id} trade={t} hideValues={hideValues} onSaved={onPlanSaved} />",
                    "        <SpotHistoryReview key={'review-' + id} trade={t} onSaved={onReviewSaved} />"]) in js
    assert ("    setTrades(prev => prev.map(t => t.trade_id === id ? { ...t, plan, plan_missing: splMissing(t, plan) } : t));"
            in _between(js, "  function onPlanSaved(id, plan) {", NL + "  }" + NL))


def test_text_sizes_and_colours():
    js = _read("static/spotplan.js")
    sizes = [int(x) for x in re.findall("fontSize: ([0-9]+)", js)]
    assert sizes and min(sizes) >= 12
    colours = set(re.findall(r"color: '([^']+)'", js))
    assert colours <= {"var(--text)", "var(--text2)", "var(--text3)", "var(--ok)", "var(--fail)"}, colours
    assert "rgba(255,255,255,0.25)" in js and "rgba(255,255,255,0.6)" in js


# -- the real helpers in node -------------------------------------------------

def _run(script_body, data):
    js = _read("static/spotplan.js")
    helpers = "// [value, label, description]" + _between(js, "// [value, label, description]", "const SPL_BANDS_TIP")
    nl = chr(10)
    script = nl.join([
        "function spotFmtDay(s) { const m = /^([0-9]{4})-([0-9]{2})-([0-9]{2})/.exec(String(s || '')); if (!m) return null;"
        " return ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+m[2] - 1] + ' ' + (+m[3]); }",
        "function spotFmtPx(v) { return '$' + Number(v).toFixed(2); }",
        "function shxDayKey(s) { const m = /^([0-9]{4}-[0-9]{2}-[0-9]{2})/.exec(String(s || '')); return m ? m[1] : null; }",
        helpers,
        "const data = JSON.parse(process.argv[1]);",
        script_body,
    ])
    res = subprocess.run(["node", "-e", script, json.dumps(data)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


FULL = {"basis": "own_setup", "setup": "compression", "thesis": "", "exit_plan": "weekly_flip",
        "invalidation_px": "", "conviction": "high", "horizon": "cyclical"}


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_picking_a_basis():
    out = _run("console.log(JSON.stringify(data.map(c => splPickBasis(c.d, c.b))));", [
        {"d": dict(FULL, basis="", setup="", exit_plan=""), "b": "own_setup"},
        {"d": dict(FULL, exit_plan="target"), "b": "own_setup"},
        {"d": FULL, "b": "analyst_call"},
        {"d": dict(FULL, basis="", exit_plan=""), "b": "other"},
    ])
    assert out[0]["exit_plan"] == "weekly_flip" and out[0]["basis"] == "own_setup"   # preselected
    assert out[1]["exit_plan"] == "target"                                            # a pick already made stays
    assert out[2]["setup"] == "" and out[2]["exit_plan"] == "weekly_flip"         # setup cleared, exit kept
    assert out[3]["exit_plan"] == "" and out[3]["basis"] == "other"                   # no preselect


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_drafts_bodies_and_sameness():
    stored = {"basis": "analyst_call", "setup": None, "thesis": "AI agents rotate next", "exit_plan": "price_level",
              "invalidation_px": "0.025", "conviction": "low", "horizon": "narrative", "saved_at": "2026-10-20T18:00:00+00:00"}
    out = _run("""
const d = splDraft(data.stored);
const edited = Object.assign({}, d, { invalidation_px: '0.0250', thesis: data.messy });
console.log(JSON.stringify({
  empty: splDraft(null), draft: d, body: splBody(d), same: splSame(data.stored, d), sameEdited: splSame(data.stored, edited),
  changed: splSame(data.stored, Object.assign({}, d, { conviction: 'high' })), none: splSame(null, d),
  ownBody: splBody(Object.assign({}, d, { basis: 'other', setup: 'compression' })),
  messyThesis: splThesis(data.messy),
}));""", {"stored": stored, "messy": "  AI" + NL + "agents" + chr(9) + chr(9) + " rotate   next "})
    assert out["empty"] == {k: "" for k in wp._SPOT_PLAN_FIELDS}
    assert out["draft"]["setup"] == "" and out["draft"]["invalidation_px"] == "0.025"
    assert out["body"] == {k: stored[k] for k in wp._SPOT_PLAN_FIELDS}
    assert out["same"] is True and out["sameEdited"] is True                 # same once normalised: Save stays off
    assert out["messyThesis"] == "AI agents rotate next"                      # newlines and tabs too, as the server
    assert out["changed"] is False and out["none"] is False
    assert out["ownBody"]["setup"] is None                               # a setup only goes with an own chart setup


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_the_page_and_the_server_agree_on_what_saves():
    cases = [                                            # (draft, the page lets it save)
        (FULL, True),
        (dict(FULL, basis=""), False),
        (dict(FULL, setup=""), False),
        (dict(FULL, basis="analyst_call", setup="", thesis=""), False),
        (dict(FULL, basis="analyst_call", setup="", thesis="   "), False),
        (dict(FULL, basis="analyst_call", setup="", thesis=" a  call "), True),
        (dict(FULL, basis="other", setup=""), True),
        (dict(FULL, thesis="x" * 200), True),
        (dict(FULL, thesis="x" * 201), False),
        (dict(FULL, thesis="x" * 198 + "   y"), True),       # 200 once the spaces collapse
        (dict(FULL, thesis="x" * 199 + "   y"), False),
        (dict(FULL, exit_plan=""), False),
        (dict(FULL, exit_plan="price_level"), False),
        (dict(FULL, exit_plan="price_level", invalidation_px="1.25"), True),
        (dict(FULL, invalidation_px="0"), False),
        (dict(FULL, invalidation_px="-1"), False),
        (dict(FULL, invalidation_px="abc"), False),
        (dict(FULL, invalidation_px="1e5"), False),           # the page takes plain decimals only
        (dict(FULL, invalidation_px=".5"), True),
        (dict(FULL, invalidation_px="5."), True),
        (dict(FULL, invalidation_px=" 0.0000000123 "), True),
        (dict(FULL, invalidation_px="0." + "0" * 29 + "1"), True),    # 1e-30: the floor
        (dict(FULL, invalidation_px="0." + "0" * 30 + "1"), False),   # 1e-31
        (dict(FULL, invalidation_px="1" * 16), True),
        (dict(FULL, invalidation_px="1" * 17), False),
        (dict(FULL, invalidation_px="1" * 41), False),
        (dict(FULL, conviction=""), False),
        (dict(FULL, horizon=""), False),
    ]
    drafts = [c[0] for c in cases]
    out = _run("console.log(JSON.stringify(data.map(d => ({ problems: splProblems(d), body: splBody(d) }))));", drafts)
    assert [not r["problems"] for r in out] == [c[1] for c in cases], [r["problems"] for r in out]
    for (d, page_ok), r in zip(cases, out):
        body = {k: (v if v != "" else None) for k, v in r["body"].items()}
        plan, err = wp._spot_plan_from_body(body)
        if page_ok:
            assert err is None, (d, body, err)               # what the page saves, the server takes
        elif d.get("invalidation_px") != "1e5":
            assert err is not None, (r["problems"], body)    # what the page blocks, the server refuses


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_problem_messages_in_form_order():
    out = _run("console.log(JSON.stringify(data.map(d => splProblems(d))));", [
        {k: "" for k in wp._SPOT_PLAN_FIELDS},
        dict(FULL, setup="", conviction="", horizon=""),
        dict(FULL, basis="analyst_call", setup="", exit_plan="price_level"),
        dict(FULL, invalidation_px="abc", exit_plan="price_level"),
    ])
    assert out[0] == ["Pick a basis.", "Pick an exit plan.", "Pick conviction.", "Pick a horizon."]
    assert out[1] == ["Pick the setup.", "Pick conviction.", "Pick a horizon."]
    assert out[2] == ["An analyst call needs a one-line thesis.", "A price-level exit needs the invalidation price."]
    assert out[3] == ["The invalidation price must be a positive number."]


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_summary_saved_text_and_missing():
    plan = {"basis": "own_setup", "setup": "trend_retest_poi", "thesis": None, "exit_plan": "price_level",
            "invalidation_px": "158.5", "conviction": "high", "horizon": "positional", "saved_at": "2026-10-21T09:00:00+00:00"}
    out = _run("""
const p = data.plan;
console.log(JSON.stringify({
  shown: splSummary(p, false), hidden: splSummary(p, true),
  other: splSummary(Object.assign({}, p, { basis: 'other', setup: null, invalidation_px: null, exit_plan: 'analyst_exit' }), false),
  afterClose: splSavedText(p, { status: 'closed', closed_at: '2026-10-05' }),
  sameDay: splSavedText(p, { status: 'closed', closed_at: '2026-10-21' }),
  open: splSavedText(p, { status: 'open', closed_at: null }),
  missing: [splMissing({ book: 'trading', status: 'open' }, null), splMissing({ book: 'trading', status: 'partly_closed' }, null),
            splMissing({ book: 'trading', status: 'closed' }, null), splMissing({ book: 'long_term', status: 'open' }, null),
            splMissing({ book: null, status: 'open' }, null), splMissing({ book: 'trading', status: 'open' }, p)],
}));""", {"plan": plan})
    assert out["shown"] == {"basis": SEP.join(["Own chart setup", "Trend continuation retest with POI"]),
                            "details": SEP.join(["Exit: price level", "Invalidation $158.50", "Conviction high", "Horizon positional"])}
    assert out["hidden"]["details"] == SEP.join(["Exit: price level", "Invalidation " + MASK, "Conviction high", "Horizon positional"])
    assert out["other"] == {"basis": "Other", "details": SEP.join(["Exit: analyst's exit call", "Conviction high", "Horizon positional"])}
    assert out["afterClose"] == "Saved Oct 21, after the trade closed"
    assert out["sameDay"] == "Saved Oct 21" and out["open"] == "Saved Oct 21"
    assert out["missing"] == [True, True, False, False, False, False]        # as the server's plan_missing


@pytest.mark.skipif(not HAS_NODE, reason="node not installed")
def test_band_text():
    def part(state, pos, cross):
        return {"state": state, "position": pos, "cross_state": cross, "upper": "2", "lower": "1", "bars": 700}
    trades = [
        {"source": "spot_tx", "book": "trading", "symbol": "ETH", "doc_bands_at_open": None},
        {"source": "spot_tx", "book": "long_term", "symbol": "BTC", "doc_bands_at_open": None},
        {"source": "manual", "book": None, "symbol": "SOL", "doc_bands_at_open": None},
        {"source": "spot_tx", "book": "trading", "symbol": "X", "doc_bands_at_open": {"reason": "not_on_hyperliquid"}},
        {"source": "spot_tx", "book": "trading", "symbol": "X", "doc_bands_at_open": {"reason": "price_mismatch"}},
        {"source": "spot_tx", "book": "trading", "symbol": "X", "doc_bands_at_open": {"reason": "something_new"}},
        {"source": "spot_tx", "book": "trading", "symbol": "ETH", "doc_bands_at_open": {
            "reason": None, "market": "ETH", "scale": 1, "as_of": "2026-10-14T00:00:00+00:00",
            "daily": part("BULLISH", "above", "BULLISH"), "weekly": part("BEARISH", "inside", "BEARISH")}},
        {"source": "spot_tx", "book": "trading", "symbol": "PEPE", "doc_bands_at_open": {
            "reason": None, "market": "kPEPE", "scale": 1000, "as_of": "2026-10-16T00:00:00+00:00",
            "daily": part(None, "below", None), "weekly": {"state": None, "position": None, "cross_state": None, "bars": 120}}},
    ]
    out = _run("console.log(JSON.stringify(data.map(t => splBands(t))));", trades)
    assert out[0] == {"kind": "pending", "text": "Not captured yet"}
    assert out[1] is None and out[2] is None                                  # not captured for these trades
    assert out[3]["text"] == "Not listed on Hyperliquid, so there are no Doc bands."
    assert out[4]["kind"] == "reason" and "likely a different token" in out[4]["text"]
    assert out[5]["text"] == "No Doc bands for this trade."
    ok = out[6]
    assert [p["text"] for p in ok["parts"]] == ["Daily held, close above", "Weekly lost, close inside"]
    assert [p["state"] for p in ok["parts"]] == ["BULLISH", "BEARISH"]
    assert ok["ema"] == SEP.join(["EMA 100 vs 200: Daily above, Weekly below", "candles closed before Oct 14 (UTC)"])
    assert ok["text"] == ("Doc bands at open: Daily held, close above; Weekly lost, close inside. "
                          + ok["ema"] + ".")
    kilo = out[7]
    assert [p["text"] for p in kilo["parts"]] == ["Daily not set, close below", "Weekly: too few candles before the trade day"]
    assert kilo["ema"] == SEP.join(["candles closed before Oct 16 (UTC)", "Hyperliquid market kPEPE"])
