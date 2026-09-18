"""Noodle scanner (MA-band trend indicator, Commit 2) - the busy lock, the
spawn seam, the staleness trigger, and the retention sweep for
_run_noodle_scan_body / _maybe_kick_noodle_auto_refresh.

Same shared-cache sqlite / monkeypatched get_connection pattern as
tests/test_metrics_auto_refresh.py (the scan body opens and closes its OWN
connection per call - a bare ":memory:" would lose state the instant that
connection closed). No network, no real threads - _spawn_noodle_scan_thread
is monkeypatched to a recorder in every trigger test, and every HL-touching
function (_hl_fetch_top_volume, _hl_resolve_coin, _hl_fetch_candles) plus
compute_noodle_state itself is monkeypatched in every scan-body test so
nothing here ever reaches the network or depends on the indicator's own
numeric behavior (that's covered by tests/test_noodle_bands.py).
_SCANNER_SETTINGS_PATH is monkeypatched to a tmp_path file in every test
that reaches _scanner_settings(), so a stray real settings file can never
leak into these tests.
"""
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import pytest

import src.storage.portfolio_db as portfolio_db

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
        UNIQUE(symbol, timeframe)
    )
"""

# Commit 3 (async scan + progress) - mirrors the noodle_scan_runs
# CREATE TABLE in src/storage/portfolio_db.py exactly (see
# tests/test_noodle_scan_runs.py for the schema-migration test itself).
NOODLE_SCAN_RUNS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS noodle_scan_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trigger TEXT NOT NULL,
        status TEXT NOT NULL,
        started_ts REAL NOT NULL,
        updated_ts REAL NOT NULL,
        finished_ts REAL,
        total INTEGER,
        done INTEGER NOT NULL DEFAULT 0,
        errors INTEGER NOT NULL DEFAULT 0,
        retired INTEGER,
        error_msg TEXT
    )
"""

# Trends-restyle Commit 2: compute_noodle_state has returned the four
# alignment_* keys since Commit 1 - every test here monkeypatches
# compute_noodle_state directly, so FAKE_RESULT must carry them too or the
# scan body's now-additive reads of result['alignment_state'] etc. raise
# KeyError. Values are internally consistent with alignment_bull=3/
# alignment_bear=0 (a full bullish stack -> alignment_state=BULLISH) and a
# distinct alignment_changed_ts from flip_ts so the two can be told apart
# in assertions.
FAKE_RESULT = {
    'state': 'BULLISH', 'flip_ts': 1700000000.0, 'flip_price': 123.45,
    'flip_age_unbounded': False, 'flip_count_window': 4,
    'alignment_bull': 3, 'alignment_bear': 0,
    'basis_ema': 100.0, 'upper_band': 110.0, 'lower_band': 90.0,
    'alignment_state': 'BULLISH', 'alignment_prev_state': None,
    'alignment_changed_ts': 1690000000.0, 'alignment_changed_unbounded': True,
}


@pytest.fixture
def noodle_db(monkeypatch):
    uri = f"file:noodle_auto_refresh_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    keepalive.row_factory = sqlite3.Row
    keepalive.executescript(NOODLE_STATE_SCHEMA)
    # Commit 3: _run_noodle_scan_body now writes a noodle_scan_runs row
    # before it ever touches noodle_state (the run row is inserted right
    # after the lock is acquired) - every scan-body test in this file
    # would fail on that very first write without this table.
    keepalive.executescript(NOODLE_SCAN_RUNS_SCHEMA)
    keepalive.commit()

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    yield keepalive
    keepalive.close()


def _default_scanner_settings_path(monkeypatch, tmp_path):
    """Points _SCANNER_SETTINGS_PATH at a not-yet-existing tmp file, so
    _scanner_settings() falls back to _SCANNER_SETTINGS_DEFAULTS
    deterministically (noodle_staleness_hours=6, noodle_retention_days=14,
    noodle_max_tickers=250, ...) regardless of any real settings file on
    disk."""
    monkeypatch.setattr(wp, "_SCANNER_SETTINGS_PATH", str(tmp_path / "scanner_settings.json"))


def _fake_universe(*symbols, asset_type='crypto'):
    """A _hl_fetch_top_volume-shaped list: perp entries ('-USDT' suffix),
    already volume-sorted descending, same field names the real function
    returns (name/symbol/volume_24h/price/asset_type)."""
    return [
        {'name': s, 'symbol': f'{s}-USDT', 'volume_24h': 1000.0 - i,
         'price': 100.0 + i, 'asset_type': asset_type}
        for i, s in enumerate(symbols)
    ]


def _tiny_candles(n=10, start=1_700_000_000, step=86400):
    return [
        {'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.0,
         'volume': 1.0, 'time': start + i * step}
        for i in range(n)
    ]


def _seed_row(db, symbol, timeframe, computed_at):
    db.execute(
        "INSERT INTO noodle_state (symbol, timeframe, computed_at) VALUES (?, ?, ?)",
        (symbol, timeframe, computed_at))
    db.commit()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


# ── (a) busy lock ─────────────────────────────────────────────────────────

def test_run_noodle_scan_body_409s_while_lock_held_then_recovers(noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume', lambda n=None, limit=None: [])

    assert wp._NOODLE_SCAN_LOCK.acquire(blocking=False)
    try:
        # The 409 happens BEFORE _run_noodle_scan_body even attempts to
        # acquire (acquire fails immediately) - nothing for that call to
        # release, so the lock is still held by this test right here.
        payload, status = wp._run_noodle_scan_body()
        assert status == 409
        assert payload['error'] == 'RefreshBusy'
        assert wp._NOODLE_SCAN_LOCK.locked()
    finally:
        wp._NOODLE_SCAN_LOCK.release()

    # Lock released - a normal call must no longer 409. Empty universe, so
    # this exercises the ordinary empty-pass path.
    payload2, status2 = wp._run_noodle_scan_body()
    assert status2 == 200
    assert payload2['universe_size'] == 0
    assert payload2['scanned'] == 0
    assert payload2['errors'] == 0


# ── (b) successful run upserts rows with the expected columns ──────────────

def test_run_noodle_scan_body_upserts_rows_for_each_timeframe(noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('BTC'))
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    monkeypatch.setattr(wp, '_hl_fetch_candles', lambda coin, interval, limit=200: _tiny_candles())
    monkeypatch.setattr(wp, 'compute_noodle_state', lambda candles, **kw: dict(FAKE_RESULT))

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['universe_size'] == 1
    assert payload['scanned'] == 1
    assert payload['errors'] == 0

    rows = {r['timeframe']: dict(r) for r in
            noodle_db.execute("SELECT * FROM noodle_state WHERE symbol='BTC'").fetchall()}
    # Intraday-timeframes Commit 1: '4h' (derived) and '1h' (native) joined
    # the per-symbol timeframe tuple alongside the original three.
    assert set(rows.keys()) == {'1w', '1d', '12h', '4h', '1h'}
    for tf, row in rows.items():
        assert row['state'] == 'BULLISH'
        assert row['flip_ts'] == pytest.approx(1700000000.0)
        assert row['flip_price'] == pytest.approx(123.45)
        assert row['flip_age_unbounded'] == 0    # stored as INTEGER 0/1
        assert row['alignment_bull'] == 3
        assert row['alignment_bear'] == 0
        assert row['basis_ema'] == pytest.approx(100.0)
        assert row['upper_band'] == pytest.approx(110.0)
        assert row['lower_band'] == pytest.approx(90.0)
        assert row['price'] == pytest.approx(100.0)   # BTC's fake universe price
        assert row['computed_at']   # non-empty timestamp string


def test_run_noodle_scan_body_logs_short_1h_depth_but_completes_normally(
        noodle_db, tmp_path, monkeypatch, capsys):
    """Ruling 8 regression guard (HANDOFF_intraday_timeframes.md): an
    under-depth 1h fetch (fewer bars than NOODLE_CANDLE_LIMITS['1h']) is a
    log-only depth-quality signal - it must never increment errors, block
    the row write, or otherwise fail the scan. Mocks _hl_fetch_candles to
    return fewer bars specifically for the '1h' interval, well under the
    1440-bar limit."""
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('BTC'))
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)

    def fake_fetch_candles(coin, interval, limit=200):
        if interval == '1h':
            return _tiny_candles(n=100)   # well under NOODLE_CANDLE_LIMITS['1h'] (1440)
        return _tiny_candles()

    monkeypatch.setattr(wp, '_hl_fetch_candles', fake_fetch_candles)
    monkeypatch.setattr(wp, 'compute_noodle_state', lambda candles, **kw: dict(FAKE_RESULT))

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['scanned'] == 1
    assert payload['errors'] == 0   # log-only - never counted as a scan error

    out = capsys.readouterr().out
    assert 'BTC' in out
    assert '1h depth short' in out
    assert 'requested=1440' in out
    assert 'returned=100' in out

    # The scan proceeds on whatever depth it actually got - a row is still
    # written for every timeframe, '1h'/'4h' included.
    rows = {r['timeframe'] for r in noodle_db.execute(
        "SELECT timeframe FROM noodle_state WHERE symbol='BTC'").fetchall()}
    assert rows == {'1w', '1d', '12h', '4h', '1h'}


def test_run_noodle_scan_body_upsert_overwrites_prior_row(noodle_db, tmp_path, monkeypatch):
    """UNIQUE(symbol, timeframe) is the upsert key - a second pass replaces,
    never duplicates."""
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('BTC'))
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    monkeypatch.setattr(wp, '_hl_fetch_candles', lambda coin, interval, limit=200: _tiny_candles())
    monkeypatch.setattr(wp, 'compute_noodle_state', lambda candles, **kw: dict(FAKE_RESULT))

    wp._run_noodle_scan_body()
    changed = dict(FAKE_RESULT, state='BEARISH')
    monkeypatch.setattr(wp, 'compute_noodle_state', lambda candles, **kw: dict(changed))
    wp._run_noodle_scan_body()

    rows = noodle_db.execute("SELECT state FROM noodle_state WHERE symbol='BTC' AND timeframe='1d'").fetchall()
    assert len(rows) == 1
    assert rows[0]['state'] == 'BEARISH'


# ── universe filter: spot ('-USDC') entries are excluded ───────────────────

def test_run_noodle_scan_body_filters_out_spot_entries(noodle_db, tmp_path, monkeypatch):
    universe = _fake_universe('BTC') + [
        {'name': 'ETH', 'symbol': 'ETH-USDC', 'volume_24h': 999.0, 'price': 200.0, 'asset_type': 'crypto'},
    ]
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume', lambda n=None, limit=None: universe)
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    monkeypatch.setattr(wp, '_hl_fetch_candles', lambda coin, interval, limit=200: _tiny_candles())
    monkeypatch.setattr(wp, 'compute_noodle_state', lambda candles, **kw: dict(FAKE_RESULT))

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['universe_size'] == 1   # ETH-USDC (spot) dropped

    symbols = {r['symbol'] for r in noodle_db.execute("SELECT DISTINCT symbol FROM noodle_state").fetchall()}
    assert symbols == {'BTC'}


# ── (c) staleness trigger ───────────────────────────────────────────────

def test_maybe_kick_noodle_auto_refresh_fresh_table_does_not_spawn(noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    recorder = []
    monkeypatch.setattr(wp, '_spawn_noodle_scan_thread', lambda trigger: recorder.append(trigger))
    now = datetime.now(timezone.utc).isoformat()
    _seed_row(noodle_db, 'BTC', '1d', now)

    stale = wp._maybe_kick_noodle_auto_refresh()
    assert stale is False
    assert recorder == []


def test_maybe_kick_noodle_auto_refresh_stale_row_spawns(noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    recorder = []
    monkeypatch.setattr(wp, '_spawn_noodle_scan_thread', lambda trigger: recorder.append(trigger))
    old = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()   # default staleness = 6h
    _seed_row(noodle_db, 'BTC', '1d', old)

    stale = wp._maybe_kick_noodle_auto_refresh()
    assert stale is True
    # Commit 3: the auto-trigger must identify itself as 'auto', not
    # 'manual' - GET /noodle-progress and the frontend's "(auto)" label
    # both depend on this.
    assert recorder == ['auto']


def test_maybe_kick_noodle_auto_refresh_empty_table_spawns(noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    recorder = []
    monkeypatch.setattr(wp, '_spawn_noodle_scan_thread', lambda trigger: recorder.append(trigger))
    # No rows at all.

    stale = wp._maybe_kick_noodle_auto_refresh()
    assert stale is True
    assert recorder == ['auto']


# ── (d) retention ─────────────────────────────────────────────────────────

def test_run_noodle_scan_body_retires_rows_past_retention_but_not_within(noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume', lambda n=None, limit=None: [])   # isolates retention
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=20)).isoformat()     # older than the default 14-day retention
    fresh = (now - timedelta(days=1)).isoformat()    # within the retention window
    _seed_row(noodle_db, 'OLDCOIN', '1d', old)
    _seed_row(noodle_db, 'FRESHCOIN', '1d', fresh)

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['retired'] == 1

    remaining = {r['symbol'] for r in noodle_db.execute("SELECT symbol FROM noodle_state").fetchall()}
    assert remaining == {'FRESHCOIN'}


def test_run_noodle_scan_body_never_retires_a_null_computed_at_row(noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume', lambda n=None, limit=None: [])
    noodle_db.execute(
        "INSERT INTO noodle_state (symbol, timeframe, computed_at) VALUES ('NOCOMPUTE', '1d', NULL)")
    noodle_db.commit()

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['retired'] == 0
    remaining = {r['symbol'] for r in noodle_db.execute("SELECT symbol FROM noodle_state").fetchall()}
    assert remaining == {'NOCOMPUTE'}


# ── (e) per-symbol isolation ─────────────────────────────────────────────

def test_run_noodle_scan_body_isolates_one_symbols_failure(noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('GOODCOIN', 'BADCOIN'))
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)

    def fake_fetch_candles(coin, interval, limit=200):
        if coin == 'BADCOIN':
            raise RuntimeError('simulated HL failure')
        return _tiny_candles()

    monkeypatch.setattr(wp, '_hl_fetch_candles', fake_fetch_candles)
    monkeypatch.setattr(wp, 'compute_noodle_state', lambda candles, **kw: dict(FAKE_RESULT))

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['universe_size'] == 2
    assert payload['scanned'] == 1
    assert payload['errors'] == 1

    rows = noodle_db.execute("SELECT symbol, timeframe FROM noodle_state").fetchall()
    symbols = {r['symbol'] for r in rows}
    assert symbols == {'GOODCOIN'}                 # BADCOIN never wrote a row
    assert len(rows) == 5                          # GOODCOIN's all 5 timeframes intact, none dropped


def test_run_noodle_scan_body_isolates_a_compute_failure_too(noodle_db, tmp_path, monkeypatch):
    """The same isolation must hold when compute_noodle_state itself raises,
    not just when the HL fetch raises. GOODCOIN is processed first (and
    fully committed) so this only exercises isolation, not the separate
    question of whether a mid-loop failure could leak a partial row into a
    LATER symbol's commit."""
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('GOODCOIN', 'BADCOIN'))
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)

    def fake_fetch_candles(coin, interval, limit=200):
        # BADCOIN's series are deliberately much shorter (post-trim len <=
        # 2, including its DERIVED weekly bucket) so fake_compute below can
        # tell them apart from GOODCOIN's without relying on object
        # identity, which candles[:-1] always breaks. GOODCOIN gets 60 days
        # so its own derived weekly series (~8 buckets) stays well clear of
        # that threshold regardless of Monday-boundary alignment.
        return _tiny_candles(n=3) if coin == 'BADCOIN' else _tiny_candles(n=60)

    def fake_compute(candles, **kw):
        if len(candles) <= 2:
            raise RuntimeError('boom')
        return dict(FAKE_RESULT)

    monkeypatch.setattr(wp, '_hl_fetch_candles', fake_fetch_candles)
    monkeypatch.setattr(wp, 'compute_noodle_state', fake_compute)

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['scanned'] == 1
    assert payload['errors'] == 1
    symbols = {r['symbol'] for r in noodle_db.execute("SELECT symbol FROM noodle_state").fetchall()}
    assert symbols == {'GOODCOIN'}


# ── regression: a mid-loop failure must not leave an orphaned partial row ──

def test_run_noodle_scan_body_rolls_back_partial_write_before_later_symbols_commit(
        noodle_db, tmp_path, monkeypatch):
    """FAILCOIN fails partway through its 5-timeframe loop - AFTER its '1w'
    row would already have been written (execute()'d, not yet committed)
    but BEFORE '1d' (still the second entry in the per-symbol timeframe
    tuple - '4h'/'1h' were appended at the end, not inserted mid-loop).
    Without a rollback in the except path, that dangling '1w' insert stays
    on the shared connection and gets flushed for free by LATERCOIN's own
    conn.commit() later in the same pass, leaving FAILCOIN with one
    orphaned row instead of zero. FAILCOIN is scanned first (universe
    order), so failing on its second compute_noodle_state call ('1d')
    reproduces exactly that after-first-write, before-second-write
    window."""
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('FAILCOIN', 'LATERCOIN'))
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    monkeypatch.setattr(wp, '_hl_fetch_candles', lambda coin, interval, limit=200: _tiny_candles())

    counter = {'n': 0}

    def fake_compute_ordered(candles, **kw):
        counter['n'] += 1
        if counter['n'] == 2:   # FAILCOIN's '1d' call - its '1w' already wrote
            raise RuntimeError('boom on second timeframe')
        return dict(FAKE_RESULT)

    monkeypatch.setattr(wp, 'compute_noodle_state', fake_compute_ordered)

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['scanned'] == 1
    assert payload['errors'] == 1

    fail_rows = noodle_db.execute("SELECT * FROM noodle_state WHERE symbol='FAILCOIN'").fetchall()
    assert fail_rows == []   # zero rows - not one orphaned '1w' row

    later_rows = noodle_db.execute(
        "SELECT timeframe FROM noodle_state WHERE symbol='LATERCOIN'").fetchall()
    assert {r['timeframe'] for r in later_rows} == {'1w', '1d', '12h', '4h', '1h'}


# ── Trends-restyle Commit 2: volume_24h + alignment fields ────────────────

def test_run_noodle_scan_body_writes_volume_and_alignment_fields(noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('BTC'))
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    monkeypatch.setattr(wp, '_hl_fetch_candles', lambda coin, interval, limit=200: _tiny_candles())
    monkeypatch.setattr(wp, 'compute_noodle_state', lambda candles, **kw: dict(FAKE_RESULT))

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['scanned'] == 1

    rows = noodle_db.execute("SELECT * FROM noodle_state WHERE symbol='BTC'").fetchall()
    assert len(rows) == 5   # '1w'/'1d'/'12h'/'4h'/'1h' - all five timeframes
    for row in rows:
        # volume_24h comes from the universe entry's own field (1000.0, per
        # _fake_universe's i=0 volume of 1000.0-0), NOT re-derived from
        # anything compute_noodle_state returns.
        assert row['volume_24h'] == pytest.approx(1000.0)
        assert row['alignment_state'] == 'BULLISH'
        assert row['alignment_prev_state'] is None
        assert row['alignment_changed_ts'] == pytest.approx(1690000000.0)
        assert row['alignment_changed_unbounded'] == 1   # stored as INTEGER 0/1


def test_run_noodle_scan_body_stores_alignment_changed_unbounded_false_and_prev_state(
        noodle_db, tmp_path, monkeypatch):
    """The bool/None-on-True/False-on-located-change/None-on-undefined shape
    must round-trip through storage correctly for the non-unbounded branch
    too, not just the unbounded one FAKE_RESULT defaults to."""
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('ETH'))
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    monkeypatch.setattr(wp, '_hl_fetch_candles', lambda coin, interval, limit=200: _tiny_candles())
    located_change = dict(FAKE_RESULT, alignment_state='BEARISH',
                           alignment_prev_state='NEUTRAL',
                           alignment_changed_ts=1695000000.0,
                           alignment_changed_unbounded=False)
    monkeypatch.setattr(wp, 'compute_noodle_state', lambda candles, **kw: dict(located_change))

    wp._run_noodle_scan_body()

    row = noodle_db.execute(
        "SELECT * FROM noodle_state WHERE symbol='ETH' AND timeframe='1d'").fetchone()
    assert row['alignment_state'] == 'BEARISH'
    assert row['alignment_prev_state'] == 'NEUTRAL'
    assert row['alignment_changed_ts'] == pytest.approx(1695000000.0)
    assert row['alignment_changed_unbounded'] == 0   # False -> stored as 0, not NULL


def test_run_noodle_scan_body_stores_alignment_changed_unbounded_null_when_undefined(
        noodle_db, tmp_path, monkeypatch):
    """The undefined case (too-short history: alignment_bull is None) must
    store a real SQL NULL, not 0 - None must survive the int(...) guard."""
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('SOL'))
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    monkeypatch.setattr(wp, '_hl_fetch_candles', lambda coin, interval, limit=200: _tiny_candles())
    undefined = {
        'state': 'WARMUP', 'flip_ts': None, 'flip_price': None,
        'flip_age_unbounded': None, 'flip_count_window': None,
        'alignment_bull': None, 'alignment_bear': None,
        'basis_ema': None, 'upper_band': None, 'lower_band': None,
        'alignment_state': None, 'alignment_prev_state': None,
        'alignment_changed_ts': None, 'alignment_changed_unbounded': None,
    }
    monkeypatch.setattr(wp, 'compute_noodle_state', lambda candles, **kw: dict(undefined))

    wp._run_noodle_scan_body()

    row = noodle_db.execute(
        "SELECT * FROM noodle_state WHERE symbol='SOL' AND timeframe='1d'").fetchone()
    assert row['alignment_state'] is None
    assert row['alignment_changed_unbounded'] is None


# ── Trends-restyle Commit 2: route payload (GET /noodle-state) ────────────

def test_noodle_state_route_returns_volume_and_alignment_fields(client, noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    # Freeze the staleness trigger so this test only exercises the read
    # path, not a real (mocked-away) scan.
    monkeypatch.setattr(wp, '_maybe_kick_noodle_auto_refresh', lambda: False)
    noodle_db.execute(
        """INSERT INTO noodle_state
             (symbol, timeframe, state, price, computed_at, volume_24h,
              alignment_state, alignment_prev_state, alignment_changed_ts,
              alignment_changed_unbounded)
           VALUES ('BTC', '1d', 'BULLISH', 50000.0, '2026-01-01T00:00:00+00:00',
                   12345.0, 'BEARISH', 'NEUTRAL', 1695000000.0, 0)""")
    noodle_db.commit()

    resp = client.get('/api/trading/scanner/noodle-state')
    assert resp.status_code == 200
    payload = resp.get_json()
    entry = next(s for s in payload['symbols'] if s['symbol'] == 'BTC')
    tf = entry['timeframes']['1d']
    assert tf['volume_24h'] == pytest.approx(12345.0)
    assert tf['alignment_state'] == 'BEARISH'
    assert tf['alignment_prev_state'] == 'NEUTRAL'
    assert tf['alignment_changed_ts'] == pytest.approx(1695000000.0)
    assert tf['alignment_changed_unbounded'] is False   # int 0 -> bool False, not 0


def test_noodle_state_route_converts_alignment_changed_unbounded_null_to_none(
        client, noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_maybe_kick_noodle_auto_refresh', lambda: False)
    noodle_db.execute(
        "INSERT INTO noodle_state (symbol, timeframe, computed_at) VALUES ('ETH', '12h', NULL)")
    noodle_db.commit()

    resp = client.get('/api/trading/scanner/noodle-state')
    assert resp.status_code == 200
    payload = resp.get_json()
    entry = next(s for s in payload['symbols'] if s['symbol'] == 'ETH')
    tf = entry['timeframes']['12h']
    assert tf['alignment_changed_unbounded'] is None
    assert tf['alignment_state'] is None


def test_noodle_state_route_includes_window_days_meta(client, noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_maybe_kick_noodle_auto_refresh', lambda: False)

    resp = client.get('/api/trading/scanner/noodle-state')
    assert resp.status_code == 200
    payload = resp.get_json()
    # Intraday-timeframes Commit 1: NOODLE_WINDOW_DAYS gained '1h'/'4h' -
    # this route reads the constant directly, so the route needed no code
    # change, only this expectation update.
    assert payload['meta']['window_days'] == {
        '12h': 150, '1d': 299, '1w': 290, '1h': 60, '4h': 60,
    }


# ── Commit 3 (async scan + progress): noodle_scan_runs tracking ──────────

def test_run_noodle_scan_body_creates_run_row_with_total_and_final_done(
        noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('AAA', 'BBB'))
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    monkeypatch.setattr(wp, '_hl_fetch_candles', lambda coin, interval, limit=200: _tiny_candles())
    monkeypatch.setattr(wp, 'compute_noodle_state', lambda candles, **kw: dict(FAKE_RESULT))

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    run_id = payload['run_id']

    row = noodle_db.execute("SELECT * FROM noodle_scan_runs WHERE id=?", (run_id,)).fetchone()
    assert row['trigger'] == 'manual'
    assert row['total'] == 2
    assert row['done'] == 2
    assert row['errors'] == 0


def test_run_noodle_scan_body_advances_done_progressively(noodle_db, tmp_path, monkeypatch):
    """done is written and COMMITTED after each symbol, not batched to the
    end - proven by having compute_noodle_state (called mid-loop, for every
    symbol) read the run row back through the fixture's OWN connection and
    record what it sees. If progress were only written once at the end,
    every one of these reads would see done=0."""
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('AAA', 'BBB', 'CCC'))
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    monkeypatch.setattr(wp, '_hl_fetch_candles', lambda coin, interval, limit=200: _tiny_candles())

    seen = []

    def fake_compute(candles, **kw):
        row = noodle_db.execute(
            "SELECT done, total FROM noodle_scan_runs ORDER BY id DESC LIMIT 1").fetchone()
        seen.append((row['done'], row['total']))
        return dict(FAKE_RESULT)

    monkeypatch.setattr(wp, 'compute_noodle_state', fake_compute)

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['scanned'] == 3

    # total is visible (set before the loop starts) for all 9 calls
    # (3 symbols x 3 timeframes each); done is non-decreasing, starts at 0
    # (AAA's own three calls, before AAA itself has committed) and reaches
    # 2 by CCC's calls (AAA + BBB already committed).
    assert all(total == 3 for _done, total in seen)
    done_values = [d for d, _t in seen]
    assert done_values == sorted(done_values)
    assert done_values[0] == 0
    assert done_values[-1] == 2


def test_run_noodle_scan_body_marks_run_done_with_finished_ts(noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(wp, '_hl_fetch_top_volume',
                         lambda n=None, limit=None: _fake_universe('BTC'))
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    monkeypatch.setattr(wp, '_hl_fetch_candles', lambda coin, interval, limit=200: _tiny_candles())
    monkeypatch.setattr(wp, 'compute_noodle_state', lambda candles, **kw: dict(FAKE_RESULT))

    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    run_id = payload['run_id']

    row = noodle_db.execute("SELECT * FROM noodle_scan_runs WHERE id=?", (run_id,)).fetchone()
    assert row['status'] == 'done'
    assert row['finished_ts'] is not None


def test_run_noodle_scan_body_escaping_exception_marks_run_error(noodle_db, tmp_path, monkeypatch):
    """A failure OUTSIDE the per-symbol loop (universe fetch here) is not
    isolated the way a single symbol's failure is - it must still leave
    the run row in a terminal state (not stuck 'running' until the
    5-minute abandoned threshold) and must not re-raise past this
    function, matching _spawn_noodle_scan_thread's worker contract of
    always getting back a (payload, status) tuple."""
    _default_scanner_settings_path(monkeypatch, tmp_path)

    def boom(n=None, limit=None):
        raise RuntimeError('universe fetch exploded')

    monkeypatch.setattr(wp, '_hl_fetch_top_volume', boom)

    payload, status = wp._run_noodle_scan_body()
    assert status == 500
    assert payload['error'] == 'ScanFailed'
    assert 'universe fetch exploded' in payload['detail']
    run_id = payload['run_id']

    row = noodle_db.execute("SELECT * FROM noodle_scan_runs WHERE id=?", (run_id,)).fetchone()
    assert row['status'] == 'error'
    assert row['error_msg'] and 'universe fetch exploded' in row['error_msg']
    assert row['finished_ts'] is not None

    # The outer finally must still release the lock despite the escaping
    # exception, or every later call/test would 409 forever.
    assert not wp._NOODLE_SCAN_LOCK.locked()


def test_run_noodle_scan_body_409_includes_latest_running_row(noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    now = time.time()
    noodle_db.execute(
        "INSERT INTO noodle_scan_runs (trigger, status, started_ts, updated_ts, done, errors) "
        "VALUES ('manual', 'running', ?, ?, 0, 0)", (now, now))
    noodle_db.commit()

    assert wp._NOODLE_SCAN_LOCK.acquire(blocking=False)
    try:
        payload, status = wp._run_noodle_scan_body()
        assert status == 409
        assert payload['error'] == 'RefreshBusy'
        assert payload['run'] is not None
        assert payload['run']['status'] == 'running'
        assert payload['run']['trigger'] == 'manual'
    finally:
        wp._NOODLE_SCAN_LOCK.release()


def test_spawn_noodle_scan_thread_retention_keeps_newest_20(noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    # This test only exercises the synchronous insert+retention half of
    # _spawn_noodle_scan_thread, with no network mocks set up for the
    # daemon thread's own body - so the thread must never actually run.
    # Same technique this file's own import-time patch (top of file) uses,
    # scoped here via monkeypatch so it auto-restores after the test.
    monkeypatch.setattr(wp.threading.Thread, 'start', lambda self, *a, **k: None)

    for _ in range(25):
        wp._spawn_noodle_scan_thread(trigger='auto')

    rows = noodle_db.execute("SELECT id FROM noodle_scan_runs ORDER BY id").fetchall()
    ids = [r['id'] for r in rows]
    assert len(ids) == 20
    assert min(ids) > 5   # the oldest 5 of 25 runs were retired, not an arbitrary 20


# ── Commit 3: POST /noodle-refresh is now async (202, never inline) ──────

def test_noodle_refresh_route_returns_202_and_spawns_without_running_inline(client, monkeypatch):
    calls = []

    def fake_spawn(trigger):
        calls.append(trigger)
        return 42

    monkeypatch.setattr(wp, '_spawn_noodle_scan_thread', fake_spawn)
    # If the route ran the scan inline (the pre-Commit-3 contract) it would
    # call the real _run_noodle_scan_body, which needs a DB/network stack
    # this test never sets up - trap it so any such call fails loudly
    # instead of silently doing real work.
    def trap(*a, **kw):
        raise AssertionError('_run_noodle_scan_body must not run inline from the route')

    monkeypatch.setattr(wp, '_run_noodle_scan_body', trap)

    resp = client.post('/api/trading/scanner/noodle-refresh')
    assert resp.status_code == 202
    body = resp.get_json()
    assert body == {'run_id': 42, 'status': 'running'}
    assert calls == ['manual']


def test_noodle_refresh_route_409_when_lock_held(client, monkeypatch):
    monkeypatch.setattr(wp, '_latest_running_noodle_run', lambda: {'id': 7, 'status': 'running'})
    assert wp._NOODLE_SCAN_LOCK.acquire(blocking=False)
    try:
        resp = client.post('/api/trading/scanner/noodle-refresh')
        assert resp.status_code == 409
        body = resp.get_json()
        assert body['error'] == 'RefreshBusy'
        assert body['run'] == {'id': 7, 'status': 'running'}
    finally:
        wp._NOODLE_SCAN_LOCK.release()


# ── Commit 3: GET /noodle-progress ────────────────────────────────────────

def test_noodle_progress_route_returns_null_run_when_no_runs(client, noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    resp = client.get('/api/trading/scanner/noodle-progress')
    assert resp.status_code == 200
    assert resp.get_json() == {'run': None}


def test_noodle_progress_route_returns_newest_row(client, noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    t1 = time.time() - 100
    t2 = time.time() - 10
    noodle_db.execute(
        "INSERT INTO noodle_scan_runs (trigger, status, started_ts, updated_ts, done, errors, total) "
        "VALUES ('auto', 'done', ?, ?, 5, 0, 5)", (t1, t1))
    noodle_db.execute(
        "INSERT INTO noodle_scan_runs (trigger, status, started_ts, updated_ts, done, errors, total) "
        "VALUES ('manual', 'running', ?, ?, 2, 0, 5)", (t2, t2))
    noodle_db.commit()

    resp = client.get('/api/trading/scanner/noodle-progress')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['run']['trigger'] == 'manual'
    assert body['run']['status'] == 'running'
    assert body['run']['done'] == 2


def test_noodle_progress_route_derives_abandoned_after_300s(client, noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    old = time.time() - 301
    noodle_db.execute(
        "INSERT INTO noodle_scan_runs (trigger, status, started_ts, updated_ts, done, errors) "
        "VALUES ('manual', 'running', ?, ?, 1, 0)", (old, old))
    noodle_db.commit()

    resp = client.get('/api/trading/scanner/noodle-progress')
    body = resp.get_json()
    assert body['run']['status'] == 'abandoned'

    # Derived only, never stored - the row itself stays 'running' so a
    # later poll can still see it as such if this read merely raced a
    # progress write rather than the scan actually having died.
    row = noodle_db.execute("SELECT status FROM noodle_scan_runs").fetchone()
    assert row['status'] == 'running'


def test_noodle_progress_route_stays_running_at_299s(client, noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    recent = time.time() - 299
    noodle_db.execute(
        "INSERT INTO noodle_scan_runs (trigger, status, started_ts, updated_ts, done, errors) "
        "VALUES ('manual', 'running', ?, ?, 1, 0)", (recent, recent))
    noodle_db.commit()

    resp = client.get('/api/trading/scanner/noodle-progress')
    body = resp.get_json()
    assert body['run']['status'] == 'running'
