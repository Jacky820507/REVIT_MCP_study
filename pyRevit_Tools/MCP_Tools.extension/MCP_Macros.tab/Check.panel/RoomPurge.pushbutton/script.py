# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""自動清除房間（JAC 04.11）.

Rooms accumulate junk. A room whose bounding walls were deleted survives as an
unenclosed element; a room dragged out of the model becomes 未放置. Both keep a
編號 and a 名稱, both appear in every schedule, and neither appears anywhere in
the drawings — so nobody notices until an 面積表 comes out with rows that have
no area.

Those two states are 「未涵蓋房間」 and they are ticked by default. The window
lists everything else too, so any other room can be added to the batch by hand,
but nothing else is ever pre-ticked.

Two deliberate refusals:

* **Redundant rooms are listed, not pre-ticked.** Two rooms in one enclosed
  region is a genuine defect, but which of the pair is the keeper is a question
  about intent. Choosing automatically would discard the right one half the
  time.
* **The checkbox list is built in code, not bound.** Plain IronPython objects
  do not raise ``INotifyPropertyChanged``, so a two-way ``IsChecked`` binding
  would read back stale values. The window keeps the CheckBox controls
  themselves, which also means filtering never loses a tick.

State is read from Revit's own warning GUIDs (``BuiltInFailures.RoomFailures``)
rather than from message text, which is localised.

Deleting is a single Transaction, all or nothing, and a backup of what is about
to go is offered first.
"""

__title__ = u'自動清除\n房間'
__author__ = 'RevitMCP'

import os

from Autodesk.Revit import DB
from pyrevit import forms, revit, script
from System.Windows import Thickness
from System.Windows.Controls import CheckBox

import room_purge_logic as logic
import xlsx_writer


TITLE = u'自動清除房間'
SQFT_TO_SQM = 0.09290304
FOOT_TO_M = 0.3048
ALL_STATES = u'（全部狀態）'
UNCOVERED_CHOICE = u'未涵蓋房間（未放置＋未封閉）'

EXPORT_CHOICES = (
    (u'先匯出房間清單再刪除（建議）', True),
    (u'直接刪除，不匯出', False),
)

_WARNING_GUIDS = {}


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


def _element_name(element):
    """``SpatialElement.Name`` is set-only, so it has to be read this way."""
    if element is None:
        return u''
    try:
        return DB.Element.Name.GetValue(element) or u''
    except Exception:
        try:
            return element.Name or u''
        except Exception:
            return u''


def _pick(options, title):
    labels = [label for label, unused in options]
    picked = forms.SelectFromList.show(labels, title=title, multiselect=False)
    if not picked:
        return None
    for label, value in options:
        if label == picked:
            return value
    return None


def _failure_guid(definition_id):
    if definition_id is None:
        return u''
    try:
        return u'{}'.format(definition_id.Guid)
    except Exception:
        return u''


def _warning_guids():
    """GUID -> kind, built once from ``BuiltInFailures.RoomFailures``.

    The ``...Rooms`` members, not the ``...Areas`` ones the area tools use —
    they are different failure definitions for different categories.
    """
    if _WARNING_GUIDS:
        return _WARNING_GUIDS
    failures = getattr(DB, 'BuiltInFailures', None)
    group = getattr(failures, 'RoomFailures', None) if failures else None
    if group is None:
        return _WARNING_GUIDS
    for attribute, kind in (('RoomUnplaceWarning', logic.KIND_NOT_PLACED),
                            ('RoomNotEnclosedRooms', logic.KIND_NOT_ENCLOSED),
                            ('RoomNotEnclosed', logic.KIND_NOT_ENCLOSED),
                            ('RoomsInSameRegionRooms', logic.KIND_REDUNDANT),
                            ('RoomsInSameRegion', logic.KIND_REDUNDANT)):
        guid = _failure_guid(getattr(group, attribute, None))
        if guid:
            _WARNING_GUIDS[guid] = kind
    return _WARNING_GUIDS


def _warning_kinds(doc):
    """``{room_id: [kind]}`` from the project's live warning list."""
    flags = {}
    try:
        warnings = list(doc.GetWarnings())
    except Exception:
        return flags
    known = _warning_guids()
    for warning in warnings:
        try:
            guid = _failure_guid(warning.GetFailureDefinitionId())
        except Exception:
            continue
        kind = known.get(guid)
        if not kind:
            continue
        try:
            failing = list(warning.GetFailingElements())
        except Exception:
            continue
        for element_id in failing:
            key = _id_value(element_id)
            kinds = flags.setdefault(key, [])
            if kind not in kinds:
                kinds.append(kind)
    return flags


def _rooms(doc):
    category = getattr(DB.BuiltInCategory, 'OST_Rooms', None)
    if category is None:
        return []
    try:
        return list(DB.FilteredElementCollector(doc)
                    .OfCategory(category)
                    .WhereElementIsNotElementType()
                    .ToElements())
    except Exception:
        return []


def _records(doc):
    kinds = _warning_kinds(doc)
    records = []
    for element in _rooms(doc):
        try:
            placed = element.Location is not None
        except Exception:
            placed = False
        try:
            area = float(element.Area) * SQFT_TO_SQM
        except Exception:
            area = 0.0
        try:
            perimeter = float(element.Perimeter) * FOOT_TO_M
        except Exception:
            perimeter = 0.0
        try:
            number = element.Number or u''
        except Exception:
            number = u''
        try:
            level = _element_name(element.Level)
        except Exception:
            level = u''
        room_id = _id_value(element.Id)
        records.append({
            'id': room_id,
            'element_id': element.Id,
            'number': number,
            'name': _element_name(element),
            'level': level,
            'area_m2': area,
            'perimeter_m': perimeter,
            'is_placed': placed,
            'warning_kinds': kinds.get(room_id, []),
        })
    return records


class RoomPurgeWindow(forms.WPFWindow):
    """Checkbox list built in code — see the module docstring for why."""

    def __init__(self, records):
        xaml = os.path.join(os.path.dirname(__file__), 'RoomPurge.xaml')
        forms.WPFWindow.__init__(self, xaml)
        self.records = records
        self.result = None
        self._ready = False

        self.states = [(ALL_STATES, None),
                       (UNCOVERED_CHOICE, list(logic.UNCOVERED_STATES))]
        for state in logic.STATE_ORDER:
            self.states.append((state, [state]))
        for label, unused in self.states:
            self.stateCombo.Items.Add(label)
        # Opening on 未涵蓋 rather than 全部: it is what the button is for,
        # and on a large model it keeps the first render to a handful of rows.
        self.stateCombo.SelectedIndex = 1

        # CheckBox controls are created on first sight and then kept, so that
        # changing the filter never discards a tick. Building all of them up
        # front would stall the window open on a model with thousands of rooms.
        self.boxes = {}
        self.default_ids = set(logic.default_selected_ids(records))

        self._ready = True
        self._refresh()

    def _box_for(self, item):
        box = self.boxes.get(item['id'])
        if box is not None:
            return box
        box = CheckBox()
        box.Content = u'{}　{}　{}　{}　{:.2f} m²'.format(
            item['state'],
            item.get('number') or u'(無編號)',
            item.get('name') or u'(無名稱)',
            item.get('level') or u'(無樓層)',
            item.get('area_m2') or 0.0)
        box.IsChecked = item['id'] in self.default_ids
        box.Margin = Thickness(0, 2, 0, 2)
        box.Tag = item['id']
        box.Checked += self._tick_changed
        box.Unchecked += self._tick_changed
        self.boxes[item['id']] = box
        return box

    def _tick_changed(self, sender, args):
        self._update_status()

    def _shown_items(self):
        index = self.stateCombo.SelectedIndex
        states = self.states[index][1] if index >= 0 else None
        query = self.searchText.Text or u''
        return logic.filter_rooms(self.records, states, query)

    def _refresh(self):
        if not self._ready:
            return
        self.roomList.Children.Clear()
        for item in sorted(self._shown_items(), key=logic.sort_key):
            self.roomList.Children.Add(self._box_for(item))
        self._update_status()

    def _selected_ids(self):
        """Only boxes that exist can be ticked; the rest are untouched rooms.

        Every default-ticked room is created when the window opens on 未涵蓋,
        so nothing pre-selected can be missed by never having been rendered.
        """
        return [room_id for room_id, box in self.boxes.items()
                if box.IsChecked]

    def _update_status(self):
        if not self._ready:
            return
        self.statusText.Text = u'已勾選 {} 個　目前顯示 {} 個　模型共 {} 個'.format(
            len(self._selected_ids()), self.roomList.Children.Count,
            len(self.records))

    # --- handlers -------------------------------------------------------

    def filter_changed(self, sender, args):
        self._refresh()

    def select_uncovered_clicked(self, sender, args):
        for item in logic.describe(self.records):
            if item['id'] in self.default_ids:
                self._box_for(item).IsChecked = True
        for room_id, box in self.boxes.items():
            if room_id not in self.default_ids:
                box.IsChecked = False
        self._update_status()

    def select_shown_clicked(self, sender, args):
        for item in self._shown_items():
            self._box_for(item).IsChecked = True
        self._update_status()

    def clear_all_clicked(self, sender, args):
        for box in self.boxes.values():
            box.IsChecked = False
        self._update_status()

    def cancel_clicked(self, sender, args):
        self.result = None
        self.Close()

    def ok_clicked(self, sender, args):
        chosen = self._selected_ids()
        if not chosen:
            forms.alert(u'還沒有勾選任何房間。', title=TITLE)
            return
        self.result = chosen
        self.Close()


def _safe_filename(text):
    return u''.join(u'_' if c in u'\\/:*?"<>|' else c
                    for c in u'{}'.format(text or u'')).strip() or u'Room'


def _default_name(doc):
    try:
        title = os.path.splitext(os.path.basename(doc.PathName))[0]
    except Exception:
        title = u''
    return u'{}_房間清除前備份.xlsx'.format(_safe_filename(title or u'Revit'))


def _export_backup(doc, plan):
    """Write what is about to be deleted. Returns path, or ``None`` if
    the user cancelled the save dialog."""
    path = forms.save_file(file_ext='xlsx', default_name=_default_name(doc))
    if not path:
        return None
    xlsx_writer.write_workbook(
        path, [(u'刪除前房間清單', logic.backup_rows(plan),
                logic.backup_spec())])
    return path


def _print_plan(plan):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    for group in plan['groups']:
        output.print_md(u'### {}（{} 個）'.format(group['state'],
                                                  len(group['records'])))
        output.print_table(
            table_data=[[output.linkify(item['element_id']),
                         item.get('number') or u'(無編號)',
                         item.get('name') or u'(無名稱)',
                         item.get('level') or u'',
                         u'{:.2f}'.format(item.get('area_m2') or 0.0)]
                        for item in group['records']],
            columns=[u'Element ID', u'編號', u'名稱', u'樓層', u'面積(m²)'])
    output.print_md(u'刪除房間會連同其編號、名稱與所有參數一起消失，'
                    u'本工具無法復原（Revit 的復原仍然有效）。')


def _delete(doc, plan):
    """Single Transaction, all or nothing. Returns ``(count, error)``."""
    transaction = DB.Transaction(doc, TITLE)
    try:
        transaction.Start()
        done = 0
        for item in plan['delete']:
            # Deleting one room never cascades to another, but re-checking
            # costs nothing and keeps a vanished id from aborting the batch.
            if doc.GetElement(item['element_id']) is None:
                continue
            doc.Delete(item['element_id'])
            done += 1
        transaction.Commit()
        return done, u''
    except Exception as error:
        try:
            if transaction.HasStarted():
                transaction.RollBack()
        except Exception:
            pass
        return 0, u'{}'.format(error)


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行清除。',
                    title=TITLE, exitscript=True)

    records = _records(doc)
    if not records:
        forms.alert(u'這個專案沒有房間（Room）。', title=TITLE)
        return

    window = RoomPurgeWindow(records)
    window.ShowDialog()
    if not window.result:
        return

    plan = logic.build_plan(records, window.result)
    if not logic.has_work(plan):
        forms.alert(u'沒有可刪除的房間，模型未變更。', title=TITLE)
        return

    _print_plan(plan)
    summary = logic.plan_lines(plan)

    wants_backup = _pick(EXPORT_CHOICES, u'刪除前要先備份房間清單嗎？')
    if wants_backup is None:
        return
    backup_path = None
    if wants_backup:
        try:
            backup_path = _export_backup(doc, plan)
        except Exception as error:
            forms.alert(u'備份失敗，未刪除任何東西：\n\n{}'.format(error),
                        title=TITLE)
            return
        if backup_path is None:
            # Cancelling the save dialog cancels the run: carrying on would
            # delete exactly what the person just asked to keep.
            forms.alert(u'已取消備份，因此也沒有刪除任何房間。', title=TITLE)
            return

    tail = u'\n備份：{}'.format(backup_path) if backup_path else u''
    if not forms.alert(
            u'【dry-run 預覽】模型目前未變更。\n\n{}\n{}\n\n'
            u'確定要刪除嗎？'.format(summary, tail),
            title=TITLE, yes=True, no=True):
        return

    done, error = _delete(doc, plan)
    if error:
        forms.alert(u'刪除失敗，交易已完整回復，房間都還在。\n\n{}'.format(error),
                    title=TITLE)
        return
    forms.alert(u'已刪除 {} 個房間。{}'.format(done, tail), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
