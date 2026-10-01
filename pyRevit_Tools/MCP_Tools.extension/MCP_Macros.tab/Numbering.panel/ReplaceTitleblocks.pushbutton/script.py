# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""批量換圖框.

選圖紙（可篩選複選）→ 選目標圖框類型 → dry-run 預覽 → 單一 Transaction 換類型。
規則與預覽內容在 ``replace_titleblock_logic``（有 CPython 測試）。

視窗用 ``mcp_window.ask()``：會寫入模型的按鈕不能在 modal 視窗開著時改文件，
所以視窗只收值，關掉之後才預覽與寫入。
"""

__title__ = u'批量\n換圖框'
__author__ = 'RevitMCP'

from Autodesk.Revit import DB
from pyrevit import forms, revit, script

import mcp_window as ui
import mcp_window_logic as spec_logic
import replace_titleblock_logic as logic


TITLE = u'批量換圖框'


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


def _symbol_label(symbol):
    try:
        family = symbol.FamilyName or u''
    except Exception:
        family = u''
    name = _element_name(symbol)
    return u'{}：{}'.format(family, name) if family else name


def _titleblock_types(doc):
    """``[(label, FamilySymbol)]``，依名稱排序。"""
    try:
        symbols = list(DB.FilteredElementCollector(doc)
                       .OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
                       .WhereElementIsElementType()
                       .ToElements())
    except Exception:
        return []
    options = [(_symbol_label(symbol), symbol) for symbol in symbols]
    options.sort(key=lambda entry: entry[0])
    return options


def _sheet_records(doc):
    """全部正式圖紙，每張附上它身上的圖框。圖框只掃一次，不逐張建 collector。"""
    blocks_by_sheet = {}
    instances = DB.FilteredElementCollector(doc) \
        .OfCategory(DB.BuiltInCategory.OST_TitleBlocks) \
        .WhereElementIsNotElementType() \
        .ToElements()
    for instance in instances:
        owner = _id_value(instance.OwnerViewId)
        type_id = instance.GetTypeId()
        symbol = doc.GetElement(type_id)
        blocks_by_sheet.setdefault(owner, []).append({
            'id': _id_value(instance.Id),
            'element_id': instance.Id,
            'type_id': _id_value(type_id),
            'label': _symbol_label(symbol) if symbol is not None else u'',
        })

    records = []
    sheets = DB.FilteredElementCollector(doc) \
        .OfClass(DB.ViewSheet) \
        .WhereElementIsNotElementType() \
        .ToElements()
    for sheet in sheets:
        try:
            if sheet.IsPlaceholder:
                continue
        except Exception:
            pass
        sheet_id = _id_value(sheet.Id)
        records.append({
            'id': sheet_id,
            'element_id': sheet.Id,
            'number': sheet.SheetNumber or u'',
            'name': _element_name(sheet),
            'titleblocks': blocks_by_sheet.get(sheet_id, []),
        })
    return logic.sort_records(records)


def _ask(records, types):
    selected_ids = set()
    try:
        for element_id in revit.uidoc.Selection.GetElementIds():
            selected_ids.add(_id_value(element_id))
    except Exception:
        pass
    sheet_options = [(logic.sheet_label(record), record['id'])
                     for record in records]
    default_sheets = [record['id'] for record in records
                      if record['id'] in selected_ids]
    type_options = [(label, index) for index, (label, unused)
                    in enumerate(types)]
    spec = spec_logic.spec(
        TITLE,
        [
            spec_logic.multichoice(
                'sheets', u'要換圖框的圖紙', sheet_options,
                default=default_sheets, required=True, filter=True,
                help=u'〔 〕內是目前的圖框。可輸入圖號、圖名或圖框名稱篩選；'
                     u'目前在專案瀏覽器選取的圖紙已預先勾選。'),
            spec_logic.choice('target', u'換成這個圖框', type_options),
            spec_logic.choice(
                'anchor', u'換完之後對齊', list(logic.ANCHORS),
                default='bottom-left',
                help=u'新舊圖框族群的外框相對插入點不同時，換完會跑位。'
                     u'選一個角點，換完會把新圖框的這個角搬回舊圖框同一個角'
                     u'原本的位置（每張圖紙各自對齊自己原位）。'),
            spec_logic.note(
                u'按下後先在輸出視窗列出預覽，確認後才會寫入模型。'),
        ],
        badge=spec_logic.BADGE_WRITE, run_label=u'預覽')
    values = ui.ask(spec)
    if not values:
        return None, None, None
    return (values.get('sheets') or [], values.get('target'),
            values.get('anchor') or logic.ANCHOR_NONE)


def _print_plan(plan, target_label):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    output.print_md(u'目標圖框：**{}**'.format(target_label))
    multi_ids = set(record['id'] for record in plan['multi'])
    if plan['change']:
        output.print_md(u'### 將更換（{} 張）'.format(len(plan['change'])))
        output.print_table(
            table_data=[[output.linkify(record['element_id']),
                         record['number'], record['name'],
                         logic.current_label(record),
                         u'{} 個'.format(len(todo)) +
                         (u'（多圖框）' if record['id'] in multi_ids else u'')]
                        for record, todo in plan['change']],
            columns=[u'圖紙', u'圖號', u'圖名', u'原圖框', u'更換數'])
    if plan['skipped']:
        output.print_md(u'### 略過（{} 張）'.format(len(plan['skipped'])))
        output.print_table(
            table_data=[[output.linkify(entry['record']['element_id']),
                         entry['record']['number'], entry['record']['name'],
                         entry['reason']] for entry in plan['skipped']],
            columns=[u'圖紙', u'圖號', u'圖名', u'原因'])
    if plan['unchanged']:
        output.print_md(u'### 已是目標圖框（{} 張，不動）'.format(
            len(plan['unchanged'])))


def _corner(instance, sheet, anchor):
    """圖框在該圖紙上外框的角點 ``(x, y)``（ft）；取不到回 ``None``。"""
    try:
        box = instance.get_BoundingBox(sheet)
    except Exception:
        box = None
    if box is None:
        return None
    return logic.anchor_point((box.Min.X, box.Min.Y),
                              (box.Max.X, box.Max.Y), anchor)


def _apply(doc, plan, symbol, anchor):
    """單一 Transaction，全有全無。回傳 ``(changed, moved, unaligned, error)``。

    先記下所有舊角點、全部換完後 Regenerate 一次，再逐一量新角點並搬回——
    不逐個 Regenerate，圖紙一多才不會慢到像當機。
    """
    aligning = anchor != logic.ANCHOR_NONE
    transaction = DB.Transaction(doc, TITLE)
    try:
        transaction.Start()
        try:
            if not symbol.IsActive:
                symbol.Activate()
                doc.Regenerate()
        except Exception:
            pass
        pending = []
        for record, todo in plan['change']:
            sheet = doc.GetElement(record['element_id'])
            for block in todo:
                instance = doc.GetElement(block['element_id'])
                if instance is None:
                    raise Exception(u'圖紙 {} 的圖框已不存在。'.format(
                        record['number']))
                old = _corner(instance, sheet, anchor) if aligning else None
                instance.ChangeTypeId(symbol.Id)
                pending.append((record, instance, sheet, old))

        moved = 0
        unaligned = []
        if aligning:
            doc.Regenerate()
            for record, instance, sheet, old in pending:
                new = _corner(instance, sheet, anchor)
                if old is None or new is None:
                    unaligned.append(record)
                    continue
                delta = logic.align_delta(old, new)
                if delta is None:
                    continue
                DB.ElementTransformUtils.MoveElement(
                    doc, instance.Id, DB.XYZ(delta[0], delta[1], 0))
                moved += 1
        transaction.Commit()
        return len(pending), moved, unaligned, u''
    except Exception as error:
        try:
            if transaction.HasStarted():
                transaction.RollBack()
        except Exception:
            pass
        return 0, 0, [], u'{}'.format(error)


def main():
    doc = revit.doc
    types = _titleblock_types(doc)
    if not types:
        forms.alert(u'這個專案沒有載入任何圖框族群（Title Block），'
                    u'請先載入再執行。', title=TITLE)
        return
    records = _sheet_records(doc)
    if not records:
        forms.alert(u'這個專案沒有正式圖紙。', title=TITLE)
        return

    sheet_ids, target_index, anchor = _ask(records, types)
    if not sheet_ids or target_index is None:
        return
    target_label, symbol = types[target_index]
    wanted = set(sheet_ids)
    chosen = [record for record in records if record['id'] in wanted]

    plan = logic.build_plan(chosen, _id_value(symbol.Id))
    _print_plan(plan, target_label)
    summary = logic.plan_lines(plan)
    if not logic.has_work(plan):
        forms.alert(u'【預覽】沒有需要更換的圖框，模型未變更。\n\n{}'
                    .format(summary), title=TITLE)
        return
    if not forms.alert(
            u'【dry-run 預覽】模型目前未變更。\n\n{}\n\n目標圖框：{}\n\n'
            u'對齊：{}\n\n確定要更換嗎？'.format(
                summary, target_label, spec_logic.label_for_value(
                    logic.ANCHORS, anchor)),
            title=TITLE, yes=True, no=True):
        return

    done, moved, unaligned, error = _apply(doc, plan, symbol, anchor)
    if error:
        forms.alert(u'更換失敗，交易已完整回復，模型未變更。\n\n{}'
                    .format(error), title=TITLE)
        return
    lines = [u'已更換 {} 個圖框為：{}。'.format(done, target_label)]
    if anchor != logic.ANCHOR_NONE:
        lines.append(u'對齊原位置：移動 {} 個，其餘本來就在原位。'.format(moved))
        if unaligned:
            lines.append(u'無法量測外框、未對齊：{}'.format(u'、'.join(
                record['number'] for record in unaligned)))
    forms.alert(u'\n'.join(lines), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
