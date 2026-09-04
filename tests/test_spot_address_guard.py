"""Tests for the write-time address guard and CSV chain/address support added
in Commit A: spot_symbol_has_addressed_rows(), spot_address_guard_message(),
and their wiring into POST/PUT/CSV-import for spot_transactions.

The in-memory sqlite3 harness (make_db/insert_tx) is a LOCAL copy of the same
shape used in tests/test_spot_orphan_sells.py, matching this suite's own
convention of one self-contained harness per test file rather than importing
across sibling test modules.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern, see
test_custom_tokens.py) so no thread starts.
"""
import io
import sqlite3
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

from src.storage.portfolio_db import get_connection

spot_symbol_has_addressed_rows = wp.spot_symbol_has_addressed_rows
spot_address_guard_message = wp.spot_address_guard_message

EVM_ADDR = "0xA1FBB38bF486b97108aA87E92008187CA06998f6"


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
    cur = conn.execute(
        """INSERT INTO spot_transactions
           (trade_date, symbol, side, units, price_usd, total_usd, platform, chain, contract_address)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (trade_date, symbol, side, units, price_usd, price_usd, platform, chain, contract_address)
    )
    conn.commit()
    return cur.lastrowid


# ── spot_symbol_has_addressed_rows() ────────────────────────────────────────

def test_returns_true_when_another_row_has_both_fields():
    conn = make_db()
    insert_tx(conn, '1/1/2024', 'BTC', 'buy', 1, 100, chain='base', contract_address=EVM_ADDR)
    assert spot_symbol_has_addressed_rows(conn, 'BTC') is True


def test_returns_false_when_no_row_is_addressed():
    conn = make_db()
    insert_tx(conn, '1/1/2024', 'BTC', 'buy', 1, 100)  # chain='', contract_address=''
    assert spot_symbol_has_addressed_rows(conn, 'BTC') is False


def test_excludes_given_row_id():
    """A row must not block its own update - PUT passes exclude_id=tx_id."""
    conn = make_db()
    row_id = insert_tx(conn, '1/1/2024', 'BTC', 'buy', 1, 100, chain='base', contract_address=EVM_ADDR)
    assert spot_symbol_has_addressed_rows(conn, 'BTC') is True
    assert spot_symbol_has_addressed_rows(conn, 'BTC', exclude_id=row_id) is False


def test_case_insensitive_on_symbol():
    conn = make_db()
    insert_tx(conn, '1/1/2024', 'BTC', 'buy', 1, 100, chain='base', contract_address=EVM_ADDR)
    assert spot_symbol_has_addressed_rows(conn, 'btc') is True
    assert spot_symbol_has_addressed_rows(conn, 'Btc') is True


def test_one_sided_chain_or_address_does_not_count_as_addressed():
    conn = make_db()
    insert_tx(conn, '1/1/2024', 'BTC', 'buy', 1, 100, chain='base', contract_address='')
    insert_tx(conn, '1/2/2024', 'BTC', 'buy', 1, 100, chain='', contract_address=EVM_ADDR)
    assert spot_symbol_has_addressed_rows(conn, 'BTC') is False


def test_symbol_with_no_addressed_rows_anywhere_permits_first_blank_entry():
    """The guard must not block first-ever entry of a token: a brand new
    symbol with zero rows at all has nothing to be disjoint from."""
    conn = make_db()
    assert spot_symbol_has_addressed_rows(conn, 'NEWTOKEN') is False


def test_guard_message_names_symbol():
    msg = spot_address_guard_message('BTC')
    assert 'BTC' in msg
    assert 'chain' in msg and 'contract address' in msg


# ── CSV import route ─────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    """Authenticated Flask test client (auth bypassed via a stubbed password)."""
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _cleanup(symbols):
    conn = get_connection()
    conn.executemany("DELETE FROM spot_transactions WHERE symbol=?", [(s,) for s in symbols])
    conn.commit()
    conn.close()


def test_csv_import_inserts_chain_and_contract_address_when_present(client):
    symbol = 'ZZZCSVGUARDA'
    csv_content = (
        "date,symbol,side,units,price_usd,chain,contract_address\n"
        f"1/1/2024,{symbol},buy,1,100,base,{EVM_ADDR}\n"
    )
    try:
        resp = client.post('/api/spot/import-csv',
                            data={'file': (io.BytesIO(csv_content.encode()), 'test.csv')},
                            content_type='multipart/form-data')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['imported'] == 1
        assert data['skipped'] == 0

        conn = get_connection()
        row = conn.execute(
            "SELECT chain, contract_address FROM spot_transactions WHERE symbol=?", (symbol,)
        ).fetchone()
        conn.close()
        assert row['chain'] == 'base'
        assert row['contract_address'] == EVM_ADDR.lower()  # EVM lowercased on write
    finally:
        _cleanup([symbol])


def test_csv_import_without_chain_address_columns_still_imports(client):
    symbol = 'ZZZCSVGUARDB'
    csv_content = f"date,symbol,side,units,price_usd\n1/1/2024,{symbol},buy,1,100\n"
    try:
        resp = client.post('/api/spot/import-csv',
                            data={'file': (io.BytesIO(csv_content.encode()), 'test.csv')},
                            content_type='multipart/form-data')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['imported'] == 1
        assert data['skipped'] == 0

        conn = get_connection()
        row = conn.execute(
            "SELECT chain, contract_address FROM spot_transactions WHERE symbol=?", (symbol,)
        ).fetchone()
        conn.close()
        assert row['chain'] == ''
        assert row['contract_address'] == ''
    finally:
        _cleanup([symbol])


def test_csv_import_hand_typed_mixed_case_chain_accepted(client):
    """5c: CSV lowercases chain before validation - POST/PUT never need this
    since their chain comes from a dropdown."""
    symbol = 'ZZZCSVGUARDC'
    csv_content = (
        "date,symbol,side,units,price_usd,chain,contract_address\n"
        f"1/1/2024,{symbol},buy,1,100,Base,{EVM_ADDR}\n"
    )
    try:
        resp = client.post('/api/spot/import-csv',
                            data={'file': (io.BytesIO(csv_content.encode()), 'test.csv')},
                            content_type='multipart/form-data')
        data = resp.get_json()
        assert data['imported'] == 1, data
        conn = get_connection()
        row = conn.execute(
            "SELECT chain FROM spot_transactions WHERE symbol=?", (symbol,)
        ).fetchone()
        conn.close()
        assert row['chain'] == 'base'
    finally:
        _cleanup([symbol])


def test_csv_batch_rejects_later_row_missing_address_for_symbol_addressed_earlier_in_same_batch(client):
    """5e / 6g: rows inserted earlier in the SAME loop are visible to the
    guard's SELECT before conn.commit(), because they share one connection -
    this proves that uncommitted-read behaviour holds."""
    symbol = 'ZZZCSVGUARDD'
    csv_content = (
        "date,symbol,side,units,price_usd,chain,contract_address\n"
        f"1/1/2024,{symbol},buy,1,100,base,{EVM_ADDR}\n"
        f"1/2/2024,{symbol},buy,1,100,,\n"
    )
    try:
        resp = client.post('/api/spot/import-csv',
                            data={'file': (io.BytesIO(csv_content.encode()), 'test.csv')},
                            content_type='multipart/form-data')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['imported'] == 1
        assert data['skipped'] == 1
        assert any('chain and contract address' in e for e in data['errors']), data['errors']

        conn = get_connection()
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM spot_transactions WHERE symbol=?", (symbol,)
        ).fetchone()['c']
        conn.close()
        assert count == 1  # only the first (addressed) row was inserted
    finally:
        _cleanup([symbol])


def test_csv_import_reports_invalid_chain_address_per_row_without_aborting(client):
    symbol = 'ZZZCSVGUARDE'
    csv_content = (
        "date,symbol,side,units,price_usd,chain,contract_address\n"
        f"1/1/2024,{symbol},buy,1,100,base,0xtooShort\n"
        f"1/2/2024,{symbol},sell,1,100,,\n"
    )
    try:
        resp = client.post('/api/spot/import-csv',
                            data={'file': (io.BytesIO(csv_content.encode()), 'test.csv')},
                            content_type='multipart/form-data')
        data = resp.get_json()
        # Row 1: invalid address format, skipped. Row 2: no addressed row
        # exists yet (row 1 never inserted), so it imports cleanly.
        assert data['skipped'] == 1
        assert data['imported'] == 1
        assert any('Invalid contract_address' in e for e in data['errors']), data['errors']
    finally:
        _cleanup([symbol])
