"""Exercise DC3D allocation, lifecycle and failure paths without Revit."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class XYZ:
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = x, y, z


class Outline:
    def __init__(self, low, high):
        assert low.X <= high.X and low.Y <= high.Y and low.Z <= high.Z
        self.MinimumPoint, self.MaximumPoint = low, high


class Document:
    IsValidObject = True

    def Equals(self, other):
        return self is other


class IdList(list):
    def Add(self, value):
        self.append(value)

    def Contains(self, value):
        return value in self


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.resources = []
        self.flushes = []
        self.rendering = False
        self.fail_vertex = False
        self.fail_remove = False
        self.fail_activate = False
        self.transparent = False
        self.clip_planes = []
        case = self

        class Resource:
            def __init__(self, capacity):
                assert case.rendering, 'graphics allocation outside RenderScene'
                self.capacity = capacity
                self.valid = True
                self.disposed = False
                self.mapped = False
                self.items = []
                case.resources.append(self)

            def Map(self, capacity):
                assert case.rendering and capacity == self.capacity
                self.mapped = True

            def Unmap(self):
                assert self.mapped
                self.mapped = False

            def IsValid(self):
                assert case.rendering
                return self.valid and not self.disposed

            def Dispose(self):
                assert not self.mapped
                case.events.append('dispose')
                self.disposed = True

            def GetVertexStreamPositionColored(self):
                return self

            def GetIndexStreamLine(self):
                return self

            def AddVertex(self, vertex):
                if case.fail_vertex:
                    raise RuntimeError('vertex failure')
                self.items.append(vertex)

            def AddLine(self, line):
                self.items.append(line)

        class Vertex:
            GetSizeInFloats = staticmethod(lambda: 7)

            def __init__(self, point, color):
                self.point, self.color = point, color

        class Line:
            GetSizeInShortInts = staticmethod(lambda: 2)

            def __init__(self, a, b):
                self.a, self.b = a, b

        class Service:
            def __init__(self):
                self.servers = {}
                self.active = IdList(['other-server'])

            def IsRegisteredServerId(self, guid):
                return guid in self.servers

            def GetServer(self, guid):
                return self.servers.get(guid)

            def AddServer(self, server):
                assert server.GetServerId() not in self.servers
                self.servers[server.GetServerId()] = server

            def RemoveServer(self, guid):
                if case.fail_remove:
                    raise RuntimeError('remove failure')
                case.events.append('deregister')
                del self.servers[guid]
                self.active = IdList(x for x in self.active if x != guid)

            def GetActiveServerIds(self):
                return IdList(self.active)

            def SetActiveServers(self, active):
                if case.fail_activate:
                    raise RuntimeError('activate failure')
                self.active = active

        self.service = Service()
        dc3d = types.SimpleNamespace(
            IDirectContext3DServer=object, VertexBuffer=Resource,
            IndexBuffer=Resource, VertexFormat=Resource, EffectInstance=Resource,
            VertexFormatBits=types.SimpleNamespace(PositionColored=1),
            PrimitiveType=types.SimpleNamespace(LineList=2),
            VertexPositionColored=Vertex, IndexLine=Line,
            DrawContext=types.SimpleNamespace(
                IsTransparentPass=lambda: case.transparent,
                GetClipPlanes=lambda: case.clip_planes,
                SetWorldTransform=lambda transform: case.events.append('identity transform'),
                FlushBuffer=lambda *args: case.flushes.append(args)))
        es = types.SimpleNamespace(
            ExternalServices=types.SimpleNamespace(
                BuiltInExternalServices=types.SimpleNamespace(DirectContext3DService=3)),
            ExternalServiceRegistry=types.SimpleNamespace(GetService=lambda _: self.service))
        db = types.SimpleNamespace(XYZ=XYZ, Outline=Outline,
                                   Transform=types.SimpleNamespace(Identity=object()),
                                   ColorWithTransparency=lambda *rgb: rgb)
        guid = type('Guid', (str,), {'NewGuid': staticmethod(lambda: object())})
        source = Path(__file__).resolve().parents[1] / 'MCP_Tools.extension' / 'lib' / 'group_projection_server.py'
        spec = importlib.util.spec_from_file_location('_projection_test_target', source)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
                'System': types.SimpleNamespace(Guid=guid),
                'pyrevit': types.SimpleNamespace(DB=db),
                'pyrevit.api': types.SimpleNamespace(DirectContext3D=dc3d, ExternalService=es)}):
            spec.loader.exec_module(self.module)
        self.doc = Document()
        self.view = types.SimpleNamespace(Document=self.doc, Id=types.SimpleNamespace(IntegerValue=42),
                                          IsValidObject=True)
        self.segment = (XYZ(9, -2, 7), XYZ(-3, 8, 1), (10, 20, 30))

    def server(self, segments=None):
        return self.module.ProjectionServer(self.doc, self.view.Id,
                                             [self.segment] if segments is None else segments)

    def render(self, server):
        self.rendering = True
        try:
            server.RenderScene(self.view, 0)
        finally:
            self.rendering = False

    def test_chunk_capacity_counts_indices_and_cache(self):
        server = self.server([self.segment] * 16001)
        self.assertEqual(self.resources, [])
        self.render(server)
        self.assertEqual(server.error, '')
        self.assertEqual([args[8] for args in self.flushes], [16000, 1])
        self.assertEqual(server.flush_calls, 2)
        for args in self.flushes:
            vb, vertices, ib, indices = args[:4]
            self.assertEqual(vertices, args[8] * 2)
            self.assertEqual(vb.capacity, vertices * 7)
            self.assertEqual(indices, args[8] * 2)
            self.assertEqual(ib.capacity, indices)
            self.assertEqual(ib.items[-1].b, vertices - 1)
            self.assertLess(ib.items[-1].b, 32768)
        allocated = len(self.resources)
        self.render(server)
        self.assertEqual(len(self.resources), allocated)
        self.assertEqual(server.flush_calls, 4)

    def test_each_invalid_resource_rebuilds(self):
        for index in range(4):
            server = self.server()
            self.render(server)
            old = self.resources[-4:]
            old[index].valid = False
            self.render(server)
            self.assertTrue(all(r.disposed for r in old))
            self.assertEqual(server.error, '')

    def test_exact_scope_enabled_and_empty(self):
        server = self.server([])
        self.assertTrue(server.CanExecute(self.view))
        wrong = types.SimpleNamespace(Document=Document(), Id=self.view.Id, IsValidObject=True)
        self.assertFalse(server.CanExecute(wrong))
        wrong.Document, wrong.Id = self.doc, 99
        self.assertFalse(server.CanExecute(wrong))
        self.render(server)
        self.assertEqual(self.resources, [])
        self.assertIsNone(server.GetBoundingBox(self.view))
        server.enabled = False
        self.assertFalse(server.CanExecute(self.view))

    def test_snapshot_sorted_bounds_and_null_view(self):
        incoming = [self.segment]
        server = self.server(incoming)
        incoming.clear()
        self.segment[0].X = 900
        bounds = server.GetBoundingBox(None)
        pad = 10.0 / 304.8
        for actual, expected in zip(
                (bounds.MinimumPoint.X, bounds.MinimumPoint.Y, bounds.MinimumPoint.Z),
                (-3 - pad, -2 - pad, 1 - pad)):
            self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(
                (bounds.MaximumPoint.X, bounds.MaximumPoint.Y, bounds.MaximumPoint.Z),
                (9 + pad, 8 + pad, 7 + pad)):
            self.assertAlmostEqual(actual, expected)

    def test_render_diagnostics_distinguish_matching_views(self):
        server = self.server()
        wrong = types.SimpleNamespace(Document=Document(), Id=self.view.Id,
                                      IsValidObject=True)
        self.render(server)
        self.rendering = True
        try:
            server.RenderScene(wrong, 0)
        finally:
            self.rendering = False
        self.assertEqual(server.render_calls, 2)
        self.assertEqual(server.matching_render_calls, 1)
        self.assertGreaterEqual(server.can_execute_calls, 2)

    def test_clip_report_includes_signed_distance_of_projected_bounds(self):
        self.clip_planes = [types.SimpleNamespace(
            Origin=XYZ(0, 0, 0), Normal=XYZ(0, 0, 1))]
        server = self.server()
        self.render(server)
        self.assertIn('裁切平面 1 個', server.clip_report)
        self.assertIn('群組範圍距離 305～2134 mm', server.clip_report)

    def test_replacement_preserves_others_and_old_cleanup_cannot_remove_new(self):
        old = self.server()
        self.assertTrue(old.add_server())
        self.render(old)
        new = self.server()
        self.assertTrue(new.add_server())
        self.assertEqual(self.events[-5], 'deregister')
        self.assertTrue(all(r.disposed for r in self.resources))
        self.assertFalse(old.enabled)
        self.assertTrue(old.remove_server())
        self.assertIs(self.service.GetServer(new.GetServerId()), new)
        self.assertTrue(new.add_server())
        self.assertEqual(self.service.active, ['other-server', new.GetServerId()])
        self.assertTrue(new.remove_server())
        self.assertEqual(self.service.active, ['other-server'])

    def test_failed_deregistration_keeps_buffers_until_retry(self):
        server = self.server()
        server.add_server()
        self.render(server)
        self.fail_remove = True
        self.assertFalse(server.remove_server())
        self.assertIn('remove failure', server.error)
        self.assertFalse(any(r.disposed for r in self.resources))
        self.fail_remove = False
        self.assertTrue(server.remove_server())
        self.assertTrue(all(r.disposed for r in self.resources))

    def test_partial_build_unmaps_disposes_and_reports(self):
        server = self.server()
        self.fail_vertex = True
        self.render(server)
        self.assertIn('vertex failure', server.error)
        self.assertTrue(all(r.disposed and not r.mapped for r in self.resources))
        self.assertEqual(self.flushes, [])
        self.fail_vertex = False
        self.render(server)
        self.assertEqual(server.error, '')
        self.assertEqual(len(self.flushes), 1)

    def test_activation_failure_rolls_back_only_own_registration(self):
        server = self.server()
        self.fail_activate = True
        self.assertFalse(server.add_server())
        self.assertIn('activate failure', server.error)
        self.assertFalse(server.enabled)
        self.assertEqual(self.service.servers, {})
        self.assertEqual(self.service.active, ['other-server'])

    def test_transparent_pass_is_not_drawn(self):
        server = self.server()
        self.assertFalse(server.UseInTransparentPass(self.view))
        self.transparent = True
        self.render(server)
        self.assertEqual(self.resources, [])


if __name__ == '__main__':
    unittest.main()
