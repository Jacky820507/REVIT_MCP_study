# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""共用 WPF 視窗——把 ``mcp_window_logic`` 的欄位規格畫出來.

所有 MCP 巨集按鈕共用 ``mcp_window.xaml`` 這一個外殼，欄位在這裡依規格於
code-behind 建立。不做 data binding：IronPython 的純物件不會發
``INotifyPropertyChanged``，綁上去只會得到一個不會更新的畫面。

這一層刻意做薄。要問什麼、怎麼驗、值長什麼樣，全在 ``mcp_window_logic``
（CPython 測得到）；這裡只剩「建控制項、讀控制項、轉手」。

兩種用法：

``ask(spec)``
    收集答案後關閉，回傳 ``{key: value}``，取消回 ``None``。這是連珠對話框的
    直接替代品，按鈕原有的流程一行都不用改。

``run(spec, handler)``
    視窗留著。``handler(values, window)`` 回傳 ``logic.result(...)`` 顯示在
    結果頁，使用者可以改條件重跑——**這才是換成視窗真正的收穫**：答案互相
    影響時，微調不必從第一題重來。

**``run()`` 的 handler 只能讀，不可以開 Transaction。** Revit 在 modal 視窗
開啟期間不允許修改文件，試放（``trial_*``）也算修改。所以會寫入模型的按鈕
一律用 ``ask()``：視窗只負責收值，關掉之後才做 dry-run、預覽、確認與寫入。
唯讀檢核才適合 ``run()``。這條界線不是風格偏好——弄反了會在使用者按下按鈕
之後才炸，而且訊息通常看不出原因。
"""

import os

from pyrevit import forms

from System.Windows import GridLength, GridUnitType, HorizontalAlignment
from System.Windows import Thickness, VerticalAlignment, Visibility
from System.Windows.Controls import Border, Button, CheckBox, ColumnDefinition
from System.Windows.Controls import ComboBox, Grid, Orientation, RowDefinition
from System.Windows.Controls import ScrollViewer, ScrollBarVisibility
from System.Windows.Controls import StackPanel, TextBlock, TextBox

import mcp_window_logic as logic


XAML = os.path.join(os.path.dirname(__file__), 'mcp_window.xaml')

# 複選清單超過這個項數就固定高度加捲軸，否則一個 60 層的樓層清單會把視窗
# 撐到螢幕外，而動作列被推出畫面外就等於沒有取消鈕。
LIST_SCROLL_AFTER = 8
LIST_MAX_HEIGHT = 260

TONE_BRUSHES = {
    'info': ('BrandTint', 'Text'),
    'warning': ('WarningTint', 'Warning'),
    'danger': ('DangerTint', 'Danger'),
    'success': ('BrandTint', 'Success'),
}


def _thickness(left, top, right, bottom):
    return Thickness(left, top, right, bottom)


class McpWindow(forms.WPFWindow):
    """依規格建出來的共用視窗。"""

    def __init__(self, spec, handler=None):
        forms.WPFWindow.__init__(self, XAML)
        self.spec = spec
        self.handler = handler
        self.values = logic.defaults(spec.get('fields'))
        self.result = None
        self.accepted = False
        self.controls = {}
        self.error_blocks = {}
        self.field_panels = {}
        self._ready = False

        self.Title = u'{} — RevitMCP'.format(spec.get('title') or u'RevitMCP')
        self.titleText.Text = spec.get('title') or u'RevitMCP'
        self.subtitleText.Text = spec.get('subtitle') or u''
        if not (spec.get('subtitle') or u''):
            self.subtitleText.Visibility = Visibility.Collapsed
        self.badgeText.Text = spec.get('badge') or logic.BADGE_READONLY
        self.footnoteText.Text = spec.get('footnote') or u''
        self.runButton.Content = spec.get('run_label') or u'執行'

        secondary = spec.get('secondary_label') or u''
        if secondary:
            self.secondaryButton.Content = secondary
            self.secondaryButton.Visibility = Visibility.Visible
            self.secondaryButton.IsEnabled = False

        if spec.get('width'):
            self.Width = spec['width']
        if spec.get('height'):
            self.Height = spec['height']

        self.runButton.Click += self.run_clicked
        self.cancelButton.Click += self.cancel_clicked
        self.secondaryButton.Click += self.secondary_clicked

        self._build_fields()
        self._ready = True
        self._refresh_enabled()

    # --- 建欄位 ------------------------------------------------------------

    def _res(self, key):
        try:
            return self.Resources[key]
        except Exception:
            return None

    def _styled(self, control, style_key):
        style = self._res(style_key)
        if style is not None:
            control.Style = style
        return control

    def _block(self, text, style_key):
        block = TextBlock()
        block.Text = text or u''
        return self._styled(block, style_key)

    def _build_fields(self):
        for field in self.spec.get('fields') or []:
            panel = self._build_field(field)
            if panel is None:
                continue
            self.fieldHost.Children.Add(panel)
            key = field.get('key')
            if key:
                self.field_panels[key] = panel

    def _build_field(self, field):
        kind = field.get('kind')
        if kind == logic.SECTION:
            return self._build_section(field)
        if kind == logic.NOTE:
            return self._build_note(field)

        panel = StackPanel()
        panel.Margin = _thickness(0, 0, 0, 16)

        if kind != logic.BOOL:
            panel.Children.Add(self._block(field.get('label'), 'Label'))

        control = None
        if kind == logic.CHOICE:
            control = self._build_choice(field)
        elif kind == logic.MULTICHOICE:
            control = self._build_multichoice(field, panel)
        elif kind == logic.TEXT:
            control = self._build_text(field)
        elif kind == logic.NUMBER:
            control = self._build_number(field)
        elif kind == logic.BOOL:
            control = self._build_bool(field)
        if control is not None:
            panel.Children.Add(control)

        if field.get('help'):
            panel.Children.Add(self._block(field['help'], 'Help'))

        error = self._block(u'', 'FieldError')
        error.Visibility = Visibility.Collapsed
        panel.Children.Add(error)
        self.error_blocks[field.get('key')] = error
        return panel

    def _build_section(self, field):
        panel = StackPanel()
        panel.Margin = _thickness(0, 8, 0, 12)
        panel.Children.Add(self._block(field.get('label'), 'H2'))
        if field.get('help'):
            panel.Children.Add(self._block(field['help'], 'Help'))
        line = Border()
        line.Height = 1
        line.Margin = _thickness(0, 8, 0, 0)
        brush = self._res('Border')
        if brush is not None:
            line.Background = brush
        panel.Children.Add(line)
        return panel

    def _build_note(self, field):
        background, foreground = TONE_BRUSHES.get(
            field.get('tone') or 'info', TONE_BRUSHES['info'])
        border = Border()
        border.Padding = _thickness(12, 10, 12, 10)
        border.Margin = _thickness(0, 0, 0, 16)
        radius = self._res('RadiusControl')
        if radius is not None:
            border.CornerRadius = radius
        fill = self._res(background)
        if fill is not None:
            border.Background = fill
        block = TextBlock()
        block.Text = field.get('help') or u''
        self._styled(block, 'Help')
        block.Margin = _thickness(0, 0, 0, 0)
        ink = self._res(foreground)
        if ink is not None:
            block.Foreground = ink
        border.Child = block
        return border

    def _build_choice(self, field):
        combo = ComboBox()
        options = logic.unique_labels(field.get('options'))
        field['options'] = options
        for label, unused in options:
            combo.Items.Add(label)
        default = field.get('default')
        index = -1
        for position, (unused, value) in enumerate(options):
            if value == default:
                index = position
                break
        # 沒有指定預設就選第一項：一個「請選擇」的空狀態在單選裡只是多一次
        # 點擊，而規格要真的允許未選時會把 required 設成 False 並自己給 None。
        if index < 0 and options and field.get('required'):
            index = 0
        combo.SelectedIndex = index
        if index >= 0:
            self.values[field['key']] = options[index][1]
        combo.SelectionChanged += self._changed
        self.controls[field['key']] = combo
        return combo

    def _build_multichoice(self, field, panel):
        options = logic.unique_labels(field.get('options'))
        field['options'] = options
        chosen = set(field.get('default') or [])

        if field.get('actions') and len(options) > 2:
            actions = StackPanel()
            actions.Orientation = Orientation.Horizontal
            actions.Margin = _thickness(0, 0, 0, 6)
            actions.Children.Add(self._micro(u'全選', field['key'], True))
            actions.Children.Add(self._micro(u'全部取消', field['key'], False))
            panel.Children.Add(actions)

        stack = StackPanel()
        stack.Margin = _thickness(12, 8, 12, 8)
        boxes = []
        for label, value in options:
            box = CheckBox()
            box.Content = label
            box.IsChecked = value in chosen
            box.Checked += self._changed
            box.Unchecked += self._changed
            box.Tag = value
            stack.Children.Add(box)
            boxes.append(box)
        self.controls[field['key']] = boxes

        frame = Border()
        self._styled(frame, 'ListFrame')
        if len(options) > LIST_SCROLL_AFTER:
            viewer = ScrollViewer()
            viewer.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
            viewer.MaxHeight = LIST_MAX_HEIGHT
            viewer.Content = stack
            frame.Child = viewer
        else:
            frame.Child = stack
        return frame

    def _micro(self, label, key, state):
        button = Button()
        button.Content = label
        self._styled(button, 'MicroButton')
        button.Tag = (key, state)
        button.Click += self._bulk_clicked
        return button

    def _build_text(self, field):
        box = TextBox()
        box.Text = field.get('default') or u''
        box.TextChanged += self._changed
        self.controls[field['key']] = box
        return box

    def _build_number(self, field):
        row = Grid()
        row.ColumnDefinitions.Add(ColumnDefinition())
        unit_column = ColumnDefinition()
        unit_column.Width = GridLength(1, GridUnitType.Auto)
        row.ColumnDefinitions.Add(unit_column)

        box = TextBox()
        default = field.get('default')
        box.Text = u'' if default is None else u'{:g}'.format(float(default))
        box.MaxWidth = 200
        box.HorizontalAlignment = HorizontalAlignment.Left
        box.MinWidth = 140
        box.TextChanged += self._changed
        Grid.SetColumn(box, 0)
        row.Children.Add(box)

        if field.get('unit'):
            unit = self._block(field['unit'], 'Help')
            unit.Margin = _thickness(8, 0, 0, 0)
            unit.VerticalAlignment = VerticalAlignment.Center
            Grid.SetColumn(unit, 1)
            row.Children.Add(unit)

        self.controls[field['key']] = box
        return row

    def _build_bool(self, field):
        box = CheckBox()
        box.Content = field.get('label') or u''
        box.IsChecked = bool(field.get('default'))
        box.Checked += self._changed
        box.Unchecked += self._changed
        self.controls[field['key']] = box
        return box

    # --- 讀值 --------------------------------------------------------------

    def _read(self):
        for field in logic.input_fields(self.spec.get('fields')):
            key = field['key']
            kind = field['kind']
            control = self.controls.get(key)
            if control is None:
                continue
            if kind == logic.CHOICE:
                index = control.SelectedIndex
                options = field.get('options') or []
                self.values[key] = (options[index][1]
                                    if 0 <= index < len(options) else None)
            elif kind == logic.MULTICHOICE:
                self.values[key] = [box.Tag for box in control
                                    if box.IsChecked]
            elif kind == logic.BOOL:
                self.values[key] = bool(control.IsChecked)
            else:
                self.values[key] = control.Text

    def _changed(self, sender, args):
        if not self._ready:
            return
        self._read()
        self._refresh_enabled()

    def _bulk_clicked(self, sender, args):
        key, state = sender.Tag
        for box in self.controls.get(key) or []:
            box.IsChecked = state
        self._changed(sender, args)

    def _refresh_enabled(self):
        """依目前答案啟用／停用連動欄位。

        停用的欄位是**變灰而不是消失**：欄位突然不見會讓人以為視窗壞了，
        而灰掉還看得到它為什麼在那裡。
        """
        for field in self.spec.get('fields') or []:
            key = field.get('key')
            panel = self.field_panels.get(key)
            if panel is None:
                continue
            panel.IsEnabled = logic.is_enabled(field, self.values)

    # --- 狀態 --------------------------------------------------------------

    def status(self, message, tone='info'):
        if not message:
            self.statusBorder.Visibility = Visibility.Collapsed
            return
        background, foreground = TONE_BRUSHES.get(tone, TONE_BRUSHES['info'])
        fill = self._res(background)
        if fill is not None:
            self.statusBorder.Background = fill
        ink = self._res(foreground)
        if ink is not None:
            self.statusText.Foreground = ink
        self.statusText.Text = message
        self.statusBorder.Visibility = Visibility.Visible

    def _show_errors(self, errors):
        for key, block in self.error_blocks.items():
            message = errors.get(key) if key else None
            if message:
                block.Text = message
                block.Visibility = Visibility.Visible
            else:
                block.Visibility = Visibility.Collapsed

    # --- 結果頁 ------------------------------------------------------------

    def show_result(self, result):
        self.summaryHost.Children.Clear()
        self.resultGrid.Children.Clear()
        self.resultGrid.RowDefinitions.Clear()
        self.resultGrid.ColumnDefinitions.Clear()

        for line in result.get('summary') or []:
            self.summaryHost.Children.Add(self._block(line, 'Help'))

        columns = result.get('columns') or []
        rows, note = logic.truncate_rows(result.get('rows'))
        if note:
            self.summaryHost.Children.Add(self._block(note, 'Help'))
        if not columns:
            self.resultTab.IsEnabled = True
            self.tabs.SelectedIndex = 1
            return

        for unused in columns:
            self.resultGrid.ColumnDefinitions.Add(ColumnDefinition())
        header = RowDefinition()
        header.Height = GridLength(1, GridUnitType.Auto)
        self.resultGrid.RowDefinitions.Add(header)
        for position, title in enumerate(columns):
            self.resultGrid.Children.Add(
                self._cell(title, 0, position, header=True))

        for index, row in enumerate(rows):
            definition = RowDefinition()
            definition.Height = GridLength(1, GridUnitType.Auto)
            self.resultGrid.RowDefinitions.Add(definition)
            for position in range(len(columns)):
                value = row[position] if position < len(row) else u''
                self.resultGrid.Children.Add(
                    self._cell(value, index + 1, position))

        self.resultTab.IsEnabled = True
        self.tabs.SelectedIndex = 1

    def _cell(self, value, row, column, header=False):
        border = Border()
        border.Padding = _thickness(10, 6, 10, 6)
        border.BorderThickness = _thickness(0, 0, 1, 1)
        edge = self._res('Border')
        if edge is not None:
            border.BorderBrush = edge
        if header:
            fill = self._res('BrandTint')
            if fill is not None:
                border.Background = fill
        block = TextBlock()
        block.Text = u'' if value is None else u'{}'.format(value)
        self._styled(block, 'H2' if header else 'Label')
        block.Margin = _thickness(0, 0, 0, 0)
        if header:
            block.FontSize = 12
        border.Child = block
        Grid.SetRow(border, row)
        Grid.SetColumn(border, column)
        return border

    # --- 動作 --------------------------------------------------------------

    def _collect(self):
        """``(values, ok)``——驗證失敗時把訊息掛到欄位下方並回 ``False``。"""
        self._read()
        errors, notes = logic.validate(self.spec.get('fields'), self.values)
        self._show_errors(errors)
        if errors:
            self.status(u'有 {} 個欄位需要修正。'.format(len(errors)), 'danger')
            self.tabs.SelectedIndex = 0
            return None, False
        # 夾範圍之後把畫面上的數字也改掉，否則使用者看到的還是他打的 1000，
        # 而工具用的是 600——兩邊不一致是最難查的那種問題。
        for field in logic.input_fields(self.spec.get('fields')):
            if field['kind'] == logic.NUMBER:
                control = self.controls.get(field['key'])
                value = self.values.get(field['key'])
                if control is not None and value is not None:
                    control.Text = u'{:g}'.format(float(value))
        self.status(u'\n'.join(notes) if notes else u'', 'warning')
        return dict(self.values), True

    def run_clicked(self, sender, args):
        values, ok = self._collect()
        if not ok:
            return
        if self.handler is None:
            self.accepted = True
            self.Close()
            return
        self.runButton.IsEnabled = False
        self.status(u'處理中…', 'info')
        try:
            self.result = self.handler(values, self)
        except Exception as error:
            self.status(u'執行失敗：{}'.format(error), 'danger')
            self.runButton.IsEnabled = True
            return
        self.runButton.IsEnabled = True
        if self.result:
            self.show_result(self.result)
            if self.spec.get('secondary_label'):
                self.secondaryButton.IsEnabled = True

    def secondary_clicked(self, sender, args):
        values, ok = self._collect()
        if not ok:
            return
        self.accepted = True
        self.values['__secondary__'] = True
        self.Close()

    def cancel_clicked(self, sender, args):
        self.accepted = False
        self.Close()


# --- 對外 ------------------------------------------------------------------

def ask(spec):
    """顯示視窗收集答案。回傳 ``{key: value}``；取消回 ``None``。

    這是 ``SelectFromList`` 連珠的直接替代品：按鈕拿到的還是一份普通的 dict，
    下游流程一行都不用改。
    """
    repeated = logic.duplicate_keys(spec.get('fields'))
    if repeated:
        # 重複的 key 會讓後面的欄位靜默蓋掉前面的，是那種跑起來完全正常、
        # 只是答案錯了的 bug。寧可在開視窗之前就吵。
        raise ValueError(u'欄位 key 重複：{}'.format(u'、'.join(repeated)))
    window = McpWindow(spec)
    window.ShowDialog()
    if not window.accepted:
        return None
    return window.values


def run(spec, handler):
    """顯示視窗並讓使用者反覆執行。回傳最後一次的 ``(values, result)``。

    取消時回 ``(None, None)``。
    """
    window = McpWindow(spec, handler=handler)
    window.ShowDialog()
    if not window.accepted and window.result is None:
        return None, None
    return dict(window.values), window.result
