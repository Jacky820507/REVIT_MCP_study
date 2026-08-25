# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure identity and workbook-safety helpers for multi-model room takeoff."""

import re
import math


PENDING_SPACE_STATUSES = frozenset([
    'update', 'idfill', 'insert', 'manual_append', 'delete_row', 'move'])


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def composite_room_id(source_key, element_id):
    """Return a stable room id that cannot collide between Revit documents."""
    source = _text(source_key)
    if not source:
        raise ValueError('source_key is required')
    try:
        local_id = int(element_id)
    except (TypeError, ValueError):
        raise ValueError('element_id must be an integer')
    return u'{}:{}'.format(source, local_id)


def normalize_room_number(value):
    return re.sub(r'\s+', '', _text(value)).upper()


def room_number_sort_key(value):
    """Natural room-number key: B9 before B10, B134 before B135."""
    number = normalize_room_number(value)
    if not number:
        return ((0, u''),)
    parts = []
    cursor = 0
    for match in re.finditer(r'\d+', number):
        if match.start() > cursor:
            parts.append((0, number[cursor:match.start()]))
        raw = match.group(0)
        parts.append((1, int(raw), len(raw), raw))
        cursor = match.end()
    if cursor < len(number):
        parts.append((0, number[cursor:]))
    return tuple(parts)


def room_number_prefix(value):
    number = normalize_room_number(value)
    match = re.match(r'^(.*?)(\d+)$', number)
    return match.group(1) if match else number


def duplicate_room_numbers(records):
    """Return normalized room numbers owned by more than one composite room."""
    owners = {}
    for record in records or []:
        number = normalize_room_number(record.get('Number'))
        identity = _text(
            record.get('CompositeId') or record.get('ElementId'))
        if not number or not identity:
            continue
        owners.setdefault(number, set()).add(identity)
    return dict(
        (number, sorted(values))
        for number, values in owners.items()
        if len(values) > 1)


def level_is_allowed(level_id, allowed_level_ids):
    if allowed_level_ids is None:
        return True
    try:
        value = int(level_id)
    except (TypeError, ValueError):
        return False
    return value in set(int(item) for item in allowed_level_ids)


def destructive_space_sync_allowed(options):
    """Only a complete host-only scope may remove unmatched workbook rows.

    A partial link or level selection cannot prove that an unmatched Excel
    row represents a demolished room.  The conservative host-only case keeps
    compatibility with the legacy workbook whose managed identity was the
    active model's bare ElementId.
    """
    options = options or {}
    return (
        bool(options.get('include_host', True))
        and not list(options.get('selected_link_ids') or [])
        and not list(options.get('selected_level_keys') or [])
    )


def workbook_is_host_only(entries):
    """Treat blank/bare/host ids as the proven legacy host-only contract."""
    for entry in entries or []:
        identity = _text(entry.get('rid'))
        if identity.startswith(u'link:'):
            return False
    return True


def unmatched_workbook_status(allow_removals):
    return 'delete_row' if allow_removals else 'out_of_scope'


def is_host_identity_migration(old_identity, new_identity):
    old_value = _text(old_identity)
    new_value = _text(new_identity)
    return bool(
        old_value and u':' not in old_value and
        new_value.startswith(u'host:'))


def exact_room_identity_matches(excel_identity, source_key,
                                local_element_id, composite_identity):
    """Allow composite equality plus the one safe legacy host migration."""
    excel_value = _text(excel_identity)
    composite_value = _text(composite_identity)
    if not excel_value:
        return False
    if excel_value == composite_value:
        return True
    if _text(source_key) != u'host':
        return False
    try:
        numeric_identity = float(excel_value)
        if numeric_identity != int(numeric_identity):
            return False
        return int(numeric_identity) == int(local_element_id)
    except (TypeError, ValueError):
        return False


def source_conflict_numbers(excel_entries, revit_rooms):
    """Numbers occupied by an unmatched workbook row and a selected room."""
    excel_numbers = set(
        normalize_room_number(entry.get('number'))
        for entry in excel_entries or []
        if normalize_room_number(entry.get('number')))
    revit_numbers = set(
        normalize_room_number(room.get('number') or room.get('Number'))
        for room in revit_rooms or []
        if normalize_room_number(room.get('number') or room.get('Number')))
    return excel_numbers & revit_numbers


def space_status_is_pending(status):
    return status in PENDING_SPACE_STATUSES


def space_insert_anchor_rows(entries, items):
    """Rows available as insertion anchors, including preserved out-of-scope rows."""
    anchors = {}
    for entry in entries or []:
        number = _text(entry.get('number') or entry.get('Number'))
        if number:
            anchors[number] = entry
    for item in items or []:
        entry = item.get('entry')
        if entry is None or item.get('status') in ('unresolved',):
            continue
        old_number = _text(item.get('old_number'))
        number = _text(item.get('number'))
        if old_number and old_number != number and anchors.get(old_number) is entry:
            del anchors[old_number]
        if number:
            anchors[number] = entry
    return anchors


def plan_space_row_moves(entries, movable_entries=None):
    """Plan row moves to restore contiguous natural order within prefixes.

    Prefix block order follows the workbook's first occurrence, so legacy
    blocks such as BS, B, F, R keep their relative meaning.  Only entries in
    movable_entries are moved; all other rows can still act as anchors.
    """
    current = sorted(list(entries or []), key=lambda entry: entry.get('row') or 0)
    if not current:
        return []
    if movable_entries is None:
        movable_ids = set(id(entry) for entry in current)
    else:
        movable_ids = set(id(entry) for entry in movable_entries)
    prefix_order = {}
    for entry in current:
        prefix = room_number_prefix(entry.get('number') or entry.get('Number'))
        if prefix not in prefix_order:
            prefix_order[prefix] = len(prefix_order)
    desired = sorted(
        current,
        key=lambda entry: (
            prefix_order[room_number_prefix(
                entry.get('number') or entry.get('Number'))],
            room_number_sort_key(entry.get('number') or entry.get('Number')),
            entry.get('row') or 0,
        ))
    moves = []
    for target_index, desired_entry in enumerate(desired):
        if id(desired_entry) not in movable_ids:
            continue
        current_index = current.index(desired_entry)
        if current_index == target_index:
            continue
        before_entry = current[target_index]
        anchor_entry = current[target_index - 1] if target_index else None
        moves.append({
            'entry': desired_entry,
            'before': before_entry,
            'anchor': anchor_entry,
        })
        current.pop(current_index)
        current.insert(target_index, desired_entry)
    return moves


def room_sort_key(record):
    """Basements, normal floors, roofs, then room number and source."""
    level = _text(record.get('Level')).upper().replace(' ', '')
    match = re.search(r'(^|-)B0*(\d+)F?$', level)
    if match:
        level_key = (0, -int(match.group(2)))
    else:
        match = re.search(r'(^|-)R0*(\d+)F?$', level)
        if match:
            level_key = (2, int(match.group(2)))
        elif level.endswith('RF'):
            level_key = (3, 0)
        else:
            match = re.search(r'(^|-)0*(\d+)F$', level)
            level_key = (1, int(match.group(2))) if match else (4, level)
    return (
        level_key,
        room_number_sort_key(record.get('Number')),
        _text(record.get('SourceKey')),
        _text(record.get('CompositeId')),
    )


def oriented_dimensions(points):
    """Return the minimum-area oriented XY bounds for boundary points."""
    clean = []
    for point in points or []:
        try:
            value = (float(point[0]), float(point[1]))
        except (TypeError, ValueError, IndexError):
            continue
        if value not in clean:
            clean.append(value)
    if len(clean) < 2:
        return None, None
    angles = set([0.0])
    for index, point in enumerate(clean):
        other = clean[(index + 1) % len(clean)]
        dx = other[0] - point[0]
        dy = other[1] - point[1]
        if abs(dx) + abs(dy) <= 1e-9:
            continue
        angle = math.atan2(dy, dx) % (math.pi / 2.0)
        angles.add(round(angle, 12))
    best = None
    for angle in angles:
        cosine = math.cos(angle)
        sine = math.sin(angle)
        xs = [x * cosine + y * sine for x, y in clean]
        ys = [-x * sine + y * cosine for x, y in clean]
        width = max(xs) - min(xs)
        depth = max(ys) - min(ys)
        area = width * depth
        candidate = (area, max(width, depth), min(width, depth))
        if best is None or candidate < best:
            best = candidate
    return (best[1], best[2]) if best else (None, None)
