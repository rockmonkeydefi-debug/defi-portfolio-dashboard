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
