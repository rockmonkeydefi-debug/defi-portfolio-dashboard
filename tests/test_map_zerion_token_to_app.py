"""Unit tests for map_zerion_token_to_app()."""

from src.connectors.zerion import map_zerion_token_to_app


def _position(
    chain_id="ethereum",
    symbol="ETH",
    balance=1.5,
    value=3000.0,
    price=2000.0,
):
    """Build a minimal Zerion position dict for token mapping tests."""
    return {
        "attributes": {
            "fungible_info": {"symbol": symbol},
            "quantity": {"float": balance},
            "value": value,
            "price": price,
        },
        "relationships": {
            "chain": {"data": {"id": chain_id, "type": "chains"}},
        },
    }


WALLET = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
LABEL = "Main"


class TestMapZerionTokenToApp:
    """Tests for map_zerion_token_to_app covering requirements 4.1–4.6."""

    def test_all_required_keys_present(self):
        result = map_zerion_token_to_app(_position(), WALLET, LABEL)
        assert set(result.keys()) == {
            "chain", "symbol", "balance", "value_usd", "price_usd",
            "wallet", "wallet_label",
        }

    def test_known_chain_mapped(self):
        result = map_zerion_token_to_app(_position(chain_id="arbitrum"), WALLET, LABEL)
        assert result["chain"] == "Arbitrum"

    def test_unknown_chain_capitalized(self):
        result = map_zerion_token_to_app(_position(chain_id="fantom"), WALLET, LABEL)
        assert result["chain"] == "Fantom"

    def test_symbol_extracted(self):
        result = map_zerion_token_to_app(_position(symbol="USDC"), WALLET, LABEL)
        assert result["symbol"] == "USDC"

    def test_symbol_defaults_to_unknown(self):
        pos = {"attributes": {"quantity": {"float": 1.0}, "value": 10.0, "price": 10.0},
               "relationships": {"chain": {"data": {"id": "ethereum"}}}}
        result = map_zerion_token_to_app(pos, WALLET, LABEL)
        assert result["symbol"] == "UNKNOWN"

    def test_balance_extracted(self):
        result = map_zerion_token_to_app(_position(balance=42.5), WALLET, LABEL)
        assert result["balance"] == 42.5

    def test_value_usd_defaults_to_zero_when_none(self):
        result = map_zerion_token_to_app(_position(value=None), WALLET, LABEL)
        assert result["value_usd"] == 0.0

    def test_price_usd_defaults_to_zero_when_none(self):
        result = map_zerion_token_to_app(_position(price=None), WALLET, LABEL)
        assert result["price_usd"] == 0.0

    def test_wallet_and_label_passed_through(self):
        result = map_zerion_token_to_app(_position(), WALLET, LABEL)
        assert result["wallet"] == WALLET
        assert result["wallet_label"] == LABEL

    def test_completely_empty_position(self):
        result = map_zerion_token_to_app({}, WALLET, LABEL)
        assert result["chain"] == "Unknown"
        assert result["symbol"] == "UNKNOWN"
        assert result["balance"] == 0.0
        assert result["value_usd"] == 0.0
        assert result["price_usd"] == 0.0

    def test_value_usd_non_negative(self):
        result = map_zerion_token_to_app(_position(value=500.0), WALLET, LABEL)
        assert result["value_usd"] >= 0

    def test_price_usd_non_negative(self):
        result = map_zerion_token_to_app(_position(price=1.0), WALLET, LABEL)
        assert result["price_usd"] >= 0
