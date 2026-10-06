"""Landing 11: restore a database copy (src/storage/db_restore.py and the
/api/backup/restore routes).

Real SQLite files under tmp_path; RAILWAY_VOLUME_MOUNT_PATH points the app at
a temp "volume". The live database is built by the app's own init_db. The
init_db check on a staged copy runs in a separate process for real in the
tests marked so; elsewhere it is replaced by a no-op to keep the suite fast."""

import hashlib
import io
import json
import os
import sqlite3
import sys
import time

import pytest

import web_portfolio as wp
from src.storage import db_restore, portfolio_db


# ── fixtures and helpers ─────────────────────────────────────────────────────

@pytest.fixture
def volume(tmp_path, monkeypatch):
    vol = tmp_path / "volume"
    vol.mkdir()
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(vol))
    monkeypatch.delenv("BACKUP_RETENTION", raising=False)
    monkeypatch.setattr(portfolio_db, "_backup_db_if_needed", lambda: None)
    return vol


@pytest.fixture
def fast_check(monkeypatch):
    calls = []
    monkeypatch.setattr(db_restore, "_run_init_db_on_copy", lambda staged, folder: calls.append(staged))
    return calls


@pytest.fixture
def live(volume):
    portfolio_db.init_db()
    _add_snapshots(volume / "portfolio.db", 3, "2026-10-01T10:00:00")
    return volume / "portfolio.db"


@pytest.fixture
def client(volume, monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    monkeypatch.setattr(wp, "_restart_worker_soon", lambda delay=1.0: False)
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


H = {"X-Playbook-Restore": "1"}
_real_restart = wp._restart_worker_soon


def _add_snapshots(db, n, ts, wallet="w-test"):
    conn = sqlite3.connect(db)
    for _ in range(n):
        conn.execute("INSERT INTO portfolio_snapshots (user_id, timestamp, wallet, status) VALUES (1, ?, ?, 'completed')",
                     (ts, wallet))
    conn.commit()
    conn.close()


def _count(db, table="portfolio_snapshots"):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _export(live_path, dst):
    portfolio_db.snapshot_db(str(dst), str(live_path))
    return dst


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _upload(client, path, name="portfolio_backup_20261006-0102.db", headers=H):
    data = open(path, "rb").read()
    return client.post("/api/backup/restore/upload", data=data,
                       headers=dict(headers, **{"Content-Type": "application/octet-stream", "X-Filename": name}))


def _stage_export(client, live_path, tmp_path):
    exp = _export(live_path, tmp_path / "export.db")
    r = _upload(client, exp)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["staged"], exp


def _request(client, report, confirm="RESTORE"):
    return client.post("/api/backup/restore/apply", json={"staged_sha256": report["staged_sha256"], "confirm": confirm},
                       headers=H)


def _result(volume):
    path = volume / db_restore.RESULT
    return json.loads(path.read_text()) if path.exists() else None


def _restore_files(volume):
    return sorted(n for n in os.listdir(volume) if n.startswith("portfolio_restore"))


# ── stage ────────────────────────────────────────────────────────────────────

def test_upload_is_checked_and_reported_and_the_live_database_is_untouched(live, client, tmp_path, fast_check):
    exp = _export(live, tmp_path / "export.db")
    _add_snapshots(live, 4, "2026-10-06T02:30:00")            # saved after the export
    before = _count(live)
    r = _upload(client, exp)
    assert r.status_code == 200
    rep = r.get_json()["staged"]
    assert rep["source"] == {"kind": "upload", "name": "portfolio_backup_20261006-0102.db", "sha256": _sha(exp)}
    assert rep["staged_sha256"] == _sha(live.parent / db_restore.STAGED_DB)
    assert rep["checks"] == {"integrity": "ok", "core_tables": "ok", "init_db": "ok"}
    assert {"table": "portfolio_snapshots", "file": 3, "current": 7} in rep["rows"]
    assert rep["newest"]["file"] == "2026-10-01T10:00:00+00:00"
    assert rep["newest"]["current"] == "2026-10-06T02:30:00+00:00"
    assert any("older than the current data by 4 days 16 h" in w for w in rep["warnings"])
    assert len(fast_check) == 1
    assert _count(live) == before
    assert not (live.parent / db_restore.PENDING).exists()
    assert _restore_files(live.parent) == [db_restore.STAGED_DB, db_restore.STAGED_REPORT]


def test_a_copy_saved_in_wal_mode_without_its_wal_file_is_staged_as_one_file(live, client, tmp_path, fast_check):
    raw = tmp_path / "old_style_export.db"
    raw.write_bytes(live.read_bytes())                        # the old Export DB: a plain copy of a WAL database
    assert raw.read_bytes()[18:20] == b"\x02\x02"
    r = _upload(client, raw)
    assert r.status_code == 200
    staged = live.parent / db_restore.STAGED_DB
    assert staged.read_bytes()[18:20] == b"\x01\x01"           # DELETE journal mode: self-contained
    assert not os.path.exists(str(raw) + "-wal") and not os.path.exists(str(raw) + "-shm")


def test_a_server_copy_is_staged_by_name_and_left_unchanged(live, client, fast_check):
    name = "portfolio_backup_20261005.db"
    copy = live.parent / name
    portfolio_db.snapshot_db(str(copy), str(live))
    digest, mtime = _sha(copy), copy.stat().st_mtime
    r = client.post("/api/backup/restore/server-copy", json={"name": name}, headers=H)
    assert r.status_code == 200
    assert r.get_json()["staged"]["source"] == {"kind": "daily", "name": name}
    assert _sha(copy) == digest and copy.stat().st_mtime == mtime
    assert not os.path.exists(str(copy) + "-wal") and not os.path.exists(str(copy) + "-shm")


@pytest.mark.parametrize("name", ["portfolio.db", "../portfolio.db", "/etc/passwd", "portfolio_backup_20261004.db",
                                  "portfolio_pre_restore_20261006-010203.db", "", None])
def test_server_copy_names_outside_the_list_are_refused(live, client, name, fast_check):
    r = client.post("/api/backup/restore/server-copy", json={"name": name}, headers=H)
    assert r.status_code == 404
    assert _restore_files(live.parent) == []


def test_a_link_with_a_copy_name_is_not_a_server_copy(live, client, tmp_path, fast_check):
    target = _export(live, tmp_path / "elsewhere.db")
    os.symlink(target, live.parent / "portfolio_backup_20261005.db")
    r = client.post("/api/backup/restore/server-copy", json={"name": "portfolio_backup_20261005.db"}, headers=H)
    assert r.status_code == 404


def test_not_a_sqlite_file_is_refused(live, client, tmp_path, fast_check):
    bad = tmp_path / "notes.txt"
    bad.write_bytes(b"hello " * 1000)
    r = _upload(client, bad)
    assert r.status_code == 400 and "not a SQLite database" in r.get_json()["error"]
    assert _restore_files(live.parent) == []


def test_a_damaged_database_is_refused(live, client, tmp_path, fast_check):
    exp = bytearray(_export(live, tmp_path / "export.db").read_bytes())
    page = 4096
    exp[page * 3:page * 3 + 3000] = b"\xab" * 3000             # trample a page past the header
    bad = tmp_path / "damaged.db"
    bad.write_bytes(bytes(exp))
    r = _upload(client, bad)
    assert r.status_code == 400
    assert "integrity check failed" in r.get_json()["error"] or "could not be read" in r.get_json()["error"]
    assert _restore_files(live.parent) == []


def test_a_database_from_another_app_is_refused(live, client, tmp_path, fast_check):
    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE things (id INTEGER)")
    conn.commit()
    conn.close()
    r = _upload(client, other)
    assert r.status_code == 400
    assert "not a Playbook database" in r.get_json()["error"]
    assert _restore_files(live.parent) == []


def test_a_copy_the_app_cannot_open_is_refused_by_the_real_init_db_check(live, client, tmp_path):
    exp = _export(live, tmp_path / "export.db")
    conn = sqlite3.connect(exp)
    conn.execute("DROP TABLE trade_tags")
    conn.execute("CREATE VIEW trade_tags AS SELECT 1 AS id")   # init_db cannot index a view
    conn.commit()
    conn.close()
    r = _upload(client, exp)
    assert r.status_code == 400
    err = r.get_json()["error"]
    assert err == "The app could not open this database: sqlite3.OperationalError: views may not be indexed"
    assert str(live.parent) not in err
    assert _restore_files(live.parent) == []


def test_an_older_layout_passes_the_real_init_db_check_and_is_reported(live, client, tmp_path):
    exp = _export(live, tmp_path / "export.db")
    conn = sqlite3.connect(exp)
    conn.execute("DROP TABLE trade_tags")
    conn.execute("ALTER TABLE trade_annotations DROP COLUMN exit_reason_note")
    conn.commit()
    conn.close()
    r = _upload(client, exp)
    assert r.status_code == 200, r.get_json()
    rep = r.get_json()["staged"]
    assert rep["tables"]["only_in_current"] == ["trade_tags"]
    assert rep["columns"]["only_in_current"] == {"trade_annotations": ["exit_reason_note"]}
    assert any("will start empty: trade_tags" in w for w in rep["warnings"])
    assert any("adds 1 column(s)" in w for w in rep["warnings"])
    assert not (live.parent / db_restore.CHECK_DIR).exists()


def test_a_newer_layout_is_allowed_with_a_warning(live, client, tmp_path, fast_check):
    exp = _export(live, tmp_path / "export.db")
    conn = sqlite3.connect(exp)
    conn.execute("CREATE TABLE future_things (id INTEGER)")
    conn.execute("ALTER TABLE trade_tags ADD COLUMN future_col TEXT")
    conn.commit()
    conn.close()
    rep = _upload(client, exp).get_json()["staged"]
    assert rep["tables"]["only_in_file"] == ["future_things"]
    assert rep["columns"]["only_in_file"] == {"trade_tags": ["future_col"]}
    assert any("does not use (future_things, trade_tags.future_col)" in w for w in rep["warnings"])


def test_the_report_holds_no_row_contents(live, client, tmp_path, fast_check):
    conn = sqlite3.connect(live)
    conn.execute("INSERT INTO spot_note_updates (chain, contract_address, body, created_at) "
                 "VALUES ('base', 'token-x', 'PRIVATE-NOTE-TEXT', '2026-10-05T12:00:00+00:00')")
    conn.commit()
    conn.close()
    _stage_export(client, live, tmp_path)
    text = (live.parent / db_restore.STAGED_REPORT).read_text()
    assert "PRIVATE-NOTE-TEXT" not in text and "token-x" not in text and "w-test" not in text


def test_an_upload_over_the_limit_is_refused_before_it_is_read(live, client, tmp_path, monkeypatch, fast_check):
    monkeypatch.setattr(db_restore, "MAX_UPLOAD_BYTES", 1000)
    r = _upload(client, _export(live, tmp_path / "export.db"))
    assert r.status_code == 413 and r.is_json
    assert _restore_files(live.parent) == []


def test_an_upload_above_the_app_wide_16_mb_limit_is_accepted(live, client, tmp_path, fast_check):
    conn = sqlite3.connect(live)
    conn.execute("CREATE TABLE padding (b BLOB)")
    conn.executemany("INSERT INTO padding VALUES (?)", [(os.urandom(4096),) for _ in range(5000)])
    conn.commit()
    conn.close()
    exp = _export(live, tmp_path / "big.db")
    assert exp.stat().st_size > 16 * 1024 * 1024
    r = _upload(client, exp)
    assert r.status_code == 200, r.get_json()


def test_an_upload_short_of_space_is_refused(live, client, tmp_path, monkeypatch, fast_check):
    monkeypatch.setattr(db_restore, "_free_bytes", lambda folder: 200 * 1024 * 1024)
    r = _upload(client, _export(live, tmp_path / "export.db"))
    assert r.status_code == 507 and "Not enough free space" in r.get_json()["error"]
    assert _restore_files(live.parent) == []


def test_an_upload_cut_short_leaves_nothing(live, tmp_path, fast_check):
    data = _export(live, tmp_path / "export.db").read_bytes()
    with pytest.raises(db_restore.RestoreError) as e:
        db_restore.stage_upload(io.BytesIO(data[:5000]), len(data), "x.db")
    assert e.value.status == 400 and "cut short" in str(e.value)
    assert _restore_files(live.parent) == []


def test_restore_posts_need_the_header_and_a_session(live, volume, monkeypatch, tmp_path, fast_check):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    anon = wp.app.test_client()
    assert anon.get("/api/backup/restore").status_code == 401
    assert anon.post("/api/backup/restore/upload", data=b"x", headers=H).status_code == 401
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    exp = _export(live, tmp_path / "export.db")
    assert _upload(c, exp, headers={}).status_code == 400
    assert c.post("/api/backup/restore/apply", json={"confirm": "RESTORE"}).status_code == 400
    assert c.post("/api/backup/restore/discard").status_code == 400
    assert _restore_files(live.parent) == []


def test_a_second_request_while_one_runs_is_refused(live, client, tmp_path, fast_check):
    exp = _export(live, tmp_path / "export.db")
    db_restore._STAGE_LOCK.acquire()
    try:
        r = _upload(client, exp)
    finally:
        db_restore._STAGE_LOCK.release()
    assert r.status_code == 409


def test_a_new_stage_replaces_the_old_one_and_cancels_its_request(live, client, tmp_path, fast_check):
    rep1, _ = _stage_export(client, live, tmp_path)
    assert _request(client, rep1).status_code == 202
    _add_snapshots(live, 1, "2026-10-06T03:00:00")
    rep2 = _upload(client, _export(live, tmp_path / "export2.db")).get_json()["staged"]
    assert rep2["staged_sha256"] != rep1["staged_sha256"]
    assert not (live.parent / db_restore.PENDING).exists()
    assert _request(client, rep1).status_code == 409


def test_discard_removes_the_staged_copy_and_the_request(live, client, tmp_path, fast_check):
    rep, _ = _stage_export(client, live, tmp_path)
    _request(client, rep)
    r = client.post("/api/backup/restore/discard", headers=H)
    assert r.status_code == 200 and r.get_json() == {"discarded": True}
    assert _restore_files(live.parent) == []


# ── request ──────────────────────────────────────────────────────────────────

def test_apply_needs_the_typed_word_and_the_checked_sha(live, client, tmp_path, fast_check):
    rep, _ = _stage_export(client, live, tmp_path)
    assert _request(client, rep, confirm="restore").status_code == 400
    assert _request(client, rep, confirm="").status_code == 400
    r = client.post("/api/backup/restore/apply", json={"staged_sha256": "0" * 64, "confirm": "RESTORE"}, headers=H)
    assert r.status_code == 409
    assert client.post("/api/backup/restore/apply", data="confirm=RESTORE", headers=H).status_code == 400
    assert not (live.parent / db_restore.PENDING).exists()


def test_apply_refuses_a_staged_file_changed_after_the_check(live, client, tmp_path, fast_check):
    rep, _ = _stage_export(client, live, tmp_path)
    with open(live.parent / db_restore.STAGED_DB, "ab") as f:
        f.write(b"\0" * 4096)
    assert _request(client, rep).status_code == 409
    assert not (live.parent / db_restore.PENDING).exists()


def test_apply_records_the_request_restarts_and_leaves_live_alone(live, client, tmp_path, monkeypatch, fast_check):
    calls = []
    monkeypatch.setattr(wp, "_restart_worker_soon", lambda delay=1.0: calls.append(delay) or True)
    rep, _ = _stage_export(client, live, tmp_path)
    before = _count(live)
    r = _request(client, rep)
    assert r.status_code == 202
    body = r.get_json()
    assert body["pending"] is True and body["restarting"] is True and calls == [1.0]
    pending = json.loads((live.parent / db_restore.PENDING).read_text())
    assert pending["staged_sha256"] == rep["staged_sha256"]
    assert _count(live) == before


def test_outside_gunicorn_apply_waits_for_the_next_start(live, client, tmp_path, monkeypatch, fast_check):
    monkeypatch.setattr(wp, "_restart_worker_soon", _real_restart)
    monkeypatch.delitem(sys.modules, "gunicorn", raising=False)
    rep, _ = _stage_export(client, live, tmp_path)
    body = _request(client, rep).get_json()
    assert body["restarting"] is False and "Restart the app" in body["message"]


def test_under_gunicorn_the_worker_sends_itself_sigterm(monkeypatch):
    import signal
    sent, threads = [], []

    class SyncThread:                                          # runs the target in the test, never in the background
        def __init__(self, target=None, name=None, daemon=None):
            self.target = target
            threads.append(name)

        def start(self):
            self.target()
    monkeypatch.setitem(sys.modules, "gunicorn", object())
    monkeypatch.setattr(wp.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    monkeypatch.setattr(wp.threading, "Thread", SyncThread)
    assert _real_restart(delay=0) is True
    assert threads == ["restore-restart"]
    assert sent == [(os.getpid(), signal.SIGTERM)]


# ── apply at boot ────────────────────────────────────────────────────────────

def test_boot_applies_the_restore_after_a_safety_copy(live, client, tmp_path, fast_check):
    rep, exp = _stage_export(client, live, tmp_path)           # 3 snapshots in the copy
    assert _request(client, rep).status_code == 202
    _add_snapshots(live, 2, "2026-10-06T04:00:00")             # written between the request and the restart
    portfolio_db.init_db()
    assert _count(live) == 3
    res = _result(live.parent)
    assert res["status"] == "applied" and res["source"]["kind"] == "upload"
    assert res["newest_in_copy"] == "2026-10-01T10:00:00+00:00"
    safety = live.parent / res["safety"]
    assert portfolio_db.PRE_RESTORE_NAME_RE.match(res["safety"])
    assert _count(safety) == 5                                 # the previous data, including the late writes
    conn = sqlite3.connect(live)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert "trade_tags" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()
    assert _restore_files(live.parent) == [db_restore.RESULT]
    db_restore.boot_completed()
    assert _result(live.parent)["status"] == "completed"
    portfolio_db.init_db()                                     # a later boot changes nothing
    assert _count(live) == 3 and _result(live.parent)["status"] == "completed"


def test_a_boot_that_did_not_finish_is_rolled_back_at_the_next_boot(live, client, tmp_path, fast_check):
    rep, _ = _stage_export(client, live, tmp_path)
    _add_snapshots(live, 2, "2026-10-06T04:00:00")
    _request(client, rep)
    portfolio_db.init_db()                                     # applies; the boot then "dies" before boot_completed
    assert _count(live) == 3
    portfolio_db.init_db()                                     # the next boot
    assert _count(live) == 5
    res = _result(live.parent)
    assert res["status"] == "rolled_back_after_failed_boot"
    assert "did not finish starting" in res["reason"]
    portfolio_db.init_db()
    assert _count(live) == 5 and _result(live.parent)["status"] == "rolled_back_after_failed_boot"


def test_an_interrupted_copy_is_rolled_back_at_the_next_boot(live, client, tmp_path, fast_check):
    rep, _ = _stage_export(client, live, tmp_path)
    _add_snapshots(live, 2, "2026-10-06T04:00:00")
    _request(client, rep)
    portfolio_db.init_db()
    res = _result(live.parent)
    res["status"] = "applying"                                 # as if the process died mid-copy
    (live.parent / db_restore.RESULT).write_text(json.dumps(res))
    portfolio_db.init_db()
    assert _count(live) == 5 and _result(live.parent)["status"] == "rolled_back_after_failed_boot"


def test_a_copy_that_fails_is_rolled_back_at_once(live, client, tmp_path, monkeypatch, fast_check):
    rep, _ = _stage_export(client, live, tmp_path)
    _add_snapshots(live, 2, "2026-10-06T04:00:00")
    _request(client, rep)
    real = db_restore._write_into_live
    calls = []

    def flaky(src, dst):
        calls.append(os.path.basename(src))
        if len(calls) == 1:
            real(src, dst)
            raise RuntimeError("disk I/O error")
        real(src, dst)
    monkeypatch.setattr(db_restore, "_write_into_live", flaky)
    portfolio_db.init_db()
    res = _result(live.parent)
    assert res["status"] == "rolled_back" and "disk I/O error" in res["reason"]
    assert calls[0] == db_restore.STAGED_DB and calls[1] == res["safety"]
    assert _count(live) == 5


def test_nothing_is_applied_while_another_connection_has_the_database(live, client, tmp_path, fast_check):
    rep, _ = _stage_export(client, live, tmp_path)
    _request(client, rep)
    holder = sqlite3.connect(live)
    holder.execute("SELECT COUNT(*) FROM users").fetchone()
    try:
        portfolio_db.init_db()
    finally:
        holder.close()
    res = _result(live.parent)
    assert res["status"] == "not_applied" and "in use" in res["reason"]
    assert _count(live) == 3 and not (live.parent / db_restore.PENDING).exists()


def test_nothing_is_applied_when_the_staged_copy_changed(live, client, tmp_path, fast_check):
    _add_snapshots(live, 2, "2026-10-06T04:00:00")
    rep, _ = _stage_export(client, live, tmp_path)
    _request(client, rep)
    _add_snapshots(live.parent / db_restore.STAGED_DB, 1, "2026-10-06T05:00:00")
    _add_snapshots(live, 1, "2026-10-06T06:00:00")
    portfolio_db.init_db()
    res = _result(live.parent)
    assert res["status"] == "not_applied" and "missing or had changed" in res["reason"]
    assert _count(live) == 6 and _restore_files(live.parent) == [db_restore.RESULT]


def test_nothing_is_applied_when_short_of_space(live, client, tmp_path, monkeypatch, fast_check):
    rep, _ = _stage_export(client, live, tmp_path)
    _request(client, rep)
    _add_snapshots(live, 1, "2026-10-06T04:00:00")
    monkeypatch.setattr(db_restore, "_free_bytes", lambda folder: 100 * 1024 * 1024)
    portfolio_db.init_db()
    res = _result(live.parent)
    assert res["status"] == "not_applied" and "Not enough free space" in res["reason"]
    assert _count(live) == 4
    assert not any(portfolio_db.PRE_RESTORE_NAME_RE.match(n) for n in os.listdir(live.parent))


def test_nothing_is_applied_when_the_safety_copy_fails(live, client, tmp_path, monkeypatch, fast_check):
    rep, _ = _stage_export(client, live, tmp_path)
    _request(client, rep)
    _add_snapshots(live, 1, "2026-10-06T04:00:00")

    def boom(dst, src=None):
        raise OSError("No space left on device")
    monkeypatch.setattr(portfolio_db, "snapshot_db", boom)
    portfolio_db.init_db()
    res = _result(live.parent)
    assert res["status"] == "not_applied" and "safety copy could not be made" in res["reason"]
    assert _count(live) == 4


def test_a_boot_without_restore_files_changes_nothing(live):
    before = sorted(os.listdir(live.parent))
    portfolio_db.init_db()
    assert sorted(os.listdir(live.parent)) == before
    assert _result(live.parent) is None


def test_an_older_layout_is_brought_up_to_date_by_the_boot(live, client, tmp_path, fast_check):
    exp = _export(live, tmp_path / "export.db")
    conn = sqlite3.connect(exp)
    conn.execute("DROP TABLE trade_tags")
    conn.commit()
    conn.close()
    rep = _upload(client, exp).get_json()["staged"]
    _request(client, rep)
    portfolio_db.init_db()
    assert _result(live.parent)["status"] == "applied"
    assert _count(live, "trade_tags") == 0                     # created by init_db after the copy


def test_restoring_the_safety_copy_undoes_a_restore(live, client, tmp_path, fast_check):
    rep, _ = _stage_export(client, live, tmp_path)
    _add_snapshots(live, 2, "2026-10-06T04:00:00")
    _request(client, rep)
    portfolio_db.init_db()
    db_restore.boot_completed()
    safety = _result(live.parent)["safety"]
    sources = client.get("/api/backup/restore").get_json()["sources"]
    assert {"name": safety, "kind": "safety"}.items() <= next(s for s in sources if s["name"] == safety).items()
    rep2 = client.post("/api/backup/restore/server-copy", json={"name": safety}, headers=H).get_json()["staged"]
    assert rep2["source"] == {"kind": "safety", "name": safety}
    assert _request(client, rep2).status_code == 202
    portfolio_db.init_db()
    assert _count(live) == 5


# ── leftovers, retention, status ─────────────────────────────────────────────

def test_stale_leftovers_are_cleared_at_boot(live, client, tmp_path, fast_check):
    vol = live.parent
    old = time.time() - 2 * 3600
    for name in (f"{db_restore.UPLOAD_TMP_PREFIX}123", f"{db_restore.STAGED_DB}.tmp-9"):
        (vol / name).write_bytes(b"x")
        os.utime(vol / name, (old, old))
    (vol / f"{db_restore.UPLOAD_TMP_PREFIX}456").write_bytes(b"x")          # recent: may be in progress
    (vol / db_restore.CHECK_DIR).mkdir()
    os.utime(vol / db_restore.CHECK_DIR, (old, old))
    _stage_export(client, live, tmp_path)
    day_old = time.time() - 25 * 3600
    os.utime(vol / db_restore.STAGED_DB, (day_old, day_old))
    portfolio_db.init_db()
    assert _restore_files(vol) == [f"{db_restore.UPLOAD_TMP_PREFIX}456"]


def test_a_staged_copy_waiting_for_the_boot_does_not_expire(live, client, tmp_path, fast_check):
    rep, _ = _stage_export(client, live, tmp_path)
    _request(client, rep)
    day_old = time.time() - 25 * 3600
    os.utime(live.parent / db_restore.STAGED_DB, (day_old, day_old))
    db_restore._cleanup_stale(str(live.parent))
    assert (live.parent / db_restore.STAGED_DB).exists()


def test_retention_keeps_the_two_newest_safety_copies():
    names = ["portfolio_backup_20261006.db",
             "portfolio_pre_restore_20261001-120000.db", "portfolio_pre_restore_20261006-014000.db",
             "portfolio_pre_restore_20261003-090000.db", "portfolio_pre_restore_20261006-014000.db.tmp-7",
             "portfolio_pre_restore_2026100-014000.db", db_restore.STAGED_DB, db_restore.STAGED_REPORT,
             db_restore.PENDING, db_restore.RESULT]
    plan = portfolio_db.plan_backup_retention(names)
    assert plan == {"keep": ["portfolio_backup_20261006.db", "portfolio_pre_restore_20261006-014000.db",
                             "portfolio_pre_restore_20261003-090000.db"],
                    "delete": ["portfolio_pre_restore_20261001-120000.db",
                               "portfolio_pre_restore_20261006-014000.db.tmp-7"]}


def test_prune_skips_a_recent_safety_copy_temp_file(volume):
    for name in ("portfolio_backup_20261006.db", "portfolio_pre_restore_20261006-014000.db.tmp-7"):
        (volume / name).write_bytes(b"x")
    r = portfolio_db.prune_backups(str(volume), dry_run=False)
    assert r["skipped"] == ["portfolio_pre_restore_20261006-014000.db.tmp-7"]
    assert (volume / "portfolio_pre_restore_20261006-014000.db.tmp-7").exists()


def test_status_lists_the_staged_copy_sources_and_result_without_paths(live, client, tmp_path, fast_check):
    portfolio_db.snapshot_db(str(live.parent / "portfolio_backup_20261005.db"), str(live))
    rep, _ = _stage_export(client, live, tmp_path)
    r = client.get("/api/backup/restore")
    assert r.status_code == 200
    body = r.get_json()
    assert body["staged"]["staged_sha256"] == rep["staged_sha256"]
    assert body["pending"] is False and body["result"] is None
    assert body["confirm_word"] == "RESTORE" and body["max_upload_mb"] == 1024.0
    assert [s["name"] for s in body["sources"]] == ["portfolio_backup_20261005.db"]
    assert body["boot_id"] == wp._RESTORE_BOOT_ID and body["restarts_itself"] is False
    assert str(live.parent) not in r.get_data(as_text=True)


def test_the_old_import_is_gone(client):
    assert not hasattr(wp, "api_import_db")
    assert client.post("/api/backup/db").status_code == 405


def test_times_are_read_as_utc():
    assert db_restore._to_utc("2026-10-06 01:02:03") == "2026-10-06T01:02:03+00:00"
    assert db_restore._to_utc("2026-10-06T01:02:03.123456") == "2026-10-06T01:02:03+00:00"
    assert db_restore._to_utc("2026-10-05T18:02:03-07:00") == "2026-10-06T01:02:03+00:00"
    assert db_restore._to_utc("2026-10-06T01:02:03Z") == "2026-10-06T01:02:03+00:00"
    assert db_restore._to_utc(1791248523000) == db_restore._to_utc(1791248523)
    assert db_restore._to_utc("not a time") is None and db_restore._to_utc(None) is None
    assert db_restore._to_utc("2099-01-01T00:00:00") is None


def test_gaps_are_worded_for_people():
    from datetime import timedelta
    assert db_restore._span(timedelta(seconds=30)) == "under a minute"
    assert db_restore._span(timedelta(minutes=52)) == "52 min"
    assert db_restore._span(timedelta(hours=2, minutes=52)) == "2 h 52 min"
    assert db_restore._span(timedelta(days=4, hours=16, minutes=30)) == "4 days 16 h"
