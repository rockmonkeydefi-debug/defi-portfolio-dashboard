"""Unit tests for map_zerion_lending_to_app()."""

from src.connectors.zerion import map_zerion_lending_to_app


WALLET = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
LABEL = "Main"


def _lending_pos(
    chain_id="arbitrum",
    symbol="WETH",
    balance=5.0,
    value=10000.0,
    price=2000.0,
    position_type="deposit",
    protocol_name="Aave V3",
    protocol="aave-v3",
):
    """Build a minimal Zerion lending position dict."""
    return {
        "attributes": {
            "fungible_info": {"symbol": symbol},
            "quantity": {"float": balance},
            "value": value,
            "price": price,
            "position_type": position_type,
            "application_metadata": {"name": protocol_name},
            "protocol": protocol,
        },
        "relationships": {
            "chain": {"data": {"id": chain_id, "type": "chains"}},
        },
    }


class TestMapZerionLendingToApp:
    """Tests for map_zerion_lending_to_app covering requirements 5.1–5.8."""

    def test_all_required_keys_present(self):
        """Req 5.1: Output has all required keys matching Aave format."""
        result = map_zerion_lending_to_app([_lending_pos()], WALLET, LABEL)
        expected_keys = {
            "chain", "chain_name", "protocol_name",
            "total_collateral_usd", "total_debt_usd", "available_borrows_usd",
            "ltv", "liquidation_threshold", "health_factor",
            "supplied", "borrowed",
            "wallet", "wallet_label", "liquidation_price",
        }
        assert set(result.keys()) == expected_keys

    def test_deposit_classified_as_supplied(self):
        """Req 5.2: deposit position_type → supplied."""
        result = map_zerion_lending_to_app(
            [_lending_pos(position_type="deposit")], WALLET, LABEL
        )
        assert len(result["supplied"]) == 1
        assert len(result["borrowed"]) == 0

    def test_staked_classified_as_supplied(self):
        """Req 5.2: staked position_type → supplied."""
        result = map_zerion_lending_to_app(
            [_lending_pos(position_type="staked")], WALLET, LABEL
        )
        assert len(result["supplied"]) == 1
        assert len(result["borrowed"]) == 0

    def test_borrow_classified_as_borrowed(self):
        """Req 5.3: borrow position_type → borrowed."""
        result = map_zerion_lending_to_app(
            [_lending_pos(position_type="borrow", symbol="USDC", value=5000.0, price=1.0, balance=5000.0)],
            WALLET, LABEL,
        )
        assert len(result["borrowed"]) == 1
        assert len(result["supplied"]) == 0

    def test_ltv_calculated_when_collateral_positive(self):
        """Req 5.4: ltv = (debt / collateral) * 100 when collateral > 0."""
        positions = [
            _lending_pos(position_type="deposit", value=10000.0),
            _lending_pos(position_type="borrow", symbol="USDC", value=5000.0, price=1.0, balance=5000.0),
        ]
        result = map_zerion_lending_to_app(positions, WALLET, LABEL)
        assert result["ltv"] == (5000.0 / 10000.0) * 100

    def test_ltv_zero_when_no_collateral(self):
        """Req 5.4: ltv = 0 when collateral is 0."""
        result = map_zerion_lending_to_app(
            [_lending_pos(position_type="borrow", value=5000.0)], WALLET, LABEL
        )
        assert result["ltv"] == 0

    def test_health_factor_zero(self):
        """Req 5.5: health_factor set to 0."""
        result = map_zerion_lending_to_app([_lending_pos()], WALLET, LABEL)
        assert result["health_factor"] == 0

    def test_liquidation_threshold_zero(self):
        """Req 5.5: liquidation_threshold set to 0."""
        result = map_zerion_lending_to_app([_lending_pos()], WALLET, LABEL)
        assert result["liquidation_threshold"] == 0

    def test_available_borrows_usd_zero(self):
        """Req 5.5: available_borrows_usd set to 0."""
        result = map_zerion_lending_to_app([_lending_pos()], WALLET, LABEL)
        assert result["available_borrows_usd"] == 0

    def test_liquidation_price_none(self):
        """Req 5.5: liquidation_price set to None."""
        result = map_zerion_lending_to_app([_lending_pos()], WALLET, LABEL)
        assert result["liquidation_price"] is None

    def test_supply_apy_zero(self):
        """Req 5.6: supply_apy set to 0 for supplied entries."""
        result = map_zerion_lending_to_app([_lending_pos()], WALLET, LABEL)
        assert result["supplied"][0]["supply_apy"] == 0

    def test_borrow_apy_zero(self):
        """Req 5.6: borrow_apy set to 0 for borrowed entries."""
        result = map_zerion_lending_to_app(
            [_lending_pos(position_type="borrow", value=1000.0)], WALLET, LABEL
        )
        assert result["borrowed"][0]["borrow_apy"] == 0

    def test_protocol_name_from_application_metadata(self):
        """Req 5.7: protocol name from application_metadata.name."""
        result = map_zerion_lending_to_app(
            [_lending_pos(protocol_name="Compound V3")], WALLET, LABEL
        )
        assert result["protocol_name"] == "Compound V3"

    def test_protocol_name_fallback_to_protocol(self):
        """Req 5.7: fallback to protocol attribute when metadata missing."""
        pos = _lending_pos()
        pos["attributes"]["application_metadata"] = {}
        result = map_zerion_lending_to_app([pos], WALLET, LABEL)
        assert result["protocol_name"] == "aave-v3"

    def test_borrowed_balance_absolute_value(self):
        """Req 5.8: absolute values for borrowed balance."""
        pos = _lending_pos(position_type="borrow", balance=-5000.0, value=-5000.0)
        result = map_zerion_lending_to_app([pos], WALLET, LABEL)
        assert result["borrowed"][0]["balance"] == 5000.0

    def test_borrowed_value_usd_absolute(self):
        """Req 5.8: absolute values for borrowed value_usd."""
        pos = _lending_pos(position_type="borrow", balance=-5000.0, value=-5000.0)
        result = map_zerion_lending_to_app([pos], WALLET, LABEL)
        assert result["borrowed"][0]["value_usd"] == 5000.0

    def test_chain_and_chain_name(self):
        """Chain ID preserved raw, chain_name uses get_chain_name()."""
        result = map_zerion_lending_to_app(
            [_lending_pos(chain_id="arbitrum")], WALLET, LABEL
        )
        assert result["chain"] == "arbitrum"
        assert result["chain_name"] == "Arbitrum"

    def test_wallet_and_label_passed_through(self):
        result = map_zerion_lending_to_app([_lending_pos()], WALLET, LABEL)
        assert result["wallet"] == WALLET
        assert result["wallet_label"] == LABEL

    def test_empty_positions_list(self):
        """Empty input produces valid output with zero totals."""
        result = map_zerion_lending_to_app([], WALLET, LABEL)
        assert result["total_collateral_usd"] == 0.0
        assert result["total_debt_usd"] == 0.0
        assert result["ltv"] == 0
        assert result["supplied"] == []
        assert result["borrowed"] == []

    def test_mixed_supply_and_borrow(self):
        """Mixed group correctly splits and totals."""
        positions = [
            _lending_pos(position_type="deposit", symbol="WETH", value=10000.0),
            _lending_pos(position_type="deposit", symbol="WBTC", value=5000.0),
            _lending_pos(position_type="borrow", symbol="USDC", value=3000.0, price=1.0, balance=3000.0),
        ]
        result = map_zerion_lending_to_app(positions, WALLET, LABEL)
        assert len(result["supplied"]) == 2
        assert len(result["borrowed"]) == 1
        assert result["total_collateral_usd"] == 15000.0
        assert result["total_debt_usd"] == 3000.0
        assert result["ltv"] == (3000.0 / 15000.0) * 100

    def test_supplied_entry_has_collateral_fields(self):
        """Supplied entries include collateral_enabled, ltv, liquidation_threshold."""
        result = map_zerion_lending_to_app([_lending_pos()], WALLET, LABEL)
        entry = result["supplied"][0]
        assert entry["collateral_enabled"] is True
        assert entry["ltv"] == 0
        assert entry["liquidation_threshold"] == 0

    def test_borrowed_entry_has_variable_flag(self):
        """Borrowed entries include is_variable flag."""
        result = map_zerion_lending_to_app(
            [_lending_pos(position_type="borrow", value=1000.0)], WALLET, LABEL
        )
        assert result["borrowed"][0]["is_variable"] is True
