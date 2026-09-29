"""src.models.STABLECOIN_SYMBOLS: the single stablecoin list (portfolio_total
derives its uppercased tuple from it), with USDG (Robinhood chain's Global
Dollar)."""
from src.models import STABLECOIN_SYMBOLS, is_stablecoin, is_yield_stablecoin


def test_usdg_is_a_plain_stablecoin():
    assert "USDG" in STABLECOIN_SYMBOLS
    assert is_stablecoin("USDG") is True
    assert is_yield_stablecoin("USDG") is False


def test_yield_stablecoins_unchanged():
    assert is_yield_stablecoin("syrupUSDC") is True
    assert is_stablecoin("syrupUSDC") is False
