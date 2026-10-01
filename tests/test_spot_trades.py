"""Spot trades (HANDOFF_trading_performance.md rulings 4, 7, 11; Commit 4a):
the pure spot_trades module (build, parity, fmt_num, fmt_usd),
web_portfolio._spot_fifo_rows and GET /api/trading/spot/trades.

Pure tests feed build() hand-made rows. Parity tests use an in-memory sqlite
DB (the make_db / insert pattern of tests/test_spot_orphan_sells.py) and
compare build(_spot_fifo_rows(conn)) with the real _calculate_spot_fifo.
Route tests use a real init_db() tmp_path DB as in
tests/test_spot_position_books.py. price_usd is seeded as the TOTAL amount.
Fake contract addresses only.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import random
import sqlite3
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import spot_trades
import src.storage.portfolio_db as portfolio_db

ADDR1 = '0x' + '1' * 40
ADDR2 = '0x' + '2' * 40
ADDR3 = '0x' + '3' * 40
KEY1 = 'base ' + ADDR1
KEY2 = 'base ' + ADDR2


def r(id_, side, units, total, key='K', symbol='tok', date='2024-01-01'):
    return {'id': id_, 'key': key, 'symbol': symbol, 'side': side, 'units': float(units),
            'total': float(total), 'trade_date': date}


def approx(x):
    return pytest.approx(x, abs=1e-9)


# ── a. pure build() ──────────────────────────────────────────────────────

def test_open_add_partial_then_full_close():
    out = spot_trades.build([
        r(1, 'buy', 10, 100, date='2024-01-01'),     # 10 @ 10
        r(2, 'buy', 10, 300, date='2024-01-02'),     # 10 @ 30
        r(3, 'sell', 5, 150, date='2024-01-03'),     # cost 5 x 10 = 50 -> +100
    ])
    (t,) = out['trades']
    assert t['status'] == 'partly_closed' and t['open_units'] == approx(15) and t['close_date'] is None
    out = spot_trades.build([
        r(1, 'buy', 10, 100, date='2024-01-01'),
        r(2, 'buy', 10, 300, date='2024-01-02'),
        r(3, 'sell', 5, 150, date='2024-01-03'),
        r(4, 'sell', 15, 600, date='2024-01-04'),    # cost 5 x 10 + 10 x 30 = 350 -> +250
    ])
    (t,) = out['trades']
    assert out['orphans'] == []
    assert t['trade_key'] == 'K|1' and t['key'] == 'K' and t['symbol'] == 'TOK'
    assert t['status'] == 'closed' and t['close_date'] == '2024-01-04' and t['close_id'] == 4
    assert t['open_date'] == '2024-01-01' and t['first_buy_id'] == 1
    assert t['buy_ids'] == [1, 2] and t['sell_ids'] == [3, 4] and t['flags'] == []
    assert t['units_bought'] == approx(20) and t['units_sold'] == approx(20) and t['open_units'] == 0.0
    assert t['peak_units'] == approx(20)
    assert t['cost_in'] == approx(400) and t['proceeds'] == approx(750)
    assert t['avg_entry'] == approx(20) and t['avg_exit'] == approx(37.5)
    assert t['realized_pnl'] == approx(350) and t['last_sell_date'] == '2024-01-04'


def test_dust_close_then_second_trade():
    out = spot_trades.build([
        r(1, 'buy', 100, 100),                       # 100 @ 1
        r(2, 'sell', 99.5, 199),                     # 0.5 left = 0.5% of peak -> closed; +99.5
        r(3, 'buy', 10, 50),                         # new trade, 10 @ 5
        r(4, 'sell', 10, 80),                        # dust 0.5 @ 1 + 9.5 @ 5 = 48 -> +32
    ])
    t1, t2 = out['trades']
    assert t1['status'] == 'closed' and t1['close_id'] == 2 and t1['open_units'] == 0.0
    assert t1['realized_pnl'] == approx(99.5) and t1['units_sold'] == approx(99.5)
    assert t2['trade_key'] == 'K|3' and t2['first_buy_id'] == 3 and t2['trade_key'] != t1['trade_key']
    assert t2['status'] == 'closed' and t2['peak_units'] == approx(10)
    assert t2['realized_pnl'] == approx(32)            # the dust's cost landed here (documented effect)
    assert out['orphans'] == []


def test_dust_sell_after_close_goes_to_last_trade():
    out = spot_trades.build([
        r(1, 'buy', 100, 100),
        r(2, 'sell', 99.5, 199, date='2024-01-02'),  # closed
        r(3, 'sell', 0.5, 1.5, date='2024-01-03'),   # the dust: cost 0.5 -> +1.0
    ])
    (t,) = out['trades']
    assert t['status'] == 'closed' and t['close_id'] == 2 and t['close_date'] == '2024-01-02'
    assert t['flags'] == ['after_close_sell'] and t['sell_ids'] == [2, 3]
    assert t['units_sold'] == approx(100) and t['last_sell_date'] == '2024-01-03'
    assert t['realized_pnl'] == approx(100.5) and t['proceeds'] == approx(200.5)
    assert t['after_close_realized'] == approx(1.0)       # only the after-close sell's part
    assert out['orphans'] == []


def test_orphan_full_with_no_trade_ever():
    out = spot_trades.build([r(7, 'sell', 5, 50, key='Z', symbol='zz', date='2024-02-01')])
    assert out['trades'] == []
    assert out['orphans'] == [{'sell_id': 7, 'key': 'Z', 'symbol': 'zz', 'trade_date': '2024-02-01',
                               'units_sold': 5.0, 'units_unmatched': 5.0, 'realized_pnl': 50.0, 'status': 'full'}]


def test_orphan_partial_splits_the_sell():
    out = spot_trades.build([
        r(1, 'buy', 10, 100),                        # 10 @ 10
        r(2, 'sell', 15, 300),                       # 15 @ 20: 10 matched (cost 100), 5 unmatched (100)
    ])
    (t,) = out['trades']
    assert t['status'] == 'closed' and t['flags'] == ['orphan_sell']
    assert t['units_sold'] == approx(10) and t['proceeds'] == approx(200) and t['realized_pnl'] == approx(100)
    (o,) = out['orphans']
    assert o['sell_id'] == 2 and o['status'] == 'partial'
    assert o['units_sold'] == 15.0 and o['units_unmatched'] == approx(5) and o['realized_pnl'] == approx(100)


def test_sell_after_exact_close_is_full_orphan_on_last_trade():
    out = spot_trades.build([
        r(1, 'buy', 10, 100),
        r(2, 'sell', 10, 120),                       # exact close, lots empty
        r(3, 'sell', 2, 40),                         # nothing to match
    ])
    (t,) = out['trades']
    assert t['flags'] == ['after_close_sell', 'orphan_sell'] and t['status'] == 'closed'
    assert t['realized_pnl'] == approx(20) and t['units_sold'] == approx(10) and t['sell_ids'] == [2, 3]
    (o,) = out['orphans']
    assert o['status'] == 'full' and o['realized_pnl'] == approx(40) and o['units_unmatched'] == approx(2)


def test_zero_unit_rows():
    out = spot_trades.build([
        r(1, 'buy', 0, 5),                           # no trade open: ignored
        r(2, 'buy', 10, 100),                        # opens K|2
        r(3, 'buy', 0, 3),                           # joins buy_ids only
        r(4, 'sell', 0, 2),                          # nothing matched: +2, units unchanged
        r(5, 'sell', 10, 150),                       # zero lots pop at cost 0, then 10 @ 10 -> +50
        r(6, 'sell', 0, 4, key='Q'),                 # zero-unit sell, no trade ever -> orphan
    ])
    (t,) = out['trades']
    assert t['trade_key'] == 'K|2' and t['buy_ids'] == [2, 3] and t['sell_ids'] == [4, 5]
    assert t['units_bought'] == approx(10) and t['cost_in'] == approx(100) and t['peak_units'] == approx(10)
    assert t['status'] == 'closed' and t['close_id'] == 5 and t['realized_pnl'] == approx(52)
    (o,) = out['orphans']
    assert o['key'] == 'Q' and o['status'] == 'full' and o['units_unmatched'] == 0.0 and o['realized_pnl'] == 4.0


def test_zero_unit_sell_keeps_trade_partly_closed():
    out = spot_trades.build([r(1, 'buy', 10, 100), r(2, 'sell', 0, 2)])
    (t,) = out['trades']
    assert t['status'] == 'partly_closed' and t['open_units'] == approx(10) and t['realized_pnl'] == approx(2)
    assert t['avg_exit'] is None and out['orphans'] == []


def test_two_keys_never_mix():
    out = spot_trades.build([
        r(1, 'buy', 10, 100, key=KEY1, symbol='abc'),
        r(2, 'buy', 10, 500, key='ABC', symbol='ABC'),
        r(3, 'sell', 10, 200, key=KEY1, symbol='abc'),   # KEY1 lots only: cost 100
        r(4, 'sell', 5, 300, key='ABC', symbol='ABC'),   # ABC lots: cost 250
    ])
    by = {t['key']: t for t in out['trades']}
    assert set(by) == {KEY1, 'ABC'}
    assert by[KEY1]['status'] == 'closed' and by[KEY1]['realized_pnl'] == approx(100)
    assert by['ABC']['status'] == 'partly_closed' and by['ABC']['realized_pnl'] == approx(50)
    assert by[KEY1]['symbol'] == 'ABC' and by[KEY1]['trade_key'] == KEY1 + '|1'
    assert [t['key'] for t in out['trades']] == [KEY1, 'ABC']      # the order they opened


def test_other_sides_ignored():
    base = [r(1, 'buy', 10, 100), r(3, 'sell', 4, 80)]
    with_other = [r(1, 'buy', 10, 100), r(2, 'Transfer', 10, 0), r(3, 'SELL', 4, 80)]
    a, b = spot_trades.build(base), spot_trades.build(with_other)
    assert a == b


def test_parity_function():
    trades = [{'key': 'A', 'realized_pnl': 10.0}, {'key': 'A', 'realized_pnl': 5.0}]
    orphans = [{'key': 'B', 'realized_pnl': 3.0}]
    assert spot_trades.parity(trades, orphans, {'A': 15.0, 'B': 3.0 + 1e-8}) == {
        'ok': True, 'positions': 2, 'mismatches': []}
    res = spot_trades.parity(trades, orphans, {'A': 15.0, 'C': 2.0})
    assert res['ok'] is False and res['positions'] == 3
    assert res['mismatches'] == [{'key': 'B', 'fifo_realized': 0.0, 'trades_realized': 3.0, 'diff': 3.0},
                                 {'key': 'C', 'fifo_realized': 2.0, 'trades_realized': 0.0, 'diff': -2.0}]


# ── b. parity against the real _calculate_spot_fifo ──────────────────────

def make_db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE spot_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            units REAL NOT NULL,
            price_usd REAL NOT NULL,
            total_usd REAL NOT NULL,
            platform TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            chain TEXT DEFAULT '',
            contract_address TEXT DEFAULT ''
        )
    """)
    return conn


def insert_tx(conn, trade_date, symbol, side, units, price_usd, chain='', contract_address=''):
    conn.execute(
        """INSERT INTO spot_transactions
           (trade_date, symbol, side, units, price_usd, total_usd, chain, contract_address)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (trade_date, symbol, side, units, price_usd, price_usd, chain, contract_address))
    conn.commit()


def fifo_realized(conn):
    open_p, closed_p = wp._calculate_spot_fifo(conn)
    out = {}
    for pos in list(open_p.values()) + list(closed_p.values()):
        out[pos['position_key']] = pos['realized_pnl']
    return out


def check_parity(conn):
    built = spot_trades.build(wp._spot_fifo_rows(conn))
    res = spot_trades.parity(built['trades'], built['orphans'], fifo_realized(conn))
    assert res['ok'], res['mismatches']
    return built, res


def test_spot_fifo_rows_order_and_shape():
    conn = make_db()
    insert_tx(conn, '2024-01-03', 'abc', 'buy', 1, 10)                         # id 1, Jan 3
    insert_tx(conn, '1/2/2024', 'abc', 'buy', 2, 30, 'base', ADDR1)           # id 2, Jan 2
    insert_tx(conn, '2024-01-02', 'abc', 'Sell', 1, 20, 'base', ADDR1)        # id 3, Jan 2
    rows = wp._spot_fifo_rows(conn)
    assert [x['id'] for x in rows] == [2, 3, 1]
    assert rows[0] == {'id': 2, 'key': KEY1, 'symbol': 'abc', 'side': 'buy', 'units': 2.0, 'total': 30.0,
                       'trade_date': '1/2/2024'}
    assert rows[2]['key'] == 'ABC' and rows[1]['side'] == 'Sell'


def test_parity_hand_built_history():
    conn = make_db()
    c1 = dict(chain='base', contract_address=ADDR1)
    c2 = dict(chain='base', contract_address=ADDR2)
    # KEY1: open, add, partial, full close (inserted out of date order; two date formats)
    insert_tx(conn, '1/4/2024', 'aaa', 'sell', 15, 600, **c1)
    insert_tx(conn, '2024-01-01', 'aaa', 'buy', 10, 100, **c1)
    insert_tx(conn, '1/2/2024', 'aaa', 'buy', 10, 300, **c1)
    insert_tx(conn, '2024-01-03', 'aaa', 'sell', 5, 150, **c1)
    # KEY2: dust close, after-close dust sell, a second trade, then an orphan partial
    insert_tx(conn, '2024-02-01', 'bbb', 'buy', 100, 100, **c2)
    insert_tx(conn, '2/2/2024', 'bbb', 'sell', 99.5, 199, **c2)
    insert_tx(conn, '2024-02-02', 'bbb', 'sell', 0.2, 0.7, **c2)              # same day, later id
    insert_tx(conn, '2024-02-05', 'bbb', 'buy', 10, 50, **c2)
    insert_tx(conn, '2024-02-06', 'bbb', 'sell', 12, 120, **c2)               # 10.3 held: partial orphan
    # symbol-only ABC: zero-unit rows, a non buy/sell side, a full orphan first
    insert_tx(conn, '2024-03-01', 'abc', 'sell', 3, 30)
    insert_tx(conn, '2024-03-02', 'abc', 'buy', 0, 5)
    insert_tx(conn, '2024-03-03', 'abc', 'buy', 10, 100)
    insert_tx(conn, '2024-03-03', 'abc', 'transfer', 4, 0)
    insert_tx(conn, '3/4/2024', 'abc', 'buy', 0, 3)
    insert_tx(conn, '2024-03-05', 'abc', 'sell', 0, 2)
    insert_tx(conn, '2024-03-06', 'abc', 'sell', 4, 60)
    # a symbol-only key with the same symbol as KEY1's rows never mixes with KEY1
    insert_tx(conn, '2024-01-02', 'AAA', 'buy', 1, 1000)
    built, res = check_parity(conn)
    assert res['positions'] == 4
    by = {}
    for t in built['trades']:
        by.setdefault(t['key'], []).append(t)
    assert [t['status'] for t in by[KEY1]] == ['closed'] and by[KEY1][0]['realized_pnl'] == approx(350)
    assert [t['status'] for t in by[KEY2]] == ['closed', 'closed']
    assert by[KEY2][0]['flags'] == ['after_close_sell'] and by[KEY2][1]['flags'] == ['orphan_sell']
    assert [t['status'] for t in by['ABC']] == ['partly_closed'] and by['ABC'][0]['realized_pnl'] == approx(22)
    assert [t['status'] for t in by['AAA']] == ['open'] and by['AAA'][0]['realized_pnl'] == 0.0
    assert [(o['key'], o['status']) for o in built['orphans']] == [(KEY2, 'partial'), ('ABC', 'full')]


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_parity_random_histories(seed):
    rng = random.Random(seed)
    conn = make_db()
    keys = [dict(symbol='one', chain='base', contract_address=ADDR1),
            dict(symbol='two', chain='base', contract_address=ADDR3),
            dict(symbol='thr', chain='', contract_address='')]
    held = [0.0, 0.0, 0.0]
    for _ in range(200):
        k = rng.randrange(3)
        day = rng.randrange(1, 29)
        date = f'2024-05-{day:02d}' if rng.random() < 0.5 else f'5/{day}/2024'
        roll = rng.random()
        if roll < 0.5:
            side = 'buy'
            units = rng.choice([rng.uniform(0.1, 50), rng.uniform(1e-8, 1e-5), 0.0])
        else:
            side = 'sell'
            pick = rng.random()
            if pick < 0.15:
                units = held[k] + rng.uniform(0.1, 20)        # more than held (order may differ by date)
            elif pick < 0.3:
                units = rng.uniform(1e-10, 1e-6)              # tiny
            elif pick < 0.45:
                units = held[k] * rng.uniform(0.985, 1.0)     # near-full: dust closes
            else:
                units = held[k] * rng.uniform(0.05, 0.9)
        total = round(max(units, 1e-3) * rng.uniform(0.5, 50), 6) + 0.01
        held[k] = max(held[k] + (units if side == 'buy' else -units), 0.0)
        insert_tx(conn, date, keys[k]['symbol'], side, units, total,
                  keys[k]['chain'], keys[k]['contract_address'])
    built, res = check_parity(conn)
    assert res['positions'] == 3
    assert built['trades']                                   # something was derived
    for t in built['trades']:
        assert t['status'] in ('open', 'partly_closed', 'closed')
        assert (t['status'] == 'closed') == (t['close_id'] is not None)


# ── c. fmt_num / fmt_usd ─────────────────────────────────────────────────

def test_fmt_num():
    assert spot_trades.fmt_num(0.00000364) == '0.00000364'
    assert spot_trades.fmt_num(83805.0) == '83805'
    assert spot_trades.fmt_num(1234567.891) == '1234567.891'
    assert spot_trades.fmt_num(None) is None
    assert spot_trades.fmt_num(1e-12) == '0.000000000001'
    assert spot_trades.fmt_num(1e15) == '1000000000000000'
    assert spot_trades.fmt_num(0.0) == '0' and spot_trades.fmt_num(-0.0) == '0'
    assert spot_trades.fmt_num(-2.5) == '-2.5'
    assert spot_trades.fmt_num(1 / 3) == '0.3333333333'
    for x in (1e-12, 1e15, 3.2e-9, 7.77e20):
        assert 'e' not in spot_trades.fmt_num(x).lower()


def test_fmt_usd():
    assert spot_trades.fmt_usd(None) is None
    assert spot_trades.fmt_usd(12.5) == '12.500000'
    assert spot_trades.fmt_usd(-0.1234567) == '-0.123457'


# ── d. route ─────────────────────────────────────────────────────────────

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
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def tx(conn, date, symbol, side, units, total, chain='base', contract=ADDR1):
    conn.execute(
        "INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, chain, contract_address) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (date, symbol, side, units, total, total, chain, contract))
    conn.commit()


def table_counts(conn):
    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                         "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}


def seed(db):
    tx(db, '2024-01-01', 'aaa', 'buy', 10, 100)                         # KEY1: closed win +50
    tx(db, '2024-01-05', 'aaa', 'sell', 10, 150)
    tx(db, '2024-02-01', 'bbb', 'buy', 4, 400, contract=ADDR2)         # KEY2: long_term, closed
    tx(db, '2024-02-03', 'bbb', 'sell', 4, 300, contract=ADDR2)
    tx(db, '2024-03-01', 'ccc', 'buy', 100, 50, chain='', contract='')  # CCC: partly closed
    tx(db, '2024-03-02', 'ccc', 'sell', 40, 30, chain='', contract='')
    tx(db, '2024-01-10', 'aaa', 'buy', 2, 40)                          # KEY1 second trade: closed loss -10
    tx(db, '1/12/2024', 'aaa', 'sell', 2, 30)
    tx(db, '2024-04-01', 'ddd', 'buy', 0.00000364, 1, chain='', contract='')   # DDD: open
    tx(db, '2024-04-02', 'eee', 'sell', 3, 9, chain='', contract='')   # EEE: orphan
    db.execute("INSERT INTO spot_position_books (position_key, book, updated_at) VALUES (?, ?, ?)",
               (KEY2, 'long_term', '2026-10-01T00:00:00+00:00'))
    db.commit()


def test_route_trades_books_summary_and_formats(db, client):
    seed(db)
    before = table_counts(db)
    r = client.get('/api/trading/spot/trades')
    assert r.status_code == 200
    body = r.get_json()
    assert table_counts(db) == before                     # read-only
    assert body['parity']['ok'] is True and body['parity']['mismatches'] == []
    assert body['parity']['positions'] == 5

    trades = body['trades']
    assert [t['open_date'] for t in trades] == ['2024-04-01', '2024-03-01', '2024-02-01', '2024-01-10',
                                                '2024-01-01']
    by = {t['trade_key']: t for t in trades}
    win = by[KEY1 + '|1']
    assert win['position_key'] == KEY1 and win['symbol'] == 'AAA' and win['book'] == 'trading'
    assert win['status'] == 'closed' and win['close_date'] == '2024-01-05' and win['first_buy_id'] == 1
    assert win['buy_count'] == 1 and win['sell_count'] == 1 and win['flags'] == []
    assert win['units_bought'] == '10' and win['units_sold'] == '10' and win['open_units'] == '0'
    assert win['peak_units'] == '10' and win['avg_entry'] == '10' and win['avg_exit'] == '15'
    assert win['cost_in'] == '100.000000' and win['proceeds'] == '150.000000'
    assert win['realized_pnl'] == '50.000000'
    assert by[KEY1 + '|7']['realized_pnl'] == '-10.000000' and by[KEY1 + '|7']['close_date'] == '1/12/2024'
    lt = by[KEY2 + '|3']
    assert lt['book'] == 'long_term' and lt['status'] == 'closed' and lt['realized_pnl'] == '-100.000000'
    ccc = by['CCC|5']
    assert ccc['status'] == 'partly_closed' and ccc['open_units'] == '60' and ccc['avg_exit'] == '0.75'
    ddd = by['DDD|9']
    assert ddd['status'] == 'open' and ddd['units_bought'] == '0.00000364' and ddd['avg_exit'] is None
    assert ddd['realized_pnl'] == '0.000000' and ddd['close_date'] is None
    for t in trades:
        for f in ('units_bought', 'units_sold', 'open_units', 'peak_units', 'cost_in', 'proceeds', 'realized_pnl'):
            assert isinstance(t[f], str)
        assert 'key' not in t and 'buy_ids' not in t and '_realized' not in t

    assert body['orphan_sells'] == [{'sell_id': 10, 'position_key': 'EEE', 'symbol': 'eee',
                                     'trade_date': '2024-04-02', 'units_sold': '3', 'units_unmatched': '3',
                                     'realized_pnl': '9.000000', 'status': 'full'}]
    # trading book only: the long_term loss is excluded; orphans count across books
    assert body['summary'] == {'closed_count': 2, 'partly_closed_count': 1, 'open_count': 1,
                               'closed_realized': '40.000000', 'win_count': 1, 'loss_count': 1,
                               'orphan_count': 1}


def test_route_empty_db(db, client):
    r = client.get('/api/trading/spot/trades')
    assert r.status_code == 200
    body = r.get_json()
    assert body['trades'] == [] and body['orphan_sells'] == []
    assert body['parity'] == {'ok': True, 'positions': 0, 'mismatches': []}
    assert body['summary']['closed_realized'] == '0.000000' and body['summary']['orphan_count'] == 0


def test_route_ties_by_first_buy_id_desc(db, client):
    tx(db, '2024-06-01', 'aaa', 'buy', 1, 10)
    tx(db, '6/1/2024', 'bbb', 'buy', 1, 10, contract=ADDR2)
    keys = [t['trade_key'] for t in client.get('/api/trading/spot/trades').get_json()['trades']]
    assert keys == [KEY2 + '|2', KEY1 + '|1']


def test_route_error_is_500(db, client, monkeypatch):
    def boom(conn):
        raise RuntimeError('nope')
    monkeypatch.setattr(wp, '_spot_fifo_rows', boom)
    r = client.get('/api/trading/spot/trades')
    assert r.status_code == 500 and r.get_json() == {'error': 'nope'}
