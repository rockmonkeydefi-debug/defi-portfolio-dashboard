"""Watchlist as the single source of truth for the cascade board/universe.

Covers:
  * `_cascade_summary` filters both the per-pair counts and the ticker-major
    `board` to symbols present on the watchlist (orphaned cascade_state rows are
    excluded even before the boot purge runs);
  * the watchlist remove and Remove-All handlers cascade-delete cascade_state in
    the same transaction while leaving the append-only cascade_transitions log
    intact;
  * `_purge_cascade_orphans` deletes strays and no-ops on a clean DB, transitions
    preserved throughout.

In-memory / temp-file SQLite mirrors of the post-migration tables — no network.
"""
import sqlite3
import threading

import pytest

# The module spins background schedulers at import; neutralize before importing.
_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as _pdb


def _schema(c):
    """A trimmed mirror of the columns these code paths actually read/write."""
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
    """A temp-file DB (so a handler can close its conn and we can still reopen
    to assert) with get_connection patched to hand out fresh conns to it."""
    path = str(tmp_path / 'sot.db')
    c = _open(path)
    _schema(c)
    c.commit()
    c.close()
    monkeypatch.setattr(_pdb, 'get_connection', lambda: _open(path))
    return path


# ── _cascade_summary filters to the watchlist ────────────────────────────────

def test_board_and_counts_exclude_non_watchlist_symbols(db):
    c = _open(db)
    c.execute("INSERT INTO scanner_watchlist (symbol) VALUES ('BTCUSDT')")
    # On-watchlist symbol at Stage 2, plus an ORPHAN (ETH not on the watchlist)
    # sitting at Stage 3 — the orphan must not appear anywhere in the summary.
    c.execute("INSERT INTO cascade_state (symbol, pair, stage) VALUES ('BTCUSDT','W_D',2)")
    c.execute("INSERT INTO cascade_state (symbol, pair, stage) VALUES ('ETHUSDT','W_D',3)")
    c.commit()
    summary = wp._cascade_summary(c)
    c.close()

    assert {b['symbol'] for b in summary['board']} == {'BTCUSDT'}
    wd = summary['pairs']['W_D']
    assert wd['tickers']['2'] == ['BTCUSDT']
    assert wd['tickers']['3'] == []          # orphan filtered out
    assert wd['counts']['3'] == 0
    assert wd['counts']['2'] == 1


# ── remove handler cascades to cascade_state, keeps transitions ──────────────

def test_remove_handler_deletes_cascade_state_keeps_transitions(db):
    c = _open(db)
    c.execute("INSERT INTO scanner_watchlist (id, symbol) VALUES (1, 'BTCUSDT')")
    c.execute("INSERT INTO cascade_state (symbol, pair, stage) VALUES ('BTCUSDT','W_D',2)")
    c.execute("INSERT INTO cascade_state (symbol, pair, stage) VALUES ('BTCUSDT','W_H4',1)")
    c.execute("INSERT INTO cascade_transitions (symbol, pair, from_stage, to_stage, reason) "
              "VALUES ('BTCUSDT','W_D',1,2,'nested')")
    c.commit()
    c.close()

    with wp.app.test_request_context():
        resp = wp.api_trading_scanner_watchlist_delete(1)
    assert resp.get_json()['success'] is True

    c = _open(db)
    assert c.execute("SELECT COUNT(*) FROM scanner_watchlist WHERE id=1").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM cascade_state WHERE symbol='BTCUSDT'").fetchone()[0] == 0
    # append-only history survives the removal
    assert c.execute("SELECT COUNT(*) FROM cascade_transitions WHERE symbol='BTCUSDT'").fetchone()[0] == 1
    c.close()


# ── Remove All cascades to cascade_state, keeps transitions ──────────────────

def test_clear_handler_purges_cascade_state_keeps_transitions(db):
    c = _open(db)
    c.execute("INSERT INTO scanner_watchlist (symbol) VALUES ('BTCUSDT')")
    c.execute("INSERT INTO scanner_watchlist (symbol) VALUES ('ETHUSDT')")
    c.execute("INSERT INTO cascade_state (symbol, pair, stage) VALUES ('BTCUSDT','W_D',2)")
    c.execute("INSERT INTO cascade_state (symbol, pair, stage) VALUES ('ETHUSDT','W_H4',3)")
    c.execute("INSERT INTO cascade_transitions (symbol, pair, from_stage, to_stage, reason) "
              "VALUES ('BTCUSDT','W_D',1,2,'nested')")
    c.commit()
    c.close()

    with wp.app.test_request_context():
        wp.api_trading_scanner_watchlist_clear()

    c = _open(db)
    assert c.execute("SELECT COUNT(*) FROM scanner_watchlist").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM cascade_state").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM cascade_transitions").fetchone()[0] == 1
    c.close()


# ── boot orphan purge: removes strays, no-ops when clean, keeps transitions ──

def test_orphan_purge_removes_strays_then_noops(db):
    c = _open(db)
    c.execute("INSERT INTO scanner_watchlist (symbol) VALUES ('BTCUSDT')")
    c.execute("INSERT INTO cascade_state (symbol, pair, stage) VALUES ('BTCUSDT','W_D',2)")
    c.execute("INSERT INTO cascade_state (symbol, pair, stage) VALUES ('ETHUSDT','W_D',3)")   # orphan
    c.execute("INSERT INTO cascade_state (symbol, pair, stage) VALUES ('KAITOUSDT','W_H4',1)")  # orphan
    c.execute("INSERT INTO cascade_transitions (symbol, pair, from_stage, to_stage, reason) "
              "VALUES ('ETHUSDT','W_D',2,3,'mss')")
    c.commit()

    n = wp._purge_cascade_orphans(c)
    c.commit()
    assert n == 2
    assert {r['symbol'] for r in c.execute("SELECT symbol FROM cascade_state")} == {'BTCUSDT'}
    # transitions for the purged orphan are preserved (append-only history)
    assert c.execute("SELECT COUNT(*) FROM cascade_transitions WHERE symbol='ETHUSDT'").fetchone()[0] == 1

    # second run on the now-clean DB is a no-op
    assert wp._purge_cascade_orphans(c) == 0
    c.close()


def test_orphan_purge_noop_on_clean_db(db):
    c = _open(db)
    c.execute("INSERT INTO scanner_watchlist (symbol) VALUES ('BTCUSDT')")
    c.execute("INSERT INTO cascade_state (symbol, pair, stage) VALUES ('BTCUSDT','W_D',2)")
    c.commit()
    assert wp._purge_cascade_orphans(c) == 0
    assert c.execute("SELECT COUNT(*) FROM cascade_state").fetchone()[0] == 1
    c.close()
