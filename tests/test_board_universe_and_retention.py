"""Pipeline Board = the full scanned universe (manual + scheduled), NOT filtered
by watchlist membership. Stale rows are retired by AGE, not by watchlist coupling.

This supersedes the PR #63 assertions (watchlist filter + orphan purge), which are
now inverted by the design ruling. Still valid from PR #63 and re-covered here:
the watchlist remove / Remove All handlers cascade-delete cascade_state while
leaving the append-only cascade_transitions log intact.

Temp-file SQLite mirrors of the post-migration tables — no network.
"""
import sqlite3
import threading
from datetime import datetime, timedelta

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as _pdb


def _schema(c):
    c.executescript("""
        CREATE TABLE scanner_watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT UNIQUE,
            exchange TEXT, asset_type TEXT, htf_timeframe TEXT, ltf_timeframe TEXT,
            notes TEXT, contract_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE scanner_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, status TEXT,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE cascade_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, pair TEXT,
            stage INTEGER DEFAULT 0, mss_detail TEXT, updated_at TEXT,
            UNIQUE(symbol, pair));
        CREATE TABLE cascade_transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, pair TEXT,
            from_stage INTEGER, to_stage INTEGER, reason TEXT, created_at TEXT);
    """)


def _open(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / 'board.db')
    c = _open(path)
    _schema(c)
    c.commit()
    c.close()
    monkeypatch.setattr(_pdb, 'get_connection', lambda: _open(path))
    return path


def _iso_days_ago(n):
    return (datetime.utcnow() - timedelta(days=n)).isoformat() + 'Z'


def _add_state(c, symbol, pair='W_D', stage=2, updated_at=None):
    c.execute("INSERT INTO cascade_state (symbol, pair, stage, updated_at) VALUES (?,?,?,?)",
              (symbol, pair, stage, updated_at if updated_at is not None else _iso_days_ago(0)))


# ── _cascade_summary shows the FULL universe (inverts the PR #63 filter) ──────

def test_summary_includes_non_watchlist_symbols(db):
    c = _open(db)
    c.execute("INSERT INTO scanner_watchlist (symbol) VALUES ('BTCUSDT')")
    _add_state(c, 'BTCUSDT', 'W_D', 2)     # on the watchlist
    _add_state(c, 'ETHUSDT', 'W_D', 3)     # scheduled-scan only — NOT on watchlist
    c.commit()
    summary = wp._cascade_summary(c)
    c.close()

    # Both symbols appear on the board and in the per-pair counts/tickers.
    assert {b['symbol'] for b in summary['board']} == {'BTCUSDT', 'ETHUSDT'}
    wd = summary['pairs']['W_D']
    assert wd['tickers']['2'] == ['BTCUSDT']
    assert wd['tickers']['3'] == ['ETHUSDT']
    assert wd['counts']['2'] == 1 and wd['counts']['3'] == 1


# ── watchlist remove / Remove All still cascade to cascade_state (PR #63) ─────

def test_remove_handler_deletes_cascade_state_keeps_transitions(db):
    c = _open(db)
    c.execute("INSERT INTO scanner_watchlist (id, symbol) VALUES (1, 'BTCUSDT')")
    _add_state(c, 'BTCUSDT', 'W_D', 2)
    c.execute("INSERT INTO cascade_transitions (symbol, pair, from_stage, to_stage, reason) "
              "VALUES ('BTCUSDT','W_D',1,2,'nested')")
    c.commit()
    c.close()

    with wp.app.test_request_context():
        assert wp.api_trading_scanner_watchlist_delete(1).get_json()['success'] is True

    c = _open(db)
    assert c.execute("SELECT COUNT(*) FROM cascade_state WHERE symbol='BTCUSDT'").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM cascade_transitions WHERE symbol='BTCUSDT'").fetchone()[0] == 1
    c.close()


def test_clear_handler_purges_cascade_state_keeps_transitions(db):
    c = _open(db)
    c.execute("INSERT INTO scanner_watchlist (symbol) VALUES ('BTCUSDT')")
    _add_state(c, 'BTCUSDT', 'W_D', 2)
    c.execute("INSERT INTO cascade_transitions (symbol, pair, from_stage, to_stage, reason) "
              "VALUES ('BTCUSDT','W_D',1,2,'nested')")
    c.commit()
    c.close()

    with wp.app.test_request_context():
        wp.api_trading_scanner_watchlist_clear()

    c = _open(db)
    assert c.execute("SELECT COUNT(*) FROM cascade_state").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM cascade_transitions").fetchone()[0] == 1
    c.close()


# ── age-based retirement (_retire_stale_cascade_rows) ─────────────────────────

def test_retire_deletes_only_rows_older_than_threshold(db):
    c = _open(db)
    _add_state(c, 'FRESHUSDT', 'W_D', 2, updated_at=_iso_days_ago(1))    # 1 day → keep
    _add_state(c, 'STALEUSDT', 'W_D', 1, updated_at=_iso_days_ago(10))   # 10 days → retire
    c.execute("INSERT INTO cascade_transitions (symbol, pair, from_stage, to_stage, reason) "
              "VALUES ('STALEUSDT','W_D',0,1,'rooted')")
    c.commit()

    n = wp._retire_stale_cascade_rows(c, retention_days=7)
    c.commit()
    assert n == 1
    assert {r['symbol'] for r in c.execute("SELECT symbol FROM cascade_state")} == {'FRESHUSDT'}
    # transitions of the retired symbol are preserved (append-only history)
    assert c.execute("SELECT COUNT(*) FROM cascade_transitions WHERE symbol='STALEUSDT'").fetchone()[0] == 1
    c.close()


def test_retire_respects_configured_retention(db, monkeypatch):
    c = _open(db)
    _add_state(c, 'STALEUSDT', 'W_D', 1, updated_at=_iso_days_ago(10))
    c.commit()
    # 30-day retention via the setting → the 10-day-old row survives.
    monkeypatch.setattr(wp, '_scanner_settings', lambda *a, **k: {'board_retention_days': 30})
    assert wp._retire_stale_cascade_rows(c) == 0
    assert c.execute("SELECT COUNT(*) FROM cascade_state").fetchone()[0] == 1
    # 7-day retention → it is retired.
    monkeypatch.setattr(wp, '_scanner_settings', lambda *a, **k: {'board_retention_days': 7})
    assert wp._retire_stale_cascade_rows(c) == 1
    c.close()


def test_retire_keeps_rescanned_rows_alive_across_threshold(db):
    # A row older than the threshold that is "rescanned" (updated_at refreshed to
    # now, as every scan does) survives — retirement keys off last-scan time.
    c = _open(db)
    _add_state(c, 'REVIVEUSDT', 'W_D', 2, updated_at=_iso_days_ago(10))
    c.commit()
    # simulate a scan touching the row
    c.execute("UPDATE cascade_state SET updated_at=? WHERE symbol='REVIVEUSDT'",
              (_iso_days_ago(0),))
    c.commit()
    assert wp._retire_stale_cascade_rows(c, retention_days=7) == 0
    assert c.execute("SELECT COUNT(*) FROM cascade_state").fetchone()[0] == 1
    c.close()


def test_retire_noop_on_fresh_db(db):
    c = _open(db)
    _add_state(c, 'BTCUSDT', 'W_D', 2, updated_at=_iso_days_ago(0))
    c.commit()
    assert wp._retire_stale_cascade_rows(c, retention_days=7) == 0
    c.close()


# ── board-symbol removal endpoint ─────────────────────────────────────────────

def test_board_symbol_delete_removes_state_and_watchlist_keeps_transitions(db):
    c = _open(db)
    c.execute("INSERT INTO scanner_watchlist (symbol) VALUES ('ETHUSDT')")
    _add_state(c, 'ETHUSDT', 'W_D', 2)
    _add_state(c, 'ETHUSDT', 'W_H4', 3)
    _add_state(c, 'ETHUSDT', 'D_H4', 1)
    c.execute("INSERT INTO cascade_transitions (symbol, pair, from_stage, to_stage, reason) "
              "VALUES ('ETHUSDT','W_D',1,2,'nested')")
    c.commit()
    c.close()

    with wp.app.test_request_context(
            '/api/trading/scanner/board-symbol', method='DELETE', json={'symbol': 'ETHUSDT'}):
        payload = wp.api_trading_scanner_board_symbol_delete().get_json()
    assert payload['removed'] == 'ETHUSDT'
    assert payload['rows'] == 3
    assert 'note' in payload

    c = _open(db)
    assert c.execute("SELECT COUNT(*) FROM cascade_state WHERE symbol='ETHUSDT'").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM scanner_watchlist WHERE symbol='ETHUSDT'").fetchone()[0] == 0
    # append-only history untouched
    assert c.execute("SELECT COUNT(*) FROM cascade_transitions WHERE symbol='ETHUSDT'").fetchone()[0] == 1
    c.close()


def test_board_symbol_delete_works_for_non_watchlist_symbol(db):
    # A scheduled-scan-only symbol (no watchlist row) is still removable.
    c = _open(db)
    _add_state(c, 'SOLUSDT', 'W_D', 2)
    c.commit()
    c.close()
    with wp.app.test_request_context(
            '/api/trading/scanner/board-symbol', method='DELETE', json={'symbol': 'SOLUSDT'}):
        payload = wp.api_trading_scanner_board_symbol_delete().get_json()
    assert payload['removed'] == 'SOLUSDT' and payload['rows'] == 1
    c = _open(db)
    assert c.execute("SELECT COUNT(*) FROM cascade_state").fetchone()[0] == 0
    c.close()


def test_board_symbol_delete_requires_symbol(db):
    with wp.app.test_request_context(
            '/api/trading/scanner/board-symbol', method='DELETE', json={}):
        resp = wp.api_trading_scanner_board_symbol_delete()
    body, status = (resp if isinstance(resp, tuple) else (resp, 200))
    assert status == 400
