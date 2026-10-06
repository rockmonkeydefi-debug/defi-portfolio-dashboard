"""Landing 12: the off-server copy (src/storage/offsite_backup.py and the
/api/backup/offsite routes).

Real SQLite files under tmp_path (RAILWAY_VOLUME_MOUNT_PATH points the app at
a temp "volume"), real gzip and real age encryption (pyrage). The bucket is a
fake S3 client that keeps objects in memory and, like a bucket lock, refuses
to overwrite one; no network."""

import gzip
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from pyrage import decrypt, x25519

import web_portfolio as wp
from src.storage import offsite_backup as ob
from src.storage import portfolio_db

SECRET = 'S3cr3tValueThatMustNeverShow'
KEY_ID = 'KEYID0123456789VISIBLE'
ENDPOINT = 'https://acct123.r2.cloudflarestorage.com'
H = {'X-Playbook-Backup': '1'}
UTC = timezone.utc


class _ClientError(Exception):
    def __init__(self, code, status, message='An error occurred'):
        super().__init__(f'An error occurred ({code}) when calling the operation: {message}')
        self.response = {'Error': {'Code': code, 'Message': message}, 'ResponseMetadata': {'HTTPStatusCode': status}}


class FakeS3:
    """put_object / head_object over a dict. fail_puts: that many puts raise
    first. An existing key is refused, as an R2 bucket lock refuses it."""

    def __init__(self, fail_puts=0, put_error=None, head_error=None):
        self.objects = {}
        self.calls = []
        self.fail_puts = fail_puts
        self.put_error = put_error or ConnectionError('Could not connect to the endpoint URL')
        self.head_error = head_error

    def put_object(self, Bucket, Key, Body, ContentLength, ContentType, Metadata):
        self.calls.append(('put', Key))
        if self.fail_puts:
            self.fail_puts -= 1
            raise self.put_error
        data = Body.read() if hasattr(Body, 'read') else Body
        assert len(data) == ContentLength
        assert ContentType == 'application/octet-stream'
        if Key in self.objects:
            raise _ClientError('AccessDenied', 403, 'Object is locked')
        self.objects[Key] = {'bucket': Bucket, 'data': data, 'meta': dict(Metadata)}
        return {}

    def head_object(self, Bucket, Key):
        self.calls.append(('head', Key))
        if self.head_error:
            raise self.head_error
        if Key not in self.objects:
            raise _ClientError('404', 404, 'Not Found')
        return {}


# ── fixtures and helpers ─────────────────────────────────────────────────────

@pytest.fixture
def volume(tmp_path, monkeypatch):
    vol = tmp_path / 'volume'
    vol.mkdir()
    monkeypatch.setenv('RAILWAY_VOLUME_MOUNT_PATH', str(vol))
    monkeypatch.delenv('BACKUP_RETENTION', raising=False)
    for name in (ob.ENV_SWITCH, ob.ENV_HOUR, ob.ENV_REGION) + ob.REQUIRED:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(portfolio_db, '_backup_db_if_needed', lambda: None)
    tmp = tmp_path / 'container_tmp'
    tmp.mkdir()
    monkeypatch.setattr(ob, '_tmpdir', lambda: str(tmp))
    monkeypatch.setattr(ob, '_THREAD', None)
    return vol


@pytest.fixture
def ctmp(volume):
    return ob._tmpdir()


@pytest.fixture
def live(volume):
    portfolio_db.init_db()
    _add_snapshots(volume / 'portfolio.db', 5, '2026-10-05T10:00:00')
    return volume / 'portfolio.db'


@pytest.fixture
def ident():
    return x25519.Identity.generate()


@pytest.fixture
def on(volume, ident, monkeypatch):
    monkeypatch.setenv(ob.ENV_SWITCH, 'on')
    monkeypatch.setenv(ob.ENV_ENDPOINT, ENDPOINT)
    monkeypatch.setenv(ob.ENV_BUCKET, 'playbook-backups')
    monkeypatch.setenv(ob.ENV_KEY_ID, KEY_ID)
    monkeypatch.setenv(ob.ENV_SECRET, SECRET)
    monkeypatch.setenv(ob.ENV_RECIPIENT, str(ident.to_public()))
    return ident


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(ob, '_make_client', lambda cfg: fake)
    return fake


@pytest.fixture
def sleeps(monkeypatch):
    out = []
    monkeypatch.setattr(ob, '_sleep', out.append)
    return out


@pytest.fixture
def client(volume, monkeypatch):
    monkeypatch.setattr(wp, 'get_password_hash', lambda: 'x')
    wp.app.config['TESTING'] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess['authenticated'] = True
    return c


def _add_snapshots(db, n, ts, wallet='w-test'):
    conn = sqlite3.connect(db)
    for _ in range(n):
        conn.execute("INSERT INTO portfolio_snapshots (user_id, timestamp, wallet, status) VALUES (1, ?, ?, 'completed')",
                     (ts, wallet))
    conn.commit()
    conn.close()


def _count(db, table='portfolio_snapshots'):
    conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    try:
        return conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    finally:
        conn.close()


def _config():
    return {'wallets': {'0xabc': {'label': 'Desktop Hot'}}, 'advisor_settings': {'maxfi_exposure_cap_pct': 30.0},
            'scanner_settings': None}


def _open_db(fake, key, ident, tmp_path):
    raw = gzip.decompress(decrypt(fake.objects[key]['data'], [ident]))
    path = tmp_path / ('restored_' + key.replace('/', '_') + '.db')
    path.write_bytes(raw)
    return path, raw


def _keys(fake, prefix):
    return sorted(k for k in fake.objects if k.startswith(prefix))


def _at(monkeypatch, *times):
    """_now returns these times in turn, then the last one."""
    seq = list(times)
    monkeypatch.setattr(ob, '_now', lambda: seq.pop(0) if len(seq) > 1 else seq[0])


# ── settings ─────────────────────────────────────────────────────────────────

def test_off_when_the_switch_is_not_set(volume, monkeypatch):
    started = []
    monkeypatch.setattr(ob.threading, 'Thread', lambda *a, **k: started.append(k) or pytest.fail('no thread'))
    cfg = ob.load_config()
    assert cfg['enabled'] is False and cfg['configured'] is False
    assert ob.start_thread() is False and started == []
    assert ob.run_once('manual') == {'status': 'off'}
    st = ob.status()
    assert st['enabled'] is False and st['stale'] is False and st['destination'] is None
    assert not os.path.exists(ob._state_path())


@pytest.mark.parametrize('value', ['on', 'ON', 'true', '1', 'yes'])
def test_the_switch_accepts_the_usual_words(value):
    assert ob.load_config({ob.ENV_SWITCH: value})['enabled'] is True


def test_missing_settings_are_named_never_their_values(volume, monkeypatch):
    monkeypatch.setenv(ob.ENV_SWITCH, 'on')
    monkeypatch.setenv(ob.ENV_SECRET, SECRET)
    monkeypatch.setenv(ob.ENV_KEY_ID, KEY_ID)
    st = ob.status()
    assert st['enabled'] is True and st['configured'] is False
    assert st['missing'] == [ob.ENV_ENDPOINT, ob.ENV_BUCKET, ob.ENV_RECIPIENT]
    text = json.dumps(st)
    assert SECRET not in text and KEY_ID not in text
    assert ob.run_once('manual')['status'] == 'not_configured'


def test_a_secret_age_key_in_the_recipient_variable_is_refused_and_not_shown(on, monkeypatch):
    secret_key = str(x25519.Identity.generate())
    assert secret_key.startswith('AGE-SECRET-KEY-')
    monkeypatch.setenv(ob.ENV_RECIPIENT, secret_key)
    cfg = ob.load_config()
    assert cfg['configured'] is False and cfg['recipient'] == ''
    assert any('SECRET key' in p for p in cfg['problems'])
    st = ob.status()
    assert st['recipient'] is None
    assert secret_key not in json.dumps(st)
    assert secret_key[15:30] not in json.dumps(st)


@pytest.mark.parametrize('name,value,problem', [
    (ob.ENV_ENDPOINT, 'http://acct.r2.cloudflarestorage.com', 'https://'),
    (ob.ENV_RECIPIENT, 'ssh-ed25519 AAAA', 'age public key'),
    (ob.ENV_HOUR, '24', 'whole hour'),
    (ob.ENV_HOUR, 'ten', 'whole hour'),
])
def test_bad_values_are_problems(on, monkeypatch, name, value, problem):
    monkeypatch.setenv(name, value)
    cfg = ob.load_config()
    assert cfg['configured'] is False
    assert any(problem in p for p in cfg['problems'])


def test_defaults_hour_10_and_region_auto(on):
    cfg = ob.load_config()
    assert cfg['configured'] is True and cfg['hour_utc'] == 10 and cfg['region'] == 'auto'


# ── the copy ─────────────────────────────────────────────────────────────────

def test_an_upload_decrypts_to_the_live_database(live, on, s3, sleeps, tmp_path):
    out = ob.run_once('manual', _config)
    assert out['status'] == 'ok', out
    daily = _keys(s3, 'daily/')
    assert len(daily) == 2
    db_key = [k for k in daily if k.endswith('.db.gz.age')][0]
    assert re.fullmatch(r'daily/portfolio_\d{8}-\d{6}\.db\.gz\.age', db_key)
    assert s3.objects[db_key]['bucket'] == 'playbook-backups'
    path, raw = _open_db(s3, db_key, on, tmp_path)
    conn = sqlite3.connect(path)
    assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'      # one self-contained file
    conn.close()
    assert _count(path) == _count(live) == 5
    sha = hashlib.sha256(raw).hexdigest()
    state = ob.read_state()
    assert state['db_sha256'] == sha == s3.objects[db_key]['meta']['db-sha256']
    assert state['object_sha256'] == hashlib.sha256(s3.objects[db_key]['data']).hexdigest()
    assert state['last_object'] == db_key and state['consecutive_failures'] == 0
    assert state['last_attempt_trigger'] == 'manual' and state['last_error'] is None
    assert sleeps == []


def test_the_upload_is_encrypted_and_compressed(live, on, s3, sleeps):
    ob.run_once('manual', _config)
    data = s3.objects[ob.read_state()['last_object']]['data']
    assert data.startswith(b'age-encryption.org/v1')
    assert b'SQLite format 3' not in data and b'portfolio_snapshots' not in data
    with pytest.raises(Exception):
        decrypt(data, [x25519.Identity.generate()])                   # another key cannot open it


def test_the_settings_file_holds_wallets_and_settings_and_no_secrets(live, on, s3, sleeps):
    ob.run_once('manual', wp._offsite_config_payload)
    key = ob.read_state()['last_config_object']
    assert key.endswith('.config.json.age')
    payload = json.loads(decrypt(s3.objects[key]['data'], [on]))
    assert payload['format'] == ob.CONFIG_FORMAT
    assert set(payload) == {'format', 'exported_at', 'note', 'wallets', 'advisor_settings', 'scanner_settings'}
    assert 'env' not in payload and not any('telegram' in k or 'ai_' in k for k in payload)


def test_the_app_payload_has_only_wallets_and_settings():
    assert set(wp._offsite_config_payload()) == {'wallets', 'advisor_settings', 'scanner_settings'}


def test_the_first_upload_of_a_month_is_also_the_monthly_copy(live, on, s3, sleeps, monkeypatch):
    t1 = datetime(2026, 10, 6, 10, 0, 5, tzinfo=UTC)
    t2 = datetime(2026, 10, 7, 10, 0, 5, tzinfo=UTC)
    _at(monkeypatch, t1)
    assert ob.run_once('schedule', _config)['monthly_object'] == 'monthly/portfolio_202610.db.gz.age'
    _at(monkeypatch, t2)
    assert ob.run_once('schedule', _config)['monthly_object'] is None
    assert _keys(s3, 'monthly/') == ['monthly/portfolio_202610.config.json.age', 'monthly/portfolio_202610.db.gz.age']
    assert len(_keys(s3, 'daily/')) == 4
    assert ob.read_state()['last_monthly_object'] == 'monthly/portfolio_202610.db.gz.age'
    _at(monkeypatch, datetime(2026, 11, 1, 10, 0, 5, tzinfo=UTC))
    assert ob.run_once('schedule', _config)['monthly_object'] == 'monthly/portfolio_202611.db.gz.age'


def test_a_monthly_failure_does_not_fail_the_daily_copy_and_is_tried_again(live, on, s3, sleeps, monkeypatch):
    s3.head_error = _ClientError('AccessDenied', 403)
    _at(monkeypatch, _t(6, 10))
    out = ob.run_once('manual', _config)
    assert out['status'] == 'ok' and out['monthly_object'] is None
    assert 'Monthly copy not made' in ob.read_state()['monthly_error']
    assert _keys(s3, 'monthly/') == []
    s3.head_error = None
    _at(monkeypatch, _t(7, 10))
    out = ob.run_once('manual', _config)
    assert out['monthly_object'] and ob.read_state()['monthly_error'] is None


def test_a_database_without_snapshots_is_never_uploaded(volume, on, s3, sleeps):
    portfolio_db.init_db()                    # a fresh database: tables, no snapshots
    out = ob.run_once('schedule', _config)
    assert out['status'] == 'failed' and 'no portfolio snapshots' in out['error']
    assert s3.objects == {} and s3.calls == []
    assert ob.read_state()['consecutive_failures'] == 1


def test_no_database_at_all_is_a_failure_not_a_crash(volume, on, s3, sleeps):
    out = ob.run_once('schedule', _config)
    assert out['status'] == 'failed' and s3.calls == []


def test_upload_retries_then_succeeds(live, on, s3, sleeps):
    s3.fail_puts = 2
    out = ob.run_once('schedule', _config)
    assert out['status'] == 'ok'
    assert sleeps == [30, 120]
    assert ob.read_state()['consecutive_failures'] == 0


def test_three_failed_tries_are_recorded_and_the_next_success_clears_them(live, on, s3, sleeps, ctmp):
    s3.fail_puts = 3
    out = ob.run_once('schedule', _config)
    assert out['status'] == 'failed' and 'ConnectionError' in out['error']
    st = ob.read_state()
    assert st['consecutive_failures'] == 1 and st.get('last_success_at') is None and 'ConnectionError' in st['last_error']
    assert s3.objects == {} and os.listdir(ctmp) == []
    s3.fail_puts = 3
    ob.run_once('schedule', _config)
    assert ob.read_state()['consecutive_failures'] == 2
    assert ob.run_once('schedule', _config)['status'] == 'ok'
    st = ob.read_state()
    assert st['consecutive_failures'] == 0 and st['last_error'] is None and st['last_success_at']


def test_errors_never_carry_the_keys_or_signed_query_strings(live, on, s3, sleeps):
    s3.fail_puts = 3
    s3.put_error = RuntimeError(f'denied for {KEY_ID} using {SECRET} at '
                                f'{ENDPOINT}/playbook-backups/daily/x?X-Amz-Credential={KEY_ID}%2F2026&X-Amz-Signature=abc')
    ob.run_once('schedule', _config)
    err = ob.read_state()['last_error']
    assert SECRET not in err and KEY_ID not in err and 'X-Amz' not in err
    assert 'RuntimeError' in err and '[hidden]' in err
    assert len(err) <= ob.ERROR_MAX


def test_an_s3_error_code_is_named(live, on, s3, sleeps):
    s3.fail_puts = 3
    s3.put_error = _ClientError('InvalidAccessKeyId', 403, 'The key is not valid')
    ob.run_once('schedule', _config)
    assert 'InvalidAccessKeyId' in ob.read_state()['last_error']


def test_temp_files_are_removed_after_success(live, on, s3, sleeps, ctmp):
    ob.run_once('manual', _config)
    assert os.listdir(ctmp) == []


def test_old_temp_leftovers_are_cleared_and_recent_ones_kept(live, on, s3, sleeps, ctmp):
    old = os.path.join(ctmp, ob.TMP_PREFIX + '20261001-100000_1.db')
    new = os.path.join(ctmp, ob.TMP_PREFIX + '20261006-100000_2.db.gz')
    other = os.path.join(ctmp, 'playbook_export_x.db')
    for p in (old, new, other):
        open(p, 'wb').write(b'x')
    os.utime(old, (time.time() - 2 * ob.TMP_GRACE_S,) * 2)
    os.utime(other, (time.time() - 2 * ob.TMP_GRACE_S,) * 2)
    ob.run_once('manual', _config)
    assert sorted(os.listdir(ctmp)) == sorted([os.path.basename(new), os.path.basename(other)])


def test_short_of_temp_space_fails_before_copying(live, on, s3, sleeps, ctmp, monkeypatch):
    real = ob.shutil.disk_usage
    monkeypatch.setattr(ob.shutil, 'disk_usage', lambda p: real(p)._replace(free=10 * 1024 * 1024))
    out = ob.run_once('manual', _config)
    assert out['status'] == 'failed' and 'temp folder' in out['error']
    assert s3.calls == [] and os.listdir(ctmp) == []


def test_a_settings_file_failure_does_not_stop_the_database_copy(live, on, s3, sleeps):
    def broken():
        raise ValueError('settings unreadable')
    out = ob.run_once('manual', broken)
    assert out['status'] == 'ok' and 'settings unreadable' in out['config_error']
    assert [k for k in s3.objects if k.endswith('.config.json.age')] == []
    assert ob.read_state()['last_config_object'] is None


def test_a_second_run_while_one_runs_is_refused(live, on, s3, sleeps):
    assert ob._RUN_LOCK.acquire(blocking=False)
    try:
        assert ob.run_once('schedule', _config) == {'status': 'busy'}
        with pytest.raises(ob.OffsiteError) as e:
            ob.start_manual_run(_config)
        assert e.value.status == 409
    finally:
        ob._RUN_LOCK.release()
    assert s3.calls == []


def test_a_missing_package_is_a_failed_copy_not_a_crash(live, on, s3, sleeps, monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == 'pyrage':
            raise ModuleNotFoundError("No module named 'pyrage'")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, '__import__', fake_import)
    out = ob.run_once('manual', _config)
    assert out['status'] == 'failed' and 'pyrage' in out['error']


def test_the_run_does_not_change_the_live_database(live, on, s3, sleeps):
    before = hashlib.sha256(open(live, 'rb').read()).hexdigest()
    ob.run_once('manual', _config)
    assert hashlib.sha256(open(live, 'rb').read()).hexdigest() == before
    names = sorted(os.listdir(os.path.dirname(live)))
    assert ob.STATE_NAME in names
    assert not any(n.startswith('portfolio_backup_') for n in names)       # no local copy is added


def test_retention_never_touches_the_state_file():
    plan = portfolio_db.plan_backup_retention([ob.STATE_NAME, 'portfolio_backup_20261006.db'])
    assert ob.STATE_NAME not in plan['keep'] + plan['delete']


# ── schedule ─────────────────────────────────────────────────────────────────

def _t(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


@pytest.mark.parametrize('state,now,due', [
    ({}, _t(6, 14), _t(6, 14)),                                                        # never succeeded: now
    ({'last_success_at': '2026-10-06T10:00:30+00:00'}, _t(6, 14), _t(7, 10)),          # done today: tomorrow
    ({'last_success_at': '2026-10-05T10:00:30+00:00'}, _t(6, 9), _t(6, 10)),           # before today's slot
    ({'last_success_at': '2026-10-05T10:00:30+00:00'}, _t(6, 18), _t(6, 10)),          # missed slot: due now
    ({'last_success_at': '2026-10-05T10:00:30+00:00', 'last_attempt_at': '2026-10-06T10:00:00+00:00',
      'consecutive_failures': 1}, _t(6, 10, 30), _t(6, 11)),                           # failed: an hour later
    ({'last_attempt_at': '2026-10-06T10:00:00+00:00', 'consecutive_failures': 2}, _t(6, 10, 30), _t(6, 11)),
    ({'last_success_at': '2026-10-06T09:30:00+00:00'}, _t(6, 9, 45), _t(6, 10)),       # Upload now before the slot
])
def test_next_due(state, now, due):
    assert ob.next_due(state, now, 10) == due


def test_tick_records_when_it_was_switched_on_and_copies_only_when_due(live, on, s3, sleeps, monkeypatch):
    now = _t(6, 14)
    monkeypatch.setattr(ob, '_now', lambda: now)
    assert ob.tick(_config, None, now) == 'ok'
    assert ob.read_state()['enabled_since'] == '2026-10-06T14:00:00+00:00'
    assert ob.tick(_config, None, _t(6, 14, 15)) == 'not_due'
    assert ob.tick(_config, None, _t(7, 9, 45)) == 'not_due'
    monkeypatch.setattr(ob, '_now', lambda: _t(7, 10, 0))
    assert ob.tick(_config, None, _t(7, 10, 0)) == 'ok'
    assert len(_keys(s3, 'daily/')) == 4


def test_tick_does_nothing_when_off(volume, s3):
    assert ob.tick(_config, lambda t: pytest.fail('no alert')) == 'off'
    assert s3.calls == [] and ob.read_state() == {}


def test_tick_when_not_set_up_copies_nothing(volume, s3, monkeypatch):
    monkeypatch.setenv(ob.ENV_SWITCH, 'on')
    assert ob.tick(_config, None, _t(6, 14)) == 'not_configured'
    assert s3.calls == [] and ob.read_state()['enabled_since']


def test_the_loop_waits_after_boot_then_polls(volume, monkeypatch):
    events = []

    class Stop(Exception):
        pass

    def fake_sleep(s):
        events.append(('sleep', s))
        if len([e for e in events if e[0] == 'sleep']) >= 3:
            raise Stop()
    monkeypatch.setattr(ob, '_sleep', fake_sleep)
    monkeypatch.setattr(ob, 'tick', lambda c, a: events.append(('tick',)) or 'off')
    with pytest.raises(Stop):
        ob._loop(None, None)
    assert events == [('sleep', ob.FIRST_DELAY_S), ('tick',), ('sleep', ob.POLL_S), ('tick',), ('sleep', ob.POLL_S)]


def test_a_tick_error_does_not_stop_the_loop(volume, monkeypatch):
    calls = []

    class Stop(Exception):
        pass

    def fake_sleep(s):
        if len(calls) >= 2:
            raise Stop()
    monkeypatch.setattr(ob, '_sleep', fake_sleep)

    def boom(c, a):
        calls.append(1)
        raise RuntimeError('boom')
    monkeypatch.setattr(ob, 'tick', boom)
    with pytest.raises(Stop):
        ob._loop(None, None)
    assert len(calls) == 2


# ── staleness and alerts ─────────────────────────────────────────────────────

def test_stale_after_36_hours_alerts_once_a_day(live, on, s3, sleeps, monkeypatch):
    ob._update_state(enabled_since='2026-10-01T10:00:00+00:00', last_success_at='2026-10-05T10:00:00+00:00',
                     last_attempt_at='2026-10-06T22:00:00+00:00', consecutive_failures=3,
                     last_error='ClientError InvalidAccessKeyId: denied')
    s3.fail_puts = 99
    sent = []
    alert = lambda text: sent.append(text) or (True, None)
    clock = [_t(6, 22, 30)]                                 # 36.5 h after the last success
    monkeypatch.setattr(ob, '_now', lambda: clock[0])
    ob.tick(_config, alert, clock[0])
    assert len(sent) == 1
    assert 'no successful upload since Oct 05 10:00 UTC (36 h)' in sent[0]
    assert 'InvalidAccessKeyId' in sent[0]
    assert ob.status(clock[0])['stale'] is True
    clock[0] = _t(7, 21)                                    # within 24 h: no second alert
    ob.tick(_config, alert, clock[0])
    assert len(sent) == 1
    clock[0] = _t(7, 22, 31)
    ob.tick(_config, alert, clock[0])
    assert len(sent) == 2
    assert ob.read_state()['last_alert_result'] == 'sent'


def test_not_stale_before_36_hours(live, on, s3, sleeps):
    ob._update_state(last_success_at='2026-10-05T10:00:00+00:00')
    assert ob.stale_since(ob.read_state(), _t(6, 21, 59)) is None
    assert ob.status(_t(6, 21, 59))['stale'] is False


def test_never_succeeded_counts_from_when_it_was_switched_on(volume, monkeypatch):
    monkeypatch.setenv(ob.ENV_SWITCH, 'on')                 # on, but not set up
    sent = []
    ob.tick(_config, lambda t: sent.append(t) or (True, None), _t(4, 10))
    assert sent == []
    ob.tick(_config, lambda t: sent.append(t) or (True, None), _t(5, 22, 1))
    assert len(sent) == 1
    assert 'since it was switched on' in sent[0] and 'Not set up' in sent[0] and 'missing' in sent[0]


def test_alert_text_is_safe_for_telegram_markdown(live, on, s3):
    state = {'last_success_at': '2026-10-01T10:00:00+00:00', 'last_error': 'NoSuchBucket: bucket_name *x* `y` [z]'}
    text = ob.alert_text(state, ob.load_config(), _t(1, 10), _t(6, 10))
    assert not re.search(r'[_*`\[\]]', text)
    assert 'NoSuchBucket' in text


def test_an_alert_that_cannot_be_sent_is_recorded_not_raised(live, on, s3, sleeps, monkeypatch):
    ob._update_state(last_success_at='2026-10-01T10:00:00+00:00')
    s3.fail_puts = 99
    monkeypatch.setattr(ob, '_now', lambda: _t(6, 10, 5))

    def broken(text):
        raise ConnectionError('telegram down')
    ob.tick(_config, broken, _t(6, 10, 5))
    assert ob.read_state()['last_alert_result'].startswith('not sent: ConnectionError')


def test_the_app_alert_sends_only_when_telegram_is_on(monkeypatch):
    sent = []
    monkeypatch.setattr(wp, '_send_telegram', lambda text: sent.append(text) or (True, None))
    monkeypatch.setattr(wp, '_telegram_settings', lambda: {'enabled': False})
    assert wp._offsite_alert('x') == (False, 'Telegram is off') and sent == []
    monkeypatch.setattr(wp, '_telegram_settings', lambda: {'enabled': True})
    assert wp._offsite_alert('x') == (True, None) and sent == ['x']


def test_a_failed_telegram_send_never_carries_the_bot_token(live, on, s3, sleeps, monkeypatch):
    token = '123456:AAbbCC_dd-EE'
    url_error = f"HTTPSConnectionPool(host='api.telegram.org'): Max retries exceeded with url: /bot{token}/sendMessage"
    monkeypatch.setattr(wp, '_telegram_settings', lambda: {'enabled': True, 'bot_token': token})
    monkeypatch.setattr(wp, '_send_telegram', lambda text: (False, url_error))
    ok, err = wp._offsite_alert('x')
    assert ok is False and token not in err and '[hidden]' in err
    ob._update_state(last_success_at='2026-10-01T10:00:00+00:00')
    s3.fail_puts = 99
    monkeypatch.setattr(ob, '_now', lambda: _t(6, 10, 5))
    ob.tick(_config, lambda text: (False, url_error), _t(6, 10, 5))     # an alert function that does not scrub
    result = ob.read_state()['last_alert_result']
    assert result.startswith('not sent:') and token not in result and 'bot[hidden]' in result


# ── the thread ───────────────────────────────────────────────────────────────

class _RecThread:
    made = []

    def __init__(self, target=None, args=(), kwargs=None, name=None, daemon=None):
        self.target, self.args, self.kwargs, self.name, self.daemon = target, args, kwargs or {}, name, daemon
        self.alive = False
        _RecThread.made.append(self)

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive


def test_start_thread_starts_one_named_daemon_when_on(on, monkeypatch):
    _RecThread.made = []
    monkeypatch.setattr(ob.threading, 'Thread', _RecThread)
    assert ob.start_thread(_config, None) is True
    assert ob.start_thread(_config, None) is False                  # already running in this worker
    assert len(_RecThread.made) == 1
    t = _RecThread.made[0]
    assert t.name == 'offsite-backup' and t.daemon is True and t.target is ob._loop
    assert ob.status()['thread_alive'] is True


def test_start_thread_when_on_but_not_set_up_still_starts_to_alert(volume, monkeypatch):
    _RecThread.made = []
    monkeypatch.setattr(ob.threading, 'Thread', _RecThread)
    monkeypatch.setenv(ob.ENV_SWITCH, 'on')
    assert ob.start_thread() is True and len(_RecThread.made) == 1


def test_start_thread_logs_no_secrets(on, monkeypatch, capsys):
    monkeypatch.setattr(ob.threading, 'Thread', _RecThread)
    ob.start_thread()
    out = capsys.readouterr().out
    assert '[Offsite] On: a copy daily at 10:00 UTC to bucket playbook-backups' in out
    assert SECRET not in out and KEY_ID not in out


def test_the_app_starts_the_thread_in_both_start_paths():
    src = open(wp.__file__, encoding='utf-8').read()
    tail = src[src.index("if __name__ == '__main__':"):]
    assert tail.count('start_offsite_backup()') == 2
    assert 'start_snapshot_scheduler()' in tail


def test_the_manual_run_takes_the_lock_before_its_thread_starts(live, on, s3, sleeps, monkeypatch):
    _RecThread.made = []
    monkeypatch.setattr(ob.threading, 'Thread', _RecThread)
    ob.start_manual_run(_config)
    try:
        assert ob._RUN_LOCK.locked() and ob.status()['running'] is True
        t = _RecThread.made[0]
        assert t.name == 'offsite-backup-manual' and t.kwargs == {'lock_held': True}
    finally:
        out = t.target(*t.args, **t.kwargs)                         # run it here; it releases the lock
    assert out['status'] == 'ok' and not ob._RUN_LOCK.locked()


# ── routes ───────────────────────────────────────────────────────────────────

def test_status_routes_include_the_offsite_block_without_secrets(live, on, s3, sleeps, client):
    ob.run_once('manual', _config)
    r = client.get('/api/backup/offsite')
    assert r.status_code == 200
    d = r.get_json()
    assert d['configured'] is True and d['last_object'].startswith('daily/')
    assert d['destination'] == {'endpoint_host': 'acct123.r2.cloudflarestorage.com', 'bucket': 'playbook-backups',
                                'region': 'auto'}
    assert d['recipient'].startswith('age1') and '...' in d['recipient']
    full = client.get('/api/backup/status').get_json()
    assert full['offsite']['last_object'] == d['last_object']
    assert ob.STATE_NAME in [f['name'] for f in full['other_portfolio_files']]
    for text in (json.dumps(d), json.dumps(full)):
        assert SECRET not in text and KEY_ID not in text and str(on.to_public()) not in text
        assert str(on) not in text


def test_run_route_needs_a_session_and_the_header(live, on, s3, volume, monkeypatch):
    monkeypatch.setattr(wp, 'get_password_hash', lambda: 'x')
    anon = wp.app.test_client()
    assert anon.post('/api/backup/offsite/run', headers=H).status_code == 401
    assert anon.get('/api/backup/offsite').status_code == 401
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess['authenticated'] = True
    r = c.post('/api/backup/offsite/run')
    assert r.status_code == 400 and 'header' in r.get_json()['error']
    assert s3.calls == []


def test_run_route_starts_an_upload_and_answers_202(live, on, s3, sleeps, client, monkeypatch):
    started = []
    monkeypatch.setattr(ob, 'start_manual_run', lambda config_fn=None: started.append(config_fn))
    r = client.post('/api/backup/offsite/run', headers=H)
    assert r.status_code == 202 and r.get_json()['started'] is True
    assert started == [wp._offsite_config_payload]


def test_run_route_runs_for_real_in_the_background(live, on, s3, sleeps, client):
    r = client.post('/api/backup/offsite/run', headers=H)
    assert r.status_code == 202
    for _ in range(200):
        if not ob._RUN_LOCK.locked():
            break
        time.sleep(0.05)
    st = client.get('/api/backup/offsite').get_json()
    assert st['running'] is False and st['last_attempt_trigger'] == 'manual' and st['last_object']


def test_run_route_refuses_when_off_not_set_up_or_busy(live, client, volume, monkeypatch, on):
    assert ob._RUN_LOCK.acquire(blocking=False)
    try:
        r = client.post('/api/backup/offsite/run', headers=H)
        assert r.status_code == 409 and 'already running' in r.get_json()['error']
    finally:
        ob._RUN_LOCK.release()
    monkeypatch.delenv(ob.ENV_BUCKET)
    r = client.post('/api/backup/offsite/run', headers=H)
    assert r.status_code == 400 and ob.ENV_BUCKET in r.get_json()['error']
    monkeypatch.delenv(ob.ENV_SWITCH)
    r = client.post('/api/backup/offsite/run', headers=H)
    assert r.status_code == 400 and 'off' in r.get_json()['error']


def test_status_route_survives_a_broken_offsite_status(live, client, monkeypatch):
    monkeypatch.setattr(ob, 'status', lambda: (_ for _ in ()).throw(RuntimeError('broken')))
    d = client.get('/api/backup/status').get_json()
    assert 'Off-server status failed' in d['offsite']['error'] and 'daily_backups' in d


def test_the_s3_client_skips_optional_checksums(on):
    pytest.importorskip('boto3')
    c = ob._make_client(ob.load_config())
    cfg = c.meta.config
    assert cfg.request_checksum_calculation == 'when_required'
    assert cfg.response_checksum_validation == 'when_required'
    assert c.meta.endpoint_url == ENDPOINT and cfg.s3['addressing_style'] == 'path'
