# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""清除重複的區域線及區域 — JAC 04.13.

Two cleanups that arrive together on a messy area plan:

**Duplicate boundary lines** — lines drawn on top of each other. Detection is
geometric and the rules already exist as
``area_boundary_regen_logic.plan_dedup``; this button is a second entry point
to the same tested function, not a second copy of it. (「區域線重新生成」's
third mode does the lines alone.)

**Duplicate areas** — two or more Areas in one enclosed region. Revit reports
these itself as ``RoomsInSameRegionAreas``, so detection is not guesswork;
choosing which one to delete is.

The keeper is only chosen when it is not a choice: one Area with a number or
name among blanks is obviously the one somebody made. **Two Areas both
carrying data are two different records of the same space**, so that group is
left alone entirely — deleting either loses work, and no default is better
than a coin flip. Where nothing carries data the lowest element id wins:
arbitrary, but stable, so re-running settles rather than churning.

Areas are deleted before boundary lines: a line still bounding an area is what
Revit complains about. The whole thing is one Transaction and a backup of the
areas is offered first, exactly as 「清除區域線及面積」 does.
"""

__title__ = u'清除重複\n區域線及面積'
__author__ = 'RevitMCP'

import os

from pyrevit import forms, revit, script

import area_boundary_regen_logic as line_logic
import area_dedup_logic as logic
import area_export_logic as export_logic
import area_scheme_sources as sources
import mcp_window as ui
import mcp_window_logic as uilogic
import xlsx_writer


TITLE = u'清除重複的區域線及面積'

TARGET_AREAS = 'areas'
TARGET_LINES = 'lines'
TARGET_BOTH = 'both'

TARGETS = (
    (u'重複面積＋重複區域線（預設）', TARGET_BOTH),
    (u'只清重複面積', TARGET_AREAS),
    (u'只清重複區域線', TARGET_LINES),
)

EXPORT_CHOICES = (
    (u'先匯出面積清單再刪除（建議）', True),
    (u'直接刪除，不匯出', False),
)


def _build_spec(doc, levels):
    """整份規格；沒有面積計畫時回 ``None``。

    區域線那一半需要一張面積平面圖。這裡列出全部的面積平面圖（標上所屬計畫），
    執行時再檢查它是否屬於選定的計畫——選項不能隨另一個欄位重建，所以檢查
    放在執行時，並把理由講清楚而不是靜默忽略。
    """
    schemes = sources.area_schemes(doc)
    if not schemes:
        return None
    view_rows = []
    for view in sources.area_plan_views(doc):
        level_id = sources.view_level_id(view)
        elevation = levels.get(level_id, (u'', 0.0))[1]
        view_rows.append(
            (elevation, sources.view_label(doc, view, levels), view))
    view_rows.sort(key=lambda item: (item[0], item[1]))

    fields = [
        uilogic.section(u'範圍'),
        uilogic.choice('scheme', u'面積計畫',
                       [(sources.scheme_label(scheme), scheme)
                        for scheme in schemes]),
        uilogic.choice('target', u'要清理什麼', TARGETS, default=TARGET_BOTH),
        uilogic.choice('view', u'要清理區域線的面積平面圖',
                       [(label, view) for unused, label, view in view_rows],
                       required=False,
                       enabled_when=('target', (TARGET_BOTH, TARGET_LINES)),
                       help=u'必須屬於上面選定的面積計畫。'),

        uilogic.section(u'刪除前'),
        uilogic.choice('backup', u'要先備份面積清單嗎', EXPORT_CHOICES,
                       default=True,
                       help=u'備份記錄的是**即將失去的東西**，跟著刪除清單走。'),

        uilogic.note(
            u'一組重複裡**兩個都有編號或名稱時整組不動**——那是同一空間的'
            u'兩份紀錄，刪掉哪個都會失去東西，沒有預設會比擲硬幣好。'
            u'只有一個有資料時才代為保留有資料的那個。', tone='warning'),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'清除同一封閉區域裡的重複面積，以及重疊的區域線',
        badge=uilogic.BADGE_DELETE,
        run_label=u'預覽',
        footnote=u'刪除前一定會先預覽並由你確認；先刪面積再刪區域線。',
        width=960, height=760)


def _safe_filename(text):
    return u''.join(u'_' if c in u'\\/:*?"<>|' else c
                    for c in u'{}'.format(text or u'')).strip() or u'Area'


def _export_backup(doc, records):
    """Back up the areas about to go. ``None`` if the user cancelled."""
    if not records:
        return None
    try:
        title = os.path.splitext(os.path.basename(doc.PathName))[0]
    except Exception:
        title = u''
    path = forms.save_file(
        file_ext='xlsx',
        default_name=u'{}_重複面積清除前備份.xlsx'.format(
            _safe_filename(title or u'Revit')))
    if not path:
        return None
    grouped = {}
    order = []
    for record in records:
        key = record.get('scheme') or u'(未命名計畫)'
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(record)
    sheets = export_logic.build_workbook([(name, grouped[name])
                                          for name in order])
    xlsx_writer.write_workbook(path, sheets)
    return path


def _print_plan(plan, line_plan, scheme_label):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    output.print_md(u'面積計畫：**{}**'.format(scheme_label))

    if plan['resolved']:
        output.print_md(u'### 將清除的重複面積（{} 組）'.format(
            len(plan['resolved'])))
        rows = []
        for entry in plan['resolved']:
            keeper = entry['keeper']
            for item in entry['deletes']:
                rows.append([
                    output.linkify(item['element_id']),
                    item.get('number') or u'(無編號)',
                    item.get('name') or u'(無名稱)',
                    item.get('level') or u'',
                    u'{}／{}'.format(keeper.get('number') or u'(無編號)',
                                     keeper.get('name') or u'(無名稱)'),
                    entry['reason'],
                ])
        output.print_table(
            table_data=rows,
            columns=[u'將刪除', u'編號', u'名稱', u'樓層', u'保留的是',
                     u'依據'])

    if plan['undecided']:
        output.print_md(u'### 需人工判定（{} 組，一個都不會刪）'.format(
            len(plan['undecided'])))
        rows = []
        for entry in plan['undecided']:
            for item in entry['records']:
                rows.append([
                    output.linkify(item['element_id']),
                    item.get('number') or u'(無編號)',
                    item.get('name') or u'(無名稱)',
                    item.get('level') or u'',
                    entry['reason'],
                ])
        output.print_table(
            table_data=rows,
            columns=[u'Element ID', u'編號', u'名稱', u'樓層', u'原因'])

    if line_plan and line_plan.get('deletes'):
        output.print_md(u'### 將刪除的重複區域線（{} 條）'.format(
            len(line_plan['deletes'])))
        output.print_table(
            table_data=[[output.linkify(row['element_id'])]
                        for row in line_plan['deletes'][:200]],
            columns=[u'Element ID'])

    output.print_md(u'> 刪除面積會連同編號、名稱與分類參數一起消失。'
                    u'同一區域有多個帶資料的面積時一律不代為選擇。')


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行清理。',
                    title=TITLE, exitscript=True)

    levels = sources.level_index(doc)
    spec = _build_spec(doc, levels)
    if spec is None:
        forms.alert(u'這個專案沒有面積計畫（Area Scheme）。', title=TITLE)
        return

    values = ui.ask(spec)
    if values is None:
        return

    scheme = values['scheme']
    scheme_id = sources.id_value(scheme.Id)
    scheme_label = sources.scheme_label(scheme)
    target = values['target']

    # --- duplicate areas, from Revit's own warnings ----------------------
    plan = logic.build_plan([])
    area_records = []
    if target in (TARGET_BOTH, TARGET_AREAS):
        areas = sources.collect_areas(doc, scheme_id=scheme_id, levels=levels)
        by_id = dict((row['id'], row) for row in areas)
        groups = []
        for members in sources.redundant_area_groups(doc,
                                                     area_ids=set(by_id)):
            groups.append([by_id[value] for value in members
                           if value in by_id])
        plan = logic.build_plan([group for group in groups
                                 if len(group) >= 2])
        # The backup records what is about to be *lost*, so it follows the
        # delete list rather than the keepers.
        doomed = set(plan['delete_ids'])
        area_records = [row for row in areas if row['id'] in doomed]

    # --- duplicate boundary lines, reusing 01.05's tested rules ----------
    line_plan = None
    view = None
    if target in (TARGET_BOTH, TARGET_LINES):
        view = values.get('view')
        if view is not None                 and sources.view_area_scheme_id(view) != scheme_id:
            forms.alert(
                u'選定的面積平面圖不屬於「{}」這個面積計畫。'
                u'請改選同一計畫底下的平面圖。'.format(scheme_label),
                title=TITLE)
            return
        if view is None:
            if target == TARGET_LINES:
                forms.alert(u'沒有選擇面積平面圖。', title=TITLE)
                return
        else:
            existing = sources.collect_boundary_lines(doc, view)
            line_plan = line_logic.plan_dedup(existing)

    line_deletes = len(line_plan['deletes']) if line_plan else 0
    _print_plan(plan, line_plan, scheme_label)
    summary = logic.plan_lines(plan, line_deletes)

    if not logic.has_work(plan) and not line_deletes:
        forms.alert(u'【預覽】沒有可清除的重複項目，模型未變更。\n\n{}\n\n'
                    u'明細已列在 pyRevit 輸出視窗。'.format(summary),
                    title=TITLE)
        return

    backup_path = None
    if plan['delete_ids']:
        if values['backup']:
            try:
                backup_path = _export_backup(doc, area_records)
            except Exception as error:
                forms.alert(u'備份失敗，未刪除任何東西：\n\n{}'.format(error),
                            title=TITLE)
                return
            if backup_path is None:
                # Cancelling the save dialog cancels the run: carrying on
                # would delete exactly what the person asked to keep.
                forms.alert(u'已取消備份，因此也沒有刪除任何東西。',
                            title=TITLE)
                return

    tail = u'\n備份：{}'.format(backup_path) if backup_path else u''
    if not forms.alert(
            u'【dry-run 預覽】模型目前未變更。\n\n{}\n{}\n\n'
            u'刪除後無法從這個工具復原，確定要清除嗎？'.format(summary, tail),
            title=TITLE, yes=True, no=True):
        return

    # Areas first: a line still bounding an area is what Revit warns about.
    ids = list(plan['delete_ids'])
    if line_plan:
        ids.extend([row['id'] for row in line_plan['deletes']])
    removed, error = sources.delete_elements(doc, ids, TITLE)
    if error:
        forms.alert(u'清除失敗，交易已完整回復，元素都還在。\n\n{}'.format(
            error), title=TITLE)
        return
    forms.alert(u'已刪除 {} 個元素（重複面積 {} 個、重複區域線 {} 條）。{}'
                .format(removed, plan['delete_count'], line_deletes, tail),
                title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
