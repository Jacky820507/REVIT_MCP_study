# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Read-only Revit collectors for room material details.

This module is deliberately importable without Revit so the pyRevit test suite can
import it under CPython.  Revit API access is checked only when a public collector
is called.

Public contracts
----------------
``collect_rooms(doc, uidoc, scope)`` returns a direct ``list`` of host-document
Room elements with ``Area > 0``.  ``scope`` is ``all``, ``selection``, or ``view``
(``project`` is accepted as an alias for ``all``).

``collect_room_material_details(...)`` returns::

    {
        'records': [canonical room/material rows],
        'warnings': [auditable warning strings],
        'stats': {collection and reconciliation counters}
    }

Canonical rows contain ``room_id``, ``level``, ``room_number``, ``room_name``,
``surface_kind``, ``material_id``, ``material_name``, ``material_source``,
``material_class``, ``area_m2``, ``face_count``, ``boundary_category``,
``boundary_element_ids``, ``method``, ``estimated``, and ``warnings``.

The precise path uses one shared ``SpatialElementGeometryCalculator``.  Every
room face is reconciled to ``Face.Area`` before opening deductions: missing
subfaces become an estimated Unknown residual row, and API over-reporting is
proportionally clamped with a warning.  Opening deductions are conservative:
only door/window inserts whose phase-aware FromRoom/ToRoom identifies the room
are deducted.  Unprovable membership or dimensions are never guessed.

The code is IronPython 2.7 / CPython 3 dual-compatible.
"""

import re


try:
    from Autodesk.Revit import DB
except Exception:
    DB = None


SQ_FT_TO_SQ_M = 0.09290304
CU_FT_TO_CU_M = 0.028316846592
FACE_RECONCILE_ABS_FT2 = 1.0e-7
FACE_RECONCILE_REL = 1.0e-6
AREA_EPSILON_FT2 = 1.0e-9


try:
    _STRING_TYPES = (basestring,)
except NameError:
    _STRING_TYPES = (str,)


class _SpatialRoomFailure(Exception):
    """Signals that one room must use the explicit estimated fallback."""


def _require_revit():
    if DB is None:
        raise RuntimeError(
            "Autodesk.Revit.DB is unavailable; run this collector inside Revit/pyRevit."
        )


def _id_value(element_id):
    if element_id is None:
        return None
    try:
        return int(element_id.Value)
    except Exception:
        pass
    try:
        return int(element_id.IntegerValue)
    except Exception:
        pass
    try:
        return int(element_id)
    except Exception:
        return None


def _invalid_id(element_id):
    value = _id_value(element_id)
    return value is None or value < 0


def _make_element_id(value):
    if value is None:
        return None
    if hasattr(value, "IntegerValue") or hasattr(value, "Value"):
        return value
    try:
        return DB.ElementId(int(value))
    except Exception:
        return None


def _exception_text(exc):
    try:
        return str(exc)
    except Exception:
        return exc.__class__.__name__


def _clean_text(value):
    if value is None:
        return ""
    try:
        return value.strip()
    except Exception:
        try:
            return str(value).strip()
        except Exception:
            return ""


def _append_warning(warnings, message):
    message = _clean_text(message)
    if message and message not in warnings:
        warnings.append(message)


def _safe_name(element):
    if element is None:
        return ""
    try:
        return _clean_text(element.Name)
    except Exception:
        return ""


def _area_to_m2(value):
    value = float(value or 0.0)
    if DB is not None:
        try:
            unit_type_id = getattr(DB, "UnitTypeId", None)
            if unit_type_id is not None:
                return float(DB.UnitUtils.ConvertFromInternalUnits(
                    value, unit_type_id.SquareMeters
                ))
        except Exception:
            pass
        try:
            return float(DB.UnitUtils.ConvertFromInternalUnits(
                value, DB.DisplayUnitType.DUT_SQUARE_METERS
            ))
        except Exception:
            pass
    return value * SQ_FT_TO_SQ_M


def _category_id_value(category):
    if category is None:
        return None
    try:
        return _id_value(category.Id)
    except Exception:
        return None


def _builtin_category_value(name):
    try:
        return int(getattr(DB.BuiltInCategory, name))
    except Exception:
        return None


def _is_room(element):
    if element is None:
        return False
    try:
        architecture = getattr(DB, "Architecture", None)
        room_type = getattr(architecture, "Room", None)
        if room_type is not None and isinstance(element, room_type):
            return True
    except Exception:
        pass
    try:
        return (_category_id_value(element.Category) ==
                _builtin_category_value("OST_Rooms"))
    except Exception:
        return False


def _room_area_positive(room):
    try:
        return float(room.Area) > AREA_EPSILON_FT2
    except Exception:
        return False


def _room_number(room):
    try:
        return _clean_text(room.Number)
    except Exception:
        return ""


def _room_name(room):
    try:
        parameter = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME)
        if parameter is not None:
            value = _clean_text(parameter.AsString())
            if value:
                return value
    except Exception:
        pass
    return _safe_name(room)


def _room_level_name(doc, room):
    try:
        level = doc.GetElement(room.LevelId)
        return _safe_name(level)
    except Exception:
        return ""


def _natural_key(value):
    parts = re.split(r"(\d+)", _clean_text(value).lower())
    result = []
    for part in parts:
        if part.isdigit():
            result.append((0, int(part)))
        else:
            result.append((1, part))
    return result


def _room_sort_key(doc, room):
    return (
        _natural_key(_room_level_name(doc, room)),
        _natural_key(_room_number(room)),
        _natural_key(_room_name(room)),
        _id_value(getattr(room, "Id", None)) or 0,
    )


def _collector_to_list(collector):
    try:
        return list(collector.ToElements())
    except Exception:
        return list(collector)


def collect_rooms(doc, uidoc, scope):
    """Return host-document placed Room elements for ``all/selection/view``.

    The result is a direct list because the WPF caller binds it immediately.
    Invalid scopes raise ``ValueError``.  Missing UIDocument/active view raises a
    clear ``RuntimeError``; an empty selection or a view with no rooms returns an
    empty list.
    """
    _require_revit()
    if doc is None:
        raise ValueError("doc is required")

    normalized = _clean_text(scope).lower()
    if normalized == "project":
        normalized = "all"
    if normalized not in ("all", "selection", "view"):
        raise ValueError("scope must be all, selection, or view")

    candidates = []
    if normalized == "all":
        collector = (DB.FilteredElementCollector(doc)
                     .OfCategory(DB.BuiltInCategory.OST_Rooms)
                     .WhereElementIsNotElementType())
        candidates = _collector_to_list(collector)
    elif normalized == "view":
        if uidoc is None:
            raise RuntimeError("UIDocument is required for room scope 'view'.")
        try:
            view = uidoc.ActiveView
        except Exception as exc:
            raise RuntimeError("Unable to read the active view: {0}".format(
                _exception_text(exc)))
        if view is None:
            raise RuntimeError("No active view is available for room scope 'view'.")
        collector = (DB.FilteredElementCollector(doc, view.Id)
                     .OfCategory(DB.BuiltInCategory.OST_Rooms)
                     .WhereElementIsNotElementType())
        candidates = _collector_to_list(collector)
    else:
        if uidoc is None:
            raise RuntimeError("UIDocument is required for room scope 'selection'.")
        try:
            selected_ids = list(uidoc.Selection.GetElementIds())
        except Exception as exc:
            raise RuntimeError("Unable to read current selection: {0}".format(
                _exception_text(exc)))
        for selected_id in selected_ids:
            element = doc.GetElement(selected_id)
            if element is not None:
                candidates.append(element)

    rooms = []
    seen = set()
    for candidate in candidates:
        if not _is_room(candidate) or not _room_area_positive(candidate):
            continue
        room_id = _id_value(getattr(candidate, "Id", None))
        if room_id is None or room_id in seen:
            continue
        seen.add(room_id)
        rooms.append(candidate)
    rooms.sort(key=lambda item: _room_sort_key(doc, item))
    return rooms


def _normalize_surface_keys(surface_keys):
    allowed = set(("floor", "wall", "ceiling", "other"))
    if surface_keys is None:
        return allowed
    if isinstance(surface_keys, _STRING_TYPES):
        values = [item for item in re.split(r"[,;|]", surface_keys) if item]
    else:
        values = list(surface_keys)
    result = set()
    aliases = {
        "floor": "floor",
        "ground": "floor",
        "wall": "wall",
        "ceiling": "ceiling",
        "roof": "ceiling",
        "other": "other",
        u"地面": "floor",
        u"地板": "floor",
        u"牆": "wall",
        u"牆壁": "wall",
        u"天花": "ceiling",
        u"天花板": "ceiling",
        u"其他": "other",
    }
    unknown = []
    for value in values:
        key = _clean_text(value).lower()
        normalized = aliases.get(key)
        if normalized is None:
            unknown.append(_clean_text(value))
        else:
            result.add(normalized)
    if unknown:
        raise ValueError(
            "surface_keys contains unsupported values: {0}".format(
                ", ".join(unknown)))
    return result


def _boundary_mode_value(boundary_mode):
    value = _clean_text(boundary_mode).lower()
    if value == "finish":
        return "Finish", DB.SpatialElementBoundaryLocation.Finish
    if value == "center":
        return "Center", DB.SpatialElementBoundaryLocation.Center
    raise ValueError("boundary_mode must be Finish or Center")


def _material_catalog(doc, warnings):
    by_id = {}
    by_name = {}
    try:
        collector = DB.FilteredElementCollector(doc).OfClass(DB.Material)
        materials = _collector_to_list(collector)
    except Exception as exc:
        _append_warning(
            warnings,
            u"材質目錄讀取失敗：{0}".format(_exception_text(exc)))
        return by_id, by_name

    for material in materials:
        material_id = _id_value(getattr(material, "Id", None))
        if material_id is None:
            continue
        name = _safe_name(material)
        try:
            material_class = _clean_text(material.MaterialClass)
        except Exception as exc:
            material_class = ""
            _append_warning(
                warnings,
                u"材質 {0} 的 MaterialClass 讀取失敗：{1}".format(
                    material_id, _exception_text(exc)))
        by_id[material_id] = {
            "name": name or u"(Material ID {0})".format(material_id),
            "material_class": material_class,
        }
        if name:
            by_name[name.lower()] = material_id
    return by_id, by_name


def _material_identity(material_id, material_by_id, doc=None, warnings=None):
    value = _id_value(material_id)
    if value is None or value < 0:
        return None, u"(Unknown)", ""
    record = material_by_id.get(value)
    if record is None and doc is not None:
        try:
            material = doc.GetElement(material_id)
            if material is not None:
                record = {
                    "name": _safe_name(material) or
                            u"(Material ID {0})".format(value),
                    "material_class": _clean_text(material.MaterialClass),
                }
                material_by_id[value] = record
        except Exception as exc:
            if warnings is not None:
                _append_warning(
                    warnings,
                    u"材質 {0} 已由 face 解析，但 MaterialClass 回讀失敗：{1}".format(
                        value, _exception_text(exc)))
    if record is None:
        return value, u"(Material ID {0})".format(value), ""
    return value, record.get("name") or u"(Material ID {0})".format(value), \
        record.get("material_class") or ""


def _room_finish_parameter(surface_kind):
    if surface_kind == "wall":
        return getattr(DB.BuiltInParameter, "ROOM_FINISH_WALL", None)
    if surface_kind == "floor":
        return getattr(DB.BuiltInParameter, "ROOM_FINISH_FLOOR", None)
    if surface_kind == "ceiling":
        return getattr(DB.BuiltInParameter, "ROOM_FINISH_CEILING", None)
    return None


def _room_finish_material(room, surface_kind, material_by_name,
                          material_by_id, warnings):
    parameter_id = _room_finish_parameter(surface_kind)
    if parameter_id is None:
        return None
    try:
        parameter = room.get_Parameter(parameter_id)
        if parameter is None:
            return None
        value = _clean_text(parameter.AsString())
        if not value:
            try:
                value = _clean_text(parameter.AsValueString())
            except Exception:
                value = ""
    except Exception as exc:
        _append_warning(
            warnings,
            u"房間 {0} 的 {1} finish 參數讀取失敗：{2}".format(
                _id_value(getattr(room, "Id", None)),
                surface_kind,
                _exception_text(exc)))
        return None
    if not value:
        return None
    material_id = material_by_name.get(value.lower())
    material_class = ""
    if material_id is not None:
        material_record = material_by_id.get(material_id) or {}
        material_class = material_record.get("material_class") or ""
    return material_id, value, "RoomFinishText", material_class


def _unknown_material():
    return None, u"(Unknown)", "Unknown", ""


def _host_element_id(face_info):
    try:
        link_element_id = face_info.SpatialBoundaryElement
        host_id = link_element_id.HostElementId
        if not _invalid_id(host_id):
            return host_id
    except Exception:
        pass
    return None


def _boundary_category(element):
    if element is None:
        return "other"
    category_id = None
    try:
        category_id = _category_id_value(element.Category)
    except Exception:
        category_id = None
    mappings = (
        ("OST_Walls", "Wall"),
        ("OST_Floors", "Floor"),
        ("OST_Ceilings", "Ceiling"),
        ("OST_Roofs", "Roof"),
    )
    for built_in_name, label in mappings:
        value = _builtin_category_value(built_in_name)
        if value is not None and category_id == value:
            return label

    # Category access can fail for some generated boundary elements.  Class
    # checks are only a secondary identity source, never an area/material guess.
    class_mappings = (
        ("Wall", "Wall"),
        ("Floor", "Floor"),
        ("Ceiling", "Ceiling"),
        ("RoofBase", "Roof"),
    )
    for class_name, label in class_mappings:
        try:
            class_type = getattr(DB, class_name, None)
            if class_type is not None and isinstance(element, class_type):
                return label
        except Exception:
            pass
    return "other"


def _face_normal(face, warnings, room_id, face_index):
    try:
        bounding_box = face.GetBoundingBox()
        minimum = bounding_box.Min
        maximum = bounding_box.Max
        uv = DB.UV(
            (float(minimum.U) + float(maximum.U)) / 2.0,
            (float(minimum.V) + float(maximum.V)) / 2.0)
        return face.ComputeNormal(uv)
    except Exception:
        try:
            return face.ComputeNormal(DB.UV(0.5, 0.5))
        except Exception as exc:
            _append_warning(
                warnings,
                u"房間 {0} face {1} 法向量讀取失敗，分類為 other：{2}".format(
                    room_id, face_index, _exception_text(exc)))
            return None


def _surface_kind_from_normal(normal):
    if normal is None:
        return "other"
    try:
        z_value = float(normal.Z)
    except Exception:
        return "other"
    if z_value > 0.8:
        return "ceiling"
    if z_value < -0.8:
        return "floor"
    if abs(z_value) < 0.2:
        return "wall"
    return "other"


def _surface_kind_for_face(normal_kind, descriptors):
    if normal_kind != "other":
        return normal_kind
    categories = set()
    for descriptor in descriptors:
        category = descriptor.get("boundary_category")
        if category and category != "other":
            categories.add(category)
    if len(categories) == 1:
        category = list(categories)[0]
        if category == "Wall":
            return "wall"
        if category == "Floor":
            return "floor"
        if category in ("Ceiling", "Roof"):
            return "ceiling"
    return "other"


def _room_identity(doc, room):
    return {
        "room_id": _id_value(getattr(room, "Id", None)),
        "level": _room_level_name(doc, room),
        "room_number": _room_number(room),
        "room_name": _room_name(room),
    }


def _new_aggregate(identity, surface_kind, material_id, material_name,
                   material_source, material_class, boundary_category,
                   method, estimated):
    return {
        "room_id": identity["room_id"],
        "level": identity["level"],
        "room_number": identity["room_number"],
        "room_name": identity["room_name"],
        "surface_kind": surface_kind,
        "material_id": material_id,
        "material_name": material_name,
        "material_source": material_source,
        "material_class": material_class or "",
        "face_count": 0,
        "boundary_category": boundary_category,
        "method": method,
        "estimated": bool(estimated),
        "warnings": [],
        "_gross_area_ft2": 0.0,
        "_net_area_ft2": 0.0,
        "_host_areas_ft2": {},
        "_boundary_ids": set(),
    }


def _add_descriptor(aggregates, identity, descriptor, surface_kind, method):
    material_id = descriptor.get("material_id")
    material_name = descriptor.get("material_name") or u"(Unknown)"
    material_source = descriptor.get("material_source") or "Unknown"
    material_class = descriptor.get("material_class") or ""
    boundary_category = descriptor.get("boundary_category") or "other"
    estimated = bool(descriptor.get("estimated"))
    key = (
        surface_kind,
        material_id,
        material_name,
        material_source,
        material_class,
        boundary_category,
        method,
        estimated,
    )
    row = aggregates.get(key)
    if row is None:
        row = _new_aggregate(
            identity,
            surface_kind,
            material_id,
            material_name,
            material_source,
            material_class,
            boundary_category,
            method,
            estimated)
        aggregates[key] = row

    area_ft2 = max(0.0, float(descriptor.get("area_ft2") or 0.0))
    row["_gross_area_ft2"] += area_ft2
    row["_net_area_ft2"] += area_ft2
    row["face_count"] += 1

    host_id = descriptor.get("host_id")
    host_value = _id_value(host_id)
    if host_value is not None and host_value >= 0:
        row["_boundary_ids"].add(host_value)
        row["_host_areas_ft2"][host_value] = (
            row["_host_areas_ft2"].get(host_value, 0.0) + area_ft2)
    for warning in descriptor.get("warnings") or []:
        _append_warning(row["warnings"], warning)
    return row


def _resolve_subface_material(doc, room, surface_kind, boundary_mode,
                              face_info, host_id, material_by_id,
                              material_by_name, warnings):
    local_warnings = []
    bounding_face = None
    if boundary_mode == "Finish":
        try:
            bounding_face = face_info.GetBoundingElementFace()
        except Exception as exc:
            _append_warning(
                local_warnings,
                u"房間 {0} 無法取得 bounding face；改用房間 finish 文字：{1}".format(
                    _id_value(getattr(room, "Id", None)),
                    _exception_text(exc)))
    else:
        _append_warning(
            local_warnings,
            u"Center 邊界不保證提供 bounding face；材質改用房間 finish 文字或 Unknown。")

    if bounding_face is not None:
        if host_id is not None and not _invalid_id(host_id):
            try:
                painted_id = doc.GetPaintedMaterial(host_id, bounding_face)
                if not _invalid_id(painted_id):
                    material_id, material_name, material_class = _material_identity(
                        painted_id, material_by_id, doc, warnings)
                    for message in local_warnings:
                        _append_warning(warnings, message)
                    return (
                        material_id,
                        material_name,
                        "PaintedBoundingFace",
                        material_class,
                        local_warnings,
                    )
            except Exception as exc:
                _append_warning(
                    local_warnings,
                    u"房間 {0} painted material 讀取失敗；續查 face 材質：{1}".format(
                        _id_value(getattr(room, "Id", None)),
                        _exception_text(exc)))
        try:
            face_material_id = bounding_face.MaterialElementId
            if not _invalid_id(face_material_id):
                material_id, material_name, material_class = _material_identity(
                    face_material_id, material_by_id, doc, warnings)
                for message in local_warnings:
                    _append_warning(warnings, message)
                return (
                    material_id,
                    material_name,
                    "BoundingFace",
                    material_class,
                    local_warnings,
                )
        except Exception as exc:
            _append_warning(
                local_warnings,
                u"房間 {0} bounding face 材質讀取失敗：{1}".format(
                    _id_value(getattr(room, "Id", None)),
                    _exception_text(exc)))

    fallback = _room_finish_material(
        room, surface_kind, material_by_name, material_by_id, warnings)
    for message in local_warnings:
        _append_warning(warnings, message)
    if fallback is not None:
        return (fallback[0], fallback[1], fallback[2], fallback[3],
                local_warnings)
    unknown = _unknown_material()
    return unknown[0], unknown[1], unknown[2], unknown[3], local_warnings


def _subface_descriptors(doc, room, results, face, face_index,
                         boundary_mode, material_by_id, material_by_name,
                         warnings, host_elements, stats):
    room_id = _id_value(getattr(room, "Id", None))
    face_area = 0.0
    try:
        face_area = float(face.Area)
    except Exception as exc:
        _append_warning(
            warnings,
            u"房間 {0} face {1} 面積讀取失敗，該 face 無法列入：{2}".format(
                room_id, face_index, _exception_text(exc)))
        stats["face_errors"] += 1
        return None, [], "other"
    if face_area <= AREA_EPSILON_FT2:
        return face_area, [], "other"

    normal = _face_normal(face, warnings, room_id, face_index)
    normal_kind = _surface_kind_from_normal(normal)

    try:
        boundary_infos = results.GetBoundaryFaceInfo(face)
        if boundary_infos is None:
            boundary_infos = []
        else:
            boundary_infos = list(boundary_infos)
    except Exception as exc:
        boundary_infos = []
        _append_warning(
            warnings,
            u"房間 {0} face {1} boundary info 讀取失敗；全額列 Unknown：{2}".format(
                room_id, face_index, _exception_text(exc)))
        stats["face_errors"] += 1

    descriptors = []
    for subface_index, face_info in enumerate(boundary_infos):
        try:
            subface = face_info.GetSubface()
            subface_area = float(subface.Area)
            if subface_area <= AREA_EPSILON_FT2:
                continue
        except Exception as exc:
            _append_warning(
                warnings,
                u"房間 {0} face {1} subface {2} 面積讀取失敗；餘額將列 Unknown：{3}".format(
                    room_id,
                    face_index,
                    subface_index,
                    _exception_text(exc)))
            stats["subface_errors"] += 1
            continue

        host_id = _host_element_id(face_info)
        host = None
        if host_id is None:
            _append_warning(
                warnings,
                u"房間 {0} face {1} subface {2} 沒有可追蹤的 host ElementId。".format(
                    room_id, face_index, subface_index))
        if host_id is not None and not _invalid_id(host_id):
            try:
                host = doc.GetElement(host_id)
            except Exception as exc:
                _append_warning(
                    warnings,
                    u"房間 {0} face {1} 宿主 {2} 讀取失敗：{3}".format(
                        room_id,
                        face_index,
                        _id_value(host_id),
                        _exception_text(exc)))
            host_value = _id_value(host_id)
            if host_value is not None and host is not None:
                host_elements[host_value] = host
        boundary_category = _boundary_category(host)
        material = _resolve_subface_material(
            doc,
            room,
            normal_kind,
            boundary_mode,
            face_info,
            host_id,
            material_by_id,
            material_by_name,
            warnings)
        descriptors.append({
            "area_ft2": subface_area,
            "host_id": host_id,
            "boundary_category": boundary_category,
            "material_id": material[0],
            "material_name": material[1],
            "material_source": material[2],
            "material_class": material[3],
            "estimated": False,
            "warnings": list(material[4]),
        })
        stats["subfaces"] += 1

    surface_kind = _surface_kind_for_face(normal_kind, descriptors)
    # Room finish fallback must follow the final surface classification (for
    # example a sloped face inferred as Ceiling from a Roof host).
    if surface_kind != normal_kind:
        for descriptor in descriptors:
            if descriptor.get("material_source") in ("RoomFinishText", "Unknown"):
                fallback = _room_finish_material(
                    room, surface_kind, material_by_name,
                    material_by_id, warnings)
                if fallback is not None:
                    descriptor["material_id"] = fallback[0]
                    descriptor["material_name"] = fallback[1]
                    descriptor["material_source"] = fallback[2]
                    descriptor["material_class"] = fallback[3]

    tolerance = max(FACE_RECONCILE_ABS_FT2,
                    abs(face_area) * FACE_RECONCILE_REL)
    subface_total = sum(item["area_ft2"] for item in descriptors)
    difference = face_area - subface_total

    if not descriptors:
        message = (
            u"房間 {0} face {1} 沒有可用 boundary subface；"
            u"Face.Area {2:.6f} ft² 全額列 Unknown。".format(
                room_id, face_index, face_area))
        _append_warning(warnings, message)
        descriptors.append({
            "area_ft2": face_area,
            "host_id": None,
            "boundary_category": "other",
            "material_id": None,
            "material_name": u"(Unknown)",
            "material_source": "Unknown",
            "material_class": "",
            "estimated": True,
            "warnings": [message],
        })
        stats["unknown_residual_faces"] += 1
    elif difference > tolerance:
        message = (
            u"房間 {0} face {1} 的 subface 總和少於 Face.Area "
            u"{2:.6f} ft²；差額列 Unknown。".format(
                room_id, face_index, difference))
        _append_warning(warnings, message)
        descriptors.append({
            "area_ft2": difference,
            "host_id": None,
            "boundary_category": "other",
            "material_id": None,
            "material_name": u"(Unknown)",
            "material_source": "Unknown",
            "material_class": "",
            "estimated": True,
            "warnings": [message],
        })
        stats["unknown_residual_faces"] += 1
    elif difference < -tolerance:
        message = (
            u"房間 {0} face {1} 的 subface 總和超過 Face.Area "
            u"{2:.6f} ft²；為保持逐 face 對帳，按比例縮放並標示 estimated。".format(
                room_id, face_index, -difference))
        _append_warning(warnings, message)
        scale = face_area / subface_total if subface_total > 0 else 0.0
        for descriptor in descriptors:
            descriptor["area_ft2"] *= scale
            descriptor["estimated"] = True
            _append_warning(descriptor["warnings"], message)
        stats["overreported_faces"] += 1
    else:
        # Absorb floating point drift proportionally.  Adjusting only the final
        # descriptor can go negative when that subface is tiny.
        if subface_total > 0:
            drift_scale = face_area / subface_total
            for descriptor in descriptors:
                descriptor["area_ft2"] *= drift_scale

    reconciled_total = sum(item["area_ft2"] for item in descriptors)
    residual = face_area - reconciled_total
    if (descriptors and reconciled_total > 0 and
            abs(residual) > AREA_EPSILON_FT2):
        final_scale = face_area / reconciled_total
        for descriptor in descriptors:
            descriptor["area_ft2"] *= final_scale
    stats["faces"] += 1
    stats["face_area_gross_ft2"] += face_area
    stats["face_reconciled_ft2"] += sum(
        item["area_ft2"] for item in descriptors)
    return face_area, descriptors, surface_kind


def _collect_spatial_room(doc, room, calculator, boundary_mode,
                          selected_surfaces, material_by_id,
                          material_by_name, warnings, stats):
    identity = _room_identity(doc, room)
    try:
        results = calculator.CalculateSpatialElementGeometry(room)
        solid = results.GetGeometry()
        faces = list(solid.Faces)
    except Exception as exc:
        raise _SpatialRoomFailure(_exception_text(exc))
    if not faces:
        raise _SpatialRoomFailure("SpatialElementGeometryCalculator returned no faces")

    aggregates = {}
    host_elements = {}
    readable_face_count_before = stats["faces"]
    for face_index, face in enumerate(faces):
        try:
            face_area, descriptors, surface_kind = _subface_descriptors(
                doc,
                room,
                results,
                face,
                face_index,
                boundary_mode,
                material_by_id,
                material_by_name,
                warnings,
                host_elements,
                stats)
            if face_area is None or surface_kind not in selected_surfaces:
                continue
            for descriptor in descriptors:
                _add_descriptor(
                    aggregates,
                    identity,
                    descriptor,
                    surface_kind,
                    "SpatialElementGeometryCalculator")
        except Exception as exc:
            # Per-face failures must not silently drop area.  If Face.Area is
            # still readable, preserve it as an estimated Unknown row.
            stats["face_errors"] += 1
            message = u"房間 {0} face {1} 處理失敗；保留 Unknown 面積：{2}".format(
                identity["room_id"], face_index, _exception_text(exc))
            _append_warning(warnings, message)
            try:
                face_area = float(face.Area)
            except Exception:
                face_area = 0.0
            normal = _face_normal(
                face, warnings, identity["room_id"], face_index)
            surface_kind = _surface_kind_from_normal(normal)
            if face_area > AREA_EPSILON_FT2 and surface_kind in selected_surfaces:
                _add_descriptor(
                    aggregates,
                    identity,
                    {
                        "area_ft2": face_area,
                        "host_id": None,
                        "boundary_category": "other",
                        "material_id": None,
                        "material_name": u"(Unknown)",
                        "material_source": "Unknown",
                        "material_class": "",
                        "estimated": True,
                        "warnings": [message],
                    },
                    surface_kind,
                    "SpatialElementGeometryCalculator")
                stats["unknown_residual_faces"] += 1
            if face_area > AREA_EPSILON_FT2:
                stats["faces"] += 1
                stats["face_area_gross_ft2"] += face_area
                stats["face_reconciled_ft2"] += face_area
    if stats["faces"] == readable_face_count_before:
        raise _SpatialRoomFailure(
            "No room face had a readable positive Face.Area")
    return aggregates, host_elements


def _room_phases(doc, room, warnings):
    parameter_names = ("ROOM_PHASE_ID", "ROOM_PHASE")
    for parameter_name in parameter_names:
        built_in = getattr(DB.BuiltInParameter, parameter_name, None)
        if built_in is None:
            continue
        try:
            parameter = room.get_Parameter(built_in)
            if parameter is None:
                continue
            phase_id = parameter.AsElementId()
            if _invalid_id(phase_id):
                continue
            phase = doc.GetElement(phase_id)
            if phase is not None:
                return [phase]
        except Exception:
            continue
    _append_warning(
        warnings,
        u"房間 {0} 無法解析 Phase；開口將逐一查詢 document phases，"
        u"只有 FromRoom/ToRoom 明確回傳此房間時才扣除。".format(
            _id_value(getattr(room, "Id", None))))
    try:
        return list(doc.Phases)
    except Exception:
        return []


def _family_room_values(instance, property_name, phases):
    errors = []
    try:
        getter = getattr(instance, "get_{0}".format(property_name))
    except Exception as exc:
        errors.append(_exception_text(exc))
        return [], errors
    values = []
    for phase in phases:
        try:
            value = getter(phase)
            if value is not None:
                values.append(value)
        except Exception as exc:
            errors.append(_exception_text(exc))
    return values, errors


def _is_door_or_window(element):
    try:
        category_id = _category_id_value(element.Category)
    except Exception:
        category_id = None
    return category_id in (
        _builtin_category_value("OST_Doors"),
        _builtin_category_value("OST_Windows"),
    )


def _insert_belongs_to_room(insert, room, phases, warnings):
    if not _is_door_or_window(insert):
        return False, "unsupported"
    room_id = _id_value(getattr(room, "Id", None))
    values = []
    errors = []
    for property_name in ("FromRoom", "ToRoom"):
        property_values, property_errors = _family_room_values(
            insert, property_name, phases)
        errors.extend(property_errors)
        values.extend(property_values)
    for candidate in values:
        if _id_value(getattr(candidate, "Id", None)) == room_id:
            if errors:
                _append_warning(
                    warnings,
                    u"開口 {0} 的 phase-aware room 查詢部分失敗，但另一側已明確對應房間 {1}。".format(
                        _id_value(getattr(insert, "Id", None)), room_id))
            return True, "from_to_room"
    if values:
        return False, "other_room"
    if errors:
        return False, "room_lookup_failed"
    return False, "no_room"


def _positive_parameter_value(element, built_in_names):
    if element is None:
        return 0.0
    for name in built_in_names:
        built_in = getattr(DB.BuiltInParameter, name, None)
        if built_in is None:
            continue
        try:
            parameter = element.get_Parameter(built_in)
            if parameter is None:
                continue
            value = float(parameter.AsDouble())
            if value > 0:
                return value
        except Exception:
            continue
    return 0.0


def _opening_area_ft2(insert, warnings):
    insert_id = _id_value(getattr(insert, "Id", None))
    width = _positive_parameter_value(
        insert, ("WINDOW_WIDTH", "DOOR_WIDTH"))
    height = _positive_parameter_value(
        insert, ("WINDOW_HEIGHT", "DOOR_HEIGHT"))
    if width > 0 and height > 0:
        return width * height, "InstanceWidthHeight"

    if width <= 0:
        width = _positive_parameter_value(
            insert, ("FAMILY_ROUGH_WIDTH_PARAM",))
    if height <= 0:
        height = _positive_parameter_value(
            insert, ("FAMILY_ROUGH_HEIGHT_PARAM",))
    if width > 0 and height > 0:
        return width * height, "InstanceRoughWidthHeight"

    symbol = None
    try:
        symbol = insert.Symbol
    except Exception:
        symbol = None
    if width <= 0:
        width = _positive_parameter_value(
            symbol, ("WINDOW_WIDTH", "DOOR_WIDTH"))
    if height <= 0:
        height = _positive_parameter_value(
            symbol, ("WINDOW_HEIGHT", "DOOR_HEIGHT"))
    if width <= 0:
        width = _positive_parameter_value(
            symbol, ("FAMILY_ROUGH_WIDTH_PARAM",))
    if height <= 0:
        height = _positive_parameter_value(
            symbol, ("FAMILY_ROUGH_HEIGHT_PARAM",))
    if width > 0 and height > 0:
        return width * height, "TypeWidthHeight"

    # A bounding box is only an envelope.  Its two largest dimensions can be
    # the wall thickness, swing geometry, or family clearances, so it is not
    # reliable evidence of the room-side net opening.  V1 deliberately records
    # the evidence gap and leaves the room surface undeducted.
    try:
        bounding_box = insert.get_BoundingBox(None)
        if bounding_box is not None:
            _append_warning(
                warnings,
                u"開口 {0} 只有 BoundingBox 包絡尺寸，v1 不把它視為可靠淨開口，保守不扣。".format(
                    insert_id))
    except Exception as exc:
        _append_warning(
            warnings,
            u"開口 {0} BoundingBox 尺寸讀取失敗：{1}".format(
                insert_id, _exception_text(exc)))

    _append_warning(
        warnings,
        u"開口 {0} 缺少可證明的寬高，保守不扣面積。".format(insert_id))
    return 0.0, "Unavailable"


def _host_matches_insert(host, insert):
    try:
        insert_host = insert.Host
    except Exception:
        return True
    if insert_host is None:
        return True
    return (_id_value(getattr(insert_host, "Id", None)) ==
            _id_value(getattr(host, "Id", None)))


def _deduct_openings(doc, room, aggregates, host_elements, warnings, stats):
    if not aggregates:
        return
    host_rows = {}
    for row in aggregates.values():
        if row.get("surface_kind") != "wall":
            continue
        for host_value, area_ft2 in row.get("_host_areas_ft2", {}).items():
            if area_ft2 <= AREA_EPSILON_FT2:
                continue
            host_rows.setdefault(host_value, []).append((row, area_ft2))
    if not host_rows:
        return

    phases = _room_phases(doc, room, warnings)
    processed_insert_ids = set()

    for host_value, row_areas in host_rows.items():
        host = host_elements.get(host_value)
        if host is None or _boundary_category(host) != "Wall":
            continue
        find_inserts = getattr(host, "FindInserts", None)
        if find_inserts is None:
            continue
        try:
            insert_ids = list(find_inserts(True, True, True, True))
        except Exception as exc:
            _append_warning(
                warnings,
                u"房間 {0} 邊界牆 {1} 的 inserts 讀取失敗，未扣開口：{2}".format(
                    _id_value(getattr(room, "Id", None)),
                    host_value,
                    _exception_text(exc)))
            stats["opening_host_errors"] += 1
            continue

        stats["boundary_wall_hosts"] += 1
        unrelated_count = 0
        unsupported_count = 0
        opening_area = 0.0
        for insert_id in insert_ids:
            insert_value = _id_value(insert_id)
            if insert_value is None or insert_value in processed_insert_ids:
                continue
            try:
                insert = doc.GetElement(insert_id)
            except Exception as exc:
                _append_warning(
                    warnings,
                    u"牆 {0} 的 insert {1} 讀取失敗，未扣：{2}".format(
                        host_value,
                        insert_value,
                        _exception_text(exc)))
                continue
            if insert is None or not _host_matches_insert(host, insert):
                unrelated_count += 1
                continue
            belongs, evidence = _insert_belongs_to_room(
                insert, room, phases, warnings)
            if not belongs:
                if evidence == "unsupported":
                    unsupported_count += 1
                else:
                    unrelated_count += 1
                continue

            area_ft2, dimension_source = _opening_area_ft2(insert, warnings)
            if area_ft2 <= AREA_EPSILON_FT2:
                stats["openings_skipped_no_dimensions"] += 1
                continue
            processed_insert_ids.add(insert_value)
            opening_area += area_ft2
            stats["openings_deducted"] += 1
            stats["opening_dimension_sources"][dimension_source] = (
                stats["opening_dimension_sources"].get(dimension_source, 0) + 1)

        if unrelated_count:
            _append_warning(
                warnings,
                u"房間 {0} 的邊界牆 {1} 有 {2} 個 insert 無法由 FromRoom/ToRoom 證明屬於此房間，保守不扣。".format(
                    _id_value(getattr(room, "Id", None)),
                    host_value,
                    unrelated_count))
            stats["openings_skipped_unassigned"] += unrelated_count
        if unsupported_count:
            _append_warning(
                warnings,
                u"房間 {0} 的邊界牆 {1} 有 {2} 個非門窗 insert，v1 無可靠房間歸屬，保守不扣。".format(
                    _id_value(getattr(room, "Id", None)),
                    host_value,
                    unsupported_count))
            stats["openings_skipped_unsupported"] += unsupported_count
        if opening_area <= AREA_EPSILON_FT2:
            continue

        gross_host_area = sum(item[1] for item in row_areas)
        if gross_host_area <= AREA_EPSILON_FT2:
            continue
        deduction = min(opening_area, gross_host_area)
        if opening_area > gross_host_area + FACE_RECONCILE_ABS_FT2:
            _append_warning(
                warnings,
                u"房間 {0} 邊界牆 {1} 的開口面積超過可扣牆面，已 clamp 至牆面積。".format(
                    _id_value(getattr(room, "Id", None)), host_value))
            stats["opening_clamps"] += 1

        for row, row_host_area in row_areas:
            share = deduction * row_host_area / gross_host_area
            before = row["_net_area_ft2"]
            row["_net_area_ft2"] = max(0.0, before - share)
        stats["opening_area_deducted_ft2"] += deduction


def _room_height_ft(doc, room, warnings):
    height_parameter = getattr(DB.BuiltInParameter, "ROOM_HEIGHT", None)
    if height_parameter is not None:
        try:
            parameter = room.get_Parameter(height_parameter)
            if parameter is not None:
                value = float(parameter.AsDouble())
                if value > 0:
                    return value, "RoomHeight"
        except Exception as exc:
            _append_warning(
                warnings,
                u"房間 {0} ROOM_HEIGHT 讀取失敗：{1}".format(
                    _id_value(getattr(room, "Id", None)),
                    _exception_text(exc)))

    try:
        base_level = doc.GetElement(room.LevelId)
        base_elevation = float(base_level.Elevation)
        lower_offset_parameter = room.get_Parameter(
            DB.BuiltInParameter.ROOM_LOWER_OFFSET)
        lower_offset = (float(lower_offset_parameter.AsDouble())
                        if lower_offset_parameter is not None else 0.0)
        upper_parameter = room.get_Parameter(
            DB.BuiltInParameter.ROOM_UPPER_LEVEL)
        upper_level = doc.GetElement(upper_parameter.AsElementId())
        upper_elevation = float(upper_level.Elevation)
        upper_offset_parameter = room.get_Parameter(
            DB.BuiltInParameter.ROOM_UPPER_OFFSET)
        upper_offset = (float(upper_offset_parameter.AsDouble())
                        if upper_offset_parameter is not None else 0.0)
        value = ((upper_elevation + upper_offset) -
                 (base_elevation + lower_offset))
        if value > 0:
            return value, "UpperLimit"
    except Exception:
        pass

    try:
        bounding_box = room.get_BoundingBox(None)
        if bounding_box is not None:
            value = float(bounding_box.Max.Z) - float(bounding_box.Min.Z)
            if value > 0:
                _append_warning(
                    warnings,
                    u"房間 {0} 高度改用 BoundingBox 估算。".format(
                        _id_value(getattr(room, "Id", None))))
                return value, "BoundingBox"
    except Exception as exc:
        _append_warning(
            warnings,
            u"房間 {0} BoundingBox 高度讀取失敗：{1}".format(
                _id_value(getattr(room, "Id", None)),
                _exception_text(exc)))
    _append_warning(
        warnings,
        u"房間 {0} 缺少可證明高度，fallback 牆面不計算。".format(
            _id_value(getattr(room, "Id", None))))
    return None, "Unavailable"


def _fallback_material(room, surface_kind, material_by_name,
                       material_by_id, warnings):
    fallback = _room_finish_material(
        room, surface_kind, material_by_name, material_by_id, warnings)
    if fallback is not None:
        return fallback
    return _unknown_material()


def _collect_fallback_room(doc, room, boundary_mode_enum,
                           selected_surfaces, material_by_id,
                           material_by_name, warnings, stats):
    identity = _room_identity(doc, room)
    aggregates = {}
    host_elements = {}
    method = "Fallback_BoundarySegments"
    common_warning = (
        u"房間 {0} 使用 BoundarySegments × room height / Room.Area 估算；"
        u"斜面與不規則幾何不保證精確。".format(identity["room_id"]))
    _append_warning(warnings, common_warning)

    room_area = 0.0
    try:
        room_area = max(0.0, float(room.Area))
    except Exception as exc:
        _append_warning(
            warnings,
            u"房間 {0} Room.Area 讀取失敗：{1}".format(
                identity["room_id"], _exception_text(exc)))

    for surface_kind in ("floor", "ceiling"):
        if surface_kind not in selected_surfaces or room_area <= AREA_EPSILON_FT2:
            continue
        material = _fallback_material(
            room,
            surface_kind,
            material_by_name,
            material_by_id,
            warnings)
        row_warnings = [common_warning]
        if surface_kind == "ceiling":
            row_warnings.append(
                u"天花面積代表房間上界，不保證存在實體 Ceiling 元素。")
        _add_descriptor(
            aggregates,
            identity,
            {
                "area_ft2": room_area,
                "host_id": None,
                "boundary_category": "other",
                "material_id": material[0],
                "material_name": material[1],
                "material_source": material[2],
                "material_class": material[3],
                "estimated": True,
                "warnings": row_warnings,
            },
            surface_kind,
            method)

    height_ft, height_source = _room_height_ft(doc, room, warnings)
    if "wall" in selected_surfaces and height_ft is not None:
        options = DB.SpatialElementBoundaryOptions()
        options.SpatialElementBoundaryLocation = boundary_mode_enum
        try:
            loops = room.GetBoundarySegments(options)
            if loops is None:
                loops = []
        except Exception as exc:
            loops = []
            _append_warning(
                warnings,
                u"房間 {0} fallback boundary segments 讀取失敗：{1}".format(
                    identity["room_id"], _exception_text(exc)))
        material = _fallback_material(
            room, "wall", material_by_name, material_by_id, warnings)
        for loop_index, loop in enumerate(loops):
            for segment_index, segment in enumerate(loop):
                try:
                    curve = segment.GetCurve()
                    length_ft = float(curve.Length)
                    area_ft2 = length_ft * height_ft
                    if area_ft2 <= AREA_EPSILON_FT2:
                        continue
                except Exception as exc:
                    _append_warning(
                        warnings,
                        u"房間 {0} fallback loop {1} segment {2} 讀取失敗：{3}".format(
                            identity["room_id"],
                            loop_index,
                            segment_index,
                            _exception_text(exc)))
                    stats["fallback_segment_errors"] += 1
                    continue
                try:
                    host_id = segment.ElementId
                except Exception:
                    host_id = None
                host = None
                if host_id is not None and not _invalid_id(host_id):
                    try:
                        host = doc.GetElement(host_id)
                    except Exception as exc:
                        _append_warning(
                            warnings,
                            u"房間 {0} fallback 宿主 {1} 讀取失敗：{2}".format(
                                identity["room_id"],
                                _id_value(host_id),
                                _exception_text(exc)))
                    host_value = _id_value(host_id)
                    if host_value is not None and host is not None:
                        host_elements[host_value] = host
                _add_descriptor(
                    aggregates,
                    identity,
                    {
                        "area_ft2": area_ft2,
                        "host_id": host_id,
                        "boundary_category": _boundary_category(host),
                        "material_id": material[0],
                        "material_name": material[1],
                        "material_source": material[2],
                        "material_class": material[3],
                        "estimated": True,
                        "warnings": [common_warning],
                    },
                    "wall",
                    method)
                stats["fallback_segments"] += 1
        stats["fallback_height_sources"][height_source] = (
            stats["fallback_height_sources"].get(height_source, 0) + 1)
    elif "wall" in selected_surfaces:
        stats["fallback_height_sources"][height_source] = (
            stats["fallback_height_sources"].get(height_source, 0) + 1)

    stats["fallback_area_gross_ft2"] += sum(
        row["_gross_area_ft2"] for row in aggregates.values())
    return aggregates, host_elements


def _finalize_rows(aggregates, warnings, stats):
    rows = []
    ceiling_warning = (
        u"天花面積代表房間上界，不保證存在實體 Ceiling 元素。")
    for aggregate in aggregates.values():
        if aggregate["surface_kind"] == "ceiling":
            _append_warning(aggregate["warnings"], ceiling_warning)
            _append_warning(warnings, ceiling_warning)

        gross_ft2 = max(0.0, float(aggregate["_gross_area_ft2"]))
        net_ft2 = max(0.0, float(aggregate["_net_area_ft2"]))
        stats["selected_gross_area_ft2"] += gross_ft2
        stats["selected_net_area_ft2"] += net_ft2
        row = {
            "room_id": aggregate["room_id"],
            "level": aggregate["level"],
            "room_number": aggregate["room_number"],
            "room_name": aggregate["room_name"],
            "surface_kind": aggregate["surface_kind"],
            "material_id": aggregate["material_id"],
            "material_name": aggregate["material_name"],
            "material_source": aggregate["material_source"],
            "material_class": aggregate.get("material_class") or "",
            "area_m2": _area_to_m2(net_ft2),
            "face_count": int(aggregate["face_count"]),
            "boundary_category": aggregate["boundary_category"],
            "boundary_element_ids": sorted(aggregate["_boundary_ids"]),
            "method": aggregate["method"],
            "estimated": bool(aggregate["estimated"]),
            "warnings": list(aggregate["warnings"]),
        }
        rows.append(row)
    return rows


def _record_sort_key(record):
    surface_order = {"floor": 0, "wall": 1, "ceiling": 2, "other": 3}
    return (
        _natural_key(record.get("level")),
        _natural_key(record.get("room_number")),
        _natural_key(record.get("room_name")),
        record.get("room_id") or 0,
        surface_order.get(record.get("surface_kind"), 9),
        _natural_key(record.get("material_name")),
        _natural_key(record.get("boundary_category")),
    )


def _unwrap_rooms(rooms):
    if rooms is None:
        return []
    if isinstance(rooms, dict):
        return list(rooms.get("rooms") or rooms.get("records") or [])
    if isinstance(rooms, tuple) and len(rooms) == 3:
        return list(rooms[0] or [])
    return list(rooms)


def _finalize_stats(stats, warnings, record_count):
    stats["records"] = int(record_count)
    stats["warnings"] = len(warnings)
    stats["face_reconciliation_error_m2"] = round(_area_to_m2(abs(
        stats["face_area_gross_ft2"] - stats["face_reconciled_ft2"])), 9)
    stats["face_area_gross_m2"] = round(
        _area_to_m2(stats["face_area_gross_ft2"]), 9)
    stats["face_reconciled_m2"] = round(
        _area_to_m2(stats["face_reconciled_ft2"]), 9)
    stats["fallback_area_gross_m2"] = round(
        _area_to_m2(stats["fallback_area_gross_ft2"]), 9)
    stats["opening_area_deducted_m2"] = round(
        _area_to_m2(stats["opening_area_deducted_ft2"]), 9)
    stats["selected_gross_area_m2"] = round(
        _area_to_m2(stats["selected_gross_area_ft2"]), 9)
    stats["selected_net_area_m2"] = round(
        _area_to_m2(stats["selected_net_area_ft2"]), 9)
    for key in list(stats.keys()):
        if key.endswith("_ft2"):
            del stats[key]
    return stats


def collect_room_material_details(doc, rooms, boundary_mode, surface_keys):
    """Collect reconciled, read-only room surface material rows.

    ``boundary_mode`` accepts only ``Finish`` or ``Center``.  ``surface_keys``
    accepts floor/wall/ceiling/other (``None`` means all).  Precise geometry is
    attempted with one shared calculator; a room-level calculator failure uses
    the explicit estimated BoundarySegments fallback.
    """
    _require_revit()
    if doc is None:
        raise ValueError("doc is required")
    mode_name, mode_enum = _boundary_mode_value(boundary_mode)
    selected_surfaces = _normalize_surface_keys(surface_keys)
    room_list = _unwrap_rooms(rooms)

    warnings = []
    stats = {
        "boundary_mode": mode_name,
        "surface_keys": sorted(selected_surfaces),
        "rooms_requested": len(room_list),
        "rooms_processed": 0,
        "rooms_spatial": 0,
        "rooms_fallback": 0,
        "rooms_skipped": 0,
        "skipped_room_ids": [],
        "room_errors": 0,
        "faces": 0,
        "subfaces": 0,
        "face_errors": 0,
        "subface_errors": 0,
        "unknown_residual_faces": 0,
        "overreported_faces": 0,
        "boundary_wall_hosts": 0,
        "openings_deducted": 0,
        "openings_skipped_unassigned": 0,
        "openings_skipped_unsupported": 0,
        "openings_skipped_no_dimensions": 0,
        "opening_host_errors": 0,
        "opening_clamps": 0,
        "opening_dimension_sources": {},
        "fallback_segments": 0,
        "fallback_segment_errors": 0,
        "fallback_height_sources": {},
        "face_area_gross_ft2": 0.0,
        "face_reconciled_ft2": 0.0,
        "fallback_area_gross_ft2": 0.0,
        "opening_area_deducted_ft2": 0.0,
        "selected_gross_area_ft2": 0.0,
        "selected_net_area_ft2": 0.0,
    }

    if not room_list:
        _append_warning(
            warnings,
            u"指定範圍內沒有 Area > 0 的房間，未產生材質明細。")
        _finalize_stats(stats, warnings, 0)
        return {"records": [], "warnings": warnings, "stats": stats}

    material_by_id, material_by_name = _material_catalog(doc, warnings)
    options = DB.SpatialElementBoundaryOptions()
    options.SpatialElementBoundaryLocation = mode_enum
    calculator = None
    try:
        calculator = DB.SpatialElementGeometryCalculator(doc, options)
    except Exception as exc:
        _append_warning(
            warnings,
            u"SpatialElementGeometryCalculator 建立失敗；所有房間改用 fallback：{0}".format(
                _exception_text(exc)))

    all_rows = []
    try:
        for room in room_list:
            if not _is_room(room):
                stats["rooms_skipped"] += 1
                skipped_id = _id_value(getattr(room, "Id", None))
                if skipped_id is not None:
                    stats["skipped_room_ids"].append(skipped_id)
                _append_warning(
                    warnings,
                    u"輸入元素 {0} 不是 host-document Room，已略過。".format(
                        _id_value(getattr(room, "Id", None))))
                continue
            if not _room_area_positive(room):
                stats["rooms_skipped"] += 1
                skipped_id = _id_value(getattr(room, "Id", None))
                if skipped_id is not None:
                    stats["skipped_room_ids"].append(skipped_id)
                _append_warning(
                    warnings,
                    u"房間 {0} Area <= 0 或無法讀取，已略過。".format(
                        _id_value(getattr(room, "Id", None))))
                continue
            stats["rooms_processed"] += 1
            aggregates = None
            host_elements = None
            if calculator is not None:
                try:
                    aggregates, host_elements = _collect_spatial_room(
                        doc,
                        room,
                        calculator,
                        mode_name,
                        selected_surfaces,
                        material_by_id,
                        material_by_name,
                        warnings,
                        stats)
                    stats["rooms_spatial"] += 1
                except Exception as exc:
                    _append_warning(
                        warnings,
                        u"房間 {0} 精確幾何失敗，改用 fallback：{1}".format(
                            _id_value(getattr(room, "Id", None)),
                            _exception_text(exc)))
            if aggregates is None:
                try:
                    aggregates, host_elements = _collect_fallback_room(
                        doc,
                        room,
                        mode_enum,
                        selected_surfaces,
                        material_by_id,
                        material_by_name,
                        warnings,
                        stats)
                    stats["rooms_fallback"] += 1
                except Exception as exc:
                    stats["room_errors"] += 1
                    stats["rooms_skipped"] += 1
                    skipped_id = _id_value(getattr(room, "Id", None))
                    if skipped_id is not None:
                        stats["skipped_room_ids"].append(skipped_id)
                    _append_warning(
                        warnings,
                        u"房間 {0} fallback 亦失敗，未產生資料：{1}".format(
                            _id_value(getattr(room, "Id", None)),
                            _exception_text(exc)))
                    continue

            try:
                _deduct_openings(
                    doc,
                    room,
                    aggregates,
                    host_elements or {},
                    warnings,
                    stats)
            except Exception as exc:
                _append_warning(
                    warnings,
                    u"房間 {0} 開口扣除流程失敗；保留 gross 面積：{1}".format(
                        _id_value(getattr(room, "Id", None)),
                        _exception_text(exc)))
            all_rows.extend(_finalize_rows(aggregates, warnings, stats))
    finally:
        if calculator is not None:
            try:
                calculator.Dispose()
            except Exception:
                pass

    all_rows.sort(key=_record_sort_key)
    stats["skipped_room_ids"] = sorted(set(stats["skipped_room_ids"]))
    _finalize_stats(stats, warnings, len(all_rows))
    return {"records": all_rows, "warnings": warnings, "stats": stats}


__all__ = ["collect_rooms", "collect_room_material_details"]
