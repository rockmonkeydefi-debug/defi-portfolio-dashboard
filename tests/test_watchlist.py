"""Landing 78: the Watch List - the append-only watch_items table, the
watch_trend cache, and the routes GET / POST /api/watchlist,
PUT /api/watchlist/<key>, GET /api/watchlist/prices and
POST /api/watchlist/<key>/check. An item's notes are the page_notes note under
its key notes-w<n>, which the notes routes accept (images included, through
the notes- prefix) once the item exists. Nothing is deleted.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). No network: DexScreener and the on-chain check are replaced.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import json
import sqlite3
import threading
import time

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db
import onchain_scan

WATCH = "/api/watchlist"
EVM_A = "0x" + "a" * 40
EVM_B = "0x" + "b" * 40
SOL_1 = "So11111111111111111111111111111111111111112"
SOL_2 = "so11111111111111111111111111111111111111112"      # differs from SOL_1 only by case: another token


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    conn = portfolio_db.get_connection()
    yield conn
    conn.close()


def _client(monkeypatch, block_threads):
    monkeypatch.setattr(wp.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP")))
    monkeypatch.setattr(wp.requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP")))
    if block_threads:
        monkeypatch.setattr(threading.Thread, "start", lambda self, *a, **k: (_ for _ in ()).throw(AssertionError("thread")))
    monkeypatch.setattr(wp, "_maybe_kick_noodle_auto_refresh", lambda: None)
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


@pytest.fixture
def client(db, monkeypatch):
    return _client(monkeypatch, True)


@pytest.fixture
def tclient(db, monkeypatch):
    """A client that may start threads (the prices route uses a pool)."""
    return _client(monkeypatch, False)


def rows(db):
    return [dict(r) for r in db.execute("SELECT * FROM watch_items ORDER BY id")]


def view(client):
    r = client.get(WATCH)
    assert r.status_code == 200
    return r.get_json()


def keys(client):
    return [i["key"] for i in view(client)["items"]]


def add(client, name="WIF", chain="solana", contract=SOL_1):
    return client.post(WATCH, json={"name": name, "chain": chain, "contract": contract})


def put(client, key, **body):
    return client.put(f"{WATCH}/{key}", json=body)


# -- schema ---------------------------------------------------------------------


def test_the_tables_exist_and_init_is_repeatable(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info(watch_items)")]
    assert cols == ["id", "item_key", "name", "chain", "contract", "summary", "active", "position", "created_at"]
    assert [r[1] for r in db.execute("PRAGMA table_info(watch_trend)")] == ["item_key", "computed_at", "price", "body_json"]
    portfolio_db.init_db()
    assert [r[1] for r in db.execute("PRAGMA table_info(watch_items)")] == cols


@pytest.mark.parametrize("key", ["notes-t1", "notes-w", "notes-w0", "notes-w01", "notes-w1x", "notes-w1234567", "watch-1", ""])
def test_the_table_refuses_a_key_that_is_not_notes_w_and_digits(db, key):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO watch_items (item_key, name, chain, contract, summary, active, position, created_at) "
                   "VALUES (?, 'X', 'solana', ?, '', 1, NULL, 'now')", (key, SOL_1))


def test_the_table_checks_name_contract_summary_active_and_position(db):
    ok = ("notes-w1", "X", "solana", SOL_1, "", 1, None, "now")
    sql = ("INSERT INTO watch_items (item_key, name, chain, contract, summary, active, position, created_at) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
    bad = [ok[:1] + ("",) + ok[2:], ok[:1] + ("x" * 41,) + ok[2:], ok[:3] + ("0x12",) + ok[4:],
           ok[:4] + ("s" * 161,) + ok[5:], ok[:5] + (2,) + ok[6:], ok[:6] + (-1,) + ok[7:], ok[:6] + (1.5,) + ok[7:]]
    for params in bad:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(sql, params)
    db.execute(sql, ok)                       # the good row goes in
    db.execute(sql, ok[:6] + (0,) + ok[7:])   # and a position of 0 does too


# -- list and add ------------------------------------------------------------------


def test_an_empty_list_carries_the_limits_and_the_chains(client):
    v = view(client)
    assert v["items"] == []
    assert v["limits"] == {"name_max": 40, "summary_max": 160, "items_max": 200}
    assert v["timeframes"] == ["4h", "12h", "1d", "1w"]
    assert [c["key"] for c in v["chains"]] == list(wp.SPOT_CHAINS)
    assert {"key": "solana", "label": "Solana"} in v["chains"]


def test_add_makes_an_active_item_with_the_next_key(client, db):
    r = add(client, name="  WIF   dog ", chain="solana", contract=SOL_1)
    assert r.status_code == 201
    j = r.get_json()
    assert j["key"] == "notes-w1" and j["reactivated"] is False
    item = j["items"][0]
    assert (item["name"], item["chain"], item["chain_label"], item["contract"]) == ("WIF dog", "solana", "Solana", SOL_1)
    assert (item["summary"], item["active"], item["scanner"], item["check"]) == ("", True, None, None)
    r2 = add(client, name="PEPE", chain="ethereum", contract=EVM_A.upper().replace("0X", "0x"))
    assert r2.status_code == 201 and r2.get_json()["key"] == "notes-w2"
    assert rows(db)[1]["contract"] == EVM_A                     # an EVM address is stored lowercase
    assert rows(db)[1]["position"] is None


def test_add_keeps_a_solana_address_exactly(client):
    assert add(client, "A", "solana", SOL_1).status_code == 201
    assert add(client, "B", "solana", SOL_2).status_code == 201          # a different token, not a duplicate
    assert [i["contract"] for i in view(client)["items"]] == [SOL_1, SOL_2]


@pytest.mark.parametrize("body", [
    {}, {"name": "X"}, {"name": "X", "chain": "solana"}, {"name": "X", "chain": "solana", "contract": SOL_1, "extra": 1},
    {"name": 5, "chain": "solana", "contract": SOL_1}, {"name": "X", "chain": None, "contract": SOL_1},
    {"name": "X", "chain": "solana", "contract": 7}, {"name": "   ", "chain": "solana", "contract": SOL_1},
    {"name": "x" * 41, "chain": "solana", "contract": SOL_1}, {"name": "A" + chr(0x202E) + "B", "chain": "solana", "contract": SOL_1},
    {"name": "X", "chain": "", "contract": SOL_1}, {"name": "X", "chain": "solana", "contract": "  "},
    {"name": "X", "chain": "dogechain", "contract": SOL_1}, {"name": "X", "chain": "ethereum", "contract": "0x12"},
    {"name": "X", "chain": "solana", "contract": "0" + SOL_1[1:]},
])
def test_add_refuses_a_bad_body(client, db, body):
    assert client.post(WATCH, json=body).status_code == 400
    assert rows(db) == []


def test_add_refuses_a_non_json_body(client):
    assert client.post(WATCH, data="nope", content_type="text/plain").status_code == 400


def test_the_same_chain_and_contract_is_not_added_twice(client, db):
    assert add(client, "PEPE", "ethereum", EVM_A).status_code == 201
    r = add(client, "pepe again", "ethereum", EVM_A.upper().replace("0X", "0x"))
    assert r.status_code == 409
    assert r.get_json()["key"] == "notes-w1" and "already on your watch list" in r.get_json()["error"]
    assert len(rows(db)) == 1
    assert add(client, "PEPE", "base", EVM_A).status_code == 201        # the same address on another chain is another item


def test_adding_an_inactive_item_again_brings_it_back_with_its_summary(client, db):
    add(client, "PEPE", "ethereum", EVM_A)
    put(client, "notes-w1", summary="wait for 4h reclaim")
    put(client, "notes-w1", active=False)
    r = add(client, "other name", "ethereum", EVM_A)
    assert r.status_code == 200
    j = r.get_json()
    assert j["key"] == "notes-w1" and j["reactivated"] is True
    assert [(i["key"], i["name"], i["summary"], i["active"]) for i in j["items"]] == [("notes-w1", "PEPE", "wait for 4h reclaim", True)]
    assert len({r_["item_key"] for r_ in rows(db)}) == 1


def test_the_list_is_capped(client, monkeypatch):
    monkeypatch.setattr(wp, "WATCH_ITEMS_MAX", 2)
    assert add(client, "A", "ethereum", EVM_A).status_code == 201
    assert add(client, "B", "ethereum", EVM_B).status_code == 201
    r = add(client, "C", "solana", SOL_1)
    assert r.status_code == 409 and "at most 2" in r.get_json()["error"]
    assert len(keys(client)) == 2


def test_a_key_is_never_handed_out_again_after_a_row_is_removed(client, db):
    add(client, "A", "ethereum", EVM_A)
    add(client, "B", "ethereum", EVM_B)
    db.execute("DELETE FROM watch_items WHERE item_key = 'notes-w2'")       # what Landing 79's delete will do
    db.commit()
    assert add(client, "C", "solana", SOL_1).get_json()["key"] == "notes-w3"


# -- update --------------------------------------------------------------------------


def test_update_renames_sets_the_summary_and_toggles_active_one_row_each(client, db):
    add(client, "WIF")
    before = len(rows(db))
    j = put(client, "notes-w1", name="  dogwifhat ").get_json()
    assert j["changed"] is True and j["items"][0]["name"] == "dogwifhat"
    j = put(client, "notes-w1", summary="  buy the retest\nof the weekly band  ").get_json()
    assert j["items"][0]["summary"] == "buy the retest of the weekly band"
    j = put(client, "notes-w1", active=False).get_json()
    assert j["items"][0]["active"] is False
    assert len(rows(db)) == before + 3
    last = rows(db)[-1]
    assert (last["name"], last["summary"], last["active"]) == ("dogwifhat", "buy the retest of the weekly band", 0)
    j = put(client, "notes-w1", summary="").get_json()                 # an empty summary is allowed
    assert j["items"][0]["summary"] == ""


def test_a_change_that_changes_nothing_writes_nothing(client, db):
    add(client, "WIF")
    n = len(rows(db))
    j = put(client, "notes-w1", name="WIF", active=True, summary="").get_json()
    assert j["changed"] is False and len(rows(db)) == n


def test_update_keeps_the_stored_position_and_the_address(client, db):
    add(client, "A", "ethereum", EVM_A)
    db.execute("INSERT INTO watch_items (item_key, name, chain, contract, summary, active, position, created_at) "
               "SELECT item_key, name, chain, contract, summary, active, 4, created_at FROM watch_items")
    db.commit()
    put(client, "notes-w1", summary="x")
    last = rows(db)[-1]
    assert (last["position"], last["chain"], last["contract"]) == (4, "ethereum", EVM_A)


@pytest.mark.parametrize("key", ["notes-w9", "notes-w0", "notes-w01", "notes-t1", "notes-watchlist", "x"])
def test_update_of_an_unknown_key_is_a_404(client, key):
    assert put(client, key, summary="x").status_code == 404


@pytest.mark.parametrize("body", [{}, {"chain": "base"}, {"active": "yes"}, {"active": 1}, {"summary": "s" * 161},
                                   {"summary": 7}, {"name": ""}, {"name": "x" * 41}, {"summary": "a\u0007b"}])
def test_update_refuses_a_bad_body(client, db, body):
    add(client, "WIF")
    n = len(rows(db))
    assert put(client, "notes-w1", **body).status_code == 400
    assert len(rows(db)) == n


def test_the_order_is_added_order_then_inactive_most_recently_changed_first(client):
    for n, (name, chain, addr) in enumerate([("A", "ethereum", EVM_A), ("B", "ethereum", EVM_B),
                                              ("C", "solana", SOL_1), ("D", "solana", SOL_2)], 1):
        add(client, name, chain, addr)
    assert keys(client) == ["notes-w1", "notes-w2", "notes-w3", "notes-w4"]
    put(client, "notes-w2", active=False)
    time.sleep(0.01)
    put(client, "notes-w1", active=False)
    v = view(client)["items"]
    assert [(i["key"], i["active"]) for i in v] == [("notes-w3", True), ("notes-w4", True), ("notes-w1", False), ("notes-w2", False)]


def test_a_stored_position_orders_the_active_items(client, db):
    add(client, "A", "ethereum", EVM_A)
    add(client, "B", "ethereum", EVM_B)
    for key, pos in (("notes-w1", 5), ("notes-w2", 2)):
        db.execute("INSERT INTO watch_items (item_key, name, chain, contract, summary, active, position, created_at) "
                   "SELECT item_key, name, chain, contract, summary, active, ?, created_at FROM watch_items "
                   "WHERE item_key = ? ORDER BY id DESC LIMIT 1", (pos, key))
    db.commit()
    assert keys(client) == ["notes-w2", "notes-w1"]


# -- scanner and saved check ---------------------------------------------------------


def _noodle(db, symbol, tf, price, upper, lower, **extra):
    cols = {"symbol": symbol, "timeframe": tf, "state": "BULLISH", "price": price, "upper_band": upper,
            "lower_band": lower, "computed_at": f"2026-10-30T0{len(tf)}:00:00+00:00"}
    cols.update(extra)
    db.execute(f"INSERT INTO noodle_state ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", list(cols.values()))
    db.commit()


def test_an_item_named_like_a_scanner_market_gets_its_dots(client, db):
    add(client, "wif")
    add(client, "BONK", "ethereum", EVM_A)
    add(client, "NOPE", "ethereum", EVM_B)
    _noodle(db, "WIF", "4h", 2.0, 1.5, 1.0)                  # above
    _noodle(db, "WIF", "12h", 1.2, 1.5, 1.0)                 # touch
    _noodle(db, "WIF", "1d", 0.5, 1.5, 1.0)                  # below
    _noodle(db, "WIF", "1h", 1.0, 1.5, 0.5, respect_dir="BULLISH", respect_tags=3, respect_losses=0,
            respect_since=1000, respect_last_ts=2000, respect_unbounded=1, poi_at_band=0)
    _noodle(db, "kBONK", "4h", 3.0, 2.0, 1.0)
    by = {i["name"]: i for i in view(client)["items"]}
    wif = by["wif"]["scanner"]
    assert wif["scanner_symbol"] == "WIF"
    assert {tf: wif["timeframes"][tf]["position"] for tf in ("4h", "12h", "1d")} == {"4h": "above", "12h": "touch", "1d": "below"}
    assert "1w" not in wif["timeframes"]
    one_h = wif["timeframes"]["1h"]
    assert (one_h["respect_dir"], one_h["respect_tags"], one_h["respect_losses"]) == ("BULLISH", 3, 0)
    assert one_h["respect_unbounded"] is True and one_h["poi_at_band"] is False          # booleans, not 0 / 1
    assert wif["as_of"] == min(wif["timeframes"][tf]["computed_at"] for tf in ("4h", "12h", "1d"))
    assert by["BONK"]["scanner"]["scanner_symbol"] == "kBONK"                              # the kilo-prefixed market
    assert by["NOPE"]["scanner"] is None


def _body(price=1.0, tfs=("1h", "4h", "12h", "1d", "1w")):
    return {"symbol": "WIF", "price": price, "pool": {"name": "WIF / SOL", "dex": "raydium", "liquidity_usd": 50000.0, "age_days": 90.0},
            "notes": ["No contract-safety check."],
            "timeframes": {tf: {"state": "BULLISH", "price": price, "upper_band": 1.5, "lower_band": 0.5,
                                "computed_at": "2026-10-30T10:00:00+00:00", "respect_dir": "BULLISH", "respect_tags": 2,
                                "respect_losses": 0, "respect_unbounded": 0, "bars": 120, "warming": False} for tf in tfs}}


def test_a_saved_check_is_returned_with_dots_and_a_bad_body_reads_as_none(client, db):
    add(client, "NEW", "ethereum", EVM_A)
    add(client, "BAD", "ethereum", EVM_B)
    db.execute("INSERT INTO watch_trend (item_key, computed_at, price, body_json) VALUES ('notes-w1', 't1', 1.0, ?)", (json.dumps(_body()),))
    db.execute("INSERT INTO watch_trend (item_key, computed_at, price, body_json) VALUES ('notes-w2', 't2', 1.0, 'not json')")
    db.commit()
    by = {i["name"]: i for i in view(client)["items"]}
    chk = by["NEW"]["check"]
    assert chk["computed_at"] == "t1" and chk["price"] == 1.0 and chk["symbol"] == "WIF"
    assert chk["pool"]["name"] == "WIF / SOL" and chk["notes"] == ["No contract-safety check."]
    assert sorted(chk["timeframes"]) == ["12h", "1d", "1h", "1w", "4h"]
    assert chk["timeframes"]["4h"]["position"] == "touch"
    assert chk["timeframes"]["4h"]["respect_unbounded"] is False and chk["timeframes"]["4h"]["bars"] == 120
    assert by["BAD"]["check"] is None


def test_the_list_fires_the_scanner_kick_and_survives_it_failing(client, monkeypatch):
    calls = []
    monkeypatch.setattr(wp, "_maybe_kick_noodle_auto_refresh", lambda: calls.append(1))
    view(client)
    assert calls == [1]
    monkeypatch.setattr(wp, "_maybe_kick_noodle_auto_refresh", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert client.get(WATCH).status_code == 200


# -- Check trend ---------------------------------------------------------------------


def _fake_check(chain, token, pool_address=None, now_ts=None):
    tfs = {tf: {"state": "BULLISH", "price": 2.0, "upper_band": 3.0, "lower_band": 1.0, "computed_at": "2026-10-30T10:00:00+00:00",
                "respect_dir": "BULLISH", "respect_tags": 4, "respect_losses": 0, "respect_unbounded": None,
                "bars": 90, "warming": False, "junk": "not stored"} for tf in ("1w", "1d", "12h", "4h", "1h")}
    return {"symbol": "WIF", "chain": chain, "token_address": token, "price": 2.0,
            "pool": {"address": "p", "name": "WIF / SOL", "dex": "raydium", "liquidity_usd": 9000.0, "age_days": 3.0, "side": "base"},
            "timeframes": tfs, "notes": ["n1", "n2", "n3", "n4", "n5"], "computed_at": "2026-10-30T10:00:05+00:00"}


def test_check_trend_saves_the_result_and_replaces_it_next_time(client, db, monkeypatch):
    add(client, "WIF")
    calls = []
    monkeypatch.setattr(wp, "_onchain_check_compute", lambda chain, token, *a, **k: calls.append((chain, token)) or _fake_check(chain, token))
    r = client.post(f"{WATCH}/notes-w1/check")
    assert r.status_code == 200
    chk = r.get_json()["check"]
    assert calls == [("solana", SOL_1)]
    assert chk["computed_at"] == "2026-10-30T10:00:05+00:00" and chk["price"] == 2.0
    assert chk["timeframes"]["1d"]["position"] == "touch" and chk["timeframes"]["1d"]["respect_tags"] == 4
    assert "junk" not in chk["timeframes"]["1d"] and len(chk["notes"]) == 4
    assert db.execute("SELECT COUNT(*) FROM watch_trend").fetchone()[0] == 1
    monkeypatch.setattr(wp, "_onchain_check_compute", lambda *a, **k: {**_fake_check("solana", SOL_1), "price": 5.0,
                                                                         "computed_at": "2026-10-30T11:00:00+00:00"})
    assert client.post(f"{WATCH}/notes-w1/check").get_json()["check"]["price"] == 5.0
    assert db.execute("SELECT COUNT(*) FROM watch_trend").fetchone()[0] == 1
    assert view(client)["items"][0]["check"]["computed_at"] == "2026-10-30T11:00:00+00:00"


def test_a_check_with_non_finite_numbers_is_saved_as_valid_json(client, db, monkeypatch):
    add(client, "WIF")
    res = _fake_check("solana", SOL_1)
    res["timeframes"]["4h"]["upper_band"] = float("inf")
    res["timeframes"]["4h"]["respect_tags"] = float("nan")
    res["pool"]["liquidity_usd"] = float("nan")
    monkeypatch.setattr(wp, "_onchain_check_compute", lambda *a, **k: res)
    r = client.post(f"{WATCH}/notes-w1/check")
    assert r.status_code == 200
    stored = json.loads(db.execute("SELECT body_json FROM watch_trend").fetchone()[0])      # strict JSON: no NaN / Infinity
    assert stored["timeframes"]["4h"]["upper_band"] is None and stored["pool"]["liquidity_usd"] is None
    assert r.get_json()["check"]["timeframes"]["4h"]["position"] is None
    assert r.get_json()["check"]["timeframes"]["1d"]["respect_tags"] == 4


def test_a_check_that_cannot_be_saved_says_so_without_database_detail(client, db, monkeypatch):
    add(client, "WIF")
    res = _fake_check("solana", SOL_1)
    res["notes"] = ["x" * 50000]                                  # a stored body over the table's limit
    monkeypatch.setattr(wp, "_onchain_check_compute", lambda *a, **k: res)
    r = client.post(f"{WATCH}/notes-w1/check")
    assert r.status_code == 500
    assert r.get_json()["error"] == "The trend check finished but couldn't be saved."
    assert db.execute("SELECT COUNT(*) FROM watch_trend").fetchone()[0] == 0


def test_the_prices_route_answers_before_the_page_gives_up():
    assert wp.WATCH_PRICE_TIMEOUT_S == 15            # static/watchlist.js WL_REQUEST_TIMEOUT_MS is 20 s


def test_check_trend_works_for_an_inactive_item(client, monkeypatch):
    add(client, "WIF")
    put(client, "notes-w1", active=False)
    monkeypatch.setattr(wp, "_onchain_check_compute", lambda *a, **k: _fake_check("solana", SOL_1))
    assert client.post(f"{WATCH}/notes-w1/check").status_code == 200


def test_check_trend_errors(client, db, monkeypatch):
    add(client, "WIF")
    assert client.post(f"{WATCH}/notes-w9/check").status_code == 404
    assert client.post(f"{WATCH}/bogus/check").status_code == 404
    monkeypatch.setattr(wp, "_onchain_check_compute",
                        lambda *a, **k: (_ for _ in ()).throw(onchain_scan.OnchainError("No pool found.", 404)))
    r = client.post(f"{WATCH}/notes-w1/check")
    assert r.status_code == 404 and r.get_json()["error"] == "No pool found."
    monkeypatch.setattr(wp, "_onchain_check_compute", lambda *a, **k: (_ for _ in ()).throw(KeyError("secret detail")))
    r = client.post(f"{WATCH}/notes-w1/check")
    assert r.status_code == 500 and "secret detail" not in r.get_json()["error"] and "KeyError" in r.get_json()["error"]
    assert db.execute("SELECT COUNT(*) FROM watch_trend").fetchone()[0] == 0           # a failed check saves nothing
    assert wp._ONCHAIN_CHECK_LOCK.acquire(blocking=False)                                # and releases the lock
    wp._ONCHAIN_CHECK_LOCK.release()


def test_check_trend_is_refused_while_another_check_runs(client, monkeypatch):
    add(client, "WIF")
    monkeypatch.setattr(wp, "_onchain_check_compute", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    assert wp._ONCHAIN_CHECK_LOCK.acquire(blocking=False)
    try:
        r = client.post(f"{WATCH}/notes-w1/check")
        assert r.status_code == 409 and "running" in r.get_json()["error"]
    finally:
        wp._ONCHAIN_CHECK_LOCK.release()


# -- prices --------------------------------------------------------------------------


def test_prices_cover_only_active_items_through_the_spot_dexscreener_path(tclient, monkeypatch):
    add(tclient, "A", "ethereum", EVM_A)
    add(tclient, "B", "base", EVM_B)
    add(tclient, "C", "solana", SOL_1)
    put(tclient, "notes-w3", active=False)
    seen = []

    def fake(contract, chain, _now=None):
        seen.append((contract, chain))
        return {EVM_A: 1.25, EVM_B: float("nan")}.get(contract)

    monkeypatch.setattr(wp, "fetch_dexscreener_price", fake)
    j = tclient.get(f"{WATCH}/prices").get_json()
    assert j["prices"] == {"notes-w1": 1.25, "notes-w2": None}
    assert sorted(seen) == sorted([(EVM_A, "ethereum"), (EVM_B, "base")])
    assert j["as_of"]


def test_a_failing_or_slow_lookup_reads_null_and_does_not_hang_the_route(tclient, monkeypatch):
    add(tclient, "A", "ethereum", EVM_A)
    add(tclient, "B", "ethereum", EVM_B)

    def fake(contract, chain, _now=None):
        if contract == EVM_A:
            raise RuntimeError("down")
        time.sleep(1.5)
        return 9.0

    monkeypatch.setattr(wp, "fetch_dexscreener_price", fake)
    monkeypatch.setattr(wp, "WATCH_PRICE_TIMEOUT_S", 0.3)
    t0 = time.time()
    j = tclient.get(f"{WATCH}/prices").get_json()
    assert time.time() - t0 < 1.2
    assert j["prices"] == {"notes-w1": None, "notes-w2": None}


def test_prices_of_an_empty_list(tclient):
    assert tclient.get(f"{WATCH}/prices").get_json()["prices"] == {}


# -- the item's notes ---------------------------------------------------------------


def _delta(*ops):
    return {"ops": list(ops)}


def _store_image(db):
    db.execute("INSERT INTO note_images (sha256, mime, width, height, bytes, data, created_at) VALUES (?, 'image/png', 4, 4, 8, ?, 'now')",
               ("c" * 64, b"12345678"))
    db.commit()
    return db.execute("SELECT id FROM note_images").fetchone()[0]


def test_an_items_notes_exist_once_the_item_does(client):
    assert client.get("/api/page-notes/notes-w1").status_code == 404
    add(client, "WIF")
    r = client.get("/api/page-notes/notes-w1")
    assert r.status_code == 200 and r.get_json()["id"] is None and r.get_json()["empty"] is True
    for bad in ("notes-w2", "notes-w01", "notes-w0", "notes-w1234567", "notes-wx"):
        assert client.get(f"/api/page-notes/{bad}").status_code == 404


def test_an_items_notes_save_with_formatting_and_images_even_when_inactive(client, db):
    add(client, "WIF")
    r = client.put("/api/page-notes/notes-w1", json={"delta": _delta({"insert": "Plan"}, {"insert": "\n", "attributes": {"header": 2}},
                                                                     {"insert": "buy the dip\n"}), "base_id": None})
    assert r.status_code == 200 and r.get_json()["changed"] is True
    image_id = _store_image(db)
    put(client, "notes-w1", active=False)
    r = client.put("/api/page-notes/notes-w1", json={
        "delta": _delta({"insert": "Plan"}, {"insert": "\n", "attributes": {"header": 2}},
                        {"insert": {"image": f"/api/note-images/{image_id}"}}, {"insert": "\n"}),
        "base_id": r.get_json()["id"]})
    assert r.status_code == 200 and r.get_json()["changed"] is True
    assert client.get("/api/page-notes/notes-w1").get_json()["saved_at"]
    assert db.execute("SELECT COUNT(*) FROM page_notes WHERE page = 'notes-w1'").fetchone()[0] == 2


def test_an_items_note_refuses_an_image_that_is_not_stored(client):
    add(client, "WIF")
    r = client.put("/api/page-notes/notes-w1", json={"delta": _delta({"insert": {"image": "/api/note-images/77"}}, {"insert": "\n"}),
                                                     "base_id": None})
    assert r.status_code == 400


def test_the_notes_pages_that_already_existed_still_behave(client):
    assert client.get("/api/page-notes/spot").status_code == 200
    assert client.get("/api/page-notes/notes-watchlist").status_code == 200
    assert client.get("/api/page-notes/notes-t1").status_code == 404           # no Notes tab row: unknown, as before
    assert client.get("/api/page-notes/nonsense").status_code == 404


def test_the_watch_list_routes_write_no_other_table(client, db):
    def snapshot():
        out = {}
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"):
            out[name] = db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        return out

    before = snapshot()
    add(client, "WIF")
    put(client, "notes-w1", summary="x")
    put(client, "notes-w1", active=False)
    after = snapshot()
    changed = {t for t in after if after[t] != before.get(t)}
    assert changed == {"watch_items"}
