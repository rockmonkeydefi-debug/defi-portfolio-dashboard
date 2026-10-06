"""Landing 12: the off-server copy line on Settings -> Backup & Security
(static/settings.js) matches the routes and status fields the server has.
Reads the page source; no browser."""

import os
import re

import web_portfolio as wp
from src.storage import offsite_backup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = open(os.path.join(ROOT, "static", "settings.js"), encoding="utf-8").read()


def _routes():
    out = {}
    for rule in wp.app.url_map.iter_rules():
        out.setdefault(rule.rule, set()).update(rule.methods)
    return out


def test_the_page_calls_only_offsite_routes_that_exist():
    routes = _routes()
    called = set(re.findall(r"'(/api/backup/offsite[a-z/-]*)'", PAGE))
    assert called == {"/api/backup/offsite", "/api/backup/offsite/run"}
    assert "GET" in routes["/api/backup/offsite"]
    assert "POST" in routes["/api/backup/offsite/run"]


def test_the_page_sends_the_header_the_server_expects():
    assert f"const OFFSITE_HEADERS = {{ '{wp._BACKUP_HEADER}': '1' }};" in PAGE


def test_the_page_reads_only_fields_the_status_has():
    start = PAGE.index("function offsiteLine(st)")
    end = PAGE.index("function BackupSection()")
    used = set(re.findall(r"\bst\.([a-z_]+)", PAGE[start:end]))
    assert used and used <= set(offsite_backup.status())


def test_the_line_sits_in_the_backup_card():
    section = PAGE[PAGE.index("function BackupSection()"):]
    assert "React.createElement(OffsiteBackupLine)" in section
    assert "window.location = '/api/backup/db'" in section            # Export DB stays
