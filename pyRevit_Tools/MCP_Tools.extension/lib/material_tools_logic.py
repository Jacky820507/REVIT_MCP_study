# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure data transformations shared by the material tools.

This module deliberately has no Revit or pyRevit dependency.  The buttons are
responsible for collecting primitive values from Revit; these helpers filter,
validate, aggregate, and shape those values for the UI and Excel writer.
"""

import unicodedata

try:
    from xlsx_xml import STYLE_DECIMAL, STYLE_INT
except ImportError:
    # Keep offline tests and copied deployments importable even when the
    # OpenXML helper is not beside this module.  These are xlsx_xml's stable
    # cellXfs indices.
    STYLE_INT = 2
    STYLE_DECIMAL = 3

try:
    _TEXT_TYPE = unicode  # noqa: F821  (Python 2 only)
    _STRING_TYPES = (basestring,)  # noqa: F821  (Python 2 only)
except NameError:
    _TEXT_TYPE = str
    _STRING_TYPES = (str, bytes)


SURFACE_KINDS = (u'floor', u'wall', u'ceiling', u'other')
UNKNOWN_MATERIAL_NAME = u'(未指定材質)'


def _to_text(value):
    if value is None:
        return u''
    if isinstance(value, _TEXT_TYPE):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode('utf-8')
        except (UnicodeDecodeError, AttributeError):
            return value.decode('utf-8', 'replace')
    try:
        return _TEXT_TYPE(value)
    except (TypeError, ValueError):
        return u''


def normalize_text(value):
    """Return a Unicode, NFKC-normalized, case-insensitive comparison key."""
    text = _to_text(value)
    try:
        text = unicodedata.normalize('NFKC', text)
    except (TypeError, ValueError):
        pass
    return text.strip().lower()


def _record_value(record, names, default=None):
    if record is None:
        return default
    for name in names:
        try:
            if name in record:
                return record[name]
        except (TypeError, KeyError):
            pass
        try:
            return getattr(record, name)
        except (AttributeError, TypeError):
            pass
    return default


def _number(value, default=0.0):
    if value is None or value == u'':
        return default
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if result != result:  # NaN must not poison reconciliation totals.
        return default
    return result


def _integer(value, default=0):
    if value is None or value == u'':
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        try:
            return int(float(value))
        except (TypeError, ValueError, OverflowError):
            return default


def _boolean(value):
    if isinstance(value, _STRING_TYPES):
        return normalize_text(value) in (
            u'1', u'true', u'yes', u'y', u'是', u'估算', u'estimated')
    return bool(value)


def _as_list(value):
    if value is None or value == u'':
        return []
    if isinstance(value, _STRING_TYPES):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _identity_key(value):
    return normalize_text(value)


def _append_unique(values, value):
    key = _identity_key(value)
    for existing in values:
        if _identity_key(existing) == key:
            return
    values.append(value)


def _extend_unique(values, additions):
    for value in _as_list(additions):
        if value is None or _to_text(value).strip() == u'':
            continue
        _append_unique(values, value)


def _warning_text(value):
    if isinstance(value, dict):
        value = _record_value(
            value,
            (u'message', u'warning', u'警告', u'error', u'reason'),
            u'')
    return _to_text(value)


def _add_warning(warnings, message):
    text = _warning_text(message).strip()
    if not text:
        return
    _append_unique(warnings, text)


def _material_name(record):
    return _to_text(_record_value(record, (u'name', u'material_name'), u''))


def _material_id(record):
    return _record_value(record, (u'id', u'material_id'), None)


def _material_class(record):
    return _record_value(
        record,
        (u'material_class', u'class_name', u'class', u'classification',
         u'description_class', u'material_category', u'category'),
        u'')


def filter_materials(materials, search_text=u'', usage_filter='all',
                     class_filter='all'):
    """Filter material records without mutating or reordering them.

    ``unused`` means only that this scan found neither instance usage nor a
    type-level reference.  It is intentionally not a deletion-safety verdict.
    """
    result = []
    query = normalize_text(search_text)
    usage_key = normalize_text(usage_filter)
    class_key = normalize_text(class_filter)
    all_values = (u'', u'all', u'*', u'全部', u'全部分類', u'(全部分類)')
    used_values = (u'used', u'使用中', u'使用中的', u'顯示使用中的')
    unused_values = (u'unused', u'未使用', u'未使用的', u'顯示未使用的')

    for material in materials or []:
        usage_count = _integer(_record_value(
            material, (u'usage_count', u'used_count'), 0), 0)
        type_count = _integer(_record_value(
            material, (u'type_reference_count', u'type_ref_count'), 0), 0)
        is_used = usage_count > 0 or type_count > 0

        if usage_key in used_values and not is_used:
            continue
        if usage_key in unused_values and is_used:
            continue

        if class_key not in all_values:
            if normalize_text(_material_class(material)) != class_key:
                continue

        if query:
            searchable = (
                _material_name(material),
                _material_id(material),
                _material_class(material),
                _record_value(material, (u'description',), u''),
                _record_value(material, (u'mark',), u''),
                _record_value(material, (u'manufacturer',), u''),
                _record_value(material, (u'model',), u''),
            )
            haystack = u'\n'.join([normalize_text(value)
                                   for value in searchable])
            if query not in haystack:
                continue
        result.append(material)
    return result


def _project_name_values(project_names):
    values = []
    for value in project_names or []:
        if isinstance(value, _STRING_TYPES):
            values.append(_to_text(value))
        else:
            values.append(_to_text(_record_value(
                value, (u'name', u'material_name', u'old_name'), u'')))
    return values


def validate_rename_items(items, project_names=None):
    """Validate a material rename batch before any Revit transaction starts."""
    errors = []
    warnings = []
    old_by_name = {}
    new_by_name = {}

    for item in items or []:
        old_name = _to_text(_record_value(item, (u'old_name',), u''))
        new_name = _to_text(_record_value(item, (u'new_name',), u''))
        old_key = normalize_text(old_name)
        new_key = normalize_text(new_name)
        if old_key:
            old_by_name.setdefault(old_key, []).append(item)
        if not new_name.strip():
            _add_warning(errors, u'材質「{0}」的新名稱不可為空白。'.format(
                old_name or _to_text(_record_value(item, (u'id',), u''))))
            continue
        new_by_name.setdefault(new_key, []).append(item)

    for new_key in sorted(new_by_name.keys()):
        collisions = new_by_name[new_key]
        if len(collisions) > 1:
            names = [u'「{0}」'.format(_to_text(_record_value(
                item, (u'old_name',), u''))) for item in collisions]
            _add_warning(errors, u'批次結果重名：{0} 都會成為「{1}」。'.format(
                u'、'.join(names), _to_text(_record_value(
                    collisions[0], (u'new_name',), u''))))

    # Revit requires unique names throughout a sequence of Set operations.
    # Renaming into another selected material's current name therefore needs a
    # temporary-name algorithm; the first release blocks it explicitly.
    for item in items or []:
        old_key = normalize_text(_record_value(item, (u'old_name',), u''))
        new_key = normalize_text(_record_value(item, (u'new_name',), u''))
        if new_key and new_key != old_key and new_key in old_by_name:
            target_items = old_by_name[new_key]
            is_other = False
            for target in target_items:
                if target is not item:
                    is_other = True
                    break
            if is_other:
                _add_warning(
                    errors,
                    u'批次名稱交換或佔用目前名稱：材質「{0}」不可直接改為「{1}」。'.format(
                        _to_text(_record_value(item, (u'old_name',), u'')),
                        _to_text(_record_value(item, (u'new_name',), u''))))

    selected_old_keys = set(old_by_name.keys())
    external_names = {}
    for project_name in _project_name_values(project_names):
        key = normalize_text(project_name)
        if key and key not in selected_old_keys:
            external_names[key] = project_name
    for item in items or []:
        new_name = _to_text(_record_value(item, (u'new_name',), u''))
        new_key = normalize_text(new_name)
        if new_key and new_key in external_names:
            _add_warning(errors, u'新名稱「{0}」與專案中未選取的材質重名。'.format(
                new_name))

    changed = False
    for item in items or []:
        if _to_text(_record_value(item, (u'old_name',), u'')) != _to_text(
                _record_value(item, (u'new_name',), u'')):
            changed = True
            break
    if items and not changed:
        _add_warning(warnings, u'沒有材質名稱需要變更。')
    return {u'errors': errors, u'warnings': warnings}


def build_rename_preview(materials, prefix=u'', suffix=u'', find_text=u'',
                         replace_text=u'', project_names=None):
    """Build and validate rename items without changing the Revit document."""
    prefix = _to_text(prefix)
    suffix = _to_text(suffix)
    find_text = _to_text(find_text)
    replace_text = _to_text(replace_text)
    items = []
    for material in materials or []:
        old_name = _material_name(material)
        middle = old_name
        if find_text:
            middle = middle.replace(find_text, replace_text)
        items.append({
            u'id': _material_id(material),
            u'old_name': old_name,
            u'new_name': prefix + middle + suffix,
        })
    validation = validate_rename_items(items, project_names)
    return {
        u'items': items,
        u'errors': validation[u'errors'],
        u'warnings': validation[u'warnings'],
    }


def _canonical_surface(value, warnings):
    surface = normalize_text(value)
    if surface in SURFACE_KINDS:
        return surface
    label = _to_text(value).strip() or u'(空白)'
    _add_warning(warnings, u'未知表面類型「{0}」已歸入 other。'.format(label))
    return u'other'


def _surface_filter(surface_keys):
    if surface_keys is None:
        return set(SURFACE_KINDS)
    if isinstance(surface_keys, _STRING_TYPES):
        surface_keys = [surface_keys]
    result = set()
    for value in surface_keys or []:
        surface = normalize_text(value)
        if surface in SURFACE_KINDS:
            result.add(surface)
    return result


def _canonical_record(record, global_warnings):
    local_warnings = []
    for warning in _as_list(_record_value(record, (u'warnings',), [])):
        _add_warning(local_warnings, warning)
    surface = _canonical_surface(_record_value(
        record, (u'surface_kind',), u'other'), local_warnings)
    material_name = _to_text(_record_value(
        record, (u'material_name', u'name'), u'')).strip()
    if not material_name:
        material_name = UNKNOWN_MATERIAL_NAME
        _add_warning(local_warnings, u'房間材質明細含未指定材質。')

    area_value = _record_value(record, (u'area_m2',), 0.0)
    area = _number(area_value, 0.0)
    if area_value not in (None, u''):
        try:
            raw_number = float(area_value)
            if raw_number != raw_number:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            _add_warning(local_warnings, u'無法解析面積「{0}」，已以 0 計。'.format(
                _to_text(area_value)))

    row = {
        u'room_id': _record_value(record, (u'room_id',), None),
        u'level': _to_text(_record_value(record, (u'level',), u'')),
        u'room_number': _to_text(_record_value(
            record, (u'room_number',), u'')),
        u'room_name': _to_text(_record_value(record, (u'room_name',), u'')),
        u'surface_kind': surface,
        u'material_id': _record_value(record, (u'material_id',), None),
        u'material_name': material_name,
        u'material_class': _to_text(_record_value(
            record, (u'material_class', u'class_name', u'class'), u'')),
        u'material_source': _to_text(_record_value(
            record, (u'material_source',), u'')),
        u'area_m2': area,
        u'face_count': _integer(_record_value(record, (u'face_count',), 0), 0),
        u'boundary_category': _to_text(_record_value(
            record, (u'boundary_category',), u'')),
        u'boundary_element_ids': [],
        u'method': _to_text(_record_value(record, (u'method',), u'')),
        u'estimated': _boolean(_record_value(record, (u'estimated',), False)),
        u'warnings': local_warnings,
    }
    _extend_unique(row[u'boundary_element_ids'], _record_value(
        record, (u'boundary_element_ids',), []))
    for warning in local_warnings:
        _add_warning(global_warnings, warning)
    return row


def _room_identity(row):
    room_id = row[u'room_id']
    if room_id is not None and _to_text(room_id).strip() != u'':
        return (u'id', normalize_text(room_id))
    return (u'fields', normalize_text(row[u'level']),
            normalize_text(row[u'room_number']),
            normalize_text(row[u'room_name']))


def _detail_key(row):
    return (_room_identity(row), row[u'surface_kind'],
            normalize_text(row[u'material_id']),
            normalize_text(row[u'material_name']),
            normalize_text(row[u'material_source']),
            normalize_text(row[u'method']))


def _detail_sort_key(row):
    surface_order = dict((name, index) for index, name in enumerate(
        SURFACE_KINDS))
    return (normalize_text(row[u'level']),
            normalize_text(row[u'room_number']),
            normalize_text(row[u'room_name']),
            surface_order.get(row[u'surface_kind'], 99),
            normalize_text(row[u'material_name']),
            normalize_text(row[u'material_source']),
            normalize_text(row[u'method']))


def _merge_detail(target, row):
    target[u'area_m2'] += row[u'area_m2']
    target[u'face_count'] += row[u'face_count']
    target[u'estimated'] = target[u'estimated'] or row[u'estimated']
    categories = []
    _extend_unique(categories, target[u'boundary_category'].split(u'；'))
    _extend_unique(categories, row[u'boundary_category'].split(u'；'))
    target[u'boundary_category'] = u'；'.join(categories)
    _extend_unique(target[u'boundary_element_ids'], row[u'boundary_element_ids'])
    if not target[u'material_class'] and row[u'material_class']:
        target[u'material_class'] = row[u'material_class']
    for warning in row[u'warnings']:
        _add_warning(target[u'warnings'], warning)


def group_room_records(records, surface_keys=None):
    """Aggregate canonical room/material face records in three views.

    All area values remain unrounded floats.  The three returned views are
    derived from the same detail rows so their totals reconcile.
    """
    warnings = []
    allowed_surfaces = _surface_filter(surface_keys)
    detail_by_key = {}
    detail_order = []

    for source_record in records or []:
        row = _canonical_record(source_record, warnings)
        if row[u'surface_kind'] not in allowed_surfaces:
            continue
        key = _detail_key(row)
        if key not in detail_by_key:
            detail_by_key[key] = row
            detail_order.append(key)
        else:
            _merge_detail(detail_by_key[key], row)

    detail = [detail_by_key[key] for key in detail_order]
    detail.sort(key=_detail_sort_key)

    rooms_by_key = {}
    rooms_order = []
    materials_by_key = {}
    materials_order = []
    material_room_keys = {}

    for row in detail:
        room_key = _room_identity(row)
        if room_key not in rooms_by_key:
            rooms_by_key[room_key] = {
                u'room_id': row[u'room_id'],
                u'level': row[u'level'],
                u'room_number': row[u'room_number'],
                u'room_name': row[u'room_name'],
                u'floor_area_m2': 0.0,
                u'wall_area_m2': 0.0,
                u'ceiling_area_m2': 0.0,
                u'other_area_m2': 0.0,
                u'total_area_m2': 0.0,
                u'face_count': 0,
                u'estimated': False,
                u'warnings': [],
            }
            rooms_order.append(room_key)
        room = rooms_by_key[room_key]
        room[row[u'surface_kind'] + u'_area_m2'] += row[u'area_m2']
        room[u'total_area_m2'] += row[u'area_m2']
        room[u'face_count'] += row[u'face_count']
        room[u'estimated'] = room[u'estimated'] or row[u'estimated']
        for warning in row[u'warnings']:
            _add_warning(room[u'warnings'], warning)

        material_key = (normalize_text(row[u'material_id']),
                        normalize_text(row[u'material_name']),
                        row[u'surface_kind'])
        if material_key not in materials_by_key:
            materials_by_key[material_key] = {
                u'material_id': row[u'material_id'],
                u'material_name': row[u'material_name'],
                u'material_class': row[u'material_class'],
                u'surface_kind': row[u'surface_kind'],
                u'area_m2': 0.0,
                u'room_count': 0,
                u'room_ids': [],
                u'face_count': 0,
                u'boundary_element_ids': [],
                u'material_sources': [],
                u'methods': [],
                u'estimated': False,
                u'warnings': [],
            }
            materials_order.append(material_key)
            material_room_keys[material_key] = set()
        material = materials_by_key[material_key]
        if not material[u'material_class'] and row[u'material_class']:
            material[u'material_class'] = row[u'material_class']
        material[u'area_m2'] += row[u'area_m2']
        material[u'face_count'] += row[u'face_count']
        material[u'estimated'] = material[u'estimated'] or row[u'estimated']
        _extend_unique(material[u'room_ids'], row[u'room_id'])
        _extend_unique(material[u'boundary_element_ids'],
                       row[u'boundary_element_ids'])
        _extend_unique(material[u'material_sources'], row[u'material_source'])
        _extend_unique(material[u'methods'], row[u'method'])
        for warning in row[u'warnings']:
            _add_warning(material[u'warnings'], warning)
        material_room_keys[material_key].add(room_key)

    rooms = [rooms_by_key[key] for key in rooms_order]
    rooms.sort(key=lambda row: (normalize_text(row[u'level']),
                                normalize_text(row[u'room_number']),
                                normalize_text(row[u'room_name'])))
    materials = [materials_by_key[key] for key in materials_order]
    for material_key in materials_order:
        materials_by_key[material_key][u'room_count'] = len(
            material_room_keys[material_key])
    surface_order = dict((name, index) for index, name in enumerate(
        SURFACE_KINDS))
    materials.sort(key=lambda row: (
        normalize_text(row[u'material_name']),
        surface_order.get(row[u'surface_kind'], 99)))

    detail_total = sum([row[u'area_m2'] for row in detail])
    room_total = sum([row[u'total_area_m2'] for row in rooms])
    material_total = sum([row[u'area_m2'] for row in materials])
    tolerance = max(1.0, abs(detail_total)) * 1e-10
    if abs(detail_total - room_total) > tolerance:
        _add_warning(warnings, u'依房間彙總與明細總面積不一致。')
    if abs(detail_total - material_total) > tolerance:
        _add_warning(warnings, u'依材質彙總與明細總面積不一致。')

    return {
        u'detail': detail,
        u'rooms': rooms,
        u'materials': materials,
        u'warnings': warnings,
        u'total_area_m2': detail_total,
    }


def _color_text(value):
    if value is None or value == u'':
        return u''
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return u'{0}, {1}, {2}'.format(value[0], value[1], value[2])
    red = _record_value(value, (u'Red', u'red', u'r'), None)
    green = _record_value(value, (u'Green', u'green', u'g'), None)
    blue = _record_value(value, (u'Blue', u'blue', u'b'), None)
    if red is not None and green is not None and blue is not None:
        return u'{0}, {1}, {2}'.format(red, green, blue)
    return _to_text(value)


def _joined(values, delimiter=u', '):
    return delimiter.join([_to_text(value) for value in _as_list(values)
                           if value is not None and
                           _to_text(value).strip() != u''])


def _display_area(value, digits=3):
    return round(_number(value, 0.0), digits)


def _warning_rows(explicit_warnings, collections):
    entries = []
    for warning in explicit_warnings or []:
        if isinstance(warning, dict):
            source = _to_text(_record_value(warning, (u'source', u'來源'), u''))
            message = _warning_text(warning)
        else:
            source = u''
            message = _warning_text(warning)
        if message.strip():
            entries.append((source, message))
    for source, rows in collections:
        for row in rows or []:
            for warning in _as_list(_record_value(row, (u'warnings',), [])):
                message = _warning_text(warning)
                if message.strip():
                    entries.append((_to_text(source), message))
    unique = []
    seen = set()
    for source, message in entries:
        key = (normalize_text(source), normalize_text(message))
        if key in seen:
            continue
        seen.add(key)
        unique.append([source, message])
    if not unique:
        unique.append([u'', u'無'])
    return [[u'來源', u'警告']] + unique


def material_workbook(materials, usages, warnings=None):
    """Return workbook sheets for ``xlsx_writer.write_workbook``."""
    material_rows = [[
        u'材質 ID', u'材質名稱', u'說明分類', u'材料類別', u'說明', u'標記',
        u'顏色 RGB', u'透明度', u'光澤度', u'平滑度', u'使用數',
        u'類型參照數', u'外觀資產 ID']]
    for material in materials or []:
        material_rows.append([
            _material_id(material),
            _material_name(material),
            _record_value(material, (u'material_class', u'class_name',
                                     u'class', u'classification'), u''),
            _record_value(material, (u'material_category',
                                     u'description_class'), u''),
            _record_value(material, (u'description',), u''),
            _record_value(material, (u'mark',), u''),
            _color_text(_record_value(material, (u'color_rgb', u'color'), u'')),
            _integer(_record_value(material, (u'transparency',), 0), 0),
            _integer(_record_value(material, (u'shininess', u'glossiness'), 0), 0),
            _integer(_record_value(material, (u'smoothness',), 0), 0),
            _integer(_record_value(material, (u'usage_count', u'used_count'), 0), 0),
            _integer(_record_value(material, (u'type_reference_count',
                                             u'type_ref_count'), 0), 0),
            _record_value(material, (u'appearance_asset_id',
                                     u'appearance_id'), u''),
        ])

    usage_rows = [[
        u'材質 ID', u'材質名稱', u'元素 ID', u'類別', u'族群', u'類型 ID',
        u'類型名稱', u'來源', u'面積 (m²)', u'體積 (m³)', u'槽位',
        u'圖層索引', u'塗漆']]
    for usage in usages or []:
        usage_rows.append([
            _record_value(usage, (u'material_id', u'id'), None),
            _record_value(usage, (u'material_name', u'name'), u''),
            _record_value(usage, (u'element_id',), None),
            _record_value(usage, (u'category', u'category_name'), u''),
            _record_value(usage, (u'family', u'family_name'), u''),
            _record_value(usage, (u'type_id',), None),
            _record_value(usage, (u'type_name',), u''),
            _record_value(usage, (u'source_kind', u'source',
                                  u'material_source'), u''),
            _display_area(_record_value(usage, (u'area_m2',), 0.0), 3),
            _display_area(_record_value(usage, (u'volume_m3',), 0.0), 6),
            _record_value(usage, (u'slot', u'parameter_name'), u''),
            _record_value(usage, (u'layer_index',), u''),
            u'是' if _boolean(_record_value(usage, (u'painted',), False)) else u'否',
        ])

    warning_rows = _warning_rows(warnings, (
        (u'材質庫', materials or []), (u'使用元素', usages or [])))
    return [
        (u'材質庫', material_rows, {
            u'freeze': 1,
            u'widths': [12, 24, 18, 18, 28, 16, 16, 10, 10, 10, 10, 12, 16],
            u'formats': {1: STYLE_INT, 8: STYLE_INT, 9: STYLE_INT,
                         10: STYLE_INT, 11: STYLE_INT, 12: STYLE_INT,
                         13: STYLE_INT},
        }),
        (u'使用元素', usage_rows, {
            u'freeze': 1,
            u'widths': [12, 24, 12, 20, 20, 12, 24, 18, 14, 14, 18, 12, 10],
            u'formats': {1: STYLE_INT, 3: STYLE_INT, 6: STYLE_INT,
                         9: STYLE_DECIMAL, 10: STYLE_DECIMAL,
                         12: STYLE_INT},
        }),
        (u'警告', warning_rows, {
            u'freeze': 1, u'widths': [18, 80], u'formats': {}}),
    ]


def room_workbook(records, warnings=None):
    """Return detail and reconciled room/material summary workbook sheets."""
    grouped = group_room_records(records)
    detail_rows = [[
        u'房間 ID', u'樓層', u'房號', u'房間名稱', u'表面類型', u'材質 ID',
        u'材質名稱', u'材質來源', u'面積 (m²)', u'面數', u'邊界類別',
        u'邊界元素 ID', u'方法', u'估算', u'警告']]
    for row in grouped[u'detail']:
        detail_rows.append([
            row[u'room_id'], row[u'level'], row[u'room_number'], row[u'room_name'],
            row[u'surface_kind'], row[u'material_id'], row[u'material_name'],
            row[u'material_source'], _display_area(row[u'area_m2']),
            row[u'face_count'], row[u'boundary_category'],
            _joined(row[u'boundary_element_ids']), row[u'method'],
            u'是' if row[u'estimated'] else u'否',
            _joined(row[u'warnings'], u'；')])

    room_rows = [[
        u'房間 ID', u'樓層', u'房號', u'房間名稱', u'地面 (m²)', u'牆壁 (m²)',
        u'天花板 (m²)', u'其他 (m²)', u'合計 (m²)', u'面數', u'估算', u'警告']]
    for row in grouped[u'rooms']:
        room_rows.append([
            row[u'room_id'], row[u'level'], row[u'room_number'], row[u'room_name'],
            _display_area(row[u'floor_area_m2']),
            _display_area(row[u'wall_area_m2']),
            _display_area(row[u'ceiling_area_m2']),
            _display_area(row[u'other_area_m2']),
            _display_area(row[u'total_area_m2']), row[u'face_count'],
            u'是' if row[u'estimated'] else u'否',
            _joined(row[u'warnings'], u'；')])

    material_rows = [[
        u'材質 ID', u'材質名稱', u'說明分類', u'表面類型', u'面積 (m²)',
        u'房間數', u'房間 ID', u'面數', u'邊界元素 ID', u'材質來源', u'方法',
        u'估算', u'警告']]
    for row in grouped[u'materials']:
        material_rows.append([
            row[u'material_id'], row[u'material_name'], row[u'material_class'],
            row[u'surface_kind'], _display_area(row[u'area_m2']), row[u'room_count'],
            _joined(row[u'room_ids']), row[u'face_count'],
            _joined(row[u'boundary_element_ids']),
            _joined(row[u'material_sources'], u'；'),
            _joined(row[u'methods'], u'；'),
            u'是' if row[u'estimated'] else u'否',
            _joined(row[u'warnings'], u'；')])

    combined_warnings = list(warnings or [])
    combined_warnings.extend(grouped[u'warnings'])
    warning_rows = _warning_rows(combined_warnings, ())
    return [
        (u'房間材質明細', detail_rows, {
            u'freeze': 1,
            u'widths': [12, 12, 12, 22, 12, 12, 24, 18, 14, 10, 20, 34,
                        18, 10, 45],
            u'formats': {1: STYLE_INT, 6: STYLE_INT, 9: STYLE_DECIMAL,
                         10: STYLE_INT},
        }),
        (u'依房間彙總', room_rows, {
            u'freeze': 1,
            u'widths': [12, 12, 12, 24, 14, 14, 14, 14, 14, 10, 10, 45],
            u'formats': {1: STYLE_INT, 5: STYLE_DECIMAL, 6: STYLE_DECIMAL,
                         7: STYLE_DECIMAL, 8: STYLE_DECIMAL,
                         9: STYLE_DECIMAL, 10: STYLE_INT},
        }),
        (u'依材質彙總', material_rows, {
            u'freeze': 1,
            u'widths': [12, 24, 18, 12, 14, 10, 30, 10, 36, 24, 24, 10, 45],
            u'formats': {1: STYLE_INT, 5: STYLE_DECIMAL, 6: STYLE_INT,
                         8: STYLE_INT},
        }),
        (u'警告', warning_rows, {
            u'freeze': 1, u'widths': [18, 80], u'formats': {}}),
    ]
