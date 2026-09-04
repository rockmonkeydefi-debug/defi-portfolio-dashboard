"""Tests for _get_spot_price_for_position - the chain-filtered per-position
price lookup that replaces the symbol-only, unfiltered _get_spot_price call in
api_spot_pnl. Every test injects _fetch; none perform network I/O or open the
database. _spot_position_price_cache is cleared at the start of every test so
tests don't leak state into each other.
"""
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

_get_spot_price_for_position = wp._get_spot_price_for_position


def _clear_cache():
    wp._spot_position_price_cache.clear()


def _pair(chain_id, address, price, liquidity_usd, volume_h24=0):
    return {
        "chainId": chain_id,
        "baseToken": {"address": address, "symbol": "TOK"},
        "quoteToken": {"symbol": "USDC"},
        "priceUsd": str(price),
        "liquidity": {"usd": liquidity_usd},
        "volume": {"h24": volume_h24},
    }


CHIP_ADDR = "0x0c1c1c109fe34733fca54b82d7b46b75cfb71f6e"


def test_chain_filter_picks_correct_chain_over_deeper_wrong_chain_liquidity():
    """The CHIP regression, and the most important test in the file: a deep
    arbitrum pair must NOT win just because it has more liquidity than the
    base pair on the position's actual chain."""
    _clear_cache()
    pos = {'symbol': 'CHIP', 'chain': 'base', 'contract_address': CHIP_ADDR}
    cfg = {'price_source': 'dexscreener', 'contract_address': CHIP_ADDR}
    payload = {"pairs": [
        _pair("arbitrum", CHIP_ADDR, 0.05867, 1070825),
        _pair("base", CHIP_ADDR, 0.05886, 127346),
    ]}
    price = _get_spot_price_for_position(pos, cfg, _fetch=lambda addr: payload)
    assert price == 0.05886


def test_no_pair_on_positions_chain_returns_none_no_fallback():
    _clear_cache()
    pos = {'symbol': 'XYZ', 'chain': 'robinhood', 'contract_address': '0xabc'}
    cfg = {'price_source': 'dexscreener', 'contract_address': '0xabc'}
    payload = {"pairs": [
        _pair("ethereum", '0xabc', 1.0, 500),
        _pair("base", '0xabc', 2.0, 900),
    ]}
    calls = []
    price = _get_spot_price_for_position(pos, cfg, _fetch=lambda addr: (calls.append(addr), payload)[1])
    assert price is None
    assert calls == ['0xabc']  # _fetch WAS called (dexscreener path) - no unfiltered fallback taken


def test_manual_source_returns_none_and_never_fetches():
    _clear_cache()
    pos = {'symbol': 'GG', 'chain': 'base', 'contract_address': '0xdef'}
    cfg = {'price_source': 'manual', 'contract_address': '0xdef'}
    called = []
    price = _get_spot_price_for_position(pos, cfg, _fetch=lambda addr: called.append(addr))
    assert price is None
    assert called == []


def test_no_cfg_routes_to_coingecko_path_never_fetches(monkeypatch):
    _clear_cache()
    sentinel = object()
    reached = []

    def fake_get_spot_price(symbol):
        reached.append(symbol)
        return sentinel
    monkeypatch.setattr(wp, '_get_spot_price', fake_get_spot_price)

    pos = {'symbol': 'BTC', 'chain': 'base', 'contract_address': '0xaaa'}
    called = []
    price = _get_spot_price_for_position(pos, None, _fetch=lambda addr: called.append(addr))
    assert price is sentinel
    assert reached == ['BTC']
    assert called == []


def test_dexscreener_source_but_blank_chain_routes_to_fallback_never_fetches(monkeypatch):
    _clear_cache()
    sentinel = object()
    reached = []

    def fake_get_spot_price(symbol):
        reached.append(symbol)
        return sentinel
    monkeypatch.setattr(wp, '_get_spot_price', fake_get_spot_price)

    pos = {'symbol': 'ZZZ', 'chain': '', 'contract_address': '0xbbb'}
    cfg = {'price_source': 'dexscreener', 'contract_address': '0xbbb'}
    called = []
    price = _get_spot_price_for_position(pos, cfg, _fetch=lambda addr: called.append(addr))
    assert price is sentinel
    assert reached == ['ZZZ']
    assert called == []


def test_cache_hits_on_same_chain_and_address_but_tao_scenario_two_chains_two_prices():
    """Cache half: two calls with the same chain+address hit _fetch once.
    TAO half: the SAME address on two DIFFERENT chains hits _fetch twice and
    returns the two different prices - proving chain is part of the cache key.
    """
    _clear_cache()
    tao_addr = '0xtaoaddress'
    calls = []

    def fetch_base(addr):
        calls.append(('base-call', addr))
        return {"pairs": [_pair("base", tao_addr, 228.57, 1000)]}

    def fetch_robinhood(addr):
        calls.append(('robinhood-call', addr))
        return {"pairs": [_pair("robinhood", tao_addr, 226.68, 1000)]}

    pos_base = {'symbol': 'TAO', 'chain': 'base', 'contract_address': tao_addr}
    pos_rh = {'symbol': 'TAO', 'chain': 'robinhood', 'contract_address': tao_addr}
    cfg = {'price_source': 'dexscreener', 'contract_address': tao_addr}

    p1 = _get_spot_price_for_position(pos_base, cfg, _fetch=fetch_base)
    p2 = _get_spot_price_for_position(pos_base, cfg, _fetch=fetch_base)  # same chain+addr -> cached
    assert p1 == 228.57
    assert p2 == 228.57
    assert len([c for c in calls if c[0] == 'base-call']) == 1

    p3 = _get_spot_price_for_position(pos_rh, cfg, _fetch=fetch_robinhood)  # different chain -> fetches again
    assert p3 == 226.68
    assert len([c for c in calls if c[0] == 'robinhood-call']) == 1
    assert p1 != p3


def test_fetch_raising_exception_returns_none_and_writes_no_cache():
    _clear_cache()
    pos = {'symbol': 'BOOM', 'chain': 'base', 'contract_address': '0xboom'}
    cfg = {'price_source': 'dexscreener', 'contract_address': '0xboom'}

    def boom(addr):
        raise RuntimeError("network exploded")

    price = _get_spot_price_for_position(pos, cfg, _fetch=boom)
    assert price is None
    assert wp._spot_position_price_cache.get('base|0xboom') is None
