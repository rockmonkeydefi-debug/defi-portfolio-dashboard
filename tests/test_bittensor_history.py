"""Bittensor history rules (ruling 9): the display-only Wallet tokens clause
in compose_total, and take_portfolio_snapshot marking an unavailable
Bittensor wallet's row failed (the run is then left out of the Dashboard
chart as a gap, not a dip). Values never change here.

Real init_db() on a tmp_path SQLite file for the snapshot writer. No
network. Only the public Substrate dev address ALICE is used."""
import copy
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import portfolio_total as pt
import src.engines.snapshot_service as ss
import src.storage.portfolio_db as portfolio_db

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
A = "0x" + "a" * 40
ALICE = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
HL = {"fetched_at": None, "wallets": {}, "error": None}


def _status(state, value=3773.28, age=5.2, as_of="2026-09-30T06:48:00+00:00", reason=None, diff=0.0):
    return {"state": state, "as_of": as_of, "age_hours": age, "tao_amount": 12.577601758, "value_usd": value,
            "price_usd": 300.0, "price_source": "coingecko", "price_at": NOW.isoformat(), "diff_tao": diff,
            "error": None, "reason": reason}


def _portfolio(bittensor=None, tokens=None):
    p = {"tokens": tokens if tokens is not None else [
            {"symbol": "ETH", "value_usd": 2000.0, "wallet": A},
            {"symbol": "TAO", "value_usd": 523.77, "wallet": ALICE, "chain": "Bittensor", "balance": 1.7459,
             "price_usd": 300.0}],
         "lp_positions": [], "aave_positions": [], "gmx_positions": [], "staking_positions": [],
         "total_value": 2523.77, "wallet_labels": {A: "Main", ALICE: "TAO main"},
         "fetched_at": "2026-09-30T11:55:00"}
    if bittensor is not None:
        p["bittensor"] = {"wallets": bittensor, "fetched_at": NOW.isoformat(), "error": None}
    return p


def _compose(p):
    return pt.compose_total(p, [], set(), True, {}, HL, NOW)


def _wt(r):
    return next(c for c in r["components"] if c["key"] == "wallet_tokens")


def _values(r):
    return {c["key"]: c["value_usd"] for c in r["components"]}


# ── the Wallet tokens clause ──────────────────────────────────────────────

def test_stale_clause_is_one_line_and_values_unchanged():
    r = _compose(_portfolio({ALICE: _status("stale")}))
    base = _compose(_portfolio())
    wt = _wt(r)
    assert wt["warnings"] == ["Bittensor at last good read — about $3,773, 5 h old"]
    assert wt["value_usd"] == _wt(base)["value_usd"] and r["total_usd"] == base["total_usd"]
    assert _values(r) == _values(base)
    assert wt["detail"]["bittensor"][ALICE]["state"] == "stale"


def test_unavailable_clauses():
    r = _compose(_portfolio({ALICE: _status("unavailable", age=26.0, as_of="2026-09-29T10:00:00+00:00",
                                            reason="Taostats data over 24 h old")}))
    assert _wt(r)["warnings"] == ["Bittensor not counted — last about $3,773 (Sep 29)"]
    r = _compose(_portfolio({ALICE: _status("unavailable", value=None, age=None, as_of=None,
                                            reason="no Taostats data yet")}))
    assert _wt(r)["warnings"] == ["Bittensor not counted — no Taostats data yet"]


def test_diff_clause():
    r = _compose(_portfolio({ALICE: _status("fresh", age=0.2, diff=0.005)}))
    (line,) = _wt(r)["warnings"]
    assert "differ from Taostats total" in line and line.endswith("+0.005 TAO")


def test_stale_token_and_bittensor_clauses_share_one_line():
    tokens = [{"symbol": "PLAZM", "value_usd": 3800.0, "wallet": A, "price_stale": True,
               "price_as_of": (NOW - timedelta(hours=3)).isoformat(), "contract": "0x" + "c" * 40, "chain": "Base"}]
    r = _compose(_portfolio({ALICE: _status("stale")}, tokens=tokens))
    assert _wt(r)["warnings"] == [
        "1 token at last good price — about $3,800 (PLAZM, 3 h old); "
        "Bittensor at last good read — about $3,773, 5 h old"]
    assert [w["component"] for w in r["warnings"]].count("wallet_tokens") == 1


def test_no_bittensor_key_or_all_fresh_adds_no_warning():
    base = _compose(_portfolio())
    assert _wt(base)["warnings"] == [] and "bittensor" not in _wt(base)["detail"]
    fresh = _compose(_portfolio({ALICE: _status("fresh", age=0.2)}))
    assert _wt(fresh)["warnings"] == [] and fresh["warnings"] == base["warnings"]
    assert _values(fresh) == _values(base) and fresh["total_usd"] == base["total_usd"]
    assert _wt(base)["source"].endswith(" + Bittensor (Taostats)")


# ── the snapshot writer ───────────────────────────────────────────────────

@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    return path


def _snap_portfolio(state):
    p = {"tokens": [{"wallet": A, "chain": "base", "symbol": "ETH", "balance": 1.0, "price_usd": 2000.0,
                     "value_usd": 2000.0}],
         "lp_positions": [], "gmx_positions": [], "aave_positions": [], "api_failures": [],
         "bittensor": {"wallets": {ALICE: _status(state, reason="no TAO price" if state == "unavailable" else None)},
                       "fetched_at": None, "error": None}}
    if state == "stale":
        p["tokens"].append({"wallet": ALICE, "chain": "Bittensor", "symbol": "TAO", "balance": 1.7459,
                            "price_usd": 300.0, "value_usd": 523.77, "tao_stale": True})
    return p


def _composer(portfolio):
    return pt.compose_total(portfolio, [], set(), True, {}, HL, NOW)


def _rows(path, sql):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def test_unavailable_bittensor_wallet_row_is_failed(dbpath):
    P = _snap_portfolio("unavailable")
    ss.take_portfolio_snapshot(lambda **_: copy.deepcopy(P), [A, ALICE], compose_total_fn=_composer)
    snaps = {r["wallet"]: r["status"] for r in _rows(dbpath, "SELECT wallet, status FROM portfolio_snapshots")}
    assert snaps == {A: "completed", ALICE: "failed"}
    (row,) = _rows(dbpath, "SELECT wallets_total, wallets_completed, status FROM portfolio_total_snapshots")
    assert (row["wallets_total"], row["wallets_completed"], row["status"]) == (2, 1, "completed")


def test_stale_bittensor_wallet_row_is_written(dbpath):
    P = _snap_portfolio("stale")
    ss.take_portfolio_snapshot(lambda **_: copy.deepcopy(P), [A, ALICE], compose_total_fn=_composer)
    snaps = {r["wallet"]: r["status"] for r in _rows(dbpath, "SELECT wallet, status FROM portfolio_snapshots")}
    assert snaps == {A: "completed", ALICE: "completed"}
    (row,) = _rows(dbpath, "SELECT wallets_total, wallets_completed FROM portfolio_total_snapshots")
    assert (row["wallets_total"], row["wallets_completed"]) == (2, 2)
    tao = _rows(dbpath, "SELECT symbol, token_address, value_usd FROM token_snapshots WHERE wallet = '%s'" % ALICE)
    assert tao == [{"symbol": "TAO", "token_address": None, "value_usd": 523.77}]
