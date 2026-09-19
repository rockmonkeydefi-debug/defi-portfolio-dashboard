"""Synthetic-scenario tests for maxfi_ledger.derive_position_ledger /
derive_all (HANDOFF_maxfi_ledger.md Commit 1, constraint 11). None of the
event dicts here come from a fixture - real chain data never exercised a
rebalance-tx bundle (SnuggleRebalanced + FeesCompounded + FeesHarvestedDirect
together) this session, so the double-count-avoidance branch is
[Inference, no rebalance-tx fixture exists to verify this branch] and can
only be tested synthetically, same as this file's other scenarios.
"""

import json
import os

import maxfi_ledger as ml

BASE = "2026-01-01T00:00:00.000000Z"
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "maxfi_ledger")


def load_fixture(name):
    with open(os.path.join(FIXTURES, name)) as fh:
        return json.load(fh)


def mk_event(event_type, chain, vault, token_id, tx_hash, block_number, decoded, log_index=0, block_timestamp=BASE):
    return {
        "chain": chain,
        "vault": vault,
        "npm": None,
        "token_id": token_id,
        "event_type": event_type,
        "tx_hash": tx_hash,
        "block_number": block_number,
        "block_timestamp": block_timestamp,
        "log_index": log_index,
        "decoded_json": json.dumps(decoded),
    }


def by_key(rows, chain, vault, npm, token_id):
    return next(r for r in rows if (r["chain"], r["vault"], r["npm"], r["token_id"]) == (chain, vault, npm, token_id))


# ── Scenario 1: normal lifecycle (open -> harvest -> harvest+close) ------

def test_normal_lifecycle():
    vault = "0xvault1"
    events = [
        mk_event("PositionCreated", "base", vault, "100", "0xtx1", 10,
                  {"token_id": 100, "owner": "0xowner", "pool_id": "0xpool",
                   "tick_lower": -100, "tick_upper": 100, "liquidity": 5000,
                   "auto_snuggle_enabled": True}),
        mk_event("FeesHarvested", "base", vault, "100", "0xtx2", 20,
                  {"token_id": 100, "owner": "0xowner", "fees0": 1000, "fees1": 2000}),
        mk_event("ProtocolFeesDistributed", "base", None, "100", "0xtx2", 20,
                  {"token_id": 100, "treasury0": 150, "treasury1": 300, "referral0": 0, "referral1": 0}),
        mk_event("FeesHarvested", "base", vault, "100", "0xtx3", 30,
                  {"token_id": 100, "owner": "0xowner", "fees0": 500, "fees1": 600}),
        mk_event("ProtocolFeesDistributed", "base", None, "100", "0xtx3", 30,
                  {"token_id": 100, "treasury0": 75, "treasury1": 90, "referral0": 0, "referral1": 0}),
        mk_event("PositionWithdrawn", "base", vault, "100", "0xtx3", 30,
                  {"token_id": 100, "owner": "0xowner", "amount0": 9000, "amount1": 8000}),
    ]
    rows = ml.derive_all(events)
    assert len(rows) == 1
    row = rows[0]

    assert row["chain"] == "base"
    assert row["vault"] == vault
    assert row["npm"] is None
    assert row["token_id"] == "100"
    assert row["owner"] == "0xowner"
    assert row["pool_id"] == "0xpool"
    assert row["opened_at"] == BASE
    assert row["opened_block"] == 10

    assert row["claimed_gross0_wei"] == "1500"
    assert row["claimed_gross1_wei"] == "2600"
    assert row["claimed_net0_wei"] == "1275"
    assert row["claimed_net1_wei"] == "2210"

    assert row["closed_at"] == BASE
    assert row["closed_block"] == 30
    assert row["exit_amount0_wei"] == "9000"
    assert row["exit_amount1_wei"] == "8000"
    assert row["exit_net_fee0_wei"] == "425"
    assert row["exit_net_fee1_wei"] == "510"

    assert row["compounded0_wei"] == "0"
    assert row["compounded1_wei"] == "0"


# ── Scenario 2: rebalance-minted child with no PositionCreated -----------

def test_rebalance_minted_child_has_no_position_created():
    vault = "0xvault2"
    events = [
        mk_event("PositionCreated", "base", vault, "100", "0xtx1", 10,
                  {"token_id": 100, "owner": "0xowner", "pool_id": "0xpool",
                   "tick_lower": -100, "tick_upper": 100, "liquidity": 5000,
                   "auto_snuggle_enabled": True}),
        mk_event("SnuggleRebalanced", "base", vault, "200", "0xtx4", 40,
                  {"old_token_id": 100, "new_token_id": 200, "owner": "0xowner",
                   "new_tick_lower": -50, "new_tick_upper": 50,
                   "protocol_fee0": 10, "protocol_fee1": 20,
                   "was_manual": False, "total_rebalances": 1}),
        mk_event("FeesHarvested", "base", vault, "200", "0xtx5", 50,
                  {"token_id": 200, "owner": "0xowner", "fees0": 300, "fees1": 400}),
        mk_event("ProtocolFeesDistributed", "base", None, "200", "0xtx5", 50,
                  {"token_id": 200, "treasury0": 45, "treasury1": 60, "referral0": 0, "referral1": 0}),
    ]
    rows = ml.derive_all(events)
    assert len(rows) == 2

    old_row = by_key(rows, "base", vault, None, "100")
    assert old_row["opened_at"] == BASE
    assert old_row["opened_block"] == 10
    assert old_row["rebalanced_to_token_id"] == "200"
    assert old_row["rebalanced_from_token_id"] is None
    assert old_row["rebalanced_block"] == 40

    new_row = by_key(rows, "base", vault, None, "200")
    # No PositionCreated exists for "200" - opened_at/block fall back to
    # the SnuggleRebalanced event's own block/timestamp (rebalance-mint).
    assert new_row["opened_at"] == BASE
    assert new_row["opened_block"] == 40
    assert new_row["rebalanced_from_token_id"] == "100"
    assert new_row["rebalanced_to_token_id"] is None
    assert new_row["claimed_gross0_wei"] == "300"
    assert new_row["claimed_net0_wei"] == "255"


# ── Scenario 3: FeesCompounded + FeesHarvestedDirect double-count avoidance

def test_compounded_and_harvested_direct_avoid_double_count():
    """[Inference, no rebalance-tx fixture exists to verify this branch]
    One tx carries FeesHarvested + ProtocolFeesDistributed (the ordinary
    split pair) AND FeesHarvestedDirect + FeesCompounded (the rebalance
    payout). claimed_net must come from FeesHarvestedDirect alone (700,
    1400), NOT from FeesHarvested minus ProtocolFeesDistributed
    (1000-150=850, 2000-300=1700) - adding both would double-count the
    same underlying fee event.
    """
    vault = "0xvault3"
    events = [
        mk_event("FeesHarvested", "base", vault, "300", "0xtx6", 60,
                  {"token_id": 300, "owner": "0xowner", "fees0": 1000, "fees1": 2000}),
        mk_event("ProtocolFeesDistributed", "base", None, "300", "0xtx6", 60,
                  {"token_id": 300, "treasury0": 150, "treasury1": 300, "referral0": 0, "referral1": 0}),
        mk_event("FeesHarvestedDirect", "base", None, "300", "0xtx6", 60,
                  {"token_id": 300, "owner": "0xowner", "amount0": 700, "amount1": 1400}),
        mk_event("FeesCompounded", "base", None, "300", "0xtx6", 60,
                  {"token_id": 300, "owner": "0xowner", "amount0": 150, "amount1": 300}),
    ]
    rows = ml.derive_all(events)
    assert len(rows) == 1
    row = rows[0]

    # gross is always the FeesHarvested figure, regardless of the direct/
    # compounded split.
    assert row["claimed_gross0_wei"] == "1000"
    assert row["claimed_gross1_wei"] == "2000"
    # net is FeesHarvestedDirect's amount, not (gross - treasury).
    assert row["claimed_net0_wei"] == "700"
    assert row["claimed_net1_wei"] == "1400"
    # FeesCompounded always accumulates into principal, never claimed_net.
    assert row["compounded0_wei"] == "150"
    assert row["compounded1_wei"] == "300"


def test_staking_manager_event_with_no_vault_sibling_in_batch_is_dropped():
    """A ProtocolFeesDistributed with literally no vault-carrying event
    anywhere in the input for its (tx_hash, token_id) cannot be resolved
    to a vault - derive_all() drops it rather than guessing. Documented
    coverage gap (module docstring), verified here so a future change to
    that behavior is a deliberate, visible diff.
    """
    events = [
        mk_event("ProtocolFeesDistributed", "base", None, "999", "0xorphan", 70,
                  {"token_id": 999, "treasury0": 1, "treasury1": 1, "referral0": 0, "referral1": 0}),
    ]
    rows = ml.derive_all(events)
    assert rows == []


# ── npm is always None; basis_* is always None for groups with no
#    IncreaseLiquidity event (Commit 3a scopes this - see the positive
#    counterpart below, test_basis_populates_from_increase_liquidity) ----

def test_npm_always_none_and_basis_always_none_without_increase_liquidity():
    """None of this test's 3 groups contains an IncreaseLiquidity event,
    so basis_* stays None for all of them - this is the "no basis event in
    this group" case, not a claim that basis_* is unconditionally None
    (Commit 3a's positive case is a separate test). npm is unconditionally
    None regardless - every decoder in this module always sets it to None
    (module docstring / HANDOFF ruling 9), independent of whether basis
    data exists.
    """
    vault = "0xvault4"
    events = [
        mk_event("PositionCreated", "base", vault, "100", "0xtx1", 10,
                  {"token_id": 100, "owner": "0xowner", "pool_id": "0xpool",
                   "tick_lower": -100, "tick_upper": 100, "liquidity": 5000,
                   "auto_snuggle_enabled": True}),
        mk_event("SnuggleRebalanced", "base", vault, "200", "0xtx4", 40,
                  {"old_token_id": 100, "new_token_id": 200, "owner": "0xowner",
                   "new_tick_lower": -50, "new_tick_upper": 50,
                   "protocol_fee0": 10, "protocol_fee1": 20,
                   "was_manual": False, "total_rebalances": 1}),
        mk_event("FeesHarvested", "base", vault, "300", "0xtx6", 60,
                  {"token_id": 300, "owner": "0xowner", "fees0": 1000, "fees1": 2000}),
        mk_event("ProtocolFeesDistributed", "base", None, "300", "0xtx6", 60,
                  {"token_id": 300, "treasury0": 150, "treasury1": 300, "referral0": 0, "referral1": 0}),
        mk_event("FeesHarvestedDirect", "base", None, "300", "0xtx6", 60,
                  {"token_id": 300, "owner": "0xowner", "amount0": 700, "amount1": 1400}),
        mk_event("FeesCompounded", "base", None, "300", "0xtx6", 60,
                  {"token_id": 300, "owner": "0xowner", "amount0": 150, "amount1": 300}),
    ]
    rows = ml.derive_all(events)
    assert len(rows) == 3
    for row in rows:
        assert row["npm"] is None
        assert row["basis_liquidity_wei"] is None
        assert row["basis_amount0_wei"] is None
        assert row["basis_amount1_wei"] is None
        assert row["basis_block"] is None
        assert row["basis_at"] is None
        assert row["basis_price_usd"] is None
        assert row["basis_price_source"] is None
        assert row["source_event_ids"] is None
        assert row["computed_at"] is None


def test_basis_populates_from_increase_liquidity():
    """Commit 3a positive case: a group with PositionCreated +
    IncreaseLiquidity for the same token_id derives basis_liquidity_wei/
    basis_amount0_wei/basis_amount1_wei/basis_block/basis_at from the
    IncreaseLiquidity event, while basis_price_usd/basis_price_source stay
    None (Swap-log pricing is Commit 3b's job). Synthetic values, not the
    real mint-tx fixture (see this file's build_pool_map integration test
    below for the real-fixture PositionCreated row).
    """
    vault = "0xvault6"
    events = [
        mk_event("PositionCreated", "base", vault, "400", "0xtx7", 100,
                  {"token_id": 400, "owner": "0xowner", "pool_id": "0xpool400",
                   "tick_lower": -200, "tick_upper": 200, "liquidity": 9000,
                   "auto_snuggle_enabled": True}, block_timestamp=BASE),
        mk_event("IncreaseLiquidity", "base", None, "400", "0xtx7", 100,
                  {"token_id": 400, "liquidity": 3473656907099,
                   "amount0": 1905032765586610, "amount1": 5000000},
                  block_timestamp=BASE),
    ]
    rows = ml.derive_all(events)
    assert len(rows) == 1
    row = rows[0]
    assert row["token_id"] == "400"
    assert row["npm"] is None
    assert row["basis_liquidity_wei"] == "3473656907099"
    assert row["basis_amount0_wei"] == "1905032765586610"
    assert row["basis_amount1_wei"] == "5000000"
    assert row["basis_block"] == 100
    assert row["basis_at"] == BASE
    assert row["basis_price_usd"] is None
    assert row["basis_price_source"] is None


# ── build_pool_map() / derive_all()'s post-grouping pool-address fill ----

_POOL_ADDED_DECODED = {
    "pool_id": "0x12fc2fd09d3d3bfeca3b2a731167f3740c3a543755afa8d0d93fd95889e41796",
    "pool": "0xd0b53d9277642d899df5c87a3966a349a798f224",
    "token0": "0x4200000000000000000000000000000000000006",
    "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    "fee": 500,
    "position_adapter": "0xca4cf963c71234a4f7d44a750b4d3847b4debabd",
    "reward_adapter": "0x0000000000000000000000000000000000000000",
}


def _pool_added_event(vault="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", tx_hash="0xsynthpooladded"):
    return mk_event("PoolAdded", "base", vault, None, tx_hash, 5, _POOL_ADDED_DECODED)


def test_build_pool_map_from_synthetic_pool_added():
    events = [_pool_added_event()]
    pool_map = ml.build_pool_map(events)
    assert pool_map == {_POOL_ADDED_DECODED["pool_id"]: _POOL_ADDED_DECODED["pool"]}


def test_build_pool_map_empty_without_pool_added():
    events = [
        mk_event("PositionCreated", "base", "0xvault1", "100", "0xtx1", 10,
                  {"token_id": 100, "owner": "0xowner", "pool_id": "0xpool",
                   "tick_lower": -100, "tick_upper": 100, "liquidity": 5000,
                   "auto_snuggle_enabled": True}),
    ]
    assert ml.build_pool_map(events) == {}
    assert ml.build_pool_map([]) == {}


def test_derive_all_applies_pool_map_post_grouping_using_real_fixture_position():
    """Integration: a batch containing the synthetic PoolAdded event above
    plus the REAL base_position_created.json row for Base tokenId 6039568
    (pool_id 0x12fc2fd0...41796, matching _POOL_ADDED_DECODED) results in
    that position's derived row getting pool_address filled in from the
    pool map. A second position in the same batch, whose own pool_id has
    no matching PoolAdded event anywhere in this batch, keeps
    pool_address None - the real, documented scope limit (module
    docstring / derive_all()'s own docstring), not routed around here.
    """
    rows_6039568 = [r for r in load_fixture("base_position_created.json")["result"]
                     if int(r["topics"][1], 16) == 6039568]
    assert len(rows_6039568) == 1
    position_created_6039568 = ml.decode_log(rows_6039568[0])
    position_created_6039568["chain"] = "base"
    assert json.loads(position_created_6039568["decoded_json"])["pool_id"] == _POOL_ADDED_DECODED["pool_id"]

    other_events = [
        mk_event("PositionCreated", "base", "0xothervault", "999", "0xtxother", 1,
                  {"token_id": 999, "owner": "0xowner", "pool_id": "0xno-match-pool",
                   "tick_lower": -1, "tick_upper": 1, "liquidity": 1,
                   "auto_snuggle_enabled": False}),
    ]

    events = [position_created_6039568, _pool_added_event()] + other_events
    rows = ml.derive_all(events)

    row_6039568 = by_key(rows, "base", "0x7d27cdfbfcc878f7e7349e216d44204bfd2afd55", None, "6039568")
    assert row_6039568["pool_address"] == "0xd0b53d9277642d899df5c87a3966a349a798f224"

    row_999 = by_key(rows, "base", "0xothervault", None, "999")
    assert row_999["pool_id"] == "0xno-match-pool"
    assert row_999["pool_address"] is None


def test_derive_position_ledger_direct_call_with_explicit_key():
    vault = "0xvault5"
    events = [
        mk_event("PositionCreated", "base", vault, "100", "0xtx1", 10,
                  {"token_id": 100, "owner": "0xowner", "pool_id": "0xpool",
                   "tick_lower": -100, "tick_upper": 100, "liquidity": 5000,
                   "auto_snuggle_enabled": True}),
    ]
    row = ml.derive_position_ledger(events, (vault, None, "100"))
    assert row["vault"] == vault
    assert row["token_id"] == "100"
    assert row["opened_block"] == 10
