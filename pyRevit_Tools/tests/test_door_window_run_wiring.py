# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""真的執行「門窗表 Excel」的 ``lib\\door_window_window.run()``。

形狀與機房門檻、停車位相同：``DoorWindowWindow`` 是接縫，之後分成「獨立匯出」
與「更新既有活頁簿」兩條路。更新那條走 ``door_window_excel``（程式碼裡叫 ``core``）
的 ``update_workbook``。

這顆的更新訊息有一句承諾——**「不建立門窗表或額外稽核分頁」「只修改小計」**——
那是對使用者活頁簿的保證，所以確認對話框的內容一併釘住。
"""

import os
import shutil
import tempfile
import unittest
import zipfile

import takeoff_harness as harness


LIB = 'door_window_window'

TABLES = {
    'detail_headers': ['編號', '寬 (m)', '高 (m)'],
    'detail_rows': [['D1', 0.9, 2.1], ['W1', 1.8, 1.2]],
    'formula_headers': ['項目', '計算式', '數量'],
    'formula_rows': [['金屬門窗', '=1+1', 2]],
    'audit_headers': ['檢核項目', '結果'],
    'audit_rows': [['來源', '主模型']],
}


class FakeWindow(object):
    def __init__(self, result):
        self._result = result
        self.shown = 0

    def __call__(self, doc, entry_options):
        self.entry_options = entry_options
        return self

    def ShowDialog(self):
        self.shown += 1

    @property
    def result(self):
        return self._result


class DoorWindowRunWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='dw-')
        self.outpath = os.path.join(self.tmpdir, '門窗表.xlsx')
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.updates = []

    def make_run(self, result, answers=None, update=None):
        def patches(module):
            patched = {'DoorWindowWindow': FakeWindow(result)}
            if update is not None:
                patched['core.update_workbook'] = update
            return patched

        return harness.LibRun(LIB, self.tmpdir, answers or {},
                              patches=patches)

    def standalone_result(self):
        return {'mode': 'standalone', 'tables': dict(TABLES),
                'takeoff': {'total': 2}}

    def update_result(self):
        return {
            'mode': 'update',
            'path': os.path.join(self.tmpdir, '主要.xlsx'),
            'total': 2,
            'plan': {'updates': [{'row': 8, 'value': 1},
                                 {'row': 9, 'value': 1}]},
        }

    # -- 取消 --------------------------------------------------------------

    def test_no_result_means_cancelled(self):
        with self.make_run(None) as run:
            run.run(run.stub.doc, {})
            self.assertEqual([], run.prompts)
            self.assertEqual([], run.stub.forms.alerts)
        self.assertEqual([], os.listdir(self.tmpdir))

    def test_the_entry_options_reach_the_window(self):
        holder = {}

        def patches(module):
            window = FakeWindow(None)
            holder['w'] = window
            return {'DoorWindowWindow': window}

        run = harness.LibRun(LIB, self.tmpdir, {}, patches=patches)
        with run:
            run.run(run.stub.doc, {'workbook_path': 'X.xlsx'})
        self.assertEqual({'workbook_path': 'X.xlsx'},
                         holder['w'].entry_options)

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
        self.assertIn('匯出完成', alerts[-1])
        self.assertIn('門窗 2 樘', alerts[-1])

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

    def test_a_failed_standalone_write_becomes_a_readable_alert(self):
        broken = self.standalone_result()
        broken['tables']['detail_rows'] = None
        with self.make_run(broken,
                           answers={'save_file': self.outpath}) as run:
            run.run(run.stub.doc, {})
            alerts = run.stub.forms.alerts
        self.assertIn('匯出失敗', alerts[-1])

    # -- 更新既有活頁簿 ----------------------------------------------------

    def test_the_confirmation_repeats_the_promise_it_makes(self):
        """對話框承諾「只改小計、不新增分頁」——那是對使用者活頁簿的保證。"""
        with self.make_run(self.update_result(),
                           answers={'alert_yes_no': False}) as run:
            run.run(run.stub.doc, {})
            asked = [c for c in run.stub.forms.calls if c[0] == 'alert_yes_no']
        self.assertEqual(1, len(asked))
        message = asked[0][1]['message']
        self.assertIn('小計', message)
        self.assertIn('不建立', message)
        self.assertIn('2 列', message, '要說會動幾列')
        self.assertIn('2 樘', message, '要說讀到幾樘')

    def test_declining_the_confirmation_updates_nothing(self):
        with self.make_run(self.update_result(),
                           answers={'alert_yes_no': False},
                           update=self._record()) as run:
            run.run(run.stub.doc, {})
            self.assertEqual([], self.updates)
            self.assertEqual([], run.stub.forms.alerts)

    def test_confirming_passes_the_plan_and_backup_down(self):
        result = self.update_result()
        with self.make_run(result, answers={'alert_yes_no': True},
                           update=self._record()) as run:
            run.run(run.stub.doc, {})
            alerts = run.stub.forms.alerts

        self.assertEqual(1, len(self.updates))
        path, plan, backup = self.updates[0]
        self.assertEqual(result['path'], path)
        self.assertEqual(result['plan'], plan)
        self.assertTrue(backup)
        self.assertNotEqual(result['path'], backup)
        self.assertIn('更新完成', alerts[-1])
        self.assertIn('共 2 列', alerts[-1])
        self.assertIn(backup, alerts[-1])

    def test_a_failed_update_becomes_a_readable_alert(self):
        def boom(*args, **kwargs):
            raise Exception('分頁被鎖住')

        with self.make_run(self.update_result(),
                           answers={'alert_yes_no': True},
                           update=boom) as run:
            run.run(run.stub.doc, {})
            alerts = run.stub.forms.alerts
        self.assertIn('更新失敗', alerts[-1])
        self.assertIn('分頁被鎖住', alerts[-1])

    def _record(self):
        def record(*args):
            self.updates.append(args)
        return record


if __name__ == '__main__':
    unittest.main()
