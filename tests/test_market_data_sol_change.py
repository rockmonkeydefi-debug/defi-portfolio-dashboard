"""/api/market-data: the additive sol_24h_change key beside btc/eth_24h_change
(same 20-28 h comparison row).

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched); fetch_fred_macro stubbed, so no network. Synthetic values."""
from datetime import datetime, timedelta

import pytest

import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp


@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    return path


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    monkeypatch.setattr(wp, "fetch_fred_macro", lambda *a, **k: None)
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _seed(prev_sol):
    now = datetime.utcnow()
    portfolio_db.insert_market_snapshot({"timestamp": (now - timedelta(hours=24)).isoformat(), "session": "test",
                                         "btc_price": 80.0, "eth_price": 8.0, "sol_price": prev_sol})
    portfolio_db.insert_market_snapshot({"timestamp": now.isoformat(), "session": "test",
                                         "btc_price": 100.0, "eth_price": 10.0, "sol_price": 50.0})


def test_t1_sol_change_beside_btc_and_eth(client, dbpath):
    _seed(prev_sol=40.0)
    snap = client.get("/api/market-data").get_json()["snapshot"]
    assert snap["btc_24h_change"] == pytest.approx(25.0)
    assert snap["eth_24h_change"] == pytest.approx(25.0)
    assert snap["sol_24h_change"] == pytest.approx(25.0)


def test_t2_no_sol_change_without_a_prior_sol_price(client, dbpath):
    _seed(prev_sol=None)
    snap = client.get("/api/market-data").get_json()["snapshot"]
    assert "sol_24h_change" not in snap
    assert snap["btc_24h_change"] == pytest.approx(25.0) and snap["eth_24h_change"] == pytest.approx(25.0)
