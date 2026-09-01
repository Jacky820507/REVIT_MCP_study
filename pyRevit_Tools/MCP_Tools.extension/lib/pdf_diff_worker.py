#! python3
# -*- coding: utf-8 -*-
"""兩份向量 PDF 圖說的差異比對 — CPython 3 + PyMuPDF。

**這個檔案是 CPython 3，不是 IronPython 2.7。** 第一行的 ``#! python3`` 是
CLAUDE.md 明列的豁免指令：pyRevit 的 IronPython 引擎不會匯入它，它只被
``subprocess`` 當獨立行程執行，以及被 ``pyRevit_Tools/tests/`` 的 pytest 匯入。
把它放在 ``lib/`` 而不是 ``bridge/python/skills/``，是因為呼叫者是 pyRevit 按鈕
而不是 C#——跟著 extension 的 junction 走，不需要額外的部署步驟。

``fitz``（PyMuPDF）刻意延遲到 :func:`read_pdf` 內才匯入，所以沒裝 PyMuPDF
的環境仍然可以匯入本模組、測試下面所有純函式。**這不是潔癖，是必要**：本工具
的成敗全繫於這些純函式的參數調校，它們必須能離線反覆測試。

## 為什麼是「向量比對」而不是影像比對

兩份圖說各自都是 Revit/CAD 匯出的向量 PDF，文字與線條的座標都在檔案裡。
直接比座標比「算成圖再比像素」精準一個量級，也不會被抗鋸齒與 DPI 干擾。
代價是掃描檔完全無效——所以 :func:`detect_page_kind` 必須先擋下來，
**絕不允許把「這頁沒有向量文字層」默默回報成「這頁沒有差異」**。

## 假差異才是真正的敵人

實務上這種工具失敗的方式不是「找不到差異」，而是「整頁都亮起來」。
兩版 PDF 若由不同 Revit 版本或不同 PDF 引擎輸出，同一條線可能被拆成不同數量
的 segment、同一段文字可能被切成不同的 span。三道防線依序上場：

1. :func:`fingerprint_drawings` 的座標量化（``quantum``）——吸收次像素抖動。
2. :func:`estimate_page_offset` 的全域平移對齊——吸收整頁位移。
3. :func:`cluster_to_grid` 的格網密度門檻——單點差異不成案，成片才算。

這三個參數都必須由呼叫端傳入並開放給使用者調整，本模組只給預設值。
"""

import json
import math
import re
import sys
import unicodedata
from collections import Counter
from difflib import SequenceMatcher


# ---- 預設參數 -------------------------------------------------------------
# 全部可被 args JSON 覆寫。這裡的值是起點，不是定論——實際案子一定要拿
# 真實的兩份 PDF 校準過才算數。

DEFAULT_QUANTUM_PT = 0.5        # 座標量化格；0.5pt 約 0.18mm
DEFAULT_GRID_COLS = 12
DEFAULT_GRID_ROWS = 9

# 門檻與權重是一組的，要一起看：一處文字變更（權重 3）本身就構成一個區域，
# 但要三條線對不上才算。這個不對稱是刻意的——文字變更幾乎一定有意義，
# 而一兩條線配不上多半是量化殘差。實測（A1 圖說整頁平移 7.3pt）在
# 兩張格網都救不回來的殘差約為 1/44 個圖元，門檻 2.0 會讓它成案，3.0 不會。
DEFAULT_THRESHOLD = 3.0
DEFAULT_TEXT_WEIGHT = 3.0
DEFAULT_GEOM_WEIGHT = 1.0
DEFAULT_MOVE_TOL_PT = 8.0       # 局部 CAD 標籤重排約 2.8mm 內仍視為同一位置
DEFAULT_ALIGN_TOL_PT = 36.0     # 全域平移超過此值要警告（36pt = 0.5 inch）

# 圖號預設落在右下角。region 是 (x0, y0, x1, y1) 的頁面比例，原點左上。
# 只在「標籤定位失敗」時才用得到——見 extract_sheet_number。
DEFAULT_SHEET_REGION = (0.70, 0.75, 1.0, 1.0)
DEFAULT_SHEET_PATTERN = r'^[A-Z]{1,3}[-_]?\d{1,4}[A-Z]?$'

# 標題欄的欄位標籤。**這是圖號抽取的主要方法，regex 只是備援。**
#
# 為什麼：圖號格式每家事務所都不一樣（實測一份真實圖說是
# `0721B-ARD-D02001`，任何合理的通用 regex 都接不到），但圖框裡幾乎一定寫著
# 「DWG NO.」或「圖號」這種欄位標籤。用標籤定位不需要猜圖框在頁面哪個角落，
# 標籤自己會說；也不需要使用者先看懂自己的圖號格式再去寫 regex。
DEFAULT_NUMBER_LABELS = (
    'DWG NO', 'DWG. NO', 'DWGNO', 'DRAWING NO', 'SHEET NO', 'SHT NO',
    '圖號', '圖 號', '圖面編號', '圖說編號', '圖紙編號')
DEFAULT_NAME_LABELS = (
    'DWG TITLE', 'DRAWING TITLE', 'SHEET TITLE', 'TITLE',
    '圖名', '圖 名', '圖面名稱', '圖說名稱', '圖紙名稱')

# 標籤與值的距離容差（pt）。cross = 垂直於取值方向，along = 沿著取值方向。
DEFAULT_LABEL_CROSS_PT = 60.0
DEFAULT_LABEL_ALONG_PT = 40.0

# 一朵雲圈掉半張圖等於沒圈。超過這個面積比例的區域仍然回報（那是實話），
# 但標記為 oversized 且預設不勾選——實測一份真實圖說，新版比舊版多了 7204
# 條線，整頁確實都改了；那種情況該做的是整張圖重新檢視，不是畫一朵大雲。
DEFAULT_MAX_REGION_FRACTION = 0.15

# 標題欄的版次戳記每頁都會變（實測 14 頁全部出現 `B版` -> `C(working)`），
# 那不是圖面變更。預設把標題欄區域的差異排除，可關閉。
DEFAULT_EXCLUDE_TITLE_BLOCK = True

# Revit 匯出的既有 Revision Cloud 不是一條「雲」路徑，而是很多條短 Bézier
# 弧線；相鄰弧線的端點通常會留 0.1~0.2 pt 的 PDF 四捨五入縫隙。這兩個值
# 是辨識幾何，不是比對量化：不要拿 DEFAULT_QUANTUM_PT 代替，否則半點格網
# 會把相鄰但不相干的細部線誤接起來。
DEFAULT_REVISION_CLOUD_ENDPOINT_TOL_PT = 0.35
DEFAULT_MIN_REVISION_CLOUD_CURVES = 8
DEFAULT_MIN_REVISION_CLOUD_PATHS = 4
DEFAULT_MIN_REVISION_CLOUD_SIZE_PT = 8.0
# Revision bubble text（例如 8-9 / B）與詳圖名稱可能落在雲線外緣之外；遮罩要比
# 向量外框大一些，才能避免只剔除弧線、卻又因鄰近文字把同一朵舊雲圈回來。
DEFAULT_REVISION_CLOUD_MASK_PADDING_PT = 24.0


# ---- 純函式：文字正規化與差異 --------------------------------------------

def normalize_text(value):
    """把一段 PDF 文字正規化成可比對的形式。

    做三件事，每一件都對應一種真實的假差異來源：

    - NFKC：全形數字／英文與半形是同一個字。圖說裡混用是常態。
    - 摺疊連續空白：PDF 引擎切 span 的位置不同，會塞進不同數量的空白。
    - 去頭尾空白。

    刻意**不**做大小寫統一——圖說裡 ``ch`` 與 ``CH`` 若真的不同，那是差異。
    """
    if value is None:
        return ''
    text = unicodedata.normalize('NFKC', value)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def span_center(bbox):
    """bbox ``(x0, y0, x1, y1)`` 的中心點。"""
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _quantize(value, quantum):
    if quantum <= 0:
        return value
    return round(value / quantum) * quantum


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _dist2(p, q):
    return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2


def _point_xy(value):
    """把 PyMuPDF Point 或純資料 tuple 轉成 ``(x, y)``。"""
    if hasattr(value, 'x') and hasattr(value, 'y'):
        return (float(value.x), float(value.y))
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        try:
            return (float(value[0]), float(value[1]))
        except (TypeError, ValueError):
            return None
    return None


def _revision_cloud_segments(drawings):
    """取出可用來辨識 Revision Cloud 的 stroked cubic 弧段。

    PyMuPDF 的 ``get_drawings`` 會把一朵 Revit 雲拆成很多 path；每個 path
    通常只有 2~3 個 ``c`` item。這裡刻意只讀 stroke-only path 的 cubic，
    不把填色、矩形、直線或單獨的圓混進來。
    """
    segments = []
    for path_index, path in enumerate(drawings or []):
        path_type = path.get('type')
        if path_type not in (None, 's'):
            continue
        if path.get('fill') is not None:
            continue
        for item_index, item in enumerate(path.get('items') or []):
            if not item or item[0] != 'c':
                continue
            points = [_point_xy(value) for value in item[1:]]
            points = [point for point in points if point is not None]
            if len(points) < 2:
                continue
            segments.append({
                'pathIndex': path_index,
                'itemIndex': item_index,
                'start': points[0],
                'end': points[-1],
                'points': points,
            })
    return segments


def detect_revision_clouds(drawings,
                           endpoint_tolerance=DEFAULT_REVISION_CLOUD_ENDPOINT_TOL_PT,
                           min_curves=DEFAULT_MIN_REVISION_CLOUD_CURVES,
                           min_paths=DEFAULT_MIN_REVISION_CLOUD_PATHS,
                           min_size_pt=DEFAULT_MIN_REVISION_CLOUD_SIZE_PT):
    """辨識一頁中「多段弧線首尾相接」的既有修訂雲。

    這不是用「所有圓弧都刪掉」的寬鬆規則。Revit PDF 的雲形有四個同時
    成立的特徵：

    1. 至少 8 段 cubic 弧線；
    2. 來自至少 4 個獨立 stroked path（單一圓通常只有一個 path）；
    3. 端點在 PDF 四捨五入容差內形成近似封閉鏈。

    4. 外框最大邊至少 8 pt；這會排除平面圖裡常見的「四個小圓弧組成的
       符號」，但不會排除真正圈住設備／文字的修訂雲。

    回傳的是 path index，因為同一個 path 可能包含雲邊界上的零長度連接
    item；整個 path 一起移除才能避免留下半朵雲。
    """
    try:
        tolerance = float(endpoint_tolerance)
    except (TypeError, ValueError):
        tolerance = DEFAULT_REVISION_CLOUD_ENDPOINT_TOL_PT
    if tolerance <= 0.0:
        tolerance = DEFAULT_REVISION_CLOUD_ENDPOINT_TOL_PT
    try:
        min_curves = max(int(min_curves), 1)
    except (TypeError, ValueError):
        min_curves = DEFAULT_MIN_REVISION_CLOUD_CURVES
    try:
        min_paths = max(int(min_paths), 1)
    except (TypeError, ValueError):
        min_paths = DEFAULT_MIN_REVISION_CLOUD_PATHS
    try:
        min_size_pt = max(float(min_size_pt), 0.0)
    except (TypeError, ValueError):
        min_size_pt = DEFAULT_MIN_REVISION_CLOUD_SIZE_PT

    segments = _revision_cloud_segments(drawings)
    if not segments:
        return []

    # 用空間桶找「端點在容差內」的弧段，避免頁面上萬條線變成 O(n^2)。
    tolerance2 = tolerance * tolerance
    buckets = {}

    def cell(point):
        return (int(math.floor(point[0] / tolerance)),
                int(math.floor(point[1] / tolerance)))

    parent = list(range(len(segments)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        left = find(left)
        right = find(right)
        if left != right:
            parent[right] = left

    # 同一段弧線的兩端也放入桶中，但連接判定只需要把不同 segment
    # 的端點合併；零長度 c item 不會自己製造一個假 component。
    for segment_index, segment in enumerate(segments):
        for point in (segment['start'], segment['end']):
            cx, cy = cell(point)
            for bx in range(cx - 1, cx + 2):
                for by in range(cy - 1, cy + 2):
                    for other_index, other_point in buckets.get((bx, by), []):
                        if other_index == segment_index:
                            continue
                        if _dist2(point, other_point) <= tolerance2:
                            union(segment_index, other_index)
            buckets.setdefault((cx, cy), []).append(
                (segment_index, point))

    groups = {}
    for index in range(len(segments)):
        groups.setdefault(find(index), []).append(segments[index])

    clouds = []
    for group in groups.values():
        path_indexes = sorted(set(item['pathIndex'] for item in group))
        if len(group) < min_curves or len(path_indexes) < min_paths:
            continue

        points = [point for item in group for point in item['points']]
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        if max(bbox[2] - bbox[0], bbox[3] - bbox[1]) < min_size_pt:
            continue

        # 雲形是封閉輪廓。允許最多兩個孤立端點，吸收 PDF 匯出時
        # 0.35pt 仍未能接上的 seam；開放的長弧線不會被當成雲。
        endpoints = []
        for segment_index, item in enumerate(group):
            endpoints.append((segment_index, item['start']))
            endpoints.append((segment_index, item['end']))
        open_endpoints = 0
        for endpoint_index, (segment_index, point) in enumerate(endpoints):
            connected = False
            for other_index, (other_segment_index, other_point) in enumerate(endpoints):
                if endpoint_index == other_index:
                    continue
                if segment_index == other_segment_index:
                    continue
                if _dist2(point, other_point) <= tolerance2:
                    connected = True
                    break
            if not connected:
                open_endpoints += 1

        if open_endpoints > 2:
            continue

        clouds.append({
            'pathIndexes': path_indexes,
            'curveCount': len(group),
            'pathCount': len(path_indexes),
            'bbox': bbox,
            'openEndpoints': open_endpoints,
        })

    clouds.sort(key=lambda cloud: (cloud['bbox'][1], cloud['bbox'][0]))
    return clouds


def filter_revision_clouds(drawings, options=None):
    """移除已辨識的舊／新 PDF Revision Cloud，回傳 ``(filtered, stats)``。"""
    options = options or {}
    if not options.get('excludeRevisionClouds', True):
        return (list(drawings or []), {
            'clouds': [], 'pathCount': 0, 'curveCount': 0})

    clouds = detect_revision_clouds(
        drawings,
        options.get('revisionCloudEndpointTolerancePt',
                    DEFAULT_REVISION_CLOUD_ENDPOINT_TOL_PT),
        options.get('minRevisionCloudCurves',
                    DEFAULT_MIN_REVISION_CLOUD_CURVES),
        options.get('minRevisionCloudPaths',
                    DEFAULT_MIN_REVISION_CLOUD_PATHS),
        options.get('minRevisionCloudSizePt',
                    DEFAULT_MIN_REVISION_CLOUD_SIZE_PT))
    excluded = set(index for cloud in clouds
                   for index in cloud['pathIndexes'])
    filtered = [path for index, path in enumerate(drawings or [])
                if index not in excluded]
    return (filtered, {
        'clouds': clouds,
        'pathCount': len(excluded),
        'curveCount': sum(cloud['curveCount'] for cloud in clouds),
    })


def _shift_bbox(bbox, dx=0.0, dy=0.0):
    """平移 ``(x0, y0, x1, y1)``，保留 A/B 比對共用的頁面座標系。"""
    return (bbox[0] + dx, bbox[1] + dy,
            bbox[2] + dx, bbox[3] + dy)


def drop_diffs_in_bboxes(diffs, bboxes, padding=0.0, kind_prefixes=None):
    """丟掉落在既有修訂雲遮罩內的差異點。

    舊版雲不只是幾條弧線；雲內的版次泡泡文字也屬於歷史註記。只從
    ``drawings`` 移除弧線仍會留下 ``8-9`` -> ``6-7`` 這類文字差異，
    下一步群聚後又會在原位置建立一朵新雲。這裡在文字／幾何差異合併後、
    群聚前做最後一道遮罩，且只遮罩已經被向量雲偵測器確認的區域。
    """
    if not diffs or not bboxes:
        return list(diffs or [])
    try:
        padding = max(float(padding), 0.0)
    except (TypeError, ValueError):
        padding = DEFAULT_REVISION_CLOUD_MASK_PADDING_PT

    expanded = []
    for bbox in bboxes:
        if not bbox or len(bbox) < 4:
            continue
        expanded.append((float(bbox[0]) - padding,
                         float(bbox[1]) - padding,
                         float(bbox[2]) + padding,
                         float(bbox[3]) + padding))
    if not expanded:
        return list(diffs)

    kept = []
    for diff in diffs:
        if kind_prefixes and not any(
                diff.get('kind', '').startswith(prefix)
                for prefix in kind_prefixes):
            kept.append(diff)
            continue
        x, y = diff['point']
        inside = any(x0 <= x <= x1 and y0 <= y <= y1
                     for x0, y0, x1, y1 in expanded)
        if not inside:
            kept.append(diff)
    return kept


def _is_numeric_revision_range(value):
    """辨識修訂泡泡常見的 ``8-9`` 類數字範圍。"""
    text = normalize_text(value or '')
    return bool(re.match(r'^\d{1,2}\s*[-–—~～]\s*\d{1,2}$', text))


def _looks_like_revision_cloud_marker(value):
    """辨識舊雲旁的版次泡泡文字，不把圖面內容一概當成歷史註記。

    舊版雲內可能同時有真正的圖面文字（例如 ``C5 -> C8``、``1-5``、
    「不鏽鋼活動扶手欄杆」）與舊版次標記。只有明確的版次／工作版標記、
    單獨的大寫泡泡字母才算歷史註記；數字範圍另外由呼叫端依差異種類處理，
    因為新圖的 ``1-5`` 也可能是剛新增的詳圖索引。
    """
    text = normalize_text(value or '')
    if not text:
        return False
    # ``_looks_like_title_block_revision_value`` 也會把 ``8-9`` 視為日期格式；
    # 在舊雲內它必須交給呼叫端依「是否有同雲內容變更」判斷，不能在這裡
    # 直接定性為版次泡泡。
    if _is_numeric_revision_range(text):
        return False
    upper = text.upper()
    if _looks_like_title_block_revision_value(text):
        return True
    if re.match(
            r'^[A-Z]\s*\(\s*(?:WORKING|ISSUED|CURRENT|REV(?:ISION)?)\s*\)$',
            upper):
        return True
    if re.match(r'^[A-Z]$', upper):
        return True
    return False


def drop_revision_cloud_annotation_diffs(diffs, bboxes, padding=0.0):
    """只移除既有雲的版次註記，保留雲內真正的圖面修改。

    ``drop_diffs_in_bboxes`` 的全遮罩會漏掉「舊雲範圍內的設計也被改了」的
    情況。這裡採選擇性規則：text-move 永遠丟掉；``B版``、``C(working)``、
    單獨泡泡字母丟掉；``8-9 -> 6-7`` 這種兩側都是數字範圍的版次替換丟掉。
    但新增／刪除的數字範圍不直接遮罩，讓 ``1-5`` 詳圖索引仍能形成雲；
    若數字範圍被 PDF 配對成內容替換，只有在同一舊雲內沒有任何其他真正
    文字變更時才遮掉。``C5 -> C8`` 這類識別碼變更也會保留下來。
    """
    if not diffs or not bboxes:
        return list(diffs or [])
    try:
        padding = max(float(padding), 0.0)
    except (TypeError, ValueError):
        padding = DEFAULT_REVISION_CLOUD_MASK_PADDING_PT

    expanded = []
    for bbox in bboxes:
        if not bbox or len(bbox) < 4:
            continue
        expanded.append((float(bbox[0]) - padding,
                         float(bbox[1]) - padding,
                         float(bbox[2]) + padding,
                         float(bbox[3]) + padding))
    if not expanded:
        return list(diffs)

    def _cloud_index(point):
        x, y = point
        return [index for index, (x0, y0, x1, y1) in enumerate(expanded)
                if x0 <= x <= x1 and y0 <= y <= y1]

    # 先找每一朵舊雲是否還有真正的內容差異。這能區分單獨的歷史版次
    # ``8-9 -> 6-7`` 與同一個詳圖裡的 ``8-9 -> 1-5``（旁邊同時有扶手／
    # 詳圖名稱變更）——後者不能遮掉，否則使用者會看不到真正的變更。
    substantive_clouds = [False] * len(expanded)
    for diff in diffs:
        kind = str(diff.get('kind', ''))
        if not kind.startswith('text') or kind == 'text-move':
            continue
        before = diff.get('before')
        after = diff.get('after')
        if (_looks_like_revision_cloud_marker(before) or
                _looks_like_revision_cloud_marker(after) or
                (_is_numeric_revision_range(before) and
                 _is_numeric_revision_range(after))):
            continue
        if before or after:
            for index in _cloud_index(diff['point']):
                substantive_clouds[index] = True

    kept = []
    for diff in diffs:
        kind = str(diff.get('kind', ''))
        if not kind.startswith('text'):
            kept.append(diff)
            continue
        x, y = diff['point']
        if not any(x0 <= x <= x1 and y0 <= y <= y1
                   for x0, y0, x1, y1 in expanded):
            kept.append(diff)
            continue
        if kind == 'text-move':
            continue

        before = diff.get('before')
        after = diff.get('after')
        marker_before = _looks_like_revision_cloud_marker(before)
        marker_after = _looks_like_revision_cloud_marker(after)
        if kind == 'text-change':
            # 版次泡泡的範圍替換；不要把內容相同類型的門窗／詳圖識別碼
            # （例如 C5 -> C8）誤當成這一類。
            numeric_range_change = (
                _is_numeric_revision_range(before) and
                _is_numeric_revision_range(after))
            cloud_has_content = any(
                substantive_clouds[index]
                for index in _cloud_index(diff['point']))
            if (marker_before or marker_after or
                    (numeric_range_change and not cloud_has_content)):
                continue
        elif marker_before or marker_after:
            # text-add/delete 的 numeric range 先保留，因為新圖新增的
            # ``1-5`` 可能正是使用者要圈出的詳圖索引。
            value = after if kind == 'text-add' else before
            if not _is_numeric_revision_range(value):
                continue
        kept.append(diff)
    return kept


def estimate_page_offset(spans_a, spans_b, min_samples=8):
    """用兩頁共有且唯一的文字求整頁平移量，回傳 ``(dx, dy)``。

    只取「在 A 出現一次、在 B 也出現一次」的文字當錨點——重複出現的文字
    （像 "1"、"mm"、圖層名）配對會亂跳，拿來估平移只會製造噪音。

    取**中位數**而不是平均：少數錨點真的被移動過時，平均會被拉走，中位數不會。

    錨點少於 ``min_samples`` 就回 ``(0, 0)``——寧可不對齊，也不要用三四個點
    亂推一個平移量把整頁都推歪。
    """
    counts_a = Counter(normalize_text(s['text']) for s in spans_a)
    counts_b = Counter(normalize_text(s['text']) for s in spans_b)

    lookup_b = {}
    for span in spans_b:
        key = normalize_text(span['text'])
        if counts_a.get(key) == 1 and counts_b.get(key) == 1:
            lookup_b[key] = span

    dxs, dys = [], []
    for span in spans_a:
        key = normalize_text(span['text'])
        if not key:
            continue
        partner = lookup_b.get(key)
        if partner is None:
            continue
        ax, ay = span_center(span['bbox'])
        bx, by = span_center(partner['bbox'])
        dxs.append(bx - ax)
        dys.append(by - ay)

    if len(dxs) < min_samples:
        return (0.0, 0.0)
    return (_median(dxs), _median(dys))


def shift_spans(spans, dx, dy):
    """把一組 span 的 bbox 平移，用於把 B 頁搬進 A 頁的座標系。"""
    moved = []
    for span in spans:
        x0, y0, x1, y1 = span['bbox']
        item = dict(span)
        item['bbox'] = (x0 - dx, y0 - dy, x1 - dx, y1 - dy)
        moved.append(item)
    return moved


def diff_text_spans(spans_a, spans_b, move_tol=DEFAULT_MOVE_TOL_PT):
    """比對兩組文字 span，回傳差異清單。

    兩層 key 對應五種結果：

    - 同文字、位置在 ``move_tol`` 內   -> 沒變，不回報
    - 同文字、位置差超過 ``move_tol``  -> ``text-move``
    - 位置接近、文字不同                -> ``text-change``（最有價值的一種）
    - 只在 A                            -> ``text-delete``
    - 只在 B                            -> ``text-add``

    ``text-change`` 之所以要獨立出來，是因為圖說變更絕大多數長這樣：
    同一個位置上的 ``CH=300`` 變成 ``CH=320``。若只報「刪一個、加一個」，
    使用者得自己在兩份 PDF 之間比對才看得懂。
    """
    spans_a = list(spans_a)
    spans_b = list(spans_b)
    centers_a = [span_center(span['bbox']) for span in spans_a]
    centers_b = [span_center(span['bbox']) for span in spans_b]
    keys_a = [normalize_text(span['text']) for span in spans_a]
    keys_b = [normalize_text(span['text']) for span in spans_b]
    limit2 = move_tol * move_tol
    used_a = set()
    used_b = set()
    diffs = []

    def _claim_nearest_pairs(candidates, callback=None):
        for distance, index_a, index_b in sorted(candidates):
            if index_a in used_a or index_b in used_b:
                continue
            used_a.add(index_a)
            used_b.add(index_b)
            if callback is not None:
                callback(index_a, index_b, distance)

    # 先鎖定同文字、同位置。若一開始就允許遠距離同文字配對，某處 D3
    # 會搶到別處的 D3，使原位置 D3 -> D4a 被拆成錯位的新增／刪除。
    same_place = []
    for index_a in range(len(spans_a)):
        for index_b in range(len(spans_b)):
            if keys_a[index_a] != keys_b[index_b]:
                continue
            distance = _dist2(centers_a[index_a], centers_b[index_b])
            if distance <= limit2:
                same_place.append((distance, index_a, index_b))
    _claim_nearest_pairs(same_place)

    # 再判斷同位置、內容不同；全域依距離排序，避免 PDF span 輸出順序
    # 左右配對結果。變更一律錨定在新版 bbox。
    changed_place = []
    for index_a in range(len(spans_a)):
        if index_a in used_a:
            continue
        for index_b in range(len(spans_b)):
            if index_b in used_b or keys_a[index_a] == keys_b[index_b]:
                continue
            distance = _dist2(centers_a[index_a], centers_b[index_b])
            if distance <= limit2:
                # 同一位置可能疊著房名、門窗編號、耐燃標示等多個 span。
                # 只看幾何距離會把 D3 配成 F60A；文字相似度要先協助消歧。
                similarity = SequenceMatcher(
                    None, keys_a[index_a], keys_b[index_b]).ratio()
                pairing_cost = distance + (
                    1.0 - similarity) * max(limit2, 1.0) * 10.0
                changed_place.append((pairing_cost, index_a, index_b))

    def _append_change(index_a, index_b, _distance):
        similarity = SequenceMatcher(
            None, keys_a[index_a], keys_b[index_b]).ratio()
        diffs.append({
            'kind': 'text-change',
            'point': centers_b[index_b],
            'bbox': spans_b[index_b]['bbox'],
            'before': spans_a[index_a]['text'],
            'after': spans_b[index_b]['text'],
            'fontSize': float(spans_b[index_b].get('size') or 0.0),
            'similarity': round(similarity, 4),
        })

    _claim_nearest_pairs(changed_place, _append_change)

    # 最後才處理真正搬移的同文字；這時原地變更需要的 span 已不會被搶走。
    moved = []
    for index_a in range(len(spans_a)):
        if index_a in used_a:
            continue
        for index_b in range(len(spans_b)):
            if index_b in used_b or keys_a[index_a] != keys_b[index_b]:
                continue
            moved.append((
                _dist2(centers_a[index_a], centers_b[index_b]),
                index_a, index_b))

    def _append_move(index_a, index_b, _distance):
        diffs.append({
            'kind': 'text-move',
            'point': centers_b[index_b],
            'bbox': spans_b[index_b]['bbox'],
            'before': spans_a[index_a]['text'],
            'after': spans_b[index_b]['text'],
            'fontSize': float(spans_b[index_b].get('size') or 0.0),
        })

    _claim_nearest_pairs(moved, _append_move)

    for index_a, span in enumerate(spans_a):
        if index_a not in used_a:
            diffs.append({
                'kind': 'text-delete',
                'point': centers_a[index_a],
                'bbox': span['bbox'],
                'before': span['text'],
                'after': None,
                'fontSize': float(span.get('size') or 0.0),
            })
    for index_b, span in enumerate(spans_b):
        if index_b not in used_b:
            diffs.append({
                'kind': 'text-add',
                'point': centers_b[index_b],
                'bbox': span['bbox'],
                'before': None,
                'after': span['text'],
                'fontSize': float(span.get('size') or 0.0),
            })

    return diffs


# ---- 純函式：幾何指紋與差異 ----------------------------------------------

def fingerprint_drawings(drawings, quantum=DEFAULT_QUANTUM_PT,
                         dx=0.0, dy=0.0):
    """把向量繪圖指令轉成可做集合運算的指紋。

    ``drawings`` 是 :func:`extract_drawings` 產出的純資料（不是 fitz 物件），
    所以這個函式可以在沒有 PyMuPDF 的環境下被測。

    指紋只取「形狀類型 + 量化後的座標」，刻意**丟掉顏色與線寬**：
    兩版 PDF 之間圖層顏色微調不該被當成圖面變更。

    ## 平移一定要在量化「之前」做

    ``dx`` / ``dy`` 是全域對齊量，這裡在量化前就先扣掉。**不能**先量化再平移
    再量化一次——第一次量化已經把「該落在哪一格」所需的次量化資訊丟掉了，
    二次量化會整格偏掉。實測過：B 的 ``2131.2370`` 先量化成 ``2131.0``、
    扣掉位移 ``7.3001`` 成 ``2123.6999``、再量化就變 ``2123.5``；而 A 的
    ``2123.9370`` 直接量化是 ``2124.0``。同一條線，差一整格。

    ## 為什麼每個項目有兩組指紋

    量化必然有邊界：兩個只差 0.02pt 的座標若剛好跨在格線兩側（``60.24``
    與 ``60.26``），量化後會變成 ``60.0`` 與 ``60.5``，被誤判成差異。
    所以每個項目同時算「原格網」與「偏移半格的格網」兩組指紋，
    :func:`diff_geometry` 兩輪比對，任一輪對上就算相同。跨界的座標在原格網
    分開、在半格格網一定合併，反之亦然——兩張格網不會同時失敗。

    回傳 ``[(fp_primary, fp_alt, (cx, cy), bbox)]``。中心點只負責分群；
    最後的雲形範圍必須使用圖元真正的 bbox。若只保留中心點，矩形、房間框或
    長線的中心往往正好是空白，最後就會在空白處畫出一朵莫名其妙的雲。
    """
    result = []
    half = quantum / 2.0 if quantum > 0 else 0.0
    for path in drawings or []:
        for item in path.get('items') or []:
            kind = item[0]
            coords = []
            values = item[1:]
            # PyMuPDF 的矩形 item 是 ('re', rect, orientation)。尾端 1/-1
            # 是方向 metadata，不是座標；若混進 coords，bbox 會被拉到 x=1
            # 的頁面空白處。直接呼叫此純函式的舊資料也在這裡防守。
            if kind == 're' and len(item) >= 2:
                values = (item[1],)
            for value in values:
                if isinstance(value, (tuple, list)):
                    coords.extend(float(v) for v in value)
                elif isinstance(value, (int, float)):
                    coords.append(float(value))
            if len(coords) < 2:
                continue

            # 先平移（原始座標），再量化——順序不能顛倒。
            shifted = []
            for index, value in enumerate(coords):
                shifted.append(value - (dx if index % 2 == 0 else dy))

            primary = tuple(_quantize(c, quantum) for c in shifted)
            alternate = tuple(_quantize(c + half, quantum) for c in shifted)
            xs = shifted[0::2]
            ys = shifted[1::2]
            center = (sum(xs) / len(xs), sum(ys) / len(ys))
            bbox = (min(xs), min(ys), max(xs), max(ys))
            result.append(((kind,) + primary, (kind,) + alternate, center,
                           bbox))
    return result


def _match_pass(items_a, items_b, key_index):
    """一輪多重集合配對，回傳兩邊各自沒配到的項目。

    用逐筆消耗而不是 :class:`Counter` 相減：同一條線畫兩次跟畫一次是不同的，
    純集合運算會把「重複的圖元被刪掉一份」這種真實變更吃掉。
    """
    buckets = {}
    for index, item in enumerate(items_b):
        buckets.setdefault(item[key_index], []).append(index)

    used = set()
    left_a = []
    for item in items_a:
        bucket = buckets.get(item[key_index])
        picked = None
        while bucket:
            candidate = bucket.pop()
            if candidate not in used:
                picked = candidate
                break
        if picked is None:
            left_a.append(item)
        else:
            used.add(picked)

    left_b = [item for index, item in enumerate(items_b) if index not in used]
    return (left_a, left_b)


def diff_geometry(fps_a, fps_b):
    """兩組幾何指紋的差異，回傳差異清單。

    兩輪：先用原格網配，配不到的再用半格格網配一次。只有兩張格網都配不上的
    才算真差異。兩輪都失敗代表座標真的不同，不是量化邊界問題。

    寧可少報也不要多報：邊界案例被第二輪吃掉，最壞情況是漏一個非常微小的
    位移；而多報的代價是整頁亮起來，工具直接不能用。
    """
    left_a, left_b = _match_pass(fps_a, fps_b, 0)
    left_a, left_b = _match_pass(left_a, left_b, 1)

    diffs = []
    for item in left_a:
        diff = {'kind': 'geom-delete', 'point': item[2]}
        if len(item) > 3:
            diff['bbox'] = item[3]
        diffs.append(diff)
    for item in left_b:
        diff = {'kind': 'geom-add', 'point': item[2]}
        if len(item) > 3:
            diff['bbox'] = item[3]
        diffs.append(diff)
    return diffs


# ---- 純函式：格網群聚 ------------------------------------------------------

def column_label(index):
    """0->A, 25->Z, 26->AA。跟試算表同一套，使用者不需要學新東西。"""
    label = ''
    index = int(index)
    while True:
        label = chr(ord('A') + index % 26) + label
        index = index // 26 - 1
        if index < 0:
            return label


def cluster_to_grid(diffs, page_width, page_height,
                    cols=DEFAULT_GRID_COLS, rows=DEFAULT_GRID_ROWS,
                    threshold=DEFAULT_THRESHOLD,
                    text_weight=DEFAULT_TEXT_WEIGHT,
                    geom_weight=DEFAULT_GEOM_WEIGHT,
                    max_fraction=DEFAULT_MAX_REGION_FRACTION):
    """把散落的差異點聚成可讀的矩形區域。

    為什麼用固定格網而不是 DBSCAN：格號（``F5:F7``）本身就是使用者看得懂的
    定位語言，而距離型分群的輸出只有座標。工地上要能用嘴巴講出「F5 那一塊」。

    只有加權分數超過 ``threshold`` 的格子成為「熱格」，相鄰（含斜角）的熱格
    再併成連通區塊。單一格的孤立差異因此不會成案——這是第三道防線。
    """
    if page_width <= 0 or page_height <= 0 or cols <= 0 or rows <= 0:
        return []

    cell_w = page_width / float(cols)
    cell_h = page_height / float(rows)
    cells = {}

    for diff in diffs:
        x, y = diff['point']
        col = int(min(max(x / cell_w, 0), cols - 1))
        row = int(min(max(y / cell_h, 0), rows - 1))
        weight = text_weight if diff['kind'].startswith('text') else geom_weight
        cell = cells.setdefault((col, row), {
            'score': 0.0, 'text': 0, 'geom': 0, 'diffs': []})
        cell['score'] += weight
        cell['diffs'].append(diff)
        if diff['kind'].startswith('text'):
            cell['text'] += 1
        else:
            cell['geom'] += 1

    hot = set(key for key, cell in cells.items() if cell['score'] >= threshold)
    regions = []
    for component in _connected_components(hot):
        cols_in = [c for c, _ in component]
        rows_in = [r for _, r in component]
        min_col, max_col = min(cols_in), max(cols_in)
        min_row, max_row = min(rows_in), max(rows_in)

        merged = []
        score = 0.0
        text_count = geom_count = 0
        for key in component:
            cell = cells[key]
            score += cell['score']
            text_count += cell['text']
            geom_count += cell['geom']
            merged.extend(cell['diffs'])

        label = '{}{}'.format(column_label(min_col), min_row + 1)
        if (min_col, min_row) != (max_col, max_row):
            label += ':{}{}'.format(column_label(max_col), max_row + 1)

        bbox = (min_col * cell_w, min_row * cell_h,
                (max_col + 1) * cell_w, (max_row + 1) * cell_h)
        fraction = (((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
                    / float(page_width * page_height))
        regions.append({
            'gridLabel': label,
            'bbox': bbox,
            'score': round(score, 2),
            'textCount': text_count,
            'geomCount': geom_count,
            'pageFraction': round(fraction, 4),
            # 一朵雲圈掉半張圖等於沒圈。照樣回報（那是實話），但標出來讓 UI
            # 預設不勾、並提示「這張圖該整張重新檢視」。
            'oversized': fraction > max_fraction,
            'samples': _pick_samples(merged),
        })

    regions.sort(key=lambda r: -r['score'])
    return regions


# 全部差異需要較寬的鄰近半徑，才能把同一組幾何變更視為一區；文字差異
# 另用更細的半徑，避免上下相鄰的註記（例如 D4a 與 200cm*125cm 開口）
# 被一條文字鏈合成一個過高的修訂雲。
DEFAULT_EPS_FRACTION = 0.030    # 全部差異：A3 約 25pt / 9mm
DEFAULT_TEXT_EPS_FRACTION = 0.015  # 文字差異：A3 約 12.6pt / 4.4mm
# 智慧模式的目的不是把每一條 PDF 線都變成一朵雲，而是找出使用者可複核的
# 變更群組。較寬的鄰近半徑可把同一個表格／設備的線條留在同一區；整片 CAD
# 重繪則在 compare_page 另走「整體診斷」路徑，不再遞迴硬切成數百區。
DEFAULT_SMART_EPS_FRACTION = 0.050
DEFAULT_SMART_TEXT_EPS_FRACTION = 0.050
DEFAULT_SMART_MAX_SPAN_FRACTION = 0.30
DEFAULT_SMART_MAX_PRIMITIVE_SPAN_FRACTION = 0.20
DEFAULT_SMART_MERGE_OVERLAP_FRACTION = 0.45
DEFAULT_SMART_GEOMETRY_DENSITY_FRACTION = 0.20
DEFAULT_SMART_STRICT_TEXT_DENSITY_FRACTION = 0.60
DEFAULT_SMART_GEOMETRY_EPS_FRACTION = 0.015
DEFAULT_SMART_GEOMETRY_MIN_DIFFS = 8
DEFAULT_SMART_GEOMETRY_MIN_SPAN_PT = 12.0
DEFAULT_SMART_HOTSPOT_RATIO = 0.45
DEFAULT_SMART_HOTSPOT_MIN_DIFFS = 80
DEFAULT_SMART_HOTSPOT_MAX_REGIONS = 4
# 立面圖的修改通常是同一面牆／同一組門窗的整體重繪；只抓最高密度的
# 細熱點會把建築立面切得太碎。立面專用格網門檻讓同一連續面形成一個
# 可讀的大區塊，但仍不會退回整頁一朵雲。
DEFAULT_SMART_ELEVATION_GRID_THRESHOLD = 50
DEFAULT_SMART_ELEVATION_MAX_REGIONS = 6
DEFAULT_SMART_TEXT_ATTACH_GAP_FRACTION = 0.025
# 120 是依「新增／刪除／內容變更」計，不含 text-move；D06001 實測 146
# 筆內容差異而 D02002 為 134，但後者幾何密度未達整頁重繪門檻，不會誤套。
DEFAULT_SMART_HIGH_CHURN_TEXT_DIFFS = 120
DEFAULT_SMART_MAX_REGIONS_PER_PAGE = 36
# 切割的判定門檻：任一軸的跨距超過頁面該軸的這個比例就要切。
# 用跨距而非面積，見 _split_until_small 的說明。
DEFAULT_MAX_SPAN_FRACTION = 0.30
DEFAULT_MIN_GAP_FRACTION = 0.020  # 小於這個空隙不值得切開


def cluster_diffs(diffs, page_width, page_height,
                  eps_fraction=DEFAULT_EPS_FRACTION,
                  threshold=DEFAULT_THRESHOLD,
                  text_weight=DEFAULT_TEXT_WEIGHT,
                  geom_weight=DEFAULT_GEOM_WEIGHT,
                  max_fraction=DEFAULT_MAX_REGION_FRACTION,
                  min_gap_fraction=DEFAULT_MIN_GAP_FRACTION,
                  grid_cols=DEFAULT_GRID_COLS, grid_rows=DEFAULT_GRID_ROWS,
                  max_span_fraction=DEFAULT_MAX_SPAN_FRACTION,
                  force_split_dense=False):
    """依「距離」把差異點分群，太大的群在最大空隙處切開。

    ## 為什麼不能用固定格網 + 連通合併

    那是 all-or-nothing：格子只要連成一串就會滾雪球。實測一份真實圖說，
    第 2 頁的差異散佈全頁，連通合併後產出**一個涵蓋 100% 頁面的區域**——
    準確，但圈成雲等於沒圈。使用者要的是「很近的併成一塊」，不是「全部併成
    一塊」。

    ## 做法

    1. **鄰近分群**：用 eps 大小的格子做桶，8-鄰域相連的桶算同一群。
       等價於 Chebyshev 距離的 DBSCAN，但是 O(n)。
    2. **超過上限就切**：群的外框超過 ``max_fraction`` 時，沿較長的軸把點排序，
       找**最大的空隙**切開，遞迴處理兩半。
    3. **切在空隙處，不是切在中位數**。中位數會把一團連續的東西硬切兩半，
       產生兩個都不自然的框；切在最大空隙等於「這裡本來就是分開的兩堆」。
    4. **找不到夠大的空隙就停手並標記 oversized**。那代表這一區是**真的**
       整片都變了（實測第 2 頁新版比舊版多 7204 條線）。這時候誠實回報範圍，
       比硬切成幾個假的小框有用——後者會讓人以為只有那幾處要看。
    """
    if page_width <= 0 or page_height <= 0 or not diffs:
        return []

    short_side = min(page_width, page_height)
    eps = max(eps_fraction * short_side, 1.0)
    min_gap = max(min_gap_fraction * short_side, 1.0)

    buckets = {}
    for diff in diffs:
        x, y = diff['point']
        key = (int(x // eps), int(y // eps))
        buckets.setdefault(key, []).append(diff)

    regions = []
    for component in _connected_components(set(buckets.keys())):
        group = []
        for key in component:
            group.extend(buckets[key])
        regions.extend(_split_until_small(
            group, page_width, page_height, max_fraction, min_gap,
            max_span_fraction, force_split_dense))

    out = []
    for group in regions:
        region = _describe_group(group, page_width, page_height,
                                 text_weight, geom_weight, max_fraction,
                                 grid_cols, grid_rows)
        if region['score'] >= threshold:
            out.append(region)
    out.sort(key=lambda r: -r['score'])
    return out


def _point_bbox_of(group):
    """分群／切割使用中心點，不讓一條長線把相鄰群全部黏住。"""
    xs = [d['point'][0] for d in group]
    ys = [d['point'][1] for d in group]
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_of(group):
    """輸出雲形使用圖元真實外框；舊測資沒有 bbox 時退回中心點。"""
    boxes = []
    for diff in group:
        bbox = diff.get('bbox')
        if bbox and len(bbox) >= 4:
            boxes.append(tuple(float(value) for value in bbox[:4]))
        else:
            x, y = diff['point']
            boxes.append((x, y, x, y))
    return (min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes))


def _split_until_small(group, page_width, page_height, max_fraction, min_gap,
                       max_span_fraction=DEFAULT_MAX_SPAN_FRACTION,
                       force_split_dense=False):
    """遞迴：跨距超過上限就在最大空隙處切開，切不動就原樣回傳。

    **判定用軸向跨距，不能用面積。** 一排沿著同一條線的尺寸變更，外框高度
    是 0、面積也是 0，用面積判定永遠不會切——結果是一朵橫跨整頁的扁長雲，
    比不切還糟。改看「寬度佔頁寬多少、高度佔頁高多少」，任一超標就切。
    """
    x0, y0, x1, y1 = _point_bbox_of(group)
    too_wide = (x1 - x0) > max_span_fraction * page_width
    too_tall = (y1 - y0) > max_span_fraction * page_height
    if not (too_wide or too_tall) or len(group) < 4:
        return [group]

    # 比的是「相對於頁面的跨距」而非絕對長度：A3 橫式頁寬是頁高的 1.4 倍，
    # 用絕對長度比會永遠先切 x 軸。
    axis = 0 if ((x1 - x0) / page_width) >= ((y1 - y0) / page_height) else 1
    ordered = sorted(group, key=lambda d: d['point'][axis])

    best_gap = 0.0
    best_index = None
    for i in range(1, len(ordered)):
        gap = ordered[i]['point'][axis] - ordered[i - 1]['point'][axis]
        if gap > best_gap:
            best_gap, best_index = gap, i

    # 一般「全部差異」模式保留整片結果；智慧圈選則必須產生可放置的局部雲，
    # 密集區沒有天然空隙時以中位數繼續切割。
    if best_index is None or best_gap < min_gap:
        if not force_split_dense:
            return [group]
        best_index = len(ordered) // 2
        if best_index <= 0 or best_index >= len(ordered):
            return [group]

    left = _split_until_small(ordered[:best_index], page_width, page_height,
                              max_fraction, min_gap, max_span_fraction,
                              force_split_dense)
    right = _split_until_small(ordered[best_index:], page_width, page_height,
                               max_fraction, min_gap, max_span_fraction,
                               force_split_dense)
    return left + right


def _describe_group(group, page_width, page_height, text_weight, geom_weight,
                    max_fraction, grid_cols, grid_rows):
    """把一群差異點整理成回傳用的 region dict。"""
    x0, y0, x1, y1 = _bbox_of(group)
    score = 0.0
    text_count = geom_count = 0
    for diff in group:
        if diff['kind'].startswith('text'):
            score += text_weight
            text_count += 1
        else:
            score += geom_weight
            geom_count += 1

    fraction = ((x1 - x0) * (y1 - y0)) / float(page_width * page_height)
    cell_w = page_width / float(grid_cols)
    cell_h = page_height / float(grid_rows)
    c0 = int(min(max(x0 / cell_w, 0), grid_cols - 1))
    c1 = int(min(max(x1 / cell_w, 0), grid_cols - 1))
    r0 = int(min(max(y0 / cell_h, 0), grid_rows - 1))
    r1 = int(min(max(y1 / cell_h, 0), grid_rows - 1))
    label = '{}{}'.format(column_label(c0), r0 + 1)
    if (c0, r0) != (c1, r1):
        label += ':{}{}'.format(column_label(c1), r1 + 1)

    return {
        'gridLabel': label,
        'bbox': (x0, y0, x1, y1),
        'score': round(score, 2),
        'textCount': text_count,
        'geomCount': geom_count,
        'pageFraction': round(fraction, 4),
        'oversized': fraction > max_fraction,
        'samples': _pick_samples(group),
    }


def cluster_geometry_hotspots(diffs, page_width, page_height,
                              cols=DEFAULT_GRID_COLS,
                              rows=DEFAULT_GRID_ROWS,
                              ratio=DEFAULT_SMART_HOTSPOT_RATIO,
                              min_diffs=DEFAULT_SMART_HOTSPOT_MIN_DIFFS,
                              max_regions=DEFAULT_SMART_HOTSPOT_MAX_REGIONS,
                              geom_weight=1.0,
                              text_weight=0.0,
                              max_fraction=DEFAULT_MAX_REGION_FRACTION):
    """從大量幾何差異找出少數「線條熱點」，而不是逐線畫雲。

    不同 PDF 輸出器常會讓整張 CAD 圖的線段指紋都對不上。這時候原始差異
    數量很大，但真正值得圈的是線條密度明顯高於其他區域的圖面區塊。先以
    12x9 粗格網找高密度格，再只合併這些格中的**真實圖元 bbox**，因此輸出
    會貼近牆／詳圖群組，不會被整個格網撐到空白處。

    ``ratio`` 是相對於本頁最高密度格的門檻；``min_diffs`` 是跨頁穩定的
    最低保護線。這兩個條件同時存在，避免小頁面或單一孤立線段誤成熱點。
    回傳的 ``diagnostic`` 只代表「這是幾何熱點」，不是整頁重繪診斷；呼叫端
    可以把它和文字差異合併成一個可讀的修訂區塊。
    """
    if page_width <= 0 or page_height <= 0 or cols <= 0 or rows <= 0:
        return []

    geometry = [diff for diff in (diffs or [])
                if not str(diff.get('kind', '')).startswith('text')]
    if not geometry:
        return []

    cell_w = page_width / float(cols)
    cell_h = page_height / float(rows)
    cells = {}
    for diff in geometry:
        x, y = diff['point']
        col = int(min(max(x / cell_w, 0), cols - 1))
        row = int(min(max(y / cell_h, 0), rows - 1))
        cells.setdefault((col, row), []).append(diff)

    peak = max(len(group) for group in cells.values())
    try:
        ratio = float(ratio)
    except (TypeError, ValueError):
        ratio = DEFAULT_SMART_HOTSPOT_RATIO
    try:
        min_diffs = int(min_diffs)
    except (TypeError, ValueError):
        min_diffs = DEFAULT_SMART_HOTSPOT_MIN_DIFFS
    threshold = max(float(min_diffs), peak * max(ratio, 0.0))
    hot = set(key for key, group in cells.items()
              if len(group) >= threshold)
    if not hot:
        return []

    regions = []
    for component in _connected_components(hot):
        group = []
        for key in component:
            group.extend(cells[key])
        if len(group) < min_diffs:
            continue
        region = _describe_group(
            group, page_width, page_height, text_weight, geom_weight,
            max_fraction, cols, rows)
        # 個別圖元 bbox 可能是一條跨越多格的長線，會把熱點的實際框
        # 撐到超過智慧模式的可圈範圍。此時退回「熱格外框」：它仍然是
        # 由差異密度選出的局部區塊，不是整頁診斷；也能讓使用者在預設
        # 隱藏過大區域時看得到這個主要變更，而不是被長線誤判成整片。
        if region.get('oversized'):
            cols_in = [col for col, _ in component]
            rows_in = [row for _, row in component]
            grid_bbox = (min(cols_in) * cell_w, min(rows_in) * cell_h,
                         (max(cols_in) + 1) * cell_w,
                         (max(rows_in) + 1) * cell_h)
            grid_fraction = ((grid_bbox[2] - grid_bbox[0]) *
                             (grid_bbox[3] - grid_bbox[1])) / float(
                                 page_width * page_height)
            if grid_fraction < region.get('pageFraction', 1.0):
                region['bbox'] = grid_bbox
                region['pageFraction'] = round(grid_fraction, 4)
                region['oversized'] = grid_fraction > max_fraction
                region['gridLabel'] = _grid_label_for_bbox(
                    grid_bbox, page_width, page_height, cols, rows)
                region['hotspotGridClipped'] = True
        region['diagnostic'] = 'geometryHotspot'
        region['hotspotCellCount'] = len(component)
        region['hotspotPeak'] = max(len(cells[key]) for key in component)
        regions.append(region)

    regions.sort(key=lambda region: -int(region.get('geomCount', 0)))
    try:
        max_regions = int(max_regions)
    except (TypeError, ValueError):
        max_regions = DEFAULT_SMART_HOTSPOT_MAX_REGIONS
    if max_regions > 0:
        regions = regions[:max_regions]
    return regions


def _is_elevation_sheet(page):
    """判斷本頁是否為立面圖，供立面專用的大範圍圈選策略使用。"""
    values = [page.get('sheetName'), page.get('sheetNumber')]
    values.extend(page.get('sheetNameCandidates') or [])
    values.extend(page.get('sheetNumberCandidates') or [])
    for value in values:
        text = normalize_text(value or '')
        if '立面' in text or re.search(r'\bELEVATION(?:S)?\b', text,
                                       re.IGNORECASE):
            return True
    return False


def cluster_elevation_geometry_regions(
        diffs, page_width, page_height,
        cols=DEFAULT_GRID_COLS, rows=DEFAULT_GRID_ROWS,
        threshold=DEFAULT_SMART_ELEVATION_GRID_THRESHOLD,
        max_regions=DEFAULT_SMART_ELEVATION_MAX_REGIONS,
        max_fraction=DEFAULT_MAX_REGION_FRACTION):
    """以較寬的密集格網圈出建築立面變更區塊。

    立面重繪的 unmatched line 往往不是單一構件，而是整面門窗／牆體的
    CAD 輸出差異。這裡刻意使用 ``cluster_to_grid`` 的格網外框，不使用
    單條線的真實 bbox，讓結果涵蓋使用者需要複核的「一大片立面」，同時
    只保留有限個高密度連通區，不會退回 500 多朵線條雲。
    """
    geometry = [diff for diff in (diffs or [])
                if not str(diff.get('kind', '')).startswith('text')]
    if not geometry:
        return []
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        threshold = DEFAULT_SMART_ELEVATION_GRID_THRESHOLD
    regions = cluster_to_grid(
        geometry, page_width, page_height, cols, rows, threshold,
        0.0, 1.0, max_fraction)
    for region in regions:
        region['diagnostic'] = 'elevationWideChange'
        region['elevationGridThreshold'] = round(threshold, 2)
    try:
        max_regions = int(max_regions)
    except (TypeError, ValueError):
        max_regions = DEFAULT_SMART_ELEVATION_MAX_REGIONS
    if max_regions > 0:
        regions = regions[:max_regions]
    return regions


def _bbox_gap(a, b):
    """兩矩形在 x/y 軸上的最大空隙；重疊時該軸空隙為 0。"""
    horizontal = max(float(b[0]) - float(a[2]),
                    float(a[0]) - float(b[2]), 0.0)
    vertical = max(float(b[1]) - float(a[3]),
                  float(a[1]) - float(b[3]), 0.0)
    return max(horizontal, vertical)


def filter_tiny_geometry_regions(regions,
                                 min_diffs=DEFAULT_SMART_GEOMETRY_MIN_DIFFS,
                                 min_span_pt=DEFAULT_SMART_GEOMETRY_MIN_SPAN_PT,
                                 thin_min_diffs=16):
    """移除短、稀疏的線條殘差，保留長薄線與有足夠證據的區塊。

    PDF 轉檔的端點量化常會留下 8～14 條落在不到 10pt 小線段；它們若各自
    成雲，畫面看起來就像雲形被打散。不能只用面積門檻，因為牆線本來就可能
    很薄，所以長軸達到 ``min_span_pt`` 或線條數夠多時仍保留。
    """
    try:
        min_diffs = int(min_diffs)
    except (TypeError, ValueError):
        min_diffs = DEFAULT_SMART_GEOMETRY_MIN_DIFFS
    try:
        min_span_pt = float(min_span_pt)
    except (TypeError, ValueError):
        min_span_pt = DEFAULT_SMART_GEOMETRY_MIN_SPAN_PT
    try:
        thin_min_diffs = int(thin_min_diffs)
    except (TypeError, ValueError):
        thin_min_diffs = 16

    kept = []
    for region in (regions or []):
        if int(region.get('geomCount', 0)) < min_diffs:
            continue
        bbox = region.get('bbox')
        if not bbox or len(bbox) < 4:
            continue
        width = abs(float(bbox[2]) - float(bbox[0]))
        height = abs(float(bbox[3]) - float(bbox[1]))
        if max(width, height) < min_span_pt:
            continue
        if min(width, height) < min_span_pt and int(
                region.get('geomCount', 0)) < thin_min_diffs:
            continue
        kept.append(region)
    return kept


def attach_text_regions_to_hotspots(hotspots, text_regions, page_width,
                                    page_height,
                                    gap_fraction=
                                    DEFAULT_SMART_TEXT_ATTACH_GAP_FRACTION,
                                    grid_cols=DEFAULT_GRID_COLS,
                                    grid_rows=DEFAULT_GRID_ROWS,
                                    max_fraction=DEFAULT_MAX_REGION_FRACTION):
    """把熱點附近的文字差異併入同一區，避免同一物件出現兩朵雲。

    只允許文字框與幾何熱點相交或落在很小的空隙內；不會因為「同一頁」或
    「同一個大格」就把遠處文字串起來。未找到附近熱點的文字區域原樣保留，
    所以純文字變更不會被幾何過濾吞掉。
    """
    anchors = [dict(region) for region in (hotspots or [])]
    remaining = []
    short_side = min(float(page_width), float(page_height))
    try:
        gap = max(float(gap_fraction) * short_side, 0.0)
    except (TypeError, ValueError):
        gap = DEFAULT_SMART_TEXT_ATTACH_GAP_FRACTION * short_side

    for text_region in (text_regions or []):
        target = text_region.get('bbox')
        if not target:
            remaining.append(text_region)
            continue
        nearest = None
        nearest_gap = None
        for index, anchor in enumerate(anchors):
            if anchor.get('oversized'):
                continue
            distance = _bbox_gap(anchor.get('bbox'), target)
            if distance <= gap and (nearest_gap is None or distance < nearest_gap):
                nearest = index
                nearest_gap = distance
        if nearest is None:
            remaining.append(text_region)
            continue

        anchor = anchors[nearest]
        bbox = anchor['bbox']
        anchor['bbox'] = (
            min(float(bbox[0]), float(target[0])),
            min(float(bbox[1]), float(target[1])),
            max(float(bbox[2]), float(target[2])),
            max(float(bbox[3]), float(target[3])))
        anchor['score'] = round(float(anchor.get('score', 0.0)) +
                                float(text_region.get('score', 0.0)), 2)
        anchor['textCount'] = int(anchor.get('textCount', 0)) + int(
            text_region.get('textCount', 0))
        anchor['geomCount'] = int(anchor.get('geomCount', 0)) + int(
            text_region.get('geomCount', 0))
        samples = (list(anchor.get('samples') or []) +
                   list(text_region.get('samples') or []))
        samples.sort(key=lambda sample: (
            0 if str(sample.get('kind', '')).startswith('text') else 1))
        anchor['samples'] = samples[:6]
        bbox = anchor['bbox']
        anchor['pageFraction'] = round(
            ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) /
            float(page_width * page_height), 4)
        anchor['oversized'] = anchor['pageFraction'] > float(max_fraction)
        anchor['gridLabel'] = _grid_label_for_bbox(
            bbox, page_width, page_height, grid_cols, grid_rows)

    return anchors + remaining


def merge_overlapping_regions(regions, page_width, page_height,
                              min_overlap_fraction=
                              DEFAULT_SMART_MERGE_OVERLAP_FRACTION,
                              max_fraction=DEFAULT_MAX_REGION_FRACTION,
                              grid_cols=DEFAULT_GRID_COLS,
                              grid_rows=DEFAULT_GRID_ROWS):
    """合併高度重疊的局部區域，主要用來把同一物件的刪除／新增框併成一朵雲。"""
    merged = [dict(region) for region in (regions or [])]
    changed = True
    while changed:
        changed = False
        for left_index in range(len(merged)):
            left = merged[left_index]
            if left.get('oversized'):
                continue
            a = left['bbox']
            area_a = max(float(a[2]) - float(a[0]), 0.0) * max(
                float(a[3]) - float(a[1]), 0.0)
            if area_a <= 0.0:
                continue
            for right_index in range(left_index + 1, len(merged)):
                right = merged[right_index]
                # 整頁 CAD churn 是診斷，不是可與局部文字框合併的雲形。
                # 否則一個小文字框被大框包含，就會把局部結果重新撐成整頁。
                if right.get('oversized'):
                    continue
                b = right['bbox']
                area_b = max(float(b[2]) - float(b[0]), 0.0) * max(
                    float(b[3]) - float(b[1]), 0.0)
                if area_b <= 0.0:
                    continue
                ix = max(0.0, min(float(a[2]), float(b[2])) -
                         max(float(a[0]), float(b[0])))
                iy = max(0.0, min(float(a[3]), float(b[3])) -
                         max(float(a[1]), float(b[1])))
                overlap = ix * iy
                union = area_a + area_b - overlap
                # 用 IoU 判斷兩框是否真的是同一範圍。舊的 overlap/min-area
                # 會讓一個小文字框只因被大幾何框包含，就膨脹成涵蓋空白的大雲。
                if union <= 0.0 or overlap / union < min_overlap_fraction:
                    continue

                bbox = (min(float(a[0]), float(b[0])),
                        min(float(a[1]), float(b[1])),
                        max(float(a[2]), float(b[2])),
                        max(float(a[3]), float(b[3])))
                left['bbox'] = bbox
                left['score'] = round(float(left.get('score', 0.0)) +
                                      float(right.get('score', 0.0)), 2)
                left['textCount'] = int(left.get('textCount', 0)) + int(
                    right.get('textCount', 0))
                left['geomCount'] = int(left.get('geomCount', 0)) + int(
                    right.get('geomCount', 0))
                samples = (list(left.get('samples') or []) +
                           list(right.get('samples') or []))
                samples.sort(key=lambda sample: (
                    0 if str(sample.get('kind', '')).startswith('text') else 1))
                left['samples'] = samples[:6]
                fraction = ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / float(
                    page_width * page_height)
                left['pageFraction'] = round(fraction, 4)
                left['oversized'] = fraction > max_fraction
                cell_w = page_width / float(grid_cols)
                cell_h = page_height / float(grid_rows)
                c0 = int(min(max(bbox[0] / cell_w, 0), grid_cols - 1))
                c1 = int(min(max(bbox[2] / cell_w, 0), grid_cols - 1))
                r0 = int(min(max(bbox[1] / cell_h, 0), grid_rows - 1))
                r1 = int(min(max(bbox[3] / cell_h, 0), grid_rows - 1))
                left['gridLabel'] = '{}{}'.format(column_label(c0), r0 + 1)
                if (c0, r0) != (c1, r1):
                    left['gridLabel'] += ':{}{}'.format(
                        column_label(c1), r1 + 1)
                del merged[right_index]
                changed = True
                break
            if changed:
                break
    merged.sort(key=lambda region: -float(region.get('score', 0.0)))
    return merged


def _grid_label_for_bbox(bbox, page_width, page_height,
                         grid_cols=DEFAULT_GRID_COLS,
                         grid_rows=DEFAULT_GRID_ROWS):
    """依實際 bbox 產生格號，供合併／安全折疊後的區域使用。"""
    cell_w = page_width / float(grid_cols)
    cell_h = page_height / float(grid_rows)
    c0 = int(min(max(bbox[0] / cell_w, 0), grid_cols - 1))
    c1 = int(min(max(bbox[2] / cell_w, 0), grid_cols - 1))
    r0 = int(min(max(bbox[1] / cell_h, 0), grid_rows - 1))
    r1 = int(min(max(bbox[3] / cell_h, 0), grid_rows - 1))
    label = '{}{}'.format(column_label(c0), r0 + 1)
    if (c0, r0) != (c1, r1):
        label += ':{}{}'.format(column_label(c1), r1 + 1)
    return label


def _collapse_region_records(records, page_width, page_height,
                             max_fraction, grid_cols=DEFAULT_GRID_COLS,
                             grid_rows=DEFAULT_GRID_ROWS):
    """把超出智慧模式上限的區域折疊成一筆可複核的診斷。"""
    if not records:
        return None
    boxes = [tuple(float(value) for value in region['bbox'][:4])
             for region in records if region.get('bbox')]
    if not boxes:
        return None
    bbox = (min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes))
    fraction = ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / float(
        page_width * page_height)
    samples = []
    for region in records:
        samples.extend(region.get('samples') or [])
    order = {'text-change': 0, 'text-add': 1, 'text-delete': 2,
             'text-move': 3}
    samples.sort(key=lambda sample: order.get(sample.get('kind'), 9))
    return {
        'gridLabel': _grid_label_for_bbox(
            bbox, page_width, page_height, grid_cols, grid_rows),
        'bbox': bbox,
        'score': round(sum(float(region.get('score', 0.0))
                           for region in records), 2),
        'textCount': sum(int(region.get('textCount', 0))
                         for region in records),
        'geomCount': sum(int(region.get('geomCount', 0))
                         for region in records),
        'pageFraction': round(fraction, 4),
        'oversized': fraction > max_fraction,
        'samples': samples[:6],
        'collapsedRegionCount': len(records),
    }


def collapse_smart_region_overflow(regions, page_width, page_height,
                                   limit=DEFAULT_SMART_MAX_REGIONS_PER_PAGE,
                                   max_fraction=DEFAULT_MAX_REGION_FRACTION,
                                   grid_cols=DEFAULT_GRID_COLS,
                                   grid_rows=DEFAULT_GRID_ROWS):
    """限制智慧模式輸出量，且把被折疊的內容保留成一筆診斷。"""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_SMART_MAX_REGIONS_PER_PAGE
    if limit <= 0:
        limit = DEFAULT_SMART_MAX_REGIONS_PER_PAGE

    normal = [region for region in (regions or [])
              if not region.get('oversized')]
    existing_diagnostics = [region for region in (regions or [])
                            if region.get('oversized')]
    if len(normal) <= limit:
        return (list(regions or []), 0)

    kept = normal[:limit]
    overflow = normal[limit:]
    collapsed = _collapse_region_records(
        overflow, page_width, page_height, max_fraction,
        grid_cols, grid_rows)
    if collapsed is not None:
        collapsed['oversized'] = True
        existing_diagnostics.append(collapsed)
    output = kept + existing_diagnostics
    output.sort(key=lambda region: -float(region.get('score', 0.0)))
    return (output, len(overflow))


def drop_diffs_in_region(diffs, page_width, page_height, region):
    """把落在指定區域內的差異丟掉（預設用途：標題欄）。

    實測一份真實 14 頁圖說，每一頁的標題欄都出現 ``B版`` -> ``C(working)``
    的版次戳記變更。那是「這份圖說改版了」的證據，不是「這個位置的圖面改了」，
    圈成雲只會在每張圖的右下角留一朵無意義的雲。
    """
    if not region or page_width <= 0 or page_height <= 0:
        return list(diffs)
    x0 = region[0] * page_width
    y0 = region[1] * page_height
    x1 = region[2] * page_width
    y1 = region[3] * page_height
    kept = []
    for diff in diffs:
        x, y = diff['point']
        if x0 <= x <= x1 and y0 <= y <= y1:
            continue
        kept.append(diff)
    return kept


def _looks_like_title_block_revision_value(value):
    """只辨識標題欄中的版次／日期值，不把門窗編號當成版次。

    ``sheetNumberRegion`` 涵蓋右下角相當大的範圍；那裡在真實圖說中也可能
    放門窗編號、標高與詳圖索引。短數字（例如 ``185``）與代號（例如
    ``D2a``）因此刻意不算版次值。
    """
    text = normalize_text(value or '')
    if not text:
        return False
    upper = text.upper()
    if ('WORKING' in upper or 'REVISION' in upper or
            re.search(r'(^|\s)REV(?:\.|\s|$)', upper) or '版次' in text or
            re.search(r'[A-Z0-9]+\s*版(?:次)?$', upper)):
        return True
    return bool(re.match(
        r'^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$|^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$',
        text))


def drop_title_block_revision_diffs(diffs, page_width, page_height, region):
    """只剔除標題欄內的版次文字，保留同區域的圖面與門窗編號差異。"""
    if not region or page_width <= 0 or page_height <= 0:
        return list(diffs)
    x0 = region[0] * page_width
    y0 = region[1] * page_height
    x1 = region[2] * page_width
    y1 = region[3] * page_height
    kept = []
    for diff in diffs:
        x, y = diff['point']
        in_title_block = x0 <= x <= x1 and y0 <= y <= y1
        is_revision_text = (
            str(diff.get('kind', '')).startswith('text') and
            (_looks_like_title_block_revision_value(diff.get('before')) or
             _looks_like_title_block_revision_value(diff.get('after'))))
        if in_title_block and is_revision_text:
            continue
        kept.append(diff)
    return kept


def _is_sheet_number_value(value, sheet_numbers):
    """判斷一段文字是否就是本頁圖號（含 PDF 常見的專案前綴）。"""
    text = normalize_text(value)
    if not text:
        return False
    wanted = []
    for number in sheet_numbers or []:
        try:
            variants = _sheet_value_variants(number)
        except NameError:
            # 這個 helper 定義在本檔較後方；正常執行時模組已完整載入，
            # 這個分支只讓單獨載入／早期測試仍能安全回傳。
            variants = [normalize_text(number).upper()]
        for variant in variants:
            key = normalize_text(variant).replace(' ', '').upper()
            if key and key not in wanted:
                wanted.append(key)
    key = text.replace(' ', '').upper()
    for candidate in wanted:
        if key == candidate or key.endswith('-' + candidate):
            return True
    return False


def drop_smart_title_block_layout_diffs(diffs, page_width, page_height,
                                        region, sheet_numbers=None):
    """智慧模式再排除圖框排版文字，但保留圖框內的門窗／尺寸差異。

    ``drop_title_block_revision_diffs`` 只處理版次戳記，這是刻意的，因為
    完整差異報告需要保留其他文字。然而智慧圈選的目標是放置修訂雲；圖框
    裡的公司名、欄位標題、圖名與本頁圖號若跟著 PDF 重排，圈在右下角只會
    製造一朵沒有設計意義的雲。門窗／詳圖代碼、量測值與單次數字仍保留，
    並且只在智慧模式使用這個較積極的過濾器。
    """
    if not region or page_width <= 0 or page_height <= 0:
        return list(diffs)
    x0 = region[0] * page_width
    y0 = region[1] * page_height
    x1 = region[2] * page_width
    y1 = region[3] * page_height
    kept = []
    for diff in diffs:
        if not str(diff.get('kind', '')).startswith('text'):
            kept.append(diff)
            continue
        x, y = diff['point']
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            kept.append(diff)
            continue
        values = [diff.get('before'), diff.get('after')]
        if any(_is_sheet_number_value(value, sheet_numbers)
               for value in values):
            continue
        roles = [_smart_text_role(value) for value in values if value]
        if any(role in ('layout', 'cjk', 'latin', 'other') for role in roles):
            continue
        kept.append(diff)
    return kept


def _connected_components(cells):
    """8-連通的格子分群。格網很小（預設 108 格），走訪成本可以忽略。"""
    unvisited = set(cells)
    components = []
    while unvisited:
        seed = unvisited.pop()
        stack, group = [seed], [seed]
        while stack:
            col, row = stack.pop()
            for dc in (-1, 0, 1):
                for dr in (-1, 0, 1):
                    neighbour = (col + dc, row + dr)
                    if neighbour in unvisited:
                        unvisited.remove(neighbour)
                        stack.append(neighbour)
                        group.append(neighbour)
        components.append(group)
    return components


def _pick_samples(diffs, limit=6):
    """挑幾筆最有解釋力的差異給使用者看。

    ``text-change`` 排最前面——``CH=300 -> CH=320`` 一眼就知道發生什麼事，
    而 ``geom-add`` 只能說「這裡多了幾條線」。
    """
    order = {'text-change': 0, 'text-add': 1, 'text-delete': 2,
             'text-move': 3, 'geom-add': 4, 'geom-delete': 5}
    ranked = sorted(diffs, key=lambda d: order.get(d['kind'], 9))
    samples = []
    for diff in ranked[:limit]:
        samples.append({
            'kind': diff['kind'],
            'before': diff.get('before'),
            'after': diff.get('after'),
        })
    return samples


# ``get_text('dict')`` 在表格重排、不同 PDF 輸出器或字型替換時，常會把同一
# 個欄位拆成「舊值刪除＋新值新增」。這些低信號差異若全部送進智慧模式，
# 一張門窗表就會變成幾十朵雲。相反地，門窗號、詳圖號、尺寸與設備名稱是
# 使用者真正要看的高信號文字；下面的分類只用於智慧模式，不改變完整差異
# 報告與「只圈文字」模式的原始資料。
_SMART_LAYOUT_LABELS = frozenset([
    'DWG NO', 'DWG NO.', 'DWGNO', 'DRAWING NO', 'SHEET NO', 'SHT NO',
    'ISSUE NO', 'ISSUE NO.', 'TITLE', 'DWG TITLE', 'DRAWING TITLE',
    'DATE', 'SCALE', 'REV', 'REVISION', '備註', '說明', '空間位置',
    '門框', '五金', '數量', '天花板', '天花板高度', 'FFL',
])
_SMART_LAYOUT_PREFIX_RE = re.compile(
    r'^(?:註|注|備註|說明|NOTE|NOTES|REMARK|REMARKS)\s*[:：]',
    re.IGNORECASE)
_SMART_CJK_RE = re.compile(r'[\u3400-\u9fff]')
_SMART_NUMBER_RE = re.compile(r'^[-+]?\d+(?:\.\d+)?$')
_SMART_IDENTIFIER_RE = re.compile(
    r'^[A-Za-z0-9][A-Za-z0-9_./-]*[A-Za-z0-9]$|^[A-Za-z0-9]$')


def _smart_text_role(value):
    """分類智慧模式文字，回傳 ``layout/cjk/measurement/identifier/number``。

    這是保守的「信號分類」而不是圖說語意解析器：分類不出來就回 ``other``，
    讓呼叫端不要因猜不到內容而放大一朵雲。``normalize_text`` 先折疊全形／
    空白，確保門窗號與尺寸在不同 PDF 輸出器下仍能落到同一類。
    """
    text = normalize_text(value)
    if not text:
        return 'empty'
    key = text.upper().rstrip(':：')
    if key in _SMART_LAYOUT_LABELS or _SMART_LAYOUT_PREFIX_RE.match(text):
        return 'layout'
    compact = re.sub(r'\s+', '', text)
    if _SMART_CJK_RE.search(text):
        return 'cjk'
    if re.search(r'(?:CM|MM|BOP|EL|CH)|[=＝*×xX]', compact,
                 re.IGNORECASE):
        return 'measurement'
    if _SMART_NUMBER_RE.match(compact):
        return 'number'
    if _SMART_IDENTIFIER_RE.match(compact) and any(
            char.isdigit() for char in compact):
        return 'identifier'
    if re.match(r'^[A-Za-z .:_/-]+$', text):
        return 'latin'
    return 'other'


def _smart_text_is_high_signal(value, font_size=0.0, frequency=None):
    """判斷新增／刪除文字是否值得進入智慧圈選。"""
    role = _smart_text_role(value)
    text = normalize_text(value)
    if role in ('empty', 'layout'):
        return False
    if role in ('identifier', 'measurement'):
        return True
    if role == 'cjk':
        # 三個以上中文字通常是設備名稱／變更說明；一字欄位標題在上面已排除。
        return len(text) >= 3
    if role == 'latin':
        return len(text) >= 4
    if role == 'number':
        # 重複數字即使字體較大，也多半是表格欄列重排殘留。真正的數字
        # 修正會走 text-change（例如 85 -> 90），不會在這裡被丟掉。
        if frequency is not None and frequency.get(text, 0) > 1:
            return False
        # 大字且只出現一次通常是門窗號／主要尺寸；小字的單次數字也保留，
        # 讓「刪除 290」這類可能重要的變更不會被靜默吞掉。
        return frequency is None or frequency.get(text, 0) <= 1
    return False


def _smart_text_diff_is_high_signal(diff, frequency=None):
    """保留智慧圈選需要的文字差異，排除表格欄位重排噪音。"""
    kind = diff.get('kind', '')
    if kind == 'text-move' or not kind.startswith('text'):
        return False

    before = diff.get('before')
    after = diff.get('after')
    if kind == 'text-change':
        before_role = _smart_text_role(before)
        after_role = _smart_text_role(after)
        if 'layout' in (before_role, after_role):
            return False
        similarity = float(diff.get('similarity') or 0.0)
        if similarity >= 0.35:
            return True
        # CJK 房名（例如「機房」→「操作室」）內容可能完全不同，但同類且
        # 位於原位置，仍是實際設計變更；跨類別則多半是欄位錯位。
        if before_role == after_role and before_role in (
                'cjk', 'identifier', 'number', 'measurement'):
            return True
        # 由空白標記改成門窗／踢腳代碼也值得看。
        if (normalize_text(before) in ('-', '—', '－') and
                _smart_text_is_high_signal(after, diff.get('fontSize'),
                                           frequency)):
            return True
        return False

    value = after if kind == 'text-add' else before
    return _smart_text_is_high_signal(
        value, diff.get('fontSize'), frequency)


def _smart_text_candidates(diffs, spans_a, spans_b,
                           strict_layout=False, high_churn=False):
    """從原始文字差異挑出智慧模式的高信號子集。

    整片幾何重繪時，未配對的舊表格數字大多是欄列重排，不應與局部設計
    變更同等看待。嚴格模式仍保留門窗／詳圖代碼的刪除，避免漏掉使用者特別
    在意的編號；只抑制小字數值與重複高程等低信號刪除。``high_churn``
    是更高一級的保護：文字圖元本身已經大量重排時，只保留「原位置內容
    真的改掉」的 text-change，且不把 ``- -> B1`` 這種欄位重排當成設計修改。
    """
    frequency = Counter(normalize_text(span.get('text'))
                        for span in list(spans_a or []) + list(spans_b or [])
                        if normalize_text(span.get('text')))
    candidates = []
    for diff in diffs:
        if not _smart_text_diff_is_high_signal(diff, frequency):
            continue
        if high_churn:
            if diff.get('kind') != 'text-change':
                continue
            before = normalize_text(diff.get('before'))
            after = normalize_text(diff.get('after'))
            if before in ('-', '—', '－') or after in ('-', '—', '－'):
                continue
        if strict_layout and diff.get('kind') == 'text-delete':
            role = _smart_text_role(diff.get('before'))
            # 舊版的單一門窗號／詳圖號被刪除仍可能是實際變更；數字、
            # 高程與一般說明文字在整頁重繪時則多半只是表格重排。
            if role != 'identifier':
                continue
        candidates.append(diff)
    return candidates


# ---- 純函式：圖號抽取與頁面配對 ------------------------------------------

def normalize_label(value):
    """標籤比對用的正規化：去尾端標點、轉大寫、摺疊空白。

    ``DWG NO.``、``DWG NO:``、``DWG  NO`` 是同一個標籤；圖框裡到底用哪一種
    是排版習慣，不該讓使用者為此去改設定。
    """
    text = normalize_text(value).upper()
    return text.rstrip('.:：、 ').strip()


def find_label_span(spans, labels):
    """找出欄位標籤所在的 span。找不到回 None。

    比對用 startswith 而不是完全相等——``DWG NO.`` 有時會跟後面的內容黏成
    同一個 span（``DWG NO. 0721B-...``），完全相等會漏掉那種寫法。
    """
    wanted = [normalize_label(item) for item in labels if item]
    for span in spans:
        key = normalize_label(span['text'])
        if not key:
            continue
        for label in wanted:
            if key == label or key.startswith(label):
                return span
    return None


# 一個欄位標籤永遠不會是另一個欄位的值。實測踩到的就是這一條：
# ``DWG NO.`` 正下方 24pt 處是 ``ISSUE NO.``，不排掉就會把它當圖號抓走。
_FIELD_LABEL_TAIL = re.compile(
    r'(?:^|\s)(?:NO|TITLE|DATE|SCALE|BY|REV|REVISION|SHEET|SHT|DWG|DRAWING'
    r'|JOB|ISSUE|PROJECT|CLIENT|DRAWN|DESIGNED|CHECKED|APPROVED)\.?$')

_FIELD_LABEL_ZH = frozenset([
    '圖號', '圖名', '比例', '日期', '製圖', '設計', '審核', '核准', '業主',
    '工程名稱', '專案名稱', '版次', '修訂', '張次', '圖別', '事務所'])


def looks_like_field_label(value):
    """這段文字看起來是欄位標籤而不是欄位值嗎？"""
    key = normalize_label(value)
    if not key:
        return False
    if key in _FIELD_LABEL_ZH:
        return True
    return bool(_FIELD_LABEL_TAIL.search(key))


def value_near_label(spans, label_span, labels,
                     cross_tolerance=DEFAULT_LABEL_CROSS_PT,
                     along_tolerance=DEFAULT_LABEL_ALONG_PT):
    """取標籤下方或右方最近的 span 當作欄位值。

    兩個方向都試，取距離較近的那一個：圖框有時把值放在標籤下面（直式欄位），
    有時放在右邊（橫式欄位），同一張圖框裡兩種都可能出現。與其要使用者先
    分辨自己的圖框是哪一種，不如兩種都找。

    ## 方向要用 bbox 邊緣判定，不能用中心點

    實測踩到的坑：``ISSUE NO.`` 的中心只比 ``DWG NO.`` 右 0.7pt——它其實在
    **正下方**，卻因為 ``cx > lx`` 成立就被算成「右方」，而右方的距離公式又
    讓它贏過真正的值。改用邊緣判定後語意就對了：**右方的值必須整個落在標籤
    右緣之外**，下方的值必須整個落在標籤下緣之下。

    其他欄位的標籤一律排除，見 :func:`looks_like_field_label`。
    """
    if label_span is None:
        return None

    lx0, ly0, lx1, ly1 = label_span['bbox']
    lx, ly = span_center(label_span['bbox'])
    label_keys = set(normalize_label(item) for item in labels if item)
    edge_slack = 1.0

    best = None
    best_score = None
    for span in spans:
        if span is label_span:
            continue
        key = normalize_label(span['text'])
        if not key or key in label_keys:
            continue
        if any(key.startswith(item) for item in label_keys):
            continue
        if looks_like_field_label(span['text']):
            continue

        sx0, sy0, sx1, sy1 = span['bbox']
        cx, cy = span_center(span['bbox'])

        # 下方：整個 span 在標籤下緣之下
        if sy0 >= ly1 - edge_slack:
            gap = sy0 - ly1
            if gap <= cross_tolerance and abs(cx - lx) <= cross_tolerance:
                score = gap + abs(cx - lx) * 0.5
                if best_score is None or score < best_score:
                    best, best_score = span, score

        # 右方：整個 span 在標籤右緣之外
        if sx0 >= lx1 - edge_slack:
            gap = sx0 - lx1
            if gap <= cross_tolerance and abs(cy - ly) <= along_tolerance:
                score = gap + abs(cy - ly) * 0.5
                if best_score is None or score < best_score:
                    best, best_score = span, score

    return normalize_text(best['text']) if best is not None else None


def extract_by_label(spans, labels,
                     cross_tolerance=DEFAULT_LABEL_CROSS_PT,
                     along_tolerance=DEFAULT_LABEL_ALONG_PT):
    """標籤定位的欄位抽取。回傳值字串或 None。"""
    label_span = find_label_span(spans, labels)
    if label_span is None:
        return None
    return value_near_label(spans, label_span, labels,
                            cross_tolerance, along_tolerance)


def extract_sheet_number(spans, page_width, page_height,
                         region=DEFAULT_SHEET_REGION,
                         pattern=DEFAULT_SHEET_PATTERN,
                         labels=DEFAULT_NUMBER_LABELS):
    """找圖號，回傳 ``(best, candidates)``。

    ## 兩段式，標籤優先

    1. **標籤定位**（主要）：找 ``DWG NO.`` / ``圖號`` 這種欄位標籤，取它下方
       或右方最近的字。實測一份真實 A3 圖說 14 頁全中，兩份新舊版一一對應。
    2. **regex + 區域**（備援）：標籤找不到時，才在指定區域內用格式比對。

    順序不能顛倒。regex 要求使用者先看懂自己的圖號長什麼樣、再寫出正確的
    pattern；而標籤是圖框本來就印在上面的東西。實測那份圖說的圖號是
    ``0721B-ARD-D02001``，預設 regex 一個都接不到，但 ``DWG NO.`` 標籤在。

    區域、regex 與標籤清單 **都是參數不是常數**——依
    ``domain/user-specified-runtime-parameters.md``，圖框配置是每個案子自己的
    事，寫死等於只服務第一個案子。

    回傳「候選清單」而不是單一答案，是因為自動抽取一定會有猜錯的時候，
    UI 必須能讓使用者從候選裡挑，或直接手打。
    """
    if page_width <= 0 or page_height <= 0:
        return (None, [])

    # 標籤定位不需要知道圖框在頁面哪個角落，所以先做、且不受 region 限制。
    by_label = extract_by_label(spans, labels)
    if by_label:
        return (by_label, [by_label])

    x0 = region[0] * page_width
    y0 = region[1] * page_height
    x1 = region[2] * page_width
    y1 = region[3] * page_height

    try:
        compiled = re.compile(pattern)
    except re.error:
        return (None, [])

    candidates = []
    for span in spans:
        cx, cy = span_center(span['bbox'])
        if not (x0 <= cx <= x1 and y0 <= cy <= y1):
            continue
        text = normalize_text(span['text'])
        if not text or not compiled.match(text):
            continue
        # 越靠右下越可能是圖號欄；用距離右下角的遠近排序。
        distance = ((page_width - cx) ** 2 + (page_height - cy) ** 2) ** 0.5
        candidates.append((distance, text))

    if not candidates:
        return (None, [])
    candidates.sort()
    ordered = []
    for _, text in candidates:
        if text not in ordered:
            ordered.append(text)
    return (ordered[0], ordered)


# 標題欄裡「不是圖名」的東西：比例尺、日期、純數字、單頁編號。
# 這些跟圖名混在同一塊區域，字級有時也不小，必須先排掉。
_NOT_A_NAME = re.compile(
    r'^(?:'
    r'\d+(?:[./:-]\d+)*'                    # 純數字、日期、比例尺 1:100、2026/08/26
    r'|[Ss]\s*[:=]?\s*1\s*[:/]\s*\d+'       # S:1/100 這種比例尺寫法
    r'|1\s*[:/]\s*\d+'
    r'|(?:NO|No|no|SHEET|Sheet|SCALE|Scale|DATE|Date|REV|Rev)\.?'
    r'|[A-Za-z]'                            # 單一字母（欄位代號）
    r')$')

# 註記不是圖名。實測踩到：新版第 3 頁在標題欄附近多了一段
# 「註:詳細高程詳機電設備圖」，字級剛好比真正的圖名大，就把圖名擠掉了。
_NOTE_PREFIX = re.compile(r'^(?:註|注|備註|說明|NOTE|NOTES|REMARK|REMARKS)\s*[:：.]?')


def refine_sheet_names(pages, min_pages=3):
    """跨頁挑掉「每頁都一樣」的候選，把真正的圖名選出來。

    ## 為什麼單頁看字級不夠

    實測那份圖說，標題欄裡字級最大的是專案名
    ``統一企業集團桃園U-PARK智匯產業園區``（12.4pt）與 ``建築新建工程``
    （12.4pt），而真正的圖名 ``地下一層平面圖`` 只有 11pt。單看一頁的字級
    會挑到專案名。

    但專案名**每一頁都一模一樣**，那正是它當不了圖名的原因——圖名的職責是
    區分這一頁與其他頁。所以規則很簡單：**在所有頁面都出現的候選，一律不是
    圖名。** 這條規則不依賴任何一家事務所的排版習慣。

    頁數太少（``min_pages`` 以下）時不做這件事：三頁以內「每頁都出現」可能
    只是巧合，貿然剔除反而會把正確答案刪掉。
    """
    if not pages or len(pages) < min_pages:
        return pages

    counts = {}
    for page in pages:
        for text in set(page.get('sheetNameCandidates') or []):
            counts[text] = counts.get(text, 0) + 1

    total = len(pages)
    for page in pages:
        candidates = page.get('sheetNameCandidates') or []
        varying = [t for t in candidates if counts.get(t, 0) < total]
        if varying:
            page['sheetNameCandidates'] = varying + [
                t for t in candidates if t not in varying]
            page['sheetName'] = varying[0]
    return pages


def extract_sheet_name(spans, page_width, page_height,
                       region=DEFAULT_SHEET_REGION, sheet_number=None,
                       min_length=2, labels=DEFAULT_NAME_LABELS):
    """從標題欄區域找圖名候選，回傳 ``(best, candidates)``。

    ## 為什麼用字級排序而不是位置

    標題欄的欄位配置每家事務所都不一樣，用「圖名一定在圖號上面／左邊」這種
    位置規則寫死，換一份圖框就全錯。但**圖名幾乎一定是標題欄裡最大的字之一**
    ——那是圖框設計的通則，不是某一家的習慣。所以先按字級排，同字級再按
    「離圖號多近」排（圖名與圖號通常同一格或相鄰格）。

    排除規則處理的是「跟圖名擠在同一塊區域、字級又不小」的東西：比例尺、
    日期、純數字、``SHEET``／``SCALE`` 這類欄位標籤。圖號本身也要排掉。

    跟 :func:`extract_sheet_number` 一樣回傳候選清單——猜錯時使用者要能改。
    """
    if page_width <= 0 or page_height <= 0:
        return (None, [])

    x0 = region[0] * page_width
    y0 = region[1] * page_height
    x1 = region[2] * page_width
    y1 = region[3] * page_height

    # 圖名同樣先試標籤（DWG TITLE / 圖名）；沒有標籤才退回字級啟發式。
    by_label = extract_by_label(spans, labels)
    if by_label:
        return (by_label, [by_label])

    number_key = normalize_text(sheet_number) if sheet_number else None
    number_center = None
    if number_key:
        for span in spans:
            if normalize_text(span['text']) == number_key:
                number_center = span_center(span['bbox'])
                break

    scored = []
    for span in spans:
        cx, cy = span_center(span['bbox'])
        if not (x0 <= cx <= x1 and y0 <= cy <= y1):
            continue
        text = normalize_text(span['text'])
        if not text or len(text) < min_length:
            continue
        if number_key and text == number_key:
            continue
        if _NOT_A_NAME.match(text):
            continue
        if _NOTE_PREFIX.match(text):
            continue
        distance = 0.0
        if number_center is not None:
            distance = ((cx - number_center[0]) ** 2
                        + (cy - number_center[1]) ** 2) ** 0.5
        # 字級大的優先（負號讓 sort 由大到小），同字級離圖號近的優先
        scored.append((-float(span.get('size') or 0.0), distance, text))

    if not scored:
        return (None, [])
    scored.sort()
    ordered = []
    for _size, _distance, text in scored:
        if text not in ordered:
            ordered.append(text)
    return (ordered[0], ordered)


def pair_pages(pages_a, pages_b):
    """依圖號配對兩份 PDF 的頁面。

    回傳 ``(matched, only_a, only_b)``。三類全部攤開回傳，不吞掉任何一頁——
    「新版多了一張圖」跟「這張圖有變更」同樣是使用者要知道的事。

    圖號抽不到的頁面一律進 ``only_*``，由 UI 讓使用者手動指定。
    """
    index_b = {}
    for page in pages_b:
        key = page.get('sheetNumber')
        if key:
            index_b.setdefault(key, []).append(page)

    matched, only_a = [], []
    used = set()
    for page in pages_a:
        key = page.get('sheetNumber')
        bucket = index_b.get(key) if key else None
        partner = None
        if bucket:
            for candidate in bucket:
                if id(candidate) not in used:
                    partner = candidate
                    break
        if partner is None:
            only_a.append(page)
        else:
            used.add(id(partner))
            matched.append((page, partner))

    only_b = [p for p in pages_b if id(p) not in used]
    return (matched, only_a, only_b)


def detect_page_kind(spans, drawings):
    """判斷這一頁是向量還是掃描件。

    沒有文字 span 也沒有繪圖指令 = 整頁是一張點陣圖。這種頁面本工具做不了，
    必須明確回報 ``scanned`` 讓 UI 標示，**不可以讓它走完流程回報「無差異」**。
    """
    if not spans and not drawings:
        return 'scanned'
    if not spans:
        return 'no-text'
    return 'vector'


# ---- PyMuPDF 邊界：只有以下三個函式碰 fitz -------------------------------

def _require_fitz():
    """匯入 PyMuPDF，失敗時給出可以照著做的指示而不是 traceback。

    issue #93 的教訓：多版本 Python 環境下，「裝了但 Revit 叫到另一支」
    跟「沒裝」的症狀一模一樣，所以錯誤訊息一定要附上實際的直譯器路徑。
    """
    try:
        import fitz
        return fitz
    except Exception as exc:
        raise RuntimeError(
            '無法匯入 PyMuPDF（fitz）：{}: {}\n'
            '請在這一支 Python 安裝：\n'
            '    "{}" -m pip install pymupdf\n'
            '目前 Python：{}（版本 {}）'.format(
                type(exc).__name__, exc,
                sys.executable, sys.executable,
                sys.version.split()[0]))


def _rotation_matrix(page):
    """取得「未旋轉座標 -> 顯示座標」的轉換矩陣。

    **旋轉頁是建築 PDF 的常態，而 PyMuPDF 在這件事上會騙人。**
    ``page.get_text()`` 與 ``page.get_drawings()`` 回傳的座標在**未旋轉**空間
    （``mediabox``，例如 842x1191），但 ``page.rect`` 是**旋轉後**的顯示尺寸
    （1191x842）。拿後者去正規化前者，算出來的比例會超過 100%，圖框位置整個
    找錯——實測一份 A3 橫式圖說，y 座標跑到 118%。

    一律轉到**顯示座標**而不是反過來：使用者看到的、以及 Revit 圖紙上的方位，
    都是旋轉後的樣子。雲必須落在使用者看到差異的地方。
    """
    try:
        if page.rotation:
            return page.rotation_matrix
    except Exception:
        pass
    return None


def _apply_matrix_to_rect(fitz, matrix, bbox):
    if matrix is None:
        return tuple(bbox)
    rect = fitz.Rect(bbox) * matrix
    return (rect.x0, rect.y0, rect.x1, rect.y1)


def extract_spans(page):
    """抽出一頁的所有文字 span，轉成純資料（座標已轉到顯示空間）。

    連 ``size``（字級）一起帶出來：標題欄裡圖名通常是除了圖號以外最大的字，
    那是抽圖名最可靠的訊號，比「位置猜測」穩得多。
    """
    fitz = _require_fitz()
    matrix = _rotation_matrix(page)
    spans = []
    data = page.get_text('dict')
    for block in data.get('blocks', []):
        for line in block.get('lines', []):
            for span in line.get('spans', []):
                text = span.get('text', '')
                if not text or not text.strip():
                    continue
                spans.append({
                    'text': text,
                    'bbox': _apply_matrix_to_rect(fitz, matrix,
                                                  span.get('bbox')),
                    'size': float(span.get('size') or 0.0),
                })
    return spans


def extract_drawings(page):
    """抽出一頁的所有向量繪圖指令，轉成純資料（座標已轉到顯示空間）。

    轉成純資料而不是直接傳 fitz 物件，是為了讓下游的指紋化函式能離線測試。

    旋轉的處理與 :func:`extract_spans` 一致——文字與幾何**必須在同一個座標
    空間**，否則全域對齊會拿文字算出一個平移量，套到幾何上卻是錯的方向。
    """
    fitz = _require_fitz()
    matrix = _rotation_matrix(page)
    paths = []
    for path in page.get_drawings():
        items = []
        for item in path.get('items', []):
            kind = item[0]
            if kind == 're' and len(item) >= 2:
                # item[2] 是矩形方向值，不可當成第五個幾何座標。
                items.append((
                    kind,
                    _apply_matrix_to_rect(fitz, matrix, item[1])))
                continue
            if kind == 'qu' and len(item) >= 2:
                quad = item[1]
                points = []
                for name in ('ul', 'ur', 'lr', 'll'):
                    point = getattr(quad, name, None)
                    if point is None:
                        continue
                    point = fitz.Point(point.x, point.y)
                    if matrix is not None:
                        point = point * matrix
                    points.extend((float(point.x), float(point.y)))
                if len(points) == 8:
                    items.append((kind, tuple(points)))
                continue
            converted = [item[0]]
            for value in item[1:]:
                if hasattr(value, 'x') and hasattr(value, 'y'):
                    point = fitz.Point(value.x, value.y)
                    if matrix is not None:
                        point = point * matrix
                    converted.append((float(point.x), float(point.y)))
                elif hasattr(value, 'x0'):
                    converted.append(_apply_matrix_to_rect(fitz, matrix, value))
                else:
                    try:
                        converted.append(float(value))
                    except (TypeError, ValueError):
                        pass
            items.append(tuple(converted))
        # 保留 get_drawings 的 path metadata，讓後續可以在「指紋化前」辨識
        # Revit 既有 Revision Cloud。這些欄位不參與一般幾何指紋，只有
        # filter_revision_clouds 會使用 type/fill；rect 等欄位則方便診斷。
        rect = path.get('rect')
        if rect is not None:
            try:
                rect = tuple(float(value) for value in rect)
            except (TypeError, ValueError):
                rect = None
        try:
            width = float(path.get('width') or 0.0)
        except (TypeError, ValueError):
            width = 0.0
        paths.append({
            'items': items,
            'type': path.get('type'),
            'rect': rect,
            'width': width,
            'color': path.get('color'),
            'fill': path.get('fill'),
            'closePath': bool(path.get('closePath')),
        })
    return paths


# ---- 主流程 ---------------------------------------------------------------

def read_pdf(path, options):
    """讀一份 PDF，回傳每頁的純資料摘要。"""
    fitz = _require_fitz()
    doc = fitz.open(path)
    pages = []
    limit = options.get('pages')
    limit = set(limit) if limit else None
    try:
        for index, page in enumerate(doc):
            if limit is not None and (index + 1) not in limit:
                continue
            spans = extract_spans(page)
            drawings = extract_drawings(page)
            rect = page.rect
            title_region = tuple(
                options.get('sheetNumberRegion', DEFAULT_SHEET_REGION))
            best, candidates = extract_sheet_number(
                spans, rect.width, rect.height, title_region,
                options.get('sheetNumberPattern', DEFAULT_SHEET_PATTERN))
            name, name_candidates = extract_sheet_name(
                spans, rect.width, rect.height, title_region, best)
            pages.append({
                'pageIndex': index,
                'pageNumber': index + 1,
                'pageWidthPt': rect.width,
                'pageHeightPt': rect.height,
                'kind': detect_page_kind(spans, drawings),
                'sheetNumber': best,
                'sheetNumberCandidates': candidates,
                'sheetName': name,
                'sheetNameCandidates': name_candidates,
                'spans': spans,
                'drawings': drawings,
            })
    finally:
        doc.close()
    # 圖名要跨頁比對才選得準（專案名每頁都一樣，當不了識別）
    return refine_sheet_names(pages)


def compare_page(page_a, page_b, options):
    """比對配對好的兩頁，回傳含差異區域的結果 dict。"""
    quantum = float(options.get('quantum', DEFAULT_QUANTUM_PT))
    align_tol = float(options.get('alignTolerancePt', DEFAULT_ALIGN_TOL_PT))

    spans_a = page_a['spans']
    spans_b = page_b['spans']
    dx, dy = estimate_page_offset(spans_a, spans_b)
    spans_b = shift_spans(spans_b, dx, dy)

    # 舊圖可能已經包含 Revit Revision Cloud。它代表「更早的版次」，不是
    # 這次 A/B 比對的修改；兩邊都先剔除，否則舊雲會被當成大量新增/刪除弧線，
    # 也會把真正的差異區域撐大。一般單一路徑圓弧不符合雲狀的多 path 封閉鏈
    # 條件，仍會保留在比對裡。
    drawings_a, cloud_stats_a = filter_revision_clouds(
        page_a['drawings'], options)
    drawings_b, cloud_stats_b = filter_revision_clouds(
        page_b['drawings'], options)

    # B 的偏移在量化前扣掉（見 fingerprint_drawings 的說明），
    # A 不動——兩邊都換算到 A 的座標系。
    fps_a = fingerprint_drawings(drawings_a, quantum)
    fps_b = fingerprint_drawings(drawings_b, quantum, dx, dy)

    raw_text_diffs = diff_text_spans(
        spans_a, spans_b,
        float(options.get('moveTolerancePt', DEFAULT_MOVE_TOL_PT)))
    diffs = list(raw_text_diffs)
    diffs.extend(diff_geometry(fps_a, fps_b))

    # 舊雲內的版次泡泡文字（例如 8-9 -> 6-7）也是歷史註記，不是本次
    # 圖面修改。B 的 cloud bbox 要先扣掉 page offset，因為上面的文字與幾何
    # 差異都已經被搬到 A 的座標系；否則 B 版的遮罩會偏移一整頁的對齊量。
    # 不能再把 bbox 內所有文字整批丟掉；C5 -> C8、1-5 與設備名稱可能正是
    # 使用者要圈出的新內容，改由選擇性版次註記過濾器處理。
    revision_cloud_bboxes = [cloud['bbox']
                             for cloud in cloud_stats_a['clouds']]
    revision_cloud_bboxes.extend(
        _shift_bbox(cloud['bbox'], -dx, -dy)
        for cloud in cloud_stats_b['clouds'])
    masked_revision_cloud_diffs = len(diffs)
    diffs = drop_revision_cloud_annotation_diffs(
        diffs, revision_cloud_bboxes,
        options.get('revisionCloudMaskPaddingPt',
                    DEFAULT_REVISION_CLOUD_MASK_PADDING_PT))
    masked_revision_cloud_diffs -= len(diffs)

    # 標題欄的版次戳記每頁都變，那是「這份圖說改版了」不是「這個位置改了」。
    if options.get('excludeTitleBlock', DEFAULT_EXCLUDE_TITLE_BLOCK):
        diffs = drop_title_block_revision_diffs(
            diffs, page_a['pageWidthPt'], page_a['pageHeightPt'],
            tuple(options.get('sheetNumberRegion', DEFAULT_SHEET_REGION)))

    # 兩組區域，因為兩種問題需要不同的答案：
    #
    # `regions`     —— 全部差異。回答「這頁改了多少」。實測真實圖說時它幾乎
    #                  一定是一大塊，因為圖真的整張都動了。
    # `textRegions` —— 只用文字差異、格網更細。回答「哪幾個位置可以圈雲」。
    #                  文字變更是精準的（`防潰堤H=30cm` -> `H=50cm`），
    #                  分群後多半是佔頁面 1~2% 的小框，那才圈得出有用的雲。
    #
    # 不能只留一組：全部差異算出來的大塊即使含有文字變更，框也大到沒有意義；
    # 而只看文字會漏掉「這頁被重畫了」這個同樣要緊的事實。
    def _cluster(source, eps_fraction=None, geom_weight=None,
                 max_span_fraction=DEFAULT_MAX_SPAN_FRACTION,
                 force_split_dense=False):
        if eps_fraction is None:
            eps_fraction = float(options.get('epsFraction',
                                             DEFAULT_EPS_FRACTION))
        if geom_weight is None:
            geom_weight = float(options.get('geomWeight',
                                            DEFAULT_GEOM_WEIGHT))
        return cluster_diffs(
            source, page_a['pageWidthPt'], page_a['pageHeightPt'],
            eps_fraction,
            float(options.get('threshold', DEFAULT_THRESHOLD)),
            float(options.get('textWeight', DEFAULT_TEXT_WEIGHT)),
            geom_weight,
            float(options.get('maxRegionFraction',
                              DEFAULT_MAX_REGION_FRACTION)),
            float(options.get('minGapFraction', DEFAULT_MIN_GAP_FRACTION)),
            int(options.get('gridCols', DEFAULT_GRID_COLS)),
            int(options.get('gridRows', DEFAULT_GRID_ROWS)),
            max_span_fraction,
            force_split_dense)

    # text-move 只代表未改內容的文字位置變了，常見原因是圖面重排或 PDF
    # 內部文字基線差異；它不應把真正的新增/刪除文字拉進同一朵雲。
    text_only = [d for d in diffs
                 if d['kind'] in ('text-add', 'text-delete', 'text-change')]
    text_regions = _cluster(
        text_only,
        float(options.get('textEpsFraction', DEFAULT_TEXT_EPS_FRACTION)))
    regions = _cluster(diffs)
    # 智慧模式要先區分「局部變更」與「整片 CAD 重繪」。若把後者的每一條
    # unmatched line 都送入 force_split_dense，均勻密集的線會被中位數遞迴切成
    # 數百個假局部；這正是使用者看到 500 多朵雲的來源。大量幾何只留一筆
    # oversized 診斷，讓 UI 預設隱藏它但不吞掉事實。
    smart_max_primitive_span = float(options.get(
        'smartMaxPrimitiveSpanFraction',
        DEFAULT_SMART_MAX_PRIMITIVE_SPAN_FRACTION))

    def _is_smart_local(diff):
        if diff['kind'].startswith('text'):
            return diff['kind'] != 'text-move'
        bbox = diff.get('bbox')
        if not bbox:
            return True
        width = abs(float(bbox[2]) - float(bbox[0]))
        height = abs(float(bbox[3]) - float(bbox[1]))
        return (width <= page_a['pageWidthPt'] * smart_max_primitive_span and
                height <= page_a['pageHeightPt'] * smart_max_primitive_span)

    smart_eps = float(options.get(
        'smartEpsFraction', DEFAULT_SMART_EPS_FRACTION))
    smart_text_eps = float(options.get(
        'smartTextEpsFraction', DEFAULT_SMART_TEXT_EPS_FRACTION))
    smart_span = float(options.get(
        'smartMaxSpanFraction', DEFAULT_SMART_MAX_SPAN_FRACTION))
    geometry_diffs = [d for d in diffs
                      if not d['kind'].startswith('text')]
    filtered_item_count_a = sum(len(path.get('items') or [])
                                for path in drawings_a)
    filtered_item_count_b = sum(len(path.get('items') or [])
                                for path in drawings_b)
    geometry_density = len(geometry_diffs) / float(max(
        filtered_item_count_a, filtered_item_count_b, 1))
    smart_geometry_density = float(options.get(
        'smartGeometryDensityFraction',
        DEFAULT_SMART_GEOMETRY_DENSITY_FRACTION))
    global_geometry_change = geometry_density >= smart_geometry_density

    strict_text_density = float(options.get(
        'smartStrictTextDensityFraction',
        DEFAULT_SMART_STRICT_TEXT_DENSITY_FRACTION))
    high_churn_text_limit = int(options.get(
        'smartHighChurnTextDiffs', DEFAULT_SMART_HIGH_CHURN_TEXT_DIFFS))
    raw_text_content_count = sum(1 for diff in raw_text_diffs
                                 if diff['kind'] != 'text-move')
    high_churn = (raw_text_content_count >= high_churn_text_limit and
                  geometry_density >= 0.80)
    elevation_sheet = (_is_elevation_sheet(page_a) or
                       _is_elevation_sheet(page_b))
    smart_text = _smart_text_candidates(
        text_only, spans_a, spans_b,
        strict_layout=geometry_density >= strict_text_density,
        high_churn=high_churn)
    if options.get('excludeTitleBlock', DEFAULT_EXCLUDE_TITLE_BLOCK):
        sheet_numbers = [page_a.get('sheetNumber'),
                         page_b.get('sheetNumber')]
        sheet_numbers.extend(page_a.get('sheetNumberCandidates') or [])
        sheet_numbers.extend(page_b.get('sheetNumberCandidates') or [])
        smart_text = drop_smart_title_block_layout_diffs(
            smart_text, page_a['pageWidthPt'], page_a['pageHeightPt'],
            tuple(options.get('sheetNumberRegion', DEFAULT_SHEET_REGION)),
            sheet_numbers)
    if global_geometry_change:
        # 只用高信號文字定位局部雲：門窗號、詳圖號、尺寸、設備名稱，以及
        # 同位置的 CJK 名稱變更；表格欄位錯位不會再把整頁文字串成雲。
        text_anchors = _cluster(
            smart_text, smart_text_eps,
            float(options.get('smartGeomWeight', 1.5)), smart_span, False)
        # 幾何差異若整片重繪，不能逐條線分群。一般圖面抓相對密度最高的
        # 少數熱點；立面圖則用較寬的密集格網，保留整面門窗／牆體的複核範圍。
        smart_geom_weight = float(options.get('smartGeomWeight', 1.5))
        if elevation_sheet:
            hotspots = cluster_elevation_geometry_regions(
                geometry_diffs, page_a['pageWidthPt'], page_a['pageHeightPt'],
                int(options.get('gridCols', DEFAULT_GRID_COLS)),
                int(options.get('gridRows', DEFAULT_GRID_ROWS)),
                float(options.get(
                    'smartElevationGridThreshold',
                    DEFAULT_SMART_ELEVATION_GRID_THRESHOLD)),
                int(options.get('smartElevationMaxRegions',
                                DEFAULT_SMART_ELEVATION_MAX_REGIONS)),
                float(options.get('maxRegionFraction',
                                  DEFAULT_MAX_REGION_FRACTION)))
        else:
            hotspots = cluster_geometry_hotspots(
                geometry_diffs, page_a['pageWidthPt'], page_a['pageHeightPt'],
                int(options.get('gridCols', DEFAULT_GRID_COLS)),
                int(options.get('gridRows', DEFAULT_GRID_ROWS)),
                float(options.get('smartHotspotRatio',
                                  DEFAULT_SMART_HOTSPOT_RATIO)),
                int(options.get('smartHotspotMinDiffs',
                                DEFAULT_SMART_HOTSPOT_MIN_DIFFS)),
                int(options.get('smartHotspotMaxRegions',
                                DEFAULT_SMART_HOTSPOT_MAX_REGIONS)),
                smart_geom_weight,
                float(options.get('textWeight', DEFAULT_TEXT_WEIGHT)),
                float(options.get('maxRegionFraction',
                                  DEFAULT_MAX_REGION_FRACTION)))
        smart_regions = attach_text_regions_to_hotspots(
            hotspots, text_anchors, page_a['pageWidthPt'],
            page_a['pageHeightPt'],
            float(options.get('smartTextAttachGapFraction',
                              DEFAULT_SMART_TEXT_ATTACH_GAP_FRACTION)),
            int(options.get('gridCols', DEFAULT_GRID_COLS)),
            int(options.get('gridRows', DEFAULT_GRID_ROWS)),
            float(options.get('maxRegionFraction',
                              DEFAULT_MAX_REGION_FRACTION)))
        if geometry_diffs:
            diagnostic = _describe_group(
                geometry_diffs, page_a['pageWidthPt'], page_a['pageHeightPt'],
                float(options.get('textWeight', DEFAULT_TEXT_WEIGHT)),
                smart_geom_weight,
                float(options.get('maxRegionFraction',
                                  DEFAULT_MAX_REGION_FRACTION)),
                int(options.get('gridCols', DEFAULT_GRID_COLS)),
                int(options.get('gridRows', DEFAULT_GRID_ROWS)))
            # 密度已達整片重繪門檻，即使 bbox 恰好沒有跨過面積門檻，也要
            # 明確標為診斷；否則使用者取消「隱藏過大區域」時會誤以為這是
            # 一個可精準圈選的小變更。
            diagnostic['oversized'] = True
            diagnostic['diagnostic'] = 'globalGeometryChange'
            smart_regions.append(diagnostic)
    else:
        text_anchors = _cluster(
            smart_text, smart_text_eps,
            float(options.get('smartGeomWeight', 1.5)), smart_span, False)
        local_geometry = [d for d in geometry_diffs if _is_smart_local(d)]
        # 文字與線條使用不同距離：文字要能和同一欄位內的內容合併，線條
        # 則只把真的相鄰的牆／詳圖群組放在一起。先分開再合併，避免一條
        # 長 CAD 線把整列文字串成一朵怪雲。
        geometry_regions = _cluster(
            local_geometry,
            float(options.get('smartGeometryEpsFraction',
                              DEFAULT_SMART_GEOMETRY_EPS_FRACTION)),
            float(options.get('smartGeomWeight', 1.5)),
            float(options.get('smartGeometryMaxSpanFraction',
                              DEFAULT_SMART_MAX_SPAN_FRACTION)),
            False)
        geometry_min_diffs = int(options.get(
            'smartGeometryMinDiffs', DEFAULT_SMART_GEOMETRY_MIN_DIFFS))
        geometry_regions = filter_tiny_geometry_regions(
            geometry_regions, geometry_min_diffs,
            float(options.get('smartGeometryMinSpanPt',
                              DEFAULT_SMART_GEOMETRY_MIN_SPAN_PT)))
        smart_regions = attach_text_regions_to_hotspots(
            geometry_regions, text_anchors, page_a['pageWidthPt'],
            page_a['pageHeightPt'],
            float(options.get('smartTextAttachGapFraction',
                              DEFAULT_SMART_TEXT_ATTACH_GAP_FRACTION)),
            int(options.get('gridCols', DEFAULT_GRID_COLS)),
            int(options.get('gridRows', DEFAULT_GRID_ROWS)),
            float(options.get('maxRegionFraction',
                              DEFAULT_MAX_REGION_FRACTION)))
    smart_regions = merge_overlapping_regions(
        smart_regions, page_a['pageWidthPt'], page_a['pageHeightPt'],
        float(options.get('smartMergeOverlapFraction',
                          DEFAULT_SMART_MERGE_OVERLAP_FRACTION)),
        float(options.get('maxRegionFraction',
                          DEFAULT_MAX_REGION_FRACTION)),
        int(options.get('gridCols', DEFAULT_GRID_COLS)),
        int(options.get('gridRows', DEFAULT_GRID_ROWS)))
    smart_regions, collapsed_smart_regions = collapse_smart_region_overflow(
        smart_regions, page_a['pageWidthPt'], page_a['pageHeightPt'],
        int(options.get('smartMaxRegionsPerPage',
                        DEFAULT_SMART_MAX_REGIONS_PER_PAGE)),
        float(options.get('maxRegionFraction',
                          DEFAULT_MAX_REGION_FRACTION)),
        int(options.get('gridCols', DEFAULT_GRID_COLS)),
        int(options.get('gridRows', DEFAULT_GRID_ROWS)))

    warnings = []
    if page_a['kind'] != 'vector' or page_b['kind'] != 'vector':
        warnings.append(
            '本頁不是完整向量頁（舊版={}、新版={}），向量比對無法涵蓋，'
            '結果不可信'.format(page_a['kind'], page_b['kind']))
    if abs(dx) > align_tol or abs(dy) > align_tol:
        warnings.append(
            '兩頁整體位移達 ({:.1f}, {:.1f}) pt，超過容差 {:.1f} pt，'
            '請確認配到的是同一張圖'.format(dx, dy, align_tol))
    if cloud_stats_a['clouds'] or cloud_stats_b['clouds']:
        warnings.append(
            '已排除既有修訂雲：舊版 {} 組、新版 {} 組；'
            '這些雲不列入本次差異；另遮罩雲內 {} 筆差異'.format(
                len(cloud_stats_a['clouds']), len(cloud_stats_b['clouds']),
                masked_revision_cloud_diffs))
    if global_geometry_change:
        if elevation_sheet:
            warnings.append(
                '偵測到大量幾何重繪（線條差異 {} 筆，占剔除既有雲後圖元 {:.1%}）；'
                '立面圖改用少數大範圍密集區並保留一筆整體診斷，避免把建築立面'
                '拆成大量局部雲'.format(
                    len(geometry_diffs), float(geometry_density)))
        else:
            warnings.append(
                '偵測到大量幾何重繪（線條差異 {} 筆，占剔除既有雲後圖元 {:.1%}）；'
                '智慧模式改抓少數線條熱點並保留一筆整體診斷；局部文字與熱點附近'
                '文字合併，不再拆成大量局部雲'.format(
                    len(geometry_diffs), float(geometry_density)))
    if high_churn:
        warnings.append(
            '偵測到文字圖元大量重排（原始內容差異 {} 筆、排除既有雲後 {} 筆）；'
            '智慧模式只保留原位置的內容變更，避免表格重排產生大量雲'.format(
                raw_text_content_count, len(text_only)))
    if collapsed_smart_regions:
        warnings.append(
            '智慧模式原本有 {} 個局部區域，已將其中 {} 個折疊成一筆診斷；'
            '請取消「隱藏過大區域」查看整體範圍'.format(
                len(smart_regions) - 1 + collapsed_smart_regions,
                collapsed_smart_regions))

    return {
        'sheetNumber': page_a.get('sheetNumber') or page_b.get('sheetNumber'),
        'sheetNumberCandidates': page_a.get('sheetNumberCandidates') or [],
        'sheetName': page_a.get('sheetName') or page_b.get('sheetName'),
        'sheetNameCandidates': page_a.get('sheetNameCandidates') or [],
        'pageNumberA': page_a['pageNumber'],
        'pageNumberB': page_b['pageNumber'],
        'pageWidthPt': page_a['pageWidthPt'],
        'pageHeightPt': page_a['pageHeightPt'],
        'kindA': page_a['kind'],
        'kindB': page_b['kind'],
        'offset': (round(dx, 2), round(dy, 2)),
        'totalDiffs': len(diffs),
        # 圖元總數是「這頁到底改了多少」最誠實的單一指標。實測第 2 頁
        # 14803 -> 22007，那不是假差異，是整張圖被重畫了——使用者需要
        # 看到這個數字才知道該不該相信下面那幾朵雲。
        'itemCountA': sum(len(path.get('items') or [])
                          for path in page_a['drawings']),
        'itemCountB': sum(len(path.get('items') or [])
                          for path in page_b['drawings']),
        'itemCountAAfterRevisionCloudFilter': sum(
            len(path.get('items') or []) for path in drawings_a),
        'itemCountBAfterRevisionCloudFilter': sum(
            len(path.get('items') or []) for path in drawings_b),
        'revisionCloudsA': len(cloud_stats_a['clouds']),
        'revisionCloudsB': len(cloud_stats_b['clouds']),
        'revisionCloudPathCountA': cloud_stats_a['pathCount'],
        'revisionCloudPathCountB': cloud_stats_b['pathCount'],
        'revisionCloudCurveCountA': cloud_stats_a['curveCount'],
        'revisionCloudCurveCountB': cloud_stats_b['curveCount'],
        'revisionCloudMaskedDiffs': masked_revision_cloud_diffs,
        'textDiffs': sum(1 for d in diffs if d['kind'].startswith('text')),
        'geometryDiffs': len(geometry_diffs),
        'geometryDiffDensity': round(geometry_density, 4),
        'smartGlobalGeometryChange': global_geometry_change,
        'smartRegionsCollapsed': collapsed_smart_regions,
        'regions': regions,
        'smartRegions': smart_regions,
        'textRegions': text_regions,
        'warnings': warnings,
    }


def compare_pdfs(options):
    """完整流程：讀兩份 PDF -> 配對 -> 逐頁比對 -> 回傳結果 dict。"""
    pages_a = read_pdf(options['pdfA'], options)
    pages_b = read_pdf(options['pdfB'], options)
    matched, only_a, only_b = pair_pages(pages_a, pages_b)

    results = [compare_page(a, b, options) for a, b in matched]
    results.sort(key=lambda r: r['pageNumberA'])

    def _summary(page):
        return {'pageNumber': page['pageNumber'],
                'sheetNumber': page['sheetNumber'],
                'sheetNumberCandidates': page['sheetNumberCandidates'],
                'sheetName': page.get('sheetName'),
                'sheetNameCandidates': page.get('sheetNameCandidates') or [],
                'kind': page['kind']}

    return {
        'pdfA': options['pdfA'],
        'pdfB': options['pdfB'],
        'pageCountA': len(pages_a),
        'pageCountB': len(pages_b),
        'matchedCount': len(results),
        'pages': results,
        'onlyInA': [_summary(p) for p in only_a],
        'onlyInB': [_summary(p) for p in only_b],
    }


def _force_utf8_stdout():
    """把 stdout 轉成 UTF-8。

    Windows 的預設是 cp950，而本模組所有的錯誤訊息都是中文——不轉的話，
    ``print`` 自己會丟 UnicodeEncodeError，呼叫端拿到的是空輸出加上非零
    exit code，真正的原因反而看不到。診斷訊息在自己輸出的路上被吃掉，
    是最難查的一種故障。
    """
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def main(argv):
    _force_utf8_stdout()
    if len(argv) < 2:
        print(json.dumps({'error': '用法：pdf_diff_worker.py <args.json>'},
                         ensure_ascii=False))
        return 2
    try:
        with open(argv[1], 'r', encoding='utf-8') as handle:
            options = json.load(handle)
        result = compare_pdfs(options)
    except Exception as exc:
        print(json.dumps({
            'error': '{}: {}'.format(type(exc).__name__, exc),
            'python': sys.executable,
            'pythonVersion': sys.version.split()[0],
        }, ensure_ascii=False))
        return 1

    output = options.get('outputPath')
    if output:
        with open(output, 'w', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=False)
        print(json.dumps({'outputPath': output,
                          'matchedCount': result['matchedCount']},
                         ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
