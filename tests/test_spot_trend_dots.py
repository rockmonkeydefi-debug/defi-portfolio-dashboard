"""Tests for the Spot page trend dots (HANDOFF_spot_perps_rebuild ruling 3.3,
Landing 2a): the shared helpers _noodle_symbol_match (extracted from
_trades_weekly_view, no behaviour change) and _noodle_band_position, and
GET /api/spot/trend-dots.

Every route test runs against a fresh temporary database (portfolio_db.get_db_path
monkeypatched, then init_db), the pattern test_spot_note_updates.py uses, with
the noodle staleness trigger stubbed so no scan thread starts. Symbols and
prices are made up; no addresses are needed.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern) so no
thread starts.
"""
import math
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

from src.storage import portfolio_db

AT = "2026-10-03T12:00:00+00:00"


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    conn = portfolio_db.get_connection()
    yield conn
    conn.close()


@pytest.fixture
def kicks(monkeypatch):
    calls = []
    monkeypatch.setattr(wp, "_maybe_kick_noodle_auto_refresh", lambda: calls.append(1) or False)
    return calls


@pytest.fixture
def client(db, kicks, monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def tx(db, symbol):
    db.execute("INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, chain, "
               "contract_address) VALUES ('2026-09-20', ?, 'buy', 10, 100, 100, '', '')", (symbol,))
    db.commit()


def noodle(db, symbol, timeframe, price, upper, lower, state="BULLISH", computed_at=AT):
    db.execute("INSERT INTO noodle_state (symbol, timeframe, state, price, upper_band, lower_band, computed_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?)", (symbol, timeframe, state, price, upper, lower, computed_at))
    db.commit()


def dots(client):
    r = client.get('/api/spot/trend-dots')
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


# ── _noodle_band_position ───────────────────────────────────────────────────

@pytest.mark.parametrize("price, upper, lower, expected", [
    (105.0, 110.0, 90.0, "touch"),
    (110.0, 110.0, 90.0, "touch"),            # upper edge counts as touching
    (90.0, 110.0, 90.0, "touch"),             # lower edge counts as touching
    (110.01, 110.0, 90.0, "above"),
    (89.99, 110.0, 90.0, "below"),
    ("105", "110", "90", "touch"),            # numeric strings are read as numbers
    (100.0, 100.0, 100.0, "touch"),           # a zero-width band
    (None, 110.0, 90.0, None),
    (105.0, None, 90.0, None),
    (105.0, 110.0, None, None),
    ("abc", 110.0, 90.0, None),
    (math.inf, 110.0, 90.0, None),
    (math.nan, 110.0, 90.0, None),
    (105.0, 90.0, 110.0, None),               # upper below lower: no answer rather than a wrong one
])
def test_band_position(price, upper, lower, expected):
    assert wp._noodle_band_position(price, upper, lower) == expected


# ── _noodle_symbol_match ────────────────────────────────────────────────────

def test_symbol_match():
    rows = {"BTC": {"symbol": "BTC"}, "KBONK": {"symbol": "kBONK"}, "PEPE": {"symbol": "PEPE"},
            "KPEPE": {"symbol": "kPEPE"}}
    assert wp._noodle_symbol_match("btc", rows) == {"symbol": "BTC"}
    assert wp._noodle_symbol_match("BONK", rows) == {"symbol": "kBONK"}      # kilo-prefixed
    assert wp._noodle_symbol_match("pepe", rows) == {"symbol": "PEPE"}       # exact beats kilo-prefixed
    assert wp._noodle_symbol_match("FOX", rows) is None
    assert wp._noodle_symbol_match(None, rows) is None
    assert wp._noodle_symbol_match("", {}) is None


def test_weekly_view_still_matches_kilo_prefixed_rows():
    weekly = {"KBONK": {"symbol": "kBONK", "state": "BEARISH", "flip_ts": None, "computed_at": AT}}
    view, flipped = wp._trades_weekly_view("bonk", weekly)
    assert view == {"symbol": "kBONK", "state": "BEARISH", "flipped_at": None, "as_of": AT} and flipped is None
    view, flipped = wp._trades_weekly_view("FOX", weekly)
    assert view == {"symbol": None, "state": None, "flipped_at": None, "as_of": None} and flipped is None


# ── GET /api/spot/trend-dots ────────────────────────────────────────────────

def test_route_with_no_spot_transactions(client, kicks):
    assert dots(client) == {"timeframes": ["4h", "12h", "1d", "1w"], "symbols": {}}
    assert kicks == [1]                                          # the staleness trigger fires once per read


def test_route_positions_matches_and_missing_rows(client, db, kicks):
    for symbol in ("BTC", "bonk", "FOX", " btc ", "BONK"):
        tx(db, symbol)
    # BTC: all four timeframes (plus a 1h row the dots never read)
    noodle(db, "BTC", "4h", 105.0, 110.0, 90.0, computed_at="2026-10-03T12:00:00+00:00")
    noodle(db, "BTC", "12h", 115.0, 110.0, 90.0, computed_at="2026-10-03T11:00:00+00:00")
    noodle(db, "BTC", "1d", 85.0, 110.0, 90.0, state="BEARISH", computed_at="2026-10-03T12:00:00+00:00")
    noodle(db, "BTC", "1w", 110.0, 110.0, 90.0, computed_at="2026-10-03T12:00:00+00:00")
    noodle(db, "BTC", "1h", 999.0, 110.0, 90.0)
    # kBONK prices 1,000 BONK: the dot uses the row's own price and bands
    noodle(db, "kBONK", "4h", 0.025, 0.03, 0.02)
    noodle(db, "kBONK", "1w", 0.025, None, None, state="WARMUP", computed_at=None)
    d = dots(client)
    assert d["timeframes"] == ["4h", "12h", "1d", "1w"]
    assert sorted(d["symbols"]) == ["BONK", "BTC", "FOX"]         # trimmed, upper-cased, de-duplicated
    assert d["symbols"]["FOX"] is None                           # not in the scanner
    btc = d["symbols"]["BTC"]
    assert btc["scanner_symbol"] == "BTC" and btc["as_of"] == "2026-10-03T11:00:00+00:00"   # oldest wins
    assert {k: v["position"] for k, v in btc["tf"].items()} == {"4h": "touch", "12h": "above", "1d": "below",
                                                                "1w": "touch"}
    assert btc["tf"]["1d"] == {"position": "below", "state": "BEARISH", "price": 85.0, "upper_band": 110.0,
                               "lower_band": 90.0, "computed_at": "2026-10-03T12:00:00+00:00"}
    bonk = d["symbols"]["BONK"]
    assert bonk["scanner_symbol"] == "kBONK" and bonk["as_of"] == AT
    assert bonk["tf"]["4h"]["position"] == "touch" and bonk["tf"]["4h"]["price"] == 0.025
    assert bonk["tf"]["12h"] is None and bonk["tf"]["1d"] is None             # rows absent
    assert bonk["tf"]["1w"]["position"] is None and bonk["tf"]["1w"]["state"] == "WARMUP"   # bands missing
    assert kicks == [1]


def test_route_writes_nothing(client, db):
    tx(db, "BTC")
    noodle(db, "BTC", "4h", 105.0, 110.0, 90.0)
    before = [db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("spot_transactions", "noodle_state")]
    dots(client)
    dots(client)
    after = [db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("spot_transactions", "noodle_state")]
    assert before == after == [1, 1]


def test_route_error_is_a_500_with_a_message(client, monkeypatch):
    def boom():
        raise RuntimeError("no database")
    monkeypatch.setattr(portfolio_db, "get_connection", boom)
    r = client.get('/api/spot/trend-dots')
    assert r.status_code == 500 and r.get_json() == {"error": "no database"}
