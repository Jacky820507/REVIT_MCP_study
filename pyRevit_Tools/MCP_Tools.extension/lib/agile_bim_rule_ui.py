# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Single-window, Excel-like settings UI for Agile BIM rule buttons."""

import os

from pyrevit import forms

import agile_bim_governance as governance


SOURCE_OPTIONS = (
    (u'內建預設規則（推薦，不需 JSON）', u'builtin'),
    (u'內建規則＋可編輯表格', u'edit_builtin'),
    (u'讀取 JSON 規則檔（進階、選用）', u'json'),
)

MODE_OPTIONS = (
    (u'只填空白（保留既有值，推薦）', u'fill_blank'),
    (u'覆寫符合規則的既有值', u'overwrite'),
)


def _text(value):
    if value is None:
        return u''
    try:
        return unicode(value).strip()
    except Exception:
        return u''


def _copy_config(preset):
    config = dict(preset)
    config['rules'] = [dict(rule) for rule in preset.get('rules', [])]
    return config


class AgileRuleSettingsWindow(forms.WPFWindow):
    """One-screen form that behaves like a small Excel rule table."""

    _MIN_RULE_ROWS = 6

    def __init__(self, title, preset, match_options, target_scope_options,
                 extra_option_label):
        xaml_path = os.path.join(os.path.dirname(__file__),
                                 'agile_bim_rule_ui.xaml')
        forms.WPFWindow.__init__(self, xaml_path)
        global GridLength, GridUnitType, HorizontalAlignment, Thickness
        global VerticalAlignment, Border, ColumnDefinition, Grid
        global TextBlock, TextBox
        from System.Windows import (GridLength, GridUnitType,
                                    HorizontalAlignment, Thickness,
                                    VerticalAlignment)
        from System.Windows.Controls import (Border, ColumnDefinition, Grid,
                                             TextBlock, TextBox)
        self.Title = title
        self.windowTitleText.Text = title + u'｜設定'
        self.result = None
        self.preset = _copy_config(preset)
        self.match_options = list(match_options or [])
        self.target_scope_options = list(target_scope_options or [])
        self.form_match_options = list(self.match_options)
        self.form_scope_options = list(self.target_scope_options)
        self.extra_option_label = _text(extra_option_label)
        self.extra_key = None
        if 'includeUnplaced' in self.preset:
            self.extra_key = 'includeUnplaced'
        elif 'includeCurtain' in self.preset:
            self.extra_key = 'includeCurtain'

        self.config = _copy_config(self.preset)
        self.rule_rows = []
        self.suppress_events = True
        self._json_pending = False
        self._source_mode = u'builtin'

        self._visible_value = self.targetScopePanel.Visibility
        self._collapsed_value = self.extraCheck.Visibility
        self.sourceParameterPanel.Visibility = self._collapsed_value

        self._fill_static_options()
        self.sourceCombo.SelectionChanged += self.source_changed
        self.loadJsonButton.Click += self.load_json_clicked
        self.addRuleButton.Click += self.add_rule_clicked
        self.previewButton.Click += self.preview_clicked
        self.cancelButton.Click += self.cancel_clicked
        self.targetParameterBox.TextChanged += self.settings_changed
        self.matchFieldCombo.SelectionChanged += self.match_field_changed
        self.sourceParameterBox.TextChanged += self.settings_changed
        self.targetScopeCombo.SelectionChanged += self.settings_changed
        self.modeCombo.SelectionChanged += self.settings_changed
        self.caseInsensitiveCheck.Checked += self.settings_changed
        self.caseInsensitiveCheck.Unchecked += self.settings_changed
        self.collapseWhitespaceCheck.Checked += self.settings_changed
        self.collapseWhitespaceCheck.Unchecked += self.settings_changed
        self.extraCheck.Checked += self.settings_changed
        self.extraCheck.Unchecked += self.settings_changed

        self._load_config(self.preset, u'內建預設規則')
        self.sourceCombo.SelectedIndex = 0
        self.suppress_events = False
        self._update_state()

    def _fill_static_options(self):
        for label, unused_value in SOURCE_OPTIONS:
            self.sourceCombo.Items.Add(label)
        for label, unused_value in MODE_OPTIONS:
            self.modeCombo.Items.Add(label)
        self.targetScopePanel.Visibility = (
            self._visible_value if self.target_scope_options
            else self._collapsed_value)

    def _set_combo_items(self, combo, options, value, unknown_label):
        combo.Items.Clear()
        selected_index = -1
        for index, option in enumerate(options):
            combo.Items.Add(option[0])
            if option[1] == value:
                selected_index = index
        if selected_index < 0 and value:
            combo.Items.Add(u'{0}：{1}'.format(unknown_label, value))
            selected_index = combo.Items.Count - 1
        combo.SelectedIndex = selected_index

    def _load_config(self, config, source_text):
        self.config = _copy_config(config)
        self.config['_rule_source'] = source_text
        self._json_pending = False
        self.targetParameterBox.Text = _text(
            self.config.get('targetParameter'))

        match_value = _text(self.config.get('matchField'))
        self.form_match_options = list(self.match_options)
        if match_value and self._option_index(
                self.form_match_options, match_value) < 0:
            self.form_match_options.append(
                (u'目前欄位：{0}'.format(match_value), match_value))
        self._set_combo_items(
            self.matchFieldCombo, self.form_match_options,
            match_value, u'目前欄位')
        self.sourceParameterBox.Text = _text(
            self.config.get('sourceParameter'))
        self._sync_source_parameter()
        scope_value = _text(self.config.get('targetScope'))
        self.form_scope_options = list(self.target_scope_options)
        if scope_value and self._option_index(
                self.form_scope_options, scope_value) < 0:
            self.form_scope_options.append(
                (u'目前範圍：{0}'.format(scope_value), scope_value))
        self._set_combo_items(
            self.targetScopeCombo, self.form_scope_options,
            scope_value, u'目前範圍')
        self.modeCombo.SelectedIndex = self._option_index(
            MODE_OPTIONS, _text(self.config.get('mode')))

        self.caseInsensitiveCheck.IsChecked = bool(
            self.config.get('caseInsensitive', True))
        self.collapseWhitespaceCheck.IsChecked = bool(
            self.config.get('collapseWhitespace', True))
        if self.extra_key:
            self.extraCheck.Content = self.extra_option_label
            self.extraCheck.Visibility = self._visible_value
            self.extraCheck.IsChecked = bool(
                self.config.get(self.extra_key, False))
        else:
            self.extraCheck.Visibility = self._collapsed_value

        self._fill_rule_rows(self.config.get('rules') or [])
        self.settingsPanel.IsEnabled = True
        editable_rules = self._source_mode in (u'edit_builtin', u'json')
        self.rulesPanel.IsEnabled = editable_rules
        self.addRuleButton.IsEnabled = editable_rules
        self.loadJsonButton.IsEnabled = False
        self.sourceHintText.Text = self._source_hint(source_text)

    def _option_index(self, options, value):
        for index, option in enumerate(options):
            if option[1] == value:
                return index
        return -1

    def _source_hint(self, source_text):
        if self._source_mode == u'json':
            if self._json_pending:
                return (u'JSON 是進階功能。請按下方「載入 JSON 規則檔」，'
                        u'載入後仍可在右側表格檢查內容。')
            return u'已載入 JSON；可在右側表格檢查或微調規則。'
        if self._source_mode == u'edit_builtin':
            return (u'內建規則已放入右側表格；直接修改文字或寫入值，'
                    u'不必自己編輯 JSON。')
        return (u'不需要準備任何檔案。先用預設規則測試，'
                u'也可以修改目標參數、比對欄位與寫入模式。')

    def _fill_rule_rows(self, rules):
        self.rule_rows = []
        self.rulesPanel.Children.Clear()
        for rule in rules:
            self._add_rule_row(
                _text(rule.get('match')), _text(rule.get('value')),
                _text(rule.get('id')))
        while len(self.rule_rows) < self._MIN_RULE_ROWS:
            self._add_rule_row()

    def _add_rule_row(self, match=u'', value=u'', rule_id=u''):
        row_number = len(self.rule_rows) + 1
        row = Grid()
        row.Height = 34
        row.ColumnDefinitions.Add(self._column(44.0, GridUnitType.Pixel))
        row.ColumnDefinitions.Add(self._column(1.0, GridUnitType.Star))
        row.ColumnDefinitions.Add(self._column(1.0, GridUnitType.Star))

        number_text = TextBlock()
        number_text.Text = u'{0}'.format(row_number)
        number_text.HorizontalAlignment = HorizontalAlignment.Center
        number_text.VerticalAlignment = VerticalAlignment.Center
        self._add_cell(row, number_text, 0)

        match_box = self._new_text_box(match)
        value_box = self._new_text_box(value)
        self._add_cell(row, match_box, 1)
        self._add_cell(row, value_box, 2)
        self.rulesPanel.Children.Add(row)
        self.rule_rows.append({
            'id': rule_id or u'rule-{0}'.format(row_number),
            'match': match_box,
            'value': value_box,
        })

    def _column(self, size, unit_type):
        column = ColumnDefinition()
        column.Width = GridLength(size, unit_type)
        return column

    def _new_text_box(self, value):
        box = TextBox()
        box.Text = value
        box.Margin = Thickness(0)
        box.Padding = Thickness(7, 2, 7, 2)
        box.TextChanged += self.settings_changed
        return box

    def _add_cell(self, row, control, column_index):
        cell = Border()
        cell.BorderBrush = self.FindResource('GridBorderBrush')
        cell.BorderThickness = Thickness(0, 0, 1, 1)
        cell.Padding = Thickness(3, 3, 3, 3)
        cell.Child = control
        Grid.SetColumn(cell, column_index)
        row.Children.Add(cell)

    def _selected_value(self, combo, options):
        index = int(combo.SelectedIndex)
        if index < 0 or index >= len(options):
            return u''
        return options[index][1]

    def _read_config(self):
        if self._json_pending:
            return None, u'請按「載入 JSON 規則檔」，或改回內建規則。'

        target_parameter = _text(self.targetParameterBox.Text)
        if not target_parameter:
            return None, u'請填寫要寫入的 Revit 文字參數。'
        match_field = self._selected_value(
            self.matchFieldCombo, self.form_match_options)
        if not match_field:
            return None, u'請選擇要拿來比對的來源欄位。'
        if match_field == u'parameter':
            source_parameter = _text(self.sourceParameterBox.Text)
            if not source_parameter:
                return None, u'選擇自訂來源參數時，請填寫參數名稱。'
        mode = self._selected_value(self.modeCombo, MODE_OPTIONS)
        if not mode:
            return None, u'請選擇寫入模式。'

        config = dict(self.config)
        config['targetParameter'] = target_parameter
        config['matchField'] = match_field
        if match_field == u'parameter':
            config['sourceParameter'] = source_parameter
        config['mode'] = mode
        config['caseInsensitive'] = bool(
            self.caseInsensitiveCheck.IsChecked)
        config['collapseWhitespace'] = bool(
            self.collapseWhitespaceCheck.IsChecked)
        if self.target_scope_options:
            target_scope = self._selected_value(
                self.targetScopeCombo, self.form_scope_options)
            if not target_scope:
                return None, u'請選擇寫入範圍。'
            config['targetScope'] = target_scope
        if self.extra_key:
            config[self.extra_key] = bool(self.extraCheck.IsChecked)

        rules = []
        for index, row in enumerate(self.rule_rows):
            match = _text(row['match'].Text)
            value = _text(row['value'].Text)
            if not match and not value:
                continue
            if not match or not value:
                return None, u'第 {0} 列只填了一半，請補齊或整列留白。'.format(
                    index + 1)
            rules.append({
                'id': row['id'] or u'rule-{0}'.format(index + 1),
                'match': match,
                'value': value,
            })
        if not rules:
            return None, u'至少需要一條規則。'
        config['rules'] = rules
        return config, None

    def _update_state(self):
        if self.suppress_events:
            return
        config, error = self._read_config()
        if error:
            self.statusText.Foreground = self.FindResource('ErrorBrush')
            self.statusText.Text = error
            self.previewButton.IsEnabled = False
            return
        self.statusText.Foreground = self.FindResource('SuccessBrush')
        self.statusText.Text = (
            u'設定完成：{0} 條規則。按「預覽規則」後才會讀取模型，'
            u'目前不會修改 Revit。').format(len(config.get('rules') or []))
        self.previewButton.IsEnabled = True

    def settings_changed(self, sender, args):
        self._update_state()

    def _sync_source_parameter(self):
        match_field = self._selected_value(
            self.matchFieldCombo, self.form_match_options)
        self.sourceParameterPanel.Visibility = (
            self._visible_value if match_field == u'parameter'
            else self._collapsed_value)

    def match_field_changed(self, sender, args):
        if self.suppress_events:
            return
        self._sync_source_parameter()
        self._update_state()

    def source_changed(self, sender, args):
        if self.suppress_events:
            return
        index = int(self.sourceCombo.SelectedIndex)
        if index < 0 or index >= len(SOURCE_OPTIONS):
            return
        self._source_mode = SOURCE_OPTIONS[index][1]
        if self._source_mode == u'json':
            self._json_pending = True
            self.settingsPanel.IsEnabled = False
            self.rulesPanel.IsEnabled = False
            self.addRuleButton.IsEnabled = False
            self.loadJsonButton.IsEnabled = True
            self.sourceHintText.Text = self._source_hint(u'')
        else:
            self._load_config(
                self.preset,
                u'內建預設規則' if self._source_mode == u'builtin'
                else u'內建規則（使用者可編輯）')
            self.sourceHintText.Text = self._source_hint(u'')
        self._update_state()

    def load_json_clicked(self, sender, args):
        path = forms.pick_file(files_filter='JSON rules (*.json)|*.json')
        if not path:
            return
        try:
            config = governance.load_rules(path)
        except Exception as error:
            forms.alert(u'讀取 JSON 失敗：\n{0}'.format(error),
                        title=self.Title)
            return
        config['_rule_file'] = path
        config['_rule_source'] = u'JSON：{0}'.format(path)
        self._load_config(config, config['_rule_source'])
        self._source_mode = u'json'
        self.sourceHintText.Text = self._source_hint(u'')
        self._update_state()

    def add_rule_clicked(self, sender, args):
        self._add_rule_row()
        self._update_state()

    def preview_clicked(self, sender, args):
        config, error = self._read_config()
        if error:
            self.statusText.Foreground = self.FindResource('ErrorBrush')
            self.statusText.Text = error
            self.previewButton.IsEnabled = False
            return
        self.result = config
        self.Close()

    def cancel_clicked(self, sender, args):
        self.result = None
        self.Close()


def configure(title, preset, match_options, target_scope_options=None,
              extra_option_label=None):
    """Show the single-window settings form and return a rule config."""
    window = AgileRuleSettingsWindow(
        title, preset, match_options, target_scope_options,
        extra_option_label)
    window.ShowDialog()
    return window.result


def _summary(config):
    """Keep a small text summary for non-UI callers and diagnostics."""
    return u'規則來源：{0}\n目標參數：{1}\n規則數量：{2}'.format(
        _text(config.get('_rule_source')),
        _text(config.get('targetParameter')),
        len(config.get('rules') or []))
