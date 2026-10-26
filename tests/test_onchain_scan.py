"""Landing 70: ad hoc on-chain token check (onchain_scan.py plus the compute
and route in web_portfolio).

No network: GeckoTerminal is replaced at two seams - onchain_scan._get_json
(networks, pools) and maxfi_history.fetch_pool_ohlcv (candles). Spacing is
zeroed. Made-up addresses and prices. The parity test stores the same
candles through the scan's own _noodle_store_symbol into a tmp SQLite and
compares every column the check returns.
"""
import random
import threading
from datetime import datetime, timezone

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import maxfi_history
import onchain_scan
import src.storage.portfolio_db as portfolio_db

TOKEN = "0x" + "a" * 40
OTHER = "0x" + "b" * 40
POOL1 = "0x" + "1" * 40
POOL2 = "0x" + "2" * 40
POOL3 = "0x" + "3" * 40
NOW = int(datetime(2026, 10, 25, 12, 30, tzinfo=timezone.utc).timestamp())
STEP = {'1h': 3600, '4h': 14400, '12h': 43200, '1d': 86400}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(maxfi_history, "GT_CALL_SPACING_SECONDS", 0)
    monkeypatch.setattr(onchain_scan, "_networks_cache", {'at': 0.0, 'ids': None})
    monkeypatch.delenv("COINGECKO_API_KEY", raising=False)


def networks_payload(ids):
    return {'data': [{'id': i, 'attributes': {'name': n}} for i, n in ids.items()], 'links': {'next': None}}


def pool_item(addr, name, liq, base, quote, dex='uniswap_v3', vol=1000.0, created='2026-09-01T00:00:00Z'):
    return {'id': f'eth_{addr}', 'attributes': {
        'address': addr, 'name': name, 'reserve_in_usd': liq, 'volume_usd': {'h24': vol},
        'pool_created_at': created},
        'relationships': {'dex': {'data': {'id': dex}},
                          'base_token': {'data': {'id': f'eth_{base}'}},
                          'quote_token': {'data': {'id': f'eth_{quote}'}}}}


def raw_series(n, step, end_ts, seed=3, drop=0.0, start=1.0):
    """Ascending-or-not GT rows ending at the bar holding end_ts, a wandering
    price in regimes, with `drop` fraction of bars missing."""
    rnd = random.Random(seed)
    last = end_ts - end_ts % step
    px, drift, rows = start, 0.004, []
    for k in range(n):
        if k % 60 == 0:
            drift = rnd.choice([0.006, -0.006, 0.0005])
        o = px
        px = max(0.0001, px * (1 + drift + rnd.uniform(-0.01, 0.01)))
        hi, lo = max(o, px) * 1.004, min(o, px) * 0.996
        rows.append([last - (n - 1 - k) * step, o, hi, lo, px, 100.0 + k])
    if drop:
        rows = [r for i, r in enumerate(rows) if i == len(rows) - 1 or rnd.random() >= drop]
    return rows


def install_candles(monkeypatch, n=600, drop=0.0, calls=None, bars=None):
    plan = {('hour', 1): '1h', ('hour', 4): '4h', ('hour', 12): '12h', ('day', 1): '1d'}

    def fake(network, pool, timeframe, *, aggregate=1, before_timestamp=None, limit=1000, token=None, timeout=10):
        key = plan[(timeframe, aggregate)]
        if calls is not None:
            calls.append({'network': network, 'pool': pool, 'tf': key, 'token': token, 'limit': limit})
        count = (bars or {}).get(key, n)
        rows = raw_series(count, STEP[key], NOW, seed={'1h': 11, '4h': 21, '12h': 31, '1d': 41}[key], drop=drop)
        random.Random(5).shuffle(rows)       # GT does not promise an order
        return {'candles': rows, 'base_address': TOKEN, 'quote_address': OTHER}
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", fake)


def install_http(monkeypatch, networks=None, pools=None, pool=None, log=None):
    networks = networks if networks is not None else {'eth': 'Ethereum', 'base': 'Base', 'solana': 'Solana'}

    def fake(path, params=None, timeout=10):
        if log is not None:
            log.append(path)
        if path == '/networks':
            return networks_payload(networks)
        if path.endswith('/pools') and '/tokens/' in path:
            return {'data': pools}
        if '/pools/' in path:
            return {'data': pool}
        raise AssertionError(path)
    monkeypatch.setattr(onchain_scan, "_get_json", fake)


# -- networks -------------------------------------------------------------

def test_network_candidate_match(monkeypatch):
    install_http(monkeypatch)
    assert onchain_scan.resolve_network('ethereum') == 'eth'
    assert onchain_scan.resolve_network('base') == 'base'


def test_network_name_fallback_for_robinhood(monkeypatch):
    install_http(monkeypatch, networks={'eth': 'Ethereum', 'rh-chain-xyz': 'Robinhood Chain'})
    assert onchain_scan.resolve_network('robinhood', 'Robinhood Chain') == 'rh-chain-xyz'


def test_network_unsupported_says_so(monkeypatch):
    install_http(monkeypatch, networks={'eth': 'Ethereum'})
    with pytest.raises(onchain_scan.OnchainError) as e:
        onchain_scan.resolve_network('sonic', 'Sonic')
    assert e.value.status == 400
    assert e.value.message == "Sonic is not supported by GeckoTerminal, so it cannot be checked here."


def test_empty_network_list_is_an_error_not_unsupported(monkeypatch):
    install_http(monkeypatch, networks={})
    with pytest.raises(onchain_scan.OnchainError) as e:
        onchain_scan.resolve_network('base', 'Base')
    assert e.value.status == 502 and 'empty' in e.value.message


def test_network_list_cached_and_failure_not_cached(monkeypatch):
    log = []
    install_http(monkeypatch, log=log)
    onchain_scan.resolve_network('base')
    onchain_scan.resolve_network('solana')
    assert log == ['/networks']
    monkeypatch.setattr(onchain_scan, "_networks_cache", {'at': 0.0, 'ids': None})

    def boom(path, params=None, timeout=10):
        raise onchain_scan.OnchainError("down", 502)
    monkeypatch.setattr(onchain_scan, "_get_json", boom)
    with pytest.raises(onchain_scan.OnchainError):
        onchain_scan.resolve_network('base')
    assert onchain_scan._networks_cache['ids'] is None


# -- pools ----------------------------------------------------------------

def test_most_liquid_pool_is_picked_with_alternatives(monkeypatch):
    pools = [pool_item(POOL1, 'AAA / WETH 0.3%', '5000', TOKEN, OTHER),
             pool_item(POOL2, 'AAA / USDC 1%', '90000', TOKEN, OTHER),
             pool_item(POOL3, 'WETH / AAA', '20000', OTHER, TOKEN)]
    install_http(monkeypatch, pools=pools)
    pool, side, alts, auto = onchain_scan.find_pool('eth', TOKEN)
    assert pool['address'] == POOL2 and side == 'base' and auto is True
    assert [a['address'] for a in alts] == [POOL3, POOL1]


def test_pool_where_token_is_quote_side(monkeypatch):
    install_http(monkeypatch, pools=[pool_item(POOL3, 'WETH / AAA', '20000', OTHER, TOKEN)])
    pool, side, alts, auto = onchain_scan.find_pool('eth', TOKEN)
    assert side == 'quote'


def test_evm_address_compare_ignores_case(monkeypatch):
    install_http(monkeypatch, pools=[pool_item(POOL1, 'A / B', '5', TOKEN, OTHER)])
    pool, side, _, _ = onchain_scan.find_pool('eth', "0x" + "A" * 40)
    assert side == 'base'


def test_pools_without_the_token_or_unusable_are_skipped(monkeypatch):
    pools = [{'bad': 1}, pool_item(POOL1, 'X / Y', '9', OTHER, "0x" + "c" * 40)]
    install_http(monkeypatch, pools=pools)
    with pytest.raises(onchain_scan.OnchainError) as e:
        onchain_scan.find_pool('eth', TOKEN)
    assert e.value.status == 404


def test_pools_shape_surprise_is_a_plain_error(monkeypatch):
    monkeypatch.setattr(onchain_scan, "_get_json", lambda *a, **k: {'nope': 1})
    with pytest.raises(onchain_scan.OnchainError) as e:
        onchain_scan.find_pool('eth', TOKEN)
    assert e.value.status == 502


def test_base58_address_compare_keeps_case(monkeypatch):
    sol = "So" + "1" * 30 + "abcdEFGH"
    install_http(monkeypatch, pools=[pool_item(POOL1, 'A / B', '5', sol, OTHER)])
    assert onchain_scan.find_pool('solana', sol)[1] == 'base'
    with pytest.raises(onchain_scan.OnchainError):
        onchain_scan.find_pool('solana', sol.lower())


def test_pasted_pool_uses_that_pool_and_not_auto(monkeypatch):
    log = []
    install_http(monkeypatch, pool=pool_item(POOL1, 'AAA / WETH', '5000', TOKEN, OTHER), log=log)
    pool, side, alts, auto = onchain_scan.find_pool('eth', TOKEN, POOL1)
    assert pool['address'] == POOL1 and auto is False and alts == [] and side == 'base'
    assert log == [f'/networks/eth/pools/{POOL1}']


def test_pasted_pool_without_token_charts_base(monkeypatch):
    install_http(monkeypatch, pool=pool_item(POOL1, 'AAA / WETH', '5000', TOKEN, OTHER))
    assert onchain_scan.find_pool('eth', '', POOL1)[1] == 'base'


def test_pasted_pool_not_holding_the_token_is_refused(monkeypatch):
    install_http(monkeypatch, pool=pool_item(POOL1, 'AAA / WETH', '5000', OTHER, "0x" + "c" * 40))
    with pytest.raises(onchain_scan.OnchainError) as e:
        onchain_scan.find_pool('eth', TOKEN, POOL1)
    assert e.value.status == 400


# -- candles --------------------------------------------------------------

def test_normalize_sorts_dedupes_and_skips_junk():
    base = 1_700_000_000 - 1_700_000_000 % 3600
    raw = [[base + 7200, 2, 3, 1, 2.5, 4], [base, 1, 2, 1, 1.5, 1], [base, 9, 9, 9, 9, 9],
           [base + 3600, 0, 1, 1, 1, 1], "junk", [base + 3600, 1, 2, 1, 'x', 1],
           [base + 10800, 2, 2, 2, 2, None]]
    out = onchain_scan.normalize_candles(raw, 3600, base + 10800)
    assert [c['time'] for c in out] == [base, base + 3600, base + 7200, base + 10800]
    assert out[0]['close'] == 9                      # later duplicate wins (dict overwrite)
    assert out[1]['volume'] == 0.0 and out[1]['close'] == 9   # carried gap
    assert out[3]['volume'] == 0.0


def test_gaps_carry_last_close_with_zero_volume():
    base = 1_700_000_000 - 1_700_000_000 % 86400
    raw = [[base, 1, 2, 0.5, 1.5, 7], [base + 4 * 86400, 1.7, 2, 1, 1.8, 3]]
    out = onchain_scan.normalize_candles(raw, 86400, base + 4 * 86400)
    assert len(out) == 5
    for c in out[1:4]:
        assert (c['open'], c['high'], c['low'], c['close'], c['volume']) == (1.5, 1.5, 1.5, 1.5, 0.0)


def test_series_runs_through_the_current_bar_when_nothing_traded_since():
    base = 1_700_000_000 - 1_700_000_000 % 14400
    raw = [[base, 1, 2, 1, 1.5, 1]]
    out = onchain_scan.normalize_candles(raw, 14400, base + 3 * 14400 + 5)
    assert [c['time'] for c in out] == [base + k * 14400 for k in range(4)]
    assert out[-1]['close'] == 1.5 and out[-1]['volume'] == 0.0


def test_series_phase_follows_the_data_not_the_epoch():
    base = 1_700_000_000 + 600          # off-grid phase
    raw = [[base, 1, 2, 1, 1.5, 1]]
    out = onchain_scan.normalize_candles(raw, 3600, base + 2 * 3600 + 100)
    assert [c['time'] for c in out] == [base, base + 3600, base + 7200]


def test_no_usable_candles_is_an_error():
    with pytest.raises(onchain_scan.OnchainError):
        onchain_scan.normalize_candles([[1, 0, 0, 0, 0, 0], 'x'], 3600, 10)
    with pytest.raises(onchain_scan.OnchainError):
        onchain_scan.normalize_candles(None, 3600, 10)


def test_fetch_series_plan_and_quote_inversion(monkeypatch):
    calls = []
    install_candles(monkeypatch, n=50, calls=calls)
    pool = {'address': POOL1}
    series = onchain_scan.fetch_series('eth', pool, 'quote', now_ts=NOW)
    assert [c['tf'] for c in calls] == ['1h', '4h', '12h', '1d']
    assert all(c['token'] == 'quote' and c['pool'] == POOL1 and c['network'] == 'eth' for c in calls)
    assert set(series) == {'1h', '4h', '12h', '1d'}
    calls.clear()
    onchain_scan.fetch_series('eth', pool, 'base', now_ts=NOW)
    assert all(c['token'] is None for c in calls)


def test_fetch_series_fills_gaps_at_each_timeframes_own_step(monkeypatch):
    install_candles(monkeypatch, n=200, drop=0.5)
    series = onchain_scan.fetch_series('eth', {'address': POOL1}, 'base', now_ts=NOW)
    for tf, step in STEP.items():
        times = [c['time'] for c in series[tf]]
        assert all(b - a == step for a, b in zip(times, times[1:])), tf
        assert times[-1] == NOW - NOW % step, tf


def test_fetch_series_maps_failures(monkeypatch):
    def rl(*a, **k):
        raise maxfi_history.GTRateLimitError("429")
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", rl)
    with pytest.raises(onchain_scan.OnchainError) as e:
        onchain_scan.fetch_series('eth', {'address': POOL1}, 'base', now_ts=NOW)
    assert e.value.status == 429

    def bad(*a, **k):
        raise maxfi_history.GTError("shape")
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", bad)
    with pytest.raises(onchain_scan.OnchainError) as e:
        onchain_scan.fetch_series('eth', {'address': POOL1}, 'base', now_ts=NOW)
    assert e.value.status == 502


def test_keyed_base_url_and_header(monkeypatch):
    monkeypatch.setenv("COINGECKO_API_KEY", "k")
    base, headers = onchain_scan._base_url_and_headers()
    assert base == maxfi_history.CG_ONCHAIN_BASE_URL and headers['x-cg-demo-api-key'] == 'k'
    monkeypatch.delenv("COINGECKO_API_KEY")
    base, headers = onchain_scan._base_url_and_headers()
    assert base == maxfi_history.GT_PUBLIC_BASE_URL and 'x-cg-demo-api-key' not in headers


class _Resp:
    def __init__(self, status, payload=None, bad_json=False):
        self.status_code, self._p, self._bad = status, payload, bad_json
        self.ok = 200 <= status < 300

    def json(self):
        if self._bad:
            raise ValueError("x")
        return self._p


@pytest.mark.parametrize("resp,status", [(_Resp(429), 429), (_Resp(404), 404), (_Resp(500), 502),
                                         (_Resp(200, bad_json=True), 502)])
def test_get_json_failures(monkeypatch, resp, status):
    monkeypatch.setattr(onchain_scan.requests, "get", lambda *a, **k: resp)
    with pytest.raises(onchain_scan.OnchainError) as e:
        onchain_scan._get_json('/networks')
    assert e.value.status == status


def test_get_json_ok_and_network_error(monkeypatch):
    monkeypatch.setattr(onchain_scan.requests, "get", lambda *a, **k: _Resp(200, {'a': 1}))
    assert onchain_scan._get_json('/x') == {'a': 1}

    def boom(*a, **k):
        raise onchain_scan.requests.ConnectionError("x")
    monkeypatch.setattr(onchain_scan.requests, "get", boom)
    with pytest.raises(onchain_scan.OnchainError) as e:
        onchain_scan._get_json('/x')
    assert e.value.status == 502


# -- compute --------------------------------------------------------------

def setup_compute(monkeypatch, pools=None, **kw):
    install_http(monkeypatch, pools=pools or [pool_item(POOL1, 'AAA / WETH 0.3%', '250000', TOKEN, OTHER)])
    install_candles(monkeypatch, **kw)


def test_compute_shape_and_pool_facts(monkeypatch):
    setup_compute(monkeypatch)
    out = wp._onchain_check_compute('ethereum', TOKEN, now_ts=NOW)
    assert out['symbol'] == 'AAA' and out['network'] == 'eth' and out['chain_label'] == 'Ethereum'
    assert set(out['timeframes']) == {'1w', '1d', '12h', '4h', '1h'}
    assert out['pool']['dex'] == 'uniswap_v3' and out['pool']['liquidity_usd'] == 250000.0
    assert out['pool']['auto'] is True and out['pool']['side'] == 'base'
    assert out['pool']['age_days'] == pytest.approx((NOW - datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()) / 86400)
    assert out['notes'][0].startswith('No contract-safety check')
    assert len(out['notes']) == 1
    for tf, row in out['timeframes'].items():
        assert row['state'] in ('BULLISH', 'BEARISH')
        assert row['bars'] > 28 and row['warming'] is False
        assert row['price'] == out['price']
        assert row['rs_vs_btc_pct'] is None
        assert ('respect_dir' in row) and ('poi_type' in row) and ('dist_to_flip_pct' in row)
    assert out['timeframes']['1w']['respect_dir'] is None      # weekly keeps no respected trend
    assert out['timeframes']['1h']['bars'] == 599              # 600 bars, forming one dropped
    assert 80 <= out['timeframes']['1w']['bars'] <= 90         # weeklies built from ~600 dailies
    assert out['price'] == raw_series(600, 3600, NOW, seed=11)[-1][4]
    h1 = out['timeframes']['1h']
    assert h1['dist_to_flip_pct'] is not None
    assert h1['dist_to_flip_pct'] == wp._noodle_dist_to_flip_pct(
        h1['state'], h1['upper_band'], h1['lower_band'], h1['last_close'])


def test_compute_quote_side_symbol_drops_the_fee_suffix(monkeypatch):
    setup_compute(monkeypatch, pools=[pool_item(POOL3, 'WETH / AAA 0.3%', '90000', OTHER, TOKEN)])
    assert wp._onchain_check_compute('ethereum', TOKEN, now_ts=NOW)['symbol'] == 'AAA'


def test_compute_with_a_pasted_pool(monkeypatch):
    install_http(monkeypatch, pool=pool_item(POOL1, 'AAA / WETH', '250000', TOKEN, OTHER))
    install_candles(monkeypatch)
    out = wp._onchain_check_compute('ethereum', TOKEN, POOL1, now_ts=NOW)
    assert out['pool']['auto'] is False and out['pool']['address'] == POOL1 and out['alternatives'] == []


def test_compute_price_is_last_hourly_close_and_forming_bar_is_dropped(monkeypatch):
    setup_compute(monkeypatch)
    out = wp._onchain_check_compute('ethereum', TOKEN, now_ts=NOW)
    h1 = out['timeframes']['1h']
    assert out['price'] == h1['price']
    assert h1['last_close'] != h1['price']      # last_close is the last CLOSED bar


def test_compute_quote_side_symbol_and_thin_young_pool_notes(monkeypatch):
    young = datetime.fromtimestamp(NOW - 3 * 86400, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    setup_compute(monkeypatch, pools=[pool_item(POOL3, 'WETH / AAA', '4000', OTHER, TOKEN, created=young)])
    out = wp._onchain_check_compute('ethereum', TOKEN, now_ts=NOW)
    assert out['symbol'] == 'AAA' and out['pool']['side'] == 'quote'
    assert any('Thin pool' in n for n in out['notes'])
    assert any('days old' in n for n in out['notes'])


def test_compute_short_history_is_warming_not_a_failure(monkeypatch):
    setup_compute(monkeypatch, bars={'1h': 600, '4h': 600, '12h': 10, '1d': 12})
    out = wp._onchain_check_compute('ethereum', TOKEN, now_ts=NOW)
    assert out['timeframes']['12h']['warming'] is True
    assert out['timeframes']['1d']['warming'] is True
    assert out['timeframes']['1h']['warming'] is False


def test_compute_handles_sparse_trading(monkeypatch):
    setup_compute(monkeypatch, drop=0.6)
    out = wp._onchain_check_compute('ethereum', TOKEN, now_ts=NOW)
    assert out['timeframes']['1h']['bars'] >= 500           # gaps filled, bar count intact


def test_compute_unsupported_chain_is_the_plain_message(monkeypatch):
    install_http(monkeypatch, networks={'eth': 'Ethereum'})
    with pytest.raises(onchain_scan.OnchainError) as e:
        wp._onchain_check_compute('robinhood', TOKEN, now_ts=NOW)
    assert 'not supported by GeckoTerminal' in e.value.message


def test_compute_writes_nothing(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    setup_compute(monkeypatch)
    wp._onchain_check_compute('ethereum', TOKEN, now_ts=NOW)
    conn = portfolio_db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM noodle_state").fetchone()[0] == 0
    conn.close()


@pytest.mark.parametrize('seed', [11, 12, 13, 14, 15])
def test_row_matches_what_the_scan_stores(tmp_path, monkeypatch, seed):
    """Same candles through _noodle_store_symbol (the scan's writer) and
    _onchain_tf_row: every column the check returns must equal the stored one."""
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    series = {tf: onchain_scan.normalize_candles(raw_series(600, STEP[tf], NOW, seed=seed), STEP[tf], NOW)
              for tf in STEP}
    weekly = wp._weekly_from_dailies(series['1d'], 200)
    params = wp._trade_snapshot_settings()
    poi_settings = wp._scanner_settings()
    price = series['1h'][-1]['close']
    conn = portfolio_db.get_connection()
    wp._noodle_store_symbol(conn, 'ZZZ', price, None, weekly, series['1d'], series['12h'],
                            series['4h'], series['1h'], {}, {}, params)
    stored = {r['timeframe']: dict(r) for r in conn.execute("SELECT * FROM noodle_state WHERE symbol='ZZZ'")}
    conn.close()
    assert set(stored) == {'1w', '1d', '12h', '4h', '1h'}
    for tf, candles in (('1w', weekly), ('1d', series['1d']), ('12h', series['12h']),
                        ('4h', series['4h']), ('1h', series['1h'])):
        row = wp._onchain_tf_row(tf, candles, price, params, poi_settings, 'now')
        for k, v in row.items():
            if k in ('bars', 'warming', 'dist_to_flip_pct', 'computed_at', 'volume_24h', 'rs_vs_btc_pct'):
                continue
            sv = stored[tf][k]
            if isinstance(v, bool):
                v = int(v)
            assert sv == v, (tf, k, sv, v)


def test_poi_gets_the_forming_bar_and_bands_in_order(monkeypatch):
    seen = {}

    def spy(candles, direction, since, upper, lower, settings=None):
        seen.update(n=len(candles), last=candles[-1]['time'], upper=upper, lower=lower, direction=direction)
        return {'type': None, 'top': None, 'bottom': None, 'ts': None, 'at_band': None, 'count': None}
    monkeypatch.setattr(wp, "_trend_pois", spy)
    c = onchain_scan.normalize_candles(raw_series(600, 3600, NOW, seed=11), 3600, NOW)
    r = wp._onchain_tf_row('1h', c, c[-1]['close'], wp._trade_snapshot_settings(), wp._scanner_settings(), 'x')
    assert seen['n'] == len(c) and seen['last'] == c[-1]['time']
    assert seen['upper'] == r['upper_band'] and seen['lower'] == r['lower_band']
    assert seen['upper'] > seen['lower'] and seen['direction'] == r['respect_dir']


def test_parity_data_exercises_respect_and_poi():
    """Guards the parity test above: seed 11 must give a respected trend and a
    point of interest on every tradable timeframe, so the comparison means something."""
    for tf in ('1d', '12h', '4h', '1h'):
        c = onchain_scan.normalize_candles(raw_series(600, STEP[tf], NOW, seed=11), STEP[tf], NOW)
        r = wp._onchain_tf_row(tf, c, c[-1]['close'], wp._trade_snapshot_settings(), wp._scanner_settings(), 'x')
        assert r['respect_dir'] and r['poi_type'], tf


# -- route ----------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


URL = '/api/trading/scanner/onchain-check'


def test_route_needs_login():
    wp.app.config["TESTING"] = True
    r = wp.app.test_client().get(f'{URL}?chain=base&token={TOKEN}')
    assert r.status_code in (301, 302, 401)


@pytest.mark.parametrize("q,frag", [
    ("chain=nope&token=" + TOKEN, "Unknown chain"),
    ("chain=base", "Enter a token"),
    ("chain=base&token=0x12", "Invalid contract_address"),
    ("chain=solana&token=" + TOKEN, "Invalid contract_address"),
    ("chain=base&token=" + TOKEN + "&pool=zz", "Invalid pool address"),
])
def test_route_validation(client, monkeypatch, q, frag):
    monkeypatch.setattr(wp, "_onchain_check_compute", lambda *a, **k: pytest.fail("no compute"))
    r = client.get(f'{URL}?{q}')
    assert r.status_code == 400 and frag in r.get_json()['error']


def test_route_passes_normalized_args_and_returns_json(client, monkeypatch):
    seen = {}

    def fake(chain, token, pool):
        seen.update(chain=chain, token=token, pool=pool)
        return {'symbol': 'AAA'}
    monkeypatch.setattr(wp, "_onchain_check_compute", fake)
    r = client.get(f'{URL}?chain=base&token={TOKEN.upper().replace("0X", "0x")}&pool={POOL1}')
    assert r.status_code == 200 and r.get_json() == {'symbol': 'AAA'}
    assert seen == {'chain': 'base', 'token': TOKEN, 'pool': POOL1}
    r = client.get(f'{URL}?chain=base&token={TOKEN}')
    assert seen['pool'] is None


def test_route_pool_only_is_allowed(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(wp, "_onchain_check_compute", lambda c, t, p: seen.update(t=t, p=p) or {'ok': 1})
    assert client.get(f'{URL}?chain=base&pool={POOL1}').status_code == 200
    assert seen == {'t': '', 'p': POOL1}


def test_route_error_mapping_and_lock_release(client, monkeypatch):
    def rl(*a):
        raise onchain_scan.OnchainError("slow down", 429)
    monkeypatch.setattr(wp, "_onchain_check_compute", rl)
    r = client.get(f'{URL}?chain=base&token={TOKEN}')
    assert r.status_code == 429 and r.get_json()['error'] == 'slow down'

    def boom(*a):
        raise RuntimeError("secret detail")
    monkeypatch.setattr(wp, "_onchain_check_compute", boom)
    r = client.get(f'{URL}?chain=base&token={TOKEN}')
    assert r.status_code == 500 and 'secret detail' not in r.get_json()['error']
    assert not wp._ONCHAIN_CHECK_LOCK.locked()


def test_route_busy_when_another_check_runs(client, monkeypatch):
    monkeypatch.setattr(wp, "_onchain_check_compute", lambda *a: pytest.fail("no compute"))
    assert wp._ONCHAIN_CHECK_LOCK.acquire(blocking=False)
    try:
        r = client.get(f'{URL}?chain=base&token={TOKEN}')
        assert r.status_code == 409
    finally:
        wp._ONCHAIN_CHECK_LOCK.release()
