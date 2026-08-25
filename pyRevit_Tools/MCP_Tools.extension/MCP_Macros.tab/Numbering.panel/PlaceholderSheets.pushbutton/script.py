# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""明細表選取範圍生成圖紙（JAC 02.03）.

Rows added to a Sheet List schedule become **placeholder sheets**: real
``ViewSheet`` elements carrying a number and a name, but with no titleblock and
no ability to hold a viewport. Revit converts them one at a time by right-click,
so a drawing register of eighty rows costs eighty trips through a dialog. This
does the selected range in one batch.

On 「選取範圍」: the API has no way to read a schedule's highlighted cells.
``Selection.GetElementIds()`` returns selected *elements* and
``TableSectionData`` reads any cell by index, but the highlighted range itself
is not exposed. So the scope is offered two ways — whatever the current
selection contains, or a picker over every placeholder in the project — and
neither path depends on undocumented schedule behaviour. If selecting schedule
rows does put the sheets in the selection, the first option simply works.

One titleblock per run, by design: a register is converted 「所有 A- 開頭的用
A1 圖框」 then 「所有 S- 開頭的用 A3」, and the picker groups by prefix so that
is two quick runs rather than one mode with a mapping table to maintain.

Conversion runs in a single Transaction. If any sheet fails, none convert.
"""

__title__ = u'佔位圖紙\n轉正式圖紙'
__author__ = 'RevitMCP'

from Autodesk.Revit import DB
from pyrevit import forms, revit, script

import placeholder_sheet_logic as logic


TITLE = u'佔位圖紙轉正式圖紙'


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


def _sheet_record(sheet):
    try:
        is_placeholder = bool(sheet.IsPlaceholder)
    except Exception:
        is_placeholder = False
    try:
        number = sheet.SheetNumber or u''
    except Exception:
        number = u''
    return {
        'id': _id_value(sheet.Id),
        'element_id': sheet.Id,
        'number': number,
        'name': _element_name(sheet),
        'is_sheet': True,
        'is_placeholder': is_placeholder,
    }


def _all_placeholders(doc):
    try:
        sheets = list(DB.FilteredElementCollector(doc)
                      .OfClass(DB.ViewSheet)
                      .WhereElementIsNotElementType()
                      .ToElements())
    except Exception:
        return []
    records = []
    for sheet in sheets:
        record = _sheet_record(sheet)
        if record['is_placeholder']:
            records.append(record)
    return records


def _selected_records(doc):
    """Whatever is selected right now, described so the plan can judge it."""
    try:
        ids = list(revit.uidoc.Selection.GetElementIds())
    except Exception:
        return []
    records = []
    for element_id in ids:
        try:
            element = doc.GetElement(element_id)
        except Exception:
            element = None
        if element is None:
            continue
        if isinstance(element, DB.ViewSheet):
            records.append(_sheet_record(element))
        else:
            records.append({
                'id': _id_value(element.Id),
                'element_id': element.Id,
                'number': u'',
                'name': _element_name(element),
                'is_sheet': False,
                'is_placeholder': False,
            })
    return records


def _titleblocks(doc):
    """``[(label, FamilySymbol)]`` of every loaded titleblock type."""
    category = getattr(DB.BuiltInCategory, 'OST_TitleBlocks', None)
    if category is None:
        return []
    try:
        symbols = list(DB.FilteredElementCollector(doc)
                       .OfCategory(category)
                       .WhereElementIsElementType()
                       .ToElements())
    except Exception:
        return []
    options = []
    for symbol in symbols:
        # FamilyName rather than Family.Name: same answer without fetching the
        # Family element, and confirmed present in 2020 and 2024 alike.
        try:
            family = symbol.FamilyName or u''
        except Exception:
            family = u''
        label = u'{}：{}'.format(family, _element_name(symbol)) if family \
            else _element_name(symbol)
        options.append((label, symbol))
    options.sort(key=lambda entry: entry[0])
    return options


def _pick_scope(doc):
    """``[record]`` to consider, or ``None`` on cancel."""
    placeholders = _all_placeholders(doc)
    if not placeholders:
        forms.alert(
            u'這個專案沒有佔位圖紙（placeholder sheet）。\n\n'
            u'佔位圖紙是在「圖紙清單」明細表裡新增列時產生的；'
            u'請先在明細表新增列，再回來執行本按鈕。', title=TITLE)
        return None

    selected = _selected_records(doc)
    selected_placeholders = [record for record in selected
                             if record['is_placeholder']]
    choices = []
    if selected_placeholders:
        choices.append((u'使用目前選取的 {} 張佔位圖紙'.format(
            len(selected_placeholders)), 'selection'))
    choices.append((u'從全部 {} 張佔位圖紙中挑選'.format(len(placeholders)),
                    'all'))
    mode = _pick(choices, u'要轉換哪些佔位圖紙？')
    if mode is None:
        return None
    if mode == 'selection':
        return selected

    labels = {}
    order = []
    for group in logic.group_by_prefix(placeholders):
        for record in group['records']:
            label = u'{}　{}　{}'.format(
                group['prefix'],
                record['number'] or u'(無圖號)',
                record['name'] or u'(無圖名)')
            # Sheet numbers are unique in Revit, so the label is too — but
            # guard anyway rather than silently dropping a row.
            while label in labels:
                label += u' '
            labels[label] = record
            order.append(label)
    picked = forms.SelectFromList.show(
        order, title=u'選擇要轉換的佔位圖紙（可複選）', multiselect=True)
    if not picked:
        return None
    return [labels[label] for label in picked if label in labels]


def _print_plan(plan, titleblock_label):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    output.print_md(u'圖框：**{}**'.format(titleblock_label))

    if plan['convert']:
        output.print_md(u'### 將轉換（{} 張）'.format(plan['count']))
        output.print_table(
            table_data=[[output.linkify(record['element_id']),
                         logic.sheet_prefix(record['number']),
                         record['number'] or u'(無圖號)',
                         record['name'] or u'(無圖名)']
                        for record in plan['convert']],
            columns=[u'Element ID', u'前綴', u'圖號', u'圖名'])

    if plan['warnings']:
        output.print_md(u'### 注意')
        output.print_table(
            table_data=[[output.linkify(entry['record']['element_id']),
                         entry['record']['number'] or u'(無圖號)',
                         entry['note']]
                        for entry in plan['warnings']],
            columns=[u'Element ID', u'圖號', u'說明'])

    if plan['blocked']:
        output.print_md(u'### 略過')
        output.print_table(
            table_data=[[output.linkify(entry['record']['element_id']),
                         entry['record']['number'] or u'',
                         entry['record']['name'] or u'',
                         entry['reason']]
                        for entry in plan['blocked']],
            columns=[u'Element ID', u'圖號', u'名稱', u'原因'])


def _convert(doc, plan, symbol):
    """Single Transaction, all or nothing. Returns ``(count, error)``."""
    transaction = DB.Transaction(doc, TITLE)
    try:
        transaction.Start()
        # A titleblock type that has never been placed may be inactive, and an
        # inactive symbol is not usable as the sheet's titleblock.
        try:
            if not symbol.IsActive:
                symbol.Activate()
                doc.Regenerate()
        except Exception:
            pass
        done = 0
        for record in plan['convert']:
            sheet = doc.GetElement(record['element_id'])
            if sheet is None:
                raise Exception(u'圖紙 {} 已不存在。'.format(
                    record['number'] or record['id']))
            sheet.ConvertToRealSheet(symbol.Id)
            done += 1
        transaction.Commit()
        return done, u''
    except Exception as error:
        try:
            if transaction.HasStarted():
                transaction.RollBack()
        except Exception:
            pass
        return 0, u'{}'.format(error)


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行轉換。',
                    title=TITLE, exitscript=True)

    records = _pick_scope(doc)
    if not records:
        return

    titleblocks = _titleblocks(doc)
    if not titleblocks:
        forms.alert(
            u'這個專案沒有載入任何圖框族群（Title Block），'
            u'佔位圖紙無法轉成正式圖紙。\n\n請先載入圖框族群再執行。',
            title=TITLE)
        return
    symbol = _pick(titleblocks, u'轉出來的圖紙要用哪個圖框？')
    if symbol is None:
        return
    titleblock_label = u''
    for label, entry in titleblocks:
        if entry is symbol:
            titleblock_label = label
            break

    plan = logic.build_plan(records)
    _print_plan(plan, titleblock_label)
    summary = logic.plan_lines(plan)

    if not logic.has_work(plan):
        forms.alert(u'【預覽】沒有可轉換的項目，模型未變更。\n\n{}\n\n'
                    u'明細已列在 pyRevit 輸出視窗。'.format(summary),
                    title=TITLE)
        return

    if not forms.alert(
            u'【dry-run 預覽】模型目前未變更。\n\n{}\n\n圖框：{}\n\n'
            u'確定要轉換嗎？'.format(summary, titleblock_label),
            title=TITLE, yes=True, no=True):
        return

    done, error = _convert(doc, plan, symbol)
    if error:
        forms.alert(u'轉換失敗，交易已完整回復，佔位圖紙都還在。\n\n{}'
                    .format(error), title=TITLE)
        return
    forms.alert(u'已將 {} 張佔位圖紙轉為正式圖紙，圖框：{}。'.format(
        done, titleblock_label), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
