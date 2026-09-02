# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""在既有修訂雲上放置修訂雲狀標籤。

這是 PDF 差異按鈕之外的獨立工具：它不讀 PDF、不呼叫 MCP，也不建立雲形。
使用者可以先在模型確認雲形，再選擇標籤類型與一張或多張圖紙執行。

PDF 差異工具建立的是直接屬於 ViewSheet 的修訂雲；這支工具只對這種紙面雲
放置標籤，避免把視圖座標誤當成圖紙座標。已經有任何修訂雲標籤的雲會跳過，
所以重複執行不會為同一朵雲再加第二個標籤。

## 大型專案的三個成本上限（2026-09-02）

這顆按鈕原本在幾千張圖紙的案子按下去要等好幾分鐘、然後把 Revit 帶走。
成因不是放標籤那一段，是「開視窗之前」的三個全案子掃描。改法都是把範圍
先縮到真正相關的元素，請不要退回去：

1. **先找雲、再找圖紙。** 只有真的有雲的圖紙需要昂貴的 DWG NO. 欄位掃描，
   而那通常是幾十張，不是全部幾千張。空白列在 UI 上也只是雜訊。
2. **只掃修訂雲標籤，不掃全部 IndependentTag。** 舊寫法走訪整份文件的
   ``IndependentTag``——大案子裡是幾萬個門窗牆標籤，全部只為了找出其中
   極少數的修訂雲標籤。``OST_RevisionCloudTags`` 讓 Revit 自己過濾。
3. **``_id_value`` 的存取器只解析一次。** ``ElementId.Value`` 是 Revit 2024
   起才有的，舊寫法在 2020–2023 上每呼叫一次就丟一次 AttributeError。

WPF 事件處理常式一律包 :func:`_guard`。裡面丟出去的例外會被 WPF 的
dispatcher 當成未處理例外，直接終止 Revit 行程（「發生嚴重錯誤」），
訊息還看不到——包起來至少會變成一個看得懂、查得到的對話框。
"""

__title__ = u'放置\n修訂雲標籤'
__author__ = 'RevitMCP'

import os
import traceback

from Autodesk.Revit import DB
from pyrevit import forms, revit
from System.Windows import Thickness
from System.Windows.Controls import CheckBox

import pdf_diff_sources as sources


TITLE = u'放置修訂雲標籤'
MM_TO_FT = 1.0 / 304.8
EDGE_PADDING_FT = 12.0 * MM_TO_FT
CLOUD_GAP_FT = 6.0 * MM_TO_FT


def _guard(method):
    """讓 WPF 事件處理常式裡的例外變成對話框，而不是終止 Revit。

    WPF 不會替我們攔 dispatcher 上的未處理例外，Revit 也只會顯示「發生嚴重
    錯誤，應用程式將終止」然後關掉——使用者拿不到任何可回報的訊息。
    """
    def handler(self, sender, args):
        try:
            return method(self, sender, args)
        except Exception as error:
            forms.alert(
                u'操作失敗（已攔下，Revit 不會被關閉）：\n\n{}\n\n{}'.format(
                    error, traceback.format_exc()), title=TITLE)
    handler.__name__ = getattr(method, '__name__', 'handler')
    handler.__doc__ = method.__doc__
    return handler


# 這個 harness 上的 ElementId 用哪個屬性取整數值；解析一次就記住。
_ID_ACCESSOR = None


def _read_id(element_id, accessor):
    if accessor == 'IntegerValue':
        return int(element_id.IntegerValue)
    return int(element_id.Value)


def _id_value(element_id):
    """Read ElementId on R20 and newer Revit versions.

    ``IntegerValue`` 在 2020–2026 都還在（2024 起標為 deprecated），
    ``Value`` 則是 2024 才加的，所以先試前者。存取器快取起來，避免在
    幾萬個元素的迴圈裡每圈丟一次 AttributeError。
    """
    if element_id is None:
        return -1

    global _ID_ACCESSOR
    if _ID_ACCESSOR is not None:
        try:
            return _read_id(element_id, _ID_ACCESSOR)
        except Exception:
            _ID_ACCESSOR = None

    for accessor in ('IntegerValue', 'Value'):
        try:
            value = _read_id(element_id, accessor)
        except Exception:
            continue
        _ID_ACCESSOR = accessor
        return value
    return -1


def _safe_sheet_id(record):
    try:
        return int(record.get('ElementId'))
    except Exception:
        return -1


def _safe_text(value):
    return u'{}'.format(value or u'').strip()


def _sheet_cloud_records(doc):
    """Return direct-on-sheet clouds grouped by sheet.

    The PDF workflow creates clouds whose OwnerViewId is the ViewSheet. A
    RevisionCloud owned by a plan/section view has a different coordinate
    system, so it is deliberately reported as out of scope instead of being
    tagged at a misleading location.

    順序很重要：**先掃雲、再取圖紙資料**。``sources.sheet_records`` 要為
    每張圖紙讀 DWG NO. 欄位，那是這支工具最貴的操作；只有真的有雲的圖紙
    需要它。幾千張圖紙的案子通常只有幾十張帶雲，差距是兩個數量級。
    回傳的 records 也因此只含有雲的圖紙——沒有雲的圖紙在這個 UI 上不能做
    任何事，列出來只是讓使用者多捲幾千列。
    """
    clouds_by_owner = sources.revision_clouds_by_owner(doc)
    if not clouds_by_owner:
        return [], 0

    sheet_ids = sources.all_sheet_ids(doc)
    clouds_by_sheet = {}
    unmapped = 0
    for owner_id, clouds in clouds_by_owner.items():
        if owner_id in sheet_ids:
            clouds_by_sheet[owner_id] = list(clouds)
        else:
            unmapped += len(clouds)

    if not clouds_by_sheet:
        return [], unmapped

    rows = sources.sheet_records(doc, sheet_ids=clouds_by_sheet.keys())

    records = []
    for row in rows:
        sheet_id = _safe_sheet_id(row)
        clouds = clouds_by_sheet.get(sheet_id)
        if not clouds:
            continue
        record = dict(row)
        record['id'] = sheet_id
        record['clouds'] = clouds
        record['cloud_count'] = len(clouds)
        record['tagged_cloud_ids'] = set()
        records.append(record)

    records.sort(key=lambda item: _safe_text(item.get('SheetNumber')).lower())
    return records, unmapped


def _tagged_cloud_id(tag):
    """Return the local RevisionCloud id referenced by an IndependentTag.

    ``TaggedElementId``/``TaggedLocalElementId`` are available in Revit 2020;
    the first branch also handles the LinkElementId shape used by newer APIs.
    """
    try:
        tagged_element_id = tag.TaggedElementId
        host_id = tagged_element_id.HostElementId
        value = _id_value(host_id)
        if value > 0:
            return value
    except Exception:
        pass

    try:
        value = _id_value(tag.TaggedLocalElementId)
        if value > 0:
            return value
    except Exception:
        pass
    return -1


def _tagged_cloud_ids_by_sheet(doc, sheet_ids):
    """Scan tags once and return ``{sheet_id: {cloud_id, ...}}``.

    只掃 ``OST_RevisionCloudTags``。舊寫法用 ``OfClass(IndependentTag)``
    走訪整份文件的標籤——大案子裡那是幾萬個門窗、房間、牆標籤，而我們只
    想知道其中極少數的修訂雲標籤指向哪朵雲。讓 Revit 先用類別過濾，迴圈
    的規模就從「全專案標籤數」降到「修訂雲標籤數」。
    """
    wanted = set(sheet_ids)
    result = dict((sheet_id, set()) for sheet_id in wanted)
    if not wanted:
        return result

    try:
        tags = DB.FilteredElementCollector(doc) \
            .OfCategory(DB.BuiltInCategory.OST_RevisionCloudTags) \
            .WhereElementIsNotElementType() \
            .ToElements()
    except Exception:
        return result

    for tag in tags:
        try:
            owner_id = _id_value(tag.OwnerViewId)
        except Exception:
            continue
        if owner_id not in wanted:
            continue
        cloud_id = _tagged_cloud_id(tag)
        if cloud_id > 0:
            result[owner_id].add(cloud_id)
    return result


def _refresh_record_tagged_cloud_ids(doc, records):
    """Refresh tags and keep only ids that are clouds in each record."""
    tagged_by_sheet = _tagged_cloud_ids_by_sheet(
        doc, [record['id'] for record in records])
    for record in records:
        cloud_ids = set(_id_value(getattr(cloud, 'Id', None))
                        for cloud in record.get('clouds') or [])
        record['tagged_cloud_ids'] = tagged_by_sheet.get(record['id'], set()) \
            .intersection(cloud_ids)


def _sheet_label(record):
    number = _safe_text(record.get('SheetNumber')) or u'(無 Revit 圖號)'
    dwg = _safe_text(record.get('DwgNumber'))
    name = _safe_text(record.get('SheetName')) or u'(無圖名)'
    count = int(record.get('cloud_count') or 0)
    tagged = len(record.get('tagged_cloud_ids') or set())
    pending = max(0, count - tagged)
    parts = [number]
    if dwg and dwg != number:
        parts.append(u'DWG NO. {}'.format(dwg))
    parts.append(name)
    parts.append(u'共 {} 朵雲／已有標籤 {}／待放置 {}'.format(
        count, tagged, pending))
    return u'　｜　'.join(parts)


def _search_text(record):
    return u'{} {} {}'.format(
        _safe_text(record.get('SheetNumber')),
        _safe_text(record.get('DwgNumber')),
        _safe_text(record.get('SheetName'))).lower()


def _unique_clouds(records):
    """Deduplicate by ElementId before a batch is sent to the transaction."""
    clouds = []
    seen = set()
    for record in records:
        for cloud in record.get('clouds') or []:
            cloud_id = _id_value(getattr(cloud, 'Id', None))
            key = cloud_id if cloud_id > 0 else id(cloud)
            if key in seen:
                continue
            seen.add(key)
            clouds.append(cloud)
    return clouds


def _eligible_clouds(records):
    """Return untagged direct-sheet clouds and the already-tagged count."""
    clouds = []
    seen = set()
    duplicate_count = 0
    for record in records:
        tagged_ids = record.get('tagged_cloud_ids') or set()
        for cloud in record.get('clouds') or []:
            cloud_id = _id_value(getattr(cloud, 'Id', None))
            key = cloud_id if cloud_id > 0 else id(cloud)
            if key in seen:
                continue
            seen.add(key)
            if cloud_id > 0 and cloud_id in tagged_ids:
                duplicate_count += 1
                continue
            clouds.append(cloud)
    return clouds, duplicate_count


def _cloud_bounds(cloud):
    """Get the paper-space rectangle of a RevisionCloud sketch loop."""
    min_u = None
    min_v = None
    max_u = None
    max_v = None
    try:
        curves = list(cloud.GetSketchCurves())
    except Exception:
        return None

    for curve in curves:
        if curve is None:
            continue
        points = []
        try:
            points = list(curve.Tessellate())
        except Exception:
            pass
        if not points:
            try:
                points = [curve.GetEndPoint(0), curve.GetEndPoint(1)]
            except Exception:
                continue
        for point in points:
            if point is None:
                continue
            x = point.X
            y = point.Y
            min_u = x if min_u is None else min(min_u, x)
            min_v = y if min_v is None else min(min_v, y)
            max_u = x if max_u is None else max(max_u, x)
            max_v = y if max_v is None else max(max_v, y)

    if min_u is None or max_u <= min_u or max_v <= min_v:
        return None
    return min_u, min_v, max_u, max_v


def _clamp(value, low, high):
    if high < low:
        return (low + high) / 2.0
    return max(low, min(high, value))


def _tag_position(record, bounds):
    """Choose a stable paper-space position: right, left, top, then bottom."""
    outline = record.get('Outline')
    if not outline or len(outline) != 4:
        return None
    sheet_min_u, sheet_min_v, sheet_max_u, sheet_max_v = outline
    if sheet_max_u <= sheet_min_u or sheet_max_v <= sheet_min_v:
        return None

    min_u, min_v, max_u, max_v = bounds
    center_u = (min_u + max_u) / 2.0
    center_v = (min_v + max_v) / 2.0
    candidates = (
        (max_u + CLOUD_GAP_FT, center_v),
        (min_u - CLOUD_GAP_FT, center_v),
        (center_u, max_v + CLOUD_GAP_FT),
        (center_u, min_v - CLOUD_GAP_FT),
    )
    safe_min_u = sheet_min_u + EDGE_PADDING_FT
    safe_max_u = sheet_max_u - EDGE_PADDING_FT
    safe_min_v = sheet_min_v + EDGE_PADDING_FT
    safe_max_v = sheet_max_v - EDGE_PADDING_FT

    for x, y in candidates:
        if (x >= safe_min_u and x <= safe_max_u and
                y >= safe_min_v and y <= safe_max_v):
            return DB.XYZ(x, y, 0)

    # If the cloud nearly fills the sheet, keep the head inside the safe area
    # rather than rotating it or producing an invalid paper-space point.
    return DB.XYZ(
        _clamp(center_u, safe_min_u, safe_max_u),
        _clamp(center_v, safe_min_v, safe_max_v), 0)


def _valid_revision_tag_type(doc, element_id):
    try:
        tag_type = doc.GetElement(DB.ElementId(int(element_id)))
    except Exception:
        tag_type = None
    if tag_type is None:
        return None
    try:
        if not isinstance(tag_type, DB.FamilySymbol):
            return None
        category = tag_type.Category
        expected = _id_value(DB.ElementId(DB.BuiltInCategory.OST_RevisionCloudTags))
        if category is None or _id_value(category.Id) != expected:
            return None
    except Exception:
        return None
    return tag_type


def _place_tags(doc, records, tag_type_id):
    """Place one tag per eligible cloud in a single reversible transaction."""
    _refresh_record_tagged_cloud_ids(doc, records)

    tag_type = _valid_revision_tag_type(doc, tag_type_id)
    if tag_type is None:
        return 0, 0, [u'找不到有效的修訂雲狀標籤類型。']

    transaction = DB.Transaction(doc, TITLE)
    created = 0
    duplicate_count = 0
    skipped = []
    try:
        transaction.Start()
        if not tag_type.IsActive:
            tag_type.Activate()
            doc.Regenerate()

        for record in records:
            sheet = doc.GetElement(DB.ElementId(record['id']))
            tagged_ids = record.get('tagged_cloud_ids') or set()
            for cloud in record.get('clouds') or []:
                cloud_id = _id_value(getattr(cloud, 'Id', None))
                if cloud_id > 0 and cloud_id in tagged_ids:
                    duplicate_count += 1
                    continue
                try:
                    bounds = _cloud_bounds(cloud)
                    if bounds is None:
                        raise Exception(u'無法讀取雲形範圍')
                    position = _tag_position(record, bounds)
                    if position is None:
                        raise Exception(u'圖紙 Outline 無效，無法定位標籤')
                    DB.IndependentTag.Create(
                        doc, tag_type.Id, sheet.Id, DB.Reference(cloud),
                        False, DB.TagOrientation.Horizontal, position)
                    created += 1
                    if cloud_id > 0:
                        tagged_ids.add(cloud_id)
                except Exception as error:
                    label = record.get('SheetNumber') or record.get('DwgNumber')
                    skipped.append(u'{} / 雲 {}：{}'.format(
                        label or u'?', cloud_id if cloud_id > 0 else u'?', error))

        transaction.Commit()
        return created, duplicate_count, skipped
    except Exception as error:
        try:
            if transaction.HasStarted():
                transaction.RollBack()
        except Exception:
            pass
        return 0, 0, [u'交易失敗，已回復：{}'.format(error)]


class PlaceRevisionCloudTagsWindow(forms.WPFWindow):
    """Checkbox UI; controls are cached so filtering never loses a tick."""

    def __init__(self, records, revision_tags, document_title,
                 unmapped_cloud_count):
        xaml = os.path.join(os.path.dirname(__file__),
                            'PlaceRevisionCloudTags.xaml')
        forms.WPFWindow.__init__(self, xaml)
        self.records = list(records)
        self.revision_tags = list(revision_tags)
        self.result = None
        self.boxes = {}
        self._ready = False
        self._bulk = False

        self.documentText.Text = u'目前文件：{}'.format(
            document_title or u'(未命名文件)')
        direct_count = sum(int(record.get('cloud_count') or 0)
                           for record in self.records)
        if unmapped_cloud_count:
            self.scopeHintText.Text = (
                u'{} 張圖紙上可處理 {} 朵雲；另有 {} 朵雲位於視圖或未上圖紙，'
                u'為避免座標偏移，本次不處理。').format(
                    len(self.records), direct_count, unmapped_cloud_count)
        else:
            self.scopeHintText.Text = (
                u'{} 張圖紙上共有 {} 朵可處理的修訂雲；已有標籤的雲會自動跳過。'
            ).format(len(self.records), direct_count)

        for revision_tag in self.revision_tags:
            self.revisionTagCombo.Items.Add(
                sources.revision_tag_label(revision_tag))
        self.revisionTagCombo.SelectedIndex = 0 if self.revision_tags else -1

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
            u'顯示 {} / {} 張有修訂雲的圖紙；請勾選要處理的，'
            u'可複選或按「全選圖紙」。'
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
        clouds, duplicate_count = _eligible_clouds(selected_records)
        self.statusText.Text = (
            u'已選 {} 張圖紙；可放置 {} 個標籤，已有標籤 {} 個會跳過。'
        ).format(len(selected_records), len(clouds), duplicate_count)
        self.placeButton.IsEnabled = bool(
            self.revision_tags and clouds and
            self.revisionTagCombo.SelectedIndex >= 0)

    @_guard
    def _selection_changed(self, sender, args):
        if not self._bulk:
            self._update_status()

    @_guard
    def filter_changed(self, sender, args):
        self._refresh()

    @_guard
    def select_all_clicked(self, sender, args):
        self._bulk = True
        try:
            for record in self.records:
                self._box_for(record).IsChecked = True
        finally:
            self._bulk = False
        self._update_status()

    @_guard
    def clear_selection_clicked(self, sender, args):
        self._bulk = True
        try:
            for box in self.boxes.values():
                box.IsChecked = False
        finally:
            self._bulk = False
        self._update_status()

    @_guard
    def cancel_clicked(self, sender, args):
        self.result = None
        self.Close()

    @_guard
    def place_clicked(self, sender, args):
        selected_records = self._selected_records()
        clouds, unused = _eligible_clouds(selected_records)
        if self.revisionTagCombo.SelectedIndex < 0:
            forms.alert(u'請先選擇修訂雲狀標籤類型。', title=TITLE)
            return
        if not selected_records:
            forms.alert(u'請先勾選至少一張圖紙。', title=TITLE)
            return
        if not clouds:
            forms.alert(u'選取的圖紙沒有需要新增標籤的修訂雲。', title=TITLE)
            return
        tag = self.revision_tags[self.revisionTagCombo.SelectedIndex]
        self.result = {
            'sheet_ids': [record['id'] for record in selected_records],
            'tag_type_id': tag.get('ElementId'),
        }
        self.Close()


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行放置標籤。',
                    title=TITLE, exitscript=True)

    # 掃描在大案子裡仍然要幾秒；沒有進度視窗使用者只會看到 Revit 沒反應，
    # 然後開始亂點——而亂點正是把「慢」變成「當掉」的那一步。
    with forms.ProgressBar(title=u'掃描修訂雲與圖紙中…', indeterminate=True):
        records, unmapped = _sheet_cloud_records(doc)
        revision_tags = sources.revision_tag_records(doc)
        if records:
            _refresh_record_tagged_cloud_ids(doc, records)

    if not records:
        if unmapped:
            forms.alert(
                u'圖紙上目前沒有可處理的修訂雲。另有 {} 朵雲位於視圖或未上圖紙，'
                u'為避免座標偏移，本工具不處理它們。'.format(unmapped),
                title=TITLE)
        else:
            forms.alert(u'圖紙上目前沒有修訂雲。', title=TITLE)
        return

    if not revision_tags:
        forms.alert(
            u'專案中沒有已載入的修訂雲狀標籤類型（OST_RevisionCloudTags）。\n\n'
            u'請先載入修訂雲狀標籤族群，再重新執行本按鈕。', title=TITLE)
        return

    try:
        document_title = doc.Title
    except Exception:
        document_title = u''

    window = PlaceRevisionCloudTagsWindow(
        records, revision_tags, document_title, unmapped)
    window.ShowDialog()
    if not window.result:
        return

    selected = [record for record in records if record['id'] in
                set(window.result['sheet_ids'])]
    clouds, duplicate_count = _eligible_clouds(selected)
    if not clouds:
        forms.alert(u'選取的圖紙沒有需要新增標籤的修訂雲，模型未變更。',
                    title=TITLE)
        return

    selected_numbers = [_safe_text(record.get('SheetNumber'))
                        for record in selected]
    shown_numbers = u'、'.join(number for number in selected_numbers if number)
    if len(shown_numbers) > 180:
        shown_numbers = shown_numbers[:180] + u'…'
    tag_row = next((row for row in revision_tags
                    if row.get('ElementId') == window.result['tag_type_id']),
                   None)
    tag_label = sources.revision_tag_label(tag_row) if tag_row else u'(未知類型)'
    preview = (
        u'【放置前確認】\n\n'
        u'圖紙：{}\n'
        u'標籤類型：{}\n'
        u'預計新增：{} 個\n'
        u'已有標籤跳過：{} 個\n\n'
        u'確定要放置嗎？'
    ).format(shown_numbers or u'(未命名圖紙)', tag_label,
             len(clouds), duplicate_count)
    if not forms.alert(preview, title=TITLE, yes=True, no=True):
        return

    with forms.ProgressBar(title=u'放置修訂雲標籤中…', indeterminate=True):
        created, duplicates, skipped = _place_tags(
            doc, selected, window.result['tag_type_id'])

    lines = [u'新增修訂雲標籤：{} 個'.format(created),
             u'已有標籤跳過：{} 個'.format(duplicates)]
    if skipped:
        lines.append(u'無法放置：{} 個'.format(len(skipped)))
        lines.extend(skipped[:8])
        if len(skipped) > 8:
            lines.append(u'其餘 {} 個略過。'.format(len(skipped) - 8))
    lines.append(u'Revit Undo 可復原本次動作。')
    forms.alert(u'\n'.join(lines), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
