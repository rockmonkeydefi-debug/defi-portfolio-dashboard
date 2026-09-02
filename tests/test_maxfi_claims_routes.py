"""Route-level tests for MaxFi claims (Phase D.3.3): POST/GET
/api/maxfi/positions/<id>/claims, DELETE /api/maxfi/claims/<id>, and the
claimed_usd figure surfaced on /api/maxfi/positions/<chain>/<wallet>.

Uses the iv_db shared-cache sqlite pattern from
tests/test_maxfi_valuation_route.py:308 (not a bare ":memory:") because
every route under test opens and closes its OWN connection per call - a
fresh anonymous ":memory:" would lose all state the instant the route's
own conn.close() ran, breaking any test that hits a route more than once.
"""
import sqlite3
import uuid

import pytest

import maxfi_schema
import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

WALLET = "0x" + "c" * 40


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


@pytest.fixture
def claims_db(monkeypatch):
    uri = f"file:maxfi_claims_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
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


def _seed_position(db, position_id, status="open", token_id=None, array_index=0,
                    chain="base", wallet=WALLET, pool_address="0xPOOL"):
    db.execute(
        """
        INSERT INTO maxfi_positions (
            id, chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, first_seen_block,
            last_scan_at, closed_at
        ) VALUES (?, ?, ?, ?, ?, ?, '0xT0', '0xT1', 3000, ?,
                  '2026-01-01T00:00:00+00:00', 'chain', '1',
                  '2026-01-01T00:00:00+00:00', ?)
        """,
        (position_id, chain, wallet, token_id or str(position_id), array_index,
         pool_address, status, '2026-06-01T00:00:00+00:00' if status == 'closed' else None),
    )
    db.commit()


def _seed_claim(db, position_id, claimed_at, proceeds_usd):
    db.execute(
        """
        INSERT INTO maxfi_claims
            (position_id, claimed_at, proceeds_usd, set_at, set_by)
        VALUES (?, ?, ?, '2026-01-01T00:00:00+00:00', 'system')
        """,
        (position_id, claimed_at, proceeds_usd),
    )
    db.commit()


def _seed_lineage(db, departing_id, arriving_id, split_group_id, arriving_current_value_usd,
                   created_at="2026-06-01T00:00:00+00:00"):
    db.execute(
        """
        INSERT INTO maxfi_position_lineage
            (departing_position_id, arriving_position_id, split_group_id,
             arriving_current_value_usd, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (departing_id, arriving_id, split_group_id, arriving_current_value_usd, created_at),
    )
    db.commit()


# ── POST happy path ──────────────────────────────────────────────────────

def test_post_happy_path_returns_row_with_id_and_persists(client, claims_db):
    _seed_position(claims_db, 1)

    r = client.post(
        "/api/maxfi/positions/1/claims",
        json={
            "claimed_at": "2026-06-15T00:00:00+00:00",
            "token0_symbol": "WETH", "token0_amount": 0.5,
            "token1_symbol": "USDC", "token1_amount": 100.0,
            "sold_at": "2026-06-16T00:00:00+00:00",
            "proceeds_usd": 250.0,
            "note": "first claim",
        },
    )
    assert r.status_code == 200
    body = r.get_json()
    assert isinstance(body["id"], int)
    assert body["position_id"] == 1
    assert body["proceeds_usd"] == 250.0
    assert body["note"] == "first claim"

    row = claims_db.execute(
        "SELECT * FROM maxfi_claims WHERE id = ?", (body["id"],)
    ).fetchone()
    assert row is not None
    assert row["position_id"] == 1
    assert row["proceeds_usd"] == 250.0


def test_two_identical_posts_persist_as_separate_rows(client, claims_db):
    _seed_position(claims_db, 1)
    payload = {"claimed_at": "2026-06-15T00:00:00+00:00", "proceeds_usd": 10.0}

    r1 = client.post("/api/maxfi/positions/1/claims", json=payload)
    r2 = client.post("/api/maxfi/positions/1/claims", json=payload)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.get_json()["id"] != r2.get_json()["id"]

    count = claims_db.execute(
        "SELECT COUNT(*) FROM maxfi_claims WHERE position_id = 1"
    ).fetchone()[0]
    assert count == 2


# ── proceeds_usd validation ───────────────────────────────────────────────

def test_proceeds_usd_zero_succeeds(client, claims_db):
    _seed_position(claims_db, 1)
    r = client.post(
        "/api/maxfi/positions/1/claims",
        json={"claimed_at": "2026-06-15T00:00:00+00:00", "proceeds_usd": 0},
    )
    assert r.status_code == 200
    assert r.get_json()["proceeds_usd"] == 0


def test_proceeds_usd_negative_rejected(client, claims_db):
    _seed_position(claims_db, 1)
    r = client.post(
        "/api/maxfi/positions/1/claims",
        json={"claimed_at": "2026-06-15T00:00:00+00:00", "proceeds_usd": -0.01},
    )
    assert r.status_code == 400
    body = r.get_json()
    assert body["error"] == "InvalidProceeds"


def test_proceeds_usd_bool_rejected_not_coerced(client, claims_db):
    _seed_position(claims_db, 1)
    r = client.post(
        "/api/maxfi/positions/1/claims",
        json={"claimed_at": "2026-06-15T00:00:00+00:00", "proceeds_usd": True},
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidProceeds"


# ── closed position and missing position ────────────────────────────────

def test_post_against_closed_position_succeeds(client, claims_db):
    _seed_position(claims_db, 1, status="closed")
    r = client.post(
        "/api/maxfi/positions/1/claims",
        json={"claimed_at": "2026-06-15T00:00:00+00:00", "proceeds_usd": 5.0},
    )
    assert r.status_code == 200


def test_post_against_nonexistent_position_returns_position_not_found(client, claims_db):
    r = client.post(
        "/api/maxfi/positions/999/claims",
        json={"claimed_at": "2026-06-15T00:00:00+00:00"},
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "PositionNotFound"


# ── note length boundary ────────────────────────────────────────────────

def test_note_at_2000_chars_accepted_2001_rejected(client, claims_db):
    _seed_position(claims_db, 1)
    r_ok = client.post(
        "/api/maxfi/positions/1/claims",
        json={"claimed_at": "2026-06-15T00:00:00+00:00", "note": "x" * 2000},
    )
    assert r_ok.status_code == 200

    r_bad = client.post(
        "/api/maxfi/positions/1/claims",
        json={"claimed_at": "2026-06-15T00:00:00+00:00", "note": "x" * 2001},
    )
    assert r_bad.status_code == 400
    assert r_bad.get_json()["error"] == "InvalidClaimNote"


# ── GET own claims only, correctly ordered ─────────────────────────────

def test_get_returns_own_claims_only_correctly_ordered(client, claims_db):
    _seed_position(claims_db, 1)
    _seed_position(claims_db, 2, token_id="2")
    _seed_claim(claims_db, 1, "2026-01-01T00:00:00+00:00", 10.0)
    _seed_claim(claims_db, 1, "2026-03-01T00:00:00+00:00", 20.0)
    _seed_claim(claims_db, 2, "2026-06-01T00:00:00+00:00", 999.0)  # different position

    r = client.get("/api/maxfi/positions/1/claims")
    assert r.status_code == 200
    rows = r.get_json()
    assert len(rows) == 2
    assert [row["proceeds_usd"] for row in rows] == [20.0, 10.0]  # claimed_at DESC
    assert all(row["position_id"] == 1 for row in rows)


def test_get_claims_for_nonexistent_position_returns_position_not_found(client, claims_db):
    r = client.get("/api/maxfi/positions/999/claims")
    assert r.status_code == 400
    assert r.get_json()["error"] == "PositionNotFound"


def test_get_claims_empty_for_position_with_none(client, claims_db):
    _seed_position(claims_db, 1)
    r = client.get("/api/maxfi/positions/1/claims")
    assert r.status_code == 200
    assert r.get_json() == []


# ── DELETE ───────────────────────────────────────────────────────────────

def test_delete_removes_row_second_delete_not_found(client, claims_db):
    _seed_position(claims_db, 1)
    _seed_claim(claims_db, 1, "2026-01-01T00:00:00+00:00", 10.0)
    claim_id = claims_db.execute("SELECT id FROM maxfi_claims").fetchone()[0]

    r1 = client.delete(f"/api/maxfi/claims/{claim_id}")
    assert r1.status_code == 200

    remaining = claims_db.execute(
        "SELECT COUNT(*) FROM maxfi_claims WHERE id = ?", (claim_id,)
    ).fetchone()[0]
    assert remaining == 0

    r2 = client.delete(f"/api/maxfi/claims/{claim_id}")
    assert r2.status_code == 400
    assert r2.get_json()["error"] == "ClaimNotFound"


# ── Positions route: claimed_usd surfaced, strategy_label gone ─────────

def test_positions_route_exposes_claimed_usd_and_drops_strategy_label(client, claims_db):
    _seed_position(claims_db, 1)
    _seed_position(claims_db, 2, token_id="2")
    _seed_claim(claims_db, 1, "2026-01-01T00:00:00+00:00", 42.0)

    r = client.get(f"/api/maxfi/positions/base/{WALLET}")
    assert r.status_code == 200
    rows = {row["id"]: row for row in r.get_json()}

    assert rows[1]["claimed_usd"] == 42.0
    assert rows[2]["claimed_usd"] == 0.0
    assert "strategy_label" not in rows[1]
    assert "strategy_label" not in rows[2]


def test_positions_route_end_to_end_allocation_through_lineage(client, claims_db):
    # Ancestor position 10 has $100 of realized claims. It auto-split into
    # arriving positions 11 (value 300) and 12 (value 700) under one real
    # lineage group - a normal 2x2 cross product with position 20 as the
    # second (claim-less) departing row, matching how
    # resolve_ambiguous_auto_splits actually writes lineage.
    _seed_position(claims_db, 10, status="closed", token_id="10")
    _seed_position(claims_db, 20, status="closed", token_id="20")
    _seed_position(claims_db, 11, token_id="11")
    _seed_position(claims_db, 12, token_id="12")
    _seed_claim(claims_db, 10, "2026-01-01T00:00:00+00:00", 100.0)

    split_group_id = "2026-06-01T00:00:00+00:00|0xPOOL"
    _seed_lineage(claims_db, 10, 11, split_group_id, 300.0)
    _seed_lineage(claims_db, 10, 12, split_group_id, 700.0)
    _seed_lineage(claims_db, 20, 11, split_group_id, 300.0)
    _seed_lineage(claims_db, 20, 12, split_group_id, 700.0)

    r = client.get(f"/api/maxfi/positions/base/{WALLET}")
    rows = {row["id"]: row for row in r.get_json()}

    assert rows[11]["claimed_usd"] == pytest.approx(30.0)
    assert rows[12]["claimed_usd"] == pytest.approx(70.0)
    assert rows[11]["claimed_usd"] + rows[12]["claimed_usd"] == pytest.approx(100.0)
