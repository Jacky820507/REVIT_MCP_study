# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import codecs
import json
from collections import OrderedDict

from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter,
                               FamilyInstance, FilteredElementCollector,
                               SpatialElementBoundaryOptions, Wall)
from Autodesk.Revit.DB.Architecture import Room
from pyrevit import forms, revit, script


__title__ = u'房間\n關係盤點'
_TITLE = u'房間—牆—門窗關係盤點'


def _id_value(element_or_id):
    """Return a Revit ElementId as a plain int across supported versions."""
    value = getattr(element_or_id, 'Id', element_or_id)
    for property_name in ('Value', 'IntegerValue'):
        try:
            return int(getattr(value, property_name))
        except Exception:
            pass
    try:
        return int(value)
    except Exception:
        return 0


def _safe_text(value):
    if value is None:
        return u''
    try:
        return unicode(value)
    except Exception:
        return u''


def _parameter_text(element, parameter_id):
    if element is None:
        return u''
    try:
        parameter = element.get_Parameter(parameter_id)
        if parameter is None:
            return u''
        return (_safe_text(parameter.AsString()) or
                _safe_text(parameter.AsValueString()))
    except Exception:
        return u''


def _room_name(room):
    try:
        return _safe_text(room.Name)
    except Exception:
        return u''


def _room_ref(room):
    if room is None:
        return u''
    try:
        return u'{0} {1}'.format(_id_value(room), _safe_text(room.Number))
    except Exception:
        return u'{0}'.format(_id_value(room))


def _level_name(doc, element):
    try:
        level_id = element.LevelId
        level = doc.GetElement(level_id)
        return _safe_text(level.Name) if level is not None else u''
    except Exception:
        return u''


def _room_level_name(doc, room):
    try:
        level = doc.GetElement(room.LevelId)
        return _safe_text(level.Name) if level is not None else u''
    except Exception:
        return u''


def _boundary_walls(doc, room):
    wall_ids = set()
    walls = []
    try:
        loops = room.GetBoundarySegments(SpatialElementBoundaryOptions())
        if loops is None:
            return wall_ids, walls
        for loop in loops:
            if loop is None:
                continue
            for segment in loop:
                if segment is None:
                    continue
                boundary = doc.GetElement(segment.ElementId)
                if not isinstance(boundary, Wall):
                    continue
                wall_id = _id_value(boundary)
                if wall_id in wall_ids:
                    continue
                wall_ids.add(wall_id)
                wall_type = u''
                try:
                    wall_type = _safe_text(boundary.WallType.Name)
                except Exception:
                    pass
                walls.append(OrderedDict([
                    ('ElementId', wall_id),
                    ('UniqueId', _safe_text(boundary.UniqueId)),
                    ('Name', _safe_text(boundary.Name)),
                    ('Type', wall_type),
                    ('RelationStatus', u'confirmed'),
                ]))
    except Exception as ex:
        return wall_ids, [OrderedDict([
            ('ElementId', 0),
            ('UniqueId', u''),
            ('Name', u''),
            ('Type', u''),
            ('RelationStatus', u'unresolved'),
            ('Warning', u'讀取 Room 邊界失敗：{0}'.format(_safe_text(ex))),
        ])]
    return wall_ids, walls


def _document_phases(doc):
    phases = []
    try:
        for phase in doc.Phases:
            phases.append(phase)
    except Exception:
        pass
    return phases


def _opening_phases(doc, opening, phases):
    """Put the opening's creation phase first, then use the document phases."""
    created = None
    try:
        parameter = opening.get_Parameter(BuiltInParameter.PHASE_CREATED)
        if parameter is not None and parameter.HasValue:
            created = doc.GetElement(parameter.AsElementId())
    except Exception:
        created = None
    if created is None:
        return phases

    created_id = _id_value(created)
    return [created] + [phase for phase in phases
                        if _id_value(phase) != created_id]


def _opening_room(opening, property_name, phases):
    """Resolve FromRoom/ToRoom without exposing IronPython's indexer object.

    Revit exposes both a parameterless property and a Phase overload.  Under
    IronPython 2.7, the parameterless member is surfaced as ``indexer#``;
    calling the generated ``get_*`` accessor with a Phase returns the Room.
    """
    try:
        getter = getattr(opening, 'get_{0}'.format(property_name))
    except Exception:
        return None
    for phase in phases:
        try:
            room = getter(phase)
            if room is not None:
                return room
        except Exception:
            pass
    return None


def _opening_summary(doc, opening, is_door, from_room, to_room,
                     relation_status, relation_source):
    symbol = None
    host = None
    try:
        symbol = opening.Symbol
    except Exception:
        pass
    try:
        host = opening.Host
    except Exception:
        pass

    family_name = u''
    type_name = u''
    if symbol is not None:
        try:
            family_name = _safe_text(symbol.FamilyName)
        except Exception:
            pass
        try:
            type_name = _safe_text(symbol.Name)
        except Exception:
            pass

    return OrderedDict([
        ('ElementId', _id_value(opening)),
        ('UniqueId', _safe_text(opening.UniqueId)),
        ('Category', u'Doors' if is_door else u'Windows'),
        ('Family', family_name),
        ('Type', type_name),
        ('TypeMark', _parameter_text(symbol, BuiltInParameter.ALL_MODEL_TYPE_MARK)),
        ('Mark', _parameter_text(opening, BuiltInParameter.ALL_MODEL_MARK)),
        ('HostWallId', _id_value(host) if host is not None else 0),
        ('Level', _level_name(doc, opening)),
        ('FromRoomId', _id_value(from_room) if from_room is not None else 0),
        ('FromRoomNumber', _safe_text(from_room.Number) if from_room is not None else u''),
        ('FromRoomName', _room_name(from_room) if from_room is not None else u''),
        ('ToRoomId', _id_value(to_room) if to_room is not None else 0),
        ('ToRoomNumber', _safe_text(to_room.Number) if to_room is not None else u''),
        ('ToRoomName', _room_name(to_room) if to_room is not None else u''),
        ('RelationStatus', relation_status),
        ('RelationSource', relation_source),
    ])


def _attach_opening(doc, opening, is_door, room_by_id, wall_to_rooms,
                    assigned_ids, unassigned, phases):
    opening_phases = _opening_phases(doc, opening, phases)
    from_room = _opening_room(opening, 'FromRoom', opening_phases)
    to_room = _opening_room(opening, 'ToRoom', opening_phases)
    direct_matches = []
    for room, source in ((from_room, u'FromRoom'), (to_room, u'ToRoom')):
        if room is None:
            continue
        room_id = _id_value(room)
        if room_id in room_by_id and room_id not in [item[0] for item in direct_matches]:
            direct_matches.append((room_id, source))

    matches = list(direct_matches)
    if not matches:
        try:
            host = opening.Host
            host_id = _id_value(host) if host is not None else 0
        except Exception:
            host_id = 0
        for room_id in wall_to_rooms.get(host_id, []):
            matches.append((room_id, u'HostWallBoundary'))

    if not matches:
        unassigned.append(_opening_summary(
            doc, opening, is_door, from_room, to_room,
            u'unresolved', u'NoRoomMatch'))
        return

    relation_status = u'confirmed' if direct_matches else u'inferred'
    for room_id, relation_source in matches:
        record = room_by_id[room_id]
        opening_id = _id_value(opening)
        target_ids = record['_DoorIds'] if is_door else record['_WindowIds']
        if opening_id in target_ids:
            continue
        target_ids.add(opening_id)
        target = record['Doors'] if is_door else record['Windows']
        target.append(_opening_summary(
            doc, opening, is_door, from_room, to_room,
            relation_status, relation_source))
        assigned_ids.add(opening_id)


def _build_report(doc):
    phases = _document_phases(doc)
    room_elements = list(FilteredElementCollector(doc)
                         .OfCategory(BuiltInCategory.OST_Rooms)
                         .WhereElementIsNotElementType()
                         .ToElements())
    rooms = [room for room in room_elements if isinstance(room, Room)]
    rooms = sorted(rooms, key=lambda room: (
        _room_level_name(doc, room),
        _safe_text(room.Number),
        _room_name(room)))

    records = []
    room_by_id = {}
    wall_to_rooms = {}
    boundary_wall_ids = set()
    for room in rooms:
        wall_ids, walls = _boundary_walls(doc, room)
        record = OrderedDict([
            ('ElementId', _id_value(room)),
            ('UniqueId', _safe_text(room.UniqueId)),
            ('Number', _safe_text(room.Number)),
            ('Name', _room_name(room)),
            ('Level', _room_level_name(doc, room)),
            ('AreaM2', round(float(room.Area) * 0.09290304, 2)),
            ('RelationStatus', u'confirmed' if wall_ids else u'unresolved'),
            ('BoundaryWalls', walls),
            ('Doors', []),
            ('Windows', []),
            ('Warnings', []),
            ('_BoundaryWallIds', wall_ids),
            ('_DoorIds', set()),
            ('_WindowIds', set()),
        ])
        for wall_id in wall_ids:
            boundary_wall_ids.add(wall_id)
            wall_to_rooms.setdefault(wall_id, []).append(_id_value(room))
        if not wall_ids:
            record['Warnings'].append(
                u'未取得可辨識的邊界牆；需檢查 Room Bounding、Phase 或邊界設定。')
        records.append(record)
        room_by_id[_id_value(room)] = record

    doors = list(FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_Doors)
                 .OfClass(FamilyInstance)
                 .WhereElementIsNotElementType()
                 .ToElements())
    windows = list(FilteredElementCollector(doc)
                   .OfCategory(BuiltInCategory.OST_Windows)
                   .OfClass(FamilyInstance)
                   .WhereElementIsNotElementType()
                   .ToElements())
    unassigned_doors = []
    unassigned_windows = []
    assigned_doors = set()
    assigned_windows = set()
    for door in doors:
        _attach_opening(doc, door, True, room_by_id, wall_to_rooms,
                        assigned_doors, unassigned_doors, phases)
    for window in windows:
        _attach_opening(doc, window, False, room_by_id, wall_to_rooms,
                        assigned_windows, unassigned_windows, phases)

    public_records = []
    for record in records:
        public_records.append(OrderedDict([
            ('ElementId', record['ElementId']),
            ('UniqueId', record['UniqueId']),
            ('Number', record['Number']),
            ('Name', record['Name']),
            ('Level', record['Level']),
            ('AreaM2', record['AreaM2']),
            ('RelationStatus', record['RelationStatus']),
            ('BoundaryWalls', record['BoundaryWalls']),
            ('Doors', record['Doors']),
            ('Windows', record['Windows']),
            ('Warnings', record['Warnings']),
        ]))

    return OrderedDict([
        ('Success', True),
        ('Scope', OrderedDict([
            ('IncludeWindows', True),
            ('Rule', u'Room 邊界是幾何證據；FromRoom/ToRoom 是 Revit 關係證據；Host Wall 對應只標記為 inferred。'),
        ])),
        ('Summary', OrderedDict([
            ('TotalRooms', len(public_records)),
            ('BoundaryWalls', len(boundary_wall_ids)),
            ('TotalDoors', len(doors)),
            ('AssignedDoors', len(assigned_doors)),
            ('InferredDoors', sum(1 for record in public_records for item in record['Doors'] if item['RelationStatus'] == u'inferred')),
            ('UnassignedDoors', len(unassigned_doors)),
            ('TotalWindows', len(windows)),
            ('AssignedWindows', len(assigned_windows)),
            ('InferredWindows', sum(1 for record in public_records for item in record['Windows'] if item['RelationStatus'] == u'inferred')),
            ('UnassignedWindows', len(unassigned_windows)),
        ])),
        ('Rooms', public_records),
        ('UnassignedDoors', unassigned_doors),
        ('UnassignedWindows', unassigned_windows),
        ('Message', u'唯讀盤點完成；本按鈕沒有修改模型。'),
    ])


def _print_report(report):
    output = script.get_output()
    summary = report['Summary']
    output.print_md(u'## {0}'.format(_TITLE))
    output.print_md(u'**{0}**'.format(report['Message']))
    output.print_table([
        [u'房間', summary['TotalRooms']],
        [u'邊界牆', summary['BoundaryWalls']],
        [u'門／已分配／推定', u'{0} / {1} / {2}'.format(summary['TotalDoors'], summary['AssignedDoors'], summary['InferredDoors'])],
        [u'窗／已分配／推定', u'{0} / {1} / {2}'.format(summary['TotalWindows'], summary['AssignedWindows'], summary['InferredWindows'])],
        [u'未分配門／窗', u'{0} / {1}'.format(summary['UnassignedDoors'], summary['UnassignedWindows'])],
    ], [u'項目', u'數值'], title=u'摘要')

    room_rows = []
    for room in report['Rooms']:
        room_rows.append([
            room['Level'], room['Number'], room['Name'], room['AreaM2'],
            len(room['BoundaryWalls']), len(room['Doors']), len(room['Windows']),
            room['RelationStatus'],
        ])
    output.print_table(room_rows,
                       [u'樓層', u'編號', u'名稱', u'面積 m²', u'牆', u'門', u'窗', u'狀態'],
                       title=u'Room 關係盤點')

    relation_rows = []
    for room in report['Rooms']:
        for item in room['Doors'] + room['Windows']:
            relation_rows.append([
                item['Category'], room['Level'], room['Number'],
                item['ElementId'], item['Family'], item['Type'],
                item['FromRoomNumber'], item['ToRoomNumber'],
                item['RelationStatus'], item['RelationSource'],
            ])
    if relation_rows:
        output.print_table(relation_rows,
                           [u'類別', u'樓層', u'房間', u'ElementId', u'族', u'類型',
                            u'FromRoom', u'ToRoom', u'狀態', u'來源'],
                           title=u'門窗關係證據')

    if report['UnassignedDoors'] or report['UnassignedWindows']:
        output.print_md(u'### 未分配門窗')
        for item in report['UnassignedDoors'] + report['UnassignedWindows']:
            output.print_md(u'- {0} `#{1}` {2} / {3}：{4}'.format(
                item['Category'], item['ElementId'], item['Family'], item['Type'],
                item['RelationStatus']))


def _save_report(report):
    if not forms.alert(u'要另存 JSON 盤點報告嗎？', title=_TITLE, yes=True, no=True):
        return
    path = forms.save_file(file_ext='json',
                           default_name='room-wall-door-audit.json')
    if not path:
        return
    handle = codecs.open(path, 'w', 'utf-8')
    try:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        handle.close()
    forms.alert(u'已輸出：\n{0}'.format(path), title=_TITLE)


if revit.doc is None:
    forms.alert(u'請先開啟 Revit 專案檔，再執行房間關係盤點。',
                title=_TITLE, exitscript=True)

try:
    _report = _build_report(revit.doc)
    _print_report(_report)
    _save_report(_report)
except Exception as ex:
    forms.alert(u'盤點失敗：\n{0}'.format(_safe_text(ex)),
                title=_TITLE, exitscript=True)
