# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""可編輯參數表格視窗（房間參數表、明細表參數表共用）。

表格操作、變更追蹤與 Excel 往返規則在 ``room_param_grid_logic``（有 CPython
測試）；這裡是 WPF 視窗與 Revit 參數讀寫。視窗是 modal、只收集修改，寫入由
呼叫端在視窗關閉後處理。

``labels`` 決定狀態列與匯出檔名的用語::

    {'unit': u'間房間', 'unit_short': u'間', 'export_name': u'房間參數'}
"""

from Autodesk.Revit import DB
from pyrevit import forms

import clr
clr.AddReference('System.Data')

from System import DBNull, String
from System.Data import DataTable
from System.Windows import Clipboard, Setter, Style
from System.Windows.Controls import (Control, DataGridCell,
                                     DataGridEditingUnit, DataGridLength,
                                     DataGridTextColumn, TextBox)
from System.Windows.Data import Binding
from System.Windows.Input import ApplicationCommands, Key, Keyboard, \
    ModifierKeys
from System.Windows.Media import Color, SolidColorBrush

import code_integrity_excel
import room_param_grid_logic as logic
import xlsx_writer
import xlsx_xml


KEY_ID = 'k_id'
SORT_SUFFIX = '__sort'
KEY_CHANGED = 'k_changed'

KIND_TEXT = 'text'
KIND_INT = 'int'
KIND_DOUBLE = 'double'
KIND_YESNO = 'yesno'
KIND_OTHER = 'other'

ROOM_LABELS = {'unit': u'間房間', 'unit_short': u'間',
               'export_name': u'房間參數', 'title': u'房間參數表'}


# ── Revit 參數讀寫 ──────────────────────────────────────────────────

def id_value(element_id):
    if element_id is None:
        return -1
    # Revit 2025+ exposes .Value; 2020-2024 only .IntegerValue.
    try:
        return int(element_id.Value)
    except Exception:
        try:
            return int(element_id.IntegerValue)
        except Exception:
            return -1


def element_id(value):
    try:
        return DB.ElementId(value)
    except Exception:
        return DB.ElementId(int(value))


def is_yesno(param):
    # 2022+ 用 GetDataType()；2020/2021 只有 ParameterType。以探測決定。
    try:
        return param.Definition.GetDataType() == DB.SpecTypeId.Boolean.YesNo
    except Exception:
        pass
    try:
        return param.Definition.ParameterType == DB.ParameterType.YesNo
    except Exception:
        return False


def param_kind(param):
    storage = param.StorageType
    if storage == DB.StorageType.String:
        return KIND_TEXT
    if storage == DB.StorageType.Integer:
        return KIND_YESNO if is_yesno(param) else KIND_INT
    if storage == DB.StorageType.Double:
        return KIND_DOUBLE
    return KIND_OTHER


def read(param, kind):
    if param is None:
        return u''
    try:
        if kind == KIND_TEXT:
            return param.AsString() or u''
        if not param.HasValue:
            return u''
        if kind == KIND_YESNO:
            return logic.yesno_text(param.AsInteger())
        return param.AsValueString() or u''
    except Exception:
        return u''


def write(param, kind, value):
    """寫一格。失敗丟 Exception，訊息給使用者看。"""
    if param is None:
        raise Exception(u'這間房間沒有這個參數')
    if param.IsReadOnly:
        raise Exception(u'參數唯讀')
    value = logic.text(value)
    if kind == KIND_TEXT:
        ok = param.Set(value)
    elif kind == KIND_YESNO:
        flag = logic.parse_yesno(value)
        if flag is None:
            raise Exception(u'是/否 參數只接受 是、否、1、0')
        ok = param.Set(flag)
    elif kind == KIND_INT:
        try:
            ok = param.Set(int(value.strip()))
        except ValueError:
            ok = param.SetValueString(value)
    elif kind == KIND_DOUBLE:
        if not value.strip():
            raise Exception(u'數值不可空白')
        ok = param.SetValueString(value)
    else:
        raise Exception(u'不支援的參數型別')
    if not ok:
        raise Exception(u'Revit 不接受這個值')



# ── 表格視窗 ────────────────────────────────────────────────────────

def brush(r, g, b):
    return SolidColorBrush(Color.FromRgb(r, g, b))


class ParamGridWindow(forms.WPFWindow):
    def __init__(self, xaml, columns, records, original, values,
                 labels=None):
        forms.WPFWindow.__init__(self, xaml)
        self.labels = labels or ROOM_LABELS
        self.columns = columns
        self.records = records
        self.original = original
        self.result = None
        self.row_by_id = {}
        self.change_count = {}
        self._bulk = False
        self._build(values)
        self.grid.PreviewKeyDown += self._key_down
        self.exportButton.Click += self._export
        self.importButton.Click += self._import
        self.revertButton.Click += self._revert
        self.applyButton.Click += self._apply
        self.cancelButton.Click += self._cancel
        # ContextMenu 不在視覺樹裡，名稱查找不一定找得到，依序綁定。
        handlers = [self._copy, lambda s, a: self._paste(),
                    lambda s, a: self._fill_down(), lambda s, a: self._clear()]
        for item, handler in zip(list(self.grid.ContextMenu.Items), handlers):
            item.Click += handler
        self._refresh_all()

    # 建表 --------------------------------------------------------------
    def _build(self, values):
        table = DataTable('rooms')
        for column in self.columns:
            table.Columns.Add(column['key'], String)
        table.Columns.Add(KEY_CHANGED, String)
        # 排序用的影子欄：DataView 只會照字串排，「編號」會排成 1、10、2，
        # 所以每欄另存一份數字補零的自然排序鍵，欄位標題點下去排的是它。
        self._sort_of = {}
        for column in self.columns:
            sort_key = column['key'] + SORT_SUFFIX
            table.Columns.Add(sort_key, String)
            self._sort_of[column['key']] = sort_key
        for record in self.records:
            row = table.NewRow()
            current = values.get(record['id'], {})
            for column in self.columns:
                if column['key'] == KEY_ID:
                    row[KEY_ID] = logic.text(record['id'])
                else:
                    row[column['key']] = logic.text(current.get(column['key']))
            row[KEY_CHANGED] = u''
            for key, sort_key in self._sort_of.items():
                row[sort_key] = logic.natural_sort_key(self._cell(row, key))
            table.Rows.Add(row)
            self.row_by_id[record['id']] = row
        self.table = table

        readonly_style = Style(DataGridCell)
        readonly_style.Setters.Add(
            Setter(Control.BackgroundProperty, brush(0xEE, 0xF1, 0xF4)))
        readonly_style.Setters.Add(
            Setter(Control.ForegroundProperty, brush(0x6B, 0x77, 0x82)))
        for column in self.columns:
            grid_column = DataGridTextColumn()
            grid_column.Header = column['header'] if column['editable'] \
                else u'{}（唯讀）'.format(column['header'])
            grid_column.Binding = Binding(u'[{}]'.format(column['key']))
            # 不指定的話 DataGrid 會拿綁定路徑 "[p0]" 當排序欄名，DataView
            # 找不到這個欄位就丟例外（「沒有名為 '[p0]' 的屬性」）。
            grid_column.SortMemberPath = self._sort_of[column['key']]
            grid_column.IsReadOnly = not column['editable']
            if not column['editable']:
                grid_column.CellStyle = readonly_style
            grid_column.MinWidth = 70
            grid_column.Width = DataGridLength.Auto
            self.grid.Columns.Add(grid_column)
        changed_column = DataGridTextColumn()
        changed_column.Header = u'已改'
        changed_column.Binding = Binding(u'[{}]'.format(KEY_CHANGED))
        changed_column.IsReadOnly = True
        changed_column.SortMemberPath = KEY_CHANGED
        changed_column.MinWidth = 46
        self.grid.Columns.Add(changed_column)

        self.grid.ItemsSource = table.DefaultView
        table.ColumnChanged += self._column_changed

    # 讀寫格子 ----------------------------------------------------------
    @staticmethod
    def _cell(row, key):
        value = row[key]
        if value is None or value is DBNull.Value:
            return u''
        return logic.text(value)

    def _row_at(self, index):
        return self.grid.Items[index].Row

    def _selected(self):
        cells = []
        for info in self.grid.SelectedCells:
            row = self.grid.Items.IndexOf(info.Item)
            col = self.grid.Columns.IndexOf(info.Column)
            if row >= 0 and 0 <= col < len(self.columns):
                cells.append((row, col))
        return cells

    def _anchor(self, selected):
        try:
            current = self.grid.CurrentCell
            if current.Item is not None and current.Column is not None:
                row = self.grid.Items.IndexOf(current.Item)
                col = self.grid.Columns.IndexOf(current.Column)
                if len(selected) <= 1 and row >= 0 and col >= 0:
                    return (row, col)
        except Exception:
            pass
        return logic.anchor_of(selected)

    def _apply_writes(self, writes, skipped, action):
        self.grid.CommitEdit(DataGridEditingUnit.Row, True)
        # 先把列索引全部換成 DataRow 再寫：表格有排序時，寫一格就可能讓
        # 列重排，邊寫邊用索引找列會寫到別間。
        targets = [(self._row_at(row_index), self.columns[col]['key'], value)
                   for row_index, col, value in writes]
        self._bulk = True
        try:
            for row, key, value in targets:
                row[key] = value
        finally:
            self._bulk = False
        self._refresh_all()
        note = u'{}：{} 格'.format(action, len(writes))
        if skipped:
            note += u'，略過唯讀 {} 格'.format(skipped)
        self._set_status(note)

    # 鍵盤 --------------------------------------------------------------
    def _key_down(self, sender, args):
        if isinstance(args.OriginalSource, TextBox):
            return  # 格子正在編輯：交給 TextBox 自己處理貼上/刪除
        ctrl = Keyboard.Modifiers & ModifierKeys.Control
        if ctrl and args.Key == Key.V:
            self._paste()
            args.Handled = True
        elif ctrl and args.Key == Key.D:
            self._fill_down()
            args.Handled = True
        elif args.Key == Key.Delete and not ctrl:
            self._clear()
            args.Handled = True

    def _copy(self, sender, args):
        ApplicationCommands.Copy.Execute(None, self.grid)

    def _paste(self):
        try:
            if not Clipboard.ContainsText():
                return
            raw = Clipboard.GetText()
        except Exception:
            return
        selected = self._selected()
        writes, skipped = logic.paste_plan(
            logic.parse_clipboard(raw), self._anchor(selected), selected,
            self.grid.Items.Count, self.columns)
        self._apply_writes(writes, skipped, u'貼上')

    def _fill_down(self):
        writes, skipped = logic.fill_down_plan(
            self._selected(),
            lambda row, col: self._cell(self._row_at(row),
                                        self.columns[col]['key']),
            self.columns)
        self._apply_writes(writes, skipped, u'向下填滿')

    def _clear(self):
        writes, skipped = logic.clear_plan(self._selected(), self.columns)
        self._apply_writes(writes, skipped, u'清空')

    # 變更追蹤 ----------------------------------------------------------
    def values(self):
        result = {}
        for room_id, row in self.row_by_id.items():
            result[room_id] = dict(
                (column['key'], self._cell(row, column['key']))
                for column in self.columns if column['key'] != KEY_ID)
        return result

    def _refresh_row(self, room_id):
        row = self.row_by_id[room_id]
        current = {room_id: dict((column['key'], self._cell(row, column['key']))
                                 for column in self.columns)}
        count = len(logic.changes(current, self.original, self.columns))
        self.change_count[room_id] = count
        self._bulk = True
        try:
            row[KEY_CHANGED] = logic.text(count) if count else u''
        finally:
            self._bulk = False

    def _refresh_all(self):
        for room_id in self.row_by_id:
            self._refresh_row(room_id)
        self._set_status(u'')

    def _set_status(self, note):
        cells = sum(self.change_count.values())
        rooms = len([1 for count in self.change_count.values() if count])
        text = u'{} {} · 已修改 {} 格（{} {}）'.format(
            len(self.records), self.labels['unit'], cells, rooms,
            self.labels['unit_short'])
        if note:
            text += u' · ' + note
        self.statusText.Text = text

    def _column_changed(self, sender, args):
        name = args.Column.ColumnName
        sort_key = self._sort_of.get(name)
        if sort_key is None:
            return  # 排序影子欄或「已改」欄本身的變動
        args.Row[sort_key] = logic.natural_sort_key(self._cell(args.Row, name))
        if self._bulk:
            return
        try:
            room_id = int(self._cell(args.Row, KEY_ID))
        except Exception:
            return
        self._refresh_row(room_id)
        self._set_status(u'')

    # 按鈕 --------------------------------------------------------------
    def _export(self, sender, args):
        self.grid.CommitEdit(DataGridEditingUnit.Row, True)
        path = forms.save_file(file_ext='xlsx', default_name=self.labels['export_name'],
                               title=u'匯出 Excel')
        if not path:
            return
        if not path.lower().endswith('.xlsx'):
            path += '.xlsx'
        rows = logic.export_rows(self.columns, self.records, self.values())
        widths = [12] + [18] * (len(self.columns) - 1)
        try:
            xlsx_writer.write_workbook(path, [
                (logic.SHEET_NAME, rows,
                 {'freeze': 1, 'widths': widths,
                  'formats': {1: xlsx_xml.STYLE_INT}}),
                (logic.NOTE_SHEET_NAME, logic.note_rows(self.columns),
                 {'widths': [28, 48]}),
            ])
        except Exception as error:
            forms.alert(u'匯出失敗（檔案是否正被 Excel 開著？）\n\n{}'.format(
                error), title=self.labels['title'])
            return
        self._set_status(u'已匯出 {}'.format(os.path.basename(path)))

    def _import(self, sender, args):
        self.grid.CommitEdit(DataGridEditingUnit.Row, True)
        path = forms.pick_file(file_ext='xlsx')
        if not path:
            return
        try:
            book = code_integrity_excel.read_workbook(path)
        except Exception as error:
            forms.alert(u'讀取 Excel 失敗：\n\n{}'.format(error), title=self.labels['title'])
            return
        sheets = book.get('sheets') or {}
        sheet = sheets.get(logic.SHEET_NAME)
        if sheet is None and len(sheets) == 1:
            sheet = list(sheets.values())[0]
        if sheet is None:
            forms.alert(u'找不到工作表「{}」。'.format(logic.SHEET_NAME),
                        title=self.labels['title'])
            return
        sheet_rows = [line.get('values') or [] for line in sheet['rows']]
        plan = logic.import_plan(sheet_rows, self.columns,
                                 list(self.row_by_id.keys()))
        if plan['error']:
            forms.alert(plan['error'], title=self.labels['title'])
            return
        applied = 0
        self._bulk = True
        try:
            for room_id, key, value in plan['writes']:
                row = self.row_by_id[room_id]
                if self._cell(row, key).strip() != value.strip():
                    row[key] = value
                    applied += 1
        finally:
            self._bulk = False
        self._refresh_all()
        forms.alert(logic.import_summary(plan, applied), title=self.labels['title'])

    def _revert(self, sender, args):
        self.grid.CancelEdit()
        self._bulk = True
        try:
            for room_id, row in self.row_by_id.items():
                before = self.original.get(room_id, {})
                for column in self.columns:
                    if column['editable']:
                        row[column['key']] = before.get(column['key'], u'')
        finally:
            self._bulk = False
        self._refresh_all()

    def _apply(self, sender, args):
        self.grid.CommitEdit(DataGridEditingUnit.Row, True)
        if not sum(self.change_count.values()):
            forms.alert(u'目前沒有任何修改。', title=self.labels['title'])
            return
        self.result = 'apply'
        self.Close()

    def _cancel(self, sender, args):
        self.Close()
