# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 面積列式 — the calculation expression (JAC 01.04).

Taiwanese permit review does not accept a bare total: the 面積計算表 has to show
*how* each area was derived, one simple shape at a time —

    A1 居室
    (H1) = 2.80 x 4.50 = 12.60 m²
    (H2) = 10.50 x 2.30 = 24.15 m²
    (H1) + (H2) = 36.75 m²

so this module turns each sub-area's boundary into that expression, groups the
results by 戶別 and 分類, and numbers them.

The rule that makes the output trustworthy: **an expression is only emitted if
its own arithmetic reproduces the polygon's real area.** Shape recognition on
hand-drawn boundaries is never certain, and a confidently wrong ``2.80 x 4.50``
is far worse than an honest 「無法列式」 — the first passes review and the
second gets fixed. Anything that fails the check is reported with its area and
no formula.

Input loops are millimetres; expressions are metres to two decimals, because
that is the unit the 計算表 is written in.
"""

import math

import area_placement_logic as base


MM_PER_M = 1000.0

# How far a hand-drawn boundary may stray and still count as the ideal shape.
ANGLE_TOLERANCE_DEG = 2.0
# The expression must reproduce the polygon area to within this fraction.
AREA_TOLERANCE = 0.005
# Vertices closer than this, or bulges shallower than this, are noise.
POINT_TOLERANCE_MM = 1.0

KIND_RECTANGLE = 'rectangle'
KIND_TRIANGLE = 'triangle'
KIND_TRAPEZOID = 'trapezoid'
KIND_UNKNOWN = 'unknown'

KIND_LABELS = {
    KIND_RECTANGLE: u'矩形',
    KIND_TRIANGLE: u'三角形',
    KIND_TRAPEZOID: u'梯形',
    KIND_UNKNOWN: u'無法列式',
}

NO_FORMULA = u'無法列式'

# Default 分類 -> code letter. Project-specific names are common, so the caller
# can override; anything unmapped still gets a stable letter rather than being
# dropped from the schedule.
DEFAULT_LETTERS = (
    (u'居室', u'H'),
    (u'陽台', u'B'),
    (u'陽臺', u'B'),
    (u'樓梯間', u'S'),
    (u'梯廳', u'L'),
    (u'機電設備', u'E'),
    (u'室內', u'H'),
)
FALLBACK_LETTERS = u'XYZWVUTRQPNMKJGFDCA'


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _fmt(value):
    """Two decimals, matching how the 計算表 is written."""
    return u'{:.2f}'.format(round(float(value) + 0.0, 2))


def _distance(first, second):
    return math.hypot(float(second[0]) - float(first[0]),
                      float(second[1]) - float(first[1]))


# --- loop normalisation ----------------------------------------------------

def normalize_loop(points, tolerance_mm=POINT_TOLERANCE_MM):
    """Drop duplicate and collinear vertices so a shape can be recognised.

    Revit hands back one vertex per boundary segment, and a wall split into two
    segments puts a redundant point in the middle of a straight edge. Left in,
    a plain rectangle arrives as five vertices and is classified as an
    unrecognised polygon.
    """
    cleaned = []
    for point in points or []:
        candidate = (float(point[0]), float(point[1]))
        if cleaned and _distance(cleaned[-1], candidate) <= tolerance_mm:
            continue
        cleaned.append(candidate)
    while len(cleaned) > 1 and _distance(cleaned[0], cleaned[-1]) <= \
            tolerance_mm:
        cleaned.pop()
    if len(cleaned) < 3:
        return []

    result = []
    count = len(cleaned)
    for index in range(count):
        previous = cleaned[index - 1]
        current = cleaned[index]
        following = cleaned[(index + 1) % count]
        ax = current[0] - previous[0]
        ay = current[1] - previous[1]
        bx = following[0] - current[0]
        by = following[1] - current[1]
        # Cross product against the segment lengths: a vertex that bends by
        # less than the tolerance over its own span is not a corner.
        cross = abs(ax * by - ay * bx)
        span = max(math.hypot(ax, ay), math.hypot(bx, by))
        if span > 0 and cross / span <= tolerance_mm:
            continue
        result.append(current)
    return result if len(result) >= 3 else []


def _angles(loop):
    angles = []
    count = len(loop)
    for index in range(count):
        previous = loop[index - 1]
        current = loop[index]
        following = loop[(index + 1) % count]
        ax = previous[0] - current[0]
        ay = previous[1] - current[1]
        bx = following[0] - current[0]
        by = following[1] - current[1]
        na = math.hypot(ax, ay)
        nb = math.hypot(bx, by)
        if na <= 0 or nb <= 0:
            angles.append(0.0)
            continue
        cosine = max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb)))
        angles.append(math.degrees(math.acos(cosine)))
    return angles


def _side_lengths(loop):
    return [_distance(loop[index], loop[(index + 1) % len(loop)])
            for index in range(len(loop))]


def _is_parallel(loop, first, second, tolerance_deg):
    """Whether two sides of the loop run parallel, ignoring direction."""
    def direction(index):
        start = loop[index]
        end = loop[(index + 1) % len(loop)]
        return (end[0] - start[0], end[1] - start[1])

    ax, ay = direction(first)
    bx, by = direction(second)
    na = math.hypot(ax, ay)
    nb = math.hypot(bx, by)
    if na <= 0 or nb <= 0:
        return False
    cosine = abs(ax * bx + ay * by) / (na * nb)
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(cosine)) <= tolerance_deg


# --- shape recognition -----------------------------------------------------

def classify(points, expected_m2=None,
             angle_tolerance_deg=ANGLE_TOLERANCE_DEG,
             area_tolerance=AREA_TOLERANCE,
             point_tolerance_mm=POINT_TOLERANCE_MM):
    """``{kind, expression, value_m2, actual_m2, vertices, reason}``.

    ``expected_m2`` is Revit's own area for the region. When given it is used
    both as the reported area and as the yardstick for the self-check, because
    it is the number the schedule and the reviewer will see — an expression
    that agrees with my polygon maths but not with Revit's area is still wrong.

    ``expression`` is empty whenever the shape could not be written as one of
    the simple forms, or when the arithmetic disagreed with that area.
    """
    loop = normalize_loop(points, point_tolerance_mm)
    if expected_m2 is not None:
        actual_m2 = abs(float(expected_m2))
    else:
        actual_mm2 = abs(base.polygon_area(loop)) if loop else 0.0
        actual_m2 = actual_mm2 / (MM_PER_M * MM_PER_M)

    result = {
        'kind': KIND_UNKNOWN,
        'expression': u'',
        'value_m2': 0.0,
        'actual_m2': round(actual_m2, 4),
        'vertices': len(loop),
        'reason': u'',
    }
    if not loop:
        result['reason'] = u'讀不到有效邊界'
        return result

    sides = [length / MM_PER_M for length in _side_lengths(loop)]

    if len(loop) == 3:
        angles = _angles(loop)
        right = None
        for index, angle in enumerate(angles):
            if abs(angle - 90.0) <= angle_tolerance_deg:
                right = index
                break
        if right is not None:
            # A right triangle is written on its two legs — that is how anyone
            # checking the 計算表 would measure it. The hypotenuse can be the
            # longest side, so "longest" would pick the one nobody writes.
            legs = sorted([sides[right - 1], sides[right]])
            first, second = legs[0], legs[1]
        else:
            # Otherwise the longest side is the base: a sliver measured off its
            # shortest side produces a meaningless height.
            first = max(sides)
            second = (2.0 * actual_m2 / first) if first > 0 else 0.0
        expression = u'{} x {} / 2'.format(_fmt(first), _fmt(second))
        value = float(_fmt(first)) * float(_fmt(second)) / 2.0
        result.update({'kind': KIND_TRIANGLE, 'expression': expression,
                       'value_m2': value})
    elif len(loop) == 4:
        angles = _angles(loop)
        if all(abs(angle - 90.0) <= angle_tolerance_deg for angle in angles):
            width = (sides[0] + sides[2]) / 2.0
            depth = (sides[1] + sides[3]) / 2.0
            expression = u'{} x {}'.format(_fmt(width), _fmt(depth))
            value = float(_fmt(width)) * float(_fmt(depth))
            result.update({'kind': KIND_RECTANGLE, 'expression': expression,
                           'value_m2': value})
        else:
            pairs = []
            if _is_parallel(loop, 0, 2, angle_tolerance_deg):
                pairs.append((0, 2, 1, 3))
            if _is_parallel(loop, 1, 3, angle_tolerance_deg):
                pairs.append((1, 3, 0, 2))
            if pairs:
                first, second, unused_a, unused_b = pairs[0]
                # Shorter parallel side first, so the expression does not
                # depend on which corner the boundary loop happened to start.
                top, bottom = sorted([sides[first], sides[second]])
                total = top + bottom
                height = (2.0 * actual_m2 / total) if total > 0 else 0.0
                expression = u'({} + {}) x {} / 2'.format(
                    _fmt(top), _fmt(bottom), _fmt(height))
                value = ((float(_fmt(top)) + float(_fmt(bottom)))
                         * float(_fmt(height)) / 2.0)
                result.update({'kind': KIND_TRAPEZOID,
                               'expression': expression, 'value_m2': value})
            else:
                result['reason'] = u'四邊形但沒有平行邊'
    else:
        result['reason'] = u'{} 邊形'.format(len(loop))

    if not result['expression']:
        if not result['reason']:
            result['reason'] = NO_FORMULA
        return result

    # The self-check. Recognition can be fooled; arithmetic cannot.
    if actual_m2 <= 0:
        result.update({'kind': KIND_UNKNOWN, 'expression': u'',
                       'value_m2': 0.0, 'reason': u'面積為 0'})
        return result
    drift = abs(result['value_m2'] - actual_m2) / actual_m2
    if drift > area_tolerance:
        result.update({
            'kind': KIND_UNKNOWN, 'expression': u'', 'value_m2': 0.0,
            'reason': u'算式與實際面積不符（差 {:.1%}）'.format(drift)})
    else:
        result['value_m2'] = round(result['value_m2'], 2)
    return result


# --- codes and grouping ----------------------------------------------------

def classify_loops(loops, expected_m2=None, **options):
    """Classify a region that may arrive as several boundary loops.

    More than one loop means a hole or a detached island, and neither is a
    simple shape — no ``a x b`` describes it. The area is still reported so the
    row survives into the schedule with an honest note.
    """
    usable = [loop for loop in loops or [] if loop]
    if not usable:
        return classify([], expected_m2, **options)
    if len(usable) == 1:
        return classify(usable[0], expected_m2, **options)
    outer = max(usable, key=lambda loop: abs(base.polygon_area(loop)))
    result = classify(outer, expected_m2, **options)
    result.update({'kind': KIND_UNKNOWN, 'expression': u'', 'value_m2': 0.0,
                   'reason': u'邊界有 {} 個迴圈（含內孔或分離區塊）'.format(
                       len(usable))})
    return result


def build_letter_map(categories, overrides=None):
    """``{分類: 字母}`` — known names keep their conventional letter.

    An unmapped 分類 still gets a letter rather than being dropped, because a
    category missing from the schedule is a silent hole in the total.
    """
    letters = {}
    used = set()
    defaults = dict(DEFAULT_LETTERS)
    for name in sorted(set(_text(item) for item in categories or []) - set([u''])):
        letter = (overrides or {}).get(name) or defaults.get(name)
        if letter and letter not in used:
            letters[name] = letter
            used.add(letter)
    for name in sorted(set(_text(item) for item in categories or []) - set([u''])):
        if name in letters:
            continue
        for candidate in FALLBACK_LETTERS:
            if candidate not in used:
                letters[name] = candidate
                used.add(candidate)
                break
        else:
            letters[name] = u'?'
    return letters


def _sort_key(record):
    return (_text(record.get('unit')),
            _text(record.get('category')),
            base.sort_key(record))


def build_report(records, letter_overrides=None, **classify_options):
    """Classify, number and group every sub-area.

    Numbering runs continuously per 分類 across 戶別 — A1's 居室 taking H1–H3
    and A2's taking H4–H6 — which is how the printed 計算表 reads.
    """
    rows = sorted(records or [], key=_sort_key)
    letters = build_letter_map(
        [row.get('category') for row in rows], letter_overrides)

    counters = {}
    prepared = []
    for record in rows:
        category = _text(record.get('category'))
        if record.get('loops') is not None:
            shape = classify_loops(record.get('loops'),
                                   record.get('area_m2'), **classify_options)
        else:
            shape = classify(record.get('loop') or record.get('points'),
                             record.get('area_m2'), **classify_options)
        letter = letters.get(category, u'?')
        counters[letter] = counters.get(letter, 0) + 1
        item = dict(record)
        item.update(shape)
        item['category'] = category
        item['unit'] = _text(record.get('unit'))
        item['code'] = u'{}{}'.format(letter, counters[letter])
        prepared.append(item)

    groups = []
    index = {}
    for item in prepared:
        key = (item['unit'], item['category'])
        if key not in index:
            index[key] = {'unit': item['unit'], 'category': item['category'],
                          'items': []}
            groups.append(index[key])
        index[key]['items'].append(item)

    for group in groups:
        usable = [item for item in group['items'] if item['expression']]
        group['total_m2'] = round(
            sum(item['actual_m2'] for item in group['items']), 2)
        group['formula_total_m2'] = round(
            sum(item['value_m2'] for item in usable), 2)
        group['sum_expression'] = (
            u' + '.join(u'({})'.format(item['code']) for item in usable)
            if len(usable) > 1 else u'')

    return {
        'letters': letters,
        'groups': groups,
        'items': prepared,
        'total': len(prepared),
        'unformulated': [item for item in prepared if not item['expression']],
    }


def group_lines(group):
    """The printed block for one 戶別 × 分類."""
    lines = [u'{} {}'.format(group['unit'] or u'(未指定戶別)',
                             group['category'] or u'(未分類)')]
    for item in group['items']:
        if item['expression']:
            lines.append(u'({}) = {} = {} m²'.format(
                item['code'], item['expression'], _fmt(item['value_m2'])))
        else:
            lines.append(u'({}) = {} = {} m²　← {}'.format(
                item['code'], NO_FORMULA, _fmt(item['actual_m2']),
                item['reason'] or NO_FORMULA))
    if group['sum_expression']:
        lines.append(u'{} = {} m²'.format(
            group['sum_expression'], _fmt(group['formula_total_m2'])))
    return lines


def report_text(report):
    blocks = []
    for group in report['groups']:
        blocks.append(u'\n'.join(group_lines(group)))
    return u'\n\n'.join(blocks)


def report_summary(report):
    lines = [
        u'子區域共 {} 個'.format(report['total']),
        u'分組（戶別 × 分類）：{} 組'.format(len(report['groups'])),
    ]
    unformulated = report['unformulated']
    if unformulated:
        lines.append(u'')
        lines.append(u'✗ 無法列式 {} 個，只列面積：'.format(len(unformulated)))
        reasons = {}
        for item in unformulated:
            reasons[item['reason']] = reasons.get(item['reason'], 0) + 1
        for reason in sorted(reasons, key=lambda key: -reasons[key]):
            lines.append(u'　{}：{} 個'.format(reason, reasons[reason]))
    else:
        lines.append(u'')
        lines.append(u'✓ 全部都能列式。')
    return u'\n'.join(lines)


def export_rows(report):
    """Flat rows for the Excel sheet, one per sub-area."""
    rows = [[u'戶別', u'分類', u'代號', u'形狀', u'計算式',
             u'算式面積(m²)', u'實際面積(m²)', u'備註']]
    for group in report['groups']:
        for item in group['items']:
            rows.append([
                item['unit'], item['category'], item['code'],
                KIND_LABELS.get(item['kind'], item['kind']),
                item['expression'] or NO_FORMULA,
                item['value_m2'] if item['expression'] else 0.0,
                item['actual_m2'],
                item['reason'],
            ])
        if group['sum_expression']:
            rows.append([group['unit'], group['category'], u'小計', u'',
                         group['sum_expression'],
                         group['formula_total_m2'], group['total_m2'], u''])
    return rows
