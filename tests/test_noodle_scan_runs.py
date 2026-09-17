"""Schema-only tests for noodle_scan_runs (async noodle scan, Commit 3) -
see the Commit 3 task block for the column list and the design (variant
C1: background thread + one row per run).

Same style/technique as tests/test_noodle_state_schema.py: runs the real
init_db() against a temp-file SQLite (via a monkeypatched get_db_path())
rather than a hand-rolled schema mirror, so this also proves init_db() is
idempotent for the new CREATE TABLE IF NOT EXISTS (a new table, not a
migrations-list column - no ALTER TABLE involved here).
"""
import sqlite3

import src.storage.portfolio_db as _pdb

COLUMNS = (
    'id', 'trigger', 'status', 'started_ts', 'updated_ts', 'finished_ts',
    'total', 'done', 'errors', 'retired', 'error_msg',
)


def _open(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_noodle_scan_runs_table_exists_after_init_db(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(_pdb, 'get_db_path', lambda: path)

    _pdb.init_db()

    conn = _open(path)
    cols = {row['name'] for row in conn.execute("PRAGMA table_info(noodle_scan_runs)")}
    for col in COLUMNS:
        assert col in cols
    conn.close()


def test_init_db_twice_is_a_noop_for_noodle_scan_runs(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(_pdb, 'get_db_path', lambda: path)

    _pdb.init_db()
    _pdb.init_db()  # must not raise (CREATE TABLE IF NOT EXISTS is already idempotent)

    conn = _open(path)
    cols = {row['name'] for row in conn.execute("PRAGMA table_info(noodle_scan_runs)")}
    for col in COLUMNS:
        assert col in cols
    conn.close()
