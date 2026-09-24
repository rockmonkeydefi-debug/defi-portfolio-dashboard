"""Emissions C4 - the write path: maxfi_ledger_reward_claims rows (one per
key, every status, DELETE-then-INSERT on the full PK), raw reward events
into maxfi_ledger_events (INSERT OR IGNORE), carry-forward of prior priced
rows, and the gates (dry run / emissions error write nothing for
emissions). Fixtures and stubs are shared with
tests/test_maxfi_ledger_emissions_backfill.py (synthetic-but-exact fixture;
no network)."""
import ast
import inspect
import json
import textwrap

from test_maxfi_ledger_emissions_backfill import (  # noqa: F401  (client/db/autouse are fixtures)
    AERO, BACKFILL_URL, SM, VAULT, WALLET, _fx, _install, _last_run_path, _post, _wallets, client, db, mli, wp,
)

EMISSIONS_TYPES = ("StakingRewardsClaimed", "PerformanceFeeCollected", "PositionStaked", "PositionUnstaked")


def _rows(db):
    return [dict(r) for r in db.execute("SELECT * FROM maxfi_ledger_reward_claims ORDER BY block_number, tx_hash")]


def _emissions_events(db):
    placeholders = ", ".join("?" for _ in EMISSIONS_TYPES)
    return [dict(r) for r in db.execute(
        f"SELECT * FROM maxfi_ledger_events WHERE event_type IN ({placeholders}) ORDER BY tx_hash, log_index",
        EMISSIONS_TYPES)]


def test_real_run_writes_one_row_per_key_with_exact_wei_and_statuses(client, db, monkeypatch):
    fx = _fx()
    _install(monkeypatch, fx)
    body = _post(client)
    rows = _rows(db)
    assert len(rows) == 3 == body["emissions"]["rows_upserted"]
    expected_path = {"manual": ("manual", "vault"), "keeper": ("rebalance", "sm"), "withdrawal": ("withdrawal", "both")}
    for t, row in zip(fx["txs"], rows):
        assert (row["chain"], row["tx_hash"], row["token_id"], row["reward_token"]) == ("base", t["tx_hash"],
                                                                                        t["token_id"], AERO)
        assert (row["gross_wei"], row["fee_wei"], row["net_wei"]) == (t["gross_wei"], t["fee_wei"], t["net_wei"])
        assert (row["treasury_wei"], row["referral_wei"]) == (t["fee_wei"], "0")
        assert (row["claim_path"], row["gross_source"]) == expected_path[t["label"]]
        assert row["verification_status"] == "verified" and row["owner"] == WALLET
        assert (row["transfer_to"], row["transfer_wei"]) == (WALLET, t["net_wei"])
        assert row["vault"] == VAULT and row["block_number"] == t["block_number"]
        assert abs(row["net_usd"] - int(t["net_wei"]) / 1e18 * 0.5) < 1e-9 and row["price_source"] == "swap_log"
        assert row["price_block"] is not None and row["computed_at"] == body["run_at"]


def test_rerun_is_idempotent_rows_and_raw_events(client, db, monkeypatch):
    _install(monkeypatch, _fx())
    first = _post(client)["emissions"]
    rows_1, events_1 = _rows(db), _emissions_events(db)
    second = _post(client)["emissions"]
    rows_2, events_2 = _rows(db), _emissions_events(db)
    strip = lambda rs: [{k: v for k, v in r.items() if k != "computed_at"} for r in rs]
    assert strip(rows_1) == strip(rows_2) and len(rows_2) == 3
    assert events_1 == events_2 and len(events_2) == 9
    assert sum(first["events_inserted"].values()) == 9 and first["events_ignored_duplicate"] == {}
    assert second["events_inserted"] == {} and sum(second["events_ignored_duplicate"].values()) == 9


def test_raw_events_shape_emitter_and_vault_column(client, db, monkeypatch):
    _install(monkeypatch, _fx())
    body = _post(client)
    events = _emissions_events(db)
    assert body["emissions"]["events_inserted"] == {"StakingRewardsClaimed": 4, "PerformanceFeeCollected": 3,
                                                    "PositionUnstaked": 2}
    for ev in events:
        decoded = json.loads(ev["decoded_json"])
        assert ev["contract_address"] in (VAULT, SM)
        if ev["contract_address"] == VAULT:
            assert ev["vault"] == VAULT and decoded["emitter"] == "vault"
        else:
            assert ev["vault"] is None and decoded["emitter"] == "staking_manager"
        assert ev["npm"] is None and ev["pool_address"] is None and ev["created_at"] == body["run_at"]
        assert json.loads(ev["topics_json"])[0] == ev["topic0"]
    vault_claims = [json.loads(e["decoded_json"]) for e in events
                    if e["event_type"] == "StakingRewardsClaimed" and e["vault"] == VAULT]
    assert {c["owner"] for c in vault_claims} == {WALLET} and len(vault_claims) == 2


def test_dry_run_writes_nothing_but_classifies(client, db, monkeypatch):
    _install(monkeypatch, _fx())
    em = _post(client, f"{BACKFILL_URL}?dry_run=true")["emissions"]
    assert _rows(db) == [] and _emissions_events(db) == []
    assert em["writes"] == "dry_run (nothing written)" and em["rows_upserted"] == 3
    assert sum(em["events_inserted"].values()) == 9 and em["events_ignored_duplicate"] == {}


def test_dry_run_after_real_run_classifies_raw_events_as_duplicates(client, db, monkeypatch):
    _install(monkeypatch, _fx())
    _post(client)
    em = _post(client, f"{BACKFILL_URL}?dry_run=true")["emissions"]
    assert em["events_inserted"] == {} and sum(em["events_ignored_duplicate"].values()) == 9
    assert len(_rows(db)) == 3


def test_emissions_error_writes_nothing_and_keeps_prior_rows_while_positions_write(client, db, monkeypatch):
    fx = _fx()
    _install(monkeypatch, fx)
    first = _post(client)
    rows_before, events_before = _rows(db), _emissions_events(db)
    _install(monkeypatch, fx, reward_getlogs_error=mli.MaxFiRpcError("reward getLogs down"))
    second = _post(client)
    assert second["emissions"]["status"] == "error"
    assert second["emissions"]["writes"] == "skipped (emissions error; prior rows untouched)"
    assert _rows(db) == rows_before and _emissions_events(db) == events_before  # computed_at untouched too
    positions_at = {r[0] for r in db.execute("SELECT computed_at FROM maxfi_ledger_positions")}
    assert positions_at == {second["run_at"]} and second["run_at"] != first["run_at"]
    assert second["positions_upserted"] == first["positions_upserted"] == 3


def test_carry_forward_skips_repricing_and_reprice_true_reprices(client, db, monkeypatch):
    seen = _install(monkeypatch, _fx())
    _post(client)
    assert len(seen) == 3
    usd_before = [r["net_usd"] for r in _rows(db)]
    em = _post(client)["emissions"]
    assert len(seen) == 3  # nothing re-priced
    assert em["pricing"]["carried_forward"] == 3 and em["pricing"]["priced"] == 0
    assert em["pricing"]["calls_used"] == 0 and em["acceptance"]["carried_forward_keys"] == 3
    assert [r["net_usd"] for r in _rows(db)] == usd_before
    em = _post(client, f"{BACKFILL_URL}?reprice=true")["emissions"]
    assert len(seen) == 6 and em["pricing"]["priced"] == 3 and em["pricing"]["carried_forward"] == 0


def test_carry_forward_reprices_a_key_whose_net_changed(client, db, monkeypatch):
    fx = _fx()
    seen = _install(monkeypatch, fx)
    _post(client)
    db.execute("UPDATE maxfi_ledger_reward_claims SET net_wei = '1' WHERE tx_hash = ?", (fx["txs"][0]["tx_hash"],))
    db.commit()
    em = _post(client)["emissions"]
    assert em["pricing"]["carried_forward"] == 2 and em["pricing"]["priced"] == 1 and len(seen) == 4
    assert _rows(db)[0]["net_wei"] == fx["txs"][0]["net_wei"]  # rewritten from chain truth


def test_reconciliation_output_is_unchanged_by_raw_reward_events(client, db, monkeypatch):
    _install(monkeypatch, _fx())
    _post(client)
    assert len(_emissions_events(db)) == 9

    def recon():
        r = client.get("/api/maxfi/ledger-reconciliation")
        assert r.status_code == 200
        body = r.get_json()
        body.pop("as_of", None)
        return body

    with_events = recon()
    db.execute("DELETE FROM maxfi_ledger_events WHERE event_type IN (?, ?, ?, ?)", EMISSIONS_TYPES)
    db.commit()
    assert recon() == with_events


def test_no_emissions_write_sits_inside_the_reports_broad_except():
    report_src = inspect.getsource(wp._ledger_emissions_report)
    for needle in ("execute(", "INSERT", "DELETE", "commit(", "_ledger_emissions_write("):
        assert needle not in report_src, needle
    write_tree = ast.parse(textwrap.dedent(inspect.getsource(wp._ledger_emissions_write)))
    # no try/except at all: write failures propagate like positions/claims writes
    assert not any(isinstance(node, ast.Try) for node in ast.walk(write_tree))
    run_src = inspect.getsource(wp._run_ledger_backfill)
    assert run_src.index("_ledger_emissions_write(") > run_src.index("conn = get_connection()")
    assert run_src.index("_ledger_emissions_write(") < run_src.index("conn.commit()")
