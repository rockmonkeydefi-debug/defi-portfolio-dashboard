"""Landing 74: the Spot add-transaction form's "Close position" option, pinned
as source text (the server side is tests/test_spot_close_position.py): the
checkbox on a sell in the add form only, the disabled Units field, the
preview line from GET /api/spot/transactions/open-units, and what save sends.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_the_form_offers_close_position_on_a_sell_in_the_add_form_only():
    src = _read("static/spotpnl.js")
    assert "const closingNow = !!(showForm && !editId && form.closing && form.side === 'sell');" in src
    assert "{form.side === 'sell' && <label" in src and "/>Close Position</label>}" in src
    assert "closing:e.target.value==='sell'?form.closing:false" in src          # the add form's Side list turns it off
    assert src.count("Close Position</label>") == 1                 # not in the edit row
    assert "value={closingNow ? '' : form.units} disabled={closingNow} placeholder={closingNow ? 'All open units' : ''}" in src
    assert "closing:false });" in src and src.count("closing:false") >= 3          # initial state and openAdd reset it


def test_the_page_previews_with_the_server_and_drops_late_answers():
    src = _read("static/spotpnl.js")
    assert "api('/api/spot/transactions/open-units?' + q.toString())" in src
    assert "symbol: form.symbol.trim(), date: form.trade_date, chain: form.chain.trim(), contract_address: form.contract_address.trim()" in src
    assert "if (!stale && d) setClosePreview({ units: d.open_units, asOf: d.as_of });" in src
    assert "if (!stale) setClosePreview({ error: extractApiErrorMessage(e) });" in src
    assert "return () => { stale = true; clearTimeout(t); };" in src
    assert "}, [closingNow, form.symbol, form.trade_date, form.chain, form.contract_address]);" in src
    assert "units open as of {closePreview.asOf}</div>" in src and "whiteSpace:'nowrap'" in src
    assert 'role="alert"' in src[src.index("closePreview.error"):src.index("closePreview.error") + 200]


def test_save_sends_close_position_and_does_not_need_units_for_it():
    src = _read("static/spotpnl.js")
    assert "const closing = !!(!editId && form.closing && form.side === 'sell');" in src
    assert "(!closing && !form.units)" in src
    assert "const { closing: _closing, ...fields } = form;" in src
    assert "if (closing) { payload.close_position = true; payload.units = ''; }" in src
    assert "payload = { ...fields," in src
