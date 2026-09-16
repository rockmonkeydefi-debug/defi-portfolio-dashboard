"""Schema-only tests for noodle_state's Trends-restyle Commit 2 columns
(volume_24h, alignment_state, alignment_prev_state, alignment_changed_ts,
alignment_changed_unbounded) - see HANDOFF_trends_restyle.md.

Same style/technique as tests/test_spot_transactions_schema.py: runs the
real init_db() against a temp-file SQLite (via a monkeypatched
get_db_path()) rather than a hand-rolled schema mirror, so this also
proves init_db() is idempotent for noodle_state's migration entries -
the same (table, col, col_type) list cascade_state's own mss_detail
column was added through.
"""
import sqlite3

import src.storage.portfolio_db as _pdb

NEW_COLUMNS = (
    'volume_24h', 'alignment_state', 'alignment_prev_state',
    'alignment_changed_ts', 'alignment_changed_unbounded',
)


def _open(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_noodle_state_has_the_five_new_columns(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(_pdb, 'get_db_path', lambda: path)

    _pdb.init_db()

    conn = _open(path)
    cols = {row['name'] for row in conn.execute("PRAGMA table_info(noodle_state)")}
    for col in NEW_COLUMNS:
        assert col in cols
    conn.close()


def test_noodle_state_new_columns_default_to_null(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(_pdb, 'get_db_path', lambda: path)

    _pdb.init_db()

    conn = _open(path)
    conn.execute(
        "INSERT INTO noodle_state (symbol, timeframe) VALUES ('BTC', '1d')")
    conn.commit()
    row = conn.execute(
        "SELECT volume_24h, alignment_state, alignment_prev_state, "
        "alignment_changed_ts, alignment_changed_unbounded "
        "FROM noodle_state WHERE symbol='BTC'"
    ).fetchone()
    for col in NEW_COLUMNS:
        assert row[col] is None
    conn.close()


def test_init_db_twice_is_a_noop_for_noodle_state(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(_pdb, 'get_db_path', lambda: path)

    _pdb.init_db()
    _pdb.init_db()  # must not raise (ADD COLUMN on an already-migrated table)

    conn = _open(path)
    cols = {row['name'] for row in conn.execute("PRAGMA table_info(noodle_state)")}
    for col in NEW_COLUMNS:
        assert col in cols
    conn.close()
