"""Why a snapshot run is left out of the chart, recorded with the run (Landing 42, Oct 15).

take_portfolio_snapshot writes plain sentences (wallet labels, never
addresses) into the portfolio_total_snapshots row's detail_json under
"run_notes": API failures, held custom tokens whose balance read failed,
wallet rows that failed, TxFlow not read and Hyperliquid not counted. The
Dashboard chart's tooltip shows them. Nothing about the run's status, values
or other rows changes, and building the notes never fails a run.

Real init_db() on a tmp_path SQLite file; no network. Addresses are synthetic.
"""
import json
import re
import sqlite3
from datetime import datetime, timedelta

import pytest

import src.engines.snapshot_service as ss
import src.storage.portfolio_db as portfolio_db

A = "0x" + "a1" * 20
B = "0x" + "b2" * 20
C = "0x" + "c3" * 20                            # not in wallet_labels
SOL = "SynthNotesWa11et" + "9" * 28
TOKEN = "0x" + "5C" * 20
LABELS = {A: "Desk Hot", B: "Vault Cold", SOL: "Sol Main"}
EVM = re.compile(r"0x[0-9a-fA-F]{40}")


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


def _portfolio(*extra_tokens, api_failures=(), bittensor=None):
    p = {
        "tokens": [{"wallet": A, "chain": "base", "symbol": "ETH", "balance": 1.0, "price_usd": 2000.0,
                    "value_usd": 2000.0},
                   {"wallet": B, "chain": "base", "symbol": "USDT", "balance": 200.0, "price_usd": 1.0,
                    "value_usd": 200.0}] + list(extra_tokens),
        "lp_positions": [], "gmx_positions": [], "aave_positions": [], "api_failures": list(api_failures),
        "wallet_labels": dict(LABELS),
    }
    if bittensor is not None:
        p["bittensor"] = bittensor
    return p


def _comp(key, counted=True, warnings=(), detail=None):
    return {"key": key, "label": key, "value_usd": 0.0, "counted": counted, "as_of": None, "source": "stub",
            "warnings": list(warnings), "detail": detail or {}}


def _composer(*comps):
    def compose(_portfolio):
        cs = list(comps) or [_comp("wallet_tokens"), _comp("hyperliquid")]
        if not any(c["key"] == "hyperliquid" for c in cs):
            cs.append(_comp("hyperliquid"))
        return {"status": "ok", "total_usd": 2200.0, "components": cs, "warnings": [], "as_of": {}}
    return compose


def _run(portfolio, wallets=(A, B), composer=None):
    ss.take_portfolio_snapshot(lambda **_: portfolio, list(wallets), compose_total_fn=composer or _composer())
    (row,) = _rows(portfolio_db.get_db_path(), "portfolio_total_snapshots")
    detail = json.loads(row["detail_json"]) if row["detail_json"] else None
    return row, detail


def _history(wallet=A, contract=TOKEN, balance=1000.0):
    ts = (datetime.utcnow() - timedelta(days=1)).isoformat()
    sid = portfolio_db.create_portfolio_snapshot(wallet, 1, timestamp=ts)
    portfolio_db.insert_token_snapshot(sid, {"timestamp": ts, "wallet": wallet, "chain": "Base", "symbol": "PLAZM",
                                             "token_address": contract, "balance": balance, "price_usd": 0.04,
                                             "value_usd": balance * 0.04}, 1)


def _lp_history(position_id, wallet=A, token0="WETH", token1="USDC", protocol="uniswap_v3", chain="base",
                days_ago=1.0):
    ts = (datetime.utcnow() - timedelta(days=days_ago)).isoformat()
    conn = sqlite3.connect(portfolio_db.get_db_path())
    conn.execute("INSERT INTO lp_snapshots (snapshot_id, user_id, timestamp, wallet, chain, protocol, position_id, "
                 "token0, token1, value_usd) VALUES (1, 1, ?, ?, ?, ?, ?, ?, ?, 500.0)",
                 (ts, wallet, chain, protocol, str(position_id), token0, token1))
    conn.commit()
    conn.close()


def _no_addresses(notes):
    text = " ".join(notes)
    assert not EVM.search(text), text
    assert SOL not in text, text


# ── API failures ───────────────────────────────────────────────────────────

def test_api_failures_become_sentences_with_labels(dbpath):
    _lp_history(4242, wallet=B, token0="WETH", token1="USDC", days_ago=3)
    _lp_history(4242, wallet=B, token0="cbBTC", token1="USDC", protocol="aerodrome_slipstream", days_ago=1)
    failures = [f"zerion:{A}", f"aave_enrich:base:{B[:8]}", "lp:4242", "lp:999", f"other:{C}"]
    row, detail = _run(_portfolio(api_failures=failures))
    assert row["status"] == "partial"
    assert detail["run_notes"] == [
        "Zerion: tokens and positions for Desk Hot didn't load",
        "Aave details didn't load on base (Vault Cold)",
        "LP position #4242 didn't load (cbBTC/USDC, aerodrome_slipstream on base, Vault Cold)",
        "LP position #999 didn't load",
        "Data didn't load: other:a wallet",
    ]
    _no_addresses(detail["run_notes"])


def test_zerion_not_configured_and_token_chain_failures(dbpath):
    _, detail = _run(_portfolio(api_failures=["zerion:not_configured", "tokens:arbitrum"]))
    assert detail["run_notes"] == ["Zerion isn't set up (no API key), so wallet tokens weren't read",
                                   "Token balances didn't load (arbitrum)"]


def test_ambiguous_aave_prefix_names_no_wallet(dbpath, monkeypatch):
    twin = "0x" + "a1" * 3 + "ff" * 17                                 # same first 8 characters as A
    p = _portfolio(api_failures=[f"aave_enrich:arbitrum:{A[:8]}"])
    p["wallet_labels"][twin] = "Twin"
    _, detail = _run(p)
    assert detail["run_notes"] == ["Aave details didn't load on arbitrum (a wallet)"]


def test_unlabeled_wallet_reads_by_its_last_four_characters(dbpath):
    p = _portfolio(api_failures=[f"zerion:{C}", f"zerion:{B}"])
    p["wallet_labels"][C] = C[:10] + "..."                    # get_portfolio_data's stand-in for no label
    del p["wallet_labels"][B]                                  # and an address it doesn't know at all
    _, detail = _run(p)
    assert detail["run_notes"] == [f"Zerion: tokens and positions for unlabeled wallet …{C[-4:]} didn't load",
                                   f"Zerion: tokens and positions for unlabeled wallet …{B[-4:]} didn't load"]
    assert C[:10] not in " ".join(detail["run_notes"])


def test_unlabeled_solana_and_bare_hex_addresses_are_masked(dbpath, monkeypatch):
    sol2 = "SynthUnlabeledSol" + "4" * 27
    real = ss.insert_token_snapshot

    def boom(snapshot_id, data, user_id=1):
        if data["wallet"] == B:
            raise RuntimeError(f"bad rows for {sol2} and {'d4' * 20}")
        return real(snapshot_id, data, user_id)

    monkeypatch.setattr(ss, "insert_token_snapshot", boom)
    p = _portfolio()
    p["wallet_labels"][sol2] = sol2[:10] + "..."
    _, detail = _run(p)
    assert detail["run_notes"] == [f"Vault Cold: didn't save (RuntimeError: bad rows for unlabeled wallet …{sol2[-4:]} "
                                   f"and a wallet)"]


# ── custom tokens and wallet rows ──────────────────────────────────────────

def test_held_custom_token_read_failure_is_named(dbpath):
    _history()
    failed = {"chain": "Base", "symbol": "PLAZM", "balance": None, "value_usd": 0.0, "price_usd": 0.04,
              "contract": TOKEN, "wallet": A, "source": "custom", "balance_failed": True}
    row, detail = _run(_portfolio(failed))
    assert row["status"] == "partial"
    assert detail["run_notes"] == ["PLAZM on Base: balance read failed (Desk Hot)"]


def test_bittensor_wallet_unavailable_is_named_with_its_reason(dbpath):
    bt = {"wallets": {SOL: {"state": "unavailable", "reason": "Taostats data over 24 h old"}}}
    row, detail = _run(_portfolio(bittensor=bt), wallets=(A, B, SOL))
    assert (row["wallets_total"], row["wallets_completed"]) == (3, 2)
    assert detail["run_notes"] == ["Sol Main: Bittensor data unavailable (Taostats data over 24 h old)"]


def test_wallet_row_error_is_named_without_addresses(dbpath, monkeypatch):
    real = ss.insert_token_snapshot

    def boom(snapshot_id, data, user_id=1):
        if data["wallet"] == B:
            raise RuntimeError(f"disk full writing {B} and {C}")
        return real(snapshot_id, data, user_id)

    monkeypatch.setattr(ss, "insert_token_snapshot", boom)
    row, detail = _run(_portfolio())
    assert row["wallets_completed"] == 1
    assert detail["run_notes"] == ["Vault Cold: didn't save (RuntimeError: disk full writing Vault Cold and a wallet)"]
    _no_addresses(detail["run_notes"])


# ── TxFlow and Hyperliquid ─────────────────────────────────────────────────

def test_hyperliquid_not_counted_with_its_last_error(dbpath):
    hl = _comp("hyperliquid", counted=False,
               warnings=["Hyperliquid loading", f"last Hyperliquid refresh failed: HTTP 429 for {A}"])
    row, detail = _run(_portfolio(), composer=_composer(_comp("wallet_tokens"), hl))
    assert row["hl_counted"] == 0
    assert detail["run_notes"] == ["Hyperliquid not counted: no Hyperliquid reading yet "
                                   "(last refresh failed: HTTP 429 for Desk Hot)"]


def test_txflow_wallets_not_read_are_listed(dbpath):
    tx = _comp("txflow", counted=True, detail={"wallets": [{"label": "TxFlow Main", "counted": False},
                                                           {"label": "TxFlow Alt", "counted": True}],
                                               "unread": 1, "expected": 2})
    row, detail = _run(_portfolio(), composer=_composer(_comp("wallet_tokens"), tx))
    assert row["status"] == "partial"
    assert detail["run_notes"] == ["TxFlow not read for TxFlow Main"]


def test_txflow_never_read(dbpath):
    tx = _comp("txflow", counted=False, warnings=["TxFlow loading"], detail={"wallets": [], "unread": 0})
    row, detail = _run(_portfolio(), composer=_composer(_comp("wallet_tokens"), tx))
    assert row["status"] == "partial" and detail["run_notes"] == ["TxFlow not counted: no TxFlow reading yet"]


# ── storage ────────────────────────────────────────────────────────────────

def test_clean_run_stores_the_composed_result_unchanged(dbpath):
    composer = _composer()
    row, detail = _run(_portfolio(), composer=composer)
    assert row["status"] == "completed" and detail == composer(None)
    assert "run_notes" not in detail


def test_notes_sit_beside_the_composed_result(dbpath):
    composer = _composer()
    _, detail = _run(_portfolio(api_failures=["lp:7"]), composer=composer)
    expected = dict(composer(None), run_notes=["LP position #7 didn't load"])
    assert detail == expected


def test_composer_failure_keeps_the_notes(dbpath):
    def broken(_portfolio):
        raise TypeError("bad part")
    ss.take_portfolio_snapshot(lambda **_: _portfolio(api_failures=["lp:7"]), [A, B], compose_total_fn=broken)
    (row,) = _rows(dbpath, "portfolio_total_snapshots")
    assert row["status"] == "failed" and row["error"] == "TypeError: bad part"
    assert json.loads(row["detail_json"]) == {"run_notes": ["LP position #7 didn't load"]}


def test_statuses_and_values_match_a_run_without_notes(dbpath, monkeypatch):
    p = _portfolio(api_failures=["lp:7"])
    _run(p)
    with_notes = _rows(dbpath, "portfolio_total_snapshots")[0]
    snaps_with = [(r["wallet"], r["status"], r["total_value_usd"]) for r in _rows(dbpath, "portfolio_snapshots")]
    conn = sqlite3.connect(dbpath)
    conn.execute("DELETE FROM portfolio_total_snapshots")
    conn.execute("DELETE FROM portfolio_snapshots")
    conn.execute("DELETE FROM token_snapshots")
    conn.commit()
    conn.close()
    monkeypatch.setattr(ss, "_run_notes", lambda *a, **k: [])
    monkeypatch.setattr(ss, "_component_notes", lambda *a, **k: [])
    _run(p)
    without = _rows(dbpath, "portfolio_total_snapshots")[0]
    snaps_without = [(r["wallet"], r["status"], r["total_value_usd"]) for r in _rows(dbpath, "portfolio_snapshots")]
    for key in ("status", "total_usd", "hl_counted", "wallets_total", "wallets_completed", "warning_count",
                "snapshot_total_usd"):
        assert with_notes[key] == without[key], key
    assert snaps_with == snaps_without


def test_note_building_never_fails_the_run(dbpath, monkeypatch):
    monkeypatch.setattr(ss, "_labeler", lambda p: (_ for _ in ()).throw(ValueError("labels broke")))
    row, detail = _run(_portfolio(api_failures=["lp:7"]))
    assert row["status"] == "partial" and row["total_usd"] == 2200.0
    assert detail["run_notes"] == ["Couldn't record why (ValueError)"]


def test_component_notes_failing_never_fails_the_row(dbpath, monkeypatch):
    monkeypatch.setattr(ss, "_component_notes", lambda *a: (_ for _ in ()).throw(KeyError("comps")))
    row, detail = _run(_portfolio(api_failures=["lp:7"]))
    assert (row["status"], row["total_usd"], row["error"]) == ("partial", 2200.0, None)
    assert detail["run_notes"] == ["LP position #7 didn't load"]


def test_notes_are_capped(dbpath):
    _, detail = _run(_portfolio(api_failures=[f"lp:{i}" for i in range(30)]))
    notes = detail["run_notes"]
    assert len(notes) == 20 and notes[-1] == "and 11 more" and notes[0] == "LP position #0 didn't load"


def test_long_notes_are_cut(dbpath):
    _, detail = _run(_portfolio(api_failures=["other:" + "x" * 500]))
    (note,) = detail["run_notes"]
    assert len(note) == 240 and note.endswith("…")
