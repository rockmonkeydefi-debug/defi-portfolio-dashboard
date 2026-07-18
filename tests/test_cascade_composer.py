"""Cascade composer unit tests (Phase 3b) — pure logic, no network, no DB.

Exercises src.engines.cascade_composer directly: stage 0/1/2 assignment, overlap
boundary cases, POI identity stability, bias-flip nuke, demotions, transition
ordering, and zone taps.
"""
from src.engines.cascade_composer import (
    compose_cascades, diff_transitions, intervals_intersect, compute_taps,
    qualified_pois, poi_id,
)

DAY = 86400
T0 = 1_700_000_000


def _snap(bias, dr_high, dr_low, obs=(), fvgs=()):
    """obs/fvgs items: (bottom, top, origin_ts[, qualified]). Default qualified."""
    def _ob(item):
        b, t, ts = item[0], item[1], item[2]
        q = item[3] if len(item) > 3 else True
        return {'qualified': q, 'top': t, 'bottom': b,
                'cluster_end_time': ts, 'type': bias}

    def _fvg(item):
        b, t, ts = item[0], item[1], item[2]
        return {'top': t, 'bottom': b, 'gap_start_time': ts}

    return {
        'structure': {'bias': bias, 'dr_high': dr_high, 'dr_low': dr_low},
        'obs': [_ob(o) for o in obs],
        'fvgs': {'candidates': [_fvg(f) for f in fvgs]},
        'levels': {},
    }


def _state_row(stage, root_bias, root_id=None, nested_id=None):
    """A prior cascade_state row (as read from SQLite)."""
    return {'stage': stage, 'root_bias': root_bias,
            'root_poi_id': root_id, 'nested_poi_id': nested_id}


# ── extraction ────────────────────────────────────────────────────────────
def test_qualified_pois_excludes_unqualified_ob():
    snap = _snap('bearish', 110, 90,
                 obs=[(100, 108, 1000, True), (95, 105, 2000, False)],
                 fvgs=[(96, 102, 3000)])
    pois = qualified_pois(snap, '1w')
    kinds = sorted(p['poi_type'] for p in pois)
    assert kinds == ['FVG', 'OB']            # the unqualified OB is dropped
    assert poi_id(pois[0]) == '1w:OB:1000'


# ── stage assignment ──────────────────────────────────────────────────────
def test_stage0_no_root():
    snaps = {'1w': _snap('bearish', 110, 90), '1d': None,
             '12h': None, '4h': None}
    st = compose_cascades(snaps)
    assert st['W_D']['stage'] == 0
    assert st['W_D']['root_poi'] is None


def test_stage1_root_but_no_nested_overlap():
    root = _snap('bearish', 200, 100, obs=[(150, 160, 1000)])
    nested = _snap('bearish', 200, 100, obs=[(120, 130, 2000)])   # disjoint
    snaps = {'1w': root, '1d': nested, '12h': None, '4h': None}
    st = compose_cascades(snaps)['W_D']
    assert st['stage'] == 1
    assert st['root_poi']['poi_id'] == '1w:OB:1000'
    assert st['nested_poi'] is None


def test_stage2_nested_overlaps_root():
    root = _snap('bearish', 200, 100, obs=[(150, 160, 1000)])
    nested = _snap('bearish', 200, 100, obs=[(155, 170, 2000)])   # overlaps 155-160
    snaps = {'1w': root, '1d': nested, '12h': None, '4h': None}
    st = compose_cascades(snaps)['W_D']
    assert st['stage'] == 2
    assert st['nested_poi']['poi_id'] == '1d:OB:2000'
    assert st['overlaps'][0]['overlap_bottom'] == 155
    assert st['overlaps'][0]['overlap_top'] == 160


def test_d_h4_pair_roots_on_daily():
    # D_H4 stage 2 depends on DAILY root ∩ H4 nested, independent of weekly.
    daily = _snap('bearish', 50, 30, obs=[(40, 44, 1000)])
    h4 = _snap('bearish', 50, 30, fvgs=[(42, 46, 2000)])          # overlaps 42-44
    snaps = {'1w': None, '1d': daily, '12h': None, '4h': h4}
    st = compose_cascades(snaps)['D_H4']
    assert st['stage'] == 2
    assert st['root_poi']['poi_id'] == '1d:OB:1000'
    assert st['nested_poi']['poi_id'] == '4h:FVG:2000'


# ── overlap boundary ──────────────────────────────────────────────────────
def test_exact_touch_counts_as_intersecting():
    assert intervals_intersect(100, 110, 110, 120) is True        # max==min


def test_disjoint_does_not_intersect():
    assert intervals_intersect(100, 110, 111, 120) is False


def test_exact_touch_promotes_to_stage2():
    root = _snap('bearish', 300, 100, obs=[(100, 110, 1000)])
    nested = _snap('bearish', 300, 100, obs=[(110, 120, 2000)])   # touches at 110
    snaps = {'1w': root, '1d': nested, '12h': None, '4h': None}
    assert compose_cascades(snaps)['W_D']['stage'] == 2


# ── identity stability ────────────────────────────────────────────────────
def test_wiggled_zone_prices_same_identity_no_transition():
    # Same origin_bar_ts, different zone prices → same poi_id → no transition.
    root_v1 = _snap('bearish', 200, 100, obs=[(150, 160, 1000)])
    st_v1 = compose_cascades({'1w': root_v1, '1d': None, '12h': None, '4h': None})['W_D']
    prior = _state_row(1, 'bearish', root_id='1w:OB:1000')

    root_v2 = _snap('bearish', 201, 99, obs=[(151, 162, 1000)])   # prices moved
    st_v2 = compose_cascades({'1w': root_v2, '1d': None, '12h': None, '4h': None})['W_D']
    transitions, forced = diff_transitions(prior, st_v2)
    assert transitions == []
    assert forced is None


def test_new_origin_ts_is_poi_replaced():
    prior = _state_row(1, 'bearish', root_id='1w:OB:1000')
    new_root = _snap('bearish', 200, 100, obs=[(150, 160, 9999)])  # new origin ts
    st = compose_cascades({'1w': new_root, '1d': None, '12h': None, '4h': None})['W_D']
    transitions, forced = diff_transitions(prior, st)
    assert len(transitions) == 1
    assert transitions[0]['reason'] == 'poi_replaced'
    assert transitions[0]['from_stage'] == 1 and transitions[0]['to_stage'] == 1


# ── bias flip nuke ────────────────────────────────────────────────────────
def test_bias_flip_nukes_branch_before_root_lost():
    prior = _state_row(2, 'bearish', root_id='1w:OB:1000', nested_id='1d:OB:2000')
    new_state = {'stage': 1, 'root_bias': 'bullish',
                 'root_poi': {'poi_id': '1w:OB:5000'}, 'nested_poi': None}
    transitions, forced = diff_transitions(prior, new_state)
    assert forced == 'nuke'
    assert len(transitions) == 1
    assert transitions[0]['reason'] == 'bias_flip'
    assert transitions[0]['to_stage'] == 0
    assert transitions[0]['from_stage'] == 2


# ── demotions ─────────────────────────────────────────────────────────────
def test_root_lost_demotes_to_zero():
    prior = _state_row(2, 'bearish', root_id='1w:OB:1000', nested_id='1d:OB:2000')
    new_state = {'stage': 0, 'root_bias': 'bearish',
                 'root_poi': None, 'nested_poi': None}
    transitions, forced = diff_transitions(prior, new_state)
    assert forced is None
    assert [t['reason'] for t in transitions] == ['root_lost']
    assert transitions[0]['from_stage'] == 2 and transitions[0]['to_stage'] == 0


def test_nested_lost_demotes_two_to_one():
    prior = _state_row(2, 'bearish', root_id='1w:OB:1000', nested_id='1d:OB:2000')
    new_state = {'stage': 1, 'root_bias': 'bearish',
                 'root_poi': {'poi_id': '1w:OB:1000'}, 'nested_poi': None}
    transitions, forced = diff_transitions(prior, new_state)
    assert [t['reason'] for t in transitions] == ['nested_lost']
    assert transitions[0]['from_stage'] == 2 and transitions[0]['to_stage'] == 1


# ── promotions / append-only ordering ─────────────────────────────────────
def test_fresh_symbol_to_stage2_logs_rooted_then_nested_in_order():
    prior = None                                     # never seen before
    new_state = {'stage': 2, 'root_bias': 'bearish',
                 'root_poi': {'poi_id': '1w:OB:1000'},
                 'nested_poi': {'poi_id': '1d:OB:2000'}}
    transitions, forced = diff_transitions(prior, new_state)
    assert [t['reason'] for t in transitions] == ['rooted', 'nested']
    assert transitions[0]['from_stage'] == 0 and transitions[0]['to_stage'] == 1
    assert transitions[1]['from_stage'] == 1 and transitions[1]['to_stage'] == 2


def test_stage0_to_stage0_no_transition():
    prior = _state_row(0, None)
    new_state = {'stage': 0, 'root_bias': None,
                 'root_poi': None, 'nested_poi': None}
    transitions, forced = diff_transitions(prior, new_state)
    assert transitions == []


# ── zone taps ─────────────────────────────────────────────────────────────
def test_compute_taps_only_after_formation():
    zone_b, zone_t, origin = 100, 110, T0 + 5 * DAY
    candles = [
        {'time': T0 + 3 * DAY, 'low': 101, 'high': 109},   # before formation → ignored
        {'time': T0 + 6 * DAY, 'low': 95, 'high': 102},    # taps (intersects)
        {'time': T0 + 7 * DAY, 'low': 120, 'high': 130},   # above zone → no tap
        {'time': T0 + 8 * DAY, 'low': 108, 'high': 115},   # taps
    ]
    first, last = compute_taps(zone_b, zone_t, origin, candles)
    assert first == T0 + 6 * DAY
    assert last == T0 + 8 * DAY


def test_compute_taps_none_when_untapped():
    candles = [{'time': T0 + 9 * DAY, 'low': 200, 'high': 210}]
    assert compute_taps(100, 110, T0, candles) == (None, None)
