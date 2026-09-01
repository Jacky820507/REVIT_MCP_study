# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""真的執行「機房門檻 Excel」的 ``lib\\machine_room_threshold_excel.run()``。

## 接縫在哪

``run()`` 開頭就 ``MachineRoomThresholdWindow(doc, options).ShowDialog()``，之後
所有分支都看 ``window.result``。所以接縫是**那個視窗**——換掉它，就能把三種結果
（取消／獨立匯出／更新既有活頁簿）各自的下游流程都跑一次。

## 兩條下游

* **獨立匯出**：``takeoff_standalone.write_standard_workbook`` 直接產 ``.xlsx``，
  不碰 COM，所以這條可以端對端驗到真的檔案。
* **更新既有活頁簿**：走 ``update_workbook``（Excel COM）。這裡換掉那一支，留下來
  受測的是 run() 的編排——確認對話框有沒有把關、備份路徑有沒有一起傳下去、
  失敗時有沒有轉成看得懂的訊息。

## 這支測不到什麼

視窗自己的互動與 ``update_workbook`` 內部的 COM 操作。
"""

import os
import shutil
import tempfile
import unittest
import zipfile

import takeoff_harness as harness


LIB = 'machine_room_threshold_excel'

TABLES = {
    'detail_headers': ['門編號', '寬度 (m)', '樓層'],
    'detail_rows': [['D-01', 0.9, '1F'], ['D-02', 1.2, '1F']],
    'formula_headers': ['項目', '計算式', '小計 (m)'],
    'formula_rows': [['機房門檻', '=0.9+1.2', 2.1]],
    'audit_headers': ['檢核項目', '結果'],
    'audit_rows': [['寬度來源', '開口寬度欄']],
}
SUMMARY = {'doors': ['D-01', 'D-02'], 'total_m': 2.1}


class FakeWindow(object):
    """換掉 ``MachineRoomThresholdWindow``：只負責把預先排好的 result 交出來。"""

    def __init__(self, result):
        self._result = result
        self.shown = 0

    def __call__(self, doc, entry_options):
        self.doc = doc
        self.entry_options = entry_options
        return self

    def ShowDialog(self):
        self.shown += 1

    @property
    def result(self):
        return self._result


class MachineRoomThresholdRunWiringTests(unittest.TestCase):
    _DEFAULT = object()

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='mrt-')
        self.outpath = os.path.join(self.tmpdir, '機房門檻.xlsx')
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.updates = []

    def make_run(self, result, answers=None, update=None):
        def patches(module):
            patched = {'MachineRoomThresholdWindow': FakeWindow(result)}
            if update is not None:
                patched['update_workbook'] = update
            return patched

        return harness.LibRun(LIB, self.tmpdir, answers or {},
                              patches=patches)

    def standalone_result(self, module_mode='standalone'):
        return {'mode': module_mode, 'tables': dict(TABLES),
                'summary': dict(SUMMARY)}

    def update_result(self):
        return {
            'mode': 'update',
            'path': os.path.join(self.tmpdir, '主要.xlsx'),
            'inspection': {'target_address': "'門檻'!C12"},
            'summary': dict(SUMMARY),
            'plan': {'index_sheet': '02門窗表', 'rows': [4, 5],
                     'total_m': 2.1, 'formula': '=SUM(D4:D5)'},
        }

    # -- 使用者取消 --------------------------------------------------------

    def test_no_result_means_the_user_cancelled_and_nothing_happens(self):
        with self.make_run(None) as run:
            run.run(run.stub.doc, {})
            self.assertEqual([], run.prompts, '取消了還跳對話框')
            self.assertEqual([], run.stub.forms.alerts)
        self.assertEqual([], os.listdir(self.tmpdir))

    # -- 獨立匯出 ----------------------------------------------------------

    def test_standalone_export_writes_a_real_three_sheet_workbook(self):
        with self.make_run(self.standalone_result(),
                           answers={'save_file': self.outpath}) as run:
            run.run(run.stub.doc, {})
            alerts = run.stub.forms.alerts

        self.assertTrue(os.path.exists(self.outpath))
        self.assertTrue(zipfile.is_zipfile(self.outpath))
        with zipfile.ZipFile(self.outpath) as archive:
            names = archive.namelist()
        self.assertEqual(sorted(set(names)), sorted(names),
                         'xlsx 內有重複的 part')
        self.assertEqual(
            3, len([n for n in names if n.startswith('xl/worksheets/sheet')]),
            '明細／計算式／稽核三個分頁')
        self.assertTrue(alerts)
        self.assertIn('匯出完成', alerts[-1])
        self.assertIn('2 樘', alerts[-1], '通知要報門數')
        self.assertIn(self.outpath, alerts[-1])

    def test_standalone_appends_the_missing_extension(self):
        bare = os.path.join(self.tmpdir, '沒有副檔名')
        with self.make_run(self.standalone_result(),
                           answers={'save_file': bare}) as run:
            run.run(run.stub.doc, {})
        self.assertTrue(os.path.exists(bare + '.xlsx'))
        self.assertFalse(os.path.exists(bare))

    def test_cancelling_the_standalone_save_writes_nothing(self):
        with self.make_run(self.standalone_result(),
                           answers={'save_file': None}) as run:
            run.run(run.stub.doc, {})
            self.assertEqual([], run.stub.forms.alerts,
                             '取消了還跳完成通知')
        self.assertEqual([], os.listdir(self.tmpdir))

    def test_a_failed_standalone_write_becomes_a_readable_alert(self):
        broken = self.standalone_result()
        broken['tables']['detail_rows'] = None  # 讓寫檔那一步炸掉
        with self.make_run(broken,
                           answers={'save_file': self.outpath}) as run:
            run.run(run.stub.doc, {})
            alerts = run.stub.forms.alerts
        self.assertTrue(alerts)
        self.assertIn('匯出失敗', alerts[-1])

    # -- 更新既有活頁簿 ----------------------------------------------------

    def test_the_confirmation_states_the_target_and_the_counts(self):
        """要更新別人的活頁簿之前，對話框必須講清楚寫到哪、寫什麼。"""
        with self.make_run(self.update_result(),
                           answers={'alert_yes_no': False}) as run:
            run.run(run.stub.doc, {})
            asked = [call for call in run.stub.forms.calls
                     if call[0] == 'alert_yes_no']
        self.assertEqual(1, len(asked))
        message = asked[0][1]['message']
        for expected in ("'門檻'!C12", '02門窗表', '2.1000', '=SUM(D4:D5)'):
            self.assertIn(expected, message)

    def test_declining_the_confirmation_updates_nothing(self):
        with self.make_run(self.update_result(),
                           answers={'alert_yes_no': False},
                           update=self._record_update()) as run:
            run.run(run.stub.doc, {})
            self.assertEqual([], self.updates, '按了否還是寫進去了')
            self.assertEqual([], run.stub.forms.alerts)

    def test_confirming_passes_the_backup_path_down(self):
        """備份路徑是在 run() 算的，沒傳下去就等於沒有備份。"""
        result = self.update_result()
        with self.make_run(result, answers={'alert_yes_no': True},
                           update=self._record_update()) as run:
            run.run(run.stub.doc, {})
            alerts = run.stub.forms.alerts

        self.assertEqual(1, len(self.updates))
        path, inspection, summary, backup, plan = self.updates[0]
        self.assertEqual(result['path'], path)
        self.assertTrue(backup, '備份路徑是空的')
        self.assertNotEqual(result['path'], backup)
        self.assertEqual(result['plan'], plan)
        self.assertIn('更新完成', alerts[-1])
        self.assertIn(backup, alerts[-1], '通知要說備份在哪裡')

    def test_a_failed_update_becomes_a_readable_alert(self):
        def boom(*args, **kwargs):
            raise Exception('分頁被鎖住')

        with self.make_run(self.update_result(),
                           answers={'alert_yes_no': True},
                           update=boom) as run:
            run.run(run.stub.doc, {})
            alerts = run.stub.forms.alerts
        self.assertTrue(alerts)
        self.assertIn('更新失敗', alerts[-1])
        self.assertIn('分頁被鎖住', alerts[-1])

    # -- 小工具 ------------------------------------------------------------

    def _record_update(self):
        def record(*args):
            self.updates.append(args)
        return record


if __name__ == '__main__':
    unittest.main()
