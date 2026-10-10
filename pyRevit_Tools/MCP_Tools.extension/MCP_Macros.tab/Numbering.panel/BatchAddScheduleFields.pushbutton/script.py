# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""批量新增明細表欄位.

複選既有明細表 → 從它們可用欄位的聯集勾選參數欄位 → dry-run 預覽 → 單一
Transaction 把欄位附加到每張明細表最後；任何一張失敗整批回復。

明細表已經有的欄位不重複加；該明細表品類沒有的參數列為「對不到」並略過。
"""

__title__ = u'批量新增\n明細表欄位'
__author__ = 'RevitMCP'

from pyrevit import forms, revit, script

import mcp_window as ui
import mcp_window_logic as spec_logic
import schedule_batch_logic as logic
import schedule_batch_revit as batch


TITLE = u'批量新增明細表欄位'


def _ask_schedules(views, doc):
    active = None
    try:
        active = batch.id_value(revit.active_view.Id)
    except Exception:
        pass
    options = []
    for view in views:
        category = batch.category_name(doc, view)
        label = u'{}（{}）'.format(view.Name, category) if category \
            else view.Name
        options.append((label, batch.id_value(view.Id)))
    spec = spec_logic.spec(
        TITLE,
        [spec_logic.multichoice(
            'schedules', u'明細表', options,
            default=[active] if active in [o[1] for o in options] else [],
            required=True, filter=True,
            help=u'可輸入名稱或品類關鍵字篩選（例如輸入「牆」只留下牆相關的表）；'
                 u'Shift+點擊可連選。目前開啟的明細表已預先勾選。'),
         spec_logic.note(
             u'下一步從所選明細表的可用欄位勾選要加入的欄位，再預覽；'
             u'確認前模型不會變更。')],
        badge=spec_logic.BADGE_WRITE, run_label=u'下一步：選欄位',
        width=680, height=720)
    values = ui.ask(spec)
    return (values or {}).get('schedules') or []


def _ask_fields(doc, chosen):
    union = logic.field_union(
        [(v.Name, batch.schedulable_names(doc, v)) for v in chosen])
    total = len(chosen)
    options = []
    for name, owners in union:
        suffix = u'' if len(owners) == total else \
            u'（{}/{} 張）'.format(len(owners), total)
        options.append((name + suffix, name))
    spec = spec_logic.spec(
        TITLE,
        [spec_logic.multichoice(
            'fields', u'要加入的欄位', options, required=True, filter=True,
            help=u'可輸入關鍵字篩選。標示「n/m 張」的欄位只有部分明細表可加，'
                 u'其餘會在預覽列為對不到並略過。已在明細表上的欄位不會重複加。')],
        badge=spec_logic.BADGE_WRITE, run_label=u'預覽',
        width=680, height=720)
    values = ui.ask(spec)
    return (values or {}).get('fields') or []


def _print_preview(rows):
    output = script.get_output()
    output.print_md(u'## {} — 預覽'.format(TITLE))
    output.print_table(
        table_data=rows,
        columns=[u'明細表', u'品類', u'將加入', u'已存在（略過）', u'對不到'])


def main():
    doc = revit.doc
    views = batch.user_schedules(doc)
    if not views:
        forms.alert(u'這個專案沒有明細表。', title=TITLE)
        return
    chosen_ids = set(_ask_schedules(views, doc))
    if not chosen_ids:
        return
    chosen = [v for v in views if batch.id_value(v.Id) in chosen_ids]
    wanted = _ask_fields(doc, chosen)
    if not wanted:
        return

    rows = []
    targets = []
    add_count = 0
    for view in chosen:
        report = batch.add_fields(doc, view, wanted, False)
        add_count += len(report['added'])
        if report['added']:
            targets.append(view)
        rows.append([view.Name, batch.category_name(doc, view) or u'-',
                     u'、'.join(report['added']) or u'-',
                     u'、'.join(report['already']) or u'-',
                     u'、'.join(report['missing']) or u'-'])
    _print_preview(rows)
    if not targets:
        forms.alert(u'所選欄位在這些明細表上都已存在或對不到，沒有要加的欄位。'
                    u'明細在輸出視窗。', title=TITLE)
        return

    answer = forms.alert(
        u'【dry-run 預覽】模型目前未變更。\n\n將對 {} 張明細表共加入 {} 個欄位，'
        u'明細在輸出視窗。\n\n確定寫入嗎？'.format(len(targets), add_count),
        title=TITLE, yes=True, no=True)
    if not answer:
        return

    failures = batch.add_fields_to_schedules(doc, targets, wanted, TITLE)
    if failures:
        forms.alert(
            u'有 {} 張寫不進去，交易已完整回復，模型未變更。\n\n{}'.format(
                len(failures), u'\n'.join(failures[:25])), title=TITLE)
        return
    forms.alert(u'已對 {} 張明細表加入 {} 個欄位。'.format(
        len(targets), add_count), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
