"""Tests for the spot notes journal back end (Oct 3 rulings): the
spot_note_updates and note_revisions tables, the dated-update routes
(GET / POST /api/spot/note-updates, PUT / DELETE /api/spot/note-updates/<id>),
the 2,000-character Summary limit on PUT /api/spot/position-notes, and the
earlier versions kept when a Summary, an update, or a trade's notes /
deviation note change.

Every test runs against a fresh temporary database (portfolio_db.get_db_path
monkeypatched, then init_db), the pattern test_trades_unified.py uses. Test
addresses are built in code and are not real.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern) so no
thread starts.
"""
import threading
from datetime import datetime, timedelta

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

from src.storage import portfolio_db

EVM = '0x' + 'ab' * 20
SOL = 'FaKeMiNt' + 'AbCdEfGhJk' * 3          # base58-style, mixed case
TRADE_ID = 'tp1'


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


def add(client, body, chain='base', addr=EVM):
    return client.post('/api/spot/note-updates', json={'chain': chain, 'contract_address': addr, 'body': body})


def revisions(db, kind=None):
    sql = "SELECT kind, ref, old_text, action, revised_at FROM note_revisions"
    args = ()
    if kind:
        sql += " WHERE kind = ?"
        args = (kind,)
    return [dict(r) for r in db.execute(sql + " ORDER BY id", args)]


def utc(s):
    d = datetime.fromisoformat(s)
    assert d.utcoffset() == timedelta(0)
    return d


# ── schema ──────────────────────────────────────────────────────────────────

def test_tables_and_indexes_exist_and_init_is_idempotent(db):
    portfolio_db.init_db()                                   # second run: no error, no change
    cols = lambda t: [r["name"] for r in db.execute(f"PRAGMA table_info({t})")]
    assert cols("spot_note_updates") == ["id", "chain", "contract_address", "body",
                                         "created_at", "edited_at", "deleted_at"]
    assert cols("note_revisions") == ["id", "kind", "ref", "old_text", "action", "revised_at"]
    idx = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"idx_spot_note_updates_position", "idx_note_revisions_ref"} <= idx


def test_revision_kind_and_action_are_checked(db):
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO note_revisions (kind, ref, old_text, action, revised_at) "
                   "VALUES ('other', 'r', 't', 'edit', 'now')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO note_revisions (kind, ref, old_text, action, revised_at) "
                   "VALUES ('spot_update', 'r', 't', 'other', 'now')")


def test_revision_helper_ignores_empty_text(db):
    wp._note_revision(db, 'spot_update', 1, '', 'edit')
    wp._note_revision(db, 'spot_update', 1, None, 'edit')
    db.commit()
    assert revisions(db) == []


# ── POST ────────────────────────────────────────────────────────────────────

def test_add_returns_the_stored_update(client, db):
    r = client.post('/api/spot/note-updates',
                    json={'chain': ' solana ', 'contract_address': ' ' + SOL + ' ', 'body': 'Weekly **bullish**.\n- hold'})
    assert r.status_code == 201
    u = r.get_json()
    assert u['chain'] == 'solana' and u['contract_address'] == SOL        # trimmed, case kept
    assert u['position_key'] == 'solana ' + SOL
    assert u['body'] == 'Weekly **bullish**.\n- hold' and u['edited_at'] is None
    utc(u['created_at'])
    stored = dict(db.execute("SELECT * FROM spot_note_updates WHERE id = ?", (u['id'],)).fetchone())
    assert stored['deleted_at'] is None and stored['contract_address'] == SOL


@pytest.mark.parametrize("payload, message", [
    ({'contract_address': EVM, 'body': 'x'}, 'chain is required'),
    ({'chain': '  ', 'contract_address': EVM, 'body': 'x'}, 'chain is required'),
    ({'chain': 'base', 'body': 'x'}, 'contract_address is required'),
    ({'chain': 'base', 'contract_address': '', 'body': 'x'}, 'contract_address is required'),
    ({'chain': 'base', 'contract_address': EVM}, 'body must be a non-empty string'),
    ({'chain': 'base', 'contract_address': EVM, 'body': '  \n '}, 'body must be a non-empty string'),
    ({'chain': 'base', 'contract_address': EVM, 'body': 5}, 'body must be a non-empty string'),
    ({'chain': 'base', 'contract_address': EVM, 'body': 'x' * 2001}, 'body must be 2000 characters or fewer'),
])
def test_add_rejects_bad_input_and_writes_nothing(client, db, payload, message):
    r = client.post('/api/spot/note-updates', json=payload)
    assert r.status_code == 400 and r.get_json() == {'error': message}
    assert db.execute("SELECT COUNT(*) FROM spot_note_updates").fetchone()[0] == 0


def test_add_rejects_a_non_json_body(client, db):
    r = client.post('/api/spot/note-updates', data='not json', content_type='text/plain')
    assert r.status_code == 400 and r.get_json() == {'error': 'chain is required'}


def test_add_accepts_exactly_2000_characters(client):
    r = add(client, 'x' * 2000)
    assert r.status_code == 201 and len(r.get_json()['body']) == 2000


# ── GET ─────────────────────────────────────────────────────────────────────

def test_list_newest_first_filtered_and_without_deleted(client, db):
    a = add(client, 'oldest').get_json()['id']
    b = add(client, 'middle').get_json()['id']
    c = add(client, 'sol one', chain='solana', addr=SOL).get_json()['id']
    for uid, at in ((a, '2026-09-01T00:00:00+00:00'), (b, '2026-09-02T00:00:00+00:00'),
                    (c, '2026-09-03T00:00:00+00:00')):
        db.execute("UPDATE spot_note_updates SET created_at = ? WHERE id = ?", (at, uid))
    db.commit()
    body = client.get('/api/spot/note-updates').get_json()
    assert [u['id'] for u in body] == [c, b, a]
    one = client.get('/api/spot/note-updates', query_string={'chain': 'base', 'contract_address': EVM}).get_json()
    assert [u['id'] for u in one] == [b, a] and all(u['position_key'] == 'base ' + EVM for u in one)
    assert client.delete(f'/api/spot/note-updates/{b}').status_code == 200
    assert [u['id'] for u in client.get('/api/spot/note-updates').get_json()] == [c, a]


def test_list_same_time_ties_newest_id_first(client, db):
    a = add(client, 'first').get_json()['id']
    b = add(client, 'second').get_json()['id']
    db.execute("UPDATE spot_note_updates SET created_at = '2026-09-01T00:00:00+00:00'")
    db.commit()
    assert [u['id'] for u in client.get('/api/spot/note-updates').get_json()] == [b, a]


def test_list_filter_needs_both_chain_and_address(client):
    r = client.get('/api/spot/note-updates', query_string={'chain': 'base'})
    assert r.status_code == 400 and r.get_json() == {'error': 'chain and contract_address go together'}
    r = client.get('/api/spot/note-updates', query_string={'contract_address': EVM})
    assert r.status_code == 400


def test_list_empty(client):
    r = client.get('/api/spot/note-updates')
    assert r.status_code == 200 and r.get_json() == []


# ── PUT ─────────────────────────────────────────────────────────────────────

def test_edit_keeps_the_earlier_text_and_the_original_date(client, db):
    u = add(client, 'first take').get_json()
    r = client.put(f"/api/spot/note-updates/{u['id']}", json={'body': 'second take'})
    assert r.status_code == 200
    e = r.get_json()
    assert e['body'] == 'second take' and e['created_at'] == u['created_at']
    assert utc(e['edited_at']) >= utc(u['created_at'])
    revs = revisions(db)
    assert len(revs) == 1
    assert (revs[0]['kind'], revs[0]['ref'], revs[0]['old_text'], revs[0]['action']) == \
        ('spot_update', str(u['id']), 'first take', 'edit')
    utc(revs[0]['revised_at'])


def test_edit_with_the_same_text_changes_nothing(client, db):
    u = add(client, 'same').get_json()
    r = client.put(f"/api/spot/note-updates/{u['id']}", json={'body': 'same'})
    assert r.status_code == 200 and r.get_json()['edited_at'] is None
    assert revisions(db) == []


def test_edit_rejects_bad_text_and_unknown_or_deleted_ids(client, db):
    u = add(client, 'keep').get_json()
    assert client.put(f"/api/spot/note-updates/{u['id']}", json={'body': ' '}).status_code == 400
    assert client.put(f"/api/spot/note-updates/{u['id']}", json={'body': 'x' * 2001}).status_code == 400
    assert client.put(f"/api/spot/note-updates/{u['id']}", json={}).status_code == 400
    r = client.put('/api/spot/note-updates/999', json={'body': 'x'})
    assert r.status_code == 404 and r.get_json() == {'error': 'update not found'}
    client.delete(f"/api/spot/note-updates/{u['id']}")
    assert client.put(f"/api/spot/note-updates/{u['id']}", json={'body': 'x'}).status_code == 404
    assert db.execute("SELECT body FROM spot_note_updates WHERE id = ?", (u['id'],)).fetchone()[0] == 'keep'


# ── DELETE ──────────────────────────────────────────────────────────────────

def test_delete_hides_the_update_and_keeps_its_text(client, db):
    u = add(client, 'gone soon').get_json()
    r = client.delete(f"/api/spot/note-updates/{u['id']}")
    assert r.status_code == 200
    out = r.get_json()
    assert out['id'] == u['id']
    utc(out['deleted_at'])
    row = db.execute("SELECT * FROM spot_note_updates WHERE id = ?", (u['id'],)).fetchone()
    assert row is not None and row['deleted_at'] == out['deleted_at'] and row['body'] == 'gone soon'
    revs = revisions(db)
    assert [(x['kind'], x['ref'], x['old_text'], x['action']) for x in revs] == \
        [('spot_update', str(u['id']), 'gone soon', 'delete')]
    r = client.delete(f"/api/spot/note-updates/{u['id']}")
    assert r.status_code == 404 and r.get_json() == {'error': 'update not found'}
    assert len(revisions(db)) == 1


def test_delete_unknown_id(client):
    assert client.delete('/api/spot/note-updates/12345').status_code == 404


# ── Summary (PUT /api/spot/position-notes) ──────────────────────────────────

def summary(client, note, chain='base', addr=EVM):
    return client.put('/api/spot/position-notes', json={'chain': chain, 'contract_address': addr, 'note': note})


def test_summary_limit_is_2000(client):
    assert summary(client, 'x' * 2000).status_code == 200
    r = summary(client, 'x' * 2001)
    assert r.status_code == 400 and r.get_json() == {'error': 'note must be 2000 characters or fewer'}


def test_summary_changes_keep_the_earlier_text(client, db):
    ref = 'base ' + EVM
    assert summary(client, 'Fusion wallets').status_code == 200        # first text: nothing earlier
    assert summary(client, 'Fusion wallets').status_code == 200        # same text: nothing kept
    assert revisions(db) == []
    summary(client, 'Fusion wallets. Long-term.')
    summary(client, '')                                                # cleared: the cleared text is kept
    summary(client, '')                                                # empty again: nothing to keep
    revs = revisions(db, 'spot_summary')
    assert [(x['ref'], x['old_text'], x['action']) for x in revs] == [
        (ref, 'Fusion wallets', 'edit'), (ref, 'Fusion wallets. Long-term.', 'edit')]


def test_summary_revision_ref_keeps_solana_case(client, db):
    summary(client, 'one', chain='solana', addr=SOL)
    summary(client, 'two', chain='solana', addr=SOL)
    assert [x['ref'] for x in revisions(db)] == ['solana ' + SOL]


# ── trade notes (PUT /api/trading/trades/<id>/annotation) ────────────────────

@pytest.fixture
def trade_client(client, db, monkeypatch):
    def fake_build(conn):
        ann = {r["trade_id"]: dict(r) for r in conn.execute("SELECT * FROM trade_annotations")}
        return [{"trade_id": TRADE_ID, "source": "hl", "market": "perp"}], ann
    monkeypatch.setattr(wp, "_trades_build", fake_build)
    return client


def annotate(client, body):
    r = client.put(f'/api/trading/trades/{TRADE_ID}/annotation', json=body)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()['annotation']


def test_trade_note_changes_keep_the_earlier_text(trade_client, db):
    annotate(trade_client, {'notes': 'first'})                         # new row: nothing earlier
    annotate(trade_client, {'notes': 'first'})                         # same text
    assert revisions(db) == []
    annotate(trade_client, {'notes': 'second'})
    annotate(trade_client, {'stop_px': '9.5'})                         # stop only: no note change
    annotate(trade_client, {'followed_rules': True})
    annotate(trade_client, {'notes': None})                            # cleared: kept
    annotate(trade_client, {'notes': None})
    revs = revisions(db, 'trade_notes')
    assert [(x['ref'], x['old_text'], x['action']) for x in revs] == [
        (TRADE_ID, 'first', 'edit'), (TRADE_ID, 'second', 'edit')]
    stored = db.execute("SELECT notes, stop_px, followed_rules FROM trade_annotations WHERE trade_id = ?",
                        (TRADE_ID,)).fetchone()
    assert (stored['notes'], stored['stop_px'], stored['followed_rules']) == (None, '9.5', 1)


def test_trade_deviation_note_changes_keep_the_earlier_text(trade_client, db):
    annotate(trade_client, {'deviation_note': 'moved stop'})
    annotate(trade_client, {'deviation_note': 'moved stop down', 'notes': 'n1'})
    revs = revisions(db)
    assert [(x['kind'], x['old_text']) for x in revs] == [('trade_deviation_note', 'moved stop')]
