# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""清除區域線及區域（多視圖）— JAC 04.07 / 04.12.

Deletes area boundary lines and Areas across several area plans at once.

This is the only tool here that purely destroys: nothing is rebuilt, so the
preview is the only chance to catch a mistake. Two consequences shape it.

Counts are deduplicated. Two area plans over the same scheme and level show the
*same* elements, so adding their per-view numbers would promise twice the
deletion the model can actually deliver.

Deleting an Area discards its 編號, 名稱 and classification parameters with it,
which is why the confirmation names how many carry data and why exporting them
to Excel first is offered — and defaulted to.

It deliberately lives in its own button rather than as a mode of 區域線重新生成:
nobody reaching for "regenerate" should be one wrong menu pick away from
emptying every area plan in the project.
"""

__title__ = u'清除區域線\n及面積'
__author__ = 'RevitMCP'

import os

from pyrevit import forms, revit, script

import area_export_logic as export_logic
import area_purge_logic as logic
import area_scheme_sources as sources
import mcp_window as ui
import mcp_window_logic as uilogic
import xlsx_writer


TITLE = u'清除區域線及面積'

TARGETS = (
    (logic.TARGET_LABELS[logic.TARGET_BOTH], logic.TARGET_BOTH),
    (logic.TARGET_LABELS[logic.TARGET_LINES], logic.TARGET_LINES),
    (logic.TARGET_LABELS[logic.TARGET_AREAS], logic.TARGET_AREAS),
)

EXPORT_CHOICES = (
    (u'先匯出面積清單再刪除（建議）', True),
    (u'直接刪除，不匯出', False),
)


def _build_spec(doc, levels):
    """整份規格；沒有面積平面圖時回 ``None``。"""
    views = sources.area_plan_views(doc)
    if not views:
        return None
    view_options = []
    for view in views:
        level_id = sources.view_level_id(view)
        elevation = levels.get(level_id, (u'', 0.0))[1]
        view_options.append(
            (elevation, sources.view_label(doc, view, levels), view))
    view_options.sort(key=lambda item: (item[0], item[1]))

    fields = [
        uilogic.section(u'清除範圍'),
        uilogic.multichoice(
            'views', u'面積平面圖（可複選）',
            [(label, view) for unused, label, view in view_options],
            required=True),
        uilogic.choice('target', u'要清除什麼', TARGETS,
                       default=logic.TARGET_BOTH),

        uilogic.section(u'刪除前'),
        uilogic.choice('backup', u'要先備份面積清單嗎', EXPORT_CHOICES,
                       default=True,
                       help=u'備份只涵蓋面積，區域線沒有可匯出的欄位。'
                            u'取消存檔對話框會連刪除一起取消——'
                            u'繼續下去會刪掉的正是剛剛說要留的東西。'),

        uilogic.note(
            u'刪除後**無法從這個工具復原**。面積連同編號、名稱與所有參數'
            u'一起消失；區域線刪掉後，仍在用它的面積會變成未封閉。',
            tone='danger'),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'清除指定面積平面圖裡的區域線與面積',
        badge=uilogic.BADGE_DELETE,
        run_label=u'預覽',
        footnote=u'刪除前一定會先預覽並由你確認。',
        width=940, height=720)


def _safe_filename(text):
    return u''.join(u'_' if c in u'\\/:*?"<>|' else c
                    for c in u'{}'.format(text or u'')).strip() or u'Area'


def _default_name(doc):
    try:
        title = os.path.splitext(os.path.basename(doc.PathName))[0]
    except Exception:
        title = u''
    return u'{}_面積清除前備份.xlsx'.format(_safe_filename(title or u'Revit'))


def _view_records(doc, views, levels):
    records = []
    for view in views:
        scheme_id = sources.view_area_scheme_id(view)
        level_id = sources.view_level_id(view)
        lines = sources.collect_boundary_lines(doc, view)
        areas = sources.collect_areas(doc, scheme_id=scheme_id,
                                      level_id=level_id, levels=levels)
        scheme_name = areas[0]['scheme'] if areas else u''
        records.append({
            'view_id': sources.id_value(view.Id),
            'view_label': sources.view_label(doc, view, levels),
            'view': view,
            'scheme': scheme_name,
            'level': levels.get(level_id, (u'', 0.0))[0],
            'is_area_plan': scheme_id > 0,
            'line_ids': [row['id'] for row in lines],
            'area_ids': [row['id'] for row in areas],
            'areas': areas,
        })
    return records


def _print_plan(plan):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    output.print_md(u'清除範圍：**{}**'.format(
        logic.TARGET_LABELS.get(plan['target'])))

    if plan['views']:
        output.print_md(u'### 各視圖')
        output.print_table(
            table_data=[[
                row['view_label'], row['scheme'], row['level'],
                u'{}'.format(row['shows_lines']),
                u'{}'.format(row['adds_lines']),
                u'{}'.format(row['shows_areas']),
                u'{}'.format(row['adds_areas']),
            ] for row in plan['views']],
            columns=[u'視圖', u'面積計畫', u'樓層', u'看到的線', u'新增到清單的線',
                     u'看到的面積', u'新增到清單的面積'])
        output.print_md(
            u'「看到的」是該視圖顯示的數量，「新增到清單的」才是它實際多帶來的；'
            u'同一計畫同一樓層的多個平面圖看到的是同一批元素。')

    named = logic.numbered_areas(plan)
    if named:
        output.print_md(u'### 帶有編號或名稱的面積（{} 個）'.format(len(named)))
        output.print_table(
            table_data=[[
                output.linkify(area['element_id']),
                area.get('number', u''), area.get('name', u''),
                area.get('level', u''),
            ] for area in named],
            columns=[u'Element ID', u'編號', u'名稱', u'樓層'])

    if plan['blocked']:
        output.print_md(u'### 略過的視圖')
        output.print_table(
            table_data=[[row['record'].get('view_label', u''), row['reason']]
                        for row in plan['blocked']],
            columns=[u'視圖', u'原因'])


def _export_backup(doc, plan):
    """Write the areas about to be deleted to .xlsx. Returns path or ``None``."""
    grouped = {}
    order = []
    for area in plan['areas']:
        key = area.get('scheme') or u'(未命名計畫)'
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(area)
    if not order:
        forms.alert(u'這次沒有要刪除的面積，不需要備份。', title=TITLE)
        return None
    path = forms.save_file(file_ext='xlsx', default_name=_default_name(doc))
    if not path:
        return None
    sheets = export_logic.build_workbook(
        [(name, grouped[name]) for name in order])
    xlsx_writer.write_workbook(path, sheets)
    return path


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行清除。',
                    title=TITLE, exitscript=True)

    levels = sources.level_index(doc)
    spec = _build_spec(doc, levels)
    if spec is None:
        forms.alert(u'這個專案沒有面積平面圖（Area Plan）。', title=TITLE)
        return

    values = ui.ask(spec)
    if values is None:
        return
    views = values['views']
    target = values['target']

    plan = logic.build_plan(_view_records(doc, views, levels), target)
    _print_plan(plan)
    summary = logic.plan_lines(plan)

    if not logic.has_work(plan):
        forms.alert(u'【預覽】沒有可清除的項目，模型未變更。\n\n{}\n\n'
                    u'明細已列在 pyRevit 輸出視窗。'.format(summary),
                    title=TITLE)
        return

    backup_path = None
    if plan['area_ids']:
        if values['backup']:
            try:
                backup_path = _export_backup(doc, plan)
            except Exception as error:
                forms.alert(u'備份失敗，未刪除任何東西：\n\n{}'.format(error),
                            title=TITLE)
                return
            if backup_path is None:
                # Cancelling the save dialog cancels the run: carrying on
                # would delete exactly what the person just asked to keep.
                forms.alert(u'已取消備份，因此也沒有刪除任何東西。',
                            title=TITLE)
                return

    tail = u'\n備份：{}'.format(backup_path) if backup_path else u''
    if not forms.alert(
            u'【dry-run 預覽】模型目前未變更。\n\n{}\n{}\n\n'
            u'刪除後無法從這個工具復原，確定要清除嗎？'.format(summary, tail),
            title=TITLE, yes=True, no=True):
        return

    removed, error = sources.delete_elements(
        doc, logic.delete_ids(plan), TITLE)
    if error:
        forms.alert(
            u'清除失敗，交易已完整回復，元素都還在。\n\n{}'.format(error),
            title=TITLE)
        return
    forms.alert(u'已刪除 {} 個元素（區域線 {} 條、面積 {} 個）。{}'.format(
        removed, plan['line_count'], plan['area_count'], tail), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
