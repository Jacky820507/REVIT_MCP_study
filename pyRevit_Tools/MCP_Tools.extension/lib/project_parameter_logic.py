# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 專案參數移轉（可篩選）— JAC 11.04.

Moving project parameters between documents is not a copy. A ``Definition``
belongs to the document that owns it, so the target has to be given a *new*
definition that Revit recognises as the same parameter — which is only possible
for **shared** parameters, where the GUID is the identity.

That produces the one limitation worth stating loudly:

**Non-shared project parameters cannot be transferred.** The API offers no way
to create one in another document. They could be recreated as *shared*
parameters instead, but a shared parameter is a different thing — it can be
tagged, scheduled across families, and exported differently — so turning one
into the other behind the user's back would be a silent change of meaning. They
are reported as untransferable and left alone.

Everything else is filtering, which is what 「可篩選」 asks for: by name, by
category, and by whether the parameter binds to instances or to types. A
standards file carries hundreds of them and an unfiltered list is one nobody
reads.

Nothing here touches Revit.
"""


BINDING_INSTANCE = 'instance'
BINDING_TYPE = 'type'
BINDING_LABELS = {
    BINDING_INSTANCE: u'實體參數',
    BINDING_TYPE: u'類型參數',
}

BLOCK_NOT_SHARED = u'非共用參數，API 無法在其他檔案建立'
BLOCK_ALREADY_BOUND = u'目標已綁定同一個共用參數'
BLOCK_NAME_TAKEN = u'目標已有同名但不同 GUID 的參數'

BLOCK_ORDER = (BLOCK_NOT_SHARED, BLOCK_ALREADY_BOUND, BLOCK_NAME_TAKEN)

NO_CATEGORY = u'（未綁定品類）'


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _fold(value):
    return u''.join(_text(value).split()).lower()


def binding_label(kind):
    return BINDING_LABELS.get(kind, _text(kind))


def matches_keyword(record, keyword):
    """Every whitespace-separated term must appear — narrowing, not widening."""
    terms = [_fold(term) for term in _text(keyword).split()]
    terms = [term for term in terms if term]
    if not terms:
        return True
    haystack = (_fold(record.get('name')) + _fold(record.get('group'))
                + _fold(u''.join(record.get('categories') or [])))
    for term in terms:
        if term not in haystack:
            return False
    return True


def filter_parameters(records, keyword=u'', categories=None,
                      binding_kind=None):
    """Name / category / binding filters, all optional and combined with AND."""
    wanted = set(categories) if categories else None
    found = []
    for record in records or []:
        if not matches_keyword(record, keyword):
            continue
        if binding_kind and record.get('binding_kind') != binding_kind:
            continue
        if wanted is not None:
            names = set(record.get('categories') or [])
            if not (names & wanted):
                continue
        found.append(record)
    return found


def all_categories(records):
    """Every category any of these parameters binds to, for the filter list."""
    found = set()
    for record in records or []:
        for name in record.get('categories') or []:
            if _text(name):
                found.add(_text(name))
    return sorted(found)


def group_by_binding(records):
    """``[{'binding_kind', 'label', 'records'}]`` — instance and type differ."""
    groups = []
    for kind in (BINDING_INSTANCE, BINDING_TYPE):
        chosen = [record for record in records or []
                  if record.get('binding_kind') == kind]
        if chosen:
            groups.append({
                'binding_kind': kind,
                'label': binding_label(kind),
                'records': sorted(chosen,
                                  key=lambda item: _text(item.get('name'))),
            })
    other = [record for record in records or []
             if record.get('binding_kind') not in (BINDING_INSTANCE,
                                                   BINDING_TYPE)]
    if other:
        groups.append({'binding_kind': u'', 'label': u'（未知綁定）',
                       'records': other})
    return groups


def build_plan(records, selected_ids, destination_guids=None,
               destination_names=None):
    """Split the picked parameters into what transfers and what cannot."""
    chosen = set(selected_ids or [])
    bound = set(_fold(value) for value in destination_guids or [])
    taken = set(_fold(value) for value in destination_names or [])

    transfer = []
    blocked = []
    for record in records or []:
        if record.get('id') not in chosen:
            continue
        if not record.get('is_shared'):
            blocked.append({'record': record, 'reason': BLOCK_NOT_SHARED})
            continue
        if _fold(record.get('guid')) in bound:
            blocked.append({'record': record, 'reason': BLOCK_ALREADY_BOUND})
            continue
        if _fold(record.get('name')) in taken:
            # Same name, different GUID: inserting would leave two parameters
            # indistinguishable in every dialog the user ever sees.
            blocked.append({'record': record, 'reason': BLOCK_NAME_TAKEN})
            continue
        transfer.append(record)

    transfer.sort(key=lambda item: (_text(item.get('binding_kind')),
                                    _text(item.get('name'))))
    counts = {}
    for entry in blocked:
        counts[entry['reason']] = counts.get(entry['reason'], 0) + 1

    return {
        'transfer': transfer,
        'blocked': blocked,
        'block_counts': counts,
        'groups': group_by_binding(transfer),
        'count': len(transfer),
        'ids': [record.get('id') for record in transfer],
    }


def has_work(plan):
    return bool(plan.get('transfer'))


def plan_lines(plan, source_title=u'', destination_title=u''):
    lines = []
    if source_title or destination_title:
        lines.append(u'從「{}」移轉到「{}」'.format(
            source_title or u'(來源)', destination_title or u'(目前檔案)'))
        lines.append(u'')

    if not has_work(plan):
        lines.append(u'沒有可移轉的專案參數，模型不會變更。')
    else:
        lines.append(u'將移轉 {} 個專案參數：'.format(plan['count']))
        for group in plan['groups']:
            names = [_text(record.get('name'))
                     for record in group['records']]
            shown = u'、'.join(names[:6])
            if len(names) > 6:
                shown += u' …等 {} 個'.format(len(names))
            lines.append(u'　{}：{} 個　{}'.format(
                group['label'], len(group['records']), shown))

    if plan['blocked']:
        lines.append(u'')
        lines.append(u'略過 {} 個：'.format(len(plan['blocked'])))
        for reason in BLOCK_ORDER:
            count = plan['block_counts'].get(reason)
            if count:
                lines.append(u'　{}：{} 個'.format(reason, count))

    lines.append(u'')
    lines.append(u'只有共用參數能跨檔移轉——非共用的專案參數沒有 API 可以在'
                 u'其他檔案建立。把它們改建成共用參數會改變性質（可被標籤、'
                 u'可跨族群排程），因此本工具不代為轉換。')
    return u'\n'.join(lines)
