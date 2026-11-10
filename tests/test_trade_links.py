"""Landing 96: links from a trade to Glenn's trading-journal posts (trade_links,
GET / POST /api/trading/trades/<id>/links, PUT / DELETE .../links/<link id>,
GET /api/trading/trade-links/counts).

Links only: https URLs, Discord message links marked kind 'discord', Discord
attachment links refused. These tests pin the validation, the routes, that no
existing payload changes, and the schema upgrade on a database main built.
Real init_db() on a tmp_path SQLite file; wallets are made-up strings, never
real addresses; no network."""
import importlib.util
import os
import sqlite3
import subprocess
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import hl_trades
import src.storage.portfolio_db as portfolio_db

W_RM = "0x" + "a" * 40
H = 3600000
DAY = 24 * H
T_SYN = 1789862400000                                       # 2026-09-20T00:00Z
MSG = "https://discord.com/channels/111111111111111111/222222222222222222/333333333333333333"
UNKNOWN = "t" + "0" * 20
_BUILT = {}
MAIN_BEFORE = "a7997ad7c6bb302070307721b3bf76498fd62d40"   # main at Landing 95, before trade_links


def _never(*a, **k):
    raise AssertionError("no venue call here")


def _cycles(n=2):
    """n closed Hyperliquid ETH perp cycles (the test_trades_unified synthetic shape)."""
    fills, orders = [], []
    for i in range(n):
        t0 = T_SYN + i * DAY
        fills.append({"coin": "ETH", "side": "B", "sz": "1", "px": "100", "startPosition": "0", "time": t0,
                      "tid": 2 * i + 1, "closedPnl": "0", "fee": "0", "dir": "Open Long", "feeToken": "USDC"})
        fills.append({"coin": "ETH", "side": "A", "sz": "1", "px": "110", "startPosition": "1", "time": t0 + H,
                      "tid": 2 * i + 2, "closedPnl": "10", "fee": "0", "dir": "Close Long", "feeToken": "USDC"})
        orders.append({"order": {"coin": "ETH", "side": "A", "oid": 900 + i, "timestamp": t0, "isTrigger": True,
                                 "reduceOnly": True, "orderType": "Stop Market", "triggerPx": "95", "children": []},
                       "status": "open", "statusTimestamp": t0})
    cycles = hl_trades.build_cycles(W_RM, fills, [], orders)["cycles"]
    for c in cycles:
        c["wallet_label"] = "Hyperliquid RM"
    return {"cycles": cycles, "by_wallet": {}, "sync_rows": []}


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.setattr(wp, "_HL_TRADES_IN_FLIGHT", False)
    monkeypatch.setattr(wp, "_HL_TRADES_LAST_KICK", {"at": None})
    monkeypatch.setattr(wp, "_spawn_hl_trades_refresh_thread", lambda: None)
    monkeypatch.setattr(wp, "_hl_post", _never)
    monkeypatch.setattr(wp, "_txflow_post", _never)
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": None, "wallets": {}})
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {W_RM: {"label": "Hyperliquid RM"}})
    built = _cycles()
    monkeypatch.setattr(wp, "_hl_trade_cycles", lambda conn: built)
    conn = portfolio_db.get_connection()
    _BUILT["cycles"] = built
    yield conn
    conn.close()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(wp, "_maybe_kick_hl_trades_refresh", lambda now, force=False: False)
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", lambda now: False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", lambda now: False)
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


@pytest.fixture
def ids(db):
    perp = [wp._trade_id(c["trade_key"]) for c in _BUILT["cycles"]["cycles"]]
    cur = db.execute("INSERT INTO spot_trade_log (ticker, direction, source, entry_price, stop_price, qty, entered_at) "
                     "VALUES ('SOL', 'long', 'manual', 100.0, 95.0, 2.0, '2026-09-20T10:00:00+00:00')")
    db.commit()
    return {"perp": perp[0], "perp2": perp[1], "manual": wp._trade_id("manual|%d" % cur.lastrowid)}


def links_url(tid):
    return f"/api/trading/trades/{tid}/links"


def add(client, tid, url=MSG, **kw):
    return client.post(links_url(tid), json={"url": url, **kw})


def listed(client, tid):
    r = client.get(links_url(tid))
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()["links"]


def counts(client):
    r = client.get("/api/trading/trade-links/counts")
    assert r.status_code == 200
    return r.get_json()["counts"]


# -- validation -----------------------------------------------------------

@pytest.mark.parametrize("url,kind", [
    (MSG, "discord"),
    ("https://ptb.discord.com/channels/1/2/3", "discord"),
    ("https://canary.discord.com/channels/1/2/3", "discord"),
    ("https://discordapp.com/channels/1/2/3", "discord"),
    ("https://discord.com/channels/@me/2/3", "discord"),
    ("https://DISCORD.com/channels/1/2/3", "discord"),
    ("https://discord.com/channels/1/2", "link"),                 # a channel, not a message
    ("https://discord.com/invite/abc", "link"),
    ("https://discord.com/channels/1/2/3/4", "link"),
    ("https://discord.com/channels/x/2/3", "link"),
    ("https://example.com/chart?id=1#top", "link"),
    ("https://notdiscord.com/channels/1/2/3", "link"),
])
def test_url_kinds(url, kind):
    got, k, err = wp._trade_link_url(url)
    assert err is None and k == kind


def test_url_host_lowercased_rest_kept():
    got, kind, err = wp._trade_link_url("  https://Example.COM:8443/Path/A?Q=B#Frag  ")
    assert err is None and got == "https://example.com:8443/Path/A?Q=B#Frag" and kind == "link"
    got, _, _ = wp._trade_link_url("HTTPS://Discord.com/channels/1/2/3")
    assert got == "HTTPS://discord.com/channels/1/2/3"


@pytest.mark.parametrize("url", [
    "http://discord.com/channels/1/2/3", "javascript:alert(1)", "data:text/html,hi", "discord://channels/1/2/3",
    "ftp://example.com/a", "example.com/a", "https://", "https:///path", "https:example.com",
    "https://exa mple.com/", "https://example.com/a b", "https://example.com/a\tb", "https://example.com/a\x00b",
    "https://example.com/a\x7fb", "https://example.com/a\u0085b", "https://example.com/a\u00a0b",
    "https://user:pw@example.com/", "https://discord.com@evil.example/", "https://example.com:notaport/",
    "", "   ", None, 5, ["https://example.com"],
    "https://example.com/" + "a" * 481,
])
def test_url_refused(url):
    got, kind, err = wp._trade_link_url(url)
    assert got is None and kind is None and err


def test_url_length_limit():
    ok = "https://example.com/" + "a" * 480
    assert len(ok) == 500 and wp._trade_link_url(ok)[2] is None
    assert wp._trade_link_url(ok + "a")[2]


@pytest.mark.parametrize("url", [
    "https://cdn.discordapp.com/attachments/1/2/chart.png",
    "https://media.discordapp.net/attachments/1/2/chart.png?width=400",
    "https://images-ext-1.discordapp.net/external/abc/https/example.com/x.png",
    "https://images-ext-2.discordapp.net/x",
    "https://CDN.DiscordApp.com/attachments/1/2/c.png",
])
def test_discord_attachments_refused_with_hint(url):
    got, kind, err = wp._trade_link_url(url)
    assert got is None and err == wp.TRADE_LINK_ATTACHMENT_HINT and "Copy Message Link" in err


def test_phase_and_caption():
    assert wp._trade_link_phase(None) == (None, None)
    for p in ("entry", "management", "exit"):
        assert wp._trade_link_phase(p) == (p, None)
    for bad in ("Entry", "stop", "", 1, True):
        assert wp._trade_link_phase(bad)[1]
    assert wp._trade_link_caption(None) == (None, None)
    assert wp._trade_link_caption("   ") == (None, None)
    assert wp._trade_link_caption("  breakout retest  ") == ("breakout retest", None)
    assert wp._trade_link_caption("x" * 200) == ("x" * 200, None)
    assert wp._trade_link_caption("x" * 201)[1]
    assert wp._trade_link_caption(7)[1]


# -- routes ---------------------------------------------------------------

def test_create_list_and_duplicate(client, ids):
    tid = ids["perp"]
    assert listed(client, tid) == []
    r = add(client, tid, phase="entry", caption=" setup ")
    assert r.status_code == 201
    link = r.get_json()["link"]
    assert set(link) == {"id", "url", "kind", "phase", "caption", "created_at", "updated_at"}
    assert link["url"] == MSG and link["kind"] == "discord" and link["phase"] == "entry" and link["caption"] == "setup"
    r2 = add(client, tid, url="https://example.com/chart")
    assert r2.status_code == 201 and r2.get_json()["link"]["kind"] == "link" and r2.get_json()["link"]["phase"] is None
    dup = add(client, tid, url="  " + MSG + " ", phase="exit", caption="ignored")
    assert dup.status_code == 200 and dup.get_json()["link"] == link
    assert [l["url"] for l in listed(client, tid)] == [MSG, "https://example.com/chart"]


def test_same_url_on_another_trade_is_its_own_link(client, ids):
    assert add(client, ids["perp"]).status_code == 201
    assert add(client, ids["perp2"]).status_code == 201
    assert counts(client) == {ids["perp"]: 1, ids["perp2"]: 1}


def test_create_validation(client, ids):
    tid = ids["perp"]
    for body in ({}, {"url": "http://example.com"}, {"url": MSG, "phase": "later"},
                 {"url": MSG, "caption": "x" * 201}, {"url": "https://cdn.discordapp.com/attachments/1/2/a.png"}):
        r = client.post(links_url(tid), json=body)
        assert r.status_code == 400, body
    assert client.post(links_url(tid), data="not json", content_type="text/plain").status_code == 400
    r = client.post(links_url(tid), json={"url": "https://media.discordapp.net/attachments/1/2/a.png"})
    assert r.get_json()["error"] == wp.TRADE_LINK_ATTACHMENT_HINT
    assert listed(client, tid) == []


def test_limit_is_409(client, ids):
    tid = ids["perp"]
    for i in range(wp.TRADE_LINKS_MAX):
        assert add(client, tid, url=f"https://example.com/{i}").status_code == 201
    r = add(client, tid, url="https://example.com/eleven")
    assert r.status_code == 409
    assert add(client, tid, url="https://example.com/3").status_code == 200        # a duplicate still answers
    first = listed(client, tid)[0]["id"]
    assert client.delete(f"{links_url(tid)}/{first}").status_code == 200
    assert add(client, tid, url="https://example.com/eleven").status_code == 201


def test_edit(client, ids):
    tid = ids["perp"]
    link = add(client, tid, phase="entry", caption="a").get_json()["link"]
    u = f"{links_url(tid)}/{link['id']}"
    r = client.put(u, json={"phase": "management"})
    assert r.status_code == 200
    got = r.get_json()["link"]
    assert got["phase"] == "management" and got["caption"] == "a" and got["url"] == MSG
    assert got["updated_at"] >= link["updated_at"] and got["created_at"] == link["created_at"]
    got = client.put(u, json={"caption": "  ", "phase": None}).get_json()["link"]
    assert got["caption"] is None and got["phase"] is None
    assert client.put(u, json={"url": "https://example.com/x"}).status_code == 400
    assert client.put(u, json={"url": MSG, "caption": "b"}).status_code == 400
    assert client.put(u, json={}).status_code == 400
    assert client.put(u, json={"phase": "nope"}).status_code == 400
    assert client.put(u, json={"caption": "x" * 201}).status_code == 400
    assert listed(client, tid)[0]["url"] == MSG


def test_remove(client, ids, db):
    tid = ids["perp"]
    a = add(client, tid).get_json()["link"]
    b = add(client, tid, url="https://example.com/b").get_json()["link"]
    assert counts(client) == {tid: 2}
    r = client.delete(f"{links_url(tid)}/{a['id']}")
    assert r.status_code == 200 and r.get_json() == {"removed": True, "id": a["id"]}
    assert [l["id"] for l in listed(client, tid)] == [b["id"]]
    assert counts(client) == {tid: 1}
    row = db.execute("SELECT removed_at FROM trade_links WHERE id = ?", (a["id"],)).fetchone()
    assert row["removed_at"] is not None                                              # kept, not deleted
    assert client.delete(f"{links_url(tid)}/{a['id']}").status_code == 404           # already removed
    assert client.put(f"{links_url(tid)}/{a['id']}", json={"caption": "x"}).status_code == 404
    again = add(client, tid)                                                          # re-adding is a new link
    assert again.status_code == 201 and again.get_json()["link"]["id"] != a["id"]
    client.delete(f"{links_url(tid)}/{b['id']}")
    client.delete(f"{links_url(tid)}/{again.get_json()['link']['id']}")
    assert counts(client) == {}


def test_wrong_trade_and_unknown_ids(client, ids):
    link = add(client, ids["perp"]).get_json()["link"]
    other = f"{links_url(ids['perp2'])}/{link['id']}"
    assert client.put(other, json={"caption": "x"}).status_code == 404
    assert client.delete(other).status_code == 404
    assert client.delete(f"{links_url(ids['perp'])}/999999").status_code == 404
    assert len(listed(client, ids["perp"])) == 1


def test_unknown_trade_matches_the_annotation_route(client, ids):
    annotation = client.put(f"/api/trading/trades/{UNKNOWN}/annotation", json={"notes": "x"}).status_code
    assert annotation == 404
    assert client.get(links_url(UNKNOWN)).status_code == annotation
    assert add(client, UNKNOWN).status_code == annotation
    assert client.put(f"{links_url(UNKNOWN)}/1", json={"caption": "x"}).status_code == annotation
    assert client.delete(f"{links_url(UNKNOWN)}/1").status_code == annotation
    assert counts(client) == {}


def test_manual_trade_takes_links(client, ids):
    tid = ids["manual"]
    assert client.put(f"/api/trading/trades/{tid}/annotation", json={"notes": "x"}).status_code == 400
    r = add(client, tid, phase="exit")
    assert r.status_code == 201
    assert [l["phase"] for l in listed(client, tid)] == ["exit"]
    assert counts(client) == {tid: 1}


def test_counts_route(client, ids):
    assert counts(client) == {}
    add(client, ids["perp"])
    add(client, ids["perp"], url="https://example.com/1")
    add(client, ids["manual"])
    assert counts(client) == {ids["perp"]: 2, ids["manual"]: 1}


def test_routes_need_login(db, monkeypatch, ids):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    for r in (c.get(links_url(ids["perp"])), c.post(links_url(ids["perp"]), json={"url": MSG}),
              c.get("/api/trading/trade-links/counts")):
        assert r.status_code in (302, 401, 403)
    assert db.execute("SELECT COUNT(*) FROM trade_links").fetchone()[0] == 0


# -- isolation ------------------------------------------------------------

def test_links_leave_the_trades_payload_alone(client, ids):
    def trades():
        r = client.get("/api/trading/trades")
        assert r.status_code == 200
        return r.get_json()
    before = trades()
    assert trades() == before                                   # the payload is stable on its own
    add(client, ids["perp"], phase="entry", caption="c")
    add(client, ids["manual"], url="https://example.com/x")
    after = trades()
    assert after == before


def test_no_money_path_reads_the_table():
    """trade_links is named only by its own routes and helpers."""
    import inspect
    src = inspect.getsource(wp)
    users = set()
    for name, fn in vars(wp).items():
        if inspect.isfunction(fn) and getattr(fn, "__module__", "") == wp.__name__:
            try:
                body = inspect.getsource(fn)
            except (OSError, TypeError):
                continue
            if "trade_links" in body:
                users.add(name)
    assert users == {"_trade_link_active", "api_trading_trade_links", "api_trading_trade_link",
                     "api_trading_trade_link_counts"}
    assert src.count("trade_links") >= 4


# -- upgrade rehearsal ----------------------------------------------------

def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _snapshot(path):
    conn = sqlite3.connect(path)
    try:
        objs = sorted(conn.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        rows = {}
        for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"):
            rows[t] = sorted(conn.execute(f'SELECT * FROM "{t}"').fetchall(), key=repr)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    return objs, rows, integrity


def test_upgrade_rehearsal_on_mains_database(tmp_path, monkeypatch):
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        old_src = subprocess.check_output(["git", "show", MAIN_BEFORE + ":src/storage/portfolio_db.py"], cwd=repo,
                                          stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("main before Landing 96 is not in this checkout's history")
    assert b"trade_links" not in old_src
    old_file = tmp_path / "portfolio_db_main.py"
    old_file.write_bytes(old_src)
    path = str(tmp_path / "upgrade.db")
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path))
    old = _load_module(str(old_file), "portfolio_db_main_l96")
    monkeypatch.setattr(old, "get_db_path", lambda: path)
    old.init_db()
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO trade_annotations (trade_id, market, notes, created_at, updated_at) "
                 "VALUES ('t00000000000000000001', 'perp', 'kept', 'now', 'now')")
    conn.execute("INSERT INTO spot_trade_log (ticker, direction, source, entry_price, stop_price, qty, entered_at) "
                 "VALUES ('SOL', 'long', 'manual', 100.0, 95.0, 2.0, '2026-09-20T10:00:00+00:00')")
    conn.execute("INSERT INTO note_revisions (kind, ref, old_text, action, revised_at) "
                 "VALUES ('trade_notes', 't00000000000000000001', 'older', 'edit', 'now')")
    conn.commit()
    conn.close()
    before_objs, before_rows, before_ok = _snapshot(path)
    assert before_ok == "ok"

    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    first = _snapshot(path)
    portfolio_db.init_db()
    second = _snapshot(path)

    objs, rows, ok = first
    added = sorted((t, n) for t, n, _ in set(objs) - set(before_objs))
    assert added == [("index", "idx_trade_links_trade"), ("table", "trade_links")]
    assert set(before_objs) <= set(objs)                         # no table or index changed
    assert {t: r for t, r in rows.items() if t != "trade_links"} == before_rows
    assert rows["trade_links"] == []
    assert ok == "ok"
    assert second == first                                      # the second boot changes nothing
    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(trade_links)")]
    conn.close()
    assert cols == ["id", "trade_id", "url", "kind", "phase", "caption", "created_at", "updated_at", "removed_at"]
