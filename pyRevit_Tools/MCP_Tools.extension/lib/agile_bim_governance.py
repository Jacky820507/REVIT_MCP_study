# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Shared IronPython 2.7 helpers for the Agile BIM governance buttons."""

import codecs
import json
import re
from collections import OrderedDict

from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter,
                               FilteredElementCollector, SpatialElementBoundaryOptions,
                               StorageType, Transaction, Wall, WallKind)
from Autodesk.Revit.DB.Architecture import Room

import door_window_marks as door_marks
import duplicate_mark_logic as mark_identity


SQFT_TO_SQM = 0.09290304


def _id_value(value):
    target = getattr(value, 'Id', value)
    for property_name in ('Value', 'IntegerValue'):
        try:
            return int(getattr(target, property_name))
        except Exception:
            pass
    try:
        return int(target)
    except Exception:
        return -1


def _text(value):
    if value is None:
        return u''
    try:
        return unicode(value).strip()
    except Exception:
        return u''


def room_name(room):
    try:
        parameter = room.get_Parameter(BuiltInParameter.ROOM_NAME)
        if parameter is not None:
            value = _text(parameter.AsString())
            if value:
                return value
    except Exception:
        pass
    try:
        return _text(room.Name)
    except Exception:
        return u''


def room_number(room):
    try:
        return _text(room.Number)
    except Exception:
        return u''


def level_name(doc, room):
    try:
        level = doc.GetElement(room.LevelId)
        return _text(level.Name) if level is not None else u''
    except Exception:
        return u''


def collect_rooms(doc, include_unplaced=False):
    rooms = []
    elements = (FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Rooms)
                .WhereElementIsNotElementType()
                .ToElements())
    for room in elements:
        if not isinstance(room, Room):
            continue
        try:
            if not include_unplaced and float(room.Area) <= 0:
                continue
        except Exception:
            if not include_unplaced:
                continue
        rooms.append(room)
    return sorted(rooms, key=lambda room: (
        level_name(doc, room), room_number(room), room_name(room)))


def parameter_name(parameter):
    try:
        return _text(parameter.Definition.Name)
    except Exception:
        return u''


def parameter_value(parameter):
    if parameter is None:
        return u''
    try:
        if parameter.StorageType == StorageType.String:
            return _text(parameter.AsString())
        return _text(parameter.AsValueString())
    except Exception:
        return u''


def resolve_parameter(room, requested_name):
    """Return (parameter, ambiguous) without guessing among same-name fields."""
    requested = _text(requested_name)
    if room is None or not requested:
        return None, False

    matches = []
    try:
        for parameter in room.Parameters:
            if parameter_name(parameter).lower() == requested.lower():
                matches.append(parameter)
    except Exception:
        matches = []
    if len(matches) > 1:
        return None, True
    if len(matches) == 1:
        return matches[0], False

    aliases = {
        'room_name': BuiltInParameter.ROOM_NAME,
        'room_number': BuiltInParameter.ROOM_NUMBER,
        'room_department': BuiltInParameter.ROOM_DEPARTMENT,
    }
    built_in = aliases.get(requested.lower())
    if built_in is not None:
        try:
            parameter = room.get_Parameter(built_in)
            if parameter is not None:
                return parameter, False
        except Exception:
            pass
    try:
        return room.LookupParameter(requested), False
    except Exception:
        return None, False


def parameter_dictionary(rooms, include_values=True, max_samples=5):
    entries = {}
    for room in rooms:
        try:
            parameters = list(room.Parameters)
        except Exception:
            parameters = []
        for parameter in parameters:
            name = parameter_name(parameter)
            if not name:
                continue
            key = name.lower()
            if key not in entries:
                entries[key] = OrderedDict([
                    ('Name', name),
                    ('ParameterIds', set()),
                    ('StorageTypes', set()),
                    ('SampleCount', 0),
                    ('WritableSampleCount', 0),
                    ('ReadOnlySampleCount', 0),
                    ('Samples', []),
                ])
            entry = entries[key]
            try:
                entry['ParameterIds'].add(_id_value(parameter))
            except Exception:
                pass
            try:
                entry['StorageTypes'].add(_text(parameter.StorageType))
            except Exception:
                pass
            entry['SampleCount'] += 1
            try:
                if parameter.IsReadOnly:
                    entry['ReadOnlySampleCount'] += 1
                else:
                    entry['WritableSampleCount'] += 1
            except Exception:
                pass
            if include_values and len(entry['Samples']) < max_samples:
                try:
                    has_value = bool(parameter.HasValue)
                except Exception:
                    has_value = False
                entry['Samples'].append(OrderedDict([
                    ('ElementId', _id_value(room)),
                    ('Number', room_number(room)),
                    ('Value', parameter_value(parameter)),
                    ('HasValue', has_value),
                    ('IsReadOnly', bool(parameter.IsReadOnly)),
                ]))

    result = []
    for key in sorted(entries.keys()):
        entry = entries[key]
        public = OrderedDict([
            ('Name', entry['Name']),
            ('ParameterIds', sorted(entry['ParameterIds'])),
            ('StorageTypes', sorted(entry['StorageTypes'])),
            ('SampleCount', entry['SampleCount']),
            ('WritableSampleCount', entry['WritableSampleCount']),
            ('ReadOnlySampleCount', entry['ReadOnlySampleCount']),
            ('Samples', entry['Samples'] if entry['Samples'] else None),
        ])
        result.append(public)
    return result


def normalize_text(value, collapse_whitespace=True):
    value = _text(value)
    if collapse_whitespace:
        value = re.sub(r'\s+', ' ', value)
    return value.strip()


def load_rules(path):
    handle = codecs.open(path, 'r', 'utf-8')
    try:
        data = json.load(handle)
    finally:
        handle.close()
    if isinstance(data, list):
        data = {'rules': data}
    if not isinstance(data, dict):
        raise ValueError(u'規則 JSON 必須是 object，或直接是 rule 陣列。')
    rules = data.get('rules')
    if not isinstance(rules, list) or not rules:
        raise ValueError(u'規則 JSON 必須包含非空 rules 陣列。')
    normalized_rules = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(u'第 {0} 條規則不是 object。'.format(index + 1))
        match = rule.get('match', rule.get('contains'))
        value = rule.get('value', rule.get('proposedValue'))
        if not _text(match) or value is None:
            raise ValueError(u'第 {0} 條規則缺少 match 或 value。'.format(index + 1))
        normalized_rules.append(OrderedDict([
            ('id', _text(rule.get('id')) or u'rule-{0}'.format(index + 1)),
            ('match', _text(match)),
            ('value', _text(value)),
        ]))
    data['rules'] = normalized_rules
    data.setdefault('targetParameter', u'')
    data.setdefault('matchField', u'name')
    data.setdefault('mode', u'fill_blank')
    data.setdefault('includeUnplaced', False)
    data.setdefault('caseInsensitive', True)
    data.setdefault('collapseWhitespace', True)
    return data


def _source_value(room, match_field, source_parameter):
    field = _text(match_field).lower() or u'name'
    if field == u'name':
        return room_name(room), None
    if field == u'number':
        return room_number(room), None
    if field == u'department':
        try:
            return parameter_value(room.get_Parameter(BuiltInParameter.ROOM_DEPARTMENT)), None
        except Exception:
            return u'', None
    if field == u'parameter':
        parameter, ambiguous = resolve_parameter(room, source_parameter)
        if ambiguous:
            return u'', u'來源參數名稱不唯一。'
        if parameter is None:
            return u'', u'找不到來源參數：{0}'.format(source_parameter)
        return parameter_value(parameter), None
    return u'', u'不支援的 matchField：{0}'.format(field)


def build_preview(rooms, config, doc=None):
    target_name = _text(config.get('targetParameter'))
    match_field = _text(config.get('matchField')) or u'name'
    source_parameter = _text(config.get('sourceParameter'))
    case_insensitive = bool(config.get('caseInsensitive', True))
    collapse_whitespace = bool(config.get('collapseWhitespace', True))
    rules = config.get('rules', [])
    plans = []
    for room in rooms:
        plan = OrderedDict([
            ('ElementId', _id_value(room)),
            ('Number', room_number(room)),
            ('Name', room_name(room)),
            ('Level', level_name(doc, room) if doc is not None else u''),
            ('SourceValue', u''),
            ('CurrentValue', u''),
            ('ProposedValue', u''),
            ('RuleIds', u''),
            ('Status', u'blocked'),
            ('Reason', u''),
        ])
        target, ambiguous = resolve_parameter(room, target_name)
        if ambiguous:
            plan['Reason'] = u'目標參數名稱不唯一。'
            plans.append(plan)
            continue
        if target is None:
            plan['Reason'] = u'找不到目標參數。'
            plans.append(plan)
            continue
        if target.IsReadOnly:
            plan['Reason'] = u'目標參數是唯讀的。'
            plans.append(plan)
            continue
        if target.StorageType != StorageType.String:
            plan['Reason'] = u'房間分類目前只支援 String 參數。'
            plans.append(plan)
            continue

        plan['CurrentValue'] = parameter_value(target)
        source, source_error = _source_value(room, match_field, source_parameter)
        if source_error:
            plan['Reason'] = source_error
            plans.append(plan)
            continue
        plan['SourceValue'] = source
        normalized_source = normalize_text(source, collapse_whitespace)
        matched = []
        for rule in rules:
            needle = normalize_text(rule.get('match'), collapse_whitespace)
            haystack = normalized_source
            if case_insensitive:
                needle = needle.lower()
                haystack = haystack.lower()
            if needle and haystack.find(needle) >= 0:
                matched.append(rule)
        plan['RuleIds'] = u', '.join([_text(rule.get('id')) for rule in matched])
        if not matched:
            plan['Status'] = u'unmatched'
            plan['Reason'] = u'沒有規則命中；保留原值。'
            plans.append(plan)
            continue
        values = []
        for rule in matched:
            value = _text(rule.get('value'))
            if value not in values:
                values.append(value)
        if len(values) > 1:
            plan['Status'] = u'conflict'
            plan['Reason'] = u'多條規則命中且 proposed value 不一致。'
            plans.append(plan)
            continue
        plan['ProposedValue'] = values[0]
        if plan['CurrentValue'] == plan['ProposedValue']:
            plan['Status'] = u'unchanged'
            plan['Reason'] = u'既有值已符合命中規則。'
        else:
            plan['Status'] = u'proposed'
            plan['Reason'] = u'規則命中，可依 fill_blank 或 overwrite 處理。'
        plans.append(plan)
    return plans


def public_summary(plans, total_rooms=None, applied=0, skipped=0):
    statuses = [plan.get('Status') for plan in plans]
    return OrderedDict([
        ('TotalRooms', total_rooms if total_rooms is not None else len(plans)),
        ('ReturnedPlans', len(plans)),
        ('Proposed', statuses.count(u'proposed') + statuses.count(u'applied')),
        ('AppliedChanges', applied),
        ('SkippedExisting', skipped),
        ('Unchanged', statuses.count(u'unchanged')),
        ('Unmatched', statuses.count(u'unmatched')),
        ('Conflicts', statuses.count(u'conflict')),
        ('Blocked', statuses.count(u'blocked')),
    ])


def apply_plans(doc, rooms, plans, target_name, mode):
    write_plans = []
    skipped = 0
    for plan in plans:
        if plan.get('Status') != u'proposed':
            continue
        if mode == u'fill_blank' and _text(plan.get('CurrentValue')):
            plan['Status'] = u'skipped_existing'
            plan['Reason'] = u'fill_blank 保留既有值。'
            skipped += 1
        else:
            write_plans.append(plan)

    applied = 0
    if write_plans:
        transaction = Transaction(doc, u'套用房間分類')
        transaction.Start()
        try:
            for plan in write_plans:
                room = None
                for candidate in rooms:
                    if _id_value(candidate) == plan.get('ElementId'):
                        room = candidate
                        break
                if room is None:
                    raise ValueError(u'找不到房間 ElementId：{0}'.format(plan.get('ElementId')))
                parameter, ambiguous = resolve_parameter(room, target_name)
                if ambiguous or parameter is None:
                    raise ValueError(u'目標參數無法唯一解析：{0}'.format(target_name))
                if parameter.IsReadOnly or parameter.StorageType != StorageType.String:
                    raise ValueError(u'目標參數不可寫入 String：{0}'.format(target_name))
                if not parameter.Set(plan.get('ProposedValue', u'')):
                    raise ValueError(u'Revit 未接受房間分類值：{0}'.format(plan.get('ElementId')))
                plan['Status'] = u'applied'
                plan['Reason'] = u'已在單一 Transaction 寫入。'
                applied += 1
            transaction.Commit()
        except Exception:
            transaction.RollBack()
            raise
    return applied, skipped


def write_json(path, payload):
    handle = codecs.open(path, 'w', 'utf-8')
    try:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        handle.close()


# ---------------------------------------------------------------------------
# Agile BIM door / window / wall governance helpers
# ---------------------------------------------------------------------------

def _element_parameter(element, requested_name):
    """Return ``(parameter, ambiguous)`` without guessing among same-name fields."""
    requested = _text(requested_name)
    if element is None or not requested:
        return None, False
    matches = []
    try:
        for parameter in element.Parameters:
            if parameter_name(parameter).lower() == requested.lower():
                matches.append(parameter)
    except Exception:
        matches = []
    if len(matches) > 1:
        return None, True
    if len(matches) == 1:
        return matches[0], False

    aliases = {
        u'mark': getattr(BuiltInParameter, 'ALL_MODEL_MARK', None),
        u'instance_mark': getattr(BuiltInParameter, 'ALL_MODEL_MARK', None),
        u'all_model_mark': getattr(BuiltInParameter, 'ALL_MODEL_MARK', None),
        u'type_mark': getattr(BuiltInParameter, 'ALL_MODEL_TYPE_MARK', None),
        u'all_model_type_mark': getattr(BuiltInParameter, 'ALL_MODEL_TYPE_MARK', None),
    }
    built_in = aliases.get(requested.lower())
    if built_in is not None:
        try:
            parameter = element.get_Parameter(built_in)
            if parameter is not None:
                return parameter, False
        except Exception:
            pass
    try:
        return element.LookupParameter(requested), False
    except Exception:
        return None, False


def _parameter_status(parameter):
    if parameter is None:
        return u'查無參數'
    try:
        if parameter.IsReadOnly:
            return u'唯讀'
        if parameter.StorageType != StorageType.String:
            return u'非文字參數'
    except Exception:
        return u'無法讀取參數狀態'
    return u'ok'


def _safe_room_value(room, property_name):
    if room is None:
        return u''
    try:
        return _text(getattr(room, property_name))
    except Exception:
        return u''


def _opening_is_curtain(record):
    if not record.get('host'):
        return bool(record.get('curtain'))
    try:
        wall_type = record['host'].WallType
        return wall_type is not None and wall_type.Kind == WallKind.Curtain
    except Exception:
        return bool(record.get('curtain'))


def _document_phases(doc):
    phases = []
    try:
        for phase in doc.Phases:
            phases.append(phase)
    except Exception:
        pass
    return phases


def _opening_phases(doc, opening, phases):
    """Put the opening's creation phase first, then use document phases."""
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
    """Resolve a phase-aware room without returning IronPython's indexer#.

    FromRoom and ToRoom are overloaded Revit properties.  IronPython 2.7
    exposes the parameterless form as an indexer object, so always call the
    generated get_* accessor with an explicit Phase.
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


def collect_agile_openings(doc, categories=None, level_filter=u'', element_ids=None,
                           include_curtain=False):
    """Collect live door/window evidence shared by the three governance paths."""
    categories = categories or ('doors', 'windows')
    wanted = set([_text(value).lower() for value in categories])
    normalized_wanted = set()
    for value in wanted:
        if value in ('door', 'doors'):
            normalized_wanted.add(u'門')
        if value in ('window', 'windows'):
            normalized_wanted.add(u'窗')
    allowed_ids = None
    if element_ids:
        allowed_ids = set([int(value) for value in element_ids])

    phases = _document_phases(doc)
    records = door_marks.collect(doc)
    result = []
    for record in records:
        if record.get('category') not in normalized_wanted:
            continue
        if allowed_ids is not None and record.get('id') not in allowed_ids:
            continue
        if level_filter and _text(record.get('level')).lower().find(
                _text(level_filter).lower()) < 0:
            continue
        record['host'] = None
        record['from_room'] = None
        record['to_room'] = None
        try:
            record['host'] = record['element'].Host
        except Exception:
            pass
        try:
            opening_phases = _opening_phases(doc, record['element'], phases)
            record['from_room'] = _opening_room(
                record['element'], 'FromRoom', opening_phases)
        except Exception:
            pass
        try:
            opening_phases = _opening_phases(doc, record['element'], phases)
            record['to_room'] = _opening_room(
                record['element'], 'ToRoom', opening_phases)
        except Exception:
            pass
        record['curtain'] = _opening_is_curtain(record)
        if record['curtain'] and not include_curtain:
            continue
        result.append(record)
    result.sort(key=lambda item: (
        float(item.get('level_elevation') or 0.0),
        0 if item.get('category') == u'門' else 1,
        _text(item.get('level')),
        _text(item.get('family_name')),
        _text(item.get('type_name')),
        int(item.get('id') or 0)))
    return result


def _group_records(records, target_scope):
    groups = {}
    for record in records:
        if target_scope == 'type':
            key = ('type', record.get('type_id'))
            target = record.get('symbol')
        else:
            key = ('instance', record.get('id'))
            target = record.get('element')
        if target is None:
            continue
        if key not in groups:
            groups[key] = {
                'key': key,
                'target': target,
                'records': [],
                'record': record,
            }
        groups[key]['records'].append(record)
    result = list(groups.values())
    result.sort(key=lambda group: (
        float(group['record'].get('level_elevation') or 0.0),
        0 if group['record'].get('category') == u'門' else 1,
        _text(group['record'].get('level')),
        _text(group['record'].get('family_name')),
        _text(group['record'].get('type_name')),
        int(group['record'].get('id') or 0)))
    return result


def _opening_source(record, match_field, source_parameter=u''):
    field = _text(match_field).lower() or u'type'
    if field == u'family':
        return _text(record.get('family_name'))
    if field == u'type':
        return _text(record.get('type_name'))
    if field == u'mark':
        parameter, unused = _element_parameter(record.get('element'), u'ALL_MODEL_MARK')
        return parameter_value(parameter)
    if field == u'from_room_name':
        return _safe_room_value(record.get('from_room'), 'Name')
    if field == u'to_room_name':
        return _safe_room_value(record.get('to_room'), 'Name')
    if field == u'room_name':
        return u' / '.join([value for value in [
            _safe_room_value(record.get('from_room'), 'Name'),
            _safe_room_value(record.get('to_room'), 'Name')]
            if value])
    if field == u'host_wall_type':
        try:
            return _text(record['host'].WallType.Name)
        except Exception:
            return u''
    if field == u'parameter':
        parameter, ambiguous = _element_parameter(
            record.get('element'), source_parameter)
        if parameter is not None and not ambiguous:
            return parameter_value(parameter)
        parameter, ambiguous = _element_parameter(
            record.get('symbol'), source_parameter)
        return parameter_value(parameter) if parameter is not None and not ambiguous else u''
    return u''


def _opening_group_source(group, match_field, source_parameter=u''):
    values = []
    for record in group.get('records', []):
        value = _opening_source(record, match_field, source_parameter)
        if value and value not in values:
            values.append(value)
    return u' / '.join(values)


def _match_rules(source, rules, case_insensitive=True, collapse_whitespace=True):
    source_value = normalize_text(source, collapse_whitespace)
    matched = []
    for rule in rules:
        needle = normalize_text(rule.get('match'), collapse_whitespace)
        haystack = source_value
        if case_insensitive:
            needle = needle.lower()
            haystack = haystack.lower()
        if needle and haystack.find(needle) >= 0:
            matched.append(rule)
    return matched


def _plan_public(plan, kind):
    if kind == 'door':
        record = plan['group']['record']
        payload = OrderedDict([
            ('ElementId', plan['ElementId']),
            ('TargetScope', plan['TargetScope']),
            ('Category', record.get('category')),
            ('Family', record.get('family_name')),
            ('Type', record.get('type_name')),
            ('Level', record.get('level')),
            ('InstanceCount', len(plan['group']['records'])),
            ('SourceValue', plan.get('SourceValue', u'')),
            ('CurrentValue', plan.get('CurrentValue', u'')),
            ('ProposedValue', plan.get('ProposedValue', u'')),
            ('RuleIds', plan.get('RuleIds', u'')),
            ('Status', plan.get('Status', u'')),
            ('Reason', plan.get('Reason', u'')),
            ('FromRoomName', _safe_room_value(record.get('from_room'), 'Name')),
            ('ToRoomName', _safe_room_value(record.get('to_room'), 'Name')),
            ('HostWallId', _id_value(record.get('host')) if record.get('host') else 0),
            ('IsCurtain', bool(record.get('curtain'))),
        ])
        return payload
    if kind == 'numbering':
        record = plan['group']['record']
        return OrderedDict([
            ('ElementId', plan['ElementId']),
            ('TargetScope', plan['TargetScope']),
            ('Category', record.get('category')),
            ('Family', record.get('family_name')),
            ('Type', record.get('type_name')),
            ('Level', record.get('level')),
            ('InstanceCount', len(plan['group']['records'])),
            ('Source', plan.get('Source', u'')),
            ('CurrentValue', plan.get('CurrentValue', u'')),
            ('ProposedValue', plan.get('ProposedValue', u'')),
            ('Status', plan.get('Status', u'')),
            ('Reason', plan.get('Reason', u'')),
            ('FromRoomName', _safe_room_value(record.get('from_room'), 'Name')),
            ('ToRoomName', _safe_room_value(record.get('to_room'), 'Name')),
            ('HostWallId', _id_value(record.get('host')) if record.get('host') else 0),
            ('IsCurtain', bool(record.get('curtain'))),
        ])
    return OrderedDict([
        ('ElementId', plan['ElementId']),
        ('TargetScope', plan['TargetScope']),
        ('Type', plan.get('TypeName', u'')),
        ('Function', plan.get('Function', u'')),
        ('Kind', plan.get('Kind', u'')),
        ('Level', plan.get('Level', u'')),
        ('RoomNames', plan.get('RoomNames', u'')),
        ('InstanceCount', len(plan['group']['records'])),
        ('SourceValue', plan.get('SourceValue', u'')),
        ('CurrentValue', plan.get('CurrentValue', u'')),
        ('ProposedValue', plan.get('ProposedValue', u'')),
        ('RuleIds', plan.get('RuleIds', u'')),
        ('Status', plan.get('Status', u'')),
        ('Reason', plan.get('Reason', u'')),
        ('IsCurtain', bool(plan['group']['record'].get('is_curtain'))),
    ])


def _classification_summary(plans, total, applied=0, skipped=0):
    statuses = [plan.get('Status') for plan in plans]
    return OrderedDict([
        ('Total', total),
        ('ReturnedPlans', len(plans)),
        ('Proposed', statuses.count(u'proposed') + statuses.count(u'applied')),
        ('AppliedChanges', applied),
        ('SkippedExisting', skipped),
        ('Unchanged', statuses.count(u'unchanged')),
        ('Unmatched', statuses.count(u'unmatched')),
        ('Conflicts', statuses.count(u'conflict')),
        ('Blocked', statuses.count(u'blocked')),
        ('Collisions', statuses.count(u'collision')),
    ])


def build_door_spec_preview(records, config):
    target_name = _text(config.get('targetParameter'))
    target_scope = _text(config.get('targetScope')).lower() or u'type'
    groups = _group_records(records, target_scope)
    plans = []
    rules = config.get('rules') or []
    case_insensitive = bool(config.get('caseInsensitive', True))
    collapse_whitespace = bool(config.get('collapseWhitespace', True))
    match_field = _text(config.get('matchField')).lower() or u'type'
    source_parameter = _text(config.get('sourceParameter'))
    for group in groups:
        record = group['record']
        target, ambiguous = _element_parameter(group['target'], target_name)
        status = u'ok' if not ambiguous else u'目標參數名稱不唯一。'
        if not ambiguous:
            status = _parameter_status(target)
        plan = {
            'group': group,
            'ElementId': _id_value(group['target']),
            'TargetScope': target_scope,
            'CurrentValue': parameter_value(target) if status == u'ok' else u'',
            'SourceValue': u'',
            'ProposedValue': u'',
            'RuleIds': u'',
            'Status': u'blocked' if status != u'ok' else u'pending',
            'Reason': status if status != u'ok' else u'',
        }
        if status != u'ok':
            plans.append(plan)
            continue
        plan['SourceValue'] = _opening_group_source(
            group, match_field, source_parameter)
        matched = _match_rules(
            plan['SourceValue'], rules, case_insensitive, collapse_whitespace)
        plan['RuleIds'] = u', '.join([_text(item.get('id')) for item in matched])
        values = []
        for item in matched:
            value = _text(item.get('value', item.get('proposedValue')))
            if value not in values:
                values.append(value)
        if not matched:
            plan['Status'] = u'unmatched'
            plan['Reason'] = (u'來源值空白或未取得；沒有規則命中。'
                              if not plan['SourceValue']
                              else u'沒有規則命中；保留原值。')
        elif len(values) > 1:
            plan['Status'] = u'conflict'
            plan['Reason'] = u'多條規則命中且 proposed value 不一致。'
        else:
            plan['ProposedValue'] = values[0]
            if plan['CurrentValue'] == plan['ProposedValue']:
                plan['Status'] = u'unchanged'
                plan['Reason'] = u'既有值已符合命中規則。'
            else:
                plan['Status'] = u'proposed'
                plan['Reason'] = u'規則命中，可依 fill_blank 或 overwrite 處理。'
        plans.append(plan)
    return plans


def apply_door_spec_plans(doc, plans, target_name, mode):
    writes = []
    skipped = 0
    for plan in plans:
        if plan.get('Status') != u'proposed':
            continue
        if mode == u'fill_blank' and _text(plan.get('CurrentValue')):
            plan['Status'] = u'skipped_existing'
            plan['Reason'] = u'fill_blank 保留既有值。'
            skipped += 1
        else:
            writes.append(plan)
    applied = 0
    if not writes:
        return applied, skipped
    transaction = Transaction(doc, u'套用門規格')
    transaction.Start()
    try:
        for plan in writes:
            parameter, ambiguous = _element_parameter(
                plan['group']['target'], target_name)
            if ambiguous or parameter is None:
                raise ValueError(u'門規格目標參數無法唯一解析：{0}'.format(plan['ElementId']))
            if _parameter_status(parameter) != u'ok':
                raise ValueError(u'門規格目標參數不可寫入：{0}'.format(plan['ElementId']))
            if not parameter.Set(plan.get('ProposedValue', u'')):
                raise ValueError(u'Revit 未接受門規格值：{0}'.format(plan['ElementId']))
            plan['Status'] = u'applied'
            plan['Reason'] = u'已在單一 Transaction 寫入。'
            applied += 1
        transaction.Commit()
    except Exception:
        transaction.RollBack()
        raise
    return applied, skipped


def _numbering_source(record, source, source_parameter, config):
    source = _text(source).lower()
    if source == u'type_mark':
        parameter, ambiguous = _element_parameter(
            record.get('symbol'), u'ALL_MODEL_TYPE_MARK')
        return parameter_value(parameter) if parameter is not None and not ambiguous else u''
    if source == u'type_name':
        return _text(record.get('type_name'))
    if source == u'parameter':
        parameter, ambiguous = _element_parameter(
            record.get('element'), source_parameter)
        if parameter is not None and not ambiguous:
            return parameter_value(parameter)
        parameter, ambiguous = _element_parameter(
            record.get('symbol'), source_parameter)
        return parameter_value(parameter) if parameter is not None and not ambiguous else u''
    if source == u'constant':
        return _text(config.get('constant'))
    return u''


def _numbering_bucket(record, sequence_scope):
    if sequence_scope == u'level':
        return _text(record.get('level'))
    if sequence_scope == u'category':
        return _text(record.get('category'))
    if sequence_scope == u'level_category':
        return u'{0}\x1f{1}'.format(
            _text(record.get('level')), _text(record.get('category')))
    return u'global'


def _sequence_value(record, config, number):
    prefix = _text(config.get('prefix'))
    if record.get('category') == u'門' and config.get('doorPrefix') is not None:
        prefix = _text(config.get('doorPrefix'))
    if record.get('category') == u'窗' and config.get('windowPrefix') is not None:
        prefix = _text(config.get('windowPrefix'))
    try:
        pad = int(config.get('pad', 0))
    except Exception:
        pad = 0
    number_text = _text(number)
    if pad > 0:
        number_text = number_text.zfill(min(pad, 12))
    return prefix + number_text


def build_door_window_numbering_preview(records, config, mode=u'fill_blank'):
    target_name = _text(config.get('targetParameter'))
    target_scope = _text(config.get('targetScope')).lower() or u'instance'
    source = _text(config.get('source')).lower() or u'sequence'
    sequence_scope = _text(config.get('sequenceScope')).lower() or u'category'
    groups = _group_records(records, target_scope)
    plans = []
    occupied = {}
    for group in groups:
        target, ambiguous = _element_parameter(group['target'], target_name)
        status = u'目標參數名稱不唯一。' if ambiguous else _parameter_status(target)
        current = parameter_value(target) if status == u'ok' else u''
        plan = {
            'group': group,
            'ElementId': _id_value(group['target']),
            'TargetScope': target_scope,
            'CurrentValue': current,
            'ProposedValue': u'',
            'Source': source,
            'ParameterStatus': status if status != u'ok' else u'',
            'Status': u'blocked' if status != u'ok' else u'pending',
            'Reason': status if status != u'ok' else u'',
        }
        plans.append(plan)
        if current:
            occupied[mark_identity.normalize_mark(current)] = group['key']

    if mode == u'overwrite':
        for key in list(occupied.keys()):
            if occupied[key] in [group['key'] for group in groups]:
                del occupied[key]

    claimed = {}
    counters = {}
    try:
        start = int(config.get('start', 1))
    except Exception:
        start = 1
    for plan in plans:
        if plan['ParameterStatus']:
            continue
        if mode == u'fill_blank' and plan['CurrentValue']:
            plan['Status'] = u'unchanged'
            plan['Reason'] = u'fill_blank 保留既有值。'
            continue
        record = plan['group']['record']
        if source == u'sequence':
            bucket = _numbering_bucket(record, sequence_scope)
            index = counters.get(bucket, 0)
            counters[bucket] = index + 1
            value = _sequence_value(record, config, start + index)
        else:
            value = _numbering_source(
                record, source, _text(config.get('sourceParameter')), config)
        plan['ProposedValue'] = value
        if not value:
            plan['Status'] = u'blocked'
            plan['Reason'] = u'來源值空白；沒有可寫入的編號。'
            continue
        normalized = mark_identity.normalize_mark(value)
        if mode == u'overwrite' and normalized == mark_identity.normalize_mark(
                plan['CurrentValue']):
            plan['Status'] = u'unchanged'
            plan['Reason'] = u'產生值與既有值相同。'
            continue
        if normalized in occupied:
            plan['Status'] = u'collision'
            plan['Reason'] = u'與既有或未選取門窗編號重複。'
            continue
        if normalized in claimed:
            plan['Status'] = u'collision'
            plan['Reason'] = u'本次產生的編號互相重複。'
            continue
        claimed[normalized] = plan['group']['key']
        plan['Status'] = u'proposed'
        plan['Reason'] = u'可依確認模式寫入。'
    return plans


def apply_door_window_numbering_plans(doc, plans, target_name):
    writes = [plan for plan in plans if plan.get('Status') == u'proposed']
    if not writes:
        return 0
    transaction = Transaction(doc, u'套用門窗編號')
    transaction.Start()
    applied = 0
    try:
        for plan in writes:
            parameter, ambiguous = _element_parameter(
                plan['group']['target'], target_name)
            if ambiguous or parameter is None or _parameter_status(parameter) != u'ok':
                raise ValueError(u'門窗編號目標參數不可寫入：{0}'.format(plan['ElementId']))
            if not parameter.Set(plan.get('ProposedValue', u'')):
                raise ValueError(u'Revit 未接受門窗編號：{0}'.format(plan['ElementId']))
            plan['Status'] = u'applied'
            plan['Reason'] = u'已在單一 Transaction 寫入。'
            applied += 1
        transaction.Commit()
    except Exception:
        transaction.RollBack()
        raise
    return applied


def _wall_room_index(doc):
    index = {}
    rooms = (FilteredElementCollector(doc)
             .OfCategory(BuiltInCategory.OST_Rooms)
             .WhereElementIsNotElementType()
             .ToElements())
    for room in rooms:
        if not isinstance(room, Room):
            continue
        try:
            loops = room.GetBoundarySegments(SpatialElementBoundaryOptions())
        except Exception:
            loops = None
        if loops is None:
            continue
        for loop in loops:
            if loop is None:
                continue
            for segment in loop:
                if segment is None:
                    continue
                try:
                    wall = doc.GetElement(segment.ElementId)
                except Exception:
                    wall = None
                if not isinstance(wall, Wall):
                    continue
                wall_id = _id_value(wall)
                index.setdefault(wall_id, [])
                if room not in index[wall_id]:
                    index[wall_id].append(room)
    return index


def collect_agile_walls(doc, level_filter=u'', wall_ids=None,
                        include_curtain=False, include_room_relations=True):
    requested = set([int(value) for value in wall_ids]) if wall_ids else None
    room_index = _wall_room_index(doc) if include_room_relations else {}
    walls = []
    elements = (FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Walls)
                .WhereElementIsNotElementType()
                .ToElements())
    for wall in elements:
        if not isinstance(wall, Wall):
            continue
        wall_id = _id_value(wall)
        if requested is not None and wall_id not in requested:
            continue
        try:
            wall_type = wall.WallType
        except Exception:
            wall_type = None
        if wall_type is None:
            continue
        try:
            is_curtain = wall_type.Kind == WallKind.Curtain
        except Exception:
            is_curtain = False
        if is_curtain and not include_curtain:
            continue
        level = u''
        elevation = 0.0
        try:
            level_element = doc.GetElement(wall.LevelId)
            level = _text(level_element.Name) if level_element is not None else u''
            elevation = float(level_element.Elevation)
        except Exception:
            pass
        if level_filter and level.lower().find(_text(level_filter).lower()) < 0:
            continue
        try:
            function = _text(wall_type.Function)
        except Exception:
            function = u''
        try:
            kind = _text(wall_type.Kind)
        except Exception:
            kind = u''
        walls.append({
            'element': wall,
            'type': wall_type,
            'id': wall_id,
            'type_id': _id_value(wall_type),
            'level': level,
            'level_elevation': elevation,
            'type_name': _text(wall_type.Name),
            'function': function,
            'kind': kind,
            'is_curtain': is_curtain,
            'rooms': room_index.get(wall_id, []),
        })
    walls.sort(key=lambda item: (
        float(item.get('level_elevation') or 0.0),
        _text(item.get('level')),
        _text(item.get('type_name')),
        int(item.get('id') or 0)))
    return walls


def _wall_source(record, match_field, source_parameter=u''):
    field = _text(match_field).lower() or u'type'
    if field == u'type':
        return _text(record.get('type_name'))
    if field == u'function':
        return _text(record.get('function'))
    if field == u'kind':
        return _text(record.get('kind'))
    if field == u'room_name':
        return u' / '.join([_safe_room_value(room, 'Name')
                            for room in record.get('rooms', [])
                            if _safe_room_value(room, 'Name')])
    if field == u'room_number':
        return u' / '.join([_safe_room_value(room, 'Number')
                            for room in record.get('rooms', [])
                            if _safe_room_value(room, 'Number')])
    if field == u'parameter':
        parameter, ambiguous = _element_parameter(
            record.get('element'), source_parameter)
        if parameter is not None and not ambiguous:
            return parameter_value(parameter)
        parameter, ambiguous = _element_parameter(
            record.get('type'), source_parameter)
        return parameter_value(parameter) if parameter is not None and not ambiguous else u''
    return u''


def _wall_group_source(group, match_field, source_parameter=u''):
    values = []
    for record in group.get('records', []):
        value = _wall_source(record, match_field, source_parameter)
        if value and value not in values:
            values.append(value)
    return u' / '.join(values)


def _wall_group_room_names(group):
    values = []
    for record in group.get('records', []):
        for room in record.get('rooms', []):
            value = _safe_room_value(room, 'Name')
            if value and value not in values:
                values.append(value)
    return u' / '.join(values)


def _wall_groups(records, target_scope):
    groups = {}
    for record in records:
        if target_scope == u'type':
            key = ('type', record.get('type_id'))
            target = record.get('type')
        else:
            key = ('instance', record.get('id'))
            target = record.get('element')
        if target is None:
            continue
        if key not in groups:
            groups[key] = {
                'key': key,
                'target': target,
                'records': [],
                'record': record,
            }
        groups[key]['records'].append(record)
    result = list(groups.values())
    result.sort(key=lambda group: (
        float(group['record'].get('level_elevation') or 0.0),
        _text(group['record'].get('level')),
        _text(group['record'].get('type_name')),
        int(group['record'].get('id') or 0)))
    return result


def build_wall_performance_preview(records, config):
    target_name = _text(config.get('targetParameter'))
    target_scope = _text(config.get('targetScope')).lower() or u'instance'
    match_field = _text(config.get('matchField')).lower() or u'type'
    source_parameter = _text(config.get('sourceParameter'))
    groups = _wall_groups(records, target_scope)
    rules = config.get('rules') or []
    case_insensitive = bool(config.get('caseInsensitive', True))
    collapse_whitespace = bool(config.get('collapseWhitespace', True))
    plans = []
    for group in groups:
        record = group['record']
        target, ambiguous = _element_parameter(group['target'], target_name)
        status = u'目標參數名稱不唯一。' if ambiguous else _parameter_status(target)
        current = parameter_value(target) if status == u'ok' else u''
        room_names = _wall_group_room_names(group)
        plan = {
            'group': group,
            'ElementId': _id_value(group['target']),
            'TargetScope': target_scope,
            'TypeName': _text(record.get('type_name')),
            'Function': _text(record.get('function')),
            'Kind': _text(record.get('kind')),
            'Level': _text(record.get('level')),
            'RoomNames': room_names,
            'CurrentValue': current,
            'SourceValue': u'',
            'ProposedValue': u'',
            'RuleIds': u'',
            'Status': u'blocked' if status != u'ok' else u'pending',
            'Reason': status if status != u'ok' else u'',
        }
        if status != u'ok':
            plans.append(plan)
            continue
        plan['SourceValue'] = _wall_group_source(
            group, match_field, source_parameter)
        matched = _match_rules(
            plan['SourceValue'], rules, case_insensitive, collapse_whitespace)
        plan['RuleIds'] = u', '.join([_text(item.get('id')) for item in matched])
        values = []
        for item in matched:
            value = _text(item.get('value', item.get('proposedValue')))
            if value not in values:
                values.append(value)
        if not matched:
            plan['Status'] = u'unmatched'
            plan['Reason'] = (u'來源值空白或未取得；沒有規則命中。'
                              if not plan['SourceValue']
                              else u'沒有規則命中；保留原值。')
        elif len(values) > 1:
            plan['Status'] = u'conflict'
            plan['Reason'] = u'多條規則命中且 proposed value 不一致。'
        else:
            plan['ProposedValue'] = values[0]
            if plan['CurrentValue'] == plan['ProposedValue']:
                plan['Status'] = u'unchanged'
                plan['Reason'] = u'既有值已符合命中規則。'
            else:
                plan['Status'] = u'proposed'
                plan['Reason'] = u'規則命中，可依 fill_blank 或 overwrite 處理。'
        plans.append(plan)
    return plans


def apply_wall_performance_plans(doc, plans, target_name, mode):
    writes = []
    skipped = 0
    for plan in plans:
        if plan.get('Status') != u'proposed':
            continue
        if mode == u'fill_blank' and _text(plan.get('CurrentValue')):
            plan['Status'] = u'skipped_existing'
            plan['Reason'] = u'fill_blank 保留既有值。'
            skipped += 1
        else:
            writes.append(plan)
    if not writes:
        return 0, skipped
    transaction = Transaction(doc, u'套用牆性能分類')
    transaction.Start()
    applied = 0
    try:
        for plan in writes:
            parameter, ambiguous = _element_parameter(
                plan['group']['target'], target_name)
            if ambiguous or parameter is None or _parameter_status(parameter) != u'ok':
                raise ValueError(u'牆性能分類目標參數不可寫入：{0}'.format(plan['ElementId']))
            if not parameter.Set(plan.get('ProposedValue', u'')):
                raise ValueError(u'Revit 未接受牆性能分類：{0}'.format(plan['ElementId']))
            plan['Status'] = u'applied'
            plan['Reason'] = u'已在單一 Transaction 寫入。'
            applied += 1
        transaction.Commit()
    except Exception:
        transaction.RollBack()
        raise
    return applied, skipped
