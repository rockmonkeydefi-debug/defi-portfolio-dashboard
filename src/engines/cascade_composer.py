"""Cascade composer (Phase 3b) — pure stage logic.

Consumes the per-TF snapshots produced by web_portfolio._compute_tf_snapshot
(the Phase 2 SnapshotRun cache) and walks each ticker through cascade stages 0-2
for the four pairs W->D, W->H12, W->H4, D->H4.

This module is deliberately free of Flask, SQLite, and network dependencies:
`compose_cascades` is a pure function of the snapshot dicts (plus optional raw
candles for zone-tap timestamps), so it is unit-testable in isolation. DB
persistence, the scan hook, and the HTTP endpoint live in web_portfolio.py.

Stage 3 (MSS_FIRED) is deferred to Phase 4; zone taps ARE recorded now because
Stage 3's future trigger needs them.
"""

# (pair_name, root_tf, nested_tf). D_H4 roots on a qualified DAILY POI.
PAIRS = [
    ('W_D',   '1w',  '1d'),
    ('W_H12', '1w',  '12h'),
    ('W_H4',  '1w',  '4h'),
    ('D_H4',  '1d',  '4h'),
]

# OTE sweet spot the shipped ranking measures depth against (web_portfolio.py:
# `ote_depth = abs(((dr_high - poi_mid)/rng) - 0.705)`). Smaller == deeper/better.
_OTE_SWEET_SPOT = 0.705


def qualified_pois(snap, tf):
    """Qualified POIs on one TF snapshot as stable-identity dicts.

    OB : shipped row['qualified'] (in-zone AND qualification.status=='qualified');
         origin_bar_ts = the cluster's last candle (e) open time = cluster_end_time.
    FVG: snap['fvgs']['candidates'] (kept = size-passed, in-zone, not fully filled);
         origin_bar_ts = the gap's first candle open time = gap_start_time.

    Both detectors already emit bias-side POIs only, so no extra bias filter is
    needed here. Returns [] for a missing/errored snapshot.
    """
    out = []
    if not snap:
        return out
    for o in snap.get('obs', []) or []:
        if o.get('qualified'):
            out.append({
                'tf': tf, 'poi_type': 'OB',
                'origin_bar_ts': o.get('cluster_end_time'),
                'bottom': o.get('bottom'), 'top': o.get('top'),
            })
    for f in (snap.get('fvgs', {}) or {}).get('candidates', []) or []:
        out.append({
            'tf': tf, 'poi_type': 'FVG',
            'origin_bar_ts': f.get('gap_start_time'),
            'bottom': f.get('bottom'), 'top': f.get('top'),
        })
    return out


def poi_id(poi):
    """Stable identity string: (tf, poi_type, origin_bar_ts). Zone prices are
    mutable attributes of this identity, deliberately excluded."""
    return f"{poi['tf']}:{poi['poi_type']}:{poi['origin_bar_ts']}"


def _ote_depth(poi, structure):
    """Depth of a POI in the OTE band, per the shipped ranking. Smaller is
    deeper (closer to the 0.705 sweet spot); missing range → worst (1e9)."""
    if not structure:
        return 1e9
    hi, lo = structure.get('dr_high'), structure.get('dr_low')
    if hi is None or lo is None:
        return 1e9
    rng = hi - lo
    if not rng:
        return 1e9
    mid = (poi['top'] + poi['bottom']) / 2.0
    return abs(((hi - mid) / rng) - _OTE_SWEET_SPOT)


def intervals_intersect(a_bottom, a_top, b_bottom, b_top):
    """True iff price intervals [bottom, top] intersect. Exact touch
    (max(bottoms) == min(tops)) counts as intersecting."""
    return max(a_bottom, b_bottom) <= min(a_top, b_top)


def _overlap_width(a, b):
    return min(a['top'], b['top']) - max(a['bottom'], b['bottom'])


def compute_taps(zone_bottom, zone_top, origin_bar_ts, candles):
    """first/last timestamps of nested-TF candles whose [low, high] intersects
    the nested POI zone at ANY BAR AFTER formation (candle time > origin_bar_ts).

    Annotation only — never changes stage. Returns (first_ts, last_ts) as the
    candles' own epoch-second times, or (None, None) if never tapped / no data.
    """
    if not candles or zone_bottom is None or zone_top is None:
        return None, None
    taps = []
    for c in candles:
        t = c.get('time')
        if t is None or origin_bar_ts is None or t <= origin_bar_ts:
            continue
        lo, hi = c.get('low'), c.get('high')
        if lo is None or hi is None:
            continue
        if lo <= zone_top and hi >= zone_bottom:   # candle range ∩ zone
            taps.append(t)
    if not taps:
        return None, None
    return min(taps), max(taps)


def compose_cascades(snaps, candles_by_tf=None):
    """Compute the four cascade pair-states for ONE symbol.

    snaps: {'1w': snap, '1d': snap, '12h': snap, '4h': snap} — per-TF snapshots
           from _compute_tf_snapshot (a missing/errored TF may be None).
    candles_by_tf: optional {tf: [candle, ...]} used only for zone-tap
           timestamps on the Stage-2 nested POI. Omit → taps are None.

    Returns {pair_name: pair_state}. Each pair_state is a plain dict:
      stage (0/1/2), root_bias,
      root_poi / nested_poi (the BEST one, or None): {poi_id, poi_type,
        origin_bar_ts, zone_bottom, zone_top},
      first_tap_at / last_tap_at (epoch seconds or None),
      root_candidates / nested_candidates (full qualified lists),
      overlaps (list of {nested_id, root_id, overlap_bottom, overlap_top,
        overlap_width}) — the Stage-2 evidence, for the diagnose payload.
    No DB, no network, no mutation of the inputs.
    """
    candles_by_tf = candles_by_tf or {}
    out = {}
    for (pair_name, root_tf, nested_tf) in PAIRS:
        root_snap = snaps.get(root_tf)
        nested_snap = snaps.get(nested_tf)
        root_struct = (root_snap or {}).get('structure') or {}
        root_bias = root_struct.get('bias')

        root_pois = qualified_pois(root_snap, root_tf)
        nested_pois = qualified_pois(nested_snap, nested_tf)

        state = {
            'pair': pair_name, 'root_tf': root_tf, 'nested_tf': nested_tf,
            'stage': 0, 'root_bias': root_bias,
            'root_poi': None, 'nested_poi': None,
            'first_tap_at': None, 'last_tap_at': None,
            'root_candidates': [{**p, 'poi_id': poi_id(p)} for p in root_pois],
            'nested_candidates': [{**p, 'poi_id': poi_id(p)} for p in nested_pois],
            'overlaps': [],
        }

        if not root_pois:
            out[pair_name] = state           # Stage 0 — NO_ROOT
            continue

        # Stage >= 1. Best root = deepest in OTE (shipped ranking).
        best_root = min(root_pois, key=lambda p: _ote_depth(p, root_struct))
        state['stage'] = 1
        state['root_poi'] = _poi_slot(best_root)

        # Stage 2 candidates: nested POIs intersecting ANY root zone.
        overlaps = []
        for npoi in nested_pois:
            best = None
            for rp in root_pois:
                if intervals_intersect(rp['bottom'], rp['top'],
                                       npoi['bottom'], npoi['top']):
                    w = _overlap_width(rp, npoi)
                    if best is None or w > best['overlap_width']:
                        best = {
                            'nested_id': poi_id(npoi), 'root_id': poi_id(rp),
                            'overlap_bottom': max(rp['bottom'], npoi['bottom']),
                            'overlap_top': min(rp['top'], npoi['top']),
                            'overlap_width': w, '_nested': npoi,
                        }
            if best is not None:
                overlaps.append(best)

        if overlaps:
            state['stage'] = 2               # NESTED_POI
            best_ov = max(overlaps, key=lambda x: x['overlap_width'])
            best_nested = best_ov['_nested']
            state['nested_poi'] = _poi_slot(best_nested)
            first_tap, last_tap = compute_taps(
                best_nested['bottom'], best_nested['top'],
                best_nested['origin_bar_ts'], candles_by_tf.get(nested_tf))
            state['first_tap_at'] = first_tap
            state['last_tap_at'] = last_tap
            state['overlaps'] = [
                {k: v for k, v in o.items() if k != '_nested'} for o in overlaps]

        out[pair_name] = state
    return out


def _poi_slot(poi):
    """The persisted/best-POI projection of a qualified POI."""
    return {
        'poi_id': poi_id(poi), 'poi_type': poi['poi_type'],
        'origin_bar_ts': poi['origin_bar_ts'],
        'zone_bottom': poi['bottom'], 'zone_top': poi['top'],
    }


def diff_transitions(prior, new_state):
    """Diff a prior cascade_state row (dict-like, or None) against a freshly
    composed pair-state; return the list of transition dicts to append.

    Reasons: rooted / nested / root_lost / nested_lost / bias_flip / poi_replaced.
    bias_flip is checked BEFORE root_lost so the nuke reason wins. When a bias
    flip fires, the branch nukes to Stage 0 this cycle regardless of any
    freshly-formed opposite-bias root (which re-roots on the next compose).

    Returns (transitions, forced_state) where forced_state is None normally, or
    a Stage-0 override dict when a bias flip nuked the branch.
    """
    prior_stage = int(prior['stage']) if prior else 0
    prior_bias = (prior['root_bias'] if prior else None) or None
    prior_root_id = (prior['root_poi_id'] if prior else None) or None
    prior_nested_id = (prior['nested_poi_id'] if prior else None) or None

    new_stage = new_state['stage']
    new_bias = new_state.get('root_bias')
    new_root_id = (new_state['root_poi'] or {}).get('poi_id')
    new_nested_id = (new_state['nested_poi'] or {}).get('poi_id')

    def _t(from_s, to_s, reason):
        return {'from_stage': from_s, 'to_stage': to_s, 'reason': reason,
                'root_poi_id': new_root_id, 'nested_poi_id': new_nested_id}

    # ── Bias flip on the root TF = branch nuke (wins over root_lost). ──
    if prior_stage >= 1 and prior_bias and new_bias and new_bias != prior_bias:
        nuke = {'from_stage': prior_stage, 'to_stage': 0, 'reason': 'bias_flip',
                'root_poi_id': prior_root_id, 'nested_poi_id': prior_nested_id}
        return [nuke], 'nuke'

    transitions = []
    if new_stage == 0 and prior_stage >= 1:
        transitions.append(_t(prior_stage, 0, 'root_lost'))
    elif new_stage == 1 and prior_stage == 2:
        transitions.append(_t(2, 1, 'nested_lost'))
    elif new_stage > prior_stage:
        # Stepwise promotion so the ladder stays legible (0->2 logs both).
        if prior_stage == 0:
            transitions.append(_t(0, 1, 'rooted'))
        if new_stage == 2:
            transitions.append(_t(1, 2, 'nested'))
    elif new_stage == prior_stage and new_stage >= 1:
        # Stage unchanged — did the best POI identity change?
        replaced = (new_root_id != prior_root_id) or (
            new_stage == 2 and new_nested_id != prior_nested_id)
        if replaced:
            transitions.append(_t(new_stage, new_stage, 'poi_replaced'))

    return transitions, None
