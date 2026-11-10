"""Landing 97: journal links on the Perps rows (static/perps.js).

The links of a trade (Landing 96's trade_links routes) are listed, edited,
removed and added inside each expanded row's Notes card, Open and Closed, and
the symbol line shows a count from GET /api/trading/trade-links/counts. Links
show no balances, so Hide values leaves them visible. These read the source
only; the browser checks (1920, 1250 and 390px) are in the landing record.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _between(text, start, end):
    assert start in text, start
    rest = text.split(start, 1)[1]
    assert end in rest, end
    return rest.split(end, 1)[0]


def _links_code(js):
    """Everything Landing 97 added in one block: the constants through PerpsJournalLinks."""
    return _between(js, "/* -- journal links (Landing 97)", "function PerpsReviewButtons(")


def _notes_card(js, fn, next_fn):
    body = _between(js, "function " + fn + "(", "function " + next_fn + "(")
    return _between(body, '<PerpsCard part="notes" title="Notes">', "</PerpsCard>")


def test_every_link_route_is_used():
    js = _read("static/perps.js")
    code = _links_code(js)
    assert "'/api/trading/trades/' + encodeURIComponent(tradeId) + '/links'" in code
    assert "{ method: 'POST', body: JSON.stringify(body) }" in code
    assert "{ method: 'PUT', body: JSON.stringify(body) }" in code
    assert "{ method: 'DELETE' }" in code
    assert "api(prpLinksPath(tradeId))" in code                      # the list (GET)
    assert "api('/api/trading/trade-links/counts')" in js


def test_the_route_paths_match_the_server():
    py = _read("web_portfolio.py")
    assert "@app.route('/api/trading/trades/<trade_id>/links', methods=['GET', 'POST'])" in py
    assert "@app.route('/api/trading/trades/<trade_id>/links/<int:link_id>', methods=['PUT', 'DELETE'])" in py
    assert "@app.route('/api/trading/trade-links/counts', methods=['GET'])" in py


def test_limits_match_the_server():
    js = _read("static/perps.js")
    py = _read("web_portfolio.py")
    for js_name, py_name in (("PRP_LINKS_MAX", "TRADE_LINKS_MAX"), ("PRP_LINK_CAPTION_MAX", "TRADE_LINK_CAPTION_MAX"),
                             ("PRP_LINK_URL_MAX", "TRADE_LINK_URL_MAX")):
        js_v = re.search(r"^const " + js_name + r" = (\d+);", js, re.M)
        py_v = re.search(r"^" + py_name + r" = (\d+)", py, re.M)
        assert js_v and py_v and js_v.group(1) == py_v.group(1), js_name


def test_the_link_anchor_opens_safely():
    code = _links_code(_read("static/perps.js"))
    anchors = re.findall(r"<a [^>]*>", code)
    assert len(anchors) == 1
    assert 'href={l.url} target="_blank" rel="noopener noreferrer"' in anchors[0]


def test_no_blocking_dialogs_or_raw_html():
    code = _links_code(_read("static/perps.js"))
    for bad in ("window.confirm", "window.alert", "window.prompt", "confirm(", "alert(", "prompt(",
                "dangerouslySetInnerHTML", "innerHTML"):
        assert bad not in code, bad
    js = _read("static/perps.js")
    assert "dangerouslySetInnerHTML" not in js
    assert js.count("window.confirm(") == 1                          # the manual-trade delete, from before
    assert "window.alert(" not in js and "prompt(" not in js
    assert "Remove this link?" in code and ">Keep</button>" in code   # removal is confirmed inline


def test_journal_links_sit_in_both_notes_cards():
    js = _read("static/perps.js")
    for fn, nxt in (("PerpsOpenRow", "PerpsUntrackedRow"), ("PerpsHistoryRow", "PerpsUnattached")):
        notes = _notes_card(js, fn, nxt)
        editor = notes.index("<PerpsNotesEditor")
        links = notes.index("<PerpsJournalLinks trade={t} onCountChange={onLinkCount} />")
        status = notes.index("<PerpsStatus saving={notesSaver.saving} status={notesSaver.status} />")
        assert editor < links < status, fn
    open_notes = _notes_card(js, "PerpsOpenRow", "PerpsUntrackedRow")
    assert open_notes.index("Followed or deviated is set once the trade closes") < open_notes.index("<PerpsJournalLinks")
    code = _links_code(js)
    assert "<span style={PRP_SECTION}>Journal links</span>" in code
    assert "borderTop: PRP_LINE" in code                              # the 2px divider above the section


def test_the_limit_and_the_messages():
    js = _read("static/perps.js")
    code = _links_code(js)
    assert "const PRP_LINK_LIMIT_TEXT = PRP_LINKS_MAX + ' links is the most a trade can hold; remove one first.';" in code
    assert "{full && <span" in code and "{PRP_LINK_LIMIT_TEXT}" in code
    assert "const canAdd = !!links && url.trim() !== '' && !saving && !full;" in code
    assert "setNote('Already attached.')" in code
    assert 'placeholder="Paste a Discord message link"' in code and 'placeholder="Caption (optional)"' in code
    assert "Loading links..." in code and ">Retry</button>" in code
    py = _read("web_portfolio.py")
    hint = re.search(r"TRADE_LINK_ATTACHMENT_HINT = \((.*?)\)\n", py, re.S).group(1)
    server_text = "".join(re.findall(r'"([^"]*)"', hint))
    js_hint = re.search(r"const PRP_LINK_ATTACHMENT_HINT = (.*?);", code, re.S).group(1)
    assert "".join(re.findall(r"'([^']*)'", js_hint)) == server_text   # the client hint is the server's words


def test_the_attachment_hosts_match_the_server():
    code = _links_code(_read("static/perps.js"))
    body = _between(code, "function prpLinkIsAttachment(", "\n}\n")
    for host in ("'cdn.discordapp.com'", "'media.discordapp.net'", r"/^images-ext-[^.]+\.discordapp\.net$/"):
        assert host in body, host


def test_counts_on_the_symbol_lines():
    js = _read("static/perps.js")
    badge = _between(js, "function PerpsLinkCount(", "\n}\n")
    assert "if (!(n > 0)) return null;" in badge
    assert "title={words} aria-label={words}" in badge and "color: 'var(--text3)'" in badge
    assert "{'\\uD83D\\uDD17 ' + n}" in badge                         # the link symbol, written as an escape
    for fn, nxt in (("PerpsOpenRow", "PerpsUntrackedRow"), ("PerpsHistoryRow", "PerpsUnattached")):
        row = _between(js, "function " + fn + "(", "if (!open) return row;")
        assert row.index('aria-label="Has trade notes"') < row.index("<PerpsLinkCount n={linkCount} />")
    untracked = _between(js, "function PerpsUntrackedRow(", "function PerpsOpenTab(")
    assert "PerpsLinkCount" not in untracked and "linkCount" not in untracked


def test_counts_load_beside_the_trades_and_update_in_place():
    js = _read("static/perps.js")
    load = _between(js, "  function load() {", "  function loadRules() {")
    assert load.index("loadLinkCounts();") < load.index("api('/api/trading/trades')")   # not waited on
    counts = _between(js, "  function loadLinkCounts() {", "  function onLinkCount(")
    assert "mine !== linksReqRef.current || epoch !== linksEpochRef.current" in counts
    assert ".catch(() =>" in counts and "setLoadError" not in counts and "setUpdateError" not in counts
    setter = _between(js, "  function onLinkCount(tradeId, n) {", "  function loadTags() {")
    assert "linksEpochRef.current += 1;" in setter and "setLinkCounts(prev =>" in setter
    assert js.count("linkCounts={linkCounts} onLinkCount={onLinkCount} />}") == 2
    assert js.count("linkCount={(linkCounts || {})[t.trade_id]} onLinkCount={onLinkCount} />)}") == 2


def test_hide_values_does_not_reach_the_links():
    code = _links_code(_read("static/perps.js"))
    assert "hide" not in code and "hideValues" not in code             # nothing in the links reads Hide values


def test_added_text_is_readable():
    code = _links_code(_read("static/perps.js"))
    sizes = [int(x) for x in re.findall(r"fontSize: (\d+)", code)]
    assert sizes and min(sizes) >= 12
    anchor = re.findall(r"<a [^>]*>", code)[0]
    assert "color: 'var(--text)'" in anchor
    for weak in ("var(--text4)'", "#8b98a5", "#6e7781", "opacity"):
        assert ("color: '" + weak) not in code
