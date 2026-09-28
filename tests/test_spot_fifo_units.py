"""_calculate_spot_fifo's additive unit keys (Spot Trade History, Sep 28):
units_bought, units_sold, cost_basis_sold and pct_sold on every
closed_positions entry; every pre-existing closed key and every
open_positions field unchanged.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). price_usd is seeded as the TOTAL transaction amount, as the
Spot page stores it. _reference_spot_fifo below is origin/main's function
body pasted verbatim (only the def line renamed) - the invariance reference.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import copy
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db

# Names the pasted reference body reads from web_portfolio's module scope.
_parse_trade_date = wp._parse_trade_date
_spot_position_key = wp._spot_position_key
_stringify_spot_position_key = wp._stringify_spot_position_key

NEW_KEYS = ('units_bought', 'units_sold', 'cost_basis_sold', 'pct_sold')


def _reference_spot_fifo(conn):
    """
    FIFO P&L across all spot_transactions rows.
    Returns (open_positions, closed_positions) dicts keyed by _spot_position_key(row)
    (a (chain, contract_address) tuple, or a plain uppercase symbol string when
    either is blank). Every value dict also carries a 'symbol' field (the
    uppercased symbol of the chronologically earliest row seen under that key)
    and a 'position_key' field (the JSON-safe stringified key) - callers that
    need a plain string (price lookups, SQL params) must read pos['symbol'] or
    pos['position_key'], never the dict key itself, since the key may be a tuple.
    """
    from collections import defaultdict, deque

    rows = conn.execute(
        "SELECT * FROM spot_transactions ORDER BY id ASC"
    ).fetchall()
    rows = sorted(rows, key=lambda r: (_parse_trade_date(r['trade_date']) or 0, r['id']))

    lots            = defaultdict(deque)   # position_key -> deque of {units, price, date}
    realized_pnl    = defaultdict(float)
    total_invested  = defaultdict(float)
    total_proceeds  = defaultdict(float)
    last_sell_date  = defaultdict(str)
    all_keys        = set()
    first_symbol    = {}

    for row in rows:
        key   = _spot_position_key(row)
        side  = row['side'].lower()
        units = float(row['units'])
        tx_amt = float(row['price_usd'])          # total transaction amount (incl. fees)
        price  = tx_amt / units if units > 1e-12 else 0.0  # derive per-unit cost for FIFO lots
        total  = tx_amt
        date  = row['trade_date']

        all_keys.add(key)
        if key not in first_symbol:
            first_symbol[key] = row['symbol'].upper()

        if side == 'buy':
            lots[key].append({'units': units, 'price': price, 'date': date})
            total_invested[key] += total
        elif side == 'sell':
            remaining  = units
            cost_basis = 0.0
            while remaining > 1e-9 and lots[key]:
                lot = lots[key][0]
                if lot['units'] <= remaining + 1e-9:
                    cost_basis += lot['units'] * lot['price']
                    remaining  -= lot['units']
                    lots[key].popleft()
                else:
                    cost_basis     += remaining * lot['price']
                    lot['units']   -= remaining
                    remaining       = 0.0
            total_proceeds[key] += total
            realized_pnl[key]   += total - cost_basis
            last_sell_date[key]  = date

    open_positions = {}
    for key, lot_queue in lots.items():
        remaining_units = sum(l['units'] for l in lot_queue)
        if remaining_units > 1e-6:
            total_cost = sum(l['units'] * l['price'] for l in lot_queue)
            open_positions[key] = {
                'symbol':           first_symbol[key],
                'position_key':     _stringify_spot_position_key(key),
                'chain':            key[0] if isinstance(key, tuple) else '',
                'contract_address': key[1] if isinstance(key, tuple) else '',
                'units':            remaining_units,
                'avg_cost_usd':     total_cost / remaining_units,
                'total_cost_basis': total_cost,
                'oldest_lot_date':  lot_queue[0]['date'],
                'lot_count':        len(lot_queue),
                'lots':             list(lot_queue),
                'realized_pnl':     realized_pnl.get(key, 0.0),
            }

    closed_positions = {}
    for key in all_keys:
        if total_proceeds.get(key, 0.0) > 0:
            invested  = total_invested[key]
            proceeds  = total_proceeds[key]
            rpnl      = realized_pnl.get(key, 0.0)
            # Cost basis of sold units = proceeds minus the profit on those units.
            # Using total_invested as denominator is wrong when only some units were sold
            # (it includes the cost of unsold lots, making profitable trades look negative).
            cost_basis_sold = proceeds - rpnl
            closed_positions[key] = {
                'symbol':          first_symbol[key],
                'position_key':    _stringify_spot_position_key(key),
                'realized_pnl':    rpnl,
                'total_invested':  invested,
                'total_proceeds':  proceeds,
                'last_sell_date':  last_sell_date.get(key, ''),
                'roi_pct':         (rpnl / cost_basis_sold * 100) if cost_basis_sold > 0 else 0.0,
            }

    return open_positions, closed_positions



@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    conn = portfolio_db.get_connection()
    yield conn
    conn.close()


def tx(conn, date, symbol, side, units, total, chain='base', contract=None):
    contract = contract if contract is not None else '0x' + symbol.lower().ljust(40, '0')[:40]
    conn.execute(
        "INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, chain, contract_address) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (date, symbol, side, units, total, total, chain, contract))
    conn.commit()


def only(closed):
    assert len(closed) == 1
    return next(iter(closed.values()))


def test_t1_partial_sale(db):
    tx(db, '2026-09-01', 'AAA', 'buy', 100, 100)
    tx(db, '2026-09-02', 'AAA', 'buy', 100, 300)
    tx(db, '2026-09-03', 'AAA', 'sell', 50, 250)
    _, closed = wp._calculate_spot_fifo(db)
    c = only(closed)
    assert c['realized_pnl'] == pytest.approx(200)
    assert c['cost_basis_sold'] == pytest.approx(50)
    assert c['units_bought'] == pytest.approx(200)
    assert c['units_sold'] == pytest.approx(50)
    assert c['pct_sold'] == pytest.approx(25)
    assert c['roi_pct'] == pytest.approx(400)
    assert c['total_invested'] == pytest.approx(400)


def test_t2_full_sale(db):
    tx(db, '2026-09-01', 'BBB', 'buy', 10, 100)
    tx(db, '2026-09-02', 'BBB', 'sell', 10, 150)
    _, closed = wp._calculate_spot_fifo(db)
    c = only(closed)
    assert c['pct_sold'] == pytest.approx(100)
    assert c['cost_basis_sold'] == pytest.approx(100)
    assert c['realized_pnl'] == pytest.approx(50)


def test_t3_buy_after_a_full_sale(db):
    tx(db, '2026-09-01', 'CCC', 'buy', 100, 100)
    tx(db, '2026-09-02', 'CCC', 'sell', 100, 150)
    tx(db, '2026-09-03', 'CCC', 'buy', 50, 60)
    open_, closed = wp._calculate_spot_fifo(db)
    c = only(closed)
    assert c['units_bought'] == pytest.approx(150)
    assert c['units_sold'] == pytest.approx(100)
    assert c['pct_sold'] == pytest.approx(66.6666667)
    assert c['realized_pnl'] == pytest.approx(50)
    key = next(iter(closed))
    assert key in open_ and open_[key]['units'] == pytest.approx(50)


def test_t4_oversold(db):
    tx(db, '2026-09-01', 'DDD', 'buy', 10, 10)
    tx(db, '2026-09-02', 'DDD', 'sell', 15, 30)
    _, closed = wp._calculate_spot_fifo(db)
    _, ref = _reference_spot_fifo(db)
    c, r = only(closed), only(ref)
    assert c['units_sold'] == pytest.approx(15)
    assert c['pct_sold'] == pytest.approx(150)
    # Realized and the cost of sold as today's logic gives (lots run out after 10 units).
    assert c['realized_pnl'] == r['realized_pnl'] == pytest.approx(20)
    assert c['cost_basis_sold'] == pytest.approx(r['total_proceeds'] - r['realized_pnl']) == pytest.approx(10)


def test_t5_invariance_against_the_pre_change_function(db):
    # Key 1: partial sale then a later buy (ISO dates).
    tx(db, '2026-08-01', 'EEE', 'buy', 1000, 500)
    tx(db, '2026-08-05', 'EEE', 'sell', 300, 330)
    tx(db, '2026-08-09', 'EEE', 'buy', 200, 260)
    # Key 2: full exit, then re-entry (M/D/YYYY dates, out of id order).
    tx(db, '8/20/2026', 'FFF', 'sell', 40, 90, contract='0x' + 'f' * 40)
    tx(db, '8/10/2026', 'FFF', 'buy', 40, 60, contract='0x' + 'f' * 40)
    tx(db, '9/2/2026', 'FFF', 'buy', 25, 70, contract='0x' + 'f' * 40)
    # Key 3: symbol-only key (blank chain/contract), two partial sells.
    tx(db, '2026-09-01', 'GGG', 'buy', 12.5, 1250, chain='', contract='')
    tx(db, '9/5/2026', 'GGG', 'sell', 2.5, 300, chain='', contract='')
    tx(db, '2026-09-07', 'GGG', 'sell', 5, 450, chain='', contract='')
    # A buy-only key: open, never closed.
    tx(db, '2026-09-08', 'HHH', 'buy', 3, 33)
    ref_open, ref_closed = _reference_spot_fifo(db)
    ref_open, ref_closed = copy.deepcopy(ref_open), copy.deepcopy(ref_closed)
    new_open, new_closed = wp._calculate_spot_fifo(db)
    assert new_open == ref_open
    assert set(new_closed) == set(ref_closed) and len(new_closed) == 3
    for key, ref_row in ref_closed.items():
        new_row = new_closed[key]
        assert {k: v for k, v in new_row.items() if k not in NEW_KEYS} == ref_row
        assert set(new_row) == set(ref_row) | set(NEW_KEYS)
        assert new_row['cost_basis_sold'] == ref_row['total_proceeds'] - ref_row['realized_pnl']


def test_t6_route_returns_the_new_keys(db, monkeypatch):
    tx(db, '2026-09-01', 'III', 'buy', 100, 100)
    tx(db, '2026-09-02', 'III', 'sell', 25, 50)
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    client = wp.app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
    r = client.get('/api/spot/history')
    assert r.status_code == 200
    rows = r.get_json()
    assert len(rows) == 1
    row = rows[0]
    for k in NEW_KEYS:
        assert k in row
    assert row['units_bought'] == pytest.approx(100)
    assert row['units_sold'] == pytest.approx(25)
    assert row['pct_sold'] == pytest.approx(25)
    assert row['cost_basis_sold'] == pytest.approx(25)
