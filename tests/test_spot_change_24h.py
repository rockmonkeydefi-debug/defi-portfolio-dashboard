"""GET /api/spot/change-24h: the 24h price change per open spot position from
snapshot history (Dashboard "24h movers", Sep 29).

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched); _calculate_spot_fifo is monkeypatched to return controlled
open positions. Read-only route, no network."""
import sqlite3
from datetime import datetime, timedelta

import pytest

import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

T_NOW = datetime(2026, 9, 29, 12, 0, 0)
EVM = "0x" + "ab" * 20
SOL_A = "So1anaMintAbc111111111111111111111111111111"
SOL_B = "So1anaMintABC111111111111111111111111111111"      # differs only by case


@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    return path


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _iso(dt):
    return dt.isoformat()


def _runs(path, *offsets_h):
    """One completed portfolio_snapshots run at T_NOW + each offset (hours)."""
    conn = sqlite3.connect(path)
    for h in offsets_h:
        conn.execute("INSERT INTO portfolio_snapshots (user_id, timestamp, wallet, status) VALUES (1, ?, 'w', 'completed')",
                     (_iso(T_NOW + timedelta(hours=h)),))
    conn.commit()
    conn.close()


def _tok(path, offset_h, chain, symbol, address, price, value=100.0):
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO token_snapshots (snapshot_id, user_id, timestamp, wallet, chain, symbol, token_address, balance, "
        "price_usd, value_usd) VALUES (1, 1, ?, 'w', ?, ?, ?, 1, ?, ?)",
        (_iso(T_NOW + timedelta(hours=offset_h)), chain, symbol, address, price, value))
    conn.commit()
    conn.close()


def _market(path, offset_h, **prices):
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO market_snapshots (timestamp, session, btc_price, eth_price, sol_price) VALUES (?, 'x', ?, ?, ?)",
                 (_iso(T_NOW + timedelta(hours=offset_h)), prices.get("btc"), prices.get("eth"), prices.get("sol")))
    conn.commit()
    conn.close()


def _positions(monkeypatch, *keys):
    """Open positions for the given FIFO keys: (chain, address) tuples or
    plain symbol strings."""
    out = {}
    for k in keys:
        if isinstance(k, tuple):
            out[k] = {"symbol": "TOK", "chain": k[0], "contract_address": k[1],
                      "position_key": wp._stringify_spot_position_key(k)}
        else:
            out[k] = {"symbol": k, "chain": "", "contract_address": "", "position_key": k}
    monkeypatch.setattr(wp, "_calculate_spot_fifo", lambda conn: (out, {}))


def _get(client):
    r = client.get("/api/spot/change-24h")
    assert r.status_code == 200
    return r.get_json()


def test_evm_position_pct_and_case_insensitive_address(client, dbpath, monkeypatch):
    _runs(dbpath, 0, -24)
    _tok(dbpath, 0, "Base", "TOK", EVM.upper().replace("0X", "0x"), 2.0)
    _tok(dbpath, -24, "Base", "TOK", EVM, 1.6)
    _positions(monkeypatch, ("base", EVM))
    body = _get(client)
    assert body["as_of"] == "2026-09-29T12:00:00+00:00" and body["then"] == "2026-09-28T12:00:00+00:00"
    assert body["positions"] == {f"base {EVM}": {"pct": pytest.approx(25.0), "price_now": 2.0, "price_then": 1.6,
                                                 "source": "wallet snapshots", "reason": None}}


def test_solana_address_matches_exact_case_only(client, dbpath, monkeypatch):
    _runs(dbpath, 0, -24)
    for addr, now, then in ((SOL_A, 3.0, 2.0), (SOL_B, 50.0, 1.0)):
        _tok(dbpath, 0, "Solana", "X", addr, now)
        _tok(dbpath, -24, "Solana", "X", addr, then)
    _positions(monkeypatch, ("solana", SOL_A))
    got = _get(client)["positions"][f"solana {SOL_A}"]
    assert (got["price_now"], got["price_then"], got["pct"]) == (3.0, 2.0, pytest.approx(50.0))


def test_bsc_alias_matches_binance_smart_chain(client, dbpath, monkeypatch):
    _runs(dbpath, 0, -24)
    _tok(dbpath, 0, "Binance-smart-chain", "TOK", EVM, 1.1)
    _tok(dbpath, -24, "Binance-smart-chain", "TOK", EVM, 1.0)
    _positions(monkeypatch, ("bsc", EVM))
    assert _get(client)["positions"][f"bsc {EVM}"]["pct"] == pytest.approx(10.0)


def test_same_address_on_two_chains_uses_only_its_own_chain(client, dbpath, monkeypatch):
    _runs(dbpath, 0, -24)
    _tok(dbpath, 0, "Robinhood", "TOK", EVM, 4.0)
    _tok(dbpath, -24, "Robinhood", "TOK", EVM, 2.0)
    _tok(dbpath, 0, "Base", "TOK", EVM, 9.0)
    _tok(dbpath, -24, "Base", "TOK", EVM, 10.0)
    _positions(monkeypatch, ("robinhood", EVM), ("base", EVM))
    pos = _get(client)["positions"]
    assert pos[f"robinhood {EVM}"]["pct"] == pytest.approx(100.0)
    assert pos[f"base {EVM}"]["pct"] == pytest.approx(-10.0)


def test_symbol_eth_uses_market_snapshots(client, dbpath, monkeypatch):
    _runs(dbpath, 0, -24)
    _market(dbpath, -27, eth=1000.0)          # outside +-4 h of the target: ignored
    _market(dbpath, -23, eth=2500.0)          # closest to latest - 24 h
    _market(dbpath, -1, eth=2750.0)
    _market(dbpath, 0, btc=60000.0)           # no ETH price in the newest row
    _positions(monkeypatch, "ETH")
    body = _get(client)
    assert body["positions"] == {"ETH": {"pct": pytest.approx(10.0), "price_now": 2750.0, "price_then": 2500.0,
                                         "source": "market snapshots", "reason": None}}


def test_symbol_position_median_skips_spam_rows(client, dbpath, monkeypatch):
    _runs(dbpath, 0, -24)
    _tok(dbpath, 0, "Hyperevm", "HYPE", "", 97.0, value=900.0)
    _tok(dbpath, 0, "Base", "HYPE", "0xspam", 0.0001, value=0.0)
    _tok(dbpath, -24, "Hyperevm", "HYPE", "", 90.0, value=850.0)
    _positions(monkeypatch, "HYPE")
    got = _get(client)["positions"]["HYPE"]
    assert (got["price_now"], got["price_then"]) == (97.0, 90.0)
    assert got["pct"] == pytest.approx((97.0 - 90.0) / 90.0 * 100)


def test_jump_over_10x_is_a_suspected_glitch(client, dbpath, monkeypatch):
    _runs(dbpath, 0, -24)
    _tok(dbpath, 0, "Base", "TOK", EVM, 1.2)
    _tok(dbpath, -24, "Base", "TOK", EVM, 0.1)
    _positions(monkeypatch, ("base", EVM))
    body = _get(client)
    assert body["positions"] == {f"base {EVM}": {"pct": None, "price_now": 1.2, "price_then": 0.1, "source": None,
                                                 "reason": "jump over 10× (suspected glitch)"}}


def test_no_run_20_to_28h_earlier(client, dbpath, monkeypatch):
    _runs(dbpath, 0, -12, -30)
    _tok(dbpath, 0, "Base", "TOK", EVM, 2.0)
    _positions(monkeypatch, ("base", EVM), "ETH")
    body = _get(client)
    assert body["then"] is None
    assert {k: v["reason"] for k, v in body["positions"].items()} == {
        f"base {EVM}": "no snapshot 20–28 h earlier", "ETH": "no snapshot 20–28 h earlier"}


def test_position_without_rows_and_unpriced_snapshot(client, dbpath, monkeypatch):
    _runs(dbpath, 0, -24)
    other = "0x" + "cd" * 20
    _tok(dbpath, 0, "Base", "TOK", other, 2.0)
    _tok(dbpath, -24, "Base", "TOK", other, 0.0)
    _positions(monkeypatch, ("base", EVM), ("base", other))
    pos = _get(client)["positions"]
    assert pos[f"base {EVM}"]["reason"] == "not in wallet snapshots" and pos[f"base {EVM}"]["pct"] is None
    assert pos[f"base {other}"]["reason"] == "unpriced in a snapshot"


def test_t_then_is_the_run_closest_to_24h_before(client, dbpath, monkeypatch):
    _runs(dbpath, 0, -21, -25)
    _tok(dbpath, 0, "Base", "TOK", EVM, 2.0)
    _tok(dbpath, -21, "Base", "TOK", EVM, 1.9)
    _tok(dbpath, -25, "Base", "TOK", EVM, 1.0)
    _positions(monkeypatch, ("base", EVM))
    body = _get(client)
    assert body["then"] == "2026-09-28T11:00:00+00:00"
    assert body["positions"][f"base {EVM}"]["price_then"] == 1.0


def test_no_snapshots_at_all(client, dbpath, monkeypatch):
    _positions(monkeypatch, ("base", EVM))
    body = _get(client)
    assert body["as_of"] is None and body["then"] is None
    assert body["positions"][f"base {EVM}"]["reason"] == "no snapshot 20–28 h earlier"


def test_error_returns_500(client, dbpath, monkeypatch):
    def boom(conn):
        raise RuntimeError("fifo down")
    monkeypatch.setattr(wp, "_calculate_spot_fifo", boom)
    r = client.get("/api/spot/change-24h")
    assert r.status_code == 500 and r.get_json() == {"error": "fifo down"}
