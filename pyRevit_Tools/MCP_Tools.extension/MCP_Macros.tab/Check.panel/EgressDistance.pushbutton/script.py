# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""步行距離檢核（JAC 03.01）— read-only.

建築技術規則建築設計施工編 §93 二寫得很死：

    「自樓面居室之任一點至樓梯口之步行距離（**即隔間後之可行距離非直線距離**）」

括號裡那句話是整顆按鈕的形狀。**直線距離不只是近似，它錯在危險的方向**——
直線永遠不會大於實際要走的距離，所以用直線量會把不合格的平面判成合格。因此
這裡把樓層的可走空間格網化，從樓梯端點做多源 Dijkstra，量的是繞過隔間之後
真正要走的距離。

可走空間來自**房間邊界**，而房間邊界止於牆面，相鄰兩室天生不相連；門是它們
唯一的連接處，所以門的位置會補上一塊可走區域把兩側接起來（見
``egress_sources.collect_doors``）。

量到哪裡由 §93 末項決定，兩種都提供：直通樓梯之第一階（取樓梯輪廓）、或安全
梯的進入樓梯間防火門（以門編號關鍵字指定）。

門檻所需的四個條件——用途類組、是否第十五層以上、是否集合住宅複層式無出入口
樓層、是否非防火構造——**全部是專案事實，模型讀不到**，一律由使用者指定。猜
一個會讓整份報告的門檻是錯的。

UI 走共用視窗（``mcp_window``）。這顆按鈕特別需要「改條件重跑」：容許值取決於
四個互相影響的條件，用對話框連珠問，每次微調都得從第一題重來。

唯讀。唯一的副作用是可選地把有問題的房間選取起來。
"""

__title__ = u'步行距離\n檢核'
__author__ = 'RevitMCP'

from Autodesk.Revit import DB
from pyrevit import forms, revit, script
from System.Collections.Generic import List

import area_scheme_sources as sources
import egress_distance_logic as logic
import egress_sources as egress
import mcp_window as ui
import mcp_window_logic as uilogic


TITLE = u'步行距離檢核'

ENDPOINT_STAIRS = 'stairs'
ENDPOINT_DOORS = 'doors'

ENDPOINT_OPTIONS = (
    (u'直通樓梯之第一階（自動取樓梯輪廓）', ENDPOINT_STAIRS),
    (u'進入樓梯間之防火門（安全梯，依門編號關鍵字）', ENDPOINT_DOORS),
)

CONDITION_OPTIONS = (
    (u'本層為第十五層以上（§93 二（三））', 'floor15'),
    (u'集合住宅複層式構造之無出入口樓層（§93 二（四））', 'duplex'),
    (u'非防火構造或非使用不燃材料（§93 二（五））', 'combustible'),
)

DEFAULT_EXCLUDE = u'樓梯,梯廳,電梯,管道,機房,陽台'
DEFAULT_DOOR_KEYWORD = u'梯'


def _level_options(doc):
    """依高程排序的樓層選項。1F/2F/10F 用文字排會把 10F 排到中間。"""
    levels = sources.level_index(doc)
    ordered = sorted(levels.items(), key=lambda item: item[1][1])
    return [(u'{}　（{:+.0f} mm）'.format(name, elevation), level_id)
            for level_id, (name, elevation) in ordered], levels


def _build_spec(doc):
    level_options, levels = _level_options(doc)
    if not level_options:
        return None, None

    use_options = [(u'{}　→　{:.0f} 公尺'.format(label, limit / 1000.0), code)
                   for code, label, limit in logic.USE_GROUPS]

    fields = [
        uilogic.section(u'檢核範圍'),
        uilogic.choice('level', u'樓層', level_options),
        uilogic.text(
            'exclude', u'排除關鍵字（房間編號或名稱含這些字就不檢核）',
            default=DEFAULT_EXCLUDE,
            help=u'§93 規範的是「居室」，但模型分不出居室與非居室，'
                 u'因此由你指定要排除哪些。被排除的房間**仍然算可以走過去**'
                 u'——走廊常正好落在這個名單裡，把它們變成牆會讓整層斷成孤島。'),

        uilogic.section(u'容許步行距離（§93 二）',
                        u'以下四項都是專案事實，模型讀不到，必須由你指定。'
                        u'猜錯會讓整份報告的門檻是錯的。'),
        uilogic.choice('use_group', u'建築物用途類組', use_options,
                       default=logic.DEFAULT_USE_GROUP),
        uilogic.multichoice(
            'conditions', u'適用的加嚴條件（可複選，都不符合就全部不勾）',
            CONDITION_OPTIONS,
            help=u'§93 二（三）只點名三十與五十公尺，未提七十；'
                 u'因此 C 類的 70 公尺在第十五層以上照條文字面不遞減，'
                 u'報告會把這個理由寫出來讓你自行判斷。'),

        uilogic.section(u'量測終點（§93 末項）'),
        uilogic.choice('endpoint', u'步行距離量到哪裡', ENDPOINT_OPTIONS,
                       default=ENDPOINT_STAIRS,
                       help=logic.ENDPOINT_NOTE),
        uilogic.text('door_keyword', u'樓梯間防火門的編號／名稱關鍵字',
                     default=DEFAULT_DOOR_KEYWORD, required=True,
                     enabled_when=('endpoint', ENDPOINT_DOORS),
                     help=u'符合關鍵字的門會被當成量測終點，'
                          u'執行後報告會列出實際命中幾扇讓你核對。'),

        uilogic.section(u'取樣'),
        uilogic.number('cell', u'格點大小', default=logic.DEFAULT_CELL_MM,
                       minimum=logic.MIN_CELL_MM, maximum=logic.MAX_CELL_MM,
                       unit=u'mm',
                       help=u'越小越準也越慢。必須明顯小於門洞淨寬，'
                            u'否則一個門會被整格封起來，該側房間會變成'
                            u'「無法到達」。超出範圍會自動夾回並說明。'),
    ]

    spec = uilogic.spec(
        TITLE, fields,
        subtitle=u'建技規 §93 二 · 隔間後之可行距離，非直線距離',
        badge=uilogic.BADGE_READONLY,
        run_label=u'開始檢核',
        secondary_label=u'選取有問題的房間',
        footnote=u'唯讀。完整明細同時列在 pyRevit 輸出視窗，可點擊跳到元素。',
        width=1000, height=760)
    return spec, levels


def _door_targets(doors, keyword):
    hits = []
    for door in doors:
        text = u'{} {}'.format(door.get('mark') or u'', door.get('name') or u'')
        if keyword in text:
            hits.append(door)
    return hits


def _compute(doc, values, levels):
    """跑一次檢核。回傳 ``(result_dict, payload)``；``payload`` 給輸出視窗用。

    有任何一步走不下去就回 ``(None, message)``，由呼叫端顯示在狀態列——
    這比丟一個 modal 出來打斷「調參數再跑一次」的節奏好。
    """
    level_id = values.get('level')
    level_label = levels.get(level_id, (u'(未知樓層)', 0.0))[0]

    conditions = set(values.get('conditions') or [])
    limit_mm, limit_reasons = logic.limit_for(
        use_group=values.get('use_group'),
        floor_15_or_above='floor15' in conditions,
        duplex_no_exit_floor='duplex' in conditions,
        non_fire_resistant='combustible' in conditions)

    cell_mm, cell_note = logic.clamp_cell(values.get('cell'))
    notes = [cell_note] if cell_note else []

    rooms, skipped = egress.collect_rooms(doc, level_id=level_id)
    if not rooms:
        return None, u'「{}」這一層沒有可用的房間邊界。'.format(level_label)

    keywords = uilogic.split_keywords(values.get('exclude'))
    kept = []
    excluded = []
    for row in rooms:
        text = u'{} {}'.format(row.get('room_number') or u'',
                              row.get('room_name') or u'')
        hit = u''
        for keyword in keywords:
            if keyword in text:
                hit = keyword
                break
        if hit:
            excluded.append((row, hit))
        else:
            kept.append(row)
    if not kept:
        return None, u'所有房間都被關鍵字排除了，沒有東西可以檢核。'

    doors = egress.collect_doors(doc, level_id=level_id)
    target_loops = []
    target_discs = []

    if values.get('endpoint') == ENDPOINT_DOORS:
        endpoint_label = logic.ENDPOINT_STAIR_DOOR
        keyword = (values.get('door_keyword') or u'').strip()
        target_discs = _door_targets(doors, keyword)
        if not target_discs:
            return None, (u'這一層沒有編號或名稱含「{}」的門。'
                          u'請換一個關鍵字，或改用「直通樓梯之第一階」。'
                          .format(keyword))
        notes.append(u'命中 {} 扇樓梯間防火門。'.format(len(target_discs)))
    else:
        endpoint_label = logic.ENDPOINT_FIRST_STEP
        for stair in egress.collect_stairs(doc, level_id=level_id):
            target_loops.extend(stair.get('loops') or [])
        if not target_loops:
            return None, (u'「{}」這一層取不到樓梯輪廓。可能這層沒有樓梯，'
                          u'或樓梯的基準樓層不是這一層；也可以改用'
                          u'「進入樓梯間之防火門」指定終點。'.format(level_label))

    # 房間、門與樓梯必須共用同一個原點，否則格點對不齊，門就接不起來。
    all_loops = [row['loops'] for row in kept]
    all_loops.extend([row['loops'] for row, unused in excluded])
    all_loops.extend([[loop] for loop in target_loops])
    bounds = logic.loops_bounds(all_loops)
    if bounds is None:
        return None, u'取不到幾何範圍。'
    origin = (bounds[0] - cell_mm, bounds[1] - cell_mm)

    walkable = set()
    for row in kept:
        row['cells'] = logic.rasterize(row['loops'], origin, cell_mm)
        walkable |= row['cells']
    for row, unused in excluded:
        # 被排除的房間不列入檢核，但仍然是可以走過去的空間。
        walkable |= logic.rasterize(row['loops'], origin, cell_mm)

    assumed = 0
    for door in doors:
        walkable |= logic.disc_cells(door['point_xy'], door['radius_mm'],
                                     origin, cell_mm)
        if door.get('radius_assumed'):
            assumed += 1
    if assumed:
        notes.append(u'有 {} 扇門查不到宿主牆厚，連通半徑採預設 {:.0f} mm。'
                     .format(assumed, egress.FALLBACK_DOOR_RADIUS_MM))

    source_cells = set()
    for loop in target_loops:
        cells = logic.rasterize([loop], origin, cell_mm)
        walkable |= cells
        source_cells |= cells
    for door in target_discs:
        cells = logic.disc_cells(door['point_xy'], door['radius_mm'],
                                 origin, cell_mm)
        walkable |= cells
        source_cells |= cells
    if not source_cells:
        return None, u'終點取不到任何取樣點，請把格點調小再試。'

    distances = logic.distance_field(walkable, source_cells, cell_mm)
    outcome = logic.evaluate(kept, distances, limit_mm)

    summary = logic.summary_lines(outcome, limit_reasons, endpoint_label,
                                  cell_mm)
    summary.insert(0, u'樓層：{}　檢核 {} 室（另排除 {} 室）'.format(
        level_label, len(kept), len(excluded)))
    return outcome, {
        'summary': summary,
        'notes': notes,
        'skipped': skipped,
        'excluded': excluded,
        'level_label': level_label,
    }


def _rows_for_window(outcome):
    rows = []
    for row in outcome['rows']:
        distance = row.get('distance_mm')
        rows.append([
            row.get('room_number') or u'',
            row.get('room_name') or u'',
            row['verdict'],
            u'{:.2f}'.format(distance / 1000.0) if distance is not None
            else u'—',
            row.get('unreached_cells') or u'',
            row.get('reason') or u'',
        ])
    return rows


def _print_report(outcome, payload):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    for line in payload['summary']:
        output.print_md(line)
    for note in payload['notes']:
        output.print_md(u'> {}'.format(note))

    if outcome['rows']:
        output.print_md(u'### 逐室結果')
        data = []
        for row in outcome['rows']:
            distance = row.get('distance_mm')
            data.append([
                output.linkify(row['element_id']),
                row.get('room_number') or u'',
                row.get('room_name') or u'',
                row['verdict'],
                u'{:.2f}'.format(distance / 1000.0) if distance is not None
                else u'—',
                row.get('sample_count'),
                row.get('unreached_cells') or u'',
                row.get('reason') or u'',
            ])
        output.print_table(
            table_data=data,
            columns=[u'房間', u'編號', u'名稱', u'結果', u'步行距離(m)',
                     u'取樣點', u'走不到', u'說明'])

    if payload['excluded']:
        output.print_md(u'### 依關鍵字排除的房間（未檢核）')
        output.print_table(
            table_data=[[row.get('room_number') or u'',
                         row.get('room_name') or u'', keyword]
                        for row, keyword in payload['excluded']],
            columns=[u'編號', u'名稱', u'命中關鍵字'])

    if payload['skipped']:
        output.print_md(u'### 取不到邊界而未檢核的房間')
        output.print_table(
            table_data=[[label, reason] for label, reason in payload['skipped']],
            columns=[u'房間', u'原因'])


class _Runner(object):
    """把最後一次的結果留住，關窗後才知道要不要選取那些房間。"""

    def __init__(self, doc, levels):
        self.doc = doc
        self.levels = levels
        self.outcome = None

    def __call__(self, values, window):
        outcome, payload = _compute(self.doc, values, self.levels)
        if outcome is None:
            self.outcome = None
            window.status(payload, 'warning')
            return None
        self.outcome = outcome
        _print_report(outcome, payload)

        counts = outcome['counts']
        tone = 'danger' if outcome['failed'] else 'success'
        window.status(
            u'合格 {} 室、超過 {} 室、無法到達 {} 室、無法取樣 {} 室。'.format(
                counts.get(logic.VERDICT_PASS, 0),
                counts.get(logic.VERDICT_FAIL, 0),
                counts.get(logic.VERDICT_UNREACHABLE, 0),
                counts.get(logic.VERDICT_NO_CELLS, 0)), tone)
        return uilogic.result(
            summary_lines=payload['summary'] + payload['notes'],
            columns=[u'編號', u'名稱', u'結果', u'步行距離(m)', u'走不到', u'說明'],
            rows=_rows_for_window(outcome))


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行檢核。',
                    title=TITLE, exitscript=True)

    spec, levels = _build_spec(doc)
    if spec is None:
        forms.alert(u'這個專案讀不到任何樓層。', title=TITLE)
        return

    runner = _Runner(doc, levels)
    values, unused = ui.run(spec, runner)
    if values is None or runner.outcome is None:
        return

    if values.get('__secondary__') and runner.outcome['failed']:
        ids = List[DB.ElementId]()
        for row in runner.outcome['failed']:
            ids.Add(row['element_id'])
        revit.uidoc.Selection.SetElementIds(ids)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
