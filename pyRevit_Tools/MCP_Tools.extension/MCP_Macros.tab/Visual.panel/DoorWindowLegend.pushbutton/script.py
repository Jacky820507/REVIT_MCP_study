# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""門窗圖例＋參數（自動完成門窗圖）— 依 domain/door-window-legend-workflow.md.

流程圖的六步對應到這些 Revit API（全部經反射確認 2020／2024 相同）：

===============================  =========================================
提取所有 Family                  ``FilteredElementCollector``
篩選門窗 Family                  ``OfCategory(OST_Doors / OST_Windows)``
創建集合暫存                     ``WhereElementIsElementType()`` → FamilySymbol
選擇列出參數                     ``symbol.Parameters`` → ``AsValueString()``
放置在圖例中點選的位置           ``UIDocument.PromptToPlaceElementTypeOnLegendView``
底部對齊平均展開                 ``get_BoundingBox(view)`` + ``MoveElement``
===============================  =========================================

**最關鍵的一項不在流程圖上**：``PromptToPlaceElementTypeOnLegendView`` 一次只
放一個、而且每次都要人點一下，32 個類型就是 32 次點擊。反射確認
``BuiltInParameter.LEGEND_COMPONENT`` 存在——圖例元件「顯示哪個類型」是一個
**參數**，所以只要點一次放下 seed，其餘用 ``CopyElement`` 複製再改這個參數。
這正是 domain 檔〈設計約束〉指定的「template 預埋 seed → 複製 → 改 type」。

domain 檔的三條硬規則在這裡的落實方式：

* **不得自動選 seed** —— 圖例視圖與 seed 來源都用「（請選擇）」起始，
  不預選；沒選就過不了驗證。
* **不得自動補排版方向或每排數量** —— 同上，兩個欄位都要人明確指定。
* **Legend Component 無法被 tag** —— 參數只能寫成 ``TextNote``。

原本 MCP 那條路（``door-window-legend-tools``）在**這個 fork 是打不通的**：C# 的
``DoorWindowLegendTools()`` 有定義但 dispatcher 沒有對應的 case，它就列在
``UNIMPLEMENTED_ON_THIS_FORK`` 裡。所以這顆按鈕走直接 Revit API。

寫入前一定先 dry-run 預覽；寫入是單一 Transaction，任一步失敗整批回復。
"""

__title__ = u'門窗圖例\n＋參數'
__author__ = 'RevitMCP'

from Autodesk.Revit import DB
from pyrevit import forms, revit, script

import legend_layout_logic as logic
import legend_sources as legend
import mcp_window as ui
import mcp_window_logic as uilogic


TITLE = u'門窗圖例＋參數'

# 「（請選擇）」是一個真的選項，不是留白。domain 檔明訂不得自動選 seed、
# 不得自動補排版——預選第一項就是替使用者做了那個決定。
PICK_ME = u'（請選擇）'

SEED_EXISTING = 'existing'
SEED_PROMPT = 'prompt'

SEED_CHOICES = (
    (PICK_ME, None),
    (u'用這張圖例視圖裡既有的圖例元件當 seed（不需點選）', SEED_EXISTING),
    (u'我自己點一下放置第一個，該點就是排版原點', SEED_PROMPT),
)

KIND_CHOICES = (
    (u'門與窗', (legend.DOOR, legend.WINDOW)),
    (u'只有門', (legend.DOOR,)),
    (u'只有窗', (legend.WINDOW,)),
)

USED_CHOICES = (
    (u'只列模型裡真的有放置的類型（建議）', True),
    (u'列出專案載入的全部門窗類型', False),
)

LAYOUT_CHOICES = (
    (PICK_ME, None),
    (logic.LAYOUT_LABELS[logic.LAYOUT_HORIZONTAL], logic.LAYOUT_HORIZONTAL),
    (logic.LAYOUT_LABELS[logic.LAYOUT_VERTICAL], logic.LAYOUT_VERTICAL),
)

TEXT_ALIGN_CHOICES = (
    (logic.TEXT_ALIGN_LABELS[logic.TEXT_LEFT], logic.TEXT_LEFT),
    (logic.TEXT_ALIGN_LABELS[logic.TEXT_CENTER], logic.TEXT_CENTER),
)

MISSING_CHOICES = (
    (u'該類型沒有的參數整行省略（建議）', False),
    (u'留一行空值，讓每一格行數一致', True),
)


def _build_kind_spec(doc):
    """第一個視窗：要收哪些類型。

    參數清單是所選類型的聯集，必須先知道選了哪些類型才列得出來，
    所以分兩段——這是真的相依，不是多問一次。
    """
    views = legend.legend_views(doc)
    if not views:
        return None, (u'這個專案沒有圖例（Legend）視圖。\n\n'
                      u'Revit API 無法從零建立圖例視圖，請先在專案瀏覽器裡'
                      u'手動建立一張，再執行本按鈕。')

    fields = [
        uilogic.section(u'要收哪些門窗'),
        uilogic.choice('kinds', u'品類', KIND_CHOICES,
                       default=(legend.DOOR, legend.WINDOW)),
        uilogic.choice('only_used', u'範圍', USED_CHOICES, default=True,
                       help=u'一個專案常常載入幾十個沒在用的族群，'
                            u'全部畫進圖例表會讓看圖的人以為那些都要施作。'),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'依 domain/door-window-legend-workflow.md 的 seed 複製法',
        badge=uilogic.BADGE_READONLY,
        run_label=u'下一步：挑類型與參數',
        footnote=u'這一步只是讀取，還不會動到模型。',
        width=860, height=520), u''


def _build_main_spec(doc, symbol_options, parameter_names, view_options,
                     note_options):
    fields = [
        uilogic.section(u'類型'),
        uilogic.multichoice('symbols', u'要放進圖例的門窗類型（可複選）',
                            symbol_options, required=True),

        uilogic.section(u'參數', u'圖例元件無法被 tag，參數只能寫成文字。'),
        uilogic.multichoice('parameters', u'要列在元件下方的參數（可複選）',
                            [(name, name) for name in parameter_names],
                            help=u'清單是所選類型的**聯集**；某個類型沒有的'
                                 u'參數，執行後會列在報告裡而不是靜默消失。'),
        uilogic.choice('include_missing', u'類型缺少某個參數時', MISSING_CHOICES,
                       default=False),
        uilogic.choice('note_type', u'文字類型', note_options,
                       required=False),
        uilogic.choice('text_align', u'文字對齊', TEXT_ALIGN_CHOICES,
                       default=logic.TEXT_LEFT),

        uilogic.section(u'圖例視圖與 seed',
                        u'API 無法直接建立圖例元件，只能複製一個既有的再改'
                        u'它的類型參數。顯示方向與細緻度會跟著 seed 一起複製'
                        u'——要立面圖例，就把 seed 設成立面。'),
        uilogic.choice('view', u'畫在哪一張圖例視圖',
                       [(PICK_ME, None)] + list(view_options)),
        uilogic.choice('seed', u'seed 從哪裡來', SEED_CHOICES),

        uilogic.section(u'排版'),
        uilogic.choice('direction', u'排版方向', LAYOUT_CHOICES),
        uilogic.number('per_line', u'每列（欄）幾個', default=5, minimum=1,
                       integer=True),
        uilogic.number('gap_x', u'水平間距', default=logic.DEFAULT_GAP_X_MM,
                       minimum=0, unit=u'mm',
                       help=u'間距量的是**元件邊界之間的空隙**，不是中心距——'
                            u'元件寬度不一，等中心距會讓寬的幾乎貼在一起。'),
        uilogic.number('gap_y', u'列（欄）間距', default=logic.DEFAULT_GAP_Y_MM,
                       minimum=0, unit=u'mm'),
        uilogic.number('text_gap', u'文字與元件的距離',
                       default=logic.DEFAULT_TEXT_GAP_MM, minimum=0,
                       unit=u'mm'),
        uilogic.number('text_height', u'預留給文字的高度', default=900.0,
                       minimum=0, unit=u'mm',
                       help=u'排下一列時要讓開文字佔的高度。太小會讓上一列的'
                            u'文字壓到下一列的元件。'),

        uilogic.note(
            u'**底部對齊**：同一列所有元件的邊界框底緣放在同一條線上。'
            u'一扇 300 cm 的窗和一扇 210 cm 的門並排時，置中會讓窗台浮在不同'
            u'高度、置頂會讓門懸空——門窗立面都站在樓板上，底部才是共同基準。',
            tone='info'),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'放置圖例元件並在下方列出選定的參數',
        badge=uilogic.BADGE_WRITE,
        run_label=u'預覽',
        footnote=u'寫入前一定會先預覽並由你確認；單一交易，全有全無。',
        width=1020, height=860)


def _measure(doc, view, pairs):
    """``([item], [blocked])``——量出每個新元件在圖例視圖裡的邊界框。"""
    items = []
    blocked = []
    for element_id, row in pairs:
        element = doc.GetElement(element_id)
        box = legend.bounding_box_mm(element, view) if element else None
        if box is None:
            blocked.append({'record': row, 'reason': logic.BLOCK_NO_BOX})
            continue
        items.append({
            'id': element_id,
            'label': row.get('label') or u'',
            'text': row.get('text') or u'',
            'min_x_mm': box[0],
            'min_y_mm': box[1],
            'width_mm': box[2],
            'height_mm': box[3],
        })
    return items, blocked


def _print_report(plan, view_label, placed, notes, blocked, bounds):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    output.print_md(logic.plan_lines(plan, view_label))
    if bounds:
        output.print_md(
            u'圖例整體佔用範圍約 **{:.0f} × {:.0f} mm**（未含文字寬度）。'
            .format(bounds[2] - bounds[0], bounds[3] - bounds[1]))
    output.print_md(u'已放置 {} 個圖例元件、{} 則參數文字。'.format(placed,
                                                            notes))

    shortfall = [row for row in plan['rows'] if row.get('missing')]
    if shortfall:
        output.print_md(u'### 缺少參數的類型（那幾行沒有印出來）')
        output.print_table(
            table_data=[[row['label'], u'、'.join(row['missing'])]
                        for row in shortfall],
            columns=[u'類型', u'缺少的參數'])

    if blocked:
        output.print_md(u'### 未放置的類型')
        output.print_table(
            table_data=[[(entry['record'].get('label')
                          if isinstance(entry.get('record'), dict) else u''),
                         entry['reason']] for entry in blocked],
            columns=[u'類型', u'原因'])


def main():
    doc = revit.doc
    uidoc = revit.uidoc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行。',
                    title=TITLE, exitscript=True)

    kind_spec, problem = _build_kind_spec(doc)
    if kind_spec is None:
        forms.alert(problem, title=TITLE)
        return
    picked = ui.ask(kind_spec)
    if picked is None:
        return

    symbols = legend.door_window_symbols(doc, kinds=picked['kinds'],
                                         only_used=picked['only_used'])
    if not symbols:
        forms.alert(u'找不到符合條件的門窗類型。', title=TITLE)
        return
    records = legend.symbol_records(symbols)
    parameter_names = logic.parameter_union(records)
    by_id = dict((row['id'], row) for row in records)
    view_options = legend.legend_views(doc)

    values = ui.ask(_build_main_spec(
        doc,
        [(row['label'], row['id']) for row in records],
        parameter_names,
        view_options,
        [(u'（用專案預設）', None)] + legend.text_note_types(doc)))
    if values is None:
        return

    view = values['view']
    direction = values['direction']
    if view is None or direction is None:
        # domain：不得自動選 seed、不得自動補排版方向。這裡不代填，只說明。
        forms.alert(u'「圖例視圖」與「排版方向」都必須明確指定，'
                    u'本工具不會替你選。', title=TITLE)
        return
    seed_mode = values['seed']
    if seed_mode is None:
        forms.alert(u'請指定 seed 從哪裡來。', title=TITLE)
        return

    chosen = [by_id[value] for value in values['symbols'] if value in by_id]
    plan = logic.build_plan(chosen, values['parameters'], values['per_line'],
                            direction, include_missing=values['include_missing'])
    view_label = uilogic.label_for_value(view_options, view) or u'(未命名)'

    if not logic.has_work(plan):
        forms.alert(u'【預覽】沒有要放置的類型，模型未變更。', title=TITLE)
        return

    if not forms.alert(
            u'【預覽】模型目前未變更。\n\n{}\n\n確定要放置嗎？'.format(
                logic.plan_lines(plan, view_label)),
            title=TITLE, yes=True, no=True):
        return

    # --- seed：一定在交易之外 -------------------------------------------
    existing = legend.legend_components(doc, view)
    if seed_mode == SEED_EXISTING:
        if not existing:
            forms.alert(
                u'「{}」裡沒有任何圖例元件可以當 seed。\n\n'
                u'API 無法從零建立圖例元件，請改選「我自己點一下放置第一個」，'
                u'或先手動拖一個圖例構件進這張視圖。'.format(view_label),
                title=TITLE)
            return
        seed = existing[0]
    else:
        try:
            uidoc.ActiveView = view
        except Exception:
            forms.alert(u'無法切換到「{}」，請先手動開啟該視圖再試。'.format(
                view_label), title=TITLE)
            return
        first = doc.GetElement(DB.ElementId(int(plan['rows'][0]['id'])))
        seed = legend.prompt_place_seed(uidoc, first)
        if seed is None:
            forms.alert(u'沒有放置任何元件，已取消。', title=TITLE)
            return

    origin = (0.0, 0.0)
    box = legend.bounding_box_mm(seed['element'], view)
    if box is not None:
        # 「放置在圖例中點選的位置」——使用者點的那一下就是排版原點。
        origin = (box[0], box[1] + box[3])

    note_type = values['note_type'] or legend.default_text_note_type(doc)
    if values['parameters'] and note_type is None:
        forms.alert(u'讀不到可用的文字類型，無法寫參數文字。', title=TITLE)
        return

    transaction = DB.Transaction(doc, TITLE)
    try:
        transaction.Start()
        pairs = []
        blocked = list(plan['blocked'])
        for row in plan['rows']:
            new_id, failure = legend.copy_and_retarget(
                doc, seed['element_id'], DB.ElementId(int(row['id'])))
            if new_id is None:
                blocked.append({'record': row,
                                'reason': logic.BLOCK_COPY_FAILED})
                continue
            if failure == u'retarget':
                blocked.append({'record': row,
                                'reason': logic.BLOCK_RETARGET_FAILED})
                continue
            pairs.append((new_id, row))
        doc.Regenerate()

        items, unmeasured = _measure(doc, view, pairs)
        blocked.extend(unmeasured)
        moves = logic.plan_layout(
            items, plan['per_line'], origin, direction=direction,
            gap_x_mm=values['gap_x'], gap_y_mm=values['gap_y'],
            text_gap_mm=values['text_gap'], text_align=values['text_align'],
            text_height_mm=values['text_height'])

        notes = 0
        for move in moves:
            legend.move_element(doc, move['id'], move['dx_mm'], move['dy_mm'])
            if move['text'] and legend.create_note(
                    doc, view, move['text_x_mm'], move['text_y_mm'],
                    move['text'], note_type) is not None:
                notes += 1
        transaction.Commit()
    except Exception as error:
        try:
            if transaction.HasStarted():
                transaction.RollBack()
        except Exception:
            pass
        forms.alert(u'放置失敗，交易已完整回復，模型沒有留下半成品。\n\n{}'
                    .format(error), title=TITLE)
        return

    bounds = logic.bounds_of(moves, items)
    _print_report(plan, view_label, len(moves), notes, blocked, bounds)
    forms.alert(u'已在「{}」放置 {} 個圖例元件、{} 則參數文字。\n\n'
                u'明細已列在 pyRevit 輸出視窗。'.format(
                    view_label, len(moves), notes), title=TITLE)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
