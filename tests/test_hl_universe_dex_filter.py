"""The scanner's market list keeps only HIP-3 exchanges the candle lookup can name.

Oct 14 (ruling B): _hl_fetch_top_volume listed every HIP-3 exchange in
perpDexs and stripped the 'dex:' prefix, but _hl_refresh_universes loads only
the native universe and _HL_TRADFI_DEX ('xyz'), so _hl_resolve_coin handed
candleSnapshot a bare name (e.g. 'ANTH' for 'vntl:ANTH') and every candle
fetch for those markets answered 500. The list now skips every other HIP-3
exchange (not fetched at all) and logs the skipped set when it changes.

No network: _hl_post is replaced with a fake keyed on the request payload.
The web_portfolio import spawns schedulers on import; threading.Thread.start
is neutralized during import (established pattern).
"""
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start


def _ctx(vol, px):
    return {'dayNtlVlm': str(vol), 'markPx': str(px)}


# Each dex: (universe names as HL returns them, matching asset contexts).
DEXES = {
    '':     (['BTC', 'kBONK'], [_ctx(5e9, 100000), _ctx(2e7, 0.02)]),
    'xyz':  (['xyz:TSLA', 'xyz:NVDA'], [_ctx(3e6, 250), _ctx(4e6, 180)]),
    'flx':  (['flx:TSLA'], [_ctx(9e6, 251)]),            # more volume than xyz:TSLA
    'vntl': (['vntl:ANTH', 'vntl:OAI'], [_ctx(1e6, 40), _ctx(2e6, 60)]),
}
SPOT = ({'tokens': [{'index': 0, 'name': 'PURR'}, {'index': 1, 'name': 'USDC'}],
         'universe': [{'tokens': [0, 1], 'isCanonical': True}]},
        [_ctx(5e5, 0.2)])


class FakeHL:
    def __init__(self, dexs=(None, 'xyz', 'flx', 'vntl'), perp_dexs_fails=False):
        self.calls = []
        self.dexs = dexs
        self.perp_dexs_fails = perp_dexs_fails

    def __call__(self, payload, timeout=10, retries=4):
        self.calls.append(dict(payload))
        kind = payload.get('type')
        if kind == 'perpDexs':
            if self.perp_dexs_fails:
                raise RuntimeError("HL down")
            return [None if d is None else {'name': d, 'fullName': d + ' dex'} for d in self.dexs]
        if kind == 'metaAndAssetCtxs':
            names, ctxs = DEXES[payload.get('dex', '')]
            return [{'universe': [{'name': n} for n in names]}, ctxs]
        if kind == 'meta':
            names, _ = DEXES[payload.get('dex', '')]
            return {'universe': [{'name': n} for n in names]}
        if kind == 'spotMetaAndAssetCtxs':
            return list(SPOT)
        raise AssertionError(f"unexpected HL call {payload}")

    def meta_dexes(self):
        return [c.get('dex', '') for c in self.calls if c['type'] == 'metaAndAssetCtxs']


@pytest.fixture
def hl(monkeypatch):
    fake = FakeHL()
    monkeypatch.setattr(wp, '_hl_post', fake)
    monkeypatch.setattr(wp, '_HL_SKIPPED_DEXES_LOGGED', None)
    return fake


def _by_symbol(assets):
    return {a['symbol']: a for a in assets}


def test_only_native_and_xyz_dexes_are_fetched(hl):
    wp._hl_fetch_top_volume(n=None, limit=None)
    assert hl.meta_dexes() == ['', 'xyz']          # flx and vntl never fetched


def test_other_hip3_markets_are_left_out(hl):
    assets = _by_symbol(wp._hl_fetch_top_volume(n=None, limit=None))
    assert 'ANTH-USDT' not in assets and 'OAI-USDT' not in assets
    assert {'BTC-USDT', 'kBONK-USDT', 'TSLA-USDT', 'NVDA-USDT', 'PURR-USDC'} == set(assets)
    assert assets['NVDA-USDT']['asset_type'] == 'tradfi'
    assert assets['BTC-USDT']['asset_type'] == 'crypto'


def test_ticker_on_two_exchanges_takes_xyz_volume_and_price(hl):
    tsla = _by_symbol(wp._hl_fetch_top_volume(n=None, limit=None))['TSLA-USDT']
    assert tsla['volume_24h'] == 3e6 and tsla['price'] == 250.0   # xyz's, not flx's 9e6 / 251


def test_every_listed_perp_resolves_to_a_name_candles_accept(hl, monkeypatch):
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, 'crypto', None)
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, 'xyz', None)
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, 'fetched_at', 0.0)
    perps = [a for a in wp._hl_fetch_top_volume(n=None, limit=None)
             if a['symbol'].endswith('-USDT')]
    assert len(perps) == 4                         # BTC, kBONK, TSLA, NVDA: never vacuous
    native = set(DEXES[''][0])
    xyz = set(DEXES['xyz'][0])
    for a in perps:
        coin = wp._hl_resolve_coin(a['name'])
        assert coin in native or coin in xyz, (a['name'], coin)


def test_universe_refresh_still_asks_for_xyz(hl, monkeypatch):
    # All three keys restored after the test: the refresh writes fake maps.
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, 'crypto', None)
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, 'xyz', None)
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, 'fetched_at', 0.0)
    wp._hl_refresh_universes(force=True)
    assert {'type': 'meta', 'dex': 'xyz'} in hl.calls


def test_skipped_set_logged_once_then_on_change(hl, capsys):
    wp._hl_fetch_top_volume(n=None, limit=None)
    first = capsys.readouterr().out
    assert first.count('[HL] market list: skipped 2 HIP-3 exchange(s)') == 1
    assert "can't name: flx, vntl" in first

    wp._hl_fetch_top_volume(n=None, limit=None)
    assert '[HL] market list' not in capsys.readouterr().out   # same set: quiet

    hl.dexs = (None, 'xyz', 'vntl', 'km')
    wp._hl_fetch_top_volume(n=None, limit=None)
    assert "can't name: km, vntl" in capsys.readouterr().out


def test_unexpected_perp_dexs_answer_is_not_logged(monkeypatch, capsys):
    fake = FakeHL()
    monkeypatch.setattr(wp, '_hl_post', lambda p, timeout=10, retries=4:
                        {'error': 'x'} if p.get('type') == 'perpDexs' else fake(p))
    monkeypatch.setattr(wp, '_HL_SKIPPED_DEXES_LOGGED', None)
    wp._hl_fetch_top_volume(n=None, limit=None)
    assert '[HL] market list' not in capsys.readouterr().out
    assert wp._HL_SKIPPED_DEXES_LOGGED is None


def test_perp_dexs_failure_is_native_only_and_not_logged(monkeypatch, capsys):
    fake = FakeHL(perp_dexs_fails=True)
    monkeypatch.setattr(wp, '_hl_post', fake)
    monkeypatch.setattr(wp, '_HL_SKIPPED_DEXES_LOGGED', ('flx', 'vntl'))
    assets = _by_symbol(wp._hl_fetch_top_volume(n=None, limit=None))
    assert fake.meta_dexes() == ['']
    assert 'BTC-USDT' in assets and 'TSLA-USDT' not in assets
    assert '[HL] market list' not in capsys.readouterr().out
    assert wp._HL_SKIPPED_DEXES_LOGGED == ('flx', 'vntl')   # memo untouched


def test_only_xyz_listed_logs_none_once(monkeypatch, capsys):
    fake = FakeHL(dexs=(None, 'xyz'))
    monkeypatch.setattr(wp, '_hl_post', fake)
    monkeypatch.setattr(wp, '_HL_SKIPPED_DEXES_LOGGED', None)
    wp._hl_fetch_top_volume(n=None, limit=None)
    wp._hl_fetch_top_volume(n=None, limit=None)
    out = capsys.readouterr().out
    assert out.count("[HL] market list: skipped 0 HIP-3 exchange(s) the candle lookup can't name: none") == 1
