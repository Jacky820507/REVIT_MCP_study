# -*- coding: utf-8 -*-
from __future__ import unicode_literals

__title__ = u'RC體積\nExcel'
__author__ = 'Claude'

"""RC wall volume takeoff.

Sheet 1 keeps the 輕隔間 Excel layout (room -> wall type -> openings -> total)
with 厚度 and 體積 added; sheet 2 is the per-wall audit list that mirrors the
牆面清單 export, so every m³ on sheet 1 can be traced to a wall ElementId,
its grid location and the openings deducted from it.
"""

import math
import os
import re

import clr

clr.AddReference('System.IO.Compression')
clr.AddReference('System.IO.Compression.FileSystem')

from Autodesk.Revit.DB import (  # noqa: E402
    BooleanOperationsType,
    BooleanOperationsUtils,
    BoundingBoxIntersectsFilter,
    BuiltInCategory,
    BuiltInParameter,
    Element,
    ElementId,
    FamilyInstance,
    FilteredElementCollector,
    GeometryInstance,
    Grid,
    JoinGeometryUtils,
    Line,
    LocationCurve,
    Options,
    Outline,
    Solid,
    SpatialElement,
    SpatialElementBoundaryLocation,
    SpatialElementBoundaryOptions,
    ViewDetailLevel,
    Wall,
    XYZ,
)
from System import String  # noqa: E402
from System.IO import FileAccess, FileMode, FileStream, StreamWriter  # noqa: E402
from System.IO.Compression import ZipArchive, ZipArchiveMode  # noqa: E402
from System.Text import Encoding  # noqa: E402

from pyrevit import forms, revit, script  # noqa: E402

import rc_volume_logic as logic  # noqa: E402
import sheet_layout  # noqa: E402
import takeoff_excel_styles  # noqa: E402
import scaffold_height_logic  # noqa: E402

try:
    import scaffold_height  # noqa: E402
    try:
        reload(scaffold_height)
    except Exception:
        pass
except Exception:
    scaffold_height = None

try:
    reload(logic)
except Exception:
    pass


TITLE = u'RC體積 Excel'
FT_TO_M = 0.3048
SQFT_TO_SQM = 0.09290304
CUFT_TO_CUM = 0.028316846592
FIRST_DATA_ROW = 6
SUMMARY_LABEL = u'RC 體積總計 (m³)'

# Sheet 1 的欄位順序。公式一律用這些名字寫（見 lib\sheet_layout.py）：欄位字母
# 由 layout 在寫檔那一刻算出來，中間插一欄不需要回頭改任何一段公式。
SUMMARY_COLUMNS = [
    'room_no',          # 編號
    'room_name',        # 空間名稱
    'room_perimeter',   # 空間周長
    'wall_type',        # RC 牆類型
    'length',           # 牆長
    'height',           # 牆高
    'thickness',        # 厚度
    'area',             # 面積
    'area_subtotal',    # 小計
    'opening_name',     # 開口名稱
    'opening_count',    # 開口數量
    'opening_width',    # 開口長
    'opening_height',   # 開口高
    'opening_area',     # 開口面積
    'opening_subtotal', # 開口小計
    'net_area',         # 淨面積
    'gross_volume',     # 毛體積 (m³)
    'overlap_deduct',   # 樑柱板扣除 (m³)
    'net_volume',       # 淨體積 (m³)
]
# 與 SUMMARY_COLUMNS 一一對應的表頭文字。
SUMMARY_HEADERS = [
    u'編號', u'空間名稱', u'空間周長', u'RC 牆類型', u'牆長', u'牆高',
    u'厚度', u'面積', u'小計',
    u'名稱', u'數量', u'長', u'高', u'面積', u'小計',
    u'淨面積', u'毛體積 (m³)', u'樑柱板扣除 (m³)', u'淨體積 (m³)',
]
if len(SUMMARY_COLUMNS) != len(SUMMARY_HEADERS):
    raise AssertionError(
        u'SUMMARY_COLUMNS 與 SUMMARY_HEADERS 長度不一致（{0} vs {1}）：'
        u'加欄位時兩邊都要加'.format(
            len(SUMMARY_COLUMNS), len(SUMMARY_HEADERS)))
# 每種牆型一欄接在這些固定欄之後（with_columns）。
SUMMARY_LAYOUT = sheet_layout.SheetLayout(
    SUMMARY_COLUMNS, first_data_row=FIRST_DATA_ROW, name=u'RC體積數量計算')
FIXED_REPORT_COLS = SUMMARY_LAYOUT.width
# Sheet 2 mirrors 牆面清單: A..G wall, I..M openings, O subtotal, Q..R volume,
# and the columns this report adds start at S.
DETAIL_FIRST_DATA_ROW = 3
# Zone/pour-area is a project parameter; these are candidates, not a schema.
ZONE_PARAM_NAMES = (u'澆置分區', u'分區', u'施工分區', u'棟別', u'Zone')
# Categories whose solids can occupy the same space as an un-joined RC wall.
OVERLAP_CATEGORIES = (
    ('OST_StructuralFraming', u'梁'),
    ('OST_StructuralColumns', u'結構柱'),
    ('OST_Columns', u'柱'),
    ('OST_Floors', u'樓板'),
)
# Same 1 ft search margin the unjoin tools use (domain/unjoin-geometry-workflow).
OVERLAP_SEARCH_MARGIN_FT = 1.0
# 0.5 litre: below this an "overlap" is two faces touching, not shared concrete.
OVERLAP_MIN_M3 = 0.0005

doc = revit.doc
output = script.get_output()

if doc is None:
    forms.alert(u'請先開啟 Revit 專案檔，再匯出 RC體積 Excel。', exitscript=True)


def clean(value):
    if value is None:
        return ''
    return String.Format('{0}', value).strip()


def element_id_value(element_id):
    try:
        return int(element_id.Value)
    except Exception:
        return int(element_id.IntegerValue)


def get_bip_param(element, bip_name):
    try:
        bip = getattr(BuiltInParameter, bip_name)
    except AttributeError:
        return None
    try:
        return element.get_Parameter(bip)
    except Exception:
        return None


def lookup_value(element, names):
    for name in names:
        try:
            param = element.LookupParameter(name)
        except Exception:
            param = None
        if param and param.HasValue:
            return clean(param.AsValueString() or param.AsString())
    return ''


def element_name(element):
    if element is None:
        return ''
    try:
        value = clean(Element.Name.GetValue(element))
        if value:
            return value
    except Exception:
        pass
    try:
        value = clean(element.Name)
        if value:
            return value
    except Exception:
        pass
    for bip_name in ('SYMBOL_NAME_PARAM', 'ALL_MODEL_TYPE_NAME', 'ROOM_NAME',
                     'DATUM_TEXT'):
        param = get_bip_param(element, bip_name)
        if param and param.HasValue:
            value = clean(param.AsString() or param.AsValueString())
            if value:
                return value
    return ''


def param_double_m(element, bip_names, lookup_names=None):
    lookup_names = lookup_names or []
    for bip_name in bip_names:
        param = get_bip_param(element, bip_name)
        if param and param.HasValue:
            try:
                return param.AsDouble() * FT_TO_M
            except Exception:
                pass
    for name in lookup_names:
        try:
            param = element.LookupParameter(name)
        except Exception:
            param = None
        if param and param.HasValue:
            try:
                return param.AsDouble() * FT_TO_M
            except Exception:
                number = logic.parse_number(
                    clean(param.AsValueString() or param.AsString()))
                if number is not None:
                    return number
    return None


def fixed(value, digits=2):
    return logic.format_number(value, digits)


def room_number(room):
    value = ''
    param = get_bip_param(room, 'ROOM_NUMBER')
    if param:
        value = clean(param.AsString() or param.AsValueString())
    if not value:
        value = lookup_value(room, ['編號', 'Number'])
    if value:
        return value.upper()
    match = re.search(r'((?:BS|FN|B|F|R)\d{2,4})\b', element_name(room), re.I)
    return match.group(1).upper() if match else ''


def room_name(room, number):
    value = ''
    param = get_bip_param(room, 'ROOM_NAME')
    if param:
        value = clean(param.AsString() or param.AsValueString())
    if not value:
        value = lookup_value(room, ['名稱', 'Name']) or element_name(room)
    if number:
        value = re.sub(r'\s*{0}\s*$'.format(re.escape(number)), '', value,
                       flags=re.I).strip()
    return value


def room_perimeter(room):
    param = get_bip_param(room, 'ROOM_PERIMETER')
    if param and param.HasValue:
        try:
            return fixed(param.AsDouble() * FT_TO_M)
        except Exception:
            pass
    value = logic.parse_number(lookup_value(room, ['周長', 'Perimeter']))
    return fixed(value) if value is not None else ''


def level_name(element):
    try:
        level = doc.GetElement(element.LevelId)
        if level:
            return element_name(level)
    except Exception:
        pass
    return lookup_value(element, ['樓層', '底部約束', 'Level'])


def base_constraint_name(wall):
    """The wall's Base Constraint level — what 牆面清單 calls 位置."""
    param = get_bip_param(wall, 'WALL_BASE_CONSTRAINT')
    if param and param.HasValue:
        try:
            level = doc.GetElement(param.AsElementId())
            if level is not None:
                return element_name(level)
        except Exception:
            pass
    return level_name(wall)


def build_room(room):
    number = room_number(room)
    element_id = element_id_value(room.Id)
    return {
        'id': element_id,
        # Rooms are keyed by number, but an unnumbered room still needs an
        # identity or its walls would all pile into one nameless group.
        'key': number or 'ID{0}'.format(element_id),
        'number': number,
        'name': room_name(room, number),
        'level': clean(level_name(room)),
        'perimeter': room_perimeter(room),
    }


def apply_room_clear_heights(rooms):
    """Attach the shared ceiling/floor/level height to each source Room."""
    if not rooms or scaffold_height is None:
        return {'updated': 0, 'error': 'shared height resolver unavailable'}
    try:
        resolved = scaffold_height.resolve_room_heights(
            doc, [room['id'] for room in rooms], detect_lower_floor=True)
    except Exception as error:
        return {'updated': 0, 'error': clean(error)}
    updated = 0
    for room in rooms:
        info = (resolved.get('rooms') or {}).get(str(room['id']))
        if not info or not info.get('height') or info['height'] <= 0:
            continue
        room['clear_height'] = info['height']
        room['clear_height_source'] = info.get('source') or ''
        room['clear_height_warnings'] = info.get('warnings') or []
        updated += 1
    return {'updated': updated, 'error': ''}


def collect_grids():
    """Straight grids as ``{name, point, direction}`` in metres.

    Arc grids are skipped rather than approximated: a curved grid has no single
    perpendicular offset, and a wrong location mark is worse than a blank one.
    """
    grids = []
    for grid in (FilteredElementCollector(doc).OfClass(Grid)
                 .WhereElementIsNotElementType()):
        try:
            curve = grid.Curve
        except Exception:
            continue
        if not isinstance(curve, Line):
            continue
        try:
            start = curve.GetEndPoint(0)
            end = curve.GetEndPoint(1)
        except Exception:
            continue
        grids.append({
            'name': element_name(grid),
            'point': (start.X * FT_TO_M, start.Y * FT_TO_M),
            'direction': ((end.X - start.X) * FT_TO_M,
                          (end.Y - start.Y) * FT_TO_M),
        })
    return grids


def wall_thickness_m(wall):
    try:
        width = float(wall.Width) * FT_TO_M
        if width > 0:
            return width
    except Exception:
        pass
    value = param_double_m(wall.WallType, ['WALL_ATTR_WIDTH_PARAM'], ['厚度'])
    return value if value and value > 0 else None


def wall_revit_volume_m3(wall):
    param = get_bip_param(wall, 'HOST_VOLUME_COMPUTED')
    if param and param.HasValue:
        try:
            return param.AsDouble() * CUFT_TO_CUM
        except Exception:
            pass
    return None


def wall_revit_area_m2(wall):
    param = get_bip_param(wall, 'HOST_AREA_COMPUTED')
    if param and param.HasValue:
        try:
            return param.AsDouble() * SQFT_TO_SQM
        except Exception:
            pass
    return None


def wall_bbox_height_m(wall):
    try:
        box = wall.get_BoundingBox(None)
    except Exception:
        box = None
    if box:
        height = (box.Max.Z - box.Min.Z) * FT_TO_M
        if height > 0:
            return height
    return None


def build_wall(wall, grids):
    loc = wall.Location
    if not isinstance(loc, LocationCurve):
        return None
    curve = loc.Curve
    start = curve.GetEndPoint(0)
    end = curve.GetEndPoint(1)
    length = curve.Length * FT_TO_M
    if not length or length <= 0:
        return None
    midpoint = ((start.X + end.X) / 2.0 * FT_TO_M,
                (start.Y + end.Y) / 2.0 * FT_TO_M)
    return {
        'element_id': element_id_value(wall.Id),
        'type_name': element_name(wall.WallType),
        'zone': lookup_value(wall, list(ZONE_PARAM_NAMES)),
        'base_constraint': base_constraint_name(wall),
        'level': clean(level_name(wall)),
        'location_mark': logic.location_mark(midpoint, grids),
        'room_number_param': lookup_value(wall, ['空間編號']),
        'length': length,
        'thickness': wall_thickness_m(wall),
        'revit_area': wall_revit_area_m2(wall),
        'revit_volume': wall_revit_volume_m3(wall),
        'bbox_height': wall_bbox_height_m(wall),
        'user_height': param_double_m(wall, ['WALL_USER_HEIGHT_PARAM'],
                                      ['不連續高度']),
        'start': (start.X, start.Y),
        'end': (end.X, end.Y),
        'openings': [],
        'height': None,
        'height_source': '',
        'room_assign': '',
        'overlap_deduct': 0.0,
        'overlap_detail': '',
        'join_state': '',
    }


def opening_name(opening):
    """``族群 - 類型``, the form 牆面清單 uses to name an opening."""
    type_name = ''
    family = ''
    try:
        symbol = opening.Symbol
        type_name = element_name(symbol)
        family = clean(symbol.Family.Name)
    except Exception:
        pass
    if not type_name:
        type_name = element_name(opening)
    if family and type_name and family != type_name:
        return u'{0} - {1}'.format(family, type_name)
    return type_name or family


def opening_dimensions(opening):
    """Sizes come from parameters first; the name is only a last resort.

    A family named ``門開口_220x240`` measured 2.24 x 2.53 m in this project —
    parsing the name would have under-deducted every one of them.
    """
    width_bips = ['DOOR_WIDTH', 'WINDOW_WIDTH', 'FAMILY_WIDTH_PARAM',
                  'FAMILY_ROUGH_WIDTH_PARAM', 'GENERIC_WIDTH']
    height_bips = ['DOOR_HEIGHT', 'WINDOW_HEIGHT', 'FAMILY_HEIGHT_PARAM',
                   'FAMILY_ROUGH_HEIGHT_PARAM', 'GENERIC_HEIGHT']
    width_names = ['寬度', '寬', '粗略寬度', 'Width']
    height_names = ['高度', '高', '粗略高度', 'Height']
    width = param_double_m(opening, width_bips, width_names)
    height = param_double_m(opening, height_bips, height_names)
    if not width or not height:
        symbol = getattr(opening, 'Symbol', None)
        if symbol:
            if not width:
                width = param_double_m(symbol, width_bips, width_names)
            if not height:
                height = param_double_m(symbol, height_bips, height_names)
    return (width, height)


def collect_wall_openings(wall_element, wall_data, warnings):
    """Deduct what Revit itself reports as inserted into this wall.

    Two rules are combined and both must hold: the element is in the wall's
    own ``FindInserts`` set (so it really cuts the concrete), and its Host is
    this wall. Proximity never deducts anything.

    Doors and windows are not enough here — this project also cuts RC with
    牆開口 and 通風格柵開口 generic-model families, and a category filter would
    leave those openings in the pour. Conversely, scanning every wall-hosted
    family would deduct non-cutting inserts such as fixtures, which FindInserts
    keeps out.
    """
    try:
        insert_ids = wall_element.FindInserts(True, True, True, True)
    except Exception:
        insert_ids = None
    if not insert_ids:
        return 0
    assigned = 0
    for insert_id in insert_ids:
        element = doc.GetElement(insert_id)
        if element is None:
            continue
        if not isinstance(element, FamilyInstance):
            # Wall-opening / shaft elements carry no width-height parameters;
            # deriving a size from their bounding box would silently invent a
            # deduction, so they are reported for a human instead.
            warnings.append(
                u'牆 {0} 有非族群開口元件 ElementId {1}（{2}），未自動扣除'.format(
                    wall_data['element_id'], element_id_value(element.Id),
                    element_name(element) or element.GetType().Name))
            continue
        try:
            host = element.Host
        except Exception:
            host = None
        if host is None or element_id_value(host.Id) != wall_data['element_id']:
            continue
        name = opening_name(element)
        width, height = opening_dimensions(element)
        if not width or not height or width <= 0 or height <= 0:
            warnings.append(u'{0}（ElementId {1}，宿主牆 {2}）尺寸讀不到，未扣除'
                            .format(name or u'(無名稱)',
                                    element_id_value(element.Id),
                                    wall_data['element_id']))
            continue
        wall_data['openings'].append({
            'id': element_id_value(element.Id),
            'name': name,
            'width': width,
            'height': height,
            # Where along the wall it sits, so a wall shared by several rooms
            # can hand each opening to the room it is actually cut into.
            'param': opening_param_on_wall(element, wall_data),
        })
        assigned += 1
    return assigned


def opening_param_on_wall(element, wall_data):
    """Distance in metres from the wall's start to the opening's centre."""
    point = None
    try:
        location = element.Location
        if location is not None and hasattr(location, 'Point'):
            point = (location.Point.X, location.Point.Y)
    except Exception:
        point = None
    if point is None:
        try:
            box = element.get_BoundingBox(None)
            if box is not None:
                point = ((box.Min.X + box.Max.X) / 2.0,
                         (box.Min.Y + box.Max.Y) / 2.0)
        except Exception:
            point = None
    if point is None:
        return None
    return logic.project_param(point, wall_data['start'],
                               wall_data['end']) * FT_TO_M


def geometry_options():
    options = Options()
    options.ComputeReferences = False
    options.IncludeNonVisibleObjects = False
    # Coarse returns a stick for structural framing; the solid only exists at
    # Fine, and this whole calculation is a solid intersection.
    options.DetailLevel = ViewDetailLevel.Fine
    return options


def _gather_solids(geometry, out):
    for item in geometry:
        if isinstance(item, Solid):
            try:
                if item.Volume > 0:
                    out.append(item)
            except Exception:
                pass
        elif isinstance(item, GeometryInstance):
            try:
                _gather_solids(item.GetInstanceGeometry(), out)
            except Exception:
                pass


def element_solids(element, cache=None):
    """Solids as Revit currently draws them — joins and cuts already applied."""
    key = None
    if cache is not None:
        key = element_id_value(element.Id)
        if key in cache:
            return cache[key]
    solids = []
    try:
        geometry = element.get_Geometry(geometry_options())
    except Exception:
        geometry = None
    if geometry is not None:
        _gather_solids(geometry, solids)
    if cache is not None:
        cache[key] = solids
    return solids


def intersection_volume_m3(wall_solids, other_solids):
    """``(m³, failures)`` shared by two elements' solids."""
    total = 0.0
    failures = 0
    for wall_solid in wall_solids:
        for other_solid in other_solids:
            try:
                result = BooleanOperationsUtils.ExecuteBooleanOperation(
                    wall_solid, other_solid, BooleanOperationsType.Intersect)
            except Exception:
                failures += 1
                continue
            if result is None:
                continue
            try:
                volume = float(result.Volume)
            except Exception:
                continue
            if volume > 0:
                total += volume * CUFT_TO_CUM
    return total, failures


def overlap_search_filter(wall_element):
    try:
        box = wall_element.get_BoundingBox(None)
    except Exception:
        box = None
    if box is None:
        return None
    margin = OVERLAP_SEARCH_MARGIN_FT
    try:
        outline = Outline(
            XYZ(box.Min.X - margin, box.Min.Y - margin, box.Min.Z - margin),
            XYZ(box.Max.X + margin, box.Max.Y + margin, box.Max.Z + margin))
        return BoundingBoxIntersectsFilter(outline)
    except Exception:
        return None


def collect_overlap_deduction(wall_element, wall_data, solid_cache, stats):
    """Remove concrete the wall only owns because nobody joined it.

    A joined pair is skipped outright rather than measured: Revit has already
    decided which element keeps the shared volume — if the beam won, the wall's
    solid (and therefore its 面積-derived height) is already short by that much,
    and if the wall won, the concrete really is the wall's. Measuring a joined
    pair would also be unreliable, because joining fuses the two solids
    (see domain/beam-penetration-algorithm.md).

    Un-joined is the case this exists for: the wall runs straight through the
    beam or slab, both elements report the full volume, and the same concrete
    gets paid for twice.
    """
    wall_solids = element_solids(wall_element)
    if not wall_solids:
        return
    search = overlap_search_filter(wall_element)
    if search is None:
        return
    details = []
    joined = 0
    for category_name, label in OVERLAP_CATEGORIES:
        category = getattr(BuiltInCategory, category_name, None)
        if category is None:
            continue
        try:
            candidates = (FilteredElementCollector(doc)
                          .OfCategory(category)
                          .WhereElementIsNotElementType()
                          .WherePasses(search)
                          .ToElements())
        except Exception:
            continue
        for other in candidates:
            other_id = element_id_value(other.Id)
            if other_id == wall_data['element_id']:
                continue
            try:
                if JoinGeometryUtils.AreElementsJoined(doc, wall_element,
                                                       other):
                    joined += 1
                    continue
            except Exception:
                pass
            volume, failures = intersection_volume_m3(
                wall_solids, element_solids(other, solid_cache))
            stats['overlap_failures'] += failures
            if volume < OVERLAP_MIN_M3:
                continue
            details.append({'label': label, 'id': other_id,
                            'volume': volume})
            stats['overlap_by_category'][label] = (
                stats['overlap_by_category'].get(label, 0.0) + volume)
    wall_data['overlap_deduct'] = sum(item['volume'] for item in details)
    wall_data['overlap_detail'] = logic.format_deduction_detail(details)
    wall_data['join_state'] = logic.format_join_state(joined, len(details))
    stats['joined_pairs'] += joined
    stats['deducted_pairs'] += len(details)


def resolve_wall_heights(walls):
    """Gross height per wall, preferring Revit's own face area.

    ``面積`` is net of openings and already reflects attached tops and sloped
    conditions, so adding the openings back and dividing by the length gives
    the height the model actually contains. Only when the area is unusable
    does this fall back to the unconnected height or the bounding box.
    """
    for wall in walls:
        length = wall.get('length')
        area = wall.get('revit_area')
        gross = None
        source = ''
        if area and area > 0 and length and length > 0:
            gross = (area + logic.opening_area(
                logic.group_openings(wall['openings']))) / length
            source = 'revit-area'
        if not gross or gross <= 0:
            gross = wall.get('user_height')
            source = 'unconnected-height' if gross else source
        if not gross or gross <= 0:
            gross = wall.get('bbox_height')
            source = 'bounding-box' if gross else source
        wall['height'] = gross
        wall['height_source'] = source or 'none'


def boundary_options():
    options = SpatialElementBoundaryOptions()
    try:
        options.SpatialElementBoundaryLocation = (
            SpatialElementBoundaryLocation.Finish)
    except Exception:
        pass
    return options


def collect_room_boundaries(rooms, walls_by_id):
    """``wall_id -> [{room_key, seg_length, span}]`` from the rooms themselves.

    Revit already knows which wall forms which room's boundary and over what
    stretch; a BoundingBox test does not. This project proves why: F102 is
    L-shaped and its bounding box completely swallows F103, so every wall
    bounding F103 also "touches" F102 and the nearest-centre tie-break sends it
    to the wrong room — taking the openings cut into it along for the ride.
    """
    entries = {}
    options = boundary_options()
    for room in rooms:
        element = doc.GetElement(ElementId(int(room['id'])))
        if element is None:
            continue
        try:
            loops = element.GetBoundarySegments(options)
        except Exception:
            loops = None
        if not loops:
            continue
        for loop in loops:
            for segment in loop:
                try:
                    wall_id = element_id_value(segment.ElementId)
                except Exception:
                    continue
                wall = walls_by_id.get(wall_id)
                if wall is None:
                    continue
                try:
                    curve = segment.GetCurve()
                    length = curve.Length * FT_TO_M
                    start = curve.GetEndPoint(0)
                    end = curve.GetEndPoint(1)
                except Exception:
                    continue
                if length <= 0:
                    continue
                span = (
                    logic.project_param((start.X, start.Y), wall['start'],
                                        wall['end']) * FT_TO_M,
                    logic.project_param((end.X, end.Y), wall['start'],
                                        wall['end']) * FT_TO_M,
                )
                entries.setdefault(wall_id, []).append({
                    'room_key': room['key'],
                    'room': room,
                    'seg_length': length,
                    'span': span,
                })
    return entries


def split_wall_across_rooms(wall, allocations):
    """One share dict per room, carrying that room's slice of this wall.

    The shares reuse the same keys a wall dict has, so every downstream step
    (type grouping, formulas, totals) treats a slice exactly like a wall.
    Openings and the beam/slab deduction travel with the slice they belong to,
    and the slices' lengths add back up to the wall — the concrete is divided,
    never duplicated.
    """
    shares = []
    by_key = {}
    for allocation in allocations:
        room = allocation.get('room') or {}
        share_height, share_height_source = (
            scaffold_height_logic.effective_wall_height(
                wall.get('height'), room.get('clear_height')))
        share = {
            'element_id': wall['element_id'],
            'type_name': wall['type_name'],
            'height': share_height,
            'height_source': share_height_source,
            'thickness': wall['thickness'],
            'length': allocation['length'],
            'share': allocation['share'],
            'room_key': allocation['room_key'],
            'openings': [],
            # The overlap is geometric and cannot be re-measured per slice, so
            # it rides along in proportion to the length each room took.
            'overlap_deduct': (wall.get('overlap_deduct') or 0.0) *
                              allocation['share'],
        }
        shares.append(share)
        by_key[allocation['room_key']] = share
    for opening in wall['openings']:
        allocation = logic.assign_opening_to_allocation(
            opening.get('param'), allocations)
        if allocation is None:
            continue
        target = by_key.get(allocation['room_key'])
        if target is not None:
            target['openings'].append(opening)
    return shares


def apply_consistent_wall_clear_height(wall, allocations):
    """Use one shared clear height in the whole-wall audit when possible."""
    candidates = []
    sources = []
    for allocation in allocations or []:
        room = allocation.get('room') or {}
        clear_height = room.get('clear_height')
        if not clear_height:
            continue
        height, source = scaffold_height_logic.effective_wall_height(
            wall.get('height'), clear_height)
        if height and height > 0:
            candidates.append(height)
            sources.append(source)
    if not candidates:
        return
    reference = candidates[0]
    if any(abs(value - reference) > 0.10 for value in candidates[1:]):
        # A wall genuinely touching rooms with different clear heights is
        # represented by the room shares; the whole-wall audit stays physical.
        return
    wall['height'] = reference
    wall['height_source'] = sources[0] or 'room-clear-height'


def collect_data(keywords, deduct_overlaps):
    rooms = []
    for room in (FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_Rooms)
                 .WhereElementIsNotElementType()):
        if not isinstance(room, SpatialElement):
            continue
        try:
            if room.Area <= 0:
                continue
        except Exception:
            pass
        data = build_room(room)
        if data['number'] or data['name']:
            rooms.append(data)
    rooms.sort(key=lambda r: logic.floor_sort_key(r['number']))
    height_result = apply_room_clear_heights(rooms)

    grids = collect_grids()
    rc_walls = []
    scanned = 0
    assigned_openings = 0
    opening_warnings = []
    solid_cache = {}
    overlap_stats = {
        'overlap_failures': 0,
        'overlap_by_category': {},
        'joined_pairs': 0,
        'deducted_pairs': 0,
    }
    for wall in (FilteredElementCollector(doc).OfClass(Wall)
                 .WhereElementIsNotElementType()):
        scanned += 1
        if not logic.matches_keywords(element_name(wall.WallType), keywords):
            continue
        data = build_wall(wall, grids)
        if data is None:
            continue
        assigned_openings += collect_wall_openings(wall, data,
                                                   opening_warnings)
        if deduct_overlaps:
            collect_overlap_deduction(wall, data, solid_cache, overlap_stats)
        rc_walls.append(data)

    resolve_wall_heights(rc_walls)

    walls_by_id = dict((wall['element_id'], wall) for wall in rc_walls)
    boundaries = collect_room_boundaries(rooms, walls_by_id)
    room_labels = dict(
        (room['key'], u'{0} {1}'.format(room['number'], room['name']).strip())
        for room in rooms)
    room_names = dict((room['key'], room['name']) for room in rooms)

    grouped_by_room = {}
    unassigned = []
    split_walls = 0
    for wall in rc_walls:
        allocations = logic.allocate_wall_to_rooms(
            wall['length'], boundaries.get(wall['element_id']) or [])
        wall['allocation_text'] = logic.format_room_allocation(
            allocations, room_labels)
        if not allocations:
            # No room claims this wall on its boundary. It still has to appear,
            # or the project total quietly loses it.
            wall['room_assign'] = 'none'
            wall['room_number'] = ''
            wall['room_name'] = logic.UNASSIGNED_ROOM_LABEL
            unassigned.append(dict(wall, share=1.0, room_key=''))
            continue
        apply_consistent_wall_clear_height(wall, allocations)
        wall['room_assign'] = ('boundary' if len(allocations) == 1
                               else 'boundary-split')
        if len(allocations) > 1:
            split_walls += 1
        wall['room_number'] = u'、'.join(
            allocation['room_key'] for allocation in allocations)
        wall['room_name'] = u'、'.join(
            room_names.get(allocation['room_key'], '')
            for allocation in allocations)
        for share in split_wall_across_rooms(wall, allocations):
            grouped_by_room.setdefault(share['room_key'], []).append(share)
    assign_sources = {}
    for wall in rc_walls:
        key = wall.get('room_assign') or 'none'
        assign_sources[key] = assign_sources.get(key, 0) + 1

    wall_type_cols = sorted(set(wall['type_name'] for wall in rc_walls),
                            key=logic.type_sort_key)

    missing_thickness = [wall for wall in rc_walls if not wall.get('thickness')]
    missing_height = [wall for wall in rc_walls if not wall.get('height')]
    height_sources = {}
    for wall in rc_walls:
        key = wall.get('height_source') or 'none'
        height_sources[key] = height_sources.get(key, 0) + 1

    stats = dict(overlap_stats)
    stats.update({
        'rooms': len(rooms),
        'scanned_walls': scanned,
        'rc_walls': len(rc_walls),
        'assigned_openings': assigned_openings,
        'opening_warnings': opening_warnings,
        'missing_thickness': missing_thickness,
        'missing_height': missing_height,
        'unassigned': unassigned,
        'assign_sources': assign_sources,
        'height_sources': height_sources,
        'clear_height_rooms': height_result.get('updated', 0),
        'clear_height_error': height_result.get('error', ''),
        'grids': len(grids),
        'revit_volume_total': sum(wall['revit_volume'] for wall in rc_walls
                                  if wall.get('revit_volume')),
        'overlap_total': sum(wall.get('overlap_deduct') or 0.0
                             for wall in rc_walls),
        'split_walls': split_walls,
        'deduct_overlaps': bool(deduct_overlaps),
    })
    # rc_walls is returned separately from grouped_by_room: sheet 1 groups the
    # per-room slices, sheet 2 lists the whole walls one row each.
    return rooms, grouped_by_room, unassigned, wall_type_cols, rc_walls, stats


# --- sheet 1: room summary -------------------------------------------------

def group_walls_by_type(walls):
    groups = {}
    order = []
    for wall in walls:
        key = logic.wall_group_key(wall['type_name'], wall['height'],
                                   wall['thickness'])
        if key not in groups:
            groups[key] = {
                'type_name': wall['type_name'],
                'height': wall['height'],
                'thickness': wall['thickness'],
                'walls': [],
                'openings': [],
            }
            order.append(key)
        groups[key]['walls'].append(wall)
        groups[key]['openings'].extend(wall['openings'])
    result = [groups[key] for key in order]
    result.sort(key=lambda g: (logic.type_sort_key(g['type_name']),
                               g['height'] or 0))
    return result


def make_summary_rows(rooms, grouped_by_room, unassigned, wall_type_cols):
    rows = []
    full = SUMMARY_LAYOUT.with_columns(wall_type_cols)

    entries = [(room, grouped_by_room.get(room['key'], []))
               for room in rooms]
    if unassigned:
        entries.append(({
            'number': '',
            'name': logic.UNASSIGNED_ROOM_LABEL,
            'perimeter': '',
        }, unassigned))

    for room, walls in entries:
        if not walls:
            rows.append(full.row_from({
                'room_no': room['number'],
                'room_name': room['name'],
                'room_perimeter': room['perimeter'],
            }))
            continue

        for group in group_walls_by_type(walls):
            openings = logic.group_openings(group['openings'])
            lengths = [fixed(wall['length']) for wall in group['walls']
                       if wall.get('length')]
            row_count = max(1, len(openings))
            for i in range(row_count):
                row = full.blank_row()
                if i == 0:
                    full.put(row, 'room_no', room['number'])
                    full.put(row, 'room_name', room['name'])
                    full.put(row, 'room_perimeter', room['perimeter'])
                    full.put(row, 'wall_type', group['type_name'])
                    full.put(row, 'length',
                             '=' + '+'.join(lengths) if lengths else '')
                    full.put(row, 'height', fixed(group['height']))
                    full.put(row, 'thickness', fixed(group['thickness'], 3))
                    full.put(row, 'area', 'AREA_FORMULA')
                    full.put(row, 'area_subtotal', 'AREA_SUBTOTAL_FORMULA')
                    full.put(row, 'net_area', 'NET_AREA_FORMULA')
                    full.put(row, 'gross_volume', 'VOLUME_FORMULA')
                    full.put(row, 'overlap_deduct',
                             fixed(sum(wall.get('overlap_deduct') or 0.0
                                       for wall in group['walls']), 3))
                    full.put(row, 'net_volume', 'NET_VOLUME_FORMULA')
                    if full.has(group['type_name']):
                        full.put(row, group['type_name'], 'TYPE_FORMULA')

                if i < len(openings):
                    opening = openings[i]
                    full.put(row, 'opening_name', opening['name'])
                    full.put(row, 'opening_count', opening['count'])
                    full.put(row, 'opening_width', fixed(opening['width']))
                    full.put(row, 'opening_height', fixed(opening['height']))
                    full.put(row, 'opening_area', 'OPENING_AREA_FORMULA')
                    full.put(row, 'opening_subtotal',
                             'OPENING_SUBTOTAL_FORMULA')

                rows.append(row)

    return fill_summary_formulas(rows, wall_type_cols)


def fill_summary_formulas(rows, wall_type_cols):
    """把佔位字串換成真正的公式。

    公式一律用欄位名稱寫，字母由 SUMMARY_LAYOUT 產生——這裡以前是全檔案手寫欄位
    字母最密集的地方，也是欄位一搬動就會安靜指錯的地方。
    """
    layout = SUMMARY_LAYOUT
    full = layout.with_columns(wall_type_cols)
    for i, row in enumerate(rows):
        r = FIRST_DATA_ROW + i
        if layout.get(row, 'area') == 'AREA_FORMULA':
            layout.put(row, 'area', layout.formula(r, '{length}*{height}'))
        if layout.get(row, 'area_subtotal') == 'AREA_SUBTOTAL_FORMULA':
            layout.put(row, 'area_subtotal', layout.formula(r, '{area}'))
        if layout.get(row, 'opening_area') == 'OPENING_AREA_FORMULA':
            layout.put(row, 'opening_area', layout.formula(
                r, '{opening_count}*{opening_width}*{opening_height}'))
        if layout.get(row, 'opening_subtotal') == 'OPENING_SUBTOTAL_FORMULA':
            layout.put(row, 'opening_subtotal',
                       layout.formula(r, '{opening_area}'))
        if layout.get(row, 'net_area') == 'NET_AREA_FORMULA':
            deductions = []
            if layout.get(row, 'opening_subtotal'):
                deductions.append(layout.cell('opening_subtotal', r))
            look = 1
            # Continuation rows carry only openings: no wall type of their own.
            while (i + look < len(rows)
                   and not layout.get(rows[i + look], 'wall_type')
                   and layout.get(rows[i + look], 'opening_subtotal')):
                deductions.append(layout.cell('opening_subtotal', r + look))
                look += 1
            net_area = layout.expr(r, '{area_subtotal}')
            if deductions:
                net_area += '-' + '-'.join(deductions)
            layout.put(row, 'net_area', '=' + net_area)
        if layout.get(row, 'gross_volume') == 'VOLUME_FORMULA':
            layout.put(row, 'gross_volume',
                       layout.formula(r, '{net_area}*{thickness}'))
        if layout.get(row, 'net_volume') == 'NET_VOLUME_FORMULA':
            layout.put(row, 'net_volume',
                       layout.formula(r, '{gross_volume}-{overlap_deduct}'))
        wall_type = layout.get(row, 'wall_type')
        if wall_type in wall_type_cols:
            if full.get(row, wall_type) == 'TYPE_FORMULA':
                full.put(row, wall_type, layout.formula(r, '{net_volume}'))
    return rows


def build_summary_values(rows, wall_type_cols, project_title, keywords,
                         deduct_overlaps):
    total_cols = FIXED_REPORT_COLS + len(wall_type_cols)
    blank_tail = [''] * (total_cols - 1)
    values = []
    values.append([project_title] + blank_tail)
    values.append([u'RC 牆體積數量計算表'] + blank_tail)
    values.append([
        u'依房間別（淨體積＝(牆長 × 牆高 − 開口面積) × 厚度 − 樑柱板重疊；'
        u'牆高取 Revit 牆面積回推的毛高；類型篩選關鍵字：{0}；'
        u'樑柱板重疊{1}；'
        u'跨房間的牆依各房間邊界長度比例分攤，同一支牆只計一次；'
        u'本表顯示兩位小數，逐面全精度明細見「牆面清單」分頁）'.format(
            u'、'.join(keywords),
            u'已扣除未接合的重疊（已接合者 Revit 已自行切割，不重複扣）'
            if deduct_overlaps else u'**未計算**（本次略過，未接合處會多算）')
    ] + blank_tail)

    full = SUMMARY_LAYOUT.with_columns(wall_type_cols)
    section = full.row_from({
        'room_no': u'樓別名稱',
        'room_perimeter': u'RC 牆',
        'opening_name': u'門開口、窗開口、牆開口',
    })
    if wall_type_cols:
        full.put(section, wall_type_cols[0], u'RC 牆淨體積 (m³)')
    values.append(section)

    values.append(list(SUMMARY_HEADERS) + wall_type_cols)
    values.extend(rows)
    values.append(build_summary_total_row(len(rows), wall_type_cols))
    return values


def summary_total_volume(rooms, grouped_by_room, unassigned):
    """The same arithmetic the sheet performs, for the run report.

    It reuses the rounded values written into the cells, so the number printed
    in pyRevit is the number Excel will show — a total computed at full
    precision would disagree with the workbook and start an argument about
    which one is right.
    """
    total = 0.0
    walls_by_room = [grouped_by_room.get(room['key'], []) for room in rooms]
    walls_by_room.append(unassigned)
    for walls in walls_by_room:
        for group in group_walls_by_type(walls):
            length = sum(logic.parse_number(fixed(wall['length'])) or 0
                         for wall in group['walls'] if wall.get('length'))
            height = logic.parse_number(fixed(group['height'])) or 0
            thickness = logic.parse_number(fixed(group['thickness'], 3)) or 0
            openings = logic.group_openings(group['openings'])
            deduct = sum(item['count'] *
                         (logic.parse_number(fixed(item['width'])) or 0) *
                         (logic.parse_number(fixed(item['height'])) or 0)
                         for item in openings)
            overlap = logic.parse_number(fixed(
                sum(wall.get('overlap_deduct') or 0.0
                    for wall in group['walls']), 3)) or 0
            total += logic.net_volume(
                logic.wall_volume(length, height, thickness, deduct), overlap)
    return total


def build_summary_total_row(data_row_count, wall_type_cols):
    full = SUMMARY_LAYOUT.with_columns(wall_type_cols)
    row = full.row_from({'room_no': SUMMARY_LABEL})
    last_data_row = FIRST_DATA_ROW + data_row_count - 1
    for type_name in wall_type_cols:
        # 每一欄加的是自己那一欄。以前這裡是 excel_col(FIXED + index + 1)，
        # 一個 +1 就會讓總計加到隔壁去，而且不會報錯。
        full.put(row, type_name,
                 full.sum_of(type_name, FIRST_DATA_ROW, last_data_row)
                 if data_row_count > 0 else '=0')
    return row


# --- sheet 2: per-wall audit list ------------------------------------------

DETAIL_HEADERS = [
    u'牆面ID', u'牆面類型', u'位置標記', u'澆置分區', u'長 (m)', u'高 (m)',
    u'厚度 (m)', '',
    u'名稱', u'數量', u'寬 (m)', u'高 (m)', u'面積小計 (m²)', '',
    u'開口合計面積 (m²)', '',
    u'合計計算式', u'總計體積 (m³)',
    u'房號', u'空間名稱', u'歸屬方式', u'基準約束', u'高度來源',
    u'樑柱板扣除 (m³)', u'淨體積 (m³)', u'扣除明細', u'接合狀態',
    u'Revit 體積 (m³)', u'差異 (m³)', u'房間分攤',
]
# 與 DETAIL_HEADERS 一一對應的內部名稱；公式只用這些名字，不寫欄位字母。
DETAIL_COLUMNS = [
    'wall_id', 'wall_type', 'location_mark', 'zone', 'length', 'height',
    'thickness', 'gap_after_wall',
    'opening_name', 'opening_count', 'opening_width', 'opening_height',
    'opening_area', 'gap_after_opening',
    'opening_total', 'gap_after_opening_total',
    'volume_expr', 'gross_volume',
    'room_no', 'room_name', 'room_assign', 'base_constraint', 'height_source',
    'overlap_deduct', 'net_volume', 'overlap_detail', 'join_state',
    'revit_volume', 'revit_diff', 'allocation',
]
if len(DETAIL_COLUMNS) != len(DETAIL_HEADERS):
    raise AssertionError(
        u'DETAIL_COLUMNS 與 DETAIL_HEADERS 長度不一致（{0} vs {1}）：'
        u'加欄位時兩邊都要加'.format(
            len(DETAIL_COLUMNS), len(DETAIL_HEADERS)))
DETAIL_LAYOUT = sheet_layout.SheetLayout(
    DETAIL_COLUMNS, first_data_row=DETAIL_FIRST_DATA_ROW, name=u'牆面清單')
DETAIL_COLS = DETAIL_LAYOUT.width


def build_detail_values(walls):
    layout = DETAIL_LAYOUT
    values = []
    banner = layout.row_from({
        'wall_id': u'[牆面面積]',
        'opening_name': u'[開口]',
        'opening_total': u'[開口合計]',
        'volume_expr': u'[牆面體積]',
        'overlap_deduct': u'[未接合的樑柱板重疊]',
    })
    values.append(banner)
    values.append(list(DETAIL_HEADERS))

    row_index = DETAIL_FIRST_DATA_ROW
    for wall in walls:
        openings = logic.group_openings(wall.get('openings'))
        span = max(1, len(openings))
        first_row = row_index
        last_row = row_index + span - 1
        for i in range(span):
            r = row_index + i
            row = layout.blank_row()
            if i == 0:
                # Every field is read with .get(): this sheet is the last step
                # of the export, and a missing key here would throw away the
                # whole run.
                layout.put(row, 'wall_id', wall.get('element_id', ''))
                layout.put(row, 'wall_type', wall.get('type_name', ''))
                layout.put(row, 'location_mark',
                           wall.get('location_mark', ''))
                layout.put(row, 'zone', wall.get('zone', ''))
                layout.put(row, 'length', fixed(wall.get('length'), 3))
                layout.put(row, 'height', fixed(wall.get('height'), 3))
                layout.put(row, 'thickness', fixed(wall.get('thickness'), 3))
                layout.put(row, 'opening_total',
                           '=SUM({0})'.format(
                               layout.rng('opening_area', first_row,
                                          last_row)))
                # The audit expression is a live formula, so it can never drift
                # from the numbers in the row it is supposed to explain.
                layout.put(row, 'volume_expr', layout.formula(
                    r,
                    '"("&{length}&"*"&{height}&"-"&{opening_total}&")*"'
                    '&{thickness}&"="&{gross_volume}'))
                layout.put(row, 'gross_volume', layout.formula(
                    r,
                    '({length}*{height}-{opening_total})*{thickness}'))
                layout.put(row, 'room_no', wall.get('room_number', ''))
                layout.put(row, 'room_name', wall.get('room_name', ''))
                layout.put(row, 'room_assign', wall.get('room_assign', ''))
                layout.put(row, 'base_constraint',
                           wall.get('base_constraint', ''))
                layout.put(row, 'height_source',
                           wall.get('height_source', ''))
                layout.put(row, 'overlap_deduct',
                           fixed(wall.get('overlap_deduct') or 0.0, 3))
                layout.put(row, 'net_volume', layout.formula(
                    r, '{gross_volume}-{overlap_deduct}'))
                layout.put(row, 'overlap_detail',
                           wall.get('overlap_detail', ''))
                layout.put(row, 'join_state', wall.get('join_state', ''))
                layout.put(row, 'allocation', wall.get('allocation_text', ''))
                if wall.get('revit_volume') is not None:
                    layout.put(row, 'revit_volume',
                               fixed(wall['revit_volume'], 3))
                    # Revit's own volume is already net of joins and openings,
                    # so it is the closest independent check on the net figure.
                    layout.put(row, 'revit_diff', layout.formula(
                        r, '{revit_volume}-{net_volume}'))
            if i < len(openings):
                opening = openings[i]
                layout.put(row, 'opening_name', opening['name'])
                layout.put(row, 'opening_count', opening['count'])
                layout.put(row, 'opening_width', fixed(opening['width'], 3))
                layout.put(row, 'opening_height', fixed(opening['height'], 3))
                layout.put(row, 'opening_area', layout.formula(
                    r,
                    '{opening_width}*{opening_height}*{opening_count}'))
            elif i == 0:
                layout.put(row, 'opening_name', logic.NO_OPENING_LABEL)
            values.append(row)
        row_index += span

    total = layout.row_from({'volume_expr': SUMMARY_LABEL})
    totalled = ('gross_volume', 'overlap_deduct', 'net_volume')
    if row_index > DETAIL_FIRST_DATA_ROW:
        last = row_index - 1
        for key in totalled:
            layout.put(total, key,
                       layout.sum_of(key, DETAIL_FIRST_DATA_ROW, last))
    else:
        for key in totalled:
            layout.put(total, key, '=0')
    values.append(total)
    return values


# --- xlsx writer -----------------------------------------------------------

def xml_escape(value):
    text = clean(value)
    return (
        text.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )


def is_number(value):
    if isinstance(value, (int, float)):
        return True
    text = clean(value)
    if not text:
        return False
    try:
        float(text)
        return True
    except Exception:
        return False


def cell_xml(row_index, col_index, value, summary_row_index, freeze_rows):
    ref = '{0}{1}'.format(logic.excel_col(col_index), row_index)
    text = clean(value)
    if summary_row_index and row_index == summary_row_index:
        style = ' s="2"'
    elif freeze_rows >= 5:
        style = takeoff_excel_styles.style_attr(
            takeoff_excel_styles.row_style_id(
                row_index, summary_row_index, header_row_count=freeze_rows))
    elif row_index <= freeze_rows:
        style = ' s="1"'
    else:
        style = ''
    if value is None or value == '':
        return '<c r="{0}"{1}/>'.format(ref, style)
    if text.startswith('='):
        return '<c r="{0}"{1}><f>{2}</f></c>'.format(ref, style,
                                                     xml_escape(text[1:]))
    if is_number(value):
        return '<c r="{0}"{1}><v>{2}</v></c>'.format(ref, style, clean(value))
    return '<c r="{0}"{1} t="inlineStr"><is><t>{2}</t></is></c>'.format(
        ref, style, xml_escape(text))


def sheet_xml(values, freeze_rows, cols_xml, merges=None):
    rows_xml = []
    summary_row_index = None
    for row_index, row in enumerate(values, start=1):
        if SUMMARY_LABEL in row:
            summary_row_index = row_index
            break
    for row_index, row in enumerate(values, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            cell = cell_xml(row_index, col_index, value,
                            summary_row_index, freeze_rows)
            if cell:
                cells.append(cell)
        rows_xml.append('<row r="{0}">{1}</row>'.format(row_index,
                                                        ''.join(cells)))
    merge_xml = ''
    refs = list(merges or [])
    if refs:
        merge_xml = '<mergeCells count="{0}">{1}</mergeCells>'.format(
            len(refs),
            ''.join('<mergeCell ref="{0}"/>'.format(ref) for ref in refs))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="{0}" topLeftCell="A{1}" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        '<cols>{2}</cols><sheetData>{3}</sheetData>{4}'
        '</worksheet>'
    ).format(freeze_rows, freeze_rows + 1, cols_xml, ''.join(rows_xml),
             merge_xml)


SUMMARY_COLS_XML = ''.join([
    '<col min="1" max="1" width="10" customWidth="1"/>',
    '<col min="2" max="2" width="18" customWidth="1"/>',
    '<col min="3" max="3" width="12" customWidth="1"/>',
    '<col min="4" max="4" width="26" customWidth="1"/>',
    '<col min="5" max="9" width="10" customWidth="1"/>',
    '<col min="10" max="10" width="30" customWidth="1"/>',
    '<col min="11" max="19" width="13" customWidth="1"/>',
    '<col min="20" max="50" width="18" customWidth="1"/>',
])

DETAIL_COLS_XML = ''.join([
    '<col min="1" max="1" width="12" customWidth="1"/>',
    '<col min="2" max="2" width="24" customWidth="1"/>',
    '<col min="3" max="3" width="18" customWidth="1"/>',
    '<col min="4" max="4" width="12" customWidth="1"/>',
    '<col min="5" max="8" width="10" customWidth="1"/>',
    '<col min="9" max="9" width="34" customWidth="1"/>',
    '<col min="10" max="16" width="12" customWidth="1"/>',
    '<col min="17" max="17" width="42" customWidth="1"/>',
    '<col min="18" max="25" width="14" customWidth="1"/>',
    '<col min="26" max="26" width="40" customWidth="1"/>',
    '<col min="27" max="29" width="14" customWidth="1"/>',
    '<col min="30" max="30" width="40" customWidth="1"/>',
])


def write_zip_entry(archive, name, content):
    entry = archive.CreateEntry(name)
    stream = entry.Open()
    writer = StreamWriter(stream, Encoding.UTF8)
    writer.Write(content)
    writer.Close()
    stream.Close()


def write_xlsx(path, sheets):
    """Minimal two-sheet OpenXML writer; no Excel COM, no external package."""
    fs = FileStream(path, FileMode.Create, FileAccess.ReadWrite)
    archive = ZipArchive(fs, ZipArchiveMode.Create)
    try:
        overrides = ''.join(
            '<Override PartName="/xl/worksheets/sheet{0}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.worksheet+xml"/>'.format(index + 1)
            for index in range(len(sheets)))
        write_zip_entry(
            archive, '[Content_Types].xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + overrides +
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '</Types>')
        write_zip_entry(
            archive, '_rels/.rels',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>')
        sheet_rels = ''.join(
            '<Relationship Id="rId{0}" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet{0}.xml"/>'.format(index + 1)
            for index in range(len(sheets)))
        write_zip_entry(
            archive, 'xl/_rels/workbook.xml.rels',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + sheet_rels +
            '<Relationship Id="rId{0}" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            .format(len(sheets) + 1) +
            '</Relationships>')
        sheet_tags = ''.join(
            '<sheet name="{0}" sheetId="{1}" r:id="rId{1}"/>'.format(
                xml_escape(name), index + 1)
            for index, (name, _values, _freeze, _cols, _merges)
            in enumerate(sheets))
        write_zip_entry(
            archive, 'xl/workbook.xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets>' + sheet_tags + '</sheets>'
            '<calcPr calcMode="auto" fullCalcOnLoad="1"/></workbook>')
        write_zip_entry(
            archive, 'xl/styles.xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + takeoff_excel_styles.FONTS_XML
            + takeoff_excel_styles.FILLS_XML
            + takeoff_excel_styles.BORDERS_XML
            + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="5">'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/>'
            '</xf>'
            '<xf numFmtId="0" fontId="4" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/>'
            '</xf>'
            '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center" wrapText="1"/>'
            '</xf>'
            '<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center" wrapText="1"/>'
            '</xf>'
            '</cellXfs>'
            '</styleSheet>')
        for index, (_name, values, freeze, cols_xml, merges) in \
                enumerate(sheets):
            write_zip_entry(archive, 'xl/worksheets/sheet{0}.xml'.format(
                index + 1), sheet_xml(values, freeze, cols_xml, merges))
    finally:
        archive.Dispose()
        fs.Close()


def build_workbook(rooms, grouped_by_room, unassigned, wall_type_cols,
                   rc_walls, project_title, keywords, deduct_overlaps):
    """Both sheets, assembled from the two different views of the same walls.

    Sheet 1 consumes the per-room slices in ``grouped_by_room``; sheet 2
    consumes the whole walls in ``rc_walls``, one row each. Keeping the
    assembly here (rather than inline in ``main``) is what lets the offline
    harness exercise the real wiring — feeding sheet 2 the slices instead of
    the walls is exactly the mistake that shipped once.
    """
    summary_rows = make_summary_rows(rooms, grouped_by_room, unassigned,
                                     wall_type_cols)
    summary_values = build_summary_values(summary_rows, wall_type_cols,
                                          project_title, keywords,
                                          deduct_overlaps)

    # One row per physical wall, ordered by the first room that claims it, so
    # the audit sheet reads alongside sheet 1 without duplicating a split wall.
    room_order = dict((room['key'], index)
                      for index, room in enumerate(rooms))
    unplaced = len(rooms)

    def wall_order(wall):
        keys = [key for key in (wall.get('room_number') or '').split(u'、')
                if key]
        positions = [room_order.get(key, unplaced) for key in keys] or [unplaced]
        return (min(positions), wall.get('element_id') or 0)

    detail_values = build_detail_values(sorted(rc_walls, key=wall_order))

    # 總計列把固定欄整段併成一格：從第一欄併到最後一個固定欄（淨體積）。
    summary_merge = ['{0}{2}:{1}{2}'.format(
        SUMMARY_LAYOUT.col(SUMMARY_COLUMNS[0]),
        SUMMARY_LAYOUT.col(SUMMARY_COLUMNS[-1]),
        len(summary_values))]
    # 第 1 列的四個 banner 各自橫跨自己那一組欄位（見 build_detail_values）
    detail_merge = ['{0}1:{1}1'.format(DETAIL_LAYOUT.col(first),
                                       DETAIL_LAYOUT.col(last))
                    for first, last in (('wall_id', 'thickness'),
                                        ('opening_name', 'opening_area'),
                                        ('volume_expr', 'gross_volume'),
                                        ('overlap_deduct', 'join_state'))]
    return [
        (u'RC體積數量計算', summary_values, 5, SUMMARY_COLS_XML, summary_merge),
        (u'牆面清單', detail_values, 2, DETAIL_COLS_XML, detail_merge),
    ]


def safe_filename(text):
    value = re.sub(r'[\\/:*?"<>|]+', '_', clean(text))
    return value or 'Revit'


def revit_file_title():
    path_name = clean(getattr(doc, 'PathName', ''))
    if path_name:
        title = os.path.splitext(os.path.basename(path_name))[0]
        if title:
            return title
    title = clean(getattr(doc, 'Title', ''))
    if title.lower().endswith('.rvt'):
        title = os.path.splitext(title)[0]
    return title or 'Revit'


def ask_keywords():
    """The type filter is asked for, not hardcoded; the default is a fallback."""
    answer = forms.ask_for_string(
        default=u'、'.join(logic.DEFAULT_KEYWORDS),
        prompt=u'只計算「牆類型名稱」含這些關鍵字的牆（以逗號或空白分隔）。\n'
               u'英數關鍵字需落在字詞邊界上，所以 RC 不會誤中 ARCH / SRC。',
        title=TITLE)
    if answer is None:
        return None
    keywords = logic.parse_keywords(answer)
    if not keywords:
        forms.alert(u'沒有輸入任何關鍵字，已取消。', title=TITLE)
        return None
    return keywords


def ask_deduct_overlaps():
    """Un-joined beams/slabs overlap the wall; ask before the slow scan."""
    return bool(forms.alert(
        u'要扣除樑／柱／樓板與 RC 牆重疊的體積嗎？\n\n'
        u'· 已接合（Join）的部分 Revit 已自行切割，不會重複扣。\n'
        u'· 未接合而牆直接穿過樑或樓板時，同一塊混凝土會被算兩次，'
        u'選「是」才會扣掉。\n'
        u'· 需要逐面做實體布林運算，模型大時較慢。\n\n'
        u'選「否」則只算 牆長×牆高×厚度 − 開口。',
        title=TITLE, yes=True, no=True, ok=False))


def report(stats, wall_type_cols, outpath, total_volume):
    output.print_md(u'## RC體積 Excel 匯出完成')
    output.print_md(u'- 檔案：`{0}`'.format(outpath))
    output.print_md(u'- Rooms：{0}　Grids：{1}'.format(stats['rooms'],
                                                      stats['grids']))
    output.print_md(u'- 掃描牆 {0} 面，命中 RC 牆 {1} 面，類型 {2} 種'.format(
        stats['scanned_walls'], stats['rc_walls'], len(wall_type_cols)))
    output.print_md(u'- **本表體積合計：{0} m³**'.format(fixed(total_volume, 3)))
    revit_total = stats.get('revit_volume_total')
    if revit_total:
        difference = total_volume - revit_total
        output.print_md(
            u'- Revit 原生體積合計：{0} m³（差 {1} m³，{2}%）；'
            u'Revit 值已扣除開口與接合，僅供對照'.format(
                fixed(revit_total, 3), fixed(difference, 3),
                fixed(difference / revit_total * 100.0, 1)))
    output.print_md(u'- 已扣除的宿主開口：{0}'.format(stats['assigned_openings']))
    if stats.get('deduct_overlaps'):
        output.print_md(
            u'- 樑柱板重疊：已接合 {0} 對（Revit 已自行切割，未重複扣）／'
            u'未接合 {1} 對，扣除 {2} m³'.format(
                stats['joined_pairs'], stats['deducted_pairs'],
                fixed(stats['overlap_total'], 3)))
        for label, volume in sorted(stats['overlap_by_category'].items()):
            output.print_md(u'  - {0}：{1} m³'.format(label,
                                                      fixed(volume, 3)))
        if stats['deducted_pairs']:
            output.print_md(
                u'  - 未接合代表模型裡這些樑柱板與牆是重疊的實體；'
                u'圖面上建議仍回頭把它們接合，本表只是先把重複的量扣掉。')
        if stats['overlap_failures']:
            output.print_md(u'  - **布林運算失敗 {0} 次**，該部分未扣除'.format(
                stats['overlap_failures']))
    else:
        output.print_md(u'- 樑柱板重疊：**本次未計算**，未接合處的體積會多算')
    output.print_md(u'- 房間歸屬（依 Room 邊界，非 BoundingBox）：')
    for source, count in sorted(stats['assign_sources'].items()):
        output.print_md(u'  - `{0}`：{1} 面'.format(source, count))
    if stats.get('split_walls'):
        output.print_md(
            u'  - 其中 {0} 面牆跨多個房間，已依各房間邊界長度比例分攤；'
            u'同一支牆只計一次，逐面分攤結果見「牆面清單」分頁最後一欄。'
            .format(stats['split_walls']))
    for source, count in sorted(stats['height_sources'].items()):
        output.print_md(u'  - 牆高來源 `{0}`：{1}'.format(source, count))
    if stats['unassigned']:
        output.print_md(u'- **未分配到房間**：{0} 面（已列在最後一組，不會漏算）'
                        .format(len(stats['unassigned'])))
    if stats['missing_thickness']:
        output.print_md(u'- **缺厚度**：{0} 面，體積無法計算'.format(
            len(stats['missing_thickness'])))
    if stats['missing_height']:
        output.print_md(u'- **缺牆高**：{0} 面，體積無法計算'.format(
            len(stats['missing_height'])))
    if stats['opening_warnings']:
        output.print_md(u'- **開口未扣除**：{0} 筆，需人工確認'.format(
            len(stats['opening_warnings'])))
        for item in stats['opening_warnings'][:20]:
            output.print_md(u'  - {0}'.format(item))


def main():
    keywords = ask_keywords()
    if not keywords:
        return
    deduct_overlaps = ask_deduct_overlaps()

    project_title = revit_file_title()
    outpath = forms.save_file(
        file_ext='xlsx',
        default_name=safe_filename(project_title) + u'_RC體積數量計算.xlsx',
        title=u'匯出 RC 體積數量計算 Excel')
    if not outpath:
        return
    if not outpath.lower().endswith('.xlsx'):
        outpath += '.xlsx'

    rooms, grouped_by_room, unassigned, wall_type_cols, rc_walls, stats = \
        collect_data(keywords, deduct_overlaps)
    if not stats['rc_walls']:
        forms.alert(
            u'找不到任何牆類型名稱含「{0}」的牆，未匯出。'.format(
                u'、'.join(keywords)), title=TITLE)
        return

    write_xlsx(outpath, build_workbook(
        rooms, grouped_by_room, unassigned, wall_type_cols, rc_walls,
        project_title, keywords, deduct_overlaps))

    total_volume = summary_total_volume(rooms, grouped_by_room, unassigned)
    report(stats, wall_type_cols, outpath, total_volume)
    forms.alert(u'RC體積 Excel 匯出完成。\nRC 牆 {0} 面，體積合計 {1} m³。\n\n{2}'
                .format(stats['rc_walls'], fixed(total_volume, 3), outpath),
                title=TITLE)


main()
