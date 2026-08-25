# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import re
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


try:
    _STRING_TYPES = (basestring,)
except NameError:
    _STRING_TYPES = (str,)


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


def _id_value(value, default=-1):
    raw = _get(value, 'IntegerValue', 'Value')
    return _int(raw if raw is not None else value, default)


def _ids(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            item_id = _id_value(item, -1)
            if item_id >= 0:
                result.append(item_id)
        return result
    if not isinstance(value, _STRING_TYPES):
        item_id = _id_value(value, -1)
        return [item_id] if item_id >= 0 else []
    return [_int(item) for item in re.findall(r'\d+', value)]


def _ids_text(value):
    return u', '.join([_text(item) for item in _ids(value)])


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


def _bool_value(value):
    if isinstance(value, bool):
        return value
    return _text(value).strip().lower() in ('1', 'true', 'yes', u'是')


def _warning_message(value):
    if isinstance(value, dict):
        message = _get(value, 'message', 'warning', u'警告', 'error', 'reason')
        return _text(message) if message is not None else u'未分類警示'
    return _text(value)


def _surface_label(value):
    labels = {
        'floor': u'地面',
        'wall': u'牆面',
        'ceiling': u'天花／上界',
        'other': u'其他'
    }
    key = _text(value).strip().lower()
    return labels.get(key, _text(value))


def _result_parts(result):
    if isinstance(result, dict):
        return (_list(result.get('records', [])),
                result.get('stats', {}) or {},
                _list(result.get('warnings', [])))
    return _list(result), {}, []


class RoomMaterialDetailWindow(forms.WPFWindow):
    def __init__(self, xaml_path, doc, uidoc):
        forms.WPFWindow.__init__(self, xaml_path)
        self.doc = doc
        self.uidoc = uidoc
        self.rooms = []
        self.records = []
        self.grouped = {'detail': [], 'rooms': [], 'materials': []}
        self.visible_rows = []
        self.warnings = []
        self.stats = {}
        self.skipped_room_ids = []
        self.surface_keys = []
        self.result_table = None
        self._bind_events()

    def _bind_events(self):
        self.calculateButton.Click += self._on_calculate
        self.exportButton.Click += self._on_export
        self.showElementsButton.Click += self._on_show_elements
        self.showRoomsButton.Click += self._on_show_rooms
        self.showSkippedButton.Click += self._on_show_skipped
        self.closeButton.Click += self._on_close
        self.viewCombo.SelectionChanged += self._on_view_changed
        self.searchBox.TextChanged += self._on_search_changed
        self.resultGrid.AutoGeneratingColumn += self._on_auto_generating_column

    def _selected_surfaces(self):
        values = []
        if _checked(self.floorCheck):
            values.append('floor')
        if _checked(self.wallCheck):
            values.append('wall')
        if _checked(self.ceilingCheck):
            values.append('ceiling')
        if _checked(self.otherCheck):
            values.append('other')
        return values

    def calculate(self):
        self.surface_keys = self._selected_surfaces()
        if not self.surface_keys:
            forms.alert(u'請至少勾選一種表面。', title=u'房間材質明細', warn_icon=True)
            return
        scope = _combo_tag(self.scopeCombo, 'all')
        boundary_mode = _combo_tag(self.boundaryCombo, 'finish')
        self.statusText.Text = u'正在收集房間與邊界材質…'
        try:
            self.rooms = _list(api.collect_rooms(self.doc, self.uidoc, scope))
            details = api.collect_room_material_details(
                self.doc, self.rooms, boundary_mode, self.surface_keys)
            self.records, self.stats, detail_warnings = _result_parts(details)
            self.grouped = logic.group_room_records(
                self.records, surface_keys=self.surface_keys)
            group_warnings = _list(self.grouped.get('warnings', [])) if isinstance(self.grouped, dict) else []
            self.warnings = detail_warnings + group_warnings
            self._collect_skipped_room_ids()
            self.rebuild_table()
            self._update_status()
        except Exception as error:
            self.statusText.Text = u'計算失敗。'
            forms.alert(u'無法完成房間材質計算：\n{0}'.format(_text(error)),
                        title=u'房間材質明細', warn_icon=True)

    def _collect_skipped_room_ids(self):
        values = []
        values.extend(_ids(_get(self.stats, 'skipped_room_ids', 'skipped_ids')))
        for warning in self.warnings:
            values.extend(_ids(_get(warning, 'room_id', 'roomId', 'RoomId')))
        self.skipped_room_ids = sorted(set(values))

    def _mode(self):
        return _combo_tag(self.viewCombo, 'detail')

    def _mode_rows(self, mode):
        if not isinstance(self.grouped, dict):
            return []
        return _list(self.grouped.get(mode, []))

    def _match_search(self, record, query):
        if not query:
            return True
        if isinstance(record, dict):
            text = u' '.join([_text(value) for value in record.values()])
        else:
            text = _text(record)
        return query in text.lower()

    def _table_spec(self, mode):
        if mode == 'rooms':
            return [
                (u'樓層', String), (u'房號', String), (u'房間名稱', String),
                (u'地面 (m²)', Double), (u'牆面 (m²)', Double),
                (u'天花／上界 (m²)', Double), (u'其他 (m²)', Double),
                (u'合計 (m²)', Double), (u'房間 ID', Int64),
                (u'_房間IDs', String), (u'_元素IDs', String), (u'_Key', String)]
        if mode == 'materials':
            return [
                (u'材質名稱', String), (u'說明分類', String), (u'表面', String),
                (u'面積 (m²)', Double), (u'房間數', Int32), (u'面數', Int32),
                (u'來源元素 ID', String),
                (u'_房間IDs', String), (u'_元素IDs', String), (u'_Key', String)]
        return [
            (u'樓層', String), (u'房號', String), (u'房間名稱', String),
            (u'表面', String), (u'材質名稱', String), (u'面積 (m²)', Double),
            (u'面數', Int32), (u'來源／方法', String), (u'來源元素 ID', String),
            (u'房間 ID', Int64), (u'品質', String),
            (u'_房間IDs', String), (u'_元素IDs', String), (u'_Key', String)]

    def _room_ids(self, record):
        value = _get(record, 'room_ids', 'RoomIds')
        if value is None:
            value = _get(record, 'room_id', 'roomId', 'RoomId')
        return _ids(value)

    def _element_ids(self, record):
        return _ids(_get(
            record,
            'element_ids', 'boundary_element_ids', 'host_element_ids',
            'element_id', 'boundary_element_id', 'host_element_id',
            'ElementIds', 'ElementId'))

    def _derived_ids(self, record, need_rooms):
        values = []
        target_room_ids = set(self._room_ids(record))
        target_room_number = _text(_get(record, 'room_number', 'number', 'RoomNumber'))
        target_material_id = _text(_get(record, 'material_id', 'MaterialId'))
        target_material_name = _text(_get(record, 'material_name', 'name', 'MaterialName'))
        target_surface = _text(_get(record, 'surface_kind', 'surface', 'Surface'))
        for detail in self._mode_rows('detail'):
            detail_room_ids = set(self._room_ids(detail))
            room_matches = bool(target_room_ids.intersection(detail_room_ids))
            if not target_room_ids and target_room_number:
                room_matches = target_room_number == _text(_get(
                    detail, 'room_number', 'number', 'RoomNumber'))
            material_matches = False
            if target_material_id:
                material_matches = target_material_id == _text(_get(
                    detail, 'material_id', 'MaterialId'))
            elif target_material_name:
                material_matches = target_material_name == _text(_get(
                    detail, 'material_name', 'name', 'MaterialName'))
            if target_surface and target_surface != _text(_get(
                    detail, 'surface_kind', 'surface', 'Surface')):
                material_matches = False
            if (target_room_ids or target_room_number) and not room_matches:
                continue
            if (target_material_id or target_material_name) and not material_matches:
                continue
            if need_rooms:
                values.extend(self._room_ids(detail))
            else:
                values.extend(self._element_ids(detail))
        return sorted(set(values))

    def _surface_area(self, record, key):
        names = {
            'floor': ('floor_m2', 'floor_area_m2', 'floor_area', 'FloorM2'),
            'wall': ('wall_m2', 'wall_area_m2', 'wall_area', 'WallM2'),
            'ceiling': ('ceiling_m2', 'ceiling_area_m2', 'ceiling_area', 'CeilingM2'),
            'other': ('other_m2', 'other_area_m2', 'other_area', 'OtherM2')
        }
        return _float(_get(record, *names[key]))

    def _display_values(self, mode, record, index):
        room_ids = self._room_ids(record)
        element_ids = self._element_ids(record)
        if not room_ids and mode == 'materials':
            room_ids = self._derived_ids(record, True)
        if not element_ids and mode == 'rooms':
            element_ids = self._derived_ids(record, False)
        room_id = room_ids[0] if room_ids else -1
        key = u'{0}:{1}'.format(mode, index)
        if mode == 'rooms':
            total = _get(record, 'total_area_m2', 'total_m2', 'area_m2', 'TotalAreaM2')
            if total is None:
                total = sum([self._surface_area(record, item) for item in ('floor', 'wall', 'ceiling', 'other')])
            return [
                _text(_get(record, 'level_name', 'level', 'Level')),
                _text(_get(record, 'room_number', 'number', 'RoomNumber')),
                _text(_get(record, 'room_name', 'name', 'RoomName')),
                self._surface_area(record, 'floor'),
                self._surface_area(record, 'wall'),
                self._surface_area(record, 'ceiling'),
                self._surface_area(record, 'other'),
                _float(total), room_id,
                _ids_text(room_ids), _ids_text(element_ids), key]
        if mode == 'materials':
            return [
                _text(_get(record, 'material_name', 'name', 'MaterialName')),
                _text(_get(record, 'material_class', 'class_name', 'Class')) or u'（未分類）',
                _surface_label(_get(record, 'surface_kind', 'surface_name', 'surface_label', 'surface_key', 'surface', 'Surface')),
                _float(_get(record, 'area_m2', 'total_area_m2', 'area', 'AreaM2')),
                _int(_get(record, 'room_count', 'rooms_count', 'RoomCount')),
                _int(_get(record, 'face_count', 'faces', 'FaceCount')),
                _ids_text(element_ids),
                _ids_text(room_ids), _ids_text(element_ids), key]
        method = _text(_get(record, 'method', 'Method'))
        material_source = _text(_get(record, 'material_source', 'source_kind', 'source', 'SourceKind'))
        source_parts = [item for item in (material_source, method) if item]
        source = u'／'.join(source_parts)
        if 'fallback_boundarysegments' in method.lower() or 'fallback' in method.lower():
            quality = u'fallback'
        elif _bool_value(_get(record, 'estimated', 'Estimated')):
            quality = u'estimated'
        else:
            quality = u'exact'
        return [
            _text(_get(record, 'level_name', 'level', 'Level')),
            _text(_get(record, 'room_number', 'number', 'RoomNumber')),
            _text(_get(record, 'room_name', 'name', 'RoomName')),
            _surface_label(_get(record, 'surface_kind', 'surface_name', 'surface_label', 'surface_key', 'surface', 'Surface')),
            _text(_get(record, 'material_name', 'material', 'MaterialName')),
            _float(_get(record, 'area_m2', 'area', 'AreaM2')),
            _int(_get(record, 'face_count', 'faces', 'FaceCount'), 1),
            source, _ids_text(element_ids), room_id, quality,
            _ids_text(room_ids), _ids_text(element_ids), key]

    def rebuild_table(self):
        mode = self._mode()
        query = _text(self.searchBox.Text).strip().lower()
        rows = self._mode_rows(mode)
        self.visible_rows = [row for row in rows if self._match_search(row, query)]
        table = DataTable('RoomMaterialResults')
        spec = self._table_spec(mode)
        for name, data_type in spec:
            table.Columns.Add(name, data_type)
        for index, record in enumerate(self.visible_rows):
            values = self._display_values(mode, record, index)
            row = table.NewRow()
            for column_index in range(len(spec)):
                row[spec[column_index][0]] = values[column_index]
            table.Rows.Add(row)
        self.result_table = table
        self.resultGrid.ItemsSource = self.result_table.DefaultView
        title_by_mode = {
            'detail': u'逐房間明細',
            'rooms': u'依房間彙總',
            'materials': u'依材質彙總'
        }
        self.tableTitle.Text = title_by_mode.get(mode, u'房間材質明細')
        self.rowCountText.Text = u'{0} 列'.format(len(self.visible_rows))
        self._update_visible_total(mode)

    def _update_visible_total(self, mode):
        total = 0.0
        for record in self.visible_rows:
            if mode == 'rooms':
                value = _get(record, 'total_area_m2', 'total_m2', 'area_m2', 'TotalAreaM2')
                if value is None:
                    value = sum([self._surface_area(record, item) for item in ('floor', 'wall', 'ceiling', 'other')])
            else:
                value = _get(record, 'area_m2', 'total_area_m2', 'area', 'AreaM2')
            total += _float(value)
        self.totalAreaText.Text = u'顯示合計 {0:,.3f} m²'.format(total)

    def _quality_counts(self):
        exact = _int(_get(self.stats, 'exact', 'exact_count'), -1)
        fallback = _int(_get(self.stats, 'fallback', 'fallback_count'), -1)
        estimated = _int(_get(self.stats, 'estimated', 'estimated_count'), -1)
        if exact >= 0 and fallback >= 0 and estimated >= 0:
            return exact, fallback, estimated
        exact = 0
        fallback = 0
        estimated = 0
        for record in self.records:
            quality = _text(_get(record, 'quality', 'accuracy', 'status', 'Quality')).lower()
            method = _text(_get(record, 'method', 'source_kind', 'Method', 'SourceKind')).lower()
            combined = quality + u' ' + method
            if 'fallback' in combined or u'替代' in combined:
                fallback += 1
            elif _bool_value(_get(record, 'estimated', 'Estimated')) or 'estimate' in combined or u'估算' in combined:
                estimated += 1
            else:
                exact += 1
        return exact, fallback, estimated

    def _update_status(self):
        exact, fallback, estimated = self._quality_counts()
        skipped = _int(_get(
            self.stats, 'rooms_skipped', 'skipped', 'skipped_count'),
            len(self.skipped_room_ids))
        self.statusText.Text = u'房間 {0} 個；明細 {1} 筆；exact {2}／fallback {3}／estimated {4}；略過 {5}；警示 {6}。'.format(
            len(self.rooms), len(self.records), exact, fallback, estimated, skipped, len(self.warnings))
        base = u'注意：天花是房間上界，不必然是 Ceiling 元素；請用「來源／方法」與亮顯邊界元素複核。'
        if self.warnings:
            base += u' 第一項警示：' + _warning_message(self.warnings[0])
        self.warningText.Text = base

    def _selected_hidden_ids(self, column_name):
        items = _list(self.resultGrid.SelectedItems)
        if not items and self.result_table is not None:
            items = _list(self.result_table.DefaultView)
        values = []
        for item in items:
            try:
                values.extend(_ids(item[column_name]))
            except Exception:
                pass
        return sorted(set(values))

    def _show_ids(self, values, empty_message):
        if not values:
            self.statusText.Text = empty_message
            return
        ids = List[DB.ElementId]()
        for value in values:
            ids.Add(DB.ElementId(value))
        self.uidoc.Selection.SetElementIds(ids)
        self.uidoc.ShowElements(ids)
        self.statusText.Text = u'已在 Revit 選取並亮顯 {0} 個元素。'.format(ids.Count)

    def _on_calculate(self, sender, args):
        self.calculate()

    def _on_view_changed(self, sender, args):
        if self.result_table is not None:
            self.rebuild_table()

    def _on_search_changed(self, sender, args):
        if self.result_table is not None:
            self.rebuild_table()

    def _on_auto_generating_column(self, sender, args):
        name = _text(args.PropertyName)
        if name.startswith('_'):
            args.Cancel = True
            return
        if u'(m²)' in name:
            try:
                args.Column.Binding.StringFormat = 'N3'
            except Exception:
                pass

    def _on_show_elements(self, sender, args):
        self._show_ids(self._selected_hidden_ids(u'_元素IDs'), u'目前列沒有可亮顯的邊界元素。')

    def _on_show_rooms(self, sender, args):
        self._show_ids(self._selected_hidden_ids(u'_房間IDs'), u'目前列沒有可亮顯的房間。')

    def _on_show_skipped(self, sender, args):
        self._show_ids(self.skipped_room_ids, u'沒有可亮顯的略過房間，或警示未提供房間 ID。')

    def _on_export(self, sender, args):
        if not self.records:
            self.statusText.Text = u'請先開始計算，再匯出 Excel。'
            return
        path = forms.save_file(file_ext='xlsx',
                               default_name='room_material_detail.xlsx',
                               title=u'匯出房間材質明細 Excel')
        if not path:
            return
        try:
            sheets = logic.room_workbook(self.records, self.warnings)
            xlsx_writer.write_workbook(path, sheets)
            self.statusText.Text = u'已匯出：{0}'.format(path)
        except Exception as error:
            forms.alert(u'匯出失敗：\n{0}'.format(_text(error)),
                        title=u'房間材質明細', warn_icon=True)

    def _on_close(self, sender, args):
        host = getattr(self, '_unified_host', None)
        if host is not None:
            host.Close()
            return
        self.Close()


def main():
    import material_tools_window
    material_tools_window.show('room')


if __name__ == '__main__':
    main()
