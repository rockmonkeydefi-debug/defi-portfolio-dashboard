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
        alignment_bull INTEGER,
        alignment_bear INTEGER,
        basis_ema REAL,
        upper_band REAL,
        lower_band REAL,
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
    'flip_age_unbounded': False, 'alignment_bull': 3, 'alignment_bear': 0,
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
    assert set(rows.keys()) == {'1w', '1d', '12h'}
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
    monkeypatch.setattr(wp, '_spawn_noodle_scan_thread', lambda: recorder.append(True))
    now = datetime.now(timezone.utc).isoformat()
    _seed_row(noodle_db, 'BTC', '1d', now)

    stale = wp._maybe_kick_noodle_auto_refresh()
    assert stale is False
    assert recorder == []


def test_maybe_kick_noodle_auto_refresh_stale_row_spawns(noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    recorder = []
    monkeypatch.setattr(wp, '_spawn_noodle_scan_thread', lambda: recorder.append(True))
    old = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()   # default staleness = 6h
    _seed_row(noodle_db, 'BTC', '1d', old)

    stale = wp._maybe_kick_noodle_auto_refresh()
    assert stale is True
    assert recorder == [True]


def test_maybe_kick_noodle_auto_refresh_empty_table_spawns(noodle_db, tmp_path, monkeypatch):
    _default_scanner_settings_path(monkeypatch, tmp_path)
    recorder = []
    monkeypatch.setattr(wp, '_spawn_noodle_scan_thread', lambda: recorder.append(True))
    # No rows at all.

    stale = wp._maybe_kick_noodle_auto_refresh()
    assert stale is True
    assert recorder == [True]


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
    assert len(rows) == 3                          # GOODCOIN's all 3 timeframes intact, none dropped


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
    """FAILCOIN fails partway through its 3-timeframe loop - AFTER its '1w'
    row would already have been written (execute()'d, not yet committed)
    but BEFORE '1d'. Without a rollback in the except path, that dangling
    '1w' insert stays on the shared connection and gets flushed for free
    by LATERCOIN's own conn.commit() later in the same pass, leaving
    FAILCOIN with one orphaned row instead of zero. FAILCOIN is scanned
    first (universe order), so its three compute_noodle_state calls are
    globally calls #1-#3; failing on call #2 ('1d') reproduces exactly
    that after-first-write, before-second-write window."""
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
    assert {r['timeframe'] for r in later_rows} == {'1w', '1d', '12h'}


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
    assert len(rows) == 3
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
        'flip_age_unbounded': None, 'alignment_bull': None, 'alignment_bear': None,
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
