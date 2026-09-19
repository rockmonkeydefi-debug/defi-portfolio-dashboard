"""Route-level tests for POST /api/maxfi/ledger/seed-case1-base-6039568
(HANDOFF_maxfi_ledger.md, MaxFi ledger Commit 2). Runs against the ACTUAL
fixture files under tests/fixtures/maxfi_ledger/ (never mocked/mutated in
place) - same discipline as Commit 1's decode tests. The one exception is
the ground-truth-mismatch test, which redirects `open()` for the harvest
fixture's path only, to a corrupted TEST-LOCAL copy - the real fixture
file on disk is never touched.

No network. web_portfolio spawns a background scheduler on non-__main__
import; threading.Thread.start is neutralized during import (established
pattern in tests/test_maxfi_valuation_route.py / test_maxfi_advisor.py).
"""
import builtins
import json
import sqlite3
import threading
import uuid

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import pytest

import maxfi_schema
import src.storage.portfolio_db as portfolio_db


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


@pytest.fixture
def seed_db(monkeypatch):
    uri = f"file:maxfi_ledger_seed_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    keepalive.row_factory = sqlite3.Row
    maxfi_schema.ensure_maxfi_tables(keepalive)

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    yield keepalive
    keepalive.close()


SEED_URL = "/api/maxfi/ledger/seed-case1-base-6039568"


# ── dry_run ───────────────────────────────────────────────────────────

def test_dry_run_decodes_exactly_three_events_and_writes_nothing(client, seed_db):
    resp = client.post(SEED_URL, query_string={"dry_run": "true"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["dry_run"] is True
    assert body["would_insert_events"] == 3
    assert len(body["decoded_events"]) == 3
    event_types = {e["event_type"] for e in body["decoded_events"]}
    assert event_types == {"PositionCreated", "FeesHarvested", "ProtocolFeesDistributed"}
    assert all(e["chain"] == "base" for e in body["decoded_events"])

    derived = body["derived_position"]
    assert derived["chain"] == "base"
    assert derived["token_id"] == "6039568"
    assert derived["vault"] == "0x7d27cdfbfcc878f7e7349e216d44204bfd2afd55"
    assert derived["claimed_gross0_wei"] == "242214271699"
    assert derived["claimed_gross1_wei"] == "583"

    # Nothing written.
    assert seed_db.execute("SELECT COUNT(*) FROM maxfi_ledger_events").fetchone()[0] == 0
    assert seed_db.execute("SELECT COUNT(*) FROM maxfi_ledger_positions").fetchone()[0] == 0


def test_dry_run_via_json_body(client, seed_db):
    resp = client.post(SEED_URL, json={"dry_run": True})
    assert resp.status_code == 200
    assert resp.get_json()["dry_run"] is True
    assert seed_db.execute("SELECT COUNT(*) FROM maxfi_ledger_events").fetchone()[0] == 0


# ── real run ──────────────────────────────────────────────────────────

def test_real_run_inserts_three_events_and_one_position(client, seed_db):
    resp = client.post(SEED_URL)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["dry_run"] is False
    assert body["inserted_events"] == 3
    assert body["skipped_events"] == 0

    events = seed_db.execute(
        "SELECT event_type, chain, token_id FROM maxfi_ledger_events"
    ).fetchall()
    assert len(events) == 3
    assert {e["event_type"] for e in events} == {
        "PositionCreated", "FeesHarvested", "ProtocolFeesDistributed",
    }
    assert all(e["chain"] == "base" for e in events)
    assert all(e["token_id"] == "6039568" for e in events)

    positions = seed_db.execute(
        "SELECT chain, vault, npm, token_id, claimed_gross0_wei, claimed_gross1_wei, computed_at "
        "FROM maxfi_ledger_positions"
    ).fetchall()
    assert len(positions) == 1
    row = positions[0]
    assert row["chain"] == "base"
    assert row["vault"] == "0x7d27cdfbfcc878f7e7349e216d44204bfd2afd55"
    assert row["npm"] is None
    assert row["token_id"] == "6039568"
    assert row["claimed_gross0_wei"] == "242214271699"
    assert row["claimed_gross1_wei"] == "583"
    assert row["computed_at"] is not None


def test_real_run_ground_truth_response_matches_doc(client, seed_db):
    resp = client.post(SEED_URL)
    body = resp.get_json()
    derived = body["derived_position"]
    # HANDOFF_maxfi_ledger.md, "Split verified to the wei": gross
    # 242,214,271,699 wei WETH / 583 uUSDC.
    assert derived["claimed_gross0_wei"] == "242214271699"
    assert derived["claimed_gross1_wei"] == "583"
    # 15% treasury / 85% wallet net, referral 0.
    assert derived["claimed_net0_wei"] == "205882130945"
    assert derived["claimed_net1_wei"] == "496"


# ── idempotency ───────────────────────────────────────────────────────

def test_real_run_twice_does_not_duplicate(client, seed_db):
    resp1 = client.post(SEED_URL)
    assert resp1.status_code == 200
    body1 = resp1.get_json()
    assert body1["inserted_events"] == 3
    assert body1["skipped_events"] == 0

    resp2 = client.post(SEED_URL)
    assert resp2.status_code == 200
    body2 = resp2.get_json()
    assert body2["inserted_events"] == 0
    assert body2["skipped_events"] == 3

    assert seed_db.execute("SELECT COUNT(*) FROM maxfi_ledger_events").fetchone()[0] == 3
    assert seed_db.execute("SELECT COUNT(*) FROM maxfi_ledger_positions").fetchone()[0] == 1


def test_real_run_twice_refreshes_computed_at(client, seed_db):
    client.post(SEED_URL)
    computed_at_1 = seed_db.execute(
        "SELECT computed_at FROM maxfi_ledger_positions"
    ).fetchone()[0]

    client.post(SEED_URL)
    computed_at_2 = seed_db.execute(
        "SELECT computed_at FROM maxfi_ledger_positions"
    ).fetchone()[0]

    # A derived cache row, not an append log - computed_at is refreshed
    # on every run (maxfi_ledger.py's derive_position_ledger docstring:
    # computed_at is left None by the pure function, filled in by the
    # write path at INSERT time).
    assert computed_at_1 is not None
    assert computed_at_2 is not None
    assert computed_at_2 >= computed_at_1


# ── ground-truth cross-check abort path ──────────────────────────────

def test_ground_truth_mismatch_aborts_without_writing(client, seed_db, monkeypatch, tmp_path):
    """Prove the abort path actually fires: redirect open() for the
    harvest fixture's path to a TEST-LOCAL corrupted copy (fees0's data
    word zeroed) and confirm the route reports GroundTruthMismatch and
    writes nothing. The real fixture file on disk is never modified.
    """
    real_open = builtins.open

    def corrupting_open(path, *args, **kwargs):
        if isinstance(path, str) and path.endswith("base_harvest_6039568.json"):
            with real_open(path) as fh:
                data = json.load(fh)
            fh_topic0 = "0x452b22f6ddf3d1109a8e3ffa961f0727935ebd4df8c6e922f5361aba654acec1"
            corrupted_any = False
            for item in data["items"]:
                if item["topics"][0].lower() == fh_topic0:
                    body = item["data"][2:]
                    item["data"] = "0x" + ("0" * 64) + body[64:]
                    corrupted_any = True
            assert corrupted_any, "test setup bug: FeesHarvested item not found in fixture"
            corrupted_path = tmp_path / "corrupted_base_harvest_6039568.json"
            corrupted_path.write_text(json.dumps(data))
            return real_open(str(corrupted_path), *args, **kwargs)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", corrupting_open)

    resp = client.post(SEED_URL)
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["error"] == "GroundTruthMismatch"
    assert "242214271699" in body["detail"]

    assert seed_db.execute("SELECT COUNT(*) FROM maxfi_ledger_events").fetchone()[0] == 0
    assert seed_db.execute("SELECT COUNT(*) FROM maxfi_ledger_positions").fetchone()[0] == 0


def test_ground_truth_mismatch_aborts_in_dry_run_too(client, seed_db, monkeypatch, tmp_path):
    real_open = builtins.open

    def corrupting_open(path, *args, **kwargs):
        if isinstance(path, str) and path.endswith("base_harvest_6039568.json"):
            with real_open(path) as fh:
                data = json.load(fh)
            fh_topic0 = "0x452b22f6ddf3d1109a8e3ffa961f0727935ebd4df8c6e922f5361aba654acec1"
            for item in data["items"]:
                if item["topics"][0].lower() == fh_topic0:
                    body = item["data"][2:]
                    item["data"] = "0x" + ("0" * 64) + body[64:]
            corrupted_path = tmp_path / "corrupted_dry_run.json"
            corrupted_path.write_text(json.dumps(data))
            return real_open(str(corrupted_path), *args, **kwargs)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", corrupting_open)

    resp = client.post(SEED_URL, query_string={"dry_run": "true"})
    assert resp.status_code == 500
    assert resp.get_json()["error"] == "GroundTruthMismatch"
