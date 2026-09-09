"""Route-level tests for LP Advisor Phase B, commit 3 (B3): POST
/api/maxfi/token-daily-refresh/<chain> - builds a worklist of eligible
volatile tokens (held tokens always eligible; non-held tokens gated by
their deepest catalogue pool's maxfi_pool_metrics.liquidity_usd), fetches
GeckoTerminal day candles per token, and writes bounded daily-close rows
into maxfi_token_daily. Same client/monkeypatch fixture pattern as
tests/test_maxfi_metrics_refresh.py; same shared-cache sqlite URI pattern
as tests/test_maxfi_valuation_route.py:308.

No network - maxfi_history.fetch_pool_ohlcv is monkeypatched;
resolve_token_side is the real pure function.
"""
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import maxfi_history
import maxfi_schema
import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

WALLET = "0x" + "c" * 40
TOKEN_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
TOKEN_B = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
TOKEN_C = "0xcccccccccccccccccccccccccccccccccccccccc"
# A quote-side token for the hybrid-orientation tests below - its pool's
# first (un-oriented) fetch_pool_ohlcv call resolves it as GT's "quote"
# side, requiring a second, correctly-oriented call before any row is
# ever written for it.
TOKEN_Q = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
# The base-chain ETH anchor address (MAXFI_ANCHOR_REGISTRY_DEFAULTS) - used
# as the "other side" of every seeded pool so it never shows up as its own
# extra worklist entry (it's always excluded via excluded_anchor instead).
QUOTE = "0x4200000000000000000000000000000000000006"
POOL_A = "0xpoola"
POOL_B = "0xpoolb"
POOL_C = "0xpoolc"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


@pytest.fixture
def daily_db(monkeypatch):
    uri = f"file:maxfi_token_daily_refresh_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
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


def _seed_catalogue_pool(db, chain, pool_address, token0, token1,
                          sym0="TOK0", sym1="TOK1", ts="2026-01-01T00:00:00+00:00"):
    db.execute(
        """
        INSERT INTO maxfi_catalogue_pools (
          chain, pool_address, token0_address, token1_address,
          token0_symbol, token1_symbol, fee_tier, position_count,
          first_seen_at, last_seen_at, last_enumerated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 3000, 1, ?, ?, ?)
        """,
        (chain, pool_address, token0, token1, sym0, sym1, ts, ts, ts),
    )
    db.commit()


def _seed_metrics(db, chain, pool_address, liquidity_usd, ts="2026-01-01T00:00:00+00:00"):
    db.execute(
        """
        INSERT INTO maxfi_pool_metrics (
          chain, pool_address, price_usd, liquidity_usd, volume_h24,
          volume_h6, volume_h1, price_change_h24, fetched_at
        ) VALUES (?, ?, 1.0, ?, 100.0, 10.0, 1.0, 0.5, ?)
        """,
        (chain, pool_address, liquidity_usd, ts),
    )
    db.commit()


def _seed_position(db, position_id, chain, pool_address, token0, token1,
                    status="open", wallet=WALLET):
    db.execute(
        """
        INSERT INTO maxfi_positions (
            id, chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, last_scan_at
        ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, 3000, ?,
                  '2026-01-01T00:00:00+00:00', 'chain', '2026-01-01T00:00:00+00:00')
        """,
        (position_id, chain, wallet, str(position_id), pool_address, token0, token1, status),
    )
    db.commit()


def _seed_token_daily(db, chain, address, date, close_usd=1.0,
                       source_pool_address="0xpool", fetched_at="2020-01-01T00:00:00+00:00"):
    db.execute(
        """
        INSERT INTO maxfi_token_daily (
          chain, address, date, close_usd, source_pool_address, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (chain, address, date, close_usd, source_pool_address, fetched_at),
    )
    db.commit()


def _daily_rows(db, chain="base", address=None):
    q = "SELECT * FROM maxfi_token_daily WHERE chain = ?"
    params = [chain]
    if address:
        q += " AND address = ?"
        params.append(address)
    return [dict(row) for row in db.execute(q, params).fetchall()]


def _candles(dates_closes):
    """dates_closes: list of (date_str, close). Builds [ts, o, h, l, c, v] rows."""
    out = []
    for date_str, close in dates_closes:
        ts = int(datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc).timestamp())
        out.append([ts, close, close, close, close, 1000.0])
    return out


def _page(base_address, quote_address, dates_closes):
    return {
        "candles": _candles(dates_closes),
        "base_address": base_address.lower(),
        "quote_address": quote_address.lower(),
    }


# ── held token, deepest pool chosen ─────────────────────────────────────

def test_held_token_deepest_pool_chosen_and_rows_lowercased(client, daily_db, monkeypatch):
    _seed_catalogue_pool(daily_db, "base", POOL_A, TOKEN_A, QUOTE)
    _seed_catalogue_pool(daily_db, "base", POOL_B, TOKEN_A, QUOTE)
    _seed_metrics(daily_db, "base", POOL_A, liquidity_usd=5000.0)
    _seed_metrics(daily_db, "base", POOL_B, liquidity_usd=50000.0)
    _seed_position(daily_db, 1, "base", POOL_A, TOKEN_A.upper(), QUOTE)

    calls = []

    def _fake_fetch(network, pool_address, timeframe, **kwargs):
        calls.append((network, pool_address, timeframe, kwargs))
        return _page(TOKEN_A, QUOTE, [("2026-09-01", 1.5), ("2026-09-02", 1.6)])
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", _fake_fetch)

    r = client.post("/api/maxfi/token-daily-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    # held_tokens counts every token appearing in an open position - TOKEN_A
    # AND its anchor pairing (QUOTE), which is filtered out separately via
    # excluded_anchor rather than being excluded from this descriptive count.
    assert body["held_tokens"] == 2
    assert body["attempted"] == 1
    assert calls[0][1] == POOL_B  # deepest pool (higher liquidity) chosen

    rows = _daily_rows(daily_db, "base", TOKEN_A.lower())
    assert len(rows) == 2
    for row in rows:
        assert row["address"] == TOKEN_A.lower()
        assert row["source_pool_address"] == POOL_B.lower()
        assert row["fetched_at"] == body["run_at"]


# ── non-held below floor ─────────────────────────────────────────────────

def test_non_held_token_below_floor_excluded_no_gt_call(client, daily_db, monkeypatch):
    _seed_catalogue_pool(daily_db, "base", POOL_A, TOKEN_A, QUOTE)
    _seed_metrics(daily_db, "base", POOL_A, liquidity_usd=100.0)  # below default 10000 floor

    def _boom(*a, **k):
        raise AssertionError("must not fetch a below-floor non-held token")
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", _boom)

    r = client.post("/api/maxfi/token-daily-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["excluded_below_floor"] == 1
    assert body["attempted"] == 0
    assert _daily_rows(daily_db, "base") == []


# ── non-held above floor ─────────────────────────────────────────────────

def test_non_held_token_above_floor_attempted_and_written(client, daily_db, monkeypatch):
    _seed_catalogue_pool(daily_db, "base", POOL_A, TOKEN_A, QUOTE)
    _seed_metrics(daily_db, "base", POOL_A, liquidity_usd=20000.0)

    monkeypatch.setattr(
        maxfi_history, "fetch_pool_ohlcv",
        lambda network, pool, timeframe, **kw: _page(TOKEN_A, QUOTE, [("2026-09-01", 2.0)]),
    )

    r = client.post("/api/maxfi/token-daily-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["attempted"] == 1
    assert body["results"][0]["status"] == "written"
    assert body["results"][0]["rows_written"] == 1
    assert len(_daily_rows(daily_db, "base", TOKEN_A.lower())) == 1


# ── non-held with no metrics row ─────────────────────────────────────────

def test_non_held_token_no_metrics_row_excluded_no_liquidity_data(client, daily_db, monkeypatch):
    _seed_catalogue_pool(daily_db, "base", POOL_A, TOKEN_A, QUOTE)
    # No maxfi_pool_metrics row seeded at all for POOL_A.

    def _boom(*a, **k):
        raise AssertionError("must not fetch a token with no liquidity data")
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", _boom)

    r = client.post("/api/maxfi/token-daily-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["excluded_no_liquidity_data"] == 1
    assert body["attempted"] == 0


# ── anchor exclusion ──────────────────────────────────────────────────────

def test_anchor_token_excluded_no_gt_call(client, daily_db, monkeypatch):
    anchor_address = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"  # base:USDC default anchor
    _seed_catalogue_pool(daily_db, "base", POOL_A, anchor_address, QUOTE)
    _seed_metrics(daily_db, "base", POOL_A, liquidity_usd=999999.0)
    _seed_position(daily_db, 1, "base", POOL_A, anchor_address, QUOTE)  # even held, still excluded

    def _boom(*a, **k):
        raise AssertionError("must not fetch an anchor token")
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", _boom)

    r = client.post("/api/maxfi/token-daily-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["excluded_anchor"] >= 1
    assert body["attempted"] == 0


# ── today-row drop-out ────────────────────────────────────────────────────

def test_token_daily_today_row_drops_out_of_worklist(client, daily_db, monkeypatch):
    _seed_catalogue_pool(daily_db, "base", POOL_A, TOKEN_A, QUOTE)
    _seed_metrics(daily_db, "base", POOL_A, liquidity_usd=20000.0)
    today = datetime.now(timezone.utc).date().isoformat()
    _seed_token_daily(daily_db, "base", TOKEN_A.lower(), today, close_usd=1.23)

    def _boom(*a, **k):
        raise AssertionError("must not fetch a token already current for today")
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", _boom)

    r = client.post("/api/maxfi/token-daily-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["already_current_today"] == 1
    assert body["attempted"] == 0


# ── prune bound in same transaction ──────────────────────────────────────

def test_token_daily_prune_bounded_in_same_transaction(client, daily_db, monkeypatch):
    _seed_catalogue_pool(daily_db, "base", POOL_A, TOKEN_A, QUOTE)
    _seed_metrics(daily_db, "base", POOL_A, liquidity_usd=20000.0)

    # Pre-seed 5 old rows for this token, well before the fetched range.
    for i in range(5):
        old_date = (datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)).date().isoformat()
        _seed_token_daily(daily_db, "base", TOKEN_A.lower(), old_date, close_usd=0.5)

    # Fetch returns more than MAXFI_TOKEN_DAILY_MAX_ROWS (35) distinct dates.
    base_date = datetime(2026, 6, 1, tzinfo=timezone.utc)
    dates_closes = [
        ((base_date + timedelta(days=i)).date().isoformat(), 1.0 + i)
        for i in range(40)
    ]
    monkeypatch.setattr(
        maxfi_history, "fetch_pool_ohlcv",
        lambda network, pool, timeframe, **kw: _page(TOKEN_A, QUOTE, dates_closes),
    )

    r = client.post("/api/maxfi/token-daily-refresh/base")
    assert r.status_code == 200

    rows = _daily_rows(daily_db, "base", TOKEN_A.lower())
    assert len(rows) == maxfi_schema.MAXFI_TOKEN_DAILY_MAX_ROWS
    kept_dates = sorted(row["date"] for row in rows)
    expected_dates = sorted(d for d, _ in dates_closes)[-maxfi_schema.MAXFI_TOKEN_DAILY_MAX_ROWS:]
    assert kept_dates == expected_dates
    # None of the pre-seeded 2025 rows survive.
    assert all(not d.startswith("2025") for d in kept_dates)


# ── hybrid orientation: base-side (1 call) vs quote-side (2 calls) ──────

def test_token_daily_base_side_uses_single_call(client, daily_db, monkeypatch):
    _seed_catalogue_pool(daily_db, "base", POOL_A, TOKEN_A, QUOTE)
    _seed_position(daily_db, 1, "base", POOL_A, TOKEN_A.upper(), QUOTE)

    calls = []

    def _fake_fetch(network, pool, timeframe, **kw):
        calls.append(kw.get("token"))
        return _page(TOKEN_A, QUOTE, [("2026-09-01", 3.0)])
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", _fake_fetch)

    r = client.post("/api/maxfi/token-daily-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert calls == [None]  # exactly one call; no token= kwarg passed
    result = body["results"][0]
    assert result["side"] == "base"
    assert result["gt_calls"] == 1
    assert result["status"] == "written"
    assert len(_daily_rows(daily_db, "base", TOKEN_A.lower())) == 1


def test_token_daily_quote_side_uses_oriented_second_call(client, daily_db, monkeypatch):
    _seed_catalogue_pool(daily_db, "base", POOL_A, TOKEN_Q, QUOTE)
    _seed_position(daily_db, 1, "base", POOL_A, TOKEN_Q.upper(), QUOTE)

    calls = []

    def _fake_fetch(network, pool, timeframe, **kw):
        calls.append(kw.get("token"))
        if kw.get("token") == "quote":
            return _page(QUOTE, TOKEN_Q, [("2026-09-01", 9.0)])  # Y - correctly oriented
        return _page(QUOTE, TOKEN_Q, [("2026-09-01", 1.0)])  # X - GT's default (wrong) orientation
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", _fake_fetch)

    r = client.post("/api/maxfi/token-daily-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert calls == [None, "quote"]
    result = body["results"][0]
    assert result["side"] == "quote"
    assert result["gt_calls"] == 2
    assert result["status"] == "written"

    rows = _daily_rows(daily_db, "base", TOKEN_Q.lower())
    assert len(rows) == 1
    assert rows[0]["close_usd"] == 9.0  # Y, never X


def test_token_daily_quote_side_deferred_when_budget_cannot_cover_oriented_call(client, daily_db, monkeypatch):
    _seed_catalogue_pool(daily_db, "base", POOL_A, TOKEN_Q, QUOTE)
    _seed_position(daily_db, 1, "base", POOL_A, TOKEN_Q.upper(), QUOTE)

    monkeypatch.setattr(maxfi_history, "GT_CALL_BUDGET_PER_RUN", 1)

    def _boom_if_second(network, pool, timeframe, **kw):
        if kw.get("token") == "quote":
            raise AssertionError("must not make the second call when budget can't cover it")
        return _page(QUOTE, TOKEN_Q, [("2026-09-01", 1.0)])
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", _boom_if_second)

    r = client.post("/api/maxfi/token-daily-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["gt_calls_used"] == 1  # the already-spent first call is not refunded
    assert body["deferred_budget"] == 1
    assert body["attempted"] == 0
    assert len(body["results"]) == 0
    assert _daily_rows(daily_db, "base", TOKEN_Q.lower()) == []


def test_mixed_budget_base_and_quote_side_both_written(client, daily_db, monkeypatch):
    _seed_catalogue_pool(daily_db, "base", POOL_A, TOKEN_A, QUOTE)
    _seed_catalogue_pool(daily_db, "base", POOL_B, TOKEN_Q, QUOTE)
    _seed_position(daily_db, 1, "base", POOL_A, TOKEN_A.upper(), QUOTE)
    _seed_position(daily_db, 2, "base", POOL_B, TOKEN_Q.upper(), QUOTE)

    monkeypatch.setattr(maxfi_history, "GT_CALL_BUDGET_PER_RUN", 3)

    def _fake_fetch(network, pool, timeframe, **kw):
        if pool == POOL_A:
            return _page(TOKEN_A, QUOTE, [("2026-09-01", 1.0)])
        if kw.get("token") == "quote":
            return _page(QUOTE, TOKEN_Q, [("2026-09-01", 9.0)])
        return _page(QUOTE, TOKEN_Q, [("2026-09-01", 1.0)])
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", _fake_fetch)

    r = client.post("/api/maxfi/token-daily-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["gt_calls_used"] == 3  # 1 (base-side) + 2 (quote-side)
    assert body["attempted"] == 2
    assert body["deferred_budget"] == 0

    statuses = {res["address"]: res["status"] for res in body["results"]}
    assert statuses[TOKEN_A.lower()] == "written"
    assert statuses[TOKEN_Q.lower()] == "written"

    quote_rows = _daily_rows(daily_db, "base", TOKEN_Q.lower())
    assert len(quote_rows) == 1
    assert quote_rows[0]["close_usd"] == 9.0


def test_rate_limit_on_second_call_aborts_but_keeps_earlier_commit(client, daily_db, monkeypatch):
    _seed_catalogue_pool(daily_db, "base", POOL_A, TOKEN_A, QUOTE)
    _seed_catalogue_pool(daily_db, "base", POOL_B, TOKEN_Q, QUOTE)
    _seed_catalogue_pool(daily_db, "base", POOL_C, TOKEN_C, QUOTE)
    # Descending liquidity forces worklist order: TOKEN_A, TOKEN_Q, TOKEN_C.
    _seed_metrics(daily_db, "base", POOL_A, liquidity_usd=300.0)
    _seed_metrics(daily_db, "base", POOL_B, liquidity_usd=200.0)
    _seed_metrics(daily_db, "base", POOL_C, liquidity_usd=100.0)
    _seed_position(daily_db, 1, "base", POOL_A, TOKEN_A.upper(), QUOTE)
    _seed_position(daily_db, 2, "base", POOL_B, TOKEN_Q.upper(), QUOTE)
    _seed_position(daily_db, 3, "base", POOL_C, TOKEN_C.upper(), QUOTE)

    def _fake_fetch(network, pool, timeframe, **kw):
        if pool == POOL_A:
            return _page(TOKEN_A, QUOTE, [("2026-09-01", 1.0)])
        if pool == POOL_B:
            if kw.get("token") == "quote":
                raise maxfi_history.GTRateLimitError("simulated 429 on oriented call")
            return _page(QUOTE, TOKEN_Q, [("2026-09-01", 1.0)])  # resolves side="quote"
        raise AssertionError("third token must not be fetched after a rate limit")
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", _fake_fetch)

    r = client.post("/api/maxfi/token-daily-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["aborted_rate_limited"] is True
    assert len(_daily_rows(daily_db, "base", TOKEN_A.lower())) == 1
    assert _daily_rows(daily_db, "base", TOKEN_Q.lower()) == []
    assert body["deferred_budget"] == 1  # third token

    results_by_addr = {res["address"]: res for res in body["results"]}
    assert results_by_addr[TOKEN_A.lower()]["status"] == "written"
    assert results_by_addr[TOKEN_Q.lower()]["status"] == "error"
    assert results_by_addr[TOKEN_Q.lower()]["gt_calls"] == 2
    assert results_by_addr[TOKEN_Q.lower()]["side"] == "quote"


# ── budget deferral ───────────────────────────────────────────────────────

def test_budget_deferral_second_token_deferred(client, daily_db, monkeypatch):
    _seed_catalogue_pool(daily_db, "base", POOL_A, TOKEN_A, QUOTE)
    _seed_catalogue_pool(daily_db, "base", POOL_B, TOKEN_B, QUOTE)
    _seed_position(daily_db, 1, "base", POOL_A, TOKEN_A.upper(), QUOTE)
    _seed_position(daily_db, 2, "base", POOL_B, TOKEN_B.upper(), QUOTE)

    monkeypatch.setattr(maxfi_history, "GT_CALL_BUDGET_PER_RUN", 1)
    monkeypatch.setattr(
        maxfi_history, "fetch_pool_ohlcv",
        lambda network, pool, timeframe, **kw: _page(TOKEN_A, QUOTE, [("2026-09-01", 1.0)])
        if pool == POOL_A else _page(TOKEN_B, QUOTE, [("2026-09-01", 2.0)]),
    )

    r = client.post("/api/maxfi/token-daily-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["attempted"] == 1
    assert body["deferred_budget"] == 1
    assert body["gt_calls_used"] == 1
    assert body["gt_call_budget"] == 1
    assert len(body["results"]) == 1


# ── rate limit abort ───────────────────────────────────────────────────────

def test_rate_limit_aborts_run_but_keeps_earlier_commits(client, daily_db, monkeypatch):
    _seed_catalogue_pool(daily_db, "base", POOL_A, TOKEN_A, QUOTE)
    _seed_catalogue_pool(daily_db, "base", POOL_B, TOKEN_B, QUOTE)
    _seed_catalogue_pool(daily_db, "base", POOL_C, TOKEN_C, QUOTE)
    _seed_position(daily_db, 1, "base", POOL_A, TOKEN_A.upper(), QUOTE)
    _seed_position(daily_db, 2, "base", POOL_B, TOKEN_B.upper(), QUOTE)
    _seed_position(daily_db, 3, "base", POOL_C, TOKEN_C.upper(), QUOTE)

    def _fake_fetch(network, pool, timeframe, **kw):
        if pool == POOL_A:
            return _page(TOKEN_A, QUOTE, [("2026-09-01", 1.0)])
        if pool == POOL_B:
            raise maxfi_history.GTRateLimitError("simulated 429")
        raise AssertionError("third token must not be fetched after a rate limit")
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", _fake_fetch)

    r = client.post("/api/maxfi/token-daily-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    assert body["aborted_rate_limited"] is True
    assert len(_daily_rows(daily_db, "base", TOKEN_A.lower())) == 1
    assert body["deferred_budget"] == 1
    statuses = {res["address"]: res["status"] for res in body["results"]}
    assert statuses[TOKEN_A.lower()] == "written"
    assert statuses[TOKEN_B.lower()] == "error"


# ── side_unresolved ────────────────────────────────────────────────────────

def test_side_unresolved_per_token_error_run_continues(client, daily_db, monkeypatch):
    _seed_catalogue_pool(daily_db, "base", POOL_A, TOKEN_A, QUOTE)
    _seed_catalogue_pool(daily_db, "base", POOL_B, TOKEN_B, QUOTE)
    _seed_position(daily_db, 1, "base", POOL_A, TOKEN_A.upper(), QUOTE)
    _seed_position(daily_db, 2, "base", POOL_B, TOKEN_B.upper(), QUOTE)

    def _fake_fetch(network, pool, timeframe, **kw):
        if pool == POOL_A:
            # base/quote addresses match NEITHER token0 nor TOKEN_A.
            return _page("0x" + "9" * 40, "0x" + "8" * 40, [("2026-09-01", 1.0)])
        return _page(TOKEN_B, QUOTE, [("2026-09-01", 2.0)])
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", _fake_fetch)

    r = client.post("/api/maxfi/token-daily-refresh/base")
    assert r.status_code == 200
    body = r.get_json()

    results = {res["address"]: res for res in body["results"]}
    assert results[TOKEN_A.lower()]["status"] == "error"
    assert results[TOKEN_A.lower()]["reason"] == "side_unresolved"
    assert results[TOKEN_B.lower()]["status"] == "written"
    assert _daily_rows(daily_db, "base", TOKEN_A.lower()) == []


# ── dry_run ──────────────────────────────────────────────────────────────

def test_dry_run_true_fetches_but_writes_nothing(client, daily_db, monkeypatch):
    _seed_catalogue_pool(daily_db, "base", POOL_A, TOKEN_A, QUOTE)
    _seed_position(daily_db, 1, "base", POOL_A, TOKEN_A.upper(), QUOTE)

    called = {"count": 0}

    def _fake_fetch(network, pool, timeframe, **kw):
        called["count"] += 1
        return _page(TOKEN_A, QUOTE, [("2026-09-01", 1.0), ("2026-09-02", 1.1)])
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", _fake_fetch)

    r = client.post("/api/maxfi/token-daily-refresh/base?dry_run=true")
    assert r.status_code == 200
    body = r.get_json()

    assert called["count"] == 1
    assert body["dry_run"] is True
    assert body["results"][0]["status"] == "would_write"
    assert body["results"][0]["would_write"] == 2
    assert _daily_rows(daily_db, "base") == []


def test_dry_run_string_one_is_treated_as_a_real_run(client, daily_db, monkeypatch):
    _seed_catalogue_pool(daily_db, "base", POOL_A, TOKEN_A, QUOTE)
    _seed_position(daily_db, 1, "base", POOL_A, TOKEN_A.upper(), QUOTE)
    monkeypatch.setattr(
        maxfi_history, "fetch_pool_ohlcv",
        lambda network, pool, timeframe, **kw: _page(TOKEN_A, QUOTE, [("2026-09-01", 1.0)]),
    )

    r = client.post("/api/maxfi/token-daily-refresh/base?dry_run=1")
    assert r.status_code == 200
    body = r.get_json()

    assert body["dry_run"] is False
    assert body["results"][0]["status"] == "written"
    assert len(_daily_rows(daily_db, "base")) == 1


# ── invalid chain ────────────────────────────────────────────────────────

def test_invalid_chain_returns_400(client, daily_db):
    r = client.post("/api/maxfi/token-daily-refresh/not-a-real-chain")
    assert r.status_code == 400
    body = r.get_json()
    assert body["error"] == "InvalidChain"
    assert "valid_chains" in body
