"""Tests for _dexscreener_audit_analyse, the pure helper behind the read-only
GET /api/spot/dexscreener-audit diagnostic. Covers the helper ONLY, with
hand-built payload fixtures and no network I/O and no database access - the
endpoint itself (which fetches fresh from DexScreener and reads
_calculate_spot_fifo) is intentionally not exercised here.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern, see
test_custom_tokens.py) so no thread starts.
"""
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

_dexscreener_audit_analyse = wp._dexscreener_audit_analyse

CONTRACT = "0xAAAA000000000000000000000000000000AAAA"


def _pair(chain_id, address=CONTRACT, price="1.0", liquidity_usd=1000, volume_h24=500,
          base_symbol="TOK", quote_symbol="USDC", dex_id="uniswap", pair_address="0xpair"):
    return {
        "chainId": chain_id,
        "dexId": dex_id,
        "pairAddress": pair_address,
        "baseToken": {"address": address, "symbol": base_symbol, "name": base_symbol},
        "quoteToken": {"symbol": quote_symbol},
        "priceUsd": price,
        "liquidity": {"usd": liquidity_usd},
        "volume": {"h24": volume_h24},
        "url": f"https://dexscreener.com/{chain_id}/{pair_address}",
    }


def test_deep_wrong_chain_pair_wins_unfiltered_but_loses_filtered():
    """The RUNNER/FOX scenario: two base-side pairs on different chains, the
    WRONG chain has deeper liquidity. unfiltered_price must pick the deep
    wrong-chain pair (replicating today's real bug); filtered_price must pick
    the correct-chain pair instead; agreement must be "differ". This is the
    most important test in the file.
    """
    payload = {"pairs": [
        _pair(chain_id="ethereum", price="5.0", liquidity_usd=999999),   # wrong chain, deep
        _pair(chain_id="robinhood", price="0.0002262", liquidity_usd=100),  # correct chain, shallow
    ]}
    result = _dexscreener_audit_analyse(payload, CONTRACT, "robinhood")

    assert result["unfiltered_price"] == 5.0
    assert result["unfiltered_chain_id"] == "ethereum"
    assert result["filtered_price"] == 0.0002262
    assert result["filtered_pair_count"] == 1
    assert result["agreement"] == "differ"
    assert result["non_base_pair_count"] == 0
    assert result["observed_chain_ids"] == ["ethereum", "robinhood"]
    assert len(result["base_pairs"]) == 2
    # base_pairs sorted by liquidity_usd descending
    assert result["base_pairs"][0]["chain_id"] == "ethereum"
    assert result["base_pairs"][0]["liquidity_usd"] == 999999
    assert result["base_pairs"][1]["chain_id"] == "robinhood"


def test_only_wrong_chain_pairs_filtered_empty():
    payload = {"pairs": [
        _pair(chain_id="ethereum", price="5.0", liquidity_usd=100),
        _pair(chain_id="base", price="6.0", liquidity_usd=200),
    ]}
    result = _dexscreener_audit_analyse(payload, CONTRACT, "robinhood")

    assert result["unfiltered_price"] is not None
    assert result["filtered_price"] is None
    assert result["filtered_pair_count"] == 0
    assert result["agreement"] == "filtered_empty"


def test_quote_side_pair_excluded_from_base_pairs_and_never_prices():
    """A pair where the queried address is the QUOTE token (not the base) must
    be excluded from base_pairs, counted in non_base_pair_count, and must
    never contribute a price to either selection."""
    quote_side_pair = {
        "chainId": "ethereum",
        "dexId": "uniswap",
        "pairAddress": "0xquoteside",
        "baseToken": {"address": "0xSOMEOTHERADDRESS", "symbol": "OTHER", "name": "Other"},
        "quoteToken": {"symbol": "TOK"},
        "priceUsd": "999.0",
        "liquidity": {"usd": 5000000},
        "volume": {"h24": 1000000},
        "url": "https://dexscreener.com/ethereum/0xquoteside",
    }
    payload = {"pairs": [quote_side_pair]}
    result = _dexscreener_audit_analyse(payload, CONTRACT, "ethereum")

    assert result["base_pairs"] == []
    assert result["non_base_pair_count"] == 1
    assert result["unfiltered_price"] is None
    assert result["filtered_price"] is None
    assert result["agreement"] == "both_empty"
    assert result["observed_chain_ids"] == []


def test_empty_payload_dict_no_exception():
    result = _dexscreener_audit_analyse({}, CONTRACT, "ethereum")
    assert result["base_pairs"] == []
    assert result["non_base_pair_count"] == 0
    assert result["observed_chain_ids"] == []
    assert result["unfiltered_price"] is None
    assert result["unfiltered_chain_id"] is None
    assert result["filtered_price"] is None
    assert result["filtered_pair_count"] == 0
    assert result["agreement"] == "both_empty"


def test_payload_none_no_exception():
    result = _dexscreener_audit_analyse(None, CONTRACT, "ethereum")
    assert result["base_pairs"] == []
    assert result["non_base_pair_count"] == 0
    assert result["unfiltered_price"] is None
    assert result["filtered_price"] is None
    assert result["agreement"] == "both_empty"


def test_pair_missing_liquidity_and_volume_no_exception():
    pair = {
        "chainId": "ethereum",
        "dexId": "uniswap",
        "pairAddress": "0xpair",
        "baseToken": {"address": CONTRACT, "symbol": "TOK", "name": "TOK"},
        "quoteToken": {"symbol": "USDC"},
        "priceUsd": "2.5",
        "url": "https://dexscreener.com/ethereum/0xpair",
        # liquidity and volume keys deliberately absent
    }
    payload = {"pairs": [pair]}
    result = _dexscreener_audit_analyse(payload, CONTRACT, "ethereum")

    assert len(result["base_pairs"]) == 1
    assert result["base_pairs"][0]["liquidity_usd"] == 0.0
    assert result["base_pairs"][0]["volume_h24"] == 0.0
    assert result["base_pairs"][0]["price_usd"] == 2.5
    assert result["unfiltered_price"] == 2.5
    assert result["filtered_price"] == 2.5
    assert result["agreement"] == "match"


def test_observed_chain_ids_are_verbatim_including_mixed_case():
    payload = {"pairs": [
        _pair(chain_id="Ethereum", price="1.0", liquidity_usd=10),
        _pair(chain_id="BASE", price="2.0", liquidity_usd=20),
        _pair(chain_id="base", price="3.0", liquidity_usd=30),
    ]}
    result = _dexscreener_audit_analyse(payload, CONTRACT, "base")

    # Verbatim, case-preserved, sorted, and deduped only on exact string match
    # ("BASE" and "base" are NOT the same string and both survive).
    assert result["observed_chain_ids"] == ["BASE", "Ethereum", "base"]
    for p in result["base_pairs"]:
        assert p["chain_id"] in ("Ethereum", "BASE", "base")

    # filtered_price matches case-insensitively against the queried chain
    # ("base"), so both "BASE" and "base" pairs qualify; "base" wins on
    # liquidity (30 > 20).
    assert result["filtered_price"] == 3.0
    assert result["filtered_pair_count"] == 2
