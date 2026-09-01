# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""依圖紙複選清除圖紙上的 Revit 修訂雲狀線。

這是獨立的清除工具，不依賴 MCP 連線：它直接在 pyRevit 的 Revit API
交易中執行，所以即使 MCP Server 暫時重連或回 409，也不會阻塞清除流程。

「圖紙」的範圍包含兩種常見情況：

* 雲形直接畫在 ViewSheet 上（圖說差異工具目前採用的方式）。
* 雲形畫在視圖內，而該視圖透過 Viewport 放在圖紙上（常見的手動畫法）。

清除前先掃描一次修訂雲並建立 View／圖紙對照，清除時只針對使用者勾選的
圖紙；交易失敗會完整回復，不會留下半批刪除的結果。
"""

__title__ = u'清除\n修訂雲'
__author__ = 'RevitMCP'

import os

from Autodesk.Revit import DB
from pyrevit import forms, revit
from System.Windows import Thickness
from System.Windows.Controls import CheckBox
from System.Collections.Generic import List

import pdf_diff_sources as sources


TITLE = u'清除修訂雲狀線'


def _id_value(element_id):
    """Read ElementId on R20 and newer Revit versions."""
    if element_id is None:
        return -1
    try:
        return int(element_id.Value)
    except Exception:
        try:
            return int(element_id.IntegerValue)
        except Exception:
            return -1


def _safe_sheet_id(record):
    try:
        return int(record.get('ElementId'))
    except Exception:
        return -1


def _safe_text(value):
    return u'{}'.format(value or u'').strip()


def _clear_sheet_records(doc):
    """Build the sheet list with one global title-block scan.

    ``sources.sheet_records`` is intentionally thorough for PDF matching: it
    creates a title-block collector for every sheet and reads every matching
    parameter from the sheet, title-block instance and type. The clear dialog
    only needs a display row, so doing that full pass here made opening the
    button unnecessarily slow on large projects.
    """
    try:
        sheets = list(DB.FilteredElementCollector(doc)
                      .OfClass(DB.ViewSheet)
                      .WhereElementIsNotElementType()
                      .ToElements())
    except Exception:
        return []

    # Read title blocks once, then attach their first DWG NO. value to the
    # owning sheet. Type values are cached because many sheets share a title
    # block type.
    dwg_by_sheet = {}
    type_dwg_cache = {}
    try:
        title_blocks = list(DB.FilteredElementCollector(doc)
                            .OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
                            .WhereElementIsNotElementType()
                            .ToElements())
    except Exception:
        title_blocks = []

    def append_values(target, values):
        for value in values or []:
            if value and value not in target:
                target.append(value)

    for title_block in title_blocks:
        try:
            sheet_id = _id_value(title_block.OwnerViewId)
        except Exception:
            continue
        if sheet_id <= 0:
            continue
        values = dwg_by_sheet.setdefault(sheet_id, [])
        try:
            append_values(values, sources._dwg_values_from_element(title_block))
        except Exception:
            pass
        try:
            type_id = _id_value(title_block.GetTypeId())
        except Exception:
            type_id = -1
        if type_id <= 0:
            continue
        if type_id not in type_dwg_cache:
            try:
                title_block_type = doc.GetElement(DB.ElementId(type_id))
                type_dwg_cache[type_id] = (
                    sources._dwg_values_from_element(title_block_type)
                    if title_block_type is not None else [])
            except Exception:
                type_dwg_cache[type_id] = []
        append_values(values, type_dwg_cache[type_id])

    rows = []
    for sheet in sheets:
        try:
            if sheet.IsTemplate:
                continue
        except Exception:
            pass
        try:
            sheet_id = _id_value(sheet.Id)
            number = sheet.SheetNumber
        except Exception:
            continue
        values = []
        try:
            append_values(values, sources._dwg_values_from_element(sheet))
        except Exception:
            pass
        append_values(values, dwg_by_sheet.get(sheet_id))
        try:
            name = sources.element_name(sheet)
        except Exception:
            name = u''
        rows.append({
            'SheetNumber': number,
            'SheetName': name,
            'DwgNumber': values[0] if values else None,
            'DwgNumberCandidates': values,
            'Outline': None,
            'ElementId': sheet_id,
        })

    rows.sort(key=lambda row: _safe_text(row.get('SheetNumber')).lower())
    return rows


def _view_to_sheet_ids(doc, wanted_view_ids=None, wanted_sheet_ids=None):
    """Return ``{view_id: [sheet_id, ...]}`` through placed viewports."""
    result = {}
    wanted_views = set(wanted_view_ids or [])
    wanted_sheets = set(wanted_sheet_ids or [])
    try:
        viewports = DB.FilteredElementCollector(doc).OfClass(DB.Viewport)
    except Exception:
        return result

    for viewport in viewports:
        try:
            view_id = _id_value(viewport.ViewId)
            sheet_id = _id_value(viewport.SheetId)
        except Exception:
            continue
        if view_id <= 0 or sheet_id <= 0:
            continue
        if wanted_views and view_id not in wanted_views:
            continue
        if wanted_sheets and sheet_id not in wanted_sheets:
            continue
        result.setdefault(view_id, []).append(sheet_id)
    return result


def _sheet_cloud_records(doc):
    """Return ``(sheet_records, unmapped_cloud_count)``.

    The clear-specific sheet reader keeps the custom DWG NO. display while
    avoiding the per-sheet title-block collectors used by the PDF matcher.
    """
    rows = _clear_sheet_records(doc)
    by_sheet_id = {}
    for row in rows:
        sheet_id = _safe_sheet_id(row)
        if sheet_id > 0:
            by_sheet_id[sheet_id] = row

    clouds_by_sheet = {}
    unmapped = 0
    try:
        clouds = list(DB.FilteredElementCollector(doc)
                      .OfClass(DB.RevisionCloud)
                      .WhereElementIsNotElementType()
                      .ToElements())
    except Exception:
        clouds = []

    cloud_entries = []
    view_ids_needing_mapping = set()
    for cloud in clouds:
        try:
            cloud_id = cloud.Id
            owner_id = _id_value(cloud.OwnerViewId)
        except Exception:
            unmapped += 1
            continue
        cloud_entries.append((cloud_id, owner_id))
        if owner_id > 0 and owner_id not in by_sheet_id:
            view_ids_needing_mapping.add(owner_id)

    # Most PDF-generated clouds are already owned by ViewSheet. Do not scan
    # every Viewport at all when there are no view-owned clouds to resolve.
    view_to_sheets = _view_to_sheet_ids(
        doc, view_ids_needing_mapping, by_sheet_id.keys()) \
        if view_ids_needing_mapping else {}

    for cloud_id, owner_id in cloud_entries:
        # A cloud created directly on a ViewSheet owns the sheet itself;
        # otherwise follow the Viewport(s) that place the owner view.
        target_sheet_ids = []
        if owner_id in by_sheet_id:
            target_sheet_ids = [owner_id]
        else:
            target_sheet_ids = view_to_sheets.get(owner_id, [])

        target_sheet_ids = [sheet_id for sheet_id in target_sheet_ids
                            if sheet_id in by_sheet_id]
        if not target_sheet_ids:
            # This is usually a cloud in an unplaced working view. It is
            # intentionally not included when the user says "圖紙".
            unmapped += 1
            continue

        for sheet_id in target_sheet_ids:
            # Keep only ElementId wrappers after the owner mapping. The UI
            # needs counts and the delete transaction needs IDs; retaining all
            # RevisionCloud objects adds memory and property access overhead.
            clouds_by_sheet.setdefault(sheet_id, []).append(cloud_id)

    records = []
    for row in rows:
        record = dict(row)
        record['id'] = _safe_sheet_id(row)
        record['clouds'] = clouds_by_sheet.get(record['id'], [])
        record['cloud_count'] = len(record['clouds'])
        records.append(record)

    records.sort(key=lambda item: _safe_text(item.get('SheetNumber')).lower())
    return records, unmapped


def _sheet_label(record):
    number = _safe_text(record.get('SheetNumber')) or u'(無 Revit 圖號)'
    dwg = _safe_text(record.get('DwgNumber'))
    name = _safe_text(record.get('SheetName')) or u'(無圖名)'
    count = int(record.get('cloud_count') or 0)
    parts = [number]
    if dwg and dwg != number:
        parts.append(u'DWG NO. {}'.format(dwg))
    parts.append(name)
    parts.append(u'{} 朵雲'.format(count))
    return u'　｜　'.join(parts)


def _search_text(record):
    return u'{} {} {}'.format(
        _safe_text(record.get('SheetNumber')),
        _safe_text(record.get('DwgNumber')),
        _safe_text(record.get('SheetName'))).lower()


def _unique_clouds(records):
    """Deduplicate a cloud visible on more than one placed sheet."""
    clouds = []
    seen = set()
    for record in records:
        for cloud_id in record.get('clouds') or []:
            key = _id_value(cloud_id)
            if key <= 0:
                key = id(cloud_id)
            if key in seen:
                continue
            seen.add(key)
            clouds.append(cloud_id)
    return clouds


class ClearRevisionCloudsWindow(forms.WPFWindow):
    """Checkbox UI; controls are cached so filtering never loses a tick."""

    def __init__(self, records, document_title, unmapped_cloud_count):
        xaml = os.path.join(os.path.dirname(__file__),
                            'ClearRevisionClouds.xaml')
        forms.WPFWindow.__init__(self, xaml)
        self.records = list(records)
        self.result = None
        self.boxes = {}
        self._ready = False
        self._bulk = False

        self.documentText.Text = u'目前文件：{}'.format(
            document_title or u'(未命名文件)')
        if unmapped_cloud_count:
            self.scopeHintText.Text = (
                u'只處理圖紙上的雲狀線；目前另有 {} 朵修訂雲位於未上圖紙視圖，'
                u'本次不會刪除。').format(unmapped_cloud_count)
        else:
            self.scopeHintText.Text = (
                u'目前共 {} 張圖紙。清除範圍會依雲形所屬圖紙判定，'
                u'不會刪除未放在圖紙上的修訂雲。').format(len(self.records))

        self.searchText.TextChanged += self.filter_changed
        self._ready = True
        self._refresh()

    def _shown_records(self):
        query = _safe_text(self.searchText.Text).lower()
        if not query:
            return self.records
        return [record for record in self.records
                if query in _search_text(record)]

    def _box_for(self, record):
        record_id = record['id']
        box = self.boxes.get(record_id)
        if box is not None:
            return box
        box = CheckBox()
        box.Content = _sheet_label(record)
        box.Margin = Thickness(4, 3, 4, 3)
        box.Tag = record_id
        box.Checked += self._selection_changed
        box.Unchecked += self._selection_changed
        self.boxes[record_id] = box
        return box

    def _refresh(self):
        if not self._ready:
            return
        self.sheetList.Children.Clear()
        shown = self._shown_records()
        for record in shown:
            self.sheetList.Children.Add(self._box_for(record))
        self.listHintText.Text = (
            u'顯示 {} / {} 張圖紙；勾選後會清除這些圖紙上的全部修訂雲。'
        ).format(len(shown), len(self.records))
        self._update_status()

    def _selected_ids(self):
        selected = []
        for record in self.records:
            box = self.boxes.get(record['id'])
            if box is not None and bool(box.IsChecked):
                selected.append(record['id'])
        return selected

    def _selected_records(self):
        selected = set(self._selected_ids())
        return [record for record in self.records if record['id'] in selected]

    def _update_status(self):
        if not self._ready:
            return
        selected_records = self._selected_records()
        clouds = _unique_clouds(selected_records)
        self.statusText.Text = (
            u'已選 {} 張圖紙，實際將刪除 {} 朵修訂雲（去除重複顯示）。'
        ).format(len(selected_records), len(clouds))
        self.deleteButton.IsEnabled = bool(clouds)

    def _selection_changed(self, sender, args):
        if not self._bulk:
            self._update_status()

    def filter_changed(self, sender, args):
        self._refresh()

    def select_all_clicked(self, sender, args):
        self._bulk = True
        try:
            for record in self.records:
                self._box_for(record).IsChecked = True
        finally:
            self._bulk = False
        self._update_status()

    def clear_selection_clicked(self, sender, args):
        self._bulk = True
        try:
            for box in self.boxes.values():
                box.IsChecked = False
        finally:
            self._bulk = False
        self._update_status()

    def cancel_clicked(self, sender, args):
        self.result = None
        self.Close()

    def delete_clicked(self, sender, args):
        selected_ids = self._selected_ids()
        if not selected_ids:
            forms.alert(u'請先勾選至少一張圖紙。', title=TITLE)
            return
        if not _unique_clouds(self._selected_records()):
            forms.alert(u'選取的圖紙目前沒有可清除的修訂雲。', title=TITLE)
            return
        self.result = selected_ids
        self.Close()


def _delete_clouds(doc, clouds):
    """Delete the batch in one transaction; return ``(count, error)``."""
    transaction = DB.Transaction(doc, TITLE)
    try:
        transaction.Start()
        cloud_ids = List[DB.ElementId]()
        cloud_id_values = set()
        for cloud_id in clouds:
            try:
                cloud_id_value = _id_value(cloud_id)
                if cloud_id_value <= 0:
                    continue
                cloud_ids.Add(cloud_id)
                cloud_id_values.add(cloud_id_value)
            except Exception:
                raise
        if cloud_ids.Count == 0:
            transaction.Commit()
            return 0, u''

        # Revit resolves dependent elements more efficiently when the whole
        # set is submitted once. It also keeps the operation one atomic Undo.
        deleted_ids = doc.Delete(cloud_ids) or []
        deleted_id_values = set(_id_value(element_id)
                                for element_id in deleted_ids)
        deleted = len(cloud_id_values.intersection(deleted_id_values))
        transaction.Commit()
        return deleted, u''
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

    records, unmapped = _sheet_cloud_records(doc)
    if not records:
        forms.alert(u'這個專案沒有可用的圖紙。', title=TITLE)
        return
    if not any(record.get('cloud_count') for record in records):
        if unmapped:
            forms.alert(
                u'圖紙上沒有修訂雲。另有 {} 朵雲位於未上圖紙視圖，'
                u'本工具不會處理它們。'.format(unmapped), title=TITLE)
        else:
            forms.alert(u'圖紙上目前沒有修訂雲。', title=TITLE)
        return

    try:
        document_title = doc.Title
    except Exception:
        document_title = u''

    window = ClearRevisionCloudsWindow(records, document_title, unmapped)
    window.ShowDialog()
    if not window.result:
        return

    selected_ids = set(window.result)
    selected = [record for record in records if record['id'] in selected_ids]
    clouds = _unique_clouds(selected)
    if not clouds:
        forms.alert(u'選取的圖紙沒有可清除的修訂雲，模型未變更。',
                    title=TITLE)
        return

    selected_numbers = [_safe_text(record.get('SheetNumber'))
                        for record in selected]
    shown_numbers = u'、'.join(number for number in selected_numbers if number)
    if len(shown_numbers) > 180:
        shown_numbers = shown_numbers[:180] + u'…'
    preview = (
        u'【刪除前確認】\n\n'
        u'圖紙：{}\n'
        u'預計刪除：{} 朵修訂雲\n\n'
        u'這會包含手動建立的雲狀線。確定要清除嗎？'
    ).format(shown_numbers or u'(未命名圖紙)', len(clouds))
    if not forms.alert(preview, title=TITLE, yes=True, no=True):
        return

    deleted, error = _delete_clouds(doc, clouds)
    if error:
        forms.alert(u'清除失敗，交易已回復，模型未變更。\n\n{}'.format(error),
                    title=TITLE)
        return
    forms.alert(u'已清除 {} 朵修訂雲。\n\nRevit Undo 可復原本次動作。'.format(
        deleted), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
