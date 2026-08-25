# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Shared font scheme for the takeoff reports that publish into the main Excel.

Each generated sheet uses this small common font and border scheme when it is
exported as a standalone workbook.  When it is published into the user's
main workbook, the publisher keeps the target sheet's fills, column widths,
row heights and merges, applies these row-role fonts, and enforces a thin
table grid.  This lets the current desktop workbook remain the visual source
of truth for colors and layout while fixing old borderless report sheets.

Row role -> font id -> size (every font is 標楷體):

    0  data rows and blank cells      9
    1  section row and column header 12
    2  report title (row 1)          24
    3  project name / table name     14
    4  summary row                    9  bold

The cellXfs (style) indices are deliberately NOT shared: each report carries
its own number formats, so the tables are different lengths.  Every script
maps rows to style ids next to its own cell writer.
"""

FONT_DATA = 0
FONT_HEADER = 1
FONT_TITLE = 2
FONT_SUBTITLE = 3
FONT_SUMMARY = 4

STYLE_DEFAULT = 0
STYLE_HEADER = 1
STYLE_SUMMARY = 2
STYLE_TITLE = 3
STYLE_SUBTITLE = 4

FONT_NAME = '標楷體'

FONTS_XML = (
    '<fonts count="5">'
    '<font><sz val="9"/><name val="標楷體"/></font>'
    '<font><sz val="12"/><name val="標楷體"/></font>'
    '<font><sz val="24"/><name val="標楷體"/></font>'
    '<font><sz val="14"/><name val="標楷體"/></font>'
    '<font><b/><sz val="9"/><name val="標楷體"/></font>'
    '</fonts>'
)

# The desktop workbook owns fills and layout.  Standalone exports still need
# a real border definition so blank/detail cells do not lose the table frame.
FILLS_XML = (
    '<fills count="2">'
    '<fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '</fills>'
)

BORDERS_XML = (
    '<borders count="1"><border>'
    '<left style="thin"><color rgb="FF000000"/></left>'
    '<right style="thin"><color rgb="FF000000"/></right>'
    '<top style="thin"><color rgb="FF000000"/></top>'
    '<bottom style="thin"><color rgb="FF000000"/></bottom>'
    '<diagonal/>'
    '</border></borders>'
)


def style_attr(style_id):
    if style_id in ('', None, STYLE_DEFAULT):
        return ''
    return ' s="{0}"'.format(style_id)


def row_style_id(row_index, summary_row_index=None, header_row_count=5):
    if summary_row_index and row_index == summary_row_index:
        return STYLE_SUMMARY
    if row_index == 1:
        return STYLE_TITLE
    if row_index in (2, 3):
        return STYLE_SUBTITLE
    if row_index <= header_row_count:
        return STYLE_HEADER
    return STYLE_DEFAULT
