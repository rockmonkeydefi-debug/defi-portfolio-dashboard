"""Tests for the chain + contract_address write-path capture added in step 2:
normalize_spot_chain_address() and its wiring into the POST/PUT spot
transaction routes. Schema-only column presence is covered by
test_spot_transactions_schema.py; this file covers validation, normalization,
and the routes.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern, see
test_custom_tokens.py) so no thread starts.
"""
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

from src.storage.portfolio_db import get_connection

normalize_spot_chain_address = wp.normalize_spot_chain_address

EVM_ADDR = "0xA1FBB38bF486b97108aA87E92008187CA06998f6"
# Wrapped SOL mint address - a real, well-known base58 address.
SOLANA_ADDR_MIXED_CASE = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"


# ── normalize_spot_chain_address() ──────────────────────────────────────────

def test_both_absent_accepted_as_empty_strings():
    assert normalize_spot_chain_address(None, None) == ('', '', None)


def test_both_empty_string_accepted():
    assert normalize_spot_chain_address('', '') == ('', '', None)


def test_valid_evm_accepted_and_lowercased():
    chain, address, err = normalize_spot_chain_address('base', EVM_ADDR)
    assert err is None
    assert chain == 'base'
    assert address == EVM_ADDR.lower()


def test_solana_mixed_case_address_preserved():
    chain, address, err = normalize_spot_chain_address('solana', SOLANA_ADDR_MIXED_CASE)
    assert err is None
    assert chain == 'solana'
    assert address == SOLANA_ADDR_MIXED_CASE  # case preserved exactly, not lowercased


def test_chain_without_address_rejected():
    chain, address, err = normalize_spot_chain_address('base', '')
    assert (chain, address) == (None, None)
    assert err == "chain and contract_address must be provided together"


def test_address_without_chain_rejected():
    chain, address, err = normalize_spot_chain_address('', EVM_ADDR)
    assert (chain, address) == (None, None)
    assert err == "chain and contract_address must be provided together"


def test_unknown_chain_rejected():
    chain, address, err = normalize_spot_chain_address('dogechain', EVM_ADDR)
    assert (chain, address) == (None, None)
    assert "Unknown chain 'dogechain'" in err


def test_evm_address_wrong_length_rejected():
    too_short = EVM_ADDR[:-1]  # 39 hex chars after 0x, not 40
    chain, address, err = normalize_spot_chain_address('base', too_short)
    assert (chain, address) == (None, None)
    assert err is not None


def test_evm_address_missing_0x_prefix_rejected():
    no_prefix = EVM_ADDR[2:]
    chain, address, err = normalize_spot_chain_address('base', no_prefix)
    assert (chain, address) == (None, None)
    assert err is not None


def test_base58_address_with_excluded_character_rejected():
    # base58 excludes 0, O, I, l - swap the leading '7' for a '0'.
    bad = '0' + SOLANA_ADDR_MIXED_CASE[1:]
    chain, address, err = normalize_spot_chain_address('solana', bad)
    assert (chain, address) == (None, None)
    assert err is not None


def test_robinhood_chain_with_valid_evm_address_accepted():
    # dexscreener_slug is None for robinhood - must not block capture, only
    # pricing (a later step's concern).
    chain, address, err = normalize_spot_chain_address('robinhood', EVM_ADDR)
    assert err is None
    assert chain == 'robinhood'
    assert address == EVM_ADDR.lower()


def test_sonic_chain_with_valid_evm_address_accepted_and_lowercased():
    # Sonic is EVM (chain ID 146) - same lowercasing as every other EVM chain.
    chain, address, err = normalize_spot_chain_address('sonic', EVM_ADDR)
    assert err is None
    assert chain == 'sonic'
    assert address == EVM_ADDR.lower()


# ── routes ───────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    """Authenticated Flask test client (auth bypassed via a stubbed password)."""
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def test_put_can_set_chain_and_address_on_a_row_with_empty_strings(client):
    created = client.post('/api/spot/transactions', json={
        'trade_date': '1/1/2024', 'symbol': 'ZZZTESTCOIN', 'side': 'buy',
        'units': 1, 'price_usd': 100,
    })
    assert created.status_code == 200
    tx_id = created.get_json()['id']
    try:
        conn = get_connection()
        row = conn.execute(
            "SELECT chain, contract_address FROM spot_transactions WHERE id=?", (tx_id,)
        ).fetchone()
        conn.close()
        assert row['chain'] == ''
        assert row['contract_address'] == ''

        updated = client.put(f'/api/spot/transactions/{tx_id}', json={
            'trade_date': '1/1/2024', 'symbol': 'ZZZTESTCOIN', 'side': 'buy',
            'units': 1, 'price_usd': 100, 'chain': 'base', 'contract_address': EVM_ADDR,
        })
        assert updated.status_code == 200

        conn = get_connection()
        row = conn.execute(
            "SELECT chain, contract_address FROM spot_transactions WHERE id=?", (tx_id,)
        ).fetchone()
        conn.close()
        assert row['chain'] == 'base'
        assert row['contract_address'] == EVM_ADDR.lower()
    finally:
        conn = get_connection()
        conn.execute("DELETE FROM spot_transactions WHERE id=?", (tx_id,))
        conn.commit()
        conn.close()


def test_post_rejects_chain_without_address(client):
    resp = client.post('/api/spot/transactions', json={
        'trade_date': '1/1/2024', 'symbol': 'ZZZTESTCOIN', 'side': 'buy',
        'units': 1, 'price_usd': 100, 'chain': 'base',
    })
    assert resp.status_code == 400
    assert 'error' in resp.get_json()
