"""Landing 75: the Spot add-transaction form's default date is today's date on
the user's computer (not UTC, which gave tomorrow in a Pacific evening), and
the Total field's hint reads "Total USD incl fees/slippage" on one line.
Pinned as source text.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_the_add_form_starts_on_the_local_date():
    src = _read("static/spotpnl.js")
    assert "function spotLocalToday() {" in src
    assert "d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')" in src
    assert src.count("trade_date: spotLocalToday(), symbol:'', side:'buy'") == 2      # first state and the reset in openAdd
    assert "trade_date: new Date().toISOString()" not in src


def test_the_total_hint_is_short_and_stays_on_one_line():
    src = _read("static/spotpnl.js")
    assert "whiteSpace:'nowrap' }}>Total USD incl fees/slippage</div>" in src
    assert "sent/received including" not in src
