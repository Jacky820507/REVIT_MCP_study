# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""門窗編號重複檢查（JAC 10.08）— read-only.

Reads a 編號 off every door and window in the host model, folds away the
typo-level differences (全形、大小寫、空白), and reports the 編號 that collide.
Nothing is written; the only side effect offered is selecting the offenders so
they can be fixed by hand.
"""

__title__ = u'門窗編號\n重複'
__author__ = 'RevitMCP'

from Autodesk.Revit import DB
from pyrevit import forms, revit, script
from System.Collections.Generic import List

import door_window_marks as marks
import duplicate_mark_logic as logic
import mcp_window as ui
import mcp_window_logic as uilogic


TITLE = u'門窗編號重複'

SOURCES = (
    (u'類型註記 Type Mark（門窗表最常用）', marks.SOURCE_TYPE_MARK),
    (u'註記 Mark（逐樘標號時用）', marks.SOURCE_INSTANCE_MARK),
    (u'類型名稱', marks.SOURCE_TYPE_NAME),
    (u'自訂參數名稱…', marks.SOURCE_CUSTOM),
)

MODES = (
    (u'同一編號用在不同類型（門窗表重複，建議）', logic.DISTINCT_BY_TYPE),
    (u'同一編號用在多個元件（嚴格逐樘唯一）', logic.DISTINCT_BY_INSTANCE),
)

# 帷幕嵌板換成門窗族群時會沿用嵌板命名，編號常空白或重覆；那跟門窗表的編號
# 衝突是兩回事，所以 JAC 這個檢核標示為「帷幕X」。
CURTAIN_CHOICES = (
    (u'排除帷幕牆上的門窗（帷幕X，建議）', True),
    (u'一併檢查', False),
)

def _build_spec(doc):
    """整份視窗規格。樓層一個都不勾＝全部，這是原本 ALL_LEVELS 哨符的意思，
    現在由 multichoice 本身表達，不必再發明一個假選項。"""
    level_options = [(marks.element_name(level), marks.id_value(level.Id))
                     for level in marks.levels(doc)]

    fields = [
        uilogic.section(u'編號來源'),
        uilogic.choice('source', u'編號讀哪個參數', SOURCES,
                       default=marks.SOURCE_TYPE_MARK),
        uilogic.text('parameter_name', u'自訂參數名稱',
                     default=u'門窗編號', required=True,
                     enabled_when=('source', marks.SOURCE_CUSTOM),
                     help=u'實例或類型參數皆可，先找實例再找類型。'),

        uilogic.section(u'判定方式'),
        uilogic.choice('mode', u'什麼情況算重複', MODES,
                       default=logic.DISTINCT_BY_TYPE),
        uilogic.choice('curtain', u'帷幕牆上的門窗怎麼算', CURTAIN_CHOICES,
                       default=True,
                       help=u'帷幕嵌板換成門窗族群時會沿用嵌板命名，編號常空白'
                            u'或重覆；那跟門窗表的編號衝突是兩回事，'
                            u'所以 JAC 這個檢核標示為「帷幕X」。'),

        uilogic.section(u'檢查範圍'),
        uilogic.multichoice('levels', u'樓層（不勾就是全部）', level_options,
                            help=u'一個都不勾代表全部樓層。'),
    ]

    return uilogic.spec(
        TITLE, fields,
        subtitle=u'找出同一個編號被用在不同類型或不同元件上的門窗',
        badge=uilogic.BADGE_READONLY,
        run_label=u'開始檢查',
        secondary_label=u'選取重複的門窗',
        footnote=u'唯讀。完整明細列在 pyRevit 輸出視窗，可點擊跳到元素。',
        width=960, height=720)


def _print_table(report, parameter_label):
    output = script.get_output()
    output.print_md(u'## {} — {}'.format(TITLE, parameter_label))
    output.print_md(u'判定方式：**{}**'.format(
        logic.MODE_LABELS[report['mode']]))
    if not report['groups']:
        output.print_md(u'沒有重複編號。')
    else:
        rows = []
        for group in report['groups']:
            for record in group['records']:
                rows.append([
                    group['key'],
                    output.linkify(record['element_id']),
                    record['category'],
                    record['family_name'],
                    record['type_name'],
                    record['level'],
                    record['mark'],
                ])
        output.print_table(
            table_data=rows,
            columns=[u'編號', u'Element ID', u'類別', u'族群', u'類型',
                     u'樓層', u'原始編號'])
    if report['blank']:
        output.print_md(u'### 編號空白（{} 樘）'.format(len(report['blank'])))
        output.print_md(u'可用「門窗編號補空值」按鈕批次補上。')
        output.print_table(
            table_data=[[output.linkify(record['element_id']),
                         record['category'], record['family_name'],
                         record['type_name'], record['level']]
                        for record in report['blank']],
            columns=[u'Element ID', u'類別', u'族群', u'類型', u'樓層'])
    if report['excluded_curtain']:
        output.print_md(u'### 已排除的帷幕牆門窗（{} 樘）'.format(
            len(report['excluded_curtain'])))


class _Runner(object):
    """留住最後一次的報告，關窗後才知道要不要選取那些門窗。"""

    def __init__(self, doc):
        self.doc = doc
        self.report = None

    def __call__(self, values, window):
        source = values['source']
        parameter_name = u''
        if source == marks.SOURCE_CUSTOM:
            parameter_name = (values.get('parameter_name') or u'').strip()
        parameter_label = parameter_name or marks.SOURCE_LABELS[source]

        allowed = set(values.get('levels') or ()) or None
        records = marks.collect(self.doc, allowed)
        if not records:
            self.report = None
            window.status(u'指定範圍內沒有門窗。', 'warning')
            return None
        for record in records:
            record['mark'] = marks.read_mark(
                record['element'], record['symbol'], source, parameter_name)

        report = logic.analyze(records, distinct_by=values['mode'],
                               exclude_curtain=values['curtain'])
        self.report = report
        _print_table(report, parameter_label)
        summary = logic.report_lines(report, parameter_label,
                                     values['curtain'])
        window.status(summary,
                      'danger' if report['groups'] else 'success')

        rows = []
        for group in report['groups']:
            for record in group['records']:
                rows.append([group['key'], record['category'],
                             record['family_name'], record['type_name'],
                             record['level'], record['mark']])
        return uilogic.result(
            summary_lines=[summary],
            columns=[u'編號', u'類別', u'族群', u'類型', u'樓層', u'原始編號'],
            rows=rows)


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行門窗編號重複檢查。',
                    title=TITLE, exitscript=True)

    runner = _Runner(doc)
    values, unused = ui.run(_build_spec(doc), runner)
    if values is None or runner.report is None:
        return

    if values.get('__secondary__') and runner.report['groups']:
        ids = List[DB.ElementId]()
        for value in logic.flagged_ids(runner.report):
            ids.Add(DB.ElementId(int(value)))
        revit.uidoc.Selection.SetElementIds(ids)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
