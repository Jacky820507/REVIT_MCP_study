# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""複製面積到別的面積計畫（JAC 01.06）.

``Area.AreaScheme`` is read-only, so an area cannot be moved between schemes.
Copying means recreating: draw the same boundary lines in the target scheme's
plan, then place areas inside the regions those lines form, carrying the 編號
and 名稱 across.

Restricted to plans on the **same level**. The source line's own sketch plane
is reused, which is exactly right within a level and wrong across one — a
cross-level copy needs the curves moved in Z, and drawing them at the wrong
height silently would be worse than refusing.

Preview works the way the sibling buttons do, extended to cover both halves at
once: the lines are drawn and the areas placed inside a Transaction that always
rolls back, because an area copied without its boundary encloses nothing and
measuring it beforehand would report a failure the real run would not have.
"""

__title__ = u'複製面積到\n其他計畫'
__author__ = 'RevitMCP'

from pyrevit import forms, revit, script

import area_copy_logic as logic
import area_scheme_sources as sources
import mcp_window as ui
import mcp_window_logic as uilogic


TITLE = u'複製面積到其他面積計畫'
SQ_FT_TO_SQ_M = 0.09290304

WHAT_BOTH = 'both'
WHAT_LINES = 'lines'
WHAT_AREAS = 'areas'

WHAT_CHOICES = (
    (u'邊界線 + 面積（建議）', WHAT_BOTH),
    (u'只複製面積邊界線', WHAT_LINES),
    (u'只複製面積（目標計畫必須已有對應邊界）', WHAT_AREAS),
)


def _view_options(doc):
    """``[(label, view)]``，依樓層高程再依名稱排序。"""
    levels = sources.level_index(doc)
    rows = []
    for view in sources.area_plan_views(doc):
        level_id = sources.view_level_id(view)
        elevation = levels.get(level_id, (u'', 0.0))[1]
        rows.append((elevation, sources.view_label(doc, view, levels), view))
    rows.sort(key=lambda item: (item[0], item[1]))
    return [(label, view) for unused, label, view in rows]


def _build_spec(options):
    fields = [
        uilogic.section(u'來源與目標',
                        u'只支援同樓層複製：來源的草圖平面會直接沿用。'
                        u'選到不同樓層時執行會擋下並說明。'),
        uilogic.choice('source', u'來源面積平面圖', options),
        uilogic.choice('target', u'目標面積平面圖', options),

        uilogic.section(u'複製內容'),
        uilogic.choice('what', u'要複製什麼', WHAT_CHOICES, default=WHAT_BOTH),

        uilogic.note(
            u'按下「預覽」之後會先做一次**保證回復的試放**，把實際結果算出來'
            u'再問你要不要真的寫入——預覽數字來自 Revit 本身，不是用邏輯猜的。',
            tone='info'),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'邊界線與面積複製到同樓層的另一個面積計畫',
        badge=uilogic.BADGE_WRITE,
        run_label=u'預覽（試放後回復）',
        footnote=u'寫入前一定會先預覽並由你確認；失敗時整批回復。',
        width=940, height=680)


def _print_plan(plan, source_label, target_label):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    output.print_md(u'來源：**{}**　→　目標：**{}**'.format(
        source_label, target_label))

    if plan['copy_lines']:
        group = plan['lines']
        output.print_md(u'### 邊界線：複製 {} 條（來源共 {} 條）'.format(
            len(group['writes']), plan['source_line_count']))
        rows = [[output.linkify(row['element_id']), row['reason']]
                for row in group['skipped'] + group['blocked']]
        if rows:
            output.print_table(table_data=rows,
                               columns=[u'來源 Element ID', u'略過原因'])

    if plan['copy_areas']:
        group = plan['areas']
        verb = u'將建立' if plan.get('trialled') else u'預計建立'
        output.print_md(u'### 面積：{} {} 個（來源共 {} 個）'.format(
            verb, len(group['writes']), plan['source_area_count']))
        if group['writes']:
            output.print_table(
                table_data=[[
                    output.linkify(row['element_id']),
                    row.get('target_number') or u'(自動)',
                    row.get('target_name', u''),
                    u'{:.2f}'.format(
                        float(row.get('area_sqft') or 0.0) * SQ_FT_TO_SQ_M),
                ] for row in group['writes']],
                columns=[u'來源 Element ID', u'編號', u'名稱',
                         u'試放面積(m²)'])
        rows = [[output.linkify(row['record']['element_id']),
                 row['record'].get('number', u''), row['reason']]
                for row in group['skipped'] + group['blocked']]
        if rows:
            output.print_table(
                table_data=rows,
                columns=[u'來源 Element ID', u'編號', u'略過／阻擋原因'])


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行複製面積。',
                    title=TITLE, exitscript=True)

    if not sources.area_plan_views(doc):
        forms.alert(
            u'這個專案沒有面積平面圖（Area Plan）。\n\n'
            u'複製的來源與目標都必須是面積平面圖，本按鈕不會代為建立視圖。',
            title=TITLE)
        return

    options = _view_options(doc)
    values = ui.ask(_build_spec(options))
    if values is None:
        return

    source_view = values['source']
    target_view = values['target']
    levels = sources.level_index(doc)
    source_level = sources.view_level_id(source_view)
    source_label = sources.view_label(doc, source_view, levels)
    target_label = sources.view_label(doc, target_view, levels)

    if sources.id_value(source_view.Id) == sources.id_value(target_view.Id):
        forms.alert(u'來源與目標是同一張面積平面圖。', title=TITLE)
        return
    if sources.view_level_id(target_view) != source_level:
        forms.alert(
            u'來源在「{}」、目標在「{}」，不是同一個樓層。\n\n'
            u'本按鈕只支援同樓層複製（來源的草圖平面會直接沿用）；'
            u'請先為目標面積計畫在同一樓層建立面積平面圖。'
            .format(source_label, target_label), title=TITLE)
        return

    source_scheme_id = sources.view_area_scheme_id(source_view)
    target_scheme_id = sources.view_area_scheme_id(target_view)
    if source_scheme_id == target_scheme_id:
        forms.alert(u'來源與目標屬於同一個面積計畫，沒有東西要複製。',
                    title=TITLE)
        return

    what = values['what']
    copy_lines = what in (WHAT_BOTH, WHAT_LINES)
    copy_areas = what in (WHAT_BOTH, WHAT_AREAS)

    source_lines = sources.collect_boundary_lines(doc, source_view) \
        if copy_lines else []
    target_lines = sources.collect_boundary_lines(doc, target_view) \
        if copy_lines else []
    source_areas = sources.collect_areas(
        doc, scheme_id=source_scheme_id, level_id=source_level,
        levels=levels) if copy_areas else []
    target_areas = sources.collect_areas(
        doc, scheme_id=target_scheme_id, level_id=source_level, levels=levels)

    plan = logic.build_plan(source_lines, target_lines, source_areas,
                            target_areas, copy_lines=copy_lines,
                            copy_areas=copy_areas)

    if not logic.has_work(plan):
        _print_plan(plan, source_label, target_label)
        forms.alert(
            u'【預覽】沒有要複製的東西，模型未變更。\n\n{}\n\n'
            u'明細已列在 pyRevit 輸出視窗。'.format(
                logic.plan_summary(plan, source_label, target_label)),
            title=TITLE)
        return

    if plan['areas']['writes']:
        trial = sources.trial_copy(doc, target_view, plan['lines']['writes'],
                                   plan['areas']['writes'])
        plan = logic.apply_trial_result(plan, trial)

    _print_plan(plan, source_label, target_label)
    summary = logic.plan_summary(plan, source_label, target_label)

    if not logic.has_work(plan):
        forms.alert(
            u'【dry-run 預覽】沒有可複製的項目，模型未變更。\n\n{}\n\n'
            u'明細已列在 pyRevit 輸出視窗。'.format(summary), title=TITLE)
        return

    if not forms.alert(
            u'【dry-run 預覽】試放已完成並回復，模型目前未變更。\n\n{}\n\n'
            u'明細已列在 pyRevit 輸出視窗。\n'
            u'確定要複製到目標面積計畫嗎？'.format(summary),
            title=TITLE, yes=True, no=True):
        return

    lines, areas, error = sources.copy_to_scheme(
        doc, target_view, plan['lines']['writes'], plan['areas']['writes'])
    if error:
        forms.alert(
            u'複製失敗，交易已完整回復，模型沒有留下半成品。\n\n{}'
            .format(error), title=TITLE)
        return
    forms.alert(u'已複製 {} 條邊界線、{} 個面積到「{}」。'.format(
        lines, areas, target_label), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
