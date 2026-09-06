"""GET/POST /api/settings/display — MaxFi value-health threshold keys
(maxfi_value_band_pct / maxfi_value_danger_pct) added alongside the existing
dust_threshold/lending_threshold prefs. Same invoke-the-undecorated-view
pattern as tests/test_regime_and_settings.py's _put helper, against a
tmp_path-patched DISPLAY_PREFS_PATH. No network.
"""
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start


def _get():
    with wp.app.test_request_context('/api/settings/display', method='GET'):
        resp = wp.api_display_prefs_get()
    return resp.get_json()


def _post(json_body):
    with wp.app.test_request_context('/api/settings/display', method='POST', json=json_body):
        resp = wp.api_display_prefs_save()
    if isinstance(resp, tuple):
        body, status = resp[0], resp[1]
    else:
        body, status = resp, 200
    return status, body.get_json()


def test_get_returns_new_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(wp, "DISPLAY_PREFS_PATH", str(tmp_path / "display_prefs.json"))
    prefs = _get()
    assert prefs["maxfi_value_band_pct"] == 15.0
    assert prefs["maxfi_value_danger_pct"] == 30.0


def test_post_valid_values_persist_and_get_reflects_them(tmp_path, monkeypatch):
    monkeypatch.setattr(wp, "DISPLAY_PREFS_PATH", str(tmp_path / "display_prefs.json"))
    status, saved = _post({"maxfi_value_band_pct": 10.0, "maxfi_value_danger_pct": 25.0})
    assert status == 200
    assert saved["status"] == "success"

    prefs = _get()
    assert prefs["maxfi_value_band_pct"] == 10.0
    assert prefs["maxfi_value_danger_pct"] == 25.0


def test_post_effective_band_gte_danger_rejected_and_file_unchanged(tmp_path, monkeypatch):
    path = str(tmp_path / "display_prefs.json")
    monkeypatch.setattr(wp, "DISPLAY_PREFS_PATH", path)
    # Seed a valid saved state first.
    status, _ = _post({"maxfi_value_band_pct": 10.0, "maxfi_value_danger_pct": 25.0})
    assert status == 200
    before = _get()

    # A partial POST of band alone, made >= the ALREADY-SAVED danger (25), must be
    # rejected using the EFFECTIVE merged value, not just the posted key.
    status, body = _post({"maxfi_value_band_pct": 25.0})
    assert status == 400
    assert "maxfi_value_band_pct must be less than maxfi_value_danger_pct" in body["error"]

    after = _get()
    assert after == before
