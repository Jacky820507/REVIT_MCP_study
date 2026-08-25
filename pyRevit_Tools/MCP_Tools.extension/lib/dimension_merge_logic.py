# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 尺寸線合併 (JAC 08.04).

Revit has no "merge dimensions" command. Combining two dimension strings means
rebuilding: take the union of their references, create one new dimension along
the shared line, and delete the originals. That is destructive, so most of this
module is about deciding when it is *not* safe to do.

The rule that matters most: **a dimension carrying a text override is never
merged.** ``ValueOverride``, ``Prefix``, ``Suffix``, ``Above`` and ``Below``
(on the dimension or any of its segments) are deliberate annotations someone
typed, and rebuilding silently discards them — the drawing then looks perfectly
normal while the note is gone. Those are reported and left alone.

Two dimensions also have to genuinely share a line. Collinearity is tested by
direction *and* by perpendicular offset, because two parallel strings 300 mm
apart are two separate dimension runs, not one.

Lengths are millimetres; points are ``(x, y, z)`` tuples.
"""

import math


DEFAULT_ANGLE_TOLERANCE_DEG = 1.0
DEFAULT_OFFSET_TOLERANCE_MM = 5.0
# Two collinear runs far apart along the same line are still two runs; merging
# them would dimension the empty space between them as one enormous segment.
DEFAULT_MAX_GAP_MM = 3000.0

SHAPE_LINEAR = 'Linear'

BLOCK_NOT_LINEAR = u'不是線性標註（半徑／角度／弧長無法合併）'
BLOCK_NO_REFERENCES = u'讀不到參考（AreReferencesAvailable 為否）'
BLOCK_HAS_OVERRIDE = u'有人工覆寫的文字，合併會遺失'
BLOCK_NO_GEOMETRY = u'讀不到標註線'
BLOCK_LOCKED = u'標註已鎖定'

SKIP_ALONE = u'同一條線上沒有其他可合併的標註'

OVERRIDE_FIELDS = ('value_override', 'prefix', 'suffix', 'above', 'below')


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _number(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _sub(a, b):
    return (_number(a[0]) - _number(b[0]),
            _number(a[1]) - _number(b[1]),
            _number(a[2]) - _number(b[2]))


def _dot(a, b):
    return (_number(a[0]) * _number(b[0]) + _number(a[1]) * _number(b[1])
            + _number(a[2]) * _number(b[2]))


def _norm(v):
    return math.sqrt(_dot(v, v))


def unit(v):
    length = _norm(v)
    if length <= 0:
        return (0.0, 0.0, 0.0)
    return (_number(v[0]) / length, _number(v[1]) / length,
            _number(v[2]) / length)


def direction_of(record):
    """Unit direction of a dimension line, from its two endpoints."""
    start = record.get('start')
    end = record.get('end')
    if not start or not end:
        return None
    d = unit(_sub(end, start))
    return d if _norm(d) > 0 else None


def perpendicular_distance(point, origin, direction):
    """Distance from a point to the infinite line through origin."""
    v = _sub(point, origin)
    along = _dot(v, direction)
    projected = (origin[0] + direction[0] * along,
                 origin[1] + direction[1] * along,
                 origin[2] + direction[2] * along)
    return _norm(_sub(point, projected))


def are_collinear(first, second, angle_tolerance_deg=None,
                  offset_tolerance_mm=None):
    """Whether two dimension lines lie on the same infinite line.

    Direction alone is not enough: two parallel strings offset from each other
    are two separate runs, and merging them would drag one onto the other's
    line.
    """
    angle_tolerance_deg = (DEFAULT_ANGLE_TOLERANCE_DEG
                           if angle_tolerance_deg is None
                           else angle_tolerance_deg)
    offset_tolerance_mm = (DEFAULT_OFFSET_TOLERANCE_MM
                           if offset_tolerance_mm is None
                           else offset_tolerance_mm)
    a = direction_of(first)
    b = direction_of(second)
    if a is None or b is None:
        return False
    cosine = min(1.0, max(-1.0, abs(_dot(a, b))))
    if math.degrees(math.acos(cosine)) > angle_tolerance_deg:
        return False
    for point in (second.get('start'), second.get('end')):
        if point is None:
            return False
        if perpendicular_distance(point, first['start'], a) > \
                offset_tolerance_mm:
            return False
    return True


def has_override(record):
    """Whether anything a person typed would be lost by rebuilding."""
    for field in OVERRIDE_FIELDS:
        if _text(record.get(field)):
            return True
    for segment in record.get('segments') or []:
        for field in OVERRIDE_FIELDS:
            if _text(segment.get(field)):
                return True
    return False


def block_reason(record):
    """Why this dimension cannot take part in a merge, or ``''``."""
    if _text(record.get('shape')) != SHAPE_LINEAR:
        return BLOCK_NOT_LINEAR
    if not record.get('references_available'):
        return BLOCK_NO_REFERENCES
    if direction_of(record) is None:
        return BLOCK_NO_GEOMETRY
    if record.get('is_locked'):
        return BLOCK_LOCKED
    if has_override(record):
        return BLOCK_HAS_OVERRIDE
    return u''


def _span(record, origin, direction):
    """``(t_min, t_max)`` of a dimension along the shared direction."""
    values = [_dot(_sub(point, origin), direction)
              for point in (record['start'], record['end'])]
    return min(values), max(values)


def build_runs(records, angle_tolerance_deg=None, offset_tolerance_mm=None,
               max_gap_mm=None):
    """Cluster dimensions into mergeable runs.

    A run is a set of dimensions on one line, of one type, in one view, whose
    spans are close enough along that line to read as a single string.
    """
    max_gap_mm = DEFAULT_MAX_GAP_MM if max_gap_mm is None else max_gap_mm

    blocked = []
    usable = []
    for record in records or []:
        reason = block_reason(record)
        if reason:
            blocked.append({'record': record, 'reason': reason})
        else:
            usable.append(record)

    lines = []
    for record in usable:
        placed = False
        for line in lines:
            head = line['records'][0]
            if head.get('view_id') != record.get('view_id'):
                continue
            # Different dimension types format differently; merging them would
            # silently restyle one of the two.
            if head.get('type_id') != record.get('type_id'):
                continue
            if are_collinear(head, record, angle_tolerance_deg,
                             offset_tolerance_mm):
                line['records'].append(record)
                placed = True
                break
        if not placed:
            lines.append({'records': [record]})

    runs = []
    singles = []
    for line in lines:
        head = line['records'][0]
        origin = head['start']
        direction = direction_of(head)
        spans = []
        for record in line['records']:
            low, high = _span(record, origin, direction)
            spans.append({'record': record, 'min': low, 'max': high})
        spans.sort(key=lambda item: item['min'])

        current = [spans[0]]
        chunks = [current]
        # Track how far the current chunk reaches, not where the last item
        # happened to end: a short dimension sitting inside a long one ends
        # early, and comparing against that would split the run at the next
        # item even though the long one still covers the ground.
        reach = spans[0]['max']
        for item in spans[1:]:
            if item['min'] - reach > max_gap_mm:
                current = [item]
                chunks.append(current)
                reach = item['max']
            else:
                current.append(item)
                if item['max'] > reach:
                    reach = item['max']

        for chunk in chunks:
            members = [item['record'] for item in chunk]
            if len(members) < 2:
                singles.append({'record': members[0], 'reason': SKIP_ALONE})
                continue
            low = min(item['min'] for item in chunk)
            high = max(item['max'] for item in chunk)
            runs.append({
                'members': members,
                'origin': origin,
                'direction': direction,
                'start': (origin[0] + direction[0] * low,
                          origin[1] + direction[1] * low,
                          origin[2] + direction[2] * low),
                'end': (origin[0] + direction[0] * high,
                        origin[1] + direction[1] * high,
                        origin[2] + direction[2] * high),
                'length_mm': high - low,
                'view_id': members[0].get('view_id'),
                'type_id': members[0].get('type_id'),
                'type_name': _text(members[0].get('type_name')),
            })

    for run in runs:
        seen = []
        for record in run['members']:
            for key in record.get('reference_keys') or []:
                if key not in seen:
                    seen.append(key)
        run['reference_keys'] = seen
        run['reference_count'] = len(seen)
        run['dropped_duplicates'] = sum(
            len(record.get('reference_keys') or [])
            for record in run['members']) - len(seen)

    runs.sort(key=lambda run: -len(run['members']))
    return {'runs': runs, 'blocked': blocked, 'singles': singles,
            'total': len(records or []),
            'max_gap_mm': _number(max_gap_mm, DEFAULT_MAX_GAP_MM)}


def merged_count(plan):
    return sum(len(run['members']) for run in plan['runs'])


def has_work(plan):
    return bool(plan['runs'])


def _reason_counts(rows):
    counts = {}
    for row in rows or []:
        counts[row['reason']] = counts.get(row['reason'], 0) + 1
    return counts


def plan_lines(plan):
    lines = [
        u'掃描標註 {} 個'.format(plan['total']),
        u'最大合併間距：{:.0f} mm'.format(plan['max_gap_mm']),
        u'',
    ]
    if not plan['runs']:
        lines.append(u'沒有可以合併的標註。')
    else:
        lines.append(u'將把 {} 個標註合併成 {} 條：'.format(
            merged_count(plan), len(plan['runs'])))
        for run in plan['runs'][:15]:
            lines.append(u'　{} 個 → 1 條　長度 {:.0f} mm　參考 {} 個{}'.format(
                len(run['members']), run['length_mm'], run['reference_count'],
                u'（去除重複 {} 個）'.format(run['dropped_duplicates'])
                if run['dropped_duplicates'] else u''))
        if len(plan['runs']) > 15:
            lines.append(u'　…（其餘 {} 條見輸出視窗）'.format(
                len(plan['runs']) - 15))

    if plan['blocked']:
        lines.append(u'')
        lines.append(u'✗ 不合併 {} 個：'.format(len(plan['blocked'])))
        counts = _reason_counts(plan['blocked'])
        for reason in sorted(counts, key=lambda key: -counts[key]):
            lines.append(u'　{}：{} 個'.format(reason, counts[reason]))
    if plan['singles']:
        lines.append(u'')
        lines.append(u'　{}：{} 個'.format(SKIP_ALONE, len(plan['singles'])))
    return u'\n'.join(lines)
