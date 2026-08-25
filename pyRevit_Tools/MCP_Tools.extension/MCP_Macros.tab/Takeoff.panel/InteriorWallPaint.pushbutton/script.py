# -*- coding: utf-8 -*-
from __future__ import unicode_literals

__title__ = u'內牆粉刷\nExcel'
__author__ = 'Codex'

import math
import os
import re
import codecs

import clr

clr.AddReference('System.IO.Compression')
clr.AddReference('System.IO.Compression.FileSystem')

from Autodesk.Revit.DB import (  # noqa: E402
    BuiltInCategory,
    BuiltInParameter,
    Element,
    FamilyInstance,
    FamilySymbol,
    FilteredElementCollector,
    Level,
    SpatialElement,
    SpatialElementBoundaryLocation,
    SpatialElementBoundaryOptions,
    XYZ,
)
from System import String  # noqa: E402
from System.IO import FileAccess, FileMode, FileStream, StreamWriter  # noqa: E402
from System.IO.Compression import ZipArchive, ZipArchiveMode  # noqa: E402
from System.Text import Encoding  # noqa: E402

from pyrevit import forms, revit, script  # noqa: E402

import takeoff_direct_publish  # noqa: E402
import takeoff_excel_styles  # noqa: E402
import takeoff_entry  # noqa: E402
import room_takeoff_sources_logic  # noqa: E402

try:
    reload(takeoff_direct_publish)
except Exception:
    pass

SCAFFOLD_HEIGHT_IMPORT_ERROR = ''
try:
    import scaffold_height  # noqa: E402
    try:
        reload(scaffold_height)
    except Exception:
        pass
except Exception as import_error:
    scaffold_height = None
    SCAFFOLD_HEIGHT_IMPORT_ERROR = u'{0}'.format(import_error)


FT_TO_M = 0.3048
ROOM_ASSIGN_PADDING_FT = 1000.0 / 304.8
HEIGHT_BUCKET_SIZE_M = 0.05
CEILING_SAMPLE_GRID = 5
MIN_VALID_HEIGHT_M = 0.50
MAX_VALID_HEIGHT_M = 20.0
FIXED_REPORT_COLS = 16
FIRST_DATA_ROW = 6
SUMMARY_LABEL = u'內牆粉刷數量總計'


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
            return clean(param.AsValueString() or param.AsString())
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
    value = lookup_value(element, lookup_names)
    return value


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
                text = clean(param.AsValueString() or param.AsString())
                number = parse_number(text)
                if number is not None:
                    return number
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


def floor_sort_key(number):
    text = normalize_level(number)
    if text == 'BS':
        return (-1000, clean(number))

    match = re.match(r'^(BS|B|F|R)?0*(\d+)', text)
    if not match:
        return (9999, clean(number))
    prefix = match.group(1) or 'F'
    value = int(match.group(2))
    if prefix == 'BS':
        order = -100
    elif prefix == 'B':
        order = -value
    elif prefix == 'R':
        order = 1000 + value
    else:
        order = value
    return (order, clean(number))


def room_number(room):
    value = ''
    param = get_bip_param(room, 'ROOM_NUMBER')
    if param:
        value = clean(param.AsString() or param.AsValueString())
    if not value:
        value = lookup_value(room, [u'編號', 'Number'])
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
        value = lookup_value(room, [u'名稱', 'Name']) or element_name(room)
    if number:
        value = re.sub(r'\s*{0}\s*$'.format(re.escape(number)), '', value, flags=re.I).strip()
    return value


def room_perimeter(room):
    param = get_bip_param(room, 'ROOM_PERIMETER')
    if param and param.HasValue:
        try:
            return param.AsDouble() * FT_TO_M
        except Exception:
            pass
    value = lookup_value(room, [u'周長', 'Perimeter'])
    number = parse_number(value)
    return number


def room_boundary_perimeter(room):
    options = SpatialElementBoundaryOptions()
    try:
        options.SpatialElementBoundaryLocation = SpatialElementBoundaryLocation.Finish
    except Exception:
        pass

    try:
        loops = room.GetBoundarySegments(options)
    except Exception:
        loops = None

    if not loops:
        return {
            'perimeter': None,
            'source': 'parameter',
            'loop_count': 0,
            'segment_count': 0,
        }

    total = 0.0
    loop_count = 0
    segment_count = 0
    boundary_element_ids = set()
    for loop in loops:
        loop_count += 1
        for segment in loop:
            try:
                curve = segment.GetCurve()
                length = curve.Length * FT_TO_M if curve else 0
            except Exception:
                length = 0
            if length > 0:
                total += length
                segment_count += 1
                try:
                    element_id = segment.ElementId
                    if valid_element_id(element_id):
                        boundary_element_ids.add(element_id_value(element_id))
                except Exception:
                    pass

    return {
        'perimeter': total if total > 0 else None,
        'source': 'boundary' if total > 0 else 'parameter',
        'loop_count': loop_count,
        'segment_count': segment_count,
        'element_ids': boundary_element_ids,
    }


def room_wall_finish(room):
    value = lookup_value(room, [
        u'牆面塗層',
        u'牆面',
        u'內牆粉刷',
        u'內牆塗層',
        u'粉刷',
        'Wall Finish',
        'WallFinish',
    ])
    if clean(value).upper() in ('-', u'無', 'NA', 'N/A', 'NONE'):
        return ''
    return value


def level_name(room):
    try:
        level_id = room.LevelId
        if level_id:
            level = doc.GetElement(level_id)
            if level:
                return element_name(level)
    except Exception:
        pass
    return lookup_value(room, [u'樓層', 'Level'])


def opening_level_name(opening):
    try:
        level_id = opening.LevelId
        if level_id:
            level = doc.GetElement(level_id)
            if level:
                return element_name(level)
    except Exception:
        pass
    return lookup_value(opening, [u'樓層', 'Level'])


def same_level_name(left, right):
    left_key = normalize_level(left)
    right_key = normalize_level(right)
    return bool(left_key and right_key and left_key == right_key)


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
            text = clean(param.AsValueString() or param.AsString())
            value = normalize_metric_m(parse_number(text))
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
            text = clean(param.AsValueString() or param.AsString())
            value = normalize_metric_m(parse_number(text))
            if valid_height(value):
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


def valid_element_id(element_id):
    if element_id is None:
        return False
    try:
        return element_id_value(element_id) > 0
    except Exception:
        return False


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
            'key': normalize_level(element_name(level)),
            'elevation': elevation,
        }
        entries.append(entry)
        by_id[entry['id']] = entry
    entries.sort(key=lambda item: item['elevation'])
    return {
        'entries': entries,
        'by_id': by_id,
    }


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

    level_key = normalize_level(level_name(element))
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


def box_overlap_area_xy(left, right):
    if not left or not right:
        return 0
    min_x = max(left[0], right[0])
    min_y = max(left[1], right[1])
    max_x = min(left[3], right[3])
    max_y = min(left[4], right[4])
    if max_x <= min_x or max_y <= min_y:
        return 0
    return (max_x - min_x) * (max_y - min_y)


def collect_ceiling_data(level_catalog):
    ceilings = []
    for ceiling in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Ceilings).WhereElementIsNotElementType():
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
        ceilings.append({
            'id': element_id_value(ceiling.Id),
            'name': element_name(ceiling),
            'level': level_entry['key'] if level_entry else normalize_level(level_name(ceiling)),
            'level_elevation': level_entry['elevation'] if level_entry else None,
            'offset_m': offset_m,
            'box': box,
            'bottom_m': offset_bottom_m if offset_bottom_m is not None else bbox_bottom_m,
            'bbox_bottom_m': bbox_bottom_m,
            'top_m': top_m,
        })
    return ceilings


def build_height_context():
    level_catalog = build_level_catalog()
    thickness_groups = {}

    for floor in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Floors).WhereElementIsNotElementType():
        thickness = floor_thickness_m(floor)
        if not thickness:
            continue
        level_entry = level_entry_from_id(level_catalog, getattr(floor, 'LevelId', None))
        level_key = level_entry['key'] if level_entry else normalize_level(level_name(floor))
        floor_type_name = ''
        try:
            floor_type_name = element_name(doc.GetElement(floor.GetTypeId()))
        except Exception:
            floor_type_name = ''
        add_slab_thickness_group(thickness_groups, level_key, thickness, u'{0} {1}'.format(element_name(floor), floor_type_name))

    thickness_by_level = {}
    for level_key, items in thickness_groups.items():
        thickness = select_group_thickness(items)
        if thickness:
            thickness_by_level[level_key] = thickness

    return {
        'levels': level_catalog,
        'thickness_by_level': thickness_by_level,
        'ceilings': collect_ceiling_data(level_catalog),
    }


def room_base_level_entry(room, height_context):
    return level_entry_from_id(height_context.get('levels', {}), getattr(room, 'LevelId', None))


def room_base_elevation_m(room, height_context):
    entry = room_base_level_entry(room, height_context)
    offset = param_double_m(room, ['ROOM_LOWER_OFFSET'], [u'基準偏移', u'底部偏移', 'Base Offset']) or 0
    if entry:
        return entry['elevation'] + offset
    try:
        box = room.get_BoundingBox(None)
    except Exception:
        box = None
    if box:
        return box.Min.Z * FT_TO_M
    return None


def room_top_level_entry(room, height_context, base_elevation):
    level_catalog = height_context.get('levels', {})
    upper_id = param_element_id(room, 'ROOM_UPPER_LEVEL')
    entry = level_entry_from_id(level_catalog, upper_id)
    if entry and base_elevation is not None and entry['elevation'] > base_elevation + 0.50:
        return entry

    for candidate in level_catalog.get('entries', []):
        if base_elevation is not None and candidate['elevation'] > base_elevation + 1.50:
            return candidate
    return None


def ceiling_room_sample_score(room, room_box_data, ceiling_box):
    if not room_box_data or not ceiling_box:
        return None

    min_x = max(room_box_data[0], ceiling_box[0])
    min_y = max(room_box_data[1], ceiling_box[1])
    max_x = min(room_box_data[3], ceiling_box[3])
    max_y = min(room_box_data[4], ceiling_box[4])
    if max_x <= min_x or max_y <= min_y:
        return None

    sample_z = (room_box_data[2] + room_box_data[5]) / 2.0
    grid = CEILING_SAMPLE_GRID
    inside = 0
    total = grid * grid
    for x_index in range(grid):
        x_ratio = float(x_index + 1) / float(grid + 1)
        x_value = min_x + (max_x - min_x) * x_ratio
        for y_index in range(grid):
            y_ratio = float(y_index + 1) / float(grid + 1)
            y_value = min_y + (max_y - min_y) * y_ratio
            try:
                if room.IsPointInRoom(XYZ(x_value, y_value, sample_z)):
                    inside += 1
            except Exception:
                pass

    if inside <= 0:
        return None

    overlap = (max_x - min_x) * (max_y - min_y)
    inside_ratio = float(inside) / float(total)
    return {
        'score': overlap * inside_ratio,
        'overlap': overlap,
        'inside': inside,
        'total': total,
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


def ceiling_bottom_height_info(room, height_context, base_elevation):
    if base_elevation is None:
        return None
    room_box_data = element_box_tuple(room)
    room_level_entry = room_base_level_entry(room, height_context)
    room_level = normalize_level(level_name(room))
    candidates = {}

    for ceiling in height_context.get('ceilings', []):
        height, source = ceiling_height_from_room_base(ceiling, base_elevation, room_level_entry, room_level)
        if not valid_height(height):
            continue
        ceiling_level = ceiling.get('level')
        if room_level and ceiling_level and room_level != ceiling_level:
            continue

        sample_score = ceiling_room_sample_score(room, room_box_data, ceiling.get('box'))
        if not sample_score:
            continue

        bucket = fixed2(round_to_step(height, HEIGHT_BUCKET_SIZE_M))
        if bucket not in candidates:
            candidates[bucket] = {
                'height': round_to_step(height, HEIGHT_BUCKET_SIZE_M),
                'score': 0,
                'offset_count': 0,
                'source': source,
                'names': [],
            }
        candidates[bucket]['score'] += sample_score['score']
        if source == 'actual-ceiling-offset':
            candidates[bucket]['offset_count'] += 1
            candidates[bucket]['source'] = source
        if ceiling.get('name') and ceiling.get('name') not in candidates[bucket]['names']:
            candidates[bucket]['names'].append(ceiling.get('name'))

    if not candidates:
        return None

    selected = sorted(candidates.values(), key=lambda item: (-item['score'], -item['offset_count'], item['height']))[0]
    return {
        'height': selected['height'],
        'source': selected.get('source') or 'actual-ceiling-bottom',
        'target_level': '',
        'slab_thickness': None,
        'raw_height': selected['height'],
        'ceiling_names': selected['names'],
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

    top_offset = param_double_m(room, ['ROOM_UPPER_OFFSET'], [u'頂部偏移', u'上限偏移', 'Limit Offset', 'Upper Offset']) or 0
    height = top_entry['elevation'] + top_offset - base_elevation
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
        'target_level': top_entry['key'] or top_entry['name'],
        'slab_thickness': slab_thickness,
        'raw_height': height,
        'warnings': warnings,
    }


def room_height_info(room, height_context):
    base_elevation = room_base_elevation_m(room, height_context)
    ceiling_info = ceiling_bottom_height_info(room, height_context, base_elevation)
    if ceiling_info:
        return ceiling_info

    info = room_slab_bottom_height_info(room, height_context, base_elevation)
    if info:
        return info

    explicit = param_height_m(
        room,
        [],
        [u'內牆淨高', u'牆面淨高', u'淨高', 'Net Height']
    )
    if explicit:
        return {
            'height': round_to_step(explicit, HEIGHT_BUCKET_SIZE_M),
            'source': 'room-explicit-height-fallback',
            'target_level': '',
            'slab_thickness': None,
            'raw_height': explicit,
        }

    fallback = param_height_m(room, ['ROOM_HEIGHT'], [u'不連續高度', 'Unbounded Height'])
    if not fallback:
        try:
            box = room.get_BoundingBox(None)
        except Exception:
            box = None
        if box:
            fallback = (box.Max.Z - box.Min.Z) * FT_TO_M
    if fallback and valid_height(fallback):
        return {
            'height': round_to_step(fallback, HEIGHT_BUCKET_SIZE_M),
            'source': 'room-revit-height',
            'target_level': '',
            'slab_thickness': None,
            'raw_height': fallback,
        }

    return {
        'height': None,
        'source': 'missing-height',
        'target_level': '',
        'slab_thickness': None,
        'raw_height': None,
    }


def room_box(room):
    try:
        box = room.get_BoundingBox(None)
    except Exception:
        box = None
    if not box:
        return None
    return (
        box.Min.X, box.Min.Y, box.Min.Z,
        box.Max.X, box.Max.Y, box.Max.Z,
    )


def room_center(room, box):
    try:
        location = room.Location
        point = location.Point
        return (point.X, point.Y, point.Z)
    except Exception:
        pass
    if box:
        return (
            (box[0] + box[3]) / 2.0,
            (box[1] + box[4]) / 2.0,
            (box[2] + box[5]) / 2.0,
        )
    return (0, 0, 0)


def build_room(room, height_context):
    number = room_number(room)
    box = room_box(room)
    boundary = room_boundary_perimeter(room)
    parameter_perimeter = room_perimeter(room)
    perimeter = boundary.get('perimeter') or parameter_perimeter
    perimeter_source = boundary.get('source') if boundary.get('perimeter') else 'parameter'
    height_info = room_height_info(room, height_context)
    try:
        area = room.Area
    except Exception:
        area = 0
    return {
        'element': room,
        'element_id': element_id_value(room.Id),
        'number': number,
        'name': room_name(room, number),
        'perimeter': perimeter,
        'parameter_perimeter': parameter_perimeter,
        'perimeter_source': perimeter_source if perimeter else 'missing',
        'boundary_loop_count': boundary.get('loop_count') or 0,
        'boundary_segment_count': boundary.get('segment_count') or 0,
        'boundary_element_ids': boundary.get('element_ids') or set(),
        'height': height_info.get('height'),
        'height_source': height_info.get('source'),
        'height_target_level': height_info.get('target_level'),
        'slab_thickness': height_info.get('slab_thickness'),
        'height_warnings': height_info.get('warnings') or [],
        'wall_finish': room_wall_finish(room),
        'level': level_name(room),
        'box': box,
        'center': room_center(room, box),
        'area': area,
    }


def finish_sort_key(value):
    text = clean(value).upper()
    match = re.match(r'^W\s*0*(\d+)([A-Z]*)$', text)
    if match:
        suffix = match.group(2) or ''
        return (0, int(match.group(1)), suffix, text)
    parts = []
    for part in re.split(r'(\d+)', text):
        if part.isdigit():
            parts.append(int(part))
        else:
            parts.append(part)
    return (1, parts)


def wall_finish_codes(value):
    text = clean(value)
    if not text:
        return []
    result = []
    for raw in re.split(r'\s*(?:\+|＋|、|/|,|，)\s*', text):
        token = clean(raw)
        if not token or token.upper() in ('-', u'無', 'NA', 'N/A', 'NONE'):
            continue
        match = re.match(r'^(W\s*0*\d+[A-Z]?)(?:\s*[=＝:：\-].*)?$', token, re.I)
        code = match.group(1) if match else token
        code = re.sub(r'\s+', '', clean(code)).upper()
        if code and code not in result:
            result.append(code)
    return result


def find_material_table():
    try:
        current = os.path.abspath(os.path.dirname(__file__))
    except Exception:
        current = os.getcwd()
    for _index in range(10):
        candidate = os.path.join(current, u'材料表對照.csv')
        if os.path.exists(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return ''


def read_text_with_fallback(path):
    for encoding in ('utf-8-sig', 'cp950', 'big5', 'mbcs'):
        try:
            handle = codecs.open(path, 'r', encoding)
            try:
                return handle.read()
            finally:
                handle.close()
        except Exception:
            pass
    return ''


def load_material_names():
    path = find_material_table()
    if not path:
        return {}
    text = read_text_with_fallback(path)
    result = {}
    for raw_line in text.splitlines():
        line = clean(raw_line)
        if not line or ',' not in line:
            continue
        code, name = line.split(',', 1)
        code = clean(code)
        name = clean(name)
        if not code or code == u'材料編號':
            continue
        result[code.upper()] = name
    return result


def collect_family_symbols_by_name():
    result = {}
    for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
        family = getattr(symbol, 'Family', None)
        family_name = element_name(family)
        if not family_name:
            family_name = lookup_value(symbol, [u'族群名稱', 'Family Name'])
        if not family_name:
            continue
        result.setdefault(family_name, []).append(symbol)
    return result


def family_choice_sort_key(name):
    text = clean(name)
    if text == u'AE-材料版':
        return (0, text)
    if u'材料' in text:
        return (1, text)
    return (2, text)


def choose_material_family(material_cols, families=None):
    if not material_cols:
        return ('', {})
    if families is None:
        families = collect_family_symbols_by_name()
    if not families:
        return ('', {})

    skip_label = u'（略過，使用 CSV 備援）'
    options = [skip_label] + sorted(families.keys(), key=family_choice_sort_key)
    selected = forms.SelectFromList.show(
        options,
        title=u'選擇材料版族群',
        button_name=u'讀取材料名稱',
        multiselect=False
    )
    if selected is None:
        return (None, families)
    if selected == skip_label:
        return ('', families)
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
        if re.search(r'(^|[\s_/\\\-\(\[（【]){0}($|[\s=＝:：\-\)）\]】])'.format(re.escape(code_text)), text):
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
        return clean_material_name_from_text(type_name, code) or type_name
    return ''


def load_material_names_from_family(family_name, family_symbols, material_cols):
    if not family_name:
        return {}
    symbols = family_symbols.get(family_name, [])
    result = {}
    for code in material_cols:
        for symbol in symbols:
            name = material_name_from_symbol(symbol, code)
            if name:
                result[clean(code).upper()] = name
                break
    return result


def parse_size_from_name(name):
    match = re.search(r'(\d+(?:\.\d+)?)\s*[xX×*]\s*(\d+(?:\.\d+)?)', clean(name))
    if not match:
        return (None, None)
    a = float(match.group(1))
    b = float(match.group(2))
    divisor = 100.0 if ('cm' in clean(name).lower() or a > 20 or b > 20) else 1.0
    return (a / divisor, b / divisor)


def opening_dimensions(opening):
    width = param_double_m(
        opening,
        ['DOOR_WIDTH', 'WINDOW_WIDTH', 'FAMILY_WIDTH_PARAM', 'FAMILY_ROUGH_WIDTH_PARAM'],
        [u'寬度', u'粗略寬度', 'Width']
    )
    height = param_double_m(
        opening,
        ['DOOR_HEIGHT', 'WINDOW_HEIGHT', 'FAMILY_HEIGHT_PARAM', 'FAMILY_ROUGH_HEIGHT_PARAM'],
        [u'高度', u'粗略高度', 'Height']
    )
    symbol = getattr(opening, 'Symbol', None)
    if symbol:
        if not width:
            width = param_double_m(
                symbol,
                ['DOOR_WIDTH', 'WINDOW_WIDTH', 'FAMILY_WIDTH_PARAM', 'FAMILY_ROUGH_WIDTH_PARAM'],
                [u'寬度', u'粗略寬度', 'Width']
            )
        if not height:
            height = param_double_m(
                symbol,
                ['DOOR_HEIGHT', 'WINDOW_HEIGHT', 'FAMILY_HEIGHT_PARAM', 'FAMILY_ROUGH_HEIGHT_PARAM'],
                [u'高度', u'粗略高度', 'Height']
            )
    if not width or not height:
        parsed_width, parsed_height = parse_size_from_name(element_name(symbol) or element_name(opening))
        width = width or parsed_width
        height = height or parsed_height
    return (width, height)


def opening_name(opening):
    symbol = getattr(opening, 'Symbol', None)
    type_name = element_name(symbol)
    if type_name:
        return type_name

    for element in (symbol, opening):
        value = param_text(
            element,
            ['ALL_MODEL_TYPE_MARK'],
            [u'類型標記', u'類型註記', 'Type Mark']
        )
        if value:
            return value
    value = param_text(opening, ['ALL_MODEL_MARK'], [u'標記', 'Mark'])
    if value:
        return value
    return element_name(symbol) or element_name(opening) or 'Door'


def opening_host_id(opening):
    try:
        host = opening.Host
    except Exception:
        host = None
    if not host:
        return None
    try:
        return element_id_value(host.Id)
    except Exception:
        return None


def opening_is_on_room_boundary(opening_item, room_data):
    host_id = opening_item.get('host_id')
    if not host_id or not room_data:
        return False
    boundary_ids = room_data.get('boundary_element_ids') or set()
    return host_id in boundary_ids


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


def family_room_for_phase(instance, attr_name):
    try:
        room = getattr(instance, attr_name)
        if valid_room(room):
            return room
    except Exception:
        pass

    getter = getattr(instance, 'get_{0}'.format(attr_name), None)
    if getter:
        try:
            phases = list(doc.Phases)
        except Exception:
            phases = []
        for phase in reversed(phases):
            try:
                room = getter(phase)
                if valid_room(room):
                    return room
            except Exception:
                pass
    return None


def point_inside_box(point, box, padding):
    if not point or not box:
        return False
    return (
        box[0] - padding <= point[0] <= box[3] + padding and
        box[1] - padding <= point[1] <= box[4] + padding and
        box[2] - padding <= point[2] <= box[5] + padding
    )


def distance_to_box(point, box):
    if not point or not box:
        return float('inf')
    dx = max(box[0] - point[0], 0, point[0] - box[3])
    dy = max(box[1] - point[1], 0, point[1] - box[4])
    dz = max(box[2] - point[2], 0, point[2] - box[5])
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def opening_point(opening):
    try:
        point = opening.Location.Point
        return (point.X, point.Y, point.Z)
    except Exception:
        pass
    try:
        box = opening.get_BoundingBox(None)
    except Exception:
        box = None
    if box:
        return (
            (box.Min.X + box.Max.X) / 2.0,
            (box.Min.Y + box.Max.Y) / 2.0,
            (box.Min.Z + box.Max.Z) / 2.0,
        )
    return None


def room_assignment_is_plausible(room_data, point, opening_level):
    if not room_data:
        return False
    if same_level_name(opening_level, room_data.get('level')):
        return True
    if point_inside_box(point, room_data.get('box'), ROOM_ASSIGN_PADDING_FT * 0.5):
        return True
    return False


def nearest_rooms(opening, rooms, opening_level, excluded_ids, limit):
    point = opening_point(opening)
    if not point or limit <= 0:
        return []

    inside_room_ids = set()
    for room in rooms:
        try:
            if room['element'].IsPointInRoom(opening.Location.Point):
                inside_room_ids.add(room['element_id'])
        except Exception:
            pass

    candidates = []
    for room in rooms:
        if room['element_id'] in excluded_ids:
            continue
        if not room['box']:
            continue
        if not same_level_name(opening_level, room.get('level')) and room['element_id'] not in inside_room_ids:
            continue
        box_distance = distance_to_box(point, room['box'])
        if box_distance > ROOM_ASSIGN_PADDING_FT and room['element_id'] not in inside_room_ids:
            continue
        candidates.append(room)

    best = None
    scored = []
    for room in candidates:
        box_distance = distance_to_box(point, room['box'])
        center = room['center']
        center_distance = math.sqrt((point[0] - center[0]) ** 2 + (point[1] - center[1]) ** 2)
        area_penalty = (room['area'] or 0) * 0.01
        score = box_distance * 20 + center_distance + area_penalty
        if room['element_id'] in inside_room_ids:
            score -= 100000
        scored.append((score, room))

    scored.sort(key=lambda item: item[0])
    return [room for _score, room in scored[:limit]]


def rooms_for_opening(opening, rooms, rooms_by_id):
    found = {}
    raw_seen = 0
    invalid_seen = 0
    point = opening_point(opening)
    opening_level = opening_level_name(opening)

    for attr_name in ('FromRoom', 'ToRoom'):
        room = family_room_for_phase(opening, attr_name)
        if valid_room(room):
            raw_seen += 1
            room_id = element_id_value(room.Id)
            room_data = rooms_by_id.get(room_id)
            if room_assignment_is_plausible(room_data, point, opening_level):
                found[room_id] = room
            else:
                invalid_seen += 1

    if invalid_seen and len(found) < 2:
        for room_data in nearest_rooms(opening, rooms, opening_level, set(found.keys()), 2 - len(found)):
            found[room_data['element_id']] = room_data['element']
    elif not raw_seen and not found:
        for room_data in nearest_rooms(opening, rooms, opening_level, set(), 1):
            found[room_data['element_id']] = room_data['element']

    return found.values()


def apply_reference_intersector_heights(rooms, stats):
    stats['height_detector'] = 'legacy'
    stats['height_detector_view'] = ''
    stats['height_bottom_detector_view'] = ''
    stats['height_detector_has_3d_view'] = False
    stats['height_detector_error'] = SCAFFOLD_HEIGHT_IMPORT_ERROR
    stats['height_detector_counts'] = {}
    stats['height_bottom_counts'] = {}
    stats['height_bottom_ambiguous_rooms'] = []
    stats['height_bottom_fallback_rooms'] = []
    stats['height_detector_updated'] = 0

    if not rooms or scaffold_height is None:
        return

    room_ids = [room['element_id'] for room in rooms if room.get('element_id')]
    if not room_ids:
        return

    try:
        resolved = scaffold_height.resolve_room_heights(
            doc, room_ids, detect_lower_floor=True)
    except Exception as resolve_error:
        stats['height_detector_error'] = u'{0}'.format(resolve_error)
        return

    resolved_rooms = resolved.get('rooms') or {}
    if not resolved_rooms:
        stats['height_detector_error'] = u'No resolved room heights returned.'
        return

    stats['height_detector'] = 'reference-intersector'
    stats['height_detector_view'] = resolved.get('detector_view') or ''
    stats['height_bottom_detector_view'] = (
        resolved.get('bottom_detector_view') or '')
    stats['height_detector_has_3d_view'] = bool(resolved.get('has_3d_view'))
    stats['height_detector_counts'] = resolved.get('counts') or {}
    stats['height_bottom_counts'] = resolved.get('bottom_counts') or {}
    stats['height_detector_error'] = ''

    for room in rooms:
        room_id = room.get('element_id')
        info = resolved_rooms.get(str(room_id))
        if not info:
            continue
        height = info.get('height')
        if not valid_height(height):
            continue
        room['height'] = height
        top_source = info.get('source') or room.get('height_source')
        bottom_source = info.get('bottom_source') or ''
        room['height_source'] = (
            u'{0}+{1}'.format(top_source, bottom_source)
            if top_source and bottom_source else top_source or bottom_source)
        room['height_target_level'] = info.get('target_level') or ''
        room['slab_thickness'] = info.get('slab_thickness')
        room['height_raw'] = info.get('raw_height')
        room['height_hit_count'] = info.get('hit_count') or 0
        room['height_warnings'] = info.get('warnings') or []
        room['height_bottom_source'] = info.get('bottom_source') or ''
        room['height_bottom_offset'] = info.get('bottom_offset_m')
        room['height_bottom_hit_count'] = info.get('bottom_hit_count') or 0
        room['height_bottom_spread'] = info.get('bottom_spread_m') or 0
        room['height_bottom_ambiguous'] = bool(info.get('bottom_ambiguous'))
        room_label = room.get('number') or str(room_id)
        if room['height_bottom_ambiguous']:
            stats['height_bottom_ambiguous_rooms'].append(room_label)
        if bottom_source.endswith('-fallback'):
            stats['height_bottom_fallback_rooms'].append(room_label)
        stats['height_detector_updated'] += 1


def collect_data():
    height_context = build_height_context()
    rooms = []
    for room in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType():
        if not isinstance(room, SpatialElement):
            continue
        if not room_is_in_active_level_scope(room):
            continue
        try:
            if room.Area <= 0:
                continue
        except Exception:
            pass
        data = build_room(room, height_context)
        if data['number'] or data['name']:
            rooms.append(data)
    rooms.sort(key=lambda r: (
        floor_sort_key(r['level'] or r['number']),
        room_takeoff_sources_logic.room_number_sort_key(r['number']),
        r['name']))

    rooms_by_id = dict((r['element_id'], r) for r in rooms)
    openings_by_room = dict((r['element_id'], []) for r in rooms)

    stats = {
        'rooms': len(rooms),
        'openings': 0,
        'opening_room_deductions': 0,
        'skipped_no_size': 0,
        'skipped_no_host': 0,
        'skipped_no_room': 0,
        'skipped_not_boundary': 0,
        'missing_wall_finish': 0,
        'multi_wall_finish': 0,
        'perimeter_boundary': 0,
        'perimeter_parameter': 0,
        'perimeter_missing': 0,
        'multi_loop_rooms': 0,
        'slab_levels': len(height_context.get('thickness_by_level', {})),
        'ceilings': len(height_context.get('ceilings', [])),
        'height_sources': {},
    }

    apply_reference_intersector_heights(rooms, stats)

    for room in rooms:
        codes = wall_finish_codes(room.get('wall_finish'))
        if not codes:
            stats['missing_wall_finish'] += 1
        elif len(codes) > 1:
            stats['multi_wall_finish'] += 1
        source = room.get('perimeter_source')
        if source == 'boundary':
            stats['perimeter_boundary'] += 1
        elif source == 'parameter':
            stats['perimeter_parameter'] += 1
        else:
            stats['perimeter_missing'] += 1
        if (room.get('boundary_loop_count') or 0) > 1:
            stats['multi_loop_rooms'] += 1
        height_source = room.get('height_source') or 'unknown'
        stats['height_sources'][height_source] = stats['height_sources'].get(height_source, 0) + 1

    for category in (BuiltInCategory.OST_Doors, BuiltInCategory.OST_Windows):
        for opening in FilteredElementCollector(doc).OfCategory(category).WhereElementIsNotElementType():
            if not isinstance(opening, FamilyInstance):
                continue
            stats['openings'] += 1
            width, height = opening_dimensions(opening)
            if not width or not height or width <= 0 or height <= 0:
                stats['skipped_no_size'] += 1
                continue
            host_id = opening_host_id(opening)
            if not host_id:
                stats['skipped_no_host'] += 1
                continue
            linked_rooms = rooms_for_opening(opening, rooms, rooms_by_id)
            if not linked_rooms:
                stats['skipped_no_room'] += 1
                continue
            item = {
                'id': element_id_value(opening.Id),
                'name': opening_name(opening),
                'width': width,
                'height': height,
                'host_id': host_id,
            }
            for room in linked_rooms:
                room_id = element_id_value(room.Id)
                room_data = rooms_by_id.get(room_id)
                if not room_data:
                    continue
                if not opening_is_on_room_boundary(item, room_data):
                    stats['skipped_not_boundary'] += 1
                    continue
                openings_by_room.setdefault(room_id, []).append(item)
                stats['opening_room_deductions'] += 1

    material_codes = set()
    for room in rooms:
        for code in wall_finish_codes(room.get('wall_finish')):
            material_codes.add(code)
    material_cols = sorted(list(material_codes), key=finish_sort_key)
    stats['wall_finish_types'] = len(material_cols)
    return rooms, openings_by_room, material_cols, stats


def grouped_openings(openings):
    groups = {}
    for opening in openings:
        width = opening.get('width')
        height = opening.get('height')
        if not width or width <= 0 or not height or height <= 0:
            continue
        key = '{0}||{1}||{2}'.format(opening.get('name') or 'Opening', fixed2(width), fixed2(height))
        if key not in groups:
            groups[key] = {
                'name': opening.get('name') or 'Opening',
                'width': width,
                'height': height,
                'count': 0,
            }
        groups[key]['count'] += 1
    result = groups.values()
    result.sort(key=lambda item: (item['name'], item['width'], item['height']))
    return result


def make_rows(rooms, openings_by_room, material_cols):
    rows = []
    total_cols = FIXED_REPORT_COLS + len(material_cols) + 1
    material_index = dict((name, index) for index, name in enumerate(material_cols))

    for room in rooms:
        openings = grouped_openings(openings_by_room.get(room['element_id'], []))
        row_count = max(1, len(openings))
        material_codes = wall_finish_codes(room.get('wall_finish'))
        for i in range(row_count):
            row = [''] * total_cols
            if i == 0:
                row[0] = room['number']
                row[1] = room['name']
                row[2] = fixed2(room['perimeter'])
                row[5] = fixed2(room.get('height'))
                row[6] = 'WALL_AREA_FORMULA'
                row[7] = 'WALL_SUBTOTAL_FORMULA'
                row[14] = 'OPENING_TOTAL_FORMULA'
                row[15] = 'TOTAL_FORMULA'
                row[-1] = room.get('source_label') or ''
                for code in material_codes:
                    material_col = material_index.get(code)
                    if material_col is not None:
                        row[FIXED_REPORT_COLS + material_col] = 'MATERIAL_FORMULA'

            if i < len(openings):
                opening = openings[i]
                row[8] = opening['name']
                row[9] = opening['count']
                row[10] = fixed2(opening['width'])
                row[11] = fixed2(opening['height'])
                row[12] = 'OPENING_AREA_FORMULA'
                row[13] = 'OPENING_SUBTOTAL_FORMULA'

            rows.append(row)

    return fill_formulas(rows, material_cols)


def excel_col(index):
    result = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def fill_formulas(rows, material_cols):
    for i, row in enumerate(rows):
        row_number = FIRST_DATA_ROW + i
        if row[6] == 'WALL_AREA_FORMULA':
            row[6] = '=C{0}*F{0}'.format(row_number)
        if row[7] == 'WALL_SUBTOTAL_FORMULA':
            row[7] = '=G{0}'.format(row_number)
        if row[12] == 'OPENING_AREA_FORMULA':
            row[12] = '=K{0}*L{0}'.format(row_number)
        if row[13] == 'OPENING_SUBTOTAL_FORMULA':
            row[13] = '=M{0}*J{0}'.format(row_number)
        if row[14] == 'OPENING_TOTAL_FORMULA':
            start_row = row_number if row[13] else None
            end_row = start_row
            look = 1
            while i + look < len(rows) and not rows[i + look][0] and not rows[i + look][1] and rows[i + look][13]:
                end_row = row_number + look
                look += 1
            if start_row and end_row and end_row != start_row:
                row[14] = '=SUM(N{0}:N{1})'.format(start_row, end_row)
            elif start_row:
                row[14] = '=N{0}'.format(start_row)
            else:
                row[14] = '=0'
        if row[15] == 'TOTAL_FORMULA':
            row[15] = '=H{0}-O{0}'.format(row_number)
        for index, _material in enumerate(material_cols):
            col = FIXED_REPORT_COLS + index
            if row[col] == 'MATERIAL_FORMULA':
                row[col] = '=P{0}'.format(row_number)
    return rows


def build_summary_row(data_row_count, material_cols):
    row = [''] * (FIXED_REPORT_COLS + len(material_cols) + 1)
    row[0] = SUMMARY_LABEL
    last_data_row = FIRST_DATA_ROW + data_row_count - 1
    for index, _material in enumerate(material_cols):
        col_name = excel_col(FIXED_REPORT_COLS + index + 1)
        if data_row_count > 0:
            row[FIXED_REPORT_COLS + index] = '=SUM({0}{1}:{0}{2})'.format(
                col_name,
                FIRST_DATA_ROW,
                last_data_row
            )
        else:
            row[FIXED_REPORT_COLS + index] = '=0'
    return row


def build_sheet_values(rows, material_cols, project_title, material_names):
    total_cols = FIXED_REPORT_COLS + len(material_cols) + 1
    drawing_col = total_cols - 1
    blank_tail = [''] * (total_cols - 1)
    values = []
    values.append([u'工程採購數量計算表'] + blank_tail)
    values.append([project_title] + blank_tail)

    title_row = [u'內牆粉刷數量計算表'] + blank_tail
    for index, material in enumerate(material_cols):
        title_row[FIXED_REPORT_COLS + index] = material
    title_row[drawing_col] = u'對應\n圖說'
    values.append(title_row)

    section = [''] * total_cols
    section[0] = u'樓別名稱'
    section[3] = u'牆面'
    section[8] = u'開口'
    section[15] = u'總計'
    material_name_headers = [material_names.get(clean(material).upper(), '') for material in material_cols]
    for index, material in enumerate(material_cols):
        section[FIXED_REPORT_COLS + index] = material_name_headers[index]
    values.append(section)

    header = [
        u'編號',
        u'空間名稱',
        u'周長',
        u'數量',
        u'牆長',
        u'淨高',
        u'面積',
        u'小計',
        u'名稱',
        u'數量',
        u'寬',
        u'高',
        u'面積',
        u'小計',
        u'開口合計',
        '',
    ] + [''] * len(material_cols) + ['']
    values.append(header)
    values.extend(rows)
    values.append(build_summary_row(len(rows), material_cols))
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


def cell_xml(row_index, col_index, value, summary_row_index):
    ref = '{0}{1}'.format(excel_col(col_index), row_index)
    text = clean(value)
    style = takeoff_excel_styles.style_attr(
        takeoff_excel_styles.row_style_id(
            row_index, summary_row_index, header_row_count=5))
    if value is None or value == '':
        return '<c r="{0}"{1}/>'.format(ref, style)
    if text.startswith('='):
        return '<c r="{0}"{1}><f>{2}</f></c>'.format(ref, style, xml_escape(text[1:]))
    if is_number(value):
        return '<c r="{0}"{1}><v>{2}</v></c>'.format(ref, style, clean(value))
    return '<c r="{0}"{1} t="inlineStr"><is><t>{2}</t></is></c>'.format(ref, style, xml_escape(text))


def sheet_xml(values):
    total_cols = len(values[0]) if values else 1
    drawing_col = total_cols
    summary_row_index = None
    for row_index, row in enumerate(values, start=1):
        if row and row[0] == SUMMARY_LABEL:
            summary_row_index = row_index
            break

    rows_xml = []
    for row_index, row in enumerate(values, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            cell = cell_xml(row_index, col_index, value, summary_row_index)
            if cell:
                cells.append(cell)
        rows_xml.append('<row r="{0}">{1}</row>'.format(row_index, ''.join(cells)))

    merge_refs = [
        'A1:{0}1'.format(excel_col(total_cols)),
        'A2:{0}2'.format(excel_col(total_cols)),
        'A3:P3',
        'A4:C4',
        'D4:H4',
        'I4:O4',
        'P4:P5',
        '{0}3:{0}5'.format(excel_col(drawing_col)),
    ]
    for col_index in range(FIXED_REPORT_COLS + 1, total_cols):
        merge_refs.append('{0}4:{0}5'.format(excel_col(col_index)))
    if summary_row_index:
        merge_refs.append('A{0}:P{0}'.format(summary_row_index))
    merge_xml = '<mergeCells count="{0}">{1}</mergeCells>'.format(
        len(merge_refs),
        ''.join(['<mergeCell ref="{0}"/>'.format(ref) for ref in merge_refs])
    )

    material_start = FIXED_REPORT_COLS + 1
    material_end = total_cols - 1
    col_defs = [
        '<col min="1" max="1" width="11" customWidth="1"/>',
        '<col min="2" max="2" width="20" customWidth="1"/>',
        '<col min="3" max="3" width="12" customWidth="1"/>',
        '<col min="4" max="4" width="8" customWidth="1"/>',
        '<col min="5" max="5" width="8" customWidth="1"/>',
        '<col min="6" max="16" width="12" customWidth="1"/>',
    ]
    if material_end >= material_start:
        col_defs.append('<col min="{0}" max="{1}" width="16" customWidth="1"/>'.format(material_start, material_end))
    col_defs.append('<col min="{0}" max="{0}" width="16" customWidth="1"/>'.format(total_cols))
    cols = ''.join(col_defs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<dimension ref="A1:{0}{1}"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="5" topLeftCell="A6" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        '<cols>{2}</cols><sheetData>{3}</sheetData>{4}'
        '</worksheet>'
    ).format(excel_col(total_cols), len(values), cols, ''.join(rows_xml), merge_xml)


def write_zip_entry(archive, name, content):
    entry = archive.CreateEntry(name)
    stream = entry.Open()
    writer = StreamWriter(stream, Encoding.UTF8)
    writer.Write(content)
    writer.Close()
    stream.Close()


def write_xlsx(path, values):
    fs = FileStream(path, FileMode.Create, FileAccess.ReadWrite)
    archive = ZipArchive(fs, ZipArchiveMode.Create)
    try:
        write_zip_entry(archive, '[Content_Types].xml',
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                        '<Default Extension="xml" ContentType="application/xml"/>'
                        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                        '</Types>')
        write_zip_entry(archive, '_rels/.rels',
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                        '</Relationships>')
        write_zip_entry(archive, 'xl/_rels/workbook.xml.rels',
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                        '</Relationships>')
        write_zip_entry(archive, 'xl/workbook.xml',
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                        '<sheets><sheet name="內牆粉刷數量計算" sheetId="1" r:id="rId1"/></sheets>'
                        '<calcPr calcMode="auto"/></workbook>')
        write_zip_entry(archive, 'xl/styles.xml',
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                        + takeoff_excel_styles.FONTS_XML
                        + takeoff_excel_styles.FILLS_XML
                        + takeoff_excel_styles.BORDERS_XML
                        + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                        '<cellXfs count="5">'
                        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
                        '<alignment horizontal="center" vertical="center" wrapText="1"/>'
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
        write_zip_entry(archive, 'xl/worksheets/sheet1.xml', sheet_xml(values))
    finally:
        archive.Dispose()
        fs.Close()


def safe_filename(text):
    value = re.sub(r'[\\/:*?"<>|]+', '_', clean(text))
    return value or 'Revit'


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
    all_openings = {}
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
            rooms, openings_by_room, material_cols, stats = collect_data()
            for label_key in (
                    'height_bottom_ambiguous_rooms',
                    'height_bottom_fallback_rooms'):
                stats[label_key] = [
                    u'{0} / {1}'.format(source_label, value)
                    for value in stats.get(label_key) or []
                ]
            rooms, openings_by_room = (
                takeoff_direct_publish.rekey_room_records(
                    source_key, source_label, rooms, openings_by_room))
            all_rooms.extend(rooms)
            all_openings.update(openings_by_room)
            all_material_cols.update(material_cols)
            takeoff_direct_publish.merge_stats(all_stats, stats)
    finally:
        doc = previous_doc
        ACTIVE_ALLOWED_LEVEL_IDS = previous_levels
    material_cols = sorted(list(all_material_cols), key=finish_sort_key)
    all_rooms.sort(key=lambda room: (
        clean(room.get('source_label')),
        floor_sort_key(room.get('level') or room.get('number')),
        room_takeoff_sources_logic.room_number_sort_key(
            room.get('number')),
        clean(room.get('name'))))
    all_stats['rooms'] = len(all_rooms)
    all_stats['wall_finish_types'] = len(material_cols)
    return all_rooms, all_openings, material_cols, all_stats, sources


def main():
    if not doc:
        forms.alert(u'請先開啟 Revit 專案檔，再匯出內牆粉刷 Excel。', title=u'內牆粉刷 Excel')
        return

    host_doc = doc
    options = takeoff_entry.choose_options(
        host_doc, u'內牆粉刷 Excel',
        allow_host=True, host_required=False)
    if options is None:
        return
    rooms, openings_by_room, material_cols, stats, sources = (
        collect_selected_sources(host_doc, options))
    family_symbols = collect_family_symbols_for_documents(
        [source[2] for source in sources])
    selected_family, family_symbols = choose_material_family(
        material_cols, family_symbols)
    if selected_family is None:
        return

    project_title = revit_file_title()
    rows = make_rows(rooms, openings_by_room, material_cols)
    material_names = load_material_names()
    family_material_names = load_material_names_from_family(selected_family, family_symbols, material_cols)
    material_names.update(family_material_names)
    values = build_sheet_values(rows, material_cols, project_title, material_names)
    workbook_path = options.get('workbook_path')
    publish_result = None
    if workbook_path:
        temp_path = takeoff_direct_publish.new_temp_xlsx_path()
        try:
            write_xlsx(temp_path, values)
            publish_result = (
                takeoff_direct_publish.publish_generated_workbook(
                    workbook_path,
                    temp_path,
                    [(u'內牆粉刷數量計算', u'內牆')],
                    summary_specs={
                        u'內牆': {
                            'label': SUMMARY_LABEL,
                            'header_label': u'內牆粉刷數量計算表',
                            'data_header_label': u'空間名稱',
                        },
                    }))
            outpath = workbook_path
        except takeoff_direct_publish.WorkbookPublishError as exc:
            forms.alert(
                u'更新主要 Excel 失敗：\n{0}'.format(exc),
                title=u'內牆粉刷 Excel')
            return
        finally:
            takeoff_direct_publish.remove_file_quietly(temp_path)
    else:
        default_name = (
            safe_filename(project_title) + u'_內牆粉刷數量計算.xlsx')
        outpath = forms.save_file(
            file_ext='xlsx',
            default_name=default_name,
            title=u'匯出內牆粉刷數量計算 Excel'
        )
        if not outpath:
            return
        if not outpath.lower().endswith('.xlsx'):
            outpath += '.xlsx'
        write_xlsx(outpath, values)

    action_label = u'更新' if workbook_path else u'匯出'
    output.print_md(u'## 內牆粉刷 Excel {0}完成'.format(action_label))
    output.print_md(u'- 檔案：`{0}`'.format(outpath))
    output.print_md(u'- Revit 來源：{0}'.format(len(sources)))
    if publish_result:
        output.print_md(u'- 備份：`{0}`'.format(
            publish_result.get('backup_path')))
    output.print_md(u'- Rooms：{0}'.format(stats['rooms']))
    output.print_md(u'- 周長來源：房間邊界段 {0}，Revit 周長 fallback {1}，無周長 {2}，多重邊界房間 {3}'.format(
        stats['perimeter_boundary'],
        stats['perimeter_parameter'],
        stats['perimeter_missing'],
        stats['multi_loop_rooms']
    ))
    output.print_md(u'- 淨高來源：實體天花板優先（先讀距樓層的高度偏移，再用幾何底面備援），無天花板改用上層樓板底；Ceilings：{0}，Slab thickness levels：{1}'.format(
        stats.get('ceilings', 0),
        stats.get('slab_levels', 0)
    ))
    output.print_md(u'- Height detector: {0}, updated rooms: {1}, 3D view: {2}'.format(
        stats.get('height_detector'),
        stats.get('height_detector_updated'),
        stats.get('height_detector_view') or u'N/A'
    ))
    for source, count in sorted(stats.get('height_bottom_counts', {}).items()):
        output.print_md(u'  - Bottom `{0}`: {1}'.format(source, count))
    if stats.get('height_bottom_detector_view'):
        output.print_md(u'  - Bottom detector view: {0}'.format(
            stats['height_bottom_detector_view']))
    if stats.get('height_bottom_ambiguous_rooms'):
        output.print_md(u'  - Mixed bottom elevations: {0}'.format(
            u', '.join(stats['height_bottom_ambiguous_rooms'])))
    if stats.get('height_bottom_fallback_rooms'):
        output.print_md(u'  - Bottom fallback rooms: {0}'.format(
            u', '.join(stats['height_bottom_fallback_rooms'])))
    if stats.get('height_detector_error'):
        output.print_md(u'  - Height detector fallback reason: `{0}`'.format(stats.get('height_detector_error')))
    for source, count in sorted(stats.get('height_sources', {}).items()):
        output.print_md(u'  - `{0}`：{1}'.format(source, count))
    output.print_md(u'- Doors/Windows：{0}，扣除關聯：{1}'.format(stats['openings'], stats['opening_room_deductions']))
    output.print_md(u'- 略過開口：無尺寸 {0}，無 host 牆 {1}，無房間關聯 {2}，非房間邊界牆 {3}'.format(
        stats['skipped_no_size'],
        stats['skipped_no_host'],
        stats['skipped_no_room'],
        stats['skipped_not_boundary']
    ))
    output.print_md(u'- W 牆面類型：{0}，無牆面塗層/未填房間：{1}（仍已列出房間明細），多重 W 代碼房間：{2}'.format(
        stats['wall_finish_types'],
        stats['missing_wall_finish'],
        stats['multi_wall_finish']
    ))
    output.print_md(u'- 材料版族群：{0}'.format(selected_family or u'未選擇（使用 CSV 備援）'))
    output.print_md(u'- 材料版命中：{0}，材料名稱對照總數：{1}'.format(len(family_material_names), len(material_names)))
    forms.alert(
        u'內牆粉刷 Excel {0}完成。'.format(action_label),
        title=u'內牆粉刷 Excel')


main()
