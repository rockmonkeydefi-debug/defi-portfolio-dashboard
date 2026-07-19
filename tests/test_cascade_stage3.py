"""Phase 4b — Stage 3 (MSS_FIRED) composer wiring.

Drives the persistence path (web_portfolio._persist_cascade_pair) against an
in-memory SQLite mirror of the post-migration cascade tables. The MSS overlay is
stateful (idempotence, re-arm, demotion-from-3), so these are row-level tests, not
pure-composer tests. The FROZEN _detect_mss is exercised on synthetic trigger
series reused from the Phase-4a construction. No network.
"""
import sqlite3
import json
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

_ST = dict(wp._SCANNER_SETTINGS_DEFAULTS)
_H = 3600 * 4
_WARM = [97.0] * 14
_APP = [98, 99, 100, 98, 96, 93, 90]      # pivot high @101 (idx16), pivot low @88 (idx20)
_GENTLE = [91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 101, 101]   # break idx31


def _series(lo_extra=None):
    lo = {20: 88}
    if lo_extra:
        lo.update(lo_extra)
    closes = _WARM + _APP + _GENTLE
    hi = {16: 101}
    out = []
    prev = closes[0]
    for i, cl in enumerate(closes):
        o = prev
        h = max(o, cl) + 0.2
        l = min(o, cl) - 1.2
        if i in hi:
            h = hi[i]
        if i in lo:
            l = lo[i]
        out.append({'open': o, 'high': round(h, 4), 'low': round(l, 4), 'close': cl,
                    'time': 1_700_000_000 + i * _H, 'volume': 1.0})
        prev = cl
    return out


# A bullish MSS that FIRES (SFP sweep of the 88 low at idx25) vs one that does NOT
# (a clean break with no evidence → _detect_mss returns fired=False).
_FIRE = _series(lo_extra={25: 86})
_NOFIRE = _series()
_TAP = _FIRE[17]['time']       # a tap timestamp before the reversal/break


def _conn():
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE cascade_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, pair TEXT,
            stage INTEGER DEFAULT 0, root_poi_id TEXT, root_zone_top REAL,
            root_zone_bottom REAL, root_poi_type TEXT, nested_poi_id TEXT,
            nested_zone_top REAL, nested_zone_bottom REAL, nested_poi_type TEXT,
            first_tap_at TEXT, last_tap_at TEXT, root_bias TEXT, mss_detail TEXT,
            updated_at TEXT, UNIQUE(symbol, pair));
        CREATE TABLE cascade_transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, pair TEXT,
            from_stage INTEGER, to_stage INTEGER, reason TEXT, root_poi_id TEXT,
            nested_poi_id TEXT, detail TEXT, created_at TEXT);
    """)
    return c


def _ns(stage, bias='bullish', root_id='1w:OB:1', nested_id='4h:FVG:2',
        tap=_TAP, has_nested=True):
    root = None if stage == 0 else {
        'poi_id': root_id, 'poi_type': 'OB', 'zone_top': 102, 'zone_bottom': 100,
        'origin_bar_ts': 1}
    nested = ({'poi_id': nested_id, 'poi_type': 'FVG', 'zone_top': 101,
               'zone_bottom': 99, 'origin_bar_ts': 2}
              if (has_nested and stage >= 2) else None)
    return {'stage': stage, 'root_bias': bias, 'root_poi': root,
            'nested_poi': nested, 'first_tap_at': (tap if stage >= 2 else None),
            'last_tap_at': (tap if stage >= 2 else None)}


def _persist(conn, ns, cbt, pair='W_H4', now='t'):
    wp._persist_cascade_pair(conn, 'FOO', pair, ns, now, cbt, _ST)


def _state(conn, pair='W_H4'):
    return conn.execute("SELECT * FROM cascade_state WHERE symbol='FOO' AND pair=?",
                        (pair,)).fetchone()


def _trans(conn, pair='W_H4'):
    return conn.execute(
        "SELECT * FROM cascade_transitions WHERE symbol='FOO' AND pair=? ORDER BY id",
        (pair,)).fetchall()


# ── the eight Phase-4b behaviors ──────────────────────────────────────────────

def test_stage2_with_tap_fires():
    conn = _conn()
    _persist(conn, _ns(2), {'4h': _FIRE, '1h': _FIRE})
    row = _state(conn)
    assert row['stage'] == 3
    reasons = [t['reason'] for t in _trans(conn)]
    assert reasons == ['rooted', 'nested', 'mss_fired']
    fired = [t for t in _trans(conn) if t['reason'] == 'mss_fired']
    assert len(fired) == 1
    detail = json.loads(fired[0]['detail'])
    assert detail['evidence'] and set(detail['evidence']) <= {'SFP', 'OB', 'FVG'}
    assert detail['broken_swing']['side'] == 'high'
    # persisted state carries the same MSS record
    assert json.loads(row['mss_detail'])['evidence'] == detail['evidence']


def test_no_tap_no_eval():
    conn = _conn()
    ns = _ns(2)
    ns['first_tap_at'] = None            # Stage 2 reached but never tapped
    _persist(conn, ns, {'4h': _FIRE, '1h': _FIRE})
    row = _state(conn)
    assert row['stage'] == 2              # no MSS evaluation → stays Stage 2
    assert 'mss_fired' not in [t['reason'] for t in _trans(conn)]
    assert row['mss_detail'] is None


def test_stage3_idempotent():
    conn = _conn()
    _persist(conn, _ns(2), {'4h': _FIRE, '1h': _FIRE})
    n_before = len(_trans(conn))
    _persist(conn, _ns(2), {'4h': _FIRE, '1h': _FIRE})   # re-observe Stage 3
    assert len(_trans(conn)) == n_before                 # zero new rows
    assert _state(conn)['stage'] == 3


def test_stage3_root_lost():
    conn = _conn()
    _persist(conn, _ns(2), {'4h': _FIRE, '1h': _FIRE})   # → Stage 3
    _persist(conn, _ns(0), {'4h': _FIRE, '1h': _FIRE})   # root invalidates
    row = _state(conn)
    assert row['stage'] == 0
    last = _trans(conn)[-1]
    assert last['reason'] == 'root_lost'
    assert last['from_stage'] == 3 and last['to_stage'] == 0
    assert row['mss_detail'] is None                     # event record cleared


def test_stage3_bias_flip():
    conn = _conn()
    _persist(conn, _ns(2), {'4h': _FIRE, '1h': _FIRE})   # → Stage 3 (bullish)
    _persist(conn, _ns(1, bias='bearish'), {'4h': _FIRE, '1h': _FIRE})
    row = _state(conn)
    assert row['stage'] == 0
    flips = [t for t in _trans(conn) if t['reason'] == 'bias_flip']
    assert len(flips) == 1
    assert flips[0]['from_stage'] == 3 and flips[0]['to_stage'] == 0
    assert row['mss_detail'] is None


def test_stage3_poi_replaced_keeps_stage():
    conn = _conn()
    _persist(conn, _ns(2), {'4h': _FIRE, '1h': _FIRE})   # → Stage 3
    detail_before = _state(conn)['mss_detail']
    # best nested identity churns while root+nested both remain valid.
    _persist(conn, _ns(2, nested_id='4h:FVG:999'), {'4h': _FIRE, '1h': _FIRE})
    row = _state(conn)
    assert row['stage'] == 3                              # ranking churn keeps Stage 3
    last = _trans(conn)[-1]
    assert last['reason'] == 'poi_replaced'
    assert last['from_stage'] == 3 and last['to_stage'] == 3
    assert row['mss_detail'] == detail_before            # fire record preserved


def test_h1_confirm_annotation():
    # W-rooted fire with an H1 series that ALSO fires → h1_confirm true + evidence.
    conn = _conn()
    _persist(conn, _ns(2), {'4h': _FIRE, '1h': _FIRE})
    d = json.loads(_state(conn)['mss_detail'])
    assert d['h1_confirm'] is True and d['h1_evidence']

    # W-rooted fire with an H1 series that does NOT fire → h1_confirm false, and the
    # promotion is unaffected (annotation only).
    conn2 = _conn()
    _persist(conn2, _ns(2), {'4h': _FIRE, '1h': _NOFIRE})
    row = _state(conn2)
    assert row['stage'] == 3
    d2 = json.loads(row['mss_detail'])
    assert d2['h1_confirm'] is False and d2['h1_evidence'] == []


def test_rearm_after_demotion():
    conn = _conn()
    _persist(conn, _ns(2), {'4h': _FIRE, '1h': _FIRE})       # fire #1 → Stage 3
    _persist(conn, _ns(0), {'4h': _FIRE, '1h': _FIRE})       # root_lost → Stage 0
    assert _state(conn)['stage'] == 0
    _persist(conn, _ns(2), {'4h': _FIRE, '1h': _FIRE})       # re-reach Stage 2 + tap
    row = _state(conn)
    assert row['stage'] == 3                                 # armed fresh, fired again
    fired = [t for t in _trans(conn) if t['reason'] == 'mss_fired']
    assert len(fired) == 2                                   # a SECOND mss_fired row


def test_d_h4_triggers_on_h1_series():
    # D_H4 uses the H1 series (not H4) and takes NO H1-confirm annotation.
    conn = _conn()
    _persist(conn, _ns(2, root_id='1d:OB:1'), {'4h': _NOFIRE, '1h': _FIRE},
             pair='D_H4')
    row = _state(conn, 'D_H4')
    assert row['stage'] == 3
    d = json.loads(row['mss_detail'])
    assert d['evidence']
    assert 'h1_confirm' not in d                             # D_H4 is not W-rooted
