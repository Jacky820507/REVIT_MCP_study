# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 更改剖刀＆立面標記（多張）— JAC 07.04.

The graphics of a 剖刀 come from the section's **type**: the head symbol, the
tail, the line weight all hang off the ``ViewFamilyType``. Same for an
elevation marker, whose symbol is its ``ElementType``. Changing either is one
dropdown in Type Properties — and Revit gives you no way to do it to forty
sections at once, so a drawing set that has drifted onto three different section
types gets fixed by hand, one property palette at a time.

The whole job is therefore ``Element.ChangeTypeId``. What this module adds is
the part that stops it going wrong halfway.

**The target list is the intersection of what every selected element accepts.**
``GetValidTypes()`` differs per element — a detail-family section will not take
a building-section type. Offering the union and discovering that on element 27
of 40 means a rolled-back transaction and a user who does not know which ones
were the problem. Intersecting up front means every offered type is one that
will work for the whole batch.

**Elements already on the target type are separated, not counted.** Reporting
「已更改 40 個」 when 12 were already correct overstates what happened, and the
next person cannot tell whether the tool worked.

Nothing here touches Revit; the caller supplies plain dicts.
"""


KIND_SECTION = 'section'
KIND_ELEV_MARKER = 'elevation_marker'
KIND_ELEV_VIEW = 'elevation_view'

KIND_LABELS = {
    KIND_SECTION: u'剖面圖（剖刀）',
    KIND_ELEV_MARKER: u'立面標記',
    KIND_ELEV_VIEW: u'立面圖',
}

BLOCK_SAME_TYPE = u'已經是目標類型'
BLOCK_INVALID = u'該元素不接受這個類型'

NO_TYPE = u'（無類型）'


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def kind_label(kind):
    return KIND_LABELS.get(kind, _text(kind))


def valid_type_intersection(records):
    """Type ids every one of these elements will accept, order preserved.

    Order comes from the first record so the picker is stable between runs;
    sorting by id would reshuffle the list whenever the model changes.
    """
    items = [record for record in records or []]
    if not items:
        return []
    ordered = []
    for type_id in items[0].get('valid_type_ids') or []:
        if type_id not in ordered:
            ordered.append(type_id)
    for record in items[1:]:
        allowed = set(record.get('valid_type_ids') or [])
        ordered = [type_id for type_id in ordered if type_id in allowed]
        if not ordered:
            break
    return ordered


def group_by_current_type(records):
    """``[{'type_id','type_name','records'}]`` — the shape people select in.

    A drawing set drifts one type at a time, so 「把目前是 A 的那些改成 B」 is
    the actual request nearly every time.
    """
    buckets = {}
    order = []
    for record in records or []:
        key = record.get('type_id')
        if key not in buckets:
            buckets[key] = {
                'type_id': key,
                'type_name': _text(record.get('type_name')) or NO_TYPE,
                'records': [],
            }
            order.append(key)
        buckets[key]['records'].append(record)
    groups = [buckets[key] for key in order]
    groups.sort(key=lambda group: group['type_name'])
    return groups


def build_plan(records, target_type_id, target_type_name=u''):
    """Split the selection into what changes, what is already right, and
    what Revit would refuse."""
    change = []
    blocked = []
    for record in records or []:
        if record.get('type_id') == target_type_id:
            blocked.append({'record': record, 'reason': BLOCK_SAME_TYPE})
            continue
        allowed = record.get('valid_type_ids') or []
        if target_type_id not in allowed:
            blocked.append({'record': record, 'reason': BLOCK_INVALID})
            continue
        change.append(record)

    change.sort(key=lambda record: (_text(record.get('type_name')),
                                    _text(record.get('sort_label'))
                                    or _text(record.get('label'))))

    return {
        'change': change,
        'blocked': blocked,
        'groups': group_by_current_type(change),
        'target_type_id': target_type_id,
        'target_type_name': _text(target_type_name),
        'count': len(change),
        'ids': [record.get('id') for record in change],
    }


def has_work(plan):
    return bool(plan.get('change'))


def plan_lines(plan):
    lines = []
    if not has_work(plan):
        lines.append(u'沒有需要更改的項目。')
    else:
        lines.append(u'將把 {} 個項目改成「{}」：'.format(
            plan['count'], plan['target_type_name'] or NO_TYPE))
        for group in plan['groups']:
            labels = [_text(record.get('label')) or u'(未命名)'
                      for record in group['records']]
            shown = u'、'.join(labels[:6])
            if len(labels) > 6:
                shown += u' …等 {} 個'.format(len(labels))
            lines.append(u'　目前「{}」：{} 個　{}'.format(
                group['type_name'], len(group['records']), shown))

    if plan['blocked']:
        counts = {}
        for entry in plan['blocked']:
            counts[entry['reason']] = counts.get(entry['reason'], 0) + 1
        lines.append(u'')
        lines.append(u'略過 {} 個：'.format(len(plan['blocked'])))
        for reason in sorted(counts):
            lines.append(u'　{}：{} 個'.format(reason, counts[reason]))
    return u'\n'.join(lines)
