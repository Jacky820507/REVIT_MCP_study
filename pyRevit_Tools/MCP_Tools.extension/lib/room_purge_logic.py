# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 自動清除房間 (JAC 04.11).

Rooms accumulate junk. A room whose bounding walls were deleted keeps existing
as an unenclosed element; a room dragged out of the model becomes 未放置. Both
still appear in every schedule, both still hold a 編號 and a 名稱, and neither
shows up anywhere in the drawings — so nobody notices until a 面積表 comes out
with rows that have no area.

Those two states are what 「未涵蓋房間」 means here and they are what the tool
selects by default. Everything else a person may want gone is offered but never
pre-selected.

Two rules shape the module.

**Redundant rooms are shown but never pre-selected.** Two rooms in one enclosed
region is a real defect, but which of the pair is the keeper is a question about
intent — the numbers and names differ, and picking one automatically would throw
away the right one half the time.

**Deleting a room destroys its 編號, 名稱 and every parameter on it** — finish
codes, 空間表 keys, everything. So the plan counts what carries data and the
caller is expected to offer a backup before committing.

State comes from Revit's own warning GUIDs where possible rather than from
guessing at geometry, and never from message text, which is localised.
"""


STATE_NOT_PLACED = u'未放置'
STATE_NOT_ENCLOSED = u'未封閉'
STATE_REDUNDANT = u'冗餘（同一區域有多個房間）'
STATE_OK = u'正常'

# 「未涵蓋」: the room bounds nothing, either because it was never placed or
# because whatever enclosed it is gone.
UNCOVERED_STATES = (STATE_NOT_PLACED, STATE_NOT_ENCLOSED)

STATE_ORDER = (
    STATE_NOT_PLACED,
    STATE_NOT_ENCLOSED,
    STATE_REDUNDANT,
    STATE_OK,
)

# Warning kinds the caller resolves from BuiltInFailures.RoomFailures GUIDs.
KIND_NOT_PLACED = 'not_placed'
KIND_NOT_ENCLOSED = 'not_enclosed'
KIND_REDUNDANT = 'redundant'

AREA_EPSILON_M2 = 1e-6

BACKUP_COLUMNS = (u'Element ID', u'編號', u'名稱', u'樓層',
                  u'面積(m²)', u'周長(m)', u'狀態')


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _number(value, fallback=0.0):
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _fold(value):
    """Case- and space-insensitive form, for the search box."""
    return u''.join(_text(value).split()).lower()


def classify(record):
    """The one state that decides how this room is offered.

    Order matters: an unplaced room also has no area, and reporting it as
    「未封閉」 would send someone hunting for a missing wall that never existed.
    """
    kinds = record.get('warning_kinds') or []
    if not record.get('is_placed', True) or KIND_NOT_PLACED in kinds:
        return STATE_NOT_PLACED
    if KIND_NOT_ENCLOSED in kinds:
        return STATE_NOT_ENCLOSED
    if _number(record.get('area_m2')) <= AREA_EPSILON_M2:
        return STATE_NOT_ENCLOSED
    if KIND_REDUNDANT in kinds:
        return STATE_REDUNDANT
    return STATE_OK


def describe(records):
    """Attach a state to every record without mutating the caller's dicts."""
    described = []
    for record in records or []:
        item = dict(record)
        item['state'] = classify(record)
        item['carries_data'] = bool(_text(record.get('number'))
                                    or _text(record.get('name')))
        described.append(item)
    return described


def default_selected_ids(records):
    """「未涵蓋房間」 — the default tick, and nothing else."""
    return [item['id'] for item in describe(records)
            if item['state'] in UNCOVERED_STATES]


def filter_rooms(records, states=None, query=u''):
    """Rows the window should show. Pure, so the filter box is testable.

    ``states`` of ``None`` means every state. ``query`` matches 編號 or 名稱,
    ignoring case and spacing.
    """
    wanted = set(states) if states else None
    needle = _fold(query)
    found = []
    for item in describe(records):
        if wanted is not None and item['state'] not in wanted:
            continue
        if needle and needle not in _fold(item.get('number')) \
                and needle not in _fold(item.get('name')):
            continue
        found.append(item)
    return found


def sort_key(item):
    return (STATE_ORDER.index(item.get('state', STATE_OK)),
            _text(item.get('level')),
            _text(item.get('number')),
            int(_number(item.get('id'))))


def build_plan(records, selected_ids):
    """What will actually be deleted, grouped so the preview is readable."""
    chosen = set(selected_ids or [])
    described = describe(records)

    delete = [item for item in described if item['id'] in chosen]
    delete.sort(key=sort_key)

    groups = []
    index = {}
    for item in delete:
        state = item['state']
        if state not in index:
            index[state] = {'state': state, 'records': []}
            groups.append(index[state])
        index[state]['records'].append(item)
    groups.sort(key=lambda group: STATE_ORDER.index(group['state']))

    named = [item for item in delete if item['carries_data']]
    normal = [item for item in delete if item['state'] == STATE_OK]

    return {
        'delete': delete,
        'groups': groups,
        'named': named,
        'normal': normal,
        'count': len(delete),
        'ids': [item['id'] for item in delete],
        'total_available': len(described),
    }


def has_work(plan):
    return bool(plan.get('delete'))


def backup_rows(plan):
    """Header plus one row per room about to be deleted."""
    rows = [list(BACKUP_COLUMNS)]
    for item in plan.get('delete') or []:
        rows.append([
            item.get('id'),
            _text(item.get('number')),
            _text(item.get('name')),
            _text(item.get('level')),
            _number(item.get('area_m2')),
            _number(item.get('perimeter_m')),
            item.get('state'),
        ])
    return rows


def backup_spec():
    return {
        'widths': [12, 14, 24, 14, 12, 12, 26],
        'freeze': 1,
        'formats': {},
    }


def plan_lines(plan):
    lines = []
    if not has_work(plan):
        lines.append(u'沒有選到任何房間，模型不會變更。')
        return u'\n'.join(lines)

    lines.append(u'將刪除 {} 個房間（模型中共 {} 個）：'.format(
        plan['count'], plan['total_available']))
    for group in plan['groups']:
        numbers = [_text(item.get('number')) or u'(無編號)'
                   for item in group['records']]
        shown = u'、'.join(numbers[:8])
        if len(numbers) > 8:
            shown += u' …等 {} 個'.format(len(numbers))
        lines.append(u'　{}：{} 個　{}'.format(
            group['state'], len(group['records']), shown))

    if plan['normal']:
        lines.append(u'')
        lines.append(u'⚠ 其中 {} 個是「正常」房間——它們有面積、也在圖上，'
                     u'請確認真的要刪。'.format(len(plan['normal'])))
    if plan['named']:
        lines.append(u'')
        lines.append(u'{} 個帶有編號或名稱，刪除後這些資料'
                     u'（含所有參數）會一併消失。'.format(len(plan['named'])))
    return u'\n'.join(lines)
