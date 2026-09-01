# -*- coding: utf-8 -*-
from __future__ import unicode_literals

__title__ = u'天花\nExcel'
__author__ = 'Codex'

import math
import os
import re

import clr

clr.AddReference('System.IO.Compression')
clr.AddReference('System.IO.Compression.FileSystem')

from Autodesk.Revit.DB import (  # noqa: E402
    BooleanOperationsType,
    BooleanOperationsUtils,
    BuiltInCategory,
    BuiltInParameter,
    CurveLoop,
    Element,
    FamilySymbol,
    FilledRegion,
    FilteredElementCollector,
    GeometryCreationUtilities,
    GeometryInstance,
    IndependentTag,
    Level,
    Options,
    Solid,
    SpatialElement,
    SpatialElementBoundaryLocation,
    SpatialElementBoundaryOptions,
    UV,
    ViewSheet,
    XYZ,
)
from System import String  # noqa: E402
from System.Collections.Generic import List  # noqa: E402
from System.IO import FileAccess, FileMode, FileStream, StreamWriter  # noqa: E402
from System.IO.Compression import ZipArchive, ZipArchiveMode  # noqa: E402
from System.Text import Encoding  # noqa: E402

from pyrevit import forms, revit, script  # noqa: E402

import sheet_layout  # noqa: E402
import takeoff_direct_publish  # noqa: E402
import takeoff_excel_styles  # noqa: E402
import takeoff_entry  # noqa: E402
import room_takeoff_sources_logic  # noqa: E402

try:
    reload(takeoff_direct_publish)
except Exception:
    pass


FT_TO_M = 0.3048
SQFT_TO_SQM = FT_TO_M * FT_TO_M
HEIGHT_BUCKET_SIZE_M = 0.05
CEILING_SAMPLE_GRID = 5
MIN_VALID_HEIGHT_M = 0.50
MAX_VALID_HEIGHT_M = 30.0
CEILING_ABOVE_SLAB_TOLERANCE_M = 0.15
CEILING_SAMPLE_BELOW_M = 0.05
AREA_DIFF_WARN_TOLERANCE_M2 = 0.05
CEILING_NOTE_AREA_TOLERANCE_M2 = 2.0
CEILING_NOTE_AREA_TOLERANCE_RATIO = 0.05
SCAN_CEILING_FILLED_REGIONS = False
ROOM_CLIP_HEIGHT_M = 100.0
MIN_SOLID_VOLUME_FT3 = 1e-9
MIN_CLIPPED_AREA_M2 = 0.001
FIRST_DATA_ROW = 8

# 欄位順序。公式一律用這些名字寫（見 lib\sheet_layout.py）：欄位字母由 layout
# 在寫檔那一刻算出來，中間插一欄不需要回頭改任何一段公式。
SUMMARY_COLUMNS = ['room_no', 'room_name', 'quantity_area']
SUMMARY_HEADERS = [u'編號', u'空間名稱', u'面積']
# 材料欄夾在中間，最後兩欄固定是「對應圖說」與「備註」。
DRAWING_COLUMN = 'drawing'
NOTES_COLUMN = 'notes'
TRAILING_COLUMNS = [DRAWING_COLUMN, NOTES_COLUMN]
SUMMARY_LAYOUT = sheet_layout.SheetLayout(
    SUMMARY_COLUMNS, first_data_row=FIRST_DATA_ROW, name=u'天花數量計算')
FIXED_REPORT_COLS = SUMMARY_LAYOUT.width
TRAILING_REPORT_COLS = len(TRAILING_COLUMNS)


def full_layout(material_cols):
    """固定欄 ＋ 材料欄 ＋ 對應圖說／備註欄。"""
    return SUMMARY_LAYOUT.with_columns(
        list(material_cols) + TRAILING_COLUMNS)
SUMMARY_LABEL = u'天花數量總計'
SCRIPT_VERSION = u'2026-07-23-ceiling-residual-no-filled-area-v7'


doc = revit.doc
output = script.get_output()
ACTIVE_ALLOWED_LEVEL_IDS = None


def clean(value):
    if value is None:
        return ''
    return String.Format('{0}', value).strip()


def element_id_value(element_id):
    try:
        return int(element_id.Value)
    except Exception:
        return int(element_id.IntegerValue)


def room_is_in_active_level_scope(room):
    if ACTIVE_ALLOWED_LEVEL_IDS is None:
        return True
    try:
        return element_id_value(room.LevelId) in ACTIVE_ALLOWED_LEVEL_IDS
    except Exception:
        return False


def valid_element_id(element_id):
    if element_id is None:
        return False
    try:
        return element_id_value(element_id) > 0
    except Exception:
        return False


def get_bip_param(element, bip_name):
    if element is None:
        return None
    try:
        bip = getattr(BuiltInParameter, bip_name)
    except AttributeError:
        return None
    try:
        return element.get_Parameter(bip)
    except Exception:
        return None


def lookup_value(element, names):
    if element is None:
        return ''
    for name in names:
        try:
            param = element.LookupParameter(name)
        except Exception:
            param = None
        if param and param.HasValue:
            value = clean(param.AsValueString() or param.AsString())
            if value:
                return value
    return ''


def param_text(element, bip_names=None, lookup_names=None):
    bip_names = bip_names or []
    lookup_names = lookup_names or []
    for bip_name in bip_names:
        param = get_bip_param(element, bip_name)
        if param and param.HasValue:
            value = clean(param.AsString() or param.AsValueString())
            if value:
                return value
    return lookup_value(element, lookup_names)


def element_name(element):
    if element is None:
        return ''
    try:
        value = clean(element.Name)
        if value:
            return value
    except Exception:
        pass
    try:
        value = clean(Element.Name.GetValue(element))
        if value:
            return value
    except Exception:
        pass
    for bip_name in ('SYMBOL_NAME_PARAM', 'ALL_MODEL_TYPE_NAME', 'ROOM_NAME', 'DATUM_TEXT'):
        param = get_bip_param(element, bip_name)
        if param and param.HasValue:
            value = clean(param.AsString() or param.AsValueString())
            if value:
                return value
    return ''


def parse_number(value):
    text = clean(value).replace(',', '')
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    return float(match.group(0)) if match else None


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
                value = parse_number(param.AsValueString() or param.AsString())
                if value is not None:
                    return value
    return None


def param_double_sqm(element, bip_names, lookup_names=None):
    lookup_names = lookup_names or []
    for bip_name in bip_names:
        param = get_bip_param(element, bip_name)
        if param and param.HasValue:
            try:
                value = param.AsDouble() * SQFT_TO_SQM
                if value > 0:
                    return value
            except Exception:
                pass
            value = parse_number(param.AsValueString() or param.AsString())
            if value is not None and value > 0:
                return value
    for name in lookup_names:
        try:
            param = element.LookupParameter(name)
        except Exception:
            param = None
        if param and param.HasValue:
            try:
                value = param.AsDouble() * SQFT_TO_SQM
                if value > 0:
                    return value
            except Exception:
                pass
            value = parse_number(param.AsValueString() or param.AsString())
            if value is not None and value > 0:
                return value
    return None


def param_element_id(element, bip_name):
    param = get_bip_param(element, bip_name)
    if param and param.HasValue:
        try:
            return param.AsElementId()
        except Exception:
            return None
    return None


def round2(value):
    return round(value + 1e-9, 2)


def fixed2(value):
    if value is None:
        return ''
    try:
        if math.isnan(value) or math.isinf(value):
            return ''
    except Exception:
        pass
    return '{0:.2f}'.format(round2(value))


def note_area_diff_significant(value, reference):
    if value is None or reference is None:
        return False
    try:
        diff = abs(value - reference)
    except Exception:
        return False
    tolerance = max(CEILING_NOTE_AREA_TOLERANCE_M2, abs(reference) * CEILING_NOTE_AREA_TOLERANCE_RATIO)
    return diff > tolerance


def main_note_warnings(warnings):
    result = []
    keep_patterns = [
        u'房間天花板塗層未填',
        u'未辨識到 C 代碼',
        u'未辨識 C 代碼',
        u'房間天花板塗層為',
        u'房間有多重天花代碼',
        u'同時有多個 C 代碼',
        u'差異較大',
    ]
    skip_patterns = [
        u'已排除',
        u'另排除',
        u'幾乎完整位於房間內',
        u'僅供比對',
        u'覆蓋估算',
        u'淨高採',
        u'改用樓板底',
        u'淨高改用上層樓板底',
        u'填滿範圍面積掃描',
    ]
    for warning in warnings or []:
        text = clean(warning)
        if not text:
            continue
        if any(pattern in text for pattern in skip_patterns):
            continue
        if any(pattern in text for pattern in keep_patterns):
            append_unique(result, [text])
    return result


def round_to_step(value, step):
    if value is None or not step:
        return value
    return math.floor((value / step) + 0.5) * step


def valid_height(value):
    return value is not None and value >= MIN_VALID_HEIGHT_M and value <= MAX_VALID_HEIGHT_M


def normalize_metric_m(value):
    if value is None:
        return None
    try:
        number = float(value)
    except Exception:
        return None
    if number <= 0:
        return None
    if number > 50:
        return number / 1000.0
    if number > 20:
        return number / 100.0
    return number


def param_height_m(element, bip_names=None, lookup_names=None):
    bip_names = bip_names or []
    lookup_names = lookup_names or []
    for bip_name in bip_names:
        param = get_bip_param(element, bip_name)
        if param and param.HasValue:
            try:
                value = param.AsDouble() * FT_TO_M
                if valid_height(value):
                    return value
            except Exception:
                pass
            value = normalize_metric_m(parse_number(param.AsValueString() or param.AsString()))
            if valid_height(value):
                return value
    for name in lookup_names:
        try:
            param = element.LookupParameter(name)
        except Exception:
            param = None
        if param and param.HasValue:
            try:
                value = param.AsDouble() * FT_TO_M
                if valid_height(value):
                    return value
            except Exception:
                pass
            value = normalize_metric_m(parse_number(param.AsValueString() or param.AsString()))
            if valid_height(value):
                return value
    return None


def normalize_level(value):
    text = clean(value).upper().replace(' ', '')
    if not text:
        return ''

    match = re.match(r'^[A-Z]+-(.+)$', text)
    if match:
        text = match.group(1)

    if text in ('FN', 'BS'):
        return 'BS'

    match = re.match(r'^B0*(\d+)F?$', text)
    if match:
        return 'B{0}'.format(int(match.group(1)))

    match = re.match(r'^R0*(\d+)F?$', text)
    if match:
        return 'R{0}'.format(int(match.group(1)))

    match = re.match(r'^0*(\d+)F$', text)
    if match:
        return 'F{0}'.format(int(match.group(1)))

    return text[:-1] if text.endswith('F') else text


def level_storage_key(value):
    return clean(value).upper().replace(' ', '')


def level_series(value):
    text = level_storage_key(value)
    match = re.match(r'^([A-Z]+)-', text)
    return match.group(1) if match else ''


def floor_sort_key(value):
    """Floor ordering BS < B3 < B2 < B1 < F1 < F2 < R1 (same rule as Baseboard)."""
    text = normalize_level(value)
    if text == 'BS':
        return (-1000, clean(value))

    match = re.match(r'^(BS|B|F|R)?0*(\d+)', text)
    if not match:
        return (9999, clean(value))
    prefix = match.group(1) or 'F'
    number = int(match.group(2))
    if prefix == 'BS':
        order = -100
    elif prefix == 'B':
        order = -number
    elif prefix == 'R':
        order = 1000 + number
    else:
        order = number
    return (order, clean(value))


def room_sort_key(number, level):
    return (
        floor_sort_key(level or number),
        room_takeoff_sources_logic.room_number_sort_key(number),
        clean(number).upper().replace(' ', ''))


def room_number(room):
    param = get_bip_param(room, 'ROOM_NUMBER')
    value = clean(param.AsString() or param.AsValueString()) if param else ''
    if not value:
        value = lookup_value(room, [u'編號', 'Number'])
    if value:
        return value.upper()
    match = re.search(r'((?:BS|FN|B|F|R)\d{2,4})\b', element_name(room), re.I)
    return match.group(1).upper() if match else ''


def room_name(room, number):
    param = get_bip_param(room, 'ROOM_NAME')
    value = clean(param.AsString() or param.AsValueString()) if param else ''
    if not value:
        value = lookup_value(room, [u'名稱', 'Name']) or element_name(room)
    if number:
        value = re.sub(r'\s*{0}\s*$'.format(re.escape(number)), '', value, flags=re.I).strip()
    return value


def level_name(element):
    try:
        level_id = element.LevelId
        if valid_element_id(level_id):
            level = doc.GetElement(level_id)
            if level:
                return element_name(level)
    except Exception:
        pass
    return lookup_value(element, [u'樓層', 'Level'])


def room_ceiling_finish(room):
    value = lookup_value(room, [
        u'天花板塗層',
        u'天花板',
        u'天花塗層',
        u'天花',
        'Ceiling Finish',
        'CeilingFinish',
    ])
    if clean(value).upper() in ('-', u'無', 'NA', 'N/A', 'NONE'):
        return ''
    return value


def ceiling_finish_codes(value):
    text = clean(value)
    if not text:
        return []
    result = []
    for match in re.finditer(r'(?<![A-Z0-9])(C\s*0*\d+[A-Z]?)(?![A-Z0-9])', text.upper()):
        code = match.group(1)
        code = re.sub(r'\s+', '', clean(code)).upper()
        if code and code not in result:
            result.append(code)
    return result


def ceiling_type_codes(ceiling_type):
    if ceiling_type is None:
        return []
    type_mark = param_text(
        ceiling_type,
        ['ALL_MODEL_TYPE_MARK'],
        [u'類型標記', u'類型註記', 'Type Mark']
    )
    return ceiling_finish_codes(type_mark)


def ceiling_material_codes(ceiling_type):
    if ceiling_type is None:
        return []
    codes = []
    try:
        compound = ceiling_type.GetCompoundStructure()
    except Exception:
        compound = None
    if compound is None:
        return codes
    try:
        layers = list(compound.GetLayers())
    except Exception:
        layers = []
    for layer in layers:
        try:
            material_id = layer.MaterialId
        except Exception:
            material_id = None
        if not valid_element_id(material_id):
            continue
        try:
            material = doc.GetElement(material_id)
        except Exception:
            material = None
        if material is None:
            continue
        texts = [
            param_text(material, ['ALL_MODEL_MARK'], [u'標記', u'材料標記', 'Mark']),
            lookup_value(material, [u'描述', 'Description', u'註解', 'Comments']),
            element_name(material),
        ]
        for text in texts:
            append_unique(codes, ceiling_finish_codes(text))
    return codes


def ceiling_area_sqm(ceiling):
    return param_double_sqm(
        ceiling,
        ['HOST_AREA_COMPUTED'],
        [u'面積', 'Area']
    )


def finish_sort_key(value):
    text = clean(value).upper()
    match = re.match(r'^C\s*0*(\d+)([A-Z]*)$', text)
    if match:
        return (0, int(match.group(1)), match.group(2) or '', text)
    parts = []
    for part in re.split(r'(\d+)', text):
        parts.append(int(part) if part.isdigit() else part)
    return (1, parts)


def valid_room(room):
    if room is None:
        return False
    try:
        if not isinstance(room, SpatialElement):
            return False
    except Exception:
        pass
    try:
        return room.Area > 0
    except Exception:
        return True


def build_level_catalog():
    entries = []
    by_id = {}
    for level in FilteredElementCollector(doc).OfClass(Level):
        try:
            elevation = level.Elevation * FT_TO_M
        except Exception:
            continue
        entry = {
            'id': element_id_value(level.Id),
            'name': element_name(level),
            'key': level_storage_key(element_name(level)),
            'elevation': elevation,
        }
        entries.append(entry)
        by_id[entry['id']] = entry
    entries.sort(key=lambda item: item['elevation'])
    return {'entries': entries, 'by_id': by_id}


def level_entry_from_id(level_catalog, element_id):
    if not valid_element_id(element_id):
        return None
    return level_catalog.get('by_id', {}).get(element_id_value(element_id))


def level_entry_for_element(element, level_catalog):
    entry = level_entry_from_id(level_catalog, getattr(element, 'LevelId', None))
    if entry:
        return entry
    for bip_name in ('LEVEL_PARAM', 'SCHEDULE_LEVEL_PARAM'):
        entry = level_entry_from_id(level_catalog, param_element_id(element, bip_name))
        if entry:
            return entry
    level_key = level_storage_key(level_name(element))
    if level_key:
        for candidate in level_catalog.get('entries', []):
            if candidate.get('key') == level_key:
                return candidate
    return None


def ceiling_offset_m(ceiling):
    return param_height_m(
        ceiling,
        ['CEILING_HEIGHTABOVELEVEL_PARAM', 'INSTANCE_FREE_HOST_OFFSET_PARAM'],
        [u'距樓層的高度偏移', u'高度偏移', u'天花高度', 'Height Offset From Level', 'Offset']
    )


def floor_thickness_m(floor):
    thickness = param_double_m(floor, ['FLOOR_ATTR_THICKNESS_PARAM'], [u'厚度', 'Thickness'])
    if not thickness:
        try:
            floor_type = doc.GetElement(floor.GetTypeId())
        except Exception:
            floor_type = None
        if floor_type:
            thickness = param_double_m(floor_type, ['FLOOR_ATTR_THICKNESS_PARAM'], [u'厚度', 'Thickness'])
    try:
        box = floor.get_BoundingBox(None)
    except Exception:
        box = None
    if (not thickness or thickness <= 0) and box:
        thickness = (box.Max.Z - box.Min.Z) * FT_TO_M
    if thickness and thickness >= 0.08 and thickness <= 1.20:
        return thickness
    return None


def is_structural_floor_name(name):
    text = clean(name).upper()
    return bool(re.search(r'(^|[_\s-])RC([_\s-]|$)|結構|STRUCT', text))


def add_slab_thickness_group(groups, level_key, thickness, name):
    if not level_key or not thickness:
        return
    bucket = fixed2(thickness)
    if level_key not in groups:
        groups[level_key] = {}
    if bucket not in groups[level_key]:
        groups[level_key][bucket] = {
            'thickness': thickness,
            'count': 0,
            'structural_count': 0,
        }
    item = groups[level_key][bucket]
    item['count'] += 1
    if is_structural_floor_name(name):
        item['structural_count'] += 1


def select_group_thickness(items):
    selected = None
    for item in items.values():
        if selected is None:
            selected = item
        elif item['structural_count'] > selected['structural_count']:
            selected = item
        elif item['structural_count'] == selected['structural_count']:
            if item['count'] > selected['count']:
                selected = item
            elif item['count'] == selected['count'] and item['thickness'] < selected['thickness']:
                selected = item
    return selected['thickness'] if selected else None


def element_box_tuple(element):
    try:
        box = element.get_BoundingBox(None)
    except Exception:
        box = None
    if not box:
        return None
    return (
        box.Min.X, box.Min.Y, box.Min.Z,
        box.Max.X, box.Max.Y, box.Max.Z,
    )


def append_geometry_solids(geometry, result):
    if geometry is None:
        return
    for geometry_object in geometry:
        if isinstance(geometry_object, Solid):
            try:
                if geometry_object.Volume > MIN_SOLID_VOLUME_FT3:
                    result.append(geometry_object)
            except Exception:
                pass
        elif isinstance(geometry_object, GeometryInstance):
            try:
                append_geometry_solids(geometry_object.GetInstanceGeometry(), result)
            except Exception:
                pass


def element_solids(element):
    try:
        geometry = element.get_Geometry(Options())
    except Exception:
        geometry = None
    result = []
    append_geometry_solids(geometry, result)
    return result


def room_boundary_prism(room):
    options = SpatialElementBoundaryOptions()
    try:
        options.SpatialElementBoundaryLocation = SpatialElementBoundaryLocation.Finish
    except Exception:
        pass
    try:
        segment_loops = room.GetBoundarySegments(options)
    except Exception:
        segment_loops = None
    if not segment_loops:
        return None

    curve_loops = List[CurveLoop]()
    try:
        for segments in segment_loops:
            curve_loop = CurveLoop()
            curve_count = 0
            for segment in segments:
                curve = segment.GetCurve()
                if curve is None or curve.Length <= 1e-9:
                    continue
                curve_loop.Append(curve)
                curve_count += 1
            if curve_count >= 3:
                curve_loops.Add(curve_loop)
        if curve_loops.Count <= 0:
            return None
        return GeometryCreationUtilities.CreateExtrusionGeometry(
            curve_loops,
            XYZ.BasisZ,
            ROOM_CLIP_HEIGHT_M / FT_TO_M
        )
    except Exception:
        return None


def solid_upward_area_sqm(solid):
    total = 0.0
    try:
        faces = solid.Faces
    except Exception:
        return None
    for face in faces:
        try:
            normal = face.ComputeNormal(UV(0.5, 0.5))
            if normal.Z > 0.05:
                total += face.Area * SQFT_TO_SQM
        except Exception:
            pass
    return total if total > MIN_CLIPPED_AREA_M2 else None


def ceiling_clipped_area_sqm(room_prism, ceiling):
    if room_prism is None:
        return None, 'unavailable'
    ceiling_solids = ceiling.get('solids') or []
    if not ceiling_solids:
        return None, 'unavailable'
    total = 0.0
    success = False
    boolean_failed = False
    for ceiling_solid in ceiling_solids:
        try:
            intersection = BooleanOperationsUtils.ExecuteBooleanOperation(
                room_prism,
                ceiling_solid,
                BooleanOperationsType.Intersect
            )
            if intersection is None or intersection.Volume <= MIN_SOLID_VOLUME_FT3:
                continue
            area = solid_upward_area_sqm(intersection)
            if area is not None:
                total += area
                success = True
        except Exception:
            boolean_failed = True
    if success and total > MIN_CLIPPED_AREA_M2:
        return total, 'clipped'
    if boolean_failed:
        return None, 'failed'
    return None, 'no-intersection'


def ceiling_estimated_room_area_sqm(score, ceiling_area, room_area):
    estimated = score.get('score', 0) * SQFT_TO_SQM if score else 0
    candidates = [value for value in (estimated, ceiling_area, room_area) if value is not None and value > 0]
    return min(candidates) if candidates else None


def ceiling_codes_from_evidence_text(value):
    result = []
    text = clean(value).upper()
    for match in re.finditer(r'(?<![A-Z0-9])(C\s*0*\d+[A-Z]?)(?![A-Z0-9])', text):
        code = re.sub(r'\s+', '', match.group(1)).upper()
        if code and code not in result:
            result.append(code)
    return result


def filled_region_type_codes(region, tagged_codes=None):
    try:
        region_type = doc.GetElement(region.GetTypeId())
    except Exception:
        region_type = None
    texts = [
        element_name(region_type),
        param_text(region_type, ['ALL_MODEL_TYPE_MARK'], [u'類型標記', 'Type Mark']),
        lookup_value(region_type, [u'描述', 'Description', u'類型備註', 'Type Comments']),
        lookup_value(region, [u'備註', 'Comments', u'標註', u'說明文字']),
    ]
    codes = []
    for text in texts:
        append_unique(codes, ceiling_codes_from_evidence_text(text))
    append_unique(codes, (tagged_codes or {}).get(element_id_value(region.Id), []))
    return codes, element_name(region_type) or element_name(region)


def view_tagged_ceiling_codes(view):
    result = {}
    collector = FilteredElementCollector(doc, view.Id).OfClass(IndependentTag)
    for tag in collector:
        try:
            tag_text = tag.TagText
        except Exception:
            tag_text = ''
        codes = ceiling_codes_from_evidence_text(tag_text)
        if not codes:
            continue
        tagged_ids = []
        try:
            for element_id in tag.GetTaggedLocalElementIds():
                tagged_ids.append(element_id_value(element_id))
        except Exception:
            try:
                tagged_id = tag.TaggedLocalElementId
                if valid_element_id(tagged_id):
                    tagged_ids.append(element_id_value(tagged_id))
            except Exception:
                pass
        for tagged_id in tagged_ids:
            if tagged_id not in result:
                result[tagged_id] = []
            append_unique(result[tagged_id], codes)
    return result


def curve_loop_fingerprint(curve_loops):
    loops = []
    try:
        iterator = list(curve_loops)
    except Exception:
        iterator = []
    for curve_loop in iterator:
        points = []
        try:
            curves = list(curve_loop)
        except Exception:
            curves = []
        for curve in curves:
            try:
                point = curve.GetEndPoint(0)
                points.append((round(point.X, 4), round(point.Y, 4)))
            except Exception:
                pass
        if points:
            loops.append(tuple(sorted(points)))
    return tuple(sorted(loops))


def filled_region_solid(curve_loops):
    loops = List[CurveLoop]()
    try:
        for curve_loop in curve_loops:
            loops.Add(curve_loop)
        if loops.Count <= 0:
            return None
        return GeometryCreationUtilities.CreateExtrusionGeometry(
            loops,
            XYZ.BasisZ,
            ROOM_CLIP_HEIGHT_M / FT_TO_M
        )
    except Exception:
        return None


def collect_ceiling_filled_regions(level_catalog):
    view_sources = {}
    for sheet in FilteredElementCollector(doc).OfClass(ViewSheet):
        try:
            if sheet.IsPlaceholder:
                continue
        except Exception:
            pass
        sheet_number = param_text(
            sheet,
            ['SHEET_NUMBER'],
            [u'圖紙編號', 'Sheet Number']
        ) or element_name(sheet)
        sheet_name = param_text(
            sheet,
            ['SHEET_NAME'],
            [u'圖紙名稱', 'Sheet Name']
        ) or element_name(sheet)
        sheet_has_ceiling = u'天花' in clean(sheet_name)
        try:
            placed_view_ids = sheet.GetAllPlacedViews()
        except Exception:
            placed_view_ids = []
        for view_id in placed_view_ids:
            view = doc.GetElement(view_id)
            if view is None or getattr(view, 'IsTemplate', False):
                continue
            view_name = element_name(view)
            view_has_ceiling = u'天花' in clean(view_name)
            if not sheet_has_ceiling and not view_has_ceiling:
                continue
            try:
                gen_level = view.GenLevel
            except Exception:
                gen_level = None
            level_entry = level_entry_from_id(
                level_catalog,
                gen_level.Id if gen_level is not None else None
            )
            if level_entry is None:
                continue
            view_type = clean(getattr(view, 'ViewType', ''))
            if 'CEILINGPLAN' not in view_type.upper() and not view_has_ceiling:
                continue
            key = element_id_value(view.Id)
            if key not in view_sources:
                view_sources[key] = {
                    'view': view,
                    'view_id': key,
                    'view_name': view_name,
                    'level_id': level_entry['id'],
                    'sources': [],
                }
            source = u'{0}／{1}'.format(sheet_number, view_name)
            if source not in view_sources[key]['sources']:
                view_sources[key]['sources'].append(source)

    regions = []
    deduped = {}
    for view_info in view_sources.values():
        view = view_info['view']
        tagged_codes = view_tagged_ceiling_codes(view)
        collector = FilteredElementCollector(doc, view.Id).OfClass(FilledRegion)
        for region in collector:
            try:
                owner_view_id = element_id_value(region.OwnerViewId)
            except Exception:
                owner_view_id = 0
            if owner_view_id and owner_view_id != view_info['view_id']:
                continue
            codes, type_name = filled_region_type_codes(region, tagged_codes)
            if not codes:
                continue
            try:
                boundaries = region.GetBoundaries()
            except Exception:
                boundaries = None
            if not boundaries:
                continue
            solid = filled_region_solid(boundaries)
            if solid is None:
                continue
            fingerprint = curve_loop_fingerprint(boundaries)
            dedupe_key = (
                view_info['level_id'],
                tuple(sorted(codes)),
                fingerprint,
            )
            if dedupe_key in deduped:
                append_unique(deduped[dedupe_key]['sources'], view_info['sources'])
                continue
            try:
                box = region.get_BoundingBox(view)
            except Exception:
                box = None
            item = {
                'id': element_id_value(region.Id),
                'codes': codes,
                'type_name': type_name,
                'level_id': view_info['level_id'],
                'view_id': view_info['view_id'],
                'view_name': view_info['view_name'],
                'sources': list(view_info['sources']),
                'solid': solid,
                'box': (
                    (box.Min.X, box.Min.Y, box.Max.X, box.Max.Y)
                    if box is not None else None
                ),
            }
            deduped[dedupe_key] = item
            regions.append(item)
    return regions, len(view_sources)


def room_filled_region_info(room, height_context):
    if not height_context.get('filled_regions'):
        return {
            'codes': [],
            'code_areas': {},
            'details': [],
            'warnings': [],
            'area': 0.0,
            'match_count': 0,
        }
    room_level_id = element_id_value(getattr(room, 'LevelId', None))
    room_box = element_box_tuple(room)
    room_prism = room_boundary_prism(room)
    code_areas = {}
    codes = []
    details = []
    warnings = []
    matched_ids = []
    if room_prism is None:
        return {
            'codes': [],
            'code_areas': {},
            'details': [],
            'warnings': [],
            'match_count': 0,
        }

    for region in height_context.get('filled_regions', []):
        if region.get('level_id') != room_level_id:
            continue
        region_box = region.get('box')
        if room_box and region_box:
            if (room_box[3] <= region_box[0] or room_box[0] >= region_box[2] or
                    room_box[4] <= region_box[1] or room_box[1] >= region_box[3]):
                continue
        try:
            intersection = BooleanOperationsUtils.ExecuteBooleanOperation(
                room_prism,
                region.get('solid'),
                BooleanOperationsType.Intersect
            )
            if intersection is None or intersection.Volume <= MIN_SOLID_VOLUME_FT3:
                continue
            area = solid_upward_area_sqm(intersection)
        except Exception:
            area = None
        if area is None or area <= MIN_CLIPPED_AREA_M2:
            continue
        matched_ids.append(region['id'])
        append_unique(codes, region.get('codes') or [])
        region_codes = region.get('codes') or []
        if len(region_codes) == 1:
            code = region_codes[0]
            code_areas[code] = code_areas.get(code, 0.0) + area
        else:
            warnings.append(
                u'填滿範圍 Id {0} 同時解析出多個 C 代碼 {1}，未自動分攤面積'.format(
                    region['id'],
                    '+'.join(region_codes)
                )
            )
        details.append({
            'id': region['id'],
            'codes': list(region_codes),
            'area': area,
            'type_name': region.get('type_name') or '',
            'sources': list(region.get('sources') or []),
        })

    return {
        'codes': codes,
        'code_areas': code_areas,
        'details': details,
        'warnings': warnings,
        'area': sum(code_areas.values()),
        'match_count': len(matched_ids),
    }


def collect_ceiling_data(level_catalog):
    ceilings = []
    collector = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Ceilings).WhereElementIsNotElementType()
    for ceiling in collector:
        box = element_box_tuple(ceiling)
        if not box:
            continue
        bbox_bottom_m = box[2] * FT_TO_M
        top_m = box[5] * FT_TO_M
        if top_m <= bbox_bottom_m:
            continue
        level_entry = level_entry_for_element(ceiling, level_catalog)
        offset_m = ceiling_offset_m(ceiling)
        offset_bottom_m = None
        if level_entry and offset_m is not None:
            offset_bottom_m = level_entry['elevation'] + offset_m
        try:
            ceiling_type = doc.GetElement(ceiling.GetTypeId())
        except Exception:
            ceiling_type = None
        ceiling_name = element_name(ceiling_type) or element_name(ceiling)
        type_codes = ceiling_type_codes(ceiling_type)
        material_codes = ceiling_material_codes(ceiling_type)
        name_codes = ceiling_finish_codes(ceiling_name)
        effective_codes = list(type_codes)
        if not effective_codes:
            append_unique(effective_codes, material_codes)
        if not effective_codes:
            append_unique(effective_codes, name_codes)
        ceilings.append({
            'id': element_id_value(ceiling.Id),
            'name': ceiling_name,
            'codes': effective_codes,
            'type_codes': type_codes,
            'material_codes': material_codes,
            'name_codes': name_codes,
            'level': level_entry['key'] if level_entry else level_storage_key(level_name(ceiling)),
            'level_elevation': level_entry['elevation'] if level_entry else None,
            'offset_m': offset_m,
            'box': box,
            'area': ceiling_area_sqm(ceiling),
            'solids': element_solids(ceiling),
            'bottom_m': offset_bottom_m if offset_bottom_m is not None else bbox_bottom_m,
            'bbox_bottom_m': bbox_bottom_m,
            'top_m': top_m,
        })
    return ceilings


def build_height_context():
    level_catalog = build_level_catalog()
    thickness_groups = {}
    collector = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Floors).WhereElementIsNotElementType()
    for floor in collector:
        thickness = floor_thickness_m(floor)
        if not thickness:
            continue
        level_entry = level_entry_from_id(level_catalog, getattr(floor, 'LevelId', None))
        level_key = level_entry['key'] if level_entry else level_storage_key(level_name(floor))
        try:
            floor_type_name = element_name(doc.GetElement(floor.GetTypeId()))
        except Exception:
            floor_type_name = ''
        add_slab_thickness_group(
            thickness_groups,
            level_key,
            thickness,
            u'{0} {1}'.format(element_name(floor), floor_type_name)
        )

    thickness_by_level = {}
    for level_key, items in thickness_groups.items():
        thickness = select_group_thickness(items)
        if thickness:
            thickness_by_level[level_key] = thickness

    if SCAN_CEILING_FILLED_REGIONS:
        filled_regions, ceiling_drawing_view_count = collect_ceiling_filled_regions(level_catalog)
    else:
        filled_regions, ceiling_drawing_view_count = [], 0
    return {
        'levels': level_catalog,
        'thickness_by_level': thickness_by_level,
        'ceilings': collect_ceiling_data(level_catalog),
        'filled_regions': filled_regions,
        'ceiling_drawing_view_count': ceiling_drawing_view_count,
    }


def room_base_level_entry(room, height_context):
    return level_entry_from_id(height_context.get('levels', {}), getattr(room, 'LevelId', None))


def room_base_elevation_m(room, height_context):
    entry = room_base_level_entry(room, height_context)
    offset = param_double_m(room, ['ROOM_LOWER_OFFSET'], [u'基準偏移', u'底部偏移', 'Base Offset']) or 0
    if entry:
        return entry['elevation'] + offset
    box = element_box_tuple(room)
    return box[2] * FT_TO_M if box else None


def room_top_level_entry(room, height_context, base_elevation):
    level_catalog = height_context.get('levels', {})
    upper_id = param_element_id(room, 'ROOM_UPPER_LEVEL')
    entry = level_entry_from_id(level_catalog, upper_id)
    if entry and base_elevation is not None and entry['elevation'] > base_elevation + 0.50:
        return entry

    base_entry = room_base_level_entry(room, height_context)
    base_series = level_series(base_entry.get('name')) if base_entry else level_series(level_name(room))
    if base_series:
        for candidate in level_catalog.get('entries', []):
            if level_series(candidate.get('name')) != base_series:
                continue
            if base_elevation is not None and candidate['elevation'] > base_elevation + 1.50:
                return candidate
    for candidate in level_catalog.get('entries', []):
        if base_elevation is not None and candidate['elevation'] > base_elevation + 1.50:
            return candidate
    return None


def ceiling_room_sample_score(room, room_box_data, ceiling_box, sample_z=None):
    if not room_box_data or not ceiling_box:
        return None
    min_x = max(room_box_data[0], ceiling_box[0])
    min_y = max(room_box_data[1], ceiling_box[1])
    max_x = min(room_box_data[3], ceiling_box[3])
    max_y = min(room_box_data[4], ceiling_box[4])
    if max_x <= min_x or max_y <= min_y:
        return None

    if sample_z is None:
        sample_z = (room_box_data[2] + room_box_data[5]) / 2.0
    inside = 0
    total = CEILING_SAMPLE_GRID * CEILING_SAMPLE_GRID
    for x_index in range(CEILING_SAMPLE_GRID):
        x_ratio = float(x_index + 1) / float(CEILING_SAMPLE_GRID + 1)
        x_value = min_x + (max_x - min_x) * x_ratio
        for y_index in range(CEILING_SAMPLE_GRID):
            y_ratio = float(y_index + 1) / float(CEILING_SAMPLE_GRID + 1)
            y_value = min_y + (max_y - min_y) * y_ratio
            try:
                if room.IsPointInRoom(XYZ(x_value, y_value, sample_z)):
                    inside += 1
            except Exception:
                pass
    if inside <= 0:
        return None
    overlap = (max_x - min_x) * (max_y - min_y)
    return {
        'score': overlap * (float(inside) / float(total)),
        'inside': inside,
        'total': total,
    }


def ceiling_room_match_score(room, room_box_data, ceiling, room_codes=None):
    room_codes = room_codes or []
    bottom_m = ceiling.get('bottom_m')
    if bottom_m is None:
        bottom_m = ceiling.get('bbox_bottom_m')
    if bottom_m is not None:
        sample_z = (bottom_m - CEILING_SAMPLE_BELOW_M) / FT_TO_M
        score = ceiling_room_sample_score(room, room_box_data, ceiling.get('box'), sample_z)
        if score:
            score['mode'] = 'ceiling-plane'
            return score

    score = ceiling_room_sample_score(room, room_box_data, ceiling.get('box'))
    if score and room_codes:
        match_codes = list(ceiling.get('codes') or [])
        append_unique(match_codes, ceiling.get('name_codes') or [])
        for code in match_codes:
            if code in room_codes:
                score['mode'] = 'room-code-overlap'
                return score
    return None


def append_unique(target, values):
    for value in values or []:
        if value and value not in target:
            target.append(value)


def room_actual_ceiling_info(room, height_context, room_codes=None):
    room_codes = room_codes or []
    room_box_data = element_box_tuple(room)
    try:
        room_area = room.Area * SQFT_TO_SQM
    except Exception:
        room_area = None
    room_prism = room_boundary_prism(room)
    base_elevation = room_base_elevation_m(room, height_context)
    room_level_entry = room_base_level_entry(room, height_context)
    room_level_key = room_level_entry.get('key') if room_level_entry else level_storage_key(level_name(room))
    room_level_series = level_series(room_level_key)
    if base_elevation is None:
        return {
            'area': None,
            'area_source': 'room-area',
            'clipped_area': 0.0,
            'estimated_area': 0.0,
            'vertically_rejected_count': 0,
            'match_count': 0,
            'ceiling_names': [],
            'ceiling_codes': [],
            'code_areas': {},
            'ceiling_unmarked_names': [],
            'warnings': [],
        }

    total_area = 0.0
    clipped_area = 0.0
    estimated_area = 0.0
    match_count = 0
    names = []
    codes = []
    code_areas = {}
    unmarked_names = []
    warnings = []
    seen_ids = set()
    candidates = []
    contained_element_area_used = False

    for ceiling in height_context.get('ceilings', []):
        ceiling_id = ceiling.get('id')
        if ceiling_id in seen_ids:
            continue
        ceiling_level = ceiling.get('level')
        ceiling_series = level_series(ceiling_level)
        if room_level_series and ceiling_series and room_level_series != ceiling_series:
            continue
        height, _source = ceiling_height_from_room_base(
            ceiling,
            base_elevation,
            room_level_entry,
            room_level_key
        )
        if not valid_height(height):
            continue
        score = ceiling_room_match_score(room, room_box_data, ceiling, room_codes)
        if not score:
            continue

        clipped, clip_status = ceiling_clipped_area_sqm(room_prism, ceiling)
        if clip_status == 'no-intersection':
            continue
        seen_ids.add(ceiling_id)
        candidates.append({
            'ceiling': ceiling,
            'height': height,
            'score': score,
            'clipped_area': clipped,
            'clip_status': clip_status,
        })

    same_level_candidates = [
        item for item in candidates
        if item['ceiling'].get('level') == room_level_key
    ]
    if same_level_candidates:
        selected_candidates = same_level_candidates
    elif candidates:
        nearest = min(candidates, key=lambda item: item.get('height') or MAX_VALID_HEIGHT_M)
        nearest_level = nearest['ceiling'].get('level')
        if nearest_level:
            selected_candidates = [
                item for item in candidates
                if item['ceiling'].get('level') == nearest_level
            ]
        else:
            nearest_height = nearest.get('height') or 0
            selected_candidates = [
                item for item in candidates
                if abs((item.get('height') or 0) - nearest_height) <= CEILING_ABOVE_SLAB_TOLERANCE_M
            ]
    else:
        selected_candidates = []

    vertically_rejected = len(candidates) - len(selected_candidates)
    if vertically_rejected > 0:
        warnings.append(
            u'已排除 {0} 筆位於其他樓層或更高高度的重疊天花候選，避免垂直重複加總。'.format(
                vertically_rejected
            )
        )

    for candidate in selected_candidates:
        ceiling = candidate['ceiling']
        allocated_area = 0.0
        match_count += 1
        if ceiling.get('name') and ceiling.get('name') not in names:
            names.append(ceiling.get('name'))
        has_any_ceiling_code = bool(
            ceiling.get('type_codes') or ceiling.get('material_codes') or ceiling.get('name_codes')
        )
        if not has_any_ceiling_code and ceiling.get('name') and ceiling.get('name') not in unmarked_names:
            unmarked_names.append(ceiling.get('name'))
        append_unique(codes, ceiling.get('codes') or [])

        area = candidate.get('clipped_area')
        if area is not None and area > 0:
            element_area = ceiling.get('area')
            if (element_area is not None and element_area > 0 and
                    room_area is not None and element_area <= room_area + AREA_DIFF_WARN_TOLERANCE_M2 and
                    area / element_area >= 0.98):
                if abs(element_area - area) > AREA_DIFF_WARN_TOLERANCE_M2:
                    warnings.append(
                        u'實體天花 {0} 幾乎完整位於房間內，採 Revit 元件面積 {1} m²'
                        u'（房間邊界裁切為 {2} m²）'.format(
                            ceiling.get('name') or ceiling.get('id'),
                            fixed2(element_area),
                            fixed2(area)
                        )
                    )
                area = element_area
                contained_element_area_used = True
            total_area += area
            clipped_area += area
            allocated_area = area
        else:
            estimated = ceiling_estimated_room_area_sqm(
                candidate.get('score'),
                ceiling.get('area'),
                room_area
            )
            if estimated is not None and estimated > 0:
                if room_area is not None:
                    estimated = min(estimated, max(room_area - total_area, 0))
                if estimated > 0:
                    total_area += estimated
                    estimated_area += estimated
                    allocated_area = estimated
        ceiling_codes = list(ceiling.get('codes') or [])
        if allocated_area > 0 and len(ceiling_codes) == 1:
            code = ceiling_codes[0]
            code_areas[code] = code_areas.get(code, 0.0) + allocated_area
        elif allocated_area > 0 and len(ceiling_codes) > 1:
            warnings.append(
                u'實體天花 Id {0} 同時有多個 C 代碼 {1}，未自動分攤該片面積'.format(
                    ceiling.get('id'),
                    '+'.join(ceiling_codes)
                )
            )

    if match_count and estimated_area > 0:
        warnings.append(u'部分實體天花無法完成房間邊界幾何裁切，已使用房間內覆蓋估算；估算面積不會超過 Room 面積。')

    if clipped_area > 0 and estimated_area > 0:
        area_source = 'actual-ceiling-room-clipped-with-estimate'
    elif clipped_area > 0 and contained_element_area_used:
        area_source = 'actual-ceiling-contained-element-area'
    elif clipped_area > 0:
        area_source = 'actual-ceiling-room-clipped-area'
    elif estimated_area > 0:
        area_source = 'actual-ceiling-estimated-area'
    else:
        area_source = 'room-area'

    return {
        'area': total_area if total_area > 0 else None,
        'area_source': area_source,
        'clipped_area': clipped_area,
        'estimated_area': estimated_area,
        'vertically_rejected_count': vertically_rejected,
        'match_count': match_count,
        'ceiling_names': names,
        'ceiling_codes': codes,
        'code_areas': code_areas,
        'ceiling_unmarked_names': unmarked_names,
        'warnings': warnings,
    }


def ceiling_height_from_room_base(ceiling, base_elevation, room_level_entry, room_level_key):
    offset_m = ceiling.get('offset_m')
    level_elevation = ceiling.get('level_elevation')
    if offset_m is not None:
        if level_elevation is not None:
            height = level_elevation + offset_m - base_elevation
            if valid_height(height):
                return height, 'actual-ceiling-offset'
        elif room_level_entry and ceiling.get('level') == room_level_key:
            height = room_level_entry['elevation'] + offset_m - base_elevation
            if valid_height(height):
                return height, 'actual-ceiling-offset'

    bbox_bottom_m = ceiling.get('bbox_bottom_m')
    if bbox_bottom_m is not None:
        height = bbox_bottom_m - base_elevation
        if valid_height(height):
            return height, 'actual-ceiling-bbox'

    bottom_m = ceiling.get('bottom_m')
    if bottom_m is not None:
        height = bottom_m - base_elevation
        if valid_height(height):
            return height, 'actual-ceiling-bottom'
    return None, ''


def ceiling_bottom_height_info(room, height_context, base_elevation, max_height=None):
    if base_elevation is None:
        return None
    room_box_data = element_box_tuple(room)
    room_level_entry = room_base_level_entry(room, height_context)
    room_level_key = room_level_entry.get('key') if room_level_entry else level_storage_key(level_name(room))
    room_level_series = level_series(room_level_key)
    candidates = {}
    all_names = []
    all_codes = []
    unmarked_names = []
    rejected_names = []
    rejected_codes = []

    for ceiling in height_context.get('ceilings', []):
        ceiling_level = ceiling.get('level')
        ceiling_series = level_series(ceiling_level)
        if room_level_series and ceiling_series and room_level_series != ceiling_series:
            continue
        height, source = ceiling_height_from_room_base(
            ceiling,
            base_elevation,
            room_level_entry,
            room_level_key
        )
        if not valid_height(height):
            continue
        sample_score = ceiling_room_sample_score(room, room_box_data, ceiling.get('box'))
        if not sample_score:
            continue

        if max_height is not None and height > max_height:
            if ceiling.get('name') and ceiling.get('name') not in rejected_names:
                rejected_names.append(ceiling.get('name'))
            for code in ceiling.get('codes') or []:
                if code not in rejected_codes:
                    rejected_codes.append(code)
            continue

        if ceiling.get('name') and ceiling.get('name') not in all_names:
            all_names.append(ceiling.get('name'))
        if not ceiling.get('codes') and ceiling.get('name') and ceiling.get('name') not in unmarked_names:
            unmarked_names.append(ceiling.get('name'))
        for code in ceiling.get('codes') or []:
            if code not in all_codes:
                all_codes.append(code)

        rounded_height = round_to_step(height, HEIGHT_BUCKET_SIZE_M)
        bucket = fixed2(rounded_height)
        if bucket not in candidates:
            candidates[bucket] = {
                'height': rounded_height,
                'raw_height': height,
                'score': 0,
                'offset_count': 0,
                'source': source,
                'names': [],
                'codes': [],
            }
        item = candidates[bucket]
        item['score'] += sample_score['score']
        if source == 'actual-ceiling-offset':
            item['offset_count'] += 1
            item['source'] = source
        if ceiling.get('name') and ceiling.get('name') not in item['names']:
            item['names'].append(ceiling.get('name'))
        for code in ceiling.get('codes') or []:
            if code not in item['codes']:
                item['codes'].append(code)

    if not candidates:
        if rejected_names:
            return {
                'height': None,
                'source': 'upper-ceiling-candidates-only',
                'target_level': '',
                'slab_thickness': None,
                'raw_height': None,
                'ceiling_names': [],
                'ceiling_codes': [],
                'ceiling_unmarked_names': [],
                'rejected_ceiling_names': rejected_names,
                'rejected_ceiling_codes': rejected_codes,
                'warnings': [],
            }
        return None
    selected = sorted(
        candidates.values(),
        key=lambda item: (-item['score'], -item['offset_count'], item['height'])
    )[0]
    warnings = []
    if len(candidates) > 1:
        warnings.append(u'房間內命中多組實體天花高度，淨高採水平重疊面積最大的高度組')
    if rejected_names:
        warnings.append(u'另排除高於本房間上層樓板底的天花：{0}'.format(u'、'.join(rejected_names)))
    return {
        'height': selected['height'],
        'source': selected.get('source') or 'actual-ceiling-bottom',
        'target_level': '',
        'slab_thickness': None,
        'raw_height': selected['raw_height'],
        'ceiling_names': all_names,
        'ceiling_codes': all_codes,
        'ceiling_unmarked_names': unmarked_names,
        'rejected_ceiling_names': rejected_names,
        'rejected_ceiling_codes': rejected_codes,
        'warnings': warnings,
    }


def room_slab_bottom_height_info(room, height_context, base_elevation=None):
    if base_elevation is None:
        base_elevation = room_base_elevation_m(room, height_context)
    if base_elevation is None:
        return None
    top_entry = room_top_level_entry(room, height_context, base_elevation)
    if not top_entry:
        return None
    slab_thickness = height_context.get('thickness_by_level', {}).get(top_entry['key'])
    height = top_entry['elevation'] - base_elevation
    source = 'level-to-level-no-slab-thickness'
    warnings = [
        u'本來源模型找不到上層代表樓板厚度，淨高暫採同一來源模型的樓層到樓層高度'
    ]
    if slab_thickness:
        height -= slab_thickness
        source = 'level-to-upper-slab-bottom'
        warnings = []
    if not valid_height(height):
        return None
    return {
        'height': round_to_step(height, HEIGHT_BUCKET_SIZE_M),
        'source': source,
        'target_level': top_entry['name'] or top_entry['key'],
        'slab_thickness': slab_thickness,
        'raw_height': height,
        'ceiling_names': [],
        'ceiling_codes': [],
        'ceiling_unmarked_names': [],
        'rejected_ceiling_names': [],
        'rejected_ceiling_codes': [],
        'warnings': warnings,
    }


def room_height_info(room, height_context):
    base_elevation = room_base_elevation_m(room, height_context)
    slab_info = room_slab_bottom_height_info(room, height_context, base_elevation)

    max_ceiling_height = None
    if slab_info and slab_info.get('raw_height') is not None:
        max_ceiling_height = slab_info.get('raw_height') + CEILING_ABOVE_SLAB_TOLERANCE_M
    ceiling_info = ceiling_bottom_height_info(
        room,
        height_context,
        base_elevation,
        max_ceiling_height
    )
    if ceiling_info and valid_height(ceiling_info.get('height')):
        return ceiling_info

    if ceiling_info and ceiling_info.get('source') == 'upper-ceiling-candidates-only' and slab_info:
        result = dict(slab_info)
        result['source'] = 'upper-ceiling-rejected-to-slab-bottom'
        result['rejected_ceiling_names'] = ceiling_info.get('rejected_ceiling_names') or []
        result['rejected_ceiling_codes'] = ceiling_info.get('rejected_ceiling_codes') or []
        result['warnings'] = [u'偵測到同棟且 XY 重疊的上層天花，高於本房間上層樓板底，已排除並改用樓板底']
        return result

    if slab_info:
        return slab_info

    explicit = param_height_m(room, [], [u'天花淨高', u'淨高', 'Net Height'])
    if explicit:
        return {
            'height': round_to_step(explicit, HEIGHT_BUCKET_SIZE_M),
            'source': 'room-explicit-height-fallback',
            'target_level': '',
            'slab_thickness': None,
            'raw_height': explicit,
            'ceiling_names': [],
            'ceiling_codes': [],
            'ceiling_unmarked_names': [],
            'rejected_ceiling_names': [],
            'rejected_ceiling_codes': [],
            'warnings': [u'本來源模型無法取得實體天花或可用上層樓層，使用房間淨高參數'],
        }

    fallback = param_height_m(room, ['ROOM_HEIGHT'], [u'不連續高度', 'Unbounded Height'])
    if not fallback:
        box = element_box_tuple(room)
        if box:
            fallback = (box[5] - box[2]) * FT_TO_M
    if fallback and valid_height(fallback):
        return {
            'height': round_to_step(fallback, HEIGHT_BUCKET_SIZE_M),
            'source': 'room-revit-height',
            'target_level': '',
            'slab_thickness': None,
            'raw_height': fallback,
            'ceiling_names': [],
            'ceiling_codes': [],
            'ceiling_unmarked_names': [],
            'rejected_ceiling_names': [],
            'rejected_ceiling_codes': [],
            'warnings': [u'無法取得實體天花或上層樓板底，使用 Revit 房間高度'],
        }

    return {
        'height': None,
        'source': 'missing-height',
        'target_level': '',
        'slab_thickness': None,
        'raw_height': None,
        'ceiling_names': [],
        'ceiling_codes': [],
        'ceiling_unmarked_names': [],
        'rejected_ceiling_names': [],
        'rejected_ceiling_codes': [],
        'warnings': [u'無可用淨高來源'],
    }


def collect_family_symbols_by_name():
    result = {}
    for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
        family = getattr(symbol, 'Family', None)
        family_name = element_name(family)
        if not family_name:
            family_name = lookup_value(symbol, [u'族群名稱', 'Family Name'])
        if family_name:
            result.setdefault(family_name, []).append(symbol)
    return result


def family_choice_sort_key(name):
    text = clean(name)
    if text == u'AE-材料版':
        return (0, text)
    if u'材料' in text:
        return (1, text)
    return (2, text)


def choose_material_family(families=None):
    if families is None:
        families = collect_family_symbols_by_name()
    if not families:
        forms.alert(u'目前專案找不到可讀取的族群類型。', title=u'天花 Excel')
        return (None, {})
    options = sorted(families.keys(), key=family_choice_sort_key)
    selected = forms.SelectFromList.show(
        options,
        title=u'選擇材料版族群',
        button_name=u'讀取材料名稱',
        multiselect=False
    )
    return (selected, families)


def parameter_text_values(element):
    values = []
    if element is None:
        return values
    try:
        parameters = list(element.Parameters)
    except Exception:
        parameters = []
    for param in parameters:
        if not param or not param.HasValue:
            continue
        try:
            value = clean(param.AsString() or param.AsValueString())
        except Exception:
            value = ''
        if value:
            values.append(value)
    return values


def clean_material_name_from_text(text, code):
    value = clean(text)
    code_text = clean(code)
    if not value or not code_text:
        return ''
    pattern = re.compile(
        r'(^|[\s_/\\\-\(\[（【]){0}\s*[=＝:：\-]\s*(.+)$'.format(re.escape(code_text)),
        re.I
    )
    match = pattern.search(value)
    if match:
        return clean(match.group(2))
    pattern = re.compile(r'^\s*{0}\s*(.+)$'.format(re.escape(code_text)), re.I)
    match = pattern.match(value)
    if match:
        return clean(match.group(1).lstrip('=＝:：- '))
    return ''


def symbol_code_match(symbol, code):
    code_text = clean(code).upper()
    if not code_text:
        return False
    candidates = [
        element_name(symbol),
        param_text(symbol, ['ALL_MODEL_TYPE_MARK'], [u'類型標記', 'Type Mark']),
    ] + parameter_text_values(symbol)
    for candidate in candidates:
        text = clean(candidate).upper()
        if not text:
            continue
        if text == code_text:
            return True
        pattern = r'(^|[\s_/\\\-\(\[（【]){0}($|[\s=＝:：\-\)）\]】])'.format(re.escape(code_text))
        if re.search(pattern, text):
            return True
    return False


def material_name_from_symbol(symbol, code):
    type_name = element_name(symbol)
    name = clean_material_name_from_text(type_name, code)
    if name:
        return name
    for value in parameter_text_values(symbol):
        name = clean_material_name_from_text(value, code)
        if name:
            return name
    if symbol_code_match(symbol, code):
        for parameter_name in (u'描述', 'Description', u'類型備註', 'Type Comments', u'模型', 'Model'):
            value = lookup_value(symbol, [parameter_name])
            if value and value.upper() != clean(code).upper():
                return value
        return type_name
    return ''


def load_material_names_from_family(family_name, family_symbols, material_cols):
    symbols = family_symbols.get(family_name, [])
    result = {}
    for code in material_cols:
        for symbol in symbols:
            name = material_name_from_symbol(symbol, code)
            if name:
                result[clean(code).upper()] = name
                break
    return result


def collect_base_rooms():
    rooms = []
    collector = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()
    for room in collector:
        if not valid_room(room):
            continue
        if not room_is_in_active_level_scope(room):
            continue
        number = room_number(room)
        name = room_name(room, number)
        if not number and not name:
            continue
        try:
            area = room.Area * SQFT_TO_SQM
        except Exception:
            area = None
        rooms.append({
            'element': room,
            'element_id': element_id_value(room.Id),
            'number': number,
            'name': name,
            'level': level_name(room),
            'area': area,
            'ceiling_finish': room_ceiling_finish(room),
        })
    rooms.sort(key=lambda item: room_sort_key(item['number'], item['level']))
    return rooms


def build_room_code_areas(room_codes, actual_info, filled_info, room_area, warnings):
    if not room_codes:
        return {}
    result = {}
    physical = {}
    regions = {}
    for code, area in (actual_info.get('code_areas') or {}).items():
        if code in room_codes and area is not None and area > 0:
            physical[code] = physical.get(code, 0.0) + area
    for code, area in (filled_info.get('code_areas') or {}).items():
        if code in room_codes and area is not None and area > 0:
            regions[code] = regions.get(code, 0.0) + area

    for code, area in physical.items():
        result[code] = result.get(code, 0.0) + area

    missing_physical_codes = [
        code for code in room_codes
        if code not in physical
    ]
    physical_total = sum(physical.values())
    can_infer_residual = (
        len(missing_physical_codes) == 1 and
        bool(physical) and
        room_area is not None and
        physical_total < room_area - AREA_DIFF_WARN_TOLERANCE_M2 and
        set(room_codes) == set(list(physical.keys()) + missing_physical_codes)
    )
    if can_infer_residual:
        drawing_code = missing_physical_codes[0]
        residual = room_area - physical_total
        result[drawing_code] = residual
    else:
        for code, area in regions.items():
            result[code] = result.get(code, 0.0) + area

    actual_area = actual_info.get('area')
    if not result and len(room_codes) == 1:
        fallback_area = actual_area if actual_area is not None else room_area
        if fallback_area is not None and fallback_area > 0:
            result[room_codes[0]] = fallback_area

    if result and room_area is not None:
        total = sum(result.values())
        if total > room_area + AREA_DIFF_WARN_TOLERANCE_M2:
            overflow = total - room_area
            for code in sorted(physical, key=lambda item: physical[item], reverse=True):
                reducible = min(physical.get(code, 0.0), overflow)
                result[code] = max(0.0, result.get(code, 0.0) - reducible)
                overflow -= reducible
                if overflow <= AREA_DIFF_WARN_TOLERANCE_M2:
                    break
            if overflow > AREA_DIFF_WARN_TOLERANCE_M2:
                for code in sorted(regions, key=lambda item: regions[item], reverse=True):
                    reducible = min(result.get(code, 0.0), overflow)
                    result[code] = max(0.0, result.get(code, 0.0) - reducible)
                    overflow -= reducible
                    if overflow <= AREA_DIFF_WARN_TOLERANCE_M2:
                        break
            warnings.append(
                u'天花材料分區合計超過 Room 面積，已把總量限制在 {0} m²'.format(fixed2(room_area))
            )

    result = dict((code, area) for code, area in result.items()
                  if area is not None and area > MIN_CLIPPED_AREA_M2)
    if len(room_codes) > 1:
        missing = [code for code in room_codes if code not in result]
        if missing:
            warnings.append(
                u'房間有多重天花代碼，但缺少 {0} 的可分區面積證據；該材料欄不自動填入整間面積'.format(
                    '+'.join(missing)
                )
            )
    return result


def collect_data():
    rooms = collect_base_rooms()
    height_context = build_height_context()
    material_codes = set()
    height_sources = {}
    missing_finish = 0
    rooms_with_code = 0
    code_mismatch_rooms = []
    code_mismatch_details = []
    actual_ceiling_without_code = []
    room_code_missing_with_actual = []
    upper_ceiling_rejected_rooms = []
    actual_ceiling_area_rooms = 0
    room_area_fallback_rooms = 0
    vertically_rejected_ceilings = 0
    area_sources = {}
    filled_region_rooms = 0
    mixed_ceiling_rooms = []

    for room in rooms:
        codes = ceiling_finish_codes(room.get('ceiling_finish'))
        height_info = room_height_info(room['element'], height_context)
        actual_info = room_actual_ceiling_info(room['element'], height_context, codes)
        filled_info = room_filled_region_info(room['element'], height_context)
        vertically_rejected_ceilings += actual_info.get('vertically_rejected_count', 0)
        warnings = list(height_info.get('warnings') or [])
        warnings.extend(actual_info.get('warnings') or [])
        warnings.extend(filled_info.get('warnings') or [])
        actual_ceiling_used = actual_info.get('match_count', 0) > 0
        ceiling_codes = actual_info.get('ceiling_codes') or height_info.get('ceiling_codes') or []
        filled_region_codes = filled_info.get('codes') or []
        evidence_codes = list(ceiling_codes)
        append_unique(evidence_codes, filled_region_codes)
        residual_inferred_codes = []
        physical_code_areas = actual_info.get('code_areas') or {}
        physical_codes_in_room = [
            code for code in codes
            if physical_code_areas.get(code) is not None and physical_code_areas.get(code) > 0
        ]
        missing_physical_codes = [
            code for code in codes
            if code not in physical_codes_in_room
        ]
        physical_total_for_room_codes = sum([
            physical_code_areas.get(code, 0.0) for code in physical_codes_in_room
        ])
        if (len(codes) > 1 and len(missing_physical_codes) == 1 and
                physical_codes_in_room and room.get('area') is not None and
                physical_total_for_room_codes < room.get('area') - AREA_DIFF_WARN_TOLERANCE_M2):
            residual_inferred_codes = list(missing_physical_codes)
        evidence_codes_for_compare = list(evidence_codes)
        append_unique(evidence_codes_for_compare, residual_inferred_codes)
        if filled_info.get('match_count', 0) > 0:
            filled_region_rooms += 1
        if actual_ceiling_used and filled_region_codes:
            mixed_ceiling_rooms.append(room['number'])
            warnings.append(
                u'混合天花：實體天花 {0}；圖面填滿範圍 {1}'.format(
                    '+'.join(ceiling_codes) or u'未編碼',
                    '+'.join(filled_region_codes)
                )
            )
        if residual_inferred_codes and room['number'] not in mixed_ceiling_rooms:
            mixed_ceiling_rooms.append(room['number'])
        ceiling_unmarked_names = actual_info.get('ceiling_unmarked_names') or height_info.get('ceiling_unmarked_names') or []
        rejected_ceiling_names = height_info.get('rejected_ceiling_names') or []
        height_source = height_info.get('source') or 'unknown'
        code_status = ''
        quantity_area = room.get('area')
        quantity_area_source = 'room-area'

        if actual_info.get('area') is not None:
            quantity_area = actual_info.get('area')
            quantity_area_source = actual_info.get('area_source') or 'actual-ceiling-area'
            actual_ceiling_area_rooms += 1
            if room.get('area') is not None:
                if note_area_diff_significant(quantity_area, room.get('area')):
                    warnings.append(
                        u'天花面積採實體天花 {0} m²；Room 面積 {1} m²僅供比對'.format(
                            fixed2(quantity_area),
                            fixed2(room.get('area'))
                        )
                    )
        else:
            room_area_fallback_rooms += 1
        has_code_evidence = actual_ceiling_used or filled_info.get('match_count', 0) > 0
        if (not actual_ceiling_used and filled_info.get('match_count', 0) > 0 and
                note_area_diff_significant(filled_info.get('area'), room.get('area'))):
            warnings.append(
                u'僅命中天花圖面填滿範圍，面積 {0} m² 與 Room 面積 {1} m² 差異較大，請確認圖面範圍或房間邊界'.format(
                    fixed2(filled_info.get('area')),
                    fixed2(room.get('area'))
                )
            )

        if not codes:
            missing_finish += 1
            if has_code_evidence:
                room_code_missing_with_actual.append(room['number'])
                if evidence_codes:
                    code_status = u'房間需填 C 代碼'
                    warnings.append(u'房間天花板塗層未填；天花證據為 {0}，請回填房間參數後再匯出數量'.format(
                        '+'.join(evidence_codes)
                    ))
                else:
                    code_status = u'房間與天花證據皆未編碼'
                    actual_ceiling_without_code.append(room['number'])
                    warnings.append(u'房間天花板塗層未填，命中的天花證據也沒有 C 代碼')
            else:
                code_status = u'房間未填 C 代碼'
        else:
            rooms_with_code += 1
            for code in codes:
                material_codes.add(code)
            if has_code_evidence:
                if not evidence_codes_for_compare:
                    code_status = u'天花證據未辨識 C 代碼'
                    actual_ceiling_without_code.append(room['number'])
                    warnings.append(u'材料欄依房間天花板塗層；本房間命中的實體／圖面天花未辨識到 C 代碼，請核對材料標記、類型名稱或圖面標註')
                elif set(codes) != set(evidence_codes_for_compare):
                    code_status = u'需更改'
                    code_mismatch_rooms.append(room['number'])
                    code_mismatch_details.append({
                        'room': room['number'] or room['name'],
                        'room_codes': list(codes),
                        'ceiling_codes': list(ceiling_codes),
                        'filled_region_codes': list(filled_region_codes),
                        'evidence_codes': list(evidence_codes_for_compare),
                    })
                    warnings.append(
                        u'房間天花板塗層為 {0}，實體／圖面天花證據為 {1}；材料欄依房間參數，請修正模型或圖面'.format(
                            '+'.join(codes),
                            '+'.join(evidence_codes_for_compare)
                        )
                    )
                else:
                    code_status = u'反推' if residual_inferred_codes else u'一致'
                if ceiling_unmarked_names:
                    if room['number'] not in actual_ceiling_without_code:
                        actual_ceiling_without_code.append(room['number'])
                    warnings.append(u'房間內另有實體天花未辨識到 C 代碼：{0}'.format(
                        u'、'.join(ceiling_unmarked_names)
                    ))
            if not actual_ceiling_used:
                if not code_status:
                    code_status = u'無本房間有效實體天花'
                    if filled_region_codes:
                        code_status = u'僅有圖面填滿範圍'
                if height_source == 'level-to-upper-slab-bottom':
                    warnings.append(u'房間天花板塗層有 C 代碼，但本房間未命中有效實體天花，淨高改用上層樓板底')

        quantity_by_code = build_room_code_areas(
            codes,
            actual_info,
            filled_info,
            room.get('area'),
            warnings
        )
        if quantity_by_code:
            quantity_area = sum(quantity_by_code.values())
            if residual_inferred_codes and actual_ceiling_used:
                quantity_area_source = 'actual-ceiling-residual-room-area'
            elif filled_region_codes and actual_ceiling_used:
                quantity_area_source = 'actual-ceiling-and-filled-region'
            elif filled_region_codes:
                quantity_area_source = 'filled-region-room-intersection'
        area_sources[quantity_area_source] = area_sources.get(quantity_area_source, 0) + 1

        if height_source == 'upper-ceiling-rejected-to-slab-bottom':
            upper_ceiling_rejected_rooms.append(room['number'])

        source = height_source
        height_sources[source] = height_sources.get(source, 0) + 1
        room.update({
            'codes': codes,
            'eligible_codes': codes,
            'quantity_area': quantity_area,
            'quantity_area_source': quantity_area_source,
            'height': height_info.get('height'),
            'height_source': source,
            'height_target_level': height_info.get('target_level') or '',
            'slab_thickness': height_info.get('slab_thickness'),
            'ceiling_names': actual_info.get('ceiling_names') or height_info.get('ceiling_names') or [],
            'ceiling_codes': ceiling_codes,
            'filled_region_codes': filled_region_codes,
            'filled_region_details': filled_info.get('details') or [],
            'residual_inferred_codes': residual_inferred_codes,
            'quantity_by_code': quantity_by_code,
            'ceiling_unmarked_names': ceiling_unmarked_names,
            'rejected_ceiling_names': rejected_ceiling_names,
            'ceiling_code_status': code_status,
            'main_warnings': main_note_warnings(warnings),
            'warnings': warnings,
        })

    material_cols = sorted(list(material_codes), key=finish_sort_key)
    stats = {
        'rooms': len(rooms),
        'rooms_with_code': rooms_with_code,
        'missing_ceiling_finish': missing_finish,
        'ceiling_finish_types': len(material_cols),
        'ceilings': len(height_context.get('ceilings', [])),
        'slab_levels': len(height_context.get('thickness_by_level', {})),
        'height_sources': height_sources,
        'ceiling_code_mismatch_rooms': code_mismatch_rooms,
        'ceiling_code_mismatch_details': code_mismatch_details,
        'actual_ceiling_without_code': actual_ceiling_without_code,
        'room_code_missing_with_actual': room_code_missing_with_actual,
        'upper_ceiling_rejected_rooms': upper_ceiling_rejected_rooms,
        'actual_ceiling_area_rooms': actual_ceiling_area_rooms,
        'room_area_fallback_rooms': room_area_fallback_rooms,
        'vertically_rejected_ceilings': vertically_rejected_ceilings,
        'area_sources': area_sources,
        'ceiling_drawing_views': height_context.get('ceiling_drawing_view_count', 0),
        'filled_regions': len(height_context.get('filled_regions', [])),
        'filled_region_rooms': filled_region_rooms,
        'mixed_ceiling_rooms': mixed_ceiling_rooms,
    }
    return rooms, material_cols, stats


def excel_col(index):
    result = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def make_rows(rooms, material_cols):
    full = full_layout(material_cols)
    rows = []
    for row_offset, room in enumerate(rooms):
        row_number = FIRST_DATA_ROW + row_offset
        row = full.blank_row()
        full.put(row, 'room_no', room['number'])
        full.put(row, 'room_name', room['name'])
        full.put(row, 'quantity_area',
                 room.get('quantity_area')
                 if room.get('quantity_area') is not None else '')
        quantity_by_code = room.get('quantity_by_code') or {}
        for code in room.get('eligible_codes') or []:
            if code not in material_cols:
                continue
            area = quantity_by_code.get(code)
            if area is None or area <= MIN_CLIPPED_AREA_M2:
                continue
            if (len(quantity_by_code) == 1 and
                    abs(area - (room.get('quantity_area') or 0.0)) <= AREA_DIFF_WARN_TOLERANCE_M2):
                full.put(row, code,
                         SUMMARY_LAYOUT.formula(row_number,
                                                '{quantity_area}'))
            else:
                full.put(row, code, round2(area))
        drawing_sources = (
            [room.get('source_label')]
            if room.get('source_label') else [])
        for detail in room.get('filled_region_details') or []:
            append_unique(drawing_sources, detail.get('sources') or [])
        full.put(row, DRAWING_COLUMN, u'；'.join(drawing_sources))
        full.put(row, NOTES_COLUMN,
                 u'；'.join(room.get('main_warnings') or []))
        rows.append(row)
    return rows


def build_summary_row(data_row_count, material_cols):
    full = full_layout(material_cols)
    row = full.row_from({'room_no': SUMMARY_LABEL})
    last_data_row = FIRST_DATA_ROW + data_row_count - 1
    for material in material_cols:
        # 每一欄加的是自己那一欄。以前這裡是 excel_col(FIXED + index + 1)，
        # 一個 +1 就會讓總計加到隔壁去，而且不會報錯。
        full.put(row, material,
                 full.sum_of(material, FIRST_DATA_ROW, last_data_row)
                 if data_row_count > 0 else '=0')
    return row


def build_sheet_values(rows, material_cols, project_title, material_names):
    total_cols = FIXED_REPORT_COLS + len(material_cols) + TRAILING_REPORT_COLS
    drawing_col = total_cols - 2
    notes_col = total_cols - 1
    values = []

    row = [''] * total_cols
    row[0] = u'工程採購數量計算表'
    values.append(row)

    row = [''] * total_cols
    row[0] = project_title
    values.append(row)

    row = [''] * total_cols
    row[0] = u'天花數量計算表'
    values.append(row)

    full = full_layout(material_cols)

    row = full.row_from({'room_no': u'工程項目',
                         DRAWING_COLUMN: u'對應\n圖說',
                         NOTES_COLUMN: u'備註'})
    if material_cols:
        full.put(row, material_cols[0], u'天花')
    values.append(row)

    row = full.row_from({'room_no': u'材料編號'})
    for code in material_cols:
        full.put(row, code, code)
    values.append(row)

    row = full.row_from({'room_no': u'材料名稱'})
    for code in material_cols:
        full.put(row, code, material_names.get(clean(code).upper(), ''))
    values.append(row)

    values.append(list(SUMMARY_HEADERS)
                  + [''] * (len(material_cols) + TRAILING_REPORT_COLS))

    values.extend(rows)
    values.append(build_summary_row(len(rows), material_cols))
    return values


def height_source_label(source):
    labels = {
        'actual-ceiling-offset': u'實體天花：距樓層高度偏移',
        'actual-ceiling-bbox': u'實體天花：幾何底面',
        'actual-ceiling-bottom': u'實體天花：底面',
        'level-to-upper-slab-bottom': u'基準樓層至上層樓板底',
        'level-to-level-no-slab-thickness': u'同來源模型樓層到樓層（無樓板厚度）',
        'upper-ceiling-rejected-to-slab-bottom': u'排除上層天花後採上層樓板底',
        'room-explicit-height-fallback': u'房間淨高參數備援',
        'room-revit-height': u'Revit 房間高度備援',
        'missing-height': u'缺少淨高',
    }
    return labels.get(source, clean(source))


def area_source_label(source):
    labels = {
        'actual-ceiling-room-clipped-area': u'實體天花與房間邊界幾何交集',
        'actual-ceiling-room-clipped-with-estimate': u'實體天花幾何交集＋受限估算',
        'actual-ceiling-estimated-area': u'房間內覆蓋估算（不超過 Room 面積）',
        'actual-ceiling-contained-element-area': u'幾乎完整位於房間內的 Revit 實體天花面積',
        'actual-ceiling-area': u'實體天花面積',
        'actual-ceiling-residual-room-area': u'實體天花＋Room 剩餘面積反推',
        'actual-ceiling-and-filled-region': u'實體天花＋天花圖面填滿範圍分區',
        'filled-region-room-intersection': u'天花圖面填滿範圍與 Room 幾何交集',
        'room-area': u'Room 面積備援',
    }
    return labels.get(source, clean(source))


def build_audit_values(rooms):
    values = [[
        u'編號',
        u'空間名稱',
        u'樓層',
        u'房間 C 代碼',
        u'實體天花 C 代碼',
        u'反推 C 代碼',
        u'代碼檢核',
        u'填入天花數量',
        u'數量面積(m²)',
        u'面積來源',
        u'淨高(m)',
        u'高度來源',
        u'實體天花類型',
        u'填滿範圍來源',
        u'排除的上層天花',
        u'上層樓層',
        u'樓板厚度(m)',
        u'備註',
    ]]
    for room in rooms:
        values.append([
            room['number'],
            room['name'],
            room['level'],
            '+'.join(room.get('codes') or []),
            '+'.join(room.get('ceiling_codes') or []),
            '+'.join(room.get('residual_inferred_codes') or []),
            room.get('ceiling_code_status') or '',
            u'是' if room.get('eligible_codes') else u'否',
            fixed2(room.get('quantity_area')),
            area_source_label(room.get('quantity_area_source')),
            fixed2(room.get('height')),
            height_source_label(room.get('height_source')),
            u'、'.join(room.get('ceiling_names') or []),
            u'；'.join([
                u'{0} {1} m² [Id {2}；{3}]'.format(
                    '+'.join(detail.get('codes') or []) or detail.get('type_name') or '',
                    fixed2(detail.get('area')),
                    detail.get('id'),
                    u'、'.join(detail.get('sources') or [])
                )
                for detail in room.get('filled_region_details') or []
            ]),
            u'、'.join(room.get('rejected_ceiling_names') or []),
            room.get('height_target_level') or '',
            fixed2(room.get('slab_thickness')),
            u'；'.join(room.get('warnings') or []),
        ])
    return values


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


def main_cell_xml(row_index, col_index, value, summary_row_index, total_cols):
    ref = '{0}{1}'.format(excel_col(col_index), row_index)
    text = clean(value)
    style = ''
    if summary_row_index and row_index == summary_row_index:
        if FIXED_REPORT_COLS + 1 <= col_index <= total_cols - TRAILING_REPORT_COLS:
            style = ' s="5"'
        else:
            style = ' s="2"'
    elif row_index == 1:
        style = ' s="7"'
    elif row_index in (2, 3):
        style = ' s="8"'
    elif row_index <= 7:
        style = ' s="1"'
    elif row_index >= FIRST_DATA_ROW:
        if col_index >= total_cols - TRAILING_REPORT_COLS + 1:
            style = ' s="6"'
        elif 3 <= col_index <= total_cols - TRAILING_REPORT_COLS:
            style = ' s="3"'
    if value is None or value == '':
        return '<c r="{0}"{1}/>'.format(ref, style)
    if text.startswith('='):
        return '<c r="{0}"{1}><f>{2}</f></c>'.format(ref, style, xml_escape(text[1:]))
    if is_number(value):
        return '<c r="{0}"{1}><v>{2}</v></c>'.format(ref, style, clean(value))
    return '<c r="{0}"{1} t="inlineStr"><is><t>{2}</t></is></c>'.format(
        ref,
        style,
        xml_escape(text)
    )


def main_sheet_xml(values):
    total_cols = len(values[0]) if values else 1
    drawing_col = total_cols - 1
    notes_col = total_cols
    summary_row_index = None
    for row_index, row in enumerate(values, start=1):
        if row and row[0] == SUMMARY_LABEL:
            summary_row_index = row_index
            break

    rows_xml = []
    for row_index, row in enumerate(values, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            cell = main_cell_xml(row_index, col_index, value, summary_row_index, total_cols)
            if cell:
                cells.append(cell)
        row_attrs = ' r="{0}"'.format(row_index)
        if row_index == 6:
            row_attrs += ' ht="30" customHeight="1"'
        rows_xml.append('<row{0}>{1}</row>'.format(row_attrs, ''.join(cells)))

    # 欄位範圍一律問 layout，不寫死字母
    first_col = SUMMARY_LAYOUT.col(SUMMARY_COLUMNS[0])
    last_fixed_col = SUMMARY_LAYOUT.col(SUMMARY_COLUMNS[-1])
    last_col = sheet_layout.column_letter(total_cols - 1)
    merge_refs = [
        '{0}1:{1}1'.format(first_col, last_col),
        '{0}2:{1}2'.format(first_col, last_col),
        '{0}3:{1}3'.format(first_col, last_col),
        '{0}4:{1}4'.format(first_col, last_fixed_col),
        '{0}5:{1}5'.format(first_col, last_fixed_col),
        '{0}6:{1}6'.format(first_col, last_fixed_col),
        '{0}4:{0}7'.format(excel_col(drawing_col)),
        '{0}4:{0}7'.format(excel_col(notes_col)),
    ]
    material_end = total_cols - TRAILING_REPORT_COLS
    if material_end > FIXED_REPORT_COLS + 1:
        merge_refs.append('{0}4:{1}4'.format(
            excel_col(FIXED_REPORT_COLS + 1),
            excel_col(material_end)
        ))
    if summary_row_index:
        merge_refs.append('{0}{1}:{2}{1}'.format(
            first_col, summary_row_index, last_fixed_col))
    merge_xml = '<mergeCells count="{0}">{1}</mergeCells>'.format(
        len(merge_refs),
        ''.join(['<mergeCell ref="{0}"/>'.format(ref) for ref in merge_refs])
    )

    material_start = FIXED_REPORT_COLS + 1
    col_defs = [
        '<col min="1" max="1" width="11" customWidth="1"/>',
        '<col min="2" max="2" width="24" customWidth="1"/>',
        '<col min="3" max="3" width="13" customWidth="1"/>',
    ]
    if material_end >= material_start:
        col_defs.append('<col min="{0}" max="{1}" width="20" customWidth="1"/>'.format(
            material_start,
            material_end
        ))
    col_defs.append('<col min="{0}" max="{0}" width="34" customWidth="1"/>'.format(drawing_col))
    col_defs.append('<col min="{0}" max="{0}" width="72" customWidth="1"/>'.format(notes_col))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<dimension ref="A1:{0}{1}"/>'  # sheet-layout: ignore（A1 是工作表原點，恆定）
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="7" topLeftCell="A8" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        '<cols>{2}</cols><sheetData>{3}</sheetData>{4}'
        '</worksheet>'
    ).format(excel_col(total_cols), len(values), ''.join(col_defs), ''.join(rows_xml), merge_xml)


def audit_cell_xml(row_index, col_index, value):
    ref = '{0}{1}'.format(excel_col(col_index), row_index)
    text = clean(value)
    style = ' s="1"' if row_index == 1 else ''
    if row_index > 1 and col_index in (9, 11, 17):
        style = ' s="4"'
    if value is None or value == '':
        return '<c r="{0}"{1}/>'.format(ref, style)
    if is_number(value):
        return '<c r="{0}"{1}><v>{2}</v></c>'.format(ref, style, clean(value))
    return '<c r="{0}"{1} t="inlineStr"><is><t>{2}</t></is></c>'.format(
        ref,
        style,
        xml_escape(text)
    )


def audit_sheet_xml(values):
    total_cols = len(values[0]) if values else 1
    rows_xml = []
    for row_index, row in enumerate(values, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            cell = audit_cell_xml(row_index, col_index, value)
            if cell:
                cells.append(cell)
        rows_xml.append('<row r="{0}">{1}</row>'.format(row_index, ''.join(cells)))
    col_widths = [11, 22, 12, 14, 18, 18, 16, 14, 12, 30, 12, 34, 34, 52, 24, 14, 14, 52]
    col_defs = []
    for index, width in enumerate(col_widths, start=1):
        col_defs.append('<col min="{0}" max="{0}" width="{1}" customWidth="1"/>'.format(index, width))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<dimension ref="A1:{0}{1}"/>'  # sheet-layout: ignore（A1 是工作表原點，恆定）
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        '<cols>{2}</cols><sheetData>{3}</sheetData>'
        '<autoFilter ref="A1:{0}{1}"/>'  # sheet-layout: ignore（A1 是工作表原點，恆定）
        '</worksheet>'
    ).format(excel_col(total_cols), len(values), ''.join(col_defs), ''.join(rows_xml))


def write_zip_entry(archive, name, content):
    entry = archive.CreateEntry(name)
    stream = entry.Open()
    writer = StreamWriter(stream, Encoding.UTF8)
    writer.Write(content)
    writer.Close()
    stream.Close()


def write_xlsx(path, main_values, audit_values):
    fs = FileStream(path, FileMode.Create, FileAccess.ReadWrite)
    archive = ZipArchive(fs, ZipArchiveMode.Create)
    try:
        write_zip_entry(
            archive,
            '[Content_Types].xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '</Types>'
        )
        write_zip_entry(
            archive,
            '_rels/.rels',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'
        )
        write_zip_entry(
            archive,
            'xl/_rels/workbook.xml.rels',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>'
        )
        write_zip_entry(
            archive,
            'xl/workbook.xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets>'
            '<sheet name="天花數量計算" sheetId="1" r:id="rId1"/>'
            '<sheet name="高度檢核" sheetId="2" r:id="rId2"/>'
            '</sheets>'
            '<calcPr calcMode="auto" fullCalcOnLoad="1" forceFullCalc="1"/>'
            '</workbook>'
        )
        write_zip_entry(
            archive,
            'xl/styles.xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<numFmts count="2">'
            '<numFmt numFmtId="164" formatCode="0.00 &quot;㎡&quot;"/>'
            '<numFmt numFmtId="165" formatCode="0.00 &quot;m&quot;"/>'
            '</numFmts>'
            + takeoff_excel_styles.FONTS_XML
            + takeoff_excel_styles.FILLS_XML
            + takeoff_excel_styles.BORDERS_XML
            + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="9">'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center" wrapText="1"/>'
            '</xf>'
            '<xf numFmtId="0" fontId="4" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/>'
            '</xf>'
            '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
            '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
            '<xf numFmtId="164" fontId="4" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/>'
            '</xf>'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
            '<alignment horizontal="left" vertical="top" wrapText="1"/>'
            '</xf>'
            '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center" wrapText="1"/>'
            '</xf>'
            '<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center" wrapText="1"/>'
            '</xf>'
            '</cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            '</styleSheet>'
        )
        write_zip_entry(archive, 'xl/worksheets/sheet1.xml', main_sheet_xml(main_values))
        write_zip_entry(archive, 'xl/worksheets/sheet2.xml', audit_sheet_xml(audit_values))
    finally:
        archive.Dispose()
        fs.Close()


def safe_filename(text):
    value = re.sub(r'[\\/:*?"<>|]+', '_', clean(text))
    return value or 'Revit'


def alert_list_preview(values, limit=12):
    items = [clean(value) for value in values if clean(value)]
    if len(items) <= limit:
        return u'\n'.join(items)
    return u'{0}\n…另 {1} 筆，請查看「高度檢核」工作表'.format(
        u'\n'.join(items[:limit]),
        len(items) - limit
    )


def revit_file_title():
    path_name = clean(getattr(doc, 'PathName', ''))
    if path_name:
        base = os.path.basename(path_name)
        title = os.path.splitext(base)[0]
        if title:
            return title
    title = clean(getattr(doc, 'Title', ''))
    if title.lower().endswith('.rvt'):
        title = os.path.splitext(title)[0]
    return title or 'Revit'


def collect_family_symbols_for_documents(documents):
    global doc
    previous_doc = doc
    combined = {}
    try:
        for source_doc in documents:
            doc = source_doc
            for family_name, symbols in collect_family_symbols_by_name().items():
                combined.setdefault(family_name, []).extend(symbols)
    finally:
        doc = previous_doc
    return combined


def collect_selected_sources(host_doc, options):
    global doc
    global ACTIVE_ALLOWED_LEVEL_IDS
    all_rooms = []
    all_material_cols = set()
    all_stats = {}
    sources = list(takeoff_entry.iter_sources(host_doc, options))
    previous_doc = doc
    previous_levels = ACTIVE_ALLOWED_LEVEL_IDS
    try:
        for (source_key, source_label, source_doc,
             allowed_level_ids, unused_link_instance_id) in sources:
            doc = source_doc
            ACTIVE_ALLOWED_LEVEL_IDS = allowed_level_ids
            rooms, material_cols, stats = collect_data()
            for label_key in (
                    'ceiling_code_mismatch_rooms',
                    'actual_ceiling_without_code',
                    'room_code_missing_with_actual',
                    'upper_ceiling_rejected_rooms',
                    'mixed_ceiling_rooms'):
                stats[label_key] = [
                    u'{0} / {1}'.format(source_label, value)
                    for value in stats.get(label_key) or []
                ]
            for detail in stats.get(
                    'ceiling_code_mismatch_details') or []:
                detail['room'] = u'{0} / {1}'.format(
                    source_label, detail.get('room') or '')
            rooms, unused_related = (
                takeoff_direct_publish.rekey_room_records(
                    source_key, source_label, rooms))
            all_rooms.extend(rooms)
            all_material_cols.update(material_cols)
            takeoff_direct_publish.merge_stats(all_stats, stats)
    finally:
        doc = previous_doc
        ACTIVE_ALLOWED_LEVEL_IDS = previous_levels
    material_cols = sorted(list(all_material_cols), key=finish_sort_key)
    all_rooms.sort(key=lambda room: (
        clean(room.get('source_label')),
        room_sort_key(room.get('number'), room.get('level'))))
    all_stats['rooms'] = len(all_rooms)
    all_stats['ceiling_finish_types'] = len(material_cols)
    return all_rooms, material_cols, all_stats, sources


def main():
    if not doc:
        forms.alert(u'請先開啟 Revit 專案檔，再匯出天花 Excel。', title=u'天花 Excel')
        return

    host_doc = doc
    options = takeoff_entry.choose_options(
        host_doc, u'天花 Excel', allow_host=True, host_required=False)
    if options is None:
        return
    sources = list(takeoff_entry.iter_sources(host_doc, options))
    family_symbols = collect_family_symbols_for_documents(
        [source[2] for source in sources])
    selected_family, family_symbols = choose_material_family(family_symbols)
    if selected_family is None:
        return

    rooms, material_cols, stats, sources = collect_selected_sources(
        host_doc, options)

    project_title = revit_file_title()
    material_names = load_material_names_from_family(selected_family, family_symbols, material_cols)
    rows = make_rows(rooms, material_cols)
    main_values = build_sheet_values(rows, material_cols, project_title, material_names)
    audit_values = build_audit_values(rooms)
    workbook_path = options.get('workbook_path')
    publish_result = None
    if workbook_path:
        temp_path = takeoff_direct_publish.new_temp_xlsx_path()
        try:
            write_xlsx(temp_path, main_values, audit_values)
            publish_result = (
                takeoff_direct_publish.publish_generated_workbook(
                    workbook_path,
                    temp_path,
                    [
                        (u'天花數量計算', u'天花'),
                        u'高度檢核',
                    ],
                    summary_specs={
                        u'天花': {
                            'label': SUMMARY_LABEL,
                            'header_label': u'材料編號',
                            'data_header_label': u'空間名稱',
                        },
                    }))
            outpath = workbook_path
        except takeoff_direct_publish.WorkbookPublishError as exc:
            forms.alert(
                u'更新主要 Excel 失敗：\n{0}'.format(exc),
                title=u'天花 Excel')
            return
        finally:
            takeoff_direct_publish.remove_file_quietly(temp_path)
    else:
        default_name = safe_filename(project_title) + u'_天花數量計算.xlsx'
        outpath = forms.save_file(
            file_ext='xlsx',
            default_name=default_name,
            title=u'匯出天花數量計算 Excel'
        )
        if not outpath:
            return
        if not outpath.lower().endswith('.xlsx'):
            outpath += '.xlsx'
        write_xlsx(outpath, main_values, audit_values)

    action_label = u'更新' if workbook_path else u'匯出'
    output.print_md(u'## 天花 Excel {0}完成'.format(action_label))
    output.print_md(u'- 版本：`{0}`'.format(SCRIPT_VERSION))
    output.print_md(u'- 檔案：`{0}`'.format(outpath))
    output.print_md(u'- Revit 來源：{0}'.format(len(sources)))
    if publish_result:
        output.print_md(u'- 備份：`{0}`'.format(
            publish_result.get('backup_path')))
    output.print_md(u'- Rooms：{0}（全部有效房間皆列出）'.format(stats['rooms']))
    output.print_md(u'- 直接讀取 Room「天花板塗層」：有 C 代碼 {0}，空白或 - {1}'.format(
        stats['rooms_with_code'],
        stats['missing_ceiling_finish']
    ))
    output.print_md(u'- C 材料欄：{0}；材料版命中：{1}；材料版族群：{2}'.format(
        stats['ceiling_finish_types'],
        len(material_names),
        selected_family
    ))
    output.print_md(u'- 面積來源：實體天花 {0} 間，Room 面積回退 {1} 間'.format(
        stats.get('actual_ceiling_area_rooms', 0),
        stats.get('room_area_fallback_rooms', 0)
    ))
    area_sources = stats.get('area_sources', {})
    output.print_md(u'- 實體天花面積方法：房間邊界幾何裁切 {0} 間，含估算 {1} 間，純估算 {2} 間'.format(
        area_sources.get('actual-ceiling-room-clipped-area', 0),
        area_sources.get('actual-ceiling-room-clipped-with-estimate', 0),
        area_sources.get('actual-ceiling-estimated-area', 0)
    ))
    output.print_md(u'- 垂直重疊排除：{0} 筆其他樓層／更高天花候選未納入房間面積'.format(
        stats.get('vertically_rejected_ceilings', 0)
    ))
    output.print_md(u'- 填滿範圍面積掃描：停用；混合天花改採 Room 面積扣除實體天花面積反推')
    if stats.get('mixed_ceiling_rooms'):
        output.print_md(u'- 混合天花剩餘面積反推房間：{0}'.format(
            u'、'.join(stats.get('mixed_ceiling_rooms') or [])
        ))
    output.print_md(u'- 實體／反推天花代碼檢核：不一致 {0}，未辨識 C 代碼 {1}'.format(
        len(stats.get('ceiling_code_mismatch_rooms', [])),
        len(stats.get('actual_ceiling_without_code', []))
    ))
    for detail in stats.get('ceiling_code_mismatch_details', []):
        output.print_md(u'  - {0}：Room {1} / 實體 {2}，請修正模型'.format(
            detail['room'],
            '+'.join(detail['room_codes']),
            '+'.join(detail.get('ceiling_codes') or []) or u'無'
        ))
    if stats.get('room_code_missing_with_actual'):
        output.print_md(u'- 命中實體天花但 Room「天花板塗層」未填：{0}（未填入數量）'.format(
            u'、'.join(stats['room_code_missing_with_actual'])
        ))
    if stats.get('upper_ceiling_rejected_rooms'):
        output.print_md(u'- 排除上層天花、改採上層樓板底：{0}'.format(
            u'、'.join(stats['upper_ceiling_rejected_rooms'])
        ))
    output.print_md(u'- 淨高來源（詳見「高度檢核」工作表）：')
    for source, count in sorted(stats.get('height_sources', {}).items()):
        output.print_md(u'  - `{0}`：{1}'.format(source, count))
    output.print_md(u'- 實體 Ceilings：{0}；可用樓板厚度樓層：{1}'.format(
        stats['ceilings'],
        stats['slab_levels']
    ))
    mismatch_count = len(stats.get('ceiling_code_mismatch_rooms', []))
    missing_room_code_count = len(stats.get('room_code_missing_with_actual', []))
    alert_lines = [u'天花 Excel {0}完成。'.format(action_label)]
    if mismatch_count:
        mismatch_alert_items = []
        for detail in stats.get('ceiling_code_mismatch_details', []):
            mismatch_alert_items.append(u'{0}（Room {1} / 實體 {2}）'.format(
                detail['room'],
                '+'.join(detail['room_codes']),
                '+'.join(detail.get('ceiling_codes') or []) or u'無'
            ))
        alert_lines.append(
            u'偵測到 {0} 間房間的實體天花證據與 Room「天花板塗層」不一致。'
            u'材料欄仍以 Room 參數為主，請修正模型。\n{1}'.format(
                mismatch_count,
                alert_list_preview(mismatch_alert_items)
            )
        )
    if missing_room_code_count:
        alert_lines.append(
            u'另有 {0} 間房間命中實體天花，但 Room「天花板塗層」未填，'
            u'本次未填入數量。請回填房間參數後重新匯出。\n房間：{1}'.format(
                missing_room_code_count,
                alert_list_preview(stats['room_code_missing_with_actual'])
            )
        )
    if mismatch_count or missing_room_code_count:
        alert_lines.append(u'詳細內容已寫入主表右側「備註」及「高度檢核」工作表。')
    forms.alert(u'\n\n'.join(alert_lines), title=u'天花 Excel')


main()
