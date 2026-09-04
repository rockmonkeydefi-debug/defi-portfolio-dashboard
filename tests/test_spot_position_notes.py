"""Tests for the per-position notes table (spot_position_notes) and its
read/write endpoints: GET /api/spot/position-notes, PUT /api/spot/position-notes,
and the _spot_position_notes_map(conn) helper. Also confirms /api/spot/pnl wires
a 'note' key onto every position row.

Route tests use the real get_connection() database via the Flask test client -
matching the established convention in test_spot_address_guard.py and
test_spot_orphan_sells.py (this schema's routes never take a mockable conn
argument, so there is no way to test them without touching the real DB) - with
explicit cleanup by a distinctive sentinel `chain` value so no test row is ever
mistaken for real data.

_spot_position_notes_map(conn) itself takes a plain conn argument, so its own
tests use a local in-memory sqlite3 harness, matching test_spot_orphan_sells.py's
own convention of one self-contained harness per test file.

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

from src.storage.portfolio_db import get_connection

_spot_position_notes_map = wp._spot_position_notes_map

TEST_CHAIN = 'zzztestchain'
MIXED_CASE_ADDR = '0xAbCdEf1234567890AbCdEf1234567890AbCdEf12'


def _cleanup(chains):
    conn = get_connection()
    conn.executemany("DELETE FROM spot_position_notes WHERE chain=?", [(c,) for c in chains])
    conn.commit()
    conn.close()


@pytest.fixture
def client(monkeypatch):
    """Authenticated Flask test client (auth bypassed via a stubbed password)."""
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


# ── PUT / GET routes ────────────────────────────────────────────────────────

def test_put_creates_row_and_get_returns_it(client):
    chain = TEST_CHAIN + '_a'
    try:
        resp = client.put('/api/spot/position-notes', json={
            'chain': chain, 'contract_address': '0xAAA', 'note': 'watching for a breakout',
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['chain'] == chain
        assert data['contract_address'] == '0xAAA'
        assert data['note'] == 'watching for a breakout'

        listed = client.get('/api/spot/position-notes').get_json()
        match = [r for r in listed if r['chain'] == chain]
        assert len(match) == 1
        assert match[0]['note'] == 'watching for a breakout'
    finally:
        _cleanup([chain])


def test_put_twice_same_position_updates_in_place_no_duplicate(client):
    chain = TEST_CHAIN + '_b'
    try:
        r1 = client.put('/api/spot/position-notes', json={
            'chain': chain, 'contract_address': '0xBBB', 'note': 'first note',
        })
        assert r1.status_code == 200
        r2 = client.put('/api/spot/position-notes', json={
            'chain': chain, 'contract_address': '0xBBB', 'note': 'second note',
        })
        assert r2.status_code == 200
        assert r2.get_json()['note'] == 'second note'

        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM spot_position_notes WHERE chain=? AND contract_address=?",
            (chain, '0xBBB')
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0]['note'] == 'second note'
    finally:
        _cleanup([chain])


def test_put_blank_chain_returns_400(client):
    resp = client.put('/api/spot/position-notes', json={
        'chain': '', 'contract_address': '0xCCC', 'note': 'x',
    })
    assert resp.status_code == 400


def test_put_blank_contract_address_returns_400(client):
    resp = client.put('/api/spot/position-notes', json={
        'chain': TEST_CHAIN + '_c', 'contract_address': '', 'note': 'x',
    })
    assert resp.status_code == 400


def test_put_note_over_500_chars_returns_400(client):
    chain = TEST_CHAIN + '_d'
    try:
        resp = client.put('/api/spot/position-notes', json={
            'chain': chain, 'contract_address': '0xDDD', 'note': 'x' * 501,
        })
        assert resp.status_code == 400
        # Confirm nothing was written on the rejected write.
        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM spot_position_notes WHERE chain=?", (chain,)
        ).fetchone()
        conn.close()
        assert row is None
    finally:
        _cleanup([chain])


def test_put_empty_note_returns_200_and_row_persists(client):
    chain = TEST_CHAIN + '_e'
    try:
        resp = client.put('/api/spot/position-notes', json={
            'chain': chain, 'contract_address': '0xEEE', 'note': '',
        })
        assert resp.status_code == 200
        assert resp.get_json()['note'] == ''

        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM spot_position_notes WHERE chain=? AND contract_address=?",
            (chain, '0xEEE')
        ).fetchone()
        conn.close()
        assert row is not None
        assert row['note'] == ''
    finally:
        _cleanup([chain])


def test_mixed_case_contract_address_stored_exactly_not_lowercased(client):
    """The Solana case-collision guard: this table must never re-lowercase a
    contract_address, or two distinct addresses differing only by case would
    collide onto the same note row."""
    chain = TEST_CHAIN + '_f'
    try:
        resp = client.put('/api/spot/position-notes', json={
            'chain': chain, 'contract_address': MIXED_CASE_ADDR, 'note': 'case guard',
        })
        assert resp.status_code == 200
        assert resp.get_json()['contract_address'] == MIXED_CASE_ADDR

        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM spot_position_notes WHERE chain=?", (chain,)
        ).fetchone()
        conn.close()
        assert row['contract_address'] == MIXED_CASE_ADDR  # character-for-character
    finally:
        _cleanup([chain])


# ── _spot_position_notes_map ────────────────────────────────────────────────

def _make_notes_db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE spot_position_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain TEXT NOT NULL,
            contract_address TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(chain, contract_address)
        )
    """)
    return conn


def test_notes_map_empty_when_table_empty():
    conn = _make_notes_db()
    assert _spot_position_notes_map(conn) == {}


def test_notes_map_keyed_on_chain_address_tuple():
    conn = _make_notes_db()
    conn.execute(
        "INSERT INTO spot_position_notes (chain, contract_address, note) VALUES (?, ?, ?)",
        ('base', '0xabc', 'a note')
    )
    conn.commit()
    result = _spot_position_notes_map(conn)
    assert result == {('base', '0xabc'): 'a note'}


# ── /api/spot/pnl wiring ─────────────────────────────────────────────────────

def test_pnl_route_every_position_row_has_note_key(client):
    resp = client.get('/api/spot/pnl')
    assert resp.status_code == 200
    data = resp.get_json()
    for entry in data:
        assert 'note' in entry
