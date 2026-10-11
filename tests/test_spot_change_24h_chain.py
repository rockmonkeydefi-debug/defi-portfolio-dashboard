"""GET /api/spot/change-24h: chains named by their display label (Oct 11).

Custom-token rows in token_snapshots carry the CUSTOM_TOKEN_CHAINS label
("Robinhood Chain"), while open spot positions are keyed by the chain key
("robinhood"). The route used _spot_norm_chain alone, which turns the label
into "robinhood-chain", so every Robinhood Chain position read "not in wallet
snapshots" and dropped out of the Dashboard's 24h movers. It now compares
chains with _spot_location_chain (Landing 26), like /api/spot/locations.

Same setup as tests/test_spot_change_24h.py: real init_db() on a tmp_path
SQLite file, _calculate_spot_fifo monkeypatched. Read-only route, no network."""
import sqlite3
from datetime import datetime, timedelta

import pytest

import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

T_NOW = datetime(2026, 10, 11, 12, 0, 0)
EVM = "0x" + "cd" * 20


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


def _runs(path, *offsets_h):
    conn = sqlite3.connect(path)
    for h in offsets_h:
        conn.execute("INSERT INTO portfolio_snapshots (user_id, timestamp, wallet, status) VALUES (1, ?, 'w', 'completed')",
                     ((T_NOW + timedelta(hours=h)).isoformat(),))
    conn.commit()
    conn.close()


def _tok(path, offset_h, chain, address, price, symbol="TOK", value=100.0):
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO token_snapshots (snapshot_id, user_id, timestamp, wallet, chain, symbol, token_address, balance, "
        "price_usd, value_usd) VALUES (1, 1, ?, 'w', ?, ?, ?, 1, ?, ?)",
        ((T_NOW + timedelta(hours=offset_h)).isoformat(), chain, symbol, address, price, value))
    conn.commit()
    conn.close()


def _positions(monkeypatch, *keys):
    out = {k: {"symbol": "TOK", "chain": k[0], "contract_address": k[1],
               "position_key": wp._stringify_spot_position_key(k)} for k in keys}
    monkeypatch.setattr(wp, "_calculate_spot_fifo", lambda conn: (out, {}))


def _get(client):
    r = client.get("/api/spot/change-24h")
    assert r.status_code == 200
    return r.get_json()["positions"]


def test_robinhood_chain_label_row_matches_robinhood_position(client, dbpath, monkeypatch):
    _runs(dbpath, 0, -24)
    _tok(dbpath, 0, "Robinhood Chain", EVM, 3.0)
    _tok(dbpath, -24, "Robinhood Chain", EVM, 2.0)
    _positions(monkeypatch, ("robinhood", EVM))
    assert _get(client) == {f"robinhood {EVM}": {"pct": pytest.approx(50.0), "price_now": 3.0, "price_then": 2.0,
                                                 "source": "wallet snapshots", "reason": None}}


def test_label_match_ignores_case_and_surrounding_spaces(client, dbpath, monkeypatch):
    _runs(dbpath, 0, -24)
    _tok(dbpath, 0, " robinhood CHAIN ", EVM, 1.2)
    _tok(dbpath, -24, "ROBINHOOD CHAIN", EVM, 1.0)
    _positions(monkeypatch, ("robinhood", EVM))
    assert _get(client)[f"robinhood {EVM}"]["pct"] == pytest.approx(20.0)


def test_bnb_chain_label_row_matches_bsc_position(client, dbpath, monkeypatch):
    _runs(dbpath, 0, -24)
    _tok(dbpath, 0, "BNB Chain", EVM, 0.9)
    _tok(dbpath, -24, "BNB Chain", EVM, 1.0)
    _positions(monkeypatch, ("bsc", EVM))
    assert _get(client)[f"bsc {EVM}"]["pct"] == pytest.approx(-10.0)


def test_label_and_key_rows_of_one_token_count_together(client, dbpath, monkeypatch):
    # Rows written as the label (custom tokens) and as the bare name both
    # count; the price is the median of the matching rows.
    _runs(dbpath, 0, -24)
    _tok(dbpath, 0, "Robinhood Chain", EVM, 3.0)
    _tok(dbpath, 0, "Robinhood", EVM, 5.0)
    _tok(dbpath, -24, "Robinhood Chain", EVM, 2.0)
    _positions(monkeypatch, ("robinhood", EVM))
    got = _get(client)[f"robinhood {EVM}"]
    assert (got["price_now"], got["price_then"], got["pct"]) == (4.0, 2.0, pytest.approx(100.0))


def test_label_row_does_not_match_a_position_on_another_chain(client, dbpath, monkeypatch):
    _runs(dbpath, 0, -24)
    _tok(dbpath, 0, "Robinhood Chain", EVM, 3.0)
    _tok(dbpath, -24, "Robinhood Chain", EVM, 2.0)
    _positions(monkeypatch, ("base", EVM))
    got = _get(client)[f"base {EVM}"]
    assert got["pct"] is None and got["reason"] == "not in wallet snapshots"


def test_same_address_on_label_chain_and_base_stays_apart(client, dbpath, monkeypatch):
    _runs(dbpath, 0, -24)
    _tok(dbpath, 0, "Robinhood Chain", EVM, 4.0)
    _tok(dbpath, -24, "Robinhood Chain", EVM, 2.0)
    _tok(dbpath, 0, "Base", EVM, 9.0)
    _tok(dbpath, -24, "Base", EVM, 10.0)
    _positions(monkeypatch, ("robinhood", EVM), ("base", EVM))
    pos = _get(client)
    assert pos[f"robinhood {EVM}"]["pct"] == pytest.approx(100.0)
    assert pos[f"base {EVM}"]["pct"] == pytest.approx(-10.0)


@pytest.mark.parametrize("row_chain,pos_chain", [
    ("Base", "base"), ("base", "base"), ("Ethereum", "ethereum"), ("Arbitrum", "arbitrum"),
    ("BSC", "bsc"), ("Binance-smart-chain", "bsc"), ("Robinhood", "robinhood"), ("Sonic", "sonic"),
])
def test_names_that_matched_before_still_match(client, dbpath, monkeypatch, row_chain, pos_chain):
    _runs(dbpath, 0, -24)
    _tok(dbpath, 0, row_chain, EVM, 1.1)
    _tok(dbpath, -24, row_chain, EVM, 1.0)
    _positions(monkeypatch, (pos_chain, EVM))
    assert _get(client)[f"{pos_chain} {EVM}"]["pct"] == pytest.approx(10.0)


def _registry_labels():
    out = []
    for name, registry in (("SPOT_CHAINS", wp.SPOT_CHAINS), ("CUSTOM_TOKEN_CHAINS", wp.CUSTOM_TOKEN_CHAINS)):
        for key, info in registry.items():
            if isinstance(info, dict) and info.get("label"):
                out.append(pytest.param(key, info["label"], id=f"{name}-{key}"))
    return out


@pytest.mark.parametrize("key,label", _registry_labels())
def test_every_registry_label_matches_its_key_like_the_locations_route(client, dbpath, monkeypatch, key, label):
    # The 24h movers and /api/spot/locations decide "same chain" the same way.
    assert wp._spot_location_row_matches({"symbol": "TOK", "chain": key, "contract_address": EVM},
                                         {"chain": label, "symbol": "TOK", "token_address": EVM})
    _runs(dbpath, 0, -24)
    _tok(dbpath, 0, label, EVM, 1.5)
    _tok(dbpath, -24, label, EVM, 1.0)
    _positions(monkeypatch, (key, EVM))
    assert _get(client)[f"{key} {EVM}"]["pct"] == pytest.approx(50.0)


def test_route_stays_read_only(client, dbpath, monkeypatch):
    _runs(dbpath, 0, -24)
    _tok(dbpath, 0, "Robinhood Chain", EVM, 3.0)
    _tok(dbpath, -24, "Robinhood Chain", EVM, 2.0)
    _positions(monkeypatch, ("robinhood", EVM))

    def counts():
        conn = sqlite3.connect(dbpath)
        try:
            return [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("portfolio_snapshots", "token_snapshots", "market_snapshots")]
        finally:
            conn.close()

    before = counts()
    _get(client)
    assert counts() == before
