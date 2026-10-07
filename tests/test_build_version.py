"""Landing 14: the frontend build id and GET /api/build.

The build id is a hash of every file under static/ and templates/ (paths and
bytes), so it changes exactly when the frontend changes and never on a
restart alone. It is the ?v= on the page's static tags, the playbook-build
meta in index.html, and the body of GET /api/build, which an open page polls
to offer a reload when a newer build is live. The page side (the meta and
static/app.js) is tested in tests/test_build_banner_wiring.py.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import os
import re
import threading

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start


def _tree(root, files):
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


BASE = {
    "static/app.js": b"const a = 1;\n",
    "static/sub/x.css": b"body {}\n",
    "templates/index.html": b"<html></html>\n",
    "web_portfolio.py": b"print('backend')\n",
}


def _build(tmp_path, files):
    root = tmp_path / "root"
    _tree(root, files)
    return wp._frontend_build_id(str(root))


def test_same_files_give_the_same_id(tmp_path):
    a = _build(tmp_path / "a", BASE)
    b = _build(tmp_path / "b", BASE)
    assert a == b
    assert re.fullmatch(r"[0-9a-f]{12}", a)


@pytest.mark.parametrize("change", [
    {"static/app.js": b"const a = 2;\n"},          # a static file's bytes
    {"static/sub/x.css": b"body { }\n"},           # a nested static file
    {"templates/index.html": b"<html> </html>\n"},  # a template
    {"static/new.js": b""},                         # a new (empty) static file
])
def test_a_frontend_change_changes_the_id(tmp_path, change):
    before = _build(tmp_path / "a", BASE)
    after = _build(tmp_path / "b", dict(BASE, **change))
    assert before != after


def test_a_renamed_file_changes_the_id(tmp_path):
    files = dict(BASE)
    files["static/app2.js"] = files.pop("static/app.js")
    assert _build(tmp_path / "a", BASE) != _build(tmp_path / "b", files)


def test_a_backend_only_change_keeps_the_id(tmp_path):
    before = _build(tmp_path / "a", BASE)
    after = _build(tmp_path / "b", dict(BASE, **{"web_portfolio.py": b"print('changed')\n"}))
    assert before == after


def test_the_running_app_uses_the_hash_of_its_own_frontend():
    assert wp._static_version == wp._frontend_build_id(wp.app.root_path)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    return wp.app.test_client()


def _login(c):
    with c.session_transaction() as sess:
        sess["authenticated"] = True


def test_build_route_returns_the_id_and_is_never_cached(client):
    _login(client)
    r = client.get("/api/build")
    assert r.status_code == 200
    assert r.get_json() == {"build": wp._static_version}
    assert r.headers["Cache-Control"] == "no-store"


def test_build_route_sits_behind_the_login_gate(client):
    r = client.get("/api/build")
    assert r.status_code == 401
    assert "build" not in (r.get_json() or {})
