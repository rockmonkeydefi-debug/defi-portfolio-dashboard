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
        CREATE TABLE scanner_watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT UNIQUE);
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
    wp._persist_cascade_pair(conn, 'FOOUSDT', pair, ns, now, cbt, _ST)


def _state(conn, pair='W_H4'):
    return conn.execute("SELECT * FROM cascade_state WHERE symbol='FOOUSDT' AND pair=?",
                        (pair,)).fetchone()


def _trans(conn, pair='W_H4'):
    return conn.execute(
        "SELECT * FROM cascade_transitions WHERE symbol='FOOUSDT' AND pair=? ORDER BY id",
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


def test_cascade_summary_board_ticker_major():
    # Phase 5: the summary carries a ticker-major `board` (stages per pair + the
    # Stage-3 MSS break_bar_ts for age), read from cascade_state only.
    conn = _conn()
    conn.execute("INSERT INTO scanner_watchlist (symbol) VALUES ('FOOUSDT')")  # on the active universe
    _persist(conn, _ns(2), {'4h': _FIRE, '1h': _FIRE}, pair='W_H4')  # FOO W_H4 → Stage 3
    _persist(conn, _ns(1), {}, pair='W_D')                           # FOO W_D → Stage 1
    summ = wp._cascade_summary(conn)
    board = {b['symbol']: b for b in summ['board']}
    assert 'FOOUSDT' in board
    assert board['FOOUSDT']['stages']['W_H4'] == 3
    assert board['FOOUSDT']['stages']['W_D'] == 1
    # Stage-3 pair carries the break timestamp for the age column.
    assert board['FOOUSDT']['breakTs'].get('W_H4') is not None
    assert 'W_D' not in board['FOOUSDT']['breakTs']                      # no fire → no ts


# ── Cascade root-invalidation rules (regime gate + OTE acceptance) ────────────
# Rules invalidate a root at BOTH candidacy (front door) and stored-state
# re-evaluation. Existing tests above pass only 4h/1h candles (no 1w/1d) so both
# rules no-op there; these drive the rules explicitly (regime via monkeypatch,
# OTE via crafted 1w closes). Reasons: 'regime_conflict' / 'ote_acceptance'.

def test_root_regime_conflict_pure():
    # Rule 1: a NON-neutral regime OPPOSITE the root bias conflicts; W-rooted read
    # 1W, D-rooted read 1D; neutral / aligned / missing → no conflict.
    assert wp._root_regime_conflict('W_H4', 'bullish', {'1W': 'bearish'}) is True
    assert wp._root_regime_conflict('W_D',  'bearish', {'1W': 'bullish'}) is True
    assert wp._root_regime_conflict('D_H4', 'bullish', {'1D': 'bearish'}) is True
    assert wp._root_regime_conflict('D_H4', 'bullish',
                                    {'1W': 'bearish', '1D': 'bullish'}) is False  # reads 1D
    assert wp._root_regime_conflict('W_H4', 'bullish', {'1W': 'bullish'}) is False
    assert wp._root_regime_conflict('W_H4', 'bullish', {'1W': 'neutral'}) is False
    assert wp._root_regime_conflict('W_H4', 'bullish', {}) is False


def test_root_ote_bounds_and_acceptance_pure():
    top, bottom = wp._root_ote_bounds({'high': 200, 'low': 100, 'bias': 'bullish'})
    assert bottom == round(200 - 0.786 * 100, 6)   # 121.4 (far side, bullish)
    assert top == round(200 - 0.618 * 100, 6)      # 138.2
    def cx(*cl):
        return [{'close': c} for c in cl]
    # (c) two closed bars below the far side → invalid (last elem = forming bar).
    assert wp._root_ote_acceptance(cx(150, 110, 110, 999), 'bullish', top, bottom, 2) is True
    # (d) 1 below + 1 inside on the last-2 closed → valid (not all beyond).
    assert wp._root_ote_acceptance(cx(110, 130, 999), 'bullish', top, bottom, 2) is False
    # (e) forming bar excluded: only the forming bar is below; closed bars inside → valid.
    assert wp._root_ote_acceptance(cx(130, 130, 110), 'bullish', top, bottom, 2) is False
    # fewer than n closed bars → valid (cannot confirm acceptance).
    assert wp._root_ote_acceptance(cx(110, 999), 'bullish', top, bottom, 2) is False
    # bearish mirror: closes ABOVE ote_top.
    tb, bb = wp._root_ote_bounds({'high': 200, 'low': 100, 'bias': 'bearish'})
    assert wp._root_ote_acceptance(cx(150, 190, 190, 1), 'bearish', tb, bb, 2) is True


def test_regime_conflict_blocks_candidacy():
    # (a) front door: bullish root + bearish weekly regime → no seeding (stays 0).
    conn = _conn()
    _orig = wp._cascade_scan_regimes
    wp._cascade_scan_regimes = lambda *a, **k: {'1W': 'bearish', '1D': 'neutral'}
    try:
        _persist(conn, _ns(2), {'4h': _FIRE, '1h': _FIRE})   # would fire; root is dead
    finally:
        wp._cascade_scan_regimes = _orig
    row = _state(conn)
    assert row['stage'] == 0
    assert row['mss_detail'] is None
    assert _trans(conn) == []                                # prior 0 → no transition


def test_neutral_regime_does_not_block():
    # (b) neutral weekly regime → normal Stage-3 fire, no block.
    conn = _conn()
    _orig = wp._cascade_scan_regimes
    wp._cascade_scan_regimes = lambda *a, **k: {'1W': 'neutral', '1D': 'neutral'}
    try:
        _persist(conn, _ns(2), {'4h': _FIRE, '1h': _FIRE})
    finally:
        wp._cascade_scan_regimes = _orig
    assert _state(conn)['stage'] == 3


def test_stored_stage3_demotes_regime_conflict():
    # (f) stored Stage 3 → regime turns bearish → demote to 0, reason
    # 'regime_conflict', mss_detail cleared, exactly one new transition row.
    conn = _conn()
    _persist(conn, _ns(2), {'4h': _FIRE, '1h': _FIRE})       # → Stage 3 (neutral)
    assert _state(conn)['stage'] == 3
    n0 = len(_trans(conn))
    _orig = wp._cascade_scan_regimes
    wp._cascade_scan_regimes = lambda *a, **k: {'1W': 'bearish', '1D': 'neutral'}
    try:
        _persist(conn, _ns(2), {'4h': _FIRE, '1h': _FIRE})
    finally:
        wp._cascade_scan_regimes = _orig
    row = _state(conn)
    assert row['stage'] == 0
    assert row['mss_detail'] is None
    trs = _trans(conn)
    assert len(trs) - n0 == 1
    assert trs[-1]['reason'] == 'regime_conflict'
    assert trs[-1]['from_stage'] == 3 and trs[-1]['to_stage'] == 0


def test_bias_flip_precedence_over_regime():
    # (g) bias_flip stays highest: both would fire → bias_flip wins, not regime.
    conn = _conn()
    _persist(conn, _ns(2), {'4h': _FIRE, '1h': _FIRE})       # → Stage 3 bullish
    _orig = wp._cascade_scan_regimes
    wp._cascade_scan_regimes = lambda *a, **k: {'1W': 'bearish', '1D': 'neutral'}
    try:
        _persist(conn, _ns(1, bias='bearish'), {'4h': _FIRE, '1h': _FIRE})  # bias flips
    finally:
        wp._cascade_scan_regimes = _orig
    assert _state(conn)['stage'] == 0
    assert _trans(conn)[-1]['reason'] == 'bias_flip'


def test_stored_demotes_ote_acceptance():
    # OTE acceptance (neutral regime): last 2 CLOSED 1W closes beyond the root OTE
    # far side → demote to 0 with reason 'ote_acceptance'.
    conn = _conn()
    _persist(conn, _ns(2), {'4h': _FIRE, '1h': _FIRE})       # → Stage 3
    ns2 = _ns(2)
    ns2['root_dr'] = {'high': 200, 'low': 100, 'bias': 'bullish'}   # OTE bottom 121.4
    wk = [{'close': 150}, {'close': 110}, {'close': 110}, {'close': 999}]  # last = forming
    _orig = wp._cascade_scan_regimes
    wp._cascade_scan_regimes = lambda *a, **k: {'1W': 'neutral', '1D': 'neutral'}
    try:
        _persist(conn, ns2, {'4h': _FIRE, '1h': _FIRE, '1w': wk})
    finally:
        wp._cascade_scan_regimes = _orig
    row = _state(conn)
    assert row['stage'] == 0
    assert row['mss_detail'] is None
    assert _trans(conn)[-1]['reason'] == 'ote_acceptance'
