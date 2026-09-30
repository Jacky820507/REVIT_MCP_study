# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""離線驅動 ``PdfDiffClouds`` 視窗，用假的 WPF 元件抓出宿主內才會發作的錯。

## 為什麼需要這一支

這顆按鈕連續三次「1453 項測試全綠、IronPython 編譯通過、真實 PDF 端對端成功，
然後在 Revit 裡第一次點就炸」。三次的成因都不是演算法，是 **WPF 的物件模型**：

1. 同一個 ComboBox 被掛到第二個父層（切換下拉時重建左欄）→ Revit 行程終止。
2. 同一張卡片在一次繪製裡被加兩次（``(gridLabel, score)`` 當快取 key 會撞，
   實測第 1 頁兩個區域都叫 ``J4`` 且分數都是 9.0）→ Revit 行程終止。
3. ``selected_pairings`` 自己重組了一份 key，改了 ``_box_for`` 卻漏改它 →
   **不崩潰、不報錯，一朵雲都建不出來**。

前兩者在 CPython 下用真的 WPF 測不到（沒有 WPF），用純函式測試也測不到
（問題在 UI 的物件關係）。所以這裡把 **WPF 的單一父層規則做成會拋例外的
強制規約**：``Children.Add`` 遇到已經有父層的元素就丟，跟 WPF 一模一樣。
第三者則靠「勾了就要出現在 selected_pairings」這條端對端斷言擋下來。

## 這支測不到什麼

IronPython 與 CPython 的行為差異（例如 ``'{:.2f}'.format(0)`` 只在 IronPython
丟 ValueError）測不到——那類要靠 ``verify_ironpython.ps1`` 與
``logic.format_fraction_percent`` 的型別不變量。版面外觀也測不到。
**這支管的是物件關係與資料流，不是像素。**
"""

import os
import sys
import unittest

try:
    from importlib.util import spec_from_file_location, module_from_spec
except ImportError:  # pragma: no cover - Python 2 不會跑這支
    spec_from_file_location = None

import xml.etree.ElementTree as ElementTree


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
LIB = os.path.join(ROOT, 'MCP_Tools.extension', 'lib')
BUTTON = os.path.join(ROOT, 'MCP_Tools.extension', 'MCP_Macros.tab',
                      'Revision.panel', 'PdfDiffClouds.pushbutton')
if LIB not in sys.path:
    sys.path.insert(0, LIB)


# ---- 假的 WPF ------------------------------------------------------------

class VisualError(Exception):
    """對應 WPF 的「指定的 Visual 已經是另一個 Visual 的子項目」。"""


class _Children(object):
    """模擬 ``UIElementCollection``，**強制單一父層規則**。"""

    def __init__(self, owner):
        self._owner = owner
        self._items = []

    def Add(self, child):
        if getattr(child, 'Parent', None) is not None:
            raise VisualError(
                '指定的 Visual 已經是另一個 Visual 的子項目'
                '（{!r} 的父層是 {!r}）'.format(child, child.Parent))
        child.Parent = self._owner
        self._items.append(child)

    def Clear(self):
        # 只釋放**直接子層**——這正是 WPF 的行為，也正是「快取深層元件」
        # 會出事、「快取整張卡片」沒事的原因。
        for item in self._items:
            item.Parent = None
        self._items = []

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    @property
    def Count(self):
        return len(self._items)


class _Element(object):
    def __init__(self, name=None):
        self.Parent = None
        self.Name = name
        self.Children = _Children(self)
        self.Margin = None
        self.Padding = None
        self.Background = None
        self.Foreground = None
        self.BorderBrush = None
        self.BorderThickness = None
        self.Cursor = None
        self.Width = None
        self.Height = None
        self.IsEnabled = True
        self.Visibility = None
        self.Tag = None
        self._handlers = {}

    def __repr__(self):
        return '<{} {}>'.format(type(self).__name__, self.Name or id(self))


class _Event(object):
    """支援 ``obj.Event += handler`` 的最小實作。"""

    def __init__(self, owner, key):
        self._owner = owner
        self._key = key

    def __iadd__(self, handler):
        self._owner._handlers.setdefault(self._key, []).append(handler)
        return self

    def fire(self, sender, args=None):
        for handler in self._owner._handlers.get(self._key, []):
            handler(sender, args)


def _event_property(key):
    def getter(self):
        return _Event(self, key)

    def setter(self, value):
        # `+=` 會先讀再寫回同一個 _Event，這裡吞掉即可。
        pass

    return property(getter, setter)


class StackPanel(_Element):
    Orientation = None
    VerticalAlignment = None
    HorizontalAlignment = None


class Border(_Element):
    def __init__(self, name=None):
        _Element.__init__(self, name)
        self._child = None

    @property
    def Child(self):
        return self._child

    @Child.setter
    def Child(self, value):
        if value is not None and getattr(value, 'Parent', None) is not None:
            raise VisualError('Border.Child 已經有父層：{!r}'.format(value))
        if value is not None:
            value.Parent = self
        self._child = value

    MouseLeftButtonUp = _event_property('MouseLeftButtonUp')


class TextBlock(_Element):
    def __init__(self, name=None):
        _Element.__init__(self, name)
        self.Text = ''
        self.FontSize = None
        self.FontWeight = None
        self.TextWrapping = None
        self.VerticalAlignment = None


class TextBox(TextBlock):
    IsReadOnly = False
    TextChanged = _event_property('TextChanged')


class CheckBox(_Element):
    def __init__(self, name=None):
        _Element.__init__(self, name)
        self._checked = False
        self.Content = None

    @property
    def IsChecked(self):
        return self._checked

    @IsChecked.setter
    def IsChecked(self, value):
        was = self._checked
        self._checked = bool(value)
        if was == self._checked:
            return
        key = 'Checked' if self._checked else 'Unchecked'
        for handler in self._handlers.get(key, []):
            handler(self, None)

    Checked = _event_property('Checked')
    Unchecked = _event_property('Unchecked')


class ItemsSourceConflict(Exception):
    """對應 WPF「使用 ItemsSource 時操作 Items 會產生無效的作業」。"""


class _Items(object):
    def __init__(self, owner):
        self._owner = owner
        self._items = []

    def Add(self, item):
        if getattr(self._owner, '_items_source', None) is not None:
            raise ItemsSourceConflict(
                '使用 ItemsSource 時不能再 Items.Add')
        self._items.append(item)

    def _bind(self, source):
        self._items = list(source)

    def __len__(self):
        return len(self._items)

    def __getitem__(self, index):
        return self._items[index]


class ComboBox(_Element):
    def __init__(self, name=None):
        _Element.__init__(self, name)
        self.Items = _Items(self)
        self._items_source = None
        self._index = -1

    @property
    def ItemsSource(self):
        return self._items_source

    @ItemsSource.setter
    def ItemsSource(self, value):
        # WPF 的 Items 在綁定之後是 ItemsSource 的唯讀檢視。這裡照做，
        # 讓「共用同一份清單」的寫法在測試裡也看得到同樣的內容。
        self._items_source = value
        self.Items._bind(value or [])

    @property
    def SelectedIndex(self):
        return self._index

    @SelectedIndex.setter
    def SelectedIndex(self, value):
        self._index = value
        for handler in self._handlers.get('SelectionChanged', []):
            handler(self, None)

    SelectionChanged = _event_property('SelectionChanged')


class Button(_Element):
    Content = None
    Click = _event_property('Click')


_CONTROL_TYPES = {
    'StackPanel': StackPanel, 'Border': Border, 'TextBlock': TextBlock,
    'TextBox': TextBox, 'CheckBox': CheckBox, 'ComboBox': ComboBox,
    'Button': Button,
}


class _Namespace(object):
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def _install_stubs():
    """把假模組塞進 ``sys.modules``，讓 script.py 能在 CPython 下匯入。"""
    import types

    def module(name, **attrs):
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        sys.modules[name] = mod
        return mod

    module('clr', AddReference=lambda *a, **k: None,
           AddReferenceToFileAndPath=lambda *a, **k: None,
           GetClrType=lambda *a, **k: None)

    module('System')
    module('System.Windows', FontWeights=_Namespace(SemiBold='SemiBold'),
           TextWrapping=_Namespace(Wrap='Wrap'),
           Thickness=lambda *a: tuple(a),
           Visibility=_Namespace(Visible='Visible', Collapsed='Collapsed'))
    module('System.Windows.Controls', Orientation=_Namespace(
        Horizontal='Horizontal', Vertical='Vertical'), **_CONTROL_TYPES)
    module('System.Windows.Input', Cursors=_Namespace(Hand='Hand'))
    module('System.Windows.Media',
           Brushes=_Namespace(Transparent='Transparent',
                              WhiteSmoke='WhiteSmoke'),
           SolidColorBrush=lambda c: ('brush', c),
           Color=_Namespace(FromRgb=lambda r, g, b: (r, g, b)))

    class _ProgressBar(object):
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class WPFWindow(object):
        """從 XAML 讀出所有 ``x:Name``，建立對應的假控制項。

        順帶驗證了一件事：**程式碼引用的每個名稱都必須真的存在於 XAML**。
        名字打錯在 Revit 裡是 AttributeError，在這裡會是同樣的錯，但發生在
        CI 而不是使用者的螢幕上。
        """

        def __init__(self, xaml_path):
            tree = ElementTree.parse(xaml_path)
            ns_x = '{http://schemas.microsoft.com/winfx/2006/xaml}Name'
            for element in tree.iter():
                name = element.get(ns_x)
                if not name:
                    continue
                tag = element.tag.split('}')[-1]
                factory = _CONTROL_TYPES.get(tag, _Element)
                setattr(self, name, factory(name))

        def ShowDialog(self):
            return None

        def Close(self):
            pass

    alerts = []
    module('pyrevit',
           forms=_Namespace(WPFWindow=WPFWindow, ProgressBar=_ProgressBar,
                            alert=lambda *a, **k: alerts.append(a),
                            pick_file=lambda *a, **k: None),
           revit=_Namespace(doc=object(), uidoc=None))
    module('pyrevit.forms')

    class MCPBridgeError(Exception):
        pass

    module('mcp_bridge', MCPBridgeError=MCPBridgeError,
           brief=lambda data, **k: u'{}'.format(data),
           dry_run_then_apply=lambda *a, **k: None,
           show_error=lambda *a, **k: None,
           run=lambda *a, **k: None)
    class ScanCancelled(Exception):
        pass

    module('pdf_diff_sources', sheet_records=lambda doc, **k: [],
           revision_records=lambda doc: [], revision_label=lambda row: u'',
           selected_revision_cloud_id=lambda doc, uidoc: None,
           fill_dwg_numbers=lambda doc, rows, **k: rows,
           ScanCancelled=ScanCancelled)
    return alerts


def _load_script():
    _install_stubs()
    path = os.path.join(BUTTON, 'script.py')
    spec = spec_from_file_location('pdf_diff_button', path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


# ---- 測資 ----------------------------------------------------------------

A3_PT = (1191.0, 842.0)
A3_FT = (0.0, 0.0, 420.0 / 304.8, 297.0 / 304.8)


def region(label, score, bbox, text=1, geom=0, oversized=False):
    return {'gridLabel': label, 'score': score, 'bbox': bbox,
            'textCount': text, 'geomCount': geom, 'oversized': oversized,
            'pageFraction': 0.0,
            'samples': [{'kind': 'text-change', 'before': u'A',
                         'after': u'B'}]}


def page(number, sheet_number, sheet_name, text_regions, all_regions=None):
    return {
        'pageNumberA': number, 'pageNumberB': number,
        'sheetNumber': sheet_number, 'sheetName': sheet_name,
        'sheetNumberCandidates': [sheet_number],
        'sheetNameCandidates': [sheet_name],
        'pageWidthPt': A3_PT[0], 'pageHeightPt': A3_PT[1],
        'itemCountA': 100, 'itemCountB': 120, 'textDiffs': 3,
        'offset': (0.0, 0.0), 'warnings': [],
        'smartRegions': text_regions,
        'textRegions': text_regions,
        'regions': all_regions if all_regions is not None else text_regions,
    }


def sheet(number, name, dwg_number=None):
    return {'SheetNumber': number, 'SheetName': name,
            'DwgNumber': dwg_number, 'DwgNumberCandidates': [dwg_number]
            if dwg_number else [], 'Outline': A3_FT, 'ElementId': 1}


def make_result():
    """刻意包含實測踩到的兩個危險特徵：

    - 同一頁兩個區域 ``gridLabel`` 與 ``score`` 完全相同（實測第 1 頁的 J4）
    - 一個 ``pageFraction`` 為 0.0 的區域（實測讓格式化炸掉的那種）
    """
    return {
        'pageCountA': 2, 'pageCountB': 2, 'matchedCount': 2,
        'onlyInA': [], 'onlyInB': [],
        'pages': [
            page(1, u'0721B-ARD-D02001', u'地下一層平面圖', [
                region(u'J4', 9.0, (100.0, 100.0, 116.0, 125.0)),
                region(u'J4', 9.0, (300.0, 400.0, 314.0, 409.0)),
                region(u'F4:G5', 3.0, (500.0, 200.0, 559.0, 322.0)),
            ], all_regions=[
                region(u'A1:L9', 900.0, (0.0, 0.0, 1191.0, 842.0),
                       text=5, geom=800, oversized=True),
                region(u'C2', 6.0, (200.0, 200.0, 260.0, 240.0)),
            ]),
            page(2, u'0721B-ARD-D02002', u'一層平面圖', [
                region(u'B3', 3.0, (50.0, 50.0, 70.0, 70.0)),
            ]),
        ],
    }


def make_window():
    window = script.PdfDiffWindow([
                                   sheet(u'A2-02', u'地下一層平面圖',
                                         u'0721B-ARD-D02001'),
                                   sheet(u'A2-01', u'一層平面圖',
                                         u'0721B-ARD-D02002'),
                                   sheet(u'A3-01', u'立面圖(一)')])
    window.result = make_result()
    window._build_rows()
    window._render_sheets()
    window._select_row(window.rows[0])
    return window


# ---- 測試 ----------------------------------------------------------------

class StubSanityTests(unittest.TestCase):
    """先證明這個模擬器真的抓得到問題，否則它只是裝飾。"""

    def test_adding_the_same_element_twice_raises(self):
        panel_a, panel_b = StackPanel(), StackPanel()
        child = TextBlock()
        panel_a.Children.Add(child)
        self.assertRaises(VisualError, panel_b.Children.Add, child)

    def test_clear_releases_direct_children_only(self):
        """這正是「快取整張卡片沒事、快取深層元件會出事」的原因。"""
        outer, inner = StackPanel(), StackPanel()
        deep = TextBlock()
        inner.Children.Add(deep)
        outer.Children.Add(inner)
        outer.Children.Clear()
        self.assertIsNone(inner.Parent)      # 直接子層被釋放
        self.assertIs(inner, deep.Parent)    # 深層的沒有


class WindowRenderTests(unittest.TestCase):
    def test_the_window_builds_without_reparenting(self):
        make_window()

    def test_duplicate_grid_labels_do_not_reuse_one_card(self):
        """實測第 1 頁有兩個區域都叫 J4 且分數都是 9.0。用 (label, score)
        當快取 key 會讓同一張卡片被加兩次，直接終止 Revit 行程。"""
        window = make_window()
        # 1 行摘要（圖元數／文字變更數）+ 3 張區域卡片
        self.assertEqual(4, len(window.regionList.Children))

    def test_switching_mode_does_not_reparent_anything(self):
        """換模式一度重建整個左欄，把快取的 ComboBox 掛到第二個父層。"""
        window = make_window()
        window.modeCombo.SelectedIndex = 1
        window.filter_changed(window.modeCombo, None)
        window.modeCombo.SelectedIndex = 0
        window.filter_changed(window.modeCombo, None)

    def test_revisiting_a_sheet_does_not_reparent_anything(self):
        """點回看過的圖紙會重掛快取的卡片。"""
        window = make_window()
        window._select_row(window.rows[1])
        window._select_row(window.rows[0])
        window._select_row(window.rows[1])

    def test_toggling_the_oversized_filter_is_safe(self):
        window = make_window()
        window.modeCombo.SelectedIndex = 2
        window.hideOversizedCheck.IsChecked = False
        window.filter_changed(window.hideOversizedCheck, None)
        window.hideOversizedCheck.IsChecked = True
        window.filter_changed(window.hideOversizedCheck, None)

    def test_bulk_select_and_clear_are_safe(self):
        window = make_window()
        window.select_shown_clicked(None, None)
        window.clear_all_clicked(None, None)

    def test_every_name_the_code_uses_exists_in_the_xaml(self):
        """XAML 名稱打錯在 Revit 裡是 AttributeError；在這裡也是，
        只是發生在 CI 而不是使用者的螢幕上。"""
        window = make_window()
        for name in ('oldPathText', 'newPathText', 'compareButton',
                     'modeCombo', 'thresholdCombo', 'hideOversizedCheck',
                     'excludeTitleCheck', 'removeOverlapCheck',
                     'removeManualOverlapCheck', 'sheetFilterList',
                     'sheetFilterStatus', 'revisionCombo',
                     'sheetList', 'regionList',
                     'detailLabel', 'statusText', 'okButton'):
            self.assertTrue(hasattr(window, name), name)


class ScaleTests(unittest.TestCase):
    """會隨專案規模爆掉的寫法。這些不是效能微調，是「大案子按下去會死」。"""

    def test_sheet_filter_boxes_are_in_the_panel(self):
        """勾選框要真的掛進 sheetFilterList，不能只活在字典裡。

        原本只建立控制項、忘了 ``Children.Add``，所以視窗上「欲標圖紙」那一
        欄是空的——使用者看不到也不能取消任何一張圖紙。這支測試本身正是
        當初沒抓到的原因：其他測試都直接用 ``sheet_filter_boxes`` 字典取用，
        繞過了 UI。
        """
        window = make_window()
        self.assertEqual(len(window.rows),
                         len(window.sheetFilterList.Children))
        for row in window.rows:
            box = window.sheet_filter_boxes[id(row)]
            self.assertIs(window.sheetFilterList, box.Parent)

    def test_rows_with_equal_content_are_filtered_independently(self):
        """圖紙勾選要用身分判斷，不能用 ``row in list``。

        ``row`` 是 dict，``list.__contains__`` 沒命中時會做完整的深層比較，
        而 ``row['page']`` 底下掛著整頁的 region 清單。這個查詢對每一列各做
        一次，就是 O(N²) 次深層比較——300 頁的 PDF 卡死在這裡。

        內容相同的兩列還會被判成同一列，所以這同時是正確性問題：這裡的
        兩頁圖號都配不到 Revit 圖紙，於是兩個 row dict 完全相等。
        """
        window = script.PdfDiffWindow([sheet(u'A2-01', u'一層平面圖')])
        twin = page(1, u'讀不到的圖號', u'同名圖', [
            region(u'B3', 3.0, (50.0, 50.0, 70.0, 70.0))])
        window.result = {'pageCountA': 2, 'pageCountB': 2, 'matchedCount': 0,
                         'onlyInA': [], 'onlyInB': [],
                         'pages': [twin, dict(twin)]}
        window._build_rows()
        first, second = window.rows
        self.assertEqual(first, second, u'測資本身要是「內容相同」才有意義')
        self.assertIsNot(first, second)

        window.sheet_filter_boxes[id(first)].IsChecked = False
        self.assertFalse(window._row_is_sheet_selected(first))
        self.assertTrue(window._row_is_sheet_selected(second))

    def test_every_combo_shares_one_items_source(self):
        """圖紙下拉不能每個都逐項 Items.Add。

        1500 張圖紙 x 200 頁 = 30 萬次跨 WPF 邊界呼叫，而且全部發生在
        ``compare_clicked`` 這個事件處理常式裡。共用一份 ItemsSource 之後
        每個下拉只剩一次屬性設定。
        """
        window = make_window()
        for row in window.rows:
            combo = row['combo']
            self.assertIs(window._sheet_labels, combo.ItemsSource)
            self.assertEqual(len(window._sheet_labels), len(combo.Items))
            # 共用清單但**不共用「目前項目」**——同步的話動一個下拉會讓
            # 全部一起動，雲就畫到錯的圖紙上，而且不會報錯。
            self.assertFalse(combo.IsSynchronizedWithCurrentItem)
        # 綁定之後再 Items.Add 在 WPF 是 InvalidOperationException。
        self.assertRaises(ItemsSourceConflict,
                          window.rows[0]['combo'].Items.Add, u'x')

    def test_a_failing_handler_does_not_escape_to_wpf(self):
        """事件處理常式丟出去的例外會終止 Revit，所以一律要被攔下來。

        WPF 不會替我們攔 dispatcher 上的未處理例外；Revit 只會顯示「發生
        嚴重錯誤，應用程式將終止」然後關掉，訊息還看不到。``_guard`` 把它
        變成一個可回報的對話框。
        """
        window = make_window()

        def boom(*args, **kwargs):
            raise ValueError('boom')

        window._update_status = boom
        # 沒有 _guard 的話這一行會把 ValueError 丟回 WPF 的 dispatcher。
        window._combo_changed(None, None)
        window._tick_changed(None, None)


class LazySheetLoadingTests(unittest.TestCase):
    """圖紙清單要延到真的需要時才讀。

    按下按鈕就掃描全案子是錯的時機：那份資料要到使用者選完兩份 PDF、按下
    「比對」之後才用得到，而使用者常常只想比其中幾張圖。實測 538 張圖紙的
    專案因此每次都先卡住才看得到視窗。
    """

    def _compare(self, window, result):
        window.old_pdf = 'old.pdf'
        window.new_pdf = 'new.pdf'
        script.runner.run_worker = lambda *a, **k: result
        window.compare_clicked(None, None)

    def test_no_sheets_are_read_when_the_window_opens(self):
        calls = []
        script.PdfDiffWindow(None, sheet_loader=lambda pages:
                             calls.append(pages) or [])
        self.assertEqual([], calls, u'開視窗就不該讀圖紙')

    def test_the_loader_runs_on_compare_and_sees_the_pages(self):
        seen = []
        sheets = [sheet(u'A2-02', u'地下一層平面圖', u'0721B-ARD-D02001'),
                  sheet(u'A2-01', u'一層平面圖', u'0721B-ARD-D02002')]

        def loader(pages):
            seen.append(len(pages))
            return sheets

        window = script.PdfDiffWindow(None, sheet_loader=loader)
        self._compare(window, make_result())
        self.assertEqual([2], seen, u'loader 應該在比對後跑一次，且拿得到頁面')
        self.assertEqual(2, len(window.rows))

    def test_a_second_compare_does_not_reload_the_sheets(self):
        """讀過就留著——同一個 session 比第二次不該再掃一遍。"""
        calls = []
        sheets = [sheet(u'A2-02', u'地下一層平面圖', u'0721B-ARD-D02001')]

        def loader(pages):
            calls.append(1)
            return sheets

        window = script.PdfDiffWindow(None, sheet_loader=loader)
        self._compare(window, make_result())
        self._compare(window, make_result())
        self.assertEqual(1, len(calls))

    def test_cancelling_the_scan_leaves_the_window_usable(self):
        def loader(pages):
            raise script.sources.ScanCancelled()

        window = script.PdfDiffWindow(None, sheet_loader=loader)
        self._compare(window, make_result())
        self.assertEqual([], window.rows)
        self.assertEqual([], window.sheets)

    def test_labels_are_rebuilt_in_place_so_bound_combos_stay_valid(self):
        """``_sheet_labels`` 是所有下拉共用的 ItemsSource。

        重建時換成新的 list 的話，已經綁上去的下拉會繼續指著舊的那一份，
        使用者就會在下拉裡看到空的或過期的圖紙清單——不會報錯，只是選不到。
        """
        window = script.PdfDiffWindow(None, sheet_loader=lambda pages: [
            sheet(u'A2-02', u'地下一層平面圖', u'0721B-ARD-D02001'),
            sheet(u'A2-01', u'一層平面圖', u'0721B-ARD-D02002')])
        labels = window._sheet_labels
        self._compare(window, make_result())
        self.assertIs(labels, window._sheet_labels)
        self.assertEqual(3, len(labels))       # NO_SHEET + 兩張圖紙
        self.assertIs(labels, window.rows[0]['combo'].ItemsSource)

    def test_passing_sheets_directly_still_works(self):
        """已經有圖紙資料的呼叫端（含既有測試）不受影響。"""
        window = make_window()
        self.assertEqual(3, len(window.sheets))


class SelectionTests(unittest.TestCase):
    """勾選狀態與送出結果之間的資料流。

    `selected_pairings` 曾經自己重組一份快取 key，改了 `_box_for` 卻漏改它，
    導致查不到任何勾選框——**不崩潰、不報錯，一朵雲都建不出來**。
    """

    def test_default_ticks_reach_selected_pairings(self):
        window = make_window()
        pairings = window.selected_pairings()
        self.assertTrue(pairings, u'預設勾選的區域沒有進入 selected_pairings')
        self.assertEqual(3, len(pairings[0]['regions']))

    def test_revision_selection_returns_the_chosen_element_id(self):
        window = script.PdfDiffWindow(
            [sheet(u'A2-01', u'一層平面圖')],
            revisions=[{'ElementId': 7654, 'SequenceNumber': 3,
                        'Description': u'本次修訂', 'RevisionDate': u''}])
        self.assertIsNone(window._selected_revision_id())
        window.revisionCombo.SelectedIndex = 1
        self.assertEqual(7654, window._selected_revision_id())

    def test_unticking_removes_a_region_from_the_result(self):
        window = make_window()
        row = window.rows[0]
        target = row['page']['textRegions'][0]
        window._box_for(row, target).IsChecked = False
        regions = window.selected_pairings()[0]['regions']
        self.assertEqual(2, len(regions))
        self.assertNotIn(target, regions)

    def test_two_regions_with_the_same_label_are_ticked_independently(self):
        """撞號的兩個區域一度共用一個勾選框，勾一個等於勾兩個。"""
        window = make_window()
        row = window.rows[0]
        first, second = row['page']['textRegions'][0:2]
        self.assertIsNot(window._box_for(row, first),
                         window._box_for(row, second))
        window._box_for(row, first).IsChecked = False
        self.assertTrue(window._box_for(row, second).IsChecked)

    def test_an_unmapped_sheet_contributes_nothing(self):
        window = make_window()
        window.rows[0]['combo'].SelectedIndex = 0
        for pairing in window.selected_pairings():
            self.assertIsNot(pairing['page'], window.rows[0]['page'])

    def test_unchecked_sheet_is_excluded_from_selected_pairings(self):
        window = make_window()
        window.sheet_filter_boxes[id(window.rows[0])].IsChecked = False
        pairings = window.selected_pairings()
        self.assertTrue(pairings)
        self.assertNotIn(window.rows[0]['page'],
                         [pairing['page'] for pairing in pairings])

    def test_clearing_sheet_filter_means_all(self):
        window = make_window()
        for box in window.sheet_filter_boxes.values():
            box.IsChecked = False
        pairings = window.selected_pairings()
        self.assertEqual(2, len(pairings))

    def test_clearing_all_empties_the_result(self):
        window = make_window()
        window.clear_all_clicked(None, None)
        self.assertEqual([], window.selected_pairings())

    def test_the_status_count_matches_what_will_be_created(self):
        """使用者看到的數字必須等於按下去真的會建立的數量。"""
        window = make_window()
        window._update_status()
        created = sum(len(p['regions']) for p in window.selected_pairings())
        self.assertIn(u'已勾選 {} 個'.format(created), window.statusText.Text)

    def test_oversized_regions_are_not_ticked_by_default(self):
        window = make_window()
        window.modeCombo.SelectedIndex = 2
        window.filter_changed(window.modeCombo, None)
        window.hideOversizedCheck.IsChecked = False
        window.filter_changed(window.hideOversizedCheck, None)
        row = window.rows[0]
        big = [r for r in row['page']['regions'] if r['oversized']][0]
        self.assertFalse(window._box_for(row, big).IsChecked)


if __name__ == '__main__':
    unittest.main()
