"""Route-level tests for GET /api/maxfi/ledger-reconciliation
(HANDOFF_maxfi_ledger.md, MaxFi ledger Commit 2).

Production data will never exercise "matched"/"mismatch" today (ledger
USD is always None on basis_price_usd/exit_price_usd, and
wp._maxfi_ledger_claim_usd always returns None) - so every synthetic
maxfi_ledger_positions/maxfi_ledger_events row here is constructed
directly with INSERT, bypassing maxfi_ledger.decode_log /
derive_position_ledger entirely for the rows that need to prove the
priced-comparison branches. maxfi_ledger.py and maxfi_schema.py are
never imported for decoding here - only maxfi_schema.ensure_maxfi_tables
to build the test DB. The claims-pricing seam (wp._maxfi_ledger_claim_usd)
is monkeypatched via `priced_claim_usd` below for the tests that need a
priced ledger event - decoded_json itself NEVER carries a USD key
(maxfi_ledger_events is raw/append-only; see the seam's own docstring).

No network. web_portfolio spawns a background scheduler on non-__main__
import; threading.Thread.start is neutralized during import (established
pattern).
"""
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

RECON_URL = "/api/maxfi/ledger-reconciliation"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


@pytest.fixture
def db(monkeypatch):
    uri = f"file:maxfi_ledger_recon_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
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


# ── seed helpers ──────────────────────────────────────────────────────

def _seed_position(db, position_id, chain="base", wallet="0x" + "a" * 40,
                    token_id="1", status="open", first_seen_at="2026-01-01T00:00:00+00:00",
                    first_seen_block="100", closed_at=None):
    db.execute(
        """
        INSERT INTO maxfi_positions (
            id, chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, first_seen_block,
            last_scan_at, closed_at
        ) VALUES (?, ?, ?, ?, 0, '0xpool', '0xtoken0', '0xtoken1', 3000, ?,
                  ?, 'chain', ?, ?, ?)
        """,
        (position_id, chain, wallet, token_id, status, first_seen_at,
         first_seen_block, first_seen_at, closed_at),
    )
    db.commit()


def _seed_initial_value(db, position_id, initial_value_usd, source="manual_override"):
    db.execute(
        """
        INSERT INTO maxfi_initial_value (position_id, source, initial_value_usd, set_at, set_by)
        VALUES (?, ?, ?, '2026-01-01T00:00:00+00:00', 'glenn')
        """,
        (position_id, source, initial_value_usd),
    )
    db.commit()


def _seed_claim(db, position_id, claimed_at, proceeds_usd):
    cur = db.execute(
        """
        INSERT INTO maxfi_claims (position_id, claimed_at, proceeds_usd, set_at, set_by)
        VALUES (?, ?, ?, '2026-01-01T00:00:00+00:00', 'glenn')
        """,
        (position_id, claimed_at, proceeds_usd),
    )
    db.commit()
    return cur.lastrowid


def _seed_closing_value(db, position_id, closing_value_usd):
    db.execute(
        """
        INSERT INTO maxfi_position_user_data (position_id, closing_value_usd, set_at, set_by)
        VALUES (?, ?, '2026-01-01T00:00:00+00:00', 'glenn')
        """,
        (position_id, closing_value_usd),
    )
    db.commit()


_LEDGER_POSITION_DEFAULTS = {
    "chain": "base", "vault": "0xvault", "npm": None, "token_id": "1",
    "pool_id": None, "pool_address": None, "owner": None,
    "opened_at": None, "opened_block": None,
    "rebalanced_from_token_id": None, "rebalanced_to_token_id": None,
    "rebalanced_at": None, "rebalanced_block": None,
    "closed_at": None, "closed_block": None,
    "exit_amount0_wei": None, "exit_amount1_wei": None,
    "exit_net_fee0_wei": None, "exit_net_fee1_wei": None,
    "exit_price_usd": None, "exit_price_source": None,
    "claimed_gross0_wei": "0", "claimed_gross1_wei": "0",
    "claimed_net0_wei": "0", "claimed_net1_wei": "0",
    "compounded0_wei": "0", "compounded1_wei": "0",
    "basis_liquidity_wei": None, "basis_amount0_wei": None,
    "basis_amount1_wei": None, "basis_block": None, "basis_at": None,
    "basis_price_usd": None, "basis_price_source": None,
    "source_event_ids": None, "computed_at": "2026-01-01T00:00:00+00:00",
}


def _seed_ledger_position(db, **overrides):
    row = dict(_LEDGER_POSITION_DEFAULTS)
    row.update(overrides)
    cols = list(row.keys())
    db.execute(
        f"INSERT INTO maxfi_ledger_positions ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        tuple(row[c] for c in cols),
    )
    db.commit()


def _seed_ledger_event(db, chain, token_id, event_type, block_timestamp, decoded,
                        tx_hash=None, log_index=0, vault="0xvault", npm=None,
                        pool_address=None, contract_address="0xvault", block_number=1):
    tx_hash = tx_hash or f"0xtx-{uuid.uuid4().hex}"
    db.execute(
        """
        INSERT INTO maxfi_ledger_events (
            chain, contract_address, vault, npm, token_id, pool_address,
            event_type, block_number, block_timestamp, tx_hash, log_index,
            topic0, topics_json, data_hex, decoded_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '0xtopic', '[]', '0x', ?, '2026-01-01T00:00:00+00:00')
        """,
        (chain, contract_address, vault, npm, token_id, pool_address,
         event_type, block_number, block_timestamp, tx_hash, log_index,
         json.dumps(decoded)),
    )
    db.commit()


def _get_position(body, position_id):
    return next(p for p in body["positions"] if p["position_id"] == position_id)


def priced_claim_usd(monkeypatch):
    """Monkeypatch wp._maxfi_ledger_claim_usd (the pricing seam - see its
    own docstring in web_portfolio.py) so a test can give a specific
    FeesHarvested event a USD figure WITHOUT ever writing a `claimed_usd`
    key into a decoded dict (maxfi_ledger_events is raw/append-only - a
    real pricing commit must never do that either). The fake seam reads
    an ordinary `_test_usd` key from the decoded dict instead - a value
    only this test file's own synthetic rows ever carry, never something
    real decode_log() output would produce.
    """
    monkeypatch.setattr(wp, "_maxfi_ledger_claim_usd", lambda decoded: decoded.get("_test_usd"))


def _claim_by_id(claims_result, claim_id):
    return next(c for c in claims_result["claims"] if c["claim_id"] == claim_id)


# ── basis: matched / mismatch / ledger_only / manual_only / ledger_unpriced / no_data

def test_basis_matched(client, db):
    _seed_position(db, 1, token_id="1")
    _seed_initial_value(db, 1, 100.0)
    _seed_ledger_position(db, token_id="1", opened_at="2026-01-01T00:00:00Z", basis_price_usd=100.50)

    resp = client.get(RECON_URL)
    body = resp.get_json()
    pos = _get_position(body, 1)
    assert pos["basis"]["status"] == "matched"
    assert body["summary"]["basis"]["matched"] == 1


def test_basis_mismatch(client, db):
    _seed_position(db, 1, token_id="1")
    _seed_initial_value(db, 1, 100.0)
    _seed_ledger_position(db, token_id="1", opened_at="2026-01-01T00:00:00Z", basis_price_usd=150.0)

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["basis"]["status"] == "mismatch"


def test_basis_ledger_only(client, db):
    _seed_position(db, 1, token_id="1")
    _seed_ledger_position(db, token_id="1", opened_at="2026-01-01T00:00:00Z", basis_price_usd=100.0)
    # No maxfi_initial_value row at all.

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["basis"]["status"] == "ledger_only"


def test_basis_manual_only(client, db):
    _seed_position(db, 1, token_id="1")
    _seed_initial_value(db, 1, 100.0)
    # No ledger position row at all - no ledger data of any kind.

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["basis"]["status"] == "manual_only"


def test_basis_ledger_unpriced(client, db):
    """The realistic production shape today: a ledger position exists
    (PositionCreated decoded -> opened_at set) but basis_price_usd is
    always None (maxfi_ledger.py's derive_position_ledger hardcodes it -
    see the route's own docstring citing L586/L600), even though a manual
    figure exists.
    """
    _seed_position(db, 1, token_id="1")
    _seed_initial_value(db, 1, 100.0)
    _seed_ledger_position(db, token_id="1", opened_at="2026-01-01T00:00:00Z", basis_price_usd=None)

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["basis"]["status"] == "ledger_unpriced"


def test_basis_no_data(client, db):
    _seed_position(db, 1, token_id="1")
    # No initial_value row, no ledger position row.

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["basis"]["status"] == "no_data"


def test_basis_priced_value_implies_presence(client, db):
    """Ruling Y: a priced value on its own implies presence, even when
    opened_at AND basis_liquidity_wei are both None (a shape that
    shouldn't occur from real derive_position_ledger output today, since
    basis_price_usd is always None there too - but the predicate must not
    depend on opened_at/basis_liquidity_wei alone, or a future commit
    that populates basis_price_usd without also touching those two
    columns would silently read as ledger_only/no ledger data)."""
    _seed_position(db, 1, token_id="1")
    _seed_initial_value(db, 1, 100.0)
    _seed_ledger_position(db, token_id="1", opened_at=None, basis_liquidity_wei=None, basis_price_usd=100.25)

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["basis"]["status"] == "matched"
    assert pos["basis"]["ledger_context"]["present"] is True


# ── exit: same six statuses, mirroring basis but on closed_at/exit_price_usd

def test_exit_matched(client, db):
    _seed_position(db, 1, token_id="1", status="closed", closed_at="2026-02-01T00:00:00+00:00")
    _seed_closing_value(db, 1, 200.0)
    _seed_ledger_position(db, token_id="1", closed_at="2026-02-01T00:00:00Z", exit_price_usd=200.25)

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["exit"]["status"] == "matched"


def test_exit_mismatch(client, db):
    _seed_position(db, 1, token_id="1", status="closed", closed_at="2026-02-01T00:00:00+00:00")
    _seed_closing_value(db, 1, 200.0)
    _seed_ledger_position(db, token_id="1", closed_at="2026-02-01T00:00:00Z", exit_price_usd=300.0)

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["exit"]["status"] == "mismatch"


def test_exit_ledger_only(client, db):
    _seed_position(db, 1, token_id="1", status="closed", closed_at="2026-02-01T00:00:00+00:00")
    _seed_ledger_position(db, token_id="1", closed_at="2026-02-01T00:00:00Z", exit_price_usd=200.0)

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["exit"]["status"] == "ledger_only"


def test_exit_manual_only(client, db):
    _seed_position(db, 1, token_id="1", status="closed", closed_at="2026-02-01T00:00:00+00:00")
    _seed_closing_value(db, 1, 200.0)

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["exit"]["status"] == "manual_only"


def test_exit_ledger_unpriced(client, db):
    _seed_position(db, 1, token_id="1", status="closed", closed_at="2026-02-01T00:00:00+00:00")
    _seed_closing_value(db, 1, 200.0)
    _seed_ledger_position(db, token_id="1", closed_at="2026-02-01T00:00:00Z", exit_price_usd=None)

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["exit"]["status"] == "ledger_unpriced"


def test_exit_no_data(client, db):
    _seed_position(db, 1, token_id="1", status="open")

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["exit"]["status"] == "no_data"


def test_exit_priced_value_implies_presence(client, db):
    """Ruling Y, exit side - mirrors test_basis_priced_value_implies_presence."""
    _seed_position(db, 1, token_id="1", status="closed", closed_at="2026-02-01T00:00:00+00:00")
    _seed_closing_value(db, 1, 200.0)
    _seed_ledger_position(db, token_id="1", closed_at=None, exit_amount0_wei=None, exit_price_usd=200.10)

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["exit"]["status"] == "matched"
    assert pos["exit"]["ledger_context"]["present"] is True


# ── claims: greedy 1:1 nearest-timestamp pairing, calendar-day window,
# ruling 13 (corrected after chat review - see HANDOFF_maxfi_ledger.md's
# Commit 2 landing note) ─────────────────────────────────────────────

def test_claims_ledger_unpriced_on_real_shape(client, db):
    """The realistic production shape: a ledger FeesHarvested event
    exists for this token_id, but wp._maxfi_ledger_claim_usd (the seam)
    always returns None today - so this pairs, but is ledger_unpriced,
    even though a manual claim on the same day exists.
    """
    _seed_position(db, 1, token_id="1")
    _seed_claim(db, 1, "2026-03-01", 50.0)
    _seed_ledger_event(db, "base", "1", "FeesHarvested", "2026-03-01T00:00:00Z",
                        {"token_id": 1, "fees0": 1000, "fees1": 2000})

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["claims"]["status"] == "ledger_unpriced"
    claim = pos["claims"]["claims"][0]
    assert claim["status"] == "ledger_unpriced"
    assert claim["ledger_usd"] is None


def test_claims_timestamps_are_iso_not_http_date(client, db):
    """Chat review caught this against the live pulled tree: an aware
    datetime handed straight to jsonify serializes as an RFC-822 HTTP
    date ("Sun, 01 Mar 2026 00:00:00 GMT"), not ISO 8601, while every
    other timestamp in this payload (as_of, first_seen_at,
    ledger_opened_at) is ISO. claimed_at, ledger_block_timestamp, and
    unpaired_ledger_events[].block_timestamp must all be ISO strings.
    """
    _seed_position(db, 1, token_id="1")
    _seed_claim(db, 1, "2026-03-01", 50.0)
    _seed_ledger_event(db, "base", "1", "FeesHarvested", "2026-03-02T23:00:00Z",
                        {"token_id": 1, "fees0": 1, "fees1": 1})

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    claim = pos["claims"]["claims"][0]
    assert claim["claimed_at"] == "2026-03-01T00:00:00+00:00"
    assert claim["ledger_block_timestamp"] == "2026-03-02T23:00:00+00:00"


def test_claims_matched_with_synthetic_priced_event(client, db, monkeypatch):
    """Proves the matched/mismatch branch works, via the
    wp._maxfi_ledger_claim_usd seam (monkeypatched here) - decoded_json
    itself never carries a claimed_usd key (see priced_claim_usd's own
    docstring). A future pricing commit would populate the seam for real.
    """
    priced_claim_usd(monkeypatch)
    _seed_position(db, 1, token_id="1")
    _seed_claim(db, 1, "2026-03-01T12:00:00+00:00", 50.0)
    _seed_ledger_event(db, "base", "1", "FeesHarvested", "2026-03-01T18:00:00Z",
                        {"token_id": 1, "fees0": 1000, "fees1": 2000, "_test_usd": 50.25})

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["claims"]["status"] == "matched"
    claim = pos["claims"]["claims"][0]
    assert claim["status"] == "matched"
    assert claim["ledger_usd"] == 50.25


def test_claims_mismatch_with_synthetic_priced_event(client, db, monkeypatch):
    priced_claim_usd(monkeypatch)
    _seed_position(db, 1, token_id="1")
    _seed_claim(db, 1, "2026-03-01T12:00:00+00:00", 50.0)
    _seed_ledger_event(db, "base", "1", "FeesHarvested", "2026-03-01T18:00:00Z",
                        {"token_id": 1, "fees0": 1000, "fees1": 2000, "_test_usd": 90.0})

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["claims"]["status"] == "mismatch"
    claim = pos["claims"]["claims"][0]
    assert claim["status"] == "mismatch"
    assert claim["ledger_usd"] == 90.0


def test_claims_unpaired_both_sides_reports_unmatched_not_no_data(client, db, monkeypatch):
    """The window is enforced: a priced ledger event 9 days away from the
    manual claim must NOT pair (rewritten from the old
    test_claims_priced_event_outside_one_day_window_does_not_match, which
    wrongly expected no_data here - both sides are non-empty, they are
    just never connected, so the position status must be `unmatched`,
    with one unmatched claim and one unpaired ledger event, not no_data.
    """
    priced_claim_usd(monkeypatch)
    _seed_position(db, 1, token_id="1")
    claim_id = _seed_claim(db, 1, "2026-03-01T12:00:00+00:00", 50.0)
    _seed_ledger_event(db, "base", "1", "FeesHarvested", "2026-03-10T12:00:00Z",
                        {"token_id": 1, "fees0": 1000, "fees1": 2000, "_test_usd": 50.0})

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["claims"]["status"] == "unmatched"
    assert len(pos["claims"]["claims"]) == 1
    claim = _claim_by_id(pos["claims"], claim_id)
    assert claim["status"] == "unmatched"
    assert len(pos["claims"]["unpaired_ledger_events"]) == 1


def test_claims_manual_only(client, db):
    _seed_position(db, 1, token_id="1")
    _seed_claim(db, 1, "2026-03-01", 50.0)
    # No ledger events at all for this token_id.

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["claims"]["status"] == "manual_only"
    assert pos["claims"]["claims"][0]["status"] == "unmatched"


def test_claims_ledger_only(client, db, monkeypatch):
    priced_claim_usd(monkeypatch)
    _seed_position(db, 1, token_id="1")
    _seed_ledger_event(db, "base", "1", "FeesHarvested", "2026-03-01T00:00:00Z",
                        {"token_id": 1, "fees0": 1000, "fees1": 2000, "_test_usd": 50.0})
    # No manual claims at all.

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["claims"]["status"] == "ledger_only"
    assert len(pos["claims"]["unpaired_ledger_events"]) == 1


def test_claims_no_data(client, db):
    _seed_position(db, 1, token_id="1")

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["claims"]["status"] == "no_data"


def test_claims_never_compares_against_aggregated_wei_total(client, db):
    """claimed_net0_wei/claimed_net1_wei must appear ONLY as informational
    ledger_context, never influence the status - a huge aggregated wei
    total alongside an unrelated manual claim must still resolve to
    whatever the per-claim date logic says (ledger_unpriced here, since
    the one real FeesHarvested event is unpriced via the seam), not get
    treated as some kind of aggregate match.
    """
    _seed_position(db, 1, token_id="1")
    _seed_claim(db, 1, "2026-03-01", 50.0)
    _seed_ledger_event(db, "base", "1", "FeesHarvested", "2026-03-01T00:00:00Z",
                        {"token_id": 1, "fees0": 1000, "fees1": 2000})
    _seed_ledger_position(db, token_id="1", claimed_net0_wei="999999999999999999", claimed_net1_wei="1")

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["claims"]["status"] == "ledger_unpriced"
    assert pos["claims"]["ledger_context"]["claimed_net0_wei"] == "999999999999999999"


def test_claims_bare_date_manual_vs_next_day_late_ledger_pairs(client, db, monkeypatch):
    """The case the old 24h/86400s window failed: production claimed_at
    is a bare DATE (parsed to midnight UTC), and a harvest at 23:00Z the
    NEXT calendar day is 47 hours away - outside 86400s, but within the
    corrected calendar-day (adjacent-date) window, so it must still pair.
    """
    priced_claim_usd(monkeypatch)
    _seed_position(db, 1, token_id="1")
    claim_id = _seed_claim(db, 1, "2026-03-01", 50.0)
    _seed_ledger_event(db, "base", "1", "FeesHarvested", "2026-03-02T23:00:00Z",
                        {"token_id": 1, "fees0": 1, "fees1": 1, "_test_usd": 50.0})

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["claims"]["status"] == "matched"
    assert _claim_by_id(pos["claims"], claim_id)["status"] == "matched"


def test_claims_two_days_apart_does_not_pair(client, db, monkeypatch):
    priced_claim_usd(monkeypatch)
    _seed_position(db, 1, token_id="1")
    claim_id = _seed_claim(db, 1, "2026-03-01", 50.0)
    _seed_ledger_event(db, "base", "1", "FeesHarvested", "2026-03-03T00:00:00Z",
                        {"token_id": 1, "fees0": 1, "fees1": 1, "_test_usd": 50.0})

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["claims"]["status"] == "unmatched"
    assert _claim_by_id(pos["claims"], claim_id)["status"] == "unmatched"


def test_claims_one_matched_one_unmatched_manual_reports_unmatched(client, db, monkeypatch):
    """Two manual claims, only one has a temporally-aligned priced ledger
    event - the position status must be `unmatched` (something on this
    side is unresolved), never silently `matched` just because one claim
    happened to line up.
    """
    priced_claim_usd(monkeypatch)
    _seed_position(db, 1, token_id="1")
    matched_id = _seed_claim(db, 1, "2026-03-01T00:00:00+00:00", 50.0)
    unmatched_id = _seed_claim(db, 1, "2026-03-20T00:00:00+00:00", 30.0)
    _seed_ledger_event(db, "base", "1", "FeesHarvested", "2026-03-01T06:00:00Z",
                        {"token_id": 1, "fees0": 1, "fees1": 1, "_test_usd": 50.0})

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["claims"]["status"] == "unmatched"
    assert _claim_by_id(pos["claims"], matched_id)["status"] == "matched"
    assert _claim_by_id(pos["claims"], unmatched_id)["status"] == "unmatched"


def test_claims_pairing_is_one_to_one_nearest_first(client, db, monkeypatch):
    """One manual claim, two in-window priced ledger events - greedy
    nearest-first pairing must bind the claim to the CLOSER event only,
    leaving the other as an unpaired ledger event (position status
    `unmatched`, a leftover ledger event), never `mismatch` from being
    compared against the wrong (farther) event.
    """
    priced_claim_usd(monkeypatch)
    _seed_position(db, 1, token_id="1")
    claim_id = _seed_claim(db, 1, "2026-03-01T12:00:00+00:00", 50.0)
    _seed_ledger_event(db, "base", "1", "FeesHarvested", "2026-03-01T13:00:00Z",
                        {"token_id": 1, "fees0": 1, "fees1": 1, "_test_usd": 50.10},
                        tx_hash="0xnear")
    _seed_ledger_event(db, "base", "1", "FeesHarvested", "2026-03-02T09:00:00Z",
                        {"token_id": 1, "fees0": 1, "fees1": 1, "_test_usd": 200.0},
                        tx_hash="0xfar")

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    claim = _claim_by_id(pos["claims"], claim_id)
    assert claim["status"] == "matched"
    assert claim["ledger_usd"] == 50.10
    assert len(pos["claims"]["unpaired_ledger_events"]) == 1
    assert pos["claims"]["unpaired_ledger_events"][0]["ledger_usd"] == 200.0
    assert pos["claims"]["status"] == "unmatched"


def test_claims_ledger_unpriced_outranks_unmatched(client, db):
    """One manual claim pairs with one unpriced ledger event; a second
    unpriced ledger event falls outside the window and stays unpaired.
    Position status must be ledger_unpriced (the one pair that formed is
    unpriced), not unmatched, even though an unpaired event also exists -
    ledger_unpriced takes precedence (docstring's stated precedence).
    """
    _seed_position(db, 1, token_id="1")
    _seed_claim(db, 1, "2026-03-01T12:00:00+00:00", 50.0)
    _seed_ledger_event(db, "base", "1", "FeesHarvested", "2026-03-01T13:00:00Z",
                        {"token_id": 1, "fees0": 1, "fees1": 1}, tx_hash="0xinwindow")
    _seed_ledger_event(db, "base", "1", "FeesHarvested", "2026-04-01T13:00:00Z",
                        {"token_id": 1, "fees0": 1, "fees1": 1}, tx_hash="0xoutofwindow")

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["claims"]["status"] == "ledger_unpriced"
    assert len(pos["claims"]["unpaired_ledger_events"]) == 1


def test_summary_claims_has_unmatched_key(client, db, monkeypatch):
    priced_claim_usd(monkeypatch)
    _seed_position(db, 1, token_id="1")
    _seed_claim(db, 1, "2026-03-01T12:00:00+00:00", 50.0)
    _seed_ledger_event(db, "base", "1", "FeesHarvested", "2026-03-10T12:00:00Z",
                        {"token_id": 1, "fees0": 1, "fees1": 1, "_test_usd": 50.0})

    resp = client.get(RECON_URL)
    body = resp.get_json()
    assert "unmatched" in body["summary"]["claims"]
    assert body["summary"]["claims"]["unmatched"] == 1


# ── ruling 14: first_seen vs ledger opened is informational only ───────

def test_first_seen_vs_ledger_opened_never_affects_status(client, db):
    _seed_position(db, 1, token_id="1", first_seen_at="2026-05-01T00:00:00+00:00", first_seen_block="999999")
    _seed_initial_value(db, 1, 100.0)
    _seed_ledger_position(db, token_id="1", opened_at="2026-01-01T00:00:00Z", opened_block=1,
                           basis_price_usd=100.0)

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    # Wildly different first_seen vs ledger opened - still matched, no
    # error/mismatch status surfaces from this disagreement (ruling 14).
    assert pos["basis"]["status"] == "matched"
    fs = pos["first_seen_vs_ledger_opened"]
    assert fs["first_seen_at"] == "2026-05-01T00:00:00+00:00"
    assert fs["ledger_opened_at"] == "2026-01-01T00:00:00Z"
    assert "informational" in fs["note"]


# ── join-key limitation: rebalanced position's old ledger segment is invisible

def test_rebalanced_position_old_ledger_segment_is_invisible_not_a_false_match(client, db, monkeypatch):
    """maxfi_positions updates token_id IN PLACE on a rebalance; the
    ledger produces a SEPARATE row per token_id. Simulate: the position
    now sits at token_id "200" (post-rebalance, current), but the only
    ledger data seeded is for token_id "100" (the old, pre-rebalance
    segment) - the (chain, token_id) join must NOT find it, so this
    position reports as if it had no ledger data at all (manual_only /
    no_data), never a false match against the wrong segment's numbers.
    """
    priced_claim_usd(monkeypatch)
    _seed_position(db, 1, token_id="200")
    _seed_initial_value(db, 1, 100.0)
    # Ledger data exists only for the OLD token_id "100", not "200".
    _seed_ledger_position(db, token_id="100", opened_at="2026-01-01T00:00:00Z", basis_price_usd=999.0)
    _seed_ledger_event(db, "base", "100", "FeesHarvested", "2026-01-05T00:00:00Z",
                        {"token_id": 100, "fees0": 1, "fees1": 1, "_test_usd": 999.0})

    resp = client.get(RECON_URL)
    pos = _get_position(resp.get_json(), 1)
    assert pos["basis"]["status"] == "manual_only"
    assert pos["basis"]["ledger_context"]["present"] is False
    assert pos["basis"]["ledger_context"]["basis_price_usd"] is None
    assert pos["claims"]["status"] == "no_data"


# ── summary counts and tolerance echo ──────────────────────────────────

def test_summary_counts_and_tolerance(client, db):
    _seed_position(db, 1, token_id="1")
    _seed_initial_value(db, 1, 100.0)
    _seed_position(db, 2, token_id="2")

    resp = client.get(RECON_URL)
    body = resp.get_json()
    assert body["tolerance_usd"] == wp.MAXFI_LEDGER_RECONCILE_USD_TOLERANCE_USD
    assert body["summary"]["basis"]["manual_only"] == 1
    assert body["summary"]["basis"]["no_data"] == 1
    assert len(body["positions"]) == 2


def test_includes_closed_positions_not_just_open(client, db):
    _seed_position(db, 1, token_id="1", status="open")
    _seed_position(db, 2, token_id="2", status="closed", closed_at="2026-02-01T00:00:00+00:00")

    resp = client.get(RECON_URL)
    body = resp.get_json()
    ids = {p["position_id"] for p in body["positions"]}
    assert ids == {1, 2}
