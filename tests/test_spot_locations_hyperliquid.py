"""Landing 85: Hyperliquid spot balances in GET /api/spot/locations.

A symbol-keyed open spot position (no chain and contract: the BTC / ETH / SOL
kind) is also matched against the Hyperliquid spot balances in the accounts
cache; that wallet's entry reads "<label> App". Cache only: no call, no
refresh kick. A position with a chain and contract never matches a coin
there. Real init_db() on a tmp_path SQLite file; wallets are made-up test
strings."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

T0 = datetime(2026, 10, 10, 12, 0, 0)
NOW = (T0 + timedelta(hours=1)).replace(tzinfo=timezone.utc)
RM = "0x" + "a1" * 20
RABBY = "0x" + "b2" * 20
HIDDEN = "0x" + "c3" * 20
CHAIN_WALLET = "chain_wallet"
EVM = "0x" + "ab" * 20


@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    return path


@pytest.fixture(autouse=True)
def now(monkeypatch):
    monkeypatch.setattr(wp, "_spot_location_now", lambda: NOW)


@pytest.fixture
def spawned(monkeypatch):
    calls = []
    monkeypatch.setattr(wp, "_spawn_hl_accounts_refresh_thread", lambda wallets: calls.append(list(wallets)))
    return calls


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _config(monkeypatch, **extra):
    cfg = {RM: {"label": "Hyperliquid RM"}, RABBY: {"label": "Rabby (Hyperliquid)"},
           HIDDEN: {"label": "Old wallet", "hidden": True}, CHAIN_WALLET: {"label": "Desktop Hot"}}
    cfg.update(extra)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: cfg)


def _positions(monkeypatch, *specs):
    """specs: (key, symbol, units); key = (chain, address) or a symbol string."""
    out = {}
    for key, symbol, units in specs:
        chain, addr = key if isinstance(key, tuple) else ("", "")
        out[key] = {"symbol": symbol, "chain": chain, "contract_address": addr, "units": units,
                    "position_key": wp._stringify_spot_position_key(key)}
    monkeypatch.setattr(wp, "_calculate_spot_fifo", lambda conn: (out, {}))


def _run(path, wallet, hours=0):
    conn = sqlite3.connect(path)
    cur = conn.execute("INSERT INTO portfolio_snapshots (user_id, timestamp, wallet, status) "
                       "VALUES (1, ?, ?, 'completed')", ((T0 + timedelta(hours=hours)).isoformat(), wallet))
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def _tok(path, snap_id, wallet, chain, symbol, address, balance):
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO token_snapshots (snapshot_id, user_id, timestamp, wallet, chain, symbol, token_address, "
        "balance, price_usd, value_usd) VALUES (?, 1, ?, ?, ?, ?, ?, ?, 1, ?)",
        (snap_id, T0.isoformat(), wallet, chain, symbol, address, balance, balance))
    conn.commit()
    conn.close()


def _cache(monkeypatch, wallets, fetched_at=None, error=None):
    at = (NOW - timedelta(minutes=10)).isoformat() if fetched_at is None else fetched_at
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_CACHE", {"fetched_at": at, "wallets": wallets, "error": error})


def _coin(coin, amount):
    return {"coin": coin, "amount": amount, "price": 1.0, "value": amount}


def _get(client):
    r = client.get("/api/spot/locations")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _base(dbpath):
    """One completed run for the on-chain wallet, so the route has a snapshot to answer from."""
    return _run(dbpath, CHAIN_WALLET)


def test_a_symbol_keyed_position_is_found_on_hyperliquid_by_its_unit_alias(client, dbpath, monkeypatch, spawned):
    _config(monkeypatch)
    _positions(monkeypatch, ("ETH", "ETH", 3.0))
    _base(dbpath)
    _cache(monkeypatch, {RM: {"spot": [_coin("UETH", 2.5), _coin("USDC", 50.0)]}})
    entry = _get(client)["positions"]["ETH"]
    assert entry["status"] == "found"
    assert entry["wallets"] == [{"label": "Hyperliquid RM App", "units": 2.5,
                                 "as_of": (NOW - timedelta(minutes=10)).isoformat(), "stale": False}]
    assert spawned == []                                  # cache only: no refresh kick


def test_the_plain_coin_name_matches_and_same_wallet_coins_add_up(client, dbpath, monkeypatch, spawned):
    _config(monkeypatch)
    _positions(monkeypatch, ("ETH", "ETH", 4.0))
    _base(dbpath)
    _cache(monkeypatch, {RM: {"spot": [_coin("ETH", 1.0), _coin("UETH", 2.0)]}, RABBY: {"spot": [_coin("UETH", 0.5)]}})
    wallets = _get(client)["positions"]["ETH"]["wallets"]
    assert [(w["label"], w["units"]) for w in wallets] == [("Hyperliquid RM App", 3.0), ("Rabby (Hyperliquid) App", 0.5)]


def test_it_sits_beside_an_on_chain_wallet_largest_first(client, dbpath, monkeypatch, spawned):
    _config(monkeypatch)
    _positions(monkeypatch, ("ETH", "ETH", 4.0))
    s = _base(dbpath)
    _tok(dbpath, s, CHAIN_WALLET, "Ethereum", "ETH", "", 1.5)
    _cache(monkeypatch, {RM: {"spot": [_coin("UETH", 2.2)]}})
    labels = [w["label"] for w in _get(client)["positions"]["ETH"]["wallets"]]
    assert labels == ["Hyperliquid RM App", "Desktop Hot"]


def test_a_position_with_a_chain_and_contract_never_matches_a_coin(client, dbpath, monkeypatch, spawned):
    _config(monkeypatch)
    _positions(monkeypatch, (("base", EVM), "ETH", 3.0), (("base", "0x" + "cd" * 20), "HYPE", 3.0))
    _base(dbpath)
    _cache(monkeypatch, {RM: {"spot": [_coin("UETH", 2.5), _coin("HYPE", 9.0)]}})
    body = _get(client)
    assert body["positions"]["base " + EVM]["status"] == "not_found"
    assert body["positions"]["base 0x" + "cd" * 20]["status"] == "not_found"


def test_a_non_native_symbol_held_only_on_hyperliquid_is_listed(client, dbpath, monkeypatch, spawned):
    _config(monkeypatch)
    _positions(monkeypatch, ("HYPE", "HYPE", 10.0), ("ZZZ", "ZZZ", 10.0))
    _base(dbpath)
    _cache(monkeypatch, {RABBY: {"spot": [_coin("HYPE", 9.0)]}})
    positions = _get(client)["positions"]
    assert [w["label"] for w in positions["HYPE"]["wallets"]] == ["Rabby (Hyperliquid) App"]
    assert "ZZZ" not in positions                         # not native, not found anywhere: unknown, as before


def test_dust_below_the_one_percent_floor_is_not_listed(client, dbpath, monkeypatch, spawned):
    _config(monkeypatch)
    _positions(monkeypatch, ("ETH", "ETH", 100.0))
    _base(dbpath)
    _cache(monkeypatch, {RM: {"spot": [_coin("UETH", 0.5)]}})              # 0.5% of the position
    assert _get(client)["positions"]["ETH"]["status"] == "not_found"


def test_hidden_wallets_are_left_out(client, dbpath, monkeypatch, spawned):
    _config(monkeypatch)
    _positions(monkeypatch, ("ETH", "ETH", 3.0))
    _base(dbpath)
    _cache(monkeypatch, {HIDDEN: {"spot": [_coin("UETH", 2.5)]}})
    assert _get(client)["positions"]["ETH"]["status"] == "not_found"


def test_an_old_cache_or_a_failed_wallet_refresh_is_marked_stale(client, dbpath, monkeypatch, spawned):
    _config(monkeypatch)
    _positions(monkeypatch, ("ETH", "ETH", 3.0))
    _base(dbpath)
    old = (NOW - timedelta(hours=30)).isoformat()
    _cache(monkeypatch, {RM: {"spot": [_coin("UETH", 2.5)]}}, fetched_at=old)
    w = _get(client)["positions"]["ETH"]["wallets"][0]
    assert w["stale"] is True and w["as_of"] == old
    _cache(monkeypatch, {RM: {"spot": [_coin("UETH", 2.5)], "stale": True}})
    assert _get(client)["positions"]["ETH"]["wallets"][0]["stale"] is True


def test_a_cold_cache_changes_nothing(client, dbpath, monkeypatch, spawned):
    _config(monkeypatch)
    _positions(monkeypatch, ("ETH", "ETH", 3.0))
    _base(dbpath)
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    assert _get(client)["positions"]["ETH"] == {"status": "not_found", "wallets": []}
    assert spawned == []


def test_an_unlabelled_wallet_reads_unlabelled_wallet_app(client, dbpath, monkeypatch, spawned):
    _config(monkeypatch, **{RM: {}})
    _positions(monkeypatch, ("ETH", "ETH", 3.0))
    _base(dbpath)
    _cache(monkeypatch, {RM: {"spot": [_coin("UETH", 2.5)]}})
    assert _get(client)["positions"]["ETH"]["wallets"][0]["label"] == "Unlabelled wallet App"


def test_a_position_keyed_by_the_coin_name_matches_that_coin_alone(client, dbpath, monkeypatch, spawned):
    _config(monkeypatch)
    _positions(monkeypatch, ("UETH", "UETH", 3.0), ("ETH", "ETH", 3.0))
    _base(dbpath)
    _cache(monkeypatch, {RM: {"spot": [_coin("UETH", 2.5)]}, RABBY: {"spot": [_coin("ETH", 1.0)]}})
    positions = _get(client)["positions"]
    assert [(w["label"], w["units"]) for w in positions["UETH"]["wallets"]] == [("Hyperliquid RM App", 2.5)]
    assert [(w["label"], w["units"]) for w in positions["ETH"]["wallets"]] == [
        ("Hyperliquid RM App", 2.5), ("Rabby (Hyperliquid) App", 1.0)]


def test_hyperliquid_usdc_is_margin_and_never_a_holding(client, dbpath, monkeypatch, spawned):
    _config(monkeypatch)
    _positions(monkeypatch, ("USDC", "USDC", 100.0), ("ETH", "ETH", 3.0))
    _base(dbpath)
    _cache(monkeypatch, {RM: {"spot": [_coin("USDC", 5000.0), _coin("UETH", 2.5)]}})
    positions = _get(client)["positions"]
    assert "USDC" not in positions                      # not native, found nowhere: unknown, as without Hyperliquid
    assert [w["units"] for w in positions["ETH"]["wallets"]] == [2.5]


def test_a_failure_in_the_hyperliquid_part_leaves_the_wallet_line_as_it_was(client, dbpath, monkeypatch, spawned):
    _config(monkeypatch)
    _positions(monkeypatch, ("ETH", "ETH", 3.0))
    s = _base(dbpath)
    _tok(dbpath, s, CHAIN_WALLET, "Ethereum", "ETH", "", 1.5)
    _cache(monkeypatch, {RM: {"spot": [_coin("UETH", 2.5)]}})

    def boom(state, config, visible):
        raise AttributeError("odd cache shape " + RM)
    monkeypatch.setattr(wp, "_hl_spot_holdings", boom)
    body = _get(client)
    assert [w["label"] for w in body["positions"]["ETH"]["wallets"]] == ["Desktop Hot"]
    assert RM not in str(body)


def test_a_failed_whole_refresh_marks_the_rows_stale_even_when_the_cache_is_recent(client, dbpath, monkeypatch, spawned):
    _config(monkeypatch)
    _positions(monkeypatch, ("ETH", "ETH", 3.0))
    _base(dbpath)
    _cache(monkeypatch, {RM: {"spot": [_coin("UETH", 2.5)]}}, error="Hyperliquid price call failed")
    assert _get(client)["positions"]["ETH"]["wallets"][0]["stale"] is True


def test_with_no_completed_snapshot_the_route_answers_empty_even_with_a_warm_cache(client, dbpath, monkeypatch, spawned):
    """Known limit, pinned so a change is deliberate: the Hyperliquid part is
    skipped when no wallet has a completed snapshot."""
    _config(monkeypatch)
    _positions(monkeypatch, ("ETH", "ETH", 3.0))
    _cache(monkeypatch, {RM: {"spot": [_coin("UETH", 2.5)]}})
    assert _get(client) == {"as_of": None, "stale": False, "old_wallets": [], "positions": {}}
