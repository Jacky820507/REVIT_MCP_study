# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""群組高度檢查（JAC 06.03）— read-only.

A model group instance sits where two parameters put it: ``GROUP_LEVEL`` and
``GROUP_OFFSET_FROM_LEVEL``. When a 標準層 group is copied up a tower, every
instance is meant to sit the same way on its own floor — and when one offset
drifts, that unit floats above its slab with nothing in Revit complaining.

So the check compares instances of the same group type against each other
rather than against a number this button invents; the offset most of them
share is treated as the intended one. It also reports each group's vertical
extent, and flags content that pokes above the level overhead.

Nothing is written. The only side effect offered is selecting the offenders.
"""

__title__ = u'群組高度\n檢查'
__author__ = 'RevitMCP'

from Autodesk.Revit import DB
from pyrevit import forms, revit, script
from System.Collections.Generic import List

import group_height_logic as logic
import mcp_window as ui
import mcp_window_logic as uilogic


TITLE = u'群組高度檢查'
MM_PER_FOOT = 304.8
ZERO_CHOICES = (
    (u'只比對同型群組之間是否一致（建議）', False),
    (u'另外把「偏移不為 0」也列為問題', True),
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


def _levels(doc):
    found = list(DB.FilteredElementCollector(doc)
                 .OfClass(DB.Level)
                 .WhereElementIsNotElementType()
                 .ToElements())
    found.sort(key=lambda level: level.Elevation)
    return found


def _level_table(doc):
    """``{level_id: (name, elevation_mm, next_elevation_mm)}``.

    The level above is what decides whether a group's content pokes through the
    slab overhead, so it is resolved once here rather than per group.
    """
    table = {}
    levels = _levels(doc)
    for index, level in enumerate(levels):
        try:
            elevation = float(level.Elevation) * MM_PER_FOOT
        except Exception:
            elevation = 0.0
        following = None
        if index + 1 < len(levels):
            try:
                following = float(levels[index + 1].Elevation) * MM_PER_FOOT
            except Exception:
                following = None
        table[_id_value(level.Id)] = (_element_name(level), elevation,
                                      following)
    return table


def _group_level_id(group):
    """The level a group belongs to — ``GROUP_LEVEL`` first, then ``LevelId``."""
    parameter = _built_in_parameter(group, 'GROUP_LEVEL')
    if parameter is not None:
        try:
            value = _id_value(parameter.AsElementId())
            if value > 0:
                return value
        except Exception:
            pass
    try:
        return _id_value(group.LevelId)
    except Exception:
        return -1


def _group_offset_mm(group):
    parameter = _built_in_parameter(group, 'GROUP_OFFSET_FROM_LEVEL')
    if parameter is None:
        return 0.0
    try:
        return float(parameter.AsDouble()) * MM_PER_FOOT
    except Exception:
        return 0.0


def _extent_mm(group):
    """``(bottom_mm, top_mm)`` of the group's content, or ``(None, None)``."""
    try:
        box = group.get_BoundingBox(None)
    except Exception:
        box = None
    if box is None:
        return None, None
    try:
        return (float(box.Min.Z) * MM_PER_FOOT,
                float(box.Max.Z) * MM_PER_FOOT)
    except Exception:
        return None, None


def _collect(doc, allowed_level_ids, levels):
    """Placed model groups. Detail groups are excluded — they have no height."""
    records = []
    category = getattr(DB.BuiltInCategory, 'OST_IOSModelGroups', None)
    if category is None:
        return records
    try:
        collector = (DB.FilteredElementCollector(doc)
                     .OfCategory(category)
                     .WhereElementIsNotElementType())
    except Exception:
        return records
    for group in collector:
        # Attached detail groups come back through the same collector on some
        # models; they hang off a parent and carry no independent height.
        try:
            if group.IsAttached:
                continue
        except Exception:
            pass
        level_id = _group_level_id(group)
        if allowed_level_ids is not None and level_id not in allowed_level_ids:
            continue
        name, elevation, following = levels.get(level_id,
                                                (u'', 0.0, None))
        bottom, top = _extent_mm(group)
        try:
            group_type = group.GroupType
        except Exception:
            group_type = None
        try:
            members = len(list(group.GetMemberIds()))
        except Exception:
            members = 0
        records.append({
            'id': _id_value(group.Id),
            'element_id': group.Id,
            'type_id': _id_value(group_type.Id) if group_type is not None
            else -1,
            'type_name': _element_name(group_type),
            'level_id': level_id,
            'level': name,
            'level_elevation_mm': elevation,
            'next_level_elevation_mm': following,
            'offset_mm': _group_offset_mm(group),
            'bottom_mm': bottom,
            'top_mm': top,
            'member_count': members,
        })
    return records


def _build_spec(levels):
    """整份規格。樓層一個都不勾＝全部，原本的 ALL_LEVELS 假選項不再需要。"""
    level_options = sorted(
        [(entry[0], level_id) for level_id, entry in levels.items()],
        key=lambda item: levels[item[1]][1])

    fields = [
        uilogic.section(u'檢查範圍'),
        uilogic.multichoice('levels', u'樓層（不勾就是全部）', level_options,
                            help=u'一個都不勾代表全部樓層。'),

        uilogic.section(u'判定'),
        uilogic.choice('flag_nonzero', u'偏移不為 0 算不算問題', ZERO_CHOICES,
                       default=False,
                       help=u'有些樣板刻意把每個實例放在固定偏移上，'
                            u'那是合理的做法；所以這是專案決定而不是常數。'),
        uilogic.number('tolerance', u'偏移比對容差',
                       default=logic.DEFAULT_TOLERANCE_MM, minimum=0.001,
                       unit=u'mm',
                       help=u'小於此值視為相同偏移。'),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'找出同型群組裡偏移或內容高度和多數不一致的那幾個',
        badge=uilogic.BADGE_READONLY,
        run_label=u'開始檢查',
        secondary_label=u'選取有問題的群組',
        footnote=u'唯讀。完整明細列在 pyRevit 輸出視窗，可點擊跳到元素。',
        width=980, height=700)


def _fmt(value):
    if value is None:
        return u''
    return u'{:.0f}'.format(value)


def _print_table(report):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    output.print_md(u'偏移比對容差 **{:.0f} mm**；同型群組互相比對，'
                    u'多數的偏移視為正確值。'.format(report['tolerance_mm']))
    rows = []
    for item in report['rows']:
        rows.append([
            output.linkify(item['element_id']),
            item['type_name'],
            item['level'] or u'(無樓層)',
            _fmt(item['offset_mm']),
            _fmt(item['expected_offset_mm']),
            _fmt(item['relative_bottom_mm']),
            _fmt(item['relative_top_mm']),
            _fmt(item['content_height_mm']),
            u'{}'.format(item['member_count']),
            u'；'.join(item['flags']),
        ])
    output.print_table(
        table_data=rows,
        columns=[u'Element ID', u'群組型別', u'樓層', u'偏移(mm)',
                 u'同型多數(mm)', u'內容底(mm)', u'內容頂(mm)',
                 u'內容高度(mm)', u'成員數', u'問題'])


class _Runner(object):
    """留住最後一次的報告，關窗後才知道要不要選取那些群組。"""

    def __init__(self, doc, levels):
        self.doc = doc
        self.levels = levels
        self.report = None

    def __call__(self, values, window):
        allowed = set(values.get('levels') or ()) or None
        records = _collect(self.doc, allowed, self.levels)
        if not records:
            self.report = None
            window.status(u'指定範圍內沒有已放置的模型群組。', 'warning')
            return None

        report = logic.analyze(records,
                               flag_nonzero=values['flag_nonzero'],
                               tolerance_mm=values['tolerance'])
        self.report = report
        _print_table(report)
        summary = logic.report_lines(report)
        window.status(summary,
                      'danger' if report['flagged_ids'] else 'success')

        rows = []
        for item in report['rows']:
            if not item['flags']:
                continue
            rows.append([
                item['type_name'], item['level'],
                _fmt(item['offset_mm']), _fmt(item['expected_offset_mm']),
                _fmt(item['content_height_mm']),
                u'{}'.format(item['member_count']),
                u'；'.join(item['flags']),
            ])
        return uilogic.result(
            summary_lines=[summary],
            columns=[u'群組型別', u'樓層', u'偏移(mm)', u'同型多數(mm)',
                     u'內容高度(mm)', u'成員數', u'問題'],
            rows=rows)


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行群組高度檢查。',
                    title=TITLE, exitscript=True)

    levels = _level_table(doc)
    runner = _Runner(doc, levels)
    values, unused = ui.run(_build_spec(levels), runner)
    if values is None or runner.report is None:
        return

    if values.get('__secondary__') and runner.report['flagged_ids']:
        ids = List[DB.ElementId]()
        for value in runner.report['flagged_ids']:
            ids.Add(DB.ElementId(int(value)))
        revit.uidoc.Selection.SetElementIds(ids)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
