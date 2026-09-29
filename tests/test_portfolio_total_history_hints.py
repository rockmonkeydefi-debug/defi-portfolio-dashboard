"""Read-only history hints for compose_total's uncounted-value warnings
(portfolio_total ruling 6): web_portfolio._portfolio_total_history_hints and
its wiring into GET /api/portfolio/total and the snapshot composer.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched), seeded token_snapshots / lp_snapshots rows. No network."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import portfolio_total as pt
import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

A = "0x" + "a" * 40
B = "0x" + "b" * 40
PLAZM = "0x" + "aaa" + "1" * 37
TWIN = "0x" + "ddd" + "3" * 37          # another contract that also calls itself PLAZM
CUSTOM = "0x" + "cc" + "2" * 38
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


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


def _ago(now, **delta):
    """A naive-UTC ISO timestamp, as the snapshot writer stores them."""
    return (now - timedelta(**delta)).replace(tzinfo=None).isoformat()


def _token(path, ts, symbol, address, price, balance=1.0, chain="Base", wallet=A):
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO token_snapshots (snapshot_id, user_id, timestamp, wallet, chain, symbol, token_address, "
        "balance, price_usd, value_usd) VALUES (1, 1, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ts, wallet, chain, symbol, address, balance, price, balance * price))
    conn.commit()
    conn.close()


def _lp(path, ts, value, token0="ETH", amount0=1.2068, wallet=B, chain="base", protocol="dex_finance"):
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO lp_snapshots (snapshot_id, user_id, timestamp, wallet, chain, protocol, position_id, "
        "token0, token1, amount0, amount1, value_usd) VALUES (1, 1, ?, ?, ?, ?, 'p1', ?, '?', ?, 0, ?)",
        (ts, wallet, chain, protocol, token0, amount0, value))
    conn.commit()
    conn.close()


def _plazm_row(**kw):
    row = {"chain": "Base", "symbol": "PLAZM", "balance": 100000.0, "value_usd": 0.0, "price_usd": 0.0,
           "contract": PLAZM, "wallet": A}
    row.update(kw)
    return row


def _dex_lp():
    return {"protocol": "dex_finance", "protocol_display": "Dex Finance", "chain": "base", "wallet": B,
            "deposit_legs": 0, "total_value_usd": 0, "total_fees_usd": 0, "uncounted_legs_usd": 327.62,
            "token0_symbol": "?", "token1_symbol": "?"}


def _hints(tokens=(), lps=(), now=NOW):
    return wp._portfolio_total_history_hints({"tokens": list(tokens), "lp_positions": list(lps)}, now)


# ── token prices ───────────────────────────────────────────────────────────

def test_address_price_three_hours_old_is_returned(dbpath):
    _token(dbpath, _ago(NOW, hours=5), "PLAZM", PLAZM.upper().replace("0X", "0x"), 0.04)
    _token(dbpath, _ago(NOW, hours=3), "PLAZM", PLAZM, 0.05)
    h = _hints([_plazm_row()])
    assert h["token_prices"] == {("base", PLAZM): {"price_usd": 0.05, "at": _ago(NOW, hours=3) + "+00:00"}}
    assert h["token_balances"] == {} and h["lp_last_valued"] == {}


def test_price_older_than_30_days_is_ignored(dbpath):
    _token(dbpath, _ago(NOW, days=40), "PLAZM", PLAZM, 0.05)
    assert _hints([_plazm_row()])["token_prices"] == {}


def test_same_symbol_different_address_is_not_returned(dbpath):
    _token(dbpath, _ago(NOW, hours=1), "PLAZM", TWIN, 9.99)
    assert _hints([_plazm_row()])["token_prices"] == {}


def test_native_row_matches_by_chain_and_symbol(dbpath):
    _token(dbpath, _ago(NOW, hours=2), "ETH", "", 2500.0)
    _token(dbpath, _ago(NOW, hours=1), "ETH", None, 2600.0, chain="Arbitrum")
    _token(dbpath, _ago(NOW, hours=1), "ETH", "0x" + "e" * 40, 1.0)      # a contract named ETH: never a native hint
    native = {"chain": "Base", "symbol": "eth", "balance": 1.0, "price_usd": 0.0, "value_usd": 0.0, "wallet": A}
    prices = _hints([native])["token_prices"]
    assert prices[("base", "sym:ETH")]["price_usd"] == 2500.0
    assert prices[("arbitrum", "sym:ETH")]["price_usd"] == 2600.0
    assert all(k[1].startswith("sym:") for k in prices)


# ── failed-balance rows ────────────────────────────────────────────────────

def test_failed_balance_uses_balance_from_two_days_ago_not_ten(dbpath):
    _token(dbpath, _ago(NOW, days=10), "ESHARE", CUSTOM, 700.0, balance=99.0, chain="base")
    _token(dbpath, _ago(NOW, days=2), "ESHARE", CUSTOM, 700.0, balance=10.0, chain="base")
    row = {"chain": "base", "symbol": "ESHARE", "balance": 0.0, "price_usd": None, "value_usd": 0.0,
           "contract": CUSTOM, "wallet": A, "source": "custom", "balance_failed": True}
    h = _hints([row])
    assert h["token_balances"] == {(A, "base", CUSTOM): {"balance": 10.0, "at": _ago(NOW, days=2) + "+00:00"}}


def test_failed_balance_only_ten_days_old_gives_no_balance(dbpath):
    _token(dbpath, _ago(NOW, days=10), "ESHARE", CUSTOM, 700.0, balance=99.0, chain="base")
    row = {"chain": "base", "symbol": "ESHARE", "contract": CUSTOM, "wallet": A, "source": "custom",
           "balance_failed": True}
    h = _hints([row])
    assert h["token_balances"] == {}
    assert h["token_prices"][("base", CUSTOM)]["price_usd"] == 700.0     # 10 days is inside the price window


# ── LP groups with no deposit ──────────────────────────────────────────────

def test_lp_hint_is_latest_positive_value_even_when_later_rows_are_zero(dbpath):
    _lp(dbpath, "2026-09-01T10:00:00", 2500.0, amount0=1.0)
    _lp(dbpath, "2026-09-08T13:13:21.822544", 2982.5007)
    _lp(dbpath, "2026-09-10T10:00:00", 0.0)
    _lp(dbpath, "2026-09-28T10:00:00", 0.0)
    _lp(dbpath, "2026-09-28T10:00:00", 5000.0, protocol="aerodrome")      # another protocol: not this group
    h = _hints(lps=[_dex_lp()])
    assert h["lp_last_valued"] == {(B, "base", "dex_finance"): {
        "value_usd": 2982.5007, "token0": "ETH", "amount0": 1.2068, "token1": "?", "amount1": 0.0,
        "at": "2026-09-08T13:13:21.822544+00:00"}}


# ── custom_token_price_snapshot's real fetch time wins ─────────────────────

def _custom_snapshot(path, contract, price, fetched_at):
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO custom_token_price_snapshot (contract, chain, price_usd, fetched_at) "
                 "VALUES (?, 'base', ?, ?)", (contract, price, fetched_at))
    conn.commit()
    conn.close()


def _unpriced_custom():
    return {"chain": "Base", "symbol": "ESHARE", "balance": 10.0, "price_usd": None, "value_usd": 0.0,
            "contract": CUSTOM, "wallet": A, "source": "custom"}


def test_custom_snapshot_fetch_time_preferred_over_token_snapshots(dbpath):
    table_at = (NOW - timedelta(hours=30)).isoformat()
    _custom_snapshot(dbpath, CUSTOM, 0.05, table_at)
    _token(dbpath, _ago(NOW, hours=2), "ESHARE", CUSTOM, 0.05)       # the carried price, saved as if live
    h = _hints([_unpriced_custom()])
    assert h["token_prices"] == {("base", CUSTOM): {"price_usd": 0.05, "at": table_at}}


def test_without_custom_snapshot_token_snapshots_used_as_before(dbpath):
    _token(dbpath, _ago(NOW, hours=2), "ESHARE", CUSTOM, 0.05)
    h = _hints([_unpriced_custom()])
    assert h["token_prices"] == {("base", CUSTOM): {"price_usd": 0.05, "at": _ago(NOW, hours=2) + "+00:00"}}


def test_custom_snapshot_older_than_lookback_ignored(dbpath):
    _custom_snapshot(dbpath, CUSTOM, 0.05, (NOW - timedelta(days=40)).isoformat())
    _token(dbpath, _ago(NOW, hours=2), "ESHARE", CUSTOM, 0.04)
    h = _hints([_unpriced_custom()])
    assert h["token_prices"][("base", CUSTOM)]["price_usd"] == 0.04


# ── nothing flagged / errors ───────────────────────────────────────────────

def test_nothing_flagged_returns_empty_without_touching_the_db(monkeypatch):
    def boom():
        raise AssertionError("no DB read when nothing is flagged")
    monkeypatch.setattr(portfolio_db, "get_connection", boom)
    priced = {"chain": "Base", "symbol": "ETH", "balance": 1.0, "price_usd": 2500.0, "value_usd": 2500.0}
    onchain_lp = {"protocol": "uniswap_v3", "chain": "base", "wallet": A, "total_value_usd": 10.0}
    assert _hints([priced], [onchain_lp]) == {}
    assert wp._portfolio_total_history_hints(None, NOW) == {}


def test_db_error_returns_empty_and_logs(monkeypatch, caplog):
    def boom():
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(portfolio_db, "get_connection", boom)
    with caplog.at_level("ERROR"):
        assert _hints([_plazm_row()], [_dex_lp()]) == {}
    assert any("history hints failed" in r.getMessage() for r in caplog.records)


# ── wiring ─────────────────────────────────────────────────────────────────

def _stub_route_inputs(monkeypatch, cache):
    monkeypatch.setattr(wp, "_portfolio_cache", cache)
    monkeypatch.setattr(wp, "_portfolio_total_db_inputs", lambda: {
        "maxfi_rows": [], "ledger_head_closed_ids": set(), "ledger_ok": True, "latest_scan_by_key": {}})
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", lambda now_utc: False)
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": None, "wallets": {}, "error": None})


def test_route_warns_on_unpriced_row_and_total_is_unchanged(client, dbpath, monkeypatch):
    now = datetime.now(timezone.utc)
    _token(dbpath, _ago(now, hours=2), "PLAZM", PLAZM, 0.05)
    cache = {"tokens": [{"chain": "Base", "symbol": "ETH", "balance": 1.0, "price_usd": 2000.0,
                         "value_usd": 2000.0, "wallet": A}, _plazm_row()],
             "lp_positions": [], "total_value": 2000.0}
    _stub_route_inputs(monkeypatch, cache)
    r = client.get("/api/portfolio/total").get_json()

    wt = next(c for c in r["components"] if c["key"] == "wallet_tokens")
    assert wt["warnings"] == ["1 token unpriced — about $5,000 not counted (PLAZM)"]
    assert {"component": "wallet_tokens", "warning": wt["warnings"][0]} in r["warnings"]
    no_hints = pt.compose_total(cache, [], set(), True, {}, {"fetched_at": None, "wallets": {}, "error": None},
                                now)
    assert r["total_usd"] == pytest.approx(no_hints["total_usd"]) == pytest.approx(2000.0)
    assert wt["value_usd"] == 2000.0


def test_snapshot_composer_passes_history_hints(monkeypatch):
    calls = []

    def fake_compose(*args, **kwargs):
        calls.append(kwargs)
        return {"status": "ok"}
    monkeypatch.setattr(wp.portfolio_total, "compose_total", fake_compose)
    monkeypatch.setattr(wp, "_portfolio_total_db_inputs", lambda: {
        "maxfi_rows": [], "ledger_head_closed_ids": set(), "ledger_ok": True, "latest_scan_by_key": {}})
    monkeypatch.setattr(wp, "_hl_accounts_state_for_snapshot", lambda now_utc: {})
    dexfi = {"fetched_at": None, "info": None, "wallets": {}, "error": None}
    monkeypatch.setattr(wp, "_dexfi_bonds_state_for_snapshot", lambda now_utc: dexfi)
    sentinel = {"token_prices": {"x": 1}, "token_balances": {}, "lp_last_valued": {}}
    seen = []
    monkeypatch.setattr(wp, "_portfolio_total_history_hints",
                        lambda portfolio, now_utc: seen.append(portfolio) or sentinel)
    P = {"tokens": [_plazm_row()], "lp_positions": []}
    assert wp._compose_total_for_snapshot(P) == {"status": "ok"}
    assert calls == [{"history_hints": sentinel, "dexfi_state": dexfi}] and seen == [P]


def test_route_kicks_dexfi_refresh_and_passes_dexfi_state(client, monkeypatch):
    cache = {"tokens": [], "lp_positions": [], "total_value": 0.0}
    _stub_route_inputs(monkeypatch, cache)
    kicks, seen = [], []
    dexfi = {"fetched_at": "2026-09-29T11:50:00+00:00", "info": None, "wallets": {}, "error": None}
    monkeypatch.setattr(wp, "_maybe_kick_dexfi_bonds_refresh", lambda now_utc: kicks.append(now_utc) or True)
    monkeypatch.setattr(wp, "_dexfi_bonds_cache_copy", lambda: dexfi)
    real = wp.portfolio_total.compose_total

    def spy(*args, **kwargs):
        seen.append(kwargs.get("dexfi_state"))
        return real(*args, **kwargs)
    monkeypatch.setattr(wp.portfolio_total, "compose_total", spy)
    assert client.get("/api/portfolio/total").get_json()["status"] == "ok"
    assert len(kicks) == 1 and seen == [dexfi]
