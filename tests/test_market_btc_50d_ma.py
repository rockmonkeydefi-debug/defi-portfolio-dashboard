"""market_snapshots.btc_50d_ma (Dashboard redesign PR 3 step 0): the BTC 50-day
moving average beside the 200-day, the last 50 points of the same once-a-day
CoinGecko market_chart daily series as btc_200d_ma.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). The CoinGecko GET is a fake routed by URL that records calls,
and sleep is a recorder, so nothing touches the network or really sleeps.
Synthetic values."""
from datetime import datetime, timedelta

import pytest

import src.engines.snapshot_service as snapshot_service
import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

MA_URL = 'https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=200&interval=daily'
SERIES = [float(p) for p in range(1, 202)]      # 201 daily points


@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    return path


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    monkeypatch.setattr(wp, "fetch_fred_macro", lambda *a, **k: None)
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


class _Resp:
    def __init__(self, ok=True, payload=None, status_code=200):
        self.ok = ok
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def _series_resp(prices):
    return _Resp(payload={'prices': [[1_700_000_000_000 + i * 86_400_000, p] for i, p in enumerate(prices)]})


class _Get:
    """Fake requests.get routed by exact URL; unrouted URLs get ok=False. Records every call."""

    def __init__(self, routes=None, exc=None):
        self.routes = routes or {}
        self.exc = exc
        self.calls = []

    def __call__(self, url, timeout=None, **kwargs):
        self.calls.append((url, timeout))
        if self.exc is not None:
            raise self.exc
        return self.routes.get(url) or _Resp(ok=False, status_code=503)


class _Sleep:
    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


def _insert(ts, **fields):
    portfolio_db.insert_market_snapshot({'timestamp': ts.isoformat(), 'session': 'test', **fields})


def _now():
    return datetime.utcnow()


# --- btc_moving_averages (pure) ---------------------------------------------

def test_t1_both_averages_from_one_series():
    mas = snapshot_service.btc_moving_averages(list(range(1, 202)))
    assert mas == {'btc_200d_ma': 101.0, 'btc_50d_ma': 176.5}


def test_t2_under_100_points_has_no_200_day():
    prices = [float(p) for p in range(1, 61)]
    mas = snapshot_service.btc_moving_averages(prices)
    assert mas['btc_200d_ma'] is None
    assert mas['btc_50d_ma'] == pytest.approx(sum(prices[-50:]) / 50)


def test_t3_under_50_points_has_neither():
    assert snapshot_service.btc_moving_averages([1.0] * 49) == {'btc_200d_ma': None, 'btc_50d_ma': None}


# --- schema and route ----------------------------------------------------------

def test_t4_migration_adds_the_column_once(dbpath):
    portfolio_db.init_db()
    conn = portfolio_db.get_connection()
    try:
        names = [r['name'] for r in conn.execute("PRAGMA table_info(market_snapshots)").fetchall()]
    finally:
        conn.close()
    assert names.count('btc_50d_ma') == 1
    assert names.count('btc_200d_ma') == 1


def test_t5_market_data_returns_btc_50d_ma(client, dbpath):
    _insert(_now(), btc_price=100.0, btc_200d_ma=90.0, btc_50d_ma=95.0)
    snap = client.get("/api/market-data").get_json()["snapshot"]
    assert snap["btc_50d_ma"] == 95.0
    assert snap["btc_200d_ma"] == 90.0


def test_t5b_market_data_btc_50d_ma_null_when_absent(client, dbpath):
    _insert(_now(), btc_price=100.0, btc_200d_ma=90.0)
    snap = client.get("/api/market-data").get_json()["snapshot"]
    assert "btc_50d_ma" in snap and snap["btc_50d_ma"] is None
    assert snap["btc_200d_ma"] == 90.0


# --- _btc_moving_averages_for_snapshot (once-a-day cache) ----------------------

def test_t6_today_has_both_no_fetch(dbpath, capsys):
    _insert(_now(), btc_200d_ma=70000.0, btc_50d_ma=65000.0)
    get, sleep = _Get({MA_URL: _series_resp(SERIES)}), _Sleep()
    result = snapshot_service._btc_moving_averages_for_snapshot(get=get, sleep=sleep)
    assert result == {'btc_200d_ma': 70000.0, 'btc_50d_ma': 65000.0}
    assert get.calls == [] and sleep.calls == []
    out = capsys.readouterr().out
    assert 'BTC 200D MA: $70,000 (cached from today)' in out
    assert 'BTC 50D MA: $65,000 (cached from today)' in out


def test_t6b_todays_newest_row_decides(dbpath):
    now = _now()
    _insert(now - timedelta(seconds=2), btc_200d_ma=70000.0, btc_50d_ma=65000.0)
    _insert(now - timedelta(seconds=1), btc_200d_ma=71000.0)
    get, sleep = _Get(), _Sleep()
    result = snapshot_service._btc_moving_averages_for_snapshot(get=get, sleep=sleep)
    assert len(get.calls) == 1
    assert result == {'btc_200d_ma': 71000.0}


def test_t7_today_has_200_day_only_refetches_once(dbpath, capsys):
    _insert(_now(), btc_200d_ma=70000.0)
    get, sleep = _Get({MA_URL: _series_resp(SERIES)}), _Sleep()
    result = snapshot_service._btc_moving_averages_for_snapshot(get=get, sleep=sleep)
    assert result == snapshot_service.btc_moving_averages(SERIES)
    assert result == {'btc_200d_ma': 101.0, 'btc_50d_ma': 176.5}
    assert get.calls == [(MA_URL, 20)]
    assert sleep.calls == [3]
    out = capsys.readouterr().out
    assert 'BTC 200D MA: $101 (201 days, fresh)' in out
    assert 'BTC 50D MA: $176 (50 days, fresh)' in out          # 176.5 formats as 176 (round-half-even)


def test_t7b_refetch_without_a_200_day_keeps_the_cached_one(dbpath):
    _insert(_now(), btc_200d_ma=70000.0)
    short = [float(p) for p in range(1, 61)]                    # 60 points: 50-day only
    get, sleep = _Get({MA_URL: _series_resp(short)}), _Sleep()
    result = snapshot_service._btc_moving_averages_for_snapshot(get=get, sleep=sleep)
    assert result == {'btc_200d_ma': 70000.0, 'btc_50d_ma': pytest.approx(35.5)}


def test_t8_refetch_not_ok_keeps_the_cached_200_day(dbpath, capsys):
    _insert(_now(), btc_200d_ma=70000.0)
    get, sleep = _Get(), _Sleep()
    result = snapshot_service._btc_moving_averages_for_snapshot(get=get, sleep=sleep)
    assert result == {'btc_200d_ma': 70000.0}
    assert len(get.calls) == 1
    assert sleep.calls == [3]
    assert 'BTC 200D MA: CoinGecko returned 503' in capsys.readouterr().out


def test_t9_refetch_raises_keeps_the_cached_200_day(dbpath, capsys):
    _insert(_now(), btc_200d_ma=70000.0)
    get, sleep = _Get(exc=RuntimeError('coingecko down')), _Sleep()
    result = snapshot_service._btc_moving_averages_for_snapshot(get=get, sleep=sleep)
    assert result == {'btc_200d_ma': 70000.0}
    assert len(get.calls) == 1
    assert sleep.calls == []
    assert '[Market] BTC 200D MA error: coingecko down' in capsys.readouterr().out


def test_t10_only_yesterdays_row_fetches(dbpath):
    _insert(_now() - timedelta(days=1), btc_200d_ma=70000.0, btc_50d_ma=65000.0)
    get, sleep = _Get({MA_URL: _series_resp(SERIES)}), _Sleep()
    result = snapshot_service._btc_moving_averages_for_snapshot(get=get, sleep=sleep)
    assert get.calls == [(MA_URL, 20)]
    assert result == {'btc_200d_ma': 101.0, 'btc_50d_ma': 176.5}
    assert sleep.calls == [3]


# --- take_market_snapshot end to end --------------------------------------------

def test_t11_take_market_snapshot_writes_both_averages(dbpath, monkeypatch):
    monkeypatch.delenv('ETHEREUM_RPC_URL', raising=False)     # no web3 gas-price call
    get, sleep = _Get({MA_URL: _series_resp(SERIES)}), _Sleep()
    monkeypatch.setattr(snapshot_service.requests, 'get', get)
    monkeypatch.setattr(snapshot_service.time, 'sleep', sleep)
    snapshot_service.take_market_snapshot('test')
    conn = portfolio_db.get_connection()
    try:
        rows = conn.execute("SELECT btc_200d_ma, btc_50d_ma FROM market_snapshots").fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert dict(rows[0]) == snapshot_service.btc_moving_averages(SERIES)
    assert [u for u, _ in get.calls].count(MA_URL) == 1
    assert get.calls[0] == (MA_URL, 20)                          # still FIRST
