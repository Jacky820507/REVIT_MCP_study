# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 專有共用、面積類型分類 — JAC 04.05.

Method and citations live in ``domain/exclusive-shared-area-classification.md``;
this module implements them. Three of its rules shape everything here.

**共用 is the complement of 專有, not a list.** 公寓大廈管理條例 §3 defines
共用部分 as 「專有部分**以外**之其他部分…而供共同使用者」. So the classifier
decides 專有 and lets everything else fall to 共用 — matching a "shared space
keyword list" would be running the definition backwards, and one missing entry
would misclassify silently.

**約定專用 and 約定共用 can never be derived.** Both definitions contain
「經**約定**」. Agreement lives in the 規約, not the model. This module will not
produce those values under any input; they exist as constants only so a human
can assign them.

**The classification is a suggestion, never a finding.** 專有 turns on
「使用上之獨立性」 and 「區分所有之標的」 — a room called 儲藏室 may be either.
So every row carries the keyword that triggered it, and rows nothing matched
are returned as 待確認 rather than pushed into a bucket.

大公／小公 is not statutory. It is a sales-and-公設比 convention, tagged as such.
"""


OWNERSHIP_EXCLUSIVE = u'專有'
OWNERSHIP_SHARED = u'共用'
OWNERSHIP_UNDECIDED = u'待確認'

# Present so a person can pick them; never produced by classify().
OWNERSHIP_AGREED_EXCLUSIVE = u'約定專用'
OWNERSHIP_AGREED_SHARED = u'約定共用'

OWNERSHIP_VALUES = (
    OWNERSHIP_EXCLUSIVE,
    OWNERSHIP_SHARED,
    OWNERSHIP_AGREED_EXCLUSIVE,
    OWNERSHIP_AGREED_SHARED,
    OWNERSHIP_UNDECIDED,
)

# Only 約定* require an agreement; these are the two this tool may suggest.
SUGGESTABLE = (OWNERSHIP_EXCLUSIVE, OWNERSHIP_SHARED)

SCOPE_WHOLE = u'大公'
SCOPE_FLOOR = u'小公'
SCOPE_NONE = u''

# Names that indicate a space is 區分所有之標的 — a saleable unit. 共用 is
# whatever is left, per §3, so only this side is listed.
DEFAULT_EXCLUSIVE_KEYWORDS = (
    u'客廳', u'餐廳', u'臥室', u'主臥', u'書房', u'廚房', u'浴室', u'衛浴',
    u'更衣', u'儲藏', u'工作陽台', u'陽台', u'露台', u'店舖', u'店面',
    u'辦公', u'住戶', u'套房', u'單元',
)

# Shared spaces serving the whole building rather than one floor. Not
# statutory — 大公／小公 is a 公設比 convention.
DEFAULT_WHOLE_BUILDING_KEYWORDS = (
    u'屋突', u'屋頂突出物', u'machine', u'機房', u'機電', u'發電機',
    u'配電', u'受電', u'蓄水池', u'水箱', u'消防', u'管理室', u'管委會',
    u'垃圾', u'公共廁所',
)

DEFAULT_FLOOR_KEYWORDS = (
    u'電梯', u'梯廳', u'樓梯', u'走廊', u'走道', u'通道', u'前室',
)

DISCLAIMER = (
    u'本分類為依名稱關鍵字提出之「建議」，非法律認定。專有／共用之最終認定'
    u'依區分所有權登記與規約；約定專用、約定共用依其約定，無法由模型判定。'
)


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _fold(value):
    return u''.join(_text(value).split()).lower()


def matched_keyword(name, keywords):
    """The *longest* keyword found in the name, or ``''``.

    Longest rather than first, so the answer never depends on how the list was
    ordered — the keyword lists are meant to be edited per project, and a user
    reordering their own list should not change what the tool decides.
    「主臥室」 reports 主臥, not 臥室.
    """
    haystack = _fold(name)
    if not haystack:
        return u''
    best = u''
    for keyword in keywords or ():
        folded = _fold(keyword)
        if folded and folded in haystack and len(folded) > len(_fold(best)):
            best = keyword
    return best


def classify(record, exclusive_keywords=None, whole_keywords=None,
             floor_keywords=None):
    """Suggest 專有／共用 and 大公／小公 for one area.

    Returns ``(ownership, scope, reason)``. Ownership is only ever one of
    :data:`SUGGESTABLE` or :data:`OWNERSHIP_UNDECIDED` — 約定專用/約定共用
    require an agreement and are never inferred.
    """
    exclusive_keywords = (DEFAULT_EXCLUSIVE_KEYWORDS
                          if exclusive_keywords is None
                          else exclusive_keywords)
    whole_keywords = (DEFAULT_WHOLE_BUILDING_KEYWORDS
                      if whole_keywords is None else whole_keywords)
    floor_keywords = (DEFAULT_FLOOR_KEYWORDS if floor_keywords is None
                      else floor_keywords)

    name = _text(record.get('name'))
    if not name:
        return OWNERSHIP_UNDECIDED, SCOPE_NONE, u'面積沒有名稱，無從判斷'

    hit = matched_keyword(name, exclusive_keywords)
    if hit:
        return (OWNERSHIP_EXCLUSIVE, SCOPE_NONE,
                u'名稱含「{}」，屬區分所有之標的'.format(hit))

    whole = matched_keyword(name, whole_keywords)
    if whole:
        return (OWNERSHIP_SHARED, SCOPE_WHOLE,
                u'名稱含「{}」，服務全棟'.format(whole))

    floor = matched_keyword(name, floor_keywords)
    if floor:
        return (OWNERSHIP_SHARED, SCOPE_FLOOR,
                u'名稱含「{}」，服務單層'.format(floor))

    # §3 makes 共用 the complement of 專有, but "no keyword matched" is not
    # evidence of anything — saying 共用 here would dress a miss as a finding.
    return (OWNERSHIP_UNDECIDED, SCOPE_NONE,
            u'名稱未命中任何關鍵字，需人工判定')


def describe(records, exclusive_keywords=None, whole_keywords=None,
             floor_keywords=None):
    """Attach a suggestion to every area without mutating the caller's dicts."""
    described = []
    for record in records or []:
        ownership, scope, reason = classify(
            record, exclusive_keywords, whole_keywords, floor_keywords)
        item = dict(record)
        item['suggested'] = ownership
        item['suggested_scope'] = scope
        item['reason'] = reason
        item['has_existing'] = bool(_text(record.get('current')))
        described.append(item)
    return described


def build_plan(records, overwrite=False, exclusive_keywords=None,
               whole_keywords=None, floor_keywords=None):
    """Split areas into what will be written, kept, and left for a human."""
    described = describe(records, exclusive_keywords, whole_keywords,
                         floor_keywords)

    write = []
    kept = []
    undecided = []
    for item in described:
        if item['suggested'] == OWNERSHIP_UNDECIDED:
            undecided.append(item)
            continue
        if item['has_existing'] and not overwrite:
            # An existing value is usually a human's decision, which beats a
            # keyword match.
            kept.append(item)
            continue
        if item['has_existing'] and _text(item.get('current')) == \
                item['suggested']:
            kept.append(item)
            continue
        write.append(item)

    counts = {}
    for item in write:
        counts[item['suggested']] = counts.get(item['suggested'], 0) + 1

    scope_counts = {}
    for item in write:
        if item['suggested_scope']:
            scope_counts[item['suggested_scope']] = scope_counts.get(
                item['suggested_scope'], 0) + 1

    return {
        'write': write,
        'kept': kept,
        'undecided': undecided,
        'counts': counts,
        'scope_counts': scope_counts,
        'overwrite': bool(overwrite),
        'count': len(write),
        'ids': [item.get('id') for item in write],
        'total': len(described),
    }


def has_work(plan):
    return bool(plan.get('write'))


def plan_lines(plan, parameter_name=u'', scope_parameter=u''):
    lines = []
    if parameter_name:
        lines.append(u'寫入參數：{}{}'.format(
            parameter_name,
            u'（大公／小公寫入 {}）'.format(scope_parameter)
            if scope_parameter else u''))
        lines.append(u'')

    if not has_work(plan):
        lines.append(u'沒有要寫入的面積，模型不會變更。')
    else:
        lines.append(u'將寫入 {} 個面積（共 {} 個）：'.format(
            plan['count'], plan['total']))
        for value in SUGGESTABLE:
            count = plan['counts'].get(value)
            if count:
                lines.append(u'　{}：{} 個'.format(value, count))
        for value in (SCOPE_WHOLE, SCOPE_FLOOR):
            count = plan['scope_counts'].get(value)
            if count:
                lines.append(u'　　其中 {}：{} 個'.format(value, count))

    if plan['kept']:
        lines.append(u'')
        lines.append(u'保留原值 {} 個{}。'.format(
            len(plan['kept']),
            u'' if plan['overwrite'] else u'（未選覆寫；既有值多半是人工判定過的）'))

    if plan['undecided']:
        lines.append(u'')
        lines.append(u'需人工判定 {} 個（名稱未命中關鍵字）：'.format(
            len(plan['undecided'])))
        for item in plan['undecided'][:8]:
            lines.append(u'　{}　{}'.format(
                _text(item.get('number')) or u'(無編號)',
                _text(item.get('name')) or u'(無名稱)'))
        if len(plan['undecided']) > 8:
            lines.append(u'　…（其餘 {} 個見輸出視窗）'.format(
                len(plan['undecided']) - 8))

    lines.append(u'')
    lines.append(DISCLAIMER)
    return u'\n'.join(lines)
