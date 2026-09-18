"""Spot trade log (HANDOFF_trade_log.md) - the Sep 13 sizing gate's source
of truth. Commit 1 (backend): the _trade_log_* pure helpers (R is
computed, never stored/typed - ruling 2), the spot_trade_log table
(ruling 1, including the ticker-casing deviation), the scanner-snapshot
capture at POST time (ruling 4), and the four routes under
/api/spot/trade-log (ruling 3/5).

Fixture conventions (this suite has no cross-file fixture imports - every
noodle_*/spot_* test file in this repo is self-contained):
  - Schema-existence tests mirror tests/test_noodle_scan_runs.py exactly:
    real init_db() against a temp-file SQLite via a monkeypatched
    get_db_path() - proves the new CREATE TABLE IF NOT EXISTS is
    idempotent, not a hand-rolled schema mirror.
  - R/risk/notional helper tests call the pure functions directly, no
    fixture at all.
  - Route tests reuse tests/test_noodle_band_proximity.py's shared-cache
    in-memory SQLite + hand-rolled schema + monkeypatched get_connection +
    client fixture convention verbatim (both noodle_state, for the
    snapshot join, and the new spot_trade_log table live in the same
    hand-rolled schema here).
"""
import sqlite3
import threading
import uuid

import pytest

import src.storage.portfolio_db as portfolio_db

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start


# ── schema existence, mirroring test_noodle_scan_runs.py exactly ─────────

SPOT_TRADE_LOG_COLUMNS = (
    'id', 'ticker', 'direction', 'source', 'venue', 'entry_price',
    'stop_price', 'qty', 'target_price', 'exit_price', 'entered_at',
    'exited_at', 'followed_rules', 'deviation_note', 'notes',
    'scanner_snapshot_json', 'created_at', 'updated_at',
)


def _open(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_spot_trade_log_table_exists_after_init_db(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(portfolio_db, 'get_db_path', lambda: path)

    portfolio_db.init_db()

    conn = _open(path)
    cols = {row['name'] for row in conn.execute("PRAGMA table_info(spot_trade_log)")}
    for col in SPOT_TRADE_LOG_COLUMNS:
        assert col in cols
    conn.close()


def test_init_db_twice_is_a_noop_for_spot_trade_log(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(portfolio_db, 'get_db_path', lambda: path)

    portfolio_db.init_db()
    portfolio_db.init_db()  # must not raise (CREATE TABLE IF NOT EXISTS is already idempotent)

    conn = _open(path)
    cols = {row['name'] for row in conn.execute("PRAGMA table_info(spot_trade_log)")}
    for col in SPOT_TRADE_LOG_COLUMNS:
        assert col in cols
    conn.close()


# ── pure helpers: _trade_log_risk_and_r / _trade_log_planned_rr ──────────

def test_risk_and_r_long_win():
    risk_per_unit, r_result = wp._trade_log_risk_and_r('long', 100.0, 90.0, 120.0)
    assert risk_per_unit == pytest.approx(10.0)
    assert r_result == pytest.approx(2.0)   # (120-100)/10


def test_risk_and_r_long_loss():
    risk_per_unit, r_result = wp._trade_log_risk_and_r('long', 100.0, 90.0, 95.0)
    assert risk_per_unit == pytest.approx(10.0)
    assert r_result == pytest.approx(-0.5)   # (95-100)/10


def test_risk_and_r_short_win():
    risk_per_unit, r_result = wp._trade_log_risk_and_r('short', 100.0, 110.0, 80.0)
    assert risk_per_unit == pytest.approx(10.0)
    assert r_result == pytest.approx(2.0)   # (100-80)/10


def test_risk_and_r_short_loss():
    risk_per_unit, r_result = wp._trade_log_risk_and_r('short', 100.0, 110.0, 105.0)
    assert risk_per_unit == pytest.approx(10.0)
    assert r_result == pytest.approx(-0.5)   # (100-105)/10


def test_risk_and_r_none_while_open():
    risk_per_unit, r_result = wp._trade_log_risk_and_r('long', 100.0, 90.0, None)
    assert risk_per_unit == pytest.approx(10.0)
    assert r_result is None


def test_planned_rr_long():
    assert wp._trade_log_planned_rr('long', 100.0, 90.0, 130.0) == pytest.approx(3.0)


def test_planned_rr_short():
    assert wp._trade_log_planned_rr('short', 100.0, 110.0, 70.0) == pytest.approx(3.0)


def test_planned_rr_none_when_no_target():
    assert wp._trade_log_planned_rr('long', 100.0, 90.0, None) is None


def test_risk_usd_and_notional_usd():
    assert wp._trade_log_risk_usd(10.0, 5.0) == pytest.approx(50.0)
    assert wp._trade_log_notional_usd(100.0, 5.0) == pytest.approx(500.0)


# ── routes, reusing test_noodle_band_proximity.py's shared-cache/ ────────
# ── hand-rolled-schema/client fixture convention ──────────────────────────

NOODLE_STATE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS noodle_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        state TEXT,
        flip_ts REAL,
        flip_price REAL,
        flip_age_unbounded INTEGER,
        flip_count_window INTEGER,
        alignment_bull INTEGER,
        alignment_bear INTEGER,
        basis_ema REAL,
        upper_band REAL,
        lower_band REAL,
        last_close REAL,
        price REAL,
        computed_at TEXT,
        volume_24h REAL,
        alignment_state TEXT,
        alignment_prev_state TEXT,
        alignment_changed_ts REAL,
        alignment_changed_unbounded INTEGER,
        rs_vs_btc_pct REAL,
        UNIQUE(symbol, timeframe)
    )
"""

SPOT_TRADE_LOG_SCHEMA = """
    CREATE TABLE IF NOT EXISTS spot_trade_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT NOT NULL,
        direction TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'MHC',
        venue TEXT,
        entry_price REAL NOT NULL,
        stop_price REAL NOT NULL,
        qty REAL NOT NULL,
        target_price REAL,
        exit_price REAL,
        entered_at TEXT NOT NULL,
        exited_at TEXT,
        followed_rules INTEGER,
        deviation_note TEXT,
        notes TEXT,
        scanner_snapshot_json TEXT,
        created_at TEXT,
        updated_at TEXT
    )
"""


@pytest.fixture
def trade_log_db(monkeypatch):
    uri = f"file:spot_trade_log_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    keepalive.row_factory = sqlite3.Row
    keepalive.executescript(NOODLE_STATE_SCHEMA)
    keepalive.executescript(SPOT_TRADE_LOG_SCHEMA)
    keepalive.commit()

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    yield keepalive
    keepalive.close()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def test_post_rejects_entry_equal_to_stop(client, trade_log_db):
    resp = client.post('/api/spot/trade-log', json={
        'ticker': 'BTC', 'direction': 'long', 'entry_price': 100.0,
        'stop_price': 100.0, 'qty': 1.0,
    })
    assert resp.status_code == 400


def test_post_captures_snapshot_with_noodle_state_rows_present(client, trade_log_db):
    trade_log_db.execute(
        """INSERT INTO noodle_state
             (symbol, timeframe, state, upper_band, lower_band, last_close, computed_at)
           VALUES ('BTC', '1d', 'BEARISH', 110.0, 90.0, 100.0, '2026-01-01T00:00:00+00:00')""")
    trade_log_db.execute(
        """INSERT INTO noodle_state
             (symbol, timeframe, state, upper_band, lower_band, last_close, computed_at)
           VALUES ('BTC', '1w', 'BULLISH', 210.0, 190.0, 200.0, '2026-01-01T00:00:00+00:00')""")
    trade_log_db.commit()

    resp = client.post('/api/spot/trade-log', json={
        'ticker': 'BTC', 'direction': 'long', 'entry_price': 100.0,
        'stop_price': 90.0, 'qty': 1.0,
    })
    assert resp.status_code == 200
    payload = resp.get_json()
    snapshot = payload['scanner_snapshot']
    assert 'reason' not in snapshot
    tfs = {t['timeframe']: t for t in snapshot['timeframes']}
    assert set(tfs.keys()) == {'1d', '1w'}
    for tf in tfs.values():
        assert 'dist_to_flip_pct' in tf
    assert tfs['1d']['dist_to_flip_pct'] == pytest.approx((110.0 - 100.0) / 100.0 * 100.0)
    assert tfs['1w']['dist_to_flip_pct'] == pytest.approx((190.0 - 200.0) / 200.0 * 100.0)


def test_post_captures_snapshot_with_no_noodle_state_rows(client, trade_log_db):
    resp = client.post('/api/spot/trade-log', json={
        'ticker': 'NOTASCANNEDCOIN', 'direction': 'long', 'entry_price': 100.0,
        'stop_price': 90.0, 'qty': 1.0,
    })
    assert resp.status_code == 200
    snapshot = resp.get_json()['scanner_snapshot']
    assert snapshot['reason'] == 'not_in_scanner_universe'


def test_ticker_casing_preserved_exactly_through_post_and_snapshot(client, trade_log_db):
    # Regression guard for the ruling-1 deviation: kilo-token tickers carry
    # a lowercase 'k' prefix in noodle_state.symbol - forcing uppercase
    # anywhere in the write path would silently break the snapshot join.
    trade_log_db.execute(
        """INSERT INTO noodle_state
             (symbol, timeframe, state, upper_band, lower_band, last_close, computed_at)
           VALUES ('kBONK', '1d', 'BULLISH', 1.1, 0.9, 1.0, '2026-01-01T00:00:00+00:00')""")
    trade_log_db.commit()

    resp = client.post('/api/spot/trade-log', json={
        'ticker': 'kBONK', 'direction': 'long', 'entry_price': 1.0,
        'stop_price': 0.9, 'qty': 100.0,
    })
    assert resp.status_code == 200
    payload = resp.get_json()
    snapshot = payload['scanner_snapshot']
    assert snapshot['timeframes'][0]['timeframe'] == '1d'
    assert 'reason' not in snapshot

    row = trade_log_db.execute(
        "SELECT ticker FROM spot_trade_log WHERE id=?", (payload['id'],)).fetchone()
    assert row['ticker'] == 'kBONK'   # not 'KBONK'


def test_put_close_without_followed_rules_rejected(client, trade_log_db):
    created = client.post('/api/spot/trade-log', json={
        'ticker': 'ETH', 'direction': 'long', 'entry_price': 100.0,
        'stop_price': 90.0, 'qty': 1.0,
    }).get_json()

    resp = client.put(f"/api/spot/trade-log/{created['id']}", json={'exit_price': 120.0})
    assert resp.status_code == 400


def test_put_close_with_followed_rules_zero_or_one_succeeds(client, trade_log_db):
    created = client.post('/api/spot/trade-log', json={
        'ticker': 'ETH', 'direction': 'long', 'entry_price': 100.0,
        'stop_price': 90.0, 'qty': 1.0,
    }).get_json()

    resp = client.put(f"/api/spot/trade-log/{created['id']}",
                       json={'exit_price': 120.0, 'followed_rules': 1})
    assert resp.status_code == 200

    created2 = client.post('/api/spot/trade-log', json={
        'ticker': 'ETH', 'direction': 'long', 'entry_price': 100.0,
        'stop_price': 90.0, 'qty': 1.0,
    }).get_json()
    resp2 = client.put(f"/api/spot/trade-log/{created2['id']}",
                        json={'exit_price': 80.0, 'followed_rules': 0})
    assert resp2.status_code == 200


def test_followed_rules_already_set_allows_close_without_repeating(client, trade_log_db):
    # Ruling 3's "already set" branch: followed_rules recorded on an
    # earlier PUT while still open, then closed later WITHOUT repeating
    # it in the closing request - must succeed using the row's existing
    # value, not just the "same request" branch every other close test
    # here exercises.
    created = client.post('/api/spot/trade-log', json={
        'ticker': 'ETH', 'direction': 'long', 'entry_price': 100.0,
        'stop_price': 90.0, 'qty': 1.0,
    }).get_json()

    put1 = client.put(f"/api/spot/trade-log/{created['id']}", json={'followed_rules': 1})
    assert put1.status_code == 200

    put2 = client.put(f"/api/spot/trade-log/{created['id']}", json={'exit_price': 120.0})
    assert put2.status_code == 200

    row = trade_log_db.execute(
        "SELECT followed_rules, exit_price FROM spot_trade_log WHERE id=?",
        (created['id'],)).fetchone()
    assert row['followed_rules'] == 1
    assert row['exit_price'] == pytest.approx(120.0)

    resp = client.get('/api/spot/trade-log')
    trade = next(t for t in resp.get_json()['trades'] if t['id'] == created['id'])
    assert trade['status'] == 'closed'
    assert trade['followed_rules'] == 1


def test_summary_math_on_a_small_seeded_set(client, trade_log_db):
    # One open trade + two closed trades with known r_results.
    open_trade = client.post('/api/spot/trade-log', json={
        'ticker': 'OPEN1', 'direction': 'long', 'entry_price': 100.0,
        'stop_price': 90.0, 'qty': 2.0,   # risk_usd = 10 * 2 = 20
    }).get_json()

    win_trade = client.post('/api/spot/trade-log', json={
        'ticker': 'WIN1', 'direction': 'long', 'entry_price': 100.0,
        'stop_price': 90.0, 'qty': 1.0, 'source': 'MHC',
    }).get_json()
    client.put(f"/api/spot/trade-log/{win_trade['id']}",
               json={'exit_price': 120.0, 'followed_rules': 1})   # r_result = +2.0

    loss_trade = client.post('/api/spot/trade-log', json={
        'ticker': 'LOSS1', 'direction': 'long', 'entry_price': 100.0,
        'stop_price': 90.0, 'qty': 1.0, 'source': 'MHC',
    }).get_json()
    client.put(f"/api/spot/trade-log/{loss_trade['id']}",
               json={'exit_price': 85.0, 'followed_rules': 1})   # r_result = -1.5

    resp = client.get('/api/spot/trade-log')
    assert resp.status_code == 200
    summary = resp.get_json()['summary']
    assert summary['open_count'] == 1
    assert summary['closed_count'] == 2
    assert summary['win_count'] == 1
    assert summary['loss_count'] == 1
    assert summary['mhc_followed_closed_count'] == 2
    assert summary['gate_target'] == 20
    assert summary['net_r'] == pytest.approx(0.5)         # 2.0 + (-1.5)
    assert summary['expectancy_r'] == pytest.approx(0.25)  # 0.5 / 2
    assert summary['open_risk_usd'] == pytest.approx(20.0)
