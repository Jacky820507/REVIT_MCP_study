"""Geometry contracts: project XY, instance coordinates and cancellation."""
import importlib.util
import math
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

LIB = Path(__file__).resolve().parents[1] / 'MCP_Tools.extension' / 'lib'


class XYZ:
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = x, y, z

    def DistanceTo(self, other):
        return math.sqrt(sum((getattr(self, k) - getattr(other, k)) ** 2 for k in 'XYZ'))

    def Add(self, other):
        return XYZ(self.X + other.X, self.Y + other.Y, self.Z + other.Z)

    def Multiply(self, value):
        return XYZ(self.X * value, self.Y * value, self.Z * value)


class Element:
    Category = None
    Name = 'test'

    def __init__(self, eid, hidden=False):
        self.Id = types.SimpleNamespace(IntegerValue=eid)
        self.hidden = hidden

    def IsHidden(self, view):
        return self.hidden


class Curve:
    def Tessellate(self):
        return [XYZ(100, 200, 50), XYZ(110, 220, 50)]


class CurveElement(Element):
    GeometryCurve = Curve()


class Group(Element):
    def GetMemberIds(self):
        return self.members


class GeometryInstance:
    def GetInstanceGeometry(self):
        return [Curve()]


class ViewPlan:
    pass


class SourceTests(unittest.TestCase):
    def setUp(self):
        db = types.SimpleNamespace(XYZ=XYZ, Group=Group, Curve=Curve,
            CurveElement=CurveElement, GeometryInstance=GeometryInstance,
            PolyLine=type('PolyLine', (), {}), Solid=type('Solid', (), {}),
            Mesh=type('Mesh', (), {}), FilledRegion=type('FilledRegion', (), {}),
            TextNote=type('TextNote', (), {}), FamilyInstance=type('FamilyInstance', (), {}),
            Options=type('Options', (), {}), StorageType=types.SimpleNamespace(Integer=1),
            ViewType=types.SimpleNamespace(FloorPlan='floor', StructuralPlan='structural', ThreeD='3d'),
            PlanViewDirection=types.SimpleNamespace(Up='up', Down='down'),
            RenderNodeAction=types.SimpleNamespace(Proceed='proceed', Skip='skip'),
            IExportContext2D=type('IExportContext2D', (), {}),
            ViewPlan=ViewPlan)
        self.db = db
        autodesk = types.ModuleType('Autodesk')
        revit = types.ModuleType('Autodesk.Revit')
        revit.DB = db
        with patch.dict(sys.modules, {'Autodesk': autodesk, 'Autodesk.Revit': revit}):
            spec = importlib.util.spec_from_file_location('projection_source_under_test', LIB / 'group_projection_source.py')
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        self.projection_z = self.module.projection_z
        self.module.projection_z = lambda view: 1000
        self.reader = self.module.Reader(None, object(), (10, 20, 30))

    def test_projection_plane_uses_camera_facing_side_of_plan_range(self):
        top, bottom = object(), object()
        cut = object()
        self.db.PlanViewPlane = types.SimpleNamespace(
            TopClipPlane=top, BottomClipPlane=bottom, CutPlane=cut)
        # Elevation is relative to the level type's Elevation Base (survey
        # point here); clip planes use internal coordinates.
        level = types.SimpleNamespace(ProjectElevation=100.0, Elevation=100.0 + 199275 / 304.8)
        view_range = types.SimpleNamespace(
            GetLevelId=lambda requested: 7,
            GetOffset=lambda requested: {top: 8.0, bottom: 0.0, cut: 4.0}[requested])
        view = self.db.ViewPlan()
        view.GetViewRange = lambda: view_range
        view.Document = types.SimpleNamespace(GetElement=lambda eid: level)
        view.GenLevel = level
        view.ViewType = self.db.ViewType.FloorPlan
        view.ViewDirection = XYZ(0, 0, 1)
        inset = 25.0 / 304.8
        self.assertAlmostEqual(self.projection_z(view), 108.0 - inset)
        view.ViewDirection = XYZ(0, 0, -1)
        self.assertAlmostEqual(self.projection_z(view), 100.0 + inset)

    def test_structural_plan_looking_up_uses_bottom_side(self):
        top, bottom = object(), object()
        cut = object()
        self.db.PlanViewPlane = types.SimpleNamespace(
            TopClipPlane=top, BottomClipPlane=bottom, CutPlane=cut)
        level = types.SimpleNamespace(ProjectElevation=0.0)
        view = self.db.ViewPlan()
        view.ViewType = self.db.ViewType.StructuralPlan
        view.GetViewRange = lambda: types.SimpleNamespace(
            GetLevelId=lambda plane: 1,
            GetOffset=lambda plane: {top: 10.0, bottom: 2.0, cut: 6.0}[plane])
        view.Document = types.SimpleNamespace(GetElement=lambda eid: level)
        view.GenLevel = level
        view.GetTypeId = lambda: 2
        view.Document.GetElement = lambda eid: (level if eid == 1 else
            types.SimpleNamespace(PlanViewDirection=self.db.PlanViewDirection.Up))
        inset = 25.0 / 304.8
        self.assertAlmostEqual(self.projection_z(view), 2.0 + inset)

    def test_projection_auto_fits_only_when_segments_are_outside_canvas(self):
        self.module.projection_z = self.projection_z
        floorplan = self.db.ViewType.FloorPlan
        view = types.SimpleNamespace(ViewType=floorplan,
            RightDirection=XYZ(1, 0, 0), UpDirection=XYZ(0, 1, 0),
            CropBoxActive=False)
        calls = []
        ui_view = types.SimpleNamespace(
            GetZoomCorners=lambda: [XYZ(-10, -5, 0), XYZ(10, 5, 0)],
            ZoomAndCenterRectangle=lambda a, b: calls.append((a, b)))
        inside = [(XYZ(-2, 0, 0), XYZ(2, 0, 0), (255, 0, 0))]
        self.assertFalse(self.module.ensure_projection_visible(ui_view, view, inside))
        self.assertFalse(calls)
        outside = [(XYZ(-20, 0, 0), XYZ(20, 0, 0), (255, 0, 0))]
        self.assertTrue(self.module.ensure_projection_visible(ui_view, view, outside))
        self.assertEqual(len(calls), 1)
        first, second = calls[0]
        self.assertLess(first.X, -20)
        self.assertGreater(second.X, 20)
        self.assertLess(first.Y, -5)
        self.assertGreater(second.Y, 5)

    def test_projection_outside_crop_is_reported_without_changing_view(self):
        view = types.SimpleNamespace(ViewType=self.db.ViewType.FloorPlan,
            RightDirection=XYZ(1, 0, 0), UpDirection=XYZ(0, 1, 0),
            CropBoxActive=True)
        view.CropBox = types.SimpleNamespace(
            Min=XYZ(-5, -5, -1), Max=XYZ(5, 5, 1),
            Transform=types.SimpleNamespace(OfPoint=lambda point: point))
        calls = []
        ui_view = types.SimpleNamespace(
            GetZoomCorners=lambda: [XYZ(-50, -50, 0), XYZ(50, 50, 0)],
            ZoomAndCenterRectangle=lambda a, b: calls.append((a, b)))
        segments = [(XYZ(10, 0, 0), XYZ(20, 0, 0), (255, 0, 0))]
        self.assertEqual(self.module.ensure_projection_visible(ui_view, view, segments), 'crop')
        self.assertFalse(calls)

    def test_2d_export_context_keeps_only_selected_group_member_geometry(self):
        context_type = self.module.GroupExportContext2D
        first = self.module.Reader(None, object(), (255, 0, 0))
        second = self.module.Reader(None, object(), (0, 0, 255))
        context = context_type({101: 1, 202: 2}, {1: first, 2: second})
        start, end = XYZ(0, 0, 0), XYZ(5, 6, 0)

        self.assertEqual(context.OnElementBegin2D(
            types.SimpleNamespace(ElementId=types.SimpleNamespace(IntegerValue=101))), 'proceed')
        context.OnLineSegment(types.SimpleNamespace(StartPoint=start, EndPoint=end))
        context.OnElementEnd2D(None)

        self.assertEqual(context.OnElementBegin2D(
            types.SimpleNamespace(ElementId=types.SimpleNamespace(IntegerValue=202))), 'proceed')
        context.OnLineSegment(types.SimpleNamespace(StartPoint=start, EndPoint=end))
        context.OnElementEnd2D(None)

        self.assertEqual(context.OnElementBegin2D(
            types.SimpleNamespace(ElementId=types.SimpleNamespace(IntegerValue=303))), 'skip')
        context.OnLineSegment(types.SimpleNamespace(StartPoint=start, EndPoint=end))
        context.OnElementEnd2D(None)

        self.assertEqual(len(first.segments), 1)
        self.assertEqual(len(second.segments), 1)
        self.assertEqual(first.segments[0][2], (255, 0, 0))
        self.assertEqual(second.segments[0][2], (0, 0, 255))

    def test_diagnostic_is_independent_of_groups_and_centered(self):
        self.module.projection_z = self.projection_z
        top, cut, bottom = object(), object(), object()
        self.db.PlanViewPlane = types.SimpleNamespace(
            TopClipPlane=top, CutPlane=cut, BottomClipPlane=bottom)
        view = self.db.ViewPlan()
        view.RightDirection = XYZ(1, 0, 0)
        view.UpDirection = XYZ(0, 1, 0)
        level = types.SimpleNamespace(ProjectElevation=100)
        view.GetViewRange = lambda: types.SimpleNamespace(
            GetLevelId=lambda plane: 7,
            GetOffset=lambda plane: {top: 8, cut: 4, bottom: 0}[plane])
        view.Document = types.SimpleNamespace(GetElement=lambda eid: level)
        view.GenLevel = level
        segments = self.module.diagnostic_segments(view, (XYZ(-10, -10, 0), XYZ(10, 10, 0)))
        self.assertEqual(len(segments), 18)
        self.assertEqual({rgb for a, b, rgb in segments},
                         {(255, 0, 255), (0, 180, 0), (0, 110, 255)})
        self.assertTrue(all(100 < a.Z < 108 and a.Z == b.Z
                            for a, b, rgb in segments))

    def test_non_plan_view_projects_to_its_view_plane(self):
        view = types.SimpleNamespace(
            Origin=XYZ(100, 200, 300),
            ViewDirection=XYZ(0, 1, 0),
            IsTemplate=False)
        reader = self.module.Reader(None, view, (10, 20, 30))
        reader.curve(Curve())
        a, b, unused = reader.segments[0]
        offset = 100.0 / 304.8
        self.assertAlmostEqual(a.X, 100)
        self.assertAlmostEqual(a.Y, 200 + offset)
        self.assertAlmostEqual(a.Z, 50)
        self.assertAlmostEqual(b.X, 110)
        self.assertAlmostEqual(b.Y, 200 + offset)
        self.assertAlmostEqual(b.Z, 50)

    def test_target_view_validation_is_not_tied_to_drainage_plan_name(self):
        graphical_view = types.SimpleNamespace(
            Origin=XYZ(0, 0, 0), ViewDirection=XYZ(0, 0, 1), IsTemplate=False)
        self.assertIsNone(self.module.target_view_error(graphical_view))
        unusable_view = types.SimpleNamespace(IsTemplate=False)
        self.assertIn('視圖平面', self.module.target_view_error(unusable_view))

    def test_curve_keeps_project_xy_changes_only_z(self):
        self.reader.curve(Curve())
        a, b, rgb = self.reader.segments[0]
        self.assertEqual((a.X, a.Y, a.Z), (100, 200, 1000))
        self.assertEqual((b.X, b.Y, b.Z), (110, 220, 1000))
        self.assertEqual(rgb, (10, 20, 30))

    def test_instance_geometry_is_not_transformed_twice(self):
        self.reader.geometry([GeometryInstance()])
        self.assertEqual(self.reader.segments[0][0].X, 100)

    def test_nested_groups_visit_each_member_once(self):
        root, nested, line = Group(1), Group(2), CurveElement(3)
        root.members, nested.members = [2, 3], [3]
        self.reader.doc = types.SimpleNamespace(GetElement=lambda eid: {2: nested, 3: line}[eid])
        self.reader.element(root, object())
        self.assertEqual(self.reader.element_count, 1)
        self.assertEqual(len(self.reader.segments), 1)

    def test_hidden_group_skips_members(self):
        hidden = Group(1, hidden=True)
        hidden.members = [2]
        self.reader.element(hidden, object())
        self.assertFalse(self.reader.segments)
        self.assertEqual(self.reader.element_count, 0)

    def test_direction_parameters_keep_false_distinct_from_missing(self):
        param = types.SimpleNamespace(StorageType=1, AsInteger=lambda: 0)
        element = Element(4)
        element.LookupParameter = lambda name: param if name == 'UP' else None
        self.reader.symbol(element)
        self.assertIs(self.reader.symbols[0]['UP'], False)
        self.assertIsNone(self.reader.symbols[0]['DN'])

    def test_cancel_and_limit_abort_instead_of_silent_partial_result(self):
        self.reader.cancelled = lambda: True
        with self.assertRaises(self.module.ExtractionCancelled):
            self.reader.curve(Curve())
        self.reader.cancelled = lambda: False
        self.reader.max_segments = 0
        with self.assertRaises(self.module.SegmentLimit):
            self.reader.curve(Curve())

    def test_unsupported_element_is_reported(self):
        element = Element(7)
        element.get_Geometry = lambda options: None
        self.reader.element(element, object())
        self.assertFalse(self.reader.segments)
        self.assertTrue(self.reader.warnings)


if __name__ == '__main__':
    unittest.main()
