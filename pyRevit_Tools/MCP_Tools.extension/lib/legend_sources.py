# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""門窗圖例的 Revit 端取數與寫入 — 依 ``domain/door-window-legend-workflow.md``.

該 domain 檔的〈設計約束〉明列三條 Revit API 事實，這個模組整個建立在上面：

1. **API 無法直接建立 Legend Component。** 唯一可靠的繞路是
   「seed → 複製 → 改 type」。反射確認 ``BuiltInParameter.LEGEND_COMPONENT``
   在 2020 與 2024 都存在——圖例元件「是哪個類型」是一個**參數**，所以複製一
   個既有元件再改這個參數，就等於放了一個新的。
2. **Legend Component 無法被 tag。** 附屬資料只能用 TextNote 呈現，
   所以「選擇列出參數」只能寫成文字。
3. **不得自動選 seed。** 由呼叫端讓人挑，這裡不代選。

另外一條不在 domain 檔但同樣硬的限制：
``UIDocument.PromptToPlaceElementTypeOnLegendView()`` 是 UI API，**不能在
Transaction 內、也不能在 modal 視窗開著的時候呼叫**。所以放置 seed 這一步一定
在視窗關閉之後、交易開始之前。
"""

from Autodesk.Revit import DB

import area_scheme_sources as sources


MM_PER_FOOT = 304.8

DOOR = 'door'
WINDOW = 'window'

CATEGORY_OF = {DOOR: 'OST_Doors', WINDOW: 'OST_Windows'}
CATEGORY_LABELS = {DOOR: u'門', WINDOW: u'窗'}


def _mm(value):
    return float(value) * MM_PER_FOOT


def _feet(value):
    return float(value) / MM_PER_FOOT


def legend_views(doc):
    """``[(label, view)]``——非樣板的圖例視圖。

    API 建不出 Legend view，所以一個都沒有時只能請人先手動建一張；
    這個模組不代建，也不代選（domain：不得自動選 seed）。
    """
    rows = []
    try:
        views = list(DB.FilteredElementCollector(doc)
                     .OfClass(DB.View)
                     .WhereElementIsNotElementType()
                     .ToElements())
    except Exception:
        return rows
    for view in views:
        try:
            if view.IsTemplate:
                continue
            if u'{}'.format(view.ViewType) != 'Legend':
                continue
        except Exception:
            continue
        rows.append((sources.element_name(view), view))
    rows.sort(key=lambda item: item[0])
    return rows


def legend_components(doc, view):
    """圖例視圖裡的圖例元件。

    每一筆帶 ``symbol_id``——它來自 ``LEGEND_COMPONENT`` 參數，也就是「這個
    元件現在顯示哪個類型」。複製之後改寫的正是這個參數。
    """
    rows = []
    category = getattr(DB.BuiltInCategory, 'OST_LegendComponents', None)
    if category is None:
        return rows
    try:
        collector = (DB.FilteredElementCollector(doc, view.Id)
                     .OfCategory(category)
                     .WhereElementIsNotElementType())
    except Exception:
        return rows
    for element in collector:
        parameter = sources.built_in_parameter(element, 'LEGEND_COMPONENT')
        symbol_id = None
        if parameter is not None:
            try:
                symbol_id = parameter.AsElementId()
            except Exception:
                symbol_id = None
        symbol = None
        if symbol_id is not None:
            try:
                symbol = doc.GetElement(symbol_id)
            except Exception:
                symbol = None
        rows.append({
            'id': sources.id_value(element.Id),
            'element_id': element.Id,
            'element': element,
            'symbol_id': symbol_id,
            'symbol_label': symbol_label(symbol) if symbol is not None else u'',
        })
    return rows


def symbol_label(symbol):
    try:
        family = symbol.Family.Name
    except Exception:
        family = u''
    name = sources.element_name(symbol)
    return u'{} : {}'.format(family, name) if family else name


def _placed_symbol_ids(doc, category):
    """已經有實例被放在模型裡的類型 id。"""
    used = set()
    try:
        collector = (DB.FilteredElementCollector(doc)
                     .OfCategory(category)
                     .WhereElementIsNotElementType())
    except Exception:
        return used
    for instance in collector:
        try:
            used.add(sources.id_value(instance.GetTypeId()))
        except Exception:
            continue
    return used


def door_window_symbols(doc, kinds=(DOOR, WINDOW), only_used=True):
    """門窗的族群類型。

    ``only_used=True`` 只回模型裡真的有放置實例的類型——一個專案常常載入了幾
    十個沒在用的族群，全部畫進圖例表只會讓看圖的人以為那些都要施作。
    """
    rows = []
    for kind in kinds or ():
        category = getattr(DB.BuiltInCategory, CATEGORY_OF.get(kind, u''), None)
        if category is None:
            continue
        used = _placed_symbol_ids(doc, category) if only_used else None
        try:
            collector = (DB.FilteredElementCollector(doc)
                         .OfCategory(category)
                         .WhereElementIsElementType())
        except Exception:
            continue
        for symbol in collector:
            value = sources.id_value(symbol.Id)
            if used is not None and value not in used:
                continue
            rows.append({
                'id': value,
                'element_id': symbol.Id,
                'element': symbol,
                'kind': kind,
                'kind_label': CATEGORY_LABELS.get(kind, u''),
                'label': u'[{}] {}'.format(CATEGORY_LABELS.get(kind, u''),
                                           symbol_label(symbol)),
                'type_mark': sources.parameter_text(
                    sources.built_in_parameter(symbol, 'ALL_MODEL_TYPE_MARK')),
            })
    rows.sort(key=lambda row: (row['kind'], row['label']))
    return rows


# 圖面上不會想印出來的內部欄位。這不是安全過濾，只是把雜訊收掉；
# 使用者仍然可以在清單裡看到並勾選其餘全部參數。
SKIP_PARAMETERS = (u'Type Name', u'類型名稱', u'Family Name', u'族群名稱')


def type_parameters(symbol):
    """``(names, values)``——這個類型上可讀的參數。

    值取 ``AsValueString()`` 優先，因為那是**帶單位、照專案設定格式化過**的
    字串，跟使用者在屬性面板看到的一致；直接取內部值會印出英尺與未四捨五入
    的小數。
    """
    names = []
    values = {}
    try:
        parameters = list(symbol.Parameters)
    except Exception:
        return names, values
    for parameter in parameters:
        try:
            name = parameter.Definition.Name
        except Exception:
            continue
        if not name or name in SKIP_PARAMETERS or name in values:
            continue
        text = u''
        try:
            text = parameter.AsValueString() or u''
        except Exception:
            text = u''
        if not text:
            try:
                text = parameter.AsString() or u''
            except Exception:
                text = u''
        names.append(name)
        values[name] = text
    return names, values


def symbol_records(symbols):
    """把類型變成 ``legend_layout_logic`` 要的記錄。"""
    records = []
    for row in symbols or []:
        names, values = type_parameters(row['element'])
        record = dict(row)
        record['parameters'] = names
        record['values'] = values
        records.append(record)
    return records


def text_note_types(doc):
    """``[(label, type_id)]``——可用的文字類型。"""
    rows = []
    try:
        collector = (DB.FilteredElementCollector(doc)
                     .OfClass(DB.TextNoteType)
                     .WhereElementIsElementType())
    except Exception:
        return rows
    for note_type in collector:
        rows.append((sources.element_name(note_type), note_type.Id))
    rows.sort(key=lambda item: item[0])
    return rows


def default_text_note_type(doc):
    try:
        return doc.GetDefaultElementTypeId(DB.ElementTypeGroup.TextNoteType)
    except Exception:
        return None


def prompt_place_seed(uidoc, symbol):
    """請使用者在圖例視圖裡點一下放置第一個元件，回傳新元件或 ``None``.

    **不能在 Transaction 內呼叫**，也不能在 modal 視窗開著時呼叫。
    新元件靠「呼叫前後的 id 差集」找出來——這個 API 回傳 ``Void``，
    沒有別的辦法知道使用者放了什麼、或有沒有按 Esc 取消。
    """
    doc = uidoc.Document
    view = doc.ActiveView
    before = set(row['id'] for row in legend_components(doc, view))
    try:
        uidoc.PromptToPlaceElementTypeOnLegendView(symbol)
    except Exception:
        return None
    after = legend_components(doc, view)
    for row in after:
        if row['id'] not in before:
            return row
    return None


def bounding_box_mm(element, view):
    """``(min_x, min_y, width, height)`` 毫米，量不到回 ``None``。"""
    try:
        box = element.get_BoundingBox(view)
    except Exception:
        box = None
    if box is None:
        return None
    try:
        return (_mm(box.Min.X), _mm(box.Min.Y),
                _mm(box.Max.X - box.Min.X), _mm(box.Max.Y - box.Min.Y))
    except Exception:
        return None


def copy_and_retarget(doc, seed_element_id, symbol_id):
    """複製一個圖例元件並把它改成別的類型。回傳新元件 id 或 ``None``。

    位移給 0：真正的位置在稍後的排版一次算完，這裡先原地疊著。

    顯示方向（``LEGEND_COMPONENT_VIEW``：平面／立面／剖面）與細緻度會**跟著
    seed 一起被複製過來**，所以這個工具不去設定它們——想要立面圖例，就把 seed
    設成立面。Revit 沒有公開列舉那個參數合法值的 API，硬寫一份對照表只會在
    某個版本悄悄對不上。
    """
    try:
        copied = DB.ElementTransformUtils.CopyElement(
            doc, seed_element_id, DB.XYZ(0, 0, 0))
    except Exception:
        return None, u'copy'
    new_id = None
    for value in copied or []:
        new_id = value
        break
    if new_id is None:
        return None, u'copy'
    element = doc.GetElement(new_id)
    parameter = sources.built_in_parameter(element, 'LEGEND_COMPONENT')
    if parameter is None:
        return new_id, u'retarget'
    try:
        parameter.Set(symbol_id)
    except Exception:
        return new_id, u'retarget'
    return new_id, u''


def create_note(doc, view, x_mm, y_mm, text, type_id):
    """在圖例視圖裡建立一則文字。空字串不建立。"""
    if not text:
        return None
    try:
        point = DB.XYZ(_feet(x_mm), _feet(y_mm), 0.0)
        note = DB.TextNote.Create(doc, view.Id, point, text, type_id)
        return note.Id
    except Exception:
        return None


def move_element(doc, element_id, dx_mm, dy_mm):
    if abs(dx_mm) < 1e-9 and abs(dy_mm) < 1e-9:
        return True
    try:
        DB.ElementTransformUtils.MoveElement(
            doc, element_id, DB.XYZ(_feet(dx_mm), _feet(dy_mm), 0.0))
        return True
    except Exception:
        return False
