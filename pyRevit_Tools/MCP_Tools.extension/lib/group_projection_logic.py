# -*- coding: utf-8 -*-
"""Pure, IronPython 2.7-compatible elevation and group colour helpers."""
from __future__ import division

import colorsys
import math


_LABELS = {'above': u'↑ 上方', 'below': u'↓ 下方',
           'same': u'↔ 同高', 'unknown': u'↕ 未知'}
_PALETTES = {
    'above': ((220, 60, 40), (235, 120, 35), (190, 45, 65)),
    'below': ((40, 100, 220), (35, 155, 200), (75, 65, 190)),
    'same': ((110, 110, 110), (145, 145, 145), (180, 180, 180)),
    'unknown': ((90, 90, 90), (125, 125, 125), (160, 160, 160)),
}


def _finite(value):
    try:
        value = float(value)
        return value if not (math.isnan(value) or math.isinf(value)) else None
    except (TypeError, ValueError, OverflowError):
        return None


def relation(source_elevation_ft, target_elevation_ft,
             tolerance_ft=1 / 304.8):
    """Compare elevations in feet; the inclusive default tolerance is 1 mm.

    Missing/non-finite elevations or an invalid tolerance return 'unknown'.
    """
    source = _finite(source_elevation_ft)
    target = _finite(target_elevation_ft)
    tolerance = _finite(tolerance_ft)
    if source is None or target is None or tolerance is None or tolerance < 0:
        return 'unknown'
    # Compare against bounds to avoid subtraction error at a nonzero datum.
    if source > target + tolerance:
        return 'above'
    if source < target - tolerance:
        return 'below'
    return 'same'


def _colors(direction):
    for rgb in _PALETTES[direction]:
        yield rgb
    # A bounded HSV grid avoids palette wrapping and keeps direction hues.
    for index in range(32768):
        phase = ((index % 32) * 19 % 32) / 31.0
        saturation_step = (index // 32) % 16
        value_step = index // 512
        if direction == 'above':
            hue = phase * 0.12
        elif direction == 'below':
            hue = 0.50 + phase * 0.20
        else:
            hue = phase
        saturation = (0.55 + saturation_step * 0.025
                      if direction in ('above', 'below')
                      else 0.02 + saturation_step * 0.006)
        value = 0.95 - value_step * 0.006
        yield tuple(int(channel * 255 + 0.5) for channel in
                    colorsys.hsv_to_rgb(hue, saturation, value))


def assign_colors(records, target_elevation_ft):
    """Return {id: {relation, rgb, hex, label}} without changing records.

    IDs must be unique and mutually sortable (normally integer element IDs).
    Each relation sorts IDs independently; input order never affects colours.
    Neutral colours have low saturation. RGB collisions are skipped globally.
    Raises ValueError for duplicate IDs or exhaustion of distinct colours.
    """
    buckets = dict((key, []) for key in _LABELS)
    seen = set()
    for record in records:
        group_id = record['id']
        if group_id in seen:
            raise ValueError('Duplicate group ID: {0}'.format(group_id))
        seen.add(group_id)
        direction = relation(record.get('elevation'), target_elevation_ft)
        buckets[direction].append(group_id)
    result = {}
    used = set()
    for direction in ('above', 'below', 'same', 'unknown'):
        candidates = _colors(direction)
        for group_id in sorted(buckets[direction]):
            for rgb in candidates:
                if rgb not in used:
                    break
            else:
                raise ValueError('Distinct group colours exhausted')
            used.add(rgb)
            result[group_id] = {
                'relation': direction, 'rgb': rgb,
                'hex': '#{0:02X}{1:02X}{2:02X}'.format(*rgb),
                'label': _LABELS[direction],
            }
    return result


def interleave_coincident(segments):
    """Reveal exact overlapping segments without moving their XY positions.

    Inputs/outputs are (xyz tuple, xyz tuple, rgb tuple), in internal feet.
    Only matching full spans (rounded to 8 decimals) are interleaved; this is
    not a general partial-intersection or curved-path overlap solver.
    """
    groups = {}
    for a, b, rgb in segments:
        a, b, rgb = tuple(a), tuple(b), tuple(rgb)
        if b < a:
            a, b = b, a
        key = (tuple(round(v, 8) for v in a), tuple(round(v, 8) for v in b))
        if key not in groups:
            groups[key] = [a, b, set()]
        groups[key][2].add(rgb)
    result = []
    for key in sorted(groups):
        a, b, colors = groups[key]
        colors = sorted(colors)
        count = len(colors)
        if count == 1:
            result.append((a, b, colors[0]))
            continue
        for index, color in enumerate(colors):
            start = a if index == 0 else tuple(a[j] + (b[j] - a[j]) * index / float(count) for j in range(3))
            end = b if index == count - 1 else tuple(a[j] + (b[j] - a[j]) * (index + 1) / float(count) for j in range(3))
            result.append((start, end, color))
    return result
