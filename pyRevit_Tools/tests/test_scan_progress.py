# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""開視窗前那段掃描的進度條契約。

## 為什麼這支存在

2026-09-02 使用者回報「點下按鈕一直在轉圈、UI 視窗根本沒出來、Revit 直接
掛掉」。成因是前一版把整段掃描包成：

```python
with forms.ProgressBar(title=u'讀取中…', indeterminate=True):
    rows = sources.sheet_records(doc)     # 中間完全沒有 update_progress
```

``forms.ProgressBar`` 是設計成在迴圈裡逐次更新的。當成空殼套在不透明的長時間
呼叫外面，那個 WPF 視窗建在 Revit 的 UI 執行緒上卻永遠不被抽動——畫不出來、
按不動，Revit 判定「沒有回應」後行程被收掉。journal 記到
``API External Command Time 739 秒`` 加一個 ``0xe0434352`` managed exception。

**這比原本「安靜地很慢」更糟**，所以守門的斷言是「有沒有真的更新過」，
而不是「有沒有進度條」。純功能測試看不出差別：兩種寫法的輸出完全一樣。
"""

import os
import sys
import types
import unittest

from importlib.util import spec_from_file_location, module_from_spec


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
LIB = os.path.join(ROOT, 'MCP_Tools.extension', 'lib')


def _load(name, filename):
    spec = spec_from_file_location(name, os.path.join(LIB, filename))
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scan_progress = _load('scan_progress_under_test', 'scan_progress.py')


# ---- 假的 pyRevit forms --------------------------------------------------

class FakeProgressBar(object):
    """記錄「被更新了幾次」，這正是本測試要斷言的東西。"""

    def __init__(self, title=None, cancellable=False, indeterminate=False):
        self.title = title
        self.cancellable = cancellable
        self.indeterminate = indeterminate
        self.updates = []
        self.cancelled = False
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *args):
        self.exited = True
        return False

    def update_progress(self, done, total):
        self.updates.append((done, total))


class LegacyProgressBar(FakeProgressBar):
    """舊版 pyRevit：``ProgressBar`` 不接受 ``cancellable``。"""

    def __init__(self, title=None, indeterminate=False):
        FakeProgressBar.__init__(self, title=title, indeterminate=indeterminate)


class FakeForms(object):
    def __init__(self, bar_class=FakeProgressBar):
        self._bar_class = bar_class
        self.bars = []

    def ProgressBar(self, **kwargs):
        bar = self._bar_class(**kwargs)
        self.bars.append(bar)
        return bar


class PumpingTests(unittest.TestCase):
    """幫浦有沒有真的被抽動。"""

    def test_the_bar_is_updated_during_a_long_scan(self):
        forms = FakeForms()
        with scan_progress.ScanProgress(forms, u'讀取', throttle=10) as scan:
            for i in range(1, 101):
                scan.callback(i, 100)
        bar = forms.bars[0]
        self.assertTrue(bar.entered and bar.exited)
        self.assertTrue(
            len(bar.updates) >= 10,
            u'只更新了 {} 次；進度條沒被抽動就會變成幽靈視窗'.format(
                len(bar.updates)))

    def test_the_last_item_always_updates(self):
        """節流不能讓最後一筆被吃掉，否則進度條停在 99%。"""
        forms = FakeForms()
        with scan_progress.ScanProgress(forms, u'讀取', throttle=1000) as scan:
            for i in range(1, 51):
                scan.callback(i, 50)
        self.assertIn((50, 50), forms.bars[0].updates)

    def test_throttling_keeps_the_update_count_far_below_the_item_count(self):
        """每一筆都更新反而會拖慢掃描——更新本身要抽動訊息幫浦。"""
        forms = FakeForms()
        with scan_progress.ScanProgress(forms, u'讀取', throttle=25) as scan:
            for i in range(1, 1001):
                scan.callback(i, 1000)
        self.assertLess(len(forms.bars[0].updates), 100)

    def test_it_asks_for_a_cancellable_bar(self):
        forms = FakeForms()
        with scan_progress.ScanProgress(forms, u'讀取'):
            pass
        self.assertTrue(forms.bars[0].cancellable)

    def test_it_falls_back_when_pyrevit_has_no_cancellable(self):
        """舊版 pyRevit 沒有 cancellable：沒有取消也好過沒有進度條。"""
        forms = FakeForms(bar_class=LegacyProgressBar)
        with scan_progress.ScanProgress(forms, u'讀取', throttle=1) as scan:
            scan.callback(1, 1)
        self.assertEqual([(1, 1)], forms.bars[0].updates)


class CancelTests(unittest.TestCase):
    def test_callback_reports_cancellation(self):
        forms = FakeForms()
        with scan_progress.ScanProgress(forms, u'讀取', throttle=1) as scan:
            self.assertFalse(scan.callback(1, 10))
            forms.bars[0].cancelled = True
            self.assertTrue(scan.callback(2, 10))

    def test_cancellation_sticks_even_between_throttled_calls(self):
        """取消一次就是取消——不能因為節流跳過而又變回未取消。"""
        forms = FakeForms()
        with scan_progress.ScanProgress(forms, u'讀取', throttle=5) as scan:
            scan.callback(1, 100)                    # 第 1 次一定更新
            forms.bars[0].cancelled = True
            for i in range(2, 5):
                self.assertFalse(scan.callback(i, 100))   # 被節流跳過
            self.assertTrue(scan.callback(5, 100))   # 第 5 次更新，讀到取消
            self.assertTrue(scan.callback(6, 100))   # 之後被跳過也要記得

    def test_the_first_item_updates_immediately(self):
        """前 throttle 筆空白正是使用者最需要看到「它在動」的時候。"""
        forms = FakeForms()
        with scan_progress.ScanProgress(forms, u'讀取', throttle=25) as scan:
            scan.callback(1, 5000)
        self.assertEqual([(1, 5000)], forms.bars[0].updates)

    def test_a_broken_bar_does_not_kill_the_scan(self):
        """進度條只是回饋，不是結果；它壞掉不該讓掃描跟著死。"""
        class Broken(FakeProgressBar):
            def update_progress(self, done, total):
                raise ValueError('boom')

        forms = FakeForms(bar_class=Broken)
        with scan_progress.ScanProgress(forms, u'讀取', throttle=1) as scan:
            self.assertFalse(scan.callback(1, 10))


class RetitleTests(unittest.TestCase):
    """換階段（便宜掃描 -> 補 DWG NO.）時進度條要跟著換。"""

    def test_retitle_updates_the_bar_title(self):
        forms = FakeForms()
        with scan_progress.ScanProgress(forms, u'讀取圖紙') as scan:
            scan.retitle(u'讀取圖框 DWG NO.')
        self.assertIn(u'讀取圖框 DWG NO.', forms.bars[0].title)

    def test_retitle_makes_the_next_callback_update_immediately(self):
        """不重設計數器的話，新階段的前幾筆會沿用舊的節流相位——
        使用者會看到標題變了但數字停在上一階段的尾巴。"""
        forms = FakeForms()
        with scan_progress.ScanProgress(forms, u'讀取', throttle=25) as scan:
            for i in range(1, 13):
                scan.callback(i, 100)
            before = len(forms.bars[0].updates)
            scan.retitle(u'第二階段')
            scan.callback(1, 100)
        self.assertEqual(before + 1, len(forms.bars[0].updates))

    def test_retitle_without_a_bar_is_harmless(self):
        forms = FakeForms()
        scan = scan_progress.ScanProgress(forms, u'讀取')
        scan.retitle(u'第二階段')   # 還沒 __enter__


class TimerTests(unittest.TestCase):
    def test_phases_are_recorded_in_order(self):
        timer = scan_progress.Timer()
        timer.mark('a')
        timer.mark('b')
        self.assertEqual(['a', 'b'], [name for name, unused in timer.phases])
        self.assertGreaterEqual(timer.total(), 0.0)
        self.assertIn('a', timer.summary())


class LogTests(unittest.TestCase):
    def test_writing_the_log_never_raises(self):
        """診斷用的東西不該變成新的失敗來源。"""
        saved = os.environ.get(scan_progress.LOG_DIR_ENV)
        try:
            os.environ.pop(scan_progress.LOG_DIR_ENV, None)
            self.assertIsNone(scan_progress.write_log('t', [('a', 1.0)]))
        finally:
            if saved is not None:
                os.environ[scan_progress.LOG_DIR_ENV] = saved

    def test_a_log_line_is_written_when_a_target_exists(self):
        import tempfile
        saved = os.environ.get(scan_progress.LOG_DIR_ENV)
        folder = tempfile.mkdtemp()
        try:
            os.environ[scan_progress.LOG_DIR_ENV] = folder
            path = scan_progress.write_log(
                u'圖說差異', [('sheets', 12.5)], extra='sheets=1200')
            self.assertIsNotNone(path)
            stream = open(path, 'rb')
            try:
                text = stream.read().decode('utf-8')
            finally:
                stream.close()
            self.assertIn('sheets=12.50s', text)
            self.assertIn('sheets=1200', text)
        finally:
            if saved is not None:
                os.environ[scan_progress.LOG_DIR_ENV] = saved
            else:
                os.environ.pop(scan_progress.LOG_DIR_ENV, None)


if __name__ == '__main__':
    unittest.main()
