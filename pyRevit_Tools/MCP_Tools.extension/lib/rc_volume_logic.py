# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for the RC wall volume takeoff (RcVolumeExcel button).

Everything here is Revit-free so it can be unit-tested under CPython: the
RC type filter, grid location marks, opening grouping and the sort keys the
report rows are ordered by.
"""

import math
import re
import unicodedata


DEFAULT_KEYWORDS = (u'RC', u'混凝土', u'CONCRETE')
NO_OPENING_LABEL = u'無開口'
UNASSIGNED_ROOM_LABEL = u'（未分配到房間的 RC 牆）'
# A grid offset smaller than this reads as "on the grid" and is not printed.
GRID_ON_LINE_TOLERANCE_M = 0.05


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _fold(value):
    return unicodedata.normalize('NFKC', _text(value)).upper()


def parse_keywords(text):
    """Split a user-entered keyword list on comma / space / slash.

    The filter is a runtime parameter, not a hardcoded rule: a project that
    names its concrete walls something else has to be able to say so without
    editing this file.
    """
    parts = re.split(u'[,，/、|\\s]+', _text(text))
    return [part for part in parts if part]


def _is_ascii_word(value):
    return bool(re.match(r'^[A-Z0-9]+$', value))


def matches_keywords(type_name, keywords):
    """Whether a wall type name is in scope for this takeoff.

    ``RC`` has to respect latin word boundaries — as a bare substring it also
    fires inside ARCH, PORCH and SRC, which would pull non-RC walls into a
    concrete volume. CJK keywords keep plain substring matching because
    Chinese type names have no separators to anchor on.
    """
    haystack = _fold(type_name)
    if not haystack:
        return False
    for keyword in keywords or ():
        needle = _fold(keyword)
        if not needle:
            continue
        if _is_ascii_word(needle):
            if re.search(r'(?<![A-Z0-9])' + re.escape(needle) + r'(?![A-Z0-9])',
                         haystack):
                return True
        elif needle in haystack:
            return True
    return False


def format_number(value, digits=2):
    """Fixed-decimal text; the workbook's arithmetic must be reproducible.

    Excel is handed the same rounded numbers a reviewer reads, so
    ``長 × 高 × 厚`` on paper equals what the cell computes.
    """
    if value is None:
        return u''
    try:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return u''
    except Exception:
        return u''
    return u'{0:.{1}f}'.format(number + 1e-9 if number >= 0 else number - 1e-9,
                               digits)


def parse_number(value):
    text = _text(value).replace(u',', u'')
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    return float(match.group(0)) if match else None


def excel_col(index):
    result = u''
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


# --- grid location mark ----------------------------------------------------

def grid_normal(direction):
    """Unit normal of a grid line, with a deterministic sign.

    A grid's curve can be drawn from either end, which would flip the sign of
    every offset measured against it. The normal is therefore forced to point
    at +X (or +Y for grids running along X) so the same wall always reports the
    same side.
    """
    dx, dy = direction
    length = math.hypot(dx, dy)
    if length <= 0:
        return None
    nx, ny = -dy / length, dx / length
    if abs(nx) >= abs(ny):
        if nx < 0:
            nx, ny = -nx, -ny
    elif ny < 0:
        nx, ny = -nx, -ny
    return (nx, ny)


def grid_offset(point, grid):
    """Signed perpendicular distance in metres from the point to the grid."""
    normal = grid_normal(grid['direction'])
    if normal is None:
        return None
    return ((point[0] - grid['point'][0]) * normal[0] +
            (point[1] - grid['point'][1]) * normal[1])


def grid_runs_along_x(grid):
    return abs(grid['direction'][0]) >= abs(grid['direction'][1])


def offset_label(offset, tolerance=GRID_ON_LINE_TOLERANCE_M):
    if offset is None or abs(offset) < tolerance:
        return u''
    return u'({0:.1f})'.format(offset)


def _is_letter_grid(name):
    return not _text(name)[:1].isdigit()


def location_mark(point, grids, tolerance=GRID_ON_LINE_TOLERANCE_M):
    """``G(2.6)/15(1.5)`` — nearest grid in each direction, plus the offset.

    One pick per grid direction, so the mark always locates the wall on the
    plan rather than naming the two closest lines of the same family.
    """
    best = {}
    for grid in grids or ():
        offset = grid_offset(point, grid)
        if offset is None:
            continue
        family = 'x' if grid_runs_along_x(grid) else 'y'
        current = best.get(family)
        if current is None or abs(offset) < abs(current[1]):
            best[family] = (_text(grid.get('name')), offset)
    picks = [best[key] for key in ('y', 'x') if key in best]
    # Letter grids read first, matching how a drawing is called out.
    picks.sort(key=lambda item: 0 if _is_letter_grid(item[0]) else 1)
    return u'/'.join(u'{}{}'.format(name, offset_label(offset, tolerance))
                     for name, offset in picks)


# --- openings --------------------------------------------------------------

def opening_key(opening):
    return u'{0}||{1}||{2}'.format(
        _text(opening.get('name')),
        format_number(opening.get('width'), 3),
        format_number(opening.get('height'), 3))


def group_openings(openings):
    """Collapse identical openings into ``count`` rows, dropping sizeless ones.

    An opening with no readable width or height cannot be deducted; it is
    reported separately as a warning instead of silently counting as zero.
    """
    grouped = {}
    order = []
    for opening in openings or ():
        width = opening.get('width')
        height = opening.get('height')
        if not width or not height or width <= 0 or height <= 0:
            continue
        key = opening_key(opening)
        if key not in grouped:
            grouped[key] = {
                'name': _text(opening.get('name')),
                'width': float(width),
                'height': float(height),
                'count': 0,
            }
            order.append(key)
        grouped[key]['count'] += 1
    rows = [grouped[key] for key in order]
    rows.sort(key=lambda item: (item['name'], item['width'], item['height']))
    return rows


def opening_area(openings):
    """Deductible area of already-grouped opening rows."""
    return sum(item['count'] * item['width'] * item['height']
               for item in openings or ())


def wall_volume(length, height, thickness, deduct_area=0.0):
    """``(長 × 高 - 開口面積) × 厚``; never negative.

    An opening schedule larger than the wall face means bad data, not a
    negative pour, so the volume floors at zero and the caller reports it.
    """
    try:
        gross = float(length) * float(height)
        net = gross - float(deduct_area or 0.0)
        return max(0.0, net) * float(thickness)
    except Exception:
        return 0.0


def project_param(point, start, end):
    """How far along the wall (from its start) a point sits, in wall units.

    Walls are vertical, so the XY projection is enough to place a boundary
    segment or an opening along the wall's location line.
    """
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 0:
        return 0.0
    return ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length


def allocate_wall_to_rooms(wall_length, entries):
    """Split one wall's length among the rooms whose boundary it forms.

    A wall is one physical object, so its volume must be counted once no matter
    how many rooms it touches. Each room's share is its own boundary length
    against this wall, normalised so the shares add back up to the wall's real
    length:

    - An exterior wall running past three rooms is divided roughly where the
      rooms actually divide it.
    - An interior wall between two rooms is listed at full length by both, so
      each ends up with half — the shared wall is shared, not doubled.

    ``entries`` are ``{'room_key', 'seg_length', 'span'}``; the returned
    allocations carry ``length`` and ``share`` and always sum to
    ``wall_length``.
    """
    usable = [item for item in entries or ()
              if (item.get('seg_length') or 0) > 0]
    if not usable:
        return []
    total = sum(item['seg_length'] for item in usable)
    if total <= 0:
        return []
    allocations = []
    for item in usable:
        share = item['seg_length'] / total
        allocations.append({
            'room_key': item.get('room_key'),
            'room': item.get('room'),
            'span': item.get('span'),
            'seg_length': item['seg_length'],
            'share': share,
            'length': float(wall_length) * share,
        })
    return allocations


def assign_opening_to_allocation(param, allocations):
    """Which room's stretch of the wall an opening physically sits in.

    The opening is placed by where it is along the wall, not by which room the
    wall as a whole was filed under — that is the whole point of splitting.
    A hit outside every span (openings near a corner, or a boundary that does
    not reach the wall ends) falls back to the largest share rather than being
    dropped, because an un-deducted opening silently inflates the concrete.
    """
    if not allocations:
        return None
    if param is not None:
        for allocation in allocations:
            span = allocation.get('span')
            if not span:
                continue
            low, high = min(span), max(span)
            if low <= param <= high:
                return allocation
    return max(allocations, key=lambda item: item.get('share') or 0)


def format_room_allocation(allocations, room_labels, digits=2):
    """``F103:3.23m(33%) / F102:2.71m(27%)`` — how one wall was divided."""
    parts = []
    for allocation in allocations or ():
        label = room_labels.get(allocation.get('room_key'),
                                allocation.get('room_key') or u'?')
        parts.append(u'{0}:{1}m({2:.0f}%)'.format(
            label, format_number(allocation.get('length'), digits),
            (allocation.get('share') or 0) * 100.0))
    return u' / '.join(parts)


def net_volume(gross, deduction):
    """Volume after the un-joined beam/column/slab overlap comes off.

    Two beams crossing the same stretch of wall are measured against the wall
    separately, so their overlaps can add up to more than the wall holds; the
    result floors at zero and the caller reports the wall instead of writing a
    negative pour.
    """
    try:
        return max(0.0, float(gross) - float(deduction or 0.0))
    except Exception:
        return 0.0


def format_deduction_detail(items, limit=8):
    """``梁 12345:0.352 / 樓板 678:0.120`` — every deduction names its element.

    A volume that was removed without saying what removed it cannot be argued
    with on site, so each term carries the category and the ElementId.
    """
    parts = [u'{0} {1}:{2}'.format(item.get('label'), item.get('id'),
                                   format_number(item.get('volume'), 3))
             for item in items or ()]
    if len(parts) > limit:
        rest = len(parts) - limit
        parts = parts[:limit] + [u'…另 {0} 項'.format(rest)]
    return u' / '.join(parts)


def format_join_state(joined, deducted):
    """What the model's join state was for this wall, in one cell."""
    if not joined and not deducted:
        return u'無相鄰樑柱板'
    parts = []
    if joined:
        parts.append(u'已接合 {0}'.format(joined))
    if deducted:
        parts.append(u'未接合扣除 {0}'.format(deducted))
    return u'／'.join(parts)


def wall_group_key(type_name, height, thickness):
    """Walls only share a report row when all three multiplicands match."""
    return u'{0}||{1}||{2}'.format(
        _text(type_name), format_number(height, 2), format_number(thickness, 3))


# --- sorting ---------------------------------------------------------------

def floor_sort_key(number):
    """FN/BS -> B (deep to shallow) -> F (low to high) -> R, per the SOP."""
    text = _fold(number)
    if text.startswith(u'BS') or text.startswith(u'FN'):
        return (0, 0, parse_number(text) or 0, text)
    match = re.match(r'^([BFR])(\d{2,4})$', text)
    if not match:
        return (9, 999, 999999, text)
    prefix = match.group(1)
    digits = int(match.group(2))
    floor = digits // 100 if digits >= 100 else digits
    group = 1 if prefix == 'B' else 2 if prefix == 'F' else 3
    return (group, floor, digits, text)


def type_sort_key(type_name):
    """Group by the leading token, then by the thickness in the name.

    RC type names carry their thickness (``WA1 RC 牆 15cm``,
    ``外牆-RC-35cm``), so ordering by that number keeps thin walls together
    instead of relying on the string order of the whole name.
    """
    text = _fold(type_name)
    match = re.search(r'(\d+(?:\.\d+)?)\s*CM', text)
    thickness = float(match.group(1)) if match else 9999.0
    return (text.split(u' ')[0], thickness, text)
