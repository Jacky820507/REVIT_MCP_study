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
梯的進入樓梯間防火門。

**哪幾座樓梯算數，由使用者勾選。** §93 規範的是**直通樓梯**，而一座三階的
室內高差踏階同樣是 Stairs 元素——把它當成量測終點，它附近的房間會全部被判成
合格，正是這個檢核最不能犯的錯。工具以「頂端有沒有接到上一層樓板」自動分類
並預先勾選，但那只是建議：分類理由會寫在每一行上，勾選權在人。

防火門也不再靠命名關鍵字：所選樓梯的重心落在哪個房間裡，那間就是梯間，
其上的門就是終點。關鍵字要求全案命名習慣一致，幾何不用。

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
ENDPOINT_EXIT = 'exit'

ENDPOINT_OPTIONS = (
    (u'§93：居室任一點 → 直通樓梯之第一階（取所選樓梯的輪廓）',
     ENDPOINT_STAIRS),
    (u'§93 但書：居室任一點 → 進入樓梯間之防火門（安全梯）', ENDPOINT_DOORS),
    (u'§94：樓梯口 → 屋外出入口（避難層適用，受檢對象改為樓梯）',
     ENDPOINT_EXIT),
)

CONDITION_OPTIONS = (
    (u'本層為第十五層以上（§93 二（三））', 'floor15'),
    (u'集合住宅複層式構造之無出入口樓層（§93 二（四））', 'duplex'),
    (u'非防火構造或非使用不燃材料（§93 二（五））', 'combustible'),
)

# 兩排分開，因為「法條這樣寫」跟「大家習慣這樣做」不是同一件事：
# 上排改了就不合 §1 十九，下排可以依專案調整。
DEFAULT_STATUTORY = u'，'.join(logic.NON_HABITABLE_STATUTORY)
DEFAULT_CONVENTION = u'，'.join(logic.NON_HABITABLE_CONVENTION)


def _level_options(doc):
    """依高程排序的樓層選項。1F/2F/10F 用文字排會把 10F 排到中間。"""
    levels = sources.level_index(doc)
    ordered = sorted(levels.items(), key=lambda item: item[1][1])
    return [(u'{}　（{:+.0f} mm）'.format(name, elevation), level_id)
            for level_id, (name, elevation) in ordered], levels


def _build_spec(doc):
    level_options, levels = _level_options(doc)
    if not level_options:
        return None, None, None, None

    # 房間清單也要先全部收齊：選項不能隨樓層欄位重建，所以列全案並在標籤上
    # 標出樓層，執行時再依所選樓層過濾。
    every_room, unused_skipped = egress.collect_rooms(doc)
    rooms = logic.describe_rooms(every_room)
    room_options = [(logic.room_label(row), row['id']) for row in rooms]

    # 樓梯要先全部收齊、比對過樓層高程才分類得出來，所以這裡不依樓層過濾。
    elevations = [entry[1] for entry in levels.values()]
    stairs = logic.describe_stairs(egress.collect_stairs(doc), elevations)
    for row in stairs:
        row['base_level'] = levels.get(row.get('base_level_id'),
                                       (u'(無基準樓層)', 0.0))[0]

    # 預設避難層取最低的那一層，只為了先算出建議勾選；使用者在視窗裡改了
    # 避難層之後，執行時會用實際選的重算並在報告裡說明。
    lowest = level_options[0][1] if level_options else None
    stairs = logic.apply_refuge_test(stairs, lowest)
    stair_options = [(u'{}　｜　{}'.format(logic.stair_label(row),
                                        row.get('refuge_note') or u''),
                      row['id']) for row in stairs]

    use_options = [(u'{}　→　{:.0f} 公尺'.format(label, limit / 1000.0), code)
                   for code, label, limit in logic.USE_GROUPS]

    fields = [
        uilogic.section(u'檢核範圍'),
        uilogic.choice('level', u'樓層', level_options),

        uilogic.section(u'要檢核哪些房間（§1 十九「居室」）'),
        uilogic.note(logic.HABITABLE_NOTE, tone='info'),
        uilogic.note(
            u'**下面的建議會漏，所以最終由你勾。** 設計者不會照條文用詞命名：'
            u'一間「備品室」實質是儲藏室、「鼓風機室」實質是機械室，'
            u'兩者都不會被「儲藏室」「機械室」這兩個詞命中。'
            u'清單已標出每一間的建議與依據，請照實際用途調整。', tone='warning'),
        uilogic.multichoice(
            'rooms', u'要檢核的房間（可複選）', room_options,
            default=logic.suggested_room_ids(rooms), required=True,
            help=u'清單含全專案的房間，執行時只用屬於所選樓層的那些。'
                 u'**沒勾的房間仍然算可以走過去**——走廊與門廳正好都在條文的'
                 u'排除清單裡，把它們變成牆會讓整層樓斷成孤島。'
                 u'不勾的意思是「不檢核它」，不是「走不過去」。'),

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
        uilogic.choice('endpoint', u'要檢核哪一條規定', ENDPOINT_OPTIONS,
                       default=ENDPOINT_STAIRS,
                       help=logic.ENDPOINT_NOTE),
        uilogic.note(logic.ARTICLE_94_NOTE, tone='info'),

        uilogic.section(u'哪幾座算直通樓梯（§1 三十九）'),
        uilogic.note(logic.STAIR_NOTE, tone='warning'),
        uilogic.note(logic.REFUGE_NOTE, tone='info'),
        uilogic.choice('refuge', u'避難層（§1 三十四：有出入口通達地面之樓層）',
                       level_options,
                       help=u'指定之後，工具會沿著樓梯一層層往下追；'
                            u'追不到避難層的一律取消建議勾選。'),
        uilogic.multichoice(
            'stairs', u'計入步行距離的樓梯（可複選）', stair_options,
            default=logic.suggested_stair_ids(stairs), required=True,
            help=u'預設只勾選「連通上層」的那些。清單含全專案的樓梯；'
                 u'執行時只會用到基準層或頂層等於所選樓層的那幾座，'
                 u'其餘會在報告裡說明為什麼沒用到。'),

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
        width=1040, height=860)
    return spec, levels, stairs, rooms


def _enclosure_rooms(stairs, rooms):
    """所選樓梯落在哪些房間裡——那些就是梯間。

    用樓梯輪廓的重心去問「這一點在哪個房間的邊界內」，比關鍵字可靠：
    關鍵字要求命名習慣一致，而重心用的是幾何。找不到房間的樓梯會被回報，
    不會靜默略過。
    """
    found = []
    missed = []
    for stair in stairs:
        centre = egress.loops_centroid(stair.get('loops'))
        hit = None
        if centre is not None:
            for room in rooms:
                if logic.point_in_loops(centre, room.get('loops')):
                    hit = room
                    break
        if hit is None:
            missed.append(stair)
        elif hit not in found:
            found.append(hit)
    return found, missed


def _doors_opening_onto(doors, room_cells, origin, cell_mm):
    """門的連通圓與梯間房間的格點有交集，就是通往那個梯間的門。

    這裡直接重用已經算好的兩組格點，不另外做點到多邊形的距離計算；門本來就
    畫在牆上（也就是房間邊界上），用「圓盤有沒有碰到房間」比用「門心在不在
    房間內」穩定得多。
    """
    hits = []
    for door in doors:
        cells = logic.disc_cells(door['point_xy'], door['radius_mm'],
                                 origin, cell_mm)
        if cells & room_cells:
            hits.append(door)
    return hits


def _compute(doc, values, levels, all_stairs, all_rooms):
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

    # 檢核哪幾間由勾選決定；沒勾的仍然是可以走過去的空間。
    chosen = set(values.get('rooms') or ())
    graded_rooms = dict((item['id'], item) for item in all_rooms or [])
    kept = []
    excluded = []
    for row in rooms:
        if row['id'] in chosen:
            kept.append(row)
        else:
            item = graded_rooms.get(row['id']) or {}
            reason = item.get('kind') or u'未勾選'
            if item.get('keyword'):
                reason = u'{}：{}'.format(reason, item['keyword'])
            excluded.append((row, reason))
    if not kept:
        return None, (u'這一層沒有任何被勾選的房間。'
                      u'請回設定頁勾選要檢核的房間。')

    doors = egress.collect_doors(doc, level_id=level_id)

    # 只用勾選、且基準層或頂層落在這一層的樓梯。§93 說的是**直通樓梯**——
    # 一座三階的室內高差踏階也有 Stairs 元素，把它當終點會讓附近房間全部
    # 變成合格，所以哪幾座算數由使用者勾，不由工具猜。
    # 使用者可能在視窗裡改了避難層，這裡用實際選的重跑 §1 三十九的追溯。
    refuge_id = values.get('refuge')
    graded = logic.apply_refuge_test(all_stairs, refuge_id)
    by_id = dict((row['id'], row) for row in graded)
    unreachable = [by_id[value].get('name') or u'(未命名)'
                   for value in (values.get('stairs') or ())
                   if value in by_id and not by_id[value].get('reaches_refuge')]
    if unreachable:
        notes.append(
            u'勾選的樓梯裡有 {} 座依 §1 三十九追不到避難層「{}」：{}。'
            u'仍照你的勾選計算，但那幾座嚴格說不是直通樓梯。'.format(
                len(unreachable),
                levels.get(refuge_id, (u'(未指定)', 0.0))[0],
                u'、'.join(unreachable)))

    used_stairs, other_level = logic.stairs_for_level(
        graded, level_id, values.get('stairs'))
    if not used_stairs:
        if other_level:
            return None, (u'勾選的 {} 座樓梯都不屬於「{}」這一層'
                          u'（基準層與頂層都不是）。'
                          .format(len(other_level), level_label))
        return None, u'沒有勾選任何樓梯，無法決定量測終點。'
    if other_level:
        notes.append(u'另有 {} 座勾選的樓梯不屬於這一層，未列入計算。'
                     .format(len(other_level)))

    target_loops = []
    for stair in used_stairs:
        target_loops.extend(stair.get('loops') or [])
    if not target_loops:
        return None, (u'所選的 {} 座樓梯在「{}」都取不到輪廓。'
                      .format(len(used_stairs), level_label))

    # 房間、門與樓梯必須共用同一個原點，否則格點對不齊，門就接不起來。
    all_loops = [row['loops'] for row in kept]
    all_loops.extend([row['loops'] for row, unused in excluded])
    all_loops.extend([[loop] for loop in target_loops])
    bounds = logic.loops_bounds(all_loops)
    if bounds is None:
        return None, u'取不到幾何範圍。'
    origin = (bounds[0] - cell_mm, bounds[1] - cell_mm)

    walkable = set()
    room_cells = {}
    for row in kept:
        row['cells'] = logic.rasterize(row['loops'], origin, cell_mm)
        room_cells[row['id']] = row['cells']
        walkable |= row['cells']
    for row, unused in excluded:
        # 被排除的房間不列入檢核，但仍然是可以走過去的空間。
        cells = logic.rasterize(row['loops'], origin, cell_mm)
        room_cells[row['id']] = cells
        walkable |= cells

    assumed = 0
    for door in doors:
        walkable |= logic.disc_cells(door['point_xy'], door['radius_mm'],
                                     origin, cell_mm)
        if door.get('radius_assumed'):
            assumed += 1
    if assumed:
        notes.append(u'有 {} 扇門查不到宿主牆厚，連通半徑採預設 {:.0f} mm。'
                     .format(assumed, egress.FALLBACK_DOOR_RADIUS_MM))

    stair_cells = set()
    cells_by_stair = {}
    for stair in used_stairs:
        own = set()
        for loop in stair.get('loops') or []:
            own |= logic.rasterize([loop], origin, cell_mm)
        cells_by_stair[stair.get('id')] = own
        walkable |= own
        stair_cells |= own

    endpoint_rows = []
    subjects = kept
    if values.get('endpoint') == ENDPOINT_EXIT:
        # §94 量的是**不同的東西**：從樓梯口到屋外出入口，所以受檢對象是
        # 樓梯而不是房間。房間仍然是可走空間，只是不列入評定。
        endpoint_label = logic.ENDPOINT_OUTSIDE_EXIT
        exits = [door for door in doors if door.get('exterior')]
        if not exits:
            return None, logic.EXIT_NO_DOOR
        notes.append(
            u'外牆上的門 {} 扇被當成屋外出入口（依宿主牆的牆類型「功能」＝外部'
            u'判定；設錯或沒設的牆會漏抓，請核對）。'.format(len(exits)))
        endpoint_rows = exits
        source_cells = set()
        for door in exits:
            cells = logic.disc_cells(door['point_xy'], door['radius_mm'],
                                     origin, cell_mm)
            walkable |= cells
            source_cells |= cells
        subjects = logic.stair_subjects(used_stairs, cells_by_stair)
        if not subjects:
            return None, logic.EXIT_NO_STAIR
    elif values.get('endpoint') == ENDPOINT_DOORS:
        endpoint_label = logic.ENDPOINT_STAIR_DOOR
        # 梯間由**幾何**認定：所選樓梯的重心落在哪個房間裡。這比關鍵字可靠，
        # 關鍵字要求全案命名習慣一致，而這裡只要房間畫得出來。
        every_room = kept + [row for row, unused in excluded]
        enclosures, missed = _enclosure_rooms(used_stairs, every_room)
        if missed:
            notes.append(u'有 {} 座樓梯的重心不落在任何房間內，'
                         u'找不到對應梯間（凹形梯間可能發生）。'
                         .format(len(missed)))
        if not enclosures:
            return None, (u'找不到所選樓梯所在的房間，無法推導樓梯間防火門。'
                          u'請確認梯間有畫房間，或改用「直通樓梯之第一階」。')
        enclosure_cells = set()
        for room in enclosures:
            enclosure_cells |= room_cells.get(room['id']) or set()
        hits = _doors_opening_onto(doors, enclosure_cells, origin, cell_mm)
        if not hits:
            return None, (u'梯間「{}」上找不到任何門。'
                          u'請確認門有畫，或改用「直通樓梯之第一階」。'
                          .format(u'、'.join(
                              room.get('room_name') or room.get('room_number')
                              or u'(無名稱)' for room in enclosures)))
        notes.append(u'梯間 {} 間，其上的門 {} 扇被當成量測終點。'.format(
            len(enclosures), len(hits)))
        endpoint_rows = hits
        source_cells = set()
        for door in hits:
            cells = logic.disc_cells(door['point_xy'], door['radius_mm'],
                                     origin, cell_mm)
            walkable |= cells
            source_cells |= cells
    else:
        endpoint_label = logic.ENDPOINT_FIRST_STEP
        source_cells = stair_cells

    if not source_cells:
        return None, u'終點取不到任何取樣點，請把格點調小再試。'

    distances = logic.distance_field(walkable, source_cells, cell_mm)
    outcome = logic.evaluate(subjects, distances, limit_mm)

    summary = logic.summary_lines(outcome, limit_reasons, endpoint_label,
                                  cell_mm)
    # 結論先講最不利那一條——實務上第一個問題是「最遠幾公尺、在哪、過不過」，
    # 而不是「每一間各是多少」。
    if values.get('endpoint') == ENDPOINT_EXIT:
        summary.insert(0, u'樓層：{}　受檢對象為 {} 座樓梯（§94）'.format(
            level_label, len(subjects)))
    else:
        summary.insert(0, u'樓層：{}　檢核 {} 室（另 {} 室未勾選）'.format(
            level_label, len(kept), len(excluded)))
    summary.insert(0, logic.headline(outcome))

    # 「換一個用途類組還過不過」是實務上緊接著會問的第二個問題，
    # 尤其混合用途的樓層——同一層裡不同使用單元的類組可能不同。
    worst = logic.worst_row(outcome)
    if worst is not None:
        summary.extend(logic.threshold_lines(worst.get('distance_mm')))
        tightest = logic.tightest_passing(worst.get('distance_mm'))
        if tightest is not None:
            summary.append(u'能通過的最嚴門檻是 {:.0f} 公尺——'
                           u'這代表這份平面還有多少餘地。'
                           .format(tightest[0] / 1000.0))
        else:
            summary.append(u'**§93 二的所有門檻都過不了**，'
                           u'不是換個類組就能解決的。')
    return outcome, {
        'summary': summary,
        'notes': notes,
        'skipped': skipped,
        'excluded': excluded,
        'level_label': level_label,
        'stairs': used_stairs,
        'endpoint_doors': endpoint_rows,
        'endpoint_mode': values.get('endpoint'),
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
        if payload.get('endpoint_mode') == ENDPOINT_EXIT:
            output.print_md(u'### 逐座樓梯結果（§94：樓梯口 → 屋外出入口）')
        else:
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

    if payload.get('stairs'):
        output.print_md(u'### 計入的樓梯')
        output.print_table(
            table_data=[[output.linkify(row['element_id']),
                         row.get('name') or u'', row.get('base_level') or u'',
                         row.get('kind') or u'', row.get('detail') or u'']
                        for row in payload['stairs']],
            columns=[u'樓梯', u'名稱', u'基準樓層', u'判定', u'依據'])

    if payload.get('endpoint_doors'):
        output.print_md(
            u'### 當成量測終點的屋外出入口'
            if payload.get('endpoint_mode') == ENDPOINT_EXIT
            else u'### 當成量測終點的樓梯間防火門')
        output.print_table(
            table_data=[[output.linkify(row['element_id']),
                         row.get('mark') or u'', row.get('name') or u'']
                        for row in payload['endpoint_doors']],
            columns=[u'門', u'編號', u'名稱'])

    if payload['excluded']:
        output.print_md(u'### 未勾選、因此未檢核的房間')
        output.print_md(u'未勾選不代表走不過去——這些房間仍計入可走空間。')
        output.print_md(
            u'「條文明列」是 §1 十九逐字寫出來的；「慣例」是條文沒寫、'
            u'由你指定的。兩者分開列，才看得出哪些是依法、哪些是判斷。')
        output.print_table(
            table_data=[[row.get('room_number') or u'',
                         row.get('room_name') or u'', reason]
                        for row, reason in payload['excluded']],
            columns=[u'編號', u'名稱', u'判定依據'])

    if payload['skipped']:
        output.print_md(u'### 取不到邊界而未檢核的房間')
        output.print_table(
            table_data=[[label, reason] for label, reason in payload['skipped']],
            columns=[u'房間', u'原因'])


class _Runner(object):
    """把最後一次的結果留住，關窗後才知道要不要選取那些房間。"""

    def __init__(self, doc, levels, stairs, rooms):
        self.doc = doc
        self.levels = levels
        self.stairs = stairs
        self.rooms = rooms
        self.outcome = None

    def __call__(self, values, window):
        outcome, payload = _compute(self.doc, values, self.levels,
                                    self.stairs, self.rooms)
        if outcome is None:
            self.outcome = None
            window.status(payload, 'warning')
            return None
        self.outcome = outcome
        _print_report(outcome, payload)

        counts = outcome['counts']
        tone = 'danger' if outcome['failed'] else 'success'
        window.status(
            u'{}\n合格 {} 室、超過 {} 室、無法到達 {} 室、無法取樣 {} 室。'.format(
                logic.headline(outcome),
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

    spec, levels, stairs, rooms = _build_spec(doc)
    if spec is None:
        forms.alert(u'這個專案讀不到任何樓層。', title=TITLE)
        return
    if not stairs:
        forms.alert(u'這個專案沒有任何樓梯，無法決定步行距離的量測終點。',
                    title=TITLE)
        return

    runner = _Runner(doc, levels, stairs, rooms)
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
