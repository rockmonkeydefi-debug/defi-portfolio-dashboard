"""Spot position books (HANDOFF_trading_performance.md Commit 1, ruling 1):
the spot_position_books table, GET/PUT /api/spot/position-books, the
additive 'book' field on /api/spot/pnl and /api/spot/history rows, and
_spot_all_position_keys agreeing with _calculate_spot_fifo's keys.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). price_usd is seeded as the TOTAL transaction amount, as the
Spot page stores it. _get_spot_price_stale_serve is stubbed, so no test makes
a network call. Fake contract addresses only.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
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

ADDR1 = '0x' + '1' * 40
ADDR2 = '0x' + '2' * 40
ADDR3 = '0x' + '3' * 40
ADDR9 = '0x' + '9' * 40
KEY1 = 'base ' + ADDR1


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
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    monkeypatch.setattr(wp, "_get_spot_price_stale_serve",
                        lambda pos, cfg, _now=None: (2.0, '2026-09-30T00:00:00+00:00'))
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def tx(conn, date, symbol, side, units, total, chain='base', contract=ADDR1):
    """One spot_transactions row; price_usd = total_usd = the TOTAL amount."""
    conn.execute(
        "INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, chain, contract_address) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (date, symbol, side, units, total, total, chain, contract))
    conn.commit()


def book_rows(conn):
    return [dict(r) for r in conn.execute("SELECT position_key, book FROM spot_position_books ORDER BY id")]


def put(client, body):
    return client.put('/api/spot/position-books', json=body)


def without_book(rows):
    return {r['position_key']: {k: v for k, v in r.items() if k != 'book'} for r in rows}


# ── a, b ──────────────────────────────────────────────────────────────────

def test_a_table_columns_and_init_db_idempotent(db):
    cols = {r['name'] for r in db.execute("PRAGMA table_info(spot_position_books)")}
    assert cols == {'id', 'position_key', 'book', 'updated_at'}
    portfolio_db.init_db()          # a second call raises nothing


def test_b_spot_books_constant():
    assert wp.SPOT_BOOKS == ('trading', 'long_term', 'bot_capital')


# ── c, d, e: tag, retag, back to trading ─────────────────────────────────

def test_c_put_then_get(db, client):
    tx(db, '9/1/2026', 'AAA', 'buy', 10, 20)
    r = put(client, {'position_key': KEY1, 'book': 'long_term'})
    assert r.status_code == 200
    body = r.get_json()
    assert (body['position_key'], body['book'], body['attached']) == (KEY1, 'long_term', True)
    assert body['updated_at']
    rows = client.get('/api/spot/position-books').get_json()
    assert len(rows) == 1
    assert (rows[0]['position_key'], rows[0]['book'], rows[0]['attached']) == (KEY1, 'long_term', True)


def test_d_retag_keeps_one_row(db, client):
    tx(db, '9/1/2026', 'AAA', 'buy', 10, 20)
    assert put(client, {'position_key': KEY1, 'book': 'long_term'}).status_code == 200
    r = put(client, {'position_key': KEY1, 'book': 'bot_capital'})
    assert r.status_code == 200 and r.get_json()['book'] == 'bot_capital'
    assert book_rows(db) == [{'position_key': KEY1, 'book': 'bot_capital'}]


def test_e_trading_keeps_the_row(db, client):
    tx(db, '9/1/2026', 'AAA', 'buy', 10, 20)
    assert put(client, {'position_key': KEY1, 'book': 'long_term'}).status_code == 200
    assert put(client, {'position_key': KEY1, 'book': 'trading'}).status_code == 200
    assert book_rows(db) == [{'position_key': KEY1, 'book': 'trading'}]


# ── f: rejects ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body,error", [
    ({'position_key': KEY1, 'book': 'longterm'}, 'book must be one of trading, long_term, bot_capital'),
    ({'book': 'long_term'}, 'position_key is required'),
    ({'position_key': '   ', 'book': 'long_term'}, 'position_key is required'),
    ({'position_key': 123, 'book': 'long_term'}, 'position_key is required'),
    ({'position_key': 'base ' + ADDR9, 'book': 'long_term'}, 'unknown position_key'),
])
def test_f_rejects_write_nothing(db, client, body, error):
    tx(db, '9/1/2026', 'AAA', 'buy', 10, 20)
    assert put(client, {'position_key': KEY1, 'book': 'bot_capital'}).status_code == 200
    before = db.execute("SELECT COUNT(*) FROM spot_position_books").fetchone()[0]
    r = put(client, body)
    assert r.status_code == 400
    assert r.get_json() == {'error': error}
    assert db.execute("SELECT COUNT(*) FROM spot_position_books").fetchone()[0] == before
    assert book_rows(db) == [{'position_key': KEY1, 'book': 'bot_capital'}]


def test_f_key_is_used_exactly_as_given(db, client):
    tx(db, '9/1/2026', 'AAA', 'buy', 10, 20)
    for k in (' ' + KEY1, KEY1 + ' ', KEY1.upper()):
        assert put(client, {'position_key': k, 'book': 'long_term'}).status_code == 400
    assert book_rows(db) == []


# ── g: symbol-only positions ──────────────────────────────────────────────

def test_g_symbol_only_key(db, client):
    tx(db, '9/1/2026', 'TAO', 'buy', 2, 10, chain='', contract='')
    r = put(client, {'position_key': 'TAO', 'book': 'bot_capital'})
    assert r.status_code == 200 and r.get_json()['book'] == 'bot_capital'
    assert book_rows(db) == [{'position_key': 'TAO', 'book': 'bot_capital'}]


# ── h: /api/spot/pnl ──────────────────────────────────────────────────────

def test_h_pnl_book_field_is_additive(db, client):
    tx(db, '9/1/2026', 'AAA', 'buy', 10, 20)
    tx(db, '9/2/2026', 'BBB', 'buy', 5, 5, contract=ADDR2)
    tx(db, '9/3/2026', 'TAO', 'buy', 2, 10, chain='', contract='')
    before = client.get('/api/spot/pnl').get_json()
    assert len(before) == 3
    assert all(r['book'] == 'trading' for r in before)
    assert put(client, {'position_key': KEY1, 'book': 'long_term'}).status_code == 200
    assert put(client, {'position_key': 'TAO', 'book': 'bot_capital'}).status_code == 200
    after = client.get('/api/spot/pnl').get_json()
    books = {r['position_key']: r['book'] for r in after}
    assert books == {KEY1: 'long_term', 'base ' + ADDR2: 'trading', 'TAO': 'bot_capital'}
    assert without_book(after) == without_book(before)


# ── i: /api/spot/history ─────────────────────────────────────────────────

def test_i_history_book_field_is_additive(db, client):
    tx(db, '9/1/2026', 'AAA', 'buy', 10, 20)                     # partly sold
    tx(db, '9/2/2026', 'AAA', 'sell', 4, 12)
    tx(db, '9/1/2026', 'CCC', 'buy', 3, 6, contract=ADDR3)       # fully sold
    tx(db, '9/3/2026', 'CCC', 'sell', 3, 9, contract=ADDR3)
    before = client.get('/api/spot/history').get_json()
    assert {r['position_key'] for r in before} == {KEY1, 'base ' + ADDR3}
    assert all(r['book'] == 'trading' for r in before)
    assert put(client, {'position_key': 'base ' + ADDR3, 'book': 'long_term'}).status_code == 200
    after = client.get('/api/spot/history').get_json()
    assert {r['position_key']: r['book'] for r in after} == {KEY1: 'trading', 'base ' + ADDR3: 'long_term'}
    assert without_book(after) == without_book(before)
    assert [r['position_key'] for r in after] == [r['position_key'] for r in before]   # sort kept


# ── j: detachment ────────────────────────────────────────────────────────

def test_j_detached_tag_is_kept_and_reported(db, client):
    tx(db, '9/1/2026', 'TAO', 'buy', 2, 10, chain='', contract='')
    assert put(client, {'position_key': 'TAO', 'book': 'bot_capital'}).status_code == 200
    db.execute("UPDATE spot_transactions SET chain='base', contract_address=? WHERE symbol='TAO'", (ADDR2,))
    db.commit()
    rows = client.get('/api/spot/position-books').get_json()
    assert [(r['position_key'], r['book'], r['attached']) for r in rows] == [('TAO', 'bot_capital', False)]
    assert book_rows(db) == [{'position_key': 'TAO', 'book': 'bot_capital'}]
    pnl = {r['position_key']: r for r in client.get('/api/spot/pnl').get_json()}
    assert pnl['base ' + ADDR2]['book'] == 'trading'


# ── k: keys agree with FIFO ──────────────────────────────────────────────

def test_k_all_position_keys_match_fifo(db):
    tx(db, '9/1/2026', 'AAA', 'buy', 10, 20)                     # open only
    tx(db, '9/1/2026', 'BBB', 'buy', 10, 20, contract=ADDR2)     # partly sold
    tx(db, '9/2/2026', 'BBB', 'sell', 5, 15, contract=ADDR2)
    tx(db, '9/1/2026', 'CCC', 'buy', 3, 6, contract=ADDR3)       # fully sold
    tx(db, '9/3/2026', 'CCC', 'sell', 3, 9, contract=ADDR3)
    open_, closed = wp._calculate_spot_fifo(db)
    expected = {p['position_key'] for p in open_.values()} | {p['position_key'] for p in closed.values()}
    assert wp._spot_all_position_keys(db) == expected
    assert expected == {KEY1, 'base ' + ADDR2, 'base ' + ADDR3}
