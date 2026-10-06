"""Landing 10: backup hygiene - consistent copies of the WAL-mode database
(portfolio_db.snapshot_db, used by the daily boot backup and by Export DB),
retention of old daily copies (plan_backup_retention / prune_backups, off
unless BACKUP_RETENTION is on), and the read-only GET /api/backup/status.

Real SQLite files under tmp_path; RAILWAY_VOLUME_MOUNT_PATH points the app
at them. No network. Copies are opened with ?immutable=1 so reading them
creates no side files.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db

MB = 1024 * 1024


class _Oct6(datetime):
    """portfolio_db.datetime with utcnow fixed at 2026-10-06 01:00 UTC."""
    @classmethod
    def utcnow(cls):
        return cls(2026, 10, 6, 1, 0)


def _wal_db(path):
    """A WAL database: row 1 checkpointed into the main file, row 2 committed
    but still only in the -wal file while the returned connection stays open."""
    holder = sqlite3.connect(str(path))
    holder.execute("PRAGMA journal_mode=WAL")
    holder.execute("CREATE TABLE t (x INTEGER)")
    holder.execute("INSERT INTO t VALUES (1)")
    holder.commit()
    holder.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    holder.execute("INSERT INTO t VALUES (2)")
    holder.commit()
    return holder


def _read(path):
    return sqlite3.connect(f"file:{path}?immutable=1", uri=True)


def _rows(path):
    conn = _read(path)
    try:
        return [r[0] for r in conn.execute("SELECT x FROM t ORDER BY x")]
    finally:
        conn.close()


def _quick_check(path):
    conn = _read(path)
    try:
        return conn.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        conn.close()


def _journal_byte(path):
    """Byte 18 of the SQLite header: 1 = rollback journal (a self-contained
    file), 2 = WAL (needs its -wal file to be complete)."""
    with open(path, "rb") as f:
        return f.read(19)[18]


def _daily(day):
    return f"portfolio_backup_{day:%Y%m%d}.db"


def _days(first, last):
    d, out = first, []
    while d <= last:
        out.append(d)
        d += timedelta(days=1)
    return out


@pytest.fixture
def volume(tmp_path, monkeypatch):
    vol = tmp_path / "volume"
    vol.mkdir()
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(vol))
    monkeypatch.delenv("BACKUP_RETENTION", raising=False)
    monkeypatch.setattr(portfolio_db, "datetime", _Oct6)
    return vol


@pytest.fixture
def live_db(volume):
    holder = _wal_db(volume / "portfolio.db")
    yield holder
    holder.close()


@pytest.fixture
def container_tmp(tmp_path, monkeypatch):
    d = tmp_path / "container_tmp"
    d.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(d))
    return d


@pytest.fixture
def client(volume, monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


# ── snapshot_db ──────────────────────────────────────────────────────────────

def test_plain_copy_misses_the_wal_commit_and_snapshot_keeps_it(tmp_path):
    db = tmp_path / "portfolio.db"
    holder = _wal_db(db)
    try:
        shutil.copy2(db, tmp_path / "plain.db")
        assert _rows(tmp_path / "plain.db") == [1]            # the old Export DB method loses row 2

        size = portfolio_db.snapshot_db(str(tmp_path / "copy.db"), str(db))

        assert size == os.path.getsize(tmp_path / "copy.db")
        assert _rows(tmp_path / "copy.db") == [1, 2]
        assert _journal_byte(tmp_path / "copy.db") == 1        # one self-contained file
        assert _quick_check(tmp_path / "copy.db") == "ok"
        assert not [n for n in os.listdir(tmp_path) if ".tmp-" in n or n.startswith("copy.db-")]
    finally:
        holder.close()


def test_snapshot_does_not_wait_for_an_open_write_and_leaves_it_out(tmp_path):
    db = tmp_path / "portfolio.db"
    holder = _wal_db(db)
    writer = sqlite3.connect(str(db), timeout=0.1, isolation_level=None)
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO t VALUES (3)")
        started = time.time()
        portfolio_db.snapshot_db(str(tmp_path / "copy.db"), str(db))
        assert time.time() - started < 5
        assert _rows(tmp_path / "copy.db") == [1, 2]           # uncommitted row 3 is not in the copy
        writer.execute("COMMIT")                                # and the writer was never blocked
    finally:
        writer.close()
        holder.close()


def test_snapshot_replaces_an_older_copy_of_the_same_name(tmp_path):
    db = tmp_path / "portfolio.db"
    holder = _wal_db(db)
    try:
        (tmp_path / "copy.db").write_bytes(b"old copy")
        portfolio_db.snapshot_db(str(tmp_path / "copy.db"), str(db))
        assert _rows(tmp_path / "copy.db") == [1, 2]
    finally:
        holder.close()


def test_snapshot_failure_raises_and_leaves_nothing(tmp_path):
    bad = tmp_path / "portfolio.db"
    bad.write_bytes(b"this is not a database " * 200)
    with pytest.raises(sqlite3.DatabaseError):
        portfolio_db.snapshot_db(str(tmp_path / "copy.db"), str(bad))
    assert sorted(os.listdir(tmp_path)) == ["portfolio.db"]


# ── the daily boot backup ────────────────────────────────────────────────────

def test_daily_backup_holds_the_wal_commit_and_runs_once_a_day(volume, live_db, capsys):
    portfolio_db._backup_db_if_needed()

    copy = volume / "portfolio_backup_20261006.db"
    assert _rows(copy) == [1, 2]
    assert _journal_byte(copy) == 1
    out = capsys.readouterr().out
    assert "[DB] Backup created: portfolio_backup_20261006.db (" in out
    assert str(volume) not in out

    first = copy.stat().st_mtime_ns
    live_db.execute("INSERT INTO t VALUES (3)")
    live_db.commit()
    portfolio_db._backup_db_if_needed()
    assert copy.stat().st_mtime_ns == first and _rows(copy) == [1, 2]
    assert "Backup created" not in capsys.readouterr().out


def test_no_database_means_no_backup(volume, capsys):
    portfolio_db._backup_db_if_needed()
    assert os.listdir(volume) == []
    assert capsys.readouterr().out == ""


def test_a_copy_cut_short_does_not_count_as_todays_backup(volume, live_db):
    leftover = volume / "portfolio_backup_20261006.db.tmp-4242"
    leftover.write_bytes(b"half a copy")
    portfolio_db._backup_db_if_needed()
    assert _rows(volume / "portfolio_backup_20261006.db") == [1, 2]
    assert leftover.exists()                                     # retention is off: nothing deleted


@pytest.mark.parametrize("spare, made", [(portfolio_db.BACKUP_MIN_FREE_BYTES - 1, False),
                                         (portfolio_db.BACKUP_MIN_FREE_BYTES, True)])
def test_daily_backup_is_skipped_when_the_volume_is_short_of_space(volume, live_db, monkeypatch, capsys,
                                                                    spare, made):
    need = portfolio_db._db_bytes(str(volume / "portfolio.db"))
    monkeypatch.setattr(portfolio_db.shutil, "disk_usage",
                        lambda p: SimpleNamespace(total=5000 * MB, used=0, free=need + spare))
    portfolio_db._backup_db_if_needed()
    assert (volume / "portfolio_backup_20261006.db").exists() is made
    out = capsys.readouterr().out
    assert ("[DB] Backup skipped:" in out) is (not made)


def test_old_copies_stay_unless_retention_is_switched_on(volume, live_db, monkeypatch, capsys):
    for d in _days(date(2026, 9, 20), date(2026, 10, 5)):          # 16 old copies
        (volume / _daily(d)).write_bytes(b"x" * 1000)

    portfolio_db._backup_db_if_needed()                           # BACKUP_RETENTION not set
    assert len([n for n in os.listdir(volume) if portfolio_db.BACKUP_NAME_RE.match(n)]) == 17
    assert "pruned" not in capsys.readouterr().out

    (volume / "portfolio_backup_20261006.db").unlink()
    monkeypatch.setenv("BACKUP_RETENTION", "on")
    portfolio_db._backup_db_if_needed()
    kept = sorted(n for n in os.listdir(volume) if portfolio_db.BACKUP_NAME_RE.match(n))
    assert kept == sorted([_daily(d) for d in _days(date(2026, 9, 30), date(2026, 10, 6))]
                          + [_daily(date(2026, 9, 20))])          # newest 7 + Sep's first (Oct 1 is in the 7)
    out = capsys.readouterr().out
    assert "[DB] Backup created: portfolio_backup_20261006.db" in out
    assert "[DB] Backups pruned: 9 deleted (0.0 MB freed), 8 kept" in out
    assert (volume / "portfolio.db").exists() and (volume / "portfolio.db-wal").exists()


@pytest.mark.parametrize("value, on", [("on", True), (" On ", True), ("true", True), ("1", True),
                                       ("yes", True), ("off", False), ("", False), ("0", False)])
def test_retention_switch_values(monkeypatch, value, on):
    monkeypatch.setenv("BACKUP_RETENTION", value)
    assert portfolio_db.backup_retention_enabled() is on


# ── the retention rule ───────────────────────────────────────────────────────

def test_rule_on_five_months_of_daily_copies():
    days = _days(date(2026, 5, 10), date(2026, 10, 6))             # 150 copies
    names = [_daily(d) for d in days]
    plan = portfolio_db.plan_backup_retention(names + ["portfolio.db", "portfolio.db-wal"])

    expected = ([_daily(d) for d in _days(date(2026, 9, 30), date(2026, 10, 6))][::-1]
                + [_daily(date(2026, m, 1)) for m in (9, 8, 7, 6)] + [_daily(date(2026, 5, 10))])
    assert plan["keep"] == expected                                # 7 newest + Sep, Aug, Jul, Jun, May firsts
    assert len(plan["delete"]) == 150 - 12
    assert set(plan["delete"]) == set(names) - set(expected)
    assert plan["delete"] == sorted(plan["delete"], reverse=True)  # newest first


def test_rule_counts_months_that_have_copies():
    names = [f"portfolio_backup_2026{m:02d}{d:02d}.db" for m in (1, 3, 4, 5, 6, 7, 8) for d in (3, 20)]
    plan = portfolio_db.plan_backup_retention(names)
    assert set(plan["keep"]) == {
        "portfolio_backup_20260820.db", "portfolio_backup_20260803.db", "portfolio_backup_20260720.db",
        "portfolio_backup_20260703.db", "portfolio_backup_20260620.db", "portfolio_backup_20260603.db",
        "portfolio_backup_20260520.db",                            # the 7 newest
        "portfolio_backup_20260503.db", "portfolio_backup_20260403.db", "portfolio_backup_20260303.db"}
    assert set(plan["delete"]) == {"portfolio_backup_20260420.db", "portfolio_backup_20260320.db",
                                   "portfolio_backup_20260120.db", "portfolio_backup_20260103.db"}


def test_rule_only_ever_names_its_own_files():
    names = ["portfolio.db", "portfolio.db-wal", "portfolio.db-shm", "portfolio.db.pre_import",
             "portfolio_backup_20261399.db", "portfolio_backup_2026100.db", "portfolio_backup_20261006.db.bak",
             "portfolio_backup_20261006.db-journal", "scanner_prompt.md", ".env", "wallet_config.json",
             "portfolio_backup_20261006.db", "portfolio_backup_20261005.db.tmp-77", "portfolio.db.backup"]
    plan = portfolio_db.plan_backup_retention(names)
    assert plan == {"keep": ["portfolio_backup_20261006.db"],
                    "delete": ["portfolio_backup_20261005.db.tmp-77", "portfolio.db.backup"]}


def test_rule_keeps_everything_when_there_are_few_copies():
    names = [_daily(d) for d in _days(date(2026, 10, 2), date(2026, 10, 6))]
    assert portfolio_db.plan_backup_retention(names)["delete"] == []


def test_rule_needs_at_least_one_daily_copy_kept():
    with pytest.raises(ValueError):
        portfolio_db.plan_backup_retention([], keep_daily=0)


# ── prune_backups ────────────────────────────────────────────────────────────

def _prune_folder(volume):
    for d in _days(date(2026, 9, 27), date(2026, 10, 6)):           # 10 copies
        (volume / _daily(d)).write_bytes(b"x" * 1000)
    (volume / "portfolio.db.backup").write_bytes(b"e" * 500)
    old_tmp = volume / "portfolio_backup_20261001.db.tmp-1"
    old_tmp.write_bytes(b"t" * 300)
    two_hours_ago = time.time() - 7200
    os.utime(old_tmp, (two_hours_ago, two_hours_ago))
    (volume / "portfolio_backup_20261006.db.tmp-2").write_bytes(b"t" * 300)   # fresh: maybe in progress
    (volume / "portfolio_backup_20260915.db").mkdir()               # a folder with a backup name
    (volume / "notes.txt").write_text("keep me")


def test_prune_dry_run_deletes_nothing_and_a_real_run_deletes_only_the_plan(volume, live_db):
    _prune_folder(volume)
    before = sorted(os.listdir(volume))
    expected = ["portfolio_backup_20260929.db", "portfolio_backup_20260928.db",
                "portfolio_backup_20261001.db.tmp-1", "portfolio.db.backup"]

    dry = portfolio_db.prune_backups(str(volume))
    assert dry["dry_run"] is True
    assert dry["deleted"] == expected
    assert dry["skipped"] == ["portfolio_backup_20261006.db.tmp-2"]
    assert dry["freed_bytes"] == 1000 + 1000 + 300 + 500
    assert dry["kept"] == [_daily(d) for d in _days(date(2026, 9, 30), date(2026, 10, 6))][::-1] + [
        "portfolio_backup_20260927.db"]
    assert sorted(os.listdir(volume)) == before

    real = portfolio_db.prune_backups(str(volume), dry_run=False)
    assert real["deleted"] == expected and real["errors"] == []
    assert sorted(os.listdir(volume)) == sorted(set(before) - set(expected))
    for survivor in ("portfolio.db", "portfolio.db-wal", "portfolio.db-shm", "notes.txt",
                     "portfolio_backup_20260915.db", "portfolio_backup_20261006.db.tmp-2"):
        assert (volume / survivor).exists()
    assert (volume / "portfolio_backup_20260915.db").is_dir()
    assert _rows(volume / "portfolio.db") == [1]                   # main file untouched (row 2 is in the -wal)


# ── routes ───────────────────────────────────────────────────────────────────

def test_export_downloads_a_consistent_copy_and_leaves_nothing(volume, live_db, client, container_tmp, tmp_path):
    before = sorted(os.listdir(volume))
    r = client.get("/api/backup/db")
    body = r.get_data()
    r.close()

    assert r.status_code == 200
    assert r.mimetype == "application/x-sqlite3"
    assert re.search(r"filename=portfolio_backup_\d{8}-\d{4}\.db", r.headers["Content-Disposition"])
    assert int(r.headers["Content-Length"]) == len(body)
    download = tmp_path / "download.db"
    download.write_bytes(body)
    assert _rows(download) == [1, 2]
    assert _journal_byte(download) == 1
    assert _quick_check(download) == "ok"
    assert sorted(os.listdir(volume)) == before                    # no portfolio.db.backup on the volume
    assert os.listdir(container_tmp) == []                         # the temp copy is gone


def test_export_without_a_database_is_404(volume, client, container_tmp):
    r = client.get("/api/backup/db")
    assert r.status_code == 404
    assert os.listdir(container_tmp) == []


def test_export_failure_is_500_and_leaves_no_temp_file(volume, client, container_tmp):
    (volume / "portfolio.db").write_bytes(b"this is not a database " * 200)
    r = client.get("/api/backup/db")
    assert r.status_code == 500
    assert r.get_json()["error"].startswith("Export failed")
    assert os.listdir(container_tmp) == []


def test_status_reports_sizes_copies_and_the_retention_preview(volume, live_db, client, monkeypatch):
    for i, d in enumerate(_days(date(2026, 9, 28), date(2026, 10, 6))):   # 9 copies
        (volume / _daily(d)).write_bytes(b"x" * (1000 + i))
    (volume / "portfolio.db.backup").write_bytes(b"e" * 500)
    (volume / ".env").write_text("SECRET_NAME=1")
    (volume / "wallet_config.json").write_text("{}")
    (volume / "cache").mkdir()
    (volume / "cache" / "a.json").write_text("{}")
    (volume / "cache" / "b.json").write_text("{}")
    before = sorted(os.listdir(volume))

    r = client.get("/api/backup/status")
    assert r.status_code == 200
    j = r.get_json()
    text = r.get_data(as_text=True)

    assert set(j) == {"database", "volume", "daily_backups", "other_portfolio_files", "other_files", "retention",
                      "offsite"}                                    # Landing 12 adds the off-server copy
    daily = j["daily_backups"]
    assert daily["count"] == 9 and daily["today_made"] is True
    assert [c["name"] for c in daily["copies"]] == [_daily(d) for d in _days(date(2026, 9, 28),
                                                                               date(2026, 10, 6))][::-1]
    assert daily["copies"][0]["date"] == "2026-10-06"
    assert j["other_portfolio_files"] == [{"name": "portfolio.db.backup", "mb": 0.0}]
    assert j["other_files"]["count"] == 4                          # .env, wallet_config.json, cache/a, cache/b
    for hidden in (".env", "SECRET_NAME", "wallet_config", "cache", str(volume)):
        assert hidden not in text
    v = j["volume"]
    assert v["total_mb"] > 0 and v["used_mb"] >= 0 and v["free_mb"] >= 0
    ret = j["retention"]
    assert ret["enabled"] is False and "BACKUP_RETENTION=on" in ret["switch"]
    assert ret["would_delete"] == ["portfolio_backup_20260929.db", "portfolio.db.backup"]
    assert "portfolio_backup_20260928.db" in ret["would_keep"]      # Sep's first copy
    assert sorted(os.listdir(volume)) == before                    # read-only

    monkeypatch.setenv("BACKUP_RETENTION", "on")
    assert client.get("/api/backup/status").get_json()["retention"]["enabled"] is True
    assert sorted(os.listdir(volume)) == before                    # still read-only with the switch on


def test_backup_routes_need_a_session(volume, monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    c = wp.app.test_client()
    for path in ("/api/backup/status", "/api/backup/db"):
        assert c.get(path).status_code == 401
