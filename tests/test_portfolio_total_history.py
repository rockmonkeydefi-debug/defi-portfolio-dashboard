"""Snapshot history for the complete total (HANDOFF_total_history.md).

Covers the portfolio_total_snapshots table and its insert/read helpers, the
read-only GET /api/history/portfolio-total route, the extraction of
/api/portfolio/total's input gathering, and the snapshot writer.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched), so portfolio_snapshots and the new table are the real schema.
No network: Hyperliquid runs only through a stubbed wp._hl_fetch_accounts."""
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import maxfi_schema
import portfolio_total as pt
import src.engines.snapshot_service as ss
import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

A = "0x" + "a" * 40
B = "0x" + "b" * 40


@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    return path


def _open(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _total_row(ts, status="completed", hl_counted=1, total=100.0, detail=None, **extra):
    row = {"timestamp": ts, "status": status, "definition_version": 1, "total_usd": total,
           "snapshot_total_usd": 90.0, "wallets_total": 2, "wallets_completed": 2, "hl_counted": hl_counted,
           "detail_json": json.dumps(detail) if detail is not None else None}
    row.update(extra)
    return row


# ── commit 1: table, helpers, read route ───────────────────────────────────

def test_init_db_creates_table_with_exact_columns_and_is_idempotent(dbpath):
    portfolio_db.init_db()                                                   # second run raises nothing
    conn = _open(dbpath)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(portfolio_total_snapshots)")]
    idx = [r["name"] for r in conn.execute("PRAGMA index_list(portfolio_total_snapshots)")]
    conn.close()
    assert cols == ["id"] + list(portfolio_db.PORTFOLIO_TOTAL_SNAPSHOT_COLUMNS)
    assert "idx_portfolio_total_snapshots_user_ts" in idx


def test_insert_read_round_trip_order_and_days_filter(dbpath):
    now = datetime.utcnow()
    newer = (now - timedelta(hours=1)).isoformat()
    older = (now - timedelta(hours=3)).isoformat()
    ancient = (now - timedelta(days=40)).isoformat()
    id1 = portfolio_db.insert_portfolio_total_snapshot(_total_row(newer, hyperliquid_usd=7.5, error=None), user_id=1)
    id2 = portfolio_db.insert_portfolio_total_snapshot(_total_row(older, total=50.0))
    id3 = portfolio_db.insert_portfolio_total_snapshot(_total_row(ancient))
    assert id1 and id2 and id3
    rows = portfolio_db.get_portfolio_total_snapshots(user_id=1, days=30)
    assert [r["id"] for r in rows] == [id2, id1]                                         # ascending, ancient excluded
    r1 = rows[1]
    assert set(r1) == {"id"} | set(portfolio_db.PORTFOLIO_TOTAL_SNAPSHOT_COLUMNS)
    assert (r1["timestamp"], r1["status"], r1["definition_version"], r1["total_usd"], r1["hyperliquid_usd"],
            r1["user_id"], r1["stablecoins_usd"]) == (newer, "completed", 1, 100.0, 7.5, 1, None)
    assert [r["id"] for r in portfolio_db.get_portfolio_total_snapshots(user_id=1, days=9999)] == [id3, id2, id1]


def test_route_empty(client, dbpath):
    r = client.get("/api/history/portfolio-total")
    assert r.status_code == 200 and r.get_json() == []


def test_route_usable_and_detail(client, dbpath):
    now = datetime.utcnow()
    detail = {"status": "ok", "total_usd": 100.0, "components": [{"key": "hyperliquid", "counted": True}]}
    rows = [
        _total_row((now - timedelta(hours=4)).isoformat(), detail=detail),                 # usable
        _total_row((now - timedelta(hours=3)).isoformat(), hl_counted=0),                   # HL not counted
        _total_row((now - timedelta(hours=2)).isoformat(), status="partial"),               # partial
        _total_row((now - timedelta(hours=1)).isoformat(), status="failed", total=None, detail_json="{not json"),
    ]
    for row in rows:
        portfolio_db.insert_portfolio_total_snapshot(row)
    body = client.get("/api/history/portfolio-total").get_json()
    assert [b["usable"] for b in body] == [True, False, False, False]
    assert all("detail" not in b and "detail_json" not in b for b in body)
    body = client.get("/api/history/portfolio-total?detail=1&days=2").get_json()
    assert [b["detail"] for b in body] == [detail, None, None, None]                  # unparseable -> None
    assert all("detail_json" not in b for b in body)
    assert client.get("/api/history/portfolio-total?days=0").get_json() == body_without_detail(body)


def body_without_detail(body):
    return [{k: v for k, v in b.items() if k != "detail"} for b in body]


def test_route_unauthenticated_401(dbpath, monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    r = wp.app.test_client().get("/api/history/portfolio-total")
    assert r.status_code == 401


# ── commit 2: /api/portfolio/total input extraction ────────────────────────
# Same fixture state as tests/test_portfolio_total.py's
# test_route_warm_cache_cache_only_no_writes, reproduced here (that file is
# not modified).

H = "0x" + "c" * 40          # a hidden wallet


def _portfolio():
    return {
        "tokens": [
            {"symbol": "ETH", "value_usd": 2000.0, "wallet": A},
            {"symbol": "USDC", "value_usd": 300.0, "wallet": A},
            {"symbol": "usdt", "value_usd": 200.0, "wallet": B},
        ],
        "lp_positions": [
            {"protocol": "snuggle", "chain": "robinhood", "wallet": A, "total_value_usd": 700.0, "total_fees_usd": 0},
            {"protocol": "uniswap_v3", "chain": "base", "wallet": A, "total_value_usd": 500.0, "total_fees_usd": 5.0},
        ],
        "aave_positions": [], "gmx_positions": [], "staking_positions": [],
        "total_tokens_value": 2500.0, "total_lp_value": 1200.0, "total_uncollected_fees": 5.0, "total_value": 3705.0,
        "wallet_labels": {A: "Rabby", B: "Other"},
        "fetched_at": "2026-09-27T11:50:00",
    }


@pytest.fixture
def mem_db(monkeypatch):
    uri = f"file:portfolio_total_history_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    maxfi_schema.ensure_maxfi_tables(keepalive)
    keepalive.commit()

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    yield keepalive
    keepalive.close()


def _seed(db, pid, wallet, uncollected, chain="robinhood", status="open", value=700.0,
          value_at="2026-09-27T11:00:00+00:00", scan="2026-09-27T10:00:00+00:00"):
    db.execute(
        """INSERT INTO maxfi_positions (id, chain, wallet, token_id, array_index, pool_address, token0_address,
             token1_address, fee_tier, status, first_seen_at, first_seen_at_source, last_scan_at,
             last_value_usd, last_value_at, last_uncollected_usd)
           VALUES (?, ?, ?, ?, ?, '0xpool', '0xt0', '0xt1', 3000, ?, '2026-01-01T00:00:00+00:00', 'chain', ?, ?, ?, ?)""",
        (pid, chain, wallet, str(pid), pid, status, scan, value, value_at, uncollected))
    db.commit()


def _warm_route_state(db, monkeypatch):
    config = {A: {"label": "Rabby", "maxfi": True}, B: {"label": "Other"},
              H: {"label": "Hidden", "hidden": True, "maxfi": True}}
    monkeypatch.setattr(wp, "load_wallet_config", lambda: config)
    cache = _portfolio()
    monkeypatch.setattr(wp, "_portfolio_cache", cache)

    def _never(*a, **k):
        raise AssertionError("get_portfolio_data must not be called")
    monkeypatch.setattr(wp, "get_portfolio_data", _never)
    _seed(db, 1, A.upper().replace("0X", "0x"), 10.0)
    _seed(db, 2, A, 20.0)
    _seed(db, 3, A, 99.0, status="closed", scan="2026-09-27T11:59:00+00:00")
    _seed(db, 4, H, 50.0)
    monkeypatch.setattr(wp, "_maxfi_ledger_load_inputs", lambda conn, chain=None: {"x": 1})
    monkeypatch.setattr(wp, "_maxfi_ledger_position_claims",
                        lambda **kw: {1: {"ledger_head_closed": False}, 2: {"ledger_head_closed": True}})
    return cache


def test_route_equals_compose_total_of_the_extracted_helpers(client, mem_db, monkeypatch):
    cache = _warm_route_state(mem_db, monkeypatch)
    r = client.get("/api/portfolio/total")
    now_utc = datetime.now(timezone.utc)
    assert r.status_code == 200
    inputs = wp._portfolio_total_db_inputs()
    assert sorted(inputs) == ["latest_scan_by_key", "ledger_head_closed_ids", "ledger_ok", "maxfi_rows"]
    assert inputs["ledger_head_closed_ids"] == {2} and inputs["ledger_ok"] is True
    expected = pt.compose_total(cache, inputs["maxfi_rows"], inputs["ledger_head_closed_ids"], inputs["ledger_ok"],
                                inputs["latest_scan_by_key"], wp._hl_accounts_cache_copy(), now_utc)
    assert r.get_json() == json.loads(wp.app.json.dumps(expected))
    assert r.get_json()["total_usd"] == pytest.approx(3705.0 + 8.5)


# ── commit 3: the snapshot writer ──────────────────────────────────────────

def _snap_portfolio(api_failures=()):
    """A: $2,300 tokens + $500 LP + $5 fees = $2,805; B: $200 tokens."""
    return {
        "tokens": [
            {"wallet": A, "chain": "base", "symbol": "ETH", "balance": 1.0, "price_usd": 2000.0, "value_usd": 2000.0},
            {"wallet": A, "chain": "base", "symbol": "USDC", "balance": 300.0, "price_usd": 1.0, "value_usd": 300.0},
            {"wallet": B, "chain": "base", "symbol": "USDT", "balance": 200.0, "price_usd": 1.0, "value_usd": 200.0},
        ],
        "lp_positions": [{"wallet": A, "chain": "base", "protocol": "uniswap_v3", "token_id": 123,
                          "token0_symbol": "ETH", "token1_symbol": "USDC", "total_value_usd": 500.0,
                          "total_fees_usd": 5.0, "in_range": True}],
        "gmx_positions": [], "aave_positions": [], "api_failures": list(api_failures),
    }


def _stub_result(hl_counted=True):
    parts = {"wallet_tokens": 2000.0, "stablecoins": 500.0, "maxfi_lp": 0.0, "other_lp": 500.0,
             "lp_uncollected": 5.0, "maxfi_uncollected": 8.5, "hyperliquid": 1450.78, "lending_net": 0.0,
             "gmx": 0.0, "zerion_staking": 19.3}
    comps = [{"key": k, "label": k, "value_usd": v, "counted": (hl_counted if k == "hyperliquid" else k != "zerion_staking"),
              "as_of": None, "source": "stub", "warnings": [], "detail": {}} for k, v in parts.items()]
    return {"status": "ok", "total_usd": sum(c["value_usd"] for c in comps if c["counted"]),
            "portfolio_total_value": 2705.0, "components": comps, "maxfi_drift": [],
            "as_of": {"portfolio": "2026-09-27T11:50:00", "hyperliquid": "2026-09-27T11:58:00+00:00",
                      "maxfi_values_oldest": "2026-09-27T11:00:00+00:00"},
            "warnings": [{"component": "maxfi_uncollected", "warning": "w1"}, {"component": "gmx", "warning": "w2"}]}


class _Composer:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, []

    def __call__(self, portfolio):
        self.calls.append(portfolio)
        if self.exc:
            raise self.exc
        return self.result


def _rows(path, table):
    conn = _open(path)
    rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
    conn.close()
    return rows


def test_writer_off_pins_todays_behavior(dbpath):
    ss.take_portfolio_snapshot(lambda **_: _snap_portfolio(), [A, B])
    snaps = _rows(dbpath, "portfolio_snapshots")
    assert [(s["wallet"], s["status"], s["total_value_usd"], s["total_tokens_usd"], s["total_lp_usd"],
             s["total_lending_usd"], s["total_hedge_collateral_usd"]) for s in snaps] == [
        (A, "completed", 2805.0, 2300.0, 500.0, 0.0, 0.0), (B, "completed", 200.0, 200.0, 0.0, 0.0, 0.0)]
    assert snaps[0]["timestamp"] == snaps[1]["timestamp"]
    assert _rows(dbpath, "portfolio_total_snapshots") == []


def test_writer_writes_one_row_per_run(dbpath):
    P = _snap_portfolio()
    comp = _Composer(_stub_result())
    ss.take_portfolio_snapshot(lambda **_: P, [A, B], compose_total_fn=comp)
    assert len(comp.calls) == 1 and comp.calls[0] is P
    snaps = _rows(dbpath, "portfolio_snapshots")
    assert [s["status"] for s in snaps] == ["completed", "completed"]
    (row,) = _rows(dbpath, "portfolio_total_snapshots")
    res = _stub_result()
    assert row["timestamp"] == snaps[0]["timestamp"]
    assert (row["status"], row["definition_version"], row["user_id"]) == (
        "completed", ss.PORTFOLIO_TOTAL_DEFINITION_VERSION, 1)
    for c in res["components"]:
        assert row[c["key"] + "_usd"] == c["value_usd"], c["key"]
    assert row["total_usd"] == pytest.approx(res["total_usd"])
    assert row["hl_counted"] == 1
    assert (row["portfolio_as_of"], row["hyperliquid_as_of"], row["maxfi_values_oldest"]) == (
        "2026-09-27T11:50:00", "2026-09-27T11:58:00+00:00", "2026-09-27T11:00:00+00:00")
    assert row["warning_count"] == 2
    assert json.loads(row["detail_json"]) == res
    assert row["snapshot_total_usd"] == pytest.approx(sum(s["total_value_usd"] for s in snaps)) == pytest.approx(3005.0)
    assert (row["wallets_total"], row["wallets_completed"]) == (2, 2)
    assert row["error"] is None and row["duration_seconds"] >= 0


def test_writer_partial_run(dbpath):
    ss.take_portfolio_snapshot(lambda **_: _snap_portfolio(["lp:123"]), [A, B], compose_total_fn=_Composer(_stub_result()))
    assert [s["status"] for s in _rows(dbpath, "portfolio_snapshots")] == ["partial", "partial"]
    (row,) = _rows(dbpath, "portfolio_total_snapshots")
    assert row["status"] == "partial" and row["wallets_completed"] == 2


def test_writer_skipped_run_writes_nothing(dbpath):
    comp = _Composer(_stub_result())
    ss.take_portfolio_snapshot(lambda **_: _snap_portfolio(["tokens:base", "tokens:arbitrum", "zerion:x"]), [A, B],
                               compose_total_fn=comp)
    assert comp.calls == []
    assert _rows(dbpath, "portfolio_snapshots") == [] and _rows(dbpath, "portfolio_total_snapshots") == []


def test_writer_composer_failure_never_touches_portfolio_snapshots(dbpath):
    ss.take_portfolio_snapshot(lambda **_: _snap_portfolio(), [A, B], compose_total_fn=_Composer(exc=RuntimeError("boom")))
    assert [s["status"] for s in _rows(dbpath, "portfolio_snapshots")] == ["completed", "completed"]
    (row,) = _rows(dbpath, "portfolio_total_snapshots")
    assert row["status"] == "failed" and "RuntimeError: boom" in row["error"]
    assert row["total_usd"] is None and row["detail_json"] is None and row["hl_counted"] == 0
    assert all(row[k + "_usd"] is None for k in ss._PORTFOLIO_TOTAL_PART_KEYS)
    assert row["snapshot_total_usd"] == pytest.approx(3005.0)


def test_writer_non_ok_status_is_failed(dbpath):
    ss.take_portfolio_snapshot(lambda **_: _snap_portfolio(), [A], compose_total_fn=_Composer({"status": "cache_cold"}))
    (row,) = _rows(dbpath, "portfolio_total_snapshots")
    assert row["status"] == "failed" and row["error"] == "ValueError: compose status 'cache_cold'"


def test_writer_hyperliquid_not_counted(dbpath):
    ss.take_portfolio_snapshot(lambda **_: _snap_portfolio(), [A, B], compose_total_fn=_Composer(_stub_result(hl_counted=False)))
    (row,) = _rows(dbpath, "portfolio_total_snapshots")
    assert row["hl_counted"] == 0 and row["status"] == "completed"


# ── _hl_accounts_state_for_snapshot ────────────────────────────────────────

SNAP_NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def hl_env(monkeypatch):
    """Two visible EVM wallets plus a Solana wallet; a recording stub fetch."""
    config = {A: {"label": "Rabby"}, B: {"label": "Hyperliquid RM"}, "SoLaNaAddr": {"label": "Sol", "type": "solana"}}
    monkeypatch.setattr(wp, "load_wallet_config", lambda: config)
    fetches = []

    def fetch(wallets):
        fetches.append(list(wallets))
        return {"prices": {"USDC": 1.0}, "price_error": None, "errors": {}, "wallets_checked": len(wallets),
                "wallets": {A: {"perp_account_value": 222.68, "open_perps": 1, "mode": "unifiedAccount",
                                "spot": [{"coin": "USDC", "amount": 1450.78, "price": 1.0, "value": 1450.78}]}}}
    monkeypatch.setattr(wp, "_hl_fetch_accounts", fetch)
    return fetches


def _no_sleep(_):
    raise AssertionError("must not sleep")


def test_hl_snapshot_fresh_cache_no_fetch(hl_env, monkeypatch):
    fresh = {"fetched_at": (SNAP_NOW - timedelta(minutes=5)).isoformat(), "wallets": {A: {"perp_account_value": 1.0}},
             "error": None}
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_CACHE", fresh)
    got = wp._hl_accounts_state_for_snapshot(SNAP_NOW, sleep=_no_sleep)
    assert hl_env == [] and got == fresh and got is not fresh


@pytest.mark.parametrize("fetched_at", [None, (SNAP_NOW - timedelta(minutes=16)).isoformat()])
def test_hl_snapshot_stale_or_empty_runs_worker_inline(hl_env, monkeypatch, fetched_at):
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_CACHE", {"fetched_at": fetched_at, "wallets": {}, "error": None})
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_LAST_KICK", {"at": SNAP_NOW - timedelta(minutes=1)})   # cooldown ignored
    got = wp._hl_accounts_state_for_snapshot(SNAP_NOW, sleep=_no_sleep)
    assert hl_env == [[A, B]]
    assert got["fetched_at"] and got["fetched_at"] != fetched_at
    assert got["wallets"][A]["mode"] == "unifiedAccount"
    assert wp._HL_ACCOUNTS_IN_FLIGHT is False
    assert wp._HL_ACCOUNTS_LAST_KICK["at"] == SNAP_NOW


def test_hl_snapshot_waits_for_in_flight_refresh(hl_env, monkeypatch):
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_IN_FLIGHT", True)
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:                        # the other refresh lands
            wp._HL_ACCOUNTS_CACHE.update({"fetched_at": SNAP_NOW.isoformat(), "wallets": {B: {"perp_account_value": 2.0}}})
            wp._HL_ACCOUNTS_IN_FLIGHT = False
    got = wp._hl_accounts_state_for_snapshot(SNAP_NOW, sleep=sleep)
    assert hl_env == [] and sleeps == [wp.HL_SNAPSHOT_POLL_SECONDS] * 2
    assert got["fetched_at"] == SNAP_NOW.isoformat() and B in got["wallets"]


def test_hl_snapshot_gives_up_after_wait_limit(hl_env, monkeypatch):
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_IN_FLIGHT", True)
    sleeps = []
    got = wp._hl_accounts_state_for_snapshot(SNAP_NOW, sleep=sleeps.append)
    assert hl_env == []
    assert sum(sleeps) == wp.HL_SNAPSHOT_WAIT_SECONDS
    assert got == {"fetched_at": None, "wallets": {}, "error": None}
    assert wp._HL_ACCOUNTS_IN_FLIGHT is True                                  # someone else's refresh


def test_hl_snapshot_no_evm_wallets_no_fetch(hl_env, monkeypatch):
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {"SoLaNaAddr": {"label": "Sol", "type": "solana"}})
    got = wp._hl_accounts_state_for_snapshot(SNAP_NOW, sleep=_no_sleep)
    assert hl_env == [] and got["fetched_at"] is None and wp._HL_ACCOUNTS_IN_FLIGHT is False


def test_hl_snapshot_wallet_list_failure_falls_through(hl_env, monkeypatch):
    def boom():
        raise RuntimeError("config unreadable")
    monkeypatch.setattr(wp, "_hl_accounts_wallets", boom)
    got = wp._hl_accounts_state_for_snapshot(SNAP_NOW, sleep=_no_sleep)
    assert hl_env == [] and got == {"fetched_at": None, "wallets": {}, "error": None}
    assert wp._HL_ACCOUNTS_IN_FLIGHT is False


# ── parity: the snapshot composer vs the route ─────────────────────────────

def test_compose_total_for_snapshot_matches_route(client, mem_db, monkeypatch):
    P = _warm_route_state(mem_db, monkeypatch)
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_CACHE", {
        "fetched_at": (now - timedelta(minutes=2)).isoformat(), "error": None, "wallets_checked": 2,
        "wallets": {A: {"perp_account_value": 222.676897, "open_perps": 1, "mode": "unifiedAccount",
                        "spot": [{"coin": "USDC", "amount": 1450.78, "price": 1.0, "value": 1450.78}]},
                    B: {"perp_account_value": 10.0, "open_perps": 0, "mode": "disabled",
                        "spot": [{"coin": "USDC", "amount": 5.0, "price": 1.0, "value": 5.0}]}}})
    monkeypatch.setattr(wp, "_hl_fetch_accounts", lambda wallets: (_ for _ in ()).throw(AssertionError("fetched")))
    route = client.get("/api/portfolio/total").get_json()
    snap = wp._compose_total_for_snapshot(P)
    assert snap["total_usd"] == pytest.approx(route["total_usd"])
    assert [(c["key"], c["value_usd"], c["counted"]) for c in snap["components"]] == [
        (c["key"], c["value_usd"], c["counted"]) for c in route["components"]]
    hl = next(c for c in snap["components"] if c["key"] == "hyperliquid")
    assert hl["counted"] and hl["value_usd"] == pytest.approx(1450.78 + 10.0 + 5.0)
    assert snap["total_usd"] == pytest.approx(3705.0 + 8.5 + 1465.78)


# ── wiring ─────────────────────────────────────────────────────────────────

def test_post_snapshot_passes_the_composer(client, monkeypatch):
    calls = []
    monkeypatch.setattr(ss, "take_portfolio_snapshot", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [A])
    r = client.post("/api/snapshot")
    assert r.status_code == 200
    ((args, kwargs),) = calls
    assert args == (wp.get_portfolio_data, [A]) and kwargs == {"compose_total_fn": wp._compose_total_for_snapshot}


def test_portfolio_refresh_passes_the_composer(client, monkeypatch):
    import threading
    calls = []
    data = {"tokens": [], "total_value": 1.0}
    monkeypatch.setattr(ss, "take_portfolio_snapshot", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [A])
    monkeypatch.setattr(wp, "get_portfolio_data", lambda force_refresh=False: data)

    class _SyncThread:
        def __init__(self, target=None, **kw):
            self._target = target

        def start(self):
            self._target()
    monkeypatch.setattr(threading, "Thread", _SyncThread)
    r = client.get("/api/portfolio?refresh=true")
    assert r.status_code == 200
    ((args, kwargs),) = calls
    assert args[1] == [A] and args[0](force_refresh=True) is data
    assert kwargs == {"compose_total_fn": wp._compose_total_for_snapshot}


def test_start_snapshot_scheduler_passes_the_composer(monkeypatch):
    calls = []
    monkeypatch.setattr(ss, "start_scheduler", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(wp, "_scheduler_started", False)
    wp.start_snapshot_scheduler()
    ((args, kwargs),) = calls
    assert args == (wp.get_portfolio_data, wp.get_wallet_addresses)
    assert kwargs == {"compose_total_fn": wp._compose_total_for_snapshot}
