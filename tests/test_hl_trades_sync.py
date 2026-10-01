"""Hyperliquid trade history storage, sync and routes (HANDOFF_trading_performance.md
Commit 3): the hl_fills / hl_funding / hl_orders / hl_sync_state tables,
_hl_trades_sync_wallet (insert-only, forward paging, idempotent), the refresh
worker and kick, GET /api/trading/perps/trades and POST
/api/trading/perps/sync, and the per-position fields in _hl_fetch_accounts.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). A fake post serves the recorded fixtures in
tests/fixtures/hl_trading (read-only); no network, no real threads. Fake
wallet addresses only.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import hl_trades
import src.storage.portfolio_db as portfolio_db

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "hl_trading")
W_RM = "0x" + "a" * 40
W_RABBY = "0x" + "b" * 40
NAMES = {W_RM: "rm", W_RABBY: "rabby"}
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def _load(name, kind):
    with open(os.path.join(FIX, f"{name}.{kind}.json")) as f:
        return json.load(f)


class FakePost:
    """Serves the fixtures by payload type: fills / funding with time >=
    startTime, time ascending, at most `cap` rows per page."""

    def __init__(self, fills_cap=2000, funding_cap=500, fail=()):
        self.calls = []
        self.fills_cap, self.funding_cap, self.fail = fills_cap, funding_cap, set(fail)

    def __call__(self, payload):
        self.calls.append(dict(payload))
        user = payload.get("user")
        if user in self.fail:
            raise ConnectionError("fake outage")
        name = NAMES[user]
        kind = payload["type"]
        if kind == "userFillsByTime":
            rows = sorted(_load(name, "fills"), key=lambda r: r["time"])
            return [r for r in rows if r["time"] >= payload["startTime"]][:self.fills_cap]
        if kind == "userFunding":
            rows = sorted(_load(name, "funding"), key=lambda r: r["time"])
            return [r for r in rows if r["time"] >= payload["startTime"]][:self.funding_cap]
        if kind == "historicalOrders":
            return _load(name, "hist_orders")
        raise AssertionError(f"unexpected payload {payload}")


# The fixtures' timestamps were shifted by whole days to before the real
# window start, so tests start the sync window at the fixtures' earliest row.
FIXTURE_START = min(r["time"] for n in ("rm", "rabby") for k in ("fills", "funding") for r in _load(n, k))


def _never_post(*a, **k):
    raise AssertionError("Hyperliquid must not be called here")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.setattr(wp, "_HL_TRADES_IN_FLIGHT", False)
    monkeypatch.setattr(wp, "_HL_TRADES_LAST_KICK", {"at": None})
    monkeypatch.setattr(wp, "HL_TRADES_START_MS", FIXTURE_START)
    spawned = []
    monkeypatch.setattr(wp, "_spawn_hl_trades_refresh_thread", lambda: spawned.append(1))
    monkeypatch.setattr(wp, "_hl_post", _never_post)
    conn = portfolio_db.get_connection()
    yield conn, spawned
    conn.close()


def _count(conn, table, wallet):
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE wallet = ?", (wallet,)).fetchone()[0]


# ── tables ───────────────────────────────────────────────────────────────

def test_tables_exist_and_init_db_is_idempotent(db):
    conn, _ = db
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"hl_fills", "hl_funding", "hl_orders", "hl_sync_state"} <= names
    cols = lambda t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
    assert cols("hl_fills") == {"id", "wallet", "tid", "coin", "time_ms", "raw_json", "fetched_at"}
    assert cols("hl_funding") == {"id", "wallet", "coin", "time_ms", "raw_json", "fetched_at"}
    assert cols("hl_orders") == {"id", "wallet", "oid", "coin", "status", "status_ts", "order_ts", "raw_json",
                                 "fetched_at"}
    assert cols("hl_sync_state") == {"wallet", "first_seen_at", "last_sync_at", "last_ok_at", "last_error"}
    portfolio_db.init_db()


# ── _hl_trades_sync_wallet ───────────────────────────────────────────────

def test_window_constants():
    assert datetime.fromtimestamp(1789257600000 / 1000, tz=timezone.utc) == datetime(2026, 9, 13, tzinfo=timezone.utc)
    assert (wp.HL_TRADES_START_MS, wp.HL_TRADES_TTL_MINUTES, wp.HL_FILLS_PAGE_CAP, wp.HL_FUNDING_PAGE_CAP,
            wp.HL_TRADES_MAX_PAGES) == (1789257600000, 10, 2000, 500, 20)


def test_sync_inserts_everything_then_nothing(db):
    conn, _ = db
    post = FakePost()
    got = wp._hl_trades_sync_wallet(conn, W_RM, post=post, now_utc=NOW)
    assert got == {"fills": len(_load("rm", "fills")), "funding": len(_load("rm", "funding")),
                   "orders": len(_load("rm", "hist_orders"))}
    assert _count(conn, "hl_fills", W_RM) == 61 and _count(conn, "hl_funding", W_RM) == 162
    assert _count(conn, "hl_orders", W_RM) == 102
    assert post.calls[0] == {"type": "userFillsByTime", "user": W_RM, "startTime": FIXTURE_START,
                             "aggregateByTime": False}
    assert wp._hl_trades_sync_wallet(conn, W_RM, post=FakePost(), now_utc=NOW) == {"fills": 0, "funding": 0, "orders": 0}
    assert _count(conn, "hl_fills", W_RM) == 61


def test_sync_pages_forward_and_resumes_from_the_stored_max(db, monkeypatch):
    conn, _ = db
    # Caps above the fixtures' largest same-timestamp group (13 fills): a page
    # made only of already-stored rows ends paging by design.
    monkeypatch.setattr(wp, "HL_FILLS_PAGE_CAP", 20)
    monkeypatch.setattr(wp, "HL_FUNDING_PAGE_CAP", 25)
    post = FakePost(fills_cap=20, funding_cap=25)
    got = wp._hl_trades_sync_wallet(conn, W_RABBY, post=post, now_utc=NOW)
    assert got["fills"] == 99 and got["funding"] == 183
    fill_calls = [c for c in post.calls if c["type"] == "userFillsByTime"]
    funding_calls = [c for c in post.calls if c["type"] == "userFunding"]
    assert len(fill_calls) >= 2 and len(funding_calls) >= 2
    assert all(b["startTime"] >= a["startTime"] for a, b in zip(fill_calls, fill_calls[1:]))

    max_fill = conn.execute("SELECT MAX(time_ms) FROM hl_fills WHERE wallet = ?", (W_RABBY,)).fetchone()[0]
    max_funding = conn.execute("SELECT MAX(time_ms) FROM hl_funding WHERE wallet = ?", (W_RABBY,)).fetchone()[0]
    again = FakePost(fills_cap=20, funding_cap=25)
    assert wp._hl_trades_sync_wallet(conn, W_RABBY, post=again, now_utc=NOW) == {"fills": 0, "funding": 0, "orders": 0}
    assert [c["startTime"] for c in again.calls if c["type"] == "userFillsByTime"][0] == max_fill
    assert [c["startTime"] for c in again.calls if c["type"] == "userFunding"][0] == max_funding


def test_order_records_keep_every_status(db):
    conn, _ = db
    wp._hl_trades_sync_wallet(conn, W_RABBY, post=FakePost(), now_utc=NOW)
    statuses = {r[0] for r in conn.execute("SELECT DISTINCT status FROM hl_orders WHERE wallet = ?", (W_RABBY,))}
    assert {"open", "canceled", "triggered", "filled"} <= statuses


# ── worker, wallets, kick ────────────────────────────────────────────────

def test_worker_isolates_a_failing_wallet(db, monkeypatch):
    conn, _ = db
    conn.execute("INSERT INTO hl_sync_state (wallet, first_seen_at) VALUES (?, ?)", (W_RM, NOW.isoformat()))
    conn.commit()
    monkeypatch.setattr(wp, "_hl_accounts_state_for_snapshot", lambda now: {"wallets": {W_RABBY: {}}})
    monkeypatch.setattr(wp, "_HL_TRADES_IN_FLIGHT", True)
    wp._hl_trades_refresh_worker(now_utc=NOW, post=FakePost(fail={W_RM}))
    assert wp._HL_TRADES_IN_FLIGHT is False
    rows = {r["wallet"]: dict(r) for r in conn.execute("SELECT * FROM hl_sync_state")}
    assert set(rows) == {W_RM, W_RABBY}                       # stored UNION accounts-state wallets
    assert rows[W_RM]["last_error"].startswith("ConnectionError") and rows[W_RM]["last_ok_at"] is None
    assert rows[W_RM]["last_sync_at"] is not None
    assert rows[W_RABBY]["last_ok_at"] is not None and rows[W_RABBY]["last_error"] is None
    assert _count(conn, "hl_fills", W_RABBY) == 99 and _count(conn, "hl_fills", W_RM) == 0


def test_worker_clears_in_flight_even_when_wallet_listing_fails(db, monkeypatch):
    def boom(now):
        raise RuntimeError("accounts down")
    monkeypatch.setattr(wp, "_hl_accounts_state_for_snapshot", boom)
    monkeypatch.setattr(wp, "_HL_TRADES_IN_FLIGHT", True)
    wp._hl_trades_refresh_worker(now_utc=NOW, post=FakePost())
    assert wp._HL_TRADES_IN_FLIGHT is False


def test_wallets_are_remembered_once_seen(db, monkeypatch):
    conn, _ = db
    monkeypatch.setattr(wp, "_hl_accounts_state_for_snapshot", lambda now: {"wallets": {W_RM: {}}})
    assert wp._hl_trades_wallets(NOW) == [W_RM]
    monkeypatch.setattr(wp, "_hl_accounts_state_for_snapshot", lambda now: {"wallets": {W_RABBY: {}}})
    assert wp._hl_trades_wallets(NOW) == [W_RM, W_RABBY]
    monkeypatch.setattr(wp, "_hl_accounts_state_for_snapshot", lambda now: {"wallets": {}})
    assert wp._hl_trades_wallets(NOW) == [W_RM, W_RABBY]


def test_kick_respects_in_flight_and_ttl(db, monkeypatch):
    _, spawned = db
    assert wp._maybe_kick_hl_trades_refresh(NOW) is True and len(spawned) == 1
    assert wp._HL_TRADES_IN_FLIGHT is True
    assert wp._maybe_kick_hl_trades_refresh(NOW + timedelta(hours=1)) is False           # in flight
    assert wp._maybe_kick_hl_trades_refresh(NOW + timedelta(hours=1), force=True) is False  # force ignores TTL only
    monkeypatch.setattr(wp, "_HL_TRADES_IN_FLIGHT", False)
    assert wp._maybe_kick_hl_trades_refresh(NOW + timedelta(minutes=5)) is False         # inside the TTL
    assert wp._maybe_kick_hl_trades_refresh(NOW + timedelta(minutes=5), force=True) is True
    monkeypatch.setattr(wp, "_HL_TRADES_IN_FLIGHT", False)
    assert wp._maybe_kick_hl_trades_refresh(NOW + timedelta(minutes=16)) is True
    assert len(spawned) == 3


def test_kick_never_raises_when_spawn_fails(db, monkeypatch):
    def boom():
        raise RuntimeError("no threads")
    monkeypatch.setattr(wp, "_spawn_hl_trades_refresh_thread", boom)
    assert wp._maybe_kick_hl_trades_refresh(NOW) is False
    assert wp._HL_TRADES_IN_FLIGHT is False


def test_snapshot_path_kicks_without_blocking(db, monkeypatch):
    kicks = []
    monkeypatch.setattr(wp, "_tao_state_for_snapshot", lambda now: None)
    monkeypatch.setattr(wp, "_maybe_kick_hl_trades_refresh", lambda now, force=False: kicks.append(now) or True)
    monkeypatch.setattr(wp, "get_portfolio_data", lambda force_refresh=False: {"ok": force_refresh})
    assert wp._get_portfolio_data_for_snapshot(force_refresh=True) == {"ok": True}
    assert len(kicks) == 1

    def boom(now, force=False):
        raise RuntimeError("kick failed")
    monkeypatch.setattr(wp, "_maybe_kick_hl_trades_refresh", boom)
    assert wp._get_portfolio_data_for_snapshot(force_refresh=True) == {"ok": True}


# ── routes ───────────────────────────────────────────────────────────────

@pytest.fixture
def seeded(db, monkeypatch):
    conn, spawned = db
    monkeypatch.setattr(wp, "_hl_accounts_state_for_snapshot", lambda now: {"wallets": {W_RM: {}, W_RABBY: {}}})
    wp._hl_trades_refresh_worker(now_utc=NOW, post=FakePost())
    monkeypatch.setattr(wp, "_hl_accounts_state_for_snapshot", _never_post)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {W_RM: {"label": "Hyperliquid RM"}})
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    client = wp.app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
    return conn, spawned, client


def _engine(wallet):
    name = NAMES[wallet]
    return hl_trades.build_cycles(wallet, _load(name, "fills"), _load(name, "funding"), _load(name, "hist_orders"))


def test_trades_route_matches_the_engine(seeded, monkeypatch):
    conn, spawned, client = seeded
    open_coin = next(c["coin"] for c in _engine(W_RABBY)["cycles"] if c["status"] == "open")
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {
        "fetched_at": NOW.isoformat(),
        "wallets": {W_RABBY: {"positions": [{"coin": open_coin, "szi": "1.0", "entry_px": "1.0",
                                             "unrealized_pnl": "12.5", "cum_funding_since_open": "0.1"}]}}})
    r = client.get('/api/trading/perps/trades')
    assert r.status_code == 200
    body = r.get_json()
    trades = body["trades"]
    expected = _engine(W_RM)["cycles"] + _engine(W_RABBY)["cycles"]
    assert len(trades) == len(expected) == 20
    assert [t["open_time"] for t in trades] == sorted((t["open_time"] for t in trades), reverse=True)
    by_key = {t["trade_key"]: t for t in trades}
    for c in expected:
        t = by_key[c["trade_key"]]
        assert {k: t[k] for k in c} == c
        assert t["wallet_label"] == ("Hyperliquid RM" if c["wallet"] == W_RM else "Wallet …" + W_RABBY[-4:])
    opens = [t for t in trades if t["status"] == "open"]
    assert len(opens) == 1
    assert opens[0]["unrealized_pnl"] == "12.5" and opens[0]["mark_as_of"] == NOW.isoformat()
    assert all("unrealized_pnl" not in t for t in trades if t["status"] == "closed")
    assert len(spawned) == 1                        # the route kicked the sync, nothing more

    closed = [c for c in expected if c["status"] == "closed"]
    s = body["summary"]
    total = lambda k: str(sum((Decimal(c[k]) for c in closed), Decimal(0)).quantize(Decimal("0.000001")))
    assert s["closed_count"] == 19 and s["open_count"] == 1
    assert s["win_count"] == sum(1 for c in closed if Decimal(c["net_pnl"]) > 0)
    assert s["loss_count"] == sum(1 for c in closed if Decimal(c["net_pnl"]) < 0)
    for k in ("gross_closed_pnl", "fees", "funding", "net_pnl"):
        assert s[k] == total(k)
    assert set(s["by_wallet"]) == {"Hyperliquid RM", "Wallet …" + W_RABBY[-4:]}
    assert s["by_wallet"]["Hyperliquid RM"]["closed_count"] == 9
    assert s["by_wallet"]["Wallet …" + W_RABBY[-4:]]["open_count"] == 1

    sync = body["sync"]
    assert sync["in_flight"] is True                # set by the route's kick (spawn stubbed)
    rows = {w["wallet_label"]: w for w in sync["wallets"]}
    assert rows["Hyperliquid RM"]["fills"] == 61 and rows["Hyperliquid RM"]["orders"] == 102
    assert rows["Hyperliquid RM"]["funding_rows"] == 162 and rows["Hyperliquid RM"]["last_error"] is None
    assert rows["Hyperliquid RM"]["unattributed_funding"] == "0.000000"
    assert rows["Hyperliquid RM"]["skipped_partial_fills"] == 0


def test_trades_route_open_trade_without_a_mark(seeded, monkeypatch):
    _, _, client = seeded
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": None, "wallets": {}})
    trades = client.get('/api/trading/perps/trades').get_json()["trades"]
    (o,) = [t for t in trades if t["status"] == "open"]
    assert o["unrealized_pnl"] is None and o["mark_as_of"] is None


def test_trades_route_with_no_wallets(db, monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": None, "wallets": {}})
    client = wp.app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
    body = client.get('/api/trading/perps/trades').get_json()
    assert body["trades"] == [] and body["summary"]["closed_count"] == 0 and body["summary"]["by_wallet"] == {}
    assert body["summary"]["net_pnl"] == "0.000000" and body["sync"]["wallets"] == []


def test_sync_route_returns_202(seeded):
    _, spawned, client = seeded
    r = client.post('/api/trading/perps/sync')
    assert r.status_code == 202 and r.get_json() == {"started": True}
    r = client.post('/api/trading/perps/sync')
    assert r.status_code == 202 and r.get_json() == {"started": False}     # one already in flight
    assert len(spawned) == 1


# ── per-position fields in _hl_fetch_accounts ────────────────────────────

def test_fetch_accounts_positions():
    full = {"coin": "ETH", "szi": "1.5", "entryPx": "2000.0", "unrealizedPnl": "12.3",
            "cumFunding": {"allTime": "-1.0", "sinceOpen": "-0.5", "sinceChange": "-0.2"}}

    def post(payload):
        t = payload["type"]
        if t == "spotMetaAndAssetCtxs":
            return [{"tokens": [], "universe": []}, []]
        if t == "clearinghouseState":
            if payload["user"] == W_RM:
                return {"marginSummary": {"accountValue": "100"},
                        "assetPositions": [{"position": full}, {"position": {}}, {"type": "oneWay"}]}
            return {"marginSummary": {"accountValue": "5"}, "assetPositions": [{"position": {}}]}
        if t == "spotClearinghouseState":
            return {"balances": []}
        if t == "userAbstraction":
            return "default"
        raise AssertionError(t)

    res = wp._hl_fetch_accounts([W_RM, W_RABBY], post=post)
    assert res["errors"] == {}
    assert len(res["wallets"][W_RM]["positions"]) == 1
    pos = res["wallets"][W_RM]["positions"][0]
    for k, v in {"coin": "ETH", "szi": "1.5", "entry_px": "2000.0", "unrealized_pnl": "12.3",
                 "cum_funding_since_open": "-0.5"}.items():
        assert pos[k] == v
    for k in ("position_value", "liquidation_px", "margin_used", "return_on_equity", "leverage", "leverage_type"):
        assert k in pos and pos[k] is None          # this fixture's position carries none of them
    assert res["wallets"][W_RM]["open_perps"] == 3                  # unchanged: len(assetPositions)
    assert res["wallets"][W_RABBY]["positions"] == []
