"""POST /api/maxfi/pool-classify - Phase E v2 catalogue-classification
session (design step A only). Route-level tests over maxfi_catalogue_pools
+ maxfi_pool_meta, seeded directly (same shared-cache sqlite / monkeypatched
get_connection pattern as tests/test_maxfi_valuation_route.py's iv_db and
tests/test_metrics_auto_refresh.py's metrics_db - the route opens and
closes its OWN connection per call, so a bare ":memory:" would lose state
the instant that connection closed).

No network, no on-chain calls - this route is DB-only by design.
"""
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
def pc_db(monkeypatch):
    uri = f"file:pool_classify_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
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


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _seed_pool(db, chain, pool_address, token0_symbol, token1_symbol):
    db.execute(
        """
        INSERT INTO maxfi_catalogue_pools (
            chain, pool_address, token0_address, token1_address,
            token0_symbol, token1_symbol, fee_tier, position_count,
            first_seen_at, last_seen_at, last_enumerated_at
        ) VALUES (?, ?, '0xT0', '0xT1', ?, ?, 3000, 1,
                  '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00',
                  '2026-01-01T00:00:00+00:00')
        """,
        (chain, pool_address, token0_symbol, token1_symbol),
    )
    db.commit()


def _seed_meta(db, chain, pool_address, asset_class, set_by, set_at='2025-01-01T00:00:00+00:00'):
    db.execute(
        """
        INSERT INTO maxfi_pool_meta (chain, pool_address, asset_class, set_at, set_by)
        VALUES (?, ?, ?, ?, ?)
        """,
        (chain, pool_address.lower(), asset_class, set_at, set_by),
    )
    db.commit()


def _run(client, dry_run=None, as_body=False):
    if dry_run and as_body:
        return client.post("/api/maxfi/pool-classify", json={"dry_run": True})
    if dry_run:
        return client.post("/api/maxfi/pool-classify?dry_run=true")
    return client.post("/api/maxfi/pool-classify")


def _meta_row(db, chain, pool_address):
    return db.execute(
        "SELECT asset_class, set_by, set_at FROM maxfi_pool_meta WHERE chain = ? AND pool_address = ?",
        (chain, pool_address.lower()),
    ).fetchone()


# ── (a) registry match, either side ─────────────────────────────────────

def test_registry_match_on_token0_side_classifies_stock(client, pc_db):
    _seed_pool(pc_db, "robinhood", "0x" + "1" * 40, "AAPL", "USDG")

    r = _run(client)

    assert r.status_code == 200
    body = r.get_json()
    assert body["chains"]["robinhood"]["would_insert"] == 1
    assert body["chains"]["robinhood"]["writes"][0]["asset_class"] == "stock"
    row = _meta_row(pc_db, "robinhood", "0x" + "1" * 40)
    assert row["asset_class"] == "stock"
    assert row["set_by"] == "heuristic"


def test_registry_match_on_token1_side_classifies_stock(client, pc_db):
    _seed_pool(pc_db, "robinhood", "0x" + "2" * 40, "USDG", "TSLA")

    r = _run(client)

    assert r.status_code == 200
    row = _meta_row(pc_db, "robinhood", "0x" + "2" * 40)
    assert row["asset_class"] == "stock"


# ── (b) unlisted symbols -> crypto, including a stock-adjacent meme ─────

def test_unlisted_symbols_both_sides_classify_crypto(client, pc_db):
    _seed_pool(pc_db, "robinhood", "0x" + "3" * 40, "WETH", "USDG")

    r = _run(client)

    row = _meta_row(pc_db, "robinhood", "0x" + "3" * 40)
    assert row["asset_class"] == "crypto"


def test_stock_adjacent_meme_not_in_registry_classifies_crypto(client, pc_db):
    """STONKBROKER references a stock ticker in name only - it must never
    be in MAXFI_STOCK_TICKER_REGISTRY, so this pool falls to crypto."""
    _seed_pool(pc_db, "robinhood", "0x" + "4" * 40, "STONKBROKER", "USDG")

    r = _run(client)

    row = _meta_row(pc_db, "robinhood", "0x" + "4" * 40)
    assert row["asset_class"] == "crypto"


# ── (c) base chain has an empty registry -> always crypto ──────────────

def test_base_chain_pool_always_classifies_crypto_empty_registry(client, pc_db):
    _seed_pool(pc_db, "base", "0x" + "5" * 40, "AAPL", "TSLA")

    r = _run(client)

    row = _meta_row(pc_db, "base", "0x" + "5" * 40)
    assert row["asset_class"] == "crypto"
    assert r.get_json()["chains"]["base"]["would_insert"] == 1


# ── (d) NULL symbol -> no write, skipped_null_symbol ────────────────────

def test_null_token_symbol_writes_nothing_and_is_counted(client, pc_db):
    _seed_pool(pc_db, "robinhood", "0x" + "6" * 40, None, "USDG")

    r = _run(client)

    assert r.status_code == 200
    assert r.get_json()["chains"]["robinhood"]["skipped_null_symbol"] == 1
    assert _meta_row(pc_db, "robinhood", "0x" + "6" * 40) is None


def test_empty_string_token_symbol_also_counts_as_null(client, pc_db):
    _seed_pool(pc_db, "robinhood", "0x" + "7" * 40, "", "USDG")

    r = _run(client)

    assert r.get_json()["chains"]["robinhood"]["skipped_null_symbol"] == 1
    assert _meta_row(pc_db, "robinhood", "0x" + "7" * 40) is None


# ── (e) manual row always wins, never overwritten ───────────────────────

def test_manual_glenn_row_is_untouched_even_when_registry_disagrees(client, pc_db):
    addr = "0x" + "8" * 40
    _seed_pool(pc_db, "robinhood", addr, "AAPL", "USDG")
    _seed_meta(pc_db, "robinhood", addr, "crypto", "glenn", set_at="2025-06-01T00:00:00+00:00")

    r = _run(client)

    assert r.status_code == 200
    assert r.get_json()["chains"]["robinhood"]["skipped_manual"] == 1
    row = _meta_row(pc_db, "robinhood", addr)
    assert row["asset_class"] == "crypto"
    assert row["set_by"] == "glenn"
    assert row["set_at"] == "2025-06-01T00:00:00+00:00"


# ── (f) heuristic row updates on re-run when classification flips ──────

def test_heuristic_row_is_updated_on_reclassification(client, pc_db, monkeypatch):
    addr = "0x" + "9" * 40
    _seed_pool(pc_db, "robinhood", addr, "NEWTICKER", "USDG")
    _seed_meta(pc_db, "robinhood", addr, "crypto", "heuristic")

    monkeypatch.setattr(wp, "MAXFI_STOCK_TICKER_REGISTRY", {
        "base": frozenset(), "robinhood": frozenset({"NEWTICKER"}),
    })

    r = _run(client)

    assert r.status_code == 200
    body = r.get_json()
    assert body["chains"]["robinhood"]["would_update_heuristic"] == 1
    row = _meta_row(pc_db, "robinhood", addr)
    assert row["asset_class"] == "stock"
    assert row["set_by"] == "heuristic"


# ── (g) dry_run: query param and body form both no-op ───────────────────

@pytest.mark.parametrize("as_body", [False, True])
def test_dry_run_writes_zero_rows_but_reports_identical_counts(client, pc_db, as_body):
    _seed_pool(pc_db, "robinhood", "0x" + "a" * 40, "AAPL", "USDG")
    _seed_pool(pc_db, "robinhood", "0x" + "b" * 40, "WETH", "USDG")

    r_dry = _run(client, dry_run=True, as_body=as_body)
    assert r_dry.status_code == 200
    dry_body = r_dry.get_json()
    assert dry_body["dry_run"] is True
    assert _meta_row(pc_db, "robinhood", "0x" + "a" * 40) is None
    assert _meta_row(pc_db, "robinhood", "0x" + "b" * 40) is None

    r_real = _run(client)
    real_body = r_real.get_json()
    assert real_body["dry_run"] is False

    dry_chain = dry_body["chains"]["robinhood"]
    real_chain = real_body["chains"]["robinhood"]
    assert dry_chain["would_insert"] == real_chain["would_insert"]
    assert dry_chain["would_update_heuristic"] == real_chain["would_update_heuristic"]
    assert dry_chain["skipped_manual"] == real_chain["skipped_manual"]
    assert dry_chain["skipped_null_symbol"] == real_chain["skipped_null_symbol"]
    assert sorted(dry_chain["writes"], key=lambda w: w["pool_address"]) == \
        sorted(real_chain["writes"], key=lambda w: w["pool_address"])


# ── (h) case sensitivity ─────────────────────────────────────────────────

def test_lowercase_symbol_does_not_match_registry(client, pc_db):
    _seed_pool(pc_db, "robinhood", "0x" + "c" * 40, "aapl", "USDG")

    r = _run(client)

    row = _meta_row(pc_db, "robinhood", "0x" + "c" * 40)
    assert row["asset_class"] == "crypto"


# ── (i) exactly-one-outcome accounting ───────────────────────────────────

def test_counts_sum_to_number_of_catalogue_rows_per_chain(client, pc_db):
    addr_manual = "0x" + "d" * 40
    _seed_pool(pc_db, "robinhood", "0x" + "e" * 40, "AAPL", "USDG")      # would_insert
    _seed_pool(pc_db, "robinhood", "0x" + "f" * 40, "WETH", "USDG")      # would_insert
    _seed_pool(pc_db, "robinhood", "0x" + "1a" * 20, None, "USDG")       # skipped_null_symbol
    _seed_pool(pc_db, "robinhood", addr_manual, "AAPL", "USDG")
    _seed_meta(pc_db, "robinhood", addr_manual, "crypto", "glenn")       # skipped_manual

    r = _run(client)

    chain = r.get_json()["chains"]["robinhood"]
    total = (chain["would_insert"] + chain["would_update_heuristic"]
             + chain["skipped_manual"] + chain["skipped_null_symbol"])
    assert total == 4
