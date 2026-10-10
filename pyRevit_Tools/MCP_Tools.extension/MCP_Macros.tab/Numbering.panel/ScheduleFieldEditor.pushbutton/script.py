# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""明細表欄位編輯.

複選明細表 → 雙欄編輯器（可用欄位 ⇄ 明細表欄位，跟 Revit「明細表性質 >
欄位」同一個概念）：加入、移除、排序、改欄位標題，每張明細表各自編輯，
也可以把某一張的欄位設定複製到其他張 → 關閉後 dry-run 預覽（會被一併
刪掉的篩選、排序/組成群組條件會列出警告）→ 單一 Transaction 寫入。

編輯操作與差異比對在 ``schedule_fields_logic``（有 CPython 測試）。
任何一張寫入失敗就整批回復，並帶著修改重開編輯器。
"""

__title__ = u'明細表\n欄位編輯'
__author__ = 'RevitMCP'

import os

from Autodesk.Revit import DB
from pyrevit import forms, revit, script

import clr
clr.AddReference('System.Data')

from System import Boolean, DBNull, String
from System.Collections.Generic import List
from System.Data import DataTable
from System.Windows.Controls import (DataGridCheckBoxColumn,
                                     DataGridEditingUnit, DataGridLength,
                                     DataGridLengthUnitType,
                                     DataGridTextColumn, ListBoxItem)
from System.Windows.Data import Binding

import mcp_window as ui
import mcp_window_logic as spec_logic
import schedule_fields_logic as logic


TITLE = u'明細表欄位編輯'
XAML = os.path.join(os.path.dirname(__file__), 'ScheduleFieldEditor.xaml')


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


def _is_fixed(field):
    """計算值/百分比/組合參數：無法從可用欄位重新加回。"""
    try:
        if field.IsCalculatedField:
            return True
    except Exception:
        pass
    try:
        if field.IsCombinedParameterField:  # 2022+
            return True
    except Exception:
        pass
    try:
        return field.FieldType in (DB.ScheduleFieldType.Formula,
                                   DB.ScheduleFieldType.Percentage)
    except Exception:
        return False


def _schedules(doc):
    result = []
    for view in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        try:
            if view.IsTemplate or view.IsTitleblockRevisionSchedule:
                continue
            view.Definition
        except Exception:
            continue
        result.append(view)
    result.sort(key=lambda v: v.Name.lower())
    return result


def _source(field_type):
    try:
        if field_type == DB.ScheduleFieldType.ElementType:
            return u'類型'
    except Exception:
        pass
    return u''


def _read_schedule(doc, view):
    """回傳 ``(used, available, schedulable_by_key)``。"""
    definition = view.Definition
    used = []
    seen = set()
    for field_id in definition.GetFieldOrder():
        field = definition.GetField(field_id)
        fid = field_id.IntegerValue
        fixed = _is_fixed(field)
        key = None
        if not fixed:
            key = logic.field_key(int(field.FieldType),
                                  _id_value(field.ParameterId))
            if key in seen:
                key, fixed = None, True
        if key is None:
            key = logic.fixed_key(fid)
        seen.add(key)
        try:
            name = field.GetName()
        except Exception:
            name = field.ColumnHeading
        used.append(logic.entry(key, name, heading=field.ColumnHeading,
                                hidden=field.IsHidden, fixed=fixed,
                                field_id=fid,
                                source=_source(field.FieldType)))
    available = []
    schedulable_by_key = {}
    for schedulable in definition.GetSchedulableFields():
        key = logic.field_key(int(schedulable.FieldType),
                              _id_value(schedulable.ParameterId))
        if key in schedulable_by_key:
            continue
        schedulable_by_key[key] = schedulable
        try:
            name = schedulable.GetName(doc)
        except Exception:
            continue
        available.append(logic.entry(key, name,
                                     source=_source(schedulable.FieldType)))
    return used, available, schedulable_by_key


def _filter_sort_usage(definition):
    """``{field_id: [說明…]}``：哪些欄位被篩選、排序/組成群組用到。"""
    usage = {}
    for index in range(definition.GetFilterCount()):
        fid = definition.GetFilter(index).FieldId.IntegerValue
        usage.setdefault(fid, []).append(u'篩選條件')
    for index in range(definition.GetSortGroupFieldCount()):
        fid = definition.GetSortGroupField(index).FieldId.IntegerValue
        usage.setdefault(fid, []).append(u'排序/組成群組')
    return usage


# ── 編輯器視窗 ──────────────────────────────────────────────────────

class FieldEditorWindow(forms.WPFWindow):
    def __init__(self, items, originals, states):
        forms.WPFWindow.__init__(self, XAML)
        self.items = items              # [{'id', 'name'}]
        self.originals = originals      # {sid: state}
        self.states = states            # {sid: state}
        self.current = items[0]['id']
        self.result = None
        self._loading = False

        self.scheduleList.SelectionChanged += self._schedule_changed
        self.filterBox.TextChanged += lambda s, a: self._fill_pool()
        self.poolList.MouseDoubleClick += lambda s, a: self._add(None, None)
        self._build_grid()
        self.hideButton.Click += lambda s, a: self._edit(
            lambda st, keys: logic.set_hidden(st, keys, True), True)
        self.showButton.Click += lambda s, a: self._edit(
            lambda st, keys: logic.set_hidden(st, keys, False), True)
        self.addButton.Click += self._add
        self.removeButton.Click += self._remove
        self.upButton.Click += lambda s, a: self._edit(
            lambda st, keys: logic.move(st, keys, -1), True)
        self.downButton.Click += lambda s, a: self._edit(
            lambda st, keys: logic.move(st, keys, 1), True)
        self.topButton.Click += lambda s, a: self._edit(
            lambda st, keys: logic.move_to_edge(st, keys, True), True)
        self.bottomButton.Click += lambda s, a: self._edit(
            lambda st, keys: logic.move_to_edge(st, keys, False), True)
        self.copyButton.Click += self._copy
        self.revertButton.Click += self._revert
        self.applyButton.Click += self._apply
        self.cancelButton.Click += lambda s, a: self.Close()

        self._fill_schedules()
        self.scheduleList.SelectedIndex = 0

    # 狀態 --------------------------------------------------------------
    def _state(self):
        return self.states[self.current]

    def _changed(self, sid):
        return logic.diff(self.originals[sid]['used'],
                          self.states[sid]['used'])['changed']

    def _status(self, note=u''):
        changed = len([1 for i in self.items if self._changed(i['id'])])
        text = u'{} 張明細表 · 已修改 {} 張'.format(len(self.items), changed)
        if note:
            text += u' · ' + note
        self.statusText.Text = text

    # 清單填充 ----------------------------------------------------------
    @staticmethod
    def _item(text, tag):
        item = ListBoxItem()
        item.Content = text
        item.Tag = tag
        return item

    def _fill_schedules(self):
        self._loading = True
        try:
            selected = self.scheduleList.SelectedIndex
            self.scheduleList.Items.Clear()
            for info in self.items:
                mark = u'● ' if self._changed(info['id']) else u'    '
                self.scheduleList.Items.Add(
                    self._item(mark + info['name'], info['id']))
            if selected >= 0:
                self.scheduleList.SelectedIndex = selected
        finally:
            self._loading = False
        self._status()

    def _fill_pool(self):
        self.poolList.Items.Clear()
        keyword = self.filterBox.Text
        for entry in self._state()['pool']:
            if logic.matches(entry, keyword):
                self.poolList.Items.Add(
                    self._item(logic.label(entry, in_pool=True), entry['key']))

    def _build_grid(self):
        name_column = DataGridTextColumn()
        name_column.Header = u'欄位'
        name_column.Binding = Binding(u'[name]')
        name_column.IsReadOnly = True
        name_column.Width = DataGridLength(1, DataGridLengthUnitType.Star)
        heading_column = DataGridTextColumn()
        heading_column.Header = u'欄位標題（可編輯）'
        heading_column.Binding = Binding(u'[heading]')
        heading_column.Width = DataGridLength(1, DataGridLengthUnitType.Star)
        hidden_column = DataGridCheckBoxColumn()
        hidden_column.Header = u'隱藏'
        hidden_column.Binding = Binding(u'[hidden]')
        hidden_column.Width = DataGridLength(52)
        for column in (name_column, heading_column, hidden_column):
            self.usedGrid.Columns.Add(column)
        self.table = None

    @staticmethod
    def _value(row, key):
        value = row[key]
        if value is None or value is DBNull.Value:
            return u''
        return value

    def _fill_used(self, select_keys=None):
        self._loading = True
        try:
            table = DataTable('fields')
            for name in ('key', 'name', 'heading'):
                table.Columns.Add(name, String)
            table.Columns.Add('hidden', Boolean)
            for entry in self._state()['used']:
                row = table.NewRow()
                row['key'] = entry['key']
                text = logic.display_name(entry)
                if entry['fixed']:
                    text += u'（計算值）'
                if entry['field_id'] is None:
                    text += u' ＋新增'
                row['name'] = text
                row['heading'] = entry['heading']
                row['hidden'] = entry['hidden']
                table.Rows.Add(row)
            table.ColumnChanged += self._cell_changed
            self.table = table
            self.usedGrid.ItemsSource = table.DefaultView
            wanted = set(select_keys or [])
            for item in list(self.usedGrid.Items):
                if item.Row['key'] in wanted:
                    self.usedGrid.SelectedItems.Add(item)
        finally:
            self._loading = False

    def _cell_changed(self, sender, args):
        if self._loading:
            return
        name = args.Column.ColumnName
        key = self._value(args.Row, 'key')
        if name == 'heading':
            heading = logic.text(self._value(args.Row, 'heading'))
            if not heading.strip():
                return  # 空白標題不收，切換明細表或重繪時會還原
            self.states[self.current] = logic.set_heading(
                self._state(), key, heading)
        elif name == 'hidden':
            self.states[self.current] = logic.set_hidden(
                self._state(), [key], bool(self._value(args.Row, 'hidden')))
        else:
            return
        self._fill_schedules()

    def _refresh(self, select_keys=None):
        self._fill_pool()
        self._fill_used(select_keys)
        self._fill_schedules()

    def _selected_keys(self, control):
        if control is self.usedGrid:
            self.usedGrid.CommitEdit(DataGridEditingUnit.Row, True)
            return [item.Row['key'] for item in self.usedGrid.SelectedItems]
        return [item.Tag for item in control.SelectedItems]

    # 事件 --------------------------------------------------------------
    def _schedule_changed(self, sender, args):
        if self._loading:
            return
        item = self.scheduleList.SelectedItem
        if item is None:
            return
        self.current = item.Tag
        self.usedGrid.CommitEdit(DataGridEditingUnit.Row, True)
        self._fill_pool()
        self._fill_used()

    def _add(self, sender, args):
        keys = self._selected_keys(self.poolList)
        if not keys:
            return
        used_keys = logic.keys_of(self._state()['used'])
        picked = [used_keys.index(k) for k in
                  self._selected_keys(self.usedGrid) if k in used_keys]
        at = max(picked) + 1 if picked else None
        self.states[self.current] = logic.add(self._state(), keys, at)
        self._refresh(keys)

    def _remove(self, sender, args):
        keys = self._selected_keys(self.usedGrid)
        if not keys:
            return
        self.states[self.current] = logic.remove(self._state(), keys)
        self._refresh()

    def _edit(self, operation, keep_selection):
        keys = self._selected_keys(self.usedGrid)
        if not keys:
            return
        self.states[self.current] = operation(self._state(), keys)
        self._refresh(keys if keep_selection else None)

    def _copy(self, sender, args):
        others = [i for i in self.items if i['id'] != self.current]
        if not others:
            forms.alert(u'只選了一張明細表，沒有可以複製過去的對象。',
                        title=TITLE)
            return
        spec = spec_logic.spec(
            u'複製欄位設定',
            [spec_logic.multichoice(
                'targets', u'複製到', [(i['name'], i['id']) for i in others],
                required=True, filter=True,
                help=u'目標明細表的欄位會換成這張的欄位、順序與標題；'
                     u'目標沒有的可用欄位會略過並列出。'),
             spec_logic.note(u'只改編輯器內的狀態，寫入前仍會預覽。')],
            badge=spec_logic.BADGE_READONLY, run_label=u'複製',
            width=620, height=600)
        values = ui.ask(spec)
        if not values:
            return
        source = self._state()['used']
        report = []
        for sid in values.get('targets') or []:
            state, missing = logic.copy_layout(source, self.states[sid])
            self.states[sid] = state
            if missing:
                name = [i['name'] for i in self.items if i['id'] == sid][0]
                report.append(u'{}：略過 {}'.format(name, u'、'.join(missing)))
        self._fill_schedules()
        message = u'已複製到 {} 張明細表。'.format(
            len(values.get('targets') or []))
        if report:
            message += u'\n\n以下欄位在目標明細表不存在，已略過：\n' + \
                u'\n'.join(report)
        forms.alert(message, title=TITLE)

    def _revert(self, sender, args):
        self.states[self.current] = logic.clone(self.originals[self.current])
        self._refresh()

    def _apply(self, sender, args):
        self.usedGrid.CommitEdit(DataGridEditingUnit.Row, True)
        if not [1 for i in self.items if self._changed(i['id'])]:
            forms.alert(u'目前沒有任何修改。', title=TITLE)
            return
        self.result = 'apply'
        self.Close()


# ── 預覽與寫入 ──────────────────────────────────────────────────────

def _plan(views, originals, states):
    plans = []
    for view in views:
        sid = _id_value(view.Id)
        change = logic.diff(originals[sid]['used'], states[sid]['used'])
        if not change['changed']:
            continue
        usage = _filter_sort_usage(view.Definition)
        warnings = []
        for entry in change['removed']:
            for what in usage.get(entry['field_id'], []):
                warnings.append(u'移除「{}」會一併刪除它的{}'.format(
                    entry['name'], what))
        plans.append({'view': view, 'sid': sid, 'change': change,
                      'warnings': warnings})
    return plans


def _print_preview(plans):
    output = script.get_output()
    output.print_md(u'## {} — 寫入預覽'.format(TITLE))
    for plan in plans:
        output.print_md(u'### {} {}'.format(
            plan['view'].Name, output.linkify(plan['view'].Id)))
        for line in logic.summary_lines(plan['change']):
            output.print_md(u'- ' + line)
        for line in plan['warnings']:
            output.print_md(u'- ⚠ **{}**'.format(line))


def _write_one(view, state, schedulable_by_key, removed):
    definition = view.Definition
    removed_ids = set(e['field_id'] for e in removed)
    # 先刪掉引用被移除欄位的篩選與排序（倒序刪，索引才不會跑掉）。
    for index in range(definition.GetFilterCount() - 1, -1, -1):
        if definition.GetFilter(index).FieldId.IntegerValue in removed_ids:
            definition.RemoveFilter(index)
    for index in range(definition.GetSortGroupFieldCount() - 1, -1, -1):
        if definition.GetSortGroupField(index).FieldId.IntegerValue \
                in removed_ids:
            definition.RemoveSortGroupField(index)
    id_by_value = dict((fid.IntegerValue, fid)
                       for fid in definition.GetFieldOrder())
    for fid in removed_ids:
        definition.RemoveField(id_by_value[fid])

    order = List[DB.ScheduleFieldId]()
    for entry in state['used']:
        if entry['field_id'] is None:
            schedulable = schedulable_by_key.get(entry['key'])
            if schedulable is None:
                raise Exception(u'找不到可用欄位「{}」'.format(entry['name']))
            field = definition.AddField(schedulable)
        else:
            field = definition.GetField(id_by_value[entry['field_id']])
        if field.ColumnHeading != entry['heading']:
            field.ColumnHeading = entry['heading']
        if field.IsHidden != entry['hidden']:
            field.IsHidden = entry['hidden']
        order.Add(field.FieldId)
    definition.SetFieldOrder(order)


def _commit(doc, plans, states, schedulable):
    failures = []
    transaction = DB.Transaction(doc, TITLE)
    transaction.Start()
    try:
        for plan in plans:
            try:
                _write_one(plan['view'], states[plan['sid']],
                           schedulable[plan['sid']],
                           plan['change']['removed'])
            except Exception as error:
                failures.append(u'{}：{}'.format(plan['view'].Name, error))
        if failures:
            transaction.RollBack()
        else:
            transaction.Commit()
    except Exception as error:
        if transaction.HasStarted() and not transaction.HasEnded():
            transaction.RollBack()
        failures.append(u'{}'.format(error))
    return failures


# ── 流程 ────────────────────────────────────────────────────────────

def _ask(views):
    active = None
    try:
        active = _id_value(revit.active_view.Id)
    except Exception:
        pass
    options = [(v.Name, _id_value(v.Id)) for v in views]
    spec = spec_logic.spec(
        TITLE,
        [spec_logic.multichoice(
            'schedules', u'明細表', options,
            default=[active] if active in [o[1] for o in options] else [],
            required=True, filter=True,
            help=u'可輸入名稱關鍵字篩選；Shift+點擊可連選。'
                 u'目前開啟的明細表已預先勾選。'),
         spec_logic.note(
             u'下一步開啟雙欄編輯器：可用欄位 ⇄ 明細表欄位，可加入、移除、'
             u'排序、直接在表格改欄位標題、批次隱藏/取消隱藏，或把一張的設定複製到其他張；寫入前會先預覽。')],
        badge=spec_logic.BADGE_WRITE, run_label=u'開啟編輯器',
        width=680, height=720)
    values = ui.ask(spec)
    return (values or {}).get('schedules') or []


def main():
    doc = revit.doc
    views = _schedules(doc)
    if not views:
        forms.alert(u'這個專案沒有明細表。', title=TITLE)
        return
    chosen_ids = set(_ask(views))
    if not chosen_ids:
        return
    chosen = [v for v in views if _id_value(v.Id) in chosen_ids]

    originals = {}
    schedulable = {}
    for view in chosen:
        sid = _id_value(view.Id)
        used, available, by_key = _read_schedule(doc, view)
        originals[sid] = logic.new_state(used, available)
        schedulable[sid] = by_key
    states = dict((sid, logic.clone(s)) for sid, s in originals.items())
    items = [{'id': _id_value(v.Id), 'name': v.Name} for v in chosen]

    while True:
        window = FieldEditorWindow(items, originals, states)
        window.ShowDialog()
        if window.result != 'apply':
            return
        states = window.states
        plans = _plan(chosen, originals, states)
        if not plans:
            return
        _print_preview(plans)
        warning_count = sum(len(p['warnings']) for p in plans)
        message = u'【dry-run 預覽】模型目前未變更。\n\n將修改 {} 張明細表，' \
            u'明細在輸出視窗。'.format(len(plans))
        if warning_count:
            message += u'\n\n⚠ 有 {} 個篩選或排序/組成群組條件會因為移除欄位' \
                u'而一併刪除（輸出視窗有列出）。'.format(warning_count)
        message += u'\n\n確定寫入嗎？選「否」回到編輯器繼續修改。'
        if not forms.alert(message, title=TITLE, yes=True, no=True):
            continue
        failures = _commit(doc, plans, states, schedulable)
        if failures:
            forms.alert(
                u'寫入失敗，交易已完整回復，模型未變更。\n'
                u'編輯器會重新開啟（你的修改都還在）。\n\n{}'.format(
                    u'\n'.join(failures[:20])), title=TITLE)
            continue
        forms.alert(u'已修改 {} 張明細表。'.format(len(plans)), title=TITLE)
        return


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
