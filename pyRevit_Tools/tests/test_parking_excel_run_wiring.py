# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""真的執行「停車位 Excel」的 ``lib\\parking_excel.run()``。

形狀與機房門檻那顆相同：``ParkingExcelWindow`` 是接縫，之後分成「獨立匯出」
與「更新既有活頁簿」兩條路。差別是這顆在開視窗之前先 ``collect_levels(doc)``
（碰 Revit），而且**整個 run() 包在一個 try/except 裡**——所以「獨立匯出寫檔失敗」
不會有自己的訊息，會落到最外層的「執行失敗」。這支把那個行為也釘住。

``test_parking_excel.py`` 測的是產表邏輯，這支測接線，分工同前。
"""

import os
import shutil
import tempfile
import unittest
import zipfile

import takeoff_harness as harness


LIB = 'parking_excel'

TABLES = {
    'detail_headers': ['車位編號', '型式', '樓層'],
    'detail_rows': [['P-01', '標準', 'B1'], ['P-02', '機械', 'B1']],
    'formula_headers': ['項目', '計算式', '數量'],
    'formula_rows': [['標準車位', '=1+1', 2]],
    'audit_headers': ['檢核項目', '結果'],
    'audit_rows': [['來源', '連結模型']],
}


class FakeWindow(object):
    def __init__(self, result):
        self._result = result
        self.shown = 0

    def __call__(self, doc, levels, entry_options):
        self.levels = levels
        return self

    def ShowDialog(self):
        self.shown += 1

    @property
    def result(self):
        return self._result


class ParkingRunWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='parking-')
        self.outpath = os.path.join(self.tmpdir, '停車位.xlsx')
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.updates = []

    def make_run(self, result, answers=None, update=None, levels=None):
        """``result`` 可以是值，也可以是「吃 module 回傳 result」的函式。"""
        self.last_result = {}

        def patches(module):
            value = result(module) if callable(result) else result
            self.last_result = value
            patched = {
                'collect_levels': lambda doc: levels or ['B1', 'B2'],
                'ParkingExcelWindow': FakeWindow(value),
            }
            if update is not None:
                patched['update_workbook'] = update
            return patched

        return harness.LibRun(LIB, self.tmpdir, answers or {},
                              patches=patches)

    def standalone_result(self):
        return {'mode': 'standalone', 'tables': dict(TABLES)}

    def update_result(self, module):
        """車位種類直接取自模組的 ITEMS——寫死的話那份清單一改，這裡就過期。"""
        counts = dict((item['key'], 2) for item in module.logic.ITEMS)
        return {
            'mode': 'update',
            'path': os.path.join(self.tmpdir, '主要.xlsx'),
            'inspection': {'target_address': "'小計'!D8",
                           'rows': {'wheel_stop': 12}},
            'takeoff': {'counts': counts},
            'multiplier': 2.0,
            'selected_link_ids': [7],
        }

    # -- 取消 --------------------------------------------------------------

    def test_no_result_means_cancelled(self):
        with self.make_run(None) as run:
            run.run(run.stub.doc, {})
            self.assertEqual([], run.prompts)
            self.assertEqual([], run.stub.forms.alerts)
        self.assertEqual([], os.listdir(self.tmpdir))

    def test_levels_are_collected_before_the_window_opens(self):
        """視窗要靠樓層清單建，先後順序反了視窗就是空的。"""
        window_holder = {}

        def patches(module):
            window = FakeWindow(None)
            window_holder['w'] = window
            return {'collect_levels': lambda doc: ['B3', 'B4'],
                    'ParkingExcelWindow': window}

        run = harness.LibRun(LIB, self.tmpdir, {}, patches=patches)
        with run:
            run.run(run.stub.doc, {})
        self.assertEqual(['B3', 'B4'], window_holder['w'].levels)

    # -- 獨立匯出 ----------------------------------------------------------

    def test_standalone_export_writes_a_real_workbook(self):
        with self.make_run(self.standalone_result(),
                           answers={'save_file': self.outpath}) as run:
            run.run(run.stub.doc, {})
            alerts = run.stub.forms.alerts

        self.assertTrue(zipfile.is_zipfile(self.outpath))
        with zipfile.ZipFile(self.outpath) as archive:
            names = archive.namelist()
        self.assertEqual(sorted(set(names)), sorted(names))
        self.assertEqual(
            3, len([n for n in names if n.startswith('xl/worksheets/sheet')]))
        self.assertTrue(alerts)
        self.assertIn('匯出完成', alerts[-1])
        self.assertIn(self.outpath, alerts[-1])

    def test_cancelling_the_standalone_save_writes_nothing(self):
        with self.make_run(self.standalone_result(),
                           answers={'save_file': None}) as run:
            run.run(run.stub.doc, {})
            self.assertEqual([], run.stub.forms.alerts)
        self.assertEqual([], os.listdir(self.tmpdir))

    def test_missing_extension_is_appended(self):
        bare = os.path.join(self.tmpdir, '沒有副檔名')
        with self.make_run(self.standalone_result(),
                           answers={'save_file': bare}) as run:
            run.run(run.stub.doc, {})
        self.assertTrue(os.path.exists(bare + '.xlsx'))

    def test_a_standalone_write_failure_falls_to_the_outer_handler(self):
        """這顆沒有內層 try，寫檔失敗會變成「執行失敗」——確認它至少有被接住。"""
        broken = self.standalone_result()
        broken['tables']['detail_rows'] = None
        with self.make_run(broken,
                           answers={'save_file': self.outpath}) as run:
            run.run(run.stub.doc, {})
            alerts = run.stub.forms.alerts
        self.assertTrue(alerts, '寫檔失敗卻沒有任何提示')
        self.assertIn('執行失敗', alerts[-1])

    # -- 更新既有活頁簿 ----------------------------------------------------

    def test_declining_the_confirmation_updates_nothing(self):
        with self.make_run(self.update_result,
                           answers={'alert_yes_no': False},
                           update=self._record()) as run:
            run.run(run.stub.doc, {})
            self.assertEqual([], self.updates)
            self.assertEqual([], run.stub.forms.alerts)

    def test_confirming_passes_the_backup_and_multiplier_down(self):
        with self.make_run(self.update_result,
                           answers={'alert_yes_no': True},
                           update=self._record()) as run:
            run.run(run.stub.doc, {})
            alerts = run.stub.forms.alerts
        result = self.last_result

        self.assertEqual(1, len(self.updates))
        path, inspection, counts, multiplier, backup = self.updates[0]
        self.assertEqual(result['path'], path)
        self.assertEqual(result['takeoff']['counts'], counts)
        self.assertEqual(result['multiplier'], multiplier)
        self.assertTrue(backup)
        self.assertNotEqual(result['path'], backup)
        self.assertIn('更新完成', alerts[-1])
        self.assertIn(backup, alerts[-1])

    def test_a_failed_update_becomes_a_readable_alert(self):
        def boom(*args, **kwargs):
            raise Exception('分頁被鎖住')

        with self.make_run(self.update_result,
                           answers={'alert_yes_no': True},
                           update=boom) as run:
            run.run(run.stub.doc, {})
            alerts = run.stub.forms.alerts
        self.assertIn('執行失敗', alerts[-1])
        self.assertIn('分頁被鎖住', alerts[-1])

    def _record(self):
        def record(*args):
            self.updates.append(args)
        return record


if __name__ == '__main__':
    unittest.main()
