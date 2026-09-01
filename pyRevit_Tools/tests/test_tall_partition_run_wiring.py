# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""真的執行「高隔間分析 Excel」的 ``lib\\tall_partition_excel.run()``。

## 為什麼另開一支

高隔間這顆是**薄殼按鈕**：``TallPartitionExcel.pushbutton\\script.py`` 只有 23 行，
確認 ``revit.doc`` 之後就把事情交給 ``tall_partition_excel.run(doc)``。它沒有
``main()`` 可以拆，要驅動的是 lib 模組的 ``run()``——``takeoff_harness.LibRun``
就是為這種按鈕做的。

``test_tall_partition.py`` 測的是 ``tall_partition_logic``（純函式），跟這支的分工
和 ``test_rc_volume`` ↔ ``test_rc_volume_main_wiring`` 一樣：那支測算式，這支測接線。

## 這支涵蓋什麼

``run()`` 的接縫是 **MCP 呼叫**（``mcp.run('analyze_tall_partition_rooms', ...)``）
而不是 Revit collector，所以換掉的是 ``mcp.run``。涵蓋：送出的參數對不對、三條
提早 return 的路（橋接失敗／回傳不成功／沒有符合的牆）、真的寫出來的三分頁活頁簿，
以及結束時的摘要訊息。

## 這支測不到什麼

MCP 橋接本身（那一頭是 Revit 外掛）。以及 Excel 實際開啟後的行為。
"""

import os
import shutil
import tempfile
import unittest
import zipfile

import takeoff_harness as harness
from takeoff_harness import read_sheets
from test_tall_partition import SAMPLE


LIB = 'tall_partition_excel'


class TallPartitionRunWiringTests(unittest.TestCase):
    # 「不傳」與「傳 None（＝使用者按取消）」是兩件事，用哨兵分開
    _DEFAULT = object()

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='tallpart-')
        self.outpath = os.path.join(self.tmpdir, '高隔間.xlsx')
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.mcp_calls = []

    def make_run(self, mcp_result=_DEFAULT, save_to=_DEFAULT):
        result = SAMPLE if mcp_result is self._DEFAULT else mcp_result
        answers = {'save_file': (self.outpath if save_to is self._DEFAULT
                                 else save_to)}
        return harness.LibRun(LIB, self.tmpdir, answers,
                              patches={'mcp.run': self._returner(result)})

    # -- 端對端 ------------------------------------------------------------

    def test_run_writes_a_three_sheet_workbook(self):
        with self.make_run() as run:
            run.run(run.stub.doc)
        self.assertTrue(os.path.exists(self.outpath))
        self.assertTrue(zipfile.is_zipfile(self.outpath))
        with zipfile.ZipFile(self.outpath) as archive:
            names = archive.namelist()
        self.assertEqual(sorted(set(names)), sorted(names),
                         'xlsx 內有重複的 part，Excel 開檔會要求修復')
        self.assertEqual(3, len(read_sheets(self.outpath)),
                         '牆／房間／檢核條件三個分頁')

    def test_the_mcp_call_carries_the_threshold_and_flags(self):
        """送錯參數不會報錯，只會拿回一批不該進表的牆。"""
        with self.make_run() as run:
            run.run(run.stub.doc)
            module = run.module
        self.assertEqual(1, len(self.mcp_calls))
        command, payload = self.mcp_calls[0]
        self.assertEqual('analyze_tall_partition_rooms', command)
        self.assertEqual(module.THRESHOLD_MM, payload['minWallHeightMm'])
        self.assertTrue(payload['autoDetectLevels'])
        self.assertTrue(payload['includeDetails'])
        self.assertTrue(payload['includeRoomRayHeight'])

    def test_the_final_alert_reports_the_same_counts_as_the_sheets(self):
        with self.make_run() as run:
            run.run(run.stub.doc)
            module = run.module
            alerts = run.stub.forms.alerts
            shaped = module.logic.build_workbook_data(SAMPLE)
        self.assertTrue(alerts, '跑完要有一個完成通知')
        self.assertIn(self.outpath, alerts[-1], '通知要說檔案寫到哪裡')
        self.assertIn('{0}'.format(shaped['wall_count']), alerts[-1])

    # -- 三條提早 return 的路 ----------------------------------------------

    def test_a_bridge_error_stops_before_asking_where_to_save(self):
        def patches(module):
            # MCPBridgeError 這個類別要載入之後才拿得到，所以用可呼叫的 patches
            error = module.mcp.MCPBridgeError('Revit 沒有回應')
            return {'mcp.run': self._raiser(error)}

        run = harness.LibRun(LIB, self.tmpdir, {'save_file': self.outpath},
                             patches=patches)
        with run:
            run.run(run.stub.doc)
            self.assertNotIn('save_file', run.prompts,
                             '橋接就失敗了還跳存檔對話框')
        self.assertFalse(os.path.exists(self.outpath))

    def test_an_unsuccessful_result_stops_before_writing(self):
        with self.make_run(mcp_result={'Success': False}) as run:
            run.run(run.stub.doc)
            self.assertTrue(run.stub.forms.alerts)
            self.assertIn('未成功', run.stub.forms.alerts[-1])
            self.assertNotIn('save_file', run.prompts)
        self.assertFalse(os.path.exists(self.outpath))

    def test_no_qualifying_wall_says_so_and_writes_nothing(self):
        """一面牆都不符合時要明講，不能沉默地產出一張空表。"""
        empty = dict(SAMPLE, Walls=[])
        with self.make_run(mcp_result=empty) as run:
            run.run(run.stub.doc)
            self.assertTrue(run.stub.forms.alerts)
            self.assertIn('找不到', run.stub.forms.alerts[-1])
            self.assertNotIn('save_file', run.prompts)
        self.assertFalse(os.path.exists(self.outpath))

    def test_cancelling_the_save_dialog_writes_nothing(self):
        run = harness.LibRun(LIB, self.tmpdir, {'save_file': None},
                             patches={'mcp.run': self._returner(SAMPLE)})
        with run:
            run.run(run.stub.doc)
            self.assertEqual([], run.stub.forms.alerts,
                             '使用者取消了，不該再跳完成通知')
        self.assertEqual([], os.listdir(self.tmpdir))

    # -- 小工具 ------------------------------------------------------------

    @staticmethod
    def _raiser(error):
        def raise_it(*args, **kwargs):
            raise error
        return raise_it

    def _returner(self, result):
        calls = self.mcp_calls

        def run_it(command, payload=None, **kwargs):
            calls.append((command, payload))
            return result
        return run_it


if __name__ == '__main__':
    unittest.main()
