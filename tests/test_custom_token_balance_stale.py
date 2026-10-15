"""Stale custom-token balances (Landing 39, Oct 14).

A custom token's balance is served from a 5-minute in-process cache; an
expired entry is served at once while a background refresh runs. When that
refresh fails, the last good balance stays served and counted with no sign.
Landing 39 records the failure (_custom_balance_refresh_failed, cleared by
the next success) and flags the holdings row (balance_stale, balance_as_of =
the time of the read still shown). portfolio_total adds one display-only
clause per part (ruling 11). No value changes anywhere.

Real init_db() on a tmp_path SQLite file. Every RPC and price call is faked;
no network. Addresses are synthetic.
"""
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

import portfolio_total as pt
import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

TOKEN = "0x" + "5A" * 20                      # synthetic ERC-20 contract (mixed case, as stored)
WALLET = "0x" + "1" * 40
WALLET2 = "0x" + "2" * 40
MINT = "MintStaleXyz" + "4" * 30              # synthetic Solana mint (mixed case)
SOL_WALLET = "SynthStaleWa11et" + "5" * 26    # synthetic Solana wallet
PRICE = 2.0


def _wait(cond, timeout=3.0):
    """Polls without time.sleep (a fixture's sleep stub would hit it too)."""
    ev = threading.Event()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        ev.wait(0.01)
    return cond()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """One custom token on base and two EVM wallets; tests drive the balance
    read (state["balance"]: a number, a dict per wallet, or an Exception
    to raise) and may record spawns instead of starting threads."""
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO custom_tokens (chain, contract, symbol, decimals, added_at) "
                 "VALUES ('base', ?, 'STALE', 18, '2026-01-01T00:00:00')", (TOKEN,))
    conn.commit()
    conn.close()
    wp._dexscreener_price_cache.clear()
    wp._custom_balance_cache.clear()
    wp._custom_balance_refresh_failed.clear()
    with wp._balance_refresh_lock:
        wp._balance_refresh_inflight.clear()
    state = {"balance": 1000.0, "wallets": [WALLET], "spawns": [], "record_spawns": True,
             "config": {WALLET: {"label": "Main"}, WALLET2: {"label": "Second"}}}

    def balance(chain, contract, wallet, decimals):
        if state.get("gate") is not None:
            state["gate"].wait(3)      # holds a background refresh until released
        b = state["balance"]
        if isinstance(b, dict):
            b = b[wallet]
        if isinstance(b, Exception):
            raise b
        return b

    real_spawn = wp._spawn_balance_refresh

    def spawn(chain, contract, wallet, decimals, key):
        state["spawns"].append(key)
        if not state["record_spawns"]:
            real_spawn(chain, contract, wallet, decimals, key)

    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: list(state["wallets"]))
    monkeypatch.setattr(wp, "load_wallet_config", lambda: state["config"])
    monkeypatch.setattr(wp, "custom_token_chain_supported", lambda chain: (True, "RPC"))
    monkeypatch.setattr(wp, "fetch_dexscreener_price", lambda contract, chain=None, _now=None: PRICE)
    monkeypatch.setattr(wp, "_custom_token_balance", balance)
    monkeypatch.setattr(wp, "_spawn_balance_refresh", spawn)
    yield state
    if state.get("gate") is not None:
        state["gate"].set()                     # never leave a refresh thread waiting
    wp._dexscreener_price_cache.clear()
    wp._custom_balance_cache.clear()
    wp._custom_balance_refresh_failed.clear()
    with wp._balance_refresh_lock:
        wp._balance_refresh_inflight.clear()


def _key(wallet=WALLET):
    return ("base", TOKEN.lower(), wallet.lower())


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _row(rows, wallet=WALLET):
    return next(r for r in rows if r["wallet"] == wallet)


# ── the holdings rows ──────────────────────────────────────────────────────

def test_fresh_read_is_not_stale(env):
    row = _row(wp.build_custom_token_rows())
    assert (row["balance"], row["value_usd"]) == (1000.0, 2000.0)
    assert (row["balance_stale"], row["balance_as_of"], row["balance_failed"]) == (False, None, False)


def test_expired_entry_without_a_failure_is_not_stale(env):
    t0 = time.time() - 3 * 3600
    wp._custom_balance_cache[_key()] = (800.0, t0)
    row = _row(wp.build_custom_token_rows())
    assert (row["balance"], row["value_usd"]) == (800.0, 1600.0)        # the stale-served value
    assert (row["balance_stale"], row["balance_as_of"]) == (False, None)
    assert env["spawns"] == [_key()]                                    # a refresh was started


def test_failed_refresh_flags_the_row_and_keeps_its_value(env):
    t0 = time.time() - 3 * 3600
    wp._custom_balance_cache[_key()] = (800.0, t0)
    plain = _row(wp.build_custom_token_rows())
    wp._custom_balance_refresh_failed[_key()] = t0 + 600
    row = _row(wp.build_custom_token_rows())
    assert (row["balance_stale"], row["balance_as_of"]) == (True, _iso(t0))
    assert (row["balance"], row["value_usd"], row["balance_failed"]) == (800.0, 1600.0, False)
    # Nothing else in the row changes.
    new_fields = ("balance_stale", "balance_as_of")
    assert ({k: v for k, v in row.items() if k not in new_fields}
            == {k: v for k, v in plain.items() if k not in new_fields})


def test_failure_older_than_the_read_is_not_stale(env):
    t0 = time.time() - 3 * 3600
    wp._custom_balance_cache[_key()] = (800.0, t0)
    wp._custom_balance_refresh_failed[_key()] = t0 - 1
    row = _row(wp.build_custom_token_rows())
    assert (row["balance_stale"], row["balance_as_of"]) == (False, None)


def test_failed_first_read_is_failed_not_stale(env):
    env["balance"] = RuntimeError("rpc down")
    wp._custom_balance_refresh_failed[_key()] = time.time()
    row = _row(wp.build_custom_token_rows())
    assert (row["balance"], row["value_usd"], row["balance_failed"]) == (None, 0.0, True)
    assert (row["balance_stale"], row["balance_as_of"]) == (False, None)


def test_only_the_failing_wallet_is_flagged(env):
    env["wallets"] = [WALLET, WALLET2]
    t0 = time.time() - 3 * 3600
    wp._custom_balance_cache[_key(WALLET)] = (800.0, t0)
    wp._custom_balance_cache[_key(WALLET2)] = (50.0, t0)
    wp._custom_balance_refresh_failed[_key(WALLET)] = t0 + 600
    rows = wp.build_custom_token_rows()
    assert _row(rows, WALLET)["balance_stale"] is True
    assert (_row(rows, WALLET2)["balance_stale"], _row(rows, WALLET2)["balance_as_of"]) == (False, None)
    assert [r["value_usd"] for r in rows] == [1600.0, 100.0]


def test_served_value_differing_from_the_entry_is_not_stale(env, monkeypatch):
    # A refresh landed between the read and the row: the time no longer
    # belongs to the value shown, so nothing is claimed.
    t0 = time.time() - 3 * 3600
    wp._custom_balance_cache[_key()] = (800.0, t0)
    wp._custom_balance_refresh_failed[_key()] = t0 + 600
    monkeypatch.setattr(wp, "fetch_erc20_balance_cached", lambda chain, contract, wallet, decimals, _now=None: 799.0)
    row = _row(wp.build_custom_token_rows())
    assert (row["balance"], row["balance_stale"], row["balance_as_of"]) == (799.0, False, None)


def test_a_broken_staleness_check_never_costs_the_row(env, monkeypatch):
    # The check runs outside the balance read: if it ever raised, the row
    # must still carry its balance and value (never "—" / $0).
    monkeypatch.setattr(wp, "fetch_erc20_balance_cached", lambda chain, contract, wallet, decimals, _now=None: 800.0)

    def boom(*a, **k):
        raise RuntimeError("key helper broke")
    monkeypatch.setattr(wp, "_custom_balance_key", boom)
    row = _row(wp.build_custom_token_rows())
    assert (row["balance"], row["value_usd"], row["balance_failed"]) == (800.0, 1600.0, False)
    assert (row["balance_stale"], row["balance_as_of"]) == (False, None)


def test_staleness_helper_never_raises(monkeypatch):
    def boom(*a):
        raise ValueError("x")
    monkeypatch.setattr(wp, "_custom_balance_key", boom)
    assert wp._custom_balance_staleness("base", TOKEN, WALLET, 1.0) == (False, None)
    assert wp._custom_balance_staleness("base", TOKEN, WALLET, None) == (False, None)


def test_solana_key_keeps_its_case(env):
    env["wallets"] = [SOL_WALLET]
    env["config"] = {SOL_WALLET: {"label": "Sol", "type": "solana"}}
    conn = sqlite3.connect(portfolio_db.get_db_path())
    conn.execute("DELETE FROM custom_tokens")
    conn.execute("INSERT INTO custom_tokens (chain, contract, symbol, decimals, added_at) "
                 "VALUES ('solana', ?, 'SOLX', 6, '2026-01-01T00:00:00')", (MINT,))
    conn.commit()
    conn.close()
    t0 = time.time() - 3 * 3600
    key = ("solana", MINT, SOL_WALLET)
    assert wp._custom_balance_key("solana", MINT, SOL_WALLET) == key
    wp._custom_balance_cache[key] = (1000.0, t0)
    wp._custom_balance_refresh_failed[key] = t0 + 60
    row = _row(wp.build_custom_token_rows(), SOL_WALLET)
    assert (row["chain"], row["balance_stale"], row["balance_as_of"]) == ("Solana", True, _iso(t0))
    # A lowercased key (EVM shape) would not match the Solana entry.
    wp._custom_balance_refresh_failed.clear()
    wp._custom_balance_refresh_failed[("solana", MINT.lower(), SOL_WALLET.lower())] = t0 + 60
    assert _row(wp.build_custom_token_rows(), SOL_WALLET)["balance_stale"] is False


# ── the background refresh records and clears failures ─────────────────────

def test_refresh_failure_is_recorded_and_success_clears_it(env):
    env["record_spawns"] = False
    t0 = time.time() - 3 * 3600
    wp._custom_balance_cache[_key()] = (800.0, t0)
    env["balance"] = RuntimeError("rpc down")
    before = time.time()
    wp._spawn_balance_refresh("base", TOKEN, WALLET, 18, _key())
    assert _wait(lambda: _key() in wp._custom_balance_refresh_failed and _key() not in wp._balance_refresh_inflight)
    assert wp._custom_balance_refresh_failed[_key()] >= before
    assert wp._custom_balance_cache[_key()] == (800.0, t0)            # last good read kept

    env["balance"] = 900.0
    wp._spawn_balance_refresh("base", TOKEN, WALLET, 18, _key())
    assert _wait(lambda: wp._custom_balance_cache[_key()][0] == 900.0 and _key() not in wp._balance_refresh_inflight)
    assert _key() not in wp._custom_balance_refresh_failed


def test_two_builds_flag_a_failing_refresh_then_clear_after_success(env):
    """End to end: the build that starts a failing refresh can't know yet;
    the next one flags it; after a successful refresh the flag goes."""
    env["record_spawns"] = False
    t0 = time.time() - 3 * 3600
    wp._custom_balance_cache[_key()] = (800.0, t0)
    env["balance"] = RuntimeError("rpc down")
    env["gate"] = threading.Event()            # the refresh fails only after the build

    first = _row(wp.build_custom_token_rows())
    assert (first["balance"], first["balance_stale"]) == (800.0, False)
    env["gate"].set()
    assert _wait(lambda: _key() in wp._custom_balance_refresh_failed and _key() not in wp._balance_refresh_inflight)

    second = _row(wp.build_custom_token_rows())
    assert (second["balance"], second["value_usd"]) == (800.0, 1600.0)
    assert (second["balance_stale"], second["balance_as_of"]) == (True, _iso(t0))
    assert _wait(lambda: _key() not in wp._balance_refresh_inflight)

    env["balance"] = 900.0
    third = _row(wp.build_custom_token_rows())                 # serves 800 again, refresh succeeds
    assert third["balance"] == 800.0
    assert _wait(lambda: wp._custom_balance_cache[_key()][0] == 900.0 and _key() not in wp._balance_refresh_inflight)
    assert _key() not in wp._custom_balance_refresh_failed
    fourth = _row(wp.build_custom_token_rows())                # fresh entry: no refresh, not stale
    assert (fourth["balance"], fourth["balance_stale"], fourth["balance_as_of"]) == (900.0, False, None)


# ── the total's warning line (portfolio_total ruling 11) ───────────────────

NOW = datetime(2026, 10, 14, 20, 0, tzinfo=timezone.utc)
A = "0x" + "a" * 40
B = "0x" + "b" * 40


def _portfolio(*extra):
    return {
        "tokens": [{"symbol": "ETH", "value_usd": 2000.0, "wallet": A},
                   {"symbol": "USDC", "value_usd": 300.0, "wallet": A}] + list(extra),
        "lp_positions": [], "aave_positions": [], "gmx_positions": [], "staking_positions": [],
        "total_tokens_value": 2300.0, "total_lp_value": 0.0, "total_uncollected_fees": 0.0,
        "total_value": 2300.0, "wallet_labels": {A: "Rabby", B: "Other"}, "fetched_at": "2026-10-14T19:50:00",
    }


def _compose(p, hints=None):
    return pt.compose_total(p, [], set(), True, {}, {"fetched_at": None, "wallets": {}, "error": None}, NOW,
                            history_hints=hints)


def _c(result, key):
    return next(c for c in result["components"] if c["key"] == key)


def _stale(symbol="SOLX", value=4200.0, wallet=A, hours=3.0, contract=MINT, chain="Solana", **kw):
    row = {"chain": chain, "symbol": symbol, "balance": value / PRICE, "value_usd": value, "price_usd": PRICE,
           "contract": contract, "wallet": wallet, "source": "custom", "balance_failed": False,
           "price_stale": False, "price_as_of": None, "balance_stale": True,
           "balance_as_of": (NOW - timedelta(hours=hours)).isoformat()}
    row.update(kw)
    return row


def test_stale_balance_line_and_value_counted():
    r = _compose(_portfolio(_stale()))
    wt = _c(r, "wallet_tokens")
    assert wt["warnings"] == ["1 token at last good balance — about $4,200 (SOLX, 3 h old)"]
    assert wt["value_usd"] == pytest.approx(2000.0 + 4200.0)
    assert wt["detail"]["stale_balance"] == {"rows": 1, "tokens": 1, "est_usd": 4200.0, "symbols": ["SOLX"],
                                             "balance_oldest_hours": pytest.approx(3.0)}
    assert {"component": "wallet_tokens", "warning": wt["warnings"][0]} in r["warnings"]


def test_total_and_values_unchanged_by_the_flag():
    flagged = _compose(_portfolio(_stale()))
    plain = _compose(_portfolio(_stale(balance_stale=False, balance_as_of=None)))
    bare = _stale()
    del bare["balance_stale"], bare["balance_as_of"]
    older = _compose(_portfolio(bare))
    assert flagged["total_usd"] == plain["total_usd"] == older["total_usd"]
    assert [c["value_usd"] for c in flagged["components"]] == [c["value_usd"] for c in plain["components"]]
    assert plain == older                                       # rows without the fields read as before
    assert "stale_balance" not in _c(plain, "wallet_tokens")["detail"]


def test_small_stale_balance_is_detail_only():
    wt = _c(_compose(_portfolio(_stale(value=300.0))), "wallet_tokens")
    assert wt["warnings"] == []
    assert wt["detail"]["stale_balance"]["est_usd"] == 300.0


@pytest.mark.parametrize("hours, text", [
    (40 / 60, "40 min old"), (5 / 3600, "1 min old"), (59.7 / 60, "1 h old"), (1.0, "1 h old"),
    (26.4, "26 h old")])
def test_age_wording(hours, text):
    wt = _c(_compose(_portfolio(_stale(hours=hours))), "wallet_tokens")
    assert wt["warnings"] == [f"1 token at last good balance — about $4,200 (SOLX, {text})"]


def test_missing_time_has_no_age():
    wt = _c(_compose(_portfolio(_stale(balance_as_of=None))), "wallet_tokens")
    assert wt["warnings"] == ["1 token at last good balance — about $4,200 (SOLX)"]
    assert wt["detail"]["stale_balance"]["balance_oldest_hours"] is None


def test_zero_value_rows_skipped_and_wallets_count_once():
    rows = [_stale(value=2600.0, wallet=A), _stale(value=1600.0, wallet=B, hours=5.0),
            _stale(value=0.0, wallet="0x" + "c" * 40, hours=9.0)]
    wt = _c(_compose(_portfolio(*rows)), "wallet_tokens")
    assert wt["warnings"] == ["1 token at last good balance — about $4,200 (SOLX, 5 h old)"]
    assert (wt["detail"]["stale_balance"]["rows"], wt["detail"]["stale_balance"]["tokens"]) == (2, 1)


def test_stablecoin_custom_token_goes_on_the_stablecoins_line():
    usdc = _stale(symbol="USDC", value=1200.0, contract="0x" + "ee" * 20, chain="Base")
    r = _compose(_portfolio(usdc))
    assert _c(r, "stablecoins")["warnings"] == ["1 token at last good balance — about $1,200 (USDC, 3 h old)"]
    assert _c(r, "wallet_tokens")["warnings"] == []


def test_clause_order_price_then_balance_then_uncounted():
    carried = _stale(symbol="PLAZM", value=3800.0, contract="0x" + "ab" * 20, chain="Base",
                     balance_stale=False, balance_as_of=None, price_stale=True,
                     price_as_of=(NOW - timedelta(hours=2)).isoformat())
    unpriced = {"chain": "Base", "symbol": "VIRT", "balance": 100000.0, "value_usd": 0.0, "price_usd": 0.0,
                "contract": "0x" + "cd" * 20, "wallet": A}
    hints = {"token_prices": {pt.token_hint_key(unpriced): {"price_usd": 0.05, "at": NOW.isoformat()}},
             "token_balances": {}, "lp_last_valued": {}}
    wt = _c(_compose(_portfolio(carried, _stale(), unpriced), hints), "wallet_tokens")
    assert wt["warnings"] == [
        "1 token at last good price — about $3,800 (PLAZM, 2 h old); "
        "1 token at last good balance — about $4,200 (SOLX, 3 h old); "
        "1 token unpriced — about $5,000 not counted (VIRT)"]


def test_three_stale_tokens_list_three_symbols():
    rows = [_stale(symbol=s, contract="0x" + c * 20, chain="Base", value=600.0)
            for s, c in (("AAA", "a1"), ("BBB", "b2"), ("CCC", "c3"), ("DDD", "d4"))]
    wt = _c(_compose(_portfolio(*rows)), "wallet_tokens")
    assert wt["warnings"] == ["4 tokens at last good balance — about $2,400 (AAA, BBB, CCC, 3 h old)"]
