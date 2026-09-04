"""Schema-only tests for spot_transactions.chain / contract_address.

No existing test file referenced spot_transactions before this. Runs the real
init_db() against a temp-file SQLite (via a monkeypatched get_db_path()) rather
than a hand-rolled schema mirror, so this also proves init_db() itself is
idempotent for this table.
"""
import sqlite3

import src.storage.portfolio_db as _pdb


def _open(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_spot_transactions_has_chain_and_contract_address_columns(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(_pdb, 'get_db_path', lambda: path)

    _pdb.init_db()

    conn = _open(path)
    cols = {row['name'] for row in conn.execute("PRAGMA table_info(spot_transactions)")}
    assert 'chain' in cols
    assert 'contract_address' in cols
    conn.close()


def test_spot_transactions_chain_and_contract_address_default_to_empty_string(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(_pdb, 'get_db_path', lambda: path)

    _pdb.init_db()

    conn = _open(path)
    conn.execute(
        "INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd) "
        "VALUES ('1/1/2024', 'BTC', 'buy', 1, 100, 100)"
    )
    conn.commit()
    row = conn.execute(
        "SELECT chain, contract_address FROM spot_transactions WHERE symbol='BTC'"
    ).fetchone()
    assert row['chain'] == ''
    assert row['contract_address'] == ''
    conn.close()


def test_init_db_twice_is_a_noop_for_spot_transactions(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(_pdb, 'get_db_path', lambda: path)

    _pdb.init_db()
    _pdb.init_db()  # must not raise (ADD COLUMN on an already-migrated table)

    conn = _open(path)
    cols = {row['name'] for row in conn.execute("PRAGMA table_info(spot_transactions)")}
    assert 'chain' in cols
    assert 'contract_address' in cols
    conn.close()
