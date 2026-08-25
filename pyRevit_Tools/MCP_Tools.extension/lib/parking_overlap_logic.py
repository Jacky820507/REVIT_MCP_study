# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure geometry for 重疊車位檢核 (JAC 07.01).

Every length here is millimetres. The Revit side converts once on the way in,
so the tolerance a user types is the tolerance this module compares against.

Why oriented rectangles rather than bounding boxes: parking bays are routinely
placed at an angle, and an axis-aligned box around a rotated 2.5×5.5 m bay is
about 40% larger than the bay. Pairing those boxes reports neighbours that do
not actually touch, and a check that cries wolf gets switched off. Each bay is
therefore carried as a centre, its two axes, and its half extents, and pairs
are tested with the separating-axis theorem.

Two rules that keep the result meaningful:

- bays are only compared within the same level, because a B1 bay and the B2 bay
  beneath it overlap in plan by design;
- touching is not overlapping. Adjacent bays share an edge, so an overlap only
  counts once it exceeds a caller-supplied tolerance
  (see domain/user-specified-runtime-parameters.md — the default is a
  fallback, not a rule).
"""

import math


DEFAULT_TOLERANCE_MM = 50.0


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def make_rect(center, axis_x, axis_y, half):
    """Normalize an oriented rectangle so the projections below are metric.

    A non-unit axis silently scales every projection, which would turn the
    tolerance into an arbitrary number, so the axes are normalized here rather
    than trusted from the caller.
    """
    def unit(vector, fallback):
        length = math.sqrt(vector[0] * vector[0] + vector[1] * vector[1])
        if length <= 1e-9:
            return fallback
        return (vector[0] / length, vector[1] / length)

    return {
        'center': (float(center[0]), float(center[1])),
        'axis_x': unit(axis_x, (1.0, 0.0)),
        'axis_y': unit(axis_y, (0.0, 1.0)),
        'half': (abs(float(half[0])), abs(float(half[1]))),
    }


def rect_from_size(center, width, length, angle_rad=0.0):
    """Convenience builder used by the tests and by any caller with w/l/angle."""
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    return make_rect(center, (cos_a, sin_a), (-sin_a, cos_a),
                     (width / 2.0, length / 2.0))


def aabb(rect):
    """Axis-aligned bounds of an oriented rectangle — a cheap reject filter."""
    cx, cy = rect['center']
    hx, hy = rect['half']
    ax, ay = rect['axis_x'], rect['axis_y']
    extent_x = abs(ax[0]) * hx + abs(ay[0]) * hy
    extent_y = abs(ax[1]) * hx + abs(ay[1]) * hy
    return (cx - extent_x, cy - extent_y, cx + extent_x, cy + extent_y)


def _aabb_apart(first, second, tolerance):
    a = aabb(first)
    b = aabb(second)
    return (a[2] - b[0] <= tolerance or b[2] - a[0] <= tolerance
            or a[3] - b[1] <= tolerance or b[3] - a[1] <= tolerance)


def _span(rect, axis):
    center = _dot(rect['center'], axis)
    radius = (abs(_dot(rect['axis_x'], axis)) * rect['half'][0]
              + abs(_dot(rect['axis_y'], axis)) * rect['half'][1])
    return center - radius, center + radius


def overlap_depth(first, second):
    """How far two rectangles penetrate each other, in mm; 0 when separated.

    The separating-axis theorem on the four face normals: if any axis shows a
    gap the rectangles are apart, and otherwise the smallest of the four
    overlaps is how deep they actually sit inside one another. That number is
    what a reviewer can act on — 「插入 320 mm」 says more than a boolean.
    """
    depth = None
    for axis in (first['axis_x'], first['axis_y'],
                 second['axis_x'], second['axis_y']):
        first_min, first_max = _span(first, axis)
        second_min, second_max = _span(second, axis)
        gap = min(first_max, second_max) - max(first_min, second_min)
        if gap <= 0.0:
            return 0.0
        if depth is None or gap < depth:
            depth = gap
    return depth or 0.0


def find_pairs(bays, tolerance_mm=DEFAULT_TOLERANCE_MM):
    """Overlapping pairs, compared only within a level.

    ``bays`` are dicts carrying at least ``id``, ``level_id`` and ``rect``.
    """
    tolerance = float(tolerance_mm)
    by_level = {}
    order = []
    for bay in bays or []:
        # A bay whose geometry could not be read is reported as skipped, not
        # paired — comparing it would crash the run for every other bay too.
        if bay.get('rect') is None:
            continue
        key = bay.get('level_id')
        if key not in by_level:
            by_level[key] = []
            order.append(key)
        by_level[key].append(bay)

    pairs = []
    for key in order:
        group = by_level[key]
        for index, first in enumerate(group):
            for second in group[index + 1:]:
                if _aabb_apart(first['rect'], second['rect'], tolerance):
                    continue
                depth = overlap_depth(first['rect'], second['rect'])
                if depth <= tolerance:
                    continue
                pairs.append({'a': first, 'b': second, 'depth': depth})
    pairs.sort(key=lambda pair: -pair['depth'])
    return pairs


def cluster(pairs):
    """Connected components, so three stacked copies read as one problem.

    Reporting three pairs for one triple-placed bay makes the count look worse
    than the model is and gives no hint that they are the same spot.
    """
    parent = {}

    def find(key):
        while parent.get(key, key) != key:
            parent[key] = parent.get(parent[key], parent[key])
            key = parent[key]
        return key

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    bays = {}
    for pair in pairs:
        for side in ('a', 'b'):
            bay = pair[side]
            bays[bay['id']] = bay
            parent.setdefault(bay['id'], bay['id'])
        union(pair['a']['id'], pair['b']['id'])

    grouped = {}
    for pair in pairs:
        root = find(pair['a']['id'])
        entry = grouped.setdefault(root, {'members': {}, 'depth': 0.0,
                                          'pairs': 0})
        entry['members'][pair['a']['id']] = pair['a']
        entry['members'][pair['b']['id']] = pair['b']
        entry['pairs'] += 1
        if pair['depth'] > entry['depth']:
            entry['depth'] = pair['depth']

    clusters = []
    for entry in grouped.values():
        members = sorted(entry['members'].values(),
                         key=lambda bay: bay.get('id', 0))
        clusters.append({
            'members': members,
            'depth': entry['depth'],
            'pairs': entry['pairs'],
            'level': members[0].get('level') if members else u'',
        })
    clusters.sort(key=lambda item: (-item['depth'],
                                    item['members'][0].get('id', 0)))
    return clusters


def analyze(bays, tolerance_mm=DEFAULT_TOLERANCE_MM):
    pairs = find_pairs(bays, tolerance_mm)
    clusters = cluster(pairs)
    flagged = set()
    for group in clusters:
        for bay in group['members']:
            flagged.add(bay['id'])
    return {
        'tolerance_mm': float(tolerance_mm),
        'total': len(bays or []),
        'pairs': pairs,
        'clusters': clusters,
        'flagged_ids': [bay['id'] for bay in bays or []
                        if bay['id'] in flagged],
        'in_group': len([bay for bay in bays or [] if bay.get('in_group')]),
        'approx': len([bay for bay in bays or []
                       if bay.get('rect') is not None and bay.get('approx')]),
        'no_geometry': len([bay for bay in bays or []
                            if bay.get('rect') is None]),
    }


def bay_label(bay):
    parts = [_text(bay.get('mark')), _text(bay.get('type_name'))]
    label = u' '.join(part for part in parts if part)
    return label or u'ID {}'.format(bay.get('id'))


def report_lines(report):
    lines = [
        u'容許重疊：{:.0f} mm（小於此值視為相鄰、不報）'.format(
            report['tolerance_mm']),
        u'',
        u'掃描車位：{} 個'.format(report['total']),
    ]
    if report['no_geometry']:
        lines.append(u'無法取得幾何、已略過：{} 個'.format(
            report['no_geometry']))
    if report['approx']:
        # An axis-aligned fallback is wider than a rotated bay actually is, so
        # these can over-report. Saying so beats a silently inflated result.
        lines.append(u'僅取得外框、角度未計入：{} 個（可能誤報）'.format(
            report['approx']))
    if report['in_group']:
        # parking-space-review.md flags grouped bays as the usual performance
        # and double-counting trap, so the count is surfaced rather than hidden.
        lines.append(u'位於群組內：{} 個'.format(report['in_group']))
    lines.append(u'')
    if not report['clusters']:
        lines.append(u'✓ 沒有重疊車位。')
        return u'\n'.join(lines)
    lines.append(u'✗ 重疊 {} 處，涉及 {} 個車位：'.format(
        len(report['clusters']), len(report['flagged_ids'])))
    for group in report['clusters'][:20]:
        lines.append(u'　{}｜{} 個車位　最大重疊 {:.0f} mm　{}'.format(
            _text(group['level']), len(group['members']), group['depth'],
            u'、'.join(bay_label(bay) for bay in group['members'][:4])))
    if len(report['clusters']) > 20:
        lines.append(u'　…（其餘 {} 處見輸出視窗）'.format(
            len(report['clusters']) - 20))
    return u'\n'.join(lines)
