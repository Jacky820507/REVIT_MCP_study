# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""重疊車位檢核（JAC 07.01）— read-only.

Finds parking bays that physically overlap each other in plan: duplicates left
behind by a copy-paste, and bays pushed into their neighbour. Nothing is
written; the only side effect offered is selecting the offenders.

The geometry rules (oriented rectangles, per-level comparison, tolerance) live
in :mod:`parking_overlap_logic`. This file only turns Revit elements into the
rectangles that module expects — which is the part that needs a live document
and cannot be unit-tested.
"""

__title__ = u'重疊車位\n檢核'
__author__ = 'RevitMCP'

from Autodesk.Revit import DB
from pyrevit import forms, revit, script
from System.Collections.Generic import List

import parking_overlap_logic as logic


TITLE = u'重疊車位檢核'
MM_PER_FOOT = 304.8
ALL_LEVELS = u'（全部樓層）'


def _id_value(element_id):
    if element_id is None:
        return -1
    # Revit 2025+ exposes .Value; 2020-2024 only .IntegerValue.
    try:
        return int(element_id.Value)
    except Exception:
        try:
            return int(element_id.IntegerValue)
        except Exception:
            return -1


def _element_name(element):
    if element is None:
        return u''
    try:
        return DB.Element.Name.GetValue(element) or u''
    except Exception:
        try:
            return element.Name or u''
        except Exception:
            return u''


def _levels(doc):
    found = list(DB.FilteredElementCollector(doc)
                 .OfClass(DB.Level)
                 .WhereElementIsNotElementType()
                 .ToElements())
    found.sort(key=lambda level: (level.Elevation, _element_name(level)))
    return found


def _level_id(element):
    """Level of a parking bay, with the fallbacks Revit actually needs."""
    try:
        value = _id_value(element.LevelId)
        if value >= 0:
            return value
    except Exception:
        pass
    for name in ('INSTANCE_REFERENCE_LEVEL_PARAM', 'FAMILY_LEVEL_PARAM',
                 'INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM', 'SCHEDULE_LEVEL_PARAM',
                 'LEVEL_PARAM'):
        built_in = getattr(DB.BuiltInParameter, name, None)
        if built_in is None:
            continue
        try:
            parameter = element.get_Parameter(built_in)
            if parameter is not None:
                value = _id_value(parameter.AsElementId())
                if value >= 0:
                    return value
        except Exception:
            pass
    return -1


def _mark(element):
    built_in = getattr(DB.BuiltInParameter, 'ALL_MODEL_MARK', None)
    if built_in is None:
        return u''
    try:
        parameter = element.get_Parameter(built_in)
        return (parameter.AsString() or u'') if parameter else u''
    except Exception:
        return u''


def _geometry_points(element):
    """Every vertex of the bay's coarse geometry, in world coordinates."""
    options = DB.Options()
    options.ComputeReferences = False
    options.IncludeNonVisibleObjects = False
    try:
        options.DetailLevel = DB.ViewDetailLevel.Coarse
    except Exception:
        pass
    points = []

    def walk(container, depth):
        if container is None or depth > 3:
            return
        for item in container:
            if isinstance(item, DB.GeometryInstance):
                # Instance geometry is already in world coordinates, which
                # avoids having to compose the symbol transform by hand.
                walk(item.GetInstanceGeometry(), depth + 1)
            elif isinstance(item, DB.Solid):
                try:
                    for edge in item.Edges:
                        curve = edge.AsCurve()
                        if curve is not None:
                            points.extend(curve.Tessellate())
                except Exception:
                    pass
            elif isinstance(item, DB.Mesh):
                try:
                    points.extend(item.Vertices)
                except Exception:
                    pass
            elif isinstance(item, DB.Curve):
                try:
                    points.extend(item.Tessellate())
                except Exception:
                    pass

    try:
        walk(element.get_Geometry(options), 0)
    except Exception:
        return []
    return points


def _rect_from_geometry(element):
    """Oriented rectangle in mm, or ``None`` when the geometry is unusable.

    The bay's own transform gives the axes, so the extents are measured in the
    bay's local frame — that is what keeps a 45-degree bay from being treated
    as the much larger box that encloses it.
    """
    try:
        transform = element.GetTransform()
    except Exception:
        return None
    points = _geometry_points(element)
    if not points:
        return None
    try:
        inverse = transform.Inverse
    except Exception:
        return None
    min_x = min_y = None
    max_x = max_y = None
    for point in points:
        try:
            local = inverse.OfPoint(point)
        except Exception:
            continue
        if min_x is None or local.X < min_x:
            min_x = local.X
        if max_x is None or local.X > max_x:
            max_x = local.X
        if min_y is None or local.Y < min_y:
            min_y = local.Y
        if max_y is None or local.Y > max_y:
            max_y = local.Y
    if min_x is None or max_x - min_x <= 0 or max_y - min_y <= 0:
        return None
    local_center = DB.XYZ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0, 0.0)
    center = transform.OfPoint(local_center)
    return logic.make_rect(
        (center.X * MM_PER_FOOT, center.Y * MM_PER_FOOT),
        (transform.BasisX.X, transform.BasisX.Y),
        (transform.BasisY.X, transform.BasisY.Y),
        ((max_x - min_x) / 2.0 * MM_PER_FOOT,
         (max_y - min_y) / 2.0 * MM_PER_FOOT))


def _rect_from_bounding_box(element):
    """Axis-aligned fallback. Wider than a rotated bay, so it is flagged."""
    try:
        box = element.get_BoundingBox(None)
    except Exception:
        box = None
    if box is None:
        return None
    width = (box.Max.X - box.Min.X) * MM_PER_FOOT
    length = (box.Max.Y - box.Min.Y) * MM_PER_FOOT
    if width <= 0 or length <= 0:
        return None
    return logic.make_rect(
        ((box.Min.X + box.Max.X) / 2.0 * MM_PER_FOOT,
         (box.Min.Y + box.Max.Y) / 2.0 * MM_PER_FOOT),
        (1.0, 0.0), (0.0, 1.0), (width / 2.0, length / 2.0))


def _in_group(element):
    try:
        return _id_value(element.GroupId) > 0
    except Exception:
        return False


def _collect(doc, allowed_level_ids, level_names):
    bays = []
    collector = (DB.FilteredElementCollector(doc)
                 .OfCategory(DB.BuiltInCategory.OST_Parking)
                 .WhereElementIsNotElementType())
    for element in collector:
        level_id = _level_id(element)
        if (allowed_level_ids is not None
                and level_id not in allowed_level_ids):
            continue
        rect = _rect_from_geometry(element)
        approx = False
        if rect is None:
            rect = _rect_from_bounding_box(element)
            approx = rect is not None
        symbol = None
        try:
            symbol = element.Symbol
        except Exception:
            symbol = doc.GetElement(element.GetTypeId())
        bays.append({
            'id': _id_value(element.Id),
            'element_id': element.Id,
            'level_id': level_id,
            'level': level_names.get(level_id, u'(未知樓層)'),
            'mark': _mark(element),
            'type_name': _element_name(symbol),
            'family_name': _element_name(
                symbol.Family) if symbol is not None else u'',
            'rect': rect,
            'approx': approx,
            'in_group': _in_group(element),
        })
    return bays


def _pick_levels(doc):
    """``None`` means every level — the documented default is 全部."""
    levels = _levels(doc)
    if not levels:
        return None
    labels = [ALL_LEVELS] + [_element_name(level) for level in levels]
    picked = forms.SelectFromList.show(
        labels, title=u'選擇檢查範圍（可複選）', multiselect=True)
    if not picked:
        return None
    if ALL_LEVELS in picked:
        return None
    allowed = set()
    for level in levels:
        if _element_name(level) in picked:
            allowed.add(_id_value(level.Id))
    return allowed or None


def _print_table(report):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    output.print_md(u'容許重疊：**{:.0f} mm**'.format(report['tolerance_mm']))
    if not report['clusters']:
        output.print_md(u'沒有重疊車位。')
        return
    rows = []
    for index, group in enumerate(report['clusters'], start=1):
        for bay in group['members']:
            rows.append([
                u'{}'.format(index),
                output.linkify(bay['element_id']),
                bay['level'],
                bay['mark'],
                bay['type_name'],
                u'{:.0f}'.format(group['depth']),
                u'{}'.format(len(group['members'])),
            ])
    output.print_table(
        table_data=rows,
        columns=[u'重疊處', u'Element ID', u'樓層', u'編號', u'類型',
                 u'最大重疊(mm)', u'該處車位數'])


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行重疊車位檢核。',
                    title=TITLE, exitscript=True)

    # Neighbouring bays share an edge, so 「重疊多少才算重疊」 is a project
    # decision, not a constant. See domain/user-specified-runtime-parameters.md.
    raw = forms.ask_for_string(
        default=u'{:.0f}'.format(logic.DEFAULT_TOLERANCE_MM),
        prompt=u'容許重疊 (mm)：小於此值視為相鄰、不報\n'
               u'（相鄰車位共用邊線，設 0 會把整排都報出來）',
        title=TITLE)
    if not raw:
        return
    try:
        tolerance = float(raw.strip())
    except ValueError:
        forms.alert(u'容許重疊必須是數字。', title=TITLE)
        return
    if tolerance < 0:
        forms.alert(u'容許重疊不能是負數。', title=TITLE)
        return

    allowed_level_ids = _pick_levels(doc)
    level_names = {}
    for level in _levels(doc):
        level_names[_id_value(level.Id)] = _element_name(level)

    bays = _collect(doc, allowed_level_ids, level_names)
    if not bays:
        forms.alert(u'指定範圍內沒有停車位（Parking 類別）。', title=TITLE)
        return

    report = logic.analyze(bays, tolerance_mm=tolerance)
    _print_table(report)
    summary = logic.report_lines(report)

    if not report['clusters']:
        forms.alert(u'{}\n\n明細已列在 pyRevit 輸出視窗。'.format(summary),
                    title=TITLE)
        return

    if forms.alert(
            u'{}\n\n明細已列在 pyRevit 輸出視窗。\n'
            u'要把這些車位選取起來嗎？'.format(summary),
            title=TITLE, yes=True, no=True):
        ids = List[DB.ElementId]()
        for value in report['flagged_ids']:
            ids.Add(DB.ElementId(int(value)))
        revit.uidoc.Selection.SetElementIds(ids)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
