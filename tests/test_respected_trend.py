"""Respected trend columns on noodle_state (Landings 50, 50b, 51).

Landing 50 (Oct 17) added the columns; Landing 51 (Oct 18) reworked the rule
around the band's slope (Glenn's rulings, SPEC_respected_trend_test.md
addendum):

  * the band must be sloping for a history to begin (slope = slow EMA change
    over 10 bars / ATR, enter 0.6, exit 0.3); a flat band is not a trend
  * a tag is a wick into the band that holds (low <= upper and close >= lower
    for a bullish band) followed by a new history high; mirrored when bearish
  * a loss is two consecutive closes beyond the far edge (one rogue close is
    not acceptance); two or more losses mean "not respected" (frontend rule)
  * the history is back-dated to where the slope first exceeded the exit
    threshold; a flat band resets tags, losses and the clock
  * a respected history that ends in a flat band leaves a Ranging marker

src/engines/respected_trend gives dir / tags / last_ts / unbounded / since /
losses / ranging_since; the scan stores them in respect_* columns on the
1h / 4h / 12h / 1d rows (1w stays NULL); respect_breaks is no longer written.
Engine cases pin the slow EMA, ATR and bands (as test_doc_trend.py pins its
inputs) so each one is written by hand. Fixture conventions copy
test_doc_trend.py (no cross-file fixture imports).
"""
import sqlite3
import threading
import uuid

import src.engines.respected_trend as rt
import src.storage.portfolio_db as portfolio_db
from src.engines.respected_trend import compute_respected_trend

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import pytest

RESPECT_COLUMNS = ('respect_dir', 'respect_tags', 'respect_last_ts', 'respect_unbounded', 'respect_breaks',
                   'respect_since', 'respect_losses', 'respect_ranging_since')
LANDING_51_COLUMNS = ('respect_since', 'respect_losses', 'respect_ranging_since')
T0 = 1_699_999_200          # a whole hour (and a whole 4h bucket) in unix seconds
STEP = 3600
UPPER, LOWER = 110.0, 90.0
EMPTY = {'dir': None, 'tags': None, 'last_ts': None, 'unbounded': None,
         'since': None, 'losses': None, 'ranging_since': None}


def _bars(closes, step, t0=T0):
    return [{'open': c, 'high': c + 1.0, 'low': c - 1.0, 'close': c, 'volume': 10.0,
             'time': t0 + i * step} for i, c in enumerate(closes)]


def _down_then_up(n_down, n_up, start=100.0, step=0.1):
    down = [start - step * i for i in range(n_down)]
    low = down[-1]
    return down + [low + step * (i + 1) for i in range(n_up)]


def _basis(n, *runs):
    """Stand-in for the slow EMA: flat at 100 except +0.5 / -0.5 per bar inside
    each (first, last, sign) run, inclusive. With ATR pinned to 1 the slope over
    10 bars is the change of this series, and the first slope is at index 10."""
    incs = [0.0] * n
    for first, last, sign in runs:
        for i in range(first, min(last, n - 1) + 1):
            incs[i] += 0.5 * sign
    out, v = [], 100.0
    for x in incs:
        v += x
        out.append(v)
    return out


RISE = (14, 999, 1)        # the band slopes up from bar 14 to the end: slope 0.5 at 14, 1.0 at 15 (enters)
FALL = (14, 999, -1)

# Closes (high = close + 1, low = close - 1), bands pinned at 90 / 110. Bars 0-13 sit
# in the band with a flat basis; the history is back-dated to bar 14 (entry is bar 15).
# 14 first bar (seek) | 15,16 clear | 17 pullback (low 108) | 18 new high: tag 1
# | 19 pullback | 20 new high: tag 2
PRE = [100.0] * 14
BULL_TAIL = [100.0, 112.0, 116.0, 109.0, 118.0, 108.0, 120.0]


@pytest.fixture
def run(monkeypatch):
    """run(closes, *basis_runs, tweak={bar: {field: value}}, **kwargs) -> (result, bars)."""
    def _run(closes, *runs, tweak=None, upper=UPPER, lower=LOWER, basis=None, **kwargs):
        bars = _bars(closes, STEP)
        for i, fields in (tweak or {}).items():
            bars[i].update(fields)
        basis = basis if basis is not None else _basis(len(bars), *runs)
        monkeypatch.setattr(rt, 'ema', lambda values, period: list(basis))
        monkeypatch.setattr(rt, 'atr', lambda candles, period: [1.0] * len(candles))
        monkeypatch.setattr(rt, '_compute_bands',
                            lambda e, a, m, u: ([upper] * len(e), [lower] * len(e)))
        return compute_respected_trend(bars, **kwargs), bars
    return _run


# -- the engine: entry, tags -----------------------------------------------

def test_a_sloping_band_opens_a_bullish_history_back_dated_to_where_the_slope_began(run):
    out, bars = run(PRE + BULL_TAIL, RISE)
    assert out == {'dir': 'BULLISH', 'tags': 2, 'last_ts': bars[20]['time'], 'unbounded': False,
                   'since': bars[14]['time'], 'losses': 0, 'ranging_since': None}


def test_a_flat_band_has_no_history_however_price_behaves(run):
    out, _ = run(PRE + BULL_TAIL)
    assert out == EMPTY


def test_the_slope_must_reach_the_enter_threshold_and_the_equal_value_enters(run):
    # Slope 0.5 at bar 14, 1.0 at bar 15: a history cannot be open at bar 14 ...
    out, _ = run((PRE + BULL_TAIL)[:15], RISE)
    assert out == EMPTY
    # ... and 1.0 against an enter threshold of 1.0 opens it (>=), dated from bar 14.
    out, bars = run((PRE + BULL_TAIL)[:16], RISE, slope_enter=1.0, slope_exit=0.4)
    assert out['dir'] == 'BULLISH' and out['since'] == bars[14]['time']


def test_the_tag_is_dated_by_the_bar_that_makes_the_new_high(run):
    out, bars = run((PRE + BULL_TAIL)[:19], RISE)
    assert out['tags'] == 1 and out['last_ts'] == bars[18]['time']


def test_a_wick_into_the_band_that_closes_clear_of_it_is_a_pullback(run):
    # Bar 17 closes at 118, above the 110 upper band, but its low (108) reached into the band.
    closes = PRE + [100.0, 112.0, 116.0, 118.0, 125.0]
    out, bars = run(closes, RISE, tweak={17: {'low': 108.0}})
    assert out['tags'] == 1 and out['last_ts'] == bars[18]['time']
    out, _ = run(closes, RISE)                         # same closes, the low stays above the band
    assert out['tags'] == 0


def test_a_bar_that_closes_beyond_the_far_edge_is_not_a_pullback_that_holds(run):
    closes = PRE + [100.0, 112.0, 116.0, 85.0, 125.0]
    out, _ = run(closes, RISE)
    assert out['tags'] == 0


def test_a_pullback_without_a_new_high_is_not_a_tag(run):
    out, _ = run(PRE + [100.0, 112.0, 116.0, 109.0, 111.0, 113.0], RISE)
    assert out['dir'] == 'BULLISH' and out['tags'] == 0 and out['last_ts'] is None


def test_equalling_the_history_high_is_not_a_new_high(run):
    out, _ = run(PRE + [100.0, 112.0, 116.0, 109.0, 116.0], RISE)      # bar 18 high 117 = bar 16 high
    assert out['tags'] == 0


def test_the_bar_that_spikes_to_a_new_high_is_not_also_the_pullback(run):
    # Bar 17 dips into the band but spikes to 130 first: a rejection, not a tag.
    out, _ = run(PRE + [100.0, 112.0, 116.0, 109.0], RISE, tweak={17: {'high': 130.0}})
    assert out['tags'] == 0


def test_a_pullback_bar_followed_by_a_new_high_bar_is_a_tag(run):
    out, bars = run(PRE + [100.0, 112.0, 116.0, 109.0, 109.0], RISE, tweak={18: {'high': 130.0}})
    assert out['tags'] == 1 and out['last_ts'] == bars[18]['time']


def test_after_a_tag_the_next_one_needs_price_clear_of_the_band_again(run):
    # Bar 18 tags and closes inside the band; bar 19 makes another high from inside: no second tag.
    closes = PRE + [100.0, 112.0, 116.0, 109.0, 109.0, 109.0]
    tweak = {18: {'high': 130.0}, 19: {'high': 135.0}}
    out, _ = run(closes, RISE, tweak=tweak)
    assert out['tags'] == 1
    # Clear again (bar 19 closes above the band), pull back (bar 20), new high (bar 21): second tag.
    closes = PRE + [100.0, 112.0, 116.0, 109.0, 109.0, 120.0, 109.0, 109.0]
    tweak = {18: {'high': 130.0}, 19: {'high': 131.0}, 21: {'high': 140.0}}
    out, bars = run(closes, RISE, tweak=tweak)
    assert out['tags'] == 2 and out['last_ts'] == bars[21]['time']


def test_a_history_that_opens_below_the_band_needs_to_get_clear_before_it_can_tag(run):
    # Bar 14 (first of the history) is inside the band, so a high at bar 15 is not a tag.
    out, _ = run(PRE + [100.0, 112.0], RISE)
    assert out['tags'] == 0
    # A history whose first bar is already clear of the band can tag on its first pullback.
    out, bars = run([100.0] * 13 + [112.0, 116.0, 109.0, 120.0], RISE)
    assert out['tags'] == 1 and out['last_ts'] == bars[16]['time']


def test_bearish_equalling_the_history_low_is_not_a_new_low(run):
    closes = [200.0 - c for c in PRE + [100.0, 112.0, 116.0, 109.0, 116.0]]      # bar 18 low 83 = bar 16 low
    out, _ = run(closes, FALL)
    assert out['dir'] == 'BEARISH' and out['tags'] == 0


def test_a_bearish_history_that_opens_clear_of_the_band_can_tag_on_its_first_pullback(run):
    closes = [200.0 - c for c in [100.0] * 13 + [112.0, 116.0, 109.0, 120.0]]
    out, bars = run(closes, FALL)
    assert out['tags'] == 1 and out['last_ts'] == bars[16]['time']


def test_bearish_mirror(run):
    closes = [200.0 - c for c in PRE + BULL_TAIL]
    out, bars = run(closes, FALL)
    assert out == {'dir': 'BEARISH', 'tags': 2, 'last_ts': bars[20]['time'], 'unbounded': False,
                   'since': bars[14]['time'], 'losses': 0, 'ranging_since': None}


def test_a_bearish_wick_into_the_band_that_closes_clear_of_it_is_a_pullback(run):
    # Mirror of the bullish case: bar 17 closes at 82, below the 90 lower band, but its high (92) reached the band.
    closes = [200.0 - c for c in PRE + [100.0, 112.0, 116.0, 118.0, 125.0]]
    out, bars = run(closes, FALL, tweak={17: {'high': 92.0}})
    assert out['dir'] == 'BEARISH' and out['tags'] == 1 and out['last_ts'] == bars[18]['time']
    out, _ = run(closes, FALL)                         # same closes, the high stays below the band
    assert out['tags'] == 0


# -- the engine: losses ------------------------------------------------------

def test_one_close_beyond_the_far_edge_is_not_a_loss(run):
    out, _ = run(PRE + BULL_TAIL + [85.0, 115.0], RISE)
    assert out['dir'] == 'BULLISH' and out['tags'] == 2 and out['losses'] == 0


def test_a_wick_through_the_far_edge_that_closes_back_is_not_a_loss(run):
    out, _ = run(PRE + BULL_TAIL + [105.0], RISE, tweak={21: {'low': 80.0}})
    assert out['losses'] == 0


def test_a_close_on_the_far_edge_is_not_beyond_it(run):
    out, _ = run(PRE + BULL_TAIL + [90.0, 90.0, 100.0], RISE)
    assert out['losses'] == 0


def test_two_consecutive_closes_beyond_the_far_edge_are_a_loss_and_tags_are_kept(run):
    out, _ = run(PRE + BULL_TAIL + [85.0, 84.0], RISE)
    assert out['dir'] == 'BULLISH' and out['tags'] == 2 and out['losses'] == 1


def test_a_longer_streak_counts_once_and_a_second_streak_counts_again(run):
    out, _ = run(PRE + BULL_TAIL + [85.0, 84.0, 83.0, 82.0], RISE)
    assert out['losses'] == 1
    out, _ = run(PRE + BULL_TAIL + [85.0, 84.0, 100.0, 85.0, 84.0], RISE)
    assert out['losses'] == 2


def test_two_closes_beyond_that_are_not_consecutive_are_not_a_loss(run):
    out, _ = run(PRE + BULL_TAIL + [85.0, 100.0, 85.0, 100.0], RISE)
    assert out['losses'] == 0


def test_a_bearish_history_loses_on_closes_above_the_upper_band(run):
    closes = [200.0 - c for c in PRE + BULL_TAIL] + [115.0, 116.0]
    out, _ = run(closes, FALL)
    assert out['dir'] == 'BEARISH' and out['tags'] == 2 and out['losses'] == 1
    out, _ = run(closes[:-1] + [100.0], FALL)
    assert out['losses'] == 0


def test_confirm_one_makes_a_single_close_a_loss(run):
    out, _ = run(PRE + BULL_TAIL + [85.0], RISE, confirm=1)
    assert out['losses'] == 1
    assert rt.RESPECT_CONFIRM_CLOSES == 2


# -- the engine: the band going flat, reversing, ranging ---------------------

def test_a_slope_between_the_exit_and_enter_thresholds_keeps_the_history_open(run):
    # The rise stops at bar 20; by bar 29 the slope has decayed to 0.5 (between 0.3 and 0.6).
    out, _ = run(PRE + BULL_TAIL + [120.0] * 9, (14, 20, 1))
    assert out['dir'] == 'BULLISH' and out['tags'] == 2


def test_a_flat_band_ends_the_history(run):
    out, bars = run(PRE + BULL_TAIL + [120.0] * 10, (14, 20, 1))      # bar 30: slope 0
    assert out['dir'] is None and out['tags'] is None and out['since'] is None
    assert out['losses'] is None and out['last_ts'] is None and out['unbounded'] is None
    assert out['ranging_since'] == bars[30]['time']                    # respected at its end


def test_the_bearish_enter_and_exit_thresholds_are_inclusive_too(run):
    mirror = [200.0 - c for c in PRE + BULL_TAIL]
    out, bars = run(mirror[:16], FALL, slope_enter=1.0, slope_exit=0.4)       # slope -1.0 at bar 15 enters, dated from 14
    assert out['dir'] == 'BEARISH' and out['since'] == bars[14]['time']
    out, _ = run(mirror + [80.0] * 9, (14, 20, -1), slope_enter=1.0, slope_exit=0.5)      # bar 29: slope -0.5 exits
    assert out['dir'] is None
    out, _ = run(mirror + [80.0] * 9, (14, 20, -1), slope_enter=1.0, slope_exit=0.4)      # -0.5 is beyond -0.4: still open
    assert out['dir'] == 'BEARISH'


def test_the_exit_threshold_is_inclusive(run):
    out, _ = run(PRE + BULL_TAIL + [120.0] * 9, (14, 20, 1), slope_enter=1.0, slope_exit=0.5)   # bar 29: slope 0.5
    assert out['dir'] is None
    out, _ = run(PRE + BULL_TAIL + [120.0] * 9, (14, 20, 1), slope_enter=1.0, slope_exit=0.4)   # 0.5 > 0.4: still open
    assert out['dir'] == 'BULLISH'


def test_when_the_slope_resumes_tags_losses_and_the_clock_start_over(run):
    first = PRE + BULL_TAIL + [85.0, 84.0]                              # 2 tags, 1 loss, rise ends at bar 22
    closes = first + [100.0] * (60 - len(first) + 1)
    out, _ = run(closes[:40], (14, 22, 1), (45, 60, 1))                # still flat at bar 39
    assert out['dir'] is None and out['ranging_since'] is not None
    out, bars = run(closes, (14, 22, 1), (45, 60, 1))
    assert out == {'dir': 'BULLISH', 'tags': 0, 'last_ts': None, 'unbounded': False,
                   'since': bars[45]['time'], 'losses': 0, 'ranging_since': None}


def test_a_slope_that_crosses_straight_to_the_other_side_starts_a_new_history(run):
    # The band rises to bar 18 (slope 2.5), then one -4.0 step at bar 21 takes the slope from +2.5 straight
    # to -1.5, below -0.6, without passing through a flat stretch: a bearish history opens at bar 21.
    closes = PRE + BULL_TAIL + [100.0]
    incs = [0.0] * 14 + [0.5] * 5 + [0.0, 0.0] + [-4.0]
    basis, v = [], 100.0
    for x in incs:
        v += x
        basis.append(v)
    out, bars = run(closes, basis=basis)
    assert len(bars) == 22
    assert out == {'dir': 'BEARISH', 'tags': 0, 'last_ts': None, 'unbounded': False,
                   'since': bars[21]['time'], 'losses': 0, 'ranging_since': None}


def test_a_bearish_slope_that_crosses_straight_to_a_bullish_one_starts_a_new_history(run):
    closes = [200.0 - c for c in PRE + BULL_TAIL + [100.0]]
    incs = [0.0] * 14 + [-0.5] * 5 + [0.0, 0.0] + [4.0]
    basis, v = [], 100.0
    for x in incs:
        v += x
        basis.append(v)
    out, bars = run(closes, basis=basis)
    assert out == {'dir': 'BULLISH', 'tags': 0, 'last_ts': None, 'unbounded': False,
                   'since': bars[21]['time'], 'losses': 0, 'ranging_since': None}


def test_a_bearish_history_that_ends_flat_leaves_the_ranging_marker_when_it_was_respected(run):
    closes = [200.0 - c for c in PRE + BULL_TAIL + [120.0] * 10]
    out, bars = run(closes, (14, 20, -1))                               # bar 30: slope 0
    assert out['dir'] is None and out['ranging_since'] == bars[30]['time']
    # one tag only: no marker
    closes = [200.0 - c for c in PRE + BULL_TAIL[:5] + [118.0] * 13]
    out, _ = run(closes, (14, 18, -1))
    assert out['dir'] is None and out['ranging_since'] is None
    # two losses: no marker
    closes = [200.0 - c for c in PRE + BULL_TAIL + [85.0, 84.0, 100.0, 85.0, 84.0] + [100.0] * 10]
    out, _ = run(closes, (14, 25, -1))
    assert out['dir'] is None and out['ranging_since'] is None


def test_ranging_needs_a_history_that_was_respected_at_its_end(run):
    base = PRE + BULL_TAIL
    # one tag only
    out, _ = run(PRE + BULL_TAIL[:5] + [118.0] * 13, (14, 18, 1))
    assert out['dir'] is None and out['ranging_since'] is None
    # two losses
    closes = base + [85.0, 84.0, 100.0, 85.0, 84.0] + [100.0] * 10
    out, _ = run(closes, (14, 25, 1))        # flat from bar 35
    assert out['dir'] is None and out['ranging_since'] is None
    # one loss is tolerated
    closes = base + [85.0, 84.0] + [100.0] * 10
    out, bars = run(closes, (14, 22, 1))
    assert out['dir'] is None and out['ranging_since'] == bars[32]['time']


def test_ranging_needs_the_latest_tag_within_the_window_at_the_end_of_the_history(run):
    # Last rise bar L: the history's last bar is L + 9 and the flat bar is L + 10; the tag is at bar 20.
    ok, bars = run(PRE + BULL_TAIL + [120.0] * 30, (14, 40, 1))        # bar 49 is 29 bars after the tag: counts
    assert ok['ranging_since'] == bars[50]['time']
    late, _ = run(PRE + BULL_TAIL + [120.0] * 31, (14, 41, 1))         # bar 50 is 30 bars after: stale
    assert late['dir'] is None and late['ranging_since'] is None


def test_ranging_belongs_to_the_most_recent_history_only(run):
    # A respected history, then flat, then a history that is not respected, then flat again.
    first = PRE + BULL_TAIL + [120.0] * 20                              # ends at bar 30 (flat from there)
    second = [100.0] * 15                                               # rise bars 40..44, then flat
    out, _ = run(first + second, (14, 20, 1), (40, 44, 1))
    assert out['dir'] is None and out['ranging_since'] is None


def test_the_flat_marker_is_dropped_while_a_new_history_is_open(run):
    out, _ = run(PRE + BULL_TAIL + [120.0] * 10 + [120.0] * 12, (14, 20, 1), (32, 60, 1))
    assert out['dir'] == 'BULLISH' and out['ranging_since'] is None


def test_unbounded_when_the_history_reaches_the_first_measurable_slope(run):
    out, bars = run([100.0] * 25, (0, 999, 1))
    assert out['dir'] == 'BULLISH' and out['unbounded'] is True and out['since'] == bars[10]['time']


# -- the engine: inputs, real bands ------------------------------------------

def test_no_bars_or_too_few_bars_says_nothing():
    assert compute_respected_trend([]) == EMPTY
    assert compute_respected_trend(None) == EMPTY
    assert compute_respected_trend(_bars([100.0 + i for i in range(20)], STEP)) == EMPTY
    assert compute_respected_trend(_bars([100.0 + i for i in range(30)], STEP)) == EMPTY    # slope needs 38 bars


def test_the_defaults_are_the_calibrated_values():
    assert (rt.RESPECT_SLOPE_BARS, rt.RESPECT_SLOPE_ENTER, rt.RESPECT_SLOPE_EXIT) == (10, 0.6, 0.3)
    assert (rt.RESPECT_MIN_TAGS, rt.RESPECT_MAX_LOSSES, rt.RESPECT_WINDOW_BARS) == (2, 1, 30)


def test_real_bands_a_steady_climb_is_one_bullish_history_without_tags():
    bars = _bars([100.0 + 0.5 * i for i in range(300)], STEP)
    out = compute_respected_trend(bars)
    assert out['dir'] == 'BULLISH' and out['tags'] == 0 and out['losses'] == 0
    assert out['unbounded'] is True and out['since'] == bars[37]['time']     # first slope: EMA exists from bar 27


def test_real_bands_a_flat_market_has_no_history():
    assert compute_respected_trend(_bars([100.0] * 200, STEP)) == EMPTY


def test_real_bands_a_fall_after_a_climb_is_a_seen_reversal():
    closes = [100.0 + 0.5 * i for i in range(200)] + [200.0 - 1.5 * i for i in range(120)]
    out = compute_respected_trend(_bars(closes, STEP))
    assert out['dir'] == 'BEARISH' and out['unbounded'] is False


def test_the_noodle_state_still_flips_on_one_close():
    """One close beyond the lower band flips the noodle `state` but not the respected history."""
    from src.engines.noodle_bands import compute_noodle_state
    closes = [100.0 + 0.5 * i for i in range(120)]
    bars = _bars(closes + [closes[-1] - 40.0], STEP)
    noodle = compute_noodle_state(bars)
    assert noodle['state'] == 'BEARISH'
    out = compute_respected_trend(bars)
    assert out['dir'] == 'BULLISH' and out['losses'] == 0


# -- the migration -------------------------------------------------------

def _cols(path):
    conn = sqlite3.connect(path)
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(noodle_state)")}
    finally:
        conn.close()


def test_init_db_adds_the_respect_columns_and_twice_is_a_noop(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(portfolio_db, 'get_db_path', lambda: path)
    portfolio_db.init_db()
    portfolio_db.init_db()
    assert set(RESPECT_COLUMNS) <= _cols(path)


def test_upgrade_keeps_existing_rows_and_leaves_the_new_columns_null(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(portfolio_db, 'get_db_path', lambda: path)
    portfolio_db.init_db()
    conn = sqlite3.connect(path)
    for col in RESPECT_COLUMNS:                  # back to the pre-Landing 50 table
        conn.execute(f"ALTER TABLE noodle_state DROP COLUMN {col}")
    conn.execute("INSERT INTO noodle_state (symbol, timeframe, state, upper_band, computed_at, doc_ema_fast) "
                 "VALUES ('ETH', '4h', 'BULLISH', 110.0, '2026-10-17T00:00:00+00:00', 99.5)")
    conn.commit()
    conn.close()
    assert not set(RESPECT_COLUMNS) & _cols(path)

    portfolio_db.init_db()

    assert set(RESPECT_COLUMNS) <= _cols(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM noodle_state WHERE symbol='ETH'").fetchone()
    conn.close()
    assert row['state'] == 'BULLISH' and row['upper_band'] == 110.0 and row['doc_ema_fast'] == 99.5
    assert all(row[c] is None for c in RESPECT_COLUMNS)


def test_upgrade_from_landing_50c_adds_the_slope_columns_and_keeps_the_row(tmp_path, monkeypatch):
    path = str(tmp_path / 'portfolio.db')
    monkeypatch.setattr(portfolio_db, 'get_db_path', lambda: path)
    portfolio_db.init_db()
    conn = sqlite3.connect(path)
    for col in LANDING_51_COLUMNS:               # the table as Landing 50c left it
        conn.execute(f"ALTER TABLE noodle_state DROP COLUMN {col}")
    conn.execute("INSERT INTO noodle_state (symbol, timeframe, state, computed_at, respect_dir, respect_tags, "
                 "respect_last_ts, respect_unbounded, respect_breaks) VALUES "
                 "('ETH', '4h', 'BULLISH', '2026-10-18T00:00:00+00:00', 'BULLISH', 3, 1760000000.0, 0, 1)")
    conn.commit()
    conn.close()
    assert not set(LANDING_51_COLUMNS) & _cols(path)

    portfolio_db.init_db()
    portfolio_db.init_db()

    assert set(LANDING_51_COLUMNS) <= _cols(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM noodle_state WHERE symbol='ETH'").fetchone()
    conn.close()
    assert row['respect_dir'] == 'BULLISH' and row['respect_tags'] == 3
    assert row['respect_last_ts'] == 1760000000.0 and row['respect_unbounded'] == 0 and row['respect_breaks'] == 1
    assert all(row[c] is None for c in LANDING_51_COLUMNS)


# -- the scan and the route ---------------------------------------------

NOODLE_STATE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS noodle_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        state TEXT,
        flip_ts REAL,
        flip_price REAL,
        flip_age_unbounded INTEGER,
        flip_count_window INTEGER,
        alignment_bull INTEGER,
        alignment_bear INTEGER,
        basis_ema REAL,
        upper_band REAL,
        lower_band REAL,
        last_close REAL,
        price REAL,
        computed_at TEXT,
        volume_24h REAL,
        alignment_state TEXT,
        alignment_prev_state TEXT,
        alignment_changed_ts REAL,
        alignment_changed_unbounded INTEGER,
        rs_vs_btc_pct REAL,
        doc_ema_fast REAL,
        doc_ema_slow REAL,
        doc_cross_state TEXT,
        doc_cross_ts REAL,
        doc_cross_unbounded INTEGER,
        respect_dir TEXT,
        respect_tags INTEGER,
        respect_last_ts REAL,
        respect_unbounded INTEGER,
        respect_breaks INTEGER,
        respect_since REAL,
        respect_losses INTEGER,
        respect_ranging_since REAL,
        poi_type TEXT,
        poi_top REAL,
        poi_bottom REAL,
        poi_ts REAL,
        poi_at_band INTEGER,
        poi_count INTEGER,
        UNIQUE(symbol, timeframe)
    )
"""

NOODLE_SCAN_RUNS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS noodle_scan_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trigger TEXT NOT NULL,
        status TEXT NOT NULL,
        started_ts REAL NOT NULL,
        updated_ts REAL NOT NULL,
        finished_ts REAL,
        total INTEGER,
        done INTEGER NOT NULL DEFAULT 0,
        errors INTEGER NOT NULL DEFAULT 0,
        retired INTEGER,
        error_msg TEXT
    )
"""


@pytest.fixture
def noodle_db(monkeypatch):
    uri = f"file:respected_trend_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    keepalive.row_factory = sqlite3.Row
    keepalive.executescript(NOODLE_STATE_SCHEMA)
    keepalive.executescript(NOODLE_SCAN_RUNS_SCHEMA)
    keepalive.commit()

    def fake_get_connection():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(portfolio_db, "get_connection", fake_get_connection)
    yield keepalive
    keepalive.close()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def test_scan_stores_the_respected_trend_on_four_rows_and_not_on_1w(noodle_db, tmp_path, monkeypatch):
    monkeypatch.setattr(wp, "_SCANNER_SETTINGS_PATH", str(tmp_path / "scanner_settings.json"))
    monkeypatch.setattr(wp, '_hl_fetch_top_volume', lambda n=None, limit=None: [
        {'name': 'ETH', 'symbol': 'ETH-USDT', 'volume_24h': 1000.0, 'price': 100.0,
         'asset_type': 'crypto'}])
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    # Steep enough that the slow EMA's slope (0.5 a bar against an ATR of about 2) opens histories.
    dailies_deep = _bars(_down_then_up(450, 251, start=500.0, step=0.5), 86400)
    h1_deep = _bars(_down_then_up(1700, 1101, start=1000.0, step=0.5), 3600)
    h12 = _bars(_down_then_up(180, 121, start=500.0, step=0.5), 43200)
    monkeypatch.setattr(wp, '_hl_fetch_candles',
                        lambda coin, interval, limit=200: {'1d': dailies_deep, '12h': h12, '1h': h1_deep}[interval])

    payload, status = wp._run_noodle_scan_body()
    assert status == 200 and payload['scanned'] == 1 and payload['errors'] == 0

    rows = {r['timeframe']: dict(r) for r in noodle_db.execute(
        "SELECT * FROM noodle_state WHERE symbol='ETH'").fetchall()}
    old_dailies = dailies_deep[-301:]
    old_h1 = h1_deep[-1440:]
    expected_inputs = {
        '1d': old_dailies[:-1],
        '12h': h12[:-1],
        '4h': wp._h4_from_h1(old_h1, limit=360)[:-1],
        '1h': old_h1[:-1],
    }
    seen_a_run = False
    for tf, closed in expected_inputs.items():
        exp = compute_respected_trend(closed, slow=28, atr_length=14, band_multiplier=0.011875, use_atr=True)
        r = rows[tf]
        assert r['respect_dir'] == exp['dir'], tf
        assert r['respect_tags'] == exp['tags'], tf
        assert r['respect_last_ts'] == exp['last_ts'], tf
        assert r['respect_unbounded'] == (int(exp['unbounded']) if exp['unbounded'] is not None else None), tf
        assert r['respect_since'] == exp['since'], tf
        assert r['respect_losses'] == exp['losses'], tf
        assert r['respect_ranging_since'] == exp['ranging_since'], tf
        assert r['respect_breaks'] is None, tf                      # legacy column: no longer written
        seen_a_run = seen_a_run or exp['dir'] is not None
        assert r['state'] == wp.compute_noodle_state(closed)['state'], tf     # the noodle state is unchanged
    assert seen_a_run
    assert all(rows['1w'][c] is None for c in RESPECT_COLUMNS)


def test_scan_stores_each_respect_field_in_its_own_column(noodle_db, tmp_path, monkeypatch):
    """Distinct sentinel values per field and timeframe catch a transposed column in the INSERT (40 values since Landing 58)."""
    monkeypatch.setattr(wp, "_SCANNER_SETTINGS_PATH", str(tmp_path / "scanner_settings.json"))
    monkeypatch.setattr(wp, '_hl_fetch_top_volume', lambda n=None, limit=None: [
        {'name': 'ETH', 'symbol': 'ETH-USDT', 'volume_24h': 1000.0, 'price': 100.0,
         'asset_type': 'crypto'}])
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    series = {'1d': _bars(_down_then_up(450, 251), 86400),
              '12h': _bars(_down_then_up(180, 121, step=0.2), 43200),
              '1h': _bars(_down_then_up(1700, 1101, step=0.01), 3600)}
    monkeypatch.setattr(wp, '_hl_fetch_candles', lambda coin, interval, limit=200: series[interval])
    calls = []

    def fake(closed, **kwargs):
        calls.append(len(closed))
        k = len(calls)
        if k % 2:       # histories: sentinel values that differ per call
            return {'dir': 'BULLISH', 'tags': 3 + k, 'last_ts': 1000.5 + k, 'unbounded': k == 1,
                    'since': 2000.5 + k, 'losses': k, 'ranging_since': None}
        return {'dir': None, 'tags': None, 'last_ts': None, 'unbounded': None,
                'since': None, 'losses': None, 'ranging_since': 3000.5 + k}

    monkeypatch.setattr(wp, 'compute_respected_trend', fake)
    payload, status = wp._run_noodle_scan_body()
    assert status == 200 and payload['errors'] == 0
    assert len(calls) == 4                                           # 1d, 12h, 4h, 1h; never 1w
    rows = {r['timeframe']: dict(r) for r in noodle_db.execute("SELECT * FROM noodle_state").fetchall()}
    by_call = {}
    for tf, row in rows.items():
        if tf == '1w':
            continue
        by_call[tf] = (row['respect_dir'], row['respect_tags'], row['respect_last_ts'], row['respect_unbounded'],
                       row['respect_since'], row['respect_losses'], row['respect_ranging_since'], row['respect_breaks'])
    histories = [v for v in by_call.values() if v[0] == 'BULLISH']
    flats = [v for v in by_call.values() if v[0] is None]
    assert len(histories) == 2 and len(flats) == 2
    for dir_, tags, last_ts, unbounded, since, losses, ranging, breaks in histories:
        k = int(losses)
        assert tags == 3 + k and last_ts == 1000.5 + k and since == 2000.5 + k
        assert unbounded == (1 if k == 1 else 0) and ranging is None and breaks is None
    for dir_, tags, last_ts, unbounded, since, losses, ranging, breaks in flats:
        assert tags is None and last_ts is None and unbounded is None and since is None and losses is None
        assert ranging in (3002.5, 3004.5) and breaks is None


def test_route_returns_the_respect_columns(client, noodle_db, monkeypatch):
    monkeypatch.setattr(wp, '_maybe_kick_noodle_auto_refresh', lambda: False)
    monkeypatch.setattr(wp, '_hl_refresh_universes', lambda force=False: None)
    noodle_db.execute(
        "INSERT INTO noodle_state (symbol, timeframe, state, computed_at, respect_dir, respect_tags, "
        "respect_last_ts, respect_unbounded, respect_breaks, respect_since, respect_losses, respect_ranging_since) "
        "VALUES ('ETH', '4h', 'BULLISH', '2026-10-17T00:00:00+00:00', 'BULLISH', 3, 1760000000.0, 0, NULL, "
        "1759000000.0, 1, NULL)")
    noodle_db.execute(
        "INSERT INTO noodle_state (symbol, timeframe, state, computed_at, respect_dir, respect_tags, "
        "respect_last_ts, respect_unbounded, respect_breaks, respect_since, respect_losses, respect_ranging_since) "
        "VALUES ('ETH', '1d', 'BEARISH', '2026-10-17T00:00:00+00:00', NULL, NULL, NULL, NULL, NULL, "
        "NULL, NULL, 1758000000.0)")
    noodle_db.execute(
        "INSERT INTO noodle_state (symbol, timeframe, state, computed_at) VALUES "
        "('ETH', '1w', 'BULLISH', '2026-10-17T00:00:00+00:00')")
    noodle_db.commit()
    resp = client.get('/api/trading/scanner/noodle-state')
    assert resp.status_code == 200
    tfs = resp.get_json()['symbols'][0]['timeframes']
    assert tfs['4h']['respect_dir'] == 'BULLISH' and tfs['4h']['respect_tags'] == 3
    assert tfs['4h']['respect_last_ts'] == 1760000000.0 and tfs['4h']['respect_unbounded'] is False
    assert tfs['4h']['respect_since'] == 1759000000.0 and tfs['4h']['respect_losses'] == 1
    assert tfs['4h']['respect_ranging_since'] is None and tfs['4h']['respect_breaks'] is None
    assert tfs['1d']['respect_dir'] is None and tfs['1d']['respect_tags'] is None
    assert tfs['1d']['respect_unbounded'] is None and tfs['1d']['respect_since'] is None
    assert tfs['1d']['respect_ranging_since'] == 1758000000.0
    assert all(tfs['1w'][c] is None for c in RESPECT_COLUMNS)


def test_a_failing_detector_leaves_the_noodle_rows_intact(noodle_db, tmp_path, monkeypatch):
    monkeypatch.setattr(wp, "_SCANNER_SETTINGS_PATH", str(tmp_path / "scanner_settings.json"))
    monkeypatch.setattr(wp, '_hl_fetch_top_volume', lambda n=None, limit=None: [
        {'name': 'ETH', 'symbol': 'ETH-USDT', 'volume_24h': 1000.0, 'price': 100.0,
         'asset_type': 'crypto'}])
    monkeypatch.setattr(wp, '_hl_resolve_coin', lambda s: s)
    series = {'1d': _bars(_down_then_up(450, 251), 86400),
              '12h': _bars(_down_then_up(180, 121, step=0.2), 43200),
              '1h': _bars(_down_then_up(1700, 1101, step=0.01), 3600)}
    monkeypatch.setattr(wp, '_hl_fetch_candles', lambda coin, interval, limit=200: series[interval])

    def boom(*a, **k):
        raise RuntimeError('boom')

    monkeypatch.setattr(wp, 'compute_respected_trend', boom)
    payload, status = wp._run_noodle_scan_body()
    assert status == 200 and payload['scanned'] == 1 and payload['errors'] == 0
    rows = noodle_db.execute("SELECT * FROM noodle_state WHERE symbol='ETH'").fetchall()
    assert len(rows) == 5
    assert all(r['state'] is not None for r in rows)
    assert all(r[c] is None for r in rows for c in RESPECT_COLUMNS)
