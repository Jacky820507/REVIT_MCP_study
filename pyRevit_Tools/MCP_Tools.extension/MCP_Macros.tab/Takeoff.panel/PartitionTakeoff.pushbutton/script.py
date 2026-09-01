# -*- coding: utf-8 -*-
from __future__ import unicode_literals

__title__ = u'輕隔間\nExcel'
__author__ = 'Codex'

import math
import os
import re

import clr

clr.AddReference('System.IO.Compression')
clr.AddReference('System.IO.Compression.FileSystem')

from Autodesk.Revit.DB import (  # noqa: E402
    BuiltInCategory,
    BuiltInParameter,
    Element,
    FamilyInstance,
    FilteredElementCollector,
    Level,
    LocationCurve,
    SpatialElement,
    Wall,
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

try:
    reload(takeoff_direct_publish)
except Exception:
    pass

# 高度口徑（比照 InteriorWallPaint「內牆粉刷」的頂部偵測，牆底不比照）：
#
#   頂部  用 scaffold_height.resolve_room_heights 的幾何射線結果，取「上層樓板底」。
#         天花來源（actual-ceiling-*）一律排除——輕隔間牆做到樓板底，不是做到天花，
#         見 domain/revit-partition-takeoff.md 第 105 行。射線取不到就退回本檔既有的
#         樓層標高−樓板厚度公式，再取不到才退回樓層到樓層（附警語）。
#   牆底  維持牆自己的結構樓層標高＋底部偏移，不採內牆那套偵測到的完成地板面：
#         輕隔間牆立在結構樓板上、地坪面層之前施作，從完成面起算會系統性短計。
#
# 禁止改用 scaffold_height_logic.effective_wall_height()：那支把牆高直接截短成房間
# 淨高，等同把面積差異藏進牆高欄，違反同文件第 160 行（2026-08-06 曾造成面積 −28.7%）。
try:
    import scaffold_height  # noqa: E402
    try:
        reload(scaffold_height)
    except Exception:
        pass
    SCAFFOLD_HEIGHT_IMPORT_ERROR = ''
except Exception as _scaffold_import_error:
    scaffold_height = None
    SCAFFOLD_HEIGHT_IMPORT_ERROR = u'{0}'.format(_scaffold_import_error)


FT_TO_M = 0.3048
SQFT_TO_SQM = 0.09290304
ROOM_ASSIGN_PADDING_FT = 750.0 / 304.8
USE_WALL_AREA_FOR_EFFECTIVE_HEIGHT = False
HEIGHT_BUCKET_SIZE_M = 0.05
FULL_HEIGHT_MIN_M = 2.70
SLAB_MATCH_TOLERANCE_M = 0.80
SLAB_XY_PADDING_FT = 300.0 / 304.8
ATTACHED_GEOMETRY_DELTA_M = 0.15
# 牆頂超出目標樓層這個距離以上，視為跨樓層高牆，不套目標高度
TALL_WALL_TOLERANCE_M = 0.35
FIRST_DATA_ROW = 6
SUMMARY_LABEL = '輕隔間數量總計'

# 欄位順序。公式一律用這些名字寫（見 lib\sheet_layout.py）：欄位字母由 layout
# 在寫檔那一刻算出來，中間插一欄不需要回頭改任何一段公式。
SUMMARY_COLUMNS = [
    'room_no',          # 編號
    'room_name',        # 空間名稱
    'room_perimeter',   # 空間周長
    'wall_type',        # 輕隔間牆類型
    'length',           # 牆長
    'height',           # 牆高
    'area',             # 面積
    'area_subtotal',    # 小計
    'opening_name',     # 開口名稱
    'opening_count',    # 開口數量
    'opening_width',    # 開口長
    'opening_height',   # 開口高
    'opening_area',     # 開口面積
    'opening_subtotal', # 開口小計
    'total',            # 總計
]
# 與 SUMMARY_COLUMNS 一一對應的表頭文字。
SUMMARY_HEADERS = [
    '編號', '空間名稱', '空間周長', '輕隔間牆類型', '牆長', '牆高', '面積',
    '小計', '名稱', '數量', '長', '高', '面積', '小計', '總計',
]
if len(SUMMARY_COLUMNS) != len(SUMMARY_HEADERS):
    raise AssertionError(
        'SUMMARY_COLUMNS 與 SUMMARY_HEADERS 長度不一致（{0} vs {1}）：'
        '加欄位時兩邊都要加'.format(
            len(SUMMARY_COLUMNS), len(SUMMARY_HEADERS)))
# 每種牆型一欄接在這些固定欄之後（with_columns）。
SUMMARY_LAYOUT = sheet_layout.SheetLayout(
    SUMMARY_COLUMNS, first_data_row=FIRST_DATA_ROW, name='輕隔間數量計算')
FIXED_REPORT_COLS = SUMMARY_LAYOUT.width

# 主檔分頁名：手算驗證放逐房逐牆明細，實際數量放各 TYPE 對照
GENERATED_SHEET = '輕隔間數量計算'
VERIFY_SHEET = '輕隔間(手算驗證)'
ACTUAL_SHEET = '輕隔間(實際數量)'
ACTUAL_TYPE_COL = 1      # A：輕隔間類型
# B「Excel(手算)」＝本按鈕算出來的量，連到「輕隔間(手算驗證)」的合計列。
# C「Revit(自動)」由使用者自行填寫（通常是從 Revit 明細表抄的數字），本程式
# 一律不碰，兩欄才能互為對照。
ACTUAL_TOTAL_COL = 2

# 逐來源掃描時由 collect_selected_sources 換掉；None 表示不限樓層
ACTIVE_ALLOWED_LEVEL_IDS = None

# 名稱含 TYPE 但不列入計算的牆類型（模型裡的錯誤類型）。
# 2026-08-07 使用者指定排除 Type-E 複壁：本案 9 個正規類型都是「TYPE X 」空格
# 寫法，只有它用連字號，且來自連結模型；扣掉後報表長度 6132.32 m 與主模型
# 「輕隔間牆明細表」的 6131.99 m 吻合。要再排除其他類型就加在這裡。
EXCLUDED_WALL_TYPE_NAMES = (
    'Type-E 複壁',
)

# ---------------------------------------------------------------------------
# 版面：整份比照使用者提供的範本
# 「U-PARK-AR-物流中心_09044_輕隔間數量計算_0521.xlsx」（2026-08-06 量測）。
# 不套 takeoff_excel_styles.FONTS_XML，因為那套把第 2、3 列當成同一種副標題，
# 範本這兩列分別是 14pt 與 12pt。字型索引：
#   0 內文 10 / 1 合計 10 粗體 / 2 標題 24 / 3 專案 14 / 4 表名 12
# 框線不能沿用 takeoff_excel_styles.BORDERS_XML：那份把細框線放在 borders[0]，
# 但 OOXML 規定索引 0 必須是「無框線」的預設項，Excel 會直接忽略它——實測產出
# 的檔案 264 格 × 4 邊全部沒有框線。這裡改成索引 0 留空、細框線放索引 1，
# 並在每個 cellXf 明確 borderId="1" applyBorder="1"。
PARTITION_BORDERS_XML = (
    '<borders count="2">'
    '<border><left/><right/><top/><bottom/><diagonal/></border>'
    '<border>'
    '<left style="thin"><color rgb="FF000000"/></left>'
    '<right style="thin"><color rgb="FF000000"/></right>'
    '<top style="thin"><color rgb="FF000000"/></top>'
    '<bottom style="thin"><color rgb="FF000000"/></bottom>'
    '<diagonal/>'
    '</border>'
    '</borders>'
)

PARTITION_FONTS_XML = (
    '<fonts count="5">'
    '<font><sz val="10"/><name val="標楷體"/></font>'
    '<font><b/><sz val="10"/><name val="標楷體"/></font>'
    '<font><sz val="24"/><name val="標楷體"/></font>'
    '<font><sz val="14"/><name val="標楷體"/></font>'
    '<font><sz val="12"/><name val="標楷體"/></font>'
    '</fonts>'
)

# cellXfs 索引，與 write_xlsx 內的順序一一對應
# 索引 0 刻意空著放一個沒人用的預設項：Excel 會把 cellXfs[0] 當成內建 Normal
# 樣式，即使儲存格明寫 s="0" 也不吃它的框線設定（實測資料列 120 格全無框線）。
# 真正在用的樣式一律從 1 開始。
STYLE_DATA = 1       # 內文：水平一般、垂直置中
STYLE_CENTER = 2     # 第 4、5 列群組標題與欄位標題：水平垂直皆置中
STYLE_SUMMARY = 3    # 合計列：粗體置中
STYLE_TITLE = 4      # 第 1 列 24pt 靠左
STYLE_PROJECT = 5    # 第 2 列 14pt 靠左
STYLE_TABLE_NAME = 6 # 第 3 列 12pt 靠左

# 兩套版面，字型／對齊／合併／框線完全相同，差別只在欄寬、D 欄是否隱藏、
# 以及資料列高。A~O 取各自範本的實測值；D 與 TYPE 欄依實際名稱用
# autofit_width() 算，因為 TYPE 數量與名稱會隨模型變動，寫死會對不上。
#
# LAYOUT_STANDALONE  範本：桌面 U-PARK-AR-..._輕隔間數量計算_0521.xlsx
# LAYOUT_PUBLISH     範本：物流中心工項-0806.xls 之「輕隔間(手算驗證)」
#                    （該表把 D 欄隱藏，TYPE 名稱看 P 欄以後的欄位標題）
LAYOUT_STANDALONE = {
    'col_widths': [6.00, 23.71, 9.57, 40.43, 26.86, 7.71, 7.71, 7.71,
                   13.71, 4.14, 7.71, 7.71, 7.71, 7.71, 7.71],
    'type_width_scale': 1.0,
    'data_row_height': 16.5,
    'hide_type_name_column': False,
}
LAYOUT_PUBLISH = {
    'col_widths': [5.75, 24.38, 10.25, 24.38, 27.63, 8.38, 8.38, 8.38,
                   14.5, 4.88, 8.38, 8.38, 8.38, 8.38, 8.38],
    # 兩表的固定欄寬差一個定值（8.38 / 7.71），因為 .xls 主檔的內建字型與
    # .xlsx 匯出檔不同，欄寬單位的基準跟著不同；TYPE 欄同步放大。
    'type_width_scale': 8.38 / 7.71,
    'data_row_height': 14.25,
    'hide_type_name_column': True,
}

# 範本的 TYPE 欄寬 / 顯示字數 在 6 欄上都落在 1.122，據此重建 autofit 結果
AUTOFIT_WIDTH_RATIO = 1.122
TITLE_ROW_HEIGHT = 32.25
PROJECT_ROW_HEIGHT = 19.5
HEADER_ROW_HEIGHT = 16.5


doc = revit.doc
output = script.get_output()

if doc is None:
    forms.alert('請先開啟 Revit 專案檔，再匯出輕隔間 Excel。', exitscript=True)


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


def parse_number(value):
    text = clean(value).replace(',', '')
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    return float(match.group(0)) if match else None


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
        value = re.sub(r'\s*{0}\s*$'.format(re.escape(number)), '', value, flags=re.I).strip()
    return value


def room_perimeter(room):
    param = get_bip_param(room, 'ROOM_PERIMETER')
    if param and param.HasValue:
        try:
            return fixed2(param.AsDouble() * FT_TO_M)
        except Exception:
            pass
    value = parse_number(lookup_value(room, ['周長', 'Perimeter']))
    return fixed2(value) if value is not None else ''


def level_name(element):
    try:
        level = doc.GetElement(element.LevelId)
        if level:
            return element_name(level)
    except Exception:
        pass
    return lookup_value(element, ['樓層', '底部約束', 'Level'])


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


def parse_bool_text(value):
    text = clean(value).upper()
    if not text:
        return None
    if text in ('1', 'YES', 'Y', 'TRUE', 'T', '是', '真'):
        return True
    if text in ('0', 'NO', 'N', 'FALSE', 'F', '否', '假'):
        return False
    return None


def param_bool(element, bip_names, lookup_names=None):
    lookup_names = lookup_names or []
    for bip_name in bip_names:
        param = get_bip_param(element, bip_name)
        if param and param.HasValue:
            try:
                return param.AsInteger() != 0
            except Exception:
                value = parse_bool_text(param.AsValueString() or param.AsString())
                if value is not None:
                    return value
    for name in lookup_names:
        try:
            param = element.LookupParameter(name)
        except Exception:
            param = None
        if param and param.HasValue:
            value = parse_bool_text(param.AsValueString() or param.AsString())
            if value is not None:
                return value
    return False


def round_to_step(value, step):
    if value is None or not step:
        return value
    return math.floor((value / step) + 0.5) * step


def build_level_catalog():
    entries = []
    by_id = {}

    for level in FilteredElementCollector(doc).OfClass(Level):
        try:
            elevation = level.Elevation * FT_TO_M
        except Exception:
            continue
        name = element_name(level)
        entry = {
            'id': element_id_value(level.Id),
            'name': name,
            'key': normalize_level(name),
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


def floor_thickness_m(floor):
    thickness = param_double_m(floor, ['FLOOR_ATTR_THICKNESS_PARAM'], ['厚度', 'Thickness'])
    if not thickness:
        try:
            floor_type = doc.GetElement(floor.GetTypeId())
        except Exception:
            floor_type = None
        if floor_type:
            thickness = param_double_m(floor_type, ['FLOOR_ATTR_THICKNESS_PARAM'], ['厚度', 'Thickness'])

    box = None
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
        name = '{0} {1}'.format(element_name(floor), floor_type_name)
        add_slab_thickness_group(thickness_groups, level_key, thickness, name)

    thickness_by_level = {}
    for level_key, items in thickness_groups.items():
        thickness = select_group_thickness(items)
        if thickness:
            thickness_by_level[level_key] = thickness

    return {
        'levels': level_catalog,
        'thickness_by_level': thickness_by_level,
    }


def point_inside_box(point, box, padding):
    if not box:
        return False
    return (
        point[0] >= box.Min.X - padding and
        point[0] <= box.Max.X + padding and
        point[1] >= box.Min.Y - padding and
        point[1] <= box.Max.Y + padding
    )


def distance_to_box(point, box):
    if not box:
        return float('inf')
    dx = box.Min.X - point[0] if point[0] < box.Min.X else point[0] - box.Max.X if point[0] > box.Max.X else 0
    dy = box.Min.Y - point[1] if point[1] < box.Min.Y else point[1] - box.Max.Y if point[1] > box.Max.Y else 0
    return math.sqrt(dx * dx + dy * dy)


def segment_touches_box(wall, box, padding):
    if not box:
        return False
    for t in (0, 0.25, 0.5, 0.75, 1):
        x = wall['start'][0] + (wall['end'][0] - wall['start'][0]) * t
        y = wall['start'][1] + (wall['end'][1] - wall['start'][1]) * t
        if point_inside_box((x, y), box, padding):
            return True
    return False


def floor_sort_key(number):
    text = clean(number).upper()
    if text.startswith('BS') or text.startswith('FN'):
        return (0, 0, parse_number(text) or 0, text)
    match = re.match(r'^([BFR])(\d{2,4})$', text)
    if not match:
        return (9, 999, 999999, text)
    prefix = match.group(1)
    digits = int(match.group(2))
    floor = digits // 100 if digits >= 100 else digits
    group = 1 if prefix == 'B' else 2 if prefix == 'F' else 3
    return (group, floor, digits, text)


def type_sort_key(type_name):
    """TYPE 排序：主字母優先，後綴字母緊接在同一主字母之後。

    A > B > C > Ca > D > E > F > G。舊版把整串字母當 26 進位（CA=79），
    會讓 Ca 掉到 G 後面。
    """
    text = clean(type_name).upper()
    match = re.search(r'TYPE[-\s]*([A-Z]+)(\d*)', text)
    if not match:
        return (999, '', 999, text)
    letters = match.group(1)
    rank = ord(letters[0]) - 64
    suffix = letters[1:]
    number = int(match.group(2)) if match.group(2) else 0
    return (rank, suffix, number, text)


def safe_element_id_value(element_id):
    """element_id_value() 對 None／InvalidElementId 會拋例外，這裡回 None。"""
    if not valid_element_id(element_id):
        return None
    try:
        return element_id_value(element_id)
    except Exception:
        return None


def room_level_in_scope(room):
    if ACTIVE_ALLOWED_LEVEL_IDS is None:
        return True
    return safe_element_id_value(
        getattr(room, 'LevelId', None)) in ACTIVE_ALLOWED_LEVEL_IDS


def wall_level_in_scope(wall):
    """牆以底部約束樓層判定，取不到再退回牆自己的 LevelId。"""
    if ACTIVE_ALLOWED_LEVEL_IDS is None:
        return True
    base_value = safe_element_id_value(
        param_element_id(wall, 'WALL_BASE_CONSTRAINT'))
    if base_value is not None and base_value in ACTIVE_ALLOWED_LEVEL_IDS:
        return True
    return safe_element_id_value(
        getattr(wall, 'LevelId', None)) in ACTIVE_ALLOWED_LEVEL_IDS


def is_excluded_type(type_name):
    """使用者指定不列入計算的牆類型。

    比對走 normalize_type_key()（去空白、轉大寫），大小寫與全半形空白的
    差異都不影響。被排除的牆會計入 stats['excluded_walls'] 並列在輸出面板，
    不會靜默消失。
    """
    key = normalize_type_key(type_name)
    for name in EXCLUDED_WALL_TYPE_NAMES:
        if normalize_type_key(name) == key:
            return True
    return False


def is_partition_type(type_name):
    if is_excluded_type(type_name):
        return False
    return 'TYPE' in clean(type_name).upper()


def build_room(room):
    number = room_number(room)
    box = room.get_BoundingBox(None)
    center = (0, 0)
    if box:
        center = ((box.Min.X + box.Max.X) / 2.0, (box.Min.Y + box.Max.Y) / 2.0)
    area = None
    param = get_bip_param(room, 'ROOM_AREA')
    if param and param.HasValue:
        try:
            area = param.AsDouble() * SQFT_TO_SQM
        except Exception:
            pass
    return {
        # 'id' 是該來源文件內的原生 ElementId，射線測頂要用它回查 Revit；
        # 'element_id' 會被 rekey_room_records 換成跨來源不衝突的複合鍵。
        'id': element_id_value(room.Id),
        'element_id': element_id_value(room.Id),
        'source_key': '',
        'source_label': '',
        'number': number,
        'name': room_name(room, number),
        'level': normalize_level(level_name(room)),
        'perimeter': room_perimeter(room),
        'area': area,
        'center': center,
        'box': box,
    }


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


def wall_base_level_entry(wall, height_context):
    level_catalog = height_context.get('levels', {})
    base_id = param_element_id(wall, 'WALL_BASE_CONSTRAINT')
    entry = level_entry_from_id(level_catalog, base_id)
    if entry:
        return entry
    return level_entry_from_id(level_catalog, getattr(wall, 'LevelId', None))


def wall_base_elevation_m(wall, height_context):
    entry = wall_base_level_entry(wall, height_context)
    offset = param_double_m(wall, ['WALL_BASE_OFFSET'], ['底部偏移']) or 0
    if entry:
        return entry['elevation'] + offset
    try:
        box = wall.get_BoundingBox(None)
    except Exception:
        box = None
    if box:
        return box.Min.Z * FT_TO_M
    return None


def wall_top_level_entry(wall, height_context, base_elevation):
    level_catalog = height_context.get('levels', {})
    top_id = param_element_id(wall, 'WALL_HEIGHT_TYPE')
    entry = level_entry_from_id(level_catalog, top_id)
    if entry and base_elevation is not None and entry['elevation'] > base_elevation + 0.50:
        return entry

    for candidate in level_catalog.get('entries', []):
        if base_elevation is not None and candidate['elevation'] > base_elevation + 1.50:
            return candidate
    return None


def wall_top_attached(wall):
    return param_bool(
        wall,
        ['WALL_TOP_IS_ATTACHED'],
        ['貼附頂/底', '頂部已貼附', '頂部貼附', 'Top is Attached', 'Top Attached']
    )


def wall_height_guard(source_height, target_height, top_attached,
                      slab_thickness=None):
    """牆的實際高度與目標高度落差過大時，保留 Revit 實際高度。

    樓板底公式與射線頂標高兩條路共用這一套，判斷門檻才不會分歧。三種例外：

    revit-low-wall     矮於 FULL_HEIGHT_MIN_M 的矮牆。
    revit-partial-wall 確實沒做到頂的牆（比目標矮超過 0.35 m 且未貼附頂部）。
    revit-tall-wall    比目標高出「樓板厚度 + 0.35 m」以上的牆。因為
                       目標高度 = 上層樓層標高 − 樓板厚度 − 牆底標高，
                       這個門檻等同「牆頂超出目標樓層 0.35 m 以上」，
                       代表這道牆根本跨越了該樓層（跨樓層高牆、通到屋頂的
                       庫板牆），目標樓層對它不適用。此時若照樣套目標高度
                       就是把面積差異藏進牆高欄，違反
                       domain/revit-partition-takeoff.md 第 160 行。
    """
    if source_height and source_height < FULL_HEIGHT_MIN_M:
        return {
            'height': source_height,
            'source': 'revit-low-wall',
            'target_level': '',
            'slab_thickness': None,
        }
    if (not top_attached) and source_height and source_height < target_height - 0.35:
        return {
            'height': source_height,
            'source': 'revit-partial-wall',
            'target_level': '',
            'slab_thickness': None,
        }
    tall_allowance = (slab_thickness or 0.0) + TALL_WALL_TOLERANCE_M
    if source_height and source_height > target_height + tall_allowance:
        return {
            'height': round_to_step(source_height, HEIGHT_BUCKET_SIZE_M),
            'source': 'revit-tall-wall',
            'target_level': '',
            'slab_thickness': None,
        }
    return None


def wall_slab_bottom_height_info(wall, raw_height, height_context, top_attached):
    base_elevation = wall_base_elevation_m(wall, height_context)
    if base_elevation is None:
        return None

    top_entry = wall_top_level_entry(wall, height_context, base_elevation)
    if not top_entry:
        return None

    # 比照 InteriorWallPaint.room_slab_bottom_height_info：查不到上層代表樓板厚度時
    # 不整個放棄，改用樓層到樓層高度並附警語，讓這道牆仍有可解釋的來源。
    thickness = height_context.get('thickness_by_level', {}).get(top_entry['key'])
    height = top_entry['elevation'] - base_elevation
    warnings = []
    if thickness:
        height -= thickness
        full_source = ('attach-top-bottom-level-slab-bottom' if top_attached
                       else 'level-to-upper-slab-bottom')
    else:
        full_source = ('attach-top-bottom-level-to-level' if top_attached
                       else 'level-to-level-no-slab-thickness')
        warnings = [u'找不到上層代表樓板厚度，牆高暫採樓層到樓層高度']
    if height <= 0:
        return None

    guarded = wall_height_guard(
        raw_height or wall_bbox_height_m(wall), height, top_attached,
        slab_thickness=thickness)
    if guarded:
        return guarded

    return {
        'height': round_to_step(height, HEIGHT_BUCKET_SIZE_M),
        'source': full_source,
        'target_level': top_entry['key'] or top_entry['name'],
        'slab_thickness': thickness,
        'slab_formula_height': height,
        'warnings': warnings,
    }


def wall_report_height_info(wall, raw_height, height_context, top_attached):
    info = wall_slab_bottom_height_info(wall, raw_height, height_context, top_attached)
    if info and info.get('height'):
        return info

    fallback = raw_height or wall_bbox_height_m(wall)
    return {
        'height': fallback,
        'source': 'attach-top-bottom-revit-height' if top_attached else 'revit-wall-height',
        'target_level': '',
        'slab_thickness': None,
        'slab_formula_height': None,
    }


def wall_opening_area_raw(wall):
    total = 0
    for op in wall.get('openings', []):
        width = op.get('width')
        height = op.get('height')
        if width and height and width > 0 and height > 0:
            total += width * height
    return total


def finalize_attached_wall_heights(walls):
    for wall in walls:
        if not wall.get('top_attached'):
            continue

        area = wall.get('area')
        length = wall.get('length')
        if not area or not length or length <= 0:
            continue

        attached_height = (area + wall_opening_area_raw(wall)) / length
        if attached_height < FULL_HEIGHT_MIN_M:
            continue

        formula_height = wall.get('slab_formula_height')
        if formula_height and abs(attached_height - formula_height) <= ATTACHED_GEOMETRY_DELTA_M:
            continue

        wall['height'] = round_to_step(attached_height, HEIGHT_BUCKET_SIZE_M)
        wall['height_source'] = 'attach-top-bottom-geometry'


# 天花來源不採用：輕隔間牆做到上層樓板底，不是做到天花。
CEILING_TOP_SOURCES = ('actual-ceiling-ray', 'actual-ceiling-bbox-fallback')


def resolve_room_top_elevations(rooms):
    """比照內牆的頂部偵測：用幾何射線取每個房間頂面的「絕對標高」。

    只收上層樓板底類的結果，天花來源整筆略過（該房間的牆退回本檔的樓層標高−
    樓板厚度公式）。回傳 (tops_by_room_id, stats)。

    這裡刻意只取「頂」：牆底仍由 wall_base_elevation_m 用牆自己的結構樓層標高
    決定，不採內牆那套偵測到的完成地板面，見檔頭高度口徑說明。
    """
    stats = {
        'detector': 'legacy',
        'detector_view': '',
        'error': SCAFFOLD_HEIGHT_IMPORT_ERROR,
        'resolved_rooms': 0,
        'ceiling_skipped': 0,
        'counts': {},
    }
    tops = {}
    if not rooms or scaffold_height is None:
        return tops, stats

    room_ids = [room['id'] for room in rooms if room.get('id')]
    if not room_ids:
        return tops, stats

    try:
        resolved = scaffold_height.resolve_room_heights(
            doc, room_ids, detect_lower_floor=True)
    except Exception as resolve_error:
        stats['error'] = u'{0}'.format(resolve_error)
        return tops, stats

    resolved_rooms = resolved.get('rooms') or {}
    if not resolved_rooms:
        stats['error'] = u'resolve_room_heights 沒有回傳任何房間高度'
        return tops, stats

    stats['detector'] = 'reference-intersector'
    stats['detector_view'] = resolved.get('detector_view') or ''
    stats['counts'] = resolved.get('counts') or {}
    stats['error'] = ''

    for room in rooms:
        info = resolved_rooms.get(str(room.get('id')))
        if not info:
            continue
        source = clean(info.get('source'))
        if source in CEILING_TOP_SOURCES:
            stats['ceiling_skipped'] += 1
            continue
        bottom_elevation = info.get('bottom_elevation_m')
        height = info.get('raw_height') or info.get('height')
        if bottom_elevation is None or not height or height <= 0:
            continue
        tops[room['id']] = {
            'elevation': bottom_elevation + height,
            'source': source or 'upper-floor-bottom-ray',
            'warnings': info.get('warnings') or [],
        }
        stats['resolved_rooms'] += 1
    return tops, stats


def apply_room_top_to_wall(wall, room_top):
    """用房間頂面的絕對標高重算這道牆的牆高，牆底維持牆自己的結構樓層標高。"""
    if not room_top:
        return False
    if wall.get('height_source') == 'attach-top-bottom-geometry':
        # Revit 牆面積反推的貼附高度屬幾何實測，優先於射線與任何公式
        return False

    base_elevation = wall.get('base_elevation')
    if base_elevation is None:
        return False
    target = room_top['elevation'] - base_elevation
    if target <= 0:
        return False

    guarded = wall_height_guard(
        wall.get('model_height'), target, wall.get('top_attached'),
        slab_thickness=wall.get('slab_thickness'))
    if guarded:
        wall['height'] = guarded['height']
        wall['height_source'] = guarded['source']
        return True

    wall['height'] = round_to_step(target, HEIGHT_BUCKET_SIZE_M)
    wall['height_source'] = ('attach-top-bottom-room-top-ray'
                             if wall.get('top_attached') else 'room-top-ray')
    wall['height_target_level'] = ''
    wall['height_warnings'] = room_top.get('warnings') or []
    return True


def build_wall(wall, height_context):
    loc = wall.Location
    if not isinstance(loc, LocationCurve):
        return None
    curve = loc.Curve
    start = curve.GetEndPoint(0)
    end = curve.GetEndPoint(1)
    length = curve.Length * FT_TO_M
    raw_height = param_double_m(wall, ['WALL_USER_HEIGHT_PARAM'], ['不連續高度'])
    top_attached = wall_top_attached(wall)
    height_info = wall_report_height_info(wall, raw_height, height_context, top_attached)

    area = None
    param = get_bip_param(wall, 'HOST_AREA_COMPUTED')
    if param and param.HasValue:
        try:
            area = param.AsDouble() * SQFT_TO_SQM
        except Exception:
            area = None
    if area is None:
        area = parse_number(lookup_value(wall, ['面積', 'Area']))

    return {
        'element_id': element_id_value(wall.Id),
        'type_name': element_name(wall.WallType),
        'room_number_param': lookup_value(wall, ['空間編號']),
        'room_name_param': lookup_value(wall, ['空間名稱']),
        'level': normalize_level(level_name(wall)),
        'length': length,
        'height': height_info.get('height'),
        'raw_height': raw_height,
        # Revit 模型上這道牆的實際高度，供歸房後重算時判斷矮牆／未到頂牆
        'model_height': raw_height or wall_bbox_height_m(wall),
        'height_source': height_info.get('source'),
        'height_target_level': height_info.get('target_level'),
        'height_warnings': height_info.get('warnings') or [],
        'slab_thickness': height_info.get('slab_thickness'),
        'slab_formula_height': height_info.get('slab_formula_height'),
        'base_elevation': wall_base_elevation_m(wall, height_context),
        'top_attached': top_attached,
        'area': area,
        'start': (start.X, start.Y),
        'end': (end.X, end.Y),
        'openings': [],
    }


def wall_midpoint(wall):
    return ((wall['start'][0] + wall['end'][0]) / 2.0, (wall['start'][1] + wall['end'][1]) / 2.0)


def assign_wall_to_room(wall, rooms, rooms_by_number):
    rn = clean(wall.get('room_number_param')).upper()
    if rn and rn in rooms_by_number:
        return rooms_by_number[rn]

    same_level = [r for r in rooms if r['level'] and wall['level'] and r['level'] == wall['level'] and r['box']]
    pool = same_level or [r for r in rooms if r['box']]
    mid = wall_midpoint(wall)

    best_room = None
    best_score = float('inf')
    for room in pool:
        touches = segment_touches_box(wall, room['box'], ROOM_ASSIGN_PADDING_FT)
        box_distance = distance_to_box(mid, room['box'])
        center_distance = math.sqrt((mid[0] - room['center'][0]) ** 2 + (mid[1] - room['center'][1]) ** 2)
        area_penalty = (room['area'] or 0) * 0.01
        score = (-100000 if touches else 0) + box_distance * 10 + center_distance + area_penalty
        if score < best_score:
            best_room = room
            best_score = score
    return best_room


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
        ['寬度', '粗略寬度']
    )
    height = param_double_m(
        opening,
        ['DOOR_HEIGHT', 'WINDOW_HEIGHT', 'FAMILY_HEIGHT_PARAM', 'FAMILY_ROUGH_HEIGHT_PARAM'],
        ['高度', '粗略高度']
    )
    if not width or not height:
        symbol = getattr(opening, 'Symbol', None)
        if symbol:
            if not width:
                width = param_double_m(symbol, ['DOOR_WIDTH', 'WINDOW_WIDTH', 'FAMILY_WIDTH_PARAM', 'FAMILY_ROUGH_WIDTH_PARAM'], ['寬度', '粗略寬度'])
            if not height:
                height = param_double_m(symbol, ['DOOR_HEIGHT', 'WINDOW_HEIGHT', 'FAMILY_HEIGHT_PARAM', 'FAMILY_ROUGH_HEIGHT_PARAM'], ['高度', '粗略高度'])
    if not width or not height:
        parsed_width, parsed_height = parse_size_from_name(element_name(opening))
        width = width or parsed_width
        height = height or parsed_height
    return (width, height)


def assign_openings_to_host_walls(openings, walls_by_id):
    assigned = 0
    skipped = 0
    for opening in openings:
        if not isinstance(opening, FamilyInstance):
            continue
        host = opening.Host
        if not host:
            skipped += 1
            continue
        host_wall = walls_by_id.get(element_id_value(host.Id))
        if not host_wall:
            skipped += 1
            continue
        width, height = opening_dimensions(opening)
        if not width or not height:
            skipped += 1
            continue
        host_wall['openings'].append({
            'id': element_id_value(opening.Id),
            'name': element_name(opening),
            'width': width,
            'height': height,
        })
        assigned += 1
    return assigned, skipped


def collect_data():
    height_context = build_height_context()
    rooms = []
    for room in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType():
        if not isinstance(room, SpatialElement):
            continue
        if not room_level_in_scope(room):
            continue
        try:
            if room.Area <= 0:
                continue
        except Exception:
            pass
        data = build_room(room)
        if data['number'] or data['name']:
            rooms.append(data)
    rooms.sort(key=lambda r: floor_sort_key(r['number']))
    rooms_by_number = dict((r['number'].upper(), r) for r in rooms if r['number'])
    room_tops, height_detector = resolve_room_top_elevations(rooms)

    raw_walls = []
    excluded_walls = 0
    excluded_types = {}
    for wall in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        if not wall_level_in_scope(wall):
            continue
        wall_type_name = element_name(wall.WallType)
        if is_excluded_type(wall_type_name):
            excluded_walls += 1
            excluded_types[clean(wall_type_name)] = (
                excluded_types.get(clean(wall_type_name), 0) + 1)
            continue
        if is_partition_type(wall_type_name):
            raw_walls.append(wall)

    partition_walls = []
    for wall in raw_walls:
        data = build_wall(wall, height_context)
        if not data:
            continue
        if not is_partition_type(data['type_name']):
            continue
        if not data['length'] or data['length'] <= 0:
            continue
        partition_walls.append(data)

    walls_by_id = dict((wall['element_id'], wall) for wall in partition_walls)

    openings = []
    for category in (BuiltInCategory.OST_Doors, BuiltInCategory.OST_Windows):
        openings.extend(list(FilteredElementCollector(doc).OfCategory(category).WhereElementIsNotElementType()))
    assigned_openings, skipped_openings = assign_openings_to_host_walls(openings, walls_by_id)
    finalize_attached_wall_heights(partition_walls)

    grouped_by_room = {}
    assigned_walls = 0
    room_top_applied = 0
    for wall in partition_walls:
        room = assign_wall_to_room(wall, rooms, rooms_by_number)
        if not room:
            continue
        if apply_room_top_to_wall(wall, room_tops.get(room.get('id'))):
            room_top_applied += 1
        # 以 element_id 而非房號分組：跨來源模型時房號會重複
        grouped_by_room.setdefault(room['element_id'], []).append(wall)
        assigned_walls += 1

    used_types = [w['type_name'] for w in partition_walls if is_partition_type(w['type_name'])]
    wall_type_cols = sorted(list(set(used_types)), key=type_sort_key)

    height_sources = {}
    for wall in partition_walls:
        source = wall.get('height_source') or 'unknown'
        height_sources[source] = height_sources.get(source, 0) + 1

    return rooms, grouped_by_room, wall_type_cols, {
        'rooms': len(rooms),
        'partition_walls': len(partition_walls),
        'assigned_walls': assigned_walls,
        'openings': len(openings),
        'assigned_openings': assigned_openings,
        'skipped_openings': skipped_openings,
        'slab_levels': len(height_context.get('thickness_by_level', {})),
        'height_sources': height_sources,
        'excluded_walls': excluded_walls,
        'excluded_types': excluded_types,
        'height_detector': height_detector.get('detector'),
        'height_detector_view': height_detector.get('detector_view'),
        'height_detector_error': height_detector.get('error'),
        'height_detector_rooms': height_detector.get('resolved_rooms', 0),
        'height_detector_ceiling_skipped': height_detector.get('ceiling_skipped', 0),
        'height_detector_walls': room_top_applied,
    }


def wall_report_length(wall):
    return parse_number(fixed2(wall.get('length'))) or 0


def wall_opening_area(wall):
    total = 0
    for op in wall.get('openings', []):
        width = op.get('width')
        height = op.get('height')
        if width and height and width > 0 and height > 0:
            total += width * height
    return total


def wall_height_bucket(wall):
    height = wall.get('height')
    if height and height > 0 and HEIGHT_BUCKET_SIZE_M > 0:
        bucket = math.floor((height / HEIGHT_BUCKET_SIZE_M) + 0.5) * HEIGHT_BUCKET_SIZE_M
        return fixed2(bucket)
    return 'NO_HEIGHT'


def height_catalog_key(wall):
    if USE_WALL_AREA_FOR_EFFECTIVE_HEIGHT and wall.get('area') is not None:
        return 'AREA||{0}||{1}||{2}'.format(
            wall.get('type_name') or '',
            wall.get('level') or '',
            wall_height_bucket(wall)
        )
    return 'RAW||{0}||{1}'.format(wall.get('type_name') or '', fixed2(wall.get('height')))


def build_height_catalog(grouped_by_room):
    catalog = {}
    for walls in grouped_by_room.values():
        for wall in walls:
            key = height_catalog_key(wall)
            length = wall_report_length(wall)
            if length <= 0:
                continue
            if key not in catalog:
                catalog[key] = {
                    'length': 0,
                    'area': 0,
                    'openings': 0,
                    'height': wall.get('height'),
                }
            catalog[key]['length'] += length
            if wall.get('area') and wall.get('area') > 0:
                catalog[key]['area'] += wall.get('area')
            catalog[key]['openings'] += wall_opening_area(wall)

    for item in catalog.values():
        if USE_WALL_AREA_FOR_EFFECTIVE_HEIGHT and item['area'] > 0 and item['length'] > 0:
            item['height'] = (item['area'] + item['openings']) / item['length']
    return catalog


def make_rows(rooms, grouped_by_room, wall_type_cols):
    rows = []
    full = SUMMARY_LAYOUT.with_columns(wall_type_cols)
    height_catalog = build_height_catalog(grouped_by_room)

    for room in rooms:
        walls = grouped_by_room.get(room['element_id'], [])
        if not walls:
            rows.append(full.row_from({
                'room_no': room['number'],
                'room_name': room['name'],
                'room_perimeter': room['perimeter'],
            }))
            continue

        groups = {}
        for wall in walls:
            key = height_catalog_key(wall)
            if key not in groups:
                groups[key] = {
                    'type_name': wall['type_name'],
                    'height': wall['height'],
                    'level': wall['level'],
                    'height_key': key,
                    'walls': [],
                    'openings': [],
                }
            groups[key]['walls'].append(wall)
            groups[key]['openings'].extend(wall['openings'])

        sorted_groups = sorted(groups.values(), key=lambda g: (type_sort_key(g['type_name']), clean(g['level']), g['height'] or 0))

        for group in sorted_groups:
            opening_groups = {}
            for op in group['openings']:
                key = '{0}||{1}||{2}'.format(op['name'], fixed2(op['width']), fixed2(op['height']))
                if key not in opening_groups:
                    opening_groups[key] = dict(op)
                    opening_groups[key]['count'] = 0
                opening_groups[key]['count'] += 1

            openings = [
                op for op in opening_groups.values()
                if op.get('width') and op.get('height') and op['width'] > 0 and op['height'] > 0
            ]
            openings.sort(key=lambda op: (op['name'], op['width'], op['height']))

            lengths = [fixed2(wall['length']) for wall in group['walls'] if wall.get('length')]
            length_total = sum(parse_number(value) or 0 for value in lengths)
            opening_area = sum(op['count'] * op['width'] * op['height'] for op in openings)
            wall_area = sum(wall.get('area') or 0 for wall in group['walls'] if wall.get('area') and wall.get('area') > 0)
            catalog_item = height_catalog.get(group.get('height_key'))
            if catalog_item and catalog_item.get('height'):
                group_height = catalog_item['height']
            elif USE_WALL_AREA_FOR_EFFECTIVE_HEIGHT and wall_area > 0 and length_total > 0:
                group_height = (wall_area + opening_area) / length_total
            else:
                group_height = group['height']

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
                    full.put(row, 'height', fixed2(group_height))
                    full.put(row, 'area', 'AREA_FORMULA')
                    full.put(row, 'area_subtotal', 'SUBTOTAL_FORMULA')
                    full.put(row, 'total', 'TOTAL_FORMULA')
                    if full.has(group['type_name']):
                        full.put(row, group['type_name'], 'TYPE_FORMULA')

                if i < len(openings):
                    op = openings[i]
                    full.put(row, 'opening_name', op['name'])
                    full.put(row, 'opening_count', op['count'])
                    full.put(row, 'opening_width', fixed2(op['width']))
                    full.put(row, 'opening_height', fixed2(op['height']))
                    full.put(row, 'opening_area', 'OPENING_AREA_FORMULA')
                    full.put(row, 'opening_subtotal',
                             'OPENING_SUBTOTAL_FORMULA')

                rows.append(row)

    return fill_formulas(rows, wall_type_cols)


def excel_col(index):
    result = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def fill_formulas(rows, wall_type_cols):
    """把佔位字串換成真正的公式。

    公式一律用欄位名稱寫，字母由 SUMMARY_LAYOUT 產生——欄位一搬動，這裡以前的
    寫死字母不會跟著動，公式不會壞掉，只會安靜地指到隔壁那一欄。
    """
    layout = SUMMARY_LAYOUT
    full = layout.with_columns(wall_type_cols)
    for i, row in enumerate(rows):
        row_number = FIRST_DATA_ROW + i
        if layout.get(row, 'area') == 'AREA_FORMULA':
            layout.put(row, 'area',
                       layout.formula(row_number, '{length}*{height}'))
        if layout.get(row, 'area_subtotal') == 'SUBTOTAL_FORMULA':
            layout.put(row, 'area_subtotal',
                       layout.formula(row_number, '{area}'))
        if layout.get(row, 'opening_area') == 'OPENING_AREA_FORMULA':
            layout.put(row, 'opening_area', layout.formula(
                row_number,
                '{opening_count}*{opening_width}*{opening_height}'))
        if layout.get(row, 'opening_subtotal') == 'OPENING_SUBTOTAL_FORMULA':
            layout.put(row, 'opening_subtotal',
                       layout.formula(row_number, '{opening_area}'))
        if layout.get(row, 'total') == 'TOTAL_FORMULA':
            deductions = []
            if layout.get(row, 'opening_subtotal'):
                deductions.append(
                    layout.cell('opening_subtotal', row_number))
            look = 1
            while (i + look < len(rows)
                   and not layout.get(rows[i + look], 'wall_type')
                   and layout.get(rows[i + look], 'opening_subtotal')):
                deductions.append(
                    layout.cell('opening_subtotal', row_number + look))
                look += 1
            total = layout.expr(row_number, '{area_subtotal}')
            if deductions:
                total += '-' + '-'.join(deductions)
            layout.put(row, 'total', '=' + total)
        wall_type = layout.get(row, 'wall_type')
        if wall_type in wall_type_cols:
            if full.get(row, wall_type) == 'TYPE_FORMULA':
                full.put(row, wall_type,
                         layout.formula(row_number, '{total}'))
    return rows


def build_sheet_values(rows, wall_type_cols, project_title):
    total_cols = FIXED_REPORT_COLS + len(wall_type_cols)
    blank_tail = [''] * (total_cols - 1)
    values = []
    values.append([project_title] + blank_tail)
    values.append(['輕隔間數量計算表'] + blank_tail)
    values.append(['依房間別（全高牆=樓層至上層樓板底；貼附頂/底與低矮特殊牆依 Revit 幾何）'] + blank_tail)

    full = SUMMARY_LAYOUT.with_columns(wall_type_cols)
    section = full.row_from({
        'room_no': '樓別名稱',
        'room_perimeter': '輕隔間牆',
        'opening_name': '門開口、窗開口',
    })
    if wall_type_cols:
        full.put(section, wall_type_cols[0], '輕隔間牆面積')
    values.append(section)

    values.append(list(SUMMARY_HEADERS) + wall_type_cols)
    values.extend(rows)
    values.append(build_summary_row(len(rows), wall_type_cols))
    return values


def build_summary_row(data_row_count, wall_type_cols):
    row = [''] * (FIXED_REPORT_COLS + len(wall_type_cols))
    full = SUMMARY_LAYOUT.with_columns(wall_type_cols)
    full.put(row, 'room_no', SUMMARY_LABEL)
    last_data_row = FIRST_DATA_ROW + data_row_count - 1
    for type_name in wall_type_cols:
        # 每一欄加的是自己那一欄。以前這裡是 excel_col(FIXED + index + 1)，
        # 一個 +1 就會讓總計加到隔壁去，而且不會報錯。
        full.put(row, type_name,
                 full.sum_of(type_name, FIRST_DATA_ROW, last_data_row)
                 if data_row_count > 0 else '=0')
    return row


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


def display_width(text):
    """儲存格文字的顯示寬度，中日韓字元算 2 個字寬。"""
    width = 0
    for ch in clean(text):
        width += 2 if ord(ch) > 0x2E80 else 1
    return width


# OOXML 的 <col width> 含 5px 內距，Excel 顯示出來的欄寬會少 5/MDW（預設字型
# MDW=7px，約 0.71）。上面的常數存的是「Excel 顯示的欄寬」——也就是量測範本
# 得到的值——所以寫檔時要補回這段內距，否則每欄都會窄 0.71。
COL_WIDTH_PADDING = 5.0 / 7.0


def col_width_attr(width):
    return round(width + COL_WIDTH_PADDING, 2)


def autofit_width(text):
    """重建 Excel 自動調整欄寬的結果（依範本量測出的比例）。"""
    return round(display_width(text) * AUTOFIT_WIDTH_RATIO, 2)


def row_style_id(row_index, summary_row_index):
    """列 → cellXfs 索引。比照範本：1/2/3 列字級各不相同。"""
    if summary_row_index and row_index == summary_row_index:
        return STYLE_SUMMARY
    if row_index == 1:
        return STYLE_TITLE
    if row_index == 2:
        return STYLE_PROJECT
    if row_index == 3:
        return STYLE_TABLE_NAME
    if row_index <= 5:
        return STYLE_CENTER
    return STYLE_DATA


def style_attr(style_id):
    """每一格都要明確標 s=，包含索引 0。

    省略 s= 時 Excel 不會套用 cellXfs[0]，而是回頭用內建的 Normal 樣式，
    框線因此整片消失（實測資料列 120 格全無框線，只有有標 s= 的第 5 列與
    合計列有）。檔案大一點，但版面才會與範本一致。
    """
    return ' s="{0}"'.format(style_id or 0)


def cell_xml(row_index, col_index, value, summary_row_index):
    ref = '{0}{1}'.format(excel_col(col_index), row_index)
    text = clean(value)
    style = style_attr(row_style_id(row_index, summary_row_index))
    if value is None or value == '':
        return '<c r="{0}"{1}/>'.format(ref, style)
    if text.startswith('='):
        return '<c r="{0}"{1}><f>{2}</f></c>'.format(ref, style, xml_escape(text[1:]))
    if is_number(value):
        return '<c r="{0}"{1}><v>{2}</v></c>'.format(ref, style, clean(value))
    return '<c r="{0}"{1} t="inlineStr"><is><t>{2}</t></is></c>'.format(ref, style, xml_escape(text))


def sheet_xml(values, layout):
    rows_xml = []
    summary_row_index = None
    for row_index, row in enumerate(values, start=1):
        if row and row[0] == SUMMARY_LABEL:
            summary_row_index = row_index
        cells = []
        for col_index, value in enumerate(row, start=1):
            cell = cell_xml(row_index, col_index, value, summary_row_index)
            if cell:
                cells.append(cell)
        if row_index == 1:
            height = TITLE_ROW_HEIGHT
        elif row_index == 2:
            height = PROJECT_ROW_HEIGHT
        elif row_index <= 5:
            height = HEADER_ROW_HEIGHT
        else:
            height = layout['data_row_height']
        rows_xml.append(
            '<row r="{0}" ht="{1}" customHeight="1">{2}</row>'.format(
                row_index, height, ''.join(cells)))

    # 本檔跑 IronPython 2.7（無 #! python3），不能用 max(..., default=)
    total_cols = FIXED_REPORT_COLS
    for row in values:
        if len(row) > total_cols:
            total_cols = len(row)

    # TYPE 欄名稱在第 5 列（欄位標題列）的 FIXED_REPORT_COLS 之後
    header_row = values[4] if len(values) > 4 else []
    type_names = [clean(name) for name in header_row[FIXED_REPORT_COLS:]]

    scale = layout['type_width_scale']
    widths = list(layout['col_widths'])
    if type_names:
        # D 欄放的是 TYPE 名稱本身，寬度跟著最長的那個走（範本即如此）
        longest = 0
        for name in type_names:
            candidate = round(autofit_width(name) * scale, 2)
            if candidate > longest:
                longest = candidate
        if longest > 0:
            widths[3] = longest

    col_parts = []
    for index, width in enumerate(widths, start=1):
        hidden = ''
        if index == 4 and layout['hide_type_name_column']:
            # 主檔那張把牆類型欄隱藏，TYPE 名稱看 P 欄以後的欄位標題
            hidden = ' hidden="1"'
        col_parts.append(
            '<col min="{0}" max="{0}" width="{1}" customWidth="1"{2}/>'.format(
                index, col_width_attr(width), hidden))
    for offset, name in enumerate(type_names):
        col_parts.append(
            '<col min="{0}" max="{0}" width="{1}" customWidth="1"/>'.format(
                len(layout['col_widths']) + offset + 1,
                col_width_attr(round(autofit_width(name) * scale, 2))))
    cols = ''.join(col_parts)

    # 合併：第 1~3 列整列跨欄，第 4 列四個群組區段，最後是合計列的標籤
    merges = []
    # 注意：這個函式的 ``layout`` 參數是版面設定 dict（列高、縮放），不是
    # SheetLayout；欄位一律問 SUMMARY_LAYOUT。
    first_col = SUMMARY_LAYOUT.col(SUMMARY_COLUMNS[0])
    last_fixed_col = SUMMARY_LAYOUT.col(SUMMARY_COLUMNS[-1])
    last_col = sheet_layout.column_letter(total_cols - 1)

    def merge(from_key, to_key, row_index):
        return '{0}{2}:{1}{2}'.format(SUMMARY_LAYOUT.col(from_key),
                                      SUMMARY_LAYOUT.col(to_key), row_index)

    for row_index in (1, 2, 3):
        merges.append('{0}{1}:{2}{1}'.format(first_col, row_index, last_col))
    # 第 4 列的四個區段，範圍要跟該區段的標題對齊（見 build_sheet_values）
    merges.append(merge('room_no', 'room_name', 4))
    merges.append(merge('room_perimeter', 'area_subtotal', 4))
    merges.append(merge('opening_name', 'total', 4))
    if total_cols > FIXED_REPORT_COLS:
        merges.append('{0}4:{1}4'.format(
            sheet_layout.column_letter(FIXED_REPORT_COLS), last_col))
    if summary_row_index:
        merges.append('{0}{1}:{2}{1}'.format(
            first_col, summary_row_index, last_fixed_col))
    merge_xml = '<mergeCells count="{0}">{1}</mergeCells>'.format(
        len(merges),
        ''.join('<mergeCell ref="{0}"/>'.format(ref) for ref in merges))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="5" topLeftCell="A6" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="{3}"/>'
        '<cols>{0}</cols><sheetData>{1}</sheetData>{2}'
        '</worksheet>'
    ).format(cols, ''.join(rows_xml), merge_xml,
             layout['data_row_height'])


def write_zip_entry(archive, name, content):
    entry = archive.CreateEntry(name)
    stream = entry.Open()
    writer = StreamWriter(stream, Encoding.UTF8)
    writer.Write(content)
    writer.Close()
    stream.Close()


def write_xlsx(path, values, layout):
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
                        '<sheets><sheet name="輕隔間數量計算" sheetId="1" r:id="rId1"/></sheets>'
                        '<calcPr calcMode="auto"/></workbook>')
        write_zip_entry(archive, 'xl/styles.xml',
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                        + PARTITION_FONTS_XML
                        + takeoff_excel_styles.FILLS_XML
                        + PARTITION_BORDERS_XML
                        + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                        # 順序即 STYLE_* 常數，改動請一併改那組常數
                        '<cellXfs count="7">'
                        # 0 佔位：Excel 視為 Normal 樣式，不指派給任何儲存格
                        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                        # 1 內文：水平一般、垂直置中
                        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1">'
                        '<alignment vertical="center"/>'
                        '</xf>'
                        # 2 群組標題與欄位標題
                        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1">'
                        '<alignment horizontal="center" vertical="center"/>'
                        '</xf>'
                        # 3 合計列：粗體置中
                        '<xf numFmtId="0" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1">'
                        '<alignment horizontal="center" vertical="center"/>'
                        '</xf>'
                        # 4 第 1 列標題 24pt 靠左
                        '<xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1">'
                        '<alignment horizontal="left" vertical="center" wrapText="1"/>'
                        '</xf>'
                        # 5 第 2 列專案名稱 14pt 靠左
                        '<xf numFmtId="0" fontId="3" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1">'
                        '<alignment horizontal="left" vertical="center" wrapText="1"/>'
                        '</xf>'
                        # 6 第 3 列表名 12pt 靠左
                        '<xf numFmtId="0" fontId="4" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1">'
                        '<alignment horizontal="left" vertical="center" wrapText="1"/>'
                        '</xf>'
                        '</cellXfs>'
                        '</styleSheet>')
        write_zip_entry(archive, 'xl/worksheets/sheet1.xml', sheet_xml(values, layout))
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


def collect_selected_sources(host_doc, options):
    """依 UI 選取的宿主／連結模型與樓層逐一掃描，合併成一份報表資料。"""
    global doc
    global ACTIVE_ALLOWED_LEVEL_IDS
    all_rooms = []
    all_grouped = {}
    all_type_cols = set()
    all_stats = {}
    sources = list(takeoff_entry.iter_sources(host_doc, options))
    previous_doc = doc
    previous_levels = ACTIVE_ALLOWED_LEVEL_IDS
    try:
        for (source_key, source_label, source_doc,
             allowed_level_ids, unused_link_instance_id) in sources:
            doc = source_doc
            ACTIVE_ALLOWED_LEVEL_IDS = allowed_level_ids
            rooms, grouped_by_room, wall_type_cols, stats = collect_data()
            # 房號在不同來源模型會重複，改用來源前綴後的複合鍵
            rooms, grouped_by_room = (
                takeoff_direct_publish.rekey_room_records(
                    source_key, source_label, rooms, grouped_by_room))
            all_rooms.extend(rooms)
            all_grouped.update(grouped_by_room)
            all_type_cols.update(wall_type_cols)
            takeoff_direct_publish.merge_stats(all_stats, stats)
    finally:
        doc = previous_doc
        ACTIVE_ALLOWED_LEVEL_IDS = previous_levels

    wall_type_cols = sorted(list(all_type_cols), key=type_sort_key)
    # 依房號排序，來源只當同號時的次要鍵：連結模型的 B135 要接在宿主的 B134
    # 之後，而不是整批連結房間被推到最前面或最後面。
    all_rooms.sort(key=lambda room: (
        floor_sort_key(room.get('number')),
        clean(room.get('source_label'))))
    all_stats['rooms'] = len(all_rooms)
    all_stats['sources'] = len(sources)
    return all_rooms, all_grouped, wall_type_cols, all_stats, sources


def normalize_type_key(value):
    """比對 TYPE 名稱用：去掉所有空白並轉大寫，避免全半形空格造成對不上。"""
    return re.sub(r'\s+', '', clean(value)).upper()


def update_actual_quantity_sheet(workbook_path, wall_type_cols,
                                 summary_row_index):
    """把各 TYPE 的總量以公式帶進「輕隔間(實際數量)」的 B 欄「Excel(手算)」。

    寫的是公式而不是數值，讓它跟著「輕隔間(手算驗證)」的摘要列連動，
    數字有出入時可以直接追回逐牆明細。C 欄「Revit(自動)」是使用者手填的
    對照值，本函式不會寫入也不會清除。
    """
    result = {
        'updated': [],
        'sheet_unmatched': [],
        'type_unmatched': [],
        'error': '',
    }
    if not wall_type_cols:
        result['error'] = '本次沒有取得任何輕隔間 TYPE，未寫入實際數量分頁'
        return result

    # 這裡算出來的字母會被寫進使用者真正的活頁簿（跨分頁參照「手算驗證」的
    # 合計列），所以更不能手算欄號——一律問 layout。
    full = SUMMARY_LAYOUT.with_columns(wall_type_cols)
    targets = {}
    for type_name in wall_type_cols:
        targets[normalize_type_key(type_name)] = (type_name,
                                                  full.col(type_name))
    remaining = dict(targets)

    app = None
    workbook = None
    saved = False
    try:
        from System import Activator, Type
        xl_type = Type.GetTypeFromProgID('Excel.Application')
        if xl_type is None:
            raise Exception('Excel 未安裝或 COM 無法使用')
        app = Activator.CreateInstance(xl_type)
        app.Visible = False
        app.DisplayAlerts = False
        app.AskToUpdateLinks = False

        workbook = app.Workbooks.Open(workbook_path, 0, False)
        sheet = None
        for candidate in workbook.Worksheets:
            if clean(candidate.Name) == ACTUAL_SHEET:
                sheet = candidate
                break
        if sheet is None:
            raise Exception('找不到分頁「{0}」'.format(ACTUAL_SHEET))

        last_row = int(sheet.UsedRange.Rows.Count) + int(sheet.UsedRange.Row) - 1
        for row in range(2, last_row + 1):
            label = clean(sheet.Cells.Item(row, ACTUAL_TYPE_COL).Value2)
            if not label or label.startswith('*'):
                continue
            key = normalize_type_key(label)
            if key not in targets:
                result['sheet_unmatched'].append(label)
                continue
            type_name, col_letter = targets[key]
            remaining.pop(key, None)
            sheet.Cells.Item(row, ACTUAL_TOTAL_COL).Formula = (
                "='{0}'!{1}{2}".format(
                    VERIFY_SHEET, col_letter, summary_row_index))
            result['updated'].append(type_name)

        result['type_unmatched'] = [name for name, _col in remaining.values()]
        workbook.Save()
        saved = True
    except Exception as error:
        result['error'] = '{0}'.format(error)
    finally:
        try:
            if workbook is not None:
                workbook.Close(saved)
        except Exception:
            pass
        try:
            if app is not None:
                app.DisplayAlerts = True
                app.Quit()
        except Exception:
            pass
    return result


def main():
    if not doc:
        forms.alert('目前沒有開啟 Revit 文件。', title='輕隔間 Excel')
        return

    host_doc = doc
    options = takeoff_entry.choose_options(
        host_doc, '輕隔間 Excel', allow_host=True, host_required=False)
    if options is None:
        return

    try:
        rooms, grouped_by_room, wall_type_cols, stats, sources = (
            collect_selected_sources(host_doc, options))
    except Exception as collect_error:
        forms.alert(
            '讀取來源模型失敗：\n{0}'.format(collect_error), title='輕隔間 Excel')
        return

    project_title = revit_file_title()
    rows = make_rows(rooms, grouped_by_room, wall_type_cols)
    values = build_sheet_values(rows, wall_type_cols, project_title)
    summary_row_index = FIRST_DATA_ROW + len(rows)

    workbook_path = options.get('workbook_path')
    actual_result = None
    if workbook_path:
        temp_path = takeoff_direct_publish.new_temp_xlsx_path()
        try:
            write_xlsx(temp_path, values, LAYOUT_PUBLISH)
            takeoff_direct_publish.publish_generated_workbook(
                workbook_path,
                temp_path,
                [(GENERATED_SHEET, VERIFY_SHEET)],
                summary_specs={
                    VERIFY_SHEET: {
                        'label': SUMMARY_LABEL,
                        'header_label': '編號',
                        'data_header_label': '空間名稱',
                    },
                })
            outpath = workbook_path
        except takeoff_direct_publish.WorkbookPublishError as exc:
            forms.alert(
                '更新主要 Excel 失敗：\n{0}'.format(exc), title='輕隔間 Excel')
            return
        finally:
            takeoff_direct_publish.remove_file_quietly(temp_path)
        actual_result = update_actual_quantity_sheet(
            workbook_path, wall_type_cols, summary_row_index)
    else:
        default_name = safe_filename(project_title) + '_輕隔間數量計算.xlsx'
        outpath = forms.save_file(
            file_ext='xlsx',
            default_name=default_name,
            title='匯出輕隔間數量計算 Excel'
        )
        if not outpath:
            return
        if not outpath.lower().endswith('.xlsx'):
            outpath += '.xlsx'
        write_xlsx(outpath, values, LAYOUT_STANDALONE)

    output.print_md('## 輕隔間 Excel {0}完成'.format(
        '更新' if workbook_path else '匯出'))
    output.print_md('- 檔案：`{0}`'.format(outpath))
    for source_key, source_label, _d, allowed_levels, _i in sources:
        output.print_md('- 來源：{0}（{1}）'.format(
            source_label,
            '全部樓層' if allowed_levels is None
            else '{0} 個樓層'.format(len(allowed_levels))))
    if workbook_path:
        output.print_md('- 分頁：`{0}` 明細，摘要列第 {1} 列'.format(
            VERIFY_SHEET, summary_row_index))
    if actual_result is not None:
        if actual_result.get('error'):
            output.print_md('- **`{0}` 未更新：{1}**'.format(
                ACTUAL_SHEET, actual_result['error']))
        else:
            output.print_md('- `{0}` {1} 欄已帶入 {2} 個 TYPE（{3} 欄不動，由人工填寫）'.format(
                ACTUAL_SHEET, excel_col(ACTUAL_TOTAL_COL),
                len(actual_result.get('updated') or []),
                excel_col(ACTUAL_TOTAL_COL + 1)))
        for label in actual_result.get('sheet_unmatched') or []:
            output.print_md('  - 分頁列在模型中找不到對應 TYPE：{0}'.format(label))
        for label in actual_result.get('type_unmatched') or []:
            output.print_md('  - 模型 TYPE 在分頁中沒有對應列：{0}'.format(label))
    output.print_md('- Rooms：{0}'.format(stats['rooms']))
    output.print_md('- TYPE walls：{0}，已分配：{1}'.format(stats['partition_walls'], stats['assigned_walls']))
    output.print_md('- Openings：{0}，host 已扣除：{1}，略過：{2}'.format(
        stats['openings'], stats['assigned_openings'], stats['skipped_openings']
    ))
    output.print_md('- Slab thickness levels：{0}'.format(stats.get('slab_levels', 0)))
    output.print_md('- 頂部偵測：`{0}`{1}'.format(
        stats.get('height_detector') or 'legacy',
        u'（3D 視圖 {0}）'.format(stats.get('height_detector_view'))
        if stats.get('height_detector_view') else ''
    ))
    if stats.get('height_detector_error'):
        output.print_md('  - 射線測頂未啟用，全數退回樓層標高−樓板厚度公式：`{0}`'.format(
            stats['height_detector_error']))
    else:
        output.print_md('  - 取得樓板底標高的房間：{0}，因偵測到天花而不採用：{1}'.format(
            stats.get('height_detector_rooms', 0),
            stats.get('height_detector_ceiling_skipped', 0)))
        output.print_md('  - 依此重算牆高的牆：{0}'.format(
            stats.get('height_detector_walls', 0)))
    for source, count in sorted(stats.get('height_sources', {}).items()):
        output.print_md('  - Height source `{0}`：{1}'.format(source, count))
    output.print_md('- Wall types：{0}'.format(len(wall_type_cols)))
    if stats.get('excluded_walls'):
        output.print_md('- 已排除的錯誤類型：{0} 道牆'.format(stats['excluded_walls']))
        for name, count in sorted((stats.get('excluded_types') or {}).items()):
            output.print_md('  - `{0}`：{1} 道'.format(name, count))
    forms.alert(
        '輕隔間 Excel {0}完成。'.format('更新' if workbook_path else '匯出'),
        title='輕隔間 Excel')


main()
