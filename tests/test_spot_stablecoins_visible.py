"""Dry powder (GET /api/spot/stablecoins) counts only wallets visible in
Settings: the latest completed snapshot of each visible wallet, stablecoin
rows only. A wallet hidden or removed in Settings no longer adds its last
stablecoin balance. The spot price diagnostic's denominator reads the same
helper (_spot_stable_rows), so the two agree.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched); load_wallet_config is monkeypatched. Wallets are plain test
strings, never real addresses. Read-only routes, no network."""
import sqlite3
from datetime import datetime, timedelta

import pytest

import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

T0 = datetime(2026, 10, 10, 12, 0, 0)
A = "0x" + "a1" * 20
B = "0x" + "b2" * 20
H = "0x" + "c3" * 20          # hidden in Settings
R = "0x" + "d4" * 20          # removed from Settings (snapshots remain)


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


def _wallets(monkeypatch, cfg):
    monkeypatch.setattr(wp, "load_wallet_config", lambda: cfg)


def _run(path, wallet, hours=0, status="completed"):
    conn = sqlite3.connect(path)
    cur = conn.execute("INSERT INTO portfolio_snapshots (user_id, timestamp, wallet, status) VALUES (1, ?, ?, ?)",
                       ((T0 + timedelta(hours=hours)).isoformat(), wallet, status))
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def _tok(path, snap_id, wallet, symbol, value):
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO token_snapshots (snapshot_id, user_id, timestamp, wallet, chain, symbol, token_address, balance, "
        "price_usd, value_usd) VALUES (?, 1, ?, ?, 'Base', ?, '', ?, 1, ?)",
        (snap_id, T0.isoformat(), wallet, symbol, value, value))
    conn.commit()
    conn.close()


def _get(client):
    r = client.get("/api/spot/stablecoins")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _row_counts(path):
    conn = sqlite3.connect(path)
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                            "AND name NOT LIKE 'sqlite_%'")]
        return {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}
    finally:
        conn.close()


def _seed_three(path):
    """A visible, H hidden, R removed: each has one completed run with stables."""
    for wallet, usdc in ((A, 100.0), (H, 500.0), (R, 700.0)):
        sid = _run(path, wallet)
        _tok(path, sid, wallet, "USDC", usdc)
        _tok(path, sid, wallet, "ETH", 3000.0)


def test_hidden_and_removed_wallets_left_out(dbpath, client, monkeypatch):
    _seed_three(dbpath)
    _wallets(monkeypatch, {A: {"label": "Desktop Hot"}, H: {"label": "Old", "hidden": True}})
    body = _get(client)
    assert body["total_usd"] == pytest.approx(100.0)
    assert {b["wallet"] for b in body["breakdown"]} == {A}


def test_every_visible_wallet_counts_stables_only(dbpath, client, monkeypatch):
    sa = _run(dbpath, A)
    _tok(dbpath, sa, A, "USDC", 100.0)
    _tok(dbpath, sa, A, "usdt", 20.0)             # symbol case ignored
    _tok(dbpath, sa, A, "ETH", 3000.0)            # not a stablecoin
    sb = _run(dbpath, B)
    _tok(dbpath, sb, B, "DAI", 5.0)
    _wallets(monkeypatch, {A: {"label": "One"}, B: {"label": "Two"}})
    body = _get(client)
    assert body["total_usd"] == pytest.approx(125.0)
    assert sorted((b["wallet"], b["symbol"]) for b in body["breakdown"]) == [(A, "USDC"), (A, "usdt"), (B, "DAI")]


@pytest.mark.parametrize("status", ["failed", "partial", "pending"])
def test_latest_completed_run_per_wallet(dbpath, client, monkeypatch, status):
    old = _run(dbpath, A, hours=0)
    _tok(dbpath, old, A, "USDC", 100.0)
    new = _run(dbpath, A, hours=2)
    _tok(dbpath, new, A, "USDC", 150.0)
    later = _run(dbpath, A, hours=4, status=status)
    _tok(dbpath, later, A, "USDC", 999.0)
    _wallets(monkeypatch, {A: {"label": "One"}})
    assert _get(client)["total_usd"] == pytest.approx(150.0)


def test_no_visible_wallet_gives_zero(dbpath, client, monkeypatch):
    _seed_three(dbpath)
    _wallets(monkeypatch, {H: {"label": "Old", "hidden": True}})
    assert _get(client) == {"total_usd": 0, "breakdown": []}
    _wallets(monkeypatch, {})
    assert _get(client) == {"total_usd": 0, "breakdown": []}


def test_unhidden_wallet_counts_again(dbpath, client, monkeypatch):
    _seed_three(dbpath)
    _wallets(monkeypatch, {A: {"label": "One"}, H: {"label": "Old", "hidden": True}})
    assert _get(client)["total_usd"] == pytest.approx(100.0)
    _wallets(monkeypatch, {A: {"label": "One"}, H: {"label": "Old"}})
    assert _get(client)["total_usd"] == pytest.approx(600.0)


def test_wallet_matched_as_settings_keys_it(dbpath, client, monkeypatch):
    """Snapshots store the Settings key as given; the match is exact, as on
    /api/spot/locations. A key saved with different letter case reads nothing
    until that wallet's next snapshot."""
    sid = _run(dbpath, A)
    _tok(dbpath, sid, A, "USDC", 100.0)
    _wallets(monkeypatch, {A.upper().replace("0X", "0x"): {"label": "One"}})
    assert _get(client)["total_usd"] == 0


def test_helper_with_no_wallets_runs_no_query():
    class NoQuery:
        def execute(self, *a, **k):
            raise AssertionError("no query expected")
    assert wp._spot_stable_rows(NoQuery(), []) == []
    assert wp._spot_stable_rows(NoQuery(), None) == []


def test_diagnostic_denominator_reads_visible_wallets(dbpath, client, monkeypatch):
    _seed_three(dbpath)
    _wallets(monkeypatch, {A: {"label": "Desktop Hot"}, H: {"label": "Old", "hidden": True}})
    monkeypatch.setattr(wp, "_calculate_spot_fifo", lambda conn: ({}, {}))
    r = client.get("/spot-price-diagnose")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["portfolio_total_denominator_usd"] == pytest.approx(_get(client)["total_usd"])
    assert r.get_json()["portfolio_total_denominator_usd"] == pytest.approx(100.0)


def test_reads_only(dbpath, client, monkeypatch):
    _seed_three(dbpath)
    _wallets(monkeypatch, {A: {"label": "Desktop Hot"}, H: {"label": "Old", "hidden": True}})
    before = _row_counts(dbpath)
    _get(client)
    assert _row_counts(dbpath) == before
