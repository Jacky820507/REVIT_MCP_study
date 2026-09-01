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


# --- 哪些樓梯算「直通樓梯」 ------------------------------------------------

STAIR_CONNECTS = u'連通上層'
STAIR_SHORT = u'未達上層'
STAIR_STEP = u'高差踏階'
STAIR_TOP = u'基準層之上無樓層'
STAIR_UNKNOWN = u'無法判定'

# 頂端與上一層樓板高程差在這個範圍內，視為「真的接上去了」。
# 樓板厚度、面層與結構偏移常讓兩者差幾十到兩百多 mm，不留容差會把正常的
# 樓梯全判成未達。
DEFAULT_REACH_TOLERANCE_MM = 300.0

# 上面沒有樓層可比對時的輔助判準：爬升低於這個高度的多半是室內高差踏階，
# 不是通往另一個樓層的直通樓梯。這是**啟發式**，所以只在無法做高程比對時
# 才動用，而且結果一律只是建議。
DEFAULT_MIN_STOREY_CLIMB_MM = 1500.0

STAIR_SUGGESTED = (STAIR_CONNECTS,)

STAIR_NOTE = (
    u'§93 規範的是**直通樓梯**。一座三階的室內高差踏階不是直通樓梯，'
    u'但它同樣有 Stairs 元素——把它當成量測終點，附近的房間會全部變成合格。'
    u'因此這裡以「頂端有沒有接到上一層樓板」判斷，並且**只給建議**：'
    u'要算哪幾座，由你勾選。')


def _next_level_above(elevation_mm, level_elevations, epsilon_mm=1.0):
    """基準高程之上最近的一個樓層高程；沒有就回 ``None``。"""
    target = _number(elevation_mm)
    above = [_number(value) for value in level_elevations or []
             if _number(value) > target + epsilon_mm]
    if not above:
        return None
    return min(above)


def classify_stair(record, level_elevations,
                   tolerance_mm=DEFAULT_REACH_TOLERANCE_MM,
                   min_climb_mm=DEFAULT_MIN_STOREY_CLIMB_MM):
    """``(kind, detail)``——這座樓梯像不像直通樓梯。

    主判準是**頂端有沒有接到上一層樓板**，因為那是客觀的高程比對；爬升高度
    只在「基準層之上根本沒有樓層」或「確定沒接到」時當輔助標籤用。

    ``record`` 需要 ``base_elevation_mm`` 與 ``top_elevation_mm``。
    """
    base = record.get('base_elevation_mm')
    top = record.get('top_elevation_mm')
    if base is None or top is None:
        return STAIR_UNKNOWN, u'讀不到基準或頂端高程'

    climb = _number(top) - _number(base)
    next_up = _next_level_above(base, level_elevations)
    if next_up is None:
        return STAIR_TOP, u'爬升 {:.0f} mm，但基準層之上沒有其他樓層'.format(
            climb)

    delta = _number(top) - next_up
    if abs(delta) <= _number(tolerance_mm, DEFAULT_REACH_TOLERANCE_MM):
        return STAIR_CONNECTS, u'爬升 {:.0f} mm，頂端與上層樓板差 {:+.0f} mm'.format(
            climb, delta)
    if climb < _number(min_climb_mm, DEFAULT_MIN_STOREY_CLIMB_MM):
        return STAIR_STEP, u'只爬升 {:.0f} mm，距上層樓板還差 {:.0f} mm'.format(
            climb, abs(delta))
    return STAIR_SHORT, u'爬升 {:.0f} mm，距上層樓板還差 {:.0f} mm'.format(
        climb, abs(delta))


def describe_stairs(records, level_elevations, **options):
    """逐座分類，回傳帶 ``kind``／``detail``／``suggested`` 的新清單。

    不改動輸入——呼叫端可能還要用原本的記錄。
    """
    rows = []
    for record in records or []:
        kind, detail = classify_stair(record, level_elevations, **options)
        row = dict(record)
        row['kind'] = kind
        row['detail'] = detail
        row['suggested'] = kind in STAIR_SUGGESTED
        rows.append(row)
    return rows


def suggested_stair_ids(rows):
    return [row['id'] for row in rows or [] if row.get('suggested')]


def stair_label(row):
    """勾選清單上那一行字：名稱、基準樓層、判定與理由。"""
    return u'{}　｜　{}　｜　{}（{}）'.format(
        row.get('name') or u'(未命名樓梯)',
        row.get('base_level') or u'(無基準樓層)',
        row.get('kind') or STAIR_UNKNOWN,
        row.get('detail') or u'')


def stairs_for_level(rows, level_id, chosen_ids):
    """``(used, other_level)``——勾選的樓梯裡，哪些屬於這一層。

    基準層或頂層任一等於被檢核的樓層就算數：一座 3F→4F 的樓梯，在 3F 是往上
    的那一跑、在 4F 是往下的那一跑，兩層都看得到同一個梯間。
    """
    chosen = set(chosen_ids or ())
    used = []
    other = []
    for row in rows or []:
        if row.get('id') not in chosen:
            continue
        if row.get('base_level_id') == level_id \
                or row.get('top_level_id') == level_id:
            used.append(row)
        else:
            other.append(row)
    return used, other


# --- §1 第十九款：哪些房間是「居室」 --------------------------------------

# 條文**逐字列舉**的不視為居室者。這不是慣例，是法條寫死的清單，
# 所以與下面的慣例清單分開——「法條這樣寫」跟「大家習慣這樣做」不是同一件事，
# 混在一起會讓使用者無法判斷哪一條可以改、哪一條改了就不合法。
NON_HABITABLE_STATUTORY = (
    u'門廳', u'走廊', u'樓梯間', u'衣帽間', u'廁所', u'盥洗室',
    u'浴室', u'儲藏室', u'機械室', u'車庫',
)

# 條文沒有列舉，但實務上通常也不當居室檢討的。預設帶入，可自行增刪。
NON_HABITABLE_CONVENTION = (
    u'梯廳', u'電梯', u'昇降機', u'管道', u'機房', u'配電', u'空調',
    u'陽台', u'陽臺', u'露台', u'露臺',
)

ROOM_HABITABLE = u'居室'
ROOM_NON_STATUTORY = u'非居室（§1 十九明列）'
ROOM_NON_CONVENTION = u'非居室（慣例，非條文明列）'

HABITABLE_NOTE = (
    u'§1 十九：「供居住、工作、集會、娛樂、烹飪等使用之房間，均稱居室。'
    u'門廳、走廊、樓梯間、衣帽間、廁所盥洗室、浴室、儲藏室、機械室、車庫等'
    u'不視為居室。」上排是**條文明列**的，改了就不合條文；'
    u'下排是條文沒寫、實務上通常也不算的，可自行增刪。')


def _matched_keyword(text, keywords):
    """命中的關鍵字，取**最長**的那一個；沒命中回 ``u''``。

    取最長是因為「樓梯間」與「樓梯」同時在清單裡時，報「樓梯間」才對得上
    條文的用語；報「樓梯」會讓人以為工具用的是別的判準。
    """
    haystack = u'{}'.format(text or u'')
    best = u''
    for keyword in keywords or ():
        if keyword and keyword in haystack and len(keyword) > len(best):
            best = keyword
    return best


def classify_room(text, statutory=NON_HABITABLE_STATUTORY,
                  convention=NON_HABITABLE_CONVENTION):
    """``(kind, keyword)``——這個房間名稱算不算居室。

    條文清單先比，因為它的效力比慣例高：一個叫「儲藏室兼機房」的房間，
    要報的是條文那一條。
    """
    hit = _matched_keyword(text, statutory)
    if hit:
        return ROOM_NON_STATUTORY, hit
    hit = _matched_keyword(text, convention)
    if hit:
        return ROOM_NON_CONVENTION, hit
    return ROOM_HABITABLE, u''


# --- §1 第三十九款：直通樓梯要能通達避難層 --------------------------------

STAIR_REACHES_REFUGE = u'可通達避難層'
STAIR_NO_REFUGE_PATH = u'通不到避難層'

REFUGE_NOTE = (
    u'§1 三十九：「直通樓梯：建築物地面以上或以下任一樓層可**直接通達避難層'
    u'或地面**之樓梯（包括坡道）。」所以「有沒有接到上一層」只是必要條件——'
    u'一座 5F→6F 但下方斷掉的樓梯接到了上層，卻通不到避難層。'
    u'指定避難層之後，工具會沿著樓梯一層一層往下追，追得到才算直通樓梯。')


def reaches_refuge(stair, stairs, refuge_level_id, seen=None):
    """這座樓梯順著往下走，接不接得到避難層。

    往下追的方式是「誰的頂層等於我的基準層」——那就是同一個梯間再往下的那一
    跑。``seen`` 擋住環（模型畫錯時，兩座樓梯可能互相指涉而無限遞迴）。
    """
    if stair is None:
        return False
    base = stair.get('base_level_id')
    if base is None:
        return False
    if base == refuge_level_id:
        return True
    visited = set(seen or ())
    key = stair.get('id')
    if key in visited:
        return False
    visited.add(key)
    for other in stairs or []:
        if other.get('top_level_id') == base:
            if reaches_refuge(other, stairs, refuge_level_id, visited):
                return True
    return False


def apply_refuge_test(rows, refuge_level_id):
    """在既有分類上再套 §1 三十九：追不到避難層的一律取消建議。

    只會**收緊**不會放寬——原本就不建議的（踏階、未達上層）不會因為追得到
    避難層而變成建議。條文是兩個條件都要滿足，不是二選一。
    """
    result = []
    for row in rows or []:
        item = dict(row)
        ok = reaches_refuge(row, rows, refuge_level_id)
        item['reaches_refuge'] = ok
        item['refuge_note'] = (STAIR_REACHES_REFUGE if ok
                               else STAIR_NO_REFUGE_PATH)
        if not ok:
            item['suggested'] = False
        result.append(item)
    return result


def describe_rooms(rooms, statutory=NON_HABITABLE_STATUTORY,
                   convention=NON_HABITABLE_CONVENTION):
    """逐間附上 §1 十九的建議判定。

    **關鍵字比對在真實專案上會漏。** 設計者不會照條文用詞命名：一間「備品室」
    實質是儲藏室、「鼓風機室」實質是機械室，兩者都不會被「儲藏室」「機械室」
    這兩個關鍵字命中。所以這裡產生的是**建議**，最終要檢核哪幾間由人勾選——
    這跟樓梯那邊採同一個立場，理由也一樣：猜錯的代價是靜默漏檢或誤檢。
    """
    rows = []
    for room in rooms or []:
        text = u'{} {}'.format(room.get('room_number') or u'',
                               room.get('room_name') or u'')
        kind, hit = classify_room(text, statutory, convention)
        row = dict(room)
        row['kind'] = kind
        row['keyword'] = hit
        row['suggested'] = kind == ROOM_HABITABLE
        rows.append(row)
    return rows


def suggested_room_ids(rows):
    return [row['id'] for row in rows or [] if row.get('suggested')]


def room_label(row):
    """勾選清單那一行：樓層、編號、名稱、面積與建議判定。"""
    area = row.get('area_m2')
    size = u'{:.1f} m²'.format(area) if area else u''
    verdict = row.get('kind') or ROOM_HABITABLE
    if row.get('keyword'):
        verdict = u'{}／命中「{}」'.format(verdict, row['keyword'])
    # 部門通常比房間名稱更接近實際用途：實測案例裡「備品室」「鼓風機室」
    # 從名稱看不出是儲藏室與機械室，但部門欄寫的是「設備作業區」。
    # 不拿它自動判定（同一個部門底下仍可能混著居室與非居室），只擺出來給人看。
    department = row.get('department') or u''
    return u'[{}] {} {}　{}　{}　→　{}'.format(
        row.get('level') or u'?', row.get('room_number') or u'',
        row.get('room_name') or u'(無名稱)', size,
        u'〔{}〕'.format(department) if department else u'', verdict)


def rooms_for_level(rows, level_id, chosen_ids):
    """勾選的房間裡屬於這一層的那些。"""
    chosen = set(chosen_ids or ())
    return [row for row in rows or []
            if row.get('id') in chosen and row.get('level_id') == level_id]


def worst_row(result):
    """整份結果裡最該先看的那一列。

    優先序：超過 > 無法到達 > 無法取樣 > 合格中最遠的。因為實務上問的第一個
    問題是「最不利那條是多少、在哪裡、過不過」，而不是「每一間各是多少」——
    設計者在圖上也只畫一條最不利路徑。
    """
    rows = (result or {}).get('rows') or []
    if not rows:
        return None
    return rows[0]


def headline(result):
    """一句話的結論。逐室表格之前先講這一句。"""
    row = worst_row(result)
    if row is None:
        return u'沒有可檢核的居室。'
    limit = (result or {}).get('limit_mm') or 0.0
    distance = row.get('distance_mm')
    where = u'{} {}'.format(row.get('room_number') or u'',
                            row.get('room_name') or u'').strip() or u'(無名稱)'
    verdict = row.get('verdict')
    if verdict == VERDICT_FAIL:
        return u'**最不利：{} — {:.1f} 公尺，超過容許值 {:.1f} 公尺**'.format(
            where, (distance or 0.0) / 1000.0, limit / 1000.0)
    if verdict != VERDICT_PASS:
        # 走不到的房間**不是超標**。它的 distance 是「已到達的點裡最遠的那
        # 個」，拿來說「超過容許值」是假話——而且是往嚴的方向假，一樣不行。
        return u'**最需要看的是「{}」：{}**（{}）'.format(
            where, verdict, row.get('reason') or u'')
    return u'最不利：{} — {:.1f} 公尺，容許 {:.1f} 公尺，**合格**'.format(
        where, (distance or 0.0) / 1000.0, limit / 1000.0)


# --- 各類組門檻對照 --------------------------------------------------------

# §93 二會用到的所有門檻，由嚴到寬。實務上量完會想知道「換一個類組會怎樣」
# ——尤其混合用途的樓層，同一層裡不同使用單元的類組可能不同。
ALL_THRESHOLDS = (
    (LIMIT_20_M, u'20 m（§93 二（三）：三十公尺者於十五層以上）'),
    (LIMIT_30_M, u'30 m（§93 二（一）：Ａ類、Ｂ-1~3、Ｄ-1、'
                 u'有現場觀眾之電視攝影場；或（五）非防火構造一律）'),
    (LIMIT_40_M, u'40 m（§93 二（三）（四）：五十公尺者於十五層以上、'
                 u'集合住宅複層式無出入口樓層）'),
    (LIMIT_50_M, u'50 m（§93 二（二）：前述以外之用途）'),
    (LIMIT_70_M, u'70 m（§93 二（一）：Ｃ類，電視攝影場除外）'),
)


def threshold_table(distance_mm):
    """量到的距離對照所有門檻。``[(limit_mm, label, ok, margin_mm)]``。

    一次列出全部而不是只講選定的那一個，是因為「其他類要怎麼檢討」在實務上
    問的其實是「這個數字換個類組還過不過」。有了餘裕就看得出來這份檢討是
    穩過、還是壓線過——壓線過的案子改個隔間就會翻掉。
    """
    value = _number(distance_mm)
    rows = []
    for limit, label in ALL_THRESHOLDS:
        rows.append((limit, label, value <= limit, limit - value))
    return rows


def threshold_lines(distance_mm):
    """對照表的文字版，給報告用。"""
    if distance_mm is None:
        return [u'沒有量到距離，無法對照門檻。']
    lines = [u'實測 {:.2f} 公尺對照 §93 二各門檻：'.format(
        _number(distance_mm) / 1000.0)]
    for limit, label, ok, margin in threshold_table(distance_mm):
        lines.append(u'　{} {}　餘裕 {:+.2f} m'.format(
            u'○' if ok else u'✕', label, margin / 1000.0))
    return lines


def tightest_passing(distance_mm):
    """這個距離能通過的**最嚴**門檻；一個都過不了回 ``None``。

    報「最嚴還能過哪一級」比報「選定的那級過了」有用：它直接說出這份平面
    還有多少餘地，也讓人看出如果類組認定被打回票會不會出事。
    """
    for limit, label, ok, unused in threshold_table(distance_mm):
        if ok:
            return limit, label
    return None


# --- §94：避難層自樓梯口至屋外出入口 --------------------------------------

ENDPOINT_OUTSIDE_EXIT = u'屋外出入口（§94，避難層適用）'

ARTICLE_94_NOTE = (
    u'§94：「避難層自**樓梯口**至屋外出入口之步行距離不得超過前條規定。」'
    u'注意它量的是**不同的東西**——§93 從居室任一點量到樓梯口，§94 從樓梯口'
    u'量到屋外出入口。所以這個模式的受檢對象是**樓梯**而不是房間，'
    u'一座樓梯一列；容許值沿用 §93 二的同一組數字（條文寫「不得超過前條規定」）。')

EXIT_NO_STAIR = (
    u'這一層沒有計入的樓梯，§94 沒有「樓梯口」可以當起點。'
    u'單層建築或該層沒有直通樓梯時，這一條本來就不適用。')
EXIT_NO_DOOR = (
    u'這一層找不到外牆上的門。§94 的終點是屋外出入口——'
    u'請確認外牆的牆類型「功能」設為外部，或改用其他終點模式。')


def stair_subjects(stairs, cells_by_id):
    """把樓梯轉成 ``evaluate()`` 吃得下的受檢列。

    §94 的受檢對象是樓梯，但評定與排序的程式是共用的，所以把樓梯的名稱與
    編號填進同樣的欄位——不另外複製一份幾乎一樣的評定程式。
    """
    rows = []
    for stair in stairs or []:
        rows.append({
            'id': stair.get('id'),
            'element_id': stair.get('element_id'),
            'room_number': stair.get('mark') or u'',
            'room_name': stair.get('name') or u'(未命名樓梯)',
            'level': stair.get('base_level') or u'',
            'cells': cells_by_id.get(stair.get('id')) or set(),
        })
    return rows
