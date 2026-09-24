"""Emissions C5 - GET /api/maxfi/ledger-reconciliation gains ADDITIVE
emissions keys (per-row "emissions", top-level "unattributed_reward_claims",
summary["emissions"]) through ONE read helper, _maxfi_ledger_emissions_rollup
(counted = verified + verified_aggregate only). Still a pure DB read; no
existing key changes. Seeding helpers/fixtures are imported from
tests/test_maxfi_ledger_reconciliation.py (underscore helpers + fixtures
only, the lineage-rollup tests' own convention). Expected values are
hand-computed from the seeded rows."""
import web_portfolio as wp

import maxfi_ledger_emissions as mle

from test_maxfi_ledger_reconciliation import (  # noqa: F401  (client/db are fixtures)
    RECON_URL,
    _forbid_rpc,
    _get_position,
    _seed_ledger_position,
    _seed_position,
    client,
    db,
)

AERO = "0x940181a94a35a4569e4529a3cdfb74e38fd98631"
CAKE = "0x3055913c90fcc1a6ce9a358911721eeb942013a1"
NON_COUNTED = [s for s in mle.ALL_STATUSES if s not in mle.COUNTED_STATUSES]


def _row(status, net_wei, net_usd=None, token=AERO):
    return {"reward_token": token, "verification_status": status, "net_wei": net_wei, "net_usd": net_usd}


def _seed_reward_claim(db, token_id, tx_hash, status, net_wei, net_usd=None, chain="base", reward_token=AERO):
    db.execute(
        """
        INSERT INTO maxfi_ledger_reward_claims
        (chain, tx_hash, token_id, reward_token, log_index, block_number, block_timestamp,
         gross_wei, fee_wei, treasury_wei, referral_wei, net_wei, verification_status, net_usd, computed_at)
        VALUES (?, ?, ?, ?, 1, 100, '2026-05-01T00:00:00.000000Z', ?, '0', '0', '0', ?, ?, ?,
                '2026-09-24T00:00:00+00:00')
        """,
        (chain, tx_hash, token_id, reward_token, net_wei, net_wei, status, net_usd),
    )
    db.commit()


def _link(db, chain, tokens):
    for i, t in enumerate(tokens):
        _seed_ledger_position(db, chain=chain, token_id=t,
                              rebalanced_from_token_id=tokens[i - 1] if i > 0 else None,
                              rebalanced_to_token_id=tokens[i + 1] if i + 1 < len(tokens) else None)


def _get(client):
    r = client.get(RECON_URL)
    assert r.status_code == 200
    return r.get_json()


# ── the one read helper ───────────────────────────────────────────────────

def test_every_non_counted_status_contributes_zero():
    assert set(NON_COUNTED) == {"fee_without_claim", "window_unknown", "out_of_window", "gross_disagreement",
                                "mismatch", "no_payout", "ambiguous"}
    for status in NON_COUNTED:
        out = wp._maxfi_ledger_emissions_rollup([_row(status, "1000", 5.0)])
        assert out["by_reward_token"] == {AERO: {"counted_keys": 0, "net_wei": "0", "net_usd": 0.0, "unpriced": 0}}
        assert out["by_status"][status] == 1 and sum(out["by_status"].values()) == 1


def test_counted_statuses_sum_exact_wei_and_track_unpriced():
    out = wp._maxfi_ledger_emissions_rollup([
        _row("verified", "215760000000000000000", 2.5),
        _row("verified_aggregate", "1", None),
        _row("mismatch", "999", 9.0),
        _row("verified", "7", 1.0, token=CAKE),
    ])
    assert out["by_reward_token"][AERO] == {"counted_keys": 2, "net_wei": "215760000000000000001",
                                           "net_usd": 2.5, "unpriced": 1}
    assert out["by_reward_token"][CAKE] == {"counted_keys": 1, "net_wei": "7", "net_usd": 1.0, "unpriced": 0}
    assert (out["by_status"]["verified"], out["by_status"]["verified_aggregate"], out["by_status"]["mismatch"]) == (2, 1, 1)


def test_amended_acceptance_target_rolls_up_to_the_ruled_total():
    # The 11 Base AERO nets from the Sep 24 dry-run acceptance record (amended
    # target, Glenn's ruling Q1 = A): 10 close-out keys + token 69889434.
    nets = ["43453473746189322345", "3821022968111457775", "44907450836606249630", "3050682281500181320",
            "23031889415892703971", "20925537807145975297", "56719289503162014228", "464696119531125660",
            "14372355595908421831", "885386173835962716", "4130489214614044736"]
    out = wp._maxfi_ledger_emissions_rollup([_row("verified", n, 1.0) for n in nets])
    assert out["by_reward_token"][AERO]["counted_keys"] == 11
    assert out["by_reward_token"][AERO]["net_wei"] == "215762273662497459509"


# ── route ─────────────────────────────────────────────────────────────────

def _seed_lineage_scene(db):
    """base chain 100 -> 200 -> 300 with the app row (id 1) on 200, so all
    three tokens are assigned to row 1; token 999 has a ledger row but no
    app row and no link (its own unattributed lineage)."""
    _seed_position(db, 1, chain="base", token_id="200")
    _link(db, "base", ["100", "200", "300"])
    _seed_ledger_position(db, chain="base", token_id="999")


def _seed_reward_scene(db):
    _seed_reward_claim(db, "100", "0xa1", "verified", "10", 1.0)
    _seed_reward_claim(db, "300", "0xa3", "verified_aggregate", "20", None)
    _seed_reward_claim(db, "200", "0xa2", "mismatch", "5", 0.5)
    _seed_reward_claim(db, "999", "0xa9", "verified", "40", 4.0)


def test_route_row_emissions_cover_the_assigned_lineage_tokens(client, db, monkeypatch):
    _forbid_rpc(monkeypatch)
    _seed_lineage_scene(db)
    _seed_reward_scene(db)
    body = _get(client)
    em = _get_position(body, 1)["emissions"]
    assert em["by_reward_token"] == {AERO: {"counted_keys": 2, "net_wei": "30", "net_usd": 1.0, "unpriced": 1}}
    assert (em["by_status"]["verified"], em["by_status"]["verified_aggregate"], em["by_status"]["mismatch"]) == (1, 1, 1)


def test_route_unattributed_reward_claims_and_summary_totals(client, db, monkeypatch):
    _forbid_rpc(monkeypatch)
    _seed_lineage_scene(db)
    _seed_reward_scene(db)
    body = _get(client)
    assert body["unattributed_reward_claims"] == {"base": {
        "by_reward_token": {AERO: {"counted_keys": 1, "net_wei": "40", "net_usd": 4.0, "unpriced": 0}},
        "by_status": dict({s: 0 for s in mle.ALL_STATUSES}, verified=1),
    }}
    totals = body["summary"]["emissions"]
    assert totals["by_reward_token"][AERO] == {"counted_keys": 3, "net_wei": "70", "net_usd": 5.0, "unpriced": 1}
    assert sum(totals["by_status"].values()) == 4


def test_route_existing_output_is_unchanged_by_the_new_keys(client, db, monkeypatch):
    _forbid_rpc(monkeypatch)
    _seed_lineage_scene(db)

    def strip(body):
        body.pop("as_of")
        body.pop("unattributed_reward_claims")
        body["summary"].pop("emissions")
        for p in body["positions"]:
            p.pop("emissions")
        return body

    before = strip(_get(client))
    _seed_reward_scene(db)
    after = strip(_get(client))
    assert before == after
    assert set(before["summary"]) == {"basis", "claims", "exit"}


def test_route_with_no_reward_rows_has_empty_emissions(client, db, monkeypatch):
    _forbid_rpc(monkeypatch)
    _seed_lineage_scene(db)
    body = _get(client)
    empty = {"by_reward_token": {}, "by_status": {s: 0 for s in mle.ALL_STATUSES}}
    assert _get_position(body, 1)["emissions"] == empty
    assert body["summary"]["emissions"] == empty
    assert body["unattributed_reward_claims"] == {"base": empty}
