# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""門窗編號補空值（JAC 10.09）— writes, so it runs dry-run first.

Fills *blank* 門窗編號 only. A 編號 that already has a value is never touched:
overwriting one is renumbering, which carries different risks and belongs in a
different button.

Contract, same as the other writing buttons here: preview everything in the
output window, confirm, then one Transaction that rolls back completely if any
single write is refused. Nothing partial is left in the model.
"""

__title__ = u'門窗編號\n補空值'
__author__ = 'RevitMCP'

from Autodesk.Revit import DB
from pyrevit import forms, revit, script

import blank_mark_fill_logic as logic
import door_window_marks as marks


TITLE = u'門窗編號補空值'

# 類型名稱 is missing on purpose: it is not a writable parameter, so it can be
# a *source* of a 編號 but never a destination.
TARGETS = (
    (u'註記 Mark（逐樘各自的編號）', marks.SOURCE_INSTANCE_MARK),
    (u'類型註記 Type Mark（同型號共用，門窗表最常用）', marks.SOURCE_TYPE_MARK),
    (u'自訂參數名稱…', marks.SOURCE_CUSTOM),
)

SOURCES = (
    (u'由類型註記 Type Mark 帶入', logic.SOURCE_TYPE_MARK),
    (u'由類型名稱帶入', logic.SOURCE_TYPE_NAME),
    (u'由其他參數帶入…', logic.SOURCE_OTHER),
    (u'產生流水號…', logic.SOURCE_SEQUENCE),
    (u'填入固定文字…', logic.SOURCE_CONSTANT),
)

CURTAIN_CHOICES = (
    (u'排除帷幕牆上的門窗（帷幕X，建議）', True),
    (u'一併填入', False),
)

ALL_LEVELS = u'（全部樓層）'


def _pick(options, title):
    """SelectFromList single pick; returns the paired value, None on cancel."""
    labels = [label for label, unused in options]
    picked = forms.SelectFromList.show(labels, title=title, multiselect=False)
    if not picked:
        return None
    for label, value in options:
        if label == picked:
            return value
    return None


def _pick_levels(doc):
    """``None`` means every level — the documented default is 全部."""
    levels = marks.levels(doc)
    if not levels:
        return None
    labels = [ALL_LEVELS] + [marks.element_name(level) for level in levels]
    picked = forms.SelectFromList.show(
        labels, title=u'選擇填值範圍（可複選）', multiselect=True)
    if not picked:
        return None
    if ALL_LEVELS in picked:
        return None
    allowed = set()
    for level in levels:
        if marks.element_name(level) in picked:
            allowed.add(marks.id_value(level.Id))
    return allowed or None


def _ask_sequence():
    prefix = forms.ask_for_string(
        default=u'D', prompt=u'流水號前綴（可留空）', title=TITLE)
    if prefix is None:
        return None
    raw = forms.ask_for_string(
        default=u'1', prompt=u'起始號碼', title=TITLE)
    if not raw:
        return None
    try:
        start = int(raw.strip())
    except ValueError:
        forms.alert(u'起始號碼必須是整數。', title=TITLE)
        return None
    raw = forms.ask_for_string(
        default=u'0', prompt=u'補零位數（0 表示不補零，例如 3 會產生 001）',
        title=TITLE)
    if raw is None:
        return None
    try:
        pad = int((raw or u'0').strip())
    except ValueError:
        forms.alert(u'補零位數必須是整數。', title=TITLE)
        return None
    return {'prefix': prefix.strip(), 'start': start, 'pad': max(0, pad)}


def _annotate(records, target, target_parameter_name, source,
              source_parameter_name):
    """Attach the target's current value, its writability, and the source value.

    Reading the source through the same helper as the check button is what
    keeps 「空白」 meaning the same thing in both.
    """
    for record in records:
        instance = record['element']
        symbol = record['symbol']
        parameter, scope = marks.mark_parameter(
            instance, symbol, target, target_parameter_name)
        record['current'] = marks.parameter_text(parameter)
        record['writable'] = marks.parameter_status(parameter)
        record['scope'] = scope
        record['parameter'] = parameter
        record['type_mark'] = marks.read_mark(
            instance, symbol, marks.SOURCE_TYPE_MARK)
        if source == logic.SOURCE_OTHER:
            found, unused_scope = marks.lookup_parameter(
                instance, symbol, source_parameter_name)
            record['other'] = marks.parameter_text(found)
        else:
            record['other'] = u''
    return records


def _print_table(plan, target_label, source_label):
    output = script.get_output()
    output.print_md(u'## {} — 寫入 {}'.format(TITLE, target_label))
    output.print_md(u'取值方式：**{}**'.format(source_label))
    if plan['writes']:
        rows = []
        for row in plan['writes']:
            record = row['record']
            rows.append([
                output.linkify(record['element_id']),
                record['category'],
                record['family_name'],
                record['type_name'],
                record['level'],
                row['value'],
                u'{}'.format(row['instance_count']),
            ])
        output.print_table(
            table_data=rows,
            columns=[u'Element ID', u'類別', u'族群', u'類型', u'樓層',
                     u'新編號', u'影響樘數'])
    else:
        output.print_md(u'沒有可寫入的項目。')
    if plan['blocked']:
        output.print_md(u'### 阻擋不寫（{} 筆）'.format(len(plan['blocked'])))
        rows = []
        for row in plan['blocked']:
            record = row['record']
            rows.append([
                output.linkify(record['element_id']),
                record['category'],
                record['type_name'],
                record['level'],
                row.get('value') or u'',
                row['reason'],
            ])
        output.print_table(
            table_data=rows,
            columns=[u'Element ID', u'類別', u'類型', u'樓層', u'擬填值',
                     u'原因'])


class WarningSwallower(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, failures_accessor):
        for failure in failures_accessor.GetFailureMessages():
            if failure.GetSeverity() == DB.FailureSeverity.Warning:
                failures_accessor.DeleteWarning(failure)
        return DB.FailureProcessingResult.Continue


def _apply(doc, plan):
    """One Transaction; any refused write rolls the whole run back."""
    transaction = DB.Transaction(doc, TITLE)
    transaction.Start()
    options = transaction.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(WarningSwallower())
    transaction.SetFailureHandlingOptions(options)
    written = 0
    try:
        for row in plan['writes']:
            parameter = row['record'].get('parameter')
            if parameter is None:
                raise RuntimeError(
                    u'Element ID {} 的參數在預覽後消失了'.format(
                        row['record']['id']))
            if not parameter.Set(row['value']):
                raise RuntimeError(
                    u'Element ID {} 的參數拒絕寫入「{}」'.format(
                        row['record']['id'], row['value']))
            written += 1
        transaction.Commit()
        return written, None
    except Exception as error:
        transaction.RollBack()
        return 0, u'{}'.format(error)


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行門窗編號補空值。',
                    title=TITLE, exitscript=True)

    target = _pick(TARGETS, u'編號要寫進哪個參數？')
    if target is None:
        return
    target_parameter_name = u''
    if target == marks.SOURCE_CUSTOM:
        target_parameter_name = forms.ask_for_string(
            default=u'門窗編號',
            prompt=u'自訂參數名稱（實例或類型參數皆可，先找實例再找類型）',
            title=TITLE)
        if not target_parameter_name:
            return
        target_parameter_name = target_parameter_name.strip()
    target_label = target_parameter_name or marks.SOURCE_LABELS[target]

    source = _pick(SOURCES, u'空白的編號要填什麼？')
    if source is None:
        return
    source_parameter_name = u''
    options = {}
    if source == logic.SOURCE_OTHER:
        source_parameter_name = forms.ask_for_string(
            default=u'備註', prompt=u'要當作來源的參數名稱', title=TITLE)
        if not source_parameter_name:
            return
        source_parameter_name = source_parameter_name.strip()
    elif source == logic.SOURCE_CONSTANT:
        constant = forms.ask_for_string(
            default=u'', prompt=u'要填入的固定文字', title=TITLE)
        if not constant:
            return
        options['constant'] = constant.strip()
    elif source == logic.SOURCE_SEQUENCE:
        options = _ask_sequence()
        if options is None:
            return

    exclude_curtain = _pick(CURTAIN_CHOICES, u'帷幕牆上的門窗怎麼算？')
    if exclude_curtain is None:
        return

    allowed_level_ids = _pick_levels(doc)
    records = marks.collect(doc, allowed_level_ids)
    if not records:
        forms.alert(u'指定範圍內沒有門窗。', title=TITLE)
        return
    _annotate(records, target, target_parameter_name, source,
              source_parameter_name)

    # A custom parameter may be authored on the instance in one family and on
    # the type in another, so the scope comes from where it was actually found
    # rather than from the first record — which might be one that has neither.
    target_scope = logic.TARGET_INSTANCE
    for record in records:
        if record.get('parameter') is None:
            continue
        if record['scope'] == marks.SCOPE_TYPE:
            target_scope = logic.TARGET_TYPE
        break
    plan = logic.build_plan(records, target_scope=target_scope, source=source,
                            options=options, exclude_curtain=exclude_curtain)
    source_label = logic.SOURCE_LABELS[source]
    _print_table(plan, target_label, source_label)
    summary = logic.plan_lines(plan, target_label, exclude_curtain)

    if not plan['writes']:
        forms.alert(
            u'【dry-run 預覽】沒有可寫入的項目，模型未變更。\n\n{}\n\n'
            u'明細已列在 pyRevit 輸出視窗。'.format(summary), title=TITLE)
        return

    if logic.sequence_is_gapped(plan):
        forms.alert(
            u'【dry-run 預覽】\n\n{}\n\n'
            u'流水號模式有被阻擋的項目，寫下去會跳號。\n'
            u'本次不提供套用；請先修正輸出視窗裡列出的原因。'.format(summary),
            title=TITLE)
        return

    warning = u''
    if target_scope == logic.TARGET_TYPE:
        warning = (u'\n注意：寫入的是類型參數，同型號的每一樘都會一起變。\n')
    if not forms.alert(
            u'【dry-run 預覽】\n\n{}\n{}\n'
            u'明細已列在 pyRevit 輸出視窗。\n'
            u'確定要寫入目前模型嗎？'.format(summary, warning),
            title=TITLE, yes=True, no=True):
        return

    written, error = _apply(doc, plan)
    if error:
        forms.alert(
            u'寫入失敗，交易已完整回復，模型沒有留下部分編號。\n\n{}'
            .format(error), title=TITLE)
        return
    forms.alert(u'已寫入 {} 筆，影響 {} 樘門窗。'.format(
        written, plan['affected_instances']), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
