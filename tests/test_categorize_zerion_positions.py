"""Unit tests for categorize_zerion_positions()."""

from src.connectors.zerion import categorize_zerion_positions


def _pos(position_type="wallet", protocol_module=None):
    """Helper to build a minimal Zerion position dict."""
    attrs = {"position_type": position_type}
    if protocol_module is not None:
        attrs["protocol_module"] = protocol_module
    return {"attributes": attrs}


class TestCategorizeZerionPositions:
    """Tests for categorize_zerion_positions covering requirements 3.1–3.7."""

    def test_empty_input(self):
        result = categorize_zerion_positions([])
        assert result == {"tokens": [], "lending": [], "lp_basic": [], "staking": []}

    def test_wallet_position_goes_to_tokens(self):
        pos = _pos(position_type="wallet")
        result = categorize_zerion_positions([pos])
        assert result["tokens"] == [pos]
        assert result["lending"] == []
        assert result["lp_basic"] == []
        assert result["staking"] == []

    def test_lending_module_goes_to_lending(self):
        pos = _pos(position_type="deposit", protocol_module="lending")
        result = categorize_zerion_positions([pos])
        assert result["lending"] == [pos]
        assert result["tokens"] == []

    def test_liquidity_pool_goes_to_lp_basic(self):
        pos = _pos(position_type="deposit", protocol_module="liquidity_pool")
        result = categorize_zerion_positions([pos])
        assert result["lp_basic"] == [pos]

    def test_farming_goes_to_lp_basic(self):
        pos = _pos(position_type="deposit", protocol_module="farming")
        result = categorize_zerion_positions([pos])
        assert result["lp_basic"] == [pos]

    def test_staked_module_goes_to_staking(self):
        pos = _pos(position_type="deposit", protocol_module="staked")
        result = categorize_zerion_positions([pos])
        assert result["staking"] == [pos]

    def test_locked_module_goes_to_staking(self):
        pos = _pos(position_type="deposit", protocol_module="locked")
        result = categorize_zerion_positions([pos])
        assert result["staking"] == [pos]

    def test_staked_position_type_goes_to_staking(self):
        pos = _pos(position_type="staked", protocol_module="some_other")
        result = categorize_zerion_positions([pos])
        assert result["staking"] == [pos]

    def test_locked_position_type_goes_to_staking(self):
        pos = _pos(position_type="locked")
        result = categorize_zerion_positions([pos])
        assert result["staking"] == [pos]

    def test_unmatched_falls_back_to_tokens(self):
        pos = _pos(position_type="unknown_type", protocol_module="unknown_module")
        result = categorize_zerion_positions([pos])
        assert result["tokens"] == [pos]

    def test_missing_attributes_defaults_to_tokens(self):
        pos = {}  # no attributes at all
        result = categorize_zerion_positions([pos])
        assert result["tokens"] == [pos]

    def test_total_count_preserved(self):
        positions = [
            _pos("wallet"),
            _pos("deposit", "lending"),
            _pos("deposit", "liquidity_pool"),
            _pos("deposit", "farming"),
            _pos("deposit", "staked"),
            _pos("staked"),
            _pos("locked"),
            _pos("borrow", "lending"),
            _pos("unknown", "unknown"),
        ]
        result = categorize_zerion_positions(positions)
        total = (
            len(result["tokens"])
            + len(result["lending"])
            + len(result["lp_basic"])
            + len(result["staking"])
        )
        assert total == len(positions)

    def test_none_protocol_module_with_wallet_type(self):
        pos = _pos(position_type="wallet", protocol_module=None)
        result = categorize_zerion_positions([pos])
        assert result["tokens"] == [pos]
