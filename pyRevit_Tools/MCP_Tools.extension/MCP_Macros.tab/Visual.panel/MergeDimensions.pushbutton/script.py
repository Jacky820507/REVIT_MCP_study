# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""尺寸線合併（JAC 08.04）.

Revit has no merge command for dimensions. Combining two strings means
rebuilding: take the union of their references, create one dimension along the
shared line, then delete the originals. That is destructive, so the rules for
refusing live in :mod:`dimension_merge_logic` and most of them are about not
losing anything.

The one worth repeating here: **a dimension carrying typed text is never
merged.** An override, prefix, suffix or above/below note is something a person
wrote, and rebuilding discards it while the drawing still looks right.

Contract as with the other writing buttons: dry-run preview, confirm, one
Transaction that rolls back completely if any single step is refused.
"""

__title__ = u'尺寸線\n合併'
__author__ = 'RevitMCP'

from Autodesk.Revit import DB
from pyrevit import forms, revit, script

import dimension_merge_logic as logic
import mcp_window as ui
import mcp_window_logic as uilogic


TITLE = u'尺寸線合併'
MM_PER_FOOT = 304.8

SCOPE_VIEW = 'view'
SCOPE_SELECTION = 'selection'

SCOPES = (
    (u'目前視圖的所有尺寸標註', SCOPE_VIEW),
    (u'目前選取的尺寸標註', SCOPE_SELECTION),
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


def _build_spec():
    fields = [
        uilogic.section(u'範圍'),
        uilogic.choice('scope', u'要合併哪些標註', SCOPES, default=SCOPE_VIEW),

        uilogic.section(u'合併規則'),
        uilogic.number('max_gap', u'最大合併間距',
                       default=logic.DEFAULT_MAX_GAP_MM, minimum=0,
                       unit=u'mm',
                       help=u'同一條線上相隔超過此距離的標註視為兩段，'
                            u'不會合併成一條。'),

        uilogic.note(
            u'合併會建立新的標註並刪除原本那幾條。'
            u'原標註上的覆寫文字若彼此不同，該組會被擋下而不是任選一個——'
            u'挑錯一個等於默默改掉圖面上的數字。', tone='warning'),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'把同一條線上連續的尺寸標註合併成一條多段標註',
        badge=uilogic.BADGE_WRITE,
        run_label=u'預覽',
        footnote=u'寫入前一定會先預覽並由你確認；失敗時整批回復。',
        width=920, height=660)


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value)
    except Exception:
        return u''


def _point_mm(point):
    return (float(point.X) * MM_PER_FOOT,
            float(point.Y) * MM_PER_FOOT,
            float(point.Z) * MM_PER_FOOT)


def _overrides(source):
    """The five text fields that a rebuild would silently discard."""
    return {
        'value_override': _text(getattr(source, 'ValueOverride', None)),
        'prefix': _text(getattr(source, 'Prefix', None)),
        'suffix': _text(getattr(source, 'Suffix', None)),
        'above': _text(getattr(source, 'Above', None)),
        'below': _text(getattr(source, 'Below', None)),
    }


def _owner_view_id(dimension):
    """Which view a dimension belongs to.

    ``Dimension.View`` is the property this API is confirmed to expose;
    ``OwnerViewId`` is the generic Element fallback for anything that does not
    answer it.
    """
    try:
        view = dimension.View
        if view is not None:
            return _id_value(view.Id)
    except Exception:
        pass
    try:
        return _id_value(dimension.OwnerViewId)
    except Exception:
        return -1


def _segments(dimension):
    rows = []
    try:
        segments = dimension.Segments
    except Exception:
        return rows
    if segments is None:
        return rows
    try:
        for segment in segments:
            rows.append(_overrides(segment))
    except Exception:
        pass
    return rows


def _record(doc, dimension):
    try:
        shape = u'{}'.format(dimension.DimensionShape)
    except Exception:
        shape = u''
    try:
        available = bool(dimension.AreReferencesAvailable)
    except Exception:
        available = False
    try:
        locked = bool(dimension.IsLocked)
    except Exception:
        locked = False

    start = end = None
    try:
        curve = dimension.Curve
        if curve is not None:
            start = _point_mm(curve.GetEndPoint(0))
            end = _point_mm(curve.GetEndPoint(1))
    except Exception:
        start = end = None

    references = []
    keys = []
    if available:
        try:
            for reference in dimension.References:
                # The stable representation is the only dependable identity for
                # a Reference; two objects for the same edge are not equal.
                try:
                    key = reference.ConvertToStableRepresentation(doc)
                except Exception:
                    key = None
                if not key:
                    continue
                references.append(reference)
                keys.append(key)
        except Exception:
            references = []
            keys = []

    try:
        dimension_type = dimension.DimensionType
    except Exception:
        dimension_type = None

    record = {
        'id': _id_value(dimension.Id),
        'element_id': dimension.Id,
        'element': dimension,
        # Dimension.View is the property confirmed present on this API; fall
        # back to OwnerViewId only if it is unavailable.
        'view_id': _owner_view_id(dimension),
        'type_id': _id_value(dimension_type.Id) if dimension_type is not None
        else -1,
        'type_name': _element_name(dimension_type),
        'type_element': dimension_type,
        'shape': shape,
        'references_available': available,
        'is_locked': locked,
        'start': start,
        'end': end,
        'references': references,
        'reference_keys': keys,
        'segments': _segments(dimension),
    }
    record.update(_overrides(dimension))
    return record


def _collect(doc, view, scope):
    dimensions = []
    if scope == SCOPE_SELECTION:
        try:
            ids = list(revit.uidoc.Selection.GetElementIds())
        except Exception:
            ids = []
        for element_id in ids:
            element = doc.GetElement(element_id)
            if isinstance(element, DB.Dimension):
                dimensions.append(element)
    else:
        try:
            collector = (DB.FilteredElementCollector(doc, view.Id)
                         .OfClass(DB.Dimension)
                         .WhereElementIsNotElementType())
            dimensions = list(collector)
        except Exception:
            dimensions = []
    return [_record(doc, dimension) for dimension in dimensions]


def _print_plan(plan):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    output.print_md(u'最大合併間距 **{:.0f} mm**；同一視圖、同一標註型式、'
                    u'且在同一條線上的標註才會合併。'.format(
                        plan['max_gap_mm']))
    if plan['runs']:
        rows = []
        for index, run in enumerate(plan['runs'], start=1):
            for record in run['members']:
                rows.append([
                    u'{}'.format(index),
                    output.linkify(record['element_id']),
                    record['type_name'],
                    u'{:.0f}'.format(run['length_mm']),
                    u'{}'.format(run['reference_count']),
                    u'{}'.format(len(run['members'])),
                ])
        output.print_table(
            table_data=rows,
            columns=[u'合併組', u'Element ID', u'標註型式', u'合併後長度(mm)',
                     u'合併後參考數', u'本組標註數'])
    else:
        output.print_md(u'沒有可以合併的標註。')

    rows = [[output.linkify(row['record']['element_id']),
             row['record'].get('type_name', u''), row['reason']]
            for row in plan['blocked'] + plan['singles']]
    if rows:
        output.print_md(u'### 不合併（{} 個）'.format(len(rows)))
        output.print_table(table_data=rows,
                           columns=[u'Element ID', u'標註型式', u'原因'])


class WarningSwallower(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, failures_accessor):
        for failure in failures_accessor.GetFailureMessages():
            if failure.GetSeverity() == DB.FailureSeverity.Warning:
                failures_accessor.DeleteWarning(failure)
        return DB.FailureProcessingResult.Continue


def _apply(doc, view, plan):
    """Create each merged dimension, then delete its sources. All or nothing.

    The new dimension is created first and checked before anything is deleted,
    so a refusal leaves the originals untouched rather than removing them and
    failing to replace them.
    """
    created = 0
    removed = 0
    transaction = DB.Transaction(doc, TITLE)
    transaction.Start()
    options = transaction.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(WarningSwallower())
    transaction.SetFailureHandlingOptions(options)
    try:
        for run in plan['runs']:
            lookup = {}
            for record in run['members']:
                for key, reference in zip(record['reference_keys'],
                                          record['references']):
                    if key not in lookup:
                        lookup[key] = reference
            array = DB.ReferenceArray()
            for key in run['reference_keys']:
                reference = lookup.get(key)
                if reference is not None:
                    array.Append(reference)
            if array.Size < 2:
                raise RuntimeError(u'合併後參考不足 2 個，無法建立標註')

            start = DB.XYZ(run['start'][0] / MM_PER_FOOT,
                           run['start'][1] / MM_PER_FOOT,
                           run['start'][2] / MM_PER_FOOT)
            end = DB.XYZ(run['end'][0] / MM_PER_FOOT,
                         run['end'][1] / MM_PER_FOOT,
                         run['end'][2] / MM_PER_FOOT)
            line = DB.Line.CreateBound(start, end)
            dimension_type = run['members'][0].get('type_element')
            if dimension_type is not None:
                merged = doc.Create.NewDimension(view, line, array,
                                                 dimension_type)
            else:
                merged = doc.Create.NewDimension(view, line, array)
            if merged is None:
                raise RuntimeError(u'建立合併後的標註失敗')
            created += 1

            for record in run['members']:
                doc.Delete(record['element_id'])
                removed += 1
        transaction.Commit()
        return created, removed, None
    except Exception as error:
        transaction.RollBack()
        return 0, 0, u'{}'.format(error)


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行尺寸線合併。',
                    title=TITLE, exitscript=True)
    view = revit.active_view
    if view is None:
        forms.alert(u'讀不到目前的視圖。', title=TITLE)
        return

    values = ui.ask(_build_spec())
    if values is None:
        return
    scope = values['scope']
    max_gap = values['max_gap']

    records = _collect(doc, view, scope)
    if not records:
        forms.alert(
            u'找不到尺寸標註。' if scope == SCOPE_VIEW
            else u'目前的選取裡沒有尺寸標註。', title=TITLE)
        return

    plan = logic.build_runs(records, max_gap_mm=max_gap)
    _print_plan(plan)
    summary = logic.plan_lines(plan)

    if not logic.has_work(plan):
        forms.alert(u'【預覽】沒有可以合併的標註，模型未變更。\n\n{}\n\n'
                    u'明細已列在 pyRevit 輸出視窗。'.format(summary),
                    title=TITLE)
        return

    if not forms.alert(
            u'【dry-run 預覽】模型目前未變更。\n\n{}\n\n'
            u'明細已列在 pyRevit 輸出視窗。\n'
            u'合併會刪除原本的標註並重建，確定要執行嗎？'.format(summary),
            title=TITLE, yes=True, no=True):
        return

    created, removed, error = _apply(doc, view, plan)
    if error:
        forms.alert(
            u'合併失敗，交易已完整回復，原本的標註都還在。\n\n{}'.format(error),
            title=TITLE)
        return
    forms.alert(u'已建立 {} 條合併後的標註，刪除原本的 {} 個。'.format(
        created, removed), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
