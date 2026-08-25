# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure shaping rules for the tall-partition (>6 m) structural feedback sheet.

The MCP command returns wall records and room records separately. Structural
review needs them reconciled: excluding a wall type has to drop the wall *and*
any room that only qualified because of that wall, or the two sheets disagree
about how many rooms are affected.
"""

import re
import unicodedata


# domain/tall-partition-index-workflow.md fixes these wall types as out of
# scope. The MCP command has no excludeWallTypeNames parameter, so the filter
# is applied here on the returned wall list instead of being pushed into C#.
DEFAULT_EXCLUDE_WALL_TYPES = (
    u'Type-F 岩棉庫板',
    u'Type-F 岩棉庫板(柱封版)',
)

WALL_HEADERS = (
    u'樓層', u'牆 ElementId', u'牆類型', u'牆高(mm)', u'高度依據',
    u'牆長(m)', u'牆面積(m²)', u'相鄰房間數', u'雙面共用', u'關聯房間',
)

ROOM_HEADERS = (
    u'樓層', u'房號', u'房間名稱', u'房間 ElementId', u'房間面積(m²)',
    u'高牆數', u'共用高牆數', u'牆邊界長(m)', u'房間側牆面積(m²)',
    u'射線淨高最小(mm)', u'射線淨高最大(mm)', u'射線淨高平均(mm)',
    u'關聯牆 ElementId',
)


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value)
    except Exception:
        return str(value)


def normalize_text(value):
    text = unicodedata.normalize('NFKC', _text(value)).lower()
    return re.sub(u'[\\s（）()\\[\\]【】，,、:：;；._\\-/\\\\]', u'', text)


def wall_type_excluded(type_name, exclusions):
    """Normalized substring match, so 全形/半形 and spacing do not matter."""
    value = normalize_text(type_name)
    if not value:
        return False
    for item in exclusions or ():
        needle = normalize_text(item)
        if needle and needle in value:
            return True
    return False


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _id_list(values):
    return u', '.join(_text(value) for value in values)


def room_label(room):
    return u'{} {}'.format(
        _text(room.get('Number')), _text(room.get('Name'))).strip()


def split_walls(data, exclusions):
    """``(kept, excluded)`` wall records from the command response."""
    kept = []
    excluded = []
    for wall in data.get('Walls') or []:
        if wall_type_excluded(wall.get('TypeName'), exclusions):
            excluded.append(wall)
        else:
            kept.append(wall)
    return kept, excluded


def build_wall_rows(walls):
    """One row per wall, tallest first within a level — structure reads it that way."""
    rows = []
    for wall in walls:
        rooms = wall.get('Rooms') or []
        rows.append([
            _text(wall.get('Level')),
            wall.get('WallId'),
            _text(wall.get('TypeName')),
            _number(wall.get('HeightMm')),
            _text(wall.get('HeightBasis')),
            _number(wall.get('WallLengthM')),
            _number(wall.get('UniqueWallAreaM2')),
            len(rooms),
            u'是' if wall.get('IsSharedBetweenTargetRooms') else u'否',
            u' / '.join(room_label(room) for room in rooms),
        ])
    rows.sort(key=lambda row: (
        _text(row[0]), -(row[3] if row[3] is not None else 0), _text(row[1])))
    return rows


def rebuild_rooms(data, walls):
    """Recompute per-room figures from the walls that survived the filter.

    Room totals in the raw response include the excluded wall types, so they
    cannot be reused as-is: a room whose only tall wall is a Type-F panel must
    disappear from the room sheet, not show up with a zero count.
    """
    meta = {}
    for room in data.get('Rooms') or []:
        meta[room.get('RoomId')] = room
    rooms = {}
    for wall in walls:
        height = _number(wall.get('HeightMm'))
        shared = bool(wall.get('IsSharedBetweenTargetRooms'))
        for side in wall.get('Rooms') or []:
            room_id = side.get('RoomId')
            entry = rooms.get(room_id)
            if entry is None:
                source = meta.get(room_id) or {}
                entry = {
                    'room_id': room_id,
                    'number': _text(side.get('Number') or source.get('Number')),
                    'name': _text(side.get('Name') or source.get('Name')),
                    'level': _text(side.get('Level') or source.get('Level')),
                    'area_m2': _number(source.get('AreaM2')),
                    'clear_height': source.get('RoomClearHeightByRay') or {},
                    'wall_ids': [],
                    'wall_count': 0,
                    'shared_count': 0,
                    'boundary_length_m': 0.0,
                    'room_side_area_m2': 0.0,
                    'max_wall_height_mm': None,
                }
                rooms[room_id] = entry
            entry['wall_ids'].append(wall.get('WallId'))
            entry['wall_count'] += 1
            if shared:
                entry['shared_count'] += 1
            entry['boundary_length_m'] += _number(
                side.get('BoundaryLengthM')) or 0.0
            entry['room_side_area_m2'] += _number(
                side.get('RoomSideAreaM2')) or 0.0
            if height is not None and (entry['max_wall_height_mm'] is None
                                       or height > entry['max_wall_height_mm']):
                entry['max_wall_height_mm'] = height
    return rooms


def build_room_rows(rooms):
    rows = []
    for entry in rooms.values():
        clear = entry['clear_height'] or {}
        rows.append([
            entry['level'],
            entry['number'],
            entry['name'],
            entry['room_id'],
            entry['area_m2'],
            entry['wall_count'],
            entry['shared_count'],
            round(entry['boundary_length_m'], 2),
            round(entry['room_side_area_m2'], 2),
            _number(clear.get('MinHeightMm')),
            _number(clear.get('MaxHeightMm')),
            _number(clear.get('AverageHeightMm')),
            _id_list(entry['wall_ids']),
        ])
    rows.sort(key=lambda row: (_text(row[0]), _text(row[1]), _text(row[3])))
    return rows


def build_criteria_rows(data, exclusions, excluded_walls, kept_walls,
                        room_count):
    criteria = data.get('Criteria') or {}
    summary = data.get('Summary') or {}
    rows = [[u'項目', u'內容']]

    def add(label, value):
        rows.append([label, _text(value)])

    levels = criteria.get('Levels')
    add(u'掃描樓層', u', '.join(_text(item) for item in levels or [])
        if isinstance(levels, list) else levels)
    add(u'自動偵測樓層', u'是' if criteria.get('AutoDetectLevels') else u'否')
    add(u'牆類型關鍵字', criteria.get('WallTypeContains'))
    add(u'高度門檻(mm)', criteria.get('MinWallHeightMm'))
    add(u'排除房名關鍵字', u', '.join(
        _text(item) for item in criteria.get('ExcludeRoomNameContains') or []))
    add(u'排除牆類型', u', '.join(_text(item) for item in exclusions or ())
        or u'（無）')
    add(u'含單面邊界牆', u'是' if criteria.get(
        'IncludeSingleRoomBoundaryWalls') else u'否')
    add(u'射線淨高取樣', criteria.get('RoomRaySampleGrid'))
    rows.append([u'', u''])
    rows.append([u'統計', u''])
    add(u'掃描房間數', summary.get('RoomsScanned'))
    add(u'排除房間數', summary.get('RoomsExcluded'))
    add(u'命中高牆數（排除牆型前）', summary.get('TallPartitionWalls'))
    add(u'排除牆型後高牆數', len(kept_walls))
    add(u'因牆型被排除的牆數', len(excluded_walls))
    add(u'受影響房間數', room_count)
    add(u'高牆總長(m)', summary.get('UniqueWallLengthM'))
    add(u'高牆總面積(m²)', summary.get('UniqueWallAreaM2'))

    if excluded_walls:
        rows.append([u'', u''])
        rows.append([u'因牆型排除的牆', u''])
        for wall in excluded_walls:
            rows.append([
                _text(wall.get('WallId')),
                u'{}　{}　{} mm'.format(
                    _text(wall.get('Level')), _text(wall.get('TypeName')),
                    _text(wall.get('HeightMm')))])

    excluded_rooms = data.get('ExcludedRooms') or []
    if excluded_rooms:
        rows.append([u'', u''])
        rows.append([u'因房名排除的房間', u''])
        for room in excluded_rooms:
            if isinstance(room, dict):
                rows.append([_text(room.get('RoomId')), u'{} {} {}'.format(
                    _text(room.get('Level')), _text(room.get('Number')),
                    _text(room.get('Name'))).strip()])
            else:
                rows.append([u'', _text(room)])

    warnings = data.get('Warnings') or []
    if warnings:
        rows.append([u'', u''])
        rows.append([u'警告', u''])
        for warning in warnings:
            rows.append([u'', _text(warning)])
    return rows


def build_workbook_data(data, exclusions=DEFAULT_EXCLUDE_WALL_TYPES):
    """Everything the three sheets need, reconciled against one wall filter."""
    kept, excluded = split_walls(data, exclusions)
    rooms = rebuild_rooms(data, kept)
    wall_rows = build_wall_rows(kept)
    room_rows = build_room_rows(rooms)
    return {
        'wall_values': [list(WALL_HEADERS)] + wall_rows,
        'room_values': [list(ROOM_HEADERS)] + room_rows,
        'criteria_values': build_criteria_rows(
            data, exclusions, excluded, kept, len(rooms)),
        'wall_count': len(kept),
        'excluded_wall_count': len(excluded),
        'room_count': len(rooms),
        'levels': sorted(set(
            _text(wall.get('Level')) for wall in kept if wall.get('Level'))),
        'max_height_mm': max(
            [_number(wall.get('HeightMm')) or 0 for wall in kept] or [0]),
    }


def summary_message(shaped, threshold_mm):
    lines = [
        u'高於 {:.0f} mm 的輕隔間牆：{} 面'.format(
            float(threshold_mm), shaped['wall_count']),
        u'受影響房間：{} 間'.format(shaped['room_count']),
        u'涵蓋樓層：{}'.format(u', '.join(shaped['levels']) or u'（無）'),
    ]
    if shaped['max_height_mm']:
        lines.append(u'最高牆：{:.0f} mm'.format(shaped['max_height_mm']))
    if shaped['excluded_wall_count']:
        lines.append(u'依牆型排除：{} 面'.format(shaped['excluded_wall_count']))
    return u'\n'.join(lines)
