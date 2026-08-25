# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""更改剖刀＆立面標記（多張）— JAC 07.04.

A 剖刀's graphics live on the section's **type**: the head symbol, the tail,
the line weight all hang off the ``ViewFamilyType``. Same for an elevation
marker, whose symbol is its ``ElementType``. Changing one is a single dropdown
in Type Properties, and Revit offers no way at all to do it to forty sections
at once — so a drawing set that has drifted onto three different section types
gets straightened out by hand, one property palette at a time.

The work itself is ``Element.ChangeTypeId``. What this adds is the part that
keeps it from failing halfway:

* The target list is the **intersection** of ``GetValidTypes()`` across every
  selected element. Offering the union means discovering on element 27 of 40
  that a detail section will not take a building-section type — a rolled-back
  transaction, and no clue which ones were the problem.
* Elements already on the target type are separated out rather than counted, so
  「已更改 40 個」 never covers 12 that were already right.

Selection is grouped by current type, because 「把目前是 A 的那些改成 B」 is
what the request actually is nearly every time.

dry-run preview first; the change is one Transaction, all or nothing.
"""

__title__ = u'更改剖刀\n立面標記'
__author__ = 'RevitMCP'

from Autodesk.Revit import DB
from pyrevit import forms, revit, script

import mcp_window as ui
import mcp_window_logic as uilogic
import view_type_swap_logic as logic


TITLE = u'更改剖刀＆立面標記'

KIND_CHOICES = (
    (logic.KIND_LABELS[logic.KIND_SECTION], logic.KIND_SECTION),
    (logic.KIND_LABELS[logic.KIND_ELEV_MARKER], logic.KIND_ELEV_MARKER),
    (logic.KIND_LABELS[logic.KIND_ELEV_VIEW], logic.KIND_ELEV_VIEW),
)


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
    if element is None:
        return u''
    try:
        return DB.Element.Name.GetValue(element) or u''
    except Exception:
        try:
            return element.Name or u''
        except Exception:
            return u''


def _built_in_parameter(element, name):
    built_in = getattr(DB.BuiltInParameter, name, None)
    if built_in is None:
        return None
    try:
        return element.get_Parameter(built_in)
    except Exception:
        return None


def _parameter_text(element, name):
    parameter = _built_in_parameter(element, name)
    if parameter is None:
        return u''
    try:
        return (parameter.AsString() or u'').strip()
    except Exception:
        return u''


def _valid_type_ids(element):
    try:
        return [_id_value(type_id) for type_id in element.GetValidTypes()]
    except Exception:
        return []


def _type_name(doc, type_id):
    if type_id is None or type_id <= 0:
        return u''
    try:
        return _element_name(doc.GetElement(DB.ElementId(int(type_id))))
    except Exception:
        return u''


def _views(doc, view_type_name):
    """Non-template views of one ``ViewType``.

    Collected as ``ViewSection`` rather than ``View``: both 剖面圖 and 立面圖
    are ViewSection instances separated only by ``ViewType``, and ViewSection
    is concrete — ``OfClass`` on an abstract base is the kind of call that
    works until the one Revit build where it raises.
    """
    wanted = getattr(DB.ViewType, view_type_name, None)
    if wanted is None:
        return []
    found = []
    try:
        views = list(DB.FilteredElementCollector(doc)
                     .OfClass(DB.ViewSection)
                     .WhereElementIsNotElementType()
                     .ToElements())
    except Exception:
        return []
    for view in views:
        try:
            if view.IsTemplate:
                continue
            if view.ViewType != wanted:
                continue
        except Exception:
            continue
        found.append(view)
    return found


def _elevation_markers(doc):
    category = getattr(DB.BuiltInCategory, 'OST_ElevationMarks', None)
    if category is None:
        return []
    try:
        return list(DB.FilteredElementCollector(doc)
                    .OfCategory(category)
                    .WhereElementIsNotElementType()
                    .ToElements())
    except Exception:
        return []


def _view_records(doc, views):
    records = []
    for view in views:
        type_id = _id_value(view.GetTypeId())
        detail = _parameter_text(view, 'VIEWER_DETAIL_NUMBER')
        sheet = _parameter_text(view, 'VIEWER_SHEET_NUMBER')
        name = _element_name(view)
        pieces = [piece for piece in (sheet, detail, name) if piece]
        records.append({
            'id': _id_value(view.Id),
            'element_id': view.Id,
            'label': u' '.join(pieces) or name,
            'sort_label': u'{}{}'.format(sheet, detail),
            'name': name,
            'sheet': sheet,
            'detail': detail,
            'type_id': type_id,
            'type_name': _type_name(doc, type_id),
            'valid_type_ids': _valid_type_ids(view),
        })
    return records


def _marker_records(doc, markers):
    records = []
    for marker in markers:
        type_id = _id_value(marker.GetTypeId())
        # A marker has no name of its own; the elevation views hanging off it
        # are how a person recognises which one it is.
        names = []
        try:
            for index in range(int(marker.MaximumViewCount)):
                view_id = marker.GetViewId(index)
                if _id_value(view_id) <= 0:
                    continue
                view = doc.GetElement(view_id)
                if view is not None:
                    names.append(_element_name(view))
        except Exception:
            pass
        label = u'、'.join(names) if names else u'(未建立立面視圖)'
        records.append({
            'id': _id_value(marker.Id),
            'element_id': marker.Id,
            'label': u'{}　[{}]'.format(label, _id_value(marker.Id)),
            'sort_label': label,
            'name': label,
            'sheet': u'',
            'detail': u'',
            'type_id': type_id,
            'type_name': _type_name(doc, type_id),
            'valid_type_ids': _valid_type_ids(marker),
        })
    return records


def _collect(doc, kind):
    if kind == logic.KIND_SECTION:
        return _view_records(doc, _views(doc, 'Section'))
    if kind == logic.KIND_ELEV_VIEW:
        return _view_records(doc, _views(doc, 'Elevation'))
    return _marker_records(doc, _elevation_markers(doc))


def _record_options(records):
    """依目前類型分組的選項，同一群內再依標籤排序。"""
    options = []
    for group in logic.group_by_current_type(records):
        for record in sorted(group['records'],
                             key=lambda item: item.get('sort_label') or u''):
            options.append((u'[{}]　{}'.format(group['type_name'],
                                              record['label']), record))
    return options


def _build_pick_spec(by_kind):
    """第一個視窗：要改哪一種、改哪幾個。

    三種對象的清單都先備好，用 enabled_when 跟著種類切換——選項無法隨另一個
    欄位重建，所以三份都放進去再依種類啟用，比開三次對話框好。
    """
    fields = [
        uilogic.section(u'對象'),
        uilogic.choice('kind', u'要更改哪一種對象的類型', KIND_CHOICES,
                       default=logic.KIND_SECTION),
    ]
    for label, kind in KIND_CHOICES:
        fields.append(uilogic.multichoice(
            'items_' + kind, u'{}（可複選）'.format(label),
            _record_options(by_kind.get(kind) or []), required=True,
            enabled_when=('kind', kind)))
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'批次更換剖面標籤、立面標記或立面視圖的類型',
        badge=uilogic.BADGE_WRITE,
        run_label=u'下一步：選目標類型',
        footnote=u'下一步會只列出所選項目**共通可用**的類型。',
        width=980, height=760)


def _build_target_spec(options, count):
    """第二個視窗：改成哪一個類型。

    這一步真的相依於上一步——可用的類型是所選項目的**交集**，選項在按下第一個
    視窗的執行鈕之前不存在。兩個視窗仍然比原本的三次對話框少一次。
    """
    fields = [
        uilogic.note(u'已選 {} 個項目。以下只列出這些項目共通可用的類型。'
                     .format(count), tone='info'),
        uilogic.choice('target', u'要改成哪一個類型', options),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'選擇目標類型',
        badge=uilogic.BADGE_WRITE,
        run_label=u'預覽',
        footnote=u'寫入前一定會先預覽並由你確認；失敗時整批回復。',
        width=760, height=460)


def _print_plan(plan, kind):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    output.print_md(u'對象：**{}**　目標類型：**{}**'.format(
        logic.kind_label(kind), plan['target_type_name'] or logic.NO_TYPE))

    if plan['change']:
        output.print_md(u'### 將更改（{} 個）'.format(plan['count']))
        output.print_table(
            table_data=[[output.linkify(record['element_id']),
                         record.get('sheet') or u'',
                         record.get('detail') or u'',
                         record.get('name') or u'',
                         record.get('type_name') or logic.NO_TYPE,
                         plan['target_type_name'] or logic.NO_TYPE]
                        for record in plan['change']],
            columns=[u'Element ID', u'圖紙', u'圖號', u'名稱',
                     u'目前類型', u'改為'])

    if plan['blocked']:
        output.print_md(u'### 略過')
        output.print_table(
            table_data=[[output.linkify(entry['record']['element_id']),
                         entry['record'].get('name') or u'',
                         entry['record'].get('type_name') or logic.NO_TYPE,
                         entry['reason']]
                        for entry in plan['blocked']],
            columns=[u'Element ID', u'名稱', u'目前類型', u'原因'])


def _apply(doc, plan):
    """Single Transaction, all or nothing. Returns ``(count, error)``."""
    transaction = DB.Transaction(doc, TITLE)
    try:
        transaction.Start()
        target = DB.ElementId(int(plan['target_type_id']))
        done = 0
        for record in plan['change']:
            element = doc.GetElement(record['element_id'])
            if element is None:
                raise Exception(u'{} 已不存在。'.format(record['label']))
            element.ChangeTypeId(target)
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
        forms.alert(u'請先開啟 Revit 專案文件，再執行更改。',
                    title=TITLE, exitscript=True)

    by_kind = {}
    for unused_label, kind in KIND_CHOICES:
        by_kind[kind] = _collect(doc, kind) or []
    if not any(by_kind.values()):
        forms.alert(u'這個專案沒有剖面標籤、立面標記或立面視圖。', title=TITLE)
        return

    values = ui.ask(_build_pick_spec(by_kind))
    if values is None:
        return
    kind = values['kind']
    chosen = values.get('items_' + kind) or []
    if not chosen:
        forms.alert(u'沒有選擇任何{}。'.format(logic.kind_label(kind)),
                    title=TITLE)
        return

    valid_ids = logic.valid_type_intersection(chosen)
    if not valid_ids:
        forms.alert(
            u'選取的 {} 個項目沒有共通可用的類型，無法一次改完。\n\n'
            u'請縮小選取範圍（例如只選目前同一種類型的那些）再試一次。'
            .format(len(chosen)), title=TITLE)
        return

    options = [(_type_name(doc, type_id) or u'(未命名類型)', type_id)
               for type_id in valid_ids]
    target = ui.ask(_build_target_spec(options, len(chosen)))
    if target is None:
        return
    target_type_id = target['target']
    target_name = _type_name(doc, target_type_id)

    plan = logic.build_plan(chosen, target_type_id, target_name)
    _print_plan(plan, kind)
    summary = logic.plan_lines(plan)

    if not logic.has_work(plan):
        forms.alert(u'【預覽】沒有需要更改的項目，模型未變更。\n\n{}\n\n'
                    u'明細已列在 pyRevit 輸出視窗。'.format(summary),
                    title=TITLE)
        return

    if not forms.alert(
            u'【dry-run 預覽】模型目前未變更。\n\n{}\n\n確定要更改嗎？'
            .format(summary), title=TITLE, yes=True, no=True):
        return

    done, error = _apply(doc, plan)
    if error:
        forms.alert(u'更改失敗，交易已完整回復，類型都沒有動。\n\n{}'
                    .format(error), title=TITLE)
        return
    forms.alert(u'已將 {} 個{}改成「{}」。'.format(
        done, logic.kind_label(kind), target_name or logic.NO_TYPE),
        title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
