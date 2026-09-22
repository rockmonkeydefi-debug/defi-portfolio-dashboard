import json
import os

import maxfi_ledger as ml

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "maxfi_ledger")


def load(name):
    with open(os.path.join(FIXTURES, name)) as fh:
        return json.load(fh)


def decoded(record):
    return json.loads(record["decoded_json"])


# ── topic0 constants cross-verified against the fixtures' own topics[0] ---

def test_topic0_position_created_matches_fixture():
    rows = load("base_position_created.json")["result"]
    assert ml.TOPIC_POSITION_CREATED == rows[0]["topics"][0].lower()


def test_topic0_swap_matches_fixture():
    rows = load("base_swap_page.json")["result"]
    assert ml.TOPIC_SWAP == rows[0]["topics"][0].lower()


def test_topic0_fees_harvested_matches_fixture():
    items = load("base_harvest_6039568.json")["items"]
    fh = next(i for i in items if i["topics"][0].lower() == ml.TOPIC_FEES_HARVESTED)
    assert fh["decoded"]["method_call"].startswith("FeesHarvested(")


def test_topic0_protocol_fees_distributed_matches_fixture():
    items = load("base_harvest_6039568.json")["items"]
    pfd = next(i for i in items if i["topics"][0].lower() == ml.TOPIC_PROTOCOL_FEES_DISTRIBUTED)
    assert pfd["decoded"]["method_call"].startswith("ProtocolFeesDistributed(")


def test_topic0_increase_liquidity_matches_fixture():
    items = load("base_mint_6039568.json")["items"]
    il = next(i for i in items if i["topics"][0].lower() == ml.TOPIC_INCREASE_LIQUIDITY)
    assert il["decoded"]["method_call"].startswith("IncreaseLiquidity(")


# ── base_position_created.json: 13 rows, all decode to PositionCreated ---

def test_base_position_created_all_13_decode():
    rows = load("base_position_created.json")["result"]
    assert len(rows) == 13
    records = [ml.decode_log(r) for r in rows]
    assert all(r is not None for r in records)
    assert all(r["event_type"] == "PositionCreated" for r in records)


def test_base_position_created_token_ids_and_npm_split():
    rows = load("base_position_created.json")["result"]
    records = [ml.decode_log(r) for r in rows]
    token_ids = {r["token_id"] for r in records}
    npm_a = {"4954839", "4956448", "5884225", "5972982", "5973070", "5973556", "5973562", "6039568"}
    npm_b = {"67658300", "67661111", "67701581", "67833581", "67834188"}
    assert token_ids == npm_a | npm_b
    # RULING 9: npm is always None this commit even though these 13 rows
    # span two different real position managers - resolving npm needs a
    # live eth_call, not attempted here.
    assert all(r["npm"] is None for r in records)


def test_base_position_created_fields_and_vault_lowercased():
    rows = load("base_position_created.json")["result"]
    record = ml.decode_log(rows[0])
    assert record["vault"] == "0x7d27cdfbfcc878f7e7349e216d44204bfd2afd55"
    d = decoded(record)
    assert d["token_id"] == 4954839
    assert d["owner"] == "0xab7a515c6e2eea5140ed8a5b09a7d782f3b26743"
    assert d["auto_snuggle_enabled"] is True
    assert isinstance(d["tick_lower"], int) and d["tick_lower"] < 0
    assert isinstance(d["liquidity"], int) and d["liquidity"] > 0


# ── base_harvest_6039568.json: 11 items, exactly 2 recognized -----------

def test_base_harvest_exactly_two_of_eleven_recognized():
    items = load("base_harvest_6039568.json")["items"]
    assert len(items) == 11
    records = [ml.decode_log(i) for i in items]
    recognized = [r for r in records if r is not None]
    assert len(recognized) == 2
    event_types = {r["event_type"] for r in recognized}
    assert event_types == {"FeesHarvested", "ProtocolFeesDistributed"}


def test_base_harvest_pool_and_npm_collect_and_burn_and_transfer_all_none():
    items = load("base_harvest_6039568.json")["items"]
    records = [ml.decode_log(i) for i in items]
    by_topic = {i["topics"][0].lower(): r for i, r in zip(items, records)}
    # Burn, both Collects, Transfer are NOT in the tracked vocabulary.
    burn_topic = "0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c"
    pool_collect_topic = "0x70935338e69775456a85ddef226c395fb668b63fa0115f5f20610b388e6ca9c0"
    npm_collect_topic = "0x40d0efd1a53d60ecbf40971b9daf7dc90178c3aadc7aab1765632738fa8b8f01"
    transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    assert by_topic[burn_topic] is None
    assert by_topic[pool_collect_topic] is None
    assert by_topic[npm_collect_topic] is None
    assert by_topic[transfer_topic] is None
    # And the two topics really are different from each other and from
    # FeesHarvested's - the "same name, different topic0" landmine.
    assert pool_collect_topic != npm_collect_topic
    assert pool_collect_topic != ml.TOPIC_FEES_HARVESTED


def test_base_harvest_fees_harvested_exact_wei_amounts():
    items = load("base_harvest_6039568.json")["items"]
    records = [ml.decode_log(i) for i in items]
    fh = next(r for r in records if r and r["event_type"] == "FeesHarvested")
    d = decoded(fh)
    assert d["token_id"] == 6039568
    assert d["fees0"] == 242214271699
    assert d["fees1"] == 583
    assert fh["vault"] == "0x7d27cdfbfcc878f7e7349e216d44204bfd2afd55"
    assert fh["block_number"] == 51497380


def test_base_harvest_protocol_fees_distributed_exact_wei_amounts():
    items = load("base_harvest_6039568.json")["items"]
    records = [ml.decode_log(i) for i in items]
    pfd = next(r for r in records if r and r["event_type"] == "ProtocolFeesDistributed")
    d = decoded(pfd)
    assert d["token_id"] == 6039568
    assert d["treasury0"] == 36332140754
    assert d["treasury1"] == 87
    assert d["referral0"] == 0
    assert d["referral1"] == 0
    # vault is None for a StakingManager event - decode_log() cannot know
    # the vault without same-tx correlation (that's derive_all()'s job).
    assert pfd["vault"] is None


# ── base_mint_6039568.json: Base tokenId 6039568's own deposit tx -------
# A 14-item SUBSET of the real tx's full log list (indices 294-299,
# 302-309 - indices 300/301, both plain ERC20 Transfers into the pool via
# the position adapter, are absent - see HANDOFF_maxfi_ledger.md's Commit
# 3a landing note). Not the complete response; asserting len == 14 here
# documents that, rather than padding or guessing at the missing two.

def test_base_mint_fourteen_items_two_recognized():
    items = load("base_mint_6039568.json")["items"]
    assert len(items) == 14
    records = [ml.decode_log(i) for i in items]
    recognized = [r for r in records if r is not None]
    assert len(recognized) == 2
    assert {r["event_type"] for r in recognized} == {"IncreaseLiquidity", "PositionCreated"}


def test_base_mint_increase_liquidity_exact_wei_amounts():
    items = load("base_mint_6039568.json")["items"]
    records = [ml.decode_log(i) for i in items]
    il = next(r for r in records if r and r["event_type"] == "IncreaseLiquidity")
    d = decoded(il)
    assert d["token_id"] == 6039568
    assert d["liquidity"] == 3473656907099
    assert d["amount0"] == 1905032765586610
    assert d["amount1"] == 5000000
    assert il["topic0"] == ml.TOPIC_INCREASE_LIQUIDITY


def test_base_mint_position_created_matches_same_token_id_and_pool():
    items = load("base_mint_6039568.json")["items"]
    records = [ml.decode_log(i) for i in items]
    pc = next(r for r in records if r and r["event_type"] == "PositionCreated")
    d = decoded(pc)
    assert d["token_id"] == 6039568
    assert d["pool_id"] == "0x12fc2fd09d3d3bfeca3b2a731167f3740c3a543755afa8d0d93fd95889e41796"


def test_base_mint_erc20_transfer_approval_mint_logs_all_none():
    """Same "same name, different topic0" landmine as
    test_base_harvest_pool_and_npm_collect_and_burn_and_transfer_all_none -
    the plain ERC20 Transfer/Approval logs (WETH/USDC moving vault<->
    adapter<->NPM) and the pool-level Uniswap V3 Mint log in this same tx
    are none of them in this module's tracked vocabulary and must all
    decode to None.
    """
    items = load("base_mint_6039568.json")["items"]
    records = [ml.decode_log(i) for i in items]
    by_topic = {i["topics"][0].lower(): r for i, r in zip(items, records)}
    transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    approval_topic = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
    pool_mint_topic = "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde"
    assert by_topic[transfer_topic] is None
    assert by_topic[approval_topic] is None
    assert by_topic[pool_mint_topic] is None
    # And confirm these are really distinct from every tracked topic0.
    assert transfer_topic not in ml._DECODERS
    assert approval_topic not in ml._DECODERS
    assert pool_mint_topic not in ml._DECODERS


# ── rh_harvest_908769.json: mirrors the Base shape on Robinhood Chain ---

def test_rh_harvest_exactly_two_of_eleven_recognized():
    items = load("rh_harvest_908769.json")["items"]
    assert len(items) == 11
    records = [ml.decode_log(i) for i in items]
    recognized = [r for r in records if r is not None]
    assert len(recognized) == 2
    assert {r["event_type"] for r in recognized} == {"FeesHarvested", "ProtocolFeesDistributed"}


def test_rh_harvest_exact_wei_amounts():
    items = load("rh_harvest_908769.json")["items"]
    records = [ml.decode_log(i) for i in items]
    fh = next(r for r in records if r and r["event_type"] == "FeesHarvested")
    d = decoded(fh)
    assert d["token_id"] == 908769
    assert d["fees0"] == 1920374570879319
    assert d["fees1"] == 164307542526138520213

    pfd = next(r for r in records if r and r["event_type"] == "ProtocolFeesDistributed")
    d2 = decoded(pfd)
    assert d2["token_id"] == 908769
    assert d2["treasury0"] == 288056185631897
    assert d2["treasury1"] == 24646131378920778031
    assert d2["referral0"] == 0
    assert d2["referral1"] == 0


def test_rh_harvest_split_is_85_15_0():
    items = load("rh_harvest_908769.json")["items"]
    records = [ml.decode_log(i) for i in items]
    fh = decoded(next(r for r in records if r and r["event_type"] == "FeesHarvested"))
    pfd = decoded(next(r for r in records if r and r["event_type"] == "ProtocolFeesDistributed"))
    net0 = fh["fees0"] - pfd["treasury0"] - pfd["referral0"]
    net1 = fh["fees1"] - pfd["treasury1"] - pfd["referral1"]
    assert net0 == 1632318385247422
    assert abs(pfd["treasury0"] / fh["fees0"] - 0.15) < 0.0001
    assert abs(net1 / fh["fees1"] - 0.85) < 0.0001


# ── rh_bridge_negative.json: the explicit negative case ------------------

def test_rh_bridge_negative_all_five_decode_to_none():
    items = load("rh_bridge_negative.json")["items"]
    assert len(items) == 5
    records = [ml.decode_log(i) for i in items]
    assert all(r is None for r in records)


# ── base_swap_page.json: 1000-row truncated page, Swap decode + pricing --

def test_base_swap_page_all_rows_decode_to_swap():
    rows = load("base_swap_page.json")["result"]
    assert len(rows) == 1000
    records = [ml.decode_log(r) for r in rows]
    assert all(r is not None and r["event_type"] == "Swap" for r in records)
    assert all(r["pool_address"] == "0xd0b53d9277642d899df5c87a3966a349a798f224" for r in records)
    assert all(r["vault"] is None and r["token_id"] is None for r in records)


def test_base_swap_price_matches_known_eth_price_within_one_percent():
    rows = load("base_swap_page.json")["result"]
    record = ml.decode_swap(rows[0], decimals0=18, decimals1=6)
    price = record["price_token1_per_token0"]
    assert abs(price - 2621) / 2621 < 0.01
    d = decoded(record)
    assert d["tick"] == -197610


def test_decode_swap_raises_on_non_swap_log():
    items = load("base_harvest_6039568.json")["items"]
    fh_log = next(i for i in items if i["topics"][0].lower() == ml.TOPIC_FEES_HARVESTED)
    try:
        ml.decode_swap(fh_log, 18, 6)
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_price_at_or_before_selects_correct_swap():
    rows = load("base_swap_page.json")["result"]
    result = ml.price_at_or_before(rows, target_block=51494865)
    assert result is not None
    assert result["block_number"] == 51494865

    result_none = ml.price_at_or_before(rows, target_block=1)
    assert result_none is None

    result_last = ml.price_at_or_before(rows, target_block=99999999)
    last_block = max(int(r["blockNumber"], 16) for r in rows)
    assert result_last["block_number"] == last_block


# ── Commit 3b.2: usd_price_at_or_before / position_usd_value -------------

def _sqrt_price_x96_for(price_t1_per_t0, decimals0, decimals1):
    """Test-only inverse of maxfi_math.sqrt_price_x96_to_price, used
    purely to construct a synthetic Swap log with a round, hand-checkable
    price - never used by production code (that always goes the other
    direction, real sqrtPriceX96 -> price)."""
    from decimal import Decimal
    Q96 = 2 ** 96
    ratio_squared = Decimal(price_t1_per_t0) / (Decimal(10) ** (decimals0 - decimals1))
    return int(ratio_squared.sqrt() * Q96)


def _synthetic_swap_log(sqrt_price_x96, block_number, pool_address="0x" + "aa" * 20, log_index=0):
    words = [
        format(0, "064x"),  # amount0 - unused by pricing
        format(0, "064x"),  # amount1 - unused by pricing
        format(sqrt_price_x96, "064x"),
        format(0, "064x"),  # liquidity - unused by pricing
        format(0, "064x"),  # tick - unused by pricing
    ]
    return {
        "address": pool_address,
        "topics": [ml.TOPIC_SWAP, "0x" + "11" * 32, "0x" + "22" * 32],
        "data": "0x" + "".join(words),
        "blockNumber": hex(block_number),
        "timeStamp": hex(1700000000 + block_number),
        "transactionHash": "0x" + format(block_number, "x").rjust(64, "0"),
        "logIndex": hex(log_index),
    }


def test_usd_price_at_or_before_direct_stable_token1_matches_known_eth_price():
    """Real fixture, real ground truth (test_base_swap_price_matches_known_
    eth_price_within_one_percent's own $2621/ETH) - anchor_is_token1=True
    (USDC is token1, anchor_usd=1.0) must reproduce the same ~$2621."""
    rows = load("base_swap_page.json")["result"]
    target_block = int(rows[0]["blockNumber"], 16)
    usd = ml.usd_price_at_or_before(rows, target_block, decimals0=18, decimals1=6, anchor_is_token1=True, anchor_usd=1.0)
    assert usd is not None
    assert abs(usd - 2621) / 2621 < 0.01


def test_usd_price_at_or_before_direct_stable_token0_inverts():
    """Synthetic pool, stablecoin on token0 (decimals0=6) instead of
    token1 - anchor_is_token1=False must invert the ratio, not reuse it
    directly. price_t1_per_t0 constructed for exactly 500 ALT per 1 USDC
    (1 ALT = $0.002)."""
    sqrt_price_x96 = _sqrt_price_x96_for(500, decimals0=6, decimals1=18)
    log = _synthetic_swap_log(sqrt_price_x96, block_number=1000)
    usd = ml.usd_price_at_or_before([log], target_block=1000, decimals0=6, decimals1=18, anchor_is_token1=False, anchor_usd=1.0)
    assert usd is not None
    assert abs(usd - 0.002) / 0.002 < 1e-6


def test_usd_price_at_or_before_hop_composes_two_pools():
    """Hop case (HANDOFF ruling 10): a position pool (synthetic ALT/WETH,
    token1=WETH) priced via the REAL WETH/USDC fixture as its anchor -
    two separate calls, composed by the caller, exactly as
    usd_price_at_or_before's own docstring says a hop must be done."""
    rows = load("base_swap_page.json")["result"]
    hop_target_block = int(rows[0]["blockNumber"], 16)
    weth_usd = ml.usd_price_at_or_before(
        rows, hop_target_block, decimals0=18, decimals1=6, anchor_is_token1=True, anchor_usd=1.0
    )
    assert weth_usd is not None

    # Position pool: token0=ALT (decimals 18), token1=WETH (decimals 18),
    # rate fixed at exactly 0.0004 WETH per 1 ALT (2500 ALT = 1 WETH).
    sqrt_price_x96 = _sqrt_price_x96_for(0.0004, decimals0=18, decimals1=18)
    position_log = _synthetic_swap_log(sqrt_price_x96, block_number=2000)
    alt_usd = ml.usd_price_at_or_before(
        [position_log], target_block=2000, decimals0=18, decimals1=18,
        anchor_is_token1=True, anchor_usd=weth_usd,
    )
    assert alt_usd is not None
    expected = weth_usd * 0.0004
    assert abs(alt_usd - expected) / expected < 1e-9


def test_usd_price_at_or_before_returns_none_with_no_swap_at_or_before_target():
    log = _synthetic_swap_log(_sqrt_price_x96_for(1.0, 18, 18), block_number=5000)
    usd = ml.usd_price_at_or_before([log], target_block=1, decimals0=18, decimals1=18, anchor_is_token1=True, anchor_usd=1.0)
    assert usd is None


def test_position_usd_value_sums_both_sides():
    # amount0 = 2 * 10**18 wei (2 tokens, 18 decimals) at $3/token = $6
    # amount1 = 500 * 10**6 wei (500 tokens, 6 decimals) at $1/token = $500
    usd = ml.position_usd_value(2 * 10**18, 500 * 10**6, decimals0=18, decimals1=6, token0_usd=3.0, token1_usd=1.0)
    assert abs(usd - 506.0) < 1e-9


def test_position_usd_value_none_if_either_price_missing():
    assert ml.position_usd_value(1, 1, 18, 6, None, 1.0) is None
    assert ml.position_usd_value(1, 1, 18, 6, 1.0, None) is None


# ── PoolAdded: synthetic-but-ABI-exact (Commit 3a) ------------------------
#
# NOT a captured Blockscout response - no real PoolAdded log exists in any
# fixture (it fires once per pool at admin-approval time, not on every
# deposit). Built inline from the sourcify-verified SnuggleVaultUpgradeable
# ABI (module docstring), using the mint tx's own real pool/token values so
# this test data stays internally consistent with the rest of the fixture
# set. Constructed here rather than as a fixtures/ file per that
# directory's own README convention (recorded responses only).
#
# UPDATE (Commit 3a addendum): base_mint_6039568.json (the real captured
# Blockscout tx-logs bundle for the Base tokenId 6039568 mint tx,
# 0xa8544cd39a163083f5eeb69bd9643dc62150cbd44136ca1c66f095e18028520c - a
# 14-item subset, see that fixture's own test section below) has since
# been added, closing the gap this note originally flagged. Checked
# explicitly against it: no real PoolAdded log exists in this tx either
# (it fires once per pool at admin-approval time, not on every deposit -
# same reasoning as above), so nothing about this synthetic test changes.
# The topic0-vs-fixture cross-check and real-data tests this note used to
# say were deferred are now written (see
# test_topic0_increase_liquidity_matches_fixture and the
# base_mint_6039568.json test section below).

_POOL_ADDED_DECODED = {
    "pool_id": "0x12fc2fd09d3d3bfeca3b2a731167f3740c3a543755afa8d0d93fd95889e41796",
    "pool": "0xd0b53d9277642d899df5c87a3966a349a798f224",
    "token0": "0x4200000000000000000000000000000000000006",
    "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    "fee": 500,
    "position_adapter": "0xca4cf963c71234a4f7d44a750b4d3847b4debabd",
    "reward_adapter": "0x0000000000000000000000000000000000000000",
}

_POOL_ADDED_LOG = {
    "address": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "blockNumber": hex(50000001),
    "data": (
        "0x000000000000000000000000d0b53d9277642d899df5c87a3966a349a798f224"
        "0000000000000000000000004200000000000000000000000000000000000006"
        "000000000000000000000000833589fcd6edb6e08f4c7c32d4f71b54bda02913"
        "00000000000000000000000000000000000000000000000000000000000001f4"
        "000000000000000000000000ca4cf963c71234a4f7d44a750b4d3847b4debabd"
        "0000000000000000000000000000000000000000000000000000000000000000"
    ),
    "logIndex": hex(0),
    "timeStamp": hex(1700000000),
    "topics": [
        ml.TOPIC_POOL_ADDED,
        _POOL_ADDED_DECODED["pool_id"],
    ],
    "transactionHash": "0x" + "5ee7748accef" + "0" * 52,
}


def test_pool_added_synthetic_but_abi_exact_decodes():
    record = ml.decode_log(_POOL_ADDED_LOG)
    assert record is not None
    assert record["event_type"] == "PoolAdded"
    assert record["topic0"] == ml.TOPIC_POOL_ADDED
    d = decoded(record)
    assert d == _POOL_ADDED_DECODED


# ── Commit 3b.1.5: FeesCompounded/FeesHarvestedDirect real layout -------
# Real 11-log Base StakingManager page (keeper batch tx touching three
# owners' positions), captured live via Alchemy, Base block 0x2a9d8a6.
# Raw RPC-shape logs carry blockTimestamp, not timeStamp -
# maxfi_ledger._normalize_log's Etherscan branch reads log["timeStamp"]
# unconditionally. This file must not import maxfi_ledger_ingest this
# commit (only maxfi_ledger.py and this test file may change) - _adapt()
# below is a tiny test-local stand-in for that module's own
# rpc_log_to_etherscan_shape(), not a duplicate of its full contract
# (no blockTimestamp-absent fallback needed - every log in this fixture
# has one).

def _adapt(raw_log):
    log = dict(raw_log)
    log["timeStamp"] = log.pop("blockTimestamp")
    return log


def test_staking_manager_page_eleven_logs_event_type_split():
    """11 logs: 3 FeesHarvestedDirect + 2 FeesCompounded (this commit's
    fix) + 3 ProtocolFeesDistributed (topic0 0x017fe984..., already
    tracked by an existing decoder - NOT one of the still-unidentified
    topic0s, despite this commit's task description assuming otherwise)
    + 3 genuinely unrecognized (0xe6d1ff39..., 0xdd8df9cd..., 0x627009b4...,
    noted-not-scoped in HANDOFF_maxfi_ledger.md).
    """
    rows = load("base_staking_manager_page_0x2a9d8a6.json")
    assert len(rows) == 11
    records = [ml.decode_log(_adapt(r)) for r in rows]
    event_types = [r["event_type"] if r else None for r in records]
    assert event_types.count("FeesHarvestedDirect") == 3
    assert event_types.count("FeesCompounded") == 2
    assert event_types.count("ProtocolFeesDistributed") == 3
    assert event_types.count(None) == 3


def test_staking_manager_page_log_0x6a_fees_harvested_direct_for_glenn():
    rows = load("base_staking_manager_page_0x2a9d8a6.json")
    row = next(r for r in rows if r["logIndex"] == "0x6a")
    record = ml.decode_log(_adapt(row))
    assert record is not None
    assert record["event_type"] == "FeesHarvestedDirect"
    d = decoded(record)
    assert d["token_id"] == 4956448
    assert d["owner"] == "0xab7a515c6e2eea5140ed8a5b09a7d782f3b26743"
    assert d["amount0"] == 0
    assert d["amount1"] == 1795


def test_staking_manager_page_log_0x6b_fees_compounded_for_glenn():
    rows = load("base_staking_manager_page_0x2a9d8a6.json")
    row = next(r for r in rows if r["logIndex"] == "0x6b")
    record = ml.decode_log(_adapt(row))
    assert record is not None
    assert record["event_type"] == "FeesCompounded"
    d = decoded(record)
    assert d["token_id"] == 4956448
    assert d["owner"] == "0xab7a515c6e2eea5140ed8a5b09a7d782f3b26743"
    assert d["amount0"] == 9606364
    assert d["amount1"] == 0


def test_staking_manager_page_log_0x50_owner_read_from_topics2_not_assumed():
    """A different owner entirely - pins that owner comes from
    topics[2], not from some fixed/assumed value carried over from the
    Glenn-owned logs above."""
    rows = load("base_staking_manager_page_0x2a9d8a6.json")
    row = next(r for r in rows if r["logIndex"] == "0x50")
    record = ml.decode_log(_adapt(row))
    assert record is not None
    assert record["event_type"] == "FeesHarvestedDirect"
    d = decoded(record)
    assert d["token_id"] == 4961418
    assert d["owner"] == "0xb99a8dc6ab78115dcac8ff3ead16779ebc218cfc"
    assert d["amount0"] == 329099
    assert d["amount1"] == 110


def test_fees_compounded_too_few_topics_raises_readable_value_error():
    log = _make_synthetic_staking_manager_log(ml.TOPIC_FEES_COMPOUNDED, topic_count=2, data_word_count=2)
    try:
        ml.decode_log(log)
        raised = None
    except ValueError as e:
        raised = e
    assert raised is not None
    assert "FeesCompounded" in str(raised)
    assert "topics" in str(raised)


def test_fees_harvested_direct_too_few_data_words_raises_readable_value_error():
    log = _make_synthetic_staking_manager_log(ml.TOPIC_FEES_HARVESTED_DIRECT, topic_count=3, data_word_count=1)
    try:
        ml.decode_log(log)
        raised = None
    except ValueError as e:
        raised = e
    assert raised is not None
    assert "FeesHarvestedDirect" in str(raised)
    assert "data" in str(raised)


def _make_synthetic_staking_manager_log(topic0, topic_count, data_word_count):
    topics = [topic0, hex(100)]
    if topic_count >= 3:
        topics.append("0x000000000000000000000000ab7a515c6e2eea5140ed8a5b09a7d782f3b26743")
    data = "0x" + "".join(format(i, "064x") for i in range(data_word_count))
    return {
        "address": "0x4994743d7183d2ea5c651292a9dab2c781020638",
        "blockNumber": hex(44700000),
        "timeStamp": hex(1700000000),
        "transactionHash": "0x" + "cc" * 32,
        "logIndex": hex(0),
        "topics": topics,
        "data": data,
    }


def test_derive_position_ledger_fees_compounded_flows_into_compounded_totals():
    """Regression pin on derive (derive_position_ledger/derive_all
    themselves untouched by this commit - only maxfi_ledger.py's two
    decoders changed). Builds a minimal real event set for tokenId
    4956448: the real PositionCreated row from
    base_position_created.json plus the two real, now-correctly-decoded
    fixture records above (0x6a FeesHarvestedDirect, 0x6b FeesCompounded).

    Only compounded0/compounded1 are asserted. derive_position_ledger()'s
    main loop has NO branch for event_type == "FeesHarvestedDirect" at
    all - that event only ever affects claimed_net indirectly, via
    _tx_net_claim(), and only for a tx that ALSO contains a plain
    FeesHarvested event (module docstring's _tx_net_claim rebalance-tx
    branch). This event set deliberately has no FeesHarvested event, so
    claimed_gross/claimed_net stay at 0 - current, unmodified derive
    behavior, verified by reading derive_position_ledger() directly
    before writing this assertion, not assumed.
    """
    pc_rows = load("base_position_created.json")["result"]
    pc_row = next(r for r in pc_rows if int(r["topics"][1], 16) == 4956448)
    pc_record = ml.decode_log(pc_row)
    assert pc_record["event_type"] == "PositionCreated"

    sm_rows = load("base_staking_manager_page_0x2a9d8a6.json")
    fhd_row = next(r for r in sm_rows if r["logIndex"] == "0x6a")
    fc_row = next(r for r in sm_rows if r["logIndex"] == "0x6b")
    fhd_record = ml.decode_log(_adapt(fhd_row))
    fc_record = ml.decode_log(_adapt(fc_row))
    assert fhd_record["event_type"] == "FeesHarvestedDirect"
    assert fc_record["event_type"] == "FeesCompounded"

    events = [pc_record, fhd_record, fc_record]
    for event in events:
        event["chain"] = "base"

    row = ml.derive_position_ledger(events, (pc_record["vault"], None, "4956448"))

    assert row["compounded0_wei"] == "9606364"
    assert row["compounded1_wei"] == "0"
    # Documented, not asserted-away: claimed_gross/claimed_net stay "0"
    # here - see this test's own docstring for why that is current,
    # correct derive behavior for this event combination, not a gap
    # this commit introduces or is responsible for closing.
    assert row["claimed_gross0_wei"] == "0"
    assert row["claimed_net0_wei"] == "0"


# ── Commit 3b.3b-2: base_rebalance_batch_0xd2b724f3 - a real keeper batch
# rebalance tx (Base block 51383244, 2026-09-16), complete tx logs 112-258
# across three Blockscout v2 /api/v2/transactions/<hash>/logs pages. Three
# vault positions rebalanced with full harvest clusters (5955462 -> 6009049,
# 5997350 -> 6009050, 5984382 -> 6009051 = position id 113) plus one
# PancakeSwap-NPM position (2124374 -> 2124648) with no harvest cluster. ──

BATCH_TX = "0xd2b724f3166fc96e711aeb48946bc59f032e172a1d454db5038e457684bc21c1"
BATCH_PAGES = [f"base_rebalance_batch_0xd2b724f3_page{n}.json" for n in (1, 2, 3)]
PANCAKE_NPM = "0x46a15b0b27311cedf172ab29e4f4766fbe7f4364"


def load_batch_items():
    items = []
    for name in BATCH_PAGES:
        items.extend(load(name)["items"])
    return items


def test_batch_fixture_pages_are_complete_contiguous_and_one_tx():
    pages = [load(name) for name in BATCH_PAGES]
    indexes = sorted(item["index"] for page in pages for item in page["items"])
    assert indexes == list(range(112, 259))
    assert pages[-1]["next_page_params"] is None
    assert all(item["transaction_hash"] == BATCH_TX for page in pages for item in page["items"])


def test_batch_fixture_decodes_expected_vault_event_counts():
    records = [ml.decode_log(item) for item in load_batch_items()]
    records = [r for r in records if r is not None]
    counts = {}
    for r in records:
        counts[r["event_type"]] = counts.get(r["event_type"], 0) + 1
    assert counts == {
        "IncreaseLiquidity": 5, "SnuggleRebalanced": 5, "FeesHarvested": 3,
        "ProtocolFeesDistributed": 3, "FeesHarvestedDirect": 3, "FeesCompounded": 3,
    }
    assert all(r["tx_hash"] == BATCH_TX and r["block_number"] == 51383244 for r in records)


def test_batch_fixture_log_217_is_id_113_rebalance_with_protocol_fees_equal_to_pfd():
    by_index = {item["index"]: item for item in load_batch_items()}
    reb = ml.decode_log(by_index[217])
    assert reb["event_type"] == "SnuggleRebalanced"
    assert reb["log_index"] == 217
    d = decoded(reb)
    assert d["old_token_id"] == 5984382
    assert d["new_token_id"] == 6009051
    assert d["owner"] == "0xab7a515c6e2eea5140ed8a5b09a7d782f3b26743"
    assert (d["protocol_fee0"], d["protocol_fee1"]) == (6129085, 544066)
    pfd = decoded(ml.decode_log(by_index[199]))
    assert pfd["token_id"] == 5984382
    assert (pfd["treasury0"], pfd["treasury1"]) == (d["protocol_fee0"], d["protocol_fee1"])


def test_batch_fixture_harvest_cluster_events_are_keyed_by_the_old_token_id():
    """FeesHarvested / ProtocolFeesDistributed / FeesHarvestedDirect /
    FeesCompounded all carry the OLD tokenId in a rebalance tx - the new
    mint only ever appears in IncreaseLiquidity and SnuggleRebalanced.
    This is the fact _tx_net_claim's rebalance branch keys on."""
    records = [r for r in (ml.decode_log(i) for i in load_batch_items()) if r is not None]
    for event_type in ("FeesHarvested", "ProtocolFeesDistributed", "FeesHarvestedDirect", "FeesCompounded"):
        token_ids = sorted(decoded(r)["token_id"] for r in records if r["event_type"] == event_type)
        assert token_ids == [5955462, 5984382, 5997350], event_type
    new_mints = sorted(decoded(r)["token_id"] for r in records if r["event_type"] == "IncreaseLiquidity")
    assert new_mints == [2124648, 6009048, 6009049, 6009050, 6009051]


def test_batch_fixture_pancake_segment_has_no_harvest_cluster_and_zero_protocol_fee():
    records = [r for r in (ml.decode_log(i) for i in load_batch_items()) if r is not None]
    reb = next(decoded(r) for r in records
               if r["event_type"] == "SnuggleRebalanced" and decoded(r)["old_token_id"] == 2124374)
    assert reb["new_token_id"] == 2124648
    assert (reb["protocol_fee0"], reb["protocol_fee1"]) == (0, 0)
    cluster_tokens = {decoded(r)["token_id"] for r in records if r["event_type"] in (
        "FeesHarvested", "ProtocolFeesDistributed", "FeesHarvestedDirect", "FeesCompounded")}
    assert 2124374 not in cluster_tokens and 2124648 not in cluster_tokens
    il = next(r for r in records if r["event_type"] == "IncreaseLiquidity" and decoded(r)["token_id"] == 2124648)
    assert il["contract_address"] == PANCAKE_NPM
