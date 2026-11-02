"""Landing 85: GET /api/portfolio/hyperliquid-spot, the display-only list of
Hyperliquid spot balances for Token Holdings.

The balances are already counted by the complete total's "hyperliquid" part
(portfolio_total.compose_total part 7). The invariant these tests pin: the
route reads the accounts cache only, and nothing it builds can reach
portfolio["tokens"], the wallet snapshots, compose_total's inputs or Spot's
Dry powder, so nothing is counted twice and Hyperliquid USDC (perp margin)
never becomes dry powder. Wallets are made-up test strings, never real
addresses. No network: the cache is filled by hand and the refresh spawner
is a recorder."""
import ast
import copy
import inspect
import json
import math
import os
import textwrap
from datetime import datetime, timedelta, timezone

import pytest

import portfolio_total
import web_portfolio as wp

RM = "0x" + "a1" * 20
RABBY = "0x" + "b2" * 20
HIDDEN = "0x" + "c3" * 20
FETCHED = "2026-11-01T12:00:00+00:00"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


@pytest.fixture
def spawned(monkeypatch):
    calls = []
    monkeypatch.setattr(wp, "_spawn_hl_accounts_refresh_thread", lambda wallets: calls.append(list(wallets)))
    return calls


def _config(monkeypatch, extra=None):
    cfg = {RM: {"label": "Hyperliquid RM"}, RABBY: {"label": "Rabby (Hyperliquid)"},
           HIDDEN: {"label": "Old wallet", "hidden": True}}
    cfg.update(extra or {})
    monkeypatch.setattr(wp, "load_wallet_config", lambda: cfg)
    return cfg


def _fresh():
    return datetime.now(timezone.utc).isoformat()


def _cache(monkeypatch, wallets, fetched_at=None, error=None, wallet_errors=None):
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_CACHE", {
        "fetched_at": _fresh() if fetched_at is None else fetched_at, "wallets": wallets,
        "error": error, "wallet_errors": wallet_errors or {}})


def _coin(coin, amount, price, value=None):
    return {"coin": coin, "amount": amount, "price": price,
            "value": (amount * price if price is not None else None) if value is None else value}


def _wallets():
    return {
        RM: {"perp_account_value": 0.0, "open_perps": 0, "mode": "unifiedAccount", "positions": [],
             "spot": [_coin("USDC", 100.0, 1.0), _coin("UETH", 2.5, 3000.0), _coin("ZZZ", 5.0, None)]},
        RABBY: {"perp_account_value": 0.0, "open_perps": 0, "mode": "unifiedAccount", "positions": [],
                "spot": [_coin("HYPE", 10.0, 20.0)]},
    }


def _get(client):
    r = client.get("/api/portfolio/hyperliquid-spot")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


# -- rows -------------------------------------------------------------------

def test_rows_carry_labels_flags_and_sort(client, monkeypatch, spawned):
    _config(monkeypatch)
    _cache(monkeypatch, _wallets())
    body = _get(client)
    assert body["status"] == "ok" and body["refresh_failed"] is False and body["unread"] == []
    rows = body["rows"]
    assert [(r["wallet_label"], r["coin"]) for r in rows] == [
        ("Hyperliquid RM", "UETH"), ("Hyperliquid RM", "USDC"), ("Hyperliquid RM", "ZZZ"),
        ("Rabby (Hyperliquid)", "HYPE")]
    by = {r["coin"]: r for r in rows}
    assert by["UETH"]["venue_label"] == "Hyperliquid RM App"
    assert by["HYPE"]["venue_label"] == "Rabby (Hyperliquid) App"
    assert by["UETH"]["canonical"] == "ETH" and by["HYPE"]["canonical"] == "HYPE"
    assert [r["coin"] for r in rows if r["margin"]] == ["USDC"]
    assert by["UETH"]["balance"] == 2.5 and by["UETH"]["price_usd"] == 3000.0 and by["UETH"]["value_usd"] == 7500.0
    assert by["ZZZ"]["priced"] is False and by["ZZZ"]["price_usd"] is None and by["ZZZ"]["value_usd"] is None
    assert by["UETH"]["priced"] is True and all(r["stale"] is False for r in rows)
    assert body["as_of"] is not None
    assert spawned == []                      # a fresh cache starts no refresh


def test_only_the_wallet_field_carries_an_address(client, monkeypatch, spawned):
    _config(monkeypatch)
    _cache(monkeypatch, _wallets())
    body = _get(client)
    for r in body["rows"]:
        for k, v in r.items():
            if k != "wallet":
                assert RM not in str(v) and RABBY not in str(v), k
    assert {r["wallet"] for r in body["rows"]} == {RM, RABBY}
    rest = {k: v for k, v in body.items() if k != "rows"}
    assert RM not in json.dumps(rest) and RABBY not in json.dumps(rest)


def test_hidden_and_no_longer_visible_wallets_are_left_out(client, monkeypatch, spawned):
    _config(monkeypatch)
    wallets = _wallets()
    wallets[HIDDEN] = {"spot": [_coin("PURR", 1.0, 2.0)]}
    wallets["0x" + "d4" * 20] = {"spot": [_coin("PURR", 1.0, 2.0)]}        # in the cache, not in Settings
    _cache(monkeypatch, wallets)
    assert {r["wallet"] for r in _get(client)["rows"]} == {RM, RABBY}


def test_unlabelled_wallet_and_case_insensitive_label_lookup(client, monkeypatch, spawned):
    cfg = {RM.upper().replace("0X", "0x"): {}, RABBY: {"label": "  Desk  "}}
    monkeypatch.setattr(wp, "load_wallet_config", lambda: cfg)
    _cache(monkeypatch, {RM: {"spot": [_coin("HYPE", 1.0, 1.0)]}, RABBY: {"spot": [_coin("HYPE", 1.0, 1.0)]}})
    labels = {r["wallet"]: r["venue_label"] for r in _get(client)["rows"]}
    assert labels == {RM: "Unlabelled wallet App", RABBY: "Desk App"}


def test_row_builder_skips_unusable_balances(monkeypatch):
    cfg = _config(monkeypatch)
    state = {"wallets": {RM: {"spot": [
        _coin("OK", 1.0, 2.0), _coin("ZERO", 0.0, 2.0), _coin("NEG", -1.0, 2.0), _coin("NAN", float("nan"), 2.0),
        _coin("", 1.0, 2.0), {"coin": "STR", "amount": "abc", "price": 1.0, "value": 1.0}, "junk", None,
        {"coin": "INF", "amount": 1.0, "price": float("inf"), "value": float("inf")}]}}}
    rows = wp._hl_spot_holdings(state, cfg, {RM.lower()})
    assert [r["coin"] for r in rows] == ["OK", "INF"]
    inf = next(r for r in rows if r["coin"] == "INF")
    assert inf["priced"] is False and inf["value_usd"] is None and inf["price_usd"] is None
    assert all(math.isfinite(r["balance"]) for r in rows)
    assert wp._hl_spot_holdings({"wallets": {RM: "not a dict"}}, cfg, {RM.lower()}) == []
    assert wp._hl_spot_holdings({}, cfg, {RM.lower()}) == []


def test_stale_wallet_unread_wallet_and_failed_refresh_are_reported(client, monkeypatch, spawned):
    _config(monkeypatch)
    wallets = _wallets()
    wallets[RM]["stale"] = True
    del wallets[RABBY]
    _cache(monkeypatch, wallets, error="refresh failed for " + RABBY,
           wallet_errors={RM: "boom " + RM, RABBY: "boom " + RABBY, HIDDEN: "boom"})
    body = _get(client)
    assert body["refresh_failed"] is True
    assert body["unread"] == ["Rabby (Hyperliquid)"]                  # RM has an older good row; HIDDEN is not visible
    assert all(r["stale"] is True for r in body["rows"])
    assert RM not in json.dumps({k: v for k, v in body.items() if k != "rows"})


# -- cache states and the refresh kick --------------------------------------

def test_cold_cache_answers_loading_and_starts_one_refresh(client, monkeypatch, spawned):
    _config(monkeypatch)
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    body = _get(client)
    assert body == {"status": "loading", "as_of": None, "rows": [], "unread": [], "refresh_failed": False}
    assert spawned == [[RM, RABBY]]                       # visible EVM wallets only
    _get(client)
    assert len(spawned) == 1                              # in flight: no second start


def test_first_refresh_failure_answers_error_without_its_text(client, monkeypatch, spawned):
    _config(monkeypatch)
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_CACHE", {
        "fetched_at": None, "wallets": {}, "error": "every wallet failed: " + RM + ": ConnectionError"})
    body = _get(client)
    assert body["status"] == "error" and body["rows"] == []
    assert RM not in json.dumps(body) and "ConnectionError" not in json.dumps(body)


def test_no_visible_evm_wallet_is_ok_and_empty(client, monkeypatch, spawned):
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {"xpub6ABC": {"type": "bitcoin_xpub"}})
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    assert _get(client) == {"status": "ok", "as_of": None, "rows": [], "unread": [], "refresh_failed": False}
    assert spawned == []


def test_a_stale_cache_starts_the_refresh_and_still_answers_its_rows(client, monkeypatch, spawned):
    _config(monkeypatch)
    old = (datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat()
    _cache(monkeypatch, _wallets(), fetched_at=old)
    body = _get(client)
    assert body["status"] == "ok" and len(body["rows"]) == 4 and body["as_of"] == old
    assert spawned == [[RM, RABBY]]


def test_the_route_is_get_only_and_needs_a_login(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    rules = [r for r in wp.app.url_map.iter_rules() if r.rule == "/api/portfolio/hyperliquid-spot"]
    assert len(rules) == 1 and rules[0].methods - {"HEAD", "OPTIONS"} == {"GET"}
    anon = wp.app.test_client()
    assert anon.get("/api/portfolio/hyperliquid-spot").status_code == 401


# -- the invariant: display only --------------------------------------------

def test_the_route_never_touches_the_portfolio_cache(client, monkeypatch, spawned):
    _config(monkeypatch)
    _cache(monkeypatch, _wallets())
    sentinel = {"tokens": [{"wallet": RM, "chain": "base", "symbol": "SENTINEL", "value_usd": 5.0}],
                "lp_positions": [], "total_tokens_value": 5.0, "total_value": 5.0}
    monkeypatch.setattr(wp, "_portfolio_cache", sentinel)
    before = copy.deepcopy(sentinel)
    body = _get(client)
    assert sentinel == before
    assert "SENTINEL" not in json.dumps(body)


def test_the_route_leaves_the_cache_alone_and_the_total_counts_the_balances_once(client, monkeypatch, spawned):
    _config(monkeypatch)
    wallets = _wallets()
    _cache(monkeypatch, wallets)
    portfolio = {"fetched_at": "2026-11-01T12:00:00", "wallet_labels": {RM: "Hyperliquid RM"},
                 "tokens": [{"wallet": RM, "chain": "base", "symbol": "WETH", "value_usd": 1000.0},
                            {"wallet": RM, "chain": "base", "symbol": "USDC", "value_usd": 400.0}],
                 "lp_positions": [], "aave_positions": [], "gmx_positions": []}
    now = datetime(2026, 11, 1, 12, 5, tzinfo=timezone.utc)

    def total():
        # compose_total on the SAME cache the route reads
        return portfolio_total.compose_total(copy.deepcopy(portfolio), [], set(), True, {},
                                             wp._hl_accounts_cache_copy(), now)

    cache_before = copy.deepcopy(wp._HL_ACCOUNTS_CACHE)
    first = total()
    _get(client)
    _get(client)
    assert wp._HL_ACCOUNTS_CACHE == cache_before          # no pop, sort or rewrite of the cache by the route
    second = total()
    assert first == second
    parts = {c["key"]: c["value_usd"] for c in second["components"]}
    assert parts["wallet_tokens"] == 1000.0 and parts["stablecoins"] == 400.0
    assert parts["hyperliquid"] == 100.0 + 2.5 * 3000.0 + 10.0 * 20.0      # ZZZ has no price: not counted
    assert second["total_usd"] == 1000.0 + 400.0 + parts["hyperliquid"]


ALLOWED_USERS = {
    ("web_portfolio.py", "<module>"): {"HL_SPOT_ALIASES", "HL_SPOT_VENUE_SUFFIX"},        # their definitions
    ("web_portfolio.py", "api_portfolio_hyperliquid_spot"): {"_hl_spot_holdings", "_hl_spot_wallet_label"},
    ("web_portfolio.py", "api_spot_locations"): {"_hl_spot_holdings"},
    # Landing 86: the "Held at" choices name your Hyperliquid wallets the same way ("<label> App")
    ("web_portfolio.py", "_spot_wallet_app_name"): {"HL_SPOT_VENUE_SUFFIX"},
    ("web_portfolio.py", "_hl_spot_holdings"): {"_hl_spot_wallet_label", "HL_SPOT_ALIASES", "HL_SPOT_VENUE_SUFFIX"},
}
WATCHED = {"_hl_spot_holdings", "_hl_spot_wallet_label", "HL_SPOT_ALIASES", "HL_SPOT_VENUE_SUFFIX"}


def _uses_in_module(path):
    """{(file, enclosing function or '<module>'): names of watched helpers it mentions}"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rel = os.path.relpath(path, root)
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    found = {}

    def visit(node, scope):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else scope
            name = child.id if isinstance(child, ast.Name) else child.attr if isinstance(child, ast.Attribute) else None
            if name in WATCHED:
                found.setdefault((rel, scope), set()).add(name)
            visit(child, inner)
    visit(tree, "<module>")
    return found


def test_only_the_two_display_routes_use_the_display_helpers():
    """The helpers exist for two pages. If any other module or function (the
    snapshot writer, the total's inputs, the history hints, the scheduler, the
    advisors, Telegram, Dry powder...) starts to read them, Hyperliquid
    balances would be counted twice or reach Dry powder - the failure this
    landing was designed around. Every non-test .py file is parsed."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    uses = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("tests", ".git", "node_modules", "__pycache__", "data")]
        for name in files:
            if name.endswith(".py"):
                uses.update(_uses_in_module(os.path.join(base, name)))
    assert uses == ALLOWED_USERS, uses
    # the route path is named in no other Python module, and in no function that counts money
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("tests", ".git", "node_modules", "__pycache__", "data")]
        for name in files:
            if name.endswith(".py") and name != "web_portfolio.py":
                with open(os.path.join(base, name), encoding="utf-8") as f:
                    assert "hyperliquid-spot" not in f.read(), name
    for fn in (wp.get_portfolio_data, wp.api_portfolio, wp.api_portfolio_total, wp._compose_total_for_snapshot,
               wp._portfolio_total_db_inputs, wp._portfolio_total_history_hints, wp._spot_stable_rows,
               wp.api_spot_stablecoins, wp.api_spot_change_24h):
        assert "hyperliquid-spot" not in inspect.getsource(fn), fn.__name__


def _code_only(fn):
    """The function's source without its docstring (which names what it avoids)."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    func = tree.body[0]
    func.body = [n for n in func.body
                 if not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant)
                         and isinstance(n.value.value, str))]
    return ast.unparse(func)


def test_the_route_reads_no_database_and_no_portfolio_data():
    route = _code_only(wp.api_portfolio_hyperliquid_spot)
    for banned in ("get_connection", "_portfolio_cache", "get_portfolio_data", "execute(", "insert_", "requests."):
        assert banned not in route, banned
    helper = _code_only(wp._hl_spot_holdings)
    for banned in ("get_connection", "_portfolio_cache", "execute(", "requests.", "_hl_post"):
        assert banned not in helper, banned
    assert "_hl_accounts_cache_copy" in route and "_maybe_kick_hl_accounts_refresh" in route


def test_unit_coin_aliases_are_exactly_these_three(client, monkeypatch, spawned):
    assert wp.HL_SPOT_ALIASES == {"UBTC": "BTC", "UETH": "ETH", "USOL": "SOL"}
    _config(monkeypatch)
    _cache(monkeypatch, {RM: {"spot": [_coin(c, 1.0, 1.0) for c in ("UBTC", "UETH", "USOL", "ubtc", "BTC", "HYPE")]}})
    got = {r["coin"]: r["canonical"] for r in _get(client)["rows"]}
    assert got == {"UBTC": "BTC", "UETH": "ETH", "USOL": "SOL", "ubtc": "BTC", "BTC": "BTC", "HYPE": "HYPE"}


def test_a_failure_answers_with_the_error_type_only(client, monkeypatch, spawned):
    _config(monkeypatch)
    _cache(monkeypatch, _wallets())

    def boom(state, config, visible):
        raise RuntimeError("secret " + RM)
    monkeypatch.setattr(wp, "_hl_spot_holdings", boom)
    r = client.get("/api/portfolio/hyperliquid-spot")
    assert r.status_code == 500 and r.get_json() == {"error": "RuntimeError"}
    assert RM not in r.get_data(as_text=True)


def test_a_failing_refresh_kick_does_not_break_the_answer(client, monkeypatch, spawned):
    _config(monkeypatch)
    _cache(monkeypatch, _wallets())

    def boom(now):
        raise RuntimeError("kick failed " + RM)
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", boom)
    body = _get(client)
    assert body["status"] == "ok" and len(body["rows"]) == 4
