# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""面積重新編號（JAC 01.03）.

Reassigns 編號 across a set of Areas in a chosen order. Unlike filling a blank,
the numbers being handed out are already in use by the very elements being
renumbered, so a swap (A1↔A2) would momentarily give two areas the same 編號 —
and Revit only *warns* about that rather than refusing, so it would commit. The
plan detects that case and the write routes through a temporary numbering pass.

Same contract as the other writing buttons: dry-run preview, confirm, one
Transaction that rolls back completely on any refusal.
"""

__title__ = u'面積\n重新編號'
__author__ = 'RevitMCP'

from pyrevit import forms, revit, script

import area_renumber_logic as logic
import area_scheme_sources as sources
import mcp_window as ui
import mcp_window_logic as uilogic


TITLE = u'面積重新編號'
SQ_FT_TO_SQ_M = 0.09290304
ALL_VIEWS = u'（整個面積計畫，不分平面圖）'

ORDERS = (
    (logic.ORDER_LABELS[logic.ORDER_BY_ROW], logic.ORDER_BY_ROW),
    (logic.ORDER_LABELS[logic.ORDER_BY_COLUMN], logic.ORDER_BY_COLUMN),
    (logic.ORDER_LABELS[logic.ORDER_BY_NUMBER], logic.ORDER_BY_NUMBER),
    (logic.ORDER_LABELS[logic.ORDER_BY_NAME], logic.ORDER_BY_NAME),
    (logic.ORDER_LABELS[logic.ORDER_BY_AREA_DESC], logic.ORDER_BY_AREA_DESC),
    (logic.ORDER_LABELS[logic.ORDER_BY_AREA_ASC], logic.ORDER_BY_AREA_ASC),
)

LEVEL_MODES = (
    (u'每個樓層各自從起始號重新編', True),
    (u'全部連號，不分樓層', False),
)


def _build_spec(doc, levels):
    """整份規格；沒有面積計畫時回 ``None``。

    範圍原本是「挑一張面積平面圖」，但那張圖唯一提供的資訊就是樓層。直接列
    樓層等價、且不必隨面積計畫重建選項；選到沒有面積的樓層時，後面既有的
    「指定範圍內沒有面積」仍然會擋下來。
    """
    schemes = sources.area_schemes(doc)
    if not schemes:
        return None
    scheme_options = [(sources.scheme_label(scheme), scheme)
                      for scheme in schemes]
    scope_options = [(ALL_VIEWS, None)]
    for level_id, entry in sorted(levels.items(), key=lambda i: i[1][1]):
        scope_options.append((entry[0], level_id))

    fields = [
        uilogic.section(u'範圍'),
        uilogic.choice('scheme', u'面積計畫', scheme_options),
        uilogic.choice('level', u'重新編號的範圍', scope_options, default=None,
                       required=False),

        uilogic.section(u'順序'),
        uilogic.choice('strategy', u'要照什麼順序編號', ORDERS,
                       default=logic.ORDER_BY_ROW),
        uilogic.number('band', u'同一列（行）的容許誤差',
                       default=int(logic.DEFAULT_BAND_MM), minimum=0,
                       unit=u'mm', integer=True,
                       enabled_when=('strategy', tuple(logic.POSITION_ORDERS)),
                       help=u'兩個面積的中心點在這個範圍內就算同一列。'
                            u'太小會把一整排拆成很多列，太大會把上下兩排'
                            u'併成一列。只有依位置排序時才有作用。'),
        uilogic.choice('per_level', u'跨樓層怎麼編', LEVEL_MODES, default=True),

        uilogic.section(u'編號格式'),
        uilogic.text('prefix', u'前綴（可留空）', default=u'A'),
        uilogic.number('start', u'起始號碼', default=1, integer=True),
        uilogic.number('pad', u'補零位數', default=0, minimum=0, integer=True,
                       help=u'0 表示不補零；3 會產生 001。'),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'依位置或既有欄位重新編號，寫入前先 dry-run 預覽',
        badge=uilogic.BADGE_WRITE,
        run_label=u'預覽',
        footnote=u'寫入前一定會先預覽並由你確認；需要時自動走兩階段避免撞號。',
        width=940, height=780)


def _print_plan(plan, scheme_label, scope_label):
    output = script.get_output()
    output.print_md(u'## {} — {}'.format(TITLE, scheme_label))
    output.print_md(u'範圍：**{}**　排序：**{}**'.format(
        scope_label, logic.ORDER_LABELS.get(plan['strategy'])))
    if plan['writes']:
        output.print_table(
            table_data=[[
                u'{}'.format(index + 1),
                output.linkify(row['element_id']),
                row['level'],
                row.get('number') or u'(空白)',
                row['target'],
                row.get('name', u''),
                u'{:.2f}'.format(
                    float(row.get('area_sqft') or 0.0) * SQ_FT_TO_SQ_M),
            ] for index, row in enumerate(plan['writes'])],
            columns=[u'順序', u'Element ID', u'樓層', u'原編號', u'新編號',
                     u'名稱', u'面積(m²)'])
    else:
        output.print_md(u'沒有需要變更的編號。')
    if plan['unchanged']:
        output.print_md(u'### 編號不變（{} 個）'.format(len(plan['unchanged'])))
    if plan['blocked']:
        output.print_md(u'### 阻擋不改（{} 個）'.format(len(plan['blocked'])))
        output.print_table(
            table_data=[[
                output.linkify(row['record']['element_id']),
                row['record'].get('number') or u'(空白)',
                row['record'].get('target', u''),
                row['reason'],
            ] for row in plan['blocked']],
            columns=[u'Element ID', u'原編號', u'擬用編號', u'原因'])


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行面積重新編號。',
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
    level_id = values['level']
    scope_label = (levels.get(level_id, (ALL_VIEWS, 0.0))[0]
                   if level_id is not None else ALL_VIEWS)

    everything = sources.collect_areas(doc, scheme_id=scheme_id, levels=levels)
    if not everything:
        forms.alert(u'這個面積計畫底下沒有面積。', title=TITLE)
        return
    if level_id is None:
        targets = everything
        outside = []
    else:
        targets = [row for row in everything if row['level_id'] == level_id]
        # Areas elsewhere in the same scheme still own their 編號; a target
        # landing on one of those is a duplicate nothing in this run can free.
        outside = [row['number'] for row in everything
                   if row['level_id'] != level_id]
    if not targets:
        forms.alert(u'指定範圍內沒有面積。', title=TITLE)
        return

    strategy = values['strategy']
    band_mm = values['band']
    per_level = values['per_level']
    prefix = values['prefix']
    start = values['start']
    pad = values['pad']

    plan = logic.build_plan(
        targets, strategy=strategy, prefix=prefix.strip(), start=start,
        pad=pad, per_level=per_level, band_mm=float(band_mm),
        outside_numbers=outside)
    scheme_label = sources.scheme_label(scheme)
    _print_plan(plan, scheme_label, scope_label)
    summary = logic.plan_lines(plan, scheme_label, scope_label)

    if not plan['writes']:
        forms.alert(
            u'【dry-run 預覽】沒有需要變更的編號，模型未變更。\n\n{}\n\n'
            u'明細已列在 pyRevit 輸出視窗。'.format(summary), title=TITLE)
        return

    if not forms.alert(
            u'【dry-run 預覽】\n\n{}\n\n'
            u'明細已列在 pyRevit 輸出視窗。\n'
            u'確定要寫入目前模型嗎？'.format(summary),
            title=TITLE, yes=True, no=True):
        return

    written, error = sources.renumber_areas(
        doc, plan['writes'], two_phase=plan['two_phase'])
    if error:
        forms.alert(
            u'寫入失敗，交易已完整回復，模型沒有留下部分改號。\n\n{}'
            .format(error), title=TITLE)
        return
    tail = u'（經暫時編號兩階段寫入）' if plan['two_phase'] else u''
    forms.alert(u'已重新編號 {} 個面積{}。'.format(written, tail), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
