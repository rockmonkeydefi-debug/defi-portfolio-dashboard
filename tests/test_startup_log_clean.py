"""Startup log stays clean (Landing 13).

The module-level startup steps in web_portfolio.py each catch their own errors
and print one line, so a broken step fails quietly on every boot. Three did:
a date normalisation that called normalize_date before its definition (removed
in Landing 8d), a scanner_signals rebuild whose INSERT left out a column, and a
strategy prompt read that called _get_scanner_prompt_path before its definition
(both removed in Landing 13).

Each test boots the module in a fresh interpreter on an empty temporary volume,
then again on the database the first boot made, with thread starts disabled
(the conftest pattern) and every config path inside the temporary folder.
"""
import os
import sqlite3
import subprocess
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_BOOT = (
    "import threading\n"
    "threading.Thread.start = lambda self, *a, **k: None\n"
    "import web_portfolio\n"
)

# A name used before its definition, and an INSERT whose value count does not
# match its table: the two ways the removed steps failed.
_BAD = ("is not defined", "values were supplied")


def _boot(tmp_path):
    env = dict(os.environ)
    env["RAILWAY_VOLUME_MOUNT_PATH"] = str(tmp_path / "vol")
    env["DOTENV_PATH"] = str(tmp_path / ".env")
    env["WALLET_CONFIG_PATH"] = str(tmp_path / "wallet_config.json")
    env["PYTHONPATH"] = _ROOT + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", _BOOT],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=300,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-4000:]
    return out


@pytest.fixture(scope="module")
def boots(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("startup")
    first = _boot(tmp_path)
    second = _boot(tmp_path)
    return tmp_path, first, second


def test_both_boots_reach_the_end_of_startup(boots):
    _, first, second = boots
    for log in (first, second):
        assert "[startup] db path:" in log


@pytest.mark.parametrize("which", [1, 2])
def test_no_startup_step_fails_on_an_undefined_name_or_a_column_count(boots, which):
    log = boots[which]
    bad = [ln for ln in log.splitlines() if any(b in ln for b in _BAD)]
    assert bad == []


def test_removed_steps_leave_nothing_behind(boots):
    tmp_path, _, _ = boots
    conn = sqlite3.connect(str(tmp_path / "vol" / "portfolio.db"))
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "scanner_signals" in tables
        assert "scanner_signals_new" not in tables
        cols = [r[1] for r in conn.execute("PRAGMA table_info(scanner_signals)")]
        assert "pair_key" in cols
        # The seeded strategy's prompt stays empty, as it always was.
        rows = conn.execute("SELECT name, ai_prompt FROM strategies").fetchall()
        assert rows == [("Mayne — OB/FVG System", "")]
    finally:
        conn.close()
