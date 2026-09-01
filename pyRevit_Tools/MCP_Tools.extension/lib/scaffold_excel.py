# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Shared pyRevit Excel updater for scaffold takeoff items."""

import os
import re
import shutil
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime

from pyrevit import forms, revit, script

from System import Activator, GC, Type
from System.Runtime.InteropServices import Marshal

import mcp_bridge as mcp
import room_takeoff_sources
import room_takeoff_sources_logic
import scaffold_height
import sheet_layout

try:
    reload(scaffold_height)
except Exception:
    pass


SCRIPT_VERSION = u'2026-08-07-rounding-tolerance-and-calc-perf-v20'
REPORT_FONT_NAME = u'標楷體'

XL_UP = -4162
XL_CALCULATION_MANUAL = -4135
XL_CALCULATION_AUTOMATIC = -4105
AUDIT_SHEET = u'施工架計算'
SPACE_SHEET = u'01空間表'
OTHER_AREA_SHEET = u'其他面積'
SUBTOTAL_SHEET = u'小計'
UPDATE_ITEM_SHEET = u'更新工項'
INNER_WALL_SHEET = u'內牆'

LEVEL_SUMMARY_HEADER_ROW = 9
LEVEL_SUMMARY_START_ROW = 10
# 逐房明細佔用第 1~23 欄（最後四欄是來源Key/來源模型/ElementId/長寬來源）。
# 逐房稽核表的欄位。以前這 23 欄同時被三種寫法引用：Cells(row, 15) 這類欄號、
# '=IF(Q{}="是",ROUND(I{}*L{},3),0)' 這類寫死字母的公式、以及手寫的
# ROOM_AUDIT_LAST_COL = 23。三者必須同步，錯開時公式不會壞掉，只會指到隔壁欄。
ROOM_AUDIT_COLUMNS = [
    'revit_id',         # RevitId
    'level',            # 樓層
    'number',           # 房間編號
    'name',             # 房間名稱
    'category',         # 分類代碼
    'category_name',    # 計入工項
    'rule',             # 分類依據
    'space_row',        # 「<空間表>列」
    'perimeter',        # 周長(m)
    'length',           # 長(m)
    'width',            # 寬(m)
    'height',           # 高(m)
    'height_source',    # 高度來源
    'formula_text',     # 計算式
    'quantity',         # 數量
    'unit',             # 單位
    'included',         # 計入
    'note',             # 備註
    'level_key',        # 樓層鍵
    'source_key',       # 來源Key
    'source_label',     # 來源模型
    'element_id',       # ElementId
    'dimension_source', # 長寬來源
]
ROOM_AUDIT = sheet_layout.SheetLayout(
    ROOM_AUDIT_COLUMNS, first_data_row=10, name=u'逐房稽核')
ROOM_AUDIT_HEADER_ROW = 9
ROOM_AUDIT_FIRST_ROW = ROOM_AUDIT.first_data_row
# 表頭文字（「<空間表>列」那一欄的名稱要帶入實際分頁名，寫入時再補）
ROOM_AUDIT_HEADERS = [
    ('revit_id', u'RevitId'), ('level', u'樓層'), ('number', u'房間編號'),
    ('name', u'房間名稱'), ('category', u'分類代碼'),
    ('category_name', u'計入工項'), ('rule', u'分類依據'),
    ('space_row', u'列'), ('perimeter', u'周長(m)'), ('length', u'長(m)'),
    ('width', u'寬(m)'), ('height', u'高(m)'), ('height_source', u'高度來源'),
    ('formula_text', u'計算式'), ('quantity', u'數量'), ('unit', u'單位'),
    ('included', u'計入'), ('note', u'備註'), ('level_key', u'樓層鍵'),
    ('source_key', u'來源Key'), ('source_label', u'來源模型'),
    ('element_id', u'ElementId'), ('dimension_source', u'長寬來源'),
]
# --- 工項活頁簿「範本」的欄位 ------------------------------------------------
#
# 下面三張分頁的欄位順序是**使用者的範本**決定的，不是我們排的版，所以不用
# SheetLayout（那是給我們自己排版的表用的）。但同一個範本欄位在這支程式裡同時
# 以欄號（``Cells(sr, 6)``）與字母（``'!F{}'``）出現——寫入一次、驗證再寫一次、
# 訊息再寫一次，一個欄位三個地方。統一從這裡取，字母一律用 _col_letter() 導出。
SUBTOTAL_COLS = {
    'code': 2,          # B 工項代碼
    'name': 3,          # C 工項名稱
    'unit': 5,          # E 單位
    'rounded_qty': 6,   # F 取整數量（=ROUND(數量,0)）
    'source': 7,        # G 來源註記
    'quantity': 8,      # H 數量
}
OTHER_COLS = {
    'code': 2,          # B
    'name': 3,          # C
    'level': 4,         # D 樓層／位置
    'count': 5,         # E 數量（固定 1）
    'length': 6,        # F
    'height': 8,        # H
    'subtotal': 9,      # I 小計
    'total': 16,        # P 總量
}
UPDATE_COLS = {
    'name': 2,          # B 工項名稱
    'unit': 3,          # C 單位
    'rounded_qty': 4,   # D
    'source': 5,        # E
    'quantity': 6,      # F
}


def _rounded_qty_formula(row):
    """小計分頁「取整數量」欄的公式。寫入端與驗證端共用同一份定義——以前這串
    取整公式以前在三個地方各寫一次，改一個忘一個時驗證會安靜地放行。"""
    return u'=ROUND({0}{1},0)'.format(
        _col_letter(SUBTOTAL_COLS['quantity']), row)


def _addr(sheet_name, col_number, row):
    """給人看的位址（驗證訊息用，不加引號）：``其他面積!D12``。"""
    return u'{0}!{1}{2}'.format(sheet_name, _col_letter(col_number), row)


def _sheet_ref(sheet_name, col_number, row):
    """``'小計'!H12``——欄位字母由欄號導出，不手寫。"""
    return u'{0}!{1}{2}'.format(_quote_sheet(sheet_name),
                                _col_letter(col_number), row)


# 獨立匯出的「數量明細」分頁欄位（跟上面那張逐房稽核表不同張、不同順序）。
STANDALONE_DETAIL_COLUMNS = [
    'source_key', 'source_label', 'composite_id', 'element_id', 'level',
    'number', 'name', 'category', 'perimeter', 'length', 'width',
    'height', 'height_source', 'included', 'quantity', 'unit',
    'rule', 'dimension_source', 'warning',
]
STANDALONE_DETAIL_HEADERS = [
    u'來源Key', u'來源模型', u'複合識別', u'ElementId', u'樓層',
    u'房號', u'房名', u'分類', u'周長(m)', u'長(m)', u'寬(m)',
    u'高度(m)', u'高度來源', u'計入', u'數量', u'單位',
    u'分類依據', u'長寬來源', u'警告',
]
if len(STANDALONE_DETAIL_COLUMNS) != len(STANDALONE_DETAIL_HEADERS):
    raise AssertionError(
        u'STANDALONE_DETAIL 的欄位與表頭長度不一致：加欄位時兩邊都要加')
STANDALONE_DETAIL = sheet_layout.SheetLayout(
    STANDALONE_DETAIL_COLUMNS, first_data_row=2, name=u'施工架數量明細')

ROOM_AUDIT_WIDTHS = [
    18, 12, 13, 24, 24, 28, 25, 12, 12, 12, 12, 12, 28, 30,
    14, 10, 9, 42, 12, 16, 28, 13, 30,
]
if [key for key, _t in ROOM_AUDIT_HEADERS] != ROOM_AUDIT_COLUMNS:
    raise AssertionError(
        u'ROOM_AUDIT_HEADERS 與 ROOM_AUDIT_COLUMNS 的欄位順序不一致')
if len(ROOM_AUDIT_WIDTHS) != len(ROOM_AUDIT_COLUMNS):
    raise AssertionError(
        u'ROOM_AUDIT_WIDTHS 有 {0} 個、欄位有 {1} 個：加欄位時兩邊都要加'.format(
            len(ROOM_AUDIT_WIDTHS), len(ROOM_AUDIT_COLUMNS)))
# 樓層小計表必須留在它右邊，中間空兩欄當分隔；放在 21~23 欄會蓋掉前幾間房的
# 來源證據，並讓逐房明細的自動篩選連帶隱藏小計列。
ROOM_AUDIT_LAST_COL = ROOM_AUDIT.width
LEVEL_SUMMARY_LEVEL_COL = 26
LEVEL_SUMMARY_KEY_COL = 27
LEVEL_SUMMARY_GENERAL_COL = 28

ITEM_NAMES = {
    'exterior': u'室外框式施工架(含防護設施)',
    'general': u'室內施工架(含防護措施)',
    'interior_finish': u'室內裝修施工架',
}

ITEM_UNITS = {
    'exterior': u'M2',
    'general': u'M2',
    'interior_finish': u'M3',
}

SUMMARY_ROWS = {
    'exterior': 4,
    'general': 5,
    'interior_finish': 6,
}
SUMMARY_FIRST_ROW = min(SUMMARY_ROWS.values())
SUMMARY_LAST_ROW = max(SUMMARY_ROWS.values())
AUDIT_HEADER_ROW = 3
AUDIT_SOURCE_ROW = 7          # 室外周長來源那一列

# 稽核表上方摘要區的五欄。以前這五欄有**三個各自維護的真相**：headers 清單、
# 'A3:E3' 這類手寫字母、以及 _write_exterior_audit 裡的 Cells(row, 2/4/5)。
# 加一欄就會全部錯開，而且不會報錯。現在字母與欄號一律問 layout。
AUDIT_SUMMARY_COLUMNS = ['item', 'quantity', 'unit', 'formula', 'updated_at']
AUDIT_SUMMARY_HEADERS = [u'工項', u'數量', u'單位', u'公式／來源', u'更新時間']
AUDIT_SUMMARY_WIDTHS = [28, 14, 10, 34, 20]
if not (len(AUDIT_SUMMARY_COLUMNS) == len(AUDIT_SUMMARY_HEADERS)
        == len(AUDIT_SUMMARY_WIDTHS)):
    raise AssertionError(
        u'AUDIT_SUMMARY 的欄位／表頭／欄寬三份清單長度不一致：加欄位時三邊都要加')
AUDIT_SUMMARY = sheet_layout.SheetLayout(
    AUDIT_SUMMARY_COLUMNS, first_data_row=SUMMARY_FIRST_ROW,
    name=AUDIT_SHEET)

# 標題橫幅的寬度與欄位無關，純粹是視覺上要夠寬。
AUDIT_TITLE_LAST_COL = 19
AUDIT_TITLE_SPAN = u'{0}1:{1}1'.format(
    sheet_layout.column_letter(0),
    sheet_layout.column_letter(AUDIT_TITLE_LAST_COL - 1))

SUMMARY_CATEGORIES = {
    'general': 'general_scaffold',
    'interior_finish': 'interior_finish_scaffold',
}

FINISH_KEYWORDS = [
    u'安全梯', u'無障礙梯', u'樓梯', u'電梯', u'貨梯',
    u'昇降機', u'升降機', u'客梯',
]

EXCLUDE_KEYWORDS = [
    u'戶外平台', u'戶外平臺', u'室外平台', u'室外平臺',
    u'屋頂平台', u'屋頂平臺', u'露臺', u'露台', u'陽台', u'陽臺',
    u'管道間', u'水箱', u'挑空',
]

EXCLUDE_LEVELS = [u'FN', u'TF']

try:
    NUMERIC_TYPES = (int, long, float)
except NameError:
    NUMERIC_TYPES = (int, float)


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _number(value):
    if isinstance(value, NUMERIC_TYPES):
        number = float(value)
    else:
        text = _text(value).replace(',', '')
        if u'#' in text or u'ERROR' in text.upper():
            return None
        match = re.search(r'-?\d+(?:\.\d+)?', text)
        number = float(match.group(0)) if match else None
    # Excel COM exposes CVErr values such as #REF! as signed HRESULT integers.
    if number is not None and abs(number) >= 2000000000:
        return None
    return number


def _fmt(value, digits=3):
    number = _number(value)
    if number is None:
        number = 0.0
    return (u'%%.%df' % int(digits)) % float(number)


def _positive(value):
    value = _number(value)
    return value if value is not None and value > 0 else None


def _round_quantity(value, digits=3):
    """Round a decimal quantity with the same half-up rule as Excel ROUND."""
    number = _number(value)
    if number is None:
        return 0.0
    quantum = Decimal(1).scaleb(-int(digits))
    try:
        decimal_value = Decimal(_text(number))
        return float(decimal_value.quantize(quantum, rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return round(number, int(digits))


def _round_product_quantity(values, digits=3):
    """Multiply decimal inputs before rounding to avoid binary half-value drift."""
    product = Decimal(1)
    try:
        for value in values:
            number = _number(value)
            if number is None:
                return 0.0
            product *= Decimal(_text(number))
        quantum = Decimal(1).scaleb(-int(digits))
        return float(product.quantize(quantum, rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        product = 1.0
        for value in values:
            product *= _number(value) or 0.0
        return _round_quantity(product, digits)


def _append_unique(target, values):
    for value in values or []:
        text = _text(value)
        if text and text not in target:
            target.append(text)


def _concise_room_warnings(warnings):
    """Keep the room note column focused on actionable scaffold issues."""
    result = []
    keep_patterns = [
        u'重複',
        u'未計入',
        u'無對應房間',
        u'沒有有效 Finish boundary',
        u'房名不一致',
        u'缺少有效高度',
        u'缺少周長',
        u'長寬不足',
        u'包絡面積',
        u'人工確認',
        u'Room 高度備援',
        u'高度證據解析未回傳',
    ]
    skip_patterns = [
        u'實體天花：',
        u'實體天花 Level 與房間 Level 不一致',
        u'樓梯／電梯類不採天花高度',
        u'樓梯／電梯垂直堆疊',
        u'找不到上層代表樓板厚度',
        u'暫採樓層到樓層高度',
        u'已依幾何高度採用',
        u'採上方重疊 Room',
    ]
    for warning in warnings or []:
        text = _text(warning)
        if not text:
            continue
        if any(pattern in text for pattern in skip_patterns):
            continue
        if any(pattern in text for pattern in keep_patterns):
            _append_unique(result, [text])
    return result


def _norm_number(value):
    return re.sub(r'\s+', '', _text(value)).upper()


def _quote_sheet(name):
    if name is None:
        value = u''
    else:
        try:
            value = u'{}'.format(name)
        except Exception:
            value = str(name)
    # Excel permits significant trailing spaces in worksheet names.
    return u"'{}'".format(value.replace(u"'", u"''"))


def _col_letter(index):
    result = u''
    value = int(index)
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _rgb(red, green, blue):
    return int(red) + int(green) * 256 + int(blue) * 65536


def _merge_area(cell):
    """Return (top, left, bottom, right) when the cell sits inside a merge."""
    try:
        if not cell.MergeCells:
            return None
    except Exception:
        return None
    try:
        area = cell.MergeArea
        top = int(area.Row)
        left = int(area.Column)
        return (top, left,
                top + int(area.Rows.Count) - 1,
                left + int(area.Columns.Count) - 1)
    except Exception:
        return None


def _clear_contents(ws, first_row, first_col, last_row, last_col):
    """ClearContents that survives merged cells.

    Excel raises 「無法對合併儲存格執行該動作」 whenever a range covers only part
    of a merged area, and 工項活頁簿 differ on which columns the template merges.
    Merges lying entirely inside the target rectangle are cleared as a whole;
    merges reaching outside belong to a neighbouring block (工項名稱 B/C 欄、
    工項總量 P 欄) and are left untouched so the caller can write their anchor.
    Writing a value into a merged cell is always allowed, so only clearing
    needs this guard.
    """
    target = ws.Range(
        ws.Cells(first_row, first_col), ws.Cells(last_row, last_col))
    try:
        merged_flag = target.MergeCells
    except Exception:
        merged_flag = None
    if merged_flag is not None and not merged_flag:
        target.ClearContents()
        return
    handled = set()
    for row in range(first_row, last_row + 1):
        for col in range(first_col, last_col + 1):
            cell = ws.Cells(row, col)
            area = _merge_area(cell)
            if area is None:
                cell.ClearContents()
                continue
            if area in handled:
                continue
            handled.add(area)
            top, left, bottom, right = area
            if (top < first_row or bottom > last_row or
                    left < first_col or right > last_col):
                continue
            ws.Range(
                ws.Cells(top, left), ws.Cells(bottom, right)).ClearContents()


def _split_block_merges(ws, first_row, last_row, cols):
    """Split vertical merges so每一列都能帶自己的數值。

    Only merges fully inside the block are split. A merge crossing the block
    boundary belongs to a neighbouring 工項 and must stay as-is.
    """
    for col in cols:
        row = first_row
        while row <= last_row:
            area = _merge_area(ws.Cells(row, col))
            if area is None:
                row += 1
                continue
            top, left, bottom, right = area
            if top < first_row or bottom > last_row:
                row = max(bottom, row) + 1
                continue
            try:
                ws.Range(
                    ws.Cells(top, left), ws.Cells(bottom, right)).UnMerge()
            except Exception:
                pass
            row = max(bottom, row) + 1


def _excel_open(path, read_only):
    xl_type = Type.GetTypeFromProgID('Excel.Application')
    if xl_type is None:
        raise Exception(u'找不到 Excel（COM）。此功能需要本機安裝 Microsoft Excel。')
    excel = Activator.CreateInstance(xl_type)
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        excel.EnableEvents = False
        excel.AskToUpdateLinks = False
        excel.AutomationSecurity = 3
        excel.Calculation = XL_CALCULATION_MANUAL
        # 逐格寫入時每次都重繪畫面是這支流程最大的固定成本之一
        excel.ScreenUpdating = False
    except Exception:
        pass
    wb = excel.Workbooks.Open(path, 0, read_only)
    return excel, wb


def _excel_close(excel, wb, save):
    try:
        if wb is not None:
            if save:
                # _calculate_workbook() 已經做過整本重建，這裡只補算尚未更新的
                # 部分即可；再開一次 ForceFullCalculation 等於整本重建第二次。
                try:
                    wb.Application.Calculate()
                except Exception:
                    pass
                wb.Save()
            wb.Close(False)
            try:
                Marshal.FinalReleaseComObject(wb)
            except Exception:
                try:
                    Marshal.ReleaseComObject(wb)
                except Exception:
                    pass
    finally:
        if excel is not None:
            try:
                excel.Quit()
            except Exception:
                pass
            try:
                Marshal.FinalReleaseComObject(excel)
            except Exception:
                try:
                    Marshal.ReleaseComObject(excel)
                except Exception:
                    pass
        try:
            GC.Collect()
            GC.WaitForPendingFinalizers()
            GC.Collect()
            GC.WaitForPendingFinalizers()
        except Exception:
            pass


def _sheet_by_trim(wb, requested, required=True):
    wanted = _text(requested).strip()
    for ws in wb.Worksheets:
        if _text(ws.Name).strip() == wanted:
            return ws
    if required:
        raise Exception(u'Excel 找不到分頁「{}」。'.format(requested))
    return None


def _find_header_columns(ws):
    for row in range(1, 9):
        found = {}
        for col in range(1, 21):
            label = _text(ws.Cells(row, col).Text).replace(u'\n', u'')
            if u'房間編號' in label or label == u'編號':
                found.setdefault('number', col)
            elif u'房間名稱' in label or u'空間名稱' in label:
                found.setdefault('name', col)
            elif u'周長' in label:
                found.setdefault('perimeter', col)
            elif u'面積' in label:
                found.setdefault('area', col)
            elif u'樓層' in label or u'樓別' in label:
                found.setdefault('level', col)
            elif label.replace(u' ', u'').lower() == u'revitid':
                found.setdefault('rid', col)
        if all(key in found for key in ('number', 'name', 'perimeter')):
            return row, found
    raise Exception(u'「{}」找不到房間編號、房間名稱與周長欄。'.format(ws.Name))


def _read_space_table(ws):
    header_row, cols = _find_header_columns(ws)
    last_row = ws.Cells(ws.Rows.Count, cols['number']).End(XL_UP).Row
    entries = []
    for row in range(header_row + 1, last_row + 1):
        number = _norm_number(ws.Cells(row, cols['number']).Text)
        if not number:
            continue
        entries.append({
            'row': row,
            'number': number,
            'name': _text(ws.Cells(row, cols['name']).Text),
            'level': _text(ws.Cells(row, cols.get('level', 1)).Text),
            'composite_id': (
                _text(ws.Cells(row, cols['rid']).Text)
                if cols.get('rid') else u''),
            'perimeter': _positive(ws.Cells(row, cols['perimeter']).Value2),
            'area': _positive(ws.Cells(row, cols.get('area', cols['perimeter'])).Value2),
            'perimeter_col': cols['perimeter'],
        })
    if not entries:
        raise Exception(u'「{}」沒有可讀取的房間資料。'.format(ws.Name))
    rows_by_number = {}
    for entry in entries:
        rows_by_number.setdefault(entry['number'], []).append(entry['row'])
    duplicates = [(number, rows) for number, rows in rows_by_number.items()
                  if len(rows) > 1]
    if duplicates:
        detail = u'、'.join(
            u'{}（第 {} 列）'.format(number, u'/'.join(str(row) for row in rows))
            for number, rows in sorted(duplicates))
        raise Exception(
            u'「{}」有重複房間編號，為避免雙重計量已中止：\n{}'.format(
                ws.Name, detail))
    return entries


def _find_inner_wall_columns(ws):
    for row in range(1, 12):
        number_col = None
        height_col = None
        for col in range(1, 16):
            label = _text(ws.Cells(row, col).Text).replace(u'\n', u'')
            if label in (u'編號', u'房間編號'):
                number_col = col
            if (u'天花高' in label or u'淨高' in label or
                    label in (u'高度', u'牆高')):
                height_col = col
        if number_col and height_col:
            return row, number_col, height_col
    return 5, 3, 8


def _read_inner_wall_heights(ws, wanted_numbers):
    if ws is None:
        return {}
    header_row, number_col, height_col = _find_inner_wall_columns(ws)
    last_row = ws.Cells(ws.Rows.Count, number_col).End(XL_UP).Row
    result = {}
    for row in range(header_row + 1, last_row + 1):
        number = _norm_number(ws.Cells(row, number_col).Text)
        if number not in wanted_numbers or number in result:
            continue
        height = _positive(ws.Cells(row, height_col).Value2)
        if height:
            result[number] = {
                'value': height,
                'row': row,
                'col': height_col,
                'sheet': ws.Name,
            }
    return result


def _excluded_level(level):
    value = re.sub(r'\s+', '', _text(level)).upper()
    for token in EXCLUDE_LEVELS:
        if value == token or value.endswith(u'-' + token) or value.endswith(token):
            return token
    return None


def _classify(level, number, name):
    level_rule = _excluded_level(level)
    if level_rule:
        return 'excluded', u'排除樓層：{}'.format(level_rule)
    evidence = u'{} {}'.format(number, name)
    for keyword in FINISH_KEYWORDS:
        if keyword in evidence:
            return 'interior_finish_scaffold', u'樓梯/電梯類：{}'.format(keyword)
    for keyword in EXCLUDE_KEYWORDS:
        if keyword in evidence:
            return 'excluded', u'排除房間：{}'.format(keyword)
    return 'general_scaffold', u'一般室內房間'


def _room_sort_key(item):
    return room_takeoff_sources_logic.room_number_sort_key(
        item.get('number'))


def _collect_room_takeoff(options=None):
    if options is not None:
        data = room_takeoff_sources.collect_selected_rooms(
            revit.doc, options)
        combined_heights = {}
        for source in data.get('Sources') or []:
            source_rooms = source.get('records') or []
            room_ids = []
            force_slab_ids = []
            for room in source_rooms:
                room_id = _number(room.get('LocalElementId'))
                if room_id is None:
                    continue
                room_id = int(room_id)
                room_ids.append(room_id)
                evidence = u'{} {}'.format(
                    _text(room.get('Number')), _text(room.get('Name')))
                if any(keyword in evidence for keyword in FINISH_KEYWORDS):
                    force_slab_ids.append(room_id)
            resolved = scaffold_height.resolve_room_heights(
                source['source_doc'], room_ids, force_slab_ids)
            local_heights = resolved.get('rooms') or {}
            for room in source_rooms:
                local_id = _text(room.get('LocalElementId'))
                height = local_heights.get(local_id)
                if height is not None:
                    combined_heights[room.get('CompositeId')] = height
        data['_height_evidence'] = {'rooms': combined_heights}
        return data

    data = mcp.run('calculate_room_scaffold_perimeters', {
        'includeRoomDetails': True,
        'finishKeywords': FINISH_KEYWORDS,
        'excludeKeywords': EXCLUDE_KEYWORDS,
        'excludeLevels': EXCLUDE_LEVELS,
    })
    room_ids = []
    force_slab_ids = []
    for room in data.get('Rooms') or []:
        room_id = _number(room.get('ElementId'))
        if room_id is None:
            continue
        room_id = int(room_id)
        room_ids.append(room_id)
        evidence = u'{} {}'.format(
            _text(room.get('Number')), _text(room.get('Name')))
        if (room.get('CategoryKey') == 'interior_finish_scaffold' or
                any(keyword in evidence for keyword in FINISH_KEYWORDS)):
            force_slab_ids.append(room_id)
    data['_height_evidence'] = scaffold_height.resolve_room_heights(
        revit.doc, room_ids, force_slab_ids)
    return data


def _collect_exterior_takeoff():
    selected_count = 0
    try:
        selected_count = revit.uidoc.Selection.GetElementIds().Count
    except Exception:
        pass
    choices = [
        u'目前選取的詳圖線／填滿區域（建議）',
        u'自動偵測目前視圖外牆（輔助）',
    ]
    choice = forms.SelectFromList.show(
        choices,
        title=u'選擇室外框式施工架周長來源',
        multiselect=False,
    )
    if not choice:
        return None
    if choice == choices[0] and selected_count <= 0:
        forms.alert(
            u'目前沒有選取元素。\n\n請先選取描繪施工架外框的詳圖線、詳圖元件或填滿區域。',
            title=ITEM_NAMES['exterior'],
        )
        return None
    height_text = forms.ask_for_string(
        default=u'',
        prompt=u'請輸入室外框式施工架總高度（m）。\n此高度會與外部周長相乘。',
        title=ITEM_NAMES['exterior'],
    )
    if height_text is None:
        return None
    height = _positive(height_text)
    if not height:
        forms.alert(u'施工架高度必須是大於 0 的數字（單位 m）。', title=ITEM_NAMES['exterior'])
        return None
    params = {'scaffoldHeightMm': height * 1000.0}
    if choice == choices[0]:
        command = 'calculate_selected_detail_line_perimeter'
        source = u'目前選取的詳圖線／填滿區域'
    else:
        command = 'calculate_exterior_wall_scaffold_perimeter'
        params.update({'activeViewOnly': True, 'selectResult': True})
        source = u'目前視圖外牆幾何射線（輔助）'
    data = mcp.run(command, params)
    perimeter = _positive(data.get('TotalLengthM'))
    area = _positive(data.get('ScaffoldAreaSqM'))
    if perimeter is None or area is None:
        raise Exception(u'室外施工架未取得有效周長或面積。')
    return {
        'source': source,
        'command': command,
        'perimeter': perimeter,
        'height': height,
        'quantity': area,
        'raw': data,
    }


def _map_revit_rooms(data):
    mapped = {}
    duplicates = set()
    for room in data.get('Rooms') or []:
        number = _norm_number(room.get('Number'))
        composite_id = _text(
            room.get('CompositeId') or room.get('ElementId'))
        if composite_id:
            mapped[u'id:' + composite_id] = room
        if not number:
            continue
        number_key = u'number:' + number
        if number_key in mapped:
            duplicates.add(number)
        else:
            mapped[number_key] = room
    skipped = {}
    for room in data.get('SkippedRooms') or []:
        number = _norm_number(room.get('Number'))
        if number:
            skipped[number] = room
    return mapped, duplicates, skipped


def _build_room_rows(space_entries, height_evidence, data, space_sheet_name):
    revit_rooms, duplicate_numbers, skipped_rooms = _map_revit_rooms(data)
    excel_numbers = set(item['number'] for item in space_entries)
    revit_numbers = set(
        _norm_number(room.get('Number'))
        for room in data.get('Rooms') or []
        if _norm_number(room.get('Number')))
    result = []
    totals = {'general': 0.0, 'interior_finish': 0.0}
    counts = {
        'general': 0,
        'interior_finish': 0,
        'excluded': 0,
        'missing_revit': 0,
        'missing_height': 0,
        'revit_only': len(revit_numbers - excel_numbers),
        'ceiling_height': 0,
        'slab_height': 0,
        'fallback_height': 0,
    }
    for entry in space_entries:
        number = entry['number']
        composite_id = _text(entry.get('composite_id'))
        room = None
        if composite_id:
            room = revit_rooms.get(u'id:' + composite_id)
        if room is None and number not in duplicate_numbers:
            room = revit_rooms.get(u'number:' + number)
        warnings = []
        if number in duplicate_numbers and not composite_id:
            warnings.append(u'Revit 房間編號重複，未計入')
            room = None
        if room is None:
            counts['missing_revit'] += 1
            if number in skipped_rooms:
                warnings.append(u'Revit 房間沒有有效 Finish boundary，未計入')
            else:
                warnings.append(u'{}有列、Revit 無對應房間，未計入'.format(
                    space_sheet_name))

        current_level = _text(room.get('Level')) if room else entry['level']
        current_name = _text(room.get('Name')) if room else entry['name']
        if room and entry['name'] and current_name != entry['name']:
            warnings.append(u'房名不一致：{}「{}」/ Revit「{}」'.format(
                space_sheet_name, entry['name'], current_name))
        category, rule = _classify(current_level, number, current_name)

        height = None
        height_source = u''
        height_ref = None
        room_height = None
        if room:
            room_height = (height_evidence.get('rooms') or {}).get(
                _text(room.get('CompositeId') or room.get('ElementId')))
        if room_height:
            height = _positive(room_height.get('height'))
            height_source = _text(room_height.get('label'))
            warnings.extend(room_height.get('warnings') or [])
            ceiling_names = room_height.get('ceiling_names') or []
            if ceiling_names:
                warnings.append(u'實體天花：{}'.format(
                    u'、'.join(ceiling_names[:3])))
            if category != 'excluded' and height:
                source = _text(room_height.get('source'))
                if source.startswith('actual-ceiling'):
                    counts['ceiling_height'] += 1
                elif 'floor' in source or 'slab' in source or 'level-to-level' in source:
                    counts['slab_height'] += 1
                else:
                    counts['fallback_height'] += 1
        elif room:
            height = _positive(room.get('HeightM'))
            if height:
                height_source = u'Revit Room 高度備援（缺少幾何證據）'
                warnings.append(u'高度證據解析未回傳此房間，使用 MCP Room 高度備援')
                if category != 'excluded':
                    counts['fallback_height'] += 1
        if category != 'excluded' and not height:
            counts['missing_height'] += 1
            warnings.append(u'缺少有效高度，未計入')

        perimeter = entry.get('perimeter')
        length = _positive(room.get('LengthM')) if room else None
        width = _positive(room.get('WidthM')) if room else None
        dimension_source = _text(room.get('DimensionSource')) if room else u''
        if u'BoundingBox' in dimension_source:
            warnings.append(dimension_source)
        included = room is not None and (
            bool(composite_id) or number not in duplicate_numbers)
        quantity = 0.0
        unit = u''
        formula_text = u''
        category_name = u'不計入'
        if category == 'general_scaffold':
            unit = u'M2'
            category_name = ITEM_NAMES['general']
            included = included and perimeter is not None and height is not None
            if perimeter is None:
                warnings.append(u'{}缺少周長，未計入'.format(space_sheet_name))
            if included:
                quantity = _round_product_quantity((perimeter, height))
                totals['general'] += quantity
                counts['general'] += 1
            formula_text = u'{}周長 × 高度'.format(space_sheet_name)
        elif category == 'interior_finish_scaffold':
            unit = u'M3'
            category_name = ITEM_NAMES['interior_finish']
            included = included and length is not None and width is not None and height is not None
            if length is None or width is None:
                warnings.append(u'Revit 房間長寬不足，未計入')
            room_area = _positive(room.get('AreaM2')) if room else None
            plan_box_area = length * width if length and width else None
            if (room_area and plan_box_area and
                    plan_box_area > room_area * 1.10 and
                    plan_box_area - room_area > 0.50):
                warnings.append(
                    u'長×寬包絡面積 {} m2 比 Room 面積 {} m2 大 {}%；'
                    u'可能為旋轉或不規則房間，請人工確認'.format(
                        _fmt(plan_box_area), _fmt(room_area),
                        _fmt((plan_box_area / room_area - 1.0) * 100.0, 1)))
            if included:
                quantity = _round_product_quantity((length, width, height))
                totals['interior_finish'] += quantity
                counts['interior_finish'] += 1
            formula_text = u'Revit 房間長 × 寬 × 高度'
        else:
            included = False
            counts['excluded'] += 1

        result.append({
            'revit_id': _text(
                room.get('CompositeId') or room.get('ElementId'))
            if room else u'',
            'local_element_id': _text(
                room.get('LocalElementId') or room.get('ElementId'))
            if room else u'',
            'source_key': _text(room.get('SourceKey')) if room else u'',
            'source_label': _text(room.get('SourceLabel')) if room else u'',
            'level': current_level,
            'number': number,
            'name': current_name,
            'category': category,
            'category_name': category_name,
            'rule': rule,
            'space_row': entry['row'],
            'space_sheet': space_sheet_name,
            'perimeter_col': entry['perimeter_col'],
            'perimeter': perimeter,
            'length': length,
            'width': width,
            'dimension_source': dimension_source,
            'height': height,
            'height_source': height_source,
            'height_ref': height_ref,
            'formula_text': formula_text,
            'quantity': quantity,
            'unit': unit,
            'included': included,
            'warnings': _concise_room_warnings(warnings),
            'audit_warnings': warnings,
        })
    result.sort(key=lambda item: (
        _level_sort_key(item.get('level')), _room_sort_key(item)))
    totals['general'] = _round_quantity(totals['general'])
    totals['interior_finish'] = _round_quantity(totals['interior_finish'])
    return {
        'rows': result,
        'totals': totals,
        'counts': counts,
        'space_sheet': space_sheet_name,
    }


def _item_kind(value):
    text = re.sub(r'\s+', '', _text(value))
    if u'室內裝修施工架' in text:
        return 'interior_finish'
    if u'框式施工架' in text:
        return 'exterior'
    if u'施工架' in text and (u'防護設施' in text or u'防護措施' in text):
        return 'general'
    return None


def _find_item_row(ws, mode):
    used = ws.UsedRange
    first_row = max(1, used.Row)
    last_row = min(1000, used.Row + used.Rows.Count - 1)
    first_col = max(1, used.Column)
    last_col = min(20, used.Column + used.Columns.Count - 1)
    for row in range(first_row, last_row + 1):
        for col in range(first_col, last_col + 1):
            if _item_kind(ws.Cells(row, col).Value2) == mode:
                return row, col
    return None, None


def _looks_like_calculation_item(ws, row):
    return bool(
        _text(ws.Cells(row, 2).Value2) and
        _text(ws.Cells(row, 3).Value2) and
        _text(ws.Cells(row, 5).Value2))


def _next_calculation_item_row(ws, start_row):
    used = ws.UsedRange
    last_row = min(1000, used.Row + used.Rows.Count - 1)
    for row in range(start_row + 1, last_row + 1):
        if _looks_like_calculation_item(ws, row):
            return row
    return start_row + 1


def _item_blocks(ws, item_rows):
    blocks = {}
    starts = sorted(row for row in item_rows.values() if row)
    for mode, start_row in item_rows.items():
        if not start_row:
            continue
        later = [row for row in starts if row > start_row]
        if later:
            end_row = min(later) - 1
        else:
            end_row = _next_calculation_item_row(ws, start_row) - 1
        blocks[mode] = (start_row, max(start_row, end_row))
    return blocks


def _level_text(value):
    text = _text(value).upper()
    text = text.replace(u'樓層', u'').replace(u'樓', u'')
    return re.sub(r'[\s_]+', u'', text)


def _takeoff_building_prefixes(takeoff):
    """Detect prefixes such as B- in B-B1F/B-1F/B-R1F level names."""
    prefixes = set()
    for item in takeoff.get('rows') or []:
        text = _level_text(item.get('level'))
        match = re.match(
            r'^([A-Z][A-Z0-9]*)-(?:B0*\d+F?|R0*\d+F?|RF|FN|TF)$', text)
        if match:
            prefixes.add(match.group(1))
    return prefixes


def _level_key(value, building_prefixes=None):
    text = _level_text(value)
    for prefix in sorted(building_prefixes or [], key=len, reverse=True):
        marker = prefix + u'-'
        if not text.startswith(marker):
            continue
        candidate = text[len(marker):]
        if re.match(r'^(?:B0*\d+F?|R0*\d+F?|0*\d+M?F?|RF|FN|TF)$', candidate):
            text = candidate
            break
    text = text.replace(u'-', u'')
    if text == u'RF':
        return u'RF'
    match = re.match(r'^B0*(\d+)F?$', text)
    if match:
        return u'B{}F'.format(int(match.group(1)))
    match = re.match(r'^R0*(\d+)F?$', text)
    if match:
        return u'R{}F'.format(int(match.group(1)))
    match = re.match(r'^0*(\d+)MF$', text)
    if match:
        return u'{}MF'.format(int(match.group(1)))
    match = re.match(r'^0*(\d+)F?$', text)
    if match:
        return u'{}F'.format(int(match.group(1)))
    return text


def _recognized_level_key(key):
    return bool(
        key == u'RF' or
        re.match(r'^(?:B\d+F|\d+F|\d+MF|R\d+F)$', key))


def _level_sort_key(level):
    """地下深層到 B1F，接地上層，再接屋突層，最後放未知樓層。"""
    key = _level_key(level)
    match = re.match(r'^B(\d+)F$', key)
    if match:
        return (0, -int(match.group(1)), key)
    match = re.match(r'^(\d+)F$', key)
    if match:
        return (1, int(match.group(1)), key)
    match = re.match(r'^(\d+)MF$', key)
    if match:
        return (2, int(match.group(1)), key)
    match = re.match(r'^R(\d+)F$', key)
    if match:
        return (3, int(match.group(1)), key)
    if key == u'RF':
        return (3, 9999, key)
    return (9, 0, key)


def _takeoff_levels(takeoff):
    """Get active Revit room levels; Excel template rows are never the source."""
    levels = {}
    building_prefixes = _takeoff_building_prefixes(takeoff)
    for item in takeoff.get('rows') or []:
        if not item.get('revit_id') or item.get('category') == 'excluded':
            continue
        raw_display = _text(item.get('level'))
        key = _level_key(raw_display, building_prefixes)
        display = key if _recognized_level_key(key) else raw_display
        if key and key not in levels:
            levels[key] = display
    return [
        {'key': key, 'display': display}
        for key, display in sorted(
            levels.items(), key=lambda pair: _level_sort_key(pair[1]))
    ]


def _general_level_totals(takeoff):
    levels = _takeoff_levels(takeoff)
    building_prefixes = _takeoff_building_prefixes(takeoff)
    totals = dict(
        (level['key'], {'perimeter': 0.0, 'quantity': 0.0})
        for level in levels)
    for item in takeoff.get('rows') or []:
        if not item.get('included') or item.get('category') != 'general_scaffold':
            continue
        key = _level_key(item.get('level'), building_prefixes)
        if key not in totals:
            totals[key] = {'perimeter': 0.0, 'quantity': 0.0}
        totals[key]['perimeter'] += _number(item.get('perimeter')) or 0.0
        totals[key]['quantity'] += _number(item.get('quantity')) or 0.0
    for values in totals.values():
        values['perimeter'] = _round_quantity(values['perimeter'])
        values['quantity'] = _round_quantity(values['quantity'])
    target = _round_quantity(
        _number(takeoff.get('totals', {}).get('general')) or 0.0, 3)
    displayed = _round_quantity(sum(values['quantity'] for values in totals.values()))
    remainder = _round_quantity(target - displayed)
    if abs(remainder) >= 0.001:
        for level in reversed(levels):
            values = totals[level['key']]
            if abs(values['quantity']) >= 0.001:
                values['quantity'] = _round_quantity(values['quantity'] + remainder)
                break
    return totals


def _general_level_summary_rows(takeoff):
    result = {}
    for offset, level in enumerate(_takeoff_levels(takeoff)):
        result[level['key']] = LEVEL_SUMMARY_START_ROW + offset
    return result


def _read_old_totals(wb):
    ws = _sheet_by_trim(wb, OTHER_AREA_SHEET)
    result = {}
    for mode in ('exterior', 'general', 'interior_finish'):
        row, unused = _find_item_row(ws, mode)
        value = None
        if row:
            total_cell = ws.Cells(row, 16)
            value = None if _cell_has_excel_error(total_cell) else _number(total_cell.Value2)
            if value is None:
                quantity_cell = ws.Cells(row, 8)
                if not _cell_has_excel_error(quantity_cell):
                    value = _number(quantity_cell.Value2)
        result[mode] = value
    return result


def _validate_template(wb, needs_rooms, space_sheet_name=None):
    for name in (OTHER_AREA_SHEET, SUBTOTAL_SHEET):
        _sheet_by_trim(wb, name)
    subtotal = _sheet_by_trim(wb, SUBTOTAL_SHEET)
    other = _sheet_by_trim(wb, OTHER_AREA_SHEET)
    for mode in ('exterior', 'general'):
        for ws in (subtotal, other):
            row, unused = _find_item_row(ws, mode)
            if not row:
                raise Exception(u'「{}」找不到既有工項「{}」。'.format(
                    ws.Name, ITEM_NAMES[mode]))
    if needs_rooms:
        _sheet_by_trim(wb, space_sheet_name or SPACE_SHEET)


def _copy_insert_row(excel, ws, source_row, insert_row):
    ws.Rows(source_row).Copy()
    ws.Rows(insert_row).Insert()
    excel.CutCopyMode = False


def _renumber_section(ws, start_row, number_col, name_col, marker_col):
    previous = _number(ws.Cells(start_row - 1, number_col).Value2)
    if previous is None:
        previous = 0
    number = int(previous)
    for row in range(start_row, min(start_row + 250, ws.Rows.Count) + 1):
        if not _text(ws.Cells(row, name_col).Value2):
            break
        if not _text(ws.Cells(row, marker_col).Value2):
            break
        number += 1
        ws.Cells(row, number_col).Value2 = number


def _expand_general_level_block(excel, ws, item_rows, takeoff):
    levels = _takeoff_levels(takeoff)
    blocks = _item_blocks(ws, item_rows)
    start_row, end_row = blocks['general']
    missing_rows = len(levels) - (end_row - start_row + 1)
    if missing_rows <= 0:
        return

    source_row = start_row + 1 if end_row > start_row else start_row
    for offset in range(missing_rows):
        insert_row = end_row + 1 + offset
        _copy_insert_row(excel, ws, source_row, insert_row)
        # Keep row formatting only. Calculation inputs are rewritten explicitly.
        # Inserting inside the block stretches the 工項名稱 B/C 與總量 P 合併範圍,
        # so the clear has to skip those instead of failing on them.
        _clear_contents(ws, insert_row, 1, insert_row, 4)
        _clear_contents(ws, insert_row, 5, insert_row, 18)


def _ensure_item_rows(wb, excel, takeoff=None):
    subtotal = _sheet_by_trim(wb, SUBTOTAL_SHEET)
    update = _sheet_by_trim(wb, UPDATE_ITEM_SHEET, required=False)
    other = _sheet_by_trim(wb, OTHER_AREA_SHEET)
    created_finish = False

    ext_row, unused = _find_item_row(subtotal, 'exterior')
    gen_row, unused = _find_item_row(subtotal, 'general')
    finish_row, unused = _find_item_row(subtotal, 'interior_finish')
    if not ext_row or not gen_row:
        raise Exception(u'「小計」缺少既有室外或室內施工架工項。')
    if not finish_row:
        finish_row = gen_row + 1
        _copy_insert_row(excel, subtotal, gen_row, finish_row)
        subtotal.Cells(finish_row, SUBTOTAL_COLS['name']).Value2 = ITEM_NAMES['interior_finish']
        created_finish = True
    subtotal_rows = {}
    for mode in ('exterior', 'general', 'interior_finish'):
        row, unused = _find_item_row(subtotal, mode)
        if mode == 'interior_finish' and not row:
            row = finish_row
        subtotal_rows[mode] = row
        subtotal.Cells(row, SUBTOTAL_COLS['unit']).Value2 = ITEM_UNITS[mode]
        subtotal.Cells(row, SUBTOTAL_COLS['rounded_qty']).Formula = _rounded_qty_formula(row)
        subtotal.Cells(row, SUBTOTAL_COLS['source']).Value2 = u'其他面積數量計算表'

    update_rows = dict((mode, (None, None)) for mode in (
        'exterior', 'general', 'interior_finish'))
    if update is not None:
        update_rows = dict((mode, _find_item_row(update, mode)) for mode in (
            'exterior', 'general', 'interior_finish'))
    update_rows = dict((mode, value[0]) for mode, value in update_rows.items())

    ext_row, unused = _find_item_row(other, 'exterior')
    gen_row, unused = _find_item_row(other, 'general')
    finish_row, unused = _find_item_row(other, 'interior_finish')
    if not ext_row or not gen_row:
        raise Exception(u'「{}」缺少既有室外或室內施工架工項。'.format(other.Name))
    if not finish_row:
        finish_row = _next_calculation_item_row(other, gen_row)
        _copy_insert_row(excel, other, gen_row, finish_row)
        _clear_contents(other, finish_row, 6, finish_row, 18)
        other.Cells(finish_row, OTHER_COLS['name']).Value2 = ITEM_NAMES['interior_finish']
        other.Cells(finish_row, 4).Value2 = u'ALL'
        created_finish = True
    other_rows = {}
    for mode in ('exterior', 'general', 'interior_finish'):
        row, unused = _find_item_row(other, mode)
        if mode == 'interior_finish' and not row:
            row = finish_row
        other_rows[mode] = row

    # 一般室內施工架區塊是逐樓層表。有些工項活頁簿（例如綜合大樓）把整個區塊的
    # I 欄縱向合併成 =SUM(H..)，各樓層數量就寫不進自己的列，之後的清空也會被
    # Excel 以「無法對合併儲存格執行該動作」擋下，所以展開樓層列之前先拆開。
    general_block = _item_blocks(other, other_rows).get('general')
    if general_block:
        _split_block_merges(
            other, general_block[0], general_block[1], range(4, 10))

    if takeoff and takeoff.get('rows'):
        _expand_general_level_block(excel, other, other_rows, takeoff)
        other_rows = {}
        for mode in ('exterior', 'general', 'interior_finish'):
            row, unused = _find_item_row(other, mode)
            other_rows[mode] = row
    other_blocks = _item_blocks(other, other_rows)

    for mode in ('exterior', 'general', 'interior_finish'):
        sr = subtotal_rows[mode]
        other_row = other_rows[mode]
        subtotal.Cells(sr, SUBTOTAL_COLS['unit']).Value2 = ITEM_UNITS[mode]
        subtotal.Cells(sr, SUBTOTAL_COLS['rounded_qty']).Formula = _rounded_qty_formula(sr)
        subtotal.Cells(sr, SUBTOTAL_COLS['source']).Value2 = u'其他面積數量計算表'
        subtotal.Cells(sr, SUBTOTAL_COLS['quantity']).Formula = u'=' + _sheet_ref(
                                                          other.Name, OTHER_COLS['total'], other_row)

        ur = update_rows.get(mode)
        if update is not None and ur:
            update.Cells(ur, UPDATE_COLS['name']).Formula = u'=' + _sheet_ref(
                                                            subtotal.Name, SUBTOTAL_COLS['name'], sr)
            update.Cells(ur, UPDATE_COLS['unit']).Formula = u'=' + _sheet_ref(
                                                            subtotal.Name, SUBTOTAL_COLS['unit'], sr)
            update.Cells(ur, UPDATE_COLS['rounded_qty']).Formula = u'=' + _sheet_ref(
                                                            subtotal.Name, SUBTOTAL_COLS['rounded_qty'], sr)
            update.Cells(ur, UPDATE_COLS['source']).Formula = u'=' + _sheet_ref(
                                                            subtotal.Name, SUBTOTAL_COLS['source'], sr)
            update.Cells(ur, UPDATE_COLS['quantity']).Formula = u'=' + _sheet_ref(
                                                            subtotal.Name, SUBTOTAL_COLS['quantity'], sr)

        other.Cells(other_row, 2).Formula = u'=' + _sheet_ref(
                                                              subtotal.Name, SUBTOTAL_COLS['code'], sr)
        other.Cells(other_row, OTHER_COLS['name']).Formula = u'=' + _sheet_ref(
                                                              subtotal.Name, SUBTOTAL_COLS['name'], sr)

    return {
        'subtotal': subtotal,
        'update': update,
        'other': other,
        'subtotal_rows': subtotal_rows,
        'update_rows': update_rows,
        'other_rows': other_rows,
        'other_blocks': other_blocks,
        'created_finish': created_finish,
    }


def _ensure_audit_sheet(wb):
    ws = _sheet_by_trim(wb, AUDIT_SHEET, required=False)
    if ws is None:
        ws = wb.Worksheets.Add()
        ws.Name = AUDIT_SHEET
    elif ws.Name != AUDIT_SHEET:
        ws.Name = AUDIT_SHEET
    try:
        ws.Range(AUDIT_TITLE_SPAN).UnMerge()
    except Exception:
        pass
    ws.Range(AUDIT_TITLE_SPAN).Merge()
    ws.Cells(1, 1).Value2 = u'施工架數量計算稽核表'
    ws.Cells(1, 1).Font.Name = REPORT_FONT_NAME
    ws.Cells(1, 1).Font.Bold = False
    ws.Cells(1, 1).Font.Size = 24
    ws.Cells(1, 1).HorizontalAlignment = -4108
    ws.Cells(1, 1).VerticalAlignment = -4108
    ws.Range(AUDIT_TITLE_SPAN).Interior.Color = _rgb(47, 84, 91)
    ws.Range(AUDIT_TITLE_SPAN).Font.Color = _rgb(255, 255, 255)

    for key, value in zip(AUDIT_SUMMARY_COLUMNS, AUDIT_SUMMARY_HEADERS):
        ws.Cells(AUDIT_HEADER_ROW, AUDIT_SUMMARY.number(key)).Value2 = value
    for mode in ('exterior', 'general', 'interior_finish'):
        row = SUMMARY_ROWS[mode]
        ws.Cells(row, AUDIT_SUMMARY.number('item')).Value2 = ITEM_NAMES[mode]
        ws.Cells(row, AUDIT_SUMMARY.number('unit')).Value2 = ITEM_UNITS[mode]

    first, last = AUDIT_SUMMARY_COLUMNS[0], AUDIT_SUMMARY_COLUMNS[-1]
    header_span = AUDIT_SUMMARY.rect(first, last, AUDIT_HEADER_ROW)
    body_span = AUDIT_SUMMARY.rect(first, last,
                                   SUMMARY_FIRST_ROW, SUMMARY_LAST_ROW)
    whole_span = AUDIT_SUMMARY.rect(first, last,
                                    AUDIT_HEADER_ROW, SUMMARY_LAST_ROW)
    ws.Range(header_span).Font.Name = REPORT_FONT_NAME
    ws.Range(header_span).Font.Bold = False
    ws.Range(body_span).Font.Name = REPORT_FONT_NAME
    ws.Range(body_span).Font.Size = 9
    ws.Range(body_span).Font.Bold = True
    ws.Range(header_span).Interior.Color = _rgb(217, 225, 225)
    ws.Range(whole_span).Borders.LineStyle = 1
    ws.Range(AUDIT_SUMMARY.rng('quantity', SUMMARY_FIRST_ROW,
                               SUMMARY_LAST_ROW)).NumberFormat = u'0.000'
    for key, width in zip(AUDIT_SUMMARY_COLUMNS, AUDIT_SUMMARY_WIDTHS):
        ws.Columns(AUDIT_SUMMARY.number(key)).ColumnWidth = width
    return ws


def _clear_room_audit(ws):
    used = ws.UsedRange
    last_row = used.Row + used.Rows.Count - 1
    if last_row >= 9:
        ws.Range(ws.Rows(9), ws.Rows(last_row)).EntireRow.Delete()


def _write_general_level_summary(ws, takeoff, last_room_row):
    headers = [u'樓層', u'樓層鍵', u'一般室內施工架小計(M2)']
    for offset, value in enumerate(headers):
        ws.Cells(LEVEL_SUMMARY_HEADER_ROW, LEVEL_SUMMARY_LEVEL_COL + offset).Value2 = value
    ws.Range(
        ws.Cells(LEVEL_SUMMARY_HEADER_ROW, LEVEL_SUMMARY_LEVEL_COL),
        ws.Cells(LEVEL_SUMMARY_HEADER_ROW, LEVEL_SUMMARY_GENERAL_COL),
    ).Font.Name = REPORT_FONT_NAME
    ws.Range(
        ws.Cells(LEVEL_SUMMARY_HEADER_ROW, LEVEL_SUMMARY_LEVEL_COL),
        ws.Cells(LEVEL_SUMMARY_HEADER_ROW, LEVEL_SUMMARY_GENERAL_COL),
    ).Interior.Color = _rgb(217, 225, 225)

    levels = _takeoff_levels(takeoff)
    if not levels:
        return None
    if last_room_row < 10:
        last_room_row = 10
    for offset, level in enumerate(levels):
        row = LEVEL_SUMMARY_START_ROW + offset
        ws.Cells(row, LEVEL_SUMMARY_LEVEL_COL).Value2 = level['display']
        ws.Cells(row, LEVEL_SUMMARY_KEY_COL).Value2 = level['key']
        # $O/$S/$E/$Q are per-room detail columns and never move; the criteria
        # cell is this table's own 樓層鍵 column, so it must follow the constant.
        ws.Cells(row, LEVEL_SUMMARY_GENERAL_COL).Formula = (
            u'=ROUND(SUMIFS($O$10:$O${last},$S$10:$S${last},${key}{row},'
            u'$E$10:$E${last},"general_scaffold",$Q$10:$Q${last},"是"),3)'
        ).format(last=last_room_row, row=row,
                 key=_col_letter(LEVEL_SUMMARY_KEY_COL))
    last_summary_row = LEVEL_SUMMARY_START_ROW + len(levels) - 1
    ws.Range(
        ws.Cells(LEVEL_SUMMARY_HEADER_ROW, LEVEL_SUMMARY_LEVEL_COL),
        ws.Cells(last_summary_row, LEVEL_SUMMARY_GENERAL_COL),
    ).Borders.LineStyle = 1
    ws.Range(
        ws.Cells(LEVEL_SUMMARY_START_ROW, LEVEL_SUMMARY_GENERAL_COL),
        ws.Cells(last_summary_row, LEVEL_SUMMARY_GENERAL_COL),
    ).NumberFormat = u'0.000'
    ws.Columns(LEVEL_SUMMARY_LEVEL_COL).ColumnWidth = 14
    ws.Columns(LEVEL_SUMMARY_KEY_COL).ColumnWidth = 12
    ws.Columns(LEVEL_SUMMARY_GENERAL_COL).ColumnWidth = 22
    return (LEVEL_SUMMARY_START_ROW, last_summary_row)


def _audit_summary_formula(category, last_room_row):
    return (
        u'=ROUND(SUMIFS($O$10:$O${last},$E$10:$E${last},"{category}",'
        u'$Q$10:$Q${last},"是"),3)'
    ).format(last=last_room_row, category=category)


def _write_room_audit(ws, takeoff):
    _clear_room_audit(ws)
    building_prefixes = _takeoff_building_prefixes(takeoff)
    space_sheet_name = _text(takeoff.get('space_sheet')) or SPACE_SHEET
    headers = dict(ROOM_AUDIT_HEADERS)
    headers['space_row'] = u'{}列'.format(space_sheet_name)
    for key in ROOM_AUDIT_COLUMNS:
        ws.Cells(ROOM_AUDIT_HEADER_ROW,
                 ROOM_AUDIT.number(key)).Value2 = headers[key]
    header_range = ROOM_AUDIT.rect(ROOM_AUDIT_COLUMNS[0],
                                   ROOM_AUDIT_COLUMNS[-1],
                                   ROOM_AUDIT_HEADER_ROW)
    ws.Range(header_range).Font.Name = REPORT_FONT_NAME
    ws.Range(header_range).Font.Bold = False
    ws.Range(header_range).Interior.Color = _rgb(217, 225, 225)
    ws.Range(header_range).WrapText = True

    start_row = ROOM_AUDIT_FIRST_ROW
    col = ROOM_AUDIT.number
    for offset, item in enumerate(takeoff['rows']):
        row = start_row + offset
        for key in ('revit_id', 'level', 'number', 'name', 'category',
                    'category_name', 'rule', 'space_row'):
            ws.Cells(row, col(key)).Value2 = item[key]
        ws.Cells(row, col('perimeter')).Formula = u'={}!{}{}'.format(
            _quote_sheet(item['space_sheet']),
            _col_letter(item['perimeter_col']),
            item['space_row'],
        )
        if item['length'] is not None:
            ws.Cells(row, col('length')).Value2 = item['length']
        if item['width'] is not None:
            ws.Cells(row, col('width')).Value2 = item['width']
        if item['height_ref']:
            ref = item['height_ref']
            ws.Cells(row, col('height')).Formula = u'={}!{}{}'.format(
                _quote_sheet(ref['sheet']), _col_letter(ref['col']), ref['row'])
        elif item['height'] is not None:
            ws.Cells(row, col('height')).Value2 = item['height']
        ws.Cells(row, col('height_source')).Value2 = item['height_source']
        ws.Cells(row, col('formula_text')).Value2 = item['formula_text']
        # 數量欄的公式以前把欄位字母（Q/I/J/K/L）寫死，跟上面的欄號是兩套真相。
        if item['category'] == 'general_scaffold':
            ws.Cells(row, col('quantity')).Formula = ROOM_AUDIT.formula(
                row, u'IF({included}="是",ROUND({perimeter}*{height},3),0)')
        elif item['category'] == 'interior_finish_scaffold':
            ws.Cells(row, col('quantity')).Formula = ROOM_AUDIT.formula(
                row,
                u'IF({included}="是",'
                u'ROUND({length}*{width}*{height},3),0)')
        else:
            ws.Cells(row, col('quantity')).Value2 = 0
        ws.Cells(row, col('unit')).Value2 = item['unit']
        ws.Cells(row, col('included')).Value2 = (
            u'是' if item['included'] else u'否')
        ws.Cells(row, col('note')).Value2 = u'；'.join(item['warnings'])
        ws.Cells(row, col('level_key')).Value2 = _level_key(
            item['level'], building_prefixes)
        ws.Cells(row, col('source_key')).Value2 = item.get('source_key') or u''
        ws.Cells(row, col('source_label')).Value2 = (
            item.get('source_label') or u'')
        ws.Cells(row, col('element_id')).Value2 = (
            item.get('local_element_id') or u'')
        ws.Cells(row, col('dimension_source')).Value2 = (
            item.get('dimension_source') or u'')

    last_row = start_row + len(takeoff['rows']) - 1
    if takeoff['rows']:
        _write_general_level_summary(ws, takeoff, last_row)
        ws.Cells(5, 2).Formula = _audit_summary_formula(
            SUMMARY_CATEGORIES['general'], last_row)
        ws.Cells(6, 2).Formula = _audit_summary_formula(
            SUMMARY_CATEGORIES['interior_finish'], last_row)
        ws.Range(ws.Cells(10, 8), ws.Cells(last_row, 8)).NumberFormat = u'0'
        ws.Range(ws.Cells(10, 9), ws.Cells(last_row, 15)).NumberFormat = u'0.000'
        ws.Range(ws.Cells(9, 1),
                 ws.Cells(last_row, ROOM_AUDIT_LAST_COL)).Borders.LineStyle = 1
        try:
            ws.Range(ws.Cells(9, 1),
                     ws.Cells(last_row, ROOM_AUDIT_LAST_COL)).AutoFilter()
        except Exception:
            pass
    else:
        ws.Cells(5, 2).Formula = u'=0'
        ws.Cells(6, 2).Formula = u'=0'
    ws.Cells(5, 4).Value2 = (
        u'逐房明細 O 欄加總：分類=general_scaffold，計入=是；'
        u'一般房間 Finish 周長 × 有效高度')
    ws.Cells(6, 4).Value2 = (
        u'逐房明細 O 欄加總：分類=interior_finish_scaffold，計入=是；'
        u'樓梯／電梯房間長 × 寬 × 上層樓板底高度')
    ws.Cells(5, 5).Value2 = datetime.now().strftime('%Y-%m-%d %H:%M')
    ws.Cells(6, 5).Value2 = datetime.now().strftime('%Y-%m-%d %H:%M')
    for key, width in zip(ROOM_AUDIT_COLUMNS, ROOM_AUDIT_WIDTHS):
        ws.Columns(ROOM_AUDIT.number(key)).ColumnWidth = width
    report_range = ws.Range(u'{}1:{}{}'.format(
        sheet_layout.column_letter(0),
        _col_letter(LEVEL_SUMMARY_GENERAL_COL),
        max(ROOM_AUDIT_HEADER_ROW, last_row)))
    report_range.Font.Name = REPORT_FONT_NAME
    report_range.Font.Size = 9
    report_range.Font.Bold = False
    # 這裡是**第二個**格式化摘要區的地方（第一個在 _ensure_audit_sheet）。
    # 兩邊都問同一個 layout，才不會有人改了一邊忘了另一邊。
    summary_first = AUDIT_SUMMARY_COLUMNS[0]
    summary_last = AUDIT_SUMMARY_COLUMNS[-1]
    header_span = AUDIT_SUMMARY.rect(summary_first, summary_last,
                                     AUDIT_HEADER_ROW)
    body_span = AUDIT_SUMMARY.rect(summary_first, summary_last,
                                   SUMMARY_FIRST_ROW, SUMMARY_LAST_ROW)
    ws.Range(AUDIT_TITLE_SPAN).Font.Size = 24
    ws.Range(AUDIT_TITLE_SPAN).Font.Name = REPORT_FONT_NAME
    ws.Range(AUDIT_TITLE_SPAN).Font.Bold = False
    ws.Range(header_span).Font.Size = 12
    ws.Range(header_span).Font.Name = REPORT_FONT_NAME
    ws.Range(header_span).Font.Bold = False
    ws.Range(body_span).Font.Name = REPORT_FONT_NAME
    ws.Range(body_span).Font.Size = 9
    ws.Range(body_span).Font.Bold = True
    ws.Range(header_range).Font.Size = 12
    ws.Range(header_range).Font.Name = REPORT_FONT_NAME
    ws.Range(header_range).Font.Bold = False
    ws.Range(
        ws.Cells(LEVEL_SUMMARY_HEADER_ROW, LEVEL_SUMMARY_LEVEL_COL),
        ws.Cells(LEVEL_SUMMARY_HEADER_ROW, LEVEL_SUMMARY_GENERAL_COL),
    ).Font.Name = REPORT_FONT_NAME
    ws.Range(
        ws.Cells(LEVEL_SUMMARY_HEADER_ROW, LEVEL_SUMMARY_LEVEL_COL),
        ws.Cells(LEVEL_SUMMARY_HEADER_ROW, LEVEL_SUMMARY_GENERAL_COL),
    ).Font.Size = 12
    ws.Range(
        ws.Cells(LEVEL_SUMMARY_HEADER_ROW, LEVEL_SUMMARY_LEVEL_COL),
        ws.Cells(LEVEL_SUMMARY_HEADER_ROW, LEVEL_SUMMARY_GENERAL_COL),
    ).Font.Bold = False


def _write_exterior_audit(ws, takeoff):
    row = SUMMARY_ROWS['exterior']
    col = AUDIT_SUMMARY.number
    ws.Cells(row, col('quantity')).Value2 = takeoff['quantity']
    ws.Cells(row, col('formula')).Value2 = u'{} m × {} m'.format(
        _fmt(takeoff['perimeter']), _fmt(takeoff['height']))
    ws.Cells(row, col('updated_at')).Value2 = datetime.now().strftime(
        '%Y-%m-%d %H:%M')
    ws.Cells(AUDIT_SOURCE_ROW, col('item')).Value2 = u'室外周長來源'
    ws.Cells(AUDIT_SOURCE_ROW, col('quantity')).Value2 = takeoff['source']
    ws.Cells(AUDIT_SOURCE_ROW, col('formula')).Value2 = u'MCP：{}'.format(
        takeoff['command'])
    ws.Range(AUDIT_SUMMARY.rect(AUDIT_SUMMARY_COLUMNS[0],
                                AUDIT_SUMMARY_COLUMNS[-1],
                                AUDIT_SOURCE_ROW)).Interior.Color = _rgb(
        238, 242, 242)


def _link_general_other_area(ws, block, takeoff):
    start_row, end_row = block
    levels = _takeoff_levels(takeoff)
    audit_rows = _general_level_summary_rows(takeoff)
    for offset, row in enumerate(range(start_row, end_row + 1)):
        if offset >= len(levels):
            _clear_contents(ws, row, 4, row, 9)
            _clear_contents(ws, row, 16, row, 16)
            continue
        level = levels[offset]
        key = level['key']
        ws.Cells(row, 4).Value2 = level['display']
        ws.Cells(row, 5).Value2 = 1
        # The audit sheet already calculated perimeter * height. Do not rebuild
        # that result in the template's length/width/subtotal columns.
        _clear_contents(ws, row, 6, row, 8)
        ws.Cells(row, 9).Formula = u'={}!{}{}'.format(
            _quote_sheet(AUDIT_SHEET),
            _col_letter(LEVEL_SUMMARY_GENERAL_COL), audit_rows[key])
        ws.Range(ws.Cells(row, 5), ws.Cells(row, 9)).NumberFormat = u'0.000'
        if row != start_row:
            _clear_contents(ws, row, 16, row, 16)

    ws.Cells(start_row, 16).Formula = u'=' + _sheet_ref(
                                                        AUDIT_SHEET, AUDIT_SUMMARY.number('quantity'), SUMMARY_ROWS['general'])
    ws.Cells(start_row, 16).NumberFormat = u'0.00'


def _link_finish_other_area(ws, block, takeoff):
    start_row, end_row = block
    _clear_contents(ws, start_row, 4, end_row, 9)
    _clear_contents(ws, start_row, 16, end_row, 16)
    ws.Cells(start_row, 4).Value2 = u'ALL'
    ws.Cells(start_row, 5).Value2 = 1
    ws.Cells(start_row, 9).Formula = u'=' + _sheet_ref(
                                                       AUDIT_SHEET, AUDIT_SUMMARY.number('quantity'), SUMMARY_ROWS['interior_finish'])
    ws.Cells(start_row, 16).Formula = u'=' + _sheet_ref(
                                                        AUDIT_SHEET, AUDIT_SUMMARY.number('quantity'), SUMMARY_ROWS['interior_finish'])
    ws.Range(ws.Cells(start_row, 5), ws.Cells(start_row, 9)).NumberFormat = u'0.000'
    ws.Cells(start_row, 16).NumberFormat = u'0.00'


def _link_exterior_other_area(ws, block, takeoff):
    start_row, end_row = block
    _clear_contents(ws, start_row, 4, end_row, 9)
    _clear_contents(ws, start_row, 16, end_row, 16)
    ws.Cells(start_row, 4).Value2 = u'ALL'
    ws.Cells(start_row, 5).Value2 = 1
    ws.Cells(start_row, 9).Formula = u'=' + _sheet_ref(
                                                       AUDIT_SHEET, AUDIT_SUMMARY.number('quantity'), SUMMARY_ROWS['exterior'])
    ws.Cells(start_row, 16).Formula = u'=' + _sheet_ref(
                                                        AUDIT_SHEET, AUDIT_SUMMARY.number('quantity'), SUMMARY_ROWS['exterior'])
    ws.Range(ws.Cells(start_row, 5), ws.Cells(start_row, 9)).NumberFormat = u'0.000'
    ws.Cells(start_row, 16).NumberFormat = u'0.00'


def _link_other_area(rows, modes, takeoff):
    ws = rows['other']
    for mode in modes:
        block = rows['other_blocks'][mode]
        if mode == 'general':
            _link_general_other_area(ws, block, takeoff)
        elif mode == 'interior_finish':
            _link_finish_other_area(ws, block, takeoff)
        else:
            _link_exterior_other_area(ws, block, takeoff)


def _compact_formula(cell):
    return re.sub(r"[\s$']+", u'', _text(cell.Formula)).upper()


def _formula_equals(cell, expected):
    actual = _compact_formula(cell)
    wanted = re.sub(r"[\s$']+", u'', _text(expected)).upper()
    return actual == wanted


def _cell_has_formula(cell):
    """Use Excel's formula flag; Formula also returns constants for value cells."""
    try:
        return bool(cell.HasFormula)
    except Exception:
        return _text(cell.Formula).lstrip().startswith(u'=')


def _cell_has_excel_error(cell):
    values = (_text(cell.Formula).upper(), _text(cell.Text).upper())
    tokens = (u'#REF!', u'#VALUE!', u'#NAME?', u'#DIV/0!', u'#N/A')
    return any(token in value for value in values for token in tokens)


def _calculate_workbook(wb):
    """整本重算一次，然後把兩個高成本的旗標關回去。

    ForceFullCalculation 會停用 Excel 的相依樹最佳化，之後每一次重算都變成整本
    重建；再加上 Calculation 切成 AUTOMATIC，接在後面的驗證每讀一格就可能觸發
    一次全表重建（驗證要讀數百格）。重建完成後兩者都要復原，否則整支流程會慢
    上一個數量級。
    """
    try:
        wb.Application.Calculation = XL_CALCULATION_AUTOMATIC
    except Exception:
        pass
    try:
        wb.ForceFullCalculation = True
        wb.Application.CalculateFullRebuild()
    except Exception as error:
        raise Exception(u'Excel 公式重算失敗：{}'.format(error))
    finally:
        try:
            wb.ForceFullCalculation = False
        except Exception:
            pass
        try:
            wb.Application.Calculation = XL_CALCULATION_MANUAL
        except Exception:
            pass


# 逐房明細的 O 欄是 =ROUND(...,3)，摘要再對這些「已四捨五入」的值加總；Python
# 端的預期值卻是用未四捨五入的原始值相加。兩者本來就會差「每列最多 0.0005 ×
# 列數」。原本寫死 0.001，對 7718 這種量級等於要求 1.3e-7 的相對精度，78 個房
# 間就會誤判成公式鏈錯誤而拒絕存檔。單一格的固定值（例如數量恆為 1）不適用此
# 容差，仍用 SINGLE_CELL_TOLERANCE。
SINGLE_CELL_TOLERANCE = 0.001
PER_ROW_ROUNDING = 0.0005
MIN_TOTAL_TOLERANCE = 0.01


def _total_tolerance(takeoff):
    """加總類數值的容差：跟著逐列四捨五入的可能累積量走。"""
    row_count = len(takeoff.get('rows') or [])
    return max(MIN_TOTAL_TOLERANCE, row_count * PER_ROW_ROUNDING)


def _total_matches(actual, expected, tolerance):
    if actual is None:
        return False
    return abs(actual - expected) <= tolerance


def _validate_written_workbook(wb, rows, update_modes, takeoff):
    """Validate the exact scaffold chain before allowing the workbook save."""
    audit = _sheet_by_trim(wb, AUDIT_SHEET)
    subtotal = rows['subtotal']
    update = rows['update']
    other = rows['other']
    errors = []
    total_tol = _total_tolerance(takeoff)

    for mode in ('exterior', 'general', 'interior_finish'):
        sr = rows['subtotal_rows'][mode]
        ur = rows['update_rows'].get(mode)
        other_row = rows['other_rows'][mode]
        block_start, block_end = rows['other_blocks'][mode]
        expected_unit = ITEM_UNITS[mode]
        checks = [
            (_item_kind(subtotal.Cells(sr, SUBTOTAL_COLS['name']).Text) == mode,
             u'{} 工項名稱'.format(_addr(subtotal.Name, SUBTOTAL_COLS['name'], sr))),
            (_text(subtotal.Cells(sr, SUBTOTAL_COLS['unit']).Text).upper() == expected_unit,
             u'{} 單位'.format(_addr(subtotal.Name, SUBTOTAL_COLS['unit'], sr))),
            (_item_kind(other.Cells(other_row, OTHER_COLS['name']).Text) == mode,
             u'{} 工項名稱'.format(_addr(other.Name, OTHER_COLS['name'], other_row))),
            (_formula_equals(
                subtotal.Cells(sr, SUBTOTAL_COLS['rounded_qty']), _rounded_qty_formula(sr)) and
             _formula_equals(
                 subtotal.Cells(sr, SUBTOTAL_COLS['quantity']), u'=' + _sheet_ref(
                                                          other.Name, OTHER_COLS['total'], other_row)),
             u'{} → 其他面積'.format(_addr(subtotal.Name, SUBTOTAL_COLS['quantity'], sr))),
            (_formula_equals(other.Cells(other_row, OTHER_COLS['name']), u'=' + _sheet_ref(
                                                                          subtotal.Name, SUBTOTAL_COLS['name'], sr)),
             u'{} → 小計'.format(_addr(other.Name, OTHER_COLS['name'], other_row))),
        ]
        if update is not None and ur:
            checks.extend([
                (_item_kind(update.Cells(ur, UPDATE_COLS['name']).Text) == mode,
                 u'{} 工項名稱'.format(_addr(update.Name, UPDATE_COLS['name'], ur))),
                (_text(update.Cells(ur, UPDATE_COLS['unit']).Text).upper() == expected_unit,
                 u'{} 單位'.format(_addr(update.Name, UPDATE_COLS['unit'], ur))),
                (_formula_equals(update.Cells(ur, UPDATE_COLS['name']), u'=' + _sheet_ref(
                                                                        subtotal.Name, SUBTOTAL_COLS['name'], sr)) and
                 _formula_equals(update.Cells(ur, UPDATE_COLS['unit']), u'=' + _sheet_ref(
                                                                        subtotal.Name, SUBTOTAL_COLS['unit'], sr)) and
                 _formula_equals(update.Cells(ur, UPDATE_COLS['rounded_qty']), u'=' + _sheet_ref(
                                                                        subtotal.Name, SUBTOTAL_COLS['rounded_qty'], sr)) and
                 _formula_equals(update.Cells(ur, UPDATE_COLS['source']), u'=' + _sheet_ref(
                                                                        subtotal.Name, SUBTOTAL_COLS['source'], sr)) and
                 _formula_equals(update.Cells(ur, UPDATE_COLS['quantity']), u'=' + _sheet_ref(
                                                                        subtotal.Name, SUBTOTAL_COLS['quantity'], sr)),
                 u'{}:{}{} → 小計'.format(_addr(update.Name, UPDATE_COLS['name'], ur), _col_letter(UPDATE_COLS['quantity']), ur)),
            ])
        if mode in update_modes:
            summary_row = SUMMARY_ROWS[mode]
            if mode == 'general':
                expected_total = _number(
                    takeoff.get('totals', {}).get('general')) or 0.0
            elif mode == 'interior_finish':
                expected_total = _number(
                    takeoff.get('totals', {}).get('interior_finish')) or 0.0
            else:
                expected_total = _number(takeoff.get('quantity')) or 0.0
            audit_summary_value = _number(audit.Cells(summary_row, 2).Value2)
            checks.extend([
                (_formula_equals(
                    other.Cells(other_row, OTHER_COLS['total']), u'=' + _sheet_ref(
                                                                  AUDIT_SHEET, AUDIT_SUMMARY.number('quantity'), summary_row)),
                 u'{} 公式 → 施工架計算摘要'.format(_addr(other.Name, OTHER_COLS['total'], other_row))),
                (_total_matches(
                    _number(other.Cells(other_row, OTHER_COLS['total']).Value2) or 0.0,
                    expected_total, total_tol),
                 u'{} 數值應為 {}，實際為 {}'.format(_addr(other.Name, OTHER_COLS['total'], other_row), _fmt(expected_total),
                     _fmt(other.Cells(other_row, OTHER_COLS['total']).Value2))),
                (_total_matches(audit_summary_value, expected_total, total_tol),
                 u'{} 摘要數量應為 {}，實際為 {}'.format(
                     _addr(AUDIT_SHEET,
                           AUDIT_SUMMARY.number('quantity'), summary_row),
                     _fmt(expected_total), _fmt(audit_summary_value))),
            ])
            if mode in SUMMARY_CATEGORIES:
                audit_rows = takeoff.get('rows') or []
                if audit_rows:
                    summary_formula = _audit_summary_formula(
                        SUMMARY_CATEGORIES[mode],
                        ROOM_AUDIT_HEADER_ROW + len(audit_rows))
                else:
                    summary_formula = u'=0'
                checks.append((
                    _formula_equals(
                        audit.Cells(summary_row,
                                    AUDIT_SUMMARY.number('quantity')),
                        summary_formula),
                    u'{} 摘要公式 → 逐房明細 {} 欄'.format(
                        _addr(AUDIT_SHEET,
                              AUDIT_SUMMARY.number('quantity'), summary_row),
                        ROOM_AUDIT.col('quantity'))))
            if mode == 'general':
                expected_levels = _takeoff_levels(takeoff)
                expected_totals = _general_level_totals(takeoff)
                audit_level_rows = _general_level_summary_rows(takeoff)
                for offset, row in enumerate(range(block_start, block_end + 1)):
                    if offset >= len(expected_levels):
                        checks.append((
                            all(not _text(other.Cells(row, col).Text) and
                                not _text(other.Cells(row, col).Formula)
                                for col in range(4, 10)),
                            u'{}:{}{} 多餘樓層列應清空'.format(_addr(other.Name, OTHER_COLS['level'], row), _col_letter(OTHER_COLS['subtotal']), row)))
                        continue
                    expected_level = expected_levels[offset]
                    level_key = expected_level['key']
                    level_totals = expected_totals[level_key]
                    audit_level_row = audit_level_rows[level_key]
                    checks.extend([
                        (_text(other.Cells(row, 4).Text) == expected_level['display'],
                         u'{} Revit 樓層名稱'.format(_addr(other.Name, OTHER_COLS['level'], row))),
                        (abs((_number(other.Cells(row, 5).Value2) or 0.0) - 1.0)
                         <= SINGLE_CELL_TOLERANCE,
                         u'{} 數量固定為 1'.format(_addr(other.Name, OTHER_COLS['count'], row))),
                        (all(not _text(other.Cells(row, col).Text) and
                             not _text(other.Cells(row, col).Formula)
                             for col in range(6, 9)),
                         u'{}:{}{} 不得二次計算'.format(_addr(other.Name, OTHER_COLS['length'], row), _col_letter(OTHER_COLS['height']), row)),
                        (_formula_equals(
                             other.Cells(row, 9),
                             u'={}!{}{}'.format(
                                 _quote_sheet(AUDIT_SHEET),
                                 _col_letter(LEVEL_SUMMARY_GENERAL_COL),
                                 audit_level_row)),
                         u'{} 公式 → 施工架計算樓層小計'.format(_addr(other.Name, OTHER_COLS['subtotal'], row))),
                        (_total_matches(
                             _number(other.Cells(row, 9).Value2) or 0.0,
                             level_totals['quantity'], total_tol),
                         u'{} 數值應為 {}，實際為 {}'.format(_addr(other.Name, OTHER_COLS['subtotal'], row), _fmt(level_totals['quantity']),
                             _fmt(other.Cells(row, 9).Value2))),
                    ])
            else:
                if mode == 'exterior':
                    expected_quantity = _number(takeoff.get('quantity')) or 0.0
                else:
                    expected_quantity = _number(
                        takeoff.get('totals', {}).get('interior_finish')) or 0.0
                checks.extend([
                    (_text(other.Cells(other_row, 4).Text) == u'ALL',
                     u'{} 位置'.format(_addr(other.Name, OTHER_COLS['level'], other_row))),
                    (abs((_number(other.Cells(other_row, 5).Value2) or 0.0) - 1.0)
                     <= SINGLE_CELL_TOLERANCE,
                     u'{} 數量固定為 1'.format(_addr(other.Name, OTHER_COLS['count'], other_row))),
                    (all(not _text(other.Cells(other_row, col).Text) and
                         not _text(other.Cells(other_row, col).Formula)
                         for col in range(6, 9)),
                     u'{}:{}{} 不得二次計算'.format(_addr(other.Name, OTHER_COLS['length'], other_row), _col_letter(OTHER_COLS['height']), other_row)),
                    # 公式與數值分開報，訊息才看得出是連錯格還是數字對不上
                    (_formula_equals(
                        other.Cells(other_row, 9), u'=' + _sheet_ref(
                                                                     AUDIT_SHEET, AUDIT_SUMMARY.number('quantity'), summary_row)),
                     u'{} 公式 → 施工架計算摘要'.format(_addr(other.Name, OTHER_COLS['subtotal'], other_row))),
                    (_total_matches(
                        _number(other.Cells(other_row, 9).Value2) or 0.0,
                        expected_quantity, total_tol),
                     u'{} 數值應為 {}，實際為 {}'.format(_addr(other.Name, OTHER_COLS['subtotal'], other_row), _fmt(expected_quantity),
                         _fmt(other.Cells(other_row, 9).Value2))),
                ])
        for passed, label in checks:
            if not passed:
                errors.append(u'缺少或錯位：{}'.format(label))

        scan_cells = []
        if mode in update_modes:
            scan_cells.extend((subtotal, sr, col) for col in range(2, 9))
            if update is not None and ur:
                scan_cells.extend((update, ur, col) for col in range(1, 7))
            for row in range(block_start, block_end + 1):
                for col in (2, 3, 4, 5, 6, 7, 8, 9, 16):
                    scan_cells.append((other, row, col))
        for ws, row, col in scan_cells:
            if _cell_has_excel_error(ws.Cells(row, col)):
                errors.append(u'公式錯誤：{}!{}{}'.format(
                    ws.Name, _col_letter(col), row))

        if mode in update_modes:
            audit_total = _number(audit.Cells(SUMMARY_ROWS[mode], 2).Value2)
            linked_total = _number(other.Cells(other_row, OTHER_COLS['total']).Value2)
            if audit_total is None or linked_total is None:
                errors.append(u'數量無法讀取：{}／{}'.format(
                    ITEM_NAMES[mode], other.Name))
            elif abs(audit_total - linked_total) > 0.02:
                errors.append(
                    u'數量不一致：{} 稽核 {}，{} {}'.format(
                        ITEM_NAMES[mode], _fmt(audit_total), other.Name,
                        _fmt(linked_total)))

    audit_used = audit.UsedRange
    audit_last_row = audit_used.Row + audit_used.Rows.Count - 1
    for row in range(1, min(audit_last_row, 1000) + 1):
        for col in range(1, 20):
            cell = audit.Cells(row, col)
            if _cell_has_excel_error(cell):
                errors.append(u'公式錯誤：{}!{}{}'.format(
                    audit.Name, _col_letter(col), row))

    if errors:
        unique = []
        for error in errors:
            if error not in unique:
                unique.append(error)
        raise Exception(
            u'Excel 公式鏈驗證失敗，原檔未寫入：\n'
            u'版本：{}\n{}'.format(
                SCRIPT_VERSION, u'\n'.join(unique[:20])))


def _format_old(value):
    return u'尚未建立' if value is None else _fmt(value)


def _print_room_preview(path, takeoff, old_totals):
    out = script.get_output()
    out.print_md(u'## 施工架 Excel dry-run')
    out.print_md(u'- 活頁簿：`{}`'.format(path))
    out.print_md(u'- {}：{} → **{} M2**'.format(
        ITEM_NAMES['general'], _format_old(old_totals.get('general')),
        _fmt(takeoff['totals']['general'])))
    out.print_md(u'- {}：{} → **{} M3**'.format(
        ITEM_NAMES['interior_finish'], _format_old(old_totals.get('interior_finish')),
        _fmt(takeoff['totals']['interior_finish'])))
    out.print_md(u'| 房間 | 名稱 | 分類 | 計算式 | 數量 | 計入 |')
    out.print_md(u'|---|---|---|---|---:|---|')
    for item in takeoff['rows']:
        if item['category'] == 'general_scaffold':
            expression = u'{} × {}'.format(
                _fmt(item['perimeter'] or 0), _fmt(item['height'] or 0))
        elif item['category'] == 'interior_finish_scaffold':
            expression = u'{} × {} × {}'.format(
                _fmt(item['length'] or 0), _fmt(item['width'] or 0),
                _fmt(item['height'] or 0))
        else:
            expression = item['rule']
        out.print_md(u'| {} | {} | {} | {} | {} {} | {} |'.format(
            item['number'], item['name'], item['category_name'], expression,
            _fmt(item['quantity']), item['unit'], u'是' if item['included'] else u'否'))


def _room_confirm_text(takeoff, old_totals):
    counts = takeoff['counts']
    space_sheet_name = _text(takeoff.get('space_sheet')) or SPACE_SHEET
    return (
        u'【dry-run 驗證】\n\n'
        u'{general}\n{old_general} → {new_general} M2\n\n'
        u'{finish}\n{old_finish} → {new_finish} M3\n\n'
        u'計入：一般 {general_count} 間、樓梯/電梯 {finish_count} 間\n'
        u'排除 {excluded} 間；{space_sheet} 無 Revit 對應 {missing} 間\n'
        u'高度：實體天花 {ceiling} 間、上層樓板底 {slab} 間、備援 {fallback} 間、缺高度 {no_height} 間\n'
        u'Revit 有但 {space_sheet} 未列 {revit_only} 間（不計入）\n\n'
        u'確定要備份並更新 Excel 嗎？'
    ).format(
        general=ITEM_NAMES['general'],
        old_general=_format_old(old_totals.get('general')),
        new_general=_fmt(takeoff['totals']['general']),
        finish=ITEM_NAMES['interior_finish'],
        old_finish=_format_old(old_totals.get('interior_finish')),
        new_finish=_fmt(takeoff['totals']['interior_finish']),
        general_count=counts['general'], finish_count=counts['interior_finish'],
        excluded=counts['excluded'], missing=counts['missing_revit'],
        ceiling=counts['ceiling_height'], slab=counts['slab_height'],
        fallback=counts['fallback_height'],
        no_height=counts['missing_height'], revit_only=counts['revit_only'],
        space_sheet=space_sheet_name,
    )


def _exterior_confirm_text(takeoff, old_totals):
    return (
        u'【dry-run 驗證】\n\n{item}\n'
        u'周長：{perimeter} m\n高度：{height} m\n'
        u'面積：{old} → {quantity} M2\n'
        u'來源：{source}\n\n確定要備份並更新 Excel 嗎？'
    ).format(
        item=ITEM_NAMES['exterior'], perimeter=_fmt(takeoff['perimeter']),
        height=_fmt(takeoff['height']), old=_format_old(old_totals.get('exterior')),
        quantity=_fmt(takeoff['quantity']), source=takeoff['source'])


def _backup_path(path):
    stem, ext = os.path.splitext(path)
    return u'{}_backup_{}{}'.format(
        stem, datetime.now().strftime('%Y%m%d-%H%M%S'), ext)


def _space_entries_from_records(data):
    entries = []
    for offset, room in enumerate(data.get('Rooms') or []):
        entries.append({
            'row': offset + 2,
            'number': _norm_number(room.get('Number')),
            'name': _text(room.get('Name')),
            'level': _text(room.get('Level')),
            'composite_id': _text(room.get('CompositeId')),
            'perimeter': _positive(room.get('PerimeterM')),
            'area': _positive(room.get('AreaM2')),
            'perimeter_col': 9,
        })
    return entries


def _scaffold_standalone_tables(takeoff):
    detail_headers = list(STANDALONE_DETAIL_HEADERS)
    detail_rows = []
    audit_rows = []
    for offset, item in enumerate(takeoff.get('rows') or []):
        excel_row = STANDALONE_DETAIL.first_data_row + offset
        included = u'是' if item.get('included') else u'否'
        # 這兩條公式以前把 N/I/J/K/L 寫死，跟下面 detail_rows 的排列是兩套真相。
        if item.get('category') == 'general_scaffold':
            quantity = STANDALONE_DETAIL.formula(
                excel_row,
                u'IF({included}="是",ROUND({perimeter}*{height},3),0)')
        elif item.get('category') == 'interior_finish_scaffold':
            quantity = STANDALONE_DETAIL.formula(
                excel_row,
                u'IF({included}="是",'
                u'ROUND({length}*{width}*{height},3),0)')
        else:
            quantity = 0
        warning = u'；'.join(item.get('audit_warnings') or [])
        detail_rows.append([
            item.get('source_key'), item.get('source_label'),
            item.get('revit_id'), item.get('local_element_id'),
            item.get('level'), item.get('number'), item.get('name'),
            item.get('category'), item.get('perimeter'),
            item.get('length'), item.get('width'), item.get('height'),
            item.get('height_source'), included, quantity,
            item.get('unit'), item.get('rule'),
            item.get('dimension_source'), warning,
        ])
        audit_rows.append([
            (u'PASS' if item.get('included') and not warning else
             (u'WARN' if warning else u'EXCLUDE')),
            item.get('source_key'), item.get('revit_id'),
            item.get('number'), item.get('category'), warning,
        ])
    formula_headers = [u'項目', u'公式／依據', u'數值', u'單位']
    formula_rows = [
        [
            ITEM_NAMES['general'],
            u'房間 Finish 周長 × 淨高',
            u'=ROUND(SUMIFS(\'數量明細\'!O:O,\'數量明細\'!H:H,'
            u'"general_scaffold",\'數量明細\'!N:N,"是"),3)',
            u'M2',
        ],
        [
            ITEM_NAMES['interior_finish'],
            u'房間長 × 寬 × 淨高',
            u'=ROUND(SUMIFS(\'數量明細\'!O:O,\'數量明細\'!H:H,'
            u'"interior_finish_scaffold",\'數量明細\'!N:N,"是"),3)',
            u'M3',
        ],
    ]
    return {
        'detail_headers': detail_headers,
        'detail_rows': detail_rows,
        'formula_headers': formula_headers,
        'formula_rows': formula_rows,
        'audit_headers': [
            u'狀態', u'來源Key', u'複合識別', u'房號', u'分類', u'訊息'],
        'audit_rows': audit_rows,
    }


def _write_scaffold_standalone(takeoff):
    title = _text(getattr(revit.doc, 'Title', u'室內施工架'))
    title = re.sub(r'[\\/:*?"<>|]+', u'_', title) or u'室內施工架'
    path = forms.save_file(
        file_ext='xlsx',
        default_name=title + u'_室內施工架.xlsx',
        title=u'匯出室內施工架 Excel',
    )
    if not path:
        return None
    if not path.lower().endswith('.xlsx'):
        path += '.xlsx'
    import takeoff_standalone
    payload = _scaffold_standalone_tables(takeoff)
    takeoff_standalone.write_standard_workbook(
        path,
        payload['detail_rows'], payload['detail_headers'],
        payload['formula_rows'], payload['formula_headers'],
        payload['audit_rows'], payload['audit_headers'],
        u'室內施工架 Excel',
    )
    return path


def run(mode, excel_path=None, space_sheet_name=None, existing_backup=None,
        options=None):
    if mode not in ('exterior', 'general', 'interior_finish'):
        forms.alert(u'未知施工架模式：{}'.format(mode), title=u'施工架 Excel')
        return
    title = ITEM_NAMES[mode] + u' Excel'
    excel = wb = None
    try:
        if mode == 'exterior':
            source_data = _collect_exterior_takeoff()
        else:
            source_data = _collect_room_takeoff(options)
        if source_data is None:
            return

        path = excel_path
        if path is None and options is not None:
            path = options.get('workbook_path')
        if path is None and options is None:
            path = forms.pick_file(
                files_filter='Excel (*.xls;*.xlsx)|*.xls;*.xlsx')

        if mode != 'exterior' and not path and options is not None:
            takeoff = _build_room_rows(
                _space_entries_from_records(source_data),
                source_data.get('_height_evidence') or {},
                source_data,
                u'數量明細')
            standalone_path = _write_scaffold_standalone(takeoff)
            if standalone_path:
                forms.alert(
                    u'室內施工架 Excel 已匯出：\n\n{}'.format(
                        standalone_path),
                    title=title)
            return
        if not path:
            return

        try:
            excel, wb = _excel_open(path, True)
            _validate_template(
                wb, mode != 'exterior', space_sheet_name=space_sheet_name)
            old_totals = _read_old_totals(wb)
            if mode != 'exterior':
                space_ws = _sheet_by_trim(
                    wb, space_sheet_name or SPACE_SHEET)
                space_entries = _read_space_table(space_ws)
                takeoff = _build_room_rows(
                    space_entries,
                    source_data.get('_height_evidence') or {},
                    source_data,
                    space_ws.Name)
            else:
                takeoff = source_data
        finally:
            _excel_close(excel, wb, False)
            excel = wb = None

        if mode == 'exterior':
            confirmed = forms.alert(
                _exterior_confirm_text(takeoff, old_totals),
                title=title, yes=True, no=True)
        else:
            _print_room_preview(path, takeoff, old_totals)
            confirmed = forms.alert(
                _room_confirm_text(takeoff, old_totals),
                title=title, yes=True, no=True)
        if not confirmed:
            return

        backup = existing_backup or _backup_path(path)
        if not existing_backup:
            shutil.copy2(path, backup)

        try:
            excel, wb = _excel_open(path, False)
            if wb.ReadOnly:
                raise Exception(u'Excel 檔目前是唯讀，請先關閉該活頁簿後再執行。')
            audit = _ensure_audit_sheet(wb)
            if mode == 'exterior':
                _write_exterior_audit(audit, takeoff)
                update_modes = ['exterior']
            else:
                _write_room_audit(audit, takeoff)
                update_modes = ['general', 'interior_finish']
            item_rows = _ensure_item_rows(wb, excel, takeoff)
            if item_rows['created_finish'] and 'interior_finish' not in update_modes:
                if audit.Cells(SUMMARY_ROWS['interior_finish'], 2).Value2 is None:
                    audit.Cells(SUMMARY_ROWS['interior_finish'], 2).Value2 = 0
                update_modes.append('interior_finish')
            _link_other_area(item_rows, update_modes, takeoff)
            _calculate_workbook(wb)
            _validate_written_workbook(wb, item_rows, update_modes, takeoff)
            _excel_close(excel, wb, True)
            excel = wb = None
        finally:
            if excel is not None:
                _excel_close(excel, wb, False)

        if mode == 'exterior':
            summary = u'{}：{} M2'.format(ITEM_NAMES['exterior'], _fmt(takeoff['quantity']))
        else:
            summary = u'{}：{} M2\n{}：{} M3'.format(
                ITEM_NAMES['general'], _fmt(takeoff['totals']['general']),
                ITEM_NAMES['interior_finish'], _fmt(takeoff['totals']['interior_finish']))
        forms.alert(
            u'Excel 更新完成。\n\n{}\n\n已建立／更新「施工架計算」稽核分頁。\n備份：{}'.format(
                summary, os.path.basename(backup)),
            title=title,
        )
    except mcp.MCPBridgeError as error:
        mcp.show_error(error, title)
    except Exception as error:
        forms.alert(u'執行失敗：\n\n{}'.format(error), title=title)
