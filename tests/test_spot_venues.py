"""Landing 86: "Held at" per spot position (spot_position_venues,
GET / PUT /api/spot/venues, and the entries in GET /api/spot/locations).

Display only: the venues name where a position's asset sits when no tracked
wallet shows it. These tests pin the rules (replace-the-set writes, validation,
the choices list, the merge into the wallet line) and that nothing that counts
money reads the table. Real init_db() on a tmp_path SQLite file; wallets are
made-up strings, never real addresses; no network."""
import ast
import os
import sqlite3
import textwrap
import inspect
from datetime import datetime, timedelta, timezone

import pytest

import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

T0 = datetime(2026, 11, 1, 12, 0, 0)
NOW = (T0 + timedelta(hours=1)).replace(tzinfo=timezone.utc)
RM = "0x" + "a1" * 20
RABBY = "0x" + "b2" * 20
TXF = "0x" + "e5" * 20
HIDDEN = "0x" + "c3" * 20
DESK = "desk_wallet"
ARB_ETH = "0x" + "ab" * 20


@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    return path


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(wp, "_spot_location_now", lambda: NOW)
    monkeypatch.setattr(wp, "_spawn_hl_accounts_refresh_thread", lambda wallets: None)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _config(monkeypatch, **extra):
    cfg = {RM: {"label": "Hyperliquid RM"}, RABBY: {"label": "Rabby (Hyperliquid)"},
           TXF: {"label": "TxFlow Main", "perp_venues": ["txflow"]},
           HIDDEN: {"label": "Old", "hidden": True}, DESK: {"label": "Desktop Hot"}}
    cfg.update(extra)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: cfg)
    return cfg


def _sql(path, query, args=()):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, args).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def _tx(path, symbol, chain="", addr="", side="buy", units=2.0):
    _sql(path, "INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, platform, notes, "
               "chain, contract_address) VALUES ('11/1/2026', ?, ?, ?, 100, 100, '', '', ?, ?)",
         (symbol, side, units, chain, addr))


def _venues(path, key=None):
    q = "SELECT position_key, venue, set_at FROM spot_position_venues"
    rows = _sql(path, q + (" WHERE position_key = ?" if key else "") + " ORDER BY id", (key,) if key else ())
    return [(r["venue"], r["set_at"]) for r in rows]


def _put(client, body):
    return client.put("/api/spot/venues", json=body)


ETH_KEY = "arbitrum " + ARB_ETH


# -- the table -----------------------------------------------------------------

def test_init_db_adds_only_the_venues_table_and_is_repeatable(tmp_path, monkeypatch):
    path = str(tmp_path / "up.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    _tx(path, "ETH", "arbitrum", ARB_ETH)
    _sql(path, "INSERT INTO spot_position_books (position_key, book, updated_at) VALUES ('ETH', 'long_term', 'x')")
    names_before = {r["name"] for r in _sql(path, "SELECT name FROM sqlite_master")}
    _sql(path, "DROP TABLE spot_position_venues")                      # a database from before this landing
    assert "spot_position_venues" not in {r["name"] for r in _sql(path, "SELECT name FROM sqlite_master")}
    portfolio_db.init_db()
    portfolio_db.init_db()
    assert {r["name"] for r in _sql(path, "SELECT name FROM sqlite_master")} == names_before
    assert [tuple(r) for r in _sql(path, "SELECT symbol, units FROM spot_transactions")] == [("ETH", 2.0)]
    assert [tuple(r) for r in _sql(path, "SELECT position_key, book FROM spot_position_books")] == [("ETH", "long_term")]
    assert _sql(path, "PRAGMA integrity_check")[0][0] == "ok"
    assert [r["name"] for r in _sql(path, "PRAGMA table_info(spot_position_venues)")] == ["id", "position_key", "venue", "set_at"]


def test_the_table_keeps_one_row_per_position_and_name_ignoring_case(dbpath):
    _sql(dbpath, "INSERT INTO spot_position_venues (position_key, venue, set_at) VALUES ('ETH', 'Hyperliquid', 'a')")
    with pytest.raises(sqlite3.IntegrityError):
        _sql(dbpath, "INSERT INTO spot_position_venues (position_key, venue, set_at) VALUES ('ETH', 'hyperliquid', 'b')")
    _sql(dbpath, "INSERT INTO spot_position_venues (position_key, venue, set_at) VALUES ('BTC', 'Hyperliquid', 'c')")


# -- validation ----------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    (["Hyperliquid"], ["Hyperliquid"]),
    ([], []),
    (["  Variational  ", "Some   Place"], ["Variational", "Some Place"]),
    (["Tx" + chr(9) + "Flow"], ["Tx Flow"]),
    (["Hyperliquid", "hyperliquid", "HYPERLIQUID", "TxFlow"], ["Hyperliquid", "TxFlow"]),
    (["x" * 40], ["x" * 40]),
    ([chr(0x4E16) + chr(0x754C)], [chr(0x4E16) + chr(0x754C)]),
    (["e" + chr(0x301), chr(0xE9)], [chr(0xE9)]),                      # the same letter typed two ways is one name
    (["v%d" % i for i in range(8)], ["v%d" % i for i in range(8)]),
])
def test_clean_venues_accepts(raw, expected):
    assert wp._spot_clean_venues(raw) == (expected, None)


@pytest.mark.parametrize("raw", [
    "Hyperliquid", None, {"a": 1}, [1], [None], [["x"]], [""], ["   "], ["x" * 41],
    ["bad" + chr(0) + "name"], ["bad" + chr(7)], ["bad" + chr(127)], ["v%d" % i for i in range(9)],
    [chr(0x200B)], ["zero" + chr(0x200B) + "width"], [chr(0xFEFF) + "bom"],
])
def test_clean_venues_refuses(raw):
    out, err = wp._spot_clean_venues(raw)
    assert out is None and isinstance(err, str) and err


# -- PUT -----------------------------------------------------------------------

def test_put_by_position_key_replaces_the_set_and_keeps_dates_of_venues_that_stay(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _tx(dbpath, "ETH", "arbitrum", ARB_ETH)
    r = _put(client, {"position_key": ETH_KEY, "venues": ["Hyperliquid", "TxFlow"]})
    assert r.status_code == 200
    body = r.get_json()
    assert body["position_key"] == ETH_KEY and body["attached"] is True
    assert [v["venue"] for v in body["venues"]] == ["Hyperliquid", "TxFlow"]
    first = dict(_venues(dbpath, ETH_KEY))
    assert set(first) == {"Hyperliquid", "TxFlow"}
    _sql(dbpath, "UPDATE spot_position_venues SET set_at = '2026-10-01T00:00:00+00:00' WHERE venue = 'TxFlow'")
    r = _put(client, {"position_key": ETH_KEY, "venues": ["TxFlow", "Variational"]})
    assert r.status_code == 200
    after = dict(_venues(dbpath, ETH_KEY))
    assert set(after) == {"TxFlow", "Variational"}                      # Hyperliquid removed
    assert after["TxFlow"] == "2026-10-01T00:00:00+00:00"               # kept its date
    assert after["Variational"] > "2026-10-02"                          # new: now


def test_put_empty_list_clears_only_that_position(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _tx(dbpath, "ETH", "arbitrum", ARB_ETH)
    _tx(dbpath, "BTC")
    _put(client, {"position_key": ETH_KEY, "venues": ["Hyperliquid"]})
    _put(client, {"position_key": "BTC", "venues": ["Variational"]})
    r = _put(client, {"position_key": ETH_KEY, "venues": []})
    assert r.status_code == 200 and r.get_json()["venues"] == []
    assert _venues(dbpath, ETH_KEY) == []
    assert [v for v, _ in _venues(dbpath, "BTC")] == ["Variational"]


def test_put_a_new_spelling_of_a_kept_venue_changes_the_text_not_the_date(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _tx(dbpath, "ETH")
    _put(client, {"position_key": "ETH", "venues": ["variational"]})
    _sql(dbpath, "UPDATE spot_position_venues SET set_at = '2026-10-01T00:00:00+00:00'")
    r = _put(client, {"position_key": "ETH", "venues": ["Variational"]})
    assert r.status_code == 200
    assert _venues(dbpath, "ETH") == [("Variational", "2026-10-01T00:00:00+00:00")]


def test_put_by_symbol_chain_and_contract_names_the_same_position_as_fifo(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _tx(dbpath, "ETH", "arbitrum", ARB_ETH)
    _tx(dbpath, "BTC")
    upper = "0x" + "AB" * 20                                            # the page may send any case; the key is as stored
    r = _put(client, {"symbol": "eth", "chain": "arbitrum", "contract_address": upper, "venues": ["Hyperliquid"]})
    assert r.status_code == 200 and r.get_json()["position_key"] == ETH_KEY
    r = _put(client, {"symbol": "btc", "chain": "", "contract_address": "", "venues": ["TxFlow"]})
    assert r.status_code == 200 and r.get_json()["position_key"] == "BTC"
    with sqlite3.connect(dbpath) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT symbol, chain, contract_address FROM spot_transactions").fetchall():
            assert wp._stringify_spot_position_key(wp._spot_position_key(row)) in {ETH_KEY, "BTC"}


@pytest.mark.parametrize("body, fragment", [
    ({"venues": ["x"]}, "position_key, or symbol"),
    ({"position_key": "", "venues": ["x"]}, "position_key is required"),
    ({"position_key": 5, "venues": ["x"]}, "position_key is required"),
    ({"position_key": "NOPE", "venues": ["x"]}, "unknown position"),
    ({"symbol": "ETH", "chain": "arbitrum", "venues": ["x"]}, "together"),
    ({"symbol": "ETH", "chain": "mars", "contract_address": ARB_ETH, "venues": ["x"]}, "Unknown chain"),
    ({"symbol": "ZZZ", "venues": ["x"]}, "unknown position"),
    ({"position_key": "ETH", "venues": "x"}, "must be a list"),
    ({"position_key": "ETH"}, "must be a list"),
    ({"position_key": "ETH", "venues": [""]}, "empty"),
    ({"position_key": "ETH", "venues": ["x" * 41]}, "at most 40"),
])
def test_put_refuses_bad_input_and_writes_nothing(client, dbpath, monkeypatch, body, fragment):
    _config(monkeypatch)
    _tx(dbpath, "ETH")
    _put(client, {"position_key": "ETH", "venues": ["Keep"]})
    r = _put(client, body)
    assert r.status_code == 400 and fragment in r.get_json()["error"]
    assert _venues(dbpath) == [("Keep", _venues(dbpath)[0][1])]


def test_put_with_nine_venues_is_refused_whole(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _tx(dbpath, "ETH")
    r = _put(client, {"position_key": "ETH", "venues": ["v%d" % i for i in range(9)]})
    assert r.status_code == 400 and "at most 8" in r.get_json()["error"]
    assert _venues(dbpath) == []


def test_put_changes_no_transaction_and_no_fifo_position(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _tx(dbpath, "ETH", "arbitrum", ARB_ETH)
    _tx(dbpath, "ETH", "arbitrum", ARB_ETH, side="sell", units=0.5)
    conn = portfolio_db.get_connection()
    before_rows = [tuple(r) for r in conn.execute("SELECT * FROM spot_transactions ORDER BY id").fetchall()]
    before_fifo = wp._calculate_spot_fifo(conn)
    conn.close()
    _put(client, {"position_key": ETH_KEY, "venues": ["Hyperliquid", "TxFlow"]})
    _put(client, {"position_key": ETH_KEY, "venues": []})
    conn = portfolio_db.get_connection()
    assert [tuple(r) for r in conn.execute("SELECT * FROM spot_transactions ORDER BY id").fetchall()] == before_rows
    assert wp._calculate_spot_fifo(conn) == before_fifo
    conn.close()


def test_the_routes_need_a_login(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    anon = wp.app.test_client()
    assert anon.get("/api/spot/venues").status_code == 401
    assert anon.put("/api/spot/venues", json={"position_key": "ETH", "venues": []}).status_code == 401


# -- GET ----------------------------------------------------------------------

def test_options_list_fixed_names_wallet_apps_then_names_used_before(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _tx(dbpath, "ETH")
    _sql(dbpath, "INSERT INTO hl_sync_state (wallet, first_seen_at) VALUES (?, 'x')", (RM,))
    _sql(dbpath, "INSERT INTO hl_sync_state (wallet, first_seen_at) VALUES (?, 'x')", (HIDDEN,))
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_CACHE", {"fetched_at": "2026-11-01T12:00:00+00:00", "error": None,
                                                    "wallets": {RABBY: {"spot": []}, "0x" + "dd" * 20: {"spot": []}}})
    _sql(dbpath, "INSERT INTO spot_position_venues (position_key, venue, set_at) VALUES ('ETH', 'Zeta DEX', 'a')")
    _sql(dbpath, "INSERT INTO spot_position_venues (position_key, venue, set_at) VALUES ('ETH', 'hyperliquid', 'a')")
    r = client.get("/api/spot/venues")
    assert r.status_code == 200
    options = r.get_json()["options"]
    assert options == ["Hyperliquid", "TxFlow", "Variational", "Hyperliquid RM App", "Rabby (Hyperliquid) App",
                       "TxFlow Main App", "Zeta DEX"]
    assert RM not in str(options) and RABBY not in str(options) and TXF not in str(options)


def test_options_come_from_stored_history_when_the_live_cache_is_cold(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _sql(dbpath, "INSERT INTO hl_sync_state (wallet, first_seen_at) VALUES (?, 'x')", (RM,))
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    assert "Hyperliquid RM App" in client.get("/api/spot/venues").get_json()["options"]


def test_get_lists_saved_venues_with_attached_flags(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _tx(dbpath, "ETH")
    _put(client, {"position_key": "ETH", "venues": ["Hyperliquid"]})
    _sql(dbpath, "INSERT INTO spot_position_venues (position_key, venue, set_at) VALUES ('GONE', 'TxFlow', 'z')")
    venues = client.get("/api/spot/venues").get_json()["venues"]
    by_key = {v["position_key"]: v for v in venues}
    assert by_key["ETH"]["attached"] is True and by_key["ETH"]["venue"] == "Hyperliquid"
    assert by_key["GONE"]["attached"] is False


# -- the Spot wallet line ------------------------------------------------------

def _snapshot(path):
    conn = sqlite3.connect(path)
    cur = conn.execute("INSERT INTO portfolio_snapshots (user_id, timestamp, wallet, status) VALUES (1, ?, ?, 'completed')",
                       (T0.isoformat(), DESK))
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def _positions(monkeypatch, *specs):
    out = {}
    for key, symbol, units in specs:
        chain, addr = key if isinstance(key, tuple) else ("", "")
        out[key] = {"symbol": symbol, "chain": chain, "contract_address": addr, "units": units,
                    "position_key": wp._stringify_spot_position_key(key)}
    monkeypatch.setattr(wp, "_calculate_spot_fifo", lambda conn: (out, {}))


def _locations(client):
    r = client.get("/api/spot/locations")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _held(path, key, *names):
    for n in names:
        _sql(path, "INSERT INTO spot_position_venues (position_key, venue, set_at) VALUES (?, ?, '2026-11-01T11:00:00+00:00')", (key, n))


def test_a_venue_replaces_not_in_a_tracked_wallet_for_a_chain_and_contract_position(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _positions(monkeypatch, (("arbitrum", ARB_ETH), "ETH", 3.0))
    _snapshot(dbpath)
    assert _locations(client)["positions"][ETH_KEY] == {"status": "not_found", "wallets": []}
    _held(dbpath, ETH_KEY, "Hyperliquid RM App")
    entry = _locations(client)["positions"][ETH_KEY]
    assert entry == {"status": "found", "wallets": [{"label": "Hyperliquid RM App", "units": None,
                                                     "as_of": "2026-11-01T11:00:00+00:00", "stale": False, "manual": True}]}


def test_venues_follow_the_automatic_entries_and_repeat_nothing(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _positions(monkeypatch, ("ETH", "ETH", 4.0))
    s = _snapshot(dbpath)
    _sql(dbpath, "INSERT INTO token_snapshots (snapshot_id, user_id, timestamp, wallet, chain, symbol, token_address, balance, "
                 "price_usd, value_usd) VALUES (?, 1, ?, ?, 'Ethereum', 'ETH', '', 1.5, 1, 1.5)", (s, T0.isoformat(), DESK))
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_CACHE", {"fetched_at": (NOW - timedelta(minutes=5)).isoformat(), "error": None, "wallets": {
        RM: {"spot": [{"coin": "UETH", "amount": 2.5, "price": 1.0, "value": 2.5}]}}})
    _held(dbpath, "ETH", "Zeta", "hyperliquid rm app", "Alpha")
    wallets = _locations(client)["positions"]["ETH"]["wallets"]
    assert [(w["label"], w.get("manual", False)) for w in wallets] == [
        ("Hyperliquid RM App", False), ("Desktop Hot", False), ("Alpha", True), ("Zeta", True)]
    assert [w["units"] for w in wallets] == [2.5, 1.5, None, None]       # the automatic entry won the repeated name


def test_a_symbol_only_position_with_a_venue_is_listed_even_if_not_native(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _positions(monkeypatch, ("ZZZ", "ZZZ", 5.0), ("QQQ", "QQQ", 5.0))
    _snapshot(dbpath)
    _held(dbpath, "ZZZ", "Variational")
    positions = _locations(client)["positions"]
    assert positions["ZZZ"]["status"] == "found" and positions["ZZZ"]["wallets"][0]["label"] == "Variational"
    assert "QQQ" not in positions                                       # unknown, as before


def test_a_failure_in_the_held_at_part_leaves_the_line_as_it_was(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _positions(monkeypatch, (("arbitrum", ARB_ETH), "ETH", 3.0))
    _snapshot(dbpath)
    _held(dbpath, ETH_KEY, "Hyperliquid")

    def boom(conn):
        raise sqlite3.OperationalError("no such table")
    monkeypatch.setattr(wp, "_spot_venues_by_key", boom)
    assert _locations(client)["positions"][ETH_KEY] == {"status": "not_found", "wallets": []}


def test_without_any_venue_the_route_answers_exactly_as_before(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _positions(monkeypatch, (("arbitrum", ARB_ETH), "ETH", 3.0))
    _snapshot(dbpath)
    body = _locations(client)
    assert body["positions"][ETH_KEY] == {"status": "not_found", "wallets": []}
    assert set(body) == {"as_of", "stale", "old_wallets", "positions"}


# -- the invariant: display only -------------------------------------------------

WATCHED_TABLE = "spot_position_venues"
WATCHED_NAMES = {"_spot_venues_by_key", "_spot_clean_venues", "_spot_venue_options", "SPOT_VENUE_FIXED",
                 "SPOT_VENUE_MAX_PER_POSITION", "SPOT_VENUE_NAME_MAX"}
ALLOWED_TABLE_USERS = {
    ("src/storage/portfolio_db.py", "init_db"),
    ("web_portfolio.py", "_spot_venues_by_key"),
    ("web_portfolio.py", "_spot_venue_options"),
    ("web_portfolio.py", "api_spot_venues_put"),
}
ALLOWED_NAME_USERS = {
    ("web_portfolio.py", "<module>"): {"SPOT_VENUE_FIXED", "SPOT_VENUE_MAX_PER_POSITION", "SPOT_VENUE_NAME_MAX"},
    ("web_portfolio.py", "_spot_clean_venues"): {"SPOT_VENUE_MAX_PER_POSITION", "SPOT_VENUE_NAME_MAX"},
    ("web_portfolio.py", "_spot_venue_options"): {"SPOT_VENUE_FIXED", "_spot_clean_venues"},
    ("web_portfolio.py", "api_spot_venues_list"): {"_spot_venue_options", "_spot_venues_by_key", "SPOT_VENUE_FIXED"},
    ("web_portfolio.py", "api_spot_venues_put"): {"_spot_clean_venues", "_spot_venues_by_key"},
    ("web_portfolio.py", "api_spot_locations"): {"_spot_venues_by_key"},
}


def _scan(path, root):
    rel = os.path.relpath(path, root)
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    tables, names = set(), {}
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
                  and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}

    def visit(node, scope):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else scope
            if (isinstance(child, ast.Constant) and isinstance(child.value, str) and WATCHED_TABLE in child.value
                    and id(child) not in docstrings):
                tables.add((rel, scope))
            ident = child.id if isinstance(child, ast.Name) else child.attr if isinstance(child, ast.Attribute) else None
            if ident in WATCHED_NAMES:
                names.setdefault((rel, scope), set()).add(ident)
            visit(child, inner)
    visit(tree, "<module>")
    return tables, names


def test_only_the_venue_code_touches_the_venues_table_and_helpers():
    """If the snapshot writer, the total's inputs, Dry powder, the advisors or
    anything else that counts money starts to read the table or the helpers,
    this fails. Every non-test .py file is parsed."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tables, names = set(), {}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("tests", ".git", "node_modules", "__pycache__", "data")]
        for name in files:
            if name.endswith(".py"):
                t, n = _scan(os.path.join(base, name), root)
                tables |= t
                names.update(n)
    assert tables == ALLOWED_TABLE_USERS, tables
    assert names == ALLOWED_NAME_USERS, names
    for fn in (wp.get_portfolio_data, wp._compose_total_for_snapshot, wp.api_portfolio_total,
               wp._portfolio_total_db_inputs, wp._spot_stable_rows, wp.api_spot_stablecoins, wp.api_spot_change_24h,
               wp._calculate_spot_fifo):
        src = inspect.getsource(fn)
        assert WATCHED_TABLE not in src and "api/spot/venues" not in src, fn.__name__


# -- review fixes (Landing 86) -------------------------------------------------------

def _other_tables_digest(path):
    conn = sqlite3.connect(path)
    try:
        out = {}
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall():
            if name != "spot_position_venues":
                out[name] = repr(conn.execute('SELECT * FROM "%s" ORDER BY 1' % name).fetchall())
        return out
    finally:
        conn.close()


def test_put_touches_no_table_but_the_venues_table(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _tx(dbpath, "ETH", "arbitrum", ARB_ETH)
    _sql(dbpath, "INSERT INTO spot_position_books (position_key, book, updated_at) VALUES (?, 'long_term', 'x')", (ETH_KEY,))
    before = _other_tables_digest(dbpath)
    assert _put(client, {"position_key": ETH_KEY, "venues": ["Hyperliquid", "TxFlow"]}).status_code == 200
    assert _put(client, {"position_key": ETH_KEY, "venues": ["TxFlow"], "merge": True}).status_code == 200
    assert _put(client, {"position_key": ETH_KEY, "venues": []}).status_code == 200
    assert _other_tables_digest(dbpath) == before


def test_one_name_on_two_positions_is_separate_for_each(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _tx(dbpath, "ETH")
    _tx(dbpath, "BTC")
    _put(client, {"position_key": "ETH", "venues": ["Hyperliquid", "TxFlow"]})
    _put(client, {"position_key": "BTC", "venues": ["Hyperliquid"]})
    _put(client, {"position_key": "ETH", "venues": ["TxFlow"]})                       # ETH drops Hyperliquid ...
    assert [v for v, _ in _venues(dbpath, "BTC")] == ["Hyperliquid"]                  # ... BTC keeps it
    _put(client, {"position_key": "ETH", "venues": ["Hyperliquid"], "merge": True})
    _put(client, {"position_key": "BTC", "venues": []})
    assert sorted(v for v, _ in _venues(dbpath, "ETH")) == ["Hyperliquid", "TxFlow"]


def test_merge_adds_to_the_saved_set_and_removes_nothing(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _tx(dbpath, "ETH")
    _put(client, {"position_key": "ETH", "venues": ["Hyperliquid", "TxFlow"]})
    _sql(dbpath, "UPDATE spot_position_venues SET set_at = '2026-10-01T00:00:00+00:00' WHERE venue = 'TxFlow'")
    r = _put(client, {"position_key": "ETH", "venues": ["variational", "TXFLOW"], "merge": True})
    assert r.status_code == 200
    got = dict(_venues(dbpath, "ETH"))
    assert set(got) == {"Hyperliquid", "TxFlow", "variational"}                       # TxFlow kept its spelling
    assert got["TxFlow"] == "2026-10-01T00:00:00+00:00"
    assert [v["venue"] for v in r.get_json()["venues"]] == ["TxFlow", "Hyperliquid", "variational"]      # oldest set first
    r = _put(client, {"position_key": "ETH", "venues": [], "merge": True})            # nothing to add: nothing changes
    assert r.status_code == 200 and {v for v, _ in _venues(dbpath, "ETH")} == {"Hyperliquid", "TxFlow", "variational"}


def test_merge_that_would_pass_eight_is_refused_whole(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _tx(dbpath, "ETH")
    _put(client, {"position_key": "ETH", "venues": ["v%d" % i for i in range(8)]})
    r = _put(client, {"position_key": "ETH", "venues": ["one more"], "merge": True})
    assert r.status_code == 400 and "at most 8" in r.get_json()["error"]
    assert len(_venues(dbpath, "ETH")) == 8
    r = _put(client, {"position_key": "ETH", "venues": ["V1"], "merge": True})        # already there (ignoring case): fine
    assert r.status_code == 200 and len(_venues(dbpath, "ETH")) == 8


def test_merge_only_counts_when_it_is_exactly_true(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _tx(dbpath, "ETH")
    _put(client, {"position_key": "ETH", "venues": ["Hyperliquid"]})
    for flag in ("true", 1, "yes", None):
        _put(client, {"position_key": "ETH", "venues": ["TxFlow"], "merge": flag})
        assert [v for v, _ in _venues(dbpath, "ETH")] == ["TxFlow"]                    # replaced, not merged
        _put(client, {"position_key": "ETH", "venues": ["Hyperliquid"]})


def test_two_puts_at_once_leave_one_whole_set_and_no_error(client, dbpath, monkeypatch):
    """The read of the saved set and the writes are one transaction, so two PUTs
    for one position cannot interleave: both answer 200, and what is saved is
    exactly one of the two requested sets."""
    import threading
    _config(monkeypatch)
    _tx(dbpath, "ETH")
    gate = threading.Barrier(2, timeout=10)
    real = wp._spot_all_position_keys

    def keys_then_wait(conn):
        out = real(conn)
        gate.wait()                                   # both requests are past validation before either writes
        return out
    monkeypatch.setattr(wp, "_spot_all_position_keys", keys_then_wait)
    sets = [["Hyperliquid"], ["hyperliquid", "TxFlow"]]
    for _ in range(4):
        _sql(dbpath, "DELETE FROM spot_position_venues")
        out = [None, None]

        def go(i):
            c = wp.app.test_client()
            with c.session_transaction() as sess:
                sess["authenticated"] = True
            out[i] = c.put("/api/spot/venues", json={"position_key": "ETH", "venues": sets[i]}).status_code
        threads = [threading.Thread(target=go, args=(i,)) for i in range(2)]
        [t.start() for t in threads]
        [t.join(30) for t in threads]
        assert out == [200, 200], out
        saved = sorted(v.casefold() for v, _ in _venues(dbpath, "ETH"))
        assert saved in (["hyperliquid"], ["hyperliquid", "txflow"]), saved
        gate.reset()


def test_a_failure_answers_with_the_error_type_only(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _tx(dbpath, "ETH")

    def boom(conn):
        raise RuntimeError("secret " + RM)
    monkeypatch.setattr(wp, "_spot_venues_by_key", boom)
    for r in (_put(client, {"position_key": "ETH", "venues": ["Hyperliquid"]}), client.get("/api/spot/venues")):
        assert r.status_code == 500 and r.get_json() == {"error": "RuntimeError"}
        assert RM not in r.get_data(as_text=True)


def test_options_skip_unlabelled_wallets_and_names_the_put_would_refuse(client, dbpath, monkeypatch):
    long_label = "L" * 38
    cfg = _config(monkeypatch)
    cfg["0x" + "f6" * 20] = {"label": long_label, "perp_venues": ["txflow"]}        # label + " App" is 41: too long
    cfg["0x" + "f7" * 20] = {"perp_venues": ["txflow"]}                              # no label: never "TxFlow ...e5e5"
    cfg["0x" + "f8" * 20] = {"label": "  Spaced   Out  ", "perp_venues": ["txflow"]}
    for w in ("0x" + "f6" * 20, "0x" + "f7" * 20, "0x" + "f8" * 20):
        _sql(dbpath, "INSERT INTO hl_sync_state (wallet, first_seen_at) VALUES (?, 'x')", (w,))
    options = client.get("/api/spot/venues").get_json()["options"]
    assert "Spaced Out App" in options
    assert long_label + " App" not in options
    assert not any("..." in o or chr(0x2026) in o for o in options)
    assert not any("nlabelled" in o for o in options)                               # no wallet without a label is offered
    assert all(wp._spot_clean_venues([o])[0] == [o] for o in options)                # every offered name is one the PUT accepts


def test_an_odd_wallet_label_does_not_take_the_saved_venues_down_with_it(client, dbpath, monkeypatch):
    cfg = _config(monkeypatch)
    cfg[TXF] = {"label": 7, "perp_venues": ["txflow"]}
    _tx(dbpath, "ETH")
    _put(client, {"position_key": "ETH", "venues": ["Hyperliquid"]})
    r = client.get("/api/spot/venues")
    assert r.status_code == 200
    body = r.get_json()
    assert [v["venue"] for v in body["venues"]] == ["Hyperliquid"] and body["options"][:3] == ["Hyperliquid", "TxFlow", "Variational"]


def test_a_failure_building_the_choices_still_returns_the_saved_venues(client, dbpath, monkeypatch):
    _config(monkeypatch)
    _tx(dbpath, "ETH")
    _put(client, {"position_key": "ETH", "venues": ["Hyperliquid"]})

    def boom(conn, config):
        raise TypeError("odd wallet config")
    monkeypatch.setattr(wp, "_spot_venue_options", boom)
    r = client.get("/api/spot/venues")
    assert r.status_code == 200
    body = r.get_json()
    assert body["options"] == ["Hyperliquid", "TxFlow", "Variational"]
    assert [v["venue"] for v in body["venues"]] == ["Hyperliquid"]
