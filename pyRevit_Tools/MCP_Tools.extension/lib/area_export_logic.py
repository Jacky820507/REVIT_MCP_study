# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 面積清單匯出 Excel (JAC 01.01).

「多筆」 means several area schemes in one workbook: one worksheet per scheme
plus a summary that totals each scheme by level. Exporting schemes one at a
time is what makes people reconcile numbers by hand.

Which columns appear is a choice, not a constant — the fields a 法定面積 review
needs are not the fields a 銷售面積 sheet needs, and hard-coding either would
send someone back to Excel to delete columns. :data:`FIELDS` is the menu; the
caller passes the keys it wants, in order.
"""

import area_placement_logic as base
import xlsx_xml


SQ_FT_TO_SQ_M = 0.09290304
FT_TO_M = 0.3048

# key, header, cell style, column width, and how to pull it off a record.
FIELDS = (
    ('scheme', u'面積計畫', xlsx_xml.STYLE_TEXT, 22),
    ('level', u'樓層', xlsx_xml.STYLE_TEXT, 12),
    ('number', u'編號', xlsx_xml.STYLE_TEXT, 14),
    ('name', u'名稱', xlsx_xml.STYLE_TEXT, 24),
    ('area_m2', u'面積(m²)', xlsx_xml.STYLE_DECIMAL, 13),
    ('perimeter_m', u'周長(m)', xlsx_xml.STYLE_DECIMAL, 12),
    ('area_type', u'面積類型', xlsx_xml.STYLE_TEXT, 16),
    ('status', u'狀態', xlsx_xml.STYLE_TEXT, 12),
    ('warnings', u'Revit 警告', xlsx_xml.STYLE_TEXT, 30),
    ('id', u'Element ID', xlsx_xml.STYLE_INT, 13),
)

DEFAULT_FIELD_KEYS = ('level', 'number', 'name', 'area_m2', 'perimeter_m',
                      'status', 'id')

FIELD_INDEX = dict((key, (header, style, width))
                   for key, header, style, width in FIELDS)

SUMMARY_SHEET = u'彙總'


def field_labels():
    """``[(label, key)]`` in menu order, for a selection dialog."""
    return [(header, key) for key, header, unused_style, unused_width
            in FIELDS]


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _round(value, digits=2):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return 0.0


def record_value(record, key):
    """One cell's value, converted to the unit its header promises.

    Revit stores lengths in feet and areas in square feet; a column headed
    ``面積(m²)`` holding square feet is the kind of error that survives review
    because the number still looks plausible.
    """
    if key == 'area_m2':
        return _round(_number(record.get('area_sqft')) * SQ_FT_TO_SQ_M)
    if key == 'perimeter_m':
        return _round(_number(record.get('perimeter_ft')) * FT_TO_M)
    if key == 'id':
        try:
            return int(record.get('id'))
        except (TypeError, ValueError):
            return 0
    if key == 'warnings':
        return u'；'.join(
            _text(entry.get('label') if isinstance(entry, dict) else entry)
            for entry in record.get('warnings') or [])
    return _text(record.get(key))


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def resolve_fields(keys):
    """Validate and order the requested columns, falling back to the default."""
    chosen = [key for key in keys or [] if key in FIELD_INDEX]
    if not chosen:
        chosen = list(DEFAULT_FIELD_KEYS)
    return chosen


def build_sheet(records, field_keys=None):
    """``(rows, spec)`` for one scheme's worksheet."""
    keys = resolve_fields(field_keys)
    header = [FIELD_INDEX[key][0] for key in keys]
    rows = [header]
    for record in sorted(records or [], key=base.sort_key):
        rows.append([record_value(record, key) for key in keys])
    spec = {
        'widths': [FIELD_INDEX[key][2] for key in keys],
        'formats': dict((index, FIELD_INDEX[key][1])
                        for index, key in enumerate(keys, start=1)),
        'freeze': 1,
    }
    return rows, spec


def build_summary(grouped):
    """``(rows, spec)`` totalling每個面積計畫 by level.

    ``grouped`` is ``[(scheme_name, [records])]``. Totals are computed from the
    same records the detail sheets use, so the two can never disagree.
    """
    rows = [[u'面積計畫', u'樓層', u'面積數', u'合計面積(m²)']]
    grand_count = 0
    grand_area = 0.0
    for scheme_name, records in grouped or []:
        levels = {}
        order = []
        for record in records or []:
            level = _text(record.get('level')) or u'(未知樓層)'
            if level not in levels:
                levels[level] = {'count': 0, 'area': 0.0,
                                 'elevation': _number(
                                     record.get('level_elevation'))}
                order.append(level)
            levels[level]['count'] += 1
            levels[level]['area'] += (_number(record.get('area_sqft'))
                                      * SQ_FT_TO_SQ_M)
        order.sort(key=lambda name: levels[name]['elevation'])
        scheme_count = 0
        scheme_area = 0.0
        for level in order:
            entry = levels[level]
            rows.append([_text(scheme_name), level, entry['count'],
                         _round(entry['area'])])
            scheme_count += entry['count']
            scheme_area += entry['area']
        rows.append([_text(scheme_name), u'小計', scheme_count,
                     _round(scheme_area)])
        grand_count += scheme_count
        grand_area += scheme_area
    rows.append([u'總計', u'', grand_count, _round(grand_area)])
    spec = {
        'widths': [22, 14, 10, 16],
        'formats': {3: xlsx_xml.STYLE_INT, 4: xlsx_xml.STYLE_DECIMAL},
        'freeze': 1,
    }
    return rows, spec


def build_workbook(grouped, field_keys=None):
    """``[(sheet_name, rows, spec)]`` — summary first, then one sheet each."""
    grouped = [item for item in grouped or []]
    sheets = []
    summary_rows, summary_spec = build_summary(grouped)
    sheets.append((SUMMARY_SHEET, summary_rows, summary_spec))
    used = [SUMMARY_SHEET]
    for scheme_name, records in grouped:
        name = xlsx_xml.safe_sheet_name(scheme_name, used)
        used.append(name)
        rows, spec = build_sheet(records, field_keys)
        sheets.append((name, rows, spec))
    return sheets


def export_lines(grouped, field_keys=None, path=u''):
    keys = resolve_fields(field_keys)
    total = sum(len(records or []) for unused, records in grouped or [])
    lines = [
        u'面積計畫：{} 個'.format(len(grouped or [])),
        u'面積合計：{} 個'.format(total),
        u'欄位：{}'.format(u'、'.join(
            FIELD_INDEX[key][0] for key in keys)),
    ]
    for scheme_name, records in grouped or []:
        lines.append(u'　{}：{} 個'.format(_text(scheme_name),
                                        len(records or [])))
    if path:
        lines.append(u'')
        lines.append(u'輸出：{}'.format(path))
    return u'\n'.join(lines)
