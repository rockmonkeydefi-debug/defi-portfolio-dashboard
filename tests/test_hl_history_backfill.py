"""Hyperliquid history backfill (definition_version 0): the pure
hl_history_backfill module and POST /api/history/portfolio-total/backfill-hyperliquid.

Synthetic only: made-up addresses and values in the documented response
shapes. No network: an autouse fixture replaces web_portfolio._hl_post with a
fake responder keyed on (type, user, startTime) that counts calls."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import hl_history_backfill as hb
import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

W1 = "0x" + "a" * 40
W2 = "0x" + "b" * 40
W3 = "0x" + "c" * 40
OTHER = "0x" + "d" * 40
H = 3600 * 1000
D = 24 * H
T0 = int(datetime(2026, 6, 10, tzinfo=timezone.utc).timestamp() * 1000)


def ms(iso):
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1000)


def naive(t_ms):
    """Epoch ms -> a naive-UTC portfolio_snapshots timestamp string."""
    return datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc).replace(tzinfo=None).isoformat()


def pts(*pairs):
    return [[t, str(v)] for t, v in pairs]


def portfolio_resp(**windows):
    return [[w, {"accountValueHistory": points, "pnlHistory": [], "vlm": "0.0"}] for w, points in windows.items()]


def ev(t, kind, n, **delta):
    return {"time": t, "hash": "0x%064x" % n, "delta": dict({"type": kind}, **delta)}


def wd(windows=None, events=(), wallet=W1):
    """Pure-test wallet data: windows as {w: [(ms, v)]} plus classified flows."""
    w = {x: [] for x in hb.WINDOWS}
    w.update(windows or {})
    return {"windows": w, "flows": hb.classify_ledger(list(events), wallet)}


# ── pure: parsing ──────────────────────────────────────────────────────────

def test_p1_parse_portfolio():
    resp = portfolio_resp(
        day=pts((3000, 5), (1000, 0), (2000, "0.0"), (500, -1), (4000, 0), (5000, "nan"), (6000, "inf"),
                (7000, "x"), (8000, 7)),
        perpDay=pts((1000, 99)), week=[], allTime=[["bad"], [9000, "3"]])
    out = hb.parse_portfolio(resp)
    assert set(out) == set(hb.WINDOWS)
    assert out["day"] == [(3000, 5.0), (4000, 0.0), (8000, 7.0)]     # leading <= 0 trimmed, interior 0 kept
    assert out["week"] == [] and out["month"] == []
    assert out["allTime"] == [(9000, 3.0)]
    assert all(isinstance(t, int) and isinstance(v, float) for t, v in out["day"])
    with pytest.raises(ValueError):
        hb.parse_portfolio({"error": "x"})


def test_p2_classify_ledger():
    events = [
        ev(2, "withdraw", 2, usdc="40", nonce=1, fee="1"),
        ev(1, "deposit", 1, usdc="100"),
        ev(1, "deposit", 1, usdc="100"),                                                   # duplicate page overlap
        ev(3, "accountClassTransfer", 3, usdc="5", toPerp=True),
        ev(4, "send", 4, user=W1.upper().replace("0X", "0x"), destination=W1, token="USDC", amount="9", usdcValue="9"),
        ev(5, "send", 5, user=OTHER, destination=W1.upper().replace("0X", "0x"), token="USDC", amount="25", usdcValue="25"),
        ev(6, "send", 6, user=W1, destination=OTHER, token="USDC", amount="10"),
        ev(7, "spotTransfer", 7, user=W1, destination=OTHER, token="HYPE", amount="3", usdcValue="0.0"),
        ev(8, "spotTransfer", 8, user=W1, destination=OTHER, token="HYPE", amount="3"),
        ev(9, "cStakingTransfer", 9, token="HYPE", amount="1", isDeposit=True),
        ev(10, "mysteryType", 10),
        ev(11, "deposit", 11, usdc="abc"),
        ev(12, "send", 12, user=OTHER, destination=W3, token="USDC", amount="1", usdcValue="1"),
    ]
    flows = hb.classify_ledger(events, W1)
    assert [(f["time_ms"], f["type"], f["usd"]) for f in flows] == [
        (1, "deposit", 100.0), (2, "withdraw", -40.0), (3, "accountClassTransfer", 0.0), (4, "send", 0.0),
        (5, "send", 25.0), (6, "send", -10.0), (7, "spotTransfer", -0.0), (8, "spotTransfer", None),
        (9, "cStakingTransfer", None), (10, "mysteryType", None), (11, "deposit", None), (12, "send", None)]
    assert flows[6]["usd"] is not None                                         # usdcValue "0.0" is valued


# ── pure: value_at ─────────────────────────────────────────────────────────

def test_p3_ledger_only_before_the_first_real_point():
    X = 750.0
    raw = hb.parse_portfolio(portfolio_resp(allTime=pts((T0, 0), (T0 + H, X))))
    assert raw["allTime"] == [(T0 + H, X)]                                     # the $0 start is dropped
    data = {"windows": raw, "flows": hb.classify_ledger([ev(T0 - 4 * D, "deposit", 1, usdc=str(X))], W1)}
    for t in (T0 - 2 * D, T0, T0 + H - 1):
        v = hb.value_at(data["windows"], data["flows"], t)
        assert (v["value_usd"], v["basis"], v["window"], v["p1"]) == (X, "ledger_only", None, None)
        assert v["transfers_since_p1_usd"] == X and v["pnl_share_usd"] == 0.0
    assert hb.value_at(data["windows"], data["flows"], T0 - 5 * D)["value_usd"] == 0.0
    at_point = hb.value_at(data["windows"], data["flows"], T0 + H)
    assert (at_point["value_usd"], at_point["basis"]) == (X, "points")


def test_p4_transfer_counted_at_its_true_time():
    v1, F, P = 1000.0, 300.0, 40.0
    t1, tf, t2 = T0, T0 + 4 * H, T0 + 10 * H
    data = wd({"week": [(t1, v1), (t2, v1 + F + P)]}, [ev(tf, "deposit", 1, usdc=str(F))])
    before = hb.value_at(data["windows"], data["flows"], T0 + 2 * H)
    assert before["value_usd"] == pytest.approx(v1 + P * 0.2)
    assert before["transfers_since_p1_usd"] == 0.0 and before["transfers_p1_to_p2_usd"] == F
    at = hb.value_at(data["windows"], data["flows"], tf)
    assert at["value_usd"] == pytest.approx(v1 + F + P * 0.4)
    after = hb.value_at(data["windows"], data["flows"], T0 + 8 * H)
    assert after["value_usd"] == pytest.approx(v1 + F + P * 0.8)
    assert after["pnl_share_usd"] == pytest.approx(P * 0.8)
    assert after["p1"] == [hb.iso_ms(t1), v1] and after["p2"] == [hb.iso_ms(t2), v1 + F + P]


def test_p5_straight_line_pnl():
    v1, v2 = 1000.0, 1200.0
    data = wd({"week": [(T0, v1), (T0 + 8 * H, v2), (T0 + 16 * H, 900.0)]})
    assert hb.value_at(data["windows"], data["flows"], T0 + 2 * H)["value_usd"] == pytest.approx(v1 + 0.25 * (v2 - v1))
    assert hb.value_at(data["windows"], data["flows"], T0)["value_usd"] == v1
    assert hb.value_at(data["windows"], data["flows"], T0 + 8 * H)["value_usd"] == v2
    assert hb.value_at(data["windows"], data["flows"], T0 + 12 * H)["value_usd"] == pytest.approx(1050.0)


def test_p6_finest_window_wins():
    data = wd({"day": [(T0 + 10 * H, 3.0), (T0 + 20 * H, 3.0)], "week": [(T0, 2.0), (T0 + D, 2.0)],
               "allTime": [(T0 - 30 * D, 1.0), (T0 + D, 1.0)]})
    assert hb.value_at(data["windows"], data["flows"], T0 + 12 * H)["window"] == "day"
    assert hb.value_at(data["windows"], data["flows"], T0 + 5 * H)["window"] == "week"
    old = hb.value_at(data["windows"], data["flows"], T0 - 10 * D)
    assert (old["window"], old["value_usd"]) == ("allTime", 1.0)


def test_p7_no_next_point():
    data = wd({"week": [(T0, 500.0)]}, [ev(T0 + H, "deposit", 1, usdc="20"), ev(T0 + 5 * H, "withdraw", 2, usdc="5")])
    v = hb.value_at(data["windows"], data["flows"], T0 + 3 * H)
    assert v["value_usd"] == 520.0 and v["p2"] is None and v["transfers_p1_to_p2_usd"] is None
    assert v["pnl_share_usd"] == 0.0


def test_p8_unvalued_transfer_only_matters_inside_the_used_interval():
    data = wd({"week": [(T0, 500.0), (T0 + 10 * H, 500.0)],
               "allTime": [(T0 - 10 * D, 500.0), (T0 - D, 500.0), (T0 + 10 * H, 500.0)]},
              [ev(T0 + 4 * H, "mysteryType", 1), ev(T0 + 20 * H, "cStakingTransfer", 2, token="HYPE", amount="1")])
    with pytest.raises(hb.UnvaluedTransfer) as err:
        hb.value_at(data["windows"], data["flows"], T0 + 2 * H)                # inside (p1, p2]
    assert (err.value.time_ms, err.value.type) == (T0 + 4 * H, "mysteryType")
    assert hb.value_at(data["windows"], data["flows"], T0 - 5 * D)["value_usd"] == 500.0   # allTime (T0-10d, T0-1d]
    clean = wd({"week": [(T0, 500.0), (T0 + 10 * H, 500.0)]}, [ev(T0 + 20 * H, "mysteryType", 1)])
    assert hb.value_at(clean["windows"], clean["flows"], T0 + 2 * H)["value_usd"] == 500.0


# ── pure: build_backfill ───────────────────────────────────────────────────

FIRST = {"timestamp": naive(T0 + 30 * D), "snapshot_total_usd": 4000.0, "hyperliquid_usd": 600.0, "total_usd": 4700.0,
         "definition_version": 1}


def _funded_w1():
    """W1: $500 before T0 (a $500 deposit at T0 - 2d), $600 flat from T0."""
    return {"windows": {"day": [], "week": [(T0, 600.0), (T0 + 10 * D, 600.0)], "month": [],
                        "allTime": [(T0 - D, 500.0), (T0, 600.0)]},
            "flows": hb.classify_ledger([ev(T0 - 2 * D, "deposit", 1, usdc="500")], W1),
            "ledger_events": 1, "ledger_types": {"deposit": 1}, "funded": True}


def _unfunded():
    return {"windows": {w: [] for w in hb.WINDOWS}, "flows": [], "ledger_events": 0, "ledger_types": {}, "funded": False}


def _run(t_ms, *rows):
    return {"timestamp": naive(t_ms), "rows": [{"wallet": w, "status": s, "total_value_usd": v} for w, s, v in rows]}


def test_b1_run_selection_and_snapshot_total():
    runs = [_run(T0 + H, (W1, "completed", 100.0), (W2, "completed", 50.0)),
            _run(T0 + 2 * H, (W1, "failed", 0.0), (W2, "partial", 70.0)),
            _run(T0 + 3 * H, (W1, "completed", 100.0), (W2, "failed", None), (W3, "completed", None))]
    rows, rep = hb.build_backfill(runs, {W1: _funded_w1(), W2: _unfunded()}, FIRST)
    assert [r["timestamp"] for r in rows] == [runs[0]["timestamp"], runs[2]["timestamp"]]
    assert [(r["snapshot_total_usd"], r["wallets_total"], r["wallets_completed"]) for r in rows] == [
        (150.0, 2, 2), (100.0, 3, 2)]
    assert (rep["runs_before_cutoff"], rep["runs_selected"], rep["rows"], rep["wallets_queried"]) == (3, 2, 2, 2)


def test_b2_per_run_presence():
    runs = [_run(T0 + H, (W2, "completed", 50.0)),                            # W1 absent: adds 0
            _run(T0 + 2 * H, (W1.upper().replace("0X", "0x"), "failed", 0.0), (W2, "completed", 50.0))]
    rows, rep = hb.build_backfill(runs, {W1: _funded_w1(), W2: _unfunded()}, FIRST)
    assert [r["hyperliquid_usd"] for r in rows] == [0.0, 600.0]
    assert [r["total_usd"] for r in rows] == [50.0, 650.0]
    assert rep["funded_wallets"][0]["runs_counted"] == 1


def test_b3_row_contents():
    runs = [_run(T0 - D - H, (W1, "completed", 1000.0)), _run(T0 + H, (W1, "completed", 1000.0))]
    rows, rep = hb.build_backfill(runs, {W1: _funded_w1()}, FIRST, capture_id="cap-x", labels={W1: "Main"})
    r = rows[1]
    assert set(r) == {"timestamp", "status", "definition_version", "total_usd", "snapshot_total_usd", "hyperliquid_usd",
                      "hl_counted", "wallets_total", "wallets_completed", "detail_json"}
    assert (r["status"], r["definition_version"], r["hl_counted"]) == ("completed", 0, 1)
    assert r["total_usd"] == r["snapshot_total_usd"] + r["hyperliquid_usd"] == 1600.0
    d = json.loads(r["detail_json"])
    assert set(d) == {"source", "definition_version", "definition", "method", "capture_id", "run_rows", "wallets"}
    assert (d["source"], d["definition_version"], d["capture_id"]) == ("hyperliquid_backfill", 0, "cap-x")
    assert d["definition"] == hb.DEFINITION_TEXT and d["method"] == hb.METHOD_TEXT
    assert d["run_rows"] == {"total": 1, "completed": 1}
    assert list(d["wallets"]) == [W1] and d["wallets"][W1]["window"] == "week"
    assert json.loads(rows[0]["detail_json"])["wallets"][W1]["basis"] == "ledger_only"
    fw = rep["funded_wallets"][0]
    assert (fw["wallet"], fw["label"]) == (hb.short(W1), "Main")
    assert fw["first_history_point"] == [hb.iso_ms(T0 - D), 500.0]
    assert fw["points"] == {"day": 0, "week": 2, "month": 0, "allTime": 2}
    assert fw["basis_counts"] == {"points": 1, "ledger_only": 1} and fw["window_counts"]["week"] == 1
    assert fw["first_ledger_event"] == hb.iso_ms(T0 - 2 * D)
    assert rep["runs"][1]["hl_by_wallet"] == {hb.short(W1): 600.0}


def test_b4_checks():
    unvalued = _funded_w1()
    unvalued["flows"] = hb.classify_ledger([ev(T0 - 2 * D, "deposit", 1, usdc="500"), ev(T0 + H, "mysteryType", 2)], W1)
    negative = {"windows": {"day": [], "week": [(T0, 100.0), (T0 + D, 100.0)], "month": [], "allTime": []},
                "flows": hb.classify_ledger([ev(T0 + H, "withdraw", 3, usdc="150")], W2),
                "ledger_events": 1, "ledger_types": {"withdraw": 1}, "funded": True}
    runs = [_run(T0 + 2 * H, (W1, "completed", 1.0), (W2, "completed", 1.0), (W3, "completed", 1.0),
                 ("bc1-not-evm", "completed", 1.0)),
            {"timestamp": naive(T0 + 2 * H)[:16] + ":30", "rows": [{"wallet": W3, "status": "completed", "total_value_usd": 1.0}]},
            {"timestamp": "garbage", "rows": [{"wallet": W1, "status": "completed", "total_value_usd": 1.0}]}]
    rows, rep = hb.build_backfill(runs, {W1: unvalued, W2: negative}, FIRST)
    c = rep["checks"]
    assert c["unvalued_used_count"] == 1 and c["unvalued_used"][0] == {
        "wallet": hb.short(W1), "run": runs[0]["timestamp"], "event": hb.iso_ms(T0 + H), "type": "mysteryType"}
    assert c["negative_values_count"] == 1 and c["negative_values"][0]["value_usd"] < 0
    assert c["not_queried_evm_in_runs"] == [{"wallet": hb.short(W3), "runs": 2}]
    assert c["minute_collisions"] == 1 and c["unparseable_timestamps"] == 1
    assert rep["blocking"] is True
    # W1 counted as 0; W2 = 100 - 150 + (0 - (-150)) * 2/24
    assert rows[0]["hyperliquid_usd"] == pytest.approx(-37.5)
    clean_rows, clean = hb.build_backfill(runs[:1], {W1: _funded_w1()}, FIRST)
    assert clean["blocking"] is False and clean["checks"]["unvalued_used"] == []


def test_b5_seam():
    runs = [_run(T0 + H, (W1, "completed", 100.0)), _run(T0 + 2 * H, (W1, "completed", 200.0))]
    rows, rep = hb.build_backfill(runs, {W1: _funded_w1()}, FIRST)
    assert rep["seam"]["last_backfill"] == {"timestamp": runs[1]["timestamp"], "snapshot_total_usd": 200.0,
                                            "hyperliquid_usd": 600.0, "total_usd": 800.0}
    assert rep["seam"]["first_measured"] == {"timestamp": FIRST["timestamp"], "snapshot_total_usd": 4000.0,
                                             "hyperliquid_usd": 600.0, "total_usd": 4700.0}
    assert rep["cutoff"] == FIRST["timestamp"]
    assert hb.build_backfill([], {W1: _funded_w1()}, FIRST)[1]["seam"]["last_backfill"] is None


# ── route ──────────────────────────────────────────────────────────────────

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


class FakeHL:
    """Fake _hl_post keyed on (type, user, startTime); unknown keys answer []."""

    def __init__(self):
        self.responses = {}
        self.calls = []
        self.error = None

    def set(self, kind, user, resp, start=None):
        self.responses[(kind, user.lower(), start)] = resp

    def __call__(self, payload):
        self.calls.append(payload)
        if self.error:
            raise self.error
        return self.responses.get((payload["type"], payload["user"], payload.get("startTime")), [])


@pytest.fixture(autouse=True)
def fake_hl(monkeypatch):
    fake = FakeHL()
    # W1: allTime history starts at $0 (dropped), $1000 at T0 - 9d, $1500 at T0, flat after; deposits of $1000 at
    # T0 - 9d - 1h and $500 at T0 - 12h. W2: no history, no ledger.
    fake.set("portfolio", W1, portfolio_resp(
        allTime=pts((T0 - 10 * D, 0), (T0 - 9 * D, 1000), (T0, 1500), (T0 + 5 * D, 1500)),
        week=pts((T0 - D, 1000), (T0, 1500), (T0 + D, 1500)),
        perpAllTime=pts((T0 - 9 * D, 5))))
    fake.set("userNonFundingLedgerUpdates", W1, [ev(T0 - 9 * D - H, "deposit", 1, usdc="1000"),
                                                 ev(T0 - 12 * H, "deposit", 2, usdc="500")], start=0)
    monkeypatch.setattr(wp, "_hl_post", fake)
    monkeypatch.setattr(wp, "_hl_accounts_wallets", lambda: [W1, W2])
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {})
    return fake


RUN_TIMES = [T0 - 9 * D - 2 * H, T0 - 5 * D, T0 - H, T0 + 2 * H, T0 + 3 * H]


def _seed(path, measured=True):
    """Five runs: W1 + W2 completed, except run 4 (W2 only) and run 5 (all failed:
    not chart-visible); then the first measured (v1) row."""
    conn = sqlite3.connect(path)
    for i, t in enumerate(RUN_TIMES):
        ts = naive(t)
        if i == 4:
            rows = [(W1, "failed", 0.0), (W2, "failed", 0.0)]
        elif i == 3:
            rows = [(W2, "completed", 200.0)]
        else:
            rows = [(W1, "completed", 1000.0 + i), (W2, "completed", 200.0)]
        for w, s, v in rows:
            conn.execute("INSERT INTO portfolio_snapshots (user_id, timestamp, wallet, status, total_value_usd) "
                         "VALUES (1,?,?,?,?)", (ts, w, s, v))
    conn.commit()
    conn.close()
    if measured:
        return portfolio_db.insert_portfolio_total_snapshot({
            "timestamp": naive(T0 + 20 * D), "status": "completed", "definition_version": 1, "total_usd": 5000.0,
            "snapshot_total_usd": 3400.0, "hyperliquid_usd": 1500.0, "maxfi_uncollected_usd": 100.0, "hl_counted": 1,
            "wallets_total": 2, "wallets_completed": 2, "detail_json": '{"status": "ok"}'})
    return None


def _rows(path, sql, params=()):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    out = [dict(r) for r in conn.execute(sql, params)]
    conn.close()
    return out


URL = "/api/history/portfolio-total/backfill-hyperliquid"
EXPECTED_HL = [0.0, 1000.0, 1500.0, 0.0]   # run 1 before the first deposit; run 2 allTime; run 3 week; run 4 W1 absent


def test_r1_no_measured_row(client, dbpath, fake_hl):
    _seed(dbpath, measured=False)
    r = client.post(URL + "?dry_run=true")
    assert r.status_code == 409 and r.get_json()["error"] == "NoMeasuredRow"
    assert fake_hl.calls == []


def test_r2_dry_run_writes_nothing(client, dbpath, fake_hl):
    _seed(dbpath)
    r = client.post(URL, json={"dry_run": True})
    assert r.status_code == 200
    body = r.get_json()
    assert (body["dry_run"], body["capture_id"], body["capture_source"]) == (True, None, "fresh")
    assert (body["runs_before_cutoff"], body["runs_selected"], body["rows"], body["wallets_queried"]) == (5, 4, 4, 2)
    assert [x["hyperliquid_usd"] for x in body["runs"]] == pytest.approx(EXPECTED_HL)
    assert body["blocking"] is False and body["checks"]["unvalued_used_count"] == 0
    assert [f["wallet"] for f in body["funded_wallets"]] == [hb.short(W1)]
    assert body["funded_wallets"][0]["label"] == W1[:10] + "..."
    assert _rows(dbpath, "SELECT * FROM hl_history_captures") == []
    assert _rows(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE definition_version=0") == []
    assert {c["type"] for c in fake_hl.calls} == {"portfolio", "userNonFundingLedgerUpdates"}


def test_r3_real_run(client, dbpath, fake_hl):
    v1_id = _seed(dbpath)
    v1_before = _rows(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE id=?", (v1_id,))
    r = client.post(URL)
    assert r.status_code == 200
    body = r.get_json()
    assert "runs" not in body and body["dry_run"] is False and body["capture_source"] == "fresh"
    assert body["rows_written"] == body["runs_selected"] == 4 and body["v0_deleted"] == 0
    caps = _rows(dbpath, "SELECT * FROM hl_history_captures ORDER BY id")
    assert body["captures_written"] == len(caps) and {c["capture_id"] for c in caps} == {body["capture_id"]}
    for w in (W1, W2):
        kinds = [c["request_type"] for c in caps if c["wallet"] == w]
        assert kinds.count("portfolio") == 1 and kinds.count("ledger") >= 1
    v0 = _rows(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE definition_version=0 ORDER BY timestamp")
    assert [x["hyperliquid_usd"] for x in v0] == pytest.approx(EXPECTED_HL)
    assert [x["timestamp"] for x in v0] == [naive(t) for t in RUN_TIMES[:4]]
    assert json.loads(v0[0]["detail_json"])["capture_id"] == body["capture_id"]
    assert all(x["maxfi_uncollected_usd"] is None and x["wallet_tokens_usd"] is None for x in v0)
    assert _rows(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE id=?", (v1_id,)) == v1_before
    hist = client.get("/api/history/portfolio-total?days=9999").get_json()
    assert [(h["definition_version"], h["usable"]) for h in hist] == [(0, True)] * 4 + [(1, True)]


def test_r4_second_fresh_run_replaces_v0(client, dbpath, fake_hl):
    v1_id = _seed(dbpath)
    v1_before = _rows(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE id=?", (v1_id,))
    first = client.post(URL).get_json()
    second = client.post(URL).get_json()
    assert second["v0_deleted"] == first["rows_written"] == second["rows_written"]
    assert len(_rows(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE definition_version=0")) == 4
    assert len(_rows(dbpath, "SELECT * FROM hl_history_captures")) == first["captures_written"] + second["captures_written"]
    assert _rows(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE id=?", (v1_id,)) == v1_before


def test_r5_rederive_from_stored_capture(client, dbpath, fake_hl):
    _seed(dbpath)
    first = client.post(URL).get_json()
    cols = "timestamp, status, definition_version, total_usd, snapshot_total_usd, hyperliquid_usd, hl_counted, " \
           "wallets_total, wallets_completed, detail_json"
    before = _rows(dbpath, f"SELECT {cols} FROM portfolio_total_snapshots WHERE definition_version=0 ORDER BY timestamp")
    caps_before = len(_rows(dbpath, "SELECT * FROM hl_history_captures"))
    fake_hl.calls.clear()
    r = client.post(URL + "?capture_id=" + first["capture_id"])
    assert r.status_code == 200 and fake_hl.calls == []
    body = r.get_json()
    assert (body["capture_source"], body["capture_id"], body["captures_written"]) == ("stored", first["capture_id"], 0)
    after = _rows(dbpath, f"SELECT {cols} FROM portfolio_total_snapshots WHERE definition_version=0 ORDER BY timestamp")
    assert after == before
    assert len(_rows(dbpath, "SELECT * FROM hl_history_captures")) == caps_before
    dry = client.post(URL, json={"capture_id": first["capture_id"], "dry_run": True})
    assert dry.status_code == 200 and dry.get_json()["capture_id"] == first["capture_id"] and fake_hl.calls == []
    missing = client.post(URL + "?capture_id=nope")
    assert missing.status_code == 404 and missing.get_json()["error"] == "CaptureNotFound"


def test_r6_hyperliquid_failure(client, dbpath, fake_hl):
    _seed(dbpath)
    fake_hl.error = TimeoutError("hl timeout")
    r = client.post(URL)
    assert r.status_code == 502
    assert r.get_json() == {"error": "HyperliquidFetchError", "detail": "TimeoutError: hl timeout"}
    assert _rows(dbpath, "SELECT * FROM hl_history_captures") == []
    assert _rows(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE definition_version=0") == []


def test_r7_unvalued_transfer_blocks_the_real_run(client, dbpath, fake_hl):
    _seed(dbpath)
    fake_hl.set("userNonFundingLedgerUpdates", W1, [ev(T0 - 9 * D - H, "deposit", 1, usdc="1000"),
                                                    ev(T0 - 12 * H, "deposit", 2, usdc="500"),
                                                    ev(T0 - 3 * D, "mysteryType", 3)], start=0)
    r = client.post(URL)
    assert r.status_code == 422
    body = r.get_json()
    assert body["error"] == "BackfillBlocked" and body["blocking"] is True and "runs" not in body
    assert body["checks"]["unvalued_used_count"] >= 1
    assert body["checks"]["unvalued_used"][0]["type"] == "mysteryType"
    assert _rows(dbpath, "SELECT * FROM hl_history_captures") == []
    assert _rows(dbpath, "SELECT * FROM portfolio_total_snapshots WHERE definition_version=0") == []
    dry = client.post(URL + "?dry_run=true")
    assert dry.status_code == 200 and dry.get_json()["checks"]["unvalued_used_count"] >= 1


def test_r8_busy_lock(client, dbpath, fake_hl):
    _seed(dbpath)
    assert wp._HL_HISTORY_BACKFILL_LOCK.acquire(blocking=False)
    try:
        r = client.post(URL + "?dry_run=true")
        assert r.status_code == 409 and r.get_json()["error"] == "RefreshBusy"
        assert fake_hl.calls == []
    finally:
        wp._HL_HISTORY_BACKFILL_LOCK.release()
    assert client.post(URL + "?dry_run=true").status_code == 200


def _page(first_n, count):
    return [ev(T0 - 20 * D + i * 1000, "deposit", i, usdc="1") for i in range(first_n, first_n + count)]


def test_r9_ledger_paging(client, dbpath, fake_hl):
    _seed(dbpath)
    L = hb.LEDGER_PAGE_LIMIT
    page1 = _page(0, L)
    page2 = _page(L - 1, 3)                                                   # overlaps by one, adds two
    fake_hl.set("userNonFundingLedgerUpdates", W1, page1, start=0)
    fake_hl.set("userNonFundingLedgerUpdates", W1, page2, start=page1[-1]["time"])
    fake_hl.set("userNonFundingLedgerUpdates", W1, [page2[-1]], start=page2[-1]["time"])   # adds none
    body = client.post(URL + "?dry_run=true").get_json()
    starts = [c.get("startTime") for c in fake_hl.calls if c["type"] != "portfolio" and c["user"] == W1]
    assert starts == [0, page1[-1]["time"]]                                   # page 2 is short: paging stops
    assert body["funded_wallets"][0]["ledger_events"] == L + 2


def test_r9b_ledger_paging_stops_when_a_full_page_adds_nothing(client, dbpath, fake_hl):
    _seed(dbpath)
    L = hb.LEDGER_PAGE_LIMIT
    page1 = _page(0, L)
    fake_hl.set("userNonFundingLedgerUpdates", W1, page1, start=0)
    fake_hl.set("userNonFundingLedgerUpdates", W1, list(page1), start=page1[-1]["time"])   # full page, nothing new
    body = client.post(URL + "?dry_run=true").get_json()
    starts = [c.get("startTime") for c in fake_hl.calls if c["type"] != "portfolio" and c["user"] == W1]
    assert starts == [0, page1[-1]["time"]]
    assert body["funded_wallets"][0]["ledger_events"] == L
