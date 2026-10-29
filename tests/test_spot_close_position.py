"""Landing 74: "Close position" on the Spot add-transaction form.

A sell can ask to close the position instead of naming the units: the server
works out the units open on the sell's date (_spot_close_units, on the engine's
own grouping key and order), GET /api/spot/transactions/open-units previews
the same number, and POST /api/spot/transactions with close_position stores a
plain sell with those units. A typed sell is untouched. The page's checkbox,
disabled Units field and preview line are pinned as source text.
"""
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db

EVM = "0xA1FBB38bF486b97108aA87E92008187CA06998f6"
EVM_OTHER = "0xB2FBB38bF486b97108aA87E92008187CA06998f7"


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    conn = portfolio_db.get_connection()
    yield conn
    conn.close()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(wp.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP")))
    monkeypatch.setattr(wp.requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP")))
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def add(db, date, side, units, symbol="AAA", chain="", addr="", total=100.0):
    db.execute(
        "INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, platform, notes, chain, contract_address)"
        " VALUES (?, ?, ?, ?, ?, ?, '', '', ?, ?)", (date, symbol, side, units, total, total, chain, addr))
    db.commit()


def close(db, date="3/1/2026", symbol="AAA", chain="", addr=""):
    return wp._spot_close_units(db, symbol, chain, addr, date)


# -- the helper --

def test_a_plain_position_closes_at_its_open_units(db):
    add(db, "1/5/2026", "buy", 10)
    assert close(db) == (10.0, None)


def test_partial_sells_and_later_buys_are_counted(db):
    add(db, "1/5/2026", "buy", 10)
    add(db, "1/10/2026", "sell", 3)
    assert close(db) == (7.0, None)
    add(db, "1/20/2026", "buy", 5)
    assert close(db) == (12.0, None)


def test_only_rows_dated_on_or_before_the_sell_count(db):
    add(db, "1/1/2026", "buy", 10)
    add(db, "3/1/2026", "buy", 5)
    assert close(db, date="2/1/2026") == (10.0, None)
    assert close(db, date="3/1/2026") == (15.0, None)          # the same day counts: it sorts first
    assert close(db, date="2026-03-01") == (15.0, None)        # the form's ISO date


def test_dates_in_any_stored_format_are_compared_as_dates(db):
    add(db, "2026-01-05", "buy", 4)
    add(db, "1/10/2026", "buy", 6)
    add(db, "2/1/2026", "buy", 100)
    assert close(db, date="2026-01-10") == (10.0, None)


def test_a_sell_ahead_of_its_buys_cannot_make_the_total_negative(db):
    add(db, "1/1/2026", "sell", 4)             # an orphan: nothing was open
    add(db, "2/1/2026", "buy", 10)
    assert close(db, date="2/1/2026") == (10.0, None)


def test_other_positions_are_not_counted(db):
    add(db, "1/1/2026", "buy", 10)
    add(db, "1/1/2026", "buy", 99, symbol="BBB")
    add(db, "1/1/2026", "buy", 7, symbol="CCC", chain="base", addr=EVM.lower())
    add(db, "1/1/2026", "buy", 3, symbol="CCC", chain="base", addr=EVM_OTHER.lower())
    assert close(db) == (10.0, None)
    assert close(db, symbol="CCC", chain="base", addr=EVM) == (7.0, None)
    assert close(db, symbol="CCC", chain="base", addr=EVM_OTHER) == (3.0, None)


def test_the_symbol_is_case_insensitive(db):
    add(db, "1/1/2026", "buy", 2)
    assert close(db, symbol=" aaa ") == (2.0, None)


def test_nothing_open_is_an_error(db):
    assert "No open AAA units as of 3/1/2026" in close(db)[1]
    add(db, "1/1/2026", "buy", 10)
    add(db, "1/2/2026", "sell", 10)
    assert close(db)[0] is None and "No open" in close(db)[1]
    assert close(db, date="1/1/2026") == (10.0, None)          # before the sell it was open


def test_a_residue_under_the_engines_tolerance_is_nothing_open(db):
    add(db, "1/1/2026", "buy", 0.1)
    add(db, "1/1/2026", "buy", 0.2)
    add(db, "1/2/2026", "sell", 0.3)                           # 0.1 + 0.2 - 0.3 leaves about 5.5e-17
    assert close(db)[0] is None
    add(db, "1/1/2026", "buy", 1.0, symbol="DDD")
    add(db, "1/2/2026", "sell", 0.9999999995, symbol="DDD")
    assert close(db, symbol="DDD")[0] is None                   # the engine closes that lot too


def test_the_symbol_only_guard_and_the_address_rules_apply(db):
    add(db, "1/1/2026", "buy", 5, symbol="CCC", chain="base", addr=EVM.lower())
    units, err = close(db, symbol="CCC")
    assert units is None and err == wp.spot_address_guard_message("CCC")
    assert close(db, symbol="CCC", chain="base", addr=EVM) == (5.0, None)
    assert "together" in close(db, symbol="CCC", chain="base")[1]
    assert "Unknown chain" in close(db, symbol="CCC", chain="nope", addr=EVM)[1]
    assert close(db, symbol="")[1] == "Enter the symbol first."
    assert close(db, date="not a date")[1] == "Enter a valid date."
    assert close(db, date="")[1] == "Enter a valid date."


def test_it_reads_and_writes_nothing(db):
    add(db, "1/1/2026", "buy", 3)
    before = [tuple(r) for r in db.execute("SELECT * FROM spot_transactions")]
    close(db)
    assert [tuple(r) for r in db.execute("SELECT * FROM spot_transactions")] == before


# -- the routes --

def body(**kw):
    d = {"trade_date": "2026-03-01", "symbol": "AAA", "side": "sell", "price_usd": 250, "platform": "x", "chain": "", "contract_address": ""}
    d.update(kw)
    return d


def test_the_preview_route_gives_the_units_and_the_date(client, db):
    add(db, "1/5/2026", "buy", 10)
    r = client.get("/api/spot/transactions/open-units?symbol=aaa&date=2026-03-01&chain=&contract_address=")
    assert r.status_code == 200
    assert r.get_json() == {"open_units": 10.0, "as_of": "3/1/2026"}


def test_the_preview_route_reports_problems_as_400(client, db):
    r = client.get("/api/spot/transactions/open-units?symbol=AAA&date=2026-03-01")
    assert r.status_code == 400 and "No open AAA" in r.get_json()["error"]
    assert client.get("/api/spot/transactions/open-units?date=2026-03-01").status_code == 400
    assert client.get("/api/spot/transactions/open-units?symbol=AAA").status_code == 400


def test_a_closing_sell_stores_the_open_units_whatever_was_sent(client, db):
    add(db, "1/5/2026", "buy", 10)
    add(db, "1/9/2026", "sell", 2.5)
    pre = client.get("/api/spot/transactions/open-units?symbol=AAA&date=2026-03-01").get_json()["open_units"]
    r = client.post("/api/spot/transactions", json=body(close_position=True, units=999))
    assert r.status_code == 200, r.get_json()
    out = r.get_json()
    assert out["units"] == pre == 7.5 and out["total_usd"] == 250.0
    row = dict(db.execute("SELECT * FROM spot_transactions WHERE id = ?", (out["id"],)).fetchone())
    assert (row["side"], row["units"], row["price_usd"], row["total_usd"], row["trade_date"]) == ("sell", 7.5, 250.0, 250.0, "3/1/2026")


def test_a_closing_sell_needs_no_units_but_still_needs_the_total(client, db):
    add(db, "1/5/2026", "buy", 10)
    r = client.post("/api/spot/transactions", json=body(close_position=True))
    assert r.status_code == 200, r.get_json()
    d = body(close_position=True); del d["price_usd"]
    r = client.post("/api/spot/transactions", json=d)
    assert r.status_code == 400 and "price_usd" in r.get_json()["error"]


def test_a_closing_sell_with_nothing_open_saves_nothing(client, db):
    r = client.post("/api/spot/transactions", json=body(close_position=True))
    assert r.status_code == 400 and "No open AAA" in r.get_json()["error"]
    assert db.execute("SELECT COUNT(*) FROM spot_transactions").fetchone()[0] == 0


def test_close_position_is_for_a_sell_only(client, db):
    add(db, "1/5/2026", "buy", 10)
    r = client.post("/api/spot/transactions", json=body(side="buy", close_position=True, units=1))
    assert r.status_code == 400 and "only applies to a sell" in r.get_json()["error"]
    assert db.execute("SELECT COUNT(*) FROM spot_transactions").fetchone()[0] == 1


def test_only_true_closes(client, db):
    add(db, "1/5/2026", "buy", 10)
    for v in (False, None, "true", 1, "yes"):
        r = client.post("/api/spot/transactions", json=body(close_position=v, units=2))
        assert r.status_code == 200, (v, r.get_json())
        assert r.get_json()["units"] == 2.0, v


def test_a_typed_sell_is_unchanged(client, db):
    add(db, "1/5/2026", "buy", 10)
    r = client.post("/api/spot/transactions", json=body(units=4))
    assert r.status_code == 200 and r.get_json()["units"] == 4.0
    r = client.post("/api/spot/transactions", json=body())
    assert r.status_code == 400 and "units" in r.get_json()["error"]


def test_the_closing_sell_goes_through_the_address_guard(client, db):
    add(db, "1/5/2026", "buy", 5, symbol="CCC", chain="base", addr=EVM.lower())
    r = client.post("/api/spot/transactions", json=body(symbol="CCC", close_position=True))
    assert r.status_code == 400 and r.get_json()["error"] == wp.spot_address_guard_message("CCC")
    r = client.post("/api/spot/transactions", json=body(symbol="CCC", close_position=True, chain="base", contract_address=EVM))
    assert r.status_code == 200 and r.get_json()["units"] == 5.0


def test_after_a_closing_sell_the_engine_has_nothing_open_and_no_orphan(client, db):
    add(db, "1/5/2026", "buy", 0.1)
    add(db, "1/6/2026", "buy", 0.2)
    add(db, "1/7/2026", "buy", 3.3333333333333335)
    add(db, "1/8/2026", "sell", 1.1)
    r = client.post("/api/spot/transactions", json=body(close_position=True))
    assert r.status_code == 200, r.get_json()
    open_positions, closed_positions = wp._calculate_spot_fifo(db)
    assert not [k for k in open_positions if "AAA" in str(k)]
    assert [k for k in closed_positions if "AAA" in str(k)]
    assert wp._detect_spot_orphan_sells(db)["orphans"] == []


def test_the_put_route_ignores_close_position(client, db):
    add(db, "1/5/2026", "buy", 10)
    new_id = client.post("/api/spot/transactions", json=body(units=1)).get_json()["id"]
    r = client.put("/api/spot/transactions/%d" % new_id, json=body(units=2, close_position=True))
    assert r.status_code == 200, r.get_json()
    assert db.execute("SELECT units FROM spot_transactions WHERE id = ?", (new_id,)).fetchone()[0] == 2.0
