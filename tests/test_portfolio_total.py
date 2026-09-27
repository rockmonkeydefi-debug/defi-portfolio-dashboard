"""GET /api/portfolio/total and portfolio_total.compose_total (Total portfolio
value, commit B).

Covers the pure composition (every component, the counted total, the
invariant against get_portfolio_data's own total_value, the MaxFi uncollected
rules, Hyperliquid, lending net, GMX, staking, drift warnings), the
Hyperliquid accounts fetch / background swap / kick logic, and the route
(cache-only, never calls get_portfolio_data, zero DB writes, hidden MaxFi
wallets excluded), plus /api/spot/stablecoins staying byte-identical now that
it shares STABLECOIN_SYMBOLS.

No network: the Hyperliquid fetch runs only against a fake `post`; the spawner
is conftest's autouse no-op (tests that need a spawn install a recorder)."""
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import maxfi_schema
import portfolio_total as pt
import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
A = "0x" + "a" * 40
B = "0x" + "b" * 40
H = "0x" + "c" * 40          # a hidden wallet
_REAL_FETCH = wp._hl_fetch_accounts   # captured before any test patches it
OLD_STABLES = ('USDC', 'USDT', 'DAI', 'FRAX', 'LUSD', 'BUSD', 'TUSD', 'USDS', 'CRVUSD')


def _portfolio(**overrides):
    """A get_portfolio_data-shaped payload: $2,000 ETH + $300 USDC + $200 USDT
    tokens, a $700 snuggle (MaxFi) LP row and a $500 other LP row with $5
    fees. total_value = 2500 + 1200 + 5 = 3705."""
    p = {
        "tokens": [
            {"symbol": "ETH", "value_usd": 2000.0, "wallet": A},
            {"symbol": "USDC", "value_usd": 300.0, "wallet": A},
            {"symbol": "usdt", "value_usd": 200.0, "wallet": B},
        ],
        "lp_positions": [
            {"protocol": "snuggle", "chain": "robinhood", "wallet": A, "total_value_usd": 700.0, "total_fees_usd": 0},
            {"protocol": "uniswap_v3", "chain": "base", "wallet": A, "total_value_usd": 500.0, "total_fees_usd": 5.0},
        ],
        "aave_positions": [],
        "gmx_positions": [],
        "staking_positions": [],
        "total_tokens_value": 2500.0,
        "total_lp_value": 1200.0,
        "total_uncollected_fees": 5.0,
        "total_value": 3705.0,
        "wallet_labels": {A: "Rabby", B: "Other"},
        "fetched_at": "2026-09-27T11:50:00",
    }
    p.update(overrides)
    return p


def _row(pid, uncollected=10.0, wallet=A, chain="robinhood", value=700.0, value_at="2026-09-27T11:00:00+00:00"):
    return {"id": pid, "chain": chain, "wallet": wallet, "token_id": str(pid), "last_value_usd": value,
            "last_value_at": value_at, "last_uncollected_usd": uncollected}


def _compose(portfolio=None, rows=(), closed=(), ledger_ok=True, scans=None, hl=None):
    return pt.compose_total(portfolio if portfolio is not None else _portfolio(), list(rows), set(closed),
                            ledger_ok, scans or {}, hl or {"fetched_at": None, "wallets": {}, "error": None}, NOW)


def _c(result, key):
    return next(c for c in result["components"] if c["key"] == key)


# ── pure composition ───────────────────────────────────────────────────────

def test_component_values_and_order():
    r = _compose()
    assert [c["key"] for c in r["components"]] == [
        "wallet_tokens", "stablecoins", "maxfi_lp", "other_lp", "lp_uncollected", "maxfi_uncollected",
        "hyperliquid", "lending_net", "gmx", "zerion_staking"]
    vals = {c["key"]: c["value_usd"] for c in r["components"]}
    assert vals["wallet_tokens"] == 2000.0          # ETH
    assert vals["stablecoins"] == 500.0             # USDC 300 + usdt 200 (case-insensitive)
    assert vals["maxfi_lp"] == 700.0 and vals["other_lp"] == 500.0
    assert vals["lp_uncollected"] == 5.0
    for c in r["components"]:
        assert set(c) == {"key", "label", "value_usd", "counted", "as_of", "source", "warnings", "detail"}
    assert r["status"] == "ok"


def test_total_is_sum_of_counted_components():
    r = _compose(rows=[_row(1, 10.0)], hl={"fetched_at": "2026-09-27T11:55:00+00:00",
                                            "wallets": {A: {"perp_account_value": 100.0, "open_perps": 0, "spot": []}}})
    assert r["total_usd"] == pytest.approx(sum(c["value_usd"] for c in r["components"] if c["counted"]))
    assert not _c(r, "zerion_staking")["counted"]


def test_invariant_equals_portfolio_total_value():
    # no HL, no maxfi rows, no lending, stable GMX only, no staking; lp sum == total_lp_value
    p = _portfolio(gmx_positions=[{"collateral_symbol": "USDC", "collateral_amount": 250.0, "market": "ETH"}],
                   total_value=3705.0 + 250.0)
    r = _compose(p)
    assert r["total_usd"] == pytest.approx(p["total_value"]) == pytest.approx(r["portfolio_total_value"])


def test_stablecoin_split_matches_the_shared_tuple():
    assert pt.STABLECOIN_SYMBOLS == OLD_STABLES
    tokens = [{"symbol": s, "value_usd": 1.0} for s in OLD_STABLES] + [{"symbol": "USDC.E", "value_usd": 1.0},
                                                                    {"symbol": "BTC", "value_usd": 1.0}]
    r = _compose(_portfolio(tokens=tokens))
    assert _c(r, "stablecoins")["value_usd"] == len(OLD_STABLES)
    assert _c(r, "wallet_tokens")["value_usd"] == 2.0


def test_snuggle_rows_are_maxfi_lp_case_insensitively():
    lp = [{"protocol": "Snuggle", "chain": "robinhood", "wallet": A, "total_value_usd": 10.0, "total_fees_usd": 0},
          {"protocol": "aerodrome", "chain": "base", "wallet": A, "total_value_usd": 3.0, "total_fees_usd": 0}]
    r = _compose(_portfolio(lp_positions=lp))
    assert (_c(r, "maxfi_lp")["value_usd"], _c(r, "maxfi_lp")["detail"]["rows"]) == (10.0, 1)
    assert (_c(r, "other_lp")["value_usd"], _c(r, "other_lp")["detail"]["rows"]) == (3.0, 1)


def test_maxfi_uncollected_at_85_percent():
    r = _compose(rows=[_row(1, 10.0), _row(2, 30.0)])
    mx = _c(r, "maxfi_uncollected")
    assert mx["value_usd"] == pytest.approx(40.0 * 0.85)                     # 34.0
    assert mx["detail"]["gross_uncollected_usd"] == 40.0
    assert mx["counted"] and mx["warnings"] == []
    assert mx["as_of"] == "2026-09-27T11:00:00+00:00"


def test_ledger_head_closed_rows_excluded():
    r = _compose(rows=[_row(1, 10.0), _row(2, 30.0)], closed={2})
    mx = _c(r, "maxfi_uncollected")
    assert mx["value_usd"] == pytest.approx(8.5)
    assert mx["detail"]["excluded_ledger_withdrawn"] == 1
    assert any("withdrawn" in w for w in mx["warnings"])


def test_ledger_unavailable_excludes_nothing_and_warns():
    r = _compose(rows=[_row(1, 10.0), _row(2, 30.0)], closed={2}, ledger_ok=False)
    mx = _c(r, "maxfi_uncollected")
    assert mx["value_usd"] == pytest.approx(34.0)
    assert "ledger unavailable — withdrawn-position guard off" in mx["warnings"]


def test_null_uncollected_not_counted_and_warned():
    r = _compose(rows=[_row(1, None), _row(2, 30.0)])
    mx = _c(r, "maxfi_uncollected")
    assert mx["value_usd"] == pytest.approx(25.5)
    assert mx["detail"]["no_uncollected_data"] == 1
    assert any("no uncollected data" in w for w in mx["warnings"])


def test_old_value_counted_but_flagged():
    r = _compose(rows=[_row(1, 10.0, value_at="2026-09-25T00:00:00"), _row(2, 10.0, value_at=None)])
    mx = _c(r, "maxfi_uncollected")
    assert mx["value_usd"] == pytest.approx(17.0)
    assert mx["detail"]["stale_values"] == 2
    assert any("more than 24 h ago" in w for w in mx["warnings"])
    assert mx["as_of"] == "2026-09-25T00:00:00+00:00"                        # naive read as UTC


def test_zerion_fees_skip_db_uncollected_for_that_wallet_chain_only():
    lp = [{"protocol": "snuggle", "chain": "robinhood", "wallet": A.upper().replace("0X", "0x"),
           "total_value_usd": 700.0, "total_fees_usd": 2.0},
          {"protocol": "snuggle", "chain": "base", "wallet": A, "total_value_usd": 10.0, "total_fees_usd": 0}]
    r = _compose(_portfolio(lp_positions=lp), rows=[_row(1, 10.0), _row(2, 20.0, chain="base")])
    mx = _c(r, "maxfi_uncollected")
    assert mx["value_usd"] == pytest.approx(17.0)                            # only the base row
    assert "Zerion now reports MaxFi fees for Rabby/robinhood; DB uncollected skipped" in mx["warnings"]


def test_hyperliquid_never_fetched_is_loading_and_not_counted():
    hl = _c(_compose(), "hyperliquid")
    assert (hl["value_usd"], hl["counted"]) == (0, False)
    assert "Hyperliquid loading" in hl["warnings"]


def test_hyperliquid_priced_sum_and_unpriced_excluded():
    state = {"fetched_at": "2026-09-27T11:58:00+00:00", "wallets_checked": 3, "error": None, "wallets": {
        A: {"perp_account_value": 228.61, "open_perps": 0, "mode": "disabled", "spot": [
            {"coin": "USDC", "amount": 1456.71, "price": 1.0, "value": 1456.71},
            {"coin": "MAX", "amount": 100.0, "price": 0.5, "value": 50.0},
            {"coin": "ODD", "amount": 5.0, "price": None, "value": None}]}}}
    hl = _c(_compose(hl=state), "hyperliquid")
    assert hl["counted"] and hl["as_of"] == "2026-09-27T11:58:00+00:00"
    assert hl["value_usd"] == pytest.approx(228.61 + 1456.71 + 50.0)
    assert any("ODD has no USDC price" in w for w in hl["warnings"])
    row = hl["detail"]["wallets"][0]
    assert row["label"] == "Rabby" and [s["coin"] for s in row["spot"]] == ["USDC", "MAX", "ODD"]
    assert hl["detail"]["wallets_checked"] == 3


def test_hyperliquid_stale_wallet_warned():
    state = {"fetched_at": "2026-09-27T11:58:00+00:00", "wallets": {
        A: {"perp_account_value": 10.0, "open_perps": 0, "mode": "disabled", "spot": [], "stale": True, "error": "Timeout"}},
        "wallet_errors": {A: "Timeout", B: "boom"}}
    hl = _c(_compose(hl=state), "hyperliquid")
    assert hl["value_usd"] == 10.0
    assert any("Rabby: last refresh failed (Timeout)" in w for w in hl["warnings"])
    assert any("Other: refresh failed (boom) — no data" in w for w in hl["warnings"])


def test_lending_net_with_gross_reported():
    aave = [{"total_collateral_usd": 1000.0, "total_debt_usd": 400.0, "health_factor": 2.1, "chain": "base"},
            {"total_collateral_usd": 50.0, "total_debt_usd": 0.0, "health_factor": None, "chain": "arbitrum"}]
    lend = _c(_compose(_portfolio(aave_positions=aave)), "lending_net")
    assert lend["value_usd"] == 650.0 and lend["counted"]
    assert (lend["detail"]["gross_collateral_usd"], lend["detail"]["debt_usd"]) == (1050.0, 400.0)
    assert [r["health_factor"] for r in lend["detail"]["rows"]] == [2.1, None]


def test_gmx_non_stable_collateral_not_counted():
    gmx = [{"collateral_symbol": "USDC", "collateral_amount": 100.0, "market": "ETH"},
           {"collateral_symbol": "WETH", "collateral_amount": 0.5, "market": "ETH"}]
    g = _c(_compose(_portfolio(gmx_positions=gmx)), "gmx")
    assert g["value_usd"] == 100.0
    assert g["detail"]["not_counted"] == [{"market": "ETH", "collateral_symbol": "WETH", "collateral_amount": 0.5}]
    assert any("known gmx_v2 units bug" in w for w in g["warnings"])
    assert g["detail"]["pnl"] == "not included"


def test_staking_reported_not_counted_and_missing_key():
    st = [{"wallet_label": "Rabby", "chain": "Base", "protocol": "Lido", "position_type": "staked",
           "symbol": "stETH", "value_usd": 40.0}]
    r = _compose(_portfolio(staking_positions=st))
    s = _c(r, "zerion_staking")
    assert (s["value_usd"], s["counted"]) == (40.0, False)
    assert r["total_usd"] == pytest.approx(3705.0)                           # not in the total
    p = _portfolio()
    del p["staking_positions"]
    s2 = _c(_compose(p), "zerion_staking")
    assert s2["value_usd"] == 0 and s2["detail"]["note"] == "not reported by this portfolio payload"


def test_drift_warnings():
    lp = [{"protocol": "snuggle", "chain": "robinhood", "wallet": A, "total_value_usd": 700.0, "total_fees_usd": 0},
          {"protocol": "snuggle", "chain": "robinhood", "wallet": A, "total_value_usd": 300.0, "total_fees_usd": 0}]
    # aligned: 2 vs 2, 1000 vs 990 (inside max(25, 5% of 1000)=50), scan before fetched_at
    r = _compose(_portfolio(lp_positions=lp), rows=[_row(1, value=700.0), _row(2, value=290.0)],
                 scans={(A, "robinhood"): "2026-09-27T11:00:00+00:00"})
    (d,) = r["maxfi_drift"]
    assert (d["zerion_count"], d["zerion_sum"], d["db_open"], d["db_sum"], d["db_null_values"]) == (2, 1000.0, 2, 990.0, 0)
    assert d["warnings"] == [] and d["wallet_label"] == "Rabby"
    # count mismatch + sum over threshold + newer scan
    r2 = _compose(_portfolio(lp_positions=lp), rows=[_row(1, value=700.0), _row(2, value=200.0), _row(3, value=None)],
                  scans={(A, "robinhood"): "2026-09-27T11:59:00+00:00"})
    (d2,) = r2["maxfi_drift"]
    assert d2["db_null_values"] == 1
    assert any(w.startswith("count mismatch") for w in d2["warnings"])
    assert any(w.startswith("value drift") for w in d2["warnings"])          # 1000 vs 900 > 50
    assert "portfolio data predates your last MaxFi scan — press Refresh" in d2["warnings"]
    assert any(w["component"] == "maxfi_drift" for w in r2["warnings"])
    # drift never changes counted values: the same inputs without the scan give the same total
    r3 = _compose(_portfolio(lp_positions=lp), rows=[_row(1, value=700.0), _row(2, value=200.0), _row(3, value=None)])
    assert r3["total_usd"] == r2["total_usd"]
    assert _c(r2, "maxfi_lp")["value_usd"] == 1000.0


# ── Hyperliquid fetch / swap / kick ────────────────────────────────────────

def _fake_post(fail_wallet=None, price_fail=False):
    meta = {"tokens": [{"name": "USDC", "index": 0}, {"name": "MAX", "index": 1}, {"name": "HYPE", "index": 2},
                       {"name": "ODD", "index": 3}],
            "universe": [{"name": "@1", "tokens": [1, 0], "index": 0, "isCanonical": False},
                         {"name": "MAX/USDC", "tokens": [1, 0], "index": 1, "isCanonical": True},
                         {"name": "@2", "tokens": [2, 0], "index": 2, "isCanonical": False},
                         {"name": "@3", "tokens": [2, 0], "index": 3, "isCanonical": False},
                         {"name": "@4", "tokens": [3, 2], "index": 4, "isCanonical": False}]}
    ctxs = [{"markPx": "9.0", "dayNtlVlm": "1000000"}, {"markPx": "0.5", "dayNtlVlm": "10"},
            {"midPx": "30", "dayNtlVlm": "100"}, {"markPx": "31", "dayNtlVlm": "500"}, {"markPx": "1"}]
    calls = []

    def post(payload):
        calls.append(payload)
        t = payload["type"]
        if t == "spotMetaAndAssetCtxs":
            if price_fail:
                raise RuntimeError("meta down")
            return [meta, ctxs]
        user = payload["user"]
        if user == fail_wallet:
            raise TimeoutError("hl timeout")
        if t == "clearinghouseState":
            return {"marginSummary": {"accountValue": "228.61" if user == A else "0.0"},
                    "assetPositions": [{"position": {}}] if user == A else []}
        if t == "spotClearinghouseState":
            if user == A:
                return {"balances": [{"coin": "USDC", "total": "1456.71"}, {"coin": "MAX", "total": "100"},
                                     {"coin": "ODD", "total": "5"}, {"coin": "ZZZ", "total": "0.0"}]}
            return {"balances": []}
        if t == "userAbstraction":
            return "unifiedAccount" if user == A else "disabled"
        raise AssertionError(t)
    post.calls = calls
    return post


def test_hl_fetch_price_map_and_wallet_rows():
    res = wp._hl_fetch_accounts([A, B, H], post=_fake_post(fail_wallet=H))
    assert res["price_error"] is None
    assert res["prices"] == {"USDC": 1.0, "MAX": 0.5, "HYPE": 31.0}          # canonical MAX wins; HYPE by volume
    assert res["wallets_checked"] == 3
    assert list(res["wallets"]) == [A]                                        # B all-zero omitted, H failed
    assert "TimeoutError" in res["errors"][H]
    a = res["wallets"][A]
    assert (a["perp_account_value"], a["open_perps"]) == (228.61, 1)
    assert [(s["coin"], s["price"], s["value"]) for s in a["spot"]] == [
        ("USDC", 1.0, 1456.71), ("MAX", 0.5, 50.0), ("ODD", None, None)]


def test_hl_fetch_price_failure_still_reads_wallets():
    res = wp._hl_fetch_accounts([A], post=_fake_post(price_fail=True))
    assert "meta down" in res["price_error"]
    assert res["prices"] == {"USDC": 1.0}
    assert res["wallets"][A]["spot"][1]["price"] is None                      # MAX unpriced without the map


def test_worker_swap_keeps_stale_row_for_failed_wallet(monkeypatch):
    wp._HL_ACCOUNTS_CACHE.update({"fetched_at": "2026-09-27T11:00:00+00:00",
                                  "wallets": {H: {"perp_account_value": 5.0, "open_perps": 0, "spot": []}}})
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_IN_FLIGHT", True)
    monkeypatch.setattr(wp, "_hl_fetch_accounts", lambda wallets: _REAL_FETCH(wallets, post=_fake_post(fail_wallet=H)))
    wp._hl_accounts_refresh_worker([A, H], now_utc=NOW)
    c = wp._HL_ACCOUNTS_CACHE
    assert c["fetched_at"] == NOW.isoformat()
    assert c["wallets"][A]["perp_account_value"] == 228.61
    assert c["wallets"][H]["stale"] is True and c["wallets"][H]["perp_account_value"] == 5.0
    assert wp._HL_ACCOUNTS_IN_FLIGHT is False


def test_worker_price_failure_keeps_everything(monkeypatch):
    prior = {"fetched_at": "2026-09-27T11:00:00+00:00", "wallets": {A: {"perp_account_value": 1.0}}, "error": None}
    wp._HL_ACCOUNTS_CACHE.update(prior)
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_IN_FLIGHT", True)
    monkeypatch.setattr(wp, "_hl_fetch_accounts", lambda wallets: _REAL_FETCH(wallets, post=_fake_post(price_fail=True)))
    wp._hl_accounts_refresh_worker([A], now_utc=NOW)
    c = wp._HL_ACCOUNTS_CACHE
    assert c["fetched_at"] == "2026-09-27T11:00:00+00:00"                    # unchanged
    assert c["wallets"] == {A: {"perp_account_value": 1.0}}
    assert "meta down" in c["error"]
    assert wp._HL_ACCOUNTS_IN_FLIGHT is False


def test_worker_clears_in_flight_on_exception(monkeypatch):
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_IN_FLIGHT", True)

    def boom(wallets):
        raise RuntimeError("fetch exploded")
    monkeypatch.setattr(wp, "_hl_fetch_accounts", boom)
    wp._hl_accounts_refresh_worker([A], now_utc=NOW)
    assert wp._HL_ACCOUNTS_IN_FLIGHT is False
    assert "fetch exploded" in wp._HL_ACCOUNTS_CACHE["error"]
    assert wp._HL_ACCOUNTS_CACHE["fetched_at"] is None



@pytest.fixture
def kick_env(monkeypatch):
    spawned = []
    monkeypatch.setattr(wp, "_spawn_hl_accounts_refresh_thread", lambda wallets: spawned.append(list(wallets)))
    config = {A: {"label": "Rabby"}, B: {"label": "Other"}, H: {"label": "Hidden", "hidden": True},
              "xpub6ABC": {"type": "bitcoin_xpub"}, "So1anaWa11etAddre55xxxxxxxxxxxxxxxxxxxxx": {"type": "solana"},
              "0xshort": {}}
    monkeypatch.setattr(wp, "load_wallet_config", lambda: config)
    return spawned


def test_kick_selects_visible_evm_wallets_only(kick_env):
    assert wp._maybe_kick_hl_accounts_refresh(NOW) is True
    assert kick_env == [[A, B]]
    assert wp._HL_ACCOUNTS_IN_FLIGHT is True


def test_kick_respects_ttl_in_flight_and_cooldown(kick_env, monkeypatch):
    wp._HL_ACCOUNTS_CACHE["fetched_at"] = (NOW - timedelta(minutes=5)).isoformat()
    assert wp._maybe_kick_hl_accounts_refresh(NOW) is False                  # fresh cache
    wp._HL_ACCOUNTS_CACHE["fetched_at"] = (NOW - timedelta(minutes=16)).isoformat()
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_IN_FLIGHT", True)
    assert wp._maybe_kick_hl_accounts_refresh(NOW) is False                  # in flight
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_IN_FLIGHT", False)
    wp._HL_ACCOUNTS_LAST_KICK["at"] = NOW - timedelta(minutes=10)
    assert wp._maybe_kick_hl_accounts_refresh(NOW) is False                  # cooldown
    wp._HL_ACCOUNTS_LAST_KICK["at"] = NOW - timedelta(minutes=16)
    assert wp._maybe_kick_hl_accounts_refresh(NOW) is True
    assert kick_env == [[A, B]]


# ── the route ──────────────────────────────────────────────────────────────

class _TrackedConn(sqlite3.Connection):
    closed_changes = []

    def close(self):
        _TrackedConn.closed_changes.append(self.total_changes)
        super().close()


@pytest.fixture
def db(monkeypatch):
    uri = f"file:portfolio_total_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    maxfi_schema.ensure_maxfi_tables(keepalive)
    keepalive.execute("CREATE TABLE portfolio_snapshots (id INTEGER PRIMARY KEY, wallet TEXT, status TEXT)")
    keepalive.execute("CREATE TABLE token_snapshots (id INTEGER PRIMARY KEY, snapshot_id INTEGER, wallet TEXT, "
                      "symbol TEXT, value_usd REAL)")
    keepalive.commit()
    _TrackedConn.closed_changes = []

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True, factory=_TrackedConn)
        conn.row_factory = sqlite3.Row
        return conn
    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    yield keepalive
    keepalive.close()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _seed(db, pid, wallet, uncollected, chain="robinhood", status="open", value=700.0,
          value_at="2026-09-27T11:00:00+00:00", scan="2026-09-27T10:00:00+00:00"):
    db.execute(
        """INSERT INTO maxfi_positions (id, chain, wallet, token_id, array_index, pool_address, token0_address,
             token1_address, fee_tier, status, first_seen_at, first_seen_at_source, last_scan_at,
             last_value_usd, last_value_at, last_uncollected_usd)
           VALUES (?, ?, ?, ?, ?, '0xpool', '0xt0', '0xt1', 3000, ?, '2026-01-01T00:00:00+00:00', 'chain', ?, ?, ?, ?)""",
        (pid, chain, wallet, str(pid), pid, status, scan, value, value_at, uncollected))
    db.commit()


def test_route_cold_cache(client, db, monkeypatch):
    monkeypatch.setattr(wp, "_portfolio_cache", None)
    monkeypatch.setattr(wp, "get_portfolio_data", lambda *a, **k: (_ for _ in ()).throw(AssertionError("built")))
    r = client.get("/api/portfolio/total")
    assert r.status_code == 200 and r.get_json() == {"status": "cache_cold"}


def test_route_warm_cache_cache_only_no_writes(client, db, monkeypatch):
    config = {A: {"label": "Rabby", "maxfi": True}, B: {"label": "Other"},
              H: {"label": "Hidden", "hidden": True, "maxfi": True}}
    monkeypatch.setattr(wp, "load_wallet_config", lambda: config)
    monkeypatch.setattr(wp, "_portfolio_cache", _portfolio())

    def _never(*a, **k):
        raise AssertionError("get_portfolio_data must not be called")
    monkeypatch.setattr(wp, "get_portfolio_data", _never)
    _seed(db, 1, A.upper().replace("0X", "0x"), 10.0)                        # mixed-case wallet in the DB
    _seed(db, 2, A, 20.0)                                                     # ledger head withdrawn
    _seed(db, 3, A, 99.0, status="closed", scan="2026-09-27T11:59:00+00:00")  # closed: only feeds latest scan
    _seed(db, 4, H, 50.0)                                                     # hidden wallet: excluded
    loads = []
    monkeypatch.setattr(wp, "_maxfi_ledger_load_inputs", lambda conn, chain=None: loads.append(chain) or {"x": 1})
    monkeypatch.setattr(wp, "_maxfi_ledger_position_claims",
                        lambda **kw: {1: {"ledger_head_closed": False}, 2: {"ledger_head_closed": True}})
    spawned = []
    monkeypatch.setattr(wp, "_spawn_hl_accounts_refresh_thread", lambda wallets: spawned.append(list(wallets)))

    r = client.get("/api/portfolio/total")
    assert r.status_code == 200
    body = r.get_json()
    mx = next(c for c in body["components"] if c["key"] == "maxfi_uncollected")
    assert mx["value_usd"] == pytest.approx(8.5)                             # row 1 only, x 0.85
    assert mx["detail"]["open_rows"] == 2 and mx["detail"]["excluded_ledger_withdrawn"] == 1
    assert loads == ["robinhood"]
    assert body["total_usd"] == pytest.approx(3705.0 + 8.5)
    (d,) = body["maxfi_drift"]
    assert d["latest_scan_at"] == "2026-09-27T11:59:00+00:00"                # closed row's scan counts
    assert "portfolio data predates your last MaxFi scan — press Refresh" in d["warnings"]
    assert spawned == [[A, B]]                                                # background kick only
    assert _TrackedConn.closed_changes and all(n == 0 for n in _TrackedConn.closed_changes)


def test_route_ledger_failure_answers_with_warning(client, db, monkeypatch):
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {A: {"label": "Rabby", "maxfi": True}})
    monkeypatch.setattr(wp, "_portfolio_cache", _portfolio())
    _seed(db, 1, A, 10.0)

    def boom(*a, **k):
        raise RuntimeError("ledger down")
    monkeypatch.setattr(wp, "_maxfi_ledger_load_inputs", boom)
    body = client.get("/api/portfolio/total").get_json()
    mx = next(c for c in body["components"] if c["key"] == "maxfi_uncollected")
    assert mx["value_usd"] == pytest.approx(8.5)
    assert "ledger unavailable — withdrawn-position guard off" in mx["warnings"]


def test_spot_stablecoins_unchanged(client, db):
    db.execute("INSERT INTO portfolio_snapshots (id, wallet, status) VALUES (1, ?, 'completed'), (2, ?, 'completed'), "
               "(3, ?, 'failed')", (A, B, A))
    rows = [(1, A, "USDC", 300.0), (1, A, "ETH", 2000.0), (1, A, "dai", 5.0), (2, B, "USDT", 200.0),
            (2, B, "CRVUSD", 7.0), (2, B, "USDC.e", 9.0), (3, A, "USDC", 999.0)]
    db.executemany("INSERT INTO token_snapshots (snapshot_id, wallet, symbol, value_usd) VALUES (?, ?, ?, ?)", rows)
    db.commit()
    body = client.get("/api/spot/stablecoins").get_json()
    # what the old local tuple would give, via the route's own SQL
    old = db.execute("""
        SELECT t.symbol, t.value_usd, t.wallet FROM token_snapshots t
        JOIN (SELECT wallet, MAX(id) AS snap_id FROM portfolio_snapshots WHERE status = 'completed' GROUP BY wallet) latest
          ON t.snapshot_id = latest.snap_id
        WHERE UPPER(t.symbol) IN ({})""".format(','.join('?' * len(OLD_STABLES))), OLD_STABLES).fetchall()
    expected = [{"symbol": s, "value_usd": v or 0, "wallet": w} for s, v, w in old]
    assert body == {"total_usd": sum(e["value_usd"] for e in expected), "breakdown": expected}
    assert body["total_usd"] == 512.0
