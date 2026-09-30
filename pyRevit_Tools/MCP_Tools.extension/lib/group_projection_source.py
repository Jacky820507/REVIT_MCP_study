# -*- coding: utf-8 -*-
"""Read detail groups in API context; build detached plan-projection segments.

IronPython 2.7 compatible. Coordinates are internal feet throughout. Group
member geometry is already in project coordinates: never apply Group.Location
or the FamilyInstance transform a second time to GetInstanceGeometry().
"""
from __future__ import unicode_literals

import math

from Autodesk.Revit import DB

PROJECTION_FRONT_OFFSET_MM = 100.0
PROJECTION_NEAR_INSET_MM = 25.0


def id_value(value):
    try:
        return int(value.Value)
    except AttributeError:
        return int(value.IntegerValue)


def is_plan_view(view):
    """Return whether *view* is a Revit plan view without assuming test stubs."""
    view_plan = getattr(DB, 'ViewPlan', None)
    return view_plan is not None and isinstance(view, view_plan)


def _view_origin(view):
    try:
        return view.Origin
    except Exception:
        return None


def _view_direction(view):
    try:
        return view.ViewDirection
    except Exception:
        return None


def target_view_error(view):
    """Return a user-facing error, or None when the view has a projection plane."""
    if view is None:
        return '目前沒有可用的 Revit 視圖。'
    try:
        if view.IsTemplate:
            return '視圖樣板不能作為投影目標，請切換到實際視圖。'
    except Exception:
        pass
    if is_plan_view(view):
        return None
    origin = _view_origin(view)
    direction = _view_direction(view)
    if origin is None or direction is None:
        return ('目前視圖不提供可用的視圖平面；請改用平面、剖面、立面、'
                '詳圖、製圖或 3D 視圖。')
    length = math.sqrt(direction.X * direction.X +
                       direction.Y * direction.Y +
                       direction.Z * direction.Z)
    if length < 1e-12:
        return '目前視圖的觀看方向無效，無法建立投影平面。'
    return None


def level_of(view):
    level = None
    try:
        level = view.GenLevel
    except Exception:
        pass
    if level:
        return (level.Name, level.Elevation)
    origin = _view_origin(view)
    if origin is not None:
        return ('視圖平面', origin.Z)
    return ('未指定樓層', None)


def collect_groups(doc, target):
    records = []
    for group in DB.FilteredElementCollector(doc).OfClass(DB.Group):
        if id_value(group.GroupId) != -1:
            continue  # nested groups are traversed from their parent only
        try:
            source = doc.GetElement(group.OwnerViewId)
        except Exception:
            source = None
        if source is None or source.IsTemplate:
            continue
        if id_value(source.Id) == id_value(target.Id):
            continue
        name, elevation = level_of(source)
        records.append(dict(id=id_value(group.Id), name=group.Name,
                            view_id=id_value(source.Id), view_name=source.Name,
                            level=name, elevation=elevation))
    return sorted(records, key=lambda r: (r['elevation'] is None,
                                          r['elevation'] or 0, r['view_name'], r['id']))


def projection_z(view):
    """Choose a plan depth just inside the side facing the view camera."""
    if not is_plan_view(view):
        origin = _view_origin(view)
        direction = _view_direction(view)
        if origin is None or direction is None:
            raise ValueError('目前視圖沒有可用的投影平面。')
        return origin.Z + direction.Z * PROJECTION_FRONT_OFFSET_MM / 304.8

    cut = _plan_plane_z(view, DB.PlanViewPlane.CutPlane)
    try:
        top = _plan_plane_z(view, DB.PlanViewPlane.TopClipPlane)
        bottom = _plan_plane_z(view, DB.PlanViewPlane.BottomClipPlane)
    except Exception:
        return cut

    low, high = min(top, bottom), max(top, bottom)
    span = high - low
    if span <= 1e-9:
        return cut

    # Structural plans can look up or down. The property is only valid on
    # StructuralPlan; normal floor/ceiling plans use View.ViewDirection.
    near_top = None
    try:
        if view.ViewType == DB.ViewType.StructuralPlan:
            view_type = view.Document.GetElement(view.GetTypeId())
            near_top = view_type.PlanViewDirection != DB.PlanViewDirection.Up
    except Exception:
        near_top = None
    if near_top is None:
        direction = _view_direction(view)
        near_top = direction is None or direction.Z >= 0.0

    inset = min(PROJECTION_NEAR_INSET_MM / 304.8, span * 0.02)
    return high - inset if near_top else low + inset


def _plan_plane_z(view, plane):
    view_range = view.GetViewRange()
    level = view.Document.GetElement(view_range.GetLevelId(plane))
    if level is None:
        level = view.GenLevel
    if level is None:
        raise ValueError('目前視圖沒有可用的樓層／剖切平面。')
    return level.Elevation + view_range.GetOffset(plane)


def project_point(point, view, fallback_z=None):
    """Project a source point onto the target view's display plane.

    Plan views retain the existing XY-over-target-Z behaviour. Other
    orthographic or perspective views use their screen origin and view
    direction, so the same source geometry can be displayed without assuming
    that the target is a drainage floor plan.
    """
    if is_plan_view(view):
        z = projection_z(view) if fallback_z is None else fallback_z
        return DB.XYZ(point.X, point.Y, z)

    origin = _view_origin(view)
    direction = _view_direction(view)
    if origin is None or direction is None:
        if fallback_z is None:
            raise ValueError('目前視圖沒有可用的投影平面。')
        # Keeps isolated unit-test stubs and legacy callers deterministic.
        return DB.XYZ(point.X, point.Y, fallback_z)
    length = math.sqrt(direction.X * direction.X +
                       direction.Y * direction.Y +
                       direction.Z * direction.Z)
    if length < 1e-12:
        raise ValueError('目前視圖的觀看方向無效，無法建立投影平面。')
    nx, ny, nz = (direction.X / length, direction.Y / length,
                  direction.Z / length)
    dx, dy, dz = (point.X - origin.X, point.Y - origin.Y,
                  point.Z - origin.Z)
    depth = dx * nx + dy * ny + dz * nz
    offset = PROJECTION_FRONT_OFFSET_MM / 304.8
    return DB.XYZ(point.X - nx * depth + nx * offset,
                  point.Y - ny * depth + ny * offset,
                  point.Z - nz * depth + nz * offset)


def diagnostic_segments(view, corners):
    """Build visible crosses at several depths in a plan view.

    Independent of group extraction. Distinct colors reveal depth clipping.
    """
    low, high = corners
    center = DB.XYZ((low.X + high.X) / 2.0,
                    (low.Y + high.Y) / 2.0,
                    (low.Z + high.Z) / 2.0)
    diagonal = low.DistanceTo(high)
    radius = max(0.5, diagonal * 0.02)
    right, up = view.RightDirection, view.UpDirection
    if is_plan_view(view):
        top = _plan_plane_z(view, DB.PlanViewPlane.TopClipPlane)
        cut = projection_z(view)
        bottom = _plan_plane_z(view, DB.PlanViewPlane.BottomClipPlane)
        inset = min(100.0 / 304.8, max(0.0, (top - bottom) / 10.0))
        depths = [(top - inset, (255, 0, 255), -1),
                  (cut, (0, 180, 0), 0),
                  (bottom + inset, (0, 110, 255), 1)]
    else:
        depths = [(None, (255, 0, 255), 0)]
    pairs = [((-1, 0), (1, 0)), ((0, -1), (0, 1)),
             ((0, 1), (1, 0)), ((1, 0), (0, -1)),
             ((0, -1), (-1, 0)), ((-1, 0), (0, 1))]
    result = []
    for depth, color, position in depths:
        shifted = DB.XYZ(center.X + position * diagonal * 0.10 * right.X,
                         center.Y + position * diagonal * 0.10 * right.Y,
                         center.Z + position * diagonal * 0.10 * right.Z)
        origin = project_point(shifted, view, depth)

        def at(x, y):
            return DB.XYZ(origin.X + radius * (x * right.X + y * up.X),
                          origin.Y + radius * (x * right.Y + y * up.Y),
                          origin.Z + radius * (x * right.Z + y * up.Z))

        result.extend((at(*a), at(*b), color) for a, b in pairs)
    return result


class ExtractionCancelled(Exception):
    pass


class SegmentLimit(Exception):
    pass


class Reader(object):
    def __init__(self, doc, target, color, cancelled=None, max_segments=200000):
        self.doc = doc
        self.z = projection_z(target)
        self.target = target
        self.color = color
        self.cancelled = cancelled or (lambda: False)
        self.max_segments = max_segments
        self.segments = []
        self.warnings = []
        self.symbols = []
        self.symbol_ids = set()
        self.visited = set()
        self.element_count = 0
        self.seen_segments = set()

    def line(self, a, b):
        if self.cancelled():
            raise ExtractionCancelled()
        a, b = (project_point(a, self.target, self.z),
                project_point(b, self.target, self.z))
        if a.DistanceTo(b) < 1e-8:
            return
        key = tuple(sorted(((round(a.X, 8), round(a.Y, 8), round(a.Z, 8)),
                            (round(b.X, 8), round(b.Y, 8), round(b.Z, 8)))))
        if key in self.seen_segments:
            return
        if len(self.segments) >= self.max_segments:
            raise SegmentLimit('群組線段超過上限，請縮小選取範圍。')
        self.seen_segments.add(key)
        self.segments.append((a, b, self.color))

    def curve(self, curve):
        points = list(curve.Tessellate())
        for i in range(1, len(points)):
            self.line(points[i - 1], points[i])

    def geometry(self, geometry):
        if geometry is None:
            return
        for obj in geometry:
            if isinstance(obj, DB.GeometryInstance):
                self.geometry(obj.GetInstanceGeometry())
            elif isinstance(obj, DB.Curve):
                self.curve(obj)
            elif isinstance(obj, DB.PolyLine):
                points = list(obj.GetCoordinates())
                for i in range(1, len(points)):
                    self.line(points[i - 1], points[i])
            elif isinstance(obj, DB.Solid):
                for edge in obj.Edges:
                    self.curve(edge.AsCurve())
            elif isinstance(obj, DB.Mesh):
                for i in range(obj.NumTriangles):
                    tri = obj.get_Triangle(i)
                    for j in range(3):
                        self.line(tri.get_Vertex(j), tri.get_Vertex((j + 1) % 3))

    def symbol(self, element):
        eid = id_value(element.Id)
        if eid in self.symbol_ids:
            return
        values = {}
        for name in ('UP', 'DN'):
            param = element.LookupParameter(name)
            values[name] = bool(param.AsInteger()) if param and param.StorageType == DB.StorageType.Integer else None
        if all(v is None for v in values.values()):
            return
        self.symbol_ids.add(eid)
        values['id'] = eid
        self.symbols.append(values)

    def text_node(self, node):
        """Convert a Revit 2D-export text node to temporary outline segments."""
        from System.Globalization import CultureInfo
        from System.Windows import FlowDirection, Point, TextAlignment
        from System.Windows.Media import (FormattedText, Typeface, Brushes,
                                          PolyLineSegment, LineSegment,
                                          ToleranceType)
        text = node.Text
        font = node.FontName or 'Arial'
        height = node.FontHeight
        if not text or height <= 1e-9:
            return
        factor = height / 100.0
        width_scale = max(1e-6, node.WidthScale)
        formatted = FormattedText(text, CultureInfo.CurrentCulture,
                                  FlowDirection.LeftToRight, Typeface(font),
                                  100.0, Brushes.Black)
        if node.Width > 0:
            formatted.MaxTextWidth = max(1.0, node.Width / (factor * width_scale))
        horizontal = str(node.HorizontalAlignment).split('.')[-1]
        if horizontal == 'Center':
            formatted.TextAlignment = TextAlignment.Center
        elif horizontal == 'Right':
            formatted.TextAlignment = TextAlignment.Right
        path = formatted.BuildGeometry(Point(0, 0)).GetFlattenedPathGeometry(
            0.3, ToleranceType.Absolute)
        base, up, origin = node.BaseDirection, node.UpDirection, node.Position
        if horizontal == 'Center':
            origin = origin.Subtract(base.Multiply(node.Width / 2.0))
        elif horizontal == 'Right':
            origin = origin.Subtract(base.Multiply(node.Width))
        vertical = str(node.VerticalAlignment).split('.')[-1]
        if vertical == 'Center':
            origin = origin.Add(up.Multiply(node.Height / 2.0))
        elif vertical == 'Bottom':
            origin = origin.Add(up.Multiply(node.Height))

        def point(p):
            return origin.Add(base.Multiply(p.X * factor * width_scale)).Subtract(
                up.Multiply(p.Y * factor))

        for figure in path.Figures:
            previous = figure.StartPoint
            for segment in figure.Segments:
                points = list(segment.Points) if isinstance(segment, PolyLineSegment) else (
                    [segment.Point] if isinstance(segment, LineSegment) else [])
                for p in points:
                    self.line(point(previous), point(p))
                    previous = p
            if figure.IsClosed:
                self.line(point(previous), point(figure.StartPoint))
        self.warnings.append('文字：DC3D 以向量輪廓近似顯示，字型與富文字格式請以原圖為準。')

    def text(self, note, source):
        """TextNote outlines, not native Revit glyphs; formatting is approximate."""
        from System.Globalization import CultureInfo
        from System.Windows import FlowDirection, Point, TextAlignment
        from System.Windows.Media import (FormattedText, Typeface, Brushes,
                                          PolyLineSegment, LineSegment,
                                          ToleranceType)
        kind = self.doc.GetElement(note.GetTypeId())
        font = kind.get_Parameter(DB.BuiltInParameter.TEXT_FONT).AsString()
        size = kind.get_Parameter(DB.BuiltInParameter.TEXT_SIZE).AsDouble()
        # 100 DIP em creates a stable outline; then convert to model feet.
        formatted = FormattedText(note.Text, CultureInfo.CurrentCulture,
                                  FlowDirection.LeftToRight, Typeface(font),
                                  100.0, Brushes.Black)
        factor = size * source.Scale / 100.0
        # Width is in paper feet, whereas Coord is in model feet.
        width = note.Width * source.Scale
        if note.IsTextWrappingActive and width > 0:
            formatted.MaxTextWidth = max(1.0, width / factor)
        alignment = str(note.HorizontalAlignment)
        if alignment == 'Center':
            formatted.TextAlignment = TextAlignment.Center
        elif alignment == 'Right':
            formatted.TextAlignment = TextAlignment.Right
        path = formatted.BuildGeometry(Point(0, 0)).GetFlattenedPathGeometry(
            0.3, ToleranceType.Absolute)
        base, up, origin = note.BaseDirection, note.UpDirection, note.Coord
        if note.IsTextWrappingActive:
            if alignment == 'Center':
                origin = origin.Subtract(base.Multiply(width / 2.0))
            elif alignment == 'Right':
                origin = origin.Subtract(base.Multiply(width))

        def point(p):
            return origin.Add(base.Multiply(p.X * factor)).Subtract(up.Multiply(p.Y * factor))

        for figure in path.Figures:
            previous = figure.StartPoint
            for segment in figure.Segments:
                points = list(segment.Points) if isinstance(segment, PolyLineSegment) else (
                    [segment.Point] if isinstance(segment, LineSegment) else [])
                for p in points:
                    self.line(point(previous), point(p))
                    previous = p
            if figure.IsClosed:
                self.line(point(previous), point(figure.StartPoint))
        for leader in note.GetLeaders():
            self.line(leader.Anchor, leader.Elbow)
            self.line(leader.Elbow, leader.End)
        self.warnings.append('文字 {}：輪廓近似；字型、對齊、富文字及引線弧度請以原圖為準。'.format(id_value(note.Id)))

    def element(self, element, source):
        if self.cancelled():
            raise ExtractionCancelled()
        eid = id_value(element.Id)
        if eid in self.visited:
            return
        self.visited.add(eid)
        try:
            if element.IsHidden(source):
                return
            if element.Category and source.GetCategoryHidden(element.Category.Id):
                return
        except Exception as exc:
            self.warnings.append('元素 {}：無法確認來源可見性：{}'.format(eid, exc))
            return
        if isinstance(element, DB.Group):
            for member_id in element.GetMemberIds():
                member = self.doc.GetElement(member_id)
                if member is not None:
                    self.element(member, source)
            return
        self.element_count += 1
        before = len(self.segments)
        try:
            if isinstance(element, DB.CurveElement):
                self.curve(element.GeometryCurve)
            elif isinstance(element, DB.FilledRegion):
                for loop in element.GetBoundaries():
                    for curve in loop:
                        self.curve(curve)
                self.warnings.append('填充區域 {}：顯示邊界，未投影填充紋樣／遮罩。'.format(eid))
            elif isinstance(element, DB.TextNote):
                self.text(element, source)
            else:
                options = DB.Options()
                options.View = source
                options.IncludeNonVisibleObjects = False
                self.geometry(element.get_Geometry(options))
                if isinstance(element, DB.FamilyInstance):
                    self.symbol(element)
            if len(self.segments) == before:
                self.warnings.append('元素 {}（{}）：無可投影線形或與已有線形重合。'.format(eid, element.Name))
        except (ExtractionCancelled, SegmentLimit):
            raise
        except Exception as exc:
            self.warnings.append('元素 {}：{}'.format(eid, exc))


def extract(doc, target, record, color, cancelled=None):
    group = doc.GetElement(DB.ElementId(record['id']))
    source = doc.GetElement(DB.ElementId(record['view_id']))
    if group is None or source is None:
        raise ValueError('群組或來源視圖已刪除，請重新整理清單。')
    reader = Reader(doc, target, color, cancelled)
    reader.element(group, source)
    reader.warnings.append('詳圖族群內的標籤文字、填充及遮罩不保證可由幾何 API 取得。')
    return reader


_EXPORT_CONTEXT_2D = getattr(DB, 'IExportContext2D', object)


class GroupExportContext2D(_EXPORT_CONTEXT_2D):
    """Capture the displayed 2D graphics of selected detail-group members."""
    def __init__(self, owners, readers, cancelled=None):
        self.owners = owners
        self.readers = readers
        self.cancelled = cancelled or (lambda: False)
        self.group_stack = []

    def _action(self, proceed):
        return DB.RenderNodeAction.Proceed if proceed else DB.RenderNodeAction.Skip

    def _group_id(self):
        for group_id in reversed(self.group_stack):
            if group_id is not None:
                return group_id
        return None

    def _reader(self):
        group_id = self._group_id()
        return self.readers.get(group_id) if group_id is not None else None

    def _add_polyline(self, points):
        reader = self._reader()
        if reader is None or points is None:
            return
        points = list(points)
        for index in range(1, len(points)):
            reader.line(points[index - 1], points[index])

    def Start(self):
        return True

    def Finish(self):
        pass

    def IsCanceled(self):
        return bool(self.cancelled())

    def OnViewBegin(self, node):
        return self._action(True)

    def OnViewEnd(self, element_id):
        pass

    def OnElementBegin2D(self, node):
        element_id = id_value(node.ElementId)
        group_id = self.owners.get(element_id)
        if group_id is None:
            group_id = self._group_id()
        self.group_stack.append(group_id)
        return self._action(group_id is not None)

    def OnElementEnd2D(self, node):
        if self.group_stack:
            self.group_stack.pop()

    def OnElementBegin(self, element_id):
        return self._action(True)

    def OnElementEnd(self, element_id):
        pass

    def OnInstanceBegin(self, node):
        return self._action(True)

    def OnInstanceEnd(self, node):
        pass

    def OnLinkBegin(self, node):
        return self._action(True)

    def OnLinkEnd(self, node):
        pass

    def OnFaceBegin(self, node):
        return self._action(self._reader() is not None)

    def OnFaceEnd(self, node):
        pass

    def OnFaceEdge2D(self, node):
        reader = self._reader()
        if reader is None:
            return self._action(False)
        try:
            edge = node.GetFaceEdge()
            reader.curve(edge.AsCurve())
        except Exception:
            # Revit may provide the tessellated edge through OnLineSegment.
            pass
        return self._action(True)

    def OnFaceSilhouette2D(self, node):
        return self._action(self._reader() is not None)

    def OnCurve(self, node):
        reader = self._reader()
        if reader is None:
            return self._action(False)
        try:
            reader.curve(node.GetCurve())
        except Exception as exc:
            reader.warnings.append('2D 匯出曲線：{}'.format(exc))
        return self._action(False)

    def OnPolyline(self, node):
        reader = self._reader()
        if reader is None:
            return self._action(False)
        try:
            self._add_polyline(node.GetPolyline().GetCoordinates())
        except Exception as exc:
            reader.warnings.append('2D 匯出多段線：{}'.format(exc))
        return self._action(False)

    def OnLineSegment(self, segment):
        reader = self._reader()
        if reader is not None:
            reader.line(segment.StartPoint, segment.EndPoint)

    def OnPolylineSegments(self, segments):
        if self._reader() is not None:
            self._add_polyline(segments.GetVertices())

    def OnText(self, node):
        reader = self._reader()
        if reader is not None:
            try:
                reader.text_node(node)
            except Exception as exc:
                reader.warnings.append('2D 匯出文字：{}'.format(exc))

    def OnPolymesh(self, topology):
        # IExportContext.OnPolymesh has a void return; 2D line callbacks carry
        # the geometry needed by this projection, so do not emit tessellation.
        pass

    def OnMaterial(self, node):
        pass

    def OnLight(self, node):
        pass

    def OnRPC(self, node):
        pass


def _prepare_group(doc, record, reader, owners, cancelled):
    group = doc.GetElement(DB.ElementId(record['id']))
    source_view = doc.GetElement(DB.ElementId(record['view_id']))
    if group is None or source_view is None:
        raise ValueError('群組或來源視圖已刪除，請重新整理清單。')
    group_id = record['id']
    visited = set()

    def visit(element):
        if cancelled():
            raise ExtractionCancelled()
        element_id = id_value(element.Id)
        owners[element_id] = group_id
        if element_id in visited:
            return
        visited.add(element_id)
        if isinstance(element, DB.Group):
            for member_id in element.GetMemberIds():
                member = doc.GetElement(member_id)
                if member is not None:
                    visit(member)
            return
        reader.element_count += 1
        try:
            reader.symbol(element)
        except Exception as exc:
            reader.warnings.append('元素 {} 的 UP/DN 參數：{}'.format(element_id, exc))

    visit(group)
    return group, source_view


def _legacy_group_fallback(doc, target, record, reader, cancelled):
    fallback = Reader(doc, target, reader.color, cancelled)
    group = doc.GetElement(DB.ElementId(record['id']))
    source_view = doc.GetElement(DB.ElementId(record['view_id']))
    if group is None or source_view is None:
        raise ValueError('群組或來源視圖已刪除，請重新整理清單。')
    fallback.element(group, source_view)
    reader.segments.extend(fallback.segments)
    reader.seen_segments.update(fallback.seen_segments)
    reader.element_count = max(reader.element_count, fallback.element_count)
    reader.warnings.extend(fallback.warnings)
    known = set(item['id'] for item in reader.symbols)
    for item in fallback.symbols:
        if item['id'] not in known:
            known.add(item['id'])
            reader.symbols.append(item)
    reader.symbol_ids.update(known)


def extract_selected_groups(doc, target, records, colors, cancelled=None,
                           progress=None):
    """Export selected source views' 2D display, retaining group colors.

    Revit 2020's CustomExporter/IExportContext2D is the primary path because
    it includes view-specific detail graphics and optional annotations. The
    existing element-geometry reader remains a per-group fallback.
    """
    cancelled = cancelled or (lambda: False)
    readers = dict((record['id'], Reader(doc, target,
                    colors[record['id']]['rgb'], cancelled)) for record in records)
    by_view = {}
    group_elements = {}
    for record in records:
        owners = {}
        group, source_view = _prepare_group(
            doc, record, readers[record['id']], owners, cancelled)
        group_elements[record['id']] = (group, source_view, owners)
        by_view.setdefault(record['view_id'], []).append(record)

    view_items = list(by_view.items())
    for view_index, (view_id, view_records) in enumerate(view_items):
        if cancelled():
            raise ExtractionCancelled()
        source_view = group_elements[view_records[0]['id']][1]
        owners = {}
        for record in view_records:
            unused_group, unused_view, owner_map = group_elements[record['id']]
            for element_id in owner_map:
                owners[element_id] = record['id']

        exported = False
        exporter = None
        try:
            exporter_type = getattr(DB, 'CustomExporter', None)
            context_type = getattr(DB, 'IExportContext2D', None)
            if exporter_type is None or context_type is None:
                raise RuntimeError('此 Revit API 未提供 2D CustomExporter。')
            if source_view.ViewType == DB.ViewType.ThreeD:
                raise RuntimeError('3D 來源視圖改用元素幾何擷取。')
            context = GroupExportContext2D(owners, readers, cancelled)
            exporter = exporter_type(doc, context)
            exporter.IncludeGeometricObjects = True
            exporter.Export2DIncludingAnnotationObjects = True
            exporter.Export2DGeometricObjectsIncludingPatternLines = True
            exporter.Export2DForceDisplayStyle = DB.DisplayStyle.HLR
            exporter.ShouldStopOnError = False
            exporter.Export(source_view)
            exported = True
        except ExtractionCancelled:
            raise
        except Exception as exc:
            for record in view_records:
                readers[record['id']].warnings.append(
                    '2D 視圖匯出未完成，改用元素幾何擷取：{}'.format(exc))
        finally:
            if exporter is not None:
                try:
                    exporter.Dispose()
                except Exception:
                    pass

        for record in view_records:
            reader = readers[record['id']]
            if not reader.segments:
                if exported:
                    reader.warnings.append(
                        '2D 匯出未取得此群組線稿，改用元素幾何擷取。')
                _legacy_group_fallback(doc, target, record, reader, cancelled)
            if not reader.segments:
                reader.warnings.append(
                    '此群組沒有可顯示的曲線；請確認來源視圖可見性與群組成員幾何。')
        if progress is not None:
            progress(view_index + 1, len(view_items))

    return readers


def ensure_projection_visible(ui_view, view, segments):
    """Expand the on-screen rectangle only when projected lines are off-screen.

    This changes the UI zoom only. It does not alter the Revit crop region or
    plan view range, and it keeps the existing visible context in the rectangle.
    """
    if not segments:
        return False
    try:
        if view.ViewType == DB.ViewType.ThreeD and view.IsPerspective:
            return 'unavailable'
        corners = list(ui_view.GetZoomCorners())
        if len(corners) < 2:
            return 'unavailable'
        right, up = view.RightDirection, view.UpDirection
        anchor = segments[0][0]

        def coordinates(point):
            dx, dy, dz = (point.X - anchor.X, point.Y - anchor.Y,
                          point.Z - anchor.Z)
            return (dx * right.X + dy * right.Y + dz * right.Z,
                    dx * up.X + dy * up.Y + dz * up.Z)

        visible = [coordinates(point) for point in corners]
        projected = [coordinates(point) for a, b, unused in segments
                     for point in (a, b)]
        if view.CropBoxActive:
            crop = view.CropBox
            crop_points = [crop.Transform.OfPoint(DB.XYZ(x, y, z))
                           for x in (crop.Min.X, crop.Max.X)
                           for y in (crop.Min.Y, crop.Max.Y)
                           for z in (crop.Min.Z, crop.Max.Z)]
            crop_uv = [coordinates(point) for point in crop_points]
            crop_u = [point[0] for point in crop_uv]
            crop_v = [point[1] for point in crop_uv]
            projected_u = [point[0] for point in projected]
            projected_v = [point[1] for point in projected]
            tolerance = 1.0 / 304.8
            if (min(projected_u) < min(crop_u) - tolerance or
                    max(projected_u) > max(crop_u) + tolerance or
                    min(projected_v) < min(crop_v) - tolerance or
                    max(projected_v) > max(crop_v) + tolerance):
                # Zooming cannot recover geometry excluded by the target crop.
                # Do not silently change a persistent project view setting.
                return 'crop'
        visible_u = [point[0] for point in visible]
        visible_v = [point[1] for point in visible]
        projected_u = [point[0] for point in projected]
        projected_v = [point[1] for point in projected]
        tolerance = 1.0 / 304.8
        if (min(projected_u) >= min(visible_u) - tolerance and
                max(projected_u) <= max(visible_u) + tolerance and
                min(projected_v) >= min(visible_v) - tolerance and
                max(projected_v) <= max(visible_v) + tolerance):
            return False

        low_u = min(min(visible_u), min(projected_u))
        high_u = max(max(visible_u), max(projected_u))
        low_v = min(min(visible_v), min(projected_v))
        high_v = max(max(visible_v), max(projected_v))
        margin = max((high_u - low_u) * 0.04,
                     (high_v - low_v) * 0.04, 10.0 / 304.8)
        first = anchor.Add(right.Multiply(low_u - margin)).Add(
            up.Multiply(low_v - margin))
        second = anchor.Add(right.Multiply(high_u + margin)).Add(
            up.Multiply(high_v + margin))
        ui_view.ZoomAndCenterRectangle(first, second)
        return True
    except Exception:
        return 'unavailable'
