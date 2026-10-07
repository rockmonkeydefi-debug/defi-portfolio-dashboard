"""Landing 14: the page side of the new-build notice. templates/index.html
carries the build it was rendered with in a playbook-build meta, and
static/app.js compares it with GET /api/build. These tests read the page
source and the rendered page: the meta exists and matches the route, every
static tag carries the same build, and the names app.js uses exist.

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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def test_page_meta_and_every_static_tag_carry_the_build(client):
    html = client.get("/").get_data(as_text=True)
    m = re.search(r'<meta name="playbook-build" content="([^"]*)">', html)
    assert m, "playbook-build meta missing from index.html"
    assert m.group(1) == wp._static_version
    assert m.group(1) == client.get("/api/build").get_json()["build"]
    versions = set(re.findall(r'/static/[^"?]+\?v=([^"]+)"', html))
    assert versions == {wp._static_version}


def test_app_reads_the_meta_and_polls_the_route():
    src = read("static", "app.js")
    assert "meta[name=\"playbook-build\"]" in src
    assert "fetch('/api/build'" in src
    rules = {r.rule for r in wp.app.url_map.iter_rules()}
    assert "/api/build" in rules


def test_notice_offers_a_reload_and_never_reloads_by_itself():
    src = read("static", "app.js")
    # Exactly one reload call, and it sits in the notice's button handler.
    assert src.count("location.reload(") == 1
    assert "onClick: () => window.location.reload()" in src
