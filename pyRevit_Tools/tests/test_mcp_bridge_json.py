# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""mcp_bridge 在 IronPython 2.7 下送出中文參數的回歸測試。"""

import json
import os
import runpy
import sys
import types
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BRIDGE_PATH = os.path.join(ROOT, 'MCP_Tools.extension', 'lib',
                           'mcp_bridge.py')


def _load_bridge_globals():
    """在不載入 Revit/CLR 的情況下讀取 bridge 的純 Python 部分。"""
    missing = object()
    saved = {}
    for name in ('clr', 'pyrevit'):
        saved[name] = sys.modules.get(name, missing)

    clr = types.ModuleType('clr')
    clr.AddReference = lambda *args, **kwargs: None
    clr.AddReferenceToFileAndPath = lambda *args, **kwargs: None

    pyrevit = types.ModuleType('pyrevit')
    pyrevit.forms = object()
    pyrevit.HOST_APP = object()
    sys.modules['clr'] = clr
    sys.modules['pyrevit'] = pyrevit
    try:
        return runpy.run_path(BRIDGE_PATH,
                              run_name='mcp_bridge_encoding_test')
    finally:
        for name, value in saved.items():
            if value is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


BRIDGE = _load_bridge_globals()


class JsonEncodingTests(unittest.TestCase):
    def test_chinese_cloud_comments_round_trip_as_ascii_json(self):
        payload = {
            u'autoCommentPrefix': u'[自動]',
            u'clouds': [{
                u'sheetNumber': u'ARD-D02005',
                u'comment': u'[自動] F105｜修改：C5 → C8',
            }],
        }

        encoded = BRIDGE['_json_dumps_for_bridge'](payload)

        self.assertEqual(encoded, encoded.encode('ascii').decode('ascii'))
        self.assertEqual(payload, json.loads(encoded))

    def test_quotes_slashes_controls_and_nested_values_are_valid_json(self):
        payload = {
            u'text': u'引號"、斜線\\、換行\n與 tab\t\f',
            u'utf8Bytes': b'\xe8\x87\xaa',
            u'values': [None, True, False, 5, 2.5],
        }

        encoded = BRIDGE['_json_dumps_for_bridge'](payload)

        decoded = json.loads(encoded)
        self.assertEqual(payload[u'text'], decoded[u'text'])
        self.assertEqual(u'自', decoded[u'utf8Bytes'])
        self.assertEqual(payload[u'values'], decoded[u'values'])
        self.assertEqual(encoded, encoded.encode('ascii').decode('ascii'))

    def test_run_passes_a_dotnet_string_containing_only_ascii(self):
        class DotNetString(str):
            pass

        class ArrayFactory(object):
            def __getitem__(self, unused_type):
                return lambda values: list(values)

        system = types.ModuleType('System')
        system.String = DotNetString
        system.Object = object
        system.Array = ArrayFactory()

        models = types.ModuleType('RevitMCP.Models')

        class RevitCommandRequest(object):
            pass

        models.RevitCommandRequest = RevitCommandRequest
        revit_mcp = types.ModuleType('RevitMCP')
        revit_mcp.__path__ = []

        class ParseMethod(object):
            def __init__(self):
                self.arguments = None

            def Invoke(self, unused_target, arguments):
                self.arguments = arguments
                return object()

        parse = ParseMethod()

        class Response(object):
            Success = True
            Error = None
            Data = None

        class Executor(object):
            def ExecuteCommand(self, request):
                self.request = request
                return Response()

        executor = Executor()
        saved = {}
        for name, value in (('System', system), ('RevitMCP', revit_mcp),
                            ('RevitMCP.Models', models)):
            saved[name] = sys.modules.get(name)
            sys.modules[name] = value
        # runpy.run_path 會回傳一份 globals 複本；函式實際查找名稱時使用
        # ``__globals__``，所以 monkeypatch 必須套在那個字典上。
        runtime = BRIDGE['run'].__globals__
        old_ensure = runtime['_ensure_assembly']
        old_json_api = runtime['_get_json_api']
        old_executor = runtime['_get_executor']
        runtime['_ensure_assembly'] = lambda: None
        runtime['_get_json_api'] = lambda: (parse, None)
        runtime['_get_executor'] = lambda: executor
        try:
            runtime['run'](
                'create_revision_clouds_on_sheets',
                {'autoCommentPrefix': u'[自動]',
                 'comment': u'修改：C5 → C8'})
        finally:
            runtime['_ensure_assembly'] = old_ensure
            runtime['_get_json_api'] = old_json_api
            runtime['_get_executor'] = old_executor
            for name, value in saved.items():
                if value is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = value

        self.assertEqual(1, len(parse.arguments))
        self.assertIsInstance(parse.arguments[0], DotNetString)
        self.assertEqual(parse.arguments[0],
                         parse.arguments[0].encode('ascii').decode('ascii'))
        self.assertEqual({u'autoCommentPrefix': u'[自動]',
                          u'comment': u'修改：C5 → C8'},
                         json.loads(parse.arguments[0]))


if __name__ == '__main__':
    unittest.main()
