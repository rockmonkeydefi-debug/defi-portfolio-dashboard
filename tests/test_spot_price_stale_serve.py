"""Tests for _get_spot_price_stale_serve / _spawn_spot_price_refresh /
_spot_snapshot_upsert (Spot stale-serve 2/3) - the serve-stale-while-
refreshing layer above _get_spot_price_for_position, backed by the
spot_price_snapshot table (commit 1).

DB-backed tests use the tmp-path + monkeypatched get_db_path() pattern from
test_spot_price_snapshot_schema.py (init_db() against a real temp-file
SQLite, not a hand-rolled schema mirror). wp._get_spot_price_for_position and
wp._spawn_spot_price_refresh are monkeypatched at module level for
call-capture in most tests; the dedupe test (f) uses the REAL
_spawn_spot_price_refresh with a real background thread, polling for the
in-flight set to settle - mirroring test_stale_refresh_deduped /
test_stale_serve_returns_immediately_and_refreshes in test_custom_tokens.py,
the established precedent for testing this exact serve-stale shape.
"""
import time as _t
import threading
from datetime import datetime, timezone

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as _pdb

_BASE_NOW = 1_800_000_000.0  # arbitrary fixed epoch, used as _now everywhere


def _iso(epoch_seconds):
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


@pytest.fixture(autouse=True)
def _clean_module_state():
    """Mirrors test_spot_position_pricing.py's _clear_cache() convention:
    clear every module-level structure this test file touches, before AND
    after each test, so no test leaks dedupe/cache state into another."""
    wp._spot_snapshot_refresh_inflight.clear()
    yield
    wp._spot_snapshot_refresh_inflight.clear()


@pytest.fixture
def spot_db(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(_pdb, 'get_db_path', lambda: path)
    _pdb.init_db()
    return path


def _open(path):
    import sqlite3
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _seed_snapshot(path, position_key, price_usd, fetched_at):
    conn = _open(path)
    conn.execute(
        "INSERT INTO spot_price_snapshot (position_key, price_usd, fetched_at) VALUES (?, ?, ?)",
        (position_key, price_usd, fetched_at),
    )
    conn.commit()
    conn.close()


def _row_count(path):
    conn = _open(path)
    n = conn.execute("SELECT COUNT(*) AS n FROM spot_price_snapshot").fetchone()['n']
    conn.close()
    return n


def _pos(position_key='BTC'):
    return {'position_key': position_key, 'symbol': 'BTC', 'chain': '', 'contract_address': ''}


def _boom(*a, **k):
    raise AssertionError("must not be called on this path")


# ---------------------------------------------------------------------------
# a. manual source
# ---------------------------------------------------------------------------

def test_manual_source_returns_none_none_and_touches_nothing(spot_db, monkeypatch):
    monkeypatch.setattr(wp, '_get_spot_price_for_position', _boom)
    monkeypatch.setattr(wp, '_spawn_spot_price_refresh', _boom)

    result = wp._get_spot_price_stale_serve(_pos(), {'price_source': 'manual'}, _now=_BASE_NOW)

    assert result == (None, None)
    assert _row_count(spot_db) == 0


# ---------------------------------------------------------------------------
# b. fresh snapshot row
# ---------------------------------------------------------------------------

def test_fresh_row_is_served_without_fetch_or_spawn(spot_db, monkeypatch):
    monkeypatch.setattr(wp, '_get_spot_price_for_position', _boom)
    monkeypatch.setattr(wp, '_spawn_spot_price_refresh', _boom)
    fetched_at = _iso(_BASE_NOW - 10)  # 10s old, well under the 60s TTL
    _seed_snapshot(spot_db, 'BTC', 50000.0, fetched_at)

    result = wp._get_spot_price_stale_serve(_pos(), {'price_source': 'coingecko'}, _now=_BASE_NOW)

    assert result == (50000.0, fetched_at)


# ---------------------------------------------------------------------------
# c. expired snapshot row
# ---------------------------------------------------------------------------

def test_expired_row_is_served_stale_and_spawns_refresh_once(spot_db, monkeypatch):
    monkeypatch.setattr(wp, '_get_spot_price_for_position', _boom)
    spawn_calls = []
    monkeypatch.setattr(wp, '_spawn_spot_price_refresh', lambda pos, cfg: spawn_calls.append((pos, cfg)))
    fetched_at = _iso(_BASE_NOW - 120)  # older than the 60s TTL
    pos = _pos()
    cfg = {'price_source': 'coingecko'}
    _seed_snapshot(spot_db, 'BTC', 50000.0, fetched_at)

    result = wp._get_spot_price_stale_serve(pos, cfg, _now=_BASE_NOW)

    assert result == (50000.0, fetched_at)
    assert len(spawn_calls) == 1
    assert spawn_calls[0] == (pos, cfg)


# ---------------------------------------------------------------------------
# d/e. no snapshot row yet
# ---------------------------------------------------------------------------

def test_no_row_blocking_fetch_returns_price_and_upserts_one_row(spot_db, monkeypatch):
    monkeypatch.setattr(wp, '_get_spot_price_for_position', lambda pos, cfg: 123.45)
    monkeypatch.setattr(wp, '_spawn_spot_price_refresh', _boom)

    price, fetched_at = wp._get_spot_price_stale_serve(_pos(), {'price_source': 'coingecko'}, _now=_BASE_NOW)

    assert price == 123.45
    assert fetched_at is not None
    assert _row_count(spot_db) == 1
    conn = _open(spot_db)
    row = conn.execute("SELECT price_usd, fetched_at FROM spot_price_snapshot WHERE position_key='BTC'").fetchone()
    conn.close()
    assert row['price_usd'] == 123.45
    assert row['fetched_at'] == fetched_at


def test_no_row_blocking_fetch_returns_none_writes_nothing(spot_db, monkeypatch):
    monkeypatch.setattr(wp, '_get_spot_price_for_position', lambda pos, cfg: None)
    monkeypatch.setattr(wp, '_spawn_spot_price_refresh', _boom)

    result = wp._get_spot_price_stale_serve(_pos(), {'price_source': 'coingecko'}, _now=_BASE_NOW)

    assert result == (None, None)
    assert _row_count(spot_db) == 0


# ---------------------------------------------------------------------------
# f. dedupe (real _spawn_spot_price_refresh, real background thread)
# ---------------------------------------------------------------------------

def test_spawn_is_a_noop_when_key_already_inflight(spot_db, monkeypatch):
    monkeypatch.setattr(wp, '_get_spot_price_for_position', _boom)
    pos = _pos('BTC')
    wp._spot_snapshot_refresh_inflight.add('BTC')

    wp._spawn_spot_price_refresh(pos, {'price_source': 'coingecko'})  # must not call _boom

    assert _row_count(spot_db) == 0


def test_spawn_discards_inflight_key_after_fetch_exception(spot_db, monkeypatch):
    def _raise(pos, cfg):
        raise RuntimeError("network exploded")
    monkeypatch.setattr(wp, '_get_spot_price_for_position', _raise)
    pos = _pos('ETH')

    wp._spawn_spot_price_refresh(pos, {'price_source': 'coingecko'})

    for _ in range(100):
        if 'ETH' not in wp._spot_snapshot_refresh_inflight:
            break
        _t.sleep(0.02)
    assert 'ETH' not in wp._spot_snapshot_refresh_inflight
    assert _row_count(spot_db) == 0  # failure never writes


def test_spawn_upserts_on_success_and_clears_inflight(spot_db, monkeypatch):
    monkeypatch.setattr(wp, '_get_spot_price_for_position', lambda pos, cfg: 7.5)
    pos = _pos('SOL')

    wp._spawn_spot_price_refresh(pos, {'price_source': 'coingecko'})

    for _ in range(100):
        if _row_count(spot_db) == 1:
            break
        _t.sleep(0.02)
    assert _row_count(spot_db) == 1
    assert 'SOL' not in wp._spot_snapshot_refresh_inflight
    conn = _open(spot_db)
    row = conn.execute("SELECT price_usd FROM spot_price_snapshot WHERE position_key='SOL'").fetchone()
    conn.close()
    assert row['price_usd'] == 7.5


# ---------------------------------------------------------------------------
# g. malformed fetched_at
# ---------------------------------------------------------------------------

def test_malformed_fetched_at_is_treated_as_expired_no_exception(spot_db, monkeypatch):
    monkeypatch.setattr(wp, '_get_spot_price_for_position', _boom)
    spawn_calls = []
    monkeypatch.setattr(wp, '_spawn_spot_price_refresh', lambda pos, cfg: spawn_calls.append((pos, cfg)))
    _seed_snapshot(spot_db, 'BTC', 50000.0, 'not-a-timestamp')

    result = wp._get_spot_price_stale_serve(_pos(), {'price_source': 'coingecko'}, _now=_BASE_NOW)

    assert result == (50000.0, 'not-a-timestamp')
    assert len(spawn_calls) == 1
