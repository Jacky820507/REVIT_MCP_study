# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""真的執行 ``DoorWindowWindow`` 這個視窗類別本身。

跟 ``test_parking_excel_window_wiring.py`` 同一個目的、同一套辦法（見那支的
docstring）——``test_door_window_run_wiring.py`` 只測 ``run()``，整顆
``DoorWindowWindow`` 被換成假窗；這支用 ``revit_stub.FakeWPFWindow`` 真的解析
``DoorWindowExcel.xaml``，建構真正的視窗，驗證建構子的初始狀態與
``preview_clicked``／``cancel_clicked``／``update_clicked`` 的資料流。

沒有重複 Parking 那支已經證明過的每一種案型（例如「輸入變更使結果失效」），
只挑跟這顆按鈕不一樣、值得單獨釘住的部分：``sourceModeCombo`` 的初始選取
（跟 Parking 的 multiplierCombo 是不同的 XAML 區塊）、以及 update 模式（有
主檔路徑）在 Excel 讀取失敗時的收場。
"""

import os
import shutil
import tempfile
import unittest

import revit_stub


LIB = 'door_window_window'


def make_takeoff():
    return {
        'sources': [u'主模型'],
        'total': 8,
        'counts': {'D1': 3, 'W1': 5},
    }


class DoorWindowWindowTestCase(unittest.TestCase):
    def setUp(self):
        self._ctx = revit_stub.install(answers={})
        self.stub = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)

        self.module = revit_stub.load_lib(LIB)
        core = self.module.core
        core.list_links = lambda doc: []
        core.list_schedules = lambda doc: []
        core.list_levels = lambda doc, selected_link_ids: []
        self.takeoff = make_takeoff()
        core.collect_counts_for_options = (
            lambda doc, options, source_mode, schedule_ids: self.takeoff)

        self.window = self.module.DoorWindowWindow(
            self.stub.doc, {'workbook_path': None})

    # -- 建構子 ----------------------------------------------------------

    def test_source_mode_combo_keeps_the_xaml_default_selection(self):
        """XAML 第一個 ``<ComboBoxItem IsSelected="True">`` 是「自動偵測」，
        程式碼沒有另外設過 SelectedIndex。"""
        self.assertEqual(0, self.window.sourceModeCombo.SelectedIndex)

    def test_standalone_mode_relabels_the_update_button_and_status(self):
        self.assertEqual(u'匯出 Excel', self.window.updateButton.Content)
        self.assertIn('請設定資料來源模式', self.window.statusText.Text)

    def test_pick_buttons_start_disabled_in_standalone_mode(self):
        self.assertFalse(self.window.browseButton.IsEnabled)
        self.assertFalse(self.window.selectLinksButton.IsEnabled)
        self.assertFalse(self.window.selectLevelsButton.IsEnabled)

    # -- 取消 ----------------------------------------------------------

    def test_cancel_clears_the_result_and_closes(self):
        self.window.cancelButton.click()
        self.assertIsNone(self.window.result)
        self.assertTrue(self.window.closed)

    # -- 預覽 → 結果 → 更新 ------------------------------------------------

    def test_preview_populates_the_result_and_enables_update(self):
        self.window.previewButton.click()
        self.assertIsNotNone(self.window.result)
        self.assertEqual('standalone', self.window.result['mode'])
        self.assertTrue(self.window.updateButton.IsEnabled)
        self.assertIn('8 樘', self.window.previewBox.Text,
                      '預覽文字要報出讀到的門窗總數')

    def test_clicking_update_after_a_successful_preview_closes_the_window(self):
        self.window.previewButton.click()
        result_before = self.window.result
        self.window.updateButton.click()
        self.assertTrue(self.window.closed)
        self.assertEqual(result_before, self.window.result)

    def test_clicking_update_while_disabled_does_nothing(self):
        self.assertFalse(self.window.updateButton.IsEnabled)
        self.window.updateButton.click()
        self.assertFalse(self.window.closed)

    # -- 更新模式：Excel 讀取失敗要有收場，不能讓例外整支炸出去 ---------------

    def test_a_failed_excel_read_in_update_mode_alerts_and_keeps_the_window_open(self):
        # preview_clicked 進 Excel 讀取分支之前會先擋「檔案是否存在」，所以
        # 要用一個真的存在的路徑，讀取失敗只發生在後面的 _excel_open。
        tmpdir = tempfile.mkdtemp(prefix='dw-window-')
        self.addCleanup(shutil.rmtree, tmpdir, True)
        path = os.path.join(tmpdir, '主要.xlsx')
        with open(path, 'wb') as handle:
            handle.write(b'placeholder')

        entry_options = {'workbook_path': path}
        self.module.core.collect_counts_for_options = (
            lambda doc, options, source_mode, schedule_ids: self.takeoff)
        window = self.module.DoorWindowWindow(self.stub.doc, entry_options)

        def boom(open_path, read_only):
            raise Exception('檔案被鎖住')

        self.module.core._excel_open = boom
        self.module.core._excel_close = lambda *a, **k: None

        window.previewButton.click()

        self.assertIsNone(window.result)
        self.assertFalse(window.closed, '讀取失敗不該直接關窗，要留給使用者重試')
        self.assertTrue(self.stub.forms.alerts)
        self.assertIn('檔案被鎖住', self.stub.forms.alerts[-1])


if __name__ == '__main__':
    unittest.main()
