"""Tests for the GeckoTerminal backfill workstream (commit 2 of 3):
maxfi_history.py's pure fetch/compute helpers, and the resumable
POST /api/maxfi/backfill-history/<chain> route in web_portfolio.py.

No network calls anywhere - maxfi_history.fetch_pool_ohlcv is monkeypatched
in every route-level test, and the pure-function tests (compute_ath,
candle_open_at, resolve_token_side, fetch_full_day_history) pass their own
fakes directly. web_portfolio spawns a background scheduler on
non-__main__ import; neutralized during import exactly like
tests/test_maxfi_valuation_route.py does.
"""
import sqlite3
import threading
import uuid
from datetime import datetime, timezone, timedelta

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import pytest

import maxfi_history
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
def hist_db(monkeypatch):
    """Same shared-cache-sqlite-URI + monkeypatched get_connection
    convention as test_maxfi_valuation_route.py's iv_db fixture - the route
    opens and closes its OWN connection per call, so a fresh anonymous
    ':memory:' db would lose all state the instant the route's own
    conn.close() ran. time.sleep is also neutralized here (the SAME `time`
    module object web_portfolio.py calls time.sleep through), so tests
    never actually pace out GT_CALL_SPACING_SECONDS between fake calls."""
    uri = f"file:maxfi_history_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    keepalive.row_factory = sqlite3.Row
    maxfi_schema.ensure_maxfi_tables(keepalive)

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    monkeypatch.setattr(wp.time, "sleep", lambda *a, **k: None)
    yield keepalive
    keepalive.close()


def _seed_position(db, position_id, chain='base', wallet='0xWALLET', pool='0xpool',
                    token0='0xtoken0', token1='0xtoken1', status='open',
                    first_seen_at='2026-01-01T00:00:00+00:00',
                    open_token_price_usd=None, open_token_price_source=None):
    db.execute(
        """
        INSERT INTO maxfi_positions (
            id, chain, wallet, token_id, array_index, pool_address,
            token0_address, token1_address, fee_tier, status,
            first_seen_at, first_seen_at_source, first_seen_block,
            last_scan_at, closed_at, open_token_price_usd, open_token_price_source
        ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, 3000, ?,
                  ?, 'chain', '1', ?, NULL, ?, ?)
        """,
        (position_id, chain, wallet, str(position_id), pool, token0, token1, status,
         first_seen_at, first_seen_at, open_token_price_usd, open_token_price_source),
    )
    db.commit()


def _seed_stats(db, chain='base', address='0xtoken1', symbol='FOO', last_price=1.0,
                 ath_price=1.0, ts='2026-01-01T00:00:00+00:00', ath_source=None):
    if ath_source is None:
        db.execute(
            "INSERT INTO maxfi_token_price_stats (chain, address, symbol, last_price_usd, "
            "last_price_at, ath_price_usd, ath_at, first_recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (chain, address, symbol, last_price, ts, ath_price, ts, ts),
        )
    else:
        db.execute(
            "INSERT INTO maxfi_token_price_stats (chain, address, symbol, last_price_usd, "
            "last_price_at, ath_price_usd, ath_at, first_recorded_at, ath_source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (chain, address, symbol, last_price, ts, ath_price, ts, ts, ath_source),
        )
    db.commit()


def _make_fake_fetch(day_candles, hour_candles, base_address, quote_address):
    def fake_fetch(network, pool_address, timeframe, *, aggregate=1,
                    before_timestamp=None, limit=1000, token=None):
        candles = day_candles if timeframe == "day" else hour_candles
        return {"candles": candles, "base_address": base_address, "quote_address": quote_address}
    return fake_fetch


# ── (a) compute_ath ──────────────────────────────────────────────────────

def test_compute_ath_unordered_skips_malformed_rows_and_handles_empty():
    candles = [
        [300, 1, 5, 0.5, 2, 100],
        [100, 1, 10, 0.5, 2, 100],   # highest high, but earliest ts - order-agnostic
        ["bad", "row", "here"],       # malformed - skipped
        [200, 1, "notanumber", 0.5, 2, 100],  # malformed high - skipped
        [400, 1, 3, 0.5, 2, 100],
    ]
    assert maxfi_history.compute_ath(candles) == (10.0, 100)
    assert maxfi_history.compute_ath([]) is None
    assert maxfi_history.compute_ath(None) is None
    assert maxfi_history.compute_ath([["bad"]]) is None


# ── (b) candle_open_at ───────────────────────────────────────────────────

def test_candle_open_at_exact_bracket_near_miss_and_outside_tolerance():
    candle_seconds = 3600
    candles = [
        [1000, 10.0, 12, 9, 11, 100],
        [1000 + 3600, 11.0, 13, 10, 12, 100],
        [1000 + 3600 * 5, 20.0, 22, 19, 21, 100],
    ]
    # Exact bracket.
    assert maxfi_history.candle_open_at(candles, 1500, candle_seconds) == (10.0, 1000)

    # Near miss: within 2*candle_seconds (7200s) of the last candle (19000).
    near_target = 1000 + 3600 * 5 + 6000
    assert maxfi_history.candle_open_at(candles, near_target, candle_seconds) == (20.0, 1000 + 3600 * 5)

    # Outside tolerance for every candle -> None.
    far_target = 1000 + 3600 * 5 + 3600 * 10
    assert maxfi_history.candle_open_at(candles, far_target, candle_seconds) is None


# ── (c) resolve_token_side ───────────────────────────────────────────────

def test_resolve_token_side_both_sides_and_neither():
    assert maxfi_history.resolve_token_side("0xABC", "0xabc", "0xdef") == "base"
    assert maxfi_history.resolve_token_side("0xDEF", "0xabc", "0xdef") == "quote"
    assert maxfi_history.resolve_token_side("0x999", "0xabc", "0xdef") is None
    assert maxfi_history.resolve_token_side(None, "0xabc", "0xdef") is None


# ── (d) fetch_full_day_history paging ────────────────────────────────────

def test_fetch_full_day_history_pages_until_empty_and_counts():
    pages = [
        {"candles": [[300, 1, 2, 0.5, 1, 10], [200, 1, 2, 0.5, 1, 10]], "base_address": "0xa", "quote_address": "0xb"},
        {"candles": [[100, 1, 2, 0.5, 1, 10]], "base_address": "0xa", "quote_address": "0xb"},
        {"candles": [], "base_address": "0xa", "quote_address": "0xb"},
    ]
    calls = []

    def fake_fetch(network, pool_address, timeframe, *, aggregate=1, before_timestamp=None, limit=1000, token=None):
        calls.append(before_timestamp)
        return pages[len(calls) - 1]

    counter = [0]
    candles = maxfi_history.fetch_full_day_history(
        "base", "0xpool", "base", fetch=fake_fetch, max_pages=4, counter=counter
    )
    assert len(candles) == 3
    assert counter[0] == 3
    assert calls == [None, 200, 100]


def test_fetch_full_day_history_respects_max_pages():
    def fake_fetch_infinite(network, pool_address, timeframe, *, aggregate=1,
                             before_timestamp=None, limit=1000, token=None):
        ts = (before_timestamp or 1000) - 100
        return {"candles": [[ts, 1, 2, 0.5, 1, 10]], "base_address": "0xa", "quote_address": "0xb"}

    counter = [0]
    candles = maxfi_history.fetch_full_day_history(
        "base", "0xpool", "base", fetch=fake_fetch_infinite, max_pages=3, counter=counter
    )
    assert counter[0] == 3
    assert len(candles) == 3


# ── (e) route dry_run: would_write, DB untouched ─────────────────────────

def test_route_dry_run_would_write_and_writes_nothing(monkeypatch, client, hist_db):
    volatile, anchor = "0xvolatile", "0xanchor"
    _seed_position(hist_db, 1, token0=volatile, token1=anchor,
                    open_token_price_source='seeded', first_seen_at='2026-01-01T00:00:00+00:00')
    _seed_stats(hist_db, address=volatile, ath_price=5.0)

    day_candles = [[1735689600, 1.0, 10.0, 0.5, 8.0, 100]]  # high 10.0 > existing ath 5.0
    hour_candles = [[int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()), 3.0, 3.5, 2.5, 3.2, 50]]
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv",
                         _make_fake_fetch(day_candles, hour_candles, volatile, anchor))

    before_positions = [tuple(r) for r in hist_db.execute("SELECT * FROM maxfi_positions ORDER BY id").fetchall()]
    before_stats = [tuple(r) for r in hist_db.execute("SELECT * FROM maxfi_token_price_stats ORDER BY address").fetchall()]

    r = client.post("/api/maxfi/backfill-history/base?dry_run=true")
    assert r.status_code == 200
    body = r.get_json()
    assert body["dry_run"] is True

    ath_entry = next(a for a in body["ath"] if a["address"] == volatile)
    assert ath_entry["status"] == "would_write"
    assert ath_entry["ath_price_usd"] == 10.0

    open_entry = next(o for o in body["open_prices"] if o["position_id"] == 1)
    assert open_entry["status"] == "would_write"
    assert open_entry["open_price_usd"] == 3.0

    after_positions = [tuple(r) for r in hist_db.execute("SELECT * FROM maxfi_positions ORDER BY id").fetchall()]
    after_stats = [tuple(r) for r in hist_db.execute("SELECT * FROM maxfi_token_price_stats ORDER BY address").fetchall()]
    assert before_positions == after_positions
    assert before_stats == after_stats


# ── (f) route apply: seeded updated, recorded/backfilled untouched ───────

def test_route_apply_updates_seeded_leaves_recorded_and_backfilled_untouched(monkeypatch, client, hist_db):
    volatile, anchor = "0xvolatile", "0xanchor"
    _seed_position(hist_db, 1, token0=volatile, token1=anchor, open_token_price_source='seeded',
                    first_seen_at='2026-01-01T00:00:00+00:00')
    _seed_position(hist_db, 2, token0=volatile, token1=anchor, open_token_price_source='recorded',
                    open_token_price_usd=42.0, first_seen_at='2026-01-01T00:00:00+00:00')
    _seed_position(hist_db, 3, token0=volatile, token1=anchor, open_token_price_source='backfilled',
                    open_token_price_usd=99.0, first_seen_at='2026-01-01T00:00:00+00:00')
    _seed_stats(hist_db, address=volatile, ath_price=1.0)

    hour_candles = [[int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()), 7.0, 7.5, 6.5, 7.2, 50]]
    day_candles = [[1735689600, 1.0, 2.0, 0.5, 1.5, 100]]
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv",
                         _make_fake_fetch(day_candles, hour_candles, volatile, anchor))

    r = client.post("/api/maxfi/backfill-history/base", json={"dry_run": False})
    assert r.status_code == 200
    assert r.get_json()["dry_run"] is False

    row1 = hist_db.execute(
        "SELECT open_token_price_usd, open_token_price_source FROM maxfi_positions WHERE id=1"
    ).fetchone()
    assert row1["open_token_price_usd"] == 7.0
    assert row1["open_token_price_source"] == "backfilled"

    row2 = hist_db.execute(
        "SELECT open_token_price_usd, open_token_price_source FROM maxfi_positions WHERE id=2"
    ).fetchone()
    assert row2["open_token_price_usd"] == 42.0
    assert row2["open_token_price_source"] == "recorded"

    row3 = hist_db.execute(
        "SELECT open_token_price_usd, open_token_price_source FROM maxfi_positions WHERE id=3"
    ).fetchone()
    assert row3["open_token_price_usd"] == 99.0
    assert row3["open_token_price_source"] == "backfilled"


def test_open_price_update_sql_guard_structurally_ignores_non_seeded_rows(hist_db):
    """Direct proof, independent of the route's own worklist filtering: the
    exact UPDATE statement the backfill route runs for an open-price unit
    is powerless against a 'recorded' or already-'backfilled' row even if
    targeted directly - the WHERE clause's guard protects them, not merely
    the worklist query that decides which rows become units."""
    _seed_position(hist_db, 10, open_token_price_source='recorded', open_token_price_usd=42.0)
    _seed_position(hist_db, 11, open_token_price_source='backfilled', open_token_price_usd=99.0)

    cur = hist_db.cursor()
    for pos_id in (10, 11):
        cur.execute(
            "UPDATE maxfi_positions SET open_token_price_usd = ?, open_token_price_source = 'backfilled' "
            "WHERE id = ? AND open_token_price_source = 'seeded'",
            (7.0, pos_id),
        )
        assert cur.rowcount == 0
    hist_db.commit()

    row10 = hist_db.execute(
        "SELECT open_token_price_usd, open_token_price_source FROM maxfi_positions WHERE id=10"
    ).fetchone()
    assert row10["open_token_price_usd"] == 42.0 and row10["open_token_price_source"] == "recorded"
    row11 = hist_db.execute(
        "SELECT open_token_price_usd, open_token_price_source FROM maxfi_positions WHERE id=11"
    ).fetchone()
    assert row11["open_token_price_usd"] == 99.0 and row11["open_token_price_source"] == "backfilled"


# ── (g) ATH apply: MAX semantics ──────────────────────────────────────────

def test_ath_apply_keeps_higher_existing_price_but_still_flips_source(monkeypatch, client, hist_db):
    volatile, anchor = "0xvolatile", "0xanchor"
    _seed_position(hist_db, 1, token0=volatile, token1=anchor, open_token_price_source='recorded',
                    open_token_price_usd=1.0)
    _seed_stats(hist_db, address=volatile, ath_price=100.0, ts='2026-06-01T00:00:00+00:00')

    day_candles_low = [[1735689600, 1.0, 10.0, 0.5, 8.0, 100]]  # historical high BELOW existing ATH
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv",
                         _make_fake_fetch(day_candles_low, [], volatile, anchor))

    r = client.post("/api/maxfi/backfill-history/base", json={"dry_run": False})
    assert r.status_code == 200

    row = hist_db.execute(
        "SELECT ath_price_usd, ath_at, ath_source FROM maxfi_token_price_stats WHERE chain='base' AND address=?",
        (volatile,),
    ).fetchone()
    assert row["ath_price_usd"] == 100.0                        # existing higher price kept
    assert row["ath_at"] == "2026-06-01T00:00:00+00:00"          # existing date kept
    assert row["ath_source"] == "backfilled"                     # source still flips


def test_ath_apply_replaces_price_and_date_when_historical_is_higher(monkeypatch, client, hist_db):
    volatile, anchor = "0xvolatile2", "0xanchor"
    _seed_position(hist_db, 2, token0=volatile, token1=anchor, open_token_price_source='recorded',
                    open_token_price_usd=1.0)
    _seed_stats(hist_db, address=volatile, ath_price=5.0, ts='2026-06-01T00:00:00+00:00')

    day_candles_high = [[1735689600, 1.0, 50.0, 0.5, 8.0, 100]]  # historical high ABOVE existing ATH
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv",
                         _make_fake_fetch(day_candles_high, [], volatile, anchor))

    r = client.post("/api/maxfi/backfill-history/base", json={"dry_run": False})
    assert r.status_code == 200

    row = hist_db.execute(
        "SELECT ath_price_usd, ath_at, ath_source FROM maxfi_token_price_stats WHERE chain='base' AND address=?",
        (volatile,),
    ).fetchone()
    assert row["ath_price_usd"] == 50.0
    assert row["ath_at"] == datetime.fromtimestamp(1735689600, tz=timezone.utc).isoformat()
    assert row["ath_source"] == "backfilled"


# ── (h) budget resumability ───────────────────────────────────────────────

def test_budget_exhaustion_defers_remaining_and_second_run_completes(monkeypatch, client, hist_db):
    monkeypatch.setattr(maxfi_history, "GT_CALL_BUDGET_PER_RUN", 2)

    anchor = "0xanchor"
    pool_to_addr = {}
    for i, addr in enumerate(["0xvol1", "0xvol2", "0xvol3"], start=1):
        pool = f"0xpool{i}"
        pool_to_addr[pool] = addr
        _seed_position(hist_db, i, token0=addr, token1=anchor, pool=pool,
                        open_token_price_source='recorded', open_token_price_usd=1.0)
        _seed_stats(hist_db, address=addr, ath_price=1.0)

    day_candles = [[1735689600, 1.0, 2.0, 0.5, 1.5, 100]]
    call_counts = {}

    def fake_fetch(network, pool_address, timeframe, *, aggregate=1, before_timestamp=None, limit=1000, token=None):
        call_counts[pool_address] = call_counts.get(pool_address, 0) + 1
        # First 2 day-fetches for a given pool return data; the 3rd (the
        # second fetch_full_day_history page) returns empty so paging ends
        # deterministically at exactly 3 GT calls per fully-processed unit.
        candles = day_candles if call_counts[pool_address] <= 2 else []
        return {"candles": candles, "base_address": pool_to_addr[pool_address], "quote_address": anchor}

    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", fake_fetch)

    r1 = client.post("/api/maxfi/backfill-history/base", json={"dry_run": False})
    assert r1.status_code == 200
    body1 = r1.get_json()
    assert body1["complete"] is False
    assert body1["remaining"]["ath"] > 0
    statuses1 = {a["address"]: a["status"] for a in body1["ath"]}
    assert "budget_deferred" in statuses1.values()

    # Fresh (larger) budget for the resuming call - the worklist is
    # rebuilt from scratch and naturally excludes whatever already
    # succeeded (ath_source now 'backfilled'), so only the leftover units
    # need to fit this time.
    monkeypatch.setattr(maxfi_history, "GT_CALL_BUDGET_PER_RUN", 100)
    r2 = client.post("/api/maxfi/backfill-history/base", json={"dry_run": False})
    assert r2.status_code == 200
    body2 = r2.get_json()
    assert body2["complete"] is True
    assert body2["remaining"] == {"ath": 0, "open_prices": 0}

    sources = {row["address"]: row["ath_source"] for row in hist_db.execute(
        "SELECT address, ath_source FROM maxfi_token_price_stats WHERE chain='base'"
    ).fetchall()}
    assert set(sources.values()) == {"backfilled"}


# ── (i) per-unit GT error isolation ───────────────────────────────────────

def test_gt_error_on_one_pool_is_isolated_from_others(monkeypatch, client, hist_db):
    _seed_position(hist_db, 1, token0="0xvol1", token1="0xanchor", pool="0xpool1",
                    open_token_price_source='recorded', open_token_price_usd=1.0)
    _seed_position(hist_db, 2, token0="0xvol2", token1="0xanchor", pool="0xpool2",
                    open_token_price_source='recorded', open_token_price_usd=1.0)
    _seed_stats(hist_db, address="0xvol1", ath_price=1.0)
    _seed_stats(hist_db, address="0xvol2", ath_price=1.0)

    day_candles = [[1735689600, 1.0, 20.0, 0.5, 15.0, 100]]

    def fake_fetch(network, pool_address, timeframe, *, aggregate=1, before_timestamp=None, limit=1000, token=None):
        if pool_address == "0xpool1":
            raise maxfi_history.GTError("simulated GT outage for pool1")
        return {"candles": day_candles, "base_address": "0xvol2", "quote_address": "0xanchor"}

    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", fake_fetch)

    r = client.post("/api/maxfi/backfill-history/base", json={"dry_run": False})
    assert r.status_code == 200
    body = r.get_json()

    entry1 = next(a for a in body["ath"] if a["address"] == "0xvol1")
    assert entry1["status"] == "error"
    assert "simulated GT outage" in entry1["reason"]

    entry2 = next(a for a in body["ath"] if a["address"] == "0xvol2")
    assert entry2["status"] == "done"
    assert entry2["ath_price_usd"] == 20.0


# ── 429 fix (commit 1 of 2): self-pacing client + rate-limit abort ────────

class _FakeResponse:
    def __init__(self, status_code, json_data=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


_FAKE_GT_PAYLOAD = {
    "data": {"attributes": {"ohlcv_list": [[1, 2, 3, 4, 5, 6]]}},
    "meta": {"base": {"address": "0xAAA"}, "quote": {"address": "0xBBB"}},
}


def test_fetch_pool_ohlcv_sleeps_before_the_request(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr(maxfi_history.time, "sleep", lambda s: sleep_calls.append(s))

    def fake_get(url, params=None, timeout=None, headers=None):
        # The sleep must already have happened by the time the request fires.
        assert sleep_calls == [maxfi_history.GT_CALL_SPACING_SECONDS]
        return _FakeResponse(200, _FAKE_GT_PAYLOAD)

    monkeypatch.setattr(maxfi_history.requests, "get", fake_get)

    result = maxfi_history.fetch_pool_ohlcv("base", "0xpool", "day")
    assert sleep_calls == [maxfi_history.GT_CALL_SPACING_SECONDS]
    assert result["base_address"] == "0xaaa"
    assert result["quote_address"] == "0xbbb"


def test_fetch_pool_ohlcv_429_raises_rate_limit_error_other_failures_raise_plain_gterror(monkeypatch):
    monkeypatch.setattr(maxfi_history.time, "sleep", lambda s: None)

    monkeypatch.setattr(maxfi_history.requests, "get", lambda *a, **k: _FakeResponse(429))
    with pytest.raises(maxfi_history.GTRateLimitError):
        maxfi_history.fetch_pool_ohlcv("base", "0xpool", "day")

    monkeypatch.setattr(maxfi_history.requests, "get", lambda *a, **k: _FakeResponse(500))
    with pytest.raises(maxfi_history.GTError) as exc_info:
        maxfi_history.fetch_pool_ohlcv("base", "0xpool", "day")
    assert not isinstance(exc_info.value, maxfi_history.GTRateLimitError)


def test_route_aborts_on_rate_limit_first_unit_persists_no_later_unit_attempted(monkeypatch, client, hist_db):
    anchor = "0xanchor"
    pool_to_addr = {"0xpool1": "0xvol1", "0xpool2": "0xvol2", "0xpool3": "0xvol3"}
    for pool, addr in pool_to_addr.items():
        pos_id = {"0xpool1": 1, "0xpool2": 2, "0xpool3": 3}[pool]
        _seed_position(hist_db, pos_id, token0=addr, token1=anchor, pool=pool,
                        open_token_price_source='recorded', open_token_price_usd=1.0)
        _seed_stats(hist_db, address=addr, ath_price=1.0)

    day_candles = [[1735689600, 1.0, 20.0, 0.5, 15.0, 100]]
    call_counts = {}

    def fake_fetch(network, pool_address, timeframe, *, aggregate=1, before_timestamp=None, limit=1000, token=None):
        call_counts[pool_address] = call_counts.get(pool_address, 0) + 1
        if pool_address == "0xpool2":
            raise maxfi_history.GTRateLimitError("GeckoTerminal HTTP 429 for base/0xpool2")
        # Deterministic 2-pages-then-empty pattern (same technique as the
        # budget test above) so unit1 fully completes in exactly 3 calls.
        candles = day_candles if call_counts[pool_address] <= 2 else []
        return {"candles": candles, "base_address": pool_to_addr[pool_address], "quote_address": anchor}

    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv", fake_fetch)

    r = client.post("/api/maxfi/backfill-history/base", json={"dry_run": False})
    assert r.status_code == 200
    body = r.get_json()

    assert body["rate_limited"] is True
    assert body["complete"] is False

    # The first unit's write persists - the abort happens on the SECOND unit.
    entry1 = next(a for a in body["ath"] if a["address"] == "0xvol1")
    assert entry1["status"] == "done"
    row1 = hist_db.execute(
        "SELECT ath_price_usd, ath_source FROM maxfi_token_price_stats WHERE chain='base' AND address='0xvol1'"
    ).fetchone()
    assert row1["ath_price_usd"] == 20.0
    assert row1["ath_source"] == "backfilled"

    # The aborting unit reports the 429 reason.
    entry2 = next(a for a in body["ath"] if a["address"] == "0xvol2")
    assert entry2["status"] == "error"
    assert "429" in entry2["reason"]

    # The third unit is never attempted at all - no call for its pool.
    entry3 = next(a for a in body["ath"] if a["address"] == "0xvol3")
    assert entry3["status"] == "budget_deferred"
    assert "0xpool3" not in call_counts
    row3 = hist_db.execute(
        "SELECT ath_source FROM maxfi_token_price_stats WHERE chain='base' AND address='0xvol3'"
    ).fetchone()
    assert row3["ath_source"] != "backfilled"

    assert body["remaining"] == {"ath": 1, "open_prices": 0}


def test_clean_full_run_reports_rate_limited_false(monkeypatch, client, hist_db):
    volatile, anchor = "0xvolatile", "0xanchor"
    _seed_position(hist_db, 1, token0=volatile, token1=anchor, open_token_price_source='recorded',
                    open_token_price_usd=1.0)
    _seed_stats(hist_db, address=volatile, ath_price=1.0)

    day_candles = [[1735689600, 1.0, 2.0, 0.5, 1.5, 100]]
    monkeypatch.setattr(maxfi_history, "fetch_pool_ohlcv",
                         _make_fake_fetch(day_candles, [], volatile, anchor))

    r = client.post("/api/maxfi/backfill-history/base", json={"dry_run": False})
    assert r.status_code == 200
    body = r.get_json()
    assert body["rate_limited"] is False


# ── Keyed CoinGecko onchain API upgrade ────────────────────────────────────

def test_key_absent_targets_public_gt_url_with_no_key_header(monkeypatch):
    monkeypatch.delenv("COINGECKO_API_KEY", raising=False)
    monkeypatch.setattr(maxfi_history.time, "sleep", lambda s: None)

    captured = {}

    def fake_get(url, params=None, timeout=None, headers=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResponse(200, _FAKE_GT_PAYLOAD)

    monkeypatch.setattr(maxfi_history.requests, "get", fake_get)

    maxfi_history.fetch_pool_ohlcv("base", "0xpool", "day")

    assert captured["url"].startswith(maxfi_history.GT_PUBLIC_BASE_URL)
    assert "x-cg-demo-api-key" not in captured["headers"]


def test_key_present_targets_coingecko_onchain_url_with_key_header(monkeypatch):
    monkeypatch.setenv("COINGECKO_API_KEY", "test-key-123")
    monkeypatch.setattr(maxfi_history.time, "sleep", lambda s: None)

    captured = {}

    def fake_get(url, params=None, timeout=None, headers=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return _FakeResponse(200, _FAKE_GT_PAYLOAD)

    monkeypatch.setattr(maxfi_history.requests, "get", fake_get)

    maxfi_history.fetch_pool_ohlcv(
        "base", "0xpool", "hour", aggregate=1, before_timestamp=12345, limit=10, token="quote",
    )

    assert captured["url"].startswith(maxfi_history.CG_ONCHAIN_BASE_URL)
    assert captured["headers"]["x-cg-demo-api-key"] == "test-key-123"
    assert captured["headers"]["Accept"] == "application/json;version=20230302"
    assert captured["params"] == {
        "aggregate": 1, "limit": 10, "currency": "usd",
        "before_timestamp": 12345, "token": "quote",
    }


def test_key_present_429_still_raises_rate_limit_error(monkeypatch):
    monkeypatch.setenv("COINGECKO_API_KEY", "test-key-123")
    monkeypatch.setattr(maxfi_history.time, "sleep", lambda s: None)
    monkeypatch.setattr(maxfi_history.requests, "get", lambda *a, **k: _FakeResponse(429))

    with pytest.raises(maxfi_history.GTRateLimitError):
        maxfi_history.fetch_pool_ohlcv("base", "0xpool", "day")


def test_key_is_read_per_call_not_cached(monkeypatch):
    monkeypatch.setattr(maxfi_history.time, "sleep", lambda s: None)
    urls = []

    def fake_get(url, params=None, timeout=None, headers=None):
        urls.append(url)
        return _FakeResponse(200, _FAKE_GT_PAYLOAD)

    monkeypatch.setattr(maxfi_history.requests, "get", fake_get)

    monkeypatch.setenv("COINGECKO_API_KEY", "test-key-123")
    maxfi_history.fetch_pool_ohlcv("base", "0xpool", "day")

    monkeypatch.delenv("COINGECKO_API_KEY", raising=False)
    maxfi_history.fetch_pool_ohlcv("base", "0xpool", "day")

    assert urls[0].startswith(maxfi_history.CG_ONCHAIN_BASE_URL)
    assert urls[1].startswith(maxfi_history.GT_PUBLIC_BASE_URL)
