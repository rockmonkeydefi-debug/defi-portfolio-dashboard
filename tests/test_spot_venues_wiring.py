"""Landing 86: the page side of "Held at" (static/spotpnl.js).

A position's venues come from GET /api/spot/venues and are set with PUT
/api/spot/venues, from the Add Transaction form (a new transaction only) and
from the editor in the expanded position row. The Spot wallet line shows them
after the automatic wallets, marked "(set by you)", with no units. These read
the source and run the page's own helpers in node; the headless checks for the
landing exercise the browser."""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_NODE = shutil.which("node") is not None
needs_node = pytest.mark.skipif(not HAS_NODE, reason="node not installed")
DOT = " " + chr(0xB7) + " "


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _function(src, name):
    start = src.index("function " + name + "(")
    depth, i = 0, src.index("{", start)
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise AssertionError(name)


def _run(expr, data):
    sp, sj, ut = _read("static/spotpnl.js"), _read("static/spotjournal.js"), _read("static/utils.js")
    parts = [_function(ut, "fmtNum"), _function(sj, "sjParseTime"), _function(sj, "sjStamp"),
             _function(sp, "spotHoldFmtUnits"), _function(sp, "spotFmtDate"),
             "const SPOT_NOT_TRACKED = 'not in a tracked wallet';"]
    parts += [_function(sp, n) for n in ("spotWalletTag", "spotVenuesForKey", "spotVenueChoices", "spotVenueListToSend")]
    script = "\n".join(parts) + "\nconst data = JSON.parse(process.argv[1]);\nconsole.log(JSON.stringify(" + expr + "));"
    res = subprocess.run(["node", "-e", script, json.dumps(data)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


# -- source pins ------------------------------------------------------------------

def test_the_page_loads_the_choices_and_saves_through_the_venues_routes_only():
    src = _read("static/spotpnl.js")
    assert "api('/api/spot/venues').then(d => {" in src
    assert src.count("'/api/spot/venues', { method: 'PUT'") == 2          # the row editor and the add form
    assert "position_key: row.position_key, venues: list })" in src
    assert "const list = spotVenueListToSend(picked, other);" in src
    assert "symbol: payload.symbol, chain: chainVal, contract_address: addressVal, venues: heldList, merge: true" in src
    assert "<SpotHeldAt key={'held-' + key} row={r} status={venues.status} saved={spotVenuesForKey(venues.list, key)} options={venues.options} onSaved={onVenuesSaved} />" in src


def test_the_add_form_keeps_held_at_out_of_the_transaction_and_only_for_a_new_one():
    src = _read("static/spotpnl.js")
    form_state = re.search(r"const \[form, setForm\] = useState\(\{[^}]*\}\);", src).group(0)
    assert "heldAt" not in form_state and "held" not in form_state.lower()
    save = _function(src[src.index("function Transactions("):], "save")      # not the row editor's own save
    assert "const heldList = !editId ? spotVenueListToSend(heldAt, heldOther) : [];" in save
    assert save.count("heldAt") == 2 and save.count("heldOther") == 2       # the check before the post, and the list after it
    assert "if (heldList.length) {" in save
    # the transaction body is built from `form` alone: no held-at field can reach the transaction route
    assert "const { closing: _closing, ...fields } = form;" in save and "heldAt" not in save.split("const payload")[1].split("\n")[0]
    # a failed venue save never reopens the form (saving again would add the transaction twice)
    after = save.split("if (why) setHeldNotice(")[1]
    assert "setShowForm(false);" in after and "setErr(" not in after.split("load();")[0]


def test_the_add_form_resets_held_at_each_time_it_opens():
    src = _read("static/spotpnl.js")
    open_add = _function(src, "openAdd")
    assert "setHeldAt([]); setHeldOther(''); setHeldNotice('');" in open_add
    assert "api('/api/spot/venues').then(d => { if (d && Array.isArray(d.options)) setVenueOptions(d.options); })" in open_add


def test_the_row_editor_refreshes_the_choices_and_the_wallet_lines_after_a_save():
    src = _read("static/spotpnl.js")
    fn = _function(src, "onVenuesSaved")
    assert "api('/api/spot/venues')" in fn and "api('/api/spot/locations')" in fn and "setLocs(" in fn and "setVenues(" in fn


def test_the_new_page_code_is_ascii():
    src = _read("static/spotpnl.js")
    block = src[src.index("// \"Held at\" (Landing 86): where a position sits"):src.index("function SpotTrendDot")]
    assert all(ord(c) < 128 for c in block)
    assert "SPOT_VENUE_NAME_MAX = 40" in block


# -- helpers, run in node ------------------------------------------------------------

@needs_node
def test_venues_for_a_key():
    rows = [{"position_key": "ETH", "venue": "A"}, {"position_key": "BTC", "venue": "B"}, None, {"position_key": "ETH", "venue": "C"}]
    assert [v["venue"] for v in _run("spotVenuesForKey(data, 'ETH')", rows)] == ["A", "C"]
    assert _run("spotVenuesForKey(data, 'ETH')", None) == []


@needs_node
def test_choices_keep_the_server_order_add_selected_names_and_repeat_nothing():
    assert _run("spotVenueChoices(data[0], data[1])", [["Hyperliquid", "TxFlow"], ["txflow", "Old place", "Old Place"]]) == [
        "Hyperliquid", "TxFlow", "Old place"]
    assert _run("spotVenueChoices(data[0], data[1])", [None, None]) == []


@needs_node
def test_the_list_to_send_collapses_spaces_adds_other_and_repeats_nothing():
    assert _run("spotVenueListToSend(data[0], data[1])", [["Hyperliquid", " TxFlow "], "  Some   place  "]) == [
        "Hyperliquid", "TxFlow", "Some place"]
    assert _run("spotVenueListToSend(data[0], data[1])", [["Hyperliquid"], "hyperliquid"]) == ["Hyperliquid"]
    assert _run("spotVenueListToSend(data[0], data[1])", [[], ""]) == []
    assert _run("spotVenueListToSend(data[0], data[1])", [None, None]) == []


def _locs(entry):
    return {"status": "ok", "asOf": "2026-11-01T20:00:00+00:00", "oldWallets": [], "positions": {"ETH": entry}}


@needs_node
def test_a_venue_alone_shows_by_name_marked_set_by_you_without_units():
    entry = {"status": "found", "wallets": [{"label": "Hyperliquid RM App", "units": None,
                                             "as_of": "2026-11-01T11:00:00+00:00", "stale": False, "manual": True}]}
    tag = _run("spotWalletTag(data, 'ETH', 'ETH', false)", _locs(entry))
    assert tag["found"] is True and tag["name"] == "Hyperliquid RM App" and tag["manual"] is True and tag["more"] == 0
    assert tag["note"] == ""                                          # the mark is drawn by SpotWalletTag, after the "+N"
    assert "Hyperliquid RM App: set by you on " in tag["title"] and "ETH" not in tag["title"].split(":")[1].split(DOT.strip())[0]
    assert tag["detail"] == "Wallets: " + tag["title"]


@needs_node
def test_automatic_wallets_come_first_and_a_venue_follows_with_its_own_wording():
    entry = {"status": "found", "wallets": [
        {"label": "Desktop Hot", "units": 1.5, "as_of": "2026-11-01T20:00:00+00:00", "stale": False},
        {"label": "Variational", "units": None, "as_of": "2026-11-01T11:00:00+00:00", "stale": False, "manual": True}]}
    tag = _run("spotWalletTag(data, 'ETH', 'ETH', false)", _locs(entry))
    assert tag["name"] == "Desktop Hot" and tag["note"] == "" and tag["more"] == 1 and tag["manual"] is False
    lines = tag["title"].split(DOT)
    assert lines[0] == "Desktop Hot: 1.5 ETH" and lines[1].startswith("Variational: set by you on ")
    hidden = _run("spotWalletTag(data, 'ETH', 'ETH', true)", _locs(entry))
    assert hidden["title"].split(DOT)[1].startswith("Variational: set by you on ")      # a date, not an amount
    assert "1.5" not in hidden["title"]


@needs_node
def test_without_a_venue_the_line_reads_as_before():
    entry = {"status": "not_found", "wallets": []}
    tag = _run("spotWalletTag(data, 'ETH', 'ETH', false)", _locs(entry))
    assert tag["found"] is False and tag["name"] == "not in a tracked wallet"
    plain = {"status": "found", "wallets": [{"label": "Desktop Hot", "units": 1.5, "as_of": "2026-10-30T20:00:00+00:00", "stale": True}]}
    old = _run("spotWalletTag(data, 'ETH', 'ETH', false)", _locs(plain))
    assert old["note"].startswith(" (") and "set by you" not in old["title"]


def test_the_tag_draws_the_set_by_you_mark_after_the_count_and_the_date_note():
    src = _read("static/spotpnl.js")
    tag = src[src.index("function SpotWalletTag("):src.index("// \"Held at\" (Landing 86): where a position sits")]
    assert "{tag.more > 0 ? ' +' + tag.more : ''}{tag.note}{tag.manual ? ' (set by you)' : ''}" in tag
    assert "note: wallets[0].stale ? dateNote(wallets[0].as_of) : ''," in _function(src, "spotWalletTag")   # unchanged


def test_the_limits_agree_between_the_page_and_the_server():
    import web_portfolio as wp
    src = _read("static/spotpnl.js")
    assert int(re.search(r"const SPOT_VENUE_NAME_MAX = (\d+);", src).group(1)) == wp.SPOT_VENUE_NAME_MAX
    assert int(re.search(r"const SPOT_VENUE_MAX = (\d+);", src).group(1)) == wp.SPOT_VENUE_MAX_PER_POSITION
    assert "maxLength={SPOT_VENUE_NAME_MAX}" in src


def test_too_many_places_are_refused_before_the_transaction_is_posted():
    src = _read("static/spotpnl.js")
    save = _function(src[src.index("function Transactions("):], "save")
    before_post = save.split("const d = await api(url")[0]
    assert "heldCheck.length > SPOT_VENUE_MAX" in before_post and "setErr(" in before_post.split("heldCheck.length > SPOT_VENUE_MAX")[1].split("return;")[0]
    row_save = _function(src[src.index("function SpotHeldAt("):], "save")
    assert "list.length > SPOT_VENUE_MAX" in row_save.split("await api(")[0]


def test_the_row_editor_waits_for_the_load_and_never_calls_a_failed_load_not_set():
    src = _read("static/spotpnl.js")
    ed = src[src.index("function SpotHeldAt("):src.index("function SpotTrendDot")]
    assert "{status === 'loading' && <span>loading...</span>}" in ed
    assert "{status === 'error' && <span>could not be loaded" in ed
    assert "{status === 'ok' && saved.length === 0 && !editing && <span>not set</span>}" in ed
    assert "{status === 'ok' && !editing && <button" in ed                  # no Set / Edit until the saved venues are known
    assert "useState({ status: 'loading', options: [], list: [] })" in src
    assert "else setVenues(prev => prev.status === 'ok' ? prev : { ...prev, status: 'error' });" in src


def test_a_save_shows_the_answer_at_once_before_the_refetch():
    src = _read("static/spotpnl.js")
    fn = _function(src, "onVenuesSaved")
    assert fn.index("setVenues(prev => ({ ...prev, list: prev.list.filter(v => v.position_key !== key)") < fn.index("api('/api/spot/venues')")
    assert ".concat((Array.isArray(items) ? items : []).map(v => ({ position_key: key, venue: v.venue, set_at: v.set_at, attached: true }))) }));" in fn


def test_the_add_form_adds_and_says_so():
    src = _read("static/spotpnl.js")
    assert "These are added to what is already set; remove one later on the position row in Open positions." in src
    assert "Leave empty to keep what is already set" not in src
