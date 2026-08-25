# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 群組高度檢查 (JAC 06.03).

A model group instance carries two things that decide where it actually sits:
the level it belongs to (``GROUP_LEVEL``) and how far above that level it was
placed (``GROUP_OFFSET_FROM_LEVEL``). A 標準層 group copied up a tower is
supposed to sit the same way on every floor, so when one instance's offset
drifts the unit floats above its slab — and nothing in Revit complains.

The core check therefore compares instances **of the same group type** against
each other rather than against a number this module invents. The offset most
of them share is taken as the intended one.

Where there is no majority — two instances at 0 and two at 300 — no winner is
declared. Picking one arbitrarily would blame half the model for the other
half's mistake, so the type is reported as split and left for a human.

Lengths are millimetres.
"""


DEFAULT_TOLERANCE_MM = 1.0

FLAG_OFFSET_MISMATCH = u'偏移與同型群組多數不一致'
FLAG_OFFSET_SPLIT = u'同型群組偏移分歧，無多數可依據'
FLAG_OFFSET_NONZERO = u'偏移不為 0'
FLAG_ABOVE_NEXT_LEVEL = u'內容頂超出上層樓板'
FLAG_NO_LEVEL = u'沒有對應樓層'
FLAG_NO_GEOMETRY = u'讀不到內容範圍'

# Ordered worst-first, so a row carrying several flags still has one headline
# worth acting on.
FLAG_ORDER = (
    FLAG_NO_LEVEL,
    FLAG_OFFSET_MISMATCH,
    FLAG_OFFSET_SPLIT,
    FLAG_ABOVE_NEXT_LEVEL,
    FLAG_OFFSET_NONZERO,
    FLAG_NO_GEOMETRY,
)


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


def _snap(value, tolerance_mm):
    """Quantise so offsets differing only by float noise compare equal."""
    try:
        return int(round(float(value) / float(tolerance_mm)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


def expected_offsets(records, tolerance_mm=DEFAULT_TOLERANCE_MM):
    """``{type_id: (expected_mm, decided)}`` per group type.

    ``decided`` is False when no single offset holds a strict majority. That is
    the signal not to accuse anyone: the type is inconsistent, but nothing here
    can say which half is right.
    """
    buckets = {}
    for record in records or []:
        type_id = record.get('type_id')
        key = _snap(record.get('offset_mm'), tolerance_mm)
        entry = buckets.setdefault(type_id, {})
        slot = entry.setdefault(key, {'count': 0,
                                      'offset': _number(
                                          record.get('offset_mm'))})
        slot['count'] += 1

    results = {}
    for type_id in buckets:
        ordered = sorted(buckets[type_id].values(),
                         key=lambda item: -item['count'])
        top = ordered[0]
        decided = len(ordered) == 1 or top['count'] > ordered[1]['count']
        results[type_id] = (top['offset'], decided)
    return results


def _flags(record, expected, decided, flag_nonzero, tolerance_mm):
    flags = []
    if _number(record.get('level_id'), -1) <= 0:
        flags.append(FLAG_NO_LEVEL)

    offset = _number(record.get('offset_mm'))
    if expected is not None:
        if not decided:
            flags.append(FLAG_OFFSET_SPLIT)
        elif _snap(offset, tolerance_mm) != _snap(expected, tolerance_mm):
            flags.append(FLAG_OFFSET_MISMATCH)

    if flag_nonzero and abs(offset) > _number(tolerance_mm, 1.0):
        flags.append(FLAG_OFFSET_NONZERO)

    if record.get('top_mm') is None or record.get('bottom_mm') is None:
        flags.append(FLAG_NO_GEOMETRY)
    else:
        ceiling = record.get('next_level_elevation_mm')
        if ceiling is not None and _number(record.get('top_mm')) > \
                _number(ceiling) + _number(tolerance_mm, 1.0):
            flags.append(FLAG_ABOVE_NEXT_LEVEL)
    return flags


def analyze(records, flag_nonzero=False, tolerance_mm=DEFAULT_TOLERANCE_MM):
    """Classify every group instance and roll the results up by type."""
    expected = expected_offsets(records, tolerance_mm)

    rows = []
    for record in records or []:
        wanted, decided = expected.get(record.get('type_id'), (None, True))
        item = dict(record)
        item['expected_offset_mm'] = wanted
        item['offset_decided'] = decided
        item['flags'] = _flags(record, wanted, decided, flag_nonzero,
                               tolerance_mm)
        has_extent = (record.get('top_mm') is not None
                      and record.get('bottom_mm') is not None)
        item['relative_bottom_mm'] = (
            _number(record.get('bottom_mm'))
            - _number(record.get('level_elevation_mm'))
            if has_extent else None)
        item['relative_top_mm'] = (
            _number(record.get('top_mm'))
            - _number(record.get('level_elevation_mm'))
            if has_extent else None)
        item['content_height_mm'] = (
            _number(record.get('top_mm')) - _number(record.get('bottom_mm'))
            if has_extent else None)
        rows.append(item)

    rows.sort(key=lambda item: (_text(item.get('type_name')),
                                _number(item.get('level_elevation_mm')),
                                int(_number(item.get('id')))))

    types = []
    index = {}
    for item in rows:
        key = item.get('type_id')
        if key not in index:
            wanted, decided = expected.get(key, (None, True))
            index[key] = {'type_id': key,
                          'type_name': _text(item.get('type_name')),
                          'expected_offset_mm': wanted,
                          'decided': decided, 'items': []}
            types.append(index[key])
        index[key]['items'].append(item)
    for entry in types:
        entry['flagged'] = [item for item in entry['items'] if item['flags']]

    counts = {}
    for item in rows:
        for flag in item['flags']:
            counts[flag] = counts.get(flag, 0) + 1

    return {
        'tolerance_mm': _number(tolerance_mm, DEFAULT_TOLERANCE_MM),
        'flag_nonzero': bool(flag_nonzero),
        'total': len(rows),
        'rows': rows,
        'types': types,
        'counts': counts,
        'flagged_ids': [item['id'] for item in rows if item['flags']],
    }


def headline_flag(item):
    """The one flag worth showing when a row carries several."""
    present = item.get('flags') or []
    for flag in FLAG_ORDER:
        if flag in present:
            return flag
    return u''


def report_lines(report):
    lines = [
        u'模型群組共 {} 個實例，{} 種型別'.format(
            report['total'], len(report['types'])),
        u'偏移比對容差：{:.0f} mm'.format(report['tolerance_mm']),
    ]
    if report['flag_nonzero']:
        lines.append(u'（另檢查偏移是否為 0）')
    lines.append(u'')

    if not report['flagged_ids']:
        lines.append(u'✓ 沒有發現高度異常。')
        return u'\n'.join(lines)

    lines.append(u'✗ {} 個實例有問題：'.format(len(report['flagged_ids'])))
    for flag in FLAG_ORDER:
        count = report['counts'].get(flag)
        if count:
            lines.append(u'　{}：{} 個'.format(flag, count))

    lines.append(u'')
    for entry in report['types']:
        if not entry['flagged']:
            continue
        if entry['decided'] and entry['expected_offset_mm'] is not None:
            lines.append(u'{}（多數偏移 {:.0f} mm）'.format(
                entry['type_name'], entry['expected_offset_mm']))
        else:
            lines.append(u'{}（偏移分歧）'.format(entry['type_name']))
        for item in entry['flagged'][:8]:
            lines.append(u'　{}　偏移 {:.0f} mm　{}'.format(
                _text(item.get('level')) or u'(無樓層)',
                _number(item.get('offset_mm')), headline_flag(item)))
        if len(entry['flagged']) > 8:
            lines.append(u'　…（其餘 {} 個見輸出視窗）'.format(
                len(entry['flagged']) - 8))
    return u'\n'.join(lines)
