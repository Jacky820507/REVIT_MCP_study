# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 清除區域線及區域（多視圖）— JAC 04.07 / 04.12.

This is the only purely destructive tool in the set: nothing is rebuilt
afterwards, so the preview is the only chance to notice a mistake. Two things
therefore matter more here than in the tools that create something.

**Counts across views are not additive.** An area belongs to a scheme and a
level, not to a view, so two area plans over the same scheme and level show the
*same* areas and the same boundary lines. Adding the per-view numbers would
tell someone they are deleting 200 elements when the model only contains 100 —
and the moment they see the real number afterwards, they stop trusting the
tool. Every count here is over deduplicated element ids, and the per-view
figures are labelled as what that view shows rather than what it contributes.

**What is lost is worth naming.** Deleting an Area discards its 編號, 名稱 and
any classification parameters with it; the boundary lines are just geometry.
The plan keeps the areas' identifying fields so the caller can export them
before committing.
"""


TARGET_LINES = 'lines'
TARGET_AREAS = 'areas'
TARGET_BOTH = 'both'

TARGET_LABELS = {
    TARGET_LINES: u'只清除區域線',
    TARGET_AREAS: u'只清除面積',
    TARGET_BOTH: u'區域線與面積都清除',
}

BLOCK_NOT_AREA_PLAN = u'不是面積平面圖'
BLOCK_EMPTY = u'這個視圖沒有可清除的東西'


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _ids(values):
    """Ordered unique ids; order is kept so a rerun deletes in the same order."""
    seen = []
    for value in values or []:
        if value is None:
            continue
        if value not in seen:
            seen.append(value)
    return seen


def build_plan(views, target=TARGET_BOTH):
    """Work out the deduplicated set of elements the selected views cover.

    ``views`` is ``[{view_id, view_label, scheme, level, line_ids, area_ids,
    areas}]``. ``areas`` carries the identifying fields worth exporting before
    they are gone.
    """
    if target not in TARGET_LABELS:
        raise ValueError('unknown target: {}'.format(target))

    want_lines = target in (TARGET_LINES, TARGET_BOTH)
    want_areas = target in (TARGET_AREAS, TARGET_BOTH)

    rows = []
    blocked = []
    line_ids = []
    area_ids = []
    areas = []
    seen_area_ids = set()

    for view in views or []:
        if not view.get('is_area_plan', True):
            blocked.append({'record': view, 'reason': BLOCK_NOT_AREA_PLAN})
            continue
        view_lines = _ids(view.get('line_ids')) if want_lines else []
        view_areas = _ids(view.get('area_ids')) if want_areas else []
        if not view_lines and not view_areas:
            blocked.append({'record': view, 'reason': BLOCK_EMPTY})
            continue

        # What this view adds that no earlier view already covered. Reported
        # separately from "shows", because the two differ whenever two plans
        # sit over the same scheme and level.
        new_lines = [value for value in view_lines if value not in line_ids]
        new_areas = [value for value in view_areas if value not in area_ids]

        rows.append({
            'view': view,
            'view_label': _text(view.get('view_label')),
            'scheme': _text(view.get('scheme')),
            'level': _text(view.get('level')),
            'shows_lines': len(view_lines),
            'shows_areas': len(view_areas),
            'adds_lines': len(new_lines),
            'adds_areas': len(new_areas),
        })

        line_ids.extend(new_lines)
        area_ids.extend(new_areas)
        for area in view.get('areas') or []:
            key = area.get('id')
            if key in seen_area_ids or key not in view_areas:
                continue
            seen_area_ids.add(key)
            areas.append(area)

    duplicated = any(row['shows_lines'] != row['adds_lines']
                     or row['shows_areas'] != row['adds_areas']
                     for row in rows)

    return {
        'target': target,
        'views': rows,
        'blocked': blocked,
        'line_ids': line_ids,
        'area_ids': area_ids,
        'areas': areas,
        'line_count': len(line_ids),
        'area_count': len(area_ids),
        'has_overlap': duplicated,
    }


def delete_ids(plan):
    """Everything to remove. Areas first: a line still bounding an area is
    what Revit complains about, and removing the areas first keeps the run
    quiet."""
    return list(plan['area_ids']) + list(plan['line_ids'])


def has_work(plan):
    return bool(plan['line_ids']) or bool(plan['area_ids'])


def numbered_areas(plan):
    """Areas carrying a 編號 or 名稱 — the ones whose loss is not just geometry."""
    rows = []
    for area in plan['areas']:
        if _text(area.get('number')) or _text(area.get('name')):
            rows.append(area)
    return rows


def plan_lines(plan):
    lines = [
        u'清除範圍：{}'.format(TARGET_LABELS.get(plan['target'],
                                            plan['target'])),
        u'選定視圖：{} 個'.format(len(plan['views'])),
        u'',
    ]
    if not has_work(plan):
        lines.append(u'沒有可清除的項目。')
        return u'\n'.join(lines)

    lines.append(u'將刪除區域線 {} 條、面積 {} 個（已扣除重複）'.format(
        plan['line_count'], plan['area_count']))
    if plan['has_overlap']:
        lines.append(u'')
        lines.append(
            u'※ 有視圖看到的是同一批元素（同一面積計畫的同一樓層可能有多個'
            u'平面圖），上面的數字已去除重複，不是各視圖相加。')

    named = numbered_areas(plan)
    if named:
        lines.append(u'')
        lines.append(
            u'※ 其中 {} 個面積帶有編號或名稱，刪除後這些資料不會留下。'.format(
                len(named)))
        for area in named[:8]:
            lines.append(u'　{}　{}'.format(
                _text(area.get('number')) or u'(無編號)',
                _text(area.get('name'))))
        if len(named) > 8:
            lines.append(u'　…（其餘 {} 個見輸出視窗）'.format(len(named) - 8))

    if plan['blocked']:
        lines.append(u'')
        counts = {}
        for row in plan['blocked']:
            counts[row['reason']] = counts.get(row['reason'], 0) + 1
        lines.append(u'略過的視圖：')
        for reason in sorted(counts, key=lambda key: -counts[key]):
            lines.append(u'　{}：{} 個'.format(reason, counts[reason]))
    return u'\n'.join(lines)
