"""map_zerion_lp_to_app's additive fields (level-shift PR 1): deposit_legs and
uncounted_legs_usd. Display-only diagnostics - every pre-existing field keeps
today's value.

TWO_DEPOSIT_BEFORE is origin/main's output for the TWO_DEPOSIT fixture
(computed once from the pre-change function and pasted here), so the
field-by-field comparison does not depend on git at test time.
"""
import pytest

from src.connectors.zerion import map_zerion_lp_to_app

NEW_KEYS = ("deposit_legs", "uncounted_legs_usd")


def leg(sym, qty, value, price, ptype, module="liquidity_pool", app="Uniswap V3", chain="base"):
    return {"attributes": {"fungible_info": {"symbol": sym}, "quantity": {"float": qty}, "value": value, "price": price,
                           "position_type": ptype, "protocol_module": module, "protocol": app.lower(),
                           "application_metadata": {"name": app, "icon": {"url": ""}}},
            "relationships": {"chain": {"data": {"id": chain}}}}


TWO_DEPOSIT = [leg("WETH", 0.5, 1250.0, 2500.0, "deposit"), leg("USDC", 1300.0, 1299.5, 0.9996, "deposit"),
               leg("WETH", 0.002, 5.0, 2500.0, "reward"), leg("USDC", 3.1, 3.099, 0.9996, "reward")]

TWO_DEPOSIT_BEFORE = {
    'age_days': None,
    'age_hours': None,
    'amount0': 0.5,
    'amount1': 1300.0,
    'chain': 'base',
    'collected_fees_0': 0.0,
    'collected_fees_0_usd': 0.0,
    'collected_fees_1': 0.0,
    'collected_fees_1_usd': 0.0,
    'current_price': 0,
    'daily_apr': None,
    'daily_earnings': None,
    'fee_tier': 0,
    'fees0_usd': 5.0,
    'fees1_usd': 3.099,
    'fees_owed0': 0.002,
    'fees_owed1': 3.1,
    'in_range': None,
    'monthly_apr': None,
    'pair': 'WETH/USDC',
    'position_module': 'liquidity_pool',
    'price0_usd': 2500.0,
    'price1_usd': 0.9996,
    'price_lower': 0,
    'price_upper': 0,
    'protocol': 'uniswap_v3',
    'protocol_display': 'Uniswap V3',
    'protocol_icon_url': '',
    'range': {'current_price': None, 'in_range': None, 'max_price': None, 'min_price': None, 'source': None},
    'source': 'zerion',
    'token0_symbol': 'WETH',
    'token1_symbol': 'USDC',
    'token_id': None,
    'total_collected_fees_usd': 0.0,
    'total_earned_fees_0': 0.002,
    'total_earned_fees_1': 3.1,
    'total_earned_fees_usd': 8.099,
    'total_fees_usd': 8.099,
    'total_value_usd': 2549.5,
    'value0_usd': 1250.0,
    'value1_usd': 1299.5,
    'wallet': '0xW',
    'wallet_label': 'Alpha',
}


def test_a_reward_only_group_has_no_deposit_and_an_uncounted_leg():
    lp = map_zerion_lp_to_app([leg("USDC", 327.645, 327.62, 0.99993, "reward", module="farming", app="Dex Finance")],
                              "0xW", "Alpha")
    assert lp["total_value_usd"] == 0
    assert lp["deposit_legs"] == 0
    assert lp["uncounted_legs_usd"] == pytest.approx(327.62)
    assert lp["token0_symbol"] == "?"
    assert lp["total_fees_usd"] == 0
    assert lp["protocol"] == "dex_finance" and lp["protocol_display"] == "Dex Finance"


def test_b_two_deposit_group_unchanged_plus_new_fields():
    lp = map_zerion_lp_to_app(TWO_DEPOSIT, "0xW", "Alpha")
    assert lp["deposit_legs"] == 2
    assert lp["uncounted_legs_usd"] == 0
    assert set(lp) == set(TWO_DEPOSIT_BEFORE) | set(NEW_KEYS)
    for key, value in TWO_DEPOSIT_BEFORE.items():
        assert lp[key] == value, key


def test_c_reward_leg_in_a_third_token_is_uncounted():
    lp = map_zerion_lp_to_app(TWO_DEPOSIT + [leg("AERO", 10.0, 12.5, 1.25, "reward")], "0xW", "Alpha")
    assert lp["deposit_legs"] == 2
    assert lp["uncounted_legs_usd"] == pytest.approx(12.5)
    # Today's behaviour: the AERO leg is not in total_fees_usd (same as without it).
    assert lp["total_fees_usd"] == pytest.approx(TWO_DEPOSIT_BEFORE["total_fees_usd"])
    for key, value in TWO_DEPOSIT_BEFORE.items():
        assert lp[key] == value, key
