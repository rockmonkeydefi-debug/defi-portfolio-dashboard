"""Route-level regression tests for MaxFi Phase D.1.

Covers: the anchor registry code-side defaults + settings-override merge
(STEP 4), the dual-anchor valuation path where Phase D's one real defect
was found (STEP 5), the mirrored anchor-as-token1 case (also STEP 5 - the
census confirms this inversion direction is live in three real positions,
not hypothetical), and the collected_valuation_basis field (STEP 3c).

No network, no database writes - the client/anchor-resolver seams are
monkeypatched. web_portfolio spawns a background scheduler on non-__main__
import; we neutralize threading.Thread.start during import (established
pattern) so no thread starts.
"""
import json
import math
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

WALLET = "0x" + "b" * 40
WETH_BASE = "0x4200000000000000000000000000000000000006"
USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
WETH_ROBINHOOD = "0x0bd7d308f8e1639fab988df18a8011f41eacad73"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def price_to_tick(price_decimal_adjusted, decimals0, decimals1):
    raw_price = price_decimal_adjusted / (10 ** (decimals0 - decimals1))
    return math.log(raw_price) / math.log(1.0001)


def tick_to_sqrt_price_x96(tick):
    return int((1.0001 ** (tick / 2)) * (2 ** 96))


def make_diag(token0_addr, token1_addr, dec0, dec1, price_lower, price_upper, price_current, liquidity):
    """Synthetic position_diagnostic()-shaped payload with a
    self-consistent, correctly-derived sqrtPriceX96/ticks for the given
    (decimals-adjusted) price range and current price."""
    tick_lower = round(price_to_tick(price_lower, dec0, dec1))
    tick_upper = round(price_to_tick(price_upper, dec0, dec1))
    current_tick = round(price_to_tick(price_current, dec0, dec1))
    sqrt_price_x96 = tick_to_sqrt_price_x96(current_tick)
    return {
        "token0": {"address": token0_addr, "symbol": "T0", "decimals": dec0},
        "token1": {"address": token1_addr, "symbol": "T1", "decimals": dec1},
        "vault_position": {"decoded": {
            "currentTickLower": str(tick_lower), "currentTickUpper": str(tick_upper),
            "cumulativeFees0": "0", "cumulativeFees1": "0",
        }},
        "npm_position": {"decoded": {
            "liquidity": str(liquidity),
            "feeGrowthInside0LastX128": "0", "feeGrowthInside1LastX128": "0",
            "tokensOwed0": "0", "tokensOwed1": "0",
        }},
        "slot0": {"decoded": {"sqrtPriceX96": str(sqrt_price_x96), "tick": str(current_tick)}},
        "fee_growth_global_0_x128": "0", "fee_growth_global_1_x128": "0",
        "ticks_lower": {"decoded": {"feeGrowthOutside0X128": "0", "feeGrowthOutside1X128": "0"}},
        "ticks_upper": {"decoded": {"feeGrowthOutside0X128": "0", "feeGrowthOutside1X128": "0"}},
    }


# ── STEP 4: anchor registry defaults + settings override merge ──────────

def test_anchor_registry_defaults_resolve_all_four_seeded_addresses(monkeypatch):
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {})
    registry = wp._maxfi_effective_anchor_registry()
    assert registry["robinhood:0x0bd7d308f8e1639fab988df18a8011f41eacad73"] == "ETH"
    assert registry["robinhood:0x5fc5360d0400a0fd4f2af552add042d716f1d168"] == "USDG"
    assert registry["base:0x4200000000000000000000000000000000000006"] == "ETH"
    assert registry["base:0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"] == "USDC"


def test_anchor_registry_absent_settings_key_falls_back_to_defaults_only(monkeypatch):
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {"some_unrelated_key": 1})
    registry = wp._maxfi_effective_anchor_registry()
    assert registry == dict(wp.MAXFI_ANCHOR_REGISTRY_DEFAULTS)


def test_anchor_registry_settings_override_merges_on_top_not_replaces(monkeypatch):
    new_token = "base:0x9999999999999999999999999999999999999999"
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {
        "maxfi_anchor_registry": {new_token: "USDC"}
    })
    registry = wp._maxfi_effective_anchor_registry()
    assert registry[new_token] == "USDC"
    # All four code-side defaults survive - override merges on top, doesn't replace.
    assert registry["robinhood:0x0bd7d308f8e1639fab988df18a8011f41eacad73"] == "ETH"
    assert registry["robinhood:0x5fc5360d0400a0fd4f2af552add042d716f1d168"] == "USDG"
    assert registry["base:0x4200000000000000000000000000000000000006"] == "ETH"
    assert registry["base:0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"] == "USDC"
    assert len(registry) == 5


def test_anchor_registry_lookup_is_case_insensitive_on_address(monkeypatch):
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {
        "maxfi_anchor_registry": {"base:0xAAAABBBBCCCCDDDDEEEEFFFF0000111122223333": "USDC"}
    })
    registry = wp._maxfi_effective_anchor_registry()
    assert registry["base:0xaaaabbbbccccddddeeeeffff0000111122223333"] == "USDC"


# ── STEP 5: dual-anchor route-level regression ───────────────────────────
# The one real defect found in Phase D was here: a hand-rolled
# multiplication in this exact branch produced ~6.25M instead of ~1.0. See
# the Phase D.1 summary for confirmation that swapping the fix back to a
# multiplication makes this test fail.

def test_dual_anchor_route_path_sanity_check_and_value(monkeypatch, client):
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {})  # code-side defaults only
    monkeypatch.setattr(wp, "maxfi_eth_block_number", lambda chain: 1000)

    snapshot = [{"array_index": 0, "token_id": "1", "pool_address": "0xPOOL",
                 "token0_address": WETH_BASE, "token1_address": USDC_BASE, "fee_tier": 500}]
    monkeypatch.setattr(wp, "maxfi_get_wallet_position_snapshot", lambda chain, wallet: snapshot)

    diag = make_diag(WETH_BASE, USDC_BASE, 18, 6, 2300.0, 2700.0, 2500.0, 5 * 10 ** 17)
    monkeypatch.setattr(wp, "maxfi_position_diagnostic", lambda chain, wallet, token_id: diag)

    def fake_resolve(symbol, now=None, fetcher=None):
        return {"ETH": {"usd": 2500.0, "price_source": "live", "age_seconds": 0},
                "USDC": {"usd": 1.0, "price_source": "live", "age_seconds": 0}}[symbol]
    monkeypatch.setattr(wp.maxfi_anchor_prices, "resolve_anchor_price", fake_resolve)

    r = client.get(f"/api/maxfi/valuation/base/{WALLET}")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]

    assert "sanity_check" in pos
    assert pos["sanity_check"]["diverged"] is False
    assert pos["sanity_check"]["ratio"] == pytest.approx(1.0, rel=0.01)

    # Both anchors resolved INDEPENDENTLY (not derived from each other):
    # amount*_usd must equal amount * that side's own known price exactly.
    assert pos["amount0_usd"] == pytest.approx(pos["amount0"] * 2500.0, rel=1e-6)
    assert pos["amount1_usd"] == pytest.approx(pos["amount1"] * 1.0, rel=1e-6)
    expected_value = pos["amount0"] * 2500.0 + pos["amount1"] * 1.0
    assert pos["current_value_usd"] == pytest.approx(expected_value, rel=1e-6)


def test_single_anchor_route_path_anchor_as_token1(monkeypatch, client):
    """Address sorting can put the anchor on EITHER side. The token census
    confirms WETH sits as token1 in the CASHCAT pool and USDG as token1
    against DJT on Robinhood Chain - this inversion direction is live in
    three real positions, not a hypothetical edge case."""
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {})
    monkeypatch.setattr(wp, "maxfi_eth_block_number", lambda chain: 2000)

    memecoin_addr = "0x" + "c" * 40  # synthetic - exact address not needed for this test

    snapshot = [{"array_index": 0, "token_id": "2", "pool_address": "0xPOOL2",
                 "token0_address": memecoin_addr, "token1_address": WETH_ROBINHOOD, "fee_tier": 3000}]
    monkeypatch.setattr(wp, "maxfi_get_wallet_position_snapshot", lambda chain, wallet: snapshot)

    # 1 WETH = 2500 memecoin -> 1 memecoin = 1/2500 WETH.
    diag = make_diag(memecoin_addr, WETH_ROBINHOOD, 18, 18, 1 / 2600, 1 / 2400, 1 / 2500, 5 * 10 ** 17)
    monkeypatch.setattr(wp, "maxfi_position_diagnostic", lambda chain, wallet, token_id: diag)

    monkeypatch.setattr(
        wp.maxfi_anchor_prices, "resolve_anchor_price",
        lambda symbol, now=None, fetcher=None: {"usd": 2500.0, "price_source": "live", "age_seconds": 0},
    )

    r = client.get(f"/api/maxfi/valuation/robinhood/{WALLET}")
    assert r.status_code == 200
    pos = r.get_json()["positions"][0]

    assert pos["status"] in ("priced", "partial")
    assert pos["reason"] in (None, "no_matching_db_row")
    # token1 (WETH) is the anchor - its USD value is amount1 * $2500 exactly.
    assert pos["amount1_usd"] == pytest.approx(pos["amount1"] * 2500.0, rel=1e-6)
    # token0 (memecoin) is DERIVED: 1 memecoin ~= 1/2500 WETH ~= $1.
    assert pos["amount0_usd"] == pytest.approx(pos["amount0"] * 1.0, rel=0.01)


# ── D.2d hotfix: per-position isolation around anchor pricing ───────────
# D.2b's USDG KeyError crashed the WHOLE endpoint for a wallet holding even
# one USDG-anchored position, because no try/except wrapped this section.
# This proves isolation now actually contains a failure, not just that
# USDG specifically no longer raises.

def test_anchor_resolution_exception_isolated_from_other_positions(monkeypatch, client):
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {})
    monkeypatch.setattr(wp, "maxfi_eth_block_number", lambda chain: 5000)

    snapshot = [
        {"array_index": 0, "token_id": "5", "pool_address": "0xPOOL5",
         "token0_address": WETH_BASE, "token1_address": USDC_BASE, "fee_tier": 500},
        {"array_index": 1, "token_id": "6", "pool_address": "0xPOOL6",
         "token0_address": WETH_BASE, "token1_address": USDC_BASE, "fee_tier": 500},
    ]
    monkeypatch.setattr(wp, "maxfi_get_wallet_position_snapshot", lambda chain, wallet: snapshot)

    diag = make_diag(WETH_BASE, USDC_BASE, 18, 6, 2300.0, 2700.0, 2500.0, 5 * 10 ** 17)
    monkeypatch.setattr(wp, "maxfi_position_diagnostic", lambda chain, wallet, token_id: diag)

    calls = {"n": 0}

    def flaky_resolve(symbol, now=None, fetcher=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyError("USDG")  # simulates the exact D.2b production crash
        return {"ETH": {"usd": 2500.0, "price_source": "live", "age_seconds": 0},
                "USDC": {"usd": 1.0, "price_source": "live", "age_seconds": 0}}[symbol]
    monkeypatch.setattr(wp.maxfi_anchor_prices, "resolve_anchor_price", flaky_resolve)

    r = client.get(f"/api/maxfi/valuation/base/{WALLET}")
    assert r.status_code == 200  # the whole response must NOT 500
    positions = r.get_json()["positions"]
    assert len(positions) == 2

    failed = positions[0]
    assert failed["status"] == "unpriced"
    assert failed["reason"] == "anchor_resolution_error"
    assert failed["current_value_usd"] is None
    assert failed["performance"] is None
    assert failed["collected_valuation_basis"] is None

    # The second position's resolution must be entirely unaffected by the
    # first position's exception - proving isolation, not just that this
    # one asset happens not to crash.
    healthy = positions[1]
    assert healthy["status"] in ("priced", "partial")
    assert healthy["current_value_usd"] is not None


# ── STEP 3c: collected_valuation_basis field ─────────────────────────────

def test_valuation_response_includes_collected_valuation_basis(monkeypatch, client):
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {})
    monkeypatch.setattr(wp, "maxfi_eth_block_number", lambda chain: 3000)

    snapshot = [{"array_index": 0, "token_id": "3", "pool_address": "0xPOOL3",
                 "token0_address": WETH_BASE, "token1_address": USDC_BASE, "fee_tier": 500}]
    monkeypatch.setattr(wp, "maxfi_get_wallet_position_snapshot", lambda chain, wallet: snapshot)

    diag = make_diag(WETH_BASE, USDC_BASE, 18, 6, 2300.0, 2700.0, 2500.0, 5 * 10 ** 17)
    monkeypatch.setattr(wp, "maxfi_position_diagnostic", lambda chain, wallet, token_id: diag)

    def fake_resolve(symbol, now=None, fetcher=None):
        return {"ETH": {"usd": 2500.0, "price_source": "live", "age_seconds": 0},
                "USDC": {"usd": 1.0, "price_source": "live", "age_seconds": 0}}[symbol]
    monkeypatch.setattr(wp.maxfi_anchor_prices, "resolve_anchor_price", fake_resolve)

    r = client.get(f"/api/maxfi/valuation/base/{WALLET}")
    pos = r.get_json()["positions"][0]
    assert pos["collected_valuation_basis"] == "current_price"


def test_unpriced_position_has_null_collected_valuation_basis(monkeypatch, client):
    # No anchor in this pair at all -> unpriced, and collected fees were
    # never valued, so the basis field must be null, not a misleading
    # "current_price" label on a figure that doesn't exist.
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {})
    monkeypatch.setattr(wp, "maxfi_eth_block_number", lambda chain: 4000)

    non_anchor_a = "0x" + "d" * 40
    non_anchor_b = "0x" + "e" * 40
    snapshot = [{"array_index": 0, "token_id": "4", "pool_address": "0xPOOL4",
                 "token0_address": non_anchor_a, "token1_address": non_anchor_b, "fee_tier": 3000}]
    monkeypatch.setattr(wp, "maxfi_get_wallet_position_snapshot", lambda chain, wallet: snapshot)

    diag = make_diag(non_anchor_a, non_anchor_b, 18, 18, 0.9, 1.1, 1.0, 5 * 10 ** 17)
    monkeypatch.setattr(wp, "maxfi_position_diagnostic", lambda chain, wallet, token_id: diag)

    r = client.get(f"/api/maxfi/valuation/base/{WALLET}")
    pos = r.get_json()["positions"][0]
    assert pos["status"] == "unpriced"
    assert pos["reason"] == "no_anchor_in_pair"
    assert pos["collected_valuation_basis"] is None


# ── /initial-value: null clears a basis (DELETE, not a null-valued row) ─────
#
# get_connection() is called via a local `from src.storage.portfolio_db
# import get_connection` INSIDE the route body, re-resolving the module
# attribute on every call - so patching portfolio_db.get_connection itself
# (not wp.get_connection, which doesn't exist as a module-level name here)
# correctly intercepts every connection the route opens. A shared-cache
# sqlite URI (unique per test, via uuid) is used rather than plain
# ":memory:" because the route opens and closes its OWN connection per
# call - a fresh anonymous ":memory:" db would lose all state the instant
# the route's own conn.close() ran, breaking any test that calls the route
# more than once (clear-then-verify, double-clear, etc).

@pytest.fixture
def iv_db(monkeypatch):
    uri = f"file:maxfi_iv_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
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


def _seed_position(db, position_id):
    db.execute(
        """
        INSERT INTO maxfi_positions (
            id, chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, first_seen_block,
            last_scan_at, closed_at
        ) VALUES (?, 'base', '0xWALLET', ?, 0, '0xPOOL', '0xT0', '0xT1', 3000,
                  'open', '2026-01-01T00:00:00+00:00', 'chain', '1',
                  '2026-01-01T00:00:00+00:00', NULL)
        """,
        (position_id, str(position_id)),
    )
    db.commit()


def test_clear_existing_basis_deletes_the_row(client, iv_db):
    _seed_position(iv_db, 31)
    iv_db.execute(
        "INSERT INTO maxfi_initial_value (position_id, source, initial_value_usd, set_at, set_by) "
        "VALUES (31, 'ambiguity_auto_split', 324.18, '2026-08-29T20:44:00+00:00', 'system')"
    )
    iv_db.commit()

    r = client.post("/api/maxfi/positions/31/initial-value", json={"initial_value_usd": None})

    assert r.status_code == 200
    body = r.get_json()
    assert body == {
        "position_id": 31, "initial_value_usd": None, "source": None,
        "set_by": None, "set_at": body["set_at"], "cleared": True,
        "skipped": False,
    }
    row = iv_db.execute("SELECT 1 FROM maxfi_initial_value WHERE position_id = 31").fetchone()
    assert row is None


def test_clear_when_no_row_exists_is_a_no_op_success(client, iv_db):
    _seed_position(iv_db, 40)

    r = client.post("/api/maxfi/positions/40/initial-value", json={"initial_value_usd": None})

    assert r.status_code == 200
    assert r.get_json()["cleared"] is True
    row = iv_db.execute("SELECT 1 FROM maxfi_initial_value WHERE position_id = 40").fetchone()
    assert row is None


def test_set_a_number_still_works_unchanged(client, iv_db):
    _seed_position(iv_db, 41)

    r = client.post("/api/maxfi/positions/41/initial-value", json={"initial_value_usd": 123.45})

    assert r.status_code == 200
    body = r.get_json()
    assert body["position_id"] == 41
    assert body["initial_value_usd"] == 123.45
    assert body["source"] == "manual_override"
    assert body["set_by"] == "glenn"
    assert body["cleared"] is False
    row = iv_db.execute(
        "SELECT source, initial_value_usd FROM maxfi_initial_value WHERE position_id = 41"
    ).fetchone()
    assert row["source"] == "manual_override"
    assert row["initial_value_usd"] == 123.45


def test_absent_field_is_400_and_does_not_clear(client, iv_db):
    _seed_position(iv_db, 42)
    iv_db.execute(
        "INSERT INTO maxfi_initial_value (position_id, source, initial_value_usd, set_at, set_by) "
        "VALUES (42, 'manual_override', 50.0, '2026-01-01T00:00:00+00:00', 'glenn')"
    )
    iv_db.commit()

    r = client.post("/api/maxfi/positions/42/initial-value", json={})

    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidInitialValue"
    row = iv_db.execute(
        "SELECT initial_value_usd FROM maxfi_initial_value WHERE position_id = 42"
    ).fetchone()
    assert row is not None and row["initial_value_usd"] == 50.0


@pytest.mark.parametrize("bool_value", [True, False])
def test_booleans_are_rejected_and_false_does_not_clear(client, iv_db, bool_value):
    _seed_position(iv_db, 43)
    iv_db.execute(
        "INSERT INTO maxfi_initial_value (position_id, source, initial_value_usd, set_at, set_by) "
        "VALUES (43, 'manual_override', 75.0, '2026-01-01T00:00:00+00:00', 'glenn')"
    )
    iv_db.commit()

    r = client.post("/api/maxfi/positions/43/initial-value", json={"initial_value_usd": bool_value})

    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidInitialValue"
    row = iv_db.execute(
        "SELECT initial_value_usd FROM maxfi_initial_value WHERE position_id = 43"
    ).fetchone()
    assert row is not None and row["initial_value_usd"] == 75.0  # untouched, NOT cleared


def test_clear_for_nonexistent_position_id_is_position_not_found(client, iv_db):
    r = client.post("/api/maxfi/positions/999999/initial-value", json={"initial_value_usd": None})

    assert r.status_code == 400
    assert r.get_json()["error"] == "PositionNotFound"


def test_clear_is_idempotent_two_consecutive_clears_both_succeed(client, iv_db):
    _seed_position(iv_db, 44)
    iv_db.execute(
        "INSERT INTO maxfi_initial_value (position_id, source, initial_value_usd, set_at, set_by) "
        "VALUES (44, 'manual_override', 10.0, '2026-01-01T00:00:00+00:00', 'glenn')"
    )
    iv_db.commit()

    r1 = client.post("/api/maxfi/positions/44/initial-value", json={"initial_value_usd": None})
    r2 = client.post("/api/maxfi/positions/44/initial-value", json={"initial_value_usd": None})

    assert r1.status_code == 200 and r1.get_json()["cleared"] is True
    assert r2.status_code == 200 and r2.get_json()["cleared"] is True
    row = iv_db.execute("SELECT 1 FROM maxfi_initial_value WHERE position_id = 44").fetchone()
    assert row is None


# ── Block C1: only_if_empty on /initial-value, and the manual /close route ──
#
# The skip decision in only_if_empty must key SOLELY on whether a
# maxfi_initial_value row exists - never on maxfi_positions.notes. Row 31
# above is the canonical trap: its notes column (seeded by the real
# auto-split write path, see test_maxfi_auto_split_write.py) can carry
# auto-split JSON proposing one value while its actual maxfi_initial_value
# row already holds a different, human-corrected value. Keying on notes
# would skip a row a human already fixed.

def _seed_basis(db, position_id, source, value, set_by='glenn', set_at='2026-01-01T00:00:00+00:00'):
    db.execute(
        "INSERT INTO maxfi_initial_value (position_id, source, initial_value_usd, set_at, set_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (position_id, source, value, set_at, set_by),
    )
    db.commit()


def test_only_if_empty_absent_overwrites_exactly_as_before(client, iv_db):
    _seed_position(iv_db, 50)
    _seed_basis(iv_db, 50, 'ambiguity_auto_split', 324.18, set_by='system')

    r = client.post("/api/maxfi/positions/50/initial-value", json={"initial_value_usd": 999.0})

    assert r.status_code == 200
    body = r.get_json()
    assert body["initial_value_usd"] == 999.0
    assert body["source"] == "manual_override"
    assert body["skipped"] is False
    row = iv_db.execute(
        "SELECT source, initial_value_usd FROM maxfi_initial_value WHERE position_id = 50"
    ).fetchone()
    assert row["source"] == "manual_override" and row["initial_value_usd"] == 999.0


def test_only_if_empty_explicit_false_same_as_absent(client, iv_db):
    _seed_position(iv_db, 51)
    _seed_basis(iv_db, 51, 'manual_override', 10.0)

    r = client.post(
        "/api/maxfi/positions/51/initial-value",
        json={"initial_value_usd": 500.0, "only_if_empty": False},
    )

    assert r.status_code == 200
    body = r.get_json()
    assert body["initial_value_usd"] == 500.0
    assert body["skipped"] is False
    row = iv_db.execute(
        "SELECT initial_value_usd FROM maxfi_initial_value WHERE position_id = 51"
    ).fetchone()
    assert row["initial_value_usd"] == 500.0


def test_only_if_empty_true_no_existing_row_writes_normally(client, iv_db):
    _seed_position(iv_db, 52)

    r = client.post(
        "/api/maxfi/positions/52/initial-value",
        json={"initial_value_usd": 42.0, "only_if_empty": True},
    )

    assert r.status_code == 200
    body = r.get_json()
    assert body["initial_value_usd"] == 42.0
    assert body["source"] == "manual_override"
    assert body["skipped"] is False
    row = iv_db.execute(
        "SELECT source, initial_value_usd FROM maxfi_initial_value WHERE position_id = 52"
    ).fetchone()
    assert row["source"] == "manual_override" and row["initial_value_usd"] == 42.0


def test_only_if_empty_true_existing_auto_split_row_skips_and_writes_nothing(client, iv_db):
    _seed_position(iv_db, 53)
    _seed_basis(iv_db, 53, 'ambiguity_auto_split', 324.18, set_by='system')

    r = client.post(
        "/api/maxfi/positions/53/initial-value",
        json={"initial_value_usd": 999.0, "only_if_empty": True},
    )

    assert r.status_code == 200
    body = r.get_json()
    assert body["skipped"] is True
    assert body["cleared"] is False
    assert body["initial_value_usd"] == 324.18   # the EXISTING value, not 999.0
    assert body["source"] == "ambiguity_auto_split"
    assert body["set_by"] == "system"
    row = iv_db.execute(
        "SELECT source, initial_value_usd FROM maxfi_initial_value WHERE position_id = 53"
    ).fetchone()
    assert row["source"] == "ambiguity_auto_split" and row["initial_value_usd"] == 324.18  # unchanged


def test_only_if_empty_true_existing_manual_override_row_also_skips(client, iv_db):
    _seed_position(iv_db, 54)
    _seed_basis(iv_db, 54, 'manual_override', 200.0)

    r = client.post(
        "/api/maxfi/positions/54/initial-value",
        json={"initial_value_usd": 999.0, "only_if_empty": True},
    )

    assert r.status_code == 200
    body = r.get_json()
    assert body["skipped"] is True
    assert body["initial_value_usd"] == 200.0
    assert body["source"] == "manual_override"
    row = iv_db.execute(
        "SELECT initial_value_usd FROM maxfi_initial_value WHERE position_id = 54"
    ).fetchone()
    assert row["initial_value_usd"] == 200.0


def test_ROW_31_CASE_skip_keys_on_initial_value_row_never_on_notes(client, iv_db):
    """The exact scenario the task's own spec calls out by name: row 31's
    notes column carries auto-split JSON proposing $324.18, but its real
    maxfi_initial_value row is a human 'manual_override' at $130.00 - Glenn
    overrode a fabricated basis. only_if_empty must skip based on the
    maxfi_initial_value row's existence alone and must never parse notes -
    a future refactor that starts keying the skip on notes would revive the
    discarded $324.18 value or otherwise disagree with this test."""
    iv_db.execute(
        """
        INSERT INTO maxfi_positions (
            id, chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, first_seen_block,
            last_scan_at, closed_at, notes
        ) VALUES (31, 'base', '0xWALLET', '31', 0, '0xPOOL', '0xT0', '0xT1', 3000,
                  'open', '2026-01-01T00:00:00+00:00', 'chain', '1',
                  '2026-01-01T00:00:00+00:00', NULL, ?)
        """,
        ('{"resolution": "ambiguity_auto_split", "arriving": '
         '[{"token_id": "31", "proposed_initial_value_usd": 324.18}]}',),
    )
    _seed_basis(iv_db, 31, 'manual_override', 130.0)

    r = client.post(
        "/api/maxfi/positions/31/initial-value",
        json={"initial_value_usd": 999.0, "only_if_empty": True},
    )

    assert r.status_code == 200
    body = r.get_json()
    assert body["skipped"] is True
    assert body["initial_value_usd"] == 130.0   # the human override survives
    assert body["source"] == "manual_override"
    row = iv_db.execute(
        "SELECT source, initial_value_usd FROM maxfi_initial_value WHERE position_id = 31"
    ).fetchone()
    assert row["source"] == "manual_override" and row["initial_value_usd"] == 130.0


def test_only_if_empty_true_with_null_value_is_400_and_writes_nothing(client, iv_db):
    _seed_position(iv_db, 55)

    r = client.post(
        "/api/maxfi/positions/55/initial-value",
        json={"initial_value_usd": None, "only_if_empty": True},
    )

    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidOnlyIfEmpty"
    row = iv_db.execute("SELECT 1 FROM maxfi_initial_value WHERE position_id = 55").fetchone()
    assert row is None


@pytest.mark.parametrize("bad_value", ["true", 1])
def test_only_if_empty_non_bool_is_400(client, iv_db, bad_value):
    _seed_position(iv_db, 56)

    r = client.post(
        "/api/maxfi/positions/56/initial-value",
        json={"initial_value_usd": 10.0, "only_if_empty": bad_value},
    )

    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidOnlyIfEmpty"
    row = iv_db.execute("SELECT 1 FROM maxfi_initial_value WHERE position_id = 56").fetchone()
    assert row is None


# ── Block C1: manual /close route ────────────────────────────────────────

def test_close_open_position_succeeds(client, iv_db):
    _seed_position(iv_db, 60)

    r = client.post("/api/maxfi/positions/60/close")

    assert r.status_code == 200
    body = r.get_json()
    assert body["position_id"] == 60
    assert body["status"] == "closed"
    assert body["closed_by"] == "manual_ui"
    assert body["already_closed"] is False
    assert body["closed_at"]
    row = iv_db.execute(
        "SELECT status, closed_at, closed_by FROM maxfi_positions WHERE id = 60"
    ).fetchone()
    assert row["status"] == "closed" and row["closed_by"] == "manual_ui"
    assert row["closed_at"] == body["closed_at"]


def test_close_already_closed_position_is_idempotent(client, iv_db):
    _seed_position(iv_db, 61)

    r1 = client.post("/api/maxfi/positions/61/close")
    r2 = client.post("/api/maxfi/positions/61/close")

    assert r1.status_code == 200 and r2.status_code == 200
    body1, body2 = r1.get_json(), r2.get_json()
    assert body1["already_closed"] is False
    assert body2["already_closed"] is True
    assert body2["closed_at"] == body1["closed_at"]   # unchanged from the first call
    assert body2["closed_by"] == "manual_ui"


def test_close_unknown_position_is_400_position_not_found(client, iv_db):
    r = client.post("/api/maxfi/positions/999999/close")

    assert r.status_code == 400
    assert r.get_json()["error"] == "PositionNotFound"


def test_close_non_integer_position_id_is_400_invalid_position_id(client, iv_db):
    r = client.post("/api/maxfi/positions/not-an-int/close")

    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidPositionId"


def test_close_preserves_existing_basis_row(client, iv_db):
    _seed_position(iv_db, 62)
    _seed_basis(iv_db, 62, 'manual_override', 55.5)

    r = client.post("/api/maxfi/positions/62/close")

    assert r.status_code == 200
    row = iv_db.execute(
        "SELECT source, initial_value_usd FROM maxfi_initial_value WHERE position_id = 62"
    ).fetchone()
    assert row is not None
    assert row["source"] == "manual_override" and row["initial_value_usd"] == 55.5


def test_positions_list_surfaces_closed_by(client, iv_db):
    _seed_position(iv_db, 70)   # open row -> closed_by must be null
    _seed_position(iv_db, 71)
    iv_db.execute("UPDATE maxfi_positions SET status='closed', closed_at=?, closed_by=NULL WHERE id=71",
                  ('2026-01-01T00:00:00+00:00',))
    _seed_position(iv_db, 72)
    iv_db.execute(
        "UPDATE maxfi_positions SET status='closed', closed_at=?, closed_by='manual_ui' WHERE id=72",
        ('2026-01-01T00:00:00+00:00',),
    )
    iv_db.commit()

    r = client.get("/api/maxfi/positions/base/0xWALLET")

    assert r.status_code == 200
    by_id = {row["id"]: row for row in r.get_json()}
    assert by_id[70]["closed_by"] is None
    assert by_id[71]["closed_by"] is None       # scan-closed
    assert by_id[72]["closed_by"] == "manual_ui"  # manually closed


# ── Block B: durable maxfi_token_symbols cache ───────────────────────────
#
# api_maxfi_token_census's own decimals()/symbol() Multicall3 batching and
# decoding (encode_aggregate3/decode_aggregate3_result/decode_string_or_
# bytes32) is proven, existing code and is NOT reimplemented here - these
# fake_aggregate3_raw()/word encoders below build a raw hex response using
# the exact inverse of decode_aggregate3_result()'s own indexing scheme, so
# every test below exercises the REAL decoder end to end rather than
# stubbing it out. The only new code under test is: the maxfi_token_symbols
# table (maxfi_schema.py) and the write-through/read-through wiring around
# it (web_portfolio.py).
#
# maxfi_get_wallet_position_snapshot is always monkeypatched to a canned
# snapshot (the established pattern above) so the *snapshot* fetch never
# touches the network either - the only thing tests need to assert about
# RPC usage is calls to maxfi_rpc_call, which is exactly the entry point
# the decimals()/symbol() Multicall3 batch (and nothing else in this route)
# goes through.

def _word(n):
    return format(n, "064x")


def _encode_uint_return(n):
    return "0x" + _word(n)


def _encode_string_return(s):
    b = s.encode("utf-8")
    n_words = (len(b) + 31) // 32 if b else 0
    padded = b + b"\x00" * (n_words * 32 - len(b))
    return "0x" + _word(0x20) + _word(len(b)) + padded.hex()


def fake_aggregate3_raw(results):
    """Build the raw hex Multicall3.aggregate3 would return for `results`
    (a list of (success: bool, return_data_hex: str) in call order)."""
    n = len(results)
    tuples_words = []
    element_word_offsets = []
    running = 0
    for success, data_hex in results:
        element_word_offsets.append(n + running)
        raw_bytes = bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex)
        n_words = (len(raw_bytes) + 31) // 32
        padded = raw_bytes + b"\x00" * (n_words * 32 - len(raw_bytes))
        padded_hex = padded.hex()
        tuple_words = [_word(1 if success else 0), _word(0x40), _word(len(raw_bytes))]
        tuple_words += [padded_hex[i * 64:(i + 1) * 64] for i in range(n_words)]
        tuples_words.append(tuple_words)
        running += len(tuple_words)

    offset_words = [_word(o * 32) for o in element_word_offsets]
    all_words = [_word(0x20), _word(n)] + offset_words
    for tw in tuples_words:
        all_words.extend(tw)
    return "0x" + "".join(all_words)


def _fail_if_called(*args, **kwargs):
    pytest.fail("maxfi_rpc_call was invoked - a warm cache must issue zero RPC calls")


TOKEN_A = "0x" + "1" * 40
TOKEN_B = "0x" + "2" * 40


@pytest.fixture
def census_client(monkeypatch, client):
    """The `client` fixture plus a clean, isolated MaxFi DB
    (get_connection() monkeypatched to a per-test shared-cache sqlite URI,
    same technique as `iv_db`) and a FRESH in-process
    _maxfi_token_metadata_cache - this dict is module-level state shared
    across the whole pytest session, so a leftover entry from another test
    must never make a test in this section look like it hit a cache it
    didn't actually populate itself."""
    uri = f"file:maxfi_census_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    keepalive.row_factory = sqlite3.Row
    maxfi_schema.ensure_maxfi_tables(keepalive)

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    monkeypatch.setattr(wp, "_maxfi_token_metadata_cache", {})
    monkeypatch.setattr(wp, "maxfi_multicall_chunk_size", lambda: 1000)
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {})
    yield keepalive
    keepalive.close()


def test_ensure_maxfi_tables_creates_token_symbols_and_is_idempotent():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    maxfi_schema.ensure_maxfi_tables(conn)
    maxfi_schema.ensure_maxfi_tables(conn)  # must not raise on rerun

    cols = {row["name"] for row in conn.execute("PRAGMA table_info(maxfi_token_symbols)")}
    assert cols == {"chain", "address", "symbol", "decimals", "last_attempt_at"}
    conn.close()


def test_ensure_maxfi_tables_does_not_add_a_schema_status_key_for_token_symbols():
    conn = sqlite3.connect(":memory:")
    status = maxfi_schema.ensure_maxfi_tables(conn)
    assert set(status.keys()) == {"unique_index_ready", "notes_column_ready"}
    conn.close()


def test_CASING_row_written_mixed_case_is_found_by_a_differently_cased_lookup(
    monkeypatch, census_client
):
    """The single most likely way to get this block wrong (per the design
    doc): a cache keyed on address must normalize casing at BOTH write and
    lookup time, or a token resolved once will silently look unresolved
    forever and re-fetch on every request. First run writes the row for a
    MIXED-CASE address; second run presents the SAME token in a
    DIFFERENT casing and must still find it in the table (zero RPC calls
    the second time)."""
    mixed_case_addr = "0x" + "Aa" * 20
    other_case_addr = "0x" + ("Aa" * 20).lower()

    snapshot = [{"array_index": 0, "token_id": "1", "pool_address": "0xPOOL",
                 "token0_address": mixed_case_addr, "token1_address": TOKEN_B, "fee_tier": 500}]
    monkeypatch.setattr(wp, "maxfi_get_wallet_position_snapshot", lambda chain, wallet: snapshot)

    raw = fake_aggregate3_raw([
        (True, _encode_uint_return(18)), (True, _encode_string_return("AAA")),
        (True, _encode_uint_return(6)), (True, _encode_string_return("BBB")),
    ])
    monkeypatch.setattr(wp, "maxfi_rpc_call", lambda chain, to, cd, timeout=None: raw)

    r1 = client_get_census(census_client, wp, "base", WALLET)
    assert r1["resolution_counts"]["fetched_via_rpc"] == 2

    # Second run: a DIFFERENT casing of the SAME address, fresh snapshot,
    # zero-RPC RPC layer, AND a reset in-process cache (simulating a new
    # worker process) so this run is forced through the DURABLE TABLE
    # lookup - the thing this test is actually about - rather than being
    # silently served by the (also-correct, but untested-here) in-process
    # dict from run 1.
    monkeypatch.setattr(wp, "_maxfi_token_metadata_cache", {})
    snapshot2 = [{"array_index": 0, "token_id": "1", "pool_address": "0xPOOL",
                  "token0_address": other_case_addr, "token1_address": TOKEN_B, "fee_tier": 500}]
    monkeypatch.setattr(wp, "maxfi_get_wallet_position_snapshot", lambda chain, wallet: snapshot2)
    monkeypatch.setattr(wp, "maxfi_rpc_call", _fail_if_called)

    r2 = client_get_census(census_client, wp, "base", WALLET)
    assert r2["resolution_counts"]["fetched_via_rpc"] == 0
    assert r2["resolution_counts"]["served_from_table"] == 2
    symbols = {t["address"]: t["symbol"] for t in r2["tokens"]}
    assert symbols[other_case_addr] == "AAA"


def test_write_through_resolved_symbols_land_in_maxfi_token_symbols(monkeypatch, census_client):
    snapshot = [{"array_index": 0, "token_id": "1", "pool_address": "0xPOOL",
                 "token0_address": TOKEN_A, "token1_address": TOKEN_B, "fee_tier": 3000}]
    monkeypatch.setattr(wp, "maxfi_get_wallet_position_snapshot", lambda chain, wallet: snapshot)

    raw = fake_aggregate3_raw([
        (True, _encode_uint_return(18)), (True, _encode_string_return("TKA")),
        (True, _encode_uint_return(6)), (True, _encode_string_return("TKB")),
    ])
    monkeypatch.setattr(wp, "maxfi_rpc_call", lambda chain, to, cd, timeout=None: raw)

    body = client_get_census(census_client, wp, "base", WALLET)
    assert body["resolution_counts"]["fetched_via_rpc"] == 2

    rows = {
        r["address"]: (r["symbol"], r["decimals"])
        for r in census_client.execute(
            "SELECT address, symbol, decimals FROM maxfi_token_symbols WHERE chain = 'base'"
        ).fetchall()
    }
    assert rows[TOKEN_A] == ("TKA", 18)
    assert rows[TOKEN_B] == ("TKB", 6)


def test_warm_cache_issues_zero_rpc_calls(monkeypatch, census_client):
    now = "2026-08-30T00:00:00+00:00"
    census_client.executemany(
        "INSERT INTO maxfi_token_symbols (chain, address, symbol, decimals, last_attempt_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [("base", TOKEN_A, "TKA", 18, now), ("base", TOKEN_B, "TKB", 6, now)],
    )
    census_client.commit()

    snapshot = [{"array_index": 0, "token_id": "1", "pool_address": "0xPOOL",
                 "token0_address": TOKEN_A, "token1_address": TOKEN_B, "fee_tier": 3000}]
    monkeypatch.setattr(wp, "maxfi_get_wallet_position_snapshot", lambda chain, wallet: snapshot)
    monkeypatch.setattr(wp, "maxfi_rpc_call", _fail_if_called)

    body = client_get_census(census_client, wp, "base", WALLET)
    assert body["resolution_counts"]["fetched_via_rpc"] == 0
    assert body["resolution_counts"]["served_from_table"] == 2
    symbols = {t["address"]: t["symbol"] for t in body["tokens"]}
    assert symbols[TOKEN_A] == "TKA"
    assert symbols[TOKEN_B] == "TKB"


def test_failed_resolution_stores_null_symbol_and_is_retried_next_run(monkeypatch, census_client):
    snapshot = [{"array_index": 0, "token_id": "1", "pool_address": "0xPOOL",
                 "token0_address": TOKEN_A, "token1_address": TOKEN_B, "fee_tier": 3000}]
    monkeypatch.setattr(wp, "maxfi_get_wallet_position_snapshot", lambda chain, wallet: snapshot)

    # First run: TOKEN_A's symbol() sub-call reverts (success=False).
    raw_fail = fake_aggregate3_raw([
        (True, _encode_uint_return(18)), (False, "0x"),
        (True, _encode_uint_return(6)), (True, _encode_string_return("TKB")),
    ])
    monkeypatch.setattr(wp, "maxfi_rpc_call", lambda chain, to, cd, timeout=None: raw_fail)

    body1 = client_get_census(census_client, wp, "base", WALLET)
    assert body1["resolution_counts"]["fetched_via_rpc"] == 2
    row = census_client.execute(
        "SELECT symbol FROM maxfi_token_symbols WHERE chain = 'base' AND address = ?", (TOKEN_A,)
    ).fetchone()
    assert row is not None and row["symbol"] is None  # attempted-and-failed, NOT omitted

    # Simulate a fresh worker process (in-process dict reset) and a healthy
    # RPC this time - TOKEN_A must be RE-ATTEMPTED (its table row has a NULL
    # symbol), while TOKEN_B - already resolved to "TKB" in the table from
    # run 1 - must NOT be re-fetched. Only TOKEN_A's two calls (decimals,
    # symbol) go out this time.
    monkeypatch.setattr(wp, "_maxfi_token_metadata_cache", {})
    raw_ok = fake_aggregate3_raw([
        (True, _encode_uint_return(18)), (True, _encode_string_return("TKA")),
    ])
    monkeypatch.setattr(wp, "maxfi_rpc_call", lambda chain, to, cd, timeout=None: raw_ok)

    body2 = client_get_census(census_client, wp, "base", WALLET)
    assert body2["resolution_counts"]["fetched_via_rpc"] == 1       # only TOKEN_A re-attempted
    assert body2["resolution_counts"]["served_from_table"] == 1     # TOKEN_B served from the table
    row2 = census_client.execute(
        "SELECT symbol FROM maxfi_token_symbols WHERE chain = 'base' AND address = ?", (TOKEN_A,)
    ).fetchone()
    assert row2["symbol"] == "TKA"  # upgraded in place


def test_positions_list_exposes_token_symbols_from_cache_with_no_rpc(monkeypatch, client, iv_db):
    _seed_position(iv_db, 60)  # chain='base', token0_address='0xT0', token1_address='0xT1'
    iv_db.execute(
        "INSERT INTO maxfi_token_symbols (chain, address, symbol, decimals, last_attempt_at) "
        "VALUES ('base', '0xt0', 'T0SYM', 18, '2026-08-30T00:00:00+00:00')"
    )
    iv_db.commit()
    monkeypatch.setattr(wp, "maxfi_rpc_call", _fail_if_called)

    r = client.get(f"/api/maxfi/positions/base/0xWALLET")
    assert r.status_code == 200
    row = [p for p in r.get_json() if p["id"] == 60][0]
    assert row["token0_symbol"] == "T0SYM"   # LOWER(p.token0_address)='0xt0' matched the cache row
    assert row["token1_symbol"] is None      # no cache row for '0xt1' -> unresolved, not an error


# ── Wallet-casing fix: LOWER() applied to BOTH sides of every comparison ────
#
# Neither the wallets store nor maxfi_positions.wallet is normalized on
# write - each keeps whatever casing appeared at write time (a human's
# Add-Wallet-form input; a scan's URL segment), and existing rows are never
# rewritten (rewriting would break the live checksummed
# 0xaB7A515c6e2Eea5140eD8A5b09A7D782F3B26743 wallet). So the fix is
# comparison-only: LOWER(<col>) = LOWER(?) everywhere a WHERE clause filters
# on wallet - never on write, never a backfill.

MIXED_CASE_WALLET = "0xaB7A515c6e2Eea5140eD8A5b09A7D782F3B26743"


def _seed_position_with_wallet(db, position_id, wallet, chain='base'):
    db.execute(
        """
        INSERT INTO maxfi_positions (
            id, chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, first_seen_block,
            last_scan_at, closed_at
        ) VALUES (?, ?, ?, ?, 0, '0xPOOL', '0xT0', '0xT1', 3000,
                  'open', '2026-01-01T00:00:00+00:00', 'chain', '1',
                  '2026-01-01T00:00:00+00:00', NULL)
        """,
        (position_id, chain, wallet, str(position_id)),
    )
    db.commit()


def test_positions_list_finds_mixedcase_stored_row_via_lowercase_url(client, iv_db):
    _seed_position_with_wallet(iv_db, 80, MIXED_CASE_WALLET)

    r = client.get(f"/api/maxfi/positions/base/{MIXED_CASE_WALLET.lower()}")

    assert r.status_code == 200
    ids = [p["id"] for p in r.get_json()]
    assert 80 in ids


def test_positions_list_finds_lowercase_stored_row_via_mixedcase_url(client, iv_db):
    _seed_position_with_wallet(iv_db, 81, MIXED_CASE_WALLET.lower())

    r = client.get(f"/api/maxfi/positions/base/{MIXED_CASE_WALLET}")

    assert r.status_code == 200
    ids = [p["id"] for p in r.get_json()]
    assert 81 in ids


def test_positions_list_for_a_genuinely_unknown_wallet_still_returns_empty(client, iv_db):
    """Guards against the broadened LOWER() predicate accidentally matching
    everything - a wallet with zero rows must still get zero rows back."""
    _seed_position_with_wallet(iv_db, 82, MIXED_CASE_WALLET)

    r = client.get("/api/maxfi/positions/base/0x" + "9" * 40)

    assert r.status_code == 200
    assert r.get_json() == []


def client_get_census(db_conn, wp_module, chain, wallet):
    """Small helper: the census fixtures above hand back the raw sqlite
    connection, not the Flask test client, so route calls in this section
    go through wp_module.app.test_client() directly rather than threading a
    second fixture parameter through every test."""
    c = wp_module.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    r = c.get(f"/api/maxfi/token-census/{chain}/{wallet}")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


# ── Block 2: maxfi_position_user_data / maxfi_pool_meta routes ──────────────
#
# Both tables are additive (42ea12b) and had no routes before this block.
# maxfi_position_user_data is position-scoped (closing value + note);
# maxfi_pool_meta is (chain, pool_address)-scoped, independent of any wallet
# or position. Both follow /initial-value's _MISSING-sentinel absent-means-
# unchanged / explicit-null-means-clear convention, but neither route
# deletes its row on an all-null result the way /initial-value does - see
# each route's own comment for why that's safe here.

def _seed_position_with_pool_address(db, position_id, pool_address, chain='base'):
    db.execute(
        """
        INSERT INTO maxfi_positions (
            id, chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, first_seen_block,
            last_scan_at, closed_at
        ) VALUES (?, ?, '0xWALLET', ?, 0, ?, '0xT0', '0xT1', 3000,
                  'open', '2026-01-01T00:00:00+00:00', 'chain', '1',
                  '2026-01-01T00:00:00+00:00', NULL)
        """,
        (position_id, chain, str(position_id), pool_address),
    )
    db.commit()


# ---- user-data route ----

def test_user_data_non_integer_position_id_is_400_invalid_position_id(client, iv_db):
    r = client.post("/api/maxfi/positions/not-an-int/user-data", json={"user_note": "x"})
    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidPositionId"


def test_user_data_unknown_position_id_is_400_position_not_found(client, iv_db):
    r = client.post("/api/maxfi/positions/999999/user-data", json={"user_note": "x"})
    assert r.status_code == 400
    assert r.get_json()["error"] == "PositionNotFound"


def test_user_data_both_fields_absent_is_400(client, iv_db):
    _seed_position(iv_db, 100)
    r = client.post("/api/maxfi/positions/100/user-data", json={})
    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidUserNote"


def test_user_data_closing_value_zero_is_accepted_and_stored(client, iv_db):
    """Deliberately different from /initial-value's <= 0 rejection - a
    position can genuinely drain to zero."""
    _seed_position(iv_db, 101)
    r = client.post("/api/maxfi/positions/101/user-data", json={"closing_value_usd": 0})
    assert r.status_code == 200
    body = r.get_json()
    assert body["closing_value_usd"] == 0
    row = iv_db.execute(
        "SELECT closing_value_usd FROM maxfi_position_user_data WHERE position_id = 101"
    ).fetchone()
    assert row["closing_value_usd"] == 0


def test_user_data_closing_value_negative_is_400(client, iv_db):
    _seed_position(iv_db, 102)
    r = client.post("/api/maxfi/positions/102/user-data", json={"closing_value_usd": -0.01})
    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidClosingValue"


@pytest.mark.parametrize("bool_value", [True, False])
def test_user_data_closing_value_boolean_is_400(client, iv_db, bool_value):
    """Mirrors test_booleans_are_rejected_and_false_does_not_clear above -
    bool is an int subclass in Python, so it must be rejected explicitly
    rather than silently accepted as 0/1."""
    _seed_position(iv_db, 103)
    r = client.post("/api/maxfi/positions/103/user-data", json={"closing_value_usd": bool_value})
    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidClosingValue"


@pytest.mark.parametrize("bad_value", [float('inf'), float('nan')])
def test_user_data_closing_value_non_finite_is_400(client, iv_db, bad_value):
    """Sent via a hand-serialized body rather than the json= kwarg: Python's
    json.dumps emits the non-standard Infinity/NaN tokens by default, and
    Flask's JSON provider (built on the stdlib json module) accepts them
    back on parse, so this exercises the route's real isfinite() check end
    to end rather than only validating in the test itself."""
    _seed_position(iv_db, 104)
    body = json.dumps({"closing_value_usd": bad_value})
    r = client.post(
        "/api/maxfi/positions/104/user-data", data=body, content_type="application/json"
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidClosingValue"


def test_user_data_note_over_2000_chars_is_400(client, iv_db):
    _seed_position(iv_db, 105)
    r = client.post("/api/maxfi/positions/105/user-data", json={"user_note": "x" * 2001})
    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidUserNote"


def test_user_data_empty_note_is_accepted_and_distinct_from_null(client, iv_db):
    _seed_position(iv_db, 106)
    r = client.post("/api/maxfi/positions/106/user-data", json={"user_note": ""})
    assert r.status_code == 200
    body = r.get_json()
    assert body["user_note"] == ""
    row = iv_db.execute(
        "SELECT user_note FROM maxfi_position_user_data WHERE position_id = 106"
    ).fetchone()
    assert row["user_note"] == ""


def test_user_data_setting_note_alone_preserves_existing_closing_value(client, iv_db):
    _seed_position(iv_db, 107)
    r1 = client.post("/api/maxfi/positions/107/user-data", json={"closing_value_usd": 42.5})
    assert r1.status_code == 200

    r2 = client.post("/api/maxfi/positions/107/user-data", json={"user_note": "hello"})
    assert r2.status_code == 200
    body = r2.get_json()
    assert body["closing_value_usd"] == 42.5
    assert body["user_note"] == "hello"


def test_user_data_setting_closing_value_alone_preserves_existing_note(client, iv_db):
    _seed_position(iv_db, 108)
    r1 = client.post("/api/maxfi/positions/108/user-data", json={"user_note": "keep me"})
    assert r1.status_code == 200

    r2 = client.post("/api/maxfi/positions/108/user-data", json={"closing_value_usd": 7.0})
    assert r2.status_code == 200
    body = r2.get_json()
    assert body["user_note"] == "keep me"
    assert body["closing_value_usd"] == 7.0


def test_user_data_explicit_null_clears_only_closing_value(client, iv_db):
    _seed_position(iv_db, 109)
    client.post("/api/maxfi/positions/109/user-data",
                json={"closing_value_usd": 10.0, "user_note": "note"})

    r = client.post("/api/maxfi/positions/109/user-data", json={"closing_value_usd": None})

    assert r.status_code == 200
    body = r.get_json()
    assert body["closing_value_usd"] is None
    assert body["user_note"] == "note"


def test_user_data_explicit_null_clears_only_note(client, iv_db):
    _seed_position(iv_db, 110)
    client.post("/api/maxfi/positions/110/user-data",
                json={"closing_value_usd": 10.0, "user_note": "note"})

    r = client.post("/api/maxfi/positions/110/user-data", json={"user_note": None})

    assert r.status_code == 200
    body = r.get_json()
    assert body["user_note"] is None
    assert body["closing_value_usd"] == 10.0


# ---- pool-meta route ----

@pytest.mark.parametrize("asset_class", ["crypto", "stock"])
def test_pool_meta_valid_asset_classes_accepted(client, iv_db, asset_class):
    r = client.post("/api/maxfi/pool-meta", json={
        "chain": "base", "pool_address": "0x" + "a" * 40, "asset_class": asset_class,
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body["asset_class"] == asset_class
    assert body["pool_address"] == "0x" + "a" * 40


@pytest.mark.parametrize("bad_class", ["c", "Crypto", "equity"])
def test_pool_meta_invalid_asset_class_strings_are_400(client, iv_db, bad_class):
    r = client.post("/api/maxfi/pool-meta", json={
        "chain": "base", "pool_address": "0x" + "b" * 40, "asset_class": bad_class,
    })
    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidAssetClass"


def test_pool_meta_absent_asset_class_is_400(client, iv_db):
    r = client.post("/api/maxfi/pool-meta", json={"chain": "base", "pool_address": "0x" + "c" * 40})
    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidAssetClass"


@pytest.mark.parametrize("bad_addr", ["not-an-address", "0x123", "", "0x" + "g" * 40])
def test_pool_meta_malformed_pool_address_is_400(client, iv_db, bad_addr):
    r = client.post("/api/maxfi/pool-meta", json={
        "chain": "base", "pool_address": bad_addr, "asset_class": "crypto",
    })
    assert r.status_code == 400
    assert r.get_json()["error"] == "InvalidPoolAddress"


def test_pool_meta_mixed_case_address_is_stored_lowercased(client, iv_db):
    mixed = "0x" + "AbCd" * 10
    assert len(mixed) == 42
    r = client.post("/api/maxfi/pool-meta", json={
        "chain": "base", "pool_address": mixed, "asset_class": "crypto",
    })
    assert r.status_code == 200
    assert r.get_json()["pool_address"] == mixed.lower()

    row = iv_db.execute(
        "SELECT pool_address FROM maxfi_pool_meta WHERE chain = 'base' AND pool_address = ?",
        (mixed.lower(),),
    ).fetchone()
    assert row is not None
    assert row["pool_address"] == mixed.lower()


def test_pool_meta_upsert_updates_in_place_leaving_one_row(client, iv_db):
    addr = "0x" + "d" * 40
    r1 = client.post("/api/maxfi/pool-meta", json={
        "chain": "base", "pool_address": addr, "asset_class": "crypto",
    })
    r2 = client.post("/api/maxfi/pool-meta", json={
        "chain": "base", "pool_address": addr, "asset_class": "stock",
    })
    assert r1.status_code == 200 and r2.status_code == 200

    rows = iv_db.execute(
        "SELECT asset_class FROM maxfi_pool_meta WHERE chain = 'base' AND pool_address = ?",
        (addr,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["asset_class"] == "stock"


# ---- positions list: new joined columns ----

def test_positions_list_new_columns_are_null_with_no_user_data_or_pool_meta(client, iv_db):
    _seed_position(iv_db, 120)

    r = client.get("/api/maxfi/positions/base/0xWALLET")

    assert r.status_code == 200
    row = next(p for p in r.get_json() if p["id"] == 120)
    assert row["closing_value_usd"] is None
    assert row["user_note"] is None
    assert row["asset_class"] is None


def test_positions_list_surfaces_written_user_data_and_pool_meta(client, iv_db):
    # _seed_position's hardcoded '0xPOOL' is not a real hex address and
    # would be rejected by the pool-meta route's own validation, so this
    # test seeds a position with a valid address instead.
    pool = "0x" + "e" * 40
    _seed_position_with_pool_address(iv_db, 121, pool)
    client.post("/api/maxfi/positions/121/user-data",
                json={"closing_value_usd": 88.0, "user_note": "sold"})
    r_meta = client.post("/api/maxfi/pool-meta", json={
        "chain": "base", "pool_address": pool, "asset_class": "crypto",
    })
    assert r_meta.status_code == 200

    r = client.get("/api/maxfi/positions/base/0xWALLET")

    assert r.status_code == 200
    row = next(p for p in r.get_json() if p["id"] == 121)
    assert row["closing_value_usd"] == 88.0
    assert row["user_note"] == "sold"
    assert row["asset_class"] == "crypto"


def test_positions_list_pool_meta_joins_across_stored_casing_mismatch(client, iv_db):
    """The single most important test in this block: maxfi_pool_meta stores
    pool_address already-lowercased (this block's writer); maxfi_positions
    does NOT normalize pool_address on write. The join's LOWER() must be on
    the maxfi_positions side only, or a mixed-case-stored position would
    never match its pool's asset_class."""
    mixed_pool = "0x" + "AbCdEf1234567890AbCdEf1234567890AbCdEf12"
    assert len(mixed_pool) == 42
    _seed_position_with_pool_address(iv_db, 122, mixed_pool)

    r = client.post("/api/maxfi/pool-meta", json={
        "chain": "base", "pool_address": mixed_pool, "asset_class": "stock",
    })
    assert r.status_code == 200
    assert r.get_json()["pool_address"] == mixed_pool.lower()

    r2 = client.get("/api/maxfi/positions/base/0xWALLET")
    assert r2.status_code == 200
    row = next(p for p in r2.get_json() if p["id"] == 122)
    assert row["asset_class"] == "stock"


# ── Scan route: wallet-casing resolution + per-(chain, wallet) lock ─────────
#
# No existing test file drove POST /api/maxfi/scan/<chain>/<wallet> over the
# Flask test client before this block - test_maxfi_orchestration.py exercises
# orch.run_scan_and_persist() directly against a bare sqlite3 connection, with
# no Flask app and no client fixture at all. This file already has the
# client/iv_db fixtures the route needs (a real get_connection() call and
# session auth), so the route-level tests below live here instead.
#
# wp.maxfi_run_scan_and_persist is monkeypatched in every test in this
# section - these tests are about the ROUTE's wallet-casing resolution and
# locking, not about scan-and-persist's own diff/write logic (already covered
# in test_maxfi_orchestration.py), and the real function makes RPC calls.

def _write_scan_wallet_config(monkeypatch, tmp_path, entries):
    path = tmp_path / "wallet_config.json"
    path.write_text(json.dumps(entries))
    monkeypatch.setattr(wp, "WALLET_CONFIG_FILE", str(path))


def _fake_run_scan_and_persist(calls):
    """Records (chain, wallet) it was actually called with and returns a
    minimal valid result shape with no ambiguous_flagged entries, so the
    route's auto-split branch (which needs its own separate connection and
    several more monkeypatches) never activates - out of scope here."""
    def _fake(conn, chain, wallet):
        calls.append({"chain": chain, "wallet": wallet})
        return {
            "chain": chain,
            "wallet": wallet,
            "captured_at_utc": "2026-01-01T00:00:00+00:00",
            "block_number": "1000",
            "written": {"matched": 0, "rebalanced": 0, "opened": 0, "closed": 0},
            "ambiguous_flagged": [],
            "snapshot": [],
        }
    return _fake


def test_scan_resolves_lowercase_input_to_checksummed_config_casing(client, iv_db, monkeypatch, tmp_path):
    checksummed = "0xaB7A515c6e2Eea5140eD8A5b09A7D782F3B26743"
    _write_scan_wallet_config(monkeypatch, tmp_path, {checksummed: {"label": "W1"}})
    calls = []
    monkeypatch.setattr(wp, "maxfi_run_scan_and_persist", _fake_run_scan_and_persist(calls))

    r = client.post(f"/api/maxfi/scan/base/{checksummed.lower()}")

    assert r.status_code == 200
    assert len(calls) == 1
    assert calls[0]["wallet"] == checksummed  # the CONFIG casing, not the lowercase URL input
    assert r.get_json()["wallet"] == checksummed


def test_scan_resolves_checksummed_input_to_lowercase_config_casing(client, iv_db, monkeypatch, tmp_path):
    """Wallet 2's real situation: a lowercase config entry. Proves resolution
    is per-wallet lookup, not normalization toward any single form - a
    checksummed request must come back OUT as lowercase here, the opposite
    direction from the test above."""
    lowercase_addr = "0x8fc433ca5117529f199e2ba07cf7edfefb5331ee"
    _write_scan_wallet_config(monkeypatch, tmp_path, {lowercase_addr: {"label": "W2"}})
    calls = []
    monkeypatch.setattr(wp, "maxfi_run_scan_and_persist", _fake_run_scan_and_persist(calls))

    r = client.post(f"/api/maxfi/scan/base/{lowercase_addr.upper().replace('0X', '0x')}")

    assert r.status_code == 200
    assert len(calls) == 1
    assert calls[0]["wallet"] == lowercase_addr


def test_scan_unknown_wallet_is_400_and_never_reaches_scan(client, iv_db, monkeypatch, tmp_path):
    _write_scan_wallet_config(monkeypatch, tmp_path, {"0x" + "9" * 40: {"label": "known"}})
    calls = []
    monkeypatch.setattr(wp, "maxfi_run_scan_and_persist", _fake_run_scan_and_persist(calls))

    r = client.post("/api/maxfi/scan/base/0x" + "8" * 40)

    assert r.status_code == 400
    assert r.get_json()["error"] == "UnknownWallet"
    assert calls == []  # the scan was never reached


def test_scan_same_wallet_concurrent_second_call_gets_409(client, iv_db, monkeypatch, tmp_path):
    addr = "0x" + "1" * 40
    _write_scan_wallet_config(monkeypatch, tmp_path, {addr: {"label": "w"}})
    calls = []
    monkeypatch.setattr(wp, "maxfi_run_scan_and_persist", _fake_run_scan_and_persist(calls))
    wp._maxfi_scan_locks.clear()

    lock = wp._get_maxfi_scan_lock("base", addr)
    assert lock.acquire(blocking=False)  # simulate a scan already in flight
    try:
        r = client.post(f"/api/maxfi/scan/base/{addr}")
        assert r.status_code == 409
        assert r.get_json()["error"] == "ScanInProgress"
        assert calls == []
    finally:
        lock.release()


def test_scan_different_wallets_same_chain_both_proceed(client, iv_db, monkeypatch, tmp_path):
    """The behaviour the lock narrowing exists to produce: a wallet selector
    plus a Scan button makes concurrent scans of two different wallets a
    reachable, legitimate state, and neither should be rejected."""
    addr_a = "0x" + "2" * 40
    addr_b = "0x" + "3" * 40
    _write_scan_wallet_config(monkeypatch, tmp_path, {addr_a: {"label": "a"}, addr_b: {"label": "b"}})
    calls = []
    monkeypatch.setattr(wp, "maxfi_run_scan_and_persist", _fake_run_scan_and_persist(calls))
    wp._maxfi_scan_locks.clear()

    lock_a = wp._get_maxfi_scan_lock("base", addr_a)
    assert lock_a.acquire(blocking=False)  # simulate wallet A's scan still in flight
    try:
        r = client.post(f"/api/maxfi/scan/base/{addr_b}")
        assert r.status_code == 200
        assert len(calls) == 1
        assert calls[0]["wallet"] == addr_b
    finally:
        lock_a.release()


def test_two_casings_of_same_wallet_resolve_to_one_lock_entry(monkeypatch, tmp_path):
    """Keying the lock dict on the raw incoming string (rather than the
    resolved casing) would let two casings of the same wallet each take
    their own Lock and defeat the guard for the exact wallet it protects.
    This asserts the fix directly: both casings resolve to the identical
    stored key, and that key maps to one Lock object."""
    checksummed = "0x" + "AbCd" * 10
    _write_scan_wallet_config(monkeypatch, tmp_path, {checksummed: {"label": "w"}})
    wp._maxfi_scan_locks.clear()

    resolved_from_lower = wp.resolve_wallet_casing(checksummed.lower())
    resolved_from_upper = wp.resolve_wallet_casing(checksummed.upper())
    assert resolved_from_lower == checksummed
    assert resolved_from_upper == checksummed

    lock1 = wp._get_maxfi_scan_lock("base", resolved_from_lower)
    lock2 = wp._get_maxfi_scan_lock("base", resolved_from_upper)
    assert lock1 is lock2
