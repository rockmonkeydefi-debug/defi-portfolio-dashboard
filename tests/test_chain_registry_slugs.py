"""Regression guard for the Robinhood Chain / sonic DexScreener slug
correction: CUSTOM_TOKEN_CHAINS and SPOT_CHAINS both previously recorded
dexscreener_slug=None for robinhood, on the false assertion that DexScreener
does not index that chain. Live production data from
/api/spot/dexscreener-audit on 2026-09-04 disproved this - DexScreener's
chainId string for Robinhood Chain is "robinhood", read verbatim off the
response. No network, no database - these assertions read the module-level
registry dicts directly.

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


def test_custom_token_chains_robinhood_slug_is_robinhood():
    assert wp.CUSTOM_TOKEN_CHAINS["robinhood"]["dexscreener_slug"] == "robinhood"


def test_spot_chains_robinhood_slug_is_robinhood():
    assert wp.SPOT_CHAINS["robinhood"]["dexscreener_slug"] == "robinhood"


def test_spot_chains_sonic_slug_is_sonic():
    assert wp.SPOT_CHAINS["sonic"]["dexscreener_slug"] == "sonic"


def test_neither_registrys_robinhood_slug_is_none():
    """Explicit regression guard against reverting to the disproven value."""
    assert wp.CUSTOM_TOKEN_CHAINS["robinhood"]["dexscreener_slug"] is not None
    assert wp.SPOT_CHAINS["robinhood"]["dexscreener_slug"] is not None
