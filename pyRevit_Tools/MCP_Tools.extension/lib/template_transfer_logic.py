# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 樣板移轉 — JAC 11.02（先輸入關鍵字）／11.03（先選模型）.

The two JAC entries are one job entered from opposite ends: either you know the
template's name and want to find which standards file has it, or you know the
file and want to see what it offers. Both land on the same copy, so they are two
modes of one tool rather than two tools.

Two facts decide most of the behaviour here.

**A same-named template cannot be overwritten.** ``DuplicateTypeAction`` offers
only ``UseDestinationTypes`` or ``Abort`` — there is no replace. So a template
whose name already exists in the target is reported *before* anything is
copied, and the default is to skip it. Copying it anyway is allowed, but the
resulting name is then Revit's decision, not ours, and the preview says so
rather than promising a name it cannot guarantee.

**A template is bound to a view type.** A floor-plan template will not apply to
a section, so the picker groups by view type — a list of forty names with no
type beside them is one where the wrong pick is invisible until it fails.

Nothing here touches Revit.
"""


BLOCK_NAME_EXISTS = u'目標檔案已有同名樣板'

NO_TYPE = u'（未知類型）'


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _fold(value):
    """Case- and space-insensitive form, for keyword matching."""
    return u''.join(_text(value).split()).lower()


def matches_keyword(record, keyword):
    """Does this template match the search box?

    Every whitespace-separated term must appear, so 「立面 彩現」 narrows rather
    than widens — a single-substring search over a standards file with two
    hundred templates returns too much to read.
    """
    terms = [_fold(term) for term in _text(keyword).split()]
    terms = [term for term in terms if term]
    if not terms:
        return True
    haystack = _fold(record.get('name')) + _fold(record.get('view_type'))
    for term in terms:
        if term not in haystack:
            return False
    return True


def filter_templates(records, keyword=u''):
    return [record for record in records or []
            if matches_keyword(record, keyword)]


def group_by_view_type(records):
    """``[{'view_type', 'records'}]`` — a template only applies to its own type."""
    buckets = {}
    order = []
    for record in records or []:
        key = _text(record.get('view_type')) or NO_TYPE
        if key not in buckets:
            buckets[key] = {'view_type': key, 'records': []}
            order.append(key)
        for entry in (buckets[key],):
            entry['records'].append(record)
    groups = [buckets[key] for key in sorted(order)]
    for group in groups:
        group['records'] = sorted(group['records'],
                                  key=lambda item: _text(item.get('name')))
    return groups


def build_plan(records, selected_ids, destination_names,
               skip_existing=True):
    """Split the picked templates into what copies and what does not."""
    chosen = set(selected_ids or [])
    existing = set(_fold(name) for name in destination_names or [])

    copy = []
    blocked = []
    renamed = []
    for record in records or []:
        if record.get('id') not in chosen:
            continue
        if _fold(record.get('name')) in existing:
            if skip_existing:
                blocked.append({'record': record,
                                'reason': BLOCK_NAME_EXISTS})
                continue
            # Copied anyway: Revit decides the resulting name, so it is listed
            # apart from the clean copies rather than counted with them.
            renamed.append(record)
        copy.append(record)

    copy.sort(key=lambda item: (_text(item.get('view_type')),
                                _text(item.get('name'))))
    return {
        'copy': copy,
        'blocked': blocked,
        'renamed': renamed,
        'groups': group_by_view_type(copy),
        'count': len(copy),
        'ids': [record.get('id') for record in copy],
        'skip_existing': bool(skip_existing),
    }


def has_work(plan):
    return bool(plan.get('copy'))


def plan_lines(plan, source_title=u'', destination_title=u''):
    lines = []
    if source_title or destination_title:
        lines.append(u'從「{}」複製到「{}」'.format(
            source_title or u'(來源)', destination_title or u'(目前檔案)'))
        lines.append(u'')

    if not has_work(plan):
        lines.append(u'沒有要複製的樣板，模型不會變更。')
    else:
        lines.append(u'將複製 {} 個視圖樣板：'.format(plan['count']))
        for group in plan['groups']:
            names = [_text(record.get('name')) for record in group['records']]
            shown = u'、'.join(names[:6])
            if len(names) > 6:
                shown += u' …等 {} 個'.format(len(names))
            lines.append(u'　{}：{} 個　{}'.format(
                group['view_type'], len(group['records']), shown))

    if plan['renamed']:
        lines.append(u'')
        lines.append(u'其中 {} 個在目標檔案已有同名樣板，仍會複製，'
                     u'但**新樣板的名稱由 Revit 決定**（通常會加後綴）：'
                     .format(len(plan['renamed'])))
        for record in plan['renamed'][:6]:
            lines.append(u'　{}'.format(_text(record.get('name'))))

    if plan['blocked']:
        lines.append(u'')
        lines.append(u'略過 {} 個（目標已有同名，且選了不覆蓋）：'.format(
            len(plan['blocked'])))
        for entry in plan['blocked'][:6]:
            lines.append(u'　{}'.format(_text(entry['record'].get('name'))))
        if len(plan['blocked']) > 6:
            lines.append(u'　…（其餘 {} 個見輸出視窗）'.format(
                len(plan['blocked']) - 6))

    lines.append(u'')
    lines.append(u'視圖樣板無法被覆寫——Revit 的複製只提供「沿用目標既有」'
                 u'或「中止」，沒有取代。要換掉舊樣板請先改名或刪除。')
    return u'\n'.join(lines)
