# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure OpenXML generation for simple .xlsx listings.

Everything here is string building with no Revit and no .NET, so the parts of
workbook writing that are easy to get subtly wrong — column letters past Z,
escaping, style indices — are unit-tested offline. The caller only has to zip
:func:`workbook_parts` into a file.

Deliberately no cell borders. ``takeoff_excel_styles.BORDERS_XML`` puts the
thin border at index 0, and Excel treats ``borderId="0"`` as its built-in
no-border default no matter what the file says, so those borders silently do
not render (see log 2026-08-07). A plain data listing reads better without
them anyway; the header gets bold and a fill, and the rest is number formats.
"""

try:
    _INTEGER_TYPES = (int, long)          # noqa: F821  (Python 2 only)
    _CHR = unichr                         # noqa: F821  (Python 2 only)
except NameError:
    _INTEGER_TYPES = (int,)
    _CHR = chr

_NUMBER_TYPES = tuple(list(_INTEGER_TYPES) + [float])

# Style indices into cellXfs below. Kept as names because a bare 3 in a sheet
# spec is unreadable and a wrong one is invisible until Excel opens the file.
STYLE_TEXT = 0
STYLE_HEADER = 1
STYLE_INT = 2
STYLE_DECIMAL = 3

# Excel refuses these in a sheet name, and caps the name at 31 characters.
SHEET_NAME_FORBIDDEN = u'[]:*?/\\'
SHEET_NAME_LIMIT = 31


def xml_escape(text):
    return (u'{}'.format(text)
            .replace(u'&', u'&amp;')
            .replace(u'<', u'&lt;')
            .replace(u'>', u'&gt;')
            .replace(u'"', u'&quot;'))


def is_number(value):
    """Whether the value should be written as a number rather than text.

    ``bool`` is excluded on purpose: it is an ``int`` subclass in Python, and
    writing True into a cell as ``1`` loses what the column meant.
    """
    if isinstance(value, bool):
        return False
    return isinstance(value, _NUMBER_TYPES)


def excel_col(index):
    """1 -> A, 26 -> Z, 27 -> AA. Wrong past Z is the classic off-by-one."""
    if index < 1:
        raise ValueError('column index is 1-based')
    letters = u''
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = _CHR(65 + remainder) + letters
    return letters


def cell_xml(row_index, col_index, value, style=STYLE_TEXT):
    if value is None or value == u'':
        return u''
    reference = u'{}{}'.format(excel_col(col_index), row_index)
    attributes = u' s="{}"'.format(style) if style else u''
    if is_number(value):
        return u'<c r="{}"{}><v>{}</v></c>'.format(
            reference, attributes, value)
    return u'<c r="{}"{} t="inlineStr"><is><t xml:space="preserve">{}</t>'\
           u'</is></c>'.format(reference, attributes, xml_escape(value))


def sheet_xml(rows, spec=None):
    """One worksheet part.

    ``spec`` keys: ``widths`` (list of column widths), ``formats``
    (1-based column index -> style), ``freeze`` (rows to freeze, which also
    turns on the autofilter over the header).
    """
    spec = spec or {}
    rows = [row for row in rows or []] or [[]]
    formats = spec.get('formats') or {}
    total_cols = max([len(row) for row in rows] or [1]) or 1

    rows_xml = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            if row_index == 1:
                style = STYLE_HEADER
            else:
                style = formats.get(col_index, STYLE_TEXT)
            cell = cell_xml(row_index, col_index, value, style)
            if cell:
                cells.append(cell)
        rows_xml.append(u'<row r="{}">{}</row>'.format(
            row_index, u''.join(cells)))

    col_defs = []
    for index, width in enumerate(spec.get('widths') or (), start=1):
        col_defs.append(
            u'<col min="{0}" max="{0}" width="{1}" customWidth="1"/>'.format(
                index, width))
    cols = u'<cols>{}</cols>'.format(u''.join(col_defs)) if col_defs else u''

    freeze = int(spec.get('freeze') or 0)
    view = u'<sheetView workbookViewId="0">'
    if freeze:
        view += (u'<pane ySplit="{0}" topLeftCell="A{1}" '
                 u'activePane="bottomLeft" state="frozen"/>'.format(
                     freeze, freeze + 1))
    view += u'</sheetView>'

    last = u'{}{}'.format(excel_col(total_cols), max(1, len(rows)))
    auto_filter = u'<autoFilter ref="A1:{}"/>'.format(last) if freeze else u''  # sheet-layout: ignore（A1 是工作表原點，恆定）
    return (
        u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        u'<worksheet xmlns="http://schemas.openxmlformats.org/'
        u'spreadsheetml/2006/main">'
        u'<dimension ref="A1:{0}"/>'  # sheet-layout: ignore（A1 是工作表原點，恆定）
        u'<sheetViews>{1}</sheetViews>{2}'
        u'<sheetData>{3}</sheetData>{4}'
        u'</worksheet>'
    ).format(last, view, cols, u''.join(rows_xml), auto_filter)


def styles_xml():
    return (
        u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        u'<styleSheet xmlns="http://schemas.openxmlformats.org/'
        u'spreadsheetml/2006/main">'
        u'<numFmts count="2">'
        u'<numFmt numFmtId="164" formatCode="#,##0"/>'
        u'<numFmt numFmtId="165" formatCode="0.00"/>'
        u'</numFmts>'
        u'<fonts count="2">'
        u'<font><sz val="11"/><name val="Calibri"/></font>'
        u'<font><b/><sz val="11"/><name val="Calibri"/></font>'
        u'</fonts>'
        u'<fills count="3">'
        u'<fill><patternFill patternType="none"/></fill>'
        u'<fill><patternFill patternType="gray125"/></fill>'
        u'<fill><patternFill patternType="solid">'
        u'<fgColor rgb="FFD9E2F3"/><bgColor indexed="64"/>'
        u'</patternFill></fill>'
        u'</fills>'
        u'<borders count="1"><border><left/><right/><top/><bottom/>'
        u'<diagonal/></border></borders>'
        u'<cellStyleXfs count="1">'
        u'<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
        u'</cellStyleXfs>'
        u'<cellXfs count="4">'
        u'<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        u'<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" '
        u'applyFont="1" applyFill="1" applyAlignment="1">'
        u'<alignment horizontal="center" vertical="center"/></xf>'
        u'<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" '
        u'applyNumberFormat="1"/>'
        u'<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" '
        u'applyNumberFormat="1"/>'
        u'</cellXfs>'
        u'<cellStyles count="1">'
        u'<cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        u'</styleSheet>')


def safe_sheet_name(raw, used=None):
    """An Excel-legal, unique sheet name.

    Excel rejects the whole file for a name over 31 characters, containing
    ``[]:*?/\\``, or repeated — so a scheme called 「法定面積／銷售面積比較表」
    cannot simply be used as-is, and two schemes whose names differ only after
    character 31 would otherwise collide silently.
    """
    used = used or []
    text = u''.join(char for char in u'{}'.format(raw or u'')
                    if char not in SHEET_NAME_FORBIDDEN).strip()
    text = text or u'Sheet'
    text = text[:SHEET_NAME_LIMIT]
    if text not in used:
        return text
    index = 2
    while True:
        suffix = u'({})'.format(index)
        candidate = text[:SHEET_NAME_LIMIT - len(suffix)] + suffix
        if candidate not in used:
            return candidate
        index += 1


def workbook_parts(sheets):
    """``[(entry_name, xml)]`` for every part of the package.

    ``sheets`` is ``[(name, rows, spec)]``. The caller writes each entry into a
    zip; nothing here touches the filesystem.
    """
    sheets = [item for item in sheets or []]
    if not sheets:
        raise ValueError('a workbook needs at least one sheet')

    overrides = u''.join(
        u'<Override PartName="/xl/worksheets/sheet{}.xml" '
        u'ContentType="application/vnd.openxmlformats-officedocument.'
        u'spreadsheetml.worksheet+xml"/>'.format(index)
        for index in range(1, len(sheets) + 1))
    rels = u''.join(
        u'<Relationship Id="rId{0}" Type="http://schemas.openxmlformats.org/'
        u'officeDocument/2006/relationships/worksheet" '
        u'Target="worksheets/sheet{0}.xml"/>'.format(index)
        for index in range(1, len(sheets) + 1))
    sheet_tags = u''.join(
        u'<sheet name="{}" sheetId="{}" r:id="rId{}"/>'.format(
            xml_escape(name), index, index)
        for index, (name, unused_rows, unused_spec)
        in enumerate(sheets, start=1))
    styles_rid = len(sheets) + 1

    parts = [
        ('[Content_Types].xml',
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
         u'</Types>'),
        ('_rels/.rels',
         u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         u'<Relationships xmlns="http://schemas.openxmlformats.org/'
         u'package/2006/relationships">'
         u'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
         u'officeDocument/2006/relationships/officeDocument" '
         u'Target="xl/workbook.xml"/></Relationships>'),
        ('xl/_rels/workbook.xml.rels',
         u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         u'<Relationships xmlns="http://schemas.openxmlformats.org/'
         u'package/2006/relationships">' + rels +
         u'<Relationship Id="rId{}" Type="http://schemas.openxmlformats.org/'
         u'officeDocument/2006/relationships/styles" '
         u'Target="styles.xml"/></Relationships>'.format(styles_rid)),
        ('xl/workbook.xml',
         u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         u'<workbook xmlns="http://schemas.openxmlformats.org/'
         u'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats'
         u'.org/officeDocument/2006/relationships">'
         u'<sheets>' + sheet_tags + u'</sheets></workbook>'),
        ('xl/styles.xml', styles_xml()),
    ]
    for index, (unused_name, rows, spec) in enumerate(sheets, start=1):
        parts.append(('xl/worksheets/sheet{}.xml'.format(index),
                      sheet_xml(rows, spec)))
    return parts
