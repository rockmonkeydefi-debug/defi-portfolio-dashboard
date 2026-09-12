"""GET/POST /api/settings/advisor - LP Advisor Phase B settings storage
(ADVISOR_SETTINGS_PATH). Commit 1 of the Phase E v2 session: settings-only,
no consumer wiring yet. Same invoke-the-undecorated-view pattern as
tests/test_display_prefs.py (the closest existing precedent: another
file-backed, DB-free settings store with the same defaults-merge shape),
against a tmp_path-patched ADVISOR_SETTINGS_PATH. No network, no DB.
"""
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start


def _get():
    with wp.app.test_request_context('/api/settings/advisor', method='GET'):
        resp = wp.api_advisor_settings_get()
    return resp.get_json()


def _post(json_body):
    with wp.app.test_request_context('/api/settings/advisor', method='POST', json=json_body):
        resp = wp.api_advisor_settings_save()
    if isinstance(resp, tuple):
        body, status = resp[0], resp[1]
    else:
        body, status = resp, 200
    return status, body.get_json()


def _patch(monkeypatch, tmp_path):
    path = str(tmp_path / "advisor_settings.json")
    monkeypatch.setattr(wp, "ADVISOR_SETTINGS_PATH", path)
    return path


# ── (a) GET with no file ─────────────────────────────────────────────────

def test_get_with_no_file_returns_exact_defaults(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    settings = _get()
    assert settings == wp.ADVISOR_SETTINGS_DEFAULTS


# ── (b) POST merges into defaults, GET reflects it ───────────────────────

def test_post_valid_values_persist_and_get_reflects_them(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    status, saved = _post({"total_capital_usd": 50000, "maxfi_exposure_cap_pct": 25})
    assert status == 200
    assert saved["total_capital_usd"] == 50000.0
    assert saved["maxfi_exposure_cap_pct"] == 25.0
    # Unspecified keys still at defaults, in the SAME response.
    assert saved["metrics_staleness_hours"] == 12.0
    assert saved["metrics_auto_refresh_enabled"] is True

    settings = _get()
    assert settings["total_capital_usd"] == 50000.0
    assert settings["maxfi_exposure_cap_pct"] == 25.0
    assert settings["metrics_staleness_hours"] == 12.0
    assert settings["metrics_auto_refresh_enabled"] is True


# ── (c) partial POSTs preserve previously-saved OTHER keys ───────────────

def test_partial_posts_preserve_other_previously_saved_keys(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    status, _ = _post({"total_capital_usd": 100000})
    assert status == 200
    status, _ = _post({"maxfi_exposure_cap_pct": 40})
    assert status == 200

    settings = _get()
    assert settings["total_capital_usd"] == 100000.0
    assert settings["maxfi_exposure_cap_pct"] == 40.0


# ── (d) bad type -> 400, file unchanged ──────────────────────────────────

def test_post_non_numeric_total_capital_rejected_and_file_unchanged(tmp_path, monkeypatch):
    path = _patch(monkeypatch, tmp_path)
    status, _ = _post({"total_capital_usd": 5000})
    assert status == 200
    before = _get()

    status, body = _post({"total_capital_usd": "abc"})
    assert status == 400
    assert "total_capital_usd" in body["error"]

    after = _get()
    assert after == before


# ── (e) exposure cap bounds ───────────────────────────────────────────────

def test_post_exposure_cap_zero_rejected(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    status, body = _post({"maxfi_exposure_cap_pct": 0})
    assert status == 400
    assert "maxfi_exposure_cap_pct" in body["error"]


def test_post_exposure_cap_over_100_rejected(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    status, body = _post({"maxfi_exposure_cap_pct": 150})
    assert status == 400
    assert "maxfi_exposure_cap_pct" in body["error"]


# ── (f) auto-refresh must be a real bool ─────────────────────────────────

def test_post_auto_refresh_string_true_rejected(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    status, body = _post({"metrics_auto_refresh_enabled": "true"})
    assert status == 400
    assert "metrics_auto_refresh_enabled" in body["error"]


def test_post_auto_refresh_real_bool_accepted(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    status, saved = _post({"metrics_auto_refresh_enabled": False})
    assert status == 200
    assert saved["metrics_auto_refresh_enabled"] is False


# ── (g) unknown key -> 400 with valid_keys ───────────────────────────────

def test_post_unknown_key_rejected_with_valid_keys(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    status, body = _post({"unknown_key": 1})
    assert status == 400
    assert "unknown_key" in body["error"]
    assert body["valid_keys"] == sorted(wp.ADVISOR_SETTINGS_DEFAULTS)


# ── (h) explicit null clears total_capital_usd ───────────────────────────

def test_post_null_total_capital_clears_a_prior_real_value(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    status, _ = _post({"total_capital_usd": 75000})
    assert status == 200
    assert _get()["total_capital_usd"] == 75000.0

    status, saved = _post({"total_capital_usd": None})
    assert status == 200
    assert saved["total_capital_usd"] is None
    assert _get()["total_capital_usd"] is None


# ── invalid payload shape ─────────────────────────────────────────────────

def test_post_non_dict_payload_rejected(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    status, body = _post([1, 2, 3])
    assert status == 400
    assert body["error"] == "Invalid payload"
