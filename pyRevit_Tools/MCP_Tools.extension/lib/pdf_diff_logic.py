# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import re

"""把 PDF 差異區域換算成 Revit 圖紙上的修訂雲 — 純邏輯，無 Revit API。

這個模組**被 IronPython 2.7 匯入**（pyRevit 按鈕）**也被 CPython 3 匯入**
（pytest），所以嚴守 CLAUDE.md 的 2.7 禁令：無 f-string、無 ``pathlib``、
無型別註解、無 dict unpacking。

職責邊界：
- ``pdf_diff_worker`` 負責「PDF 上哪裡不一樣」（點座標，單位 pt）
- 本模組負責「那對應到 Revit 圖紙的哪裡」（單位 ft）與「該不該畫」
- ``pdf_diff_sources`` 負責從 Revit 撈圖紙
- C# 的 ``create_revision_clouds_on_sheets`` 負責真的畫下去

## 座標系的兩個陷阱

1. **y 軸方向相反。** PyMuPDF 的原點在左上、y 向下；Revit 圖紙的
   ``BoundingBoxUV`` 原點在左下、y 向上。少翻一次，雲會上下顛倒地
   出現在圖紙的另一半——而且看起來「好像有在動」，很難察覺。
2. **單位不同。** PDF 是 point（1/72 inch），Revit 內部是 foot。
   這裡不直接做單位換算，而是用「兩個矩形的比例對應」，因為那同時
   吸收了 PDF 邊界裁切造成的偏移。
"""


MM_PER_FOOT = 304.8

# 圖紙上的雲形預設外擴量。差異區域是格網對齊的粗框，本來就不精確，
# 外擴一點讓雲把邊界上的東西也圈進去。
DEFAULT_PADDING_MM = 5.0

# Revit 的修訂雲弧長是專案設定；框小於一個弧長時 RevisionCloud.Create 會丟例外。
# 這個下限是保守值，寧可畫大一點也不要整批失敗。
DEFAULT_MIN_SIZE_MM = 15.0

# 長寬比差超過這個比例就警告——多半代表配到錯的圖紙尺寸。
DEFAULT_ASPECT_TOLERANCE = 0.02

# 這個前綴是去重的安全標記：重跑時只自動清理本工具留下的雲，
# 沒有這個標記的手動雲預設保留，避免把使用者自己的註記刪掉。
# 文字刻意保持短，Comments 只放辨識標記與變更重點。
AUTO_COMMENT_PREFIX = u'[自動]'


def mm_to_feet(value):
    return float(value) / MM_PER_FOOT


def feet_to_mm(value):
    return float(value) * MM_PER_FOOT


def map_pdf_bbox_to_sheet(bbox_pt, page_size_pt, sheet_outline_ft):
    """把 PDF 頁面上的矩形換算成 Revit 圖紙紙面座標（feet）。

    ``bbox_pt``          ``(x0, y0, x1, y1)``，PyMuPDF 座標（原點左上、y 向下）
    ``page_size_pt``     ``(width, height)``
    ``sheet_outline_ft`` ``(min_u, min_v, max_u, max_v)``，來自 ``sheet.Outline``

    用比例對應而不是單位換算：PDF 若有邊界裁切，比例對應會自動吸收，
    而純單位換算會把整朵雲平移出去。

    **y 軸在這裡翻轉**——PDF 的 y0（上緣）對應圖紙的 max_v（上緣），
    所以換算後要重新取 min/max，否則會得到一個 v 顛倒的無效矩形。
    """
    page_w, page_h = float(page_size_pt[0]), float(page_size_pt[1])
    if page_w <= 0 or page_h <= 0:
        return None

    min_u, min_v, max_u, max_v = [float(v) for v in sheet_outline_ft]
    span_u = max_u - min_u
    span_v = max_v - min_v

    def to_u(x):
        return min_u + (float(x) / page_w) * span_u

    def to_v(y):
        # 1 - ratio 就是那一次翻轉。
        return min_v + (1.0 - float(y) / page_h) * span_v

    u0, u1 = to_u(bbox_pt[0]), to_u(bbox_pt[2])
    v0, v1 = to_v(bbox_pt[1]), to_v(bbox_pt[3])
    return (min(u0, u1), min(v0, v1), max(u0, u1), max(v0, v1))


def check_aspect_match(page_size_pt, sheet_outline_ft,
                       tolerance=DEFAULT_ASPECT_TOLERANCE):
    """比對 PDF 頁與 Revit 圖紙的長寬比，回傳 ``(ok, message)``。

    這是唯一便宜又有效的「配錯圖紙」偵測：A1 的 PDF 配到 A3 的圖紙，
    比例對應仍然算得出座標，雲仍然畫得出來，只是全部的位置都是錯的。
    長寬比一比就露餡。

    回傳警告而不是直接擋下來——比例略有出入的圖框在實務上存在，
    要不要接受是使用者的判斷。
    """
    page_w, page_h = float(page_size_pt[0]), float(page_size_pt[1])
    min_u, min_v, max_u, max_v = [float(v) for v in sheet_outline_ft]
    sheet_w = max_u - min_u
    sheet_h = max_v - min_v

    if page_w <= 0 or page_h <= 0 or sheet_w <= 0 or sheet_h <= 0:
        return (False, u'頁面或圖紙尺寸無效，無法換算座標')

    page_ratio = page_w / page_h
    sheet_ratio = sheet_w / sheet_h
    delta = abs(page_ratio - sheet_ratio) / max(page_ratio, sheet_ratio)
    if delta <= tolerance:
        return (True, None)
    # float() 不能省：IronPython 2.7 對 int 套 '{:.3f}' 會丟
    # ValueError: Precision not allowed in integer format specifier。
    return (False, u'PDF 頁長寬比 {:.3f} 與圖紙 {:.3f} 相差 {:.1%}，'
                   u'可能配到不同尺寸的圖紙'.format(
                       float(page_ratio), float(sheet_ratio), float(delta)))


def build_cloud_rect(bbox_ft, padding_mm=DEFAULT_PADDING_MM,
                     min_size_mm=DEFAULT_MIN_SIZE_MM):
    """把換算後的矩形加上外擴與最小尺寸下限，回傳雲形要用的矩形。

    最小尺寸不是美觀考量：Revit 的修訂雲由一段段弧組成，框比一個弧還小時
    ``RevisionCloud.Create`` 會直接丟例外。與其讓整批在 Revit 端一個個失敗，
    不如在這裡就把它撐到畫得出來的大小。

    撐大時**以中心為基準往兩邊撐**，位置才不會偏掉。
    """
    min_u, min_v, max_u, max_v = [float(v) for v in bbox_ft]
    pad = mm_to_feet(padding_mm)
    min_u -= pad
    min_v -= pad
    max_u += pad
    max_v += pad

    floor = mm_to_feet(min_size_mm)
    if max_u - min_u < floor:
        center = (min_u + max_u) / 2.0
        min_u, max_u = center - floor / 2.0, center + floor / 2.0
    if max_v - min_v < floor:
        center = (min_v + max_v) / 2.0
        min_v, max_v = center - floor / 2.0, center + floor / 2.0

    return (min_u, min_v, max_u, max_v)


def clamp_to_sheet(rect_ft, sheet_outline_ft):
    """把矩形夾回圖紙範圍內。

    差異區域外擴後可能超出圖框邊界。雲畫在圖紙外不會報錯，但會變成看不見的
    幽靈元素，之後掃描釋疑時還會被算進去——所以在這裡夾掉。
    """
    min_u, min_v, max_u, max_v = [float(v) for v in rect_ft]
    s_min_u, s_min_v, s_max_u, s_max_v = [float(v) for v in sheet_outline_ft]
    return (max(min_u, s_min_u), max(min_v, s_min_v),
            min(max_u, s_max_u), min(max_v, s_max_v))


def normalize_sheet_key(value):
    """圖號比對用的正規化 key：去空白、轉大寫。

    刻意**不**移除 ``-`` 與 ``_``——``A-101`` 與 ``A101`` 在很多案子裡
    是兩張不同的圖。寬鬆比對留給 :func:`pair_sheets` 的第二輪，
    而且只在第一輪配不到時才啟用。
    """
    if value is None:
        return u''
    return u' '.join(u'{}'.format(value).split()).upper()


def loose_sheet_key(value):
    """第二輪用的寬鬆 key：連分隔符號也拿掉。"""
    key = normalize_sheet_key(value)
    for char in (u'-', u'_', u' ', u'.'):
        key = key.replace(char, u'')
    return key


def _sheet_value_variants(value):
    """回傳一個圖號的安全比對變體。

    有些事務所把專案代碼接在 ``DWG NO.`` 前面，例如 PDF 讀到
    ``0721B-ARD-D02001``，而 Revit 圖框的自訂欄位只存
    ``ARD-D02001``。只在「第一段含數字、且至少有三段」時去掉第一段，
    避免把一般的 ``A-101``／``A-101-1`` 任意截短後誤配。
    """
    key = normalize_sheet_key(value)
    if not key:
        return []

    variants = [key]
    parts = key.split(u'-')
    if len(parts) >= 3 and any(char.isdigit() for char in parts[0]):
        suffix = u'-'.join(parts[1:])
        if suffix and suffix not in variants:
            variants.append(suffix)
    return variants


def _sheet_field_values(sheet, field):
    """取出一張 Revit 圖紙某個配對欄位的所有候選值。"""
    values = []
    primary = sheet.get(field)
    if primary:
        values.append(primary)
    candidates = sheet.get(field + 'Candidates') or []
    for value in candidates:
        if value and value not in values:
            values.append(value)
    return values


def _sheet_index(sheet_records, field, loose=False):
    index = {}
    for sheet in sheet_records:
        for value in _sheet_field_values(sheet, field):
            variants = _sheet_value_variants(value)
            for variant in variants:
                key = loose_sheet_key(variant) if loose else variant
                if not key:
                    continue
                index.setdefault(key, []).append(sheet)
    return index


def _take_by_value(index, value, used, loose=False):
    """用一個 PDF 圖號的全部變體取一張尚未使用的圖紙。"""
    for variant in _sheet_value_variants(value):
        key = loose_sheet_key(variant) if loose else variant
        picked = _take_unused(index.get(key), used)
        if picked is not None:
            return picked
    return None


def pair_sheets(page_records, sheet_records):
    """把 PDF 頁配到 Revit 圖紙，回傳 ``(matched, unmatched_pages, unused_sheets)``。

    ``page_records``  ``[{'sheetNumber': ..., ...}]``（worker 的輸出）
    ``sheet_records`` ``[{'SheetNumber': ..., 'SheetName': ..., ...}]``

    兩輪比對：先用圖框／圖紙上的 ``DWG NO.`` 嚴格配對，再退回 Revit
    ``SheetNumber``；配不到的才用寬鬆 key 再試一次。
    順序不能顛倒——寬鬆比對會把 ``A-101`` 配到 ``A101``，那在某些案子裡
    是錯的，所以只當作最後手段，且結果要標 ``loose`` 讓 UI 提醒使用者確認。

    三類全部回傳。配不到的頁不是要丟掉，是要讓使用者手動指定。
    """
    by_dwg_strict = _sheet_index(sheet_records, 'DwgNumber')
    by_sheet_strict = _sheet_index(sheet_records, 'SheetNumber')
    by_dwg_loose = _sheet_index(sheet_records, 'DwgNumber', loose=True)
    by_sheet_loose = _sheet_index(sheet_records, 'SheetNumber', loose=True)

    used = set()
    matched = []
    pending = []

    for page in page_records:
        number = page.get('sheetNumber')
        if not normalize_sheet_key(number):
            pending.append(page)
            continue
        picked = _take_by_value(by_dwg_strict, number, used)
        if picked is not None:
            matched.append({'page': page, 'sheet': picked, 'match': 'exact',
                            'matchField': 'DwgNumber'})
            continue
        picked = _take_by_value(by_sheet_strict, number, used)
        if picked is None:
            pending.append(page)
        else:
            matched.append({'page': page, 'sheet': picked, 'match': 'exact',
                            'matchField': 'SheetNumber'})

    still_pending = []
    for page in pending:
        number = page.get('sheetNumber')
        picked = _take_by_value(by_dwg_loose, number, used, loose=True)
        match_field = 'DwgNumber'
        if picked is None:
            picked = _take_by_value(by_sheet_loose, number, used, loose=True)
            match_field = 'SheetNumber'
        if picked is None:
            still_pending.append(page)
        else:
            matched.append({'page': page, 'sheet': picked, 'match': 'loose',
                            'matchField': match_field})

    # 第三輪：只有 PDF 完全讀不到圖號時，才用圖名再試一次。
    # 如果 PDF 已經有圖號但 Revit 端沒有對應，不能拿圖名把它靜默配到
    # A2-01 之類的第一張同名圖紙；那正是「圈錯圖」的高風險來源。
    # 圖名比圖號容易撞名，所以即使使用也標成 name 讓 UI 提醒確認。
    by_name = {}
    for sheet in sheet_records:
        by_name.setdefault(normalize_sheet_key(sheet.get('SheetName')),
                           []).append(sheet)

    unmatched = []
    for page in still_pending:
        if normalize_sheet_key(page.get('sheetNumber')):
            unmatched.append(page)
            continue
        key = normalize_sheet_key(page.get('sheetName'))
        picked = _take_unused(by_name.get(key), used) if key else None
        if picked is None:
            unmatched.append(page)
        else:
            matched.append({'page': page, 'sheet': picked, 'match': 'name',
                            'matchField': 'SheetName'})

    unused = [s for s in sheet_records if id(s) not in used]
    return (matched, unmatched, unused)


def _take_unused(bucket, used):
    for sheet in bucket or []:
        if id(sheet) not in used:
            used.add(id(sheet))
            return sheet
    return None


def format_fraction_percent(value, places=2):
    """把 0~1 的比例格式化成百分比字串。

    **這個函式存在的唯一理由是 IronPython 2.7 的一個地雷。**

    ``'{:.2f}'.format(0)`` 在 CPython 回傳 ``'0.00'``，在 IronPython 2.7 會丟
    ``ValueError: Precision not allowed in integer format specifier``——精度
    格式對 int 是非法的。而最自然的寫法 ``(d.get('x') or 0) * 100`` 剛好會製造
    出 int：``0.0`` 是 falsy，``or 0`` 回傳的是**整數** 0，乘 100 還是整數。

    實測就是這樣炸的：面積 0.72%、0.16%、0.02%、0.01% 的區域都畫得出來，
    第一個 0.00% 的區域讓整個視窗掛掉。CPython 的 pytest 完全測不到，因為
    CPython 根本不會丟這個錯——所以格式化統一收在這裡，並用型別而非輸出
    來斷言（見對應測試）。
    """
    number = float(value if value is not None else 0.0)
    if places == 2:
        return u'{:.2f}%'.format(number * 100)
    if places == 1:
        return u'{:.1f}%'.format(number * 100)
    return u'{:.0f}%'.format(number * 100)


def describe_region(region):
    """把一個差異區域寫成一行給人看的定位字串，寫進雲形的 Comments。

    優先用 ``text-change`` 的前後值——``CH=300 → CH=320`` 是使用者真正想看的
    內容。沒有文字變更時退回計數描述，至少講清楚是文字還是線條在變。

    這個字串之後會被既有的 ``scan_revision_clouds`` 讀出來放進釋疑 Excel，
    所以要能獨立閱讀，不能依賴 UI 的上下文。
    """
    label = region.get('gridLabel') or u'?'
    samples = region.get('samples') or []
    for sample in samples:
        if sample.get('kind') == 'text-change':
            return u'[{}] {} → {}'.format(
                label, sample.get('before'), sample.get('after'))
    for sample in samples:
        if sample.get('kind') == 'text-add':
            return u'[{}] 新增文字：{}'.format(label, sample.get('after'))
        if sample.get('kind') == 'text-delete':
            return u'[{}] 刪除文字：{}'.format(label, sample.get('before'))

    text_count = region.get('textCount') or 0
    geom_count = region.get('geomCount') or 0
    return u'[{}] 圖面差異：文字 {} 處、線條 {} 處'.format(
        label, text_count, geom_count)


def _compact_sample_priority(sample):
    """讓備註優先顯示設計內容，不被孤立尺寸數字蓋掉。"""
    kind = sample.get('kind') or u''
    values = [sample.get('before'), sample.get('after')]
    text = u' '.join(u'{}'.format(value or u'') for value in values)
    if any(0x3400 <= ord(char) <= 0x9fff for char in text):
        return 0
    if re.search(r'[A-Za-z]', text) and re.search(r'\d', text):
        return 1
    if kind == 'text-change' and not re.match(
            r'^\s*[-+]?\d+(?:\.\d+)?\s*(?:→|$)', text):
        return 2
    if re.match(r'^\s*\d{1,2}\s*[-–—~～]\s*\d{1,2}\s*$', text):
        return 3
    if re.match(r'^\s*[-+]?\d+(?:\.\d+)?\s*$', text):
        return 4
    if kind.startswith('text'):
        return 5
    return 9


def describe_compact_region(region):
    """回傳適合 Revit Comments 的重點式差異摘要。

    同一框內若同時有尺寸與設備名稱，優先留下設備／識別碼；備註仍只取
    一個重點，不把整頁差異清單塞進 Revit Comments。
    """
    label = region.get('gridLabel') or u'?'
    samples = sorted(
        enumerate(region.get('samples') or []),
        key=lambda pair: (_compact_sample_priority(pair[1]), pair[0]))
    samples = [sample for _, sample in samples]
    for sample in samples:
        kind = sample.get('kind')
        if kind == 'text-change':
            return u'{}｜修改：{} → {}'.format(
                label, sample.get('before'), sample.get('after'))
        if kind == 'text-add':
            return u'{}｜新增：{}'.format(label, sample.get('after'))
        if kind == 'text-delete':
            return u'{}｜刪除：{}'.format(label, sample.get('before'))

    text_count = region.get('textCount') or 0
    geom_count = region.get('geomCount') or 0
    return u'{}｜文字 {}｜線條 {}'.format(label, text_count, geom_count)


def describe_cloud_comment(region, page, sheet, prefix=AUTO_COMMENT_PREFIX):
    """組出寫入 Revit Comments 的精簡定位字串。

    ``describe_region`` 保留給既有報告與測試；雲形備註只保留「自動標記、
    格位、變更重點」，圖號／圖名不重複塞進每一朵雲。
    """
    detail = describe_compact_region(region)
    if not prefix:
        return detail
    return u'{} {}'.format(prefix, detail)


def build_cloud_requests(pairings, options=None):
    """組出 C# ``create_revision_clouds_on_sheets`` 要的 clouds 陣列。

    ``pairings`` 是 :func:`pair_sheets` 的 matched，外加 UI 的勾選狀態：
    ``[{'page': ..., 'sheet': ..., 'regions': [...]}]``

    回傳 ``(clouds, skipped)``。**跳過的一定要回傳原因**——靜默少畫幾朵雲
    是這種工具最惡劣的失敗方式，使用者會以為那些地方沒有差異。
    """
    options = options or {}
    padding = float(options.get('paddingMm', DEFAULT_PADDING_MM))
    min_size = float(options.get('minSizeMm', DEFAULT_MIN_SIZE_MM))
    aspect_tol = float(options.get('aspectTolerance', DEFAULT_ASPECT_TOLERANCE))
    reference_cloud_id = options.get('referenceCloudId')
    comment_prefix = options.get('autoCommentPrefix', AUTO_COMMENT_PREFIX)

    clouds = []
    skipped = []

    for pairing in pairings:
        page = pairing.get('page') or {}
        sheet = pairing.get('sheet') or {}
        outline = sheet.get('Outline')
        number = sheet.get('SheetNumber')
        page_size = (page.get('pageWidthPt'), page.get('pageHeightPt'))

        if not outline:
            skipped.append({'sheetNumber': number,
                            'reason': u'圖紙沒有 Outline，無法換算座標'})
            continue

        ok, message = check_aspect_match(page_size, outline, aspect_tol)
        aspect_warning = None if ok else message

        for region in pairing.get('regions') or []:
            mapped = map_pdf_bbox_to_sheet(region.get('bbox'), page_size,
                                           outline)
            if mapped is None:
                skipped.append({
                    'sheetNumber': number,
                    'gridLabel': region.get('gridLabel'),
                    'reason': u'頁面尺寸無效，無法換算座標'})
                continue
            rect = clamp_to_sheet(
                build_cloud_rect(mapped, padding, min_size), outline)
            if rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0:
                skipped.append({
                    'sheetNumber': number,
                    'gridLabel': region.get('gridLabel'),
                    'reason': u'換算後的位置落在圖紙範圍外'})
                continue

            entry = {
                'sheetNumber': number,
                'rectFt': {'minU': rect[0], 'minV': rect[1],
                           'maxU': rect[2], 'maxV': rect[3]},
                'comment': describe_cloud_comment(
                    region, page, sheet, comment_prefix),
                'gridLabel': region.get('gridLabel'),
            }
            # ElementId 是目前文件內已選 ViewSheet 的不可混淆身分；保留
            # SheetNumber 供舊呼叫者相容，但 C# 端優先用 ID 解析，避免
            # 自訂 DWG NO. 與 Revit 內部圖號不同時落到錯的圖紙。
            if sheet.get('ElementId') is not None:
                entry['sheetId'] = sheet.get('ElementId')
            if sheet.get('DwgNumber'):
                entry['dwgNumber'] = sheet.get('DwgNumber')
            if reference_cloud_id is not None:
                # 由目前選取、已確認外觀正確的修訂雲提供迴圈方向範本。
                # C# 端會讀取該雲的 sketch curves；這裡只傳 ElementId，避免
                # 在 IronPython 端複製 Revit 幾何或自行猜測順逆時針。
                entry['referenceCloudId'] = reference_cloud_id
            if aspect_warning:
                entry['warning'] = aspect_warning
            clouds.append(entry)

    return (clouds, skipped)


def summarize(clouds, skipped, unmatched_pages=None, unused_sheets=None):
    """給確認視窗用的摘要文字。

    把「要畫幾朵」與「為什麼有些沒畫」放在同一段——使用者在按下確認之前
    就該看到全貌，而不是事後才發現少了東西。
    """
    lines = [u'將建立 {} 朵修訂雲'.format(len(clouds))]

    by_sheet = {}
    for cloud in clouds:
        by_sheet.setdefault(cloud.get('sheetNumber'), []).append(cloud)
    for number in sorted(by_sheet.keys(), key=lambda v: u'{}'.format(v)):
        entries = by_sheet[number]
        labels = u'、'.join([e.get('gridLabel') or u'?' for e in entries[:6]])
        if len(entries) > 6:
            labels += u' …'
        lines.append(u'  {}　{} 朵（{}）'.format(number, len(entries), labels))

    if skipped:
        lines.append(u'')
        lines.append(u'跳過 {} 筆：'.format(len(skipped)))
        for item in skipped[:8]:
            lines.append(u'  {} {}　{}'.format(
                item.get('sheetNumber') or u'?',
                item.get('gridLabel') or u'',
                item.get('reason')))
        if len(skipped) > 8:
            lines.append(u'  …其餘 {} 筆'.format(len(skipped) - 8))

    if unmatched_pages:
        lines.append(u'')
        lines.append(u'{} 頁 PDF 配不到 Revit 圖紙（未處理）'.format(
            len(unmatched_pages)))
    if unused_sheets:
        lines.append(u'{} 張 Revit 圖紙沒有對應的 PDF 頁'.format(
            len(unused_sheets)))

    return u'\n'.join(lines)
