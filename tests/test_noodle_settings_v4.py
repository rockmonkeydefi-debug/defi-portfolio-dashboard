"""Landing 43 (Oct 15, 2026): the noodle moved from v3's 25 / 20 / 0.01 to
slow EMA 28, ATR 14, ATR multiplier 0.475 (band_multiplier 0.011875 under
the engine's x40). Proves the new defaults in both places that hold them,
that they agree, the band width they produce, and every outcome of the
boot migration that moves a stored v3 trio (_migrate_noodle_settings_v4).
Self-contained, like the other noodle_* test files; no network, no DB.
"""
import inspect
import json
import threading

import pytest

from src.engines.noodle_bands import compute_noodle_state

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start


V3 = {'noodle_ema_slow': 25, 'noodle_atr_length': 20, 'noodle_band_multiplier': 0.01}
V4 = {'noodle_ema_slow': 28, 'noodle_atr_length': 14, 'noodle_band_multiplier': 0.011875}


def _write(path, data):
    path.write_text(json.dumps(data))


def _read(path):
    return json.loads(path.read_text())


# -- defaults ----------------------------------------------------------

def test_settings_defaults_are_the_v4_trio():
    d = wp._SCANNER_SETTINGS_DEFAULTS
    assert {k: d[k] for k in V4} == V4
    assert d['noodle_ema_fast'] == 12 and d['noodle_ema_medium'] == 21 and d['noodle_use_atr'] is True


def test_migration_constants_match_the_defaults():
    assert wp.NOODLE_SETTINGS_V3 == V3
    assert wp.NOODLE_SETTINGS_V4 == {k: wp._SCANNER_SETTINGS_DEFAULTS[k] for k in V4}


def test_engine_defaults_equal_the_settings_defaults():
    params = inspect.signature(compute_noodle_state).parameters
    d = wp._SCANNER_SETTINGS_DEFAULTS
    assert params['fast'].default == d['noodle_ema_fast']
    assert params['medium'].default == d['noodle_ema_medium']
    assert params['slow'].default == d['noodle_ema_slow']
    assert params['atr_length'].default == d['noodle_atr_length']
    assert params['band_multiplier'].default == d['noodle_band_multiplier']
    assert params['use_atr'].default == d['noodle_use_atr']


def test_snapshot_settings_with_no_file_use_the_v4_trio(tmp_path, monkeypatch):
    monkeypatch.setattr(wp, '_SCANNER_SETTINGS_PATH', str(tmp_path / 'scanner_settings.json'))
    assert wp._trade_snapshot_settings() == {'fast': 12, 'medium': 21, 'slow': 28, 'atr_length': 14,
                                             'band_multiplier': 0.011875, 'use_atr': True}


def test_default_band_is_midpoint_plus_minus_0475_atr():
    # Flat closes at 100 with a constant 2-point range: every true range is
    # 2 (max(2, |101-100|, |99-100|)), so ATR(14) is 2 and EMA(28) is 100.
    # Band = 100 +/- 2 x 0.011875 x 40 = 100 +/- 0.95.
    candles = [{'open': 100, 'high': 101, 'low': 99, 'close': 100, 'volume': 1.0, 'time': 1_700_000_000 + i * 86400}
               for i in range(80)]
    r = compute_noodle_state(candles)
    assert r['basis_ema'] == pytest.approx(100)
    assert r['upper_band'] == pytest.approx(100.95)
    assert r['lower_band'] == pytest.approx(99.05)


# -- boot migration ----------------------------------------------------

def test_v3_file_is_migrated_and_other_keys_kept(tmp_path):
    p = tmp_path / 'scanner_settings.json'
    _write(p, {**V3, 'noodle_ema_fast': 12, 'noodle_max_tickers': 180, 'board_retention_days': 9})
    assert wp._migrate_noodle_settings_v4(str(p)) == "migrated"
    assert _read(p) == {**V4, 'noodle_ema_fast': 12, 'noodle_max_tickers': 180, 'board_retention_days': 9}
    assert not (tmp_path / 'scanner_settings.json.tmp').exists()


def test_second_run_keeps_the_migrated_file(tmp_path):
    p = tmp_path / 'scanner_settings.json'
    _write(p, dict(V3))
    assert wp._migrate_noodle_settings_v4(str(p)) == "migrated"
    before = p.read_bytes()
    assert wp._migrate_noodle_settings_v4(str(p)) == "kept"
    assert p.read_bytes() == before


def test_manual_choice_is_kept_untouched(tmp_path):
    p = tmp_path / 'scanner_settings.json'
    _write(p, {**V3, 'noodle_ema_slow': 30})
    before = p.read_bytes()
    assert wp._migrate_noodle_settings_v4(str(p)) == "kept"
    assert p.read_bytes() == before


def test_some_trio_keys_at_v3_move_all_three(tmp_path):
    p = tmp_path / 'scanner_settings.json'
    _write(p, {'noodle_ema_slow': 25, 'scan_max_tickers': 50})
    assert wp._migrate_noodle_settings_v4(str(p)) == "migrated"
    assert _read(p) == {**V4, 'scan_max_tickers': 50}


def test_file_without_noodle_keys_is_left_to_the_defaults(tmp_path):
    p = tmp_path / 'scanner_settings.json'
    _write(p, {'scan_max_tickers': 50})
    before = p.read_bytes()
    assert wp._migrate_noodle_settings_v4(str(p)) == "defaults"
    assert p.read_bytes() == before


def test_absent_file_is_not_created(tmp_path):
    p = tmp_path / 'scanner_settings.json'
    assert wp._migrate_noodle_settings_v4(str(p)) == "absent"
    assert not p.exists()


@pytest.mark.parametrize("raw", ["{not json", "[1, 2, 3]", ""])
def test_unreadable_file_is_left_untouched(tmp_path, raw):
    p = tmp_path / 'scanner_settings.json'
    p.write_text(raw)
    assert wp._migrate_noodle_settings_v4(str(p)) == "unreadable"
    assert p.read_text() == raw


def test_settings_read_after_migration_serve_the_v4_trio(tmp_path, monkeypatch):
    p = tmp_path / 'scanner_settings.json'
    _write(p, {**wp._SCANNER_SETTINGS_DEFAULTS, **V3})
    monkeypatch.setattr(wp, '_SCANNER_SETTINGS_PATH', str(p))
    assert {k: wp._scanner_settings()[k] for k in V3} == V3
    assert wp._migrate_noodle_settings_v4(str(p)) == "migrated"
    assert {k: wp._scanner_settings()[k] for k in V4} == V4
