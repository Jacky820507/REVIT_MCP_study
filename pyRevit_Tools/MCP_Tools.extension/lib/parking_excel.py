# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Revit schedule reader and guarded Excel COM updater for parking quantities."""

import os
import re
import shutil
from datetime import datetime

from pyrevit import DB, forms
from System import Activator, GC, Type
from System.Runtime.InteropServices import Marshal

import parking_excel_logic as logic
import sheet_layout
import takeoff_entry
import takeoff_standalone

try:
    reload(logic)
except Exception:
    pass


TITLE = u'停車位 Excel'
SCHEDULES = (
    (u'汽車停車數量', 'car'),
    (u'大客車停車數量', 'bus'),
    (u'機車停車數量', 'motorcycle'),
)
OTHER_SHEET = u'其他數量'

# 「其他數量」分頁的兩個數量欄。同一欄在這支程式裡有三種寫法：儲存格的欄號、
# 訊息字串裡的欄位字母、以及 old[key] 的字典鍵。欄號是唯一的真相，字母一律由
# _addr() 導出（字典鍵沿用舊名，改動範圍太大另議）。
# 唯一定義在 parking_excel_logic（驗證邏輯也要用同一份），這裡只是轉出。
OTHER_COUNT_COL = logic.OTHER_COUNT_COL
OTHER_WHEEL_COL = logic.OTHER_WHEEL_COL


def _col(col_number):
    """欄位字母（1 基欄號 → 'F'）。訊息裡不再手寫字母。"""
    return sheet_layout.column_letter(col_number - 1)


def _addr(sheet_name, col_number, row):
    """給人看的位址：``其他數量!F12``。"""
    return u'{0}!{1}{2}'.format(
        sheet_name, sheet_layout.column_letter(col_number - 1), row)

SUBTOTAL_SHEET = u'小計'
XL_CALCULATION_AUTOMATIC = -4105
SOURCE_MODE_AUTO = 'auto'
SOURCE_MODE_SCHEDULES = 'schedules'
SCHEDULE_NAME_HINTS = (
    u'停車',
    u'車位',
    u'parking',
    u'汽車',
    u'機車',
    u'大客車',
)
IGNORED_PARKING_NAME_HINTS = (
    u'行車方向標誌',
    u'方向標誌',
    u'方向箭頭',
    u'箭頭',
    u'trafficarrow',
    u'directionarrow',
)
COMMENT_PARAM_NAMES = (
    u'標註',
    u'註解',
    u'備註',
    u'Comments',
)
# Linked levels rarely share the host's ElementId or naming, and their raw
# Elevation is in the link's own internal coordinates. Match them by elevation
# transformed into host coordinates, with a tolerance loose enough to absorb
# base-point rounding yet far below any real floor-to-floor spacing (~50 mm).
_LINK_LEVEL_TOLERANCE_FT = 50.0 / 304.8


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _id_value(value):
    if value is None:
        return None
    for name in ('Value', 'IntegerValue'):
        try:
            return int(getattr(value, name))
        except Exception:
            pass
    try:
        return int(value)
    except Exception:
        return None


def _element_name(element):
    values = []
    try:
        values.append(element.Name)
    except Exception:
        pass
    try:
        values.append(element.Symbol.FamilyName)
        values.append(element.Symbol.Name)
    except Exception:
        pass
    return u' '.join(_text(value) for value in values if _text(value))


def _parameter(element, names):
    sources = [element]
    try:
        if element.Symbol is not None:
            sources.append(element.Symbol)
    except Exception:
        pass
    for source in sources:
        for name in names:
            try:
                parameter = source.LookupParameter(name)
                if parameter is not None and parameter.HasValue:
                    return parameter
            except Exception:
                pass
    return None


def _double_to_mm(value):
    try:
        return DB.UnitUtils.ConvertFromInternalUnits(
            value, DB.UnitTypeId.Millimeters)
    except Exception:
        try:
            return DB.UnitUtils.ConvertFromInternalUnits(
                value, DB.DisplayUnitType.DUT_MILLIMETERS)
        except Exception:
            return float(value) * 304.8


def _parameter_mm(element, names):
    parameter = _parameter(element, names)
    if parameter is None:
        return None
    try:
        if parameter.StorageType == DB.StorageType.Double:
            return float(_double_to_mm(parameter.AsDouble()))
    except Exception:
        pass
    # A dimension embedded in the display text is still valid evidence.
    try:
        text = parameter.AsValueString()
        parsed = logic.parse_dimensions(u'{} x {}'.format(text, text))
        if parsed:
            return parsed[0]
    except Exception:
        pass
    return None


def _truthy_parameter(parameter):
    try:
        if parameter.StorageType == DB.StorageType.Integer:
            return parameter.AsInteger() != 0
        if parameter.StorageType == DB.StorageType.Double:
            return abs(parameter.AsDouble()) > 0.000001
    except Exception:
        pass
    values = []
    for getter in ('AsString', 'AsValueString'):
        try:
            values.append(_text(getattr(parameter, getter)()))
        except Exception:
            pass
    normalized = logic.normalize_label(u' '.join(values))
    if normalized in (u'', u'0', u'否', u'false', u'no', u'n'):
        return False
    return True


def _is_accessible(element, name):
    if logic.is_accessible_text(name):
        return True
    parameter = _parameter(element, (
        u'無障礙',
        u'無障礙車位',
        u'無障礙停車位',
        u'Accessible',
        u'Barrier Free',
        u'Disabled',
    ))
    if parameter is not None and _truthy_parameter(parameter):
        return True
    return False


def _annotation_text(element):
    try:
        parameter = element.get_Parameter(
            DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if parameter is not None and parameter.HasValue:
            value = _text(parameter.AsString())
            if value:
                return value
    except Exception:
        pass
    parameter = _parameter(element, COMMENT_PARAM_NAMES)
    if parameter is None:
        return u''
    for getter in ('AsString', 'AsValueString'):
        try:
            value = _text(getattr(parameter, getter)())
            if value:
                return value
        except Exception:
            pass
    return u''


def _level_id(element):
    try:
        value = _id_value(element.LevelId)
        if value is not None and value >= 0:
            return value
    except Exception:
        pass
    builtins = (
        'FAMILY_LEVEL_PARAM',
        'INSTANCE_REFERENCE_LEVEL_PARAM',
        'SCHEDULE_LEVEL_PARAM',
    )
    for name in builtins:
        try:
            parameter = element.get_Parameter(getattr(DB.BuiltInParameter, name))
            value = _id_value(parameter.AsElementId()) if parameter else None
            if value is not None and value >= 0:
                return value
        except Exception:
            pass
    for name in (u'樓層', u'Level'):
        try:
            parameter = element.LookupParameter(name)
            value = _id_value(parameter.AsElementId()) if parameter else None
            if value is not None and value >= 0:
                return value
        except Exception:
            pass
    return None


def _element_level(element):
    try:
        level_id = element.LevelId
        if _id_value(level_id) is not None and _id_value(level_id) >= 0:
            level = element.Document.GetElement(level_id)
            if level is not None:
                return level
    except Exception:
        pass
    try:
        level_id = _level_id(element)
        if level_id is not None and level_id >= 0:
            return element.Document.GetElement(DB.ElementId(int(level_id)))
    except Exception:
        pass
    return None


def _level_matches(element, selected_level_id, selected_level_name=None,
                   selected_level_elevation=None):
    level_id = _level_id(element)
    try:
        if level_id is not None and int(level_id) == int(selected_level_id):
            return True
    except Exception:
        pass
    level = _element_level(element)
    if level is None:
        return False
    if selected_level_name:
        try:
            if logic.normalize_label(level.Name) == logic.normalize_label(
                    selected_level_name):
                return True
        except Exception:
            pass
    if selected_level_elevation is not None:
        try:
            return abs(float(level.Elevation) - float(selected_level_elevation)) <= 0.05
        except Exception:
            pass
    return False


def _linked_level_matches(element, link_transform, selected_level_name=None,
                          selected_level_elevation=None):
    """Match a linked parking bay to the host level.

    Linked levels carry their own ElementIds and internal elevations, so the
    host-side ``_level_matches`` never fires for them. Prefer the element's
    level elevation transformed into host coordinates (authoritative even when
    names differ or the link is placed with a base-point offset); fall back to
    exact normalized name equality only when elevation is unavailable.
    """
    level = _element_level(element)
    if level is None:
        return False
    if selected_level_elevation is not None:
        try:
            link_elevation = float(level.Elevation)
            world_z = link_transform.OfPoint(
                DB.XYZ(0.0, 0.0, link_elevation)).Z
            return abs(world_z - float(selected_level_elevation)) <= (
                _LINK_LEVEL_TOLERANCE_FT)
        except Exception:
            pass
    if selected_level_name:
        try:
            if logic.normalize_label(level.Name) == logic.normalize_label(
                    selected_level_name):
                return True
        except Exception:
            pass
    return False


def collect_levels(doc):
    levels = list(DB.FilteredElementCollector(doc).OfClass(DB.Level))
    levels.sort(key=lambda item: (float(item.Elevation), _text(item.Name)))
    return levels


def _level_catalog(source_doc):
    """Return ``[(level_id, name, elevation_mm)]`` for one document.

    Elevations stay in the document's own internal coordinates, and bay
    elevations are read from the same document, so a linked model needs no
    transform: both sides move together with the link.
    """
    catalog = []
    try:
        levels = DB.FilteredElementCollector(source_doc).OfClass(DB.Level)
    except Exception:
        return catalog
    for level in levels:
        level_id = _id_value(level.Id)
        if level_id is None:
            continue
        try:
            elevation_mm = float(_double_to_mm(float(level.Elevation)))
        except Exception:
            continue
        catalog.append((level_id, _text(level.Name), elevation_mm))
    catalog.sort(key=lambda row: (row[2], row[0]))
    return catalog


def _catalog_level_name(catalog, level_id):
    if level_id is None:
        return u''
    for candidate_id, name, unused_elevation in catalog or []:
        if candidate_id == level_id:
            return name
    return u''


def _element_base_elevation_mm(element):
    """Return where the bay physically sits, in document millimetres."""
    try:
        point = getattr(element.Location, 'Point', None)
        if point is not None:
            return float(_double_to_mm(float(point.Z)))
    except Exception:
        pass
    try:
        box = element.get_BoundingBox(None)
        if box is not None:
            return float(_double_to_mm(float(box.Min.Z)))
    except Exception:
        pass
    return None


def _schedule_kind(schedule_name):
    normalized = logic.normalize_label(schedule_name)
    if u'機車' in normalized or u'motorcycle' in normalized:
        return 'motorcycle'
    if u'大客車' in normalized or u'bus' in normalized:
        return 'bus'
    if u'汽車' in normalized or u'car' in normalized:
        return 'car'
    return None


def _schedule_name_matches(schedule_name):
    normalized = logic.normalize_label(schedule_name)
    return any(hint in normalized for hint in SCHEDULE_NAME_HINTS)


def collect_parking_schedules(doc):
    choices = []
    for schedule in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        try:
            if schedule.IsTemplate:
                continue
        except Exception:
            pass
        choices.append(_ScheduleChoice(schedule))
    choices.sort(key=lambda item: (0 if item.is_parking_like else 1, item.name))
    return choices


def _schedule_comment_filter_values(schedule):
    values = set()
    try:
        definition = schedule.Definition
        filters = definition.GetFilters()
    except Exception:
        return values
    for schedule_filter in filters:
        try:
            field = definition.GetField(schedule_filter.FieldId)
        except Exception:
            continue
        parameter_id = None
        try:
            parameter_id = _id_value(field.ParameterId)
        except Exception:
            pass
        field_names = []
        for getter in ('GetName',):
            try:
                field_names.append(_text(getattr(field, getter)()))
            except Exception:
                pass
        try:
            field_names.append(_text(field.ColumnHeading))
        except Exception:
            pass
        is_comments = False
        try:
            is_comments = parameter_id == int(
                DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        except Exception:
            pass
        normalized_names = [
            logic.normalize_label(name) for name in field_names if name]
        if not is_comments:
            accepted_names = set(
                logic.normalize_label(name) for name in COMMENT_PARAM_NAMES)
            is_comments = any(
                normalized in accepted_names
                for normalized in normalized_names)
        if not is_comments:
            continue
        try:
            filter_type = _text(schedule_filter.FilterType).lower()
            if 'equal' not in filter_type and u'等於' not in filter_type:
                continue
        except Exception:
            continue
        try:
            value = _text(schedule_filter.GetStringValue())
        except Exception:
            value = u''
        normalized = logic.normalize_label(value)
        if normalized:
            values.add(normalized)
    return values


def _schedule_map(doc):
    found = {}
    for schedule in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        try:
            if schedule.IsTemplate:
                continue
        except Exception:
            pass
        name = _text(schedule.Name)
        if name in dict(SCHEDULES):
            found.setdefault(name, []).append(schedule)
    problems = []
    for name, unused_kind in SCHEDULES:
        matches = found.get(name, [])
        if not matches:
            problems.append(u'缺少「{}」'.format(name))
        elif len(matches) > 1:
            problems.append(u'「{}」有 {} 張同名明細表'.format(name, len(matches)))
    if problems:
        raise Exception(
            u'停車明細表不完整，禁止改用全類別 fallback：\n{}'.format(
                u'\n'.join(problems)))
    return dict((name, found[name][0]) for name, unused_kind in SCHEDULES)


def _is_parking(element):
    try:
        return (
            element.Category is not None and
            _id_value(element.Category.Id) ==
            int(DB.BuiltInCategory.OST_Parking)
        )
    except Exception:
        try:
            return (
                _id_value(element.Category.Id) ==
                _id_value(DB.Category.GetCategory(
                    element.Document, DB.BuiltInCategory.OST_Parking).Id)
            )
        except Exception:
            return False


def _is_grouped(element):
    try:
        group_id = _id_value(element.GroupId)
        return group_id is not None and group_id >= 0
    except Exception:
        return False


def _schedule_elements(doc, schedule):
    collector = (
        DB.FilteredElementCollector(doc, schedule.Id)
        .WhereElementIsNotElementType()
    )
    try:
        collector = collector.WherePasses(
            DB.ElementCategoryFilter(DB.BuiltInCategory.OST_Parking))
    except Exception:
        pass
    return collector


def _parking_elements(doc):
    try:
        return (
            DB.FilteredElementCollector(doc)
            .WhereElementIsNotElementType()
            .OfCategory(DB.BuiltInCategory.OST_Parking)
        )
    except Exception:
        return DB.FilteredElementCollector(doc).WhereElementIsNotElementType()


def _link_name(link_instance, link_doc):
    parts = []
    try:
        parts.append(_text(link_instance.Name))
    except Exception:
        pass
    try:
        parts.append(_text(link_doc.Title))
    except Exception:
        pass
    for part in parts:
        if part:
            return part
    return u'Revit Link {}'.format(_id_value(link_instance.Id))


def collect_link_choices(doc):
    try:
        links = DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance)
    except Exception:
        return []
    choices = []
    for link in links:
        try:
            link_doc = link.GetLinkDocument()
        except Exception:
            link_doc = None
        if link_doc is None:
            continue
        choices.append(_LinkChoice(link, link_doc))
    choices.sort(key=lambda item: item.label)
    return choices


def _linked_parking_entries(doc, selected_link_ids, comment_values=None,
                            kind=None, schedule_name=None):
    selected = set(int(value) for value in (selected_link_ids or []))
    if not selected:
        return []
    try:
        links = DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance)
    except Exception:
        return []
    entries = []
    found = set()
    for link in links:
        link_id = _id_value(link.Id)
        if link_id not in selected:
            continue
        found.add(link_id)
        try:
            link_doc = link.GetLinkDocument()
        except Exception:
            link_doc = None
        if link_doc is None:
            continue
        if schedule_name:
            source_name = u'指定連結：{}｜明細表：{}'.format(
                _link_name(link, link_doc), schedule_name)
        else:
            source_name = u'指定連結：{} Parking 類別'.format(
                _link_name(link, link_doc))
        try:
            link_transform = link.GetTotalTransform()
        except Exception:
            link_transform = None
        entries.append((
            source_name,
            kind,
            _parking_elements(link_doc),
            u'link:{}'.format(link_id),
            set(comment_values or []),
            link_transform,
        ))
    missing = selected - found
    if missing:
        raise Exception(u'找不到已選取的 Revit 連結，請重新選擇。')
    return entries


def _source_entries(doc, source_mode, selected_schedule_ids,
                    selected_link_ids=None):
    entries = []
    if source_mode == SOURCE_MODE_AUTO:
        entries.append((
            u'自動偵測 Parking 類別',
            None,
            _parking_elements(doc),
            u'host',
            set(),
            None,
        ))
        entries.extend(_linked_parking_entries(doc, selected_link_ids))
        return entries

    selected = set(int(value) for value in (selected_schedule_ids or []))
    selected_links = set(int(value) for value in (selected_link_ids or []))
    if not selected and not selected_links:
        raise Exception(
            u'請至少選取一張停車明細表或一個連結模型，或改用自動偵測。')

    found = set()
    for schedule in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        schedule_id = _id_value(schedule.Id)
        if schedule_id not in selected:
            continue
        found.add(schedule_id)
        try:
            if schedule.IsTemplate:
                continue
        except Exception:
            pass
        name = _text(schedule.Name)
        schedule_kind = _schedule_kind(name)
        try:
            elements = _schedule_elements(doc, schedule)
        except Exception as error:
            raise Exception(
                u'讀取明細表「{}」的 collector 失敗：{}'.format(name, error))
        entries.append((
            name, schedule_kind, elements, u'host', set(), None))

    if selected:
        missing = selected - found
        if missing:
            raise Exception(u'找不到已選取的明細表，請重新產生預覽。')
        if not entries:
            raise Exception(u'沒有可讀取的已選取明細表。')
    # Host schedules and explicitly selected links are separate source
    # boundaries. A host schedule filter must not be projected into a linked
    # document: the same localized field can be a parking number (e.g. 611)
    # in the link instead of a classification such as "汽車停車".
    entries.extend(_linked_parking_entries(doc, selected_link_ids))
    return entries


def _classify_element(kind, element, name, width, length):
    if kind is None:
        key = logic.classify_any_space(
            width, length, name, None, logic.TOLERANCE_MM)
    else:
        key = logic.classify_space(
            kind, width, length, name, None, logic.TOLERANCE_MM)
    accessible = None
    if key is None:
        accessible = _is_accessible(element, name)
        if kind is None:
            key = logic.classify_any_space(
                width, length, name, accessible, logic.TOLERANCE_MM)
        else:
            key = logic.classify_space(
                kind, width, length, name, accessible, logic.TOLERANCE_MM)
    if key is None:
        # Name-based fallback (e.g. 中巴汽車 → 大客車) for bays whose printed
        # size does not match any standard within tolerance.
        key = logic.classify_by_name(name)
    return key, accessible


def _is_ignored_parking_helper(name, width, length):
    if width is not None or length is not None:
        return False
    normalized = logic.normalize_label(name)
    return any(hint in normalized for hint in IGNORED_PARKING_NAME_HINTS)


def collect_counts(doc, selected_level_id, source_mode=SOURCE_MODE_AUTO,
                   selected_schedule_ids=None, selected_link_ids=None,
                   selected_level_name=None, selected_level_elevation=None):
    counts = logic.empty_counts()
    unclassified = []
    ignored = []
    annotation_candidates = []
    source_counts = []
    global_seen = set()
    for (source_name, kind, elements, source_key, comment_values,
            link_transform) in _source_entries(
            doc, source_mode, selected_schedule_ids, selected_link_ids):
        seen = set()
        included = 0
        grouped = 0
        ignored_count = 0
        excluded_by_annotation = 0
        blank_annotation = 0
        for element in elements:
            element_id = _id_value(element.Id)
            unique_id = (source_key, element_id)
            if unique_id in seen or unique_id in global_seen:
                continue
            seen.add(unique_id)
            if not _is_parking(element):
                continue
            if link_transform is None:
                level_ok = _level_matches(
                    element,
                    selected_level_id,
                    selected_level_name,
                    selected_level_elevation)
            else:
                level_ok = _linked_level_matches(
                    element,
                    link_transform,
                    selected_level_name,
                    selected_level_elevation)
            if not level_ok:
                continue
            annotation = u''
            if comment_values:
                annotation = _annotation_text(element)
            if comment_values and not logic.annotation_matches(
                    annotation, comment_values):
                excluded_by_annotation += 1
                if not annotation:
                    blank_annotation += 1
                annotation_candidates.append({
                    'id': element_id,
                    '_unique_id': unique_id,
                    'schedule': source_name,
                    'annotation': annotation or u'(空白)',
                    'name': _element_name(element) or u'(無名稱)',
                })
                continue
            included += 1
            if _is_grouped(element):
                grouped += 1
            name = _element_name(element)
            width = _parameter_mm(element, (u'停車位寬', u'寬'))
            length = _parameter_mm(element, (u'停車位長', u'長'))
            if _is_ignored_parking_helper(name, width, length):
                global_seen.add(unique_id)
                ignored_count += 1
                ignored.append({
                    'id': element_id,
                    'schedule': source_name,
                    'name': name or u'(無名稱)',
                })
                continue
            key, accessible = _classify_element(
                kind, element, name, width, length)
            if key:
                global_seen.add(unique_id)
                counts[key] += 1
            else:
                unclassified.append({
                    'id': element_id,
                    '_unique_id': unique_id,
                    'schedule': source_name,
                    'name': name or u'(無名稱)',
                    'width_mm': width,
                    'length_mm': length,
                    'accessible': accessible,
                })
        source_counts.append({
            'name': source_name,
            'kind': kind or u'自動',
            'included': included,
            'grouped': grouped,
            'ignored': ignored_count,
            'annotation_filter': sorted(comment_values),
            'excluded_by_annotation': excluded_by_annotation,
            'blank_annotation': blank_annotation,
        })
    filtered_unclassified = {}
    for item in unclassified:
        unique_id = item.get('_unique_id')
        if unique_id in global_seen or unique_id in filtered_unclassified:
            continue
        filtered_unclassified[unique_id] = dict(
            (key, value) for key, value in item.items()
            if key != '_unique_id')
    filtered_candidates = {}
    for item in annotation_candidates:
        unique_id = item.get('_unique_id')
        if unique_id in global_seen or unique_id in filtered_candidates:
            continue
        filtered_candidates[unique_id] = dict(
            (key, value) for key, value in item.items()
            if key != '_unique_id')
    return {
        'counts': counts,
        'unclassified': list(filtered_unclassified.values()),
        'ignored': ignored,
        'annotation_candidates': list(filtered_candidates.values()),
        'source_counts': source_counts,
    }


def _selected_host_schedule_entries(doc, selected_schedule_ids):
    selected = set(int(value) for value in (selected_schedule_ids or []))
    if not selected:
        raise Exception(u'明細表模式需要先選取至少一張停車明細表。')
    found = set()
    entries = []
    for schedule in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        schedule_id = _id_value(schedule.Id)
        if schedule_id not in selected:
            continue
        found.add(schedule_id)
        try:
            if schedule.IsTemplate:
                continue
        except Exception:
            pass
        name = _text(schedule.Name)
        entries.append((
            name,
            _schedule_kind(name),
            _schedule_elements(doc, schedule),
        ))
    missing = selected - found
    if missing:
        raise Exception(u'找不到已選取的明細表，請重新產生預覽。')
    if not entries:
        raise Exception(u'沒有可讀取的已選取明細表。')
    return entries


def _level_scope_text(source_doc, allowed_level_ids):
    if allowed_level_ids is None:
        return u'全部樓層'
    names = []
    for level_id in sorted(allowed_level_ids):
        name = u'Id {}'.format(level_id)
        try:
            level = source_doc.GetElement(DB.ElementId(int(level_id)))
            if level is not None:
                name = _element_name(level) or name
        except Exception:
            pass
        names.append(name)
    return u'、'.join(names) or u'全部樓層'


def collect_counts_for_options(doc, options, source_mode=SOURCE_MODE_AUTO,
                               selected_schedule_ids=None):
    """Count the exact host/link/level scope selected by the shared UI."""
    counts = logic.empty_counts()
    unclassified_by_uid = {}
    ignored_by_uid = {}
    candidate_by_uid = {}
    details_by_uid = {}
    source_counts = []
    global_seen = set()
    sources = list(takeoff_entry.iter_sources(doc, options))
    host_in_scope = any(record[4] is None for record in sources)
    host_schedule_entries = None
    if source_mode == SOURCE_MODE_SCHEDULES and host_in_scope:
        host_schedule_entries = _selected_host_schedule_entries(
            doc, selected_schedule_ids)

    for (source_key, source_label, source_doc, allowed_level_ids,
         link_instance_id) in sources:
        level_catalog = _level_catalog(source_doc)
        if (link_instance_id is None
                and source_mode == SOURCE_MODE_SCHEDULES):
            entries = host_schedule_entries
        else:
            name = (
                u'主模型 Parking 類別'
                if link_instance_id is None else
                u'指定連結：{} Parking 類別'.format(source_label))
            entries = [(name, None, _parking_elements(source_doc))]
        for source_name, kind, elements in entries:
            seen = set()
            included = 0
            grouped = 0
            ignored_count = 0
            excluded_by_level = 0
            level_mismatch = 0
            for element in elements:
                element_id = _id_value(element.Id)
                unique_id = (source_key, element_id)
                if unique_id in seen or unique_id in global_seen:
                    continue
                seen.add(unique_id)
                if not _is_parking(element):
                    continue
                # The Level parameter alone is not trustworthy: bays copied
                # between floors, or placed on a shared work plane, keep one
                # level for the whole model. Where the bay physically sits
                # wins, and the parameter is only a fallback.
                element_level_id = _level_id(element)
                elevation_mm = _element_base_elevation_mm(element)
                geometric_level_ids = logic.resolve_geometric_level_ids(
                    elevation_mm, level_catalog)
                basis = logic.level_basis(
                    element_level_id, geometric_level_ids)
                if basis == logic.LEVEL_BASIS_GEOMETRIC:
                    level_mismatch += 1
                if geometric_level_ids:
                    effective_level_ids = list(geometric_level_ids)
                elif element_level_id is not None:
                    effective_level_ids = [element_level_id]
                else:
                    effective_level_ids = []
                if allowed_level_ids is not None and not any(
                        value in allowed_level_ids
                        for value in effective_level_ids):
                    excluded_by_level += 1
                    continue
                # Where two levels share an elevation, report the one the user
                # actually ticked.
                geometric_level_id = None
                for value in geometric_level_ids:
                    geometric_level_id = value
                    if (allowed_level_ids is None
                            or value in allowed_level_ids):
                        break
                included += 1
                grouped_value = _is_grouped(element)
                if grouped_value:
                    grouped += 1
                name = _element_name(element)
                width = _parameter_mm(element, (u'停車位寬', u'寬'))
                length = _parameter_mm(element, (u'停車位長', u'長'))
                base_detail = {
                    'source_key': source_key,
                    'source_name': source_name,
                    'level_id': element_level_id,
                    'level_name': _catalog_level_name(
                        level_catalog, element_level_id),
                    'geometric_level_id': geometric_level_id,
                    'geometric_level_name': _catalog_level_name(
                        level_catalog, geometric_level_id),
                    'elevation_mm': elevation_mm,
                    'level_basis': basis,
                    'element_id': element_id,
                    'name': name or u'(無名稱)',
                    'width_mm': width,
                    'length_mm': length,
                    'grouped': grouped_value,
                }
                if _is_ignored_parking_helper(name, width, length):
                    global_seen.add(unique_id)
                    ignored_count += 1
                    ignored_by_uid[unique_id] = {
                        'id': element_id,
                        'source_key': source_key,
                        'schedule': source_name,
                        'name': name or u'(無名稱)',
                    }
                    detail = dict(base_detail)
                    detail.update({
                        'classification_key': u'',
                        'classification_label': u'',
                        'status': u'忽略非車位元件',
                    })
                    details_by_uid[unique_id] = detail
                    continue
                key, accessible = _classify_element(
                    kind, element, name, width, length)
                if key:
                    global_seen.add(unique_id)
                    counts[key] += 1
                    unclassified_by_uid.pop(unique_id, None)
                    candidate_by_uid.pop(unique_id, None)
                    detail = dict(base_detail)
                    detail.update({
                        'classification_key': key,
                        'classification_label':
                            logic.ITEM_BY_KEY[key]['label'],
                        'status': u'已分類',
                    })
                    details_by_uid[unique_id] = detail
                else:
                    unclassified_by_uid.setdefault(unique_id, {
                        'id': element_id,
                        'source_key': source_key,
                        'schedule': source_name,
                        'name': name or u'(無名稱)',
                        'width_mm': width,
                        'length_mm': length,
                        'accessible': accessible,
                    })
                    detail = dict(base_detail)
                    detail.update({
                        'classification_key': u'',
                        'classification_label': u'',
                        'status': u'未分類',
                    })
                    details_by_uid.setdefault(unique_id, detail)
            source_counts.append({
                'source_key': source_key,
                'name': source_name,
                'kind': kind or u'自動',
                'levels': _level_scope_text(
                    source_doc, allowed_level_ids),
                'included': included,
                'grouped': grouped,
                'ignored': ignored_count,
                'excluded_by_level': excluded_by_level,
                'level_mismatch': level_mismatch,
                'annotation_filter': [],
                'excluded_by_annotation': 0,
                'blank_annotation': 0,
            })

    for unique_id in list(unclassified_by_uid):
        if unique_id in global_seen:
            unclassified_by_uid.pop(unique_id, None)
    return {
        'counts': counts,
        'unclassified': list(unclassified_by_uid.values()),
        'ignored': list(ignored_by_uid.values()),
        'annotation_candidates': list(candidate_by_uid.values()),
        'source_counts': source_counts,
        'details': list(details_by_uid.values()),
    }


def _excel_open(path, read_only):
    xl_type = Type.GetTypeFromProgID('Excel.Application')
    if xl_type is None:
        raise Exception(u'找不到 Excel COM；此功能需要本機安裝 Microsoft Excel。')
    excel = Activator.CreateInstance(xl_type)
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        excel.EnableEvents = False
        excel.AskToUpdateLinks = False
        excel.AutomationSecurity = 3
    except Exception:
        pass
    try:
        workbook = excel.Workbooks.Open(path, 0, bool(read_only))
    except Exception:
        try:
            excel.Quit()
        except Exception:
            pass
        raise
    return excel, workbook


def _release_com(value):
    if value is None:
        return
    try:
        Marshal.FinalReleaseComObject(value)
    except Exception:
        try:
            Marshal.ReleaseComObject(value)
        except Exception:
            pass


def _excel_close(excel, workbook):
    try:
        if workbook is not None:
            try:
                workbook.Close(False)
            finally:
                _release_com(workbook)
    finally:
        if excel is not None:
            try:
                excel.Quit()
            except Exception:
                pass
            _release_com(excel)
        try:
            GC.Collect()
            GC.WaitForPendingFinalizers()
            GC.Collect()
            GC.WaitForPendingFinalizers()
        except Exception:
            pass


def _sheet(wb, requested):
    wanted = _text(requested)
    for worksheet in wb.Worksheets:
        if _text(worksheet.Name).strip() == wanted:
            return worksheet
    raise Exception(u'Excel 找不到分頁「{}」。'.format(requested))


def _has_formula(cell):
    try:
        return bool(cell.HasFormula)
    except Exception:
        return _text(cell.Formula).startswith(u'=')


def _formula(cell):
    return _text(cell.Formula) if _has_formula(cell) else u''


def _number(value):
    try:
        return float(value)
    except Exception:
        text = _text(value).replace(u',', u'')
        match = re.search(r'-?\d+(?:\.\d+)?', text)
        return float(match.group(0)) if match else None


def _row_formula_shape_ok(ws, row):
    formulas = [_formula(ws.Cells(row, col)) for col in (8, 9, 10)]
    return logic.row_formula_shape_ok(row, formulas)


def _format_formula_for_message(formula):
    text = _text(formula)
    return text if text else u'(空白)'


def _short_path(path):
    text = _text(path)
    folder, name = os.path.split(text)
    if not folder:
        return text
    return u'{}\\{}'.format(os.path.basename(folder), name)


def _formula_blocker(ws, row):
    formulas = tuple(_formula(ws.Cells(row, col)) for col in (8, 9, 10))
    if logic.row_formula_shape_ok(row, formulas):
        return None, formulas
    return (
        u'{} 第 {} 列 H/I/J 公式鏈無法確認：H：{}；I：{}；J：{}'.format(
            OTHER_SHEET,
            row,
            _format_formula_for_message(formulas[0]),
            _format_formula_for_message(formulas[1]),
            _format_formula_for_message(formulas[2]),
        ),
        formulas,
    )


def _matrix_value(matrix, row, col, row_count, col_count):
    if row_count == 1 and col_count == 1:
        return matrix
    try:
        return matrix.GetValue(row, col)
    except Exception:
        try:
            return matrix[row - 1][col - 1]
        except Exception:
            return None


def _find_rows(ws):
    used = ws.UsedRange
    first_row = max(1, int(used.Row))
    last_row = min(2000, first_row + int(used.Rows.Count) - 1)
    row_count = last_row - first_row + 1
    col_count = 7
    values = ws.Range(
        ws.Cells(first_row, 1), ws.Cells(last_row, col_count)).Value2
    rows = []
    for row_offset in range(1, row_count + 1):
        row = first_row + row_offset - 1
        parts = []
        for col in range(1, col_count + 1):
            value = _text(_matrix_value(
                values, row_offset, col, row_count, col_count))
            if value:
                parts.append(value)
        if parts:
            rows.append((row, u' '.join(parts)))
    try:
        return logic.find_unique_item_rows(rows)
    except ValueError as error:
        raise Exception(_text(error))


def _subtotal_references_other(wb):
    ws = _sheet(wb, SUBTOTAL_SHEET)
    used = ws.UsedRange
    first_row = max(1, int(used.Row))
    first_col = max(1, int(used.Column))
    last_row = min(3000, first_row + int(used.Rows.Count) - 1)
    last_col = min(100, first_col + int(used.Columns.Count) - 1)
    row_count = last_row - first_row + 1
    col_count = last_col - first_col + 1
    needle = logic.normalize_label(OTHER_SHEET)
    formulas = ws.Range(
        ws.Cells(first_row, first_col),
        ws.Cells(last_row, last_col)).Formula
    for row_offset in range(1, row_count + 1):
        for col_offset in range(1, col_count + 1):
            formula = _text(_matrix_value(
                formulas, row_offset, col_offset, row_count, col_count))
            if formula.startswith(u'=') and needle in logic.normalize_label(formula):
                return True
    return False


def inspect_workbook(path):
    if not path or not os.path.isfile(path):
        raise Exception(u'Excel 路徑不存在。')
    if os.path.splitext(path)[1].lower() not in ('.xls', '.xlsx'):
        raise Exception(u'請選擇 .xls 或 .xlsx 檔案。')
    excel = workbook = None
    try:
        excel, workbook = _excel_open(path, True)
        ws = _sheet(workbook, OTHER_SHEET)
        rows = _find_rows(ws)
        old = {}
        formulas = {}
        input_formulas = {}
        protected_inputs = []
        blockers = []
        for key, row in rows.items():
            if _has_formula(ws.Cells(row, OTHER_COUNT_COL)):
                formula = _formula(ws.Cells(row, OTHER_COUNT_COL))
                protected_inputs.append(
                    u'{} 保留公式：{}'.format(_addr(OTHER_SHEET, OTHER_COUNT_COL, row), formula))
                if not logic.protected_input_formula_shape_ok(
                        key, row, formula, rows):
                    blockers.append(
                        u'{} 是尚未列入白名單的公式，禁止覆寫：{}'.format(_addr(OTHER_SHEET, OTHER_COUNT_COL, row), formula))
            if key == 'wheel_stop' and _has_formula(ws.Cells(row, OTHER_WHEEL_COL)):
                blockers.append(
                    u'{} 是公式，禁止覆寫。'.format(_addr(OTHER_SHEET, OTHER_WHEEL_COL, row)))
            old[key] = {
                'f': ws.Cells(row, OTHER_COUNT_COL).Value2,
                'g': ws.Cells(row, OTHER_WHEEL_COL).Value2,
            }
            input_formulas[key] = {
                'f': _formula(ws.Cells(row, OTHER_COUNT_COL)),
                'g': _formula(ws.Cells(row, OTHER_WHEEL_COL)),
            }
            blocker, formulas[key] = _formula_blocker(ws, row)
            if blocker:
                blockers.append(blocker)
        if not _subtotal_references_other(workbook):
            blockers.append(u'「小計」找不到引用「其他數量」的公式，禁止更新。')
        return {
            'rows': rows,
            'old': old,
            'formulas': formulas,
            'input_formulas': input_formulas,
            'protected_inputs': protected_inputs,
            'blockers': blockers,
        }
    finally:
        _excel_close(excel, workbook)


def _wheel_stop_formula_multiplier(inspection):
    try:
        formula = inspection['input_formulas']['wheel_stop']['f']
    except Exception:
        return None
    return logic.wheel_stop_formula_multiplier(formula, inspection.get('rows'))


def _wheel_stop_g_target(inspection, multiplier):
    return 1 if _wheel_stop_formula_multiplier(inspection) else multiplier


def _target_f_value(key, counts, multiplier, inspection):
    car_total = sum(int(counts[car_key]) for car_key in logic.CAR_KEYS)
    if key == 'wheel_stop':
        if _wheel_stop_formula_multiplier(inspection):
            return car_total * int(multiplier)
        return car_total
    return int(counts[key])


def _formula_result_blockers(inspection, counts, multiplier):
    expected, unused_car_total, unused_multiplier = _expected_values(
        counts, multiplier)
    blockers = []
    embedded_multiplier = _wheel_stop_formula_multiplier(inspection)
    if embedded_multiplier and int(embedded_multiplier) != int(multiplier):
        row = inspection['rows']['wheel_stop']
        blockers.append(
            u'{} 公式已內含輪檔倍率 {}，但 UI 選擇 {}，禁止更新。'.format(_addr(OTHER_SHEET, OTHER_COUNT_COL, row), embedded_multiplier, multiplier))
    for key, row in inspection.get('rows', {}).items():
        formula = inspection['input_formulas'][key]['f']
        if not formula or (key == 'wheel_stop' and embedded_multiplier):
            continue
        actual = _number(inspection['old'][key]['f'])
        target = expected[key]
        if actual is None or abs(actual - target) > 0.0001:
            blockers.append(
                u'{} 保留公式結果為 {}，但本次預期 {}，禁止更新。'.format(_addr(OTHER_SHEET, OTHER_COUNT_COL, row), _format_number(inspection['old'][key]['f']),
                    _format_number(target)))
    return blockers


def _backup_path(path):
    stem, extension = os.path.splitext(path)
    return u'{}_backup_{}{}'.format(
        stem, datetime.now().strftime('%Y%m%d-%H%M%S'), extension)


def _expected_values(counts, multiplier):
    car_total, multiplier, wheel_total = logic.wheel_stop_values(
        counts, multiplier)
    values = dict((item['key'], int(counts[item['key']])) for item in logic.ITEMS)
    values['wheel_stop'] = wheel_total
    return values, car_total, multiplier


def _assert_can_write(path):
    if not os.access(path, os.W_OK):
        raise Exception(u'Excel 檔案是唯讀，禁止更新。')
    excel = workbook = None
    try:
        excel, workbook = _excel_open(path, False)
        if bool(workbook.ReadOnly):
            raise Exception(
                u'Excel 檔目前被鎖定或以唯讀方式開啟，請先關閉後重試。')
    finally:
        _excel_close(excel, workbook)


def update_workbook(path, inspection, counts, multiplier, backup):
    if inspection.get('blockers'):
        raise Exception(
            u'Excel 檢查仍有阻擋項，未寫入：\n{}'.format(
                u'\n'.join(inspection['blockers'])))
    formula_blockers = _formula_result_blockers(inspection, counts, multiplier)
    if formula_blockers:
        raise Exception(
            u'Excel 檢查仍有阻擋項，未寫入：\n{}'.format(
                u'\n'.join(formula_blockers)))
    expected, unused_car_total, multiplier = _expected_values(
        counts, multiplier)
    wheel_g_target = _wheel_stop_g_target(inspection, multiplier)
    _assert_can_write(path)
    shutil.copy2(path, backup)

    excel = workbook = None
    try:
        excel, workbook = _excel_open(path, False)
        if bool(workbook.ReadOnly):
            raise Exception(u'Excel 在備份後遭鎖定，未寫入。')
        ws = _sheet(workbook, OTHER_SHEET)
        current_rows = _find_rows(ws)
        if current_rows != inspection['rows']:
            raise Exception(u'Excel 工項列自預覽後已改變，未寫入。')
        for key, row in current_rows.items():
            current_input_formulas = {
                'f': _formula(ws.Cells(row, OTHER_COUNT_COL)),
                'g': _formula(ws.Cells(row, OTHER_WHEEL_COL)),
            }
            if current_input_formulas != inspection['input_formulas'][key]:
                raise Exception(
                    u'{} 第 {} 列 F/G 公式自預覽後已改變，未寫入。'.format(
                        OTHER_SHEET, row))
            if key == 'wheel_stop' and _has_formula(ws.Cells(row, OTHER_WHEEL_COL)):
                raise Exception(
                    u'{} 自預覽後變成公式，未寫入。'.format(_addr(OTHER_SHEET, OTHER_WHEEL_COL, row)))
            current_formulas = tuple(
                _formula(ws.Cells(row, col)) for col in (8, 9, 10))
            if current_formulas != inspection['formulas'][key]:
                raise Exception(
                    u'{} 第 {} 列 H/I/J 公式自預覽後已改變，未寫入。'.format(
                        OTHER_SHEET, row))
            if not logic.row_formula_shape_ok(row, current_formulas):
                raise Exception(
                    u'{} 第 {} 列 H 未直接引用同列 F/G，未寫入。'.format(
                        OTHER_SHEET, row))
            current_f = ws.Cells(row, OTHER_COUNT_COL).Value2
            current_g = ws.Cells(row, OTHER_WHEEL_COL).Value2
            if (current_f != inspection['old'][key]['f'] or
                    current_g != inspection['old'][key]['g']):
                raise Exception(
                    u'{} 第 {} 列 F/G 自預覽後已改變，未寫入。'.format(
                        OTHER_SHEET, row))
        for item in logic.ITEMS:
            row = current_rows[item['key']]
            if not _has_formula(ws.Cells(row, OTHER_COUNT_COL)):
                ws.Cells(row, OTHER_COUNT_COL).Value2 = expected[item['key']]
        wheel_row = current_rows['wheel_stop']
        if not _has_formula(ws.Cells(wheel_row, 6)):
            ws.Cells(wheel_row, 6).Value2 = sum(
                int(counts[key]) for key in logic.CAR_KEYS)
        ws.Cells(wheel_row, 7).Value2 = wheel_g_target
        try:
            workbook.Application.Calculation = XL_CALCULATION_AUTOMATIC
        except Exception:
            pass
        workbook.Application.Calculate()
        pre_save_errors = []
        for key, row in current_rows.items():
            target_f = _target_f_value(key, counts, multiplier, inspection)
            actual_f = _number(ws.Cells(row, OTHER_COUNT_COL).Value2)
            if actual_f is None or abs(actual_f - target_f) > 0.0001:
                pre_save_errors.append(
                    u'F{} 預期 {}，公式／輸入結果為 {}'.format(
                        row, target_f, ws.Cells(row, OTHER_COUNT_COL).Value2))
        actual_g = _number(ws.Cells(wheel_row, 7).Value2)
        if actual_g is None or abs(actual_g - wheel_g_target) > 0.0001:
            pre_save_errors.append(
                u'G{} 預期 {}，實際 {}'.format(
                    wheel_row, wheel_g_target, ws.Cells(wheel_row, 7).Value2))
        if pre_save_errors:
            raise Exception(
                u'Excel 重算結果不符，已在存檔前取消：\n{}'.format(
                    u'\n'.join(pre_save_errors)))
        workbook.Save()
    finally:
        _excel_close(excel, workbook)

    verified = inspect_workbook(path)
    errors = []
    if verified.get('blockers'):
        errors.extend(verified['blockers'])
    if verified.get('input_formulas') != inspection.get('input_formulas'):
        errors.append(u'F/G 輸入公式已改變')
    for key, row in verified['rows'].items():
        actual_f = _number(verified['old'][key]['f'])
        target_f = _target_f_value(key, counts, multiplier, inspection)
        if actual_f is None or abs(actual_f - target_f) > 0.0001:
            errors.append(u'F{} 預期 {}，實際 {}'.format(
                row, target_f, verified['old'][key]['f']))
        if key == 'wheel_stop':
            actual_g = _number(verified['old'][key]['g'])
            if actual_g is None or abs(actual_g - wheel_g_target) > 0.0001:
                errors.append(u'G{} 預期 {}，實際 {}'.format(
                    row, wheel_g_target, verified['old'][key]['g']))
        if verified['formulas'][key] != inspection['formulas'][key]:
            errors.append(u'第 {} 列 H/I/J 公式已改變'.format(row))
    if errors:
        raise Exception(
            u'Excel 已存檔但重新開啟驗證失敗；請由備份復原：\n{}'.format(
                u'\n'.join(errors)))


class _LevelChoice(object):
    def __init__(self, level):
        self.level = level
        self.name = _text(level.Name)
        self.element_id = _id_value(level.Id)
        try:
            self.elevation = float(level.Elevation)
        except Exception:
            self.elevation = None
        self.label = u'{}  (Id {})'.format(self.name, self.element_id)

    def __str__(self):
        return self.label


class _LinkChoice(object):
    def __init__(self, link_instance, link_doc):
        self.link_instance = link_instance
        self.link_doc = link_doc
        self.element_id = _id_value(link_instance.Id)
        self.name = _link_name(link_instance, link_doc)
        self.label = u'{}  (連結實例 Id {})'.format(
            self.name, self.element_id)

    def __str__(self):
        return self.label


class _ScheduleChoice(object):
    def __init__(self, schedule):
        self.schedule = schedule
        self.name = _text(schedule.Name)
        self.element_id = _id_value(schedule.Id)
        self.kind = _schedule_kind(self.name)
        self.is_parking_like = _schedule_name_matches(self.name)
        kind_label = {
            'bus': u'大客車',
            'car': u'汽車',
            'motorcycle': u'機車',
        }.get(
            self.kind,
            u'停車候選' if self.is_parking_like else u'一般明細表',
        )
        self.label = u'{}  ({}, Id {})'.format(
            self.name, kind_label, self.element_id)

    def __str__(self):
        return self.label


def _format_number(value):
    number = _number(value)
    if number is None:
        return u'(空白)'
    if abs(number - round(number)) < 0.000001:
        return str(int(round(number)))
    return u'{:.3f}'.format(number)


def _level_scope_note(source):
    """Say what the level filter did, so an over/under count is never silent."""
    parts = []
    if int(source.get('excluded_by_level') or 0):
        parts.append(u'依樓層排除 {} 個'.format(
            int(source['excluded_by_level'])))
    if int(source.get('level_mismatch') or 0):
        parts.append(u'樓層參數與高程不符 {} 個（已依高程歸層）'.format(
            int(source['level_mismatch'])))
    return u'，{}'.format(u'，'.join(parts)) if parts else u''


def _preview_text(path, level_name, multiplier, takeoff, inspection):
    counts = takeoff['counts']
    unused_values, car_total, multiplier = _expected_values(counts, multiplier)
    lines = [
        u'Excel：{}'.format(path),
        u'Revit 樓層：{}'.format(level_name),
        u'輪檔倍率：{} 個／汽車位'.format(multiplier),
        u'',
    ]
    lines.append(u'資料來源：')
    for source in takeoff.get('source_counts', []):
        ignored_text = (
            u'，已忽略非車位 {} 個'.format(source.get('ignored', 0))
            if source.get('ignored', 0) else u'')
        annotation_text = u''
        if source.get('annotation_filter'):
            annotation_text = u'，標註篩選 [{}]'.format(
                u'、'.join(source['annotation_filter']))
        if source.get('excluded_by_annotation', 0):
            annotation_text += u'，排除 {} 個（其中空白 {} 個）'.format(
                source['excluded_by_annotation'],
                source.get('blank_annotation', 0))
        levels_text = (
            u'（{}）'.format(source['levels']) if source.get('levels') else u'')
        lines.append(u'- {}{}：{} 個 Parking 元件，群組內 {} 個{}{}{}'.format(
            source['name'], levels_text, source['included'],
            source['grouped'], ignored_text, annotation_text,
            _level_scope_note(source)))
    lines.append(u'')
    for item in logic.ITEMS:
        row = inspection['rows'][item['key']]
        old = inspection['old'][item['key']]['f']
        lines.append(u'{:<22} {:>5} 位  ({}{} 舊值 {})'.format(
            item['label'], counts[item['key']], _col(OTHER_COUNT_COL), row,
            _format_number(old)))
    wheel_row = inspection['rows']['wheel_stop']
    wheel_formula_multiplier = _wheel_stop_formula_multiplier(inspection)
    wheel_g = 1 if wheel_formula_multiplier else multiplier
    lines.extend([
        u'',
        u'汽車合計（含大客車）：{} 位'.format(car_total),
        u'塑膠車輪檔：{} × {} = {} 個  ({}{}/{}{})'.format(
            car_total, multiplier, car_total * multiplier,
            _col(OTHER_COUNT_COL), wheel_row,
            _col(OTHER_WHEEL_COL), wheel_row),
    ])
    if wheel_formula_multiplier:
        lines.append(
            u'注意：{0}{1} 公式已內含輪檔倍率 {2}；更新時保留 {0}{1}，'
            u'{3}{1} 寫入 {4}，避免重複相乘。'.format(
                _col(OTHER_COUNT_COL), wheel_row, wheel_formula_multiplier,
                _col(OTHER_WHEEL_COL), wheel_g))
    grouped_total = sum(
        int(source.get('grouped', 0))
        for source in takeoff.get('source_counts', []))
    if grouped_total:
        lines.extend([
            u'',
            u'群組內車位：{} 位（已走快速分類；仍按明細表元素逐位計算）'.format(
                grouped_total),
        ])
    if inspection.get('protected_inputs'):
        lines.extend([
            u'',
            u'Excel 受保護輸入公式（保留、不覆寫）：',
        ])
        for item in inspection['protected_inputs']:
            lines.append(u'- {}'.format(item))
    if inspection.get('blockers'):
        lines.extend([
            u'',
            u'Excel 公式/索引檢查：{} 項需處理（禁止更新）：'.format(
                len(inspection['blockers'])),
        ])
        for issue in inspection['blockers'][:10]:
            lines.append(u'- {}'.format(issue))
    if takeoff.get('ignored'):
        lines.extend([
            u'',
            u'已忽略非車位 Parking 元件：{} 個（最多顯示 10 筆）：'.format(
                len(takeoff['ignored'])),
        ])
        for item in takeoff['ignored'][:10]:
            lines.append(u'- Id {id}｜{schedule}｜{name}'.format(
                id=item['id'],
                schedule=item['schedule'],
                name=item['name'],
            ))
    if takeoff.get('annotation_candidates'):
        lines.extend([
            u'',
            u'未納入的標註候選：{} 個（不計入數量；最多顯示 10 筆）：'.format(
                len(takeoff['annotation_candidates'])),
            u'請檢查空白標註是否為漏填；修正 Revit 後重新預覽即可納入。',
        ])
        for item in takeoff['annotation_candidates'][:10]:
            lines.append(
                u'- Id {id}｜{schedule}｜標註 {annotation}｜{name}'.format(
                    id=item['id'],
                    schedule=item['schedule'],
                    annotation=item['annotation'],
                    name=item['name'],
                ))
    if takeoff['unclassified']:
        lines.extend([
            u'',
            u'未分類 {} 筆（可預覽，禁止寫入；最多顯示 10 筆）：'.format(
                len(takeoff['unclassified'])),
        ])
        for item in takeoff['unclassified'][:10]:
            lines.append(
                u'- Id {id}｜{schedule}｜{width}×{length} mm｜{name}'.format(
                    id=item['id'],
                    schedule=item['schedule'],
                    width=_format_number(item['width_mm']),
                    length=_format_number(item['length_mm']),
                    name=item['name'],
                )
            )
    else:
        lines.extend([u'', u'未分類：0 筆，可更新。'])
    return u'\n'.join(lines)


class ParkingExcelWindow(forms.WPFWindow):
    def __init__(self, doc, levels, entry_options):
        xaml = os.path.join(
            os.path.dirname(__file__), '..', 'MCP_Macros.tab',
            'Takeoff.panel', 'ParkingExcel.pushbutton', 'ParkingExcel.xaml')
        forms.WPFWindow.__init__(self, os.path.abspath(xaml))
        self.doc = doc
        self.entry_options = dict(entry_options or {})
        self.standalone_mode = (
            takeoff_standalone.entry_mode(self.entry_options)
            == takeoff_standalone.MODE_STANDALONE)
        self.levels = [_LevelChoice(level) for level in levels]
        selected_level_count = len(
            self.entry_options.get('selected_level_keys') or [])
        self.level_labels = [
            (u'共用入口已選 {} 個逐來源樓層條件'.format(
                selected_level_count)
             if selected_level_count else
             u'共用入口未選樓層：每個來源皆抓全部樓層')]
        self.levelCombo.ItemsSource = self.level_labels
        self.schedules = collect_parking_schedules(doc)
        self.schedule_labels = [choice.label for choice in self.schedules]
        self.links = collect_link_choices(doc)
        self.link_labels = [choice.label for choice in self.links]
        self.selected_schedule_ids = []
        self.selected_link_ids = list(
            self.entry_options.get('selected_link_ids') or [])
        self.result = None
        self.levelCombo.SelectedIndex = 0
        self.levelCombo.IsEnabled = False
        self.sourceModeCombo.SelectedIndex = 1 if self.schedules else 0
        self._sync_source_controls()
        self.browseButton.Click += self.browse_clicked
        self.previewButton.Click += self.preview_clicked
        self.updateButton.Click += self.update_clicked
        self.cancelButton.Click += self.cancel_clicked
        self.pathBox.TextChanged += self.invalidate_preview
        self.levelCombo.SelectionChanged += self.invalidate_preview
        self.multiplierCombo.SelectionChanged += self.invalidate_preview
        self.sourceModeCombo.SelectionChanged += self.source_mode_changed
        self.selectSchedulesButton.Click += self.select_schedules_clicked
        self.selectLinksButton.Click += self.select_links_clicked
        self.pathBox.Text = (
            self.entry_options.get('workbook_path')
            or u'（未選主要 Excel，將另存新的 .xlsx）')
        self.pathBox.IsReadOnly = True
        self.browseButton.IsEnabled = False
        self.selectLinksButton.IsEnabled = False
        if self.standalone_mode:
            self.updateButton.Content = u'匯出 Excel'

    def _multiplier(self):
        selected = self.multiplierCombo.SelectedItem
        return int(_text(selected.Content))

    def _level_choice(self):
        index = int(self.levelCombo.SelectedIndex)
        if index < 0 or index >= len(self.levels):
            return None
        return self.levels[index]

    def _source_mode(self):
        if int(self.sourceModeCombo.SelectedIndex) == 1:
            return SOURCE_MODE_SCHEDULES
        return SOURCE_MODE_AUTO

    def _selected_schedule_ids(self):
        return list(self.selected_schedule_ids)

    def _selected_link_ids(self):
        return list(self.selected_link_ids)

    def _selected_labels(self, choices, selected_ids):
        selected = set(selected_ids)
        return [
            choice.label for choice in choices
            if choice.element_id in selected]

    def _summary(self, choices, selected_ids, empty_text):
        labels = self._selected_labels(choices, selected_ids)
        if not labels:
            return empty_text
        if len(labels) == 1:
            return labels[0]
        return u'已選取 {} 項：{}'.format(
            len(labels), u'；'.join(labels[:2]))

    def _sync_source_controls(self):
        schedule_mode = self._source_mode() == SOURCE_MODE_SCHEDULES
        self.selectSchedulesButton.IsEnabled = schedule_mode
        if not self.schedules:
            self.scheduleHintText.Text = u'目前沒有可選取的明細表；請使用自動偵測。'
        elif schedule_mode:
            self.scheduleHintText.Text = (
                u'主模型依明細表計數；指定連結則直接依樓層與停車位尺寸分類。')
        else:
            self.scheduleHintText.Text = (
                u'自動模式不需選取；會統計所選樓層所有 Parking 類別元素。')
        if schedule_mode:
            self.scheduleSummaryText.Text = self._summary(
                self.schedules,
                self.selected_schedule_ids,
                u'尚未選取明細表')
        else:
            self.scheduleSummaryText.Text = u'自動模式不使用明細表'
        self.linkSummaryText.Text = self._summary(
            self.links,
            self.selected_link_ids,
            u'未選取連結模型（只計算主模型）')
        self.selectLinksButton.IsEnabled = False

    def source_mode_changed(self, sender=None, args=None):
        self._sync_source_controls()
        self.invalidate_preview(sender, args)

    def select_schedules_clicked(self, sender, args):
        selected_ids = set(self.selected_schedule_ids)
        options = [
            forms.TemplateListItem(
                choice.label,
                checked=choice.element_id in selected_ids)
            for choice in self.schedules]
        selected = forms.SelectFromList.show(
            options,
            title=u'選擇停車明細表',
            button_name=u'使用選取的明細表',
            multiselect=True,
            width=760,
            height=650,
        )
        if selected is None:
            return
        selected_labels = set(
            _text(getattr(item, 'item', item)) for item in selected)
        self.selected_schedule_ids = [
            choice.element_id for choice in self.schedules
            if choice.label in selected_labels]
        self._sync_source_controls()
        self.invalidate_preview(sender, args)

    def select_links_clicked(self, sender, args):
        selected_ids = set(self.selected_link_ids)
        options = [
            forms.TemplateListItem(
                choice.label,
                checked=choice.element_id in selected_ids)
            for choice in self.links]
        selected = forms.SelectFromList.show(
            options,
            title=u'選擇要納入的 Revit 連結模型',
            button_name=u'使用選取的連結模型',
            multiselect=True,
            width=760,
            height=600,
        )
        if selected is None:
            return
        selected_labels = set(
            _text(getattr(item, 'item', item)) for item in selected)
        self.selected_link_ids = [
            choice.element_id for choice in self.links
            if choice.label in selected_labels]
        self._sync_source_controls()
        self.invalidate_preview(sender, args)

    def invalidate_preview(self, sender=None, args=None):
        self.result = None
        self.updateButton.IsEnabled = False
        self.statusText.Text = u'設定已變更，請重新產生預覽。'

    def browse_clicked(self, sender, args):
        return

    def preview_clicked(self, sender, args):
        path = self.entry_options.get('workbook_path')
        try:
            source_mode = self._source_mode()
            selected_schedule_ids = self._selected_schedule_ids()
            selected_link_ids = self._selected_link_ids()
            takeoff = collect_counts_for_options(
                self.doc,
                self.entry_options,
                source_mode,
                selected_schedule_ids,
            )
            multiplier = self._multiplier()
            if self.standalone_mode:
                tables = logic.standalone_tables(takeoff, multiplier)
                lines = [
                    u'輸出模式：建立新的 standalone .xlsx',
                    u'輪檔倍率：{} 個／汽車位'.format(multiplier),
                    u'',
                    u'資料來源：',
                ]
                for source in takeoff.get('source_counts') or []:
                    lines.append(
                        u'- {}｜{}｜{} 個 Parking 元件{}'.format(
                            source.get('source_key'),
                            source.get('levels'),
                            source.get('included'),
                            _level_scope_note(source)))
                lines.extend([
                    u'',
                    u'分類明細：{} 列'.format(len(tables['detail_rows'])),
                    u'未分類：{} 個'.format(len(takeoff['unclassified'])),
                    u'分頁：數量明細／公式摘要／稽核',
                ])
                self.previewBox.Text = u'\n'.join(lines)
                self.result = {
                    'mode': takeoff_standalone.MODE_STANDALONE,
                    'multiplier': multiplier,
                    'takeoff': takeoff,
                    'tables': tables,
                }
                if takeoff['unclassified']:
                    self.updateButton.IsEnabled = True
                    self.statusText.Text = (
                        u'有未分類車位；可匯出並於稽核分頁查看 BLOCK。')
                else:
                    self.updateButton.IsEnabled = True
                    self.statusText.Text = u'預覽通過，可另存新的 Excel。'
                return
            inspection = inspect_workbook(path)
            formula_blockers = _formula_result_blockers(
                inspection, takeoff['counts'], multiplier)
            preview_inspection = dict(inspection)
            preview_inspection['blockers'] = (
                list(inspection.get('blockers') or []) + formula_blockers)
            self.previewBox.Text = _preview_text(
                path,
                self.level_labels[0],
                multiplier, takeoff, preview_inspection)
            self.result = {
                'mode': takeoff_standalone.MODE_UPDATE,
                'path': path,
                'source_mode': source_mode,
                'selected_schedule_ids': selected_schedule_ids,
                'selected_link_ids': selected_link_ids,
                'multiplier': multiplier,
                'takeoff': takeoff,
                'inspection': inspection,
            }
            if preview_inspection.get('blockers'):
                self.updateButton.IsEnabled = False
                self.statusText.Text = u'Excel 公式/索引或公式結果需處理，禁止更新。'
            elif takeoff['unclassified']:
                self.updateButton.IsEnabled = False
                self.statusText.Text = u'有未分類車位，禁止更新。'
            elif takeoff.get('annotation_candidates'):
                self.updateButton.IsEnabled = True
                self.statusText.Text = (
                    u'有 {} 個未納入的標註候選；確認後可更新。'.format(
                        len(takeoff['annotation_candidates'])))
            elif self.links and not selected_link_ids:
                self.updateButton.IsEnabled = True
                self.statusText.Text = (
                    u'預覽通過；目前未選連結模型，只會更新主模型數量。')
            else:
                self.updateButton.IsEnabled = True
                self.statusText.Text = u'預覽與公式驗證通過。'
        except Exception as error:
            self.previewBox.Text = u''
            self.result = None
            self.updateButton.IsEnabled = False
            self.statusText.Text = u'預覽失敗。'
            forms.alert(u'預覽失敗：\n\n{}'.format(error), title=TITLE)

    def update_clicked(self, sender, args):
        if self.result is None:
            return
        if (self.result.get('mode') == takeoff_standalone.MODE_UPDATE
                and self.result['takeoff']['unclassified']):
            return
        self.Close()

    def cancel_clicked(self, sender, args):
        self.result = None
        self.Close()


def _confirmation_text(result, backup):
    counts = result['takeoff']['counts']
    unused_values, car_total, multiplier = _expected_values(
        counts, result['multiplier'])
    wheel_formula_multiplier = _wheel_stop_formula_multiplier(
        result['inspection'])
    wheel_g = 1 if wheel_formula_multiplier else multiplier
    wheel_row = result['inspection']['rows']['wheel_stop']
    lines = [u'即將更新以下數量：', u'']
    for item in logic.ITEMS:
        lines.append(u'{}：{} 位'.format(item['label'], counts[item['key']]))
    lines.extend([
        u'',
        u'汽車合計（含大客車）：{} 位'.format(car_total),
        u'塑膠車輪檔：{} × {} = {} 個'.format(
            car_total, multiplier, car_total * multiplier),
        u'Excel：{}'.format(_short_path(result['path'])),
        u'備份：{}'.format(_short_path(backup)),
    ])
    if wheel_formula_multiplier:
        lines.extend([
            u'',
            u'注意：F{} 公式已內含輪檔倍率 {}；本次會保留 F{}，G{} 寫入 {}。'.format(
                wheel_row, wheel_formula_multiplier, wheel_row,
                wheel_row, wheel_g),
        ])
    if not result.get('selected_link_ids'):
        lines.extend([
            u'',
            u'注意：未選取連結模型，本次只計算主模型。',
        ])
    if result['takeoff'].get('annotation_candidates'):
        lines.extend([
            u'',
            u'注意：另有 {} 個標註空白或不符合條件的連結車位未納入。'.format(
                len(result['takeoff']['annotation_candidates'])),
        ])
    lines.extend([
        u'',
        u'確定建立備份並更新 Excel 嗎？',
    ])
    return u'\n'.join(lines)


def _default_name(doc):
    title = u'{}'.format(getattr(doc, 'Title', u'停車位')).strip()
    for value in u'\\/:*?"<>|':
        title = title.replace(value, u'_')
    return (title or u'停車位') + u'_停車位.xlsx'


def run(doc, entry_options):
    try:
        levels = collect_levels(doc)
        window = ParkingExcelWindow(doc, levels, entry_options)
        window.ShowDialog()
        result = window.result
        if result is None:
            return
        if result.get('mode') == takeoff_standalone.MODE_STANDALONE:
            path = forms.save_file(
                file_ext='xlsx',
                default_name=_default_name(doc),
                title=u'匯出停車位 Excel')
            if not path:
                return
            if not path.lower().endswith('.xlsx'):
                path += '.xlsx'
            tables = result['tables']
            takeoff_standalone.write_standard_workbook(
                path,
                tables['detail_rows'], tables['detail_headers'],
                tables['formula_rows'], tables['formula_headers'],
                tables['audit_rows'], tables['audit_headers'],
                TITLE)
            forms.alert(
                u'停車位 Excel 匯出完成。\n\n檔案：{}'.format(path),
                title=TITLE)
            return
        backup = _backup_path(result['path'])
        confirmed = forms.alert(
            _confirmation_text(result, backup),
            title=TITLE, yes=True, no=True)
        if not confirmed:
            return
        update_workbook(
            result['path'],
            result['inspection'],
            result['takeoff']['counts'],
            result['multiplier'],
            backup,
        )
        forms.alert(
            u'停車位 Excel 更新完成。\n\n檔案：{}\n備份：{}'.format(
                result['path'], backup),
            title=TITLE,
        )
    except Exception as error:
        forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
