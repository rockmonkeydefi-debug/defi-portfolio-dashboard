"""Tests for GET/PUT /api/wallets - the visible/hidden fix and the new
independent maxfi flag.

wallet_config.json is a JSON file, not a SQLite table (see load_wallet_config/
save_wallet_config in web_portfolio.py). WALLET_CONFIG_FILE is monkeypatched to
a per-test tmp path rather than the loader itself, so save_wallet_config's real
file round-trip is exercised, not just an in-memory stub. No network calls.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern in the
other MaxFi/route test files) so no thread starts.
"""
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import pytest

WALLET = "0x" + "a" * 40


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    monkeypatch.setattr(wp, "WALLET_CONFIG_FILE", str(tmp_path / "wallet_config.json"))
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def _write_config(entries):
    wp.save_wallet_config(entries)


def _get_wallet(client, address):
    body = client.get("/api/wallets").get_json()
    for w in body["wallets"]:
        if w["address"] == address:
            return w
    return None


# ── (a)/(b): api_get_wallets derives visible/maxfi, never breaks `hidden` ───

def test_get_wallets_defaults_visible_true_and_maxfi_false_for_bare_entry(client):
    """The pre-existing-file case: an entry written before this block existed
    has neither key - both derived fields must fall back sanely."""
    _write_config({WALLET: {"label": "Main"}})

    w = _get_wallet(client, WALLET)

    assert w["visible"] is True
    assert w["maxfi"] is False
    assert w["hidden"] is False  # the existing key, additive-only, unchanged


def test_get_wallets_reports_visible_false_for_entry_stored_hidden_true(client):
    _write_config({WALLET: {"label": "Main", "hidden": True}})

    w = _get_wallet(client, WALLET)

    assert w["visible"] is False
    assert w["hidden"] is True


# ── (c): the regression test for the broken Visible toggle ──────────────────

def test_put_visible_false_persists_as_hidden_true_and_get_reflects_it(client):
    _write_config({WALLET: {"label": "Main"}})

    r = client.put(f"/api/wallets/{WALLET}", json={"visible": False})
    assert r.status_code == 200

    w = _get_wallet(client, WALLET)
    assert w["visible"] is False
    assert w["hidden"] is True


# ── (d): the exact call the settings checkbox will make ──────────────────────

def test_put_maxfi_true_alone_succeeds_not_nothing_to_update(client):
    """Before this block, {"maxfi": true} alone carried no label, no role, and
    no `hidden` - the old guard (`if not label and not role and hidden is
    None`) would have rejected this as 400 'Nothing to update'."""
    _write_config({WALLET: {"label": "Main"}})

    r = client.put(f"/api/wallets/{WALLET}", json={"maxfi": True})

    assert r.status_code == 200
    assert r.get_json() == {"success": True}
    w = _get_wallet(client, WALLET)
    assert w["maxfi"] is True


# ── (e): maxfi and visible/hidden are independent ────────────────────────────

def test_setting_maxfi_does_not_alter_hidden_or_visible(client):
    _write_config({WALLET: {"label": "Main"}})

    client.put(f"/api/wallets/{WALLET}", json={"maxfi": True})

    w = _get_wallet(client, WALLET)
    assert w["maxfi"] is True
    assert w["visible"] is True
    assert w["hidden"] is False


def test_setting_visible_does_not_alter_maxfi(client):
    _write_config({WALLET: {"label": "Main", "maxfi": True}})

    client.put(f"/api/wallets/{WALLET}", json={"visible": False})

    w = _get_wallet(client, WALLET)
    assert w["visible"] is False
    assert w["maxfi"] is True  # untouched by the visible-only PUT


# ── (f): bools only - strings and integers rejected ──────────────────────────

def test_put_visible_as_string_true_is_rejected(client):
    _write_config({WALLET: {"label": "Main"}})

    r = client.put(f"/api/wallets/{WALLET}", json={"visible": "true"})

    assert r.status_code == 400
    assert "visible" in r.get_json()["error"]


def test_put_maxfi_as_integer_one_is_rejected(client):
    _write_config({WALLET: {"label": "Main"}})

    r = client.put(f"/api/wallets/{WALLET}", json={"maxfi": 1})

    assert r.status_code == 400
    assert "maxfi" in r.get_json()["error"]


# ── (g): visible and hidden together is contradictory input ─────────────────

def test_put_both_visible_and_hidden_is_rejected(client):
    _write_config({WALLET: {"label": "Main"}})

    r = client.put(f"/api/wallets/{WALLET}", json={"visible": True, "hidden": False})

    assert r.status_code == 400
    assert "both" in r.get_json()["error"]
