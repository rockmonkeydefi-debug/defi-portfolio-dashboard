"""Adjudication 1 (3b.3b-adj-1) - lineage-aware claims rollup in
GET /api/maxfi/ledger-reconciliation (HANDOFF_maxfi_ledger.md).

The scanner updates maxfi_positions.token_id IN PLACE on a rebalance and a
rebalance-tx harvest carries the OLD tokenId, so claims on predecessor /
successor tokens were invisible to a (chain, row.token_id) join. The route
now walks maxfi_ledger_positions.rebalanced_from/to_token_id and assigns
every lineage token to exactly one app row (nearest app row at or before
it in chain order, else the chain's earliest app row). Basis and exit stay
on the row's OWN token.

Part 1 unit-tests the pure helper wp._maxfi_ledger_lineage_assignment.
Part 2 exercises the route. Every expected value below is hand-computed
from the seeded data, never derived from the code under test.

Seeding helpers and the client/db fixtures are IMPORTED from
tests/test_maxfi_ledger_reconciliation.py (tests/ has no __init__.py, so
pytest's default prepend import mode puts tests/ on sys.path). Only
underscore helpers and fixtures are imported - never a test_* function,
so nothing from that module is collected twice.
"""
import web_portfolio as wp

from test_maxfi_ledger_reconciliation import (  # noqa: F401  (client/db are fixtures)
    RECON_URL,
    _forbid_rpc,
    _get_position,
    _seed_claim,
    _seed_closing_value,
    _seed_initial_value,
    _seed_ledger_claim,
    _seed_ledger_event,
    _seed_ledger_position,
    _seed_position,
    client,
    db,
)


def _linear(chain, tokens):
    """ledger_links for a strictly linear chain tokens[0] -> ... -> tokens[-1]."""
    links = {}
    for i, t in enumerate(tokens):
        prev_t = tokens[i - 1] if i > 0 else None
        next_t = tokens[i + 1] if i + 1 < len(tokens) else None
        links[(chain, t)] = (prev_t, next_t)
    return links


def _assign(links, app_rows):
    return wp._maxfi_ledger_lineage_assignment(links, app_rows)


# ══ Part 1: pure helper ══════════════════════════════════════════════════

def test_helper_linear_chain_app_row_on_head_takes_all_three():
    out = _assign(_linear("base", ["100", "200", "300"]), [(7, "base", "300")])
    assert out["token_owner"] == {("base", "100"): 7, ("base", "200"): 7, ("base", "300"): 7}
    assert out["position_lineage"] == {7: {
        "root_token_id": "100", "head_token_id": "300",
        "assigned_token_ids": ["100", "200", "300"], "lineage_token_count": 3,
    }}
    assert out["unattributed"] == []


def test_helper_app_row_on_middle_token_takes_predecessor_and_successor():
    """The pos 114 shape: the app row sits mid-chain."""
    out = _assign(_linear("base", ["100", "200", "300"]), [(114, "base", "200")])
    assert out["token_owner"] == {("base", "100"): 114, ("base", "200"): 114, ("base", "300"): 114}
    assert out["position_lineage"][114]["assigned_token_ids"] == ["100", "200", "300"]


def test_helper_two_app_rows_split_the_chain_at_the_later_row():
    """The pos 5/34 shape: A,B -> 5 and C,D -> 34."""
    out = _assign(_linear("base", ["1", "2", "3", "4"]), [(5, "base", "1"), (34, "base", "3")])
    assert out["token_owner"] == {("base", "1"): 5, ("base", "2"): 5, ("base", "3"): 34, ("base", "4"): 34}
    assert out["position_lineage"] == {
        5: {"root_token_id": "1", "head_token_id": "4", "assigned_token_ids": ["1", "2"], "lineage_token_count": 4},
        34: {"root_token_id": "1", "head_token_id": "4", "assigned_token_ids": ["3", "4"], "lineage_token_count": 4},
    }


def test_helper_predecessors_before_first_app_row_fall_back_to_it():
    """App row only on C of A->B->C->D: A and B precede every app row and
    fall back to the chain's earliest app row; D is a successor of C."""
    out = _assign(_linear("base", ["10", "20", "30", "40"]), [(3, "base", "30")])
    assert out["token_owner"] == {("base", "10"): 3, ("base", "20"): 3, ("base", "30"): 3, ("base", "40"): 3}
    assert out["position_lineage"][3]["assigned_token_ids"] == ["10", "20", "30", "40"]
    assert out["position_lineage"][3]["lineage_token_count"] == 4


def test_helper_chain_with_no_app_row_is_unattributed():
    links = _linear("base", ["500", "600"])
    links.update(_linear("robinhood", ["500"]))  # same token id, other chain
    out = _assign(links, [(1, "base", "999")])  # app row elsewhere, no ledger row
    assert out["unattributed"] == [("base", ["500", "600"]), ("robinhood", ["500"])]
    assert out["token_owner"] == {("base", "999"): 1}


def test_helper_two_token_cycle_terminates_and_assigns_each_token_once():
    links = {("base", "10"): ("20", "20"), ("base", "20"): ("10", "10")}
    out = _assign(links, [(9, "base", "20")])
    assert out["token_owner"] == {("base", "10"): 9, ("base", "20"): 9}
    assert out["position_lineage"][9] == {
        "root_token_id": "10", "head_token_id": "20",
        "assigned_token_ids": ["10", "20"], "lineage_token_count": 2,
    }
    no_app = _assign(links, [])
    assert no_app["unattributed"] == [("base", ["10", "20"])]
    assert no_app["token_owner"] == {}


def test_helper_duplicate_app_rows_lowest_id_owns_higher_gets_empty():
    out = _assign({}, [(4, "base", "1"), (2, "base", "1")])
    assert out["token_owner"] == {("base", "1"): 2}
    assert out["position_lineage"][2]["assigned_token_ids"] == ["1"]
    assert out["position_lineage"][4]["assigned_token_ids"] == []

    chained = _assign(_linear("base", ["100", "200"]), [(8, "base", "200"), (3, "base", "200")])
    assert chained["token_owner"] == {("base", "100"): 3, ("base", "200"): 3}
    assert chained["position_lineage"][3]["assigned_token_ids"] == ["100", "200"]
    assert chained["position_lineage"][8] == {
        "root_token_id": "100", "head_token_id": "200",
        "assigned_token_ids": [], "lineage_token_count": 2,
    }


def test_helper_app_token_without_ledger_row_maps_to_itself():
    out = _assign(_linear("base", ["100", "200"]), [(1, "base", "100"), (2, "base", "77")])
    assert out["token_owner"][("base", "77")] == 2
    assert out["position_lineage"][2] == {
        "root_token_id": "77", "head_token_id": "77",
        "assigned_token_ids": ["77"], "lineage_token_count": 1,
    }


def test_helper_dangling_to_ends_the_chain_cleanly():
    links = {("base", "100"): (None, "200"), ("base", "200"): ("100", "999")}  # 999 has no ledger row
    out = _assign(links, [(1, "base", "100")])
    assert out["token_owner"] == {("base", "100"): 1, ("base", "200"): 1}
    assert out["position_lineage"][1] == {
        "root_token_id": "100", "head_token_id": "200",
        "assigned_token_ids": ["100", "200"], "lineage_token_count": 2,
    }


# ══ Part 2: route ════════════════════════════════════════════════════════

def _link(db, chain, tokens, **per_token):
    """Seed one maxfi_ledger_positions row per token of a linear chain,
    with rebalanced_from/to set; per_token[t] adds column overrides."""
    for i, t in enumerate(tokens):
        overrides = {
            "chain": chain, "token_id": t,
            "rebalanced_from_token_id": tokens[i - 1] if i > 0 else None,
            "rebalanced_to_token_id": tokens[i + 1] if i + 1 < len(tokens) else None,
        }
        overrides.update(per_token.get(t, {}))
        _seed_ledger_position(db, **overrides)


def _harvest(db, chain, token_id, ts, tx, usd):
    _seed_ledger_event(db, chain, token_id, "FeesHarvested", ts,
                       {"token_id": int(token_id), "fees0": 1, "fees1": 1}, tx_hash=tx)
    _seed_ledger_claim(db, chain, token_id, tx, ts, usd)


def test_route_manual_claim_pairs_with_priced_harvest_on_predecessor(client, db, monkeypatch):
    _forbid_rpc(monkeypatch)
    _seed_position(db, 1, token_id="200")
    _seed_claim(db, 1, "2026-03-01", 50.0)
    _link(db, "base", ["100", "200"])
    _harvest(db, "base", "100", "2026-03-01T06:00:00Z", "0x" + "a1" * 32, 50.0)

    pos = _get_position(client.get(RECON_URL).get_json(), 1)
    assert pos["claims"]["status"] == "matched"
    assert pos["claims"]["claims"][0]["status"] == "matched"
    assert pos["claims"]["claims"][0]["ledger_usd"] == 50.0
    assert pos["claims"]["ledger_context"]["ledger_fees_harvested_event_count"] == 1


def test_route_harvest_on_successor_token_is_visible_to_app_row(client, db, monkeypatch):
    _forbid_rpc(monkeypatch)
    _seed_position(db, 1, token_id="200")
    _link(db, "base", ["200", "300"])
    _harvest(db, "base", "300", "2026-03-05T00:00:00Z", "0x" + "a2" * 32, 20.0)

    pos = _get_position(client.get(RECON_URL).get_json(), 1)
    assert pos["claims"]["status"] == "ledger_only"
    assert pos["claims"]["ledger_context"]["ledger_fees_harvested_event_count"] == 1
    assert [e["ledger_usd"] for e in pos["claims"]["unpaired_ledger_events"]] == [20.0]


def test_route_two_app_rows_on_one_chain_each_harvest_counted_once(client, db, monkeypatch):
    """Chain 100->200->300->400, app rows pos 1 on "100" and pos 2 on "300".
    Harvests on 100, 200 (-> pos 1) and 400 (-> pos 2): 3 events, 3 counted."""
    _forbid_rpc(monkeypatch)
    _seed_position(db, 1, token_id="100")
    _seed_position(db, 2, token_id="300")
    _link(db, "base", ["100", "200", "300", "400"])
    _harvest(db, "base", "100", "2026-03-01T00:00:00Z", "0x" + "b1" * 32, 1.0)
    _harvest(db, "base", "200", "2026-03-02T00:00:00Z", "0x" + "b2" * 32, 2.0)
    _harvest(db, "base", "400", "2026-03-04T00:00:00Z", "0x" + "b4" * 32, 4.0)

    body = client.get(RECON_URL).get_json()
    p1, p2 = _get_position(body, 1), _get_position(body, 2)
    assert p1["claims"]["ledger_context"]["ledger_fees_harvested_event_count"] == 2
    assert p2["claims"]["ledger_context"]["ledger_fees_harvested_event_count"] == 1
    assert sorted(e["ledger_usd"] for e in p1["claims"]["unpaired_ledger_events"]) == [1.0, 2.0]
    assert [e["ledger_usd"] for e in p2["claims"]["unpaired_ledger_events"]] == [4.0]
    assert sum(body["summary"]["claims"].values()) == 2
    assert body["summary"]["claims"]["ledger_only"] == 2


def test_route_unattributed_lineages_exact_per_chain(client, db, monkeypatch):
    """Base: attributed chain 100->200 (pos 1, one $99 claim - must NOT
    count), unattributed chain 500->600 (claims $10.00, $2.50, one
    unpriced) and unattributed single token 800 (no claims) -> 2 lineages,
    3 claims, $12.50, 1 unpriced. Robinhood: one attributed ledger row ->
    present with zeros."""
    _forbid_rpc(monkeypatch)
    _seed_position(db, 1, token_id="200")
    _link(db, "base", ["100", "200"])
    _harvest(db, "base", "100", "2026-03-01T00:00:00Z", "0x" + "c1" * 32, 99.0)
    _link(db, "base", ["500", "600"])
    _seed_ledger_claim(db, "base", "500", "0x" + "c5" * 32, "2026-03-01T00:00:00Z", 10.0)
    _seed_ledger_claim(db, "base", "600", "0x" + "c6" * 32, "2026-03-02T00:00:00Z", 2.5)
    _seed_ledger_claim(db, "base", "600", "0x" + "c7" * 32, "2026-03-03T00:00:00Z", None)
    _link(db, "base", ["800"])
    _seed_position(db, 2, chain="robinhood", token_id="7")
    _link(db, "robinhood", ["7"])

    body = client.get(RECON_URL).get_json()
    assert body["unattributed_lineages"] == {
        "base": {"lineages": 2, "claims": 3, "claimed_usd": 12.5, "unpriced_claims": 1},
        "robinhood": {"lineages": 0, "claims": 0, "claimed_usd": 0.0, "unpriced_claims": 0},
    }


def test_route_basis_and_exit_stay_on_own_token_when_linked(client, db, monkeypatch):
    _forbid_rpc(monkeypatch)
    _seed_position(db, 1, token_id="200")
    _seed_initial_value(db, 1, 100.0)
    _seed_closing_value(db, 1, 50.0)
    _link(db, "base", ["100", "200"], **{
        "100": {"opened_at": "2026-01-01T00:00:00Z", "basis_price_usd": 999.0,
                "closed_at": "2026-02-01T00:00:00Z", "exit_price_usd": 888.0, "claimed_net0_wei": "111"},
        "200": {"opened_at": "2026-02-01T00:00:00Z", "basis_price_usd": 100.0,
                "closed_at": "2026-03-01T00:00:00Z", "exit_price_usd": 50.0, "claimed_net0_wei": "222"},
    })

    pos = _get_position(client.get(RECON_URL).get_json(), 1)
    assert pos["basis"]["status"] == "matched"
    assert pos["basis"]["ledger_context"]["basis_price_usd"] == 100.0
    assert pos["exit"]["status"] == "matched"
    assert pos["exit"]["ledger_context"]["exit_price_usd"] == 50.0
    assert pos["claims"]["ledger_context"]["claimed_net0_wei"] == "222"


def test_route_with_linked_chains_makes_no_rpc(client, db, monkeypatch):
    _forbid_rpc(monkeypatch)
    _seed_position(db, 1, token_id="200")
    _link(db, "base", ["100", "200", "300"])
    _link(db, "base", ["500", "600"])
    _harvest(db, "base", "100", "2026-03-01T00:00:00Z", "0x" + "d1" * 32, 5.0)

    resp = client.get(RECON_URL)
    assert resp.status_code == 200


def test_route_per_position_lineage_key_exact(client, db, monkeypatch):
    _forbid_rpc(monkeypatch)
    _seed_position(db, 1, token_id="200")
    _seed_position(db, 2, token_id="9")  # no ledger row at all
    _link(db, "base", ["100", "200", "300"])

    body = client.get(RECON_URL).get_json()
    assert _get_position(body, 1)["lineage"] == {
        "root_token_id": "100", "head_token_id": "300",
        "assigned_token_ids": ["100", "200", "300"], "lineage_token_count": 3,
    }
    assert _get_position(body, 2)["lineage"] == {
        "root_token_id": "9", "head_token_id": "9",
        "assigned_token_ids": ["9"], "lineage_token_count": 1,
    }
