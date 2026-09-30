"""Alpha Chasers: the pure bittensor_performance module, GET
/api/bittensor/performance (read-only, cache-only) and POST / DELETE
/api/bittensor/flows (hand-entered TAO deposits and withdrawals).

No network. Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). Only the public Substrate dev addresses are used; amounts are
the replay sample's, not a user's."""
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import bittensor_performance as bp
import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

ALICE = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
BOB = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
EVM = "0x1111111111111111111111111111111111111111"
PRICE = 303.919907109816
NOW = datetime(2026, 9, 30, 2, 0, tzinfo=timezone.utc)
TAO_TOTAL = 12.577601758
# The Taostats fixture's parts: (symbol, rao); TAO rows in rao of TAO, alpha rows in as-TAO rao.
PARTS = [("TAO", 1745899673), ("TAO reserved", 93000000), ("SN51 alpha", 2139791461), ("SN80 alpha", 2159552372),
         ("SN105 alpha", 2150880237), ("SN107 alpha", 2151182047), ("SN110 alpha", 2137295968)]


def _status(state="fresh", price=PRICE, reason=None):
    return {"state": state, "tao_amount": TAO_TOTAL, "value_usd": TAO_TOTAL * price, "price_usd": price,
            "as_of": "2026-09-30T01:29:24+00:00", "age_hours": 0.5, "reason": reason}


def _run(ts, price, alpha_only=False):
    rows = []
    for sym, rao in PARTS:
        if alpha_only and not sym.endswith("alpha"):
            continue
        value = rao / 1e9 * price
        rows.append({"timestamp": ts, "symbol": sym, "value_usd": value,
                     "price_usd": price if not sym.endswith("alpha") else value / 7.0})
    return rows


def _flow(fid, at, rao, note=None):
    return {"id": fid, "flow_at": at, "amount_rao": rao, "note": note}


# ── pure ──────────────────────────────────────────────────────────────────

def test_replay_result_vs_deposit():
    w = bp.build_wallet(ALICE, "Bittensor", _status(), [_flow(1, "2026-09-29T00:00:00+00:00", 12802160052)], [], [], NOW)
    assert w["net_deposited_tao"] == pytest.approx(12.802160052, abs=1e-12)
    assert w["result_tao"] == pytest.approx(-0.224558294, abs=1e-9)
    assert w["result_pct"] == pytest.approx(-1.7540657, abs=1e-6)
    assert w["result_usd"] == pytest.approx(-68.2477, abs=1e-3)
    assert (w["tao_now"], w["tao_usd"], w["state"]) == (TAO_TOTAL, PRICE, "fresh")


def test_series_tao_equivalent_per_run():
    rows = _run("2026-09-30T00:00:00", 310.0) + _run("2026-09-29T22:00:00", 300.0)
    series = bp.build_series(rows, [])
    assert [p["t"] for p in series] == ["2026-09-29T22:00:00+00:00", "2026-09-30T00:00:00+00:00"]
    assert all(p["tao_eq"] == pytest.approx(TAO_TOTAL, abs=1e-9) for p in series)


def test_alpha_only_run_uses_market_price_within_6h():
    rows = _run("2026-09-30T00:00:00", 300.0, alpha_only=True)
    alpha_tao = sum(rao for sym, rao in PARTS if sym.endswith("alpha")) / 1e9
    near = [(datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc), 250.0), (datetime(2026, 9, 30, 2, 0, tzinfo=timezone.utc), 300.0)]
    [point] = bp.build_series(rows, near)
    assert point["tao_eq"] == pytest.approx(alpha_tao, abs=1e-9)                  # nearest (2 h) price 300
    far = [(datetime(2026, 9, 29, 17, 0, tzinfo=timezone.utc), 300.0)]            # 7 h away
    assert bp.build_series(rows, far) == []


def test_no_flows_leaves_results_empty_but_series_present():
    w = bp.build_wallet(ALICE, "Bittensor", _status(), [], _run("2026-09-30T00:00:00", 300.0), [], NOW)
    assert (w["net_deposited_tao"], w["result_tao"], w["result_pct"], w["result_usd"]) == (None, None, None, None)
    assert len(w["series"]) == 1 and w["deposits"] == [] and w["flows"] == []


def test_unavailable_wallet_has_no_current_or_result_values():
    w = bp.build_wallet(ALICE, "Bittensor", _status("unavailable", reason="Taostats data over 24 h old"),
                        [_flow(1, "2026-09-29T00:00:00+00:00", 12802160052)], [], [], NOW)
    assert (w["tao_now"], w["usd_now"], w["result_tao"], w["result_pct"], w["result_usd"]) == (None,) * 5
    assert w["net_deposited_tao"] == pytest.approx(12.802160052) and w["reason"] == "Taostats data over 24 h old"


def test_future_flow_not_counted_but_listed():
    flows = [_flow(1, "2026-09-29T00:00:00+00:00", 10 * 10 ** 9), _flow(2, "2026-10-05T00:00:00+00:00", 5 * 10 ** 9)]
    w = bp.build_wallet(ALICE, "Bittensor", _status(), flows, [], [], NOW)
    assert w["net_deposited_tao"] == pytest.approx(10.0)
    assert [d["net_tao"] for d in w["deposits"]] == [10.0, 15.0]
    assert [f["id"] for f in w["flows"]] == [2, 1]


def test_deposit_and_withdrawal_net():
    flows = [_flow(1, "2026-09-20T00:00:00+00:00", 10 * 10 ** 9, "start"),
             _flow(2, "2026-09-25T00:00:00+00:00", -2 * 10 ** 9)]
    w = bp.build_wallet(ALICE, "Bittensor", _status(), flows, [], [], NOW)
    assert w["net_deposited_tao"] == pytest.approx(8.0)
    assert [d["net_tao"] for d in w["deposits"]] == [10.0, 8.0]
    assert [(f["id"], f["amount_tao"], f["note"]) for f in w["flows"]] == [(2, -2.0, None), (1, 10.0, "start")]


def test_compose_marks_wallet_missing_from_cache():
    out = bp.compose([ALICE, BOB], {}, {ALICE: _status()}, {}, {}, [], NOW)
    assert out["status"] == "ok" and out["as_of"] == NOW.isoformat()
    assert [w["wallet"] for w in out["wallets"]] == [ALICE, BOB]
    assert (out["wallets"][1]["state"], out["wallets"][1]["reason"]) == ("unavailable", "not in the portfolio cache")
    assert out["wallets"][1]["label"] == "Bittensor"


def test_module_is_pure():
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "bittensor_performance.py")) as f:
        src = f.read()
    for banned in ("requests", "sqlite3", "datetime.now", "flask"):
        assert banned not in src, banned


# ── routes ────────────────────────────────────────────────────────────────

@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    return path


@pytest.fixture
def client(monkeypatch, dbpath):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    config = {EVM: {"label": "Main"}, ALICE: {"label": "Alpha bot", "type": "bittensor"}}
    monkeypatch.setattr(wp, "load_wallet_config", lambda: config)
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: list(config))
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_cold_cache_and_no_bittensor_wallet(client, monkeypatch):
    monkeypatch.setattr(wp, "_portfolio_cache", None)
    assert client.get("/api/bittensor/performance").get_json() == {"status": "cache_cold"}
    monkeypatch.setattr(wp, "_portfolio_cache", {"tokens": []})
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {EVM: {"label": "Main"}})
    monkeypatch.setattr(wp, "get_wallet_addresses", lambda: [EVM])
    body = client.get("/api/bittensor/performance").get_json()
    assert body["status"] == "ok" and body["wallets"] == []


def test_route_matches_pure_function_and_skips_failed_runs(client, dbpath, monkeypatch):
    conn = _db(dbpath)
    runs = [(1, "2026-09-29T22:00:00", "completed", 300.0), (2, "2026-09-30T00:00:00", "completed", 310.0),
            (3, "2026-09-30T01:00:00", "failed", 900.0)]
    all_rows = []
    for sid, ts, st, price in runs:
        conn.execute("INSERT INTO portfolio_snapshots (id, user_id, timestamp, wallet, status) VALUES (?, 1, ?, ?, ?)",
                     (sid, ts, ALICE, st))
        for r in _run(ts, price):
            if st == "failed":
                r["value_usd"] *= 2                           # would show a false jump if not excluded
            conn.execute("INSERT INTO token_snapshots (snapshot_id, user_id, timestamp, wallet, chain, symbol, "
                         "balance, price_usd, value_usd) VALUES (?, 1, ?, ?, 'Bittensor', ?, 1, ?, ?)",
                         (sid, ts, ALICE, r["symbol"], r["price_usd"], r["value_usd"]))
            if st != "failed":
                all_rows.append(r)
    conn.execute("INSERT INTO bittensor_flows (wallet, flow_at, amount_rao, note, created_at) VALUES (?, ?, ?, ?, ?)",
                 (ALICE, "2026-09-29T00:00:00+00:00", 12802160052, None, "2026-09-29T00:00:00+00:00"))
    conn.commit()
    conn.close()
    monkeypatch.setattr(wp, "_portfolio_cache", {"tokens": [], "bittensor": {"wallets": {ALICE: _status()}}})
    body = client.get("/api/bittensor/performance").get_json()
    [w] = body["wallets"]
    assert [p["t"] for p in w["series"]] == ["2026-09-29T22:00:00+00:00", "2026-09-30T00:00:00+00:00"]
    assert all(p["tao_eq"] == pytest.approx(TAO_TOTAL, abs=1e-9) for p in w["series"])
    expected = bp.build_wallet(ALICE, "Alpha bot", _status(),
                               [{"id": 1, "flow_at": "2026-09-29T00:00:00+00:00", "amount_rao": 12802160052, "note": None}],
                               all_rows, [], datetime.now(timezone.utc))
    for k in ("label", "state", "tao_now", "net_deposited_tao", "result_tao", "result_pct", "result_usd", "flows", "deposits"):
        assert w[k] == pytest.approx(expected[k]) if isinstance(expected[k], float) else w[k] == expected[k], k


def test_post_flows_success(client, dbpath):
    r = client.post("/api/bittensor/flows", json={"wallet": ALICE, "kind": "deposit", "amount_tao": 12.802160052,
                                                  "date": "2026-09-29", "note": "start"})
    assert r.status_code == 201
    flow = r.get_json()["flow"]
    assert (flow["amount_rao"], flow["flow_at"], flow["wallet"], flow["note"]) == (
        12802160052, "2026-09-29T00:00:00+00:00", ALICE, "start")
    r = client.post("/api/bittensor/flows", json={"wallet": ALICE, "kind": "withdrawal", "amount_tao": 2,
                                                  "date": "2026-09-30"})
    assert r.status_code == 201 and r.get_json()["flow"]["amount_rao"] == -2 * 10 ** 9
    conn = _db(dbpath)
    assert [row["amount_rao"] for row in conn.execute("SELECT amount_rao FROM bittensor_flows ORDER BY id")] == [
        12802160052, -2000000000]
    conn.close()


@pytest.mark.parametrize("patch", [
    {"wallet": BOB}, {"wallet": EVM}, {"wallet": ALICE.lower()}, {"kind": "gift"},
    {"amount_tao": 0}, {"amount_tao": -1}, {"amount_tao": True}, {"amount_tao": "1"}, {"amount_tao": "NaN"},
    {"amount_tao": 2000000}, {"date": "2026-02-30"}, {"note": "x" * 201},
])
def test_post_flows_rejects(client, dbpath, patch):
    body = dict({"wallet": ALICE, "kind": "deposit", "amount_tao": 1.5, "date": "2026-09-30"}, **patch)
    r = client.post("/api/bittensor/flows", json=body)
    assert r.status_code == 400 and r.get_json()["error"]
    conn = _db(dbpath)
    assert conn.execute("SELECT COUNT(*) FROM bittensor_flows").fetchone()[0] == 0
    conn.close()


def test_delete_flow(client, dbpath):
    fid = client.post("/api/bittensor/flows", json={"wallet": ALICE, "kind": "deposit", "amount_tao": 1,
                                                    "date": "2026-09-30"}).get_json()["flow"]["id"]
    r = client.delete(f"/api/bittensor/flows/{fid}")
    assert r.status_code == 200 and r.get_json() == {"deleted": fid}
    conn = _db(dbpath)
    assert conn.execute("SELECT COUNT(*) FROM bittensor_flows").fetchone()[0] == 0
    conn.close()
    r = client.delete(f"/api/bittensor/flows/{fid}")
    assert r.status_code == 404 and r.get_json() == {"error": "not found"}
