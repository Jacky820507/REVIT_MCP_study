# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""兩份 PDF 圖說的差異比對，把差異圈成 Revit 修訂雲。

## 一個視窗走完全程

第一版把「選檔」丟給兩個 Windows 檔案對話框、比對完才開視窗，使用者在按下
第二個對話框之前完全看不到任何上下文——不知道選了什麼、不能改、也看不到
圖號有沒有讀對。這一版所有事情都在同一個視窗裡：選檔、看讀到的圖號圖名、
確認對應到哪一張 Revit 圖紙、挑要圈的區域、建立。

版面是 master-detail（左邊圖紙清單、右邊該圖的差異區域），因為這本質上是
一個 triage 工作流：逐張確認、分級、勾選。設計 token 集中在 XAML 的
``Window.Resources``——色票沿用專案既有的 ``#255783``，資訊層級參考
``linear.app``（單一強調色、四級文字灰階、髮絲邊框）。

## 三件刻意的取捨

* **雲畫在圖紙上，不畫進視圖裡。** PDF 頁座標到圖紙紙面座標是單純的比例
  對應，不必經過 viewport／crop／scale 換算，位置最不會歪。代價是雲不會跟著
  模型幾何跑。見 ``domain/pdf-drawing-diff-revision-cloud.md``。
* **勾選狀態存在 CheckBox 控制項本身，不做 binding。** IronPython 的物件不會
  發 ``INotifyPropertyChanged``，雙向 ``IsChecked`` binding 讀回來會是舊值——
  這個坑 ``RoomPurge`` 已經踩過並記錄過了。
* **每一頁的 Revit 圖紙都可以手動改。** 自動配對用圖號，而圖號是從圖框讀出來
  的；讀錯時使用者要能當場改，不必回去改設定重跑一趟。

實際比對的演算法在 ``pdf_diff_worker``（CPython 3 + PyMuPDF），座標換算在
``pdf_diff_logic``，Revit 取數在 ``pdf_diff_sources``。
"""

__title__ = u'圖說差異\n修訂雲'
__author__ = 'RevitMCP'

import os

from pyrevit import forms, revit
from System.Windows import FontWeights, TextWrapping, Thickness
from System.Windows.Controls import (Border, CheckBox, ComboBox, Orientation,
                                     StackPanel, TextBlock)
from System.Windows.Input import Cursors
from System.Windows.Media import Brushes, SolidColorBrush, Color

import mcp_bridge as mcp
import pdf_diff_logic as logic
import pdf_diff_runner as runner
import pdf_diff_sources as sources


TITLE = u'圖說差異 → 修訂雲'
NO_SHEET = u'（不建立雲形）'
NO_REVISION = u'（自動：沿用最新修訂；沒有則建立）'

# 圈雲依據。智慧模式把文字與線條都納入，但會把密集的大範圍幾何差異切成
# 可實際放置的局部雲；純文字與原始全部差異仍保留給需要人工複核的情境。
MODES = (
    (u'智慧圈選（文字＋線條，建議）', 'smartRegions'),
    (u'只圈文字變更', 'textRegions'),
    (u'全部差異（含線條增減）', 'regions'),
)

THRESHOLDS = (
    (u'標準', None),
    (u'寬鬆（更多區域，雜訊也多）', 2.0),
    (u'嚴格', 6.0),
    (u'很嚴格（只留大片變動）', 12.0),
)

_INK = SolidColorBrush(Color.FromRgb(0x1B, 0x27, 0x33))
_MUTED = SolidColorBrush(Color.FromRgb(0x5A, 0x6B, 0x7B))
_SUBTLE = SolidColorBrush(Color.FromRgb(0x8A, 0x99, 0xA8))
_BRAND = SolidColorBrush(Color.FromRgb(0x25, 0x57, 0x83))
_SUCCESS = SolidColorBrush(Color.FromRgb(0x15, 0x80, 0x3D))
_WARNING = SolidColorBrush(Color.FromRgb(0xB4, 0x53, 0x09))
_DANGER = SolidColorBrush(Color.FromRgb(0xB9, 0x1C, 0x1C))
_SEL_BG = SolidColorBrush(Color.FromRgb(0xE8, 0xF0, 0xF7))
_HAIRLINE = SolidColorBrush(Color.FromRgb(0xE2, 0xE8, 0xED))


def _text(value, size=13, brush=_INK, bold=False, wrap=False):
    block = TextBlock()
    block.Text = value
    block.FontSize = size
    block.Foreground = brush
    if bold:
        block.FontWeight = FontWeights.SemiBold
    if wrap:
        block.TextWrapping = TextWrapping.Wrap
    return block


class PdfDiffWindow(forms.WPFWindow):
    """一個視窗走完：選檔 → 比對 → 對應圖紙 → 勾選區域 → 建立。"""

    def __init__(self, sheets, reference_cloud_id=None, revisions=None):
        xaml = os.path.join(os.path.dirname(__file__), 'PdfDiffClouds.xaml')
        forms.WPFWindow.__init__(self, xaml)
        self.sheets = sheets
        self.reference_cloud_id = reference_cloud_id
        self.revisions = revisions or []
        self.result = None
        self.rows = []
        self.boxes = {}
        self.cards = {}
        self.sheet_filter_boxes = {}
        self.selected_row = None
        self.old_pdf = None
        self.new_pdf = None
        self.applied = False
        self._ready = False
        # 批次勾選期間暫停狀態更新：每個 CheckBox 的 Checked 事件都會
        # 觸發一次全量重數，213 個區域就是 213x213 次迴圈。
        self._bulk = False

        for label, unused in MODES:
            self.modeCombo.Items.Add(label)
        self.modeCombo.SelectedIndex = 0
        for label, unused in THRESHOLDS:
            self.thresholdCombo.Items.Add(label)
        self.thresholdCombo.SelectedIndex = 0

        self._sheet_labels = [NO_SHEET]
        for sheet in sheets:
            dwg = sheet.get('DwgNumber')
            dwg_label = (u'　DWG NO. {}'.format(dwg) if dwg else u'')
            self._sheet_labels.append(u'{}{}　{}'.format(
                sheet.get('SheetNumber'), dwg_label,
                sheet.get('SheetName') or u''))

        self.revisionCombo.Items.Add(NO_REVISION)
        for revision in self.revisions:
            self.revisionCombo.Items.Add(sources.revision_label(revision))
        self.revisionCombo.SelectedIndex = 0

        self._ready = True
        self._update_status()

    # --- 選檔 ------------------------------------------------------------

    def _set_path(self, box, path):
        box.Text = path if path else u'尚未選擇'
        box.Foreground = _INK if path else _SUBTLE

    def _refresh_compare_enabled(self):
        self.compareButton.IsEnabled = bool(self.old_pdf and self.new_pdf)

    def pick_old_clicked(self, sender, args):
        path = forms.pick_file(file_ext='pdf', title=u'選擇「舊版」PDF 圖說')
        if path:
            self.old_pdf = path
            self._set_path(self.oldPathText, path)
            self._refresh_compare_enabled()

    def pick_new_clicked(self, sender, args):
        path = forms.pick_file(file_ext='pdf', title=u'選擇「新版」PDF 圖說')
        if path:
            self.new_pdf = path
            self._set_path(self.newPathText, path)
            self._refresh_compare_enabled()

    # --- 比對 ------------------------------------------------------------

    def _overrides(self):
        options = {'excludeTitleBlock': bool(self.excludeTitleCheck.IsChecked)}
        index = self.thresholdCombo.SelectedIndex
        if index > 0:
            options['threshold'] = THRESHOLDS[index][1]
        return options

    def _selected_revision_id(self):
        index = self.revisionCombo.SelectedIndex
        if index <= 0 or index - 1 >= len(self.revisions):
            return None
        return self.revisions[index - 1].get('ElementId')

    def compare_clicked(self, sender, args):
        if os.path.abspath(self.old_pdf) == os.path.abspath(self.new_pdf):
            forms.alert(u'兩邊選到同一個檔案，沒有東西可以比。', title=TITLE)
            return
        with forms.ProgressBar(title=u'比對圖說中…（大份檔案可能要幾分鐘）',
                               indeterminate=True):
            try:
                self.result = runner.run_worker(
                    self.old_pdf, self.new_pdf, self._overrides())
            except RuntimeError as error:
                forms.alert(u'{}'.format(error), title=TITLE)
                return

        self._build_rows()
        if not self.rows:
            forms.alert(
                u'兩份 PDF 沒有任何一頁配對成功。\n\n'
                u'圖號是從圖框的「DWG NO.／圖號」欄位讀出來的；'
                u'若這份圖框用別的欄位名稱，就會讀不到。\n'
                u'舊版 {} 頁、新版 {} 頁。'.format(
                    self.result.get('pageCountA', 0),
                    self.result.get('pageCountB', 0)),
                title=TITLE)
            return
        self._render_sheets()
        self._select_row(self.rows[0])
        self._update_status()

    def _build_rows(self):
        """把 worker 的頁面與 Revit 圖紙配起來，一頁一列。"""
        self.rows = []
        self.boxes = {}
        self.cards = {}
        self.sheet_filter_boxes = {}
        pages = (self.result or {}).get('pages') or []
        matched, unmatched, unused = logic.pair_sheets(pages, self.sheets)
        self.unused_sheets = unused

        by_page = {}
        for pairing in matched:
            by_page[id(pairing['page'])] = pairing
        for page in pages:
            pairing = by_page.get(id(page))
            self.rows.append({
                'page': page,
                'sheet': pairing['sheet'] if pairing else None,
                'match': pairing['match'] if pairing else None,
                'matchField': pairing.get('matchField') if pairing else None,
                'combo': None,
                'border': None,
                'badge': None,
                'card': None,
            })
        self._render_sheet_filters()

    # --- 圖紙多選 ----------------------------------------------------------

    def _sheet_filter_label(self, row):
        page = row.get('page') or {}
        parts = [page.get('sheetNumber') or u'（讀不到圖號）',
                 page.get('sheetName') or u'（讀不到圖名）']
        sheet = row.get('sheet')
        if sheet is not None:
            parts.append(u'→ Revit {}'.format(sheet.get('SheetNumber') or u'?'))
        return u'　'.join(parts)

    def _render_sheet_filters(self):
        """建立欲標圖紙的多選清單；預設全部勾選。"""
        self.sheetFilterList.Children.Clear()
        for row in self.rows:
            box = CheckBox()
            box.Content = self._sheet_filter_label(row)
            box.IsChecked = True
            box.Margin = Thickness(0, 1, 0, 1)
            box.Tag = row
            box.Checked += self._sheet_filter_changed
            box.Unchecked += self._sheet_filter_changed
            self.sheet_filter_boxes[id(row)] = box
        self._update_sheet_filter_status()

    def _selected_sheet_rows(self):
        """回傳明確勾選的圖紙；全部取消時回 ``None`` 代表全選。"""
        selected = []
        for row in self.rows:
            box = self.sheet_filter_boxes.get(id(row))
            if box is not None and box.IsChecked:
                selected.append(row)
        return selected or None

    def _row_is_sheet_selected(self, row):
        selected = self._selected_sheet_rows()
        return selected is None or row in selected

    def _update_sheet_filter_status(self):
        if not hasattr(self, 'sheetFilterStatus'):
            return
        selected = self._selected_sheet_rows()
        if selected is None:
            self.sheetFilterStatus.Text = u'未指定圖紙：視為全部 ({})'.format(
                len(self.rows))
        else:
            self.sheetFilterStatus.Text = u'已選 {} / {} 張圖紙'.format(
                len(selected), len(self.rows))

    def _sheet_filter_changed(self, sender, args):
        self._update_sheet_filter_status()
        if not self._ready or not self.rows:
            return
        self._refresh_badges()
        if self.selected_row is not None:
            self._render_regions(self.selected_row)
        self._update_status()

    # --- 左欄：圖紙清單 ---------------------------------------------------

    def _mode_key(self):
        index = max(0, self.modeCombo.SelectedIndex)
        return MODES[index][1]

    def _regions_of(self, row):
        if not self._row_is_sheet_selected(row):
            return []
        regions = row['page'].get(self._mode_key()) or []
        if self.hideOversizedCheck.IsChecked:
            regions = [r for r in regions if not r.get('oversized')]
        return regions

    def _combo_for(self, row):
        if row['combo'] is not None:
            return row['combo']
        combo = ComboBox()
        for label in self._sheet_labels:
            combo.Items.Add(label)
        combo.SelectedIndex = 0
        if row['sheet'] is not None:
            try:
                combo.SelectedIndex = self.sheets.index(row['sheet']) + 1
            except ValueError:
                combo.SelectedIndex = 0
        combo.SelectionChanged += self._combo_changed
        row['combo'] = combo
        return combo

    def _combo_changed(self, sender, args):
        self._update_status()

    def _render_sheets(self):
        """建立左欄卡片。**每次比對只能呼叫一次。**

        不可以在切換篩選時重建：卡片裡的 ComboBox 是快取重用的，而
        **WPF 元素只能有一個邏輯父層**——舊的 StackPanel 仍然握著它，
        重新掛到新卡片上會丟 InvalidOperationException。那個例外發生在 WPF
        的事件處理常式裡，實測會直接把 Revit 拖垮（「發生嚴重錯誤，應用程式
        將終止」）。換模式只改 badge 的字，見 :meth:`_refresh_badges`。
        """
        self.sheetList.Children.Clear()
        added = set()
        for row in self.rows:
            card = self._sheet_card(row)
            if id(card) in added:
                continue
            added.add(id(card))
            self.sheetList.Children.Add(card)
        self._ensure_boxes()
        self._refresh_badges()

    def _refresh_badges(self):
        """只更新「N 個區域」的計數，不動任何控制項的父子關係。"""
        for row in self.rows:
            badge = row.get('badge')
            if badge is None:
                continue
            count = len(self._regions_of(row))
            badge.Text = u'　{} 個區域'.format(count)
            badge.Foreground = _MUTED if count else _SUBTLE

    def _sheet_card(self, row):
        """整張卡片快取，理由與 :meth:`_region_card` 相同。

        目前 ``_render_sheets`` 只會被呼叫一次，所以不快取也不會出事——但那是
        靠「呼叫時序」在保護，不是靠結構。卡片裡的 ComboBox 一旦被重掛就會
        終止 Revit 行程，這種代價不該押在時序假設上。
        """
        if row.get('card') is not None:
            return row['card']

        page = row['page']
        panel = StackPanel()
        panel.Margin = Thickness(12, 8, 12, 8)

        head = StackPanel()
        head.Orientation = Orientation.Horizontal
        head.Children.Add(_text(page.get('sheetNumber') or u'（讀不到圖號）',
                                13, _INK, bold=True))
        # badge 留著給 _refresh_badges 更新——換模式時只改這個字，
        # 不重建整張卡片。原因見 _render_sheets 的說明。
        badge = _text(u'', 11, _MUTED)
        row['badge'] = badge
        head.Children.Add(badge)
        panel.Children.Add(head)

        panel.Children.Add(_text(page.get('sheetName') or u'（讀不到圖名）',
                                 12, _MUTED))

        arrow = StackPanel()
        arrow.Orientation = Orientation.Horizontal
        arrow.Margin = Thickness(0, 6, 0, 0)
        arrow.Children.Add(_text(u'→ ', 12, _SUBTLE))
        combo = self._combo_for(row)
        combo.Width = 330
        arrow.Children.Add(combo)
        panel.Children.Add(arrow)

        if row['match'] == 'loose':
            if row.get('matchField') == 'DwgNumber':
                panel.Children.Add(_text(
                    u'DWG NO. 寬鬆比對，請確認；Revit 內部圖號：{}'.format(
                        row['sheet'].get('SheetNumber')), 11, _WARNING))
            else:
                panel.Children.Add(_text(u'寬鬆比對，請確認', 11, _WARNING))
        elif row.get('matchField') == 'DwgNumber':
            panel.Children.Add(_text(
                u'DWG NO. 已配對；Revit 內部圖號：{}'.format(
                    row['sheet'].get('SheetNumber')), 11, _SUCCESS))
        elif row['match'] is None:
            panel.Children.Add(_text(u'自動配不到，請手動指定', 11, _DANGER))

        for warning in page.get('warnings') or []:
            panel.Children.Add(_text(warning, 11, _WARNING, wrap=True))

        border = Border()
        border.BorderBrush = _HAIRLINE
        border.BorderThickness = Thickness(0, 0, 0, 1)
        border.Background = Brushes.Transparent
        border.Cursor = Cursors.Hand
        border.Child = panel
        border.MouseLeftButtonUp += self._make_row_click(row)
        row['border'] = border
        row['card'] = border
        return border

    def _make_row_click(self, row):
        def handler(sender, args):
            self._select_row(row)
        return handler

    def _select_row(self, row):
        self.selected_row = row
        for other in self.rows:
            if other['border'] is not None:
                other['border'].Background = (
                    _SEL_BG if other is row else Brushes.Transparent)
        self._render_regions(row)

    # --- 右欄：差異區域 ---------------------------------------------------

    def _region_key(self, row, region):
        """用物件識別當 key，**不要用 (gridLabel, score)**。

        那組值會撞：實測使用者的圖說第 1 頁有兩個區域都叫 ``J4`` 且分數都是
        9.0，第 2 頁有 6 組撞號。撞號的後果有兩層——

        1. **崩潰**：``_region_card`` 對兩個不同區域回傳同一張快取 Border，
           同一次繪製裡加兩次就丟「指定的 Visual 已經是另一個 Visual 的
           子項目」，而這個例外在 WPF 事件處理常式裡會終止 Revit。
        2. **靜默算錯**：兩個區域共用一個 CheckBox，勾一個等於勾兩個，
           送進 ``build_cloud_requests`` 的會是錯的集合。第 2 點更糟——
           它不會報錯。

        ``id()`` 在這裡是安全的：region dict 由 ``self.result`` 持有，
        存活期間 id 穩定且唯一；重新比對時 ``_build_rows`` 會連同 result
        一起換掉並清空快取。``logic.pair_sheets`` 也用同一個慣用法。
        """
        return id(region)

    def _box_for(self, row, region):
        """勾選框建立後就留著，換篩選條件不會弄丟勾選。"""
        key = self._region_key(row, region)
        box = self.boxes.get(key)
        if box is not None:
            return box
        box = CheckBox()
        box.IsChecked = not region.get('oversized')
        box.Margin = Thickness(0, 0, 0, 0)
        box.Checked += self._tick_changed
        box.Unchecked += self._tick_changed
        box.Tag = region
        self.boxes[key] = box
        return box

    def _ensure_boxes(self):
        """先把目前模式下所有區域的勾選框都建起來。

        不先建會出事：``clear_all_clicked`` 只能清掉「已經被瀏覽過」的框，
        之後 ``_update_status`` 又會用預設值（勾選）把沒建過的補出來——
        按了「全部取消」，沒看過的圖紙仍然是勾著的，而且狀態列的數字也
        會跟著跳回去。使用者沒有理由知道「有沒有看過」會影響勾選。
        """
        for row in self.rows:
            for region in self._regions_of(row):
                self._box_for(row, region)

    def _tick_changed(self, sender, args):
        if self._bulk:
            return
        self._update_status()

    def _render_regions(self, row):
        self.regionList.Children.Clear()
        page = row['page']
        self.detailLabel.Text = u'差異區域　{}　{}'.format(
            page.get('sheetNumber') or u'?', page.get('sheetName') or u'')

        raw_a = page.get('itemCountA', 0)
        raw_b = page.get('itemCountB', 0)
        filtered_a = page.get('itemCountAAfterRevisionCloudFilter', raw_a)
        filtered_b = page.get('itemCountBAfterRevisionCloudFilter', raw_b)
        cloud_a = page.get('revisionCloudsA', 0)
        cloud_b = page.get('revisionCloudsB', 0)
        cloud_masked = page.get('revisionCloudMaskedDiffs', 0)
        cloud_note = (
            u'　剔除既有雲 {}→{} 組，遮罩 {} 筆差異'.format(
                cloud_a, cloud_b, cloud_masked)
            if cloud_a or cloud_b else u'')
        summary = _text(
            u'圖元 {}→{}（剔除後 {}→{}）　文字變更 {} 處{}'.format(
                raw_a, raw_b, filtered_a, filtered_b,
                page.get('textDiffs', 0), cloud_note),
            11, _SUBTLE, wrap=True)
        summary.Margin = Thickness(0, 0, 0, 8)
        self.regionList.Children.Add(summary)

        regions = self._regions_of(row)
        if not self._row_is_sheet_selected(row):
            self.regionList.Children.Add(
                _text(u'這張圖紙目前未勾選，不會建立雲形。', 12, _WARNING))
            return
        if not regions:
            self.regionList.Children.Add(
                _text(u'這一頁在目前的條件下沒有可圈的區域。', 12, _SUBTLE))
            return

        # 同一次繪製裡絕不重複掛同一個 visual。key 已經修成唯一了，這是
        # 第二道防線——這一類錯誤的代價是整個 Revit 行程被終止，不值得
        # 只靠「key 應該是唯一的」這個假設。
        added = set()
        for region in regions:
            card = self._region_card(row, region)
            if id(card) in added:
                continue
            added.add(id(card))
            self.regionList.Children.Add(card)

    def _region_card(self, row, region):
        """回傳整張卡片，且**整張快取**。

        只快取 CheckBox 是不夠的：``Panel.Children.Clear()`` 只釋放**直接
        子層**的父子關係，而 CheckBox 埋在 ``Border -> StackPanel`` 底下，
        那一層關係不會被釋放。把它掛到新建的 StackPanel 上會丟
        InvalidOperationException（元素已經是別人的邏輯子項），而這個例外
        發生在 WPF 事件處理常式裡會把 Revit 一起帶走。

        快取整張 Border 就沒事——它的父層就是被 Clear 的那個 panel。
        """
        key = self._region_key(row, region)
        cached = self.cards.get(key)
        if cached is not None:
            return cached

        line = StackPanel()
        line.Orientation = Orientation.Horizontal
        line.Children.Add(self._box_for(row, region))

        body = StackPanel()
        body.Margin = Thickness(8, 0, 0, 0)

        head = StackPanel()
        head.Orientation = Orientation.Horizontal
        head.Children.Add(_text(region.get('gridLabel') or u'?', 12, _BRAND,
                                bold=True))
        # 百分比一律走 logic.format_fraction_percent——IronPython 2.7 對 int
        # 套精度格式會丟 ValueError，而 `or 0` 剛好會把 0.0 變成 int。
        head.Children.Add(_text(
            u'　佔頁面 {}　文字 {} ／ 線條 {}'.format(
                logic.format_fraction_percent(region.get('pageFraction')),
                region.get('textCount', 0), region.get('geomCount', 0)),
            11, _SUBTLE))
        if region.get('oversized'):
            head.Children.Add(_text(u'　範圍過大', 11, _WARNING))
        body.Children.Add(head)

        for sample in (region.get('samples') or [])[:3]:
            body.Children.Add(_text(self._sample_line(sample), 12, _MUTED,
                                    wrap=True))

        line.Children.Add(body)

        border = Border()
        border.Padding = Thickness(0, 6, 0, 6)
        border.BorderBrush = _HAIRLINE
        border.BorderThickness = Thickness(0, 0, 0, 1)
        border.Child = line
        self.cards[key] = border
        return border

    def _sample_line(self, sample):
        kind = sample.get('kind')
        before = sample.get('before') or u''
        after = sample.get('after') or u''
        if kind == 'text-change':
            return u'{} → {}'.format(before, after)
        if kind == 'text-add':
            return u'新增　{}'.format(after)
        if kind == 'text-delete':
            return u'刪除　{}'.format(before)
        if kind == 'text-move':
            return u'位移　{}'.format(before or after)
        return u'線條增減'

    # --- 狀態與取值 -------------------------------------------------------

    def selected_pairings(self):
        pairings = []
        for row in self.rows:
            combo = row['combo']
            if combo is None or combo.SelectedIndex <= 0:
                continue
            sheet = self.sheets[combo.SelectedIndex - 1]
            regions = []
            # key 一律走 _region_key／_box_for，不要在這裡重組一份。
            # 之前這裡自己組了 (gridLabel, score)，改了 _box_for 卻漏改這裡，
            # 結果 boxes.get() 永遠回 None——**不崩潰、不報錯，只是一朵雲都
            # 建不出來**。靜默算錯比崩潰難查得多。
            for region in self._regions_of(row):
                if self._box_for(row, region).IsChecked:
                    regions.append(region)
            if regions:
                pairings.append({'page': row['page'], 'sheet': sheet,
                                 'regions': regions})
        return pairings

    def _update_status(self):
        if not self._ready:
            return
        if not self.rows:
            self.statusText.Text = u'尚未比對。'
            self.okButton.IsEnabled = False
            return
        # 只數「目前模式下看得到的區域」，而且用 _box_for 確保每個都有勾選框。
        # 之前數的是 self.boxes 全部的值——那會把另一個模式的框也算進去，
        # 而且沒被瀏覽過的圖紙根本還沒建框，計數會比實際少。使用者看到的
        # 數字必須等於按下去真的會建立的數量。
        ticked = 0
        total = 0
        for row in self.rows:
            for region in self._regions_of(row):
                total += 1
                if self._box_for(row, region).IsChecked:
                    ticked += 1
        mapped = len([r for r in self.rows
                      if self._row_is_sheet_selected(r)
                      and r['combo'] is not None and r['combo'].SelectedIndex > 0])
        self.statusText.Text = (
            u'{} 頁配對成功，其中 {} 頁已指定 Revit 圖紙　·　'
            u'目前條件下共 {} 個區域，已勾選 {} 個').format(
                len(self.rows), mapped, total, ticked)
        self.okButton.IsEnabled = ticked > 0 and mapped > 0

    # --- handlers ---------------------------------------------------------

    def filter_changed(self, sender, args):
        if not self._ready or not self.rows:
            return
        # 只更新計數與右欄；**不重建左欄**（會扯斷 ComboBox 的父子關係）。
        self._ensure_boxes()
        self._refresh_badges()
        if self.selected_row is not None:
            self._render_regions(self.selected_row)
        self._update_status()

    def select_shown_clicked(self, sender, args):
        self._bulk = True
        try:
            for row in self.rows:
                for region in self._regions_of(row):
                    self._box_for(row, region).IsChecked = True
        finally:
            self._bulk = False
        self._update_status()

    def clear_all_clicked(self, sender, args):
        self._bulk = True
        try:
            self._ensure_boxes()
            for box in self.boxes.values():
                box.IsChecked = False
        finally:
            self._bulk = False
        self._update_status()

    def cancel_clicked(self, sender, args):
        self.Close()

    def ok_clicked(self, sender, args):
        pairings = self.selected_pairings()
        if not pairings:
            forms.alert(u'沒有勾選任何區域，模型未變更。', title=TITLE)
            return
        if bool(self.removeManualOverlapCheck.IsChecked):
            if not forms.alert(
                    u'你勾選了「包含手動雲」。執行時會刪除與新版差異重疊的'
                    u'未標記修訂雲，這些可能是你手動建立的雲。確定繼續嗎？',
                    title=TITLE, yes=True, no=True):
                return
        if _apply(
                pairings, self.reference_cloud_id,
                self._selected_revision_id(),
                bool(self.removeOverlapCheck.IsChecked),
                bool(self.removeManualOverlapCheck.IsChecked)):
            self.applied = True
            self.Close()


def _apply(pairings, reference_cloud_id=None, revision_id=None,
           remove_overlapping=True,
           remove_manual_overlaps=False):
    """換算成圖紙座標並呼叫 C# 建雲。回傳是否真的套用了。"""
    options = {}
    if reference_cloud_id is not None:
        options['referenceCloudId'] = reference_cloud_id
    if revision_id is not None:
        options['revisionId'] = revision_id
    clouds, skipped = logic.build_cloud_requests(pairings, options)
    if not clouds:
        forms.alert(u'沒有可建立的雲形。\n\n{}'.format(
            logic.summarize(clouds, skipped)), title=TITLE)
        return False

    def _describe(data):
        if not isinstance(data, dict):
            return mcp.brief(data)
        created = data.get('Created') or []
        cloud_skipped = data.get('Skipped') or []
        lines = [u'修訂：{}'.format(data.get('RevisionUsed')),
                 u'雲形 {} 朵'.format(len(created))]
        removed = data.get('Removed') or []
        manual_overlaps = data.get('ManualOverlaps') or []
        lines.append(u'清除重複舊雲 {} 朵'.format(len(removed)))
        if manual_overlaps:
            lines.append(u'保留未標記／手動重疊雲 {} 朵：{}'.format(
                len(manual_overlaps),
                u'、'.join(u'{}'.format(item.get('ElementId'))
                          for item in manual_overlaps[:12])))
        orientation = data.get('CloudOrientation')
        if orientation:
            lines.append(u'方向：{}'.format(orientation))
        for item in created[:12]:
            number = item.get('PdfDwgNumber') or item.get('SheetNumber')
            internal = item.get('SheetNumber')
            suffix = (u'（Revit {}）'.format(internal)
                      if item.get('PdfDwgNumber') and internal != number
                      else u'')
            lines.append(u'  {}{} {}'.format(number, suffix,
                                             item.get('GridLabel')))
        if len(created) > 12:
            lines.append(u'  …其餘 {} 朵'.format(len(created) - 12))
        if cloud_skipped:
            lines.append(u'')
            lines.append(u'Revit 端跳過 {} 筆：'.format(len(cloud_skipped)))
            for item in cloud_skipped[:6]:
                lines.append(u'  {} {}　{}'.format(
                    item.get('SheetNumber'), item.get('GridLabel') or u'',
                    item.get('Reason')))
        return u'\n'.join(lines)

    if skipped:
        forms.alert(u'有 {} 筆在換算階段就被跳過：\n\n{}'.format(
            len(skipped), logic.summarize(clouds, skipped)), title=TITLE)

    request_options = {
        'removeOverlapping': remove_overlapping,
        'removeManualOverlaps': remove_manual_overlaps,
        'overlapToleranceMm': 3.0,
        'autoCommentPrefix': logic.AUTO_COMMENT_PREFIX,
    }
    if revision_id is not None:
        request_options['revisionId'] = revision_id
    dry_run_request = {'clouds': clouds, 'dryRun': True}
    apply_request = {'clouds': clouds, 'dryRun': False}
    dry_run_request.update(request_options)
    apply_request.update(request_options)
    return mcp.dry_run_then_apply(
        'create_revision_clouds_on_sheets',
        dry_run_request, apply_request,
        TITLE, _describe) is not None


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件。', title=TITLE, exitscript=True)

    sheets = sources.sheet_records(doc)
    if not sheets:
        forms.alert(u'這個專案沒有圖紙，雲形沒有地方可畫。', title=TITLE)
        return

    revisions = sources.revision_records(doc)
    reference_cloud_id = sources.selected_revision_cloud_id(doc, revit.uidoc)
    PdfDiffWindow(sheets, reference_cloud_id, revisions).ShowDialog()


try:
    main()
except mcp.MCPBridgeError as error:
    mcp.show_error(error, TITLE)
