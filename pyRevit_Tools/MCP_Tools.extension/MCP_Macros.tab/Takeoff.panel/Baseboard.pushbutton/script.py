# -*- coding: utf-8 -*-
from __future__ import unicode_literals

__title__ = u'踢腳\nExcel'
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
    SpatialElement,
    SpatialElementBoundaryLocation,
    SpatialElementBoundaryOptions,
)
from System import String  # noqa: E402
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
ROOM_ASSIGN_PADDING_FT = 1000.0 / 304.8
FIRST_DATA_ROW = 6
SUMMARY_LABEL = u'踢腳數量總計'

# 欄位順序。公式一律用這些名字寫（見 lib\sheet_layout.py）：欄位字母由 layout
# 在寫檔那一刻算出來，中間插一欄不需要回頭改任何一段公式。
SUMMARY_COLUMNS = [
    'room_no',          # 空間編號
    'room_name',        # 空間名稱
    'room_perimeter',   # 周長
    'opening_name',     # 開口名稱
    'opening_count',    # 開口數量
    'opening_width',    # 開口寬
    'opening_subtotal', # 開口小計
    'opening_total',    # 開口合計
    'total',            # 總計
]
SUMMARY_HEADERS = [
    u'空間\n編號', u'空間\n名稱', u'周長', u'名稱', u'數量', u'寬', u'小計',
    '', '',
]
if len(SUMMARY_COLUMNS) != len(SUMMARY_HEADERS):
    raise AssertionError(
        u'SUMMARY_COLUMNS 與 SUMMARY_HEADERS 長度不一致（{0} vs {1}）：'
        u'加欄位時兩邊都要加'.format(
            len(SUMMARY_COLUMNS), len(SUMMARY_HEADERS)))
# 材料欄接在固定欄之後，最後再接一欄「對應圖說」。
DRAWING_COLUMN = 'drawing'
SUMMARY_LAYOUT = sheet_layout.SheetLayout(
    SUMMARY_COLUMNS, first_data_row=FIRST_DATA_ROW, name=u'踢腳數量計算')
FIXED_REPORT_COLS = SUMMARY_LAYOUT.width


def full_layout(material_cols):
    """固定欄 ＋ 材料欄 ＋ 對應圖說欄。"""
    return SUMMARY_LAYOUT.with_columns(
        list(material_cols) + [DRAWING_COLUMN])


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


def room_baseboard(room):
    value = lookup_value(room, [
        u'踢腳',
        u'踢腳塗層',
        u'踢腳材料',
        u'踢腳板',
        'Baseboard',
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


def build_room(room):
    number = room_number(room)
    box = room_box(room)
    boundary = room_boundary_perimeter(room)
    parameter_perimeter = room_perimeter(room)
    perimeter = boundary.get('perimeter') or parameter_perimeter
    perimeter_source = boundary.get('source') if boundary.get('perimeter') else 'parameter'
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
        'baseboard': room_baseboard(room),
        'level': level_name(room),
        'box': box,
        'center': room_center(room, box),
        'area': area,
    }


def baseboard_sort_key(value):
    text = clean(value).upper()
    parts = []
    for part in re.split(r'(\d+)', text):
        if part.isdigit():
            parts.append(int(part))
        else:
            parts.append(part)
    return parts


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


def opening_width(opening):
    width = param_double_m(
        opening,
        ['DOOR_WIDTH', 'FAMILY_WIDTH_PARAM', 'FAMILY_ROUGH_WIDTH_PARAM'],
        [u'寬度', u'粗略寬度', 'Width']
    )
    symbol = getattr(opening, 'Symbol', None)
    if not width and symbol:
        width = param_double_m(
            symbol,
            ['DOOR_WIDTH', 'FAMILY_WIDTH_PARAM', 'FAMILY_ROUGH_WIDTH_PARAM'],
            [u'寬度', u'粗略寬度', 'Width']
        )
    if not width:
        parsed_width, _parsed_height = parse_size_from_name(element_name(symbol) or element_name(opening))
        width = parsed_width
    return width


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


def collect_data():
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
        data = build_room(room)
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
        'doors': 0,
        'door_room_deductions': 0,
        'skipped_no_width': 0,
        'skipped_no_host': 0,
        'skipped_no_room': 0,
        'skipped_not_boundary': 0,
        'missing_baseboard': 0,
        'perimeter_boundary': 0,
        'perimeter_parameter': 0,
        'perimeter_missing': 0,
        'multi_loop_rooms': 0,
    }

    for room in rooms:
        if not room['baseboard']:
            stats['missing_baseboard'] += 1
        source = room.get('perimeter_source')
        if source == 'boundary':
            stats['perimeter_boundary'] += 1
        elif source == 'parameter':
            stats['perimeter_parameter'] += 1
        else:
            stats['perimeter_missing'] += 1
        if (room.get('boundary_loop_count') or 0) > 1:
            stats['multi_loop_rooms'] += 1

    for door in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Doors).WhereElementIsNotElementType():
        if not isinstance(door, FamilyInstance):
            continue
        stats['doors'] += 1
        width = opening_width(door)
        if not width or width <= 0:
            stats['skipped_no_width'] += 1
            continue
        host_id = opening_host_id(door)
        if not host_id:
            stats['skipped_no_host'] += 1
            continue
        linked_rooms = rooms_for_opening(door, rooms, rooms_by_id)
        if not linked_rooms:
            stats['skipped_no_room'] += 1
            continue
        item = {
            'id': element_id_value(door.Id),
            'name': opening_name(door),
            'width': width,
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
            stats['door_room_deductions'] += 1

    material_cols = sorted(list(set([r['baseboard'] for r in rooms if r['baseboard']])), key=baseboard_sort_key)
    stats['baseboard_types'] = len(material_cols)
    return rooms, openings_by_room, material_cols, stats


def grouped_openings(openings):
    groups = {}
    for opening in openings:
        width = opening.get('width')
        if not width or width <= 0:
            continue
        key = '{0}||{1}'.format(opening.get('name') or 'Door', fixed2(width))
        if key not in groups:
            groups[key] = {
                'name': opening.get('name') or 'Door',
                'width': width,
                'count': 0,
            }
        groups[key]['count'] += 1
    # list() 包起來：IronPython 2.7 的 dict.values() 本來就回 list，包了行為不變。
    # 少了它，離線的 main() 接線測試（跑 CPython 3）會在這裡因為 view 沒有
    # .sort() 而中斷，整顆按鈕的產表流程就測不到。
    result = list(groups.values())
    result.sort(key=lambda item: (item['name'], item['width']))
    return result


def make_rows(rooms, openings_by_room, material_cols):
    rows = []
    full = full_layout(material_cols)

    for room in rooms:
        openings = grouped_openings(openings_by_room.get(room['element_id'], []))
        row_count = max(1, len(openings))
        material = room['baseboard'] if room['baseboard'] in material_cols \
            else None
        for i in range(row_count):
            row = full.blank_row()
            if i == 0:
                full.put(row, 'room_no', room['number'])
                full.put(row, 'room_name', room['name'])
                full.put(row, 'room_perimeter', fixed2(room['perimeter']))
                full.put(row, 'opening_total', 'OPENING_TOTAL_FORMULA')
                full.put(row, 'total', 'TOTAL_FORMULA')
                full.put(row, DRAWING_COLUMN, room.get('source_label') or '')
                if material is not None:
                    full.put(row, material, 'MATERIAL_FORMULA')

            if i < len(openings):
                opening = openings[i]
                full.put(row, 'opening_name', opening['name'])
                full.put(row, 'opening_count', opening['count'])
                full.put(row, 'opening_width', fixed2(opening['width']))
                full.put(row, 'opening_subtotal', 'OPENING_SUBTOTAL_FORMULA')

            rows.append(row)

    return fill_formulas(rows, material_cols)


def excel_col(index):
    result = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def fill_formulas(rows, material_cols):
    """把佔位字串換成真正的公式。

    公式一律用欄位名稱寫，字母由 SUMMARY_LAYOUT 產生——欄位一搬動，寫死的字母
    不會跟著動，公式不會壞掉，只會安靜地指到隔壁那一欄。
    """
    layout = SUMMARY_LAYOUT
    full = full_layout(material_cols)
    for i, row in enumerate(rows):
        row_number = FIRST_DATA_ROW + i
        if layout.get(row, 'opening_subtotal') == 'OPENING_SUBTOTAL_FORMULA':
            layout.put(row, 'opening_subtotal', layout.formula(
                row_number, '{opening_count}*{opening_width}'))
        if layout.get(row, 'opening_total') == 'OPENING_TOTAL_FORMULA':
            start_row = (row_number
                         if layout.get(row, 'opening_subtotal') else None)
            end_row = start_row
            look = 1
            while (i + look < len(rows)
                   and not layout.get(rows[i + look], 'room_no')
                   and not layout.get(rows[i + look], 'room_name')
                   and layout.get(rows[i + look], 'opening_subtotal')):
                end_row = row_number + look
                look += 1
            if start_row and end_row and end_row != start_row:
                layout.put(row, 'opening_total',
                           layout.sum_of('opening_subtotal', start_row,
                                         end_row))
            elif start_row:
                layout.put(row, 'opening_total',
                           layout.formula(start_row, '{opening_subtotal}'))
            else:
                layout.put(row, 'opening_total', '=0')
        if layout.get(row, 'total') == 'TOTAL_FORMULA':
            layout.put(row, 'total', layout.formula(
                row_number, '{room_perimeter}-{opening_total}'))
        for material in material_cols:
            if full.get(row, material) == 'MATERIAL_FORMULA':
                full.put(row, material,
                         layout.formula(row_number, '{total}'))
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
    total_cols = FIXED_REPORT_COLS + len(material_cols) + 1
    drawing_col = total_cols - 1
    blank_tail = [''] * (total_cols - 1)
    values = []
    values.append([u'工程採購數量計算表'] + blank_tail)
    values.append([project_title] + blank_tail)
    values.append([u'踢腳數量計算表'] + blank_tail)

    full = full_layout(material_cols)
    section = full.row_from({
        'room_no': u'樓別名稱',
        'opening_name': u'開口',
        'opening_total': u'開口合計',
        'total': u'總計',
    })
    for material in material_cols:
        full.put(section, material, material)
    full.put(section, DRAWING_COLUMN, u'對應圖說')
    values.append(section)

    material_name_headers = [material_names.get(clean(material).upper(), '') for material in material_cols]
    values.append(list(SUMMARY_HEADERS) + material_name_headers + [''])
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

    # 欄位範圍一律問 layout：區段的起訖要跟該區段的標題對齊
    # （見 build_sheet_values），字母寫死的話欄位一搬動就會錯開。
    layout = SUMMARY_LAYOUT
    first_col = layout.col(SUMMARY_COLUMNS[0])
    last_fixed_col = layout.col(SUMMARY_COLUMNS[-1])
    last_col = sheet_layout.column_letter(total_cols - 1)

    def span(from_key, to_key, row_index):
        return '{0}{2}:{1}{2}'.format(layout.col(from_key),
                                      layout.col(to_key), row_index)

    merge_refs = [
        '{0}1:{1}1'.format(first_col, last_col),
        '{0}2:{1}2'.format(first_col, last_col),
        '{0}3:{1}3'.format(first_col, last_col),
        span('room_no', 'room_perimeter', 4),
        span('opening_name', 'opening_subtotal', 4),
        '{0}4:{0}5'.format(layout.col('opening_total')),
        '{0}4:{0}5'.format(layout.col('total')),
        # drawing_col 在這個函式裡是 1 基欄號
        '{0}4:{0}5'.format(sheet_layout.column_letter(drawing_col - 1)),
    ]
    if summary_row_index:
        merge_refs.append('{0}{1}:{2}{1}'.format(
            first_col, summary_row_index, last_fixed_col))
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
        '<col min="4" max="4" width="18" customWidth="1"/>',
        '<col min="5" max="5" width="8" customWidth="1"/>',
        '<col min="6" max="9" width="12" customWidth="1"/>',
    ]
    if material_end >= material_start:
        col_defs.append('<col min="{0}" max="{1}" width="16" customWidth="1"/>'.format(material_start, material_end))
    col_defs.append('<col min="{0}" max="{0}" width="16" customWidth="1"/>'.format(total_cols))
    cols = ''.join(col_defs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<dimension ref="A1:{0}{1}"/>'  # sheet-layout: ignore（A1 是工作表原點，恆定）
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
                        '<sheets><sheet name="踢腳數量計算" sheetId="1" r:id="rId1"/></sheets>'
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
    material_cols = sorted(
        list(all_material_cols), key=baseboard_sort_key)
    all_rooms.sort(key=lambda room: (
        clean(room.get('source_label')),
        floor_sort_key(room.get('level') or room.get('number')),
        room_takeoff_sources_logic.room_number_sort_key(
            room.get('number')),
        clean(room.get('name'))))
    all_stats['rooms'] = len(all_rooms)
    all_stats['baseboard_types'] = len(material_cols)
    return all_rooms, all_openings, material_cols, all_stats, sources


def main():
    if not doc:
        forms.alert(u'請先開啟 Revit 專案檔，再匯出踢腳 Excel。', title=u'踢腳 Excel')
        return

    host_doc = doc
    options = takeoff_entry.choose_options(
        host_doc, u'踢腳 Excel', allow_host=True, host_required=False)
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
                    [(u'踢腳數量計算', u'踢腳')],
                    summary_specs={
                        u'踢腳': {
                            'label': SUMMARY_LABEL,
                            'header_label': u'樓別名稱',
                            'data_header_label': u'空間名稱',
                        },
                    }))
            outpath = workbook_path
        except takeoff_direct_publish.WorkbookPublishError as exc:
            forms.alert(
                u'更新主要 Excel 失敗：\n{0}'.format(exc),
                title=u'踢腳 Excel')
            return
        finally:
            takeoff_direct_publish.remove_file_quietly(temp_path)
    else:
        default_name = safe_filename(project_title) + u'_踢腳數量計算.xlsx'
        outpath = forms.save_file(
            file_ext='xlsx',
            default_name=default_name,
            title=u'匯出踢腳數量計算 Excel'
        )
        if not outpath:
            return
        if not outpath.lower().endswith('.xlsx'):
            outpath += '.xlsx'
        write_xlsx(outpath, values)

    output.print_md(
        u'## 踢腳 Excel {0}完成'.format(
            u'更新' if workbook_path else u'匯出'))
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
    output.print_md(u'- Doors：{0}，扣除關聯：{1}'.format(stats['doors'], stats['door_room_deductions']))
    output.print_md(u'- 略過門：無寬度 {0}，無 host 牆 {1}，無房間關聯 {2}，非房間邊界牆 {3}'.format(
        stats['skipped_no_width'],
        stats['skipped_no_host'],
        stats['skipped_no_room'],
        stats['skipped_not_boundary']
    ))
    output.print_md(u'- 踢腳類型：{0}，無踢腳/未填踢腳房間：{1}（仍已列出房間明細）'.format(
        stats['baseboard_types'],
        stats['missing_baseboard']
    ))
    output.print_md(u'- 材料版族群：{0}'.format(selected_family or u'未選擇（使用 CSV 備援）'))
    output.print_md(u'- 材料版命中：{0}，材料名稱對照總數：{1}'.format(len(family_material_names), len(material_names)))
    forms.alert(
        u'踢腳 Excel {0}完成。'.format(
            u'更新' if workbook_path else u'匯出'),
        title=u'踢腳 Excel')


main()
