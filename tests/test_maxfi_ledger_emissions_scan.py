"""Emissions C3 - maxfi_ledger_ingest.scan_reward_events (the sibling of
scan_chain): emitters and topic filters, one receipt per distinct
claim/fee tx, zero RPC for an empty token set, RPC errors raise."""
import pytest

import maxfi_ledger_emissions as mle
import maxfi_ledger_ingest as mli

CFG = mli.CHAINS["base"]
HEAD = CFG["start_block"] + 5000
TX_CLAIM = "0x" + "c1" * 32
TX_STAKE = "0x" + "c2" * 32


def _raw(address, topics, tx, idx, data="0x"):
    return {"address": address, "topics": topics, "data": data, "blockNumber": hex(CFG["start_block"] + 10),
            "blockTimestamp": hex(1_700_000_000), "transactionHash": tx, "logIndex": hex(idx)}


def _install(monkeypatch, vault_logs=(), sm_logs=(), receipts=None):
    calls = {"get_logs": [], "receipts": []}

    def fake_get_logs(chain, address, topics, from_block, to_block, timeout=30):
        calls["get_logs"].append({"address": address, "topics": topics, "from": from_block, "to": to_block})
        if address == CFG["vault"]:
            return list(vault_logs)
        if address == CFG["staking_manager"]:
            return list(sm_logs)
        raise AssertionError(f"unexpected emitter {address}")

    def fake_receipt(chain, tx_hash, timeout=30):
        calls["receipts"].append(tx_hash)
        return (receipts or {}).get(tx_hash, {"logs": []})

    monkeypatch.setattr(mli, "eth_block_number", lambda chain, timeout=30: HEAD)
    monkeypatch.setattr(mli, "eth_get_logs", fake_get_logs)
    monkeypatch.setattr(mli, "eth_get_transaction_receipt", fake_receipt)
    return calls


def test_empty_token_set_makes_no_rpc(monkeypatch):
    for name in ("eth_block_number", "eth_get_logs", "eth_get_transaction_receipt"):
        monkeypatch.setattr(mli, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError("no rpc")))
    out = mli.scan_reward_events("base", [])
    assert out["raw_logs"] == [] and out["receipts_by_tx"] == {} and out["rpc_calls"]["total"] == 0


def test_two_passes_with_correct_emitters_and_topic_filters(monkeypatch):
    calls = _install(monkeypatch)
    out = mli.scan_reward_events("base", [300, "20", 1000])
    token_topics = [mli.encode_topic_uint256(t) for t in (20, 300, 1000)]  # sorted by int
    assert calls["get_logs"] == [
        {"address": CFG["vault"], "topics": [[mle.TOPIC_STAKING_REWARDS_CLAIMED, mle.TOPIC_PERFORMANCE_FEE_COLLECTED],
                                             token_topics], "from": CFG["start_block"], "to": HEAD},
        {"address": CFG["staking_manager"],
         "topics": [[mle.TOPIC_STAKING_REWARDS_CLAIMED, mle.TOPIC_POSITION_STAKED, mle.TOPIC_POSITION_UNSTAKED],
                    token_topics], "from": CFG["start_block"], "to": HEAD},
    ]
    assert out["rpc_calls"] == {"block_number": 1, "log_calls": 2, "timestamp_lookups": 0, "receipt_calls": 0,
                                "total": 3}


def test_one_receipt_per_distinct_claim_or_fee_tx_only(monkeypatch):
    vault_logs = [
        _raw(CFG["vault"], [mle.TOPIC_STAKING_REWARDS_CLAIMED, "0x1", "0x2", "0x3"], TX_CLAIM, 1),
        _raw(CFG["vault"], [mle.TOPIC_PERFORMANCE_FEE_COLLECTED, "0x1", "0x3"], TX_CLAIM.upper().replace("0X", "0x"), 2),
    ]
    sm_logs = [_raw(CFG["staking_manager"], [mle.TOPIC_POSITION_STAKED, "0x1", "0x4"], TX_STAKE, 3)]
    receipt_logs = [{"address": "0xabc", "topics": [], "data": "0x", "logIndex": "0x9"}]
    calls = _install(monkeypatch, vault_logs, sm_logs, receipts={TX_CLAIM: {"logs": receipt_logs}})
    out = mli.scan_reward_events("base", [1])
    assert calls["receipts"] == [TX_CLAIM]  # the stake-only tx needs no receipt
    assert out["receipts_by_tx"] == {TX_CLAIM: receipt_logs}
    assert out["chunk_stats"]["receipts"] == {"txs": 1, "calls": 1, "null_receipts": 0}
    # getLogs results are adapted to the Etherscan shape (timeStamp), same as scan_chain
    assert all("timeStamp" in log for log in out["raw_logs"]) and len(out["raw_logs"]) == 3


def test_null_receipt_is_counted_and_kept_as_none(monkeypatch):
    vault_logs = [_raw(CFG["vault"], [mle.TOPIC_STAKING_REWARDS_CLAIMED, "0x1", "0x2", "0x3"], TX_CLAIM, 1)]
    _install(monkeypatch, vault_logs)
    monkeypatch.setattr(mli, "eth_get_transaction_receipt", lambda chain, tx, timeout=30: None)
    out = mli.scan_reward_events("base", [1])
    assert out["receipts_by_tx"] == {TX_CLAIM: None}
    assert out["chunk_stats"]["receipts"]["null_receipts"] == 1


def test_rpc_error_raises_for_the_caller_to_isolate(monkeypatch):
    _install(monkeypatch)

    def boom(chain, address, topics, from_block, to_block, timeout=30):
        raise mli.MaxFiRpcError("getLogs down")

    monkeypatch.setattr(mli, "eth_get_logs", boom)
    with pytest.raises(mli.MaxFiIngestError):
        mli.scan_reward_events("base", [1])
