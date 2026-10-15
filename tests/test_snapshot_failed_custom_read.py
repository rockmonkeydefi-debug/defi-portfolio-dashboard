"""A failed custom-token balance read makes the snapshot run partial (Landing 41, Oct 15).

A custom token whose balance read failed carries balance None and
balance_failed True; take_portfolio_snapshot stores it as balance 0 (the
column is NOT NULL). Before Landing 41 the run stayed 'completed', so the
chart dipped for one run and readers of the latest completed run (Spot's
wallet line, the AI advisor) saw the token gone. Now, when that wallet stored
a balance > 0 for the token within CUSTOM_FAILED_READ_LOOKBACK_DAYS, the run
is 'partial' (every wallet's portfolio_snapshots row and the
portfolio_total_snapshots row), like an API failure.

Real init_db() on a tmp_path SQLite file; no network. Addresses are synthetic.
"""
import sqlite3
from datetime import datetime, timedelta

import pytest

import src.engines.snapshot_service as ss
import src.storage.portfolio_db as portfolio_db

A = "0x" + "a" * 40
B = "0x" + "b" * 40
TOKEN = "0x" + "5C" * 20                       # synthetic ERC-20 contract, mixed case as stored
MINT = "MintFailedRead" + "7" * 30             # synthetic Solana mint, mixed case
SOL = "SynthSolWa11et" + "8" * 30              # synthetic Solana wallet


@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    return path


def _rows(path, table):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
    conn.close()
    return rows


def _custom(wallet=A, contract=TOKEN, symbol="PLAZM", chain="Base", failed=True, balance=None):
    """A custom-token row as build_custom_token_rows returns it."""
    return {"chain": chain, "symbol": symbol, "balance": None if failed else balance,
            "value_usd": 0.0 if failed else (balance or 0) * 0.04, "price_usd": 0.04,
            "contract": contract, "wallet": wallet, "source": "custom", "balance_failed": failed}


def _portfolio(*extra, api_failures=()):
    return {
        "tokens": [{"wallet": A, "chain": "base", "symbol": "ETH", "balance": 1.0, "price_usd": 2000.0,
                    "value_usd": 2000.0},
                   {"wallet": B, "chain": "base", "symbol": "USDT", "balance": 200.0, "price_usd": 1.0,
                    "value_usd": 200.0}] + list(extra),
        "lp_positions": [], "gmx_positions": [], "aave_positions": [], "api_failures": list(api_failures),
    }


def _history(wallet=A, contract=TOKEN, symbol="PLAZM", chain="Base", balance=100000.0, days_ago=1.0,
             status="completed"):
    """One earlier run's stored token row."""
    ts = (datetime.utcnow() - timedelta(days=days_ago)).isoformat()
    sid = portfolio_db.create_portfolio_snapshot(wallet, 1, timestamp=ts)
    portfolio_db.insert_token_snapshot(sid, {"timestamp": ts, "wallet": wallet, "chain": chain, "symbol": symbol,
                                             "token_address": contract, "balance": balance, "price_usd": 0.04,
                                             "value_usd": balance * 0.04}, 1)
    if status == "completed":
        portfolio_db.complete_portfolio_snapshot(sid, {"total_value_usd": balance * 0.04,
                                                       "total_tokens_usd": balance * 0.04, "total_lp_usd": 0,
                                                       "total_lending_usd": 0, "total_hedge_collateral_usd": 0}, 0.1)
    return ts


def _composer(portfolio):
    return {"status": "ok", "total_usd": 2200.0, "components": [], "warnings": [], "as_of": {}}


def _run(portfolio, wallets=(A, B)):
    ss.take_portfolio_snapshot(lambda **_: portfolio, list(wallets), compose_total_fn=_composer)
    ts = max(r["timestamp"] for r in _rows(portfolio_db.get_db_path(), "portfolio_snapshots"))
    snaps = [r for r in _rows(portfolio_db.get_db_path(), "portfolio_snapshots") if r["timestamp"] == ts]
    (total,) = _rows(portfolio_db.get_db_path(), "portfolio_total_snapshots")
    return snaps, total


def _statuses(snaps):
    return sorted((s["wallet"], s["status"]) for s in snaps)


# ── the rule ───────────────────────────────────────────────────────────────

def test_failed_read_of_a_held_token_marks_the_run_partial(dbpath, capsys):
    _history()
    snaps, total = _run(_portfolio(_custom()))
    assert _statuses(snaps) == [(A, "partial"), (B, "partial")]
    assert total["status"] == "partial" and total["wallets_completed"] == 2
    out = capsys.readouterr().out
    assert "custom-token balance read failed for 1 held row(s) (PLAZM on Base): run marked partial" in out
    assert TOKEN.lower() not in out.lower() and A not in out           # symbol and chain only, never an address


def test_the_failed_row_is_still_stored_as_zero_and_totals_are_unchanged(dbpath):
    _history()
    snaps, _ = _run(_portfolio(_custom()))
    stored = [r for r in _rows(dbpath, "token_snapshots")
              if r["snapshot_id"] in {s["id"] for s in snaps} and r["symbol"] == "PLAZM"]
    assert [(r["balance"], r["value_usd"]) for r in stored] == [(0.0, 0.0)]
    by_wallet = {s["wallet"]: s["total_value_usd"] for s in snaps}
    assert by_wallet == {A: pytest.approx(2000.0), B: pytest.approx(200.0)}


def test_no_failed_read_stays_completed_and_skips_the_history_query(dbpath, monkeypatch):
    _history()
    calls = []
    real = ss.get_connection
    monkeypatch.setattr(ss, "get_connection", lambda: calls.append(1) or real())
    snaps, total = _run(_portfolio(_custom(failed=False, balance=100000.0)))
    assert _statuses(snaps) == [(A, "completed"), (B, "completed")] and total["status"] == "completed"
    calls.clear()                                                       # the run's other steps also connect
    assert ss._failed_custom_reads_held(_portfolio(_custom(failed=False, balance=1.0)), [A, B], 1) == []
    assert calls == []                                                  # no failed read: never queried


@pytest.mark.parametrize("history, why", [
    (None, "never stored"),
    (dict(days_ago=8.0), "only older than 7 days"),
    (dict(balance=0.0), "only a zero balance"),
    (dict(wallet=B), "held in another wallet"),
    (dict(contract="0x" + "9d" * 20), "another token"),
])
def test_failed_read_without_a_recent_holding_stays_completed(dbpath, history, why):
    if history is not None:
        _history(**history)
    snaps, total = _run(_portfolio(_custom()))
    assert _statuses(snaps) == [(A, "completed"), (B, "completed")], why
    assert total["status"] == "completed", why


def test_holding_stored_by_a_partial_run_still_counts(dbpath):
    _history(status="partial")
    snaps, total = _run(_portfolio(_custom()))
    assert total["status"] == "partial" and {s["status"] for s in snaps} == {"partial"}


def test_matching_ignores_case_evm_and_solana(dbpath):
    _history(wallet=A.upper().replace("0X", "0x"), contract=TOKEN.lower())
    _history(wallet=SOL, contract=MINT, symbol="SOLX", chain="Solana")
    helper = ss._failed_custom_reads_held
    assert [t["symbol"] for t in helper(_portfolio(_custom()), [A, B], 1)] == ["PLAZM"]
    sol = _custom(wallet=SOL, contract=MINT, symbol="SOLX", chain="Solana")
    assert [t["symbol"] for t in helper(_portfolio(sol), [A, B, SOL], 1)] == ["SOLX"]


def test_failed_read_in_a_wallet_outside_the_run_is_ignored(dbpath):
    _history(wallet=SOL, contract=MINT, symbol="SOLX", chain="Solana")
    sol = _custom(wallet=SOL, contract=MINT, symbol="SOLX", chain="Solana")
    snaps, total = _run(_portfolio(sol), wallets=(A, B))            # SOL not in this run's wallet list
    assert _statuses(snaps) == [(A, "completed"), (B, "completed")] and total["status"] == "completed"


def test_only_held_rows_are_listed_and_duplicates_collapse(dbpath, capsys):
    _history()
    _history(wallet=B)
    other = _custom(contract="0x" + "9d" * 20, symbol="NEVER")
    rows = ss._failed_custom_reads_held(_portfolio(_custom(), _custom(), _custom(wallet=B), other), [A, B], 1)
    assert sorted((t["wallet"], t["symbol"]) for t in rows) == [(A, "PLAZM"), (B, "PLAZM")]
    _run(_portfolio(_custom(), _custom(wallet=B), other))
    assert "failed for 2 held row(s) (PLAZM on Base)" in capsys.readouterr().out


def test_history_check_error_counts_every_failed_read(dbpath, monkeypatch, capsys):
    real = ss.get_connection
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] == 1:                                              # the history check's connection
            raise sqlite3.OperationalError("database is locked")
        return real()

    monkeypatch.setattr(ss, "get_connection", flaky)
    snaps, total = _run(_portfolio(_custom()))                          # no history stored at all
    assert total["status"] == "partial" and {s["status"] for s in snaps} == {"partial"}
    assert "custom-token history check failed (OperationalError: database is locked)" in capsys.readouterr().out


def test_an_api_failure_still_marks_partial_on_its_own(dbpath):
    snaps, total = _run(_portfolio(api_failures=["lp:123"]))
    assert {s["status"] for s in snaps} == {"partial"} and total["status"] == "partial"


def test_a_skipped_run_is_still_skipped(dbpath):
    _history()
    ss.take_portfolio_snapshot(lambda **_: _portfolio(_custom(), api_failures=["tokens:a", "tokens:b", "zerion:c"]),
                               [A, B], compose_total_fn=_composer)
    assert [r["status"] for r in _rows(dbpath, "portfolio_snapshots")] == ["completed"]   # the seeded run only
    assert _rows(dbpath, "portfolio_total_snapshots") == []
