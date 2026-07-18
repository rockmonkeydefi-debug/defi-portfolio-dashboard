"""Unit tests for case-insensitive HL coin resolution (Phase 3a).

Regression guard: HL lists 1000x-denominated memecoins with a lowercase 'k'
prefix (kBONK/kPEPE/kSHIB). Watchlist entries are stored upper-cased
(KBONKUSDT); the resolver must hand candleSnapshot HL's own canonical casing,
not the upper-cased form (which HL rejects with an HTTPError).

The web_portfolio import spawns a background scheduler on non-__main__ import;
we neutralize threading.Thread.start during import (established pattern) so no
thread starts. The HL universe cache is populated directly (no network) with a
mocked meta universe.
"""
import time
import threading

import pytest

# ── Import web_portfolio import-safe (suppress scheduler autostart) ──
_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start


# Mocked HL meta universe: canonical casing exactly as HL returns it.
MOCK_CRYPTO_NAMES = ["BTC", "ETH", "PURR", "kBONK", "kPEPE", "kSHIB"]


@pytest.fixture
def mocked_universe(monkeypatch):
    """Populate the resolver's cache with the mocked universe and mark it fresh
    so _hl_refresh_universes() short-circuits (no network)."""
    crypto = {name.upper(): name for name in MOCK_CRYPTO_NAMES}
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "crypto", crypto)
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "xyz", {})
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "fetched_at", time.time())
    return crypto


@pytest.mark.parametrize("candidate", ["KBONK", "kbonkusdt", "KBONK", "kBONK", "KbOnK"])
def test_k_token_resolves_to_canonical_casing(mocked_universe, candidate):
    # Any casing of the bare coin resolves to exactly HL's 'kBONK'.
    coin = wp._scanner_symbol_to_coin(candidate)   # strips a USDT/USDC suffix if present
    assert wp._hl_resolve_coin(coin) == "kBONK"


def test_full_watchlist_symbol_path_kbonk(mocked_universe):
    # Full path a scan uses: 'KBONKUSDT' -> strip suffix -> resolve to 'kBONK'.
    coin = wp._scanner_symbol_to_coin("KBONKUSDT")
    assert coin == "KBONK"                          # suffix strip only, no re-casing
    assert wp._hl_resolve_coin(coin) == "kBONK"


def test_kpepe_kshib_resolve_canonically(mocked_universe):
    assert wp._hl_resolve_coin(wp._scanner_symbol_to_coin("KPEPEUSDT")) == "kPEPE"
    assert wp._hl_resolve_coin(wp._scanner_symbol_to_coin("KSHIBUSDT")) == "kSHIB"


def test_uppercase_symbols_unchanged(mocked_universe):
    # Behavior must be unchanged for symbols already canonical-upper.
    assert wp._hl_resolve_coin(wp._scanner_symbol_to_coin("BTCUSDT")) == "BTC"
    assert wp._hl_resolve_coin("BTC") == "BTC"
    assert wp._hl_resolve_coin(wp._scanner_symbol_to_coin("PURRUSDC")) == "PURR"
    assert wp._hl_resolve_coin("ETH") == "ETH"


def test_absent_symbol_does_not_resolve(mocked_universe):
    # A symbol not in the universe must NOT be canonicalized or fuzzy-matched;
    # it is returned bare (and will fail downstream, as before).
    assert "DOGE" not in mocked_universe            # keys are UPPER
    assert wp._hl_resolve_coin("DOGE") == "DOGE"
    assert wp._hl_resolve_coin("NOTACOIN") == "NOTACOIN"


def test_empty_input_passthrough(mocked_universe):
    assert wp._hl_resolve_coin("") == ""
    assert wp._hl_resolve_coin(None) is None
