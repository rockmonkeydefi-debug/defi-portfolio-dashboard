"""Off-server copy (Landing 12): a daily encrypted copy of the database in a
bucket Glenn owns (Cloudflare R2, or any S3-compatible storage).

Each run:
1. refuses a database with no portfolio snapshots (a fresh or emptied volume
   is never uploaded over the good copies);
2. copies the live database through SQLite's backup API (portfolio_db.
   snapshot_db, the same copy Export DB makes) into the container's temp
   folder, never the volume;
3. compresses it (gzip) and encrypts it to an age public key
   (OFFSITE_AGE_RECIPIENT). The server holds only that public key, so it
   cannot read its own uploads; the private key stays with Glenn;
4. uploads daily/portfolio_YYYYMMDD-HHMMSS.db.gz.age and a small encrypted
   settings file next to it (the wallet list and the advisor and scanner
   settings, in Import Settings' format; never .env, API keys, the password
   hash or the Telegram token). The first upload of each UTC month is also
   written to monthly/portfolio_YYYYMM.*;
5. records the outcome in portfolio_offsite_state.json next to the database
   (no keys, no paths) and removes its temp files.

The app never deletes anything in the bucket. Retention and protection are
bucket rules Glenn sets: daily/ deleted after 35 days and locked for 30,
monthly/ deleted after 400 days and locked for 365. A stolen key or a bug can
add files but cannot remove the good ones.

Schedule: one daemon thread (start_thread) in the app worker, started only
when the Railway variable OFFSITE_BACKUP is on. It waits 10 minutes after
boot, then checks every 15 minutes: a copy is due once a day at
OFFSITE_HOUR_UTC (default 10:00 UTC), retried every hour after a failure. A
deploy does not trigger an upload. With no successful copy for 36 hours it
sends one alert a day (Telegram, when it is on).

Restore: download a daily/ or monthly/ file, then on your computer
    age -d -i KEYFILE FILE.db.gz.age | gunzip > restore.db
and upload restore.db in Settings -> Backup & Security -> Restore...

boto3 and pyrage are imported only when a copy is made, so a missing package
shows as a failed copy, never as an app that cannot start."""

import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from src.storage import portfolio_db as _pdb

ENV_SWITCH = 'OFFSITE_BACKUP'
ENV_ENDPOINT = 'OFFSITE_S3_ENDPOINT'
ENV_BUCKET = 'OFFSITE_S3_BUCKET'
ENV_KEY_ID = 'OFFSITE_S3_ACCESS_KEY_ID'
ENV_SECRET = 'OFFSITE_S3_SECRET_ACCESS_KEY'
ENV_REGION = 'OFFSITE_S3_REGION'
ENV_RECIPIENT = 'OFFSITE_AGE_RECIPIENT'
ENV_HOUR = 'OFFSITE_HOUR_UTC'
REQUIRED = (ENV_ENDPOINT, ENV_BUCKET, ENV_KEY_ID, ENV_SECRET, ENV_RECIPIENT)

STATE_NAME = 'portfolio_offsite_state.json'
TMP_PREFIX = 'playbook_offsite_'
DAILY_PREFIX = 'daily/'
MONTHLY_PREFIX = 'monthly/'
DB_SUFFIX = '.db.gz.age'
CONFIG_SUFFIX = '.config.json.age'
CONFIG_FORMAT = 'playbook-offsite-config-1'
DEFAULT_HOUR_UTC = 10
DEFAULT_REGION = 'auto'
FIRST_DELAY_S = 600
POLL_S = 900
RETRY_AFTER_FAILURE_S = 3600
UPLOAD_ATTEMPTS = 3
UPLOAD_WAITS_S = (30, 120)
STALE_AFTER_H = 36
ALERT_EVERY_S = 24 * 3600
TMP_GRACE_S = 3600
TMP_MARGIN_BYTES = 64 * 1024 * 1024
GZIP_LEVEL = 6
CHUNK = 1 << 20
ERROR_MAX = 300
REMOTE_RETENTION = ('Set in the bucket, not by the app: daily/ copies are deleted after 35 days '
                    '(locked for 30), monthly/ copies after 400 days (locked for 365).')
RESTORE_HOW = ('Download a daily/ or monthly/ .db.gz.age file, run '
               '"age -d -i KEYFILE FILE.db.gz.age | gunzip > restore.db" on your computer, '
               'then upload restore.db in Settings -> Backup & Security -> Restore...')
STATE_KEYS = ('enabled_since', 'last_attempt_at', 'last_attempt_trigger', 'last_success_at', 'last_object',
              'last_config_object', 'last_monthly_object', 'db_mb', 'upload_mb', 'db_sha256', 'object_sha256',
              'seconds', 'consecutive_failures', 'last_error', 'last_error_at', 'monthly_error', 'config_error',
              'last_alert_at', 'last_alert_result')

_RUN_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_THREAD = None


class OffsiteError(Exception):
    """A request the route refuses; status is the HTTP status."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class _Failed(Exception):
    """A run that failed; the message is already safe to log and show."""


# ── small helpers ────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc)


def _sleep(seconds):
    time.sleep(seconds)


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%S+00:00')


def _parse(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _tmpdir():
    return tempfile.gettempdir()


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(CHUNK), b''):
            h.update(chunk)
    return h.hexdigest()


def _state_path():
    return os.path.join(os.path.dirname(_pdb.get_db_path()), STATE_NAME)


def read_state():
    try:
        with open(_state_path(), 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _update_state(**changes):
    with _STATE_LOCK:
        state = read_state()
        state.update(changes)
        path = _state_path()
        tmp = f'{path}.tmp-{os.getpid()}'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
        return state


# ── settings (Railway variables) ─────────────────────────────────────────────

def load_config(environ=None):
    """The settings from the environment. 'configured' is true only when the
    switch is on and every required value is present and valid. The key id,
    secret and recipient are returned for the upload and never shown."""
    env = os.environ if environ is None else environ
    enabled = env.get(ENV_SWITCH, '').strip().lower() in ('on', 'true', '1', 'yes')
    values = {name: env.get(name, '').strip() for name in REQUIRED}
    missing = [name for name in REQUIRED if not values[name]]
    problems = []
    endpoint = values[ENV_ENDPOINT]
    if endpoint and not (endpoint.startswith('https://') and urlparse(endpoint).hostname):
        problems.append(f'{ENV_ENDPOINT} must be an https:// address')
    recipient = values[ENV_RECIPIENT]
    if recipient.upper().startswith('AGE-SECRET-KEY-'):
        problems.append(f'{ENV_RECIPIENT} holds a SECRET key. Delete that value from Railway and put the '
                        'public key (age1...) there; the secret key stays on your computer')
        recipient = ''
    elif recipient and not recipient.startswith('age1'):
        problems.append(f'{ENV_RECIPIENT} must be an age public key (age1...)')
    hour_text = env.get(ENV_HOUR, '').strip()
    hour = DEFAULT_HOUR_UTC
    if hour_text:
        try:
            hour = int(hour_text)
            if not 0 <= hour <= 23:
                raise ValueError
        except ValueError:
            problems.append(f'{ENV_HOUR} must be a whole hour from 0 to 23')
            hour = DEFAULT_HOUR_UTC
    return {
        'enabled': enabled,
        'configured': enabled and not missing and not problems,
        'missing': missing,
        'problems': problems,
        'endpoint': endpoint,
        'bucket': values[ENV_BUCKET],
        'key_id': values[ENV_KEY_ID],
        'secret': values[ENV_SECRET],
        'region': env.get(ENV_REGION, '').strip() or DEFAULT_REGION,
        'recipient': recipient,
        'hour_utc': hour,
    }


def _recipient_hint(recipient):
    return f'{recipient[:8]}...{recipient[-6:]}' if len(recipient) > 16 else None


def _describe(exc, cfg=None):
    """One line for the log and the status page: the error's class, its S3
    code when there is one, and its message with addresses' query strings and
    any credential removed, cut to ERROR_MAX characters."""
    text = str(exc) or type(exc).__name__
    text = re.sub(r'(https?://[^\s"\'?]+)\?[^\s"\']*', r'\1', text)
    for secret in ((cfg or {}).get('secret'), (cfg or {}).get('key_id')):
        if secret:
            text = text.replace(secret, '[hidden]')
    code = None
    response = getattr(exc, 'response', None)
    if isinstance(response, dict):
        code = (response.get('Error') or {}).get('Code')
    label = type(exc).__name__ + (f' {code}' if code and code not in text else '')
    out = f'{label}: {" ".join(text.split())}'
    return out if len(out) <= ERROR_MAX else out[:ERROR_MAX - 3] + '...'


# ── the copy ─────────────────────────────────────────────────────────────────

def _make_client(cfg):
    import boto3
    from botocore.config import Config
    return boto3.client(
        's3', endpoint_url=cfg['endpoint'], region_name=cfg['region'],
        aws_access_key_id=cfg['key_id'], aws_secret_access_key=cfg['secret'],
        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                      retries={'max_attempts': 2, 'mode': 'standard'},
                      connect_timeout=10, read_timeout=120,
                      # boto3 1.36+ adds checksum headers by default, which some
                      # S3-compatible stores reject; send them only when required.
                      request_checksum_calculation='when_required',
                      response_checksum_validation='when_required'))


def _recipients(cfg):
    from pyrage import x25519
    return [x25519.Recipient.from_str(cfg['recipient'])]


def _has_snapshots(db_path):
    """True when the database has at least one portfolio snapshot. Opened
    read-only; a missing table counts as empty."""
    try:
        conn = sqlite3.connect(Path(os.path.abspath(db_path)).as_uri() + '?mode=ro', uri=True)
    except sqlite3.Error:
        return False
    try:
        return conn.execute('SELECT 1 FROM portfolio_snapshots LIMIT 1').fetchone() is not None
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _clean_tmp(folder, now_ts=None):
    """Remove this module's temp files older than TMP_GRACE_S (a run cut
    short by a restart leaves them). Younger ones may belong to a run in
    progress and are kept."""
    now_ts = time.time() if now_ts is None else now_ts
    removed = 0
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    for name in names:
        if not name.startswith(TMP_PREFIX):
            continue
        path = os.path.join(folder, name)
        try:
            if os.path.isfile(path) and not os.path.islink(path) and now_ts - os.path.getmtime(path) > TMP_GRACE_S:
                os.remove(path)
                removed += 1
        except OSError:
            pass
    return removed


def _exists(client, bucket, key):
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception as e:
        response = getattr(e, 'response', None)
        if isinstance(response, dict):
            code = str((response.get('Error') or {}).get('Code', ''))
            status = (response.get('ResponseMetadata') or {}).get('HTTPStatusCode')
            if code in ('404', 'NoSuchKey', 'NotFound') or status == 404:
                return False
        raise


def _put(client, cfg, key, path=None, data=None, metadata=None):
    kwargs = {'Bucket': cfg['bucket'], 'Key': key, 'ContentType': 'application/octet-stream',
              'Metadata': metadata or {}}
    if path is not None:
        with open(path, 'rb') as f:
            client.put_object(Body=f, ContentLength=os.path.getsize(path), **kwargs)
    else:
        client.put_object(Body=data, ContentLength=len(data), **kwargs)


def _with_retries(action, what, cfg):
    """Run action() up to UPLOAD_ATTEMPTS times, waiting UPLOAD_WAITS_S
    between tries; raises _Failed with the last error."""
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        try:
            return action()
        except Exception as e:
            err = _describe(e, cfg)
            print(f'[Offsite] {what} failed (attempt {attempt}/{UPLOAD_ATTEMPTS}): {err}', flush=True)
            if attempt == UPLOAD_ATTEMPTS:
                raise _Failed(err)
            _sleep(UPLOAD_WAITS_S[min(attempt - 1, len(UPLOAD_WAITS_S) - 1)])


def _config_bytes(config_fn, now):
    payload = {
        'format': CONFIG_FORMAT,
        'exported_at': _iso(now),
        'note': ('Import Settings restores "wallets". advisor_settings and scanner_settings are kept for '
                 'reference. API keys, the password hash and the Telegram token are not included.'),
    }
    data = config_fn() if config_fn else {}
    for key, value in (data or {}).items():
        if key not in payload:
            payload[key] = value
    return json.dumps(payload, indent=2, sort_keys=True).encode('utf-8')


def _make_copy(cfg, config_fn, now):
    """One upload. Returns the success record; raises _Failed."""
    db_path = _pdb.get_db_path()
    if not os.path.exists(db_path) or not _has_snapshots(db_path):
        raise _Failed('Skipped: the database has no portfolio snapshots, so it looks new or empty; '
                      'it is not uploaded over the good copies')
    tmp = _tmpdir()
    _clean_tmp(tmp)
    need = 2 * (_pdb._size(db_path) + _pdb._size(db_path + '-wal')) + TMP_MARGIN_BYTES
    free = shutil.disk_usage(tmp).free
    if free < need:
        raise _Failed(f"Not enough space in the container's temp folder: {_pdb._mb(free)} MB free, "
                      f'{_pdb._mb(need)} MB needed')
    stamp = now.strftime('%Y%m%d-%H%M%S')
    month = now.strftime('%Y%m')
    raw = os.path.join(tmp, f'{TMP_PREFIX}{stamp}_{os.getpid()}.db')
    packed = raw + '.gz'
    sealed = packed + '.age'
    started = time.monotonic()
    try:
        try:
            raw_bytes = _pdb.snapshot_db(raw, db_path)
            db_sha = _sha256(raw)
            with open(raw, 'rb') as src, open(packed, 'wb') as out:
                with gzip.GzipFile(filename=f'portfolio_{stamp}.db', mode='wb', compresslevel=GZIP_LEVEL,
                                   fileobj=out, mtime=int(now.timestamp())) as gz:
                    shutil.copyfileobj(src, gz, CHUNK)
            _remove_quietly(raw)
            import pyrage
            recipients = _recipients(cfg)
            pyrage.encrypt_file(packed, sealed, recipients)
            _remove_quietly(packed)
            sealed_sha = _sha256(sealed)
            sealed_bytes = os.path.getsize(sealed)
        except Exception as e:
            raise _Failed(f'Copy failed: {_describe(e, cfg)}')
        config_error = None
        try:
            config_blob = pyrage.encrypt(_config_bytes(config_fn, now), recipients)
        except Exception as e:
            config_blob = None
            config_error = f'Settings file not made: {_describe(e, cfg)}'
            print(f'[Offsite] {config_error}', flush=True)
        try:
            client = _make_client(cfg)
        except Exception as e:
            raise _Failed(f'Storage client failed: {_describe(e, cfg)}')
        meta = {'db-sha256': db_sha, 'db-bytes': str(raw_bytes), 'format': 'sqlite+gzip+age'}
        db_key = f'{DAILY_PREFIX}portfolio_{stamp}{DB_SUFFIX}'
        config_key = f'{DAILY_PREFIX}portfolio_{stamp}{CONFIG_SUFFIX}'
        _with_retries(lambda: _put(client, cfg, db_key, path=sealed, metadata=meta), 'Upload', cfg)
        if config_blob is not None:
            try:
                _with_retries(lambda: _put(client, cfg, config_key, data=config_blob,
                                           metadata={'format': CONFIG_FORMAT}), 'Settings upload', cfg)
            except _Failed as e:
                config_error = f'Settings file not uploaded: {e}'
        monthly_key = monthly_error = None
        month_db = f'{MONTHLY_PREFIX}portfolio_{month}{DB_SUFFIX}'
        try:
            if not _exists(client, cfg['bucket'], month_db):
                _put(client, cfg, month_db, path=sealed, metadata=meta)
                monthly_key = month_db
                if config_blob is not None:
                    _put(client, cfg, f'{MONTHLY_PREFIX}portfolio_{month}{CONFIG_SUFFIX}', data=config_blob,
                         metadata={'format': CONFIG_FORMAT})
        except Exception as e:
            monthly_error = f'Monthly copy not made (tried again at the next upload): {_describe(e, cfg)}'
            print(f'[Offsite] {monthly_error}', flush=True)
        return {
            'last_object': db_key,
            'last_config_object': config_key if config_error is None else None,
            'monthly_object': monthly_key,
            'db_mb': _pdb._mb(raw_bytes),
            'upload_mb': _pdb._mb(sealed_bytes),
            'db_sha256': db_sha,
            'object_sha256': sealed_sha,
            'seconds': round(time.monotonic() - started, 1),
            'monthly_error': monthly_error,
            'config_error': config_error,
        }
    finally:
        for path in (raw, packed, sealed):
            for suffix in ('', '.tmp-' + str(os.getpid())):
                _remove_quietly(path + suffix)


def run_once(trigger='schedule', config_fn=None, lock_held=False):
    """Make one off-server copy now and record the outcome. Returns
    {'status': 'ok' | 'failed' | 'busy' | 'off' | 'not_configured', ...}.
    Never raises."""
    if not lock_held and not _RUN_LOCK.acquire(blocking=False):
        return {'status': 'busy'}
    try:
        cfg = load_config()
        if not cfg['enabled']:
            return {'status': 'off'}
        if not cfg['configured']:
            return {'status': 'not_configured', 'missing': cfg['missing'], 'problems': cfg['problems']}
        now = _now()
        _update_state(last_attempt_at=_iso(now), last_attempt_trigger=trigger)
        try:
            record = _make_copy(cfg, config_fn, now)
        except Exception as e:
            err = str(e) if isinstance(e, _Failed) else _describe(e, cfg)
            prev = read_state().get('consecutive_failures') or 0
            _update_state(consecutive_failures=prev + 1, last_error=err, last_error_at=_iso(_now()))
            print(f'[Offsite] Copy failed ({trigger}): {err}', flush=True)
            return {'status': 'failed', 'error': err}
        monthly = record.pop('monthly_object')
        changes = dict(record, last_success_at=_iso(_now()), consecutive_failures=0, last_error=None,
                       last_error_at=None)
        if monthly:
            changes['last_monthly_object'] = monthly
        _update_state(**changes)
        line = (f"[Offsite] Uploaded {record['last_object']} ({record['upload_mb']} MB from "
                f"{record['db_mb']} MB, {record['seconds']} s)")
        if monthly:
            line += f'; monthly copy {monthly}'
        print(line, flush=True)
        return dict(record, status='ok', monthly_object=monthly)
    except Exception as e:
        print(f'[Offsite] Copy failed ({trigger}): {_describe(e)}', flush=True)
        return {'status': 'failed', 'error': _describe(e)}
    finally:
        _RUN_LOCK.release()


# ── schedule, staleness, alerts ──────────────────────────────────────────────

def next_due(state, now, hour_utc=DEFAULT_HOUR_UTC):
    """When the next copy is due. Never succeeded: now. Succeeded since the
    latest daily slot: the next slot. Otherwise the latest slot, or an hour
    after the last failed attempt."""
    slot = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if now < slot:
        slot -= timedelta(days=1)
    ok = _parse(state.get('last_success_at'))
    if ok is not None and ok >= slot:
        return slot + timedelta(days=1)
    tried = _parse(state.get('last_attempt_at'))
    if state.get('consecutive_failures') and tried is not None and (ok is None or tried > ok):
        return tried + timedelta(seconds=RETRY_AFTER_FAILURE_S)
    return slot if ok is not None else now


def stale_since(state, now):
    """The time the 'no copy' clock started (the last success, or when the
    switch was first seen on) when that is STALE_AFTER_H or more ago; else
    None."""
    base = _parse(state.get('last_success_at')) or _parse(state.get('enabled_since'))
    if base is not None and now - base >= timedelta(hours=STALE_AFTER_H):
        return base
    return None


def _telegram_safe(text):
    # The Telegram sender uses Markdown, where _ * ` [ ] start formatting.
    return re.sub(r'[_*`\[\]]', ' ', text)


def alert_text(state, cfg, since, now):
    hours = int((now - since).total_seconds() // 3600)
    when = since.strftime('%b %d %H:%M UTC')
    if state.get('last_success_at'):
        head = f'no successful upload since {when} ({hours} h)'
    else:
        head = f'no successful upload since it was switched on ({when}, {hours} h ago)'
    if not cfg.get('configured'):
        reason = 'Not set up: ' + '; '.join(
            ([f"missing {', '.join(cfg.get('missing') or [])}"] if cfg.get('missing') else [])
            + list(cfg.get('problems') or []))
    else:
        reason = f"Last error: {state.get('last_error') or 'none recorded'}"
    return _telegram_safe(f'Playbook off-server copy: {head}. {reason}. '
                          'See Settings, Backup and Security, and the Railway log lines starting with [Offsite].')


def _maybe_alert(state, cfg, now, alert_fn):
    since = stale_since(state, now)
    if since is None or alert_fn is None:
        return None
    last = _parse(state.get('last_alert_at'))
    if last is not None and (now - last).total_seconds() < ALERT_EVERY_S:
        return None
    try:
        ok, err = alert_fn(alert_text(state, cfg, since, now))
    except Exception as e:
        ok, err = False, _describe(e)
    # A Telegram error can quote its request URL, /bot<id>:<token>/...
    err = re.sub(r'bot\d+:[A-Za-z0-9_-]+', 'bot[hidden]', str(err))
    result = 'sent' if ok else f'not sent: {err}'
    result = result if len(result) <= 200 else result[:197] + '...'
    _update_state(last_alert_at=_iso(now), last_alert_result=result)
    print(f'[Offsite] Stale alert {result}', flush=True)
    return result


def tick(config_fn=None, alert_fn=None, now=None):
    """One check of the loop: note when the switch was first seen on, make a
    copy when one is due, and alert when copies have stopped. Returns what
    it did ('off', 'not_due', 'not_configured', or run_once's status)."""
    cfg = load_config()
    if not cfg['enabled']:
        return 'off'
    now = now or _now()
    state = read_state()
    if not state.get('enabled_since'):
        state = _update_state(enabled_since=_iso(now))
    did = 'not_configured'
    if cfg['configured']:
        did = 'not_due'
        if now >= next_due(state, now, cfg['hour_utc']):
            did = run_once('schedule', config_fn)['status']
            state = read_state()
            now = _now()
    _maybe_alert(state, cfg, now, alert_fn)
    return did


def _loop(config_fn, alert_fn):
    _sleep(FIRST_DELAY_S)
    while True:
        try:
            tick(config_fn, alert_fn)
        except Exception as e:
            print(f'[Offsite] Loop error: {_describe(e)}', flush=True)
        _sleep(POLL_S)


def start_thread(config_fn=None, alert_fn=None):
    """Start the daily thread once per worker, only when OFFSITE_BACKUP is
    on. Returns True when it started a thread. Never raises."""
    global _THREAD
    try:
        cfg = load_config()
        if not cfg['enabled']:
            print(f'[Offsite] Off: {ENV_SWITCH} is not set', flush=True)
            return False
        if _THREAD is not None and _THREAD.is_alive():
            return False
        if cfg['configured']:
            print(f"[Offsite] On: a copy daily at {cfg['hour_utc']:02d}:00 UTC to bucket {cfg['bucket']}; "
                  f'first check in {FIRST_DELAY_S // 60} min', flush=True)
        else:
            issues = ([f"missing {', '.join(cfg['missing'])}"] if cfg['missing'] else []) + cfg['problems']
            print(f"[Offsite] Not set up: {'; '.join(issues)}", flush=True)
        _THREAD = threading.Thread(target=_loop, args=(config_fn, alert_fn), name='offsite-backup', daemon=True)
        _THREAD.start()
        return True
    except Exception as e:
        print(f'[Offsite] Thread not started: {_describe(e)}', flush=True)
        return False


def start_manual_run(config_fn=None):
    """Upload now (Settings button): checks the settings, takes the run lock,
    and runs the copy in a background thread. Raises OffsiteError."""
    cfg = load_config()
    if not cfg['enabled']:
        raise OffsiteError(f'The off-server copy is off. Set {ENV_SWITCH}=on in Railway first.', 400)
    if not cfg['configured']:
        issues = ([f"missing {', '.join(cfg['missing'])}"] if cfg['missing'] else []) + cfg['problems']
        raise OffsiteError(f"The off-server copy is not set up: {'; '.join(issues)}.", 400)
    if not _RUN_LOCK.acquire(blocking=False):
        raise OffsiteError('An upload is already running.', 409)
    try:
        threading.Thread(target=run_once, args=('manual', config_fn), kwargs={'lock_held': True},
                         name='offsite-backup-manual', daemon=True).start()
    except Exception:
        _RUN_LOCK.release()
        raise


# ── status (GET /api/backup/offsite and /api/backup/status) ──────────────────

def status(now=None):
    """Read-only. Never includes the key id, the secret, the full public key
    or any path."""
    cfg = load_config()
    now = now or _now()
    state = read_state()
    out = {key: state.get(key) for key in STATE_KEYS}
    out['consecutive_failures'] = out['consecutive_failures'] or 0
    out.update({
        'enabled': cfg['enabled'],
        'configured': cfg['configured'],
        'missing': cfg['missing'],
        'problems': cfg['problems'],
        'switch': f'{ENV_SWITCH}=on (Railway variable)',
        'destination': ({'endpoint_host': urlparse(cfg['endpoint']).hostname, 'bucket': cfg['bucket'] or None,
                         'region': cfg['region']} if cfg['enabled'] and cfg['endpoint'] else None),
        'recipient': _recipient_hint(cfg['recipient']),
        'hour_utc': cfg['hour_utc'],
        'schedule': f"daily at {cfg['hour_utc']:02d}:00 UTC; after a failure, again every hour",
        'running': _RUN_LOCK.locked(),
        'thread_alive': bool(_THREAD is not None and _THREAD.is_alive()),
        'next_due_at': _iso(next_due(state, now, cfg['hour_utc'])) if cfg['configured'] else None,
        'stale': bool(cfg['enabled'] and stale_since(state, now) is not None),
        'stale_after_hours': STALE_AFTER_H,
        'remote_retention': REMOTE_RETENTION,
        'restore': RESTORE_HOW,
    })
    return out
