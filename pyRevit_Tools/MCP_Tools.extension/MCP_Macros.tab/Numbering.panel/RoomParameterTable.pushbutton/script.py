# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""房間參數表.

複選房間 → 複選參數 → 表格顯示（唯讀參數灰底只顯示）→ 表格內 Ctrl+C/V、
Ctrl+D 向下填滿、匯出/匯入 Excel → 關閉表格後 dry-run 預覽 → 單一
Transaction 寫入。表格操作與 Excel 對應規則在 ``room_param_grid_logic``
（有 CPython 測試）。

表格是 modal 視窗，只收集修改；寫入在視窗關掉之後才做。寫入有任何一格
失敗就整批回復，並帶著原本的修改重新開表格讓使用者修正，不會丟掉編輯。
"""

__title__ = u'房間\n參數表'
__author__ = 'RevitMCP'

import os

from Autodesk.Revit import DB
from pyrevit import forms, revit, script

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
import mcp_window as ui
import mcp_window_logic as spec_logic
import room_param_grid_logic as logic
import xlsx_writer
import xlsx_xml


TITLE = u'房間參數表'
XAML = os.path.join(os.path.dirname(__file__), 'RoomParameterTable.xaml')

KEY_ID = 'k_id'
KEY_LEVEL = 'k_level'
KEY_CHANGED = 'k_changed'

KIND_TEXT = 'text'
KIND_INT = 'int'
KIND_DOUBLE = 'double'
KIND_YESNO = 'yesno'
KIND_OTHER = 'other'


# ── Revit 讀取 ──────────────────────────────────────────────────────

def _id_value(element_id):
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


def _element_id(value):
    try:
        return DB.ElementId(value)
    except Exception:
        return DB.ElementId(int(value))


def _builtin_text(element, bip):
    try:
        param = element.get_Parameter(bip)
        return (param.AsString() or u'') if param is not None else u''
    except Exception:
        return u''


def _builtin_name(element, bip):
    try:
        param = element.get_Parameter(bip)
        return param.Definition.Name if param is not None else u''
    except Exception:
        return u''


def _is_yesno(param):
    # 2022+ 用 GetDataType()；2020/2021 只有 ParameterType。以探測決定。
    try:
        return param.Definition.GetDataType() == DB.SpecTypeId.Boolean.YesNo
    except Exception:
        pass
    try:
        return param.Definition.ParameterType == DB.ParameterType.YesNo
    except Exception:
        return False


def _kind(param):
    storage = param.StorageType
    if storage == DB.StorageType.String:
        return KIND_TEXT
    if storage == DB.StorageType.Integer:
        return KIND_YESNO if _is_yesno(param) else KIND_INT
    if storage == DB.StorageType.Double:
        return KIND_DOUBLE
    return KIND_OTHER


def _rooms(doc):
    rooms = DB.FilteredElementCollector(doc) \
        .OfCategory(DB.BuiltInCategory.OST_Rooms) \
        .WhereElementIsNotElementType() \
        .ToElements()
    records = []
    for room in rooms:
        level = None
        try:
            level = room.Level
        except Exception:
            pass
        records.append({
            'id': _id_value(room.Id),
            'element': room,
            'number': _builtin_text(room, DB.BuiltInParameter.ROOM_NUMBER),
            'name': _builtin_text(room, DB.BuiltInParameter.ROOM_NAME),
            'level': level.Name if level is not None else u'',
            'elevation': level.Elevation if level is not None else 0.0,
            'placed': room.Location is not None,
        })
    records.sort(key=lambda r: (r['elevation'], r['level'], r['number'],
                                r['name'], r['id']))
    return records


def _param_infos(records):
    """全部房間的實例參數聯集 ``{name: info}``。

    同名參數只要有一間可寫就算可寫——個別房間寫不進去時，寫入階段會
    逐格回報並整批回復，不會悄悄略過。
    """
    infos = {}
    for record in records:
        for param in record['element'].Parameters:
            try:
                name = param.Definition.Name
            except Exception:
                continue
            if not name:
                continue
            kind = _kind(param)
            editable = (not param.IsReadOnly) and kind != KIND_OTHER
            info = infos.get(name)
            if info is None:
                infos[name] = {'name': name, 'kind': kind,
                               'editable': editable}
            elif editable and not info['editable']:
                info['editable'] = True
                info['kind'] = kind
    return infos


def _read(param, kind):
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


def _write(param, kind, value):
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

def _brush(r, g, b):
    return SolidColorBrush(Color.FromRgb(r, g, b))


class RoomParamWindow(forms.WPFWindow):
    def __init__(self, columns, records, original, values):
        forms.WPFWindow.__init__(self, XAML)
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
        for record in self.records:
            row = table.NewRow()
            current = values.get(record['id'], {})
            for column in self.columns:
                if column['key'] == KEY_ID:
                    row[KEY_ID] = logic.text(record['id'])
                else:
                    row[column['key']] = logic.text(current.get(column['key']))
            row[KEY_CHANGED] = u''
            table.Rows.Add(row)
            self.row_by_id[record['id']] = row
        self.table = table

        readonly_style = Style(DataGridCell)
        readonly_style.Setters.Add(
            Setter(Control.BackgroundProperty, _brush(0xEE, 0xF1, 0xF4)))
        readonly_style.Setters.Add(
            Setter(Control.ForegroundProperty, _brush(0x6B, 0x77, 0x82)))
        for column in self.columns:
            grid_column = DataGridTextColumn()
            grid_column.Header = column['header'] if column['editable'] \
                else u'{}（唯讀）'.format(column['header'])
            grid_column.Binding = Binding(u'[{}]'.format(column['key']))
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
        self._bulk = True
        try:
            for row_index, col, value in writes:
                self._row_at(row_index)[self.columns[col]['key']] = value
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
        text = u'{} 間房間 · 已修改 {} 格（{} 間）'.format(
            len(self.records), cells, rooms)
        if note:
            text += u' · ' + note
        self.statusText.Text = text

    def _column_changed(self, sender, args):
        if self._bulk or args.Column.ColumnName == KEY_CHANGED:
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
        path = forms.save_file(file_ext='xlsx', default_name=u'房間參數',
                               title=u'匯出房間參數 Excel')
        if not path:
            return
        if not path.lower().endswith('.xlsx'):
            path += '.xlsx'
        rows = logic.export_rows(self.columns, self.records, self.values())
        widths = [12, 10] + [18] * (len(self.columns) - 2)
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
                error), title=TITLE)
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
            forms.alert(u'讀取 Excel 失敗：\n\n{}'.format(error), title=TITLE)
            return
        sheets = book.get('sheets') or {}
        sheet = sheets.get(logic.SHEET_NAME)
        if sheet is None and len(sheets) == 1:
            sheet = list(sheets.values())[0]
        if sheet is None:
            forms.alert(u'找不到工作表「{}」。'.format(logic.SHEET_NAME),
                        title=TITLE)
            return
        sheet_rows = [line.get('values') or [] for line in sheet['rows']]
        plan = logic.import_plan(sheet_rows, self.columns,
                                 list(self.row_by_id.keys()))
        if plan['error']:
            forms.alert(plan['error'], title=TITLE)
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
        forms.alert(logic.import_summary(plan, applied), title=TITLE)

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
            forms.alert(u'目前沒有任何修改。', title=TITLE)
            return
        self.result = 'apply'
        self.Close()

    def _cancel(self, sender, args):
        self.Close()


# ── 流程 ────────────────────────────────────────────────────────────

def _ask(records, infos, preferred):
    selected_ids = set()
    try:
        for element_id in revit.uidoc.Selection.GetElementIds():
            selected_ids.add(_id_value(element_id))
    except Exception:
        pass
    room_options = [(logic.room_label(record), record['id'])
                    for record in records]
    ordered = logic.sort_params(list(infos.values()), preferred)
    param_options = [(logic.param_label(info), info['name'])
                     for info in ordered]
    spec = spec_logic.spec(
        TITLE,
        [
            spec_logic.multichoice(
                'rooms', u'房間', room_options,
                default=[r['id'] for r in records if r['id'] in selected_ids],
                required=True, filter=True,
                help=u'可輸入編號、名稱或樓層篩選；Shift+點擊可連選。'
                     u'目前在模型中選取的房間已預先勾選。'),
            spec_logic.multichoice(
                'params', u'要顯示的參數', param_options,
                default=[name for name in preferred if name in infos],
                required=True, filter=True,
                help=u'標「（唯讀）」的參數（面積、周長…）只顯示、不能改。'),
            spec_logic.note(
                u'下一步會開啟表格：可直接編輯、複製貼上、向下填滿、匯出匯入 '
                u'Excel；寫入模型前會先預覽。'),
        ],
        badge=spec_logic.BADGE_WRITE, run_label=u'開啟表格',
        width=720, height=760)
    values = ui.ask(spec)
    if not values:
        return None, None
    return values.get('rooms') or [], values.get('params') or []


def _print_preview(change_list, record_by_id):
    output = script.get_output()
    output.print_md(u'## {} — 寫入預覽'.format(TITLE))
    output.print_md(u'共 **{}** 格、**{}** 間房間。'.format(
        len(change_list), len(logic.changed_count_by_room(change_list))))
    output.print_table(
        table_data=[[output.linkify(record_by_id[c['id']]['element'].Id),
                     logic.room_label(record_by_id[c['id']]), c['header'],
                     c['old'], c['new']] for c in change_list],
        columns=[u'房間', u'編號名稱', u'參數', u'原值', u'新值'])


def _commit(doc, change_list, record_by_id, kind_by_key, name_by_key):
    """單一 Transaction。回傳失敗清單；有失敗就整批回復。"""
    failures = []
    transaction = DB.Transaction(doc, TITLE)
    transaction.Start()
    try:
        for change in change_list:
            record = record_by_id[change['id']]
            param = record['element'].LookupParameter(name_by_key[change['key']])
            try:
                _write(param, kind_by_key[change['key']], change['new'])
            except Exception as error:
                failures.append((record, change, u'{}'.format(error)))
        if failures:
            transaction.RollBack()
        else:
            transaction.Commit()
    except Exception as error:
        if transaction.HasStarted() and not transaction.HasEnded():
            transaction.RollBack()
        failures.append((None, None, u'{}'.format(error)))
    return failures


def _failure_text(failures):
    lines = []
    for record, change, reason in failures[:25]:
        if record is None:
            lines.append(reason)
        else:
            lines.append(u'{} ／ {} = 「{}」：{}'.format(
                logic.room_label(record), change['header'], change['new'],
                reason))
    if len(failures) > 25:
        lines.append(u'…另有 {} 格'.format(len(failures) - 25))
    return u'\n'.join(lines)


def main():
    doc = revit.doc
    records = _rooms(doc)
    if not records:
        forms.alert(u'這個專案沒有房間。', title=TITLE)
        return
    infos = _param_infos(records)
    first = records[0]['element']
    preferred = [name for name in (
        _builtin_name(first, DB.BuiltInParameter.ROOM_NUMBER),
        _builtin_name(first, DB.BuiltInParameter.ROOM_NAME)) if name]

    room_ids, param_names = _ask(records, infos, preferred)
    if not room_ids or not param_names:
        return
    wanted = set(room_ids)
    chosen = [record for record in records if record['id'] in wanted]
    record_by_id = dict((record['id'], record) for record in chosen)

    ordered = [info for info in logic.sort_params(list(infos.values()),
                                                  preferred)
               if info['name'] in set(param_names)]
    columns = [{'key': KEY_ID, 'header': logic.ID_HEADER, 'editable': False},
               {'key': KEY_LEVEL, 'header': logic.LEVEL_HEADER,
                'editable': False}]
    kind_by_key = {}
    name_by_key = {}
    for index, info in enumerate(ordered):
        key = 'p{}'.format(index)
        columns.append({'key': key, 'header': info['name'],
                        'editable': info['editable']})
        kind_by_key[key] = info['kind']
        name_by_key[key] = info['name']

    original = {}
    for record in chosen:
        row = {KEY_LEVEL: record['level']}
        for key, name in name_by_key.items():
            row[key] = _read(record['element'].LookupParameter(name),
                             kind_by_key[key])
        original[record['id']] = row

    values = dict((room_id, dict(row)) for room_id, row in original.items())
    while True:
        window = RoomParamWindow(columns, chosen, original, values)
        window.ShowDialog()
        if window.result != 'apply':
            return
        values = window.values()
        change_list = logic.changes(values, original, columns)
        if not change_list:
            return
        _print_preview(change_list, record_by_id)
        answer = forms.alert(
            u'【dry-run 預覽】模型目前未變更。\n\n將寫入 {} 格（{} 間房間），'
            u'明細在輸出視窗。\n\n確定寫入嗎？選「否」回到表格繼續編輯。'.format(
                len(change_list),
                len(logic.changed_count_by_room(change_list))),
            title=TITLE, yes=True, no=True)
        if not answer:
            continue
        failures = _commit(doc, change_list, record_by_id, kind_by_key,
                           name_by_key)
        if failures:
            forms.alert(
                u'有 {} 格寫不進去，交易已完整回復，模型未變更。\n'
                u'表格會重新開啟（你的修改都還在），請修正後再寫入。\n\n{}'
                .format(len(failures), _failure_text(failures)), title=TITLE)
            continue
        forms.alert(u'已寫入 {} 格（{} 間房間）。'.format(
            len(change_list), len(logic.changed_count_by_room(change_list))),
            title=TITLE)
        return


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
