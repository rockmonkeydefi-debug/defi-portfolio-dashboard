"""Tests for the fail-soft multicall variant and the fast range-status
endpoint (maxfi_client.multicall3_soft / fetch_range_status,
GET /api/maxfi/range/<chain>/<wallet>).

Offline, synthetic fixtures only - no network calls. Follows
tests/test_maxfi_client.py's style for the client-level tests (hand-built
ABI words via mc.encode_uint256/encode_int24/encode_address, rpc_call
monkeypatched) and tests/test_maxfi_valuation_route.py's style for the
route-level tests (threading.Thread.start neutralized around the
web_portfolio import, get_password_hash monkeypatched, a shared-cache
sqlite URI standing in for the DB).
"""
import threading
import uuid

import pytest

import maxfi_client as mc

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import sqlite3
import maxfi_schema
import src.storage.portfolio_db as portfolio_db


# ── multicall3_soft ──────────────────────────────────────────────────────

_TARGET_A = "0x" + "a" * 40
_TARGET_B = "0x" + "b" * 40
_TARGET_C = "0x" + "c" * 40


def test_multicall3_soft_success(monkeypatch):
    calls = [(_TARGET_A, "0xcd01"), (_TARGET_B, "0xcd02")]
    monkeypatch.setattr(mc, "rpc_call", lambda chain, to, cd, timeout=None: "0xraw")
    monkeypatch.setattr(
        mc, "decode_aggregate3_result",
        lambda raw: [(True, "0xdataA"), (True, "0xdataB")],
    )
    results = mc.multicall3_soft("base", calls, chunk_size=10)
    assert results == [(True, "0xdataA"), (True, "0xdataB")]


def test_multicall3_soft_partial_failure_keeps_the_successes(monkeypatch):
    # The exact behaviour multicall3() lacks: one reverted sub-call must not
    # take the rest of the batch down with it.
    calls = [(_TARGET_A, "0xcd01"), (_TARGET_B, "0xcd02"), (_TARGET_C, "0xcd03")]
    monkeypatch.setattr(mc, "rpc_call", lambda chain, to, cd, timeout=None: "0xraw")
    monkeypatch.setattr(
        mc, "decode_aggregate3_result",
        lambda raw: [(True, "0xdataA"), (False, "0x"), (True, "0xdataC")],
    )
    results = mc.multicall3_soft("base", calls, chunk_size=10)
    assert results == [(True, "0xdataA"), (False, "0x"), (True, "0xdataC")]


def test_multicall3_soft_chunk_rpc_failure_marks_chunk_false_none(monkeypatch):
    calls = [(_TARGET_A, "0xcd01"), (_TARGET_B, "0xcd02")]

    def _raise(chain, to, cd, timeout=None):
        raise mc.MaxFiRpcError("network down")

    monkeypatch.setattr(mc, "rpc_call", _raise)
    # Must not propagate - a dead RPC degrades, it does not explode.
    results = mc.multicall3_soft("base", calls, chunk_size=10)
    assert results == [(False, None), (False, None)]


# ── fetch_range_status ───────────────────────────────────────────────────

_OWNER = "0x1234567890123456789012345678901234567890"
_VAULT = "0x9999999999999999999999999999999999999999"


def _vault_words(token_id, tick_lower, tick_upper, rebalance_delay=3600,
                  out_of_range_since=0, owner=_OWNER):
    return [
        mc.encode_uint256(token_id),           # tokenId
        "ab" * 32,                             # poolId
        mc.encode_address(owner),              # owner
        mc.encode_uint256(1130),               # rangeWidthBps
        mc.encode_int24(tick_lower),           # currentTickLower
        mc.encode_int24(tick_upper),           # currentTickUpper
        mc.encode_uint256(1),                  # autoSnuggleEnabled
        mc.encode_uint256(0),                  # autoCompoundEnabled
        mc.encode_uint256(rebalance_delay),    # rebalanceDelay
        mc.encode_uint256(out_of_range_since), # outOfRangeSince
        mc.encode_uint256(4),                  # totalRebalances
        mc.encode_uint256(1700000000),         # lastRebalanceTime
        mc.encode_uint256(1690000000),         # depositTimestamp
        mc.encode_uint256(123456),             # cumulativeFees0
        mc.encode_uint256(654321),             # cumulativeFees1
        mc.encode_uint256(999),                # cumulativeRewards
    ]


def _vault_raw(token_id, tick_lower, tick_upper, **kwargs):
    return "0x" + "".join(_vault_words(token_id, tick_lower, tick_upper, **kwargs))


def _slot0_words(tick, sqrt_price_x96=123456789):
    return [
        mc.encode_uint256(sqrt_price_x96),
        mc.encode_int24(tick),
        mc.encode_uint256(5),
        mc.encode_uint256(100),
        mc.encode_uint256(100),
        mc.encode_uint256(0),
        mc.encode_uint256(1),
    ]


def _slot0_raw(tick, **kwargs):
    return "0x" + "".join(_slot0_words(tick, **kwargs))


def _make_fake_multicall3_soft(vault_responses_by_token_id, slot0_responses_by_pool, call_log=None):
    """Distinguishes the vault batch from the slot0 batch by selector (every
    vault.positions() call shares the SAME target - the vault contract - so
    responses there must be keyed by the token_id encoded in the calldata,
    not by target; every slot0() call's target IS the distinct pool
    address, so those are keyed by target directly)."""
    def _fake(chain, calls, chunk_size=None):
        if call_log is not None:
            call_log.append(list(calls))
        out = []
        for target, cd in calls:
            selector = cd[:10]
            if selector == mc.SEL_POSITIONS:
                token_id = int(cd[10:], 16)
                out.append(vault_responses_by_token_id[token_id])
            elif selector == mc.SEL_POOL_SLOT0:
                out.append(slot0_responses_by_pool[target])
            else:
                raise AssertionError(f"unexpected selector {selector}")
        return out
    return _fake


def test_fetch_range_status_in_range_boundaries(monkeypatch):
    # Uniswap V3 half-open convention: [tick_lower, tick_upper).
    # current_tick == tick_lower -> IN. current_tick == tick_upper -> OUT.
    monkeypatch.setattr(mc, "get_vault", lambda chain: (_VAULT, []))
    positions = [
        {"token_id": "1", "pool_address": "0xPoolA"},
        {"token_id": "2", "pool_address": "0xPoolB"},
    ]
    vault_by_tid = {
        1: (True, _vault_raw(1, tick_lower=-100, tick_upper=100)),
        2: (True, _vault_raw(2, tick_lower=-100, tick_upper=100)),
    }
    slot0_by_pool = {
        "0xPoolA": (True, _slot0_raw(tick=-100)),  # == tick_lower -> IN
        "0xPoolB": (True, _slot0_raw(tick=100)),   # == tick_upper -> OUT
    }
    monkeypatch.setattr(
        mc, "multicall3_soft",
        _make_fake_multicall3_soft(vault_by_tid, slot0_by_pool),
    )

    results = mc.fetch_range_status("base", _OWNER, positions)
    by_tid = {r["token_id"]: r for r in results}

    assert by_tid["1"]["status"] == "ok"
    assert by_tid["1"]["in_range"] is True
    assert by_tid["2"]["status"] == "ok"
    assert by_tid["2"]["in_range"] is False


def test_fetch_range_status_isolates_one_bad_position(monkeypatch):
    monkeypatch.setattr(mc, "get_vault", lambda chain: (_VAULT, []))
    positions = [
        {"token_id": "1", "pool_address": "0xPoolA"},
        {"token_id": "2", "pool_address": "0xPoolA"},
        {"token_id": "3", "pool_address": "0xPoolA"},
    ]
    vault_by_tid = {
        1: (True, _vault_raw(1, tick_lower=-100, tick_upper=100)),
        2: (False, None),  # this position's vault call failed
        3: (True, _vault_raw(3, tick_lower=-100, tick_upper=100)),
    }
    slot0_by_pool = {"0xPoolA": (True, _slot0_raw(tick=0))}
    monkeypatch.setattr(
        mc, "multicall3_soft",
        _make_fake_multicall3_soft(vault_by_tid, slot0_by_pool),
    )

    results = mc.fetch_range_status("base", _OWNER, positions)
    by_tid = {r["token_id"]: r for r in results}

    assert by_tid["1"]["status"] == "ok"
    assert by_tid["3"]["status"] == "ok"
    assert by_tid["2"]["status"] == "unavailable"
    for key in ("tick_lower", "tick_upper", "current_tick", "width_pct",
                "in_range", "rebalance_delay", "out_of_range_since"):
        assert by_tid["2"][key] is None


def test_fetch_range_status_dedupes_pool_slot0_calls(monkeypatch):
    monkeypatch.setattr(mc, "get_vault", lambda chain: (_VAULT, []))
    positions = [
        {"token_id": "1", "pool_address": "0xPoolA"},
        {"token_id": "2", "pool_address": "0xPoolA"},  # same pool as position 1
    ]
    vault_by_tid = {
        1: (True, _vault_raw(1, tick_lower=-100, tick_upper=100)),
        2: (True, _vault_raw(2, tick_lower=-100, tick_upper=100)),
    }
    slot0_by_pool = {"0xPoolA": (True, _slot0_raw(tick=0))}
    call_log = []
    monkeypatch.setattr(
        mc, "multicall3_soft",
        _make_fake_multicall3_soft(vault_by_tid, slot0_by_pool, call_log=call_log),
    )

    mc.fetch_range_status("base", _OWNER, positions)

    assert len(call_log) == 2  # one vault batch, one slot0 batch
    vault_calls, slot0_calls = call_log
    assert len(vault_calls) == 2       # one per position
    assert len(slot0_calls) == 1       # one per DISTINCT pool, not per position
    assert slot0_calls[0][0] == "0xPoolA"


def test_fetch_range_status_vault_call_failure_reason(monkeypatch):
    monkeypatch.setattr(mc, "get_vault", lambda chain: (_VAULT, []))
    positions = [{"token_id": "5", "pool_address": "0xPoolA"}]
    vault_by_tid = {5: (False, None)}
    slot0_by_pool = {"0xPoolA": (True, _slot0_raw(tick=0))}
    monkeypatch.setattr(
        mc, "multicall3_soft",
        _make_fake_multicall3_soft(vault_by_tid, slot0_by_pool),
    )

    results = mc.fetch_range_status("base", _OWNER, positions)

    assert results[0]["status"] == "unavailable"
    assert results[0]["reason"] == "vault_call_failed"


def test_fetch_range_status_vault_decode_failure_reason(monkeypatch):
    monkeypatch.setattr(mc, "get_vault", lambda chain: (_VAULT, []))
    positions = [{"token_id": "4", "pool_address": "0xPoolA"}]
    # Truncated word count (15 instead of 16) - the call itself succeeded,
    # but decode_vault_position raises on the short payload.
    bad_raw = "0x" + "".join(_vault_words(4, tick_lower=-100, tick_upper=100)[:15])
    vault_by_tid = {4: (True, bad_raw)}
    slot0_by_pool = {"0xPoolA": (True, _slot0_raw(tick=0))}
    monkeypatch.setattr(
        mc, "multicall3_soft",
        _make_fake_multicall3_soft(vault_by_tid, slot0_by_pool),
    )

    results = mc.fetch_range_status("base", _OWNER, positions)

    assert results[0]["status"] == "unavailable"
    assert results[0]["reason"] == "vault_decode_failed"


def test_fetch_range_status_vault_decode_failure_reason_detail(monkeypatch):
    monkeypatch.setattr(mc, "get_vault", lambda chain: (_VAULT, []))
    positions = [{"token_id": "4", "pool_address": "0xPoolA"}]
    # Truncated word count (15 instead of 16) - the call itself succeeded,
    # but decode_vault_position raises on the short payload.
    bad_raw = "0x" + "".join(_vault_words(4, tick_lower=-100, tick_upper=100)[:15])
    vault_by_tid = {4: (True, bad_raw)}
    slot0_by_pool = {"0xPoolA": (True, _slot0_raw(tick=0))}
    monkeypatch.setattr(
        mc, "multicall3_soft",
        _make_fake_multicall3_soft(vault_by_tid, slot0_by_pool),
    )

    results = mc.fetch_range_status("base", _OWNER, positions)

    assert results[0]["reason"] == "vault_decode_failed"
    assert results[0]["reason_detail"].startswith("MaxFiDecodeError:")
    assert "expected at least 16" in results[0]["reason_detail"]
    assert len(results[0]["reason_detail"]) <= 200


def test_fetch_range_status_pool_call_failure_reason(monkeypatch):
    monkeypatch.setattr(mc, "get_vault", lambda chain: (_VAULT, []))
    positions = [{"token_id": "6", "pool_address": "0xPoolA"}]
    vault_by_tid = {6: (True, _vault_raw(6, tick_lower=-100, tick_upper=100))}
    slot0_by_pool = {"0xPoolA": (False, None)}
    monkeypatch.setattr(
        mc, "multicall3_soft",
        _make_fake_multicall3_soft(vault_by_tid, slot0_by_pool),
    )

    results = mc.fetch_range_status("base", _OWNER, positions)

    assert results[0]["status"] == "unavailable"
    assert results[0]["reason"] == "pool_call_failed"


def test_fetch_range_status_both_fail_vault_reason_wins(monkeypatch):
    # Vault call is the per-position signal; pool call is shared across
    # every position on that pool. When both fail, the vault reason wins.
    monkeypatch.setattr(mc, "get_vault", lambda chain: (_VAULT, []))
    positions = [{"token_id": "7", "pool_address": "0xPoolA"}]
    vault_by_tid = {7: (False, None)}
    slot0_by_pool = {"0xPoolA": (False, None)}
    monkeypatch.setattr(
        mc, "multicall3_soft",
        _make_fake_multicall3_soft(vault_by_tid, slot0_by_pool),
    )

    results = mc.fetch_range_status("base", _OWNER, positions)

    assert results[0]["status"] == "unavailable"
    assert results[0]["reason"] == "vault_call_failed"


def test_fetch_range_status_ok_position_has_null_reason_and_range_width_bps(monkeypatch):
    monkeypatch.setattr(mc, "get_vault", lambda chain: (_VAULT, []))
    positions = [{"token_id": "8", "pool_address": "0xPoolA"}]
    vault_by_tid = {8: (True, _vault_raw(8, tick_lower=-100, tick_upper=100))}
    slot0_by_pool = {"0xPoolA": (True, _slot0_raw(tick=0))}
    monkeypatch.setattr(
        mc, "multicall3_soft",
        _make_fake_multicall3_soft(vault_by_tid, slot0_by_pool),
    )

    results = mc.fetch_range_status("base", _OWNER, positions)

    assert results[0]["status"] == "ok"
    assert results[0]["reason"] is None
    # _vault_words hardcodes rangeWidthBps=1130.
    assert results[0]["range_width_bps"] == "1130"


def test_fetch_range_status_identical_key_set_ok_and_unavailable(monkeypatch):
    # The contract the frontend will rely on: every returned dict, ok or
    # unavailable, carries the same key set.
    monkeypatch.setattr(mc, "get_vault", lambda chain: (_VAULT, []))
    positions = [
        {"token_id": "9", "pool_address": "0xPoolA"},
        {"token_id": "10", "pool_address": "0xPoolA"},
    ]
    vault_by_tid = {
        9: (True, _vault_raw(9, tick_lower=-100, tick_upper=100)),
        10: (False, None),
    }
    slot0_by_pool = {"0xPoolA": (True, _slot0_raw(tick=0))}
    monkeypatch.setattr(
        mc, "multicall3_soft",
        _make_fake_multicall3_soft(vault_by_tid, slot0_by_pool),
    )

    results = mc.fetch_range_status("base", _OWNER, positions)
    by_tid = {r["token_id"]: r for r in results}

    assert by_tid["9"]["status"] == "ok"
    assert by_tid["10"]["status"] == "unavailable"
    key_sets = [set(r.keys()) for r in results]
    assert key_sets[0] == key_sets[1]


def test_range_percent_is_decimals_independent():
    # This is the test that justifies not fetching real ERC20 decimals for
    # width_pct: the ratio price_upper/price_lower is scaled identically by
    # 10**(decimals0-decimals1) on both sides, so it cancels.
    a, b = -199240, -198110
    assert mc.range_percent(a, b, 18, 18) == pytest.approx(mc.range_percent(a, b, 18, 6))


# ── Route: GET /api/maxfi/range/<chain>/<wallet> ─────────────────────────

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


@pytest.fixture
def range_db(monkeypatch):
    uri = f"file:maxfi_range_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
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


def _seed_open_position(db, position_id, token_id, pool_address, chain="base", wallet="0xWALLET"):
    db.execute(
        """
        INSERT INTO maxfi_positions (
            id, chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, first_seen_block,
            last_scan_at, closed_at
        ) VALUES (?, ?, ?, ?, 0, ?, '0xT0', '0xT1', 3000,
                  'open', '2026-01-01T00:00:00+00:00', 'chain', '1',
                  '2026-01-01T00:00:00+00:00', NULL)
        """,
        (position_id, chain, wallet, token_id, pool_address),
    )
    db.commit()


def test_range_route_bad_chain_is_400(client, range_db):
    r = client.get("/api/maxfi/range/nonesuch/0xWALLET")
    assert r.status_code == 400
    body = r.get_json()
    assert body["error"] == "InvalidChain"


def test_range_route_zero_open_positions_makes_no_rpc_call(client, range_db, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("fetch_range_status must not be called with zero open positions")
    monkeypatch.setattr(wp, "maxfi_fetch_range_status", _boom)

    r = client.get("/api/maxfi/range/base/0xWALLET")
    assert r.status_code == 200
    assert r.get_json() == {"positions": []}


def test_range_route_client_exception_is_200_not_500(client, range_db, monkeypatch):
    _seed_open_position(range_db, 1, "1", "0xPOOL")

    def _raise(chain, wallet, positions):
        raise mc.MaxFiRpcError("rpc down")
    monkeypatch.setattr(wp, "maxfi_fetch_range_status", _raise)

    r = client.get("/api/maxfi/range/base/0xWALLET")
    assert r.status_code == 200
    body = r.get_json()
    assert body["positions"] == []
    assert body["error"] == "RpcUnavailable"
    assert "rpc down" in body["detail"]
