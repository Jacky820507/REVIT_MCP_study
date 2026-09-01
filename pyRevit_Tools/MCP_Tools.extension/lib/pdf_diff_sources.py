# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""PDF 差異比對的 Revit 端取數 — 只讀，不寫。

寫入一律走 ``mcp_bridge`` 呼叫 C# 的 ``create_revision_clouds_on_sheets``：
建立雲形要開 Transaction，而 Transaction 的正確寫法已經在 C# 那邊了，
在這裡再寫一份只會多一個會漂移的副本。

每個讀取都個別包 try/except——一張圖紙的 ``Outline`` 取不到（極少見，但
壞掉的圖框會）不該讓整批圖紙都撈不出來。這是 ``legend_sources.py`` 已經
建立的慣例。
"""

from Autodesk.Revit import DB


# Title block／Sheet 上常見的「DWG NO.」參數名稱。這裡只做欄位名稱判斷，
# 不把 Revit 內建的 SheetNumber 誤當成 PDF 圖框上的 DWG NO.。
_DWG_NUMBER_LABELS = frozenset([
    u'DWGNO', u'DRAWINGNO', u'DRAWINGNUMBER',
    u'圖號', u'圖面編號', u'圖說編號', u'圖紙編號'])


def _parameter_label_key(value):
    """把 Revit 參數名稱化成可比對的欄位 key。"""
    text = u'{}'.format(value or u'').upper()
    for char in (u' ', u'\t', u'.', u':', u'：', u'_', u'-', u'/', u'\\',
                 u'(', u')', u'[', u']'):
        text = text.replace(char, u'')
    return text


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


def _dwg_values_from_element(element):
    values = []
    try:
        parameters = list(element.Parameters)
    except Exception:
        return values

    for parameter in parameters:
        try:
            name = parameter.Definition.Name
        except Exception:
            continue
        if not _is_dwg_number_parameter(name):
            continue
        value = _parameter_text(parameter)
        if value and value not in values:
            values.append(value)
    return values


def _sheet_dwg_number_values(doc, sheet):
    """讀 Sheet／圖框 instance／圖框 type 上的 DWG NO. 自訂欄位。

    同一個專案可能把欄位綁在 Sheets，也可能綁在 Title Block；三個位置
    都讀，但不把第一個空值當成答案。回傳所有不重複值，供配對與 UI 顯示。
    """
    elements = [sheet]
    try:
        title_blocks = list(DB.FilteredElementCollector(doc, sheet.Id)
                            .OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
                            .WhereElementIsNotElementType()
                            .ToElements())
    except Exception:
        title_blocks = []

    for title_block in title_blocks:
        elements.append(title_block)
        try:
            type_id = title_block.GetTypeId()
            if type_id and type_id != DB.ElementId.InvalidElementId:
                title_block_type = doc.GetElement(type_id)
                if title_block_type is not None:
                    elements.append(title_block_type)
        except Exception:
            pass

    values = []
    for element in elements:
        for value in _dwg_values_from_element(element):
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


def sheet_records(doc):
    """回傳全專案圖紙，含紙面座標範圍。

    ``Outline`` 是 ``BoundingBoxUV``（單位 feet），``pdf_diff_logic`` 的
    座標換算就靠它。取不到 Outline 的圖紙仍然回傳（Outline 為 None），
    由下游明確報「這張圖紙沒有 Outline」而不是憑空消失。
    """
    rows = []
    try:
        sheets = list(DB.FilteredElementCollector(doc)
                      .OfClass(DB.ViewSheet)
                      .WhereElementIsNotElementType()
                      .ToElements())
    except Exception:
        return rows

    for sheet in sheets:
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

        dwg_candidates = _sheet_dwg_number_values(doc, sheet)

        rows.append({
            'SheetNumber': number,
            'SheetName': element_name(sheet),
            'DwgNumber': dwg_candidates[0] if dwg_candidates else None,
            'DwgNumberCandidates': dwg_candidates,
            'Outline': outline,
            'ElementId': _id_value(sheet.Id),
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
    FamilySymbol，不是 ``Revision`` 本身。只列出已載入專案的類型；這樣
    C# 端可以用同一個 symbol id 建立 IndependentTag，而不會誤用一般的
    多類別標籤。
    """
    rows = []
    try:
        tag_category_id = _id_value(DB.ElementId(
            DB.BuiltInCategory.OST_RevisionCloudTags))
        symbols = list(DB.FilteredElementCollector(doc)
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


def _id_value(element_id):
    """跨版本取 ElementId 的整數值。

    Revit 2024 起 ``IntegerValue`` 被 ``Value`` 取代（2025 改成 Int64）。
    本 repo 主力是 2020，但這個 lib 可能跟著較新的 Revit 跑，所以兩條都試。
    """
    try:
        return element_id.IntegerValue
    except Exception:
        try:
            return element_id.Value
        except Exception:
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
