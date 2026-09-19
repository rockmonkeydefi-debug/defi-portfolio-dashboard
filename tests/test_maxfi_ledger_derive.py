"""Synthetic-scenario tests for maxfi_ledger.derive_position_ledger /
derive_all (HANDOFF_maxfi_ledger.md Commit 1, constraint 11). None of the
event dicts here come from a fixture - real chain data never exercised a
rebalance-tx bundle (SnuggleRebalanced + FeesCompounded + FeesHarvestedDirect
together) this session, so the double-count-avoidance branch is
[Inference, no rebalance-tx fixture exists to verify this branch] and can
only be tested synthetically, same as this file's other scenarios.
"""

import json

import maxfi_ledger as ml

BASE = "2026-01-01T00:00:00.000000Z"


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


# ── basis_*/npm are always None, across every scenario in this file ------

def test_basis_columns_and_npm_are_always_none():
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
