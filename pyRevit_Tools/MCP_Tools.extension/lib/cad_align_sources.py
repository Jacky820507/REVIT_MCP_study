# -*- coding: utf-8 -*-
from __future__ import division, unicode_literals

"""CAD 對齊網格匯入——Revit API 那一側（IronPython 2.7）。

決策全部在 ``cad_align_logic``；這裡只負責把 Revit 的東西讀成純資料、
以及把決策寫回模型。
"""

import os

import clr
from Autodesk.Revit import DB

import area_scheme_sources as area_sources
import cad_align_logic as logic


MM_PER_FOOT = 304.8

COLOR_MODES = (
    (u'黑白（底圖最常用）', 'BlackAndWhite'),
    (u'保留 CAD 顏色', 'Preserved'),
    (u'反轉顏色', 'InvertColors'),
)

MODE_IMPORT = 'import'
MODE_LINK = 'link'


def _mm(point):
    return (float(point.X) * MM_PER_FOOT, float(point.Y) * MM_PER_FOOT)


def id_value(element_id):
    return area_sources.id_value(element_id)


def plan_views(doc):
    """``[(label, view)]``，依樓層高程、名稱排序。只收平面圖（含結構平面）。"""
    kinds = set([DB.ViewType.FloorPlan])
    engineering = getattr(DB.ViewType, 'EngineeringPlan', None)
    if engineering is not None:
        kinds.add(engineering)
    rows = []
    for view in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan):
        try:
            if view.IsTemplate or view.ViewType not in kinds:
                continue
        except Exception:
            continue
        level = None
        try:
            level = view.GenLevel
        except Exception:
            level = None
        elevation = float(level.Elevation) if level is not None else 0.0
        level_name = level.Name if level is not None else u''
        # 帶 id：同名視圖很常見，而選項文字必須唯一。
        label = u'{}　［{}］　#{}'.format(view.Name, level_name or u'無樓層',
                                        id_value(view.Id))
        rows.append((elevation, view.Name, label, view))
    rows.sort(key=lambda row: (row[0], row[1]))
    return [(label, view) for unused, unused2, label, view in rows]


def cad_files(folder):
    """資料夾內的 .dwg／.dxf（不遞迴），依檔名排序。"""
    found = []
    try:
        names = os.listdir(folder)
    except Exception:
        return found
    for name in sorted(names):
        if os.path.splitext(name)[1].lower() in ('.dwg', '.dxf'):
            found.append((name, os.path.join(folder, name)))
    return found


def revit_grid_lines(doc, view):
    """視圖中可見的直線 Grid（取不到就退回全部 Grid）。弧形 Grid 略過。"""
    grids = []
    try:
        grids = list(DB.FilteredElementCollector(doc, view.Id)
                     .OfClass(DB.Grid).ToElements())
    except Exception:
        grids = []
    if not grids:
        grids = list(DB.FilteredElementCollector(doc).OfClass(DB.Grid)
                     .ToElements())
    lines = []
    for grid in grids:
        try:
            curve = grid.Curve
        except Exception:
            continue
        if not isinstance(curve, DB.Line):
            continue
        lines.append(logic.make_line(_mm(curve.GetEndPoint(0)),
                                     _mm(curve.GetEndPoint(1)), grid.Name))
    return lines


def existing_import(doc, view, file_name):
    """這個視圖裡已經有同名 CAD 的話回傳它（重複執行不重複匯入）。"""
    wanted = (file_name or u'').lower()
    for instance in DB.FilteredElementCollector(doc).OfClass(
            DB.ImportInstance).WhereElementIsNotElementType():
        try:
            if instance.OwnerViewId != view.Id:
                continue
            type_name = area_sources.element_name(
                doc.GetElement(instance.GetTypeId())) or u''
        except Exception:
            continue
        if type_name.lower() == wanted:
            return instance
    return None


def build_options(color_mode, visible_only):
    options = DB.DWGImportOptions()
    options.ThisViewOnly = True
    options.Placement = DB.ImportPlacement.Origin
    options.Unit = DB.ImportUnit.Default  # 自動判斷 DWG 單位
    options.ColorMode = getattr(DB.ImportColorMode, color_mode,
                                DB.ImportColorMode.BlackAndWhite)
    options.VisibleLayersOnly = bool(visible_only)
    options.OrientToView = False
    return options


def place_cad(doc, path, view, options, mode):
    """匯入或連結一個 CAD，回傳 ImportInstance。呼叫端負責 Transaction。"""
    new_id = clr.Reference[DB.ElementId]()
    if mode == MODE_LINK:
        ok = doc.Link(path, options, view, new_id)
    else:
        ok = doc.Import(path, options, view, new_id)
    element_id = new_id.Value
    if not ok or element_id is None or element_id == DB.ElementId.InvalidElementId:
        raise Exception(u'Revit 回報{}失敗'.format(
            u'連結' if mode == MODE_LINK else u'匯入'))
    return doc.GetElement(element_id)


def grid_layer_lines(doc, instance, view, layer):
    """匯入後、平移前，CAD 軸線圖層上的直線（Revit 座標，mm）。"""
    return grid_layer_lines_with_summary(doc, instance, view, layer)[0]


def grid_layer_lines_with_summary(doc, instance, view, layer):
    """``(lines, {layer: (line_count, other_count)})``。

    摘要是給「讀到 0 條」時用的：圖層名稱打錯、軸線是弧、還是整張圖根本
    讀不到幾何，三種情況的處理方式完全不同，只回報「0 條」使用者無從下手。
    """
    lines = []
    summary = {}
    for row in area_sources.cad_layer_curves(doc, instance, view):
        name = row.get('layer') or u'(無圖層)'
        count = summary.get(name, (0, 0))
        is_line = row.get('kind') == 'Line'
        summary[name] = (count[0] + (1 if is_line else 0),
                         count[1] + (0 if is_line else 1))
        if not is_line or not logic.layer_matches(name, layer):
            continue
        lines.append(logic.make_line(row['start'], row['end']))
    return lines, summary


def move_and_pin(doc, instance, translation_mm, pin):
    vector = DB.XYZ(translation_mm[0] / MM_PER_FOOT,
                    translation_mm[1] / MM_PER_FOOT, 0.0)
    if vector.GetLength() > 1e-9:
        DB.ElementTransformUtils.MoveElement(doc, instance.Id, vector)
    if pin:
        instance.Pinned = True
