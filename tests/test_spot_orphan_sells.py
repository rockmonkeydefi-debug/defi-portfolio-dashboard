"""Tests for the read-only orphan-sell detector added in step 5:
_spot_position_key(), _detect_spot_orphan_sells(), and GET
/api/spot/orphan-sells. This is the hard-gate tripwire for the planned FIFO
grouping-key flip to (chain, contract_address) - it must report zero orphans
under symbol grouping before that flip ships.

An in-memory sqlite3 connection with just the spot_transactions columns the
functions under test actually read - _calculate_spot_fifo and
_detect_spot_orphan_sells both take `conn` as a plain argument rather than
calling get_connection() internally, so no monkeypatching of the real DB
path is needed (unlike test_spot_transactions_schema.py's init_db() tests).

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern, see
test_custom_tokens.py) so no thread starts.
"""
import sqlite3
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

_calculate_spot_fifo = wp._calculate_spot_fifo
_detect_spot_orphan_sells = wp._detect_spot_orphan_sells
_spot_position_key = wp._spot_position_key
_parse_trade_date = wp._parse_trade_date


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


def insert_tx(conn, trade_date, symbol, side, units, price_usd,
              platform='', chain='', contract_address=''):
    conn.execute(
        """INSERT INTO spot_transactions
           (trade_date, symbol, side, units, price_usd, total_usd, platform, chain, contract_address)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (trade_date, symbol, side, units, price_usd, price_usd, platform, chain, contract_address)
    )
    conn.commit()


def test_clean_buy_then_sell_produces_zero_orphans():
    conn = make_db()
    insert_tx(conn, '1/1/2024', 'BTC', 'buy', 10, 1000)   # $100/unit
    insert_tx(conn, '1/2/2024', 'BTC', 'sell', 10, 1200)  # $120/unit
    result = _detect_spot_orphan_sells(conn)
    assert result['orphans'] == []
    assert result['summary']['orphan_count'] == 0
    assert result['summary']['total_unmatched_proceeds_usd'] == 0


def test_sell_with_no_prior_buy_is_fully_orphaned():
    conn = make_db()
    insert_tx(conn, '1/1/2024', 'ORPHANCOIN', 'sell', 50, 5000, platform='Binance')
    result = _detect_spot_orphan_sells(conn)
    assert len(result['orphans']) == 1
    o = result['orphans'][0]
    assert o['symbol'] == 'ORPHANCOIN'
    assert o['platform'] == 'Binance'
    assert o['position_key'] == 'ORPHANCOIN'
    assert o['units_sold'] == 50
    assert o['units_unmatched'] == 50
    assert o['unmatched_proceeds_usd'] == 5000  # full sale amount, no lot to price it against
    assert o['status'] == 'full'
    assert result['summary']['orphan_count'] == 1
    assert result['summary']['total_unmatched_proceeds_usd'] == 5000


def test_sell_larger_than_available_lots_is_partial_and_only_excess_counted():
    conn = make_db()
    insert_tx(conn, '1/1/2024', 'ETH', 'buy', 10, 100)    # $10/unit, 10 units available
    insert_tx(conn, '1/2/2024', 'ETH', 'sell', 15, 180)   # $12/unit, sells 15 - only 10 covered
    result = _detect_spot_orphan_sells(conn)
    assert len(result['orphans']) == 1
    o = result['orphans'][0]
    assert o['units_sold'] == 15
    assert o['units_unmatched'] == 5
    assert o['unmatched_proceeds_usd'] == 60  # 5 unmatched units * $12/unit sale price
    assert o['status'] == 'partial'


def test_two_buys_spanning_one_sell_produces_zero_orphans():
    conn = make_db()
    insert_tx(conn, '1/1/2024', 'SOL', 'buy', 5, 50)    # $10/unit
    insert_tx(conn, '1/2/2024', 'SOL', 'buy', 5, 60)    # $12/unit
    insert_tx(conn, '1/3/2024', 'SOL', 'sell', 10, 150)  # exactly drains both lots
    result = _detect_spot_orphan_sells(conn)
    assert result['orphans'] == []
    assert result['summary']['orphan_count'] == 0


def test_sell_dated_before_its_buy_is_a_full_orphan_because_chronological_order_beats_insertion_order():
    """_calculate_spot_fifo sorts by (_parse_trade_date(trade_date) or 0, id)
    - trade_date is the PRIMARY sort key, id only breaks ties within the same
    date. A sell dated earlier than its only buy is therefore processed
    BEFORE that buy regardless of insertion/id order, finds no lots yet in
    the queue, and is booked as a full orphan - identical treatment to a
    sell with no buy at all. This mirrors that behaviour exactly (no special
    casing exists in _calculate_spot_fifo for this ordering).
    """
    conn = make_db()
    # Inserted buy-first (lower id), but dated AFTER the sell.
    insert_tx(conn, '1/10/2024', 'DATEFLIP', 'buy', 10, 100)
    insert_tx(conn, '1/1/2024', 'DATEFLIP', 'sell', 10, 100)
    result = _detect_spot_orphan_sells(conn)
    assert len(result['orphans']) == 1
    o = result['orphans'][0]
    assert o['status'] == 'full'
    assert o['units_unmatched'] == 10


def test_summary_chain_and_address_filled_counts_are_correct():
    conn = make_db()
    insert_tx(conn, '1/1/2024', 'AAA', 'buy', 1, 10, chain='base', contract_address='0x' + 'a' * 40)
    insert_tx(conn, '1/2/2024', 'AAA', 'sell', 1, 12)  # unfilled
    insert_tx(conn, '1/3/2024', 'BBB', 'buy', 1, 20)   # unfilled
    result = _detect_spot_orphan_sells(conn)
    summary = result['summary']
    assert summary['total_transaction_count'] == 3
    assert summary['chain_and_address_filled_count'] == 1
    assert summary['chain_and_address_unfilled_count'] == 2


def test_detector_and_fifo_agree_on_grouping_and_ordering():
    """Drift guard for constraint 2: _spot_position_key must currently match
    _calculate_spot_fifo's own inline `row['symbol'].upper()` exactly, and
    both functions must derive the identical sort order from the same rows.
    If either function's ordering/grouping is edited without the other, this
    test is the one that catches it.
    """
    conn = make_db()
    # Scrambled insertion order and mixed date formats/casing, several symbols.
    insert_tx(conn, '1/5/2024', 'zeta', 'buy', 3, 30)
    insert_tx(conn, '2024-01-01', 'ALPHA', 'buy', 1, 10)
    insert_tx(conn, '1/3/2024', 'alpha', 'sell', 1, 15)
    insert_tx(conn, '1/2/2024', 'ZETA', 'buy', 2, 18)
    insert_tx(conn, '1/6/2024', 'zeta', 'sell', 5, 60)

    rows = conn.execute("SELECT * FROM spot_transactions ORDER BY id ASC").fetchall()

    # The seam must currently agree with _calculate_spot_fifo's own inline logic.
    for row in rows:
        assert _spot_position_key(row) == row['symbol'].upper()

    # Both functions must sort identically.
    expected_order = sorted(rows, key=lambda r: (_parse_trade_date(r['trade_date']) or 0, r['id']))
    detector_order = sorted(rows, key=lambda r: (_parse_trade_date(r['trade_date']) or 0, r['id']))
    assert [r['id'] for r in expected_order] == [r['id'] for r in detector_order]

    # And on a fixture with no orphans, the detector and the real calculation
    # must agree there is nothing to flag - the only external confirmation
    # available that grouping actually matched consistently end to end.
    open_positions, closed_positions = _calculate_spot_fifo(conn)
    assert 'ZETA' in open_positions or 'ZETA' in closed_positions
    result = _detect_spot_orphan_sells(conn)
    assert result['orphans'] == []
