"""TxFlow in the Trends scan (Landing 53): _run_noodle_scan_body's TxFlow
phase, the match table, and what GET /api/trading/scanner/noodle-state says
about it.

TxFlow's info API is a fake `_txflow_post` that serves spotMeta and
candleSnapshot from made-up prices and volumes (the real function is blocked
in tests/conftest.py); the Hyperliquid side is the same fake universe and
candle series the other scan tests use, with the real indicator. Fixture
convention: the shared-cache in-memory SQLite + hand-rolled schema of
test_noodle_auto_refresh.py, copied (no cross-file fixture imports).

Covered: a TxFlow-only market above the $50k floor is scanned and stored as
"txflow:<NAME>" (five timeframes, the same columns as any row); under the
floor it is not; names TxFlow shares with Hyperliquid (aliases, 1000X = kX)
are tagged, not stored; a same-name market at a different price (QNT) is
TxFlow's own; a missing price creates no duplicate row; spotMeta failing, a
Hyperliquid list too short to match, five calls failing in a row, one
failing market; the stale-row sweep and when it does not run; progress
(done + errors = total); the match table's reuse inside a day and its JSON
file; the pacing / retry call; the route's asset_class and txflow_name.
"""
import json
import math
import os
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
import txflow_markets as tm

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
        respect_since REAL,
        respect_losses INTEGER,
        respect_ranging_since REAL,
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

TIMEFRAMES = {'1w', '1d', '12h', '4h', '1h'}
STEP_MS = {'1h': 3_600_000, '4h': 14_400_000, '12h': 43_200_000, '1d': 86_400_000}
HL_STEP = {'1w': 604800, '1d': 86400, '12h': 43200, '4h': 14400, '1h': 3600}

# Hyperliquid perps (the scan's list): name, kind, mark price.
HL_PERPS = [('BTC', 'crypto', 100000.0), ('ETH', 'crypto', 4000.0), ('kBONK', 'crypto', 0.025),
            ('GOLD', 'tradfi', 2400.0), ('QNT', 'tradfi', 38.2), ('XRP', 'crypto', None)]

# TxFlow: price per token (made up) and base volume per hourly bar.
TX_PRICE = {'BTC': 100050.0, 'ETH': 4010.0, '1000BONK': 0.0251, 'XAU': 2405.0, 'QNT': 198.0,
            'QNTX': 38.25, 'XRP': 2.2, 'COTI': 0.1, 'BAT': 0.3, 'LOWVOL': 1.0}
TX_VOLBAR = {'COTI': 100_000.0, 'BAT': 40_000.0, 'QNT': 40_000.0, 'LOWVOL': 1.0}
TOKENS = ['BTC', 'ETH', '1000BONK', 'XAU', 'QNT', 'QNTX', 'XRP', 'USDC', 'XAUT',
          'COTI', 'BAT', 'LOWVOL', 'RAY', 'RAY']


@pytest.fixture
def noodle_db(monkeypatch):
    uri = f"file:noodle_txflow_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    keepalive.row_factory = sqlite3.Row
    keepalive.executescript(NOODLE_STATE_SCHEMA)
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


class FakeTxflow:
    """A stand-in for TxFlow's info API (the `_txflow_post` signature)."""

    def __init__(self, tokens=TOKENS):
        self.tokens = list(tokens)
        self.calls = []
        self.spot_error = None
        self.fail = {}          # coin -> exception (every candle call for it)
        self.fail_all_candles = None
        self.shift_ms = {}      # coin -> how long ago its newest bar is (a market that has not traded lately)
        self.volbar = {}        # coin -> volume per hourly bar, over TX_VOLBAR
        self.raw = {}           # coin -> a raw answer to give instead of bars

    def __call__(self, body):
        self.calls.append(body)
        kind = body['type']
        if kind == 'spotMeta':
            if self.spot_error:
                raise self.spot_error
            return {'tokens': [{'name': n, 'index': i} for i, n in enumerate(self.tokens)]}
        assert kind == 'candleSnapshot', body
        req = body['req']
        coin = req['coin']
        if self.fail_all_candles:
            raise self.fail_all_candles
        if coin in self.fail:
            raise self.fail[coin]
        if coin in self.raw:
            return self.raw[coin]
        ms = STEP_MS[req['interval']]
        limit = (req['endTime'] - req['startTime']) // ms
        end = req['endTime'] - self.shift_ms.get(coin, 0)
        end -= end % ms
        base = TX_PRICE.get(coin, 1.0)
        vol = self.volbar.get(coin, TX_VOLBAR.get(coin, 500.0))
        out = []
        for i in range(limit):
            t = end - (limit - 1 - i) * ms
            px = base * (1 + 0.1 * math.sin(i / 15.0))
            out.append({'t': t, 'T': t + ms - 1, 's': coin, 'i': req['interval'],
                        'o': str(px), 'h': str(px * 1.01), 'l': str(px * 0.99), 'c': str(px * 1.001),
                        'v': str(vol / max(px, 1e-9)), 'n': 5})
        return out

    def candle_calls(self, interval=None):
        return [c for c in self.calls if c['type'] == 'candleSnapshot'
                and (interval is None or c['req']['interval'] == interval)]


def _hl_series(coin, interval, limit):
    step = HL_STEP[interval]
    end = int(time.time())
    end -= end % step
    out = []
    for i in range(limit):
        ts = end - (limit - 1 - i) * step
        base = 100.0 * (1 + 0.1 * math.sin(i / 11.0))
        out.append({'open': base, 'high': base + 1.0, 'low': base - 1.0, 'close': base + 0.2,
                    'volume': 10.0, 'time': ts})
    return out


def _setup(monkeypatch, tmp_path, noodle_db, hl_perps=HL_PERPS, tokens=TOKENS):
    monkeypatch.setattr(wp, "_SCANNER_SETTINGS_PATH", str(tmp_path / "scanner_settings.json"))
    universe = [{'name': n, 'symbol': n + '-USDT', 'volume_24h': 1e6 - i, 'price': p, 'asset_type': k}
                for i, (n, k, p) in enumerate(hl_perps)]
    monkeypatch.setattr(wp, '_hl_fetch_top_volume', lambda n=None, limit=None: universe)
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    monkeypatch.setattr(wp, '_hl_fetch_candles', _hl_series)
    monkeypatch.setattr(wp, 'TXFLOW_MIN_HL_NAMES', 2)
    monkeypatch.setattr(wp, 'TXFLOW_MIN_HL_TRADFI', 1)
    monkeypatch.setattr(wp, '_TXFLOW_MARKETS',
                        {'tokens': None, 'tokens_at': 0.0, 'match': None, 'file_loaded': False})
    fake = FakeTxflow(tokens)
    monkeypatch.setattr(wp, '_txflow_post', fake)
    return fake


def _recent(days=1):
    """An ISO computed_at inside the 14-day age retirement."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _rows(db, symbol):
    return {r['timeframe']: dict(r) for r in
            db.execute("SELECT * FROM noodle_state WHERE symbol=?", (symbol,)).fetchall()}


def _symbols(db):
    return {r['symbol'] for r in db.execute("SELECT DISTINCT symbol FROM noodle_state").fetchall()}


def _last_run(db):
    return dict(db.execute("SELECT * FROM noodle_scan_runs ORDER BY id DESC LIMIT 1").fetchone())


# ── scanned, stored, tagged ─────────────────────────────────────────────

def test_txflow_only_markets_above_the_floor_are_stored_with_the_prefix(noodle_db, tmp_path, monkeypatch):
    fake = _setup(monkeypatch, tmp_path, noodle_db)
    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['errors'] == 0
    tx = payload['txflow']
    assert tx['ran'] and tx['complete']
    # TxFlow-only: COTI, BAT (40k a bar = ~960k a day, over), LOWVOL (under), RAY, QNT (a different asset
    # from xyz's QNT). RAY has no volume entry: 500 a bar x 24 = 12k, under the floor.
    assert tx['candidates'] == 5
    assert tx['written'] == 3            # COTI, BAT, QNT
    assert tx['skipped'] == 2            # LOWVOL, RAY
    assert tx['failed'] == 0
    assert _symbols(noodle_db) == {'BTC', 'ETH', 'kBONK', 'GOLD', 'QNT', 'XRP',
                                   'txflow:COTI', 'txflow:BAT', 'txflow:QNT'}
    rows = _rows(noodle_db, 'txflow:COTI')
    assert set(rows) == TIMEFRAMES
    for r in rows.values():
        assert r['state'] in ('BULLISH', 'BEARISH', 'WARMUP')
        assert r['computed_at']
    one_h = rows['1h']
    assert one_h['volume_24h'] == pytest.approx(24 * 100_000.0 * 1.001, rel=0.02)   # volume x close summed
    assert one_h['price'] > 0                                       # the last close, the forming bar included
    # Candle depth asked of TxFlow, per interval, under its caps.
    limits = {c['req']['interval']: (c['req']['endTime'] - c['req']['startTime']) // STEP_MS[c['req']['interval']]
              for c in fake.candle_calls() if c['req']['coin'] == 'COTI'}
    assert limits == {'1h': 2800, '1d': 700, '12h': 300}


def test_tagged_markets_are_not_stored_as_txflow_rows_and_the_table_holds_the_tags(noodle_db, tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, noodle_db)
    wp._run_noodle_scan_body()
    assert wp._txflow_match_tags() == {'BTC': 'BTC', 'ETH': 'ETH', 'KBONK': '1000BONK',
                                       'GOLD': 'XAU', 'QNT': 'QNTX'}
    for name in ('txflow:BTC', 'txflow:ETH', 'txflow:1000BONK', 'txflow:XAU', 'txflow:QNTX',
                 'txflow:USDC', 'txflow:XAUT'):
        assert name not in _symbols(noodle_db)


def test_a_missing_hyperliquid_price_makes_no_txflow_row_and_no_tag(noodle_db, tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, noodle_db)
    wp._run_noodle_scan_body()
    assert 'XRP' not in wp._txflow_match_tags()
    assert 'txflow:XRP' not in _symbols(noodle_db)


def test_txflow_candles_feed_the_same_columns_as_a_hyperliquid_row(noodle_db, tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, noodle_db)
    wp._run_noodle_scan_body()
    hl_cols = set(next(iter(_rows(noodle_db, 'ETH').values())))
    tx_cols = set(next(iter(_rows(noodle_db, 'txflow:COTI').values())))
    assert hl_cols == tx_cols
    # The doc trend columns come from the 4h and 1d rows, as for any symbol.
    tx = _rows(noodle_db, 'txflow:COTI')
    assert tx['4h']['doc_ema_fast'] is not None and tx['1d']['doc_ema_fast'] is not None
    assert tx['1h']['doc_ema_fast'] is None


def test_progress_ends_with_done_plus_errors_equal_to_total(noodle_db, tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, noodle_db)
    payload, _ = wp._run_noodle_scan_body()
    run = _last_run(noodle_db)
    assert run['status'] == 'done'
    assert run['total'] == 6 + 3                      # six Hyperliquid perps + three stored TxFlow markets
    assert run['done'] + run['errors'] == run['total']
    assert payload['scanned'] == run['done']


# ── when TxFlow does not answer ─────────────────────────────────────────

def test_spotmeta_refused_leaves_hyperliquid_rows_counts_no_errors_and_no_sweep(noodle_db, tmp_path, monkeypatch, capsys):
    fake = _setup(monkeypatch, tmp_path, noodle_db)
    fake.spot_error = wp.TxflowHTTPError(403)
    noodle_db.execute("INSERT INTO noodle_state (symbol, timeframe, computed_at) VALUES ('txflow:OLD','1d',?)", (_recent(),))
    noodle_db.commit()
    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['errors'] == 0 and 'txflow' not in payload
    assert {'BTC', 'ETH', 'kBONK', 'GOLD', 'QNT', 'XRP'} <= _symbols(noodle_db)
    assert 'txflow:OLD' in _symbols(noodle_db)          # an outage never wipes TxFlow rows
    assert '[txflow-scan] skipped: spotMeta failed' in capsys.readouterr().out
    assert [c['type'] for c in fake.calls] == ['spotMeta']     # a 403 is not retried


def test_hyperliquid_list_too_short_skips_the_phase_without_a_call(noodle_db, tmp_path, monkeypatch, capsys):
    fake = _setup(monkeypatch, tmp_path, noodle_db)
    monkeypatch.setattr(wp, 'TXFLOW_MIN_HL_NAMES', 100)
    payload, _ = wp._run_noodle_scan_body()
    assert 'txflow' not in payload and payload['errors'] == 0
    assert not any('txflow:' in s for s in _symbols(noodle_db))
    assert 'Hyperliquid names' in capsys.readouterr().out
    assert [c['type'] for c in fake.calls] == ['spotMeta']     # no candle call to build a table on a short list


def test_five_failed_candle_calls_in_a_row_end_the_phase_and_skip_the_sweep(noodle_db, tmp_path, monkeypatch, capsys):
    tokens = ['BTC', 'ETH'] + [f'T{i}' for i in range(8)]
    fake = _setup(monkeypatch, tmp_path, noodle_db, tokens=tokens)
    # A table already built and fresh, so only the per-market candle calls can fail.
    monkeypatch.setitem(wp._TXFLOW_MARKETS, 'match', {'tags': {'BTC': 'BTC'}, 'only': [f'T{i}' for i in range(8)],
                                                       'built_at': time.time()})
    fake.fail_all_candles = wp.TxflowHTTPError(403)
    noodle_db.execute("INSERT INTO noodle_state (symbol, timeframe, computed_at) VALUES ('txflow:T3','1d',?)", (_recent(),))
    noodle_db.commit()
    payload, status = wp._run_noodle_scan_body()
    assert status == 200
    assert payload['errors'] == 0                        # an outage is not a symbol error
    assert payload['txflow']['complete'] is False
    assert len(fake.candle_calls()) == wp.TXFLOW_SCAN_BREAKER      # stopped after five, not eight
    assert 'txflow:T3' in _symbols(noodle_db)
    assert '5 TxFlow markets failed in a row' in capsys.readouterr().out
    run = _last_run(noodle_db)
    assert run['status'] == 'done' and run['done'] + run['errors'] == run['total']


def test_one_failing_market_is_isolated_and_keeps_its_last_good_row(noodle_db, tmp_path, monkeypatch):
    fake = _setup(monkeypatch, tmp_path, noodle_db)
    for tf in ('1d', '1h'):
        noodle_db.execute("INSERT INTO noodle_state (symbol, timeframe, state, computed_at) "
                          "VALUES ('txflow:BAT',?, 'BULLISH', ?)", (tf, _recent()))
    noodle_db.commit()
    fake.fail['BAT'] = ValueError('HTTP 500')
    payload, _ = wp._run_noodle_scan_body()
    tx = payload['txflow']
    assert payload['errors'] == 0 and tx['complete'] is True
    assert tx['written'] == 2 and tx['failed'] == 0           # COTI and QNT; BAT's failed fetch is a log line
    assert {r['state'] for r in _rows(noodle_db, 'txflow:BAT').values()} == {'BULLISH'}   # not swept, not rewritten
    assert 'txflow:COTI' in _symbols(noodle_db)


def test_a_compute_failure_on_one_market_is_an_error_and_rolls_back_its_rows(noodle_db, tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, noodle_db)

    def store(conn, symbol, *a, **k):
        if symbol == 'txflow:BAT':
            conn.execute("INSERT INTO noodle_state (symbol, timeframe) VALUES ('txflow:BAT', '1w')")   # a partial write
            raise RuntimeError('boom')
        return orig_store(conn, symbol, *a, **k)

    orig_store = wp._noodle_store_symbol
    monkeypatch.setattr(wp, '_noodle_store_symbol', store)
    payload, _ = wp._run_noodle_scan_body()
    assert payload['errors'] == 1 and payload['txflow']['failed'] == 1
    # The partial insert was rolled back: BAT has no orphaned one-timeframe row.
    assert _rows(noodle_db, 'txflow:BAT') == {}
    assert 'txflow:COTI' in _symbols(noodle_db)
    run = _last_run(noodle_db)
    assert run['done'] + run['errors'] == run['total']


# ── the stale-row sweep ──────────────────────────────────────────────────

def test_sweep_removes_rows_for_markets_gone_under_the_floor_or_now_on_hyperliquid(noodle_db, tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, noodle_db)
    for sym in ('txflow:GONE', 'txflow:LOWVOL', 'txflow:ETH'):
        noodle_db.execute("INSERT INTO noodle_state (symbol, timeframe, computed_at) VALUES (?, '1d', ?)",
                          (sym, _recent()))
    noodle_db.commit()
    payload, _ = wp._run_noodle_scan_body()
    assert payload['txflow']['swept'] == 3
    syms = _symbols(noodle_db)
    assert not {'txflow:GONE', 'txflow:LOWVOL', 'txflow:ETH'} & syms
    assert {'txflow:COTI', 'txflow:BAT'} <= syms


def test_sweep_never_touches_hyperliquid_rows(noodle_db, tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, noodle_db)
    for sym in ('TXFLOWX', 'kTXFLOW', 'TXFLOW'):          # near-miss names: none starts with "txflow:"
        noodle_db.execute("INSERT INTO noodle_state (symbol, timeframe, computed_at) VALUES (?, '1d', ?)",
                          (sym, _recent()))
    noodle_db.commit()
    wp._run_noodle_scan_body()
    assert {'TXFLOWX', 'kTXFLOW', 'TXFLOW'} <= _symbols(noodle_db)


# ── the match table ──────────────────────────────────────────────────────

def test_match_table_is_reused_inside_a_day_without_price_calls(noodle_db, tmp_path, monkeypatch):
    fake = _setup(monkeypatch, tmp_path, noodle_db)
    wp._run_noodle_scan_body()
    first = fake.candle_calls('1h')
    price_checks = [c for c in first if (c['req']['endTime'] - c['req']['startTime']) // STEP_MS['1h'] == 3]
    assert {c['req']['coin'] for c in price_checks} == {'BTC', 'ETH', '1000BONK', 'XAU', 'QNT', 'QNTX', 'XRP'}
    n_before = len(fake.calls)
    wp._run_noodle_scan_body()
    second = fake.calls[n_before:]
    assert not [c for c in second if c['type'] == 'candleSnapshot'
                and (c['req']['endTime'] - c['req']['startTime']) // STEP_MS['1h'] == 3]   # none for the table
    assert wp._txflow_match_tags()['GOLD'] == 'XAU'


def test_match_table_older_than_a_day_is_rebuilt(noodle_db, tmp_path, monkeypatch):
    fake = _setup(monkeypatch, tmp_path, noodle_db)
    wp._run_noodle_scan_body()
    wp._TXFLOW_MARKETS['match']['built_at'] = time.time() - wp.TXFLOW_MATCH_TTL_SECONDS - 5
    n_before = len(fake.calls)
    wp._run_noodle_scan_body()
    assert any((c['req']['endTime'] - c['req']['startTime']) // STEP_MS['1h'] == 3
               for c in fake.calls[n_before:] if c['type'] == 'candleSnapshot')


def test_match_table_is_saved_beside_the_settings_file_and_read_back_after_a_restart(noodle_db, tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, noodle_db)
    wp._run_noodle_scan_body()
    path = tmp_path / 'txflow_match.json'
    assert path.exists() and not (tmp_path / 'txflow_match.json.tmp').exists()
    saved = json.loads(path.read_text())
    assert saved['tags']['GOLD'] == 'XAU' and 'COTI' in saved['only'] and saved['built_at'] > 0
    # A new process: memory empty, the file read once.
    monkeypatch.setattr(wp, '_TXFLOW_MARKETS', {'tokens': None, 'tokens_at': 0.0, 'match': None, 'file_loaded': False})
    assert wp._txflow_match_tags()['KBONK'] == '1000BONK'


def test_missing_or_corrupt_match_file_is_an_empty_table(noodle_db, tmp_path, monkeypatch):
    monkeypatch.setattr(wp, '_SCANNER_SETTINGS_PATH', str(tmp_path / 'scanner_settings.json'))
    monkeypatch.setattr(wp, '_TXFLOW_MARKETS', {'tokens': None, 'tokens_at': 0.0, 'match': None, 'file_loaded': False})
    assert wp._txflow_match_tags() == {}
    (tmp_path / 'txflow_match.json').write_text('{not json')
    monkeypatch.setattr(wp, '_TXFLOW_MARKETS', {'tokens': None, 'tokens_at': 0.0, 'match': None, 'file_loaded': False})
    assert wp._txflow_match_tags() == {}


def test_a_rebuild_that_hits_the_breaker_keeps_the_stored_table(noodle_db, tmp_path, monkeypatch, capsys):
    fake = _setup(monkeypatch, tmp_path, noodle_db)
    stale = {'tags': {'GOLD': 'XAU'}, 'only': ['COTI'], 'built_at': time.time() - wp.TXFLOW_MATCH_TTL_SECONDS - 10}
    monkeypatch.setitem(wp._TXFLOW_MARKETS, 'match', dict(stale))
    fake.fail_all_candles = wp.TxflowHTTPError(403)
    payload, status = wp._run_noodle_scan_body()
    assert status == 200 and payload['errors'] == 0
    assert payload['txflow']['complete'] is False
    assert wp._TXFLOW_MARKETS['match'] == stale
    assert 'match table not rebuilt' in capsys.readouterr().out


def test_a_new_scan_with_a_changed_token_list_drops_a_delisted_candidate(noodle_db, tmp_path, monkeypatch):
    fake = _setup(monkeypatch, tmp_path, noodle_db)
    wp._run_noodle_scan_body()
    assert 'txflow:BAT' in _symbols(noodle_db)
    fake.tokens = [t for t in TOKENS if t != 'BAT']
    wp._TXFLOW_MARKETS['tokens_at'] = 0.0          # spotMeta cache expired
    payload, _ = wp._run_noodle_scan_body()
    assert 'txflow:BAT' not in _symbols(noodle_db)
    assert payload['txflow']['swept'] == 1


# ── pacing and retry ─────────────────────────────────────────────────────

def test_a_429_is_retried_once_and_a_403_is_not(monkeypatch):
    calls = []
    answers = [wp.TxflowHTTPError(429), {'tokens': []}]

    def post(body):
        calls.append(body)
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(wp, '_txflow_post', post)
    assert wp._txflow_scan_call({'type': 'spotMeta'}) == {'tokens': []}
    assert len(calls) == 2

    calls.clear()
    answers[:] = [wp.TxflowHTTPError(403), {'tokens': []}]
    with pytest.raises(wp.TxflowHTTPError):
        wp._txflow_scan_call({'type': 'spotMeta'})
    assert len(calls) == 1

    calls.clear()
    answers[:] = [wp.TxflowHTTPError(503), wp.TxflowHTTPError(503)]
    with pytest.raises(wp.TxflowHTTPError):
        wp._txflow_scan_call({'type': 'spotMeta'})
    assert len(calls) == 2                      # one retry, then the error


def test_calls_are_spaced_by_the_pace(monkeypatch):
    monkeypatch.setattr(wp, 'TXFLOW_SCAN_PACE_SECONDS', 0.05)
    monkeypatch.setattr(wp, '_TXFLOW_PACE', {'next': 0.0})
    monkeypatch.setattr(wp, '_txflow_post', lambda body: {})
    t0 = time.monotonic()
    for _ in range(4):
        wp._txflow_scan_call({'type': 'spotMeta'})
    assert time.monotonic() - t0 >= 0.15 - 0.01     # three gaps of 0.05s


def test_txflow_http_error_is_the_old_value_error_with_a_status():
    e = wp.TxflowHTTPError(403)
    assert isinstance(e, ValueError) and str(e) == 'HTTP 403' and e.status == 403


# ── review fixes: partial lists, odd answers, quiet runs ──────────────────

def test_a_list_without_the_xyz_exchange_skips_the_phase_and_keeps_the_stored_table(noodle_db, tmp_path, monkeypatch, capsys):
    """A failed xyz fetch leaves main-exchange perps only: every TxFlow stock would look TxFlow-only."""
    fake = _setup(monkeypatch, tmp_path, noodle_db, hl_perps=[(n, k, p) for n, k, p in HL_PERPS if k == 'crypto'])
    stored = {'tags': {'GOLD': 'XAU'}, 'only': ['COTI'], 'built_at': time.time() - 100}
    monkeypatch.setitem(wp._TXFLOW_MARKETS, 'match', dict(stored))
    noodle_db.execute("INSERT INTO noodle_state (symbol, timeframe, computed_at) VALUES ('txflow:COTI','1d',?)", (_recent(),))
    noodle_db.commit()
    payload, _ = wp._run_noodle_scan_body()
    assert 'txflow' not in payload and payload['errors'] == 0
    assert 'looks partial' in capsys.readouterr().out
    assert [c['type'] for c in fake.calls] == ['spotMeta']
    assert wp._txflow_match_tags() == {'GOLD': 'XAU'}              # the table is untouched
    assert 'txflow:COTI' in _symbols(noodle_db)                    # and nothing is swept


def test_the_tradfi_guard_counts_only_perps(monkeypatch):
    universe = [{'symbol': 'NVDA-USDT', 'asset_type': 'tradfi'}, {'symbol': 'GOLD-USDC', 'asset_type': 'tradfi'},
                {'symbol': 'BTC-USDT', 'asset_type': 'crypto'}]
    assert wp._txflow_hl_tradfi_count(universe) == 1               # the spot pair and the crypto perp do not count
    assert wp._txflow_hl_tradfi_count(None) == 0
    assert wp.TXFLOW_MIN_HL_TRADFI == 5


def test_a_market_the_api_does_not_know_does_not_count_toward_the_breaker(noodle_db, tmp_path, monkeypatch):
    names = [f'T{i}' for i in range(7)]
    fake = _setup(monkeypatch, tmp_path, noodle_db, tokens=['BTC', 'ETH'] + names + ['COTI'])
    monkeypatch.setitem(wp._TXFLOW_MARKETS, 'match', {'tags': {'BTC': 'BTC'}, 'only': names + ['COTI'],
                                                       'built_at': time.time()})
    for n in names:
        fake.fail[n] = wp.TxflowHTTPError(404)                      # seven unknown markets in a row, then a good one
    payload, _ = wp._run_noodle_scan_body()
    tx = payload['txflow']
    assert tx['written'] == 1 and 'txflow:COTI' in _symbols(noodle_db)     # the scan went past the dead ones
    assert tx['complete'] is True and payload['errors'] == 0


def test_server_errors_on_every_market_still_trip_the_breaker(noodle_db, tmp_path, monkeypatch):
    names = [f'T{i}' for i in range(7)]
    fake = _setup(monkeypatch, tmp_path, noodle_db, tokens=['BTC', 'ETH'] + names + ['COTI'])
    monkeypatch.setitem(wp._TXFLOW_MARKETS, 'match', {'tags': {'BTC': 'BTC'}, 'only': names + ['COTI'],
                                                       'built_at': time.time()})
    for n in names:
        fake.fail[n] = wp.TxflowHTTPError(403)
    payload, _ = wp._run_noodle_scan_body()
    assert payload['txflow']['complete'] is False and payload['txflow']['written'] == 0
    assert 'txflow:COTI' not in _symbols(noodle_db)                 # never reached


def test_an_answer_in_an_unexpected_shape_is_a_failed_market_not_a_quiet_one(noodle_db, tmp_path, monkeypatch, capsys):
    names = [f'T{i}' for i in range(6)]
    fake = _setup(monkeypatch, tmp_path, noodle_db, tokens=['BTC', 'ETH'] + names)
    monkeypatch.setitem(wp._TXFLOW_MARKETS, 'match', {'tags': {'BTC': 'BTC'}, 'only': names, 'built_at': time.time()})
    noodle_db.execute("INSERT INTO noodle_state (symbol, timeframe, computed_at) VALUES ('txflow:T1','1d',?)", (_recent(),))
    noodle_db.commit()
    for n in names:
        fake.raw[n] = [{'time': 1, 'close': 2}]                     # a bar with other field names
    payload, _ = wp._run_noodle_scan_body()
    assert payload['txflow']['complete'] is False
    assert 'txflow:T1' in _symbols(noodle_db)                       # no sweep
    assert 'no usable bars' in capsys.readouterr().out


def test_no_market_above_the_floor_among_several_means_no_sweep(noodle_db, tmp_path, monkeypatch, capsys):
    """Candles in other units or an empty answer for everything look like 'every market is quiet'."""
    names = [f'T{i}' for i in range(6)]
    fake = _setup(monkeypatch, tmp_path, noodle_db, tokens=['BTC', 'ETH'] + names)
    monkeypatch.setitem(wp._TXFLOW_MARKETS, 'match', {'tags': {'BTC': 'BTC'}, 'only': names, 'built_at': time.time()})
    noodle_db.execute("INSERT INTO noodle_state (symbol, timeframe, computed_at) VALUES ('txflow:OLD','1d',?)", (_recent(),))
    noodle_db.commit()
    for n in names:
        fake.raw[n] = []
    payload, _ = wp._run_noodle_scan_body()
    tx = payload['txflow']
    assert tx['complete'] is False and tx['written'] == 0 and tx['skipped'] == 6 and tx['swept'] == 0
    assert 'txflow:OLD' in _symbols(noodle_db)
    assert 'no sweep: none of 6' in capsys.readouterr().out


def test_a_normal_run_with_a_few_quiet_markets_still_sweeps(noodle_db, tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, noodle_db)
    noodle_db.execute("INSERT INTO noodle_state (symbol, timeframe, computed_at) VALUES ('txflow:OLD','1d',?)", (_recent(),))
    noodle_db.commit()
    payload, _ = wp._run_noodle_scan_body()
    assert payload['txflow']['complete'] is True and payload['txflow']['swept'] == 1
    assert 'txflow:OLD' not in _symbols(noodle_db)


def test_a_price_from_a_market_that_has_not_traded_lately_is_unknown_and_asked_again_soon(noodle_db, tmp_path, monkeypatch):
    fake = _setup(monkeypatch, tmp_path, noodle_db)
    fake.shift_ms['ETH'] = 5 * 3_600_000                            # its newest bar opened five hours ago
    wp._run_noodle_scan_body()
    tags = wp._txflow_match_tags()
    assert 'ETH' not in tags and tags['BTC'] == 'BTC'                # no tag, and no TxFlow-only ETH row either
    assert 'txflow:ETH' not in _symbols(noodle_db)
    age = time.time() - wp._TXFLOW_MARKETS['match']['built_at']
    assert wp.TXFLOW_MATCH_TTL_SECONDS - wp.TXFLOW_MATCH_RETRY_SECONDS <= age < wp.TXFLOW_MATCH_TTL_SECONDS - wp.TXFLOW_MATCH_RETRY_SECONDS + 60


def test_a_missing_hyperliquid_price_alone_does_not_shorten_the_table_life(noodle_db, tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, noodle_db)                        # XRP has no Hyperliquid price: unknown, never fixed by asking again
    wp._run_noodle_scan_body()
    assert time.time() - wp._TXFLOW_MARKETS['match']['built_at'] < 60


def test_a_phase_that_raises_puts_the_run_total_back(noodle_db, tmp_path, monkeypatch, capsys):
    _setup(monkeypatch, tmp_path, noodle_db)

    def boom(conn, run_id, universe, hl_total, *a, **k):
        conn.execute("UPDATE noodle_scan_runs SET total=?, updated_ts=? WHERE id=?", (hl_total + 40, time.time(), run_id))
        conn.commit()
        raise RuntimeError('database is locked')
    monkeypatch.setattr(wp, '_noodle_txflow_phase', boom)
    payload, status = wp._run_noodle_scan_body()
    assert status == 200 and payload['errors'] == 0 and 'txflow' not in payload
    run = _last_run(noodle_db)
    assert run['status'] == 'done' and run['total'] == 6 and run['done'] + run['errors'] == run['total']
    assert '[txflow-scan] phase failed: RuntimeError' in capsys.readouterr().out


# ── the route ─────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    monkeypatch.setattr(wp, '_maybe_kick_noodle_auto_refresh', lambda: False)
    monkeypatch.setattr(wp, '_hl_refresh_universes', lambda force=False: None)
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _seed(db, symbol):
    for tf in ('1d', '4h'):
        db.execute("INSERT INTO noodle_state (symbol, timeframe, state, price, volume_24h, computed_at) "
                   "VALUES (?, ?, 'BULLISH', 1.0, 100.0, '2026-10-19T00:00:00+00:00')", (symbol, tf))
    db.commit()


def test_route_tags_txflow_rows_and_names_the_txflow_market(noodle_db, client, monkeypatch):
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, 'crypto', {'BTC': 'BTC', 'KBONK': 'kBONK'})
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, 'xyz', {'GOLD': 'xyz:GOLD', 'QNT': 'xyz:QNT'})
    monkeypatch.setattr(wp, '_TXFLOW_MARKETS', {'tokens': None, 'tokens_at': 0.0, 'file_loaded': True,
                        'match': {'tags': {'BTC': 'BTC', 'KBONK': '1000BONK', 'GOLD': 'XAU', 'QNT': 'QNTX'},
                                  'only': ['COTI', 'QNT'], 'built_at': time.time()}})
    for sym in ('BTC', 'kBONK', 'GOLD', 'QNT', 'DOGE', 'txflow:COTI', 'txflow:QNT'):
        _seed(noodle_db, sym)
    data = client.get('/api/trading/scanner/noodle-state').get_json()
    by = {s['symbol']: s for s in data['symbols']}
    assert (by['BTC']['asset_class'], by['BTC']['txflow_name']) == ('crypto', 'BTC')
    assert (by['kBONK']['asset_class'], by['kBONK']['txflow_name']) == ('crypto', '1000BONK')
    assert (by['GOLD']['asset_class'], by['GOLD']['txflow_name']) == ('tradfi', 'XAU')
    assert (by['QNT']['asset_class'], by['QNT']['txflow_name']) == ('tradfi', 'QNTX')   # xyz QNT, not TxFlow's QNT
    assert (by['txflow:COTI']['asset_class'], by['txflow:COTI']['txflow_name']) == ('txflow', 'COTI')
    assert (by['txflow:QNT']['asset_class'], by['txflow:QNT']['txflow_name']) == ('txflow', 'QNT')
    assert by['DOGE']['txflow_name'] is None


def test_route_without_a_match_table_still_names_txflow_only_rows(noodle_db, client, monkeypatch):
    monkeypatch.setattr(wp, '_TXFLOW_MARKETS', {'tokens': None, 'tokens_at': 0.0, 'match': None, 'file_loaded': True})
    for sym in ('BTC', 'txflow:COTI'):
        _seed(noodle_db, sym)
    by = {s['symbol']: s for s in client.get('/api/trading/scanner/noodle-state').get_json()['symbols']}
    assert by['BTC']['txflow_name'] is None
    assert by['txflow:COTI']['txflow_name'] == 'COTI' and by['txflow:COTI']['asset_class'] == 'txflow'


def test_route_survives_a_failing_match_table_read(noodle_db, client, monkeypatch):
    def boom():
        raise RuntimeError('disk')
    monkeypatch.setattr(wp, '_txflow_match_tags', boom)
    _seed(noodle_db, 'BTC')
    resp = client.get('/api/trading/scanner/noodle-state')
    assert resp.status_code == 200
    assert resp.get_json()['symbols'][0]['txflow_name'] is None


def test_other_noodle_readers_never_match_a_txflow_symbol(noodle_db):
    rows = {'TXFLOW:QNT': {'symbol': 'txflow:QNT'}}
    assert wp._noodle_symbol_match('QNT', rows) is None            # a spot QNT is not TxFlow's QNT
    assert wp._noodle_symbol_match('txflow:QNT', rows) == {'symbol': 'txflow:QNT'}


def test_the_scan_has_the_floor_and_depths_the_spec_rules():
    # Pins the values the spec and the Trends tooltips quote ("$50k", the depths, the breaker, the file name).
    assert wp.TXFLOW_SCAN_MIN_VOLUME == 50_000.0
    assert wp.TXFLOW_SCAN_CANDLE_LIMITS == {'1h': 2800, '12h': 300, '1d': 700}
    assert wp.TXFLOW_SCAN_BREAKER == 5
    assert os.path.basename(wp._txflow_match_path()) == 'txflow_match.json'
