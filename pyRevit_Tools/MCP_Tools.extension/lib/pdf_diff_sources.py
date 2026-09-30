# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""PDF 差異比對的 Revit 端取數 — 只讀，不寫。

寫入一律走 ``mcp_bridge`` 呼叫 C# 的 ``create_revision_clouds_on_sheets``：
建立雲形要開 Transaction，而 Transaction 的正確寫法已經在 C# 那邊了，
在這裡再寫一份只會多一個會漂移的副本。

每個讀取都個別包 try/except——一張圖紙的 ``Outline`` 取不到（極少見，但
壞掉的圖框會）不該讓整批圖紙都撈不出來。這是 ``legend_sources.py`` 已經
建立的慣例。

## 大型專案的成本模型（2026-09-02）

這一層被兩顆按鈕在「按下去的第一秒」同步呼叫，所以它的複雜度就是使用者
感受到的等待時間。三個原本會隨專案規模爆掉的地方已經改掉，不要退回去：

1. **圖框不要每張圖紙開一個 collector。** 舊寫法是
   ``FilteredElementCollector(doc, sheet.Id)``，1000 張圖紙就是 1000 個
   view-scoped collector。改成整份文件掃一次再依 ``OwnerViewId`` 分組。
2. **``element.Parameters`` 每種元素只走訪一次。** 讀 ``Definition.Name``
   要跨 API 邊界，一張圖紙連圖框加起來上百個參數；但同一種元素的參數定義
   是固定的，所以只探勘一次名稱，之後用 ``LookupParameter`` 直接取值。
3. **``_id_value`` 的存取器只解析一次。** ``ElementId.Value`` 是 Revit 2024
   才有的；在 2020–2023 上，每呼叫一次「先試 Value 再退回 IntegerValue」
   就丟一次 AttributeError，而這支函式在大案子裡會被呼叫幾十萬次。
"""

from Autodesk.Revit import DB


class ScanCancelled(Exception):
    """使用者在掃描途中按了取消。

    掃描跑在 Revit 的 UI 執行緒上，沒有辦法背景化。能做的是讓它**可以被
    中斷**——呼叫端傳進來的 ``progress`` 回傳真值就丟這個例外，讓使用者在
    大案子裡不必眼睜睜等到底或去砍掉 Revit。
    """


# Title block／Sheet 上常見的「DWG NO.」參數名稱。這裡只做欄位名稱判斷，
# 不把 Revit 內建的 SheetNumber 誤當成 PDF 圖框上的 DWG NO.。
_DWG_NUMBER_LABELS = frozenset([
    u'DWGNO', u'DRAWINGNO', u'DRAWINGNUMBER',
    u'圖號', u'圖面編號', u'圖說編號', u'圖紙編號'])

_LABEL_KEY_STRIP = (u' ', u'\t', u'.', u':', u'：', u'_', u'-', u'/', u'\\',
                    u'(', u')', u'[', u']')

# 參數名稱 -> 正規化 key。整份專案的參數名稱只有幾十種，但會被問幾十萬次。
_LABEL_KEY_CACHE = {}


def _parameter_label_key(value):
    """把 Revit 參數名稱化成可比對的欄位 key。"""
    text = u'{}'.format(value or u'')
    cached = _LABEL_KEY_CACHE.get(text)
    if cached is not None:
        return cached
    key = text.upper()
    for char in _LABEL_KEY_STRIP:
        key = key.replace(char, u'')
    _LABEL_KEY_CACHE[text] = key
    return key


def _is_dwg_number_parameter(value):
    key = _parameter_label_key(value)
    return key in _DWG_NUMBER_LABELS or ('DWG' in key and 'NO' in key)


def _parameter_text(parameter):
    """讀文字參數；AsValueString 是沒有 AsString 時的跨型別備援。"""
    value = None
    try:
        value = parameter.AsString()
    except Exception:
        pass
    if value is None or not u'{}'.format(value).strip():
        try:
            value = parameter.AsValueString()
        except Exception:
            value = None
    if value is None:
        return None
    text = u'{}'.format(value).strip()
    return text or None


def _dwg_parameter_names(element):
    """列出這個元素上看起來像「DWG NO.」的參數名稱。

    這是唯一需要走訪 ``element.Parameters`` 的地方，也是這一層最貴的操作。
    呼叫端只對每一「種」元素做一次，見 :func:`_cached_dwg_values`。
    """
    names = []
    try:
        parameters = element.Parameters
    except Exception:
        return names

    for parameter in parameters:
        try:
            name = parameter.Definition.Name
        except Exception:
            continue
        if _is_dwg_number_parameter(name) and name not in names:
            names.append(name)
    return names


def _values_by_names(element, names):
    """用已知的參數名稱直接取值，不再走訪整份參數表。

    同一個元素上有兩個同名參數時（極少見）``LookupParameter`` 只會回第一個。
    為了那個邊界情況讓每張圖紙都全表掃描不划算，所以接受這個取捨。
    """
    values = []
    for name in names:
        try:
            parameter = element.LookupParameter(name)
        except Exception:
            parameter = None
        if parameter is None:
            continue
        value = _parameter_text(parameter)
        if value and value not in values:
            values.append(value)
    return values


def _cached_dwg_values(element, cache, names_key):
    """取單一元素的 DWG 值；參數名稱依 ``names_key`` 只探勘一次。

    ``names_key`` 要對應「參數定義相同」的一群元素：所有 ViewSheet 是一群
    （專案參數綁在 Sheets 類別上，每張圖紙都有同一組定義），每個圖框類型
    各自一群（instance 參數由族群決定）。
    """
    names = cache.get(names_key)
    if names is None:
        names = _dwg_parameter_names(element)
        cache[names_key] = names
    if not names:
        return []
    return _values_by_names(element, names)


def title_blocks_by_sheet(doc, sheet_ids=None):
    """一次撈全專案圖框並依所屬圖紙分組，回傳 ``{sheet_id: [圖框, ...]}``。

    給 ``sheet_ids`` 時只保留這些圖紙的圖框；``None`` 代表全收。
    """
    result = {}
    try:
        blocks = DB.FilteredElementCollector(doc) \
            .OfCategory(DB.BuiltInCategory.OST_TitleBlocks) \
            .WhereElementIsNotElementType() \
            .ToElements()
    except Exception:
        return result

    for block in blocks:
        try:
            owner_id = _id_value(block.OwnerViewId)
        except Exception:
            continue
        if owner_id <= 0:
            continue
        if sheet_ids is not None and owner_id not in sheet_ids:
            continue
        result.setdefault(owner_id, []).append(block)
    return result


def _sheet_dwg_number_values(doc, sheet, title_blocks, cache):
    """讀 Sheet／圖框 instance／圖框 type 上的 DWG NO. 自訂欄位。

    同一個專案可能把欄位綁在 Sheets，也可能綁在 Title Block；三個位置
    都讀，但不把第一個空值當成答案。回傳所有不重複值，供配對與 UI 顯示。

    圖框 type 的參數值整個類型共用，所以連「值」都快取——一個 1000 張圖紙
    的案子通常只有兩三種圖框類型。
    """
    values = []
    for value in _cached_dwg_values(sheet, cache, ('sheet',)):
        if value not in values:
            values.append(value)

    for title_block in title_blocks:
        type_id = None
        try:
            raw_type_id = title_block.GetTypeId()
            if raw_type_id and raw_type_id != DB.ElementId.InvalidElementId:
                type_id = _id_value(raw_type_id)
        except Exception:
            type_id = None

        for value in _cached_dwg_values(title_block,
                                        cache, ('title_block', type_id)):
            if value not in values:
                values.append(value)

        if type_id is None:
            continue
        type_values_key = ('title_block_type_values', type_id)
        type_values = cache.get(type_values_key)
        if type_values is None:
            title_block_type = None
            try:
                title_block_type = doc.GetElement(title_block.GetTypeId())
            except Exception:
                title_block_type = None
            if title_block_type is None:
                type_values = []
            else:
                type_values = _cached_dwg_values(
                    title_block_type, cache, ('title_block_type', type_id))
            cache[type_values_key] = type_values
        for value in type_values:
            if value not in values:
                values.append(value)
    return values


def element_name(element):
    """跨版本取名稱。

    ``Element.Name`` 在 Revit 2020 是屬性、在較新版本某些型別上行為不同，
    所以包一層。取不到名字不是致命錯誤，回空字串讓上層繼續。
    """
    try:
        return element.Name
    except Exception:
        try:
            return DB.Element.Name.__get__(element)
        except Exception:
            return u''


def all_sheet_ids(doc):
    """回傳全專案（非樣板）圖紙的 ElementId 整數值集合。

    只讀 Id，不碰參數，所以即使幾千張圖紙也很快。給「先確認哪些圖紙有雲，
    再只為那幾張做昂貴的欄位掃描」這種流程用。
    """
    result = set()
    try:
        sheets = DB.FilteredElementCollector(doc) \
            .OfClass(DB.ViewSheet) \
            .WhereElementIsNotElementType() \
            .ToElements()
    except Exception:
        return result

    for sheet in sheets:
        try:
            if sheet.IsTemplate:
                continue
        except Exception:
            pass
        value = _id_value(sheet.Id)
        if value > 0:
            result.add(value)
    return result


def revision_clouds_by_owner(doc):
    """一次掃完全案子的修訂雲，回傳 ``{OwnerViewId 整數值: [雲, ...]}``。

    這裡不判斷哪個 owner 是圖紙——「只處理直接畫在圖紙上的雲」是按鈕的
    政策，不是資料來源的政策。
    """
    result = {}
    try:
        clouds = DB.FilteredElementCollector(doc) \
            .OfClass(DB.RevisionCloud) \
            .WhereElementIsNotElementType() \
            .ToElements()
    except Exception:
        return result

    for cloud in clouds:
        try:
            owner_id = _id_value(cloud.OwnerViewId)
        except Exception:
            continue
        result.setdefault(owner_id, []).append(cloud)
    return result


def fill_dwg_numbers(doc, rows, progress=None):
    """替既有的 rows 補上 DWG NO. 欄位（就地修改），回傳同一份 rows。

    這是刻意跟 :func:`sheet_records` 分開的第二階段。讀 DWG NO. 要為每張
    圖紙查參數、還要連圖框一起查，是這一層唯一昂貴的操作；而它**只有在
    用 Revit 圖紙編號配不到 PDF 頁時才需要**。先便宜地把圖紙撈出來、配一次，
    配不到再回頭補圖號，比一開始就全掃便宜得多——尤其在圖號本來就對得上的
    專案，這一段永遠不會被執行。
    """
    if not rows:
        return rows

    wanted = set()
    for row in rows:
        try:
            wanted.add(int(row.get('ElementId')))
        except Exception:
            continue

    blocks_by_sheet = title_blocks_by_sheet(doc, wanted)
    cache = {}
    total = len(rows)
    done = 0

    for row in rows:
        done += 1
        if progress is not None and progress(done, total):
            raise ScanCancelled()

        try:
            sheet_id = int(row.get('ElementId'))
            sheet = doc.GetElement(DB.ElementId(sheet_id))
        except Exception:
            continue
        if sheet is None:
            continue

        candidates = _sheet_dwg_number_values(
            doc, sheet, blocks_by_sheet.get(sheet_id) or [], cache)
        row['DwgNumberCandidates'] = candidates
        row['DwgNumber'] = candidates[0] if candidates else None
    return rows


def sheet_records(doc, sheet_ids=None, progress=None, with_dwg=True):
    """回傳圖紙資料，含紙面座標範圍。

    ``Outline`` 是 ``BoundingBoxUV``（單位 feet），``pdf_diff_logic`` 的
    座標換算就靠它。取不到 Outline 的圖紙仍然回傳（Outline 為 None），
    由下游明確報「這張圖紙沒有 Outline」而不是憑空消失。

    ``sheet_ids`` 給只關心少數圖紙的呼叫端（例如「放置修訂雲標籤」只在意
    真的有雲的那幾張）。DWG NO. 欄位掃描是這支函式最貴的部分，能先縮範圍
    就不要整份專案掃。``None``（預設）維持原本的全案子行為。

    ``progress`` 是 ``callable(done, total)``，每張圖紙呼叫一次；回傳真值
    代表使用者要取消，會丟出 :class:`ScanCancelled`。這不只是為了好看：
    這段跑在 Revit 的 UI 執行緒上，呼叫端**必須**利用這個回呼去抽動訊息
    幫浦，否則進度視窗會變成畫不出來也按不動的幽靈視窗，Revit 會被判定
    「沒有回應」。節流由呼叫端決定——這裡每張都通知，不自作主張。

    ``with_dwg=False`` 跳過 DWG NO. 欄位掃描（``DwgNumber`` 為 ``None``）。
    那是這一層唯一昂貴的部分，而且只有在圖紙編號配不到 PDF 頁時才需要，
    所以呼叫端可以先便宜地撈一輪，需要時再用 :func:`fill_dwg_numbers` 補。
    """
    rows = []
    wanted = None
    if sheet_ids is not None:
        wanted = set()
        for sheet_id in sheet_ids:
            try:
                wanted.add(int(sheet_id))
            except Exception:
                continue
        if not wanted:
            return rows

    if wanted is None:
        try:
            sheets = list(DB.FilteredElementCollector(doc)
                          .OfClass(DB.ViewSheet)
                          .WhereElementIsNotElementType()
                          .ToElements())
        except Exception:
            return rows
    else:
        # 已經知道要哪幾張就直接取，不要撈全部再篩。
        #
        # 「放置修訂雲標籤」通常只在意幾十張有雲的圖紙，但舊寫法仍然列舉
        # 全案子的 ViewSheet 再於迴圈內 continue 掉——538 張的專案就是走訪
        # 538 次、進度條也數到 538，而真正要處理的只有 20 張。使用者看到的
        # 等待時間跟他選的範圍完全脫鉤。
        sheets = []
        for sheet_id in wanted:
            try:
                element = doc.GetElement(DB.ElementId(int(sheet_id)))
            except Exception:
                element = None
            if isinstance(element, DB.ViewSheet):
                sheets.append(element)

    blocks_by_sheet = title_blocks_by_sheet(doc, wanted) if with_dwg else {}
    cache = {}
    total = len(sheets)
    done = 0

    for sheet in sheets:
        done += 1
        if progress is not None and progress(done, total):
            raise ScanCancelled()

        sheet_id = _id_value(sheet.Id)
        if wanted is not None and sheet_id not in wanted:
            continue

        try:
            if sheet.IsTemplate:
                continue
        except Exception:
            pass

        outline = None
        try:
            box = sheet.Outline
            outline = (box.Min.U, box.Min.V, box.Max.U, box.Max.V)
        except Exception:
            outline = None

        try:
            number = sheet.SheetNumber
        except Exception:
            continue

        dwg_candidates = _sheet_dwg_number_values(
            doc, sheet, blocks_by_sheet.get(sheet_id) or [], cache) \
            if with_dwg else []

        rows.append({
            'SheetNumber': number,
            'SheetName': element_name(sheet),
            'DwgNumber': dwg_candidates[0] if dwg_candidates else None,
            'DwgNumberCandidates': dwg_candidates,
            'Outline': outline,
            'ElementId': sheet_id,
        })

    rows.sort(key=lambda row: u'{}'.format(row['SheetNumber']))
    return rows


def revision_records(doc):
    """回傳全專案修訂，供使用者選擇要把雲形掛在哪一個底下。

    空清單是正常狀態（新專案就沒有修訂）——C# 端會在需要時自己建一個，
    所以這裡不代建。
    """
    rows = []
    try:
        revisions = list(DB.FilteredElementCollector(doc)
                         .OfClass(DB.Revision)
                         .WhereElementIsNotElementType()
                         .ToElements())
    except Exception:
        return rows

    for revision in revisions:
        try:
            rows.append({
                'ElementId': _id_value(revision.Id),
                'SequenceNumber': revision.SequenceNumber,
                'Description': revision.Description or u'',
                'RevisionDate': revision.RevisionDate or u'',
            })
        except Exception:
            continue

    rows.sort(key=lambda row: row['SequenceNumber'])
    return rows


def revision_label(row):
    """修訂的下拉選單顯示文字。"""
    parts = [u'{}'.format(row.get('SequenceNumber'))]
    if row.get('Description'):
        parts.append(row['Description'])
    if row.get('RevisionDate'):
        parts.append(u'({})'.format(row['RevisionDate']))
    return u' '.join(parts)


def revision_tag_records(doc):
    """回傳已載入的修訂雲狀標籤 FamilySymbol，供 UI 選擇。

    Revit 的修訂標籤是 ``OST_RevisionCloudTags`` 類別的 annotation
    FamilySymbol，不是 ``Revision`` 本身。用 ``OfCategory`` 讓 Revit 自己
    過濾——舊寫法是撈全專案的 FamilySymbol 再逐一比對類別，大案子裡那是
    上萬個型別的無謂走訪。迴圈內的類別檢查留著當保險，成本已可忽略。
    """
    rows = []
    try:
        tag_category_id = _id_value(DB.ElementId(
            DB.BuiltInCategory.OST_RevisionCloudTags))
        symbols = list(DB.FilteredElementCollector(doc)
                       .OfCategory(DB.BuiltInCategory.OST_RevisionCloudTags)
                       .OfClass(DB.FamilySymbol)
                       .WhereElementIsElementType()
                       .ToElements())
    except Exception:
        return rows

    for symbol in symbols:
        try:
            category = symbol.Category
            if category is None or _id_value(category.Id) != tag_category_id:
                continue

            family_name = u''
            try:
                family_name = u'{}'.format(symbol.FamilyName or u'')
            except Exception:
                try:
                    family_name = element_name(symbol.Family)
                except Exception:
                    family_name = u''

            rows.append({
                'ElementId': _id_value(symbol.Id),
                'FamilyName': family_name,
                'TypeName': element_name(symbol),
            })
        except Exception:
            # 單一損壞或未完成載入的 annotation type 不應影響其他標籤。
            continue

    rows.sort(key=lambda row: (
        u'{}'.format(row.get('FamilyName') or u''),
        u'{}'.format(row.get('TypeName') or u''),
        row.get('ElementId') or 0))
    return rows


def revision_tag_label(row):
    """修訂雲狀標籤下拉選單顯示文字。"""
    family_name = row.get('FamilyName') or u'（未命名族群）'
    type_name = row.get('TypeName') or u'（未命名類型）'
    return u'{} : {} [ID {}]'.format(
        family_name, type_name, row.get('ElementId'))


# 這個 harness 上的 ElementId 用哪個屬性取整數值。解析一次就記住：
# ``Value`` 是 Revit 2024 起才有的，在 2020–2023 上每次「先試再退回」都會
# 丟一次 AttributeError，而這支函式在大案子裡會被呼叫幾十萬次。
_ID_ACCESSOR = None


def _read_id(element_id, accessor):
    if accessor == 'IntegerValue':
        return int(element_id.IntegerValue)
    return int(element_id.Value)


def _id_value(element_id):
    """跨版本取 ElementId 的整數值。

    Revit 2024 起 ``IntegerValue`` 被 ``Value`` 取代（2025 改成 Int64），
    但 ``IntegerValue`` 仍然存在，所以先試它、快取結果；哪天它真的被移除，
    快取會失效並自動改用 ``Value``。
    """
    if element_id is None:
        return 0

    global _ID_ACCESSOR
    if _ID_ACCESSOR is not None:
        try:
            return _read_id(element_id, _ID_ACCESSOR)
        except Exception:
            _ID_ACCESSOR = None

    for accessor in ('IntegerValue', 'Value'):
        try:
            value = _read_id(element_id, accessor)
        except Exception:
            continue
        _ID_ACCESSOR = accessor
        return value
    return 0


def selected_revision_cloud_id(doc, uidoc):
    """回傳目前選取的修訂雲 ElementId；沒有單一修訂雲選取時回傳 ``None``。

    PDF 差異按鈕可以用一朵使用者確認過的雲形當方向範本。這裡只讀目前
    selection，不改選取集，也不把任意繪圖元素誤當成範本。
    """
    if doc is None or uidoc is None:
        return None
    try:
        selected_ids = list(uidoc.Selection.GetElementIds())
    except Exception:
        return None

    revision_cloud_id = None
    for element_id in selected_ids:
        try:
            element = doc.GetElement(element_id)
            if isinstance(element, DB.RevisionCloud):
                if revision_cloud_id is not None:
                    # 多選時不猜方向；請使用者只選一朵範本雲。
                    return None
                revision_cloud_id = _id_value(element.Id)
        except Exception:
            continue
    return revision_cloud_id
