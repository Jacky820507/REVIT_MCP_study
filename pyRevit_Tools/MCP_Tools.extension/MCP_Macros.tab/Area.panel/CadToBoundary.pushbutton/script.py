# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""CAD 轉區域線（依圖層）— JAC 04.01.

A DWG arrives as one lump of geometry whose only structure is the layer each
curve sits on, so tracing a floor plan's 牆心線 layer into area boundary lines
is mostly a filtering job. Three things make it more than a loop.

**A DWG layer is not a property, it is a subcategory.** Revit exposes it only
through each geometry object's ``GraphicsStyleId`` → ``GraphicsStyleCategory``,
which is why the layer list has to be built by walking the geometry rather than
read off the import.

**Polylines are not curves.** LWPOLYLINE geometry comes back as ``PolyLine``
with a bare coordinate list, so it has to be rebuilt into ``Line`` segments —
and CAD drawings routinely repeat a vertex, which makes a zero-length segment
that ``Line.CreateBound`` refuses.

**CAD drawings are dirty.** The same wall drawn twice, 0.4mm stubs left from a
trim. Drawn straight into an area plan those become hundreds of invisible
duplicate boundary lines that ruin every 面積 downstream and are miserable to
find again, so they are filtered out and *counted* rather than silently
dropped.

Drawing reuses 區域線重新生成's write path, so the Z handling, the single
Transaction and the all-or-nothing rollback are the ones already in use.
"""

__title__ = u'CAD轉\n區域線'
__author__ = 'RevitMCP'

from Autodesk.Revit import DB
from pyrevit import forms, revit, script

import area_scheme_sources as sources
import cad_boundary_logic as logic
import mcp_window as ui
import mcp_window_logic as uilogic


TITLE = u'CAD 轉區域線'

CLEAR_CHOICES = (
    (u'保留既有區域線，只新增（預設）', False),
    (u'先刪除該視圖既有的區域線再新增', True),
)


def _build_source_spec(doc, levels):
    """第一個視窗：畫到哪張圖、從哪個 CAD 取線。回 ``None`` 表示條件不足。

    圖層清單必須先讀完那個 CAD 的幾何才知道，所以分成兩個視窗——這是真的相依，
    不是偷懶：把每個 CAD 都先掃一遍只為了列選項，代價比多開一個視窗高得多。
    """
    views = sources.area_plan_views(doc)
    if not views:
        return None, u'這個專案沒有面積平面圖（Area Plan），無法放置區域線。'
    imports = sources.cad_imports(doc)
    if not imports:
        return None, u'這個專案沒有匯入或連結的 CAD（DWG／DXF）。'

    view_rows = []
    for view in views:
        level_id = sources.view_level_id(view)
        elevation = levels.get(level_id, (u'', 0.0))[1]
        view_rows.append(
            (elevation, sources.view_label(doc, view, levels), view))
    view_rows.sort(key=lambda item: (item[0], item[1]))

    fields = [
        uilogic.section(u'來源與去處'),
        uilogic.choice('view', u'區域線要畫在哪個面積平面圖',
                       [(label, view) for unused, label, view in view_rows]),
        uilogic.choice('import', u'要從哪個 CAD 圖檔取線', list(imports)),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'把 CAD 圖層上的線轉成面積邊界線',
        badge=uilogic.BADGE_WRITE,
        run_label=u'讀取圖層',
        footnote=u'下一步會列出這個 CAD 各圖層的線段數與總長。',
        width=880, height=520), u''


def _build_layer_spec(records):
    """第二個視窗：圖層與過濾條件。"""
    summary = logic.layer_summary(records)
    options = [(u'{}　（{} 條，總長 {:.1f} m）'.format(
        entry['layer'], entry['count'],
        entry['total_length_mm'] / 1000.0), entry['layer'])
        for entry in summary]

    fields = [
        uilogic.section(u'圖層'),
        uilogic.multichoice('layers', u'要轉成區域線的圖層（可複選）',
                            options, required=True),

        uilogic.section(u'過濾', u'被濾掉的線會各自回報條數，不會默默消失。'),
        uilogic.number('min_length', u'長度下限',
                       default=logic.DEFAULT_MIN_LENGTH_MM, minimum=0,
                       unit=u'mm',
                       help=u'短於此值的線段視為修剪殘留，不轉換。'),
        uilogic.number('tolerance', u'重複比對容差',
                       default=logic.DEFAULT_TOLERANCE_MM, minimum=0.001,
                       unit=u'mm',
                       help=u'端點差距小於此值視為同一條線。去重是跨圖層的：'
                            u'同一條線同時存在於兩個被選圖層時仍只畫一條。'),

        uilogic.section(u'既有區域線'),
        uilogic.choice('clear', u'既有的區域線要怎麼處理', CLEAR_CHOICES,
                       default=False),

        uilogic.note(
            u'雲線與橢圓一律略過而**不自動打斷**——把一條雲線變成兩百條短'
            u'區域線是個有後果的決定，不該由工具替你做。', tone='warning'),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'選擇圖層與過濾條件',
        badge=uilogic.BADGE_WRITE,
        run_label=u'預覽',
        footnote=u'寫入前一定會先預覽並由你確認；單一交易，全有全無。',
        width=960, height=780)


def _print_plan(plan, view_label, import_label, delete_count):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    output.print_md(u'來源：**{}**　→　目標視圖：**{}**'.format(
        import_label, view_label))

    if plan['layers']:
        output.print_md(u'### 將建立的區域線（{} 條）'.format(plan['count']))
        output.print_table(
            table_data=[[entry['layer'], u'{}'.format(entry['count']),
                         u'{:.2f}'.format(entry['total_length_mm'] / 1000.0)]
                        for entry in plan['layers']],
            columns=[u'圖層', u'條數', u'總長(m)'])

    if plan['blocked']:
        rows = {}
        for entry in plan['blocked']:
            layer = entry['record'].get('layer') or u'(無圖層)'
            key = (layer, entry['reason'])
            rows[key] = rows.get(key, 0) + 1
        output.print_md(u'### 略過的線段')
        output.print_table(
            table_data=[[layer, reason, u'{}'.format(count)]
                        for (layer, reason), count in sorted(rows.items())],
            columns=[u'圖層', u'原因', u'條數'])

    if delete_count:
        output.print_md(u'另會先刪除該視圖既有的 {} 條區域線。'.format(
            delete_count))
    output.print_md(
        u'雲線／橢圓等不支援的曲線一律略過而非自動打斷——把一條雲線變成兩百條'
        u'短區域線是個有後果的決定，不該由工具替你做。')


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行轉換。',
                    title=TITLE, exitscript=True)

    levels = sources.level_index(doc)
    spec, problem = _build_source_spec(doc, levels)
    if spec is None:
        forms.alert(problem, title=TITLE)
        return
    picked = ui.ask(spec)
    if picked is None:
        return

    view = picked['view']
    import_instance = picked['import']
    view_label = sources.view_label(doc, view, levels)
    level_id = sources.view_level_id(view)
    if not level_id or level_id <= 0:
        forms.alert(u'這個面積平面圖讀不到對應樓層，無法建立區域線。',
                    title=TITLE)
        return
    import_label = sources.element_name(
        doc.GetElement(import_instance.GetTypeId())) or u'(未命名 CAD)'

    records = sources.cad_layer_curves(doc, import_instance, view)
    if not records:
        forms.alert(u'這個 CAD 圖檔裡讀不到任何線段。\n\n'
                    u'若它是連結的 CAD，請確認連結沒有遺失。', title=TITLE)
        return

    values = ui.ask(_build_layer_spec(records))
    if values is None:
        return
    layers = values['layers']
    min_length = values['min_length']
    tolerance = values['tolerance']
    clear_first = values['clear']

    delete_ids = []
    if clear_first:
        delete_ids = [row['id']
                      for row in sources.collect_boundary_lines(doc, view)]

    plan = logic.build_plan(records, layers, min_length, tolerance)
    _print_plan(plan, view_label, import_label, len(delete_ids))
    summary = logic.plan_lines(plan, len(delete_ids))

    if not logic.has_work(plan) and not delete_ids:
        forms.alert(u'【預覽】沒有可建立的區域線，模型未變更。\n\n{}\n\n'
                    u'明細已列在 pyRevit 輸出視窗。'.format(summary),
                    title=TITLE)
        return

    if not forms.alert(
            u'【dry-run 預覽】模型目前未變更。\n\n{}\n\n'
            u'目標視圖：{}\n\n確定要建立嗎？'.format(summary, view_label),
            title=TITLE, yes=True, no=True):
        return

    drawn, deleted, error = sources.regenerate_boundary_lines(
        doc, view, level_id, plan['draw'], delete_ids)
    if error:
        forms.alert(u'建立失敗，交易已完整回復，模型沒有變更。\n\n{}'.format(
            error), title=TITLE)
        return
    forms.alert(u'已建立 {} 條區域線{}。'.format(
        drawn, u'，並刪除 {} 條舊的'.format(deleted) if deleted else u''),
        title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
