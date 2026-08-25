# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure selection helpers for room top/bottom height evidence."""


DEFAULT_BUCKET_STEP_M = 0.05
LOWERED_TOLERANCE_M = 0.03
MULTI_LEVEL_TOLERANCE_M = 0.08
MIN_BOTTOM_COVERAGE_RATIO = 0.50
MIN_BOTTOM_DOMINANCE_RATIO = 2.0 / 3.0


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bucket_key(value, step):
    return int(round(float(value) / float(step)))


def select_bottom_surface(hits, reference_base_m, room_lower_offset_m=None,
                          bucket_step_m=DEFAULT_BUCKET_STEP_M):
    """Select the dominant physical floor top from sampled ray hits."""
    reference = _as_float(reference_base_m)
    if reference is None:
        return None
    step = _as_float(bucket_step_m) or DEFAULT_BUCKET_STEP_M
    if step <= 0.0:
        step = DEFAULT_BUCKET_STEP_M

    valid = []
    for hit in hits or ():
        elevation = _as_float(hit.get('elevation_m'))
        if elevation is None:
            continue
        item = dict(hit)
        item['elevation_m'] = elevation
        valid.append(item)
    if not valid:
        return None

    offset = _as_float(room_lower_offset_m)
    expected = reference + offset if offset is not None else reference
    buckets = {}
    for item in valid:
        key = _bucket_key(item['elevation_m'], step)
        bucket = buckets.setdefault(key, {
            'items': [],
            'location_count': 0,
        })
        bucket['items'].append(item)
        if item.get('is_location_sample'):
            bucket['location_count'] += 1

    ranked = []
    for key, bucket in buckets.items():
        elevations = [item['elevation_m'] for item in bucket['items']]
        average = sum(elevations) / float(len(elevations))
        ranked.append((
            -len(bucket['items']),
            -bucket['location_count'],
            abs(average - expected),
            average,
            key,
            bucket,
        ))
    ranked.sort(key=lambda item: item[:5])
    selected = ranked[0]
    average = selected[3]
    bucket = selected[5]
    runner_up_count = (
        len(ranked[1][5]['items']) if len(ranked) > 1 else 0)
    all_elevations = [item['elevation_m'] for item in valid]
    spread = max(all_elevations) - min(all_elevations)

    if average < reference - LOWERED_TOLERANCE_M:
        source = 'physical-lowered-floor-top-ray'
    elif average > reference + LOWERED_TOLERANCE_M:
        source = 'physical-raised-floor-top-ray'
    else:
        source = 'physical-floor-top-ray'

    element_ids = []
    element_names = []
    categories = []
    for item in bucket['items']:
        element_id = item.get('element_id')
        if element_id and element_id not in element_ids:
            element_ids.append(element_id)
        name = item.get('element_name')
        if name and name not in element_names:
            element_names.append(name)
        category = item.get('category')
        if category and category not in categories:
            categories.append(category)

    return {
        'elevation_m': average,
        'offset_m': average - reference,
        'source': source,
        'hit_count': len(bucket['items']),
        'total_hit_count': len(valid),
        'runner_up_count': runner_up_count,
        'dominant_ratio': len(bucket['items']) / float(len(valid)),
        'bucket_count': len(buckets),
        'spread_m': spread,
        'ambiguous': (
            len(buckets) > 1 and spread > MULTI_LEVEL_TOLERANCE_M),
        'element_ids': element_ids,
        'element_names': element_names,
        'categories': categories,
    }


def shift_height_info(info, reference_to_bottom_m, snap_height):
    """Rebase a nominal height from Room level to detected physical bottom."""
    if info is None:
        return None
    result = dict(info)
    raw = _as_float(result.get('raw_height'))
    shift = _as_float(reference_to_bottom_m)
    if raw is None or shift is None:
        return result
    raw += shift
    result['raw_height'] = raw
    result['height'] = snap_height(raw)
    return result


def choose_top_surface(ceiling_values, floor_values):
    """Apply the room clear-height priority to sampled top surfaces.

    A physical ceiling is preferred over a slab.  A slab is preferred over
    the level-based fallback, including when the slab is on a higher level in
    an open-to-above room.
    """
    if ceiling_values:
        return 'ceiling', ceiling_values
    if floor_values:
        return 'floor', floor_values
    return 'level', []


def effective_wall_height(model_height, clear_height,
                          top_attached=False, tolerance_m=0.35):
    """Use the shared clear height for full walls, retain genuine low walls."""
    model = _as_float(model_height)
    clear = _as_float(clear_height)
    if clear is None or clear <= 0.0:
        return model, 'model-height'
    if model is None or model <= 0.0:
        return clear, 'room-clear-height'
    if top_attached or model >= clear - float(tolerance_m):
        return clear, 'room-clear-height'
    return model, 'model-partial-wall-height'


def bottom_surface_is_reliable(
        selected, sample_count,
        min_coverage_ratio=MIN_BOTTOM_COVERAGE_RATIO,
        min_dominance_ratio=MIN_BOTTOM_DOMINANCE_RATIO):
    """Return whether sampled bottom evidence is safe for one room height."""
    if not selected:
        return False, 'missing'
    try:
        total_samples = int(sample_count)
    except (TypeError, ValueError):
        total_samples = 0
    if total_samples <= 0:
        return False, 'missing-samples'

    hit_count = int(selected.get('hit_count') or 0)
    coverage = hit_count / float(total_samples)
    if coverage < float(min_coverage_ratio):
        return False, 'insufficient-coverage'

    if (selected.get('ambiguous') and
            float(selected.get('dominant_ratio') or 0.0) <
            float(min_dominance_ratio)):
        return False, 'insufficient-dominance'
    return True, ''
