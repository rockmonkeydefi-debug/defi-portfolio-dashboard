"""Phase E v2 C2: metrics-refresh extraction + the on-view auto-refresh
trigger. _run_metrics_refresh is the extracted, Flask-context-free body of
POST /api/maxfi/metrics-refresh/<chain> - the extraction-equivalence proof
lives in tests/test_maxfi_metrics_refresh.py (all 11 of its route-level
tests still pass unmodified against the extracted body). This file covers
what's NEW: the busy lock, the spawn seam, and
_maybe_kick_metrics_auto_refresh's staleness logic, plus the advisor
route's one additive response key.

Same shared-cache sqlite / monkeypatched get_connection pattern as
tests/test_maxfi_metrics_refresh.py and tests/test_maxfi_advisor.py (the
route/helper opens and closes its OWN connection per call - a bare
":memory:" would lose state the instant that connection closed). No
network, no real threads - _spawn_metrics_refresh_thread is monkeypatched
to a recorder in every trigger test. ADVISOR_SETTINGS_PATH is monkeypatched
to a tmp_path file in every test that reaches _advisor_settings(), so a
stray real settings file can never leak into these tests.
"""
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import pytest

import maxfi_schema
import src.storage.portfolio_db as portfolio_db

WALLET = "0x" + "d" * 40


@pytest.fixture
def metrics_db(monkeypatch):
    uri = f"file:metrics_auto_refresh_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    keepalive.row_factory = sqlite3.Row
    maxfi_schema.ensure_maxfi_tables(keepalive)

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    yield keepalive
    keepalive.close()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _default_settings_path(monkeypatch, tmp_path):
    """Points ADVISOR_SETTINGS_PATH at a not-yet-existing tmp file, so
    _advisor_settings() falls back to ADVISOR_SETTINGS_DEFAULTS
    deterministically (metrics_staleness_hours=12.0,
    metrics_auto_refresh_enabled=True) regardless of any real settings
    file on disk."""
    monkeypatch.setattr(wp, "ADVISOR_SETTINGS_PATH", str(tmp_path / "advisor_settings.json"))


def _seed_metrics_row(db, chain, pool_address, fetched_at):
    db.execute(
        """
        INSERT INTO maxfi_pool_metrics (
          chain, pool_address, price_usd, liquidity_usd, volume_h24,
          volume_h6, volume_h1, price_change_h24, fetched_at
        ) VALUES (?, ?, 1.0, 1000.0, 100.0, 10.0, 1.0, 0.5, ?)
        """,
        (chain, pool_address, fetched_at),
    )
    db.commit()


# ── (a) busy lock ─────────────────────────────────────────────────────────

def test_run_metrics_refresh_409s_while_lock_held_then_recovers(metrics_db, tmp_path, monkeypatch):
    _default_settings_path(monkeypatch, tmp_path)
    assert wp._METRICS_REFRESH_LOCK.acquire(blocking=False)
    try:
        # The 409 return happens BEFORE the lock is even attempted inside
        # _run_metrics_refresh (acquire fails immediately) - nothing for
        # that call to release, so the lock is still held by this test
        # right here.
        payload, status = wp._run_metrics_refresh("base")
        assert status == 409
        assert payload["error"] == "RefreshBusy"
        assert wp._METRICS_REFRESH_LOCK.locked()
    finally:
        wp._METRICS_REFRESH_LOCK.release()

    # Lock released - a normal call must no longer 409. No pools seeded,
    # so this exercises the ordinary no_pools early-return path.
    payload2, status2 = wp._run_metrics_refresh("base")
    assert status2 == 200
    assert payload2.get("note") == "no_pools"


# ── (b) trigger: all fresh ────────────────────────────────────────────────

def test_trigger_all_fresh_returns_empty_and_does_not_spawn(metrics_db, tmp_path, monkeypatch):
    _default_settings_path(monkeypatch, tmp_path)
    recorder = []
    monkeypatch.setattr(wp, "_spawn_metrics_refresh_thread", lambda chains: recorder.append(chains))
    now = datetime.now(timezone.utc).isoformat()
    _seed_metrics_row(metrics_db, "base", "0xpoola", now)
    _seed_metrics_row(metrics_db, "robinhood", "0xpoolb", now)

    kicked = wp._maybe_kick_metrics_auto_refresh()
    assert kicked == []
    assert recorder == []


# ── (c) trigger: one stale ───────────────────────────────────────────────

def test_trigger_one_stale_chain_kicks_only_that_chain(metrics_db, tmp_path, monkeypatch):
    _default_settings_path(monkeypatch, tmp_path)
    recorder = []
    monkeypatch.setattr(wp, "_spawn_metrics_refresh_thread", lambda chains: recorder.append(chains))
    now = datetime.now(timezone.utc)
    _seed_metrics_row(metrics_db, "base", "0xpoola", now.isoformat())
    _seed_metrics_row(metrics_db, "robinhood", "0xpoolb", (now - timedelta(days=2)).isoformat())

    kicked = wp._maybe_kick_metrics_auto_refresh()
    assert kicked == ["robinhood"]
    assert recorder == [["robinhood"]]


# ── (d) trigger: chain absent from maxfi_pool_metrics entirely ──────────

def test_trigger_chain_with_no_rows_at_all_is_kicked(metrics_db, tmp_path, monkeypatch):
    _default_settings_path(monkeypatch, tmp_path)
    recorder = []
    monkeypatch.setattr(wp, "_spawn_metrics_refresh_thread", lambda chains: recorder.append(chains))
    now = datetime.now(timezone.utc).isoformat()
    _seed_metrics_row(metrics_db, "base", "0xpoola", now)
    # No maxfi_pool_metrics rows for "robinhood" at all.

    kicked = wp._maybe_kick_metrics_auto_refresh()
    assert kicked == ["robinhood"]
    assert recorder == [["robinhood"]]


# ── (e) trigger: auto-refresh disabled ───────────────────────────────────

def test_trigger_disabled_returns_empty_even_with_stale_data(metrics_db, tmp_path, monkeypatch):
    settings_path = tmp_path / "advisor_settings.json"
    settings_path.write_text(json.dumps({"metrics_auto_refresh_enabled": False}))
    monkeypatch.setattr(wp, "ADVISOR_SETTINGS_PATH", str(settings_path))
    recorder = []
    monkeypatch.setattr(wp, "_spawn_metrics_refresh_thread", lambda chains: recorder.append(chains))
    now = datetime.now(timezone.utc)
    _seed_metrics_row(metrics_db, "base", "0xpoola", (now - timedelta(days=5)).isoformat())
    # "robinhood" absent entirely too - would also be stale if enabled.

    kicked = wp._maybe_kick_metrics_auto_refresh()
    assert kicked == []
    assert recorder == []


# ── (f) advisor GET carries metrics_refresh_kicked either way ───────────

def test_advisor_get_reports_kicked_chains_when_present(client, metrics_db, monkeypatch):
    monkeypatch.setattr(wp, "_maybe_kick_metrics_auto_refresh", lambda: ["robinhood"])
    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    assert r.get_json()["metrics_refresh_kicked"] == ["robinhood"]


def test_advisor_get_reports_empty_kicked_list_when_nothing_kicked(client, metrics_db, monkeypatch):
    monkeypatch.setattr(wp, "_maybe_kick_metrics_auto_refresh", lambda: [])
    r = client.get("/api/maxfi/advisor")
    assert r.status_code == 200
    assert r.get_json()["metrics_refresh_kicked"] == []
