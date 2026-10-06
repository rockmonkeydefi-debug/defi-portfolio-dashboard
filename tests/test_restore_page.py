"""Landing 11: the Settings restore panel (static/settings.js) matches the
restore routes it calls. Reads the page source; no browser."""

import os
import re

import web_portfolio as wp
from src.storage import db_restore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = open(os.path.join(ROOT, "static", "settings.js"), encoding="utf-8").read()


def _routes():
    out = {}
    for rule in wp.app.url_map.iter_rules():
        out.setdefault(rule.rule, set()).update(rule.methods)
    return out


def test_the_page_calls_only_restore_routes_that_exist():
    routes = _routes()
    called = set(re.findall(r"'(/api/backup/restore[a-z/-]*)'", PAGE))
    assert called == {"/api/backup/restore", "/api/backup/restore/upload", "/api/backup/restore/server-copy",
                      "/api/backup/restore/apply", "/api/backup/restore/discard"}
    assert "GET" in routes["/api/backup/restore"]
    for path in called - {"/api/backup/restore"}:
        assert "POST" in routes[path], path


def test_the_page_sends_the_header_and_word_the_server_expects():
    assert f"'{wp._RESTORE_HEADER}': '1'" in PAGE
    assert f"xhr.setRequestHeader('{wp._RESTORE_HEADER}', '1')" in PAGE
    assert f"const DB_RESTORE_WORD = '{db_restore.CONFIRM_WORD}';" in PAGE


def test_the_old_database_import_is_gone_from_the_page():
    assert "importFile(" not in PAGE
    assert "/api/backup/${type}" not in PAGE
    assert "'/api/backup/config', { method: 'POST'" in PAGE        # the settings import stays
    assert "window.location = '/api/backup/db'" in PAGE             # Export DB stays
