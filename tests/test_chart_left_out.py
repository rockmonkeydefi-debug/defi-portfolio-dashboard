"""Runs left out of the Dashboard equity chart, with the reason (Landing 42, Oct 15).

portfolio_total_chart.build_chart lists every run it leaves out (not_usable,
incomplete, glitch) with its time; describe_left_out turns one run into plain
sentences: the notes recorded with the run (Landing 42 on), or for older runs
its failed wallet rows, the composer's error, TxFlow and Hyperliquid. GET
/api/history/portfolio-total-chart adds them as "reasons", wallets by
Settings label, never by address.

Real init_db() on a tmp_path SQLite file; no network. Addresses are synthetic.
"""
import json
import re
import sqlite3

import pytest

import portfolio_total_chart as ptc
import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

A = "0x" + "a1" * 20
B = "0x" + "b2" * 20
C = "0x" + "c3" * 20
EVM = re.compile(r"0x[0-9a-fA-F]{40}")


def _row(i, ts, status="completed", hl_counted=1, total=100.0, wt=2, wc=2, v=3):
    return {"id": i, "timestamp": ts, "status": status, "definition_version": v, "total_usd": total,
            "snapshot_total_usd": 80.0, "hyperliquid_usd": 20.0, "hl_counted": hl_counted,
            "wallets_total": wt, "wallets_completed": wc}


# ── build_chart: the list ──────────────────────────────────────────────────

def test_every_left_out_run_is_listed_with_its_time_and_kind():
    rows = [_row(1, "2026-10-14T10:00:00"),
            _row(2, "2026-10-14T12:00:00", status="partial"),
            _row(3, "2026-10-14T14:00:00", hl_counted=0),
            _row(4, "2026-10-14T16:00:00", wc=1),
            _row(5, "2026-10-14T18:00:00", status="failed", total=None),
            _row(6, "not a time", status="partial"),
            _row(7, "2026-10-14T20:00:00")]
    out = ptc.build_chart(rows, [])
    assert [p["id"] for p in out["points"]] == [1, 7]
    assert out["left_out"] == [
        {"id": 2, "t": "2026-10-14T12:00:00.000Z", "kind": "not_usable", "glitch": None},
        {"id": 3, "t": "2026-10-14T14:00:00.000Z", "kind": "not_usable", "glitch": None},
        {"id": 4, "t": "2026-10-14T16:00:00.000Z", "kind": "incomplete", "glitch": None},
        {"id": 5, "t": "2026-10-14T18:00:00.000Z", "kind": "not_usable", "glitch": None}]
    assert out["excluded"] == {"not_usable": 4, "incomplete": 1, "unparseable": 0, "glitch": 0}


def test_glitch_runs_carry_their_reason():
    ts, reason = ptc.GLITCH_RUNS[0]
    out = ptc.build_chart([_row(1, "2026-08-24T10:00:00"), _row(2, ts), _row(3, "2026-08-24T20:00:00")], [])
    assert out["left_out"] == [{"id": 2, "t": "2026-08-24T15:30:21.767Z", "kind": "glitch", "glitch": reason}]


def test_points_and_seams_unchanged_by_the_list():
    rows = [_row(1, "2026-10-14T10:00:00", v=2), _row(2, "2026-10-14T11:00:00", status="partial"),
            _row(3, "2026-10-14T12:00:00", v=3)]
    out = ptc.build_chart(rows, [])
    assert [p["id"] for p in out["points"]] == [1, 3]
    assert out["seams"] == [{"t": "2026-10-14T12:00:00.000Z", "from_v": 2, "to_v": 3}]


# ── describe_left_out ──────────────────────────────────────────────────────

def _run(status="completed", hl_counted=1, total=100.0, error=None, wt=2, wc=2, detail=None):
    return {"status": status, "hl_counted": hl_counted, "total_usd": total, "error": error,
            "wallets_total": wt, "wallets_completed": wc, "detail": detail}


def test_recorded_notes_are_used_as_they_are():
    run = _run(status="partial", detail={"run_notes": ["LP position #7 didn't load", "TxFlow not read for Main"]})
    assert ptc.describe_left_out(run, ["Ignored"]) == ["LP position #7 didn't load", "TxFlow not read for Main"]


def test_older_run_names_its_failed_wallets():
    assert ptc.describe_left_out(_run(wc=1, detail={"components": []}), ["Vault Cold"]) == [
        "Vault Cold: wallet didn't save (the cause wasn't recorded before Oct 15)"]


def test_older_run_without_failed_rows_counts_wallets():
    assert ptc.describe_left_out(_run(wt=5, wc=3)) == ["2 wallets didn't save"]
    assert ptc.describe_left_out(_run(wt=5, wc=4)) == ["1 wallet didn't save"]


@pytest.mark.parametrize("error, text", [
    ("ValueError: compose status 'cache_cold'", "The total wasn't worked out: the portfolio data hadn't loaded yet"),
    ("TypeError: bad part", "The total wasn't worked out: an error stopped it (TypeError: bad part)"),
    (None, "The total wasn't worked out: an error stopped it"),
])
def test_composer_failure_in_plain_words(error, text):
    assert ptc.describe_left_out(_run(status="failed", total=None, error=error)) == [text]


def test_composer_failure_keeps_recorded_notes_first():
    run = _run(status="failed", total=None, error="TypeError: x", detail={"run_notes": ["LP position #7 didn't load"]})
    assert ptc.describe_left_out(run) == ["LP position #7 didn't load",
                                          "The total wasn't worked out: an error stopped it (TypeError: x)"]


def test_older_hyperliquid_not_counted():
    hl = {"key": "hyperliquid", "counted": False,
          "warnings": ["Hyperliquid loading", "last Hyperliquid refresh failed: timeout"]}
    assert ptc.describe_left_out(_run(hl_counted=0, detail={"components": [hl]})) == [
        "Hyperliquid not counted: no Hyperliquid reading yet (last refresh failed: timeout)"]
    assert ptc.describe_left_out(_run(hl_counted=0, detail=None)) == [
        "Hyperliquid not counted: no Hyperliquid reading yet"]


def test_older_partial_runs():
    unread = {"key": "txflow", "counted": True, "detail": {"wallets": [{"label": "TxFlow Main", "counted": False}]}}
    never = {"key": "txflow", "counted": False, "detail": {"wallets": []}}
    assert ptc.describe_left_out(_run(status="partial", detail={"components": [unread]})) == [
        "TxFlow not read for TxFlow Main"]
    assert ptc.describe_left_out(_run(status="partial", detail={"components": [never]})) == [
        "TxFlow not counted: no TxFlow reading yet"]
    assert ptc.describe_left_out(_run(status="partial", detail={"components": []})) == [
        "Some data didn't load (which source wasn't recorded before Oct 15)"]


def test_no_total_and_glitch_and_never_empty():
    assert ptc.describe_left_out(_run(total=None)) == ["No total was saved for this run"]
    assert ptc.describe_left_out(_run(), glitch="CVX priced $0") == [
        "Left out by hand as a known glitch: CVX priced $0"]
    assert ptc.describe_left_out(_run()) == ["Left out of the chart (no cause recorded)"]
    assert ptc.describe_left_out(None) == ["Left out of the chart (no cause recorded)"]


def test_malformed_older_detail_never_raises():
    run = _run(status="partial", hl_counted=0, detail={"components": [
        {"key": "hyperliquid", "counted": False, "warnings": 5},
        {"key": "txflow", "counted": True, "detail": "not a dict"}], "run_notes": "not a list"})
    assert ptc.describe_left_out(run) == ["Hyperliquid not counted: no Hyperliquid reading yet",
                                          "Some data didn't load (which source wasn't recorded before Oct 15)"]
    assert ptc.describe_left_out(_run(status="partial", detail={"components": "nope"})) == [
        "Some data didn't load (which source wasn't recorded before Oct 15)"]


def test_duplicates_collapse():
    run = _run(status="partial", detail={"run_notes": ["Same", "Same", "Other"]})
    assert ptc.describe_left_out(run) == ["Same", "Other"]


# ── the route ──────────────────────────────────────────────────────────────

@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    return path


SOL = "SynthChartSolWa11et" + "6" * 25                  # a configured Solana wallet without a label


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {A: {"label": "Desk Hot"}, B: {"label": "Vault Cold"},
                                                           SOL: {"type": "solana"}, "0xbroken": "not a dict"})
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _seed(ts, status="completed", hl_counted=1, total=100.0, wt=2, wc=2, detail=None, error=None, failed=()):
    for w in (A, B, C)[:wt]:
        sid = portfolio_db.create_portfolio_snapshot(w, 1, timestamp=ts)
        if w in failed:
            portfolio_db.fail_portfolio_snapshot(sid, 0.1)
    portfolio_db.insert_portfolio_total_snapshot({
        "timestamp": ts, "status": status, "definition_version": 3, "total_usd": total, "snapshot_total_usd": 80.0,
        "hyperliquid_usd": 20.0, "hl_counted": hl_counted, "wallets_total": wt, "wallets_completed": wc,
        "detail_json": json.dumps(detail) if detail is not None else None, "error": error}, 1)


def test_route_adds_reasons_by_label(client, dbpath):
    from datetime import datetime, timedelta
    base = datetime.utcnow() - timedelta(hours=10)
    t = [(base + timedelta(hours=h)).isoformat() for h in range(6)]
    _seed(t[0])
    _seed(t[1], status="partial", detail={"run_notes": ["Zerion: tokens and positions for Desk Hot didn't load"]})
    _seed(t[2], wt=3, wc=1, failed=(B, C))
    _seed(t[3], status="failed", total=None, error=f"KeyError: {A}")
    _seed(t[4], hl_counted=0, detail={"components": [{"key": "hyperliquid", "counted": False,
                                                      "warnings": ["Hyperliquid loading"]}]})
    _seed(t[5])
    r = client.get("/api/history/portfolio-total-chart?days=2")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["points"]) == 2
    assert [e["reasons"] for e in body["left_out"]] == [
        ["Zerion: tokens and positions for Desk Hot didn't load"],
        ["Vault Cold: wallet didn't save (the cause wasn't recorded before Oct 15)",
         f"unlabeled wallet …{C[-4:]}: wallet didn't save (the cause wasn't recorded before Oct 15)"],
        ["The total wasn't worked out: an error stopped it (KeyError: Desk Hot)"],
        ["Hyperliquid not counted: no Hyperliquid reading yet"]]
    assert not EVM.search(json.dumps(body["left_out"]))


def test_route_masks_unlabeled_wallets_and_secrets(client, dbpath, monkeypatch):
    from datetime import datetime, timedelta
    secret = "s3cr3tValueForChartTest42"
    monkeypatch.setenv("CHART_TEST_API_KEY", secret)
    base = datetime.utcnow() - timedelta(hours=5)
    _seed(base.isoformat())
    _seed((base + timedelta(hours=1)).isoformat(), status="failed", total=None,
          error=f"KeyError: '{SOL}' via https://rpc.example/v2/{secret} and {'e5' * 20}")
    _seed((base + timedelta(hours=2)).isoformat())
    body = client.get("/api/history/portfolio-total-chart").get_json()
    (reason,) = body["left_out"][0]["reasons"]
    assert SOL not in reason and secret not in reason and "e5e5e5" not in reason
    assert f"unlabeled wallet …{SOL[-4:]}" in reason and "<redacted:CHART_TEST_API_KEY>" in reason
    assert reason.endswith("and a wallet)")


def test_one_bad_run_keeps_the_others_described(client, dbpath, monkeypatch):
    from datetime import datetime, timedelta
    base = datetime.utcnow() - timedelta(hours=6)
    _seed(base.isoformat())
    _seed((base + timedelta(hours=1)).isoformat(), status="partial", detail={"run_notes": ["First"]})
    _seed((base + timedelta(hours=2)).isoformat(), status="partial", detail={"run_notes": ["BOOM"]})
    _seed((base + timedelta(hours=3)).isoformat(), status="partial", detail={"run_notes": ["Third"]})
    _seed((base + timedelta(hours=4)).isoformat())
    real = ptc.describe_left_out

    def flaky(run, *a, **k):
        if (run.get("detail") or {}).get("run_notes") == ["BOOM"]:
            raise RuntimeError("bad row")
        return real(run, *a, **k)

    monkeypatch.setattr(ptc, "describe_left_out", flaky)
    body = client.get("/api/history/portfolio-total-chart").get_json()
    assert [e["reasons"] for e in body["left_out"]] == [
        ["First"], ["Left out of the chart (details unavailable)"], ["Third"]]


def test_route_reasons_failure_never_fails_the_chart(client, dbpath, monkeypatch):
    from datetime import datetime, timedelta
    _seed((datetime.utcnow() - timedelta(hours=3)).isoformat())
    _seed((datetime.utcnow() - timedelta(hours=2)).isoformat(), status="partial")
    _seed((datetime.utcnow() - timedelta(hours=1)).isoformat())
    monkeypatch.setattr(portfolio_db, "get_portfolio_total_runs",
                        lambda ids: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    r = client.get("/api/history/portfolio-total-chart")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["points"]) == 2
    assert body["left_out"][0]["reasons"] == ["Left out of the chart (details unavailable)"]


def test_route_with_nothing_left_out(client, dbpath):
    r = client.get("/api/history/portfolio-total-chart")
    assert r.status_code == 200 and r.get_json()["left_out"] == []


def test_run_detail_helpers_chunk_and_filter(dbpath):
    from datetime import datetime, timedelta
    stamps = [(datetime.utcnow() - timedelta(minutes=m)).isoformat() for m in range(3)]
    for ts in stamps:
        _seed(ts, wt=2, wc=1, failed=(A,))
    runs = portfolio_db.get_portfolio_total_runs([1, 2, 3, None, 99])
    assert sorted(runs) == [1, 2, 3]
    assert set(runs[1]) == {"id", "timestamp", "status", "hl_counted", "total_usd", "error", "wallets_total",
                            "wallets_completed", "detail_json"}
    failed = portfolio_db.get_failed_snapshot_wallets(stamps + [None, "nope"])
    assert {k: v for k, v in failed.items()} == {ts: [A] for ts in stamps}
    assert portfolio_db.get_portfolio_total_runs([]) == {} and portfolio_db.get_failed_snapshot_wallets([]) == {}


def test_run_detail_helper_reads_past_the_first_chunk(dbpath):
    from datetime import datetime, timedelta
    base = datetime.utcnow() - timedelta(days=30)
    for i in range(620):
        portfolio_db.insert_portfolio_total_snapshot({
            "timestamp": (base + timedelta(minutes=i)).isoformat(), "status": "partial", "definition_version": 3,
            "total_usd": 1.0, "snapshot_total_usd": 1.0, "hyperliquid_usd": 0.0, "hl_counted": 1,
            "wallets_total": 1, "wallets_completed": 1}, 1)
    runs = portfolio_db.get_portfolio_total_runs(range(1, 621))
    assert len(runs) == 620 and sorted(runs)[-1] == 620
