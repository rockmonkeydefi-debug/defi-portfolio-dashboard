"""Tests for Landing 2b's cost_sold field on trades (HANDOFF_spot_perps_rebuild
Q1-A, Oct 4): what the units a trade has sold so far cost, the denominator of
the Spot page's History by trade Return. spot_tx trades: proceeds minus
realized P/L (the FIFO cost of the lots its sells consumed, after-close sells
included); manual trades: entry x qty once closed; perps: None.

Real init_db() on a tmp_path SQLite file, the pattern test_trades_unified.py
uses; network helpers raise. Symbols and amounts are made up; token contracts
are fake strings built in code.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db

ADDR = {k: "0x" + str(k) * 40 for k in range(1, 4)}       # fake token contracts


def _never(*a, **k):
    raise AssertionError("no network in tests")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.setattr(wp, "_hl_post", _never)
    monkeypatch.setattr(wp, "_txflow_post", _never)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {})
    conn = portfolio_db.get_connection()
    yield conn
    conn.close()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(wp, "_maybe_kick_hl_trades_refresh", lambda now, force=False: False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_trades_refresh", lambda now: False)
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", lambda now: False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", lambda now: False)
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def tx(conn, date, symbol, side, units, total, contract=None):
    chain, addr = ("base", contract) if contract else ("", "")
    conn.execute("INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, chain, "
                 "contract_address) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (date, symbol, side, units, total, total, chain, addr))
    conn.commit()


def manual(conn, **fields):
    row = {"ticker": "SOL", "direction": "long", "source": "manual", "venue": None, "entry_price": 100.0,
           "stop_price": 95.0, "qty": 2.0, "entered_at": "2026-09-20T10:00:00+00:00", **fields}
    cols = list(row)
    cur = conn.execute(f"INSERT INTO spot_trade_log ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                       tuple(row[c] for c in cols))
    conn.commit()
    return cur.lastrowid


def by_symbol(conn):
    trades, _ = wp._trades_build(conn)
    out = {}
    for t in trades:
        out.setdefault(t["symbol"], []).append(t)
    return out


def test_closed_spot_trade_cost_sold_is_the_cost_of_its_lots(db):
    tx(db, "2026-09-15", "aaa", "buy", 10, 100, ADDR[1])
    tx(db, "2026-09-20", "aaa", "sell", 10, 150, ADDR[1])
    t = by_symbol(db)["AAA"][0]
    assert t["status"] == "closed" and t["cost_sold"] == "100.000000" and t["net_pnl"] == "50.000000"


def test_two_buys_one_sell(db):
    tx(db, "2026-09-15", "bbb", "buy", 10, 100, ADDR[2])
    tx(db, "2026-09-16", "bbb", "buy", 10, 200, ADDR[2])
    tx(db, "2026-09-20", "bbb", "sell", 20, 400, ADDR[2])
    t = by_symbol(db)["BBB"][0]
    assert t["cost_sold"] == "300.000000" and t["net_pnl"] == "100.000000"


def test_partly_closed_and_unsold_trades(db):
    tx(db, "2026-09-15", "ccc", "buy", 10, 100, ADDR[3])
    tx(db, "2026-09-20", "ccc", "sell", 4, 60, ADDR[3])
    tx(db, "2026-09-21", "ddd", "buy", 5, 50)
    t = by_symbol(db)
    assert t["CCC"][0]["status"] == "partly_closed" and t["CCC"][0]["cost_sold"] == "40.000000"
    assert t["DDD"][0]["status"] == "open" and t["DDD"][0]["cost_sold"] == "0.000000"


def test_after_close_sale_counts_toward_cost_sold(db):
    tx(db, "2026-09-16", "eee", "buy", 100, 100)
    tx(db, "2026-09-18", "eee", "sell", 99.5, 199)
    tx(db, "2026-09-19", "eee", "sell", 0.5, 5)              # after close
    t = by_symbol(db)["EEE"][0]
    assert t["status"] == "closed" and "after_close_sell" in t["flags"]
    assert t["cost_sold"] == "100.000000" and t["net_pnl"] == "104.000000"


def test_manual_trades(db):
    manual(db, ticker="FFF", exit_price=110.0, exited_at="2026-09-21T10:00:00+00:00")
    manual(db, ticker="GGG")
    t = by_symbol(db)
    assert t["FFF"][0]["cost_sold"] == "200.000000" and t["FFF"][0]["net_pnl"] == "20.000000"
    assert t["GGG"][0]["status"] == "open" and t["GGG"][0]["cost_sold"] is None


def test_route_carries_cost_sold(client, db):
    tx(db, "2026-09-15", "aaa", "buy", 10, 100, ADDR[1])
    tx(db, "2026-09-20", "aaa", "sell", 10, 150, ADDR[1])
    r = client.get('/api/trading/trades')
    assert r.status_code == 200, r.get_data(as_text=True)
    t = [x for x in r.get_json()["trades"] if x["symbol"] == "AAA"][0]
    assert t["cost_sold"] == "100.000000"
