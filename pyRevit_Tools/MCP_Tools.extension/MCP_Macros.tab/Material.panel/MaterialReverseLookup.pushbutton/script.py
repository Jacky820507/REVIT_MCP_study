# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys

from pyrevit import DB, forms, revit, script

import clr
clr.AddReference('System.Data')

from System import Double, Int32, Int64, String
from System.Collections.Generic import List
from System.Data import DataTable


LIB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'lib'))
if LIB_DIR not in sys.path:
    sys.path.append(LIB_DIR)

import material_tools_logic as logic
import material_tools_revit as api
import xlsx_writer


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
    if raw is not None:
        return _text(raw)
    return _text(value)


def _id_value(value, default=-1):
    return _int(_id_text(value), default)


def _int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _float(value, default=0.0):
    try:
        return float(value)
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


def _combo_tag(combo, default_value):
    item = combo.SelectedItem
    if item is None:
        return default_value
    tag = _get(item, 'Tag')
    if tag is None:
        return _text(_get(item, 'Content'))
    return _text(tag)


def _result_parts(result, row_key):
    rows = []
    stats = {}
    warnings = []
    if isinstance(result, dict):
        rows = _list(result.get(row_key, []))
        stats = result.get('stats', {}) or {}
        warnings = _list(result.get('warnings', []))
    else:
        rows = _list(result)
    return rows, stats, warnings


def _scope_parts(result):
    if isinstance(result, tuple):
        elements = _list(result[0]) if len(result) > 0 else []
        stats = result[1] if len(result) > 1 and result[1] else {}
        warnings = _list(result[2]) if len(result) > 2 else []
        return elements, stats, warnings
    if isinstance(result, dict):
        return (_list(result.get('elements', [])),
                result.get('stats', {}) or {},
                _list(result.get('warnings', [])))
    return _list(result), {}, []


def _material_id(record):
    return _id_text(_get(record, 'id', 'material_id', 'materialId', 'MaterialId', 'Id'))


def _usage_material_id(record):
    return _id_text(_get(record, 'material_id', 'materialId', 'MaterialId', 'material', 'Material'))


def _rgb_text(record, prefix=None):
    if prefix:
        color = _get(record, prefix, prefix + '_color')
    else:
        color = _get(record, 'color_rgb', 'color', 'rgb', 'Color', 'Rgb')
    if color is not None:
        red = _get(color, 'red', 'r', 'Red', 'R')
        green = _get(color, 'green', 'g', 'Green', 'G')
        blue = _get(color, 'blue', 'b', 'Blue', 'B')
        if red is not None and green is not None and blue is not None:
            return u'{0}, {1}, {2}'.format(_int(red), _int(green), _int(blue))
        if isinstance(color, (list, tuple)) and len(color) >= 3:
            return u'{0}, {1}, {2}'.format(_int(color[0]), _int(color[1]), _int(color[2]))
        text = _text(color)
        if text:
            return text
    red = _get(record, 'red', 'r', 'Red', 'R')
    green = _get(record, 'green', 'g', 'Green', 'G')
    blue = _get(record, 'blue', 'b', 'Blue', 'B')
    if red is not None and green is not None and blue is not None:
        return u'{0}, {1}, {2}'.format(_int(red), _int(green), _int(blue))
    return u'—'


def _rgb_brush(rgb_text):
    """Return a XAML-compatible solid brush value for a displayed RGB triplet."""
    try:
        parts = [item.strip() for item in _text(rgb_text).split(',')]
        if len(parts) != 3:
            raise ValueError()
        values = [_int(item, -1) for item in parts]
        if min(values) < 0 or max(values) > 255:
            raise ValueError()
        return u'#{0:02X}{1:02X}{2:02X}'.format(
            values[0], values[1], values[2])
    except Exception:
        return u'#C8CDD1'


def _format_area(value):
    if value in (None, u'', ''):
        return u'—'
    return u'{0:,.3f}'.format(_float(value))


def _message(value):
    if isinstance(value, dict):
        message = _get(value, 'message', 'warning', u'警告', 'error', 'reason')
        return _text(message) if message is not None else u'未分類警示'
    return _text(value)


class MaterialReverseLookupWindow(forms.WPFWindow):
    def __init__(self, xaml_path, doc, uidoc):
        forms.WPFWindow.__init__(self, xaml_path)
        self.doc = doc
        self.uidoc = uidoc
        self.inventory = []
        self.filtered_materials = []
        self.usages = []
        self.usage_by_material = {}
        self.material_by_id = {}
        self.scan_stats = {}
        self.scan_warnings = []
        self._make_tables()
        self._bind_events()
        self._set_classes([])
        self.refresh_data()

    def _make_tables(self):
        self.material_table = DataTable('Materials')
        for name, data_type in (
                ('Name', String), ('Class', String), ('Rgb', String),
                ('RgbBrush', String),
                ('Transparency', Int32), ('UsageCount', Int32),
                ('PaintCount', Int32), ('Id', Int64)):
            self.material_table.Columns.Add(name, data_type)
        self.materialGrid.ItemsSource = self.material_table.DefaultView

        self.usage_table = DataTable('Usages')
        for name, data_type in (
                ('Category', String), ('Element', String), ('Type', String),
                ('Level', String), ('Source', String), ('Area', Double),
                ('Id', Int64)):
            self.usage_table.Columns.Add(name, data_type)
        self.usageGrid.ItemsSource = self.usage_table.DefaultView

    def _bind_events(self):
        self.refreshButton.Click += self._on_refresh
        self.exportButton.Click += self._on_export
        self.selectButton.Click += self._on_select
        self.showButton.Click += self._on_show
        self.closeButton.Click += self._on_close
        self.materialGrid.SelectionChanged += self._on_material_selection
        self.scopeCombo.SelectionChanged += self._on_scope_changed
        self.usedCombo.SelectionChanged += self._on_filter_changed
        self.classCombo.SelectionChanged += self._on_filter_changed
        self.searchBox.TextChanged += self._on_filter_changed

    def _set_classes(self, materials):
        current = _text(self.classCombo.SelectedItem)
        values = set()
        for material in materials:
            value = _text(_get(
                material, 'material_class', 'class_name', 'description_class',
                'classification', 'material_category', 'Class', 'class'))
            if value:
                values.add(value)
        self.classCombo.Items.Clear()
        self.classCombo.Items.Add(u'全部分類')
        for value in sorted(values):
            self.classCombo.Items.Add(value)
        target = 0
        if current:
            for index in range(self.classCombo.Items.Count):
                if _text(self.classCombo.Items[index]) == current:
                    target = index
                    break
        self.classCombo.SelectedIndex = target

    def _merge_material_summaries(self, materials, summaries):
        if not summaries:
            return materials
        summary_by_id = {}
        for summary in summaries:
            summary_by_id[_material_id(summary)] = summary
        merged = []
        for material in materials:
            material_id = _material_id(material)
            summary = summary_by_id.get(material_id)
            if summary is None or not isinstance(material, dict) or not isinstance(summary, dict):
                merged.append(summary if summary is not None else material)
                continue
            item = dict(material)
            item.update(summary)
            merged.append(item)
        known = set([_material_id(item) for item in merged])
        for summary in summaries:
            if _material_id(summary) not in known:
                merged.append(summary)
        return merged

    def refresh_data(self):
        self.statusText.Text = u'正在讀取材質與使用元素…'
        try:
            materials = _list(api.collect_material_inventory(self.doc))
            scope = _combo_tag(self.scopeCombo, 'project')
            elements, scope_stats, scope_warnings = _scope_parts(
                api.collect_scope_elements(self.doc, self.uidoc, scope))
            usage_result = api.collect_material_usage(
                self.doc, elements, scope=scope)
            usage_materials, usage_stats, usage_warnings = _result_parts(usage_result, 'materials')
            usages, ignored_stats, ignored_warnings = _result_parts(usage_result, 'usages')

            self.inventory = self._merge_material_summaries(materials, usage_materials)
            self.usages = usages
            self.scan_stats = {}
            self.scan_stats.update(scope_stats)
            self.scan_stats.update(usage_stats)
            self.scan_warnings = scope_warnings + usage_warnings
            self.material_by_id = {}
            self.usage_by_material = {}
            for material in self.inventory:
                self.material_by_id[_material_id(material)] = material
            for usage in self.usages:
                material_id = _usage_material_id(usage)
                if material_id not in self.usage_by_material:
                    self.usage_by_material[material_id] = []
                self.usage_by_material[material_id].append(usage)
            self._set_classes(self.inventory)
            self.apply_filter()
        except Exception as error:
            self.statusText.Text = u'讀取失敗。'
            forms.alert(u'無法完成材質反查：\n{0}'.format(_text(error)),
                        title=u'材質反查', warn_icon=True)

    def apply_filter(self):
        search_text = _text(self.searchBox.Text).strip()
        usage_filter = _combo_tag(self.usedCombo, 'all')
        selected_class = _text(self.classCombo.SelectedItem)
        class_filter = 'all' if selected_class in (u'', u'全部分類') else selected_class
        try:
            filtered = logic.filter_materials(
                self.inventory,
                search_text=search_text,
                usage_filter=usage_filter,
                class_filter=class_filter)
        except Exception:
            filtered = self._local_filter(self.inventory, search_text, usage_filter, class_filter)
        self.filtered_materials = _list(filtered)
        self._populate_materials()
        self._populate_usages(None)
        self._update_status()

    def _local_filter(self, materials, search_text, usage_filter, class_filter):
        query = search_text.lower()
        rows = []
        for material in materials:
            material_id = _material_id(material)
            name = _text(_get(material, 'name', 'Name'))
            material_class = _text(_get(
                material, 'material_class', 'class_name', 'description_class',
                'classification', 'material_category', 'Class', 'class'))
            usage_count = _int(_get(material, 'usage_count', 'element_count', 'UsageCount'),
                               len(self.usage_by_material.get(material_id, [])))
            if query and query not in (name + u' ' + material_class + u' ' + material_id).lower():
                continue
            if class_filter != 'all' and material_class != class_filter:
                continue
            if usage_filter == 'used' and usage_count <= 0:
                continue
            if usage_filter == 'unused' and usage_count > 0:
                continue
            rows.append(material)
        return rows

    def _populate_materials(self):
        self.material_table.Rows.Clear()
        for material in self.filtered_materials:
            material_id = _material_id(material)
            row = self.material_table.NewRow()
            row['Name'] = _text(_get(material, 'name', 'Name'))
            row['Class'] = _text(_get(
                material, 'material_class', 'class_name', 'description_class',
                'classification', 'material_category', 'Class', 'class')) or u'（未分類）'
            rgb_text = _rgb_text(material)
            row['Rgb'] = rgb_text
            row['RgbBrush'] = _rgb_brush(rgb_text)
            row['Transparency'] = _int(_get(material, 'transparency', 'Transparency'))
            row['UsageCount'] = _int(
                _get(material, 'usage_count', 'element_count', 'UsageCount'),
                len(self.usage_by_material.get(material_id, [])))
            row['PaintCount'] = _int(_get(material, 'paint_count', 'PaintCount'))
            row['Id'] = _int(material_id, -1)
            self.material_table.Rows.Add(row)

    def _populate_usages(self, material_id):
        self.usage_table.Rows.Clear()
        if not material_id:
            self.usageTitle.Text = u'使用元素 — 請選取一個材質'
            return
        material = self.material_by_id.get(material_id)
        name = _text(_get(material, 'name', 'Name'))
        records = self.usage_by_material.get(material_id, [])
        self.usageTitle.Text = u'使用元素 — {0}（{1} 筆）'.format(name, len(records))
        for usage in records:
            row = self.usage_table.NewRow()
            row['Category'] = _text(_get(usage, 'category', 'category_name', 'Category'))
            row['Element'] = _text(_get(usage, 'element_name', 'name', 'ElementName', 'Element'))
            row['Type'] = _text(_get(usage, 'type_name', 'element_type', 'TypeName', 'Type'))
            row['Level'] = _text(_get(usage, 'level', 'level_name', 'Level')) or u'—'
            row['Source'] = _text(_get(
                usage, 'source_kind', 'source', 'usage_source', 'material_source', 'Source'))
            row['Area'] = _float(_get(usage, 'area_m2', 'area', 'AreaM2', 'Area'))
            row['Id'] = _id_value(_get(usage, 'element_id', 'id', 'ElementId', 'Id'))
            self.usage_table.Rows.Add(row)

    def _selected_usage_ids(self):
        items = _list(self.usageGrid.SelectedItems)
        if not items:
            items = _list(self.usageGrid.ItemsSource)
        values = []
        seen = set()
        for item in items:
            try:
                value = _int(item['Id'], -1)
            except Exception:
                value = -1
            if value >= 0 and value not in seen:
                values.append(value)
                seen.add(value)
        return values

    def _element_ids(self):
        ids = List[DB.ElementId]()
        for value in self._selected_usage_ids():
            ids.Add(DB.ElementId(value))
        return ids

    def _update_status(self):
        scanned = _int(_get(self.scan_stats, 'scanned', 'processed', 'element_count'), len(self.usages))
        skipped = _int(_get(self.scan_stats, 'skipped', 'skipped_count'), 0)
        self.statusText.Text = u'共 {0} 個材質，顯示 {1} 個；已掃描 {2} 個元素，略過 {3} 個。'.format(
            len(self.inventory), len(self.filtered_materials), scanned, skipped)
        if self.scan_warnings:
            self.warningText.Text = (u'掃描完成，但有 {0} 項警示：{1}。'
                                     u'「掃描未發現」不等於可安全刪除。').format(
                len(self.scan_warnings), _message(self.scan_warnings[0]))
        else:
            self.warningText.Text = (u'提示：材質使用量包含幾何材質、Paint 與類型參照；'
                                     u'「掃描未發現」不等於可安全刪除。右表可複核來源元素。')

    def _on_refresh(self, sender, args):
        self.refresh_data()

    def _on_scope_changed(self, sender, args):
        if hasattr(self, 'material_table'):
            self.refresh_data()

    def _on_filter_changed(self, sender, args):
        if hasattr(self, 'inventory') and hasattr(self, 'material_table'):
            self.apply_filter()

    def _on_material_selection(self, sender, args):
        item = self.materialGrid.SelectedItem
        if item is None:
            self._populate_usages(None)
            return
        try:
            material_id = _text(item['Id'])
        except Exception:
            material_id = None
        self._populate_usages(material_id)

    def _on_select(self, sender, args):
        ids = self._element_ids()
        if ids.Count == 0:
            self.statusText.Text = u'右表沒有可選取的元素。'
            return
        self.uidoc.Selection.SetElementIds(ids)
        self.statusText.Text = u'已在 Revit 選取 {0} 個元素。'.format(ids.Count)

    def _on_show(self, sender, args):
        ids = self._element_ids()
        if ids.Count == 0:
            self.statusText.Text = u'右表沒有可亮顯的元素。'
            return
        self.uidoc.ShowElements(ids)
        self.statusText.Text = u'已要求 Revit 亮顯 {0} 個元素。'.format(ids.Count)

    def _on_export(self, sender, args):
        path = forms.save_file(file_ext='xlsx',
                               default_name='material_reverse_lookup.xlsx',
                               title=u'匯出材質反查 Excel')
        if not path:
            return
        try:
            visible_ids = set([_material_id(item) for item in self.filtered_materials])
            usages = [item for item in self.usages if _usage_material_id(item) in visible_ids]
            sheets = logic.material_workbook(self.filtered_materials, usages, self.scan_warnings)
            xlsx_writer.write_workbook(path, sheets)
            self.statusText.Text = u'已匯出：{0}'.format(path)
        except Exception as error:
            forms.alert(u'匯出失敗：\n{0}'.format(_text(error)),
                        title=u'材質反查', warn_icon=True)

    def _on_close(self, sender, args):
        host = getattr(self, '_unified_host', None)
        if host is not None:
            host.Close()
            return
        self.Close()


def main():
    import material_tools_window
    material_tools_window.show('reverse')


if __name__ == '__main__':
    main()
