# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 複製面積到別的面積計畫 (JAC 01.06).

An ``Area`` cannot change scheme — ``Area.AreaScheme`` is read-only — so
"copying" means recreating: draw the same boundary lines in the target
scheme's plan, then place areas inside the regions those lines produce.

Order matters and is not negotiable. Areas placed before their boundaries
exist enclose nothing, so the caller creates lines first. That also means the
preview cannot predict the areas from geometry alone; the button gets its
numbers by doing the whole thing inside a Transaction that rolls back.

Running the copy twice must not double the model, so both halves are matched
against what the target already holds: boundary lines by sampled geometry,
areas by whether their seed falls inside an existing area.

Lengths are millimetres, points are plain ``(x, y)`` tuples.
"""

import math

import area_placement_logic as base
import duplicate_mark_logic as identity


# Two lines drawn by hand are never bit-identical, so geometry matching snaps
# to a grid. 1 mm is far below anything meaningful in a plan and far above
# floating-point noise from unit conversion.
DEFAULT_TOLERANCE_MM = 1.0

SKIP_LINE_EXISTS = u'目標計畫已有相同的邊界線'
SKIP_LINE_DUPLICATE = u'來源本身有重複的邊界線'
SKIP_AREA_COVERED = u'目標計畫的同一區域已有面積'

BLOCK_LINE_NO_GEOMETRY = u'讀不到邊界線幾何'
BLOCK_AREA_UNPLACED = u'來源面積未放置，沒有位置可複製'
BLOCK_NUMBER_COLLISION = u'編號與目標計畫既有面積重複'
BLOCK_NOT_ENCLOSED = u'複製邊界後仍未圍出面積'

SQ_FT_TO_SQ_M = 0.09290304


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _snap(value, tolerance):
    """Quantise to a tolerance grid so near-identical geometry compares equal."""
    try:
        return int(round(float(value) / float(tolerance)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


def _midpoint(points):
    """The point half way along the polyline, by length.

    Taking the middle *index* instead looks equivalent and is not: a straight
    line arrives as two points, so index ``len // 2`` is the end point, and an
    even-length tessellation picks a different vertex depending on which way
    the curve was walked. Either way the key stops being direction-symmetric
    and every straight boundary gets copied a second time on the next run.
    Distance along the curve does not care about direction.
    """
    lengths = []
    total = 0.0
    for index in range(len(points) - 1):
        first = points[index]
        second = points[index + 1]
        length = math.hypot(float(second[0]) - float(first[0]),
                            float(second[1]) - float(first[1]))
        lengths.append(length)
        total += length
    if total <= 0.0:
        return points[0]
    half = total / 2.0
    walked = 0.0
    for index, length in enumerate(lengths):
        if walked + length >= half and length > 0.0:
            ratio = (half - walked) / length
            first = points[index]
            second = points[index + 1]
            return (float(first[0]) + (float(second[0]) - float(first[0]))
                    * ratio,
                    float(first[1]) + (float(second[1]) - float(first[1]))
                    * ratio)
        walked += length
    return points[-1]


def curve_key(points, tolerance_mm=DEFAULT_TOLERANCE_MM):
    """A comparable identity for one boundary curve, or ``None``.

    Start, midpoint and end are sampled rather than just the endpoints: two
    arcs bulging opposite ways share both endpoints, and treating them as the
    same line would silently drop one of them from the copy.

    The key is canonicalised against direction, because a line drawn A→B and
    the same line drawn B→A are the same boundary and must not both be copied.
    """
    points = [point for point in points or []]
    if len(points) < 2:
        return None
    sample = (points[0], _midpoint(points), points[-1])
    snapped = tuple((_snap(point[0], tolerance_mm), _snap(point[1],
                                                          tolerance_mm))
                    for point in sample)
    return min(snapped, tuple(reversed(snapped)))


def plan_lines_to_copy(source_lines, target_lines,
                       tolerance_mm=DEFAULT_TOLERANCE_MM):
    """Split the source boundary lines into copy / skip / blocked."""
    existing = set()
    for line in target_lines or []:
        key = line.get('key') or curve_key(line.get('points'), tolerance_mm)
        if key is not None:
            existing.add(key)

    writes = []
    skipped = []
    blocked = []
    seen = set()
    for line in source_lines or []:
        key = line.get('key') or curve_key(line.get('points'), tolerance_mm)
        if key is None:
            blocked.append({'record': line, 'reason': BLOCK_LINE_NO_GEOMETRY})
            continue
        if key in existing:
            skipped.append({'record': line, 'reason': SKIP_LINE_EXISTS})
            continue
        if key in seen:
            skipped.append({'record': line, 'reason': SKIP_LINE_DUPLICATE})
            continue
        seen.add(key)
        row = dict(line)
        row['key'] = key
        writes.append(row)
    return {'writes': writes, 'skipped': skipped, 'blocked': blocked}


def plan_areas_to_copy(source_areas, target_areas):
    """Split the source areas into copy / skip / blocked.

    Coverage is judged against the target's existing area boundaries, which is
    what makes a second run place nothing instead of stacking duplicates on top
    of the first run's work.
    """
    existing_numbers = set()
    for area in target_areas or []:
        key = identity.normalize_mark(area.get('number'))
        if key:
            existing_numbers.add(key)

    writes = []
    skipped = []
    blocked = []
    claimed = set()
    for area in sorted(source_areas or [], key=base.sort_key):
        point = area.get('point_xy')
        if not area.get('placed') or point is None:
            blocked.append({'record': area, 'reason': BLOCK_AREA_UNPLACED})
            continue
        covered = False
        for target in target_areas or []:
            if base.point_in_loops(point, target.get('loops')):
                covered = True
                break
        if covered:
            skipped.append({'record': area, 'reason': SKIP_AREA_COVERED})
            continue
        number = identity.normalize_mark(area.get('number'))
        if number and (number in existing_numbers or number in claimed):
            blocked.append({'record': area, 'reason': BLOCK_NUMBER_COLLISION})
            continue
        if number:
            claimed.add(number)
        row = dict(area)
        # The placement layer keys its rows on 'id' and reads 'number'/'name';
        # reusing that shape lets the same trial and commit code drive this.
        row['target_number'] = _text(area.get('number'))
        row['target_name'] = _text(area.get('name'))
        writes.append(row)
    return {'writes': writes, 'skipped': skipped, 'blocked': blocked}


def build_plan(source_lines, target_lines, source_areas, target_areas,
               copy_lines=True, copy_areas=True,
               tolerance_mm=DEFAULT_TOLERANCE_MM):
    lines = (plan_lines_to_copy(source_lines, target_lines, tolerance_mm)
             if copy_lines
             else {'writes': [], 'skipped': [], 'blocked': []})
    areas = (plan_areas_to_copy(source_areas, target_areas) if copy_areas
             else {'writes': [], 'skipped': [], 'blocked': []})
    return {
        'copy_lines': copy_lines,
        'copy_areas': copy_areas,
        'tolerance_mm': float(tolerance_mm),
        'source_line_count': len(source_lines or []),
        'source_area_count': len(source_areas or []),
        'lines': lines,
        'areas': areas,
        'trialled': False,
    }


def apply_trial_result(plan, trial_rows):
    """Fold in what Revit reported after the lines were actually drawn.

    Areas are the only half that can fail this way: a boundary set can be
    copied faithfully and still leave a region open, and only Revit can say so.
    """
    results = dict(trial_rows or {})
    writes = []
    blocked = list(plan['areas']['blocked'])
    for row in plan['areas']['writes']:
        result = results.get(row.get('id'))
        if result is None or not result.get('enclosed'):
            blocked.append({'record': row, 'reason': BLOCK_NOT_ENCLOSED})
            continue
        item = dict(row)
        item['area_sqft'] = result.get('area_sqft') or 0.0
        writes.append(item)

    updated = dict(plan)
    updated['areas'] = {'writes': writes,
                        'skipped': plan['areas']['skipped'],
                        'blocked': blocked}
    updated['trialled'] = True
    return updated


def _reason_counts(rows):
    counts = {}
    for row in rows or []:
        counts[row['reason']] = counts.get(row['reason'], 0) + 1
    return counts


def plan_summary(plan, source_label, target_label):
    lines = [
        u'來源：{}'.format(_text(source_label)),
        u'目標：{}'.format(_text(target_label)),
        u'',
    ]
    if plan['copy_lines']:
        group = plan['lines']
        lines.append(u'邊界線：來源 {} 條，將複製 {} 條'.format(
            plan['source_line_count'], len(group['writes'])))
        for reason, count in sorted(_reason_counts(
                group['skipped'] + group['blocked']).items()):
            lines.append(u'　{}：{} 條'.format(reason, count))
    else:
        lines.append(u'邊界線：不複製')
    lines.append(u'')
    if plan['copy_areas']:
        group = plan['areas']
        verb = u'將建立' if plan['trialled'] else u'預計建立'
        lines.append(u'面積：來源 {} 個，{} {} 個'.format(
            plan['source_area_count'], verb, len(group['writes'])))
        for row in group['writes'][:15]:
            label = u'　{}'.format(
                _text(row.get('target_number')) or u'(自動編號)')
            name = _text(row.get('target_name'))
            if name:
                label += u'　{}'.format(name)
            if row.get('area_sqft'):
                label += u'　{:.2f} m²'.format(
                    float(row['area_sqft']) * SQ_FT_TO_SQ_M)
            lines.append(label)
        if len(group['writes']) > 15:
            lines.append(u'　…（其餘 {} 個見輸出視窗）'.format(
                len(group['writes']) - 15))
        for reason, count in sorted(_reason_counts(
                group['skipped'] + group['blocked']).items()):
            lines.append(u'　{}：{} 個'.format(reason, count))
    else:
        lines.append(u'面積：不複製')

    if plan['copy_areas'] and not plan['copy_lines']:
        lines.append(u'')
        lines.append(
            u'※ 沒有複製邊界線。目標計畫若沒有對應的封閉區域，'
            u'面積會圍不出來而被擋下。')
    return u'\n'.join(lines)


def has_work(plan):
    return bool(plan['lines']['writes']) or bool(plan['areas']['writes'])
