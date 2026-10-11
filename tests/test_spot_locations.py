"""GET /api/spot/locations (Landing 26): which tracked wallets hold each open
spot position, from the latest completed snapshot of each visible wallet.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched); _calculate_spot_fifo and load_wallet_config are monkeypatched.
Wallets are plain test strings, never real addresses. Read-only route, no
network."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

T0 = datetime(2026, 10, 10, 12, 0, 0)
EVM = "0x" + "ab" * 20
EVM_OTHER = "0x" + "cd" * 20
SOL_A = "So1anaMintAbc111111111111111111111111111111"
SOL_B = "So1anaMintABC111111111111111111111111111111"      # differs only by case


@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    return path


@pytest.fixture(autouse=True)
def now(monkeypatch):
    """'Now' for the staleness check: one hour after T0."""
    monkeypatch.setattr(wp, "_spot_location_now", lambda: (T0 + timedelta(hours=1)).replace(tzinfo=timezone.utc))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _wallets(monkeypatch, **labels):
    """Wallet config: name -> label (None = no label key; 'hidden' marks a hidden wallet)."""
    cfg = {}
    for name, label in labels.items():
        if label == "hidden":
            cfg[name] = {"label": name.title(), "hidden": True}
        elif label is None:
            cfg[name] = {}
        else:
            cfg[name] = {"label": label}
    monkeypatch.setattr(wp, "load_wallet_config", lambda: cfg)


def _positions(monkeypatch, *specs):
    """specs: (key, symbol, units); key = (chain, address) or a symbol string."""
    out = {}
    for key, symbol, units in specs:
        chain, addr = key if isinstance(key, tuple) else ("", "")
        out[key] = {"symbol": symbol, "chain": chain, "contract_address": addr, "units": units,
                    "position_key": wp._stringify_spot_position_key(key)}
    monkeypatch.setattr(wp, "_calculate_spot_fifo", lambda conn: (out, {}))


def _run(path, wallet, hours=0, status="completed"):
    """One portfolio_snapshots run for a wallet at T0 + hours; returns its id."""
    conn = sqlite3.connect(path)
    cur = conn.execute("INSERT INTO portfolio_snapshots (user_id, timestamp, wallet, status) VALUES (1, ?, ?, ?)",
                       ((T0 + timedelta(hours=hours)).isoformat(), wallet, status))
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def _tok(path, snap_id, wallet, chain, symbol, address, balance):
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO token_snapshots (snapshot_id, user_id, timestamp, wallet, chain, symbol, token_address, balance, "
        "price_usd, value_usd) VALUES (?, 1, ?, ?, ?, ?, ?, ?, 1, ?)",
        (snap_id, T0.isoformat(), wallet, chain, symbol, address, balance, balance))
    conn.commit()
    conn.close()


def _get(client):
    r = client.get("/api/spot/locations")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _labels(body, key):
    return [w["label"] for w in body["positions"][key]["wallets"]]


# ── the pure matcher ───────────────────────────────────────────────────────

@pytest.mark.parametrize("pos, row, expected", [
    ({"symbol": "TOK", "chain": "base", "contract_address": EVM}, {"chain": "Base", "symbol": "X", "token_address": EVM.upper().replace("0X", "0x")}, True),
    ({"symbol": "TOK", "chain": "base", "contract_address": EVM}, {"chain": "Ethereum", "symbol": "TOK", "token_address": EVM}, False),
    ({"symbol": "TOK", "chain": "base", "contract_address": EVM}, {"chain": "Base", "symbol": "TOK", "token_address": EVM_OTHER}, False),
    ({"symbol": "TOK", "chain": "solana", "contract_address": SOL_A}, {"chain": "Solana", "symbol": "TOK", "token_address": SOL_B}, False),
    ({"symbol": "TOK", "chain": "solana", "contract_address": SOL_A}, {"chain": "Solana", "symbol": "TOK", "token_address": SOL_A}, True),
    ({"symbol": "TOK", "chain": "bsc", "contract_address": EVM}, {"chain": "BSC", "symbol": "TOK", "token_address": EVM}, True),
    # native coin rows (no contract): by symbol, and chain when the position has one
    ({"symbol": "ETH", "chain": "base", "contract_address": EVM}, {"chain": "Base", "symbol": "eth", "token_address": ""}, True),
    ({"symbol": "ETH", "chain": "base", "contract_address": EVM}, {"chain": "Ethereum", "symbol": "ETH", "token_address": None}, False),
    ({"symbol": "BTC", "chain": "", "contract_address": ""}, {"chain": "Bitcoin", "symbol": "BTC", "token_address": ""}, True),
    ({"symbol": "WETH", "chain": "base", "contract_address": EVM}, {"chain": "Base", "symbol": "ETH", "token_address": ""}, False),
    # a symbol-keyed position never matches a row that has a contract (airdrop copies)
    ({"symbol": "BTC", "chain": "", "contract_address": ""}, {"chain": "Base", "symbol": "BTC", "token_address": EVM}, False),
    # custom-token rows store the chain label ("Robinhood Chain"); BNB Chain's label too
    ({"symbol": "TOK", "chain": "robinhood", "contract_address": EVM}, {"chain": "Robinhood Chain", "symbol": "TOK", "token_address": EVM}, True),
    ({"symbol": "TOK", "chain": "bsc", "contract_address": EVM}, {"chain": "BNB Chain", "symbol": "TOK", "token_address": EVM}, True),
    ({"symbol": "TOK", "chain": "robinhood", "contract_address": EVM}, {"chain": "Base", "symbol": "TOK", "token_address": EVM}, False),
    # staked TAO rows are TAO; subnet alpha rows are not
    ({"symbol": "TAO", "chain": "", "contract_address": ""}, {"chain": "Bittensor", "symbol": "TAO root", "token_address": ""}, True),
    ({"symbol": "TAO", "chain": "", "contract_address": ""}, {"chain": "Bittensor", "symbol": "TAO reserved", "token_address": ""}, True),
    ({"symbol": "TAO", "chain": "", "contract_address": ""}, {"chain": "Bittensor", "symbol": "SN64 alpha", "token_address": ""}, False),
])
def test_row_matcher(pos, row, expected):
    assert wp._spot_location_row_matches(pos, row) is expected


# ── the route ──────────────────────────────────────────────────────────────

def test_found_by_address_with_label_and_no_wallet_id_in_the_reply(client, dbpath, monkeypatch):
    _wallets(monkeypatch, wallet_a="Desktop Hot")
    _positions(monkeypatch, (("base", EVM), "TOK", 100.0))
    s = _run(dbpath, "wallet_a")
    _tok(dbpath, s, "wallet_a", "Base", "TOK", EVM.upper().replace("0X", "0x"), 100.0)
    body = _get(client)
    entry = body["positions"]["base " + EVM]
    assert entry["status"] == "found"
    assert entry["wallets"] == [{"label": "Desktop Hot", "units": 100.0, "as_of": "2026-10-10T12:00:00+00:00", "stale": False}]
    assert body["as_of"] == "2026-10-10T12:00:00+00:00"
    assert "wallet_a" not in json.dumps(body)


def test_split_is_largest_first_then_by_label(client, dbpath, monkeypatch):
    _wallets(monkeypatch, wallet_a="Plazm", wallet_b="Desktop Hot", wallet_c="Alpha")
    _positions(monkeypatch, (("base", EVM), "TOK", 100.0))
    for w, bal in (("wallet_a", 30.0), ("wallet_b", 70.0), ("wallet_c", 30.0)):
        _tok(dbpath, _run(dbpath, w), w, "Base", "TOK", EVM, bal)
    assert _labels(_get(client), "base " + EVM) == ["Desktop Hot", "Alpha", "Plazm"]


def test_one_percent_floor_drops_dust(client, dbpath, monkeypatch):
    _wallets(monkeypatch, wallet_a="Main", wallet_b="Dust", wallet_c="Edge")
    _positions(monkeypatch, (("base", EVM), "TOK", 100.0))
    _tok(dbpath, _run(dbpath, "wallet_a"), "wallet_a", "Base", "TOK", EVM, 98.0)
    _tok(dbpath, _run(dbpath, "wallet_b"), "wallet_b", "Base", "TOK", EVM, 0.99)
    _tok(dbpath, _run(dbpath, "wallet_c"), "wallet_c", "Base", "TOK", EVM, 1.0)    # exactly 1% counts
    assert _labels(_get(client), "base " + EVM) == ["Main", "Edge"]


def test_not_found_when_no_wallet_holds_it(client, dbpath, monkeypatch):
    _wallets(monkeypatch, wallet_a="Main")
    _positions(monkeypatch, (("solana", SOL_A), "TOK", 5.0), (("base", EVM), "OTH", 5.0))
    s = _run(dbpath, "wallet_a")
    _tok(dbpath, s, "wallet_a", "Solana", "TOK", SOL_B, 5.0)      # differs only by case
    _tok(dbpath, s, "wallet_a", "Ethereum", "OTH", EVM, 5.0)      # right address, wrong chain
    _tok(dbpath, s, "wallet_a", "Base", "OTH", EVM, 0.0)          # zero balance
    body = _get(client)
    assert body["positions"]["solana " + SOL_A] == {"status": "not_found", "wallets": []}
    assert body["positions"]["base " + EVM] == {"status": "not_found", "wallets": []}


def test_native_coin_by_symbol_and_symbol_keyed_position(client, dbpath, monkeypatch):
    _wallets(monkeypatch, wallet_a="Desktop Hot", wallet_b="Cold BTC")
    _positions(monkeypatch, (("base", EVM), "ETH", 1.0), ("BTC", "BTC", 0.5))
    a = _run(dbpath, "wallet_a")
    _tok(dbpath, a, "wallet_a", "Base", "ETH", "", 1.0)
    _tok(dbpath, a, "wallet_a", "Ethereum", "ETH", "", 3.0)        # other chain: not this position
    _tok(dbpath, a, "wallet_a", "Base", "BTC", EVM_OTHER, 9.0)     # a BTC-named token with a contract
    _tok(dbpath, _run(dbpath, "wallet_b"), "wallet_b", "Bitcoin", "BTC", None, 0.5)
    body = _get(client)
    assert body["positions"]["base " + EVM]["wallets"][0]["units"] == 1.0
    assert _labels(body, "base " + EVM) == ["Desktop Hot"]
    assert _labels(body, "BTC") == ["Cold BTC"]


def test_symbol_keyed_position_not_found_is_left_out_unless_native(client, dbpath, monkeypatch):
    """A symbol-keyed position can only match native coins, so 'not found' would be untrue for a token with a
    contract (its wallet row has one): it is left out, and the page shows nothing for it. A native coin
    (BTC on an exchange, say) does read 'not found'."""
    _wallets(monkeypatch, wallet_a="Main")
    _positions(monkeypatch, ("USDC", "USDC", 50.0), ("BTC", "BTC", 0.2), (("base", EVM), "TOK", 5.0))
    _tok(dbpath, _run(dbpath, "wallet_a"), "wallet_a", "Base", "USDC", EVM_OTHER, 50.0)
    body = _get(client)
    assert "USDC" not in body["positions"]
    assert body["positions"]["BTC"] == {"status": "not_found", "wallets": []}
    assert body["positions"]["base " + EVM]["status"] == "not_found"


def test_staked_tao_counts_toward_the_wallet(client, dbpath, monkeypatch):
    _wallets(monkeypatch, wallet_t="Alpha Chasers")
    _positions(monkeypatch, ("TAO", "TAO", 10.0))
    s = _run(dbpath, "wallet_t")
    _tok(dbpath, s, "wallet_t", "Bittensor", "TAO", "", 0.05)
    _tok(dbpath, s, "wallet_t", "Bittensor", "TAO root", "", 9.0)
    _tok(dbpath, s, "wallet_t", "Bittensor", "SN64 alpha", "", 500.0)
    wallets = _get(client)["positions"]["TAO"]["wallets"]
    assert [(w["label"], w["units"]) for w in wallets] == [("Alpha Chasers", 9.05)]


def test_robinhood_custom_token_row_is_found(client, dbpath, monkeypatch):
    _wallets(monkeypatch, wallet_a="MaxFi CB RM")
    _positions(monkeypatch, (("robinhood", EVM), "RUN", 20.0))
    _tok(dbpath, _run(dbpath, "wallet_a"), "wallet_a", "Robinhood Chain", "RUN", EVM, 20.0)
    assert _labels(_get(client), "robinhood " + EVM) == ["MaxFi CB RM"]


def test_units_from_several_rows_in_one_wallet_add_up(client, dbpath, monkeypatch):
    _wallets(monkeypatch, wallet_a="Main")
    _positions(monkeypatch, ("ETH", "ETH", 4.0))
    a = _run(dbpath, "wallet_a")
    _tok(dbpath, a, "wallet_a", "Base", "ETH", "", 1.0)
    _tok(dbpath, a, "wallet_a", "Arbitrum", "ETH", "", 2.5)
    assert _get(client)["positions"]["ETH"]["wallets"] == [
        {"label": "Main", "units": 3.5, "as_of": "2026-10-10T12:00:00+00:00", "stale": False}]


def test_hidden_and_removed_wallets_are_left_out(client, dbpath, monkeypatch):
    _wallets(monkeypatch, wallet_a="Main", wallet_h="hidden")
    _positions(monkeypatch, (("base", EVM), "TOK", 10.0))
    for w in ("wallet_a", "wallet_h", "wallet_gone"):
        _tok(dbpath, _run(dbpath, w), w, "Base", "TOK", EVM, 10.0)
    assert _labels(_get(client), "base " + EVM) == ["Main"]


def test_latest_completed_run_per_wallet_only(client, dbpath, monkeypatch):
    _wallets(monkeypatch, wallet_a="Main", wallet_b="Other")
    _positions(monkeypatch, (("base", EVM), "TOK", 10.0))
    old = _run(dbpath, "wallet_a", hours=-2)
    _tok(dbpath, old, "wallet_a", "Base", "TOK", EVM, 10.0)        # moved out since
    _run(dbpath, "wallet_a", hours=0)                              # latest completed: does not hold it
    failed = _run(dbpath, "wallet_b", hours=1, status="failed")
    _tok(dbpath, failed, "wallet_b", "Base", "TOK", EVM, 10.0)     # failed runs never count
    body = _get(client)
    assert body["positions"]["base " + EVM] == {"status": "not_found", "wallets": []}
    assert body["as_of"] == "2026-10-10T12:00:00+00:00"


@pytest.mark.parametrize("newer", ["failed", "pending", "partial"])
def test_falls_back_to_the_latest_completed_run(client, dbpath, monkeypatch, newer):
    _wallets(monkeypatch, wallet_a="Main")
    _positions(monkeypatch, (("base", EVM), "TOK", 10.0))
    _tok(dbpath, _run(dbpath, "wallet_a", hours=-2), "wallet_a", "Base", "TOK", EVM, 10.0)
    _run(dbpath, "wallet_a", hours=0, status=newer)                  # holds nothing, never read
    body = _get(client)
    assert body["positions"]["base " + EVM]["wallets"][0]["as_of"] == "2026-10-10T10:00:00+00:00"
    assert body["as_of"] == "2026-10-10T10:00:00+00:00"


def test_stale_wallet_snapshot_is_flagged(client, dbpath, monkeypatch):
    _wallets(monkeypatch, wallet_a="Fresh", wallet_b="Old")
    _positions(monkeypatch, (("base", EVM), "TOK", 10.0))
    _tok(dbpath, _run(dbpath, "wallet_a", hours=0), "wallet_a", "Base", "TOK", EVM, 6.0)
    _tok(dbpath, _run(dbpath, "wallet_b", hours=-25), "wallet_b", "Base", "TOK", EVM, 4.0)
    body = _get(client)
    wallets = body["positions"]["base " + EVM]["wallets"]
    assert [(w["label"], w["stale"]) for w in wallets] == [("Fresh", False), ("Old", True)]
    assert wallets[1]["as_of"] == "2026-10-09T11:00:00+00:00"
    assert body["stale"] is True
    assert body["old_wallets"] == [{"label": "Old", "as_of": "2026-10-09T11:00:00+00:00"}]


def test_everything_old_is_stale_against_now(client, dbpath, monkeypatch):
    """Staleness is measured against the current time, not only against the newest snapshot."""
    _wallets(monkeypatch, wallet_a="Main")
    _positions(monkeypatch, (("base", EVM), "TOK", 10.0), (("base", EVM_OTHER), "OTH", 1.0))
    _tok(dbpath, _run(dbpath, "wallet_a", hours=-30), "wallet_a", "Base", "TOK", EVM, 10.0)
    body = _get(client)
    assert body["stale"] is True
    assert body["positions"]["base " + EVM]["wallets"][0]["stale"] is True
    assert body["positions"]["base " + EVM_OTHER]["status"] == "not_found"


def test_fresh_wallets_are_not_old_and_unread_wallets_come_first(client, dbpath, monkeypatch):
    _wallets(monkeypatch, wallet_a="Fresh", wallet_b="Old", wallet_c="Older", wallet_new="New")
    _positions(monkeypatch, (("base", EVM), "TOK", 10.0))
    _run(dbpath, "wallet_a", hours=0)
    _run(dbpath, "wallet_b", hours=-30)
    _run(dbpath, "wallet_c", hours=-50)
    _run(dbpath, "wallet_new", hours=0, status="failed")            # no completed run yet
    body = _get(client)
    assert body["old_wallets"] == [{"label": "New", "as_of": None},
                                   {"label": "Older", "as_of": "2026-10-08T10:00:00+00:00"},
                                   {"label": "Old", "as_of": "2026-10-09T06:00:00+00:00"}]
    assert body["stale"] is True
    assert body["positions"]["base " + EVM]["status"] == "not_found"


def test_nothing_old_when_every_wallet_is_fresh(client, dbpath, monkeypatch):
    _wallets(monkeypatch, wallet_a="Main", wallet_b="Other")
    _positions(monkeypatch, (("base", EVM), "TOK", 10.0))
    _run(dbpath, "wallet_a", hours=0)
    _run(dbpath, "wallet_b", hours=-20)
    body = _get(client)
    assert body["stale"] is False and body["old_wallets"] == []


def test_missing_label_never_shows_the_wallet(client, dbpath, monkeypatch):
    _wallets(monkeypatch, wallet_a=None)
    _positions(monkeypatch, (("base", EVM), "TOK", 10.0))
    _tok(dbpath, _run(dbpath, "wallet_a"), "wallet_a", "Base", "TOK", EVM, 10.0)
    body = _get(client)
    assert _labels(body, "base " + EVM) == ["Unlabelled wallet"]
    assert "wallet_a" not in json.dumps(body)


@pytest.mark.parametrize("setup", ["no_wallets", "no_snapshot", "only_failed"])
def test_unknown_when_nothing_was_read(client, dbpath, monkeypatch, setup):
    _positions(monkeypatch, (("base", EVM), "TOK", 10.0))
    if setup == "no_wallets":
        _wallets(monkeypatch)
        _tok(dbpath, _run(dbpath, "wallet_a"), "wallet_a", "Base", "TOK", EVM, 10.0)
    else:
        _wallets(monkeypatch, wallet_a="Main")
        if setup == "only_failed":
            _tok(dbpath, _run(dbpath, "wallet_a", status="failed"), "wallet_a", "Base", "TOK", EVM, 10.0)
    assert _get(client) == {"as_of": None, "stale": False, "old_wallets": [], "positions": {}}


def test_read_only_and_no_network(client, dbpath, monkeypatch):
    import requests

    def _no_network(*a, **k):
        raise AssertionError("no network call here")

    monkeypatch.setattr(requests.Session, "request", _no_network)
    _wallets(monkeypatch, wallet_a="Main")
    _positions(monkeypatch, (("base", EVM), "TOK", 10.0))
    _tok(dbpath, _run(dbpath, "wallet_a"), "wallet_a", "Base", "TOK", EVM, 10.0)

    def counts():
        conn = sqlite3.connect(dbpath)
        try:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
        finally:
            conn.close()

    before = counts()
    assert _get(client)["positions"]["base " + EVM]["status"] == "found"
    assert counts() == before
