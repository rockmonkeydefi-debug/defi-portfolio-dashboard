"""Route-level tests for LP Advisor Phase B, commit 2 (B2): POST
/api/maxfi/metrics-refresh/<chain> - reads the requested pool set
(catalogue pools plus held-position pools not yet catalogued), fetches
DexScreener pair snapshots in batches, and OVERWRITE-ALWAYS upserts into
maxfi_pool_metrics. Same client/monkeypatch fixture pattern as
tests/test_maxfi_catalogue_refresh.py; same shared-cache sqlite URI
pattern as tests/test_maxfi_valuation_route.py:308, since the route opens
and closes its OWN connection per call.

No network - maxfi_pooldata.fetch_dexscreener_pairs is monkeypatched.
"""
import sqlite3
import uuid

import pytest

import maxfi_pooldata
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
def metrics_db(monkeypatch):
    uri = f"file:maxfi_metrics_refresh_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
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


def _seed_catalogue_pool(db, chain, pool_address, ts="2026-01-01T00:00:00+00:00"):
    db.execute(
        """
        INSERT INTO maxfi_catalogue_pools (
          chain, pool_address, token0_address, token1_address,
          token0_symbol, token1_symbol, fee_tier, position_count,
          first_seen_at, last_seen_at, last_enumerated_at
        ) VALUES (?, ?, '0xtoken0', '0xtoken1', 'FOO', 'USDC', 3000, 1, ?, ?, ?)
        """,
        (chain, pool_address, ts, ts, ts),
    )
    db.commit()


def _seed_position(db, position_id, chain="base", pool_address="0xpool", status="open",
                    wallet=WALLET, token_id=None):
    db.execute(
        """
        INSERT INTO maxfi_positions (
            id, chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, last_scan_at
        ) VALUES (?, ?, ?, ?, 0, ?, '0xT0', '0xT1', 3000, ?,
                  '2026-01-01T00:00:00+00:00', 'chain', '2026-01-01T00:00:00+00:00')
        """,
        (position_id, chain, wallet, token_id or str(position_id), pool_address, status),
    )
    db.commit()


def _seed_metrics_row(db, chain, pool_address, price_usd=1.0, fetched_at="2026-01-01T00:00:00+00:00"):
    db.execute(
        """
        INSERT INTO maxfi_pool_metrics (
          chain, pool_address, price_usd, liquidity_usd, volume_h24,
          volume_h6, volume_h1, price_change_h24, fetched_at
        ) VALUES (?, ?, ?, 1000.0, 100.0, 10.0, 1.0, 0.5, ?)
        """,
        (chain, pool_address, price_usd, fetched_at),
    )
    db.commit()


def _metrics_rows(db, chain="base"):
    return {
        row["pool_address"]: dict(row)
        for row in db.execute(
            "SELECT * FROM maxfi_pool_metrics WHERE chain = ?", (chain,)
        ).fetchall()
    }


def _pair(pool_address, price_usd="1.23", liquidity_usd=5000.0, volume_h24=1000.0,
          volume_h6=100.0, volume_h1=10.0, price_change_h24=2.5):
    pair = {"pairAddress": pool_address, "priceUsd": price_usd}
    if liquidity_usd is not None:
        pair["liquidity"] = {"usd": liquidity_usd}
    if volume_h24 is not None or volume_h6 is not None or volume_h1 is not None:
        pair["volume"] = {"h24": volume_h24, "h6": volume_h6, "h1": volume_h1}
    if price_change_h24 is not None:
        pair["priceChange"] = {"h24": price_change_h24}
    return pair


# ── fresh write ──────────────────────────────────────────────────────────

def test_fresh_write_two_catalogue_pools(client, metrics_db, monkeypatch):
    _seed_catalogue_pool(metrics_db, "base", "0xpoola")
    _seed_catalogue_pool(metrics_db, "base", "0xpoolb")

    def _fake_fetch(slug, batch):
        return [_pair("0xpoola", price_usd="1.5"), _pair("0xpoolb", price_usd="2.5")]
    monkeypatch.setattr(maxfi_pooldata, "fetch_dexscreener_pairs", _fake_fetch)

    r = client.post("/api/maxfi/metrics-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["requested_pools"] == 2
    assert body["catalogue_pools"] == 2
    assert body["held_only_pools"] == 0
    assert body["written"] == 2
    assert body["dry_run"] is False

    rows = _metrics_rows(metrics_db)
    assert set(rows.keys()) == {"0xpoola", "0xpoolb"}
    assert rows["0xpoola"]["price_usd"] == 1.5
    assert rows["0xpoola"]["fetched_at"] == body["fetched_at"]
    assert rows["0xpoolb"]["price_usd"] == 2.5


# ── OVERWRITE-ALWAYS ─────────────────────────────────────────────────────

def test_metrics_refresh_overwrite_always_replaces_full_row(client, metrics_db, monkeypatch):
    _seed_catalogue_pool(metrics_db, "base", "0xpoola")

    def _fetch_run1(slug, batch):
        return [_pair("0xpoola", price_usd="1.0", liquidity_usd=100.0, price_change_h24=5.0)]
    monkeypatch.setattr(maxfi_pooldata, "fetch_dexscreener_pairs", _fetch_run1)

    r1 = client.post("/api/maxfi/metrics-refresh/base")
    assert r1.status_code == 200
    row1 = _metrics_rows(metrics_db)["0xpoola"]
    assert row1["price_usd"] == 1.0
    assert row1["liquidity_usd"] == 100.0
    assert row1["price_change_h24"] == 5.0
    fetched_at_1 = row1["fetched_at"]

    # Second run: different price/liquidity, priceChange omitted entirely
    # (thin-pair shape) - must end up NULL, not carrying over run 1's value.
    def _fetch_run2(slug, batch):
        return [_pair("0xpoola", price_usd="9.0", liquidity_usd=200.0, price_change_h24=None)]
    monkeypatch.setattr(maxfi_pooldata, "fetch_dexscreener_pairs", _fetch_run2)

    r2 = client.post("/api/maxfi/metrics-refresh/base")
    assert r2.status_code == 200
    body2 = r2.get_json()
    row2 = _metrics_rows(metrics_db)["0xpoola"]

    assert row2["price_usd"] == 9.0
    assert row2["liquidity_usd"] == 200.0
    assert row2["price_change_h24"] is None
    assert row2["fetched_at"] == body2["fetched_at"]
    assert row2["fetched_at"] != fetched_at_1


# ── per-batch isolation ──────────────────────────────────────────────────

def test_per_batch_isolation_first_batch_fails_second_succeeds(client, metrics_db, monkeypatch):
    pool_addrs = [f"0xpool{i:03d}" for i in range(35)]
    for addr in pool_addrs:
        _seed_catalogue_pool(metrics_db, "base", addr)

    calls = []

    def _fake_fetch(slug, batch):
        calls.append(batch)
        if len(calls) == 1:
            raise maxfi_pooldata.DexScreenerError("simulated batch failure")
        return [_pair(addr) for addr in batch]
    monkeypatch.setattr(maxfi_pooldata, "fetch_dexscreener_pairs", _fake_fetch)

    r = client.post("/api/maxfi/metrics-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["batches_total"] == 2
    assert body["batches_failed"] == 1
    assert len(body["failed_batches"]) == 1
    assert body["failed_batches"][0]["batch_index"] == 0
    assert body["failed_batches"][0]["size"] == 30
    assert "simulated batch failure" in body["failed_batches"][0]["error"]

    rows = _metrics_rows(metrics_db)
    second_batch_addrs = set(calls[1])
    assert set(rows.keys()) == second_batch_addrs
    # The failed batch's 30 pools contribute to missing.
    assert body["missing"] == 30
    assert body["written"] == 5


# ── no-pair pool keeps its old snapshot ─────────────────────────────────

def test_pool_with_no_pair_data_keeps_old_snapshot(client, metrics_db, monkeypatch):
    _seed_catalogue_pool(metrics_db, "base", "0xpoola")
    _seed_catalogue_pool(metrics_db, "base", "0xpoolb")
    _seed_metrics_row(metrics_db, "base", "0xpoolb", price_usd=42.0, fetched_at="2020-01-01T00:00:00+00:00")

    def _fake_fetch(slug, batch):
        # Only pool A gets a pair back this run - pool B returns nothing.
        return [_pair("0xpoola")]
    monkeypatch.setattr(maxfi_pooldata, "fetch_dexscreener_pairs", _fake_fetch)

    r = client.post("/api/maxfi/metrics-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    rows = _metrics_rows(metrics_db)
    assert "0xpoola" in rows
    # Untouched - old snapshot, old fetched_at, never a partial/merged row.
    assert rows["0xpoolb"]["price_usd"] == 42.0
    assert rows["0xpoolb"]["fetched_at"] == "2020-01-01T00:00:00+00:00"
    assert body["missing"] == 1


# ── dry_run ──────────────────────────────────────────────────────────────

def test_dry_run_true_fetches_but_writes_nothing(client, metrics_db, monkeypatch):
    _seed_catalogue_pool(metrics_db, "base", "0xpoola")

    called = {"count": 0}

    def _fake_fetch(slug, batch):
        called["count"] += 1
        return [_pair("0xpoola")]
    monkeypatch.setattr(maxfi_pooldata, "fetch_dexscreener_pairs", _fake_fetch)

    r = client.post("/api/maxfi/metrics-refresh/base?dry_run=true")
    assert r.status_code == 200
    body = r.get_json()

    assert called["count"] == 1
    assert body["dry_run"] is True
    assert body["would_write"] == 1
    assert "written" not in body
    assert _metrics_rows(metrics_db) == {}


def test_dry_run_string_one_is_treated_as_a_real_run(client, metrics_db, monkeypatch):
    # Pins the exact-'true' convention: dry_run='1' must NOT be a dry run.
    _seed_catalogue_pool(metrics_db, "base", "0xpoola")
    monkeypatch.setattr(maxfi_pooldata, "fetch_dexscreener_pairs", lambda slug, batch: [_pair("0xpoola")])

    r = client.post("/api/maxfi/metrics-refresh/base?dry_run=1")
    assert r.status_code == 200
    body = r.get_json()

    assert body["dry_run"] is False
    assert body["written"] == 1
    assert len(_metrics_rows(metrics_db)) == 1


# ── held-only pool ───────────────────────────────────────────────────────

def test_held_only_pool_included_lowercased_and_written(client, metrics_db, monkeypatch):
    _seed_catalogue_pool(metrics_db, "base", "0xpoola")
    _seed_position(metrics_db, 1, chain="base", pool_address="0xPoolHeldOnly")

    def _fake_fetch(slug, batch):
        return [_pair("0xpoola"), _pair("0xpoolheldonly")]
    monkeypatch.setattr(maxfi_pooldata, "fetch_dexscreener_pairs", _fake_fetch)

    r = client.post("/api/maxfi/metrics-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["held_only_pools"] == 1
    assert body["requested_pools"] == 2

    rows = _metrics_rows(metrics_db)
    assert "0xpoolheldonly" in rows
    assert "0xPoolHeldOnly" not in rows


def test_closed_position_pool_not_included_as_held_only(client, metrics_db, monkeypatch):
    _seed_catalogue_pool(metrics_db, "base", "0xpoola")
    _seed_position(metrics_db, 1, chain="base", pool_address="0xclosedpool", status="closed")

    monkeypatch.setattr(maxfi_pooldata, "fetch_dexscreener_pairs", lambda slug, batch: [_pair("0xpoola")])

    r = client.post("/api/maxfi/metrics-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["held_only_pools"] == 0
    assert body["requested_pools"] == 1


# ── unrequested pair ignored ─────────────────────────────────────────────

def test_unrequested_pair_ignored_and_not_written(client, metrics_db, monkeypatch):
    _seed_catalogue_pool(metrics_db, "base", "0xpoola")

    def _fake_fetch(slug, batch):
        return [_pair("0xpoola"), _pair("0xnotrequested")]
    monkeypatch.setattr(maxfi_pooldata, "fetch_dexscreener_pairs", _fake_fetch)

    r = client.post("/api/maxfi/metrics-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["unrequested"] == 1
    assert body["written"] == 1

    rows = _metrics_rows(metrics_db)
    assert "0xnotrequested" not in rows
    assert set(rows.keys()) == {"0xpoola"}


# ── invalid chain ────────────────────────────────────────────────────────

def test_invalid_chain_returns_400(client, metrics_db):
    r = client.post("/api/maxfi/metrics-refresh/not-a-real-chain")
    assert r.status_code == 400
    body = r.get_json()
    assert body["error"] == "InvalidChain"
    assert "valid_chains" in body


# ── no pools ─────────────────────────────────────────────────────────────

def test_no_pools_returns_early_with_no_pools_note(client, metrics_db, monkeypatch):
    def _boom(slug, batch):
        raise AssertionError("must not fetch when the requested pool set is empty")
    monkeypatch.setattr(maxfi_pooldata, "fetch_dexscreener_pairs", _boom)

    r = client.post("/api/maxfi/metrics-refresh/base")
    assert r.status_code == 200
    body = r.get_json()
    assert body["requested_pools"] == 0
    assert body["note"] == "no_pools"
    assert _metrics_rows(metrics_db) == {}
