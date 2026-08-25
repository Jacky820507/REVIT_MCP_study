# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Revit-side collection shared by the 門窗編號 buttons (JAC 10.08 / 10.09).

Only the parts that need a live document live here: reading a 編號 off an
opening, deciding whether that opening belongs to a curtain wall, and finding
its level. The rules built on top of those facts live in
:mod:`duplicate_mark_logic` and :mod:`blank_mark_fill_logic`.

The split matters because the check button and the fill button must agree on
what they are looking at. If each carried its own copy of 「這樘算不算帷幕」,
one of them would eventually be corrected and the other would not.
"""

from Autodesk.Revit import DB


CATEGORIES = (
    (DB.BuiltInCategory.OST_Doors, u'門'),
    (DB.BuiltInCategory.OST_Windows, u'窗'),
)

# 編號 lives in a different place in every office's template, so the source is
# asked for rather than assumed. See domain/user-specified-runtime-parameters.md.
SOURCE_TYPE_MARK = 'type_mark'
SOURCE_INSTANCE_MARK = 'instance_mark'
SOURCE_TYPE_NAME = 'type_name'
SOURCE_CUSTOM = 'custom'

SOURCE_LABELS = {
    SOURCE_TYPE_MARK: u'類型註記 Type Mark',
    SOURCE_INSTANCE_MARK: u'註記 Mark',
    SOURCE_TYPE_NAME: u'類型名稱',
    SOURCE_CUSTOM: u'自訂參數',
}

# Where a parameter physically lives, which decides how many openings one
# write moves.
SCOPE_INSTANCE = 'instance'
SCOPE_TYPE = 'type'

STATUS_OK = 'ok'
STATUS_MISSING = u'查無參數'
STATUS_READONLY = u'唯讀'
STATUS_NOT_TEXT = u'非文字參數'


def id_value(element_id):
    if element_id is None:
        return -1
    # Revit 2025+ exposes .Value; 2020-2024 only .IntegerValue.
    try:
        return int(element_id.Value)
    except Exception:
        try:
            return int(element_id.IntegerValue)
        except Exception:
            return -1


def element_name(element):
    if element is None:
        return u''
    try:
        return DB.Element.Name.GetValue(element) or u''
    except Exception:
        try:
            return element.Name or u''
        except Exception:
            return u''


def symbol_of(instance, doc):
    try:
        symbol = instance.Symbol
        if symbol is not None:
            return symbol
    except Exception:
        pass
    try:
        return doc.GetElement(instance.GetTypeId())
    except Exception:
        return None


def built_in_parameter(element, built_in_name):
    """``get_Parameter`` guarded on both sides — the enum member may not exist."""
    if element is None:
        return None
    built_in = getattr(DB.BuiltInParameter, built_in_name, None)
    if built_in is None:
        return None
    try:
        return element.get_Parameter(built_in)
    except Exception:
        return None


def parameter_text(parameter):
    if parameter is None:
        return u''
    try:
        value = parameter.AsString()
    except Exception:
        value = None
    if not value:
        try:
            value = parameter.AsValueString()
        except Exception:
            value = None
    return value or u''


def lookup_parameter(instance, symbol, parameter_name):
    """``(parameter, scope)`` — instance parameter first, then the type.

    A custom 編號 field is authored on either, depending on the template, and
    the caller needs to know which one it found so a type-level write can be
    collapsed correctly.
    """
    if not parameter_name:
        return None, SCOPE_INSTANCE
    for element, scope in ((instance, SCOPE_INSTANCE), (symbol, SCOPE_TYPE)):
        if element is None:
            continue
        try:
            parameter = element.LookupParameter(parameter_name)
        except Exception:
            parameter = None
        if parameter is not None:
            return parameter, scope
    return None, SCOPE_INSTANCE


def mark_parameter(instance, symbol, source, parameter_name=u''):
    """``(parameter, scope)`` for the chosen 編號 source.

    ``SOURCE_TYPE_NAME`` has no parameter behind it — it is read-only by
    nature, so it returns ``None`` and callers must treat it as unwritable.
    """
    if source == SOURCE_TYPE_MARK:
        return built_in_parameter(symbol, 'ALL_MODEL_TYPE_MARK'), SCOPE_TYPE
    if source == SOURCE_INSTANCE_MARK:
        return built_in_parameter(instance, 'ALL_MODEL_MARK'), SCOPE_INSTANCE
    if source == SOURCE_TYPE_NAME:
        return None, SCOPE_TYPE
    return lookup_parameter(instance, symbol, parameter_name)


def read_mark(instance, symbol, source, parameter_name=u''):
    if source == SOURCE_TYPE_NAME:
        return element_name(symbol)
    parameter, unused_scope = mark_parameter(
        instance, symbol, source, parameter_name)
    return parameter_text(parameter)


def parameter_status(parameter):
    """Why a parameter cannot be written, or ``STATUS_OK``."""
    if parameter is None:
        return STATUS_MISSING
    try:
        if parameter.IsReadOnly:
            return STATUS_READONLY
    except Exception:
        return STATUS_READONLY
    try:
        if parameter.StorageType != DB.StorageType.String:
            return STATUS_NOT_TEXT
    except Exception:
        return STATUS_NOT_TEXT
    return STATUS_OK


def is_curtain(instance, symbol):
    """Whether this opening belongs to a curtain wall rather than a real 門窗.

    Three independent signals, because none of them holds for every template:
    a swapped-in curtain panel, a family authored as a curtain wall panel, and
    an opening hosted directly in a wall that carries a curtain grid.
    """
    panel_class = getattr(DB, 'Panel', None)
    if panel_class is not None:
        try:
            if isinstance(instance, panel_class):
                return True
        except Exception:
            pass
    try:
        family = symbol.Family if symbol is not None else None
        placement = getattr(family, 'FamilyPlacementType', None)
        curtain_placement = getattr(
            DB.FamilyPlacementType, 'CurtainWallPanel', None)
        if (placement is not None and curtain_placement is not None
                and placement == curtain_placement):
            return True
    except Exception:
        pass
    try:
        host = instance.Host
        if host is not None and isinstance(host, DB.Wall):
            if host.CurtainGrid is not None:
                return True
    except Exception:
        pass
    return False


def level_id(instance):
    """Level of an opening, with the fallbacks Revit actually needs.

    A door hosted in a wall often leaves LevelId invalid, so the built-in level
    parameters are tried next — the same chain the 門窗表 button uses.
    """
    try:
        value = id_value(instance.LevelId)
        if value >= 0:
            return value
    except Exception:
        pass
    for name in ('FAMILY_LEVEL_PARAM', 'INSTANCE_REFERENCE_LEVEL_PARAM',
                 'SCHEDULE_LEVEL_PARAM'):
        parameter = built_in_parameter(instance, name)
        if parameter is None:
            continue
        try:
            value = id_value(parameter.AsElementId())
            if value >= 0:
                return value
        except Exception:
            pass
    try:
        host = instance.Host
        if host is not None:
            value = id_value(host.LevelId)
            if value >= 0:
                return value
    except Exception:
        pass
    return -1


def levels(doc):
    found = list(DB.FilteredElementCollector(doc)
                 .OfClass(DB.Level)
                 .WhereElementIsNotElementType()
                 .ToElements())
    found.sort(key=lambda level: (level.Elevation, element_name(level)))
    return found


def level_index(doc):
    """``{level_id: (name, elevation)}`` for labelling and sort order."""
    index = {}
    for level in levels(doc):
        try:
            elevation = float(level.Elevation)
        except Exception:
            elevation = 0.0
        index[id_value(level.Id)] = (element_name(level), elevation)
    return index


def collect(doc, allowed_level_ids=None, level_map=None):
    """Base record per door/window; callers add whatever 編號 fields they need.

    ``allowed_level_ids`` of ``None`` means every level — 抓全部 is the
    documented default.
    """
    if level_map is None:
        level_map = level_index(doc)
    records = []
    for category, kind in CATEGORIES:
        try:
            collector = (DB.FilteredElementCollector(doc)
                         .OfCategory(category)
                         .WhereElementIsNotElementType())
        except Exception:
            continue
        for instance in collector:
            found_level = level_id(instance)
            if (allowed_level_ids is not None
                    and found_level not in allowed_level_ids):
                continue
            symbol = symbol_of(instance, doc)
            family_name = u''
            try:
                family = symbol.Family if symbol is not None else None
                family_name = element_name(family)
            except Exception:
                family_name = u''
            name, elevation = level_map.get(found_level, (u'(未知樓層)', 0.0))
            records.append({
                'id': id_value(instance.Id),
                'element': instance,
                'element_id': instance.Id,
                'symbol': symbol,
                'type_id': id_value(symbol.Id) if symbol is not None else -1,
                'category': kind,
                'family_name': family_name,
                'type_name': element_name(symbol),
                'level': name,
                'level_elevation': elevation,
                'curtain': is_curtain(instance, symbol),
            })
    return records
