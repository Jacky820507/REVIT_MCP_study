# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""開視窗之前那段掃描的進度條與計時。IronPython 2.7 / CPython 3 雙相容。

## 為什麼需要這一支

``forms.ProgressBar`` 是設計成**在迴圈裡逐次 ``update_progress()``** 用的。
把它當成空殼套在一個不透明的長時間呼叫外面：

```python
with forms.ProgressBar(title=u'讀取中…', indeterminate=True):
    rows = expensive_scan(doc)          # 幾分鐘，中間完全沒有更新
```

那個 WPF 視窗建立在 Revit 的 UI 執行緒上卻永遠不被抽動，結果是一個畫不出來、
按不動的幽靈視窗；Revit 進入「沒有回應」，使用者只看到轉圈，然後行程被收掉。
2026-09-02 實測就是這樣：``API External Command Time`` 739 秒，最後 journal 記到
一個 ``0xe0434352`` managed exception。**這比原本「安靜地很慢」更糟。**

所以這裡把正確用法包成一支：``ScanProgress`` 產生給取數層用的 ``progress``
回呼，回呼裡才真正呼叫 ``update_progress``（並節流），使用者按取消時回傳真值。

## 計時

順便量每個階段花多久，寫進 ``%APPDATA%\\RevitMCP\\Logs``。沒有這個就只能猜
「12 分鐘花在哪」——猜錯一次的代價是使用者再被卡一次。寫檔失敗一律吞掉：
診斷用的東西不該變成新的失敗來源。
"""

import os
import time


LOG_DIR_ENV = 'APPDATA'
LOG_SUBPATH = os.path.join('RevitMCP', 'Logs')
LOG_NAME = 'pyrevit_scan.log'

# 每幾次才真的更新一次進度視窗。更新本身要抽動訊息幫浦，每張圖紙都做反而
# 讓掃描變慢；完全不做則視窗會凍住。25 是「看得到在動」與「不拖慢」的折衷。
DEFAULT_THROTTLE = 25


def _log_path():
    root = os.environ.get(LOG_DIR_ENV)
    if not root:
        return None
    return os.path.join(root, LOG_SUBPATH, LOG_NAME)


def write_log(title, phases, extra=None):
    """把一次掃描的階段耗時附加到記錄檔。失敗就安靜放棄。

    ``phases`` 是 ``[(名稱, 秒數), ...]``。
    """
    path = _log_path()
    if not path:
        return None
    try:
        folder = os.path.dirname(path)
        if not os.path.exists(folder):
            os.makedirs(folder)
        parts = ['{}={:.2f}s'.format(name, seconds)
                 for name, seconds in phases]
        if extra:
            parts.append(extra)
        line = '[{}] {} | {}\n'.format(
            time.strftime('%Y-%m-%d %H:%M:%S'), title, '  '.join(parts))
        stream = open(path, 'ab')
        try:
            stream.write(line.encode('utf-8'))
        finally:
            stream.close()
        return path
    except Exception:
        return None


class Timer(object):
    """記錄一連串階段的耗時。"""

    def __init__(self):
        self.phases = []
        self._start = time.time()

    def mark(self, name):
        now = time.time()
        self.phases.append((name, now - self._start))
        self._start = now

    def total(self):
        return sum(seconds for unused, seconds in self.phases)

    def summary(self):
        return u'　'.join(u'{} {:.1f}s'.format(name, seconds)
                          for name, seconds in self.phases)


class ScanProgress(object):
    """把 pyRevit 的 ProgressBar 接成取數層要的 ``progress(done, total)``。

    用法：

    ```python
    with ScanProgress(forms, u'讀取圖紙…') as scan:
        rows = sources.sheet_records(doc, progress=scan.callback)
    ```

    ``forms`` 由呼叫端傳進來（而不是在這裡 import pyrevit），這樣離線測試
    可以塞一個假的進去，不必有 Revit 也能驗證「有沒有真的更新」。
    """

    def __init__(self, forms, title, throttle=DEFAULT_THROTTLE):
        self._forms = forms
        self._title = title
        self._throttle = max(1, int(throttle))
        self._bar = None
        self._count = 0
        self.cancelled = False

    def __enter__(self):
        try:
            self._bar = self._forms.ProgressBar(
                title=self._title + u'  {value}/{max_value}', cancellable=True)
        except TypeError:
            # 舊版 pyRevit 沒有 cancellable；沒有取消總比沒有進度條好。
            self._bar = self._forms.ProgressBar(title=self._title)
        self._bar.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        bar = self._bar
        self._bar = None
        if bar is None:
            return False
        return bar.__exit__(exc_type, exc_value, traceback)

    def retitle(self, title):
        """進入下一個階段：換標題，並讓下一次回呼立刻更新。

        重設計數器很重要——不重設的話新階段的前 ``throttle`` 筆會沿用舊的
        節流相位，使用者會看到標題變了但數字停在上一階段的尾巴。
        """
        self._title = title
        self._count = 0
        bar = self._bar
        if bar is None:
            return
        try:
            bar.title = title + u'  {value}/{max_value}'
        except Exception:
            pass

    def callback(self, done, total):
        """回傳真值代表使用者按了取消。

        **第一次一定更新。** 只用 ``% throttle`` 判斷的話，前 ``throttle``
        筆之內進度條是空白的——而那正是使用者最需要看到「它在動」的時候
        （幾千張圖紙的專案，前 25 筆可能就是好幾秒）。最後一筆也一定更新，
        否則進度條會停在 99% 不動。
        """
        self._count += 1
        first = self._count == 1
        periodic = self._count % self._throttle == 0
        if not (first or periodic or done == total):
            return self.cancelled
        bar = self._bar
        if bar is None:
            return self.cancelled
        try:
            bar.update_progress(done, total)
        except Exception:
            # 進度條壞掉不該讓掃描跟著死——它只是回饋，不是結果。
            return self.cancelled
        if getattr(bar, 'cancelled', False):
            self.cancelled = True
        return self.cancelled
