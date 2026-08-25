# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Revit-side collection and writing for 面積 (Area) work — JAC 01.x.

Signatures here were settled by reading ``RevitAPI.dll`` metadata directly
rather than from memory, because this repository had never touched the Area
element before and there was no existing code to copy. The surface is
byte-identical between Revit 2020 and 2024, so no version shim is needed
beyond the ``ElementId`` one every module here already carries.

Three facts from that metadata shape this module, and getting any of them
wrong would fail quietly:

``SpatialElement.Name`` **has no getter.**
    It is declared set-only, so ``area.Name`` cannot be read — only assigned.
    Reading the name has to go through ``Element.Name.GetValue(area)``, which
    is what :func:`element_name` does.

``SpatialElement.Number`` is readable *and* writable.
    So the 編號 write path is a plain property assignment, with the
    ``ROOM_NUMBER`` parameter kept as a fallback for locked templates.

Unplaced / not-enclosed / redundant areas each have their own
``FailureDefinitionId``.
    ``BuiltInFailures.RoomFailures`` exposes ``AreaUnplaceWarning``,
    ``RoomNotEnclosedAreas`` and ``RoomsInSameRegionAreas``. Matching on those
    GUIDs classifies a problem precisely, instead of guessing from warning text
    that changes with the UI language.

Everything geometric leaves here as millimetre tuples, never ``XYZ``, so the
rules in :mod:`area_placement_logic` stay testable without Revit.
"""

from Autodesk.Revit import DB

import area_placement_logic as logic
import area_renumber_logic as logic_renumber
import cad_boundary_logic as cad_logic


MM_PER_FOOT = 304.8
SQ_FT_TO_SQ_M = 0.09290304

# Warning kinds live in the logic module so the rules and the collector cannot
# drift apart; this layer only maps Revit's GUIDs onto them.
KIND_NOT_PLACED = logic.KIND_NOT_PLACED
KIND_NOT_ENCLOSED = logic.KIND_NOT_ENCLOSED
KIND_REDUNDANT = logic.KIND_REDUNDANT
KIND_BOUNDARY_OVERLAP = logic.KIND_BOUNDARY_OVERLAP
KIND_OTHER = logic.KIND_OTHER
KIND_LABELS = logic.KIND_LABELS

_WARNING_GUIDS = {}


# --- generic element helpers ----------------------------------------------

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
    """Name via ``Element.Name``, which is the only way to read a 面積 name.

    ``SpatialElement`` redeclares ``Name`` as set-only, so ``area.Name`` raises
    on read. Going through the base-class descriptor sidesteps that.
    """
    if element is None:
        return u''
    try:
        return DB.Element.Name.GetValue(element) or u''
    except Exception:
        try:
            return element.Name or u''
        except Exception:
            return u''


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


def _boundary_options(location=None):
    options = DB.SpatialElementBoundaryOptions()
    if location is None:
        location = getattr(DB.SpatialElementBoundaryLocation, 'Finish', None)
    if location is not None:
        try:
            options.SpatialElementBoundaryLocation = location
        except Exception:
            pass
    return options


def _point_xy(element):
    """``(x_mm, y_mm)`` of a spatial element's location point, or ``None``."""
    try:
        location = element.Location
    except Exception:
        return None
    if location is None:
        return None
    try:
        point = location.Point
    except Exception:
        return None
    if point is None:
        return None
    return (point.X * MM_PER_FOOT, point.Y * MM_PER_FOOT)


def _level_id(element):
    try:
        value = id_value(element.LevelId)
        if value > 0:
            return value
    except Exception:
        pass
    try:
        level = element.Level
        if level is not None:
            return id_value(level.Id)
    except Exception:
        pass
    return -1


def _elevation(level):
    try:
        return float(level.Elevation) * MM_PER_FOOT
    except Exception:
        return 0.0


def level_index(doc):
    """``{level_id: (name, elevation_mm)}`` for labelling and sort order."""
    index = {}
    try:
        levels = (DB.FilteredElementCollector(doc)
                  .OfClass(DB.Level)
                  .WhereElementIsNotElementType()
                  .ToElements())
    except Exception:
        return index
    for level in levels:
        index[id_value(level.Id)] = (element_name(level), _elevation(level))
    return index


# --- AreaScheme ------------------------------------------------------------

def area_schemes(doc):
    try:
        schemes = list(DB.FilteredElementCollector(doc)
                       .OfClass(DB.AreaScheme)
                       .ToElements())
    except Exception:
        return []
    schemes.sort(key=lambda scheme: element_name(scheme))
    return schemes


def scheme_label(scheme):
    name = element_name(scheme)
    try:
        if scheme.IsGrossBuildingArea:
            # Worth surfacing: a gross scheme measures one region per floor, so
            # seeding it per room produces a pile of redundant areas.
            return u'{}（總建築面積類型）'.format(name)
    except Exception:
        pass
    return name


# --- AreaPlan views --------------------------------------------------------

def view_area_scheme_id(view):
    """Scheme id of an area plan; ``-1`` for any other view.

    ``ViewPlan.AreaScheme`` exists on every ViewPlan but only means anything on
    an area plan, so the property access is guarded rather than the view type
    tested — Revit's own answer is more reliable than the type name.
    """
    try:
        scheme = view.AreaScheme
    except Exception:
        return -1
    if scheme is None:
        return -1
    return id_value(scheme.Id)


def view_level_id(view):
    try:
        level = view.GenLevel
        if level is not None:
            return id_value(level.Id)
    except Exception:
        pass
    return -1


def area_plan_views(doc, scheme_id=None):
    """Non-template area plans, optionally limited to one scheme."""
    views = []
    try:
        candidates = (DB.FilteredElementCollector(doc)
                      .OfClass(DB.ViewPlan)
                      .WhereElementIsNotElementType())
    except Exception:
        return views
    for view in candidates:
        try:
            if view.IsTemplate:
                continue
        except Exception:
            continue
        found = view_area_scheme_id(view)
        if found <= 0:
            continue
        if scheme_id is not None and found != scheme_id:
            continue
        views.append(view)
    levels = level_index(doc)
    views.sort(key=lambda item: (
        levels.get(view_level_id(item), (u'', 0.0))[1], element_name(item)))
    return views


def view_label(doc, view, levels=None):
    if levels is None:
        levels = level_index(doc)
    name, unused = levels.get(view_level_id(view), (u'(無樓層)', 0.0))
    # The id keeps the label unique — duplicated view names are common.
    return u'{}　[{}]　#{}'.format(
        element_name(view), name, id_value(view.Id))


# --- Areas -----------------------------------------------------------------

def area_boundary_loops(area, options=None):
    """Boundary loops as millimetre tuples; ``[]`` when nothing encloses.

    An area that does not close returns no loops, which is exactly the signal
    the placement preview needs — so an empty result is data, not an error.
    """
    if options is None:
        options = _boundary_options()
    try:
        segments = area.GetBoundarySegments(options)
    except Exception:
        return []
    loops = []
    for loop in segments or []:
        points = []
        for segment in loop:
            try:
                curve = segment.GetCurve()
            except Exception:
                curve = None
            if curve is None:
                continue
            try:
                tessellated = list(curve.Tessellate())
            except Exception:
                tessellated = []
            if not tessellated:
                try:
                    tessellated = [curve.GetEndPoint(0), curve.GetEndPoint(1)]
                except Exception:
                    tessellated = []
            for point in tessellated:
                points.append((point.X * MM_PER_FOOT, point.Y * MM_PER_FOOT))
        # Consecutive segments repeat the vertex they share; a duplicated point
        # would add zero-length edges to every geometry test downstream.
        cleaned = []
        for point in points:
            if not cleaned or (abs(point[0] - cleaned[-1][0]) > 1e-6
                               or abs(point[1] - cleaned[-1][1]) > 1e-6):
                cleaned.append(point)
        if len(cleaned) >= 3:
            loops.append(cleaned)
    return loops


def read_area_number(area):
    try:
        return area.Number or u''
    except Exception:
        return parameter_text(built_in_parameter(area, 'ROOM_NUMBER'))


def set_area_number(area, value):
    """``SpatialElement.Number`` is writable; the parameter is the fallback."""
    try:
        area.Number = value
        return True
    except Exception:
        pass
    parameter = built_in_parameter(area, 'ROOM_NUMBER')
    if parameter is None:
        return False
    try:
        return bool(parameter.Set(value))
    except Exception:
        return False


def set_area_name(area, value):
    try:
        area.Name = value
        return True
    except Exception:
        pass
    parameter = built_in_parameter(area, 'ROOM_NAME')
    if parameter is None:
        return False
    try:
        return bool(parameter.Set(value))
    except Exception:
        return False


def collect_areas(doc, scheme_id=None, level_id=None, levels=None):
    """Every Area as a plain dict, including the unplaced ones.

    Unplaced areas are deliberately kept: they are invisible in every view but
    still counted in schedules, which is precisely why the audit exists.
    """
    if levels is None:
        levels = level_index(doc)
    options = _boundary_options()
    records = []
    category = getattr(DB.BuiltInCategory, 'OST_Areas', None)
    if category is None:
        return records
    try:
        collector = (DB.FilteredElementCollector(doc)
                     .OfCategory(category)
                     .WhereElementIsNotElementType())
    except Exception:
        return records
    for area in collector:
        try:
            scheme = area.AreaScheme
        except Exception:
            scheme = None
        found_scheme = id_value(scheme.Id) if scheme is not None else -1
        if scheme_id is not None and found_scheme != scheme_id:
            continue
        found_level = _level_id(area)
        if level_id is not None and found_level != level_id:
            continue
        point = _point_xy(area)
        try:
            area_sqft = float(area.Area)
        except Exception:
            area_sqft = 0.0
        try:
            perimeter_ft = float(area.Perimeter)
        except Exception:
            perimeter_ft = 0.0
        name, elevation = levels.get(found_level, (u'(未知樓層)', 0.0))
        records.append({
            'perimeter_ft': perimeter_ft,
            'area_type': parameter_text(
                built_in_parameter(area, 'AREA_TYPE_TEXT')),
            'id': id_value(area.Id),
            'element': area,
            'element_id': area.Id,
            'number': read_area_number(area),
            'name': element_name(area),
            'scheme_id': found_scheme,
            'scheme': element_name(scheme),
            'level_id': found_level,
            'level': name,
            'level_elevation': elevation,
            'area_sqft': area_sqft,
            'placed': point is not None,
            'point_xy': point,
            'loops': area_boundary_loops(area, options),
        })
    return records


# --- warnings --------------------------------------------------------------

def _failure_guid(definition_id):
    if definition_id is None:
        return u''
    try:
        return u'{}'.format(definition_id.Guid)
    except Exception:
        return u''


def _warning_guids():
    """GUID -> kind, built once from ``BuiltInFailures``.

    Matching GUIDs rather than description text keeps this working on a
    Chinese Revit UI, where the message string is localised.
    """
    if _WARNING_GUIDS:
        return _WARNING_GUIDS
    failures = getattr(DB, 'BuiltInFailures', None)
    groups = (
        ('RoomFailures', (('AreaUnplaceWarning', KIND_NOT_PLACED),
                          ('RoomNotEnclosedAreas', KIND_NOT_ENCLOSED),
                          ('RoomsInSameRegionAreas', KIND_REDUNDANT))),
        ('OverlapFailures', (('AreaBoundaryLinesOverlap',
                              KIND_BOUNDARY_OVERLAP),)),
    )
    for group_name, entries in groups:
        group = getattr(failures, group_name, None)
        if group is None:
            continue
        for attribute, kind in entries:
            guid = _failure_guid(getattr(group, attribute, None))
            if guid:
                _WARNING_GUIDS[guid] = kind
    return _WARNING_GUIDS


def warning_flags(doc, area_ids=None):
    """``{area_id: [{'kind', 'label', 'text'}]}`` for Area-related warnings."""
    flags = {}
    try:
        warnings = list(doc.GetWarnings())
    except Exception:
        return flags
    known = _warning_guids()
    wanted = set(area_ids) if area_ids is not None else None
    for warning in warnings:
        try:
            failing = list(warning.GetFailingElements())
        except Exception:
            continue
        guid = _failure_guid_of(warning)
        kind = known.get(guid, KIND_OTHER)
        try:
            text = warning.GetDescriptionText() or u''
        except Exception:
            text = u''
        for element_id in failing:
            value = id_value(element_id)
            if wanted is not None and value not in wanted:
                continue
            entry = {'kind': kind, 'label': KIND_LABELS.get(kind, kind),
                     'text': text}
            flags.setdefault(value, []).append(entry)
    return flags


def _failure_guid_of(warning):
    try:
        return _failure_guid(warning.GetFailureDefinitionId())
    except Exception:
        return u''


# --- rooms, as the seed source --------------------------------------------

def rooms_for_level(doc, level_id=None, levels=None):
    """Rooms as seed candidates, with boundaries already reduced to mm tuples."""
    if levels is None:
        levels = level_index(doc)
    options = _boundary_options()
    records = []
    category = getattr(DB.BuiltInCategory, 'OST_Rooms', None)
    if category is None:
        return records
    try:
        collector = (DB.FilteredElementCollector(doc)
                     .OfCategory(category)
                     .WhereElementIsNotElementType())
    except Exception:
        return records
    for room in collector:
        found_level = _level_id(room)
        if level_id is not None and found_level != level_id:
            continue
        point = _point_xy(room)
        try:
            area_sqft = float(room.Area)
        except Exception:
            area_sqft = 0.0
        name, elevation = levels.get(found_level, (u'(未知樓層)', 0.0))
        records.append({
            'id': id_value(room.Id),
            'element': room,
            'element_id': room.Id,
            'room_number': parameter_text(
                built_in_parameter(room, 'ROOM_NUMBER')),
            'room_name': element_name(room),
            'level_id': found_level,
            'level': name,
            'level_elevation': elevation,
            'area_sqft': area_sqft,
            'placed': point is not None,
            'point_xy': point,
            'loops': area_boundary_loops(room, options),
        })
    return records


# --- tags ------------------------------------------------------------------

def area_tag_types(doc):
    """``[(label, type_id)]`` — ``AreaTagType`` derives from ``FamilySymbol``."""
    results = []
    category = getattr(DB.BuiltInCategory, 'OST_AreaTags', None)
    if category is None:
        return results
    try:
        symbols = list(DB.FilteredElementCollector(doc)
                       .OfCategory(category)
                       .WhereElementIsElementType()
                       .ToElements())
    except Exception:
        return results
    for symbol in symbols:
        family = u''
        try:
            family = element_name(symbol.Family)
        except Exception:
            family = u''
        label = u'{} : {}'.format(family, element_name(symbol)) if family \
            else element_name(symbol)
        results.append((label, id_value(symbol.Id)))
    results.sort()
    return results


def tagged_area_ids(doc, view_id):
    """Areas already tagged in this view, so a rerun does not double-tag."""
    tagged = set()
    category = getattr(DB.BuiltInCategory, 'OST_AreaTags', None)
    if category is None:
        return tagged
    try:
        collector = (DB.FilteredElementCollector(doc, view_id)
                     .OfCategory(category)
                     .WhereElementIsNotElementType())
    except Exception:
        return tagged
    for tag in collector:
        try:
            area = tag.Area
        except Exception:
            area = None
        if area is not None:
            tagged.add(id_value(area.Id))
    return tagged


# --- writing ---------------------------------------------------------------

class WarningSwallower(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, failures_accessor):
        for failure in failures_accessor.GetFailureMessages():
            if failure.GetSeverity() == DB.FailureSeverity.Warning:
                failures_accessor.DeleteWarning(failure)
        return DB.FailureProcessingResult.Continue


def create_area(doc, view, point_xy_mm):
    """``NewArea(ViewPlan, UV)`` — the UV is a plan point in feet."""
    point = DB.UV(point_xy_mm[0] / MM_PER_FOOT, point_xy_mm[1] / MM_PER_FOOT)
    return doc.Create.NewArea(view, point)


def create_area_tag(doc, view, area, point_xy_mm, symbol=None):
    """``NewAreaTag(ViewPlan, Area, UV)``; the type is applied afterwards."""
    point = DB.UV(point_xy_mm[0] / MM_PER_FOOT, point_xy_mm[1] / MM_PER_FOOT)
    tag = doc.Create.NewAreaTag(view, area, point)
    if tag is not None and symbol is not None:
        try:
            tag.AreaTagType = symbol
        except Exception:
            pass
    return tag


def _covered(point, loops_list):
    for loops in loops_list:
        if logic.point_in_loops(point, loops):
            return True
    return False


def trial_place(doc, view, rows):
    """Place the areas for real, measure them, then roll the whole lot back.

    Whether a seed produces an enclosed area depends on the scheme's own rules
    about which walls act as boundaries, and no amount of pure geometry can
    predict that — only Revit knows. So the preview asks Revit directly and
    then undoes it. The ``finally`` is the safety net: the Transaction is
    rolled back whether the loop finished, raised, or was interrupted, so this
    can never leave a half-placed area behind.

    Returns ``{room_id: {'enclosed', 'self_covered', 'area_sqft'}}`` containing
    no Revit objects, so the result can be handed to the pure planner.
    """
    results = {}
    options = _boundary_options()
    transaction = DB.Transaction(doc, u'面積試放（僅預覽，會自動回復）')
    transaction.Start()
    handling = transaction.GetFailureHandlingOptions()
    handling.SetFailuresPreprocessor(WarningSwallower())
    transaction.SetFailureHandlingOptions(handling)
    covered = []
    try:
        for row in rows or []:
            key = row.get('id')
            point = row.get('point_xy')
            if point is None:
                results[key] = {'enclosed': False, 'self_covered': False,
                                'area_sqft': 0.0}
                continue
            if _covered(point, covered):
                results[key] = {'enclosed': True, 'self_covered': True,
                                'area_sqft': 0.0}
                continue
            try:
                area = create_area(doc, view, point)
            except Exception:
                results[key] = {'enclosed': False, 'self_covered': False,
                                'area_sqft': 0.0}
                continue
            if area is None:
                results[key] = {'enclosed': False, 'self_covered': False,
                                'area_sqft': 0.0}
                continue
            try:
                doc.Regenerate()
            except Exception:
                pass
            try:
                area_sqft = float(area.Area)
            except Exception:
                area_sqft = 0.0
            loops = area_boundary_loops(area, options)
            enclosed = area_sqft > 0.0 and bool(loops)
            results[key] = {'enclosed': enclosed, 'self_covered': False,
                            'area_sqft': area_sqft}
            if enclosed:
                covered.append(loops)
    finally:
        transaction.RollBack()
    return results


def readable_parameters(element):
    """``[(label, name)]`` of parameters on an element that hold readable text.

    棟別 / 分類 / 戶別 are project parameters with no fixed names — every office
    calls them something slightly different — so the button asks which ones to
    read rather than guessing. See
    domain/user-specified-runtime-parameters.md.
    """
    found = {}
    if element is None:
        return []
    try:
        parameters = list(element.Parameters)
    except Exception:
        return []
    for parameter in parameters:
        try:
            definition = parameter.Definition
            name = definition.Name if definition is not None else None
        except Exception:
            name = None
        if not name or name in found:
            continue
        try:
            storage = parameter.StorageType
        except Exception:
            continue
        if storage not in (DB.StorageType.String, DB.StorageType.ElementId,
                           DB.StorageType.Integer):
            continue
        sample = parameter_text(parameter)
        label = u'{}　（目前：{}）'.format(name, sample or u'空白')
        found[name] = label
    return sorted((label, name) for name, label in found.items())


def read_named_parameter(element, name):
    """Instance parameter first, then the type — either can carry the value."""
    if not name or element is None:
        return u''
    try:
        parameter = element.LookupParameter(name)
    except Exception:
        parameter = None
    if parameter is not None:
        return parameter_text(parameter)
    return u''


BOUNDARY_LOCATIONS = (
    (u'牆中心線 Center（共用牆合成一條，建議）', 'Center'),
    (u'牆面 Finish（共用牆各自一條，相距一個牆厚）', 'Finish'),
    (u'核心層邊界 CoreBoundary', 'CoreBoundary'),
    (u'核心層中心 CoreCenter', 'CoreCenter'),
)


def boundary_location(name):
    return getattr(DB.SpatialElementBoundaryLocation, name, None)


def room_boundary_curves(doc, level_id=None, location_name='Center'):
    """Room boundary segments on a level, as real curves plus mm sample points.

    ``BoundarySegment.GetCurve()`` returns the actual line or arc, so the
    regenerated boundary keeps its curvature. Rebuilding from the tessellated
    points instead would turn every arc into a fan of short straight lines.
    """
    rows = []
    options = _boundary_options(boundary_location(location_name))
    category = getattr(DB.BuiltInCategory, 'OST_Rooms', None)
    if category is None:
        return rows
    try:
        collector = (DB.FilteredElementCollector(doc)
                     .OfCategory(category)
                     .WhereElementIsNotElementType())
    except Exception:
        return rows
    for room in collector:
        if level_id is not None and _level_id(room) != level_id:
            continue
        try:
            loops = room.GetBoundarySegments(options)
        except Exception:
            continue
        for loop in loops or []:
            for segment in loop:
                try:
                    curve = segment.GetCurve()
                except Exception:
                    curve = None
                if curve is None:
                    continue
                points = []
                try:
                    for point in curve.Tessellate():
                        points.append((point.X * MM_PER_FOOT,
                                       point.Y * MM_PER_FOOT))
                except Exception:
                    points = []
                rows.append({
                    'id': len(rows) + 1,
                    'room_id': id_value(room.Id),
                    'room_number': parameter_text(
                        built_in_parameter(room, 'ROOM_NUMBER')),
                    # Carried so a room picker can label rows by name as well
                    # as number; SpatialElement.Name is set-only, hence the
                    # helper rather than room.Name.
                    'room_name': element_name(room),
                    'element_id': room.Id,
                    'curve': curve,
                    'points': points,
                })
    return rows


def _compound_layers(wall_type):
    """``(layer_widths_ft, first_core, last_core)`` for a wall type.

    Layers come back exterior-to-interior, which is what lets the core be
    located by walking inward from each face.
    """
    try:
        structure = wall_type.GetCompoundStructure()
    except Exception:
        structure = None
    if structure is None:
        return [], None, None
    widths = []
    try:
        for index in range(structure.LayerCount):
            widths.append(float(structure.GetLayerWidth(index)))
    except Exception:
        return [], None, None
    first = last = None
    try:
        first = int(structure.GetFirstCoreLayerIndex())
        last = int(structure.GetLastCoreLayerIndex())
    except Exception:
        first = last = None
    return widths, first, last


def collect_walls(doc, level_id=None, view=None):
    """Walls as plain dicts for :mod:`wall_boundary_logic`, plus the curve.

    Widths stay in feet: the offset maths only sums and halves them, so the
    unit only has to be consistent, and converting twice is a chance to be
    wrong.
    """
    rows = []
    category = getattr(DB.BuiltInCategory, 'OST_Walls', None)
    if category is None:
        return rows
    try:
        if view is not None:
            collector = DB.FilteredElementCollector(doc, view.Id)
        else:
            collector = DB.FilteredElementCollector(doc)
        collector = collector.OfCategory(category).WhereElementIsNotElementType()
    except Exception:
        return rows

    for wall in collector:
        if level_id is not None and _level_id(wall) != level_id:
            continue
        try:
            location = wall.Location
            curve = location.Curve if location is not None else None
        except Exception:
            curve = None
        try:
            wall_type = wall.WallType
        except Exception:
            wall_type = None
        widths, first_core, last_core = _compound_layers(wall_type) \
            if wall_type is not None else ([], None, None)
        try:
            is_curtain = wall.CurtainGrid is not None
        except Exception:
            is_curtain = False
        try:
            stacked = bool(wall.IsStackedWall)
        except Exception:
            stacked = False
        try:
            normal = wall.Orientation
        except Exception:
            normal = None
        location_line = u''
        parameter = built_in_parameter(wall, 'WALL_KEY_REF_PARAM')
        if parameter is not None:
            try:
                enum = getattr(DB, 'WallLocationLine', None)
                if enum is not None:
                    location_line = u'{}'.format(
                        enum.ToObject(enum, parameter.AsInteger()))
            except Exception:
                location_line = u''
        try:
            width = float(wall.Width)
        except Exception:
            width = 0.0

        rows.append({
            'id': id_value(wall.Id),
            'element': wall,
            'element_id': wall.Id,
            'name': element_name(wall_type),
            'curve': curve,
            'normal': normal,
            'has_curve': curve is not None and normal is not None,
            'width': width,
            'layer_widths': widths,
            'first_core': first_core,
            'last_core': last_core,
            'is_curtain': is_curtain,
            'is_stacked': stacked,
            'location_line': location_line,
            'level_id': _level_id(wall),
        })
    return rows


def offset_curve(curve, normal, distance_ft):
    """Move a curve ``distance_ft`` along ``normal``; ``None`` if it cannot.

    A straight wall is translated, which is exact and has no sign ambiguity.
    A curved wall needs a true offset — a translated arc keeps its radius and
    would no longer follow the wall — and ``CreateOffset``'s sign depends on
    the curve's own direction, so the result is *checked* against the intended
    side and retried the other way rather than assumed. Getting that sign
    wrong would put every boundary on the wrong face of every curved wall.
    """
    if abs(distance_ft) < 1e-9:
        return curve
    try:
        vector = DB.XYZ(normal.X * distance_ft, normal.Y * distance_ft,
                        normal.Z * distance_ft)
    except Exception:
        return None
    if isinstance(curve, DB.Line):
        try:
            return curve.CreateTransformed(
                DB.Transform.CreateTranslation(vector))
        except Exception:
            return None
    for sign in (1.0, -1.0):
        try:
            candidate = curve.CreateOffset(distance_ft * sign, DB.XYZ.BasisZ)
        except Exception:
            continue
        if candidate is None:
            continue
        try:
            moved = candidate.GetEndPoint(0) - curve.GetEndPoint(0)
            along = (moved.X * normal.X + moved.Y * normal.Y
                     + moved.Z * normal.Z)
        except Exception:
            continue
        if (along > 0) == (distance_ft > 0):
            return candidate
    return None


def sketch_plane_for_level(doc, level_id):
    """A sketch plane on the level's datum, for drawing boundary lines on."""
    return DB.SketchPlane.Create(doc, DB.ElementId(int(level_id)))


def level_elevation_feet(doc, level_id):
    try:
        level = doc.GetElement(DB.ElementId(int(level_id)))
        return float(level.Elevation)
    except Exception:
        return 0.0


def create_boundary_line_from_curve(doc, view, curve, sketch_plane,
                                    target_z=None):
    """Draw one area boundary line, moving the curve onto the plane's height.

    A room's boundary sits at that room's own base height, which is not always
    the level's. Translating in Z keeps the curve's type intact — flattening it
    by rebuilding from endpoints would silently straighten every arc.
    """
    if target_z is not None:
        try:
            source_z = curve.GetEndPoint(0).Z
            delta = float(target_z) - float(source_z)
            if abs(delta) > 1e-9:
                curve = curve.CreateTransformed(
                    DB.Transform.CreateTranslation(DB.XYZ(0.0, 0.0, delta)))
        except Exception:
            pass
    return doc.Create.NewAreaBoundaryLine(sketch_plane, curve, view)


def regenerate_boundary_lines(doc, view, level_id, draw_rows, delete_ids):
    """Delete then draw, in one Transaction. Returns ``(drawn, deleted, error)``.

    Deletion runs first so a regenerate-with-clear cannot trip over its own
    output, and the whole thing rolls back together — a half-cleared area plan
    with no lines is worse than either end state.
    """
    drawn = 0
    deleted = 0
    transaction = DB.Transaction(doc, u'區域線重新生成')
    transaction.Start()
    handling = transaction.GetFailureHandlingOptions()
    handling.SetFailuresPreprocessor(WarningSwallower())
    transaction.SetFailureHandlingOptions(handling)
    try:
        for value in delete_ids or []:
            try:
                doc.Delete(DB.ElementId(int(value)))
                deleted += 1
            except Exception as error:
                raise RuntimeError(u'刪除區域線 {} 失敗：{}'.format(
                    value, error))
        if draw_rows:
            sketch_plane = sketch_plane_for_level(doc, level_id)
            target_z = level_elevation_feet(doc, level_id)
            for row in draw_rows:
                created = create_boundary_line_from_curve(
                    doc, view, row['curve'], sketch_plane, target_z)
                if created is None:
                    # Rows arrive from three different sources now (rooms,
                    # walls, CAD layers), so the label falls back rather than
                    # reporting a room number the row never had.
                    label = (row.get('room_number') or row.get('room_id')
                             or row.get('layer') or row.get('index'))
                    raise RuntimeError(
                        u'區域線建立失敗（來源 {}）'.format(label))
                drawn += 1
        transaction.Commit()
        return drawn, deleted, None
    except Exception as error:
        transaction.RollBack()
        return 0, 0, u'{}'.format(error)


def collect_boundary_lines(doc, view):
    """Area boundary lines visible in one area plan, as mm point lists.

    ``OST_AreaSchemeLines`` is the category Revit files these under; the name
    says scheme rather than boundary, which is why it is easy to look for the
    wrong one.
    """
    rows = []
    category = getattr(DB.BuiltInCategory, 'OST_AreaSchemeLines', None)
    if category is None or view is None:
        return rows
    try:
        collector = (DB.FilteredElementCollector(doc, view.Id)
                     .OfCategory(category)
                     .WhereElementIsNotElementType())
    except Exception:
        return rows
    for element in collector:
        try:
            curve = element.GeometryCurve
        except Exception:
            curve = None
        points = []
        if curve is not None:
            try:
                for point in curve.Tessellate():
                    points.append((point.X * MM_PER_FOOT,
                                   point.Y * MM_PER_FOOT))
            except Exception:
                points = []
        rows.append({
            'id': id_value(element.Id),
            'element': element,
            'element_id': element.Id,
            'curve': curve,
            'points': points,
        })
    return rows


def create_boundary_line(doc, view, source_element):
    """Redraw one boundary line in ``view`` using the source line's geometry.

    The source line's own sketch plane is reused. That is only valid because
    the button restricts the copy to plans on the same level — a different
    level would need the curve moved in Z as well, and silently drawing it at
    the wrong height is worse than refusing.
    """
    curve = source_element.GeometryCurve
    sketch_plane = source_element.SketchPlane
    created = doc.Create.NewAreaBoundaryLine(sketch_plane, curve, view)
    if created is not None:
        try:
            created.LineStyle = source_element.LineStyle
        except Exception:
            pass
    return created


def trial_copy(doc, target_view, line_rows, area_rows):
    """Draw the lines, place the areas, measure, then roll all of it back.

    Both halves have to happen inside one experiment: an area copied without
    its boundary encloses nothing, so measuring the areas before the lines
    exist would report a failure that the real run would not have.

    Returns ``{source_area_id: {'enclosed', 'area_sqft'}}`` with no Revit
    objects in it.
    """
    results = {}
    options = _boundary_options()
    transaction = DB.Transaction(doc, u'複製面積試放（僅預覽，會自動回復）')
    transaction.Start()
    handling = transaction.GetFailureHandlingOptions()
    handling.SetFailuresPreprocessor(WarningSwallower())
    transaction.SetFailureHandlingOptions(handling)
    try:
        for row in line_rows or []:
            try:
                create_boundary_line(doc, target_view, row['element'])
            except Exception:
                pass
        try:
            doc.Regenerate()
        except Exception:
            pass
        for row in area_rows or []:
            key = row.get('id')
            point = row.get('point_xy')
            if point is None:
                results[key] = {'enclosed': False, 'area_sqft': 0.0}
                continue
            try:
                area = create_area(doc, target_view, point)
            except Exception:
                area = None
            if area is None:
                results[key] = {'enclosed': False, 'area_sqft': 0.0}
                continue
            try:
                doc.Regenerate()
            except Exception:
                pass
            try:
                area_sqft = float(area.Area)
            except Exception:
                area_sqft = 0.0
            enclosed = area_sqft > 0.0 and bool(
                area_boundary_loops(area, options))
            results[key] = {'enclosed': enclosed, 'area_sqft': area_sqft}
    finally:
        transaction.RollBack()
    return results


def copy_to_scheme(doc, target_view, line_rows, area_rows):
    """Commit the copy. Returns ``(lines, areas, error)``; all or nothing."""
    lines = 0
    areas = 0
    transaction = DB.Transaction(doc, u'複製面積到其他面積計畫')
    transaction.Start()
    handling = transaction.GetFailureHandlingOptions()
    handling.SetFailuresPreprocessor(WarningSwallower())
    transaction.SetFailureHandlingOptions(handling)
    try:
        for row in line_rows or []:
            if create_boundary_line(doc, target_view, row['element']) is None:
                raise RuntimeError(
                    u'邊界線 {} 複製失敗'.format(row.get('id')))
            lines += 1
        if line_rows:
            try:
                doc.Regenerate()
            except Exception:
                pass
        for row in area_rows or []:
            point = row.get('point_xy')
            area = create_area(doc, target_view, point)
            if area is None:
                raise RuntimeError(u'面積 {} 建立失敗'.format(
                    row.get('target_number') or row.get('id')))
            try:
                doc.Regenerate()
            except Exception:
                pass
            try:
                area_sqft = float(area.Area)
            except Exception:
                area_sqft = 0.0
            if area_sqft <= 0.0:
                raise RuntimeError(
                    u'面積 {} 在目標計畫未封閉，整批取消'.format(
                        row.get('target_number') or row.get('id')))
            number = row.get('target_number')
            if number and not set_area_number(area, number):
                raise RuntimeError(u'編號「{}」寫入被拒絕'.format(number))
            name = row.get('target_name')
            if name and not set_area_name(area, name):
                raise RuntimeError(u'名稱「{}」寫入被拒絕'.format(name))
            areas += 1
        transaction.Commit()
        return lines, areas, None
    except Exception as error:
        transaction.RollBack()
        return 0, 0, u'{}'.format(error)


def delete_elements(doc, element_ids, transaction_name=u'清除元素'):
    """Delete a list of element ids in one Transaction. Returns ``(n, error)``.

    All or nothing: a half-cleared area plan — boundaries gone but areas left,
    or the reverse — is worse than either end state, and there is nothing to
    rebuild from afterwards.

    Ids that have already gone are counted as done rather than treated as a
    failure: deleting an area can take its own boundary lines with it, so the
    list can contain ids that no longer resolve by the time they come up.
    """
    removed = 0
    transaction = DB.Transaction(doc, transaction_name)
    transaction.Start()
    handling = transaction.GetFailureHandlingOptions()
    handling.SetFailuresPreprocessor(WarningSwallower())
    transaction.SetFailureHandlingOptions(handling)
    try:
        for value in element_ids or []:
            element_id = DB.ElementId(int(value))
            if doc.GetElement(element_id) is None:
                continue
            doc.Delete(element_id)
            removed += 1
        transaction.Commit()
        return removed, None
    except Exception as error:
        transaction.RollBack()
        return 0, u'{}'.format(error)


def renumber_areas(doc, rows, two_phase=False):
    """Rewrite 編號 for a set of areas. Returns ``(count, error)``.

    When ``two_phase`` is set, every area is first given a throwaway number and
    only then its final one. That extra pass exists because Revit *warns* about
    duplicate area numbers instead of rejecting them: a straight pass through a
    swap would leave two areas holding the same 編號 at the moment of the first
    write, and Revit would let it commit. The temporary numbers guarantee no
    two areas ever claim the same one.

    Either way it is a single Transaction, so a refusal anywhere rolls back the
    whole run rather than leaving half the plan renumbered.
    """
    written = 0
    transaction = DB.Transaction(doc, u'面積重新編號')
    transaction.Start()
    handling = transaction.GetFailureHandlingOptions()
    handling.SetFailuresPreprocessor(WarningSwallower())
    transaction.SetFailureHandlingOptions(handling)
    try:
        if two_phase:
            existing = [read_area_number(row['element']) for row in rows or []]
            temps = logic_renumber.temporary_numbers(rows, taken=existing)
            for row, temp in zip(rows or [], temps):
                if not set_area_number(row['element'], temp):
                    raise RuntimeError(
                        u'暫時編號「{}」寫入被拒絕'.format(temp))
        for row in rows or []:
            target = row.get('target')
            if not set_area_number(row['element'], target):
                raise RuntimeError(u'編號「{}」寫入被拒絕'.format(target))
            written += 1
        transaction.Commit()
        return written, None
    except Exception as error:
        transaction.RollBack()
        return 0, u'{}'.format(error)


def place_areas(doc, view, rows, tag_type_id=None):
    """One Transaction, all or nothing. Returns ``(created, tagged, error)``.

    Any refusal — a zero-area result, a rejected 編號, a failed tag — raises and
    rolls the whole run back, so the model never keeps the unplaced-area debris
    that a partial run would leave behind.
    """
    created = 0
    tagged = 0
    transaction = DB.Transaction(doc, u'自動放置面積')
    transaction.Start()
    handling = transaction.GetFailureHandlingOptions()
    handling.SetFailuresPreprocessor(WarningSwallower())
    transaction.SetFailureHandlingOptions(handling)
    try:
        symbol = None
        if tag_type_id:
            symbol = doc.GetElement(DB.ElementId(int(tag_type_id)))
            if symbol is not None:
                try:
                    if not symbol.IsActive:
                        symbol.Activate()
                        doc.Regenerate()
                except Exception:
                    pass
        for row in rows or []:
            point = row.get('point_xy')
            if point is None:
                raise RuntimeError(u'房間 {} 沒有可用的種子點'.format(
                    row.get('room_number') or row.get('id')))
            area = create_area(doc, view, point)
            if area is None:
                raise RuntimeError(u'房間 {} 建立面積失敗'.format(
                    row.get('room_number') or row.get('id')))
            try:
                doc.Regenerate()
            except Exception:
                pass
            try:
                area_sqft = float(area.Area)
            except Exception:
                area_sqft = 0.0
            if area_sqft <= 0.0:
                raise RuntimeError(
                    u'房間 {} 的面積未封閉（面積為 0），整批取消'.format(
                        row.get('room_number') or row.get('id')))
            number = row.get('number')
            if number and not set_area_number(area, number):
                raise RuntimeError(u'編號「{}」寫入被拒絕'.format(number))
            name = row.get('name')
            if name and not set_area_name(area, name):
                raise RuntimeError(u'名稱「{}」寫入被拒絕'.format(name))
            created += 1
            if symbol is not None:
                tag = create_area_tag(doc, view, area, point, symbol)
                if tag is None:
                    raise RuntimeError(u'面積 {} 的標籤放置失敗'.format(
                        number or created))
                tagged += 1
        transaction.Commit()
        return created, tagged, None
    except Exception as error:
        transaction.RollBack()
        return 0, 0, u'{}'.format(error)


# --- CAD 圖層轉區域線（JAC 04.01）--------------------------------------

def cad_imports(doc):
    """``[(label, ImportInstance)]`` of every DWG/DXF in the document.

    Both imported and linked CAD come back as ``ImportInstance``; the two are
    told apart by ``IsLinked`` and labelled, because a linked drawing that gets
    reloaded will silently change what this button produces next time.
    """
    category = getattr(DB.BuiltInCategory, 'OST_ImportObjectStyles', None)
    found = []
    try:
        elements = list(DB.FilteredElementCollector(doc)
                        .OfClass(DB.ImportInstance)
                        .WhereElementIsNotElementType()
                        .ToElements())
    except Exception:
        return found
    for element in elements:
        try:
            linked = bool(element.IsLinked)
        except Exception:
            linked = False
        try:
            type_name = element_name(doc.GetElement(element.GetTypeId()))
        except Exception:
            type_name = u''
        name = type_name or element_name(element) or u'(未命名)'
        label = u'{}　{}　[{}]'.format(
            name, u'連結' if linked else u'匯入', id_value(element.Id))
        found.append((label, element))
    found.sort(key=lambda entry: entry[0])
    return found


def _layer_name(doc, geometry_object, cache):
    """The CAD layer a geometry object came from.

    Revit models a DWG layer as a subcategory of the import, reachable only
    through the object's ``GraphicsStyleId`` — there is no layer property.
    """
    try:
        style_id = geometry_object.GraphicsStyleId
    except Exception:
        return u''
    key = id_value(style_id)
    if key in cache:
        return cache[key]
    name = u''
    try:
        style = doc.GetElement(style_id)
        if style is not None:
            category = style.GraphicsStyleCategory
            if category is not None:
                name = category.Name or u''
    except Exception:
        name = u''
    cache[key] = name
    return name


def _xy_mm(point):
    return (float(point.X) * MM_PER_FOOT, float(point.Y) * MM_PER_FOOT)


def _curve_record(curve, layer, index):
    """One plain-data row plus the live Curve, or ``None`` if unusable."""
    try:
        start = curve.GetEndPoint(0)
        end = curve.GetEndPoint(1)
        length_mm = float(curve.Length) * MM_PER_FOOT
    except Exception:
        return None
    try:
        mid = curve.Evaluate(0.5, True)
    except Exception:
        mid = None
    name = type(curve).__name__
    if name not in (cad_logic.KIND_LINE, cad_logic.KIND_ARC):
        name = cad_logic.KIND_OTHER
    return {
        'index': index,
        'layer': layer or u'(無圖層)',
        'kind': name,
        'start': _xy_mm(start),
        'end': _xy_mm(end),
        'mid': _xy_mm(mid) if mid is not None else None,
        'length_mm': length_mm,
        'curve': curve,
    }


def _explode_polyline(polyline, layer, next_index):
    """A DWG polyline is a ``PolyLine``, not a ``Curve``.

    Revit hands LWPOLYLINE geometry over as a bare coordinate list, so it has
    to be rebuilt into ``Line`` segments before anything can be drawn from it.
    Repeated vertices are common — a closing vertex on top of the start point,
    or a double-click while drafting — and ``Line.CreateBound`` throws on a
    zero-length segment, so those are dropped rather than allowed to abort the
    whole import.
    """
    rows = []
    try:
        points = list(polyline.GetCoordinates())
    except Exception:
        return rows, next_index
    for position in range(len(points) - 1):
        first = points[position]
        second = points[position + 1]
        try:
            if first.DistanceTo(second) < 1e-7:
                continue
            line = DB.Line.CreateBound(first, second)
        except Exception:
            continue
        row = _curve_record(line, layer, next_index)
        if row is not None:
            rows.append(row)
            next_index += 1
    return rows, next_index


def _walk_geometry(doc, geometry, layer_cache, rows, next_index, depth=0):
    if geometry is None or depth > 6:
        return next_index
    for item in geometry:
        try:
            if isinstance(item, DB.GeometryInstance):
                # GetInstanceGeometry() applies the import's placement, so the
                # curves come back already in project coordinates.
                next_index = _walk_geometry(
                    doc, item.GetInstanceGeometry(), layer_cache, rows,
                    next_index, depth + 1)
                continue
            layer = _layer_name(doc, item, layer_cache)
            if isinstance(item, DB.PolyLine):
                more, next_index = _explode_polyline(item, layer, next_index)
                rows.extend(more)
                continue
            if isinstance(item, DB.Curve):
                row = _curve_record(item, layer, next_index)
                if row is not None:
                    rows.append(row)
                    next_index += 1
        except Exception:
            continue
    return next_index


def cad_layer_curves(doc, import_instance, view=None):
    """Every curve in one CAD import, tagged with its layer.

    ``IncludeNonVisibleObjects`` is on: a layer switched off in the current
    view still holds the geometry someone wants to trace, and having the answer
    depend on view visibility settings makes the button unpredictable.
    """
    options = DB.Options()
    options.ComputeReferences = False
    options.IncludeNonVisibleObjects = True
    if view is not None:
        try:
            options.View = view
        except Exception:
            pass
    try:
        geometry = import_instance.get_Geometry(options)
    except Exception:
        return []
    rows = []
    _walk_geometry(doc, geometry, {}, rows, 0)
    return rows


def redundant_area_groups(doc, area_ids=None):
    """``[[area_id, ...], ...]`` — the areas sharing each enclosed region.

    :func:`warning_flags` flattens warnings to one entry per element, which
    answers 「這個面積有沒有問題」 but loses 「哪些面積是同一組」. Dedup needs the
    grouping: each ``RoomsInSameRegionAreas`` warning's failing elements *are*
    one region's duplicates, straight from Revit rather than re-derived from
    geometry.
    """
    groups = []
    try:
        warnings = list(doc.GetWarnings())
    except Exception:
        return groups
    known = _warning_guids()
    wanted = set(area_ids) if area_ids is not None else None
    for warning in warnings:
        if known.get(_failure_guid_of(warning)) != KIND_REDUNDANT:
            continue
        try:
            failing = list(warning.GetFailingElements())
        except Exception:
            continue
        members = []
        for element_id in failing:
            value = id_value(element_id)
            if wanted is not None and value not in wanted:
                continue
            if value not in members:
                members.append(value)
        # A one-element group means the rest of the region's areas fell
        # outside the requested scheme or level; that is not a duplicate here.
        if len(members) >= 2:
            groups.append(members)
    return groups


# --- Revit links, as a wall source (JAC 04.10) ----------------------------

def link_instances(doc):
    """``[(label, RevitLinkInstance)]`` for links whose document is loaded.

    An unloaded link still has an instance in the host but
    ``GetLinkDocument()`` returns ``None``; offering it would only produce an
    empty result later, so it is filtered here where the reason is obvious.
    """
    found = []
    try:
        instances = list(DB.FilteredElementCollector(doc)
                         .OfClass(DB.RevitLinkInstance)
                         .WhereElementIsNotElementType()
                         .ToElements())
    except Exception:
        return found
    for instance in instances:
        try:
            linked = instance.GetLinkDocument()
        except Exception:
            linked = None
        if linked is None:
            continue
        try:
            title = linked.Title or element_name(instance)
        except Exception:
            title = element_name(instance)
        found.append((u'{}　[{}]'.format(title, id_value(instance.Id)),
                      instance))
    found.sort(key=lambda entry: entry[0])
    return found


def link_levels(link_doc):
    """``[{'id', 'name', 'elevation_mm'}]`` from inside the linked document."""
    levels = []
    try:
        elements = list(DB.FilteredElementCollector(link_doc)
                        .OfClass(DB.Level)
                        .WhereElementIsNotElementType()
                        .ToElements())
    except Exception:
        return levels
    for level in elements:
        levels.append({
            'id': id_value(level.Id),
            'name': element_name(level),
            'elevation_mm': _elevation(level),
        })
    return levels


def transform_wall_rows(rows, transform):
    """Move link-space wall geometry into host space.

    The curve goes through ``CreateTransformed``; the normal goes through
    ``OfVector`` and **not** ``OfPoint`` — a normal is a direction, and
    ``OfPoint`` would add the link's translation to it, sending every offset
    the wrong way while still looking like a plausible vector.
    """
    if transform is None:
        return rows
    try:
        if transform.IsIdentity:
            return rows
    except Exception:
        pass
    moved = []
    for row in rows or []:
        item = dict(row)
        curve = row.get('curve')
        normal = row.get('normal')
        try:
            item['curve'] = (curve.CreateTransformed(transform)
                             if curve is not None else None)
        except Exception:
            item['curve'] = None
        try:
            item['normal'] = (transform.OfVector(normal)
                              if normal is not None else None)
        except Exception:
            item['normal'] = None
        item['has_curve'] = (item['curve'] is not None
                             and item['normal'] is not None)
        moved.append(item)
    return moved


def collect_link_walls(instance, level_id=None):
    """Walls from a linked document, already in host coordinates.

    Reuses :func:`collect_walls` against the linked document so the compound
    structure and Location Line handling is the one already tested for host
    walls, then moves the geometry across.
    """
    try:
        link_doc = instance.GetLinkDocument()
    except Exception:
        link_doc = None
    if link_doc is None:
        return []
    rows = collect_walls(link_doc, level_id=level_id)
    try:
        transform = instance.GetTotalTransform()
    except Exception:
        transform = None
    return transform_wall_rows(rows, transform)
