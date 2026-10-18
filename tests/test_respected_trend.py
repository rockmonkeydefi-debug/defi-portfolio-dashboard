"""Landing 50 (Oct 17): respected trend columns on noodle_state.

Glenn's rulings (SPEC_respected_trend_test.md): a trend stays intact until
TWO CONSECUTIVE candles close beyond its far edge (one close beyond, or a
wick through that closes back, does not end it); a respected TAG is a pullback
into the band that holds followed by a new run high (bullish) or low
(bearish); the columns are informational (a watch list), not entry triggers;
the noodle `state` keeps flipping on one close. src/engines/respected_trend
gives the current run's direction, tag count and latest tag; the scan stores
it in four respect_* columns on the 1h / 4h / 12h / 1d rows (1w stays NULL);
the noodle-state route returns them. Fixture conventions copy
test_doc_trend.py (no cross-file fixture imports).

Landing 50b (Oct 18): the detector also counts the run's closes beyond the
far edge (`breaks`), stored as respect_breaks, because Glenn does not want a
timeframe listed as respected once its run has two or more of them.
"""
import sqlite3
import threading
import uuid

import src.engines.respected_trend as rt
import src.storage.portfolio_db as portfolio_db
from src.engines.respected_trend import compute_respected_trend

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import pytest

RESPECT_COLUMNS = ('respect_dir', 'respect_tags', 'respect_last_ts', 'respect_unbounded', 'respect_breaks')
T0 = 1_699_999_200          # a whole hour (and a whole 4h bucket) in unix seconds
STEP = 3600
UPPER, LOWER = 110.0, 90.0


def _bars(closes, step, t0=T0):
    return [{'open': c, 'high': c + 1.0, 'low': c - 1.0, 'close': c, 'volume': 10.0,
             'time': t0 + i * step} for i, c in enumerate(closes)]


def _down_then_up(n_down, n_up, start=100.0, step=0.1):
    down = [start - step * i for i in range(n_down)]
    low = down[-1]
    return down + [low + step * (i + 1) for i in range(n_up)]


@pytest.fixture
def fixed_bands(monkeypatch):
    """Bands pinned at 90 / 110 so each case is written by hand."""
    monkeypatch.setattr(rt, 'ema', lambda values, period: [1.0] * len(values))
    monkeypatch.setattr(rt, 'atr', lambda candles, period: [1.0] * len(candles))
    monkeypatch.setattr(rt, '_compute_bands',
                        lambda e, a, m, u: ([UPPER] * len(e), [LOWER] * len(e)))


# Closes with high = close + 1 and low = close - 1.
BULL_TWO_TAGS = [100, 112, 114, 116, 109, 118, 108, 120]


# -- the engine ----------------------------------------------------------

def test_two_closes_above_start_a_bullish_run_and_pullbacks_that_hold_are_tags(fixed_bands):
    bars = _bars(BULL_TWO_TAGS, STEP)
    out = compute_respected_trend(bars)
    assert out == {'dir': 'BULLISH', 'tags': 2, 'last_ts': bars[7]['time'], 'unbounded': True, 'breaks': 0}


def test_the_first_tag_is_dated_by_the_bar_that_makes_the_new_high(fixed_bands):
    bars = _bars(BULL_TWO_TAGS[:6], STEP)
    out = compute_respected_trend(bars)
    assert out['tags'] == 1 and out['last_ts'] == bars[5]['time']


def test_a_pullback_without_a_new_high_is_not_a_tag(fixed_bands):
    out = compute_respected_trend(_bars([100, 112, 114, 116, 109, 111, 113], STEP))
    assert out['dir'] == 'BULLISH' and out['tags'] == 0 and out['last_ts'] is None


def test_equalling_the_run_high_is_not_a_new_high(fixed_bands):
    # Bar 5 closes at 116 with a high of 117, the run high so far.
    out = compute_respected_trend(_bars([100, 112, 114, 116, 109, 116], STEP))
    assert out['dir'] == 'BULLISH' and out['tags'] == 0


def test_the_bar_that_spikes_to_a_new_high_is_not_also_the_pullback(fixed_bands):
    # The last bar closes inside the band (109) but its high is 130: a rejection, not a tag.
    bars = _bars([100, 112, 114, 116, 109], STEP)
    bars[-1]['high'] = 130.0
    out = compute_respected_trend(bars)
    assert out['dir'] == 'BULLISH' and out['tags'] == 0


def test_a_pullback_bar_followed_by_a_new_high_bar_is_a_tag(fixed_bands):
    bars = _bars([100, 112, 114, 116, 109, 109], STEP)
    bars[-1]['high'] = 130.0
    out = compute_respected_trend(bars)
    assert out['tags'] == 1 and out['last_ts'] == bars[5]['time']


def test_after_a_tag_the_next_one_needs_price_clear_of_the_band_again(fixed_bands):
    # Bar 5 tags and closes inside the band; bar 6 makes another high from inside: no second tag.
    bars = _bars([100, 112, 114, 116, 109, 109, 109], STEP)
    bars[5]['high'] = 130.0
    bars[6]['high'] = 135.0
    assert compute_respected_trend(bars)['tags'] == 1
    # Clear again (bar 6 closes above the band), pull back (bar 7), new high (bar 8): second tag.
    bars = _bars([100, 112, 114, 116, 109, 109, 120, 109, 109], STEP)
    bars[5]['high'] = 130.0
    bars[6]['high'] = 131.0
    bars[8]['high'] = 140.0
    assert compute_respected_trend(bars)['tags'] == 2


def test_one_close_beyond_the_far_edge_does_not_end_the_run(fixed_bands):
    out = compute_respected_trend(_bars(BULL_TWO_TAGS + [85, 115], STEP))
    assert out['dir'] == 'BULLISH' and out['tags'] == 2 and out['breaks'] == 1


def test_a_wick_through_the_far_edge_that_closes_back_does_not_end_the_run(fixed_bands):
    bars = _bars(BULL_TWO_TAGS + [105], STEP)
    bars[-1]['low'] = 80.0
    out = compute_respected_trend(bars)
    assert out['dir'] == 'BULLISH' and out['tags'] == 2 and out['breaks'] == 0


def test_two_consecutive_closes_beyond_the_far_edge_flip_and_reset(fixed_bands):
    bars = _bars(BULL_TWO_TAGS + [85, 84], STEP)
    out = compute_respected_trend(bars)
    assert out == {'dir': 'BEARISH', 'tags': 0, 'last_ts': None, 'unbounded': False, 'breaks': 0}


def test_two_closes_beyond_that_are_not_consecutive_do_not_flip(fixed_bands):
    out = compute_respected_trend(_bars(BULL_TWO_TAGS + [85, 100, 85, 100], STEP))
    assert out['dir'] == 'BULLISH' and out['breaks'] == 2


def test_a_close_on_the_far_edge_is_not_beyond_it(fixed_bands):
    out = compute_respected_trend(_bars(BULL_TWO_TAGS + [90, 100], STEP))
    assert out['dir'] == 'BULLISH' and out['breaks'] == 0


def test_a_flip_resets_the_count_and_a_bearish_run_counts_closes_above(fixed_bands):
    closes = BULL_TWO_TAGS + [85, 100, 85, 84]          # breaks 1 and 2, then two closes below: flip
    out = compute_respected_trend(_bars(closes, STEP))
    assert out['dir'] == 'BEARISH' and out['breaks'] == 0
    out = compute_respected_trend(_bars(closes + [91, 112, 100], STEP))    # one close above the upper band
    assert out['dir'] == 'BEARISH' and out['breaks'] == 1
    out = compute_respected_trend(_bars(closes + [91, 110, 100], STEP))    # on the upper band: not beyond
    assert out['dir'] == 'BEARISH' and out['breaks'] == 0


def test_bearish_mirror(fixed_bands):
    bars = _bars([100, 88, 86, 84, 91, 82], STEP)
    out = compute_respected_trend(bars)
    assert out == {'dir': 'BEARISH', 'tags': 1, 'last_ts': bars[5]['time'], 'unbounded': True, 'breaks': 0}


def test_confirm_one_flips_on_a_single_close(fixed_bands):
    out = compute_respected_trend(_bars(BULL_TWO_TAGS + [85], STEP), confirm=1)
    assert out['dir'] == 'BEARISH'
    assert rt.RESPECT_CONFIRM_CLOSES == 2


def test_no_run_yet_or_no_bars_says_nothing(fixed_bands):
    empty = {'dir': None, 'tags': None, 'last_ts': None, 'unbounded': None, 'breaks': None}
    assert compute_respected_trend([]) == empty
    assert compute_respected_trend(None) == empty
    assert compute_respected_trend(_bars([100, 101, 99, 100, 102], STEP)) == empty
    assert compute_respected_trend(_bars([100, 112, 100], STEP)) == empty    # one close above only


def test_too_few_bars_for_the_bands_says_nothing():
    out = compute_respected_trend(_bars([100.0 + i for i in range(20)], STEP))
    assert out == {'dir': None, 'tags': None, 'last_ts': None, 'unbounded': None, 'breaks': None}


def test_real_bands_a_steady_climb_is_one_bullish_run_without_tags():
    out = compute_respected_trend(_bars([100.0 + 0.5 * i for i in range(300)], STEP))
    assert out['dir'] == 'BULLISH' and out['tags'] == 0 and out['unbounded'] is True and out['breaks'] == 0


def test_real_bands_a_fall_after_a_climb_is_a_seen_flip():
    closes = [100.0 + 0.5 * i for i in range(200)] + [200.0 - 1.5 * i for i in range(120)]
    out = compute_respected_trend(_bars(closes, STEP))
    assert out['dir'] == 'BEARISH' and out['unbounded'] is False


def test_the_noodle_state_still_flips_on_one_close():
    """A series where one close beyond the lower band flips the noodle but not the respected run."""
    from src.engines.noodle_bands import compute_noodle_state
    closes = [100.0 + 0.5 * i for i in range(120)]
    bars = _bars(closes + [closes[-1] - 40.0], STEP)
    noodle = compute_noodle_state(bars)
    assert noodle['state'] == 'BEARISH'
    assert compute_respected_trend(bars)['dir'] == 'BULLISH'


# -- the migration -------------------------------------------------------

def _cols(path):
    conn = sqlite3.connect(path)
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(noodle_state)")}
    finally:
        conn.close()


def test_init_db_adds_the_respect_columns_and_twice_is_a_noop(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(portfolio_db, 'get_db_path', lambda: path)
    portfolio_db.init_db()
    portfolio_db.init_db()
    assert set(RESPECT_COLUMNS) <= _cols(path)


def test_upgrade_keeps_existing_rows_and_leaves_the_new_columns_null(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(portfolio_db, 'get_db_path', lambda: path)
    portfolio_db.init_db()
    conn = sqlite3.connect(path)
    for col in RESPECT_COLUMNS:                  # back to the pre-Landing 50 table
        conn.execute(f"ALTER TABLE noodle_state DROP COLUMN {col}")
    conn.execute("INSERT INTO noodle_state (symbol, timeframe, state, upper_band, computed_at, doc_ema_fast) "
                 "VALUES ('ETH', '4h', 'BULLISH', 110.0, '2026-10-17T00:00:00+00:00', 99.5)")
    conn.commit()
    conn.close()
    assert not set(RESPECT_COLUMNS) & _cols(path)

    portfolio_db.init_db()

    assert set(RESPECT_COLUMNS) <= _cols(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM noodle_state WHERE symbol='ETH'").fetchone()
    conn.close()
    assert row['state'] == 'BULLISH' and row['upper_band'] == 110.0 and row['doc_ema_fast'] == 99.5
    assert all(row[c] is None for c in RESPECT_COLUMNS)


def test_upgrade_from_landing_50_adds_respect_breaks_and_keeps_the_row(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(portfolio_db, 'get_db_path', lambda: path)
    portfolio_db.init_db()
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE noodle_state DROP COLUMN respect_breaks")     # the Landing 50 table
    conn.execute("INSERT INTO noodle_state (symbol, timeframe, state, computed_at, respect_dir, respect_tags, "
                 "respect_last_ts, respect_unbounded) VALUES "
                 "('ETH', '4h', 'BULLISH', '2026-10-18T00:00:00+00:00', 'BULLISH', 3, 1760000000.0, 0)")
    conn.commit()
    conn.close()
    assert 'respect_breaks' not in _cols(path)

    portfolio_db.init_db()

    assert 'respect_breaks' in _cols(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM noodle_state WHERE symbol='ETH'").fetchone()
    conn.close()
    assert row['respect_dir'] == 'BULLISH' and row['respect_tags'] == 3
    assert row['respect_last_ts'] == 1760000000.0 and row['respect_unbounded'] == 0
    assert row['respect_breaks'] is None


# -- the scan and the route ---------------------------------------------

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
        doc_ema_fast REAL,
        doc_ema_slow REAL,
        doc_cross_state TEXT,
        doc_cross_ts REAL,
        doc_cross_unbounded INTEGER,
        respect_dir TEXT,
        respect_tags INTEGER,
        respect_last_ts REAL,
        respect_unbounded INTEGER,
        respect_breaks INTEGER,
        UNIQUE(symbol, timeframe)
    )
"""

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


@pytest.fixture
def noodle_db(monkeypatch):
    uri = f"file:respected_trend_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    keepalive.row_factory = sqlite3.Row
    keepalive.executescript(NOODLE_STATE_SCHEMA)
    keepalive.executescript(NOODLE_SCAN_RUNS_SCHEMA)
    keepalive.commit()

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
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


def test_scan_stores_the_respected_trend_on_four_rows_and_not_on_1w(noodle_db, tmp_path, monkeypatch):
    monkeypatch.setattr(wp, "_SCANNER_SETTINGS_PATH", str(tmp_path / "scanner_settings.json"))
    monkeypatch.setattr(wp, '_hl_fetch_top_volume', lambda n=None, limit=None: [
        {'name': 'ETH', 'symbol': 'ETH-USDT', 'volume_24h': 1000.0, 'price': 100.0,
         'asset_type': 'crypto'}])
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    dailies_deep = _bars(_down_then_up(450, 251), 86400)
    h1_deep = _bars(_down_then_up(1700, 1101, step=0.01), 3600)
    h12 = _bars(_down_then_up(180, 121, step=0.2), 43200)
    monkeypatch.setattr(wp, '_hl_fetch_candles',
                        lambda coin, interval, limit=200: {'1d': dailies_deep, '12h': h12, '1h': h1_deep}[interval])

    payload, status = wp._run_noodle_scan_body()
    assert status == 200 and payload['scanned'] == 1 and payload['errors'] == 0

    rows = {r['timeframe']: dict(r) for r in noodle_db.execute(
        "SELECT * FROM noodle_state WHERE symbol='ETH'").fetchall()}
    old_dailies = dailies_deep[-301:]
    old_h1 = h1_deep[-1440:]
    expected_inputs = {
        '1d': old_dailies[:-1],
        '12h': h12[:-1],
        '4h': wp._h4_from_h1(old_h1, limit=360)[:-1],
        '1h': old_h1[:-1],
    }
    seen_a_run = False
    for tf, closed in expected_inputs.items():
        exp = compute_respected_trend(closed, slow=28, atr_length=14, band_multiplier=0.011875, use_atr=True)
        r = rows[tf]
        assert r['respect_dir'] == exp['dir'], tf
        assert r['respect_tags'] == exp['tags'], tf
        assert r['respect_last_ts'] == exp['last_ts'], tf
        assert r['respect_unbounded'] == (int(exp['unbounded']) if exp['unbounded'] is not None else None), tf
        assert r['respect_breaks'] == exp['breaks'], tf
        seen_a_run = seen_a_run or exp['dir'] is not None
        assert r['state'] == wp.compute_noodle_state(closed)['state'], tf     # the noodle state is unchanged
    assert seen_a_run
    assert all(rows['1w'][c] is None for c in RESPECT_COLUMNS)


def test_route_returns_the_respect_columns(client, noodle_db, monkeypatch):
    monkeypatch.setattr(wp, '_maybe_kick_noodle_auto_refresh', lambda: False)
    monkeypatch.setattr(wp, '_hl_refresh_universes', lambda force=False: None)
    noodle_db.execute(
        "INSERT INTO noodle_state (symbol, timeframe, state, computed_at, respect_dir, respect_tags, "
        "respect_last_ts, respect_unbounded, respect_breaks) VALUES "
        "('ETH', '4h', 'BULLISH', '2026-10-17T00:00:00+00:00', 'BULLISH', 3, 1760000000.0, 0, 1)")
    noodle_db.execute(
        "INSERT INTO noodle_state (symbol, timeframe, state, computed_at, respect_dir, respect_tags, "
        "respect_last_ts, respect_unbounded, respect_breaks) VALUES "
        "('ETH', '1d', 'BEARISH', '2026-10-17T00:00:00+00:00', 'BEARISH', 0, NULL, 1, 0)")
    noodle_db.execute(
        "INSERT INTO noodle_state (symbol, timeframe, state, computed_at) VALUES "
        "('ETH', '1w', 'BULLISH', '2026-10-17T00:00:00+00:00')")
    noodle_db.commit()
    resp = client.get('/api/trading/scanner/noodle-state')
    assert resp.status_code == 200
    tfs = resp.get_json()['symbols'][0]['timeframes']
    assert tfs['4h']['respect_dir'] == 'BULLISH' and tfs['4h']['respect_tags'] == 3
    assert tfs['4h']['respect_last_ts'] == 1760000000.0 and tfs['4h']['respect_unbounded'] is False
    assert tfs['1d']['respect_dir'] == 'BEARISH' and tfs['1d']['respect_tags'] == 0
    assert tfs['1d']['respect_last_ts'] is None and tfs['1d']['respect_unbounded'] is True
    assert tfs['4h']['respect_breaks'] == 1 and tfs['1d']['respect_breaks'] == 0
    assert all(tfs['1w'][c] is None for c in RESPECT_COLUMNS)


def test_a_failing_detector_leaves_the_noodle_rows_intact(noodle_db, tmp_path, monkeypatch):
    monkeypatch.setattr(wp, "_SCANNER_SETTINGS_PATH", str(tmp_path / "scanner_settings.json"))
    monkeypatch.setattr(wp, '_hl_fetch_top_volume', lambda n=None, limit=None: [
        {'name': 'ETH', 'symbol': 'ETH-USDT', 'volume_24h': 1000.0, 'price': 100.0,
         'asset_type': 'crypto'}])
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    series = {'1d': _bars(_down_then_up(450, 251), 86400),
              '12h': _bars(_down_then_up(180, 121, step=0.2), 43200),
              '1h': _bars(_down_then_up(1700, 1101, step=0.01), 3600)}
    monkeypatch.setattr(wp, '_hl_fetch_candles', lambda coin, interval, limit=200: series[interval])

    def boom(*a, **k):
        raise RuntimeError('boom')

    monkeypatch.setattr(wp, 'compute_respected_trend', boom)
    payload, status = wp._run_noodle_scan_body()
    assert status == 200 and payload['scanned'] == 1 and payload['errors'] == 0
    rows = noodle_db.execute("SELECT * FROM noodle_state WHERE symbol='ETH'").fetchall()
    assert len(rows) == 5
    assert all(r['state'] is not None for r in rows)
    assert all(r[c] is None for r in rows for c in RESPECT_COLUMNS)
