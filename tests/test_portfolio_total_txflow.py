"""TxFlow in the complete total (Landing 38; portfolio_total ruling 10,
definition_version 3).

Covers portfolio_total.compose_total's TxFlow part, web_portfolio's
_txflow_state_for_total (counted wallets, labels, no addresses) and
_txflow_state_for_snapshot (freshened at snapshot time), the
/api/portfolio/total wiring, the snapshot writer's txflow_usd column and
partial status, and the column's upgrade path in init_db.

No network: TxFlow runs only through a stubbed wp._txflow_fetch_states. The
recorded answer in tests/fixtures/txflow is read-only. web_portfolio spawns a
background scheduler on non-__main__ import; threading.Thread.start is
neutralized during import (established pattern).
"""
import copy
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import maxfi_schema
import portfolio_total as pt
import portfolio_total_chart as ptc
import src.engines.snapshot_service as ss
import src.storage.portfolio_db as portfolio_db

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "txflow", "clearinghouseState.json")
TA = "0x" + "a" * 40
TB = "0x" + "b" * 40
TH = "0x" + "c" * 40          # hidden in Settings
TE = "0x" + "e" * 40          # only in the TXFLOW_WALLETS variable
NOW = datetime(2026, 10, 14, 16, 0, tzinfo=timezone.utc)
ACCOUNT = 539.2062279084      # the fixture's marginSummary.accountValue


def _fixture():
    with open(FIX) as f:
        return json.load(f)


def _state(account="1000", plus=None, positions=()):
    st = {"assetPositions": [{"position": {"coin": c, "szi": s}, "tpsl": []} for c, s in positions],
          "marginSummary": {"accountValue": account}}
    if plus is not None:
        st["accountValuePlusWithdrawHold"] = plus
    return st


def _tx(*wallets, fetched_at="2026-10-14T15:58:00+00:00", error=None):
    return {"fetched_at": fetched_at, "error": error, "wallets": list(wallets)}


def _w(label="TxFlow", state=None, fetched_at="2026-10-14T15:58:00+00:00", stale=False, error=None):
    return {"label": label, "state": state, "fetched_at": fetched_at, "stale": stale, "error": error}


def _portfolio():
    return {"tokens": [{"symbol": "ETH", "value_usd": 2000.0, "wallet": TA},
                       {"symbol": "USDC", "value_usd": 300.0, "wallet": TA}],
            "lp_positions": [], "aave_positions": [], "gmx_positions": [], "staking_positions": [],
            "total_value": 2300.0, "wallet_labels": {TA: "Hyperliquid RM"}, "fetched_at": "2026-10-14T15:50:00"}


HL_EMPTY = {"fetched_at": "2026-10-14T15:59:00+00:00", "wallets": {}, "error": None}


def _compose(txflow_state=None, **kw):
    kwargs = {} if txflow_state is None else {"txflow_state": txflow_state}
    kwargs.update(kw)
    return pt.compose_total(_portfolio(), [], set(), True, {}, HL_EMPTY, NOW, **kwargs)


def _comp(result, key="txflow"):
    return next((c for c in result["components"] if c["key"] == key), None)


# ── compose_total: the TxFlow part ─────────────────────────────────────────

def test_no_txflow_state_is_todays_output():
    base = pt.compose_total(_portfolio(), [], set(), True, {}, HL_EMPTY, NOW)
    assert _compose(None) == base
    assert _comp(base) is None and "txflow" not in base["as_of"]


def test_counted_from_the_recorded_answer():
    r = _compose(_tx(_w(state=_fixture())))
    c = _comp(r)
    assert c["counted"] is True and c["value_usd"] == pytest.approx(ACCOUNT)
    assert c["label"] == "TxFlow" and c["warnings"] == []
    assert c["as_of"] == "2026-10-14T15:58:00+00:00" and r["as_of"]["txflow"] == "2026-10-14T15:58:00+00:00"
    (row,) = c["detail"]["wallets"]
    assert row["account_value"] == pytest.approx(ACCOUNT) and row["withdraw_hold"] == pytest.approx(0.0)
    assert row["open_positions"] == 1 and row["counted"] is True and row["stale"] is False
    assert (c["detail"]["unread"], c["detail"]["expected"]) == (0, 1)
    assert r["total_usd"] == pytest.approx(2300.0 + ACCOUNT)
    keys = [x["key"] for x in r["components"]]
    assert keys.index("txflow") == keys.index("hyperliquid") + 1


def test_loading_is_not_counted():
    r = _compose(_tx(_w(state=_fixture()), fetched_at=None, error="every wallet failed: TxFlow: ConnectionError: x"))
    c = _comp(r)
    assert c["counted"] is False and c["value_usd"] == 0.0 and c["detail"]["wallets"] == []
    assert c["warnings"] == ["TxFlow loading", "last TxFlow refresh failed: every wallet failed: TxFlow: ConnectionError: x"]
    assert r["total_usd"] == pytest.approx(2300.0)
    assert {"component": "txflow", "warning": "TxFlow loading"} in r["warnings"]


def test_unread_wallet_and_missing_account_value_are_not_counted():
    no_value = {"assetPositions": [], "marginSummary": {"accountValue": "n/a"}}
    r = _compose(_tx(_w("Desk", state=_state("250.5")), _w("Second", state=None), _w("Third", state=no_value)))
    c = _comp(r)
    assert c["counted"] is True and c["value_usd"] == pytest.approx(250.5)
    assert c["detail"]["unread"] == 2 and c["detail"]["expected"] == 3
    assert c["warnings"] == ["Second: no TxFlow reading yet — not counted",
                             "Third: no account value in TxFlow's answer — not counted"]
    assert [w["counted"] for w in c["detail"]["wallets"]] == [True, False, False]


def test_withdraw_hold_reported_not_counted_and_warned_when_not_zero():
    r = _compose(_tx(_w("Desk", state=_state("1000", plus="1499.99")), _w("Other", state=_state("10", plus="10.004")),
                     _w("Third", state=_state("20", plus="20.01")), _w("Fourth", state=_state("30", plus="30"))))
    c = _comp(r)
    assert c["value_usd"] == pytest.approx(1060.0)
    assert [w["withdraw_hold"] for w in c["detail"]["wallets"]] == [
        pytest.approx(499.99), pytest.approx(0.004), pytest.approx(0.01), pytest.approx(0.0)]
    assert c["warnings"] == ["Desk: $499.99 held for a pending withdrawal — not counted",
                             "Third: $0.01 held for a pending withdrawal — not counted"]   # under a cent: rounding


def test_negative_withdraw_hold_is_warned_not_counted():
    c = _comp(_compose(_tx(_w("Desk", state=_state("1000", plus="400")))))
    assert c["value_usd"] == pytest.approx(1000.0)
    assert c["detail"]["wallets"][0]["withdraw_hold"] == pytest.approx(-600.0)
    assert c["warnings"] == ["Desk: TxFlow reports a withdrawal hold of -$600.00 (inconsistent figure; "
                             "account value counted as is)"]


def test_vault_equity_reported_not_counted_and_warned_when_not_zero():
    with_vault = dict(_state("1000"), vaultEquity="250.5")
    zero_vault = dict(_state("20"), vaultEquity="0.0")
    neg_vault = dict(_state("100"), vaultEquity="-3")
    c = _comp(_compose(_tx(_w("Desk", state=with_vault), _w("Other", state=zero_vault), _w("Neg", state=neg_vault))))
    assert c["value_usd"] == pytest.approx(1120.0)
    assert [w["vault_equity"] for w in c["detail"]["wallets"]] == [
        pytest.approx(250.5), pytest.approx(0.0), pytest.approx(-3.0)]
    assert c["warnings"] == ["Desk: $250.50 vault equity reported by TxFlow — not counted",
                             "Neg: -$3.00 vault equity reported by TxFlow — not counted"]
    (row,) = _comp(_compose(_tx(_w(state=_fixture()))))["detail"]["wallets"]
    assert row["vault_equity"] == 0.0                                  # the recorded answer's "0.0"


def test_stale_wallet_counted_flagged_and_as_of_is_oldest():
    r = _compose(_tx(_w("Desk", state=_state("100"), fetched_at="2026-10-14T15:58:00+00:00"),
                     _w("Old", state=_state("50"), fetched_at="2026-10-14T13:00:00+00:00", stale=True,
                        error="ConnectionError: down")))
    c = _comp(r)
    assert c["counted"] and c["value_usd"] == pytest.approx(150.0)
    assert c["as_of"] == "2026-10-14T13:00:00+00:00"
    assert c["warnings"] == ["Old: last refresh failed (ConnectionError: down) — showing last good values"]


def test_open_positions_count_skips_flat_entries():
    st = _state("100", positions=[("ETH-USDC", "1.5"), ("BTC-USDC", "0"), ("SOL-USDC", "-2")])
    st["assetPositions"].append("odd")
    (row,) = _comp(_compose(_tx(_w(state=st))))["detail"]["wallets"]
    assert row["open_positions"] == 2


def test_component_carries_no_address():
    r = _compose(_tx(_w("Hyperliquid RM", state=_fixture())))
    assert "0x" not in json.dumps(_comp(r))


# ── _txflow_state_for_total ────────────────────────────────────────────────

CONFIG = {TA: {"label": "Hyperliquid RM", "perp_venues": ["txflow"]},
          TB: {"perp_venues": ["txflow"]},
          TH: {"label": "Hidden", "hidden": True, "perp_venues": ["txflow"]},
          "0x" + "f" * 40: {"label": "Not TxFlow"}}


def test_state_counts_visible_txflow_wallets_with_labels(monkeypatch):
    monkeypatch.setenv("TXFLOW_WALLETS", TE)
    cache = {"fetched_at": "2026-10-14T15:58:00+00:00", "error": None,
             "wallets": {TA.upper().replace("0X", "0x"): {"state": _fixture(), "fetched_at": "t1"},
                         TH: {"state": _state("9999"), "fetched_at": "t1"},
                         TE: {"state": _state("5"), "fetched_at": "t2", "stale": True,
                              "error": f"ConnectionError: {TE} refused"}}}
    st = wp._txflow_state_for_total(cache, CONFIG)
    assert st["fetched_at"] == "2026-10-14T15:58:00+00:00" and st["error"] is None
    assert [w["label"] for w in st["wallets"]] == ["Hyperliquid RM", "TxFlow …" + TB[-4:], "TxFlow …" + TE[-4:]]
    assert st["wallets"][0]["state"] == _fixture()                     # case-insensitive cache key
    assert st["wallets"][1]["state"] is None                           # never read
    assert st["wallets"][2]["stale"] is True
    assert st["wallets"][2]["error"] == "ConnectionError: TxFlow …" + TE[-4:] + " refused"
    assert "0x" not in json.dumps(st)


def test_state_none_without_a_counted_txflow_wallet(monkeypatch):
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    assert wp._txflow_state_for_total({"fetched_at": "x", "wallets": {}}, {}) is None
    only_hidden = {TH: CONFIG[TH]}
    assert wp._txflow_state_for_total({"fetched_at": "x", "wallets": {TH: {"state": _state()}}}, only_hidden) is None


def test_state_single_wallet_label_and_scrubbed_cache_error(monkeypatch):
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    config = {TB: {"perp_venues": ["txflow"]}}
    st = wp._txflow_state_for_total({"fetched_at": None, "wallets": {},
                                     "error": f"every wallet failed: {TB}: ConnectionError: x; {TA}: y"}, config)
    assert st["wallets"] == [{"label": "TxFlow", "state": None, "fetched_at": None, "stale": False, "error": None}]
    assert st["error"] == "every wallet failed: TxFlow: ConnectionError: x; a wallet: y"


# ── _txflow_state_for_snapshot ─────────────────────────────────────────────

@pytest.fixture
def tx_env(monkeypatch):
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    monkeypatch.setattr(wp, "_TXFLOW_IN_FLIGHT", False)
    monkeypatch.setattr(wp, "_TXFLOW_LAST_KICK", {"at": None})
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {TA: {"label": "Hyperliquid RM", "perp_venues": ["txflow"]}})
    fetches = []

    def fetch(wallets, post=None):
        fetches.append(list(wallets))
        # assetPositions empty: the worker's funding readings write nothing.
        return {"wallets": {a: {"state": _state("777"), "fetched_at": NOW.isoformat()} for a in wallets}, "errors": {}}
    monkeypatch.setattr(wp, "_txflow_fetch_states", fetch)
    return fetches


def _no_sleep(_):
    raise AssertionError("must not sleep")


def test_snapshot_fresh_cache_no_fetch(tx_env, monkeypatch):
    fresh = {"fetched_at": (NOW - timedelta(minutes=5)).isoformat(), "wallets": {TA: {"state": _state()}}, "error": None}
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", fresh)
    got = wp._txflow_state_for_snapshot(NOW, sleep=_no_sleep)
    assert tx_env == [] and got == fresh and got is not fresh


def test_snapshot_fresh_cache_missing_a_new_wallet_runs_worker(tx_env, monkeypatch):
    # TA was ticked in Settings after the last refresh: the cache is fresh but has no entry for it.
    fresh = {"fetched_at": (NOW - timedelta(minutes=5)).isoformat(), "error": None,
             "wallets": {TB: {"state": _state("3"), "fetched_at": (NOW - timedelta(minutes=5)).isoformat()}}}
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", fresh)
    got = wp._txflow_state_for_snapshot(NOW, sleep=_no_sleep)
    assert tx_env == [[TA]]
    assert got["wallets"][TA]["state"]["marginSummary"]["accountValue"] == "777"
    assert wp._TXFLOW_IN_FLIGHT is False


def test_snapshot_permanently_failing_wallet_one_refresh_per_run(tx_env, monkeypatch):
    calls = []

    def failing(wallets, post=None):
        calls.append(list(wallets))
        return {"wallets": {}, "errors": {a: "ValueError: unexpected clearinghouseState" for a in wallets}}
    monkeypatch.setattr(wp, "_txflow_fetch_states", failing)
    for run in range(3):
        got = wp._txflow_state_for_snapshot(NOW + timedelta(hours=2 * run), sleep=_no_sleep)
        assert got["fetched_at"] is None and got["wallets"] == {}
        assert wp._TXFLOW_IN_FLIGHT is False
    assert calls == [[TA]] * 3                                   # exactly one refresh per snapshot run


def test_conftest_guard_blocks_txflow_calls():
    # tests/conftest.py: no TXFLOW_WALLETS from the environment and no real TxFlow call in any test.
    assert "TXFLOW_WALLETS" not in os.environ
    with pytest.raises(RuntimeError, match="TxFlow disabled in tests"):
        wp._txflow_post({"type": "clearinghouseState", "user": TA})
    wp._spawn_txflow_refresh_thread([TA])
    assert wp._TXFLOW_IN_FLIGHT is False and wp._TXFLOW_CACHE == {"fetched_at": None, "wallets": {}, "error": None}


@pytest.mark.parametrize("fetched_at", [None, (NOW - timedelta(minutes=16)).isoformat()])
def test_snapshot_stale_or_empty_runs_worker_inline(tx_env, monkeypatch, fetched_at):
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": fetched_at, "wallets": {}, "error": None})
    monkeypatch.setattr(wp, "_TXFLOW_LAST_KICK", {"at": NOW - timedelta(minutes=1)})       # cooldown ignored
    got = wp._txflow_state_for_snapshot(NOW, sleep=_no_sleep)
    assert tx_env == [[TA]]
    assert got["fetched_at"] and got["fetched_at"] != fetched_at
    assert got["wallets"][TA]["state"]["marginSummary"]["accountValue"] == "777"
    assert wp._TXFLOW_IN_FLIGHT is False and wp._TXFLOW_LAST_KICK["at"] == NOW


def test_snapshot_waits_for_in_flight_refresh(tx_env, monkeypatch):
    monkeypatch.setattr(wp, "_TXFLOW_IN_FLIGHT", True)
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:                        # the other refresh lands
            wp._TXFLOW_CACHE.update({"fetched_at": NOW.isoformat(), "wallets": {TA: {"state": _state("1")}}})
            wp._TXFLOW_IN_FLIGHT = False
    got = wp._txflow_state_for_snapshot(NOW, sleep=sleep)
    assert tx_env == [] and sleeps == [wp.HL_SNAPSHOT_POLL_SECONDS] * 2
    assert got["fetched_at"] == NOW.isoformat() and TA in got["wallets"]


def test_snapshot_gives_up_after_wait_limit(tx_env, monkeypatch):
    monkeypatch.setattr(wp, "_TXFLOW_IN_FLIGHT", True)
    sleeps = []
    got = wp._txflow_state_for_snapshot(NOW, sleep=sleeps.append)
    assert tx_env == [] and sum(sleeps) == wp.HL_SNAPSHOT_WAIT_SECONDS
    assert got == {"fetched_at": None, "wallets": {}, "error": None}
    assert wp._TXFLOW_IN_FLIGHT is True                                       # someone else's refresh


def test_snapshot_no_txflow_wallets_no_fetch(tx_env, monkeypatch):
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {TA: {"label": "Rabby"}})
    got = wp._txflow_state_for_snapshot(NOW, sleep=_no_sleep)
    assert tx_env == [] and got["fetched_at"] is None and wp._TXFLOW_IN_FLIGHT is False


def test_snapshot_wallet_list_failure_falls_through(tx_env, monkeypatch):
    def boom(config=None):
        raise RuntimeError("config unreadable")
    monkeypatch.setattr(wp, "_txflow_wallets", boom)
    got = wp._txflow_state_for_snapshot(NOW, sleep=_no_sleep)
    assert tx_env == [] and got == {"fetched_at": None, "wallets": {}, "error": None}
    assert wp._TXFLOW_IN_FLIGHT is False


# ── /api/portfolio/total and the snapshot composer ─────────────────────────

@pytest.fixture
def mem_db(monkeypatch):
    uri = f"file:portfolio_total_txflow_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    maxfi_schema.ensure_maxfi_tables(keepalive)
    keepalive.commit()

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    yield keepalive
    keepalive.close()


@pytest.fixture
def client(monkeypatch, mem_db, tx_env):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    monkeypatch.setattr(wp, "_portfolio_cache", _portfolio())
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_CACHE", copy.deepcopy(HL_EMPTY) | {"fetched_at": NOW.isoformat()})
    for name in ("_maybe_kick_hl_accounts_refresh", "_maybe_kick_dexfi_bonds_refresh", "_maybe_kick_tao_refresh"):
        monkeypatch.setattr(wp, name, lambda now_utc: False)
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def test_route_kicks_txflow_and_counts_it(client, monkeypatch):
    kicks = []
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", lambda now_utc: kicks.append(now_utc) or False)
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": datetime.now(timezone.utc).isoformat(), "error": None,
                                              "wallets": {TA: {"state": _fixture(), "fetched_at": "2026-10-14T15:58:00+00:00"}}})
    body = client.get("/api/portfolio/total").get_json()
    assert len(kicks) == 1
    c = _comp(body)
    assert c["counted"] and c["value_usd"] == pytest.approx(ACCOUNT)
    assert [w["label"] for w in c["detail"]["wallets"]] == ["Hyperliquid RM"]
    assert body["total_usd"] == pytest.approx(2300.0 + ACCOUNT)
    assert "0x" not in json.dumps(c)


def test_route_kick_failure_still_answers(client, monkeypatch):
    def boom(now_utc):
        raise RuntimeError("kick")
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", boom)
    body = client.get("/api/portfolio/total").get_json()
    c = _comp(body)
    assert body["status"] == "ok" and c["counted"] is False and c["warnings"] == ["TxFlow loading"]


def test_snapshot_composer_matches_route(client, monkeypatch):
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", lambda now_utc: False)
    monkeypatch.setattr(wp, "_dexfi_bonds_state_for_snapshot", lambda now_utc: wp._dexfi_bonds_cache_copy())
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": datetime.now(timezone.utc).isoformat(), "error": None,
                                              "wallets": {TA: {"state": _fixture(), "fetched_at": "2026-10-14T15:58:00+00:00"}}})
    route = client.get("/api/portfolio/total").get_json()
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_CACHE", {"fetched_at": datetime.now(timezone.utc).isoformat(),
                                                   "wallets": {}, "error": None})
    snap = wp._compose_total_for_snapshot(_portfolio())
    assert snap["total_usd"] == pytest.approx(route["total_usd"]) == pytest.approx(2300.0 + ACCOUNT)
    assert [(c["key"], c["value_usd"], c["counted"]) for c in snap["components"]] == [
        (c["key"], c["value_usd"], c["counted"]) for c in route["components"]]
    assert _comp(snap)["counted"] and _comp(snap)["value_usd"] == pytest.approx(ACCOUNT)


# ── the snapshot writer ────────────────────────────────────────────────────

@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    return path


def _rows(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM portfolio_total_snapshots ORDER BY id")]
    conn.close()
    return rows


def _snap_portfolio():
    return {"tokens": [{"wallet": TA, "chain": "base", "symbol": "ETH", "balance": 1.0, "price_usd": 2000.0,
                        "value_usd": 2000.0}], "lp_positions": [], "gmx_positions": [], "aave_positions": [],
            "api_failures": []}


def _result(tx_state):
    return _compose(tx_state) if tx_state is not None else _compose(None)


def _write(dbpath, tx_state):
    ss.take_portfolio_snapshot(lambda **_: _snap_portfolio(), [TA], compose_total_fn=lambda p: _result(tx_state))
    (row,) = _rows(dbpath)
    return row


def test_writer_counted_txflow(dbpath):
    row = _write(dbpath, _tx(_w(state=_fixture())))
    assert ss.PORTFOLIO_TOTAL_DEFINITION_VERSION == 3 and row["definition_version"] == 3
    assert row["status"] == "completed" and row["txflow_usd"] == pytest.approx(ACCOUNT)
    assert row["total_usd"] == pytest.approx(2300.0 + ACCOUNT) and row["hl_counted"] == 1


def test_writer_without_txflow_part(dbpath):
    row = _write(dbpath, None)
    assert row["status"] == "completed" and row["txflow_usd"] is None


def test_writer_txflow_loading_is_partial_with_null_value(dbpath, capsys):
    row = _write(dbpath, _tx(_w(state=_fixture()), fetched_at=None))
    assert row["status"] == "partial" and row["txflow_usd"] is None
    assert row["total_usd"] == pytest.approx(2300.0)
    assert "[Snapshot] complete total partial: TxFlow not read" in capsys.readouterr().out


def test_writer_unread_wallet_is_partial(dbpath):
    row = _write(dbpath, _tx(_w("Desk", state=_state("100")), _w("Second", state=None)))
    assert row["status"] == "partial" and row["txflow_usd"] == pytest.approx(100.0)


def test_writer_failed_composer_keeps_failed(dbpath):
    def boom(p):
        raise RuntimeError("x")
    ss.take_portfolio_snapshot(lambda **_: _snap_portfolio(), [TA], compose_total_fn=boom)
    (row,) = _rows(dbpath)
    assert row["status"] == "failed" and row["txflow_usd"] is None


def test_chart_leaves_out_a_run_without_txflow_and_marks_the_seam():
    def row(ts, v, total, status="completed"):
        return {"id": ts, "timestamp": ts, "status": status, "definition_version": v, "total_usd": total,
                "snapshot_total_usd": 1000.0, "hyperliquid_usd": 0.0, "hl_counted": 1,
                "wallets_total": 1, "wallets_completed": 1}
    out = ptc.build_chart([row("2026-10-14T10:00:00", 2, 1000.0), row("2026-10-14T12:00:00", 3, 900.0, "partial"),
                           row("2026-10-14T14:00:00", 3, 1539.2)], [])
    assert [p["v"] for p in out["points"]] == [2, 3] and out["excluded"]["not_usable"] == 1
    assert out["seams"] == [{"t": "2026-10-14T14:00:00.000Z", "from_v": 2, "to_v": 3}]
    assert [p["basis0"] for p in out["points"]] == [1000.0, 1000.0]


# ── the column's upgrade path ──────────────────────────────────────────────

@pytest.mark.skipif(sqlite3.sqlite_version_info < (3, 35), reason="DROP COLUMN needs SQLite 3.35+")
def test_init_db_adds_txflow_column_to_an_existing_table(dbpath):
    conn = sqlite3.connect(dbpath)
    conn.execute("ALTER TABLE portfolio_total_snapshots DROP COLUMN txflow_usd")   # a database from before Landing 38
    conn.execute("INSERT INTO portfolio_total_snapshots (timestamp, status, definition_version, total_usd) "
                 "VALUES ('2026-10-14T10:00:00', 'completed', 2, 1000.0)")
    conn.commit()
    assert "txflow_usd" not in [r[1] for r in conn.execute("PRAGMA table_info(portfolio_total_snapshots)")]
    conn.close()
    portfolio_db.init_db()
    portfolio_db.init_db()                                                         # idempotent
    conn = sqlite3.connect(dbpath)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(portfolio_total_snapshots)")]
    old = conn.execute("SELECT definition_version, total_usd, txflow_usd FROM portfolio_total_snapshots").fetchall()
    conn.close()
    assert cols == ["id"] + list(portfolio_db.PORTFOLIO_TOTAL_SNAPSHOT_COLUMNS)
    assert cols[-1] == "txflow_usd" and old == [(2, 1000.0, None)]
