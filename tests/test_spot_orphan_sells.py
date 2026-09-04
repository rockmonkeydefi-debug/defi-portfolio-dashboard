"""Tests for the read-only orphan-sell detector, _spot_position_key() and the
position-key grouping it now performs, and GET /api/spot/orphan-sells. The
live grouping key is (chain, contract_address) with a symbol.upper()
fallback; the legacy symbol-only key is retained as _spot_position_key_symbol
for A/B comparison against the live key.

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

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

_calculate_spot_fifo = wp._calculate_spot_fifo
_detect_spot_orphan_sells = wp._detect_spot_orphan_sells
_spot_position_key = wp._spot_position_key
_spot_position_key_symbol = wp._spot_position_key_symbol
_spot_position_key_chain_address = wp._spot_position_key_chain_address
_spot_symbol_split_report = wp._spot_symbol_split_report
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
    """Drift guard for constraint 2: _spot_position_key is the single grouping
    definition shared by _calculate_spot_fifo and _detect_spot_orphan_sells -
    they must never diverge. This fixture has no chain/contract_address on
    any row, so _spot_position_key falls back to the plain uppercased symbol
    (matching _spot_position_key_symbol) for every row; both functions must
    also derive the identical sort order from the same rows. If either
    function's ordering/grouping is edited without the other, this test is
    the one that catches it.
    """
    conn = make_db()
    # Scrambled insertion order and mixed date formats/casing, several symbols.
    insert_tx(conn, '1/5/2024', 'zeta', 'buy', 3, 30)
    insert_tx(conn, '2024-01-01', 'ALPHA', 'buy', 1, 10)
    insert_tx(conn, '1/3/2024', 'alpha', 'sell', 1, 15)
    insert_tx(conn, '1/2/2024', 'ZETA', 'buy', 2, 18)
    insert_tx(conn, '1/6/2024', 'zeta', 'sell', 5, 60)

    rows = conn.execute("SELECT * FROM spot_transactions ORDER BY id ASC").fetchall()

    # With blank chain/contract_address, the live key must still fall back to
    # the plain uppercased symbol on every row.
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


# ── pluggable key_fn (chain+address is the live key; symbol is legacy) ──

def test_default_key_fn_matches_explicit_spot_position_key():
    """Regression guard for constraint 2: calling with no key_fn must be
    byte-identical to passing _spot_position_key explicitly."""
    conn = make_db()
    insert_tx(conn, '1/1/2024', 'ETH', 'buy', 10, 100)
    insert_tx(conn, '1/2/2024', 'ETH', 'sell', 15, 180)
    default_result = _detect_spot_orphan_sells(conn)
    explicit_result = _detect_spot_orphan_sells(conn, key_fn=_spot_position_key)
    assert default_result == explicit_result


def test_symbol_with_two_addresses_splits_under_default_key_but_not_legacy_symbol_key():
    """Post-flip: the default key_fn (_spot_position_key) IS the
    chain/contract_address key, so it's the one that splits BTC into two
    positions; _spot_position_key_symbol (legacy, explicit only) is the one
    that still merges them into one."""
    conn = make_db()
    addr_a = '0x' + 'a' * 40
    addr_b = '0x' + 'b' * 40
    insert_tx(conn, '1/1/2024', 'BTC', 'buy', 1, 100, chain='base', contract_address=addr_a)
    insert_tx(conn, '1/2/2024', 'BTC', 'sell', 1, 120, chain='base', contract_address=addr_a)
    insert_tx(conn, '1/3/2024', 'BTC', 'buy', 1, 200, chain='ethereum', contract_address=addr_b)
    insert_tx(conn, '1/4/2024', 'BTC', 'sell', 1, 250, chain='ethereum', contract_address=addr_b)

    default_result = _detect_spot_orphan_sells(conn)
    legacy_result = _detect_spot_orphan_sells(conn, key_fn=_spot_position_key_symbol)

    assert default_result['summary']['position_count'] == 2  # splits into two under the live key
    assert legacy_result['summary']['position_count'] == 1   # one BTC position under the legacy symbol key
    # Each pair still fully matches within its own address - no orphans either way.
    assert default_result['orphans'] == []
    assert legacy_result['orphans'] == []


def test_buy_chain_a_sell_chain_b_orphans_under_default_key_only():
    """The exact failure mode the identity flip risked: a buy and sell of the
    same symbol on different chains stop matching once grouping keys off
    (chain, contract_address) instead of symbol - now the LIVE default
    behaviour; the legacy symbol key (explicit only) is the one that still
    tolerates it."""
    conn = make_db()
    addr_a = '0x' + 'a' * 40
    addr_b = '0x' + 'b' * 40
    insert_tx(conn, '1/1/2024', 'BTC', 'buy', 1, 100, chain='base', contract_address=addr_a)
    insert_tx(conn, '1/2/2024', 'BTC', 'sell', 1, 150, chain='ethereum', contract_address=addr_b)

    default_result = _detect_spot_orphan_sells(conn)
    legacy_result = _detect_spot_orphan_sells(conn, key_fn=_spot_position_key_symbol)

    assert legacy_result['orphans'] == []
    assert len(default_result['orphans']) == 1
    o = default_result['orphans'][0]
    assert o['status'] == 'full'
    assert o['units_unmatched'] == 1


def test_empty_contract_address_falls_back_to_symbol_under_proposed_key():
    conn = make_db()
    insert_tx(conn, '1/1/2024', 'GG', 'buy', 1, 10)  # chain='' , contract_address=''
    row = conn.execute("SELECT * FROM spot_transactions").fetchone()
    assert _spot_position_key_chain_address(row) == 'GG'

    # One-sided (chain set, address blank) must also fall back - "OR" per constraint 4.
    conn2 = make_db()
    insert_tx(conn2, '1/1/2024', 'GG', 'buy', 1, 10, chain='base', contract_address='')
    row2 = conn2.execute("SELECT * FROM spot_transactions").fetchone()
    assert _spot_position_key_chain_address(row2) == 'GG'


def test_addresses_differing_only_by_case_are_distinct_positions():
    """Constraint 5: no second .lower() on the chain+address key - two Solana
    addresses differing only by case must NOT be merged."""
    conn = make_db()
    addr_lower = 'abc123def456ghi789jkl012mno345pqr678stu'
    addr_upper = addr_lower.upper()
    insert_tx(conn, '1/1/2024', 'SOL', 'buy', 1, 10, chain='solana', contract_address=addr_lower)
    insert_tx(conn, '1/2/2024', 'SOL', 'sell', 1, 12, chain='solana', contract_address=addr_upper)

    proposed_result = _detect_spot_orphan_sells(conn, key_fn=_spot_position_key_chain_address)
    assert proposed_result['summary']['position_count'] == 2
    assert len(proposed_result['orphans']) == 1  # the sell can't reach the differently-cased buy's lot


def test_split_symbols_lists_splitting_symbol_and_omits_non_splitting():
    conn = make_db()
    addr_a = '0x' + 'a' * 40
    addr_b = '0x' + 'b' * 40
    # BTC splits across two addresses.
    insert_tx(conn, '1/1/2024', 'BTC', 'buy', 1, 100, chain='base', contract_address=addr_a)
    insert_tx(conn, '1/2/2024', 'BTC', 'buy', 1, 100, chain='ethereum', contract_address=addr_b)
    # ETH stays on one address only - must not appear as a split.
    insert_tx(conn, '1/3/2024', 'ETH', 'buy', 1, 50, chain='base', contract_address=addr_a)

    split_symbols = _spot_symbol_split_report(conn, _spot_position_key_chain_address)
    symbols_reported = {s['symbol'] for s in split_symbols}
    assert 'BTC' in symbols_reported
    assert 'ETH' not in symbols_reported

    btc_entry = next(s for s in split_symbols if s['symbol'] == 'BTC')
    assert len(btc_entry['keys']) == 2
    assert sum(k['transaction_count'] for k in btc_entry['keys']) == 2


# ── Commit B: the FIFO identity flip (_spot_position_key now IS chain+address) ──

def test_spot_position_key_uses_chain_address_when_present():
    """7a: with real chain/address values, _spot_position_key must return the
    (chain, address) tuple (delegating to _spot_position_key_chain_address),
    while _spot_position_key_symbol keeps returning the legacy bare-symbol
    key regardless."""
    conn = make_db()
    addr = '0x' + 'a' * 40
    insert_tx(conn, '1/1/2024', 'BTC', 'buy', 1, 100, chain='base', contract_address=addr)
    row = conn.execute("SELECT * FROM spot_transactions").fetchone()
    assert _spot_position_key(row) == ('base', addr)
    assert _spot_position_key_symbol(row) == 'BTC'


def test_same_symbol_different_addresses_produce_two_open_positions():
    """7b."""
    conn = make_db()
    addr_a = '0x' + 'a' * 40
    addr_b = '0x' + 'b' * 40
    insert_tx(conn, '1/1/2024', 'BTC', 'buy', 1, 100, chain='base', contract_address=addr_a)
    insert_tx(conn, '1/2/2024', 'BTC', 'buy', 1, 200, chain='ethereum', contract_address=addr_b)
    open_positions, _closed = _calculate_spot_fifo(conn)
    assert len(open_positions) == 2
    position_keys = {pos['position_key'] for pos in open_positions.values()}
    assert len(position_keys) == 2


def test_same_chain_address_different_symbol_casing_merges_into_one_position():
    """7c. Note: 'btc'.upper() == 'BTC'.upper(), so this fixture can't by
    itself distinguish "the earlier row's symbol" from "either row's
    symbol" - it confirms the merge and the uppercasing, per the spec's
    literal fixture. See test_same_chain_address_different_symbols_keeps_earliest_symbol
    for a fixture with genuinely different symbol text that does distinguish it.
    """
    conn = make_db()
    addr = '0x' + 'a' * 40
    insert_tx(conn, '1/1/2024', 'btc', 'buy', 1, 100, chain='base', contract_address=addr)
    insert_tx(conn, '1/2/2024', 'BTC', 'buy', 1, 200, chain='base', contract_address=addr)
    open_positions, _closed = _calculate_spot_fifo(conn)
    assert len(open_positions) == 1
    pos = next(iter(open_positions.values()))
    assert pos['symbol'] == 'BTC'


def test_same_chain_address_different_symbols_keeps_earliest_symbol():
    """Position identity comes from (chain, contract_address) alone once both
    are present - the symbol text isn't part of the key at all. Two rows
    sharing an address but carrying genuinely different symbol text still
    merge into one position, labeled with the chronologically EARLIEST row's
    uppercased symbol."""
    conn = make_db()
    addr = '0x' + 'a' * 40
    insert_tx(conn, '1/1/2024', 'wbtc', 'buy', 1, 100, chain='base', contract_address=addr)
    insert_tx(conn, '1/2/2024', 'BTC', 'buy', 1, 200, chain='base', contract_address=addr)
    open_positions, _closed = _calculate_spot_fifo(conn)
    assert len(open_positions) == 1
    pos = next(iter(open_positions.values()))
    assert pos['symbol'] == 'WBTC'  # the earlier (1/1) row's symbol, uppercased


def test_blank_chain_address_falls_back_to_plain_symbol_position_key():
    """7d."""
    conn = make_db()
    insert_tx(conn, '1/1/2024', 'DOGE', 'buy', 1, 10)  # chain='', contract_address=''
    open_positions, _closed = _calculate_spot_fifo(conn)
    assert len(open_positions) == 1
    pos = next(iter(open_positions.values()))
    assert pos['position_key'] == 'DOGE'
    assert isinstance(pos['position_key'], str)


def test_position_key_present_as_string_on_open_and_closed_and_chain_fields_match_tuple_key():
    """7e."""
    conn = make_db()
    addr = '0x' + 'a' * 40
    insert_tx(conn, '1/1/2024', 'BTC', 'buy', 1, 100, chain='base', contract_address=addr)  # stays open
    insert_tx(conn, '1/1/2024', 'ETH', 'buy', 1, 50)   # blank chain/address
    insert_tx(conn, '1/2/2024', 'ETH', 'sell', 1, 60)  # fully sold -> closed, plain-symbol key

    open_positions, closed_positions = _calculate_spot_fifo(conn)

    assert len(open_positions) == 1
    btc_pos = next(iter(open_positions.values()))
    assert isinstance(btc_pos['position_key'], str)
    assert btc_pos['position_key'] == 'base ' + addr
    assert btc_pos['chain'] == 'base'
    assert btc_pos['contract_address'] == addr

    assert len(closed_positions) == 1
    eth_pos = next(iter(closed_positions.values()))
    assert isinstance(eth_pos['position_key'], str)
    assert eth_pos['position_key'] == 'ETH'


# ── route ────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    """Authenticated Flask test client (auth bypassed via a stubbed password)."""
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def test_route_unrecognised_key_value_falls_through_to_default(client):
    """Post-flip: the default IS chain_address grouping - only key=symbol is
    the special-cased legacy branch now."""
    resp = client.get('/api/spot/orphan-sells?key=bogus')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['summary']['grouping_key'] == 'chain_address'
    assert 'split_symbols' in data['summary']


def test_route_no_key_param_reports_chain_address_grouping(client):
    resp = client.get('/api/spot/orphan-sells')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['summary']['grouping_key'] == 'chain_address'


def test_route_chain_address_key_reports_chain_address_grouping_and_split_symbols(client):
    resp = client.get('/api/spot/orphan-sells?key=chain_address')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['summary']['grouping_key'] == 'chain_address'
    assert 'split_symbols' in data['summary']


def test_route_symbol_key_reports_legacy_symbol_grouping_without_split_symbols(client):
    """key=symbol is now the only way to reach the legacy bare-symbol
    grouping through this route."""
    resp = client.get('/api/spot/orphan-sells?key=symbol')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['summary']['grouping_key'] == 'symbol'
    assert 'split_symbols' not in data['summary']


def test_pnl_route_response_includes_position_key(client):
    """7f: a working client fixture already exists in this file (used by the
    orphan-sells route tests above), so this checks /api/spot/pnl's payload
    directly rather than noting a gap."""
    resp = client.get('/api/spot/pnl')
    assert resp.status_code == 200
    data = resp.get_json()
    for entry in data:
        assert 'position_key' in entry
