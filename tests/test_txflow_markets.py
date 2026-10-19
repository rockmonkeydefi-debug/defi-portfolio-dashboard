"""TxFlow market helpers for the Trends scanner (Landing 53, txflow_markets.py).

Pure functions: names and aliases, the match (tagged / mismatch / unknown /
only / ignored), the match table build and its carry-forward, the stored
symbol, the candle answer parser and request body, and the 24h volume. No
network, no DB. The facts in the cases (QNT 198 vs xyz QNT 38.2, TxFlow QNTX
= xyz QNT, 1000BONK = kBONK, RAY listed twice) are from the Oct 19 recon in
SPEC_txflow_trends.md; every price here is made up.
"""
import pytest

import txflow_markets as tm

HL = {                      # UPPER Hyperliquid name -> last prices of every perp with that name
    "BTC": [100000.0],
    "ETH": [4000.0],
    "KBONK": [0.025],
    "GOLD": [2400.0, 3.1],  # a main-exchange token and the xyz commodity share the name
    "QNT": [38.2],          # xyz QNT
    "NVDA": [150.0],
    "XRP": [None],          # a perp whose price is missing
}


# ── names ───────────────────────────────────────────────────────────────

def test_hl_name_for_alias_kilo_and_plain():
    assert tm.hl_name_for("XAU") == "GOLD"
    assert tm.hl_name_for("xag") == "SILVER"
    assert tm.hl_name_for("QNTX") == "QNT"
    assert tm.hl_name_for("1000BONK") == "KBONK"
    assert tm.hl_name_for("1000pepe") == "KPEPE"
    assert tm.hl_name_for("btc") == "BTC"
    assert tm.hl_name_for(" eth ") == "ETH"
    assert tm.hl_name_for("1000") == "1000"          # no ticker behind the 1000
    assert tm.hl_name_for("1000000MOG") == "1000000MOG"
    assert tm.hl_name_for(None) == ""


def test_every_alias_target_is_the_confirmed_one():
    assert tm.TXFLOW_ALIASES == {
        "XAU": "GOLD", "XAG": "SILVER", "XPT": "PLATINUM", "XPD": "PALLADIUM",
        "BZ": "BRENTOIL", "SAMSUNG": "SMSN", "USDJPY": "JPY", "EURUSD": "EUR", "QNTX": "QNT"}


def test_ignored_are_stablecoins_and_xaut():
    assert tm.is_ignored("USDC") and tm.is_ignored("usdt") and tm.is_ignored("XAUT")
    assert not tm.is_ignored("XAU") and not tm.is_ignored("BTC")


def test_stored_symbol_round_trip():
    assert tm.stored_symbol("QNT") == "txflow:QNT"
    assert tm.is_stored_symbol("txflow:QNT") and not tm.is_stored_symbol("QNT")
    assert tm.is_stored_symbol(None) is False
    assert tm.bare_name("txflow:1000BONK") == "1000BONK"
    assert tm.bare_name("BTC") == "BTC"


# ── classify ────────────────────────────────────────────────────────────

def test_same_name_close_price_is_tagged():
    assert tm.classify("BTC", HL, 100110.0) == ("tagged", "BTC")        # ~0.11% apart
    assert tm.classify("btc", HL, 99000.0) == ("tagged", "BTC")


def test_alias_and_kilo_name_are_tagged_to_the_hyperliquid_key():
    assert tm.classify("XAU", HL, 2410.0) == ("tagged", "GOLD")
    assert tm.classify("1000BONK", HL, 0.0251) == ("tagged", "KBONK")
    assert tm.classify("QNTX", HL, 38.3) == ("tagged", "QNT")


def test_same_name_different_price_is_a_mismatch_not_a_tag():
    # TxFlow's QNT (198) is not xyz's QNT (38.2).
    assert tm.classify("QNT", HL, 198.0) == ("mismatch", "QNT")


def test_name_on_both_exchanges_tags_when_either_price_is_close():
    assert tm.classify("GOLD", HL, 3.12) == ("tagged", "GOLD")
    assert tm.classify("GOLD", HL, 2395.0) == ("tagged", "GOLD")
    assert tm.classify("GOLD", HL, 50.0) == ("mismatch", "GOLD")


def test_tolerance_edges():
    assert tm.classify("BTC", HL, 105000.0) == ("tagged", "BTC")        # exactly 5%
    assert tm.classify("BTC", HL, 105100.0) == ("mismatch", "BTC")
    assert tm.classify("BTC", HL, 95000.0) == ("tagged", "BTC")
    assert tm.classify("BTC", HL, 94900.0) == ("mismatch", "BTC")


def test_missing_price_on_either_side_is_unknown_never_only():
    assert tm.classify("BTC", HL, None) == ("unknown", "BTC")
    assert tm.classify("BTC", HL, 0) == ("unknown", "BTC")
    assert tm.classify("BTC", HL, -5.0) == ("unknown", "BTC")
    assert tm.classify("BTC", HL, True) == ("unknown", "BTC")
    assert tm.classify("XRP", HL, 2.0) == ("unknown", "XRP")            # Hyperliquid price missing
    assert tm.classify("BTC", {"BTC": []}, 100000.0) == ("unknown", "BTC")


def test_a_non_finite_price_is_unknown_not_a_mismatch():
    inf, nan = float("inf"), float("nan")
    assert tm.classify("BTC", HL, nan) == ("unknown", "BTC")
    assert tm.classify("BTC", HL, inf) == ("unknown", "BTC")
    assert tm.classify("BTC", {"BTC": [nan]}, 100000.0) == ("unknown", "BTC")
    assert tm.classify("BTC", {"BTC": [nan, 100000.0]}, 100100.0) == ("tagged", "BTC")   # one usable price is enough


def test_name_on_neither_exchange_is_only_and_stables_are_ignored():
    assert tm.classify("COTI", HL, 0.1) == ("only", None)
    assert tm.classify("SKHYNIX", HL, 100.0) == ("only", None)          # SKHY on xyz is another instrument
    assert tm.classify("USDC", HL, 1.0) == ("ignored", None)
    assert tm.classify("XAUT", HL, 2400.0) == ("ignored", None)


# ── build_match ─────────────────────────────────────────────────────────

PRICES = {"BTC": 100100.0, "XAU": 2410.0, "1000BONK": 0.0252, "QNT": 198.0, "QNTX": 38.2}


def _price_fn(name):
    if name not in PRICES:
        raise AssertionError(f"price asked for {name}")
    return PRICES[name]


def test_build_match_tags_only_and_mismatch():
    tokens = ["BTC", "XAU", "1000BONK", "QNT", "QNTX", "COTI", "USDC", "XAUT", "COTI"]
    built = tm.build_match(tokens, HL, _price_fn)
    assert built["tags"] == {"BTC": "BTC", "GOLD": "XAU", "KBONK": "1000BONK", "QNT": "QNTX"}
    assert built["only"] == ["QNT", "COTI", "COTI"]      # the mismatch is TxFlow's own market
    assert built["mismatch"] == ["QNT"]
    assert built["unknown"] == []


def test_build_match_asks_no_price_for_names_hyperliquid_lacks():
    asked = []

    def price_fn(name):
        asked.append(name)
        return 1.0
    tm.build_match(["COTI", "BAT", "USDC"], HL, price_fn)
    assert asked == []


def test_failed_price_is_unknown_and_other_tokens_continue():
    def price_fn(name):
        if name == "BTC":
            raise ValueError("HTTP 500")
        return PRICES[name]
    built = tm.build_match(["BTC", "XAU"], HL, price_fn)
    assert built["tags"] == {"GOLD": "XAU"}
    assert built["unknown"] == ["BTC"]
    assert built["only"] == []                    # a failed call never makes a duplicate row


def test_unknown_token_keeps_what_the_previous_table_held():
    previous = {"tags": {"BTC": "BTC"}, "only": ["QNT"], "built_at": 1.0}

    def price_fn(name):
        raise ValueError("HTTP 429")
    built = tm.build_match(["BTC", "QNT", "ETH"], HL, price_fn, previous=previous)
    assert built["tags"] == {"BTC": "BTC"}          # kept
    assert built["only"] == ["QNT"]                 # kept
    assert sorted(built["unknown"]) == ["BTC", "ETH", "QNT"]   # ETH had no earlier answer: left out
    assert "ETH" not in built["tags"].values()


def test_retry_lists_the_tokens_where_only_txflows_price_is_missing():
    def price_fn(name):
        if name in ("BTC", "XRP"):
            return None                              # TxFlow has no usable price for either
        return PRICES[name]
    built = tm.build_match(["BTC", "XRP", "XAU"], HL, price_fn)
    assert sorted(built["unknown"]) == ["BTC", "XRP"]
    assert built["retry"] == ["BTC"]                 # XRP's Hyperliquid price is missing too: asking TxFlow again fixes nothing
    assert built["tags"] == {"GOLD": "XAU"}


def test_a_clean_build_has_nothing_to_retry():
    assert tm.build_match(["BTC", "XAU", "COTI"], HL, _price_fn)["retry"] == []


def test_a_raised_price_call_is_also_worth_retrying():
    def price_fn(name):
        raise ValueError("HTTP 500")
    assert tm.build_match(["ETH"], HL, price_fn)["retry"] == ["ETH"]


def test_match_aborted_passes_through_build_match():
    def price_fn(name):
        raise tm.MatchAborted("locked")
    with pytest.raises(tm.MatchAborted):
        tm.build_match(["BTC"], HL, price_fn)


def test_heartbeat_runs_after_every_token():
    beats = []
    tm.build_match(["COTI", "USDC", "BAT"], HL, _price_fn, heartbeat=lambda i, n: beats.append((i, n)))
    assert beats == [(1, 3), (2, 3), (3, 3)]


def test_first_tagged_token_wins_a_hyperliquid_name():
    tokens = ["QNTX", "QNT"]
    built = tm.build_match(tokens, HL, lambda n: {"QNTX": 38.2, "QNT": 38.1}[n])
    assert built["tags"] == {"QNT": "QNTX"}


# ── clean_match / candidates / txflow_name_for ─────────────────────────

def test_clean_match_validates_and_normalises():
    assert tm.clean_match(None) is None
    assert tm.clean_match({"tags": [], "only": []}) is None
    assert tm.clean_match({"tags": {}, "only": {}}) is None
    got = tm.clean_match({"tags": {"btc": "BTC", 3: "x", "ETH": 5, "": "y"},
                          "only": ["COTI", "COTI", 7, ""], "built_at": 12})
    assert got == {"tags": {"BTC": "BTC"}, "only": ["COTI"], "built_at": 12.0}
    assert tm.clean_match({"tags": {}, "only": [], "built_at": "x"})["built_at"] is None
    assert tm.clean_match({"tags": {}, "only": [], "built_at": True})["built_at"] is None


def test_candidates_are_the_only_names_still_listed_in_token_order():
    match = {"tags": {}, "only": ["COTI", "BAT", "GONE", "COTI"]}
    assert tm.candidates(["BAT", "X", "COTI"], match) == ["COTI", "BAT"]
    assert tm.candidates(["BAT"], None) == []


def test_txflow_name_for_stored_and_tagged_symbols():
    tags = {"KBONK": "1000BONK", "BTC": "BTC"}
    assert tm.txflow_name_for("txflow:COTI", tags) == "COTI"
    assert tm.txflow_name_for("kBONK", tags) == "1000BONK"
    assert tm.txflow_name_for("btc", tags) == "BTC"
    assert tm.txflow_name_for("DOGE", tags) is None
    assert tm.txflow_name_for("txflow:", tags) is None
    assert tm.txflow_name_for("BTC", None) is None


# ── answers and requests ──────────────────────────────────────────────

def test_parse_spot_meta_dedupes_and_skips_junk():
    answer = {"tokens": [{"name": "BTC"}, {"name": "RAY"}, {"name": "RAY"}, {"name": " ETH "},
                         {"name": ""}, {"name": 5}, "x", {"index": 3}]}
    assert tm.parse_spot_meta(answer) == ["BTC", "RAY", "ETH"]
    assert tm.parse_spot_meta({"tokens": "no"}) == []
    assert tm.parse_spot_meta([]) == []
    assert tm.parse_spot_meta(None) == []


def test_parse_candles_converts_ms_to_seconds_and_floats():
    raw = [{"t": 1_700_003_600_000, "o": "2", "h": "3", "l": "1", "c": "2.5", "v": "10"},
           {"t": 1_700_000_000_000, "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "7", "n": 4}]
    got = tm.parse_candles(raw)
    assert [c["time"] for c in got] == [1_700_000_000, 1_700_003_600]      # oldest first
    assert got[0] == {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 7.0, "time": 1_700_000_000}


def test_parse_candles_skips_malformed_bars_and_dedupes_open_times():
    raw = [{"t": 1000, "o": "1", "h": "1", "l": "1", "c": "1", "v": "1"},
           {"t": 1000, "o": "2", "h": "2", "l": "2", "c": "2", "v": "2"},
           {"o": "1"}, {"t": "x", "o": "1", "h": "1", "l": "1", "c": "1", "v": "1"}, "junk", None]
    got = tm.parse_candles(raw)
    assert len(got) == 1 and got[0]["close"] == 2.0


def test_parse_candles_skips_non_finite_and_oversized_numbers():
    good = {"t": 2_000_000, "o": "1", "h": "1", "l": "1", "c": "1", "v": "1"}
    raw = [good,
           {"t": 3_000_000, "o": "NaN", "h": "1", "l": "1", "c": "1", "v": "1"},
           {"t": 4_000_000, "o": "1", "h": "1", "l": "1", "c": "inf", "v": "1"},
           {"t": 5_000_000, "o": "1", "h": "1", "l": "1", "c": "1", "v": "-Infinity"},
           {"t": float("inf"), "o": "1", "h": "1", "l": "1", "c": "1", "v": "1"},       # int(inf) overflows
           {"t": float("nan"), "o": "1", "h": "1", "l": "1", "c": "1", "v": "1"}]
    got = tm.parse_candles(raw)
    assert [c["time"] for c in got] == [2000]


def test_parse_candles_a_list_with_no_usable_bar_is_an_error():
    """Other field names (or all bars broken) must not read as 'a market with no bars'."""
    with pytest.raises(ValueError):
        tm.parse_candles([{"time": 1, "close": 2}])
    with pytest.raises(ValueError):
        tm.parse_candles(["junk", None])
    with pytest.raises(ValueError):
        tm.parse_candles([{"t": 1000, "o": "NaN", "h": "1", "l": "1", "c": "1", "v": "1"}])


def test_parse_candles_refusal_is_an_error_not_an_empty_series():
    with pytest.raises(ValueError):
        tm.parse_candles({"error": "not allowed"})
    with pytest.raises(ValueError):
        tm.parse_candles(None)
    assert tm.parse_candles([]) == []


def test_candle_request_body_is_hyperliquids_shape_under_the_bare_name():
    body = tm.candle_request("BTC", "1h", 2800, 1_760_000_000_000)
    assert body == {"type": "candleSnapshot", "req": {
        "coin": "BTC", "interval": "1h",
        "startTime": 1_760_000_000_000 - 2800 * 3_600_000, "endTime": 1_760_000_000_000}}
    assert tm.candle_request("QNT", "1d", 700, 10 ** 13)["req"]["startTime"] == 10 ** 13 - 700 * 86_400_000
    assert tm.candle_request("QNT", "12h", 300, 10 ** 13)["req"]["interval"] == "12h"
    with pytest.raises(KeyError):
        tm.candle_request("QNT", "5m", 3, 10 ** 13)


# ── volume ──────────────────────────────────────────────────────────────

HOUR = 3600


def _bars(first_open, n, volume=2.0, close=10.0):
    return [{"time": first_open + i * HOUR, "volume": volume, "close": close, "open": close,
             "high": close, "low": close} for i in range(n)]


def test_volume_is_the_24_closed_bars_before_the_forming_hour():
    now = 1_700_002_800
    end = (now // HOUR) * HOUR                 # the forming bar's open
    bars = _bars(end - 30 * HOUR, 31)          # 30 closed hours before it, plus the forming bar
    assert tm.volume_24h(bars, now) == pytest.approx(24 * 2.0 * 10.0)


def test_volume_counts_a_missing_hour_as_none_by_time_not_by_count():
    now = 1_700_002_800
    end = (now // HOUR) * HOUR
    bars = _bars(end - 24 * HOUR, 24)
    del bars[5]                                # TxFlow listed no bar for a quiet hour
    assert tm.volume_24h(bars, now) == pytest.approx(23 * 2.0 * 10.0)


def test_volume_ignores_the_forming_bar_older_bars_and_junk():
    now = 1_700_002_800
    end = (now // HOUR) * HOUR
    bars = _bars(end - 26 * HOUR, 27)          # two bars older than 24h, 24 closed, one forming
    bars.append({"time": None, "volume": 5.0, "close": 5.0})
    assert tm.volume_24h(bars, now) == pytest.approx(24 * 2.0 * 10.0)
    assert tm.volume_24h([], now) == 0.0
    assert tm.volume_24h(None, now) == 0.0


# ── last_close ──────────────────────────────────────────────────────────

def test_last_close_is_the_newest_bars_close_when_it_is_fresh():
    now = 1_700_000_000
    bars = [{"time": now - 5 * HOUR, "close": 1.0}, {"time": now - 1000, "close": 2.0}]
    assert tm.last_close(bars, now) == 2.0


def test_last_close_is_none_for_a_market_that_has_not_traded_lately():
    now = 1_700_000_000
    bars = [{"time": now - 3 * HOUR, "close": 2.0}]
    assert tm.last_close(bars, now) is None                         # older than the 2h limit
    assert tm.last_close(bars, now, max_age=4 * HOUR) == 2.0
    assert tm.last_close([{"time": now - 2 * HOUR, "close": 2.0}], now) == 2.0     # the limit itself is still fresh


def test_last_close_is_none_without_bars_or_a_time():
    assert tm.last_close([], 1_700_000_000) is None
    assert tm.last_close(None, 1_700_000_000) is None
    assert tm.last_close([{"close": 2.0}], 1_700_000_000) is None
