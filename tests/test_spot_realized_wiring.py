"""Landing 18: the Spot page's Open positions table gains a Realized column
(the open trade's realized P&L, from GET /api/trading/trades), and Token
Holdings shows prices with the Spot page's decimals (static/utils.js
fmtTokenPrice: 2 decimals from $100 up, else 4).

Reads the source files, plus one spot_trades.build call that pins the
contract the Realized cell reads (a partly sold trade is "partly_closed" and
carries its own realized P&L). No app or database.
"""
import os
import re

import spot_trades

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _grid_tracks(spec):
    """Number of columns in a grid-template-columns string (repeat(n, x) counts n)."""
    count = 0
    for m in re.finditer(r"repeat\((\d+),", spec):
        count += int(m.group(1))
    rest = re.sub(r"repeat\(\d+,(?:[^()]|\([^()]*\))*\)", " ", spec)
    rest = re.sub(r"minmax\([^()]*\)", " TRACK ", rest)
    count += len(rest.split())
    return count


def test_one_shared_token_price_rule():
    utils = _read("static/utils.js")
    assert re.search(r"function fmtTokenPrice\(value\) \{\n  return fmtPrice\(value, Math\.abs\(Number\(value\) \|\| 0\) >= 100 \? 2 : 4\);\n\}",
                     utils)
    spot = _read("static/spotpnl.js")
    assert re.search(r"function spotFmtPx\(v\) \{\n  return fmtTokenPrice\(v\);\n\}", spot)


def test_token_holdings_price_uses_the_shared_rule():
    src = _read("static/portfolio2.js")
    assert "fmtTokenPrice(t.price_usd)" in src
    assert "fmtPrice(t.price_usd)" not in src


def test_realized_column_sits_after_unr_pct():
    src = _read("static/spotpnl.js")
    m = re.search(r"const SPOT_OPEN_GRID = '([^']*)'\n  \+ '([^']*)';", src)
    assert m, "SPOT_OPEN_GRID not found"
    assert _grid_tracks(m.group(1) + m.group(2)) == 12
    head = src.index("<span style={right}>Unr %</span>")
    assert head < src.index(">Realized</span>", head) < src.index(">% of spot</span>", head)
    row = src.index("num('Unr %'")
    assert row < src.index("num('Realized', realized.text", row) < src.index("num('% of spot'", row)
    assert "const realized = spotRealizedCell(t, trades.status, r.realized_pnl_usd, hideValues);" in src


def test_realized_cell_reads_the_open_trade():
    src = _read("static/spotpnl.js")
    body = src[src.index("function spotRealizedCell("):src.index("function SpotTrendDot(")]
    assert "t.status !== 'partly_closed'" in body
    assert "Number(t.net_pnl)" in body
    assert "hideValues ? '••••'" in body
    assert "amount hidden" in body


def test_a_partly_sold_trade_carries_its_own_realized_pnl():
    key = "base 0xabc"
    rows = [
        {"id": 1, "key": key, "symbol": "TKN", "side": "buy", "units": 10.0, "total": 100.0, "trade_date": "2026-09-01"},
        {"id": 2, "key": key, "symbol": "TKN", "side": "sell", "units": 10.0, "total": 150.0, "trade_date": "2026-09-05"},
        {"id": 3, "key": key, "symbol": "TKN", "side": "buy", "units": 10.0, "total": 200.0, "trade_date": "2026-09-10"},
        {"id": 4, "key": key, "symbol": "TKN", "side": "sell", "units": 4.0, "total": 60.0, "trade_date": "2026-09-12"},
    ]
    built = spot_trades.build(rows)
    trades = [t for t in built["trades"] if t["key"] == key]
    assert [t["status"] for t in trades] == ["closed", "partly_closed"]
    assert abs(trades[0]["realized_pnl"] - 50.0) < 1e-9          # the earlier trade
    assert abs(trades[1]["realized_pnl"] - (60.0 - 80.0)) < 1e-9  # this trade only: 4 units at $20 cost
