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
