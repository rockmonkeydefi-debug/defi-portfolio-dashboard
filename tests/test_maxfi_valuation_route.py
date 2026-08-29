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
