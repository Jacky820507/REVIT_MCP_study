# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""真的執行 ``ParkingExcelWindow`` 這個視窗類別本身。

## 這支跟 test_parking_excel_run_wiring 的分工

``test_parking_excel_run_wiring.py`` 測的是 ``run()``——它把整個
``ParkingExcelWindow`` 換成一個「直接交出結果」的假窗，驗的是「拿到結果之後
``run()`` 怎麼分派」。那支完全沒有跑過 ``ParkingExcelWindow.__init__`` 本身、
沒有跑過任何一個事件處理常式（``preview_clicked``、``source_mode_changed``、
``cancel_clicked``……）——那整層物件關係與資料流以前完全沒有測試覆蓋。

這支用 ``revit_stub.FakeWPFWindow`` 真的解析 ``ParkingExcel.xaml``，建構真正的
``ParkingExcelWindow``，用 ``.click()``/``.select()``/``.type_text()`` 模擬使用者
操作，驗證：

* 建構子把 XAML 靜態宣告的初始狀態（``multiplierCombo`` 預設選「2」）跟程式碼
  動態設定的狀態（``levelCombo`` 停用、``browseButton`` 停用）都接對了。
* 取消／預覽／更新的完整流程能不能走到底，``self.result`` 有沒有正確地被
  建立或清空。
* ``updateButton.IsEnabled`` 這個「能不能點更新」的把關，在各種情況下對不對。

## 這支測不到什麼

Excel COM 那條路（``inspect_workbook``／``_excel_open``）——測到的是「seam
接縫」以下沒有東西，不是那條路內部的正確性。真正的視窗渲染／像素當然也測不到。
"""

import unittest

import revit_stub


LIB = 'parking_excel'
BUTTON_DIR = 'ParkingExcel'


class FakeId(object):
    def __init__(self, value):
        self.IntegerValue = value


class FakeLevel(object):
    """``_LevelChoice`` 需要的最小 Revit Level 替身。"""

    def __init__(self, name, element_id, elevation=0.0):
        self.Name = name
        self.Id = FakeId(element_id)
        self.Elevation = elevation


LEVELS = [FakeLevel('1F', 101), FakeLevel('2F', 102)]


def make_takeoff(unclassified=None):
    return {
        'counts': {'general_car': 4},
        'source_counts': [
            {'source_key': 'host', 'levels': '1F', 'included': 4},
        ],
        'unclassified': unclassified or [],
        'annotation_candidates': [],
    }


class ParkingWindowTestCase(unittest.TestCase):
    """建好一個 standalone 模式的 ``ParkingExcelWindow``，事件全部可驅動。"""

    def setUp(self):
        self._ctx = revit_stub.install(answers={})
        self.stub = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)

        self.module = revit_stub.load_lib(LIB)
        self.module.collect_levels = lambda doc: list(LEVELS)
        self.module.collect_parking_schedules = lambda doc: []
        self.module.collect_link_choices = lambda doc: []
        self.takeoff = make_takeoff()
        self.module.collect_counts_for_options = (
            lambda doc, options, source_mode, schedule_ids: self.takeoff)

        self.window = self.module.ParkingExcelWindow(
            self.stub.doc, LEVELS, {'workbook_path': None})

    # -- 建構子：XAML 靜態狀態 + 程式碼動態狀態都要接對 ----------------------

    def test_multiplier_combo_keeps_the_xaml_default_selection(self):
        """XAML 裡 ``<ComboBoxItem Content="2" IsSelected="True"/>``——
        程式碼從沒設過 multiplierCombo.SelectedIndex，全靠 XAML 給預設值。"""
        self.assertEqual('2', self.window.multiplierCombo.SelectedItem.Content)

    def test_level_combo_is_disabled_with_a_single_summary_label(self):
        self.assertEqual(0, self.window.levelCombo.SelectedIndex)
        self.assertFalse(self.window.levelCombo.IsEnabled)

    def test_browse_and_select_links_buttons_start_disabled(self):
        """共用入口已經決定了主檔路徑與連結模型，這裡不該讓使用者再改一次。"""
        self.assertFalse(self.window.browseButton.IsEnabled)
        self.assertFalse(self.window.selectLinksButton.IsEnabled)

    def test_standalone_mode_relabels_the_update_button(self):
        self.assertEqual(u'匯出 Excel', self.window.updateButton.Content)

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
        self.assertIn('可另存新的 Excel', self.window.statusText.Text)

    def test_unclassified_items_still_allow_export_but_warn(self):
        """未分類車位不該擋住 standalone 匯出——那條路本來就是給人事後在
        稽核分頁看 BLOCK 用的；只是文字要換成警告。"""
        self.takeoff = make_takeoff(unclassified=[{'element_id': 999}])
        self.window.previewButton.click()
        self.assertTrue(self.window.updateButton.IsEnabled)
        self.assertIn('未分類', self.window.statusText.Text)

    def test_clicking_update_after_a_successful_preview_closes_the_window(self):
        self.window.previewButton.click()
        result_before = self.window.result
        self.window.updateButton.click()
        self.assertTrue(self.window.closed)
        self.assertEqual(result_before, self.window.result,
                         'update_clicked 不該重算或清掉已經預覽好的結果')

    def test_clicking_update_while_disabled_does_nothing(self):
        """``update_clicked`` 自己也檢查 ``self.result is None``——就算測試
        直接呼叫 ``.click()`` 繞過了真實 WPF 會做的「停用按鈕點不動」，
        邏輯本身還是要擋，不能只靠 IsEnabled 這一層 UI 防線。"""
        self.assertFalse(self.window.updateButton.IsEnabled)  # 還沒預覽過
        self.window.updateButton.click()
        self.assertFalse(self.window.closed)

    def test_a_failed_preview_clears_the_result_and_disables_update(self):
        def boom(*args, **kwargs):
            raise Exception('連結模型已卸載')

        self.module.collect_counts_for_options = boom
        self.window.previewButton.click()
        self.assertIsNone(self.window.result)
        self.assertFalse(self.window.updateButton.IsEnabled)
        self.assertEqual([], self.window.previewBox.Text.split('\n')
                         if self.window.previewBox.Text else [])
        self.assertTrue(self.stub.forms.alerts)
        self.assertIn('連結模型已卸載', self.stub.forms.alerts[-1])

    def test_editing_the_path_box_invalidates_a_stale_result(self):
        """使用者改了輸入之後，舊的預覽結果不該繼續被當成有效。"""
        self.window.previewButton.click()
        self.assertIsNotNone(self.window.result)
        self.window.pathBox.type_text('C:\\other.xlsx')
        self.assertIsNone(self.window.result)

    # -- 資料來源模式切換 ----------------------------------------------------

    def test_switching_to_schedule_mode_enables_the_schedule_picker(self):
        self.assertFalse(self.window.selectSchedulesButton.IsEnabled)
        self.window.sourceModeCombo.select(1)
        self.assertTrue(self.window.selectSchedulesButton.IsEnabled)


if __name__ == '__main__':
    unittest.main()
