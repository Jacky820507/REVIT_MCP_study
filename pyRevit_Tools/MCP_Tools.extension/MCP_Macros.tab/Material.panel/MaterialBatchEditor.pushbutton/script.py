# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys

from pyrevit import forms, revit, script

import clr
clr.AddReference('System.Data')

from System import Boolean, Int32, Int64, String
from System.Data import DataTable
from System.Windows.Controls import DataGridEditingUnit
from System.Windows.Media import Color, SolidColorBrush


LIB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'lib'))
if LIB_DIR not in sys.path:
    sys.path.append(LIB_DIR)

import material_tools_logic as logic
import material_tools_revit as api


FIELD_LABELS = (
    ('material_class', u'說明分類'),
    ('material_category', u'材質類別'),
    ('description', u'描述'),
    ('color', u'顏色'),
    ('transparency', u'透明度'),
    ('shininess', u'光澤度'),
    ('smoothness', u'平滑度'),
    ('use_render_appearance', u'渲染外觀著色'),
    ('surface_foreground_pattern_id', u'表面前景樣式'),
    ('surface_foreground_color', u'表面前景顏色'),
    ('cut_foreground_pattern_id', u'切割前景樣式'),
    ('cut_foreground_color', u'切割前景顏色')
)

# These controls are deliberately separate from the batch editor controls.
# Loading a row into the direct editor therefore never changes a pending batch
# preview or silently checks a batch field for the user.
DIRECT_FIELD_LABELS = (
    ('material_class', u'說明分類'),
    ('material_category', u'材質類別'),
    ('description', u'描述'),
    ('color', u'顏色 RGB'),
    ('transparency', u'透明度'),
    ('shininess', u'光澤度'),
    ('smoothness', u'平滑度'),
    ('surface_foreground_color', u'表面前景色'),
    ('cut_foreground_color', u'切割前景色'),
)


def _get(value, *names):
    if value is None:
        return None
    for name in names:
        try:
            if isinstance(value, dict) and name in value:
                return value[name]
        except Exception:
            pass
        try:
            found = getattr(value, name)
            if found is not None:
                return found
        except Exception:
            pass
    return None


def _text(value):
    if value is None:
        return u''
    try:
        return unicode(value)
    except Exception:
        return str(value)


def _id_text(value):
    raw = _get(value, 'IntegerValue', 'Value')
    return _text(raw if raw is not None else value)


def _int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    try:
        return list(value)
    except Exception:
        return [value]


def _material_id(record):
    return _id_text(_get(record, 'id', 'material_id', 'materialId', 'MaterialId', 'Id'))


def _rgb_text(record):
    color = _get(record, 'color_rgb', 'color', 'rgb', 'Color', 'Rgb')
    if color is not None:
        red = _get(color, 'red', 'r', 'Red', 'R')
        green = _get(color, 'green', 'g', 'Green', 'G')
        blue = _get(color, 'blue', 'b', 'Blue', 'B')
        if red is not None and green is not None and blue is not None:
            return u'{0}, {1}, {2}'.format(_int(red), _int(green), _int(blue))
        if isinstance(color, (list, tuple)) and len(color) >= 3:
            return u'{0}, {1}, {2}'.format(_int(color[0]), _int(color[1]), _int(color[2]))
    return u'—'


def _rgb_brush(rgb_text):
    try:
        values = _parse_rgb(rgb_text, u'顏色 RGB')
        return u'#{0:02X}{1:02X}{2:02X}'.format(
            values[0], values[1], values[2])
    except Exception:
        return u'#C8CDD1'


def _record_rgb(record, *names):
    """Return a canonical RGB list for a material inventory value."""
    value = _get(record, *names)
    if value is None:
        return [0, 0, 0]
    text = _rgb_text({'color': value})
    if text == u'—':
        return [0, 0, 0]
    try:
        return _parse_rgb(text, u'顏色 RGB')
    except Exception:
        return [0, 0, 0]


def _combo_tag(combo, default_value):
    item = combo.SelectedItem
    if item is None:
        return default_value
    tag = _get(item, 'Tag')
    if tag is not None:
        return _text(tag)
    return _text(_get(item, 'Content'))


def _checked(control):
    return control.IsChecked == True


def _truthy(value):
    if isinstance(value, bool):
        return value
    return _text(value).strip().lower() in ('1', 'true', 'yes', 'drafting', u'是')


def _message(value):
    if isinstance(value, dict):
        message = _get(value, 'message', 'warning', u'警告', 'error', 'reason')
        return _text(message) if message is not None else u'未分類訊息'
    return _text(value)


def _count(value, default=0):
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return _int(value, default)


def _parse_rgb(value, label):
    parts = [item.strip() for item in _text(value).split(',')]
    if len(parts) != 3:
        raise ValueError(u'{0} 必須是 R, G, B 三個整數。'.format(label))
    numbers = []
    for part in parts:
        number = int(part)
        if number < 0 or number > 255:
            raise ValueError(u'{0} 的每個數值必須介於 0 與 255。'.format(label))
        numbers.append(number)
    return numbers


def _parse_range(value, label, minimum, maximum):
    number = int(_text(value).strip())
    if number < minimum or number > maximum:
        raise ValueError(u'{0} 必須介於 {1} 與 {2}。'.format(label, minimum, maximum))
    return number


class MaterialBatchEditorWindow(forms.WPFWindow):
    def __init__(self, xaml_path, doc):
        forms.WPFWindow.__init__(self, xaml_path)
        self.doc = doc
        self.inventory = []
        self.filtered_materials = []
        self.material_by_id = {}
        self.checked_ids = set()
        self.pattern_by_label = {}
        self._suspend_filter = False
        self.preview_patch = None
        self.preview_material_ids = []
        self.rename_preview = None
        self._capturing_checks = False
        self.usage_warning_count = 0
        self.selected_material_id = None
        self.direct_snapshot = None
        self.direct_preview_patch = None
        self.direct_preview_material_id = None
        self.direct_rename_preview = None
        self._loading_direct_values = False
        self._make_table()
        self._bind_events()
        self._update_all_swatches()
        self.refresh_data()

    def _make_table(self):
        self.material_table = DataTable('Materials')
        self.material_table.Columns.Add('Checked', Boolean)
        for name, data_type in (
                ('Name', String), ('Class', String), ('Rgb', String),
                ('RgbBrush', String),
                ('Transparency', Int32), ('UsageCount', Int32),
                ('TypeRefs', Int32), ('Id', Int64)):
            self.material_table.Columns.Add(name, data_type)
        self.materialGrid.ItemsSource = self.material_table.DefaultView

    def _bind_events(self):
        self.selectVisibleButton.Click += self._on_select_visible
        self.clearCheckedButton.Click += self._on_clear_checked
        self.refreshButton.Click += self._on_refresh
        self.previewButton.Click += self._on_preview
        self.applyButton.Click += self._on_apply
        self.closeButton.Click += self._on_close
        self.classCombo.SelectionChanged += self._on_filter_changed
        self.searchBox.TextChanged += self._on_filter_changed
        self.materialGrid.SelectionChanged += self._on_material_selection
        self.materialGrid.CurrentCellChanged += self._on_check_changed
        self.colorBox.TextChanged += self._on_color_text_changed
        self.surfaceColorBox.TextChanged += self._on_surface_color_text_changed
        self.cutColorBox.TextChanged += self._on_cut_color_text_changed
        self.directColorBox.TextChanged += self._on_direct_color_text_changed
        self.directSurfaceColorBox.TextChanged += self._on_direct_surface_color_text_changed
        self.directCutColorBox.TextChanged += self._on_direct_cut_color_text_changed
        self.directApplyButton.Click += self._on_direct_apply

    def _update_swatch(self, text_box, swatch, label):
        """Update only after a valid RGB edit; invalid text keeps the last color."""
        try:
            values = _parse_rgb(text_box.Text, label)
            swatch.Background = SolidColorBrush(Color.FromRgb(
                values[0], values[1], values[2]))
        except Exception:
            pass

    def _update_all_swatches(self):
        self._update_swatch(self.colorBox, self.colorSwatch, u'顏色 RGB')
        self._update_swatch(
            self.surfaceColorBox, self.surfaceColorSwatch, u'表面前景顏色')
        self._update_swatch(
            self.cutColorBox, self.cutColorSwatch, u'切割前景顏色')
        self._update_swatch(
            self.directColorBox, self.directColorSwatch, u'直接編輯顏色 RGB')
        self._update_swatch(
            self.directSurfaceColorBox, self.directSurfaceColorSwatch,
            u'直接編輯表面前景色')
        self._update_swatch(
            self.directCutColorBox, self.directCutColorSwatch,
            u'直接編輯切割前景色')

    def _on_color_text_changed(self, sender, args):
        self._update_swatch(self.colorBox, self.colorSwatch, u'顏色 RGB')

    def _on_surface_color_text_changed(self, sender, args):
        self._update_swatch(
            self.surfaceColorBox, self.surfaceColorSwatch, u'表面前景顏色')

    def _on_cut_color_text_changed(self, sender, args):
        self._update_swatch(
            self.cutColorBox, self.cutColorSwatch, u'切割前景顏色')

    def _on_direct_color_text_changed(self, sender, args):
        self._update_swatch(
            self.directColorBox, self.directColorSwatch,
            u'直接編輯顏色 RGB')

    def _on_direct_surface_color_text_changed(self, sender, args):
        self._update_swatch(
            self.directSurfaceColorBox, self.directSurfaceColorSwatch,
            u'直接編輯表面前景色')

    def _on_direct_cut_color_text_changed(self, sender, args):
        self._update_swatch(
            self.directCutColorBox, self.directCutColorSwatch,
            u'直接編輯切割前景色')

    def refresh_data(self):
        self.statusText.Text = u'正在讀取材質與填滿樣式…'
        previous_selected_id = self.selected_material_id
        try:
            self.inventory = _list(api.collect_material_inventory(self.doc))
            self.usage_warning_count = 0
            try:
                scope_result = api.collect_scope_elements(
                    self.doc, None, 'project')
                if isinstance(scope_result, dict):
                    scope_elements = _list(scope_result.get('elements', []))
                    self.usage_warning_count += len(_list(
                        scope_result.get('warnings', [])))
                else:
                    scope_elements = _list(scope_result)
                usage_result = api.collect_material_usage(
                    self.doc, scope_elements, scope='project')
                if isinstance(usage_result, dict):
                    self._merge_usage_summaries(_list(
                        usage_result.get('materials', [])))
                    self.usage_warning_count += len(_list(
                        usage_result.get('warnings', [])))
            except Exception:
                self.usage_warning_count += 1
            self.material_by_id = {}
            for material in self.inventory:
                self.material_by_id[_material_id(material)] = material
            self.checked_ids = set()
            self._load_patterns(_list(api.collect_fill_patterns(self.doc)))
            self._set_classes()
            self.apply_filter()
            if previous_selected_id is not None:
                self._select_material_by_id(previous_selected_id)
            else:
                self._clear_direct_fields()
            self.preview_patch = None
            self.preview_material_ids = []
            self.direct_preview_patch = None
            self.direct_preview_material_id = None
            self.direct_rename_preview = None
            self.previewText.Text = u'尚未預覽。只有勾選「套用」的欄位會寫入；本工具不新增、複製或刪除材質。'
        except Exception as error:
            self.statusText.Text = u'讀取失敗。'
            forms.alert(u'無法讀取材質：\n{0}'.format(_text(error)),
                        title=u'材質批次編輯', warn_icon=True)

    def _merge_usage_summaries(self, summaries):
        by_id = {}
        for summary in summaries:
            by_id[_material_id(summary)] = summary
        for material in self.inventory:
            summary = by_id.get(_material_id(material))
            if summary is None or not isinstance(material, dict):
                continue
            for key in ('usage_count', 'paint_count',
                        'type_reference_count', 'referencing_type_count'):
                value = _get(summary, key)
                if value is not None:
                    material[key] = value

    def _set_classes(self):
        self._suspend_filter = True
        values = set()
        for material in self.inventory:
            value = _text(_get(
                material, 'material_class', 'class_name', 'description_class',
                'classification', 'material_category', 'Class', 'class'))
            if value:
                values.add(value)
        self.classCombo.Items.Clear()
        self.classCombo.Items.Add(u'全部分類')
        for value in sorted(values):
            self.classCombo.Items.Add(value)
        self.classCombo.SelectedIndex = 0
        self._suspend_filter = False

    def _load_patterns(self, patterns):
        self.pattern_by_label = {}
        self.surfacePatternCombo.Items.Clear()
        self.cutPatternCombo.Items.Clear()
        self.pattern_by_label[u'（未指定）'] = -1
        surface_labels = [u'（未指定）']
        cut_labels = [u'（未指定）']
        for pattern in patterns:
            name = _text(_get(pattern, 'name', 'Name')) or u'未命名樣式'
            pattern_id = _int(_id_text(_get(pattern, 'id', 'pattern_id', 'Id')), -1)
            target = _text(_get(pattern, 'target', 'pattern_target', 'Target')).strip().lower()
            is_drafting_value = _get(pattern, 'is_drafting', 'drafting', 'IsDrafting')
            is_model_value = _get(pattern, 'is_model', 'model', 'IsModel')
            if is_drafting_value is None:
                is_drafting = target in ('drafting', 'draft', u'製圖', u'製圖樣式')
            else:
                is_drafting = _truthy(is_drafting_value)
            if is_model_value is None:
                is_model = target in ('model', u'模型', u'模型樣式')
            else:
                is_model = _truthy(is_model_value)
            target_label = u'Drafting' if is_drafting else (u'Model' if is_model else u'未知類型')
            label = u'{0} · {1}'.format(name, target_label)
            if label in self.pattern_by_label:
                label = u'{0}  [{1}]'.format(name, pattern_id)
            self.pattern_by_label[label] = pattern_id
            if is_drafting or is_model:
                surface_labels.append(label)
            if is_drafting:
                cut_labels.append(label)
        for label in surface_labels:
            self.surfacePatternCombo.Items.Add(label)
        for label in cut_labels:
            self.cutPatternCombo.Items.Add(label)
        self.surfacePatternCombo.SelectedIndex = 0
        self.cutPatternCombo.SelectedIndex = 0

    def _capture_checks(self):
        if self._capturing_checks:
            return
        self._capturing_checks = True
        try:
            try:
                self.materialGrid.CommitEdit(DataGridEditingUnit.Cell, True)
                self.materialGrid.CommitEdit(DataGridEditingUnit.Row, True)
            except Exception:
                pass
            for row in self.material_table.Rows:
                material_id = _text(row['Id'])
                try:
                    is_checked = bool(row['Checked'])
                except Exception:
                    is_checked = False
                if is_checked:
                    self.checked_ids.add(material_id)
                elif material_id in self.checked_ids:
                    self.checked_ids.remove(material_id)
            self.checkedText.Text = u'已勾選 {0} 個'.format(len(self.checked_ids))
        finally:
            self._capturing_checks = False

    def apply_filter(self):
        self._capture_checks()
        search_text = _text(self.searchBox.Text).strip()
        selected_class = _text(self.classCombo.SelectedItem)
        class_filter = 'all' if selected_class in (u'', u'全部分類') else selected_class
        try:
            self.filtered_materials = _list(logic.filter_materials(
                self.inventory,
                search_text=search_text,
                usage_filter='all',
                class_filter=class_filter))
        except Exception:
            self.filtered_materials = self._local_filter(search_text, class_filter)
        self._populate_materials()
        warning_suffix = (u'；使用量掃描警示 {0} 項'.format(
            self.usage_warning_count) if self.usage_warning_count else u'')
        self.statusText.Text = u'共 {0} 個材質，顯示 {1} 個；已勾選 {2} 個{3}。'.format(
            len(self.inventory), len(self.filtered_materials),
            len(self.checked_ids), warning_suffix)

    def _local_filter(self, search_text, class_filter):
        query = search_text.lower()
        rows = []
        for material in self.inventory:
            name = _text(_get(material, 'name', 'Name'))
            material_class = _text(_get(
                material, 'material_class', 'class_name', 'description_class',
                'classification', 'material_category', 'Class', 'class'))
            material_id = _material_id(material)
            if query and query not in (name + u' ' + material_class + u' ' + material_id).lower():
                continue
            if class_filter != 'all' and material_class != class_filter:
                continue
            rows.append(material)
        return rows

    def _populate_materials(self):
        self.material_table.Rows.Clear()
        for material in self.filtered_materials:
            material_id = _material_id(material)
            row = self.material_table.NewRow()
            row['Checked'] = material_id in self.checked_ids
            row['Name'] = _text(_get(material, 'name', 'Name'))
            row['Class'] = _text(_get(
                material, 'material_class', 'class_name', 'description_class',
                'classification', 'material_category', 'Class', 'class')) or u'（未分類）'
            rgb_text = _rgb_text(material)
            row['Rgb'] = rgb_text
            row['RgbBrush'] = _rgb_brush(rgb_text)
            row['Transparency'] = _int(_get(material, 'transparency', 'Transparency'))
            row['UsageCount'] = _int(_get(material, 'usage_count', 'element_count', 'UsageCount'))
            row['TypeRefs'] = _int(_get(
                material, 'referencing_type_count', 'type_reference_count',
                'TypeReferenceCount'))
            row['Id'] = _int(material_id, -1)
            self.material_table.Rows.Add(row)

    def _select_material_by_id(self, material_id):
        """Restore the single direct-edit selection after a refresh."""
        target = _text(material_id)
        for item in self.materialGrid.Items:
            try:
                if _text(item['Id']) == target:
                    self.materialGrid.SelectedItem = item
                    return True
            except Exception:
                pass
        self.materialGrid.SelectedItem = None
        self._clear_direct_fields()
        return False

    def _clear_direct_fields(self):
        self.selected_material_id = None
        self.direct_snapshot = None
        self.direct_preview_patch = None
        self.direct_preview_material_id = None
        self.direct_rename_preview = None
        self._loading_direct_values = True
        try:
            self.directSelectionHint.Text = u'請先在左側材質表點選一列。這裡只會編輯目前選取的單一材質。'
            for control in (
                    self.directNameBox, self.directClassBox,
                    self.directCategoryBox, self.directDescriptionBox,
                    self.directColorBox, self.directTransparencyBox,
                    self.directShininessBox, self.directSmoothnessBox,
                    self.directSurfaceColorBox, self.directCutColorBox):
                control.Text = u''
        finally:
            self._loading_direct_values = False

    def _direct_values_from_material(self, material):
        return {
            'name': _text(_get(material, 'name', 'Name')),
            'material_class': _text(_get(
                material, 'material_class', 'class_name',
                'description_class', 'classification', 'Class', 'class')),
            'material_category': _text(_get(
                material, 'material_category', 'category',
                'description_category', 'MaterialCategory')),
            'description': _text(_get(material, 'description', 'Description')),
            'color': _record_rgb(material, 'color_rgb', 'color', 'rgb', 'Color', 'Rgb'),
            'transparency': _int(_get(material, 'transparency', 'Transparency'), 0),
            'shininess': _int(_get(material, 'shininess', 'glossiness', 'Shininess'), 0),
            'smoothness': _int(_get(material, 'smoothness', 'Smoothness'), 0),
            'surface_foreground_color': _record_rgb(
                material, 'surface_foreground_color', 'surfaceForegroundColor'),
            'cut_foreground_color': _record_rgb(
                material, 'cut_foreground_color', 'cutForegroundColor'),
        }

    def _load_direct_material(self, material):
        if material is None:
            self._clear_direct_fields()
            return
        values = self._direct_values_from_material(material)
        self.selected_material_id = _material_id(material)
        self.direct_snapshot = values.copy()
        self.direct_preview_patch = None
        self.direct_preview_material_id = None
        self.direct_rename_preview = None
        self._loading_direct_values = True
        try:
            self.directSelectionHint.Text = u'目前選取：{0}（只會套用這一個材質）'.format(
                values['name'])
            self.directNameBox.Text = values['name']
            self.directClassBox.Text = values['material_class']
            self.directCategoryBox.Text = values['material_category']
            self.directDescriptionBox.Text = values['description']
            self.directColorBox.Text = self._field_value_text(
                'color', values['color'])
            self.directTransparencyBox.Text = _text(values['transparency'])
            self.directShininessBox.Text = _text(values['shininess'])
            self.directSmoothnessBox.Text = _text(values['smoothness'])
            self.directSurfaceColorBox.Text = self._field_value_text(
                'surface_foreground_color', values['surface_foreground_color'])
            self.directCutColorBox.Text = self._field_value_text(
                'cut_foreground_color', values['cut_foreground_color'])
        finally:
            self._loading_direct_values = False
        self._update_all_swatches()

    def _selected_materials(self):
        self._capture_checks()
        materials = []
        for material_id in sorted(self.checked_ids):
            material = self.material_by_id.get(material_id)
            if material is not None:
                materials.append(material)
        return materials

    def _pattern_id(self, combo):
        label = _text(combo.SelectedItem)
        return self.pattern_by_label.get(label, -1)

    def _field(self, enabled, value):
        return {'enabled': bool(enabled), 'value': value}

    def _build_patch(self):
        mode = _combo_tag(self.renameModeCombo, 'none')
        rename_enabled = _checked(self.applyRename) and mode != 'none'
        rename_value = _text(self.renameValueBox.Text)
        replace_value = _text(self.renameReplaceBox.Text)
        rename = {
            'enabled': rename_enabled,
            'prefix': rename_value if mode == 'prefix' else u'',
            'suffix': rename_value if mode == 'suffix' else u'',
            'find_text': rename_value if mode == 'replace' else u'',
            'replace_text': replace_value if mode == 'replace' else u''
        }
        if rename_enabled and mode == 'replace' and not rename_value:
            raise ValueError(u'取代文字模式必須填寫要尋找的文字。')

        color_value = [0, 0, 0]
        if _checked(self.applyColor):
            color_value = _parse_rgb(self.colorBox.Text, u'顏色 RGB')
        surface_color = [0, 0, 0]
        if _checked(self.applySurfaceColor):
            surface_color = _parse_rgb(self.surfaceColorBox.Text, u'表面前景顏色')
        cut_color = [0, 0, 0]
        if _checked(self.applyCutColor):
            cut_color = _parse_rgb(self.cutColorBox.Text, u'切割前景顏色')

        transparency = 0
        if _checked(self.applyTransparency):
            transparency = _parse_range(self.transparencyBox.Text, u'透明度', 0, 100)
        shininess = 0
        if _checked(self.applyShininess):
            shininess = _parse_range(self.shininessBox.Text, u'光澤度', 0, 128)
        smoothness = 0
        if _checked(self.applySmoothness):
            smoothness = _parse_range(self.smoothnessBox.Text, u'平滑度', 0, 100)

        fields = {
            'material_class': self._field(_checked(self.applyClass), _text(self.classBox.Text)),
            'material_category': self._field(_checked(self.applyCategory), _text(self.categoryBox.Text)),
            'description': self._field(_checked(self.applyDescription), _text(self.descriptionBox.Text)),
            'color': self._field(_checked(self.applyColor), color_value),
            'transparency': self._field(_checked(self.applyTransparency), transparency),
            'shininess': self._field(_checked(self.applyShininess), shininess),
            'smoothness': self._field(_checked(self.applySmoothness), smoothness),
            'use_render_appearance': self._field(_checked(self.applyUseRender), _checked(self.useRenderBox)),
            'surface_foreground_pattern_id': self._field(_checked(self.applySurfacePattern), self._pattern_id(self.surfacePatternCombo)),
            'surface_foreground_color': self._field(_checked(self.applySurfaceColor), surface_color),
            'cut_foreground_pattern_id': self._field(_checked(self.applyCutPattern), self._pattern_id(self.cutPatternCombo)),
            'cut_foreground_color': self._field(_checked(self.applyCutColor), cut_color)
        }
        return {'rename': rename, 'fields': fields}

    def _enabled_labels(self, patch):
        labels = []
        if patch['rename']['enabled']:
            labels.append(u'名稱')
        for key, label in FIELD_LABELS:
            if patch['fields'][key]['enabled']:
                labels.append(label)
        return labels

    def _field_value_text(self, key, value):
        if isinstance(value, (list, tuple)):
            return u', '.join([_text(item) for item in value])
        if isinstance(value, bool):
            return u'是' if value else u'否'
        if key == 'surface_foreground_pattern_id':
            return _text(self.surfacePatternCombo.SelectedItem)
        if key == 'cut_foreground_pattern_id':
            return _text(self.cutPatternCombo.SelectedItem)
        return _text(value)

    def _build_preview_text(self, materials, patch, labels, rename_preview):
        parts = [u'預覽：將變更 {0} 個材質；欄位：{1}。'.format(
            len(materials), u'、'.join(labels))]
        if rename_preview is not None:
            rename_items = _list(rename_preview.get('items', []))
            examples = []
            for item in rename_items[:5]:
                examples.append(u'{0} → {1}'.format(
                    _text(item.get('old_name', u'')),
                    _text(item.get('new_name', u''))))
            if examples:
                suffix = u'；另 {0} 筆'.format(len(rename_items) - 5) if len(rename_items) > 5 else u''
                parts.append(u'名稱：{0}{1}。'.format(u'；'.join(examples), suffix))
            preview_warnings = _list(rename_preview.get('warnings', []))
            if preview_warnings:
                parts.append(u'名稱警示：{0}'.format(_text(preview_warnings[0])))
        value_parts = []
        for key, label in FIELD_LABELS:
            field = patch['fields'][key]
            if not field['enabled']:
                continue
            value_parts.append(u'{0}={1}'.format(
                label, self._field_value_text(key, field['value'])))
        if value_parts:
            parts.append(u'值：{0}。'.format(u'；'.join(value_parts)))
        return u'\n'.join(parts)

    def _prepare_preview(self):
        materials = self._selected_materials()
        if not materials:
            raise ValueError(u'請先在左表勾選至少一個材質。')
        patch = self._build_patch()
        labels = self._enabled_labels(patch)
        if not labels:
            raise ValueError(u'右側沒有任何欄位勾選「套用」。')
        rename_preview = None
        if patch['rename']['enabled']:
            rename_preview = logic.build_rename_preview(
                materials,
                prefix=patch['rename']['prefix'],
                suffix=patch['rename']['suffix'],
                find_text=patch['rename']['find_text'],
                replace_text=patch['rename']['replace_text'],
                project_names=self.inventory)
            rename_errors = _list(rename_preview.get('errors', []))
            if rename_errors:
                raise ValueError(u'名稱預檢未通過：{0}'.format(u'；'.join(
                    [_text(item) for item in rename_errors])))
        self.preview_patch = patch
        self.preview_material_ids = [_material_id(item) for item in materials]
        self.rename_preview = rename_preview
        self.previewText.Text = self._build_preview_text(
            materials, patch, labels, rename_preview)
        self.statusText.Text = u'預覽完成；請確認材質數量與欄位後再套用。'
        return materials, patch, labels

    def _direct_values_from_controls(self):
        return {
            'name': _text(self.directNameBox.Text),
            'material_class': _text(self.directClassBox.Text),
            'material_category': _text(self.directCategoryBox.Text),
            'description': _text(self.directDescriptionBox.Text),
            'color': _parse_rgb(self.directColorBox.Text, u'顏色 RGB'),
            'transparency': _parse_range(
                self.directTransparencyBox.Text, u'透明度', 0, 100),
            'shininess': _parse_range(
                self.directShininessBox.Text, u'光澤度', 0, 128),
            'smoothness': _parse_range(
                self.directSmoothnessBox.Text, u'平滑度', 0, 100),
            'surface_foreground_color': _parse_rgb(
                self.directSurfaceColorBox.Text, u'表面前景色'),
            'cut_foreground_color': _parse_rgb(
                self.directCutColorBox.Text, u'切割前景色'),
        }

    def _prepare_direct_preview(self):
        selected_id = self.selected_material_id
        if selected_id is None or self.direct_snapshot is None:
            raise ValueError(u'請先在左表點選一個材質。')
        material = self.material_by_id.get(_text(selected_id))
        if material is None:
            raise ValueError(u'目前選取材質已不存在，請重新讀取。')

        values = self._direct_values_from_controls()
        original = self.direct_snapshot
        fields = {}
        labels = []
        for key, label in DIRECT_FIELD_LABELS:
            if values[key] != original.get(key):
                fields[key] = self._field(True, values[key])
                labels.append(label)

        old_name = _text(original.get('name'))
        new_name = values['name']
        rename = {
            'enabled': new_name != old_name,
            'prefix': u'',
            'suffix': u'',
            'find_text': old_name if new_name != old_name else u'',
            'replace_text': new_name if new_name != old_name else u''
        }
        if rename['enabled']:
            labels.insert(0, u'名稱')
        if not labels:
            raise ValueError(u'目前選取材質沒有任何變更。')

        patch = {'rename': rename, 'fields': fields}
        rename_preview = None
        if rename['enabled']:
            rename_preview = logic.build_rename_preview(
                [material], find_text=rename['find_text'],
                replace_text=rename['replace_text'],
                project_names=self.inventory)
            rename_errors = _list(rename_preview.get('errors', []))
            if rename_errors:
                raise ValueError(u'名稱預檢未通過：{0}'.format(u'；'.join(
                    [_text(item) for item in rename_errors])))

        parts = [u'直接編輯預覽：只變更 1 個材質「{0}」。'.format(old_name)]
        if rename['enabled']:
            parts.append(u'名稱：{0} → {1}。'.format(old_name, new_name))
        for key, label in DIRECT_FIELD_LABELS:
            if key not in fields:
                continue
            parts.append(u'{0}：{1} → {2}。'.format(
                label, self._field_value_text(key, original.get(key)),
                self._field_value_text(key, values[key])))
        if rename_preview is not None:
            warnings = _list(rename_preview.get('warnings', []))
            if warnings:
                parts.append(u'名稱警示：{0}'.format(_text(warnings[0])))

        self.direct_preview_patch = patch
        self.direct_preview_material_id = _text(selected_id)
        self.direct_rename_preview = rename_preview
        self.previewText.Text = u'\n'.join(parts)
        self.statusText.Text = u'單一材質預覽完成；確認後才會寫入模型。'
        return material, patch, labels, u'\n'.join(parts)

    def _on_select_visible(self, sender, args):
        for row in self.material_table.Rows:
            row['Checked'] = True
            self.checked_ids.add(_text(row['Id']))
        self.checkedText.Text = u'已勾選 {0} 個'.format(len(self.checked_ids))
        self.preview_patch = None

    def _on_clear_checked(self, sender, args):
        self.checked_ids = set()
        for row in self.material_table.Rows:
            row['Checked'] = False
        self.checkedText.Text = u'已勾選 0 個'
        self.preview_patch = None

    def _on_refresh(self, sender, args):
        self.refresh_data()

    def _on_filter_changed(self, sender, args):
        if not self._suspend_filter and hasattr(self, 'material_table'):
            self.apply_filter()

    def _on_check_changed(self, sender, args):
        self._capture_checks()
        self.preview_patch = None

    def _on_material_selection(self, sender, args):
        item = self.materialGrid.SelectedItem
        if item is None:
            self.selectedMaterialBox.Text = u''
            self.assetNameBox.Text = u''
            self._clear_direct_fields()
            return
        try:
            material = self.material_by_id.get(_text(item['Id']))
        except Exception:
            material = None
        self.selectedMaterialBox.Text = _text(_get(material, 'name', 'Name'))
        self.assetNameBox.Text = _text(_get(
            material,
            'appearance_asset_name', 'asset_name', 'appearanceAssetName', 'AppearanceAssetName')) or u'（未指定或無法讀取）'
        self._load_direct_material(material)

    def _on_direct_apply(self, sender, args):
        try:
            material, patch, labels, preview_text = self._prepare_direct_preview()
        except Exception as error:
            message = _text(error)
            self.previewText.Text = u'無法套用目前選取：{0}'.format(message)
            self.statusText.Text = u'直接編輯未套用；模型未變更。'
            forms.alert(message, title=u'直接編輯材質', warn_icon=True)
            return

        confirmed = forms.alert(
            preview_text + u'\n\n確定要在單一 Revit 交易中套用嗎？',
            title=u'確認直接編輯材質', yes=True, no=True, warn_icon=True)
        if not confirmed:
            self.statusText.Text = u'已取消直接編輯；模型未變更。'
            return

        selected_id = _text(self.selected_material_id)
        try:
            result = api.apply_material_patch(self.doc, [material], patch)
            if isinstance(result, dict):
                errors = _list(result.get('errors', []))
                warnings = _list(result.get('warnings', []))
                ok = bool(result.get('ok', not errors)) and not errors
                changed = _count(result.get('changed', 1), 1)
            else:
                errors = []
                warnings = []
                ok = True
                changed = 1
            if not ok:
                message = _message(errors[0]) if errors else u'核心回報交易未完成。'
                self.previewText.Text = u'直接編輯失敗：{0}'.format(message)
                self.statusText.Text = u'交易未完成；模型未回報成功變更。'
                forms.alert(u'直接編輯未完成：\n{0}'.format(message),
                            title=u'直接編輯材質', warn_icon=True)
                return
            completion = u'直接編輯完成：已變更 {0} 個材質。'.format(changed)
            if warnings:
                completion += u' 第一項警示：' + _message(warnings[0])
            self.refresh_data()
            self._select_material_by_id(selected_id)
            self.previewText.Text = completion
            self.statusText.Text = u'模型已完成直接編輯，並已重新讀取目前材質。'
        except Exception as error:
            message = _text(error)
            self.previewText.Text = u'直接編輯失敗：{0}'.format(message)
            self.statusText.Text = u'套用失敗；模型可能已由核心回滾。'
            forms.alert(u'直接編輯材質失敗：\n{0}'.format(message),
                        title=u'直接編輯材質', warn_icon=True)

    def _on_preview(self, sender, args):
        try:
            self._prepare_preview()
        except Exception as error:
            self.previewText.Text = u'無法預覽：{0}'.format(_text(error))
            self.statusText.Text = u'請修正勾選或欄位內容。'

    def _on_apply(self, sender, args):
        try:
            materials, patch, labels = self._prepare_preview()
        except Exception as error:
            self.previewText.Text = u'無法套用：{0}'.format(_text(error))
            return
        confirmed = forms.alert(
            u'即將在單一 Revit 交易中變更 {0} 個材質。\n\n欄位：{1}\n\n確定要套用嗎？'.format(
                len(materials), u'、'.join(labels)),
            title=u'確認材質批次編輯',
            yes=True,
            no=True,
            warn_icon=True)
        if not confirmed:
            self.statusText.Text = u'已取消套用；模型未變更。'
            return
        try:
            result = api.apply_material_patch(self.doc, materials, patch)
            if isinstance(result, dict):
                errors = _list(result.get('errors', []))
                warnings = _list(result.get('warnings', []))
                ok = bool(result.get('ok', not errors)) and not errors
                changed = _count(result.get('changed', len(materials)), len(materials))
            else:
                errors = []
                warnings = []
                ok = True
                changed = len(materials)
            if not ok:
                message = _message(errors[0]) if errors else u'核心回報交易未完成。'
                self.previewText.Text = u'套用失敗：{0}'.format(message)
                self.statusText.Text = u'交易未完成；模型未回報成功變更。'
                forms.alert(u'材質批次編輯未完成：\n{0}'.format(message),
                            title=u'材質批次編輯', warn_icon=True)
                return
            completion = u'套用完成：已變更 {0} 個材質。'.format(changed)
            if warnings:
                completion += u' 第一項警示：' + _message(warnings[0])
            self.refresh_data()
            self.previewText.Text = completion
            self.statusText.Text = u'模型已完成材質批次編輯，並已重新讀取材質庫。'
        except Exception as error:
            forms.alert(u'材質批次編輯失敗：\n{0}'.format(_text(error)),
                        title=u'材質批次編輯', warn_icon=True)
            self.statusText.Text = u'套用失敗；請檢查警示。'

    def _on_close(self, sender, args):
        host = getattr(self, '_unified_host', None)
        if host is not None:
            host.Close()
            return
        self.Close()


def main():
    import material_tools_window
    material_tools_window.show('batch')


if __name__ == '__main__':
    main()
