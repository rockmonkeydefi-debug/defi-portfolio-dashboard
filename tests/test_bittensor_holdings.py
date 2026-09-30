"""Bittensor (TAO) holdings via Taostats: the 15-min background cache
(_tao_refresh_worker / _maybe_kick_tao_refresh / _tao_state_for_snapshot),
the last-good table bittensor_balance_snapshot, the TAO price fallback and
the token rows (_bittensor_rows), plus the get_portfolio_data wiring.

Never real network: _taostats_fetch, _get_coingecko_price and the spawner
are replaced per test. Only the public Substrate dev addresses are used; the
API key is a dummy that must never surface. Real init_db() on a tmp_path
SQLite file (portfolio_db.get_db_path monkeypatched)."""
import copy
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
import requests

import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp
from src.connectors import taostats as ts

ALICE = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
BOB = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
EVM = "0x1111111111111111111111111111111111111111"
DUMMY_KEY = "dummy-key-123"
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "taostats_account_5_subnets.json")
AS_OF = datetime(2026, 9, 30, 1, 29, 24, tzinfo=timezone.utc)
TOTAL_TAO = 12.577601758
ROW_SYMBOLS = ["TAO", "TAO reserved", "SN51 alpha", "SN80 alpha", "SN105 alpha", "SN107 alpha", "SN110 alpha"]


def _holdings(address=ALICE, as_of=None):
    with open(FIXTURE) as f:
        payload = json.load(f)
    payload["data"][0]["address"]["ss58"] = address
    for a in payload["data"][0]["alpha_balances"]:
        a["coldkey"] = address
    if as_of is not None:
        payload["data"][0]["timestamp"] = as_of
    return ts.parse_account(payload, address)


@pytest.fixture(autouse=True)
def tao_state(monkeypatch):
    """Fresh cache state per test; no spawner threads, no CoinGecko, no key."""
    monkeypatch.setattr(wp, "_TAO_CACHE", {"fetched_at": None, "wallets": {}, "wallet_errors": {}, "error": None,
                                           "tao_usd": None, "tao_usd_at": None})
    monkeypatch.setattr(wp, "_TAO_IN_FLIGHT", False)
    monkeypatch.setattr(wp, "_TAO_LAST_KICK", {"at": None})
    monkeypatch.setattr(wp, "_spawn_tao_refresh_thread", lambda wallets: setattr(wp, "_TAO_IN_FLIGHT", False))
    monkeypatch.setattr(wp, "_get_coingecko_price", lambda symbol: None)
    monkeypatch.delenv("TAOSTATS_API_KEY", raising=False)


@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    return path


def _prime(holdings=None, price=300.0, price_at=None, wallet=ALICE):
    if holdings is not None:
        wp._TAO_CACHE["wallets"][wallet] = {"holdings": holdings, "fetched_at": AS_OF.isoformat()}
    if price is not None:
        wp._TAO_CACHE["tao_usd"] = price
        wp._TAO_CACHE["tao_usd_at"] = (price_at or AS_OF).isoformat()


def _rows(now, wallets=(ALICE,), config=None):
    return wp._bittensor_rows(list(wallets), config or {ALICE: {"label": "TAO main", "type": "bittensor"}}, now)


def _db_rows(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT wallet, data_as_of, block_number, fetched_at, holdings_json "
                            "FROM bittensor_balance_snapshot ORDER BY wallet").fetchall()
    finally:
        conn.close()


# ── _bittensor_rows ───────────────────────────────────────────────────────

def test_fresh_rows_and_value(dbpath):
    now = AS_OF + timedelta(minutes=20)
    _prime(_holdings(), price_at=now)
    rows, status = _rows(now)
    assert [r["symbol"] for r in rows] == ROW_SYMBOLS
    assert sum(r["value_usd"] for r in rows) == pytest.approx(TOTAL_TAO * 300.0, abs=1e-6)
    assert all(r["chain"] == "Bittensor" and r["source"] == "taostats" and r["wallet"] == ALICE
               and r["wallet_label"] == "TAO main" for r in rows)
    assert all("contract" not in r and "token_address" not in r for r in rows)
    assert all(r["tao_stale"] is False for r in rows)
    assert all(all(ord(c) < 128 for c in r["symbol"]) for r in rows)
    sn105 = next(r for r in rows if r["symbol"] == "SN105 alpha")
    assert (sn105["netuid"], sn105["hotkeys"], sn105["balance"]) == (105, 1, pytest.approx(327.679279493))
    assert sn105["value_usd"] == pytest.approx(2.150880237 * 300.0)
    st = status["wallets"][ALICE]
    assert (st["state"], st["price_source"], st["diff_tao"]) == ("fresh", "coingecko", 0.0)
    assert st["tao_amount"] == pytest.approx(TOTAL_TAO) and st["value_usd"] == pytest.approx(TOTAL_TAO * 300.0)


def test_stale_rows_flagged(dbpath):
    now = AS_OF + timedelta(hours=5)
    _prime(_holdings(), price_at=now)
    rows, status = _rows(now)
    assert [r["symbol"] for r in rows] == ROW_SYMBOLS and all(r["tao_stale"] is True for r in rows)
    assert status["wallets"][ALICE]["state"] == "stale"
    assert status["wallets"][ALICE]["age_hours"] == pytest.approx(5.0)


def test_over_24h_is_unavailable_with_last_value(dbpath):
    now = AS_OF + timedelta(hours=25)
    _prime(_holdings(), price_at=now)
    rows, status = _rows(now)
    st = status["wallets"][ALICE]
    assert rows == []
    assert (st["state"], st["reason"]) == ("unavailable", "Taostats data over 24 h old")
    assert st["value_usd"] == pytest.approx(TOTAL_TAO * 300.0)


def test_no_data_is_unavailable(dbpath):
    wp._TAO_CACHE["error"] = "TAOSTATS_API_KEY not set"
    rows, status = _rows(AS_OF)
    st = status["wallets"][ALICE]
    assert rows == [] and (st["state"], st["reason"]) == ("unavailable", "no Taostats data yet")
    assert st["error"] == "TAOSTATS_API_KEY not set"


def test_price_falls_back_to_market_snapshot_then_none(dbpath):
    now = AS_OF + timedelta(minutes=20)
    _prime(_holdings(), price_at=now - timedelta(hours=2))            # CoinGecko price too old
    conn = sqlite3.connect(dbpath)
    conn.execute("INSERT INTO market_snapshots (timestamp, session, tao_price) VALUES (?, 'x', ?)",
                 ((now - timedelta(hours=3)).replace(tzinfo=None).isoformat(), 280.0))
    conn.commit()
    conn.close()
    rows, status = _rows(now)
    st = status["wallets"][ALICE]
    assert (st["state"], st["price_usd"], st["price_source"]) == ("fresh", 280.0, "market snapshot")
    assert sum(r["value_usd"] for r in rows) == pytest.approx(TOTAL_TAO * 280.0, abs=1e-6)

    later = now + timedelta(hours=4)                                  # market row now 7 h old
    wp._TAO_CACHE["wallets"][ALICE]["holdings"] = _holdings(as_of=later.strftime("%Y-%m-%dT%H:%M:%SZ"))
    rows, status = _rows(later)
    assert rows == [] and status["wallets"][ALICE]["reason"] == "no TAO price"


def test_parts_below_total_add_a_tao_other_row(dbpath):
    now = AS_OF + timedelta(minutes=20)
    h = _holdings()
    h["total_rao"] += 5_000_000
    h["diff_rao"] = 5_000_000
    _prime(h, price_at=now)
    rows, status = _rows(now)
    other = rows[-1]
    assert other["symbol"] == "TAO other" and other["balance"] == pytest.approx(0.005)
    assert status["wallets"][ALICE]["diff_tao"] == pytest.approx(0.005)
    assert sum(r["value_usd"] for r in rows) == pytest.approx((TOTAL_TAO + 0.005) * 300.0, abs=1e-6)


def test_restart_reads_last_good_row_from_db(dbpath):
    now = AS_OF + timedelta(minutes=20)
    wp._tao_snapshot_upsert(ALICE, _holdings(), AS_OF.isoformat())
    _prime(None, price_at=now)                                        # empty wallets cache
    rows, status = _rows(now)
    assert [r["symbol"] for r in rows] == ROW_SYMBOLS and status["wallets"][ALICE]["state"] == "fresh"


# ── _tao_refresh_worker ───────────────────────────────────────────────────

def test_worker_success_updates_cache_db_and_price(dbpath, monkeypatch):
    monkeypatch.setenv("TAOSTATS_API_KEY", DUMMY_KEY)
    monkeypatch.setattr(wp, "_get_coingecko_price", lambda symbol: 310.0 if symbol == "TAO" else None)
    got = []
    monkeypatch.setattr(wp, "_taostats_fetch", lambda addr, key: got.append((addr, key)) or _holdings(addr))
    sleeps = []
    now = AS_OF + timedelta(minutes=15)
    wp._tao_refresh_worker([ALICE, BOB], now_utc=now, sleep=sleeps.append)
    assert got == [(ALICE, DUMMY_KEY), (BOB, DUMMY_KEY)] and sleeps == [13]
    cache = wp._TAO_CACHE
    assert set(cache["wallets"]) == {ALICE, BOB} and cache["fetched_at"] == now.isoformat()
    assert (cache["error"], cache["wallet_errors"], cache["tao_usd"], cache["tao_usd_at"]) == (
        None, {}, 310.0, now.isoformat())
    assert [(r[0], r[1], r[2], r[3]) for r in _db_rows(dbpath)] == [
        (BOB, "2026-09-30T01:29:24Z", 9177434, now.isoformat()), (ALICE, "2026-09-30T01:29:24Z", 9177434, now.isoformat())]
    assert wp._TAO_IN_FLIGHT is False


def test_worker_failure_keeps_prior_entry_and_db_row(dbpath, monkeypatch):
    monkeypatch.setenv("TAOSTATS_API_KEY", DUMMY_KEY)
    prior = {"holdings": _holdings(), "fetched_at": AS_OF.isoformat()}
    wp._TAO_CACHE["wallets"][ALICE] = copy.deepcopy(prior)
    wp._tao_snapshot_upsert(ALICE, prior["holdings"], AS_OF.isoformat())
    before = _db_rows(dbpath)

    def fail(addr, key):
        raise ts.TaostatsError("HTTP 500")
    monkeypatch.setattr(wp, "_taostats_fetch", fail)
    wp._tao_refresh_worker([ALICE], now_utc=AS_OF + timedelta(hours=1))
    assert wp._TAO_CACHE["wallets"][ALICE] == prior
    assert wp._TAO_CACHE["wallet_errors"] == {ALICE: "HTTP 500"}
    assert wp._TAO_CACHE["error"] == "every wallet failed: HTTP 500" and wp._TAO_CACHE["fetched_at"] is None
    assert _db_rows(dbpath) == before


def test_missing_key_makes_no_taostats_call(dbpath, monkeypatch):
    monkeypatch.setattr(wp, "_taostats_fetch", lambda *a: (_ for _ in ()).throw(AssertionError("fetched")))
    wp._tao_refresh_worker([ALICE], now_utc=AS_OF)
    assert wp._TAO_CACHE["error"] == "TAOSTATS_API_KEY not set" and wp._TAO_IN_FLIGHT is False


def test_key_never_surfaces(dbpath, monkeypatch, capsys):
    monkeypatch.setenv("TAOSTATS_API_KEY", DUMMY_KEY)

    def boom(*a, **k):
        raise ConnectionError("connect failed for " + DUMMY_KEY)
    monkeypatch.setattr(requests, "get", boom)                        # the real connector path
    wp._tao_refresh_worker([ALICE], now_utc=AS_OF)
    assert wp._TAO_CACHE["wallet_errors"] == {ALICE: "ConnectionError"}

    def boom2(addr, key):
        raise RuntimeError("unexpected " + key)
    monkeypatch.setattr(wp, "_taostats_fetch", boom2)
    wp._tao_refresh_worker([ALICE], now_utc=AS_OF)
    assert wp._TAO_CACHE["wallet_errors"] == {ALICE: "RuntimeError"}
    out = capsys.readouterr()
    assert DUMMY_KEY not in out.out and DUMMY_KEY not in out.err
    assert DUMMY_KEY not in repr(wp._TAO_CACHE)
    assert all(DUMMY_KEY not in repr(r) for r in _db_rows(dbpath))


# ── kick + snapshot freshen ───────────────────────────────────────────────

@pytest.fixture
def spawns(monkeypatch):
    calls = []
    monkeypatch.setattr(wp, "_spawn_tao_refresh_thread", lambda wallets: calls.append(list(wallets)))
    monkeypatch.setattr(wp, "_bittensor_wallets", lambda: [ALICE])
    return calls


def test_kick_respects_ttl_in_flight_and_cooldown(spawns, monkeypatch):
    now = AS_OF
    assert wp._maybe_kick_tao_refresh(now) is True and spawns == [[ALICE]]
    assert wp._maybe_kick_tao_refresh(now + timedelta(minutes=30)) is False            # in flight
    wp._TAO_IN_FLIGHT = False
    assert wp._maybe_kick_tao_refresh(now + timedelta(minutes=5)) is False             # cooldown
    wp._TAO_CACHE["fetched_at"] = (now + timedelta(minutes=20)).isoformat()
    assert wp._maybe_kick_tao_refresh(now + timedelta(minutes=30)) is False            # fresh (10 min)
    assert wp._maybe_kick_tao_refresh(now + timedelta(minutes=36)) is True             # stale, cooled down
    assert len(spawns) == 2
    monkeypatch.setattr(wp, "_bittensor_wallets", lambda: [])
    wp._TAO_IN_FLIGHT = False
    assert wp._maybe_kick_tao_refresh(now + timedelta(hours=5)) is False and len(spawns) == 2


def test_snapshot_freshen_inline_fresh_and_waiting(spawns, monkeypatch):
    ran = []

    def worker(wallets, now_utc=None, sleep=None):
        ran.append(list(wallets))
        wp._TAO_CACHE["fetched_at"] = AS_OF.isoformat()
        wp._TAO_IN_FLIGHT = False
    monkeypatch.setattr(wp, "_tao_refresh_worker", worker)
    state = wp._tao_state_for_snapshot(AS_OF)
    assert ran == [[ALICE]] and spawns == [] and state["fetched_at"] == AS_OF.isoformat()
    wp._tao_state_for_snapshot(AS_OF + timedelta(minutes=5))                           # fresh: no refetch
    assert ran == [[ALICE]]

    wp._TAO_IN_FLIGHT = True
    sleeps = []

    def sleep(sec):
        sleeps.append(sec)
        if len(sleeps) == 2:
            wp._TAO_IN_FLIGHT = False
    wp._tao_state_for_snapshot(AS_OF + timedelta(hours=1), sleep=sleep)
    assert sleeps == [wp.HL_SNAPSHOT_POLL_SECONDS] * 2 and ran == [[ALICE]]


# ── POST /api/wallets kick ────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    monkeypatch.setattr(wp, "WALLET_CONFIG_FILE", str(tmp_path / "wallet_config.json"))
    monkeypatch.setattr(wp, "ENV_FILE", str(tmp_path / ".env"))
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def test_adding_a_bittensor_wallet_kicks_the_refresh(client, monkeypatch):
    kicks = []
    monkeypatch.setattr(wp, "_maybe_kick_tao_refresh", lambda now_utc: kicks.append(now_utc) or True)
    assert client.post("/api/wallets", json={"address": EVM, "label": ""}).status_code == 200
    assert kicks == []
    assert client.post("/api/wallets", json={"address": ALICE, "label": ""}).status_code == 200
    assert len(kicks) == 1


# ── get_portfolio_data wiring ─────────────────────────────────────────────

def test_get_portfolio_data_adds_rows_and_status_never_api_failures(dbpath, monkeypatch):
    now = datetime.now(timezone.utc)
    as_of = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _prime(_holdings(as_of=as_of), price_at=now)
    monkeypatch.setattr(wp, "_portfolio_cache", None)
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [EVM, ALICE])
    monkeypatch.setattr(wp, "load_wallet_config",
                        lambda: {EVM: {"label": "Main"}, ALICE: {"label": "TAO main", "type": "bittensor"}})
    monkeypatch.setattr(wp.ZerionConnector, "is_configured", lambda self: True)
    zerion_seen = []
    monkeypatch.setattr(wp.ZerionConnector, "get_wallet_positions",
                        lambda self, wallet: zerion_seen.append(wallet) or [])
    monkeypatch.setattr(wp.ZerionConnector, "get_wallet_transactions", lambda self, *a, **k: [])
    import src.models
    monkeypatch.setattr(src.models, "get_web3", lambda *a, **k: None)
    monkeypatch.setattr(wp, "build_custom_token_rows", lambda *a, **k: [])

    def _no_network(*a, **k):
        raise AssertionError("network call attempted")
    monkeypatch.setattr(requests, "get", _no_network)
    monkeypatch.setattr(requests, "post", _no_network)
    monkeypatch.setattr(requests.Session, "request", _no_network)
    try:
        data = wp.get_portfolio_data(force_refresh=True)
    finally:
        wp._portfolio_cache = None
    assert ALICE not in zerion_seen and EVM in zerion_seen
    assert [t["symbol"] for t in data["tokens"] if t.get("chain") == "Bittensor"] == ROW_SYMBOLS
    assert data["bittensor"]["wallets"][ALICE]["state"] == "fresh"
    assert data["total_tokens_value"] == pytest.approx(TOTAL_TAO * 300.0, abs=1e-6)
    assert data["api_failures"] == []
