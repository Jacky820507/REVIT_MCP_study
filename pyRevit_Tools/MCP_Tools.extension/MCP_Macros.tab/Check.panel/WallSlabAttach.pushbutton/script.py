# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""牆是否貼附樓板（JAC 06.05）— read-only.

Revit stores *that* a wall end is attached (``WALL_TOP_IS_ATTACHED``) but not
*what* it is attached to. The flag alone therefore cannot answer 「這面牆有沒有
貼到樓板」, and measuring the gap alone cannot either — a wall that happens to
stop exactly at the slab underside looks perfect until someone moves the slab.

So this reads both and reports the disagreements. The two rows worth the run:

* **未貼附但齊平** — correct today, silently broken tomorrow. Invisible in
  every view and every schedule.
* **已貼附但與最近樓板不齊平** — the flag says fine, the geometry says
  otherwise; usually attached to a roof or a slab two levels up.

Walls are sampled along the centreline, roughly one point per metre, because a
wall running past the edge of a slab is covered at one end and open at the
other. A single verdict per wall would have to lie about half of it.

Nothing is written. The only side effect offered is selecting the offenders.
"""

__title__ = u'牆是否\n貼附樓板'
__author__ = 'RevitMCP'

from Autodesk.Revit import DB
from pyrevit import forms, revit, script
from System.Collections.Generic import List

import wall_slab_attach_logic as logic


TITLE = u'牆是否貼附樓板'
MM_PER_FOOT = 304.8

SCOPE_CHOICES = (
    (u'整個專案', False),
    (u'只檢查目前視圖', True),
)

END_CHOICES = (
    (u'只檢查牆頂（預設）', (True, False)),
    (u'牆頂與牆底都檢查', (True, True)),
    (u'只檢查牆底', (False, True)),
)

# A wall can legitimately be attached to a roof or a ceiling, and calling that
# 「無樓板」 would bury the real findings in noise. Which categories count is
# therefore the user's call.
HOST_CHOICES = (
    (u'樓板 + 屋頂（預設）', ('OST_Floors', 'OST_Roofs')),
    (u'只有樓板', ('OST_Floors',)),
    (u'樓板 + 屋頂 + 天花板', ('OST_Floors', 'OST_Roofs', 'OST_Ceilings')),
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


def _pick(options, title):
    """SelectFromList single pick; returns the paired value, None on cancel."""
    labels = [label for label, unused in options]
    picked = forms.SelectFromList.show(labels, title=title, multiselect=False)
    if not picked:
        return None
    for label, value in options:
        if label == picked:
            return value
    return None


def _ask_number(prompt, default):
    raw = forms.ask_for_string(default=u'{:.0f}'.format(default),
                               prompt=prompt, title=TITLE)
    if not raw:
        return None
    try:
        value = float(raw.strip())
    except ValueError:
        forms.alert(u'請輸入數字。', title=TITLE)
        return None
    if value < 0:
        forms.alert(u'不能是負數。', title=TITLE)
        return None
    return value


def _built_in_parameter(element, name):
    built_in = getattr(DB.BuiltInParameter, name, None)
    if built_in is None:
        return None
    try:
        return element.get_Parameter(built_in)
    except Exception:
        return None


def _yes_no(element, name):
    """``True``/``False`` from a Yes/No parameter, ``None`` if unreadable."""
    parameter = _built_in_parameter(element, name)
    if parameter is None:
        return None
    try:
        return bool(parameter.AsInteger())
    except Exception:
        return None


def _box(element):
    try:
        return element.get_BoundingBox(None)
    except Exception:
        return None


def _collector(doc, view_only):
    if view_only:
        view = doc.ActiveView
        if view is None:
            return None
        return DB.FilteredElementCollector(doc, view.Id)
    return DB.FilteredElementCollector(doc)


def _walls(doc, view_only):
    collector = _collector(doc, view_only)
    if collector is None:
        return []
    try:
        return list(collector.OfClass(DB.Wall)
                    .WhereElementIsNotElementType()
                    .ToElements())
    except Exception:
        return []


def _slabs(doc, category_names):
    """Bounding boxes of everything a wall is allowed to be attached to.

    Always project-wide, even when the wall scope is one view. A floor plan
    does not show the slab *above* it, so scoping these to the view would
    report almost every wall as 「該側無樓板」 — the answer would be about the
    view's visibility settings rather than about the model.
    """
    records = []
    for name in category_names:
        category = getattr(DB.BuiltInCategory, name, None)
        if category is None:
            continue
        collector = _collector(doc, False)
        if collector is None:
            continue
        try:
            elements = list(collector.OfCategory(category)
                            .WhereElementIsNotElementType()
                            .ToElements())
        except Exception:
            continue
        for element in elements:
            box = _box(element)
            if box is None:
                continue
            try:
                label = element.Category.Name
            except Exception:
                label = name
            records.append({
                'id': _id_value(element.Id),
                'category': label,
                'min_x': float(box.Min.X) * MM_PER_FOOT,
                'min_y': float(box.Min.Y) * MM_PER_FOOT,
                'max_x': float(box.Max.X) * MM_PER_FOOT,
                'max_y': float(box.Max.Y) * MM_PER_FOOT,
                'bottom_z': float(box.Min.Z) * MM_PER_FOOT,
                'top_z': float(box.Max.Z) * MM_PER_FOOT,
            })
    return records


def _samples(wall, spacing_mm):
    """Plan points along the wall centreline, in mm."""
    try:
        location = wall.Location
        curve = location.Curve
    except Exception:
        curve = None
    if curve is None:
        box = _box(wall)
        if box is None:
            return []
        return [((float(box.Min.X) + float(box.Max.X)) * 0.5 * MM_PER_FOOT,
                 (float(box.Min.Y) + float(box.Max.Y)) * 0.5 * MM_PER_FOOT)]
    try:
        length_mm = float(curve.Length) * MM_PER_FOOT
    except Exception:
        length_mm = 0.0
    points = []
    for parameter in logic.sample_params(length_mm, spacing_mm):
        try:
            point = curve.Evaluate(parameter, True)
            points.append((float(point.X) * MM_PER_FOOT,
                           float(point.Y) * MM_PER_FOOT))
        except Exception:
            continue
    return points


def _wall_records(doc, walls, spacing_mm):
    records = []
    for wall in walls:
        box = _box(wall)
        try:
            is_curtain = wall.CurtainGrid is not None
        except Exception:
            is_curtain = False
        try:
            is_member = bool(wall.IsStackedWallMember)
        except Exception:
            is_member = False
        level_id = None
        parameter = _built_in_parameter(wall, 'WALL_BASE_CONSTRAINT')
        if parameter is not None:
            try:
                level_id = _id_value(parameter.AsElementId())
            except Exception:
                level_id = None
        level_name = u''
        if level_id and level_id > 0:
            try:
                level_name = _element_name(
                    doc.GetElement(DB.ElementId(int(level_id))))
            except Exception:
                level_name = u''
        records.append({
            'id': _id_value(wall.Id),
            'element_id': wall.Id,
            'name': _element_name(wall),
            'type_name': _element_name(doc.GetElement(wall.GetTypeId())),
            'level': level_name,
            'is_curtain': is_curtain,
            'is_stacked_member': is_member,
            'top_attached': _yes_no(wall, 'WALL_TOP_IS_ATTACHED'),
            'bottom_attached': _yes_no(wall, 'WALL_BOTTOM_IS_ATTACHED'),
            'top_z': float(box.Max.Z) * MM_PER_FOOT if box else None,
            'bottom_z': float(box.Min.Z) * MM_PER_FOOT if box else None,
            'samples': _samples(wall, spacing_mm),
        })
    return records


def _fmt(value):
    if value is None:
        return u''
    return u'{:+.0f}'.format(value)


def _print_report(result):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    options = result['options']
    output.print_md(
        u'齊平容差 **{:.0f} mm**；縫隙大於 **{:.0f} mm** 視為本來就不到頂的矮牆；'
        u'牆頂可穿入樓板 **{:.0f} mm** 內仍視為同一片板。'.format(
            options['flush_tol_mm'], options['ignore_gap_mm'],
            options['penetration_mm']))

    rows = []
    for item in result['rows']:
        for entry in item['ends']:
            if entry['state'] == logic.STATE_OK:
                continue
            rows.append([
                output.linkify(item['element_id']),
                item['level'] or u'(無樓層)',
                item['type_name'],
                entry['end_label'],
                u'○' if entry['attached'] else u'',
                entry['state'],
                _fmt(entry['worst_gap_mm']),
                u'{}/{}'.format(entry['covered'], entry['sample_count']),
                u'、'.join(entry['slab_categories']),
                u'；'.join(entry['flags']),
            ])
    if rows:
        output.print_md(u'### 需要注意的（已貼附且齊平者不列）')
        output.print_table(
            table_data=rows,
            columns=[u'Element ID', u'樓層', u'牆類型', u'端', u'已貼附',
                     u'判定', u'最大偏差(mm)', u'有板的取樣點', u'對到的類別',
                     u'備註'])

    if result['skipped']:
        output.print_md(u'### 略過的牆')
        output.print_table(
            table_data=[[output.linkify(row['record']['element_id']),
                         row['record']['type_name'], row['reason']]
                        for row in result['skipped'][:200]],
            columns=[u'Element ID', u'牆類型', u'原因'])

    output.print_md(
        u'牆以其外框上下緣代表，斜頂或編輯過輪廓的牆以最高／最低點判斷；'
        u'樓板同樣取外框，因此洩水或造型板會以其最低點比對。')


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行檢查。',
                    title=TITLE, exitscript=True)

    view_only = _pick(SCOPE_CHOICES, u'檢查範圍？')
    if view_only is None:
        return

    ends = _pick(END_CHOICES, u'檢查牆的哪一端？')
    if ends is None:
        return
    check_top, check_base = ends

    categories = _pick(HOST_CHOICES, u'哪些元素算是「樓板」？')
    if categories is None:
        return

    flush_tol = _ask_number(u'齊平容差 (mm)：偏差小於此值視為貼齊',
                            logic.DEFAULT_FLUSH_TOL_MM)
    if flush_tol is None:
        return
    ignore_gap = _ask_number(
        u'忽略縫隙上限 (mm)：縫隙大於此值視為矮牆／欄杆牆，不算缺失',
        logic.DEFAULT_IGNORE_GAP_MM)
    if ignore_gap is None:
        return

    walls = _walls(doc, view_only)
    if not walls:
        forms.alert(u'指定範圍內沒有牆。', title=TITLE)
        return

    slabs = _slabs(doc, categories)
    if not slabs:
        forms.alert(u'指定範圍內找不到任何樓板／屋頂／天花板，無法比對。\n\n'
                    u'若剛才選了「只檢查目前視圖」，請確認該視圖看得到樓板。',
                    title=TITLE)
        return

    records = _wall_records(doc, walls, logic.DEFAULT_SAMPLE_SPACING_MM)
    result = logic.analyze(records, slabs, {
        'check_top': check_top,
        'check_base': check_base,
        'flush_tol_mm': flush_tol,
        'ignore_gap_mm': ignore_gap,
    })
    _print_report(result)
    summary = logic.report_lines(result)

    if not result['flagged_ids']:
        forms.alert(u'{}\n\n明細已列在 pyRevit 輸出視窗。'.format(summary),
                    title=TITLE)
        return

    if forms.alert(
            u'{}\n\n明細已列在 pyRevit 輸出視窗。\n'
            u'要把有問題的牆選取起來嗎？'.format(summary),
            title=TITLE, yes=True, no=True):
        ids = List[DB.ElementId]()
        for value in result['flagged_ids']:
            ids.Add(DB.ElementId(int(value)))
        revit.uidoc.Selection.SetElementIds(ids)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
