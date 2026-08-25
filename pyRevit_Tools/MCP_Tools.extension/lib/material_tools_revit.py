# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Revit-facing adapter for the material tools.

The UI passes and receives dictionaries containing only primitive values.  All
Revit API access lives here so the sibling logic module remains testable
without Revit.  This first version intentionally does not create, duplicate,
delete, or edit appearance assets.
"""

import unicodedata

try:
    from pyrevit import DB
except Exception:
    DB = None

try:
    _TEXT_TYPE = unicode  # noqa: F821  (Python 2 only)
    _STRING_TYPES = (basestring,)  # noqa: F821  (Python 2 only)
except NameError:
    _TEXT_TYPE = str
    _STRING_TYPES = (str, bytes)


SQFT_TO_SQM = 0.09290304
CUFT_TO_CUM = 0.028316846592

ALLOWED_PATCH_FIELDS = (
    u'material_class',
    u'material_category',
    u'description',
    u'color',
    u'transparency',
    u'shininess',
    u'smoothness',
    u'use_render_appearance',
    u'surface_foreground_pattern_id',
    u'surface_foreground_color',
    u'cut_foreground_pattern_id',
    u'cut_foreground_color',
)


def _text(value):
    if value is None:
        return u''
    if isinstance(value, _TEXT_TYPE):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode('utf-8')
        except Exception:
            return value.decode('utf-8', 'replace')
    try:
        return _TEXT_TYPE(value)
    except Exception:
        return u''


def _normal(value):
    value = _text(value)
    try:
        value = unicodedata.normalize('NFKC', value)
    except Exception:
        pass
    return value.strip().lower()


def _value(record, names, default=None):
    if record is None:
        return default
    for name in names:
        try:
            if isinstance(record, dict) and name in record:
                return record[name]
        except Exception:
            pass
        try:
            value = getattr(record, name)
            if value is not None:
                return value
        except Exception:
            pass
    return default


def _integer(value, default=0):
    try:
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return default


def _float(value, default=0.0):
    try:
        result = float(value)
        if result != result:
            return default
        return result
    except Exception:
        return default


def _truthy(value):
    if isinstance(value, _STRING_TYPES):
        return _normal(value) in (u'1', u'true', u'yes', u'y', u'是', u'on')
    return bool(value)


def _items(value):
    if value is None:
        return []
    if isinstance(value, _STRING_TYPES):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return list(value)
    try:
        return list(value)
    except Exception:
        return [value]


def id_value(value, default=-1):
    """Return an int for both pre-2024 and 64-bit Revit ElementId values."""
    if value is None:
        return default
    for attribute in (u'Value', u'IntegerValue'):
        try:
            return int(getattr(value, attribute))
        except Exception:
            pass
    try:
        return int(value)
    except Exception:
        return default


def _require_revit():
    if DB is None:
        raise RuntimeError(
            u'material_tools_revit 必須在載入 pyRevit/Revit API 的程序內執行。')


def _element_id(value):
    _require_revit()
    if value is None:
        return DB.ElementId.InvalidElementId
    try:
        if value.GetType().FullName == u'Autodesk.Revit.DB.ElementId':
            return value
    except Exception:
        pass
    number = id_value(value, -1)
    if number < 0:
        return DB.ElementId.InvalidElementId
    return DB.ElementId(number)


def _valid_id(value):
    return id_value(value, -1) >= 0


def _safe_name(element):
    if element is None:
        return u''
    try:
        return _text(element.Name)
    except Exception:
        return u''


def _category_name(element):
    try:
        return _text(element.Category.Name)
    except Exception:
        return u''


def _color_value(color):
    if color is None:
        return None
    try:
        if hasattr(color, 'IsValid') and not color.IsValid:
            return None
    except Exception:
        pass
    try:
        return [int(color.Red), int(color.Green), int(color.Blue)]
    except Exception:
        return None


def _parameter(element, built_in):
    try:
        return element.get_Parameter(built_in)
    except Exception:
        return None


def _description_parameter(material):
    if DB is None:
        return None
    try:
        return _parameter(material, DB.BuiltInParameter.ALL_MODEL_DESCRIPTION)
    except Exception:
        return None


def _parameter_text(parameter):
    if parameter is None:
        return u''
    try:
        value = parameter.AsString()
        if value is not None:
            return _text(value)
    except Exception:
        pass
    try:
        value = parameter.AsValueString()
        if value is not None:
            return _text(value)
    except Exception:
        pass
    return u''


def _appearance_name(doc, material):
    try:
        asset_id = material.AppearanceAssetId
        if not _valid_id(asset_id):
            return u''
        return _safe_name(doc.GetElement(asset_id))
    except Exception:
        return u''


def _inventory_row(doc, material):
    return {
        u'id': id_value(material.Id),
        u'name': _safe_name(material),
        u'material_class': _text(_value(material, (u'MaterialClass',), u'')),
        u'material_category': _text(_value(
            material, (u'MaterialCategory',), u'')),
        u'description': _parameter_text(_description_parameter(material)),
        u'color': _color_value(_value(material, (u'Color',), None)),
        u'color_rgb': _color_value(_value(material, (u'Color',), None)),
        u'transparency': _integer(_value(material, (u'Transparency',), 0), 0),
        u'shininess': _integer(_value(material, (u'Shininess',), 0), 0),
        u'smoothness': _integer(_value(material, (u'Smoothness',), 0), 0),
        u'use_render_appearance': _truthy(_value(
            material, (u'UseRenderAppearanceForShading',), False)),
        u'surface_foreground_pattern_id': id_value(_value(
            material, (u'SurfaceForegroundPatternId',), None)),
        u'surface_foreground_color': _color_value(_value(
            material, (u'SurfaceForegroundPatternColor',), None)),
        u'cut_foreground_pattern_id': id_value(_value(
            material, (u'CutForegroundPatternId',), None)),
        u'cut_foreground_color': _color_value(_value(
            material, (u'CutForegroundPatternColor',), None)),
        u'appearance_asset_id': id_value(_value(
            material, (u'AppearanceAssetId',), None)),
        u'appearance_asset_name': _appearance_name(doc, material),
        u'usage_count': 0,
        u'type_reference_count': 0,
        u'paint_count': 0,
    }


def collect_material_inventory(doc):
    """Read all project materials and their safe Identity/Graphics fields."""
    _require_revit()
    rows = []
    collector = DB.FilteredElementCollector(doc).OfClass(DB.Material)
    for material in collector.ToElements():
        rows.append(_inventory_row(doc, material))
    rows.sort(key=lambda row: (_normal(row[u'name']), row[u'id']))
    return rows


class _ScopedElementList(list):
    pass


def _scoped_elements(values, scope):
    result = _ScopedElementList(values or [])
    result.material_scope = _text(scope)
    return result


def _unique_elements(elements):
    result = []
    seen = set()
    skipped = 0
    for element in elements or []:
        if element is None:
            skipped += 1
            continue
        key = id_value(_value(element, (u'Id',), None), -1)
        if key < 0:
            skipped += 1
            continue
        if key in seen:
            continue
        try:
            if DB is not None and isinstance(element, DB.ElementType):
                skipped += 1
                continue
        except Exception:
            pass
        seen.add(key)
        result.append(element)
    return result, skipped


def collect_scope_elements(doc, uidoc=None, scope=u'project'):
    """Collect instance elements for project, active-view, or selection scope."""
    _require_revit()
    warnings = []
    skipped = 0
    candidate_count = None
    scope_key = _normal(scope)
    resolved_scope = u'project'
    selection_values = (u'selection', u'selected', u'current_selection', u'目前選取')
    view_values = (u'view', u'current_view', u'active_view', u'目前視圖')
    project_values = (u'', u'project', u'all', u'whole_project', u'整個專案')

    if scope_key in selection_values:
        resolved_scope = u'selection'
        if uidoc is None:
            return {
                u'elements': _scoped_elements([], resolved_scope),
                u'stats': {u'raw': 0, u'scanned': 0, u'skipped': 0,
                           u'accepted': 0},
                u'warnings': [u'目前選取範圍需要有效的 UIDocument。'],
            }
        raw = []
        try:
            selected_ids = list(uidoc.Selection.GetElementIds())
            candidate_count = len(selected_ids)
            for element_id in selected_ids:
                element = doc.GetElement(element_id)
                if element is None:
                    skipped += 1
                else:
                    raw.append(element)
        except Exception as error:
            warnings.append(u'無法讀取目前選取：{0}'.format(_text(error)))
            raw = []
    elif scope_key in view_values:
        resolved_scope = u'view'
        try:
            view = uidoc.ActiveView if uidoc is not None else doc.ActiveView
        except Exception:
            view = None
        if view is None:
            return {
                u'elements': _scoped_elements([], resolved_scope),
                u'stats': {u'raw': 0, u'scanned': 0, u'skipped': 0,
                           u'accepted': 0},
                u'warnings': [u'目前視圖範圍需要有效的 ActiveView。'],
            }
        try:
            raw = DB.FilteredElementCollector(
                doc, view.Id).WhereElementIsNotElementType().ToElements()
        except Exception as error:
            return {
                u'elements': _scoped_elements([], resolved_scope),
                u'stats': {u'raw': 0, u'scanned': 0, u'skipped': 0,
                           u'accepted': 0},
                u'warnings': [u'無法建立目前視圖掃描範圍：{0}'.format(
                    _text(error))],
            }
    elif scope_key in project_values:
        raw = DB.FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements()
    else:
        warnings.append(u'未知掃描範圍「{0}」，已改用整個專案。'.format(
            _text(scope)))
        raw = DB.FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements()

    if candidate_count is None:
        try:
            candidate_count = len(raw)
        except Exception:
            raw = list(raw)
            candidate_count = len(raw)
    elements, invalid_count = _unique_elements(raw)
    elements = _scoped_elements(elements, resolved_scope)
    skipped += invalid_count
    return {
        u'elements': elements,
        u'stats': {u'raw': candidate_count, u'scanned': candidate_count,
                   u'skipped': skipped, u'accepted': len(elements)},
        u'warnings': warnings,
    }


def _warning(stage, element, error):
    return {
        u'stage': _text(stage),
        u'element_id': id_value(_value(element, (u'Id',), None), -1),
        u'message': _text(error),
    }


def _material_identity(doc, material_id):
    material = None
    try:
        material = doc.GetElement(material_id)
    except Exception:
        pass
    return material, (_safe_name(material) or u'(未知材質)')


def _type_data(doc, element):
    type_id = None
    type_element = None
    try:
        type_id = element.GetTypeId()
        if _valid_id(type_id):
            type_element = doc.GetElement(type_id)
    except Exception:
        pass
    return id_value(type_id, -1), _safe_name(type_element)


def _level_name(doc, element):
    level_id = None
    try:
        level_id = element.LevelId
    except Exception:
        pass
    if not _valid_id(level_id):
        for parameter_name in (u'LEVEL_PARAM', u'FAMILY_LEVEL_PARAM',
                               u'SCHEDULE_LEVEL_PARAM'):
            try:
                built_in = getattr(DB.BuiltInParameter, parameter_name)
                parameter = element.get_Parameter(built_in)
                if parameter is not None:
                    candidate = parameter.AsElementId()
                    if _valid_id(candidate):
                        level_id = candidate
                        break
            except Exception:
                pass
    try:
        return _safe_name(doc.GetElement(level_id)) if _valid_id(level_id) else u''
    except Exception:
        return u''


def _usage_row(doc, element, material_id, source_kind, area_m2=0.0,
               volume_m3=0.0, extras=None):
    material, material_name = _material_identity(doc, material_id)
    type_id, type_name = _type_data(doc, element)
    if source_kind in (u'compound_slot', u'parameter') and type_id < 0:
        type_id = id_value(element.Id)
        type_name = _safe_name(element)
    row = {
        u'material_id': id_value(material_id),
        u'material_name': material_name,
        u'element_id': id_value(element.Id),
        u'category': _category_name(element),
        u'element_name': _safe_name(element),
        u'type_id': type_id,
        u'type_name': type_name,
        u'level': _level_name(doc, element),
        u'source_kind': _text(source_kind),
        u'source': _text(source_kind),
        u'area_m2': float(area_m2),
        u'volume_m3': float(volume_m3),
    }
    if extras:
        row.update(extras)
    return row


def _usage_key(row):
    return (
        row[u'material_id'], row[u'element_id'], row[u'source_kind'],
        _integer(row.get(u'layer_index', -1), -1),
        _normal(row.get(u'parameter_name', u'')),
    )


def _summary_row(material_id, material_name):
    return {
        u'material_id': material_id,
        u'material_name': material_name,
        u'usage_count': 0,
        u'type_reference_count': 0,
        u'referencing_type_count': 0,
        u'paint_count': 0,
        u'nonpaint_area_m2': 0.0,
        u'paint_area_m2': 0.0,
        u'volume_m3': 0.0,
    }


def _append_distinct_usage(usages, usage_keys, row):
    key = _usage_key(row)
    if key in usage_keys:
        return False
    usage_keys.add(key)
    usages.append(row)
    return True


def _append_instance_source(doc, element, material_ids, use_paint,
                            source_kind, usages, usage_keys, warnings):
    failed = False
    for material_id in material_ids or []:
        if not _valid_id(material_id):
            continue
        area_m2 = 0.0
        volume_m3 = 0.0
        try:
            area_m2 = float(element.GetMaterialArea(
                material_id, use_paint)) * SQFT_TO_SQM
        except Exception as error:
            warnings.append(_warning(
                source_kind + u'_area', element, error))
            failed = True
        if not use_paint:
            try:
                volume_m3 = float(element.GetMaterialVolume(
                    material_id)) * CUFT_TO_CUM
            except Exception as error:
                warnings.append(_warning(u'nonpaint_volume', element, error))
                failed = True
        _append_distinct_usage(
            usages, usage_keys,
            _usage_row(doc, element, material_id, source_kind,
                       area_m2, volume_m3,
                       {u'type_reference': False,
                        u'painted': bool(use_paint)}))
    return failed


def _scan_instance_materials(doc, element, usages, usage_keys, warnings):
    nonpaint_failed = False
    paint_failed = False
    try:
        nonpaint_ids = element.GetMaterialIds(False)
    except Exception as error:
        warnings.append(_warning(u'nonpaint', element, error))
        nonpaint_ids = []
        nonpaint_failed = True
    try:
        paint_ids = element.GetMaterialIds(True)
    except Exception as error:
        warnings.append(_warning(u'paint', element, error))
        paint_ids = []
        paint_failed = True
    nonpaint_detail_failed = _append_instance_source(
        doc, element, nonpaint_ids, False, u'nonpaint', usages,
        usage_keys, warnings)
    paint_detail_failed = _append_instance_source(
        doc, element, paint_ids, True, u'paint', usages,
        usage_keys, warnings)
    # A one-sided failure still produced an auditable partial result.  Only an
    # element for which neither source could be inspected is counted skipped.
    fully_failed = nonpaint_failed and paint_failed
    partially_failed = (not fully_failed and
                        (nonpaint_failed or paint_failed or
                         nonpaint_detail_failed or paint_detail_failed))
    return fully_failed, partially_failed


def _compound_references(doc, element_type, warnings):
    rows = []
    getter = _value(element_type, (u'GetCompoundStructure',), None)
    if getter is None or not callable(getter):
        return rows
    try:
        structure = getter()
    except Exception as error:
        warnings.append(_warning(u'compound_structure', element_type, error))
        return rows
    if structure is None:
        return rows
    try:
        layer_count = int(structure.LayerCount)
    except Exception as error:
        warnings.append(_warning(u'compound_layers', element_type, error))
        return rows
    for index in range(layer_count):
        try:
            material_id = structure.GetMaterialId(index)
            if not _valid_id(material_id):
                continue
            rows.append(_usage_row(
                doc, element_type, material_id, u'compound_slot', 0.0, 0.0,
                {u'type_reference': True, u'layer_index': index,
                 u'parameter_name': u''}))
        except Exception as error:
            warnings.append(_warning(
                u'compound_layer_{0}'.format(index), element_type, error))
    return rows


def _parameter_references(doc, element_type, warnings):
    rows = []
    try:
        parameters = element_type.Parameters
    except Exception as error:
        warnings.append(_warning(u'type_parameters', element_type, error))
        return rows
    for parameter in parameters or []:
        try:
            if parameter.StorageType != DB.StorageType.ElementId:
                continue
            material_id = parameter.AsElementId()
            if not _valid_id(material_id):
                continue
            material = doc.GetElement(material_id)
            if material is None or not isinstance(material, DB.Material):
                continue
            try:
                parameter_name = _text(parameter.Definition.Name)
            except Exception:
                parameter_name = u'ElementId 材質參數'
            rows.append(_usage_row(
                doc, element_type, material_id, u'parameter', 0.0, 0.0,
                {u'type_reference': True, u'layer_index': -1,
                 u'parameter_name': parameter_name}))
        except Exception as error:
            warnings.append(_warning(u'type_parameter', element_type, error))
    return rows


def _fallback_type_material_ids(doc, element_type, known_pairs, warnings):
    rows = []
    try:
        material_ids = element_type.GetMaterialIds(False)
    except Exception:
        return rows
    type_id = id_value(element_type.Id)
    for material_id in material_ids or []:
        material_value = id_value(material_id)
        if material_value < 0 or (type_id, material_value) in known_pairs:
            continue
        rows.append(_usage_row(
            doc, element_type, material_id, u'parameter', 0.0, 0.0,
            {u'type_reference': True, u'layer_index': -1,
             u'parameter_name': u'GetMaterialIds'}))
    return rows


def _collect_type_references(doc, usages, usage_keys, warnings,
                             element_types=None):
    scanned = 0
    skipped = 0
    if element_types is None:
        try:
            element_types = DB.FilteredElementCollector(
                doc).WhereElementIsElementType().ToElements()
        except Exception as error:
            warnings.append(_warning(u'type_collector', None, error))
            return scanned, 1
    for element_type in element_types:
        scanned += 1
        found_rows = []
        try:
            found_rows.extend(_compound_references(doc, element_type, warnings))
            found_rows.extend(_parameter_references(doc, element_type, warnings))
            known_pairs = set()
            for row in found_rows:
                known_pairs.add((row[u'element_id'], row[u'material_id']))
            found_rows.extend(_fallback_type_material_ids(
                doc, element_type, known_pairs, warnings))
        except Exception as error:
            warnings.append(_warning(u'type_reference', element_type, error))
            skipped += 1
            continue
        for row in found_rows:
            _append_distinct_usage(usages, usage_keys, row)
    return scanned, skipped


def _scope_element_types(doc, elements):
    result = []
    seen = set()
    for element in elements or []:
        try:
            type_id = element.GetTypeId()
        except Exception:
            continue
        type_value = id_value(type_id, -1)
        if type_value < 0 or type_value in seen:
            continue
        try:
            element_type = doc.GetElement(type_id)
        except Exception:
            element_type = None
        if element_type is None:
            continue
        seen.add(type_value)
        result.append(element_type)
    return result


def collect_material_usage(doc, elements, scope=None,
                           include_all_types=None):
    """Collect distinct material usages while respecting the requested scope.

    Project scope scans every ElementType so an unplaced type still prevents a
    false ``unused`` result.  View and selection scopes scan only the types of
    the supplied scope elements; they never pull unrelated project types into
    the result.  ``include_all_types`` is an explicit adapter override.
    """
    _require_revit()
    if scope is None:
        scope = _value(elements, (u'material_scope',), u'project')
    warnings = []
    usages = []
    usage_keys = set()
    scope_elements, initial_skipped = _unique_elements(elements or [])
    skipped = initial_skipped
    fully_failed_count = 0
    partial_failures = 0
    for element in scope_elements:
        try:
            failed, partial = _scan_instance_materials(
                doc, element, usages, usage_keys, warnings)
            if failed:
                skipped += 1
                fully_failed_count += 1
            elif partial:
                partial_failures += 1
        except Exception as error:
            warnings.append(_warning(u'element_materials', element, error))
            skipped += 1
            fully_failed_count += 1

    if include_all_types is None:
        include_all_types = _normal(scope) in (
            u'', u'project', u'all', u'whole_project', u'整個專案')
    if _truthy(include_all_types):
        type_elements = None
        type_scope = u'project'
    else:
        type_elements = _scope_element_types(doc, scope_elements)
        type_scope = u'scope'
    type_scanned, type_skipped = _collect_type_references(
        doc, usages, usage_keys, warnings, type_elements)

    summaries = {}
    instance_ids = {}
    paint_ids = {}
    type_ids = {}
    type_slot_keys = {}
    for material in collect_material_inventory(doc):
        material_id = material[u'id']
        summaries[material_id] = _summary_row(
            material_id, material[u'name'])
        instance_ids[material_id] = set()
        paint_ids[material_id] = set()
        type_ids[material_id] = set()
        type_slot_keys[material_id] = set()

    for row in usages:
        material_id = row[u'material_id']
        if material_id not in summaries:
            summaries[material_id] = _summary_row(
                material_id, row[u'material_name'])
            instance_ids[material_id] = set()
            paint_ids[material_id] = set()
            type_ids[material_id] = set()
            type_slot_keys[material_id] = set()
        summary = summaries[material_id]
        if row.get(u'type_reference'):
            type_ids[material_id].add(row[u'element_id'])
            type_slot_keys[material_id].add(_usage_key(row))
        else:
            instance_ids[material_id].add(row[u'element_id'])
            if row[u'source_kind'] == u'paint':
                paint_ids[material_id].add(row[u'element_id'])
                summary[u'paint_area_m2'] += row[u'area_m2']
            else:
                summary[u'nonpaint_area_m2'] += row[u'area_m2']
                summary[u'volume_m3'] += row[u'volume_m3']

    material_rows = []
    for material_id in summaries:
        summary = summaries[material_id]
        summary[u'usage_count'] = len(instance_ids[material_id])
        summary[u'paint_count'] = len(paint_ids[material_id])
        summary[u'type_reference_count'] = len(type_slot_keys[material_id])
        summary[u'referencing_type_count'] = len(type_ids[material_id])
        material_rows.append(summary)
    material_rows.sort(key=lambda row: (
        _normal(row[u'material_name']), row[u'material_id']))
    usages.sort(key=lambda row: (
        _normal(row[u'material_name']), _normal(row[u'category']),
        row[u'element_id'], _normal(row[u'source_kind']),
        _integer(row.get(u'layer_index', -1), -1)))

    return {
        u'materials': material_rows,
        u'usages': usages,
        u'warnings': warnings,
        u'stats': {
            u'scanned': len(scope_elements),
            u'skipped': skipped,
            u'partial_failures': partial_failures,
            u'accepted': len(scope_elements) - fully_failed_count,
            u'type_scanned': type_scanned,
            u'type_skipped': type_skipped,
            u'type_scope': type_scope,
            u'usage_rows': len(usages),
        },
    }


def collect_fill_patterns(doc):
    """Return fill patterns with explicit Drafting/Model target metadata."""
    _require_revit()
    rows = []
    collector = DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement)
    for element in collector.ToElements():
        try:
            pattern = element.GetFillPattern()
        except Exception:
            pattern = None
        if pattern is None:
            continue
        target = _text(_value(pattern, (u'Target',), u'')).split(u'.')[-1]
        target_key = _normal(target)
        is_drafting = target_key == u'drafting'
        is_model = target_key == u'model'
        rows.append({
            u'id': id_value(element.Id),
            u'pattern_id': id_value(element.Id),
            u'name': _safe_name(element) or _text(_value(pattern, (u'Name',), u'')),
            u'target': u'drafting' if is_drafting else (
                u'model' if is_model else target_key),
            u'is_drafting': is_drafting,
            u'is_model': is_model,
            u'is_solid_fill': _truthy(_value(
                pattern, (u'IsSolidFill',), False)),
        })
    rows.sort(key=lambda row: (
        0 if row[u'is_drafting'] else 1, _normal(row[u'name']), row[u'id']))
    return rows


def _result(ok, changed=0, errors=None, warnings=None, items=None):
    return {
        u'ok': bool(ok),
        u'changed': int(changed),
        u'errors': list(errors or []),
        u'warnings': list(warnings or []),
        u'items': list(items or []),
    }


def _material_from_record(doc, record):
    try:
        if DB is not None and isinstance(record, DB.Material):
            return record
    except Exception:
        pass
    material_id = _value(
        record, (u'id', u'material_id', u'Id', u'MaterialId'), None)
    try:
        material = doc.GetElement(_element_id(material_id))
    except Exception:
        material = None
    try:
        if material is not None and isinstance(material, DB.Material):
            return material
    except Exception:
        pass
    return None


def _enabled_fields(patch):
    enabled = {}
    errors = []
    fields = patch.get(u'fields', {}) if isinstance(patch, dict) else {}
    if not isinstance(fields, dict):
        return enabled, [u'材質 patch.fields 必須是欄位字典。']
    for key in fields:
        field = fields[key]
        if not isinstance(field, dict) or not _truthy(field.get(u'enabled', False)):
            continue
        if key not in ALLOWED_PATCH_FIELDS:
            errors.append(u'不允許批次寫入欄位「{0}」。'.format(_text(key)))
            continue
        enabled[key] = field.get(u'value')
    return enabled, errors


def _rename_plan(materials, patch, project_materials):
    rename = patch.get(u'rename', {}) if isinstance(patch, dict) else {}
    if not isinstance(rename, dict) or not _truthy(rename.get(u'enabled', False)):
        return {}, [], []
    prefix = _text(rename.get(u'prefix', u''))
    suffix = _text(rename.get(u'suffix', u''))
    find_text = _text(rename.get(u'find_text', u''))
    replace_text = _text(rename.get(u'replace_text', u''))
    plan = {}
    errors = []
    warnings = []
    selected_ids = set([id_value(material.Id) for material in materials])
    selected_old = {}
    new_names = {}

    for material in materials:
        material_id = id_value(material.Id)
        old_name = _safe_name(material)
        middle = old_name.replace(find_text, replace_text) if find_text else old_name
        new_name = prefix + middle + suffix
        plan[material_id] = new_name
        old_key = _normal(old_name)
        new_key = _normal(new_name)
        selected_old.setdefault(old_key, []).append(material_id)
        new_names.setdefault(new_key, []).append(material_id)
        if not new_name.strip():
            errors.append(u'材質「{0}」的新名稱不可為空白。'.format(old_name))

    for key in new_names:
        if key and len(new_names[key]) > 1:
            errors.append(u'批次改名結果重名：「{0}」。'.format(
                plan[new_names[key][0]]))

    for material in materials:
        material_id = id_value(material.Id)
        old_key = _normal(_safe_name(material))
        new_key = _normal(plan[material_id])
        if new_key != old_key and new_key in selected_old:
            other_ids = [value for value in selected_old[new_key]
                         if value != material_id]
            if other_ids:
                errors.append(
                    u'不支援同批名稱交換：材質「{0}」不可直接改為「{1}」。'.format(
                        _safe_name(material), plan[material_id]))

    external_names = {}
    for project_material in project_materials:
        project_id = id_value(project_material.Id)
        if project_id not in selected_ids:
            external_names[_normal(_safe_name(project_material))] = project_id
    for material_id in plan:
        if _normal(plan[material_id]) in external_names:
            errors.append(u'新名稱「{0}」與專案中未選取的材質重名。'.format(
                plan[material_id]))

    changed = False
    for material in materials:
        material_id = id_value(material.Id)
        if plan[material_id] != _safe_name(material):
            changed = True
            break
    if not changed:
        warnings.append(u'名稱規則不會改變目前所選材質名稱。')
    return plan, errors, warnings


def _rgb(value, label):
    if isinstance(value, dict):
        values = [_value(value, (u'r', u'red', u'R', u'Red'), None),
                  _value(value, (u'g', u'green', u'G', u'Green'), None),
                  _value(value, (u'b', u'blue', u'B', u'Blue'), None)]
    else:
        values = _items(value)
    if len(values) < 3:
        raise ValueError(u'{0} 必須包含 R、G、B 三個數值。'.format(label))
    result = [_integer(values[0], -1), _integer(values[1], -1),
              _integer(values[2], -1)]
    if min(result) < 0 or max(result) > 255:
        raise ValueError(u'{0} 的 RGB 必須介於 0 與 255。'.format(label))
    return result


def _range(value, label, minimum, maximum):
    number = _integer(value, minimum - 1)
    if number < minimum or number > maximum:
        raise ValueError(u'{0} 必須介於 {1} 與 {2}。'.format(
            label, minimum, maximum))
    return number


def _pattern_info(doc, value, field_name):
    pattern_id = _element_id(value)
    if not _valid_id(pattern_id):
        return pattern_id, u'none'
    element = doc.GetElement(pattern_id)
    if element is None or not isinstance(element, DB.FillPatternElement):
        raise ValueError(u'{0} 指定的填滿樣式不存在。'.format(field_name))
    pattern = element.GetFillPattern()
    if pattern is None:
        raise ValueError(u'{0} 無法讀取填滿樣式內容。'.format(field_name))
    target = _normal(_text(pattern.Target).split(u'.')[-1])
    return pattern_id, target


def _validated_field_values(doc, enabled):
    values = {}
    for key in enabled:
        value = enabled[key]
        if key in (u'material_class', u'material_category', u'description'):
            values[key] = _text(value)
        elif key == u'color':
            values[key] = _rgb(value, u'顏色')
        elif key == u'transparency':
            values[key] = _range(value, u'透明度', 0, 100)
        elif key == u'shininess':
            values[key] = _range(value, u'光澤度', 0, 128)
        elif key == u'smoothness':
            values[key] = _range(value, u'平滑度', 0, 100)
        elif key == u'use_render_appearance':
            values[key] = _truthy(value)
        elif key in (u'surface_foreground_color', u'cut_foreground_color'):
            values[key] = _rgb(value, u'填滿樣式顏色')
        elif key == u'surface_foreground_pattern_id':
            pattern_id, target = _pattern_info(doc, value, u'表面前景樣式')
            if target not in (u'none', u'drafting', u'model'):
                raise ValueError(u'表面前景樣式必須是 Drafting 或 Model target。')
            values[key] = pattern_id
        elif key == u'cut_foreground_pattern_id':
            pattern_id, target = _pattern_info(doc, value, u'切割前景樣式')
            if target not in (u'none', u'drafting'):
                raise ValueError(u'切割前景樣式只接受 Drafting target。')
            values[key] = pattern_id
    return values


def _color_object(value):
    return DB.Color(int(value[0]), int(value[1]), int(value[2]))


def _set_description(material, value):
    parameter = _description_parameter(material)
    if parameter is None:
        raise ValueError(u'材質「{0}」沒有可寫入的描述參數。'.format(
            _safe_name(material)))
    try:
        if parameter.IsReadOnly:
            raise ValueError(u'材質「{0}」的描述參數為唯讀。'.format(
                _safe_name(material)))
    except AttributeError:
        pass
    if not parameter.Set(_text(value)):
        raise ValueError(u'材質「{0}」的描述寫入失敗。'.format(
            _safe_name(material)))


def _set_material_field(material, key, value):
    if key == u'material_class':
        material.MaterialClass = value
    elif key == u'material_category':
        material.MaterialCategory = value
    elif key == u'description':
        _set_description(material, value)
    elif key == u'color':
        material.Color = _color_object(value)
    elif key == u'transparency':
        material.Transparency = value
    elif key == u'shininess':
        material.Shininess = value
    elif key == u'smoothness':
        material.Smoothness = value
    elif key == u'use_render_appearance':
        material.UseRenderAppearanceForShading = value
    elif key == u'surface_foreground_pattern_id':
        material.SurfaceForegroundPatternId = value
    elif key == u'surface_foreground_color':
        material.SurfaceForegroundPatternColor = _color_object(value)
    elif key == u'cut_foreground_pattern_id':
        material.CutForegroundPatternId = value
    elif key == u'cut_foreground_color':
        material.CutForegroundPatternColor = _color_object(value)


def _read_material_field(material, key):
    if key == u'material_class':
        return _text(material.MaterialClass)
    if key == u'material_category':
        return _text(material.MaterialCategory)
    if key == u'description':
        return _parameter_text(_description_parameter(material))
    if key == u'color':
        return _color_value(material.Color)
    if key == u'transparency':
        return int(material.Transparency)
    if key == u'shininess':
        return int(material.Shininess)
    if key == u'smoothness':
        return int(material.Smoothness)
    if key == u'use_render_appearance':
        return bool(material.UseRenderAppearanceForShading)
    if key == u'surface_foreground_pattern_id':
        return id_value(material.SurfaceForegroundPatternId)
    if key == u'surface_foreground_color':
        return _color_value(material.SurfaceForegroundPatternColor)
    if key == u'cut_foreground_pattern_id':
        return id_value(material.CutForegroundPatternId)
    if key == u'cut_foreground_color':
        return _color_value(material.CutForegroundPatternColor)
    return None


def _expected_value(key, value):
    if key in (u'surface_foreground_pattern_id', u'cut_foreground_pattern_id'):
        return id_value(value)
    return value


def _values_match(actual, expected):
    if isinstance(expected, list):
        return list(actual or []) == expected
    return actual == expected


def _preflight(doc, material_records, patch):
    errors = []
    warnings = []
    materials = []
    seen = set()
    for record in material_records or []:
        material = _material_from_record(doc, record)
        if material is None:
            errors.append(u'找不到選取的材質 ID：{0}。'.format(_text(_value(
                record, (u'id', u'material_id', u'Id'), u''))))
            continue
        material_id = id_value(material.Id)
        if material_id in seen:
            continue
        seen.add(material_id)
        materials.append(material)
    if not materials:
        errors.append(u'沒有可套用的材質。')

    enabled, field_errors = _enabled_fields(patch or {})
    errors.extend(field_errors)
    try:
        values = _validated_field_values(doc, enabled)
    except Exception as error:
        values = {}
        errors.append(_text(error))

    try:
        project_materials = list(DB.FilteredElementCollector(
            doc).OfClass(DB.Material).ToElements())
        rename_plan, rename_errors, rename_warnings = _rename_plan(
            materials, patch or {}, project_materials)
        errors.extend(rename_errors)
        warnings.extend(rename_warnings)
    except Exception as error:
        rename_plan = {}
        errors.append(u'名稱預檢失敗：{0}'.format(_text(error)))

    if not enabled and not rename_plan:
        errors.append(u'沒有任何已啟用的材質欄位或名稱變更。')
    return materials, values, rename_plan, errors, warnings


def apply_material_patch(doc, material_records, patch):
    """Apply a gated patch atomically, with preflight and in-transaction read-back."""
    _require_revit()
    materials, values, rename_plan, errors, warnings = _preflight(
        doc, material_records, patch)
    if errors:
        return _result(False, 0, errors, warnings, [])

    transaction = DB.Transaction(doc, u'材質批次編輯')
    items = []
    try:
        transaction.Start()
        for material in materials:
            material_id = id_value(material.Id)
            old_name = _safe_name(material)
            for key in values:
                _set_material_field(material, key, values[key])
            if material_id in rename_plan:
                material.Name = rename_plan[material_id]
            items.append({
                u'id': material_id,
                u'old_name': old_name,
                u'new_name': _safe_name(material),
                u'fields': list(values.keys()),
                u'status': u'written',
            })

        doc.Regenerate()
        for material in materials:
            material_id = id_value(material.Id)
            if material_id in rename_plan:
                actual_name = _safe_name(material)
                if actual_name != rename_plan[material_id]:
                    raise ValueError(
                        u'材質 ID {0} 名稱 read-back 不一致。'.format(material_id))
            for key in values:
                actual = _read_material_field(material, key)
                expected = _expected_value(key, values[key])
                if not _values_match(actual, expected):
                    raise ValueError(
                        u'材質「{0}」欄位 {1} read-back 不一致：{2} != {3}。'.format(
                            _safe_name(material), key, _text(actual),
                            _text(expected)))
        status = transaction.Commit()
        try:
            if status != DB.TransactionStatus.Committed:
                raise RuntimeError(u'Revit 未回報交易已提交：{0}'.format(_text(status)))
        except AttributeError:
            pass
        for item in items:
            item[u'status'] = u'committed'
        return _result(True, len(materials), [], warnings, items)
    except Exception as error:
        try:
            if transaction.GetStatus() == DB.TransactionStatus.Started:
                transaction.RollBack()
        except Exception:
            try:
                transaction.RollBack()
            except Exception:
                pass
        for item in items:
            item[u'status'] = u'rolled_back'
        return _result(False, 0, [_text(error)], warnings, items)


# The room adapter is implemented separately.  Keep this module importable in
# offline tests and during parallel deployment even if that optional file is
# not present or cannot import Revit yet.
try:
    from room_material_revit import collect_rooms, collect_room_material_details
except Exception:
    def collect_rooms(*args, **kwargs):
        raise RuntimeError(u'room_material_revit.collect_rooms 目前不可用。')

    def collect_room_material_details(*args, **kwargs):
        raise RuntimeError(
            u'room_material_revit.collect_room_material_details 目前不可用。')
