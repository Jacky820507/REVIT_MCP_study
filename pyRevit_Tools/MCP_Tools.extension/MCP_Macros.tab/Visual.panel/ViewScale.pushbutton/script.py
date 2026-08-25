# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""視圖／圖紙比例管理（JAC 02.06 + 02.07）.

Two JAC entries, one operation: a sheet has no scale of its own, so 「圖紙比例」
is the scale of the views placed on it. The button therefore lets the scope be
named either way — pick sheets, or pick views — and both land on ``View.Scale``.

Runs in two modes. 檢視 is read-only and answers 「這批圖現在各是什麼比例」.
批次設定 writes, and follows the same contract as the other writing buttons
here: dry-run preview, confirm, one Transaction that rolls back completely.
"""

__title__ = u'視圖比例\n管理'
__author__ = 'RevitMCP'

from Autodesk.Revit import DB
from pyrevit import forms, revit, script

import mcp_window as ui
import mcp_window_logic as uilogic
import view_scale_logic as logic


TITLE = u'視圖比例管理'

SCOPE_SHEETS = 'sheets'
SCOPE_VIEWS = 'views'

SCOPES = (
    (u'選圖紙（該圖紙上的所有視圖）', SCOPE_SHEETS),
    (u'選視圖（直接指定視圖）', SCOPE_VIEWS),
)

MODE_SURVEY = 'survey'
MODE_SET = 'set'

MODES = (
    (u'只檢視目前比例（不改模型）', MODE_SURVEY),
    (u'批次設定為指定比例', MODE_SET),
)

# Sheets and schedules have no scale; legends and drafting views do, so they
# are deliberately not excluded here — the parameter check decides.
SKIP_VIEW_TYPES = ('DrawingSheet', 'ProjectBrowser', 'SystemBrowser',
                   'Internal', 'Undefined')


def _id_value(element_id):
    if element_id is None:
        return -1
    # Revit 2025+ exposes .Value; 2020-2024 only .IntegerValue.
    try:
        return int(element_id.Value)
    except Exception:
        try:
            return int(element_id.IntegerValue)
        except Exception:
            return -1


def _element_name(element):
    if element is None:
        return u''
    try:
        return DB.Element.Name.GetValue(element) or u''
    except Exception:
        try:
            return element.Name or u''
        except Exception:
            return u''


def _view_type_name(view):
    try:
        return u'{}'.format(view.ViewType)
    except Exception:
        return u''


def _scale_parameter(view):
    built_in = getattr(DB.BuiltInParameter, 'VIEW_SCALE', None)
    if built_in is None:
        return None
    try:
        return view.get_Parameter(built_in)
    except Exception:
        return None


def _template_name(doc, view):
    try:
        template_id = view.ViewTemplateId
    except Exception:
        return u''
    if _id_value(template_id) <= 0:
        return u''
    return _element_name(doc.GetElement(template_id))


def _writable_status(doc, view, parameter):
    """Let Revit answer whether the scale can be set, then explain why not.

    Asking the parameter rather than reasoning about view kinds keeps this
    correct for the cases that are easy to get wrong — view templates,
    dependent views, and view types that simply have no scale.
    """
    if parameter is None:
        return logic.BLOCK_NO_PARAMETER, u''
    template = _template_name(doc, view)
    try:
        read_only = bool(parameter.IsReadOnly)
    except Exception:
        read_only = True
    if read_only:
        if template:
            return (u'{}（{}）'.format(logic.BLOCK_TEMPLATE, template),
                    template)
        return logic.BLOCK_READONLY, template
    return logic.STATUS_OK, template


def _sheet_numbers(doc, view):
    """Sheet numbers this view is placed on, via the view's own parameter."""
    numbers = []
    built_in = getattr(DB.BuiltInParameter, 'VIEWER_SHEET_NUMBER', None)
    if built_in is None:
        return numbers
    try:
        parameter = view.get_Parameter(built_in)
        value = parameter.AsString() if parameter else None
    except Exception:
        value = None
    if value:
        numbers.append(value.strip())
    return numbers


def _record(doc, view, sheet_numbers=None):
    parameter = _scale_parameter(view)
    status, template = _writable_status(doc, view, parameter)
    scale = 0
    try:
        scale = int(view.Scale)
    except Exception:
        scale = 0
    return {
        'id': _id_value(view.Id),
        'element_id': view.Id,
        'view': view,
        'parameter': parameter,
        'name': _element_name(view),
        'view_type': _view_type_name(view),
        'scale': scale,
        'writable': status,
        'template': template,
        'sheet_numbers': list(sheet_numbers or _sheet_numbers(doc, view)),
    }


def _sheet_options(doc):
    sheets = list(DB.FilteredElementCollector(doc)
                  .OfClass(DB.ViewSheet)
                  .WhereElementIsNotElementType()
                  .ToElements())
    sheets = [sheet for sheet in sheets if not sheet.IsTemplate]
    sheets.sort(key=lambda sheet: u'{}'.format(sheet.SheetNumber))
    return [(u'{} - {}'.format(sheet.SheetNumber, _element_name(sheet)), sheet)
            for sheet in sheets]


def _scalable_views(doc):
    views = []
    for view in (DB.FilteredElementCollector(doc)
                 .OfClass(DB.View)
                 .WhereElementIsNotElementType()):
        try:
            if view.IsTemplate:
                continue
        except Exception:
            continue
        if _view_type_name(view) in SKIP_VIEW_TYPES:
            continue
        if _scale_parameter(view) is None:
            continue
        views.append(view)
    return views


def _view_options(doc):
    rows = [(u'{}｜{}　({})'.format(
        _view_type_name(view), _element_name(view),
        logic.scale_label(view.Scale)), view)
        for view in _scalable_views(doc)]
    rows.sort(key=lambda item: item[0])
    return rows


def _records_from_sheets(doc, sheets):
    """一個視圖可能出現在多張圖紙上，但它只有一個比例——因此以視圖 id 為鍵，
    計畫裡不會出現同一個視圖兩次。"""
    records = {}
    for sheet in sheets or []:
        number = u'{}'.format(sheet.SheetNumber)
        try:
            view_ids = sheet.GetAllPlacedViews()
        except Exception:
            view_ids = []
        for view_id in view_ids:
            view = doc.GetElement(view_id)
            if view is None:
                continue
            key = _id_value(view.Id)
            if key in records:
                if number not in records[key]['sheet_numbers']:
                    records[key]['sheet_numbers'].append(number)
                continue
            records[key] = _record(doc, view, [number])
    return list(records.values())


def _records_from_views(doc, views):
    return [_record(doc, view) for view in views or []]


def _build_spec(sheet_options, view_options):
    fields = [
        uilogic.section(u'範圍'),
        uilogic.choice('scope', u'要用什麼方式指定範圍', SCOPES,
                       default=SCOPE_SHEETS),
        uilogic.multichoice('sheets', u'圖紙（該圖紙上的所有視圖）',
                            sheet_options, required=True,
                            enabled_when=('scope', SCOPE_SHEETS)),
        uilogic.multichoice('views', u'視圖', view_options, required=True,
                            enabled_when=('scope', SCOPE_VIEWS)),

        uilogic.section(u'動作'),
        uilogic.choice('mode', u'要做什麼', MODES, default=MODE_SURVEY),
        uilogic.text('scale', u'目標比例', default=u'100', required=True,
                     enabled_when=('mode', MODE_SET),
                     help=u'可輸入 100 或 1:100。'),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'盤點或批次設定視圖比例，寫入前先 dry-run 預覽',
        badge=uilogic.BADGE_WRITE,
        run_label=u'執行',
        footnote=u'「只檢視目前比例」不會動到模型；設定比例會先預覽並由你確認。',
        width=980, height=760)


def _print_survey(records):
    output = script.get_output()
    output.print_md(u'## {} — 目前比例'.format(TITLE))
    rows = []
    for record in sorted(records, key=lambda item: (
            -(item['scale'] or 0), item['name'])):
        rows.append([
            output.linkify(record['element_id']),
            logic.scale_label(record['scale']),
            record['view_type'],
            record['name'],
            u'、'.join(record['sheet_numbers']),
            record['template'],
            u'' if record['writable'] == logic.STATUS_OK
            else record['writable'],
        ])
    output.print_table(
        table_data=rows,
        columns=[u'Element ID', u'比例', u'視圖類型', u'視圖名稱', u'圖紙',
                 u'視圖樣板', u'不可設定原因'])


def _print_plan(plan):
    output = script.get_output()
    output.print_md(u'## {} — 設為 {}'.format(
        TITLE, logic.scale_label(plan['target_scale'])))
    if plan['writes']:
        output.print_table(
            table_data=[[
                output.linkify(row['record']['element_id']),
                row['record']['view_type'],
                row['record']['name'],
                logic.scale_label(row['old']),
                logic.scale_label(row['new']),
                u'、'.join(row['record']['sheet_numbers']),
            ] for row in plan['writes']],
            columns=[u'Element ID', u'視圖類型', u'視圖名稱', u'原比例',
                     u'新比例', u'圖紙'])
    else:
        output.print_md(u'沒有需要變更的視圖。')
    if plan['blocked']:
        output.print_md(u'### 阻擋不改（{} 個）'.format(len(plan['blocked'])))
        output.print_table(
            table_data=[[
                output.linkify(row['record']['element_id']),
                row['record']['view_type'],
                row['record']['name'],
                logic.scale_label(row['record']['scale']),
                row['reason'],
            ] for row in plan['blocked']],
            columns=[u'Element ID', u'視圖類型', u'視圖名稱', u'目前比例',
                     u'原因'])


class WarningSwallower(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, failures_accessor):
        for failure in failures_accessor.GetFailureMessages():
            if failure.GetSeverity() == DB.FailureSeverity.Warning:
                failures_accessor.DeleteWarning(failure)
        return DB.FailureProcessingResult.Continue


def _apply(doc, plan):
    transaction = DB.Transaction(doc, TITLE)
    transaction.Start()
    options = transaction.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(WarningSwallower())
    transaction.SetFailureHandlingOptions(options)
    written = 0
    try:
        for row in plan['writes']:
            row['record']['view'].Scale = int(row['new'])
            written += 1
        transaction.Commit()
        return written, None
    except Exception as error:
        transaction.RollBack()
        return 0, u'{}'.format(error)


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行視圖比例管理。',
                    title=TITLE, exitscript=True)

    sheet_options = _sheet_options(doc)
    view_options = _view_options(doc)
    if not sheet_options and not view_options:
        forms.alert(u'專案裡沒有圖紙，也沒有可設定比例的視圖。', title=TITLE)
        return

    values = ui.ask(_build_spec(sheet_options, view_options))
    if values is None:
        return

    if values['scope'] == SCOPE_SHEETS:
        records = _records_from_sheets(doc, values['sheets'])
    else:
        records = _records_from_views(doc, values['views'])
    if not records:
        forms.alert(u'選定的範圍裡沒有可設定比例的視圖。', title=TITLE)
        return
    mode = values['mode']

    if mode == MODE_SURVEY:
        _print_survey(records)
        forms.alert(u'{}\n\n明細已列在 pyRevit 輸出視窗。'.format(
            logic.survey_lines(records)), title=TITLE)
        return

    try:
        plan = logic.build_plan(records, values['scale'])
    except ValueError as error:
        forms.alert(u'{}'.format(error), title=TITLE)
        return

    _print_plan(plan)
    summary = logic.plan_lines(plan)
    if not plan['writes']:
        forms.alert(
            u'【dry-run 預覽】沒有需要變更的視圖，模型未變更。\n\n{}\n\n'
            u'明細已列在 pyRevit 輸出視窗。'.format(summary), title=TITLE)
        return

    if not forms.alert(
            u'【dry-run 預覽】\n\n{}\n\n'
            u'明細已列在 pyRevit 輸出視窗。\n'
            u'確定要寫入目前模型嗎？'.format(summary),
            title=TITLE, yes=True, no=True):
        return

    written, error = _apply(doc, plan)
    if error:
        forms.alert(
            u'寫入失敗，交易已完整回復，模型沒有留下部分變更。\n\n{}'
            .format(error), title=TITLE)
        return

    # domain/viewport-type-scale-sync.md keys the viewport title type off the
    # placed view's scale, so a scale change leaves those titles stale.
    sheets = logic.sheets_needing_viewport_resync(plan)
    tail = u''
    if sheets:
        tail = (u'\n\n提醒：以下圖紙的視埠標題類型是依比例命名的，'
                u'請重新執行「依視圖比例同步視埠類型」：\n{}'.format(
                    u'、'.join(sheets[:15])
                    + (u' …' if len(sheets) > 15 else u'')))
    forms.alert(u'已將 {} 個視圖設為 {}。{}'.format(
        written, logic.scale_label(plan['target_scale']), tail), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
