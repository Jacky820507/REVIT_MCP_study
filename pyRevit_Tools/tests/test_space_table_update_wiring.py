# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""真的執行「空間表 Excel」（``SpaceTableUpdate.pushbutton\\script.py``）。

## 這顆和其他每一顆都不一樣

它**沒有 ``main()`` 也沒有 lib 層的 ``run()``**：1290 行的流程全部寫在模組層的
一個 ``try`` 區塊裡。而且它被設計成可以被別人嵌入執行——``ScaffoldRooms`` 會

    space_update_result = {}
    execfile(space_update_script, {'_MCP_EMBEDDED_RESULT': space_update_result,
                                   '_TAKEOFF_OPTIONS': entry_options, ...})

然後從那個 dict 讀回 ``path`` / ``sheet`` / ``backup`` / ``error``。所以「驅動它」
就等於「執行它」，用的是 ``revit_stub.run_script``。

## 這支釘住的是那份 dict 的契約

``ScaffoldRooms`` 完全靠這幾個 key 決定要不要繼續跑施工架計算。少填一個、或是
把正常中止誤報成 error，室內施工架那顆就會無聲地不做事——而且症狀出現在另一顆
按鈕上，完全指不回這裡。

## 這支測不到什麼

真正的 Excel 比對與寫入（``xls_path`` 那條路要 COM）。房間收集的 Revit 端。
"""

import os
import shutil
import tempfile
import unittest

import revit_stub


SCRIPT = revit_stub.button_path('Takeoff.panel', 'SpaceTableUpdate')

ROOMS = [
    {'ElementId': 'host:101', 'Number': '101', 'Name': '辦公室',
     'Level': '1F', 'AreaM2': 48.0, 'PerimeterM': 28.0},
    {'ElementId': 'host:102', 'Number': '102', 'Name': '茶水間',
     'Level': '1F', 'AreaM2': 12.0, 'PerimeterM': 14.0},
]


class FakeRoomSources(object):
    """換掉 ``room_takeoff_sources``：只負責交出房間資料。"""

    def __init__(self, rooms):
        self.rooms = rooms
        self.calls = []

    def collect_selected_rooms(self, doc, entry_options):
        self.calls.append(entry_options)
        return {'Rooms': list(self.rooms), 'Sources': [('host', '主模型')]}


class SpaceTableUpdateWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='spacetable-')
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def execute(self, rooms=None, options=None, answers=None):
        """在嵌入模式下跑一次，回傳 (結果 dict, 假貨, 是否正常中止)。"""
        result = {}
        sources = FakeRoomSources(ROOMS if rooms is None else rooms)
        with revit_stub.install(answers=answers or {}) as stub:
            restore = revit_stub.install_module('room_takeoff_sources',
                                                sources)
            try:
                exited = False
                try:
                    revit_stub.run_script(SCRIPT, {
                        '_MCP_EMBEDDED_RESULT': result,
                        '_TAKEOFF_OPTIONS': (
                            {'workbook_path': None} if options is None
                            else options),
                    })
                except SystemExit:
                    # pyRevit 的 script.exit() 是 SystemExit，屬於正常中止
                    exited = True
            finally:
                restore()
            return result, stub, exited, sources

    # -- 嵌入模式的契約 ----------------------------------------------------

    def test_without_a_workbook_it_reports_the_data_and_stops_cleanly(self):
        """沒有主檔時交出 data 讓呼叫端自己決定——不能當成錯誤。"""
        result, stub, _exited, sources = self.execute()

        self.assertIsNone(result.get('path'))
        self.assertIsNone(result.get('sheet'))
        self.assertIsNone(result.get('backup'))
        self.assertFalse(result.get('updated'))
        self.assertIn('data', result, 'ScaffoldRooms 靠這份 data 往下算')
        self.assertEqual(ROOMS, result['data']['Rooms'])

        self.assertNotIn('error', result,
                         '正常中止被誤報成 error，室內施工架就不會跑了')
        self.assertNotIn('handled_error', result)

    def test_the_entry_options_are_passed_through_not_re_asked(self):
        """呼叫端已經問過來源／樓層了，這裡不該再跳一次共用入口。"""
        options = {'workbook_path': None, 'levels': ['1F']}
        _result, stub, _exited, sources = self.execute(options=options)

        self.assertEqual([options], sources.calls)
        self.assertEqual([], stub.forms.prompt_sequence,
                         '嵌入模式下不該再問使用者任何事')

    def test_no_placed_room_stops_without_filling_the_contract(self):
        """一間房都沒有時要中止；此時 dict 是空的，呼叫端會當成未完成。"""
        result, stub, exited, _sources = self.execute(rooms=[])

        self.assertTrue(exited, '沒有房間卻沒有中止')
        self.assertTrue(stub.forms.alerts)
        self.assertIn('沒有已放置', stub.forms.alerts[-1])
        self.assertFalse(result.get('path'))
        self.assertFalse(result.get('sheet'))

    def test_a_collection_failure_is_reported_through_the_dict(self):
        """出錯要走 dict 回報，不能在嵌入模式下自己跳對話框。"""
        class Exploding(object):
            def collect_selected_rooms(self, doc, entry_options):
                raise Exception('連結模型已卸載')

        result = {}
        with revit_stub.install(answers={}) as stub:
            restore = revit_stub.install_module('room_takeoff_sources',
                                                Exploding())
            try:
                try:
                    revit_stub.run_script(SCRIPT, {
                        '_MCP_EMBEDDED_RESULT': result,
                        '_TAKEOFF_OPTIONS': {'workbook_path': None},
                    })
                except SystemExit:
                    pass
            finally:
                restore()

        self.assertIn('連結模型已卸載', result.get('error', ''))
        self.assertEqual([], stub.forms.alerts,
                         '嵌入模式下不該自己跳對話框，錯誤要交回呼叫端')


if __name__ == '__main__':
    unittest.main()
