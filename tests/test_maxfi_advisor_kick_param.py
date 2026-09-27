"""GET /api/maxfi/advisor?kick=0 (Dashboard redesign): skips the three on-view
background kicks (metrics refresh, ledger backfill, token-daily); any other
value, or none, behaves as before.

metrics_db / client fixtures copied from tests/test_metrics_auto_refresh.py
(shared-cache sqlite, monkeypatched get_connection). The three kick helpers
are replaced by recorders, so no thread starts and nothing touches the
network."""
import sqlite3
import uuid

import pytest

import maxfi_schema
import src.storage.portfolio_db as portfolio_db
import web_portfolio as wp

KICK_KEYS = {"metrics_refresh_kicked": [], "ledger_backfill_kicked": [], "ledger_backfill_kick_reasons": {},
             "token_daily_kicked": [], "token_daily_kick_reasons": {}}


@pytest.fixture
def metrics_db(monkeypatch):
    uri = f"file:advisor_kick_param_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
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


@pytest.fixture
def kicks(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(wp, "ADVISOR_SETTINGS_PATH", str(tmp_path / "advisor_settings.json"))
    monkeypatch.setattr(wp, "_maybe_kick_metrics_auto_refresh", lambda: calls.append("metrics") or [])
    monkeypatch.setattr(wp, "_maybe_kick_ledger_auto_backfill", lambda now_utc: calls.append("ledger") or ([], {}))
    monkeypatch.setattr(wp, "_maybe_kick_token_daily_auto_refresh",
                        lambda now_utc: calls.append("token_daily") or ([], {}))
    return calls


def test_t1_kick_0_skips_every_kick(client, metrics_db, kicks):
    r = client.get("/api/maxfi/advisor?kick=0")
    assert r.status_code == 200
    body = r.get_json()
    assert kicks == []
    assert {k: body[k] for k in KICK_KEYS} == KICK_KEYS
    assert "positions" in body and "entry_candidates" in body


def test_t2_no_param_kicks_each_once(client, metrics_db, kicks):
    assert client.get("/api/maxfi/advisor").status_code == 200
    assert sorted(kicks) == ["ledger", "metrics", "token_daily"]


@pytest.mark.parametrize("value", ["1", "false"])
def test_t3_other_values_kick_as_before(client, metrics_db, kicks, value):
    assert client.get(f"/api/maxfi/advisor?kick={value}").status_code == 200
    assert sorted(kicks) == ["ledger", "metrics", "token_daily"]
    assert client.get(f"/api/maxfi/advisor?kick={value}").status_code == 200
    assert sorted(kicks) == ["ledger", "ledger", "metrics", "metrics", "token_daily", "token_daily"]
