"""Token Holdings shows a "stale" chip on a custom token whose balance is the
last good read (Landing 39). Source-text checks of static/portfolio2.js; the
behaviour is covered by tests/test_custom_token_balance_stale.py (the row
fields) and the chat-side browser check."""
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / "static" / "portfolio2.js").read_text(encoding="utf-8")


def _chip():
    start = SRC.index("t.balance_stale === true")
    return SRC[start - 40:SRC.index("</span>}", start) + 8]


def test_chip_reads_the_row_flag_and_skips_the_zero_summary_row():
    chip = _chip()
    assert "t.source === 'custom' && t.balance_stale === true && !t._consolidated_zero" in chip
    assert 'className="tv-chip warn"' in chip
    assert ">stale</span>}" in chip
    assert "fontSize:11" in chip


def test_chip_sits_next_to_the_custom_chip():
    custom = SRC.index(">custom</span>}")
    assert custom < SRC.index("t.balance_stale === true") < custom + 200


def test_hover_names_the_time_and_the_reason_without_amounts():
    chip = _chip()
    assert "title={ctBalanceStaleTitle(t.balance_as_of)}" in chip
    start = SRC.index("function ctBalanceStaleTitle(asOf)")
    end = SRC.index("return 'Balance as of '", start)
    body = SRC[start:SRC.index("read';", end) + 6]
    assert "'Balance as of ' + when + ' — the last refresh failed, so this is the last good read'" in body
    assert "'unknown'" in body and "isFinite(d.getTime())" in body
    assert "value_usd" not in body and "t.balance" not in body     # a time, never an amount


def test_helper_is_defined_once():
    assert SRC.count("function ctBalanceStaleTitle(") == 1
