"""Spot price jump guard: _spawn_spot_price_refresh confirms a background
price that moves more than SPOT_PRICE_JUMP_FACTOR (10x) from the stored
spot_price_snapshot price with a second fetch (in-memory caches evicted
first) before storing it (Sep 27: STONK cached at ~$1,256 instead of
~$0.257 for one refresh).

Same header pattern as tests/test_spot_price_stale_serve.py: init_db()
against a tmp-path SQLite file via a monkeypatched get_db_path(), and the
REAL _spawn_spot_price_refresh with a real background thread, polling until
the key leaves the in-flight set. _get_spot_price_for_position is replaced by
a recorder that returns queued values; no network.
"""
import threading
import time as _t

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as _pdb

KEY = 'STONK|solana|abc'
OLD_TS = '2026-09-27T12:00:00+00:00'


@pytest.fixture(autouse=True)
def _clean_module_state():
    wp._spot_snapshot_refresh_inflight.clear()
    wp._spot_position_price_cache.clear()
    wp._cg_price_cache.clear()
    yield
    wp._spot_snapshot_refresh_inflight.clear()
    wp._spot_position_price_cache.clear()
    wp._cg_price_cache.clear()


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


def _row(path, position_key=KEY):
    conn = _open(path)
    row = conn.execute("SELECT price_usd, fetched_at FROM spot_price_snapshot WHERE position_key=?",
                       (position_key,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _pos(position_key=KEY):
    return {'position_key': position_key, 'symbol': 'STONK', 'chain': 'solana', 'contract_address': 'abc'}


CFG = {'price_source': 'dexscreener', 'contract_address': 'abc'}


class _Fetcher:
    """Returns queued values in order (an Exception instance is raised) and records each call."""

    def __init__(self, *values):
        self.values = list(values)
        self.calls = []

    def __call__(self, pos, cfg):
        self.calls.append((pos['position_key'], cfg))
        v = self.values.pop(0)
        if isinstance(v, Exception):
            raise v
        return v


def _refresh(monkeypatch, *values, pos=None):
    fetch = _Fetcher(*values)
    monkeypatch.setattr(wp, '_get_spot_price_for_position', fetch)
    pos = pos or _pos()
    wp._spawn_spot_price_refresh(pos, CFG)
    deadline = _t.time() + 2.0
    while pos['position_key'] in wp._spot_snapshot_refresh_inflight and _t.time() < deadline:
        _t.sleep(0.01)
    assert pos['position_key'] not in wp._spot_snapshot_refresh_inflight
    return fetch


def test_t1_no_stored_row_stores_the_first_fetch(spot_db, monkeypatch):
    fetch = _refresh(monkeypatch, 1000.0)
    assert _row(spot_db)['price_usd'] == 1000.0
    assert len(fetch.calls) == 1


def test_t2_unconfirmed_jump_keeps_the_stored_price(spot_db, monkeypatch, capsys):
    _seed_snapshot(spot_db, KEY, 0.257, OLD_TS)
    fetch = _refresh(monkeypatch, 1256.0, 0.257)
    assert _row(spot_db) == {'price_usd': 0.257, 'fetched_at': OLD_TS}
    assert len(fetch.calls) == 2
    out = capsys.readouterr().out
    assert 'price jump not confirmed' in out and 'kept the stored price' in out
    assert 'stored=0.257' in out and 'fetched=1256.0' in out and 'confirm=0.257' in out


def test_t3_confirmed_jump_stores_the_confirming_price(spot_db, monkeypatch, capsys):
    _seed_snapshot(spot_db, KEY, 0.257, OLD_TS)
    fetch = _refresh(monkeypatch, 3.0, 3.1)
    row = _row(spot_db)
    assert row['price_usd'] == 3.1 and row['fetched_at'] != OLD_TS
    assert len(fetch.calls) == 2
    out = capsys.readouterr().out
    assert 'price jump confirmed' in out and 'new=3.1' in out


def test_t4_move_under_the_factor_is_stored_directly(spot_db, monkeypatch, capsys):
    _seed_snapshot(spot_db, KEY, 1.0, OLD_TS)
    fetch = _refresh(monkeypatch, 5.0)
    assert _row(spot_db)['price_usd'] == 5.0
    assert len(fetch.calls) == 1
    assert 'price jump' not in capsys.readouterr().out


def test_t5_confirming_fetch_without_a_price_keeps_the_stored_price(spot_db, monkeypatch):
    _seed_snapshot(spot_db, KEY, 1.0, OLD_TS)
    fetch = _refresh(monkeypatch, 0.05, None)
    assert _row(spot_db) == {'price_usd': 1.0, 'fetched_at': OLD_TS}
    assert len(fetch.calls) == 2


def test_t6_confirmed_downward_jump(spot_db, monkeypatch):
    _seed_snapshot(spot_db, KEY, 1.0, OLD_TS)
    fetch = _refresh(monkeypatch, 0.01, 0.0101)
    assert _row(spot_db)['price_usd'] == 0.0101
    assert len(fetch.calls) == 2


@pytest.mark.parametrize('new', [10.0, 0.1])
def test_t7_exactly_the_factor_is_not_a_jump(spot_db, monkeypatch, new):
    _seed_snapshot(spot_db, KEY, 1.0, OLD_TS)
    fetch = _refresh(monkeypatch, new)
    assert _row(spot_db)['price_usd'] == new
    assert len(fetch.calls) == 1


def test_t8_confirming_fetch_raises(spot_db, monkeypatch):
    _seed_snapshot(spot_db, KEY, 1.0, OLD_TS)
    fetch = _refresh(monkeypatch, 50.0, RuntimeError('dexscreener down'))
    assert _row(spot_db) == {'price_usd': 1.0, 'fetched_at': OLD_TS}
    assert len(fetch.calls) == 2
    assert KEY not in wp._spot_snapshot_refresh_inflight


def test_t9_order_is_fetch_evict_fetch(spot_db, monkeypatch):
    _seed_snapshot(spot_db, KEY, 1.0, OLD_TS)
    events = []
    values = [50.0, 50.5]

    def fetch(pos, cfg):
        events.append('fetch')
        return values.pop(0)

    def evict(pos, cfg):
        events.append('evict')
    monkeypatch.setattr(wp, '_get_spot_price_for_position', fetch)
    monkeypatch.setattr(wp, '_spot_price_cache_evict', evict)
    wp._spawn_spot_price_refresh(_pos(), CFG)
    deadline = _t.time() + 2.0
    while KEY in wp._spot_snapshot_refresh_inflight and _t.time() < deadline:
        _t.sleep(0.01)
    assert events == ['fetch', 'evict', 'fetch']
    assert _row(spot_db)['price_usd'] == 50.5


def test_t10_cache_evict_drops_only_this_positions_keys():
    wp._spot_position_price_cache['solana|abc'] = (1256.0, _t.time())
    wp._spot_position_price_cache['base|0xother'] = (2.0, _t.time())
    wp._cg_price_cache['STONK'] = (1256.0, _t.time())
    wp._cg_price_cache['abc'] = (1256.0, _t.time())
    wp._cg_price_cache['BTC'] = (60000.0, _t.time())
    wp._spot_price_cache_evict({'symbol': 'STONK', 'chain': 'Solana', 'contract_address': 'ABC'},
                               {'contract_address': 'abc'})
    assert list(wp._spot_position_price_cache) == ['base|0xother']
    assert list(wp._cg_price_cache) == ['BTC']
    wp._spot_price_cache_evict({'symbol': 'X'}, None)                        # blank fields: no error


@pytest.mark.parametrize('prev, new, expected', [
    (None, 5.0, False), (0, 5.0, False), (-1.0, 5.0, False), (float('nan'), 5.0, False), ('x', 5.0, False),
    (1.0, float('nan'), False), (1.0, float('inf'), False), (1.0, None, False),
    (1.0, 10.0, False), (1.0, 0.1, False), (1.0, 10.0001, True), (1.0, 0.0999, True),
    (0.257, 1256.0, True), (1.0, 0.0, True), (1.0, 5.0, False),
])
def test_t11_is_jump(prev, new, expected):
    assert wp._spot_price_is_jump(prev, new) is expected


@pytest.mark.parametrize('first, second, expected', [
    (3.0, None, False), (0, 0, True), (0, 0.001, False), (3.0, 3.3, True), (3.0, 2.7, True),
    (3.0, 3.31, False), (3.0, 2.69, False), (1256.0, 0.257, False), (1.0, float('nan'), False),
])
def test_t11_prices_agree(first, second, expected):
    assert wp._spot_prices_agree(first, second) is expected
