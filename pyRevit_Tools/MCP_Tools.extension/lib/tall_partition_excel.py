# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Tall-partition (>6 m) structural feedback workbook.

Writes a three-sheet .xlsx straight from the MCP analysis result: a wall sheet
(the deliverable structure works from), a room sheet, and the criteria/audit
sheet. OpenXML is written directly through ZipArchive so the button never
depends on Excel being installed — matching the other takeoff buttons.

``System.IO.Compression`` is not one of the assemblies IronPython's host loads
by default, so ``clr.AddReference`` has to name it explicitly before the
``from ... import`` below can resolve — without it the import fails at runtime
with ``ImportError: Cannot import name ZipArchive`` (see log 2026-08-17: this
was the actual, previously-unverified state of this file).
"""

import os
import re

import clr
clr.AddReference('System.IO.Compression')

from pyrevit import forms, revit
from System.IO import FileAccess, FileMode, FileStream
from System.IO.Compression import ZipArchive, ZipArchiveMode
from System.Text import Encoding

import mcp_bridge as mcp
import tall_partition_logic as logic
import takeoff_excel_styles

try:
    reload(logic)
except Exception:
    pass


TITLE = u'高隔間分析 Excel'
THRESHOLD_MM = 6000.0

SHEETS = (
    (u'高牆清單', 'wall_values'),
    (u'受影響房間', 'room_values'),
    (u'檢核條件', 'criteria_values'),
)
# Per sheet: column widths, and which 1-based columns carry which number style.
SHEET_FORMATS = {
    u'高牆清單': {
        'widths': [10, 14, 30, 12, 14, 11, 13, 12, 10, 46],
        'mm': (4,), 'm': (6,), 'm2': (7,), 'freeze': 1,
    },
    u'受影響房間': {
        'widths': [10, 10, 24, 14, 13, 9, 11, 13, 16, 16, 16, 16, 40],
        'mm': (10, 11, 12), 'm': (8,), 'm2': (5, 9), 'freeze': 1,
    },
    u'檢核條件': {
        'widths': [26, 72], 'mm': (), 'm': (), 'm2': (), 'freeze': 0,
    },
}

STYLE_DEFAULT = 0
STYLE_HEADER = 1
STYLE_MM = 2
STYLE_M = 3
STYLE_M2 = 4


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value)
    except Exception:
        return str(value)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def xml_escape(text):
    return (_text(text).replace(u'&', u'&amp;').replace(u'<', u'&lt;')
            .replace(u'>', u'&gt;').replace(u'"', u'&quot;'))


def excel_col(index):
    value = int(index)
    result = u''
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _cell_xml(row_index, col_index, value, style):
    ref = u'{}{}'.format(excel_col(col_index), row_index)
    attrs = u' s="{}"'.format(style) if style else u''
    if value is None or value == u'':
        return u'<c r="{}"{} />'.format(ref, attrs)
    if _is_number(value):
        return u'<c r="{}"{}><v>{}</v></c>'.format(ref, attrs, value)
    return u'<c r="{}"{} t="inlineStr"><is><t>{}</t></is></c>'.format(
        ref, attrs, xml_escape(value))


def _sheet_xml(values, spec):
    total_cols = max([len(row) for row in values] or [1])
    mm_cols = set(spec.get('mm') or ())
    m_cols = set(spec.get('m') or ())
    m2_cols = set(spec.get('m2') or ())
    rows_xml = []
    for row_index, row in enumerate(values, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            if row_index == 1:
                style = STYLE_HEADER
            elif col_index in mm_cols:
                style = STYLE_MM
            elif col_index in m_cols:
                style = STYLE_M
            elif col_index in m2_cols:
                style = STYLE_M2
            else:
                style = STYLE_DEFAULT
            cell = _cell_xml(row_index, col_index, value, style)
            if cell:
                cells.append(cell)
        rows_xml.append(u'<row r="{}">{}</row>'.format(
            row_index, u''.join(cells)))
    col_defs = []
    for index, width in enumerate(spec.get('widths') or (), start=1):
        col_defs.append(
            u'<col min="{0}" max="{0}" width="{1}" customWidth="1"/>'.format(
                index, width))
    freeze = spec.get('freeze') or 0
    view = u'<sheetView workbookViewId="0">'
    if freeze:
        view += (u'<pane ySplit="{0}" topLeftCell="A{1}" '
                 u'activePane="bottomLeft" state="frozen"/>'.format(
                     freeze, freeze + 1))
    view += u'</sheetView>'
    last = u'{}{}'.format(excel_col(total_cols), max(1, len(values)))
    auto_filter = (u'<autoFilter ref="A1:{}"/>'.format(last)  # sheet-layout: ignore（A1 是工作表原點，恆定）
                   if freeze else u'')
    return (
        u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        u'<worksheet xmlns="http://schemas.openxmlformats.org/'
        u'spreadsheetml/2006/main">'
        u'<dimension ref="A1:{0}"/>'  # sheet-layout: ignore（A1 是工作表原點，恆定）
        u'<sheetViews>{1}</sheetViews>'
        u'<cols>{2}</cols><sheetData>{3}</sheetData>{4}'
        u'</worksheet>'
    ).format(last, view, u''.join(col_defs), u''.join(rows_xml), auto_filter)


def _write_entry(archive, name, content):
    entry = archive.CreateEntry(name)
    stream = entry.Open()
    try:
        data = Encoding.UTF8.GetBytes(content)
        stream.Write(data, 0, data.Length)
    finally:
        stream.Close()


def write_xlsx(path, shaped):
    sheet_xml = [(name, _sheet_xml(shaped[key], SHEET_FORMATS[name]))
                 for name, key in SHEETS]
    overrides = u''.join(
        u'<Override PartName="/xl/worksheets/sheet{}.xml" '
        u'ContentType="application/vnd.openxmlformats-officedocument.'
        u'spreadsheetml.worksheet+xml"/>'.format(index)
        for index in range(1, len(sheet_xml) + 1))
    rels = u''.join(
        u'<Relationship Id="rId{0}" Type="http://schemas.openxmlformats.org/'
        u'officeDocument/2006/relationships/worksheet" '
        u'Target="worksheets/sheet{0}.xml"/>'.format(index)
        for index in range(1, len(sheet_xml) + 1))
    sheets = u''.join(
        u'<sheet name="{}" sheetId="{}" r:id="rId{}"/>'.format(
            xml_escape(name), index, index)
        for index, (name, _xml) in enumerate(sheet_xml, start=1))
    styles_rid = len(sheet_xml) + 1

    stream = FileStream(path, FileMode.Create, FileAccess.ReadWrite)
    archive = ZipArchive(stream, ZipArchiveMode.Create)
    try:
        _write_entry(
            archive, '[Content_Types].xml',
            u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            u'content-types">'
            u'<Default Extension="rels" ContentType="application/'
            u'vnd.openxmlformats-package.relationships+xml"/>'
            u'<Default Extension="xml" ContentType="application/xml"/>'
            u'<Override PartName="/xl/workbook.xml" ContentType="application/'
            u'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + overrides +
            u'<Override PartName="/xl/styles.xml" ContentType="application/'
            u'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            u'</Types>')
        _write_entry(
            archive, '_rels/.rels',
            u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<Relationships xmlns="http://schemas.openxmlformats.org/'
            u'package/2006/relationships">'
            u'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            u'officeDocument/2006/relationships/officeDocument" '
            u'Target="xl/workbook.xml"/></Relationships>')
        _write_entry(
            archive, 'xl/_rels/workbook.xml.rels',
            u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<Relationships xmlns="http://schemas.openxmlformats.org/'
            u'package/2006/relationships">' + rels +
            u'<Relationship Id="rId{}" Type="http://schemas.openxmlformats.org/'
            u'officeDocument/2006/relationships/styles" '
            u'Target="styles.xml"/></Relationships>'.format(styles_rid))
        _write_entry(
            archive, 'xl/workbook.xml',
            u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<workbook xmlns="http://schemas.openxmlformats.org/'
            u'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats'
            u'.org/officeDocument/2006/relationships">'
            u'<sheets>' + sheets + u'</sheets></workbook>')
        _write_entry(
            archive, 'xl/styles.xml',
            u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<styleSheet xmlns="http://schemas.openxmlformats.org/'
            u'spreadsheetml/2006/main">'
            u'<numFmts count="3">'
            u'<numFmt numFmtId="164" formatCode="#,##0"/>'
            u'<numFmt numFmtId="165" formatCode="0.00"/>'
            u'<numFmt numFmtId="166" formatCode="0.00"/>'
            u'</numFmts>' +
            takeoff_excel_styles.FONTS_XML +
            u'<fills count="3">'
            u'<fill><patternFill patternType="none"/></fill>'
            u'<fill><patternFill patternType="gray125"/></fill>'
            u'<fill><patternFill patternType="solid">'
            u'<fgColor rgb="FFD9E2F3"/><bgColor indexed="64"/>'
            u'</patternFill></fill>'
            u'</fills>' +
            takeoff_excel_styles.BORDERS_XML +
            u'<cellStyleXfs count="1">'
            u'<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
            u'</cellStyleXfs>'
            u'<cellXfs count="5">'
            u'<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            u'<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" '
            u'applyFill="1" applyAlignment="1">'
            u'<alignment horizontal="center" vertical="center"/></xf>'
            u'<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" '
            u'applyNumberFormat="1"/>'
            u'<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" '
            u'applyNumberFormat="1"/>'
            u'<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" '
            u'applyNumberFormat="1"/>'
            u'</cellXfs>'
            u'<cellStyles count="1">'
            u'<cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            u'</styleSheet>')
        for index, (_name, xml) in enumerate(sheet_xml, start=1):
            _write_entry(archive, 'xl/worksheets/sheet{}.xml'.format(index),
                         xml)
    finally:
        archive.Dispose()
        stream.Close()


def safe_filename(text):
    value = re.sub(r'[\\/:*?"<>|]+', '_', _text(text)).strip()
    return value or u'Revit'


def default_filename(doc):
    source = doc.PathName or u''
    stem = os.path.splitext(os.path.basename(source))[0] if source else u''
    return u'{}_高隔間分析.xlsx'.format(safe_filename(stem or doc.Title))


def run(doc):
    try:
        data = mcp.run('analyze_tall_partition_rooms', {
            'autoDetectLevels': True,
            'minWallHeightMm': THRESHOLD_MM,
            'includeDetails': True,
            'includeRoomRayHeight': True,
        })
    except mcp.MCPBridgeError as error:
        mcp.show_error(error, TITLE)
        return

    if not data or not data.get('Success'):
        forms.alert(u'分析未成功回傳結果。', title=TITLE)
        return

    shaped = logic.build_workbook_data(data)
    if not shaped['wall_count']:
        forms.alert(
            u'找不到高於 {:.0f} mm 的輕隔間牆。\n\n'
            u'（已排除牆型 {} 面）'.format(
                THRESHOLD_MM, shaped['excluded_wall_count']),
            title=TITLE)
        return

    path = forms.save_file(file_ext='xlsx',
                           default_name=default_filename(doc))
    if not path:
        return
    try:
        write_xlsx(path, shaped)
    except Exception as error:
        forms.alert(u'寫入 Excel 失敗：\n\n{}'.format(error), title=TITLE)
        return

    forms.alert(
        u'{}\n\n已輸出：{}'.format(
            logic.summary_message(shaped, THRESHOLD_MM), path),
        title=TITLE)
