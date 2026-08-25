# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""步行距離檢核的 Revit 端取數 — JAC 03.01.

只做一件事：把樓層上的**可走空間**、**門洞位置**與**樓梯端點**化約成毫米純
tuple，交給 ``egress_distance_logic`` 去算。所有判斷都在那一側，這裡不做決定。

兩個必須說清楚的取數選擇：

**可走空間來自房間邊界，而房間邊界止於牆面。** 相鄰兩室的取樣格點因此天生不
相連，門是它們唯一的連接處。所以門的位置要主動補上一塊可走區域，半徑取
「宿主牆厚的一半 + 餘裕」，讓兩側確實接得起來。查不到宿主牆厚時退回一個明講
的預設值，而不是靜默當成零——當成零會讓整層樓變成一堆孤島。

**樓梯端點取整個梯段與平台的輪廓，而不是「路徑曲線的某一端」。**
``StairsRun.GetStairsPath()`` 沒有文件保證哪一端是下端，猜錯會把整段梯長算進
或漏掉。改以輪廓內的所有格點當多源起點後，量到的自然是**從樓面走得到的最近
一點**，也就是人實際踏上樓梯的地方——與 §93「第一階」相符，且不依賴曲線方向。
"""

from Autodesk.Revit import DB

import area_scheme_sources as sources


MM_PER_FOOT = 304.8

# 查不到宿主牆厚時用的門洞連通半徑。RC 隔間牆常見 150～200 mm，取 300 mm 讓
# 兩側確實接上；這個值會在報告裡列出來，不當成隱形常數。
FALLBACK_DOOR_RADIUS_MM = 300.0

# 牆厚一半之外再加的餘裕。格點是離散的，剛好等於半牆厚時兩側可能差一格而接不
# 起來，那會讓房間變成「無法到達」——安全但沒用。
DOOR_RADIUS_MARGIN_MM = 150.0


def _curve_loop_points(loop):
    """CurveLoop → 毫米點串；取不到就回空的。"""
    points = []
    try:
        curves = list(loop)
    except Exception:
        return points
    for curve in curves:
        try:
            tessellated = list(curve.Tessellate())
        except Exception:
            tessellated = []
        if not tessellated:
            try:
                tessellated = [curve.GetEndPoint(0), curve.GetEndPoint(1)]
            except Exception:
                tessellated = []
        for point in tessellated:
            xy = (point.X * MM_PER_FOOT, point.Y * MM_PER_FOOT)
            # 相鄰曲線共用端點，重複會在幾何判斷裡產生零長度邊。
            if not points or (abs(xy[0] - points[-1][0]) > 1e-6
                              or abs(xy[1] - points[-1][1]) > 1e-6):
                points.append(xy)
    return points


def collect_rooms(doc, level_id=None):
    """樓層上的房間，含毫米邊界迴圈。未放置或未封閉的一律排除但回報。

    回傳 ``(rows, skipped)``；``skipped`` 是 ``[(room_number, reason)]``，
    因為一個沒有邊界的房間不會出現在檢核結果裡，若不回報就等於默默漏檢。
    """
    rows = []
    skipped = []
    for record in sources.rooms_for_level(doc, level_id=level_id):
        label = record.get('room_number') or record.get('room_name') or u'(無編號)'
        if not record.get('placed'):
            skipped.append((label, u'房間未放置'))
            continue
        if not record.get('loops'):
            skipped.append((label, u'房間邊界未封閉，取不到迴圈'))
            continue
        rows.append({
            'id': record['id'],
            'element_id': record['element_id'],
            'room_number': record.get('room_number') or u'',
            'room_name': record.get('room_name') or u'',
            'level': record.get('level') or u'',
            'loops': record['loops'],
        })
    return rows, skipped


def _host_wall_thickness_mm(instance):
    """宿主牆厚（mm），查不到回 ``None``——由呼叫端決定要用什麼預設。"""
    try:
        host = instance.Host
    except Exception:
        return None
    if host is None:
        return None
    try:
        return float(host.Width) * MM_PER_FOOT
    except Exception:
        return None


def collect_doors(doc, level_id=None):
    """樓層上的門，含位置與連通半徑。

    半徑是**牆厚的一半加餘裕**，不是門寬——要打通的是牆這個厚度，不是洞口的
    寬度。用門寬會在薄牆上開出一塊過大的可走區域，讓路徑從門旁邊的牆體穿過。
    """
    rows = []
    category = getattr(DB.BuiltInCategory, 'OST_Doors', None)
    if category is None:
        return rows
    try:
        collector = (DB.FilteredElementCollector(doc)
                     .OfCategory(category)
                     .WhereElementIsNotElementType())
    except Exception:
        return rows
    for instance in collector:
        if level_id is not None and sources._level_id(instance) != level_id:
            continue
        point = sources._point_xy(instance)
        if point is None:
            continue
        thickness = _host_wall_thickness_mm(instance)
        if thickness is None:
            radius = FALLBACK_DOOR_RADIUS_MM
            assumed = True
        else:
            radius = thickness / 2.0 + DOOR_RADIUS_MARGIN_MM
            assumed = False
        rows.append({
            'id': sources.id_value(instance.Id),
            'element_id': instance.Id,
            'mark': sources.parameter_text(
                sources.built_in_parameter(instance, 'DOOR_NUMBER')),
            'name': sources.element_name(instance),
            'point_xy': point,
            'radius_mm': radius,
            'radius_assumed': assumed,
        })
    return rows


def _stairs_level_id(stair):
    """樓梯的基準樓層。``LevelId`` 對樓梯不一定有值，故先問專屬參數。"""
    parameter = sources.built_in_parameter(stair, 'STAIRS_BASE_LEVEL_PARAM')
    if parameter is not None:
        try:
            value = sources.id_value(parameter.AsElementId())
            if value > 0:
                return value
        except Exception:
            pass
    return sources._level_id(stair)


def collect_stairs(doc, level_id=None):
    """樓層上的樓梯，含梯段與平台的輪廓迴圈（毫米）。

    輪廓來自 ``GetFootprintBoundary()``，梯段與平台各自一圈；兩者都收，因為人
    可能從平台側踏上樓梯。曲線方向不影響結果——這正是不用 ``GetStairsPath()``
    的端點的理由。
    """
    rows = []
    category = getattr(DB.BuiltInCategory, 'OST_Stairs', None)
    if category is None:
        return rows
    try:
        collector = (DB.FilteredElementCollector(doc)
                     .OfCategory(category)
                     .WhereElementIsNotElementType())
    except Exception:
        return rows
    for stair in collector:
        if level_id is not None and _stairs_level_id(stair) != level_id:
            continue
        loops = []
        for getter in ('GetStairsRuns', 'GetStairsLandings'):
            method = getattr(stair, getter, None)
            if method is None:
                continue
            try:
                component_ids = list(method())
            except Exception:
                continue
            for component_id in component_ids:
                try:
                    component = doc.GetElement(component_id)
                except Exception:
                    component = None
                if component is None:
                    continue
                try:
                    boundary = component.GetFootprintBoundary()
                except Exception:
                    boundary = None
                if boundary is None:
                    continue
                points = _curve_loop_points(boundary)
                if len(points) >= 3:
                    loops.append(points)
        rows.append({
            'id': sources.id_value(stair.Id),
            'element_id': stair.Id,
            'name': sources.element_name(stair),
            'mark': sources.parameter_text(
                sources.built_in_parameter(stair, 'ALL_MODEL_MARK')),
            'loops': loops,
        })
    return rows
