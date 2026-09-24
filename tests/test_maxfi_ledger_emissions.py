"""Emissions C3 - pure compute (maxfi_ledger_emissions): decode by emitter,
dedup/net per (tx, token_id, reward_token), lifecycle guard, Transfer
check, status precedence (pre-ruling 1), and the three close-out wei rows
reproduced exactly from the synthetic-but-exact fixture."""
import json
import os
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import maxfi_ledger_emissions as mle
import maxfi_ledger_ingest as mli

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "maxfi_ledger", "base_emissions_claims_synthetic.json")

VAULT = mli.CHAINS["base"]["vault"]
SM = mli.CHAINS["base"]["staking_manager"]
AERO = "0x940181a94a35a4569e4529a3cdfb74e38fd98631"
CAKE = "0x3055913c90fcc1a6ce9a358911721eeb942013a1"
WALLET = "0xab7a515c6e2eea5140ed8a5b09a7d782f3b26743"
OTHER = "0x8fc4000000000000000000000000000000000001"
TREASURY = "0xef9b9e023617758a251b04d7aae9400a957d9d98"
GAUGE = "0x27f732a92cbdfd4047087b8aed4e0b88c29c4198"
TX = "0x" + "a1" * 32
BLOCK = 1000


def _w(*vals):
    return "0x" + "".join(format(v, "064x") for v in vals)


def _log(address, topics, data, idx, tx=TX, block=BLOCK):
    return {"address": address, "topics": topics, "data": data, "blockNumber": hex(block),
            "timeStamp": hex(1_700_000_000 + block), "transactionHash": tx, "logIndex": hex(idx)}


def vault_claim(token_id, amount, owner=WALLET, token=AERO, idx=1, **kw):
    return _log(VAULT, [mle.TOPIC_STAKING_REWARDS_CLAIMED, mli.encode_topic_uint256(token_id),
                        mli.encode_topic_address(owner), mli.encode_topic_address(token)], _w(amount), idx, **kw)


def sm_claim(token_id, amount, token=AERO, idx=2, **kw):
    return _log(SM, [mle.TOPIC_STAKING_REWARDS_CLAIMED, mli.encode_topic_uint256(token_id),
                     mli.encode_topic_address(VAULT), mli.encode_topic_address(token)], _w(amount), idx, **kw)


def fee_log(token_id, fee, treasury=None, referral=0, token=AERO, idx=3, **kw):
    treasury = fee - referral if treasury is None else treasury
    return _log(VAULT, [mle.TOPIC_PERFORMANCE_FEE_COLLECTED, mli.encode_topic_uint256(token_id),
                        mli.encode_topic_address(token)], _w(fee, treasury, referral), idx, **kw)


def transfer(frm, to, value, idx, token=AERO, extra_topic=None):
    topics = [mle.TOPIC_ERC20_TRANSFER, mli.encode_topic_address(frm), mli.encode_topic_address(to)]
    if extra_topic is not None:
        topics.append(extra_topic)
    return {"address": token, "topics": topics, "data": _w(value), "logIndex": hex(idx)}


def ledger(opened=900, rebalanced=None, closed=None, owner=WALLET):
    return {"owner": owner, "opened_block": opened, "rebalanced_block": rebalanced, "closed_block": closed}


def run(logs, receipts=None, ledger_by_token=None, wallets=(WALLET,)):
    events, rejected, failures = mle.decode_reward_logs(logs, VAULT, SM)
    keys = mle.build_claim_keys(events)
    mle.classify_keys(keys, ledger_by_token or {}, receipts or {}, VAULT, list(wallets))
    return keys, events, rejected, failures


def one(keys, token_id="7", token=AERO):
    return next(k for k in keys if k["token_id"] == token_id and k["reward_token"] == token)


# ── identities ────────────────────────────────────────────────────────────

def test_topic0s_equal_rewards_route_constants():
    assert mle.TOPIC_STAKING_REWARDS_CLAIMED == wp._REWARDS_TOPIC_STAKING_REWARDS_CLAIMED
    assert mle.TOPIC_PERFORMANCE_FEE_COLLECTED == wp._REWARDS_TOPIC_PERFORMANCE_FEE_COLLECTED
    assert mle.TOPIC_POSITION_STAKED == wp._REWARDS_TOPIC_POSITION_STAKED
    assert mle.TOPIC_POSITION_UNSTAKED == wp._REWARDS_TOPIC_POSITION_UNSTAKED
    assert mle.TOPIC_ERC20_TRANSFER == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


# ── decode: branch on emitter ─────────────────────────────────────────────

def test_decode_vault_claim_takes_owner_from_topics2():
    events, rejected, failures = mle.decode_reward_logs([vault_claim(7, 123)], VAULT, SM)
    assert rejected["count"] == 0 and failures["count"] == 0
    (e,) = events
    assert e["kind"] == "vault_claim" and e["token_id"] == "7"
    assert e["owner"] == WALLET and e["reward_token"] == AERO and e["amount"] == 123


def test_decode_staking_manager_claim_ignores_owner_slot():
    (e,) = mle.decode_reward_logs([sm_claim(7, 55)], VAULT, SM)[0]
    assert e["kind"] == "sm_claim" and e["amount"] == 55 and e["reward_token"] == AERO
    assert "owner" not in e  # the owner slot is the vault - ignored (close-out Q1)


def test_decode_fee_fields():
    (e,) = mle.decode_reward_logs([fee_log(7, 150, treasury=120, referral=30)], VAULT, SM)[0]
    assert e["kind"] == "fee" and e["token_id"] == "7" and e["reward_token"] == AERO
    assert (e["fee"], e["treasury"], e["referral"]) == (150, 120, 30)


def test_decode_rejects_foreign_emitter_and_disallowed_topic_per_emitter():
    foreign = dict(vault_claim(7, 1), address="0x" + "99" * 20)
    fee_from_sm = dict(fee_log(7, 1), address=SM)            # PFC is vault-only
    staked_from_vault = _log(VAULT, [mle.TOPIC_POSITION_STAKED, mli.encode_topic_uint256(7),
                                     mli.encode_topic_address(GAUGE)], "0x", 4)
    events, rejected, failures = mle.decode_reward_logs([foreign, fee_from_sm, staked_from_vault], VAULT, SM)
    assert events == [] and failures["count"] == 0
    assert rejected["count"] == 3


def test_decode_failure_is_counted_not_raised():
    short = _log(VAULT, [mle.TOPIC_STAKING_REWARDS_CLAIMED, mli.encode_topic_uint256(7)], _w(1), 1)
    events, rejected, failures = mle.decode_reward_logs([short, vault_claim(8, 2)], VAULT, SM)
    assert failures["count"] == 1 and rejected["count"] == 0
    assert [e["token_id"] for e in events] == ["8"]


def test_event_counts_cover_every_kind():
    logs = [vault_claim(7, 1), sm_claim(7, 1), fee_log(7, 1),
            _log(SM, [mle.TOPIC_POSITION_STAKED, mli.encode_topic_uint256(7), mli.encode_topic_address(GAUGE)], "0x", 5),
            _log(SM, [mle.TOPIC_POSITION_UNSTAKED, mli.encode_topic_uint256(7), mli.encode_topic_address(GAUGE)], "0x", 6),
            dict(vault_claim(7, 1), address="0x" + "99" * 20)]
    events, rejected, failures = mle.decode_reward_logs(logs, VAULT, SM)
    assert mle.event_counts(events, rejected, failures) == {
        "vault_claims": 1, "sm_claims": 1, "fees": 1, "staked": 1, "unstaked": 1, "rejected": 1, "decode_failed": 0,
    }


# ── dedup / net per path ──────────────────────────────────────────────────

def test_manual_path_vault_only():
    (k,) = mle.build_claim_keys(mle.decode_reward_logs([vault_claim(7, 1000), fee_log(7, 150)], VAULT, SM)[0])
    assert (k["claim_path"], k["gross_source"], k["gross"], k["fee"], k["net"]) == ("manual", "vault", 1000, 150, 850)
    assert k["gross_vault"] == 1000 and k["gross_sm"] is None and k["vault_owner"] == WALLET


def test_keeper_path_staking_manager_only():
    (k,) = mle.build_claim_keys(mle.decode_reward_logs([sm_claim(7, 1000), fee_log(7, 150)], VAULT, SM)[0])
    assert (k["claim_path"], k["gross_source"], k["gross"], k["net"]) == ("rebalance", "sm", 1000, 850)
    assert k["vault_owner"] is None


def test_withdrawal_path_both_equal():
    (k,) = mle.build_claim_keys(mle.decode_reward_logs(
        [sm_claim(7, 1000), vault_claim(7, 1000), fee_log(7, 150)], VAULT, SM)[0])
    assert (k["claim_path"], k["gross_source"], k["gross"], k["net"]) == ("withdrawal", "both", 1000, 850)
    assert k["gross_disagreement"] is False


def test_withdrawal_unequal_is_gross_disagreement_with_sm_gross():
    keys, *_ = run([sm_claim(7, 1000), vault_claim(7, 999), fee_log(7, 150)], ledger_by_token={"7": ledger()})
    k = one(keys)
    assert k["gross_disagreement"] is True and k["gross"] == 1000 and k["net"] == 850
    assert k["verification_status"] == mle.STATUS_GROSS_DISAGREEMENT


def test_fee_without_claim_key_has_no_gross():
    keys, *_ = run([fee_log(7, 150)], ledger_by_token={"7": ledger()})
    k = one(keys)
    assert k["gross"] is None and k["net"] is None and k["claim_path"] is None and k["gross_source"] is None
    assert k["fee"] == 150 and k["verification_status"] == mle.STATUS_FEE_WITHOUT_CLAIM


def test_claim_without_fee_has_zero_fee_and_net_equals_gross():
    receipts = {TX: [transfer(VAULT, WALLET, 1000, 20)]}
    keys, *_ = run([vault_claim(7, 1000)], receipts, {"7": ledger()})
    k = one(keys)
    assert (k["fee"], k["treasury"], k["referral"], k["fee_logs"]) == (0, 0, 0, 0)
    assert k["net"] == k["gross"] == 1000
    assert k["verification_status"] == mle.STATUS_VERIFIED


def test_keys_split_by_reward_token():
    keys = mle.build_claim_keys(mle.decode_reward_logs(
        [vault_claim(7, 10, token=AERO), vault_claim(7, 20, token=CAKE, idx=4)], VAULT, SM)[0])
    assert sorted((k["reward_token"], k["gross"]) for k in keys) == sorted([(AERO, 10), (CAKE, 20)])


# ── status precedence (pre-ruling 1): one test per step ───────────────────

def test_precedence_fee_without_claim_beats_window_unknown():
    keys, *_ = run([fee_log(7, 150)], ledger_by_token={})
    assert one(keys)["verification_status"] == mle.STATUS_FEE_WITHOUT_CLAIM


def test_precedence_window_unknown_beats_gross_disagreement():
    keys, *_ = run([sm_claim(7, 1000), vault_claim(7, 999)], ledger_by_token={"7": ledger(opened=None)})
    assert one(keys)["verification_status"] == mle.STATUS_WINDOW_UNKNOWN


def test_precedence_out_of_window_beats_gross_disagreement():
    keys, *_ = run([sm_claim(7, 1000), vault_claim(7, 999)], ledger_by_token={"7": ledger(opened=BLOCK + 1)})
    assert one(keys)["verification_status"] == mle.STATUS_OUT_OF_WINDOW


def test_precedence_gross_disagreement_beats_verified_and_keeps_transfer_fields():
    receipts = {TX: [transfer(VAULT, WALLET, 850, 20)]}
    keys, *_ = run([sm_claim(7, 1000), vault_claim(7, 999), fee_log(7, 150)], receipts, {"7": ledger()})
    k = one(keys)
    assert k["transfer_check"] == mle.STATUS_VERIFIED and k["transfer_wei"] == 850
    assert k["verification_status"] == mle.STATUS_GROSS_DISAGREEMENT


def test_precedence_transfer_check_decides_when_all_earlier_steps_pass():
    receipts = {TX: [transfer(VAULT, WALLET, 850, 20)]}
    keys, *_ = run([sm_claim(7, 1000), fee_log(7, 150)], receipts, {"7": ledger()})
    k = one(keys)
    assert k["verification_status"] == mle.STATUS_VERIFIED
    assert (k["transfer_log_index"], k["transfer_to"], k["transfer_wei"]) == (20, WALLET, 850)


def test_status_vocabulary_order_is_the_ruled_precedence():
    assert mle.STATUS_PRECEDENCE == (
        "fee_without_claim", "window_unknown", "out_of_window", "gross_disagreement",
        "verified", "verified_aggregate", "mismatch", "no_payout",
    )
    assert mle.COUNTED_STATUSES == ("verified", "verified_aggregate")
    assert "ambiguous" in mle.ALL_STATUSES and "ambiguous" not in mle.STATUS_PRECEDENCE


# ── Transfer check ────────────────────────────────────────────────────────

def test_transfer_exact_match_verified():
    keys, *_ = run([vault_claim(7, 1000), fee_log(7, 150)],
                   {TX: [transfer(VAULT, TREASURY, 150, 19), transfer(VAULT, WALLET, 850, 20)]}, {"7": ledger()})
    k = one(keys)
    assert k["verification_status"] == mle.STATUS_VERIFIED and k["transfer_log_index"] == 20
    assert [t["to"] for t in k["vault_transfers"]] == [TREASURY, WALLET]  # report-only list


def test_transfer_aggregate_two_keys_one_summed_transfer():
    logs = [sm_claim(7, 1000, idx=1), fee_log(7, 150, idx=2), sm_claim(8, 2000, idx=3), fee_log(8, 300, idx=4)]
    receipts = {TX: [transfer(VAULT, WALLET, 850 + 1700, 20)]}
    keys, *_ = run(logs, receipts, {"7": ledger(), "8": ledger()})
    assert {one(keys, t)["verification_status"] for t in ("7", "8")} == {mle.STATUS_VERIFIED_AGGREGATE}
    assert one(keys, "7")["transfer_log_index"] is None


def test_transfer_no_payout_when_no_candidate():
    keys, *_ = run([vault_claim(7, 1000), fee_log(7, 150)], {TX: [transfer(VAULT, TREASURY, 150, 19)]},
                   {"7": ledger()})
    assert one(keys)["verification_status"] == mle.STATUS_NO_PAYOUT


def test_transfer_mismatch_when_candidate_value_differs():
    keys, *_ = run([vault_claim(7, 1000), fee_log(7, 150)], {TX: [transfer(VAULT, WALLET, 849, 20)]},
                   {"7": ledger()})
    k = one(keys)
    assert k["verification_status"] == mle.STATUS_MISMATCH
    assert k["transfer_candidates_unused"] == [{"log_index": 20, "to": WALLET, "value": 849}]


def test_transfer_four_topic_erc721_transfer_is_ignored():
    nft = transfer(VAULT, WALLET, 850, 20, extra_topic=mli.encode_topic_uint256(850))
    keys, *_ = run([vault_claim(7, 1000), fee_log(7, 150)], {TX: [nft]}, {"7": ledger()})
    k = one(keys)
    assert k["verification_status"] == mle.STATUS_NO_PAYOUT and k["vault_transfers"] == []


def test_transfer_from_non_vault_sender_is_ignored():
    keys, *_ = run([vault_claim(7, 1000), fee_log(7, 150)], {TX: [transfer(GAUGE, WALLET, 850, 20)]},
                   {"7": ledger()})
    k = one(keys)
    assert k["verification_status"] == mle.STATUS_NO_PAYOUT and k["vault_transfers"] == []


def test_transfer_to_another_wallet_is_listed_but_not_matched():
    keys, *_ = run([vault_claim(7, 1000), fee_log(7, 150)], {TX: [transfer(VAULT, OTHER, 850, 20)]},
                   {"7": ledger()})
    k = one(keys)
    assert k["verification_status"] == mle.STATUS_NO_PAYOUT
    assert k["vault_transfers"] == [{"log_index": 20, "to": OTHER, "value": 850}]


def test_transfer_other_reward_token_is_not_a_candidate():
    keys, *_ = run([vault_claim(7, 1000), fee_log(7, 150)], {TX: [transfer(VAULT, WALLET, 850, 20, token=CAKE)]},
                   {"7": ledger()})
    assert one(keys)["verification_status"] == mle.STATUS_NO_PAYOUT


def test_keeper_claim_owner_comes_from_ledger_row():
    keys, *_ = run([sm_claim(7, 1000), fee_log(7, 150)], {TX: [transfer(VAULT, WALLET, 850, 20)]},
                   {"7": ledger(owner=WALLET)})
    k = one(keys)
    assert k["owner"] == WALLET and k["owner_source"] == "ledger" and k["owner_is_tracked"] is True


def test_missing_receipt_is_flagged_and_no_payout():
    keys, *_ = run([vault_claim(7, 1000)], {TX: None}, {"7": ledger()})
    k = one(keys)
    assert k["receipt_available"] is False and k["verification_status"] == mle.STATUS_NO_PAYOUT


# ── lifecycle guard ───────────────────────────────────────────────────────

def test_lifecycle_inclusive_boundaries():
    assert mle.in_lifecycle_window(100, 100, 200, None) is True
    assert mle.in_lifecycle_window(200, 100, 200, None) is True
    assert mle.in_lifecycle_window(200, 100, None, 200) is True
    assert mle.in_lifecycle_window(10 ** 9, 100, None, None) is True  # open-ended


def test_lifecycle_out_of_window_before_and_after():
    assert mle.in_lifecycle_window(99, 100, 200, None) is False
    assert mle.in_lifecycle_window(201, 100, 200, None) is False
    assert mle.in_lifecycle_window(201, 100, None, 200) is False


def test_lifecycle_rebalanced_block_takes_priority_over_closed_block():
    assert mle.in_lifecycle_window(250, 100, 200, 300) is False


def test_lifecycle_window_unknown_without_opened_block_or_ledger_row():
    assert mle.in_lifecycle_window(150, None, 200, None) is None
    keys, *_ = run([vault_claim(7, 1000)], ledger_by_token={})
    assert one(keys)["verification_status"] == mle.STATUS_WINDOW_UNKNOWN


# ── close-out wei rows, reproduced exactly (synthetic-but-exact fixture) ──

def _fixture():
    with open(FIXTURE) as fh:
        return json.load(fh)


def test_fixture_rows_satisfy_the_fee_and_net_identities():
    for t in _fixture()["txs"]:
        gross, fee, net = int(t["gross_wei"]), int(t["fee_wei"]), int(t["net_wei"])
        assert fee == gross * 1500 // 10000
        assert net == gross - fee


def test_fixture_three_paths_reproduce_close_out_wei_and_verify():
    fx = _fixture()
    ledger_by_token = {
        "67658300": ledger(opened=45_000_000, rebalanced=fx["txs"][1]["block_number"]),
        "71122634": ledger(opened=46_000_000, closed=fx["txs"][2]["block_number"]),
    }
    # Raw eth_getLogs shape (blockTimestamp) -> the same adaptation scan_reward_events applies.
    logs = [mli.rpc_log_to_etherscan_shape(log) for t in fx["txs"] for log in t["get_logs"]]
    receipts = {t["tx_hash"]: t["receipt"]["logs"] for t in fx["txs"]}
    keys, events, rejected, failures = run(logs, receipts, ledger_by_token)
    assert rejected["count"] == 0 and failures["count"] == 0
    expected_path = {"manual": ("manual", "vault"), "keeper": ("rebalance", "sm"), "withdrawal": ("withdrawal", "both")}
    for t in fx["txs"]:
        (k,) = [k for k in keys if k["tx_hash"] == t["tx_hash"]]
        assert k["token_id"] == t["token_id"] and k["reward_token"] == AERO
        assert (k["claim_path"], k["gross_source"]) == expected_path[t["label"]]
        assert str(k["gross"]) == t["gross_wei"]
        assert str(k["fee"]) == t["fee_wei"] and str(k["treasury"]) == t["fee_wei"] and k["referral"] == 0
        assert str(k["net"]) == t["net_wei"]
        assert str(k["transfer_wei"]) == t["net_wei"] and k["transfer_to"] == WALLET
        assert k["in_window"] is True
        assert k["verification_status"] == mle.STATUS_VERIFIED
    assert mle.status_counts(keys)[mle.STATUS_VERIFIED] == 3
