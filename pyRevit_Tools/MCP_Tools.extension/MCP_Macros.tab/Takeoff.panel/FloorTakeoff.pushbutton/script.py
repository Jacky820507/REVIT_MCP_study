# -*- coding: utf-8 -*-
from __future__ import unicode_literals

__title__ = u'地坪\nExcel'
__author__ = 'Codex'

import os
import re

import clr

clr.AddReference('System.IO.Compression')
clr.AddReference('System.IO.Compression.FileSystem')

from Autodesk.Revit.DB import (  # noqa: E402
    BuiltInCategory,
    BuiltInParameter,
    Element,
    FamilySymbol,
    FilteredElementCollector,
    SpatialElement,
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


FT_TO_M = 0.3048
SQFT_TO_SQM = FT_TO_M * FT_TO_M
FIXED_REPORT_COLS = 3
TRAILING_REPORT_COLS = 2
FIRST_DATA_ROW = 9
SUMMARY_LABEL = u'地坪數量總計'
SCRIPT_VERSION = u'2026-07-23-floor-layered-finish-v3'


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
        if not param or not param.HasValue:
            continue
        try:
            value = clean(param.AsString() or param.AsValueString())
        except Exception:
            value = ''
        if value:
            return value
    return ''


def param_text(element, bip_names=None, lookup_names=None):
    for bip_name in bip_names or []:
        param = get_bip_param(element, bip_name)
        if param and param.HasValue:
            try:
                value = clean(param.AsString() or param.AsValueString())
            except Exception:
                value = ''
            if value:
                return value
    return lookup_value(element, lookup_names or [])


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
    return param_text(
        element,
        ['SYMBOL_NAME_PARAM', 'ALL_MODEL_TYPE_NAME', 'ROOM_NAME', 'DATUM_TEXT'],
        [u'名稱', 'Name']
    )


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
        if value and value not in values:
            values.append(value)
    return values


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
        return False


def room_number(room):
    value = param_text(room, ['ROOM_NUMBER'], [u'編號', 'Number'])
    return clean(value).upper()


def room_name(room, number):
    value = param_text(room, ['ROOM_NAME'], [u'名稱', 'Name']) or element_name(room)
    if number:
        value = re.sub(r'\s*{0}\s*$'.format(re.escape(number)), '', value, flags=re.I).strip()
    return value


def level_name(room):
    try:
        level_id = room.LevelId
        if element_id_value(level_id) > 0:
            level = doc.GetElement(level_id)
            if level:
                return element_name(level)
    except Exception:
        pass
    return lookup_value(room, [u'樓層', 'Level'])


def detect_building_prefixes(values):
    prefixes = set()
    for value in values or []:
        text = clean(value).upper()
        text = text.replace(u'樓層', '').replace(u'樓', '')
        text = re.sub(r'[\s_]+', '', text)
        match = re.match(r'^([A-Z]+)-(B\d+F?|R\d+F?|RF)$', text)
        if match:
            prefixes.add(match.group(1))
    return prefixes


def normalize_level(value, building_prefixes=None):
    building_prefixes = building_prefixes or set()
    text = clean(value).upper()
    text = text.replace(u'樓層', '').replace(u'樓', '')
    text = re.sub(r'[\s_]+', '', text)
    prefix_match = re.match(r'^([A-Z]+)-(.+)$', text)
    if prefix_match and prefix_match.group(1) in building_prefixes:
        text = prefix_match.group(2)
    text = re.sub(r'^B-0*(\d+)F?$', r'B\1F', text)
    text = re.sub(r'^R-0*(\d+)F?$', r'R\1F', text)
    text = re.sub(r'^B0*(\d+)F?$', r'B\1F', text)
    text = re.sub(r'^R0*(\d+)F?$', r'R\1F', text)
    text = re.sub(r'^0*(\d+)F?$', r'\1F', text)
    return text


def floor_sort_key(value, building_prefixes=None):
    text = normalize_level(value, building_prefixes)
    if text in ('FN', 'BS'):
        return (0, -9999, text)
    match = re.match(r'^B(\d+)F$', text)
    if match:
        return (0, -int(match.group(1)), text)
    match = re.match(r'^(\d+)F$', text)
    if match:
        return (1, int(match.group(1)), text)
    match = re.match(r'^R(\d+)F$', text)
    if match:
        return (2, int(match.group(1)), text)
    if text == 'RF':
        return (2, 9999, text)
    return (3, 0, text)


def natural_key(value):
    parts = []
    for part in re.split(r'(\d+)', clean(value).upper()):
        parts.append(int(part) if part.isdigit() else part)
    return parts


def room_sort_key(room, building_prefixes=None):
    return (
        floor_sort_key(room.get('level'), building_prefixes),
        clean(room.get('level')).upper(),
        room_takeoff_sources_logic.room_number_sort_key(
            room.get('number')),
        natural_key(room.get('name')),
        room.get('element_id', 0),
    )


def room_floor_finish(room):
    value = lookup_value(room, [
        u'樓板塗層',
        u'地坪塗層',
        u'地坪',
        'Floor Finish',
        'FloorFinish',
    ])
    if clean(value).upper() in ('', '-', u'無', 'NA', 'N/A', 'NONE'):
        return ''
    return value


def floor_finish_codes(value):
    result = []
    for match in re.finditer(
            r'(?<![A-Z0-9])(F\s*0*\d+[A-Z]?)(?![A-Z0-9])',
            clean(value).upper()):
        code = re.sub(r'\s+', '', match.group(1)).upper()
        if code not in result:
            result.append(code)
    return result


def finish_sort_key(value):
    text = clean(value).upper()
    match = re.match(r'^F0*(\d+)([A-Z]*)$', text)
    if match:
        return (0, int(match.group(1)), match.group(2) or '', text)
    return (1, natural_key(text))


def is_generic_model_symbol(symbol):
    try:
        category = symbol.Category
        return category and element_id_value(category.Id) == int(BuiltInCategory.OST_GenericModel)
    except Exception:
        return False


def collect_generic_model_families():
    result = {}
    collector = FilteredElementCollector(doc).OfClass(FamilySymbol)
    for symbol in collector:
        if not is_generic_model_symbol(symbol):
            continue
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
        families = collect_generic_model_families()
    if not families:
        forms.alert(
            u'目前專案找不到「一般模型」品類的族群類型。',
            title=u'地坪 Excel'
        )
        return (None, {})
    selected = forms.SelectFromList.show(
        sorted(families.keys(), key=family_choice_sort_key),
        title=u'選擇一般模型材料版族群',
        button_name=u'讀取地坪材料',
        multiselect=False
    )
    return (selected, families)


def clean_material_name_from_text(text, code):
    value = clean(text)
    code_text = clean(code)
    if not value or not code_text:
        return ''
    match = re.search(
        r'(^|[\s_/\\\-\(\[（【]){0}\s*[=＝:：\-]\s*(.+)$'.format(
            re.escape(code_text)
        ),
        value,
        re.I
    )
    if match:
        return clean(match.group(2))
    match = re.match(r'^\s*{0}\s+(.+)$'.format(re.escape(code_text)), value, re.I)
    if match:
        return clean(match.group(1).lstrip('=＝:：- '))
    return ''


def symbol_code_match(symbol, code):
    code_text = clean(code).upper()
    candidates = [
        element_name(symbol),
        param_text(symbol, ['ALL_MODEL_TYPE_MARK'], [u'類型標記', 'Type Mark']),
    ] + parameter_text_values(symbol)
    for candidate in candidates:
        if code_text in floor_finish_codes(candidate):
            return True
    return False


def material_name_from_symbol(symbol, code):
    candidates = [element_name(symbol)] + parameter_text_values(symbol)
    for value in candidates:
        name = clean_material_name_from_text(value, code)
        if name:
            return name
    if symbol_code_match(symbol, code):
        for parameter_name in (
                u'描述', 'Description', u'類型備註', 'Type Comments', u'模型', 'Model'):
            value = lookup_value(symbol, [parameter_name])
            if value and value.upper() != clean(code).upper():
                return value
        return element_name(symbol)
    return ''


def load_material_definitions(family_name, families):
    result = {}
    for symbol in families.get(family_name, []):
        texts = [
            element_name(symbol),
            param_text(symbol, ['ALL_MODEL_TYPE_MARK'], [u'類型標記', 'Type Mark']),
        ] + parameter_text_values(symbol)
        codes = []
        for text in texts:
            for code in floor_finish_codes(text):
                if code not in codes:
                    codes.append(code)
        for code in codes:
            name = material_name_from_symbol(symbol, code)
            if code not in result or (name and not result[code]):
                result[code] = name
    return result


def append_unique(values, value):
    text = clean(value)
    if text and text not in values:
        values.append(text)


def collect_rooms(material_definitions):
    rooms = []
    used_codes = set()
    stats = {
        'rooms': 0,
        'rooms_with_code': 0,
        'rooms_without_code': 0,
        'base_rooms': [],
        'missing_material_codes': set(),
    }
    collector = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_Rooms)
        .WhereElementIsNotElementType()
    )
    for element in collector:
        if not valid_room(element):
            continue
        if not room_is_in_active_level_scope(element):
            continue
        number = room_number(element)
        name = room_name(element, number)
        if not number and not name:
            continue
        try:
            area = element.Area * SQFT_TO_SQM
        except Exception:
            area = None
        finish = room_floor_finish(element)
        codes = floor_finish_codes(finish)
        warnings = []
        base_codes = []
        regular_codes = []
        unresolved_codes = []
        for code in codes:
            used_codes.add(code)
            material_name = material_definitions.get(code, '')
            if not material_name:
                stats['missing_material_codes'].add(code)
                append_unique(warnings, u'材料版找不到 {0} 的材料名稱'.format(code))
                unresolved_codes.append(code)
            elif u'基座' in material_name:
                base_codes.append(code)
            else:
                regular_codes.append(code)
        if base_codes:
            stats['base_rooms'].append(number or name)
            append_unique(warnings, u'此房間有基座需自行手動計算填入數值')
        if codes:
            stats['rooms_with_code'] += 1
        else:
            stats['rooms_without_code'] += 1
        rooms.append({
            'element_id': element_id_value(element.Id),
            'number': number,
            'name': name,
            'level': level_name(element),
            'area': area,
            'floor_finish': finish,
            'codes': codes,
            'base_codes': base_codes,
            'regular_codes': regular_codes,
            'unresolved_codes': unresolved_codes,
            'warnings': warnings,
        })
    building_prefixes = detect_building_prefixes([
        room.get('level') for room in rooms
    ])
    rooms.sort(key=lambda item: room_sort_key(item, building_prefixes))
    stats['rooms'] = len(rooms)
    stats['missing_material_codes'] = sorted(
        list(stats['missing_material_codes']),
        key=finish_sort_key
    )
    return rooms, sorted(list(used_codes), key=finish_sort_key), stats


def excel_col(index):
    result = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def round2(value):
    return round(value + 1e-9, 2)


def make_rows(rooms, material_cols):
    total_cols = FIXED_REPORT_COLS + len(material_cols) + TRAILING_REPORT_COLS
    drawing_col = total_cols - 2
    notes_col = total_cols - 1
    material_index = dict((code, index) for index, code in enumerate(material_cols))
    rows = []
    for offset, room in enumerate(rooms):
        row_number = FIRST_DATA_ROW + offset
        row = [''] * total_cols
        row[0] = room['number']
        row[1] = room['name']
        row[2] = round2(room['area']) if room.get('area') is not None else ''
        for code in room.get('regular_codes') or []:
            index = material_index.get(code)
            if index is not None:
                row[FIXED_REPORT_COLS + index] = '=C{0}'.format(row_number)
        row[drawing_col] = room.get('source_label') or ''
        row[notes_col] = u'；'.join(room.get('warnings') or [])
        rows.append(row)
    return rows


def build_summary_row(data_row_count, material_cols):
    row = [''] * (FIXED_REPORT_COLS + len(material_cols) + TRAILING_REPORT_COLS)
    row[0] = SUMMARY_LABEL
    last_data_row = FIRST_DATA_ROW + data_row_count - 1
    for index, _code in enumerate(material_cols):
        col_name = excel_col(FIXED_REPORT_COLS + index + 1)
        row[FIXED_REPORT_COLS + index] = (
            '=SUM({0}{1}:{0}{2})'.format(
                col_name,
                FIRST_DATA_ROW,
                last_data_row
            ) if data_row_count else '=0'
        )
    return row


def build_sheet_values(rows, material_cols, project_title, material_definitions):
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
    row[0] = u'地坪數量計算表'
    values.append(row)

    row = [''] * total_cols
    row[0] = u'工程項目'
    if material_cols:
        row[FIXED_REPORT_COLS] = u'地坪'
    row[drawing_col] = u'對應\n圖說'
    row[notes_col] = u'備註'
    values.append(row)

    row = [''] * total_cols
    row[0] = u'材料編號'
    for index, code in enumerate(material_cols):
        row[FIXED_REPORT_COLS + index] = code
    values.append(row)

    row = [''] * total_cols
    row[0] = u'材料名稱'
    for index, code in enumerate(material_cols):
        row[FIXED_REPORT_COLS + index] = material_definitions.get(code, '')
    values.append(row)

    values.append([''] * total_cols)

    row = [''] * total_cols
    row[0] = u'編號'
    row[1] = u'空間名稱'
    row[2] = u'面積'
    values.append(row)

    values.extend(rows)
    values.append(build_summary_row(len(rows), material_cols))
    return values


def build_audit_values(rooms, material_definitions):
    values = [[
        u'Room Id',
        u'房間編號',
        u'房間名稱',
        u'樓層',
        u'Room 面積(m²)',
        u'樓板塗層原值',
        u'F 代碼',
        u'材料名稱',
        u'自動填入代碼',
        u'基座代碼',
        u'未辨識材料代碼',
        u'備註',
    ]]
    for room in rooms:
        names = []
        for code in room.get('codes') or []:
            names.append(u'{0}={1}'.format(code, material_definitions.get(code, '')))
        auto_codes = room.get('regular_codes') or []
        values.append([
            room['element_id'],
            room['number'],
            room['name'],
            room['level'],
            round2(room['area']) if room.get('area') is not None else '',
            room.get('floor_finish') or '',
            '+'.join(room.get('codes') or []),
            u'；'.join(names),
            '+'.join(auto_codes),
            '+'.join(room.get('base_codes') or []),
            '+'.join(room.get('unresolved_codes') or []),
            u'；'.join(room.get('warnings') or []),
        ])
    return values


def xml_escape(value):
    return (
        clean(value)
        .replace('&', '&amp;')
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


def cell_xml(row_index, col_index, value, style=''):
    ref = '{0}{1}'.format(excel_col(col_index), row_index)
    text = clean(value)
    style_attr = ' s="{0}"'.format(style) if style != '' else ''
    if value is None or value == '':
        return '<c r="{0}"{1}/>'.format(ref, style_attr)
    if text.startswith('='):
        return '<c r="{0}"{1}><f>{2}</f></c>'.format(
            ref, style_attr, xml_escape(text[1:])
        )
    if is_number(value):
        return '<c r="{0}"{1}><v>{2}</v></c>'.format(
            ref, style_attr, clean(value)
        )
    return '<c r="{0}"{1} t="inlineStr"><is><t>{2}</t></is></c>'.format(
        ref, style_attr, xml_escape(text)
    )


def main_sheet_xml(values):
    total_cols = len(values[0]) if values else 1
    material_end = total_cols - TRAILING_REPORT_COLS
    drawing_col = total_cols - 1
    notes_col = total_cols
    summary_row_index = len(values)
    rows_xml = []
    for row_index, row in enumerate(values, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            style = ''
            if row_index == summary_row_index:
                style = 5 if FIXED_REPORT_COLS < col_index <= material_end else 2
            elif row_index == 1:
                style = 7
            elif row_index in (2, 3):
                style = 8
            elif row_index <= 8:
                style = 1
            elif col_index == notes_col:
                style = 6
            elif col_index >= 3:
                style = 3
            cell = cell_xml(row_index, col_index, value, style)
            if cell:
                cells.append(cell)
        row_attrs = ' r="{0}"'.format(row_index)
        if row_index == 6:
            row_attrs += ' ht="30" customHeight="1"'
        rows_xml.append('<row{0}>{1}</row>'.format(row_attrs, ''.join(cells)))

    merges = [
        'A1:{0}1'.format(excel_col(total_cols)),
        'A2:{0}2'.format(excel_col(total_cols)),
        'A3:{0}3'.format(excel_col(total_cols)),
        'A4:{0}4'.format(excel_col(FIXED_REPORT_COLS)),
        'A5:{0}5'.format(excel_col(FIXED_REPORT_COLS)),
        'A6:{0}6'.format(excel_col(FIXED_REPORT_COLS)),
        '{0}4:{0}8'.format(excel_col(drawing_col)),
        '{0}4:{0}8'.format(excel_col(notes_col)),
        'A{0}:{1}{0}'.format(summary_row_index, excel_col(FIXED_REPORT_COLS)),
    ]
    if material_end > FIXED_REPORT_COLS:
        merges.append('{0}4:{1}4'.format(
            excel_col(FIXED_REPORT_COLS + 1),
            excel_col(material_end)
        ))
    merge_xml = '<mergeCells count="{0}">{1}</mergeCells>'.format(
        len(merges),
        ''.join(['<mergeCell ref="{0}"/>'.format(ref) for ref in merges])
    )

    cols = [
        '<col min="1" max="1" width="12" customWidth="1"/>',
        '<col min="2" max="2" width="24" customWidth="1"/>',
        '<col min="3" max="3" width="13" customWidth="1"/>',
    ]
    if material_end >= FIXED_REPORT_COLS + 1:
        cols.append(
            '<col min="{0}" max="{1}" width="20" customWidth="1"/>'.format(
                FIXED_REPORT_COLS + 1, material_end
            )
        )
    cols.append(
        '<col min="{0}" max="{0}" width="28" customWidth="1"/>'.format(drawing_col)
    )
    cols.append(
        '<col min="{0}" max="{0}" width="48" customWidth="1"/>'.format(notes_col)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<dimension ref="A1:{0}{1}"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="8" topLeftCell="A9" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        '<cols>{2}</cols><sheetData>{3}</sheetData>{4}'
        '</worksheet>'
    ).format(
        excel_col(total_cols),
        len(values),
        ''.join(cols),
        ''.join(rows_xml),
        merge_xml
    )


def audit_sheet_xml(values):
    total_cols = len(values[0]) if values else 1
    rows_xml = []
    for row_index, row in enumerate(values, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            style = 1 if row_index == 1 else (3 if col_index == 5 else '')
            cell = cell_xml(row_index, col_index, value, style)
            if cell:
                cells.append(cell)
        rows_xml.append('<row r="{0}">{1}</row>'.format(row_index, ''.join(cells)))
    widths = [12, 12, 24, 16, 15, 24, 18, 44, 18, 18, 20, 58]
    cols = []
    for index, width in enumerate(widths, start=1):
        cols.append(
            '<col min="{0}" max="{0}" width="{1}" customWidth="1"/>'.format(
                index, width
            )
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<dimension ref="A1:{0}{1}"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        '<cols>{2}</cols><sheetData>{3}</sheetData>'
        '<autoFilter ref="A1:{0}{1}"/>'
        '</worksheet>'
    ).format(excel_col(total_cols), len(values), ''.join(cols), ''.join(rows_xml))


def styles_xml():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="1">'
        '<numFmt numFmtId="164" formatCode="0.00 &quot;㎡&quot;"/>'
        '</numFmts>'
        + takeoff_excel_styles.FONTS_XML
        + takeoff_excel_styles.FILLS_XML
        + takeoff_excel_styles.BORDERS_XML
        + '<cellStyleXfs count="1">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
        '</cellStyleXfs>'
        '<cellXfs count="9">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
        '<alignment horizontal="center" vertical="center" wrapText="1"/>'
        '</xf>'
        '<xf numFmtId="0" fontId="4" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
        '<alignment horizontal="center" vertical="center"/>'
        '</xf>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
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
            '<sheet name="地坪數量計算" sheetId="1" r:id="rId1"/>'
            '<sheet name="地坪檢核" sheetId="2" r:id="rId2"/>'
            '</sheets>'
            '<calcPr calcMode="auto" fullCalcOnLoad="1" forceFullCalc="1"/>'
            '</workbook>'
        )
        write_zip_entry(archive, 'xl/styles.xml', styles_xml())
        write_zip_entry(archive, 'xl/worksheets/sheet1.xml', main_sheet_xml(main_values))
        write_zip_entry(archive, 'xl/worksheets/sheet2.xml', audit_sheet_xml(audit_values))
    finally:
        archive.Dispose()
        fs.Close()


def safe_filename(value):
    return re.sub(r'[\\/:*?"<>|]+', '_', clean(value)) or 'Revit'


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


def collect_families_for_documents(documents):
    global doc
    previous_doc = doc
    combined = {}
    try:
        for source_doc in documents:
            doc = source_doc
            for family_name, symbols in collect_generic_model_families().items():
                combined.setdefault(family_name, []).extend(symbols)
    finally:
        doc = previous_doc
    return combined


def collect_selected_sources(host_doc, options, material_definitions):
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
            rooms, material_cols, stats = collect_rooms(
                material_definitions)
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
    building_prefixes = detect_building_prefixes([
        room.get('level') for room in all_rooms
    ])
    all_rooms.sort(key=lambda room: (
        clean(room.get('source_label')),
        room_sort_key(room, building_prefixes)))
    all_stats['rooms'] = len(all_rooms)
    all_stats['base_rooms'] = [
        u'{0} / {1}'.format(
            room.get('source_label') or '',
            room.get('number') or room.get('name') or room.get('element_id'))
        for room in all_rooms if room.get('base_codes')
    ]
    all_stats['missing_material_codes'] = sorted(list(set(
        all_stats.get('missing_material_codes') or [])),
        key=finish_sort_key)
    return all_rooms, material_cols, all_stats, sources


def main():
    if not doc:
        forms.alert(u'請先開啟 Revit 專案檔，再匯出地坪 Excel。', title=u'地坪 Excel')
        return

    host_doc = doc
    options = takeoff_entry.choose_options(
        host_doc, u'地坪 Excel', allow_host=True, host_required=False)
    if options is None:
        return
    sources = list(takeoff_entry.iter_sources(host_doc, options))
    families = collect_families_for_documents(
        [source[2] for source in sources])
    selected_family, families = choose_material_family(families)
    if selected_family is None:
        return

    material_definitions = load_material_definitions(selected_family, families)
    rooms, material_cols, stats, sources = collect_selected_sources(
        host_doc, options, material_definitions)
    if not rooms:
        forms.alert(u'目前專案沒有可列入報表的有效房間。', title=u'地坪 Excel')
        return

    project_title = revit_file_title()
    main_values = build_sheet_values(
        make_rows(rooms, material_cols),
        material_cols,
        project_title,
        material_definitions
    )
    audit_values = build_audit_values(rooms, material_definitions)
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
                        (u'地坪數量計算', u'地坪'),
                        u'地坪檢核',
                    ],
                    summary_specs={
                        u'地坪': {
                            'label': SUMMARY_LABEL,
                            'header_label': u'材料編號',
                            'data_header_label': u'空間名稱',
                        },
                    }))
            outpath = workbook_path
        except takeoff_direct_publish.WorkbookPublishError as exc:
            forms.alert(
                u'更新主要 Excel 失敗：\n{0}'.format(exc),
                title=u'地坪 Excel')
            return
        finally:
            takeoff_direct_publish.remove_file_quietly(temp_path)
    else:
        outpath = forms.save_file(
            file_ext='xlsx',
            default_name=(
                safe_filename(project_title) + u'_地坪數量計算.xlsx'),
            title=u'匯出地坪數量計算 Excel'
        )
        if not outpath:
            return
        if not outpath.lower().endswith('.xlsx'):
            outpath += '.xlsx'
        write_xlsx(outpath, main_values, audit_values)

    action_label = u'更新' if workbook_path else u'匯出'
    output.print_md(u'## 地坪 Excel {0}完成'.format(action_label))
    output.print_md(u'- 版本：`{0}`'.format(SCRIPT_VERSION))
    output.print_md(u'- 檔案：`{0}`'.format(outpath))
    output.print_md(u'- Revit 來源：{0}'.format(len(sources)))
    if publish_result:
        output.print_md(u'- 備份：`{0}`'.format(
            publish_result.get('backup_path')))
    output.print_md(u'- 一般模型材料版族群：{0}'.format(selected_family))
    output.print_md(u'- Rooms：{0}（全部有效房間皆列出）'.format(stats['rooms']))
    output.print_md(u'- Room「樓板塗層」：有 F 代碼 {0}，空白或 - {1}'.format(
        stats['rooms_with_code'],
        stats['rooms_without_code']
    ))
    output.print_md(u'- F 材料欄：{0}；材料版辨識：{1}'.format(
        len(material_cols),
        len([code for code in material_cols if material_definitions.get(code)])
    ))
    output.print_md(u'- 含基座、需人工計算：{0} 間'.format(len(stats['base_rooms'])))
    output.print_md(u'- 多重一般地坪：每個非基座材料欄皆引用同一列 Room 面積')
    if stats['missing_material_codes']:
        output.print_md(u'- 材料版找不到名稱的代碼：{0}'.format(
            u'、'.join(stats['missing_material_codes'])
        ))

    message = u'地坪 Excel 已{0}：\n{1}'.format(action_label, outpath)
    if stats['base_rooms']:
        message += u'\n\n含基座、需手動計算：{0} 間（詳見備註）'.format(
            len(stats['base_rooms'])
        )
    forms.alert(message, title=u'地坪 Excel')


try:
    main()
except Exception as exc:
    forms.alert(u'執行失敗：\n{0}'.format(exc), title=u'地坪 Excel')
    raise
