"""Test actual event methods in isolation; XAML must bind existing handlers."""
import ast
from pathlib import Path
import types
import unittest
import xml.etree.ElementTree as ET

LIB = Path(__file__).resolve().parents[1] / 'MCP_Tools.extension' / 'lib'
TREE = ast.parse((LIB / 'group_projection_window.py').read_text(encoding='utf-8'))


def method(class_name, name, namespace):
    cls = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    code = ast.Module(body=[fn], type_ignores=[])
    scope = dict(namespace)
    exec(compile(ast.fix_missing_locations(code), 'group_projection_window.py', 'exec'), scope)
    return scope[name]


class WindowTests(unittest.TestCase):
    def test_xaml_events_have_handlers_and_named_controls_are_unique(self):
        tree = ET.parse(LIB / 'GroupProjection.xaml')
        cls = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'ProjectionWindow')
        methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
        names = []
        for node in tree.iter():
            for event in ('Click', 'TextChanged', 'SelectionChanged'):
                if event in node.attrib:
                    self.assertIn(node.attrib[event], methods)
            name = node.attrib.get('{http://schemas.microsoft.com/winfx/2006/xaml}Name')
            if name:
                names.append(name)
        self.assertEqual(len(names), len(set(names)))
        self.assertNotIn('diagnosticButton', names)

    def handler_fixture(self, same_doc=True, same_view=True):
        calls = []
        window = types.SimpleNamespace(closed=False, doc=object(), view_id=11,
            status=types.SimpleNamespace(Text=''), report=types.SimpleNamespace(Text=''),
            controls=lambda value: calls.append(('controls', value)),
            load=lambda uidoc: calls.append('load'),
            project=lambda uidoc: calls.append('project'), cleanup=lambda: calls.append('cleanup'))
        uidoc = types.SimpleNamespace(Document=types.SimpleNamespace(Equals=lambda other: same_doc),
                                     ActiveView=types.SimpleNamespace(Id=11 if same_view else 12))
        handler = types.SimpleNamespace(window=window, action='apply')
        execute = method('Handler', 'Execute', {'source': types.SimpleNamespace(
            id_value=lambda eid: eid, ExtractionCancelled=type('Cancelled', (Exception,), {}))})
        return execute, handler, types.SimpleNamespace(ActiveUIDocument=uidoc), calls

    def test_apply_reloads_new_document_and_retargets_changed_view(self):
        execute, handler, app, calls = self.handler_fixture(False, True)
        execute(handler, app)
        self.assertEqual(calls.count('load'), 1)
        self.assertNotIn('project', calls)

        execute, handler, app, calls = self.handler_fixture(True, False)
        execute(handler, app)
        self.assertLess(calls.index('load'), calls.index('project'))
        execute, handler, app, calls = self.handler_fixture()
        execute(handler, app)
        self.assertIn('project', calls)

    def test_diagnostic_runs_without_group_selection(self):
        execute, handler, app, calls = self.handler_fixture()
        handler.action = 'diagnostic'
        handler.window.diagnostic = lambda uidoc: calls.append('diagnostic')
        execute(handler, app)
        self.assertIn('diagnostic', calls)
        self.assertNotIn('project', calls)

    def test_closed_window_does_not_read_model_and_cleans_once(self):
        execute, handler, app, calls = self.handler_fixture()
        handler.window.closed = True
        execute(handler, object())  # no ActiveUIDocument: must not be accessed
        self.assertEqual(calls.count('cleanup'), 1)
        self.assertNotIn('project', calls)

    def test_model_change_disables_snapshot_and_requires_reload(self):
        window = types.SimpleNamespace(closed=False, doc=types.SimpleNamespace(Equals=lambda d: True),
            server=types.SimpleNamespace(enabled=True), status=types.SimpleNamespace(Text=''))
        changed = method('ProjectionWindow', 'on_document_changed', {})
        changed(window, None, types.SimpleNamespace(GetDocument=lambda: window.doc))
        self.assertFalse(window.server.enabled)
        self.assertTrue(window.needs_reload)

    def test_disabled_projection_does_not_report_old_calls_as_live(self):
        point = lambda x, y, z: types.SimpleNamespace(X=x, Y=y, Z=z)
        server = types.SimpleNamespace(enabled=False, render_calls=79,
            matching_render_calls=79, bounding_box_calls=3, can_execute_calls=1651,
            view_id=8585012, error='', _bounds=(point(0, 0, 20), point(10, 10, 20)))
        window = types.SimpleNamespace(server=server, renderStatus=types.SimpleNamespace(Text=''))
        tick = method('ProjectionWindow', 'on_tick', {})
        tick(window, None, None)
        self.assertIn('目前投影已停用', window.renderStatus.Text)
        self.assertIn('停用前的舊計數', window.renderStatus.Text)

    def test_normal_projection_surfaces_clip_plane_report(self):
        point = lambda x, y, z: types.SimpleNamespace(X=x, Y=y, Z=z)
        server = types.SimpleNamespace(enabled=True, render_calls=28,
            matching_render_calls=28, flush_calls=28, bounding_box_calls=0,
            can_execute_calls=140, view_id=695, error='',
            clip_report='裁切平面 1 個。距離範圍 -10～20 mm。',
            _bounds=(point(-15, -1, 18), point(15, 12, 18)))
        window = types.SimpleNamespace(server=server, diagnostic_report=None,
            projection_report='來源 FL1，249 線段。',
            report=types.SimpleNamespace(Text='來源 FL1，249 線段.'),
            renderStatus=types.SimpleNamespace(Text=''))
        method('ProjectionWindow', 'on_tick', {})(window, None, None)
        self.assertIn('來源 FL1，249 線段。', window.report.Text)
        self.assertIn('裁切平面 1 個', window.report.Text)
        self.assertIn('FlushBuffer 28 次', window.renderStatus.Text)

    def test_closing_disables_before_queuing_removal(self):
        calls = []
        window = types.SimpleNamespace(server=types.SimpleNamespace(enabled=True),
            timer=types.SimpleNamespace(Stop=lambda: calls.append('stop')),
            handler=types.SimpleNamespace(action=None), app=object())
        window.event = types.SimpleNamespace(Raise=lambda: calls.append(window.server.enabled))
        method('ProjectionWindow', 'on_closed', {})(window, None, None)
        self.assertTrue(window.closed)
        self.assertEqual(window.handler.action, 'close')
        self.assertEqual(calls, ['stop', False])


    def test_project_level_checks_only_that_level_then_applies(self):
        check = lambda: types.SimpleNamespace(IsChecked=True)
        checks = [(check(), {'level': '2F'}), (check(), {'level': '3F'}), (check(), {'level': '3F'})]
        applied = []
        window = types.SimpleNamespace(checks=checks, status=types.SimpleNamespace(Text=''),
            selected_level=lambda: '3F', apply_clicked=lambda s, a: applied.append(True))
        method('ProjectionWindow', 'project_level_clicked', {'ALL_LEVELS': None})(window, None, None)
        self.assertEqual([c.IsChecked for c, r in checks], [False, True, True])
        self.assertEqual(applied, [True])

        window.selected_level = lambda: None
        applied[:] = []
        method('ProjectionWindow', 'project_level_clicked', {'ALL_LEVELS': None})(window, None, None)
        self.assertEqual(applied, [])
        self.assertIn('來源樓層', window.status.Text)

if __name__ == '__main__':
    unittest.main()
