"""Database restore (Landing 11): stage a copy, check it, apply it at boot.

A restore runs in three steps, so the live database is only replaced while
nothing else has it open:

1. Stage (stage_upload / stage_server_copy). The chosen copy is written next to
   the database as portfolio_restore_staged.db through SQLite's backup API (one
   self-contained file, whatever journal mode the copy was saved in). It is
   checked: integrity_check, the core tables, and init_db run on a copy of it
   in a separate process (the same code the boot will run). It is compared
   with the live database, and the report goes to portfolio_restore_staged.json.
   The live database is not touched.
2. Request (request_apply). After the typed confirmation, the route writes
   portfolio_restore_pending.json and restarts the app worker.
3. Apply (apply_pending_restore). This is the first thing init_db does at boot,
   before migrations and before any background thread starts:
   - a safety copy of the live database, portfolio_pre_restore_YYYYMMDD-HHMMSS.db (UTC);
   - then the staged copy is written into the live database through the backup
     API (DELETE journal mode during the copy, WAL again after, then quick_check).
   Progress is kept in portfolio_restore_result.json:
   - 'applying', then 'applied', then 'completed' (boot_completed, called once
     web_portfolio has finished importing);
   - a boot that finds 'applying' or 'applied' means the previous boot never
     finished, so the safety copy is written back ('rolled_back_after_failed_boot').

The live database is never replaced by moving a file, so no stale -wal / -shm
can be replayed. No row contents leave this module: reports hold table and
column names, row counts and timestamps only."""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.storage import portfolio_db as _pdb

STAGED_DB = 'portfolio_restore_staged.db'
STAGED_REPORT = 'portfolio_restore_staged.json'
PENDING = 'portfolio_restore_pending.json'
RESULT = 'portfolio_restore_result.json'
UPLOAD_TMP_PREFIX = 'portfolio_restore_upload.tmp-'
CHECK_DIR = 'portfolio_restore_check'
SAFETY_PREFIX = 'portfolio_pre_restore_'

CONFIRM_WORD = 'RESTORE'
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024
MIN_FREE_BYTES = _pdb.BACKUP_MIN_FREE_BYTES
STAGE_FREE_FACTOR = 3        # upload + staged copy + the copy init_db is tried on
APPLY_FREE_FACTOR = 2        # safety copy + rollback journal while the copy is written
STAGED_TTL_S = 24 * 3600
TMP_GRACE_S = 3600
CHECK_TIMEOUT_S = 300
CHUNK = 1 << 20
SQLITE_MAGIC = b'SQLite format 3\x00'
CORE_TABLES = ('users', 'portfolio_snapshots', 'token_snapshots')
NEWEST_COLUMNS = (            # (table, column, label): where "newest data" is read from
    ('portfolio_snapshots', 'timestamp', 'Portfolio snapshots'),
    ('portfolio_total_snapshots', 'timestamp', 'Portfolio totals'),
    ('market_snapshots', 'timestamp', 'Market snapshots'),
    ('hl_fills', 'time_ms', 'Hyperliquid fills'),
    ('spot_transactions', 'created_at', 'Spot transactions'),
    ('trade_annotations', 'updated_at', 'Trade reviews and notes'),
    ('trade_tags', 'created_at', 'Trade tags'),
    ('spot_note_updates', 'created_at', 'Spot journal updates'),
    ('note_revisions', 'revised_at', 'Note edits'),
)
APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_STAGE_LOCK = threading.Lock()


class RestoreError(Exception):
    """A restore step refused or failed; status is the HTTP status for the route."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ── small helpers ────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%S+00:00')


def _folder():
    return os.path.dirname(_pdb.get_db_path())


def _remove_db_files(path):
    for suffix in ('', '-journal', '-wal', '-shm'):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


def _read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_json(path, data):
    tmp = f'{path}.tmp-{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(CHUNK), b''):
            h.update(chunk)
    return h.hexdigest()


def _ro_uri(path):
    """A copy that nothing writes to (an upload, a staged file, a server copy):
    opened read-only and immutable, so SQLite never creates a -wal or -shm next
    to it or changes it, whatever journal mode it was saved in."""
    return Path(os.path.abspath(path)).as_uri() + '?mode=ro&immutable=1'


def _copy_readonly(src_path, dst_path):
    """Copy src_path into dst_path through the backup API as one self-contained
    file (journal_mode=DELETE); written to a temp name and renamed into place."""
    tmp = f'{dst_path}.tmp-{os.getpid()}'
    _remove_db_files(tmp)
    src = dst = None
    try:
        src = sqlite3.connect(_ro_uri(src_path), uri=True)
        dst = sqlite3.connect(tmp)
        src.backup(dst)
        dst.execute('PRAGMA journal_mode=DELETE')
        dst.close()
        dst = None
        src.close()
        src = None
        os.replace(tmp, dst_path)
    except Exception:
        for conn in (dst, src):
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        _remove_db_files(tmp)
        raise


def _free_bytes(folder):
    return shutil.disk_usage(folder).free


def _check_space(folder, incoming_bytes):
    db_bytes = _pdb._db_bytes(_pdb.get_db_path())
    need = STAGE_FREE_FACTOR * max(incoming_bytes, db_bytes) + MIN_FREE_BYTES
    free = _free_bytes(folder)
    if free < need:
        raise RestoreError(f'Not enough free space on the volume: {_pdb._mb(free)} MB free, '
                           f'a restore of this size needs {_pdb._mb(need)} MB.', 507)


def _to_utc(value):
    """A stored time as UTC ISO text, or None. Numbers are epoch seconds or
    milliseconds; text without an offset is UTC (the app stores UTC)."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            secs = value / 1000.0 if value > 1e11 else float(value)
            dt = datetime.fromtimestamp(secs, timezone.utc)
        else:
            text = str(value).strip()
            if not text:
                return None
            if text.endswith('Z'):
                text = text[:-1] + '+00:00'
            dt = datetime.fromisoformat(text)
            dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    if dt > _now() + timedelta(days=2):          # a stray far-future value is not "newest data"
        return None
    return _iso(dt)


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _inspect(conn, integrity):
    """Tables, columns, row counts, newest times (and integrity_check) of a database."""
    out = {}
    if integrity:
        out['integrity'] = [r[0] for r in conn.execute('PRAGMA integrity_check(5)').fetchall()]
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    columns, counts = {}, {}
    for name in names:
        columns[name] = [r[1] for r in conn.execute(f'PRAGMA table_info({_quote(name)})')]
        counts[name] = conn.execute(f'SELECT COUNT(*) FROM {_quote(name)}').fetchone()[0]
    newest = {}
    for table, column, _label in NEWEST_COLUMNS:
        if column in columns.get(table, ()):
            raw = conn.execute(f'SELECT MAX({_quote(column)}) FROM {_quote(table)}').fetchone()[0]
            newest[table] = _to_utc(raw)
    out.update(columns=columns, counts=counts, newest=newest,
               page_size=conn.execute('PRAGMA page_size').fetchone()[0])
    return out


def _run_init_db_on_copy(staged_path, folder):
    """Run init_db on a copy of the staged file in a separate process, with the
    database folder pointed at a temp folder on the volume and the daily backup
    turned off. Raises RestoreError with the last line of the error when it fails."""
    check = os.path.join(folder, CHECK_DIR)
    shutil.rmtree(check, ignore_errors=True)
    os.makedirs(check)
    try:
        shutil.copyfile(staged_path, os.path.join(check, 'portfolio.db'))
        env = dict(os.environ)
        env['RAILWAY_VOLUME_MOUNT_PATH'] = check
        env.pop(_pdb.BACKUP_RETENTION_ENV, None)
        code = ('import src.storage.portfolio_db as p\n'
                'p._backup_db_if_needed = lambda: None\n'
                'p.init_db()\n')
        try:
            r = subprocess.run([sys.executable, '-c', code], cwd=APP_ROOT, env=env,
                               capture_output=True, text=True, timeout=CHECK_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise RestoreError('The app took too long to open this database '
                               f'(over {CHECK_TIMEOUT_S // 60} minutes).', 400)
        if r.returncode != 0:
            lines = [ln.strip() for ln in (r.stderr or '').splitlines() if ln.strip()]
            tail = (lines[-1] if lines else f'exit code {r.returncode}').replace(check, '<copy>')
            raise RestoreError(f'The app could not open this database: {tail[:300]}', 400)
    finally:
        shutil.rmtree(check, ignore_errors=True)


def _build_report(staged_path, source, info, current):
    size = os.path.getsize(staged_path)
    file_tables = set(info['columns'])
    report = {
        'version': 1,
        'staged_at': _iso(_now()),
        'source': source,
        'staged_sha256': _sha256(staged_path),
        'bytes': size,
        'mb': _pdb._mb(size),
        'page_size': info['page_size'],
        'checks': {'integrity': 'ok', 'core_tables': 'ok', 'init_db': 'ok'},
    }
    by_table = []
    for table, column, label in NEWEST_COLUMNS:
        f_val = info['newest'].get(table)
        c_val = current['newest'].get(table) if current else None
        if f_val or c_val:
            by_table.append({'table': table, 'column': column, 'label': label, 'file': f_val, 'current': c_val})
    file_newest = max((v for v in info['newest'].values() if v), default=None)
    current_newest = max((v for v in current['newest'].values() if v), default=None) if current else None
    report['newest'] = {'file': file_newest, 'current': current_newest, 'by_table': by_table}
    warnings = []
    if current is None:
        report['tables'] = {'file': len(file_tables), 'current': None, 'only_in_file': [], 'only_in_current': []}
        report['columns'] = {'only_in_file': {}, 'only_in_current': {}}
        report['rows'] = [{'table': t, 'file': info['counts'][t], 'current': None} for t in sorted(file_tables)]
        report['rows_total'] = {'file': sum(info['counts'].values()), 'current': None}
        warnings.append('There is no current database; the restore creates it.')
    else:
        cur_tables = set(current['columns'])
        only_file = sorted(file_tables - cur_tables)
        only_cur = sorted(cur_tables - file_tables)
        col_file, col_cur = {}, {}
        for t in sorted(file_tables & cur_tables):
            a, b = set(info['columns'][t]), set(current['columns'][t])
            if a - b:
                col_file[t] = sorted(a - b)
            if b - a:
                col_cur[t] = sorted(b - a)
        report['tables'] = {'file': len(file_tables), 'current': len(cur_tables),
                            'only_in_file': only_file, 'only_in_current': only_cur}
        report['columns'] = {'only_in_file': col_file, 'only_in_current': col_cur}
        rows = []
        for t in sorted(file_tables | cur_tables):
            f_n, c_n = info['counts'].get(t), current['counts'].get(t)
            if f_n != c_n:
                rows.append({'table': t, 'file': f_n, 'current': c_n})
        rows.sort(key=lambda r: (-abs((r['file'] or 0) - (r['current'] or 0)), r['table']))
        report['rows'] = rows
        report['rows_total'] = {'file': sum(info['counts'].values()), 'current': sum(current['counts'].values())}
        if only_cur:
            warnings.append(f'{len(only_cur)} table(s) are newer than this copy and will start empty: '
                            + ', '.join(only_cur) + '.')
        if col_cur:
            n = sum(len(v) for v in col_cur.values())
            warnings.append(f'Older layout: the app adds {n} column(s) when it starts '
                            f'(in {", ".join(sorted(col_cur))}).')
        if only_file or col_file:
            parts = list(only_file) + [f'{t}.{c}' for t, cs in sorted(col_file.items()) for c in cs]
            warnings.append('This copy has tables or columns this version of the app does not use '
                            f'({", ".join(parts[:12])}{" …" if len(parts) > 12 else ""}). It was probably '
                            'saved by a newer version; they are kept but ignored.')
        if file_newest and current_newest and file_newest < current_newest:
            gap = datetime.fromisoformat(current_newest) - datetime.fromisoformat(file_newest)
            warnings.append(f'This copy is older than the current data by {_span(gap)}: anything saved '
                            f'after {file_newest[:16].replace("T", " ")} UTC is not in it.')
    report['warnings'] = warnings
    return report


def _span(delta):
    mins = int(delta.total_seconds() // 60)
    if mins < 1:
        return 'under a minute'
    if mins < 60:
        return f'{mins} min'
    hours, mins = divmod(mins, 60)
    if hours < 48:
        return f'{hours} h {mins} min'
    return f'{hours // 24} days {hours % 24} h'


def _discard_files(folder, pending_too=False):
    removed = False
    names = [STAGED_DB, STAGED_REPORT] + ([PENDING] if pending_too else [])
    for name in names:
        path = os.path.join(folder, name)
        if os.path.exists(path):
            removed = True
        if name == STAGED_DB:
            _remove_db_files(path)
        else:
            _remove_quiet(path)
    shutil.rmtree(os.path.join(folder, CHECK_DIR), ignore_errors=True)
    return removed


def _remove_quiet(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _cleanup_stale(folder):
    """Leftovers of a stage that was cut short (older than an hour), and a staged
    copy older than a day that no restore is waiting for. Only this module's names."""
    now = time.time()
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        path = os.path.join(folder, name)
        try:
            age = now - os.path.getmtime(path)
        except OSError:
            continue
        if age < TMP_GRACE_S:
            continue
        if name.startswith(UPLOAD_TMP_PREFIX) or name.startswith(STAGED_DB + '.tmp-') \
                or name.startswith(STAGED_REPORT + '.tmp-'):
            _remove_quiet(path)
        elif name == CHECK_DIR and os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
    staged = os.path.join(folder, STAGED_DB)
    if os.path.exists(staged) and not os.path.exists(os.path.join(folder, PENDING)):
        try:
            if now - os.path.getmtime(staged) > STAGED_TTL_S:
                _discard_files(folder)
        except OSError:
            pass


class _Staging:
    """One stage, discard or apply request at a time (the app runs one worker)."""

    def __enter__(self):
        if not _STAGE_LOCK.acquire(blocking=False):
            raise RestoreError('Another restore step is running. Try again in a minute.', 409)
        return self

    def __exit__(self, *exc):
        _STAGE_LOCK.release()
        return False


# ── stage ────────────────────────────────────────────────────────────────────

def _stage(src_path, source):
    folder = _folder()
    db_path = _pdb.get_db_path()
    with open(src_path, 'rb') as f:
        head = f.read(len(SQLITE_MAGIC))
    if head != SQLITE_MAGIC:
        raise RestoreError('This is not a SQLite database file.', 400)
    _discard_files(folder, pending_too=True)
    staged = os.path.join(folder, STAGED_DB)
    try:
        try:
            _copy_readonly(src_path, staged)
        except sqlite3.DatabaseError as e:
            raise RestoreError(f'This file could not be read as a database: {e}', 400)
        conn = sqlite3.connect(_ro_uri(staged), uri=True)
        try:
            info = _inspect(conn, integrity=True)
        except sqlite3.DatabaseError as e:
            raise RestoreError(f'This file could not be read as a database: {e}', 400)
        finally:
            conn.close()
        if info['integrity'] != ['ok']:
            raise RestoreError('The database integrity check failed: ' + '; '.join(info['integrity'][:3]), 400)
        missing = [t for t in CORE_TABLES if t not in info['columns']]
        if missing:
            raise RestoreError('This is not a Playbook database (missing table: ' + ', '.join(missing) + ').', 400)
        _run_init_db_on_copy(staged, folder)
        current = None
        if os.path.exists(db_path):
            live = sqlite3.connect(db_path)
            try:
                current = _inspect(live, integrity=False)
            finally:
                live.close()
        report = _build_report(staged, source, info, current)
        _write_json(os.path.join(folder, STAGED_REPORT), report)
        return report
    except BaseException:
        _discard_files(folder)
        raise


def _clean_name(name):
    name = os.path.basename(str(name or '').replace('\\', '/')).strip()
    name = ''.join(ch for ch in name if ch.isprintable())
    return name[:200] or 'uploaded file'


def stage_upload(stream, length, filename=None):
    """Stream an upload of `length` bytes to the volume, then stage it. The
    upload's own sha256 is reported so it can be compared with the file on disk."""
    with _Staging():
        folder = _folder()
        _cleanup_stale(folder)
        _check_space(folder, length)
        tmp = os.path.join(folder, f'{UPLOAD_TMP_PREFIX}{os.getpid()}')
        _remove_db_files(tmp)
        h = hashlib.sha256()
        got = 0
        try:
            try:
                f = open(tmp, 'wb')
            except OSError as e:
                raise RestoreError(f'The upload could not be saved: {e.strerror or e}', 507)
            with f:
                while got < length:
                    try:
                        chunk = stream.read(min(CHUNK, length - got))
                    except Exception:
                        raise RestoreError('The upload was cut short. Try again.', 400)
                    if not chunk:
                        break
                    try:
                        f.write(chunk)
                    except OSError as e:
                        raise RestoreError(f'The upload could not be saved: {e.strerror or e}', 507)
                    h.update(chunk)
                    got += len(chunk)
            if got != length:
                raise RestoreError('The upload was cut short. Try again.', 400)
            return _stage(tmp, {'kind': 'upload', 'name': _clean_name(filename), 'sha256': h.hexdigest()})
        finally:
            _remove_db_files(tmp)


def server_sources():
    """Copies on the server a restore can start from: the daily copies and the
    safety copies made before a restore, newest first. Names and sizes only."""
    folder = _folder()
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    for name in names:
        path = os.path.join(folder, name)
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        m_daily = _pdb.BACKUP_NAME_RE.match(name)
        m_safe = _pdb.PRE_RESTORE_NAME_RE.match(name)
        if not (m_daily or m_safe):
            continue
        try:
            stat = os.stat(path)
        except OSError:
            continue
        if m_daily:
            d = m_daily.group(1)
            when = f'{d[:4]}-{d[4:6]}-{d[6:]}'
            kind = 'daily'
        else:
            d, t = m_safe.group(1), m_safe.group(2)
            when = f'{d[:4]}-{d[4:6]}-{d[6:]}T{t[:2]}:{t[2:4]}:{t[4:]}+00:00'
            kind = 'safety'
        out.append({'name': name, 'kind': kind, 'when': when,
                    'saved_at': _iso(datetime.fromtimestamp(stat.st_mtime, timezone.utc)),
                    'mb': _pdb._mb(stat.st_size)})
    out.sort(key=lambda s: s['saved_at'], reverse=True)
    return out


def stage_server_copy(name):
    """Stage one of server_sources() by name (never a path)."""
    with _Staging():
        folder = _folder()
        name = str(name or '')
        if not (_pdb.BACKUP_NAME_RE.match(name) or _pdb.PRE_RESTORE_NAME_RE.match(name)):
            raise RestoreError('No such copy on the server.', 404)
        path = os.path.join(folder, name)
        if os.path.islink(path) or not os.path.isfile(path):
            raise RestoreError('No such copy on the server.', 404)
        _cleanup_stale(folder)
        _check_space(folder, os.path.getsize(path))
        kind = 'daily' if _pdb.BACKUP_NAME_RE.match(name) else 'safety'
        return _stage(path, {'kind': kind, 'name': name})


def staged_report():
    folder = _folder()
    if not os.path.exists(os.path.join(folder, STAGED_DB)):
        return None
    return _read_json(os.path.join(folder, STAGED_REPORT))


def discard():
    """Remove the staged copy and any restore waiting for the next boot."""
    with _Staging():
        return _discard_files(_folder(), pending_too=True)


# ── request ──────────────────────────────────────────────────────────────────

def request_apply(staged_sha256, confirm):
    """Record that the staged copy is to replace the live database at the next
    boot. Needs the typed word and the sha256 the page was shown."""
    if confirm != CONFIRM_WORD:
        raise RestoreError(f'Type {CONFIRM_WORD} to confirm.', 400)
    with _Staging():
        folder = _folder()
        report = staged_report()
        staged = os.path.join(folder, STAGED_DB)
        if report is None:
            raise RestoreError('Nothing is staged. Check a copy first.', 409)
        if not staged_sha256 or staged_sha256 != report.get('staged_sha256') \
                or _sha256(staged) != report.get('staged_sha256'):
            raise RestoreError('The staged copy changed since it was checked. Check it again.', 409)
        pending = {'staged_sha256': report['staged_sha256'], 'requested_at': _iso(_now())}
        _write_json(os.path.join(folder, PENDING), pending)
        print(f"[DB] Restore requested: {report.get('source', {}).get('name')} "
              f"(sha256 {report['staged_sha256'][:12]}); it is applied when the app starts", flush=True)
        return pending


# ── apply at boot ────────────────────────────────────────────────────────────

class _LiveBusy(Exception):
    pass


def _write_into_live(src_path, db_path):
    """Write src_path into the live database through the backup API. The live
    database goes to DELETE journal mode first, which only works when no other
    connection has it open (_LiveBusy otherwise, nothing written); WAL again
    after; then quick_check."""
    dst = sqlite3.connect(db_path, timeout=5)
    try:
        try:
            mode = dst.execute('PRAGMA journal_mode=DELETE').fetchone()[0]
        except sqlite3.OperationalError as e:
            raise _LiveBusy(str(e))
        if str(mode).lower() != 'delete':
            raise _LiveBusy(f'journal mode stayed {mode}')
        src = sqlite3.connect(_ro_uri(src_path), uri=True)
        try:
            src.backup(dst)
        finally:
            src.close()
        dst.execute('PRAGMA journal_mode=WAL')
        check = dst.execute('PRAGMA quick_check').fetchone()[0]
        if check != 'ok':
            raise RestoreError(f'quick_check after the copy: {check}')
    finally:
        dst.close()


def _result_path(folder):
    return os.path.join(folder, RESULT)


def _apply(db_path, folder):
    pending_path = os.path.join(folder, PENDING)
    pending = _read_json(pending_path) or {}
    report = _read_json(os.path.join(folder, STAGED_REPORT))
    staged = os.path.join(folder, STAGED_DB)
    base = {
        'requested_at': pending.get('requested_at'),
        'source': (report or {}).get('source'),
        'staged_sha256': (report or {}).get('staged_sha256'),
        'mb': (report or {}).get('mb'),
        'newest_in_copy': ((report or {}).get('newest') or {}).get('file'),
    }

    def record(status, **extra):
        data = dict(base, status=status, at=_iso(_now()), **extra)
        _write_json(_result_path(folder), data)
        return data

    if not report or not os.path.exists(staged) or not pending.get('staged_sha256') \
            or pending.get('staged_sha256') != report.get('staged_sha256') \
            or _sha256(staged) != report.get('staged_sha256'):
        _remove_quiet(pending_path)
        _discard_files(folder)
        record('not_applied', reason='The staged copy was missing or had changed, so nothing was restored.')
        print('[DB] Restore not applied: the staged copy was missing or had changed', flush=True)
        return
    need = APPLY_FREE_FACTOR * _pdb._db_bytes(db_path) + MIN_FREE_BYTES
    free = _free_bytes(folder)
    if free < need:
        _remove_quiet(pending_path)
        record('not_applied', reason=f'Not enough free space ({_pdb._mb(free)} MB free, {_pdb._mb(need)} MB '
                                     'needed), so nothing was restored.')
        print(f'[DB] Restore not applied: {_pdb._mb(free)} MB free, {_pdb._mb(need)} MB needed', flush=True)
        return
    safety = None
    if os.path.exists(db_path):
        name = f"{SAFETY_PREFIX}{_now().strftime('%Y%m%d-%H%M%S')}.db"
        try:
            _pdb.snapshot_db(os.path.join(folder, name), db_path)
            safety = name
        except Exception as e:
            _remove_quiet(pending_path)
            record('not_applied', reason=f'The safety copy could not be made ({e}), so nothing was restored.')
            print(f'[DB] Restore not applied: the safety copy failed: {e}', flush=True)
            return
    record('applying', safety=safety)
    _remove_quiet(pending_path)
    try:
        _write_into_live(staged, db_path)
    except _LiveBusy as e:
        record('not_applied', safety=safety, reason=f'The database was in use ({e}), so nothing was restored.')
        print(f'[DB] Restore not applied: the database was in use: {e}', flush=True)
        return
    except Exception as e:
        if safety:
            try:
                _write_into_live(os.path.join(folder, safety), db_path)
                record('rolled_back', safety=safety,
                       reason=f'The restore failed ({e}), so the previous database was put back.')
                print(f'[DB] Restore failed and was rolled back from {safety}: {e}', flush=True)
            except Exception as e2:
                record('rollback_failed', safety=safety,
                       reason=f'The restore failed ({e}) and putting the previous database back also '
                              f'failed ({e2}). The previous database is in {safety}.')
                print(f'[DB] RESTORE ROLLBACK FAILED: {e2}; the previous database is in {safety}', flush=True)
        else:
            record('failed', reason=f'The restore failed ({e}).')
            print(f'[DB] Restore failed: {e}', flush=True)
        return
    record('applied', safety=safety)
    _discard_files(folder)
    src_name = (base['source'] or {}).get('name')
    print(f"[DB] Restore applied: {src_name} (sha256 {(base['staged_sha256'] or '')[:12]}); "
          f"previous database kept as {safety}", flush=True)


def _rollback_after_failed_boot(db_path, folder, result):
    safety = result.get('safety')
    base = {k: v for k, v in result.items() if k not in ('status', 'reason', 'at')}
    reason = 'The app did not finish starting after the restore, so the previous database was put back.'
    if not safety or not os.path.exists(os.path.join(folder, safety)):
        _write_json(_result_path(folder), dict(base, status='rollback_failed', at=_iso(_now()),
                                               reason='The app did not finish starting after the restore, '
                                                      'and the safety copy is missing.'))
        print('[DB] RESTORE ROLLBACK FAILED: the first boot after the restore did not finish '
              'and the safety copy is missing', flush=True)
        return
    try:
        _write_into_live(os.path.join(folder, safety), db_path)
    except Exception as e:
        _write_json(_result_path(folder), dict(base, status='rollback_failed', at=_iso(_now()),
                                               reason='The app did not finish starting after the restore, '
                                                      f'and putting the previous database back failed ({e}). '
                                                      f'The previous database is in {safety}.'))
        print(f'[DB] RESTORE ROLLBACK FAILED: {e}; the previous database is in {safety}', flush=True)
        return
    _write_json(_result_path(folder), dict(base, status='rolled_back_after_failed_boot', at=_iso(_now()),
                                           reason=reason))
    print(f'[DB] Restore rolled back from {safety}: the first boot after the restore did not finish', flush=True)


def apply_pending_restore():
    """First step of init_db at boot. Rolls back a restore whose first boot never
    finished, then applies a confirmed restore, then clears stale leftovers.
    Never raises (the boot must go on)."""
    try:
        db_path = _pdb.get_db_path()
        folder = os.path.dirname(db_path)
        result = _read_json(_result_path(folder))
        if result and result.get('status') in ('applying', 'applied'):
            _rollback_after_failed_boot(db_path, folder, result)
            if os.path.exists(os.path.join(folder, PENDING)):
                _remove_quiet(os.path.join(folder, PENDING))
                print('[DB] Restore request dropped: a rollback ran at this boot', flush=True)
        elif os.path.exists(os.path.join(folder, PENDING)):
            _apply(db_path, folder)
        _cleanup_stale(folder)
    except Exception as e:
        print(f'[DB] Restore step at boot failed: {e}', flush=True)


def boot_completed():
    """Called when web_portfolio has finished importing: a restore applied at
    this boot is complete. Never raises."""
    try:
        path = _result_path(_folder())
        result = _read_json(path)
        if result and result.get('status') == 'applied':
            result['status'] = 'completed'
            result['completed_at'] = _iso(_now())
            _write_json(path, result)
            print('[DB] Restore complete: the app started on the restored database', flush=True)
    except Exception as e:
        print(f'[DB] Restore completion could not be recorded: {e}', flush=True)


def status():
    """Read-only summary for GET /api/backup/restore."""
    folder = _folder()
    try:
        free_mb = _pdb._mb(_free_bytes(folder))
    except OSError:
        free_mb = None
    return {
        'staged': staged_report(),
        'pending': os.path.exists(os.path.join(folder, PENDING)),
        'result': _read_json(_result_path(folder)),
        'sources': server_sources(),
        'confirm_word': CONFIRM_WORD,
        'max_upload_mb': _pdb._mb(MAX_UPLOAD_BYTES),
        'free_mb': free_mb,
    }
