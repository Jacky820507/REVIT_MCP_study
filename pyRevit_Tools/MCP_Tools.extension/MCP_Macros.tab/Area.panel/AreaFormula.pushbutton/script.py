# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""面積計算式列式（JAC 01.04 階段二）— read-only.

Produces the 面積計算表 expression Taiwanese permit review asks for: each
sub-area written as one simple shape, grouped by 戶別 and 分類, numbered
continuously per category, and summed —

    A1 居室
    (H1) = 2.80 x 4.50 = 12.60 m²
    (H2) = 10.50 x 2.30 = 24.15 m²
    (H1) + (H2) = 36.75 m²

Reads only. Nothing is written to the model; the output goes to the pyRevit
window and an .xlsx.

An expression is only printed when its own arithmetic reproduces **Revit's**
area for that region. A confidently wrong 2.80 x 4.50 passes review; an honest
「無法列式」 gets fixed. Rows that fail keep their area and say why.

The splitting itself is not done here — the sub-areas are the Areas the user
drew with 區域線 (see 區域線重新生成). This button reads what is there.
"""

__title__ = u'面積\n計算式'
__author__ = 'RevitMCP'

import os

from pyrevit import forms, revit, script

import area_formula_logic as logic
import area_scheme_sources as sources
import mcp_window as ui
import mcp_window_logic as uilogic
import xlsx_writer
import xlsx_xml


TITLE = u'面積計算式'
NONE_LABEL = u'（不使用）'
ALL_LEVELS = u'（全部樓層）'

SHEET_DETAIL = u'計算式明細'
SHEET_SOURCE = u'列式全文'


def _safe_filename(text):
    return u''.join(u'_' if c in u'\\/:*?"<>|' else c
                    for c in u'{}'.format(text or u'')).strip() or u'Area'


def _default_name(doc):
    try:
        title = os.path.splitext(os.path.basename(doc.PathName))[0]
    except Exception:
        title = u''
    return u'{}_面積計算式.xlsx'.format(_safe_filename(title or u'Revit'))


def _parameter_options(doc, schemes, levels):
    """面積上可讀的文字參數。取任何一個已放置的面積來問即可。"""
    for scheme in schemes:
        for row in sources.collect_areas(
                doc, scheme_id=sources.id_value(scheme.Id), levels=levels):
            if row.get('placed') and row.get('element') is not None:
                return list(sources.readable_parameters(row['element']))
    return []


def _build_spec(doc, schemes, levels, parameters):
    fields = [
        uilogic.section(u'範圍'),
        uilogic.choice('scheme', u'面積計畫',
                       [(sources.scheme_label(scheme), scheme)
                        for scheme in schemes]),
        uilogic.multichoice(
            'levels', u'樓層（不勾就是全部）',
            sorted([(entry[0], level_id) for level_id, entry in levels.items()],
                   key=lambda item: levels[item[1]][1]),
            help=u'一個都不勾代表全部樓層。'),

        uilogic.section(u'欄位對應',
                        u'戶別與分類決定計算式怎麼分組，因此不能略過；'
                        u'棟別可以留白。'),
        uilogic.choice('unit', u'「戶別」是哪個參數（例如 A1、A2）',
                       parameters),
        uilogic.choice('category', u'「分類」是哪個參數（居室／陽台／樓梯間…）',
                       parameters),
        uilogic.choice('building', u'「棟別」是哪個參數（可略過）',
                       [(NONE_LABEL, u'')] + list(parameters), default=u''),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'依戶別與分類產生可稽核的面積計算式',
        badge=uilogic.BADGE_READONLY,
        run_label=u'產生並選擇存檔位置',
        footnote=u'唯讀，不寫入模型。計算式同時列在 pyRevit 輸出視窗。',
        width=960, height=740)


def _print_report(report, scheme_label, params):
    output = script.get_output()
    output.print_md(u'## {} — {}'.format(TITLE, scheme_label))
    output.print_md(u'戶別：`{}`　分類：`{}`　棟別：`{}`'.format(
        params.get('unit') or u'(未指定)',
        params.get('category') or u'(未指定)',
        params.get('building') or u'(未指定)'))

    output.print_md(u'### 代號對照')
    output.print_table(
        table_data=[[name, letter]
                    for name, letter in sorted(report['letters'].items())],
        columns=[u'分類', u'代號字母'])

    output.print_md(u'### 計算式')
    for group in report['groups']:
        output.print_md(u'```\n{}\n```'.format(
            u'\n'.join(logic.group_lines(group))))

    if report['unformulated']:
        output.print_md(u'### 無法列式（{} 個）'.format(
            len(report['unformulated'])))
        output.print_table(
            table_data=[[
                output.linkify(item['element_id']),
                item['code'], item['unit'], item['category'],
                u'{:.2f}'.format(item['actual_m2']),
                u'{}'.format(item['vertices']),
                item['reason'],
            ] for item in report['unformulated']],
            columns=[u'Element ID', u'代號', u'戶別', u'分類',
                     u'面積(m²)', u'邊數', u'原因'])


def _workbook(report):
    detail = logic.export_rows(report)
    detail_spec = {
        'widths': [12, 16, 10, 12, 30, 14, 14, 30],
        'formats': {6: xlsx_xml.STYLE_DECIMAL, 7: xlsx_xml.STYLE_DECIMAL},
        'freeze': 1,
    }
    # The second sheet is the block exactly as it should read on the drawing,
    # so it can be pasted into the 面積計算表 without reformatting.
    text_rows = [[u'列式']]
    for group in report['groups']:
        for line in logic.group_lines(group):
            text_rows.append([line])
        text_rows.append([u''])
    return [(SHEET_DETAIL, detail, detail_spec),
            (SHEET_SOURCE, text_rows, {'widths': [70], 'freeze': 1})]


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再產生面積計算式。',
                    title=TITLE, exitscript=True)

    schemes = sources.area_schemes(doc)
    if not schemes:
        forms.alert(u'這個專案沒有任何面積計畫（Area Scheme）。', title=TITLE)
        return
    levels = sources.level_index(doc)
    parameters = _parameter_options(doc, schemes, levels)
    if not parameters:
        forms.alert(u'讀不到面積上的任何文字參數。', title=TITLE)
        return

    values = ui.ask(_build_spec(doc, schemes, levels, parameters))
    if values is None:
        return

    scheme = values['scheme']
    allowed = set(values['levels']) or None
    unit_param = values['unit']
    category_param = values['category']
    building_param = values['building']

    records = sources.collect_areas(
        doc, scheme_id=sources.id_value(scheme.Id), levels=levels)
    if allowed is not None:
        records = [row for row in records if row['level_id'] in allowed]
    records = [row for row in records if row['placed']]
    if not records:
        forms.alert(u'選定範圍內沒有已放置的面積。', title=TITLE)
        return

    prepared = []
    for row in records:
        item = dict(row)
        item['unit'] = sources.read_named_parameter(row['element'],
                                                    unit_param)
        item['category'] = sources.read_named_parameter(row['element'],
                                                        category_param)
        item['building'] = sources.read_named_parameter(row['element'],
                                                        building_param)
        item['area_m2'] = row['area_sqft'] * sources.SQ_FT_TO_SQ_M
        prepared.append(item)

    report = logic.build_report(prepared)
    params = {'unit': unit_param, 'category': category_param,
              'building': building_param}
    _print_report(report, sources.scheme_label(scheme), params)

    summary = logic.report_summary(report)
    if not forms.alert(
            u'{}\n\n計算式已列在 pyRevit 輸出視窗。\n'
            u'要匯出成 Excel 嗎？'.format(summary),
            title=TITLE, yes=True, no=True):
        return

    path = forms.save_file(file_ext='xlsx', default_name=_default_name(doc))
    if not path:
        return
    try:
        xlsx_writer.write_workbook(path, _workbook(report))
    except Exception as error:
        forms.alert(u'寫入 Excel 失敗：\n\n{}'.format(error), title=TITLE)
        return
    forms.alert(u'{}\n\n已輸出：{}'.format(summary, path), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
