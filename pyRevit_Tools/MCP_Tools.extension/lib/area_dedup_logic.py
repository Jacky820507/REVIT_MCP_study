# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 清除重複的區域及區域線 — JAC 04.13.

The boundary-line half already exists as
:func:`area_boundary_regen_logic.plan_dedup`; this module is the other half —
**duplicate Areas**, meaning two or more Areas occupying one enclosed region.
Revit reports those itself as ``RoomsInSameRegionAreas``, so detection is not
guesswork. Choosing which one to delete is.

**A group's keeper is a question about intent, and the tool only answers it
when the answer is not a choice.** If exactly one Area in a region carries a
number or a name and the rest are blank, the one with data is obviously the
one somebody made — that is a fact, not a preference. If two carry data, they
are two different records of the same space and deleting either loses
something, so the group is returned undecided and nobody's work is thrown
away by default.

**Where nothing carries data the keeper is the lowest element id.** Arbitrary,
but *stable*: re-running finds nothing left to do rather than churning a
different survivor every pass.

Nothing here touches Revit.
"""


KEEP_ONLY_WITH_DATA = u'群組中只有這一個有編號或名稱'
KEEP_LOWEST_ID = u'群組中都沒有編號或名稱，保留 id 最小者'

UNDECIDED_MANY_WITH_DATA = u'群組中有多個帶編號或名稱，無法代為選擇'
UNDECIDED_TOO_FEW = u'群組不足兩個面積'


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _number(value, fallback=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def carries_data(record):
    """Does this Area hold anything a person typed?"""
    return bool(_text(record.get('number')) or _text(record.get('name')))


def resolve_group(records):
    """Decide one region's keeper.

    Returns ``(keeper, deletes, reason)``; ``keeper`` is ``None`` when the
    choice belongs to a human, and ``deletes`` is then empty — an undecided
    group must never lose an element.
    """
    items = [record for record in records or []]
    if len(items) < 2:
        return None, [], UNDECIDED_TOO_FEW

    ordered = sorted(items, key=lambda item: _number(item.get('id')))
    with_data = [item for item in ordered if carries_data(item)]

    if len(with_data) == 1:
        keeper = with_data[0]
        return (keeper,
                [item for item in ordered if item is not keeper],
                KEEP_ONLY_WITH_DATA)

    if len(with_data) > 1:
        return None, [], UNDECIDED_MANY_WITH_DATA

    keeper = ordered[0]
    return keeper, ordered[1:], KEEP_LOWEST_ID


def build_plan(groups):
    """Resolve every duplicate-area group.

    ``groups`` is a list of lists of area records, one list per enclosed
    region, exactly as Revit's own warning reports them.
    """
    resolved = []
    undecided = []
    delete_ids = []

    for records in groups or []:
        keeper, deletes, reason = resolve_group(records)
        entry = {
            'records': list(records or []),
            'keeper': keeper,
            'deletes': deletes,
            'reason': reason,
        }
        if keeper is None:
            undecided.append(entry)
            continue
        resolved.append(entry)
        delete_ids.extend([item.get('id') for item in deletes])

    return {
        'resolved': resolved,
        'undecided': undecided,
        'delete_ids': delete_ids,
        'group_count': len(resolved) + len(undecided),
        'delete_count': len(delete_ids),
    }


def has_work(plan):
    return bool(plan.get('delete_ids'))


def plan_lines(plan, line_delete_count=0):
    lines = []
    total = plan['group_count']
    if not total:
        lines.append(u'沒有偵測到位於同一封閉區域的重複面積。')
    else:
        lines.append(u'重複面積群組：{} 組'.format(total))

    if plan['resolved']:
        lines.append(u'')
        lines.append(u'將刪除 {} 個重複面積（保留每組一個）：'.format(
            plan['delete_count']))
        for entry in plan['resolved'][:8]:
            keeper = entry['keeper']
            lines.append(u'　保留 {}／{}　刪除 {} 個　（{}）'.format(
                _text(keeper.get('number')) or u'(無編號)',
                _text(keeper.get('name')) or u'(無名稱)',
                len(entry['deletes']), entry['reason']))
        if len(plan['resolved']) > 8:
            lines.append(u'　…（其餘 {} 組見輸出視窗）'.format(
                len(plan['resolved']) - 8))

    if plan['undecided']:
        lines.append(u'')
        lines.append(u'需人工判定 {} 組（不會刪除任何一個）：'.format(
            len(plan['undecided'])))
        for entry in plan['undecided'][:8]:
            names = [u'{}／{}'.format(
                _text(item.get('number')) or u'(無編號)',
                _text(item.get('name')) or u'(無名稱)')
                for item in entry['records']]
            lines.append(u'　{}　→　{}'.format(entry['reason'],
                                               u'、'.join(names)))
        if len(plan['undecided']) > 8:
            lines.append(u'　…（其餘 {} 組見輸出視窗）'.format(
                len(plan['undecided']) - 8))

    if line_delete_count:
        lines.append(u'')
        lines.append(u'另會刪除 {} 條重複的區域線。'.format(line_delete_count))

    lines.append(u'')
    lines.append(u'刪除面積會連同其編號、名稱與分類參數一起消失。'
                 u'同一區域有多個帶資料的面積時一律不代為選擇——'
                 u'那是兩份不同的紀錄，刪掉哪一個都會失去東西。')
    return u'\n'.join(lines)
