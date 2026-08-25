# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""步行距離檢核的純規則與路徑計算 — JAC 03.01.

法源是建築技術規則建築設計施工編 §93（直通樓梯之設置）第二款，並及於 §94
（避難層自樓梯口至屋外出入口）。條文的一句話決定了整個模組的形狀：

    「自樓面居室之任一點至樓梯口之步行距離（**即隔間後之可行距離非直線距離**）」

所以**直線距離是錯的，而且錯在危險的方向**——它永遠不會大於實際步行距離，
因此會把不合格的平面判成合格。本模組因此把樓層的可走空間格網化，用多源
Dijkstra 從樓梯端點往外量，量的是繞過隔間之後真正要走的距離。

三個刻意的保守選擇，因為這個檢核錯在「過寬」比錯在「過嚴」嚴重得多：

**八方向格網的距離會略為高估。** octile 距離相對真實最短路徑最多高估約 8%，
高估表示更容易判成不合格，由人複核；反過來的誤差會放走真正超標的平面。
不修正這個偏差，並在報告裡寫明。

**對角線不切牆角。** 只有在兩個相鄰的正交格點都可走時才允許斜走，否則路徑
會從兩道牆的交角「穿過去」，量出一條人走不了的捷徑。

**到不了的房間永遠不會是合格。** 格網有可能把一個窄門封起來而讓房間變成孤島。
那既可能是真的沒有路（真發現），也可能是取樣造成的假象（工具誤差），兩者都
需要人看，所以獨立成一種結果而不是「通過」。

長度單位一律毫米。
"""

import heapq
import math

from area_placement_logic import point_in_loops


# --- §93 二：容許步行距離 --------------------------------------------------

LIMIT_20_M = 20000.0
LIMIT_30_M = 30000.0
LIMIT_40_M = 40000.0
LIMIT_50_M = 50000.0
LIMIT_70_M = 70000.0

# (code, label, base_limit_mm) —— 依 §93 二（一）（二）逐字對應。
USE_GROUPS = (
    ('A', u'Ａ類（公共集會）', LIMIT_30_M),
    ('B-1', u'Ｂ－１組', LIMIT_30_M),
    ('B-2', u'Ｂ－２組', LIMIT_30_M),
    ('B-3', u'Ｂ－３組', LIMIT_30_M),
    ('D-1', u'Ｄ－１組', LIMIT_30_M),
    ('C-TV', u'Ｃ類：有現場觀眾之電視攝影場', LIMIT_30_M),
    ('C', u'Ｃ類（電視攝影場除外）', LIMIT_70_M),
    ('OTHER', u'前目規定以外用途之建築物', LIMIT_50_M),
)

USE_GROUP_LIMITS = dict((code, limit) for code, unused, limit in USE_GROUPS)
USE_GROUP_LABELS = dict((code, label) for code, label, unused in USE_GROUPS)

DEFAULT_USE_GROUP = 'OTHER'

# §93 二（三）只點名三十公尺與五十公尺兩種，**沒有提到七十公尺**。照條文字面
# 實作而不自行補齊，並在結果裡說明——替法規補一條它沒寫的規定不是工具的權限。
FLOOR_15_REDUCTION = {LIMIT_30_M: LIMIT_20_M, LIMIT_50_M: LIMIT_40_M}


def limit_for(use_group=DEFAULT_USE_GROUP, floor_15_or_above=False,
              duplex_no_exit_floor=False, non_fire_resistant=False):
    """容許步行距離（mm）與逐條理由。

    回傳 ``(limit_mm, [reason])``。四個旗標都是**專案事實**而非模型讀得到的
    東西，一律由使用者指定；猜錯用途類組會讓整份報告的門檻是錯的。
    """
    code = use_group if use_group in USE_GROUP_LIMITS else DEFAULT_USE_GROUP
    limit = USE_GROUP_LIMITS[code]
    reasons = [u'§93 二：{} → {:.0f} 公尺'.format(
        USE_GROUP_LABELS[code], limit / 1000.0)]

    if floor_15_or_above:
        reduced = FLOOR_15_REDUCTION.get(limit)
        if reduced is not None:
            reasons.append(u'§93 二（三）第十五層以上：{:.0f} → {:.0f} 公尺'
                           .format(limit / 1000.0, reduced / 1000.0))
            limit = reduced
        else:
            reasons.append(
                u'§93 二（三）只規定三十公尺者減為二十、五十公尺者減為四十，'
                u'未提及 {:.0f} 公尺，故不遞減（條文字面）'.format(
                    limit / 1000.0))

    if duplex_no_exit_floor and limit > LIMIT_40_M:
        reasons.append(u'§93 二（四）集合住宅複層式無出入口樓層：'
                       u'不得超過四十公尺')
        limit = LIMIT_40_M

    if non_fire_resistant and limit > LIMIT_30_M:
        reasons.append(u'§93 二（五）非防火構造或非不燃材料：'
                       u'不論任何用途減為三十公尺以下')
        limit = LIMIT_30_M

    return limit, reasons


def overlap_limit_mm(limit_mm):
    """§95 末項：二座樓梯之步行路徑重複部分不得大於容許距離的二分之一。

    本模組**只算出這個門檻值，不量測重複長度**。重複長度需要逐點還原兩條路徑
    再比對共同前段，而格網路徑在等值格點之間會擺盪，量出來的重複段可能偏短——
    偏短就是偏鬆，正是這個檢核不能犯的方向。所以門檻照報，量測留給人。
    """
    try:
        return float(limit_mm) / 2.0
    except (TypeError, ValueError):
        return 0.0


# --- §93 末項：量到哪裡 ----------------------------------------------------

ENDPOINT_FIRST_STEP = u'直通樓梯之第一階'
ENDPOINT_STAIR_DOOR = u'進入樓梯間之防火門（安全梯適用）'

ENDPOINT_NOTE = (
    u'§93 末項：步行距離應計算至直通樓梯之第一階；'
    u'但直通樓梯為安全梯者，得計算至進入樓梯間之防火門。')


# --- 格網 ------------------------------------------------------------------

DEFAULT_CELL_MM = 250.0
MIN_CELL_MM = 50.0

# 走廊與門洞常見淨寬約 800～1200 mm，取樣格點必須明顯小於它，否則一個門會被
# 整格封起來。這個上限不是精度偏好，是「別把通道取樣掉」的下限。
MAX_CELL_MM = 600.0

GRID_NOTE = (
    u'距離以格網最短路徑量測（八方向、對角線不切牆角），相對真實最短路徑'
    u'最多高估約 8%。高估會讓結果偏嚴而非偏鬆，因此不做修正。')

DIAGONAL = math.sqrt(2.0)


def _number(value, fallback=0.0):
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def clamp_cell(cell_mm):
    """把格點大小夾在可用範圍內，回傳 ``(cell_mm, note)``。"""
    value = _number(cell_mm, DEFAULT_CELL_MM)
    if value < MIN_CELL_MM:
        return MIN_CELL_MM, u'格點過小，已改為 {:.0f} mm'.format(MIN_CELL_MM)
    if value > MAX_CELL_MM:
        return MAX_CELL_MM, (
            u'格點大於 {:.0f} mm 會把門洞取樣掉，已改為 {:.0f} mm'
            .format(MAX_CELL_MM, MAX_CELL_MM))
    return value, u''


def loops_bounds(loops_list):
    """所有迴圈的整體外框 ``(min_x, min_y, max_x, max_y)``，空的話回 ``None``。"""
    xs = []
    ys = []
    for loops in loops_list or []:
        for loop in loops or []:
            for point in loop or []:
                xs.append(_number(point[0]))
                ys.append(_number(point[1]))
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def rasterize(loops, origin, cell_mm):
    """一個房間的可走格點集合。

    格點以其**中心**是否落在迴圈內判定，並沿用 ``point_in_loops`` 的偶奇規則，
    所以中庭這種洞會正確地判成外部而不是可走。
    """
    bounds = loops_bounds([loops])
    if bounds is None:
        return set()
    origin_x, origin_y = origin
    min_col = int(math.floor((bounds[0] - origin_x) / cell_mm))
    max_col = int(math.ceil((bounds[2] - origin_x) / cell_mm))
    min_row = int(math.floor((bounds[1] - origin_y) / cell_mm))
    max_row = int(math.ceil((bounds[3] - origin_y) / cell_mm))
    cells = set()
    for col in range(min_col, max_col + 1):
        x = origin_x + (col + 0.5) * cell_mm
        for row in range(min_row, max_row + 1):
            y = origin_y + (row + 0.5) * cell_mm
            if point_in_loops((x, y), loops):
                cells.add((col, row))
    return cells


def disc_cells(point, radius_mm, origin, cell_mm):
    """以一點為心的圓形格點集合——用來把門洞打通。

    房間邊界止於牆面，兩個相鄰房間的格點因此天生不相連。門是它們唯一的連接
    處，所以在門的位置補上一塊可走區域；半徑取牆厚的一半再加餘裕，讓兩側確實
    接上。補得太小會讓房間變孤島（結果是「無法到達」而非放行），補得太大會讓
    路徑穿牆——所以半徑由呼叫端依實際牆厚給，不在這裡猜。
    """
    if point is None:
        return set()
    radius = _number(radius_mm)
    if radius <= 0.0:
        return set()
    origin_x, origin_y = origin
    center_x = _number(point[0])
    center_y = _number(point[1])
    min_col = int(math.floor((center_x - radius - origin_x) / cell_mm))
    max_col = int(math.ceil((center_x + radius - origin_x) / cell_mm))
    min_row = int(math.floor((center_y - radius - origin_y) / cell_mm))
    max_row = int(math.ceil((center_y + radius - origin_y) / cell_mm))
    cells = set()
    for col in range(min_col, max_col + 1):
        x = origin_x + (col + 0.5) * cell_mm
        for row in range(min_row, max_row + 1):
            y = origin_y + (row + 0.5) * cell_mm
            if (x - center_x) ** 2 + (y - center_y) ** 2 <= radius ** 2:
                cells.add((col, row))
    return cells


ORTHOGONAL = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIAGONALS = ((1, 1), (1, -1), (-1, 1), (-1, -1))


def distance_field(walkable, sources, cell_mm):
    """多源 Dijkstra，回傳 ``{cell: distance_mm}``。

    八方向，斜走成本 √2；**只有在兩個相鄰正交格點都可走時才允許斜走**，
    否則路徑會從兩道牆的交角穿過去，量出一條人走不了的捷徑。
    """
    distances = {}
    heap = []
    for cell in sources or ():
        if cell in walkable and cell not in distances:
            distances[cell] = 0.0
            heap.append((0.0, cell))
    heapq.heapify(heap)

    step = _number(cell_mm, DEFAULT_CELL_MM)
    while heap:
        current, cell = heapq.heappop(heap)
        if current > distances.get(cell, float('inf')):
            continue
        col, row = cell
        for delta_col, delta_row in ORTHOGONAL:
            neighbour = (col + delta_col, row + delta_row)
            if neighbour not in walkable:
                continue
            candidate = current + step
            if candidate < distances.get(neighbour, float('inf')):
                distances[neighbour] = candidate
                heapq.heappush(heap, (candidate, neighbour))
        for delta_col, delta_row in DIAGONALS:
            neighbour = (col + delta_col, row + delta_row)
            if neighbour not in walkable:
                continue
            if ((col + delta_col, row) not in walkable
                    or (col, row + delta_row) not in walkable):
                continue
            candidate = current + step * DIAGONAL
            if candidate < distances.get(neighbour, float('inf')):
                distances[neighbour] = candidate
                heapq.heappush(heap, (candidate, neighbour))
    return distances


# --- 判定 ------------------------------------------------------------------

VERDICT_PASS = u'合格'
VERDICT_FAIL = u'超過'
VERDICT_UNREACHABLE = u'無法到達'
VERDICT_NO_CELLS = u'無法取樣'

FAILING_VERDICTS = (VERDICT_FAIL, VERDICT_UNREACHABLE, VERDICT_NO_CELLS)

REASON_NO_CELLS = (
    u'房間在此格點大小下取不到任何取樣點（房間過小或邊界未封閉），'
    u'請縮小格點或檢查房間邊界。')
REASON_UNREACHABLE = (
    u'房間有取樣點走不到任何樓梯端點。可能是真的沒有路徑，'
    u'也可能是格點把門洞封住；兩種都需要人看，因此不列為合格。')


def evaluate_room(cells, distances, limit_mm):
    """單一房間的結果 ``(verdict, worst_mm, unreached_count, reason)``。

    量的是房間內**最遠的一個取樣點**，因為 §93 說的是「自樓面居室之任一點」。
    """
    if not cells:
        return VERDICT_NO_CELLS, None, 0, REASON_NO_CELLS
    reached = []
    unreached = 0
    for cell in cells:
        value = distances.get(cell)
        if value is None:
            unreached += 1
        else:
            reached.append(value)
    if unreached:
        worst = max(reached) if reached else None
        return VERDICT_UNREACHABLE, worst, unreached, REASON_UNREACHABLE
    worst = max(reached)
    if worst > _number(limit_mm):
        return (VERDICT_FAIL, worst, 0,
                u'超出容許值 {:.2f} 公尺'.format(
                    (worst - _number(limit_mm)) / 1000.0))
    return VERDICT_PASS, worst, 0, u''


def evaluate(rooms, distances, limit_mm):
    """逐室評定並附上摘要。

    ``rooms`` 為 ``[{'id','room_number','room_name','cells'}]``。
    回傳的每一列都帶原始欄位，呼叫端不需要再對照一次。
    """
    rows = []
    counts = {}
    for room in rooms or []:
        verdict, worst, unreached, reason = evaluate_room(
            room.get('cells'), distances, limit_mm)
        row = dict(room)
        row.pop('cells', None)
        row['verdict'] = verdict
        row['distance_mm'] = worst
        row['unreached_cells'] = unreached
        row['reason'] = reason
        row['sample_count'] = len(room.get('cells') or ())
        rows.append(row)
        counts[verdict] = counts.get(verdict, 0) + 1
    rows.sort(key=sort_key)
    return {
        'rows': rows,
        'counts': counts,
        'limit_mm': _number(limit_mm),
        'overlap_limit_mm': overlap_limit_mm(limit_mm),
        'failed': [row for row in rows if row['verdict'] in FAILING_VERDICTS],
    }


VERDICT_ORDER = {VERDICT_FAIL: 0, VERDICT_UNREACHABLE: 1,
                 VERDICT_NO_CELLS: 2, VERDICT_PASS: 3}


def sort_key(row):
    """最需要看的排最前：先超過、再無法到達／取樣，同類再依距離由遠而近。"""
    distance = row.get('distance_mm')
    # 距離未知時排在同類的最前面——沒有數字比有數字更需要人看。
    ranked = -distance if distance is not None else float('-inf')
    return (VERDICT_ORDER.get(row.get('verdict'), 9), ranked,
            u'{}'.format(row.get('room_number') or u''))


def summary_lines(result, limit_reasons=None, endpoint=u'', cell_mm=0.0):
    """報告開頭那幾行：門檻怎麼來的、量到哪裡、用多大的格點。"""
    lines = [u'容許步行距離：{:.1f} 公尺'.format(
        result.get('limit_mm', 0.0) / 1000.0)]
    for reason in limit_reasons or []:
        lines.append(u'　- {}'.format(reason))
    if endpoint:
        lines.append(u'量測終點：{}'.format(endpoint))
        lines.append(u'　- {}'.format(ENDPOINT_NOTE))
    if cell_mm:
        lines.append(u'取樣格點：{:.0f} mm'.format(_number(cell_mm)))
    lines.append(GRID_NOTE)
    counts = result.get('counts') or {}
    lines.append(u'結果：合格 {} 室、超過 {} 室、無法到達 {} 室、無法取樣 {} 室'
                 .format(counts.get(VERDICT_PASS, 0),
                         counts.get(VERDICT_FAIL, 0),
                         counts.get(VERDICT_UNREACHABLE, 0),
                         counts.get(VERDICT_NO_CELLS, 0)))
    lines.append(u'§95 末項：二座樓梯之步行路徑重複部分不得大於 {:.1f} 公尺'
                 u'（容許值二分之一）。本工具只算出此門檻，未量測重複長度。'
                 .format(result.get('overlap_limit_mm', 0.0) / 1000.0))
    return lines
