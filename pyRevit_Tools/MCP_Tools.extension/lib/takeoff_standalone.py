# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Small dependency-free OpenXML writer for standalone takeoff workbooks.

The pyRevit runtime is IronPython 2.7 and cannot assume that Excel or a
third-party spreadsheet package is installed.  This module therefore writes
the minimum Office Open XML package directly with the Python standard library.
It intentionally supports only the value types needed by takeoff reports.
"""

import datetime
import os
import zipfile

import takeoff_excel_styles

try:
    text_type = unicode
except NameError:  # CPython 3 tests
    text_type = str
try:
    integer_types = (int, long)
except NameError:  # CPython 3 tests
    integer_types = (int,)


DETAIL_SHEET = u'數量明細'
FORMULA_SHEET = u'公式摘要'
AUDIT_SHEET = u'稽核'
MODE_UPDATE = 'update'
MODE_STANDALONE = 'standalone'


def entry_mode(options):
    """Pure route used by every update-or-export takeoff entry point."""
    return (
        MODE_UPDATE
        if _text((options or {}).get('workbook_path')).strip()
        else MODE_STANDALONE)


def _text(value):
    if value is None:
        return ''
    if isinstance(value, text_type):
        return value
    return text_type(value)


def _xml(value):
    return (_text(value)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&apos;'))


def _column_name(index):
    """Return the one-based Excel column name."""
    value = int(index)
    if value < 1:
        raise ValueError('Excel column indexes are one-based')
    result = []
    while value:
        value, remainder = divmod(value - 1, 26)
        result.append(chr(65 + remainder))
    result.reverse()
    return ''.join(result)


def _row_values(row, headers):
    if hasattr(row, 'get'):
        return [row.get(header) for header in headers]
    values = list(row)
    if len(values) != len(headers):
        raise ValueError(
            'A workbook row has {} values but {} headers were supplied.'
            .format(len(values), len(headers)))
    return values


def _cell_xml(reference, value, style_id=None):
    style = '' if style_id is None else ' s="{}"'.format(int(style_id))
    if value is None or value == '':
        return '<c r="{}"{} />'.format(reference, style)
    if isinstance(value, bool):
        return (
            '<c r="{}"{} t="b"><v>{}</v></c>'
            .format(reference, style, 1 if value else 0))
    if isinstance(value, integer_types + (float,)):
        return (
            '<c r="{}"{} t="n"><v>{}</v></c>'
            .format(reference, style, _text(value)))
    text = _text(value)
    if text.startswith('='):
        return (
            '<c r="{}"{}><f>{}</f><v></v></c>'
            .format(reference, style, _xml(text[1:])))
    preserve = (
        ' xml:space="preserve"'
        if text != text.strip() or '\n' in text else '')
    return (
        '<c r="{}"{} t="inlineStr"><is><t{}>{}</t></is></c>'
        .format(reference, style, preserve, _xml(text)))


def _sheet_xml(headers, rows):
    headers = [_text(value) for value in headers]
    if not headers:
        raise ValueError('Each standalone workbook sheet requires headers.')
    normalized_rows = [_row_values(row, headers) for row in rows]
    last_column = _column_name(len(headers))
    last_row = max(1, len(normalized_rows) + 1)
    output = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main">',
        '<dimension ref="A1:{}{}"/>'.format(last_column, last_row),
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
        'state="frozen"/></sheetView></sheetViews>',
        '<sheetFormatPr defaultRowHeight="15"/>',
        '<cols>',
    ]
    for index in range(1, len(headers) + 1):
        output.append(
            '<col min="{0}" max="{0}" width="18" customWidth="1"/>'
            .format(index))
    output.extend(['</cols>', '<sheetData>'])
    header_cells = []
    for index, value in enumerate(headers, 1):
        header_cells.append(_cell_xml(
            '{}1'.format(_column_name(index)), value, 1))
    output.append('<row r="1">{}</row>'.format(''.join(header_cells)))
    for row_index, values in enumerate(normalized_rows, 2):
        cells = []
        for column_index, value in enumerate(values, 1):
            cells.append(_cell_xml(
                '{}{}'.format(_column_name(column_index), row_index),
                value))
        output.append(
            '<row r="{}">{}</row>'.format(row_index, ''.join(cells)))
    output.extend([
        '</sheetData>',
        '<autoFilter ref="A1:{}{}"/>'.format(last_column, last_row),
        '</worksheet>',
    ])
    return ''.join(output)


def _content_types():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
        'content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxml'
        'formats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.'
        'openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.extended-properties+xml"/>'
        '</Types>')


def _package_rels():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
        '2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/'
        'package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/extended-properties" '
        'Target="docProps/app.xml"/>'
        '</Relationships>')


def _workbook_xml():
    names = (DETAIL_SHEET, FORMULA_SHEET, AUDIT_SHEET)
    sheets = []
    for index, name in enumerate(names, 1):
        sheets.append(
            '<sheet name="{}" sheetId="{}" r:id="rId{}"/>'
            .format(_xml(name), index, index))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
        '2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships"><bookViews><workbookView/></bookViews>'
        '<sheets>{}</sheets><calcPr calcId="0" calcMode="auto" '
        'fullCalcOnLoad="1" '
        'forceFullCalc="1"/></workbook>'.format(''.join(sheets)))


def _workbook_rels():
    relationships = []
    for index in range(1, 4):
        relationships.append(
            '<Relationship Id="rId{}" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet{}.xml"/>'.format(index, index))
    relationships.append(
        '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/styles" Target="styles.xml"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
        '2006/relationships">{}</Relationships>'
        .format(''.join(relationships)))


def _styles_xml():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
        '2006/main">'
        + takeoff_excel_styles.FONTS_XML
        + '<fills count="3"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF4472C4"/>'
        '<bgColor indexed="64"/></patternFill></fill></fills>'
        + takeoff_excel_styles.BORDERS_XML
        + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" '
        'borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" '
        'borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" '
        'borderId="0" xfId="0" applyFont="1" applyFill="1" '
        'applyAlignment="1"><alignment horizontal="center"/></xf></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" '
        'builtinId="0"/></cellStyles></styleSheet>')


def _core_xml(title):
    created = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
        'package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dc:title>{}</dc:title><dc:creator>RevitMCP</dc:creator>'
        '<cp:lastModifiedBy>RevitMCP</cp:lastModifiedBy>'
        '<dcterms:created xsi:type="dcterms:W3CDTF">{}</dcterms:created>'
        '</cp:coreProperties>'.format(_xml(title), created))


def _app_xml():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/'
        '2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/'
        'officeDocument/2006/docPropsVTypes"><Application>RevitMCP</Application>'
        '<TitlesOfParts><vt:vector size="3" baseType="lpstr">'
        '<vt:lpstr>{}</vt:lpstr><vt:lpstr>{}</vt:lpstr>'
        '<vt:lpstr>{}</vt:lpstr></vt:vector></TitlesOfParts>'
        '</Properties>'.format(
            _xml(DETAIL_SHEET), _xml(FORMULA_SHEET), _xml(AUDIT_SHEET)))


def _write_part(package, name, content):
    if isinstance(content, text_type):
        content = content.encode('utf-8')
    package.writestr(name, content)


def write_standard_workbook(path, detail_rows, detail_headers,
                            formula_rows, formula_headers,
                            audit_rows, audit_headers, title):
    """Write the standardized three-sheet takeoff workbook.

    ``rows`` may contain dictionaries keyed by the corresponding header, or
    list/tuple values in header order.  A string beginning with ``=`` is
    emitted as an Excel formula rather than as literal text.
    """
    output_path = os.path.abspath(_text(path))
    if os.path.splitext(output_path)[1].lower() != '.xlsx':
        raise ValueError('Standalone takeoff workbooks must use .xlsx.')
    directory = os.path.dirname(output_path)
    if not directory or not os.path.isdir(directory):
        raise ValueError('The destination folder does not exist.')

    sheets = (
        (detail_headers, detail_rows),
        (formula_headers, formula_rows),
        (audit_headers, audit_rows),
    )
    sheet_payloads = [
        _sheet_xml(headers, rows) for headers, rows in sheets]
    package = zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED)
    try:
        _write_part(package, '[Content_Types].xml', _content_types())
        _write_part(package, '_rels/.rels', _package_rels())
        _write_part(package, 'xl/workbook.xml', _workbook_xml())
        _write_part(package, 'xl/_rels/workbook.xml.rels', _workbook_rels())
        _write_part(package, 'xl/styles.xml', _styles_xml())
        _write_part(package, 'docProps/core.xml', _core_xml(title))
        _write_part(package, 'docProps/app.xml', _app_xml())
        for index, content in enumerate(sheet_payloads, 1):
            _write_part(
                package,
                'xl/worksheets/sheet{}.xml'.format(index),
                content)
    finally:
        package.close()
    return output_path
